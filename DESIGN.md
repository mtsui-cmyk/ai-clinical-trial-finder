# DESIGN.md

## Concept

Open Disease Research Radar is an open-data pipeline and reporting system for tracking public research activity in a disease area.

It should answer:

- What public trials are happening for this disease?
- Which interventions are being studied?
- Which sponsors are involved?
- What phases/statuses/countries appear in public registries?
- What changed this week?
- How can patients and caregivers understand the research terminology?

It should not answer:

- Should I join this trial?
- Is this drug better than another?
- What treatment should I choose?
- Am I eligible?

## Architecture

```text
Public sources
  ClinicalTrials.gov API
  Later: WHO ICTRP, EU CTIS, regulatory databases, publications
        |
        v
Fetch layer
  paginated, disease-scoped, incremental where possible
        |
        v
Normalize layer
  trial schema, intervention schema, sponsor/country/status normalization
        |
        v
Diff layer
  new records, status changes, location changes, results posted
        |
        v
AI enrichment layer
  plain-language summaries, terminology explanations, weekly briefing
        |
        v
Outputs
  JSON, CSV, Markdown reports, README dashboard, optional GitHub Pages
```

## Data Strategy

Do not download full registries.

Use:

- Disease-scoped queries
- Pagination
- Incremental updates based on registry update dates where supported
- Monthly disease-scoped full refresh
- Snapshots for diffing
- Cached AI enrichments

## Initial Data Model

```json
{
  "trial_id": "NCT00000000",
  "registry": "ClinicalTrials.gov",
  "source_url": "https://clinicaltrials.gov/study/NCT00000000",
  "title": "...",
  "conditions": ["Systemic Lupus Erythematosus"],
  "interventions": [
    {
      "name": "...",
      "type": "drug | biologic | device | procedure | behavioral | other",
      "canonical_name": null,
      "aliases": []
    }
  ],
  "sponsor": "...",
  "phase": "Phase 2",
  "status": "Recruiting",
  "countries": ["United Kingdom"],
  "last_update_posted": "2026-05-01",
  "has_results": false,
  "ai_summary": {
    "plain_language": null,
    "generated_from_fields": [],
    "generated_at": null
  }
}
```

## Output Philosophy

Prefer transparent, reusable artifacts:

- `data/current/*.json`
- `data/current/*.csv`
- `reports/weekly/*.md`
- `docs/glossary.md`
- README dashboard tables

Website UI is optional after the data/report pipeline proves useful.

