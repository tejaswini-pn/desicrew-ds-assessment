"""Streamlit chat UI for the inventory agent.  Run:  streamlit run q1_inventory_agent/app.py"""
import os
import sys

import pandas as pd
import streamlit as st

sys.path.insert(0, os.path.dirname(__file__))
from agent import InventoryAgent, load_inventory  # noqa: E402

st.set_page_config(page_title="Inventory Data Agent", page_icon="📦", layout="wide")
st.title("📦 Inventory Data Agent")
st.caption("Ask questions about the inventory spreadsheet. The agent writes & runs pandas code, "
           "looks up definitions, and explains the result in plain English.")

with st.sidebar:
    st.header("Dataset")
    up = st.file_uploader("Upload a different .xlsx (optional)", type=["xlsx"])
    if up is not None and st.session_state.get("file_name") != up.name:
        st.session_state.df = load_inventory(up)
        st.session_state.file_name = up.name
        st.session_state.pop("agent", None)
        st.session_state.messages = []
    if "df" not in st.session_state:
        st.session_state.df = load_inventory()
        st.session_state.file_name = "Inventory-Records-Sample-Data.xlsx"
    df: pd.DataFrame = st.session_state.df
    st.write(f"**{st.session_state.file_name}** — {len(df)} rows × {len(df.columns)} cols")
    st.dataframe(df, height=300, hide_index=True)
    st.markdown("**Try asking:**\n"
                "- Which 5 products have the highest inventory value?\n"
                "- What is inventory turnover, and which items turn fastest?\n"
                "- Are there any rows where the stock numbers don't add up?\n"
                "- What's the sell-through rate for gaming products vs the rest?")
    if st.button("Clear chat"):
        st.session_state.messages = []
        st.session_state.pop("agent", None)

if "agent" not in st.session_state:
    try:
        st.session_state.agent = InventoryAgent(df=st.session_state.df)
    except RuntimeError as e:
        st.error(str(e))
        st.stop()
st.session_state.setdefault("messages", [])

ICON = {"run_python": "🐍 Ran code", "search_definitions": "🔎 Searched"}


def render_trace(trace):
    if not trace:
        return
    with st.expander(f"Agent steps ({len(trace)} tool call{'s' if len(trace) != 1 else ''})"):
        for s in trace:
            st.markdown(f"**{ICON.get(s['tool'], s['tool'])}**")
            if s["tool"] == "run_python":
                st.code(s["args"].get("code", ""), language="python")
            else:
                st.markdown(f"Query: `{s['args'].get('query', '')}`")
            st.code(s["output"], language="text")


for m in st.session_state.messages:
    with st.chat_message(m["role"]):
        st.markdown(m["content"].replace("$", "\\$"))
        render_trace(m.get("trace"))

if prompt := st.chat_input("Ask about the inventory…"):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)
    with st.chat_message("assistant"):
        status = st.status("Thinking…", expanded=False)
        answer, trace = st.session_state.agent.ask(
            prompt, on_step=lambda s: status.write(f"{ICON.get(s['tool'], s['tool'])}…"))
        status.update(label=f"Done — {len(trace)} tool call(s)", state="complete")
        st.markdown(answer.replace("$", "\\$"))
        render_trace(trace)
    st.session_state.messages.append({"role": "assistant", "content": answer, "trace": trace})
