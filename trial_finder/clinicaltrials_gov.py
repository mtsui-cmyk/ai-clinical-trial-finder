"""ClinicalTrials.gov connector for the on-demand trial finder."""

from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from typing import Any

from scripts import trial_radar
from trial_finder.ai_engine import build_ai_reading
from trial_finder.geo import haversine_km, resolve_location


API_URL = "https://clinicaltrials.gov/api/v2/studies"
USER_AGENT = "open-disease-research-radar-finder/0.1 (+https://github.com)"
DEFAULT_STATUSES = ["RECRUITING", "NOT_YET_RECRUITING", "ENROLLING_BY_INVITATION"]


def build_search_params(
    condition_text: str,
    location_text: str,
    radius_km: int,
    statuses: list[str] | None = None,
    page_size: int = 100,
) -> dict[str, str]:
    location = resolve_location(location_text)
    params = {
        "query.cond": condition_text.strip(),
        "filter.overallStatus": ",".join(statuses or DEFAULT_STATUSES),
        "pageSize": str(page_size),
        "format": "json",
    }
    if location.get("lat") is not None and location.get("lon") is not None:
        miles = max(1, round(radius_km * 0.621371))
        params["filter.geo"] = f"distance({location['lat']},{location['lon']},{miles}mi)"
    elif location.get("query_text"):
        params["query.locn"] = str(location["query_text"])
    return params


def fetch_search(
    condition_text: str,
    location_text: str,
    radius_km: int,
    statuses: list[str] | None = None,
    page_size: int = 100,
    limit: int = 200,
    timeout: int = 45,
    sleep: float = 0.1,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    studies: list[dict[str, Any]] = []
    location = resolve_location(location_text)
    params = build_search_params(condition_text, location_text, radius_km, statuses, page_size)
    page_token = None
    data_timestamp = None

    while True:
        request_params = dict(params)
        if page_token:
            request_params["pageToken"] = page_token
        url = f"{API_URL}?{urllib.parse.urlencode(request_params)}"
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
        data_timestamp = payload.get("dataTimestamp") or data_timestamp
        studies.extend(payload.get("studies", []))
        if limit and len(studies) >= limit:
            studies = studies[:limit]
            break
        page_token = payload.get("nextPageToken")
        if not page_token:
            break
        time.sleep(sleep)

    return studies, {
        "source_id": "clinicaltrials_gov",
        "source_name": "ClinicalTrials.gov",
        "params": params,
        "location_resolution": location,
        "data_timestamp": data_timestamp,
    }


def normalize_for_finder(
    studies: list[dict[str, Any]],
    condition_text: str,
    location_text: str,
    radius_km: int,
) -> list[dict[str, Any]]:
    location = resolve_location(location_text)
    normalized: list[dict[str, Any]] = []
    for study in studies:
        trial = trial_radar.normalize_study(study)
        trial["matched_condition_text"] = condition_text
        trial["nearest_location"] = nearest_location(trial.get("locations", []), location)
        if trial["nearest_location"] and trial["nearest_location"].get("distance_km") is not None:
            trial["distance_km"] = trial["nearest_location"]["distance_km"]
        else:
            trial["distance_km"] = None
        trial["finder_safety_note"] = (
            "This result may be recruiting near this location based on public registry data. "
            "Verify details in the official registry. This tool does not determine eligibility and is not medical advice."
        )
        trial["research_radar"] = build_ai_reading(trial)
        normalized.append(trial)

    normalized.sort(key=lambda item: (item.get("distance_km") is None, item.get("distance_km") or 10**9, item.get("title") or ""))
    return normalized


def nearest_location(locations: list[dict[str, Any]], location_resolution: dict[str, object]) -> dict[str, Any] | None:
    if not locations:
        return None
    lat = location_resolution.get("lat")
    lon = location_resolution.get("lon")
    if lat is None or lon is None:
        return locations[0]

    nearest = None
    for site in locations:
        site_lat = site.get("geoPoint", {}).get("lat") if isinstance(site.get("geoPoint"), dict) else site.get("lat")
        site_lon = site.get("geoPoint", {}).get("lon") if isinstance(site.get("geoPoint"), dict) else site.get("lon")
        candidate = dict(site)
        if site_lat is not None and site_lon is not None:
            candidate["distance_km"] = round(haversine_km(float(lat), float(lon), float(site_lat), float(site_lon)), 1)
        if nearest is None:
            nearest = candidate
            continue
        current_distance = nearest.get("distance_km")
        candidate_distance = candidate.get("distance_km")
        if candidate_distance is not None and (current_distance is None or candidate_distance < current_distance):
            nearest = candidate
    return nearest


def summarize_trial_for_search(trial: dict[str, Any]) -> dict[str, Any]:
    return {
        "canonical_trial_key": trial.get("canonical_trial_key"),
        "trial_id": trial.get("trial_id"),
        "registry": trial.get("registry"),
        "title": trial.get("title"),
        "status": trial.get("status"),
        "phase": trial.get("phase"),
        "conditions": trial.get("conditions", []),
        "intervention_names": trial.get("intervention_names", []),
        "sponsor": trial.get("sponsor"),
        "source_url": trial.get("source_url"),
        "source_records": trial.get("source_records", []),
        "nearest_location": trial.get("nearest_location"),
        "distance_km": trial.get("distance_km"),
        "finder_safety_note": trial.get("finder_safety_note"),
        "research_radar": trial.get("research_radar", {}),
    }
