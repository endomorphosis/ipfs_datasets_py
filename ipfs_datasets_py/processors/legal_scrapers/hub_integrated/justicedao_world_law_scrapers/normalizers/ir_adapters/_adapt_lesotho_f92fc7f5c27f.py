#!/usr/bin/env python3
"""Adapt the Bahamas English memsafe FIRST_IR pack to Lesotho LS.

English Lesotho; FIRST_IR; HOLD 0 STRICT after-BS (LS→BZ→SB→CW→MU→LC→TJ).
Soft never-thin ON; SKIP_US; Italy BLOCKED. WAVE after_bm sixth country
(after TV→LR→SY→TO→BS LIVE), NOT wave end.
GATE: attested years + English legal stems from articles.parquet tip f92fc7f5c27f.
Source tip 4fbb225cc993 (Bahamas English).
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
SRC_TIP_FULL = "4fbb225cc993cb9ab19410bac4a196dad977529e"
SRC_TIP_SHORT = "4fbb225cc993"
DST_TIP_FULL = "f92fc7f5c27fb1f012876edd29d0c3fbf16b34d5"
DST_TIP_SHORT = "f92fc7f5c27f"
FLOOR_LAWS, FLOOR_ARTS = 90, 6718

# Sampled from data/articles.parquet @ f92fc7f5c27f (~10 years + ~11 stems; include lesotho)
GATE_YEARS = ["2016", "2024", "2023", "1999", "2014", "2000", "2018", "2019", "2009", "2013"]
GATE_STEMS = ["lesotho", "shall", "act", "section", "person", "court", "order", "minister", "regulation", "provision", "offence"]
GATE_NOTE_YEARS = "/".join(GATE_YEARS)
GATE_NOTE_STEMS = "/".join(GATE_STEMS)
HOLD = "HOLD 0 STRICT after-BS (LS→BZ→SB→CW→MU→LC→TJ)"
WAVE_POS = "sixth country of after_bm wave (after TV→LR→SY→TO→BS LIVE)"

FILES = [
    ("bahamas_soft_filter.py", "lesotho_soft_filter.py"),
    (f"bahamas_corpus_stream_{SRC_TIP_SHORT}.py", f"lesotho_corpus_stream_{DST_TIP_SHORT}.py"),
    (f"bahamas_encode_memsafe_{SRC_TIP_SHORT}.py", f"lesotho_encode_memsafe_{DST_TIP_SHORT}.py"),
    (f"bahamas_finish_from_emb_{SRC_TIP_SHORT}.py", f"lesotho_finish_from_emb_{DST_TIP_SHORT}.py"),
    (f"bahamas_stream_graph_parts_{SRC_TIP_SHORT}.py", f"lesotho_stream_graph_parts_{DST_TIP_SHORT}.py"),
    (f"bahamas_package_memsafe_{SRC_TIP_SHORT}.py", f"lesotho_package_memsafe_{DST_TIP_SHORT}.py"),
    ("bahamas_upload.py", "lesotho_upload.py"),
    ("bahamas_bm25_smoke.py", "lesotho_bm25_smoke.py"),
    ("bahamas_write_publish_report.py", "lesotho_write_publish_report.py"),
    (f"bahamas_orchestrator_{SRC_TIP_SHORT}.py", f"lesotho_orchestrator_{DST_TIP_SHORT}.py"),
]


def adapt(text: str, dst_name: str) -> str:
    # Protect BM25 / bm25 and intentional wave chain tokens from ISO swaps
    text = text.replace("BM25", "\x00BM25\x00").replace("bm25", "\x00bm25\x00")
    text = text.replace("bmjacency", "adjacency")
    # Protect wave-chain mentions that must keep BS as prior LIVE country
    text = text.replace("TV→LR→SY→TO→BS", "\x00WAVECHAIN\x00")
    text = text.replace("TV→LR→SY→TO", "\x00WAVECHAIN_SHORT\x00")
    # Do NOT protect after-TO — source Bahamas HOLD must rewrite to after-BS.
    text = text.replace("after-BS", "\x00AFTERBS\x00")
    text = text.replace("after BS ", "\x00AFTERBS_SP\x00")

    reps = [
        (SRC_TIP_FULL, DST_TIP_FULL),
        (SRC_TIP_SHORT, DST_TIP_SHORT),
        ("endomorphosis/ipfs_bahamas_laws", "endomorphosis/ipfs_lesotho_laws"),
        ("justicedao/ipfs_bahamas_laws_ir", "justicedao/ipfs_lesotho_laws_ir"),
        ("ipfs_bahamas_laws_ir", "ipfs_lesotho_laws_ir"),
        ("ipfs_bahamas_laws", "ipfs_lesotho_laws"),
        # HOLD / wave position BEFORE bare BS→LS swaps
        ("HOLD 0 STRICT after-TO (BS→LS→BZ→SB→CW→MU→LC→TJ)", HOLD),
        ("after-TO (BS→LS→BZ→SB→CW→MU→LC→TJ)", "after-BS (LS→BZ→SB→CW→MU→LC→TJ)"),
        ("BS→LS→BZ→SB→CW→MU→LC→TJ", "LS→BZ→SB→CW→MU→LC→TJ"),
        ("BS FIRST_IR (not wave end)", "LS FIRST_IR (not wave end)"),
        ("fifth country of after_bm wave (after TV→LR→SY→TO LIVE)", WAVE_POS),
        ("fifth of after_bm wave (after TV→LR→SY→TO LIVE)", "sixth of after_bm wave (after TV→LR→SY→TO→BS LIVE)"),
        ("fifth country of after_bm wave", WAVE_POS),
        ("fifth of after_bm wave", "sixth of after_bm wave (after TV→LR→SY→TO→BS LIVE)"),
        ("www/gov/bs", "www/gov/ls"),
        ("English (Bahamas)", "English (Lesotho)"),
        ("English Bahamas", "English Lesotho"),
        ("Bahamas", "Lesotho"),
        ("bahamas", "lesotho"),
        # ISO whole-token / path forms only
        ('"BS"', '"LS"'),
        ("BS-attested", "LS-attested"),
        ("(BS)", "(LS)"),
        ('"bs"', '"ls"'),
        ("/bs", "/ls"),
        # floors 150/6922 → 90/6718
        ("150/6922", "90/6718"),
        ("150 / 6922", "90 / 6718"),
        ("150, 6922", "90, 6718"),
        ("= 150,", "= 90,"),
        ("= 150", "= 90"),
        ("@ 150/", "@ 90/"),
        (" 150/", " 90/"),
        ("floor 150/", "floor 90/"),
        ("(150/", "(90/"),
        (" 6922", " 6718"),
        ("6922", "6718"),
        ("FLOOR_LAWS, FLOOR_ARTS = 150, 6718", "FLOOR_LAWS, FLOOR_ARTS = 90, 6718"),
        ("FLOOR_LAWS, FLOOR_ARTS = 150, 6922", "FLOOR_LAWS, FLOOR_ARTS = 90, 6718"),
        ("or 150)", "or 90)"),
        ("or 150,", "or 90,"),
    ]
    for a, b in reps:
        text = text.replace(a, b)

    text = text.replace("\x00BM25\x00", "BM25").replace("\x00bm25\x00", "bm25")
    text = text.replace("\x00WAVECHAIN\x00", "TV→LR→SY→TO→BS")
    text = text.replace("\x00WAVECHAIN_SHORT\x00", "TV→LR→SY→TO")
    text = text.replace("\x00AFTERBS\x00", "after-BS")
    text = text.replace("\x00AFTERBS_SP\x00", "after BS ")

    text = text.replace("FLOOR_LAWS, FLOOR_ARTS = 150, 6718", "FLOOR_LAWS, FLOOR_ARTS = 90, 6718")
    text = text.replace("FLOOR_LAWS, FLOOR_ARTS = 90, 6922", "FLOOR_LAWS, FLOOR_ARTS = 90, 6718")

    if dst_name == "lesotho_bm25_smoke.py":
        start = text.index("GATE = [")
        end = text.index("]", start) + 1
        years_line = ", ".join(f'"{y}"' for y in GATE_YEARS)
        stems_line = ", ".join(f'"{s}"' for s in GATE_STEMS)
        gate = f"GATE = [\n    {years_line},\n    {stems_line},\n]"
        text = text[:start] + gate + text[end:]
        text = text.replace('QUERIES = GATE + ["www", "gov", "bs"', 'QUERIES = GATE + ["www", "gov", "ls"')
        text = text.replace('QUERIES = GATE + ["www", "gov", "ls"', 'QUERIES = GATE + ["www", "gov", "ls"')
        note = (
            f"attested years {GATE_NOTE_YEARS} plus English legal stems {GATE_NOTE_STEMS} "
            f"from articles.parquet HEAD tip {DST_TIP_SHORT}; URL www/gov/ls is query-only, not GATE."
        )
        text = re.sub(
            r"GATE = attested years [^;]+; URL www/gov/(?:bs|ls) is query-only, not GATE\.",
            f"GATE = {note}",
            text,
        )
        text = text.replace('"bahamas_pass"', '"lesotho_pass"').replace('"lesotho_pass"', '"lesotho_pass"')
        text = text.replace('"bahamas_gate"', '"lesotho_gate"').replace('"lesotho_gate"', '"lesotho_gate"')

    if dst_name == "lesotho_write_publish_report.py":
        new_gate = f"{GATE_NOTE_YEARS} + stems {GATE_NOTE_STEMS}"
        text = re.sub(
            r"attested years [0-9/]+ \+ stems [a-z/]+",
            f"attested years {new_gate}",
            text,
        )
        text = text.replace("English GATE", "English (Lesotho) GATE")
        text = re.sub(
            r"HOLD 0 STRICT after-BS[^;]*; collectors kept dead \(pkill\); soft never-thin ON; SKIP_US; Italy BLOCKED;[^\"\n]*",
            f"{HOLD}; collectors kept dead (pkill); soft never-thin ON; SKIP_US; Italy BLOCKED; {WAVE_POS}",
            text,
        )
        # also catch leftover after-TO form if adapt missed
        text = re.sub(
            r"HOLD 0 STRICT after-TO[^;]*; collectors kept dead \(pkill\); soft never-thin ON; SKIP_US; Italy BLOCKED;[^\"\n]*",
            f"{HOLD}; collectors kept dead (pkill); soft never-thin ON; SKIP_US; Italy BLOCKED; {WAVE_POS}",
            text,
        )
        text = text.replace(
            "fifth country of after_bm wave (after TV→LR→SY→TO LIVE)",
            WAVE_POS,
        )
        text = text.replace(
            "sixth country of after_bm wave (after TV→LR→SY→TO LIVE)",
            WAVE_POS,
        )

    leftovers = (
        "French", "Haiti", "Nauru", "Montserrat", "Bermuda", "bermuda",
        "British Virgin Islands", "Gabon", "Togo", "Anguilla", "Cook Islands",
        "Tuvalu", "tuvalu", "Liberia", "liberia", "Syria", "syria", "Arabic",
        "arabic", "Tonga", "tonga", "Bahamas", "bahamas", "bmjacency", "msjacency",
    )
    found = [x for x in leftovers if x in text]
    if found:
        raise RuntimeError(f"language/country leftovers in {dst_name}: {found}")
    if dst_name.endswith("_bm25_smoke.py") and '", "bs"' in text:
        raise RuntimeError(f"leftover bs query token in {dst_name}")
    if dst_name.endswith("_bm25_smoke.py") and "www/gov/bs" in text:
        raise RuntimeError(f"leftover gov/bs in {dst_name}")
    # reject bare ISO leftovers that should have been swapped
    # Allow intentional wave-position mention "after TV→LR→SY→TO→BS LIVE" and HOLD after-BS
    scrub = text.replace("TV→LR→SY→TO→BS", "TV→XX→SY→XX→XX")
    scrub = scrub.replace("TV→LR→SY→TO", "TV→XX→SY→XX")
    scrub = scrub.replace("after-BS", "after-XX")
    scrub = scrub.replace("after BS ", "after XX ")
    scrub = scrub.replace("after-TO", "after-XX")
    scrub = scrub.replace("after TO ", "after XX ")
    if '"BS"' in scrub or "(BS)" in scrub or "BS→" in scrub or "BS-attested" in scrub:
        raise RuntimeError(f"leftover BS tokens in {dst_name}")
    if "Bahamas" in text or "Tonga" in text or "bahamas" in text or "tonga" in text:
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
    if entry.get("slug") == "lesotho" or entry.get("iso2") == "LS":
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
                f"LS FIRST_IR scaffold; tip MATCH {DST_TIP_SHORT}@90/6718; {HOLD}; "
                f"soft never-thin ON; SKIP_US; Italy BLOCKED; sixth of after_bm wave (after TV→LR→SY→TO→BS LIVE)"
            ),
            "status": "CLAIMED",
        })
        break
else:
    raise RuntimeError("Lesotho entry missing from wave JSON")
wave.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print("updated wave JSON Lesotho entry")
print("GATE years", GATE_YEARS)
print("GATE stems", GATE_STEMS)
print("n_gate", len(GATE_YEARS) + len(GATE_STEMS))
