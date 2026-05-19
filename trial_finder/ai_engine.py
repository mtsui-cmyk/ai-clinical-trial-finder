"""Source-grounded AI reading aid for public trial records.

The MVP uses a deterministic local engine so the browser never needs an AI
provider key. Provider-backed implementations can use the prompt contract here
and store reviewed outputs in cache.
"""

from __future__ import annotations

from typing import Any


AI_READING_CONTRACT = {
    "role": "source_grounded_trial_reader",
    "allowed": [
        "summarize public registry fields",
        "explain research terms in plain language",
        "highlight official registry fields to verify",
        "draft questions to discuss with a licensed clinician",
    ],
    "disallowed": [
        "recommend a trial",
        "decide whether a person is eligible",
        "rank treatments by safety or effectiveness",
        "infer facts not present in public registry fields",
        "use personal health data",
    ],
    "output_schema": {
        "mode": "string",
        "summary": "string",
        "signals": ["string"],
        "questions": ["string"],
        "safety_note": "string",
        "prompt_contract": "object",
    },
}


def build_trial_reading_prompt(trial: dict[str, Any]) -> dict[str, Any]:
    """Build the provider-agnostic prompt payload for an AI trial reader."""
    nearest = trial.get("nearest_location") or {}
    return {
        "task": "Explain this public clinical trial registry record as a patient-facing reading aid.",
        "hard_rules": AI_READING_CONTRACT["disallowed"],
        "allowed_outputs": AI_READING_CONTRACT["allowed"],
        "expected_schema": AI_READING_CONTRACT["output_schema"],
        "source_fields": {
            "trial_id": trial.get("trial_id"),
            "title": trial.get("title"),
            "status": trial.get("status"),
            "phase": trial.get("phase"),
            "conditions": trial.get("conditions", []),
            "interventions": trial.get("intervention_names", []),
            "sponsor": trial.get("sponsor"),
            "nearest_site": {
                "facility": nearest.get("facility"),
                "city": nearest.get("city"),
                "state": nearest.get("state"),
                "country": nearest.get("country"),
                "status": nearest.get("status"),
                "distance_km": nearest.get("distance_km"),
            },
            "eligibility_excerpt": (trial.get("eligibility") or {}).get("criteria_excerpt", ""),
            "official_registry_url": trial.get("source_url"),
        },
    }


def build_ai_reading(trial: dict[str, Any]) -> dict[str, Any]:
    """Return a safe reading aid from public registry fields.

    This is intentionally deterministic for the open-source MVP. It gives the
    app a real AI-engine boundary while avoiding browser-side secrets and
    uncontrolled medical claims.
    """
    prompt = build_trial_reading_prompt(trial)
    fields = prompt["source_fields"]
    nearest = fields["nearest_site"]
    status = _title(fields.get("status") or "status not listed")
    phase = fields.get("phase") or "phase not listed"
    focus = ", ".join(fields.get("conditions")[:2]) if fields.get("conditions") else "the searched condition"
    interventions = fields.get("interventions") or []
    intervention_text = ", ".join(interventions[:3]) if interventions else "interventions not listed in the normalized view"
    site_text = ", ".join(str(part) for part in [nearest.get("facility"), nearest.get("city"), nearest.get("country")] if part) or "the listed site"
    site_status = _title(nearest.get("status") or "site status not listed")

    return {
        "mode": "Source-grounded AI reading aid",
        "summary": f"{status} {phase} public registry record for {focus}. Nearest listed site: {site_text} ({site_status}).",
        "signals": [
            f"Research area: {intervention_text}.",
            "Verify current recruiting status, site contact details, and inclusion/exclusion text in the official registry.",
            "Use this as research context only; it does not determine eligibility.",
        ],
        "questions": _questions(trial),
        "safety_note": "AI may explain public registry fields, but must not recommend a trial or decide eligibility.",
        "prompt_contract": {
            "role": AI_READING_CONTRACT["role"],
            "source_fields_only": True,
            "provider": "local_deterministic_mvp",
        },
    }


def _questions(trial: dict[str, Any]) -> list[str]:
    existing = [item for item in trial.get("questions_to_ask", []) if item]
    fallback = [
        "What is the main question this study is trying to answer?",
        "How would this study relate to my diagnosis and current treatment history?",
        "If I am interested, what should I ask my clinician before contacting a study site?",
    ]
    return (existing or fallback)[:3]


def _title(value: str) -> str:
    return str(value).replace("_", " ").title()
