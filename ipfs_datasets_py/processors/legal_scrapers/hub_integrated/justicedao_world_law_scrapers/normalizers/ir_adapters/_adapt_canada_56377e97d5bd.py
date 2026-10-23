#!/usr/bin/env python3
"""CA tip 56377e97d5bd UPDATE_EXPAND (provincial append ON/NS/NB/NT/NU; 19208 laws / 442911 articles). Memsafe pack cloned from Australia 58732457a228 (BATCH16/CHUNK1024 encode, streaming spill concat)."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
from pathlib import Path
import re
ROOT = Path("/workspace/do_ir_resume")
DF, DS = "56377e97d5bd73624f65c3456fb887c963a938f9", "56377e97d5bd"
S_F, S_S = "58732457a228ad5b4cd8c870168b7a5974025ea4", "58732457a228"
def conv(t):
    t = t.replace(S_F, "\0F").replace(S_S, "\0S")
    t = t.replace("legislation.gov.au + state/territory registers", "laws-lois.justice.gc.ca + provincial/territorial registers")
    t = t.replace("AUSTRALIA", "CANADA").replace("Australian", "Canadian").replace("Australia", "Canada").replace("australia", "canada")
    t = t.replace("36214", "19208").replace("680077", "442911")
    return t.replace("\0F", DF).replace("\0S", DS)
for p in ("soft_filter", "corpus_stream", "encode_memsafe", "finish_from_emb", "stream_graph_parts", "package_stream", "orchestrator", "upload", "write_publish_report"):
    t = conv((ROOT / f"australia_{p}_{S_S}.py").read_text())
    if p == "write_publish_report":
        t = re.sub(r'else "HOLD 0 STRICT[^\n]*"', 'else "HOLD 0 STRICT EXPAND (CA provincial UPDATE after AU LIVE); collectors=0; soft never-thin ON; SKIP_US; Italy leave alone; MB/SK held pending licence decision"', t)
        t = re.sub(r'"BM25 PASS on Canada[^\n]*",', '"BM25 PASS on Canada English/French query set (see smoke report)",', t)
    (ROOT / f"canada_{p}_{DS}.py").write_text(t); print("wrote", p)
t = (ROOT / "canada_bm25_smoke.py").read_text().replace("7e8066f09c8c", DS)
(ROOT / f"canada_bm25_smoke_{DS}.py").write_text(t); print("wrote smoke")
