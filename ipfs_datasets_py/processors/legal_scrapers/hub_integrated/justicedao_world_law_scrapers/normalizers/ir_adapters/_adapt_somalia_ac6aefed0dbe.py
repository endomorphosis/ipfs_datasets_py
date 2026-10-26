#!/usr/bin/env python3
"""Adapt the Guyana English memsafe FIRST_IR pack to Somalia SO tip ac6aefed0dbe.

English (Somalia); FIRST_IR; HOLD 0 STRICT after-BJ (SO→MV).
Soft never-thin ON; SKIP_US; Italy BLOCKED. WAVE after_dj after BJ LIVE
(…→BJ LIVE → SO → MV; NOT wave end).
GATE: attested years + English legal stems from data/articles.parquet tip ac6aefed0dbe
(English; include somalia/somali). URL parliament.gov.so / gov.so query-only, NOT GATE.
Source tip b0752848c53b (Guyana English memsafe with data/ paths)
— keep language English (Somalia).
Keep data/articles.parquet + data/laws.parquet; agent-data not cient-data.
Do NOT start Maldives/next after LIVE.
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
SRC_TIP_FULL = "b0752848c53bef3de692ce00dcba7b9a46ed3401"
SRC_TIP_SHORT = "b0752848c53b"
DST_TIP_FULL = "ac6aefed0dbe007940d49b85d19917a98d2f8c0d"
DST_TIP_SHORT = "ac6aefed0dbe"
FLOOR_LAWS, FLOOR_ARTS = 77, 1833
SRC_FLOOR_L, SRC_FLOOR_A = 200, 2029

# Sampled from data/articles.parquet @ ac6aefed0dbe (~10 years + English stems)
# Whole-word ASCII-fold FTS hits; laws=77 articles=1833.
# Top years by doc hits; English legal stems (+ somalia/somali). ordinance=0 → omit.
GATE_YEARS = [
    "2012", "2013", "2015", "1960", "1990",
    "2018", "1948", "1963", "2010", "1991",
]
GATE_STEMS = [
    "act", "article", "section", "law", "code", "republic",
    "somalia", "somali", "government", "person", "order",
]
YEARS_ATTESTED = [int(y) for y in GATE_YEARS] + [
    2016, 2022, 1965, 2020, 1962, 1996, 2003, 2005, 2004, 2000,
]
GATE_NOTE_YEARS = "/".join(GATE_YEARS)
GATE_NOTE_STEMS = "/".join(GATE_STEMS)
HOLD = "HOLD 0 STRICT after-BJ (SO→MV)"
WAVE_POS = (
    "after BJ LIVE of after_dj wave "
    "(…→BJ LIVE → SO → MV; NOT wave end)"
)
DEST_CHAIN = "SO→MV"
SRC_HOLD = "HOLD 0 STRICT after-GQ (GY→BJ→SO→MV)"
SRC_WAVE = (
    "after GQ LIVE of after_dj wave "
    "(…→GQ LIVE → GY → BJ→SO→MV; NOT wave end)"
)
SRC_CHAIN = "GY→BJ→SO→MV"

FILES = [
    ("guyana_soft_filter.py", "somalia_soft_filter.py"),
    (f"guyana_corpus_stream_{SRC_TIP_SHORT}.py", f"somalia_corpus_stream_{DST_TIP_SHORT}.py"),
    (f"guyana_encode_memsafe_{SRC_TIP_SHORT}.py", f"somalia_encode_memsafe_{DST_TIP_SHORT}.py"),
    (f"guyana_finish_from_emb_{SRC_TIP_SHORT}.py", f"somalia_finish_from_emb_{DST_TIP_SHORT}.py"),
    (f"guyana_stream_graph_parts_{SRC_TIP_SHORT}.py", f"somalia_stream_graph_parts_{DST_TIP_SHORT}.py"),
    (f"guyana_package_memsafe_{SRC_TIP_SHORT}.py", f"somalia_package_memsafe_{DST_TIP_SHORT}.py"),
    ("guyana_upload.py", "somalia_upload.py"),
    ("guyana_bm25_smoke.py", "somalia_bm25_smoke.py"),
    ("guyana_write_publish_report.py", "somalia_write_publish_report.py"),
    (f"guyana_orchestrator_{SRC_TIP_SHORT}.py", f"somalia_orchestrator_{DST_TIP_SHORT}.py"),
]


def adapt(text: str, dst_name: str) -> str:
    # Repair path corruption from prior adapts
    for bad in (
        "cient-data", "prent-data", "stent-data", "cvent-data", "scent-data",
        "carent-data", "yement-data", "djiboutient-data", "marshallislandsent-data",
        "kiribatient-data", "burundient-data", "eswatinient-data", "niueent-data",
        "guineabissauent-data", "surinameent-data", "equatorialguineaent-data",
        "guyanaent-data", "beninent-data", "somaliaent-data",
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
    text = text.replace("after-GQ", "\x00AFTERBJ\x00")
    text = text.replace("after GQ ", "\x00AFTERBJ_SP\x00")
    text = text.replace("after_dj", "\x00AFTERDJ_US\x00")
    text = text.replace(
        "…→GQ LIVE → GY → BJ→SO→MV",
        "\x00SRCCHAIN_FULL\x00",
    )
    text = text.replace("after GQ LIVE of \x00AFTERDJ_US\x00 wave", "\x00DESTWAVE_SHORT\x00")
    text = text.replace("after GQ LIVE of after_dj wave", "\x00DESTWAVE_SHORT\x00")
    text = text.replace("GY FIRST_IR", "\x00DESTFIRST\x00")
    # Protect destination ISO in chain fragments that may appear early
    text = text.replace("BJ→SO→MV", "\x00BJSOMV\x00")
    text = text.replace("SO→MV", "\x00DESTCHAIN\x00")

    reps = [
        (SRC_TIP_FULL, DST_TIP_FULL),
        (SRC_TIP_SHORT, DST_TIP_SHORT),
        ("endomorphosis/ipfs_guyana_laws", "endomorphosis/ipfs_somalia_laws"),
        ("justicedao/ipfs_guyana_laws_ir", "justicedao/ipfs_somalia_laws_ir"),
        ("ipfs_guyana_laws_ir", "ipfs_somalia_laws_ir"),
        ("ipfs_guyana_laws", "ipfs_somalia_laws"),
        # HOLD / wave restore
        ("\x00DESTHOLD\x00", HOLD),
        ("\x00DESTWAVE\x00", WAVE_POS),
        ("\x00DESTWAVE_SHORT\x00", WAVE_POS),
        ("\x00DESTCHAIN\x00", DEST_CHAIN),
        ("\x00SRCCHAIN_FULL\x00", "…→BJ LIVE → SO → MV"),
        ("\x00AFTERBJ\x00", "after-BJ"),
        ("\x00AFTERBJ_SP\x00", "after BJ "),
        ("\x00DESTFIRST\x00", "SO FIRST_IR"),
        ("\x00BJSOMV\x00", "BJ→SO→MV"),
        ("GY FIRST_IR (not wave end)", "SO FIRST_IR (not wave end)"),
        ("www/parliament.gov.gy", "www/parliament.gov.so"),
        ("parliament.gov.gy", "parliament.gov.so"),
        ("www.parliament.gov.gy", "www.parliament.gov.so"),
        ("www/gov.gy", "www/gov.so"),
        ("gov.gy", "gov.so"),
        ("www.gov.gy", "www.gov.so"),
        # Language / country — keep English, swap country
        ("English (Guyana)", "English (Somalia)"),
        ("English Guyana", "English Somalia"),
        ("Guyana", "Somalia"),
        # slug / path forms BEFORE bare guyana
        ("guyana_ranked", "somalia_ranked"),
        ("guyana_gate", "somalia_gate"),
        ("guyana_pass", "somalia_pass"),
        ("guyana_encode_memsafe", "somalia_encode_memsafe"),
        ("guyana_package_memsafe", "somalia_package_memsafe"),
        ("guyana_corpus_stream", "somalia_corpus_stream"),
        ("guyana_encode_done", "somalia_encode_done"),
        ("guyana_filtered_", "somalia_filtered_"),
        ("guyana_", "somalia_"),
        # ISO whole-token / path forms only (GY already protected in HOLD)
        ('"GY"', '"SO"'),
        ("GY-attested", "SO-attested"),
        ("(GY)", "(SO)"),
        ('"gy"', '"so"'),
        # floors 200/2029 → 77/1833 — compound ONLY
        ("200/2029", "77/1833"),
        ("200 / 2029", "77 / 1833"),
        ("200, 2029", "77, 1833"),
        ("FLOOR_LAWS, FLOOR_ARTS = 200, 2029", "FLOOR_LAWS, FLOOR_ARTS = 77, 1833"),
        ('int(pack.get("n_laws") or 200)', 'int(pack.get("n_laws") or 77)'),
        ('int(pack.get("n_articles") or 2029)', 'int(pack.get("n_articles") or 1833)'),
        ("@ 200/", "@ 77/"),
        ("floor 200/", "floor 77/"),
        ("(200/", "(77/"),
        (" 2029", " 1833"),
        ("2029", "1833"),
    ]
    for a, b in reps:
        text = text.replace(a, b)

    # Bare slug "guyana" → "somalia"
    text = re.sub(r"(?<![A-Za-z0-9_])guyana(?![A-Za-z0-9_])", "somalia", text)

    text = text.replace("\x00BM25\x00", "BM25").replace("\x00bm25\x00", "bm25")
    text = text.replace("\x00AFTERDJ_US\x00", "after_dj")
    text = text.replace("\x00DESTHOLD\x00", HOLD)
    text = text.replace("\x00DESTCHAIN\x00", DEST_CHAIN)
    text = text.replace("\x00DESTWAVE\x00", WAVE_POS)
    text = text.replace("\x00BJSOMV\x00", "BJ→SO→MV")

    # display name / slug fixes
    text = text.replace('"name": "somalia"', '"name": "Somalia"')
    text = text.replace('"name": "Somalia"', '"name": "Somalia"')
    text = text.replace('"slug": "Somalia"', '"slug": "somalia"')
    text = text.replace('SLUG = "Somalia"', 'SLUG = "somalia"')
    text = text.replace('SLUG = "somalia"', 'SLUG = "somalia"')
    text = text.replace('"country": "Somalia"', '"country": "somalia"')
    text = text.replace('"country": "guyana"', '"country": "somalia"')

    # Ensure agent-data survived
    for bad in (
        "cient-data", "prent-data", "stent-data", "cvent-data", "scent-data",
        "carent-data", "yement-data", "djiboutient-data", "marshallislandsent-data",
        "kiribatient-data", "burundient-data", "eswatinient-data", "niueent-data",
        "guineabissauent-data", "surinameent-data", "equatorialguineaent-data",
        "guyanaent-data", "beninent-data", "somaliaent-data",
    ):
        text = text.replace(f"/home/box/{bad}/", "/home/box/agent-data/")
        text = text.replace(bad, "agent-data")

    if dst_name == "somalia_bm25_smoke.py":
        start = text.index("GATE = [")
        end = text.index("]", start) + 1
        years_line = ", ".join(f'"{y}"' for y in GATE_YEARS)
        stems_line = ", ".join(f'"{s}"' for s in GATE_STEMS)
        gate = f"GATE = [\n    {years_line},\n    {stems_line},\n]"
        text = text[:start] + gate + text[end:]
        text = re.sub(
            r"QUERIES = GATE \+ \[[^\]]*\]",
            'QUERIES = GATE + ["www", "gov.so", "www.gov.so", "parliament.gov.so", "www.parliament.gov.so", "constitution", "minister", "parliament", "shall", "federal"]',
            text,
            count=1,
        )
        text = re.sub(
            r'"""BM25 smoke for Somalia IR.*?"""',
            '"""BM25 smoke for Somalia IR — English legal corpus; years + English legal stems FTS gate.\n\n'
            "GATE is attested ASCII years plus English legal stems (ASCII-fold). URL www/gov.so\n"
            "is query-only, never GATE. Every GATE token must rank a hit.\n"
            '"""',
            text,
            count=1,
            flags=re.S,
        )
        note = (
            f"attested years {GATE_NOTE_YEARS} plus English legal stems {GATE_NOTE_STEMS} "
            f"from articles.parquet HEAD tip {DST_TIP_SHORT}; URL www/gov.so is query-only, not GATE."
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

    if dst_name == "somalia_write_publish_report.py":
        gate_note = (
            f"BM25 PASS on Somalia ASCII-fold English GATE "
            f"(attested years {GATE_NOTE_YEARS} + stems {GATE_NOTE_STEMS}); "
            f"URL www/gov.so is query-only, not GATE"
        )
        text = re.sub(
            r'BM25 PASS on Somalia[^"]*"',
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
        text = text.replace("www/gov.gy is query-only", "www/gov.so is query-only")
        text = text.replace("www/gov.so is query-only", "www/gov.so is query-only")
        text = re.sub(
            r"HOLD 0 STRICT after-GQ[^;]*; collectors kept dead \(pkill\); soft never-thin ON; SKIP_US; Italy BLOCKED;[^\"\n]*",
            f"{HOLD}; collectors kept dead (pkill); soft never-thin ON; SKIP_US; Italy BLOCKED; {WAVE_POS}",
            text,
        )
        text = re.sub(
            r"HOLD 0 STRICT after-BJ[^;]*; collectors kept dead \(pkill\); soft never-thin ON; SKIP_US; Italy BLOCKED;[^\"\n]*",
            f"{HOLD}; collectors kept dead (pkill); soft never-thin ON; SKIP_US; Italy BLOCKED; {WAVE_POS}",
            text,
        )
        text = re.sub(r"[ \t]{2,}", " ", text)

    leftovers = (
        "Guyana", "guyana",
        "cient-data", "prent-data", "stent-data", "cvent-data", "scent-data",
        "carent-data", "yement-data", "djiboutient-data", "marshallislandsent-data",
        "kiribatient-data", "burundient-data", "eswatinient-data", "niueent-data",
        "guineabissauent-data", "surinameent-data", "equatorialguineaent-data",
        "guyanaent-data",
        "gov.gy", "www.gov.gy", "parliament.gov.gy",
    )
    found = []
    for x in leftovers:
        if x == "guyana":
            if re.search(r"(?<![A-Za-z0-9_])guyana(?![A-Za-z0-9_])", text):
                found.append(x)
            continue
        if x in text:
            found.append(x)
    if found:
        raise RuntimeError(f"language/country leftovers in {dst_name}: {found}")

    # Reject non-SO tokens in GATE; require English stems
    if dst_name.endswith("_bm25_smoke.py"):
        gate_slice = text[text.index("GATE = ["): text.index("]", text.index("GATE = [")) + 1]
        for bad in (
            "guyana", "ordinance",  # ordinance=0 in SO corpus
            "loi", "decret", "ordonnance", "republique", "benin", "gouvernement", "personne", "ministre",
            "articulo", "ley", "decreto", "codigo", "seccion",
            "artikel", "wet", "besluit", "persoon", "sectie", "republiek",
            "artigo", "lei",
        ):
            if f'"{bad}"' in gate_slice:
                raise RuntimeError(f"non-SO token in GATE of {dst_name}: {bad}")
        for stem in GATE_STEMS:
            if f'"{stem}"' not in gate_slice:
                raise RuntimeError(f"missing English stem in GATE of {dst_name}: {stem}")
        for year in GATE_YEARS:
            if f'"{year}"' not in gate_slice:
                raise RuntimeError(f"missing year in GATE of {dst_name}: {year}")
        if '", "gy"' in text or '", "GY"' in text:
            raise RuntimeError(f"leftover gy query token in {dst_name}")
        if "gov.gy" in text:
            raise RuntimeError(f"leftover gov.gy in {dst_name}")

    # reject bare guyana / GY leftovers outside protected HOLD/wave
    scrub = text
    scrub = scrub.replace(WAVE_POS, "XX")
    scrub = scrub.replace(HOLD, "XX")
    scrub = scrub.replace(DEST_CHAIN, "XX")
    scrub = scrub.replace(SRC_CHAIN, "XX")
    scrub = scrub.replace(SRC_HOLD, "XX")
    scrub = scrub.replace(SRC_WAVE, "XX")
    scrub = scrub.replace("after-BJ", "after-XX")
    scrub = scrub.replace("after BJ ", "after XX ")
    scrub = scrub.replace("after_dj", "after_xx")
    scrub = scrub.replace("BJ LIVE", "XX LIVE")
    scrub = scrub.replace("BJ→", "XX→")
    scrub = scrub.replace("…→BJ", "…→XX")
    scrub = scrub.replace("GY→BJ→SO→MV", "XX")
    scrub = scrub.replace("GY LIVE", "XX LIVE")
    if re.search(r"(?<![A-Za-z0-9_])guyana(?![A-Za-z0-9_])", scrub):
        m = re.search(r"(?<![A-Za-z0-9_])guyana(?![A-Za-z0-9_])", scrub)
        raise RuntimeError(
            f"leftover guyana in {dst_name}: ...{scrub[max(0, m.start()-20):m.start()+20]}..."
        )
    if re.search(r"(?<![A-Za-z%])GY(?![A-Za-z])", scrub):
        m = re.search(r"(?<![A-Za-z%])GY(?![A-Za-z])", scrub)
        raise RuntimeError(
            f"leftover GY in {dst_name}: ...{scrub[max(0, m.start()-30):m.start()+30]}..."
        )
    if "ipfs_guyana" in text:
        raise RuntimeError(f"leftover guyana path in {dst_name}")
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
    # english language must remain for SO
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
    if entry.get("slug") == "somalia" or entry.get("iso2") == "SO":
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
            "iso2": "SO",
            "slug": "somalia",
            "repo": "endomorphosis/ipfs_somalia_laws",
            "years_attested": YEARS_ATTESTED,
            "gate_years": [int(y) for y in GATE_YEARS],
            "gate_stems": GATE_STEMS,
            "note": (
                f"SO FIRST_IR scaffold; tip MATCH {DST_TIP_SHORT}@77/1833; {HOLD}; "
                f"soft never-thin ON; SKIP_US; Italy BLOCKED; {WAVE_POS}; "
                f"English GATE ({len(GATE_YEARS)} years + {len(GATE_STEMS)} stems)"
            ),
            "status": "CLAIMED",
            "mode": "FIRST_IR",
            "wave_end": False,
        })
        break
else:
    raise RuntimeError("Somalia/SO entry missing from wave JSON")

data["wave_status"] = "IN_PROGRESS_SO"
data["hold"] = HOLD
data["current"] = "somalia"
data["do_not_start_next"] = "maldives"
data["next"] = "maldives"
wave.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print("updated wave JSON Somalia entry")
print("GATE years", GATE_YEARS)
print("GATE stems", GATE_STEMS)
print("n_gate", len(GATE_YEARS) + len(GATE_STEMS))
print("HOLD", HOLD)
print("GATE language: English years+stems")
