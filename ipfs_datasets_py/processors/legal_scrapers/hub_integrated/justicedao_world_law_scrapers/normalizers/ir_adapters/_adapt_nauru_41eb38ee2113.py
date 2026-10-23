#!/usr/bin/env python3
"""Adapt the Anguilla English FIRST_IR memsafe pack to Nauru NR."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
from pathlib import Path
ROOT = Path("/workspace/do_ir_resume")
SRC_TIP_FULL = "be6ea6899994e5ccea4a59239d8a4cc3ee67b31e"
SRC_TIP_SHORT = "be6ea6899994"
DST_TIP_FULL = "41eb38ee2113ab587d52a04444a1c05cb36bc0c3"
DST_TIP_SHORT = "41eb38ee2113"
FLOOR_LAWS, FLOOR_ARTS = 466, 10936
FILES = [
    ("anguilla_soft_filter.py", "nauru_soft_filter.py"),
    (f"anguilla_corpus_stream_{SRC_TIP_SHORT}.py", f"nauru_corpus_stream_{DST_TIP_SHORT}.py"),
    (f"anguilla_encode_memsafe_{SRC_TIP_SHORT}.py", f"nauru_encode_memsafe_{DST_TIP_SHORT}.py"),
    (f"anguilla_finish_from_emb_{SRC_TIP_SHORT}.py", f"nauru_finish_from_emb_{DST_TIP_SHORT}.py"),
    (f"anguilla_stream_graph_parts_{SRC_TIP_SHORT}.py", f"nauru_stream_graph_parts_{DST_TIP_SHORT}.py"),
    (f"anguilla_package_memsafe_{SRC_TIP_SHORT}.py", f"nauru_package_memsafe_{DST_TIP_SHORT}.py"),
    ("anguilla_upload.py", "nauru_upload.py"),
    ("anguilla_bm25_smoke.py", "nauru_bm25_smoke.py"),
    ("anguilla_write_publish_report.py", "nauru_write_publish_report.py"),
    (f"anguilla_orchestrator_{SRC_TIP_SHORT}.py", f"nauru_orchestrator_{DST_TIP_SHORT}.py"),
]

def adapt(text: str) -> str:
    reps = [
        (SRC_TIP_FULL, DST_TIP_FULL), (SRC_TIP_SHORT, DST_TIP_SHORT),
        ("endomorphosis/ipfs_anguilla_laws", "endomorphosis/ipfs_nauru_laws"),
        ("justicedao/ipfs_anguilla_laws_ir", "justicedao/ipfs_nauru_laws_ir"),
        ("ipfs_anguilla_laws_ir", "ipfs_nauru_laws_ir"),
        ("ipfs_anguilla_laws", "ipfs_nauru_laws"),
        ("HOLD 0 STRICT after-PS (CG→KG→GA→NR→TG→MS→HT→VG→SX→CD→BM)", "HOLD 0 STRICT after-GA (TG→MS→HT→VG→SX→CD→BM)"),
        ("after-PS (CG→KG→GA→NR→TG→MS→HT→VG→SX→CD→BM)", "after-GA (TG→MS→HT→VG→SX→CD→BM)"),
        ("after-PS", "after-GA"),
        ("www/gov/ai", "www/gov/nr"), ("/ai", "/nr"), ('"ai"', '"nr"'),
        ("AI-attested", "NR-attested"), ("(AI)", "(NR)"),
        ("English (Anguilla)", "English (Nauru)"),
        ("English Anguilla", "English Nauru"),
        ("Anguilla", "Nauru"), ("anguilla", "nauru"),
        ("175/12203", "466/10936"), ("175 / 12203", "466 / 10936"),
        ("175, 12203", "466, 10936"), ("175", "466"), ("12203", "10936"),
    ]
    for a, b in reps:
        text = text.replace(a, b)
    return text

for src_name, dst_name in FILES:
    src = ROOT / src_name
    if not src.is_file():
        raise FileNotFoundError(src)
    text = adapt(src.read_text(encoding="utf-8"))
    if dst_name == "nauru_bm25_smoke.py":
        start = text.index("GATE = [")
        end = text.index("]", start) + 1
        gate = ("GATE = [\n"
                "    \"1972\", \"2011\", \"2014\", \"2016\", \"2018\", \"2019\", \"2020\", \"2021\", \"2024\", \"2025\",\n"
                "    \"act\", \"person\", \"shall\", \"court\", \"republic\", \"section\", \"nauru\", \"financial\", \"order\", \"service\", \"entity\",\n"
                "]")
        text = text[:start] + gate + text[end:]
        text = text.replace('"anguilla_pass"', '"nauru_pass"').replace('"anguilla_gate"', '"nauru_gate"')
        text = text.replace("attested years 1982/2000/2006/2009/2010/2014/2019/2022 plus English legal stems authority/shall/act/anguilla/person/section/officer/aircraft/government/goods/order/law/ports/executive from articles.parquet HEAD tip be6ea6899994; URL www/gov/ai is query-only, not GATE.", "attested years 1972/2011/2014/2016/2018/2019/2020/2021/2024/2025 plus English legal stems act/person/shall/court/republic/section/nauru/financial/order/service/entity from articles.parquet HEAD tip 41eb38ee2113; URL www/gov/nr is query-only, not GATE.")
    (ROOT / dst_name).write_text(text, encoding="utf-8")
    print(f"wrote {dst_name}")
print("done")
