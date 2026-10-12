# DesiCrew Data Science Internship — Round 1 Solutions

Three LLM applications built in Python with **Google Gemini** (`gemini-3.8-flash-lite` by default) and **Streamlit**.

| # | Task | Folder | UI |
|---|---|---|---|
| 1 | Agent that answers questions about an Excel dataset (writes & runs code, searches definitions, summarises in plain English) | `q1_inventory_agent/` | Chat app on :8501 |
| 2 | Document-aware support assistant with multi-turn memory, no repetition, topic switching and section-level citations | `q2_support_assistant/` | Chat app on :8502 + 13-turn scripted demo |
| 3 | Pipeline that classifies 10+ KYC/insurance documents, extracts fields with **per-field confidence**, and flags low-confidence fields for human review | `q3_document_pipeline/` | Review app on :8503 + JSON/Markdown outputs |

## Quick start

1. Install **Python 3.10+**.
2. Get a free Gemini API key at <https://aistudio.google.com/apikey>.
3. **Windows:** double-click `setup_and_run.bat`. The first run creates `.env` and opens it in Notepad. Paste the key, save, then run the file again.
   **macOS/Linux:** `cp .env.example .env`, add the key, then `./setup_and_run.sh`.

The script creates a virtualenv, installs `requirements.txt`, runs the Q3 pipeline and the Q2 demo conversation, then opens the three apps.

Manual steps:
```bash
pip install -r requirements.txt
streamlit run q1_inventory_agent/app.py                 # Q1 chat
streamlit run q2_support_assistant/app.py               # Q2 chat
python   q2_support_assistant/demo_conversation.py      # Q2 13-turn transcript -> demo_transcript.md
python   q3_document_pipeline/pipeline.py               # Q3 -> output/
streamlit run q3_document_pipeline/review_app.py        # Q3 review UI
```
Options: `GEMINI_MODEL=gemini-3.8-pro` in `.env` reads handwriting better (slower, lower free quota). `pipeline.py --threshold 0.9 --min-interval 6` changes the review threshold and the pause between API calls (to stay under free-tier limits).

---

## Q1 — Inventory data agent

**Architecture:** a hand-written Gemini function-calling loop (up to 8 steps per question) with two tools:

* `run_python(code)` runs model-written pandas code against a copy of the DataFrame `df` and returns the printed output and any traceback. The model is told to use it for *every* number. When code fails, the model sees the error and fixes it. It runs on a thread with a timeout.
* `search_definitions(query)` checks a curated inventory glossary first (turnover, sell-through, COGS, reorder point, DIO…), then a live **DuckDuckGo** web search, and returns snippets with source URLs.
* The final answer is plain English: the direct answer first, key figures, then the definition used and its source.

**Data loading:** the sheet has a title block above the table. The loader finds the header row automatically, flattens the multi-line headers (`"Opening \nStock"` becomes `Opening Stock`) and converts the numeric columns. You can upload any other `.xlsx` from the sidebar.

**Transparency:** each answer has an "Agent steps" expander showing the exact code that ran, its output, and the search results.

Data-quality finding worth asking about: **12 of 46 products break the stock identity** `Opening + Stock in − Sold = Hand-In-Stock` (e.g. P140 USB Hub: 35 + 12 − 4 = 43, but 31 is recorded). The agent's system prompt tells it to look for this kind of inconsistency.

Example questions: *"Which 5 products hold the most inventory value?"*, *"What is inventory turnover and which items turn fastest?"*, *"Are there rows where the numbers don't add up?"*, *"Compare sell-through for gaming products vs the rest."*

## Q2 — Document-aware support assistant

**Knowledge base:** four help-centre documents I wrote for a fictional insurer, "Suraksha Life" (`knowledge_base/*.md`: Premium Payments PAY-01, Policy Servicing SRV-02, Claims CLM-03, Buying a Policy ONB-04). They are split into **29 numbered sections**, and each section gets a stable citation tag such as `[PAY-01 §2.3 Common reasons a mandate is rejected]`.

**Each turn runs four steps:**
1. **Query understanding** (JSON mode): rewrite the message into a standalone query ("how long does *that* take?" becomes "NACH mandate registration time"), label the topic, and detect a **topic switch**, a **repeated question** or chit-chat.
2. **Retrieval:** TF-IDF (unigrams and bigrams) over the sections, using both the rewritten query and the raw message.
3. **Grounded answer:** the prompt includes the retrieved sections, recent history and the **"already told" ledger**. Rules: cite the section after each fact; don't repeat ledger facts, refer back briefly instead; on a repeat question, give a one-line recap and ask what is unclear; acknowledge topic switches; say "not in the documentation" instead of inventing.
4. **Memory update:** for each cited section, a short note of what the user was told is added to the ledger. The sidebar shows the topic, turn count and ledger live.

**Demo:** `demo_conversation.py` runs a **13-turn** conversation that covers pronoun follow-ups, a repeated question (turn 8), four topic switches, a switch back, an out-of-scope question (car insurance) and a sign-off. The transcript is saved to `q2_support_assistant/demo_transcript.md`.

## Q3 — Classification & extraction pipeline

```
image/PDF ─► classify (11 classes incl. "other") ─► extract pass A (original image)
                                                  └► extract pass B (enhanced image, box-by-box)
          ─► agree? ── no ──► adjudication call (both readings + format hint), confidence capped at 0.70
          ─► validate (IFSC / PAN / passport regex, account length, dates, Aadhaar Verhoeff, MRZ check digits)
          ─► cross-document checks (application no. majority vote, FATCA TIN vs PAN card)
          ─► per-field confidence ─► flag < 0.85
```

**Outputs in `q3_document_pipeline/output/`:**
* `json/<file>.json`: structured JSON per document with **value, confidence, handwritten and flagged for every field**.
* `results.json`: full detail, including both raw readings, adjudication reasoning and validation results.
* `flagging_report.md`: **the threshold (0.85) and why it was chosen**, a table of flagged fields with reasons, flagged documents, cross-document warnings, and every extracted field.
* `HANDWRITING_NOTES.md`: how handwritten text is handled differently from printed text, and the failure cases seen.

**How confidence is scored:** the starting point is the average of the two passes' self-reported confidence. Format-valid adds +0.05; a hard format failure caps it at 0.40; a checksum warning costs −0.05; pass disagreement caps it at 0.70; handwritten values are capped at 0.97; a cross-document match adds +0.05. A field is auto-accepted only if two independent reads agree, the model is confident, and the value is format-valid.

**Notes:** 12 files were supplied: the 10 target documents plus `Assignment Ashok.pdf` and `Proposal Ashok.pdf`. The two PDFs don't match any of the 10 types, so they are classified as `other` and flagged. File names are never used for classification.

## Repository layout
```
common/llm.py                 Gemini client, retry/backoff
q1_inventory_agent/           agent.py (tools + loop), app.py (chat UI), data/
q2_support_assistant/         assistant.py, app.py, demo_conversation.py, knowledge_base/
q3_document_pipeline/         pipeline.py, schemas.py, validators.py, review_app.py, input/, output/, HANDWRITING_NOTES.md
screenshots/                  screenshots of the working apps
```
