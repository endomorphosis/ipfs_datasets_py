# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
from pathlib import Path

SRC_TIP_FULL = "dea9e0d1bd072599be5d21a54d075d6cb181a1f1"
SRC_TIP_SHORT = "dea9e0d1bd07"
DST_TIP_FULL = "397e6ed9482ed7ce7ee7fce19f818533d35da92f"
DST_TIP_SHORT = "397e6ed9482e"
SRC_SLUG = "mali"
DST_SLUG = "burkinafaso"
SRC_REPO = "endomorphosis/ipfs_mali_laws"
DST_REPO = "endomorphosis/ipfs_burkinafaso_laws"
SRC_TARGET = "justicedao/ipfs_mali_laws_ir"
DST_TARGET = "justicedao/ipfs_burkinafaso_laws_ir"
FLOOR_LAWS, FLOOR_ARTS = 142, 28929
SRC_FLOOR_L, SRC_FLOOR_A = 205, 29924

ROOT = Path("/workspace/do_ir_resume")

files = [
    ("mali_soft_filter.py", "burkinafaso_soft_filter.py"),
    (f"mali_corpus_stream_{SRC_TIP_SHORT}.py", f"burkinafaso_corpus_stream_{DST_TIP_SHORT}.py"),
    (f"mali_encode_memsafe_{SRC_TIP_SHORT}.py", f"burkinafaso_encode_memsafe_{DST_TIP_SHORT}.py"),
    (f"mali_finish_from_emb_{SRC_TIP_SHORT}.py", f"burkinafaso_finish_from_emb_{DST_TIP_SHORT}.py"),
    (f"mali_stream_graph_parts_{SRC_TIP_SHORT}.py", f"burkinafaso_stream_graph_parts_{DST_TIP_SHORT}.py"),
    (f"mali_package_memsafe_{SRC_TIP_SHORT}.py", f"burkinafaso_package_memsafe_{DST_TIP_SHORT}.py"),
    ("mali_upload.py", "burkinafaso_upload.py"),
    ("mali_bm25_smoke.py", "burkinafaso_bm25_smoke.py"),
    ("mali_write_publish_report.py", "burkinafaso_write_publish_report.py"),
    (f"mali_orchestrator_{SRC_TIP_SHORT}.py", f"burkinafaso_orchestrator_{DST_TIP_SHORT}.py"),
]

def adapt(text: str) -> str:
    t = text
    # tips: full before short (short is prefix of full)
    t = t.replace(SRC_TIP_FULL, DST_TIP_FULL)
    t = t.replace(SRC_TIP_SHORT, DST_TIP_SHORT)
    t = t.replace(SRC_REPO, DST_REPO)
    t = t.replace(SRC_TARGET, DST_TARGET)
    t = t.replace(f"ipfs_{SRC_SLUG}_laws_ir", f"ipfs_{DST_SLUG}_laws_ir")
    for kind in [
        "filtered_", "corpus_", "bm25_spill_", "corpus_parts_", "orchestrator_",
        "encode_", "finish_", "stream_graph_", "package_stream_", "package_memsafe_",
        "upload_", "bm25_smoke_", "publish_", "filter_", "build_", "graph_parts_",
        "corpus_stream_", "normalization", "gate_sample_",
    ]:
        t = t.replace(f"{SRC_SLUG}_{kind}", f"{DST_SLUG}_{kind}")
    t = t.replace(f"embeddings/{SRC_SLUG}_", f"embeddings/{DST_SLUG}_")
    t = t.replace(chr(34) + SRC_SLUG + chr(34), chr(34) + DST_SLUG + chr(34))
    t = t.replace("SLUG = " + chr(34) + SRC_SLUG + chr(34), "SLUG = " + chr(34) + DST_SLUG + chr(34))
    # Display names before slug underscore sweep
    t = t.replace("French (Mali)", "French (Burkina Faso)")
    t = t.replace("French/Latin (ML)", "French/Latin (BF)")
    t = t.replace("French Mali", "French Burkina Faso")
    t = t.replace("Mali ASCII", "Burkina Faso ASCII")
    t = t.replace("Mali IR", "Burkina Faso IR")
    t = t.replace("Mali FIRST_IR", "Burkina Faso FIRST_IR")
    t = t.replace("Mali filtered", "Burkina Faso filtered")
    t = t.replace("Mali corpus", "Burkina Faso corpus")
    t = t.replace("BM25 smoke for Mali", "BM25 smoke for Burkina Faso")
    t = t.replace("Upload Mali", "Upload Burkina Faso")
    t = t.replace("Memory-safe Mali", "Memory-safe Burkina Faso")
    t = t.replace('"name": "Mali"', '"name": "Burkina Faso"')
    t = t.replace("# Mali ", "# Burkina Faso ")
    t = t.replace("Mali", "Burkina Faso")
    t = t.replace("Malin-only", "Burkinabe-only")
    t = t.replace("Malin", "Burkinabe")
    t = t.replace("mali_ranked", "burkinafaso_ranked")
    t = t.replace("mali_gate", "burkinafaso_gate")
    t = t.replace("mali_", "burkinafaso_")
    t = t.replace("ipfs_mali", "ipfs_burkinafaso")
    # country code leftovers in smoke notes
    t = t.replace("www/gov/ml", "www/gov/bf")
    t = t.replace('"ml"', '"bf"')
    t = t.replace("lang=fr; French Burkina Faso", "lang=fr; French Burkina Faso / Burkinabe")
    # floors
    t = t.replace(f"FLOOR_LAWS, FLOOR_ARTS = {SRC_FLOOR_L}, {SRC_FLOOR_A}", f"FLOOR_LAWS, FLOOR_ARTS = {FLOOR_LAWS}, {FLOOR_ARTS}")
    t = t.replace(f"{SRC_FLOOR_L}/{SRC_FLOOR_A}", f"{FLOOR_LAWS}/{FLOOR_ARTS}")
    t = t.replace(f"{SRC_FLOOR_L}, {SRC_FLOOR_A}", f"{FLOOR_LAWS}, {FLOOR_ARTS}")
    t = t.replace(f"or {SRC_FLOOR_L}", f"or {FLOOR_LAWS}")
    t = t.replace(f"or {SRC_FLOOR_A}", f"or {FLOOR_ARTS}")
    t = t.replace(f"n_laws_source\": int(pack.get(\"n_laws\") or {SRC_FLOOR_L})", f"n_laws_source\": int(pack.get(\"n_laws\") or {FLOOR_LAWS})")
    t = t.replace(f"n_articles_source\": int(pack.get(\"n_articles\") or {SRC_FLOOR_A})", f"n_articles_source\": int(pack.get(\"n_articles\") or {FLOOR_ARTS})")
    t = t.replace("RECONFIRM_FINAL", "FIRST_IR")
    return t

for src_name, dst_name in files:
    src = ROOT / src_name
    if not src.is_file():
        print(f"MISSING {src}")
        continue
    (ROOT / dst_name).write_text(adapt(src.read_text()))
    print(f"wrote {dst_name}")
print("done")
