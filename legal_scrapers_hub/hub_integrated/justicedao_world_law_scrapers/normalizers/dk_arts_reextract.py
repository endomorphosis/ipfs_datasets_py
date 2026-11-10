#!/usr/bin/env python3
"""DK article deepen: re-split Danish § N. paragraphs on existing instruments.

Hub tip floor (soft never-thin): laws≥33328 arts≥0 (sha 5f4dc273e1c0).
CoS: prioritize arts deepen before any Hub republish even though tip arts=0.
Does NOT Hub-publish. Safe to run alongside collect_dk.py (atomic rewrites).
"""
from __future__ import annotations
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))

import json
import os
import re
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

INST = _CORPORA / "dk" / "instruments"
LOG = _CORPORA / "_wave_logs" / "dk_arts_expand.md"
RUNLOG = _CORPORA / "dk" / "logs" / "arts_reextract.out"
FLOOR_LAWS = 33328
FLOOR_ARTS = 0  # tip is 0; still deepen before publish
PT = timezone(timedelta(hours=-7))

# Article starts: "§ 1. Text..." — exclude cross-refs "§ 4, stk. 2" and "§ 7. Stk."
ART_RE = re.compile(r"§\s*(\d+[a-z]?)\.\s+(?!Stk\.?)(?=[A-ZÆØÅ])")


def now_pt() -> str:
    return datetime.now(PT).strftime("%Y-%m-%d %H:%M:%S PT")


def now_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def log(msg: str) -> None:
    line = f"[{now_pt()}] {msg}"
    print(line, flush=True)
    RUNLOG.parent.mkdir(parents=True, exist_ok=True)
    with RUNLOG.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def split_dk(text: str, law_id: str, source_url: str, date: str | None) -> list[dict]:
    if not text or len(text) < 40:
        return []
    t = text.replace("\xa0", " ")
    matches = list(ART_RE.finditer(t))
    if len(matches) < 2:
        return []
    docs = []
    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(t)
        chunk = t[start:end].strip()
        num = f"§ {m.group(1)}"
        aid = re.sub(r"[^a-z0-9]+", "-", num.lower()).strip("-")
        heading = chunk.split("\n", 1)[0][:200]
        docs.append({
            "id": f"{law_id}-{aid}"[:180],
            "title": heading,
            "text": chunk,
            "date_filed": date,
            "document_number": num,
            "source_url": source_url,
            "record_type": "article",
            "article_number": num,
            "law_identifier": law_id,
            "metadata": {"text_extraction": {"source": "official", "backend": "dk_arts_reextract"}},
        })
        if len(docs) >= 4000:
            break
    return docs


def atomic_write(path: Path, body: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(body, encoding="utf-8")
    os.replace(tmp, path)


def process_one(path: Path, force: bool = False) -> tuple[str, int]:
    try:
        rec = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return f"err:{exc}", 0
    if not force and rec.get("article_extraction_status") == "ok" and (rec.get("article_count") or 0) >= 2:
        return "skip", int(rec.get("article_count") or 0)
    text = rec.get("text") or ""
    docs = split_dk(text, rec.get("id") or path.stem, rec.get("source_url") or "", rec.get("date"))
    if len(docs) < 2:
        return "thin", 0
    rec["documents"] = docs
    rec["article_count"] = len(docs)
    rec["article_extraction_status"] = "ok"
    meta = rec.get("metadata") if isinstance(rec.get("metadata"), dict) else {}
    meta["arts_reextract"] = {"at": now_utc(), "backend": "dk_§N"}
    rec["metadata"] = meta
    atomic_write(path, json.dumps(rec, ensure_ascii=False, indent=2) + "\n")
    return "ok", len(docs)


def corpus_stats() -> dict:
    n = ok = missing = arts = 0
    for p in INST.glob("*.json"):
        n += 1
        try:
            rec = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        ac = int(rec.get("article_count") or len(rec.get("documents") or []) or 0)
        arts += ac
        if rec.get("article_extraction_status") == "ok" and ac >= 2:
            ok += 1
        else:
            missing += 1
    return {"laws": n, "ok": ok, "missing": missing, "arts": arts}


def write_progress(extra: dict) -> None:
    st = corpus_stats()
    lines = [
        "# DK arts expand",
        "",
        f"- updated_at: {now_pt()} / {now_utc()}",
        f"- hub_tip_floor: laws≥{FLOOR_LAWS} arts≥{FLOOR_ARTS} (sha 5f4dc273e1c0)",
        f"- CoS: deepen arts before Hub republish (even though tip arts=0)",
        f"- local_laws: {st['laws']}",
        f"- local_arts: {st['arts']}",
        f"- extraction_ok: {st['ok']}",
        f"- still_missing: {st['missing']}",
        f"- never_thin_laws: {'YES' if st['laws'] >= FLOOR_LAWS else 'NO — still thin vs tip'}",
        f"- publish: HOLD until CoS ping + laws≥tip + meaningful arts deepen",
        "",
        "## Extra",
        "",
        "```json",
        json.dumps(extra, indent=2),
        "```",
        "",
    ]
    LOG.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    loops = int(os.environ.get("DK_ARTS_LOOPS", "3"))
    sleep_s = int(os.environ.get("DK_ARTS_SLEEP", "90"))
    log(f"START dk_arts_reextract loops={loops} sleep={sleep_s}")
    write_progress({"phase": "start"})
    for loop in range(1, loops + 1):
        ok = thin = skip = err = arts_added = 0
        paths = sorted(INST.glob("*.json"))
        log(f"loop {loop}/{loops} instruments={len(paths)}")
        for p in paths:
            st, n = process_one(p)
            if st == "ok":
                ok += 1
                arts_added += n
            elif st == "skip":
                skip += 1
            elif st == "thin":
                thin += 1
            else:
                err += 1
        st = corpus_stats()
        log(f"loop done ok={ok} skip={skip} thin={thin} err={err} arts_added={arts_added} corpus={st}")
        write_progress({"loop": loop, "ok": ok, "skip": skip, "thin": thin, "err": err, "arts_added": arts_added, "corpus": st})
        if loop < loops:
            time.sleep(sleep_s)
    log("DONE")


if __name__ == "__main__":
    main()
