#!/usr/bin/env bash
set -e; cd "$(dirname "$0")"
[ -f .env ] || { cp .env.example .env; echo "Add GEMINI_API_KEY to .env and re-run"; exit 1; }
[ -d .venv ] || python3 -m venv .venv
source .venv/bin/activate && pip install -q -r requirements.txt
python q3_document_pipeline/pipeline.py
python q2_support_assistant/demo_conversation.py
streamlit run q1_inventory_agent/app.py --server.port 8501 &
streamlit run q2_support_assistant/app.py --server.port 8502 &
streamlit run q3_document_pipeline/review_app.py --server.port 8503
