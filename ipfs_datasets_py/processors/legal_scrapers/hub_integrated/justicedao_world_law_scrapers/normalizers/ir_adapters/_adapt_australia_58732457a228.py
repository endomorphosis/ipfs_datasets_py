#!/usr/bin/env python3
"""AU tip 58732457a228 UPDATE_EXPAND (subnational append NSW/QLD/TAS/WA/NT; 36214 laws / 680077 articles). Memsafe pack cloned from Switzerland 7f9da5c86658 (streaming spill concat)."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
from pathlib import Path
import re
ROOT = Path("/workspace/do_ir_resume")
DF, DS = "58732457a228ad5b4cd8c870168b7a5974025ea4", "58732457a228"
S_F, S_S = "7f9da5c8665870636242b176cea65e29d4f7ef0b", "7f9da5c86658"
def conv(t):
    t = t.replace(S_F, "\0F").replace(S_S, "\0S")
    t = t.replace("fedlex.admin.ch + cantonal collections", "legislation.gov.au + state/territory registers")
    t = t.replace("SWITZERLAND", "AUSTRALIA").replace("Swiss", "Australian").replace("Switzerland", "Australia").replace("switzerland", "australia")
    t = t.replace("20080", "36214").replace("483891", "680077")
    return t.replace("\0F", DF).replace("\0S", DS)
for p in ("soft_filter", "corpus_stream", "encode_memsafe", "finish_from_emb", "stream_graph_parts", "package_stream", "orchestrator", "upload", "write_publish_report"):
    t = conv((ROOT / f"switzerland_{p}_{S_S}.py").read_text())
    if p == "write_publish_report":
        t = re.sub(r'else "HOLD 0 STRICT[^\n]*"', 'else "HOLD 0 STRICT EXPAND (AU subnational UPDATE after CH LIVE); collectors=0; soft never-thin ON; SKIP_US; Italy leave alone; CA/ES/DE/IN subnational only after CoS CLEAR"', t)
        t = re.sub(r'"BM25 PASS on Australia[^\n]*",', '"BM25 PASS on Australia Australian legal English query set (see smoke report)",', t)
    (ROOT / f"australia_{p}_{DS}.py").write_text(t); print("wrote", p)
t = (ROOT / "australia_bm25_smoke.py").read_text().replace("c72ad1989fc8", DS)
(ROOT / f"australia_bm25_smoke_{DS}.py").write_text(t); print("wrote smoke")
