"""Inventory data agent (Question 1).

A tool-using Gemini agent that answers questions about an Excel dataset by
  1. writing and executing pandas code against the data      -> run_python
  2. looking up definitions / business context               -> search_definitions
  3. summarising the findings in plain English               -> final answer

The loop is implemented by hand (rather than SDK auto function calling) so every
tool call - the code written, its output, the search results - can be shown in the UI.
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import re
import sys
import threading
import traceback

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from common.llm import DEFAULT_MODEL, get_client, types, with_retry  # noqa: E402

DATA_PATH = os.path.join(os.path.dirname(__file__), "data", "Inventory-Records-Sample-Data.xlsx")
MAX_STEPS = 8
MAX_TOOL_OUTPUT = 6000


# --------------------------------------------------------------------------- data
def load_inventory(path: str = DATA_PATH) -> pd.DataFrame:
    """Load the sheet, auto-detecting the header row (the sample has a title block above the table)."""
    raw = pd.read_excel(path, header=None)
    header_row = next(
        i for i, row in raw.iterrows()
        if row.notna().sum() >= 3 and any(isinstance(v, str) and "product" in v.lower() for v in row)
    )
    df = pd.read_excel(path, header=header_row)
    df = df.dropna(axis=1, how="all").dropna(axis=0, how="all")
    # normalise header text: "Opening \nStock" -> "Opening Stock"
    df.columns = [re.sub(r"\s+", " ", str(c).replace("-\n", "-")).strip() for c in df.columns]
    for c in df.columns:
        if c not in ("Product ID", "Product Name"):
            df[c] = pd.to_numeric(df[c], errors="coerce")
    return df.reset_index(drop=True)


def schema_text(df: pd.DataFrame) -> str:
    buf = io.StringIO()
    buf.write(f"DataFrame `df`: {len(df)} rows x {len(df.columns)} columns\n")
    for c in df.columns:
        buf.write(f"  - {c!r} ({df[c].dtype})\n")
    buf.write("\nFirst 5 rows:\n" + df.head().to_string(index=False))
    return buf.getvalue()


# --------------------------------------------------------------------------- tools
def run_python(code: str, df: pd.DataFrame, timeout: int = 20) -> str:
    """Execute model-written pandas code against a *copy* of the data and capture stdout."""
    env = {"df": df.copy(), "pd": pd, "np": np}
    out = io.StringIO()
    result: dict = {}

    def target():
        try:
            pd.set_option("display.width", 200)
            pd.set_option("display.max_columns", 20)
            with contextlib.redirect_stdout(out):
                exec(compile(code, "<agent_code>", "exec"), env)  # noqa: S102 - local, single-user demo
            if "result" in env and not str(out.getvalue()).strip():
                print(env["result"], file=out)
        except Exception:  # noqa: BLE001
            result["error"] = traceback.format_exc(limit=2)

    t = threading.Thread(target=target, daemon=True)
    t.start()
    t.join(timeout)
    if t.is_alive():
        return f"ERROR: code timed out after {timeout}s"
    text = out.getvalue()
    if "error" in result:
        text += "\nERROR:\n" + result["error"]
    text = text.strip() or "(code ran with no output - remember to print() the answer)"
    return text[:MAX_TOOL_OUTPUT] + ("\n...[truncated]" if len(text) > MAX_TOOL_OUTPUT else "")


GLOSSARY = {
    "opening stock": "Opening stock is the quantity (or value) of inventory on hand at the start of an accounting period, carried over from the previous period's closing stock.",
    "purchase / stock in": "Stock in (purchases) is inventory received during the period - new purchases or transfers added to stock.",
    "units sold": "Units sold is the number of items that left inventory through sales during the period.",
    "hand-in-stock": "Hand-in-stock (stock on hand / closing stock) is what remains at the end of the period. Standard identity: Closing stock = Opening stock + Stock in - Units sold.",
    "cost price total": "Cost price total (inventory value at cost) = quantity on hand x cost price per unit. In this sheet it is Hand-In-Stock x Cost Price Per Unit.",
    "inventory turnover": "Inventory turnover = Cost of goods sold / Average inventory. It measures how many times stock is sold and replaced in a period; higher usually means leaner, faster-moving inventory.",
    "sell-through rate": "Sell-through rate = Units sold / (Opening stock + Units received) x 100. It shows what share of available stock was sold in the period.",
    "cogs": "Cost of goods sold (COGS) = units sold x cost per unit; the direct cost of the inventory that was sold.",
    "reorder point": "Reorder point = (average daily usage x lead time in days) + safety stock. When stock falls to this level, a replenishment order is placed.",
    "safety stock": "Safety stock is extra inventory held as a buffer against demand spikes or supplier delays.",
    "days of inventory": "Days inventory outstanding (DIO) = (Average inventory / COGS) x number of days in period; how long stock sits before it is sold.",
    "abc analysis": "ABC analysis ranks items by value: 'A' items (~20% of SKUs, ~80% of value) get the tightest control, 'C' items the least.",
    "dead stock": "Dead / slow-moving stock is inventory with little or no sales relative to what is held, tying up working capital.",
}


def search_definitions(query: str) -> str:
    """Look up a term: curated inventory glossary first, then the live web (DuckDuckGo)."""
    q = query.lower()
    hits = [f"[glossary] {k}: {v}" for k, v in GLOSSARY.items()
            if k in q or any(w in k for w in re.findall(r"[a-z\-]{4,}", q))]
    web: list[str] = []
    try:
        from ddgs import DDGS
        for r in DDGS().text(query, max_results=4):
            web.append(f"[web] {r.get('title')}: {r.get('body')} (source: {r.get('href')})")
    except Exception as e:  # noqa: BLE001 - network may be unavailable; glossary still answers
        web.append(f"[web search unavailable: {type(e).__name__}]")
    return "\n".join(hits[:4] + web) or "No results found."


TOOLS = types.Tool(function_declarations=[
    types.FunctionDeclaration(
        name="run_python",
        description=(
            "Execute Python (pandas) code against the inventory DataFrame `df` (also available: pd, np). "
            "Use print() to output results. Use this for EVERY number you report - never compute in your head."
        ),
        parameters=types.Schema(type="OBJECT", properties={
            "code": types.Schema(type="STRING", description="Python code to run. Must print() its findings."),
        }, required=["code"]),
    ),
    types.FunctionDeclaration(
        name="search_definitions",
        description=(
            "Look up the definition, formula or business context of a term (e.g. 'inventory turnover', "
            "'hand-in-stock', 'reorder point'). Searches a curated inventory glossary and the web."
        ),
        parameters=types.Schema(type="OBJECT", properties={
            "query": types.Schema(type="STRING", description="Term or question to look up."),
        }, required=["query"]),
    ),
])


SYSTEM_PROMPT = """You are an inventory data analyst agent. You answer questions about an Excel inventory dataset loaded as a pandas DataFrame `df`.

{schema}

How to work:
- For ANY quantitative question, call run_python with pandas code and base your answer on its printed output. Never guess or do arithmetic in your head.
- Column names contain spaces and slashes - always reference them exactly, e.g. df['Hand-In-Stock'].
- If the user asks what a term means, or a metric needs a definition (turnover, sell-through, reorder point...), call search_definitions first, then compute it with run_python if the data allows.
- If code errors, read the error, fix the code and try again.
- Be alert to data-quality issues (e.g. rows where Opening + Stock in - Sold != Hand-In-Stock, or Total != qty x unit cost) and mention them when relevant.

Final answer format (plain English, for a business user):
- Lead with the direct answer in one or two sentences.
- Then key supporting figures (a short bullet list or small markdown table if helpful).
- If you used a definition, state it briefly and cite where it came from (glossary or web source).
- Mention caveats/assumptions only if they matter. Keep it concise. Do not show code in the final answer."""


# --------------------------------------------------------------------------- agent
class InventoryAgent:
    def __init__(self, df: pd.DataFrame | None = None, model: str = DEFAULT_MODEL):
        self.df = df if df is not None else load_inventory()
        self.model = model
        self.client = get_client()
        self.history: list[types.Content] = []
        self.config = types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT.format(schema=schema_text(self.df)),
            tools=[TOOLS],
            temperature=0.1,
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )

    def _call_tool(self, name: str, args: dict) -> str:
        if name == "run_python":
            return run_python(args.get("code", ""), self.df)
        if name == "search_definitions":
            return search_definitions(args.get("query", ""))
        return f"Unknown tool {name}"

    def ask(self, question: str, on_step=None) -> tuple[str, list[dict]]:
        """Run the agent loop. Returns (final_answer, trace). on_step(step_dict) streams tool calls to a UI."""
        self.history.append(types.Content(role="user", parts=[types.Part(text=question)]))
        trace: list[dict] = []
        for _ in range(MAX_STEPS):
            resp = with_retry(self.client.models.generate_content,
                              model=self.model, contents=self.history, config=self.config)
            cand = resp.candidates[0].content
            self.history.append(cand)
            calls = [p.function_call for p in cand.parts or [] if p.function_call]
            if not calls:
                answer = "".join(p.text or "" for p in cand.parts or []).strip()
                return answer or "(no answer)", trace
            responses = []
            for fc in calls:
                args = dict(fc.args or {})
                output = self._call_tool(fc.name, args)
                step = {"tool": fc.name, "args": args, "output": output}
                trace.append(step)
                if on_step:
                    on_step(step)
                responses.append(types.Part.from_function_response(name=fc.name, response={"result": output}))
            self.history.append(types.Content(role="user", parts=responses))
        return "I could not finish within the step limit; partial findings are in the tool trace.", trace


if __name__ == "__main__":  # simple CLI: python agent.py "question"
    agent = InventoryAgent()
    q = " ".join(sys.argv[1:]) or "Which product has the highest total cost value?"
    ans, tr = agent.ask(q, on_step=lambda s: print(f"\n--- {s['tool']} {json.dumps(s['args'])[:300]}\n{s['output'][:800]}"))
    print("\n=== ANSWER ===\n" + ans)
