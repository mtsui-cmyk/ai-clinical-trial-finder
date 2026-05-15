# USER_EXPERIENCE.md

## Intended Users

The user-friendly layer is for:

- Patients and caregivers who want to understand public research activity
- NGO and patient advocacy volunteers preparing community updates
- Researchers or journalists looking for a quick public-data overview

It is not for:

- Trial eligibility decisions
- Treatment selection
- Therapy comparison
- Personal medical interpretation

## Recommended User Experience

The public-facing experience should be a static web dashboard backed by the open repo data.

Why a webpage:

- Patients and caregivers will not read JSON or CSV first.
- NGO users need something they can share in newsletters and community chats.
- A static page can stay privacy-safe because it needs no login and collects no patient data.
- GitHub Pages can host it for free.

Why keep the repo:

- The repo provides transparency, methodology, source links, and reusable data.
- Developers and NGOs can audit how the dashboard is generated.
- Other disease communities can fork the project.

## Current Navigator

Generated file:

```text
site/index.html
```

Current features:

- A simple patient-facing home page with a clear non-medical-advice boundary
- A prominent search box on the homepage for users who already know a keyword, country, intervention, or NCT ID
- Finder-first app shell with primary routes for Search, Research areas, Open studies, Updates, and Glossary
- Three homepage route cards: browse research areas, currently open studies, and recent updates
- Visible AI tools module for local guided search, cached AI-explained records, AI record reader pages, and build-time weekly brief workspace
- AI coverage strip showing how many current/open records have reviewed AI explanations and how many remain queued for optional generation
- Compact research-area directory for lupus nephritis, cell therapy, biologics, Asia-Pacific activity, pediatric lupus, and reproductive health
- Dedicated topic pages that act like focused library pages before showing source records
- Full Data Explorer moved to `site/explorer.html`, with a search workspace and left filter rail on desktop
- "Ask the research index" guided search in the Explorer, which maps plain-language requests such as "open CAR-T studies in China" into safe filters without calling an API
- Guided filter rail in the Explorer using patient-friendly choices: research area, public status, location view, and reading mode; registry-field filters stay under Advanced filters
- Current/open research by default, with historical and unclear records still available
- Lower-density trial cards with topic, status, short summary, key interventions/countries, and source links
- Reference tables live in the explorer module, not on the patient-start home page
- AI prompt packs and an AI coverage report are generated for GitHub review, so users can distinguish reviewed AI explanations from registry-template summaries
- The browser should never trigger LLM calls. Token-spending AI work happens only at generation time and is cached.

## Closed User Flow

The current MVP now supports a full non-clinical user journey:

1. Open the disease radar homepage.
2. Search directly if the user has a keyword, country, intervention, or NCT ID, or start from a research topic such as lupus nephritis, CAR-T/cell therapy, biologics, pediatric lupus, or diagnostics.
3. Read the topic page: what the area is about, common terms, and questions to discuss with a clinician.
4. Scan a small set of current/open public records for that topic.
5. Use the visible search box, guided search, topic shortcuts, or the guided filter panel to narrow by status, region, publication-linked records, or AI-explained records.
6. Open a patient-friendly trial detail page.
7. Read plain-language context, AI record-reader notes where available, conditions, interventions, locations, eligibility snapshot, and clinician discussion questions.
8. Open the official registry record to verify details.
9. Print/save the detail page or bring the questions to a clinician.

The flow intentionally stops before medical decision-making. It does not provide eligibility matching, ranking, or treatment guidance.

## Trial Detail Experience

The dashboard now links to separate detail pages for each trial record.

The detail page shows:

- Study type
- Enrollment count where listed
- Start date
- Age and sex fields from the registry
- Results-posted indicator
- Conditions listed in the registry
- Interventions and short descriptions
- Locations
- Official summary excerpt
- Eligibility snapshot excerpt
- Questions to discuss with a clinician
- AI record-reader status: either reviewed source-grounded AI explanation or registry summary only
- AI source-grounding bullets when available
- Back-to-radar link
- Official registry link
- Print/save action

This should feel more like a public research library than a trial-matching service. It keeps the boundary strict: it does not determine eligibility, collect patient health information, recommend enrollment, or ask users to submit personal medical details.

Implementation note:

The first detail implementation embedded all details in one large HTML file. This has now been changed to separate per-trial detail pages, which makes the homepage lighter and gives users a clearer flow.

## Next UX Improvements

- Add optional on-demand JSON detail loading if disease datasets become much larger.
- Add a plain-language glossary drawer for terms like randomized, placebo, phase, sponsor, and enrollment.
- Add a richer "recently changed" view that explains what changed since the last update.
- Add RSS or newsletter-ready exports for patient organization updates.
- Expand reviewed AI rewrite coverage beyond the current cache, starting with all current/open records.

## Current vs Historical Records

The dashboard should not default to old completed trials, even though those records are preserved.

Default view:

- Recruiting
- Not yet recruiting
- Enrolling by invitation
- Active, not recruiting

Archive views:

- All public records
- Historical/closed records
- Unclear status records

This keeps the first user experience focused on the present research landscape while retaining transparency.

## Competitor Lessons Applied

Products like ClinicalTrialsFinder, FindMyClinicalTrial, WithPower, and CureMap are easier for patients than raw registry pages because they do not start with a dense database table.

Useful patterns to borrow:

- Start with simple patient-facing actions
- Explain unfamiliar terms near the results
- Show recruiting/current records before historical records
- Link back to the official registry
- Avoid making users understand every registry field before they can browse

Current design response:

- The homepage starts with a clear search box and topic navigation, then keeps the Data Explorer as a separate advanced module.
- Topic pages now sit between the homepage and the Data Explorer, so patients get explanation before a list of records.
- The Data Explorer uses a search-engine style panel first, adds guided filters directly below it, and keeps field-level filters under Advanced filters.
- Guided search is framed as filter assistance, not trial matching.
- Guided search is local browser logic, so it stays visible without creating token cost.
- AI coverage is visible rather than implied; non-AI records are treated as registry-template summaries.
- Reports and briefs are generated on demand, not every time a user browses the site.
- Trial results render as lower-density cards with plain-language notes.
- Status and phase remain visible, but they are framed as research context rather than decision guidance.
- Historical records are still searchable through the archive view.

## UX Boundaries

The interface should say:

- "Explore public research records"
- "Read plain-language research summaries"
- "Verify details in the official registry"
- "Discuss clinical questions with a licensed clinician"

The interface should not say:

- "Find the best trial for you"
- "Check if you are eligible"
- "Recommended treatments"
- "Ranked therapies"
- "Best drug/device"

## Future UX Ideas

- Disease selector
- Intervention detail pages
- Country view
- Weekly NGO briefing view
- RSS/email export
- Multilingual glossary
- Print-friendly report
