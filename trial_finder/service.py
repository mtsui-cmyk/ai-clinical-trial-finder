"""FastAPI application for the on-demand clinical trial finder."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

try:
    from fastapi import FastAPI, HTTPException
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.staticfiles import StaticFiles
    from pydantic import BaseModel, Field
except ImportError as exc:  # pragma: no cover - exercised only when dependencies are missing.
    raise RuntimeError(
        "FastAPI runtime dependencies are missing. Install with `python3 -m pip install -r requirements.txt`."
    ) from exc

from trial_finder.cache import FinderCache
from trial_finder.clinicaltrials_gov import (
    DEFAULT_STATUSES,
    fetch_search,
    normalize_for_finder,
    summarize_trial_for_search,
)
from trial_finder.conditions import suggest_conditions
from trial_finder.source_catalog import list_sources, source_by_id


class SearchRequest(BaseModel):
    condition_text: str = Field(..., min_length=2)
    location_text: str = Field("", description="City, postcode, or place name typed by the user. Not stored as user profile data.")
    radius_km: int = Field(100, ge=1, le=1000)
    source_ids: list[str] = Field(default_factory=lambda: ["clinicaltrials_gov"])
    statuses: list[str] = Field(default_factory=lambda: list(DEFAULT_STATUSES))
    limit: int = Field(50, ge=1, le=200)


def create_app(cache_root: str | Path | None = None) -> FastAPI:
    app = FastAPI(
        title="Open Clinical Trial Finder API",
        description="On-demand public registry search. Not medical advice and does not determine eligibility.",
        version="0.1.0",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )

    cache = FinderCache(cache_root or os.environ.get("TRIAL_FINDER_CACHE", ".trial-finder-cache"))
    detail_store: dict[str, dict[str, Any]] = {}

    @app.get("/api/sources")
    def api_sources() -> dict[str, Any]:
        return {"sources": list_sources()}

    @app.get("/api/conditions/suggest")
    def api_suggest(q: str = "") -> dict[str, Any]:
        return {
            "query": q,
            "suggestions": suggest_conditions(q),
            "note": "Suggestions normalize common terms only. Users may still search any disease name supported by selected registries.",
        }

    @app.post("/api/search")
    def api_search(payload: SearchRequest) -> dict[str, Any]:
        if not payload.condition_text.strip():
            raise HTTPException(status_code=400, detail="condition_text is required")
        results: list[dict[str, Any]] = []
        source_messages: list[dict[str, str]] = []

        for source_id in payload.source_ids:
            source = source_by_id(source_id)
            if source is None:
                source_messages.append({"source_id": source_id, "status": "unknown", "message": "Unknown source was skipped."})
                continue
            if source.status != "connected":
                source_messages.append(
                    {
                        "source_id": source_id,
                        "status": source.status,
                        "message": "This source is visible for planning, but not connected in this MVP.",
                    }
                )
                continue
            if source_id != "clinicaltrials_gov":
                source_messages.append({"source_id": source_id, "status": "unsupported", "message": "Connector is not implemented."})
                continue

            cached = cache.get(source_id, payload.condition_text, payload.location_text, payload.radius_km, payload.statuses)
            if cached:
                normalized = cached["normalized"]
                cache_status = "hit"
            else:
                raw, meta = fetch_search(
                    condition_text=payload.condition_text,
                    location_text=payload.location_text,
                    radius_km=payload.radius_km,
                    statuses=payload.statuses,
                    limit=payload.limit,
                )
                normalized = normalize_for_finder(raw, payload.condition_text, payload.location_text, payload.radius_km)
                cache.set(source_id, payload.condition_text, payload.location_text, payload.radius_km, payload.statuses, {"meta": meta, "studies": raw}, normalized)
                cache_status = "miss"

            for trial in normalized:
                detail_store[trial["canonical_trial_key"]] = trial
            results.extend(summarize_trial_for_search(trial) for trial in normalized[: payload.limit])
            source_messages.append({"source_id": source_id, "status": "connected", "message": f"Search completed with cache {cache_status}."})

        results.sort(key=lambda item: (item.get("distance_km") is None, item.get("distance_km") or 10**9, item.get("title") or ""))
        limited = results[: payload.limit]
        return {
            "query": {
                "condition_text": payload.condition_text,
                "radius_km": payload.radius_km,
                "source_ids": payload.source_ids,
                "statuses": payload.statuses,
                "location_storage": "Location text is used for this search/cache key hash only; no user location profile is stored.",
            },
            "count": len(limited),
            "results": limited,
            "sources": source_messages,
            "safety_note": "Results may be recruiting near this location based on public registry data. Verify details in the official registry. This tool does not determine eligibility and is not medical advice.",
        }

    @app.get("/api/trials/{canonical_trial_key}")
    def api_trial_detail(canonical_trial_key: str) -> dict[str, Any]:
        trial = detail_store.get(canonical_trial_key)
        if trial:
            return {"trial": trial}

        # Fallback to generated current data when the detail page is opened before a runtime search.
        for path in Path("data/current").glob("*.trials.json"):
            for item in _load_json_list(path):
                if item.get("canonical_trial_key") == canonical_trial_key:
                    return {"trial": item}
        raise HTTPException(status_code=404, detail="Trial detail is not in the runtime cache. Run a search first or regenerate local data.")

    site_path = Path("site")
    if site_path.exists():
        app.mount("/", StaticFiles(directory=site_path, html=True), name="site")

    return app


def _load_json_list(path: Path) -> list[dict[str, Any]]:
    import json

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    return data if isinstance(data, list) else []


app = create_app()
