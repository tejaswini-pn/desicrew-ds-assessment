"""Insurance-onboarding document pipeline (Question 3).

    classify  ->  extract (2 independent passes)  ->  adjudicate disagreements
              ->  validate (format rules / checksums)  ->  cross-document consistency
              ->  per-field confidence  ->  flag below threshold for human review

Usage:
    python q3_document_pipeline/pipeline.py                       # all files in input/
    python q3_document_pipeline/pipeline.py --input some/dir --model gemini-2.5-pro
"""
from __future__ import annotations

import argparse
import io
import json
import os
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

from PIL import Image, ImageFilter, ImageOps

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
from common.llm import DEFAULT_MODEL, get_client, types, with_retry  # noqa: E402
from schemas import ALL_TYPES, CLASSIFY_GUIDE, DOC_TYPES, OTHER  # noqa: E402
from validators import comparable, validate  # noqa: E402

CONFIDENCE_THRESHOLD = 0.85
HANDWRITTEN_CAP = 0.97          # a handwritten reading is never treated as near-certain
DISAGREEMENT_CAP = 0.70         # two independent reads disagreed -> always human review
IMG_EXT = (".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff", ".bmp")


# --------------------------------------------------------------------------- image handling
def load_pages(path: str) -> list[Image.Image]:
    if path.lower().endswith(".pdf"):
        import fitz  # pymupdf
        doc = fitz.open(path)
        return [Image.open(io.BytesIO(p.get_pixmap(dpi=170).tobytes("png"))).convert("RGB") for p in doc]
    return [ImageOps.exif_transpose(Image.open(path)).convert("RGB")]


def enhance(img: Image.Image) -> Image.Image:
    """Second-view preprocessing for handwriting: grayscale, contrast stretch, upscale, unsharp mask."""
    g = ImageOps.autocontrast(ImageOps.grayscale(img), cutoff=1)
    long_side = max(g.size)
    if long_side < 2400:
        f = 2400 / long_side
        g = g.resize((int(g.width * f), int(g.height * f)), Image.LANCZOS)
    return g.filter(ImageFilter.UnsharpMask(radius=2, percent=160, threshold=3))


def to_part(img: Image.Image) -> types.Part:
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=92)
    return types.Part.from_bytes(data=buf.getvalue(), mime_type="image/jpeg")


# --------------------------------------------------------------------------- LLM calls
class Gemini:
    def __init__(self, model: str, min_interval: float):
        self.client, self.model, self.min_interval, self._last = get_client(), model, min_interval, 0.0

    def json(self, parts: list, prompt: str, schema: dict, temperature: float = 0.0) -> dict:
        wait = self.min_interval - (time.time() - self._last)
        if wait > 0:
            time.sleep(wait)
        self._last = time.time()
        cfg = types.GenerateContentConfig(temperature=temperature, response_mime_type="application/json",
                                          response_schema=schema)
        r = with_retry(self.client.models.generate_content, model=self.model,
                       contents=parts + [prompt], config=cfg, retries=6)
        return json.loads(r.text)


CLASSIFY_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "doc_type": {"type": "STRING", "enum": ALL_TYPES},
        "confidence": {"type": "NUMBER"},
        "has_handwriting": {"type": "BOOLEAN"},
        "evidence": {"type": "STRING"},
    },
    "required": ["doc_type", "confidence", "has_handwriting", "evidence"],
}

CLASSIFY_PROMPT = f"""Classify this document image (Indian KYC / life-insurance onboarding) into exactly one type:
{CLASSIFY_GUIDE}
Return: doc_type, confidence (0-1, calibrated: 0.95+ only if the title/layout is unambiguous),
has_handwriting (true if any of the filled-in values are handwritten), evidence (the title or key text you relied on)."""

FIELD_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "value": {"type": "STRING", "nullable": True},
        "confidence": {"type": "NUMBER"},
        "handwritten": {"type": "BOOLEAN"},
        "alternatives": {"type": "ARRAY", "items": {"type": "STRING"}},
        "notes": {"type": "STRING"},
    },
    "required": ["value", "confidence", "handwritten", "alternatives", "notes"],
}


def extract_schema(doc_type: str) -> dict:
    keys = list(DOC_TYPES[doc_type]["fields"])
    return {"type": "OBJECT", "properties": {k: FIELD_SCHEMA for k in keys}, "required": keys}


def field_list(doc_type: str) -> str:
    return "\n".join(f"- {k} ({lab}): {hint}" for k, (lab, hint) in DOC_TYPES[doc_type]["fields"].items())


EXTRACT_PROMPT_A = """You are a meticulous data-entry operator for an insurance company. The image is a {name}.
Extract these fields:
{fields}

For each field return:
- value: exactly what is written/printed (null if absent or blank). Do not "correct" what the customer wrote.
- confidence: 0-1, honest. Lower it for messy handwriting, overwriting, ambiguous characters (0/O, 1/7, 5/S, 2/Z, 8/B, 6/b), boxes you cannot see clearly.
- handwritten: true if this value is handwritten rather than printed.
- alternatives: other plausible readings if any character is ambiguous (empty list if none).
- notes: brief note on any difficulty."""

EXTRACT_PROMPT_B = """Second independent reading of a {name}. The image has been contrast-enhanced and enlarged.
Work character by character. For values written in boxes, read one box at a time, left to right, and count the boxes.
For ticked checkboxes, identify which box actually contains the tick mark.
Fields:
{fields}

Return value (verbatim, null if blank), confidence (0-1, honest), handwritten, alternatives (other plausible readings), notes."""

ADJUDICATE_SCHEMA = {
    "type": "OBJECT",
    "properties": {"value": {"type": "STRING", "nullable": True}, "confidence": {"type": "NUMBER"},
                   "reasoning": {"type": "STRING"}},
    "required": ["value", "confidence", "reasoning"],
}

ADJUDICATE_PROMPT = """Two independent readings of the field "{label}" on this {name} disagree:
  reading 1: {a!r}
  reading 2: {b!r}
Expected format: {hint}
Zoom in mentally on that exact field. Compare each character of both readings with the ink on the page.
Return the correct value exactly as written (it may differ from both), your confidence (0-1), and short reasoning."""


# --------------------------------------------------------------------------- core
def process_document(path: str, llm: Gemini, log=print) -> dict:
    fname = os.path.basename(path)
    pages = load_pages(path)
    orig_parts = [to_part(p) for p in pages]

    cls = llm.json(orig_parts, CLASSIFY_PROMPT, CLASSIFY_SCHEMA)
    doc_type = cls["doc_type"]
    log(f"  {fname}: classified as {doc_type} ({cls['confidence']:.2f})")
    result = {
        "file": fname, "pages": len(pages), "doc_type": doc_type,
        "doc_type_name": DOC_TYPES.get(doc_type, {}).get("name", "Other / Unsupported"),
        "classification_confidence": round(float(cls["confidence"]), 3),
        "classification_evidence": cls["evidence"], "has_handwriting": bool(cls["has_handwriting"]),
        "fields": {}, "flag_reasons": [],
    }
    if doc_type == OTHER:
        result["document_flagged"] = True
        result["flag_reasons"].append("Document type is not one of the 10 supported types - route to manual handling.")
        return result

    spec = DOC_TYPES[doc_type]
    schema = extract_schema(doc_type)
    fields = field_list(doc_type)
    enh_parts = [to_part(enhance(p)) for p in pages]
    a = llm.json(orig_parts, EXTRACT_PROMPT_A.format(name=spec["name"], fields=fields), schema)
    # second independent pass only for handwritten forms (saves API quota; printed IDs are
    # double-checked by format/checksum validators instead)
    b = llm.json(enh_parts, EXTRACT_PROMPT_B.format(name=spec["name"], fields=fields), schema, temperature=0.4) \
        if spec["handwritten"] else a

    for key, (label, hint) in spec["fields"].items():
        ra, rb = a.get(key) or {}, b.get(key) or {}
        va, sa, na = validate(key, ra.get("value"))
        vb, sb, nb = validate(key, rb.get("value"))
        handwritten = bool(ra.get("handwritten") or rb.get("handwritten"))
        reasons: list[str] = []
        record = {"label": label, "handwritten": handwritten,
                  "readings": {"pass_a": ra.get("value"), "pass_b": rb.get("value")},
                  "model_confidence": {"pass_a": ra.get("confidence"), "pass_b": rb.get("confidence")},
                  "alternatives": sorted(set((ra.get("alternatives") or []) + (rb.get("alternatives") or [])))}
        agree = comparable(key, va) == comparable(key, vb)

        if agree:
            value, status, note = va, sa, na
            conf = (float(ra.get("confidence", 0.5)) + float(rb.get("confidence", 0.5))) / 2
            record["agreement"] = "both passes agree" if spec["handwritten"] else "single pass (printed) + validation"
        else:
            adj = llm.json(orig_parts, ADJUDICATE_PROMPT.format(
                label=label, name=spec["name"], a=ra.get("value"), b=rb.get("value"), hint=hint), ADJUDICATE_SCHEMA)
            value, status, note = validate(key, adj.get("value"))
            record["readings"]["adjudicated"] = adj.get("value")
            record["adjudication_reasoning"] = adj.get("reasoning")
            conf = min(float(adj.get("confidence", 0.5)), DISAGREEMENT_CAP)
            record["agreement"] = "passes disagreed -> adjudicated"
            reasons.append(f"independent reads disagreed ({ra.get('value')!r} vs {rb.get('value')!r})")
            # if adjudicated value is invalid but one of the passes is valid, prefer the valid one
            if status == "fail" and "pass" in (sa, sb):
                value, status, note = (va, sa, na) if sa == "pass" else (vb, sb, nb)
                reasons.append("adjudicated value failed validation; fell back to the valid reading")

        if value is None:
            conf = 0.0
            reasons.append("field not found / blank")
        elif status == "pass":
            conf = min(conf + 0.05, 0.99)
        elif status == "warn":
            conf -= 0.05
        elif status == "fail":
            conf = min(conf, 0.40)
            reasons.append(f"validation failed: {note}")
        if handwritten:
            conf = min(conf, HANDWRITTEN_CAP)
        record.update({"value": value, "validation": {"status": status, "note": note},
                       "confidence": round(max(conf, 0.0), 3), "flag_reasons": reasons})
        result["fields"][key] = record
    return result


def cross_document_checks(results: list[dict]) -> list[str]:
    """Same applicant across all forms: application/policy numbers and names should agree."""
    warnings = []
    nums = [(r["file"], k, f) for r in results for k, f in r["fields"].items()
            if k in ("application_number", "policy_number") and f["value"]]
    majority = Counter(comparable(k, f["value"]) for _, k, f in nums).most_common(1)
    if majority and majority[0][1] >= 2:
        maj = majority[0][0]
        for file, k, f in nums:
            if comparable(k, f["value"]) == maj:
                f["confidence"] = round(min(f["confidence"] + 0.05, 0.99), 3)
                f["cross_check"] = f"matches application/policy no. on {majority[0][1] - 1} other document(s)"
            else:
                f["confidence"] = round(min(f["confidence"], 0.70), 3)
                f["flag_reasons"].append(f"differs from the number on other forms ({maj})")
                warnings.append(f"{file}: {f['label']} '{f['value']}' differs from majority '{maj}'")
    # all declaration forms of one application are normally signed on the same day
    dates = [(r["file"], f) for r in results for k, f in r["fields"].items() if k == "date" and f["value"]]
    dmaj = Counter(f["value"] for _, f in dates).most_common(1)
    if dmaj and dmaj[0][1] >= 2:
        for file, f in dates:
            if f["value"] != dmaj[0][0]:
                f["confidence"] = round(min(f["confidence"], 0.70), 3)
                f["flag_reasons"].append(f"date differs from the other declaration forms ({dmaj[0][0]}) - possible misread")
                warnings.append(f"{file}: {f['label']} '{f['value']}' differs from the other forms' date '{dmaj[0][0]}'")
    pan_cards = [f["value"] for r in results if r["doc_type"] == "pan_card"
                 for k, f in r["fields"].items() if k == "pan_number" and f["value"]]
    for r in results:
        tin = r["fields"].get("tin_pan")
        if tin and tin["value"] and pan_cards and comparable("x", tin["value"]) not in map(lambda v: comparable("x", v), pan_cards):
            msg = (f"{r['file']}: FATCA TIN/PAN '{tin['value']}' does not match the PAN card in the set "
                   f"({', '.join(pan_cards)}) - extraction kept as written; KYC team should confirm.")
            tin["cross_check"] = msg
            warnings.append(msg)
    return warnings


def finalise(results: list[dict], threshold: float) -> None:
    for r in results:
        for key, f in r["fields"].items():
            # re-apply current validation rules (cached results may predate a rule change)
            if f["value"] is not None:
                _, status, note = validate(key, f["value"])
                if status == "fail" and f["validation"]["status"] != "fail":
                    f["validation"] = {"status": status, "note": note}
                    f["confidence"] = round(min(f["confidence"], 0.40), 3)
                    f["flag_reasons"].append(f"validation failed: {note}")
            f["flagged"] = f["confidence"] < threshold
            if f["flagged"] and not f["flag_reasons"]:
                f["flag_reasons"].append("model confidence below threshold")
        flagged = [f["label"] for f in r["fields"].values() if f["flagged"]]
        if r["doc_type"] != OTHER and r["classification_confidence"] < 0.80:
            r["flag_reasons"].append(f"low classification confidence {r['classification_confidence']}")
        if flagged:
            r["flag_reasons"].append(f"{len(flagged)} field(s) below threshold: {', '.join(flagged)}")
        r["document_flagged"] = bool(r["flag_reasons"])
        confs = [f["confidence"] for f in r["fields"].values()]
        r["document_confidence"] = round(min([r["classification_confidence"]] + confs), 3)


def clean_output(r: dict) -> dict:
    """Compact structured JSON per document: value + confidence per field (full detail in results.json)."""
    return {
        "file": r["file"], "document_type": r["doc_type_name"],
        "classification_confidence": r["classification_confidence"],
        "document_flagged_for_review": r["document_flagged"],
        "fields": {k: {"label": f["label"], "value": f["value"], "confidence": f["confidence"],
                       "handwritten": f["handwritten"], "flagged": f["flagged"]} for k, f in r["fields"].items()},
    }


def write_report(results, warnings, threshold, model, out_dir):
    L = ["# Flagging report — fields below confidence threshold\n",
         f"*Model:* `{model}` · *Documents:* {len(results)} · **Threshold: {threshold}**\n",
         "## Threshold choice & rationale\n",
         f"A field is sent to human review when its final confidence is **< {threshold}**. "
         "Final confidence is not the model's self-reported number alone; it combines: (1) the average self-reported "
         "confidence of two independent extraction passes (original image, and a contrast-enhanced/upscaled image read "
         "character by character); (2) agreement between the two passes — any disagreement is capped at "
         f"{DISAGREEMENT_CAP}, so it **always** goes to review even after adjudication; (3) deterministic validation "
         "(IFSC/PAN/passport regex, account-number length, real calendar dates, Aadhaar Verhoeff and MRZ check digits): a "
         "hard failure caps confidence at 0.40; (4) handwritten values are capped at "
         f"{HANDWRITTEN_CAP}; (5) cross-document consistency (the same application number appears on several forms).\n",
         f"{threshold} was chosen because, in an insurance onboarding pipeline, a wrong IFSC / account number causes a "
         "failed mandate or a debit from the wrong account, which is far costlier than a 30-second human check. With "
         "this scoring, a field only clears 0.85 when two independent readings agree *and* the model is confident *and* "
         "(where a rule exists) the value is format-valid. Lowering to ~0.75 would let single-read, disagreeing values "
         "through; raising to ~0.95 would send nearly every handwritten field to review and remove the benefit of automation.\n"]
    flagged_rows = []
    for r in results:
        for k, f in r["fields"].items():
            if f["flagged"]:
                flagged_rows.append(f"| {r['file']} | {r['doc_type_name']} | {f['label']} | `{f['value']}` | "
                                    f"{f['confidence']:.2f} | {'yes' if f['handwritten'] else 'no'} | "
                                    f"{'; '.join(f['flag_reasons'])} |")
    L.append(f"## Flagged fields ({len(flagged_rows)})\n")
    if flagged_rows:
        L += ["| File | Document type | Field | Extracted value | Confidence | Handwritten | Reason |",
              "|---|---|---|---|---|---|---|"] + flagged_rows
    else:
        L.append("No field fell below the threshold.")
    L.append("\n## Documents flagged for review\n")
    for r in results:
        if r["document_flagged"]:
            L.append(f"- **{r['file']}** ({r['doc_type_name']}): {' / '.join(r['flag_reasons'])}")
    if warnings:
        L.append("\n## Cross-document consistency warnings\n")
        L += [f"- {w}" for w in warnings]
    L.append("\n## All extracted fields\n")
    L += ["| File | Type | Field | Value | Conf. | HW | Flag |", "|---|---|---|---|---|---|---|"]
    for r in results:
        for f in r["fields"].values():
            L.append(f"| {r['file']} | {r['doc_type_name']} | {f['label']} | `{f['value']}` | {f['confidence']:.2f} | "
                     f"{'✍' if f['handwritten'] else ''} | {'⚠' if f['flagged'] else '✓'} |")
    open(os.path.join(out_dir, "flagging_report.md"), "w", encoding="utf-8").write("\n".join(L) + "\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default=os.path.join(HERE, "input"))
    ap.add_argument("--output", default=os.path.join(HERE, "output"))
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--threshold", type=float, default=CONFIDENCE_THRESHOLD)
    ap.add_argument("--min-interval", type=float, default=float(os.getenv("GEMINI_MIN_INTERVAL", "4")),
                    help="seconds between API calls (free tier rate limits)")
    ap.add_argument("--workers", type=int, default=1)
    args = ap.parse_args()

    files = sorted(os.path.join(args.input, f) for f in os.listdir(args.input)
                   if f.lower().endswith(IMG_EXT + (".pdf",)))
    os.makedirs(os.path.join(args.output, "json"), exist_ok=True)
    llm = Gemini(args.model, args.min_interval)
    print(f"Processing {len(files)} documents with {args.model} ...")

    cache_dir = os.path.join(args.output, "cache")
    os.makedirs(cache_dir, exist_ok=True)

    def run(p):
        cache = os.path.join(cache_dir, os.path.basename(p) + ".json")
        if os.path.exists(cache):  # resume: don't spend quota on documents already processed
            print(f"  {os.path.basename(p)}: cached")
            return json.load(open(cache, encoding="utf-8"))
        try:
            r = process_document(p, llm)
            json.dump(r, open(cache, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
            return r
        except Exception as e:  # noqa: BLE001
            print(f"  ERROR {os.path.basename(p)}: {e}")
            return {"file": os.path.basename(p), "doc_type": OTHER, "doc_type_name": "ERROR", "fields": {},
                    "classification_confidence": 0.0, "flag_reasons": [f"processing error: {e}"]}

    with ThreadPoolExecutor(args.workers) as ex:
        results = list(ex.map(run, files))
    warnings = cross_document_checks(results)
    finalise(results, args.threshold)

    for r in results:
        stem = os.path.splitext(r["file"])[0]
        json.dump(clean_output(r), open(os.path.join(args.output, "json", f"{stem}.json"), "w"), indent=2, ensure_ascii=False)
    json.dump({"model": llm.model, "threshold": args.threshold, "consistency_warnings": warnings, "documents": results},
              open(os.path.join(args.output, "results.json"), "w"), indent=2, ensure_ascii=False)
    write_report(results, warnings, args.threshold, args.model, args.output)
    nf = sum(f["flagged"] for r in results for f in r["fields"].values())
    nt = sum(len(r["fields"]) for r in results)
    print(f"Done. {nt} fields extracted, {nf} flagged (< {args.threshold}). See {args.output}/")


if __name__ == "__main__":
    main()
