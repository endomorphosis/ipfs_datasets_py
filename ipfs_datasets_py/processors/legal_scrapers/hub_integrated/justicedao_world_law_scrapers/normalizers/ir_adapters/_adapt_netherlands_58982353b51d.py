#!/usr/bin/env python3
"""NL tip 58982353b51d ARTICLE_EXTRACT (KOOP CC0 repository split; 18626 laws / 272214 articles). Memsafe pack cloned from Germany 4911b83beea2."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
from pathlib import Path
import re
ROOT = Path("/workspace/do_ir_resume")
DF, DS = "58982353b51d0b5d8896f29ce0fb2925c6c00c90", "58982353b51d"
S_F, S_S = "4911b83beea20b59806bce17c4bfe082d44fc2c0", "4911b83beea2"
def conv(t):
    t = t.replace(S_F, "\0F").replace(S_S, "\0S")
    t = t.replace("gesetze-im-internet.de + Länder portals (NW/SN/BB; HB held)", "KOOP basiswettenbestand repository (CC0)")
    t = t.replace("GERMANY", "NETHERLANDS").replace("Germany", "Netherlands").replace("germany", "netherlands").replace("German", "Dutch")
    t = t.replace("9287", "18626").replace("194134", "272214")
    return t.replace("\0F", DF).replace("\0S", DS)
for p in ("soft_filter", "corpus_stream", "encode_memsafe", "finish_from_emb", "stream_graph_parts", "package_stream", "orchestrator", "upload", "write_publish_report"):
    t = conv((ROOT / f"germany_{p}_{S_S}.py").read_text())
    if p == "write_publish_report":
        t = re.sub(r'else "HOLD 0 STRICT[^\n]*"', 'else "HOLD 0 STRICT ARTICLE_EXTRACT (NL KOOP CC0 split after DE LIVE); collectors=0; soft never-thin ON; SKIP_US; Italy leave alone"', t)
    (ROOT / f"netherlands_{p}_{DS}.py").write_text(t); print("wrote", p)
t = (ROOT / "netherlands_bm25_smoke.py").read_text()
old = re.findall(r"netherlands_bm25_smoke_([0-9a-f]{12})", t)
for o in set(old): t = t.replace(o, DS)
t = re.sub(r'detail\["tip"\] = "[0-9a-f]{12}"', f'detail["tip"] = "{DS}"', t)
(ROOT / f"netherlands_bm25_smoke_{DS}.py").write_text(t); print("wrote smoke", set(old))
