# METHODOLOGY.md

## Current MVP Method

The MVP builds a disease-scoped public research radar from ClinicalTrials.gov records.

For the lupus configuration, it queries:

- `systemic lupus erythematosus`
- `lupus nephritis`

The script deduplicates records by `NCT ID`, normalizes selected fields, and generates reusable JSON, CSV, and Markdown outputs.

## Data Included

Each normalized record currently includes:

- Trial identifier and source URL
- Registry name
- Title and official title
- Conditions
- Interventions and intervention types
- Sponsor and sponsor class
- Phase
- Recruitment status
- Study type
- Countries
- Start, completion, and last-update dates where present
- Results-posted indicator
- Basic FDA-regulated drug/device flags where present in the registry
- Plain-language template summary

## Data Not Included Yet

The MVP does not yet include:

- WHO ICTRP records
- EU CTIS records
- PubMed publication matching
- FDA/EMA approval databases
- Company pipeline pages
- Press release monitoring
- Human-reviewed medical summaries
- Trial eligibility matching

## Update Model

The MVP performs a disease-scoped refresh, not a full registry download.

For lupus, the refresh currently returned 1,433 deduplicated public records. This is small enough for GitHub Actions and local execution.

Future versions should add:

- Incremental update by registry update date where supported
- Monthly disease-scoped full refresh
- Cached AI enrichment keyed by trial ID and source update date

## Interpretation Limits

The generated outputs summarize public registry records only. They should not be treated as complete, current clinical guidance or regulatory status.

Clinical trial registries can contain stale, incomplete, delayed, or sponsor-entered information. Each record keeps a source link so users can verify details in the official registry.

