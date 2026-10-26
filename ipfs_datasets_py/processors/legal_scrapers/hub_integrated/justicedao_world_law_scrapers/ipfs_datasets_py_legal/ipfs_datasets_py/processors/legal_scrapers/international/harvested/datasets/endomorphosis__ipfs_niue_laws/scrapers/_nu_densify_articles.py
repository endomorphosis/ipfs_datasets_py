#!/usr/bin/env python3
"""NU Cap/Section densify on existing instruments (offline, no re-fetch / no WARC).

Government of Niue (gov.nu) Acts, consolidations, and multi-Act law volumes.
Skip Assembly order papers / pure gazette shells. LEAN Cap: write only when
article count rises. Official pack text only.
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
    r"s\.\s*[0-9]+[A-Za-z]?\b|"
    r"\d+[A-Za-z]?\.\s*[-–—~]?\s*[A-Z]|"
    r"\d+[A-Za-z]?\.\s+[A-Z][A-Za-z0-9'’()\-/,& ]{1,80}\.?\s*$|"
    r"\d+[A-Za-z]?\.\s+(?:This Act|In this Act|These |Subject to|Notwithstanding|Except as|Unless |For the purposes)\b"
    r")"
)
ART_VOL = re.compile(
    r"(?im)^\s*((?:Article|Art\.?|Section|Sec\.?|SECTION|SCHEDULE|Schedule|PART|Part|CHAPTER|Chapter)\s+[0-9IVXLC]+[A-Za-z]?\b|"
    r"(?:AN ACT\b)|"
    r"\d+[A-Za-z]?\.\s*[-–—~]?\s*[A-Z]|"
    r"\d+[A-Za-z]?\.\s+[A-Z][A-Za-z0-9'’()\-/,& ]{1,80}\.?\s*$)"
)
TAG = "nu_cap_section_v1"
SHELL = re.compile(r"(?i)order.?paper|tohi fono|opening prayer")
ACTISH_TITLE = re.compile(r"(?i)\bact\b|consolidat|ordinance|regulation|laws.?vol|legislation.?supplement")
ACTISH_BODY = re.compile(r"(?i)BE IT ENACTED|Short title|AN ACT\b|This Act may be cited|ARRANGEMENT OF")


def prefer_enacting_body(text: str) -> str:
    if not text:
        return text
    m = re.search(r"(?is)BE IT ENACTED.{0,600}?as follows\s*:", text)
    if m and m.end() < len(text) - 120:
        rest = text[m.end() :]
        if len(rest) > len(text) * 0.15:
            return rest
    m = re.search(r"(?is)BE IT ENACTED[^\n]*\n", text)
    if m and m.end() < len(text) - 200:
        return text[m.end() :]
    ones = list(re.finditer(r"(?im)^\s*1\.\s+Short [Tt]itle\b", text))
    if len(ones) >= 2:
        return text[ones[-1].start() :]
    if len(ones) == 1 and ones[0].start() > 120:
        return text[ones[0].start() :]
    return text


def eligible(rec: dict, name: str, text: str) -> tuple[bool, bool]:
    """Return (eligible, is_volume)."""
    kind = ((rec.get("metadata") or {}).get("nu_kind") or "")
    title = rec.get("title") or name
    blob = f"{name}|{title}|{kind}|{text[:2500]}"
    if SHELL.search(blob) or len(text) < 100:
        return False, False
    is_volume = bool(re.search(r"(?i)niue_laws_vol|legislation.?supplement|laws vol", blob))
    is_act = kind in ("act", "consolidation") or bool(ACTISH_TITLE.search(title))
    if kind == "gazette" and not is_volume and not ACTISH_BODY.search(text[:5000]):
        return False, False
    if not (is_act or is_volume or ACTISH_BODY.search(text[:5000])):
        return False, False
    return True, is_volume


def pick_docs(text: str, rid: str, url: str, date, *, is_volume: bool):
    if is_volume:
        d_vol = split_custom(text, rid, url, date, ART_VOL)
        d_art = split_custom(text, rid, url, date, ART)
        if len(d_art) >= len(d_vol):
            return d_art, "vol_art"
        return d_vol, "vol"
    body = prefer_enacting_body(text)
    d_lean = split_custom(body, rid, url, date, ART)
    if len(body) < len(text) * 0.35:
        d_full = split_custom(text, rid, url, date, ART)
        if len(d_full) >= len(d_lean):
            return d_full, "full"
    return d_lean, "lean"


def rebuild_index() -> tuple[int, int]:
    inst = ROOT / "nu" / "instruments"
    index = ROOT / "nu" / "index.jsonl"
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
    root = ROOT / "nu" / "instruments"
    old_sum = new_sum = changed = skipped = 0
    modes: dict[str, int] = {}
    for path in sorted(root.glob("*.json")):
        try:
            rec = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        text = rec.get("text") or ""
        old = int(rec.get("article_count") or len(rec.get("documents") or []) or 0)
        ok, is_volume = eligible(rec, path.name, text)
        if not ok:
            skipped += 1
            old_sum += old
            new_sum += old
            continue
        rid = rec.get("id") or path.stem
        docs, mode = pick_docs(text, rid, rec.get("source_url") or "", rec.get("date"), is_volume=is_volume)
        new = len(docs)
        modes[mode] = modes.get(mode, 0) + 1
        if new <= old or (new < 2 and old >= new):
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
        meta["article_reprocess"] = "collect_nu.py-cap-sections"
        meta["article_split"] = "commonwealth-cap"
        rec["metadata"] = meta
        atomic_write(path, json.dumps(rec, ensure_ascii=False, indent=2) + "\n")
        changed += 1
        old_sum += old
        new_sum += new
    laws = arts = 0
    if not dry:
        laws, arts = rebuild_index()
    report = {
        "cc": "nu",
        "tag": TAG,
        "dry_run": dry,
        "changed": changed,
        "skipped_shells": skipped,
        "old_articles_sum": old_sum,
        "new_articles_sum": new_sum,
        "delta": new_sum - old_sum,
        "laws": laws,
        "articles": arts,
        "modes": modes,
    }
    if not dry:
        out = ROOT / "nu" / "raw" / "densify_articles_report.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        atomic_write(out, json.dumps(report, indent=2) + "\n")
    print(json.dumps(report), flush=True)


if __name__ == "__main__":
    main()
