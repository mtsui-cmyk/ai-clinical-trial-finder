# Security Policy

## Public Data Boundary

This project is designed for public clinical research data. The connected MVP source, ClinicalTrials.gov, does not require an API key.

The app must not collect patient health data, store patient location profiles, recommend trials, or determine eligibility.

## Secrets

Do not commit API keys, tokens, credentials, `.env` files, raw private exports, or local cache directories.

Use environment variables for optional AI enrichment:

```bash
OPENAI_API_KEY=... python3 scripts/ai_rewrite.py --dry-run
DEEPSEEK_API_KEY=... python3 scripts/ai_rewrite.py --provider deepseek --dry-run
```

Local secret files such as `.env.local` are ignored by git. If a key is ever committed or pasted into a public issue, revoke it in the provider dashboard and create a new key.

## GitHub Release Checklist

- Run `python3 -m unittest discover -s tests -v`.
- Run a local secret scan before the first push.
- Confirm `.env*`, `.trial-finder-cache/`, `data/raw/`, and local virtual environments are not staged.
- Keep AI outputs source-grounded and cached; the browser UI should not expose model provider keys.

## Reporting

For now, open a private maintainer issue or contact the repository owner directly for security concerns.
