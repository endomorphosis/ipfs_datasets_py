#!/usr/bin/env python3
"""Adapt the Antigua and Barbuda English memsafe FIRST_IR pack to Côte d'Ivoire CI.

French Côte d'Ivoire; FIRST_IR; HOLD 0 STRICT after-AG (CI→PR→ST→CV→SC→CF→YE→DJ).
Soft never-thin ON; SKIP_US; Italy BLOCKED. WAVE after_tj fifth country (after
DM→SL→GM→AG LIVE), NOT wave end. GATE: attested years + French legal stems from
articles.parquet tip 67ef43d5e4b3 (French; include ivoire/republique). URL
www/gov/ci query-only, NOT GATE.
Source tip 85734f06153d (Antigua and Barbuda English) — override language to French.
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
SRC_TIP_FULL = "85734f06153d45a6f2ceb9e69bd5c4d7b50de23a"
SRC_TIP_SHORT = "85734f06153d"
DST_TIP_FULL = "67ef43d5e4b3053bccc68b9a6bebbbc1f4e98bd3"
DST_TIP_SHORT = "67ef43d5e4b3"
FLOOR_LAWS, FLOOR_ARTS = 71, 3771

# Sampled from data/articles.parquet @ 67ef43d5e4b3 (~10 years + ~11 French stems)
GATE_YEARS = ["2000", "2016", "2013", "2020", "2019", "2012", "1964", "2011", "2014", "2004"]
GATE_STEMS = [
    "article", "loi", "decret", "ministre", "personne", "code",
    "section", "ordonnance", "ivoire", "republique", "etat",
]
GATE_NOTE_YEARS = "/".join(GATE_YEARS)
GATE_NOTE_STEMS = "/".join(GATE_STEMS)
HOLD = "HOLD 0 STRICT after-AG (CI→PR→ST→CV→SC→CF→YE→DJ)"
WAVE_POS = (
    "fifth country of after_tj wave "
    "(after DM→SL→GM→AG LIVE; CI→PR→ST→CV→SC→CF→YE→DJ; NOT wave end)"
)
DEST_CHAIN = "CI→PR→ST→CV→SC→CF→YE→DJ"
SRC_CHAIN = "AG→CI→PR→ST→CV→SC→CF→YE→DJ"
SRC_HOLD = "HOLD 0 STRICT after-GM (AG→CI→PR→ST→CV→SC→CF→YE→DJ)"
SRC_WAVE = (
    "fourth country of after_tj wave "
    "(after DM→SL→GM LIVE; AG→CI→PR→ST→CV→SC→CF→YE→DJ; NOT wave end)"
)

FILES = [
    ("antigua_barbuda_soft_filter.py", "cotedivoire_soft_filter.py"),
    (f"antigua_barbuda_corpus_stream_{SRC_TIP_SHORT}.py", f"cotedivoire_corpus_stream_{DST_TIP_SHORT}.py"),
    (f"antigua_barbuda_encode_memsafe_{SRC_TIP_SHORT}.py", f"cotedivoire_encode_memsafe_{DST_TIP_SHORT}.py"),
    (f"antigua_barbuda_finish_from_emb_{SRC_TIP_SHORT}.py", f"cotedivoire_finish_from_emb_{DST_TIP_SHORT}.py"),
    (f"antigua_barbuda_stream_graph_parts_{SRC_TIP_SHORT}.py", f"cotedivoire_stream_graph_parts_{DST_TIP_SHORT}.py"),
    (f"antigua_barbuda_package_memsafe_{SRC_TIP_SHORT}.py", f"cotedivoire_package_memsafe_{DST_TIP_SHORT}.py"),
    ("antigua_barbuda_upload.py", "cotedivoire_upload.py"),
    ("antigua_barbuda_bm25_smoke.py", "cotedivoire_bm25_smoke.py"),
    ("antigua_barbuda_write_publish_report.py", "cotedivoire_write_publish_report.py"),
    (f"antigua_barbuda_orchestrator_{SRC_TIP_SHORT}.py", f"cotedivoire_orchestrator_{DST_TIP_SHORT}.py"),
]


def adapt(text: str, dst_name: str) -> str:
    # Protect BM25 / bm25
    text = text.replace("BM25", "\x00BM25\x00").replace("bm25", "\x00bm25\x00")
    text = text.replace("bmjacency", "adjacency")

    # Protect / rewrite HOLD + wave BEFORE ISO/slug swaps (AG appears in SRC_CHAIN)
    text = text.replace(SRC_HOLD, "\x00DESTHOLD\x00")
    text = text.replace(SRC_WAVE, "\x00DESTWAVE\x00")
    text = text.replace(SRC_CHAIN, "\x00DESTCHAIN\x00")
    text = text.replace(HOLD, "\x00DESTHOLD\x00")
    text = text.replace(DEST_CHAIN, "\x00DESTCHAIN\x00")
    text = text.replace(WAVE_POS, "\x00DESTWAVE\x00")
    text = text.replace("after-GM", "\x00AFTERAG\x00")
    text = text.replace("after GM ", "\x00AFTERAG_SP\x00")
    text = text.replace("after_tj", "\x00AFTERTJ_US\x00")
    text = text.replace("DM→SL→GM LIVE", "\x00DMSLGMAG\x00")
    text = text.replace("fourth country of \x00AFTERTJ_US\x00 wave", "\x00DESTWAVE_SHORT\x00")
    text = text.replace("fourth country of after_tj wave", "\x00DESTWAVE_SHORT\x00")

    reps = [
        (SRC_TIP_FULL, DST_TIP_FULL),
        (SRC_TIP_SHORT, DST_TIP_SHORT),
        ("endomorphosis/ipfs_antigua_barbuda_laws", "endomorphosis/ipfs_cotedivoire_laws"),
        ("justicedao/ipfs_antigua_barbuda_laws_ir", "justicedao/ipfs_cotedivoire_laws_ir"),
        ("ipfs_antigua_barbuda_laws_ir", "ipfs_cotedivoire_laws_ir"),
        ("ipfs_antigua_barbuda_laws", "ipfs_cotedivoire_laws"),
        # HOLD / wave restore tokens mapped to dest
        ("\x00DESTHOLD\x00", HOLD),
        ("\x00DESTWAVE\x00", WAVE_POS),
        ("\x00DESTWAVE_SHORT\x00", WAVE_POS),
        ("\x00DESTCHAIN\x00", DEST_CHAIN),
        ("\x00AFTERAG\x00", "after-AG"),
        ("\x00AFTERAG_SP\x00", "after AG "),
        ("\x00DMSLGMAG\x00", "DM→SL→GM→AG LIVE"),
        ("AG FIRST_IR (not wave end)", "CI FIRST_IR (not wave end)"),
        ("www/gov/ag", "www/gov/ci"),
        # Language override English → French BEFORE country name swaps that mention English
        ("English (Antigua and Barbuda)", "French (Côte d'Ivoire)"),
        ("English Antigua and Barbuda", "French Côte d'Ivoire"),
        ("ASCII-fold English", "ASCII-fold French"),
        ("English legal stems", "French legal stems"),
        ("English legal corpus", "French legal corpus"),
        ("Antigua and Barbuda", "Côte d'Ivoire"),
        # slug / path forms (underscore → compact)
        ("antigua_barbuda_ranked", "cotedivoire_ranked"),
        ("antigua_barbuda_gate", "cotedivoire_gate"),
        ("antigua_barbuda_pass", "cotedivoire_pass"),
        ("antigua_barbuda_encode_memsafe", "cotedivoire_encode_memsafe"),
        ("antigua_barbuda_package_memsafe", "cotedivoire_package_memsafe"),
        ("antigua_barbuda_corpus_stream", "cotedivoire_corpus_stream"),
        ("antigua_barbuda_encode_done", "cotedivoire_encode_done"),
        ("antigua_barbuda_", "cotedivoire_"),
        ("antigua_barbuda", "cotedivoire"),
        # ISO whole-token / path forms only
        ('"AG"', '"CI"'),
        ("AG-attested", "CI-attested"),
        ("(AG)", "(CI)"),
        ('"ag"', '"ci"'),
        ("/ag", "/ci"),
        # floors 150/4387 → 71/3771
        ("150/4387", "71/3771"),
        ("150 / 4387", "71 / 3771"),
        ("150, 4387", "71, 3771"),
        ("FLOOR_LAWS, FLOOR_ARTS = 150, 4387", "FLOOR_LAWS, FLOOR_ARTS = 71, 3771"),
        ("or 150)", "or 71)"),
        ("or 150,", "or 71,"),
        ("or 150}", "or 71}"),
        ("= 150,", "= 71,"),
        ("= 150", "= 71"),
        ("@ 150/", "@ 71/"),
        (" 150/", " 71/"),
        ("floor 150/", "floor 71/"),
        ("(150/", "(71/"),
        (" or 150", " or 71"),
        (" 4387", " 3771"),
        ("4387", "3771"),
        # language field leftovers
        ('"language": "English"', '"language": "French"'),
        ('"lang": "English"', '"lang": "French"'),
        ("language: English", "language: French"),
        ("Language: English", "Language: French"),
    ]
    for a, b in reps:
        text = text.replace(a, b)

    text = text.replace("\x00BM25\x00", "BM25").replace("\x00bm25\x00", "bm25")
    text = text.replace("\x00AFTERTJ_US\x00", "after_tj")
    text = text.replace("\x00DESTHOLD\x00", HOLD)
    text = text.replace("\x00DESTCHAIN\x00", DEST_CHAIN)
    text = text.replace("\x00DESTWAVE\x00", WAVE_POS)

    text = text.replace("FLOOR_LAWS, FLOOR_ARTS = 150, 3771", "FLOOR_LAWS, FLOOR_ARTS = 71, 3771")
    text = text.replace("FLOOR_LAWS, FLOOR_ARTS = 71, 4387", "FLOOR_LAWS, FLOOR_ARTS = 71, 3771")
    text = text.replace('int(pack.get("n_articles") or 4387)', 'int(pack.get("n_articles") or 3771)')
    text = text.replace('int(pack.get("n_articles") or 3771)', 'int(pack.get("n_articles") or 3771)')
    text = text.replace('int(pack.get("n_laws") or 150)', 'int(pack.get("n_laws") or 71)')
    text = text.replace('int(pack.get("n_laws") or 71)', 'int(pack.get("n_laws") or 71)')

    # display name fixes (slug vs title)
    text = text.replace('"name": "cotedivoire"', '"name": "Côte d\'Ivoire"')
    text = text.replace('"name": "Côte d\'Ivoire"', '"name": "Côte d\'Ivoire"')
    text = text.replace('"slug": "Côte d\'Ivoire"', '"slug": "cotedivoire"')

    if dst_name == "cotedivoire_bm25_smoke.py":
        start = text.index("GATE = [")
        end = text.index("]", start) + 1
        years_line = ", ".join(f'"{y}"' for y in GATE_YEARS)
        stems_line = ", ".join(f'"{s}"' for s in GATE_STEMS)
        gate = f"GATE = [\n    {years_line},\n    {stems_line},\n]"
        text = text[:start] + gate + text[end:]
        text = text.replace(
            'QUERIES = GATE + ["www", "gov", "ag"',
            'QUERIES = GATE + ["www", "gov", "ci"',
        )
        text = text.replace(
            'QUERIES = GATE + ["www", "gov", "ci"',
            'QUERIES = GATE + ["www", "gov", "ci"',
        )
        # Drop English diagnostic extras; keep French-friendly extras
        text = re.sub(
            r'QUERIES = GATE \+ \["www", "gov", "ci"[^\]]*\]',
            'QUERIES = GATE + ["www", "gov", "ci", "officiel", "tribunal", "justice", "penal", "constitution"]',
            text,
        )
        note = (
            f"attested years {GATE_NOTE_YEARS} plus French legal stems {GATE_NOTE_STEMS} "
            f"from articles.parquet HEAD tip {DST_TIP_SHORT}; URL www/gov/ci is query-only, not GATE."
        )
        text = re.sub(
            r"GATE = attested years [^;]+; URL www/gov/(?:ag|ci) is query-only, not GATE\.",
            f"GATE = {note}",
            text,
        )
        text = text.replace('"antigua_barbuda_pass"', '"cotedivoire_pass"')
        text = text.replace('"cotedivoire_pass"', '"cotedivoire_pass"')
        text = text.replace('"antigua_barbuda_gate"', '"cotedivoire_gate"')
        text = text.replace('"cotedivoire_gate"', '"cotedivoire_gate"')
        text = text.replace(
            "attested Antigua and Barbuda years and English legal stems",
            "attested Côte d'Ivoire years and French legal stems",
        )
        text = text.replace(
            "attested Côte d'Ivoire years and French legal stems",
            "attested Côte d'Ivoire years and French legal stems",
        )
        text = text.replace(
            "attested Côte d'Ivoire years and English legal stems",
            "attested Côte d'Ivoire years and French legal stems",
        )
        # drop leftover antigua GATE stems if any
        text = text.replace('"antigua"', '"ivoire"')
        # restore slug keys
        text = text.replace('"ivoire_pass"', '"cotedivoire_pass"')
        text = text.replace('"ivoire_gate"', '"cotedivoire_gate"')
        # docstring language
        text = text.replace("— English legal corpus", "— French legal corpus")
        text = text.replace("English legal corpus", "French legal corpus")
        text = text.replace("English Antigua", "French Côte d'Ivoire")

    if dst_name == "cotedivoire_write_publish_report.py":
        new_gate = f"{GATE_NOTE_YEARS} + stems {GATE_NOTE_STEMS}"
        text = re.sub(
            r"attested years [0-9/]+ \+ stems [a-z_/]+",
            f"attested years {new_gate}",
            text,
        )
        text = text.replace("English GATE", "French (Côte d'Ivoire) GATE")
        text = text.replace(
            "ASCII-fold French (Côte d'Ivoire) GATE",
            "ASCII-fold French (Côte d'Ivoire) GATE",
        )
        text = text.replace(
            "ASCII-fold English (Côte d'Ivoire) GATE",
            "ASCII-fold French (Côte d'Ivoire) GATE",
        )
        text = re.sub(
            r"HOLD 0 STRICT after-GM[^;]*; collectors kept dead \(pkill\); soft never-thin ON; SKIP_US; Italy BLOCKED;[^\"\n]*",
            f"{HOLD}; collectors kept dead (pkill); soft never-thin ON; SKIP_US; Italy BLOCKED; {WAVE_POS}",
            text,
        )
        text = re.sub(
            r"HOLD 0 STRICT after-AG[^;]*; collectors kept dead \(pkill\); soft never-thin ON; SKIP_US; Italy BLOCKED;[^\"\n]*",
            f"{HOLD}; collectors kept dead (pkill); soft never-thin ON; SKIP_US; Italy BLOCKED; {WAVE_POS}",
            text,
        )
        text = text.replace("www/gov/ag is query-only", "www/gov/ci is query-only")
        text = text.replace("antigua_barbuda/", "cotedivoire/")
        # Fix BM25 note to French GATE
        text = re.sub(
            r'BM25 PASS on Côte d\'Ivoire ASCII-fold (?:English|French) \(Côte d\'Ivoire\) GATE \([^)]+\); URL www/gov/ci is query-only, not GATE',
            f"BM25 PASS on Côte d'Ivoire ASCII-fold French GATE (attested years {GATE_NOTE_YEARS} + stems {GATE_NOTE_STEMS}); URL www/gov/ci is query-only, not GATE",
            text,
        )

    leftovers = (
        "Antigua and Barbuda", "antigua_barbuda", "Antigua", "antigua",
        "Gambia", "gambia",
        "Sierra Leone", "sierraleone",
        "Dominica", "dominica",
        "Saint Lucia", "saint_lucia",
        "Mauritius", "mauritius",
        "Curaçao", "Curacao", "curacao", "Dutch",
        "Solomon Islands", "solomonislands",
        "Belize", "belize", "Lesotho", "lesotho",
        "Haiti", "Nauru", "Montserrat", "Bermuda", "bermuda",
        "British Virgin Islands", "Gabon", "Togo", "Anguilla", "Cook Islands",
        "Tuvalu", "tuvalu", "Liberia", "liberia", "Syria", "syria", "Arabic",
        "arabic", "Tonga", "tonga", "Bahamas", "bahamas",
        "bmjacency", "msjacency",
        "English (Antigua", "English Antigua",
        "English (Gambia", "English Gambia",
        "Tajikistan", "tajikistan",
        "Barbuda", "barbuda",
    )
    # Allow "English" only if somehow residual in tokenizer notes we missed — reject
    found = [x for x in leftovers if x in text]
    if found:
        raise RuntimeError(f"language/country leftovers in {dst_name}: {found}")
    # Reject residual English language claims (French pack)
    if re.search(r'\bEnglish\b', text):
        # allow only in comments saying we overrode FROM English? Prefer none.
        raise RuntimeError(f"leftover English token in {dst_name}")
    if dst_name.endswith("_bm25_smoke.py") and '", "ag"' in text:
        raise RuntimeError(f"leftover ag query token in {dst_name}")
    if dst_name.endswith("_bm25_smoke.py") and "www/gov/ag" in text:
        raise RuntimeError(f"leftover gov/ag in {dst_name}")
    # reject bare ISO leftovers that should have been swapped
    scrub = text
    scrub = scrub.replace(DEST_CHAIN, "XX")
    scrub = scrub.replace(HOLD, "XX")
    scrub = scrub.replace(WAVE_POS, "XX")
    scrub = scrub.replace("after-AG", "after-XX")
    scrub = scrub.replace("after AG ", "after XX ")
    scrub = scrub.replace("after_tj", "after_xx")
    scrub = scrub.replace("DM→SL→GM→AG LIVE", "XX→XX→XX→XX LIVE")
    scrub = scrub.replace("after DM→SL→GM→AG LIVE", "after XX→XX→XX→XX LIVE")
    if '"AG"' in scrub or "(AG)" in scrub or "AG→" in scrub or "AG-attested" in scrub:
        tmp = scrub
        if re.search(r'(?<![A-Za-z])AG(?![A-Za-z])', tmp):
            raise RuntimeError(f"leftover AG tokens in {dst_name}: ...{tmp[max(0,tmp.find('AG')-20):tmp.find('AG')+20]}...")
    if "Antigua" in text or "antigua" in text or "Barbuda" in text or "barbuda" in text:
        raise RuntimeError(f"leftover Antigua/Barbuda in {dst_name}")
    if "ipfs_antigua" in text:
        raise RuntimeError(f"leftover antigua path in {dst_name}")
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
    if entry.get("slug") == "cotedivoire" or entry.get("iso2") == "CI":
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
            "iso2": "CI",
            "repo": "endomorphosis/ipfs_cotedivoire_laws",
            "years_attested": [int(y) for y in GATE_YEARS],
            "gate_years": [int(y) for y in GATE_YEARS],
            "gate_stems": GATE_STEMS,
            "note": (
                f"CI FIRST_IR scaffold; tip MATCH {DST_TIP_SHORT}@71/3771; {HOLD}; "
                f"soft never-thin ON; SKIP_US; Italy BLOCKED; {WAVE_POS}"
            ),
            "status": "CLAIMED",
        })
        break
else:
    raise RuntimeError("Côte d'Ivoire entry missing from wave JSON")
wave.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print("updated wave JSON Côte d'Ivoire entry")
print("GATE years", GATE_YEARS)
print("GATE stems", GATE_STEMS)
print("n_gate", len(GATE_YEARS) + len(GATE_STEMS))
print("GATE language: French")
print("HOLD", HOLD)
