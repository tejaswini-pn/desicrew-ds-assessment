# Flagging report — fields below confidence threshold

*Model:* `gemini-3.8-flash-lite` · *Documents:* 12 · **Threshold: 0.85**

## Threshold choice & rationale

A field is sent to human review when its final confidence is **< 0.85**. Final confidence is not the model's self-reported number alone; it combines: (1) the average self-reported confidence of two independent extraction passes (original image, and a contrast-enhanced/upscaled image read character by character); (2) agreement between the two passes — any disagreement is capped at 0.7, so it **always** goes to review even after adjudication; (3) deterministic validation (IFSC/PAN/passport regex, account-number length, real calendar dates, Aadhaar Verhoeff and MRZ check digits): a hard failure caps confidence at 0.40; (4) handwritten values are capped at 0.97; (5) cross-document consistency (the same application number appears on several forms).

0.85 was chosen because, in an insurance onboarding pipeline, a wrong IFSC / account number causes a failed mandate or a debit from the wrong account, which is far costlier than a 30-second human check. With this scoring, a field only clears 0.85 when two independent readings agree *and* the model is confident *and* (where a rule exists) the value is format-valid. Lowering to ~0.75 would let single-read, disagreeing values through; raising to ~0.95 would send nearly every handwritten field to review and remove the benefit of automation.

## Flagged fields (2)

| File | Document type | Field | Extracted value | Confidence | Handwritten | Reason |
|---|---|---|---|---|---|---|
| ChatGPT Image May 2, 2026, 03_52_54 PM.png | Passport | MRZ Line 2 | `X1234567<7IND7912185M3001010<<<<<<<<<<<<<<<08` | 0.40 | no | validation failed: length 45 (ICAO TD3 standard is 44); DOB check digit mismatch; expiry check digit mismatch - '<' filler count is unreliable, verify against image |
| Illustration.jpeg | Benefit Illustration Declaration | Date | `20/04/2026` | 0.70 | yes | date differs from the other declaration forms (26/04/2026) - possible misread |

## Documents flagged for review

- **Assignment Ashok.pdf** (Other / Unsupported): Document type is not one of the 10 supported types - route to manual handling.
- **ChatGPT Image May 2, 2026, 03_52_54 PM.png** (Passport): 1 field(s) below threshold: MRZ Line 2
- **Illustration.jpeg** (Benefit Illustration Declaration): 1 field(s) below threshold: Date
- **Proposal Ashok.pdf** (Other / Unsupported): Document type is not one of the 10 supported types - route to manual handling.

## Cross-document consistency warnings

- Illustration.jpeg: Date '20/04/2026' differs from the other forms' date '26/04/2026'
- Fatca.jpeg: FATCA TIN/PAN 'BPQPD3051R' does not match the PAN card in the set (ABCDE1234F) - extraction kept as written; KYC team should confirm.

## All extracted fields

| File | Type | Field | Value | Conf. | HW | Flag |
|---|---|---|---|---|---|---|
| Aadhar.png | Aadhaar Card | Aadhaar Number | `1234 5678 9012` | 0.95 |  | ✓ |
| Aadhar.png | Aadhaar Card | Full Name | `Mr. Ashok` | 1.00 |  | ✓ |
| Aadhar.png | Aadhaar Card | Date of Birth | `18/12/1979` | 0.99 |  | ✓ |
| Aadhar.png | Aadhaar Card | Address | `S/O Kumar, Kataia, West Bihar, India - 841543` | 1.00 |  | ✓ |
| ChatGPT Image May 2, 2026, 03_43_11 PM.png | Driving Licence | DL Number | `MH12 2021 0001234` | 0.99 |  | ✓ |
| ChatGPT Image May 2, 2026, 03_43_11 PM.png | Driving Licence | Name | `MR. ASHOK` | 1.00 |  | ✓ |
| ChatGPT Image May 2, 2026, 03_43_11 PM.png | Driving Licence | Date of Issue | `15/06/2021` | 0.99 |  | ✓ |
| ChatGPT Image May 2, 2026, 03_43_11 PM.png | Driving Licence | Valid Till | `14/06/2041` | 0.99 |  | ✓ |
| ChatGPT Image May 2, 2026, 03_52_54 PM.png | Passport | Passport Number | `X1234567` | 0.99 |  | ✓ |
| ChatGPT Image May 2, 2026, 03_52_54 PM.png | Passport | Date of Birth | `18/12/1979` | 0.99 |  | ✓ |
| ChatGPT Image May 2, 2026, 03_52_54 PM.png | Passport | Date of Expiry | `01/01/2030` | 0.99 |  | ✓ |
| ChatGPT Image May 2, 2026, 03_52_54 PM.png | Passport | MRZ Line 2 | `X1234567<7IND7912185M3001010<<<<<<<<<<<<<<<08` | 0.40 |  | ⚠ |
| ECS.jpeg | NACH / ECS Mandate | Bank Account Number | `31004258912` | 0.97 | ✍ | ✓ |
| ECS.jpeg | NACH / ECS Mandate | IFSC Code | `SBIN0227112` | 0.97 | ✍ | ✓ |
| ECS.jpeg | NACH / ECS Mandate | Bank Name | `State Bank of India` | 0.97 | ✍ | ✓ |
| ECS.jpeg | NACH / ECS Mandate | Amount (figures) | `50000` | 0.97 | ✍ | ✓ |
| ECS.jpeg | NACH / ECS Mandate | Frequency | `As & when presented` | 0.97 | ✍ | ✓ |
| Fatca.jpeg | FATCA Annexure Form | Policy Number | `1500137601025` | 0.99 | ✍ | ✓ |
| Fatca.jpeg | FATCA Annexure Form | TIN / PAN | `BPQPD3051R` | 0.97 | ✍ | ✓ |
| Fatca.jpeg | FATCA Annexure Form | Father's Name | `Arjun Das Kumar` | 0.96 | ✍ | ✓ |
| Fatca.jpeg | FATCA Annexure Form | Place of Birth | `West Bihar` | 0.95 | ✍ | ✓ |
| Fatca.jpeg | FATCA Annexure Form | Nationality | `Indian` | 0.97 | ✍ | ✓ |
| ID.png | PAN Card | PAN Number | `ABCDE1234F` | 0.99 |  | ✓ |
| ID.png | PAN Card | Full Name | `MR. ASHOK` | 1.00 |  | ✓ |
| ID.png | PAN Card | Father's Name | `S/O KUMAR` | 1.00 |  | ✓ |
| ID.png | PAN Card | Date of Birth | `18/12/1979` | 0.99 |  | ✓ |
| Illustration.jpeg | Benefit Illustration Declaration | Application Number | `1500137601025` | 0.99 | ✍ | ✓ |
| Illustration.jpeg | Benefit Illustration Declaration | Policyholder Name | `Ashok` | 0.96 | ✍ | ✓ |
| Illustration.jpeg | Benefit Illustration Declaration | Date | `20/04/2026` | 0.70 | ✍ | ⚠ |
| Illustration.jpeg | Benefit Illustration Declaration | Place | `West Bihar` | 0.88 | ✍ | ✓ |
| Moral.jpeg | Moral Hazard Questionnaire | Application Number | `1500137601025` | 0.99 | ✍ | ✓ |
| Moral.jpeg | Moral Hazard Questionnaire | Name of Life Assured | `Ashok` | 0.97 | ✍ | ✓ |
| Moral.jpeg | Moral Hazard Questionnaire | Nominee Relationship | `Nephew` | 0.97 | ✍ | ✓ |
| Moral.jpeg | Moral Hazard Questionnaire | Date | `26/04/2026` | 0.97 | ✍ | ✓ |
| Moral.jpeg | Moral Hazard Questionnaire | Place | `West Bihar` | 0.97 | ✍ | ✓ |
| split.jpeg | Multiple Policies Consent Form | Proposer Name | `Ashok` | 0.97 | ✍ | ✓ |
| split.jpeg | Multiple Policies Consent Form | Reason for Multiple Policies | `Financial Planning (viz. payout on different life stages, different payment terms,etc.)` | 0.99 |  | ✓ |
| split.jpeg | Multiple Policies Consent Form | Date | `26/04/2026` | 0.97 | ✍ | ✓ |
| split.jpeg | Multiple Policies Consent Form | Place | `West Bihar` | 0.97 | ✍ | ✓ |
| suitability.jpeg | Suitability Profiler Declaration | Application Number | `1500137601025` | 0.99 | ✍ | ✓ |
| suitability.jpeg | Suitability Profiler Declaration | Name of Life Assured | `Ashok` | 0.97 | ✍ | ✓ |
| suitability.jpeg | Suitability Profiler Declaration | Name of Agent/SP | `Ramesh Kumar` | 0.97 | ✍ | ✓ |
| suitability.jpeg | Suitability Profiler Declaration | Date | `26/04/2026` | 0.97 | ✍ | ✓ |
| suitability.jpeg | Suitability Profiler Declaration | Place | `West Bihar` | 0.97 | ✍ | ✓ |
