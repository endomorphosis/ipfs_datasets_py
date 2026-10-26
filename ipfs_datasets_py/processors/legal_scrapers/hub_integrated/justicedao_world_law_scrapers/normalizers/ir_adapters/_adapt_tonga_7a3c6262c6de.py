#!/usr/bin/env python3
"""Adapt the Liberia English memsafe FIRST_IR pack to Tonga TO.

English Tonga; FIRST_IR; HOLD 0 STRICT after-SY (TO→BS→LS→BZ→SB→CW→MU→LC→TJ).
Soft never-thin ON; SKIP_US; Italy BLOCKED. WAVE after_bm fourth country (after TV→LR→SY LIVE), NOT wave end.
GATE: attested years + English legal stems from articles.parquet tip 7a3c6262c6de.
Source tip aa4f84dc94fa (Liberia English) — NOT Syria Arabic years-primary.
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
SRC_TIP_FULL = "aa4f84dc94fa6f57af2d39219e07bf7429d72454"
SRC_TIP_SHORT = "aa4f84dc94fa"
DST_TIP_FULL = "7a3c6262c6de75a8587ff6a9fe0cff087aad98c4"
DST_TIP_SHORT = "7a3c6262c6de"
FLOOR_LAWS, FLOOR_ARTS = 687, 7016

# Sampled from data/articles.parquet @ 7a3c6262c6de (~10 years + ~11 stems; include tonga)
GATE_YEARS = ["2020", "2010", "2014", "2016", "1988", "2025", "2012", "2007", "2019", "2013"]
GATE_STEMS = ["tonga", "section", "act", "part", "shall", "person", "minister", "subsection", "offence", "schedule", "order"]
GATE_NOTE_YEARS = "/".join(GATE_YEARS)
GATE_NOTE_STEMS = "/".join(GATE_STEMS)
HOLD = "HOLD 0 STRICT after-SY (TO→BS→LS→BZ→SB→CW→MU→LC→TJ)"
WAVE_POS = "fourth country of after_bm wave (after TV→LR→SY LIVE)"

FILES = [
    ("liberia_soft_filter.py", "tonga_soft_filter.py"),
    (f"liberia_corpus_stream_{SRC_TIP_SHORT}.py", f"tonga_corpus_stream_{DST_TIP_SHORT}.py"),
    (f"liberia_encode_memsafe_{SRC_TIP_SHORT}.py", f"tonga_encode_memsafe_{DST_TIP_SHORT}.py"),
    (f"liberia_finish_from_emb_{SRC_TIP_SHORT}.py", f"tonga_finish_from_emb_{DST_TIP_SHORT}.py"),
    (f"liberia_stream_graph_parts_{SRC_TIP_SHORT}.py", f"tonga_stream_graph_parts_{DST_TIP_SHORT}.py"),
    (f"liberia_package_memsafe_{SRC_TIP_SHORT}.py", f"tonga_package_memsafe_{DST_TIP_SHORT}.py"),
    ("liberia_upload.py", "tonga_upload.py"),
    ("liberia_bm25_smoke.py", "tonga_bm25_smoke.py"),
    ("liberia_write_publish_report.py", "tonga_write_publish_report.py"),
    (f"liberia_orchestrator_{SRC_TIP_SHORT}.py", f"tonga_orchestrator_{DST_TIP_SHORT}.py"),
]


def adapt(text: str, dst_name: str) -> str:
    # Protect BM25 / bm25 from accidental ISO swaps
    text = text.replace("BM25", "\x00BM25\x00").replace("bm25", "\x00bm25\x00")
    text = text.replace("bmjacency", "adjacency")

    reps = [
        (SRC_TIP_FULL, DST_TIP_FULL),
        (SRC_TIP_SHORT, DST_TIP_SHORT),
        ("endomorphosis/ipfs_liberia_laws", "endomorphosis/ipfs_tonga_laws"),
        ("justicedao/ipfs_liberia_laws_ir", "justicedao/ipfs_tonga_laws_ir"),
        ("ipfs_liberia_laws_ir", "ipfs_tonga_laws_ir"),
        ("ipfs_liberia_laws", "ipfs_tonga_laws"),
        # HOLD / wave position BEFORE bare LR→TO swaps
        ("HOLD 0 STRICT after-TV (LR→SY→TO→BS→LS→BZ→SB→CW→MU→LC→TJ)", HOLD),
        ("after-TV (LR→SY→TO→BS→LS→BZ→SB→CW→MU→LC→TJ)", "after-SY (TO→BS→LS→BZ→SB→CW→MU→LC→TJ)"),
        ("after-TV", "after-SY"),
        ("LR FIRST_IR (not wave end)", "TO FIRST_IR (not wave end)"),
        ("second country of after_bm wave (after TV LIVE)", WAVE_POS),
        ("second of after_bm wave (after TV LIVE)", "fourth of after_bm wave (after TV→LR→SY LIVE)"),
        ("second country of after_bm wave", WAVE_POS),
        ("second of after_bm wave", "fourth of after_bm wave (after TV→LR→SY LIVE)"),
        ("www/gov/lr", "www/gov/to"),
        ("English (Liberia)", "English (Tonga)"),
        ("English Liberia", "English Tonga"),
        ("Liberia", "Tonga"),
        ("liberia", "tonga"),
        # ISO whole-token / path forms only (avoid bare 'to' English false positives)
        ('"LR"', '"TO"'),
        ("LR-attested", "TO-attested"),
        ("(LR)", "(TO)"),
        ('"lr"', '"to"'),
        ("/lr", "/to"),
        # floors 160/7848 → 687/7016
        ("160/7848", "687/7016"),
        ("160 / 7848", "687 / 7016"),
        ("160, 7848", "687, 7016"),
        ("= 160,", "= 687,"),
        ("= 160", "= 687"),
        ("@ 160/", "@ 687/"),
        (" 160/", " 687/"),
        ("floor 160/", "floor 687/"),
        ("(160/", "(687/"),
        (" 7848", " 7016"),
        ("7848", "7016"),
        ("FLOOR_LAWS, FLOOR_ARTS = 160, 7016", "FLOOR_LAWS, FLOOR_ARTS = 687, 7016"),
        ("FLOOR_LAWS, FLOOR_ARTS = 160, 7848", "FLOOR_LAWS, FLOOR_ARTS = 687, 7016"),
        ("or 160)", "or 687)"),
        ("or 160,", "or 687,"),
    ]
    for a, b in reps:
        text = text.replace(a, b)

    text = text.replace("\x00BM25\x00", "BM25").replace("\x00bm25\x00", "bm25")

    text = text.replace("FLOOR_LAWS, FLOOR_ARTS = 160, 7016", "FLOOR_LAWS, FLOOR_ARTS = 687, 7016")
    text = text.replace("FLOOR_LAWS, FLOOR_ARTS = 687, 7848", "FLOOR_LAWS, FLOOR_ARTS = 687, 7016")

    if dst_name == "tonga_bm25_smoke.py":
        start = text.index("GATE = [")
        end = text.index("]", start) + 1
        years_line = ", ".join(f'"{y}"' for y in GATE_YEARS)
        stems_line = ", ".join(f'"{s}"' for s in GATE_STEMS)
        gate = f"GATE = [\n    {years_line},\n    {stems_line},\n]"
        text = text[:start] + gate + text[end:]
        text = text.replace('QUERIES = GATE + ["www", "gov", "lr"', 'QUERIES = GATE + ["www", "gov", "to"')
        text = text.replace('QUERIES = GATE + ["www", "gov", "to"', 'QUERIES = GATE + ["www", "gov", "to"')
        note = (
            f"attested years {GATE_NOTE_YEARS} plus English legal stems {GATE_NOTE_STEMS} "
            f"from articles.parquet HEAD tip {DST_TIP_SHORT}; URL www/gov/to is query-only, not GATE."
        )
        text = re.sub(
            r"GATE = attested years [^;]+; URL www/gov/(?:lr|to) is query-only, not GATE\.",
            f"GATE = {note}",
            text,
        )
        text = text.replace('"liberia_pass"', '"tonga_pass"').replace('"tonga_pass"', '"tonga_pass"')
        text = text.replace('"liberia_gate"', '"tonga_gate"').replace('"tonga_gate"', '"tonga_gate"')

    if dst_name == "tonga_write_publish_report.py":
        new_gate = f"{GATE_NOTE_YEARS} + stems {GATE_NOTE_STEMS}"
        text = re.sub(
            r"attested years [0-9/]+ \+ stems [a-z/]+",
            f"attested years {new_gate}",
            text,
        )
        text = text.replace("English GATE", "English (Tonga) GATE")
        text = re.sub(
            r"HOLD 0 STRICT after-SY[^;]*; collectors kept dead \(pkill\); soft never-thin ON; SKIP_US; Italy BLOCKED;[^\"\n]*",
            f"{HOLD}; collectors kept dead (pkill); soft never-thin ON; SKIP_US; Italy BLOCKED; {WAVE_POS}",
            text,
        )
        # catch residual after-TV / second-country wording
        text = text.replace(
            "second country of after_bm wave (after TV LIVE)",
            WAVE_POS,
        )

    leftovers = (
        "French", "Haiti", "Nauru", "Montserrat", "Bermuda", "bermuda",
        "British Virgin Islands", "Gabon", "Togo", "Anguilla", "Cook Islands",
        "Tuvalu", "tuvalu", "Liberia", "liberia", "Syria", "syria", "Arabic",
        "arabic", "bmjacency", "msjacency",
    )
    found = [x for x in leftovers if x in text]
    if found:
        raise RuntimeError(f"language/country leftovers in {dst_name}: {found}")
    if dst_name.endswith("_bm25_smoke.py") and '", "lr"' in text:
        raise RuntimeError(f"leftover lr query token in {dst_name}")
    if dst_name.endswith("_bm25_smoke.py") and "www/gov/lr" in text:
        raise RuntimeError(f"leftover gov/lr in {dst_name}")
    # reject bare ISO leftovers that should have been swapped
    # Allow intentional wave-position mention "after TV→LR→SY LIVE"
    scrub = text.replace("TV→LR→SY", "TV→XX→SY")
    if '"LR"' in scrub or "(LR)" in scrub or "LR→" in scrub or "LR-attested" in scrub:
        raise RuntimeError(f"leftover LR tokens in {dst_name}")
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
    if entry.get("slug") == "tonga" or entry.get("iso2") == "TO":
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
            "years_attested": [2020, 2010, 2014, 2016, 1988, 2025, 2012, 2007, 2019, 2013],
            "gate_years": [int(y) for y in GATE_YEARS],
            "gate_stems": GATE_STEMS,
            "note": (
                f"TO FIRST_IR scaffold; tip MATCH {DST_TIP_SHORT}@687/7016; {HOLD}; "
                f"soft never-thin ON; SKIP_US; Italy BLOCKED; fourth of after_bm wave (after TV→LR→SY LIVE)"
            ),
            "status": "CLAIMED",
        })
        break
else:
    raise RuntimeError("Tonga entry missing from wave JSON")
wave.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print("updated wave JSON Tonga entry")
print("GATE years", GATE_YEARS)
print("GATE stems", GATE_STEMS)
print("n_gate", len(GATE_YEARS) + len(GATE_STEMS))
