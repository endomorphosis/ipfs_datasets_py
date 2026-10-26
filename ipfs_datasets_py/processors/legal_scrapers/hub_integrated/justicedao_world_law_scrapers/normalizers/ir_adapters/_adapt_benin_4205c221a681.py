#!/usr/bin/env python3
"""Adapt the Guyana English memsafe FIRST_IR pack to Benin BJ tip 4205c221a681.

French (Benin / Bénin); FIRST_IR; HOLD 0 STRICT after-GY (BJ→SO→MV).
Soft never-thin ON; SKIP_US; Italy BLOCKED. WAVE after_dj after GY LIVE
(…→GY LIVE → BJ → SO→MV), NOT wave end.
GATE: attested years + French legal stems from data/articles.parquet tip 4205c221a681
(French; include benin/republique). URL sgg.gouv.bj / gouv.bj query-only, NOT GATE.
Source tip b0752848c53b (Guyana English memsafe with data/ paths)
— override language English → French (Benin).
Keep data/articles.parquet + data/laws.parquet; agent-data not cient-data.
Do NOT start Somalia/next after LIVE.
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
DST_TIP_FULL = "4205c221a681583a607f9e255b196b476b48ba7a"
DST_TIP_SHORT = "4205c221a681"
FLOOR_LAWS, FLOOR_ARTS = 102, 1900
SRC_FLOOR_L, SRC_FLOOR_A = 200, 2029

# Sampled from data/articles.parquet @ 4205c221a681 (~10 years + French stems)
# Whole-word ASCII-fold FTS hits; laws=102 articles=1900.
# Top years by doc hits; French legal stems (+ benin country).
GATE_YEARS = [
    "2020", "2021", "2022", "2019", "2018",
    "2001", "1990", "2017", "2015", "2016",
]
GATE_STEMS = [
    "article", "loi", "decret", "code", "ordonnance", "section",
    "republique", "benin", "gouvernement", "personne", "ministre",
]
YEARS_ATTESTED = [int(y) for y in GATE_YEARS] + [
    2002, 2026, 2000, 2013, 2012, 2023, 2008, 2014, 2006, 1993,
]
GATE_NOTE_YEARS = "/".join(GATE_YEARS)
GATE_NOTE_STEMS = "/".join(GATE_STEMS)
HOLD = "HOLD 0 STRICT after-GY (BJ→SO→MV)"
WAVE_POS = (
    "after GY LIVE of after_dj wave "
    "(…→GY LIVE → BJ → SO→MV; NOT wave end)"
)
DEST_CHAIN = "BJ→SO→MV"
SRC_HOLD = "HOLD 0 STRICT after-GQ (GY→BJ→SO→MV)"
SRC_WAVE = (
    "after GQ LIVE of after_dj wave "
    "(…→GQ LIVE → GY → BJ→SO→MV; NOT wave end)"
)
SRC_CHAIN = "GY→BJ→SO→MV"

FILES = [
    ("guyana_soft_filter.py", "benin_soft_filter.py"),
    (f"guyana_corpus_stream_{SRC_TIP_SHORT}.py", f"benin_corpus_stream_{DST_TIP_SHORT}.py"),
    (f"guyana_encode_memsafe_{SRC_TIP_SHORT}.py", f"benin_encode_memsafe_{DST_TIP_SHORT}.py"),
    (f"guyana_finish_from_emb_{SRC_TIP_SHORT}.py", f"benin_finish_from_emb_{DST_TIP_SHORT}.py"),
    (f"guyana_stream_graph_parts_{SRC_TIP_SHORT}.py", f"benin_stream_graph_parts_{DST_TIP_SHORT}.py"),
    (f"guyana_package_memsafe_{SRC_TIP_SHORT}.py", f"benin_package_memsafe_{DST_TIP_SHORT}.py"),
    ("guyana_upload.py", "benin_upload.py"),
    ("guyana_bm25_smoke.py", "benin_bm25_smoke.py"),
    ("guyana_write_publish_report.py", "benin_write_publish_report.py"),
    (f"guyana_orchestrator_{SRC_TIP_SHORT}.py", f"benin_orchestrator_{DST_TIP_SHORT}.py"),
]


def adapt(text: str, dst_name: str) -> str:
    # Repair path corruption from prior adapts
    for bad in (
        "cient-data", "prent-data", "stent-data", "cvent-data", "scent-data",
        "carent-data", "yement-data", "djiboutient-data", "marshallislandsent-data",
        "kiribatient-data", "burundient-data", "eswatinient-data", "niueent-data",
        "guineabissauent-data", "surinameent-data", "equatorialguineaent-data",
        "guyanaent-data", "beninent-data",
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
    text = text.replace("after-GQ", "\x00AFTERGY\x00")
    text = text.replace("after GQ ", "\x00AFTERGY_SP\x00")
    text = text.replace("after_dj", "\x00AFTERDJ_US\x00")
    text = text.replace(
        "…→GQ LIVE → GY → BJ→SO→MV",
        "\x00SRCCHAIN_FULL\x00",
    )
    text = text.replace("after GQ LIVE of \x00AFTERDJ_US\x00 wave", "\x00DESTWAVE_SHORT\x00")
    text = text.replace("after GQ LIVE of after_dj wave", "\x00DESTWAVE_SHORT\x00")
    text = text.replace("GY FIRST_IR", "\x00DESTFIRST\x00")

    reps = [
        (SRC_TIP_FULL, DST_TIP_FULL),
        (SRC_TIP_SHORT, DST_TIP_SHORT),
        ("endomorphosis/ipfs_guyana_laws", "endomorphosis/ipfs_benin_laws"),
        ("justicedao/ipfs_guyana_laws_ir", "justicedao/ipfs_benin_laws_ir"),
        ("ipfs_guyana_laws_ir", "ipfs_benin_laws_ir"),
        ("ipfs_guyana_laws", "ipfs_benin_laws"),
        # HOLD / wave restore
        ("\x00DESTHOLD\x00", HOLD),
        ("\x00DESTWAVE\x00", WAVE_POS),
        ("\x00DESTWAVE_SHORT\x00", WAVE_POS),
        ("\x00DESTCHAIN\x00", DEST_CHAIN),
        ("\x00SRCCHAIN_FULL\x00", "…→GY LIVE → BJ → SO→MV"),
        ("\x00AFTERGY\x00", "after-GY"),
        ("\x00AFTERGY_SP\x00", "after GY "),
        ("\x00DESTFIRST\x00", "BJ FIRST_IR"),
        ("GY FIRST_IR (not wave end)", "BJ FIRST_IR (not wave end)"),
        ("www/parliament.gov.gy", "www/sgg.gouv.bj"),
        ("parliament.gov.gy", "sgg.gouv.bj"),
        ("www.parliament.gov.gy", "www.sgg.gouv.bj"),
        ("www/gov.gy", "www/gouv.bj"),
        ("gov.gy", "gouv.bj"),
        ("www.gov.gy", "www.gouv.bj"),
        # Language / country — English → French BEFORE bare Guyana
        ("English (Guyana)", "French (Benin)"),
        ("English Guyana", "French Benin"),
        ("ASCII-fold English", "ASCII-fold French"),
        ("English legal stems", "French legal stems"),
        ("English legal corpus", "French legal corpus"),
        ("English years+stems GATE", "French years+stems GATE"),
        ("English GATE", "French GATE"),
        ("language: English", "language: French"),
        ("Language: English", "Language: French"),
        ('"language": "English"', '"language": "French"'),
        ('"lang": "English"', '"lang": "French"'),
        ("Guyana", "Benin"),
        # slug / path forms BEFORE bare guyana
        ("guyana_ranked", "benin_ranked"),
        ("guyana_gate", "benin_gate"),
        ("guyana_pass", "benin_pass"),
        ("guyana_encode_memsafe", "benin_encode_memsafe"),
        ("guyana_package_memsafe", "benin_package_memsafe"),
        ("guyana_corpus_stream", "benin_corpus_stream"),
        ("guyana_encode_done", "benin_encode_done"),
        ("guyana_filtered_", "benin_filtered_"),
        ("guyana_", "benin_"),
        # ISO whole-token / path forms only (GY already protected in HOLD)
        ('"GY"', '"BJ"'),
        ("GY-attested", "BJ-attested"),
        ("(GY)", "(BJ)"),
        ('"gy"', '"bj"'),
        # floors 200/2029 → 102/1900 — compound ONLY
        ("200/2029", "102/1900"),
        ("200 / 2029", "102 / 1900"),
        ("200, 2029", "102, 1900"),
        ("FLOOR_LAWS, FLOOR_ARTS = 200, 2029", "FLOOR_LAWS, FLOOR_ARTS = 102, 1900"),
        ('int(pack.get("n_laws") or 200)', 'int(pack.get("n_laws") or 102)'),
        ('int(pack.get("n_articles") or 2029)', 'int(pack.get("n_articles") or 1900)'),
        ("@ 200/", "@ 102/"),
        ("floor 200/", "floor 102/"),
        ("(200/", "(102/"),
        (" 2029", " 1900"),
        ("2029", "1900"),
    ]
    for a, b in reps:
        text = text.replace(a, b)

    # Bare slug "guyana" → "benin"
    text = re.sub(r"(?<![A-Za-z0-9_])guyana(?![A-Za-z0-9_])", "benin", text)

    text = text.replace("\x00BM25\x00", "BM25").replace("\x00bm25\x00", "bm25")
    text = text.replace("\x00AFTERDJ_US\x00", "after_dj")
    text = text.replace("\x00DESTHOLD\x00", HOLD)
    text = text.replace("\x00DESTCHAIN\x00", DEST_CHAIN)
    text = text.replace("\x00DESTWAVE\x00", WAVE_POS)

    # display name / slug fixes
    text = text.replace('"name": "benin"', '"name": "Benin"')
    text = text.replace('"name": "Benin"', '"name": "Benin"')
    text = text.replace('"slug": "Benin"', '"slug": "benin"')
    text = text.replace('SLUG = "Benin"', 'SLUG = "benin"')
    text = text.replace('SLUG = "benin"', 'SLUG = "benin"')
    text = text.replace('"country": "Benin"', '"country": "benin"')
    text = text.replace('"country": "guyana"', '"country": "benin"')

    # Ensure agent-data survived
    for bad in (
        "cient-data", "prent-data", "stent-data", "cvent-data", "scent-data",
        "carent-data", "yement-data", "djiboutient-data", "marshallislandsent-data",
        "kiribatient-data", "burundient-data", "eswatinient-data", "niueent-data",
        "guineabissauent-data", "surinameent-data", "equatorialguineaent-data",
        "guyanaent-data", "beninent-data",
    ):
        text = text.replace(f"/home/box/{bad}/", "/home/box/agent-data/")
        text = text.replace(bad, "agent-data")

    if dst_name == "benin_bm25_smoke.py":
        start = text.index("GATE = [")
        end = text.index("]", start) + 1
        years_line = ", ".join(f'"{y}"' for y in GATE_YEARS)
        stems_line = ", ".join(f'"{s}"' for s in GATE_STEMS)
        gate = f"GATE = [\n    {years_line},\n    {stems_line},\n]"
        text = text[:start] + gate + text[end:]
        text = re.sub(
            r"QUERIES = GATE \+ \[[^\]]*\]",
            'QUERIES = GATE + ["www", "gouv.bj", "www.gouv.bj", "sgg.gouv.bj", "www.sgg.gouv.bj", "constitution", "ministre", "ordonnance", "decret", "loi"]',
            text,
            count=1,
        )
        text = re.sub(
            r'"""BM25 smoke for Benin IR.*?"""',
            '"""BM25 smoke for Benin IR — French legal corpus; years + French legal stems FTS gate.\n\n'
            "GATE is attested ASCII years plus French legal stems (ASCII-fold). URL www/gouv.bj\n"
            "is query-only, never GATE. Every GATE token must rank a hit.\n"
            '"""',
            text,
            count=1,
            flags=re.S,
        )
        note = (
            f"attested years {GATE_NOTE_YEARS} plus French legal stems {GATE_NOTE_STEMS} "
            f"from articles.parquet HEAD tip {DST_TIP_SHORT}; URL www/gouv.bj is query-only, not GATE."
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

    if dst_name == "benin_write_publish_report.py":
        gate_note = (
            f"BM25 PASS on Benin ASCII-fold French GATE "
            f"(attested years {GATE_NOTE_YEARS} + stems {GATE_NOTE_STEMS}); "
            f"URL www/gouv.bj is query-only, not GATE"
        )
        text = re.sub(
            r'BM25 PASS on Benin[^"]*"',
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
        text = text.replace("English years+stems GATE", "French years+stems GATE")
        text = text.replace("Spanish years+stems GATE", "French years+stems GATE")
        text = text.replace("Dutch years+stems GATE", "French years+stems GATE")
        text = text.replace("English legal stems GATE", "French years+stems GATE")
        text = re.sub(
            r"HOLD 0 STRICT after-GQ[^;]*; collectors kept dead \(pkill\); soft never-thin ON; SKIP_US; Italy BLOCKED;[^\"\n]*",
            f"{HOLD}; collectors kept dead (pkill); soft never-thin ON; SKIP_US; Italy BLOCKED; {WAVE_POS}",
            text,
        )
        text = re.sub(
            r"HOLD 0 STRICT after-GY[^;]*; collectors kept dead \(pkill\); soft never-thin ON; SKIP_US; Italy BLOCKED;[^\"\n]*",
            f"{HOLD}; collectors kept dead (pkill); soft never-thin ON; SKIP_US; Italy BLOCKED; {WAVE_POS}",
            text,
        )
        text = text.replace("www/gov.gy is query-only", "www/gouv.bj is query-only")
        text = text.replace("www/gouv.bj is query-only", "www/gouv.bj is query-only")
        text = re.sub(r"[ \t]{2,}", " ", text)

    leftovers = (
        "Guyana", "guyana",
        "cient-data", "prent-data", "stent-data", "cvent-data", "scent-data",
        "carent-data", "yement-data", "djiboutient-data", "marshallislandsent-data",
        "kiribatient-data", "burundient-data", "eswatinient-data", "niueent-data",
        "guineabissauent-data", "surinameent-data", "equatorialguineaent-data",
        "guyanaent-data",
        "gov.gy", "www.gov.gy", "parliament.gov.gy",
        "English",
    )
    found = []
    for x in leftovers:
        if x == "guyana":
            if re.search(r"(?<![A-Za-z0-9_])guyana(?![A-Za-z0-9_])", text):
                found.append(x)
            continue
        if x == "English":
            # allow in comments about override / source; reject GATE language labels
            if re.search(r"ASCII-fold English|English legal|language: English|\"language\": \"English\"", text):
                found.append(x)
            continue
        if x in text:
            found.append(x)
    if found:
        raise RuntimeError(f"language/country leftovers in {dst_name}: {found}")

    # Reject English leftovers in GATE; require French stems
    if dst_name.endswith("_bm25_smoke.py"):
        gate_slice = text[text.index("GATE = ["): text.index("]", text.index("GATE = [")) + 1]
        for bad in (
            "guyana", "act", "law", "ordinance", "republic", "government", "person", "order",
            "articulo", "ley", "decreto", "codigo", "seccion",
            "artikel", "wet", "besluit", "persoon", "sectie", "republiek",
            "artigo", "lei",
        ):
            if f'"{bad}"' in gate_slice:
                raise RuntimeError(f"non-BJ token in GATE of {dst_name}: {bad}")
        for stem in GATE_STEMS:
            if f'"{stem}"' not in gate_slice:
                raise RuntimeError(f"missing French stem in GATE of {dst_name}: {stem}")
        for year in GATE_YEARS:
            if f'"{year}"' not in gate_slice:
                raise RuntimeError(f"missing year in GATE of {dst_name}: {year}")
        if '", "gy"' in text or '", "GY"' in text:
            raise RuntimeError(f"leftover gy query token in {dst_name}")
        if "gov.gy" in text:
            raise RuntimeError(f"leftover gov.gy in {dst_name}")
        if re.search(r"English legal", text):
            raise RuntimeError(f"leftover English legal phrasing in {dst_name}")

    # reject bare guyana / GY leftovers outside protected HOLD/wave
    scrub = text
    scrub = scrub.replace(WAVE_POS, "XX")
    scrub = scrub.replace(HOLD, "XX")
    scrub = scrub.replace(DEST_CHAIN, "XX")
    scrub = scrub.replace(SRC_CHAIN, "XX")
    scrub = scrub.replace(SRC_HOLD, "XX")
    scrub = scrub.replace(SRC_WAVE, "XX")
    scrub = scrub.replace("after-GY", "after-XX")
    scrub = scrub.replace("after GY ", "after XX ")
    scrub = scrub.replace("after_dj", "after_xx")
    scrub = scrub.replace("GY LIVE", "XX LIVE")
    scrub = scrub.replace("GY→", "XX→")
    scrub = scrub.replace("…→GY", "…→XX")
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
    if "write_publish" in dst_name or "bm25_smoke" in dst_name:
        if re.search(r"ASCII-fold English", text):
            raise RuntimeError(f"leftover ASCII-fold English in {dst_name}")
        if re.search(r"English legal (stems|corpus)", text):
            raise RuntimeError(f"leftover English legal phrasing in {dst_name}")
    # tip integrity
    if DST_TIP_SHORT not in text and ("TIP" in text or "tip" in text):
        if any(x in dst_name for x in ("soft_filter", "orchestrator", "bm25_smoke", "corpus", "encode", "package", "finish", "stream_graph", "upload", "write_publish")):
            if "TIP_SHORT" in text or "TIP_FULL" in text or "tip" in text.lower():
                if DST_TIP_SHORT not in text and SRC_TIP_SHORT in text:
                    raise RuntimeError(f"src tip leftover in {dst_name}")
    if SRC_TIP_SHORT in text:
        raise RuntimeError(f"src tip leftover in {dst_name}")
    if "67930c3f-c86b-" in text:
        raise RuntimeError(f"UUID c94b corrupted to c86b in {dst_name}")
    if DST_TIP_SHORT not in text and any(x in dst_name for x in ("soft_filter", "orchestrator", "bm25_smoke")):
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
    if entry.get("slug") == "benin" or entry.get("iso2") == "BJ":
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
            "language": "French",
            "lang": "French",
            "iso2": "BJ",
            "slug": "benin",
            "repo": "endomorphosis/ipfs_benin_laws",
            "years_attested": YEARS_ATTESTED,
            "gate_years": [int(y) for y in GATE_YEARS],
            "gate_stems": GATE_STEMS,
            "note": (
                f"BJ FIRST_IR scaffold; tip MATCH {DST_TIP_SHORT}@102/1900; {HOLD}; "
                f"soft never-thin ON; SKIP_US; Italy BLOCKED; {WAVE_POS}; "
                f"French GATE ({len(GATE_YEARS)} years + {len(GATE_STEMS)} stems)"
            ),
            "status": "CLAIMED",
            "mode": "FIRST_IR",
            "wave_end": False,
        })
        break
else:
    raise RuntimeError("Benin/BJ entry missing from wave JSON")

data["wave_status"] = "IN_PROGRESS_BJ"
data["hold"] = HOLD
data["current"] = "benin"
data["do_not_start_next"] = "somalia"
data["next"] = "somalia"
wave.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print("updated wave JSON Benin entry")
print("GATE years", GATE_YEARS)
print("GATE stems", GATE_STEMS)
print("n_gate", len(GATE_YEARS) + len(GATE_STEMS))
print("HOLD", HOLD)
print("GATE language: French years+stems")
