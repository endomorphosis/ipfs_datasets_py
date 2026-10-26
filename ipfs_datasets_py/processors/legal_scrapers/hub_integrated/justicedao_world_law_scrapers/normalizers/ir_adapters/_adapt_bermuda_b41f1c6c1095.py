#!/usr/bin/env python3
"""Adapt the Montserrat English memsafe FIRST_IR pack to Bermuda BM."""
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
DST_TIP_FULL = "b41f1c6c1095aa608d8d06a31e88e6886b2e9e1a"
DST_TIP_SHORT = "b41f1c6c1095"
FLOOR_LAWS, FLOOR_ARTS = 175, 8334

FILES = [
    ("montserrat_soft_filter.py", "bermuda_soft_filter.py"),
    (f"montserrat_corpus_stream_{SRC_TIP_SHORT}.py", f"bermuda_corpus_stream_{DST_TIP_SHORT}.py"),
    (f"montserrat_encode_memsafe_{SRC_TIP_SHORT}.py", f"bermuda_encode_memsafe_{DST_TIP_SHORT}.py"),
    (f"montserrat_finish_from_emb_{SRC_TIP_SHORT}.py", f"bermuda_finish_from_emb_{DST_TIP_SHORT}.py"),
    (f"montserrat_stream_graph_parts_{SRC_TIP_SHORT}.py", f"bermuda_stream_graph_parts_{DST_TIP_SHORT}.py"),
    (f"montserrat_package_memsafe_{SRC_TIP_SHORT}.py", f"bermuda_package_memsafe_{DST_TIP_SHORT}.py"),
    ("montserrat_upload.py", "bermuda_upload.py"),
    ("montserrat_bm25_smoke.py", "bermuda_bm25_smoke.py"),
    ("montserrat_write_publish_report.py", "bermuda_write_publish_report.py"),
    (f"montserrat_orchestrator_{SRC_TIP_SHORT}.py", f"bermuda_orchestrator_{DST_TIP_SHORT}.py"),
]


def adapt(text: str, dst_name: str) -> str:
    reps = [
        (SRC_TIP_FULL, DST_TIP_FULL),
        (SRC_TIP_SHORT, DST_TIP_SHORT),
        ("endomorphosis/ipfs_montserrat_laws", "endomorphosis/ipfs_bermuda_laws"),
        ("justicedao/ipfs_montserrat_laws_ir", "justicedao/ipfs_bermuda_laws_ir"),
        ("ipfs_montserrat_laws_ir", "ipfs_bermuda_laws_ir"),
        ("ipfs_montserrat_laws", "ipfs_bermuda_laws"),
        ("HOLD 0 STRICT after-TG (HT→VG→SX→CD→BM)", "HOLD 0 STRICT after-CD (BM WAVE END)"),
        ("after-TG (HT→VG→SX→CD→BM)", "after-CD (BM WAVE END)"),
        ("after-TG", "after-CD"),
        ("www/gov/ms", "www/gov/bm"),
        ("English (Montserrat)", "English (Bermuda)"),
        ("English Montserrat", "English Bermuda"),
        ("Montserrat", "Bermuda"),
        ("montserrat", "bermuda"),
        ('"MS"', '"BM"'),
        ("MS-attested", "BM-attested"),
        ("ms", "bm"),
        ("(MS)", "(BM)"),
        ("/ms", "/bm"),
        (" 9650", " 8334"),
        ("9650", "8334"),
    ]
    for a, b in reps:
        text = text.replace(a, b)

    if dst_name == "bermuda_bm25_smoke.py":
        start = text.index("GATE = [")
        end = text.index("]", start) + 1
        gate = ("GATE = [\n"
                "    \"1998\", \"1999\", \"2004\", \"2006\", \"2008\", \"2010\", \"2011\", \"2013\", \"2015\", \"2018\",\n"
                "    \"person\", \"shall\", \"section\", \"court\", \"act\", \"offence\", \"order\", \"subsection\", \"imprisonment\", \"evidence\", \"junction\",\n"
                "]")
        text = text[:start] + gate + text[end:]
        text = text.replace(
            "attested years 1967/2000/2002/2005/2008/2011/2013/2019/2020/2025 plus English legal stems shall/assembly/governor/person/bermuda/constitution/act/section/legislative/committee/member/office from articles.parquet HEAD tip b41f1c6c1095; URL www/gov/bm is query-only, not GATE.",
            "attested years 1998/1999/2004/2006/2008/2010/2011/2013/2015/2018 plus English legal stems person/shall/section/court/act/offence/order/subsection/imprisonment/evidence/junction from articles.parquet HEAD tip b41f1c6c1095; URL www/gov/bm is query-only, not GATE.")

    if dst_name == "bermuda_write_publish_report.py":
        text = text.replace(
            "1967/2000/2002/2005/2008/2011/2013/2019/2020/2025 + stems shall/assembly/governor/person/bermuda/constitution/act/section/legislative/committee/member/office",
            "1998/1999/2004/2006/2008/2010/2011/2013/2015/2018 + stems person/shall/section/court/act/offence/order/subsection/imprisonment/evidence/junction")
        text = text.replace("English GATE", "English (Bermuda) GATE")

    leftovers = ("French", "Haiti", "Nauru", "Montserrat", "British Virgin Islands", "Gabon", "Togo")
    if any(x in text for x in leftovers):
        raise RuntimeError(f"language/country leftovers in {dst_name}: {[x for x in leftovers if x in text]}")
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
    if entry.get("slug") == "bermuda":
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
            "years_attested": [2018, 2004, 2010, 2011, 2008, 2013, 1999, 2015, 2006, 2017, 2012, 1998],
            "gate_years": [1998, 1999, 2004, 2006, 2008, 2010, 2011, 2013, 2015, 2018],
            "gate_stems": ["person", "shall", "section", "court", "act", "offence", "order", "subsection", "imprisonment", "evidence", "junction"],
            "note": "BM FIRST_IR scaffold; tip MATCH b41f1c6c1095@175/8334; HOLD 0 STRICT; WAVE END after-CD",
        })
        break
else:
    raise RuntimeError("Bermuda entry missing from wave JSON")
wave.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print("updated wave JSON Bermuda entry")
