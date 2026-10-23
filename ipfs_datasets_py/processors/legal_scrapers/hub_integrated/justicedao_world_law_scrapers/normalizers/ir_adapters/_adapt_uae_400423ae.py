# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
from pathlib import Path

SRC_TIP_FULL = "404a1774ff3b276b5a92ae998c2592537614cf84"
SRC_TIP_SHORT = "404a1774ff3b"
DST_TIP_FULL = "400423ae7692a605e81863ee9c19b1daa33b46b0"
DST_TIP_SHORT = "400423ae7692"
SRC_SLUG = "malta"
DST_SLUG = "uae"
SRC_REPO = "endomorphosis/ipfs_malta_laws"
DST_REPO = "endomorphosis/ipfs_uae_laws"
SRC_TARGET = "justicedao/ipfs_malta_laws_ir"
DST_TARGET = "justicedao/ipfs_uae_laws_ir"
FLOOR_LAWS, FLOOR_ARTS = 237, 12566
SRC_FLOOR_L, SRC_FLOOR_A = 19675, 128394

ROOT = Path("/workspace/do_ir_resume")

files = [
    ("malta_soft_filter.py", "uae_soft_filter.py"),
    (f"malta_corpus_stream_{SRC_TIP_SHORT}.py", f"uae_corpus_stream_{DST_TIP_SHORT}.py"),
    (f"malta_encode_memsafe_{SRC_TIP_SHORT}.py", f"uae_encode_memsafe_{DST_TIP_SHORT}.py"),
    (f"malta_finish_from_emb_{SRC_TIP_SHORT}.py", f"uae_finish_from_emb_{DST_TIP_SHORT}.py"),
    (f"malta_stream_graph_parts_{SRC_TIP_SHORT}.py", f"uae_stream_graph_parts_{DST_TIP_SHORT}.py"),
    (f"malta_package_memsafe_{SRC_TIP_SHORT}.py", f"uae_package_memsafe_{DST_TIP_SHORT}.py"),
    ("malta_upload.py", "uae_upload.py"),
    ("malta_bm25_smoke.py", "uae_bm25_smoke.py"),
    ("malta_write_publish_report.py", "uae_write_publish_report.py"),
    (f"malta_orchestrator_{SRC_TIP_SHORT}.py", f"uae_orchestrator_{DST_TIP_SHORT}.py"),
]

def adapt(text: str) -> str:
    t = text
    t = t.replace(SRC_TIP_FULL, DST_TIP_FULL)
    t = t.replace(SRC_TIP_SHORT, DST_TIP_SHORT)
    t = t.replace(SRC_REPO, DST_REPO)
    t = t.replace(SRC_TARGET, DST_TARGET)
    t = t.replace(f"ipfs_{SRC_SLUG}_laws_ir", f"ipfs_{DST_SLUG}_laws_ir")
    for kind in [
        "filtered_", "corpus_", "bm25_spill_", "corpus_parts_", "orchestrator_",
        "encode_", "finish_", "stream_graph_", "package_stream_", "package_memsafe_",
        "upload_", "bm25_smoke_", "publish_", "filter_", "build_", "graph_parts_",
        "corpus_stream_",
    ]:
        t = t.replace(f"{SRC_SLUG}_{kind}", f"{DST_SLUG}_{kind}")
    t = t.replace(f"embeddings/{SRC_SLUG}_", f"embeddings/{DST_SLUG}_")
    t = t.replace(f"{SRC_SLUG}_normalization", f"{DST_SLUG}_normalization")
    t = t.replace(chr(34) + SRC_SLUG + chr(34), chr(34) + DST_SLUG + chr(34))
    t = t.replace("SLUG = " + chr(34) + SRC_SLUG + chr(34), "SLUG = " + chr(34) + DST_SLUG + chr(34))
    t = t.replace("Malta", "UAE")
    t = t.replace("Maltese", "Arabic")
    t = t.replace("Maltan", "UAE")
    t = t.replace("malta_", "uae_")
    t = t.replace("ipfs_malta", "ipfs_uae")
    t = t.replace("valletta", "abu")  # placeholder; smoke rewritten separately
    t = t.replace(f"FLOOR_LAWS, FLOOR_ARTS = {SRC_FLOOR_L}, {SRC_FLOOR_A}", f"FLOOR_LAWS, FLOOR_ARTS = {FLOOR_LAWS}, {FLOOR_ARTS}")
    t = t.replace(f"{SRC_FLOOR_L}/{SRC_FLOOR_A}", f"{FLOOR_LAWS}/{FLOOR_ARTS}")
    t = t.replace(f"{SRC_FLOOR_L}, {SRC_FLOOR_A}", f"{FLOOR_LAWS}, {FLOOR_ARTS}")
    t = t.replace(f"or {SRC_FLOOR_L}", f"or {FLOOR_LAWS}")
    t = t.replace(f"or {SRC_FLOOR_A}", f"or {FLOOR_ARTS}")
    t = t.replace(f"n_laws_source\": int(pack.get(\"n_laws\") or {SRC_FLOOR_L})", f"n_laws_source\": int(pack.get(\"n_laws\") or {FLOOR_LAWS})")
    t = t.replace(f"n_articles_source\": int(pack.get(\"n_articles\") or {SRC_FLOOR_A})", f"n_articles_source\": int(pack.get(\"n_articles\") or {FLOOR_ARTS})")
    t = t.replace("FIRST-IR", "RECONFIRM_FINAL")
    t = t.replace("RECONFIRM", "RECONFIRM_FINAL")
    # undo double-replacement
    t = t.replace("RECONFIRM_FINAL_FINAL", "RECONFIRM_FINAL")
    return t

for src_name, dst_name in files:
    src = ROOT / src_name
    if not src.is_file():
        print(f"MISSING {src}")
        continue
    (ROOT / dst_name).write_text(adapt(src.read_text()))
    print(f"wrote {dst_name}")
print("done")
