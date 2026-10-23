#!/usr/bin/env python3
"""Adapt the Seychelles English memsafe FIRST_IR pack to Central African Republic CF.

French Central African Republic (CAR); FIRST_IR; HOLD 0 STRICT after-SC (CF→YE→DJ).
Soft never-thin ON; SKIP_US; Italy BLOCKED. WAVE after_tj tenth country (after
DM→SL→GM→AG→CI→PR→ST→CV→SC LIVE), NOT wave end. GATE: attested years + French legal
stems from data/articles.parquet tip 7fd4f3ed940b (French; include centrafricaine/
republique). URL www/gov/cf query-only, NOT GATE.
Source tip 18e49bfef602 (Seychelles English) — override language to French (CAR).
Script prefix: car_* (NOT cf_* or centralafrican*).
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
SRC_TIP_FULL = "18e49bfef60298c5af0c230df686cd188a653652"
SRC_TIP_SHORT = "18e49bfef602"
DST_TIP_FULL = "7fd4f3ed940b51cdb51cbf3eebd93db15865f78c"
DST_TIP_SHORT = "7fd4f3ed940b"
FLOOR_LAWS, FLOOR_ARTS = 93, 3472
SRC_FLOOR_L, SRC_FLOOR_A = 118, 3623

# Sampled from data/articles.parquet @ 7fd4f3ed940b (~10 years + ~11 French stems)
# Whole-word ASCII-fold FTS hits; laws=93 articles=3472.
GATE_YEARS = ["2017", "2023", "2007", "2018", "2008", "2020", "2019", "2009", "1993", "2021"]
GATE_STEMS = [
    "article", "loi", "decret", "ministre", "personne", "code",
    "section", "ordonnance", "republique", "centrafricaine", "etat",
]
GATE_NOTE_YEARS = "/".join(GATE_YEARS)
GATE_NOTE_STEMS = "/".join(GATE_STEMS)
HOLD = "HOLD 0 STRICT after-SC (CF→YE→DJ)"
WAVE_POS = (
    "tenth country of after_tj wave "
    "(after DM→SL→GM→AG→CI→PR→ST→CV→SC LIVE; CF→YE→DJ; NOT wave end)"
)
DEST_CHAIN = "CF→YE→DJ"
SRC_CHAIN = "SC→CF→YE→DJ"
SRC_HOLD = "HOLD 0 STRICT after-CV (SC→CF→YE→DJ)"
SRC_WAVE = (
    "ninth country of after_tj wave "
    "(after DM→SL→GM→AG→CI→PR→ST→CV LIVE; SC→CF→YE→DJ; NOT wave end)"
)

FILES = [
    ("seychelles_soft_filter.py", "car_soft_filter.py"),
    (f"seychelles_corpus_stream_{SRC_TIP_SHORT}.py", f"car_corpus_stream_{DST_TIP_SHORT}.py"),
    (f"seychelles_encode_memsafe_{SRC_TIP_SHORT}.py", f"car_encode_memsafe_{DST_TIP_SHORT}.py"),
    (f"seychelles_finish_from_emb_{SRC_TIP_SHORT}.py", f"car_finish_from_emb_{DST_TIP_SHORT}.py"),
    (f"seychelles_stream_graph_parts_{SRC_TIP_SHORT}.py", f"car_stream_graph_parts_{DST_TIP_SHORT}.py"),
    (f"seychelles_package_memsafe_{SRC_TIP_SHORT}.py", f"car_package_memsafe_{DST_TIP_SHORT}.py"),
    ("seychelles_upload.py", "car_upload.py"),
    ("seychelles_bm25_smoke.py", "car_bm25_smoke.py"),
    ("seychelles_write_publish_report.py", "car_write_publish_report.py"),
    (f"seychelles_orchestrator_{SRC_TIP_SHORT}.py", f"car_orchestrator_{DST_TIP_SHORT}.py"),
]


def adapt(text: str, dst_name: str) -> str:
    # Repair path corruption from prior adapts
    text = text.replace("/home/box/cient-data/", "/home/box/agent-data/")
    text = text.replace("cient-data", "agent-data")
    text = text.replace("/home/box/prent-data/", "/home/box/agent-data/")
    text = text.replace("prent-data", "agent-data")
    text = text.replace("/home/box/stent-data/", "/home/box/agent-data/")
    text = text.replace("stent-data", "agent-data")
    text = text.replace("/home/box/cvent-data/", "/home/box/agent-data/")
    text = text.replace("cvent-data", "agent-data")
    text = text.replace("/home/box/scent-data/", "/home/box/agent-data/")
    text = text.replace("scent-data", "agent-data")

    # Protect BM25 / bm25
    text = text.replace("BM25", "\x00BM25\x00").replace("bm25", "\x00bm25\x00")
    text = text.replace("bmjacency", "adjacency")

    # Protect / rewrite HOLD + wave BEFORE ISO/slug swaps (SC appears in SRC_CHAIN)
    text = text.replace(SRC_HOLD, "\x00DESTHOLD\x00")
    text = text.replace(SRC_WAVE, "\x00DESTWAVE\x00")
    text = text.replace(SRC_CHAIN, "\x00DESTCHAIN\x00")
    text = text.replace(HOLD, "\x00DESTHOLD\x00")
    text = text.replace(DEST_CHAIN, "\x00DESTCHAIN\x00")
    text = text.replace(WAVE_POS, "\x00DESTWAVE\x00")
    text = text.replace("after-CV", "\x00AFTERSC\x00")
    text = text.replace("after CV ", "\x00AFTERSC_SP\x00")
    text = text.replace("after_tj", "\x00AFTERTJ_US\x00")
    text = text.replace("DM→SL→GM→AG→CI→PR→ST→CV LIVE", "\x00PRIORLIVE\x00")
    text = text.replace("ninth country of \x00AFTERTJ_US\x00 wave", "\x00DESTWAVE_SHORT\x00")
    text = text.replace("ninth country of after_tj wave", "\x00DESTWAVE_SHORT\x00")

    reps = [
        (SRC_TIP_FULL, DST_TIP_FULL),
        (SRC_TIP_SHORT, DST_TIP_SHORT),
        ("endomorphosis/ipfs_seychelles_laws", "endomorphosis/ipfs_car_laws"),
        ("justicedao/ipfs_seychelles_laws_ir", "justicedao/ipfs_car_laws_ir"),
        ("ipfs_seychelles_laws_ir", "ipfs_car_laws_ir"),
        ("ipfs_seychelles_laws", "ipfs_car_laws"),
        # HOLD / wave restore tokens mapped to dest
        ("\x00DESTHOLD\x00", HOLD),
        ("\x00DESTWAVE\x00", WAVE_POS),
        ("\x00DESTWAVE_SHORT\x00", WAVE_POS),
        ("\x00DESTCHAIN\x00", DEST_CHAIN),
        ("\x00AFTERSC\x00", "after-SC"),
        ("\x00AFTERSC_SP\x00", "after SC "),
        ("\x00PRIORLIVE\x00", "DM→SL→GM→AG→CI→PR→ST→CV→SC LIVE"),
        ("SC FIRST_IR (not wave end)", "CF FIRST_IR (not wave end)"),
        ("www/gov.sc", "www/gov/cf"),
        ("gov.sc", "gov/cf"),
        # Language English → French; country name swaps
        ("English (Seychelles)", "French (Central African Republic)"),
        ("English Seychelles", "French Central African Republic"),
        ("ASCII-fold English", "ASCII-fold French"),
        ("English legal stems", "French legal stems"),
        ("English legal corpus", "French legal corpus"),
        ("Seychelles", "Central African Republic"),
        # slug / path forms BEFORE bare seychelles
        ("seychelles_ranked", "car_ranked"),
        ("seychelles_gate", "car_gate"),
        ("seychelles_pass", "car_pass"),
        ("seychelles_encode_memsafe", "car_encode_memsafe"),
        ("seychelles_package_memsafe", "car_package_memsafe"),
        ("seychelles_corpus_stream", "car_corpus_stream"),
        ("seychelles_encode_done", "car_encode_done"),
        ("seychelles_filtered_", "car_filtered_"),
        ("seychelles_", "car_"),
        ("seychelles", "car"),
        # ISO whole-token / path forms only
        ('"SC"', '"CF"'),
        ("SC-attested", "CF-attested"),
        ("(SC)", "(CF)"),
        ('"sc"', '"cf"'),
        # floors 118/3623 → 93/3472
        ("118/3623", "93/3472"),
        ("118 / 3623", "93 / 3472"),
        ("118, 3623", "93, 3472"),
        ("FLOOR_LAWS, FLOOR_ARTS = 118, 3623", "FLOOR_LAWS, FLOOR_ARTS = 93, 3472"),
        ("or 118)", "or 93)"),
        ("or 118,", "or 93,"),
        ("or 118}", "or 93}"),
        ("= 118,", "= 93,"),
        ("= 118", "= 93"),
        ("@ 118/", "@ 93/"),
        (" 118/", " 93/"),
        ("floor 118/", "floor 93/"),
        ("(118/", "(93/"),
        (" or 118", " or 93"),
        (" 3623", " 3472"),
        ("3623", "3472"),
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

    text = text.replace("FLOOR_LAWS, FLOOR_ARTS = 118, 3472", "FLOOR_LAWS, FLOOR_ARTS = 93, 3472")
    text = text.replace("FLOOR_LAWS, FLOOR_ARTS = 93, 3623", "FLOOR_LAWS, FLOOR_ARTS = 93, 3472")
    text = text.replace('int(pack.get("n_articles") or 3623)', 'int(pack.get("n_articles") or 3472)')
    text = text.replace('int(pack.get("n_articles") or 3472)', 'int(pack.get("n_articles") or 3472)')
    text = text.replace('int(pack.get("n_laws") or 118)', 'int(pack.get("n_laws") or 93)')
    text = text.replace('int(pack.get("n_laws") or 93)', 'int(pack.get("n_laws") or 93)')

    # display name / slug fixes
    text = text.replace('"name": "car"', '"name": "Central African Republic"')
    text = text.replace('"name": "Central African Republic"', '"name": "Central African Republic"')
    text = text.replace('"slug": "Central African Republic"', '"slug": "car"')
    text = text.replace('SLUG = "Central African Republic"', 'SLUG = "car"')
    text = text.replace('SLUG = "car"', 'SLUG = "car"')
    text = text.replace('"country": "Central African Republic"', '"country": "car"')
    text = text.replace('"country": "car"', '"country": "car"')

    # Ensure agent-data survived any residual swaps (car from seychelles won't hit agent)
    text = text.replace("/home/box/prent-data/", "/home/box/agent-data/")
    text = text.replace("prent-data", "agent-data")
    text = text.replace("/home/box/cient-data/", "/home/box/agent-data/")
    text = text.replace("/home/box/stent-data/", "/home/box/agent-data/")
    text = text.replace("stent-data", "agent-data")
    text = text.replace("/home/box/cvent-data/", "/home/box/agent-data/")
    text = text.replace("cvent-data", "agent-data")
    text = text.replace("/home/box/scent-data/", "/home/box/agent-data/")
    text = text.replace("scent-data", "agent-data")
    # car-from-sc corruption edge
    text = text.replace("/home/box/carent-data/", "/home/box/agent-data/")
    text = text.replace("carent-data", "agent-data")

    if dst_name == "car_bm25_smoke.py":
        start = text.index("GATE = [")
        end = text.index("]", start) + 1
        years_line = ", ".join(f'"{y}"' for y in GATE_YEARS)
        stems_line = ", ".join(f'"{s}"' for s in GATE_STEMS)
        gate = f"GATE = [\n    {years_line},\n    {stems_line},\n]"
        text = text[:start] + gate + text[end:]
        text = re.sub(
            r'QUERIES = GATE \+ \[[^\]]*\]',
            'QUERIES = GATE + ["www", "gov", "cf", "officiel", "tribunal", "justice", "penal", "constitution"]',
            text,
        )
        note = (
            f"attested years {GATE_NOTE_YEARS} plus French legal stems {GATE_NOTE_STEMS} "
            f"from articles.parquet HEAD tip {DST_TIP_SHORT}; URL www/gov/cf is query-only, not GATE."
        )
        text = re.sub(
            r"GATE = attested years [^;]+; URL www/(?:gov\.sc|gov/cf) is query-only, not GATE\.",
            f"GATE = {note}",
            text,
        )
        text = re.sub(
            r"GATE = attested years [^\"\n]+",
            f"GATE = {note}",
            text,
            count=1,
        )
        text = text.replace('"seychelles_pass"', '"car_pass"')
        text = text.replace('"car_pass"', '"car_pass"')
        text = text.replace('"seychelles_gate"', '"car_gate"')
        text = text.replace('"car_gate"', '"car_gate"')
        text = text.replace(
            "attested Central African Republic years and English legal stems",
            "attested Central African Republic years and French legal stems",
        )
        text = text.replace(
            "attested Seychelles years and English legal stems",
            "attested Central African Republic years and French legal stems",
        )
        text = text.replace(
            "attested Central African Republic years and French legal stems",
            "attested Central African Republic years and French legal stems",
        )
        text = text.replace("— English legal corpus", "— French legal corpus")
        text = text.replace("— French legal corpus", "— French legal corpus")
        # docstring
        text = text.replace("English legal corpus", "French legal corpus")
        text = text.replace("English Central African", "French Central African")

    if dst_name == "car_write_publish_report.py":
        new_gate = f"{GATE_NOTE_YEARS} + stems {GATE_NOTE_STEMS}"
        text = re.sub(
            r"attested years [0-9/]+ \+ stems [a-z_/]+",
            f"attested years {new_gate}",
            text,
        )
        text = text.replace("English (Seychelles) GATE", "French (Central African Republic) GATE")
        text = text.replace("English (Central African Republic) GATE", "French (Central African Republic) GATE")
        text = text.replace(
            "ASCII-fold English (Central African Republic) GATE",
            "ASCII-fold French (Central African Republic) GATE",
        )
        text = text.replace(
            "ASCII-fold French (Central African Republic) GATE",
            "ASCII-fold French (Central African Republic) GATE",
        )
        text = re.sub(
            r"HOLD 0 STRICT after-CV[^;]*; collectors kept dead \(pkill\); soft never-thin ON; SKIP_US; Italy BLOCKED;[^\"\n]*",
            f"{HOLD}; collectors kept dead (pkill); soft never-thin ON; SKIP_US; Italy BLOCKED; {WAVE_POS}",
            text,
        )
        text = re.sub(
            r"HOLD 0 STRICT after-SC[^;]*; collectors kept dead \(pkill\); soft never-thin ON; SKIP_US; Italy BLOCKED;[^\"\n]*",
            f"{HOLD}; collectors kept dead (pkill); soft never-thin ON; SKIP_US; Italy BLOCKED; {WAVE_POS}",
            text,
        )
        text = text.replace("www/gov.sc is query-only", "www/gov/cf is query-only")
        text = text.replace("www/gov/cf is query-only", "www/gov/cf is query-only")
        text = text.replace("seychelles/", "car/")
        text = re.sub(
            r"BM25 PASS on Central African Republic ASCII-fold (?:English|French)(?: \(Central African Republic\))? GATE \([^)]+\); URL www/gov(?:\.sc|/cf) is query-only, not GATE",
            f"BM25 PASS on Central African Republic ASCII-fold French GATE (attested years {GATE_NOTE_YEARS} + stems {GATE_NOTE_STEMS}); URL www/gov/cf is query-only, not GATE",
            text,
        )
        text = re.sub(
            r"BM25 PASS on Seychelles ASCII-fold English GATE \([^)]+\); URL www/gov\.sc is query-only, not GATE",
            f"BM25 PASS on Central African Republic ASCII-fold French GATE (attested years {GATE_NOTE_YEARS} + stems {GATE_NOTE_STEMS}); URL www/gov/cf is query-only, not GATE",
            text,
        )

    leftovers = (
        "Seychelles", "seychelles",
        "Cabo Verde", "caboverde", "Cabo",
        "São Tomé", "Sao Tome", "saotome", "Príncipe", "Principe",
        "Puerto Rico", "puerto_rico",
        "Côte d'Ivoire", "Cote d'Ivoire", "cotedivoire",
        "Antigua and Barbuda", "antigua_barbuda",
        "Gambia", "gambia",
        "Sierra Leone", "sierraleone",
        "Dominica", "dominica",
        "cient-data", "prent-data", "stent-data", "cvent-data", "scent-data", "carent-data",
        "gov.sc",
        # English GATE stems that must not remain (whole-word checked below for some)
        "shall",
    )
    found = []
    for x in leftovers:
        if x == "Cabo":
            if re.search(r'(?<![A-Za-z])Cabo(?![A-Za-z])', text):
                found.append(x)
            continue
        if x == "shall":
            if re.search(r'(?<![A-Za-z])shall(?![A-Za-z])', text):
                found.append(x)
            continue
        if x in text:
            found.append(x)
    if found:
        raise RuntimeError(f"language/country leftovers in {dst_name}: {found}")
    if re.search(r'\bEnglish\b', text):
        raise RuntimeError(f"leftover English token in {dst_name}")
    if re.search(r'\bPortuguese\b', text):
        raise RuntimeError(f"leftover Portuguese token in {dst_name}")
    if re.search(r'\bSpanish\b', text):
        raise RuntimeError(f"leftover Spanish token in {dst_name}")
    # Reject leftover English GATE stems as quoted tokens in GATE/QUERIES context
    for stem in ('"act"', '"law"', '"person"', '"republic"', '"government"', '"minister"', '"seychelles"'):
        if stem in text and dst_name.endswith("_bm25_smoke.py"):
            # minister may appear as ministre only; government→gone; allow if French replacements done
            if stem in ('"act"', '"law"', '"person"', '"republic"', '"government"', '"seychelles"'):
                raise RuntimeError(f"leftover English GATE stem {stem} in {dst_name}")
            if stem == '"minister"' and '"ministre"' not in text:
                raise RuntimeError(f"leftover English GATE stem {stem} in {dst_name}")
    if dst_name.endswith("_bm25_smoke.py") and '", "sc"' in text:
        raise RuntimeError(f"leftover sc query token in {dst_name}")
    if dst_name.endswith("_bm25_smoke.py") and "gov.sc" in text:
        raise RuntimeError(f"leftover gov.sc in {dst_name}")
    # reject cf_* script naming in comments? allow ISO CF
    if "centralafrican" in text.lower() or "cf_" in text.replace("CF→", "").replace('"CF"', "").replace("(CF)", "").replace("after-SC", ""):
        # allow CF ISO; reject cf_ script prefix
        if re.search(r'\bcf_[a-z]', text) or "centralafrican" in text.lower():
            raise RuntimeError(f"forbidden cf_/centralafrican naming in {dst_name}")
    scrub = text
    scrub = scrub.replace(DEST_CHAIN, "XX")
    scrub = scrub.replace(HOLD, "XX")
    scrub = scrub.replace(WAVE_POS, "XX")
    scrub = scrub.replace("after-SC", "after-XX")
    scrub = scrub.replace("after SC ", "after XX ")
    scrub = scrub.replace("after_tj", "after_xx")
    scrub = scrub.replace("DM→SL→GM→AG→CI→PR→ST→CV→SC LIVE", "XX→XX→XX→XX→XX→XX→XX→XX→XX LIVE")
    scrub = scrub.replace("after DM→SL→GM→AG→CI→PR→ST→CV→SC LIVE", "after XX→XX→XX→XX→XX→XX→XX→XX→XX LIVE")
    if '"SC"' in scrub or "(SC)" in scrub or "SC→" in scrub or "SC-attested" in scrub:
        tmp = scrub
        if re.search(r'(?<![A-Za-z])SC(?![A-Za-z])', tmp):
            raise RuntimeError(f"leftover SC tokens in {dst_name}: ...{tmp[max(0,tmp.find('SC')-20):tmp.find('SC')+20]}...")
    if "Seychelles" in text or "seychelles" in text:
        raise RuntimeError(f"leftover Seychelles in {dst_name}")
    if "ipfs_seychelles" in text:
        raise RuntimeError(f"leftover seychelles path in {dst_name}")
    if "agent-data" not in text and "SECRET" in text.upper():
        if any(x in dst_name for x in ("soft_filter", "upload", "orchestrator")):
            if "/home/box/" in text and "agent-data" not in text:
                raise RuntimeError(f"missing agent-data secret path in {dst_name}")
    # data/ paths must survive
    if "soft_filter" in dst_name or "corpus_stream" in dst_name:
        if "data/laws.parquet" not in text and 'data" / "laws.parquet"' not in text and "data/laws" not in text:
            if '"data"' not in text and "/data/" not in text:
                pass
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
    if entry.get("slug") == "car" or entry.get("iso2") == "CF":
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
            "iso2": "CF",
            "slug": "car",
            "repo": "endomorphosis/ipfs_car_laws",
            "years_attested": [int(y) for y in GATE_YEARS],
            "gate_years": [int(y) for y in GATE_YEARS],
            "gate_stems": GATE_STEMS,
            "note": (
                f"CF FIRST_IR scaffold; tip MATCH {DST_TIP_SHORT}@93/3472; {HOLD}; "
                f"soft never-thin ON; SKIP_US; Italy BLOCKED; {WAVE_POS}"
            ),
            "status": "CLAIMED",
            "mode": "FIRST_IR",
        })
        break
else:
    raise RuntimeError("CAR/CF entry missing from wave JSON")
wave.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print("updated wave JSON CAR entry")
print("GATE years", GATE_YEARS)
print("GATE stems", GATE_STEMS)
print("n_gate", len(GATE_YEARS) + len(GATE_STEMS))
print("GATE language: French")
print("HOLD", HOLD)
