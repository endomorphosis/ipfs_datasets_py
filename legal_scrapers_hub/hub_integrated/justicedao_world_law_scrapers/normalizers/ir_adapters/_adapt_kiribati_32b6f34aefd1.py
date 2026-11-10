#!/usr/bin/env python3
"""Adapt the Marshall Islands English memsafe FIRST_IR pack to Kiribati KI tip 32b6f34aefd1.

English Kiribati; FIRST_IR; HOLD 0 STRICT after-MH (KI→BI→SZ→NU→GW→SR→GQ→GY→BJ→SO→MV).
Soft never-thin ON; SKIP_US; Italy BLOCKED. WAVE after_dj after MH LIVE
(MH→KI→BI→SZ→NU→GW→SR→GQ→GY→BJ→SO→MV), NOT wave end.
GATE: attested years + English legal stems from data/articles.parquet tip 32b6f34aefd1
(English; include kiribati). URL www/president.gov.ki query-only, NOT GATE.
Source tip 74821456297a (Marshall Islands English memsafe with data/ paths)
— keep language English (Kiribati); GATE English years+stems.
Keep data/articles.parquet + data/laws.parquet; agent-data not cient-data.
Do NOT start Burundi/next after LIVE.
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
SRC_TIP_FULL = "74821456297a7786caf5b7fc54c6770482130629"
SRC_TIP_SHORT = "74821456297a"
DST_TIP_FULL = "32b6f34aefd14f542d25cd9dbde7e86f90883449"
DST_TIP_SHORT = "32b6f34aefd1"
FLOOR_LAWS, FLOOR_ARTS = 165, 3118
SRC_FLOOR_L, SRC_FLOOR_A = 884, 3119

# Sampled from data/articles.parquet @ 32b6f34aefd1 (~10 years + ~11 English stems)
# Whole-word ASCII-fold FTS hits; laws=165 articles=3118.
# Top years by doc hits; stems from user list all attested.
GATE_YEARS = [
    "2022", "2021", "2025", "2024", "2026",
    "2019", "2020", "2013", "2014", "2023",
]
GATE_STEMS = [
    "article", "section", "act", "law", "person", "republic",
    "code", "kiribati", "minister", "government",
]
YEARS_ATTESTED = [int(y) for y in GATE_YEARS] + [
    2018, 2015, 2016, 2017, 2010, 2012, 2011, 2006, 2000, 2005,
]
GATE_NOTE_YEARS = "/".join(GATE_YEARS)
GATE_NOTE_STEMS = "/".join(GATE_STEMS)
HOLD = "HOLD 0 STRICT after-MH (KI→BI→SZ→NU→GW→SR→GQ→GY→BJ→SO→MV)"
WAVE_POS = (
    "after MH LIVE of after_dj wave "
    "(MH→KI→BI→SZ→NU→GW→SR→GQ→GY→BJ→SO→MV; NOT wave end)"
)
DEST_CHAIN = "KI→BI→SZ→NU→GW→SR→GQ→GY→BJ→SO→MV"
SRC_HOLD = "HOLD 0 STRICT after-DJ (MH→KI→BI→SZ→NU→GW→SR→GQ→GY→BJ→SO→MV)"
SRC_WAVE = (
    "first country of after_dj wave "
    "(MH→KI→BI→SZ→NU→GW→SR→GQ→GY→BJ→SO→MV; NOT wave end)"
)
SRC_CHAIN = "MH→KI→BI→SZ→NU→GW→SR→GQ→GY→BJ→SO→MV"

FILES = [
    ("marshallislands_soft_filter.py", "kiribati_soft_filter.py"),
    (f"marshallislands_corpus_stream_{SRC_TIP_SHORT}.py", f"kiribati_corpus_stream_{DST_TIP_SHORT}.py"),
    (f"marshallislands_encode_memsafe_{SRC_TIP_SHORT}.py", f"kiribati_encode_memsafe_{DST_TIP_SHORT}.py"),
    (f"marshallislands_finish_from_emb_{SRC_TIP_SHORT}.py", f"kiribati_finish_from_emb_{DST_TIP_SHORT}.py"),
    (f"marshallislands_stream_graph_parts_{SRC_TIP_SHORT}.py", f"kiribati_stream_graph_parts_{DST_TIP_SHORT}.py"),
    (f"marshallislands_package_memsafe_{SRC_TIP_SHORT}.py", f"kiribati_package_memsafe_{DST_TIP_SHORT}.py"),
    ("marshallislands_upload.py", "kiribati_upload.py"),
    ("marshallislands_bm25_smoke.py", "kiribati_bm25_smoke.py"),
    ("marshallislands_write_publish_report.py", "kiribati_write_publish_report.py"),
    (f"marshallislands_orchestrator_{SRC_TIP_SHORT}.py", f"kiribati_orchestrator_{DST_TIP_SHORT}.py"),
]


def adapt(text: str, dst_name: str) -> str:
    # Repair path corruption from prior adapts
    for bad in (
        "cient-data", "prent-data", "stent-data", "cvent-data", "scent-data",
        "carent-data", "yement-data", "djiboutient-data", "marshallislandsent-data",
        "kiribatient-data",
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
    text = text.replace("after-DJ", "\x00AFTERMH\x00")
    text = text.replace("after DJ ", "\x00AFTERMH_SP\x00")
    text = text.replace("after_dj", "\x00AFTERDJ_US\x00")
    text = text.replace(
        "MH→KI→BI→SZ→NU→GW→SR→GQ→GY→BJ→SO→MV",
        "\x00SRCCHAIN\x00",
    )
    text = text.replace("first country of \x00AFTERDJ_US\x00 wave", "\x00DESTWAVE_SHORT\x00")
    text = text.replace("first country of after_dj wave", "\x00DESTWAVE_SHORT\x00")
    text = text.replace("MH FIRST_IR", "\x00DESTFIRST\x00")

    reps = [
        (SRC_TIP_FULL, DST_TIP_FULL),
        (SRC_TIP_SHORT, DST_TIP_SHORT),
        ("endomorphosis/ipfs_marshallislands_laws", "endomorphosis/ipfs_kiribati_laws"),
        ("justicedao/ipfs_marshallislands_laws_ir", "justicedao/ipfs_kiribati_laws_ir"),
        ("ipfs_marshallislands_laws_ir", "ipfs_kiribati_laws_ir"),
        ("ipfs_marshallislands_laws", "ipfs_kiribati_laws"),
        # HOLD / wave restore
        ("\x00DESTHOLD\x00", HOLD),
        ("\x00DESTWAVE\x00", WAVE_POS),
        ("\x00DESTWAVE_SHORT\x00", WAVE_POS),
        ("\x00DESTCHAIN\x00", DEST_CHAIN),
        ("\x00SRCCHAIN\x00", DEST_CHAIN),
        ("\x00AFTERMH\x00", "after-MH"),
        ("\x00AFTERMH_SP\x00", "after MH "),
        ("\x00DESTFIRST\x00", "KI FIRST_IR"),
        ("MH FIRST_IR (not wave end)", "KI FIRST_IR (not wave end)"),
        ("www/rmiparliament.org", "www/president.gov.ki"),
        ("rmiparliament.org", "president.gov.ki"),
        # Language stays English; country name swaps
        ("English (Marshall Islands)", "English (Kiribati)"),
        ("English Marshall Islands", "English Kiribati"),
        ("Marshall Islands", "Kiribati"),
        # slug / path forms BEFORE bare marshallislands
        ("marshallislands_ranked", "kiribati_ranked"),
        ("marshallislands_gate", "kiribati_gate"),
        ("marshallislands_pass", "kiribati_pass"),
        ("marshallislands_encode_memsafe", "kiribati_encode_memsafe"),
        ("marshallislands_package_memsafe", "kiribati_package_memsafe"),
        ("marshallislands_corpus_stream", "kiribati_corpus_stream"),
        ("marshallislands_encode_done", "kiribati_encode_done"),
        ("marshallislands_filtered_", "kiribati_filtered_"),
        ("marshallislands_", "kiribati_"),
        # ISO whole-token / path forms only
        ('"MH"', '"KI"'),
        ("MH-attested", "KI-attested"),
        ("(MH)", "(KI)"),
        ('"mh"', '"ki"'),
        # floors 884/3119 → 165/3118
        ("884/3119", "165/3118"),
        ("884 / 3119", "165 / 3118"),
        ("884, 3119", "165, 3118"),
        ("FLOOR_LAWS, FLOOR_ARTS = 884, 3119", "FLOOR_LAWS, FLOOR_ARTS = 165, 3118"),
        ("or 884)", "or 165)"),
        ("or 884,", "or 165,"),
        ("or 884}", "or 165}"),
        ("= 884,", "= 165,"),
        ("= 884", "= 165"),
        ("@ 884/", "@ 165/"),
        (" 884/", " 165/"),
        ("floor 884/", "floor 165/"),
        ("(884/", "(165/"),
        (" or 884", " or 165"),
        (" 3119", " 3118"),
        ("3119", "3118"),
        # language field leftovers stay English
        ('"language": "English"', '"language": "English"'),
        ('"lang": "English"', '"lang": "English"'),
    ]
    for a, b in reps:
        text = text.replace(a, b)

    # Bare slug "marshallislands" → "kiribati"
    text = re.sub(r"(?<![A-Za-z0-9_])marshallislands(?![A-Za-z0-9_])", "kiribati", text)
    # "marshall" / "islands" leftovers in GATE contexts handled later
    text = re.sub(r"(?<![A-Za-z0-9_])marshall(?![A-Za-z0-9_])", "kiribati", text)

    text = text.replace("\x00BM25\x00", "BM25").replace("\x00bm25\x00", "bm25")
    text = text.replace("\x00AFTERDJ_US\x00", "after_dj")
    text = text.replace("\x00DESTHOLD\x00", HOLD)
    text = text.replace("\x00DESTCHAIN\x00", DEST_CHAIN)
    text = text.replace("\x00DESTWAVE\x00", WAVE_POS)

    text = text.replace(
        "FLOOR_LAWS, FLOOR_ARTS = 884, 3118",
        "FLOOR_LAWS, FLOOR_ARTS = 165, 3118",
    )
    text = text.replace(
        "FLOOR_LAWS, FLOOR_ARTS = 165, 3119",
        "FLOOR_LAWS, FLOOR_ARTS = 165, 3118",
    )
    text = text.replace(
        'int(pack.get("n_articles") or 3119)',
        'int(pack.get("n_articles") or 3118)',
    )
    text = text.replace(
        'int(pack.get("n_articles") or 3118)',
        'int(pack.get("n_articles") or 3118)',
    )
    text = text.replace(
        'int(pack.get("n_laws") or 884)',
        'int(pack.get("n_laws") or 165)',
    )
    text = text.replace(
        'int(pack.get("n_laws") or 165)',
        'int(pack.get("n_laws") or 165)',
    )

    # display name / slug fixes
    text = text.replace('"name": "kiribati"', '"name": "Kiribati"')
    text = text.replace('"name": "Kiribati"', '"name": "Kiribati"')
    text = text.replace('"slug": "Kiribati"', '"slug": "kiribati"')
    text = text.replace('SLUG = "Kiribati"', 'SLUG = "kiribati"')
    text = text.replace('SLUG = "kiribati"', 'SLUG = "kiribati"')
    text = text.replace('"country": "Kiribati"', '"country": "kiribati"')

    # Ensure agent-data survived
    for bad in (
        "cient-data", "prent-data", "stent-data", "cvent-data", "scent-data",
        "carent-data", "yement-data", "djiboutient-data", "marshallislandsent-data",
        "kiribatient-data",
    ):
        text = text.replace(f"/home/box/{bad}/", "/home/box/agent-data/")
        text = text.replace(bad, "agent-data")

    if dst_name == "kiribati_bm25_smoke.py":
        start = text.index("GATE = [")
        end = text.index("]", start) + 1
        years_line = ", ".join(f'"{y}"' for y in GATE_YEARS)
        stems_line = ", ".join(f'"{s}"' for s in GATE_STEMS)
        gate = f"GATE = [\n    {years_line},\n    {stems_line},\n]"
        text = text[:start] + gate + text[end:]
        text = re.sub(
            r"QUERIES = GATE \+ \[[^\]]*\]",
            'QUERIES = GATE + ["www", "president.gov.ki", "court", "order", "offence", "constitution", "president", "parliament", "chapter", "shall"]',
            text,
            count=1,
        )
        text = re.sub(
            r'"""BM25 smoke for Kiribati IR.*?"""',
            '"""BM25 smoke for Kiribati IR — English legal corpus; years + English legal stems FTS gate.\n\n'
            "GATE is attested ASCII years plus English legal stems (ASCII-fold). URL www/president.gov.ki\n"
            "is query-only, never GATE. Every GATE token must rank a hit.\n"
            '"""',
            text,
            count=1,
            flags=re.S,
        )
        note = (
            f"attested years {GATE_NOTE_YEARS} plus English legal stems {GATE_NOTE_STEMS} "
            f"from articles.parquet HEAD tip {DST_TIP_SHORT}; URL www/president.gov.ki is query-only, not GATE."
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
        text = text.replace("— English legal corpus", "— English legal corpus")
        text = text.replace("English years+stems English GATE", "English years+stems GATE")
        text = text.replace(
            "attested Kiribati years and English legal stems",
            "attested Kiribati years and English legal stems",
        )
        text = text.replace('"kiribati_pass"', '"kiribati_pass"')
        text = text.replace('"kiribati_gate"', '"kiribati_gate"')

    if dst_name == "kiribati_write_publish_report.py":
        gate_note = (
            f"BM25 PASS on Kiribati ASCII-fold English GATE "
            f"(attested years {GATE_NOTE_YEARS} + stems {GATE_NOTE_STEMS}); "
            f"URL www/president.gov.ki is query-only, not GATE"
        )
        text = re.sub(
            r'BM25 PASS on Kiribati[^"]*"',
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
        text = text.replace("English years+stems GATE", "English years+stems GATE")
        text = text.replace("English legal stems GATE", "English years+stems GATE")
        text = re.sub(
            r"HOLD 0 STRICT after-DJ[^;]*; collectors kept dead \(pkill\); soft never-thin ON; SKIP_US; Italy BLOCKED;[^\"\n]*",
            f"{HOLD}; collectors kept dead (pkill); soft never-thin ON; SKIP_US; Italy BLOCKED; {WAVE_POS}",
            text,
        )
        text = re.sub(
            r"HOLD 0 STRICT after-MH[^;]*; collectors kept dead \(pkill\); soft never-thin ON; SKIP_US; Italy BLOCKED;[^\"\n]*",
            f"{HOLD}; collectors kept dead (pkill); soft never-thin ON; SKIP_US; Italy BLOCKED; {WAVE_POS}",
            text,
        )
        text = text.replace("www/rmiparliament.org is query-only", "www/president.gov.ki is query-only")
        text = text.replace("www/president.gov.ki is query-only", "www/president.gov.ki is query-only")
        text = re.sub(r"[ \t]{2,}", " ", text)

    leftovers = (
        "Marshall Islands", "marshallislands", "Marshall",
        "cient-data", "prent-data", "stent-data", "cvent-data", "scent-data",
        "carent-data", "yement-data", "djiboutient-data", "marshallislandsent-data",
        "rmiparliament.org", "nitijela",
    )
    found = []
    for x in leftovers:
        if x == "marshallislands":
            if re.search(r"(?<![A-Za-z0-9_])marshallislands(?![A-Za-z0-9_])", text):
                found.append(x)
            continue
        if x == "Marshall":
            if re.search(r"(?<![A-Za-z])Marshall(?![A-Za-z])", text):
                found.append(x)
            continue
        if x in text:
            found.append(x)
    if found:
        raise RuntimeError(f"language/country leftovers in {dst_name}: {found}")
    # Reject MH stems leftover in GATE
    if dst_name.endswith("_bm25_smoke.py"):
        gate_slice = text[text.index("GATE = ["): text.index("]", text.index("GATE = [")) + 1]
        for bad in (
            "marshall", "islands", "nitijela", "djibouti", "loi", "decret",
        ):
            if f'"{bad}"' in gate_slice:
                raise RuntimeError(f"non-KI token in GATE of {dst_name}: {bad}")
        for stem in GATE_STEMS:
            if f'"{stem}"' not in gate_slice:
                raise RuntimeError(f"missing English stem in GATE of {dst_name}: {stem}")
        for year in GATE_YEARS:
            if f'"{year}"' not in gate_slice:
                raise RuntimeError(f"missing year in GATE of {dst_name}: {year}")
        if '", "mh"' in text or '", "MH"' in text:
            raise RuntimeError(f"leftover mh query token in {dst_name}")
        if "rmiparliament.org" in text:
            raise RuntimeError(f"leftover rmiparliament.org in {dst_name}")
    # reject bare marshallislands leftovers
    scrub = text
    scrub = scrub.replace(WAVE_POS, "XX")
    scrub = scrub.replace(HOLD, "XX")
    scrub = scrub.replace(DEST_CHAIN, "XX")
    scrub = scrub.replace(SRC_CHAIN, "XX")
    scrub = scrub.replace(SRC_HOLD, "XX")
    scrub = scrub.replace(SRC_WAVE, "XX")
    scrub = scrub.replace("after-MH", "after-XX")
    scrub = scrub.replace("after MH ", "after XX ")
    scrub = scrub.replace("after_dj", "after_xx")
    scrub = scrub.replace("MH LIVE", "XX LIVE")
    scrub = scrub.replace("MH→", "XX→")
    if re.search(r"(?<![A-Za-z0-9_])marshallislands(?![A-Za-z0-9_])", scrub):
        m = re.search(r"(?<![A-Za-z0-9_])marshallislands(?![A-Za-z0-9_])", scrub)
        raise RuntimeError(
            f"leftover marshallislands in {dst_name}: ...{scrub[max(0, m.start()-20):m.start()+20]}..."
        )
    if re.search(r"(?<![A-Za-z])MH(?![A-Za-z])", scrub):
        m = re.search(r"(?<![A-Za-z])MH(?![A-Za-z])", scrub)
        raise RuntimeError(
            f"leftover MH in {dst_name}: ...{scrub[max(0, m.start()-30):m.start()+30]}..."
        )
    if "ipfs_marshallislands" in text:
        raise RuntimeError(f"leftover marshallislands path in {dst_name}")
    if "marshall_islands" in text or "ipfs_marshall_islands" in text:
        raise RuntimeError(f"underscore-between-marshall-islands in {dst_name}")
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
    if entry.get("slug") == "kiribati" or entry.get("iso2") == "KI":
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
            "iso2": "KI",
            "slug": "kiribati",
            "repo": "endomorphosis/ipfs_kiribati_laws",
            "years_attested": YEARS_ATTESTED,
            "gate_years": [int(y) for y in GATE_YEARS],
            "gate_stems": GATE_STEMS,
            "note": (
                f"KI FIRST_IR scaffold; tip MATCH {DST_TIP_SHORT}@165/3118; {HOLD}; "
                f"soft never-thin ON; SKIP_US; Italy BLOCKED; {WAVE_POS}; "
                f"English GATE ({len(GATE_YEARS)} years + {len(GATE_STEMS)} stems)"
            ),
            "status": "CLAIMED",
            "mode": "FIRST_IR",
            "wave_end": False,
        })
        break
else:
    raise RuntimeError("Kiribati/KI entry missing from wave JSON")

data["wave_status"] = "IN_PROGRESS_KI"
data["hold"] = HOLD
data["current"] = "kiribati"
data["do_not_start_next"] = "burundi"
wave.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print("updated wave JSON Kiribati entry")
print("GATE years", GATE_YEARS)
print("GATE stems", GATE_STEMS)
print("n_gate", len(GATE_YEARS) + len(GATE_STEMS))
print("HOLD", HOLD)
print("GATE language: English years+stems")
