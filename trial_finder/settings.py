"""Runtime settings for the TrialCompass API."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class AppSettings:
    cache_root: str = ".trial-finder-cache"
    cache_ttl_days: int = 7
    rate_limit_per_minute: int = 60
    geocoder: str = "local"
    allow_origins: tuple[str, ...] = ("*",)
    uvicorn_host: str = "127.0.0.1"
    uvicorn_port: int = 8000


def load_settings() -> AppSettings:
    return AppSettings(
        cache_root=os.environ.get("TRIAL_FINDER_CACHE", ".trial-finder-cache"),
        cache_ttl_days=_int_env("TRIAL_FINDER_CACHE_TTL_DAYS", 7, minimum=0),
        rate_limit_per_minute=_int_env("TRIAL_FINDER_RATE_LIMIT_PER_MINUTE", 60, minimum=0),
        geocoder=os.environ.get("TRIAL_FINDER_GEOCODER", "local").strip().lower() or "local",
        allow_origins=_origins_env("TRIAL_FINDER_ALLOW_ORIGINS"),
        uvicorn_host=os.environ.get("TRIAL_FINDER_UVICORN_HOST", "127.0.0.1"),
        uvicorn_port=_int_env("TRIAL_FINDER_UVICORN_PORT", 8000, minimum=1),
    )


def _int_env(name: str, default: int, minimum: int | None = None) -> int:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer") from exc
    if minimum is not None and value < minimum:
        raise RuntimeError(f"{name} must be >= {minimum}")
    return value


def _origins_env(name: str) -> tuple[str, ...]:
    raw = os.environ.get(name)
    if not raw:
        return ("*",)
    origins = tuple(item.strip() for item in raw.split(",") if item.strip())
    return origins or ("*",)
