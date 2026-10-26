#!/usr/bin/env python3
"""Adapt the Mauritius English memsafe FIRST_IR pack to Saint Lucia LC.

English Saint Lucia; FIRST_IR; HOLD 0 STRICT after-MU (LC→TJ WAVE END).
Soft never-thin ON; SKIP_US; Italy BLOCKED. WAVE after_bm eleventh country
(after TV→LR→SY→TO→BS→LS→BZ→SB→CW→MU LIVE), NOT wave end (TJ is wave end).
GATE: attested years + English legal stems from articles.parquet tip 2216d124ae85
(English dominates; include lucia).
Source tip 94566e522d28 (Mauritius English) — NOT Curaçao Dutch.
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
SRC_TIP_FULL = "94566e522d28037d4b70c7c0bbfea9fc3aa4aadd"
SRC_TIP_SHORT = "94566e522d28"
DST_TIP_FULL = "2216d124ae8531c4c0752eea40ef57732e8e86f6"
DST_TIP_SHORT = "2216d124ae85"
FLOOR_LAWS, FLOOR_ARTS = 150, 5078

# Sampled from data/articles.parquet @ 2216d124ae85 (~10 years + ~11 stems; include lucia)
GATE_YEARS = ["2005", "2001", "2023", "2006", "2020", "2022", "2015", "2018", "2004", "1997"]
GATE_STEMS = [
    "lucia", "shall", "act", "section", "person", "court",
    "order", "minister", "offence", "subsection", "schedule",
]
GATE_NOTE_YEARS = "/".join(GATE_YEARS)
GATE_NOTE_STEMS = "/".join(GATE_STEMS)
HOLD = "HOLD 0 STRICT after-MU (LC→TJ WAVE END)"
WAVE_POS = "eleventh country of after_bm wave (after TV→LR→SY→TO→BS→LS→BZ→SB→CW→MU LIVE)"

FILES = [
    ("mauritius_soft_filter.py", "saint_lucia_soft_filter.py"),
    (f"mauritius_corpus_stream_{SRC_TIP_SHORT}.py", f"saint_lucia_corpus_stream_{DST_TIP_SHORT}.py"),
    (f"mauritius_encode_memsafe_{SRC_TIP_SHORT}.py", f"saint_lucia_encode_memsafe_{DST_TIP_SHORT}.py"),
    (f"mauritius_finish_from_emb_{SRC_TIP_SHORT}.py", f"saint_lucia_finish_from_emb_{DST_TIP_SHORT}.py"),
    (f"mauritius_stream_graph_parts_{SRC_TIP_SHORT}.py", f"saint_lucia_stream_graph_parts_{DST_TIP_SHORT}.py"),
    (f"mauritius_package_memsafe_{SRC_TIP_SHORT}.py", f"saint_lucia_package_memsafe_{DST_TIP_SHORT}.py"),
    ("mauritius_upload.py", "saint_lucia_upload.py"),
    ("mauritius_bm25_smoke.py", "saint_lucia_bm25_smoke.py"),
    ("mauritius_write_publish_report.py", "saint_lucia_write_publish_report.py"),
    (f"mauritius_orchestrator_{SRC_TIP_SHORT}.py", f"saint_lucia_orchestrator_{DST_TIP_SHORT}.py"),
]


def adapt(text: str, dst_name: str) -> str:
    # Protect BM25 / bm25 and intentional wave-chain tokens from ISO swaps
    text = text.replace("BM25", "\x00BM25\x00").replace("bm25", "\x00bm25\x00")
    text = text.replace("bmjacency", "adjacency")
    # Protect full wave-chain mentions that must keep prior LIVE countries incl. MU
    text = text.replace("TV→LR→SY→TO→BS→LS→BZ→SB→CW→MU", "\x00WAVECHAIN11\x00")
    text = text.replace("TV→LR→SY→TO→BS→LS→BZ→SB→CW", "\x00WAVECHAIN10\x00")
    text = text.replace("TV→LR→SY→TO→BS→LS→BZ→SB", "\x00WAVECHAIN9\x00")
    text = text.replace("TV→LR→SY→TO→BS→LS→BZ", "\x00WAVECHAIN8\x00")
    text = text.replace("TV→LR→SY→TO→BS→LS", "\x00WAVECHAIN7\x00")
    text = text.replace("TV→LR→SY→TO→BS", "\x00WAVECHAIN6\x00")
    text = text.replace("TV→LR→SY→TO", "\x00WAVECHAIN5\x00")
    # Protect destination HOLD after-MU; source after-CW must rewrite
    text = text.replace("after-MU", "\x00AFTERMU\x00")
    text = text.replace("after MU ", "\x00AFTERMU_SP\x00")
    text = text.replace("after-CW", "\x00AFTERCW\x00")
    text = text.replace("after CW ", "\x00AFTERCW_SP\x00")
    # Protect HOLD chains before ISO swaps
    text = text.replace("CW→MU→LC→TJ", "\x00HOLDCHAIN_SRC\x00")
    text = text.replace("MU→LC→TJ", "\x00HOLDCHAIN_MID\x00")
    text = text.replace("LC→TJ WAVE END", "\x00DESTCHAIN\x00")
    text = text.replace("LC→TJ", "\x00DESTCHAIN_SHORT\x00")

    reps = [
        (SRC_TIP_FULL, DST_TIP_FULL),
        (SRC_TIP_SHORT, DST_TIP_SHORT),
        ("endomorphosis/ipfs_mauritius_laws", "endomorphosis/ipfs_saint_lucia_laws"),
        ("justicedao/ipfs_mauritius_laws_ir", "justicedao/ipfs_saint_lucia_laws_ir"),
        ("ipfs_mauritius_laws_ir", "ipfs_saint_lucia_laws_ir"),
        ("ipfs_mauritius_laws", "ipfs_saint_lucia_laws"),
        # HOLD / wave position BEFORE bare MU→LC swaps
        ("HOLD 0 STRICT \x00AFTERCW\x00 (\x00HOLDCHAIN_MID\x00)", HOLD),
        ("HOLD 0 STRICT after-CW (MU→LC→TJ)", HOLD),
        ("after-CW (MU→LC→TJ)", "after-MU (LC→TJ WAVE END)"),
        ("MU FIRST_IR (not wave end)", "LC FIRST_IR (not wave end)"),
        ("tenth country of after_bm wave (after TV→LR→SY→TO→BS→LS→BZ→SB→CW LIVE)", WAVE_POS),
        ("tenth of after_bm wave (after TV→LR→SY→TO→BS→LS→BZ→SB→CW LIVE)",
         "eleventh of after_bm wave (after TV→LR→SY→TO→BS→LS→BZ→SB→CW→MU LIVE)"),
        ("tenth country of after_bm wave", WAVE_POS),
        ("tenth of after_bm wave",
         "eleventh of after_bm wave (after TV→LR→SY→TO→BS→LS→BZ→SB→CW→MU LIVE)"),
        ("www/gov/mu", "www/gov/lc"),
        ("English (Mauritius)", "English (Saint Lucia)"),
        ("English Mauritius", "English Saint Lucia"),
        ("Mauritius", "Saint Lucia"),
        # slug / path forms (underscore)
        ("mauritius_ranked", "saint_lucia_ranked"),
        ("mauritius_gate", "saint_lucia_gate"),
        ("mauritius_pass", "saint_lucia_pass"),
        ("mauritius_encode_memsafe", "saint_lucia_encode_memsafe"),
        ("mauritius_package_memsafe", "saint_lucia_package_memsafe"),
        ("mauritius_corpus_stream", "saint_lucia_corpus_stream"),
        ("mauritius_encode_done", "saint_lucia_encode_done"),
        ("mauritius_", "saint_lucia_"),
        ("mauritius", "saint_lucia"),
        # ISO whole-token / path forms only
        ('"MU"', '"LC"'),
        ("MU-attested", "LC-attested"),
        ("(MU)", "(LC)"),
        ('"mu"', '"lc"'),
        ("/mu", "/lc"),
        # floors 158/5451 → 150/5078
        ("158/5451", "150/5078"),
        ("158 / 5451", "150 / 5078"),
        ("158, 5451", "150, 5078"),
        ("FLOOR_LAWS, FLOOR_ARTS = 158, 5451", "FLOOR_LAWS, FLOOR_ARTS = 150, 5078"),
        ("or 158)", "or 150)"),
        ("or 158,", "or 150,"),
        ("or 158}", "or 150}"),
        ("= 158,", "= 150,"),
        ("= 158", "= 150"),
        ("@ 158/", "@ 150/"),
        (" 158/", " 150/"),
        ("floor 158/", "floor 150/"),
        ("(158/", "(150/"),
        (" or 158", " or 150"),
        (" 5451", " 5078"),
        ("5451", "5078"),
    ]
    for a, b in reps:
        text = text.replace(a, b)

    text = text.replace("\x00BM25\x00", "BM25").replace("\x00bm25\x00", "bm25")
    text = text.replace("\x00WAVECHAIN11\x00", "TV→LR→SY→TO→BS→LS→BZ→SB→CW→MU")
    text = text.replace("\x00WAVECHAIN10\x00", "TV→LR→SY→TO→BS→LS→BZ→SB→CW")
    text = text.replace("\x00WAVECHAIN9\x00", "TV→LR→SY→TO→BS→LS→BZ→SB")
    text = text.replace("\x00WAVECHAIN8\x00", "TV→LR→SY→TO→BS→LS→BZ")
    text = text.replace("\x00WAVECHAIN7\x00", "TV→LR→SY→TO→BS→LS")
    text = text.replace("\x00WAVECHAIN6\x00", "TV→LR→SY→TO→BS")
    text = text.replace("\x00WAVECHAIN5\x00", "TV→LR→SY→TO")
    text = text.replace("\x00DESTCHAIN\x00", "LC→TJ WAVE END")
    text = text.replace("\x00DESTCHAIN_SHORT\x00", "LC→TJ")
    text = text.replace("\x00HOLDCHAIN_MID\x00", "LC→TJ WAVE END")  # after after-MU rewrite of MU→LC→TJ
    text = text.replace("\x00HOLDCHAIN_SRC\x00", "LC→TJ WAVE END")
    text = text.replace("\x00AFTERMU\x00", "after-MU")
    text = text.replace("\x00AFTERMU_SP\x00", "after MU ")
    # Source after-CW that wasn't rewritten via full HOLD → after-MU
    text = text.replace("\x00AFTERCW\x00", "after-MU")
    text = text.replace("\x00AFTERCW_SP\x00", "after MU ")

    text = text.replace("FLOOR_LAWS, FLOOR_ARTS = 158, 5078", "FLOOR_LAWS, FLOOR_ARTS = 150, 5078")
    text = text.replace("FLOOR_LAWS, FLOOR_ARTS = 150, 5451", "FLOOR_LAWS, FLOOR_ARTS = 150, 5078")
    text = text.replace("or 158)", "or 150)")
    text = text.replace("or 158,", "or 150,")
    text = text.replace("or 158}", "or 150}")

    # Fix pack_meta name if still slug-title
    text = text.replace('"name": "Saint_Lucia"', '"name": "Saint Lucia"')
    text = text.replace('"name": "Saint lucia"', '"name": "Saint Lucia"')

    if dst_name == "saint_lucia_bm25_smoke.py":
        start = text.index("GATE = [")
        end = text.index("]", start) + 1
        years_line = ", ".join(f'"{y}"' for y in GATE_YEARS)
        stems_line = ", ".join(f'"{s}"' for s in GATE_STEMS)
        gate = f"GATE = [\n    {years_line},\n    {stems_line},\n]"
        text = text[:start] + gate + text[end:]
        text = text.replace(
            'QUERIES = GATE + ["www", "gov", "mu"',
            'QUERIES = GATE + ["www", "gov", "lc"',
        )
        text = text.replace(
            'QUERIES = GATE + ["www", "gov", "lc"',
            'QUERIES = GATE + ["www", "gov", "lc"',
        )
        note = (
            f"attested years {GATE_NOTE_YEARS} plus English legal stems {GATE_NOTE_STEMS} "
            f"from articles.parquet HEAD tip {DST_TIP_SHORT}; URL www/gov/lc is query-only, not GATE."
        )
        text = re.sub(
            r"GATE = attested years [^;]+; URL www/gov/(?:mu|lc) is query-only, not GATE\.",
            f"GATE = {note}",
            text,
        )
        text = text.replace('"mauritius_pass"', '"saint_lucia_pass"')
        text = text.replace('"saint_lucia_pass"', '"saint_lucia_pass"')
        text = text.replace('"mauritius_gate"', '"saint_lucia_gate"')
        text = text.replace('"saint_lucia_gate"', '"saint_lucia_gate"')
        text = text.replace(
            "attested Mauritius years and English legal stems",
            "attested Saint Lucia years and English legal stems",
        )
        text = text.replace(
            "attested Saint Lucia years and English legal stems",
            "attested Saint Lucia years and English legal stems",
        )

    if dst_name == "saint_lucia_write_publish_report.py":
        new_gate = f"{GATE_NOTE_YEARS} + stems {GATE_NOTE_STEMS}"
        text = re.sub(
            r"attested years [0-9/]+ \+ stems [a-z_/]+",
            f"attested years {new_gate}",
            text,
        )
        text = text.replace("English GATE", "English (Saint Lucia) GATE")
        text = text.replace(
            "ASCII-fold English (Saint Lucia) GATE",
            "ASCII-fold English (Saint Lucia) GATE",
        )
        text = re.sub(
            r"HOLD 0 STRICT after-MU[^;]*; collectors kept dead \(pkill\); soft never-thin ON; SKIP_US; Italy BLOCKED;[^\"\n]*",
            f"{HOLD}; collectors kept dead (pkill); soft never-thin ON; SKIP_US; Italy BLOCKED; {WAVE_POS}",
            text,
        )
        text = re.sub(
            r"HOLD 0 STRICT after-CW[^;]*; collectors kept dead \(pkill\); soft never-thin ON; SKIP_US; Italy BLOCKED;[^\"\n]*",
            f"{HOLD}; collectors kept dead (pkill); soft never-thin ON; SKIP_US; Italy BLOCKED; {WAVE_POS}",
            text,
        )
        text = text.replace(
            "tenth country of after_bm wave (after TV→LR→SY→TO→BS→LS→BZ→SB→CW LIVE)",
            WAVE_POS,
        )
        text = text.replace(
            "eleventh country of after_bm wave (after TV→LR→SY→TO→BS→LS→BZ→SB→CW LIVE)",
            WAVE_POS,
        )
        text = text.replace("www/gov/mu is query-only", "www/gov/lc is query-only")

    leftovers = (
        "Mauritius", "mauritius",
        "Curaçao", "Curacao", "curacao", "Dutch",
        "Solomon Islands", "solomonislands", "solomon",
        "Belize", "belize", "Lesotho", "lesotho",
        "French", "Haiti", "Nauru", "Montserrat", "Bermuda", "bermuda",
        "British Virgin Islands", "Gabon", "Togo", "Anguilla", "Cook Islands",
        "Tuvalu", "tuvalu", "Liberia", "liberia", "Syria", "syria", "Arabic",
        "arabic", "Tonga", "tonga", "Bahamas", "bahamas",
        "bmjacency", "msjacency",
        "English (Mauritius", "English Mauritius",
    )
    found = [x for x in leftovers if x in text]
    if found:
        raise RuntimeError(f"language/country leftovers in {dst_name}: {found}")
    if dst_name.endswith("_bm25_smoke.py") and '", "mu"' in text:
        raise RuntimeError(f"leftover mu query token in {dst_name}")
    if dst_name.endswith("_bm25_smoke.py") and "www/gov/mu" in text:
        raise RuntimeError(f"leftover gov/mu in {dst_name}")
    # reject bare ISO leftovers that should have been swapped
    scrub = text.replace("TV→LR→SY→TO→BS→LS→BZ→SB→CW→MU", "TV→XX→SY→XX→XX→XX→XX→XX→XX→XX")
    scrub = scrub.replace("TV→LR→SY→TO→BS→LS→BZ→SB→CW", "TV→XX→SY→XX→XX→XX→XX→XX→XX")
    scrub = scrub.replace("TV→LR→SY→TO→BS→LS→BZ→SB", "TV→XX→SY→XX→XX→XX→XX→XX")
    scrub = scrub.replace("TV→LR→SY→TO→BS→LS→BZ", "TV→XX→SY→XX→XX→XX→XX")
    scrub = scrub.replace("TV→LR→SY→TO→BS→LS", "TV→XX→SY→XX→XX→XX")
    scrub = scrub.replace("TV→LR→SY→TO→BS", "TV→XX→SY→XX→XX")
    scrub = scrub.replace("TV→LR→SY→TO", "TV→XX→SY→XX")
    scrub = scrub.replace("after-MU", "after-XX")
    scrub = scrub.replace("after MU ", "after XX ")
    scrub = scrub.replace("after-CW", "after-XX")
    scrub = scrub.replace("LC→TJ WAVE END", "XX→XX")
    scrub = scrub.replace("LC→TJ", "XX→XX")
    scrub = scrub.replace("MU→LC→TJ", "XX→XX→XX")
    scrub = scrub.replace("CW→MU→LC→TJ", "XX→XX→XX→XX")
    if '"MU"' in scrub or "(MU)" in scrub or "MU→" in scrub or "MU-attested" in scrub:
        raise RuntimeError(f"leftover MU tokens in {dst_name}")
    if "Mauritius" in text or "mauritius" in text:
        raise RuntimeError(f"leftover Mauritius in {dst_name}")
    if "ipfs_mauritius" in text:
        raise RuntimeError(f"leftover mauritius path in {dst_name}")
    if "Cura" in text or "curacao" in text or "Dutch" in text:
        raise RuntimeError(f"leftover Curaçao/Dutch in {dst_name}")
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
    if entry.get("slug") == "saint_lucia" or entry.get("iso2") == "LC":
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
            "lang": "English",
            "years_attested": [int(y) for y in GATE_YEARS],
            "gate_years": [int(y) for y in GATE_YEARS],
            "gate_stems": GATE_STEMS,
            "note": (
                f"LC FIRST_IR scaffold; tip MATCH {DST_TIP_SHORT}@150/5078; {HOLD}; "
                f"soft never-thin ON; SKIP_US; Italy BLOCKED; {WAVE_POS}"
            ),
            "status": "CLAIMED",
        })
        break
else:
    raise RuntimeError("Saint Lucia entry missing from wave JSON")
wave.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print("updated wave JSON Saint Lucia entry")
print("GATE years", GATE_YEARS)
print("GATE stems", GATE_STEMS)
print("n_gate", len(GATE_YEARS) + len(GATE_STEMS))
print("GATE language: English")
print("HOLD", HOLD)
