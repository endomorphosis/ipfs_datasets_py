#!/usr/bin/env python3
"""Coordinator update 2026-10-10 15:49 PT: ops-jg.d1-law.com robots.txt is a real 404 (RFC 9309 allow).
Re-emit the ops-jg places from the d1-law robots_unreachable manifest as a NEWER .full batch WITHOUT
source_policy=robots_unreachable (set robots_404_allow_rfc9309). Finished files untouched; manifest appended."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import sys as _sys; _sys.path.insert(0, (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/pipeline/scrapers/asia_latam/common")); from jsonl_io import open_text, glob_jsonl, locate  # noqa: E402,E702
import json, os, sys, hashlib
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse
sys.path.insert(0, (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/pipeline"))
import schema as S
STAGE = Path((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/staging/asia_latam")); OUT = STAGE / "JP"
MP = STAGE / "_d1law_robots_unreachable_manifest.jsonl"
DRY = "--dry" in sys.argv   # read + count only, write nothing
ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%MZ")
entries = [json.loads(l) for l in open(MP) if l.strip()]
superseded = {e["place_key"] for e in entries if e.get("action") == "superseded"}
out = []
for e in entries:
    if e.get("action") or e["place_key"] in superseded:
        continue
    src = locate(e["file"])                      # may have been moved to processed/ and gzipped
    if not src:
        print("missing (not in staging/processed):", e["file"]); continue
    recs = [json.loads(l) for l in open_text(src)]
    if not all(urlparse(r["source_url"]).netloc.lower() == "ops-jg.d1-law.com" for r in recs):
        continue
    pk = e["place_key"]
    if DRY:
        print("dry", pk, len(recs), os.path.basename(src)); continue
    final = OUT / f"{pk}.full.d1ops-robots404-allow-{ts}.jsonl"
    tmp = final.with_name("." + final.name + ".tmp.jsonl")
    with tmp.open("w", encoding="utf-8") as fh:
        for r in recs:
            r = {k: v for k, v in r.items() if k not in ("source_policy", "source_policy_note")}
            r["source_policy"] = "robots_404_allow_rfc9309"
            r["source_policy_note"] = "ops-jg.d1-law.com /robots.txt returns HTTP 404 -> allow (RFC 9309); re-enabled by coordinator 2026-10-10 15:49 PT"
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
        fh.flush(); os.fsync(fh.fileno())
    v = S.validate_file(tmp, expect_place_key=pk)
    assert v["ok"], v["errors"][:3]
    os.rename(tmp, final)
    out.append({"action": "superseded", "place_key": pk, "place_id": e["place_id"], "superseded_file": e["file"],
                "superseded_by": str(final), "docs": len(recs),
                "doc_ids_sha256": hashlib.sha256("\n".join(sorted(r["doc_id"] for r in recs)).encode()).hexdigest(),
                "reason": "source host ops-jg.d1-law.com serves robots.txt HTTP 404 = allow under RFC 9309; "
                          "robots_unreachable flag was wrong for this host; coordinator re-enabled it 2026-10-10 15:49 PT",
                "new_source_policy": "robots_404_allow_rfc9309", "written_at": ts})
with open(MP, "a", encoding="utf-8") as fh:
    for m in out: fh.write(json.dumps(m, ensure_ascii=False) + "\n")
print("re-emitted", len(out), "places", sum(m["docs"] for m in out), "docs")
for m in out: print(m["superseded_by"], m["docs"])
