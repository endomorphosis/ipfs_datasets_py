# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
from pathlib import Path

SRC_TIP_FULL = "796ca261e322f0325e210285660fa944654dea07"
SRC_TIP_SHORT = "796ca261e322"
DST_TIP_FULL = "4da9b81784842bcce890bcdd4b837819e2f84fc2"
DST_TIP_SHORT = "4da9b8178484"
SRC_SLUG = "indonesia"
DST_SLUG = "brazil"
SRC_REPO = "endomorphosis/ipfs_indonesia_laws"
DST_REPO = "endomorphosis/ipfs_brazil_laws"
SRC_TARGET = "justicedao/ipfs_indonesia_laws_ir"
DST_TARGET = "justicedao/ipfs_brazil_laws_ir"
FLOOR_LAWS, FLOOR_ARTS = 16875, 99687

ROOT = Path("/workspace/do_ir_resume")

files = [
    ("indonesia_soft_filter.py", "brazil_soft_filter.py"),
    (f"indonesia_corpus_stream_{SRC_TIP_SHORT}.py", f"brazil_corpus_stream_{DST_TIP_SHORT}.py"),
    (f"indonesia_encode_memsafe_{SRC_TIP_SHORT}.py", f"brazil_encode_memsafe_{DST_TIP_SHORT}.py"),
    (f"indonesia_finish_from_emb_{SRC_TIP_SHORT}.py", f"brazil_finish_from_emb_{DST_TIP_SHORT}.py"),
    (f"indonesia_stream_graph_parts_{SRC_TIP_SHORT}.py", f"brazil_stream_graph_parts_{DST_TIP_SHORT}.py"),
    (f"indonesia_package_stream_{SRC_TIP_SHORT}.py", f"brazil_package_stream_{DST_TIP_SHORT}.py"),
    ("indonesia_upload.py", "brazil_upload.py"),
    ("indonesia_bm25_smoke.py", "brazil_bm25_smoke.py"),
    ("indonesia_write_publish_report.py", "brazil_write_publish_report.py"),
    (f"indonesia_orchestrator_{SRC_TIP_SHORT}.py", f"brazil_orchestrator_{DST_TIP_SHORT}.py"),
    ("indonesia_tip_check.py", "brazil_tip_check.py"),
]

def adapt(text: str) -> str:
    t = text
    t = t.replace(SRC_TIP_FULL, DST_TIP_FULL)
    t = t.replace(SRC_TIP_SHORT, DST_TIP_SHORT)
    t = t.replace(SRC_REPO, DST_REPO)
    t = t.replace(SRC_TARGET, DST_TARGET)
    t = t.replace(f"ipfs_{SRC_SLUG}_laws_ir", f"ipfs_{DST_SLUG}_laws_ir")
    for kind in ["filtered_", "corpus_", "bm25_spill_", "corpus_parts_", "orchestrator_", "encode_", "finish_", "stream_graph_", "package_stream_", "upload_", "bm25_smoke_", "publish_", "filter_", "build_", "graph_parts_", "corpus_stream_"]:
        t = t.replace(f"{SRC_SLUG}_{kind}", f"{DST_SLUG}_{kind}")
    t = t.replace(f"embeddings/{SRC_SLUG}_", f"embeddings/{DST_SLUG}_")
    t = t.replace(f"{SRC_SLUG}_normalization", f"{DST_SLUG}_normalization")
    t = t.replace(chr(34)+SRC_SLUG+chr(34), chr(34)+DST_SLUG+chr(34))
    t = t.replace("SLUG = "+chr(34)+SRC_SLUG+chr(34), "SLUG = "+chr(34)+DST_SLUG+chr(34))
    t = t.replace("Indonesia", "Brazil")
    t = t.replace("indonesia_", "brazil_")
    t = t.replace("ipfs_indonesia", "ipfs_brazil")
    t = t.replace("FLOOR_LAWS, FLOOR_ARTS = 1924, 105645", f"FLOOR_LAWS, FLOOR_ARTS = {FLOOR_LAWS}, {FLOOR_ARTS}")
    t = t.replace("1924/105645", f"{FLOOR_LAWS}/{FLOOR_ARTS}")
    t = t.replace("1924, 105645", f"{FLOOR_LAWS}, {FLOOR_ARTS}")
    t = t.replace("or 1924", f"or {FLOOR_LAWS}")
    t = t.replace("or 105645", f"or {FLOOR_ARTS}")
    return t

for src_name, dst_name in files:
    src = ROOT / src_name
    if not src.is_file():
        print(f"MISSING {src}")
        continue
    (ROOT / dst_name).write_text(adapt(src.read_text()))
    print(f"wrote {dst_name}")
print("done")
