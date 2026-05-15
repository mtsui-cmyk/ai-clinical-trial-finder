# Deduplication Strategy

Multi-source clinical research data will create duplicates. The same study can appear in ClinicalTrials.gov, WHO ICTRP, EU CTIS, country registries, publications, company pipeline pages, and press releases. The project should not display those as separate studies unless they are truly separate records.

## Core Model

Use two layers:

- `source_record`: one raw public record from one source.
- `canonical_trial`: the merged public-study concept shown to users.

Every normalized record should keep:

- `canonical_trial_key`: stable internal key for the merged record.
- `source_records`: source name, record ID, URL, and source update date.
- `registry_id`: the source-specific primary ID.
- `secondary_ids`: other public IDs listed by the source.

## Matching Priority

1. Exact registry ID match, such as the same NCT ID.
2. Secondary ID match, such as a EudraCT, CTIS, sponsor protocol, or registry cross-reference.
3. Trial acronym or sponsor protocol ID plus sponsor.
4. Highly similar title plus overlapping sponsor, condition, intervention, phase, and start date.
5. Publication or press release mentions a registry ID.

Only tiers 1-3 should auto-merge. Tiers 4-5 should create a review queue unless the evidence is very strong.

## Do Not Merge When

- The records study different populations, arms, phases, or dates.
- A company uses the same intervention in separate disease areas.
- A publication discusses a program but does not identify a specific trial.
- A press release describes a pipeline milestone without enough trial identifiers.

## User-Facing Display

The trial page should show one canonical study page with a "Source records" section. That section can list ClinicalTrials.gov, EU CTIS, WHO ICTRP, PubMed, FDA/EMA, company pipeline, and press-release links as separate evidence objects.

## Why This Matters

For patients and NGOs, duplicate records can make a field look more active than it really is. For developers, over-merging is also dangerous because it hides differences between sources. The safe default is:

- exact IDs merge automatically
- fuzzy matches are flagged for review
- source-specific facts keep their source label
