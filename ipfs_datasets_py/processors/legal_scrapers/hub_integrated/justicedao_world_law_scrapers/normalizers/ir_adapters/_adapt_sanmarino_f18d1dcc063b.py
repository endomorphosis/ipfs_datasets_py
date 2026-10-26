#!/usr/bin/env python3
"""Adapt the Cook Islands memsafe FIRST_IR pack to San Marino tip f18d1dcc063b.

Italian San Marino; FIRST_IR; HOLD 0 STRICT; soft never-thin ON; SKIP_US; Italy BLOCKED.
Queue after-CK: TM -> GD -> MG -> PS.
"""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
from pathlib import Path

SRC_TIP_FULL = "197f309a560bd462f3547aa841ba4ff65af80367"
SRC_TIP_SHORT = "197f309a560b"
DST_TIP_FULL = "f18d1dcc063b37162cd7c5cad9a86de043578d25"
DST_TIP_SHORT = "f18d1dcc063b"
SRC_SLUG = "cookislands"
DST_SLUG = "sanmarino"
SRC_REPO = "endomorphosis/ipfs_cookislands_laws"
DST_REPO = "endomorphosis/ipfs_sanmarino_laws"
SRC_TARGET = "justicedao/ipfs_cookislands_laws_ir"
DST_TARGET = "justicedao/ipfs_sanmarino_laws_ir"
SRC_FLOOR_L, SRC_FLOOR_A = 1036, 14855
FLOOR_LAWS, FLOOR_ARTS = 4442, 14705
ROOT = Path("/workspace/do_ir_resume")

files = [
    ("cookislands_soft_filter.py", "sanmarino_soft_filter.py"),
    (f"cookislands_corpus_stream_{SRC_TIP_SHORT}.py", f"sanmarino_corpus_stream_{DST_TIP_SHORT}.py"),
    (f"cookislands_encode_memsafe_{SRC_TIP_SHORT}.py", f"sanmarino_encode_memsafe_{DST_TIP_SHORT}.py"),
    (f"cookislands_finish_from_emb_{SRC_TIP_SHORT}.py", f"sanmarino_finish_from_emb_{DST_TIP_SHORT}.py"),
    (f"cookislands_stream_graph_parts_{SRC_TIP_SHORT}.py", f"sanmarino_stream_graph_parts_{DST_TIP_SHORT}.py"),
    (f"cookislands_package_memsafe_{SRC_TIP_SHORT}.py", f"sanmarino_package_memsafe_{DST_TIP_SHORT}.py"),
    ("cookislands_upload.py", "sanmarino_upload.py"),
    ("cookislands_bm25_smoke.py", "sanmarino_bm25_smoke.py"),
    ("cookislands_write_publish_report.py", "sanmarino_write_publish_report.py"),
    (f"cookislands_orchestrator_{SRC_TIP_SHORT}.py", f"sanmarino_orchestrator_{DST_TIP_SHORT}.py"),
]

def adapt(text: str) -> str:
    replacements = [
        (SRC_TIP_FULL, DST_TIP_FULL),
        (SRC_TIP_SHORT, DST_TIP_SHORT),
        (SRC_REPO, DST_REPO),
        (SRC_TARGET, DST_TARGET),
        (f"ipfs_{SRC_SLUG}_laws_ir", f"ipfs_{DST_SLUG}_laws_ir"),
        (f"ipfs_{SRC_SLUG}_laws", f"ipfs_{DST_SLUG}_laws"),
        ("HOLD 0 STRICT after-KM (SM→TM→GD→MG→PS)", "HOLD 0 STRICT after-CK (TM→GD→MG→PS)"),
        ("after-KM (SM→TM→GD→MG→PS)", "after-CK (TM→GD→MG→PS)"),
        ("after-KM", "after-CK"),
        ("www/gov/ck", "www/gov/sm"),
        ("/ck", "/sm"),
        ('"ck"', '"sm"'),
        ("CK-attested", "SM-attested"),
        ("(CK)", "(SM)"),
        ("English (Cook Islands)", "Italian (San Marino)"),
        ("English/Latin (CK)", "Italian/Latin (SM)"),
        ("English Cook Islands", "Italian San Marino"),
        ("Cook Islands", "San Marino"),
        ("cookislands", "sanmarino"),
        ("English", "Italian"),
        ("en;", "it;"),
        ("en)", "it)"),
        ("1036/14855", "4442/14705"),
        ("1036 / 14855", "4442 / 14705"),
        ("1036, 14855", "4442, 14705"),
        ("1036", "4442"),
        ("14855", "14705"),
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
