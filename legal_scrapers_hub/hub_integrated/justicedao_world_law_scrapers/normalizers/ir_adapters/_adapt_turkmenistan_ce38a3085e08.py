#!/usr/bin/env python3
"""Adapt the San Marino memsafe FIRST_IR pack to Turkmenistan tip ce38a3085e08.

Russian (Cyrillic) Turkmenistan; FIRST_IR; HOLD 0 STRICT; soft never-thin ON;
SKIP_US; Italy BLOCKED. Queue after-SM: GD -> MG -> PS.
"""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
from pathlib import Path

SRC_TIP_FULL = "f18d1dcc063b37162cd7c5cad9a86de043578d25"
SRC_TIP_SHORT = "f18d1dcc063b"
DST_TIP_FULL = "ce38a3085e088c63199c8df68f15274c86755d74"
DST_TIP_SHORT = "ce38a3085e08"
SRC_SLUG = "sanmarino"
DST_SLUG = "turkmenistan"
SRC_REPO = "endomorphosis/ipfs_sanmarino_laws"
DST_REPO = "endomorphosis/ipfs_turkmenistan_laws"
SRC_TARGET = "justicedao/ipfs_sanmarino_laws_ir"
DST_TARGET = "justicedao/ipfs_turkmenistan_laws_ir"
SRC_FLOOR_L, SRC_FLOOR_A = 4442, 14705
FLOOR_LAWS, FLOOR_ARTS = 422, 14191
ROOT = Path("/workspace/do_ir_resume")

files = [
    ("sanmarino_soft_filter.py", "turkmenistan_soft_filter.py"),
    (f"sanmarino_corpus_stream_{SRC_TIP_SHORT}.py", f"turkmenistan_corpus_stream_{DST_TIP_SHORT}.py"),
    (f"sanmarino_encode_memsafe_{SRC_TIP_SHORT}.py", f"turkmenistan_encode_memsafe_{DST_TIP_SHORT}.py"),
    (f"sanmarino_finish_from_emb_{SRC_TIP_SHORT}.py", f"turkmenistan_finish_from_emb_{DST_TIP_SHORT}.py"),
    (f"sanmarino_stream_graph_parts_{SRC_TIP_SHORT}.py", f"turkmenistan_stream_graph_parts_{DST_TIP_SHORT}.py"),
    (f"sanmarino_package_memsafe_{SRC_TIP_SHORT}.py", f"turkmenistan_package_memsafe_{DST_TIP_SHORT}.py"),
    ("sanmarino_upload.py", "turkmenistan_upload.py"),
    ("sanmarino_bm25_smoke.py", "turkmenistan_bm25_smoke.py"),
    ("sanmarino_write_publish_report.py", "turkmenistan_write_publish_report.py"),
    (f"sanmarino_orchestrator_{SRC_TIP_SHORT}.py", f"turkmenistan_orchestrator_{DST_TIP_SHORT}.py"),
]

def adapt(text: str) -> str:
    replacements = [
        (SRC_TIP_FULL, DST_TIP_FULL),
        (SRC_TIP_SHORT, DST_TIP_SHORT),
        (SRC_REPO, DST_REPO),
        (SRC_TARGET, DST_TARGET),
        (f"ipfs_{SRC_SLUG}_laws_ir", f"ipfs_{DST_SLUG}_laws_ir"),
        (f"ipfs_{SRC_SLUG}_laws", f"ipfs_{DST_SLUG}_laws"),
        ("HOLD 0 STRICT after-CK (TM→GD→MG→PS)", "HOLD 0 STRICT after-SM (GD→MG→PS)"),
        ("after-CK (TM→GD→MG→PS)", "after-SM (GD→MG→PS)"),
        ("after-CK", "after-SM"),
        ("www/gov/sm", "www/gov/tm"),
        ("/sm", "/tm"),
        ('"sm"', '"tm"'),
        ("SM-attested", "TM-attested"),
        ("(SM)", "(TM)"),
        ("Italian (San Marino)", "Russian (Turkmenistan)"),
        ("Italian/Latin (SM)", "Russian/Cyrillic (TM)"),
        ("Italian San Marino", "Russian Turkmenistan"),
        ("San Marino", "Turkmenistan"),
        ("sanmarino", "turkmenistan"),
        ("Italian", "Russian"),
        ("it;", "ru;"),
        ("it)", "ru)"),
        ("4442/14705", "422/14191"),
        ("4442 / 14705", "422 / 14191"),
        ("4442, 14705", "422, 14191"),
        ("4442", "422"),
        ("14705", "14191"),
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
