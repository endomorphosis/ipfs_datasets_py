# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
from pathlib import Path

SRC_TIP_FULL = "88ecd571972f4e066ed6bf91d4ac97f427902563"
SRC_TIP_SHORT = "88ecd571972f"
DST_TIP_FULL = "9a0cf396c0864b5d5ebd226df621505ee23bb853"
DST_TIP_SHORT = "9a0cf396c086"
SRC_SLUG = "hungary"
DST_SLUG = "liechtenstein"
SRC_REPO = "endomorphosis/ipfs_hungary_laws"
DST_REPO = "endomorphosis/ipfs_liechtenstein_laws"
SRC_TARGET = "justicedao/ipfs_hungary_laws_ir"
DST_TARGET = "justicedao/ipfs_liechtenstein_laws_ir"
FLOOR_LAWS, FLOOR_ARTS = 15800, 183038
SRC_FLOOR_L, SRC_FLOOR_A = 380, 10520

ROOT = Path("/workspace/do_ir_resume")

files = [
    ("hungary_soft_filter.py", "liechtenstein_soft_filter.py"),
    (f"hungary_corpus_stream_{SRC_TIP_SHORT}.py", f"liechtenstein_corpus_stream_{DST_TIP_SHORT}.py"),
    (f"hungary_encode_memsafe_{SRC_TIP_SHORT}.py", f"liechtenstein_encode_memsafe_{DST_TIP_SHORT}.py"),
    (f"hungary_finish_from_emb_{SRC_TIP_SHORT}.py", f"liechtenstein_finish_from_emb_{DST_TIP_SHORT}.py"),
    (f"hungary_stream_graph_parts_{SRC_TIP_SHORT}.py", f"liechtenstein_stream_graph_parts_{DST_TIP_SHORT}.py"),
    (f"hungary_package_memsafe_{SRC_TIP_SHORT}.py", f"liechtenstein_package_memsafe_{DST_TIP_SHORT}.py"),
    ("hungary_upload.py", "liechtenstein_upload.py"),
    ("hungary_bm25_smoke.py", "liechtenstein_bm25_smoke.py"),
    ("hungary_write_publish_report.py", "liechtenstein_write_publish_report.py"),
    (f"hungary_orchestrator_{SRC_TIP_SHORT}.py", f"liechtenstein_orchestrator_{DST_TIP_SHORT}.py"),
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
    t = t.replace("Hungary", "Liechtenstein")
    t = t.replace("Hungarian legal corpus (Latin script; ASCII after diacritic fold)",
                  "German (Liechtenstein) legal corpus (Latin script; ASCII after diacritic fold)")
    t = t.replace("Hungarian Latin", "German/Latin (LI)")
    t = t.replace("Hungarian (Latin)", "German (Liechtenstein)")
    t = t.replace("Hungarian-only may empty FTS; prefer years + attested Latin",
                  "German-only diacritic-heavy may thin FTS; prefer years + attested Latin/German stems")
    t = t.replace("Prefer years + attested Latin legal stems; Hungarian-only may empty FTS",
                  "Prefer years + attested Latin/German legal stems; German-only may empty FTS")
    t = t.replace("Hungarian corpus", "Liechtenstein corpus")
    t = t.replace("Hungarian legal corpus", "German (Liechtenstein) legal corpus")
    t = t.replace("hungary_", "liechtenstein_")
    t = t.replace("ipfs_hungary", "ipfs_liechtenstein")
    t = t.replace(f"FLOOR_LAWS, FLOOR_ARTS = {SRC_FLOOR_L}, {SRC_FLOOR_A}", f"FLOOR_LAWS, FLOOR_ARTS = {FLOOR_LAWS}, {FLOOR_ARTS}")
    t = t.replace(f"{SRC_FLOOR_L}/{SRC_FLOOR_A}", f"{FLOOR_LAWS}/{FLOOR_ARTS}")
    t = t.replace(f"{SRC_FLOOR_L}, {SRC_FLOOR_A}", f"{FLOOR_LAWS}, {FLOOR_ARTS}")
    t = t.replace(f"or {SRC_FLOOR_L}", f"or {FLOOR_LAWS}")
    t = t.replace(f"or {SRC_FLOOR_A}", f"or {FLOOR_ARTS}")
    t = t.replace(f"n_laws_source\": int(pack.get(\"n_laws\") or {SRC_FLOOR_L})", f"n_laws_source\": int(pack.get(\"n_laws\") or {FLOOR_LAWS})")
    t = t.replace(f"n_articles_source\": int(pack.get(\"n_articles\") or {SRC_FLOOR_A})", f"n_articles_source\": int(pack.get(\"n_articles\") or {FLOOR_ARTS})")
    t = t.replace("RECONFIRM_FINAL", "FIRST_IR")
    t = t.replace("lang=hu", "lang=de")
    return t

for src_name, dst_name in files:
    src = ROOT / src_name
    if not src.is_file():
        print(f"MISSING {src}")
        continue
    (ROOT / dst_name).write_text(adapt(src.read_text()))
    print(f"wrote {dst_name}")
print("done")
