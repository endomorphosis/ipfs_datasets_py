#!/usr/bin/env python3
"""Adapt the Somalia English memsafe FIRST_IR pack to Maldives MV tip 7c8f75f3868a.

English (Maldives); FIRST_IR; HOLD 0 STRICT after-SO (MV WAVE END).
Soft never-thin ON; SKIP_US; Italy BLOCKED. WAVE END of after_dj
(MH→…→SO LIVE → MV). GATE: attested years + English legal stems from
data/articles.parquet tip 7c8f75f3868a (English; include maldives/maldivian).
URL gazette.gov.mv / mira.gov.mv / gov.mv query-only, NOT GATE.
Source tip ac6aefed0dbe (Somalia English memsafe with data/ paths)
— keep language English (Maldives).
Keep data/articles.parquet + data/laws.parquet; agent-data not cient-data.
Do NOT start any next country after LIVE. Floors 2535 laws / 1678 articles
(laws > articles — both floors as given).
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
SRC_TIP_FULL = "ac6aefed0dbe007940d49b85d19917a98d2f8c0d"
SRC_TIP_SHORT = "ac6aefed0dbe"
DST_TIP_FULL = "7c8f75f3868a7168ab564df0c838458f921c14c3"
DST_TIP_SHORT = "7c8f75f3868a"
FLOOR_LAWS, FLOOR_ARTS = 2535, 1678
SRC_FLOOR_L, SRC_FLOOR_A = 77, 1833

# Sampled from data/articles.parquet @ 7c8f75f3868a (~10 years + English stems)
# Whole-word ASCII-fold FTS hits; laws=2535 articles=1678.
# Top years by doc hits; English legal stems (+ maldives/maldivian/ruling).
GATE_YEARS = [
    "2025", "2021", "2023", "2022", "2000",
    "2012", "2013", "2015", "2020", "2010",
]
GATE_STEMS = [
    "act", "article", "section", "law", "ordinance", "code", "republic",
    "maldives", "maldivian", "government", "person", "order", "ruling",
]
YEARS_ATTESTED = [int(y) for y in GATE_YEARS] + [
    2014, 2019, 2024, 2016, 2026, 2009, 2007, 2008, 2011, 1994,
]
GATE_NOTE_YEARS = "/".join(GATE_YEARS)
GATE_NOTE_STEMS = "/".join(GATE_STEMS)
HOLD = "HOLD 0 STRICT after-SO (MV WAVE END)"
WAVE_POS = (
    "WAVE END of after_dj wave "
    "(after MH→KI→BI→SZ→NU→GW→SR→GQ→GY→BJ→SO LIVE)"
)
DEST_CHAIN = "MV WAVE END"
SRC_HOLD = "HOLD 0 STRICT after-BJ (SO→MV)"
SRC_WAVE = (
    "after BJ LIVE of after_dj wave "
    "(…→BJ LIVE → SO → MV; NOT wave end)"
)
SRC_CHAIN = "SO→MV"

FILES = [
    ("somalia_soft_filter.py", "maldives_soft_filter.py"),
    (f"somalia_corpus_stream_{SRC_TIP_SHORT}.py", f"maldives_corpus_stream_{DST_TIP_SHORT}.py"),
    (f"somalia_encode_memsafe_{SRC_TIP_SHORT}.py", f"maldives_encode_memsafe_{DST_TIP_SHORT}.py"),
    (f"somalia_finish_from_emb_{SRC_TIP_SHORT}.py", f"maldives_finish_from_emb_{DST_TIP_SHORT}.py"),
    (f"somalia_stream_graph_parts_{SRC_TIP_SHORT}.py", f"maldives_stream_graph_parts_{DST_TIP_SHORT}.py"),
    (f"somalia_package_memsafe_{SRC_TIP_SHORT}.py", f"maldives_package_memsafe_{DST_TIP_SHORT}.py"),
    ("somalia_upload.py", "maldives_upload.py"),
    ("somalia_bm25_smoke.py", "maldives_bm25_smoke.py"),
    ("somalia_write_publish_report.py", "maldives_write_publish_report.py"),
    (f"somalia_orchestrator_{SRC_TIP_SHORT}.py", f"maldives_orchestrator_{DST_TIP_SHORT}.py"),
]


def adapt(text: str, dst_name: str) -> str:
    # Repair path corruption from prior adapts
    for bad in (
        "cient-data", "prent-data", "stent-data", "cvent-data", "scent-data",
        "carent-data", "yement-data", "djiboutient-data", "marshallislandsent-data",
        "kiribatient-data", "burundient-data", "eswatinient-data", "niueent-data",
        "guineabissauent-data", "surinameent-data", "equatorialguineaent-data",
        "guyanaent-data", "beninent-data", "somaliaent-data", "maldivesent-data",
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
    text = text.replace("after-BJ", "\x00AFTERSO\x00")
    text = text.replace("after BJ ", "\x00AFTERSO_SP\x00")
    text = text.replace("after_dj", "\x00AFTERDJ_US\x00")
    text = text.replace(
        "…→BJ LIVE → SO → MV",
        "\x00SRCCHAIN_FULL\x00",
    )
    text = text.replace("after BJ LIVE of \x00AFTERDJ_US\x00 wave", "\x00DESTWAVE_SHORT\x00")
    text = text.replace("after BJ LIVE of after_dj wave", "\x00DESTWAVE_SHORT\x00")
    text = text.replace("SO FIRST_IR", "\x00DESTFIRST\x00")
    text = text.replace("SO→MV", "\x00DESTCHAIN\x00")
    text = text.replace("NOT wave end", "\x00NOTWE\x00")

    reps = [
        (SRC_TIP_FULL, DST_TIP_FULL),
        (SRC_TIP_SHORT, DST_TIP_SHORT),
        ("endomorphosis/ipfs_somalia_laws", "endomorphosis/ipfs_maldives_laws"),
        ("justicedao/ipfs_somalia_laws_ir", "justicedao/ipfs_maldives_laws_ir"),
        ("ipfs_somalia_laws_ir", "ipfs_maldives_laws_ir"),
        ("ipfs_somalia_laws", "ipfs_maldives_laws"),
        # HOLD / wave restore
        ("\x00DESTHOLD\x00", HOLD),
        ("\x00DESTWAVE\x00", WAVE_POS),
        ("\x00DESTWAVE_SHORT\x00", WAVE_POS),
        ("\x00DESTCHAIN\x00", DEST_CHAIN),
        ("\x00SRCCHAIN_FULL\x00", "after MH→KI→BI→SZ→NU→GW→SR→GQ→GY→BJ→SO LIVE"),
        ("\x00AFTERSO\x00", "after-SO"),
        ("\x00AFTERSO_SP\x00", "after SO "),
        ("\x00DESTFIRST\x00", "MV FIRST_IR"),
        ("\x00NOTWE\x00", "WAVE END"),
        ("SO FIRST_IR (not wave end)", "MV FIRST_IR (WAVE END)"),
        ("www/parliament.gov.so", "www/gazette.gov.mv"),
        ("parliament.gov.so", "gazette.gov.mv"),
        ("www.parliament.gov.so", "www.gazette.gov.mv"),
        ("www/gov.so", "www/gov.mv"),
        ("gov.so", "gov.mv"),
        ("www.gov.so", "www.gov.mv"),
        # Language / country — keep English, swap country
        ("English (Somalia)", "English (Maldives)"),
        ("English Somalia", "English Maldives"),
        ("Somalia", "Maldives"),
        # slug / path forms BEFORE bare somalia
        ("somalia_ranked", "maldives_ranked"),
        ("somalia_gate", "maldives_gate"),
        ("somalia_pass", "maldives_pass"),
        ("somalia_encode_memsafe", "maldives_encode_memsafe"),
        ("somalia_package_memsafe", "maldives_package_memsafe"),
        ("somalia_corpus_stream", "maldives_corpus_stream"),
        ("somalia_encode_done", "maldives_encode_done"),
        ("somalia_filtered_", "maldives_filtered_"),
        ("somalia_", "maldives_"),
        # ISO whole-token / path forms only (SO already protected in HOLD)
        ('"SO"', '"MV"'),
        ("SO-attested", "MV-attested"),
        ("(SO)", "(MV)"),
        ('"so"', '"mv"'),
        # floors 77/1833 → 2535/1678 — compound ONLY first
        ("77/1833", "2535/1678"),
        ("77 / 1833", "2535 / 1678"),
        ("77, 1833", "2535, 1678"),
        ("FLOOR_LAWS, FLOOR_ARTS = 77, 1833", "FLOOR_LAWS, FLOOR_ARTS = 2535, 1678"),
        ('int(pack.get("n_laws") or 77)', 'int(pack.get("n_laws") or 2535)'),
        ('int(pack.get("n_articles") or 1833)', 'int(pack.get("n_articles") or 1678)'),
        ("@ 77/", "@ 2535/"),
        ("floor 77/", "floor 2535/"),
        ("(77/", "(2535/"),
        (" 1833", " 1678"),
        ("1833", "1678"),
        # bare 77 floor leftovers (avoid UUID c94b etc — only floor context left)
        ("= 77,", "= 2535,"),
        ("or 77)", "or 2535)"),
    ]
    for a, b in reps:
        text = text.replace(a, b)

    # Bare slug "somalia" → "maldives"
    text = re.sub(r"(?<![A-Za-z0-9_])somalia(?![A-Za-z0-9_])", "maldives", text)

    text = text.replace("\x00BM25\x00", "BM25").replace("\x00bm25\x00", "bm25")
    text = text.replace("\x00AFTERDJ_US\x00", "after_dj")
    text = text.replace("\x00DESTHOLD\x00", HOLD)
    text = text.replace("\x00DESTCHAIN\x00", DEST_CHAIN)
    text = text.replace("\x00DESTWAVE\x00", WAVE_POS)

    # display name / slug fixes
    text = text.replace('"name": "maldives"', '"name": "Maldives"')
    text = text.replace('"name": "Maldives"', '"name": "Maldives"')
    text = text.replace('"slug": "Maldives"', '"slug": "maldives"')
    text = text.replace('SLUG = "Maldives"', 'SLUG = "maldives"')
    text = text.replace('SLUG = "maldives"', 'SLUG = "maldives"')
    text = text.replace('"country": "Maldives"', '"country": "maldives"')
    text = text.replace('"country": "somalia"', '"country": "maldives"')

    # Ensure agent-data survived
    for bad in (
        "cient-data", "prent-data", "stent-data", "cvent-data", "scent-data",
        "carent-data", "yement-data", "djiboutient-data", "marshallislandsent-data",
        "kiribatient-data", "burundient-data", "eswatinient-data", "niueent-data",
        "guineabissauent-data", "surinameent-data", "equatorialguineaent-data",
        "guyanaent-data", "beninent-data", "somaliaent-data", "maldivesent-data",
    ):
        text = text.replace(f"/home/box/{bad}/", "/home/box/agent-data/")
        text = text.replace(bad, "agent-data")

    if dst_name == "maldives_bm25_smoke.py":
        start = text.index("GATE = [")
        end = text.index("]", start) + 1
        years_line = ", ".join(f'"{y}"' for y in GATE_YEARS)
        stems_line = ", ".join(f'"{s}"' for s in GATE_STEMS)
        gate = f"GATE = [\n    {years_line},\n    {stems_line},\n]"
        text = text[:start] + gate + text[end:]
        text = re.sub(
            r"QUERIES = GATE \+ \[[^\]]*\]",
            'QUERIES = GATE + ["www", "gov.mv", "www.gov.mv", "gazette.gov.mv", "www.gazette.gov.mv", "mira.gov.mv", "constitution", "minister", "parliament", "shall", "gazette"]',
            text,
            count=1,
        )
        text = re.sub(
            r'"""BM25 smoke for Maldives IR.*?"""',
            '"""BM25 smoke for Maldives IR — English legal corpus; years + English legal stems FTS gate.\n\n'
            "GATE is attested ASCII years plus English legal stems (ASCII-fold). URL www/gov.mv\n"
            "gazette.gov.mv / mira.gov.mv is query-only, never GATE. Every GATE token must rank a hit.\n"
            '"""',
            text,
            count=1,
            flags=re.S,
        )
        note = (
            f"attested years {GATE_NOTE_YEARS} plus English legal stems {GATE_NOTE_STEMS} "
            f"from articles.parquet HEAD tip {DST_TIP_SHORT}; URL www/gov.mv gazette.gov.mv "
            f"mira.gov.mv is query-only, not GATE."
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

    if dst_name == "maldives_write_publish_report.py":
        gate_note = (
            f"BM25 PASS on Maldives ASCII-fold English GATE "
            f"(attested years {GATE_NOTE_YEARS} + stems {GATE_NOTE_STEMS}); "
            f"URL www/gov.mv gazette.gov.mv mira.gov.mv is query-only, not GATE"
        )
        text = re.sub(
            r'BM25 PASS on Maldives[^"]*"',
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
        text = text.replace("www/gov.so is query-only", "www/gov.mv is query-only")
        text = text.replace("www/gov.mv is query-only", "www/gov.mv is query-only")
        text = re.sub(
            r"HOLD 0 STRICT after-BJ[^;]*; collectors kept dead \(pkill\); soft never-thin ON; SKIP_US; Italy BLOCKED;[^\"\n]*",
            f"{HOLD}; collectors kept dead (pkill); soft never-thin ON; SKIP_US; Italy BLOCKED; {WAVE_POS}",
            text,
        )
        text = re.sub(
            r"HOLD 0 STRICT after-SO[^;]*; collectors kept dead \(pkill\); soft never-thin ON; SKIP_US; Italy BLOCKED;[^\"\n]*",
            f"{HOLD}; collectors kept dead (pkill); soft never-thin ON; SKIP_US; Italy BLOCKED; {WAVE_POS}",
            text,
        )
        text = re.sub(r"[ \t]{2,}", " ", text)

    leftovers = (
        "Somalia", "somalia",
        "cient-data", "prent-data", "stent-data", "cvent-data", "scent-data",
        "carent-data", "yement-data", "djiboutient-data", "marshallislandsent-data",
        "kiribatient-data", "burundient-data", "eswatinient-data", "niueent-data",
        "guineabissauent-data", "surinameent-data", "equatorialguineaent-data",
        "guyanaent-data", "beninent-data", "somaliaent-data",
        "gov.so", "www.gov.so", "parliament.gov.so",
    )
    found = []
    for x in leftovers:
        if x == "somalia":
            if re.search(r"(?<![A-Za-z0-9_])somalia(?![A-Za-z0-9_])", text):
                found.append(x)
            continue
        if x in text:
            found.append(x)
    if found:
        raise RuntimeError(f"language/country leftovers in {dst_name}: {found}")

    # Reject non-MV tokens in GATE; require English stems
    if dst_name.endswith("_bm25_smoke.py"):
        gate_slice = text[text.index("GATE = ["): text.index("]", text.index("GATE = [")) + 1]
        for bad in (
            "somalia", "somali",
            "loi", "decret", "ordonnance", "republique", "benin", "gouvernement", "personne", "ministre",
            "articulo", "ley", "decreto", "codigo", "seccion",
            "artikel", "wet", "besluit", "persoon", "sectie", "republiek",
            "artigo", "lei",
        ):
            if f'"{bad}"' in gate_slice:
                raise RuntimeError(f"non-MV token in GATE of {dst_name}: {bad}")
        for stem in GATE_STEMS:
            if f'"{stem}"' not in gate_slice:
                raise RuntimeError(f"missing English stem in GATE of {dst_name}: {stem}")
        for year in GATE_YEARS:
            if f'"{year}"' not in gate_slice:
                raise RuntimeError(f"missing year in GATE of {dst_name}: {year}")
        if '", "so"' in text or '", "SO"' in text:
            raise RuntimeError(f"leftover so query token in {dst_name}")
        if "gov.so" in text:
            raise RuntimeError(f"leftover gov.so in {dst_name}")

    # reject bare somalia / SO leftovers outside protected HOLD/wave
    scrub = text
    scrub = scrub.replace(WAVE_POS, "XX")
    scrub = scrub.replace(HOLD, "XX")
    scrub = scrub.replace(DEST_CHAIN, "XX")
    scrub = scrub.replace(SRC_CHAIN, "XX")
    scrub = scrub.replace(SRC_HOLD, "XX")
    scrub = scrub.replace(SRC_WAVE, "XX")
    scrub = scrub.replace("after-SO", "after-XX")
    scrub = scrub.replace("after SO ", "after XX ")
    scrub = scrub.replace("after_dj", "after_xx")
    scrub = scrub.replace("SO LIVE", "XX LIVE")
    scrub = scrub.replace("→SO ", "→XX ")
    scrub = scrub.replace("BJ→SO", "BJ→XX")
    scrub = scrub.replace("MH→KI→BI→SZ→NU→GW→SR→GQ→GY→BJ→SO", "XXCHAIN")
    scrub = scrub.replace("SO→MV", "XX")
    if re.search(r"(?<![A-Za-z0-9_])somalia(?![A-Za-z0-9_])", scrub):
        m = re.search(r"(?<![A-Za-z0-9_])somalia(?![A-Za-z0-9_])", scrub)
        raise RuntimeError(
            f"leftover somalia in {dst_name}: ...{scrub[max(0, m.start()-20):m.start()+20]}..."
        )
    if re.search(r"(?<![A-Za-z%])SO(?![A-Za-z])", scrub):
        m = re.search(r"(?<![A-Za-z%])SO(?![A-Za-z])", scrub)
        raise RuntimeError(
            f"leftover SO in {dst_name}: ...{scrub[max(0, m.start()-30):m.start()+30]}..."
        )
    if "ipfs_somalia" in text:
        raise RuntimeError(f"leftover somalia path in {dst_name}")
    if "agent-data" not in text and "SECRET" in text.upper():
        if any(x in dst_name for x in ("soft_filter", "upload", "orchestrator")):
            if "/home/box/" in text and "agent-data" not in text:
                raise RuntimeError(f"missing agent-data secret path in {dst_name}")
    # data/ paths must survive
    if "soft_filter" in dst_name or "corpus_stream" in dst_name:
        if "data/laws.parquet" not in text and 'data" / "laws.parquet"' not in text:
            if '"data"' not in text and "/data/" not in text:
                raise RuntimeError(f"missing data/ parquet paths in {dst_name}")
    # tip integrity
    if SRC_TIP_SHORT in text:
        raise RuntimeError(f"src tip leftover in {dst_name}")
    if "67930c3f-c86b-" in text:
        raise RuntimeError(f"UUID c94b corrupted to c86b in {dst_name}")
    if DST_TIP_SHORT not in text and any(x in dst_name for x in ("soft_filter", "orchestrator", "bm25_smoke")):
        raise RuntimeError(f"missing DST tip in {dst_name}")
    # english language must remain for MV
    if "write_publish" in dst_name or "bm25_smoke" in dst_name:
        if re.search(r"ASCII-fold French|French legal", text):
            raise RuntimeError(f"leftover French phrasing in {dst_name}")
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
    if entry.get("slug") == "maldives" or entry.get("iso2") == "MV":
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
            "iso2": "MV",
            "slug": "maldives",
            "repo": "endomorphosis/ipfs_maldives_laws",
            "years_attested": YEARS_ATTESTED,
            "gate_years": [int(y) for y in GATE_YEARS],
            "gate_stems": GATE_STEMS,
            "note": (
                f"MV FIRST_IR scaffold; tip MATCH {DST_TIP_SHORT}@2535/1678; {HOLD}; "
                f"soft never-thin ON; SKIP_US; Italy BLOCKED; {WAVE_POS}; "
                f"English GATE ({len(GATE_YEARS)} years + {len(GATE_STEMS)} stems); WAVE END"
            ),
            "status": "CLAIMED",
            "mode": "FIRST_IR",
            "wave_end": True,
        })
        break
else:
    raise RuntimeError("Maldives/MV entry missing from wave JSON")

data["wave_status"] = "IN_PROGRESS_MV_WAVE_END"
data["hold"] = HOLD
data["current"] = "maldives"
data["do_not_start_next"] = None
data["next"] = None
data["wave_end_country"] = "maldives"
data["wave_end_note"] = (
    "MV is WAVE END of after_dj (MH→…→SO→MV). After LIVE: clear HOLD; "
    "set wave_status=COMPLETE; do NOT start any further country."
)
data["hold_note"] = "HOLD 0 STRICT for MV WAVE END build in progress; collectors/deepeners dead"
wave.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print("updated wave JSON Maldives entry")
print("GATE years", GATE_YEARS)
print("GATE stems", GATE_STEMS)
print("n_gate", len(GATE_YEARS) + len(GATE_STEMS))
print("HOLD", HOLD)
print("GATE language: English years+stems")
