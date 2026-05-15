# CONTRIBUTING.md

This project welcomes contributions that improve public-data quality, transparency, and patient-friendly research education.

## Good Contributions

- Add or improve disease configs
- Improve field normalization
- Improve Markdown report formatting
- Add tests and sample fixtures
- Add official public data source notes
- Improve glossary language
- Fix source-linked factual errors

## Contributions That Need Extra Care

- AI-generated trial summaries
- Mechanism-of-action explanations
- Drug/device alias normalization
- Eligibility wording
- Regulatory status interpretation

These should cite public sources and avoid medical advice.

## Not Accepted

- Patient-specific matching logic
- Treatment recommendations
- Drug/device ranking
- Claims that a therapy is safe or effective beyond public source wording
- Personal health data examples
- Scraped proprietary medical education or paid database content

## Local Development

Run tests:

```bash
python3 -m unittest discover -s tests -v
```

Run a fixture smoke test:

```bash
python3 scripts/trial_radar.py --config configs/lupus.json --out /tmp/trial-radar-smoke --offline-raw tests/fixtures/sample_studies
```

Run the lupus data refresh:

```bash
python3 scripts/trial_radar.py --config configs/lupus.json --out . --page-size 1000 --timeout 45 --retries 3 --verbose
```

