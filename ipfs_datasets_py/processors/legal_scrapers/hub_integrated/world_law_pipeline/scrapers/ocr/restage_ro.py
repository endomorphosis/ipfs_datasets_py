#!/usr/bin/env python3
"""Restage already-written OCR rows with the v2 number/title/low-conf rules (same doc_ids, newer batch ts).
Re-derives from the OCR text kept in the staged rows; no re-OCR. Usage: python3 restage_ro.py FILE..."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import json, os, sys
from collections import defaultdict
sys.path.insert(0, (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/ocr"))
import ocr_ro as o
titles = {}
for ln in open(o.INP, encoding="utf-8"):
    try: e = json.loads(ln); titles[e["source_url"]] = e.get("title")
    except Exception: pass
by = defaultdict(dict)
for f in sys.argv[1:]:
    for ln in open(f, encoding="utf-8"):
        r = json.loads(ln); by[r["place_id"]][r["doc_id"]] = r
ts = o.utctag(); n = 0
for i, (pid, rows) in enumerate(by.items(), 1):
    out = []
    for r in rows.values():
        e = {"title": titles.get(r["source_url"]) or "", "source_url": r["source_url"]}
        r["number"] = o.doc_number(r["text"], e["title"], r["source_url"])
        r["title_native"] = o.doc_title(e, r["text"])
        m = r["extra_metadata"]; lst = m.get("ocr_low_conf_page_list", m.get("ocr_low_conf_pages") or [])
        if isinstance(lst, int): lst = m.get("ocr_low_conf_page_list", [])
        m["ocr_low_conf_page_list"] = lst; m["ocr_low_conf_pages"] = len(lst)
        m["restaged_at"] = o.utcnow(); r["retrieved_at"] = r["retrieved_at"]
        assert not o.validate_record(r), o.validate_record(r)
        out.append(r)
    pk = o.place_key(pid); fn = o.OUT / "RO" / f"{pk}.ocr{ts}p{i:04d}.jsonl"
    tmp = fn.with_name("." + fn.name[:-6] + ".tmp.jsonl")
    with tmp.open("w", encoding="utf-8") as f:
        for r in out: f.write(json.dumps(r, ensure_ascii=False) + "\n")
        f.flush(); os.fsync(f.fileno())
    v = o.validate_file(tmp, expect_place_key=pk); assert v["ok"], v["errors"][:2]
    os.rename(tmp, fn); n += len(out); print(fn, len(out))
print("restaged", n)
