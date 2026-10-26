#!/usr/bin/env python3
"""CH tip 7f9da5c86658 UPDATE_EXPAND (cantonal append; 20080 laws / 483891 articles). Memsafe+memmap pack cloned from Slovenia 8ba5be36c89f (streaming spill concat)."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
from pathlib import Path
import re
ROOT = Path("/workspace/do_ir_resume")
DF, DS = "7f9da5c8665870636242b176cea65e29d4f7ef0b", "7f9da5c86658"
S_F, S_S = "8ba5be36c89f75e4a06e57ff943d48d77e819d33", "8ba5be36c89f"
def conv(t):
    t = t.replace(S_F, "\0F").replace(S_S, "\0S")
    t = t.replace("uradni-list.si", "fedlex.admin.ch + cantonal collections")
    t = t.replace("SLOVENIA", "SWITZERLAND").replace("Slovenian", "Swiss").replace("Slovenia", "Switzerland").replace("slovenia", "switzerland")
    t = t.replace("236538", "20080").replace("1515677", "483891")
    return t.replace("\0F", DF).replace("\0S", DS)
for p in ("soft_filter", "corpus_stream", "encode_memsafe", "finish_from_emb", "stream_graph_parts", "package_stream", "orchestrator", "upload", "write_publish_report"):
    t = conv((ROOT / f"slovenia_{p}_{S_S}.py").read_text())
    if p == "write_publish_report":
        t = re.sub(r'else "HOLD 0 STRICT[^\n]*"', 'else "HOLD 0 STRICT EXPAND (CH cantonal UPDATE after SI LIVE); collectors=0; soft never-thin ON; SKIP_US; Italy leave alone; AU subnational only after CoS CLEAR"', t)
        t = re.sub(r'"BM25 PASS on Switzerland[^\n]*",', '"BM25 PASS on Switzerland Swiss query set (see smoke report)",', t)
    (ROOT / f"switzerland_{p}_{DS}.py").write_text(t); print("wrote", p)
t = (ROOT / "switzerland_bm25_smoke.py").read_text().replace("b23f3e62b4b2", DS)
(ROOT / f"switzerland_bm25_smoke_{DS}.py").write_text(t); print("wrote smoke")
