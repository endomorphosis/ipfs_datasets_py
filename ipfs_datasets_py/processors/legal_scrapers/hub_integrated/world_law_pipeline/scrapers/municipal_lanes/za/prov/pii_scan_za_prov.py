#!/usr/bin/env python3
"""PII scan for ZA provincial pack1 shards (data/laws.parquet, data/articles.parquet); ported from pii_scan_za_metro.py (batch 6): every string column, every row.
FAIL kinds: sa_id_valid (13-digit run, valid YYMMDD + citizenship digit + Luhn), email_non_gov, phone_mobile,
name_near_street_address, gazette_private_notice (creditors / deceased-estate / liquor-licence notice text).
WARN kinds: sa_id_13digit_other (any other 13-digit run), phone_landline.
Output records row id, column, kind and character offset only - never the matched value."""
import json, re, sys
from datetime import date
import pyarrow.parquet as pq
GOV = re.compile(r"(?i)@(?:[a-z0-9-]+\.)*(?:gov\.za|wcpp\.gov\.za|kznlegislature\.gov\.za|parliament\.gov\.za)$")
EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
D13 = re.compile(r"(?<![0-9A-Za-z])\d{13}(?![0-9A-Za-z])")
PHONE = re.compile(r"(?<![0-9A-Za-z])(?:\+?27[\s-]?|0)\(?(\d{2})\)?[\s-]?\d{3}[\s-]?\d{4}(?![0-9A-Za-z])")
NAME = re.compile(r"\b(?:Mr|Mrs|Ms|Miss|Mnr|Mev|Me)\.?\s+(?:[A-Z]\.?\s*){0,3}[A-Z][a-z]+")
STREET = re.compile(r"\b\d{1,5}[A-Za-z]?,?\s+(?:[A-Z][a-z]+\s+){1,3}(?:Street|Road|Avenue|Crescent|Drive|Lane|Close|Way|Place|Boulevard|St|Rd|Ave|Cres|Straat|Weg|Laan|Singel)\b", re.I)
PRIV = re.compile(r"(?i)notice\s+to\s+creditors|deceased\s+estate|estate\s+late|boedel\s+wyle|liquor\s+licen[cs]e\s+application|application\s+for\s+(?:a\s+)?liquor")
def luhn(s):
    t = 0
    for i, c in enumerate(reversed(s)):
        d = int(c)
        if i % 2: d = d * 2 - 9 if d > 4 else d * 2
        t += d
    return t % 10 == 0
def valid_id(s):
    yy, mm, dd = int(s[:2]), int(s[2:4]), int(s[4:6])
    try: date(2000 + yy, mm, dd)
    except ValueError: return False
    return s[10] in "012" and luhn(s)
def scan_value(v):
    out = []
    for m in D13.finditer(v): out.append(("sa_id_valid" if valid_id(m.group(0)) else "sa_id_13digit_other", m.start()))
    for m in EMAIL.finditer(v):
        if not GOV.search(m.group(0)): out.append(("email_non_gov", m.start()))
    for m in PHONE.finditer(v):
        a = m.group(1)
        if a[0] in "678" and not a.startswith(("80", "86")): out.append(("phone_mobile", m.start()))
        elif not a.startswith(("80", "86")): out.append(("phone_landline", m.start()))
    for m in NAME.finditer(v):
        if STREET.search(v[max(0, m.start() - 200): m.end() + 200]): out.append(("name_near_street_address", m.start()))
    for m in PRIV.finditer(v): out.append(("gazette_private_notice", m.start()))
    return out
FAIL = {"sa_id_valid", "email_non_gov", "phone_mobile", "name_near_street_address", "gazette_private_notice"}
def scan(paths):
    hits = []
    for p in paths:
        t = pq.read_table(p); ids = t.column("id").to_pylist()
        for c in t.column_names:
            if not str(t.schema.field(c).type) in ("string", "large_string"): continue
            for rid, v in zip(ids, t.column(c).to_pylist()):
                if v:
                    for k, o in scan_value(v): hits.append({"file": p.split("/")[-1], "id": rid, "column": c, "kind": k, "offset": o, "level": "fail" if k in FAIL else "warn"})
    return hits
if __name__ == "__main__":
    h = scan(sys.argv[1:]); from collections import Counter
    print(json.dumps({"counts": dict(Counter((x["level"], x["kind"]) for x in h).items()) if False else {f"{a}:{b}": n for (a, b), n in Counter((x["level"], x["kind"]) for x in h).items()}, "hits": h}, indent=1))
