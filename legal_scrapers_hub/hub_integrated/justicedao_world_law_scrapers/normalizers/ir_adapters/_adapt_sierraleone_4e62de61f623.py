#!/usr/bin/env python3
"""Adapt the Dominica English memsafe FIRST_IR pack to Sierra Leone SL.

English Sierra Leone; FIRST_IR; HOLD 0 STRICT after-DM (SL→GM→AG→CI→PR→ST→CV→SC→CF→YE→DJ).
Soft never-thin ON; SKIP_US; Italy BLOCKED. WAVE after_tj second country (after DM LIVE),
NOT wave end. GATE: attested years + English legal stems from articles.parquet tip
4e62de61f623 (English; include sierra/leone). URL www/gov/sl query-only, NOT GATE.
Source tip d071c156bb3c (Dominica English).
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
SRC_TIP_FULL = "d071c156bb3cd4da96927d7e17c5eb0a019ba0e3"
SRC_TIP_SHORT = "d071c156bb3c"
DST_TIP_FULL = "4e62de61f6238efeaf89d0527cdd262132584199"
DST_TIP_SHORT = "4e62de61f623"
FLOOR_LAWS, FLOOR_ARTS = 109, 4587

# Sampled from data/articles.parquet @ 4e62de61f623 (~10 years + ~11 stems; include sierra/leone)
GATE_YEARS = ["2000", "2007", "2004", "2017", "1964", "2012", "2019", "1953", "2011", "1962"]
GATE_STEMS = [
    "sierra", "leone", "shall", "act", "section", "person",
    "court", "order", "minister", "offence", "subsection",
]
GATE_NOTE_YEARS = "/".join(GATE_YEARS)
GATE_NOTE_STEMS = "/".join(GATE_STEMS)
HOLD = "HOLD 0 STRICT after-DM (SL→GM→AG→CI→PR→ST→CV→SC→CF→YE→DJ)"
WAVE_POS = (
    "second country of after_tj wave "
    "(after DM LIVE; SL→GM→AG→CI→PR→ST→CV→SC→CF→YE→DJ; NOT wave end)"
)
DEST_CHAIN = "SL→GM→AG→CI→PR→ST→CV→SC→CF→YE→DJ"
SRC_CHAIN = "DM→SL→GM→AG→CI→PR→ST→CV→SC→CF→YE→DJ"

FILES = [
    ("dominica_soft_filter.py", "sierraleone_soft_filter.py"),
    (f"dominica_corpus_stream_{SRC_TIP_SHORT}.py", f"sierraleone_corpus_stream_{DST_TIP_SHORT}.py"),
    (f"dominica_encode_memsafe_{SRC_TIP_SHORT}.py", f"sierraleone_encode_memsafe_{DST_TIP_SHORT}.py"),
    (f"dominica_finish_from_emb_{SRC_TIP_SHORT}.py", f"sierraleone_finish_from_emb_{DST_TIP_SHORT}.py"),
    (f"dominica_stream_graph_parts_{SRC_TIP_SHORT}.py", f"sierraleone_stream_graph_parts_{DST_TIP_SHORT}.py"),
    (f"dominica_package_memsafe_{SRC_TIP_SHORT}.py", f"sierraleone_package_memsafe_{DST_TIP_SHORT}.py"),
    ("dominica_upload.py", "sierraleone_upload.py"),
    ("dominica_bm25_smoke.py", "sierraleone_bm25_smoke.py"),
    ("dominica_write_publish_report.py", "sierraleone_write_publish_report.py"),
    (f"dominica_orchestrator_{SRC_TIP_SHORT}.py", f"sierraleone_orchestrator_{DST_TIP_SHORT}.py"),
]


def adapt(text: str, dst_name: str) -> str:
    # Protect BM25 / bm25
    text = text.replace("BM25", "\x00BM25\x00").replace("bm25", "\x00bm25\x00")
    text = text.replace("bmjacency", "adjacency")

    # Protect SOURCE chain BEFORE dest (dest is suffix of source)
    text = text.replace(
        f"HOLD 0 STRICT after-TJ ({SRC_CHAIN})",
        "\x00SRCHOLD\x00",
    )
    text = text.replace(f"after-TJ ({SRC_CHAIN})", "\x00SRCAFTER\x00")
    text = text.replace(SRC_CHAIN, "\x00SRCCHAIN\x00")

    # Protect destination HOLD / wave tokens before ISO swaps
    text = text.replace(HOLD, "\x00DESTHOLD\x00")
    text = text.replace(DEST_CHAIN, "\x00DESTCHAIN\x00")
    text = text.replace("after-DM", "\x00AFTERDM\x00")
    text = text.replace("after DM ", "\x00AFTERDM_SP\x00")
    text = text.replace("after_tj", "\x00AFTERTJ_US\x00")
    text = text.replace(
        "first country of after_tj wave (\x00SRCCHAIN\x00; NOT wave end)",
        "\x00SRCPOS\x00",
    )
    text = text.replace(
        "first country of after_tj wave",
        "\x00SRCPOS\x00",
    )
    text = text.replace("after-TJ", "\x00AFTERTJ\x00")
    text = text.replace("after TJ ", "\x00AFTERTJ_SP\x00")

    reps = [
        (SRC_TIP_FULL, DST_TIP_FULL),
        (SRC_TIP_SHORT, DST_TIP_SHORT),
        ("endomorphosis/ipfs_dominica_laws", "endomorphosis/ipfs_sierraleone_laws"),
        ("justicedao/ipfs_dominica_laws_ir", "justicedao/ipfs_sierraleone_laws_ir"),
        ("ipfs_dominica_laws_ir", "ipfs_sierraleone_laws_ir"),
        ("ipfs_dominica_laws", "ipfs_sierraleone_laws"),
        # HOLD / wave BEFORE bare DM→SL
        ("\x00SRCHOLD\x00", HOLD),
        ("\x00SRCAFTER\x00", f"after-DM ({DEST_CHAIN})"),
        ("\x00SRCCHAIN\x00", DEST_CHAIN),
        ("\x00SRCPOS\x00", WAVE_POS),
        ("\x00AFTERTJ\x00", "after-DM"),
        ("\x00AFTERTJ_SP\x00", "after DM "),
        ("DM FIRST_IR (not wave end)", "SL FIRST_IR (not wave end)"),
        ("www/gov/dm", "www/gov/sl"),
        ("English (Dominica)", "English (Sierra Leone)"),
        ("English Dominica", "English Sierra Leone"),
        ("Dominica", "Sierra Leone"),
        # slug / path forms (sierraleone, no underscore)
        ("dominica_ranked", "sierraleone_ranked"),
        ("dominica_gate", "sierraleone_gate"),
        ("dominica_pass", "sierraleone_pass"),
        ("dominica_encode_memsafe", "sierraleone_encode_memsafe"),
        ("dominica_package_memsafe", "sierraleone_package_memsafe"),
        ("dominica_corpus_stream", "sierraleone_corpus_stream"),
        ("dominica_encode_done", "sierraleone_encode_done"),
        ("dominica_", "sierraleone_"),
        ("dominica", "sierraleone"),
        # ISO whole-token / path forms only
        ('"DM"', '"SL"'),
        ("DM-attested", "SL-attested"),
        ("(DM)", "(SL)"),
        ('"dm"', '"sl"'),
        ("/dm", "/sl"),
        # floors 156/4690 → 109/4587
        ("156/4690", "109/4587"),
        ("156 / 4690", "109 / 4587"),
        ("156, 4690", "109, 4587"),
        ("FLOOR_LAWS, FLOOR_ARTS = 156, 4690", "FLOOR_LAWS, FLOOR_ARTS = 109, 4587"),
        ("or 156)", "or 109)"),
        ("or 156,", "or 109,"),
        ("or 156}", "or 109}"),
        ("= 156,", "= 109,"),
        ("= 156", "= 109"),
        ("@ 156/", "@ 109/"),
        (" 156/", " 109/"),
        ("floor 156/", "floor 109/"),
        ("(156/", "(109/"),
        (" or 156", " or 109"),
        (" 4690", " 4587"),
        ("4690", "4587"),
    ]
    for a, b in reps:
        text = text.replace(a, b)

    text = text.replace("\x00BM25\x00", "BM25").replace("\x00bm25\x00", "bm25")
    text = text.replace("\x00DESTHOLD\x00", HOLD)
    text = text.replace("\x00DESTCHAIN\x00", DEST_CHAIN)
    text = text.replace("\x00AFTERDM\x00", "after-DM")
    text = text.replace("\x00AFTERDM_SP\x00", "after DM ")
    text = text.replace("\x00AFTERTJ_US\x00", "after_tj")

    text = text.replace("FLOOR_LAWS, FLOOR_ARTS = 156, 4587", "FLOOR_LAWS, FLOOR_ARTS = 109, 4587")
    text = text.replace("FLOOR_LAWS, FLOOR_ARTS = 109, 4690", "FLOOR_LAWS, FLOOR_ARTS = 109, 4587")
    text = text.replace('int(pack.get("n_articles") or 4690)', 'int(pack.get("n_articles") or 4587)')
    text = text.replace('int(pack.get("n_articles") or 4587)', 'int(pack.get("n_articles") or 4587)')

    # display name fixes (slug vs title)
    text = text.replace('"name": "sierraleone"', '"name": "Sierra Leone"')
    text = text.replace('"name": "Sierra Leone"', '"name": "Sierra Leone"')

    if dst_name == "sierraleone_bm25_smoke.py":
        start = text.index("GATE = [")
        end = text.index("]", start) + 1
        years_line = ", ".join(f'"{y}"' for y in GATE_YEARS)
        stems_line = ", ".join(f'"{s}"' for s in GATE_STEMS)
        gate = f"GATE = [\n    {years_line},\n    {stems_line},\n]"
        text = text[:start] + gate + text[end:]
        text = text.replace(
            'QUERIES = GATE + ["www", "gov", "dm"',
            'QUERIES = GATE + ["www", "gov", "sl"',
        )
        text = text.replace(
            'QUERIES = GATE + ["www", "gov", "sl"',
            'QUERIES = GATE + ["www", "gov", "sl"',
        )
        note = (
            f"attested years {GATE_NOTE_YEARS} plus English legal stems {GATE_NOTE_STEMS} "
            f"from articles.parquet HEAD tip {DST_TIP_SHORT}; URL www/gov/sl is query-only, not GATE."
        )
        text = re.sub(
            r"GATE = attested years [^;]+; URL www/gov/(?:dm|sl) is query-only, not GATE\.",
            f"GATE = {note}",
            text,
        )
        text = text.replace('"dominica_pass"', '"sierraleone_pass"')
        text = text.replace('"sierraleone_pass"', '"sierraleone_pass"')
        text = text.replace('"dominica_gate"', '"sierraleone_gate"')
        text = text.replace('"sierraleone_gate"', '"sierraleone_gate"')
        text = text.replace(
            "attested Dominica years and English legal stems",
            "attested Sierra Leone years and English legal stems",
        )
        text = text.replace(
            "attested Sierra Leone years and English legal stems",
            "attested Sierra Leone years and English legal stems",
        )
        # drop leftover dominica GATE stem if any
        text = text.replace('"dominica"', '"sierra"')

    if dst_name == "sierraleone_write_publish_report.py":
        new_gate = f"{GATE_NOTE_YEARS} + stems {GATE_NOTE_STEMS}"
        text = re.sub(
            r"attested years [0-9/]+ \+ stems [a-z_/]+",
            f"attested years {new_gate}",
            text,
        )
        text = text.replace("English GATE", "English (Sierra Leone) GATE")
        text = text.replace(
            "ASCII-fold English (Sierra Leone) GATE",
            "ASCII-fold English (Sierra Leone) GATE",
        )
        text = re.sub(
            r"HOLD 0 STRICT after-TJ[^;]*; collectors kept dead \(pkill\); soft never-thin ON; SKIP_US; Italy BLOCKED;[^\"\n]*",
            f"{HOLD}; collectors kept dead (pkill); soft never-thin ON; SKIP_US; Italy BLOCKED; {WAVE_POS}",
            text,
        )
        text = re.sub(
            r"HOLD 0 STRICT after-DM[^;]*; collectors kept dead \(pkill\); soft never-thin ON; SKIP_US; Italy BLOCKED;[^\"\n]*",
            f"{HOLD}; collectors kept dead (pkill); soft never-thin ON; SKIP_US; Italy BLOCKED; {WAVE_POS}",
            text,
        )
        text = text.replace("www/gov/dm is query-only", "www/gov/sl is query-only")
        text = text.replace("dominica/", "sierraleone/")

    leftovers = (
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
        "English (Dominica", "English Dominica",
        "English (Saint Lucia", "English Saint Lucia",
        "Tajikistan", "tajikistan",
    )
    found = [x for x in leftovers if x in text]
    if found:
        raise RuntimeError(f"language/country leftovers in {dst_name}: {found}")
    if dst_name.endswith("_bm25_smoke.py") and '", "dm"' in text:
        raise RuntimeError(f"leftover dm query token in {dst_name}")
    if dst_name.endswith("_bm25_smoke.py") and "www/gov/dm" in text:
        raise RuntimeError(f"leftover gov/dm in {dst_name}")
    # reject bare ISO leftovers that should have been swapped
    scrub = text
    scrub = scrub.replace(DEST_CHAIN, "XX")
    scrub = scrub.replace("after-DM", "after-XX")
    scrub = scrub.replace("after DM ", "after XX ")
    scrub = scrub.replace("after_tj", "after_xx")
    scrub = scrub.replace("after DM LIVE", "after XX LIVE")
    # WAVE_POS embeds "after DM LIVE" — already protected via after DM
    if '"DM"' in scrub or "(DM)" in scrub or "DM→" in scrub or "DM-attested" in scrub:
        # allow "after DM LIVE" already replaced; check remaining
        if re.search(r'(?<![A-Za-z])DM(?![A-Za-z])', scrub.replace("after XX LIVE", "")):
            # still have bare DM?
            tmp = scrub
            tmp = re.sub(r"after XX LIVE", "", tmp)
            if re.search(r'(?<![A-Za-z])DM(?![A-Za-z])', tmp):
                raise RuntimeError(f"leftover DM tokens in {dst_name}: ...{tmp[max(0,tmp.find('DM')-20):tmp.find('DM')+20]}...")
    if "Dominica" in text or "dominica" in text:
        raise RuntimeError(f"leftover Dominica in {dst_name}")
    if "ipfs_dominica" in text:
        raise RuntimeError(f"leftover dominica path in {dst_name}")
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
    if entry.get("slug") == "sierraleone" or entry.get("iso2") == "SL":
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
                f"SL FIRST_IR scaffold; tip MATCH {DST_TIP_SHORT}@109/4587; {HOLD}; "
                f"soft never-thin ON; SKIP_US; Italy BLOCKED; {WAVE_POS}"
            ),
            "status": "CLAIMED",
        })
        break
else:
    raise RuntimeError("Sierra Leone entry missing from wave JSON")
wave.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print("updated wave JSON Sierra Leone entry")
print("GATE years", GATE_YEARS)
print("GATE stems", GATE_STEMS)
print("n_gate", len(GATE_YEARS) + len(GATE_STEMS))
print("GATE language: English")
print("HOLD", HOLD)
