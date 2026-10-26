#!/usr/bin/env python3
"""Restage the 4 KE files from afme test batch 20261014T124602Z with fixed numbers (cached OCR text, no re-OCR)."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import glob, json, os, sys
sys.path.insert(0, (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/ocr")); sys.path.insert(0, (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/pipeline"))
import ocr_afme as A
from schema import place_key, validate_file
src = sorted(glob.glob(str(A.OUT / "KE" / "*.ocr20261014T124602Zp*.jsonl")))
ts = A.utctag(); out = []
for i, f in enumerate(src, 1):
    rows = [json.loads(l) for l in open(f, encoding="utf-8")]
    for r in rows: r["number"] = A.doc_number("KE", r["text"], r["title_native"]); r["retrieved_at"] = A.utcnow()
    pk = place_key(rows[0]["place_id"]); fn = A.OUT / "KE" / f"{pk}.ocr{ts}p{i:04d}.jsonl"
    assert not fn.exists(); tmp = fn.with_name("." + fn.name[:-6] + ".tmp.jsonl")
    with tmp.open("w", encoding="utf-8") as fh:
        for r in rows: fh.write(json.dumps(r, ensure_ascii=False) + "\n")
        fh.flush(); os.fsync(fh.fileno())
    v = validate_file(tmp, expect_place_key=pk); assert v["ok"], v
    os.rename(tmp, fn); out.append((str(fn), [(r["doc_id"], r["number"]) for r in rows]))
print(json.dumps(out, ensure_ascii=False, indent=0))
