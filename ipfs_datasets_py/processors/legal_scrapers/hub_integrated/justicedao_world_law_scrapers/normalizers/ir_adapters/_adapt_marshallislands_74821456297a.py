#!/usr/bin/env python3
"""Adapt the Djibouti French memsafe FIRST_IR pack to Marshall Islands MH tip 74821456297a.

English Marshall Islands; FIRST_IR; HOLD 0 STRICT after-DJ (MH→KI→BI→SZ→NU→GW→SR→GQ→GY→BJ→SO→MV).
Soft never-thin ON; SKIP_US; Italy BLOCKED. WAVE after_dj first country
(MH→KI→BI→SZ→NU→GW→SR→GQ→GY→BJ→SO→MV), NOT wave end.
GATE: attested years + English legal stems from data/articles.parquet tip 74821456297a
(English; include marshall/islands). URL www/rmiparliament.org query-only, NOT GATE.
Source tip bc8e769bb669 (Djibouti French memsafe with data/ paths)
— override language to English (Marshall Islands); GATE English years+stems.
Keep data/articles.parquet + data/laws.parquet; agent-data not cient-data.
Do NOT start Kiribati/next after LIVE.
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
SRC_TIP_FULL = "bc8e769bb669012c993682ed6c4a6c118b569f26"
SRC_TIP_SHORT = "bc8e769bb669"
DST_TIP_FULL = "74821456297a7786caf5b7fc54c6770482130629"
DST_TIP_SHORT = "74821456297a"
FLOOR_LAWS, FLOOR_ARTS = 884, 3119
SRC_FLOOR_L, SRC_FLOOR_A = 165, 3205

# Sampled from data/articles.parquet @ 74821456297a (~10 years + ~11 English stems)
# Whole-word ASCII-fold FTS hits; laws=884 articles=3119.
# Top years by doc hits; stems from user list all attested.
GATE_YEARS = [
    "1980", "1988", "1990", "1989", "1986",
    "1983", "2000", "1987", "1970", "1991",
]
GATE_STEMS = [
    "article", "section", "act", "law", "person", "republic",
    "code", "marshall", "islands", "minister", "government",
]
YEARS_ATTESTED = [int(y) for y in GATE_YEARS] + [
    2017, 2018, 2016, 2020, 2003, 2005, 1998, 1996, 2007, 1994,
]
GATE_NOTE_YEARS = "/".join(GATE_YEARS)
GATE_NOTE_STEMS = "/".join(GATE_STEMS)
HOLD = "HOLD 0 STRICT after-DJ (MH→KI→BI→SZ→NU→GW→SR→GQ→GY→BJ→SO→MV)"
WAVE_POS = (
    "first country of after_dj wave "
    "(MH→KI→BI→SZ→NU→GW→SR→GQ→GY→BJ→SO→MV; NOT wave end)"
)
DEST_CHAIN = "MH→KI→BI→SZ→NU→GW→SR→GQ→GY→BJ→SO→MV"
SRC_HOLD = "HOLD 0 STRICT after-YE (DJ WAVE END)"
SRC_WAVE = (
    "WAVE END of after_tj wave "
    "(after DM→SL→GM→AG→CI→PR→ST→CV→SC→CF→YE LIVE)"
)
SRC_CHAIN = "DJ WAVE END"

FILES = [
    ("djibouti_soft_filter.py", "marshallislands_soft_filter.py"),
    (f"djibouti_corpus_stream_{SRC_TIP_SHORT}.py", f"marshallislands_corpus_stream_{DST_TIP_SHORT}.py"),
    (f"djibouti_encode_memsafe_{SRC_TIP_SHORT}.py", f"marshallislands_encode_memsafe_{DST_TIP_SHORT}.py"),
    (f"djibouti_finish_from_emb_{SRC_TIP_SHORT}.py", f"marshallislands_finish_from_emb_{DST_TIP_SHORT}.py"),
    (f"djibouti_stream_graph_parts_{SRC_TIP_SHORT}.py", f"marshallislands_stream_graph_parts_{DST_TIP_SHORT}.py"),
    (f"djibouti_package_memsafe_{SRC_TIP_SHORT}.py", f"marshallislands_package_memsafe_{DST_TIP_SHORT}.py"),
    ("djibouti_upload.py", "marshallislands_upload.py"),
    ("djibouti_bm25_smoke.py", "marshallislands_bm25_smoke.py"),
    ("djibouti_write_publish_report.py", "marshallislands_write_publish_report.py"),
    (f"djibouti_orchestrator_{SRC_TIP_SHORT}.py", f"marshallislands_orchestrator_{DST_TIP_SHORT}.py"),
]


def adapt(text: str, dst_name: str) -> str:
    # Repair path corruption from prior adapts
    for bad in (
        "cient-data", "prent-data", "stent-data", "cvent-data", "scent-data",
        "carent-data", "yement-data", "djiboutient-data", "marshallislandsent-data",
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
    text = text.replace("after-YE", "\x00AFTERDJ\x00")
    text = text.replace("after YE ", "\x00AFTERDJ_SP\x00")
    text = text.replace("after_tj", "\x00AFTERDJ_US\x00")
    text = text.replace(
        "DM→SL→GM→AG→CI→PR→ST→CV→SC→CF→YE LIVE",
        "\x00PRIORLIVE\x00",
    )
    text = text.replace("WAVE END of \x00AFTERDJ_US\x00 wave", "\x00DESTWAVE_SHORT\x00")
    text = text.replace("WAVE END of after_tj wave", "\x00DESTWAVE_SHORT\x00")
    text = text.replace("DJ WAVE END", "\x00DESTCHAIN\x00")

    reps = [
        (SRC_TIP_FULL, DST_TIP_FULL),
        (SRC_TIP_SHORT, DST_TIP_SHORT),
        ("endomorphosis/ipfs_djibouti_laws", "endomorphosis/ipfs_marshallislands_laws"),
        ("justicedao/ipfs_djibouti_laws_ir", "justicedao/ipfs_marshallislands_laws_ir"),
        ("ipfs_djibouti_laws_ir", "ipfs_marshallislands_laws_ir"),
        ("ipfs_djibouti_laws", "ipfs_marshallislands_laws"),
        # HOLD / wave restore
        ("\x00DESTHOLD\x00", HOLD),
        ("\x00DESTWAVE\x00", WAVE_POS),
        ("\x00DESTWAVE_SHORT\x00", WAVE_POS),
        ("\x00DESTCHAIN\x00", DEST_CHAIN),
        ("\x00AFTERDJ\x00", "after-DJ"),
        ("\x00AFTERDJ_SP\x00", "after DJ "),
        ("\x00PRIORLIVE\x00", "DJ LIVE"),
        ("DJ FIRST_IR (WAVE END)", "MH FIRST_IR (not wave end)"),
        ("DJ FIRST_IR (not wave end)", "MH FIRST_IR (not wave end)"),
        ("www/gov.dj", "www/rmiparliament.org"),
        ("gov.dj", "rmiparliament.org"),
        # Language French → English; country name swaps
        ("French (Djibouti)", "English (Marshall Islands)"),
        ("French Djibouti", "English Marshall Islands"),
        ("ASCII-fold French", "ASCII-fold English"),
        ("French legal stems", "English legal stems"),
        ("French legal corpus", "English legal corpus"),
        ("French years+stems", "English years+stems"),
        ("Djibouti", "Marshall Islands"),
        # slug / path forms BEFORE bare djibouti
        ("djibouti_ranked", "marshallislands_ranked"),
        ("djibouti_gate", "marshallislands_gate"),
        ("djibouti_pass", "marshallislands_pass"),
        ("djibouti_encode_memsafe", "marshallislands_encode_memsafe"),
        ("djibouti_package_memsafe", "marshallislands_package_memsafe"),
        ("djibouti_corpus_stream", "marshallislands_corpus_stream"),
        ("djibouti_encode_done", "marshallislands_encode_done"),
        ("djibouti_filtered_", "marshallislands_filtered_"),
        ("djibouti_", "marshallislands_"),
        # ISO whole-token / path forms only
        ('"DJ"', '"MH"'),
        ("DJ-attested", "MH-attested"),
        ("(DJ)", "(MH)"),
        ('"dj"', '"mh"'),
        # floors 165/3205 → 884/3119
        ("165/3205", "884/3119"),
        ("165 / 3205", "884 / 3119"),
        ("165, 3205", "884, 3119"),
        ("FLOOR_LAWS, FLOOR_ARTS = 165, 3205", "FLOOR_LAWS, FLOOR_ARTS = 884, 3119"),
        ("or 165)", "or 884)"),
        ("or 165,", "or 884,"),
        ("or 165}", "or 884}"),
        ("= 165,", "= 884,"),
        ("= 165", "= 884"),
        ("@ 165/", "@ 884/"),
        (" 165/", " 884/"),
        ("floor 165/", "floor 884/"),
        ("(165/", "(884/"),
        (" or 165", " or 884"),
        (" 3205", " 3119"),
        ("3205", "3119"),
        # language field leftovers
        ('"language": "French"', '"language": "English"'),
        ('"lang": "French"', '"lang": "English"'),
        ("language: French", "language: English"),
        ("Language: French", "Language: English"),
    ]
    for a, b in reps:
        text = text.replace(a, b)

    # Bare slug "djibouti" → "marshallislands"
    text = re.sub(r"(?<![A-Za-z0-9_])djibouti(?![A-Za-z0-9_])", "marshallislands", text)

    text = text.replace("\x00BM25\x00", "BM25").replace("\x00bm25\x00", "bm25")
    text = text.replace("\x00AFTERDJ_US\x00", "after_dj")
    text = text.replace("\x00DESTHOLD\x00", HOLD)
    text = text.replace("\x00DESTCHAIN\x00", DEST_CHAIN)
    text = text.replace("\x00DESTWAVE\x00", WAVE_POS)

    text = text.replace(
        "FLOOR_LAWS, FLOOR_ARTS = 165, 3119",
        "FLOOR_LAWS, FLOOR_ARTS = 884, 3119",
    )
    text = text.replace(
        "FLOOR_LAWS, FLOOR_ARTS = 884, 3205",
        "FLOOR_LAWS, FLOOR_ARTS = 884, 3119",
    )
    text = text.replace(
        'int(pack.get("n_articles") or 3205)',
        'int(pack.get("n_articles") or 3119)',
    )
    text = text.replace(
        'int(pack.get("n_articles") or 3119)',
        'int(pack.get("n_articles") or 3119)',
    )
    text = text.replace(
        'int(pack.get("n_laws") or 165)',
        'int(pack.get("n_laws") or 884)',
    )
    text = text.replace(
        'int(pack.get("n_laws") or 884)',
        'int(pack.get("n_laws") or 884)',
    )

    # display name / slug fixes (multi-word country)
    text = text.replace('"name": "marshallislands"', '"name": "Marshall Islands"')
    text = text.replace('"name": "Marshall Islands"', '"name": "Marshall Islands"')
    text = text.replace('"slug": "Marshall Islands"', '"slug": "marshallislands"')
    text = text.replace('SLUG = "Marshall Islands"', 'SLUG = "marshallislands"')
    text = text.replace('SLUG = "marshallislands"', 'SLUG = "marshallislands"')
    text = text.replace('"country": "Marshall Islands"', '"country": "marshallislands"')

    # Ensure agent-data survived
    for bad in (
        "cient-data", "prent-data", "stent-data", "cvent-data", "scent-data",
        "carent-data", "yement-data", "djiboutient-data", "marshallislandsent-data",
    ):
        text = text.replace(f"/home/box/{bad}/", "/home/box/agent-data/")
        text = text.replace(bad, "agent-data")

    # residual French → English (after protect)
    text = text.replace("French", "English")

    if dst_name == "marshallislands_bm25_smoke.py":
        start = text.index("GATE = [")
        end = text.index("]", start) + 1
        years_line = ", ".join(f'"{y}"' for y in GATE_YEARS)
        stems_line = ", ".join(f'"{s}"' for s in GATE_STEMS)
        gate = f"GATE = [\n    {years_line},\n    {stems_line},\n]"
        text = text[:start] + gate + text[end:]
        text = re.sub(
            r"QUERIES = GATE \+ \[[^\]]*\]",
            'QUERIES = GATE + ["www", "rmiparliament.org", "court", "order", "offence", "constitution", "president", "nitijela", "chapter", "shall"]',
            text,
            count=1,
        )
        text = re.sub(
            r'"""BM25 smoke for Marshall Islands IR.*?"""',
            '"""BM25 smoke for Marshall Islands IR — English legal corpus; years + English legal stems FTS gate.\n\n'
            "GATE is attested ASCII years plus English legal stems (ASCII-fold). URL www/rmiparliament.org\n"
            "is query-only, never GATE. Every GATE token must rank a hit.\n"
            '"""',
            text,
            count=1,
            flags=re.S,
        )
        note = (
            f"attested years {GATE_NOTE_YEARS} plus English legal stems {GATE_NOTE_STEMS} "
            f"from articles.parquet HEAD tip {DST_TIP_SHORT}; URL www/rmiparliament.org is query-only, not GATE."
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
            "attested Marshall Islands years and English legal stems",
            "attested Marshall Islands years and English legal stems",
        )
        text = text.replace('"marshallislands_pass"', '"marshallislands_pass"')
        text = text.replace('"marshallislands_gate"', '"marshallislands_gate"')

    if dst_name == "marshallislands_write_publish_report.py":
        gate_note = (
            f"BM25 PASS on Marshall Islands ASCII-fold English GATE "
            f"(attested years {GATE_NOTE_YEARS} + stems {GATE_NOTE_STEMS}); "
            f"URL www/rmiparliament.org is query-only, not GATE"
        )
        text = re.sub(
            r'BM25 PASS on Marshall Islands[^"]*"',
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
            r"HOLD 0 STRICT after-YE[^;]*; collectors kept dead \(pkill\); soft never-thin ON; SKIP_US; Italy BLOCKED;[^\"\n]*",
            f"{HOLD}; collectors kept dead (pkill); soft never-thin ON; SKIP_US; Italy BLOCKED; {WAVE_POS}",
            text,
        )
        text = re.sub(
            r"HOLD 0 STRICT after-DJ[^;]*; collectors kept dead \(pkill\); soft never-thin ON; SKIP_US; Italy BLOCKED;[^\"\n]*",
            f"{HOLD}; collectors kept dead (pkill); soft never-thin ON; SKIP_US; Italy BLOCKED; {WAVE_POS}",
            text,
        )
        text = text.replace("www/gov.dj is query-only", "www/rmiparliament.org is query-only")
        text = text.replace("www/rmiparliament.org is query-only", "www/rmiparliament.org is query-only")
        text = re.sub(r"[ \t]{2,}", " ", text)

    leftovers = (
        "Djibouti", "djibouti",
        "cient-data", "prent-data", "stent-data", "cvent-data", "scent-data",
        "carent-data", "yement-data", "djiboutient-data", "marshallislandsent-data",
        "gov.dj",
        "loi", "decret", "ordonnance", "personne", "republique", "etat",
        "officiel", "ministre",
    )
    found = []
    for x in leftovers:
        if x in ("loi", "decret", "ordonnance", "personne", "republique", "etat", "officiel", "ministre"):
            if re.search(rf"(?<![A-Za-z]){re.escape(x)}(?![A-Za-z])", text):
                found.append(x)
            continue
        if x == "djibouti":
            if re.search(r"(?<![A-Za-z0-9_])djibouti(?![A-Za-z0-9_])", text):
                found.append(x)
            continue
        if x in text:
            found.append(x)
    if found:
        raise RuntimeError(f"language/country leftovers in {dst_name}: {found}")
    if re.search(r"\bFrench\b", text):
        raise RuntimeError(f"leftover French token in {dst_name}")
    if re.search(r"\bArabic\b", text):
        raise RuntimeError(f"leftover Arabic token in {dst_name}")
    # Reject non-English tokens in GATE
    if dst_name.endswith("_bm25_smoke.py"):
        gate_slice = text[text.index("GATE = ["): text.index("]", text.index("GATE = [")) + 1]
        for bad in (
            "loi", "decret", "ordonnance", "personne", "republique", "etat",
            "ministre", "djibouti", "centrafricaine", "ivoire",
        ):
            if f'"{bad}"' in gate_slice:
                raise RuntimeError(f"non-English token in GATE of {dst_name}: {bad}")
        for stem in GATE_STEMS:
            if f'"{stem}"' not in gate_slice:
                raise RuntimeError(f"missing English stem in GATE of {dst_name}: {stem}")
        for year in GATE_YEARS:
            if f'"{year}"' not in gate_slice:
                raise RuntimeError(f"missing year in GATE of {dst_name}: {year}")
        if '", "dj"' in text:
            raise RuntimeError(f"leftover dj query token in {dst_name}")
        if "gov.dj" in text:
            raise RuntimeError(f"leftover gov.dj in {dst_name}")
    # reject bare djibouti leftovers
    scrub = text
    scrub = scrub.replace(DEST_CHAIN, "XX")
    scrub = scrub.replace(HOLD, "XX")
    scrub = scrub.replace(WAVE_POS, "XX")
    scrub = scrub.replace("after-DJ", "after-XX")
    scrub = scrub.replace("after DJ ", "after XX ")
    scrub = scrub.replace("after_dj", "after_xx")
    scrub = scrub.replace("DJ LIVE", "XX LIVE")
    if re.search(r"(?<![A-Za-z0-9_])djibouti(?![A-Za-z0-9_])", scrub):
        m = re.search(r"(?<![A-Za-z0-9_])djibouti(?![A-Za-z0-9_])", scrub)
        raise RuntimeError(
            f"leftover djibouti in {dst_name}: ...{scrub[max(0, m.start()-20):m.start()+20]}..."
        )
    if re.search(r"(?<![A-Za-z])DJ(?![A-Za-z])", scrub):
        m = re.search(r"(?<![A-Za-z])DJ(?![A-Za-z])", scrub)
        raise RuntimeError(
            f"leftover DJ in {dst_name}: ...{scrub[max(0, m.start()-30):m.start()+30]}..."
        )
    if "ipfs_djibouti" in text:
        raise RuntimeError(f"leftover djibouti path in {dst_name}")
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
    if entry.get("slug") == "marshallislands" or entry.get("iso2") == "MH":
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
            "iso2": "MH",
            "slug": "marshallislands",
            "repo": "endomorphosis/ipfs_marshallislands_laws",
            "years_attested": YEARS_ATTESTED,
            "gate_years": [int(y) for y in GATE_YEARS],
            "gate_stems": GATE_STEMS,
            "note": (
                f"MH FIRST_IR scaffold; tip MATCH {DST_TIP_SHORT}@884/3119; {HOLD}; "
                f"soft never-thin ON; SKIP_US; Italy BLOCKED; {WAVE_POS}; "
                f"English GATE ({len(GATE_YEARS)} years + {len(GATE_STEMS)} stems)"
            ),
            "status": "CLAIMED",
            "mode": "FIRST_IR",
            "wave_end": False,
        })
        break
else:
    raise RuntimeError("Marshall Islands/MH entry missing from wave JSON")

data["wave_status"] = "IN_PROGRESS_MH"
data["hold"] = HOLD
data["current"] = "marshallislands"
wave.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print("updated wave JSON Marshall Islands entry")
print("GATE years", GATE_YEARS)
print("GATE stems", GATE_STEMS)
print("n_gate", len(GATE_YEARS) + len(GATE_STEMS))
print("HOLD", HOLD)
print("GATE language: English years+stems")
