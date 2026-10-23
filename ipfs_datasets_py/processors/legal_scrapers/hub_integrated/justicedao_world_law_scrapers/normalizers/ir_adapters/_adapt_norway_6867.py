# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
from pathlib import Path

SRC_TIP_FULL = "9d5021ed3f4329ba551fd8dfa4c250b65bbd73be"
SRC_TIP_SHORT = "9d5021ed3f43"
DST_TIP_FULL = "6867fc1c4713e58cd493c83ced7e0e04d88881b0"
DST_TIP_SHORT = "6867fc1c4713"
SRC_SLUG = "eu"
DST_SLUG = "norway"
SRC_REPO = "endomorphosis/ipfs_eu_laws"
DST_REPO = "endomorphosis/ipfs_norway_laws"
SRC_TARGET = "justicedao/ipfs_eu_laws_ir"
DST_TARGET = "justicedao/ipfs_norway_laws_ir"
FLOOR_LAWS, FLOOR_ARTS = 5872, 97340

ROOT = Path("/workspace/do_ir_resume")

files = [
    ("eu_soft_filter.py", "norway_soft_filter.py"),
    (f"eu_corpus_stream_{SRC_TIP_SHORT}.py", f"norway_corpus_stream_{DST_TIP_SHORT}.py"),
    (f"eu_encode_memsafe_{SRC_TIP_SHORT}.py", f"norway_encode_memsafe_{DST_TIP_SHORT}.py"),
    (f"eu_finish_from_emb_{SRC_TIP_SHORT}.py", f"norway_finish_from_emb_{DST_TIP_SHORT}.py"),
    (f"eu_stream_graph_parts_{SRC_TIP_SHORT}.py", f"norway_stream_graph_parts_{DST_TIP_SHORT}.py"),
    (f"eu_package_stream_{SRC_TIP_SHORT}.py", f"norway_package_stream_{DST_TIP_SHORT}.py"),
    ("eu_upload.py", "norway_upload.py"),
    ("eu_bm25_smoke.py", "norway_bm25_smoke.py"),
    ("eu_write_publish_report.py", "norway_write_publish_report.py"),
    (f"eu_orchestrator_{SRC_TIP_SHORT}.py", f"norway_orchestrator_{DST_TIP_SHORT}.py"),
    ("eu_tip_check.py", "norway_tip_check.py"),
]

def adapt(text: str) -> str:
    t = text
    t = t.replace(SRC_TIP_FULL, DST_TIP_FULL)
    t = t.replace(SRC_TIP_SHORT, DST_TIP_SHORT)
    t = t.replace(SRC_REPO, DST_REPO)
    t = t.replace(SRC_TARGET, DST_TARGET)
    t = t.replace(f"ipfs_{SRC_SLUG}_laws_ir", f"ipfs_{DST_SLUG}_laws_ir")
    for kind in ["filtered_", "corpus_", "bm25_spill_", "corpus_parts_", "orchestrator_", "encode_", "finish_", "stream_graph_", "package_stream_", "upload_", "bm25_smoke_", "publish_", "filter_", "build_", "graph_parts_", "corpus_stream_", "normalization"]:
        t = t.replace(f"{SRC_SLUG}_{kind}", f"{DST_SLUG}_{kind}")
    t = t.replace(f"embeddings/{SRC_SLUG}_", f"embeddings/{DST_SLUG}_")
    t = t.replace(chr(34)+SRC_SLUG+chr(34), chr(34)+DST_SLUG+chr(34))
    t = t.replace("SLUG = "+chr(34)+SRC_SLUG+chr(34), "SLUG = "+chr(34)+DST_SLUG+chr(34))
    t = t.replace("European Union", "Norway")
    t = t.replace("eu_", "norway_")
    # careful: "eu" alone in paths - already slug-replaced
    t = t.replace("ipfs_eu", "ipfs_norway")
    t = t.replace('"country": "eu"', '"country": "norway"')
    t = t.replace("FLOOR_LAWS, FLOOR_ARTS = 54102, 143188", f"FLOOR_LAWS, FLOOR_ARTS = {FLOOR_LAWS}, {FLOOR_ARTS}")
    t = t.replace("54102/143188", f"{FLOOR_LAWS}/{FLOOR_ARTS}")
    t = t.replace("54102, 143188", f"{FLOOR_LAWS}, {FLOOR_ARTS}")
    t = t.replace("or 54102", f"or {FLOOR_LAWS}")
    t = t.replace("or 143188", f"or {FLOOR_ARTS}")
    return t

for src_name, dst_name in files:
    src = ROOT / src_name
    if not src.is_file():
        print(f"MISSING {src}")
        continue
    (ROOT / dst_name).write_text(adapt(src.read_text()))
    print(f"wrote {dst_name}")
print("done")
