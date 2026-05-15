"""Hash-based public source cache for on-demand searches."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any


LOCATION_CACHE_VERSION = "location-v3-research-radar"


class FinderCache:
    def __init__(self, root: Path | str = ".trial-finder-cache") -> None:
        self.root = Path(root)
        self.records_dir = self.root / "records"
        self.db_path = self.root / "metadata.sqlite3"
        self.records_dir.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS cache_entries (
                    cache_key TEXT PRIMARY KEY,
                    source_id TEXT NOT NULL,
                    condition_hash TEXT NOT NULL,
                    location_hash TEXT NOT NULL,
                    radius_km INTEGER NOT NULL,
                    statuses TEXT NOT NULL,
                    cache_date TEXT NOT NULL,
                    raw_path TEXT NOT NULL,
                    normalized_path TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )

    @staticmethod
    def build_key(source_id: str, condition_text: str, location_text: str, radius_km: int, statuses: list[str]) -> dict[str, str]:
        today = dt.date.today().isoformat()
        condition_hash = _sha256((condition_text or "").strip().lower())
        location_hash = _sha256((location_text or "").strip().lower())
        statuses_key = ",".join(sorted(statuses))
        cache_key = _sha256("|".join([LOCATION_CACHE_VERSION, source_id, condition_hash, location_hash, str(radius_km), statuses_key, today]))
        return {
            "cache_key": cache_key,
            "condition_hash": condition_hash,
            "location_hash": location_hash,
            "cache_date": today,
            "statuses_key": statuses_key,
        }

    def get(self, source_id: str, condition_text: str, location_text: str, radius_km: int, statuses: list[str]) -> dict[str, Any] | None:
        key = self.build_key(source_id, condition_text, location_text, radius_km, statuses)
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT raw_path, normalized_path FROM cache_entries WHERE cache_key = ?",
                (key["cache_key"],),
            ).fetchone()
        if not row:
            return None
        raw_path = self.root / row[0]
        normalized_path = self.root / row[1]
        if not raw_path.exists() or not normalized_path.exists():
            return None
        return {
            "raw": json.loads(raw_path.read_text(encoding="utf-8")),
            "normalized": json.loads(normalized_path.read_text(encoding="utf-8")),
            "cache_key": key["cache_key"],
        }

    def set(
        self,
        source_id: str,
        condition_text: str,
        location_text: str,
        radius_km: int,
        statuses: list[str],
        raw: Any,
        normalized: Any,
    ) -> str:
        key = self.build_key(source_id, condition_text, location_text, radius_km, statuses)
        raw_path = Path("records") / f"{key['cache_key']}.raw.json"
        normalized_path = Path("records") / f"{key['cache_key']}.normalized.json"
        (self.root / raw_path).write_text(json.dumps(raw, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        (self.root / normalized_path).write_text(
            json.dumps(normalized, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO cache_entries (
                    cache_key, source_id, condition_hash, location_hash, radius_km, statuses,
                    cache_date, raw_path, normalized_path, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    key["cache_key"],
                    source_id,
                    key["condition_hash"],
                    key["location_hash"],
                    int(radius_km),
                    key["statuses_key"],
                    key["cache_date"],
                    str(raw_path),
                    str(normalized_path),
                    dt.datetime.now(dt.timezone.utc).isoformat(),
                ),
            )
        return key["cache_key"]


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
