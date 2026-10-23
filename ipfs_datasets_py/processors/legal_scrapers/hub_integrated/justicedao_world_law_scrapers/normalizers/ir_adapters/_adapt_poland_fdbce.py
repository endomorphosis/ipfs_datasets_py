# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
from pathlib import Path

SRC_TIP_FULL = "2302d85c4edc6b31793e64858c8d306540a94a45"
SRC_TIP_SHORT = "2302d85c4edc"
DST_TIP_FULL = "fdbce4d4fb14c421ce003f8b89c526399a84a604"
DST_TIP_SHORT = "fdbce4d4fb14"
SRC_SLUG = "france"
DST_SLUG = "poland"
SRC_REPO = "endomorphosis/ipfs_france_laws"
DST_REPO = "endomorphosis/ipfs_poland_laws"
SRC_TARGET = "justicedao/ipfs_france_laws_ir"
DST_TARGET = "justicedao/ipfs_poland_laws_ir"
FLOOR_LAWS, FLOOR_ARTS = 39298, 533538

ROOT = Path("/workspace/do_ir_resume")

files = [
    ("france_soft_filter.py", "poland_soft_filter.py"),
    ("france_corpus_stream_2302d85c4edc.py", f"poland_corpus_stream_{DST_TIP_SHORT}.py"),
    ("france_encode_memsafe_2302d85c4edc.py", f"poland_encode_memsafe_{DST_TIP_SHORT}.py"),
    ("france_finish_from_emb_2302d85c4edc.py", f"poland_finish_from_emb_{DST_TIP_SHORT}.py"),
    ("france_stream_graph_parts_2302d85c4edc.py", f"poland_stream_graph_parts_{DST_TIP_SHORT}.py"),
    ("france_package_stream_2302d85c4edc.py", f"poland_package_stream_{DST_TIP_SHORT}.py"),
    ("france_upload.py", "poland_upload.py"),
    ("france_bm25_smoke.py", "poland_bm25_smoke.py"),
    ("france_write_publish_report.py", "poland_write_publish_report.py"),
    ("france_orchestrator_2302d85c4edc.py", f"poland_orchestrator_{DST_TIP_SHORT}.py"),
    ("france_tip_check.py", "poland_tip_check.py"),
]

def adapt(text: str) -> str:
    t = text
    t = t.replace(SRC_TIP_FULL, DST_TIP_FULL)
    t = t.replace(SRC_TIP_SHORT, DST_TIP_SHORT)
    t = t.replace(SRC_REPO, DST_REPO)
    t = t.replace(SRC_TARGET, DST_TARGET)
    t = t.replace(f"ipfs_{SRC_SLUG}_laws_ir", f"ipfs_{DST_SLUG}_laws_ir")
    t = t.replace(f"{SRC_SLUG}_filtered_", f"{DST_SLUG}_filtered_")
    t = t.replace(f"{SRC_SLUG}_corpus_", f"{DST_SLUG}_corpus_")
    t = t.replace(f"{SRC_SLUG}_bm25_spill_", f"{DST_SLUG}_bm25_spill_")
    t = t.replace(f"{SRC_SLUG}_corpus_parts_", f"{DST_SLUG}_corpus_parts_")
    t = t.replace(f"embeddings/{SRC_SLUG}_", f"embeddings/{DST_SLUG}_")
    t = t.replace(f"{SRC_SLUG}_orchestrator_", f"{DST_SLUG}_orchestrator_")
    t = t.replace(f"{SRC_SLUG}_encode_", f"{DST_SLUG}_encode_")
    t = t.replace(f"{SRC_SLUG}_finish_", f"{DST_SLUG}_finish_")
    t = t.replace(f"{SRC_SLUG}_stream_graph_", f"{DST_SLUG}_stream_graph_")
    t = t.replace(f"{SRC_SLUG}_package_stream_", f"{DST_SLUG}_package_stream_")
    t = t.replace(f"{SRC_SLUG}_upload_", f"{DST_SLUG}_upload_")
    t = t.replace(f"{SRC_SLUG}_bm25_smoke_", f"{DST_SLUG}_bm25_smoke_")
    t = t.replace(f"{SRC_SLUG}_publish_", f"{DST_SLUG}_publish_")
    t = t.replace(f"{SRC_SLUG}_filter_", f"{DST_SLUG}_filter_")
    t = t.replace(f"{SRC_SLUG}_build_", f"{DST_SLUG}_build_")
    t = t.replace(f"{SRC_SLUG}_normalization", f"{DST_SLUG}_normalization")
    t = t.replace(f"{SRC_SLUG}_graph_parts_", f"{DST_SLUG}_graph_parts_")
    t = t.replace(f"{SRC_SLUG}_corpus_stream_", f"{DST_SLUG}_corpus_stream_")
    t = t.replace(f'"{SRC_SLUG}"', f'"{DST_SLUG}"')
    t = t.replace(f"SLUG = \"{SRC_SLUG}\"", f"SLUG = \"{DST_SLUG}\"")
    t = t.replace("France", "Poland")
    t = t.replace("france_", "poland_")
    t = t.replace("ipfs_france", "ipfs_poland")
    t = t.replace("FLOOR_LAWS, FLOOR_ARTS = 114041, 677149", f"FLOOR_LAWS, FLOOR_ARTS = {FLOOR_LAWS}, {FLOOR_ARTS}")
    t = t.replace("114041/677149", f"{FLOOR_LAWS}/{FLOOR_ARTS}")
    t = t.replace("114041, 677149", f"{FLOOR_LAWS}, {FLOOR_ARTS}")
    t = t.replace("or 114041", f"or {FLOOR_LAWS}")
    t = t.replace("or 677149", f"or {FLOOR_ARTS}")
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
