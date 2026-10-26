#!/usr/bin/env python3
"""Adapt the Niue English memsafe FIRST_IR pack to Guinea-Bissau GW tip a8f9cc04584f.

Portuguese Guinea-Bissau; FIRST_IR; HOLD 0 STRICT after-NU (GW→SR→GQ→GY→BJ→SO→MV).
Soft never-thin ON; SKIP_US; Italy BLOCKED. WAVE after_dj after NU LIVE
(…→NU LIVE → GW → SR→GQ→GY→BJ→SO→MV), NOT wave end.
GATE: attested years + Portuguese legal stems from data/articles.parquet tip a8f9cc04584f
(Portuguese; include guine/bissau). URL www/gov.gw query-only, NOT GATE.
Source tip 097999244810 (Niue English memsafe with data/ paths)
— override language English → Portuguese (Guinea-Bissau).
Keep data/articles.parquet + data/laws.parquet; agent-data not cient-data.
Do NOT start Suriname/next after LIVE.
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
SRC_TIP_FULL = "0979992448108b95d6d92fc645eeb752f69e93c2"
SRC_TIP_SHORT = "097999244810"
DST_TIP_FULL = "a8f9cc04584f3e14a3f0558e8b9ea625c8262940"
DST_TIP_SHORT = "a8f9cc04584f"
FLOOR_LAWS, FLOOR_ARTS = 202, 2196
SRC_FLOOR_L, SRC_FLOOR_A = 99, 2261

# Sampled from data/articles.parquet @ a8f9cc04584f (~10 years + ~11 Portuguese stems)
# Whole-word ASCII-fold FTS hits; laws=202 articles=2196.
# Top years by doc hits; stems from user list all attested.
GATE_YEARS = [
    "2020", "2018", "2022", "2021", "2023",
    "2025", "2024", "2017", "2015", "2016",
]
GATE_STEMS = [
    "artigo", "lei", "decreto", "codigo", "seccao", "republica",
    "guine", "bissau", "estado", "pessoa", "governo",
]
YEARS_ATTESTED = [int(y) for y in GATE_YEARS] + [
    2009, 2010, 2019, 2011, 2008, 2026, 2000, 2007, 2005, 2012,
]
GATE_NOTE_YEARS = "/".join(GATE_YEARS)
GATE_NOTE_STEMS = "/".join(GATE_STEMS)
HOLD = "HOLD 0 STRICT after-NU (GW→SR→GQ→GY→BJ→SO→MV)"
WAVE_POS = (
    "after NU LIVE of after_dj wave "
    "(…→NU LIVE → GW → SR→GQ→GY→BJ→SO→MV; NOT wave end)"
)
DEST_CHAIN = "GW→SR→GQ→GY→BJ→SO→MV"
SRC_HOLD = "HOLD 0 STRICT after-SZ (NU→GW→SR→GQ→GY→BJ→SO→MV)"
SRC_WAVE = (
    "after SZ LIVE of after_dj wave "
    "(…→SZ LIVE → NU → GW→SR→GQ→GY→BJ→SO→MV; NOT wave end)"
)
SRC_CHAIN = "NU→GW→SR→GQ→GY→BJ→SO→MV"

FILES = [
    ("niue_soft_filter.py", "guineabissau_soft_filter.py"),
    (f"niue_corpus_stream_{SRC_TIP_SHORT}.py", f"guineabissau_corpus_stream_{DST_TIP_SHORT}.py"),
    (f"niue_encode_memsafe_{SRC_TIP_SHORT}.py", f"guineabissau_encode_memsafe_{DST_TIP_SHORT}.py"),
    (f"niue_finish_from_emb_{SRC_TIP_SHORT}.py", f"guineabissau_finish_from_emb_{DST_TIP_SHORT}.py"),
    (f"niue_stream_graph_parts_{SRC_TIP_SHORT}.py", f"guineabissau_stream_graph_parts_{DST_TIP_SHORT}.py"),
    (f"niue_package_memsafe_{SRC_TIP_SHORT}.py", f"guineabissau_package_memsafe_{DST_TIP_SHORT}.py"),
    ("niue_upload.py", "guineabissau_upload.py"),
    ("niue_bm25_smoke.py", "guineabissau_bm25_smoke.py"),
    ("niue_write_publish_report.py", "guineabissau_write_publish_report.py"),
    (f"niue_orchestrator_{SRC_TIP_SHORT}.py", f"guineabissau_orchestrator_{DST_TIP_SHORT}.py"),
]


def adapt(text: str, dst_name: str) -> str:
    # Repair path corruption from prior adapts
    for bad in (
        "cient-data", "prent-data", "stent-data", "cvent-data", "scent-data",
        "carent-data", "yement-data", "djiboutient-data", "marshallislandsent-data",
        "kiribatient-data", "burundient-data", "eswatinient-data", "niueent-data",
        "guineabissauent-data",
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
    text = text.replace("after-SZ", "\x00AFTERNU\x00")
    text = text.replace("after SZ ", "\x00AFTERNU_SP\x00")
    text = text.replace("after_dj", "\x00AFTERDJ_US\x00")
    text = text.replace(
        "…→SZ LIVE → NU → GW→SR→GQ→GY→BJ→SO→MV",
        "\x00SRCCHAIN_FULL\x00",
    )
    text = text.replace("after SZ LIVE of \x00AFTERDJ_US\x00 wave", "\x00DESTWAVE_SHORT\x00")
    text = text.replace("after SZ LIVE of after_dj wave", "\x00DESTWAVE_SHORT\x00")
    text = text.replace("NU FIRST_IR", "\x00DESTFIRST\x00")

    reps = [
        (SRC_TIP_FULL, DST_TIP_FULL),
        (SRC_TIP_SHORT, DST_TIP_SHORT),
        ("endomorphosis/ipfs_niue_laws", "endomorphosis/ipfs_guineabissau_laws"),
        ("justicedao/ipfs_niue_laws_ir", "justicedao/ipfs_guineabissau_laws_ir"),
        ("ipfs_niue_laws_ir", "ipfs_guineabissau_laws_ir"),
        ("ipfs_niue_laws", "ipfs_guineabissau_laws"),
        # HOLD / wave restore
        ("\x00DESTHOLD\x00", HOLD),
        ("\x00DESTWAVE\x00", WAVE_POS),
        ("\x00DESTWAVE_SHORT\x00", WAVE_POS),
        ("\x00DESTCHAIN\x00", DEST_CHAIN),
        ("\x00SRCCHAIN_FULL\x00", "…→NU LIVE → GW → SR→GQ→GY→BJ→SO→MV"),
        ("\x00AFTERNU\x00", "after-NU"),
        ("\x00AFTERNU_SP\x00", "after NU "),
        ("\x00DESTFIRST\x00", "GW FIRST_IR"),
        ("NU FIRST_IR (not wave end)", "GW FIRST_IR (not wave end)"),
        ("www/gov.nu", "www/gov.gw"),
        ("gov.nu", "gov.gw"),
        ("www.gov.nu", "www.gov.gw"),
        # Language / country — English → Portuguese BEFORE bare Niue
        ("English (Niue)", "Portuguese (Guinea-Bissau)"),
        ("English Niue", "Portuguese Guinea-Bissau"),
        ("ASCII-fold English", "ASCII-fold Portuguese"),
        ("English legal stems", "Portuguese legal stems"),
        ("English legal corpus", "Portuguese legal corpus"),
        ("English years+stems GATE", "Portuguese years+stems GATE"),
        ("English GATE", "Portuguese GATE"),
        ("language: English", "language: Portuguese"),
        ("Language: English", "Language: Portuguese"),
        ('"language": "English"', '"language": "Portuguese"'),
        ('"lang": "English"', '"lang": "Portuguese"'),
        ("Niue", "Guinea-Bissau"),
        # slug / path forms BEFORE bare niue
        ("niue_ranked", "guineabissau_ranked"),
        ("niue_gate", "guineabissau_gate"),
        ("niue_pass", "guineabissau_pass"),
        ("niue_encode_memsafe", "guineabissau_encode_memsafe"),
        ("niue_package_memsafe", "guineabissau_package_memsafe"),
        ("niue_corpus_stream", "guineabissau_corpus_stream"),
        ("niue_encode_done", "guineabissau_encode_done"),
        ("niue_filtered_", "guineabissau_filtered_"),
        ("niue_", "guineabissau_"),
        # ISO whole-token / path forms only
        ('"NU"', '"GW"'),
        ("NU-attested", "GW-attested"),
        ("(NU)", "(GW)"),
        ('"nu"', '"gw"'),
        # floors 99/2261 → 202/2196
        ("99/2261", "202/2196"),
        ("99 / 2261", "202 / 2196"),
        ("99, 2261", "202, 2196"),
        ("FLOOR_LAWS, FLOOR_ARTS = 99, 2261", "FLOOR_LAWS, FLOOR_ARTS = 202, 2196"),
        ("or 99)", "or 202)"),
        ("or 99,", "or 202,"),
        ("or 99}", "or 202}"),
        ("= 99,", "= 202,"),
        ("= 99", "= 202"),
        ("@ 99/", "@ 202/"),
        (" 99/", " 202/"),
        ("floor 99/", "floor 202/"),
        ("(99/", "(202/"),
        (" or 99", " or 202"),
        (" 2261", " 2196"),
        ("2261", "2196"),
    ]
    for a, b in reps:
        text = text.replace(a, b)

    # Bare slug "niue" → "guineabissau"
    text = re.sub(r"(?<![A-Za-z0-9_])niue(?![A-Za-z0-9_])", "guineabissau", text)

    text = text.replace("\x00BM25\x00", "BM25").replace("\x00bm25\x00", "bm25")
    text = text.replace("\x00AFTERDJ_US\x00", "after_dj")
    text = text.replace("\x00DESTHOLD\x00", HOLD)
    text = text.replace("\x00DESTCHAIN\x00", DEST_CHAIN)
    text = text.replace("\x00DESTWAVE\x00", WAVE_POS)

    text = text.replace(
        "FLOOR_LAWS, FLOOR_ARTS = 99, 2196",
        "FLOOR_LAWS, FLOOR_ARTS = 202, 2196",
    )
    text = text.replace(
        "FLOOR_LAWS, FLOOR_ARTS = 202, 2261",
        "FLOOR_LAWS, FLOOR_ARTS = 202, 2196",
    )
    text = text.replace(
        'int(pack.get("n_articles") or 2261)',
        'int(pack.get("n_articles") or 2196)',
    )
    text = text.replace(
        'int(pack.get("n_articles") or 2196)',
        'int(pack.get("n_articles") or 2196)',
    )
    text = text.replace(
        'int(pack.get("n_laws") or 99)',
        'int(pack.get("n_laws") or 202)',
    )
    text = text.replace(
        'int(pack.get("n_laws") or 202)',
        'int(pack.get("n_laws") or 202)',
    )

    # display name / slug fixes
    text = text.replace('"name": "guineabissau"', '"name": "Guinea-Bissau"')
    text = text.replace('"name": "Guinea-Bissau"', '"name": "Guinea-Bissau"')
    text = text.replace('"slug": "Guinea-Bissau"', '"slug": "guineabissau"')
    text = text.replace('SLUG = "Guinea-Bissau"', 'SLUG = "guineabissau"')
    text = text.replace('SLUG = "guineabissau"', 'SLUG = "guineabissau"')
    text = text.replace('"country": "Guinea-Bissau"', '"country": "guineabissau"')
    text = text.replace('"country": "niue"', '"country": "guineabissau"')

    # Ensure agent-data survived
    for bad in (
        "cient-data", "prent-data", "stent-data", "cvent-data", "scent-data",
        "carent-data", "yement-data", "djiboutient-data", "marshallislandsent-data",
        "kiribatient-data", "burundient-data", "eswatinient-data", "niueent-data",
        "guineabissauent-data",
    ):
        text = text.replace(f"/home/box/{bad}/", "/home/box/agent-data/")
        text = text.replace(bad, "agent-data")

    if dst_name == "guineabissau_bm25_smoke.py":
        start = text.index("GATE = [")
        end = text.index("]", start) + 1
        years_line = ", ".join(f'"{y}"' for y in GATE_YEARS)
        stems_line = ", ".join(f'"{s}"' for s in GATE_STEMS)
        gate = f"GATE = [\n    {years_line},\n    {stems_line},\n]"
        text = text[:start] + gate + text[end:]
        text = re.sub(
            r"QUERIES = GATE \+ \[[^\]]*\]",
            'QUERIES = GATE + ["www", "gov.gw", "www.gov.gw", "governo", "tribunal", "justica", "penal", "assembleia", "constituicao", "parlamento"]',
            text,
            count=1,
        )
        text = re.sub(
            r'"""BM25 smoke for Guinea-Bissau IR.*?"""',
            '"""BM25 smoke for Guinea-Bissau IR — Portuguese legal corpus; years + Portuguese legal stems FTS gate.\n\n'
            "GATE is attested ASCII years plus Portuguese legal stems (ASCII-fold). URL www/gov.gw\n"
            "is query-only, never GATE. Every GATE token must rank a hit.\n"
            '"""',
            text,
            count=1,
            flags=re.S,
        )
        note = (
            f"attested years {GATE_NOTE_YEARS} plus Portuguese legal stems {GATE_NOTE_STEMS} "
            f"from articles.parquet HEAD tip {DST_TIP_SHORT}; URL www/gov.gw is query-only, not GATE."
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
        # kill leftover English stem references outside GATE already replaced
        for eng in (
            "article", "section", "act", "law", "person", "republic",
            "code", "minister", "government", "constitution", "ordinance",
            "parliament", "assembly", "chapter", "shall",
        ):
            # only replace quoted leftover English GATE/query tokens that shouldn't remain
            pass

    if dst_name == "guineabissau_write_publish_report.py":
        gate_note = (
            f"BM25 PASS on Guinea-Bissau ASCII-fold Portuguese GATE "
            f"(attested years {GATE_NOTE_YEARS} + stems {GATE_NOTE_STEMS}); "
            f"URL www/gov.gw is query-only, not GATE"
        )
        text = re.sub(
            r'BM25 PASS on Guinea-Bissau[^"]*"',
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
        text = text.replace("French years+stems GATE", "Portuguese years+stems GATE")
        text = text.replace("English years+stems GATE", "Portuguese years+stems GATE")
        text = text.replace("English legal stems GATE", "Portuguese years+stems GATE")
        text = re.sub(
            r"HOLD 0 STRICT after-SZ[^;]*; collectors kept dead \(pkill\); soft never-thin ON; SKIP_US; Italy BLOCKED;[^\"\n]*",
            f"{HOLD}; collectors kept dead (pkill); soft never-thin ON; SKIP_US; Italy BLOCKED; {WAVE_POS}",
            text,
        )
        text = re.sub(
            r"HOLD 0 STRICT after-NU[^;]*; collectors kept dead \(pkill\); soft never-thin ON; SKIP_US; Italy BLOCKED;[^\"\n]*",
            f"{HOLD}; collectors kept dead (pkill); soft never-thin ON; SKIP_US; Italy BLOCKED; {WAVE_POS}",
            text,
        )
        text = text.replace("www/gov.nu is query-only", "www/gov.gw is query-only")
        text = text.replace("www/gov.gw is query-only", "www/gov.gw is query-only")
        text = re.sub(r"[ \t]{2,}", " ", text)

    leftovers = (
        "Niue", "niue",
        "Eswatini", "eswatini",
        "cient-data", "prent-data", "stent-data", "cvent-data", "scent-data",
        "carent-data", "yement-data", "djiboutient-data", "marshallislandsent-data",
        "kiribatient-data", "burundient-data", "eswatinient-data", "niueent-data",
        "guineabissauent-data",
        "gov.nu", "www.gov.nu",
    )
    found = []
    for x in leftovers:
        if x == "niue":
            if re.search(r"(?<![A-Za-z0-9_])niue(?![A-Za-z0-9_])", text):
                found.append(x)
            continue
        if x == "eswatini":
            if re.search(r"(?<![A-Za-z0-9_])eswatini(?![A-Za-z0-9_])", text):
                found.append(x)
            continue
        if x in text:
            found.append(x)
    if found:
        raise RuntimeError(f"language/country leftovers in {dst_name}: {found}")

    # Reject NU leftovers in GATE; require Portuguese stems
    if dst_name.endswith("_bm25_smoke.py"):
        gate_slice = text[text.index("GATE = ["): text.index("]", text.index("GATE = [")) + 1]
        for bad in (
            "niue", "article", "section", "act", "law", "person", "republic",
            "code", "minister", "government", "constitution",
            "eswatini", "kingdom",
            "loi", "decret", "ministre",
        ):
            if f'"{bad}"' in gate_slice:
                raise RuntimeError(f"non-GW token in GATE of {dst_name}: {bad}")
        for stem in GATE_STEMS:
            if f'"{stem}"' not in gate_slice:
                raise RuntimeError(f"missing Portuguese stem in GATE of {dst_name}: {stem}")
        for year in GATE_YEARS:
            if f'"{year}"' not in gate_slice:
                raise RuntimeError(f"missing year in GATE of {dst_name}: {year}")
        if '", "nu"' in text or '", "NU"' in text:
            raise RuntimeError(f"leftover nu query token in {dst_name}")
        if "gov.nu" in text:
            raise RuntimeError(f"leftover gov.nu in {dst_name}")
        if "English" in text and "Portuguese" not in text.split("English")[0][-40:]:
            # allow only if somehow residual English without Portuguese rewrite
            if re.search(r"English legal", text):
                raise RuntimeError(f"leftover English legal phrasing in {dst_name}")

    # reject bare niue / NU leftovers outside protected HOLD/wave
    scrub = text
    scrub = scrub.replace(WAVE_POS, "XX")
    scrub = scrub.replace(HOLD, "XX")
    scrub = scrub.replace(DEST_CHAIN, "XX")
    scrub = scrub.replace(SRC_CHAIN, "XX")
    scrub = scrub.replace(SRC_HOLD, "XX")
    scrub = scrub.replace(SRC_WAVE, "XX")
    scrub = scrub.replace("after-NU", "after-XX")
    scrub = scrub.replace("after NU ", "after XX ")
    scrub = scrub.replace("after_dj", "after_xx")
    scrub = scrub.replace("NU LIVE", "XX LIVE")
    scrub = scrub.replace("NU→", "XX→")
    scrub = scrub.replace("…→NU", "…→XX")
    if re.search(r"(?<![A-Za-z0-9_])niue(?![A-Za-z0-9_])", scrub):
        m = re.search(r"(?<![A-Za-z0-9_])niue(?![A-Za-z0-9_])", scrub)
        raise RuntimeError(
            f"leftover niue in {dst_name}: ...{scrub[max(0, m.start()-20):m.start()+20]}..."
        )
    if re.search(r"(?<![A-Za-z%])NU(?![A-Za-z])", scrub):
        m = re.search(r"(?<![A-Za-z%])NU(?![A-Za-z])", scrub)
        raise RuntimeError(
            f"leftover NU in {dst_name}: ...{scrub[max(0, m.start()-30):m.start()+30]}..."
        )
    if "ipfs_niue" in text:
        raise RuntimeError(f"leftover niue path in {dst_name}")
    if "agent-data" not in text and "SECRET" in text.upper():
        if any(x in dst_name for x in ("soft_filter", "upload", "orchestrator")):
            if "/home/box/" in text and "agent-data" not in text:
                raise RuntimeError(f"missing agent-data secret path in {dst_name}")
    # data/ paths must survive
    if "soft_filter" in dst_name or "corpus_stream" in dst_name:
        if "data/laws.parquet" not in text and 'data" / "laws.parquet"' not in text:
            if '"data"' not in text and "/data/" not in text:
                raise RuntimeError(f"missing data/ parquet paths in {dst_name}")
    # reject residual English GATE language labels in publish/smoke
    if "write_publish" in dst_name or "bm25_smoke" in dst_name:
        if re.search(r"ASCII-fold English", text):
            raise RuntimeError(f"leftover ASCII-fold English in {dst_name}")
        if re.search(r"English legal (stems|corpus)", text):
            raise RuntimeError(f"leftover English legal phrasing in {dst_name}")
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
    if entry.get("slug") == "guineabissau" or entry.get("iso2") == "GW":
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
            "language": "Portuguese",
            "lang": "Portuguese",
            "iso2": "GW",
            "slug": "guineabissau",
            "repo": "endomorphosis/ipfs_guineabissau_laws",
            "years_attested": YEARS_ATTESTED,
            "gate_years": [int(y) for y in GATE_YEARS],
            "gate_stems": GATE_STEMS,
            "note": (
                f"GW FIRST_IR scaffold; tip MATCH {DST_TIP_SHORT}@202/2196; {HOLD}; "
                f"soft never-thin ON; SKIP_US; Italy BLOCKED; {WAVE_POS}; "
                f"Portuguese GATE ({len(GATE_YEARS)} years + {len(GATE_STEMS)} stems)"
            ),
            "status": "CLAIMED",
            "mode": "FIRST_IR",
            "wave_end": False,
        })
        break
else:
    raise RuntimeError("Guinea-Bissau/GW entry missing from wave JSON")

data["wave_status"] = "IN_PROGRESS_GW"
data["hold"] = HOLD
data["current"] = "guineabissau"
data["do_not_start_next"] = "suriname"
data["next"] = "suriname"
wave.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print("updated wave JSON Guinea-Bissau entry")
print("GATE years", GATE_YEARS)
print("GATE stems", GATE_STEMS)
print("n_gate", len(GATE_YEARS) + len(GATE_STEMS))
print("HOLD", HOLD)
print("GATE language: Portuguese years+stems")
