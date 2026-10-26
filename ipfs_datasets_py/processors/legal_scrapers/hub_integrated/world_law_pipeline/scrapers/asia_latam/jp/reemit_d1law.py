#!/usr/bin/env python3
"""Re-emit already-staged *.d1-law.com docs as new .full batches carrying source_policy=robots_unreachable
(original finished files are left untouched; newest file wins in run_loop merge). Writes a _ sidecar manifest."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import sys as _sys; _sys.path.insert(0, (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/pipeline/scrapers/asia_latam/common")); from jsonl_io import open_text, glob_jsonl, locate  # noqa: E402,E702
import json, os, sys, glob, collections, hashlib
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse
sys.path.insert(0, (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/pipeline"))
import schema as S
STAGE = Path((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/staging/asia_latam"))
OUT = STAGE / "JP"
DRY = "--dry" in sys.argv   # read + count only, write nothing
def is_d1(u): return urlparse(u).netloc.lower().endswith("d1-law.com")
by = collections.defaultdict(dict); src = collections.defaultdict(set); mixed = set()
files = glob_jsonl(str(OUT / "*.jsonl")) + glob_jsonl((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/processed/asia_latam/JP/*.jsonl"))
for f in files:
    for line in open_text(f):
        r = json.loads(line)
        pk = S.place_key(r["place_id"], None, "JP")
        if is_d1(r["source_url"]):
            by[pk][r["doc_id"]] = 1 if DRY else r; src[pk].add(os.path.basename(f))
        else:
            mixed.add(pk)
if DRY:
    print(json.dumps({"files": len(files), "gz_files": sum(f.endswith(".gz") for f in files), "d1_places": len(by),
                      "d1_docs": sum(len(v) for v in by.values()), "mixed_places": len(mixed)}))
    sys.exit(0)
ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%MZ")
man = []
for pk, docs in sorted(by.items()):
    if pk in mixed:
        print("WARNING place has non-d1-law docs too, not using .full:", pk)
    batch = ("full." if pk not in mixed else "") + f"d1law-robots-unreachable-{ts}"
    final = OUT / f"{pk}.{batch}.jsonl"
    tmp = final.with_name("." + final.name + ".tmp.jsonl")
    with tmp.open("w", encoding="utf-8") as fh:
        for r in docs.values():
            r = dict(r, source_policy="robots_unreachable", source_policy_note="*.d1-law.com robots.txt unreachable; RFC 9309 disallow-all; crawl stopped 2026-10-10 15:34 PT")
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
        fh.flush(); os.fsync(fh.fileno())
    v = S.validate_file(tmp, expect_place_key=pk)
    assert v["ok"], v["errors"][:3]
    os.rename(tmp, final)
    man.append({"place_key": pk, "place_id": next(iter(docs.values()))["place_id"], "file": str(final), "docs": len(docs),
                "doc_ids_sha256": hashlib.sha256("\n".join(sorted(docs)).encode()).hexdigest(),
                "supersedes_files": sorted(src[pk]), "source_policy": "robots_unreachable", "written_at": ts})
mp = STAGE / "_d1law_robots_unreachable_manifest.jsonl"
with open(mp, "a", encoding="utf-8") as fh:
    for m in man: fh.write(json.dumps(m, ensure_ascii=False) + "\n")
print("places", len(man), "docs", sum(m["docs"] for m in man), "manifest", mp)
for m in man: print(m["file"], m["docs"])
