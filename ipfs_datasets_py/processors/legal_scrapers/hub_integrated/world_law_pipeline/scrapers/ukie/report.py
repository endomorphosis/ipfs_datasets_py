#!/usr/bin/env python3
"""Validate every ukie file (staging + processed) with schema.validate_file and summarise counts."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import collections, glob, json, sys
sys.path.insert(0, (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/pipeline"))
from schema import validate_file  # noqa: E402
files = sorted(glob.glob((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/staging/ukie/[A-Z][A-Z]/*.jsonl")) +
               glob.glob((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/processed/ukie/[A-Z][A-Z]/*.jsonl*")))
bad, rows, places, src, full = [], 0, collections.defaultdict(set), collections.Counter(), {}
for f in files:
    if f.endswith(".gz"):
        continue
    res = validate_file(f, expect_place_key=f.rsplit("/", 1)[1].split(".")[0])
    if not res["ok"]:
        bad.append((f, res["errors"][:2]))
    for l in open(f):
        r = json.loads(l); rows += 1
        places[r["country_code"]].add(r["place_id"])
        src[(r["source_platform"], r.get("local_instrument_kind") or r.get("act_kind"), bool(r.get("archive_source")))] += 1
ocr = sum(1 for _ in open((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/staging/ukie/_state/needs_ocr/notext_urls.jsonl")))
print(json.dumps({"files": len(files), "invalid_files": bad, "rows_all_batches": rows,
                  "places": {k: len(v) for k, v in places.items()},
                  "by_source": {" / ".join(map(str, k)): v for k, v in src.items()}, "needs_ocr_lines": ocr}, indent=1))

# effective current set (SCHEMA §1.4: newest batch wins per doc_id; a .full batch replaces the place)
import re, gzip
_op = lambda f: gzip.open(f, "rt") if f.endswith(".gz") else open(f)
by_place = collections.defaultdict(list)
for f in files:
    n = f.rsplit("/", 1)[1]
    by_place[(f.split("/")[-2], n.split(".")[0])].append((re.search(r"\d{8}T\d{6}Z", n).group(0), n, f))
eff = collections.Counter(); effp = collections.defaultdict(set); kinds = collections.Counter()
over = {(q["place_key"], q["doc_id"]) for o in sorted(glob.glob(
    (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/staging/ukie/_state/proposed_doc_overrides_*.json"))) for q in json.load(open(o))["quarantine"]}
for (cc, pk), lst in by_place.items():
    docs = {}
    for ts, n, f in sorted(lst):
        if ".full." in n:
            docs = {}
        for l in _op(f):
            r = json.loads(l); docs[r["doc_id"]] = r
    for d, r in docs.items():
        if (pk, d) in over:
            continue
        eff[cc] += 1; effp[cc].add(pk)
        kinds[(r["source_platform"], r.get("local_instrument_kind") or r.get("act_kind"))] += 1
ocr_ids = {json.loads(l)["doc_id"] for l in open((_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/staging/ukie/_state/needs_ocr/notext_urls.jsonl"))}
print(json.dumps({"effective_docs": eff, "effective_places": {k: len(v) for k, v in effp.items()},
                  "effective_by_kind": {" / ".join(map(str, k)): v for k, v in kinds.items()},
                  "needs_ocr_unique_docs": len(ocr_ids)}, indent=1))
