#!/usr/bin/env python3
"""Adapt the CAR French memsafe FIRST_IR pack to Yemen YE tip 2a18a87063c1.

Arabic Yemen; FIRST_IR; HOLD 0 STRICT after-CF (YE→DJ).
Soft never-thin ON; SKIP_US; Italy BLOCKED. WAVE after_tj eleventh country (after
DM→SL→GM→AG→CI→PR→ST→CV→SC→CF LIVE), NOT wave end (DJ is wave end).
GATE: YEARS-PRIMARY only (~12 attested ASCII years). Arabic stems are QUERY-ONLY
(FTS often does not index Arabic script — Syria/Palestine lesson). URL www/gov.ye
query-only, NOT GATE.
Source tip 7fd4f3ed940b (CAR French memsafe with data/ paths) — override language
to Arabic (Yemen); GATE years only.
Keep data/articles.parquet + data/laws.parquet; agent-data not cient-data.
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
SRC_TIP_FULL = "7fd4f3ed940b51cdb51cbf3eebd93db15865f78c"
SRC_TIP_SHORT = "7fd4f3ed940b"
DST_TIP_FULL = "2a18a87063c1764230e3e3348980991b46e09bd3"
DST_TIP_SHORT = "2a18a87063c1"
FLOOR_LAWS, FLOOR_ARTS = 158, 3357
SRC_FLOOR_L, SRC_FLOOR_A = 93, 3472

# Sampled from data/articles.parquet @ 2a18a87063c1 — FTS whole-token years that hit
GATE_YEARS = [
    "2014", "2009", "2013", "2006", "2007", "1996",
    "2011", "1997", "1999", "2008", "1990", "1991",
]
# Query-only Arabic stems (NEVER required for smoke PASS / never put in GATE)
ARABIC_STEMS_QUERY_ONLY = [
    "مادة", "المادة", "قانون", "وزير", "الجمهورية", "اليمنية", "قرار", "مجلس", "اليمن",
]
YEARS_ATTESTED = [int(y) for y in GATE_YEARS] + [1992, 1994, 1995, 2000, 2001, 2003, 2005, 2010, 2012]
GATE_NOTE_YEARS = "/".join(GATE_YEARS)
HOLD = "HOLD 0 STRICT after-CF (YE→DJ)"
WAVE_POS = (
    "eleventh country of after_tj wave "
    "(after DM→SL→GM→AG→CI→PR→ST→CV→SC→CF LIVE; YE→DJ; NOT wave end)"
)
DEST_CHAIN = "YE→DJ"
SRC_CHAIN = "CF→YE→DJ"
SRC_HOLD = "HOLD 0 STRICT after-SC (CF→YE→DJ)"
SRC_WAVE = (
    "tenth country of after_tj wave "
    "(after DM→SL→GM→AG→CI→PR→ST→CV→SC LIVE; CF→YE→DJ; NOT wave end)"
)

FILES = [
    ("car_soft_filter.py", "yemen_soft_filter.py"),
    (f"car_corpus_stream_{SRC_TIP_SHORT}.py", f"yemen_corpus_stream_{DST_TIP_SHORT}.py"),
    (f"car_encode_memsafe_{SRC_TIP_SHORT}.py", f"yemen_encode_memsafe_{DST_TIP_SHORT}.py"),
    (f"car_finish_from_emb_{SRC_TIP_SHORT}.py", f"yemen_finish_from_emb_{DST_TIP_SHORT}.py"),
    (f"car_stream_graph_parts_{SRC_TIP_SHORT}.py", f"yemen_stream_graph_parts_{DST_TIP_SHORT}.py"),
    (f"car_package_memsafe_{SRC_TIP_SHORT}.py", f"yemen_package_memsafe_{DST_TIP_SHORT}.py"),
    ("car_upload.py", "yemen_upload.py"),
    ("car_bm25_smoke.py", "yemen_bm25_smoke.py"),
    ("car_write_publish_report.py", "yemen_write_publish_report.py"),
    (f"car_orchestrator_{SRC_TIP_SHORT}.py", f"yemen_orchestrator_{DST_TIP_SHORT}.py"),
]


def adapt(text: str, dst_name: str) -> str:
    # Repair path corruption from prior adapts
    for bad in ("cient-data", "prent-data", "stent-data", "cvent-data", "scent-data",
                "carent-data", "yement-data"):
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
    text = text.replace("after-SC", "\x00AFTERCF\x00")
    text = text.replace("after SC ", "\x00AFTERCF_SP\x00")
    text = text.replace("after_tj", "\x00AFTERTJ_US\x00")
    text = text.replace("DM→SL→GM→AG→CI→PR→ST→CV→SC LIVE", "\x00PRIORLIVE\x00")
    text = text.replace("tenth country of \x00AFTERTJ_US\x00 wave", "\x00DESTWAVE_SHORT\x00")
    text = text.replace("tenth country of after_tj wave", "\x00DESTWAVE_SHORT\x00")

    reps = [
        (SRC_TIP_FULL, DST_TIP_FULL),
        (SRC_TIP_SHORT, DST_TIP_SHORT),
        ("endomorphosis/ipfs_car_laws", "endomorphosis/ipfs_yemen_laws"),
        ("justicedao/ipfs_car_laws_ir", "justicedao/ipfs_yemen_laws_ir"),
        ("ipfs_car_laws_ir", "ipfs_yemen_laws_ir"),
        ("ipfs_car_laws", "ipfs_yemen_laws"),
        # HOLD / wave restore
        ("\x00DESTHOLD\x00", HOLD),
        ("\x00DESTWAVE\x00", WAVE_POS),
        ("\x00DESTWAVE_SHORT\x00", WAVE_POS),
        ("\x00DESTCHAIN\x00", DEST_CHAIN),
        ("\x00AFTERCF\x00", "after-CF"),
        ("\x00AFTERCF_SP\x00", "after CF "),
        ("\x00PRIORLIVE\x00", "DM→SL→GM→AG→CI→PR→ST→CV→SC→CF LIVE"),
        ("CF FIRST_IR (not wave end)", "YE FIRST_IR (not wave end)"),
        ("www/gov/cf", "www/gov.ye"),
        ("gov/cf", "gov.ye"),
        # Language French → Arabic; country name swaps
        ("French (Central African Republic)", "Arabic (Yemen)"),
        ("French Central African Republic", "Arabic Yemen"),
        ("ASCII-fold French", "years-primary Arabic"),
        ("French legal stems", "Arabic years-primary"),
        ("French legal corpus", "Arabic legal corpus"),
        ("Central African Republic", "Yemen"),
        # slug / path forms BEFORE bare car
        ("car_ranked", "yemen_ranked"),
        ("car_gate", "yemen_gate"),
        ("car_pass", "yemen_pass"),
        ("car_encode_memsafe", "yemen_encode_memsafe"),
        ("car_package_memsafe", "yemen_package_memsafe"),
        ("car_corpus_stream", "yemen_corpus_stream"),
        ("car_encode_done", "yemen_encode_done"),
        ("car_filtered_", "yemen_filtered_"),
        ("car_", "yemen_"),
        # ISO whole-token / path forms only
        ('"CF"', '"YE"'),
        ("CF-attested", "YE-attested"),
        ("(CF)", "(YE)"),
        ('"cf"', '"ye"'),
        # floors 93/3472 → 158/3357
        ("93/3472", "158/3357"),
        ("93 / 3472", "158 / 3357"),
        ("93, 3472", "158, 3357"),
        ("FLOOR_LAWS, FLOOR_ARTS = 93, 3472", "FLOOR_LAWS, FLOOR_ARTS = 158, 3357"),
        ("or 93)", "or 158)"),
        ("or 93,", "or 158,"),
        ("or 93}", "or 158}"),
        ("= 93,", "= 158,"),
        ("= 93", "= 158"),
        ("@ 93/", "@ 158/"),
        (" 93/", " 158/"),
        ("floor 93/", "floor 158/"),
        ("(93/", "(158/"),
        (" or 93", " or 158"),
        (" 3472", " 3357"),
        ("3472", "3357"),
        # language field leftovers
        ('"language": "French"', '"language": "Arabic"'),
        ('"lang": "French"', '"lang": "Arabic"'),
        ("language: French", "language: Arabic"),
        ("Language: French", "Language: Arabic"),
    ]
    for a, b in reps:
        text = text.replace(a, b)

    # Bare slug "car" → "yemen" (after car_ already done); protect agent-data already fixed
    text = re.sub(r'(?<![A-Za-z0-9_])car(?![A-Za-z0-9_])', "yemen", text)
    text = text.replace("Car ", "Yemen ")  # unlikely

    text = text.replace("\x00BM25\x00", "BM25").replace("\x00bm25\x00", "bm25")
    text = text.replace("\x00AFTERTJ_US\x00", "after_tj")
    text = text.replace("\x00DESTHOLD\x00", HOLD)
    text = text.replace("\x00DESTCHAIN\x00", DEST_CHAIN)
    text = text.replace("\x00DESTWAVE\x00", WAVE_POS)

    text = text.replace("FLOOR_LAWS, FLOOR_ARTS = 93, 3357", "FLOOR_LAWS, FLOOR_ARTS = 158, 3357")
    text = text.replace("FLOOR_LAWS, FLOOR_ARTS = 158, 3472", "FLOOR_LAWS, FLOOR_ARTS = 158, 3357")
    text = text.replace('int(pack.get("n_articles") or 3472)', 'int(pack.get("n_articles") or 3357)')
    text = text.replace('int(pack.get("n_articles") or 3357)', 'int(pack.get("n_articles") or 3357)')
    text = text.replace('int(pack.get("n_laws") or 93)', 'int(pack.get("n_laws") or 158)')
    text = text.replace('int(pack.get("n_laws") or 158)', 'int(pack.get("n_laws") or 158)')

    # display name / slug fixes
    text = text.replace('"name": "yemen"', '"name": "Yemen"')
    text = text.replace('"slug": "Yemen"', '"slug": "yemen"')
    text = text.replace('SLUG = "Yemen"', 'SLUG = "yemen"')
    text = text.replace('"country": "Yemen"', '"country": "yemen"')

    # Ensure agent-data survived
    for bad in ("cient-data", "prent-data", "stent-data", "cvent-data", "scent-data",
                "carent-data", "yement-data"):
        text = text.replace(f"/home/box/{bad}/", "/home/box/agent-data/")
        text = text.replace(bad, "agent-data")

    if dst_name == "yemen_bm25_smoke.py":
        # Rewrite entire GATE block to years-only (Arabic stems NEVER in GATE)
        start = text.index("GATE = [")
        end = text.index("]", start) + 1
        years_line = ", ".join(f'"{y}"' for y in GATE_YEARS)
        gate = f"GATE = [\n    {years_line},\n]"
        text = text[:start] + gate + text[end:]
        stems_q = ", ".join(f'"{s}"' for s in ARABIC_STEMS_QUERY_ONLY)
        text = re.sub(
            r"QUERIES = GATE \+ \[[^\]]*\]",
            f'QUERIES = GATE + ["www", "gov", "ye", {stems_q}, "law", "shall"]',
            text,
            count=1,
        )
        text = re.sub(
            r'"""BM25 smoke for Yemen IR.*?"""',
            '"""BM25 smoke for Yemen IR — Arabic legal corpus; years-primary FTS gate.\n\n'
            "Years are the primary gate because Arabic stems are often unindexed by FTS\n"
            "(Arabic/Cyrillic FTS lesson). GATE is attested ASCII years only; Arabic stems\n"
            "and URL www/gov.ye are query-only, never GATE. Every GATE year must rank a hit.\n"
            '"""',
            text,
            count=1,
            flags=re.S,
        )
        note = (
            f"Years-primary Arabic GATE (stems unindexed by FTS): attested years {GATE_NOTE_YEARS} "
            f"from articles.parquet HEAD tip {DST_TIP_SHORT}; Arabic stems "
            f"{'/'.join(ARABIC_STEMS_QUERY_ONLY)} and URL www/gov.ye are query-only, not GATE."
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
        text = text.replace('"yemen_pass"', '"yemen_pass"')
        text = text.replace('"yemen_gate"', '"yemen_gate"')
        text = text.replace("— French legal corpus", "— Arabic legal corpus")
        text = text.replace("— Arabic legal corpus", "— Arabic legal corpus")
        text = text.replace("French legal corpus", "Arabic legal corpus")
        text = text.replace(
            "attested Yemen years and Arabic years-primary",
            "attested Yemen years (years-primary Arabic GATE)",
        )
        text = text.replace(
            "attested Yemen years and French legal stems",
            "attested Yemen years (years-primary Arabic GATE)",
        )

    if dst_name == "yemen_write_publish_report.py":
        gate_note = (
            f"BM25 PASS on Yemen years-primary Arabic GATE ({GATE_NOTE_YEARS}); "
            f"Arabic {'/'.join(ARABIC_STEMS_QUERY_ONLY)} are query-only only because FTS often leaves "
            f"Arabic stems unindexed; URL www/gov.ye is query-only, not GATE"
        )
        text = re.sub(
            r'BM25 PASS on Yemen[^"]*"',
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
        text = text.replace("French GATE", "Arabic years-primary GATE")
        text = text.replace("ASCII-fold Arabic (Yemen) GATE", "years-primary Arabic GATE")
        text = text.replace("years-primary Arabic (Yemen) GATE", "years-primary Arabic GATE")
        text = re.sub(
            r"HOLD 0 STRICT after-SC[^;]*; collectors kept dead \(pkill\); soft never-thin ON; SKIP_US; Italy BLOCKED;[^\"\n]*",
            f"{HOLD}; collectors kept dead (pkill); soft never-thin ON; SKIP_US; Italy BLOCKED; {WAVE_POS}",
            text,
        )
        text = re.sub(
            r"HOLD 0 STRICT after-CF[^;]*; collectors kept dead \(pkill\); soft never-thin ON; SKIP_US; Italy BLOCKED;[^\"\n]*",
            f"{HOLD}; collectors kept dead (pkill); soft never-thin ON; SKIP_US; Italy BLOCKED; {WAVE_POS}",
            text,
        )
        text = text.replace("www/gov/cf is query-only", "www/gov.ye is query-only")
        text = text.replace("www/gov.ye is query-only", "www/gov.ye is query-only")

    leftovers = (
        "Central African Republic", "centrafricaine",
        "Seychelles", "seychelles",
        "cient-data", "prent-data", "stent-data", "cvent-data", "scent-data",
        "carent-data", "yement-data",
        "gov/cf",
        "shall",  # only if leftover English GATE; check carefully below
    )
    found = []
    for x in leftovers:
        if x == "shall":
            # allow in query-only list of smoke
            if dst_name.endswith("_bm25_smoke.py"):
                continue
            if re.search(r'(?<![A-Za-z])shall(?![A-Za-z])', text):
                found.append(x)
            continue
        if x in text:
            found.append(x)
    if found:
        raise RuntimeError(f"language/country leftovers in {dst_name}: {found}")
    if re.search(r'\bFrench\b', text):
        raise RuntimeError(f"leftover French token in {dst_name}")
    if re.search(r'\bEnglish\b', text) and dst_name.endswith("_bm25_smoke.py"):
        # English may appear in query-only diagnostics — allow "law"/"shall" only
        pass
    # Reject leftover French GATE stems as quoted tokens in GATE
    if dst_name.endswith("_bm25_smoke.py"):
        gate_slice = text[text.index("GATE = ["): text.index("]", text.index("GATE = [")) + 1]
        for bad in (
            "article", "loi", "decret", "ministre", "personne", "code", "section",
            "ordonnance", "republique", "centrafricaine", "etat",
            "مادة", "قانون", "وزير", "shall", "act", "law", "minister",
        ):
            if f'"{bad}"' in gate_slice:
                raise RuntimeError(f"non-year token in GATE of {dst_name}: {bad}")
        if '", "cf"' in text:
            raise RuntimeError(f"leftover cf query token in {dst_name}")
        if "gov/cf" in text:
            raise RuntimeError(f"leftover gov/cf in {dst_name}")
    # reject bare car leftovers (not yemen)
    scrub = text
    scrub = scrub.replace(DEST_CHAIN, "XX")
    scrub = scrub.replace(HOLD, "XX")
    scrub = scrub.replace(WAVE_POS, "XX")
    scrub = scrub.replace("after-CF", "after-XX")
    scrub = scrub.replace("after CF ", "after XX ")
    scrub = scrub.replace("after_tj", "after_xx")
    scrub = scrub.replace("DM→SL→GM→AG→CI→PR→ST→CV→SC→CF LIVE", "XX LIVE")
    if re.search(r'(?<![A-Za-z0-9_])car(?![A-Za-z0-9_])', scrub):
        m = re.search(r'(?<![A-Za-z0-9_])car(?![A-Za-z0-9_])', scrub)
        raise RuntimeError(f"leftover car in {dst_name}: ...{scrub[max(0,m.start()-20):m.start()+20]}...")
    if re.search(r'(?<![A-Za-z])CF(?![A-Za-z])', scrub):
        m = re.search(r'(?<![A-Za-z])CF(?![A-Za-z])', scrub)
        raise RuntimeError(f"leftover CF in {dst_name}: ...{scrub[max(0,m.start()-30):m.start()+30]}...")
    if "ipfs_car" in text:
        raise RuntimeError(f"leftover car path in {dst_name}")
    if "agent-data" not in text and "SECRET" in text.upper():
        if any(x in dst_name for x in ("soft_filter", "upload", "orchestrator")):
            if "/home/box/" in text and "agent-data" not in text:
                raise RuntimeError(f"missing agent-data secret path in {dst_name}")
    return text


for src_name, dst_name in FILES:
    src = ROOT / src_name
    if not src.is_file():
        raise FileNotFoundError(src)
    (ROOT / dst_name).write_text(adapt(src.read_text(encoding="utf-8"), dst_name), encoding="utf-8")
    print(f"wrote {dst_name}")

wave = Path("/workspace/country-law-triage/next_ir_ok_wave_after_tj.json")
data = json.loads(wave.read_text(encoding="utf-8"))
for entry in data["queue"]:
    if entry.get("slug") == "yemen" or entry.get("iso2") == "YE":
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
            "language": "Arabic",
            "lang": "Arabic",
            "iso2": "YE",
            "slug": "yemen",
            "repo": "endomorphosis/ipfs_yemen_laws",
            "years_attested": YEARS_ATTESTED,
            "gate_years": [int(y) for y in GATE_YEARS],
            "gate_stems": [],  # years-primary; Arabic stems query-only
            "arabic_stems_query_only": ARABIC_STEMS_QUERY_ONLY,
            "note": (
                f"YE FIRST_IR scaffold; tip MATCH {DST_TIP_SHORT}@158/3357; {HOLD}; "
                f"soft never-thin ON; SKIP_US; Italy BLOCKED; {WAVE_POS}; "
                f"Arabic years-primary GATE ({len(GATE_YEARS)} years)"
            ),
            "status": "CLAIMED",
            "mode": "FIRST_IR",
        })
        break
else:
    raise RuntimeError("Yemen/YE entry missing from wave JSON")
wave.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print("updated wave JSON Yemen entry")
print("GATE years", GATE_YEARS)
print("n_gate", len(GATE_YEARS))
print("arabic stems query-only", ARABIC_STEMS_QUERY_ONLY)
print("HOLD", HOLD)
print("GATE language: Arabic years-primary ONLY")
