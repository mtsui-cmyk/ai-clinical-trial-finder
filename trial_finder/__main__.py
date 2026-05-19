"""Run the on-demand finder API with uvicorn."""

from __future__ import annotations

import uvicorn

from trial_finder.settings import load_settings


if __name__ == "__main__":
    settings = load_settings()
    uvicorn.run("trial_finder.service:app", host=settings.uvicorn_host, port=settings.uvicorn_port, reload=False)
