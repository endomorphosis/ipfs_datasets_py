#!/usr/bin/env python3
"""Adapt the Liberia English memsafe FIRST_IR pack to Syria SY tip 8d2537ff5585.

Arabic Syria; FIRST_IR; HOLD 0 STRICT after-LR (SY→TO→BS→LS→BZ→SB→CW→MU→LC→TJ).
Soft never-thin ON; SKIP_US; Italy BLOCKED. WAVE after_bm third country (after TV→LR LIVE), NOT wave end.
GATE: YEARS-PRIMARY (~19 attested ASCII years). Arabic stems are query-only only (FTS often
does not index Arabic stems — Palestine Arabic pack lesson). URL tokens query-only.
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
DST_TIP_FULL = "8d2537ff55851738868c0645bdb9ed31cfeedd0e"
DST_TIP_SHORT = "8d2537ff5585"
FLOOR_LAWS, FLOOR_ARTS = 215, 7194

# Sampled from data/articles.parquet @ 8d2537ff5585 (ASCII 4-digit years only; ~19 for GATE)
GATE_YEARS = [
    "1953", "1958", "1959", "1961", "1963", "1974", "1981",
    "2000", "2001", "2003", "2004", "2005", "2006", "2007", "2008", "2009", "2010", "2011", "2012",
]
# Query-only Arabic stems (NEVER required for smoke PASS / never put in GATE)
ARABIC_STEMS_QUERY_ONLY = ["مادة", "المادة", "قانون", "المرسوم", "السورية", "الجمهورية", "قرار", "مجلس"]
YEARS_ATTESTED = [
    2011, 1953, 2005, 2001, 2010, 1959, 1974, 1958, 2004, 2003, 2000, 2008, 1963, 2012, 2007,
    1961, 2009, 1981, 2006, 1950, 2002,
]
GATE_NOTE_YEARS = "/".join(GATE_YEARS)
HOLD = "HOLD 0 STRICT after-LR (SY→TO→BS→LS→BZ→SB→CW→MU→LC→TJ)"

FILES = [
    ("liberia_soft_filter.py", "syria_soft_filter.py"),
    (f"liberia_corpus_stream_{SRC_TIP_SHORT}.py", f"syria_corpus_stream_{DST_TIP_SHORT}.py"),
    (f"liberia_encode_memsafe_{SRC_TIP_SHORT}.py", f"syria_encode_memsafe_{DST_TIP_SHORT}.py"),
    (f"liberia_finish_from_emb_{SRC_TIP_SHORT}.py", f"syria_finish_from_emb_{DST_TIP_SHORT}.py"),
    (f"liberia_stream_graph_parts_{SRC_TIP_SHORT}.py", f"syria_stream_graph_parts_{DST_TIP_SHORT}.py"),
    (f"liberia_package_memsafe_{SRC_TIP_SHORT}.py", f"syria_package_memsafe_{DST_TIP_SHORT}.py"),
    ("liberia_upload.py", "syria_upload.py"),
    ("liberia_bm25_smoke.py", "syria_bm25_smoke.py"),
    ("liberia_write_publish_report.py", "syria_write_publish_report.py"),
    (f"liberia_orchestrator_{SRC_TIP_SHORT}.py", f"syria_orchestrator_{DST_TIP_SHORT}.py"),
]


def adapt(text: str, dst_name: str) -> str:
    # Protect BM25 identifiers from accidental mutation
    text = text.replace("BM25", "\x00BM25\x00").replace("bm25", "\x00bm25\x00")

    reps = [
        (SRC_TIP_FULL, DST_TIP_FULL),
        (SRC_TIP_SHORT, DST_TIP_SHORT),
        ("endomorphosis/ipfs_liberia_laws", "endomorphosis/ipfs_syria_laws"),
        ("justicedao/ipfs_liberia_laws_ir", "justicedao/ipfs_syria_laws_ir"),
        ("ipfs_liberia_laws_ir", "ipfs_syria_laws_ir"),
        ("ipfs_liberia_laws", "ipfs_syria_laws"),
        ("HOLD 0 STRICT after-TV (LR→SY→TO→BS→LS→BZ→SB→CW→MU→LC→TJ)", HOLD),
        ("after-TV (LR→SY→TO→BS→LS→BZ→SB→CW→MU→LC→TJ)", "after-LR (SY→TO→BS→LS→BZ→SB→CW→MU→LC→TJ)"),
        ("after-TV", "after-LR"),
        ("LR FIRST_IR (not wave end)", "SY FIRST_IR (not wave end)"),
        ("second country of after_bm wave (after TV LIVE)", "third country of after_bm wave (after TV→LR LIVE)"),
        ("second of after_bm wave (after TV LIVE)", "third of after_bm wave (after TV→LR LIVE)"),
        ("www/gov/lr", "www/gov/sy"),
        ("English (Liberia)", "Arabic (Syria)"),
        ("English Liberia", "Arabic Syria"),
        ("Liberia", "Syria"),
        ("liberia", "syria"),
        ('"LR"', '"SY"'),
        ("LR-attested", "SY-attested"),
        ("(LR)", "(SY)"),
        ('"lr"', '"sy"'),
        ("/lr", "/sy"),
        # floors 160/7848 → 215/7194
        ("160/7848", "215/7194"),
        ("160 / 7848", "215 / 7194"),
        ("160, 7848", "215, 7194"),
        ("= 160,", "= 215,"),
        ("= 160", "= 215"),
        ("@ 160/", "@ 215/"),
        (" 160/", " 215/"),
        ("floor 160/", "floor 215/"),
        ("(160/", "(215/"),
        (" 7848", " 7194"),
        ("7848", "7194"),
        ("FLOOR_LAWS, FLOOR_ARTS = 160, 7194", "FLOOR_LAWS, FLOOR_ARTS = 215, 7194"),
        ("FLOOR_LAWS, FLOOR_ARTS = 160, 7848", "FLOOR_LAWS, FLOOR_ARTS = 215, 7194"),
        ("or 160)", "or 215)"),
        ("or 160,", "or 215,"),
    ]
    for a, b in reps:
        text = text.replace(a, b)

    text = text.replace("\x00BM25\x00", "BM25").replace("\x00bm25\x00", "bm25")

    text = text.replace("FLOOR_LAWS, FLOOR_ARTS = 160, 7194", "FLOOR_LAWS, FLOOR_ARTS = 215, 7194")
    text = text.replace("FLOOR_LAWS, FLOOR_ARTS = 215, 7848", "FLOOR_LAWS, FLOOR_ARTS = 215, 7194")

    if dst_name == "syria_bm25_smoke.py":
        # Rewrite entire GATE block to years-only (Arabic stems NEVER in GATE)
        start = text.index("GATE = [")
        end = text.index("]", start) + 1
        years_line = ", ".join(f'"{y}"' for y in GATE_YEARS)
        gate = f"GATE = [\n    {years_line},\n]"
        text = text[:start] + gate + text[end:]
        # Query-only: URL + Arabic stems + a few English diagnostics
        stems_q = ", ".join(f'"{s}"' for s in ARABIC_STEMS_QUERY_ONLY)
        text = re.sub(
            r"QUERIES = GATE \+ \[[^\]]*\]",
            f'QUERIES = GATE + ["www", "gov", "sy", {stems_q}, "law", "shall"]',
            text,
            count=1,
        )
        # Docstring / tokenizer note → years-primary Arabic
        text = re.sub(
            r'"""BM25 smoke for Syria IR.*?"""',
            '"""BM25 smoke for Syria IR — Arabic legal corpus; years-primary FTS gate.\n\n'
            "Years are the primary gate because Arabic stems are often unindexed by FTS\n"
            "(Arabic/Cyrillic FTS lesson). GATE is attested ASCII years only; Arabic stems\n"
            "and URL www/gov/sy are query-only, never GATE. Every GATE year must rank a hit.\n"
            '"""',
            text,
            count=1,
            flags=re.S,
        )
        note = (
            f"Years-primary Arabic GATE (stems unindexed by FTS): attested years {GATE_NOTE_YEARS} "
            f"from articles.parquet HEAD tip {DST_TIP_SHORT}; Arabic stems "
            f"{'/'.join(ARABIC_STEMS_QUERY_ONLY)} and URL www/gov/sy are query-only, not GATE."
        )
        text = re.sub(
            r'"tokenizer_note":\s*"[^"]*"',
            f'"tokenizer_note": "{note}"',
            text,
            count=1,
        )
        # Fallback: if tokenizer_note is inline elsewhere
        text = re.sub(
            r"GATE = attested years [^;]+; URL www/gov/(?:lr|sy) is query-only, not GATE\.",
            f"GATE = {note}",
            text,
        )
        text = text.replace('"syria_pass"', '"syria_pass"')
        text = text.replace('"syria_gate"', '"syria_gate"')

    if dst_name == "syria_write_publish_report.py":
        gate_note = (
            f"BM25 PASS on Syria years-primary Arabic GATE ({GATE_NOTE_YEARS}); "
            f"Arabic {'/'.join(ARABIC_STEMS_QUERY_ONLY)} are query-only only because FTS often leaves "
            f"Arabic stems unindexed; URL www/gov/sy is query-only, not GATE"
        )
        text = re.sub(
            r'BM25 PASS on Syria[^"]*"',
            gate_note + '"',
            text,
            count=1,
        )
        # Also catch if still Liberia-shaped after name swap
        text = re.sub(
            r'BM25 PASS on [^"]*GATE[^"]*"',
            gate_note + '"',
            text,
            count=1,
        )
        text = text.replace("English GATE", "Arabic years-primary GATE")
        text = text.replace("ASCII-fold Arabic (Syria) GATE", "years-primary Arabic GATE")
        text = re.sub(
            r"HOLD 0 STRICT after-LR[^;]*; collectors kept dead \(pkill\); soft never-thin ON; SKIP_US; Italy BLOCKED;[^\"\n]*",
            f"{HOLD}; collectors kept dead (pkill); soft never-thin ON; SKIP_US; Italy BLOCKED; third country of after_bm wave (after TV→LR LIVE)",
            text,
        )
        # Soft filter ranked filter — keep ASCII-only ranked summary key name if present
        text = text.replace("syria_ranked", "syria_ranked")

    leftovers = (
        "French", "Haiti", "Nauru", "Montserrat", "Bermuda", "bermuda",
        "British Virgin Islands", "Gabon", "Togo", "Anguilla", "Cook Islands",
        "Tuvalu", "tuvalu", "Liberia", "liberia", "Palestine", "palestine",
        "Madagascar", "madagascar", "bmjacency", "msjacency",
    )
    # Allow "English" only in comments / query-only diagnostics strings
    found = [x for x in leftovers if x in text]
    if found:
        raise RuntimeError(f"language/country leftovers in {dst_name}: {found}")
    if dst_name.endswith("_bm25_smoke.py"):
        if '", "lr"' in text or '", "tv"' in text or '", "bm"' in text:
            raise RuntimeError(f"leftover ISO query token in {dst_name}")
        # Ensure no English legal stems leaked into GATE
        gate_slice = text[text.index("GATE = ["): text.index("]", text.index("GATE = [")) + 1]
        for bad in ("shall", "act", "section", "person", "court", "order", "chapter", "regulation", "provision", "minister", "مادة", "قانون"):
            if f'"{bad}"' in gate_slice:
                raise RuntimeError(f"non-year token in GATE of {dst_name}: {bad}")
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
    if entry.get("slug") == "syria" or entry.get("iso2") == "SY":
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
            "language": "Arabic",
            "lang": "Arabic",
            "years_attested": YEARS_ATTESTED,
            "gate_years": [int(y) for y in GATE_YEARS],
            "gate_stems": [],  # years-primary; Arabic stems query-only
            "arabic_stems_query_only": ARABIC_STEMS_QUERY_ONLY,
            "note": (
                f"SY FIRST_IR scaffold; tip MATCH {DST_TIP_SHORT}@215/7194; {HOLD}; "
                f"soft never-thin ON; SKIP_US; Italy BLOCKED; third of after_bm wave (after TV→LR LIVE); "
                f"Arabic years-primary GATE ({len(GATE_YEARS)} years)"
            ),
            "status": "CLAIMED",
        })
        break
else:
    raise RuntimeError("Syria entry missing from wave JSON")
wave.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print("updated wave JSON Syria entry")
print("GATE years", GATE_YEARS)
print("n_gate", len(GATE_YEARS))
print("arabic stems query-only", ARABIC_STEMS_QUERY_ONLY)
