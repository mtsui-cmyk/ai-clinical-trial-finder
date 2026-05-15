#!/usr/bin/env python3
"""Fetch, normalize, diff, and report disease-scoped trial registry data.

The MVP is intentionally repo-native: it writes JSON, CSV, and Markdown files
that can be reviewed, committed, and reused without a backend server.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import html
import json
import re
import shutil
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path
from typing import Any


API_URL = "https://clinicaltrials.gov/api/v2/studies"
USER_AGENT = "open-disease-research-radar/0.1 (+https://github.com)"
RECRUITING_STATUSES = {"RECRUITING", "NOT_YET_RECRUITING", "ENROLLING_BY_INVITATION"}
CURRENT_RESEARCH_STATUSES = RECRUITING_STATUSES | {"ACTIVE_NOT_RECRUITING"}
ARCHIVE_STATUSES = {"COMPLETED", "TERMINATED", "WITHDRAWN", "SUSPENDED", "NO_LONGER_AVAILABLE"}
AI_REWRITE_METHODS = {"deepseek_chat_completions_api", "openai_responses_api"}
PRODUCT_NAME = "TrialCompass"
SIGNIFICANT_DIFF_FIELDS = [
    "status",
    "phase",
    "has_results",
    "interventions",
    "countries",
    "last_update_posted",
]


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a disease clinical research radar.")
    parser.add_argument("--config", required=True, help="Path to disease config JSON.")
    parser.add_argument("--out", default=".", help="Workspace output root.")
    parser.add_argument("--page-size", type=int, default=100, help="ClinicalTrials.gov API page size.")
    parser.add_argument("--sleep", type=float, default=0.15, help="Sleep between API requests.")
    parser.add_argument("--timeout", type=int, default=60, help="HTTP request timeout in seconds.")
    parser.add_argument("--retries", type=int, default=3, help="HTTP retry attempts for transient failures.")
    parser.add_argument("--limit", type=int, default=0, help="Optional max records for development.")
    parser.add_argument("--offline-raw", help="Read raw study JSON files from a directory instead of the API.")
    parser.add_argument("--ai-cache-dir", help="Optional directory of reviewed AI rewrite JSON files.")
    parser.add_argument("--pubmed-file", help="Optional PubMed source-layer JSON.")
    parser.add_argument("--store-raw", action="store_true", help="Store raw registry records by trial ID.")
    parser.add_argument("--verbose", action="store_true", help="Print fetch progress to stderr.")
    args = parser.parse_args()

    root = Path(args.out)
    config = load_json(Path(args.config))
    slug = config["slug"]
    today = dt.date.today().isoformat()

    ensure_dirs(root, slug)
    previous = load_previous_current(root, slug)

    if args.offline_raw:
        raw_studies = load_offline_raw(Path(args.offline_raw), args.limit)
        data_timestamp = None
    else:
        raw_studies, data_timestamp = fetch_all_for_config(
            config,
            page_size=args.page_size,
            sleep=args.sleep,
            limit=args.limit,
            timeout=args.timeout,
            retries=args.retries,
            verbose=args.verbose,
        )

    normalized = normalize_studies(raw_studies, config)
    if args.ai_cache_dir:
        apply_ai_rewrites(normalized, Path(args.ai_cache_dir))
    if args.pubmed_file:
        apply_pubmed_records(normalized, Path(args.pubmed_file))
    normalized.sort(key=lambda item: item["trial_id"])
    write_outputs(root, slug, normalized, raw_studies, today, store_raw=args.store_raw)

    diff = compute_diff(previous, normalized)
    summary = build_summary(normalized, diff, config, today, data_timestamp)
    write_summary_outputs(root, slug, summary, diff, normalized, today)

    print(f"Wrote {len(normalized)} normalized trials for {slug}.")
    print(f"New: {len(diff['new'])}, changed: {len(diff['changed'])}, removed: {len(diff['removed'])}.")
    return 0


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")


def ensure_dirs(root: Path, slug: str) -> None:
    for relative in [
        "data/raw/clinicaltrials-gov",
        "data/current",
        "data/snapshots",
        "reports/weekly",
        "site",
        f"data/ai-cache/{slug}",
    ]:
        (root / relative).mkdir(parents=True, exist_ok=True)


def fetch_all_for_config(
    config: dict[str, Any],
    page_size: int,
    sleep: float,
    limit: int,
    timeout: int,
    retries: int,
    verbose: bool,
) -> tuple[list[dict[str, Any]], str | None]:
    seen: dict[str, dict[str, Any]] = {}
    data_timestamp = None

    for query in config["queries"]:
        if verbose:
            print(f"Fetching query.cond={query['condition']!r}", file=sys.stderr)
        for study, timestamp in iter_clinicaltrials_pages(query["condition"], page_size, sleep, timeout, retries, verbose):
            if timestamp:
                data_timestamp = timestamp
            nct_id = get_in(study, ["protocolSection", "identificationModule", "nctId"])
            if not nct_id:
                continue
            seen[nct_id] = study
            if limit and len(seen) >= limit:
                return list(seen.values()), data_timestamp

    return list(seen.values()), data_timestamp


def iter_clinicaltrials_pages(condition: str, page_size: int, sleep: float, timeout: int, retries: int, verbose: bool):
    page_token = None
    page_number = 0
    while True:
        params = {
            "query.cond": condition,
            "pageSize": str(page_size),
            "format": "json",
        }
        if page_token:
            params["pageToken"] = page_token

        url = f"{API_URL}?{urllib.parse.urlencode(params)}"
        page_number += 1
        if verbose:
            print(f"  page {page_number}: requesting {url}", file=sys.stderr)
        payload = fetch_json(url, timeout=timeout, retries=retries)
        studies = payload.get("studies", [])
        if verbose:
            print(f"  page {page_number}: received {len(studies)} records", file=sys.stderr)
        for study in studies:
            yield study, payload.get("dataTimestamp")

        page_token = payload.get("nextPageToken")
        if not page_token:
            break
        time.sleep(sleep)


def fetch_json(url: str, timeout: int, retries: int) -> dict[str, Any]:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            if 400 <= exc.code < 500 and exc.code != 429:
                raise RuntimeError(f"HTTP {exc.code} for {url}: {detail[:500]}") from exc
            last_error = RuntimeError(f"HTTP {exc.code} for {url}: {detail[:500]}")
        except urllib.error.URLError as exc:
            last_error = exc

        if attempt < retries:
            time.sleep(min(2 ** attempt, 10))

    raise RuntimeError(f"Could not fetch {url} after {retries} attempts: {last_error}")


def load_offline_raw(raw_dir: Path, limit: int) -> list[dict[str, Any]]:
    studies: list[dict[str, Any]] = []
    for path in sorted(raw_dir.glob("*.json")):
        studies.append(load_json(path))
        if limit and len(studies) >= limit:
            break
    return studies


def normalize_studies(studies: list[dict[str, Any]], config: dict[str, Any]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    excludes = [term.lower() for term in config.get("exclude_condition_terms", [])]

    for study in studies:
        item = normalize_study(study)
        conditions_text = " ".join(item["conditions"]).lower()
        if excludes and any(term in conditions_text for term in excludes):
            continue
        normalized.append(item)

    return normalized


def apply_ai_rewrites(trials: list[dict[str, Any]], cache_dir: Path) -> None:
    if not cache_dir.exists():
        return
    for trial in trials:
        path = cache_dir / f"{trial['trial_id']}.json"
        if not path.exists():
            continue
        rewrite = load_json(path)
        trial["patient_reading"] = {
            "method": rewrite.get("_meta", {}).get("source", "ai_rewrite_cache"),
            "review_status": rewrite.get("review_status", "ai_generated_not_medically_reviewed"),
            "patient_title": rewrite.get("patient_title") or trial.get("title"),
            "patient_summary": rewrite.get("patient_summary") or trial.get("plain_language_summary"),
            "what_researchers_are_studying": rewrite.get("what_researchers_are_studying") or trial.get("plain_language_summary"),
            "may_be_looking_for": rewrite.get("may_be_looking_for") or [],
            "may_exclude_people_who": rewrite.get("may_exclude_people_who") or [],
            "source_grounding": rewrite.get("source_grounding") or [],
            "safety_note": "This is an AI-generated public-data reading aid. It cannot decide eligibility and is not medical advice.",
        }
        if rewrite.get("questions_to_ask_clinician"):
            trial["questions_to_ask"] = rewrite["questions_to_ask_clinician"][:5]


def is_ai_explained(trial: dict[str, Any]) -> bool:
    return trial.get("patient_reading", {}).get("method") in AI_REWRITE_METHODS


def ai_coverage_stats(trials: list[dict[str, Any]]) -> dict[str, int]:
    current_trials = [trial for trial in trials if trial.get("relevance") == "current"]
    recruiting_trials = [trial for trial in trials if trial.get("status") in RECRUITING_STATUSES]
    ai_trials = [trial for trial in trials if is_ai_explained(trial)]
    current_ai_trials = [trial for trial in current_trials if is_ai_explained(trial)]
    recruiting_ai_trials = [trial for trial in recruiting_trials if is_ai_explained(trial)]
    return {
        "total": len(trials),
        "ai_total": len(ai_trials),
        "current_total": len(current_trials),
        "current_ai": len(current_ai_trials),
        "current_missing": len(current_trials) - len(current_ai_trials),
        "recruiting_total": len(recruiting_trials),
        "recruiting_ai": len(recruiting_ai_trials),
        "recruiting_missing": len(recruiting_trials) - len(recruiting_ai_trials),
    }


def apply_pubmed_records(trials: list[dict[str, Any]], pubmed_file: Path) -> None:
    if not pubmed_file.exists():
        return
    records = load_json(pubmed_file)
    by_trial: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        by_trial.setdefault(record.get("trial_id", ""), []).append(record)
    for trial in trials:
        for record in by_trial.get(trial["trial_id"], []):
            trial.setdefault("publications", []).append(record)
            trial.setdefault("source_records", []).append(
                {
                    "source": "PubMed",
                    "record_id": record.get("pmid", ""),
                    "url": record.get("url", ""),
                    "last_update_posted": record.get("pub_date", ""),
                    "title": record.get("title", ""),
                }
            )


def normalize_study(study: dict[str, Any]) -> dict[str, Any]:
    protocol = study.get("protocolSection", {})
    identification = protocol.get("identificationModule", {})
    status = protocol.get("statusModule", {})
    sponsor_module = protocol.get("sponsorCollaboratorsModule", {})
    conditions_module = protocol.get("conditionsModule", {})
    design = protocol.get("designModule", {})
    interventions_module = protocol.get("armsInterventionsModule", {})
    locations_module = protocol.get("contactsLocationsModule", {})
    eligibility = protocol.get("eligibilityModule", {})
    oversight = protocol.get("oversightModule", {})
    results_section = study.get("resultsSection", {})

    interventions = [
        normalize_intervention(intervention)
        for intervention in interventions_module.get("interventions", [])
    ]
    countries = sorted(
        {
            location.get("country", "").strip()
            for location in locations_module.get("locations", [])
            if location.get("country")
        }
    )
    locations = normalize_locations(locations_module.get("locations", []))

    nct_id = identification.get("nctId", "")
    secondary_ids = normalize_secondary_ids(identification)
    title = identification.get("briefTitle") or identification.get("officialTitle") or ""
    phase = normalize_phase(design.get("phases", []))
    overall_status = status.get("overallStatus", "UNKNOWN")
    source_url = f"https://clinicaltrials.gov/study/{nct_id}" if nct_id else ""
    has_results = bool(results_section) or bool(status.get("resultsFirstPostDateStruct"))
    relevance = classify_relevance(overall_status)
    regions = sorted({country_region(country) for country in countries if country_region(country) != "Unknown"})
    questions = build_questions_to_ask(overall_status, phase, interventions, countries, has_results)
    eligibility_summary = normalize_eligibility(eligibility)
    plain_language_summary = build_plain_language_summary(
        title=title,
        phase=phase,
        status=overall_status,
        interventions=interventions,
        conditions=conditions_module.get("conditions", []),
        countries=countries,
    )

    return {
        "trial_id": nct_id,
        "registry": "ClinicalTrials.gov",
        "registry_id": nct_id,
        "canonical_trial_key": canonical_trial_key("ClinicalTrials.gov", nct_id),
        "source_records": [
            {
                "source": "ClinicalTrials.gov",
                "record_id": nct_id,
                "url": source_url,
                "last_update_posted": get_in(status, ["lastUpdatePostDateStruct", "date"], ""),
            }
        ],
        "secondary_ids": secondary_ids,
        "source_url": source_url,
        "title": title,
        "official_title": identification.get("officialTitle", ""),
        "brief_summary": get_in(protocol, ["descriptionModule", "briefSummary"], ""),
        "conditions": sorted(conditions_module.get("conditions", [])),
        "interventions": interventions,
        "intervention_names": sorted({item["name"] for item in interventions if item["name"]}),
        "intervention_types": sorted({item["type"] for item in interventions if item["type"]}),
        "sponsor": get_in(sponsor_module, ["leadSponsor", "name"], ""),
        "sponsor_class": get_in(sponsor_module, ["leadSponsor", "class"], ""),
        "phase": phase,
        "status": overall_status,
        "relevance": relevance,
        "study_type": design.get("studyType", ""),
        "enrollment_count": get_in(design, ["enrollmentInfo", "count"]),
        "enrollment_type": get_in(design, ["enrollmentInfo", "type"], ""),
        "countries": countries,
        "regions": regions,
        "locations": locations,
        "start_date": get_in(status, ["startDateStruct", "date"], ""),
        "completion_date": get_in(status, ["completionDateStruct", "date"], ""),
        "last_update_posted": get_in(status, ["lastUpdatePostDateStruct", "date"], ""),
        "eligibility": eligibility_summary,
        "has_results": has_results,
        "is_fda_regulated_drug": bool(oversight.get("isFdaRegulatedDrug")),
        "is_fda_regulated_device": bool(oversight.get("isFdaRegulatedDevice")),
        "publications": [],
        "plain_language_summary": plain_language_summary,
        "patient_reading": build_patient_reading(
            title=title,
            summary=plain_language_summary,
            status=overall_status,
            phase=phase,
            interventions=interventions,
            conditions=conditions_module.get("conditions", []),
            eligibility=eligibility_summary,
            countries=countries,
        ),
        "questions_to_ask": questions,
    }


def normalize_intervention(intervention: dict[str, Any]) -> dict[str, Any]:
    name = intervention.get("name", "").strip()
    raw_type = intervention.get("type", "OTHER").strip().lower()
    aliases = sorted({alias.strip() for alias in intervention.get("otherNames", []) if alias.strip()})
    return {
        "name": name,
        "type": raw_type,
        "aliases": aliases,
        "description": intervention.get("description", ""),
    }


def normalize_secondary_ids(identification: dict[str, Any]) -> list[str]:
    values: set[str] = set()
    org_id = get_in(identification, ["orgStudyIdInfo", "id"])
    if org_id:
        values.add(str(org_id).strip())
    for item in identification.get("secondaryIdInfos", []) or []:
        value = item.get("id")
        if value:
            values.add(str(value).strip())
    return sorted(value for value in values if value)


def canonical_trial_key(registry: str, record_id: str) -> str:
    clean_registry = re.sub(r"[^a-z0-9]+", "-", registry.lower()).strip("-")
    clean_id = re.sub(r"[^a-z0-9]+", "-", str(record_id or "").lower()).strip("-")
    return f"{clean_registry}:{clean_id or 'unknown'}"


def normalize_locations(locations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized = []
    for location in locations:
        geo_point = location.get("geoPoint") or {}
        normalized.append(
            {
                "facility": location.get("facility", ""),
                "city": location.get("city", ""),
                "state": location.get("state", ""),
                "zip": location.get("zip", ""),
                "country": location.get("country", ""),
                "status": location.get("status", ""),
                "contacts": normalize_location_contacts(location.get("contacts", [])),
                "geoPoint": {
                    "lat": geo_point.get("lat"),
                    "lon": geo_point.get("lon"),
                }
                if geo_point
                else {},
            }
        )
    return normalized


def normalize_location_contacts(contacts: list[dict[str, Any]]) -> list[dict[str, str]]:
    normalized = []
    for contact in contacts:
        normalized.append(
            {
                "name": contact.get("name", ""),
                "role": contact.get("role", ""),
                "phone": contact.get("phone", ""),
                "email": contact.get("email", ""),
            }
        )
    return normalized


def normalize_eligibility(eligibility: dict[str, Any]) -> dict[str, Any]:
    criteria = eligibility.get("eligibilityCriteria", "")
    return {
        "sex": eligibility.get("sex", ""),
        "minimum_age": eligibility.get("minimumAge", ""),
        "maximum_age": eligibility.get("maximumAge", ""),
        "healthy_volunteers": bool(eligibility.get("healthyVolunteers")) if "healthyVolunteers" in eligibility else None,
        "criteria_excerpt": truncate_text(criteria, 900),
    }


def truncate_text(value: str, max_length: int) -> str:
    value = re.sub(r"\s+", " ", value or "").strip()
    if len(value) <= max_length:
        return value
    return value[: max_length - 1].rstrip() + "…"


def classify_relevance(status: str) -> str:
    if status in CURRENT_RESEARCH_STATUSES:
        return "current"
    if status in ARCHIVE_STATUSES:
        return "historical"
    return "unclear"


def normalize_phase(phases: list[str]) -> str:
    if not phases:
        return "N/A"
    labels = []
    for phase in phases:
        if phase.upper() in {"NA", "N/A", "NOT_APPLICABLE"}:
            labels.append("N/A")
            continue
        cleaned = phase.replace("_", " ").title()
        cleaned = re.sub(r"Phase(\d)", r"Phase \1", cleaned)
        labels.append(cleaned)
    return ", ".join(labels)


def build_plain_language_summary(
    title: str,
    phase: str,
    status: str,
    interventions: list[dict[str, Any]],
    conditions: list[str],
    countries: list[str],
) -> str:
    names = [item["name"] for item in interventions if item.get("name")]
    intervention_text = ", ".join(names[:3]) if names else "one or more interventions"
    if len(names) > 3:
        intervention_text += f", and {len(names) - 3} more"
    condition_text = ", ".join(conditions[:3]) if conditions else "the listed condition"
    country_text = ", ".join(countries[:5]) if countries else "locations not listed in the normalized record"
    phase_text = f"{phase} research" if phase != "N/A" else "research with no standard drug phase listed"
    status_text = status.replace("_", " ").lower()
    return (
        f"This public registry record describes {phase_text} involving {intervention_text} "
        f"for {condition_text}. Its listed recruitment status is {status_text}. "
        f"Listed countries include {country_text}. This summary is for research awareness only, "
        f"not medical advice or trial eligibility guidance."
    )


def build_questions_to_ask(
    status: str,
    phase: str,
    interventions: list[dict[str, Any]],
    countries: list[str],
    has_results: bool,
) -> list[str]:
    questions = [
        "What is the main question this study is trying to answer?",
        "How would this study relate to my diagnosis and current treatment history?",
    ]
    if status in RECRUITING_STATUSES:
        questions.append("If I am interested, what should I ask my clinician before contacting a study site?")
    if phase == "N/A":
        questions.append("Why does this record not list a standard drug trial phase?")
    elif "Phase 1" in phase:
        questions.append("What does early safety research mean in this study?")
    elif "Phase 2" in phase:
        questions.append("What outcomes are researchers measuring at this stage?")
    elif "Phase 3" in phase:
        questions.append("What is being compared, and how large is the study?")
    if any(item.get("type") == "device" for item in interventions):
        questions.append("Is this studying a device, procedure, or software rather than a medication?")
    if not countries:
        questions.append("Are study locations publicly listed yet?")
    if has_results:
        questions.append("Where can I read the posted public results, and what did they measure?")
    return questions[:5]


def build_patient_reading(
    title: str,
    summary: str,
    status: str,
    phase: str,
    interventions: list[dict[str, Any]],
    conditions: list[str],
    eligibility: dict[str, Any],
    countries: list[str],
) -> dict[str, Any]:
    names = [item["name"] for item in interventions if item.get("name")]
    condition_text = ", ".join(conditions[:3]) if conditions else "the listed condition"
    intervention_text = ", ".join(names[:3]) if names else "the intervention listed in the registry"
    looking_for, may_exclude = extract_eligibility_reading(eligibility)
    if not looking_for:
        looking_for = [
            f"People connected to {condition_text}.",
            f"People who fit the age and sex fields listed by the registry: {format_age_text(eligibility)}, {pretty_status(eligibility.get('sex') or 'sex not listed')}.",
        ]
    if not may_exclude:
        may_exclude = [
            "The public excerpt does not provide a short exclusion list in this generated view. Read the official criteria and ask a clinician or study team to interpret them.",
        ]
    return {
        "method": "source_grounded_rules_v1",
        "review_status": "not_medically_reviewed",
        "patient_title": simplify_title(title),
        "patient_summary": (
            f"This record is about research in {condition_text}. Researchers list {intervention_text} "
            f"and describe the study as {phase_label(phase).lower()}. The registry status is "
            f"{pretty_status(status).lower()}. Countries listed include {', '.join(countries[:5]) if countries else 'not clearly listed'}."
        ),
        "what_researchers_are_studying": truncate_text(summary, 520),
        "may_be_looking_for": looking_for[:5],
        "may_exclude_people_who": may_exclude[:5],
        "source_grounding": [
            "title",
            "brief_summary",
            "eligibility.criteria_excerpt",
            "phase",
            "status",
            "interventions",
            "countries",
        ],
        "safety_note": "This is a public-data reading aid. It cannot decide whether a person qualifies and is not medical advice.",
    }


def simplify_title(title: str) -> str:
    cleaned = re.sub(r"\s+", " ", title or "").strip()
    cleaned = re.sub(r"\bA\s+(Phase|Study)\b", r"\1", cleaned, flags=re.IGNORECASE)
    cleaned = cleaned.replace("A Study of", "Study of").replace("An Open-Label", "Open-label")
    return cleaned or "Public research record"


def extract_eligibility_reading(eligibility: dict[str, Any]) -> tuple[list[str], list[str]]:
    text = eligibility.get("criteria_excerpt") or ""
    inclusion, exclusion = split_criteria_text(text)
    looking_for = summarize_criteria_lines(inclusion, "May be looking for")
    may_exclude = summarize_criteria_lines(exclusion, "May exclude people who")
    return looking_for, may_exclude


def split_criteria_text(text: str) -> tuple[str, str]:
    if not text:
        return "", ""
    normalized = re.sub(r"\s+", " ", text).strip()
    inclusion_match = re.search(r"(inclusion criteria|key inclusion criteria|inclusion)", normalized, re.IGNORECASE)
    exclusion_match = re.search(r"(exclusion criteria|key exclusion criteria|exclusion)", normalized, re.IGNORECASE)
    if inclusion_match and exclusion_match:
        if inclusion_match.start() < exclusion_match.start():
            return normalized[inclusion_match.end() : exclusion_match.start()], normalized[exclusion_match.end() :]
        return normalized[:exclusion_match.start()], normalized[exclusion_match.end() :]
    if exclusion_match:
        return normalized[:exclusion_match.start()], normalized[exclusion_match.end() :]
    return normalized, ""


def summarize_criteria_lines(text: str, prefix: str) -> list[str]:
    if not text:
        return []
    chunks = re.split(r"(?:\s[-*]\s|\s\d+[.)]\s|;\s)", text)
    cleaned = []
    for chunk in chunks:
        value = truncate_text(re.sub(r"^(must|have|has|with|without)\s+", "", chunk.strip(" :-")), 180)
        if len(value) < 18:
            continue
        cleaned.append(f"{prefix}: {value[0].lower() + value[1:]}")
        if len(cleaned) >= 5:
            break
    return cleaned


def country_region(country: str) -> str:
    country = country.strip()
    region_map = {
        "United States": "North America",
        "Canada": "North America",
        "Mexico": "North America",
        "China": "East Asia",
        "Hong Kong": "East Asia",
        "Japan": "East Asia",
        "Korea, Republic of": "East Asia",
        "Taiwan": "East Asia",
        "India": "South Asia",
        "Pakistan": "South Asia",
        "Bangladesh": "South Asia",
        "Singapore": "Southeast Asia",
        "Malaysia": "Southeast Asia",
        "Thailand": "Southeast Asia",
        "Philippines": "Southeast Asia",
        "Vietnam": "Southeast Asia",
        "Indonesia": "Southeast Asia",
        "United Arab Emirates": "Middle East",
        "Saudi Arabia": "Middle East",
        "Israel": "Middle East",
        "Turkey": "Middle East",
        "Qatar": "Middle East",
        "Egypt": "Middle East / Africa",
        "South Africa": "Africa",
        "Brazil": "Latin America",
        "Argentina": "Latin America",
        "Chile": "Latin America",
        "Colombia": "Latin America",
        "Peru": "Latin America",
        "Australia": "Oceania",
        "New Zealand": "Oceania",
    }
    if country in region_map:
        return region_map[country]
    europe = {
        "Austria", "Belgium", "Bulgaria", "Croatia", "Czechia", "Denmark", "Estonia",
        "Finland", "France", "Germany", "Greece", "Hungary", "Ireland", "Italy",
        "Latvia", "Lithuania", "Netherlands", "Norway", "Poland", "Portugal",
        "Romania", "Russian Federation", "Serbia", "Slovakia", "Slovenia", "Spain",
        "Sweden", "Switzerland", "Ukraine", "United Kingdom",
    }
    return "Europe" if country in europe else "Other / Global"


def write_outputs(
    root: Path,
    slug: str,
    normalized: list[dict[str, Any]],
    raw_studies: list[dict[str, Any]],
    today: str,
    store_raw: bool,
) -> None:
    if store_raw:
        raw_root = root / "data/raw/clinicaltrials-gov"
        for study in raw_studies:
            nct_id = get_in(study, ["protocolSection", "identificationModule", "nctId"])
            if nct_id:
                write_json(raw_root / f"{nct_id}.json", study)

    write_json(root / f"data/current/{slug}.trials.json", normalized)
    write_json(root / f"data/snapshots/{slug}.{today}.json", normalized)
    write_trials_csv(root / f"data/current/{slug}.trials.csv", normalized)
    write_counter_csv(root / f"data/current/{slug}.interventions.csv", count_interventions(normalized), ["intervention", "count"])
    write_counter_csv(root / f"data/current/{slug}.sponsors.csv", count_field(normalized, "sponsor"), ["sponsor", "count"])
    write_counter_csv(root / f"data/current/{slug}.countries.csv", count_many(normalized, "countries"), ["country", "count"])


def write_trials_csv(path: Path, trials: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "trial_id",
        "title",
        "status",
        "phase",
        "sponsor",
        "sponsor_class",
        "intervention_names",
        "intervention_types",
        "countries",
        "regions",
        "last_update_posted",
        "has_results",
        "source_url",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for trial in trials:
            row = {field: trial.get(field, "") for field in fieldnames}
            row["intervention_names"] = "; ".join(trial.get("intervention_names", []))
            row["intervention_types"] = "; ".join(trial.get("intervention_types", []))
            row["countries"] = "; ".join(trial.get("countries", []))
            row["regions"] = "; ".join(trial.get("regions", []))
            writer.writerow(row)


def write_counter_csv(path: Path, counter: Counter[str], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(fieldnames)
        for label, count in counter.most_common():
            writer.writerow([label, count])


def load_previous_current(root: Path, slug: str) -> list[dict[str, Any]]:
    path = root / f"data/current/{slug}.trials.json"
    if not path.exists():
        return []
    return load_json(path)


def compute_diff(previous: list[dict[str, Any]], current: list[dict[str, Any]]) -> dict[str, Any]:
    previous_by_id = {trial["trial_id"]: trial for trial in previous}
    current_by_id = {trial["trial_id"]: trial for trial in current}

    new_ids = sorted(set(current_by_id) - set(previous_by_id))
    removed_ids = sorted(set(previous_by_id) - set(current_by_id))
    changed = []

    for trial_id in sorted(set(previous_by_id) & set(current_by_id)):
        before = previous_by_id[trial_id]
        after = current_by_id[trial_id]
        changes = {}
        for field in SIGNIFICANT_DIFF_FIELDS:
            if before.get(field) != after.get(field):
                changes[field] = {
                    "before": before.get(field),
                    "after": after.get(field),
                }
        if changes:
            changed.append(
                {
                    "trial_id": trial_id,
                    "title": after.get("title", ""),
                    "source_url": after.get("source_url", ""),
                    "changes": changes,
                }
            )

    return {
        "new": [current_by_id[trial_id] for trial_id in new_ids],
        "removed": [previous_by_id[trial_id] for trial_id in removed_ids],
        "changed": changed,
    }


def build_summary(
    trials: list[dict[str, Any]],
    diff: dict[str, Any],
    config: dict[str, Any],
    today: str,
    data_timestamp: str | None,
) -> dict[str, Any]:
    statuses = count_field(trials, "status")
    phases = count_field(trials, "phase")
    intervention_types = count_many(trials, "intervention_types")
    countries = count_many(trials, "countries")
    regions = count_many(trials, "regions")
    sponsors = count_field(trials, "sponsor")
    interventions = count_interventions(trials)
    recruiting_count = sum(1 for trial in trials if trial.get("status") in RECRUITING_STATUSES)
    current_count = sum(1 for trial in trials if trial.get("relevance") == "current")
    historical_count = sum(1 for trial in trials if trial.get("relevance") == "historical")
    unclear_count = sum(1 for trial in trials if trial.get("relevance") == "unclear")

    return {
        "slug": config["slug"],
        "name": config["name"],
        "updated": today,
        "source": config.get("source", "ClinicalTrials.gov"),
        "source_data_timestamp": data_timestamp,
        "total_trials": len(trials),
        "current_research_trials": current_count,
        "recruiting_or_opening_trials": recruiting_count,
        "historical_trials": historical_count,
        "unclear_trials": unclear_count,
        "countries_count": len(countries),
        "interventions_count": len(interventions),
        "new_trials": len(diff["new"]),
        "changed_trials": len(diff["changed"]),
        "removed_trials": len(diff["removed"]),
        "status_counts": statuses.most_common(),
        "phase_counts": phases.most_common(),
        "intervention_type_counts": intervention_types.most_common(),
        "region_counts": regions.most_common(),
        "top_countries": countries.most_common(config.get("report", {}).get("top_n", 12)),
        "top_sponsors": sponsors.most_common(config.get("report", {}).get("top_n", 12)),
        "top_interventions": interventions.most_common(config.get("report", {}).get("top_n", 12)),
    }


def write_summary_outputs(
    root: Path,
    slug: str,
    summary: dict[str, Any],
    diff: dict[str, Any],
    trials: list[dict[str, Any]],
    today: str,
) -> None:
    write_json(root / f"data/current/{slug}.summary.json", summary)
    write_json(root / f"data/current/{slug}.diff.json", diff)
    report = render_weekly_report(summary, diff, trials)
    latest = root / "reports/latest.md"
    weekly = root / f"reports/weekly/{today}-{slug}.md"
    latest.write_text(report, encoding="utf-8")
    weekly.write_text(report, encoding="utf-8")
    write_trial_detail_pages(root, slug, summary, trials)
    write_intervention_pages(root, slug, summary, trials)
    (root / "site/changes.html").write_text(render_changes_page(summary, diff), encoding="utf-8")
    (root / "site/glossary.html").write_text(render_glossary_page(summary), encoding="utf-8")
    (root / "site/diseases.html").write_text(render_disease_index_page([summary]), encoding="utf-8")
    (root / "site/weekly-brief.html").write_text(render_weekly_brief_page(summary, diff, trials), encoding="utf-8")
    (root / "site/publications.html").write_text(render_publications_page(summary, trials), encoding="utf-8")
    write_topic_pages(root, summary, trials)
    write_ai_prompt_pack(root, slug, trials, summary, diff)
    (root / "site/index.html").write_text(render_home_page(summary, diff, trials), encoding="utf-8")
    (root / "site/explorer.html").write_text(render_static_site(summary, diff, trials), encoding="utf-8")


def render_weekly_report(summary: dict[str, Any], diff: dict[str, Any], trials: list[dict[str, Any]]) -> str:
    lines = [
        f"# {summary['name']} Weekly Radar",
        "",
        f"Updated: {summary['updated']}",
        f"Source: {summary['source']}",
    ]
    if summary.get("source_data_timestamp"):
        lines.append(f"Source data timestamp: {summary['source_data_timestamp']}")
    lines.extend(
        [
            "",
            "## Snapshot",
            "",
            f"- Total public trial records tracked: {summary['total_trials']}",
            f"- Current/open research records: {summary['current_research_trials']}",
            f"- Recruiting or opening trials: {summary['recruiting_or_opening_trials']}",
            f"- Historical/closed records retained: {summary['historical_trials']}",
            f"- Countries represented: {summary['countries_count']}",
            f"- Distinct intervention names: {summary['interventions_count']}",
            f"- New records since previous run: {summary['new_trials']}",
            f"- Changed records since previous run: {summary['changed_trials']}",
            f"- Removed records since previous run: {summary['removed_trials']}",
            "",
            "## Top Interventions",
            "",
            render_table(["Intervention", "Count"], summary["top_interventions"]),
            "",
            "## Trial Status",
            "",
            render_table(["Status", "Count"], summary["status_counts"]),
            "",
            "## Phase Distribution",
            "",
            render_table(["Phase", "Count"], summary["phase_counts"]),
            "",
            "## Top Sponsors",
            "",
            render_table(["Sponsor", "Count"], summary["top_sponsors"]),
            "",
            "## Top Countries",
            "",
            render_table(["Country", "Count"], summary["top_countries"]),
            "",
            "## New Trial Records",
            "",
        ]
    )

    if diff["new"]:
        for trial in diff["new"][:20]:
            lines.append(f"- [{trial['trial_id']}]({trial['source_url']}) - {trial['title']}")
    else:
        lines.append("- No new records compared with the previous local run.")

    lines.extend(["", "## Changed Trial Records", ""])
    if diff["changed"]:
        for item in diff["changed"][:20]:
            changed_fields = ", ".join(item["changes"].keys())
            lines.append(f"- [{item['trial_id']}]({item['source_url']}) - {changed_fields}")
    else:
        lines.append("- No tracked field changes compared with the previous local run.")

    lines.extend(
        [
            "",
            "## Plain-Language Note",
            "",
            "This report summarizes public clinical trial registry records. It does not recommend any trial, drug, device, procedure, or treatment. Patients and caregivers should discuss clinical questions with licensed clinicians.",
            "",
            "## Example Public Records",
            "",
        ]
    )
    for trial in trials[:5]:
        lines.append(f"### [{trial['trial_id']}]({trial['source_url']})")
        lines.append("")
        lines.append(trial["plain_language_summary"])
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def write_trial_detail_pages(root: Path, slug: str, summary: dict[str, Any], trials: list[dict[str, Any]]) -> None:
    detail_root = root / "site/trials"
    if detail_root.exists():
        shutil.rmtree(detail_root)
    detail_root.mkdir(parents=True, exist_ok=True)
    for trial in trials:
        page = render_trial_detail_page(summary, trial)
        (detail_root / f"{trial['trial_id']}.html").write_text(page, encoding="utf-8")


def write_intervention_pages(root: Path, slug: str, summary: dict[str, Any], trials: list[dict[str, Any]]) -> None:
    intervention_root = root / "site/interventions"
    if intervention_root.exists():
        shutil.rmtree(intervention_root)
    intervention_root.mkdir(parents=True, exist_ok=True)
    grouped = group_trials_by_intervention(trials)
    for name, grouped_trials in grouped.items():
        page = render_intervention_page(summary, name, grouped_trials)
        (intervention_root / f"{intervention_slug(name)}.html").write_text(page, encoding="utf-8")


def group_trials_by_intervention(trials: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for trial in trials:
        names = trial.get("intervention_names") or ["Unknown"]
        for name in names:
            grouped.setdefault(normalize_label(name), []).append(trial)
    return dict(sorted(grouped.items(), key=lambda item: (-len(item[1]), item[0].lower())))


def render_trial_detail_page(summary: dict[str, Any], trial: dict[str, Any]) -> str:
    title = html.escape(trial["title"] or trial["trial_id"])
    patient = trial.get("patient_reading", {})
    ai_explained = patient.get("method") in AI_REWRITE_METHODS
    ai_badge = '<span class="badge">AI explained</span>' if ai_explained else '<span class="badge">Registry summary only</span>'
    patient_title = html.escape(patient.get("patient_title") or trial["title"] or trial["trial_id"])
    patient_summary = html.escape(patient.get("patient_summary") or trial.get("plain_language_summary") or "")
    confusing_terms = html_list(confusing_terms_for_trial(trial), "No common confusing terms were detected in this record.")
    source_grounding = html_list(patient.get("source_grounding", []) or registry_source_grounding(trial))
    studying = html.escape(patient.get("what_researchers_are_studying") or trial.get("plain_language_summary") or "")
    ai_reader_note = (
        "This record has a reviewed source-grounded AI explanation cache. It is a reading aid only and is not medically reviewed."
        if ai_explained
        else "This record has not been rewritten by the reviewed AI cache yet. The page is using registry-derived template text and source fields."
    )
    status = html.escape(pretty_status(trial["status"]))
    phase = html.escape(phase_label(trial["phase"]))
    questions = html_list(trial.get("questions_to_ask", []))
    interventions = html_interventions(trial.get("interventions", []))
    locations = html_locations(trial.get("locations", []))
    eligibility = trial.get("eligibility", {})
    conditions = html_pills(trial.get("conditions", []))
    countries = html_pills(trial.get("countries", []))
    source_records = html_source_records(trial.get("source_records", []))
    source_url = html.escape(trial["source_url"])
    official_summary = html.escape(trial.get("brief_summary") or "No public summary excerpt is available in this normalized record.")
    eligibility_text = html.escape(
        eligibility.get("criteria_excerpt")
        or "Detailed eligibility text is not included in this compact view. Verify eligibility details in the official registry and with a clinician."
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
  <style>
    :root {{
      --ink: #24211d;
      --muted: #6f6a60;
      --line: #d8d2c5;
      --bg: #f6f3ed;
      --surface: #fffdf8;
      --accent: #6d3f5f;
      --accent-soft: #f3edf2;
      --warn: #8a5a12;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      color: var(--ink);
      background: var(--bg);
      line-height: 1.5;
    }}
    .wrap {{ max-width: 980px; margin: 0 auto; padding: 24px; }}
    .app-nav {{ border-bottom: 1px solid var(--line); background: rgba(255,255,255,.96); position: sticky; top: 0; z-index: 5; }}
    .app-nav .wrap {{ display: flex; justify-content: space-between; gap: 16px; align-items: center; padding-top: 12px; padding-bottom: 12px; }}
    .brand {{ color: var(--ink); font-weight: 800; text-decoration: none; }}
    .nav-links {{ display: flex; flex-wrap: wrap; gap: 8px; justify-content: flex-end; }}
    .nav-links a {{ color: var(--muted); font-size: 13px; font-weight: 750; text-decoration: none; padding: 7px 8px; border-radius: 6px; }}
    .nav-links a:hover {{ background: var(--accent-soft); color: var(--accent); }}
    header {{ background: var(--surface); border-bottom: 1px solid var(--line); }}
    h1 {{ margin: 10px 0 10px; font-size: clamp(26px, 4vw, 42px); line-height: 1.1; letter-spacing: 0; }}
    h2 {{ margin: 0 0 12px; font-size: 22px; letter-spacing: 0; }}
    h3 {{ margin: 18px 0 8px; font-size: 17px; letter-spacing: 0; }}
    p {{ color: var(--muted); }}
    a {{ color: #5c3b72; text-decoration-thickness: 1px; }}
    section {{ background: var(--surface); border-bottom: 1px solid var(--line); }}
    .eyebrow {{ color: var(--accent); font-size: 13px; font-weight: 700; text-transform: uppercase; letter-spacing: 0; }}
    .badge {{ display: inline-block; padding: 5px 9px; border: 1px solid #d4c3d1; background: var(--accent-soft); color: var(--accent); border-radius: 4px; font-weight: 700; font-size: 13px; margin: 2px 6px 2px 0; }}
    .ai-note {{ border-left: 4px solid #77506f; background: #f5edf2; padding: 14px 16px; color: #4e3448; margin-top: 16px; }}
    .notice {{ border-left: 4px solid var(--warn); background: #fff8ea; padding: 14px 16px; color: #46340f; margin-top: 16px; }}
    .boundary {{ color: var(--muted); font-size: 13px; margin-top: 10px; }}
    .grid {{ display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; }}
    .box {{ border: 1px solid var(--line); background: #fbf8f1; padding: 13px; min-height: 86px; }}
    .box span {{ display: block; color: var(--muted); font-size: 12px; margin-bottom: 4px; }}
    .box strong {{ display: block; overflow-wrap: anywhere; }}
    .pill {{ display: inline-block; border: 1px solid var(--line); background: #fffdf8; color: var(--muted); border-radius: 4px; padding: 4px 8px; margin: 2px 4px 2px 0; font-size: 13px; }}
    .plain {{ color: #3f3a34; max-width: 860px; }}
    .actions {{ display: flex; flex-wrap: wrap; gap: 10px; margin-top: 18px; }}
    .button {{ display: inline-block; border: 1px solid var(--line); background: #fffdf8; color: var(--ink); padding: 10px 12px; border-radius: 6px; text-decoration: none; }}
    .button.primary {{ background: var(--accent); border-color: var(--accent); color: #fffdf8; }}
    .detail-layout {{ display: grid; grid-template-columns: minmax(0, 1fr) 300px; gap: 22px; align-items: start; }}
    .side-panel {{ border: 1px solid var(--line); background: #fffdf8; border-radius: 8px; padding: 15px; }}
    .read-section {{ padding-top: 18px; padding-bottom: 18px; }}
    ul {{ padding-left: 20px; color: #3f3a34; }}
    li {{ margin: 6px 0; }}
    @media (max-width: 760px) {{
      .wrap {{ padding: 18px; }}
      .app-nav .wrap {{ display: block; }}
      .nav-links {{ justify-content: flex-start; margin-top: 8px; }}
      .grid {{ grid-template-columns: 1fr; }}
      .detail-layout {{ grid-template-columns: 1fr; }}
    }}
  </style>
</head>
<body>
  <nav class="app-nav">
    <div class="wrap">
      <a class="brand" href="../index.html">{PRODUCT_NAME}</a>
      <div class="nav-links">
        <a href="../finder.html">Find</a>
        <a href="../explorer.html">Learn</a>
        <a href="../changes.html">Updates</a>
      </div>
    </div>
  </nav>
  <header>
    <div class="wrap">
      <div class="eyebrow">Verify and discuss</div>
      <h1>{title}</h1>
      <div>
        <span class="badge">{status}</span>
        <span class="badge">{phase}</span>
        <span class="badge">{html.escape(trial["trial_id"])}</span>
        {ai_badge}
      </div>
      <p class="plain">{patient_summary}</p>
      <div class="boundary">Public data only. Not medical advice. Verify details in the official registry. This page does not determine eligibility.</div>
      <div class="actions">
        <a class="button" href="../finder.html">Find another trial</a>
        <a class="button primary" href="{source_url}" target="_blank" rel="noreferrer">Official registry</a>
        <a class="button" href="javascript:window.print()">Print / save</a>
      </div>
    </div>
  </header>

  <main>
    <section>
      <div class="wrap detail-layout">
        <div>
          <div class="read-section">
            <h2>Verify first</h2>
            <h3>Locations listed</h3>
            {locations}
            <h3>Public eligibility text excerpt</h3>
            <p class="plain">{eligibility_text}</p>
            <h3>Questions to discuss with a clinician</h3>
            {questions}
          </div>
          <div class="read-section">
            <h2>Research context</h2>
            <h3>{patient_title}</h3>
            <p class="plain">{studying}</p>
            <div class="ai-note"><strong>{'AI-explained record' if ai_explained else 'Registry summary only'}:</strong> {html.escape(ai_reader_note)}</div>
            <h3>What terms may be confusing?</h3>
            {confusing_terms}
          </div>
          <div class="read-section">
            <h2>What this record lists</h2>
            <h3>Interventions</h3>
            {interventions}
            <h3>Conditions</h3>
            <div>{conditions or '<p class="plain">No conditions listed.</p>'}</div>
            <h3>Countries</h3>
            <div>{countries or '<p class="plain">No countries listed.</p>'}</div>
          </div>
          <div class="read-section">
            <h2>Source text</h2>
            <h3>Official summary excerpt</h3>
            <p class="plain">{official_summary}</p>
            <h3>Eligibility snapshot</h3>
            <p class="plain">{eligibility_text}</p>
          </div>
        </div>
        <aside class="side-panel">
          <h2>Key fields</h2>
          <div class="grid" style="grid-template-columns:1fr; gap:10px;">
            {detail_box("Sponsor", trial.get("sponsor") or "Not listed")}
            {detail_box("Study type", trial.get("study_type") or "Not listed")}
            {detail_box("Enrollment", format_enrollment_text(trial))}
            {detail_box("Start date", trial.get("start_date") or "Not listed")}
            {detail_box("Age listed", format_age_text(eligibility))}
            {detail_box("Sex listed", pretty_status(eligibility.get("sex") or "Not listed"))}
          </div>
          <h3>Source records</h3>
          {source_records}
        </aside>
      </div>
    </section>

  </main>
</body>
</html>
"""


def render_intervention_page(summary: dict[str, Any], name: str, trials: list[dict[str, Any]]) -> str:
    title = html.escape(name)
    sorted_trials = sorted(trials, key=lambda trial: (relevance_priority(trial), status_priority(trial.get("status", "")), -date_sort_value(trial.get("last_update_posted", ""))))
    statuses = count_field(sorted_trials, "status").most_common()
    phases = count_field(sorted_trials, "phase").most_common()
    countries = count_many(sorted_trials, "countries").most_common(12)
    sponsors = count_field(sorted_trials, "sponsor").most_common(12)
    intervention_types = count_many(sorted_trials, "intervention_types").most_common()
    study_types = count_field(sorted_trials, "study_type").most_common()
    current = sum(1 for trial in sorted_trials if trial.get("relevance") == "current")
    recruiting = sum(1 for trial in sorted_trials if trial.get("status") in RECRUITING_STATUSES)
    highest_phase = highest_phase_label([trial.get("phase", "N/A") for trial in sorted_trials])
    latest_update = max((trial.get("last_update_posted") or "" for trial in sorted_trials), default="")
    trial_cards = "\n".join(render_compact_trial_item(trial, prefix="../trials/") for trial in sorted_trials[:80])
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title} - {html.escape(summary["name"])}</title>
  {shared_page_style()}
</head>
<body>
  <header>
    <div class="wrap">
      <div class="eyebrow">Intervention research landscape</div>
      <h1>{title}</h1>
      <p class="plain">Public trial registry records where this intervention name appears. This page does not evaluate whether the intervention is safe, effective, available, or appropriate for any person.</p>
      <div class="notice">Verify details in official registry records and discuss clinical questions with a licensed clinician.</div>
      <div class="actions">
        <a class="button" href="../index.html">Back to radar</a>
        <a class="button" href="../glossary.html">Glossary</a>
      </div>
    </div>
  </header>
  <main>
    <section>
      <div class="wrap">
        <h2>At A Glance</h2>
        <div class="grid">
          {detail_box("Public records", len(sorted_trials))}
          {detail_box("Current/open records", current)}
          {detail_box("Recruiting/opening", recruiting)}
          {detail_box("Highest listed phase", highest_phase)}
          {detail_box("Latest registry update", latest_update or "Not listed")}
          {detail_box("Countries", len(count_many(sorted_trials, "countries")))}
          {detail_box("Sponsors", len(count_field(sorted_trials, "sponsor")))}
        </div>
      </div>
    </section>
    <section>
      <div class="wrap">
        <h2>Pipeline Signals In This Radar</h2>
        <p class="plain">This is a trial-layer landscape, not a full drug or device approval dossier. Future layers can add approvals, publications, company pipeline pages, and press releases while keeping this page as the public-trial base layer.</p>
        <div class="grid">
          <div>{render_count_block("Intervention type", intervention_types)}</div>
          <div>{render_count_block("Study type", study_types)}</div>
          <div>{render_count_block("Phase", phases)}</div>
        </div>
      </div>
    </section>
    <section>
      <div class="wrap">
        <h2>Landscape</h2>
        <div class="grid">
          <div>{render_count_block("Status", statuses)}</div>
          <div>{render_count_block("Top countries", countries)}</div>
          <div>{render_count_block("Top sponsors", sponsors)}</div>
        </div>
      </div>
    </section>
    <section>
      <div class="wrap">
        <h2>Related Trial Records</h2>
        <p class="plain">Showing up to 80 records, prioritized by current/open status and recent updates.</p>
        <div class="trial-list">{trial_cards or '<p class="plain">No related records found.</p>'}</div>
      </div>
    </section>
  </main>
</body>
</html>
"""


def render_changes_page(summary: dict[str, Any], diff: dict[str, Any]) -> str:
    briefing = render_change_briefing(summary, diff)
    new_items = "\n".join(render_change_item(trial) for trial in diff.get("new", [])[:100])
    changed_items = "\n".join(render_changed_item(item) for item in diff.get("changed", [])[:100])
    removed_items = "\n".join(render_change_item(trial) for trial in diff.get("removed", [])[:100])
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Recent Changes - {html.escape(summary["name"])}</title>
  {shared_page_style()}
</head>
<body>
  <header>
    <div class="wrap">
      <div class="eyebrow">Weekly public-data changes</div>
      <h1>Recent Changes</h1>
      <p class="plain">Changes are computed against the previous generated dataset in this repo. A change means the public registry record changed; it does not imply a clinical conclusion.</p>
      <div class="actions"><a class="button" href="index.html">Back to radar</a></div>
    </div>
  </header>
  <main>
    <section><div class="wrap">{briefing}</div></section>
    <section><div class="wrap"><h2>New Records</h2>{new_items or '<p class="plain">No new records compared with the previous local run.</p>'}</div></section>
    <section><div class="wrap"><h2>Changed Records</h2>{changed_items or '<p class="plain">No tracked field changes compared with the previous local run.</p>'}</div></section>
    <section><div class="wrap"><h2>Removed Records</h2>{removed_items or '<p class="plain">No removed records compared with the previous local run.</p>'}</div></section>
  </main>
</body>
</html>
"""


def render_change_briefing(summary: dict[str, Any], diff: dict[str, Any]) -> str:
    new_count = len(diff.get("new", []))
    changed_count = len(diff.get("changed", []))
    removed_count = len(diff.get("removed", []))
    changed_fields = Counter(
        field
        for item in diff.get("changed", [])
        for field in item.get("changes", {}).keys()
    )
    if new_count or changed_count or removed_count:
        sentence = (
            f"This run found {new_count} new public records, {changed_count} records with tracked field changes, "
            f"and {removed_count} records no longer present in the local disease-scoped result set."
        )
    else:
        sentence = "This run did not find new, removed, or tracked-field changes compared with the previous local dataset."
    fields = changed_fields.most_common(6)
    field_block = render_count_block("Most changed fields", fields) if fields else '<p class="plain">No tracked fields changed in this run.</p>'
    return f"""
      <h2>What Changed This Week</h2>
      <p class="plain">{html.escape(sentence)}</p>
      <div class="grid">
        {detail_box("New records", new_count)}
        {detail_box("Changed records", changed_count)}
        {detail_box("Removed records", removed_count)}
      </div>
      <p class="plain">Interpret this as public-data monitoring only. A registry update may be administrative, operational, or clinical; this page does not judge importance.</p>
      {field_block}
    """


def render_glossary_page(summary: dict[str, Any]) -> str:
    terms = [
        ("Recruiting", "The registry lists the study as currently looking for participants. This still does not mean any person is eligible."),
        ("Not yet recruiting", "The study is listed as planned but not yet open for enrollment."),
        ("Active, not recruiting", "The study is ongoing but is not currently adding participants."),
        ("Completed", "The study has ended. It may still be useful as historical research context."),
        ("Phase 1", "Early research often focused on safety, dosing, and how the intervention behaves in people."),
        ("Phase 2", "Research often looking at dose, safety, and early signs of effect in a more targeted group."),
        ("Phase 3", "Larger confirmatory research, often comparing an intervention with placebo, standard care, or another approach."),
        ("Phase 4", "Research after approval or wider use, often monitoring longer-term or real-world questions."),
        ("Placebo", "An inactive comparison used in some studies. Ask a clinician or study team what comparison is used and why."),
        ("Eligibility criteria", "Public rules about who a study may include or exclude. This project cannot decide whether a person meets them."),
        ("Sponsor", "The organization responsible for the study record, such as a company, university, hospital, or government institute."),
        ("Intervention", "The drug, biologic, device, procedure, behavioral program, or other approach being studied."),
    ]
    body = "\n".join(f"<h3>{html.escape(term)}</h3><p class=\"plain\">{html.escape(definition)}</p>" for term, definition in terms)
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Glossary - {html.escape(summary["name"])}</title>
  {shared_page_style()}
</head>
<body>
  <header>
    <div class="wrap">
      <div class="eyebrow">Plain-language glossary</div>
      <h1>How To Read Trial Terms</h1>
      <p class="plain">Short explanations for public clinical research terms. These definitions are educational and not medical advice.</p>
      <div class="actions"><a class="button" href="index.html">Back to radar</a></div>
    </div>
  </header>
  <main>
    <section><div class="wrap">{body}</div></section>
  </main>
</body>
</html>
"""


def render_disease_index_page(summaries: list[dict[str, Any]]) -> str:
    cards = "\n".join(
        f"""<article class="trial-card">
          <h3><a href="index.html">{html.escape(summary["name"])}</a></h3>
          <div class="meta-row">
            <span class="status-badge">{summary["total_trials"]} records</span>
            <span class="meta">{summary["current_research_trials"]} current/open</span>
            <span class="meta">{summary["countries_count"]} countries</span>
            <span class="meta">Updated: {html.escape(summary["updated"])}</span>
          </div>
        </article>"""
        for summary in summaries
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Disease Radars</title>
  {shared_page_style()}
</head>
<body>
  <header>
    <div class="wrap">
      <div class="eyebrow">Disease radar index</div>
      <h1>Disease Radars</h1>
      <p class="plain">This page is the multi-disease entry point. The current generated workspace contains one disease radar; additional configs can produce more disease pages later.</p>
      <div class="actions"><a class="button" href="index.html">Open lupus radar</a></div>
    </div>
  </header>
  <main><section><div class="wrap trial-list">{cards}</div></section></main>
</body>
</html>
"""


def render_weekly_brief_page(summary: dict[str, Any], diff: dict[str, Any], trials: list[dict[str, Any]]) -> str:
    active_trials = sorted(
        [trial for trial in trials if trial.get("relevance") == "current"],
        key=lambda trial: (status_priority(trial.get("status", "")), -date_sort_value(trial.get("last_update_posted", ""))),
    )
    ai_stats = ai_coverage_stats(trials)
    ai_count = ai_stats["ai_total"]
    active_items = "\n".join(render_compact_trial_item(trial) for trial in active_trials[:12])
    changes = render_change_briefing(summary, diff)
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Weekly Brief - {html.escape(summary["name"])}</title>
  {shared_page_style()}
  <style>
    @media print {{
      .actions {{ display: none; }}
      body {{ background: #fffdf8; }}
      section, header {{ border-bottom: 1px solid #bbb; }}
      .trial-card {{ break-inside: avoid; }}
    }}
  </style>
</head>
<body>
  <header>
    <div class="wrap">
      <div class="eyebrow">Print-friendly public-data brief</div>
      <h1>{html.escape(summary["name"])} Weekly Brief</h1>
      <p class="plain">A shareable summary for NGOs, patient advocates, and research volunteers. It summarizes public registry data only and does not recommend trials, drugs, devices, or treatments.</p>
      <div class="actions">
        <a class="button" href="index.html">Back to radar</a>
        <a class="button" href="javascript:window.print()">Print / save PDF</a>
      </div>
    </div>
  </header>
  <main>
    <section>
      <div class="wrap">
        <h2>Snapshot</h2>
        <div class="grid">
          {detail_box("Total public records", summary["total_trials"])}
          {detail_box("Current/open", summary["current_research_trials"])}
          {detail_box("Recruiting/opening", summary["recruiting_or_opening_trials"])}
          {detail_box("AI explained", ai_count)}
          {detail_box("Countries", summary["countries_count"])}
          {detail_box("Interventions", summary["interventions_count"])}
        </div>
      </div>
    </section>
    <section><div class="wrap">{changes}</div></section>
    <section>
      <div class="wrap">
        <h2>Build-Time AI Brief Workspace</h2>
        <p class="plain">The repo writes a source-grounded briefing prompt pack, but the AI brief is generated only when an operator runs the AI command. The static site does not call an LLM at page view time.</p>
        <div class="grid">
          {detail_box("AI-explained current/open", f"{ai_stats['current_ai']} / {ai_stats['current_total']}")}
          {detail_box("Current/open prompt queue", ai_stats["current_missing"])}
          {detail_box("All AI-explained records", ai_count)}
        </div>
        <div class="ai-note"><strong>Cost and safety boundary:</strong> generate the AI brief on demand, after reviewing public-data changes. The brief may explain research signals and draft advocate questions, but it must not recommend trials, rank therapies, or decide eligibility.</div>
        <div class="actions">
          <a class="button" href="../reports/ai-coverage.md">AI coverage report</a>
          <a class="button" href="../data/ai-cache/{html.escape(summary["slug"])}/weekly_brief_prompt.json">Weekly AI prompt</a>
          <a class="button" href="../data/ai-cache/{html.escape(summary["slug"])}/rewrite_prompts_current_open.jsonl">Current/open AI prompt queue</a>
        </div>
      </div>
    </section>
    <section>
      <div class="wrap">
        <h2>Current Research To Review</h2>
        <p class="plain">Showing up to 12 current/open records, sorted for patient-facing review. Verify all details in source records.</p>
        <div class="trial-list">{active_items or '<p class="plain">No current/open records found.</p>'}</div>
      </div>
    </section>
    <section>
      <div class="wrap">
        <h2>Top Landscape Signals</h2>
        <div class="grid">
          <div>{render_count_block("Top interventions", summary["top_interventions"])}</div>
          <div>{render_count_block("Top sponsors", summary["top_sponsors"])}</div>
          <div>{render_count_block("Top countries", summary["top_countries"])}</div>
        </div>
      </div>
    </section>
  </main>
</body>
</html>
"""


def render_publications_page(summary: dict[str, Any], trials: list[dict[str, Any]]) -> str:
    rows = []
    for trial in trials:
        for publication in trial.get("publications", []):
            rows.append((trial, publication))
    rows.sort(key=lambda item: (item[1].get("pub_date", ""), item[0].get("trial_id", "")), reverse=True)
    items = "\n".join(render_publication_item(trial, publication) for trial, publication in rows[:200])
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Publications - {html.escape(summary["name"])}</title>
  {shared_page_style()}
</head>
<body>
  <header>
    <div class="wrap">
      <div class="eyebrow">PubMed source layer</div>
      <h1>Publications Linked By Trial ID</h1>
      <p class="plain">This page lists PubMed records found by searching public trial identifiers. A publication link is an evidence source, not a clinical recommendation or proof of treatment value.</p>
      <div class="actions"><a class="button" href="index.html">Back to radar</a></div>
    </div>
  </header>
  <main>
    <section>
      <div class="wrap">
        <h2>Found Publications</h2>
        <p class="plain">{len(rows)} PubMed records are linked in the current source layer.</p>
        <div class="trial-list">{items or '<p class="plain">No PubMed records found in the current source layer.</p>'}</div>
      </div>
    </section>
  </main>
</body>
</html>
"""


def render_publication_item(trial: dict[str, Any], publication: dict[str, Any]) -> str:
    title = html.escape(publication.get("title") or "Untitled PubMed record")
    pmid = html.escape(publication.get("pmid") or "")
    trial_id = html.escape(trial.get("trial_id") or "")
    url = html.escape(publication.get("url") or "")
    journal = html.escape(publication.get("journal") or "Journal not listed")
    date = html.escape(publication.get("pub_date") or "Date not listed")
    link = f'<a href="{url}" target="_blank" rel="noreferrer">{title}</a>' if url else title
    return f"""<article class="trial-card">
      <h3>{link}</h3>
      <div class="meta-row">
        <span class="status-badge">PMID {pmid}</span>
        <span class="meta">Trial: <a href="trials/{trial_id}.html">{trial_id}</a></span>
        <span class="meta">{journal}</span>
        <span class="meta">{date}</span>
      </div>
    </article>"""


def write_ai_prompt_pack(
    root: Path,
    slug: str,
    trials: list[dict[str, Any]],
    summary: dict[str, Any] | None = None,
    diff: dict[str, Any] | None = None,
) -> None:
    prompt_path = root / f"data/ai-cache/{slug}/rewrite_prompts.jsonl"
    prompt_path.parent.mkdir(parents=True, exist_ok=True)
    write_jsonl(prompt_path, [build_ai_rewrite_prompt(trial) for trial in trials])

    current_open = sorted(
        [trial for trial in trials if trial.get("relevance") == "current" and not is_ai_explained(trial)],
        key=lambda trial: (status_priority(trial.get("status", "")), -date_sort_value(trial.get("last_update_posted", ""))),
    )
    priority_path = root / f"data/ai-cache/{slug}/rewrite_prompts_current_open.jsonl"
    write_jsonl(priority_path, [build_ai_rewrite_prompt(trial) for trial in current_open])

    if summary is not None and diff is not None:
        weekly_prompt_path = root / f"data/ai-cache/{slug}/weekly_brief_prompt.json"
        write_json(weekly_prompt_path, build_ai_weekly_brief_prompt(summary, diff, trials))
        coverage_report = render_ai_coverage_report(summary, trials, priority_path, weekly_prompt_path)
        (root / "reports/ai-coverage.md").write_text(coverage_report, encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def build_ai_rewrite_prompt(trial: dict[str, Any]) -> dict[str, Any]:
    return {
        "trial_id": trial["trial_id"],
        "cache_key": f"{trial['trial_id']}:{trial.get('last_update_posted') or 'no-date'}",
        "task": "Rewrite public registry fields into patient-friendly, source-grounded educational text.",
        "hard_rules": [
            "Do not decide eligibility.",
            "Do not rank, recommend, or compare treatments.",
            "Do not infer facts not present in source fields.",
            "Use may/might language for eligibility criteria.",
            "Return JSON only.",
        ],
        "source_fields": {
            "title": trial.get("title"),
            "brief_summary": trial.get("brief_summary"),
            "eligibility_excerpt": trial.get("eligibility", {}).get("criteria_excerpt"),
            "status": trial.get("status"),
            "phase": trial.get("phase"),
            "conditions": trial.get("conditions"),
            "interventions": trial.get("intervention_names"),
            "countries": trial.get("countries"),
        },
        "expected_json_schema": {
            "patient_title": "string",
            "patient_summary": "string",
            "what_researchers_are_studying": "string",
            "may_be_looking_for": ["string"],
            "may_exclude_people_who": ["string"],
            "questions_to_ask_clinician": ["string"],
            "uncertainty_notes": ["string"],
            "source_grounding": ["string"],
        },
    }


def build_ai_weekly_brief_prompt(summary: dict[str, Any], diff: dict[str, Any], trials: list[dict[str, Any]]) -> dict[str, Any]:
    current_trials = sorted(
        [trial for trial in trials if trial.get("relevance") == "current"],
        key=lambda trial: (status_priority(trial.get("status", "")), -date_sort_value(trial.get("last_update_posted", ""))),
    )
    return {
        "task": "Write a source-grounded weekly public research landscape brief for patients, caregivers, and NGOs.",
        "hard_rules": [
            "Use public registry data only.",
            "Do not recommend trials, treatments, drugs, devices, or procedures.",
            "Do not decide eligibility or imply a person should enroll.",
            "Do not rank therapies by safety or effectiveness.",
            "Use neutral language such as 'researchers are studying' and 'public records list'.",
        ],
        "summary": {
            "name": summary.get("name"),
            "updated": summary.get("updated"),
            "source": summary.get("source"),
            "total_trials": summary.get("total_trials"),
            "current_research_trials": summary.get("current_research_trials"),
            "recruiting_or_opening_trials": summary.get("recruiting_or_opening_trials"),
            "new_trials": summary.get("new_trials"),
            "changed_trials": summary.get("changed_trials"),
        },
        "source_changes": {
            "new": [
                {
                    "trial_id": trial.get("trial_id"),
                    "title": trial.get("title"),
                    "status": trial.get("status"),
                    "phase": trial.get("phase"),
                    "countries": trial.get("countries"),
                }
                for trial in diff.get("new", [])[:20]
            ],
            "changed": diff.get("changed", [])[:20],
        },
        "current_records_for_context": [
            {
                "trial_id": trial.get("trial_id"),
                "title": trial.get("title"),
                "status": trial.get("status"),
                "phase": trial.get("phase"),
                "countries": trial.get("countries"),
                "interventions": trial.get("intervention_names"),
                "last_update_posted": trial.get("last_update_posted"),
            }
            for trial in current_trials[:30]
        ],
        "expected_json_schema": {
            "plain_language_brief": "string",
            "topic_signals": ["string"],
            "new_or_changed_records_to_review": ["string"],
            "questions_for_advocates": ["string"],
            "source_grounding": ["string"],
        },
    }


def render_ai_coverage_report(summary: dict[str, Any], trials: list[dict[str, Any]], priority_path: Path, weekly_prompt_path: Path) -> str:
    stats = ai_coverage_stats(trials)
    current_missing = sorted(
        [trial for trial in trials if trial.get("relevance") == "current" and not is_ai_explained(trial)],
        key=lambda trial: (status_priority(trial.get("status", "")), -date_sort_value(trial.get("last_update_posted", ""))),
    )
    lines = [
        f"# {summary['name']} AI Coverage",
        "",
        f"Updated: {summary['updated']}",
        "",
        "This report tracks source-grounded AI explanation coverage. Missing coverage means the page falls back to registry-derived template text, not an AI rewrite. The browser does not call an LLM; AI rewrites are generated only when an operator runs the build-time cache command.",
        "",
        "| Scope | AI explained | Total | Missing |",
        "|---|---:|---:|---:|",
        f"| All public records | {stats['ai_total']} | {stats['total']} | {stats['total'] - stats['ai_total']} |",
        f"| Current/open records | {stats['current_ai']} | {stats['current_total']} | {stats['current_missing']} |",
        f"| Recruiting/opening records | {stats['recruiting_ai']} | {stats['recruiting_total']} | {stats['recruiting_missing']} |",
        "",
        "## Generated Prompt Packs",
        "",
        f"- Full rewrite prompts: `data/ai-cache/{summary['slug']}/rewrite_prompts.jsonl`",
        f"- Current/open priority prompts: `{priority_path.as_posix()}`",
        f"- Weekly brief prompt: `{weekly_prompt_path.as_posix()}`",
        "",
        "## Priority Current/Open Records Without AI Explanation",
        "",
    ]
    if current_missing:
        for trial in current_missing[:50]:
            lines.append(
                f"- `{trial.get('trial_id')}` {trial.get('title') or 'Untitled public record'} "
                f"({pretty_status(trial.get('status', ''))}, {trial.get('last_update_posted') or 'no update date'})"
            )
    else:
        lines.append("- All current/open records have reviewed AI explanation cache files.")
    lines.extend(
        [
            "",
            "## Safety Boundary",
            "",
            "AI outputs are allowed to summarize public registry fields, explain terms, and draft questions to discuss with a clinician. They must not decide eligibility, recommend treatments, rank therapies, or collect patient health data.",
            "",
        ]
    )
    return "\n".join(lines)


def detail_box(label: str, value: Any) -> str:
    return f'<div class="box"><span>{html.escape(label)}</span><strong>{html.escape(str(value or "Not listed"))}</strong></div>'


def html_pills(values: list[str]) -> str:
    return "".join(f'<span class="pill">{html.escape(str(value))}</span>' for value in values[:12])


def html_list(values: list[str], empty_text: str = "No question prompts generated for this record.") -> str:
    if not values:
        return f'<p class="plain">{html.escape(empty_text)}</p>'
    return "<ul>" + "".join(f"<li>{html.escape(value)}</li>" for value in values) + "</ul>"


def confusing_terms_for_trial(trial: dict[str, Any]) -> list[str]:
    haystack = " ".join(
        [
            str(trial.get("title") or ""),
            str(trial.get("brief_summary") or ""),
            " ".join(trial.get("conditions") or []),
            " ".join(trial.get("intervention_names") or []),
            " ".join(trial.get("intervention_types") or []),
            str(trial.get("phase") or ""),
            str(trial.get("status") or ""),
        ]
    ).lower()
    candidates = [
        (r"\bsle\b|systemic lupus erythematosus", "SLE: systemic lupus erythematosus, the medical name for lupus in many registry records."),
        (r"lupus nephritis|renal|kidney|proteinuria|glomerul", "Lupus nephritis / renal: lupus-related kidney inflammation or kidney monitoring terms."),
        (r"car\s*-?\s*t|cell therapy|ucar|t cell", "CAR-T / cell therapy: immune-cell therapy being studied in some records; this page does not say it is suitable for anyone."),
        (r"\bcd19\b", "CD19: an immune-cell marker that some cell therapy and antibody studies target."),
        (r"\bbcma\b", "BCMA: an immune-cell target that may appear in some cell therapy or antibody research."),
        (r"biologic|biological|antibody|\bmab\b|belimumab|anifrolumab|rituximab|obinutuzumab|telitacicept", "Biologic / antibody: an immune-targeting research intervention category."),
        (r"biomarker|assay|autoantibod|gene expression|blood test", "Biomarker: a measurable signal researchers may study in blood, tissue, imaging, or other public source fields."),
        (r"randomized|placebo|double-blind|open-label", "Randomized / placebo / blinded / open-label: study design terms that describe how researchers compare or observe groups."),
        (r"phase 1|early phase 1", "Phase 1: early research that often focuses on safety, dose, or tolerability questions."),
        (r"phase 2", "Phase 2: research that may explore dose, activity, or early effectiveness signals."),
        (r"phase 3", "Phase 3: larger confirmatory research in the public registry phase system."),
        (r"pharmacokinetic|pharmacodynamic|\bpk\b|\bpd\b", "PK / PD: terms about how a study drug moves through the body and what biological effects are measured."),
        (r"recruiting|not_yet_recruiting|enrolling_by_invitation|active_not_recruiting", "Recruitment status: public registry wording about whether a study is open, opening, invitation-only, or active without recruiting."),
        (r"inclusion|exclusion|eligibility", "Eligibility criteria: registry rules for a study. This page summarizes text but cannot decide eligibility."),
    ]
    terms: list[str] = []
    for pattern, explanation in candidates:
        if re.search(pattern, haystack):
            terms.append(explanation)
        if len(terms) >= 5:
            break
    return terms


def registry_source_grounding(trial: dict[str, Any]) -> list[str]:
    bullets = [
        f"Official registry record: {trial.get('trial_id') or 'ID not listed'}.",
        f"Public status and phase shown from registry fields: {pretty_status(trial.get('status') or '')}; {phase_label(trial.get('phase') or '')}.",
    ]
    if trial.get("intervention_names"):
        bullets.append("Interventions listed in the registry include: " + ", ".join(trial.get("intervention_names", [])[:4]) + ".")
    if trial.get("countries"):
        bullets.append("Countries listed in the normalized record include: " + ", ".join(trial.get("countries", [])[:4]) + ".")
    if trial.get("last_update_posted"):
        bullets.append(f"Latest public registry update date in this dataset: {trial.get('last_update_posted')}.")
    return bullets


def html_interventions(interventions: list[dict[str, Any]]) -> str:
    if not interventions:
        return '<p class="plain">No interventions listed in the normalized record.</p>'
    items = []
    for item in interventions[:12]:
        name = html.escape(item.get("name") or "Unnamed intervention")
        slug = html.escape(intervention_slug(normalize_label(item.get("name") or "Unknown")))
        kind = html.escape(item.get("type") or "type not listed")
        items.append(f'<li><strong><a href="../interventions/{slug}.html">{name}</a></strong> <span>({kind})</span></li>')
    return "<ul>" + "".join(items) + "</ul>"


def shared_page_style() -> str:
    return """<style>
    :root {
      --ink: #24211d;
      --muted: #6f6a60;
      --line: #d8d2c5;
      --bg: #f6f3ed;
      --surface: #fffdf8;
      --accent: #6d3f5f;
      --accent-soft: #f3edf2;
      --warn: #8a5a12;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      color: var(--ink);
      background: var(--bg);
      line-height: 1.5;
    }
    header { background: var(--surface); border-bottom: 1px solid var(--line); }
    section { background: var(--surface); border-bottom: 1px solid var(--line); }
    section:nth-child(even) { background: #fbf8f1; }
    .wrap { max-width: 1080px; margin: 0 auto; padding: 24px; }
    .app-nav { border-bottom: 1px solid var(--line); background: rgba(255,255,255,.96); position: sticky; top: 0; z-index: 5; }
    .app-nav .wrap { display: flex; justify-content: space-between; gap: 16px; align-items: center; padding-top: 12px; padding-bottom: 12px; }
    .brand { color: var(--ink); font-weight: 800; text-decoration: none; }
    .nav-links { display: flex; flex-wrap: wrap; gap: 8px; justify-content: flex-end; }
    .nav-links a { color: var(--muted); font-size: 13px; font-weight: 750; text-decoration: none; padding: 7px 8px; border-radius: 6px; }
    .nav-links a:hover { background: var(--accent-soft); color: var(--accent); }
    .boundary { color: var(--muted); font-size: 13px; margin-top: 10px; }
    .eyebrow { color: var(--accent); font-size: 13px; font-weight: 700; text-transform: uppercase; letter-spacing: 0; }
    h1 { margin: 8px 0 10px; font-size: clamp(28px, 4vw, 44px); line-height: 1.08; letter-spacing: 0; }
    h2 { margin: 0 0 14px; font-size: 22px; letter-spacing: 0; }
    h3 { margin: 18px 0 8px; font-size: 17px; letter-spacing: 0; }
    p { color: var(--muted); }
    a { color: #5c3b72; text-decoration-thickness: 1px; }
    .plain { color: #3f3a34; max-width: 860px; }
    .notice { border-left: 4px solid var(--warn); background: #fff8ea; padding: 14px 16px; color: #46340f; margin-top: 16px; }
    .ai-note { border-left: 4px solid #77506f; background: #f5edf2; padding: 14px 16px; color: #4e3448; margin-top: 16px; }
    .actions { display: flex; flex-wrap: wrap; gap: 10px; margin-top: 18px; }
    .button { display: inline-block; border: 1px solid var(--line); background: #fffdf8; color: var(--ink); padding: 10px 12px; border-radius: 6px; text-decoration: none; }
    .grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; }
    .box { border: 1px solid var(--line); background: #fbf8f1; padding: 13px; min-height: 86px; }
    .box span { display: block; color: var(--muted); font-size: 12px; margin-bottom: 4px; }
    .box strong { display: block; overflow-wrap: anywhere; }
    table { width: 100%; border-collapse: collapse; font-size: 14px; }
    th, td { text-align: left; vertical-align: top; padding: 10px; border-bottom: 1px solid var(--line); }
    th { color: var(--muted); font-size: 12px; text-transform: uppercase; background: #eee8dc; letter-spacing: 0; }
    ul { padding-left: 20px; color: #3f3a34; }
    li { margin: 6px 0; }
    .trial-list { display: grid; gap: 12px; }
    .trial-card { border: 1px solid var(--line); background: #fffdf8; padding: 15px; border-radius: 8px; }
    .trial-card h3 { margin: 0 0 8px; font-size: 18px; line-height: 1.28; letter-spacing: 0; }
    .meta-row { display: flex; flex-wrap: wrap; gap: 8px; margin: 8px 0; }
    .meta { color: var(--muted); font-size: 13px; }
    .pill { display: inline-block; border: 1px solid var(--line); background: #fffdf8; color: var(--muted); border-radius: 4px; padding: 4px 8px; margin: 2px 4px 2px 0; font-size: 13px; }
    .status-badge { display: inline-block; padding: 5px 8px; background: var(--accent-soft); color: var(--accent); border: 1px solid #d4c3d1; border-radius: 4px; font-size: 13px; font-weight: 700; }
    .topic-layout { display: grid; grid-template-columns: minmax(0, 1fr) 280px; gap: 22px; align-items: start; }
    .side-panel { border: 1px solid var(--line); background: #fffdf8; border-radius: 8px; padding: 15px; }
    .compact-section { padding-top: 18px; padding-bottom: 18px; }
    @media (max-width: 760px) {
      .wrap { padding: 18px; }
      .app-nav .wrap { display: block; }
      .nav-links { justify-content: flex-start; margin-top: 8px; }
      .grid { grid-template-columns: 1fr; }
      .topic-layout { grid-template-columns: 1fr; }
    }
  </style>"""


def render_compact_trial_item(trial: dict[str, Any], prefix: str = "trials/") -> str:
    trial_id = html.escape(trial.get("trial_id", ""))
    title = html.escape(trial.get("title") or trial.get("trial_id") or "Untitled public record")
    status = html.escape(pretty_status(trial.get("status", "")))
    phase = html.escape(phase_label(trial.get("phase", "N/A")))
    sponsor = html.escape(trial.get("sponsor") or "Sponsor not listed")
    updated = html.escape(trial.get("last_update_posted") or "No public update date")
    countries = html_pills(trial.get("countries", [])[:5])
    interventions = html_pills(trial.get("intervention_names", [])[:5])
    return f"""<article class="trial-card">
      <h3><a href="{html.escape(prefix)}{trial_id}.html">{title}</a></h3>
      <div class="meta-row">
        <span class="status-badge">{status}</span>
        <span class="meta">{trial_id}</span>
        <span class="meta">{phase}</span>
        <span class="meta">Updated: {updated}</span>
        <span class="meta">Sponsor: {sponsor}</span>
      </div>
      <div>{interventions or '<span class="pill">Intervention not listed</span>'}</div>
      <div>{countries or '<span class="pill">Locations not listed</span>'}</div>
    </article>"""


def render_count_block(title: str, rows: list[tuple[str, int]]) -> str:
    heading = f"<h3>{html.escape(title)}</h3>" if title else ""
    if not rows:
        return heading + '<p class="plain">No data listed.</p>'
    body = "".join(
        f"<tr><td>{html.escape(str(label or 'Unknown'))}</td><td style=\"text-align:right\">{count}</td></tr>"
        for label, count in rows
    )
    return f"{heading}<table><tbody>{body}</tbody></table>"


def render_change_item(trial: dict[str, Any]) -> str:
    trial_id = html.escape(trial.get("trial_id", ""))
    title = html.escape(trial.get("title") or trial.get("trial_id") or "Untitled public record")
    status = html.escape(pretty_status(trial.get("status", "")))
    return f'<article class="trial-card"><h3><a href="trials/{trial_id}.html">{trial_id}</a></h3><p class="plain">{title}</p><span class="status-badge">{status}</span></article>'


def render_changed_item(item: dict[str, Any]) -> str:
    trial_id = html.escape(item.get("trial_id", ""))
    title = html.escape(item.get("title") or item.get("trial_id") or "Untitled public record")
    changed_fields = ", ".join(item.get("changes", {}).keys()) or "tracked fields"
    return f'<article class="trial-card"><h3><a href="trials/{trial_id}.html">{trial_id}</a></h3><p class="plain">{title}</p><span class="meta">Changed: {html.escape(changed_fields)}</span></article>'


def intervention_slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", str(value or "").lower()).strip("-")
    return slug or "unknown"


def relevance_priority(trial: dict[str, Any]) -> int:
    return {"current": 0, "unclear": 1, "historical": 2}.get(str(trial.get("relevance", "")), 3)


def status_priority(status: str) -> int:
    order = {
        "RECRUITING": 0,
        "NOT_YET_RECRUITING": 1,
        "ENROLLING_BY_INVITATION": 2,
        "ACTIVE_NOT_RECRUITING": 3,
        "UNKNOWN": 4,
        "COMPLETED": 5,
        "SUSPENDED": 6,
        "TERMINATED": 7,
        "WITHDRAWN": 8,
    }
    return order.get(str(status or ""), 9)


def date_sort_value(value: str) -> int:
    text = str(value or "")
    match = re.match(r"^(\d{4})(?:-(\d{2}))?(?:-(\d{2}))?", text)
    if not match:
        return 0
    year = int(match.group(1))
    month = int(match.group(2) or 1)
    day = int(match.group(3) or 1)
    return year * 10000 + month * 100 + day


def highest_phase_label(phases: list[str]) -> str:
    ranks = [
        ("Phase 4", 5),
        ("Phase 3", 4),
        ("Phase 2", 3),
        ("Phase 1", 2),
        ("Early Phase 1", 1),
    ]
    best = ("N/A", 0)
    for phase in phases:
        text = str(phase or "N/A")
        for label, rank in ranks:
            if label in text and rank > best[1]:
                best = (label, rank)
    return best[0]


def html_locations(locations: list[dict[str, str]]) -> str:
    if not locations:
        return '<p class="plain">No locations listed in the normalized record.</p>'
    items = []
    for location in locations[:20]:
        text = ", ".join(
            part
            for part in [
                location.get("facility", ""),
                location.get("city", ""),
                location.get("state", ""),
                location.get("country", ""),
            ]
            if part
        )
        items.append(f"<li>{html.escape(text or 'Location details not listed')}</li>")
    return "<ul>" + "".join(items) + "</ul>"


def html_source_records(records: list[dict[str, Any]]) -> str:
    if not records:
        return '<p class="plain">No source records listed.</p>'
    rows = []
    for record in records:
        source = html.escape(record.get("source") or "Unknown source")
        record_id = html.escape(record.get("record_id") or record.get("id") or "No ID")
        updated = html.escape(record.get("last_update_posted") or record.get("date") or "No public update date")
        url = record.get("url") or ""
        label = f"{source}: {record_id}"
        link = f'<a href="{html.escape(url)}" target="_blank" rel="noreferrer">{label}</a>' if url else label
        rows.append(f"<li><strong>{link}</strong><br><span>Updated: {updated}</span></li>")
    return "<ul>" + "".join(rows) + "</ul>"


def pretty_status(value: str) -> str:
    return re.sub(r"\b\w", lambda match: match.group(0).upper(), str(value or "Unknown").replace("_", " ").lower())


def phase_label(phase: str) -> str:
    if not phase or phase == "N/A":
        return "No standard drug phase listed"
    return phase


def format_enrollment_text(trial: dict[str, Any]) -> str:
    count = trial.get("enrollment_count")
    if not count:
        return "Not listed"
    kind = f" ({str(trial.get('enrollment_type', '')).lower()})" if trial.get("enrollment_type") else ""
    return f"{count} participants{kind}"


def format_age_text(eligibility: dict[str, Any]) -> str:
    return f"{eligibility.get('minimum_age') or 'No minimum listed'} to {eligibility.get('maximum_age') or 'No maximum listed'}"


TOPIC_DEFINITIONS = [
    {
        "id": "nephritis",
        "title": "Kidney / lupus nephritis",
        "description": "Kidney-related SLE studies, including lupus nephritis and renal monitoring.",
        "overview": "This area focuses on how lupus affects the kidneys, how kidney inflammation is measured, and how researchers track kidney-related outcomes in public studies.",
        "terms": ["lupus nephritis", "renal", "proteinuria", "kidney biopsy"],
        "questions": [
            "What kidney-related question is this study trying to answer?",
            "Which outcomes are being measured, and are they registry or lab outcomes?",
            "Which details should I verify in the official registry before discussing this with a clinician?",
        ],
    },
    {
        "id": "cell-therapy",
        "title": "Cell therapy / CAR-T",
        "description": "Cell therapy, CD19, BCMA, CAR-T, and immune-reset approaches.",
        "overview": "This area groups public records involving cell-based approaches and immune-cell targeting. It is a research landscape view, not a statement that these approaches are suitable for any person.",
        "terms": ["CAR-T", "CD19", "BCMA", "cell therapy"],
        "questions": [
            "What type of cell therapy or immune target is named in the public record?",
            "Is the study early-stage, recruiting, or already completed?",
            "What safety and monitoring questions should be discussed with a licensed clinician?",
        ],
    },
    {
        "id": "biologics",
        "title": "Biologics and antibodies",
        "description": "Antibody and biologic studies such as belimumab, anifrolumab, rituximab, and similar agents.",
        "overview": "This area collects public studies involving biologics, monoclonal antibodies, and immune-pathway drugs that appear in lupus-related registry records.",
        "terms": ["biologic", "monoclonal antibody", "belimumab", "anifrolumab"],
        "questions": [
            "Which immune pathway or intervention name is listed in the record?",
            "Is the record studying lupus broadly or a more specific lupus group?",
            "What does the official registry say about status, phase, and locations?",
        ],
    },
    {
        "id": "asia",
        "title": "Asia-Pacific activity",
        "description": "Research sites and sponsors across East Asia, Southeast Asia, South Asia, and Oceania.",
        "overview": "This area is a geographic view of public registry records with Asia-Pacific countries or regions listed. It helps advocacy groups see where public research activity is appearing.",
        "terms": ["site country", "sponsor", "recruitment status", "region"],
        "questions": [
            "Which countries or regions are listed in the public record?",
            "Is the site recruiting, active, completed, or unclear?",
            "Where is the official registry source for location details?",
        ],
    },
    {
        "id": "pediatric",
        "title": "Children and teens",
        "description": "Studies that mention children, adolescents, juvenile lupus, or pediatric populations.",
        "overview": "This area gathers public records that mention pediatric, juvenile, child, adolescent, or teen-related lupus research signals.",
        "terms": ["pediatric", "juvenile lupus", "adolescent", "age criteria"],
        "questions": [
            "What age range does the public registry list?",
            "Is the study specifically pediatric, or does it include younger people among a wider group?",
            "Which questions should a family discuss with a pediatric specialist or clinician?",
        ],
    },
    {
        "id": "pregnancy",
        "title": "Pregnancy and reproductive health",
        "description": "Research involving pregnancy, contraception, fertility, estrogen, or reproductive questions.",
        "overview": "This area collects public records that mention pregnancy, reproductive health, contraception, estrogen, fertility, or related lupus research questions.",
        "terms": ["pregnancy", "fertility", "contraception", "estrogen"],
        "questions": [
            "What reproductive-health question is the public record studying?",
            "Which population or exclusion language should be checked in the official registry?",
            "What should be discussed with a licensed clinician before drawing any conclusion?",
        ],
    },
]

HOME_TOPICS = [(topic["id"], topic["title"], topic["description"]) for topic in TOPIC_DEFINITIONS]


def home_search_text(trial: dict[str, Any]) -> str:
    return " ".join(
        [
            str(trial.get("trial_id", "")),
            str(trial.get("title", "")),
            str(trial.get("status", "")),
            str(trial.get("phase", "")),
            str(trial.get("sponsor", "")),
            " ".join(trial.get("conditions", [])),
            " ".join(trial.get("intervention_names", [])),
            " ".join(trial.get("intervention_types", [])),
            " ".join(trial.get("countries", [])),
            " ".join(trial.get("regions", [])),
            str(trial.get("plain_language_summary", "")),
        ]
    ).lower()


def home_lupus_lane(trial: dict[str, Any]) -> str:
    text = home_search_text(trial)
    if re.search(r"nephritis|kidney|renal|glomerul|proteinuria|albuminuria", text):
        return "nephritis"
    if re.search(r"car\s*-?\s*t|cart|cell therapy|cd19|bcma|ucar|t cell|stem cell|hematopoietic", text):
        return "cell-therapy"
    if re.search(r"biological|antibody|\bmab\b|belimumab|anifrolumab|rituximab|obinutuzumab|telitacicept|ianalumab|dapirolizumab", text):
        return "biologics"
    if re.search(r"pediatric|paediatric|juvenile|child|children|adolescent|teen", text):
        return "pediatric"
    if re.search(r"pregnan|fertility|reproductive|estrogen|birth control|contracept|postmenopausal|menopause", text):
        return "pregnancy"
    if re.search(r"biomarker|diagnostic|blood sample|blood test|receptor|imaging|ultrasound|assay|gene expression|autoantibod", text):
        return "diagnostics"
    if re.search(r"diet|exercise|education|counseling|self-management|rehabilitation|quality of life|sleep|fatigue", text):
        return "lifestyle"
    return "general"


def render_home_page(summary: dict[str, Any], diff: dict[str, Any], trials: list[dict[str, Any]]) -> str:
    current_trials = [trial for trial in trials if trial.get("relevance") == "current"]
    ai_stats = ai_coverage_stats(trials)
    lane_counts = Counter(home_lupus_lane(trial) for trial in current_trials)
    asia_count = sum(
        1
        for trial in current_trials
        if any(region in {"East Asia", "Southeast Asia", "South Asia", "Oceania"} for region in trial.get("regions", []))
    )
    lane_counts["asia"] = asia_count
    topic_cards = "\n".join(
        f"""<a class="topic-row" href="topics/{html.escape(action)}.html">
          <span>{html.escape(title)}</span>
          <strong>{lane_counts.get(action, 0)} records</strong>
        </a>"""
        for action, title, description in HOME_TOPICS
    )
    title = html.escape(summary["name"])
    current_ai = ai_stats["current_ai"]
    current_total = ai_stats["current_total"]
    current_missing = ai_stats["current_missing"]
    ai_total = ai_stats["ai_total"]
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
  <style>
    :root {{ --ink:#24211d; --muted:#6f6a60; --line:#d8d2c5; --bg:#f6f3ed; --surface:#fffdf8; --accent:#6d3f5f; --soft:#f3edf2; --warn:#8a5a12; }}
    * {{ box-sizing:border-box; }}
    body {{ margin:0; font-family:Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; color:var(--ink); background:var(--bg); line-height:1.5; }}
    a {{ color:inherit; }}
    .wrap {{ max-width:1120px; margin:0 auto; padding:22px 28px; }}
    .nav {{ border-bottom:1px solid var(--line); background:rgba(255,255,255,.96); position:sticky; top:0; z-index:5; }}
    .nav .wrap {{ display:flex; justify-content:space-between; gap:16px; align-items:center; padding-top:12px; padding-bottom:12px; }}
    .brand {{ font-weight:800; text-decoration:none; }}
    .links {{ display:flex; gap:8px; flex-wrap:wrap; justify-content:flex-end; }}
    .links a {{ color:var(--muted); font-size:13px; font-weight:750; text-decoration:none; padding:7px 8px; border-radius:6px; }}
    .links a:hover {{ background:var(--soft); color:var(--accent); }}
    .button {{ border:1px solid var(--line); background:#fffdf8; padding:9px 12px; border-radius:4px; text-decoration:none; font-weight:750; font-size:14px; color:#5c3b72; }}
    .button.primary {{ background:var(--accent); color:#fffdf8; border-color:var(--accent); }}
    .hero {{ background:#fffdf8; border-bottom:1px solid var(--line); }}
    .hero .wrap {{ padding-top:30px; padding-bottom:30px; }}
    .eyebrow {{ color:var(--accent); font-size:12px; text-transform:uppercase; font-weight:800; }}
    h1 {{ font-size:clamp(30px,4vw,42px); line-height:1.08; margin:8px 0 10px; letter-spacing:0; max-width:720px; }}
    h2 {{ font-size:20px; margin:0 0 10px; letter-spacing:0; }}
    p {{ color:var(--muted); max-width:780px; }}
    .lead {{ font-size:16px; color:#514b43; margin:0; }}
    .boundary {{ color:var(--muted); font-size:13px; margin-top:12px; }}
    .notice {{ border:1px solid #f0dfb8; background:#fffaf0; color:#46340f; padding:10px 12px; border-radius:6px; margin-top:14px; max-width:900px; font-size:13px; }}
    .actions {{ display:flex; gap:10px; flex-wrap:wrap; margin-top:22px; }}
    .finder-layout {{ display:grid; grid-template-columns:minmax(0,1.35fr) minmax(280px,.65fr); gap:24px; align-items:start; margin-top:22px; }}
    .finder-panel {{ border:1px solid var(--line); background:#fffdf8; border-radius:4px; padding:18px; }}
    .finder-panel h2, .start-panel h2 {{ font-size:16px; margin:0 0 10px; }}
    .home-search {{ border:0; background:transparent; padding:0; max-width:none; margin-top:0; }}
    .search-row {{ display:grid; grid-template-columns:minmax(0,1fr) auto; gap:10px; }}
    .search-row input {{ width:100%; border:1px solid var(--line); border-radius:4px; padding:14px 15px; font:inherit; font-size:16px; color:var(--ink); }}
    .search-row input:focus {{ outline:3px solid rgba(109,63,95,.18); border-color:var(--accent); }}
    .search-row button {{ border:1px solid var(--accent); background:var(--accent); color:#fffdf8; border-radius:4px; padding:0 18px; font:inherit; font-weight:800; cursor:pointer; }}
    section {{ background:var(--surface); border-bottom:1px solid var(--line); }}
    section:nth-of-type(even) {{ background:#fbf8f1; }}
    .start-panel {{ border:1px solid var(--line); background:#fffdf8; border-radius:4px; padding:14px; }}
    .route-grid {{ display:grid; grid-template-columns:1fr; gap:0; border-top:1px solid var(--line); }}
    .route-card {{ border:0; border-bottom:1px solid var(--line); background:#fffdf8; border-radius:0; padding:12px 0; text-decoration:none; min-height:0; }}
    .route-card:last-child {{ border-bottom:0; }}
    .route-card strong {{ display:block; font-size:15px; margin-bottom:3px; }}
    .route-card span {{ color:var(--muted); font-size:13px; }}
    .route-card:hover, .topic-row:hover {{ background:#fffaf2; }}
    .ai-strip {{ display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:8px; margin-top:14px; }}
    .ai-strip a, .ai-strip span {{ border:1px solid var(--line); background:#fbf8f1; border-radius:4px; padding:9px 10px; font-size:13px; text-decoration:none; color:var(--muted); }}
    .ai-strip strong {{ color:var(--ink); }}
    .tool-list {{ border:1px solid var(--line); background:#fffdf8; border-radius:4px; overflow:hidden; margin-top:12px; }}
    .tool-row {{ display:grid; grid-template-columns:1fr auto; gap:16px; padding:15px 16px; border-bottom:1px solid var(--line); text-decoration:none; align-items:center; }}
    .tool-row:last-child {{ border-bottom:0; }}
    .tool-row strong {{ display:block; font-size:15px; margin-bottom:3px; }}
    .tool-row span {{ color:var(--muted); font-size:13px; }}
    .tool-row em {{ color:var(--accent); font-style:normal; font-weight:800; font-size:13px; white-space:nowrap; }}
    .tool-row:hover {{ background:#fffaf2; }}
    .topic-list {{ border:1px solid var(--line); background:#fffdf8; border-radius:4px; overflow:hidden; margin-top:12px; }}
    .topic-row {{ display:flex; justify-content:space-between; gap:14px; padding:14px 16px; text-decoration:none; border-bottom:1px solid var(--line); }}
    .topic-row:last-child {{ border-bottom:0; }}
    .topic-row span {{ font-weight:750; }}
    .topic-row strong {{ color:var(--muted); font-size:13px; white-space:nowrap; }}
    @media (max-width:820px) {{
      .wrap {{ padding:20px; }}
      .nav .wrap {{ display:block; }}
      .links {{ justify-content:flex-start; margin-top:10px; }}
      .finder-layout {{ grid-template-columns:1fr; }}
      .search-row {{ grid-template-columns:1fr; }}
      .search-row button {{ min-height:48px; }}
      .route-grid {{ grid-template-columns:1fr; }}
      .ai-strip {{ grid-template-columns:1fr; }}
      .tool-row {{ grid-template-columns:1fr; }}
      .topic-row {{ display:block; }}
      .topic-row strong {{ display:block; margin-top:4px; }}
    }}
  </style>
</head>
<body>
  <nav class="nav">
    <div class="wrap">
      <a class="brand" href="index.html">{PRODUCT_NAME}</a>
      <div class="links">
        <a href="finder.html">Find</a>
        <a href="explorer.html">Learn</a>
        <a href="changes.html">Updates</a>
      </div>
    </div>
  </nav>
  <header class="hero">
    <div class="wrap">
      <div class="eyebrow">AI clinical trial finder for patients</div>
      <h1>Find public trial records, then understand the research context.</h1>
      <p class="lead">TrialCompass helps patients search by source, condition, and location, then verify public registry details with a clinician.</p>
      <div class="finder-layout">
        <div class="finder-panel">
          <h2>Find trials near a location</h2>
          <form class="home-search" action="finder.html" method="get" aria-label="Find public trial records">
            <div class="search-row">
              <input name="condition" type="search" placeholder="Condition, for example systemic lupus erythematosus" aria-label="Condition">
              <button type="submit">Find</button>
            </div>
          </form>
          <div class="boundary">Default source: ClinicalTrials.gov. Public data only. Not medical advice. This tool does not determine eligibility.</div>
          <div class="ai-strip" aria-label="AI coverage">
            <span><strong>AI explained records:</strong> {current_ai} / {current_total} current records</span>
            <span><strong>{current_missing}</strong> current records queued for optional generation</span>
            <a href="explorer.html?reading=ai"><strong>{ai_total}</strong> reviewed AI explanations available</a>
          </div>
        </div>
        <aside class="start-panel" aria-label="Primary routes">
          <h2>Start here</h2>
          <div class="route-grid">
            <a class="route-card" href="finder.html"><strong>Find</strong><span>Choose sources, condition, location, and radius.</span></a>
            <a class="route-card" href="explorer.html"><strong>Learn</strong><span>Explore research areas, terms, and public registry fields.</span></a>
            <a class="route-card" href="changes.html"><strong>Recent updates</strong><span>New and changed public registry records.</span></a>
          </div>
        </aside>
      </div>
    </div>
  </header>
  <main>
    <section id="ai-tools">
      <div class="wrap">
        <h2>AI research tools</h2>
        <p class="boundary">Visible AI paths with cost controls: guided search runs locally with no API call; explanations and briefs are generated only when an operator runs the build-time AI commands.</p>
        <div class="tool-list">
          <a class="tool-row" href="explorer.html?assistant=1"><span><strong>Local guided search</strong>Ask for records by topic, status, country, NCT ID, publication layer, or AI-explained status. This maps text to filters in the browser.</span><em>No API</em></a>
          <a class="tool-row" href="explorer.html?reading=ai"><span><strong>Reviewed AI explanations</strong>Open records that already have source-grounded explanation cache files from a prior generation run.</span><em>{ai_total} cached</em></a>
          <a class="tool-row" href="explorer.html?reading=ai"><span><strong>AI record reader</strong>Read cached plain-language context, source grounding, and clinician discussion questions when available.</span><em>Cached</em></a>
          <a class="tool-row" href="weekly-brief.html"><span><strong>Build-time weekly brief</strong>Review the public-data changes and generate the AI brief only when needed.</span><em>On demand</em></a>
        </div>
      </div>
    </section>
    <section id="topics">
      <div class="wrap">
        <h2>Research areas</h2>
        <div class="topic-list">{topic_cards}</div>
      </div>
    </section>
  </main>
</body>
</html>
"""


def write_topic_pages(root: Path, summary: dict[str, Any], trials: list[dict[str, Any]]) -> None:
    topic_root = root / "site/topics"
    if topic_root.exists():
        shutil.rmtree(topic_root)
    topic_root.mkdir(parents=True, exist_ok=True)
    for topic in TOPIC_DEFINITIONS:
        (topic_root / f"{topic['id']}.html").write_text(render_topic_page(summary, topic, trials), encoding="utf-8")


def topic_matches(topic_id: str, trial: dict[str, Any]) -> bool:
    if topic_id == "asia":
        return any(region in {"East Asia", "Southeast Asia", "South Asia", "Oceania"} for region in trial.get("regions", []))
    return home_lupus_lane(trial) == topic_id


def render_topic_page(summary: dict[str, Any], topic: dict[str, Any], trials: list[dict[str, Any]]) -> str:
    current_matches = [trial for trial in trials if trial.get("relevance") == "current" and topic_matches(topic["id"], trial)]
    current_matches.sort(key=lambda trial: (status_priority(trial.get("status", "")), -date_sort_value(trial.get("last_update_posted", ""))))
    recruiting_count = sum(1 for trial in current_matches if trial.get("status") in RECRUITING_STATUSES)
    cards = "\n".join(render_compact_trial_item(trial, prefix="../trials/") for trial in current_matches[:8])
    terms = "".join(f"<span class=\"pill\">{html.escape(term)}</span>" for term in topic["terms"])
    questions = html_list(topic["questions"])
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(topic['title'])} - {html.escape(summary['name'])}</title>
  {shared_page_style()}
</head>
<body>
  <nav class="app-nav">
    <div class="wrap">
      <a class="brand" href="../index.html">{PRODUCT_NAME}</a>
      <div class="nav-links">
        <a href="../finder.html">Find</a>
        <a href="../explorer.html">Learn</a>
        <a href="../changes.html">Updates</a>
      </div>
    </div>
  </nav>
  <header>
    <div class="wrap">
      <div class="eyebrow">Research area</div>
      <h1>{html.escape(topic['title'])}</h1>
      <p class="plain">{html.escape(topic['overview'])}</p>
      <div class="boundary">Public data only. Not medical advice.</div>
    </div>
  </header>
  <main>
    <section>
      <div class="wrap topic-layout">
        <div>
          <div class="compact-section">
            <h2>About this area</h2>
            <p class="plain">{html.escape(topic['description'])}</p>
            <h3>Common terms</h3>
            <div>{terms}</div>
          </div>
          <div class="compact-section">
            <h2>Open records</h2>
            <p class="plain">Showing up to 8 current/open public records.</p>
            <div class="trial-list">{cards or '<p class="plain">No current/open public records found for this topic in the latest local dataset.</p>'}</div>
          </div>
        </div>
        <aside class="side-panel">
          <h2>Refine</h2>
          <div class="grid" style="grid-template-columns:1fr; gap:10px;">
            {detail_box("Current/open records", len(current_matches))}
            {detail_box("Recruiting/opening", recruiting_count)}
          </div>
          <div class="actions">
            <a class="button" href="../explorer.html?topic={html.escape(topic['id'])}">View in explorer</a>
            <a class="button" href="../explorer.html?topic={html.escape(topic['id'])}&status=recruiting">Open studies</a>
            <a class="button" href="../explorer.html?topic={html.escape(topic['id'])}&region=non-us">Outside US</a>
          </div>
          <h3>Questions for a clinician</h3>
          {questions}
        </aside>
      </div>
    </section>
  </main>
</body>
</html>
"""


def render_static_site(summary: dict[str, Any], diff: dict[str, Any], trials: list[dict[str, Any]]) -> str:
    public_trials = [
        {
            "trial_id": trial["trial_id"],
            "title": trial["title"],
            "status": trial["status"],
            "relevance": trial["relevance"],
            "phase": trial["phase"],
            "sponsor": trial["sponsor"],
            "conditions": trial.get("conditions", []),
            "countries": trial["countries"],
            "regions": trial.get("regions", []),
            "intervention_names": trial["intervention_names"],
            "intervention_types": trial["intervention_types"],
            "last_update_posted": trial["last_update_posted"],
            "source_url": trial["source_url"],
            "plain_language_summary": trial["plain_language_summary"],
            "questions_to_ask": trial["questions_to_ask"],
            "ai_explained": is_ai_explained(trial),
            "publication_count": len(trial.get("publications", [])),
        }
        for trial in trials
    ]
    ai_explained_count = sum(1 for trial in public_trials if trial["ai_explained"])
    ai_stats = ai_coverage_stats(trials)
    pubmed_linked_count = sum(1 for trial in public_trials if trial["publication_count"])
    payload = {
        "summary": summary,
        "diff": {
            "new": [
                {
                    "trial_id": trial["trial_id"],
                    "title": trial["title"],
                    "source_url": trial["source_url"],
                }
                for trial in diff["new"][:50]
            ],
            "changed": diff["changed"][:50],
        },
        "trials": public_trials,
    }
    data_json = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
    title = html.escape(summary["name"])
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
  <style>
    :root {{
      color-scheme: light;
      --ink: #24211d;
      --muted: #6f6a60;
      --line: #d8d2c5;
      --bg: #f6f3ed;
      --surface: #fffdf8;
      --accent: #6d3f5f;
      --accent-soft: #f3edf2;
      --warn: #8a5a12;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      color: var(--ink);
      background: var(--bg);
      line-height: 1.45;
    }}
    header {{
      background: var(--surface);
      border-bottom: 1px solid var(--line);
    }}
    .wrap {{
      max-width: 1180px;
      margin: 0 auto;
      padding: 24px;
    }}
    .top-nav {{
      position: sticky;
      top: 0;
      z-index: 10;
      background: rgba(255, 255, 255, 0.94);
      border-bottom: 1px solid var(--line);
      backdrop-filter: blur(10px);
    }}
    .top-nav .wrap {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
      padding-top: 12px;
      padding-bottom: 12px;
    }}
    .brand {{
      font-weight: 800;
      color: var(--ink);
      text-decoration: none;
    }}
    .nav-links {{
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
      justify-content: flex-end;
    }}
    .nav-links a {{
      color: var(--muted);
      font-size: 13px;
      font-weight: 700;
      padding: 7px 9px;
      text-decoration: none;
      border-radius: 4px;
    }}
    .nav-links a:hover {{
      background: var(--accent-soft);
      color: var(--accent);
    }}
    .eyebrow {{
      color: var(--accent);
      font-size: 13px;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0;
    }}
    h1 {{
      margin: 8px 0 12px;
      font-size: clamp(30px, 4vw, 44px);
      line-height: 1.08;
      letter-spacing: 0;
    }}
    h2 {{
      margin: 0 0 16px;
      font-size: 22px;
      letter-spacing: 0;
    }}
    p {{ color: var(--muted); max-width: 820px; }}
    .hero {{
      background: #fffdf8;
    }}
    .hero-grid {{
      padding-top: 28px;
      padding-bottom: 22px;
    }}
    .hero-copy p {{
      font-size: 16px;
      color: #514b43;
      margin: 0;
    }}
    .hero-panel {{
      border: 1px solid #d4c3d1;
      background: rgba(255, 255, 255, 0.86);
      padding: 18px;
      border-radius: 8px;
      box-shadow: none;
    }}
    .hero-panel strong {{
      display: block;
      margin-bottom: 8px;
      font-size: 16px;
    }}
    .hero-panel p {{
      margin: 0;
      font-size: 13px;
    }}
    .metrics {{
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 12px;
      margin-top: 18px;
    }}
    .metric {{
      background: #fffdf8;
      border: 1px solid var(--line);
      padding: 12px;
      min-height: 74px;
      border-radius: 8px;
    }}
    .metric strong {{
      display: block;
      font-size: 24px;
      line-height: 1;
      margin-bottom: 8px;
    }}
    .metric span {{ color: var(--muted); font-size: 14px; }}
    .ai-metric {{
      background: #f5edf2;
      border-color: #d8c2d1;
    }}
    .ai-metric strong, .ai-badge {{ color: #6d3f5f; }}
    main section {{
      border-bottom: 1px solid var(--line);
      background: var(--surface);
    }}
    main section:nth-child(even) {{ background: #fbf8f1; }}
    .notice {{
      border-left: 4px solid var(--warn);
      background: #fff8ea;
      padding: 14px 16px;
      color: #46340f;
      margin-top: 18px;
      border-radius: 0 8px 8px 0;
    }}
    .controls {{
      display: grid;
      grid-template-columns: 1fr;
      gap: 10px;
      margin: 14px 0 16px;
    }}
    .explorer-workspace {{
      display: grid;
      grid-template-columns: 270px minmax(0, 1fr);
      gap: 22px;
      align-items: start;
    }}
    .filter-rail {{
      position: sticky;
      top: 68px;
      border: 1px solid var(--line);
      background: #fffdf8;
      border-radius: 4px;
      padding: 14px;
    }}
    .results-panel {{
      min-width: 0;
    }}
    .guide-panel {{
      border: 0;
      background: transparent;
      padding: 0;
      margin: 0;
    }}
    .guide-panel h3 {{
      margin: 0 0 6px;
      font-size: 18px;
      letter-spacing: 0;
    }}
    .guide-panel p {{
      margin: 0 0 14px;
      font-size: 13px;
    }}
    .assistant-panel {{
      border: 1px solid #d4c3d1;
      background: #fffdf8;
      border-radius: 4px;
      padding: 14px;
      margin-bottom: 14px;
    }}
    .assistant-panel h2 {{
      margin: 0 0 6px;
      font-size: 18px;
    }}
    .assistant-panel p {{
      margin: 0 0 12px;
      font-size: 13px;
    }}
    .assistant-examples {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin-top: 10px;
    }}
    .assistant-example {{
      border: 1px solid var(--line);
      background: #fbf8f1;
      color: var(--ink);
      padding: 7px 9px;
      border-radius: 4px;
      font: inherit;
      font-size: 13px;
      cursor: pointer;
    }}
    .assistant-response {{
      border-left: 3px solid var(--accent);
      background: #f5edf2;
      color: #4e3448;
      padding: 10px 12px;
      margin-top: 10px;
      font-size: 13px;
      display: none;
    }}
    .assistant-response.visible {{ display: block; }}
    .search-row {{
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 10px;
      margin-bottom: 14px;
    }}
    .search-row input {{
      min-height: 52px;
      font-size: 16px;
      border-color: #d4c3d1;
    }}
    .search-row input:focus, select:focus {{
      outline: 3px solid rgba(109, 63, 95, 0.16);
      border-color: var(--accent);
    }}
    .search-row .primary-action {{
      min-height: 52px;
      border-radius: 4px;
      padding-left: 18px;
      padding-right: 18px;
    }}
    .guide-controls {{
      display: grid;
      grid-template-columns: 1fr;
      gap: 10px;
    }}
    .guide-field label {{
      display: block;
      color: var(--muted);
      font-size: 12px;
      font-weight: 800;
      margin-bottom: 5px;
      text-transform: uppercase;
      letter-spacing: 0;
    }}
    details.advanced-filters {{
      border: 1px solid var(--line);
      background: #fffdf8;
      border-radius: 4px;
      padding: 12px 14px;
      margin: 14px 0 0;
    }}
    details.advanced-filters summary {{
      cursor: pointer;
      color: var(--ink);
      font-weight: 800;
    }}
    input, select {{
      width: 100%;
      border: 1px solid var(--line);
      background: #fffdf8;
      color: var(--ink);
      padding: 11px 12px;
      font: inherit;
      border-radius: 6px;
    }}
    .quick-actions {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin: 18px 0 4px;
    }}
    .quick-action {{
      border: 1px solid #d4c3d1;
      background: #fffdf8;
      color: var(--accent);
      padding: 9px 12px;
      border-radius: 4px;
      font: inherit;
      font-weight: 650;
      cursor: pointer;
      text-decoration: none;
    }}
    .quick-action:hover, .secondary-button:hover {{
      border-color: var(--accent);
      background: #fffaf2;
    }}
    .primary-action {{
      display: inline-block;
      border: 1px solid var(--accent);
      background: var(--accent);
      color: #fffdf8;
      padding: 10px 14px;
      border-radius: 4px;
      font: inherit;
      font-weight: 750;
      cursor: pointer;
      text-decoration: none;
    }}
    .primary-action:hover {{
      background: #5a334f;
    }}
    .start-grid {{
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 14px;
      margin-top: 16px;
    }}
    .start-card {{
      border: 1px solid var(--line);
      background: #fffdf8;
      padding: 18px;
      min-height: 180px;
      border-radius: 8px;
    }}
    .start-card strong {{
      display: block;
      margin: 8px 0 6px;
      font-size: 18px;
    }}
    .start-card p {{
      margin: 0 0 12px;
      font-size: 13px;
    }}
    .result-summary {{
      border: 1px solid var(--line);
      background: #fffdf8;
      padding: 14px 16px;
      margin: 0 0 12px;
      color: #28433f;
      border-radius: 4px;
    }}
    .result-summary strong {{
      color: #18312e;
    }}
    .lupus-focus-grid {{
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 12px;
      margin-top: 16px;
    }}
    .focus-tile {{
      border: 1px solid var(--line);
      background: #fffdf8;
      padding: 16px;
      min-height: 188px;
      border-radius: 8px;
      transition: border-color 140ms ease, background 140ms ease;
    }}
    .focus-tile:hover {{
      border-color: #c7adc2;
      box-shadow: none;
      
    }}
    .focus-tile strong {{
      display: block;
      font-size: 17px;
      margin: 6px 0;
    }}
    .focus-count {{
      color: var(--accent);
      font-size: 24px;
      font-weight: 800;
      line-height: 1;
    }}
    .focus-tile p {{
      margin: 0 0 12px;
      font-size: 13px;
    }}
    .guide-grid {{
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 14px;
      margin-top: 16px;
    }}
    .guide-item {{
      border: 1px solid var(--line);
      background: #fffdf8;
      padding: 16px;
      min-height: 118px;
      border-radius: 8px;
    }}
    .brief-grid {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 14px;
      margin-top: 16px;
    }}
    .brief-item {{
      border: 1px solid var(--line);
      background: #fffdf8;
      padding: 17px;
      border-radius: 8px;
    }}
    .brief-item strong {{
      display: block;
      margin-bottom: 7px;
      font-size: 17px;
    }}
    .brief-item p {{
      margin: 0;
      font-size: 13px;
    }}
    .section-head {{
      display: flex;
      justify-content: space-between;
      gap: 18px;
      align-items: end;
      margin-bottom: 16px;
    }}
    .section-head p {{
      margin: 0;
    }}
    .guide-item strong {{
      display: block;
      margin-bottom: 7px;
      font-size: 16px;
    }}
    .trial-list {{
      display: grid;
      gap: 12px;
    }}
    .trial-card {{
      border: 1px solid var(--line);
      background: #fffdf8;
      padding: 16px;
      border-radius: 4px;
      min-width: 0;
    }}
    .trial-card * {{ min-width: 0; }}
    .trial-card h3 {{
      margin: 0 0 8px;
      font-size: 18px;
      line-height: 1.28;
      letter-spacing: 0;
      overflow-wrap: anywhere;
    }}
    .card-head {{
      display: flex;
      gap: 12px;
      justify-content: space-between;
      align-items: flex-start;
    }}
    .status-badge {{
      display: inline-block;
      white-space: normal;
      overflow-wrap: anywhere;
      padding: 5px 8px;
      background: var(--accent-soft);
      color: var(--accent);
      border: 1px solid #d4c3d1;
      border-radius: 4px;
      font-size: 13px;
      font-weight: 700;
    }}
    .ai-badge {{
      display: inline-block;
      white-space: normal;
      overflow-wrap: anywhere;
      padding: 5px 8px;
      background: #f5edf2;
      color: #6d3f5f;
      border: 1px solid #d8c2d1;
      border-radius: 4px;
      font-size: 13px;
      font-weight: 700;
    }}
    .pubmed-badge {{
      display: inline-block;
      white-space: normal;
      overflow-wrap: anywhere;
      padding: 5px 8px;
      background: #f4efe6;
      color: #5b4630;
      border: 1px solid #d9c9aa;
      border-radius: 4px;
      font-size: 13px;
      font-weight: 700;
    }}
    .topic-badge {{
      display: inline-block;
      white-space: normal;
      overflow-wrap: anywhere;
      padding: 5px 8px;
      background: #fff5e5;
      color: #7a4f0c;
      border: 1px solid #edd29a;
      border-radius: 4px;
      font-size: 13px;
      font-weight: 700;
    }}
    .card-badges {{
      display: flex;
      flex-wrap: wrap;
      justify-content: flex-end;
      gap: 6px;
      min-width: 150px;
    }}
    .ai-panel {{
      border-left: 4px solid #77506f;
      background: #f5edf2;
      padding: 14px 16px;
      color: #4e3448;
      margin-top: 18px;
    }}
    .meta-row {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin: 9px 0;
    }}
    .meta {{
      color: var(--muted);
      font-size: 13px;
      overflow-wrap: anywhere;
    }}
    .plain-note {{
      margin: 10px 0;
      color: #3f3a34;
      max-width: none;
      overflow-wrap: anywhere;
      display: -webkit-box;
      -webkit-line-clamp: 2;
      -webkit-box-orient: vertical;
      overflow: hidden;
    }}
    .ask-line {{
      margin-top: 10px;
      color: var(--muted);
      font-size: 13px;
      overflow-wrap: anywhere;
    }}
    .secondary-button {{
      display: inline-block;
      border: 1px solid var(--line);
      background: #fffdf8;
      color: var(--ink);
      padding: 8px 10px;
      border-radius: 4px;
      font: inherit;
      cursor: pointer;
      margin-top: 10px;
      text-decoration: none;
    }}
    .card-actions {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      align-items: center;
      margin-top: 10px;
    }}
    .detail-panel {{
      display: none;
      border-top: 1px solid var(--line);
      margin-top: 14px;
      padding-top: 14px;
    }}
    .detail-panel.open {{ display: block; }}
    .detail-grid {{
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 10px;
      margin-bottom: 12px;
    }}
    .detail-box {{
      background: #f7f9fb;
      border: 1px solid var(--line);
      padding: 11px;
    }}
    .detail-box span {{
      display: block;
      color: var(--muted);
      font-size: 12px;
      margin-bottom: 4px;
    }}
    .detail-box strong {{
      display: block;
      font-size: 14px;
      overflow-wrap: anywhere;
    }}
    .detail-section {{
      margin-top: 14px;
    }}
    .detail-section h4 {{
      margin: 0 0 8px;
      font-size: 15px;
    }}
    .detail-list {{
      margin: 0;
      padding-left: 18px;
      color: #3f3a34;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 14px;
    }}
    th, td {{
      text-align: left;
      vertical-align: top;
      padding: 11px 10px;
      border-bottom: 1px solid var(--line);
    }}
    th {{
      color: var(--muted);
      font-size: 12px;
      text-transform: uppercase;
      letter-spacing: 0;
      background: #eee8dc;
    }}
    a {{ color: #5c3b72; text-decoration-thickness: 1px; }}
    .pill {{
      display: inline-block;
      padding: 3px 7px;
      border: 1px solid var(--line);
      border-radius: 4px;
      margin: 2px 4px 2px 0;
      white-space: normal;
      overflow-wrap: anywhere;
      color: var(--muted);
      background: #fffdf8;
    }}
    .grid-two {{
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 20px;
    }}
    .list-table td:first-child {{ width: 72%; }}
    .small {{ font-size: 13px; color: var(--muted); }}
    .count-line {{ margin: 0 0 12px; color: var(--muted); }}
    .muted-link {{ color: var(--muted); }}
    @media (max-width: 820px) {{
      .wrap {{ padding: 18px; }}
      .top-nav .wrap {{ display: block; }}
      .nav-links {{ justify-content: flex-start; margin-top: 8px; }}
      .hero-grid {{ grid-template-columns: 1fr; padding-top: 28px; }}
      .metrics {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
      .controls {{ grid-template-columns: 1fr; }}
      .search-row {{ grid-template-columns: 1fr; }}
      .explorer-workspace {{ grid-template-columns: 1fr; }}
      .filter-rail {{ position: static; }}
      .guide-controls {{ grid-template-columns: 1fr; }}
      .guide-grid {{ grid-template-columns: 1fr; }}
      .start-grid {{ grid-template-columns: 1fr; }}
      .brief-grid {{ grid-template-columns: 1fr; }}
      .section-head {{ display: block; }}
      .lupus-focus-grid {{ grid-template-columns: 1fr; }}
      .grid-two {{ grid-template-columns: 1fr; }}
      .detail-grid {{ grid-template-columns: 1fr; }}
      .card-head {{ display: block; }}
      .card-badges {{ justify-content: flex-start; margin-top: 8px; }}
      table {{ font-size: 13px; }}
      th:nth-child(3), td:nth-child(3), th:nth-child(4), td:nth-child(4) {{ display: none; }}
    }}
  </style>
</head>
<body>
  <nav class="top-nav" aria-label="Page sections">
    <div class="wrap">
      <a class="brand" href="index.html">Home</a>
      <div class="nav-links">
        <a href="finder.html">Find</a>
        <a href="#explorer">Learn</a>
        <a href="changes.html">Updates</a>
      </div>
    </div>
  </nav>

  <main>
    <section id="explorer">
      <div class="wrap">
        <div class="eyebrow">Learn from TrialCompass</div>
        <h1>Explore public records and research context</h1>
        <p>Use this library after a finder search to understand research areas, terms, status, phase, locations, and source-linked records.</p>
        <div class="small">Public registry data only. Not medical advice. Verify details in the official registry.</div>
        <h2>Research library filters</h2>
        <div class="explorer-workspace">
          <aside class="filter-rail" aria-label="Record filters">
            <div class="guide-panel">
              <h3>Filters</h3>
              <div class="guide-controls">
                <div class="guide-field">
                  <label for="guide-topic">Research area</label>
                  <select id="guide-topic">
                    <option value="">Any research area</option>
                    <option value="nephritis">Kidney / lupus nephritis</option>
                    <option value="cell-therapy">Cell therapy / CAR-T</option>
                    <option value="biologics">Biologics / antibodies</option>
                    <option value="pediatric">Children and teens</option>
                    <option value="pregnancy">Pregnancy / reproductive health</option>
                    <option value="diagnostics">Diagnostics / biomarkers</option>
                    <option value="lifestyle">Lifestyle / education</option>
                    <option value="asia">Asia-Pacific activity</option>
                  </select>
                </div>
                <div class="guide-field">
                  <label for="guide-status">Public status</label>
                  <select id="guide-status">
                    <option value="current">Current/open</option>
                    <option value="recruiting">Recruiting/opening</option>
                    <option value="all">All public records</option>
                  </select>
                </div>
                <div class="guide-field">
                  <label for="guide-region">Location view</label>
                  <select id="guide-region">
                    <option value="">Anywhere</option>
                    <option value="non-us">Outside United States</option>
                    <option value="asia-pacific">Asia-Pacific</option>
                    <option value="Europe">Europe</option>
                    <option value="United States">United States</option>
                    <option value="China">China</option>
                  </select>
                </div>
                <div class="guide-field">
                  <label for="guide-reading">Reading mode</label>
                  <select id="guide-reading">
                    <option value="">All source records</option>
                    <option value="pubmed">Records with publications</option>
                    <option value="ai">Source-grounded notes</option>
                    <option value="recent">Recently updated</option>
                  </select>
                </div>
              </div>
            </div>
            <details class="advanced-filters">
              <summary>Advanced filters</summary>
              <div class="controls">
                <select id="view"></select>
                <select id="status"></select>
                <select id="phase"></select>
                <select id="region"></select>
              </div>
            </details>
          </aside>
          <div class="results-panel">
            <div class="assistant-panel" id="guided-search">
              <h2>Ask the research index</h2>
              <p>Local guided search: no API call. It maps plain language to filters and does not check personal eligibility or recommend a study.</p>
              <div class="search-row">
                <input id="assistant-query" type="search" placeholder="Example: open CAR-T studies in China" aria-label="Ask the research index">
                <button id="assistant-button" class="primary-action" type="button">Apply filters</button>
              </div>
              <div id="assistant-response" class="assistant-response"></div>
              <div class="assistant-examples" aria-label="Guided search examples">
                <button class="assistant-example" type="button" data-guide="open CAR-T studies in China">Open CAR-T in China</button>
                <button class="assistant-example" type="button" data-guide="kidney lupus studies with AI explanation">Kidney + AI explained</button>
                <button class="assistant-example" type="button" data-guide="recent PubMed-linked studies outside the United States">Recent PubMed outside US</button>
              </div>
            </div>
            <div class="search-row">
              <input id="search" type="search" placeholder="Search CAR-T, kidney, China, pregnancy, NCT ID..." aria-label="Search public records">
              <button id="search-button" class="primary-action" type="button">Search records</button>
            </div>
            <div id="result-summary" class="result-summary"></div>
            <p class="count-line" id="result-count"></p>
            <div id="trials-list" class="trial-list"></div>
          </div>
        </div>
      </div>
    </section>

    <section id="brief">
      <div class="wrap">
        <div class="section-head">
          <div>
            <h2>Reading Notes</h2>
            <p class="small">Status and phase are research context, not recommendations. Open official registry links before relying on details.</p>
          </div>
          <a class="quick-action" href="changes.html">Recent changes</a>
        </div>
        <div class="ai-panel"><strong>AI coverage:</strong> {ai_explained_count} records have reviewed source-grounded AI notes; {ai_stats['current_missing']} current/open records are still registry-summary only. {pubmed_linked_count} records have PubMed-linked objects. Not medically reviewed.</div>
      </div>
    </section>

    <section id="reference">
      <div class="wrap grid-two">
        <div>
          <h2>Top Interventions</h2>
          <table class="list-table" id="interventions-table"><tbody></tbody></table>
        </div>
        <div>
          <h2>Top Sponsors</h2>
          <table class="list-table" id="sponsors-table"><tbody></tbody></table>
        </div>
      </div>
    </section>

    <section>
      <div class="wrap grid-two">
        <div>
          <h2>Countries</h2>
          <table class="list-table" id="countries-table"><tbody></tbody></table>
          <h2 style="margin-top:24px">Regions</h2>
          <table class="list-table" id="regions-table"><tbody></tbody></table>
        </div>
        <div>
          <h2>Recent Local Changes</h2>
          <p class="small">Changes are computed against the previous generated dataset in this repo.</p>
          <table class="list-table" id="changes-table"><tbody></tbody></table>
        </div>
      </div>
    </section>

    <section>
      <div class="wrap">
        <h2>Data Downloads</h2>
        <p>
          <a href="../data/current/{html.escape(summary["slug"])}.trials.json">Normalized JSON</a> ·
          <a href="../data/current/{html.escape(summary["slug"])}.trials.csv">CSV</a> ·
          <a href="../reports/latest.md">Latest Markdown report</a>
        </p>
      </div>
    </section>
  </main>

  <script id="radar-data" type="application/json">{data_json}</script>
  <script>
    const data = JSON.parse(document.getElementById('radar-data').textContent);
    const summary = data.summary;
    const trials = data.trials;
    const fmt = new Intl.NumberFormat();
    const currentMetric = document.getElementById('m-current');
    if (currentMetric) {{
      currentMetric.textContent = fmt.format(summary.current_research_trials);
      document.getElementById('m-open').textContent = fmt.format(summary.recruiting_or_opening_trials);
      document.getElementById('m-countries').textContent = fmt.format(summary.countries_count);
      document.getElementById('m-ai').textContent = fmt.format(trials.filter(trial => trial.ai_explained).length);
    }}

    function fillSelect(id, label, values) {{
      const select = document.getElementById(id);
      select.innerHTML = `<option value="">${{label}}</option>` + values.map(value => `<option value="${{escapeAttr(value)}}">${{escapeHtml(value)}}</option>`).join('');
    }}
    function unique(field) {{
      return Array.from(new Set(trials.map(t => t[field]).filter(Boolean))).sort();
    }}
    fillSelect('view', 'Current/open research', ['All public records', 'Recruiting/opening only', 'AI explained records', 'Historical/closed records', 'Unclear status']);
    fillSelect('status', 'All statuses', unique('status'));
    fillSelect('phase', 'All phases', unique('phase'));
    fillSelect('region', 'All regions', Array.from(new Set(trials.flatMap(t => t.regions || []))).sort());
    renderLupusLaneMetrics();

    const trialList = document.getElementById('trials-list');
    const resultCount = document.getElementById('result-count');
    const resultSummary = document.getElementById('result-summary');
    const search = document.getElementById('search');
    const searchButton = document.getElementById('search-button');
    const assistantQuery = document.getElementById('assistant-query');
    const assistantButton = document.getElementById('assistant-button');
    const assistantResponse = document.getElementById('assistant-response');
    const view = document.getElementById('view');
    const status = document.getElementById('status');
    const phase = document.getElementById('phase');
    const region = document.getElementById('region');
    const guideTopic = document.getElementById('guide-topic');
    const guideStatus = document.getElementById('guide-status');
    const guideRegion = document.getElementById('guide-region');
    const guideReading = document.getElementById('guide-reading');
    let nonUsOnly = false;
    let pubmedOnly = false;
    let laneOnly = '';
    let activeViewLabel = 'Current/open research';

    function searchableText(trial) {{
      return [
        trial.trial_id,
        trial.title,
        trial.status,
        trial.phase,
        trial.sponsor,
        (trial.conditions || []).join(' '),
        trial.last_update_posted,
        trial.plain_language_summary,
        trial.intervention_names.join(' '),
        trial.intervention_types.join(' '),
        trial.countries.join(' '),
        (trial.regions || []).join(' '),
        trial.ai_explained ? 'ai explained deepseek plain language summary easier reading' : '',
        trial.publication_count ? 'pubmed publication paper article evidence source' : ''
      ].join(' ').toLowerCase();
    }}

    function applyGuidedSearch(text) {{
      const raw = String(text || '').trim();
      if (!raw) {{
        showAssistantResponse('Type a topic, country, treatment name, publication layer, or NCT ID.');
        return;
      }}
      const q = raw.toLowerCase().replace(/[._-]+/g, ' ');
      search.value = '';
      status.value = '';
      phase.value = '';
      region.value = '';
      view.value = '';
      guideTopic.value = '';
      guideStatus.value = 'current';
      guideRegion.value = '';
      guideReading.value = '';
      nonUsOnly = false;
      pubmedOnly = false;
      laneOnly = '';

      const applied = [];
      let guidedKeyword = '';
      if (/\\b(recruiting|recruit|open|opening|enrolling|available)\\b/.test(q)) {{
        guideStatus.value = 'recruiting';
        applied.push('recruiting/opening status');
      }}
      if (/\\b(all|completed|closed|historical|archive|past)\\b/.test(q)) {{
        guideStatus.value = 'all';
        if (/\\b(completed|closed|historical|archive|past)\\b/.test(q)) {{
          view.value = 'Historical/closed records';
          applied.push('historical/closed records');
        }} else {{
          applied.push('all public records');
        }}
      }}
      if (/\\b(kidney|renal|nephritis|glomerul|proteinuria)\\b/.test(q)) {{
        guideTopic.value = 'nephritis';
        applied.push('kidney / lupus nephritis');
      }} else if (/\\b(car\\s*t|cart|cell therapy|cd19|bcma|ucar|t cell|stem cell)\\b/.test(q)) {{
        guideTopic.value = 'cell-therapy';
        applied.push('cell therapy / CAR-T');
      }} else if (/\\b(biologic|biological|antibody|antibodies|belimumab|anifrolumab|rituximab|obinutuzumab|telitacicept|mab)\\b/.test(q)) {{
        guideTopic.value = 'biologics';
        applied.push('biologics / antibodies');
      }} else if (/\\b(child|children|pediatric|paediatric|juvenile|teen|adolescent)\\b/.test(q)) {{
        guideTopic.value = 'pediatric';
        applied.push('children and teens');
      }} else if (/\\b(pregnancy|pregnant|fertility|reproductive|birth control|contracept|menopause)\\b/.test(q)) {{
        guideTopic.value = 'pregnancy';
        applied.push('pregnancy / reproductive health');
      }} else if (/\\b(diagnostic|diagnostics|biomarker|biomarkers|blood test|assay|imaging|autoantibody)\\b/.test(q)) {{
        guideTopic.value = 'diagnostics';
        applied.push('diagnostics / biomarkers');
      }} else if (/\\b(lifestyle|diet|exercise|education|self management|counseling|fatigue|sleep)\\b/.test(q)) {{
        guideTopic.value = 'lifestyle';
        applied.push('lifestyle / education');
      }}
      if (/\\b(asia|asian|asia pacific|apac|china|japan|korea|taiwan|singapore|india|australia)\\b/.test(q)) {{
        if (/\\bchina\\b/.test(q)) {{
          guideRegion.value = 'China';
          applied.push('China');
        }} else {{
          guideRegion.value = 'asia-pacific';
          applied.push('Asia-Pacific');
        }}
      }} else if (/\\beurope|european\\b/.test(q)) {{
        guideRegion.value = 'Europe';
        applied.push('Europe');
      }} else if (/\\b(united states|usa|u s|america|us)\\b/.test(q) && !/(outside|non|not|without)\\s+(the\\s+)?(us|u s|usa|united states|america)/.test(q)) {{
        guideRegion.value = 'United States';
        applied.push('United States');
      }}
      if (/(outside|non|not|without)\\s+(the\\s+)?(us|u s|usa|united states|america)/.test(q)) {{
        guideRegion.value = 'non-us';
        applied.push('outside United States');
      }}
      if (/\\b(pubmed|publication|paper|article|journal)\\b/.test(q)) {{
        guideReading.value = 'pubmed';
        applied.push('PubMed-linked records');
      }}
      if (/\\b(ai|explained|plain language|source grounded|reader|explain)\\b/.test(q)) {{
        guideReading.value = 'ai';
        applied.push('AI-explained records');
      }}
      if (/\\b(recent|updated|new|changed|this week)\\b/.test(q)) {{
        if (guideReading.value && guideReading.value !== 'recent') {{
          guidedKeyword = String(new Date().getFullYear());
        }} else {{
          guideReading.value = 'recent';
        }}
        applied.push('recently updated records');
      }}
      const residual = residualGuidedQuery(q);
      if (residual) {{
        search.value = residual;
        applied.push(`keyword: "${{residual}}"`);
      }} else if (guidedKeyword) {{
        search.value = guidedKeyword;
        applied.push(`keyword: "${{guidedKeyword}}"`);
      }}
      if (!applied.length) {{
        search.value = raw;
        applied.push(`keyword: "${{raw}}"`);
      }}
      showAssistantResponse(`Applied filters: ${{applied.join(' · ')}}. Verify details in the official registry; this does not check eligibility.`);
      renderTrials();
    }}

    function residualGuidedQuery(q) {{
      let text = ` ${{q}} `;
      [
        /\\b(show|find|search|list|give|me|studies|study|trial|trials|records|record|public|research|about|for|in|with|and|or|now|currently|lupus|sle)\\b/g,
        /\\b(recruiting|recruit|open|opening|enrolling|available|current|all|completed|closed|historical|archive|past)\\b/g,
        /\\b(kidney|renal|nephritis|glomerul|proteinuria|car\\s*t|cart|cell therapy|cd19|bcma|ucar|t cell|stem cell)\\b/g,
        /\\b(biologic|biological|antibody|antibodies|pediatric|paediatric|juvenile|child|children|teen|adolescent)\\b/g,
        /\\b(pregnancy|pregnant|fertility|reproductive|diagnostic|diagnostics|biomarker|biomarkers|lifestyle|diet|exercise|education)\\b/g,
        /\\b(asia|asian|asia pacific|apac|china|japan|korea|taiwan|singapore|india|australia|europe|european|united states|usa|america|us)\\b/g,
        /\\b(pubmed|publication|paper|article|journal|ai|explained|explanation|plain language|source grounded|reader|explain|recent|updated|new|changed|this week)\\b/g,
        /(outside|non|not|without)\\s+(the\\s+)?(us|u s|usa|united states|america)/g
      ].forEach(pattern => {{ text = text.replace(pattern, ' '); }});
      return text.replace(/\\s+/g, ' ').trim();
    }}

    function showAssistantResponse(message) {{
      assistantResponse.textContent = message;
      assistantResponse.classList.add('visible');
    }}

    function renderTrials() {{
      const q = search.value.trim().toLowerCase();
      const queryMode = queryIntent(q);
      const v = view.value;
      const s = status.value;
      const p = phase.value;
      const r = region.value;
      const gt = guideTopic.value;
      const gs = guideStatus.value;
      const gr = guideRegion.value;
      const gm = guideReading.value;
      activeViewLabel = guidedLabel(gt, gs, gr, gm);
      const filtered = trials.filter(trial => {{
        if (!v && (!gs || gs === 'current') && trial.relevance !== 'current') return false;
        if (gs === 'recruiting' && !['RECRUITING', 'NOT_YET_RECRUITING', 'ENROLLING_BY_INVITATION'].includes(trial.status)) return false;
        if (v === 'Recruiting/opening only' && !['RECRUITING', 'NOT_YET_RECRUITING', 'ENROLLING_BY_INVITATION'].includes(trial.status)) return false;
        if (v === 'AI explained records' && !trial.ai_explained) return false;
        if (v === 'Historical/closed records' && trial.relevance !== 'historical') return false;
        if (v === 'Unclear status' && trial.relevance !== 'unclear') return false;
        if (gt === 'asia' && !(trial.regions || []).some(region => ['East Asia', 'Southeast Asia', 'South Asia', 'Oceania'].includes(region))) return false;
        if (gt && gt !== 'asia' && lupusLaneId(trial) !== gt) return false;
        if (gr === 'non-us' && (trial.countries || []).includes('United States')) return false;
        if (gr === 'asia-pacific' && !(trial.regions || []).some(region => ['East Asia', 'Southeast Asia', 'South Asia', 'Oceania'].includes(region))) return false;
        if (gr && !['non-us', 'asia-pacific'].includes(gr) && !((trial.regions || []).includes(gr) || (trial.countries || []).includes(gr))) return false;
        if (gm === 'pubmed' && !trial.publication_count) return false;
        if (gm === 'ai' && !trial.ai_explained) return false;
        if (gm === 'recent' && !String(trial.last_update_posted || '').startsWith(String(new Date().getFullYear()))) return false;
        if (s && trial.status !== s) return false;
        if (p && trial.phase !== p) return false;
        if (r && !(trial.regions || []).includes(r)) return false;
        if (nonUsOnly && (trial.countries || []).includes('United States')) return false;
        if (pubmedOnly && !trial.publication_count) return false;
        if (laneOnly && lupusLane(trial) !== laneOnly) return false;
        if (queryMode.nonUs && (trial.countries || []).includes('United States')) return false;
        if (queryMode.ai && !trial.ai_explained) return false;
        if (queryMode.pubmed && !trial.publication_count) return false;
        if (q && !queryMode.handled && !searchableText(trial).includes(q)) return false;
        return true;
      }}).sort(sortForPatients);
      resultCount.textContent = `${{fmt.format(filtered.length)}} matching records`;
      renderResultSummary(filtered);
      trialList.innerHTML = filtered.slice(0, 60).map(renderTrialCard).join('');
      if (filtered.length > 60) {{
        trialList.innerHTML += `<p class="small">Showing first 60 records. Narrow the search to see more specific results.</p>`;
      }}
    }}

    function queryIntent(q) {{
      const normalized = q.replace(/[._-]+/g, ' ');
      const intent = {{
        ai: /\\b(ai|deepseek|explained|plain language)\\b/.test(normalized),
        pubmed: /\\b(pubmed|publication|paper|article|journal)\\b/.test(normalized),
        nonUs: /(outside|non|not|without)\\s+(the\\s+)?(us|u s|usa|united states|america)/.test(normalized)
      }};
      intent.handled = Boolean(intent.ai || intent.pubmed || intent.nonUs);
      return intent;
    }}

    function renderResultSummary(filtered) {{
      if (!filtered.length) {{
        resultSummary.innerHTML = '<strong>No matching records.</strong> Try removing one filter, searching a sponsor or country, or opening the glossary before reading detail pages.';
        return;
      }}
      const recruiting = filtered.filter(trial => ['RECRUITING', 'NOT_YET_RECRUITING', 'ENROLLING_BY_INVITATION'].includes(trial.status)).length;
      const aiCount = filtered.filter(trial => trial.ai_explained).length;
      const pubmedCount = filtered.filter(trial => trial.publication_count).length;
      const statusBits = [
        `${{fmt.format(recruiting)}} recruiting/opening`,
        `${{fmt.format(aiCount)}} AI-explained`,
        `${{fmt.format(pubmedCount)}} PubMed-linked`
      ];
      resultSummary.innerHTML = `<strong>${{escapeHtml(activeViewLabel)}}:</strong> ${{fmt.format(filtered.length)}} records · ${{statusBits.join(' · ')}}. Open a detail page, then verify the official registry.`;
    }}

    function guidedLabel(topic, status, region, reading) {{
      const parts = [];
      const topicLabels = {{
        'nephritis': 'Kidney / lupus nephritis',
        'cell-therapy': 'Cell therapy / CAR-T',
        'biologics': 'Biologics / antibodies',
        'pediatric': 'Children and teens',
        'pregnancy': 'Pregnancy / reproductive health',
        'diagnostics': 'Diagnostics / biomarkers',
        'lifestyle': 'Lifestyle / education',
        'asia': 'Asia-Pacific activity'
      }};
      const statusLabels = {{
        'current': 'current/open',
        'recruiting': 'recruiting/opening',
        'all': 'all public'
      }};
      const regionLabels = {{
        'non-us': 'outside United States',
        'asia-pacific': 'Asia-Pacific',
        'Europe': 'Europe',
        'United States': 'United States',
        'China': 'China'
      }};
      const readingLabels = {{
        'pubmed': 'with publications',
        'ai': 'with source-grounded notes',
        'recent': 'recently updated'
      }};
      if (topic && topicLabels[topic]) parts.push(topicLabels[topic]);
      if (status && statusLabels[status]) parts.push(statusLabels[status]);
      if (region && regionLabels[region]) parts.push(regionLabels[region]);
      if (reading && readingLabels[reading]) parts.push(readingLabels[reading]);
      return parts.length ? parts.join(' · ') : 'Current/open research';
    }}

    function renderLupusLaneMetrics() {{
      if (!document.getElementById('lane-nephritis')) return;
      const current = trials.filter(trial => trial.relevance === 'current');
      const counts = countLupusLanes(current);
      document.getElementById('lane-nephritis').textContent = fmt.format(counts.get('Lupus nephritis / kidney') || 0);
      document.getElementById('lane-cell').textContent = fmt.format(counts.get('CAR-T / cell therapy') || 0);
      document.getElementById('lane-biologic').textContent = fmt.format(counts.get('Biologics / antibodies') || 0);
      document.getElementById('lane-asia').textContent = fmt.format(current.filter(trial => (trial.regions || []).some(region => ['East Asia', 'Southeast Asia', 'South Asia', 'Oceania'].includes(region))).length);
      document.getElementById('lane-pediatric').textContent = fmt.format(counts.get('Pediatric / juvenile lupus') || 0);
      document.getElementById('lane-pregnancy').textContent = fmt.format(counts.get('Pregnancy / reproductive health') || 0);
      document.getElementById('lane-diagnostics').textContent = fmt.format(counts.get('Diagnostics / biomarkers') || 0);
      document.getElementById('lane-lifestyle').textContent = fmt.format(counts.get('Lifestyle / education') || 0);
    }}

    function topLupusLanes(records, limit) {{
      return Array.from(countLupusLanes(records).entries())
        .sort((a, b) => b[1] - a[1] || String(a[0]).localeCompare(String(b[0])))
        .slice(0, limit);
    }}

    function countLupusLanes(records) {{
      const counts = new Map();
      records.forEach(trial => {{
        const lane = lupusLane(trial);
        counts.set(lane, (counts.get(lane) || 0) + 1);
      }});
      return counts;
    }}

    function lupusLane(trial) {{
      const haystack = searchableText(trial);
      if (/nephritis|kidney|renal|glomerul|proteinuria|albuminuria/.test(haystack)) return 'Lupus nephritis / kidney';
      if (/car\\s*-?\\s*t|cart|cell therapy|cd19|bcma|ucar|t cell|stem cell|hematopoietic/.test(haystack)) return 'CAR-T / cell therapy';
      if (/biological|antibody|\\bmab\\b|belimumab|anifrolumab|rituximab|obinutuzumab|telitacicept|ianalumab|dapirolizumab/.test(haystack)) return 'Biologics / antibodies';
      if (/biomarker|diagnostic|blood sample|blood test|receptor|imaging|ultrasound|assay|gene expression|autoantibod/.test(haystack)) return 'Diagnostics / biomarkers';
      if (/pediatric|paediatric|juvenile|child|children|adolescent|teen/.test(haystack)) return 'Pediatric / juvenile lupus';
      if (/pregnan|fertility|reproductive|estrogen|birth control|contracept|postmenopausal|menopause/.test(haystack)) return 'Pregnancy / reproductive health';
      if (/diet|exercise|education|counseling|self-management|rehabilitation|quality of life|sleep|fatigue/.test(haystack)) return 'Lifestyle / education';
      if (/device|wearable|sensor|app\\b|digital/.test(haystack)) return 'Device / digital monitoring';
      return 'General SLE research';
    }}

    function lupusLaneId(trial) {{
      return {{
        'Lupus nephritis / kidney': 'nephritis',
        'CAR-T / cell therapy': 'cell-therapy',
        'Biologics / antibodies': 'biologics',
        'Diagnostics / biomarkers': 'diagnostics',
        'Pediatric / juvenile lupus': 'pediatric',
        'Pregnancy / reproductive health': 'pregnancy',
        'Lifestyle / education': 'lifestyle',
        'Device / digital monitoring': 'devices'
      }}[lupusLane(trial)] || 'general';
    }}

    function topMany(records, field, limit) {{
      const counts = new Map();
      records.forEach(record => {{
        const values = record[field] || [];
        values.forEach(value => counts.set(value, (counts.get(value) || 0) + 1));
      }});
      return Array.from(counts.entries()).sort((a, b) => b[1] - a[1] || String(a[0]).localeCompare(String(b[0]))).slice(0, limit);
    }}

    function formatTop(rows) {{
      if (!rows.length) return 'not enough data listed';
      return rows.map(([label, count]) => `${{label}} (${{fmt.format(count)}})`).join(', ');
    }}

    function renderTrialCard(trial) {{
      const interventions = trial.intervention_names.length ? trial.intervention_names.slice(0, 3) : ['Intervention not listed'];
      const countries = trial.countries.length ? trial.countries.slice(0, 3) : ['Locations not listed'];
      const pubmedBadge = trial.publication_count ? `<span class="meta">${{fmt.format(trial.publication_count)}} PubMed</span>` : '';
      const aiLabel = trial.ai_explained ? '<span class="meta">AI explained</span>' : '';
      const topicBadge = `<span class="topic-badge">${{escapeHtml(lupusLane(trial))}}</span>`;
      return `<article class="trial-card">
        <div class="card-head">
          <div>
            <h3><a href="trials/${{escapeAttr(trial.trial_id)}}.html">${{escapeHtml(trial.title || 'Untitled public record')}}</a></h3>
          </div>
          <div class="card-badges">
            ${{topicBadge}}
            <span class="status-badge">${{escapeHtml(labelStatus(trial.status))}}</span>
          </div>
        </div>
        <p class="plain-note">${{escapeHtml(trial.plain_language_summary)}}</p>
        <div class="meta-row">
          <span class="pill">${{escapeHtml(phaseExplanation(trial.phase))}}</span>
          ${{renderPills(interventions)}}
          ${{renderPills(countries)}}
        </div>
        <div class="meta-row">
          <span class="meta">${{escapeHtml(trial.trial_id)}}</span>
          <span class="meta">Updated ${{escapeHtml(shortDate(trial.last_update_posted))}}</span>
          ${{aiLabel}}
          ${{pubmedBadge}}
        </div>
        <div class="card-actions">
          <a class="secondary-button" href="trials/${{escapeAttr(trial.trial_id)}}.html">Read detail</a>
          <a class="secondary-button" href="${{escapeAttr(trial.source_url)}}" target="_blank" rel="noreferrer">Official registry</a>
        </div>
      </article>`;
    }}

    function renderDetailPanel(trial) {{
      const eligibility = trial.eligibility || {{}};
      return `
        <div class="detail-grid">
          <div class="detail-box"><span>Study type</span><strong>${{escapeHtml(trial.study_type || 'Not listed')}}</strong></div>
          <div class="detail-box"><span>Enrollment</span><strong>${{escapeHtml(formatEnrollment(trial))}}</strong></div>
          <div class="detail-box"><span>Start date</span><strong>${{escapeHtml(trial.start_date || 'Not listed')}}</strong></div>
          <div class="detail-box"><span>Age listed</span><strong>${{escapeHtml(formatAge(eligibility))}}</strong></div>
          <div class="detail-box"><span>Sex listed</span><strong>${{escapeHtml(formatSex(eligibility.sex))}}</strong></div>
          <div class="detail-box"><span>Results posted</span><strong>${{trial.has_results ? 'Yes' : 'No / not listed'}}</strong></div>
        </div>
        <div class="detail-section">
          <h4>Conditions in the registry</h4>
          <div>${{renderPills((trial.conditions || []).slice(0, 8))}}</div>
        </div>
        <div class="detail-section">
          <h4>Interventions listed</h4>
          ${{renderInterventionDetails(trial.interventions || [])}}
        </div>
        <div class="detail-section">
          <h4>Locations listed</h4>
          ${{renderLocationDetails(trial.locations || [])}}
        </div>
        <div class="detail-section">
          <h4>Official summary excerpt</h4>
          <p class="plain-note">${{escapeHtml(trial.brief_summary || 'No public summary excerpt was included in the normalized record.')}}</p>
        </div>
        <div class="detail-section">
          <h4>Eligibility snapshot</h4>
          <p class="plain-note">${{escapeHtml(eligibility.criteria_excerpt || 'Detailed eligibility text is not included in this compact view. Verify eligibility details in the official registry and with a clinician.')}}</p>
        </div>
        <div class="detail-section">
          <h4>Questions to discuss with a clinician</h4>
          ${{renderQuestions(trial.questions_to_ask || [])}}
        </div>
        <div class="ask-line">This detail panel summarizes public registry fields only. It cannot determine whether a person is eligible.</div>
      `;
    }}

    function renderPills(items) {{
      if (!items.length) return '<span class="small">Unknown</span>';
      return items.map(item => `<span class="pill">${{escapeHtml(item)}}</span>`).join('');
    }}

    function renderInterventionDetails(items) {{
      if (!items.length) return '<p class="small">No interventions listed in the normalized record.</p>';
      return `<ul class="detail-list">${{items.map(item => `<li><strong>${{escapeHtml(item.name || 'Unnamed intervention')}}</strong> <span class="small">(${{escapeHtml(item.type || 'type not listed')}})</span>${{item.description ? `<br><span class="small">${{escapeHtml(item.description)}}</span>` : ''}}</li>`).join('')}}</ul>`;
    }}

    function renderLocationDetails(items) {{
      if (!items.length) return '<p class="small">No locations listed in the normalized record.</p>';
      return `<ul class="detail-list">${{items.slice(0, 8).map(location => `<li>${{escapeHtml(formatLocation(location))}}</li>`).join('')}}</ul>`;
    }}

    function renderQuestions(items) {{
      if (!items.length) return '<p class="small">No question prompts generated for this record.</p>';
      return `<ul class="detail-list">${{items.map(item => `<li>${{escapeHtml(item)}}</li>`).join('')}}</ul>`;
    }}

    function renderCountTable(id, rows) {{
      const body = document.querySelector(`#${{id}} tbody`);
      body.innerHTML = rows.map(([label, count]) => `<tr><td>${{escapeHtml(label || 'Unknown')}}</td><td style="text-align:right">${{fmt.format(count)}}</td></tr>`).join('');
    }}
    function renderInterventionTable(id, rows) {{
      const body = document.querySelector(`#${{id}} tbody`);
      body.innerHTML = rows.map(([label, count]) => `<tr><td><a href="interventions/${{escapeAttr(interventionSlug(label))}}.html">${{escapeHtml(label || 'Unknown')}}</a></td><td style="text-align:right">${{fmt.format(count)}}</td></tr>`).join('');
    }}
    renderInterventionTable('interventions-table', summary.top_interventions);
    renderCountTable('sponsors-table', summary.top_sponsors);
    renderCountTable('countries-table', summary.top_countries);
    renderCountTable('regions-table', summary.region_counts || []);

    const changes = document.querySelector('#changes-table tbody');
    if (data.diff.changed.length) {{
      changes.innerHTML = data.diff.changed.map(item => `<tr><td><a href="${{escapeAttr(item.source_url)}}" target="_blank" rel="noreferrer">${{escapeHtml(item.trial_id)}}</a><br>${{escapeHtml(Object.keys(item.changes).join(', '))}}</td></tr>`).join('');
    }} else {{
      changes.innerHTML = `<tr><td>No tracked field changes compared with the previous local run.</td></tr>`;
    }}

    search.addEventListener('input', renderTrials);
    search.addEventListener('keydown', event => {{
      if (event.key === 'Enter') {{
        event.preventDefault();
        renderTrials();
      }}
    }});
    searchButton.addEventListener('click', renderTrials);
    assistantButton.addEventListener('click', () => applyGuidedSearch(assistantQuery.value));
    assistantQuery.addEventListener('keydown', event => {{
      if (event.key === 'Enter') {{
        event.preventDefault();
        applyGuidedSearch(assistantQuery.value);
      }}
    }});
    document.querySelectorAll('button[data-guide]').forEach(button => {{
      button.addEventListener('click', () => {{
        assistantQuery.value = button.dataset.guide || '';
        applyGuidedSearch(assistantQuery.value);
      }});
    }});
    view.addEventListener('change', renderTrials);
    status.addEventListener('change', renderTrials);
    phase.addEventListener('change', renderTrials);
    region.addEventListener('change', renderTrials);
    guideTopic.addEventListener('change', renderTrials);
    guideStatus.addEventListener('change', renderTrials);
    guideRegion.addEventListener('change', renderTrials);
    guideReading.addEventListener('change', renderTrials);

    function applyAction(action, shouldScroll) {{
      search.value = '';
      status.value = '';
      phase.value = '';
      region.value = '';
      view.value = '';
      guideTopic.value = '';
      guideStatus.value = 'current';
      guideRegion.value = '';
      guideReading.value = '';
      nonUsOnly = false;
      pubmedOnly = false;
      laneOnly = '';
      activeViewLabel = 'Current/open research';
      if (action === 'recruiting') {{
        view.value = 'Recruiting/opening only';
        activeViewLabel = 'Recruiting or opening research';
      }}
      if (action === 'ai') {{
        view.value = 'AI explained records';
        activeViewLabel = 'AI-explained public records';
      }}
      if (action === 'pubmed') {{
        view.value = 'All public records';
        pubmedOnly = true;
        activeViewLabel = 'PubMed-linked public records';
      }}
      if (action === 'devices') {{
        search.value = 'device';
        activeViewLabel = 'Device and digital monitoring records';
      }}
      if (action === 'biologics') guideTopic.value = 'biologics';
      if (action === 'nephritis') guideTopic.value = 'nephritis';
      if (action === 'cell-therapy') guideTopic.value = 'cell-therapy';
      if (action === 'pediatric') guideTopic.value = 'pediatric';
      if (action === 'pregnancy') guideTopic.value = 'pregnancy';
      if (action === 'diagnostics') guideTopic.value = 'diagnostics';
      if (action === 'lifestyle') guideTopic.value = 'lifestyle';
      if (laneOnly) activeViewLabel = laneOnly;
      if (action === 'asia') {{
        guideTopic.value = 'asia';
        activeViewLabel = 'Asia-Pacific public records';
      }}
      if (action === 'phase3') {{
        phase.value = 'Phase 3';
        activeViewLabel = 'Phase 3 public records';
      }}
      if (action === 'non-us') {{
        guideRegion.value = 'non-us';
        activeViewLabel = 'Records outside the United States';
      }}
      if (action === 'recent') {{
        search.value = String(new Date().getFullYear());
        activeViewLabel = 'Recently updated public records';
      }}
      if (action === 'clear') {{
        view.value = '';
        guideStatus.value = 'current';
        activeViewLabel = 'Current/open research';
      }}
      renderTrials();
      if (shouldScroll) document.getElementById('explorer').scrollIntoView({{ behavior: 'smooth', block: 'start' }});
    }}

    document.querySelectorAll('button[data-action]').forEach(button => {{
      button.addEventListener('click', () => {{
        applyAction(button.dataset.action, true);
      }});
    }});
    const initialParams = new URLSearchParams(window.location.search);
    const initialTopic = initialParams.get('topic');
    if (initialTopic) {{
      applyAction(initialTopic, false);
    }}
    if (initialParams.get('status')) guideStatus.value = initialParams.get('status');
    if (initialParams.get('region')) guideRegion.value = initialParams.get('region');
    if (initialParams.get('reading')) guideReading.value = initialParams.get('reading');
    if (initialParams.get('query')) search.value = initialParams.get('query');
    if (initialParams.get('assistant')) {{
      document.getElementById('guided-search').scrollIntoView({{ behavior: 'auto', block: 'start' }});
      assistantQuery.focus();
      showAssistantResponse('Try: open CAR-T studies in China, kidney lupus with AI explanation, or recent PubMed-linked studies outside the United States.');
    }}
    renderTrials();

    function sortForPatients(a, b) {{
      const statusDelta = statusPriority(a.status) - statusPriority(b.status);
      if (statusDelta) return statusDelta;
      return dateValue(b.last_update_posted) - dateValue(a.last_update_posted);
    }}
    function statusPriority(status) {{
      return {{
        'RECRUITING': 0,
        'NOT_YET_RECRUITING': 1,
        'ENROLLING_BY_INVITATION': 2,
        'ACTIVE_NOT_RECRUITING': 3,
        'UNKNOWN': 4,
        'COMPLETED': 5,
        'SUSPENDED': 6,
        'TERMINATED': 7,
        'WITHDRAWN': 8
      }}[status] ?? 9;
    }}
    function dateValue(value) {{
      const parsed = Date.parse(value || '');
      return Number.isNaN(parsed) ? 0 : parsed;
    }}
    function shortDate(value) {{
      if (!value) return 'No public update date';
      return value;
    }}
    function phaseExplanation(phase) {{
      if (!phase || phase === 'N/A') return 'No standard drug phase listed';
      if (phase.includes('Early Phase 1')) return 'Early Phase 1 research';
      if (phase.includes('Phase 1')) return phase + ': early safety research';
      if (phase.includes('Phase 2')) return phase + ': dose or early effectiveness research';
      if (phase.includes('Phase 3')) return phase + ': larger confirmatory research';
      if (phase.includes('Phase 4')) return phase + ': post-approval research';
      return phase;
    }}
    function formatEnrollment(trial) {{
      if (!trial.enrollment_count) return 'Not listed';
      const type = trial.enrollment_type ? ` (${{trial.enrollment_type.toLowerCase()}})` : '';
      return `${{fmt.format(trial.enrollment_count)}} participants${{type}}`;
    }}
    function formatAge(eligibility) {{
      const min = eligibility.minimum_age || 'No minimum listed';
      const max = eligibility.maximum_age || 'No maximum listed';
      return `${{min}} to ${{max}}`;
    }}
    function formatSex(value) {{
      if (!value) return 'Not listed';
      return labelStatus(value);
    }}
    function formatLocation(location) {{
      return [location.facility, location.city, location.state, location.country].filter(Boolean).join(', ') || 'Location details not listed';
    }}
    function labelStatus(value) {{
      return String(value || 'Unknown').replaceAll('_', ' ').toLowerCase().replace(/\\b\\w/g, c => c.toUpperCase());
    }}
    function interventionSlug(value) {{
      return String(value || '').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '') || 'unknown';
    }}
    function escapeHtml(value) {{
      return String(value ?? '').replace(/[&<>"']/g, char => ({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[char]));
    }}
    function escapeAttr(value) {{
      return escapeHtml(value).replace(/`/g, '&#96;');
    }}
  </script>
</body>
</html>
"""


def render_table(headers: list[str], rows: list[tuple[str, int]]) -> str:
    if not rows:
        return "_No data._"
    table = [
        f"| {headers[0]} | {headers[1]} |",
        "|---|---:|",
    ]
    for label, count in rows:
        safe_label = str(label).replace("|", "\\|") or "Unknown"
        table.append(f"| {safe_label} | {count} |")
    return "\n".join(table)


def count_field(trials: list[dict[str, Any]], field: str) -> Counter[str]:
    counter: Counter[str] = Counter()
    for trial in trials:
        value = trial.get(field) or "Unknown"
        counter[str(value)] += 1
    return counter


def count_many(trials: list[dict[str, Any]], field: str) -> Counter[str]:
    counter: Counter[str] = Counter()
    for trial in trials:
        values = trial.get(field) or []
        if not values:
            counter["Unknown"] += 1
            continue
        for value in values:
            counter[str(value)] += 1
    return counter


def count_interventions(trials: list[dict[str, Any]]) -> Counter[str]:
    counter: Counter[str] = Counter()
    for trial in trials:
        names = trial.get("intervention_names") or []
        if not names:
            counter["Unknown"] += 1
            continue
        for name in names:
            counter[normalize_label(name)] += 1
    return counter


def normalize_label(value: str) -> str:
    value = re.sub(r"\s+", " ", value.strip())
    if not value:
        return "Unknown"
    special_cases = {
        "placebo": "Placebo",
        "standard care": "Standard of care",
        "standard of care": "Standard of care",
    }
    return special_cases.get(value.lower(), value)


def get_in(data: dict[str, Any], path: list[str], default: Any = None) -> Any:
    cursor: Any = data
    for key in path:
        if not isinstance(cursor, dict) or key not in cursor:
            return default
        cursor = cursor[key]
    return cursor


if __name__ == "__main__":
    sys.exit(main())
