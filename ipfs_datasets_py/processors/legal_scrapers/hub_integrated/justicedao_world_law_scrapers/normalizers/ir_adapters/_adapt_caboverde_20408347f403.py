#!/usr/bin/env python3
"""Adapt the São Tomé Portuguese memsafe FIRST_IR pack to Cabo Verde CV.

Portuguese Cabo Verde; FIRST_IR; HOLD 0 STRICT after-ST (CV→SC→CF→YE→DJ).
Soft never-thin ON; SKIP_US; Italy BLOCKED. WAVE after_tj eighth country (after
DM→SL→GM→AG→CI→PR→ST LIVE), NOT wave end. GATE: attested years + Portuguese legal
stems from data/articles.parquet tip 20408347f403 (Portuguese; include cabo/verde).
URL www/gov.cv query-only, NOT GATE.
Source tip d7dc8feb75b0 (São Tomé Portuguese).
Also repair cient-data / prent-data / stent-data → agent-data path corruption.
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
SRC_TIP_FULL = "d7dc8feb75b017e559dc7d770d04b904ea3f13df"
SRC_TIP_SHORT = "d7dc8feb75b0"
DST_TIP_FULL = "20408347f403ffa06cb1fe31789d6ef8b564a62d"
DST_TIP_SHORT = "20408347f403"
FLOOR_LAWS, FLOOR_ARTS = 110, 3625
SRC_FLOOR_L, SRC_FLOOR_A = 116, 3658

# Sampled from data/articles.parquet @ 20408347f403 (~10 years + ~11 Portuguese stems)
# Whole-word ASCII-fold FTS hits; avoid substring-only stems.
GATE_YEARS = ["2025", "2023", "2015", "2017", "2014", "2024", "2020", "2016", "2013", "2018"]
GATE_STEMS = [
    "artigo", "lei", "decreto", "codigo", "seccao", "republica",
    "cabo", "verde", "estado", "pessoa", "governo",
]
GATE_NOTE_YEARS = "/".join(GATE_YEARS)
GATE_NOTE_STEMS = "/".join(GATE_STEMS)
HOLD = "HOLD 0 STRICT after-ST (CV→SC→CF→YE→DJ)"
WAVE_POS = (
    "eighth country of after_tj wave "
    "(after DM→SL→GM→AG→CI→PR→ST LIVE; CV→SC→CF→YE→DJ; NOT wave end)"
)
DEST_CHAIN = "CV→SC→CF→YE→DJ"
SRC_CHAIN = "ST→CV→SC→CF→YE→DJ"
SRC_HOLD = "HOLD 0 STRICT after-PR (ST→CV→SC→CF→YE→DJ)"
SRC_WAVE = (
    "seventh country of after_tj wave "
    "(after DM→SL→GM→AG→CI→PR LIVE; ST→CV→SC→CF→YE→DJ; NOT wave end)"
)

FILES = [
    ("saotome_soft_filter.py", "caboverde_soft_filter.py"),
    (f"saotome_corpus_stream_{SRC_TIP_SHORT}.py", f"caboverde_corpus_stream_{DST_TIP_SHORT}.py"),
    (f"saotome_encode_memsafe_{SRC_TIP_SHORT}.py", f"caboverde_encode_memsafe_{DST_TIP_SHORT}.py"),
    (f"saotome_finish_from_emb_{SRC_TIP_SHORT}.py", f"caboverde_finish_from_emb_{DST_TIP_SHORT}.py"),
    (f"saotome_stream_graph_parts_{SRC_TIP_SHORT}.py", f"caboverde_stream_graph_parts_{DST_TIP_SHORT}.py"),
    (f"saotome_package_memsafe_{SRC_TIP_SHORT}.py", f"caboverde_package_memsafe_{DST_TIP_SHORT}.py"),
    ("saotome_upload.py", "caboverde_upload.py"),
    ("saotome_bm25_smoke.py", "caboverde_bm25_smoke.py"),
    ("saotome_write_publish_report.py", "caboverde_write_publish_report.py"),
    (f"saotome_orchestrator_{SRC_TIP_SHORT}.py", f"caboverde_orchestrator_{DST_TIP_SHORT}.py"),
]


def adapt(text: str, dst_name: str) -> str:
    # Repair path corruption from prior adapts
    text = text.replace("/home/box/cient-data/", "/home/box/agent-data/")
    text = text.replace("cient-data", "agent-data")
    text = text.replace("/home/box/prent-data/", "/home/box/agent-data/")
    text = text.replace("prent-data", "agent-data")
    text = text.replace("/home/box/stent-data/", "/home/box/agent-data/")
    text = text.replace("stent-data", "agent-data")

    # Protect BM25 / bm25
    text = text.replace("BM25", "\x00BM25\x00").replace("bm25", "\x00bm25\x00")
    text = text.replace("bmjacency", "adjacency")

    # Protect / rewrite HOLD + wave BEFORE ISO/slug swaps (ST appears in SRC_CHAIN)
    text = text.replace(SRC_HOLD, "\x00DESTHOLD\x00")
    text = text.replace(SRC_WAVE, "\x00DESTWAVE\x00")
    text = text.replace(SRC_CHAIN, "\x00DESTCHAIN\x00")
    text = text.replace(HOLD, "\x00DESTHOLD\x00")
    text = text.replace(DEST_CHAIN, "\x00DESTCHAIN\x00")
    text = text.replace(WAVE_POS, "\x00DESTWAVE\x00")
    text = text.replace("after-PR", "\x00AFTERST\x00")
    text = text.replace("after PR ", "\x00AFTERST_SP\x00")
    text = text.replace("after_tj", "\x00AFTERTJ_US\x00")
    text = text.replace("DM→SL→GM→AG→CI→PR LIVE", "\x00PRIORLIVE\x00")
    text = text.replace("seventh country of \x00AFTERTJ_US\x00 wave", "\x00DESTWAVE_SHORT\x00")
    text = text.replace("seventh country of after_tj wave", "\x00DESTWAVE_SHORT\x00")

    reps = [
        (SRC_TIP_FULL, DST_TIP_FULL),
        (SRC_TIP_SHORT, DST_TIP_SHORT),
        ("endomorphosis/ipfs_saotome_laws", "endomorphosis/ipfs_caboverde_laws"),
        ("justicedao/ipfs_saotome_laws_ir", "justicedao/ipfs_caboverde_laws_ir"),
        ("ipfs_saotome_laws_ir", "ipfs_caboverde_laws_ir"),
        ("ipfs_saotome_laws", "ipfs_caboverde_laws"),
        # HOLD / wave restore tokens mapped to dest
        ("\x00DESTHOLD\x00", HOLD),
        ("\x00DESTWAVE\x00", WAVE_POS),
        ("\x00DESTWAVE_SHORT\x00", WAVE_POS),
        ("\x00DESTCHAIN\x00", DEST_CHAIN),
        ("\x00AFTERST\x00", "after-ST"),
        ("\x00AFTERST_SP\x00", "after ST "),
        ("\x00PRIORLIVE\x00", "DM→SL→GM→AG→CI→PR→ST LIVE"),
        ("ST FIRST_IR (not wave end)", "CV FIRST_IR (not wave end)"),
        ("www/gov.st", "www/gov.cv"),
        ("gov.st", "gov.cv"),
        # Language stays Portuguese; country name swaps
        ("Portuguese (São Tomé and Príncipe)", "Portuguese (Cabo Verde)"),
        ("Portuguese São Tomé and Príncipe", "Portuguese Cabo Verde"),
        ("ASCII-fold Portuguese", "ASCII-fold Portuguese"),
        ("Portuguese legal stems", "Portuguese legal stems"),
        ("Portuguese legal corpus", "Portuguese legal corpus"),
        ("São Tomé and Príncipe", "Cabo Verde"),
        ("São Tomé", "Cabo Verde"),
        ("Sao Tome and Principe", "Cabo Verde"),
        ("Sao Tome", "Cabo Verde"),
        # slug / path forms
        ("saotome_ranked", "caboverde_ranked"),
        ("saotome_gate", "caboverde_gate"),
        ("saotome_pass", "caboverde_pass"),
        ("saotome_encode_memsafe", "caboverde_encode_memsafe"),
        ("saotome_package_memsafe", "caboverde_package_memsafe"),
        ("saotome_corpus_stream", "caboverde_corpus_stream"),
        ("saotome_encode_done", "caboverde_encode_done"),
        ("saotome_filtered_", "caboverde_filtered_"),
        ("saotome_", "caboverde_"),
        ("saotome", "caboverde"),
        # ISO whole-token / path forms only
        ('"ST"', '"CV"'),
        ("ST-attested", "CV-attested"),
        ("(ST)", "(CV)"),
        ('"st"', '"cv"'),
        # floors 116/3658 → 110/3625
        ("116/3658", "110/3625"),
        ("116 / 3658", "110 / 3625"),
        ("116, 3658", "110, 3625"),
        ("FLOOR_LAWS, FLOOR_ARTS = 116, 3658", "FLOOR_LAWS, FLOOR_ARTS = 110, 3625"),
        ("or 116)", "or 110)"),
        ("or 116,", "or 110,"),
        ("or 116}", "or 110}"),
        ("= 116,", "= 110,"),
        ("= 116", "= 110"),
        ("@ 116/", "@ 110/"),
        (" 116/", " 110/"),
        ("floor 116/", "floor 110/"),
        ("(116/", "(110/"),
        (" or 116", " or 110"),
        (" 3658", " 3625"),
        ("3658", "3625"),
    ]
    for a, b in reps:
        text = text.replace(a, b)

    text = text.replace("\x00BM25\x00", "BM25").replace("\x00bm25\x00", "bm25")
    text = text.replace("\x00AFTERTJ_US\x00", "after_tj")
    text = text.replace("\x00DESTHOLD\x00", HOLD)
    text = text.replace("\x00DESTCHAIN\x00", DEST_CHAIN)
    text = text.replace("\x00DESTWAVE\x00", WAVE_POS)

    text = text.replace("FLOOR_LAWS, FLOOR_ARTS = 116, 3625", "FLOOR_LAWS, FLOOR_ARTS = 110, 3625")
    text = text.replace("FLOOR_LAWS, FLOOR_ARTS = 110, 3658", "FLOOR_LAWS, FLOOR_ARTS = 110, 3625")
    text = text.replace('int(pack.get("n_articles") or 3658)', 'int(pack.get("n_articles") or 3625)')
    text = text.replace('int(pack.get("n_articles") or 3625)', 'int(pack.get("n_articles") or 3625)')
    text = text.replace('int(pack.get("n_laws") or 116)', 'int(pack.get("n_laws") or 110)')
    text = text.replace('int(pack.get("n_laws") or 110)', 'int(pack.get("n_laws") or 110)')

    # display name / slug fixes
    text = text.replace('"name": "caboverde"', '"name": "Cabo Verde"')
    text = text.replace('"name": "Cabo Verde"', '"name": "Cabo Verde"')
    text = text.replace('"slug": "Cabo Verde"', '"slug": "caboverde"')
    text = text.replace('SLUG = "Cabo Verde"', 'SLUG = "caboverde"')
    text = text.replace('SLUG = "caboverde"', 'SLUG = "caboverde"')

    # Ensure agent-data survived any residual swaps
    text = text.replace("/home/box/prent-data/", "/home/box/agent-data/")
    text = text.replace("prent-data", "agent-data")
    text = text.replace("/home/box/cient-data/", "/home/box/agent-data/")
    text = text.replace("/home/box/stent-data/", "/home/box/agent-data/")
    text = text.replace("stent-data", "agent-data")
    text = text.replace("/home/box/cvent-data/", "/home/box/agent-data/")
    text = text.replace("cvent-data", "agent-data")

    if dst_name == "caboverde_bm25_smoke.py":
        start = text.index("GATE = [")
        end = text.index("]", start) + 1
        years_line = ", ".join(f'"{y}"' for y in GATE_YEARS)
        stems_line = ", ".join(f'"{s}"' for s in GATE_STEMS)
        gate = f"GATE = [\n    {years_line},\n    {stems_line},\n]"
        text = text[:start] + gate + text[end:]
        text = re.sub(
            r'QUERIES = GATE \+ \[[^\]]*\]',
            'QUERIES = GATE + ["www", "gov.cv", "governo", "tribunal", "justica", "penal", "assembleia", "constituicao"]',
            text,
        )
        note = (
            f"attested years {GATE_NOTE_YEARS} plus Portuguese legal stems {GATE_NOTE_STEMS} "
            f"from articles.parquet HEAD tip {DST_TIP_SHORT}; URL www/gov.cv is query-only, not GATE."
        )
        text = re.sub(
            r"GATE = attested years [^;]+; URL www/(?:gov\.st|gov\.cv) is query-only, not GATE\.",
            f"GATE = {note}",
            text,
        )
        text = re.sub(
            r"GATE = attested years [^\"\n]+",
            f"GATE = {note}",
            text,
            count=1,
        )
        text = text.replace('"saotome_pass"', '"caboverde_pass"')
        text = text.replace('"caboverde_pass"', '"caboverde_pass"')
        text = text.replace('"saotome_gate"', '"caboverde_gate"')
        text = text.replace('"caboverde_gate"', '"caboverde_gate"')
        text = text.replace(
            "attested Cabo Verde years and Portuguese legal stems",
            "attested Cabo Verde years and Portuguese legal stems",
        )
        text = text.replace(
            "attested São Tomé and Príncipe years and Portuguese legal stems",
            "attested Cabo Verde years and Portuguese legal stems",
        )
        text = text.replace("— Portuguese legal corpus", "— Portuguese legal corpus")
        text = text.replace("tome", "cabo")  # leftover stem in notes if any — careful
        # undo accidental cabo in tip or other places — tip has no tome
        text = text.replace("principe", "verde")

    if dst_name == "caboverde_write_publish_report.py":
        new_gate = f"{GATE_NOTE_YEARS} + stems {GATE_NOTE_STEMS}"
        text = re.sub(
            r"attested years [0-9/]+ \+ stems [a-z_/]+",
            f"attested years {new_gate}",
            text,
        )
        text = text.replace("Portuguese (São Tomé and Príncipe) GATE", "Portuguese (Cabo Verde) GATE")
        text = text.replace(
            "ASCII-fold Portuguese (Cabo Verde) GATE",
            "ASCII-fold Portuguese (Cabo Verde) GATE",
        )
        text = re.sub(
            r"HOLD 0 STRICT after-PR[^;]*; collectors kept dead \(pkill\); soft never-thin ON; SKIP_US; Italy BLOCKED;[^\"\n]*",
            f"{HOLD}; collectors kept dead (pkill); soft never-thin ON; SKIP_US; Italy BLOCKED; {WAVE_POS}",
            text,
        )
        text = re.sub(
            r"HOLD 0 STRICT after-ST[^;]*; collectors kept dead \(pkill\); soft never-thin ON; SKIP_US; Italy BLOCKED;[^\"\n]*",
            f"{HOLD}; collectors kept dead (pkill); soft never-thin ON; SKIP_US; Italy BLOCKED; {WAVE_POS}",
            text,
        )
        text = text.replace("www/gov.st is query-only", "www/gov.cv is query-only")
        text = text.replace("saotome/", "caboverde/")
        text = re.sub(
            r"BM25 PASS on Cabo Verde ASCII-fold Portuguese GATE \([^)]+\); URL www/gov\.cv is query-only, not GATE",
            f"BM25 PASS on Cabo Verde ASCII-fold Portuguese GATE (attested years {GATE_NOTE_YEARS} + stems {GATE_NOTE_STEMS}); URL www/gov.cv is query-only, not GATE",
            text,
        )

    leftovers = (
        "São Tomé", "Sao Tome", "saotome", "Príncipe", "Principe", "principe",
        "tome",  # careful: may appear in "atome" etc — check
        "Puerto Rico", "puerto_rico", "Puerto",
        "Côte d'Ivoire", "Cote d'Ivoire", "cotedivoire",
        "Antigua and Barbuda", "antigua_barbuda",
        "Gambia", "gambia",
        "Sierra Leone", "sierraleone",
        "Dominica", "dominica",
        "cient-data", "prent-data", "stent-data", "cvent-data",
        "gov.st",
        "articulo", "seccion", "asociado", "constitucion", "persona",
    )
    # 'tome' alone is risky — check word-boundary leftover of São Tomé stem
    found = []
    for x in leftovers:
        if x == "tome":
            if re.search(r'(?<![A-Za-z])tome(?![A-Za-z])', text, re.I):
                found.append(x)
            continue
        if x in text:
            found.append(x)
    if found:
        raise RuntimeError(f"language/country leftovers in {dst_name}: {found}")
    if re.search(r'\bSpanish\b', text):
        raise RuntimeError(f"leftover Spanish token in {dst_name}")
    if re.search(r'\bEnglish\b', text):
        raise RuntimeError(f"leftover English token in {dst_name}")
    if re.search(r'\bFrench\b', text):
        raise RuntimeError(f"leftover French token in {dst_name}")
    if dst_name.endswith("_bm25_smoke.py") and '", "st"' in text:
        raise RuntimeError(f"leftover st query token in {dst_name}")
    if dst_name.endswith("_bm25_smoke.py") and "gov.st" in text:
        raise RuntimeError(f"leftover gov.st in {dst_name}")
    scrub = text
    scrub = scrub.replace(DEST_CHAIN, "XX")
    scrub = scrub.replace(HOLD, "XX")
    scrub = scrub.replace(WAVE_POS, "XX")
    scrub = scrub.replace("after-ST", "after-XX")
    scrub = scrub.replace("after ST ", "after XX ")
    scrub = scrub.replace("after_tj", "after_xx")
    scrub = scrub.replace("DM→SL→GM→AG→CI→PR→ST LIVE", "XX→XX→XX→XX→XX→XX→XX LIVE")
    scrub = scrub.replace("after DM→SL→GM→AG→CI→PR→ST LIVE", "after XX→XX→XX→XX→XX→XX→XX LIVE")
    if '"ST"' in scrub or "(ST)" in scrub or "ST→" in scrub or "ST-attested" in scrub:
        tmp = scrub
        if re.search(r'(?<![A-Za-z])ST(?![A-Za-z])', tmp):
            raise RuntimeError(f"leftover ST tokens in {dst_name}: ...{tmp[max(0,tmp.find('ST')-20):tmp.find('ST')+20]}...")
    if "São" in text or "saotome" in text or "Príncipe" in text:
        raise RuntimeError(f"leftover São Tomé in {dst_name}")
    if "ipfs_saotome" in text:
        raise RuntimeError(f"leftover saotome path in {dst_name}")
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
    if entry.get("slug") == "caboverde" or entry.get("iso2") == "CV":
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
            "iso2": "CV",
            "repo": "endomorphosis/ipfs_caboverde_laws",
            "years_attested": [int(y) for y in GATE_YEARS],
            "gate_years": [int(y) for y in GATE_YEARS],
            "gate_stems": GATE_STEMS,
            "note": (
                f"CV FIRST_IR scaffold; tip MATCH {DST_TIP_SHORT}@110/3625; {HOLD}; "
                f"soft never-thin ON; SKIP_US; Italy BLOCKED; {WAVE_POS}"
            ),
            "status": "CLAIMED",
            "mode": "FIRST_IR",
        })
        break
else:
    raise RuntimeError("Cabo Verde entry missing from wave JSON")
wave.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print("updated wave JSON Cabo Verde entry")
print("GATE years", GATE_YEARS)
print("GATE stems", GATE_STEMS)
print("n_gate", len(GATE_YEARS) + len(GATE_STEMS))
print("GATE language: Portuguese")
print("HOLD", HOLD)
