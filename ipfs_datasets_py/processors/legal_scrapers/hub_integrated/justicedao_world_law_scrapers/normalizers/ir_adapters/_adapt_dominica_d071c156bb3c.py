#!/usr/bin/env python3
"""Adapt the Saint Lucia English memsafe FIRST_IR pack to Dominica DM.

English Dominica; FIRST_IR; HOLD 0 STRICT after-TJ (DM→SL→GM→AG→CI→PR→ST→CV→SC→CF→YE→DJ).
Soft never-thin ON; SKIP_US; Italy BLOCKED. WAVE after_tj first country (DM this),
NOT wave end. GATE: attested years + English legal stems from articles.parquet tip
d071c156bb3c (English; include dominica). URL www/gov/dm query-only, NOT GATE.
Source tip 2216d124ae85 (Saint Lucia English).
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
DST_TIP_FULL = "d071c156bb3cd4da96927d7e17c5eb0a019ba0e3"
DST_TIP_SHORT = "d071c156bb3c"
FLOOR_LAWS, FLOOR_ARTS = 156, 4690

# Sampled from data/articles.parquet @ d071c156bb3c (~10 years + ~11 stems; include dominica)
GATE_YEARS = ["1991", "1990", "1978", "1961", "1967", "2014", "1986", "1995", "1983", "1982"]
GATE_STEMS = [
    "dominica", "shall", "act", "section", "person", "court",
    "order", "minister", "offence", "subsection", "schedule",
]
GATE_NOTE_YEARS = "/".join(GATE_YEARS)
GATE_NOTE_STEMS = "/".join(GATE_STEMS)
HOLD = "HOLD 0 STRICT after-TJ (DM→SL→GM→AG→CI→PR→ST→CV→SC→CF→YE→DJ)"
WAVE_POS = "first country of after_tj wave (DM→SL→GM→AG→CI→PR→ST→CV→SC→CF→YE→DJ; NOT wave end)"

FILES = [
    ("saint_lucia_soft_filter.py", "dominica_soft_filter.py"),
    (f"saint_lucia_corpus_stream_{SRC_TIP_SHORT}.py", f"dominica_corpus_stream_{DST_TIP_SHORT}.py"),
    (f"saint_lucia_encode_memsafe_{SRC_TIP_SHORT}.py", f"dominica_encode_memsafe_{DST_TIP_SHORT}.py"),
    (f"saint_lucia_finish_from_emb_{SRC_TIP_SHORT}.py", f"dominica_finish_from_emb_{DST_TIP_SHORT}.py"),
    (f"saint_lucia_stream_graph_parts_{SRC_TIP_SHORT}.py", f"dominica_stream_graph_parts_{DST_TIP_SHORT}.py"),
    (f"saint_lucia_package_memsafe_{SRC_TIP_SHORT}.py", f"dominica_package_memsafe_{DST_TIP_SHORT}.py"),
    ("saint_lucia_upload.py", "dominica_upload.py"),
    ("saint_lucia_bm25_smoke.py", "dominica_bm25_smoke.py"),
    ("saint_lucia_write_publish_report.py", "dominica_write_publish_report.py"),
    (f"saint_lucia_orchestrator_{SRC_TIP_SHORT}.py", f"dominica_orchestrator_{DST_TIP_SHORT}.py"),
]


def adapt(text: str, dst_name: str) -> str:
    # Protect BM25 / bm25
    text = text.replace("BM25", "\x00BM25\x00").replace("bm25", "\x00bm25\x00")
    text = text.replace("bmjacency", "adjacency")

    # Protect destination HOLD chain / wave tokens before ISO swaps
    text = text.replace(HOLD, "\x00DESTHOLD\x00")
    text = text.replace("DM→SL→GM→AG→CI→PR→ST→CV→SC→CF→YE→DJ", "\x00DESTCHAIN\x00")
    text = text.replace("after-TJ", "\x00AFTERTJ\x00")
    text = text.replace("after TJ ", "\x00AFTERTJ_SP\x00")
    text = text.replace("after_tj", "\x00AFTERTJ_US\x00")

    # Protect source HOLD / wave mentions that must rewrite
    text = text.replace("HOLD 0 STRICT after-MU (LC→TJ WAVE END)", "\x00SRCHOLD\x00")
    text = text.replace("after-MU (LC→TJ WAVE END)", "\x00SRCAFTER\x00")
    text = text.replace("LC→TJ WAVE END", "\x00SRCCHAIN\x00")
    text = text.replace("LC→TJ", "\x00SRCCHAIN_SHORT\x00")
    text = text.replace("MU→LC→TJ", "\x00SRCMID\x00")
    text = text.replace("CW→MU→LC→TJ", "\x00SRCLONG\x00")
    text = text.replace("TV→LR→SY→TO→BS→LS→BZ→SB→CW→MU", "\x00WAVECHAIN11\x00")
    text = text.replace("TV→LR→SY→TO→BS→LS→BZ→SB→CW", "\x00WAVECHAIN10\x00")
    text = text.replace("eleventh country of after_bm wave (after \x00WAVECHAIN11\x00 LIVE)", "\x00SRCPOS\x00")
    text = text.replace("eleventh country of after_bm wave", "\x00SRCPOS\x00")
    text = text.replace("eleventh of after_bm wave (after \x00WAVECHAIN11\x00 LIVE)", "\x00SRCPOS_SHORT\x00")
    text = text.replace("eleventh of after_bm wave", "\x00SRCPOS_SHORT\x00")

    reps = [
        (SRC_TIP_FULL, DST_TIP_FULL),
        (SRC_TIP_SHORT, DST_TIP_SHORT),
        ("endomorphosis/ipfs_saint_lucia_laws", "endomorphosis/ipfs_dominica_laws"),
        ("justicedao/ipfs_saint_lucia_laws_ir", "justicedao/ipfs_dominica_laws_ir"),
        ("ipfs_saint_lucia_laws_ir", "ipfs_dominica_laws_ir"),
        ("ipfs_saint_lucia_laws", "ipfs_dominica_laws"),
        # HOLD / wave BEFORE bare LC→DM
        ("\x00SRCHOLD\x00", HOLD),
        ("\x00SRCAFTER\x00", "after-TJ (DM→SL→GM→AG→CI→PR→ST→CV→SC→CF→YE→DJ)"),
        ("\x00SRCCHAIN\x00", "DM→SL→GM→AG→CI→PR→ST→CV→SC→CF→YE→DJ"),
        ("\x00SRCCHAIN_SHORT\x00", "DM→SL→GM→AG→CI→PR→ST→CV→SC→CF→YE→DJ"),
        ("\x00SRCMID\x00", "DM→SL→GM→AG→CI→PR→ST→CV→SC→CF→YE→DJ"),
        ("\x00SRCLONG\x00", "DM→SL→GM→AG→CI→PR→ST→CV→SC→CF→YE→DJ"),
        ("\x00SRCPOS\x00", WAVE_POS),
        ("\x00SRCPOS_SHORT\x00", WAVE_POS),
        ("LC FIRST_IR (not wave end)", "DM FIRST_IR (not wave end)"),
        ("www/gov/lc", "www/gov/dm"),
        ("English (Saint Lucia)", "English (Dominica)"),
        ("English Saint Lucia", "English Dominica"),
        ("Saint Lucia", "Dominica"),
        # slug / path forms
        ("saint_lucia_ranked", "dominica_ranked"),
        ("saint_lucia_gate", "dominica_gate"),
        ("saint_lucia_pass", "dominica_pass"),
        ("saint_lucia_encode_memsafe", "dominica_encode_memsafe"),
        ("saint_lucia_package_memsafe", "dominica_package_memsafe"),
        ("saint_lucia_corpus_stream", "dominica_corpus_stream"),
        ("saint_lucia_encode_done", "dominica_encode_done"),
        ("saint_lucia_", "dominica_"),
        ("saint_lucia", "dominica"),
        # ISO whole-token / path forms only
        ('"LC"', '"DM"'),
        ("LC-attested", "DM-attested"),
        ("(LC)", "(DM)"),
        ('"lc"', '"dm"'),
        ("/lc", "/dm"),
        # floors 150/5078 → 156/4690
        ("150/5078", "156/4690"),
        ("150 / 5078", "156 / 4690"),
        ("150, 5078", "156, 4690"),
        ("FLOOR_LAWS, FLOOR_ARTS = 150, 5078", "FLOOR_LAWS, FLOOR_ARTS = 156, 4690"),
        ("or 150)", "or 156)"),
        ("or 150,", "or 156,"),
        ("or 150}", "or 156}"),
        ("= 150,", "= 156,"),
        ("= 150", "= 156"),
        ("@ 150/", "@ 156/"),
        (" 150/", " 156/"),
        ("floor 150/", "floor 156/"),
        ("(150/", "(156/"),
        (" or 150", " or 156"),
        (" 5078", " 4690"),
        ("5078", "4690"),
    ]
    # Fix accidental bad tuple above by filtering only valid 2-tuples of strings
    clean_reps = []
    for item in reps:
        if isinstance(item, tuple) and len(item) == 2 and isinstance(item[0], str) and isinstance(item[1], str):
            clean_reps.append(item)
    for a, b in clean_reps:
        text = text.replace(a, b)

    text = text.replace("\x00BM25\x00", "BM25").replace("\x00bm25\x00", "bm25")
    text = text.replace("\x00DESTHOLD\x00", HOLD)
    text = text.replace("\x00DESTCHAIN\x00", "DM→SL→GM→AG→CI→PR→ST→CV→SC→CF→YE→DJ")
    text = text.replace("\x00AFTERTJ\x00", "after-TJ")
    text = text.replace("\x00AFTERTJ_SP\x00", "after TJ ")
    text = text.replace("\x00AFTERTJ_US\x00", "after_tj")
    text = text.replace("\x00WAVECHAIN11\x00", "TV→LR→SY→TO→BS→LS→BZ→SB→CW→MU")
    text = text.replace("\x00WAVECHAIN10\x00", "TV→LR→SY→TO→BS→LS→BZ→SB→CW")

    text = text.replace("FLOOR_LAWS, FLOOR_ARTS = 150, 4690", "FLOOR_LAWS, FLOOR_ARTS = 156, 4690")
    text = text.replace("FLOOR_LAWS, FLOOR_ARTS = 156, 5078", "FLOOR_LAWS, FLOOR_ARTS = 156, 4690")
    text = text.replace('int(pack.get("n_articles") or 5078)', 'int(pack.get("n_articles") or 4690)')
    text = text.replace('int(pack.get("n_articles") or 4690)', 'int(pack.get("n_articles") or 4690)')

    text = text.replace('"name": "Dominica"', '"name": "Dominica"')
    text = text.replace('"name": "dominica"', '"name": "Dominica"')

    if dst_name == "dominica_bm25_smoke.py":
        start = text.index("GATE = [")
        end = text.index("]", start) + 1
        years_line = ", ".join(f'"{y}"' for y in GATE_YEARS)
        stems_line = ", ".join(f'"{s}"' for s in GATE_STEMS)
        gate = f"GATE = [\n    {years_line},\n    {stems_line},\n]"
        text = text[:start] + gate + text[end:]
        text = text.replace(
            'QUERIES = GATE + ["www", "gov", "lc"',
            'QUERIES = GATE + ["www", "gov", "dm"',
        )
        text = text.replace(
            'QUERIES = GATE + ["www", "gov", "dm"',
            'QUERIES = GATE + ["www", "gov", "dm"',
        )
        note = (
            f"attested years {GATE_NOTE_YEARS} plus English legal stems {GATE_NOTE_STEMS} "
            f"from articles.parquet HEAD tip {DST_TIP_SHORT}; URL www/gov/dm is query-only, not GATE."
        )
        text = re.sub(
            r"GATE = attested years [^;]+; URL www/gov/(?:lc|dm) is query-only, not GATE\.",
            f"GATE = {note}",
            text,
        )
        text = text.replace('"saint_lucia_pass"', '"dominica_pass"')
        text = text.replace('"dominica_pass"', '"dominica_pass"')
        text = text.replace('"saint_lucia_gate"', '"dominica_gate"')
        text = text.replace('"dominica_gate"', '"dominica_gate"')
        text = text.replace(
            "attested Saint Lucia years and English legal stems",
            "attested Dominica years and English legal stems",
        )
        text = text.replace(
            "attested Dominica years and English legal stems",
            "attested Dominica years and English legal stems",
        )
        # drop leftover lucia GATE stem if any
        text = text.replace('"lucia"', '"dominica"')

    if dst_name == "dominica_write_publish_report.py":
        new_gate = f"{GATE_NOTE_YEARS} + stems {GATE_NOTE_STEMS}"
        text = re.sub(
            r"attested years [0-9/]+ \+ stems [a-z_/]+",
            f"attested years {new_gate}",
            text,
        )
        text = text.replace("English GATE", "English (Dominica) GATE")
        text = text.replace(
            "ASCII-fold English (Dominica) GATE",
            "ASCII-fold English (Dominica) GATE",
        )
        text = re.sub(
            r"HOLD 0 STRICT after-MU[^;]*; collectors kept dead \(pkill\); soft never-thin ON; SKIP_US; Italy BLOCKED;[^\"\n]*",
            f"{HOLD}; collectors kept dead (pkill); soft never-thin ON; SKIP_US; Italy BLOCKED; {WAVE_POS}",
            text,
        )
        text = re.sub(
            r"HOLD 0 STRICT after-TJ[^;]*; collectors kept dead \(pkill\); soft never-thin ON; SKIP_US; Italy BLOCKED;[^\"\n]*",
            f"{HOLD}; collectors kept dead (pkill); soft never-thin ON; SKIP_US; Italy BLOCKED; {WAVE_POS}",
            text,
        )
        text = text.replace("www/gov/lc is query-only", "www/gov/dm is query-only")
        text = text.replace("lucia/", "dominica/")

    leftovers = (
        "Saint Lucia", "saint_lucia", "lucia",
        "Mauritius", "mauritius",
        "Curaçao", "Curacao", "curacao", "Dutch",
        "Solomon Islands", "solomonislands",
        "Belize", "belize", "Lesotho", "lesotho",
        "Haiti", "Nauru", "Montserrat", "Bermuda", "bermuda",
        "British Virgin Islands", "Gabon", "Togo", "Anguilla", "Cook Islands",
        "Tuvalu", "tuvalu", "Liberia", "liberia", "Syria", "syria", "Arabic",
        "arabic", "Tonga", "tonga", "Bahamas", "bahamas",
        "bmjacency", "msjacency",
        "English (Saint Lucia", "English Saint Lucia",
        "English (Mauritius", "English Mauritius",
        "Tajikistan", "tajikistan",
    )
    # Allow 'lucia' only if somehow in protected words — reject always for DM
    found = [x for x in leftovers if x in text]
    # 'lucia' as substring of nothing expected; but 'dominica' does not contain lucia
    if found:
        raise RuntimeError(f"language/country leftovers in {dst_name}: {found}")
    if dst_name.endswith("_bm25_smoke.py") and '", "lc"' in text:
        raise RuntimeError(f"leftover lc query token in {dst_name}")
    if dst_name.endswith("_bm25_smoke.py") and "www/gov/lc" in text:
        raise RuntimeError(f"leftover gov/lc in {dst_name}")
    # reject bare ISO leftovers that should have been swapped
    scrub = text
    scrub = scrub.replace("DM→SL→GM→AG→CI→PR→ST→CV→SC→CF→YE→DJ", "XX")
    scrub = scrub.replace("after-TJ", "after-XX")
    scrub = scrub.replace("after TJ ", "after XX ")
    scrub = scrub.replace("after_tj", "after_xx")
    scrub = scrub.replace("TV→LR→SY→TO→BS→LS→BZ→SB→CW→MU", "XX")
    scrub = scrub.replace("TV→LR→SY→TO→BS→LS→BZ→SB→CW", "XX")
    if '"LC"' in scrub or "(LC)" in scrub or "LC→" in scrub or "LC-attested" in scrub:
        raise RuntimeError(f"leftover LC tokens in {dst_name}")
    if "Saint Lucia" in text or "saint_lucia" in text:
        raise RuntimeError(f"leftover Saint Lucia in {dst_name}")
    if "ipfs_saint_lucia" in text:
        raise RuntimeError(f"leftover saint_lucia path in {dst_name}")
    if "Mauritius" in text or "mauritius" in text:
        raise RuntimeError(f"leftover Mauritius in {dst_name}")
    if "lucia" in text.lower() and "dominica" not in text.lower()[max(0, text.lower().find("lucia")-5):text.lower().find("lucia")+15]:
        # bare lucia leftover
        if re.search(r"(?<![a-z])lucia(?![a-z])", text.lower()):
            raise RuntimeError(f"leftover lucia stem/token in {dst_name}")
    return text


for src_name, dst_name in FILES:
    src = ROOT / src_name
    if not src.is_file():
        raise FileNotFoundError(src)
    (ROOT / dst_name).write_text(adapt(src.read_text(encoding="utf-8"), dst_name), encoding="utf-8")
    print(f"wrote {dst_name}")

wave = Path("/workspace/country-law-triage/next_ir_ok_wave_after_tj.json")
data = json.loads(wave.read_text(encoding="utf-8"))
for entry in data["queue"]:
    if entry.get("slug") == "dominica" or entry.get("iso2") == "DM":
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
                f"DM FIRST_IR scaffold; tip MATCH {DST_TIP_SHORT}@156/4690; {HOLD}; "
                f"soft never-thin ON; SKIP_US; Italy BLOCKED; {WAVE_POS}"
            ),
            "status": "CLAIMED",
        })
        break
else:
    raise RuntimeError("Dominica entry missing from wave JSON")
wave.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print("updated wave JSON Dominica entry")
print("GATE years", GATE_YEARS)
print("GATE stems", GATE_STEMS)
print("n_gate", len(GATE_YEARS) + len(GATE_STEMS))
print("GATE language: English")
print("HOLD", HOLD)
