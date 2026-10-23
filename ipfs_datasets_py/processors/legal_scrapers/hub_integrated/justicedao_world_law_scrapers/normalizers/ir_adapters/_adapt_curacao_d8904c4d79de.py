#!/usr/bin/env python3
"""Adapt the Solomon Islands English memsafe FIRST_IR pack to Curaçao CW.

Dutch (Curaçao); FIRST_IR; HOLD 0 STRICT after-SB (CW→MU→LC→TJ).
Soft never-thin ON; SKIP_US; Italy BLOCKED. WAVE after_bm ninth country
(after TV→LR→SY→TO→BS→LS→BZ→SB LIVE), NOT wave end.
GATE: attested years + Dutch legal stems from articles.parquet tip d8904c4d79de
(Sint Maarten pattern: years+stems preferred; years-primary fallback).
Source tip c921827129d0 (Solomon Islands English).
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
DST_TIP_FULL = "d8904c4d79deb737f1955ed04c97a5ce86c96ca3"
DST_TIP_SHORT = "d8904c4d79de"
FLOOR_LAWS, FLOOR_ARTS = 175, 5776

# Sampled from data/articles.parquet @ d8904c4d79de (~10 years + ~11 Dutch stems; ASCII Latin)
GATE_YEARS = ["2024", "2023", "2010", "2025", "2022", "1996", "2001", "1999", "1997", "2011"]
GATE_STEMS = [
    "artikel", "wet", "koninkrijk", "minister", "besluit",
    "persoon", "hoofdstuk", "lid", "straf", "regeling", "curacao",
]
GATE_NOTE_YEARS = "/".join(GATE_YEARS)
GATE_NOTE_STEMS = "/".join(GATE_STEMS)
HOLD = "HOLD 0 STRICT after-SB (CW→MU→LC→TJ)"
WAVE_POS = "ninth country of after_bm wave (after TV→LR→SY→TO→BS→LS→BZ→SB LIVE)"

FILES = [
    ("solomonislands_soft_filter.py", "curacao_soft_filter.py"),
    (f"solomonislands_corpus_stream_{SRC_TIP_SHORT}.py", f"curacao_corpus_stream_{DST_TIP_SHORT}.py"),
    (f"solomonislands_encode_memsafe_{SRC_TIP_SHORT}.py", f"curacao_encode_memsafe_{DST_TIP_SHORT}.py"),
    (f"solomonislands_finish_from_emb_{SRC_TIP_SHORT}.py", f"curacao_finish_from_emb_{DST_TIP_SHORT}.py"),
    (f"solomonislands_stream_graph_parts_{SRC_TIP_SHORT}.py", f"curacao_stream_graph_parts_{DST_TIP_SHORT}.py"),
    (f"solomonislands_package_memsafe_{SRC_TIP_SHORT}.py", f"curacao_package_memsafe_{DST_TIP_SHORT}.py"),
    ("solomonislands_upload.py", "curacao_upload.py"),
    ("solomonislands_bm25_smoke.py", "curacao_bm25_smoke.py"),
    ("solomonislands_write_publish_report.py", "curacao_write_publish_report.py"),
    (f"solomonislands_orchestrator_{SRC_TIP_SHORT}.py", f"curacao_orchestrator_{DST_TIP_SHORT}.py"),
]


def adapt(text: str, dst_name: str) -> str:
    # Protect BM25 / bm25 and intentional wave-chain tokens from ISO swaps
    text = text.replace("BM25", "\x00BM25\x00").replace("bm25", "\x00bm25\x00")
    text = text.replace("bmjacency", "adjacency")
    # Protect full wave-chain mentions that must keep prior LIVE countries incl. SB
    text = text.replace("TV→LR→SY→TO→BS→LS→BZ→SB", "\x00WAVECHAIN9\x00")
    text = text.replace("TV→LR→SY→TO→BS→LS→BZ", "\x00WAVECHAIN8\x00")
    text = text.replace("TV→LR→SY→TO→BS→LS", "\x00WAVECHAIN7\x00")
    text = text.replace("TV→LR→SY→TO→BS", "\x00WAVECHAIN6\x00")
    text = text.replace("TV→LR→SY→TO", "\x00WAVECHAIN5\x00")
    # Protect destination HOLD after-SB form once written; source after-BZ must rewrite
    text = text.replace("after-SB", "\x00AFTERSB\x00")
    text = text.replace("after SB ", "\x00AFTERSB_SP\x00")
    text = text.replace("after-BZ", "\x00AFTERBZ\x00")
    text = text.replace("after BZ ", "\x00AFTERBZ_SP\x00")
    # Protect SB→CW→MU chain before ISO swaps (source HOLD chain)
    text = text.replace("SB→CW→MU→LC→TJ", "\x00HOLDCHAIN\x00")
    text = text.replace("CW→MU→LC→TJ", "\x00DESTCHAIN\x00")

    reps = [
        (SRC_TIP_FULL, DST_TIP_FULL),
        (SRC_TIP_SHORT, DST_TIP_SHORT),
        ("endomorphosis/ipfs_solomonislands_laws", "endomorphosis/ipfs_curacao_laws"),
        ("justicedao/ipfs_solomonislands_laws_ir", "justicedao/ipfs_curacao_laws_ir"),
        ("ipfs_solomonislands_laws_ir", "ipfs_curacao_laws_ir"),
        ("ipfs_solomonislands_laws", "ipfs_curacao_laws"),
        # HOLD / wave position BEFORE bare SB→CW swaps
        ("HOLD 0 STRICT after-BZ (SB→CW→MU→LC→TJ)", HOLD),
        ("HOLD 0 STRICT \x00AFTERBZ\x00 (\x00HOLDCHAIN\x00)", HOLD),
        ("after-BZ (SB→CW→MU→LC→TJ)", "after-SB (CW→MU→LC→TJ)"),
        ("SB FIRST_IR (not wave end)", "CW FIRST_IR (not wave end)"),
        ("eighth country of after_bm wave (after TV→LR→SY→TO→BS→LS→BZ LIVE)", WAVE_POS),
        ("eighth of after_bm wave (after TV→LR→SY→TO→BS→LS→BZ LIVE)", "ninth of after_bm wave (after TV→LR→SY→TO→BS→LS→BZ→SB LIVE)"),
        ("eighth country of after_bm wave", WAVE_POS),
        ("eighth of after_bm wave", "ninth of after_bm wave (after TV→LR→SY→TO→BS→LS→BZ→SB LIVE)"),
        ("www/gov/sb", "www/gov/cw"),
        ("English (Solomon Islands)", "Dutch (Curaçao)"),
        ("English Solomon Islands", "Dutch Curaçao"),
        ("Solomon Islands", "Curaçao"),
        ("solomonislands", "curacao"),
        # ISO whole-token / path forms only
        ('"SB"', '"CW"'),
        ("SB-attested", "CW-attested"),
        ("(SB)", "(CW)"),
        ('"sb"', '"cw"'),
        ("/sb", "/cw"),
        # language
        ("English legal", "Dutch legal"),
        ("English GATE", "Dutch GATE"),
        ("— English ", "— Dutch "),
        ("English legal corpus", "Dutch legal corpus"),
        # floors 224/6049 → 175/5776
        ("224/6049", "175/5776"),
        ("224 / 6049", "175 / 5776"),
        ("224, 6049", "175, 5776"),
        ("FLOOR_LAWS, FLOOR_ARTS = 224, 6049", "FLOOR_LAWS, FLOOR_ARTS = 175, 5776"),
        ("or 224)", "or 175)"),
        ("or 224,", "or 175,"),
        ("or 224,", "or 175,"),
        ("= 224,", "= 175,"),
        ("= 224", "= 175"),
        ("@ 224/", "@ 175/"),
        (" 224/", " 175/"),
        ("floor 224/", "floor 175/"),
        ("(224/", "(175/"),
        (" or 224", " or 175"),
        (" 6049", " 5776"),
        ("6049", "5776"),
    ]
    for a, b in reps:
        text = text.replace(a, b)

    text = text.replace("\x00BM25\x00", "BM25").replace("\x00bm25\x00", "bm25")
    text = text.replace("\x00WAVECHAIN9\x00", "TV→LR→SY→TO→BS→LS→BZ→SB")
    text = text.replace("\x00WAVECHAIN8\x00", "TV→LR→SY→TO→BS→LS→BZ")
    text = text.replace("\x00WAVECHAIN7\x00", "TV→LR→SY→TO→BS→LS")
    text = text.replace("\x00WAVECHAIN6\x00", "TV→LR→SY→TO→BS")
    text = text.replace("\x00WAVECHAIN5\x00", "TV→LR→SY→TO")
    text = text.replace("\x00HOLDCHAIN\x00", "CW→MU→LC→TJ")  # after after-SB rewrite
    text = text.replace("\x00DESTCHAIN\x00", "CW→MU→LC→TJ")
    text = text.replace("\x00AFTERSB\x00", "after-SB")
    text = text.replace("\x00AFTERSB_SP\x00", "after SB ")
    # Source after-BZ that wasn't rewritten via full HOLD string → rewrite to after-SB
    text = text.replace("\x00AFTERBZ\x00", "after-SB")
    text = text.replace("\x00AFTERBZ_SP\x00", "after SB ")

    text = text.replace("FLOOR_LAWS, FLOOR_ARTS = 224, 5776", "FLOOR_LAWS, FLOOR_ARTS = 175, 5776")
    text = text.replace("FLOOR_LAWS, FLOOR_ARTS = 175, 6049", "FLOOR_LAWS, FLOOR_ARTS = 175, 5776")
    # pack.get defaults
    text = text.replace("or 224)", "or 175)")
    text = text.replace("or 224,", "or 175,")
    text = text.replace("or 224}", "or 175}")
    text = text.replace("or 224,", "or 175,")

    if dst_name == "curacao_bm25_smoke.py":
        start = text.index("GATE = [")
        end = text.index("]", start) + 1
        years_line = ", ".join(f'"{y}"' for y in GATE_YEARS)
        stems_line = ", ".join(f'"{s}"' for s in GATE_STEMS)
        gate = (
            "GATE_YEARS = [\n"
            f"    {years_line},\n"
            "]\n"
            "GATE_STEMS = [\n"
            f"    {stems_line},\n"
            "]\n"
            "GATE = GATE_YEARS + GATE_STEMS"
        )
        text = text[:start] + gate + text[end:]
        text = text.replace(
            'QUERIES = GATE + ["www", "gov", "sb"',
            'QUERIES = GATE + ["www", "gov", "cw"',
        )
        text = text.replace(
            'QUERIES = GATE + ["www", "gov", "cw", "article", "legal", "regulation", "minister", "court"]',
            'QUERIES = GATE + ["www", "gov", "cw", "article", "legal", "regulation", "minister", "court", "law", "shall"]',
        )
        # Sint Maarten-style years-primary fallback for Dutch stems
        text = text.replace(
            '    ok = all(q in detail["ranked"] for q in GATE)',
            '    missing_stems = [q for q in GATE_STEMS if q not in detail["ranked"]]\n'
            '    selected_gate = GATE if not missing_stems else GATE_YEARS\n'
            '    gate_fallback = bool(missing_stems)\n'
            '    ok = all(q in detail["ranked"] for q in selected_gate)',
        )
        note = (
            f"preferred GATE = attested years {GATE_NOTE_YEARS} plus Dutch legal stems "
            f"{GATE_NOTE_STEMS} from articles.parquet HEAD tip {DST_TIP_SHORT}; "
            f"English law/shall are query-only; URL www/gov/cw is query-only, not GATE."
        )
        # Replace tokenizer_note detail.update block fields
        text = re.sub(
            r'"tokenizer_note": "[^"]*"',
            f'"tokenizer_note": "ASCII-after-diacritic-fold tokenizer ([0-9A-Za-z]+); {note}"',
            text,
        )
        text = text.replace('"curacao_pass": ok, "curacao_gate": GATE',
                            '"curacao_pass": ok, "curacao_gate": selected_gate, '
                            '"gate_preferred": GATE, "gate_fallback_years_primary": gate_fallback, '
                            '"missing_dutch_stems": missing_stems')
        text = text.replace('"solomonislands_pass"', '"curacao_pass"')
        text = text.replace('"solomonislands_gate"', '"curacao_gate"')
        text = text.replace(
            '"n_gate_ranked": sum(q in detail["ranked"] for q in GATE), "n_gate": len(GATE), "gate": GATE',
            '"n_gate_ranked": sum(q in detail["ranked"] for q in selected_gate), "n_gate": len(selected_gate), '
            '"gate": selected_gate, "gate_preferred": GATE, "gate_fallback_years_primary": gate_fallback, '
            '"missing_dutch_stems": missing_stems',
        )
        # docstring
        text = text.replace("English legal corpus", "Dutch legal corpus")
        text = text.replace("attested Curaçao years and English legal stems",
                            "attested Curaçao years and Dutch legal stems")
        text = text.replace("attested Solomon Islands years and English legal stems",
                            "attested Curaçao years and Dutch legal stems")

    if dst_name == "curacao_write_publish_report.py":
        new_gate = f"{GATE_NOTE_YEARS} + stems {GATE_NOTE_STEMS}"
        text = re.sub(
            r"attested years [0-9/]+ \+ stems [a-z/]+",
            f"attested years {new_gate}",
            text,
        )
        # Fix any residual English GATE wording from Solomon
        text = text.replace(
            "ASCII-fold Dutch (Curaçao) GATE",
            "ASCII-fold Dutch (Curaçao) GATE",
        )
        text = text.replace(
            "BM25 PASS on Curaçao ASCII-fold Dutch (Curaçao) GATE",
            "BM25 PASS on Curaçao ASCII-fold Dutch (Curaçao) GATE",
        )
        # If still English somehow
        text = text.replace("ASCII-fold English (Curaçao) GATE", "ASCII-fold Dutch (Curaçao) GATE")
        text = text.replace("English (Curaçao) GATE", "Dutch (Curaçao) GATE")
        text = re.sub(
            r"HOLD 0 STRICT after-SB[^;]*; collectors kept dead \(pkill\); soft never-thin ON; SKIP_US; Italy BLOCKED;[^\"\n]*",
            f"{HOLD}; collectors kept dead (pkill); soft never-thin ON; SKIP_US; Italy BLOCKED; {WAVE_POS}",
            text,
        )
        text = re.sub(
            r"HOLD 0 STRICT after-BZ[^;]*; collectors kept dead \(pkill\); soft never-thin ON; SKIP_US; Italy BLOCKED;[^\"\n]*",
            f"{HOLD}; collectors kept dead (pkill); soft never-thin ON; SKIP_US; Italy BLOCKED; {WAVE_POS}",
            text,
        )
        text = text.replace(
            "eighth country of after_bm wave (after TV→LR→SY→TO→BS→LS→BZ LIVE)",
            WAVE_POS,
        )
        text = text.replace(
            "ninth country of after_bm wave (after TV→LR→SY→TO→BS→LS→BZ LIVE)",
            WAVE_POS,
        )
        # Ensure URL query-only note mentions cw
        text = text.replace("www/gov/sb is query-only", "www/gov/cw is query-only")

    leftovers = (
        "Solomon Islands", "solomonislands", "solomon",
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
    # Allow intentional English query-only mentions in smoke/publish
    scrub_en = text
    for keep in (
        "English law/shall",
        "English law/shall are query-only",
    ):
        scrub_en = scrub_en.replace(keep, "\x00ENKEEP\x00")
    if "English" in scrub_en and dst_name in (
        "curacao_bm25_smoke.py",
        "curacao_write_publish_report.py",
        "curacao_soft_filter.py",
        "curacao_orchestrator_d8904c4d79de.py",
    ):
        # remaining English is a problem in these
        if "English" in scrub_en:
            # find context
            idx = scrub_en.index("English")
            raise RuntimeError(
                f"leftover English in {dst_name} near: {scrub_en[max(0,idx-40):idx+60]!r}"
            )
    if dst_name.endswith("_bm25_smoke.py") and '", "sb"' in text:
        raise RuntimeError(f"leftover sb query token in {dst_name}")
    if dst_name.endswith("_bm25_smoke.py") and "www/gov/sb" in text:
        raise RuntimeError(f"leftover gov/sb in {dst_name}")
    # reject bare ISO leftovers that should have been swapped
    scrub = text.replace("TV→LR→SY→TO→BS→LS→BZ→SB", "TV→XX→SY→XX→XX→XX→XX→XX")
    scrub = scrub.replace("TV→LR→SY→TO→BS→LS→BZ", "TV→XX→SY→XX→XX→XX→XX")
    scrub = scrub.replace("TV→LR→SY→TO→BS→LS", "TV→XX→SY→XX→XX→XX")
    scrub = scrub.replace("TV→LR→SY→TO→BS", "TV→XX→SY→XX→XX")
    scrub = scrub.replace("TV→LR→SY→TO", "TV→XX→SY→XX")
    scrub = scrub.replace("after-SB", "after-XX")
    scrub = scrub.replace("after SB ", "after XX ")
    scrub = scrub.replace("after-BZ", "after-XX")
    scrub = scrub.replace("CW→MU→LC→TJ", "XX→XX→XX→XX")
    scrub = scrub.replace("SB→CW→MU→LC→TJ", "XX→XX→XX→XX→XX")
    if '"SB"' in scrub or "(SB)" in scrub or "SB→" in scrub or "SB-attested" in scrub:
        raise RuntimeError(f"leftover SB tokens in {dst_name}")
    if "Solomon" in text or "belize" in text.lower() and "Belize" in leftovers:
        if "Solomon" in text:
            raise RuntimeError(f"leftover Solomon in {dst_name}")
    if "ipfs_solomon" in text or "solomonislands" in text:
        raise RuntimeError(f"leftover solomon path in {dst_name}")
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
    if entry.get("slug") == "curacao" or entry.get("iso2") == "CW":
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
            "language": "Dutch (Curaçao)",
            "lang": "Dutch",
            "years_attested": [int(y) for y in GATE_YEARS],
            "gate_years": [int(y) for y in GATE_YEARS],
            "gate_stems": GATE_STEMS,
            "note": (
                f"CW FIRST_IR scaffold; tip MATCH {DST_TIP_SHORT}@175/5776; {HOLD}; "
                f"soft never-thin ON; SKIP_US; Italy BLOCKED; {WAVE_POS}"
            ),
            "status": "CLAIMED",
        })
        break
else:
    raise RuntimeError("Curaçao entry missing from wave JSON")
wave.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print("updated wave JSON Curaçao entry")
print("GATE years", GATE_YEARS)
print("GATE stems", GATE_STEMS)
print("n_gate", len(GATE_YEARS) + len(GATE_STEMS))
