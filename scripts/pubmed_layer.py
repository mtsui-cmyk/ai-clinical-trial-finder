#!/usr/bin/env python3
"""Find PubMed records that mention normalized trial IDs."""

from __future__ import annotations

import argparse
import csv
import json
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a PubMed-by-trial-ID source layer.")
    parser.add_argument("--trials", required=True, help="Normalized trials JSON.")
    parser.add_argument("--out-json", required=True, help="Output publication JSON.")
    parser.add_argument("--out-csv", help="Optional output publication CSV.")
    parser.add_argument("--limit", type=int, default=0, help="Optional max trial IDs to query.")
    parser.add_argument("--sleep", type=float, default=0.34, help="Delay between NCBI requests.")
    args = parser.parse_args()

    trials = json.loads(Path(args.trials).read_text(encoding="utf-8"))
    records = []
    for index, trial in enumerate(trials):
        if args.limit and index >= args.limit:
            break
        trial_id = trial["trial_id"]
        pmids = search_pubmed(trial_id)
        time.sleep(args.sleep)
        if not pmids:
            continue
        summaries = fetch_pubmed_summaries(pmids)
        time.sleep(args.sleep)
        for summary in summaries:
            records.append(normalize_pubmed_record(trial_id, summary))

    write_json(Path(args.out_json), records)
    if args.out_csv:
        write_csv(Path(args.out_csv), records)
    print(f"Wrote {len(records)} PubMed records.")
    return 0


def search_pubmed(trial_id: str) -> list[str]:
    params = {
        "db": "pubmed",
        "term": f'"{trial_id}"[All Fields]',
        "retmode": "json",
        "retmax": "20",
    }
    payload = fetch_json(f"{EUTILS}/esearch.fcgi?{urllib.parse.urlencode(params)}")
    return payload.get("esearchresult", {}).get("idlist", [])


def fetch_pubmed_summaries(pmids: list[str]) -> list[dict[str, Any]]:
    params = {
        "db": "pubmed",
        "id": ",".join(pmids),
        "retmode": "json",
    }
    payload = fetch_json(f"{EUTILS}/esummary.fcgi?{urllib.parse.urlencode(params)}")
    result = payload.get("result", {})
    return [result[pmid] for pmid in result.get("uids", []) if pmid in result]


def fetch_json(url: str) -> dict[str, Any]:
    request = urllib.request.Request(url, headers={"User-Agent": "open-disease-research-radar/0.1"})
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def normalize_pubmed_record(trial_id: str, summary: dict[str, Any]) -> dict[str, Any]:
    pmid = str(summary.get("uid", ""))
    authors = [author.get("name", "") for author in summary.get("authors", []) if author.get("name")]
    return {
        "trial_id": trial_id,
        "source": "PubMed",
        "pmid": pmid,
        "title": summary.get("title", ""),
        "journal": summary.get("fulljournalname") or summary.get("source", ""),
        "pub_date": summary.get("pubdate", ""),
        "authors": authors[:8],
        "url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/" if pmid else "",
    }


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_csv(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["trial_id", "pmid", "title", "journal", "pub_date", "url"])
        writer.writeheader()
        for record in records:
            writer.writerow({field: record.get(field, "") for field in writer.fieldnames})


if __name__ == "__main__":
    raise SystemExit(main())
