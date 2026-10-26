#!/usr/bin/env python3
"""EE municipal IR stage 3: generic build_country from the pinned local pack (rev 9ef422a2a38a), reusing the
lean-encoded embeddings checkpoint; intermediates (corpus ckpt, spill, embeddings) under build/. No collector shedding."""
from __future__ import annotations
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import json, os, sys
from pathlib import Path
os.environ.setdefault("HF_HOME", "/workspace/country-laws-ir/cache/hf")
os.environ["HF_HUB_DISABLE_IMPLICIT_TOKEN"] = "1"
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ["IR_MEM_WARN_GIB"] = "0"      # disable mem.shed_collectors (never SIGTERM collectors)
os.environ.setdefault("IR_MEM_ABORT_GIB", "3.42")  # ~3500 MB hard abort
sys.path.insert(0, "/workspace/country-laws-ir")
import pandas as pd
import country_laws_ir.build as B
from country_laws_ir.catalog import get_country

SLUG = "estonia_municipal"
CAT = get_country(SLUG); TIP = CAT["revision"]; TS = TIP[:12]
BUILD = Path(f"/workspace/country-laws-ir/build/{SLUG}_{TS}"); SRC = BUILD / "src"
OUT = Path(f"/workspace/country-laws-ir/releases/ipfs_{SLUG}_laws_ir")
ROW = dict(CAT, local_source_dir=str(SRC), source_revision=TIP)
B.get_country = lambda _s: dict(ROW)
B.CACHE = BUILD / "cache"
emb = B.CACHE / "embeddings" / f"{SLUG}.npy"
assert emb.is_file() and json.loads(emb.with_suffix(".json").read_text())["n"] == 2279, "lean embeddings missing"
res = B.build_country(str(SRC), out=OUT)
# corpus order used for packaging must equal the order that was encoded
a = pd.read_parquet(B.CACHE / f"{SLUG}_corpus_{TS}.parquet", columns=["entry_cid"])["entry_cid"].tolist()
b = pd.read_parquet(B.CACHE / f"{SLUG}_corpus.parquet", columns=["entry_cid"])["entry_cid"].tolist()
assert a == b, "corpus order drift between encode and package"
res["encode_order_match"] = True
res.pop("normalization", None)
Path(f"/workspace/country-laws-ir/reports/{SLUG}_build_{TS}_result.json").write_text(json.dumps(res, indent=2, default=str) + "\n")
print(json.dumps(res, indent=2, default=str))
