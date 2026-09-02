# ConvCS Clinical Sheet Integration

## Source analysed

- Workbook: `ConvCS_Clinical_Master_Engine`
- Spreadsheet ID: `1vRBGlkjGuO1xPFbQs6HRXRdrhdTuttkijmfFKfR720s`
- Time zone: `Asia/Riyadh`
- Mode in the agent: read-only clinical knowledge retrieval

## Current structure

| Tab | Records | Purpose | Agent use |
| --- | ---: | --- | --- |
| `Chronic_Disease_Somatic_Map` | 6 | Mixed physiological, movement, emotional, and supportive-protocol mapping | Hypothesis generation only; biomedical claims require corroboration |
| `Meditation_Protocols` | 4 | Guided supportive practices | Optional adjunct only; never a substitute for indicated care |
| `Clinical_Guidance_Engine` | 3 | Patient-language reframing examples | Clinician-reviewed communication drafts |
| `Keyword_Phrases_Bank` | 5 | Clinical and content phrases | Educational wording drafts; remove blame and certainty |
| `Symptoms_Psychological_Roots` | 20 | Symptom-to-emotional-root hypotheses | Reflection only; never diagnosis, medical fact, or proven etiology |

The populated area uses 3–8 columns per tab. The inspected workbook contains 38 records in total. Several rows in `Symptoms_Psychological_Roots` do not populate the sixth header field, so the connector tolerates missing trailing cells while validating the required headers.

## Runtime link

`connectors/clinical_sheet_knowledge.py` uses the existing Google service account with the `spreadsheets.readonly` scope. The workbook remains separate from the operational `GOOGLE_SHEET_ID` used for tasks, briefs, and conversation receipts.

Optional Railway variable:

```text
CLINICAL_KNOWLEDGE_SHEET_ID=1vRBGlkjGuO1xPFbQs6HRXRdrhdTuttkijmfFKfR720s
```

The same ID is the safe code default. The workbook must be shared with the `client_email` inside the already configured `GOOGLE_SERVICE_ACCOUNT_JSON` as Viewer.

## Telegram behavior

- `/clinical_source_status` checks credentials, workbook access, and the five required tabs without sending a model prompt.
- `/clinical_ref <symptom or concept>` returns provenance-labelled sheet matches without a model call.
- Normal clinical questions automatically retrieve a bounded evidence bundle before the protected clinical model route.
- Queries containing an MRN, medical-record/identity number, phone number, or email are rejected before retrieval.

## Mandatory clinical boundary

1. Red flags and conventional clinical assessment come first.
2. Emotional or psychological-root statements are reflection hypotheses only.
3. The agent must not imply that emotions caused cancer, infection, obesity, or another disease.
4. Meditation and reframing may be optional supportive tools, never replacements for referral, medication, urgent care, or indicated treatment.
5. Every clinical output remains specialist-review-required and uses hypothesis, confirmation, and test-retest language.

## Verification

The automated tests cover provenance, tab-level policy labels, rejection of private identifiers, non-causation instructions, and fail-closed schema validation.
