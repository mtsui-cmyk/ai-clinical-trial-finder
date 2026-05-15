# COMPETITIVE_POSITIONING.md

## Comparator Products

### ClinicalTrialsFinder

ClinicalTrialsFinder presents itself as a recruiting clinical trial search service. Its public homepage says it searches actively recruiting trials and uses ClinicalTrials.gov and ANZCTR data.

Implication:

- Stronger than a raw registry for patient search
- Still mostly a broad trial finder
- Its user promise is search, eligibility review, and alerts

### FindMyClinicalTrial

FindMyClinicalTrial is framed around active and recruiting clinical trials across the United States.

Implication:

- More US-centric
- More recruitment/partner oriented
- Less like an open-source research landscape dataset

### WithPower

WithPower offers patient-friendly trial browsing by condition, location, and drug type, with plain-English summaries and some verified trials.

Implication:

- Stronger product polish
- More commercial and patient-matching oriented
- Not positioned as open data infrastructure for NGOs

### CureMap

CureMap is closer to a public-service framing. It focuses on plain-language search, map/list views, and ClinicalTrials.gov data.

Implication:

- Good reference for patient-friendly UX
- Still primarily "find clinical trials near you"
- Not disease-specific research pipeline tracking

## Our Differentiation

Do not compete as another generic trial finder.

Compete as:

> Open disease research radar for patients, caregivers, advocates, and NGOs.

Differentiators:

- Disease-specific research landscape, not generic "near me" search
- Current/open research view by default
- Historical records retained as archive, not mixed into default user results
- Open JSON/CSV data
- Open methodology
- GitHub-native reproducibility
- Weekly NGO-style report
- No patient data collection
- No eligibility matching
- No treatment recommendation
- Future support for publications, regulatory records, device records, company pipeline signals

## Handling Outdated Records

Problem:

Clinical trial registries include old records from 2008 or earlier. These are still valid public archive records, but they are often not useful to patients trying to understand current research activity.

Product decision:

- Default dashboard view shows `current` records only.
- `current` includes:
  - Recruiting
  - Not yet recruiting
  - Enrolling by invitation
  - Active, not recruiting
- `historical` includes:
  - Completed
  - Terminated
  - Withdrawn
  - Suspended
  - No longer available
- `unclear` includes records where registry status is unknown.

The historical archive remains searchable, but users must intentionally switch to all records or historical records.

## Better-Than-Generic-Trial-Finder Thesis

Generic trial finder:

- "Find a clinical trial near you"
- Focuses on location, eligibility, recruiting status
- Often US-centric
- May feel like lead generation

Open disease research radar:

- "Understand what is happening in this disease's public research landscape"
- Focuses on interventions, sponsors, phases, countries, and changes
- Better for NGOs and patient communities
- Transparent and source-linked
- Does not collect patient health data

