#!/usr/bin/env python3
"""Emit instruments from repo collectors run under staging/national/_archive_work/<CC>_repo/
(collect_eg.py / collect_ir.py with https Wayback patches) as staged docs with an 'archive' batch
suffix + archive provenance. Skips docs whose source URL is already on HF and garbage text.
Usage: emit_repo_archive.py CC [--loop SECONDS]"""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import json, re, sys, time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/pipeline"))
sys.path.insert(0, (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/pipeline/scrapers/national"))
from archive import StagedWriter, canonical_url, is_stale  # noqa: E402
from archive.core import ts_to_iso  # noqa: E402
import emit_staged as E  # noqa: E402  (reuse convert(); its WORK paths are not used here)

STAGE = Path((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/staging/national"))
WB = re.compile(r"web\.archive\.org/web/(\d{14})(?:id_|if_)?/(.+)$")


def provenance(r):
    md = r.get("metadata") or {}
    blob = json.dumps(md, ensure_ascii=False)
    m = WB.search(r.get("source_url") or "") or WB.search(blob)
    if m:
        ts, orig = m.group(1), m.group(2)
        return {"archive_source": "wayback", "archive_crawl_id": "wayback", "archive_timestamp": ts_to_iso(ts),
                "archive_url": f"https://web.archive.org/web/{ts}id_/{orig}", "original_url": orig,
                "content_complete": True, "possibly_stale": is_stale(ts)}
    meth = str((md.get("retrieval") or {}).get("method") or md.get("fetch_method") or "")
    if "wayback" in meth or "archive" in meth:
        return {"archive_source": "wayback", "archive_crawl_id": "wayback", "archive_timestamp": None,
                "archive_url": None, "original_url": r.get("source_url"), "content_complete": True,
                "possibly_stale": None}
    return {"archive_source": "live", "archive_crawl_id": None, "archive_timestamp": None, "archive_url": None,
            "original_url": r.get("source_url"), "content_complete": True, "possibly_stale": False}


def garbage(text):
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    if len(text) < 200 or not lines:
        return True
    return len(set(lines)) / len(lines) < 0.2


def emit(cc):
    root = STAGE / "_archive_work" / f"{cc}_repo"
    done_f = root / "_archive_emitted.txt"
    done = set(done_f.read_text().split()) if done_f.exists() else set()
    hf = set()
    hp = STAGE / "_archive_work" / "_hf_ids" / f"{cc}.jsonl"
    if hp.exists():
        for l in hp.open():
            u = json.loads(l).get("source_url")
            if u:
                hf.add(canonical_url(u))
    cat = E.CAT.get(cc, {"display_name": cc, "language": "und", "slug": cc.lower()})
    writers, newly, skipped = {}, [], {}
    for p in sorted(root.rglob("*.json")):
        if p.parent.name != "instruments" or p.stem in done:
            continue
        try:
            r = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        r.setdefault("id", p.stem)
        pid, rec, why = E.convert(r, cc, cat)
        prov = provenance(r)
        if rec is None or garbage(rec.get("text", "")):
            why = why or "garbage_text"
        elif canonical_url(prov.get("original_url") or rec["source_url"]) in hf:
            rec, why = None, "already_on_hf"
        if rec is None or why:
            skipped[why] = skipped.get(why, 0) + 1
            newly.append(p.stem)
            continue
        if prov.get("original_url"):
            rec["source_url"] = prov["original_url"]
        rec.update(prov)
        rec["extra_metadata"] = {"archive": dict(prov)}
        w = writers.setdefault(pid, StagedWriter(STAGE, cc, pid, batch_prefix="archiverepo", chunk=500))
        err = w.add(rec)
        if err:
            skipped["invalid"] = skipped.get("invalid", 0) + 1
        newly.append(p.stem)
    n = 0
    for w in writers.values():
        w.flush()
        n += sum(1 for _ in w.written)
    if newly:
        with done_f.open("a") as f:
            f.write("\n".join(newly) + "\n")
    print(datetime.now().strftime("%F %T"), cc, "emitted files", n, "skipped", skipped, flush=True)


if __name__ == "__main__":
    cc = sys.argv[1]
    if "--loop" in sys.argv:
        iv = int(sys.argv[sys.argv.index("--loop") + 1])
        while True:
            emit(cc)
            time.sleep(iv)
    emit(cc)
