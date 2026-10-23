#!/usr/bin/env python3
"""Adapt the Turkmenistan memsafe FIRST_IR pack to Kyrgyzstan tip 3adfd953b02b.

Russian/Cyrillic Kyrgyzstan; FIRST_IR; HOLD 0 STRICT; soft never-thin ON;
SKIP_US; Italy BLOCKED. Queue after-CG: GA -> NR -> TG -> MS -> HT -> VG -> SX -> CD -> BM.
"""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
from pathlib import Path
import re

SRC_TIP_FULL = "ce38a3085e088c63199c8df68f15274c86755d74"
SRC_TIP_SHORT = "ce38a3085e08"
DST_TIP_FULL = "3adfd953b02bd575100fdd75bf8684ed7ff78dc4"
DST_TIP_SHORT = "3adfd953b02b"
SRC_SLUG = "turkmenistan"
DST_SLUG = "kyrgyzstan"
SRC_REPO = "endomorphosis/ipfs_turkmenistan_laws"
DST_REPO = "endomorphosis/ipfs_kyrgyzstan_laws"
SRC_TARGET = "justicedao/ipfs_turkmenistan_laws_ir"
DST_TARGET = "justicedao/ipfs_kyrgyzstan_laws_ir"
SRC_FLOOR_L, SRC_FLOOR_A = 422, 14191
FLOOR_LAWS, FLOOR_ARTS = 828, 11905
ROOT = Path("/workspace/do_ir_resume")

files = [
    ("turkmenistan_soft_filter.py", "kyrgyzstan_soft_filter.py"),
    (f"turkmenistan_corpus_stream_{SRC_TIP_SHORT}.py", f"kyrgyzstan_corpus_stream_{DST_TIP_SHORT}.py"),
    (f"turkmenistan_encode_memsafe_{SRC_TIP_SHORT}.py", f"kyrgyzstan_encode_memsafe_{DST_TIP_SHORT}.py"),
    (f"turkmenistan_finish_from_emb_{SRC_TIP_SHORT}.py", f"kyrgyzstan_finish_from_emb_{DST_TIP_SHORT}.py"),
    (f"turkmenistan_stream_graph_parts_{SRC_TIP_SHORT}.py", f"kyrgyzstan_stream_graph_parts_{DST_TIP_SHORT}.py"),
    (f"turkmenistan_package_memsafe_{SRC_TIP_SHORT}.py", f"kyrgyzstan_package_memsafe_{DST_TIP_SHORT}.py"),
    ("turkmenistan_upload.py", "kyrgyzstan_upload.py"),
    ("turkmenistan_bm25_smoke.py", "kyrgyzstan_bm25_smoke.py"),
    ("turkmenistan_write_publish_report.py", "kyrgyzstan_write_publish_report.py"),
    (f"turkmenistan_orchestrator_{SRC_TIP_SHORT}.py", f"kyrgyzstan_orchestrator_{DST_TIP_SHORT}.py"),
]


def adapt(text: str) -> str:
    replacements = [
        (SRC_TIP_FULL, DST_TIP_FULL),
        (SRC_TIP_SHORT, DST_TIP_SHORT),
        (SRC_REPO, DST_REPO),
        (SRC_TARGET, DST_TARGET),
        (f"ipfs_{SRC_SLUG}_laws_ir", f"ipfs_{DST_SLUG}_laws_ir"),
        (f"ipfs_{SRC_SLUG}_laws", f"ipfs_{DST_SLUG}_laws"),
        ("HOLD 0 STRICT after-SM (GD→MG→PS)", "HOLD 0 STRICT after-CG (GA→NR→TG→MS→HT→VG→SX→CD→BM)"),
        ("after-SM (GD→MG→PS)", "after-CG (GA→NR→TG→MS→HT→VG→SX→CD→BM)"),
        ("after-SM", "after-CG"),
        ("www/gov/tm", "www/gov/kg"),
        ("/tm", "/kg"),
        ('"tm"', '"kg"'),
        ("TM-attested", "KG-attested"),
        ("(TM)", "(KG)"),
        ("Russian (Cyrillic) Turkmenistan", "Russian (Cyrillic) Kyrgyzstan"),
        ("Russian Turkmenistan", "Russian Kyrgyzstan"),
        ("Turkmenistan", "Kyrgyzstan"),
        ("turkmenistan", "kyrgyzstan"),
        ("422/14191", "828/11905"),
        ("422 / 14191", "828 / 11905"),
        ("422, 14191", "828, 11905"),
        ("422", "828"),
        ("14191", "11905"),
        # Defensive purge for stale prior Cyrillic/Latin country tokens.
        ("Madagascar", "Kyrgyzstan"), ("madagascar", "kyrgyzstan"),
        ("Comoros", "Kyrgyzstan"), ("comoros", "kyrgyzstan"),
        ("Malagasy", "Russian"), ("malagasy", "russian"),
        ("French", "Russian"), ("french", "russian"),
        ("tsy", "кыргыз"), ("ireo", "кыргыз"), ("lalana", "кыргыз"),
    ]
    for a, b in replacements:
        text = text.replace(a, b)
    return text

for src_name, dst_name in files:
    src = ROOT / src_name
    if not src.is_file():
        raise FileNotFoundError(src)
    dst = ROOT / dst_name
    dst.write_text(adapt(src.read_text(encoding="utf-8")), encoding="utf-8")
    print(f"wrote {dst_name}")

# Do not permit stale French/Malagasy/Congo gate tokens into the KG pack.
for _, dst_name in files:
    text = (ROOT / dst_name).read_text(encoding="utf-8")
    stale = re.findall(r"(?i)madagascar|malagasy|comoros|french|\btsy\b|\bireo\b|\blalana\b", text)
    if stale:
        raise RuntimeError(f"stale source tokens in {dst_name}: {sorted(set(stale))}")
print("done")
