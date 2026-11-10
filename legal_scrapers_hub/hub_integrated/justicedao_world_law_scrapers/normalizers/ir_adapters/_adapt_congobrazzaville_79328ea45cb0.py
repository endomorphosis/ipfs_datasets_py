#!/usr/bin/env python3
"""Adapt the Madagascar memsafe FIRST_IR pack to Congo-Brazzaville tip 79328ea45cb0.

French Congo-Brazzaville; FIRST_IR; HOLD 0 STRICT; soft never-thin ON; SKIP_US; Italy BLOCKED.
Queue after-AI: KG→GA→NR→TG→MS→HT→VG→SX→CD→BM.
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
DST_TIP_FULL = "79328ea45cb07f2e88708d7ab303e608038018b8"
DST_TIP_SHORT = "79328ea45cb0"
SRC_SLUG = "madagascar"
DST_SLUG = "congobrazzaville"
SRC_REPO = "endomorphosis/ipfs_madagascar_laws"
DST_REPO = "endomorphosis/ipfs_congobrazzaville_laws"
SRC_TARGET = "justicedao/ipfs_madagascar_laws_ir"
DST_TARGET = "justicedao/ipfs_congobrazzaville_laws_ir"
FLOOR_LAWS, FLOOR_ARTS = 124, 11918
ROOT = Path("/workspace/do_ir_resume")

files = [
    ("madagascar_soft_filter.py", "congobrazzaville_soft_filter.py"),
    (f"madagascar_corpus_stream_{SRC_TIP_SHORT}.py", f"congobrazzaville_corpus_stream_{DST_TIP_SHORT}.py"),
    (f"madagascar_encode_memsafe_{SRC_TIP_SHORT}.py", f"congobrazzaville_encode_memsafe_{DST_TIP_SHORT}.py"),
    (f"madagascar_finish_from_emb_{SRC_TIP_SHORT}.py", f"congobrazzaville_finish_from_emb_{DST_TIP_SHORT}.py"),
    (f"madagascar_stream_graph_parts_{SRC_TIP_SHORT}.py", f"congobrazzaville_stream_graph_parts_{DST_TIP_SHORT}.py"),
    (f"madagascar_package_memsafe_{SRC_TIP_SHORT}.py", f"congobrazzaville_package_memsafe_{DST_TIP_SHORT}.py"),
    ("madagascar_upload.py", "congobrazzaville_upload.py"),
    ("madagascar_bm25_smoke.py", "congobrazzaville_bm25_smoke.py"),
    ("madagascar_write_publish_report.py", "congobrazzaville_write_publish_report.py"),
    (f"madagascar_orchestrator_{SRC_TIP_SHORT}.py", f"congobrazzaville_orchestrator_{DST_TIP_SHORT}.py"),
]

def adapt(text: str) -> str:
    replacements = [
        (SRC_TIP_FULL, DST_TIP_FULL), (SRC_TIP_SHORT, DST_TIP_SHORT),
        (SRC_REPO, DST_REPO), (SRC_TARGET, DST_TARGET),
        (f"ipfs_{SRC_SLUG}_laws_ir", f"ipfs_{DST_SLUG}_laws_ir"),
        (f"ipfs_{SRC_SLUG}_laws", f"ipfs_{DST_SLUG}_laws"),
        ("HOLD 0 STRICT after-GD (PS); WAVE END after PS", "HOLD 0 STRICT after-AI (KG→GA→NR→TG→MS→HT→VG→SX→CD→BM)"),
        ("after-GD (PS); WAVE END after PS", "after-AI (KG→GA→NR→TG→MS→HT→VG→SX→CD→BM)"),
        ("after-GD", "after-AI"), ("www/gov/mg", "www/gov/cg"),
        ("/mg", "/cg"), ('"mg"', '"cg"'), ("MG-attested", "CG-attested"),
        ("(MG)", "(CG)"), ("French (Madagascar)", "French (Congo-Brazzaville)"),
        ("French Madagascar", "French Congo-Brazzaville"), ("Madagascar", "Congo-Brazzaville"),
        ("madagascar", "congobrazzaville"), ("225/13117", "124/11918"),
        ("225 / 13117", "124 / 11918"), ("225, 13117", "124, 11918"),
        ("225", "124"), ("13117", "11918"),
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
