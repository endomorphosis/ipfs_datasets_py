#!/usr/bin/env python3
"""Adapt the Bermuda English memsafe FIRST_IR pack to Tuvalu TV.

English Tuvalu; FIRST_IR; HOLD 0 STRICT after-BM (TV→LR→SY→TO→BS→LS→BZ→SB→CW→MU→LC→TJ).
Soft never-thin ON; SKIP_US; Italy BLOCKED. WAVE first country, NOT wave end.
GATE: attested years + English legal stems from articles.parquet tip d7f84a3a4ff7.
"""
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
from pathlib import Path
import json
import re

ROOT = Path("/workspace/do_ir_resume")
SRC_TIP_FULL = "b41f1c6c1095aa608d8d06a31e88e6886b2e9e1a"
SRC_TIP_SHORT = "b41f1c6c1095"
DST_TIP_FULL = "d7f84a3a4ff7110cd3d660f59054c0abb901d372"
DST_TIP_SHORT = "d7f84a3a4ff7"
FLOOR_LAWS, FLOOR_ARTS = 289, 8141

GATE_YEARS = ["2008", "2009", "2010", "2012", "2013", "2014", "2016", "2017", "2022", "2023"]
GATE_STEMS = ["shall", "act", "section", "person", "court", "order", "tuvalu", "subsection", "offence", "minister", "schedule"]
GATE_NOTE_YEARS = "/".join(GATE_YEARS)
GATE_NOTE_STEMS = "/".join(GATE_STEMS)
HOLD = "HOLD 0 STRICT after-BM (TV→LR→SY→TO→BS→LS→BZ→SB→CW→MU→LC→TJ)"

FILES = [
    ("bermuda_soft_filter.py", "tuvalu_soft_filter.py"),
    (f"bermuda_corpus_stream_{SRC_TIP_SHORT}.py", f"tuvalu_corpus_stream_{DST_TIP_SHORT}.py"),
    (f"bermuda_encode_memsafe_{SRC_TIP_SHORT}.py", f"tuvalu_encode_memsafe_{DST_TIP_SHORT}.py"),
    (f"bermuda_finish_from_emb_{SRC_TIP_SHORT}.py", f"tuvalu_finish_from_emb_{DST_TIP_SHORT}.py"),
    (f"bermuda_stream_graph_parts_{SRC_TIP_SHORT}.py", f"tuvalu_stream_graph_parts_{DST_TIP_SHORT}.py"),
    (f"bermuda_package_memsafe_{SRC_TIP_SHORT}.py", f"tuvalu_package_memsafe_{DST_TIP_SHORT}.py"),
    ("bermuda_upload.py", "tuvalu_upload.py"),
    ("bermuda_bm25_smoke.py", "tuvalu_bm25_smoke.py"),
    ("bermuda_write_publish_report.py", "tuvalu_write_publish_report.py"),
    (f"bermuda_orchestrator_{SRC_TIP_SHORT}.py", f"tuvalu_orchestrator_{DST_TIP_SHORT}.py"),
]


def adapt(text: str, dst_name: str) -> str:
    # Protect bm25 / BM25 from ISO bm→tv swaps
    text = text.replace("BM25", "\x00BM25\x00").replace("bm25", "\x00bm25\x00")
    # Fix corrupted adjacency path back to canonical (query.py expects adjacency)
    text = text.replace("bmjacency", "adjacency")

    reps = [
        (SRC_TIP_FULL, DST_TIP_FULL),
        (SRC_TIP_SHORT, DST_TIP_SHORT),
        ("endomorphosis/ipfs_bermuda_laws", "endomorphosis/ipfs_tuvalu_laws"),
        ("justicedao/ipfs_bermuda_laws_ir", "justicedao/ipfs_tuvalu_laws_ir"),
        ("ipfs_bermuda_laws_ir", "ipfs_tuvalu_laws_ir"),
        ("ipfs_bermuda_laws", "ipfs_tuvalu_laws"),
        ("HOLD 0 STRICT after-CD (BM WAVE END)", HOLD),
        ("after-CD (BM WAVE END)", "after-BM (TV→LR→SY→TO→BS→LS→BZ→SB→CW→MU→LC→TJ)"),
        ("after-CD", "after-BM"),
        ("BM WAVE END", "TV FIRST_IR (not wave end)"),
        ("www/gov/bm", "www/gov/tv"),
        ("English (Bermuda)", "English (Tuvalu)"),
        ("English Bermuda", "English Tuvalu"),
        ("Bermuda", "Tuvalu"),
        ("bermuda", "tuvalu"),
        ('"BM"', '"TV"'),
        ("BM-attested", "TV-attested"),
        ("(BM)", "(TV)"),
        ('"bm"', '"tv"'),
        ("/bm", "/tv"),
        (" 8334", " 8141"),
        ("8334", "8141"),
        ("175/8141", "289/8141"),  # if 175 already paired wrong after 8334→8141
        ("175 / 8141", "289 / 8141"),
        ("175, 8141", "289, 8141"),
        ("175/8334", "289/8141"),
        ("175 / 8334", "289 / 8141"),
        ("175, 8334", "289, 8141"),
        ("= 175,", "= 289,"),
        ("= 175", "= 289"),
        ("@ 175/", "@ 289/"),
        (" 175/", " 289/"),
        ("floor 175/", "floor 289/"),
        ("(175/", "(289/"),
    ]
    for a, b in reps:
        text = text.replace(a, b)

    # Restore bm25 tokens
    text = text.replace("\x00BM25\x00", "BM25").replace("\x00bm25\x00", "bm25")

    # Fix any stray 175 that should be floor (common or N patterns)
    # Only in floor contexts — leave unrelated alone. Soft filter FLOOR_LAWS already via "= 175"
    text = text.replace("FLOOR_LAWS, FLOOR_ARTS = 175, 8141", "FLOOR_LAWS, FLOOR_ARTS = 289, 8141")
    text = text.replace("FLOOR_LAWS, FLOOR_ARTS = 175, 8334", "FLOOR_LAWS, FLOOR_ARTS = 289, 8141")
    text = text.replace("or 175)", "or 289)")
    text = text.replace("or 175,", "or 289,")

    if dst_name == "tuvalu_bm25_smoke.py":
        start = text.index("GATE = [")
        end = text.index("]", start) + 1
        years_line = ", ".join(f'"{y}"' for y in GATE_YEARS)
        stems_line = ", ".join(f'"{s}"' for s in GATE_STEMS)
        gate = f"GATE = [\n    {years_line},\n    {stems_line},\n]"
        text = text[:start] + gate + text[end:]
        # QUERIES already has "tv" from "bm"→ via "bm" in list — check
        # Ensure query-only URL tokens
        if 'QUERIES = GATE + ["www", "gov", "tv"' not in text and 'QUERIES = GATE + ["www", "gov", "bm"' in text:
            text = text.replace('QUERIES = GATE + ["www", "gov", "bm"', 'QUERIES = GATE + ["www", "gov", "tv"')
        note = (
            f"attested years {GATE_NOTE_YEARS} plus English legal stems {GATE_NOTE_STEMS} "
            f"from articles.parquet HEAD tip {DST_TIP_SHORT}; URL www/gov/tv is query-only, not GATE."
        )
        # replace tokenizer_note substring after GATE =
        text = re.sub(
            r"GATE = attested years [^;]+; URL www/gov/(?:bm|tv) is query-only, not GATE\.",
            f"GATE = {note}",
            text,
        )
        text = text.replace('"tuvalu_pass"', '"tuvalu_pass"').replace('"bermuda_pass"', '"tuvalu_pass"')
        text = text.replace('"tuvalu_gate"', '"tuvalu_gate"').replace('"bermuda_gate"', '"tuvalu_gate"')

    if dst_name == "tuvalu_write_publish_report.py":
        old_gate_bits = [
            "1998/1999/2004/2006/2008/2010/2011/2013/2015/2018 + stems person/shall/section/court/act/offence/order/subsection/imprisonment/evidence/junction",
            "1998/1999/2004/2006/2008/2010/2011/2013/2015/2018 + stems person/shall/section/court/act/offence/order/subsection/imprisonment/evidence/junction",
        ]
        new_gate = f"{GATE_NOTE_YEARS} + stems {GATE_NOTE_STEMS}"
        for o in old_gate_bits:
            text = text.replace(o, new_gate)
        # also catch if years already partially swapped
        text = re.sub(
            r"attested years [0-9/]+ \+ stems [a-z/]+",
            f"attested years {new_gate}",
            text,
        )
        text = text.replace("English GATE", "English (Tuvalu) GATE")
        text = text.replace("tuvalu_ranked", "tuvalu_ranked")  # already from bermuda→tuvalu
        text = text.replace(
            "HOLD collectors already requested by CoS; lean collectors left running; no SIGTERM this run",
            f"{HOLD}; collectors kept dead (pkill); soft never-thin ON; SKIP_US; Italy BLOCKED; FIRST country of after_bm wave",
        )

    leftovers = (
        "French", "Haiti", "Nauru", "Montserrat", "Bermuda", "bermuda",
        "British Virgin Islands", "Gabon", "Togo", "Anguilla", "Cook Islands",
        "bmjacency", "msjacency",
    )
    found = [x for x in leftovers if x in text]
    # allow "bm25"/"BM25" which contain neither Bermuda nor leftover country names
    if found:
        raise RuntimeError(f"language/country leftovers in {dst_name}: {found}")
    # ensure no bare ISO bm left in smoke queries wrongly
    if dst_name.endswith("_bm25_smoke.py") and '", "bm"' in text:
        raise RuntimeError(f"leftover bm query token in {dst_name}")
    return text


for src_name, dst_name in FILES:
    src = ROOT / src_name
    if not src.is_file():
        raise FileNotFoundError(src)
    (ROOT / dst_name).write_text(adapt(src.read_text(encoding="utf-8"), dst_name), encoding="utf-8")
    print(f"wrote {dst_name}")

wave = Path("/workspace/country-law-triage/next_ir_ok_wave_after_bm.json")
data = json.loads(wave.read_text(encoding="utf-8"))
for entry in data["queue"]:
    if entry.get("slug") == "tuvalu" or entry.get("iso2") == "TV":
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
            "years_attested": [2008, 2009, 2022, 2014, 2017, 2023, 2016, 2012, 2010, 2013, 1997, 1964],
            "gate_years": [int(y) for y in GATE_YEARS],
            "gate_stems": GATE_STEMS,
            "note": f"TV FIRST_IR scaffold; tip MATCH {DST_TIP_SHORT}@289/8141; {HOLD}; soft never-thin ON; SKIP_US; Italy BLOCKED; FIRST of after_bm wave",
        })
        break
else:
    raise RuntimeError("Tuvalu entry missing from wave JSON")
wave.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print("updated wave JSON Tuvalu entry")
print("GATE years", GATE_YEARS)
print("GATE stems", GATE_STEMS)
print("n_gate", len(GATE_YEARS) + len(GATE_STEMS))
