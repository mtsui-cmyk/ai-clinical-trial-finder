# DeepSeek Rewrite QA

Cache directory: `data/ai-cache/lupus/rewrites-flash`
Files checked: 15
Failures: 0
Records with warnings: 6

## Summary

- PASS: no prohibited clinical recommendations, ranking, or eligibility decisions detected.
- Warnings are review prompts, not automatic failures.

## Failures

No failures detected.

## Warnings

### NCT00000419
- Title: Study of Estrogen Replacement Therapy in Women with Lupus
- Review wording: safety wording / `\bsafe\b`

### NCT00001676
- Title: Cyclophosphamide and Fludarabine to Treat Lupus Nephritis
- Review wording: eligibility wording / `\beligible\b`

### NCT05859191
- Title: Studying immune cell receptors in lupus patients
- Review wording: benefit wording / `\bbenefit\b`

### NCT07085676
- Title: Study of HBI0101 CAR-T for Autoimmune Diseases
- Review wording: safety wording / `\bsafe\b`

### NCT07405970
- Title: A Study of MIL62 for Systemic Lupus Erythematosus (SLE)
- Review wording: safety wording / `\bsafe\b`

### NCT07558850
- Title: Study of Anti-CD19/BCMA CAR-T Cells for Autoimmune Diseases
- Review wording: safety wording / `\bsafe\b`

## Sample Outputs

### NCT00000416

**Patient title:** Can Vocational Rehabilitation Help People with Arthritis Keep Their Jobs?

**Summary:** People with rheumatic disorders such as arthritis often have trouble keeping their jobs. This study looked at whether vocational rehabilitation (VR) can improve the ability of employed people with arthritis to keep their jobs. The study was conducted in eastern Massachusetts. Participants were divided into two groups: one received job retention services from VR counselors, and the other received literature about employment resources. The study compared outcomes to evaluate the usefulness of job retention services in preventing job loss.

**May be looking for:**
- Adults with rheumatic disorders such as ankylosing spondylitis, knee osteoarthritis, rheumatoid arthritis, or systemic lupus erythematosus
- Currently employed (full or part time)
- Live in selected communities in eastern Massachusetts

**May exclude people who:**
- Plan to move from the area
- Plan to have joint replacement surgery within the next 6 months
- Plan to retire or go on disability within the next 2 years

### NCT00000417

**Patient title:** Improving Health in Lupus with Partner Support and Communication

**Summary:** This study examined how communication with a partner, social support, and self-efficacy (belief in managing the condition) affect health in people with lupus. Participants and their partners were assigned to either counseling to improve these skills or to watch an informational film. The study followed them for 12 months to track physical and mental health, disease activity, and other factors.

**May be looking for:**
- People with systemic lupus erythematosus (SLE or lupus)
- Have a partner who is willing to participate in the study

**May exclude people who:**
- are unable to read and write English questionnaires
- cannot be reached by phone
- have a rheumatologist who considers them unable to participate due to cognitive problems or severe illness

### NCT00000419

**Patient title:** Study of Estrogen Replacement Therapy in Women with Lupus

**Summary:** This study was designed to see safety questions about estrogen replacement therapy in postmenopausal women with lupus (systemic lupus erythematosus). The researchers wanted to understand how estrogen replacement might affect lupus disease activity and severity.

**May be looking for:**
- Women with a confirmed diagnosis of lupus (SLE)
- Women whose lupus is inactive or stable on low-dose prednisone (0.5 mg/kg/day or less)
- Women who have gone through menopause (no periods for at least 6 months or chemical evidence of menopause)

**May exclude people who:**
- Have high blood pressure (over 145/95 on three occasions)
- Have had a blood clot (deep vein thrombosis, pulmonary embolism, or arterial thrombosis)
- Have high levels of antiphospholipid antibodies

### NCT00000420

**Patient title:** Safety of Estrogen in Lupus: A Study on Birth Control Pills

**Summary:** This study aimed to test safety questions about estrogen use in women with systemic lupus erythematosus (SLE or lupus). The researchers looked at the effects of birth control pills on disease activity and severity in women with SLE.

**May be looking for:**
- Women with a definite diagnosis of lupus
- Aged 18-39 if non-smoker, or 18-35 if smoker
- Inactive disease or stable on low-dose prednisone (0.5 mg/kg/day or less)

**May exclude people who:**
- Have high blood pressure over 145/95 on three occasions
- Have had deep vein thrombosis, arterial thrombosis, or pulmonary embolism
- Have elevated antiphospholipid antibodies (GPL >40, MPL >40, APL >50, dRVVT >37 sec)

### NCT00000421

**Patient title:** Study of C3a Blood Test to Predict Lupus Flares

**Summary:** This study explored whether a blood protein called C3a can help predict lupus flares. Researchers also tested if early treatment based on C3a and dsDNA antibodies, before physical symptoms appear, could reduce the number of flares and the total amount of steroids needed. Participants were followed for one year.

**May be looking for:**
- People who meet the American College of Rheumatology (ACR) criteria for systemic lupus erythematosus (SLE)
- People whose lupus is inactive or stable
- People with a history of positive dsDNA antibodies

**May exclude people who:**
- Have active infections
- Have poorly controlled diabetes
- Are pregnant

### NCT00001212

**Patient title:** Study of Drug Therapy for Membranous Lupus Nephropathy

**Summary:** This study looked at different combinations of immunosuppressive drugs for people with membranous lupus nephropathy, a kidney condition linked to lupus. The goal was to see if these drugs could reduce protein in the urine and prevent kidney failure. Participants were followed for 12 months.

**May be looking for:**
- People with systemic lupus erythematosus (SLE) as defined by at least 4 criteria from the American Rheumatism Association
- Individuals aged 12 years or older
- Those with membranous lupus nephropathy showing 2 or more grams of protein in urine per day, without infection or other kidney disease

**May exclude people who:**
- Have taken cytotoxic drugs or cyclosporin A for more than 2 weeks in the 10 weeks before starting the study

### NCT00001372

**Patient title:** Understanding Lupus: A Study of Patients and Their Relatives

**Summary:** This study is designed to learn more about how systemic lupus erythematosus (SLE) develops and changes over time, and to explore genetic factors that may increase the risk of developing the disease. Researchers will evaluate people with known or suspected SLE, as well as their first- and second-degree relatives. Participants will undergo a variety of tests and procedures, including blood draws, imaging studies, and possibly biopsies, to gather information about the disease. The goal is to better understand SLE and identify potential genetic markers. The study is currently recruiting in the United States.

**May be looking for:**
- Individuals aged 3 years or older with known or suspected systemic lupus erythematosus (SLE)
- First- or second-degree relatives of individuals with SLE (for genetic studies)

**May exclude people who:**
- Are younger than 3 years old
- Do not have known or suspected SLE (for the patient group)
- Are not first- or second-degree relatives of a person with SLE (for the relative group)

### NCT00001676

**Patient title:** Cyclophosphamide and Fludarabine to Treat Lupus Nephritis

**Summary:** This study evaluated a combination of two drugs, cyclophosphamide and fludarabine, for lupus nephritis (kidney inflammation) in people with systemic lupus erythematosus. The goal was to see if fludarabine could be given with lower doses of cyclophosphamide while still controlling kidney inflammation. The study is now complete.

**May be looking for:**
- People aged 18 years and older
- People diagnosed with systemic lupus erythematosus (SLE)
- People with active lupus nephritis confirmed by a kidney biopsy within the past year (class III or IV)

**May exclude people who:**
- People with very active kidney disease on biopsy (e.g., crescents or necrosis in more than 25% of glomeruli)
- People with rapidly worsening kidney function (doubling of creatinine in 3 months or less)
- People with severe kidney impairment (creatinine >2.5 mg/dL or GFR <50 mL/min)

### NCT00001789

**Patient title:** A Study of BG9588 for Lupus Nephritis

**Summary:** This study looked at whether the experimental drug BG9588 (anti-CD40L antibody) was being studied for lupus nephritis with different side-effect questions compared with standard treatments like cyclophosphamide, azathioprine, and prednisone. It was a Phase 2 study completed in the United States.

**May be looking for:**
- Adults aged 18 years or older
- A kidney biopsy within the past 5 years showing active lupus nephritis (WHO Class III, IV, or mixed membranous and proliferative)
- Protein in urine of 1 gram or more per day (measured twice before starting the study)

**May exclude people who:**
- Have a medical disorder that, in the investigator's opinion, would make the study unsafe or inappropriate
- Have had a prior arterial or venous thrombosis, or a history of recurrent clotting events

### NCT00004375

**Patient title:** Ultraviolet A-1 Light Therapy for Lupus

**Summary:** This study looks at how ultraviolet A-1 (UVA-1) light therapy may affect people with systemic lupus erythematosus (SLE) and healthy volunteers. Researchers want to understand the mechanisms of this therapy.

**May be looking for:**
- People aged 15 to 70 with symptomatic lupus meeting American Rheumatism Association criteria
- Healthy volunteers aged 15 to 70 (normal controls)

**May exclude people who:**
- People who require tetracycline or other photosensitizing drugs
