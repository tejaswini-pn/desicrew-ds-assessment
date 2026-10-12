"""Streamlit chat UI.  Run:  streamlit run q2_support_assistant/app.py"""
import os
import re
import sys

import streamlit as st

sys.path.insert(0, os.path.dirname(__file__))
from assistant import SupportAssistant  # noqa: E402

st.set_page_config(page_title="Suraksha Help — Support Assistant", page_icon="🛟", layout="wide")
st.title("🛟 Suraksha Help — document-aware support assistant")
st.caption("Answers come only from the Help Centre documents, with a section citation on every fact. "
           "The assistant remembers the session, avoids repeating itself and handles topic switches.")

if "bot" not in st.session_state:
    try:
        st.session_state.bot = SupportAssistant()
    except RuntimeError as e:
        st.error(str(e))
        st.stop()
bot: SupportAssistant = st.session_state.bot

with st.sidebar:
    st.subheader("Session memory")
    st.write(f"**Current topic:** {bot.memory.topic or '—'}")
    st.write(f"**Turns:** {len(bot.memory.turns)}")
    st.markdown("**Already told (ledger):**")
    if bot.memory.ledger:
        for c, n in bot.memory.ledger.items():
            st.markdown(f"- `{c}` — {n}")
    else:
        st.caption("nothing yet")
    st.divider()
    st.markdown("**Knowledge base:** " + ", ".join(sorted({s.doc_id for s in bot.sections}))
                + f" ({len(bot.sections)} sections)")
    if st.button("New session"):
        del st.session_state.bot
        st.rerun()


def show_turn(t):
    with st.chat_message("user"):
        st.markdown(t["user"])
    with st.chat_message("assistant"):
        tags = []
        if t["topic_switch"]:
            tags.append("🔀 topic switch")
        if t["repeat"]:
            tags.append("🔁 repeat question")
        tags.append(f"topic: {t['topic']}")
        st.caption(" · ".join(tags))
        st.markdown(t["assistant"])
        if t["cites"]:
            with st.expander("Sources cited"):
                for c in t["cites"]:
                    st.markdown(bot.section_text(c))
                    st.divider()


for t in bot.memory.turns:
    show_turn(t)

if msg := st.chat_input("Ask about premiums, NACH, nominees, claims, buying a policy…"):
    with st.spinner("Looking it up…"):
        bot.chat(msg)
    st.rerun()
