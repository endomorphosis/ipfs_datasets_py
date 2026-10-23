#!/usr/bin/env python3
"""Adapt the Grenada memsafe FIRST_IR pack to Anguilla tip be6ea6899994.
English (Anguilla); FIRST_IR; HOLD 0 STRICT; soft never-thin ON;
SKIP_US; Italy BLOCKED. Queue after-PS: CG -> KG -> GA -> NR -> TG -> MS -> HT -> VG -> SX -> CD -> BM.
"""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
from pathlib import Path
SRC_TIP_FULL = "50132c510a29949b3ed39d907404b0b2ed51aeab"
SRC_TIP_SHORT = "50132c510a29"
DST_TIP_FULL = "be6ea6899994e5ccea4a59239d8a4cc3ee67b31e"
DST_TIP_SHORT = "be6ea6899994"
SRC_SLUG = "grenada"
DST_SLUG = "anguilla"
SRC_REPO = "endomorphosis/ipfs_grenada_laws"
DST_REPO = "endomorphosis/ipfs_anguilla_laws"
SRC_TARGET = "justicedao/ipfs_grenada_laws_ir"
DST_TARGET = "justicedao/ipfs_anguilla_laws_ir"
FLOOR_LAWS, FLOOR_ARTS = 175, 12203
ROOT = Path("/workspace/do_ir_resume")
files = [
    ("grenada_soft_filter.py", "anguilla_soft_filter.py"),
    (f"grenada_corpus_stream_{SRC_TIP_SHORT}.py", f"anguilla_corpus_stream_{DST_TIP_SHORT}.py"),
    (f"grenada_encode_memsafe_{SRC_TIP_SHORT}.py", f"anguilla_encode_memsafe_{DST_TIP_SHORT}.py"),
    (f"grenada_finish_from_emb_{SRC_TIP_SHORT}.py", f"anguilla_finish_from_emb_{DST_TIP_SHORT}.py"),
    (f"grenada_stream_graph_parts_{SRC_TIP_SHORT}.py", f"anguilla_stream_graph_parts_{DST_TIP_SHORT}.py"),
    (f"grenada_package_memsafe_{SRC_TIP_SHORT}.py", f"anguilla_package_memsafe_{DST_TIP_SHORT}.py"),
    ("grenada_upload.py", "anguilla_upload.py"),
    ("grenada_bm25_smoke.py", "anguilla_bm25_smoke.py"),
    ("grenada_write_publish_report.py", "anguilla_write_publish_report.py"),
    (f"grenada_orchestrator_{SRC_TIP_SHORT}.py", f"anguilla_orchestrator_{DST_TIP_SHORT}.py"),
]
def adapt(text: str) -> str:
    replacements = [
        (SRC_TIP_FULL, DST_TIP_FULL), (SRC_TIP_SHORT, DST_TIP_SHORT),
        (SRC_REPO, DST_REPO), (SRC_TARGET, DST_TARGET),
        (f"ipfs_{SRC_SLUG}_laws_ir", f"ipfs_{DST_SLUG}_laws_ir"),
        (f"ipfs_{SRC_SLUG}_laws", f"ipfs_{DST_SLUG}_laws"),
        ("HOLD 0 STRICT after-TM (MG→PS)", "HOLD 0 STRICT after-PS (CG→KG→GA→NR→TG→MS→HT→VG→SX→CD→BM)"),
        ("after-TM (MG→PS)", "after-PS (CG→KG→GA→NR→TG→MS→HT→VG→SX→CD→BM)"),
        ("after-TM", "after-PS"),
        ("www/gov/gd", "www/gov/ai"), ("/gd", "/ai"), ('"gd"', '"ai"'),
        ("GD-attested", "AI-attested"), ("(GD)", "(AI)"),
        ("English (Grenada)", "English (Anguilla)"),
        ("English Grenada", "English Anguilla"), ("Grenada", "Anguilla"),
        ("grenada", "anguilla"),
        ("150/13755", "175/12203"), ("150 / 13755", "175 / 12203"),
        ("150, 13755", "175, 12203"), ("150", "175"), ("13755", "12203"),
    ]
    for a, b in replacements: text = text.replace(a, b)
    return text
for src_name, dst_name in files:
    src = ROOT / src_name
    if not src.is_file(): raise FileNotFoundError(src)
    (ROOT / dst_name).write_text(adapt(src.read_text(encoding="utf-8")), encoding="utf-8")
    print(f"wrote {dst_name}")
print("done")
