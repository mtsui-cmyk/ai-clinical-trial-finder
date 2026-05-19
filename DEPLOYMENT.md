# Deployment

TrialCompass has two parts:

- Static pages in `site/`
- FastAPI backend for `/api/search`, `/api/sources`, `/api/trials/{id}`, `/api/ai/read-trial/{id}`, and `/health`

The backend is required for live trial search. GitHub Pages alone can host static pages, but it cannot run the API.

## Local Docker Run

```bash
docker compose up --build
```

Make sure Docker Desktop or your Docker daemon is running before using this command.

Open:

```text
http://127.0.0.1:8000/finder.html
```

Check backend health:

```bash
curl http://127.0.0.1:8000/health
```

## Environment Variables

| Variable | Default | Notes |
| --- | --- | --- |
| `TRIAL_FINDER_CACHE` | `.trial-finder-cache` | Runtime cache directory. Keep it out of git. |
| `TRIAL_FINDER_CACHE_TTL_DAYS` | `7` | Deletes older public source cache files on startup. |
| `TRIAL_FINDER_RATE_LIMIT_PER_MINUTE` | `60` | Per-client API limit for `/api/*`. Set `0` to disable. |
| `TRIAL_FINDER_ALLOW_ORIGINS` | `*` | Comma-separated CORS origins for hosted frontends. |
| `TRIAL_FINDER_GEOCODER` | `local` | Use `local` by default. Optional `nominatim` sends typed unknown places to Nominatim. |
| `TRIAL_FINDER_UVICORN_HOST` | `127.0.0.1` | Use `0.0.0.0` in containers. |
| `TRIAL_FINDER_UVICORN_PORT` | `8000` | Backend port. |

ClinicalTrials.gov does not require an API key.

## Render

1. Create a new Web Service from the GitHub repository.
2. Use Docker as the runtime.
3. Set the health check path to `/health`.
4. Add environment variables:

```text
TRIAL_FINDER_CACHE=/app/.trial-finder-cache
TRIAL_FINDER_CACHE_TTL_DAYS=7
TRIAL_FINDER_RATE_LIMIT_PER_MINUTE=60
TRIAL_FINDER_ALLOW_ORIGINS=https://your-frontend.example
TRIAL_FINDER_GEOCODER=local
TRIAL_FINDER_UVICORN_HOST=0.0.0.0
TRIAL_FINDER_UVICORN_PORT=8000
```

5. Deploy and test `/finder.html` and `/health`.

## Railway or Fly.io

Use the included `Dockerfile`. Keep the same environment variables as Render, and expose port `8000`.

For Fly.io, create a persistent volume if you want cache files to survive restarts. The cache stores public source responses and hashed query metadata only; it does not store raw user location history.

## GitHub Pages Plus Backend

You can host static pages through GitHub Pages and point the frontend to a deployed backend. If the frontend and backend use different domains, set:

```text
TRIAL_FINDER_ALLOW_ORIGINS=https://<your-user>.github.io
```

Do not put model provider keys or server secrets in browser JavaScript.

## Privacy and Telemetry

This project does not include default telemetry. The backend health endpoint does not call home.

If you deploy TrialCompass publicly, consider opening an issue or pull request to add your deployment to [WHO_IS_USING.md](WHO_IS_USING.md). Please do not include patient data, search logs, private location data, or personal medical information.

## Pre-Deploy Checklist

```bash
python3 -m unittest discover -s tests -v
docker compose up --build
curl http://127.0.0.1:8000/health
```

Before making the repository public, also read [SECURITY.md](SECURITY.md) and [docs/PUBLISHING.md](docs/PUBLISHING.md).
