#!/usr/bin/env python3
"""Adapt the Equatorial Guinea Spanish memsafe FIRST_IR pack to Guyana GY tip b0752848c53b.

English (Guyana); FIRST_IR; HOLD 0 STRICT after-GQ (GY→BJ→SO→MV).
Soft never-thin ON; SKIP_US; Italy BLOCKED. WAVE after_dj after GQ LIVE
(…→GQ LIVE → GY → BJ→SO→MV), NOT wave end.
GATE: attested years + English legal stems from data/articles.parquet tip b0752848c53b
(English; include guyana). URL parliament.gov.gy / gov.gy query-only, NOT GATE.
Source tip 6d86d0c7e604 (Equatorial Guinea Spanish memsafe with data/ paths)
— override language Spanish → English (Guyana).
Keep data/articles.parquet + data/laws.parquet; agent-data not cient-data.
Do NOT start Benin/next after LIVE.
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
SRC_TIP_FULL = "6d86d0c7e6046f3b549614b9f1dcbb571020e581"
SRC_TIP_SHORT = "6d86d0c7e604"
DST_TIP_FULL = "b0752848c53bef3de692ce00dcba7b9a46ed3401"
DST_TIP_SHORT = "b0752848c53b"
FLOOR_LAWS, FLOOR_ARTS = 200, 2029
SRC_FLOOR_L, SRC_FLOOR_A = 86, 2041

# Sampled from data/articles.parquet @ b0752848c53b (~10 years + English stems)
# Whole-word ASCII-fold FTS hits; laws=200 articles=2029.
# Top years by doc hits; English legal stems (+ guyana country).
GATE_YEARS = [
    "1966", "1974", "1975", "1967", "1968",
    "2012", "1970", "1976", "1965", "1964",
]
GATE_STEMS = [
    "act", "article", "section", "law", "ordinance", "code",
    "republic", "guyana", "government", "person", "order",
]
YEARS_ATTESTED = [int(y) for y in GATE_YEARS] + [
    2000, 1973, 1962, 2001, 1957, 2010, 1990, 1980, 2005, 2015,
]
GATE_NOTE_YEARS = "/".join(GATE_YEARS)
GATE_NOTE_STEMS = "/".join(GATE_STEMS)
HOLD = "HOLD 0 STRICT after-GQ (GY→BJ→SO→MV)"
WAVE_POS = (
    "after GQ LIVE of after_dj wave "
    "(…→GQ LIVE → GY → BJ→SO→MV; NOT wave end)"
)
DEST_CHAIN = "GY→BJ→SO→MV"
SRC_HOLD = "HOLD 0 STRICT after-SR (GQ→GY→BJ→SO→MV)"
SRC_WAVE = (
    "after SR LIVE of after_dj wave "
    "(…→SR LIVE → GQ → GY→BJ→SO→MV; NOT wave end)"
)
SRC_CHAIN = "GQ→GY→BJ→SO→MV"

FILES = [
    ("equatorialguinea_soft_filter.py", "guyana_soft_filter.py"),
    (f"equatorialguinea_corpus_stream_{SRC_TIP_SHORT}.py", f"guyana_corpus_stream_{DST_TIP_SHORT}.py"),
    (f"equatorialguinea_encode_memsafe_{SRC_TIP_SHORT}.py", f"guyana_encode_memsafe_{DST_TIP_SHORT}.py"),
    (f"equatorialguinea_finish_from_emb_{SRC_TIP_SHORT}.py", f"guyana_finish_from_emb_{DST_TIP_SHORT}.py"),
    (f"equatorialguinea_stream_graph_parts_{SRC_TIP_SHORT}.py", f"guyana_stream_graph_parts_{DST_TIP_SHORT}.py"),
    (f"equatorialguinea_package_memsafe_{SRC_TIP_SHORT}.py", f"guyana_package_memsafe_{DST_TIP_SHORT}.py"),
    ("equatorialguinea_upload.py", "guyana_upload.py"),
    ("equatorialguinea_bm25_smoke.py", "guyana_bm25_smoke.py"),
    ("equatorialguinea_write_publish_report.py", "guyana_write_publish_report.py"),
    (f"equatorialguinea_orchestrator_{SRC_TIP_SHORT}.py", f"guyana_orchestrator_{DST_TIP_SHORT}.py"),
]


def adapt(text: str, dst_name: str) -> str:
    # Repair path corruption from prior adapts
    for bad in (
        "cient-data", "prent-data", "stent-data", "cvent-data", "scent-data",
        "carent-data", "yement-data", "djiboutient-data", "marshallislandsent-data",
        "kiribatient-data", "burundient-data", "eswatinient-data", "niueent-data",
        "guineabissauent-data", "surinameent-data", "equatorialguineaent-data",
        "guyanaent-data",
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
    text = text.replace("after-SR", "\x00AFTERGQ\x00")
    text = text.replace("after SR ", "\x00AFTERGQ_SP\x00")
    text = text.replace("after_dj", "\x00AFTERDJ_US\x00")
    text = text.replace(
        "…→SR LIVE → GQ → GY→BJ→SO→MV",
        "\x00SRCCHAIN_FULL\x00",
    )
    text = text.replace("after SR LIVE of \x00AFTERDJ_US\x00 wave", "\x00DESTWAVE_SHORT\x00")
    text = text.replace("after SR LIVE of after_dj wave", "\x00DESTWAVE_SHORT\x00")
    text = text.replace("GQ FIRST_IR", "\x00DESTFIRST\x00")

    reps = [
        (SRC_TIP_FULL, DST_TIP_FULL),
        (SRC_TIP_SHORT, DST_TIP_SHORT),
        ("endomorphosis/ipfs_equatorialguinea_laws", "endomorphosis/ipfs_guyana_laws"),
        ("justicedao/ipfs_equatorialguinea_laws_ir", "justicedao/ipfs_guyana_laws_ir"),
        ("ipfs_equatorialguinea_laws_ir", "ipfs_guyana_laws_ir"),
        ("ipfs_equatorialguinea_laws", "ipfs_guyana_laws"),
        # HOLD / wave restore
        ("\x00DESTHOLD\x00", HOLD),
        ("\x00DESTWAVE\x00", WAVE_POS),
        ("\x00DESTWAVE_SHORT\x00", WAVE_POS),
        ("\x00DESTCHAIN\x00", DEST_CHAIN),
        ("\x00SRCCHAIN_FULL\x00", "…→GQ LIVE → GY → BJ→SO→MV"),
        ("\x00AFTERGQ\x00", "after-GQ"),
        ("\x00AFTERGQ_SP\x00", "after GQ "),
        ("\x00DESTFIRST\x00", "GY FIRST_IR"),
        ("GQ FIRST_IR (not wave end)", "GY FIRST_IR (not wave end)"),
        ("www/gob.gq", "www/parliament.gov.gy"),
        ("gob.gq", "gov.gy"),
        ("www.gob.gq", "www.gov.gy"),
        ("boe.gob.gq", "parliament.gov.gy"),
        ("www.boe.gob.gq", "www.parliament.gov.gy"),
        # Language / country — Spanish → English BEFORE bare Equatorial Guinea
        ("Spanish (Equatorial Guinea)", "English (Guyana)"),
        ("Spanish Equatorial Guinea", "English Guyana"),
        ("ASCII-fold Spanish", "ASCII-fold English"),
        ("Spanish legal stems", "English legal stems"),
        ("Spanish legal corpus", "English legal corpus"),
        ("Spanish years+stems GATE", "English years+stems GATE"),
        ("Spanish GATE", "English GATE"),
        ("language: Spanish", "language: English"),
        ("Language: Spanish", "Language: English"),
        ('"language": "Spanish"', '"language": "English"'),
        ('"lang": "Spanish"', '"lang": "English"'),
        ("Equatorial Guinea", "Guyana"),
        # slug / path forms BEFORE bare equatorialguinea
        ("equatorialguinea_ranked", "guyana_ranked"),
        ("equatorialguinea_gate", "guyana_gate"),
        ("equatorialguinea_pass", "guyana_pass"),
        ("equatorialguinea_encode_memsafe", "guyana_encode_memsafe"),
        ("equatorialguinea_package_memsafe", "guyana_package_memsafe"),
        ("equatorialguinea_corpus_stream", "guyana_corpus_stream"),
        ("equatorialguinea_encode_done", "guyana_encode_done"),
        ("equatorialguinea_filtered_", "guyana_filtered_"),
        ("equatorialguinea_", "guyana_"),
        # ISO whole-token / path forms only (GQ already protected in HOLD)
        ('"GQ"', '"GY"'),
        ("GQ-attested", "GY-attested"),
        ("(GQ)", "(GY)"),
        ('"gq"', '"gy"'),
        # floors 86/2041 → 200/2029 — compound ONLY (tip has 86; UUID safe)
        ("86/2041", "200/2029"),
        ("86 / 2041", "200 / 2029"),
        ("86, 2041", "200, 2029"),
        ("FLOOR_LAWS, FLOOR_ARTS = 86, 2041", "FLOOR_LAWS, FLOOR_ARTS = 200, 2029"),
        ('int(pack.get("n_laws") or 86)', 'int(pack.get("n_laws") or 200)'),
        ('int(pack.get("n_articles") or 2041)', 'int(pack.get("n_articles") or 2029)'),
        ("@ 86/", "@ 200/"),
        ("floor 86/", "floor 200/"),
        ("(86/", "(200/"),
        (" 2041", " 2029"),
        ("2041", "2029"),
    ]
    for a, b in reps:
        text = text.replace(a, b)

    # Bare slug "equatorialguinea" → "guyana"
    text = re.sub(r"(?<![A-Za-z0-9_])equatorialguinea(?![A-Za-z0-9_])", "guyana", text)

    text = text.replace("\x00BM25\x00", "BM25").replace("\x00bm25\x00", "bm25")
    text = text.replace("\x00AFTERDJ_US\x00", "after_dj")
    text = text.replace("\x00DESTHOLD\x00", HOLD)
    text = text.replace("\x00DESTCHAIN\x00", DEST_CHAIN)
    text = text.replace("\x00DESTWAVE\x00", WAVE_POS)

    # display name / slug fixes
    text = text.replace('"name": "guyana"', '"name": "Guyana"')
    text = text.replace('"name": "Guyana"', '"name": "Guyana"')
    text = text.replace('"slug": "Guyana"', '"slug": "guyana"')
    text = text.replace('SLUG = "Guyana"', 'SLUG = "guyana"')
    text = text.replace('SLUG = "guyana"', 'SLUG = "guyana"')
    text = text.replace('"country": "Guyana"', '"country": "guyana"')
    text = text.replace('"country": "equatorialguinea"', '"country": "guyana"')

    # Ensure agent-data survived
    for bad in (
        "cient-data", "prent-data", "stent-data", "cvent-data", "scent-data",
        "carent-data", "yement-data", "djiboutient-data", "marshallislandsent-data",
        "kiribatient-data", "burundient-data", "eswatinient-data", "niueent-data",
        "guineabissauent-data", "surinameent-data", "equatorialguineaent-data",
        "guyanaent-data",
    ):
        text = text.replace(f"/home/box/{bad}/", "/home/box/agent-data/")
        text = text.replace(bad, "agent-data")

    if dst_name == "guyana_bm25_smoke.py":
        start = text.index("GATE = [")
        end = text.index("]", start) + 1
        years_line = ", ".join(f'"{y}"' for y in GATE_YEARS)
        stems_line = ", ".join(f'"{s}"' for s in GATE_STEMS)
        gate = f"GATE = [\n    {years_line},\n    {stems_line},\n]"
        text = text[:start] + gate + text[end:]
        text = re.sub(
            r"QUERIES = GATE \+ \[[^\]]*\]",
            'QUERIES = GATE + ["www", "gov.gy", "www.gov.gy", "parliament.gov.gy", "www.parliament.gov.gy", "constitution", "minister", "parliament", "shall", "ordinance"]',
            text,
            count=1,
        )
        text = re.sub(
            r'"""BM25 smoke for Guyana IR.*?"""',
            '"""BM25 smoke for Guyana IR — English legal corpus; years + English legal stems FTS gate.\n\n'
            "GATE is attested ASCII years plus English legal stems (ASCII-fold). URL www/gov.gy\n"
            "is query-only, never GATE. Every GATE token must rank a hit.\n"
            '"""',
            text,
            count=1,
            flags=re.S,
        )
        note = (
            f"attested years {GATE_NOTE_YEARS} plus English legal stems {GATE_NOTE_STEMS} "
            f"from articles.parquet HEAD tip {DST_TIP_SHORT}; URL www/gov.gy is query-only, not GATE."
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

    if dst_name == "guyana_write_publish_report.py":
        gate_note = (
            f"BM25 PASS on Guyana ASCII-fold English GATE "
            f"(attested years {GATE_NOTE_YEARS} + stems {GATE_NOTE_STEMS}); "
            f"URL www/gov.gy is query-only, not GATE"
        )
        text = re.sub(
            r'BM25 PASS on Guyana[^"]*"',
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
        text = text.replace("Spanish years+stems GATE", "English years+stems GATE")
        text = text.replace("Dutch years+stems GATE", "English years+stems GATE")
        text = text.replace("Spanish legal stems GATE", "English years+stems GATE")
        text = re.sub(
            r"HOLD 0 STRICT after-SR[^;]*; collectors kept dead \(pkill\); soft never-thin ON; SKIP_US; Italy BLOCKED;[^\"\n]*",
            f"{HOLD}; collectors kept dead (pkill); soft never-thin ON; SKIP_US; Italy BLOCKED; {WAVE_POS}",
            text,
        )
        text = re.sub(
            r"HOLD 0 STRICT after-GQ[^;]*; collectors kept dead \(pkill\); soft never-thin ON; SKIP_US; Italy BLOCKED;[^\"\n]*",
            f"{HOLD}; collectors kept dead (pkill); soft never-thin ON; SKIP_US; Italy BLOCKED; {WAVE_POS}",
            text,
        )
        text = text.replace("www/gob.gq is query-only", "www/gov.gy is query-only")
        text = text.replace("www/gov.gy is query-only", "www/gov.gy is query-only")
        text = re.sub(r"[ \t]{2,}", " ", text)

    leftovers = (
        "Equatorial Guinea", "equatorialguinea",
        "cient-data", "prent-data", "stent-data", "cvent-data", "scent-data",
        "carent-data", "yement-data", "djiboutient-data", "marshallislandsent-data",
        "kiribatient-data", "burundient-data", "eswatinient-data", "niueent-data",
        "guineabissauent-data", "surinameent-data", "equatorialguineaent-data",
        "gob.gq", "www.gob.gq", "boe.gob.gq",
        "Spanish",
    )
    found = []
    for x in leftovers:
        if x == "equatorialguinea":
            if re.search(r"(?<![A-Za-z0-9_])equatorialguinea(?![A-Za-z0-9_])", text):
                found.append(x)
            continue
        if x == "Spanish":
            if "Spanish" in text:
                found.append(x)
            continue
        if x in text:
            found.append(x)
    if found:
        raise RuntimeError(f"language/country leftovers in {dst_name}: {found}")

    # Reject Spanish leftovers in GATE; require English stems
    if dst_name.endswith("_bm25_smoke.py"):
        gate_slice = text[text.index("GATE = ["): text.index("]", text.index("GATE = [")) + 1]
        for bad in (
            "equatorialguinea", "articulo", "ley", "decreto", "codigo", "seccion",
            "gobierno", "persona", "republica", "estado", "guinea", "ecuatorial",
            "artikel", "wet", "besluit", "persoon", "sectie", "republiek",
            "artigo", "lei", "puerto", "asociado",
            "loi", "decret", "ministre",
        ):
            if f'"{bad}"' in gate_slice:
                raise RuntimeError(f"non-GY token in GATE of {dst_name}: {bad}")
        for stem in GATE_STEMS:
            if f'"{stem}"' not in gate_slice:
                raise RuntimeError(f"missing English stem in GATE of {dst_name}: {stem}")
        for year in GATE_YEARS:
            if f'"{year}"' not in gate_slice:
                raise RuntimeError(f"missing year in GATE of {dst_name}: {year}")
        if '", "gq"' in text or '", "GQ"' in text:
            raise RuntimeError(f"leftover gq query token in {dst_name}")
        if "gob.gq" in text:
            raise RuntimeError(f"leftover gob.gq in {dst_name}")
        if re.search(r"Spanish legal", text):
            raise RuntimeError(f"leftover Spanish legal phrasing in {dst_name}")

    # reject bare equatorialguinea / GQ leftovers outside protected HOLD/wave
    scrub = text
    scrub = scrub.replace(WAVE_POS, "XX")
    scrub = scrub.replace(HOLD, "XX")
    scrub = scrub.replace(DEST_CHAIN, "XX")
    scrub = scrub.replace(SRC_CHAIN, "XX")
    scrub = scrub.replace(SRC_HOLD, "XX")
    scrub = scrub.replace(SRC_WAVE, "XX")
    scrub = scrub.replace("after-GQ", "after-XX")
    scrub = scrub.replace("after GQ ", "after XX ")
    scrub = scrub.replace("after_dj", "after_xx")
    scrub = scrub.replace("GQ LIVE", "XX LIVE")
    scrub = scrub.replace("GQ→", "XX→")
    scrub = scrub.replace("…→GQ", "…→XX")
    if re.search(r"(?<![A-Za-z0-9_])equatorialguinea(?![A-Za-z0-9_])", scrub):
        m = re.search(r"(?<![A-Za-z0-9_])equatorialguinea(?![A-Za-z0-9_])", scrub)
        raise RuntimeError(
            f"leftover equatorialguinea in {dst_name}: ...{scrub[max(0, m.start()-20):m.start()+20]}..."
        )
    if re.search(r"(?<![A-Za-z%])GQ(?![A-Za-z])", scrub):
        m = re.search(r"(?<![A-Za-z%])GQ(?![A-Za-z])", scrub)
        raise RuntimeError(
            f"leftover GQ in {dst_name}: ...{scrub[max(0, m.start()-30):m.start()+30]}..."
        )
    if "ipfs_equatorialguinea" in text:
        raise RuntimeError(f"leftover equatorialguinea path in {dst_name}")
    if "agent-data" not in text and "SECRET" in text.upper():
        if any(x in dst_name for x in ("soft_filter", "upload", "orchestrator")):
            if "/home/box/" in text and "agent-data" not in text:
                raise RuntimeError(f"missing agent-data secret path in {dst_name}")
    # data/ paths must survive
    if "soft_filter" in dst_name or "corpus_stream" in dst_name:
        if "data/laws.parquet" not in text and 'data" / "laws.parquet"' not in text:
            if '"data"' not in text and "/data/" not in text:
                raise RuntimeError(f"missing data/ parquet paths in {dst_name}")
    # reject residual Spanish GATE language labels in publish/smoke
    if "write_publish" in dst_name or "bm25_smoke" in dst_name:
        if re.search(r"ASCII-fold Spanish", text):
            raise RuntimeError(f"leftover ASCII-fold Spanish in {dst_name}")
        if re.search(r"Spanish legal (stems|corpus)", text):
            raise RuntimeError(f"leftover Spanish legal phrasing in {dst_name}")
    # tip integrity
    if DST_TIP_SHORT not in text and ("TIP" in text or "tip" in text):
        if any(x in dst_name for x in ("soft_filter", "orchestrator", "bm25_smoke", "corpus", "encode", "package", "finish", "stream_graph", "upload", "write_publish")):
            if "TIP_SHORT" in text or "TIP_FULL" in text or "tip" in text.lower():
                if DST_TIP_SHORT not in text and SRC_TIP_SHORT in text:
                    raise RuntimeError(f"src tip leftover in {dst_name}")
    if "6d86d0c7e604" in text or "b0752848c86" in text or "b02002848c53b" in text:
        # allow src tip only if somehow residual — reject
        if SRC_TIP_SHORT in text:
            raise RuntimeError(f"src tip leftover in {dst_name}")
    if "67930c3f-c86b-" in text:
        raise RuntimeError(f"UUID c94b corrupted to c86b in {dst_name}")
    # floor 200 must not corrupt tip (tip has no 200)
    if "b0752848c53b" not in text and any(x in dst_name for x in ("soft_filter", "orchestrator", "bm25_smoke")):
        raise RuntimeError(f"missing DST tip in {dst_name}")
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
    if entry.get("slug") == "guyana" or entry.get("iso2") == "GY":
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
            "iso2": "GY",
            "slug": "guyana",
            "repo": "endomorphosis/ipfs_guyana_laws",
            "years_attested": YEARS_ATTESTED,
            "gate_years": [int(y) for y in GATE_YEARS],
            "gate_stems": GATE_STEMS,
            "note": (
                f"GY FIRST_IR scaffold; tip MATCH {DST_TIP_SHORT}@200/2029; {HOLD}; "
                f"soft never-thin ON; SKIP_US; Italy BLOCKED; {WAVE_POS}; "
                f"English GATE ({len(GATE_YEARS)} years + {len(GATE_STEMS)} stems)"
            ),
            "status": "CLAIMED",
            "mode": "FIRST_IR",
            "wave_end": False,
        })
        break
else:
    raise RuntimeError("Guyana/GY entry missing from wave JSON")

data["wave_status"] = "IN_PROGRESS_GY"
data["hold"] = HOLD
data["current"] = "guyana"
data["do_not_start_next"] = "benin"
data["next"] = "benin"
wave.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print("updated wave JSON Guyana entry")
print("GATE years", GATE_YEARS)
print("GATE stems", GATE_STEMS)
print("n_gate", len(GATE_YEARS) + len(GATE_STEMS))
print("HOLD", HOLD)
print("GATE language: English years+stems")
