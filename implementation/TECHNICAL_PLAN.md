# TECHNICAL_PLAN.md

## MVP Technical Stack

- Python for fetch, normalize, diff, and report generation
- JSON/CSV for data outputs
- Markdown for reports
- GitHub Actions for scheduled updates
- Optional later static site

## Update Strategy

- Weekly disease-scoped incremental update
- Monthly disease-scoped full refresh
- Never download complete registries
- Use pagination and field selection
- Cache AI summaries by trial identifier and source update date

## AI Enrichment Layer

- Generate source-grounded rewrite prompts into `data/ai-cache/<disease>/rewrite_prompts.jsonl`
- Cache AI outputs by `trial_id:last_update_posted`
- Store patient-facing fields separately from source fields
- Require output schema for `patient_title`, `patient_summary`, `may_be_looking_for`, `may_exclude_people_who`, and `uncertainty_notes`
- Keep rule-based draft fields available when no API output exists
- Run safety checks before publishing AI text

## Multi-Source Deduplication

- Normalize each external source into a `source_record`
- Merge into a `canonical_trial` only when IDs or strong source references match
- Auto-merge exact registry IDs and secondary IDs
- Put fuzzy title/sponsor/intervention/date matches into a review queue
- Keep source-specific facts source-labeled on public pages

## Suggested Commands

```bash
python3 scripts/trial_radar.py --config configs/lupus.json --out . --page-size 1000 --timeout 45 --retries 3 --verbose
python3 scripts/trial_radar.py --config configs/lupus.json --out /tmp/trial-radar-smoke --offline-raw tests/fixtures/sample_studies
python3 -m unittest discover -s tests -v
```

## Future CLI Shape

```bash
trial-radar fetch --config configs/lupus.yml
trial-radar report --condition lupus
trial-radar diff --condition lupus
trial-radar explain --trial-id NCT00000000
```

## Testing

- Unit tests for normalization
- Snapshot tests for generated reports
- Fixture-based tests using a few sample trial records
- Safety tests for AI summary prompts and prohibited output patterns
