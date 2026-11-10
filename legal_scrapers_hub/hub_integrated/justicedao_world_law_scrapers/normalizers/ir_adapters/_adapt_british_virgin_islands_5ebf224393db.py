#!/usr/bin/env python3
"""Adapt the Montserrat English memsafe FIRST_IR pack to British Virgin Islands VG."""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
from pathlib import Path
import json

ROOT = Path("/workspace/do_ir_resume")
SRC_TIP_FULL = "0934a8280dead70835c8f3cda66a9b36771555cb"
SRC_TIP_SHORT = "0934a8280dea"
DST_TIP_FULL = "5ebf224393db6eddd471c8742712933a8457fdee"
DST_TIP_SHORT = "5ebf224393db"
FLOOR_LAWS, FLOOR_ARTS = 175, 9495

FILES = [
    ("montserrat_soft_filter.py", "british_virgin_islands_soft_filter.py"),
    (f"montserrat_corpus_stream_{SRC_TIP_SHORT}.py", f"british_virgin_islands_corpus_stream_{DST_TIP_SHORT}.py"),
    (f"montserrat_encode_memsafe_{SRC_TIP_SHORT}.py", f"british_virgin_islands_encode_memsafe_{DST_TIP_SHORT}.py"),
    (f"montserrat_finish_from_emb_{SRC_TIP_SHORT}.py", f"british_virgin_islands_finish_from_emb_{DST_TIP_SHORT}.py"),
    (f"montserrat_stream_graph_parts_{SRC_TIP_SHORT}.py", f"british_virgin_islands_stream_graph_parts_{DST_TIP_SHORT}.py"),
    (f"montserrat_package_memsafe_{SRC_TIP_SHORT}.py", f"british_virgin_islands_package_memsafe_{DST_TIP_SHORT}.py"),
    ("montserrat_upload.py", "british_virgin_islands_upload.py"),
    ("montserrat_bm25_smoke.py", "british_virgin_islands_bm25_smoke.py"),
    ("montserrat_write_publish_report.py", "british_virgin_islands_write_publish_report.py"),
    (f"montserrat_orchestrator_{SRC_TIP_SHORT}.py", f"british_virgin_islands_orchestrator_{DST_TIP_SHORT}.py"),
]


def adapt(text: str, dst_name: str) -> str:
    reps = [
        (SRC_TIP_FULL, DST_TIP_FULL),
        (SRC_TIP_SHORT, DST_TIP_SHORT),
        ("endomorphosis/ipfs_montserrat_laws", "endomorphosis/ipfs_british_virgin_islands_laws"),
        ("justicedao/ipfs_montserrat_laws_ir", "justicedao/ipfs_british_virgin_islands_laws_ir"),
        ("ipfs_montserrat_laws_ir", "ipfs_british_virgin_islands_laws_ir"),
        ("ipfs_montserrat_laws", "ipfs_british_virgin_islands_laws"),
        ("HOLD 0 STRICT after-TG (HT→VG→SX→CD→BM)", "HOLD 0 STRICT after-HT (SX→CD→BM)"),
        ("after-TG (HT→VG→SX→CD→BM)", "after-HT (SX→CD→BM)"),
        ("after-TG", "after-HT"),
        ("HT→VG→SX→CD→BM", "SX→CD→BM"),
        ("www/gov/ms", "www/gov/vg"),
        ("English (Montserrat)", "English (British Virgin Islands)"),
        ("English Montserrat", "English British Virgin Islands"),
        ("Montserrat", "British Virgin Islands"),
        ("montserrat", "british_virgin_islands"),
        ('"MS"', '"VG"'),
        ("MS-attested", "VG-attested"),
        ("ms", "vg"),
        ("(MS)", "(VG)"),
        ("/ms", "/vg"),
        ("9650", "9495"),
    ]
    for a, b in reps:
        text = text.replace(a, b)

    if dst_name == "british_virgin_islands_bm25_smoke.py":
        start = text.index("GATE = [")
        end = text.index("]", start) + 1
        gate = ("GATE = [\n"
                "    \"2005\", \"2006\", \"2008\", \"2009\", \"2010\", \"2012\", \"2013\", \"2015\", \"2018\", \"2020\",\n"
                "    \"shall\", \"order\", \"act\", \"person\", \"section\", \"islands\", \"virgin\", \"commission\", \"trust\", \"tribunal\", \"financial\", \"property\", \"services\",\n"
                "]")
        text = text[:start] + gate + text[end:]
        text = text.replace(
            "attested years 1967/2000/2002/2005/2008/2011/2013/2019/2020/2025 plus English legal stems shall/assembly/governor/person/british_virgin_islands/constitution/act/section/legislative/committee/member/office from articles.parquet HEAD tip 5ebf224393db; URL www/gov/vg is query-only, not GATE.",
            "attested years 2005/2006/2008/2009/2010/2012/2013/2015/2018/2020 plus English legal stems shall/order/act/person/section/islands/virgin/commission/trust/tribunal/financial/property/services from articles.parquet HEAD tip 5ebf224393db; URL www/gov/vg is query-only, not GATE.")

    if dst_name == "british_virgin_islands_write_publish_report.py":
        text = text.replace(
            "1967/2000/2002/2005/2008/2011/2013/2019/2020/2025 + stems shall/assembly/governor/person/british_virgin_islands/constitution/act/section/legislative/committee/member/office",
            "2005/2006/2008/2009/2010/2012/2013/2015/2018/2020 + stems shall/order/act/person/section/islands/virgin/commission/trust/tribunal/financial/property/services")
        text = text.replace("English GATE", "English (British Virgin Islands) GATE")

    if "French" in text or "Haiti" in text or "Montserrat" in text or "Nauru" in text:
        raise RuntimeError(f"language/country leftovers in {dst_name}")
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
    if entry.get("slug") == "british_virgin_islands":
        entry.update({
            "tip": DST_TIP_SHORT,
            "tip_full": DST_TIP_FULL,
            "laws": FLOOR_LAWS,
            "articles": FLOOR_ARTS,
            "floor_laws": FLOOR_LAWS,
            "floor_articles": FLOOR_ARTS,
            "claim_tip": DST_TIP_SHORT,
            "match_claim": True,
            "ir_hub_head": None,
            "true_first_ir": True,
            "thin": False,
            "label": "EXPAND",
            "soft_never_thin": True,
            "skip_us": True,
            "italy_blocked": True,
            "language": "English",
            "years_attested": [2020, 2010, 2005, 2012, 2006, 2013, 2023, 2009, 2015, 2018, 2019, 2008],
            "gate_years": [2005, 2006, 2008, 2009, 2010, 2012, 2013, 2015, 2018, 2020],
            "gate_stems": ["shall", "order", "act", "person", "section", "islands", "virgin", "commission", "trust", "tribunal", "financial", "property", "services"],
            "note": "VG FIRST_IR scaffold; tip MATCH 5ebf224393db@175/9495; HOLD 0 STRICT; queue after-HT (SX→CD→BM)",
        })
        break
else:
    raise RuntimeError("British Virgin Islands entry missing from wave JSON")
wave.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print("updated wave JSON British Virgin Islands entry")
