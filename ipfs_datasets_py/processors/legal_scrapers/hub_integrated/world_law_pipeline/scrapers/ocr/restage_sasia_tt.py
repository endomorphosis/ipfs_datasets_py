#!/usr/bin/env python3
"""Restage the 10 Tatarstan docs from quarantined iso_RU-TA.ocr20261014T130955Zp0001.jsonl keyed by issuing body
(cached OCR text from that file, no re-OCR). Unresolved issuers -> _logs/sasia_held.jsonl."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import os as _wl_os  # WORLD_LAW_ROOT / GLOBAL_MUNICIPALITIES_ROOT override the default paths
import json, os, sys
from collections import defaultdict
sys.path.insert(0, (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/ocr")); sys.path.insert(0, (_wl_os.environ.get("WORLD_LAW_ROOT", "/workspace/world_law") + "/pipeline"))
import ocr_afme as A, ocr_sasia as S
from schema import place_key, validate_file, validate_record
SRC = A.OUT / "RU" / "iso_RU-TA.ocr20261014T130955Zp0001.jsonl"
q = {json.loads(l)["doc_id"]: json.loads(l) for l in open(S.Q / "ocr_queue.jsonl", encoding="utf-8") if l.strip()}
by, held = defaultdict(list), []
for l in open(SRC, encoding="utf-8"):
    old = json.loads(l); e = q[old["doc_id"]]; e.setdefault("country", "RU")
    meta = {k: v for k, v in old["extra_metadata"].items() if k not in ("archive", "issuer_match")}
    try: r = S.row_for(e, old["text"], meta, {"via": "commoncrawl", "url": old["archive_url"]})
    except A.Skip as s:
        held.append((old["doc_id"], s.detail))
        with open(A.LOGS / "sasia_held.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": A.utcnow(), "doc_id": old["doc_id"], "source_url": old["source_url"], "reason": s.detail, "from": SRC.name}, ensure_ascii=False) + "\n")
        continue
    assert not validate_record(r), validate_record(r); by[r["place_id"]].append(r)
ts = A.utctag(); out = []
for i, (pid, rs) in enumerate(sorted(by.items()), 1):
    pk = place_key(pid); fn = A.OUT / "RU" / f"{pk}.ocr{ts}p{i:04d}.jsonl"; assert not fn.exists()
    tmp = fn.with_name("." + fn.name[:-6] + ".tmp.jsonl")
    with tmp.open("w", encoding="utf-8") as f:
        for r in rs: f.write(json.dumps(r, ensure_ascii=False) + "\n")
        f.flush(); os.fsync(f.fileno())
    v = validate_file(tmp, expect_place_key=pk); assert v["ok"], v
    os.rename(tmp, fn); out.append({"file": str(fn), "docs": [(r["doc_id"], r["number"], r["extra_metadata"]["issuer_match"]) for r in rs]})
print(json.dumps({"staged": out, "held": held}, ensure_ascii=False, indent=1))
