#!/usr/bin/env python3
"""Run optional source-grounded AI rewrites for trial records.

This script is intentionally separate from the main data pipeline. The static
site can be regenerated without an API key, while AI rewrites can be produced
and cached when the operator explicitly opts in.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"
DEEPSEEK_CHAT_URL = "https://api.deepseek.com/chat/completions"


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate source-grounded patient rewrite cache.")
    parser.add_argument("--prompts", required=True, help="Path to rewrite_prompts.jsonl.")
    parser.add_argument("--out", required=True, help="Output cache directory.")
    parser.add_argument("--provider", choices=["openai", "deepseek"], default=os.environ.get("AI_PROVIDER", "openai"))
    parser.add_argument("--model", help="Model name. Defaults depend on --provider.")
    parser.add_argument("--env-file", default=".env.local", help="Optional local env file for API keys.")
    parser.add_argument("--limit", type=int, default=0, help="Optional maximum prompts to process.")
    parser.add_argument("--retries", type=int, default=3, help="Retries per prompt for transient API failures.")
    parser.add_argument("--continue-on-error", action="store_true", help="Record failed prompt errors and continue.")
    parser.add_argument("--sleep", type=float, default=0.2, help="Delay between API requests.")
    parser.add_argument("--dry-run", action="store_true", help="Validate prompt loading without calling the API.")
    args = parser.parse_args()
    load_env_file(Path(args.env_file))

    prompts = load_jsonl(Path(args.prompts), args.limit)
    output_dir = Path(args.out)
    output_dir.mkdir(parents=True, exist_ok=True)

    if args.dry_run:
        model = resolve_model(args.provider, args.model)
        print(f"Loaded {len(prompts)} prompts for provider={args.provider}, model={model}. Dry run only; no API calls made.")
        return 0

    model = resolve_model(args.provider, args.model)
    api_key = resolve_api_key(args.provider)

    written = 0
    for prompt in prompts:
        trial_id = prompt["trial_id"]
        cache_path = output_dir / f"{trial_id}.json"
        if cache_path.exists():
            continue
        try:
            result = call_with_retries(args.provider, api_key=api_key, model=model, prompt=prompt, retries=args.retries)
        except Exception as exc:  # noqa: BLE001 - CLI can continue over provider-specific bad responses.
            if not args.continue_on_error:
                raise
            write_error(output_dir / "_errors.jsonl", prompt, exc)
            print(f"Skipped {trial_id}: {exc}", file=sys.stderr)
            continue
        write_json(cache_path, result)
        written += 1
        time.sleep(args.sleep)

    print(f"Wrote {written} {args.provider} rewrite cache files to {output_dir}.")
    return 0


def write_error(path: Path, prompt: dict[str, Any], exc: Exception) -> None:
    payload = {
        "trial_id": prompt.get("trial_id"),
        "cache_key": prompt.get("cache_key"),
        "error": str(exc),
    }
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")


def call_with_retries(provider: str, api_key: str, model: str, prompt: dict[str, Any], retries: int) -> dict[str, Any]:
    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            if provider == "deepseek":
                return call_deepseek_rewrite(api_key=api_key, model=model, prompt=prompt)
            return call_openai_rewrite(api_key=api_key, model=model, prompt=prompt)
        except Exception as exc:  # noqa: BLE001 - CLI should retry provider/network oddities.
            last_error = exc
            if attempt < retries:
                time.sleep(min(2 ** attempt, 8))
    raise RuntimeError(f"Could not rewrite {prompt.get('trial_id')} after {retries} attempts: {last_error}") from last_error


def resolve_model(provider: str, model: str | None) -> str:
    if model:
        return model
    if provider == "deepseek":
        return os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-flash")
    return os.environ.get("OPENAI_MODEL", "gpt-5.2")


def resolve_api_key(provider: str) -> str:
    env_name = "DEEPSEEK_API_KEY" if provider == "deepseek" else "OPENAI_API_KEY"
    api_key = os.environ.get(env_name)
    if not api_key:
        raise RuntimeError(f"{env_name} is required unless --dry-run is used.")
    return api_key


def load_jsonl(path: Path, limit: int) -> list[dict[str, Any]]:
    rows = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                rows.append(json.loads(line))
            if limit and len(rows) >= limit:
                break
    return rows


def load_env_file(path: Path) -> None:
    if not path.exists():
        return
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key, value = stripped.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value


def call_openai_rewrite(api_key: str, model: str, prompt: dict[str, Any]) -> dict[str, Any]:
    body = {
        "model": model,
        "input": build_prompt_text(prompt),
        "text": {
            "format": {
                "type": "json_schema",
                "name": "patient_trial_rewrite",
                "strict": True,
                "schema": rewrite_schema(),
            }
        },
    }
    request = urllib.request.Request(
        OPENAI_RESPONSES_URL,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"OpenAI API error {exc.code}: {detail[:1000]}") from exc

    text = extract_output_text(payload)
    parsed = json.loads(text)
    parsed = normalize_rewrite_payload(parsed)
    sanitize_rewrite_payload(parsed)
    parsed["_meta"] = {
        "trial_id": prompt["trial_id"],
        "cache_key": prompt["cache_key"],
        "model": model,
        "source": "openai_responses_api",
    }
    return parsed


def call_deepseek_rewrite(api_key: str, model: str, prompt: dict[str, Any]) -> dict[str, Any]:
    body = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You rewrite public clinical-trial registry fields into patient-friendly educational JSON. "
                    "Use only the supplied source fields. Never decide eligibility, recommend treatment, rank drugs, "
                    "or claim safety/effectiveness."
                ),
            },
            {"role": "user", "content": build_prompt_text(prompt)},
        ],
        "response_format": {"type": "json_object"},
        "max_tokens": 2500,
        "stream": False,
    }
    request = urllib.request.Request(
        DEEPSEEK_CHAT_URL,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"DeepSeek API error {exc.code}: {detail[:1000]}") from exc

    text = extract_chat_message_content(payload, "DeepSeek")
    parsed = json.loads(text)
    parsed = normalize_rewrite_payload(parsed)
    sanitize_rewrite_payload(parsed)
    validate_rewrite_payload(parsed)
    parsed["_meta"] = {
        "trial_id": prompt["trial_id"],
        "cache_key": prompt["cache_key"],
        "model": model,
        "source": "deepseek_chat_completions_api",
    }
    return parsed


def build_prompt_text(prompt: dict[str, Any]) -> str:
    return (
        "Rewrite public clinical-trial registry fields into patient-friendly educational text and return valid json.\n"
        "Use only the supplied source fields. Do not decide eligibility, recommend treatment, rank drugs, "
        "or claim safety/effectiveness. Use careful language such as 'may be looking for'.\n\n"
        "Do not write first-person eligibility questions such as 'Am I eligible?' or 'Could I join?'. "
        "Instead ask what factors a clinician or study team would need to review.\n\n"
        "Return exactly this JSON object shape with all keys present:\n"
        "{\n"
        '  "patient_title": "string",\n'
        '  "patient_summary": "string",\n'
        '  "what_researchers_are_studying": "string",\n'
        '  "may_be_looking_for": ["string"],\n'
        '  "may_exclude_people_who": ["string"],\n'
        '  "questions_to_ask_clinician": ["string"],\n'
        '  "uncertainty_notes": ["string"],\n'
        '  "source_grounding": ["string"]\n'
        "}\n\n"
        f"Hard rules:\n{json.dumps(prompt['hard_rules'], ensure_ascii=False)}\n\n"
        f"Source fields:\n{json.dumps(prompt['source_fields'], ensure_ascii=False, indent=2)}"
    )


def rewrite_schema() -> dict[str, Any]:
    string_array = {"type": "array", "items": {"type": "string"}}
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "patient_title",
            "patient_summary",
            "what_researchers_are_studying",
            "may_be_looking_for",
            "may_exclude_people_who",
            "questions_to_ask_clinician",
            "uncertainty_notes",
            "source_grounding",
        ],
        "properties": {
            "patient_title": {"type": "string"},
            "patient_summary": {"type": "string"},
            "what_researchers_are_studying": {"type": "string"},
            "may_be_looking_for": string_array,
            "may_exclude_people_who": string_array,
            "questions_to_ask_clinician": string_array,
            "uncertainty_notes": string_array,
            "source_grounding": string_array,
        },
    }


def extract_output_text(payload: dict[str, Any]) -> str:
    if payload.get("output_text"):
        return payload["output_text"]
    chunks = []
    for item in payload.get("output", []):
        for content in item.get("content", []):
            if content.get("type") in {"output_text", "text"} and content.get("text"):
                chunks.append(content["text"])
    if not chunks:
        raise RuntimeError("Could not find text output in OpenAI response.")
    return "".join(chunks)


def extract_chat_message_content(payload: dict[str, Any], provider_name: str) -> str:
    choices = payload.get("choices") or []
    if not choices:
        raise RuntimeError(f"{provider_name} response had no choices.")
    message = choices[0].get("message") or {}
    content = message.get("content")
    if not content:
        raise RuntimeError(f"{provider_name} response had empty content.")
    return content


def validate_rewrite_payload(payload: dict[str, Any]) -> None:
    required = set(rewrite_schema()["required"])
    missing = sorted(required - set(payload))
    if missing:
        raise RuntimeError(f"AI rewrite payload missing keys: {', '.join(missing)}")
    for key in ["may_be_looking_for", "may_exclude_people_who", "questions_to_ask_clinician", "uncertainty_notes", "source_grounding"]:
        if not isinstance(payload.get(key), list):
            raise RuntimeError(f"AI rewrite payload key {key} must be a list.")


def normalize_rewrite_payload(payload: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(payload)
    for key in ["patient_title", "patient_summary", "what_researchers_are_studying"]:
        if normalized.get(key) is None:
            normalized[key] = ""
        elif not isinstance(normalized.get(key), str):
            normalized[key] = json.dumps(normalized[key], ensure_ascii=False)
    for key in ["may_be_looking_for", "may_exclude_people_who", "questions_to_ask_clinician", "uncertainty_notes", "source_grounding"]:
        value = normalized.get(key)
        if value is None:
            normalized[key] = []
        elif isinstance(value, str):
            normalized[key] = [value] if value.strip() else []
        elif isinstance(value, list):
            normalized[key] = [str(item) for item in value if str(item).strip()]
        else:
            normalized[key] = [json.dumps(value, ensure_ascii=False)]
    return normalized


def sanitize_rewrite_payload(payload: dict[str, Any]) -> None:
    replacements = {
        "am i potentially eligible for similar vocational rehabilitation services?": "What factors would a clinician or study team review before someone contacts a similar service or study?",
        "am i eligible": "What factors would a clinician or study team review for eligibility?",
        "could i join": "What factors would a clinician or study team review before someone considers contacting a study team?",
        "should i join": "What questions should someone discuss with a clinician before contacting a study team?",
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
        "whether women with systemic lupus erythematosus (sle or lupus) is being studied for safety questions about estrogen": "safety questions about estrogen use in women with systemic lupus erythematosus (SLE or lupus)",
    }
    for key in ["patient_summary", "what_researchers_are_studying"]:
        value = payload.get(key, "")
        if isinstance(value, str):
            payload[key] = strip_recommendation_language(value)
    for key in ["questions_to_ask_clinician", "uncertainty_notes", "may_be_looking_for", "may_exclude_people_who"]:
        safe_items = []
        for item in payload.get(key, []):
            text = strip_recommendation_language(str(item))
            lowered = text.lower().strip()
            replaced = False
            for needle, replacement in replacements.items():
                if needle in lowered:
                    safe_items.append(replacement)
                    replaced = True
                    break
            if not replaced:
                safe_items.append(text)
        payload[key] = safe_items


def strip_recommendation_language(text: str) -> str:
    text = text.replace("you should", "a person could discuss with a clinician whether to")
    text = text.replace("You should", "A person could discuss with a clinician whether to")
    text = text.replace("recommended", "described")
    text = text.replace("best treatment", "treatment option")
    text = text.replace("effectiveness", "study outcomes")
    text = text.replace("effective", "associated with the study outcome")
    return text


def write_json(path: Path, data: Any) -> None:
    with path.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")


if __name__ == "__main__":
    sys.exit(main())
