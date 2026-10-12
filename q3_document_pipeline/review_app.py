"""Human-review UI for pipeline output.  Run:  streamlit run q3_document_pipeline/review_app.py"""
import json
import os
import sys

import pandas as pd
import streamlit as st

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from pipeline import load_pages  # noqa: E402

st.set_page_config(page_title="Document Extraction Review", page_icon="🗂️", layout="wide")
res_path = os.path.join(HERE, "output", "results.json")
if not os.path.exists(res_path):
    st.error("No results yet - run `python q3_document_pipeline/pipeline.py` first.")
    st.stop()
data = json.load(open(res_path, encoding="utf-8"))
docs = data["documents"]

st.title("🗂️ Document classification & extraction — review queue")
nf = sum(f["flagged"] for d in docs for f in d["fields"].values())
nt = sum(len(d["fields"]) for d in docs)
c1, c2, c3, c4 = st.columns(4)
c1.metric("Documents", len(docs))
c2.metric("Fields extracted", nt)
c3.metric("Fields flagged for review", nf)
c4.metric("Threshold", data["threshold"])

summary = pd.DataFrame([{
    "File": d["file"], "Type": d["doc_type_name"], "Class. conf": d["classification_confidence"],
    "Handwritten": "✍" if any(f["handwritten"] for f in d["fields"].values()) else "", "Fields": len(d["fields"]),
    "Flagged": sum(f["flagged"] for f in d["fields"].values()),
    "Status": "⚠ review" if d.get("document_flagged") else "✓ auto-approved"} for d in docs])
st.dataframe(summary, hide_index=True, width="stretch")

if data.get("consistency_warnings"):
    with st.expander(f"Cross-document warnings ({len(data['consistency_warnings'])})"):
        for w in data["consistency_warnings"]:
            st.write("• " + w)

st.divider()
names = [f"{'⚠ ' if d.get('document_flagged') else '✓ '}{d['file']} — {d['doc_type_name']}" for d in docs]
idx = st.selectbox("Open document", range(len(docs)), format_func=lambda i: names[i])
d = docs[idx]
left, right = st.columns([1, 1.2])
with left:
    for p in load_pages(os.path.join(HERE, "input", d["file"])):
        st.image(p, width="stretch")
with right:
    st.subheader(d["doc_type_name"])
    st.caption(f"classification confidence {d['classification_confidence']} · evidence: {d.get('classification_evidence', '')}")
    for r in d.get("flag_reasons", []):
        st.warning(r)
    if d["fields"]:
        rows = [{"Field": f["label"], "Value": f["value"], "Confidence": f["confidence"],
                 "Handwritten": "✍" if f["handwritten"] else "", "Status": "⚠ review" if f["flagged"] else "✓",
                 "Pass A": f["readings"].get("pass_a"), "Pass B": f["readings"].get("pass_b"),
                 "Validation": f"{f['validation']['status']} {f['validation']['note']}".strip(),
                 "Why flagged": "; ".join(f["flag_reasons"])} for f in d["fields"].values()]
        df = pd.DataFrame(rows)
        st.dataframe(df.style.map(lambda v: "background-color:#fde2e1" if v == "⚠ review" else
                                  ("background-color:#e3f5e1" if v == "✓" else ""), subset=["Status"])
                     .format({"Confidence": "{:.2f}"}), hide_index=True, width="stretch")
    with st.expander("Raw JSON"):
        st.json(d)
