# Publishing to GitHub

This repository can be public if secrets and local caches stay out of git.

## What Is Safe to Publish

- Source code under `trial_finder/` and `scripts/`
- Static site under `site/`
- Public ClinicalTrials.gov-derived normalized outputs under `data/current/`
- Public prompt packs under `data/ai-cache/` when they contain registry fields only
- Tests, fixtures, docs, configs, and reports

## What Must Not Be Published

- `.env`, `.env.local`, or any file containing provider keys
- `.trial-finder-cache/`
- `data/raw/` unless deliberately reviewed
- Private patient data, user location history, medical records, or lead lists

## First Public Push

```bash
python3 -m unittest discover -s tests -v

grep -RInE \
  --exclude-dir=.git \
  --exclude-dir=.trial-finder-cache \
  --exclude-dir=.venv \
  --exclude-dir=venv \
  --exclude=.env.example \
  '(sk-[A-Za-z0-9_-]{20,}|ghp_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]{20,}|xox[baprs]-[A-Za-z0-9-]{20,}|AIza[A-Za-z0-9_-]{20,}|Bearer[[:space:]]+[A-Za-z0-9._-]{20,}|API_KEY=.*[A-Za-z0-9_-]{16,}|SECRET=.*[A-Za-z0-9_-]{16,}|TOKEN=.*[A-Za-z0-9_-]{16,})' .
```

The grep command should return no real secrets. `.env.example` placeholders are allowed.

Then initialize and push:

```bash
git init
git add .
git status --short
git commit -m "Initial AI clinical trial finder"
git branch -M main
git remote add origin git@github.com:<your-user-or-org>/<repo>.git
git push -u origin main
```

## GitHub Pages

For the static site, enable GitHub Pages from the repository settings and publish from the `main` branch. The user-facing static dashboard will be under:

```text
https://<your-user-or-org>.github.io/<repo>/site/
```

The dynamic finder API (`python3 -m trial_finder`) needs a backend host and will not run on GitHub Pages alone.

## API Key Rule

ClinicalTrials.gov does not need a key. Optional AI enrichment should run server-side or locally with environment variables. Never put model provider keys in browser JavaScript.
