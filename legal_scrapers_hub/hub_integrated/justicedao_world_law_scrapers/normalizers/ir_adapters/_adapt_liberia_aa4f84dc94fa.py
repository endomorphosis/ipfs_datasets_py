#!/usr/bin/env python3
"""Adapt the Tuvalu English memsafe FIRST_IR pack to Liberia LR.

English Liberia; FIRST_IR; HOLD 0 STRICT after-TV (LR→SY→TO→BS→LS→BZ→SB→CW→MU→LC→TJ).
Soft never-thin ON; SKIP_US; Italy BLOCKED. WAVE after_bm second country (after TV LIVE), NOT wave end.
GATE: attested years + English legal stems from articles.parquet tip aa4f84dc94fa.
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
SRC_TIP_FULL = "d7f84a3a4ff7110cd3d660f59054c0abb901d372"
SRC_TIP_SHORT = "d7f84a3a4ff7"
DST_TIP_FULL = "aa4f84dc94fa6f57af2d39219e07bf7429d72454"
DST_TIP_SHORT = "aa4f84dc94fa"
FLOOR_LAWS, FLOOR_ARTS = 160, 7848

# Sampled from data/articles.parquet @ aa4f84dc94fa (~10 years + ~11 stems; include liberia)
GATE_YEARS = ["1956", "1963", "2003", "2006", "2009", "2010", "2017", "2018", "2022", "2023"]
GATE_STEMS = ["shall", "act", "section", "person", "court", "order", "liberia", "chapter", "regulation", "provision", "minister"]
GATE_NOTE_YEARS = "/".join(GATE_YEARS)
GATE_NOTE_STEMS = "/".join(GATE_STEMS)
HOLD = "HOLD 0 STRICT after-TV (LR→SY→TO→BS→LS→BZ→SB→CW→MU→LC→TJ)"

FILES = [
    ("tuvalu_soft_filter.py", "liberia_soft_filter.py"),
    (f"tuvalu_corpus_stream_{SRC_TIP_SHORT}.py", f"liberia_corpus_stream_{DST_TIP_SHORT}.py"),
    (f"tuvalu_encode_memsafe_{SRC_TIP_SHORT}.py", f"liberia_encode_memsafe_{DST_TIP_SHORT}.py"),
    (f"tuvalu_finish_from_emb_{SRC_TIP_SHORT}.py", f"liberia_finish_from_emb_{DST_TIP_SHORT}.py"),
    (f"tuvalu_stream_graph_parts_{SRC_TIP_SHORT}.py", f"liberia_stream_graph_parts_{DST_TIP_SHORT}.py"),
    (f"tuvalu_package_memsafe_{SRC_TIP_SHORT}.py", f"liberia_package_memsafe_{DST_TIP_SHORT}.py"),
    ("tuvalu_upload.py", "liberia_upload.py"),
    ("tuvalu_bm25_smoke.py", "liberia_bm25_smoke.py"),
    ("tuvalu_write_publish_report.py", "liberia_write_publish_report.py"),
    (f"tuvalu_orchestrator_{SRC_TIP_SHORT}.py", f"liberia_orchestrator_{DST_TIP_SHORT}.py"),
]


def adapt(text: str, dst_name: str) -> str:
    # Protect bm25 / BM25 from ISO bm→lr swaps if any residual
    text = text.replace("BM25", "\x00BM25\x00").replace("bm25", "\x00bm25\x00")
    text = text.replace("bmjacency", "adjacency")

    reps = [
        (SRC_TIP_FULL, DST_TIP_FULL),
        (SRC_TIP_SHORT, DST_TIP_SHORT),
        ("endomorphosis/ipfs_tuvalu_laws", "endomorphosis/ipfs_liberia_laws"),
        ("justicedao/ipfs_tuvalu_laws_ir", "justicedao/ipfs_liberia_laws_ir"),
        ("ipfs_tuvalu_laws_ir", "ipfs_liberia_laws_ir"),
        ("ipfs_tuvalu_laws", "ipfs_liberia_laws"),
        ("HOLD 0 STRICT after-BM (TV→LR→SY→TO→BS→LS→BZ→SB→CW→MU→LC→TJ)", HOLD),
        ("after-BM (TV→LR→SY→TO→BS→LS→BZ→SB→CW→MU→LC→TJ)", "after-TV (LR→SY→TO→BS→LS→BZ→SB→CW→MU→LC→TJ)"),
        ("after-BM", "after-TV"),
        ("TV FIRST_IR (not wave end)", "LR FIRST_IR (not wave end)"),
        ("FIRST country of after_bm wave", "second country of after_bm wave (after TV LIVE)"),
        ("FIRST of after_bm wave", "second of after_bm wave (after TV LIVE)"),
        ("www/gov/tv", "www/gov/lr"),
        ("English (Tuvalu)", "English (Liberia)"),
        ("English Tuvalu", "English Liberia"),
        ("Tuvalu", "Liberia"),
        ("tuvalu", "liberia"),
        ('"TV"', '"LR"'),
        ("TV-attested", "LR-attested"),
        ("(TV)", "(LR)"),
        ('"tv"', '"lr"'),
        ("/tv", "/lr"),
        # floors 289/8141 → 160/7848
        ("289/8141", "160/7848"),
        ("289 / 8141", "160 / 7848"),
        ("289, 8141", "160, 7848"),
        ("= 289,", "= 160,"),
        ("= 289", "= 160"),
        ("@ 289/", "@ 160/"),
        (" 289/", " 160/"),
        ("floor 289/", "floor 160/"),
        ("(289/", "(160/"),
        (" 8141", " 7848"),
        ("8141", "7848"),
        ("FLOOR_LAWS, FLOOR_ARTS = 289, 7848", "FLOOR_LAWS, FLOOR_ARTS = 160, 7848"),
        ("FLOOR_LAWS, FLOOR_ARTS = 289, 8141", "FLOOR_LAWS, FLOOR_ARTS = 160, 7848"),
        ("or 289)", "or 160)"),
        ("or 289,", "or 160,"),
    ]
    for a, b in reps:
        text = text.replace(a, b)

    text = text.replace("\x00BM25\x00", "BM25").replace("\x00bm25\x00", "bm25")

    text = text.replace("FLOOR_LAWS, FLOOR_ARTS = 289, 7848", "FLOOR_LAWS, FLOOR_ARTS = 160, 7848")
    text = text.replace("FLOOR_LAWS, FLOOR_ARTS = 160, 8141", "FLOOR_LAWS, FLOOR_ARTS = 160, 7848")

    if dst_name == "liberia_bm25_smoke.py":
        start = text.index("GATE = [")
        end = text.index("]", start) + 1
        years_line = ", ".join(f'"{y}"' for y in GATE_YEARS)
        stems_line = ", ".join(f'"{s}"' for s in GATE_STEMS)
        gate = f"GATE = [\n    {years_line},\n    {stems_line},\n]"
        text = text[:start] + gate + text[end:]
        # Ensure query-only URL tokens
        text = text.replace('QUERIES = GATE + ["www", "gov", "tv"', 'QUERIES = GATE + ["www", "gov", "lr"')
        text = text.replace('QUERIES = GATE + ["www", "gov", "lr"', 'QUERIES = GATE + ["www", "gov", "lr"')
        note = (
            f"attested years {GATE_NOTE_YEARS} plus English legal stems {GATE_NOTE_STEMS} "
            f"from articles.parquet HEAD tip {DST_TIP_SHORT}; URL www/gov/lr is query-only, not GATE."
        )
        text = re.sub(
            r"GATE = attested years [^;]+; URL www/gov/(?:tv|lr) is query-only, not GATE\.",
            f"GATE = {note}",
            text,
        )
        text = text.replace('"tuvalu_pass"', '"liberia_pass"').replace('"liberia_pass"', '"liberia_pass"')
        text = text.replace('"tuvalu_gate"', '"liberia_gate"').replace('"liberia_gate"', '"liberia_gate"')

    if dst_name == "liberia_write_publish_report.py":
        new_gate = f"{GATE_NOTE_YEARS} + stems {GATE_NOTE_STEMS}"
        text = re.sub(
            r"attested years [0-9/]+ \+ stems [a-z/]+",
            f"attested years {new_gate}",
            text,
        )
        text = text.replace("English GATE", "English (Liberia) GATE")
        text = text.replace(
            "HOLD collectors already requested by CoS; lean collectors left running; no SIGTERM this run",
            f"{HOLD}; collectors kept dead (pkill); soft never-thin ON; SKIP_US; Italy BLOCKED; second country of after_bm wave (after TV LIVE)",
        )
        # also catch HOLD already adapted from TV note
        text = re.sub(
            r"HOLD 0 STRICT after-TV[^;]*; collectors kept dead \(pkill\); soft never-thin ON; SKIP_US; Italy BLOCKED;[^\"\n]*",
            f"{HOLD}; collectors kept dead (pkill); soft never-thin ON; SKIP_US; Italy BLOCKED; second country of after_bm wave (after TV LIVE)",
            text,
        )

    leftovers = (
        "French", "Haiti", "Nauru", "Montserrat", "Bermuda", "bermuda",
        "British Virgin Islands", "Gabon", "Togo", "Anguilla", "Cook Islands",
        "Tuvalu", "tuvalu", "bmjacency", "msjacency",
    )
    found = [x for x in leftovers if x in text]
    if found:
        raise RuntimeError(f"language/country leftovers in {dst_name}: {found}")
    if dst_name.endswith("_bm25_smoke.py") and '", "tv"' in text:
        raise RuntimeError(f"leftover tv query token in {dst_name}")
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
    if entry.get("slug") == "liberia" or entry.get("iso2") == "LR":
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
            "years_attested": [1956, 1963, 2023, 2010, 2017, 2006, 2022, 1971, 2003, 2018, 2009],
            "gate_years": [int(y) for y in GATE_YEARS],
            "gate_stems": GATE_STEMS,
            "note": f"LR FIRST_IR scaffold; tip MATCH {DST_TIP_SHORT}@160/7848; {HOLD}; soft never-thin ON; SKIP_US; Italy BLOCKED; second of after_bm wave (after TV LIVE)",
            "status": "CLAIMED",
        })
        break
else:
    raise RuntimeError("Liberia entry missing from wave JSON")
wave.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print("updated wave JSON Liberia entry")
print("GATE years", GATE_YEARS)
print("GATE stems", GATE_STEMS)
print("n_gate", len(GATE_YEARS) + len(GATE_STEMS))
