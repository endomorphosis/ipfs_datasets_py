#!/usr/bin/env python3
"""Adapt the Nauru English memsafe FIRST_IR pack to Montserrat MS."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
from pathlib import Path
import json
ROOT = Path("/workspace/do_ir_resume")
SRC_TIP_FULL = "41eb38ee2113ab587d52a04444a1c05cb36bc0c3"
SRC_TIP_SHORT = "41eb38ee2113"
DST_TIP_FULL = "0934a8280dead70835c8f3cda66a9b36771555cb"
DST_TIP_SHORT = "0934a8280dea"
FLOOR_LAWS, FLOOR_ARTS = 175, 9650
FILES = [
    ("nauru_soft_filter.py", "montserrat_soft_filter.py"),
    (f"nauru_corpus_stream_{SRC_TIP_SHORT}.py", f"montserrat_corpus_stream_{DST_TIP_SHORT}.py"),
    (f"nauru_encode_memsafe_{SRC_TIP_SHORT}.py", f"montserrat_encode_memsafe_{DST_TIP_SHORT}.py"),
    (f"nauru_finish_from_emb_{SRC_TIP_SHORT}.py", f"montserrat_finish_from_emb_{DST_TIP_SHORT}.py"),
    (f"nauru_stream_graph_parts_{SRC_TIP_SHORT}.py", f"montserrat_stream_graph_parts_{DST_TIP_SHORT}.py"),
    (f"nauru_package_memsafe_{SRC_TIP_SHORT}.py", f"montserrat_package_memsafe_{DST_TIP_SHORT}.py"),
    ("nauru_upload.py", "montserrat_upload.py"),
    ("nauru_bm25_smoke.py", "montserrat_bm25_smoke.py"),
    ("nauru_write_publish_report.py", "montserrat_write_publish_report.py"),
    (f"nauru_orchestrator_{SRC_TIP_SHORT}.py", f"montserrat_orchestrator_{DST_TIP_SHORT}.py"),
]

def adapt(text: str, dst_name: str) -> str:
    reps = [
        (SRC_TIP_FULL, DST_TIP_FULL), (SRC_TIP_SHORT, DST_TIP_SHORT),
        ("endomorphosis/ipfs_nauru_laws", "endomorphosis/ipfs_montserrat_laws"),
        ("justicedao/ipfs_nauru_laws_ir", "justicedao/ipfs_montserrat_laws_ir"),
        ("ipfs_nauru_laws_ir", "ipfs_montserrat_laws_ir"),
        ("ipfs_nauru_laws", "ipfs_montserrat_laws"),
        ("HOLD 0 STRICT after-GA (TG→MS→HT→VG→SX→CD→BM)", "HOLD 0 STRICT after-TG (HT→VG→SX→CD→BM)"),
        ("after-GA (TG→MS→HT→VG→SX→CD→BM)", "after-TG (HT→VG→SX→CD→BM)"),
        ("after-GA", "after-TG"),
        ("www/gov/nr", "www/gov/ms"), ("/nr", "/ms"), ('"nr"', '"ms"'),
        ("NR-attested", "MS-attested"), ("(NR)", "(MS)"),
        ("English (Nauru)", "English (Montserrat)"),
        ("English Nauru", "English Montserrat"),
        ("Nauru", "Montserrat"), ("nauru", "montserrat"),
        ("466/10936", "175/9650"), ("466 / 10936", "175 / 9650"),
        ("466, 10936", "175, 9650"), ("466", "175"), ("10936", "9650"),
    ]
    for a, b in reps:
        text = text.replace(a, b)
    if dst_name == "montserrat_bm25_smoke.py":
        start = text.index("GATE = [")
        end = text.index("]", start) + 1
        gate = ("GATE = [\n"
                "    \"1967\", \"2000\", \"2002\", \"2005\", \"2008\", \"2011\", \"2013\", \"2019\", \"2020\", \"2025\",\n"
                "    \"shall\", \"assembly\", \"governor\", \"person\", \"montserrat\", \"constitution\", \"act\", \"section\", \"legislative\", \"committee\", \"member\", \"office\",\n"
                "]")
        text = text[:start] + gate + text[end:]
        text = text.replace(
            "attested years 1972/2011/2014/2016/2018/2019/2020/2021/2024/2025 plus English legal stems act/person/shall/court/republic/section/montserrat/financial/order/service/entity from articles.parquet HEAD tip 0934a8280dea; URL www/gov/ms is query-only, not GATE.",
            "attested years 1967/2000/2002/2005/2008/2011/2013/2019/2020/2025 plus English legal stems shall/assembly/governor/person/montserrat/constitution/act/section/legislative/committee/member/office from articles.parquet HEAD tip 0934a8280dea; URL www/gov/ms is query-only, not GATE.")
    if dst_name == "montserrat_write_publish_report.py":
        text = text.replace("1972/2011/2014/2016/2018/2019/2020/2021/2024/2025 + stems act/person/shall/court/republic/section/montserrat/financial/order/service/entity", "1967/2000/2002/2005/2008/2011/2013/2019/2020/2025 + stems shall/assembly/governor/person/montserrat/constitution/act/section/legislative/committee/member/office")
        text = text.replace("English GATE", "English (Montserrat) GATE")
    if "French" in text or "Gabon" in text or "Togo" in text:
        raise RuntimeError(f"language/queue leftovers in {dst_name}")
    return text

for src_name, dst_name in FILES:
    src = ROOT / src_name
    if not src.is_file():
        raise FileNotFoundError(src)
    (ROOT / dst_name).write_text(adapt(src.read_text(encoding="utf-8"), dst_name), encoding="utf-8")
    print(f"wrote {dst_name}")

wave = Path("/workspace/country-law-triage/next_ir_ok_wave_after_ps.json")
data = json.loads(wave.read_text(encoding="utf-8"))
for entry in data["queue"]:
    if entry.get("slug") == "montserrat":
        entry.update({
            "tip": DST_TIP_SHORT, "tip_full": DST_TIP_FULL,
            "laws": FLOOR_LAWS, "articles": FLOOR_ARTS,
            "floor_laws": FLOOR_LAWS, "floor_articles": FLOOR_ARTS,
            "claim_tip": DST_TIP_SHORT, "match_claim": True,
            "ir_hub_head": None, "true_first_ir": True, "thin": False,
            "label": "EXPAND", "soft_never_thin": True, "skip_us": True,
            "italy_blocked": True, "language": "English",
            "years_attested": [2025, 2013, 2011, 2019, 2002, 2020, 2005, 2008, 2000, 2012, 1967, 2010],
            "gate_years": [1967, 2000, 2002, 2005, 2008, 2011, 2013, 2019, 2020, 2025],
            "gate_stems": ["shall", "assembly", "governor", "person", "montserrat", "constitution", "act", "section", "legislative", "committee", "member", "office"],
            "note": "MS FIRST_IR scaffold; tip MATCH 0934a8280dea@175/9650; HOLD 0 STRICT; queue HT→VG→SX→CD→BM",
        })
        break
else:
    raise RuntimeError("Montserrat entry missing from wave JSON")
wave.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print("updated wave JSON Montserrat entry")
