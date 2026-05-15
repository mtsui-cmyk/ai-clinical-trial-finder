# AGENTS.md

Guidance for AI assistants and collaborators working in this workspace.

## Project Mission

Create an open-source, patient-friendly research radar that organizes public clinical research information for a disease area.

The project is for education, awareness, NGO support, and research landscape understanding. It is not a medical decision tool.

## Hard Safety Boundaries

Do not build or propose features that:

- Match a patient to a trial based on personal medical details
- Recommend a drug, device, procedure, or trial
- Rank therapies by effectiveness or safety
- Interpret personal medical records, lab values, or imaging
- Provide diagnosis, prognosis, or treatment advice
- Collect patient health data
- Sell patient leads to sponsors or trial recruiters

Allowed AI roles:

- Summarize public trial records in plain language
- Explain research terminology
- Classify public interventions into broad categories
- Normalize names and aliases with source references
- Generate questions patients may discuss with licensed clinicians
- Generate weekly public-data briefings

## Product Tone

Use NGO/public-good language:

- "research landscape"
- "public registry data"
- "plain-language summary"
- "questions to discuss with a clinician"
- "not medical advice"

Avoid:

- "best trial"
- "recommended treatment"
- "eligible for you"
- "breakthrough cure"
- "personalized therapy recommendation"

## Development Principles

- Start repo-native: data files, Markdown reports, CLI/scripts, GitHub Actions.
- A website is optional and should not be the MVP dependency.
- Prefer public, official, citeable sources.
- Keep original source URLs and timestamps for every derived record.
- Cache AI outputs and regenerate only for new or changed records.
- Make disease configuration reusable so other disease radars can be forked.

## First Suggested MVP

`open-lupus-research-radar`

- Disease terms: systemic lupus erythematosus, SLE, lupus nephritis
- First source: ClinicalTrials.gov API
- Outputs: normalized JSON/CSV, README dashboard, weekly Markdown report
- AI: plain-language summary, intervention classification, weekly briefing

