#!/usr/bin/env python3
'''Adapt the Gabon French memsafe FIRST_IR pack to Togo.'''
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
from pathlib import Path
import re

SRC_TIP_FULL = "55ca40a7d28bf4091b9481d866e7a5d12ce5c577"
SRC_TIP_SHORT = "55ca40a7d28b"
DST_TIP_FULL = "5d6406438adc379a3db1a2102b30c3f49e313443"
DST_TIP_SHORT = "5d6406438adc"
SRC_SLUG = "gabon"
DST_SLUG = "togo"
SRC_REPO = "endomorphosis/ipfs_gabon_laws"
DST_REPO = "endomorphosis/ipfs_togo_laws"
SRC_TARGET = "justicedao/ipfs_gabon_laws_ir"
DST_TARGET = "justicedao/ipfs_togo_laws_ir"
SRC_FLOOR_LAWS, SRC_FLOOR_ARTS = 81, 11599
DST_FLOOR_LAWS, DST_FLOOR_ARTS = 170, 10915
ROOT = Path("/workspace/do_ir_resume")

files = [
    ("gabon_soft_filter.py", "togo_soft_filter.py"),
    (f"gabon_corpus_stream_{SRC_TIP_SHORT}.py", f"togo_corpus_stream_{DST_TIP_SHORT}.py"),
    (f"gabon_encode_memsafe_{SRC_TIP_SHORT}.py", f"togo_encode_memsafe_{DST_TIP_SHORT}.py"),
    (f"gabon_finish_from_emb_{SRC_TIP_SHORT}.py", f"togo_finish_from_emb_{DST_TIP_SHORT}.py"),
    (f"gabon_stream_graph_parts_{SRC_TIP_SHORT}.py", f"togo_stream_graph_parts_{DST_TIP_SHORT}.py"),
    (f"gabon_package_memsafe_{SRC_TIP_SHORT}.py", f"togo_package_memsafe_{DST_TIP_SHORT}.py"),
    ("gabon_upload.py", "togo_upload.py"),
    ("gabon_bm25_smoke.py", "togo_bm25_smoke.py"),
    ("gabon_write_publish_report.py", "togo_write_publish_report.py"),
    (f"gabon_orchestrator_{SRC_TIP_SHORT}.py", f"togo_orchestrator_{DST_TIP_SHORT}.py"),
]


def adapt(text: str, dst_name: str) -> str:
    replacements = [
        (SRC_TIP_FULL, DST_TIP_FULL),
        (SRC_TIP_SHORT, DST_TIP_SHORT),
        (SRC_REPO, DST_REPO),
        (SRC_TARGET, DST_TARGET),
        ("HOLD 0 STRICT after-KG (NR→TG→MS→HT→VG→SX→CD→BM)", "HOLD 0 STRICT after-NR (MS→HT→VG→SX→CD→BM)"),
        ("after-KG", "after-NR"),
        ("www/gov/ga", "www/gov/tg"),
        ('"ga"', '"tg"'),
        ("(GA)", "(TG)"),
        ("French (Gabon)", "French (Togo)"),
        ("French Gabon", "French Togo"),
        ("Gabon", "Togo"),
        ("gabon", "togo"),
        ("81/11599", "170/10915"),
        ("81 / 11599", "170 / 10915"),
        ("81, 11599", "170, 10915"),
        ("or 81", "or 170"),
        ("or 11599", "or 10915"),
    ]
    for a, b in replacements:
        text = text.replace(a, b)
    if dst_name == "togo_bm25_smoke.py":
        text = re.sub(r'GATE_YEARS = \[[^\n]+\]', 'GATE_YEARS = ["2007", "2011", "2012", "2015", "2017", "2018", "2019", "2020", "2022", "2024"]', text)
        text = re.sub(r'GATE_FRENCH = \[.*?\n\]', '''GATE_FRENCH = [
    "article", "loi", "republique", "president", "etat", "nationale",
    "assemblee", "cour", "autorite", "decret", "ministre", "togolaise",
]''', text, flags=re.S)
        text = text.replace('    "www", "gov", "tg", "law", "shall",', '    "www", "gov", "tg",')
        text = text.replace("URL www/gov/tg and English law/shall are query-only, not GATE.", "URL www/gov/tg is query-only, not GATE.")
        text = text.replace("# URL and English diagnostics are query-only, never GATE.", "# URL diagnostics are query-only, never GATE.")
        text = text.replace("attested Gabon", "attested Togo")
        text = text.replace("Gabon ASCII-fold", "Togo ASCII-fold")
        text = text.replace("years 1994/1995/1997/1999/2000/2004/2006/2018/2020/2021 plus French legal stems ", "years 2007/2011/2012/2015/2017/2018/2019/2020/2022/2024 plus French legal stems ")
        text = text.replace("article/etat/navire/maritime/autorite/nationale/assemblee/securite/", "article/loi/republique/president/etat/nationale/assemblee/cour/autorite/decret/ministre/togolaise")
        text = text.replace("from articles.parquet HEAD tip", "from articles.parquet HEAD tip")
        text = text.replace(
            "years 1994/1995/1997/1999/2000/2004/2006/2018/2020/2021 plus French legal stems article/etat/navire/maritime/autorite/nationale/assemblee/securite/navigation/president/code/membre",
            "years 2007/2011/2012/2015/2017/2018/2019/2020/2022/2024 plus French legal stems article/loi/republique/president/etat/nationale/assemblee/cour/autorite/decret/ministre/togolaise",
        )
        text = text.replace('detail["gabon_pass"]', 'detail["togo_pass"]')
        text = text.replace('detail["gabon_gate"]', 'detail["togo_gate"]')
    if dst_name == "togo_write_publish_report.py":
        text = text.replace("gabon_ranked", "togo_ranked")
        text = text.replace("Hub tip pinned {TIP_SHORT} (IR-OK floor 81/11599;", "Hub tip pinned {TIP_SHORT} (IR-OK floor 170/10915;")
        text = text.replace(
            "BM25 PASS on Gabon ASCII-fold French GATE (1994/1995/1997/1999/2000/2004/2006/2018/2020/2021 + article/etat/navire/maritime/autorite/nationale/assemblee/securite/navigation/president/code/membre); URL www/gov/ga and English law/shall are query-only, not GATE",
            "BM25 PASS on Togo ASCII-fold French GATE (2007/2011/2012/2015/2017/2018/2019/2020/2022/2024 + article/loi/republique/president/etat/nationale/assemblee/cour/autorite/decret/ministre/togolaise); URL www/gov/tg is query-only, not GATE",
        )
    return text

for src_name, dst_name in files:
    src = ROOT / src_name
    if not src.is_file():
        raise FileNotFoundError(src)
    (ROOT / dst_name).write_text(adapt(src.read_text(encoding="utf-8"), dst_name), encoding="utf-8")
    print(f"wrote {dst_name}")
print("done")
