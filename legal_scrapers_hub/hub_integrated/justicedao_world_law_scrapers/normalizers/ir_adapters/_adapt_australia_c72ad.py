# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
from pathlib import Path

SRC_TIP_FULL = "fdbce4d4fb14c421ce003f8b89c526399a84a604"
SRC_TIP_SHORT = "fdbce4d4fb14"
DST_TIP_FULL = "c72ad1989fc8d4f4858ea8e2944c77f08406a6dd"
DST_TIP_SHORT = "c72ad1989fc8"
SRC_SLUG = "poland"
DST_SLUG = "australia"
SRC_REPO = "endomorphosis/ipfs_poland_laws"
DST_REPO = "endomorphosis/ipfs_australia_laws"
SRC_TARGET = "justicedao/ipfs_poland_laws_ir"
DST_TARGET = "justicedao/ipfs_australia_laws_ir"
FLOOR_LAWS, FLOOR_ARTS = 29084, 309135

ROOT = Path("/workspace/do_ir_resume")

files = [
    ("poland_soft_filter.py", "australia_soft_filter.py"),
    ("poland_corpus_stream_fdbce4d4fb14.py", f"australia_corpus_stream_{DST_TIP_SHORT}.py"),
    ("poland_encode_memsafe_fdbce4d4fb14.py", f"australia_encode_memsafe_{DST_TIP_SHORT}.py"),
    ("poland_finish_from_emb_fdbce4d4fb14.py", f"australia_finish_from_emb_{DST_TIP_SHORT}.py"),
    ("poland_stream_graph_parts_fdbce4d4fb14.py", f"australia_stream_graph_parts_{DST_TIP_SHORT}.py"),
    ("poland_package_stream_fdbce4d4fb14.py", f"australia_package_stream_{DST_TIP_SHORT}.py"),
    ("poland_upload.py", "australia_upload.py"),
    ("poland_bm25_smoke.py", "australia_bm25_smoke.py"),
    ("poland_write_publish_report.py", "australia_write_publish_report.py"),
    ("poland_orchestrator_fdbce4d4fb14.py", f"australia_orchestrator_{DST_TIP_SHORT}.py"),
    ("poland_tip_check.py", "australia_tip_check.py"),
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
    t = t.replace("Poland", "Australia")
    t = t.replace("poland_", "australia_")
    t = t.replace("ipfs_poland", "ipfs_australia")
    t = t.replace("FLOOR_LAWS, FLOOR_ARTS = 39298, 533538", f"FLOOR_LAWS, FLOOR_ARTS = {FLOOR_LAWS}, {FLOOR_ARTS}")
    t = t.replace("39298/533538", f"{FLOOR_LAWS}/{FLOOR_ARTS}")
    t = t.replace("39298, 533538", f"{FLOOR_LAWS}, {FLOOR_ARTS}")
    t = t.replace("or 39298", f"or {FLOOR_LAWS}")
    t = t.replace("or 533538", f"or {FLOOR_ARTS}")
    return t

for src_name, dst_name in files:
    src = ROOT / src_name
    if not src.is_file():
        print(f"MISSING {src}")
        continue
    text = adapt(src.read_text())
    dst = ROOT / dst_name
    dst.write_text(text)
    print(f"wrote {dst.name} ({len(text)} bytes)")

print("done")
