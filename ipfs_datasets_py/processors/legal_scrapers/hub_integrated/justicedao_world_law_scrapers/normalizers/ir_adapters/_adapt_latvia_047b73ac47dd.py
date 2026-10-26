#!/usr/bin/env python3
"""LV tip 047b73ac47dd UPDATE_EXPAND (885028 units, local split). Memsafe pack from Croatia 42326b74f129; smoke from Latvia d3b4679db9d0. Floor 85628/885028."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
from pathlib import Path
import re
ROOT = Path("/workspace/do_ir_resume")
DF, DS = "047b73ac47dd614ff0815d77889ab188cf741ef9", "047b73ac47dd"
C_F, C_S = "42326b74f129b7e9502396c3776828200d508722", "42326b74f129"
def from_hr(t):
    t = t.replace(C_F, "\0F").replace(C_S, "\0S")
    t = t.replace("narodne-novine.nn.hr", "likumi.lv")
    t = t.replace("CROATIA", "LATVIA").replace("Croatian", "Latvian").replace("Croatia", "Latvia").replace("croatia", "latvia")
    t = t.replace("30315", "85628").replace("282996", "885028")
    return t.replace("\0F", DF).replace("\0S", DS)
for p in ("soft_filter", "corpus_stream", "encode_memsafe", "finish_from_emb", "stream_graph_parts", "package_stream", "orchestrator", "upload", "write_publish_report"):
    t = from_hr((ROOT / f"croatia_{p}_{C_S}.py").read_text())
    if p == "write_publish_report":
        t = re.sub(r'else "HOLD 0 STRICT[^\n]*"', 'else "HOLD 0 STRICT EXPAND (LV UPDATE after SK LIVE); collectors=0; soft never-thin ON; SKIP_US; Italy leave alone; next SI only after CoS CLEAR"', t)
        t = re.sub(r'"BM25 PASS on Latvia[^\n]*",', '"BM25 PASS on Latvia ASCII-fold Latvian query set (see smoke report); URL likumi.lv query-only",', t)
    (ROOT / f"latvia_{p}_{DS}.py").write_text(t); print("wrote", p)
t = (ROOT / "latvia_bm25_smoke.py").read_text().replace("d3b4679db9d0", DS)
(ROOT / f"latvia_bm25_smoke_{DS}.py").write_text(t); print("wrote smoke")
