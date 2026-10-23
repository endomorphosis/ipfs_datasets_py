#!/usr/bin/env python3
"""Adapt the Burundi French memsafe FIRST_IR pack to Eswatini SZ tip 7076fc82ba00.

English Eswatini; FIRST_IR; HOLD 0 STRICT after-BI (SZ→NU→GW→SR→GQ→GY→BJ→SO→MV).
Soft never-thin ON; SKIP_US; Italy BLOCKED. WAVE after_dj after BI LIVE
(…→BI LIVE → SZ → NU→GW→SR→GQ→GY→BJ→SO→MV), NOT wave end.
GATE: attested years + English legal stems from data/articles.parquet tip 7076fc82ba00
(English; include eswatini/kingdom). URL www/gov.sz query-only, NOT GATE.
Source tip b5768508c9ba (Burundi French memsafe with data/ paths)
— override language to English (Eswatini); GATE English years+stems.
Keep data/articles.parquet + data/laws.parquet; agent-data not cient-data.
Do NOT start Niue/next after LIVE.
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
SRC_TIP_FULL = "b5768508c9ba7906cd5b405b6de571cd4a82962c"
SRC_TIP_SHORT = "b5768508c9ba"
DST_TIP_FULL = "7076fc82ba0086d8509136c03535cf82cd960801"
DST_TIP_SHORT = "7076fc82ba00"
FLOOR_LAWS, FLOOR_ARTS = 56, 2385
SRC_FLOOR_L, SRC_FLOOR_A = 79, 2418

# Sampled from data/articles.parquet @ 7076fc82ba00 (~10 years + ~11 English stems)
# Whole-word ASCII-fold FTS hits; laws=56 articles=2385.
# Top years by doc hits; stems from user list all attested.
GATE_YEARS = [
    "2022", "2023", "2017", "2021", "2020",
    "1993", "2019", "2001", "2024", "2015",
]
GATE_STEMS = [
    "article", "section", "act", "law", "person", "republic",
    "code", "eswatini", "kingdom", "minister", "government",
]
YEARS_ATTESTED = [int(y) for y in GATE_YEARS] + [
    2010, 2011, 2000, 2014, 2016, 2005, 2018, 1975, 1964, 2012,
]
GATE_NOTE_YEARS = "/".join(GATE_YEARS)
GATE_NOTE_STEMS = "/".join(GATE_STEMS)
HOLD = "HOLD 0 STRICT after-BI (SZ→NU→GW→SR→GQ→GY→BJ→SO→MV)"
WAVE_POS = (
    "after BI LIVE of after_dj wave "
    "(…→BI LIVE → SZ → NU→GW→SR→GQ→GY→BJ→SO→MV; NOT wave end)"
)
DEST_CHAIN = "SZ→NU→GW→SR→GQ→GY→BJ→SO→MV"
SRC_HOLD = "HOLD 0 STRICT after-KI (BI→SZ→NU→GW→SR→GQ→GY→BJ→SO→MV)"
SRC_WAVE = (
    "after KI LIVE of after_dj wave "
    "(…→KI LIVE → BI → SZ→NU→GW→SR→GQ→GY→BJ→SO→MV; NOT wave end)"
)
SRC_CHAIN = "BI→SZ→NU→GW→SR→GQ→GY→BJ→SO→MV"

FILES = [
    ("burundi_soft_filter.py", "eswatini_soft_filter.py"),
    (f"burundi_corpus_stream_{SRC_TIP_SHORT}.py", f"eswatini_corpus_stream_{DST_TIP_SHORT}.py"),
    (f"burundi_encode_memsafe_{SRC_TIP_SHORT}.py", f"eswatini_encode_memsafe_{DST_TIP_SHORT}.py"),
    (f"burundi_finish_from_emb_{SRC_TIP_SHORT}.py", f"eswatini_finish_from_emb_{DST_TIP_SHORT}.py"),
    (f"burundi_stream_graph_parts_{SRC_TIP_SHORT}.py", f"eswatini_stream_graph_parts_{DST_TIP_SHORT}.py"),
    (f"burundi_package_memsafe_{SRC_TIP_SHORT}.py", f"eswatini_package_memsafe_{DST_TIP_SHORT}.py"),
    ("burundi_upload.py", "eswatini_upload.py"),
    ("burundi_bm25_smoke.py", "eswatini_bm25_smoke.py"),
    ("burundi_write_publish_report.py", "eswatini_write_publish_report.py"),
    (f"burundi_orchestrator_{SRC_TIP_SHORT}.py", f"eswatini_orchestrator_{DST_TIP_SHORT}.py"),
]


def adapt(text: str, dst_name: str) -> str:
    # Repair path corruption from prior adapts
    for bad in (
        "cient-data", "prent-data", "stent-data", "cvent-data", "scent-data",
        "carent-data", "yement-data", "djiboutient-data", "marshallislandsent-data",
        "kiribatient-data", "burundient-data", "eswatinient-data",
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
    text = text.replace("after-KI", "\x00AFTERBI\x00")
    text = text.replace("after KI ", "\x00AFTERBI_SP\x00")
    text = text.replace("after_dj", "\x00AFTERDJ_US\x00")
    text = text.replace(
        "…→KI LIVE → BI → SZ→NU→GW→SR→GQ→GY→BJ→SO→MV",
        "\x00SRCCHAIN_FULL\x00",
    )
    text = text.replace("after KI LIVE of \x00AFTERDJ_US\x00 wave", "\x00DESTWAVE_SHORT\x00")
    text = text.replace("after KI LIVE of after_dj wave", "\x00DESTWAVE_SHORT\x00")
    text = text.replace("BI FIRST_IR", "\x00DESTFIRST\x00")

    reps = [
        (SRC_TIP_FULL, DST_TIP_FULL),
        (SRC_TIP_SHORT, DST_TIP_SHORT),
        ("endomorphosis/ipfs_burundi_laws", "endomorphosis/ipfs_eswatini_laws"),
        ("justicedao/ipfs_burundi_laws_ir", "justicedao/ipfs_eswatini_laws_ir"),
        ("ipfs_burundi_laws_ir", "ipfs_eswatini_laws_ir"),
        ("ipfs_burundi_laws", "ipfs_eswatini_laws"),
        # HOLD / wave restore
        ("\x00DESTHOLD\x00", HOLD),
        ("\x00DESTWAVE\x00", WAVE_POS),
        ("\x00DESTWAVE_SHORT\x00", WAVE_POS),
        ("\x00DESTCHAIN\x00", DEST_CHAIN),
        ("\x00SRCCHAIN_FULL\x00", "…→BI LIVE → SZ → NU→GW→SR→GQ→GY→BJ→SO→MV"),
        ("\x00AFTERBI\x00", "after-BI"),
        ("\x00AFTERBI_SP\x00", "after BI "),
        ("\x00DESTFIRST\x00", "SZ FIRST_IR"),
        ("BI FIRST_IR (not wave end)", "SZ FIRST_IR (not wave end)"),
        ("www/senat.bi", "www/gov.sz"),
        ("senat.bi", "gov.sz"),
        ("primature.gov.bi", "centralbank.org.sz"),
        # Language French → English; country name swaps
        ("French (Burundi)", "English (Eswatini)"),
        ("French Burundi", "English Eswatini"),
        ("ASCII-fold French", "ASCII-fold English"),
        ("French legal stems", "English legal stems"),
        ("French legal corpus", "English legal corpus"),
        ("French years+stems", "English years+stems"),
        ("French GATE", "English GATE"),
        ("Burundi", "Eswatini"),
        # slug / path forms BEFORE bare burundi
        ("burundi_ranked", "eswatini_ranked"),
        ("burundi_gate", "eswatini_gate"),
        ("burundi_pass", "eswatini_pass"),
        ("burundi_encode_memsafe", "eswatini_encode_memsafe"),
        ("burundi_package_memsafe", "eswatini_package_memsafe"),
        ("burundi_corpus_stream", "eswatini_corpus_stream"),
        ("burundi_encode_done", "eswatini_encode_done"),
        ("burundi_filtered_", "eswatini_filtered_"),
        ("burundi_", "eswatini_"),
        # ISO whole-token / path forms only
        ('"BI"', '"SZ"'),
        ("BI-attested", "SZ-attested"),
        ("(BI)", "(SZ)"),
        ('"bi"', '"sz"'),
        # floors 79/2418 → 56/2385
        ("79/2418", "56/2385"),
        ("79 / 2418", "56 / 2385"),
        ("79, 2418", "56, 2385"),
        ("FLOOR_LAWS, FLOOR_ARTS = 79, 2418", "FLOOR_LAWS, FLOOR_ARTS = 56, 2385"),
        ("or 79)", "or 56)"),
        ("or 79,", "or 56,"),
        ("or 79}", "or 56}"),
        ("= 79,", "= 56,"),
        ("= 79", "= 56"),
        ("@ 79/", "@ 56/"),
        (" 79/", " 56/"),
        ("floor 79/", "floor 56/"),
        ("(79/", "(56/"),
        (" or 79", " or 56"),
        (" 2418", " 2385"),
        ("2418", "2385"),
        # language field leftovers
        ('"language": "French"', '"language": "English"'),
        ('"lang": "French"', '"lang": "English"'),
        ("language: French", "language: English"),
        ("Language: French", "Language: English"),
    ]
    for a, b in reps:
        text = text.replace(a, b)

    # Bare slug "burundi" → "eswatini"
    text = re.sub(r"(?<![A-Za-z0-9_])burundi(?![A-Za-z0-9_])", "eswatini", text)

    text = text.replace("\x00BM25\x00", "BM25").replace("\x00bm25\x00", "bm25")
    text = text.replace("\x00AFTERDJ_US\x00", "after_dj")
    text = text.replace("\x00DESTHOLD\x00", HOLD)
    text = text.replace("\x00DESTCHAIN\x00", DEST_CHAIN)
    text = text.replace("\x00DESTWAVE\x00", WAVE_POS)

    text = text.replace(
        "FLOOR_LAWS, FLOOR_ARTS = 79, 2385",
        "FLOOR_LAWS, FLOOR_ARTS = 56, 2385",
    )
    text = text.replace(
        "FLOOR_LAWS, FLOOR_ARTS = 56, 2418",
        "FLOOR_LAWS, FLOOR_ARTS = 56, 2385",
    )
    text = text.replace(
        'int(pack.get("n_articles") or 2418)',
        'int(pack.get("n_articles") or 2385)',
    )
    text = text.replace(
        'int(pack.get("n_articles") or 2385)',
        'int(pack.get("n_articles") or 2385)',
    )
    text = text.replace(
        'int(pack.get("n_laws") or 79)',
        'int(pack.get("n_laws") or 56)',
    )
    text = text.replace(
        'int(pack.get("n_laws") or 56)',
        'int(pack.get("n_laws") or 56)',
    )

    # display name / slug fixes
    text = text.replace('"name": "eswatini"', '"name": "Eswatini"')
    text = text.replace('"name": "Eswatini"', '"name": "Eswatini"')
    text = text.replace('"slug": "Eswatini"', '"slug": "eswatini"')
    text = text.replace('SLUG = "Eswatini"', 'SLUG = "eswatini"')
    text = text.replace('SLUG = "eswatini"', 'SLUG = "eswatini"')
    text = text.replace('"country": "Eswatini"', '"country": "eswatini"')

    # Ensure agent-data survived
    for bad in (
        "cient-data", "prent-data", "stent-data", "cvent-data", "scent-data",
        "carent-data", "yement-data", "djiboutient-data", "marshallislandsent-data",
        "kiribatient-data", "burundient-data", "eswatinient-data",
    ):
        text = text.replace(f"/home/box/{bad}/", "/home/box/agent-data/")
        text = text.replace(bad, "agent-data")

    if dst_name == "eswatini_bm25_smoke.py":
        start = text.index("GATE = [")
        end = text.index("]", start) + 1
        years_line = ", ".join(f'"{y}"' for y in GATE_YEARS)
        stems_line = ", ".join(f'"{s}"' for s in GATE_STEMS)
        gate = f"GATE = [\n    {years_line},\n    {stems_line},\n]"
        text = text[:start] + gate + text[end:]
        text = re.sub(
            r"QUERIES = GATE \+ \[[^\]]*\]",
            'QUERIES = GATE + ["www", "gov.sz", "centralbank.org.sz", "court", "order", "constitution", "king", "parliament", "chapter", "shall"]',
            text,
            count=1,
        )
        text = re.sub(
            r'"""BM25 smoke for Eswatini IR.*?"""',
            '"""BM25 smoke for Eswatini IR — English legal corpus; years + English legal stems FTS gate.\n\n'
            "GATE is attested ASCII years plus English legal stems (ASCII-fold). URL www/gov.sz\n"
            "is query-only, never GATE. Every GATE token must rank a hit.\n"
            '"""',
            text,
            count=1,
            flags=re.S,
        )
        note = (
            f"attested years {GATE_NOTE_YEARS} plus English legal stems {GATE_NOTE_STEMS} "
            f"from articles.parquet HEAD tip {DST_TIP_SHORT}; URL www/gov.sz is query-only, not GATE."
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
        text = text.replace("— French legal corpus", "— English legal corpus")
        text = text.replace("French years+stems English GATE", "English years+stems GATE")
        text = text.replace(
            "attested Eswatini years and French legal stems",
            "attested Eswatini years and English legal stems",
        )
        text = text.replace("French legal corpus", "English legal corpus")
        text = text.replace("French legal stems", "English legal stems")

    if dst_name == "eswatini_write_publish_report.py":
        gate_note = (
            f"BM25 PASS on Eswatini ASCII-fold English GATE "
            f"(attested years {GATE_NOTE_YEARS} + stems {GATE_NOTE_STEMS}); "
            f"URL www/gov.sz is query-only, not GATE"
        )
        text = re.sub(
            r'BM25 PASS on Eswatini[^"]*"',
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
        text = text.replace("French legal stems GATE", "English years+stems GATE")
        text = text.replace("English legal stems GATE", "English years+stems GATE")
        text = re.sub(
            r"HOLD 0 STRICT after-KI[^;]*; collectors kept dead \(pkill\); soft never-thin ON; SKIP_US; Italy BLOCKED;[^\"\n]*",
            f"{HOLD}; collectors kept dead (pkill); soft never-thin ON; SKIP_US; Italy BLOCKED; {WAVE_POS}",
            text,
        )
        text = re.sub(
            r"HOLD 0 STRICT after-BI[^;]*; collectors kept dead \(pkill\); soft never-thin ON; SKIP_US; Italy BLOCKED;[^\"\n]*",
            f"{HOLD}; collectors kept dead (pkill); soft never-thin ON; SKIP_US; Italy BLOCKED; {WAVE_POS}",
            text,
        )
        text = text.replace("www/senat.bi is query-only", "www/gov.sz is query-only")
        text = text.replace("www/gov.sz is query-only", "www/gov.sz is query-only")
        text = re.sub(r"[ \t]{2,}", " ", text)

    leftovers = (
        "Burundi", "burundi",
        "Kiribati", "kiribati",
        "Marshall Islands", "marshallislands", "Marshall",
        "cient-data", "prent-data", "stent-data", "cvent-data", "scent-data",
        "carent-data", "yement-data", "djiboutient-data", "marshallislandsent-data",
        "kiribatient-data", "burundient-data", "eswatinient-data",
        "senat.bi", "primature.gov.bi",
    )
    found = []
    for x in leftovers:
        if x == "burundi":
            if re.search(r"(?<![A-Za-z0-9_])burundi(?![A-Za-z0-9_])", text):
                found.append(x)
            continue
        if x == "kiribati":
            if re.search(r"(?<![A-Za-z0-9_])kiribati(?![A-Za-z0-9_])", text):
                found.append(x)
            continue
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
    if re.search(r"\bFrench\b", text):
        raise RuntimeError(f"leftover French token in {dst_name}")
    # Reject BI/French stems leftover in GATE
    if dst_name.endswith("_bm25_smoke.py"):
        gate_slice = text[text.index("GATE = ["): text.index("]", text.index("GATE = [")) + 1]
        for bad in (
            "burundi", "loi", "decret", "ministre", "personne", "ordonnance",
            "republique", "etat", "gouvernement", "officiel", "tribunal", "penal",
            "kiribati", "marshall",
        ):
            if f'"{bad}"' in gate_slice:
                raise RuntimeError(f"non-SZ token in GATE of {dst_name}: {bad}")
        for stem in GATE_STEMS:
            if f'"{stem}"' not in gate_slice:
                raise RuntimeError(f"missing English stem in GATE of {dst_name}: {stem}")
        for year in GATE_YEARS:
            if f'"{year}"' not in gate_slice:
                raise RuntimeError(f"missing year in GATE of {dst_name}: {year}")
        if '", "bi"' in text or '", "BI"' in text:
            raise RuntimeError(f"leftover bi query token in {dst_name}")
        if "senat.bi" in text:
            raise RuntimeError(f"leftover senat.bi in {dst_name}")
    # reject bare burundi leftovers
    scrub = text
    scrub = scrub.replace(WAVE_POS, "XX")
    scrub = scrub.replace(HOLD, "XX")
    scrub = scrub.replace(DEST_CHAIN, "XX")
    scrub = scrub.replace(SRC_CHAIN, "XX")
    scrub = scrub.replace(SRC_HOLD, "XX")
    scrub = scrub.replace(SRC_WAVE, "XX")
    scrub = scrub.replace("after-BI", "after-XX")
    scrub = scrub.replace("after BI ", "after XX ")
    scrub = scrub.replace("after_dj", "after_xx")
    scrub = scrub.replace("BI LIVE", "XX LIVE")
    scrub = scrub.replace("BI→", "XX→")
    scrub = scrub.replace("…→BI", "…→XX")
    if re.search(r"(?<![A-Za-z0-9_])burundi(?![A-Za-z0-9_])", scrub):
        m = re.search(r"(?<![A-Za-z0-9_])burundi(?![A-Za-z0-9_])", scrub)
        raise RuntimeError(
            f"leftover burundi in {dst_name}: ...{scrub[max(0, m.start()-20):m.start()+20]}..."
        )
    if re.search(r"(?<![A-Za-z])BI(?![A-Za-z])", scrub):
        m = re.search(r"(?<![A-Za-z])BI(?![A-Za-z])", scrub)
        raise RuntimeError(
            f"leftover BI in {dst_name}: ...{scrub[max(0, m.start()-30):m.start()+30]}..."
        )
    if "ipfs_burundi" in text:
        raise RuntimeError(f"leftover burundi path in {dst_name}")
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
    if entry.get("slug") == "eswatini" or entry.get("iso2") == "SZ":
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
            "iso2": "SZ",
            "slug": "eswatini",
            "repo": "endomorphosis/ipfs_eswatini_laws",
            "years_attested": YEARS_ATTESTED,
            "gate_years": [int(y) for y in GATE_YEARS],
            "gate_stems": GATE_STEMS,
            "note": (
                f"SZ FIRST_IR scaffold; tip MATCH {DST_TIP_SHORT}@56/2385; {HOLD}; "
                f"soft never-thin ON; SKIP_US; Italy BLOCKED; {WAVE_POS}; "
                f"English GATE ({len(GATE_YEARS)} years + {len(GATE_STEMS)} stems)"
            ),
            "status": "CLAIMED",
            "mode": "FIRST_IR",
            "wave_end": False,
        })
        break
else:
    raise RuntimeError("Eswatini/SZ entry missing from wave JSON")

data["wave_status"] = "IN_PROGRESS_SZ"
data["hold"] = HOLD
data["current"] = "eswatini"
data["do_not_start_next"] = "niue"
data["next"] = "niue"
wave.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print("updated wave JSON Eswatini entry")
print("GATE years", GATE_YEARS)
print("GATE stems", GATE_STEMS)
print("n_gate", len(GATE_YEARS) + len(GATE_STEMS))
print("HOLD", HOLD)
print("GATE language: English years+stems")
