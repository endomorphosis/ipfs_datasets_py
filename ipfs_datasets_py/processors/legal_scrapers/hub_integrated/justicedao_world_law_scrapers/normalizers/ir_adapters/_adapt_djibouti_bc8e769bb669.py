#!/usr/bin/env python3
"""Adapt the Yemen Arabic memsafe FIRST_IR pack to Djibouti DJ tip bc8e769bb669.

French Djibouti; FIRST_IR; HOLD 0 STRICT after-YE (DJ WAVE END).
Soft never-thin ON; SKIP_US; Italy BLOCKED. WAVE END of after_tj
(DM→…→YE LIVE). GATE: attested years + French legal stems from
data/articles.parquet tip bc8e769bb669 (French; include djibouti/republique).
URL www/gov.dj query-only, NOT GATE.
Source tip 2a18a87063c1 (Yemen Arabic years-primary memsafe with data/ paths)
— override language to French (Djibouti); GATE French years+stems (NOT years-primary-only).
Keep data/articles.parquet + data/laws.parquet; agent-data not cient-data.
Do NOT start any next country after LIVE.
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
SRC_TIP_FULL = "2a18a87063c1764230e3e3348980991b46e09bd3"
SRC_TIP_SHORT = "2a18a87063c1"
DST_TIP_FULL = "bc8e769bb669012c993682ed6c4a6c118b569f26"
DST_TIP_SHORT = "bc8e769bb669"
FLOOR_LAWS, FLOOR_ARTS = 165, 3205
SRC_FLOOR_L, SRC_FLOOR_A = 158, 3357

# Sampled from data/articles.parquet @ bc8e769bb669 (~10 years + ~11 French stems)
# Whole-word ASCII-fold FTS hits; laws=165 articles=3205.
GATE_YEARS = [
    "2016", "2021", "2023", "2019", "2022",
    "2025", "2020", "2017", "2018", "2024",
]
GATE_STEMS = [
    "article", "loi", "decret", "ministre", "personne", "code",
    "section", "ordonnance", "republique", "djibouti", "etat",
]
YEARS_ATTESTED = [int(y) for y in GATE_YEARS] + [
    2013, 2008, 2004, 2009, 1994, 2015, 1982, 2000, 2014, 2005,
]
GATE_NOTE_YEARS = "/".join(GATE_YEARS)
GATE_NOTE_STEMS = "/".join(GATE_STEMS)
HOLD = "HOLD 0 STRICT after-YE (DJ WAVE END)"
WAVE_POS = (
    "WAVE END of after_tj wave "
    "(after DM→SL→GM→AG→CI→PR→ST→CV→SC→CF→YE LIVE)"
)
DEST_CHAIN = "DJ WAVE END"
SRC_CHAIN = "YE→DJ"
SRC_HOLD = "HOLD 0 STRICT after-CF (YE→DJ)"
SRC_WAVE = (
    "eleventh country of after_tj wave "
    "(after DM→SL→GM→AG→CI→PR→ST→CV→SC→CF LIVE; YE→DJ; NOT wave end)"
)

FILES = [
    ("yemen_soft_filter.py", "djibouti_soft_filter.py"),
    (f"yemen_corpus_stream_{SRC_TIP_SHORT}.py", f"djibouti_corpus_stream_{DST_TIP_SHORT}.py"),
    (f"yemen_encode_memsafe_{SRC_TIP_SHORT}.py", f"djibouti_encode_memsafe_{DST_TIP_SHORT}.py"),
    (f"yemen_finish_from_emb_{SRC_TIP_SHORT}.py", f"djibouti_finish_from_emb_{DST_TIP_SHORT}.py"),
    (f"yemen_stream_graph_parts_{SRC_TIP_SHORT}.py", f"djibouti_stream_graph_parts_{DST_TIP_SHORT}.py"),
    (f"yemen_package_memsafe_{SRC_TIP_SHORT}.py", f"djibouti_package_memsafe_{DST_TIP_SHORT}.py"),
    ("yemen_upload.py", "djibouti_upload.py"),
    ("yemen_bm25_smoke.py", "djibouti_bm25_smoke.py"),
    ("yemen_write_publish_report.py", "djibouti_write_publish_report.py"),
    (f"yemen_orchestrator_{SRC_TIP_SHORT}.py", f"djibouti_orchestrator_{DST_TIP_SHORT}.py"),
]


def adapt(text: str, dst_name: str) -> str:
    # Repair path corruption from prior adapts
    for bad in (
        "cient-data", "prent-data", "stent-data", "cvent-data", "scent-data",
        "carent-data", "yement-data", "djiboutient-data",
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
    text = text.replace("after-CF", "\x00AFTERYE\x00")
    text = text.replace("after CF ", "\x00AFTERYE_SP\x00")
    text = text.replace("after_tj", "\x00AFTERTJ_US\x00")
    text = text.replace(
        "DM→SL→GM→AG→CI→PR→ST→CV→SC→CF LIVE",
        "\x00PRIORLIVE\x00",
    )
    text = text.replace(
        "eleventh country of \x00AFTERTJ_US\x00 wave",
        "\x00DESTWAVE_SHORT\x00",
    )
    text = text.replace(
        "eleventh country of after_tj wave",
        "\x00DESTWAVE_SHORT\x00",
    )

    reps = [
        (SRC_TIP_FULL, DST_TIP_FULL),
        (SRC_TIP_SHORT, DST_TIP_SHORT),
        ("endomorphosis/ipfs_yemen_laws", "endomorphosis/ipfs_djibouti_laws"),
        ("justicedao/ipfs_yemen_laws_ir", "justicedao/ipfs_djibouti_laws_ir"),
        ("ipfs_yemen_laws_ir", "ipfs_djibouti_laws_ir"),
        ("ipfs_yemen_laws", "ipfs_djibouti_laws"),
        # HOLD / wave restore
        ("\x00DESTHOLD\x00", HOLD),
        ("\x00DESTWAVE\x00", WAVE_POS),
        ("\x00DESTWAVE_SHORT\x00", WAVE_POS),
        ("\x00DESTCHAIN\x00", DEST_CHAIN),
        ("\x00AFTERYE\x00", "after-YE"),
        ("\x00AFTERYE_SP\x00", "after YE "),
        ("\x00PRIORLIVE\x00", "DM→SL→GM→AG→CI→PR→ST→CV→SC→CF→YE LIVE"),
        ("YE FIRST_IR (not wave end)", "DJ FIRST_IR (WAVE END)"),
        ("www/gov.ye", "www/gov.dj"),
        ("gov.ye", "gov.dj"),
        # Language Arabic → French; country name swaps
        ("Arabic (Yemen)", "French (Djibouti)"),
        ("Arabic Yemen", "French Djibouti"),
        ("years-primary Arabic", "ASCII-fold French"),
        ("Arabic years-primary", "French legal stems"),
        ("Arabic legal stems", "French legal stems"),
        ("Arabic legal corpus", "French legal corpus"),
        ("years-primary", "French years+stems"),
        ("Yemen", "Djibouti"),
        # slug / path forms BEFORE bare yemen
        ("yemen_ranked", "djibouti_ranked"),
        ("yemen_gate", "djibouti_gate"),
        ("yemen_pass", "djibouti_pass"),
        ("yemen_encode_memsafe", "djibouti_encode_memsafe"),
        ("yemen_package_memsafe", "djibouti_package_memsafe"),
        ("yemen_corpus_stream", "djibouti_corpus_stream"),
        ("yemen_encode_done", "djibouti_encode_done"),
        ("yemen_filtered_", "djibouti_filtered_"),
        ("yemen_", "djibouti_"),
        # ISO whole-token / path forms only
        ('"YE"', '"DJ"'),
        ("YE-attested", "DJ-attested"),
        ("(YE)", "(DJ)"),
        ('"ye"', '"dj"'),
        # floors 158/3357 → 165/3205
        ("158/3357", "165/3205"),
        ("158 / 3357", "165 / 3205"),
        ("158, 3357", "165, 3205"),
        ("FLOOR_LAWS, FLOOR_ARTS = 158, 3357", "FLOOR_LAWS, FLOOR_ARTS = 165, 3205"),
        ("or 158)", "or 165)"),
        ("or 158,", "or 165,"),
        ("or 158}", "or 165}"),
        ("= 158,", "= 165,"),
        ("= 158", "= 165"),
        ("@ 158/", "@ 165/"),
        (" 158/", " 165/"),
        ("floor 158/", "floor 165/"),
        ("(158/", "(165/"),
        (" or 158", " or 165"),
        (" 3357", " 3205"),
        ("3357", "3205"),
        # language field leftovers
        ('"language": "Arabic"', '"language": "French"'),
        ('"lang": "Arabic"', '"lang": "French"'),
        ("language: Arabic", "language: French"),
        ("Language: Arabic", "Language: French"),
    ]
    for a, b in reps:
        text = text.replace(a, b)

    # Bare slug "yemen" → "djibouti"
    text = re.sub(r"(?<![A-Za-z0-9_])yemen(?![A-Za-z0-9_])", "djibouti", text)

    text = text.replace("\x00BM25\x00", "BM25").replace("\x00bm25\x00", "bm25")
    text = text.replace("\x00AFTERTJ_US\x00", "after_tj")
    text = text.replace("\x00DESTHOLD\x00", HOLD)
    text = text.replace("\x00DESTCHAIN\x00", DEST_CHAIN)
    text = text.replace("\x00DESTWAVE\x00", WAVE_POS)

    text = text.replace(
        "FLOOR_LAWS, FLOOR_ARTS = 158, 3205",
        "FLOOR_LAWS, FLOOR_ARTS = 165, 3205",
    )
    text = text.replace(
        "FLOOR_LAWS, FLOOR_ARTS = 165, 3357",
        "FLOOR_LAWS, FLOOR_ARTS = 165, 3205",
    )
    text = text.replace(
        'int(pack.get("n_articles") or 3357)',
        'int(pack.get("n_articles") or 3205)',
    )
    text = text.replace(
        'int(pack.get("n_articles") or 3205)',
        'int(pack.get("n_articles") or 3205)',
    )
    text = text.replace(
        'int(pack.get("n_laws") or 158)',
        'int(pack.get("n_laws") or 165)',
    )
    text = text.replace(
        'int(pack.get("n_laws") or 165)',
        'int(pack.get("n_laws") or 165)',
    )

    # display name / slug fixes
    text = text.replace('"name": "djibouti"', '"name": "Djibouti"')
    text = text.replace('"slug": "Djibouti"', '"slug": "djibouti"')
    text = text.replace('SLUG = "Djibouti"', 'SLUG = "djibouti"')
    text = text.replace('"country": "Djibouti"', '"country": "djibouti"')

    # Ensure agent-data survived
    for bad in (
        "cient-data", "prent-data", "stent-data", "cvent-data", "scent-data",
        "carent-data", "yement-data", "djiboutient-data",
    ):
        text = text.replace(f"/home/box/{bad}/", "/home/box/agent-data/")
        text = text.replace(bad, "agent-data")

    if dst_name == "djibouti_bm25_smoke.py":
        # Rewrite entire GATE block to French years + stems
        start = text.index("GATE = [")
        end = text.index("]", start) + 1
        years_line = ", ".join(f'"{y}"' for y in GATE_YEARS)
        stems_line = ", ".join(f'"{s}"' for s in GATE_STEMS)
        gate = f"GATE = [\n    {years_line},\n    {stems_line},\n]"
        text = text[:start] + gate + text[end:]
        text = re.sub(
            r"QUERIES = GATE \+ \[[^\]]*\]",
            'QUERIES = GATE + ["www", "gov", "dj", "officiel", "tribunal", "justice", "penal", "constitution"]',
            text,
            count=1,
        )
        text = re.sub(
            r'"""BM25 smoke for Djibouti IR.*?"""',
            '"""BM25 smoke for Djibouti IR — French legal corpus; years + French legal stems FTS gate.\n\n'
            "GATE is attested ASCII years plus French legal stems (ASCII-fold). URL www/gov.dj\n"
            "is query-only, never GATE. Every GATE token must rank a hit.\n"
            '"""',
            text,
            count=1,
            flags=re.S,
        )
        note = (
            f"attested years {GATE_NOTE_YEARS} plus French legal stems {GATE_NOTE_STEMS} "
            f"from articles.parquet HEAD tip {DST_TIP_SHORT}; URL www/gov.dj is query-only, not GATE."
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
        # scrub leftover Arabic / years-primary phrasing
        text = text.replace("— Arabic legal corpus", "— French legal corpus")
        text = text.replace("Arabic legal corpus", "French legal corpus")
        text = text.replace("years-primary Arabic GATE", "French years+stems GATE")
        text = text.replace("French years+stems Arabic GATE", "French years+stems GATE")
        text = text.replace(
            "attested Djibouti years (French years+stems Arabic GATE)",
            "attested Djibouti years and French legal stems",
        )
        text = text.replace(
            "attested Djibouti years (years-primary Arabic GATE)",
            "attested Djibouti years and French legal stems",
        )
        text = text.replace(
            "attested Djibouti years and French legal stems",
            "attested Djibouti years and French legal stems",
        )
        # drop any remaining Arabic script
        text = re.sub(r"[\u0600-\u06FF]+", "", text)
        text = text.replace("//", "/")  # collapse empty stem joins if any

    if dst_name == "djibouti_write_publish_report.py":
        gate_note = (
            f"BM25 PASS on Djibouti ASCII-fold French GATE "
            f"(attested years {GATE_NOTE_YEARS} + stems {GATE_NOTE_STEMS}); "
            f"URL www/gov.dj is query-only, not GATE"
        )
        text = re.sub(
            r'BM25 PASS on Djibouti[^"]*"',
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
        text = text.replace("Arabic years-primary GATE", "French years+stems GATE")
        text = text.replace("years-primary Arabic GATE", "French years+stems GATE")
        text = text.replace("French legal stems GATE", "French years+stems GATE")
        text = re.sub(
            r"HOLD 0 STRICT after-CF[^;]*; collectors kept dead \(pkill\); soft never-thin ON; SKIP_US; Italy BLOCKED;[^\"\n]*",
            f"{HOLD}; collectors kept dead (pkill); soft never-thin ON; SKIP_US; Italy BLOCKED; {WAVE_POS}",
            text,
        )
        text = re.sub(
            r"HOLD 0 STRICT after-YE[^;]*; collectors kept dead \(pkill\); soft never-thin ON; SKIP_US; Italy BLOCKED;[^\"\n]*",
            f"{HOLD}; collectors kept dead (pkill); soft never-thin ON; SKIP_US; Italy BLOCKED; {WAVE_POS}",
            text,
        )
        text = text.replace("www/gov.ye is query-only", "www/gov.dj is query-only")
        text = text.replace("www/gov.dj is query-only", "www/gov.dj is query-only")
        # drop leftover Arabic script in notes
        text = re.sub(r"[\u0600-\u06FF]+/??", "", text)
        text = re.sub(r"Arabic\s+/+", "", text)
        text = re.sub(r"Arabic\s+are query-only[^;]*;", "", text)
        text = re.sub(r"[ \t]{2,}", " ", text)  # do not collapse newlines

    leftovers = (
        "Yemen", "yemen",
        "cient-data", "prent-data", "stent-data", "cvent-data", "scent-data",
        "carent-data", "yement-data", "djiboutient-data",
        "gov.ye",
        "shall",
    )
    found = []
    for x in leftovers:
        if x == "shall":
            if dst_name.endswith("_bm25_smoke.py"):
                continue
            if re.search(r"(?<![A-Za-z])shall(?![A-Za-z])", text):
                found.append(x)
            continue
        if x == "yemen":
            # allow in scrubbed DEST only if leftover after protect
            if re.search(r"(?<![A-Za-z0-9_])yemen(?![A-Za-z0-9_])", text):
                found.append(x)
            continue
        if x in text:
            found.append(x)
    if found:
        raise RuntimeError(f"language/country leftovers in {dst_name}: {found}")
    if re.search(r"\bArabic\b", text):
        raise RuntimeError(f"leftover Arabic token in {dst_name}")
    if re.search(r"[\u0600-\u06FF]", text):
        raise RuntimeError(f"leftover Arabic script in {dst_name}")
    # Reject non-French tokens in GATE
    if dst_name.endswith("_bm25_smoke.py"):
        gate_slice = text[text.index("GATE = ["): text.index("]", text.index("GATE = [")) + 1]
        for bad in (
            "shall", "act", "law", "minister", "person", "republic",
            "مادة", "قانون", "وزير", "centrafricaine", "ivoire",
        ):
            if f'"{bad}"' in gate_slice:
                raise RuntimeError(f"non-French token in GATE of {dst_name}: {bad}")
        # years-only leftover check: GATE must include stems
        for stem in GATE_STEMS:
            if f'"{stem}"' not in gate_slice:
                raise RuntimeError(f"missing French stem in GATE of {dst_name}: {stem}")
        if '", "ye"' in text:
            raise RuntimeError(f"leftover ye query token in {dst_name}")
        if "gov.ye" in text:
            raise RuntimeError(f"leftover gov.ye in {dst_name}")
    # reject bare yemen leftovers
    scrub = text
    scrub = scrub.replace(DEST_CHAIN, "XX")
    scrub = scrub.replace(HOLD, "XX")
    scrub = scrub.replace(WAVE_POS, "XX")
    scrub = scrub.replace("after-YE", "after-XX")
    scrub = scrub.replace("after YE ", "after XX ")
    scrub = scrub.replace("after_tj", "after_xx")
    scrub = scrub.replace(
        "DM→SL→GM→AG→CI→PR→ST→CV→SC→CF→YE LIVE",
        "XX LIVE",
    )
    if re.search(r"(?<![A-Za-z0-9_])yemen(?![A-Za-z0-9_])", scrub):
        m = re.search(r"(?<![A-Za-z0-9_])yemen(?![A-Za-z0-9_])", scrub)
        raise RuntimeError(
            f"leftover yemen in {dst_name}: ...{scrub[max(0, m.start()-20):m.start()+20]}..."
        )
    if re.search(r"(?<![A-Za-z])YE(?![A-Za-z])", scrub):
        m = re.search(r"(?<![A-Za-z])YE(?![A-Za-z])", scrub)
        raise RuntimeError(
            f"leftover YE in {dst_name}: ...{scrub[max(0, m.start()-30):m.start()+30]}..."
        )
    if "ipfs_yemen" in text:
        raise RuntimeError(f"leftover yemen path in {dst_name}")
    if "agent-data" not in text and "SECRET" in text.upper():
        if any(x in dst_name for x in ("soft_filter", "upload", "orchestrator")):
            if "/home/box/" in text and "agent-data" not in text:
                raise RuntimeError(f"missing agent-data secret path in {dst_name}")
    return text


for src_name, dst_name in FILES:
    src = ROOT / src_name
    if not src.is_file():
        raise FileNotFoundError(src)
    (ROOT / dst_name).write_text(
        adapt(src.read_text(encoding="utf-8"), dst_name), encoding="utf-8"
    )
    print(f"wrote {dst_name}")

wave = Path("/workspace/country-law-triage/next_ir_ok_wave_after_tj.json")
data = json.loads(wave.read_text(encoding="utf-8"))
for entry in data["queue"]:
    if entry.get("slug") == "djibouti" or entry.get("iso2") == "DJ":
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
            "iso2": "DJ",
            "slug": "djibouti",
            "repo": "endomorphosis/ipfs_djibouti_laws",
            "years_attested": YEARS_ATTESTED,
            "gate_years": [int(y) for y in GATE_YEARS],
            "gate_stems": GATE_STEMS,
            "note": (
                f"DJ FIRST_IR scaffold; tip MATCH {DST_TIP_SHORT}@165/3205; {HOLD}; "
                f"soft never-thin ON; SKIP_US; Italy BLOCKED; {WAVE_POS}; "
                f"French GATE ({len(GATE_YEARS)} years + {len(GATE_STEMS)} stems)"
            ),
            "status": "CLAIMED",
            "mode": "FIRST_IR",
            "wave_end": True,
        })
        break
else:
    raise RuntimeError("Djibouti/DJ entry missing from wave JSON")

# Mark wave-level WAVE END note
data["wave_status"] = "IN_PROGRESS_DJ_WAVE_END"
data["wave_end_country"] = "djibouti"
data["wave_end_note"] = (
    "DJ is WAVE END of after_tj (DM→…→DJ). After LIVE: clear HOLD; "
    "do NOT start another country; soft lean may resume after CoS confirms."
)
wave.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print("updated wave JSON Djibouti entry")
print("GATE years", GATE_YEARS)
print("GATE stems", GATE_STEMS)
print("n_gate", len(GATE_YEARS) + len(GATE_STEMS))
print("HOLD", HOLD)
print("GATE language: French years+stems")
