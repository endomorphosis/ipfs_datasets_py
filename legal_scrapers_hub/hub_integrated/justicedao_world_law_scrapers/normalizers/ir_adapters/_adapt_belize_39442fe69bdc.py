#!/usr/bin/env python3
"""Adapt the Lesotho English memsafe FIRST_IR pack to Belize BZ.

English Belize; FIRST_IR; HOLD 0 STRICT after-LS (BZ→SB→CW→MU→LC→TJ).
Soft never-thin ON; SKIP_US; Italy BLOCKED. WAVE after_bm seventh country
(after TV→LR→SY→TO→BS→LS LIVE), NOT wave end.
GATE: attested years + English legal stems from articles.parquet tip 39442fe69bdc.
Source tip f92fc7f5c27f (Lesotho English).
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
SRC_TIP_FULL = "f92fc7f5c27fb1f012876edd29d0c3fbf16b34d5"
SRC_TIP_SHORT = "f92fc7f5c27f"
DST_TIP_FULL = "39442fe69bdc240d77ad5ab0d4796a7571d1abae"
DST_TIP_SHORT = "39442fe69bdc"
FLOOR_LAWS, FLOOR_ARTS = 150, 6095

# Sampled from data/articles.parquet @ 39442fe69bdc (~10 years + ~11 stems; include belize)
GATE_YEARS = ["2020", "2018", "2001", "2017", "1999", "2010", "1963", "2014", "2016", "1998"]
GATE_STEMS = ["belize", "shall", "act", "section", "person", "court", "order", "minister", "regulation", "provision", "offence"]
GATE_NOTE_YEARS = "/".join(GATE_YEARS)
GATE_NOTE_STEMS = "/".join(GATE_STEMS)
HOLD = "HOLD 0 STRICT after-LS (BZ→SB→CW→MU→LC→TJ)"
WAVE_POS = "seventh country of after_bm wave (after TV→LR→SY→TO→BS→LS LIVE)"

FILES = [
    ("lesotho_soft_filter.py", "belize_soft_filter.py"),
    (f"lesotho_corpus_stream_{SRC_TIP_SHORT}.py", f"belize_corpus_stream_{DST_TIP_SHORT}.py"),
    (f"lesotho_encode_memsafe_{SRC_TIP_SHORT}.py", f"belize_encode_memsafe_{DST_TIP_SHORT}.py"),
    (f"lesotho_finish_from_emb_{SRC_TIP_SHORT}.py", f"belize_finish_from_emb_{DST_TIP_SHORT}.py"),
    (f"lesotho_stream_graph_parts_{SRC_TIP_SHORT}.py", f"belize_stream_graph_parts_{DST_TIP_SHORT}.py"),
    (f"lesotho_package_memsafe_{SRC_TIP_SHORT}.py", f"belize_package_memsafe_{DST_TIP_SHORT}.py"),
    ("lesotho_upload.py", "belize_upload.py"),
    ("lesotho_bm25_smoke.py", "belize_bm25_smoke.py"),
    ("lesotho_write_publish_report.py", "belize_write_publish_report.py"),
    (f"lesotho_orchestrator_{SRC_TIP_SHORT}.py", f"belize_orchestrator_{DST_TIP_SHORT}.py"),
]


def adapt(text: str, dst_name: str) -> str:
    # Protect BM25 / bm25 and intentional wave chain tokens from ISO swaps
    text = text.replace("BM25", "\x00BM25\x00").replace("bm25", "\x00bm25\x00")
    text = text.replace("bmjacency", "adjacency")
    # Protect wave-chain mentions that must keep LS as prior LIVE country
    text = text.replace("TV→LR→SY→TO→BS→LS", "\x00WAVECHAIN\x00")
    text = text.replace("TV→LR→SY→TO→BS", "\x00WAVECHAIN_SHORT\x00")
    text = text.replace("TV→LR→SY→TO", "\x00WAVECHAIN_SHORTER\x00")
    # Protect destination HOLD after-LS form once written; source after-BS must rewrite
    text = text.replace("after-LS", "\x00AFTERLS\x00")
    text = text.replace("after LS ", "\x00AFTERLS_SP\x00")

    reps = [
        (SRC_TIP_FULL, DST_TIP_FULL),
        (SRC_TIP_SHORT, DST_TIP_SHORT),
        ("endomorphosis/ipfs_lesotho_laws", "endomorphosis/ipfs_belize_laws"),
        ("justicedao/ipfs_lesotho_laws_ir", "justicedao/ipfs_belize_laws_ir"),
        ("ipfs_lesotho_laws_ir", "ipfs_belize_laws_ir"),
        ("ipfs_lesotho_laws", "ipfs_belize_laws"),
        # HOLD / wave position BEFORE bare LS→BZ swaps
        ("HOLD 0 STRICT after-BS (LS→BZ→SB→CW→MU→LC→TJ)", HOLD),
        ("after-BS (LS→BZ→SB→CW→MU→LC→TJ)", "after-LS (BZ→SB→CW→MU→LC→TJ)"),
        ("LS→BZ→SB→CW→MU→LC→TJ", "BZ→SB→CW→MU→LC→TJ"),
        ("LS FIRST_IR (not wave end)", "BZ FIRST_IR (not wave end)"),
        ("sixth country of after_bm wave (after TV→LR→SY→TO→BS LIVE)", WAVE_POS),
        ("sixth of after_bm wave (after TV→LR→SY→TO→BS LIVE)", "seventh of after_bm wave (after TV→LR→SY→TO→BS→LS LIVE)"),
        ("sixth country of after_bm wave", WAVE_POS),
        ("sixth of after_bm wave", "seventh of after_bm wave (after TV→LR→SY→TO→BS→LS LIVE)"),
        ("www/gov/ls", "www/gov/bz"),
        ("English (Lesotho)", "English (Belize)"),
        ("English Lesotho", "English Belize"),
        ("Lesotho", "Belize"),
        ("lesotho", "belize"),
        # ISO whole-token / path forms only
        ('"LS"', '"BZ"'),
        ("LS-attested", "BZ-attested"),
        ("(LS)", "(BZ)"),
        ('"ls"', '"bz"'),
        ("/ls", "/bz"),
        # floors 90/6718 → 150/6095
        ("90/6718", "150/6095"),
        ("90 / 6718", "150 / 6095"),
        ("90, 6718", "150, 6095"),
        ("FLOOR_LAWS, FLOOR_ARTS = 90, 6718", "FLOOR_LAWS, FLOOR_ARTS = 150, 6095"),
        ("FLOOR_LAWS, FLOOR_ARTS = 90, 6095", "FLOOR_LAWS, FLOOR_ARTS = 150, 6095"),
        ("= 90,", "= 150,"),
        ("= 90", "= 150"),
        ("@ 90/", "@ 150/"),
        (" 90/", " 150/"),
        ("floor 90/", "floor 150/"),
        ("(90/", "(150/"),
        (" 6718", " 6095"),
        ("6718", "6095"),
        ("or 90)", "or 150)"),
        ("or 90,", "or 150,"),
    ]
    for a, b in reps:
        text = text.replace(a, b)

    text = text.replace("\x00BM25\x00", "BM25").replace("\x00bm25\x00", "bm25")
    text = text.replace("\x00WAVECHAIN\x00", "TV→LR→SY→TO→BS→LS")
    text = text.replace("\x00WAVECHAIN_SHORT\x00", "TV→LR→SY→TO→BS")
    text = text.replace("\x00WAVECHAIN_SHORTER\x00", "TV→LR→SY→TO")
    text = text.replace("\x00AFTERLS\x00", "after-LS")
    text = text.replace("\x00AFTERLS_SP\x00", "after LS ")

    text = text.replace("FLOOR_LAWS, FLOOR_ARTS = 90, 6095", "FLOOR_LAWS, FLOOR_ARTS = 150, 6095")
    text = text.replace("FLOOR_LAWS, FLOOR_ARTS = 150, 6718", "FLOOR_LAWS, FLOOR_ARTS = 150, 6095")

    if dst_name == "belize_bm25_smoke.py":
        start = text.index("GATE = [")
        end = text.index("]", start) + 1
        years_line = ", ".join(f'"{y}"' for y in GATE_YEARS)
        stems_line = ", ".join(f'"{s}"' for s in GATE_STEMS)
        gate = f"GATE = [\n    {years_line},\n    {stems_line},\n]"
        text = text[:start] + gate + text[end:]
        text = text.replace('QUERIES = GATE + ["www", "gov", "ls"', 'QUERIES = GATE + ["www", "gov", "bz"')
        text = text.replace('QUERIES = GATE + ["www", "gov", "bz"', 'QUERIES = GATE + ["www", "gov", "bz"')
        note = (
            f"attested years {GATE_NOTE_YEARS} plus English legal stems {GATE_NOTE_STEMS} "
            f"from articles.parquet HEAD tip {DST_TIP_SHORT}; URL www/gov/bz is query-only, not GATE."
        )
        text = re.sub(
            r"GATE = attested years [^;]+; URL www/gov/(?:ls|bz) is query-only, not GATE\.",
            f"GATE = {note}",
            text,
        )
        text = text.replace('"lesotho_pass"', '"belize_pass"').replace('"belize_pass"', '"belize_pass"')
        text = text.replace('"lesotho_gate"', '"belize_gate"').replace('"belize_gate"', '"belize_gate"')

    if dst_name == "belize_write_publish_report.py":
        new_gate = f"{GATE_NOTE_YEARS} + stems {GATE_NOTE_STEMS}"
        text = re.sub(
            r"attested years [0-9/]+ \+ stems [a-z/]+",
            f"attested years {new_gate}",
            text,
        )
        text = text.replace("English GATE", "English (Belize) GATE")
        text = re.sub(
            r"HOLD 0 STRICT after-LS[^;]*; collectors kept dead \(pkill\); soft never-thin ON; SKIP_US; Italy BLOCKED;[^\"\n]*",
            f"{HOLD}; collectors kept dead (pkill); soft never-thin ON; SKIP_US; Italy BLOCKED; {WAVE_POS}",
            text,
        )
        text = re.sub(
            r"HOLD 0 STRICT after-BS[^;]*; collectors kept dead \(pkill\); soft never-thin ON; SKIP_US; Italy BLOCKED;[^\"\n]*",
            f"{HOLD}; collectors kept dead (pkill); soft never-thin ON; SKIP_US; Italy BLOCKED; {WAVE_POS}",
            text,
        )
        text = text.replace(
            "sixth country of after_bm wave (after TV→LR→SY→TO→BS LIVE)",
            WAVE_POS,
        )
        text = text.replace(
            "seventh country of after_bm wave (after TV→LR→SY→TO→BS LIVE)",
            WAVE_POS,
        )

    leftovers = (
        "French", "Haiti", "Nauru", "Montserrat", "Bermuda", "bermuda",
        "British Virgin Islands", "Gabon", "Togo", "Anguilla", "Cook Islands",
        "Tuvalu", "tuvalu", "Liberia", "liberia", "Syria", "syria", "Arabic",
        "arabic", "Tonga", "tonga", "Bahamas", "bahamas", "Lesotho", "lesotho",
        "bmjacency", "msjacency",
    )
    found = [x for x in leftovers if x in text]
    if found:
        raise RuntimeError(f"language/country leftovers in {dst_name}: {found}")
    if dst_name.endswith("_bm25_smoke.py") and '", "ls"' in text:
        raise RuntimeError(f"leftover ls query token in {dst_name}")
    if dst_name.endswith("_bm25_smoke.py") and "www/gov/ls" in text:
        raise RuntimeError(f"leftover gov/ls in {dst_name}")
    # reject bare ISO leftovers that should have been swapped
    # Allow intentional wave-position mention "after TV→LR→SY→TO→BS→LS LIVE" and HOLD after-LS
    scrub = text.replace("TV→LR→SY→TO→BS→LS", "TV→XX→SY→XX→XX→XX")
    scrub = scrub.replace("TV→LR→SY→TO→BS", "TV→XX→SY→XX→XX")
    scrub = scrub.replace("TV→LR→SY→TO", "TV→XX→SY→XX")
    scrub = scrub.replace("after-LS", "after-XX")
    scrub = scrub.replace("after LS ", "after XX ")
    scrub = scrub.replace("after-BS", "after-XX")
    scrub = scrub.replace("after BS ", "after XX ")
    if '"LS"' in scrub or "(LS)" in scrub or "LS→" in scrub or "LS-attested" in scrub:
        raise RuntimeError(f"leftover LS tokens in {dst_name}")
    if "Lesotho" in text or "Bahamas" in text or "lesotho" in text or "bahamas" in text:
        raise RuntimeError(f"leftover country name in {dst_name}")
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
    if entry.get("slug") == "belize" or entry.get("iso2") == "BZ":
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
                f"BZ FIRST_IR scaffold; tip MATCH {DST_TIP_SHORT}@150/6095; {HOLD}; "
                f"soft never-thin ON; SKIP_US; Italy BLOCKED; seventh of after_bm wave (after TV→LR→SY→TO→BS→LS LIVE)"
            ),
            "status": "CLAIMED",
        })
        break
else:
    raise RuntimeError("Belize entry missing from wave JSON")
wave.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print("updated wave JSON Belize entry")
print("GATE years", GATE_YEARS)
print("GATE stems", GATE_STEMS)
print("n_gate", len(GATE_YEARS) + len(GATE_STEMS))
