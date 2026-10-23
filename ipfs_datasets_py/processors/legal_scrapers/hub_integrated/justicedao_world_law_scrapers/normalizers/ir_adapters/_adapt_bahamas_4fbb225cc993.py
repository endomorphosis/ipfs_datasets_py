#!/usr/bin/env python3
"""Adapt the Tonga English memsafe FIRST_IR pack to Bahamas BS.

English Bahamas; FIRST_IR; HOLD 0 STRICT after-TO (BS→LS→BZ→SB→CW→MU→LC→TJ).
Soft never-thin ON; SKIP_US; Italy BLOCKED. WAVE after_bm fifth country (after TV→LR→SY→TO LIVE), NOT wave end.
GATE: attested years + English legal stems from articles.parquet tip 4fbb225cc993.
Source tip 7a3c6262c6de (Tonga English) — careful TO/to swaps (no bare English 'to').
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
SRC_TIP_FULL = "7a3c6262c6de75a8587ff6a9fe0cff087aad98c4"
SRC_TIP_SHORT = "7a3c6262c6de"
DST_TIP_FULL = "4fbb225cc993cb9ab19410bac4a196dad977529e"
DST_TIP_SHORT = "4fbb225cc993"
FLOOR_LAWS, FLOOR_ARTS = 150, 6922

# Sampled from data/articles.parquet @ 4fbb225cc993 (~10 years + ~11 stems; include bahamas)
GATE_YEARS = ["1969", "1965", "1962", "1970", "1973", "1958", "1963", "1971", "1956", "2001"]
GATE_STEMS = ["bahamas", "section", "act", "part", "shall", "person", "minister", "chapter", "court", "offence", "schedule"]
GATE_NOTE_YEARS = "/".join(GATE_YEARS)
GATE_NOTE_STEMS = "/".join(GATE_STEMS)
HOLD = "HOLD 0 STRICT after-TO (BS→LS→BZ→SB→CW→MU→LC→TJ)"
WAVE_POS = "fifth country of after_bm wave (after TV→LR→SY→TO LIVE)"

FILES = [
    ("tonga_soft_filter.py", "bahamas_soft_filter.py"),
    (f"tonga_corpus_stream_{SRC_TIP_SHORT}.py", f"bahamas_corpus_stream_{DST_TIP_SHORT}.py"),
    (f"tonga_encode_memsafe_{SRC_TIP_SHORT}.py", f"bahamas_encode_memsafe_{DST_TIP_SHORT}.py"),
    (f"tonga_finish_from_emb_{SRC_TIP_SHORT}.py", f"bahamas_finish_from_emb_{DST_TIP_SHORT}.py"),
    (f"tonga_stream_graph_parts_{SRC_TIP_SHORT}.py", f"bahamas_stream_graph_parts_{DST_TIP_SHORT}.py"),
    (f"tonga_package_memsafe_{SRC_TIP_SHORT}.py", f"bahamas_package_memsafe_{DST_TIP_SHORT}.py"),
    ("tonga_upload.py", "bahamas_upload.py"),
    ("tonga_bm25_smoke.py", "bahamas_bm25_smoke.py"),
    ("tonga_write_publish_report.py", "bahamas_write_publish_report.py"),
    (f"tonga_orchestrator_{SRC_TIP_SHORT}.py", f"bahamas_orchestrator_{DST_TIP_SHORT}.py"),
]


def adapt(text: str, dst_name: str) -> str:
    # Protect BM25 / bm25 and intentional wave chain tokens from ISO swaps
    text = text.replace("BM25", "\x00BM25\x00").replace("bm25", "\x00bm25\x00")
    text = text.replace("bmjacency", "adjacency")
    # Protect wave-chain mentions that must keep TO as prior LIVE country
    text = text.replace("TV→LR→SY→TO", "\x00WAVECHAIN\x00")
    text = text.replace("after-TO", "\x00AFTERTO\x00")
    text = text.replace("after TO ", "\x00AFTERTO_SP\x00")

    reps = [
        (SRC_TIP_FULL, DST_TIP_FULL),
        (SRC_TIP_SHORT, DST_TIP_SHORT),
        ("endomorphosis/ipfs_tonga_laws", "endomorphosis/ipfs_bahamas_laws"),
        ("justicedao/ipfs_tonga_laws_ir", "justicedao/ipfs_bahamas_laws_ir"),
        ("ipfs_tonga_laws_ir", "ipfs_bahamas_laws_ir"),
        ("ipfs_tonga_laws", "ipfs_bahamas_laws"),
        # HOLD / wave position BEFORE bare TO→BS swaps
        ("HOLD 0 STRICT after-SY (TO→BS→LS→BZ→SB→CW→MU→LC→TJ)", HOLD),
        ("after-SY (TO→BS→LS→BZ→SB→CW→MU→LC→TJ)", "after-TO (BS→LS→BZ→SB→CW→MU→LC→TJ)"),
        ("after-SY", "after-TO"),
        ("TO FIRST_IR (not wave end)", "BS FIRST_IR (not wave end)"),
        ("fourth country of after_bm wave (after TV→LR→SY LIVE)", WAVE_POS),
        ("fourth of after_bm wave (after TV→LR→SY LIVE)", "fifth of after_bm wave (after TV→LR→SY→TO LIVE)"),
        ("fourth country of after_bm wave", WAVE_POS),
        ("fourth of after_bm wave", "fifth of after_bm wave (after TV→LR→SY→TO LIVE)"),
        ("www/gov/to", "www/gov/bs"),
        ("English (Tonga)", "English (Bahamas)"),
        ("English Tonga", "English Bahamas"),
        ("Tonga", "Bahamas"),
        ("tonga", "bahamas"),
        # ISO whole-token / path forms only (avoid bare English 'to')
        ('"TO"', '"BS"'),
        ("TO-attested", "BS-attested"),
        ("(TO)", "(BS)"),
        ("TO→BS→LS", "BS→LS→BZ"),  # leftover chain start if any
        ('"to"', '"bs"'),
        ("/to", "/bs"),
        # floors 687/7016 → 150/6922
        ("687/7016", "150/6922"),
        ("687 / 7016", "150 / 6922"),
        ("687, 7016", "150, 6922"),
        ("= 687,", "= 150,"),
        ("= 687", "= 150"),
        ("@ 687/", "@ 150/"),
        (" 687/", " 150/"),
        ("floor 687/", "floor 150/"),
        ("(687/", "(150/"),
        (" 7016", " 6922"),
        ("7016", "6922"),
        ("FLOOR_LAWS, FLOOR_ARTS = 687, 6922", "FLOOR_LAWS, FLOOR_ARTS = 150, 6922"),
        ("FLOOR_LAWS, FLOOR_ARTS = 687, 7016", "FLOOR_LAWS, FLOOR_ARTS = 150, 6922"),
        ("or 687)", "or 150)"),
        ("or 687,", "or 150,"),
    ]
    for a, b in reps:
        text = text.replace(a, b)

    text = text.replace("\x00BM25\x00", "BM25").replace("\x00bm25\x00", "bm25")
    text = text.replace("\x00WAVECHAIN\x00", "TV→LR→SY→TO")
    text = text.replace("\x00AFTERTO\x00", "after-TO")
    text = text.replace("\x00AFTERTO_SP\x00", "after TO ")

    text = text.replace("FLOOR_LAWS, FLOOR_ARTS = 687, 6922", "FLOOR_LAWS, FLOOR_ARTS = 150, 6922")
    text = text.replace("FLOOR_LAWS, FLOOR_ARTS = 150, 7016", "FLOOR_LAWS, FLOOR_ARTS = 150, 6922")

    if dst_name == "bahamas_bm25_smoke.py":
        start = text.index("GATE = [")
        end = text.index("]", start) + 1
        years_line = ", ".join(f'"{y}"' for y in GATE_YEARS)
        stems_line = ", ".join(f'"{s}"' for s in GATE_STEMS)
        gate = f"GATE = [\n    {years_line},\n    {stems_line},\n]"
        text = text[:start] + gate + text[end:]
        text = text.replace('QUERIES = GATE + ["www", "gov", "to"', 'QUERIES = GATE + ["www", "gov", "bs"')
        text = text.replace('QUERIES = GATE + ["www", "gov", "bs"', 'QUERIES = GATE + ["www", "gov", "bs"')
        note = (
            f"attested years {GATE_NOTE_YEARS} plus English legal stems {GATE_NOTE_STEMS} "
            f"from articles.parquet HEAD tip {DST_TIP_SHORT}; URL www/gov/bs is query-only, not GATE."
        )
        text = re.sub(
            r"GATE = attested years [^;]+; URL www/gov/(?:to|bs) is query-only, not GATE\.",
            f"GATE = {note}",
            text,
        )
        text = text.replace('"tonga_pass"', '"bahamas_pass"').replace('"bahamas_pass"', '"bahamas_pass"')
        text = text.replace('"tonga_gate"', '"bahamas_gate"').replace('"bahamas_gate"', '"bahamas_gate"')

    if dst_name == "bahamas_write_publish_report.py":
        new_gate = f"{GATE_NOTE_YEARS} + stems {GATE_NOTE_STEMS}"
        text = re.sub(
            r"attested years [0-9/]+ \+ stems [a-z/]+",
            f"attested years {new_gate}",
            text,
        )
        text = text.replace("English GATE", "English (Bahamas) GATE")
        text = re.sub(
            r"HOLD 0 STRICT after-TO[^;]*; collectors kept dead \(pkill\); soft never-thin ON; SKIP_US; Italy BLOCKED;[^\"\n]*",
            f"{HOLD}; collectors kept dead (pkill); soft never-thin ON; SKIP_US; Italy BLOCKED; {WAVE_POS}",
            text,
        )
        text = text.replace(
            "fourth country of after_bm wave (after TV→LR→SY LIVE)",
            WAVE_POS,
        )
        text = text.replace(
            "fifth country of after_bm wave (after TV→LR→SY LIVE)",
            WAVE_POS,
        )

    leftovers = (
        "French", "Haiti", "Nauru", "Montserrat", "Bermuda", "bermuda",
        "British Virgin Islands", "Gabon", "Togo", "Anguilla", "Cook Islands",
        "Tuvalu", "tuvalu", "Liberia", "liberia", "Syria", "syria", "Arabic",
        "arabic", "Tonga", "tonga", "bmjacency", "msjacency",
    )
    found = [x for x in leftovers if x in text]
    if found:
        raise RuntimeError(f"language/country leftovers in {dst_name}: {found}")
    if dst_name.endswith("_bm25_smoke.py") and '", "to"' in text:
        raise RuntimeError(f"leftover to query token in {dst_name}")
    if dst_name.endswith("_bm25_smoke.py") and "www/gov/to" in text:
        raise RuntimeError(f"leftover gov/to in {dst_name}")
    # reject bare ISO leftovers that should have been swapped
    # Allow intentional wave-position mention "after TV→LR→SY→TO LIVE" and HOLD after-TO
    scrub = text.replace("TV→LR→SY→TO", "TV→XX→SY→XX")
    scrub = scrub.replace("after-TO", "after-XX")
    scrub = scrub.replace("after TO ", "after XX ")
    if '"TO"' in scrub or "(TO)" in scrub or "TO→" in scrub or "TO-attested" in scrub:
        raise RuntimeError(f"leftover TO tokens in {dst_name}")
    if "Liberia" in text or "Syria" in text or "Tonga" in text:
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
    if entry.get("slug") == "bahamas" or entry.get("iso2") == "BS":
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
                f"BS FIRST_IR scaffold; tip MATCH {DST_TIP_SHORT}@150/6922; {HOLD}; "
                f"soft never-thin ON; SKIP_US; Italy BLOCKED; fifth of after_bm wave (after TV→LR→SY→TO LIVE)"
            ),
            "status": "CLAIMED",
        })
        break
else:
    raise RuntimeError("Bahamas entry missing from wave JSON")
wave.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print("updated wave JSON Bahamas entry")
print("GATE years", GATE_YEARS)
print("GATE stems", GATE_STEMS)
print("n_gate", len(GATE_YEARS) + len(GATE_STEMS))
