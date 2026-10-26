#!/usr/bin/env python3
"""Adapt turks_caicos memsafe pack → bhutan FIRST_IR tip 796412e31957.

EN → EN; Turks and Caicos → Bhutan; TC → BT. Floor 197/17392. FIRST_IR.
justicedao/ipfs_bhutan_laws_ir does NOT exist yet.
HOLD 0 STRICT; soft never-thin ON; SKIP_US; Italy BLOCKED.
Queue after: GN→AD→KM→CK→SM→TM→GD→MG→PS.
"""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
from pathlib import Path

SRC_TIP_FULL = "aaafe4d3bed911181c42e6eec64bc350147c5c4a"
SRC_TIP_SHORT = "aaafe4d3bed9"
DST_TIP_FULL = "796412e31957abf8453e80acdb55385dcf73dbc7"
DST_TIP_SHORT = "796412e31957"
SRC_SLUG = "turks_caicos"
DST_SLUG = "bhutan"
SRC_REPO = "endomorphosis/ipfs_turks_caicos_laws"
DST_REPO = "endomorphosis/ipfs_bhutan_laws"
SRC_TARGET = "justicedao/ipfs_turks_caicos_laws_ir"
DST_TARGET = "justicedao/ipfs_bhutan_laws_ir"
FLOOR_LAWS, FLOOR_ARTS = 197, 17392
SRC_FLOOR_L, SRC_FLOOR_A = 178, 19088

ROOT = Path("/workspace/do_ir_resume")

files = [
    ("turks_caicos_soft_filter.py", "bhutan_soft_filter.py"),
    (f"turks_caicos_corpus_stream_{SRC_TIP_SHORT}.py", f"bhutan_corpus_stream_{DST_TIP_SHORT}.py"),
    (f"turks_caicos_encode_memsafe_{SRC_TIP_SHORT}.py", f"bhutan_encode_memsafe_{DST_TIP_SHORT}.py"),
    (f"turks_caicos_finish_from_emb_{SRC_TIP_SHORT}.py", f"bhutan_finish_from_emb_{DST_TIP_SHORT}.py"),
    (f"turks_caicos_stream_graph_parts_{SRC_TIP_SHORT}.py", f"bhutan_stream_graph_parts_{DST_TIP_SHORT}.py"),
    (f"turks_caicos_package_memsafe_{SRC_TIP_SHORT}.py", f"bhutan_package_memsafe_{DST_TIP_SHORT}.py"),
    ("turks_caicos_upload.py", "bhutan_upload.py"),
    ("turks_caicos_bm25_smoke.py", "bhutan_bm25_smoke.py"),
    ("turks_caicos_write_publish_report.py", "bhutan_write_publish_report.py"),
    (f"turks_caicos_orchestrator_{SRC_TIP_SHORT}.py", f"bhutan_orchestrator_{DST_TIP_SHORT}.py"),
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
    t = t.replace("English (Turks and Caicos)", "English (Bhutan)")
    t = t.replace("English (TC)", "English (BT)")
    t = t.replace("English Turks and Caicos", "English Bhutan")
    t = t.replace("Turks and Caicos ASCII", "Bhutan ASCII")
    t = t.replace("Turks and Caicos IR", "Bhutan IR")
    t = t.replace("Turks and Caicos FIRST_IR", "Bhutan FIRST_IR")
    t = t.replace("Turks and Caicos filtered", "Bhutan filtered")
    t = t.replace("Turks and Caicos corpus", "Bhutan corpus")
    t = t.replace("BM25 smoke for Turks and Caicos", "BM25 smoke for Bhutan")
    t = t.replace("Upload Turks and Caicos", "Upload Bhutan")
    t = t.replace("Memory-safe Turks and Caicos", "Memory-safe Bhutan")
    t = t.replace("Memsafe Turks and Caicos", "Memsafe Bhutan")
    t = t.replace("Soft filter for Turks and Caicos", "Soft filter for Bhutan")
    t = t.replace('"name": "Turks and Caicos"', '"name": "Bhutan"')
    t = t.replace("# Turks and Caicos ", "# Bhutan ")
    t = t.replace("Turks and Caicos-only", "Bhutan-only")
    t = t.replace("turks_caicos_ranked", "bhutan_ranked")
    t = t.replace("turks_caicos_gate", "bhutan_gate")
    t = t.replace("turks_caicos_pass", "bhutan_pass")
    t = t.replace("turks_caicos_encode_done", "bhutan_encode_done")
    t = t.replace("turks_caicos_pre_graph", "bhutan_pre_graph")
    t = t.replace("www/gov/tc", "www/gov/bt")
    t = t.replace('"tc"', '"bt"')
    t = t.replace(" (TC)", " (BT)")
    t = t.replace("Caribbean", "Himalayan")
    t = t.replace("Turks and Caicos", "Bhutan")
    t = t.replace("turks_caicos_", "bhutan_")
    t = t.replace("ipfs_turks_caicos", "ipfs_bhutan")
    t = t.replace(SRC_SLUG, DST_SLUG)

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
    # leftover bare floor arts in soft_filter docstring etc
    t = t.replace(str(SRC_FLOOR_A), str(FLOOR_ARTS))
    t = t.replace(str(SRC_FLOOR_L), str(FLOOR_LAWS))
    return t


for src_name, dst_name in files:
    src = ROOT / src_name
    if not src.is_file():
        print(f"MISSING {src}")
        continue
    (ROOT / dst_name).write_text(adapt(src.read_text()))
    print(f"wrote {dst_name}")
print("done")
