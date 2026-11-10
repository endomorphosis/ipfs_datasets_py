#!/usr/bin/env python3
"""Adapt the Eswatini English memsafe FIRST_IR pack to Niue NU tip 097999244810.

English Niue; FIRST_IR; HOLD 0 STRICT after-SZ (NU→GW→SR→GQ→GY→BJ→SO→MV).
Soft never-thin ON; SKIP_US; Italy BLOCKED. WAVE after_dj after SZ LIVE
(…→SZ LIVE → NU → GW→SR→GQ→GY→BJ→SO→MV), NOT wave end.
GATE: attested years + English legal stems from data/articles.parquet tip 097999244810
(English; include niue). URL www/gov.nu query-only, NOT GATE.
Source tip 7076fc82ba00 (Eswatini English memsafe with data/ paths)
— GATE English years+stems.
Keep data/articles.parquet + data/laws.parquet; agent-data not cient-data.
Do NOT start Guinea-Bissau/next after LIVE.
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
SRC_TIP_FULL = "7076fc82ba0086d8509136c03535cf82cd960801"
SRC_TIP_SHORT = "7076fc82ba00"
DST_TIP_FULL = "0979992448108b95d6d92fc645eeb752f69e93c2"
DST_TIP_SHORT = "097999244810"
FLOOR_LAWS, FLOOR_ARTS = 99, 2261
SRC_FLOOR_L, SRC_FLOOR_A = 56, 2385

# Sampled from data/articles.parquet @ 097999244810 (~10 years + ~11 English stems)
# Whole-word FTS hits; laws=99 articles=2261.
# Top years by doc hits; stems from user list all attested (+ constitution).
GATE_YEARS = [
    "2024", "2025", "2026", "2021", "2019",
    "1966", "2004", "2022", "2006", "2016",
]
GATE_STEMS = [
    "article", "section", "act", "law", "person", "republic",
    "code", "niue", "minister", "government", "constitution",
]
YEARS_ATTESTED = [int(y) for y in GATE_YEARS] + [
    2013, 1975, 1974, 1965, 1961, 2000, 2010, 2018, 2020, 2017,
]
GATE_NOTE_YEARS = "/".join(GATE_YEARS)
GATE_NOTE_STEMS = "/".join(GATE_STEMS)
HOLD = "HOLD 0 STRICT after-SZ (NU→GW→SR→GQ→GY→BJ→SO→MV)"
WAVE_POS = (
    "after SZ LIVE of after_dj wave "
    "(…→SZ LIVE → NU → GW→SR→GQ→GY→BJ→SO→MV; NOT wave end)"
)
DEST_CHAIN = "NU→GW→SR→GQ→GY→BJ→SO→MV"
SRC_HOLD = "HOLD 0 STRICT after-BI (SZ→NU→GW→SR→GQ→GY→BJ→SO→MV)"
SRC_WAVE = (
    "after BI LIVE of after_dj wave "
    "(…→BI LIVE → SZ → NU→GW→SR→GQ→GY→BJ→SO→MV; NOT wave end)"
)
SRC_CHAIN = "SZ→NU→GW→SR→GQ→GY→BJ→SO→MV"

FILES = [
    ("eswatini_soft_filter.py", "niue_soft_filter.py"),
    (f"eswatini_corpus_stream_{SRC_TIP_SHORT}.py", f"niue_corpus_stream_{DST_TIP_SHORT}.py"),
    (f"eswatini_encode_memsafe_{SRC_TIP_SHORT}.py", f"niue_encode_memsafe_{DST_TIP_SHORT}.py"),
    (f"eswatini_finish_from_emb_{SRC_TIP_SHORT}.py", f"niue_finish_from_emb_{DST_TIP_SHORT}.py"),
    (f"eswatini_stream_graph_parts_{SRC_TIP_SHORT}.py", f"niue_stream_graph_parts_{DST_TIP_SHORT}.py"),
    (f"eswatini_package_memsafe_{SRC_TIP_SHORT}.py", f"niue_package_memsafe_{DST_TIP_SHORT}.py"),
    ("eswatini_upload.py", "niue_upload.py"),
    ("eswatini_bm25_smoke.py", "niue_bm25_smoke.py"),
    ("eswatini_write_publish_report.py", "niue_write_publish_report.py"),
    (f"eswatini_orchestrator_{SRC_TIP_SHORT}.py", f"niue_orchestrator_{DST_TIP_SHORT}.py"),
]


def adapt(text: str, dst_name: str) -> str:
    # Repair path corruption from prior adapts
    for bad in (
        "cient-data", "prent-data", "stent-data", "cvent-data", "scent-data",
        "carent-data", "yement-data", "djiboutient-data", "marshallislandsent-data",
        "kiribatient-data", "burundient-data", "eswatinient-data", "niueent-data",
    ):
        text = text.replace(f"/home/box/{bad}/", "/home/box/agent-data/")
        text = text.replace(bad, "agent-data")

    # Protect BM25
    text = text.replace("BM25", "\x00BM25\x00").replace("bm25", "\x00bm25\x00")
    text = text.replace("bmjacency", "adjacency")

    # Protect HOLD / wave / chains BEFORE ISO/slug swaps
    text = text.replace(SRC_HOLD, "\x00DESTHOLD\x00")
    text = text.replace(SRC_WAVE, "\x00DESTWAVE\x00")
    text = text.replace(SRC_CHAIN, "\x00DESTCHAIN\x00")
    text = text.replace(HOLD, "\x00DESTHOLD\x00")
    text = text.replace(DEST_CHAIN, "\x00DESTCHAIN\x00")
    text = text.replace(WAVE_POS, "\x00DESTWAVE\x00")
    text = text.replace("after-BI", "\x00AFTERSZ\x00")
    text = text.replace("after BI ", "\x00AFTERSZ_SP\x00")
    text = text.replace("after_dj", "\x00AFTERDJ_US\x00")
    text = text.replace(
        "…→BI LIVE → SZ → NU→GW→SR→GQ→GY→BJ→SO→MV",
        "\x00SRCCHAIN_FULL\x00",
    )
    text = text.replace("after BI LIVE of \x00AFTERDJ_US\x00 wave", "\x00DESTWAVE_SHORT\x00")
    text = text.replace("after BI LIVE of after_dj wave", "\x00DESTWAVE_SHORT\x00")
    text = text.replace("SZ FIRST_IR", "\x00DESTFIRST\x00")

    reps = [
        (SRC_TIP_FULL, DST_TIP_FULL),
        (SRC_TIP_SHORT, DST_TIP_SHORT),
        ("endomorphosis/ipfs_eswatini_laws", "endomorphosis/ipfs_niue_laws"),
        ("justicedao/ipfs_eswatini_laws_ir", "justicedao/ipfs_niue_laws_ir"),
        ("ipfs_eswatini_laws_ir", "ipfs_niue_laws_ir"),
        ("ipfs_eswatini_laws", "ipfs_niue_laws"),
        # HOLD / wave restore
        ("\x00DESTHOLD\x00", HOLD),
        ("\x00DESTWAVE\x00", WAVE_POS),
        ("\x00DESTWAVE_SHORT\x00", WAVE_POS),
        ("\x00DESTCHAIN\x00", DEST_CHAIN),
        ("\x00SRCCHAIN_FULL\x00", "…→SZ LIVE → NU → GW→SR→GQ→GY→BJ→SO→MV"),
        ("\x00AFTERSZ\x00", "after-SZ"),
        ("\x00AFTERSZ_SP\x00", "after SZ "),
        ("\x00DESTFIRST\x00", "NU FIRST_IR"),
        ("SZ FIRST_IR (not wave end)", "NU FIRST_IR (not wave end)"),
        ("www/gov.sz", "www/gov.nu"),
        ("gov.sz", "gov.nu"),
        ("centralbank.org.sz", "www.gov.nu"),
        # Language / country
        ("English (Eswatini)", "English (Niue)"),
        ("English Eswatini", "English Niue"),
        ("ASCII-fold English", "ASCII-fold English"),
        ("Eswatini", "Niue"),
        # slug / path forms BEFORE bare eswatini
        ("eswatini_ranked", "niue_ranked"),
        ("eswatini_gate", "niue_gate"),
        ("eswatini_pass", "niue_pass"),
        ("eswatini_encode_memsafe", "niue_encode_memsafe"),
        ("eswatini_package_memsafe", "niue_package_memsafe"),
        ("eswatini_corpus_stream", "niue_corpus_stream"),
        ("eswatini_encode_done", "niue_encode_done"),
        ("eswatini_filtered_", "niue_filtered_"),
        ("eswatini_", "niue_"),
        # ISO whole-token / path forms only
        ('"SZ"', '"NU"'),
        ("SZ-attested", "NU-attested"),
        ("(SZ)", "(NU)"),
        ('"sz"', '"nu"'),
        # floors 56/2385 → 99/2261
        ("56/2385", "99/2261"),
        ("56 / 2385", "99 / 2261"),
        ("56, 2385", "99, 2261"),
        ("FLOOR_LAWS, FLOOR_ARTS = 56, 2385", "FLOOR_LAWS, FLOOR_ARTS = 99, 2261"),
        ("or 56)", "or 99)"),
        ("or 56,", "or 99,"),
        ("or 56}", "or 99}"),
        ("= 56,", "= 99,"),
        ("= 56", "= 99"),
        ("@ 56/", "@ 99/"),
        (" 56/", " 99/"),
        ("floor 56/", "floor 99/"),
        ("(56/", "(99/"),
        (" or 56", " or 99"),
        (" 2385", " 2261"),
        ("2385", "2261"),
    ]
    for a, b in reps:
        text = text.replace(a, b)

    # Bare slug "eswatini" → "niue"
    text = re.sub(r"(?<![A-Za-z0-9_])eswatini(?![A-Za-z0-9_])", "niue", text)

    text = text.replace("\x00BM25\x00", "BM25").replace("\x00bm25\x00", "bm25")
    text = text.replace("\x00AFTERDJ_US\x00", "after_dj")
    text = text.replace("\x00DESTHOLD\x00", HOLD)
    text = text.replace("\x00DESTCHAIN\x00", DEST_CHAIN)
    text = text.replace("\x00DESTWAVE\x00", WAVE_POS)

    text = text.replace(
        "FLOOR_LAWS, FLOOR_ARTS = 56, 2261",
        "FLOOR_LAWS, FLOOR_ARTS = 99, 2261",
    )
    text = text.replace(
        "FLOOR_LAWS, FLOOR_ARTS = 99, 2385",
        "FLOOR_LAWS, FLOOR_ARTS = 99, 2261",
    )
    text = text.replace(
        'int(pack.get("n_articles") or 2385)',
        'int(pack.get("n_articles") or 2261)',
    )
    text = text.replace(
        'int(pack.get("n_articles") or 2261)',
        'int(pack.get("n_articles") or 2261)',
    )
    text = text.replace(
        'int(pack.get("n_laws") or 56)',
        'int(pack.get("n_laws") or 99)',
    )
    text = text.replace(
        'int(pack.get("n_laws") or 99)',
        'int(pack.get("n_laws") or 99)',
    )

    # display name / slug fixes
    text = text.replace('"name": "niue"', '"name": "Niue"')
    text = text.replace('"name": "Niue"', '"name": "Niue"')
    text = text.replace('"slug": "Niue"', '"slug": "niue"')
    text = text.replace('SLUG = "Niue"', 'SLUG = "niue"')
    text = text.replace('SLUG = "niue"', 'SLUG = "niue"')
    text = text.replace('"country": "Niue"', '"country": "niue"')

    # Ensure agent-data survived
    for bad in (
        "cient-data", "prent-data", "stent-data", "cvent-data", "scent-data",
        "carent-data", "yement-data", "djiboutient-data", "marshallislandsent-data",
        "kiribatient-data", "burundient-data", "eswatinient-data", "niueent-data",
    ):
        text = text.replace(f"/home/box/{bad}/", "/home/box/agent-data/")
        text = text.replace(bad, "agent-data")

    if dst_name == "niue_bm25_smoke.py":
        start = text.index("GATE = [")
        end = text.index("]", start) + 1
        years_line = ", ".join(f'"{y}"' for y in GATE_YEARS)
        stems_line = ", ".join(f'"{s}"' for s in GATE_STEMS)
        gate = f"GATE = [\n    {years_line},\n    {stems_line},\n]"
        text = text[:start] + gate + text[end:]
        text = re.sub(
            r"QUERIES = GATE \+ \[[^\]]*\]",
            'QUERIES = GATE + ["www", "gov.nu", "www.gov.nu", "court", "order", "parliament", "assembly", "chapter", "shall", "ordinance"]',
            text,
            count=1,
        )
        text = re.sub(
            r'"""BM25 smoke for Niue IR.*?"""',
            '"""BM25 smoke for Niue IR — English legal corpus; years + English legal stems FTS gate.\n\n'
            "GATE is attested ASCII years plus English legal stems (ASCII-fold). URL www/gov.nu\n"
            "is query-only, never GATE. Every GATE token must rank a hit.\n"
            '"""',
            text,
            count=1,
            flags=re.S,
        )
        note = (
            f"attested years {GATE_NOTE_YEARS} plus English legal stems {GATE_NOTE_STEMS} "
            f"from articles.parquet HEAD tip {DST_TIP_SHORT}; URL www/gov.nu is query-only, not GATE."
        )
        text = re.sub(
            r'"tokenizer_note":\s*"[^"]*"',
            f'"tokenizer_note": "{note}"',
            text,
            count=1,
        )
        text = re.sub(
            r"GATE = attested years [^\"\n]+",
            f"GATE = {note}",
            text,
            count=1,
        )
        text = text.replace(
            "attested Niue years and English legal stems",
            "attested Niue years and English legal stems",
        )
        # kill leftover kingdom stem references outside GATE already replaced
        text = text.replace("kingdom", "constitution")

    if dst_name == "niue_write_publish_report.py":
        gate_note = (
            f"BM25 PASS on Niue ASCII-fold English GATE "
            f"(attested years {GATE_NOTE_YEARS} + stems {GATE_NOTE_STEMS}); "
            f"URL www/gov.nu is query-only, not GATE"
        )
        text = re.sub(
            r'BM25 PASS on Niue[^"]*"',
            gate_note + '"',
            text,
            count=1,
        )
        text = re.sub(
            r'BM25 PASS on [^"]*GATE[^"]*"',
            gate_note + '"',
            text,
            count=1,
        )
        text = text.replace("French years+stems GATE", "English years+stems GATE")
        text = text.replace("English legal stems GATE", "English years+stems GATE")
        text = re.sub(
            r"HOLD 0 STRICT after-BI[^;]*; collectors kept dead \(pkill\); soft never-thin ON; SKIP_US; Italy BLOCKED;[^\"\n]*",
            f"{HOLD}; collectors kept dead (pkill); soft never-thin ON; SKIP_US; Italy BLOCKED; {WAVE_POS}",
            text,
        )
        text = re.sub(
            r"HOLD 0 STRICT after-SZ[^;]*; collectors kept dead \(pkill\); soft never-thin ON; SKIP_US; Italy BLOCKED;[^\"\n]*",
            f"{HOLD}; collectors kept dead (pkill); soft never-thin ON; SKIP_US; Italy BLOCKED; {WAVE_POS}",
            text,
        )
        text = text.replace("www/gov.sz is query-only", "www/gov.nu is query-only")
        text = text.replace("www/gov.nu is query-only", "www/gov.nu is query-only")
        text = re.sub(r"[ \t]{2,}", " ", text)

    leftovers = (
        "Eswatini", "eswatini",
        "Burundi", "burundi",
        "Kiribati", "kiribati",
        "cient-data", "prent-data", "stent-data", "cvent-data", "scent-data",
        "carent-data", "yement-data", "djiboutient-data", "marshallislandsent-data",
        "kiribatient-data", "burundient-data", "eswatinient-data", "niueent-data",
        "gov.sz", "centralbank.org.sz", "kingdom",
    )
    found = []
    for x in leftovers:
        if x == "eswatini":
            if re.search(r"(?<![A-Za-z0-9_])eswatini(?![A-Za-z0-9_])", text):
                found.append(x)
            continue
        if x == "burundi":
            if re.search(r"(?<![A-Za-z0-9_])burundi(?![A-Za-z0-9_])", text):
                found.append(x)
            continue
        if x == "kiribati":
            if re.search(r"(?<![A-Za-z0-9_])kiribati(?![A-Za-z0-9_])", text):
                found.append(x)
            continue
        if x == "kingdom":
            # allow only if somehow still present; reject
            if "kingdom" in text.lower() and '"kingdom"' in text:
                found.append(x)
            elif re.search(r"(?<![A-Za-z])kingdom(?![A-Za-z])", text, re.I):
                found.append(x)
            continue
        if x in text:
            found.append(x)
    if found:
        raise RuntimeError(f"language/country leftovers in {dst_name}: {found}")

    # Reject SZ leftovers in GATE
    if dst_name.endswith("_bm25_smoke.py"):
        gate_slice = text[text.index("GATE = ["): text.index("]", text.index("GATE = [")) + 1]
        for bad in (
            "eswatini", "kingdom", "burundi", "kiribati", "marshall",
            "loi", "decret", "ministre",
        ):
            if f'"{bad}"' in gate_slice:
                raise RuntimeError(f"non-NU token in GATE of {dst_name}: {bad}")
        for stem in GATE_STEMS:
            if f'"{stem}"' not in gate_slice:
                raise RuntimeError(f"missing English stem in GATE of {dst_name}: {stem}")
        for year in GATE_YEARS:
            if f'"{year}"' not in gate_slice:
                raise RuntimeError(f"missing year in GATE of {dst_name}: {year}")
        if '", "sz"' in text or '", "SZ"' in text:
            raise RuntimeError(f"leftover sz query token in {dst_name}")
        if "gov.sz" in text:
            raise RuntimeError(f"leftover gov.sz in {dst_name}")

    # reject bare eswatini / SZ leftovers outside protected HOLD/wave
    scrub = text
    scrub = scrub.replace(WAVE_POS, "XX")
    scrub = scrub.replace(HOLD, "XX")
    scrub = scrub.replace(DEST_CHAIN, "XX")
    scrub = scrub.replace(SRC_CHAIN, "XX")
    scrub = scrub.replace(SRC_HOLD, "XX")
    scrub = scrub.replace(SRC_WAVE, "XX")
    scrub = scrub.replace("after-SZ", "after-XX")
    scrub = scrub.replace("after SZ ", "after XX ")
    scrub = scrub.replace("after_dj", "after_xx")
    scrub = scrub.replace("SZ LIVE", "XX LIVE")
    scrub = scrub.replace("SZ→", "XX→")
    scrub = scrub.replace("…→SZ", "…→XX")
    scrub = scrub.replace("%SZ", "%XX")  # strftime Zulu, not ISO2
    if re.search(r"(?<![A-Za-z0-9_])eswatini(?![A-Za-z0-9_])", scrub):
        m = re.search(r"(?<![A-Za-z0-9_])eswatini(?![A-Za-z0-9_])", scrub)
        raise RuntimeError(
            f"leftover eswatini in {dst_name}: ...{scrub[max(0, m.start()-20):m.start()+20]}..."
        )
    if re.search(r"(?<![A-Za-z%])SZ(?![A-Za-z])", scrub):
        m = re.search(r"(?<![A-Za-z%])SZ(?![A-Za-z])", scrub)
        raise RuntimeError(
            f"leftover SZ in {dst_name}: ...{scrub[max(0, m.start()-30):m.start()+30]}..."
        )
    if "ipfs_eswatini" in text:
        raise RuntimeError(f"leftover eswatini path in {dst_name}")
    if "agent-data" not in text and "SECRET" in text.upper():
        if any(x in dst_name for x in ("soft_filter", "upload", "orchestrator")):
            if "/home/box/" in text and "agent-data" not in text:
                raise RuntimeError(f"missing agent-data secret path in {dst_name}")
    # data/ paths must survive
    if "soft_filter" in dst_name or "corpus_stream" in dst_name:
        if "data/laws.parquet" not in text and 'data" / "laws.parquet"' not in text:
            if '"data"' not in text and "/data/" not in text:
                raise RuntimeError(f"missing data/ parquet paths in {dst_name}")
    return text


for src_name, dst_name in FILES:
    src = ROOT / src_name
    if not src.is_file():
        raise FileNotFoundError(src)
    (ROOT / dst_name).write_text(
        adapt(src.read_text(encoding="utf-8"), dst_name), encoding="utf-8"
    )
    print(f"wrote {dst_name}")

wave = Path("/workspace/country-law-triage/next_ir_ok_wave_after_dj.json")
data = json.loads(wave.read_text(encoding="utf-8"))
for entry in data["queue"]:
    if entry.get("slug") == "niue" or entry.get("iso2") == "NU":
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
            "iso2": "NU",
            "slug": "niue",
            "repo": "endomorphosis/ipfs_niue_laws",
            "years_attested": YEARS_ATTESTED,
            "gate_years": [int(y) for y in GATE_YEARS],
            "gate_stems": GATE_STEMS,
            "note": (
                f"NU FIRST_IR scaffold; tip MATCH {DST_TIP_SHORT}@99/2261; {HOLD}; "
                f"soft never-thin ON; SKIP_US; Italy BLOCKED; {WAVE_POS}; "
                f"English GATE ({len(GATE_YEARS)} years + {len(GATE_STEMS)} stems)"
            ),
            "status": "CLAIMED",
            "mode": "FIRST_IR",
            "wave_end": False,
        })
        break
else:
    raise RuntimeError("Niue/NU entry missing from wave JSON")

data["wave_status"] = "IN_PROGRESS_NU"
data["hold"] = HOLD
data["current"] = "niue"
data["do_not_start_next"] = "guineabissau"
data["next"] = "guineabissau"
wave.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print("updated wave JSON Niue entry")
print("GATE years", GATE_YEARS)
print("GATE stems", GATE_STEMS)
print("n_gate", len(GATE_YEARS) + len(GATE_STEMS))
print("HOLD", HOLD)
print("GATE language: English years+stems")
