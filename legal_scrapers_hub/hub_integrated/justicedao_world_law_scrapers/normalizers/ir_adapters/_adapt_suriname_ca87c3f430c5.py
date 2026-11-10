#!/usr/bin/env python3
"""Adapt the Guinea-Bissau Portuguese memsafe FIRST_IR pack to Suriname SR tip ca87c3f430c5.

Dutch (Suriname); FIRST_IR; HOLD 0 STRICT after-GW (SR→GQ→GY→BJ→SO→MV).
Soft never-thin ON; SKIP_US; Italy BLOCKED. WAVE after_dj after GW LIVE
(…→GW LIVE → SR → GQ→GY→BJ→SO→MV), NOT wave end.
GATE: attested years + Dutch legal stems from data/articles.parquet tip ca87c3f430c5
(Dutch; include suriname/staat). URL www/gov.sr query-only, NOT GATE.
Source tip a8f9cc04584f (Guinea-Bissau Portuguese memsafe with data/ paths)
— override language Portuguese → Dutch (Suriname).
Keep data/articles.parquet + data/laws.parquet; agent-data not cient-data.
Do NOT start Equatorial Guinea/next after LIVE.
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
SRC_TIP_FULL = "a8f9cc04584f3e14a3f0558e8b9ea625c8262940"
SRC_TIP_SHORT = "a8f9cc04584f"
DST_TIP_FULL = "ca87c3f430c5cec11da9990f4112d7ef4f1986cc"
DST_TIP_SHORT = "ca87c3f430c5"
FLOOR_LAWS, FLOOR_ARTS = 94, 2164
SRC_FLOOR_L, SRC_FLOOR_A = 202, 2196

# Sampled from data/articles.parquet @ ca87c3f430c5 (~10 years + ~11 Dutch stems)
# Whole-word ASCII-fold FTS hits; laws=94 articles=2164.
# Top years by doc hits; stems from user list all attested (+ lid).
GATE_YEARS = [
    "2024", "2016", "2019", "2017", "2011",
    "2015", "2014", "2025", "2018", "2012",
]
GATE_STEMS = [
    "artikel", "wet", "besluit", "minister", "persoon", "code",
    "sectie", "republiek", "suriname", "staat", "lid",
]
YEARS_ATTESTED = [int(y) for y in GATE_YEARS] + [
    2020, 1992, 2013, 2010, 1995, 2023, 2002, 2022, 1986, 2009,
]
GATE_NOTE_YEARS = "/".join(GATE_YEARS)
GATE_NOTE_STEMS = "/".join(GATE_STEMS)
HOLD = "HOLD 0 STRICT after-GW (SR→GQ→GY→BJ→SO→MV)"
WAVE_POS = (
    "after GW LIVE of after_dj wave "
    "(…→GW LIVE → SR → GQ→GY→BJ→SO→MV; NOT wave end)"
)
DEST_CHAIN = "SR→GQ→GY→BJ→SO→MV"
SRC_HOLD = "HOLD 0 STRICT after-NU (GW→SR→GQ→GY→BJ→SO→MV)"
SRC_WAVE = (
    "after NU LIVE of after_dj wave "
    "(…→NU LIVE → GW → SR→GQ→GY→BJ→SO→MV; NOT wave end)"
)
SRC_CHAIN = "GW→SR→GQ→GY→BJ→SO→MV"

FILES = [
    ("guineabissau_soft_filter.py", "suriname_soft_filter.py"),
    (f"guineabissau_corpus_stream_{SRC_TIP_SHORT}.py", f"suriname_corpus_stream_{DST_TIP_SHORT}.py"),
    (f"guineabissau_encode_memsafe_{SRC_TIP_SHORT}.py", f"suriname_encode_memsafe_{DST_TIP_SHORT}.py"),
    (f"guineabissau_finish_from_emb_{SRC_TIP_SHORT}.py", f"suriname_finish_from_emb_{DST_TIP_SHORT}.py"),
    (f"guineabissau_stream_graph_parts_{SRC_TIP_SHORT}.py", f"suriname_stream_graph_parts_{DST_TIP_SHORT}.py"),
    (f"guineabissau_package_memsafe_{SRC_TIP_SHORT}.py", f"suriname_package_memsafe_{DST_TIP_SHORT}.py"),
    ("guineabissau_upload.py", "suriname_upload.py"),
    ("guineabissau_bm25_smoke.py", "suriname_bm25_smoke.py"),
    ("guineabissau_write_publish_report.py", "suriname_write_publish_report.py"),
    (f"guineabissau_orchestrator_{SRC_TIP_SHORT}.py", f"suriname_orchestrator_{DST_TIP_SHORT}.py"),
]


def adapt(text: str, dst_name: str) -> str:
    # Repair path corruption from prior adapts
    for bad in (
        "cient-data", "prent-data", "stent-data", "cvent-data", "scent-data",
        "carent-data", "yement-data", "djiboutient-data", "marshallislandsent-data",
        "kiribatient-data", "burundient-data", "eswatinient-data", "niueent-data",
        "guineabissauent-data", "surinameent-data",
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
    text = text.replace("after-NU", "\x00AFTERGW\x00")
    text = text.replace("after NU ", "\x00AFTERGW_SP\x00")
    text = text.replace("after_dj", "\x00AFTERDJ_US\x00")
    text = text.replace(
        "…→NU LIVE → GW → SR→GQ→GY→BJ→SO→MV",
        "\x00SRCCHAIN_FULL\x00",
    )
    text = text.replace("after NU LIVE of \x00AFTERDJ_US\x00 wave", "\x00DESTWAVE_SHORT\x00")
    text = text.replace("after NU LIVE of after_dj wave", "\x00DESTWAVE_SHORT\x00")
    text = text.replace("GW FIRST_IR", "\x00DESTFIRST\x00")

    reps = [
        (SRC_TIP_FULL, DST_TIP_FULL),
        (SRC_TIP_SHORT, DST_TIP_SHORT),
        ("endomorphosis/ipfs_guineabissau_laws", "endomorphosis/ipfs_suriname_laws"),
        ("justicedao/ipfs_guineabissau_laws_ir", "justicedao/ipfs_suriname_laws_ir"),
        ("ipfs_guineabissau_laws_ir", "ipfs_suriname_laws_ir"),
        ("ipfs_guineabissau_laws", "ipfs_suriname_laws"),
        # HOLD / wave restore
        ("\x00DESTHOLD\x00", HOLD),
        ("\x00DESTWAVE\x00", WAVE_POS),
        ("\x00DESTWAVE_SHORT\x00", WAVE_POS),
        ("\x00DESTCHAIN\x00", DEST_CHAIN),
        ("\x00SRCCHAIN_FULL\x00", "…→GW LIVE → SR → GQ→GY→BJ→SO→MV"),
        ("\x00AFTERGW\x00", "after-GW"),
        ("\x00AFTERGW_SP\x00", "after GW "),
        ("\x00DESTFIRST\x00", "SR FIRST_IR"),
        ("GW FIRST_IR (not wave end)", "SR FIRST_IR (not wave end)"),
        ("www/gov.gw", "www/gov.sr"),
        ("gov.gw", "gov.sr"),
        ("www.gov.gw", "www.gov.sr"),
        # Language / country — Portuguese → Dutch BEFORE bare Guinea-Bissau
        ("Portuguese (Guinea-Bissau)", "Dutch (Suriname)"),
        ("Portuguese Guinea-Bissau", "Dutch Suriname"),
        ("ASCII-fold Portuguese", "ASCII-fold Dutch"),
        ("Portuguese legal stems", "Dutch legal stems"),
        ("Portuguese legal corpus", "Dutch legal corpus"),
        ("Portuguese years+stems GATE", "Dutch years+stems GATE"),
        ("Portuguese GATE", "Dutch GATE"),
        ("language: Portuguese", "language: Dutch"),
        ("Language: Portuguese", "Language: Dutch"),
        ('"language": "Portuguese"', '"language": "Dutch"'),
        ('"lang": "Portuguese"', '"lang": "Dutch"'),
        ("Guinea-Bissau", "Suriname"),
        # slug / path forms BEFORE bare guineabissau
        ("guineabissau_ranked", "suriname_ranked"),
        ("guineabissau_gate", "suriname_gate"),
        ("guineabissau_pass", "suriname_pass"),
        ("guineabissau_encode_memsafe", "suriname_encode_memsafe"),
        ("guineabissau_package_memsafe", "suriname_package_memsafe"),
        ("guineabissau_corpus_stream", "suriname_corpus_stream"),
        ("guineabissau_encode_done", "suriname_encode_done"),
        ("guineabissau_filtered_", "suriname_filtered_"),
        ("guineabissau_", "suriname_"),
        # ISO whole-token / path forms only
        ('"GW"', '"SR"'),
        ("GW-attested", "SR-attested"),
        ("(GW)", "(SR)"),
        ('"gw"', '"sr"'),
        # floors 202/2196 → 94/2164
        ("202/2196", "94/2164"),
        ("202 / 2196", "94 / 2164"),
        ("202, 2196", "94, 2164"),
        ("FLOOR_LAWS, FLOOR_ARTS = 202, 2196", "FLOOR_LAWS, FLOOR_ARTS = 94, 2164"),
        ("or 202)", "or 94)"),
        ("or 202,", "or 94,"),
        ("or 202}", "or 94}"),
        ("= 202,", "= 94,"),
        ("= 202", "= 94"),
        ("@ 202/", "@ 94/"),
        (" 202/", " 94/"),
        ("floor 202/", "floor 94/"),
        ("(202/", "(94/"),
        (" or 202", " or 94"),
        (" 2196", " 2164"),
        ("2196", "2164"),
    ]
    for a, b in reps:
        text = text.replace(a, b)

    # Bare slug "guineabissau" → "suriname"
    text = re.sub(r"(?<![A-Za-z0-9_])guineabissau(?![A-Za-z0-9_])", "suriname", text)

    text = text.replace("\x00BM25\x00", "BM25").replace("\x00bm25\x00", "bm25")
    text = text.replace("\x00AFTERDJ_US\x00", "after_dj")
    text = text.replace("\x00DESTHOLD\x00", HOLD)
    text = text.replace("\x00DESTCHAIN\x00", DEST_CHAIN)
    text = text.replace("\x00DESTWAVE\x00", WAVE_POS)

    text = text.replace(
        "FLOOR_LAWS, FLOOR_ARTS = 202, 2164",
        "FLOOR_LAWS, FLOOR_ARTS = 94, 2164",
    )
    text = text.replace(
        "FLOOR_LAWS, FLOOR_ARTS = 94, 2196",
        "FLOOR_LAWS, FLOOR_ARTS = 94, 2164",
    )
    text = text.replace(
        'int(pack.get("n_articles") or 2196)',
        'int(pack.get("n_articles") or 2164)',
    )
    text = text.replace(
        'int(pack.get("n_articles") or 2164)',
        'int(pack.get("n_articles") or 2164)',
    )
    text = text.replace(
        'int(pack.get("n_laws") or 202)',
        'int(pack.get("n_laws") or 94)',
    )
    text = text.replace(
        'int(pack.get("n_laws") or 94)',
        'int(pack.get("n_laws") or 94)',
    )

    # display name / slug fixes
    text = text.replace('"name": "suriname"', '"name": "Suriname"')
    text = text.replace('"name": "Suriname"', '"name": "Suriname"')
    text = text.replace('"slug": "Suriname"', '"slug": "suriname"')
    text = text.replace('SLUG = "Suriname"', 'SLUG = "suriname"')
    text = text.replace('SLUG = "suriname"', 'SLUG = "suriname"')
    text = text.replace('"country": "Suriname"', '"country": "suriname"')
    text = text.replace('"country": "guineabissau"', '"country": "suriname"')

    # Ensure agent-data survived
    for bad in (
        "cient-data", "prent-data", "stent-data", "cvent-data", "scent-data",
        "carent-data", "yement-data", "djiboutient-data", "marshallislandsent-data",
        "kiribatient-data", "burundient-data", "eswatinient-data", "niueent-data",
        "guineabissauent-data", "surinameent-data",
    ):
        text = text.replace(f"/home/box/{bad}/", "/home/box/agent-data/")
        text = text.replace(bad, "agent-data")

    if dst_name == "suriname_bm25_smoke.py":
        start = text.index("GATE = [")
        end = text.index("]", start) + 1
        years_line = ", ".join(f'"{y}"' for y in GATE_YEARS)
        stems_line = ", ".join(f'"{s}"' for s in GATE_STEMS)
        gate = f"GATE = [\n    {years_line},\n    {stems_line},\n]"
        text = text[:start] + gate + text[end:]
        text = re.sub(
            r"QUERIES = GATE \+ \[[^\]]*\]",
            'QUERIES = GATE + ["www", "gov.sr", "www.gov.sr", "dna.sr", "www.dna.sr", "grondwet", "wetboek", "president", "regering", "nationale"]',
            text,
            count=1,
        )
        text = re.sub(
            r'"""BM25 smoke for Suriname IR.*?"""',
            '"""BM25 smoke for Suriname IR — Dutch legal corpus; years + Dutch legal stems FTS gate.\n\n'
            "GATE is attested ASCII years plus Dutch legal stems (ASCII-fold). URL www/gov.sr\n"
            "is query-only, never GATE. Every GATE token must rank a hit.\n"
            '"""',
            text,
            count=1,
            flags=re.S,
        )
        note = (
            f"attested years {GATE_NOTE_YEARS} plus Dutch legal stems {GATE_NOTE_STEMS} "
            f"from articles.parquet HEAD tip {DST_TIP_SHORT}; URL www/gov.sr is query-only, not GATE."
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

    if dst_name == "suriname_write_publish_report.py":
        gate_note = (
            f"BM25 PASS on Suriname ASCII-fold Dutch GATE "
            f"(attested years {GATE_NOTE_YEARS} + stems {GATE_NOTE_STEMS}); "
            f"URL www/gov.sr is query-only, not GATE"
        )
        text = re.sub(
            r'BM25 PASS on Suriname[^"]*"',
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
        text = text.replace("Portuguese years+stems GATE", "Dutch years+stems GATE")
        text = text.replace("English years+stems GATE", "Dutch years+stems GATE")
        text = text.replace("Portuguese legal stems GATE", "Dutch years+stems GATE")
        text = re.sub(
            r"HOLD 0 STRICT after-NU[^;]*; collectors kept dead \(pkill\); soft never-thin ON; SKIP_US; Italy BLOCKED;[^\"\n]*",
            f"{HOLD}; collectors kept dead (pkill); soft never-thin ON; SKIP_US; Italy BLOCKED; {WAVE_POS}",
            text,
        )
        text = re.sub(
            r"HOLD 0 STRICT after-GW[^;]*; collectors kept dead \(pkill\); soft never-thin ON; SKIP_US; Italy BLOCKED;[^\"\n]*",
            f"{HOLD}; collectors kept dead (pkill); soft never-thin ON; SKIP_US; Italy BLOCKED; {WAVE_POS}",
            text,
        )
        text = text.replace("www/gov.gw is query-only", "www/gov.sr is query-only")
        text = text.replace("www/gov.sr is query-only", "www/gov.sr is query-only")
        text = re.sub(r"[ \t]{2,}", " ", text)

    leftovers = (
        "Guinea-Bissau", "guineabissau",
        "Niue", "niue",
        "cient-data", "prent-data", "stent-data", "cvent-data", "scent-data",
        "carent-data", "yement-data", "djiboutient-data", "marshallislandsent-data",
        "kiribatient-data", "burundient-data", "eswatinient-data", "niueent-data",
        "guineabissauent-data", "surinameent-data",
        "gov.gw", "www.gov.gw",
        "Portuguese",
    )
    found = []
    for x in leftovers:
        if x == "guineabissau":
            if re.search(r"(?<![A-Za-z0-9_])guineabissau(?![A-Za-z0-9_])", text):
                found.append(x)
            continue
        if x == "niue":
            if re.search(r"(?<![A-Za-z0-9_])niue(?![A-Za-z0-9_])", text):
                found.append(x)
            continue
        if x == "Portuguese":
            # allow only if somehow residual without Dutch rewrite — reject all Portuguese
            if "Portuguese" in text:
                found.append(x)
            continue
        if x in text:
            found.append(x)
    if found:
        raise RuntimeError(f"language/country leftovers in {dst_name}: {found}")

    # Reject GW leftovers in GATE; require Dutch stems
    if dst_name.endswith("_bm25_smoke.py"):
        gate_slice = text[text.index("GATE = ["): text.index("]", text.index("GATE = [")) + 1]
        for bad in (
            "guineabissau", "guine", "bissau", "artigo", "lei", "decreto", "codigo",
            "seccao", "republica", "estado", "pessoa", "governo",
            "article", "section", "act", "law", "person", "republic",
            "niue", "eswatini", "kingdom",
            "loi", "decret", "ministre",
        ):
            if f'"{bad}"' in gate_slice:
                raise RuntimeError(f"non-SR token in GATE of {dst_name}: {bad}")
        for stem in GATE_STEMS:
            if f'"{stem}"' not in gate_slice:
                raise RuntimeError(f"missing Dutch stem in GATE of {dst_name}: {stem}")
        for year in GATE_YEARS:
            if f'"{year}"' not in gate_slice:
                raise RuntimeError(f"missing year in GATE of {dst_name}: {year}")
        if '", "gw"' in text or '", "GW"' in text:
            raise RuntimeError(f"leftover gw query token in {dst_name}")
        if "gov.gw" in text:
            raise RuntimeError(f"leftover gov.gw in {dst_name}")
        if re.search(r"Portuguese legal", text):
            raise RuntimeError(f"leftover Portuguese legal phrasing in {dst_name}")

    # reject bare guineabissau / GW leftovers outside protected HOLD/wave
    scrub = text
    scrub = scrub.replace(WAVE_POS, "XX")
    scrub = scrub.replace(HOLD, "XX")
    scrub = scrub.replace(DEST_CHAIN, "XX")
    scrub = scrub.replace(SRC_CHAIN, "XX")
    scrub = scrub.replace(SRC_HOLD, "XX")
    scrub = scrub.replace(SRC_WAVE, "XX")
    scrub = scrub.replace("after-GW", "after-XX")
    scrub = scrub.replace("after GW ", "after XX ")
    scrub = scrub.replace("after_dj", "after_xx")
    scrub = scrub.replace("GW LIVE", "XX LIVE")
    scrub = scrub.replace("GW→", "XX→")
    scrub = scrub.replace("…→GW", "…→XX")
    if re.search(r"(?<![A-Za-z0-9_])guineabissau(?![A-Za-z0-9_])", scrub):
        m = re.search(r"(?<![A-Za-z0-9_])guineabissau(?![A-Za-z0-9_])", scrub)
        raise RuntimeError(
            f"leftover guineabissau in {dst_name}: ...{scrub[max(0, m.start()-20):m.start()+20]}..."
        )
    if re.search(r"(?<![A-Za-z%])GW(?![A-Za-z])", scrub):
        m = re.search(r"(?<![A-Za-z%])GW(?![A-Za-z])", scrub)
        raise RuntimeError(
            f"leftover GW in {dst_name}: ...{scrub[max(0, m.start()-30):m.start()+30]}..."
        )
    if "ipfs_guineabissau" in text:
        raise RuntimeError(f"leftover guineabissau path in {dst_name}")
    if "agent-data" not in text and "SECRET" in text.upper():
        if any(x in dst_name for x in ("soft_filter", "upload", "orchestrator")):
            if "/home/box/" in text and "agent-data" not in text:
                raise RuntimeError(f"missing agent-data secret path in {dst_name}")
    # data/ paths must survive
    if "soft_filter" in dst_name or "corpus_stream" in dst_name:
        if "data/laws.parquet" not in text and 'data" / "laws.parquet"' not in text:
            if '"data"' not in text and "/data/" not in text:
                raise RuntimeError(f"missing data/ parquet paths in {dst_name}")
    # reject residual Portuguese GATE language labels in publish/smoke
    if "write_publish" in dst_name or "bm25_smoke" in dst_name:
        if re.search(r"ASCII-fold Portuguese", text):
            raise RuntimeError(f"leftover ASCII-fold Portuguese in {dst_name}")
        if re.search(r"Portuguese legal (stems|corpus)", text):
            raise RuntimeError(f"leftover Portuguese legal phrasing in {dst_name}")
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
    if entry.get("slug") == "suriname" or entry.get("iso2") == "SR":
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
            "language": "Dutch",
            "lang": "Dutch",
            "iso2": "SR",
            "slug": "suriname",
            "repo": "endomorphosis/ipfs_suriname_laws",
            "years_attested": YEARS_ATTESTED,
            "gate_years": [int(y) for y in GATE_YEARS],
            "gate_stems": GATE_STEMS,
            "note": (
                f"SR FIRST_IR scaffold; tip MATCH {DST_TIP_SHORT}@94/2164; {HOLD}; "
                f"soft never-thin ON; SKIP_US; Italy BLOCKED; {WAVE_POS}; "
                f"Dutch GATE ({len(GATE_YEARS)} years + {len(GATE_STEMS)} stems)"
            ),
            "status": "CLAIMED",
            "mode": "FIRST_IR",
            "wave_end": False,
        })
        break
else:
    raise RuntimeError("Suriname/SR entry missing from wave JSON")

data["wave_status"] = "IN_PROGRESS_SR"
data["hold"] = HOLD
data["current"] = "suriname"
data["do_not_start_next"] = "equatorialguinea"
data["next"] = "equatorialguinea"
wave.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print("updated wave JSON Suriname entry")
print("GATE years", GATE_YEARS)
print("GATE stems", GATE_STEMS)
print("n_gate", len(GATE_YEARS) + len(GATE_STEMS))
print("HOLD", HOLD)
print("GATE language: Dutch years+stems")
