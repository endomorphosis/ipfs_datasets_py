#!/usr/bin/env python3
"""SK tip b28c2e913f97 UPDATE_EXPAND (147423 arts local split). Stream+filter+upload from Croatia 42326b74f129 memsafe pack;
smoke/report from Slovakia 22508a5eab4b pack. Floor 16799/147423."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
from pathlib import Path
ROOT = Path("/workspace/do_ir_resume")
DF, DS = "b28c2e913f97762fa150d669c930d09c07cf8332", "b28c2e913f97"
C_F, C_S = "42326b74f129b7e9502396c3776828200d508722", "42326b74f129"
S_F, S_S = None, "22508a5eab4b"
def from_hr(t):
    t = t.replace(C_F, "\0F").replace(C_S, "\0S")
    t = t.replace("narodne-novine.nn.hr", "www.slov-lex.sk")
    t = t.replace("CROATIA", "SLOVAKIA").replace("Croatian", "Slovak").replace("Croatia", "Slovakia").replace("croatia", "slovakia")
    t = t.replace("30315", "16799").replace("282996", "147423")
    return t.replace("\0F", DF).replace("\0S", DS)
def from_sk(t):
    t = t.replace(S_S, "\0S")
    t = t.replace("16799/179", "16799/147423").replace("SOFT_THIN_FINAL", "UPDATE_EXPAND")
    t = t.replace('"slovakia_filter_\0S.json"', '"slovakia_filter_\0S.json"')
    return t.replace("\0S", DS)
jobs = [(f"croatia_{p}_{C_S}.py", f"slovakia_{p}_{DS}.py", from_hr) for p in
        ("soft_filter", "corpus_stream", "encode_memsafe", "finish_from_emb", "stream_graph_parts", "package_stream", "orchestrator", "upload")]
jobs += [(f"slovakia_{p}.py", f"slovakia_{p}_{DS}.py", from_sk) for p in ("bm25_smoke", "write_publish_report")]
for s, d, fn in jobs:
    (ROOT / d).write_text(fn((ROOT / s).read_text())); print("wrote", d)
