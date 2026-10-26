#!/usr/bin/env python3
"""Adapt the Congo-Brazzaville French memsafe FIRST_IR pack to Gabon."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
from pathlib import Path

SRC_TIP_FULL = "79328ea45cb07f2e88708d7ab303e608038018b8"
SRC_TIP_SHORT = "79328ea45cb0"
DST_TIP_FULL = "55ca40a7d28bf4091b9481d866e7a5d12ce5c577"
DST_TIP_SHORT = "55ca40a7d28b"
SRC_SLUG = "congobrazzaville"
DST_SLUG = "gabon"
SRC_REPO = "endomorphosis/ipfs_congobrazzaville_laws"
DST_REPO = "endomorphosis/ipfs_gabon_laws"
SRC_TARGET = "justicedao/ipfs_congobrazzaville_laws_ir"
DST_TARGET = "justicedao/ipfs_gabon_laws_ir"
FLOOR_LAWS, FLOOR_ARTS = 124, 11918
DST_FLOOR_LAWS, DST_FLOOR_ARTS = 81, 11599
ROOT = Path("/workspace/do_ir_resume")

files = [
    ("congobrazzaville_soft_filter.py", "gabon_soft_filter.py"),
    (f"congobrazzaville_corpus_stream_{SRC_TIP_SHORT}.py", f"gabon_corpus_stream_{DST_TIP_SHORT}.py"),
    (f"congobrazzaville_encode_memsafe_{SRC_TIP_SHORT}.py", f"gabon_encode_memsafe_{DST_TIP_SHORT}.py"),
    (f"congobrazzaville_finish_from_emb_{SRC_TIP_SHORT}.py", f"gabon_finish_from_emb_{DST_TIP_SHORT}.py"),
    (f"congobrazzaville_stream_graph_parts_{SRC_TIP_SHORT}.py", f"gabon_stream_graph_parts_{DST_TIP_SHORT}.py"),
    (f"congobrazzaville_package_memsafe_{SRC_TIP_SHORT}.py", f"gabon_package_memsafe_{DST_TIP_SHORT}.py"),
    ("congobrazzaville_upload.py", "gabon_upload.py"),
    ("congobrazzaville_bm25_smoke.py", "gabon_bm25_smoke.py"),
    ("congobrazzaville_write_publish_report.py", "gabon_write_publish_report.py"),
    (f"congobrazzaville_orchestrator_{SRC_TIP_SHORT}.py", f"gabon_orchestrator_{DST_TIP_SHORT}.py"),
]

def adapt(text: str) -> str:
    replacements = [
        (SRC_TIP_FULL, DST_TIP_FULL),
        (SRC_TIP_SHORT, DST_TIP_SHORT),
        (SRC_REPO, DST_REPO),
        (SRC_TARGET, DST_TARGET),
        ("HOLD 0 STRICT after-AI (KG→GA→NR→TG→MS→HT→VG→SX→CD→BM)", "HOLD 0 STRICT after-KG (NR→TG→MS→HT→VG→SX→CD→BM)"),
        ("after-AI (KG→GA→NR→TG→MS→HT→VG→SX→CD→BM)", "after-KG (NR→TG→MS→HT→VG→SX→CD→BM)"),
        ("after-AI", "after-KG"),
        ("www/gov/cg", "www/gov/ga"),
        ("/cg", "/ga"),
        ('"cg"', '"ga"'),
        ("(CG)", "(GA)"),
        ("French (Congo-Brazzaville)", "French (Gabon)"),
        ("French Congo-Brazzaville", "French Gabon"),
        ("Congo-Brazzaville", "Gabon"),
        ("congobrazzaville", "gabon"),
        ("124/11918", "81/11599"),
        ("124 / 11918", "81 / 11599"),
        ("124, 11918", "81, 11599"),
        ("124", "81"),
        ("11918", "11599"),
    ]
    for a, b in replacements:
        text = text.replace(a, b)
    return text

for src_name, dst_name in files:
    src = ROOT / src_name
    if not src.is_file():
        raise FileNotFoundError(src)
    text = adapt(src.read_text(encoding="utf-8"))
    if dst_name == "gabon_bm25_smoke.py":
        text = text.replace(
            'GATE_YEARS = ["1996", "2005", "2007", "2009", "2012", "2015", "2020", "2022", "2023"]',
            'GATE_YEARS = ["1994", "1995", "1997", "1999", "2000", "2004", "2006", "2018", "2020", "2021"]',
        )
        text = text.replace(
            '    "article", "etat", "autorite", "membre", "civile", "aviation", "aeronef",\n    "dispositions", "marches", "vehicule", "ouvrage", "circulation",',
            '    "article", "etat", "navire", "maritime", "autorite", "nationale",\n    "assemblee", "securite", "navigation", "president", "code", "membre",',
        )
        text = text.replace('    # Malagasy-only diagnostics are query-only; French GATE is preferred.\n    "tsy", "dia", "ireo", "lalana",\n', '')
        text = text.replace('"cg", "law", "shall"', '"ga", "law", "shall"')
    (ROOT / dst_name).write_text(text, encoding="utf-8")
    print(f"wrote {dst_name}")
print("done")
