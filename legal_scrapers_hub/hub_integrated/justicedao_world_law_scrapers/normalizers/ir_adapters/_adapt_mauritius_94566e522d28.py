#!/usr/bin/env python3
"""Adapt the Solomon Islands English memsafe FIRST_IR pack to Mauritius MU.

English Mauritius; FIRST_IR; HOLD 0 STRICT after-CW (MU→LC→TJ).
Soft never-thin ON; SKIP_US; Italy BLOCKED. WAVE after_bm tenth country
(after TV→LR→SY→TO→BS→LS→BZ→SB→CW LIVE), NOT wave end (TJ is wave end).
GATE: attested years + English legal stems from articles.parquet tip 94566e522d28
(English dominates ~493/6 over French in 500-article sample).
Source tip c921827129d0 (Solomon Islands English) — NOT Curaçao Dutch.
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
SRC_TIP_FULL = "c921827129d0f97949085e0bee4f27be45fe8a8f"
SRC_TIP_SHORT = "c921827129d0"
DST_TIP_FULL = "94566e522d28037d4b70c7c0bbfea9fc3aa4aadd"
DST_TIP_SHORT = "94566e522d28"
FLOOR_LAWS, FLOOR_ARTS = 158, 5451

# Sampled from data/articles.parquet @ 94566e522d28 (English dominant; include mauritius)
GATE_YEARS = ["2013", "2011", "2020", "2012", "2010", "2015", "2014", "2018", "2016", "2019"]
GATE_STEMS = [
    "mauritius", "shall", "act", "section", "person", "court",
    "order", "minister", "offence", "subsection", "schedule",
]
GATE_NOTE_YEARS = "/".join(GATE_YEARS)
GATE_NOTE_STEMS = "/".join(GATE_STEMS)
HOLD = "HOLD 0 STRICT after-CW (MU→LC→TJ)"
WAVE_POS = "tenth country of after_bm wave (after TV→LR→SY→TO→BS→LS→BZ→SB→CW LIVE)"

FILES = [
    ("solomonislands_soft_filter.py", "mauritius_soft_filter.py"),
    (f"solomonislands_corpus_stream_{SRC_TIP_SHORT}.py", f"mauritius_corpus_stream_{DST_TIP_SHORT}.py"),
    (f"solomonislands_encode_memsafe_{SRC_TIP_SHORT}.py", f"mauritius_encode_memsafe_{DST_TIP_SHORT}.py"),
    (f"solomonislands_finish_from_emb_{SRC_TIP_SHORT}.py", f"mauritius_finish_from_emb_{DST_TIP_SHORT}.py"),
    (f"solomonislands_stream_graph_parts_{SRC_TIP_SHORT}.py", f"mauritius_stream_graph_parts_{DST_TIP_SHORT}.py"),
    (f"solomonislands_package_memsafe_{SRC_TIP_SHORT}.py", f"mauritius_package_memsafe_{DST_TIP_SHORT}.py"),
    ("solomonislands_upload.py", "mauritius_upload.py"),
    ("solomonislands_bm25_smoke.py", "mauritius_bm25_smoke.py"),
    ("solomonislands_write_publish_report.py", "mauritius_write_publish_report.py"),
    (f"solomonislands_orchestrator_{SRC_TIP_SHORT}.py", f"mauritius_orchestrator_{DST_TIP_SHORT}.py"),
]


def adapt(text: str, dst_name: str) -> str:
    # Protect BM25 / bm25 and intentional wave-chain tokens from ISO swaps
    text = text.replace("BM25", "\x00BM25\x00").replace("bm25", "\x00bm25\x00")
    text = text.replace("bmjacency", "adjacency")
    # Protect full wave-chain mentions that must keep prior LIVE countries incl. CW
    text = text.replace("TV→LR→SY→TO→BS→LS→BZ→SB→CW", "\x00WAVECHAIN10\x00")
    text = text.replace("TV→LR→SY→TO→BS→LS→BZ→SB", "\x00WAVECHAIN9\x00")
    text = text.replace("TV→LR→SY→TO→BS→LS→BZ", "\x00WAVECHAIN8\x00")
    text = text.replace("TV→LR→SY→TO→BS→LS", "\x00WAVECHAIN7\x00")
    text = text.replace("TV→LR→SY→TO→BS", "\x00WAVECHAIN6\x00")
    text = text.replace("TV→LR→SY→TO", "\x00WAVECHAIN5\x00")
    # Protect destination HOLD after-CW; source after-BZ must rewrite
    text = text.replace("after-CW", "\x00AFTERCW\x00")
    text = text.replace("after CW ", "\x00AFTERCW_SP\x00")
    text = text.replace("after-BZ", "\x00AFTERBZ\x00")
    text = text.replace("after BZ ", "\x00AFTERBZ_SP\x00")
    text = text.replace("after-SB", "\x00AFTERSB\x00")
    text = text.replace("after SB ", "\x00AFTERSB_SP\x00")
    # Protect HOLD chains before ISO swaps
    text = text.replace("SB→CW→MU→LC→TJ", "\x00HOLDCHAIN_SRC\x00")
    text = text.replace("CW→MU→LC→TJ", "\x00HOLDCHAIN_MID\x00")
    text = text.replace("MU→LC→TJ", "\x00DESTCHAIN\x00")

    reps = [
        (SRC_TIP_FULL, DST_TIP_FULL),
        (SRC_TIP_SHORT, DST_TIP_SHORT),
        ("endomorphosis/ipfs_solomonislands_laws", "endomorphosis/ipfs_mauritius_laws"),
        ("justicedao/ipfs_solomonislands_laws_ir", "justicedao/ipfs_mauritius_laws_ir"),
        ("ipfs_solomonislands_laws_ir", "ipfs_mauritius_laws_ir"),
        ("ipfs_solomonislands_laws", "ipfs_mauritius_laws"),
        # HOLD / wave position BEFORE bare SB→MU swaps
        ("HOLD 0 STRICT after-BZ (SB→CW→MU→LC→TJ)", HOLD),
        ("HOLD 0 STRICT \x00AFTERBZ\x00 (\x00HOLDCHAIN_SRC\x00)", HOLD),
        ("after-BZ (SB→CW→MU→LC→TJ)", "after-CW (MU→LC→TJ)"),
        ("SB FIRST_IR (not wave end)", "MU FIRST_IR (not wave end)"),
        ("eighth country of after_bm wave (after TV→LR→SY→TO→BS→LS→BZ LIVE)", WAVE_POS),
        ("eighth of after_bm wave (after TV→LR→SY→TO→BS→LS→BZ LIVE)",
         "tenth of after_bm wave (after TV→LR→SY→TO→BS→LS→BZ→SB→CW LIVE)"),
        ("eighth country of after_bm wave", WAVE_POS),
        ("eighth of after_bm wave",
         "tenth of after_bm wave (after TV→LR→SY→TO→BS→LS→BZ→SB→CW LIVE)"),
        ("www/gov/sb", "www/gov/mu"),
        ("English (Solomon Islands)", "English (Mauritius)"),
        ("English Solomon Islands", "English Mauritius"),
        ("Solomon Islands", "Mauritius"),
        ("solomonislands", "mauritius"),
        # ISO whole-token / path forms only
        ('"SB"', '"MU"'),
        ("SB-attested", "MU-attested"),
        ("(SB)", "(MU)"),
        ('"sb"', '"mu"'),
        ("/sb", "/mu"),
        # floors 224/6049 → 158/5451
        ("224/6049", "158/5451"),
        ("224 / 6049", "158 / 5451"),
        ("224, 6049", "158, 5451"),
        ("FLOOR_LAWS, FLOOR_ARTS = 224, 6049", "FLOOR_LAWS, FLOOR_ARTS = 158, 5451"),
        ("or 224)", "or 158)"),
        ("or 224,", "or 158,"),
        ("or 224}", "or 158}"),
        ("= 224,", "= 158,"),
        ("= 224", "= 158"),
        ("@ 224/", "@ 158/"),
        (" 224/", " 158/"),
        ("floor 224/", "floor 158/"),
        ("(224/", "(158/"),
        (" or 224", " or 158"),
        (" 6049", " 5451"),
        ("6049", "5451"),
    ]
    for a, b in reps:
        text = text.replace(a, b)

    text = text.replace("\x00BM25\x00", "BM25").replace("\x00bm25\x00", "bm25")
    text = text.replace("\x00WAVECHAIN10\x00", "TV→LR→SY→TO→BS→LS→BZ→SB→CW")
    text = text.replace("\x00WAVECHAIN9\x00", "TV→LR→SY→TO→BS→LS→BZ→SB")
    text = text.replace("\x00WAVECHAIN8\x00", "TV→LR→SY→TO→BS→LS→BZ")
    text = text.replace("\x00WAVECHAIN7\x00", "TV→LR→SY→TO→BS→LS")
    text = text.replace("\x00WAVECHAIN6\x00", "TV→LR→SY→TO→BS")
    text = text.replace("\x00WAVECHAIN5\x00", "TV→LR→SY→TO")
    text = text.replace("\x00DESTCHAIN\x00", "MU→LC→TJ")
    text = text.replace("\x00HOLDCHAIN_MID\x00", "MU→LC→TJ")  # after after-CW rewrite
    text = text.replace("\x00HOLDCHAIN_SRC\x00", "MU→LC→TJ")
    text = text.replace("\x00AFTERCW\x00", "after-CW")
    text = text.replace("\x00AFTERCW_SP\x00", "after CW ")
    # Source after-BZ / after-SB that wasn't rewritten via full HOLD → after-CW
    text = text.replace("\x00AFTERBZ\x00", "after-CW")
    text = text.replace("\x00AFTERBZ_SP\x00", "after CW ")
    text = text.replace("\x00AFTERSB\x00", "after-CW")
    text = text.replace("\x00AFTERSB_SP\x00", "after CW ")

    text = text.replace("FLOOR_LAWS, FLOOR_ARTS = 224, 5451", "FLOOR_LAWS, FLOOR_ARTS = 158, 5451")
    text = text.replace("FLOOR_LAWS, FLOOR_ARTS = 158, 6049", "FLOOR_LAWS, FLOOR_ARTS = 158, 5451")
    text = text.replace("or 224)", "or 158)")
    text = text.replace("or 224,", "or 158,")
    text = text.replace("or 224}", "or 158}")

    if dst_name == "mauritius_bm25_smoke.py":
        start = text.index("GATE = [")
        end = text.index("]", start) + 1
        years_line = ", ".join(f'"{y}"' for y in GATE_YEARS)
        stems_line = ", ".join(f'"{s}"' for s in GATE_STEMS)
        gate = f"GATE = [\n    {years_line},\n    {stems_line},\n]"
        text = text[:start] + gate + text[end:]
        text = text.replace(
            'QUERIES = GATE + ["www", "gov", "sb"',
            'QUERIES = GATE + ["www", "gov", "mu"',
        )
        text = text.replace(
            'QUERIES = GATE + ["www", "gov", "mu"',
            'QUERIES = GATE + ["www", "gov", "mu"',
        )
        note = (
            f"attested years {GATE_NOTE_YEARS} plus English legal stems {GATE_NOTE_STEMS} "
            f"from articles.parquet HEAD tip {DST_TIP_SHORT}; URL www/gov/mu is query-only, not GATE."
        )
        text = re.sub(
            r"GATE = attested years [^;]+; URL www/gov/(?:sb|mu) is query-only, not GATE\.",
            f"GATE = {note}",
            text,
        )
        text = text.replace('"mauritius_pass"', '"mauritius_pass"')
        text = text.replace('"solomonislands_pass"', '"mauritius_pass"')
        text = text.replace('"mauritius_gate"', '"mauritius_gate"')
        text = text.replace('"solomonislands_gate"', '"mauritius_gate"')
        # docstring
        text = text.replace(
            "attested Mauritius years and English legal stems",
            "attested Mauritius years and English legal stems",
        )
        text = text.replace(
            "attested Solomon Islands years and English legal stems",
            "attested Mauritius years and English legal stems",
        )

    if dst_name == "mauritius_write_publish_report.py":
        new_gate = f"{GATE_NOTE_YEARS} + stems {GATE_NOTE_STEMS}"
        text = re.sub(
            r"attested years [0-9/]+ \+ stems [a-z/]+",
            f"attested years {new_gate}",
            text,
        )
        text = text.replace("English GATE", "English (Mauritius) GATE")
        text = text.replace(
            "ASCII-fold English (Mauritius) GATE",
            "ASCII-fold English (Mauritius) GATE",
        )
        text = re.sub(
            r"HOLD 0 STRICT after-CW[^;]*; collectors kept dead \(pkill\); soft never-thin ON; SKIP_US; Italy BLOCKED;[^\"\n]*",
            f"{HOLD}; collectors kept dead (pkill); soft never-thin ON; SKIP_US; Italy BLOCKED; {WAVE_POS}",
            text,
        )
        text = re.sub(
            r"HOLD 0 STRICT after-BZ[^;]*; collectors kept dead \(pkill\); soft never-thin ON; SKIP_US; Italy BLOCKED;[^\"\n]*",
            f"{HOLD}; collectors kept dead (pkill); soft never-thin ON; SKIP_US; Italy BLOCKED; {WAVE_POS}",
            text,
        )
        text = re.sub(
            r"HOLD 0 STRICT after-SB[^;]*; collectors kept dead \(pkill\); soft never-thin ON; SKIP_US; Italy BLOCKED;[^\"\n]*",
            f"{HOLD}; collectors kept dead (pkill); soft never-thin ON; SKIP_US; Italy BLOCKED; {WAVE_POS}",
            text,
        )
        text = text.replace(
            "eighth country of after_bm wave (after TV→LR→SY→TO→BS→LS→BZ LIVE)",
            WAVE_POS,
        )
        text = text.replace(
            "tenth country of after_bm wave (after TV→LR→SY→TO→BS→LS→BZ LIVE)",
            WAVE_POS,
        )
        text = text.replace("www/gov/sb is query-only", "www/gov/mu is query-only")

    leftovers = (
        "Solomon Islands", "solomonislands", "solomon",
        "Curaçao", "Curacao", "curacao", "Dutch",
        "Belize", "belize", "Lesotho", "lesotho",
        "French", "Haiti", "Nauru", "Montserrat", "Bermuda", "bermuda",
        "British Virgin Islands", "Gabon", "Togo", "Anguilla", "Cook Islands",
        "Tuvalu", "tuvalu", "Liberia", "liberia", "Syria", "syria", "Arabic",
        "arabic", "Tonga", "tonga", "Bahamas", "bahamas",
        "bmjacency", "msjacency",
        "English (Solomon", "English Solomon",
    )
    found = [x for x in leftovers if x in text]
    if found:
        raise RuntimeError(f"language/country leftovers in {dst_name}: {found}")
    if dst_name.endswith("_bm25_smoke.py") and '", "sb"' in text:
        raise RuntimeError(f"leftover sb query token in {dst_name}")
    if dst_name.endswith("_bm25_smoke.py") and "www/gov/sb" in text:
        raise RuntimeError(f"leftover gov/sb in {dst_name}")
    # reject bare ISO leftovers that should have been swapped
    scrub = text.replace("TV→LR→SY→TO→BS→LS→BZ→SB→CW", "TV→XX→SY→XX→XX→XX→XX→XX→XX")
    scrub = scrub.replace("TV→LR→SY→TO→BS→LS→BZ→SB", "TV→XX→SY→XX→XX→XX→XX→XX")
    scrub = scrub.replace("TV→LR→SY→TO→BS→LS→BZ", "TV→XX→SY→XX→XX→XX→XX")
    scrub = scrub.replace("TV→LR→SY→TO→BS→LS", "TV→XX→SY→XX→XX→XX")
    scrub = scrub.replace("TV→LR→SY→TO→BS", "TV→XX→SY→XX→XX")
    scrub = scrub.replace("TV→LR→SY→TO", "TV→XX→SY→XX")
    scrub = scrub.replace("after-CW", "after-XX")
    scrub = scrub.replace("after CW ", "after XX ")
    scrub = scrub.replace("after-BZ", "after-XX")
    scrub = scrub.replace("after-SB", "after-XX")
    scrub = scrub.replace("MU→LC→TJ", "XX→XX→XX")
    scrub = scrub.replace("CW→MU→LC→TJ", "XX→XX→XX→XX")
    scrub = scrub.replace("SB→CW→MU→LC→TJ", "XX→XX→XX→XX→XX")
    if '"SB"' in scrub or "(SB)" in scrub or "SB→" in scrub or "SB-attested" in scrub:
        raise RuntimeError(f"leftover SB tokens in {dst_name}")
    if "Solomon" in text:
        raise RuntimeError(f"leftover Solomon in {dst_name}")
    if "ipfs_solomon" in text or "solomonislands" in text:
        raise RuntimeError(f"leftover solomon path in {dst_name}")
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
    if entry.get("slug") == "mauritius" or entry.get("iso2") == "MU":
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
                f"MU FIRST_IR scaffold; tip MATCH {DST_TIP_SHORT}@158/5451; {HOLD}; "
                f"soft never-thin ON; SKIP_US; Italy BLOCKED; {WAVE_POS}"
            ),
            "status": "CLAIMED",
        })
        break
else:
    raise RuntimeError("Mauritius entry missing from wave JSON")
wave.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print("updated wave JSON Mauritius entry")
print("GATE years", GATE_YEARS)
print("GATE stems", GATE_STEMS)
print("n_gate", len(GATE_YEARS) + len(GATE_STEMS))
print("GATE language: English")
