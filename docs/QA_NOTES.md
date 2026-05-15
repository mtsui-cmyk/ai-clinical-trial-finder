# QA_NOTES.md

## QA Cycle: 2026-05-07

### Automated Checks

- Unit tests: passed
- Fixture smoke generation: passed
- Real ClinicalTrials.gov lupus generation: passed
- Generated static site JavaScript syntax check: passed
- Per-trial detail page generation: passed
- Intervention landscape page generation: passed
- Static local link scan: passed, 8,369 links checked, 0 missing
- Browser QA in Codex in-app browser: passed, no console errors
- AI rewrite prompt generation: passed, 1,433 JSONL prompts
- Optional AI rewrite script dry run: passed, no API calls made
- DeepSeek Flash rewrite QA: passed, 10 files checked, 0 failures, 2 review warnings
- AI explained homepage filter: passed, 10 matching records
- Weekly brief browser QA: passed
- Source records detail-page QA: passed
- PubMed layer sample: passed, 25 trial IDs queried, 7 PubMed records found
- Publications page browser QA: passed

### Current Dataset Snapshot

- Total public records: 1,433
- Current/open records: 470
- Recruiting/opening records: 407
- Historical/closed records: 727
- Unclear status records: 236
- Trial detail pages: 1,433
- Intervention pages: 1,387

### Persona Review

#### Patient / Caregiver

Findings:

- Dense table-first UI was too difficult.
- Old historical records should not dominate the default view.
- Users need plain-language details and clinician discussion prompts.

Changes made:

- Replaced table-first result display with trial cards.
- Defaulted to current/open records.
- Added "How To Read This" guide.
- Replaced inline expandable details with separate per-trial detail pages.
- Added clickable intervention landscape pages.
- Added plain-language glossary.
- Added questions to discuss with a clinician.
- Added source-grounded patient reading sections with "may be looking for" and "may exclude people who" wording.
- Added region filter and non-US quick view.
- Added AI explained filter.
- Added source records section to trial detail pages.
- Added print-friendly weekly brief page.
- Added PubMed-by-NCT-ID source layer and publications page.

Remaining risks:

- Some eligibility excerpts are still dense because they come from registry text.
- Plain-language summaries are template-based and not yet high-quality AI rewrites.
- Homepage still embeds compact data for all records and is about 1.5MB for the lupus dataset.
- Intervention pages can still feel research-heavy for a first-time patient.
- Rule-based eligibility simplification can still miss nuance; true AI output should be reviewed before publication.
- Flash was more reliable than Pro in 10-record QA. Pro had slow responses and repeated empty-content failures on one sample.
- PubMed records are exact-ID source links only in this phase. No fuzzy publication matching was used.

#### NGO / Patient Advocate

Findings:

- Needs shareable public-data interpretation, not patient lead generation.
- Needs transparency and source links.

Changes made:

- Kept open JSON/CSV and weekly Markdown outputs.
- Preserved source URLs.
- Added safety and methodology docs.
- Added recent changes page for public-data monitoring.

Remaining risks:

- No newsletter/RSS output yet.
- No per-disease printable briefing view yet.

#### Clinician / Medical Advisor

Findings:

- Must avoid eligibility decisions and treatment recommendations.
- Phase/status wording must avoid implying quality or suitability.

Changes made:

- Added explicit non-recommendation language.
- Questions are phrased for clinician discussion.
- Detail panel says it cannot determine eligibility.
- Intervention pages explicitly avoid evaluating safety, effectiveness, availability, or suitability.

Remaining risks:

- Mechanism and outcome explanations are not yet medically reviewed.

#### Programmer / Open-Source Contributor

Findings:

- Repo-native data outputs are useful.
- Static HTML now embeds too much data as feature depth increases.

Changes made:

- Added tests, config, GitHub Action, contributing guide.
- Added generated detail pages, intervention pages, changes page, and glossary page.
- Added static local link scanning during QA.
- Added canonical/source-record fields for future multi-source deduplication.

Remaining risks:

- `site/index.html` is about 1.5MB after moving trial detail data to separate pages.
- Full static site is larger after 1,433 trial detail pages plus 1,387 intervention pages.

#### AI Product Manager

Findings:

- AI should improve understanding, not make clinical decisions.
- The next useful AI layer is better summary, eligibility simplification, and update briefings with source traceability.

Changes made:

- Added rule-based question prompts.
- Kept AI boundaries documented.
- Identified AI layer as explanation and summarization only, not matching, ranking, or recommendation.
- Added optional OpenAI rewrite script and strict JSON schema cache path.

Remaining risks:

- LLM enrichment is wired as an optional script but not executed in the generated site because no API key was used in QA.
- Published pages still use the rule-based patient reading unless reviewed AI cache files are generated and integrated.
