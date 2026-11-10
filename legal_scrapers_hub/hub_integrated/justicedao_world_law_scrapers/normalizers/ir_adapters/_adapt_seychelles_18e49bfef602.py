#!/usr/bin/env python3
"""Adapt the Cabo Verde Portuguese memsafe FIRST_IR pack to Seychelles SC.

English Seychelles; FIRST_IR; HOLD 0 STRICT after-CV (SC→CF→YE→DJ).
Soft never-thin ON; SKIP_US; Italy BLOCKED. WAVE after_tj ninth country (after
DM→SL→GM→AG→CI→PR→ST→CV LIVE), NOT wave end. GATE: attested years + English legal
stems from data/articles.parquet tip 18e49bfef602 (English; include seychelles).
URL www/gov.sc query-only, NOT GATE.
Source tip 20408347f403 (Cabo Verde Portuguese).
Also repair cient-data / prent-data / stent-data / cvent-data → agent-data path corruption.
Language override: Portuguese → English (Seychelles).
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
SRC_TIP_FULL = "20408347f403ffa06cb1fe31789d6ef8b564a62d"
SRC_TIP_SHORT = "20408347f403"
DST_TIP_FULL = "18e49bfef60298c5af0c230df686cd188a653652"
DST_TIP_SHORT = "18e49bfef602"
FLOOR_LAWS, FLOOR_ARTS = 118, 3623
SRC_FLOOR_L, SRC_FLOOR_A = 110, 3625

# Sampled from data/articles.parquet @ 18e49bfef602 (~10 years + ~11 English stems)
# Whole-word ASCII-fold FTS hits; ordinance absent (0 docs) — excluded.
GATE_YEARS = ["2021", "2020", "2024", "2014", "2022", "2025", "2011", "1996", "2016", "2010"]
GATE_STEMS = [
    "article", "section", "act", "law", "person", "republic",
    "code", "seychelles", "minister", "government", "shall",
]
GATE_NOTE_YEARS = "/".join(GATE_YEARS)
GATE_NOTE_STEMS = "/".join(GATE_STEMS)
HOLD = "HOLD 0 STRICT after-CV (SC→CF→YE→DJ)"
WAVE_POS = (
    "ninth country of after_tj wave "
    "(after DM→SL→GM→AG→CI→PR→ST→CV LIVE; SC→CF→YE→DJ; NOT wave end)"
)
DEST_CHAIN = "SC→CF→YE→DJ"
SRC_CHAIN = "CV→SC→CF→YE→DJ"
SRC_HOLD = "HOLD 0 STRICT after-ST (CV→SC→CF→YE→DJ)"
SRC_WAVE = (
    "eighth country of after_tj wave "
    "(after DM→SL→GM→AG→CI→PR→ST LIVE; CV→SC→CF→YE→DJ; NOT wave end)"
)

FILES = [
    ("caboverde_soft_filter.py", "seychelles_soft_filter.py"),
    (f"caboverde_corpus_stream_{SRC_TIP_SHORT}.py", f"seychelles_corpus_stream_{DST_TIP_SHORT}.py"),
    (f"caboverde_encode_memsafe_{SRC_TIP_SHORT}.py", f"seychelles_encode_memsafe_{DST_TIP_SHORT}.py"),
    (f"caboverde_finish_from_emb_{SRC_TIP_SHORT}.py", f"seychelles_finish_from_emb_{DST_TIP_SHORT}.py"),
    (f"caboverde_stream_graph_parts_{SRC_TIP_SHORT}.py", f"seychelles_stream_graph_parts_{DST_TIP_SHORT}.py"),
    (f"caboverde_package_memsafe_{SRC_TIP_SHORT}.py", f"seychelles_package_memsafe_{DST_TIP_SHORT}.py"),
    ("caboverde_upload.py", "seychelles_upload.py"),
    ("caboverde_bm25_smoke.py", "seychelles_bm25_smoke.py"),
    ("caboverde_write_publish_report.py", "seychelles_write_publish_report.py"),
    (f"caboverde_orchestrator_{SRC_TIP_SHORT}.py", f"seychelles_orchestrator_{DST_TIP_SHORT}.py"),
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
    text = text.replace("after-ST", "\x00AFTERCV\x00")
    text = text.replace("after ST ", "\x00AFTERCV_SP\x00")
    text = text.replace("after_tj", "\x00AFTERTJ_US\x00")
    text = text.replace("DM→SL→GM→AG→CI→PR→ST LIVE", "\x00PRIORLIVE\x00")
    text = text.replace("eighth country of \x00AFTERTJ_US\x00 wave", "\x00DESTWAVE_SHORT\x00")
    text = text.replace("eighth country of after_tj wave", "\x00DESTWAVE_SHORT\x00")

    reps = [
        (SRC_TIP_FULL, DST_TIP_FULL),
        (SRC_TIP_SHORT, DST_TIP_SHORT),
        ("endomorphosis/ipfs_caboverde_laws", "endomorphosis/ipfs_seychelles_laws"),
        ("justicedao/ipfs_caboverde_laws_ir", "justicedao/ipfs_seychelles_laws_ir"),
        ("ipfs_caboverde_laws_ir", "ipfs_seychelles_laws_ir"),
        ("ipfs_caboverde_laws", "ipfs_seychelles_laws"),
        # HOLD / wave restore tokens mapped to dest
        ("\x00DESTHOLD\x00", HOLD),
        ("\x00DESTWAVE\x00", WAVE_POS),
        ("\x00DESTWAVE_SHORT\x00", WAVE_POS),
        ("\x00DESTCHAIN\x00", DEST_CHAIN),
        ("\x00AFTERCV\x00", "after-CV"),
        ("\x00AFTERCV_SP\x00", "after CV "),
        ("\x00PRIORLIVE\x00", "DM→SL→GM→AG→CI→PR→ST→CV LIVE"),
        ("CV FIRST_IR (not wave end)", "SC FIRST_IR (not wave end)"),
        ("www/gov.cv", "www/gov.sc"),
        ("gov.cv", "gov.sc"),
        # Language Portuguese → English; country name swaps
        ("Portuguese (Cabo Verde)", "English (Seychelles)"),
        ("Portuguese Cabo Verde", "English Seychelles"),
        ("ASCII-fold Portuguese", "ASCII-fold English"),
        ("Portuguese legal stems", "English legal stems"),
        ("Portuguese legal corpus", "English legal corpus"),
        ("Cabo Verde", "Seychelles"),
        # slug / path forms
        ("caboverde_ranked", "seychelles_ranked"),
        ("caboverde_gate", "seychelles_gate"),
        ("caboverde_pass", "seychelles_pass"),
        ("caboverde_encode_memsafe", "seychelles_encode_memsafe"),
        ("caboverde_package_memsafe", "seychelles_package_memsafe"),
        ("caboverde_corpus_stream", "seychelles_corpus_stream"),
        ("caboverde_encode_done", "seychelles_encode_done"),
        ("caboverde_filtered_", "seychelles_filtered_"),
        ("caboverde_", "seychelles_"),
        ("caboverde", "seychelles"),
        # ISO whole-token / path forms only
        ('"CV"', '"SC"'),
        ("CV-attested", "SC-attested"),
        ("(CV)", "(SC)"),
        ('"cv"', '"sc"'),
        # floors 110/3625 → 118/3623
        ("110/3625", "118/3623"),
        ("110 / 3625", "118 / 3623"),
        ("110, 3625", "118, 3623"),
        ("FLOOR_LAWS, FLOOR_ARTS = 110, 3625", "FLOOR_LAWS, FLOOR_ARTS = 118, 3623"),
        ("or 110)", "or 118)"),
        ("or 110,", "or 118,"),
        ("or 110}", "or 118}"),
        ("= 110,", "= 118,"),
        ("= 110", "= 118"),
        ("@ 110/", "@ 118/"),
        (" 110/", " 118/"),
        ("floor 110/", "floor 118/"),
        ("(110/", "(118/"),
        (" or 110", " or 118"),
        (" 3625", " 3623"),
        ("3625", "3623"),
    ]
    for a, b in reps:
        text = text.replace(a, b)

    text = text.replace("\x00BM25\x00", "BM25").replace("\x00bm25\x00", "bm25")
    text = text.replace("\x00AFTERTJ_US\x00", "after_tj")
    text = text.replace("\x00DESTHOLD\x00", HOLD)
    text = text.replace("\x00DESTCHAIN\x00", DEST_CHAIN)
    text = text.replace("\x00DESTWAVE\x00", WAVE_POS)

    text = text.replace("FLOOR_LAWS, FLOOR_ARTS = 110, 3623", "FLOOR_LAWS, FLOOR_ARTS = 118, 3623")
    text = text.replace("FLOOR_LAWS, FLOOR_ARTS = 118, 3625", "FLOOR_LAWS, FLOOR_ARTS = 118, 3623")
    text = text.replace('int(pack.get("n_articles") or 3625)', 'int(pack.get("n_articles") or 3623)')
    text = text.replace('int(pack.get("n_articles") or 3623)', 'int(pack.get("n_articles") or 3623)')
    text = text.replace('int(pack.get("n_laws") or 110)', 'int(pack.get("n_laws") or 118)')
    text = text.replace('int(pack.get("n_laws") or 118)', 'int(pack.get("n_laws") or 118)')

    # display name / slug fixes
    text = text.replace('"name": "seychelles"', '"name": "Seychelles"')
    text = text.replace('"name": "Seychelles"', '"name": "Seychelles"')
    text = text.replace('"slug": "Seychelles"', '"slug": "seychelles"')
    text = text.replace('SLUG = "Seychelles"', 'SLUG = "seychelles"')
    text = text.replace('SLUG = "seychelles"', 'SLUG = "seychelles"')

    # Ensure agent-data survived any residual swaps
    text = text.replace("/home/box/prent-data/", "/home/box/agent-data/")
    text = text.replace("prent-data", "agent-data")
    text = text.replace("/home/box/cient-data/", "/home/box/agent-data/")
    text = text.replace("/home/box/stent-data/", "/home/box/agent-data/")
    text = text.replace("stent-data", "agent-data")
    text = text.replace("/home/box/cvent-data/", "/home/box/agent-data/")
    text = text.replace("cvent-data", "agent-data")
    text = text.replace("/home/box/scent-data/", "/home/box/agent-data/")
    text = text.replace("scent-data", "agent-data")

    if dst_name == "seychelles_bm25_smoke.py":
        start = text.index("GATE = [")
        end = text.index("]", start) + 1
        years_line = ", ".join(f'"{y}"' for y in GATE_YEARS)
        stems_line = ", ".join(f'"{s}"' for s in GATE_STEMS)
        gate = f"GATE = [\n    {years_line},\n    {stems_line},\n]"
        text = text[:start] + gate + text[end:]
        text = re.sub(
            r'QUERIES = GATE \+ \[[^\]]*\]',
            'QUERIES = GATE + ["www", "gov.sc", "court", "order", "offence", "constitution", "president", "assembly"]',
            text,
        )
        note = (
            f"attested years {GATE_NOTE_YEARS} plus English legal stems {GATE_NOTE_STEMS} "
            f"from articles.parquet HEAD tip {DST_TIP_SHORT}; URL www/gov.sc is query-only, not GATE."
        )
        text = re.sub(
            r"GATE = attested years [^;]+; URL www/(?:gov\.cv|gov\.sc) is query-only, not GATE\.",
            f"GATE = {note}",
            text,
        )
        text = re.sub(
            r"GATE = attested years [^\"\n]+",
            f"GATE = {note}",
            text,
            count=1,
        )
        text = text.replace('"caboverde_pass"', '"seychelles_pass"')
        text = text.replace('"seychelles_pass"', '"seychelles_pass"')
        text = text.replace('"caboverde_gate"', '"seychelles_gate"')
        text = text.replace('"seychelles_gate"', '"seychelles_gate"')
        text = text.replace(
            "attested Seychelles years and Portuguese legal stems",
            "attested Seychelles years and English legal stems",
        )
        text = text.replace(
            "attested Cabo Verde years and Portuguese legal stems",
            "attested Seychelles years and English legal stems",
        )
        text = text.replace(
            "attested Seychelles years and English legal stems",
            "attested Seychelles years and English legal stems",
        )
        text = text.replace("— Portuguese legal corpus", "— English legal corpus")
        text = text.replace("— English legal corpus", "— English legal corpus")

    if dst_name == "seychelles_write_publish_report.py":
        new_gate = f"{GATE_NOTE_YEARS} + stems {GATE_NOTE_STEMS}"
        text = re.sub(
            r"attested years [0-9/]+ \+ stems [a-z_/]+",
            f"attested years {new_gate}",
            text,
        )
        text = text.replace("Portuguese (Cabo Verde) GATE", "English (Seychelles) GATE")
        text = text.replace("Portuguese (Seychelles) GATE", "English (Seychelles) GATE")
        text = text.replace(
            "ASCII-fold Portuguese (Seychelles) GATE",
            "ASCII-fold English (Seychelles) GATE",
        )
        text = text.replace(
            "ASCII-fold English (Seychelles) GATE",
            "ASCII-fold English (Seychelles) GATE",
        )
        text = re.sub(
            r"HOLD 0 STRICT after-ST[^;]*; collectors kept dead \(pkill\); soft never-thin ON; SKIP_US; Italy BLOCKED;[^\"\n]*",
            f"{HOLD}; collectors kept dead (pkill); soft never-thin ON; SKIP_US; Italy BLOCKED; {WAVE_POS}",
            text,
        )
        text = re.sub(
            r"HOLD 0 STRICT after-CV[^;]*; collectors kept dead \(pkill\); soft never-thin ON; SKIP_US; Italy BLOCKED;[^\"\n]*",
            f"{HOLD}; collectors kept dead (pkill); soft never-thin ON; SKIP_US; Italy BLOCKED; {WAVE_POS}",
            text,
        )
        text = text.replace("www/gov.cv is query-only", "www/gov.sc is query-only")
        text = text.replace("caboverde/", "seychelles/")
        text = re.sub(
            r"BM25 PASS on Seychelles ASCII-fold (?:Portuguese|English) GATE \([^)]+\); URL www/gov\.sc is query-only, not GATE",
            f"BM25 PASS on Seychelles ASCII-fold English GATE (attested years {GATE_NOTE_YEARS} + stems {GATE_NOTE_STEMS}); URL www/gov.sc is query-only, not GATE",
            text,
        )
        text = re.sub(
            r"BM25 PASS on Cabo Verde ASCII-fold Portuguese GATE \([^)]+\); URL www/gov\.cv is query-only, not GATE",
            f"BM25 PASS on Seychelles ASCII-fold English GATE (attested years {GATE_NOTE_YEARS} + stems {GATE_NOTE_STEMS}); URL www/gov.sc is query-only, not GATE",
            text,
        )

    leftovers = (
        "Cabo Verde", "caboverde", "Cabo",
        "São Tomé", "Sao Tome", "saotome", "Príncipe", "Principe",
        "Puerto Rico", "puerto_rico",
        "Côte d'Ivoire", "Cote d'Ivoire", "cotedivoire",
        "Antigua and Barbuda", "antigua_barbuda",
        "Gambia", "gambia",
        "Sierra Leone", "sierraleone",
        "Dominica", "dominica",
        "cient-data", "prent-data", "stent-data", "cvent-data", "scent-data",
        "gov.cv",
        "artigo", "lei", "decreto", "codigo", "seccao", "republica",
        "pessoa", "governo", "constituicao", "justica", "assembleia",
        "tribunal", "penal",
    )
    found = []
    for x in leftovers:
        if x == "Cabo":
            if re.search(r'(?<![A-Za-z])Cabo(?![A-Za-z])', text):
                found.append(x)
            continue
        if x == "lei":
            # avoid matching "legislation" etc — whole word only
            if re.search(r'(?<![A-Za-z])lei(?![A-Za-z])', text, re.I):
                found.append(x)
            continue
        if x in text:
            found.append(x)
    if found:
        raise RuntimeError(f"language/country leftovers in {dst_name}: {found}")
    if re.search(r'\bPortuguese\b', text):
        raise RuntimeError(f"leftover Portuguese token in {dst_name}")
    if re.search(r'\bSpanish\b', text):
        raise RuntimeError(f"leftover Spanish token in {dst_name}")
    if re.search(r'\bFrench\b', text):
        raise RuntimeError(f"leftover French token in {dst_name}")
    # Portuguese stem leftovers as whole words
    for stem in ("artigo", "decreto", "codigo", "seccao", "republica", "pessoa", "governo"):
        if re.search(rf'(?<![A-Za-z]){stem}(?![A-Za-z])', text, re.I):
            raise RuntimeError(f"leftover Portuguese stem {stem} in {dst_name}")
    if dst_name.endswith("_bm25_smoke.py") and '", "cv"' in text:
        raise RuntimeError(f"leftover cv query token in {dst_name}")
    if dst_name.endswith("_bm25_smoke.py") and "gov.cv" in text:
        raise RuntimeError(f"leftover gov.cv in {dst_name}")
    scrub = text
    scrub = scrub.replace(DEST_CHAIN, "XX")
    scrub = scrub.replace(HOLD, "XX")
    scrub = scrub.replace(WAVE_POS, "XX")
    scrub = scrub.replace("after-CV", "after-XX")
    scrub = scrub.replace("after CV ", "after XX ")
    scrub = scrub.replace("after_tj", "after_xx")
    scrub = scrub.replace("DM→SL→GM→AG→CI→PR→ST→CV LIVE", "XX→XX→XX→XX→XX→XX→XX→XX LIVE")
    scrub = scrub.replace("after DM→SL→GM→AG→CI→PR→ST→CV LIVE", "after XX→XX→XX→XX→XX→XX→XX→XX LIVE")
    if '"CV"' in scrub or "(CV)" in scrub or "CV→" in scrub or "CV-attested" in scrub:
        tmp = scrub
        if re.search(r'(?<![A-Za-z])CV(?![A-Za-z])', tmp):
            raise RuntimeError(f"leftover CV tokens in {dst_name}: ...{tmp[max(0,tmp.find('CV')-20):tmp.find('CV')+20]}...")
    if "Cabo" in text or "caboverde" in text:
        raise RuntimeError(f"leftover Cabo Verde in {dst_name}")
    if "ipfs_caboverde" in text:
        raise RuntimeError(f"leftover caboverde path in {dst_name}")
    if "agent-data" not in text and "SECRET" in text.upper():
        if any(x in dst_name for x in ("soft_filter", "upload", "orchestrator")):
            if "/home/box/" in text and "agent-data" not in text:
                raise RuntimeError(f"missing agent-data secret path in {dst_name}")
    # data/ paths must survive
    if "soft_filter" in dst_name or "corpus_stream" in dst_name:
        if "data/laws.parquet" not in text and 'data" / "laws.parquet"' not in text and "data/laws" not in text:
            # soft_filter uses Path joins — check
            if '"data"' not in text and "/data/" not in text:
                pass  # Path("data") forms OK if present
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
    if entry.get("slug") == "seychelles" or entry.get("iso2") == "SC":
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
            "iso2": "SC",
            "repo": "endomorphosis/ipfs_seychelles_laws",
            "years_attested": [int(y) for y in GATE_YEARS],
            "gate_years": [int(y) for y in GATE_YEARS],
            "gate_stems": GATE_STEMS,
            "note": (
                f"SC FIRST_IR scaffold; tip MATCH {DST_TIP_SHORT}@118/3623; {HOLD}; "
                f"soft never-thin ON; SKIP_US; Italy BLOCKED; {WAVE_POS}"
            ),
            "status": "CLAIMED",
            "mode": "FIRST_IR",
        })
        break
else:
    raise RuntimeError("Seychelles entry missing from wave JSON")
wave.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print("updated wave JSON Seychelles entry")
print("GATE years", GATE_YEARS)
print("GATE stems", GATE_STEMS)
print("n_gate", len(GATE_YEARS) + len(GATE_STEMS))
print("GATE language: English")
print("HOLD", HOLD)
