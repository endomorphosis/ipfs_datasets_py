#!/usr/bin/env python3
"""Adapt the Madagascar memsafe FIRST_IR pack to Palestine tip 3dfb5eba2ced.

Arabic Palestine; FIRST_IR; HOLD 0 STRICT; soft never-thin ON; SKIP_US; Italy BLOCKED.
Queue after-MG: WAVE END after PS.
"""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
from pathlib import Path

SRC_TIP_FULL = "f9491673968734845a250c00fbf2f0ca6d49a3c8"
SRC_TIP_SHORT = "f94916739687"
DST_TIP_FULL = "3dfb5eba2ced9f2756bd35686f8e2dd3498ebfb1"
DST_TIP_SHORT = "3dfb5eba2ced"
SRC_SLUG = "madagascar"
DST_SLUG = "palestine"
SRC_REPO = "endomorphosis/ipfs_madagascar_laws"
DST_REPO = "endomorphosis/ipfs_palestine_laws"
SRC_TARGET = "justicedao/ipfs_madagascar_laws_ir"
DST_TARGET = "justicedao/ipfs_palestine_laws_ir"
SRC_FLOOR_L, SRC_FLOOR_A = 225, 13117
FLOOR_LAWS, FLOOR_ARTS = 3178, 12820
ROOT = Path("/workspace/do_ir_resume")

files = [
    ("madagascar_soft_filter.py", "palestine_soft_filter.py"),
    (f"madagascar_corpus_stream_{SRC_TIP_SHORT}.py", f"palestine_corpus_stream_{DST_TIP_SHORT}.py"),
    (f"madagascar_encode_memsafe_{SRC_TIP_SHORT}.py", f"palestine_encode_memsafe_{DST_TIP_SHORT}.py"),
    (f"madagascar_finish_from_emb_{SRC_TIP_SHORT}.py", f"palestine_finish_from_emb_{DST_TIP_SHORT}.py"),
    (f"madagascar_stream_graph_parts_{SRC_TIP_SHORT}.py", f"palestine_stream_graph_parts_{DST_TIP_SHORT}.py"),
    (f"madagascar_package_memsafe_{SRC_TIP_SHORT}.py", f"palestine_package_memsafe_{DST_TIP_SHORT}.py"),
    ("madagascar_upload.py", "palestine_upload.py"),
    ("madagascar_bm25_smoke.py", "palestine_bm25_smoke.py"),
    ("madagascar_write_publish_report.py", "palestine_write_publish_report.py"),
    (f"madagascar_orchestrator_{SRC_TIP_SHORT}.py", f"palestine_orchestrator_{DST_TIP_SHORT}.py"),
]

def adapt(text: str) -> str:
    replacements = [
        (SRC_TIP_FULL, DST_TIP_FULL),
        (SRC_TIP_SHORT, DST_TIP_SHORT),
        (SRC_REPO, DST_REPO),
        (SRC_TARGET, DST_TARGET),
        (f"ipfs_{SRC_SLUG}_laws_ir", f"ipfs_{DST_SLUG}_laws_ir"),
        (f"ipfs_{SRC_SLUG}_laws", f"ipfs_{DST_SLUG}_laws"),
        ("HOLD 0 STRICT after-GD (PS); WAVE END after PS", "HOLD 0 STRICT after-MG; WAVE END after PS"),
        ("after-GD (PS); WAVE END after PS", "after-MG; WAVE END after PS"),
        ("after-GD", "after-MG"),
        ("www/gov/mg", "www/gov/ps"),
        ("/mg", "/ps"),
        ('"mg"', '"ps"'),
        ("MG-attested", "PS-attested"),
        ("(MG)", "(PS)"),
        ("French (Madagascar)", "Arabic (Palestine)"),
        ("French Madagascar", "Arabic Palestine"),
        ("Madagascar", "Palestine"),
        ("madagascar", "palestine"),
        ("French", "Arabic"),
        ("225/13117", "3178/12820"),
        ("225 / 13117", "3178 / 12820"),
        ("225, 13117", "3178, 12820"),
        ("225", "3178"),
        ("13117", "12820"),
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
