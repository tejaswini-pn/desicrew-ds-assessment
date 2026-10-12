@echo off
REM One-click setup + run for Windows. Requires Python 3.10+ on PATH.
REM NOTE: keep this folder in a path WITHOUT "&" characters (e.g. D:\desicrew-ds-assessment).
cd /d "%~dp0"
if not exist .env (
  copy .env.example .env >nul
  echo Created .env - paste your GEMINI_API_KEY into it, save, then run this file again.
  notepad .env
  exit /b
)
if not exist .venv\Scripts\python.exe ( python -m venv .venv )
set PY=.venv\Scripts\python.exe
if not exist .venv\installed.flag (
  %PY% -m pip install -r requirements.txt || ( echo PIP INSTALL FAILED & pause & exit /b )
  echo ok> .venv\installed.flag
)
echo.
echo === Q3: running document pipeline (a few minutes) ===
%PY% q3_document_pipeline\pipeline.py
echo.
echo === Q2: running the 13-turn demo conversation ===
%PY% q2_support_assistant\demo_conversation.py
echo.
echo === Launching the three apps in your browser ===
start "Q1 Inventory Agent" %PY% -m streamlit run q1_inventory_agent\app.py --server.port 8501
start "Q2 Support Assistant" %PY% -m streamlit run q2_support_assistant\app.py --server.port 8502
start "Q3 Review UI" %PY% -m streamlit run q3_document_pipeline\review_app.py --server.port 8503
pause
