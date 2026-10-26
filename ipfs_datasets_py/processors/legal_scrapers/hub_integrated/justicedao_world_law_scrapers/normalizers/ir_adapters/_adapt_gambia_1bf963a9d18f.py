#!/usr/bin/env python3
"""Adapt the Sierra Leone English memsafe FIRST_IR pack to Gambia GM.

English Gambia; FIRST_IR; HOLD 0 STRICT after-SL (GM→AG→CI→PR→ST→CV→SC→CF→YE→DJ).
Soft never-thin ON; SKIP_US; Italy BLOCKED. WAVE after_tj third country (after DM→SL LIVE),
NOT wave end. GATE: attested years + English legal stems from articles.parquet tip
1bf963a9d18f (English; include gambia). URL www/gov/gm query-only, NOT GATE.
Source tip 4e62de61f623 (Sierra Leone English).
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
SRC_TIP_FULL = "4e62de61f6238efeaf89d0527cdd262132584199"
SRC_TIP_SHORT = "4e62de61f623"
DST_TIP_FULL = "1bf963a9d18f3ad5e401e7d26e3b4ab37e1a08fa"
DST_TIP_SHORT = "1bf963a9d18f"
FLOOR_LAWS, FLOOR_ARTS = 94, 4517

# Sampled from data/articles.parquet @ 1bf963a9d18f (~10 years + ~11 stems; include gambia)
GATE_YEARS = ["2023", "2018", "2022", "2015", "2024", "2019", "2020", "2001", "2010", "2021"]
GATE_STEMS = [
    "gambia", "shall", "act", "section", "person",
    "court", "order", "minister", "offence", "subsection", "constitution",
]
GATE_NOTE_YEARS = "/".join(GATE_YEARS)
GATE_NOTE_STEMS = "/".join(GATE_STEMS)
HOLD = "HOLD 0 STRICT after-SL (GM→AG→CI→PR→ST→CV→SC→CF→YE→DJ)"
WAVE_POS = (
    "third country of after_tj wave "
    "(after DM→SL LIVE; GM→AG→CI→PR→ST→CV→SC→CF→YE→DJ; NOT wave end)"
)
DEST_CHAIN = "GM→AG→CI→PR→ST→CV→SC→CF→YE→DJ"
SRC_CHAIN = "SL→GM→AG→CI→PR→ST→CV→SC→CF→YE→DJ"

FILES = [
    ("sierraleone_soft_filter.py", "gambia_soft_filter.py"),
    (f"sierraleone_corpus_stream_{SRC_TIP_SHORT}.py", f"gambia_corpus_stream_{DST_TIP_SHORT}.py"),
    (f"sierraleone_encode_memsafe_{SRC_TIP_SHORT}.py", f"gambia_encode_memsafe_{DST_TIP_SHORT}.py"),
    (f"sierraleone_finish_from_emb_{SRC_TIP_SHORT}.py", f"gambia_finish_from_emb_{DST_TIP_SHORT}.py"),
    (f"sierraleone_stream_graph_parts_{SRC_TIP_SHORT}.py", f"gambia_stream_graph_parts_{DST_TIP_SHORT}.py"),
    (f"sierraleone_package_memsafe_{SRC_TIP_SHORT}.py", f"gambia_package_memsafe_{DST_TIP_SHORT}.py"),
    ("sierraleone_upload.py", "gambia_upload.py"),
    ("sierraleone_bm25_smoke.py", "gambia_bm25_smoke.py"),
    ("sierraleone_write_publish_report.py", "gambia_write_publish_report.py"),
    (f"sierraleone_orchestrator_{SRC_TIP_SHORT}.py", f"gambia_orchestrator_{DST_TIP_SHORT}.py"),
]


def adapt(text: str, dst_name: str) -> str:
    # Protect BM25 / bm25
    text = text.replace("BM25", "\x00BM25\x00").replace("bm25", "\x00bm25\x00")
    text = text.replace("bmjacency", "adjacency")

    # Protect SOURCE chain BEFORE dest (dest is suffix of source)
    text = text.replace(
        f"HOLD 0 STRICT after-DM ({SRC_CHAIN})",
        "\x00SRCHOLD\x00",
    )
    text = text.replace(f"after-DM ({SRC_CHAIN})", "\x00SRCAFTER\x00")
    text = text.replace(SRC_CHAIN, "\x00SRCCHAIN\x00")

    # Protect destination HOLD / wave tokens before ISO swaps
    text = text.replace(HOLD, "\x00DESTHOLD\x00")
    text = text.replace(DEST_CHAIN, "\x00DESTCHAIN\x00")
    text = text.replace("after-SL", "\x00AFTERSL\x00")
    text = text.replace("after SL ", "\x00AFTERSL_SP\x00")
    text = text.replace("after_tj", "\x00AFTERTJ_US\x00")
    text = text.replace(
        "second country of after_tj wave (\x00SRCCHAIN\x00; NOT wave end)",
        "\x00SRCPOS\x00",
    )
    text = text.replace(
        "second country of after_tj wave",
        "\x00SRCPOS\x00",
    )
    text = text.replace("after-DM", "\x00AFTERDM\x00")
    text = text.replace("after DM ", "\x00AFTERDM_SP\x00")

    reps = [
        (SRC_TIP_FULL, DST_TIP_FULL),
        (SRC_TIP_SHORT, DST_TIP_SHORT),
        ("endomorphosis/ipfs_sierraleone_laws", "endomorphosis/ipfs_gambia_laws"),
        ("justicedao/ipfs_sierraleone_laws_ir", "justicedao/ipfs_gambia_laws_ir"),
        ("ipfs_sierraleone_laws_ir", "ipfs_gambia_laws_ir"),
        ("ipfs_sierraleone_laws", "ipfs_gambia_laws"),
        # HOLD / wave BEFORE bare SL→GM
        ("\x00SRCHOLD\x00", HOLD),
        ("\x00SRCAFTER\x00", f"after-SL ({DEST_CHAIN})"),
        ("\x00SRCCHAIN\x00", DEST_CHAIN),
        ("\x00SRCPOS\x00", WAVE_POS),
        ("\x00AFTERDM\x00", "after-SL"),
        ("\x00AFTERDM_SP\x00", "after SL "),
        ("SL FIRST_IR (not wave end)", "GM FIRST_IR (not wave end)"),
        ("www/gov/sl", "www/gov/gm"),
        ("English (Sierra Leone)", "English (Gambia)"),
        ("English Sierra Leone", "English Gambia"),
        ("Sierra Leone", "Gambia"),
        # slug / path forms (sierraleone → gambia)
        ("sierraleone_ranked", "gambia_ranked"),
        ("sierraleone_gate", "gambia_gate"),
        ("sierraleone_pass", "gambia_pass"),
        ("sierraleone_encode_memsafe", "gambia_encode_memsafe"),
        ("sierraleone_package_memsafe", "gambia_package_memsafe"),
        ("sierraleone_corpus_stream", "gambia_corpus_stream"),
        ("sierraleone_encode_done", "gambia_encode_done"),
        ("sierraleone_", "gambia_"),
        ("sierraleone", "gambia"),
        # ISO whole-token / path forms only
        ('"SL"', '"GM"'),
        ("SL-attested", "GM-attested"),
        ("(SL)", "(GM)"),
        ('"sl"', '"gm"'),
        ("/sl", "/gm"),
        # floors 109/4587 → 94/4517
        ("109/4587", "94/4517"),
        ("109 / 4587", "94 / 4517"),
        ("109, 4587", "94, 4517"),
        ("FLOOR_LAWS, FLOOR_ARTS = 109, 4587", "FLOOR_LAWS, FLOOR_ARTS = 94, 4517"),
        ("or 109)", "or 94)"),
        ("or 109,", "or 94,"),
        ("or 109}", "or 94}"),
        ("= 109,", "= 94,"),
        ("= 109", "= 94"),
        ("@ 109/", "@ 94/"),
        (" 109/", " 94/"),
        ("floor 109/", "floor 94/"),
        ("(109/", "(94/"),
        (" or 109", " or 94"),
        (" 4587", " 4517"),
        ("4587", "4517"),
    ]
    for a, b in reps:
        text = text.replace(a, b)

    text = text.replace("\x00BM25\x00", "BM25").replace("\x00bm25\x00", "bm25")
    text = text.replace("\x00DESTHOLD\x00", HOLD)
    text = text.replace("\x00DESTCHAIN\x00", DEST_CHAIN)
    text = text.replace("\x00AFTERSL\x00", "after-SL")
    text = text.replace("\x00AFTERSL_SP\x00", "after SL ")
    text = text.replace("\x00AFTERTJ_US\x00", "after_tj")

    text = text.replace("FLOOR_LAWS, FLOOR_ARTS = 109, 4517", "FLOOR_LAWS, FLOOR_ARTS = 94, 4517")
    text = text.replace("FLOOR_LAWS, FLOOR_ARTS = 94, 4587", "FLOOR_LAWS, FLOOR_ARTS = 94, 4517")
    text = text.replace('int(pack.get("n_articles") or 4587)', 'int(pack.get("n_articles") or 4517)')
    text = text.replace('int(pack.get("n_articles") or 4517)', 'int(pack.get("n_articles") or 4517)')

    # display name fixes (slug vs title)
    text = text.replace('"name": "gambia"', '"name": "Gambia"')
    text = text.replace('"name": "Gambia"', '"name": "Gambia"')

    if dst_name == "gambia_bm25_smoke.py":
        start = text.index("GATE = [")
        end = text.index("]", start) + 1
        years_line = ", ".join(f'"{y}"' for y in GATE_YEARS)
        stems_line = ", ".join(f'"{s}"' for s in GATE_STEMS)
        gate = f"GATE = [\n    {years_line},\n    {stems_line},\n]"
        text = text[:start] + gate + text[end:]
        text = text.replace(
            'QUERIES = GATE + ["www", "gov", "sl"',
            'QUERIES = GATE + ["www", "gov", "gm"',
        )
        text = text.replace(
            'QUERIES = GATE + ["www", "gov", "gm"',
            'QUERIES = GATE + ["www", "gov", "gm"',
        )
        note = (
            f"attested years {GATE_NOTE_YEARS} plus English legal stems {GATE_NOTE_STEMS} "
            f"from articles.parquet HEAD tip {DST_TIP_SHORT}; URL www/gov/gm is query-only, not GATE."
        )
        text = re.sub(
            r"GATE = attested years [^;]+; URL www/gov/(?:sl|gm) is query-only, not GATE\.",
            f"GATE = {note}",
            text,
        )
        text = text.replace('"sierraleone_pass"', '"gambia_pass"')
        text = text.replace('"gambia_pass"', '"gambia_pass"')
        text = text.replace('"sierraleone_gate"', '"gambia_gate"')
        text = text.replace('"gambia_gate"', '"gambia_gate"')
        text = text.replace(
            "attested Sierra Leone years and English legal stems",
            "attested Gambia years and English legal stems",
        )
        text = text.replace(
            "attested Gambia years and English legal stems",
            "attested Gambia years and English legal stems",
        )
        # drop leftover sierra/leone GATE stems if any
        text = text.replace('"sierra"', '"gambia"')
        text = text.replace('"leone"', '"constitution"')

    if dst_name == "gambia_write_publish_report.py":
        new_gate = f"{GATE_NOTE_YEARS} + stems {GATE_NOTE_STEMS}"
        text = re.sub(
            r"attested years [0-9/]+ \+ stems [a-z_/]+",
            f"attested years {new_gate}",
            text,
        )
        text = text.replace("English GATE", "English (Gambia) GATE")
        text = text.replace(
            "ASCII-fold English (Gambia) GATE",
            "ASCII-fold English (Gambia) GATE",
        )
        text = re.sub(
            r"HOLD 0 STRICT after-DM[^;]*; collectors kept dead \(pkill\); soft never-thin ON; SKIP_US; Italy BLOCKED;[^\"\n]*",
            f"{HOLD}; collectors kept dead (pkill); soft never-thin ON; SKIP_US; Italy BLOCKED; {WAVE_POS}",
            text,
        )
        text = re.sub(
            r"HOLD 0 STRICT after-SL[^;]*; collectors kept dead \(pkill\); soft never-thin ON; SKIP_US; Italy BLOCKED;[^\"\n]*",
            f"{HOLD}; collectors kept dead (pkill); soft never-thin ON; SKIP_US; Italy BLOCKED; {WAVE_POS}",
            text,
        )
        text = text.replace("www/gov/sl is query-only", "www/gov/gm is query-only")
        text = text.replace("sierraleone/", "gambia/")

    leftovers = (
        "Sierra Leone", "sierraleone", "sierra", "leone",
        "Dominica", "dominica",
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
        "English (Sierra Leone", "English Sierra Leone",
        "English (Dominica", "English Dominica",
        "Tajikistan", "tajikistan",
    )
    found = [x for x in leftovers if x in text]
    if found:
        raise RuntimeError(f"language/country leftovers in {dst_name}: {found}")
    if dst_name.endswith("_bm25_smoke.py") and '", "sl"' in text:
        raise RuntimeError(f"leftover sl query token in {dst_name}")
    if dst_name.endswith("_bm25_smoke.py") and "www/gov/sl" in text:
        raise RuntimeError(f"leftover gov/sl in {dst_name}")
    # reject bare ISO leftovers that should have been swapped
    scrub = text
    scrub = scrub.replace(DEST_CHAIN, "XX")
    scrub = scrub.replace("after-SL", "after-XX")
    scrub = scrub.replace("after SL ", "after XX ")
    scrub = scrub.replace("after_tj", "after_xx")
    scrub = scrub.replace("after SL LIVE", "after XX LIVE")
    scrub = scrub.replace("DM→SL LIVE", "XX→XX LIVE")
    scrub = scrub.replace("after DM→SL LIVE", "after XX→XX LIVE")
    if '"SL"' in scrub or "(SL)" in scrub or "SL→" in scrub or "SL-attested" in scrub:
        tmp = scrub
        tmp = re.sub(r"after XX LIVE", "", tmp)
        tmp = re.sub(r"XX→XX LIVE", "", tmp)
        if re.search(r'(?<![A-Za-z])SL(?![A-Za-z])', tmp):
            raise RuntimeError(f"leftover SL tokens in {dst_name}: ...{tmp[max(0,tmp.find('SL')-20):tmp.find('SL')+20]}...")
    if "Sierra Leone" in text or "sierraleone" in text:
        raise RuntimeError(f"leftover Sierra Leone in {dst_name}")
    if "ipfs_sierraleone" in text:
        raise RuntimeError(f"leftover sierraleone path in {dst_name}")
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
    if entry.get("slug") == "gambia" or entry.get("iso2") == "GM":
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
                f"GM FIRST_IR scaffold; tip MATCH {DST_TIP_SHORT}@94/4517; {HOLD}; "
                f"soft never-thin ON; SKIP_US; Italy BLOCKED; {WAVE_POS}"
            ),
            "status": "CLAIMED",
        })
        break
else:
    raise RuntimeError("Gambia entry missing from wave JSON")
wave.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print("updated wave JSON Gambia entry")
print("GATE years", GATE_YEARS)
print("GATE stems", GATE_STEMS)
print("n_gate", len(GATE_YEARS) + len(GATE_STEMS))
print("GATE language: English")
print("HOLD", HOLD)
