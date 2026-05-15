"""Small local condition suggestion layer for patient-friendly search."""

from __future__ import annotations


CONDITION_ALIASES: tuple[dict[str, object], ...] = (
    {
        "label": "Systemic lupus erythematosus",
        "query": "systemic lupus erythematosus",
        "aliases": ["lupus", "sle", "systemic lupus"],
    },
    {
        "label": "Lupus nephritis",
        "query": "lupus nephritis",
        "aliases": ["ln", "kidney lupus", "renal lupus"],
    },
    {
        "label": "Multiple sclerosis",
        "query": "multiple sclerosis",
        "aliases": ["ms"],
    },
    {
        "label": "Rheumatoid arthritis",
        "query": "rheumatoid arthritis",
        "aliases": ["ra"],
    },
    {
        "label": "Inflammatory bowel disease",
        "query": "inflammatory bowel disease",
        "aliases": ["ibd", "crohn's disease", "ulcerative colitis"],
    },
    {
        "label": "Psoriasis",
        "query": "psoriasis",
        "aliases": ["plaque psoriasis"],
    },
    {
        "label": "Myasthenia gravis",
        "query": "myasthenia gravis",
        "aliases": ["mg"],
    },
    {
        "label": "Breast cancer",
        "query": "breast cancer",
        "aliases": ["breast carcinoma"],
    },
    {
        "label": "Lung cancer",
        "query": "lung cancer",
        "aliases": ["non-small cell lung cancer", "nsclc", "small cell lung cancer"],
    },
)


def suggest_conditions(query: str, limit: int = 8) -> list[dict[str, object]]:
    needle = (query or "").strip().lower()
    if not needle:
        entries = CONDITION_ALIASES[:limit]
    else:
        scored = []
        for entry in CONDITION_ALIASES:
            haystack = [str(entry["label"]), str(entry["query"]), *[str(alias) for alias in entry.get("aliases", [])]]
            lowered = [value.lower() for value in haystack]
            if any(value == needle for value in lowered):
                scored.append((0, entry))
            elif any(value.startswith(needle) for value in lowered):
                scored.append((1, entry))
            elif any(needle in value for value in lowered):
                scored.append((2, entry))
        entries = [entry for _, entry in sorted(scored, key=lambda item: (item[0], str(item[1]["label"])))[:limit]]

    return [
        {
            "label": entry["label"],
            "condition_text": entry["query"],
            "aliases": entry.get("aliases", []),
            "source": "local_aliases",
        }
        for entry in entries
    ]

