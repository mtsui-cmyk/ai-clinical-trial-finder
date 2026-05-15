#!/usr/bin/env python3
"""QA cached AI rewrites for safety, structure, and source-grounding signals."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


REQUIRED_KEYS = [
    "patient_title",
    "patient_summary",
    "what_researchers_are_studying",
    "may_be_looking_for",
    "may_exclude_people_who",
    "questions_to_ask_clinician",
    "uncertainty_notes",
    "source_grounding",
]

LIST_KEYS = [
    "may_be_looking_for",
    "may_exclude_people_who",
    "questions_to_ask_clinician",
    "uncertainty_notes",
    "source_grounding",
]

PROHIBITED_PATTERNS = [
    (r"\byou are eligible\b", "eligibility decision"),
    (r"\byou qualify\b", "eligibility decision"),
    (r"\byou should join\b", "trial recommendation"),
    (r"\bshould join\b", "trial recommendation"),
    (r"\brecommended treatment\b", "treatment recommendation"),
    (r"\bbest treatment\b", "treatment ranking"),
    (r"\bsafest\b", "safety ranking"),
    (r"\bmost effective\b", "effectiveness ranking"),
    (r"\bam i eligible\b", "first-person eligibility question"),
    (r"\bcould i join\b", "first-person trial-joining question"),
    (r"\bshould i join\b", "first-person trial-joining question"),
    (r"\bmy ability\b", "first-person medical/work ability framing"),
    (r"\bmy condition\b", "first-person condition framing"),
]

SOFT_WARN_PATTERNS = [
    (r"\beffective\b", "effectiveness wording"),
    (r"\bsafe\b", "safety wording"),
    (r"\bbenefit\b", "benefit wording"),
    (r"\beligible\b", "eligibility wording"),
]


def main() -> int:
    parser = argparse.ArgumentParser(description="QA AI rewrite cache files.")
    parser.add_argument("--cache-dir", required=True, help="Directory containing AI rewrite JSON files.")
    parser.add_argument("--out", required=True, help="Markdown QA report path.")
    parser.add_argument("--fix", action="store_true", help="Apply conservative local sanitization before reporting.")
    args = parser.parse_args()

    cache_dir = Path(args.cache_dir)
    records = []
    for path in sorted(cache_dir.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        if args.fix:
            changed = sanitize_payload(data)
            if changed:
                path.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        records.append((path, data, qa_record(data)))

    report = render_report(cache_dir, records)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(report, encoding="utf-8")

    failures = sum(1 for _, _, result in records if result["errors"])
    warnings = sum(len(result["warnings"]) for _, _, result in records)
    print(f"AI QA checked {len(records)} files. failures={failures}, warnings={warnings}. Report: {out_path}")
    return 1 if failures else 0


def qa_record(data: dict[str, Any]) -> dict[str, Any]:
    errors = []
    warnings = []
    missing = [key for key in REQUIRED_KEYS if key not in data]
    if missing:
        errors.append(f"Missing required keys: {', '.join(missing)}")
    for key in LIST_KEYS:
        if key in data and not isinstance(data[key], list):
            errors.append(f"`{key}` should be a list.")
    if not str(data.get("patient_summary", "")).strip():
        errors.append("Empty patient_summary.")
    if not data.get("source_grounding"):
        warnings.append("No source_grounding entries.")

    text = flatten_text(data).lower()
    for pattern, label in PROHIBITED_PATTERNS:
        if re.search(pattern, text):
            errors.append(f"Prohibited wording: {label} / `{pattern}`")
    for pattern, label in SOFT_WARN_PATTERNS:
        if re.search(pattern, text):
            warnings.append(f"Review wording: {label} / `{pattern}`")
    return {"errors": errors, "warnings": warnings}


def flatten_text(value: Any) -> str:
    if isinstance(value, dict):
        return " ".join(flatten_text(item) for item in value.values())
    if isinstance(value, list):
        return " ".join(flatten_text(item) for item in value)
    return str(value or "")


def sanitize_payload(data: dict[str, Any]) -> bool:
    changed = False
    replacements = {
        "Am I eligible": "What factors would a clinician or study team review for eligibility",
        "am I eligible": "what factors would a clinician or study team review for eligibility",
        "Could I join": "What factors would a clinician or study team review before someone contacts a study team",
        "could I join": "what factors would a clinician or study team review before someone contacts a study team",
        "Should I join": "What should someone discuss with a clinician before contacting a study team",
        "should I join": "what should someone discuss with a clinician before contacting a study team",
        "my ability": "a person's ability",
        "my condition": "a person's condition",
        "your disease": "the condition",
        "could safely use estrogen replacement therapy": "was studied for safety questions about estrogen replacement therapy",
        "can safely use estrogen": "is being studied for safety questions about estrogen use",
        "could safely use": "was studied for safety questions about",
        "can safely use": "is being studied for safety questions about",
        "could treat": "was being studied for",
        "fewer side effects than": "different side-effect questions compared with",
        "if postmenopausal women with lupus (systemic lupus erythematosus) was studied for safety questions about estrogen replacement therapy": "safety questions about estrogen replacement therapy in postmenopausal women with lupus (systemic lupus erythematosus)",
        "whether women with systemic lupus erythematosus (SLE or lupus) is being studied for safety questions about estrogen": "safety questions about estrogen use in women with systemic lupus erythematosus (SLE or lupus)",
        "You should": "A person could discuss with a clinician whether to",
        "you should": "a person could discuss with a clinician whether to",
        "best treatment": "treatment option",
        "recommended treatment": "described treatment",
        "effectiveness": "study outcomes",
        "effective": "associated with the study outcome",
    }
    for key in REQUIRED_KEYS:
        if key not in data:
            data[key] = [] if key in LIST_KEYS else ""
            changed = True
    for key in LIST_KEYS:
        value = data.get(key)
        if isinstance(value, str):
            data[key] = [value] if value.strip() else []
            changed = True
        elif value is None:
            data[key] = []
            changed = True
    for key in ["patient_title", "patient_summary", "what_researchers_are_studying"]:
        new_value, did_change = sanitize_text(str(data.get(key, "")), replacements)
        data[key] = new_value
        changed = changed or did_change
    for key in LIST_KEYS:
        safe_items = []
        for item in data.get(key, []):
            new_value, did_change = sanitize_text(str(item), replacements)
            safe_items.append(new_value)
            changed = changed or did_change
        data[key] = safe_items
    return changed


def sanitize_text(text: str, replacements: dict[str, str]) -> tuple[str, bool]:
    changed = False
    for needle, replacement in replacements.items():
        if needle in text:
            text = text.replace(needle, replacement)
            changed = True
    return text, changed


def render_report(cache_dir: Path, records: list[tuple[Path, dict[str, Any], dict[str, Any]]]) -> str:
    failures = [(path, data, result) for path, data, result in records if result["errors"]]
    warnings = [(path, data, result) for path, data, result in records if result["warnings"]]
    lines = [
        "# DeepSeek Rewrite QA",
        "",
        f"Cache directory: `{cache_dir}`",
        f"Files checked: {len(records)}",
        f"Failures: {len(failures)}",
        f"Records with warnings: {len(warnings)}",
        "",
        "## Summary",
        "",
        "- PASS: no prohibited clinical recommendations, ranking, or eligibility decisions detected." if not failures else "- FAIL: prohibited or malformed output detected.",
        "- Warnings are review prompts, not automatic failures.",
        "",
    ]
    lines.extend(["## Failures", ""])
    if failures:
        for path, data, result in failures:
            lines.append(f"### {path.name}")
            for error in result["errors"]:
                lines.append(f"- {error}")
            lines.append("")
    else:
        lines.append("No failures detected.")
        lines.append("")

    lines.extend(["## Warnings", ""])
    if warnings:
        for path, data, result in warnings:
            trial_id = data.get("_meta", {}).get("trial_id", path.stem)
            lines.append(f"### {trial_id}")
            lines.append(f"- Title: {data.get('patient_title', '')}")
            for warning in result["warnings"][:8]:
                lines.append(f"- {warning}")
            lines.append("")
    else:
        lines.append("No warnings detected.")
        lines.append("")

    lines.extend(["## Sample Outputs", ""])
    for path, data, result in records[:10]:
        trial_id = data.get("_meta", {}).get("trial_id", path.stem)
        lines.append(f"### {trial_id}")
        lines.append("")
        lines.append(f"**Patient title:** {data.get('patient_title', '')}")
        lines.append("")
        lines.append(f"**Summary:** {data.get('patient_summary', '')}")
        lines.append("")
        if data.get("may_be_looking_for"):
            lines.append("**May be looking for:**")
            for item in data["may_be_looking_for"][:3]:
                lines.append(f"- {item}")
            lines.append("")
        if data.get("may_exclude_people_who"):
            lines.append("**May exclude people who:**")
            for item in data["may_exclude_people_who"][:3]:
                lines.append(f"- {item}")
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
