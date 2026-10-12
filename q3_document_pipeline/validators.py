"""Normalisation + deterministic validation of extracted values.

Each validator returns (normalised_value, status, note) where status is
  "pass"  - matches the expected format / checksum
  "fail"  - violates a hard format rule (e.g. IFSC 5th char not 0) -> strong confidence penalty
  "warn"  - format ok but a soft check failed (e.g. checksum on a sample document) -> small penalty
  "na"    - no rule for this field
"""
from __future__ import annotations

import re
from datetime import datetime

# --- Verhoeff (Aadhaar checksum)
_D = [[0,1,2,3,4,5,6,7,8,9],[1,2,3,4,0,6,7,8,9,5],[2,3,4,0,1,7,8,9,5,6],[3,4,0,1,2,8,9,5,6,7],[4,0,1,2,3,9,5,6,7,8],
      [5,9,8,7,6,0,4,3,2,1],[6,5,9,8,7,1,0,4,3,2],[7,6,5,9,8,2,1,0,4,3],[8,7,6,5,9,3,2,1,0,4],[9,8,7,6,5,4,3,2,1,0]]
_P = [[0,1,2,3,4,5,6,7,8,9],[1,5,7,6,2,8,3,0,9,4],[5,8,0,3,7,9,6,1,4,2],[8,9,1,6,0,4,3,5,2,7],
      [9,4,5,3,1,2,6,8,7,0],[4,2,8,6,5,7,3,9,0,1],[2,7,9,3,8,0,6,4,1,5],[7,0,4,6,9,1,3,2,5,8]]


def verhoeff_ok(num: str) -> bool:
    c = 0
    for i, ch in enumerate(reversed(num)):
        c = _D[c][_P[i % 8][int(ch)]]
    return c == 0


def mrz_check(s: str) -> int:
    w, t = [7, 3, 1], 0
    for i, ch in enumerate(s):
        v = 0 if ch == "<" else int(ch) if ch.isdigit() else ord(ch) - 55
        t += v * w[i % 3]
    return t % 10


# --- normalisers
def norm_date(v: str):
    s = re.sub(r"[\s]", "", v)
    s = re.sub(r"[.\-\\|]", "/", s)
    for fmt in ("%d/%m/%Y", "%d/%m/%y", "%d%m%Y", "%Y/%m/%d"):
        try:
            d = datetime.strptime(s, fmt)
            if 1900 <= d.year <= 2100:
                return d.strftime("%d/%m/%Y"), "pass", ""
        except ValueError:
            pass
    return v, "fail", "not a valid calendar date"


def _digits(v):
    return re.sub(r"\D", "", v)


def v_aadhaar(v):
    d = _digits(v)
    if len(d) != 12:
        return v, "fail", f"expected 12 digits, got {len(d)}"
    out = f"{d[:4]} {d[4:8]} {d[8:]}"
    if d[0] in "01":
        return out, "warn", "real Aadhaar numbers never start with 0/1 (sample document?)"
    return (out, "pass", "") if verhoeff_ok(d) else (out, "warn", "Verhoeff checksum fails (sample/dummy number?)")


def v_pan(v):
    s = re.sub(r"\s", "", v).upper()
    return (s, "pass", "") if re.fullmatch(r"[A-Z]{5}[0-9]{4}[A-Z]", s) else (s, "fail", "not in PAN format AAAAA9999A")


def v_ifsc(v):
    s = re.sub(r"\s", "", v).upper()
    if len(s) == 11 and s[4] == "O":  # classic handwriting confusion: letter O in the fixed zero position
        s = s[:4] + "0" + s[5:]
    return (s, "pass", "") if re.fullmatch(r"[A-Z]{4}0[A-Z0-9]{6}", s) else (s, "fail", "IFSC must be 4 letters + 0 + 6 alphanumerics")


def v_account(v):
    d = _digits(v)
    return (d, "pass", "") if 9 <= len(d) <= 18 else (d, "fail", f"bank account numbers are 9-18 digits, got {len(d)}")


def v_amount(v):
    d = _digits(v.split(".")[0])
    return (d, "pass", "") if d else (v, "fail", "no digits")


def v_appno(v):
    d = _digits(v)
    return (d, "pass", "") if 8 <= len(d) <= 16 else (d, "fail", f"unexpected length {len(d)}")


def v_passport(v):
    s = re.sub(r"\s", "", v).upper()
    return (s, "pass", "") if re.fullmatch(r"[A-Z][0-9]{7}", s) else (s, "fail", "Indian passport no. is 1 letter + 7 digits")


def v_dl(v):
    s = re.sub(r"\s+", " ", v).strip().upper()
    compact = s.replace(" ", "").replace("-", "")
    return (s, "pass", "") if re.fullmatch(r"[A-Z]{2}\d{2}\d{4}\d{7}", compact) else (s, "warn", "non-standard DL format")


def v_mrz2(v):
    s = re.sub(r"\s", "", v).upper()
    if not re.fullmatch(r"[A-Z0-9<]+", s):
        return s, "fail", "MRZ may only contain A-Z, 0-9 and '<'"
    notes = []
    if len(s) != 44:
        notes.append(f"length {len(s)} (ICAO TD3 standard is 44)")
    if len(s) >= 28:
        for name, a, b, c in (("passport no.", 0, 9, 9), ("DOB", 13, 19, 19), ("expiry", 21, 27, 27)):
            if s[c].isdigit() and mrz_check(s[a:b]) != int(s[c]):
                notes.append(f"{name} check digit mismatch")
    if len(s) != 44:  # filler '<' runs are where vision models miscount -> always human review
        return s, "fail", "; ".join(notes) + " - '<' filler count is unreliable, verify against image"
    return (s, "warn", "; ".join(notes)) if notes else (s, "pass", "")


def v_text(v):
    s = re.sub(r"\s+", " ", v).strip(" .,:;")
    return (s, "pass", "") if re.search(r"[A-Za-z]", s) else (s, "fail", "no letters")


VALIDATORS = {
    "aadhaar_number": v_aadhaar, "pan_number": v_pan, "tin_pan": v_pan, "ifsc_code": v_ifsc,
    "bank_account_number": v_account, "amount_figures": v_amount, "policy_number": v_appno,
    "application_number": v_appno, "passport_number": v_passport, "dl_number": v_dl, "mrz_line_2": v_mrz2,
    "place": v_text, "place_of_birth": v_text, "nationality": v_text, "bank_name": v_text,
}


def validate(field: str, value: str | None):
    if value is None or str(value).strip() in ("", "null", "None", "N/A"):
        return None, "fail", "empty / not found"
    value = str(value).strip()
    if "date" in field or field in ("valid_till",):
        return norm_date(value)
    fn = VALIDATORS.get(field)
    if fn:
        return fn(value)
    return re.sub(r"\s+", " ", value).strip(), "na", ""


def comparable(field: str, value) -> str:
    """Key used to decide whether two passes agree (case/space/punctuation-insensitive)."""
    if value is None:
        return ""
    return re.sub(r"[^A-Z0-9<]", "", str(value).upper())
