# ROADMAP.md

## Phase 0: Scope and Safety

- Pick first disease area
- Define disease terms and exclusions
- Write safety boundaries
- Define source policy
- Define initial schema

## Phase 1: Data MVP

- Fetch disease-scoped ClinicalTrials.gov records
- Normalize core fields
- Export JSON and CSV
- Add reproducible command/script

## Phase 2: Repo-Native Reporting

- Generate README dashboard
- Generate weekly Markdown report
- Add snapshot diffing
- Track new trials and status changes

## Phase 3: User-Friendly Web Layer

- [x] Generate static dashboard
- [x] Default to current/open research
- [x] Render patient-friendly trial cards
- [x] Add clinician discussion questions
- [x] Add phase/status explanation
- [x] Rework homepage from metrics-first dashboard to topic-first research navigator
- [x] Split patient-start homepage from full Data Explorer module
- [x] Add dedicated topic pages between homepage and source-record exploration
- [x] Add guided patient-friendly filters before advanced registry-field filters
- [x] Make search and common filters obvious on the homepage and Explorer entry point
- [x] Redesign core flow as Finder-first app shell across home, explorer, topic, and trial detail pages

## Phase 4: Performance and Detail Pages

- [x] Split one large `site/index.html` into index plus per-trial detail pages
- [x] Add print-friendly trial detail pages
- [x] Add intervention landscape pages
- [x] Add recent changes page
- [x] Add plain-language glossary
- [x] Add disease radar index page
- [x] Add region filter and non-US quick view
- [x] Add AI explained filter
- [x] Add print-friendly weekly brief
- [x] Add information hierarchy cleanup for topic navigation, landscape brief, and lower-density trial cards
- [ ] Add optional on-demand JSON detail loading if disease datasets become much larger

## Phase 5: AI Enrichment

- [x] Add template-based plain-language trial summaries
- [x] Add intervention classification from registry fields
- [x] Add source-grounded rewrite prompt pack
- [x] Add optional AI rewrite script with strict JSON schema
- [x] Integrate reviewed AI cache into published detail pages
- [x] Add visible AI coverage status and current/open prompt queue
- [x] Add guided search that maps plain-language research requests into safe filters
- [x] Add AI record reader sections to trial detail pages
- [x] Add weekly AI public-data briefing prompt workspace
- [x] Cache AI outputs
- [ ] Add safety checks for prohibited claims
- [ ] Expand reviewed AI rewrite coverage to all current/open records

## Phase 6: Open-Source Productization

- [x] Add disease config file
- [x] Add CLI or script entry points
- [x] Add GitHub Action workflow
- [x] Add contribution guide
- [x] Add example disease radar

## Phase 7: Additional Research Layers

- Link publications by trial identifier where possible
- [x] Add PubMed-by-trial-ID source layer sample
- Add regulatory public records where appropriate
- Add company pipeline source notes
- Add device-specific public-record source layer
- Add fuzzy duplicate review queue for multi-source records
