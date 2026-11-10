#!/usr/bin/env python3
"""Adapt the Kiribati English memsafe FIRST_IR pack to Burundi BI tip b5768508c9ba.

French Burundi; FIRST_IR; HOLD 0 STRICT after-KI (BI→SZ→NU→GW→SR→GQ→GY→BJ→SO→MV).
Soft never-thin ON; SKIP_US; Italy BLOCKED. WAVE after_dj after KI LIVE
(…→KI LIVE → BI → SZ→NU→GW→SR→GQ→GY→BJ→SO→MV), NOT wave end.
GATE: attested years + French legal stems from data/articles.parquet tip b5768508c9ba
(French; include burundi/republique). URL www/senat.bi query-only, NOT GATE.
Source tip 32b6f34aefd1 (Kiribati English memsafe with data/ paths)
— override language to French (Burundi); GATE French years+stems.
Keep data/articles.parquet + data/laws.parquet; agent-data not cient-data.
Do NOT start Eswatini/next after LIVE.
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
SRC_TIP_FULL = "32b6f34aefd14f542d25cd9dbde7e86f90883449"
SRC_TIP_SHORT = "32b6f34aefd1"
DST_TIP_FULL = "b5768508c9ba7906cd5b405b6de571cd4a82962c"
DST_TIP_SHORT = "b5768508c9ba"
FLOOR_LAWS, FLOOR_ARTS = 79, 2418
SRC_FLOOR_L, SRC_FLOOR_A = 165, 3118

# Sampled from data/articles.parquet @ b5768508c9ba (~10 years + ~11 French stems)
# Whole-word ASCII-fold FTS hits; laws=79 articles=2418.
# Top years by doc hits; stems from user list all attested.
GATE_YEARS = [
    "2014", "2018", "2026", "2017", "2024",
    "2020", "2016", "2023", "2022", "2015",
]
GATE_STEMS = [
    "article", "loi", "decret", "ministre", "personne", "code",
    "section", "ordonnance", "republique", "burundi", "etat",
]
YEARS_ATTESTED = [int(y) for y in GATE_YEARS] + [
    2025, 2021, 2019, 1992, 1993, 1999, 2011, 2000, 1998, 2005,
]
GATE_NOTE_YEARS = "/".join(GATE_YEARS)
GATE_NOTE_STEMS = "/".join(GATE_STEMS)
HOLD = "HOLD 0 STRICT after-KI (BI→SZ→NU→GW→SR→GQ→GY→BJ→SO→MV)"
WAVE_POS = (
    "after KI LIVE of after_dj wave "
    "(…→KI LIVE → BI → SZ→NU→GW→SR→GQ→GY→BJ→SO→MV; NOT wave end)"
)
DEST_CHAIN = "BI→SZ→NU→GW→SR→GQ→GY→BJ→SO→MV"
SRC_HOLD = "HOLD 0 STRICT after-MH (KI→BI→SZ→NU→GW→SR→GQ→GY→BJ→SO→MV)"
SRC_WAVE = (
    "after MH LIVE of after_dj wave "
    "(MH→KI→BI→SZ→NU→GW→SR→GQ→GY→BJ→SO→MV; NOT wave end)"
)
SRC_CHAIN = "KI→BI→SZ→NU→GW→SR→GQ→GY→BJ→SO→MV"

FILES = [
    ("kiribati_soft_filter.py", "burundi_soft_filter.py"),
    (f"kiribati_corpus_stream_{SRC_TIP_SHORT}.py", f"burundi_corpus_stream_{DST_TIP_SHORT}.py"),
    (f"kiribati_encode_memsafe_{SRC_TIP_SHORT}.py", f"burundi_encode_memsafe_{DST_TIP_SHORT}.py"),
    (f"kiribati_finish_from_emb_{SRC_TIP_SHORT}.py", f"burundi_finish_from_emb_{DST_TIP_SHORT}.py"),
    (f"kiribati_stream_graph_parts_{SRC_TIP_SHORT}.py", f"burundi_stream_graph_parts_{DST_TIP_SHORT}.py"),
    (f"kiribati_package_memsafe_{SRC_TIP_SHORT}.py", f"burundi_package_memsafe_{DST_TIP_SHORT}.py"),
    ("kiribati_upload.py", "burundi_upload.py"),
    ("kiribati_bm25_smoke.py", "burundi_bm25_smoke.py"),
    ("kiribati_write_publish_report.py", "burundi_write_publish_report.py"),
    (f"kiribati_orchestrator_{SRC_TIP_SHORT}.py", f"burundi_orchestrator_{DST_TIP_SHORT}.py"),
]


def adapt(text: str, dst_name: str) -> str:
    # Repair path corruption from prior adapts
    for bad in (
        "cient-data", "prent-data", "stent-data", "cvent-data", "scent-data",
        "carent-data", "yement-data", "djiboutient-data", "marshallislandsent-data",
        "kiribatient-data", "burundient-data",
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
    text = text.replace("after-MH", "\x00AFTERKI\x00")
    text = text.replace("after MH ", "\x00AFTERKI_SP\x00")
    text = text.replace("after_dj", "\x00AFTERDJ_US\x00")
    text = text.replace(
        "MH→KI→BI→SZ→NU→GW→SR→GQ→GY→BJ→SO→MV",
        "\x00SRCCHAIN_FULL\x00",
    )
    text = text.replace("after MH LIVE of \x00AFTERDJ_US\x00 wave", "\x00DESTWAVE_SHORT\x00")
    text = text.replace("after MH LIVE of after_dj wave", "\x00DESTWAVE_SHORT\x00")
    text = text.replace("KI FIRST_IR", "\x00DESTFIRST\x00")

    reps = [
        (SRC_TIP_FULL, DST_TIP_FULL),
        (SRC_TIP_SHORT, DST_TIP_SHORT),
        ("endomorphosis/ipfs_kiribati_laws", "endomorphosis/ipfs_burundi_laws"),
        ("justicedao/ipfs_kiribati_laws_ir", "justicedao/ipfs_burundi_laws_ir"),
        ("ipfs_kiribati_laws_ir", "ipfs_burundi_laws_ir"),
        ("ipfs_kiribati_laws", "ipfs_burundi_laws"),
        # HOLD / wave restore
        ("\x00DESTHOLD\x00", HOLD),
        ("\x00DESTWAVE\x00", WAVE_POS),
        ("\x00DESTWAVE_SHORT\x00", WAVE_POS),
        ("\x00DESTCHAIN\x00", DEST_CHAIN),
        ("\x00SRCCHAIN_FULL\x00", "…→KI LIVE → BI → SZ→NU→GW→SR→GQ→GY→BJ→SO→MV"),
        ("\x00AFTERKI\x00", "after-KI"),
        ("\x00AFTERKI_SP\x00", "after KI "),
        ("\x00DESTFIRST\x00", "BI FIRST_IR"),
        ("KI FIRST_IR (not wave end)", "BI FIRST_IR (not wave end)"),
        ("www/president.gov.ki", "www/senat.bi"),
        ("president.gov.ki", "senat.bi"),
        # Language English → French; country name swaps
        ("English (Kiribati)", "French (Burundi)"),
        ("English Kiribati", "French Burundi"),
        ("ASCII-fold English", "ASCII-fold French"),
        ("English legal stems", "French legal stems"),
        ("English legal corpus", "French legal corpus"),
        ("English years+stems", "French years+stems"),
        ("Kiribati", "Burundi"),
        # slug / path forms BEFORE bare kiribati
        ("kiribati_ranked", "burundi_ranked"),
        ("kiribati_gate", "burundi_gate"),
        ("kiribati_pass", "burundi_pass"),
        ("kiribati_encode_memsafe", "burundi_encode_memsafe"),
        ("kiribati_package_memsafe", "burundi_package_memsafe"),
        ("kiribati_corpus_stream", "burundi_corpus_stream"),
        ("kiribati_encode_done", "burundi_encode_done"),
        ("kiribati_filtered_", "burundi_filtered_"),
        ("kiribati_", "burundi_"),
        # ISO whole-token / path forms only
        ('"KI"', '"BI"'),
        ("KI-attested", "BI-attested"),
        ("(KI)", "(BI)"),
        ('"ki"', '"bi"'),
        # floors 165/3118 → 79/2418
        ("165/3118", "79/2418"),
        ("165 / 3118", "79 / 2418"),
        ("165, 3118", "79, 2418"),
        ("FLOOR_LAWS, FLOOR_ARTS = 165, 3118", "FLOOR_LAWS, FLOOR_ARTS = 79, 2418"),
        ("or 165)", "or 79)"),
        ("or 165,", "or 79,"),
        ("or 165}", "or 79}"),
        ("= 165,", "= 79,"),
        ("= 165", "= 79"),
        ("@ 165/", "@ 79/"),
        (" 165/", " 79/"),
        ("floor 165/", "floor 79/"),
        ("(165/", "(79/"),
        (" or 165", " or 79"),
        (" 3118", " 2418"),
        ("3118", "2418"),
        # language field leftovers
        ('"language": "English"', '"language": "French"'),
        ('"lang": "English"', '"lang": "French"'),
        ("language: English", "language: French"),
        ("Language: English", "Language: French"),
    ]
    for a, b in reps:
        text = text.replace(a, b)

    # Bare slug "kiribati" → "burundi"
    text = re.sub(r"(?<![A-Za-z0-9_])kiribati(?![A-Za-z0-9_])", "burundi", text)

    text = text.replace("\x00BM25\x00", "BM25").replace("\x00bm25\x00", "bm25")
    text = text.replace("\x00AFTERDJ_US\x00", "after_dj")
    text = text.replace("\x00DESTHOLD\x00", HOLD)
    text = text.replace("\x00DESTCHAIN\x00", DEST_CHAIN)
    text = text.replace("\x00DESTWAVE\x00", WAVE_POS)

    text = text.replace(
        "FLOOR_LAWS, FLOOR_ARTS = 165, 2418",
        "FLOOR_LAWS, FLOOR_ARTS = 79, 2418",
    )
    text = text.replace(
        "FLOOR_LAWS, FLOOR_ARTS = 79, 3118",
        "FLOOR_LAWS, FLOOR_ARTS = 79, 2418",
    )
    text = text.replace(
        'int(pack.get("n_articles") or 3118)',
        'int(pack.get("n_articles") or 2418)',
    )
    text = text.replace(
        'int(pack.get("n_articles") or 2418)',
        'int(pack.get("n_articles") or 2418)',
    )
    text = text.replace(
        'int(pack.get("n_laws") or 165)',
        'int(pack.get("n_laws") or 79)',
    )
    text = text.replace(
        'int(pack.get("n_laws") or 79)',
        'int(pack.get("n_laws") or 79)',
    )

    # display name / slug fixes
    text = text.replace('"name": "burundi"', '"name": "Burundi"')
    text = text.replace('"name": "Burundi"', '"name": "Burundi"')
    text = text.replace('"slug": "Burundi"', '"slug": "burundi"')
    text = text.replace('SLUG = "Burundi"', 'SLUG = "burundi"')
    text = text.replace('SLUG = "burundi"', 'SLUG = "burundi"')
    text = text.replace('"country": "Burundi"', '"country": "burundi"')

    # Ensure agent-data survived
    for bad in (
        "cient-data", "prent-data", "stent-data", "cvent-data", "scent-data",
        "carent-data", "yement-data", "djiboutient-data", "marshallislandsent-data",
        "kiribatient-data", "burundient-data",
    ):
        text = text.replace(f"/home/box/{bad}/", "/home/box/agent-data/")
        text = text.replace(bad, "agent-data")

    if dst_name == "burundi_bm25_smoke.py":
        start = text.index("GATE = [")
        end = text.index("]", start) + 1
        years_line = ", ".join(f'"{y}"' for y in GATE_YEARS)
        stems_line = ", ".join(f'"{s}"' for s in GATE_STEMS)
        gate = f"GATE = [\n    {years_line},\n    {stems_line},\n]"
        text = text[:start] + gate + text[end:]
        text = re.sub(
            r"QUERIES = GATE \+ \[[^\]]*\]",
            'QUERIES = GATE + ["www", "senat.bi", "primature.gov.bi", "constitution", "president", "justice", "officiel", "tribunal", "penal", "gouvernement"]',
            text,
            count=1,
        )
        text = re.sub(
            r'"""BM25 smoke for Burundi IR.*?"""',
            '"""BM25 smoke for Burundi IR — French legal corpus; years + French legal stems FTS gate.\n\n'
            "GATE is attested ASCII years plus French legal stems (ASCII-fold). URL www/senat.bi\n"
            "is query-only, never GATE. Every GATE token must rank a hit.\n"
            '"""',
            text,
            count=1,
            flags=re.S,
        )
        note = (
            f"attested years {GATE_NOTE_YEARS} plus French legal stems {GATE_NOTE_STEMS} "
            f"from articles.parquet HEAD tip {DST_TIP_SHORT}; URL www/senat.bi is query-only, not GATE."
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
        text = text.replace("— English legal corpus", "— French legal corpus")
        text = text.replace("English years+stems French GATE", "French years+stems GATE")
        text = text.replace(
            "attested Burundi years and English legal stems",
            "attested Burundi years and French legal stems",
        )
        text = text.replace(
            "attested Burundi years and French legal stems",
            "attested Burundi years and French legal stems",
        )
        text = text.replace('"burundi_pass"', '"burundi_pass"')
        text = text.replace('"burundi_gate"', '"burundi_gate"')
        text = text.replace("English legal corpus", "French legal corpus")
        text = text.replace("English legal stems", "French legal stems")

    if dst_name == "burundi_write_publish_report.py":
        gate_note = (
            f"BM25 PASS on Burundi ASCII-fold French GATE "
            f"(attested years {GATE_NOTE_YEARS} + stems {GATE_NOTE_STEMS}); "
            f"URL www/senat.bi is query-only, not GATE"
        )
        text = re.sub(
            r'BM25 PASS on Burundi[^"]*"',
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
        text = text.replace("English legal stems GATE", "French years+stems GATE")
        text = text.replace("French legal stems GATE", "French years+stems GATE")
        text = re.sub(
            r"HOLD 0 STRICT after-MH[^;]*; collectors kept dead \(pkill\); soft never-thin ON; SKIP_US; Italy BLOCKED;[^\"\n]*",
            f"{HOLD}; collectors kept dead (pkill); soft never-thin ON; SKIP_US; Italy BLOCKED; {WAVE_POS}",
            text,
        )
        text = re.sub(
            r"HOLD 0 STRICT after-KI[^;]*; collectors kept dead \(pkill\); soft never-thin ON; SKIP_US; Italy BLOCKED;[^\"\n]*",
            f"{HOLD}; collectors kept dead (pkill); soft never-thin ON; SKIP_US; Italy BLOCKED; {WAVE_POS}",
            text,
        )
        text = text.replace("www/president.gov.ki is query-only", "www/senat.bi is query-only")
        text = text.replace("www/senat.bi is query-only", "www/senat.bi is query-only")
        text = re.sub(r"[ \t]{2,}", " ", text)

    leftovers = (
        "Kiribati", "kiribati",
        "Marshall Islands", "marshallislands", "Marshall",
        "cient-data", "prent-data", "stent-data", "cvent-data", "scent-data",
        "carent-data", "yement-data", "djiboutient-data", "marshallislandsent-data",
        "kiribatient-data", "burundient-data",
        "president.gov.ki", "rmiparliament.org", "nitijela",
        "shall",
    )
    found = []
    for x in leftovers:
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
        if x == "shall":
            if re.search(r"(?<![A-Za-z])shall(?![A-Za-z])", text):
                found.append(x)
            continue
        if x in text:
            found.append(x)
    if found:
        raise RuntimeError(f"language/country leftovers in {dst_name}: {found}")
    if re.search(r"\bEnglish\b", text):
        raise RuntimeError(f"leftover English token in {dst_name}")
    # Reject KI stems leftover in GATE
    if dst_name.endswith("_bm25_smoke.py"):
        gate_slice = text[text.index("GATE = ["): text.index("]", text.index("GATE = [")) + 1]
        for bad in (
            "kiribati", "act", "law", "person", "republic", "government",
            "minister", "shall", "offence", "chapter", "marshall",
        ):
            if f'"{bad}"' in gate_slice:
                raise RuntimeError(f"non-BI token in GATE of {dst_name}: {bad}")
        for stem in GATE_STEMS:
            if f'"{stem}"' not in gate_slice:
                raise RuntimeError(f"missing French stem in GATE of {dst_name}: {stem}")
        for year in GATE_YEARS:
            if f'"{year}"' not in gate_slice:
                raise RuntimeError(f"missing year in GATE of {dst_name}: {year}")
        if '", "ki"' in text or '", "KI"' in text:
            raise RuntimeError(f"leftover ki query token in {dst_name}")
        if "president.gov.ki" in text:
            raise RuntimeError(f"leftover president.gov.ki in {dst_name}")
    # reject bare kiribati leftovers
    scrub = text
    scrub = scrub.replace(WAVE_POS, "XX")
    scrub = scrub.replace(HOLD, "XX")
    scrub = scrub.replace(DEST_CHAIN, "XX")
    scrub = scrub.replace(SRC_CHAIN, "XX")
    scrub = scrub.replace(SRC_HOLD, "XX")
    scrub = scrub.replace(SRC_WAVE, "XX")
    scrub = scrub.replace("after-KI", "after-XX")
    scrub = scrub.replace("after KI ", "after XX ")
    scrub = scrub.replace("after_dj", "after_xx")
    scrub = scrub.replace("KI LIVE", "XX LIVE")
    scrub = scrub.replace("KI→", "XX→")
    scrub = scrub.replace("…→KI", "…→XX")
    if re.search(r"(?<![A-Za-z0-9_])kiribati(?![A-Za-z0-9_])", scrub):
        m = re.search(r"(?<![A-Za-z0-9_])kiribati(?![A-Za-z0-9_])", scrub)
        raise RuntimeError(
            f"leftover kiribati in {dst_name}: ...{scrub[max(0, m.start()-20):m.start()+20]}..."
        )
    if re.search(r"(?<![A-Za-z])KI(?![A-Za-z])", scrub):
        m = re.search(r"(?<![A-Za-z])KI(?![A-Za-z])", scrub)
        raise RuntimeError(
            f"leftover KI in {dst_name}: ...{scrub[max(0, m.start()-30):m.start()+30]}..."
        )
    if "ipfs_kiribati" in text:
        raise RuntimeError(f"leftover kiribati path in {dst_name}")
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
    if entry.get("slug") == "burundi" or entry.get("iso2") == "BI":
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
            "iso2": "BI",
            "slug": "burundi",
            "repo": "endomorphosis/ipfs_burundi_laws",
            "years_attested": YEARS_ATTESTED,
            "gate_years": [int(y) for y in GATE_YEARS],
            "gate_stems": GATE_STEMS,
            "note": (
                f"BI FIRST_IR scaffold; tip MATCH {DST_TIP_SHORT}@79/2418; {HOLD}; "
                f"soft never-thin ON; SKIP_US; Italy BLOCKED; {WAVE_POS}; "
                f"French GATE ({len(GATE_YEARS)} years + {len(GATE_STEMS)} stems)"
            ),
            "status": "CLAIMED",
            "mode": "FIRST_IR",
            "wave_end": False,
        })
        break
else:
    raise RuntimeError("Burundi/BI entry missing from wave JSON")

data["wave_status"] = "IN_PROGRESS_BI"
data["hold"] = HOLD
data["current"] = "burundi"
data["do_not_start_next"] = "eswatini"
data["next"] = "eswatini"
wave.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print("updated wave JSON Burundi entry")
print("GATE years", GATE_YEARS)
print("GATE stems", GATE_STEMS)
print("n_gate", len(GATE_YEARS) + len(GATE_STEMS))
print("HOLD", HOLD)
print("GATE language: French years+stems")
