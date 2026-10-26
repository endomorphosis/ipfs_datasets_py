#!/usr/bin/env python3
"""Adapt the Gambia English memsafe FIRST_IR pack to Antigua and Barbuda AG.

English Antigua and Barbuda; FIRST_IR; HOLD 0 STRICT after-GM (AG→CI→PR→ST→CV→SC→CF→YE→DJ).
Soft never-thin ON; SKIP_US; Italy BLOCKED. WAVE after_tj fourth country (after DM→SL→GM LIVE),
NOT wave end. GATE: attested years + English legal stems from articles.parquet tip
85734f06153d (English; include antigua). URL www/gov/ag query-only, NOT GATE.
Source tip 1bf963a9d18f (Gambia English).
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
SRC_TIP_FULL = "1bf963a9d18f3ad5e401e7d26e3b4ab37e1a08fa"
SRC_TIP_SHORT = "1bf963a9d18f"
DST_TIP_FULL = "85734f06153d45a6f2ceb9e69bd5c4d7b50de23a"
DST_TIP_SHORT = "85734f06153d"
FLOOR_LAWS, FLOOR_ARTS = 150, 4387

# Sampled from data/articles.parquet @ 85734f06153d (~10 years + ~11 stems; include antigua)
GATE_YEARS = ["1981", "1967", "2016", "1979", "2025", "2018", "1958", "1959", "1975", "1986"]
GATE_STEMS = [
    "antigua", "shall", "act", "section", "person",
    "court", "order", "minister", "offence", "subsection", "constitution",
]
GATE_NOTE_YEARS = "/".join(GATE_YEARS)
GATE_NOTE_STEMS = "/".join(GATE_STEMS)
HOLD = "HOLD 0 STRICT after-GM (AG→CI→PR→ST→CV→SC→CF→YE→DJ)"
WAVE_POS = (
    "fourth country of after_tj wave "
    "(after DM→SL→GM LIVE; AG→CI→PR→ST→CV→SC→CF→YE→DJ; NOT wave end)"
)
DEST_CHAIN = "AG→CI→PR→ST→CV→SC→CF→YE→DJ"
SRC_CHAIN = "GM→AG→CI→PR→ST→CV→SC→CF→YE→DJ"
SRC_HOLD = "HOLD 0 STRICT after-SL (GM→AG→CI→PR→ST→CV→SC→CF→YE→DJ)"
SRC_WAVE = (
    "third country of after_tj wave "
    "(after DM→SL LIVE; GM→AG→CI→PR→ST→CV→SC→CF→YE→DJ; NOT wave end)"
)

FILES = [
    ("gambia_soft_filter.py", "antigua_barbuda_soft_filter.py"),
    (f"gambia_corpus_stream_{SRC_TIP_SHORT}.py", f"antigua_barbuda_corpus_stream_{DST_TIP_SHORT}.py"),
    (f"gambia_encode_memsafe_{SRC_TIP_SHORT}.py", f"antigua_barbuda_encode_memsafe_{DST_TIP_SHORT}.py"),
    (f"gambia_finish_from_emb_{SRC_TIP_SHORT}.py", f"antigua_barbuda_finish_from_emb_{DST_TIP_SHORT}.py"),
    (f"gambia_stream_graph_parts_{SRC_TIP_SHORT}.py", f"antigua_barbuda_stream_graph_parts_{DST_TIP_SHORT}.py"),
    (f"gambia_package_memsafe_{SRC_TIP_SHORT}.py", f"antigua_barbuda_package_memsafe_{DST_TIP_SHORT}.py"),
    ("gambia_upload.py", "antigua_barbuda_upload.py"),
    ("gambia_bm25_smoke.py", "antigua_barbuda_bm25_smoke.py"),
    ("gambia_write_publish_report.py", "antigua_barbuda_write_publish_report.py"),
    (f"gambia_orchestrator_{SRC_TIP_SHORT}.py", f"antigua_barbuda_orchestrator_{DST_TIP_SHORT}.py"),
]


def adapt(text: str, dst_name: str) -> str:
    # Protect BM25 / bm25
    text = text.replace("BM25", "\x00BM25\x00").replace("bm25", "\x00bm25\x00")
    text = text.replace("bmjacency", "adjacency")

    # Protect / rewrite HOLD + wave BEFORE ISO/slug swaps (AG appears in SRC_CHAIN)
    text = text.replace(SRC_HOLD, "\x00DESTHOLD\x00")
    text = text.replace(SRC_WAVE, "\x00DESTWAVE\x00")
    text = text.replace(SRC_CHAIN, "\x00DESTCHAIN\x00")
    text = text.replace(HOLD, "\x00DESTHOLD\x00")
    text = text.replace(DEST_CHAIN, "\x00DESTCHAIN\x00")
    text = text.replace(WAVE_POS, "\x00DESTWAVE\x00")
    # remaining after-SL / after SL / third-country fragments
    text = text.replace("after-SL", "\x00AFTERGM\x00")
    text = text.replace("after SL ", "\x00AFTERGM_SP\x00")
    text = text.replace("after_tj", "\x00AFTERTJ_US\x00")
    text = text.replace("DM→SL LIVE", "\x00DMSLGM\x00")
    text = text.replace("third country of \x00AFTERTJ_US\x00 wave", "\x00DESTWAVE_SHORT\x00")
    text = text.replace("third country of after_tj wave", "\x00DESTWAVE_SHORT\x00")

    reps = [
        (SRC_TIP_FULL, DST_TIP_FULL),
        (SRC_TIP_SHORT, DST_TIP_SHORT),
        ("endomorphosis/ipfs_gambia_laws", "endomorphosis/ipfs_antigua_barbuda_laws"),
        ("justicedao/ipfs_gambia_laws_ir", "justicedao/ipfs_antigua_barbuda_laws_ir"),
        ("ipfs_gambia_laws_ir", "ipfs_antigua_barbuda_laws_ir"),
        ("ipfs_gambia_laws", "ipfs_antigua_barbuda_laws"),
        # HOLD / wave restore tokens mapped to dest
        ("\x00DESTHOLD\x00", HOLD),
        ("\x00DESTWAVE\x00", WAVE_POS),
        ("\x00DESTWAVE_SHORT\x00", WAVE_POS),
        ("\x00DESTCHAIN\x00", DEST_CHAIN),
        ("\x00AFTERGM\x00", "after-GM"),
        ("\x00AFTERGM_SP\x00", "after GM "),
        ("\x00DMSLGM\x00", "DM→SL→GM LIVE"),
        ("GM FIRST_IR (not wave end)", "AG FIRST_IR (not wave end)"),
        ("www/gov/gm", "www/gov/ag"),
        ("English (Gambia)", "English (Antigua and Barbuda)"),
        ("English Gambia", "English Antigua and Barbuda"),
        ("Gambia", "Antigua and Barbuda"),
        # slug / path forms (underscore)
        ("gambia_ranked", "antigua_barbuda_ranked"),
        ("gambia_gate", "antigua_barbuda_gate"),
        ("gambia_pass", "antigua_barbuda_pass"),
        ("gambia_encode_memsafe", "antigua_barbuda_encode_memsafe"),
        ("gambia_package_memsafe", "antigua_barbuda_package_memsafe"),
        ("gambia_corpus_stream", "antigua_barbuda_corpus_stream"),
        ("gambia_encode_done", "antigua_barbuda_encode_done"),
        ("gambia_", "antigua_barbuda_"),
        ("gambia", "antigua_barbuda"),
        # ISO whole-token / path forms only
        ('"GM"', '"AG"'),
        ("GM-attested", "AG-attested"),
        ("(GM)", "(AG)"),
        ('"gm"', '"ag"'),
        ("/gm", "/ag"),
        # floors 94/4517 → 150/4387
        ("94/4517", "150/4387"),
        ("94 / 4517", "150 / 4387"),
        ("94, 4517", "150, 4387"),
        ("FLOOR_LAWS, FLOOR_ARTS = 94, 4517", "FLOOR_LAWS, FLOOR_ARTS = 150, 4387"),
        ("or 94)", "or 150)"),
        ("or 94,", "or 150,"),
        ("or 94}", "or 150}"),
        ("= 94,", "= 150,"),
        ("= 94", "= 150"),
        ("@ 94/", "@ 150/"),
        (" 94/", " 150/"),
        ("floor 94/", "floor 150/"),
        ("(94/", "(150/"),
        (" or 94", " or 150"),
        (" 4517", " 4387"),
        ("4517", "4387"),
    ]
    for a, b in reps:
        text = text.replace(a, b)

    text = text.replace("\x00BM25\x00", "BM25").replace("\x00bm25\x00", "bm25")
    text = text.replace("\x00AFTERTJ_US\x00", "after_tj")
    text = text.replace("\x00DESTHOLD\x00", HOLD)
    text = text.replace("\x00DESTCHAIN\x00", DEST_CHAIN)
    text = text.replace("\x00DESTWAVE\x00", WAVE_POS)

    text = text.replace("FLOOR_LAWS, FLOOR_ARTS = 94, 4387", "FLOOR_LAWS, FLOOR_ARTS = 150, 4387")
    text = text.replace("FLOOR_LAWS, FLOOR_ARTS = 150, 4517", "FLOOR_LAWS, FLOOR_ARTS = 150, 4387")
    text = text.replace('int(pack.get("n_articles") or 4517)', 'int(pack.get("n_articles") or 4387)')
    text = text.replace('int(pack.get("n_articles") or 4387)', 'int(pack.get("n_articles") or 4387)')
    text = text.replace('int(pack.get("n_laws") or 94)', 'int(pack.get("n_laws") or 150)')
    text = text.replace('int(pack.get("n_laws") or 150)', 'int(pack.get("n_laws") or 150)')

    # display name fixes (slug vs title)
    text = text.replace('"name": "antigua_barbuda"', '"name": "Antigua and Barbuda"')
    text = text.replace('"name": "Antigua and Barbuda"', '"name": "Antigua and Barbuda"')
    text = text.replace('"slug": "Antigua and Barbuda"', '"slug": "antigua_barbuda"')

    if dst_name == "antigua_barbuda_bm25_smoke.py":
        start = text.index("GATE = [")
        end = text.index("]", start) + 1
        years_line = ", ".join(f'"{y}"' for y in GATE_YEARS)
        stems_line = ", ".join(f'"{s}"' for s in GATE_STEMS)
        gate = f"GATE = [\n    {years_line},\n    {stems_line},\n]"
        text = text[:start] + gate + text[end:]
        text = text.replace(
            'QUERIES = GATE + ["www", "gov", "gm"',
            'QUERIES = GATE + ["www", "gov", "ag"',
        )
        text = text.replace(
            'QUERIES = GATE + ["www", "gov", "ag"',
            'QUERIES = GATE + ["www", "gov", "ag"',
        )
        note = (
            f"attested years {GATE_NOTE_YEARS} plus English legal stems {GATE_NOTE_STEMS} "
            f"from articles.parquet HEAD tip {DST_TIP_SHORT}; URL www/gov/ag is query-only, not GATE."
        )
        text = re.sub(
            r"GATE = attested years [^;]+; URL www/gov/(?:gm|ag) is query-only, not GATE\.",
            f"GATE = {note}",
            text,
        )
        text = text.replace('"gambia_pass"', '"antigua_barbuda_pass"')
        text = text.replace('"antigua_barbuda_pass"', '"antigua_barbuda_pass"')
        text = text.replace('"gambia_gate"', '"antigua_barbuda_gate"')
        text = text.replace('"antigua_barbuda_gate"', '"antigua_barbuda_gate"')
        text = text.replace(
            "attested Gambia years and English legal stems",
            "attested Antigua and Barbuda years and English legal stems",
        )
        text = text.replace(
            "attested Antigua and Barbuda years and English legal stems",
            "attested Antigua and Barbuda years and English legal stems",
        )
        # drop leftover gambia GATE stems if any
        text = text.replace('"gambia"', '"antigua"')
        text = text.replace('"antigua_barbuda"', '"antigua"')  # if stem got slug'd
        # restore slug keys that must stay underscore
        text = text.replace('"antigua_pass"', '"antigua_barbuda_pass"')
        text = text.replace('"antigua_gate"', '"antigua_barbuda_gate"')

    if dst_name == "antigua_barbuda_write_publish_report.py":
        new_gate = f"{GATE_NOTE_YEARS} + stems {GATE_NOTE_STEMS}"
        text = re.sub(
            r"attested years [0-9/]+ \+ stems [a-z_/]+",
            f"attested years {new_gate}",
            text,
        )
        text = text.replace("English GATE", "English (Antigua and Barbuda) GATE")
        text = text.replace(
            "ASCII-fold English (Antigua and Barbuda) GATE",
            "ASCII-fold English (Antigua and Barbuda) GATE",
        )
        text = re.sub(
            r"HOLD 0 STRICT after-SL[^;]*; collectors kept dead \(pkill\); soft never-thin ON; SKIP_US; Italy BLOCKED;[^\"\n]*",
            f"{HOLD}; collectors kept dead (pkill); soft never-thin ON; SKIP_US; Italy BLOCKED; {WAVE_POS}",
            text,
        )
        text = re.sub(
            r"HOLD 0 STRICT after-GM[^;]*; collectors kept dead \(pkill\); soft never-thin ON; SKIP_US; Italy BLOCKED;[^\"\n]*",
            f"{HOLD}; collectors kept dead (pkill); soft never-thin ON; SKIP_US; Italy BLOCKED; {WAVE_POS}",
            text,
        )
        text = text.replace("www/gov/gm is query-only", "www/gov/ag is query-only")
        text = text.replace("gambia/", "antigua_barbuda/")
        # ranked var may have become antigua_barbuda_ranked already
        text = text.replace("antigua_barbuda_ranked = [q for q in smoke", "antigua_barbuda_ranked = [q for q in smoke")

    leftovers = (
        "Gambia", "gambia",
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
        "English (Gambia", "English Gambia",
        "English (Sierra Leone", "English Sierra Leone",
        "Tajikistan", "tajikistan",
    )
    found = [x for x in leftovers if x in text]
    if found:
        raise RuntimeError(f"language/country leftovers in {dst_name}: {found}")
    if dst_name.endswith("_bm25_smoke.py") and '", "gm"' in text:
        raise RuntimeError(f"leftover gm query token in {dst_name}")
    if dst_name.endswith("_bm25_smoke.py") and "www/gov/gm" in text:
        raise RuntimeError(f"leftover gov/gm in {dst_name}")
    # reject bare ISO leftovers that should have been swapped
    scrub = text
    scrub = scrub.replace(DEST_CHAIN, "XX")
    scrub = scrub.replace(HOLD, "XX")
    scrub = scrub.replace(WAVE_POS, "XX")
    scrub = scrub.replace("after-GM", "after-XX")
    scrub = scrub.replace("after GM ", "after XX ")
    scrub = scrub.replace("after_tj", "after_xx")
    scrub = scrub.replace("DM→SL→GM LIVE", "XX→XX→XX LIVE")
    scrub = scrub.replace("after DM→SL→GM LIVE", "after XX→XX→XX LIVE")
    if '"GM"' in scrub or "(GM)" in scrub or "GM→" in scrub or "GM-attested" in scrub:
        tmp = scrub
        if re.search(r'(?<![A-Za-z])GM(?![A-Za-z])', tmp):
            raise RuntimeError(f"leftover GM tokens in {dst_name}: ...{tmp[max(0,tmp.find('GM')-20):tmp.find('GM')+20]}...")
    if "Gambia" in text or "gambia" in text:
        raise RuntimeError(f"leftover Gambia in {dst_name}")
    if "ipfs_gambia" in text:
        raise RuntimeError(f"leftover gambia path in {dst_name}")
    # GATE stem must be antigua not full slug (bm25)
    if dst_name.endswith("_bm25_smoke.py"):
        if '"antigua_barbuda"' in text and "GATE" in text:
            # allow slug elsewhere but GATE list should use antigua
            gate_block = text[text.index("GATE = ["): text.index("]", text.index("GATE = [")) + 1]
            if "antigua_barbuda" in gate_block:
                raise RuntimeError(f"GATE stem should be antigua not slug in {dst_name}")
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
    if entry.get("slug") == "antigua_barbuda" or entry.get("iso2") == "AG":
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
            "repo": "endomorphosis/ipfs_antigua_barbuda_laws",
            "years_attested": [int(y) for y in GATE_YEARS],
            "gate_years": [int(y) for y in GATE_YEARS],
            "gate_stems": GATE_STEMS,
            "note": (
                f"AG FIRST_IR scaffold; tip MATCH {DST_TIP_SHORT}@150/4387; {HOLD}; "
                f"soft never-thin ON; SKIP_US; Italy BLOCKED; {WAVE_POS}"
            ),
            "status": "CLAIMED",
        })
        break
else:
    raise RuntimeError("Antigua and Barbuda entry missing from wave JSON")
wave.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print("updated wave JSON Antigua and Barbuda entry")
print("GATE years", GATE_YEARS)
print("GATE stems", GATE_STEMS)
print("n_gate", len(GATE_YEARS) + len(GATE_STEMS))
print("GATE language: English")
print("HOLD", HOLD)
