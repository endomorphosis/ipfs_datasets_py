#!/usr/bin/env python3
"""Adapt mali memsafe pack → chad FIRST_IR tip cfef0584fb76 (WAVE END after-ME).

French → French; Mali → Chad; ML → TD. Floor 99/19425. FIRST_IR.
justicedao/ipfs_chad_laws_ir does NOT exist yet.
"""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
from pathlib import Path

SRC_TIP_FULL = "dea9e0d1bd072599be5d21a54d075d6cb181a1f1"
SRC_TIP_SHORT = "dea9e0d1bd07"
DST_TIP_FULL = "cfef0584fb76ace64f7b1fd9121caaf9aba2e4ec"
DST_TIP_SHORT = "cfef0584fb76"
SRC_SLUG = "mali"
DST_SLUG = "chad"
SRC_REPO = "endomorphosis/ipfs_mali_laws"
DST_REPO = "endomorphosis/ipfs_chad_laws"
SRC_TARGET = "justicedao/ipfs_mali_laws_ir"
DST_TARGET = "justicedao/ipfs_chad_laws_ir"
FLOOR_LAWS, FLOOR_ARTS = 99, 19425
SRC_FLOOR_L, SRC_FLOOR_A = 205, 29924

ROOT = Path("/workspace/do_ir_resume")

files = [
    ("mali_soft_filter.py", "chad_soft_filter.py"),
    (f"mali_corpus_stream_{SRC_TIP_SHORT}.py", f"chad_corpus_stream_{DST_TIP_SHORT}.py"),
    (f"mali_encode_memsafe_{SRC_TIP_SHORT}.py", f"chad_encode_memsafe_{DST_TIP_SHORT}.py"),
    (f"mali_finish_from_emb_{SRC_TIP_SHORT}.py", f"chad_finish_from_emb_{DST_TIP_SHORT}.py"),
    (f"mali_stream_graph_parts_{SRC_TIP_SHORT}.py", f"chad_stream_graph_parts_{DST_TIP_SHORT}.py"),
    (f"mali_package_memsafe_{SRC_TIP_SHORT}.py", f"chad_package_memsafe_{DST_TIP_SHORT}.py"),
    ("mali_upload.py", "chad_upload.py"),
    ("mali_bm25_smoke.py", "chad_bm25_smoke.py"),
    ("mali_write_publish_report.py", "chad_write_publish_report.py"),
    (f"mali_orchestrator_{SRC_TIP_SHORT}.py", f"chad_orchestrator_{DST_TIP_SHORT}.py"),
]


def adapt(text: str) -> str:
    t = text
    t = t.replace(SRC_TIP_FULL, DST_TIP_FULL)
    t = t.replace(SRC_TIP_SHORT, DST_TIP_SHORT)
    t = t.replace(SRC_REPO, DST_REPO)
    t = t.replace(SRC_TARGET, DST_TARGET)
    t = t.replace(f"ipfs_{SRC_SLUG}_laws_ir", f"ipfs_{DST_SLUG}_laws_ir")
    t = t.replace(f"ipfs_{SRC_SLUG}_laws", f"ipfs_{DST_SLUG}_laws")

    for kind in [
        "filtered_", "corpus_parts_", "corpus_stream_", "bm25_spill_", "corpus_",
        "orchestrator_", "encode_", "finish_", "stream_graph_", "package_stream_",
        "package_memsafe_", "upload_", "bm25_smoke_", "publish_", "filter_",
        "build_", "graph_parts_", "normalization", "gate_sample_", "soft_filter",
    ]:
        t = t.replace(f"{SRC_SLUG}_{kind}", f"{DST_SLUG}_{kind}")

    t = t.replace(f"embeddings/{SRC_SLUG}_", f"embeddings/{DST_SLUG}_")
    t = t.replace(chr(34) + SRC_SLUG + chr(34), chr(34) + DST_SLUG + chr(34))
    t = t.replace("SLUG = " + chr(34) + SRC_SLUG + chr(34), "SLUG = " + chr(34) + DST_SLUG + chr(34))

    # Display / language before blanket
    t = t.replace("French (Mali)", "French (Chad)")
    t = t.replace("French/Latin (ML)", "French/Latin (TD)")
    t = t.replace("French Mali", "French Chad")
    t = t.replace("Mali FIRST_IR", "Chad FIRST_IR")
    t = t.replace("Mali IR", "Chad IR")
    t = t.replace("Mali filtered", "Chad filtered")
    t = t.replace("Mali corpus", "Chad corpus")
    t = t.replace("BM25 smoke for Mali", "BM25 smoke for Chad")
    t = t.replace("Upload Mali", "Upload Chad")
    t = t.replace("Memory-safe Mali", "Memory-safe Chad")
    t = t.replace("Memsafe Mali", "Memsafe Chad")
    t = t.replace("Soft filter for Mali", "Soft filter for Chad")
    t = t.replace('"name": "Mali"', '"name": "Chad"')
    t = t.replace("# Mali ", "# Chad ")
    t = t.replace("Malian", "Chadian")
    t = t.replace("Malin-only", "Chadian-only")
    t = t.replace("mali_ranked", "chad_ranked")
    t = t.replace("mali_gate", "chad_gate")
    t = t.replace("mali_pass", "chad_pass")
    t = t.replace("mali_encode_done", "chad_encode_done")
    t = t.replace("www/gov/ml", "www/gov/td")
    t = t.replace('"ml"', '"td"')  # query token if present as string
    # Careful: only standalone ML country code leftovers in notes
    t = t.replace(" (ML)", " (TD)")
    t = t.replace("Mali", "Chad")
    t = t.replace("mali_", "chad_")
    t = t.replace("ipfs_mali", "ipfs_chad")

    t = t.replace(
        f"FLOOR_LAWS, FLOOR_ARTS = {SRC_FLOOR_L}, {SRC_FLOOR_A}",
        f"FLOOR_LAWS, FLOOR_ARTS = {FLOOR_LAWS}, {FLOOR_ARTS}",
    )
    t = t.replace(f"{SRC_FLOOR_L}/{SRC_FLOOR_A}", f"{FLOOR_LAWS}/{FLOOR_ARTS}")
    t = t.replace(f"{SRC_FLOOR_L}, {SRC_FLOOR_A}", f"{FLOOR_LAWS}, {FLOOR_ARTS}")
    t = t.replace(f"or {SRC_FLOOR_L}", f"or {FLOOR_LAWS}")
    t = t.replace(f"or {SRC_FLOOR_A}", f"or {FLOOR_ARTS}")
    t = t.replace(
        f'n_laws_source": int(pack.get("n_laws") or {SRC_FLOOR_L})',
        f'n_laws_source": int(pack.get("n_laws") or {FLOOR_LAWS})',
    )
    t = t.replace(
        f'n_articles_source": int(pack.get("n_articles") or {SRC_FLOOR_A})',
        f'n_articles_source": int(pack.get("n_articles") or {FLOOR_ARTS})',
    )
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
