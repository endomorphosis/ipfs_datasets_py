#!/usr/bin/env python3
"""OECS/Caribbean Cap-style article densify on existing instruments (no re-fetch).

Official Cap/Section split inspired by VC densify + GM/NA commonwealth body regex.
Skips gazette shells / speeches. Writes instruments in place; stage separately.
"""
from __future__ import annotations
import json, os, re, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import ROOT, atomic_write
from world_lib import split_custom

# Cap / Commonwealth body: Section/Article/Schedule/Part/Chapter OR numbered Cap
# short headings OR legal openers. Avoid bare [A-Z] (speech false positives).
ART = re.compile(
    r"(?im)^\s*((?:Section|SECTION|Article|Art\.?|SCHEDULE|Schedule|PART|Part|CHAPTER|Chapter)\s+[0-9IVXLC]+[A-Za-z]?\b|"
    r"s\.\s*[0-9]+[A-Za-z]?\b|"
    r"\d+[A-Za-z]?\.\s+[A-Z][A-Za-z0-9'()\-/ ,\"]{0,55}\.?\s*$|"
    r"\d+[A-Za-z]?\.\s+(?:This |In |These |The |For |Any |Every |Where |If |Subject |"
    r"No |Nothing |Notwithstanding |On |It |Whenever |Unless |Except |"
    r"\([0-9]|[\"'])"
    r")"
)
ART_NARROW = re.compile(
    r"(?im)^\s*((?:Section|Article|Art\.?|SCHEDULE|Schedule)\s+[0-9]+[A-Za-z]?|"
    r"s\.\s*[0-9]+[A-Za-z]?)\b"
)
NONACT = re.compile(
    r"(?i)(?:budget\s+speech|throne\s+speech|policy\s+statement|"
    r"economic and financial policies|we must |minister of finance|"
    r"mr\.?\s+speaker|house of assembly|estimates of revenue)"
)
ACTISH = re.compile(
    r"(?i)(?:AN ACT\b|BE IT ENACTED|ARRANGEMENT OF|"
    r"This Act (?:may be cited|is called|shall be called)|"
    r"Short title\.|I assent|STATUTORY INSTRUMENTS?|"
    r"CONSTITUTION OF|Criminal Code|Labour Code|"
    r"REGULATIONS?\s+made under|ORDER\s+made under|"
    r"CHAPTER\s+\d+|Cap\.\s*\d+)"
)
BROAD = {
    "ACT", "CONSTITUTION", "SRO", "CAP", "SI", "PRINCIPAL", "AMENDING",
    "SUBORDINATE", "CODE", "CHAPTER",
}
NARROW_FORCE = {"GAZETTE", "EXTRAORDINARY"}
TAG = "oecs_cap_section_v1"


def pick_re(cat: str, text: str):
    c = (cat or "").strip()
    if c in NARROW_FORCE or (c.startswith("20") and "S.I" in c) or "Press Office" in c:
        return ART_NARROW, "narrow"
    if NONACT.search((text or "")[:3000]):
        return ART_NARROW, "nonact"
    if "sustant" in c.lower() or "substant" in c.lower() or c.upper() in {x.upper() for x in BROAD}:
        return ART, "broad"
    if ACTISH.search(text or ""):
        return ART, "actish"
    return ART_NARROW, "default_narrow"


def reprocess_cc(cc: str) -> dict:
    root = ROOT / cc / "instruments"
    if not root.is_dir():
        return {"cc": cc, "error": "no instruments"}
    old_sum = new_sum = changed = 0
    for path in sorted(root.glob("*.json")):
        try:
            rec = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        text = rec.get("text") or ""
        if len(text) < 80:
            continue
        rid = rec.get("id") or path.stem
        cat = ((rec.get("metadata") or {}).get("category") or "")
        use_re, mode = pick_re(cat, text)
        docs = split_custom(text, rid, rec.get("source_url") or "", rec.get("date"), use_re)
        old = int(rec.get("article_count") or 0)
        n = len(docs)
        if n < old and old >= 2 and n < 2:
            continue
        if n == old and old > 0 and (rec.get("metadata") or {}).get("article_re") == TAG:
            old_sum += old
            new_sum += n
            continue
        if n == old and old > 0:
            # still rewrite tag if improved path same count? skip
            old_sum += old
            new_sum += n
            continue
        rec["documents"] = docs
        rec["article_count"] = n
        rec["article_extraction_status"] = (
            "ok" if n >= 2 else ("missing" if not n else "partial")
        )
        meta = rec.get("metadata") or {}
        meta["article_re"] = TAG
        meta["article_re_mode"] = mode
        rec["metadata"] = meta
        body = json.dumps(rec, ensure_ascii=False, indent=2) + "\n"
        atomic_write(path, body)
        changed += 1
        old_sum += old
        new_sum += n
    # recount fully
    arts = 0
    laws = 0
    for path in root.glob("*.json"):
        try:
            rec = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        laws += 1
        arts += int(rec.get("article_count") or 0)
    return {"cc": cc, "changed": changed, "laws": laws, "articles": arts}


def main():
    ccs = sys.argv[1:] or ["ag", "bs", "bb", "bz", "dm", "lc", "gd"]
    for cc in ccs:
        r = reprocess_cc(cc)
        print(json.dumps(r), flush=True)


if __name__ == "__main__":
    main()
