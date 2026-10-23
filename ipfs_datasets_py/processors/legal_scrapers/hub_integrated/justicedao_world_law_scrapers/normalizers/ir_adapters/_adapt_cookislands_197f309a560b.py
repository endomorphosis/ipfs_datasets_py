#!/usr/bin/env python3
"""Adapt the Comoros memsafe FIRST_IR pack to Cook Islands tip 197f309a560b.

English Cook Islands; FIRST_IR; HOLD 0 STRICT; soft never-thin ON; SKIP_US; Italy BLOCKED.
Queue after-KM: SM -> TM -> GD -> MG -> PS.
"""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
from pathlib import Path

SRC_TIP_FULL = "bf29adc2829759e4b1edf73f0ca0d6059aa2daf1"
SRC_TIP_SHORT = "bf29adc28297"
DST_TIP_FULL = "197f309a560bd462f3547aa841ba4ff65af80367"
DST_TIP_SHORT = "197f309a560b"
SRC_SLUG = "comoros"
DST_SLUG = "cookislands"
SRC_REPO = "endomorphosis/ipfs_comoros_laws"
DST_REPO = "endomorphosis/ipfs_cookislands_laws"
SRC_TARGET = "justicedao/ipfs_comoros_laws_ir"
DST_TARGET = "justicedao/ipfs_cookislands_laws_ir"
SRC_FLOOR_L, SRC_FLOOR_A = 117, 15155
FLOOR_LAWS, FLOOR_ARTS = 1036, 14855
ROOT = Path("/workspace/do_ir_resume")

files = [
    ("comoros_soft_filter.py", "cookislands_soft_filter.py"),
    (f"comoros_corpus_stream_{SRC_TIP_SHORT}.py", f"cookislands_corpus_stream_{DST_TIP_SHORT}.py"),
    (f"comoros_encode_memsafe_{SRC_TIP_SHORT}.py", f"cookislands_encode_memsafe_{DST_TIP_SHORT}.py"),
    (f"comoros_finish_from_emb_{SRC_TIP_SHORT}.py", f"cookislands_finish_from_emb_{DST_TIP_SHORT}.py"),
    (f"comoros_stream_graph_parts_{SRC_TIP_SHORT}.py", f"cookislands_stream_graph_parts_{DST_TIP_SHORT}.py"),
    (f"comoros_package_memsafe_{SRC_TIP_SHORT}.py", f"cookislands_package_memsafe_{DST_TIP_SHORT}.py"),
    ("comoros_upload.py", "cookislands_upload.py"),
    ("comoros_bm25_smoke.py", "cookislands_bm25_smoke.py"),
    ("comoros_write_publish_report.py", "cookislands_write_publish_report.py"),
    (f"comoros_orchestrator_{SRC_TIP_SHORT}.py", f"cookislands_orchestrator_{DST_TIP_SHORT}.py"),
]

def adapt(text: str) -> str:
    replacements = [
        (SRC_TIP_FULL, DST_TIP_FULL),
        (SRC_TIP_SHORT, DST_TIP_SHORT),
        (SRC_REPO, DST_REPO),
        (SRC_TARGET, DST_TARGET),
        (f"ipfs_{SRC_SLUG}_laws_ir", f"ipfs_{DST_SLUG}_laws_ir"),
        (f"ipfs_{SRC_SLUG}_laws", f"ipfs_{DST_SLUG}_laws"),
        ("HOLD 0 STRICT after-AD (KM→CK→SM→TM→GD→MG→PS)", "HOLD 0 STRICT after-KM (SM→TM→GD→MG→PS)"),
        ("after-AD (KM→CK→SM→TM→GD→MG→PS)", "after-KM (SM→TM→GD→MG→PS)"),
        ("after-AD", "after-KM"),
        ("www/gov/km", "www/gov/ck"),
        ("/km", "/ck"),
        ('"km"', '"ck"'),
        ("KM-attested", "CK-attested"),
        ("(KM)", "(CK)"),
        ("French (Comoros)", "English (Cook Islands)"),
        ("French/Latin (KM)", "English/Latin (CK)"),
        ("French Comoros", "English Cook Islands"),
        ("Comorian", "Cook Islands"),
        ("Comoros", "Cook Islands"),
        ("comoros", "cookislands"),
        ("French", "English"),
        ("fr;", "en;"),
        ("fr)", "en)"),
        ("117/15155", "1036/14855"),
        ("117 / 15155", "1036 / 14855"),
        ("117, 15155", "1036, 14855"),
        ("117", "1036"),
        ("15155", "14855"),
        ("FIRST_IR", "FIRST_IR"),
    ]
    for a, b in replacements:
        text = text.replace(a, b)
    return text

for src_name, dst_name in files:
    src = ROOT / src_name
    if not src.is_file():
        raise FileNotFoundError(src)
    (ROOT / dst_name).write_text(adapt(src.read_text(encoding="utf-8")), encoding="utf-8")
    print(f"wrote {dst_name}")
print("done")
