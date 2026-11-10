# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
from pathlib import Path

SRC_TIP_FULL = "cfcff2dc1b1a5db6e90f42ee8982a706c3b4e3b0"
SRC_TIP_SHORT = "cfcff2dc1b1a"
DST_TIP_FULL = "a174ce3d2e51385dd21584ba4aa7618c97910d86"
DST_TIP_SHORT = "a174ce3d2e51"
SRC_SLUG = "uk"
DST_SLUG = "korea"
SRC_REPO = "endomorphosis/ipfs_uk_laws"
DST_REPO = "endomorphosis/ipfs_korea_laws"
SRC_TARGET = "justicedao/ipfs_uk_laws_ir"
DST_TARGET = "justicedao/ipfs_korea_laws_ir"
FLOOR_LAWS, FLOOR_ARTS = 5659, 174324

ROOT = Path("/workspace/do_ir_resume")

files = [
    ("uk_soft_filter.py", "korea_soft_filter.py"),
    (f"uk_corpus_stream_{SRC_TIP_SHORT}.py", f"korea_corpus_stream_{DST_TIP_SHORT}.py"),
    (f"uk_encode_memsafe_{SRC_TIP_SHORT}.py", f"korea_encode_memsafe_{DST_TIP_SHORT}.py"),
    (f"uk_finish_from_emb_{SRC_TIP_SHORT}.py", f"korea_finish_from_emb_{DST_TIP_SHORT}.py"),
    (f"uk_stream_graph_parts_{SRC_TIP_SHORT}.py", f"korea_stream_graph_parts_{DST_TIP_SHORT}.py"),
    (f"uk_package_stream_{SRC_TIP_SHORT}.py", f"korea_package_stream_{DST_TIP_SHORT}.py"),
    ("uk_upload.py", "korea_upload.py"),
    ("uk_bm25_smoke.py", "korea_bm25_smoke.py"),
    ("uk_write_publish_report.py", "korea_write_publish_report.py"),
    (f"uk_orchestrator_{SRC_TIP_SHORT}.py", f"korea_orchestrator_{DST_TIP_SHORT}.py"),
    ("uk_tip_check.py", "korea_tip_check.py"),
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
    t = t.replace("United Kingdom", "Korea")
    t = t.replace("uk_", "korea_")
    t = t.replace("ipfs_uk", "ipfs_korea")
    # careful: "uk" alone in paths already handled via slug replacements
    t = t.replace("FLOOR_LAWS, FLOOR_ARTS = 6158, 332358", f"FLOOR_LAWS, FLOOR_ARTS = {FLOOR_LAWS}, {FLOOR_ARTS}")
    t = t.replace("6158/332358", f"{FLOOR_LAWS}/{FLOOR_ARTS}")
    t = t.replace("6158, 332358", f"{FLOOR_LAWS}, {FLOOR_ARTS}")
    t = t.replace("or 6158", f"or {FLOOR_LAWS}")
    t = t.replace("or 332358", f"or {FLOOR_ARTS}")
    return t

for src_name, dst_name in files:
    src = ROOT / src_name
    if not src.is_file():
        print(f"MISSING {src}")
        continue
    (ROOT / dst_name).write_text(adapt(src.read_text()))
    print(f"wrote {dst_name}")
print("done")
