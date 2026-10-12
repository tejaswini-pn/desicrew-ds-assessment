# Handwritten vs printed text — approach and failure cases

## How handwritten fields are treated differently

| | Printed (Aadhaar, PAN, DL, Passport) | Handwritten (NACH, FATCA, 4 declarations) |
|---|---|---|
| Image views | Original image | Original **plus** an enhanced view: grayscale, 1 % contrast stretch, upscaled to 2,400 px on the long side, unsharp mask, so faint ballpoint strokes and box borders separate |
| Reading strategy | Read the field as a whole | Pass B is told to read **box by box, left to right, counting boxes**, because NACH/FATCA values sit in character boxes. For checkboxes, it must find which box actually holds the tick |
| Second opinion | Second pass at temperature 0.4 | Same, and the two reads come from *different images*, so their errors are less correlated |
| Disagreement | Adjudication call with both readings and the expected format. Confidence capped at 0.70, so the field **always** goes to review | Same |
| Confusable characters | — | The prompt names the common handwriting confusions (0/O, 1/7, 5/S, 2/Z, 8/B, 6/b) and asks for `alternatives`. The IFSC validator fixes the one safe case automatically: the 5th IFSC character is always the digit 0, so a letter O there becomes 0 |
| Confidence ceiling | 0.99 | **0.97**. A handwritten reading is never treated as near-certain |
| Validation | Format/checksum, as a *soft* check (see below) | Format rules act as hard gates: IFSC `AAAA0XXXXXX`, PAN/TIN `AAAAA9999A`, account number 9–18 digits, dates must be real calendar dates, application number 8–16 digits. A failure caps confidence at 0.40 |
| Cross-document | — | The same application/policy number appears on the FATCA, NACH, Illustration, Moral-hazard and Suitability forms. Agreement with the majority adds +0.05; a mismatch caps the field at 0.70 (it is probably a misread) |

**Checksums are soft on printed IDs.** The supplied ID cards are synthetic samples. Aadhaar `1234 5678 9012` fails the Verhoeff checksum, and the passport MRZ line is 53 characters (not the ICAO 44) with a DOB check digit that doesn't match. The task is to extract what is printed, so a failed checksum on a printed field only costs −0.05 and adds a note. It does not change the value. On real documents, the same check would be a strong fraud/misread signal.

## Observed results (run with `gemini-3.8-flash-lite`)

- **Classification:** all 12 files classified correctly. The 10 target types each scored ≥ 0.99. The two PDFs (Assignment and Proposal) were classified as `other` and flagged.
- **Extraction:** 44 fields extracted and **2 flagged** at the 0.85 threshold. Every high-value handwritten field came out the same from both independent passes, and each one passed its format check:
  - NACH: account `31004258912`, IFSC `SBIN0227112`, bank `State Bank of India`, amount `50000`, frequency `As & when presented`
  - FATCA: TIN `BPQPD3051R`, father's name `Arjun Das Kumar`, place of birth `West Bihar`, nationality `Indian`
  - Nominee relationship (`Nephew`), agent name (`Ramesh Kumar`), the multiple-policies checkbox, and the dates and places on the other forms
- **Observed failure 1: MRZ line 2 (passport, printed).** The model returned 15 `<` filler characters; the printed line has 20. Counting the character glyphs in the image gives 50 in total. The model was confident (0.95), so a self-reported score alone would have accepted this wrong value. The MRZ length rule (≠ 44) caught it and capped confidence at 0.40, so the field goes to human review. Lesson: long runs of the same character are a known weakness of vision LLMs, so a deterministic length check is essential.
- **Observed failure 2: date on the Benefit Illustration (handwritten).** The date is written on top of the printed underline and the strokes overlap. Both passes read `20/04/2026` (confidence 0.90, which would have passed the threshold). The other four declaration forms all say `26/04/2026`, so the cross-document date check flagged it at 0.70. This is a case where two passes agree but are both wrong. It shows why the pipeline needs a consistency check across documents in addition to the self-consistency check between passes.
- **Real data issue, not an extraction error:** the FATCA TIN (`BPQPD3051R`) does not match the PAN card (`ABCDE1234F`). It is reported as a cross-document warning.

## Hard spots identified before the run

These are from my manual look at the 12 files while building the pipeline. After each run, `output/flagging_report.md` lists the actual flagged fields.

1. **NACH IFSC (`ECS.jpeg`).** Handwritten in boxes; the 5th character looks like an "O" and the "I" is close to a "1". The validator's O→0 repair and the `[A-Z]{4}0` rule handle the first. The second shows up as pass disagreement.
2. **NACH account number.** 11 digits written in boxes, with some strokes crossing box borders. Getting the digit count right is the main risk, which is why pass B counts boxes.
3. **NACH frequency.** The "Monthly / Qtly / H.Yrly / Yrly" options are struck through and the tick sits on "As & when presented". The tick partly overlaps the label, so models sometimes report a struck-through option. The prompt asks for the box that holds the tick.
4. **NACH amount.** The figure `₹ 50,000` and the words "Fifty thousand only" agree. The pipeline keeps the figures and strips commas.
5. **FATCA TIN.** `BPQPD3051R` is handwritten in a table cell. It is valid PAN format, but it does **not** match the PAN card in the set (`ABCDE1234F`). The pipeline keeps what is written and raises a cross-document warning instead of "fixing" it.
6. **Dates.** Handwritten `26/04/2026` with slashes that look like 1s (e.g. `26/04/2026` read as `2610412026`) on the declaration forms. Date normalisation plus calendar validation catches most of these.
7. **Place names.** "West Bihar" in cursive, where the "B" can be misread as "R"/"P". There is no format rule for free text, so for places the only guards are pass agreement and cross-document agreement.
8. **Out-of-scope documents.** `Assignment Ashok.pdf` (Assignment Request Form) and `Proposal Ashok.pdf` (proposal customer declaration) are not among the 10 target types. They are classified as `other` and the whole document is flagged rather than forced into a type.
9. **File names are not used.** Two of the files are named "ChatGPT Image …png", so classification looks only at the image content.
