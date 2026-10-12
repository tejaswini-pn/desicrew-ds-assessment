"""Document-aware support assistant with session memory (Question 2).

Per turn:
  1. Query understanding (LLM, JSON): rewrite the user message into a standalone search
     query using the conversation so far, detect topic switches, and detect if the user is
     re-asking something already answered.
  2. Retrieval: TF-IDF over heading-level sections of the knowledge base (each section has a
     stable citation id such as  [PAY-01 §2.3 Common reasons a mandate is rejected]).
  3. Grounded answer (LLM): sees the retrieved sections, the chat history and a ledger of
     facts/sections ALREADY given to the user, and is told to not repeat them - refer back instead.
  4. Session memory update: the ledger records which sections were cited and a one-line
     summary of what was told, so later turns can avoid repetition.
"""
from __future__ import annotations

import glob
import json
import os
import re
import sys
from dataclasses import dataclass, field

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from common.llm import DEFAULT_MODEL, get_client, types, with_retry  # noqa: E402

KB_DIR = os.path.join(os.path.dirname(__file__), "knowledge_base")


# --------------------------------------------------------------------------- knowledge base
@dataclass
class Section:
    doc_id: str      # e.g. PAY-01
    doc_title: str
    number: str      # e.g. 2.3
    title: str
    parent: str      # e.g. "2. NACH auto-debit"
    text: str

    @property
    def cite(self) -> str:
        return f"[{self.doc_id} §{self.number} {self.title}]"


def load_kb(kb_dir: str = KB_DIR) -> list[Section]:
    sections: list[Section] = []
    for path in sorted(glob.glob(os.path.join(kb_dir, "*.md"))):
        lines = open(path, encoding="utf-8").read().splitlines()
        doc_title = lines[0].lstrip("# ").strip()
        m = re.search(r"document ([A-Z]+-\d+)", "\n".join(lines[:3]))
        doc_id = m.group(1) if m else os.path.basename(path)
        parent, cur, buf = "", None, []

        def flush():
            if cur:
                sections.append(Section(doc_id, doc_title, cur[0], cur[1], parent, " ".join(buf).strip()))

        for ln in lines[1:]:
            if ln.startswith("### "):
                flush()
                num, _, title = ln[4:].partition(" ")
                cur, buf = (num, title.strip()), []
            elif ln.startswith("## "):
                flush()
                cur, buf = None, []
                parent = ln[3:].strip()
            elif cur and ln.strip():
                buf.append(ln.strip())
        flush()
    return sections


class Retriever:
    def __init__(self, sections: list[Section]):
        self.sections = sections
        corpus = [f"{s.doc_title} {s.parent} {s.title} {s.title} {s.text}" for s in sections]
        self.vec = TfidfVectorizer(stop_words="english", ngram_range=(1, 2), sublinear_tf=True)
        self.mat = self.vec.fit_transform(corpus)

    def search(self, query: str, k: int = 4, min_score: float = 0.05) -> list[tuple[Section, float]]:
        sims = cosine_similarity(self.vec.transform([query]), self.mat)[0]
        order = sims.argsort()[::-1][:k]
        return [(self.sections[i], float(sims[i])) for i in order if sims[i] >= min_score]


# --------------------------------------------------------------------------- session memory
@dataclass
class SessionMemory:
    turns: list[dict] = field(default_factory=list)          # {"user","assistant","topic","cites"}
    ledger: dict[str, str] = field(default_factory=dict)     # cite -> what was already told
    topic: str = ""

    def history_text(self, last: int = 6) -> str:
        out = []
        for t in self.turns[-last:]:
            out.append(f"User: {t['user']}\nAssistant: {t['assistant']}")
        return "\n\n".join(out) or "(no previous turns)"

    def ledger_text(self) -> str:
        if not self.ledger:
            return "(nothing yet)"
        return "\n".join(f"- {c}: {s}" for c, s in self.ledger.items())


# --------------------------------------------------------------------------- prompts
UNDERSTAND_PROMPT = """You are the query-understanding step of an insurance customer-support assistant.

Current topic: {topic}
Recent conversation:
{history}

New user message: "{message}"

Return JSON with:
- "standalone_query": the message rewritten as a self-contained search query (resolve pronouns like "it", "that form", "what about monthly" using the conversation). Include key nouns.
- "topic": a 2-5 word label for the topic of the NEW message.
- "topic_switch": true ONLY if the new message moves to a different subject area (e.g. from premium payments to policy assignment, or from servicing to claims). Follow-ups, clarifications and sub-questions about the same subject are NOT switches (first message: false).
- "repeat_of_previous": true if the user's information need is essentially the same as an EARLIER user question in the conversation, even if reworded (words like "again" are a strong hint).
- "chit_chat": true if it is a greeting/thanks/small talk with no information need."""

ANSWER_PROMPT = """You are "Suraksha Help", a support assistant for Suraksha Life Insurance. Answer ONLY from the knowledge-base sections below.

RULES
1. Cite the exact section for every fact using its citation tag exactly as given, e.g. [PAY-01 §2.3 Common reasons a mandate is rejected]. Put the tag right after the sentence it supports. Every answer that contains facts must have at least one citation.
2. Do NOT repeat information already given in this session (see "Already told"). If a needed fact was already given, refer back briefly ("as I mentioned earlier, ... [cite]") in at most one short clause, then add only what is NEW.
3. If the user re-asks something already answered, say so kindly, give a one-line recap with the citation, and ask what part is unclear.
4. Only if "Topic switch detected" below is True: acknowledge the switch in a few words (e.g. "Switching to claims —"), then answer; don't drag in the old topic unless genuinely relevant. If it is False, do NOT say "switching" - just continue the conversation naturally.
5. If the sections do not contain the answer, say you don't have that in the documentation and suggest contacting support - do not invent facts.
6. Be concise: 2-6 sentences or a short list. Friendly, plain English.

Topic switch detected: {switch}   |   Repeat question detected: {repeat}

Already told to the user this session (citation -> what was said):
{ledger}

Conversation so far:
{history}

Knowledge-base sections retrieved for this turn:
{context}

User: {message}"""

LEDGER_PROMPT = """For each citation tag used in the assistant answer below, write a <=15-word note of what fact(s) the answer told the user from that section.
Return JSON object mapping citation tag -> note. Only include tags that appear in the answer.

Answer:
{answer}"""


def _json(text: str) -> dict:
    text = text.strip()
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.M).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.S)
        return json.loads(m.group(0)) if m else {}


# --------------------------------------------------------------------------- assistant
class SupportAssistant:
    def __init__(self, model: str = DEFAULT_MODEL):
        self.sections = load_kb()
        self.retriever = Retriever(self.sections)
        self.by_cite = {s.cite: s for s in self.sections}
        self.client = get_client()
        self.model = model
        self.memory = SessionMemory()

    def _gen(self, prompt: str, json_mode=False, temperature=0.2) -> str:
        cfg = types.GenerateContentConfig(
            temperature=temperature,
            response_mime_type="application/json" if json_mode else None,
        )
        r = with_retry(self.client.models.generate_content, model=self.model, contents=prompt, config=cfg)
        return r.text or ""

    def chat(self, message: str) -> dict:
        mem = self.memory
        # 1. understand
        u = _json(self._gen(UNDERSTAND_PROMPT.format(
            topic=mem.topic or "(none yet)", history=mem.history_text(), message=message), json_mode=True))
        query = u.get("standalone_query") or message
        switch = bool(u.get("topic_switch")) and bool(mem.turns)
        repeat = bool(u.get("repeat_of_previous"))

        # 2. retrieve (standalone query + raw message, merged)
        hits: dict[str, tuple[Section, float]] = {}
        if not u.get("chit_chat"):
            for q in (query, message):
                for s, sc in self.retriever.search(q):
                    if s.cite not in hits or hits[s.cite][1] < sc:
                        hits[s.cite] = (s, sc)
        ranked = sorted(hits.values(), key=lambda x: -x[1])[:5]
        context = "\n\n".join(f"{s.cite} (from '{s.doc_title}' > {s.parent})\n{s.text}" for s, _ in ranked) \
            or "(no relevant sections)"

        # 3. answer
        answer = self._gen(ANSWER_PROMPT.format(
            switch=switch, repeat=repeat, ledger=mem.ledger_text(), history=mem.history_text(),
            context=context, message=message)).strip()

        # 4. update memory
        used = [c for c in self.by_cite if c in answer]
        if used:
            notes = _json(self._gen(LEDGER_PROMPT.format(answer=answer), json_mode=True))
            norm = {re.sub(r"[\[\]\s]", "", k): v for k, v in notes.items()}
            for c in used:
                prev = mem.ledger.get(c)
                note = notes.get(c) or norm.get(re.sub(r"[\[\]\s]", "", c)) or "covered"
                mem.ledger[c] = note if not prev or note in prev else f"{prev}; {note}"
        mem.topic = u.get("topic") or mem.topic
        turn = {"user": message, "assistant": answer, "topic": mem.topic, "topic_switch": switch,
                "repeat": repeat, "standalone_query": query, "cites": used,
                "retrieved": [(s.cite, round(sc, 3)) for s, sc in ranked]}
        mem.turns.append(turn)
        return turn

    def section_text(self, cite: str) -> str:
        s = self.by_cite.get(cite)
        return f"**{s.doc_title}** › {s.parent} › {s.number} {s.title}\n\n{s.text}" if s else ""
