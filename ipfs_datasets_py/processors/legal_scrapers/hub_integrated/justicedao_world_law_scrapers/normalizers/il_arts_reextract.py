#!/usr/bin/env python3
"""IL article re-extraction from existing Reshumot/OData instrument text.

Hub tip 0117f088f1f2 is 944 laws / 0 arts. Local instruments often have full
text but article_extraction_status=missing because RTL PDF extract yields
leading ".N" sections rather than line-leading סעיף. This pass re-splits only
— no LawHome/WAF, no Hub publish (parent/CoS gate articles>0 first).
"""
from __future__ import annotations
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))

import json
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, "/workspace/legal-scrapers-kit/scrapers")
from collect_knesset_laws import split_he  # noqa: E402
from common import atomic_write  # noqa: E402

PT = timezone(timedelta(hours=-7))
INST = _CORPORA / "il" / "instruments"
LOG = _CORPORA / "_wave_logs" / "il_arts_expand.md"
RUNLOG = _CORPORA / "il" / "logs" / "arts_reextract.out"


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


def write_progress(laws: int, with_docs: int, arts: int, updated: int, skipped: int) -> None:
    body = [
        "# IL arts expand (Reshumot/OData text re-split)",
        "",
        f"- updated_at: {now_pt()} / {now_utc()}",
        "- method: split_he on existing instrument text only (no LawHome/WAF)",
        "- Hub: NO publish until articles>0 and CoS OK (tip was 944/0)",
        f"- instruments: {laws}",
        f"- with_documents: {with_docs}",
        f"- article_rows: {arts}",
        f"- this_pass_updated: {updated}",
        f"- this_pass_skipped: {skipped}",
        "",
    ]
    LOG.parent.mkdir(parents=True, exist_ok=True)
    LOG.write_text("\n".join(body), encoding="utf-8")


def main() -> None:
    paths = sorted(INST.glob("*.json"))
    log(f"start reextract n={len(paths)}")
    updated = skipped = arts_before = arts_after = with_docs = 0
    for i, p in enumerate(paths, 1):
        try:
            rec = json.loads(p.read_text(encoding="utf-8"))
        except Exception as exc:
            log(f"read fail {p.name}: {exc}")
            skipped += 1
            continue
        old = rec.get("documents") or []
        arts_before += len(old)
        text = rec.get("text") or ""
        if len(text) < 80:
            skipped += 1
            continue
        if len(old) >= 2 and rec.get("article_extraction_status") == "ok":
            with_docs += 1
            arts_after += len(old)
            skipped += 1
            continue
        docs = split_he(text, rec.get("id") or p.stem, rec.get("source_url"), rec.get("date"))
        if len(docs) < 2:
            skipped += 1
            arts_after += len(old)
            continue
        rec["documents"] = docs
        rec["article_count"] = len(docs)
        rec["article_extraction_status"] = "ok"
        meta = rec.get("metadata") if isinstance(rec.get("metadata"), dict) else {}
        te = dict(meta.get("text_extraction") or {})
        te["article_split"] = "il_arts_reextract"
        meta["text_extraction"] = te
        rec["metadata"] = meta
        atomic_write(p, json.dumps(rec, ensure_ascii=False, indent=2) + "\n")
        updated += 1
        with_docs += 1
        arts_after += len(docs)
        if updated % 50 == 0 or i % 100 == 0:
            log(f"progress {i}/{len(paths)} updated={updated} arts_after~={arts_after}")
            write_progress(len(paths), with_docs, arts_after, updated, skipped)
    write_progress(len(paths), with_docs, arts_after, updated, skipped)
    log(
        f"done laws={len(paths)} updated={updated} skipped={skipped} "
        f"arts_before={arts_before} arts_after={arts_after} with_docs={with_docs}"
    )


if __name__ == "__main__":
    main()
