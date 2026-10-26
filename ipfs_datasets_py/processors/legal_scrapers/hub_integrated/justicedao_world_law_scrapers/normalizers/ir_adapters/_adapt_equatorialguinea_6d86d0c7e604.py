#!/usr/bin/env python3
"""Adapt the Suriname Dutch memsafe FIRST_IR pack to Equatorial Guinea GQ tip 6d86d0c7e604.

Spanish (Equatorial Guinea); FIRST_IR; HOLD 0 STRICT after-SR (GQ→GY→BJ→SO→MV).
Soft never-thin ON; SKIP_US; Italy BLOCKED. WAVE after_dj after SR LIVE
(…→SR LIVE → GQ → GY→BJ→SO→MV), NOT wave end.
GATE: attested years + Spanish legal stems from data/articles.parquet tip 6d86d0c7e604
(Spanish; include guinea/ecuatorial). URL gob.gq / boe.gob.gq query-only, NOT GATE.
Source tip ca87c3f430c5 (Suriname Dutch memsafe with data/ paths)
— override language Dutch → Spanish (Equatorial Guinea).
Keep data/articles.parquet + data/laws.parquet; agent-data not cient-data.
Do NOT start Guyana/next after LIVE.
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
SRC_TIP_FULL = "ca87c3f430c5cec11da9990f4112d7ef4f1986cc"
SRC_TIP_SHORT = "ca87c3f430c5"
DST_TIP_FULL = "6d86d0c7e6046f3b549614b9f1dcbb571020e581"
DST_TIP_SHORT = "6d86d0c7e604"
FLOOR_LAWS, FLOOR_ARTS = 86, 2041
SRC_FLOOR_L, SRC_FLOOR_A = 94, 2164

# Sampled from data/articles.parquet @ 6d86d0c7e604 (~10 years + ~11 Spanish stems)
# Whole-word ASCII-fold FTS hits; laws=86 articles=2041.
# Top years by doc hits; Spanish legal stems (+ guinea/ecuatorial country).
GATE_YEARS = [
    "2017", "2015", "2023", "2020", "2018",
    "2021", "2014", "2012", "2016", "2013",
]
GATE_STEMS = [
    "articulo", "ley", "decreto", "codigo", "seccion", "gobierno",
    "persona", "republica", "estado", "guinea", "ecuatorial",
]
YEARS_ATTESTED = [int(y) for y in GATE_YEARS] + [
    2022, 2008, 2019, 2004, 2000, 1968, 2001, 2024, 1995, 2009,
]
GATE_NOTE_YEARS = "/".join(GATE_YEARS)
GATE_NOTE_STEMS = "/".join(GATE_STEMS)
HOLD = "HOLD 0 STRICT after-SR (GQ→GY→BJ→SO→MV)"
WAVE_POS = (
    "after SR LIVE of after_dj wave "
    "(…→SR LIVE → GQ → GY→BJ→SO→MV; NOT wave end)"
)
DEST_CHAIN = "GQ→GY→BJ→SO→MV"
SRC_HOLD = "HOLD 0 STRICT after-GW (SR→GQ→GY→BJ→SO→MV)"
SRC_WAVE = (
    "after GW LIVE of after_dj wave "
    "(…→GW LIVE → SR → GQ→GY→BJ→SO→MV; NOT wave end)"
)
SRC_CHAIN = "SR→GQ→GY→BJ→SO→MV"

FILES = [
    ("suriname_soft_filter.py", "equatorialguinea_soft_filter.py"),
    (f"suriname_corpus_stream_{SRC_TIP_SHORT}.py", f"equatorialguinea_corpus_stream_{DST_TIP_SHORT}.py"),
    (f"suriname_encode_memsafe_{SRC_TIP_SHORT}.py", f"equatorialguinea_encode_memsafe_{DST_TIP_SHORT}.py"),
    (f"suriname_finish_from_emb_{SRC_TIP_SHORT}.py", f"equatorialguinea_finish_from_emb_{DST_TIP_SHORT}.py"),
    (f"suriname_stream_graph_parts_{SRC_TIP_SHORT}.py", f"equatorialguinea_stream_graph_parts_{DST_TIP_SHORT}.py"),
    (f"suriname_package_memsafe_{SRC_TIP_SHORT}.py", f"equatorialguinea_package_memsafe_{DST_TIP_SHORT}.py"),
    ("suriname_upload.py", "equatorialguinea_upload.py"),
    ("suriname_bm25_smoke.py", "equatorialguinea_bm25_smoke.py"),
    ("suriname_write_publish_report.py", "equatorialguinea_write_publish_report.py"),
    (f"suriname_orchestrator_{SRC_TIP_SHORT}.py", f"equatorialguinea_orchestrator_{DST_TIP_SHORT}.py"),
]


def adapt(text: str, dst_name: str) -> str:
    # Repair path corruption from prior adapts
    for bad in (
        "cient-data", "prent-data", "stent-data", "cvent-data", "scent-data",
        "carent-data", "yement-data", "djiboutient-data", "marshallislandsent-data",
        "kiribatient-data", "burundient-data", "eswatinient-data", "niueent-data",
        "guineabissauent-data", "surinameent-data", "equatorialguineaent-data",
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
    text = text.replace("after-GW", "\x00AFTERSR\x00")
    text = text.replace("after GW ", "\x00AFTERSR_SP\x00")
    text = text.replace("after_dj", "\x00AFTERDJ_US\x00")
    text = text.replace(
        "…→GW LIVE → SR → GQ→GY→BJ→SO→MV",
        "\x00SRCCHAIN_FULL\x00",
    )
    text = text.replace("after GW LIVE of \x00AFTERDJ_US\x00 wave", "\x00DESTWAVE_SHORT\x00")
    text = text.replace("after GW LIVE of after_dj wave", "\x00DESTWAVE_SHORT\x00")
    text = text.replace("SR FIRST_IR", "\x00DESTFIRST\x00")

    reps = [
        (SRC_TIP_FULL, DST_TIP_FULL),
        (SRC_TIP_SHORT, DST_TIP_SHORT),
        ("endomorphosis/ipfs_suriname_laws", "endomorphosis/ipfs_equatorialguinea_laws"),
        ("justicedao/ipfs_suriname_laws_ir", "justicedao/ipfs_equatorialguinea_laws_ir"),
        ("ipfs_suriname_laws_ir", "ipfs_equatorialguinea_laws_ir"),
        ("ipfs_suriname_laws", "ipfs_equatorialguinea_laws"),
        # HOLD / wave restore
        ("\x00DESTHOLD\x00", HOLD),
        ("\x00DESTWAVE\x00", WAVE_POS),
        ("\x00DESTWAVE_SHORT\x00", WAVE_POS),
        ("\x00DESTCHAIN\x00", DEST_CHAIN),
        ("\x00SRCCHAIN_FULL\x00", "…→SR LIVE → GQ → GY→BJ→SO→MV"),
        ("\x00AFTERSR\x00", "after-SR"),
        ("\x00AFTERSR_SP\x00", "after SR "),
        ("\x00DESTFIRST\x00", "GQ FIRST_IR"),
        ("SR FIRST_IR (not wave end)", "GQ FIRST_IR (not wave end)"),
        ("www/gov.sr", "www/gob.gq"),
        ("gov.sr", "gob.gq"),
        ("www.gov.sr", "www.gob.gq"),
        ("dna.sr", "boe.gob.gq"),
        ("www.dna.sr", "www.boe.gob.gq"),
        # Language / country — Dutch → Spanish BEFORE bare Suriname
        ("Dutch (Suriname)", "Spanish (Equatorial Guinea)"),
        ("Dutch Suriname", "Spanish Equatorial Guinea"),
        ("ASCII-fold Dutch", "ASCII-fold Spanish"),
        ("Dutch legal stems", "Spanish legal stems"),
        ("Dutch legal corpus", "Spanish legal corpus"),
        ("Dutch years+stems GATE", "Spanish years+stems GATE"),
        ("Dutch GATE", "Spanish GATE"),
        ("language: Dutch", "language: Spanish"),
        ("Language: Dutch", "Language: Spanish"),
        ('"language": "Dutch"', '"language": "Spanish"'),
        ('"lang": "Dutch"', '"lang": "Spanish"'),
        ("Suriname", "Equatorial Guinea"),
        # slug / path forms BEFORE bare suriname
        ("suriname_ranked", "equatorialguinea_ranked"),
        ("suriname_gate", "equatorialguinea_gate"),
        ("suriname_pass", "equatorialguinea_pass"),
        ("suriname_encode_memsafe", "equatorialguinea_encode_memsafe"),
        ("suriname_package_memsafe", "equatorialguinea_package_memsafe"),
        ("suriname_corpus_stream", "equatorialguinea_corpus_stream"),
        ("suriname_encode_done", "equatorialguinea_encode_done"),
        ("suriname_filtered_", "equatorialguinea_filtered_"),
        ("suriname_", "equatorialguinea_"),
        # ISO whole-token / path forms only (SR already protected in HOLD)
        ('"SR"', '"GQ"'),
        ("SR-attested", "GQ-attested"),
        ("(SR)", "(GQ)"),
        ('"sr"', '"gq"'),
        # floors 94/2164 → 86/2041 — compound ONLY (tip has 86; UUID has 94)
        ("94/2164", "86/2041"),
        ("94 / 2164", "86 / 2041"),
        ("94, 2164", "86, 2041"),
        ("FLOOR_LAWS, FLOOR_ARTS = 94, 2164", "FLOOR_LAWS, FLOOR_ARTS = 86, 2041"),
        ('int(pack.get("n_laws") or 94)', 'int(pack.get("n_laws") or 86)'),
        ('int(pack.get("n_articles") or 2164)', 'int(pack.get("n_articles") or 2041)'),
        ("@ 94/", "@ 86/"),
        ("floor 94/", "floor 86/"),
        ("(94/", "(86/"),
        (" 2164", " 2041"),
        ("2164", "2041"),
    ]
    for a, b in reps:
        text = text.replace(a, b)

    # Bare slug "suriname" → "equatorialguinea"
    text = re.sub(r"(?<![A-Za-z0-9_])suriname(?![A-Za-z0-9_])", "equatorialguinea", text)

    text = text.replace("\x00BM25\x00", "BM25").replace("\x00bm25\x00", "bm25")
    text = text.replace("\x00AFTERDJ_US\x00", "after_dj")
    text = text.replace("\x00DESTHOLD\x00", HOLD)
    text = text.replace("\x00DESTCHAIN\x00", DEST_CHAIN)
    text = text.replace("\x00DESTWAVE\x00", WAVE_POS)

    # display name / slug fixes
    text = text.replace('"name": "equatorialguinea"', '"name": "Equatorial Guinea"')
    text = text.replace('"name": "Equatorial Guinea"', '"name": "Equatorial Guinea"')
    text = text.replace('"slug": "Equatorial Guinea"', '"slug": "equatorialguinea"')
    text = text.replace('SLUG = "Equatorial Guinea"', 'SLUG = "equatorialguinea"')
    text = text.replace('SLUG = "equatorialguinea"', 'SLUG = "equatorialguinea"')
    text = text.replace('"country": "Equatorial Guinea"', '"country": "equatorialguinea"')
    text = text.replace('"country": "suriname"', '"country": "equatorialguinea"')

    # Ensure agent-data survived
    for bad in (
        "cient-data", "prent-data", "stent-data", "cvent-data", "scent-data",
        "carent-data", "yement-data", "djiboutient-data", "marshallislandsent-data",
        "kiribatient-data", "burundient-data", "eswatinient-data", "niueent-data",
        "guineabissauent-data", "surinameent-data", "equatorialguineaent-data",
    ):
        text = text.replace(f"/home/box/{bad}/", "/home/box/agent-data/")
        text = text.replace(bad, "agent-data")

    if dst_name == "equatorialguinea_bm25_smoke.py":
        start = text.index("GATE = [")
        end = text.index("]", start) + 1
        years_line = ", ".join(f'"{y}"' for y in GATE_YEARS)
        stems_line = ", ".join(f'"{s}"' for s in GATE_STEMS)
        gate = f"GATE = [\n    {years_line},\n    {stems_line},\n]"
        text = text[:start] + gate + text[end:]
        text = re.sub(
            r"QUERIES = GATE \+ \[[^\]]*\]",
            'QUERIES = GATE + ["www", "gob.gq", "www.gob.gq", "boe.gob.gq", "www.boe.gob.gq", "constitucion", "ministerio", "presidente", "asamblea", "malabo"]',
            text,
            count=1,
        )
        text = re.sub(
            r'"""BM25 smoke for Equatorial Guinea IR.*?"""',
            '"""BM25 smoke for Equatorial Guinea IR — Spanish legal corpus; years + Spanish legal stems FTS gate.\n\n'
            "GATE is attested ASCII years plus Spanish legal stems (ASCII-fold). URL www/gob.gq\n"
            "is query-only, never GATE. Every GATE token must rank a hit.\n"
            '"""',
            text,
            count=1,
            flags=re.S,
        )
        note = (
            f"attested years {GATE_NOTE_YEARS} plus Spanish legal stems {GATE_NOTE_STEMS} "
            f"from articles.parquet HEAD tip {DST_TIP_SHORT}; URL www/gob.gq is query-only, not GATE."
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

    if dst_name == "equatorialguinea_write_publish_report.py":
        gate_note = (
            f"BM25 PASS on Equatorial Guinea ASCII-fold Spanish GATE "
            f"(attested years {GATE_NOTE_YEARS} + stems {GATE_NOTE_STEMS}); "
            f"URL www/gob.gq is query-only, not GATE"
        )
        text = re.sub(
            r'BM25 PASS on Equatorial Guinea[^"]*"',
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
        text = text.replace("Dutch years+stems GATE", "Spanish years+stems GATE")
        text = text.replace("English years+stems GATE", "Spanish years+stems GATE")
        text = text.replace("Dutch legal stems GATE", "Spanish years+stems GATE")
        text = re.sub(
            r"HOLD 0 STRICT after-GW[^;]*; collectors kept dead \(pkill\); soft never-thin ON; SKIP_US; Italy BLOCKED;[^\"\n]*",
            f"{HOLD}; collectors kept dead (pkill); soft never-thin ON; SKIP_US; Italy BLOCKED; {WAVE_POS}",
            text,
        )
        text = re.sub(
            r"HOLD 0 STRICT after-SR[^;]*; collectors kept dead \(pkill\); soft never-thin ON; SKIP_US; Italy BLOCKED;[^\"\n]*",
            f"{HOLD}; collectors kept dead (pkill); soft never-thin ON; SKIP_US; Italy BLOCKED; {WAVE_POS}",
            text,
        )
        text = text.replace("www/gov.sr is query-only", "www/gob.gq is query-only")
        text = text.replace("www/gob.gq is query-only", "www/gob.gq is query-only")
        text = re.sub(r"[ \t]{2,}", " ", text)

    leftovers = (
        "Suriname", "suriname",
        "cient-data", "prent-data", "stent-data", "cvent-data", "scent-data",
        "carent-data", "yement-data", "djiboutient-data", "marshallislandsent-data",
        "kiribatient-data", "burundient-data", "eswatinient-data", "niueent-data",
        "guineabissauent-data", "surinameent-data", "equatorialguineaent-data",
        "gov.sr", "www.gov.sr", "dna.sr",
        "Dutch",
    )
    found = []
    for x in leftovers:
        if x == "suriname":
            if re.search(r"(?<![A-Za-z0-9_])suriname(?![A-Za-z0-9_])", text):
                found.append(x)
            continue
        if x == "Dutch":
            if "Dutch" in text:
                found.append(x)
            continue
        if x in text:
            found.append(x)
    if found:
        raise RuntimeError(f"language/country leftovers in {dst_name}: {found}")

    # Reject Dutch leftovers in GATE; require Spanish stems
    if dst_name.endswith("_bm25_smoke.py"):
        gate_slice = text[text.index("GATE = ["): text.index("]", text.index("GATE = [")) + 1]
        for bad in (
            "suriname", "artikel", "wet", "besluit", "minister", "persoon",
            "sectie", "republiek", "staat", "lid", "grondwet", "wetboek",
            "article", "section", "act", "law", "person", "republic",
            "artigo", "lei", "codigo",  # wait codigo is Spanish too — keep Spanish codigo
            "puerto", "asociado",
            "loi", "decret", "ministre",
        ):
            # "codigo" is valid Spanish — skip
            if bad == "codigo":
                continue
            if f'"{bad}"' in gate_slice:
                raise RuntimeError(f"non-GQ token in GATE of {dst_name}: {bad}")
        for stem in GATE_STEMS:
            if f'"{stem}"' not in gate_slice:
                raise RuntimeError(f"missing Spanish stem in GATE of {dst_name}: {stem}")
        for year in GATE_YEARS:
            if f'"{year}"' not in gate_slice:
                raise RuntimeError(f"missing year in GATE of {dst_name}: {year}")
        if '", "sr"' in text or '", "SR"' in text:
            raise RuntimeError(f"leftover sr query token in {dst_name}")
        if "gov.sr" in text:
            raise RuntimeError(f"leftover gov.sr in {dst_name}")
        if re.search(r"Dutch legal", text):
            raise RuntimeError(f"leftover Dutch legal phrasing in {dst_name}")

    # reject bare suriname / SR leftovers outside protected HOLD/wave
    scrub = text
    scrub = scrub.replace(WAVE_POS, "XX")
    scrub = scrub.replace(HOLD, "XX")
    scrub = scrub.replace(DEST_CHAIN, "XX")
    scrub = scrub.replace(SRC_CHAIN, "XX")
    scrub = scrub.replace(SRC_HOLD, "XX")
    scrub = scrub.replace(SRC_WAVE, "XX")
    scrub = scrub.replace("after-SR", "after-XX")
    scrub = scrub.replace("after SR ", "after XX ")
    scrub = scrub.replace("after_dj", "after_xx")
    scrub = scrub.replace("SR LIVE", "XX LIVE")
    scrub = scrub.replace("SR→", "XX→")
    scrub = scrub.replace("…→SR", "…→XX")
    if re.search(r"(?<![A-Za-z0-9_])suriname(?![A-Za-z0-9_])", scrub):
        m = re.search(r"(?<![A-Za-z0-9_])suriname(?![A-Za-z0-9_])", scrub)
        raise RuntimeError(
            f"leftover suriname in {dst_name}: ...{scrub[max(0, m.start()-20):m.start()+20]}..."
        )
    if re.search(r"(?<![A-Za-z%])SR(?![A-Za-z])", scrub):
        m = re.search(r"(?<![A-Za-z%])SR(?![A-Za-z])", scrub)
        raise RuntimeError(
            f"leftover SR in {dst_name}: ...{scrub[max(0, m.start()-30):m.start()+30]}..."
        )
    if "ipfs_suriname" in text:
        raise RuntimeError(f"leftover suriname path in {dst_name}")
    if "agent-data" not in text and "SECRET" in text.upper():
        if any(x in dst_name for x in ("soft_filter", "upload", "orchestrator")):
            if "/home/box/" in text and "agent-data" not in text:
                raise RuntimeError(f"missing agent-data secret path in {dst_name}")
    # data/ paths must survive
    if "soft_filter" in dst_name or "corpus_stream" in dst_name:
        if "data/laws.parquet" not in text and 'data" / "laws.parquet"' not in text:
            if '"data"' not in text and "/data/" not in text:
                raise RuntimeError(f"missing data/ parquet paths in {dst_name}")
    # reject residual Dutch GATE language labels in publish/smoke
    if "write_publish" in dst_name or "bm25_smoke" in dst_name:
        if re.search(r"ASCII-fold Dutch", text):
            raise RuntimeError(f"leftover ASCII-fold Dutch in {dst_name}")
        if re.search(r"Dutch legal (stems|corpus)", text):
            raise RuntimeError(f"leftover Dutch legal phrasing in {dst_name}")
    # tip integrity: must contain DST tip, must NOT contain bare floor corruption of tip
    if DST_TIP_SHORT not in text and ("TIP" in text or "tip" in text):
        # soft_filter / orchestrator must carry tip
        if any(x in dst_name for x in ("soft_filter", "orchestrator", "bm25_smoke", "corpus", "encode", "package", "finish", "stream_graph", "upload", "write_publish")):
            if "TIP_SHORT" in text or "TIP_FULL" in text or "tip" in text.lower():
                if DST_TIP_SHORT not in text and SRC_TIP_SHORT in text:
                    raise RuntimeError(f"src tip leftover in {dst_name}")
    if "6d94d0c7e604" in text or "6d86d0c7e94" in text:
        raise RuntimeError(f"corrupted tip in {dst_name}")
    # UUID secret path must keep c94b
    if "67930c3f-c86b-" in text:
        raise RuntimeError(f"UUID c94b corrupted to c86b in {dst_name}")
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
    if entry.get("slug") == "equatorialguinea" or entry.get("iso2") == "GQ":
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
            "language": "Spanish",
            "lang": "Spanish",
            "iso2": "GQ",
            "slug": "equatorialguinea",
            "repo": "endomorphosis/ipfs_equatorialguinea_laws",
            "years_attested": YEARS_ATTESTED,
            "gate_years": [int(y) for y in GATE_YEARS],
            "gate_stems": GATE_STEMS,
            "note": (
                f"GQ FIRST_IR scaffold; tip MATCH {DST_TIP_SHORT}@86/2041; {HOLD}; "
                f"soft never-thin ON; SKIP_US; Italy BLOCKED; {WAVE_POS}; "
                f"Spanish GATE ({len(GATE_YEARS)} years + {len(GATE_STEMS)} stems)"
            ),
            "status": "CLAIMED",
            "mode": "FIRST_IR",
            "wave_end": False,
        })
        break
else:
    raise RuntimeError("Equatorial Guinea/GQ entry missing from wave JSON")

data["wave_status"] = "IN_PROGRESS_GQ"
data["hold"] = HOLD
data["current"] = "equatorialguinea"
data["do_not_start_next"] = "guyana"
data["next"] = "guyana"
wave.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print("updated wave JSON Equatorial Guinea entry")
print("GATE years", GATE_YEARS)
print("GATE stems", GATE_STEMS)
print("n_gate", len(GATE_YEARS) + len(GATE_STEMS))
print("HOLD", HOLD)
print("GATE language: Spanish years+stems")
