#!/usr/bin/env python3
"""Adapt the Belize English memsafe FIRST_IR pack to Solomon Islands SB.

English Solomon Islands; FIRST_IR; HOLD 0 STRICT after-BZ (SB→CW→MU→LC→TJ).
Soft never-thin ON; SKIP_US; Italy BLOCKED. WAVE after_bm eighth country
(after TV→LR→SY→TO→BS→LS→BZ LIVE), NOT wave end.
GATE: attested years + English legal stems from articles.parquet tip c921827129d0.
Source tip 39442fe69bdc (Belize English).
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
SRC_TIP_FULL = "39442fe69bdc240d77ad5ab0d4796a7571d1abae"
SRC_TIP_SHORT = "39442fe69bdc"
DST_TIP_FULL = "c921827129d0f97949085e0bee4f27be45fe8a8f"
DST_TIP_SHORT = "c921827129d0"
FLOOR_LAWS, FLOOR_ARTS = 224, 6049

# Sampled from data/articles.parquet @ c921827129d0 (~10 years + ~11 stems; include solomon)
GATE_YEARS = ["2023", "2009", "2008", "2018", "1996", "2014", "1998", "2017", "2022", "2010"]
GATE_STEMS = ["solomon", "shall", "act", "section", "person", "court", "order", "minister", "offence", "subsection", "schedule"]
GATE_NOTE_YEARS = "/".join(GATE_YEARS)
GATE_NOTE_STEMS = "/".join(GATE_STEMS)
HOLD = "HOLD 0 STRICT after-BZ (SB→CW→MU→LC→TJ)"
WAVE_POS = "eighth country of after_bm wave (after TV→LR→SY→TO→BS→LS→BZ LIVE)"

FILES = [
    ("belize_soft_filter.py", "solomonislands_soft_filter.py"),
    (f"belize_corpus_stream_{SRC_TIP_SHORT}.py", f"solomonislands_corpus_stream_{DST_TIP_SHORT}.py"),
    (f"belize_encode_memsafe_{SRC_TIP_SHORT}.py", f"solomonislands_encode_memsafe_{DST_TIP_SHORT}.py"),
    (f"belize_finish_from_emb_{SRC_TIP_SHORT}.py", f"solomonislands_finish_from_emb_{DST_TIP_SHORT}.py"),
    (f"belize_stream_graph_parts_{SRC_TIP_SHORT}.py", f"solomonislands_stream_graph_parts_{DST_TIP_SHORT}.py"),
    (f"belize_package_memsafe_{SRC_TIP_SHORT}.py", f"solomonislands_package_memsafe_{DST_TIP_SHORT}.py"),
    ("belize_upload.py", "solomonislands_upload.py"),
    ("belize_bm25_smoke.py", "solomonislands_bm25_smoke.py"),
    ("belize_write_publish_report.py", "solomonislands_write_publish_report.py"),
    (f"belize_orchestrator_{SRC_TIP_SHORT}.py", f"solomonislands_orchestrator_{DST_TIP_SHORT}.py"),
]


def adapt(text: str, dst_name: str) -> str:
    # Protect BM25 / bm25 and intentional wave chain tokens from ISO swaps
    text = text.replace("BM25", "\x00BM25\x00").replace("bm25", "\x00bm25\x00")
    text = text.replace("bmjacency", "adjacency")
    # Protect full wave-chain mentions that must keep prior LIVE countries incl. BZ
    text = text.replace("TV→LR→SY→TO→BS→LS→BZ", "\x00WAVECHAIN\x00")
    text = text.replace("TV→LR→SY→TO→BS→LS", "\x00WAVECHAIN_SHORT\x00")
    text = text.replace("TV→LR→SY→TO→BS", "\x00WAVECHAIN_SHORTER\x00")
    text = text.replace("TV→LR→SY→TO", "\x00WAVECHAIN_SHORTEST\x00")
    # Protect destination HOLD after-BZ form once written; source after-LS must rewrite
    text = text.replace("after-BZ", "\x00AFTERBZ\x00")
    text = text.replace("after BZ ", "\x00AFTERBZ_SP\x00")
    text = text.replace("after-LS", "\x00AFTERLS\x00")
    text = text.replace("after LS ", "\x00AFTERLS_SP\x00")

    reps = [
        (SRC_TIP_FULL, DST_TIP_FULL),
        (SRC_TIP_SHORT, DST_TIP_SHORT),
        ("endomorphosis/ipfs_belize_laws", "endomorphosis/ipfs_solomonislands_laws"),
        ("justicedao/ipfs_belize_laws_ir", "justicedao/ipfs_solomonislands_laws_ir"),
        ("ipfs_belize_laws_ir", "ipfs_solomonislands_laws_ir"),
        ("ipfs_belize_laws", "ipfs_solomonislands_laws"),
        # HOLD / wave position BEFORE bare BZ→SB swaps
        ("HOLD 0 STRICT after-LS (BZ→SB→CW→MU→LC→TJ)", HOLD),
        ("after-LS (BZ→SB→CW→MU→LC→TJ)", "after-BZ (SB→CW→MU→LC→TJ)"),
        ("BZ→SB→CW→MU→LC→TJ", "SB→CW→MU→LC→TJ"),
        ("BZ FIRST_IR (not wave end)", "SB FIRST_IR (not wave end)"),
        ("seventh country of after_bm wave (after TV→LR→SY→TO→BS→LS LIVE)", WAVE_POS),
        ("seventh of after_bm wave (after TV→LR→SY→TO→BS→LS LIVE)", "eighth of after_bm wave (after TV→LR→SY→TO→BS→LS→BZ LIVE)"),
        ("seventh country of after_bm wave", WAVE_POS),
        ("seventh of after_bm wave", "eighth of after_bm wave (after TV→LR→SY→TO→BS→LS→BZ LIVE)"),
        ("www/gov/bz", "www/gov/sb"),
        ("English (Belize)", "English (Solomon Islands)"),
        ("English Belize", "English Solomon Islands"),
        ("Belize", "Solomon Islands"),
        ("belize", "solomonislands"),
        # ISO whole-token / path forms only
        ('"BZ"', '"SB"'),
        ("BZ-attested", "SB-attested"),
        ("(BZ)", "(SB)"),
        ('"bz"', '"sb"'),
        ("/bz", "/sb"),
        # floors 150/6095 → 224/6049
        ("150/6095", "224/6049"),
        ("150 / 6095", "224 / 6049"),
        ("150, 6095", "224, 6049"),
        ("FLOOR_LAWS, FLOOR_ARTS = 150, 6095", "FLOOR_LAWS, FLOOR_ARTS = 224, 6049"),
        ("= 150,", "= 224,"),
        ("= 150", "= 224"),
        ("@ 150/", "@ 224/"),
        (" 150/", " 224/"),
        ("floor 150/", "floor 224/"),
        ("(150/", "(224/"),
        (" 6095", " 6049"),
        ("6095", "6049"),
        ("or 150)", "or 224)"),
        ("or 150,", "or 224,"),
    ]
    for a, b in reps:
        text = text.replace(a, b)

    text = text.replace("\x00BM25\x00", "BM25").replace("\x00bm25\x00", "bm25")
    text = text.replace("\x00WAVECHAIN\x00", "TV→LR→SY→TO→BS→LS→BZ")
    text = text.replace("\x00WAVECHAIN_SHORT\x00", "TV→LR→SY→TO→BS→LS")
    text = text.replace("\x00WAVECHAIN_SHORTER\x00", "TV→LR→SY→TO→BS")
    text = text.replace("\x00WAVECHAIN_SHORTEST\x00", "TV→LR→SY→TO")
    text = text.replace("\x00AFTERBZ\x00", "after-BZ")
    text = text.replace("\x00AFTERBZ_SP\x00", "after BZ ")
    # Source after-LS that wasn't rewritten via full HOLD string → rewrite to after-BZ
    text = text.replace("\x00AFTERLS\x00", "after-BZ")
    text = text.replace("\x00AFTERLS_SP\x00", "after BZ ")

    text = text.replace("FLOOR_LAWS, FLOOR_ARTS = 150, 6049", "FLOOR_LAWS, FLOOR_ARTS = 224, 6049")
    text = text.replace("FLOOR_LAWS, FLOOR_ARTS = 224, 6095", "FLOOR_LAWS, FLOOR_ARTS = 224, 6049")

    if dst_name == "solomonislands_bm25_smoke.py":
        start = text.index("GATE = [")
        end = text.index("]", start) + 1
        years_line = ", ".join(f'"{y}"' for y in GATE_YEARS)
        stems_line = ", ".join(f'"{s}"' for s in GATE_STEMS)
        gate = f"GATE = [\n    {years_line},\n    {stems_line},\n]"
        text = text[:start] + gate + text[end:]
        text = text.replace('QUERIES = GATE + ["www", "gov", "bz"', 'QUERIES = GATE + ["www", "gov", "sb"')
        text = text.replace('QUERIES = GATE + ["www", "gov", "sb"', 'QUERIES = GATE + ["www", "gov", "sb"')
        note = (
            f"attested years {GATE_NOTE_YEARS} plus English legal stems {GATE_NOTE_STEMS} "
            f"from articles.parquet HEAD tip {DST_TIP_SHORT}; URL www/gov/sb is query-only, not GATE."
        )
        text = re.sub(
            r"GATE = attested years [^;]+; URL www/gov/(?:bz|sb) is query-only, not GATE\.",
            f"GATE = {note}",
            text,
        )
        text = text.replace('"solomonislands_pass"', '"solomonislands_pass"')
        text = text.replace('"belize_pass"', '"solomonislands_pass"')
        text = text.replace('"solomonislands_gate"', '"solomonislands_gate"')
        text = text.replace('"belize_gate"', '"solomonislands_gate"')

    if dst_name == "solomonislands_write_publish_report.py":
        new_gate = f"{GATE_NOTE_YEARS} + stems {GATE_NOTE_STEMS}"
        text = re.sub(
            r"attested years [0-9/]+ \+ stems [a-z/]+",
            f"attested years {new_gate}",
            text,
        )
        text = text.replace("English GATE", "English (Solomon Islands) GATE")
        text = re.sub(
            r"HOLD 0 STRICT after-BZ[^;]*; collectors kept dead \(pkill\); soft never-thin ON; SKIP_US; Italy BLOCKED;[^\"\n]*",
            f"{HOLD}; collectors kept dead (pkill); soft never-thin ON; SKIP_US; Italy BLOCKED; {WAVE_POS}",
            text,
        )
        text = re.sub(
            r"HOLD 0 STRICT after-LS[^;]*; collectors kept dead \(pkill\); soft never-thin ON; SKIP_US; Italy BLOCKED;[^\"\n]*",
            f"{HOLD}; collectors kept dead (pkill); soft never-thin ON; SKIP_US; Italy BLOCKED; {WAVE_POS}",
            text,
        )
        text = text.replace(
            "seventh country of after_bm wave (after TV→LR→SY→TO→BS→LS LIVE)",
            WAVE_POS,
        )
        text = text.replace(
            "eighth country of after_bm wave (after TV→LR→SY→TO→BS→LS LIVE)",
            WAVE_POS,
        )

    leftovers = (
        "French", "Haiti", "Nauru", "Montserrat", "Bermuda", "bermuda",
        "British Virgin Islands", "Gabon", "Togo", "Anguilla", "Cook Islands",
        "Tuvalu", "tuvalu", "Liberia", "liberia", "Syria", "syria", "Arabic",
        "arabic", "Tonga", "tonga", "Bahamas", "bahamas", "Lesotho", "lesotho",
        "Belize", "belize", "bmjacency", "msjacency",
    )
    found = [x for x in leftovers if x in text]
    if found:
        raise RuntimeError(f"language/country leftovers in {dst_name}: {found}")
    if dst_name.endswith("_bm25_smoke.py") and '", "bz"' in text:
        raise RuntimeError(f"leftover bz query token in {dst_name}")
    if dst_name.endswith("_bm25_smoke.py") and "www/gov/bz" in text:
        raise RuntimeError(f"leftover gov/bz in {dst_name}")
    # reject bare ISO leftovers that should have been swapped
    # Allow intentional wave-position mention "after TV→LR→SY→TO→BS→LS→BZ LIVE" and HOLD after-BZ
    scrub = text.replace("TV→LR→SY→TO→BS→LS→BZ", "TV→XX→SY→XX→XX→XX→XX")
    scrub = scrub.replace("TV→LR→SY→TO→BS→LS", "TV→XX→SY→XX→XX→XX")
    scrub = scrub.replace("TV→LR→SY→TO→BS", "TV→XX→SY→XX→XX")
    scrub = scrub.replace("TV→LR→SY→TO", "TV→XX→SY→XX")
    scrub = scrub.replace("after-BZ", "after-XX")
    scrub = scrub.replace("after BZ ", "after XX ")
    scrub = scrub.replace("after-LS", "after-XX")
    scrub = scrub.replace("after LS ", "after XX ")
    if '"BZ"' in scrub or "(BZ)" in scrub or "BZ→" in scrub or "BZ-attested" in scrub:
        raise RuntimeError(f"leftover BZ tokens in {dst_name}")
    if "Belize" in text or "Lesotho" in text or "belize" in text or "lesotho" in text:
        raise RuntimeError(f"leftover country name in {dst_name}")
    # IR hub must be justicedao/ipfs_solomonislands_laws_ir (no solomon_islands)
    if "solomon_islands" in text or "ipfs_solomon_islands" in text:
        raise RuntimeError(f"underscore-between-solomon-islands in {dst_name}")
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
    if entry.get("slug") == "solomonislands" or entry.get("iso2") == "SB":
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
            "years_attested": [int(y) for y in GATE_YEARS],
            "gate_years": [int(y) for y in GATE_YEARS],
            "gate_stems": GATE_STEMS,
            "note": (
                f"SB FIRST_IR scaffold; tip MATCH {DST_TIP_SHORT}@224/6049; {HOLD}; "
                f"soft never-thin ON; SKIP_US; Italy BLOCKED; eighth of after_bm wave (after TV→LR→SY→TO→BS→LS→BZ LIVE)"
            ),
            "status": "CLAIMED",
        })
        break
else:
    raise RuntimeError("Solomon Islands entry missing from wave JSON")
wave.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print("updated wave JSON Solomon Islands entry")
print("GATE years", GATE_YEARS)
print("GATE stems", GATE_STEMS)
print("n_gate", len(GATE_YEARS) + len(GATE_STEMS))
