#!/usr/bin/env python3
"""SB Cap/Section densify on existing instruments (offline, no re-fetch / no WARC).

Solomon Islands AGC Acts (attorneygenerals.gov.sb) — CAP./Section commonwealth reprints with ``1. Short Title``
bodies after BE IT ENACTED / ANALYSIS TOC. LEAN Cap: write only when article
count rises. Official pack text only.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import ROOT, INDEX_FIELDS, atomic_write
from world_lib import split_custom

ART = re.compile(
    r"(?im)^\s*((?:Article|Art\.?|Section|Sec\.?|SECTION|SCHEDULE|Schedule|PART|Part|CHAPTER|Chapter)\s+[0-9IVXLC]+[A-Za-z]?\b|"
    r"\d+[A-Za-z]?\.\s*[-–—~]?\s*[A-Z]|"
    r"\d+[A-Za-z]?\.\s+[A-Z][A-Za-z0-9'’()\-/,& ]{1,80}\.?\s*$|"
    r"\d+[A-Za-z]?\.\s+(?:This Act|In this Act|These |Subject to|Notwithstanding|Except as|Unless )\b"
    r")"
)
ART_STRICT = re.compile(
    r"(?im)^\s*((?:Article|Art\.?|Section|Sec\.?|SECTION)\s+[0-9]+[A-Za-z]?\b|"
    r"\d+[A-Za-z]?\.\s*[-–—~]\s*[A-Z]|"
    r"\d+[A-Za-z]?\.\s+(?:Short Title|Short title|Interpretation|Definitions|Citation|"
    r"This Act|In this Act|Application|Commencement)\b)"
)
TAG = "sb_cap_section_v1"


def prefer_enacting_body(text: str) -> str:
    if not text:
        return text
    m = re.search(r"(?is)BE IT ENACTED.{0,500}?as follows\s*:", text)
    if m and m.end() < len(text) - 120:
        rest = text[m.end() :]
        if len(rest) > len(text) * 0.2:
            return rest
    m = re.search(r"(?is)BE IT ENACTED[^\n]*\n", text)
    if m and m.end() < len(text) - 200:
        rest = text[m.end() :]
        arr = re.search(r"(?i)\bANALYSIS\b|ARRANGEMENT OF", rest[:2000])
        if not arr and len(rest) > len(text) * 0.2:
            return rest
        text = rest
    ones = list(re.finditer(r"(?im)^\s*1\.\s+Short Title\b", text))
    if len(ones) >= 2:
        return text[ones[-1].start() :]
    if len(ones) == 1 and ones[0].start() > 150:
        return text[ones[0].start() :]
    return text


def pick_docs(text: str, rid: str, url: str, date):
    body = prefer_enacting_body(text)
    d_lean = split_custom(body, rid, url, date, ART)
    d_strict = split_custom(body, rid, url, date, ART_STRICT)
    # if TOC skip was too aggressive, also try full text
    if len(body) < len(text) * 0.35:
        d_lean_f = split_custom(text, rid, url, date, ART)
        d_strict_f = split_custom(text, rid, url, date, ART_STRICT)
        if len(d_lean_f) >= len(d_lean):
            d_lean = d_lean_f
        if len(d_strict_f) >= len(d_strict):
            d_strict = d_strict_f
    if len(d_lean) >= len(d_strict):
        return d_lean, "lean"
    return d_strict, "strict"


def rebuild_index() -> tuple[int, int]:
    inst = ROOT / "sb" / "instruments"
    index = ROOT / "sb" / "index.jsonl"
    rows = []
    arts = 0
    for p in sorted(inst.glob("*.json")):
        try:
            rec = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        n = int(rec.get("article_count") or len(rec.get("documents") or []) or 0)
        arts += n
        line = {k: rec.get(k) for k in INDEX_FIELDS if k not in ("path", "bytes", "article_count")}
        line["path"] = f"instruments/{p.name}"
        line["article_count"] = n
        line["bytes"] = p.stat().st_size
        line["id"] = rec.get("id") or p.stem
        rows.append(line)
    atomic_write(index, "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
    return len(rows), arts


def main():
    dry = "--dry-run" in sys.argv
    root = ROOT / "sb" / "instruments"
    old_sum = new_sum = changed = 0
    modes: dict[str, int] = {}
    for path in sorted(root.glob("*.json")):
        try:
            rec = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        text = rec.get("text") or ""
        old = int(rec.get("article_count") or len(rec.get("documents") or []) or 0)
        if len(text) < 80:
            old_sum += old
            new_sum += old
            continue
        rid = rec.get("id") or path.stem
        url = rec.get("source_url") or ""
        date = rec.get("date")
        docs, mode = pick_docs(text, rid, url, date)
        new = len(docs)
        modes[mode] = modes.get(mode, 0) + 1
        if new <= old:
            old_sum += old
            new_sum += old
            continue
        if new < 2 and old >= new:
            old_sum += old
            new_sum += old
            continue
        if dry:
            changed += 1
            old_sum += old
            new_sum += new
            continue
        rec["documents"] = docs
        rec["article_count"] = new
        rec["article_extraction_status"] = "ok" if new >= 2 else ("missing" if not new else "partial")
        meta = rec.get("metadata") or {}
        meta["article_re"] = TAG
        meta["article_re_mode"] = mode
        meta["article_reprocess"] = "collect_sb.py-cap-sections"
        meta["article_split"] = "commonwealth-cap"
        rec["metadata"] = meta
        atomic_write(path, json.dumps(rec, ensure_ascii=False, indent=2) + "\n")
        changed += 1
        old_sum += old
        new_sum += new
    laws, arts = rebuild_index() if not dry else (0, 0)
    if not dry:
        # recount from files for report honesty
        laws, arts = rebuild_index()
    report = {
        "cc": "sb",
        "tag": TAG,
        "dry_run": dry,
        "changed": changed,
        "old_articles_sum": old_sum,
        "new_articles_sum": new_sum,
        "delta": new_sum - old_sum,
        "laws": laws,
        "articles": arts,
        "modes": modes,
    }
    out = ROOT / "sb" / "raw" / "densify_articles_report.json"
    if not dry:
        out.parent.mkdir(parents=True, exist_ok=True)
        atomic_write(out, json.dumps(report, indent=2) + "\n")
    print(json.dumps(report), flush=True)


if __name__ == "__main__":
    main()
