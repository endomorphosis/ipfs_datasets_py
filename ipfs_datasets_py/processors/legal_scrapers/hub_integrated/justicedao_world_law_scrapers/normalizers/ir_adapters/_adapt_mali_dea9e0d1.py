# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
from pathlib import Path

SRC_TIP_FULL = "d97f455627dcfc68cdf0315881196578d225fe0f"
SRC_TIP_SHORT = "d97f455627dc"
DST_TIP_FULL = "dea9e0d1bd072599be5d21a54d075d6cb181a1f1"
DST_TIP_SHORT = "dea9e0d1bd07"
SRC_SLUG = "mauritania"
DST_SLUG = "mali"
SRC_REPO = "endomorphosis/ipfs_mauritania_laws"
DST_REPO = "endomorphosis/ipfs_mali_laws"
SRC_TARGET = "justicedao/ipfs_mauritania_laws_ir"
DST_TARGET = "justicedao/ipfs_mali_laws_ir"
FLOOR_LAWS, FLOOR_ARTS = 205, 29924
SRC_FLOOR_L, SRC_FLOOR_A = 293, 61741

ROOT = Path("/workspace/do_ir_resume")

files = [
    ("mauritania_soft_filter.py", "mali_soft_filter.py"),
    (f"mauritania_corpus_stream_{SRC_TIP_SHORT}.py", f"mali_corpus_stream_{DST_TIP_SHORT}.py"),
    (f"mauritania_encode_memsafe_{SRC_TIP_SHORT}.py", f"mali_encode_memsafe_{DST_TIP_SHORT}.py"),
    (f"mauritania_finish_from_emb_{SRC_TIP_SHORT}.py", f"mali_finish_from_emb_{DST_TIP_SHORT}.py"),
    (f"mauritania_stream_graph_parts_{SRC_TIP_SHORT}.py", f"mali_stream_graph_parts_{DST_TIP_SHORT}.py"),
    (f"mauritania_package_memsafe_{SRC_TIP_SHORT}.py", f"mali_package_memsafe_{DST_TIP_SHORT}.py"),
    ("mauritania_upload.py", "mali_upload.py"),
    ("mauritania_bm25_smoke.py", "mali_bm25_smoke.py"),
    ("mauritania_write_publish_report.py", "mali_write_publish_report.py"),
    (f"mauritania_orchestrator_{SRC_TIP_SHORT}.py", f"mali_orchestrator_{DST_TIP_SHORT}.py"),
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
        "corpus_stream_", "normalization", "gate_sample_",
    ]:
        t = t.replace(f"{SRC_SLUG}_{kind}", f"{DST_SLUG}_{kind}")
    t = t.replace(f"embeddings/{SRC_SLUG}_", f"embeddings/{DST_SLUG}_")
    t = t.replace(chr(34) + SRC_SLUG + chr(34), chr(34) + DST_SLUG + chr(34))
    t = t.replace("SLUG = " + chr(34) + SRC_SLUG + chr(34), "SLUG = " + chr(34) + DST_SLUG + chr(34))
    t = t.replace("Mauritania", "Mali")
    t = t.replace("French (Mali) legal corpus (Latin script; ASCII after diacritic fold)",
                  "French (Mali) legal corpus (Latin script; ASCII after diacritic fold)")
    # After Mauritania→Mali, French (Mauritania) became French (Mali) already if we did Mauritania→Mali first
    # Fix notes that referenced Mauritania specifically before the global replace:
    # Global Mauritania→Mali already handled most. Patch residual MR / Malian notes:
    t = t.replace("French/Latin (MR)", "French/Latin (ML)")
    t = t.replace("French (Mauritania)", "French (Mali)")  # safety if any left
    t = t.replace("French-only diacritic-heavy may thin FTS; prefer years + attested Latin/French stems",
                  "French-only diacritic-heavy may thin FTS; prefer years + attested Latin/French stems")
    t = t.replace("Prefer years + attested Latin/French legal stems; French-only may empty FTS",
                  "Prefer years + attested Latin/French legal stems; French-only may empty FTS")
    t = t.replace("Mali corpus", "Mali corpus")  # already correct after replace
    t = t.replace("mauritania_", "mali_")
    t = t.replace("ipfs_mauritania", "ipfs_mali")
    t = t.replace(f"FLOOR_LAWS, FLOOR_ARTS = {SRC_FLOOR_L}, {SRC_FLOOR_A}", f"FLOOR_LAWS, FLOOR_ARTS = {FLOOR_LAWS}, {FLOOR_ARTS}")
    t = t.replace(f"{SRC_FLOOR_L}/{SRC_FLOOR_A}", f"{FLOOR_LAWS}/{FLOOR_ARTS}")
    t = t.replace(f"{SRC_FLOOR_L}, {SRC_FLOOR_A}", f"{FLOOR_LAWS}, {FLOOR_ARTS}")
    t = t.replace(f"or {SRC_FLOOR_L}", f"or {FLOOR_LAWS}")
    t = t.replace(f"or {SRC_FLOOR_A}", f"or {FLOOR_ARTS}")
    t = t.replace(f"n_laws_source\": int(pack.get(\"n_laws\") or {SRC_FLOOR_L})", f"n_laws_source\": int(pack.get(\"n_laws\") or {FLOOR_LAWS})")
    t = t.replace(f"n_articles_source\": int(pack.get(\"n_articles\") or {SRC_FLOOR_A})", f"n_articles_source\": int(pack.get(\"n_articles\") or {FLOOR_ARTS})")
    # Keep FIRST_IR (mauritania already has FIRST_IR)
    t = t.replace("RECONFIRM_FINAL", "FIRST_IR")
    t = t.replace("lang=fr", "lang=fr")
    return t

for src_name, dst_name in files:
    src = ROOT / src_name
    if not src.is_file():
        print(f"MISSING {src}")
        continue
    (ROOT / dst_name).write_text(adapt(src.read_text()))
    print(f"wrote {dst_name}")
print("done")
