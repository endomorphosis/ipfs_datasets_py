#!/usr/bin/env python3
"""Adapt the Saint Lucia English memsafe FIRST_IR pack to Tajikistan TJ tip a65dcc660a43.

Russian/Tajik Cyrillic Tajikistan; FIRST_IR; HOLD 0 STRICT after-LC (TJ WAVE END).
Soft never-thin ON; SKIP_US; Italy BLOCKED. WAVE END of after_bm (after TV→…→LC LIVE).
GATE: YEARS-PRIMARY (~21 attested ASCII years). Cyrillic stems are query-only only
(FTS often does NOT index Cyrillic stems — TM/KG/PS Cyrillic/Arabic lesson).
URL tokens query-only. Do NOT start any next country after LIVE.
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
SRC_TIP_FULL = "2216d124ae8531c4c0752eea40ef57732e8e86f6"
SRC_TIP_SHORT = "2216d124ae85"
DST_TIP_FULL = "a65dcc660a4365d4b07820f83c6e2bad1f629b20"
DST_TIP_SHORT = "a65dcc660a43"
FLOOR_LAWS, FLOOR_ARTS = 497, 4937

# Sampled from data/articles.parquet @ a65dcc660a43 (ASCII 4-digit years only; ~21 for GATE)
GATE_YEARS = [
    "2019", "2026", "2022", "2020", "2023", "2025", "2021", "2024",
    "1998", "2010", "2012", "2002", "2007", "2003", "2006", "2013",
    "2018", "2009", "2017", "2008", "1999",
]
# Query-only Cyrillic stems (NEVER required for smoke PASS / never put in GATE)
CYRILLIC_STEMS_QUERY_ONLY = [
    "статья", "республики", "таджикистан", "закон", "право", "суда", "кодекса", "права",
]
YEARS_ATTESTED = [int(y) for y in GATE_YEARS]
GATE_NOTE_YEARS = "/".join(GATE_YEARS)
HOLD = "HOLD 0 STRICT after-LC (TJ WAVE END)"
WAVE_POS = "WAVE END of after_bm wave (after TV→LR→SY→TO→BS→LS→BZ→SB→CW→MU→LC LIVE)"

FILES = [
    ("saint_lucia_soft_filter.py", "tajikistan_soft_filter.py"),
    (f"saint_lucia_corpus_stream_{SRC_TIP_SHORT}.py", f"tajikistan_corpus_stream_{DST_TIP_SHORT}.py"),
    (f"saint_lucia_encode_memsafe_{SRC_TIP_SHORT}.py", f"tajikistan_encode_memsafe_{DST_TIP_SHORT}.py"),
    (f"saint_lucia_finish_from_emb_{SRC_TIP_SHORT}.py", f"tajikistan_finish_from_emb_{DST_TIP_SHORT}.py"),
    (f"saint_lucia_stream_graph_parts_{SRC_TIP_SHORT}.py", f"tajikistan_stream_graph_parts_{DST_TIP_SHORT}.py"),
    (f"saint_lucia_package_memsafe_{SRC_TIP_SHORT}.py", f"tajikistan_package_memsafe_{DST_TIP_SHORT}.py"),
    ("saint_lucia_upload.py", "tajikistan_upload.py"),
    ("saint_lucia_bm25_smoke.py", "tajikistan_bm25_smoke.py"),
    ("saint_lucia_write_publish_report.py", "tajikistan_write_publish_report.py"),
    (f"saint_lucia_orchestrator_{SRC_TIP_SHORT}.py", f"tajikistan_orchestrator_{DST_TIP_SHORT}.py"),
]


def adapt(text: str, dst_name: str) -> str:
    text = text.replace("BM25", "\x00BM25\x00").replace("bm25", "\x00bm25\x00")
    # Protect wave chains / HOLD fragments before ISO / name swaps
    text = text.replace("TV→LR→SY→TO→BS→LS→BZ→SB→CW→MU", "\x00WAVECHAIN11\x00")
    text = text.replace("LC→TJ WAVE END", "\x00DESTCHAIN\x00")
    text = text.replace("LC→TJ", "\x00DESTCHAIN_SHORT\x00")
    text = text.replace("after-MU", "\x00AFTERMU\x00")
    text = text.replace("after MU ", "\x00AFTERMU_SP\x00")
    text = text.replace("after-LC", "\x00AFTERLC\x00")

    reps = [
        (SRC_TIP_FULL, DST_TIP_FULL),
        (SRC_TIP_SHORT, DST_TIP_SHORT),
        ("endomorphosis/ipfs_saint_lucia_laws", "endomorphosis/ipfs_tajikistan_laws"),
        ("justicedao/ipfs_saint_lucia_laws_ir", "justicedao/ipfs_tajikistan_laws_ir"),
        ("ipfs_saint_lucia_laws_ir", "ipfs_tajikistan_laws_ir"),
        ("ipfs_saint_lucia_laws", "ipfs_tajikistan_laws"),
        ("HOLD 0 STRICT \x00AFTERMU\x00 (\x00DESTCHAIN\x00)", HOLD),
        ("HOLD 0 STRICT after-MU (LC→TJ WAVE END)", HOLD),
        ("after-MU (LC→TJ WAVE END)", "after-LC (TJ WAVE END)"),
        ("LC FIRST_IR (not wave end)", "TJ FIRST_IR (WAVE END)"),
        (
            "eleventh country of after_bm wave (after TV→LR→SY→TO→BS→LS→BZ→SB→CW→MU LIVE)",
            WAVE_POS,
        ),
        (
            "eleventh of after_bm wave (after TV→LR→SY→TO→BS→LS→BZ→SB→CW→MU LIVE)",
            WAVE_POS,
        ),
        ("eleventh country of after_bm wave", WAVE_POS),
        ("eleventh of after_bm wave", WAVE_POS),
        ("www/gov/lc", "www/gov/tj"),
        ("English (Saint Lucia)", "Russian years-primary (Tajikistan)"),
        ("English Saint Lucia", "Russian Tajikistan"),
        ("Saint Lucia", "Tajikistan"),
        ("saint_lucia_ranked", "tajikistan_ranked"),
        ("saint_lucia_gate", "tajikistan_gate"),
        ("saint_lucia_pass", "tajikistan_pass"),
        ("saint_lucia_encode_memsafe", "tajikistan_encode_memsafe"),
        ("saint_lucia_package_memsafe", "tajikistan_package_memsafe"),
        ("saint_lucia_corpus_stream", "tajikistan_corpus_stream"),
        ("saint_lucia_encode_done", "tajikistan_encode_done"),
        ("saint_lucia_", "tajikistan_"),
        ("saint_lucia", "tajikistan"),
        ('"LC"', '"TJ"'),
        ("LC-attested", "TJ-attested"),
        ("(LC)", "(TJ)"),
        ('"lc"', '"tj"'),
        ("/lc", "/tj"),
        # floors 150/5078 → 497/4937
        ("150/5078", "497/4937"),
        ("150 / 5078", "497 / 4937"),
        ("150, 5078", "497, 4937"),
        ("FLOOR_LAWS, FLOOR_ARTS = 150, 5078", "FLOOR_LAWS, FLOOR_ARTS = 497, 4937"),
        ("or 150)", "or 497)"),
        ("or 150,", "or 497,"),
        ("or 150}", "or 497}"),
        ("= 150,", "= 497,"),
        ("= 150", "= 497"),
        ("@ 150/", "@ 497/"),
        (" 150/", " 497/"),
        ("floor 150/", "floor 497/"),
        ("(150/", "(497/"),
        (" or 150", " or 497"),
        (" 5078", " 4937"),
        ("5078", "4937"),
    ]
    for a, b in reps:
        text = text.replace(a, b)

    text = text.replace("\x00BM25\x00", "BM25").replace("\x00bm25\x00", "bm25")
    text = text.replace("\x00WAVECHAIN11\x00", "TV→LR→SY→TO→BS→LS→BZ→SB→CW→MU")
    text = text.replace("\x00DESTCHAIN\x00", "TJ WAVE END")
    text = text.replace("\x00DESTCHAIN_SHORT\x00", "TJ")
    text = text.replace("\x00AFTERMU\x00", "after-LC")
    text = text.replace("\x00AFTERMU_SP\x00", "after LC ")
    text = text.replace("\x00AFTERLC\x00", "after-LC")

    text = text.replace("FLOOR_LAWS, FLOOR_ARTS = 150, 4937", "FLOOR_LAWS, FLOOR_ARTS = 497, 4937")
    text = text.replace("FLOOR_LAWS, FLOOR_ARTS = 497, 5078", "FLOOR_LAWS, FLOOR_ARTS = 497, 4937")
    text = text.replace('"name": "Tajikistan"', '"name": "Tajikistan"')
    text = text.replace('"name": "Saint_Lucia"', '"name": "Tajikistan"')

    if dst_name == "tajikistan_bm25_smoke.py":
        start = text.index("GATE = [")
        end = text.index("]", start) + 1
        years_line = ", ".join(f'"{y}"' for y in GATE_YEARS)
        gate = f"GATE = [\n    {years_line},\n]"
        text = text[:start] + gate + text[end:]
        stems_q = ", ".join(f'"{s}"' for s in CYRILLIC_STEMS_QUERY_ONLY)
        text = re.sub(
            r"QUERIES = GATE \+ \[[^\]]*\]",
            f'QUERIES = GATE + ["www", "gov", "tj", {stems_q}, "law", "shall"]',
            text,
            count=1,
        )
        text = re.sub(
            r'"""BM25 smoke for Tajikistan IR.*?"""',
            '"""BM25 smoke for Tajikistan IR — Russian/Tajik Cyrillic legal corpus; years-primary FTS gate.\n\n'
            "Years are the primary gate because Cyrillic stems are often unindexed by FTS\n"
            "(TM/KG/PS Cyrillic/Arabic FTS lesson). GATE is attested ASCII years only; Cyrillic stems\n"
            "and URL www/gov/tj are query-only, never GATE. Every GATE year must rank a hit.\n"
            '"""',
            text,
            count=1,
            flags=re.S,
        )
        note = (
            f"Years-primary Russian GATE (Cyrillic stems unindexed by FTS): attested years {GATE_NOTE_YEARS} "
            f"from articles.parquet HEAD tip {DST_TIP_SHORT}; Cyrillic stems "
            f"{'/'.join(CYRILLIC_STEMS_QUERY_ONLY)} and URL www/gov/tj are query-only, not GATE."
        )
        text = re.sub(
            r'"tokenizer_note":\s*"[^"]*"',
            f'"tokenizer_note": "{note}"',
            text,
            count=1,
        )
        text = re.sub(
            r"GATE = attested years [^;]+; URL www/gov/(?:lc|tj) is query-only, not GATE\.",
            f"GATE = {note}",
            text,
        )
        text = text.replace(
            "attested Tajikistan years and English legal stems",
            "attested Tajikistan years (years-primary; Cyrillic query-only)",
        )
        text = text.replace(
            "attested Saint Lucia years and English legal stems",
            "attested Tajikistan years (years-primary; Cyrillic query-only)",
        )

    if dst_name == "tajikistan_write_publish_report.py":
        gate_note = (
            f"BM25 PASS on Tajikistan years-primary Russian GATE ({GATE_NOTE_YEARS}); "
            f"Cyrillic {'/'.join(CYRILLIC_STEMS_QUERY_ONLY)} are query-only only because FTS often leaves "
            f"Cyrillic stems unindexed; URL www/gov/tj is query-only, not GATE"
        )
        text = re.sub(
            r'BM25 PASS on Tajikistan[^"]*"',
            gate_note + '"',
            text,
            count=1,
        )
        text = re.sub(
            r'BM25 PASS on [^"]*GATE[^"]*"',
            gate_note + '"',
            text,
            count=1,
        )
        text = text.replace("English GATE", "Russian years-primary GATE")
        text = text.replace(
            "ASCII-fold Russian years-primary (Tajikistan) GATE",
            "years-primary Russian GATE",
        )
        text = text.replace(
            "ASCII-fold English (Tajikistan) GATE",
            "years-primary Russian GATE",
        )
        text = re.sub(
            r"HOLD 0 STRICT after-LC[^;]*; collectors kept dead \(pkill\); soft never-thin ON; SKIP_US; Italy BLOCKED;[^\"\n]*",
            f"{HOLD}; collectors kept dead (pkill); soft never-thin ON; SKIP_US; Italy BLOCKED; {WAVE_POS}",
            text,
        )
        text = re.sub(
            r"HOLD 0 STRICT after-MU[^;]*; collectors kept dead \(pkill\); soft never-thin ON; SKIP_US; Italy BLOCKED;[^\"\n]*",
            f"{HOLD}; collectors kept dead (pkill); soft never-thin ON; SKIP_US; Italy BLOCKED; {WAVE_POS}",
            text,
        )
        text = text.replace("www/gov/lc is query-only", "www/gov/tj is query-only")

    leftovers = (
        "Saint Lucia", "saint_lucia", "Mauritius", "mauritius",
        "Curaçao", "Curacao", "curacao", "Dutch",
        "Solomon Islands", "solomonislands", "Belize", "belize",
        "Lesotho", "lesotho", "French", "Haiti", "Nauru", "Montserrat",
        "Bermuda", "bermuda", "British Virgin Islands", "Gabon", "Togo",
        "Anguilla", "Cook Islands", "Tuvalu", "tuvalu", "Liberia", "liberia",
        "Syria", "syria", "Tonga", "tonga",
        "Bahamas", "bahamas", "bmjacency", "msjacency",
        "lucia", "English (Saint", "English Saint",
    )
    # Allow English/Arabic only as FTS-lesson / query-only diagnostic wording
    found = [x for x in leftovers if x in text]
    if found:
        raise RuntimeError(f"language/country leftovers in {dst_name}: {found}")
    if dst_name.endswith("_bm25_smoke.py"):
        if '", "lc"' in text or "www/gov/lc" in text:
            raise RuntimeError(f"leftover lc query token in {dst_name}")
        gate_slice = text[text.index("GATE = ["): text.index("]", text.index("GATE = [")) + 1]
        for bad in (
            "shall", "act", "section", "person", "court", "order", "minister",
            "offence", "subsection", "schedule", "lucia", "статья", "закон",
            "республики", "таджикистан", "право", "суда", "кодекса", "права",
        ):
            if f'"{bad}"' in gate_slice:
                raise RuntimeError(f"non-year token in GATE of {dst_name}: {bad}")
    # scrub ISO leftovers carefully
    scrub = text
    scrub = scrub.replace("TV→LR→SY→TO→BS→LS→BZ→SB→CW→MU", "TV→XX")
    scrub = scrub.replace("after-LC", "after-XX")
    scrub = scrub.replace("after LC ", "after XX ")
    scrub = scrub.replace("TJ WAVE END", "XX")
    if '"LC"' in scrub or "(LC)" in scrub or "LC→" in scrub or "LC-attested" in scrub:
        raise RuntimeError(f"leftover LC tokens in {dst_name}")
    if "Saint Lucia" in text or "saint_lucia" in text:
        raise RuntimeError(f"leftover Saint Lucia in {dst_name}")
    if "ipfs_saint_lucia" in text:
        raise RuntimeError(f"leftover saint_lucia path in {dst_name}")
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
    if entry.get("slug") == "tajikistan" or entry.get("iso2") == "TJ":
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
            "language": "Russian",
            "lang": "Russian",
            "wave_end": True,
            "years_attested": YEARS_ATTESTED,
            "gate_years": [int(y) for y in GATE_YEARS],
            "gate_stems": [],  # years-primary; Cyrillic stems query-only
            "cyrillic_stems_query_only": CYRILLIC_STEMS_QUERY_ONLY,
            "note": (
                f"TJ FIRST_IR scaffold; tip MATCH {DST_TIP_SHORT}@497/4937; {HOLD}; "
                f"soft never-thin ON; SKIP_US; Italy BLOCKED; {WAVE_POS}; "
                f"Russian years-primary GATE ({len(GATE_YEARS)} years); Cyrillic stems query-only"
            ),
            "status": "CLAIMED",
        })
        break
else:
    raise RuntimeError("Tajikistan entry missing from wave JSON")
wave.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print("updated wave JSON Tajikistan entry")
print("GATE years", GATE_YEARS)
print("n_gate", len(GATE_YEARS))
print("cyrillic stems query-only", CYRILLIC_STEMS_QUERY_ONLY)
print("HOLD", HOLD)
print("WAVE_POS", WAVE_POS)
