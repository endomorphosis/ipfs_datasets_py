#!/usr/bin/env python3
"""SI tip 8ba5be36c89f UPDATE_EXPAND (1515677 units, local split). Memsafe+memmap pack cloned from Latvia 047b73ac47dd. Floor 236538/1515677."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
from pathlib import Path
import re
ROOT = Path("/workspace/do_ir_resume")
DF, DS = "8ba5be36c89f75e4a06e57ff943d48d77e819d33", "8ba5be36c89f"
L_F, L_S = "047b73ac47dd614ff0815d77889ab188cf741ef9", "047b73ac47dd"
def from_lv(t):
    t = t.replace(L_F, "\0F").replace(L_S, "\0S")
    t = t.replace("likumi.lv", "uradni-list.si")
    t = t.replace("LATVIA", "SLOVENIA").replace("Latvian", "Slovenian").replace("Latvia", "Slovenia").replace("latvia", "slovenia")
    t = t.replace("85628", "236538").replace("885028", "1515677")
    return t.replace("\0F", DF).replace("\0S", DS)
for p in ("soft_filter", "corpus_stream", "encode_memsafe", "finish_from_emb", "stream_graph_parts", "package_stream", "orchestrator", "upload", "write_publish_report"):
    t = from_lv((ROOT / f"latvia_{p}_{L_S}.py").read_text())
    if p == "write_publish_report":
        t = re.sub(r'else "HOLD 0 STRICT[^\n]*"', 'else "HOLD 0 STRICT EXPAND (SI UPDATE after LV LIVE); collectors=0; soft never-thin ON; SKIP_US; Italy leave alone; next subnational only after CoS CLEAR"', t)
        t = re.sub(r'"BM25 PASS on Slovenia[^\n]*",', '"BM25 PASS on Slovenia Slovenian query set (see smoke report)",', t)
    (ROOT / f"slovenia_{p}_{DS}.py").write_text(t); print("wrote", p)
t = (ROOT / "slovenia_bm25_smoke.py").read_text().replace("93611719fbb1", DS)
(ROOT / f"slovenia_bm25_smoke_{DS}.py").write_text(t); print("wrote smoke")
