#!/usr/bin/env python3
"""Adapt the Puerto Rico Spanish memsafe FIRST_IR pack to São Tomé and Príncipe ST.

Portuguese São Tomé and Príncipe; FIRST_IR; HOLD 0 STRICT after-PR (ST→CV→SC→CF→YE→DJ).
Soft never-thin ON; SKIP_US; Italy BLOCKED. WAVE after_tj seventh country (after
DM→SL→GM→AG→CI→PR LIVE), NOT wave end. GATE: attested years + Portuguese legal stems from
data/articles.parquet tip d7dc8feb75b0 (Portuguese; include tome/principe/republica).
URL www/gov.st query-only, NOT GATE.
Source tip f50550af2585 (Puerto Rico Spanish) — override language to Portuguese.
Also repair cient-data / prent-data → agent-data path corruption.
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
SRC_TIP_FULL = "f50550af2585dd63c0f0901fc291bf05ac12855c"
SRC_TIP_SHORT = "f50550af2585"
DST_TIP_FULL = "d7dc8feb75b017e559dc7d770d04b904ea3f13df"
DST_TIP_SHORT = "d7dc8feb75b0"
FLOOR_LAWS, FLOOR_ARTS = 116, 3658
SRC_FLOOR_L, SRC_FLOOR_A = 175, 3677

# Sampled from data/articles.parquet @ d7dc8feb75b0 (~10 years + ~11 Portuguese stems)
# Whole-word ASCII-fold FTS hits; avoid substring-only stems.
GATE_YEARS = ["2009", "2017", "2018", "2008", "2016", "2020", "2014", "2019", "2025", "2015"]
GATE_STEMS = [
    "artigo", "lei", "decreto", "codigo", "seccao", "republica",
    "tome", "principe", "estado", "pessoa", "governo",
]
GATE_NOTE_YEARS = "/".join(GATE_YEARS)
GATE_NOTE_STEMS = "/".join(GATE_STEMS)
HOLD = "HOLD 0 STRICT after-PR (ST→CV→SC→CF→YE→DJ)"
WAVE_POS = (
    "seventh country of after_tj wave "
    "(after DM→SL→GM→AG→CI→PR LIVE; ST→CV→SC→CF→YE→DJ; NOT wave end)"
)
DEST_CHAIN = "ST→CV→SC→CF→YE→DJ"
SRC_CHAIN = "PR→ST→CV→SC→CF→YE→DJ"
SRC_HOLD = "HOLD 0 STRICT after-CI (PR→ST→CV→SC→CF→YE→DJ)"
SRC_WAVE = (
    "sixth country of after_tj wave "
    "(after DM→SL→GM→AG→CI LIVE; PR→ST→CV→SC→CF→YE→DJ; NOT wave end)"
)

FILES = [
    ("puerto_rico_soft_filter.py", "saotome_soft_filter.py"),
    (f"puerto_rico_corpus_stream_{SRC_TIP_SHORT}.py", f"saotome_corpus_stream_{DST_TIP_SHORT}.py"),
    (f"puerto_rico_encode_memsafe_{SRC_TIP_SHORT}.py", f"saotome_encode_memsafe_{DST_TIP_SHORT}.py"),
    (f"puerto_rico_finish_from_emb_{SRC_TIP_SHORT}.py", f"saotome_finish_from_emb_{DST_TIP_SHORT}.py"),
    (f"puerto_rico_stream_graph_parts_{SRC_TIP_SHORT}.py", f"saotome_stream_graph_parts_{DST_TIP_SHORT}.py"),
    (f"puerto_rico_package_memsafe_{SRC_TIP_SHORT}.py", f"saotome_package_memsafe_{DST_TIP_SHORT}.py"),
    ("puerto_rico_upload.py", "saotome_upload.py"),
    ("puerto_rico_bm25_smoke.py", "saotome_bm25_smoke.py"),
    ("puerto_rico_write_publish_report.py", "saotome_write_publish_report.py"),
    (f"puerto_rico_orchestrator_{SRC_TIP_SHORT}.py", f"saotome_orchestrator_{DST_TIP_SHORT}.py"),
]


def adapt(text: str, dst_name: str) -> str:
    # Repair path corruption from prior adapts
    text = text.replace("/home/box/cient-data/", "/home/box/agent-data/")
    text = text.replace("cient-data", "agent-data")
    text = text.replace("/home/box/prent-data/", "/home/box/agent-data/")
    text = text.replace("prent-data", "agent-data")

    # Protect BM25 / bm25
    text = text.replace("BM25", "\x00BM25\x00").replace("bm25", "\x00bm25\x00")
    text = text.replace("bmjacency", "adjacency")

    # Protect / rewrite HOLD + wave BEFORE ISO/slug swaps (PR appears in SRC_CHAIN)
    text = text.replace(SRC_HOLD, "\x00DESTHOLD\x00")
    text = text.replace(SRC_WAVE, "\x00DESTWAVE\x00")
    text = text.replace(SRC_CHAIN, "\x00DESTCHAIN\x00")
    text = text.replace(HOLD, "\x00DESTHOLD\x00")
    text = text.replace(DEST_CHAIN, "\x00DESTCHAIN\x00")
    text = text.replace(WAVE_POS, "\x00DESTWAVE\x00")
    text = text.replace("after-CI", "\x00AFTERPR\x00")
    text = text.replace("after CI ", "\x00AFTERPR_SP\x00")
    text = text.replace("after_tj", "\x00AFTERTJ_US\x00")
    text = text.replace("DM→SL→GM→AG→CI LIVE", "\x00DMSLGMAGCIPR\x00")
    text = text.replace("sixth country of \x00AFTERTJ_US\x00 wave", "\x00DESTWAVE_SHORT\x00")
    text = text.replace("sixth country of after_tj wave", "\x00DESTWAVE_SHORT\x00")

    reps = [
        (SRC_TIP_FULL, DST_TIP_FULL),
        (SRC_TIP_SHORT, DST_TIP_SHORT),
        ("endomorphosis/ipfs_puerto_rico_laws", "endomorphosis/ipfs_saotome_laws"),
        ("justicedao/ipfs_puerto_rico_laws_ir", "justicedao/ipfs_saotome_laws_ir"),
        ("ipfs_puerto_rico_laws_ir", "ipfs_saotome_laws_ir"),
        ("ipfs_puerto_rico_laws", "ipfs_saotome_laws"),
        # HOLD / wave restore tokens mapped to dest
        ("\x00DESTHOLD\x00", HOLD),
        ("\x00DESTWAVE\x00", WAVE_POS),
        ("\x00DESTWAVE_SHORT\x00", WAVE_POS),
        ("\x00DESTCHAIN\x00", DEST_CHAIN),
        ("\x00AFTERPR\x00", "after-PR"),
        ("\x00AFTERPR_SP\x00", "after PR "),
        ("\x00DMSLGMAGCIPR\x00", "DM→SL→GM→AG→CI→PR LIVE"),
        ("PR FIRST_IR (not wave end)", "ST FIRST_IR (not wave end)"),
        ("www/pr.gov", "www/gov.st"),
        # Language override Spanish → Portuguese BEFORE country name swaps
        ("Spanish (Puerto Rico)", "Portuguese (São Tomé and Príncipe)"),
        ("Spanish Puerto Rico", "Portuguese São Tomé and Príncipe"),
        ("ASCII-fold Spanish", "ASCII-fold Portuguese"),
        ("Spanish legal stems", "Portuguese legal stems"),
        ("Spanish legal corpus", "Portuguese legal corpus"),
        ("Puerto Rico", "São Tomé and Príncipe"),
        # slug / path forms (underscore slug → single token)
        ("puerto_rico_ranked", "saotome_ranked"),
        ("puerto_rico_gate", "saotome_gate"),
        ("puerto_rico_pass", "saotome_pass"),
        ("puerto_rico_encode_memsafe", "saotome_encode_memsafe"),
        ("puerto_rico_package_memsafe", "saotome_package_memsafe"),
        ("puerto_rico_corpus_stream", "saotome_corpus_stream"),
        ("puerto_rico_encode_done", "saotome_encode_done"),
        ("puerto_rico_", "saotome_"),
        ("puerto_rico", "saotome"),
        # ISO whole-token / path forms only
        ('"PR"', '"ST"'),
        ("PR-attested", "ST-attested"),
        ("(PR)", "(ST)"),
        ('"pr"', '"st"'),
        # floors 175/3677 → 116/3658
        ("175/3677", "116/3658"),
        ("175 / 3677", "116 / 3658"),
        ("175, 3677", "116, 3658"),
        ("FLOOR_LAWS, FLOOR_ARTS = 175, 3677", "FLOOR_LAWS, FLOOR_ARTS = 116, 3658"),
        ("or 175)", "or 116)"),
        ("or 175,", "or 116,"),
        ("or 175}", "or 116}"),
        ("= 175,", "= 116,"),
        ("= 175", "= 116"),
        ("@ 175/", "@ 116/"),
        (" 175/", " 116/"),
        ("floor 175/", "floor 116/"),
        ("(175/", "(116/"),
        (" or 175", " or 116"),
        (" 3677", " 3658"),
        ("3677", "3658"),
        # language field leftovers
        ('"language": "Spanish"', '"language": "Portuguese"'),
        ('"lang": "Spanish"', '"lang": "Portuguese"'),
        ("language: Spanish", "language: Portuguese"),
        ("Language: Spanish", "Language: Portuguese"),
    ]
    for a, b in reps:
        text = text.replace(a, b)

    text = text.replace("\x00BM25\x00", "BM25").replace("\x00bm25\x00", "bm25")
    text = text.replace("\x00AFTERTJ_US\x00", "after_tj")
    text = text.replace("\x00DESTHOLD\x00", HOLD)
    text = text.replace("\x00DESTCHAIN\x00", DEST_CHAIN)
    text = text.replace("\x00DESTWAVE\x00", WAVE_POS)

    text = text.replace("FLOOR_LAWS, FLOOR_ARTS = 175, 3658", "FLOOR_LAWS, FLOOR_ARTS = 116, 3658")
    text = text.replace("FLOOR_LAWS, FLOOR_ARTS = 116, 3677", "FLOOR_LAWS, FLOOR_ARTS = 116, 3658")
    text = text.replace('int(pack.get("n_articles") or 3677)', 'int(pack.get("n_articles") or 3658)')
    text = text.replace('int(pack.get("n_articles") or 3658)', 'int(pack.get("n_articles") or 3658)')
    text = text.replace('int(pack.get("n_laws") or 175)', 'int(pack.get("n_laws") or 116)')
    text = text.replace('int(pack.get("n_laws") or 116)', 'int(pack.get("n_laws") or 116)')

    # display name / slug fixes
    text = text.replace('"name": "saotome"', '"name": "São Tomé and Príncipe"')
    text = text.replace('"name": "São Tomé and Príncipe"', '"name": "São Tomé and Príncipe"')
    text = text.replace('"slug": "São Tomé and Príncipe"', '"slug": "saotome"')
    text = text.replace('SLUG = "São Tomé and Príncipe"', 'SLUG = "saotome"')
    text = text.replace('SLUG = "saotome"', 'SLUG = "saotome"')

    # Ensure agent-data survived any residual swaps (saotome has no "pr" but be safe)
    text = text.replace("/home/box/prent-data/", "/home/box/agent-data/")
    text = text.replace("prent-data", "agent-data")
    text = text.replace("/home/box/cient-data/", "/home/box/agent-data/")
    text = text.replace("/home/box/stent-data/", "/home/box/agent-data/")
    text = text.replace("stent-data", "agent-data")

    if dst_name == "saotome_bm25_smoke.py":
        start = text.index("GATE = [")
        end = text.index("]", start) + 1
        years_line = ", ".join(f'"{y}"' for y in GATE_YEARS)
        stems_line = ", ".join(f'"{s}"' for s in GATE_STEMS)
        gate = f"GATE = [\n    {years_line},\n    {stems_line},\n]"
        text = text[:start] + gate + text[end:]
        text = re.sub(
            r'QUERIES = GATE \+ \[[^\]]*\]',
            'QUERIES = GATE + ["www", "gov.st", "governo", "tribunal", "justica", "penal", "assembleia", "constituicao"]',
            text,
        )
        note = (
            f"attested years {GATE_NOTE_YEARS} plus Portuguese legal stems {GATE_NOTE_STEMS} "
            f"from articles.parquet HEAD tip {DST_TIP_SHORT}; URL www/gov.st is query-only, not GATE."
        )
        text = re.sub(
            r"GATE = attested years [^;]+; URL www/(?:pr\.gov|gov\.st) is query-only, not GATE\.",
            f"GATE = {note}",
            text,
        )
        text = re.sub(
            r"GATE = attested years [^\"\n]+",
            f"GATE = {note}",
            text,
            count=1,
        )
        text = text.replace('"puerto_rico_pass"', '"saotome_pass"')
        text = text.replace('"saotome_pass"', '"saotome_pass"')
        text = text.replace('"puerto_rico_gate"', '"saotome_gate"')
        text = text.replace('"saotome_gate"', '"saotome_gate"')
        text = text.replace(
            "attested Puerto Rico years and Spanish legal stems",
            "attested São Tomé and Príncipe years and Portuguese legal stems",
        )
        text = text.replace(
            "attested São Tomé and Príncipe years and Spanish legal stems",
            "attested São Tomé and Príncipe years and Portuguese legal stems",
        )
        text = text.replace(
            "attested São Tomé and Príncipe years and Portuguese legal stems",
            "attested São Tomé and Príncipe years and Portuguese legal stems",
        )
        text = text.replace("— Spanish legal corpus", "— Portuguese legal corpus")
        text = text.replace("Spanish legal corpus", "Portuguese legal corpus")
        text = text.replace("Spanish São Tomé", "Portuguese São Tomé")

    if dst_name == "saotome_write_publish_report.py":
        new_gate = f"{GATE_NOTE_YEARS} + stems {GATE_NOTE_STEMS}"
        text = re.sub(
            r"attested years [0-9/]+ \+ stems [a-z_/]+",
            f"attested years {new_gate}",
            text,
        )
        text = text.replace("Spanish GATE", "Portuguese (São Tomé and Príncipe) GATE")
        text = text.replace(
            "ASCII-fold Portuguese (São Tomé and Príncipe) GATE",
            "ASCII-fold Portuguese (São Tomé and Príncipe) GATE",
        )
        text = text.replace(
            "ASCII-fold Spanish (São Tomé and Príncipe) GATE",
            "ASCII-fold Portuguese (São Tomé and Príncipe) GATE",
        )
        text = re.sub(
            r"HOLD 0 STRICT after-CI[^;]*; collectors kept dead \(pkill\); soft never-thin ON; SKIP_US; Italy BLOCKED;[^\"\n]*",
            f"{HOLD}; collectors kept dead (pkill); soft never-thin ON; SKIP_US; Italy BLOCKED; {WAVE_POS}",
            text,
        )
        text = re.sub(
            r"HOLD 0 STRICT after-PR[^;]*; collectors kept dead \(pkill\); soft never-thin ON; SKIP_US; Italy BLOCKED;[^\"\n]*",
            f"{HOLD}; collectors kept dead (pkill); soft never-thin ON; SKIP_US; Italy BLOCKED; {WAVE_POS}",
            text,
        )
        text = text.replace("www/pr.gov is query-only", "www/gov.st is query-only")
        text = text.replace("puerto_rico/", "saotome/")
        text = re.sub(
            r"BM25 PASS on São Tomé and Príncipe ASCII-fold (?:English|French|Spanish|Portuguese) \(São Tomé and Príncipe\) GATE \([^)]+\); URL www/gov\.st is query-only, not GATE",
            f"BM25 PASS on São Tomé and Príncipe ASCII-fold Portuguese GATE (attested years {GATE_NOTE_YEARS} + stems {GATE_NOTE_STEMS}); URL www/gov.st is query-only, not GATE",
            text,
        )
        text = re.sub(
            r"BM25 PASS on São Tomé and Príncipe ASCII-fold Portuguese GATE \([^)]+\); URL www/gov\.st is query-only, not GATE",
            f"BM25 PASS on São Tomé and Príncipe ASCII-fold Portuguese GATE (attested years {GATE_NOTE_YEARS} + stems {GATE_NOTE_STEMS}); URL www/gov.st is query-only, not GATE",
            text,
        )

    leftovers = (
        "Puerto Rico", "puerto_rico", "Puerto",
        "Côte d'Ivoire", "Cote d'Ivoire", "cotedivoire", "Ivoire", "ivoire",
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
        "Spanish (Puerto", "Spanish Puerto", "Spanish (São",
        "Tajikistan", "tajikistan",
        "Barbuda", "barbuda",
        "cient-data", "prent-data", "stent-data",
        "articulo", "seccion", "asociado", "constitucion", "persona",
        "pr.gov",
    )
    found = [x for x in leftovers if x in text]
    if found:
        raise RuntimeError(f"language/country leftovers in {dst_name}: {found}")
    if re.search(r'\bSpanish\b', text):
        raise RuntimeError(f"leftover Spanish token in {dst_name}")
    if re.search(r'\bEnglish\b', text):
        raise RuntimeError(f"leftover English token in {dst_name}")
    if re.search(r'\bFrench\b', text):
        raise RuntimeError(f"leftover French token in {dst_name}")
    if dst_name.endswith("_bm25_smoke.py") and '", "pr"' in text:
        raise RuntimeError(f"leftover pr query token in {dst_name}")
    if dst_name.endswith("_bm25_smoke.py") and "pr.gov" in text:
        raise RuntimeError(f"leftover pr.gov in {dst_name}")
    # reject bare ISO leftovers that should have been swapped
    scrub = text
    scrub = scrub.replace(DEST_CHAIN, "XX")
    scrub = scrub.replace(HOLD, "XX")
    scrub = scrub.replace(WAVE_POS, "XX")
    scrub = scrub.replace("after-PR", "after-XX")
    scrub = scrub.replace("after PR ", "after XX ")
    scrub = scrub.replace("after_tj", "after_xx")
    scrub = scrub.replace("DM→SL→GM→AG→CI→PR LIVE", "XX→XX→XX→XX→XX→XX LIVE")
    scrub = scrub.replace("after DM→SL→GM→AG→CI→PR LIVE", "after XX→XX→XX→XX→XX→XX LIVE")
    if '"PR"' in scrub or "(PR)" in scrub or "PR→" in scrub or "PR-attested" in scrub:
        tmp = scrub
        if re.search(r'(?<![A-Za-z])PR(?![A-Za-z])', tmp):
            raise RuntimeError(f"leftover PR tokens in {dst_name}: ...{tmp[max(0,tmp.find('PR')-20):tmp.find('PR')+20]}...")
    if "Puerto" in text or "puerto_rico" in text:
        raise RuntimeError(f"leftover Puerto Rico in {dst_name}")
    if "ipfs_puerto_rico" in text:
        raise RuntimeError(f"leftover puerto_rico path in {dst_name}")
    if "agent-data" not in text and "SECRET" in text.upper():
        if any(x in dst_name for x in ("soft_filter", "upload", "orchestrator")):
            if "/home/box/" in text and "agent-data" not in text:
                raise RuntimeError(f"missing agent-data secret path in {dst_name}")
    # data/ parquet paths must remain
    if "soft_filter" in dst_name or "package" in dst_name or "corpus" in dst_name or "finish" in dst_name:
        if "data/articles.parquet" not in text and "articles.parquet" in text:
            # soft filter uses data/articles.parquet via hf_hub_download path arg
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
    if entry.get("slug") == "saotome" or entry.get("iso2") == "ST":
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
            "iso2": "ST",
            "repo": "endomorphosis/ipfs_saotome_laws",
            "years_attested": [int(y) for y in GATE_YEARS],
            "gate_years": [int(y) for y in GATE_YEARS],
            "gate_stems": GATE_STEMS,
            "note": (
                f"ST FIRST_IR scaffold; tip MATCH {DST_TIP_SHORT}@116/3658; {HOLD}; "
                f"soft never-thin ON; SKIP_US; Italy BLOCKED; {WAVE_POS}"
            ),
            "status": "CLAIMED",
        })
        break
else:
    raise RuntimeError("São Tomé entry missing from wave JSON")
wave.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print("updated wave JSON São Tomé entry")
print("GATE years", GATE_YEARS)
print("GATE stems", GATE_STEMS)
print("n_gate", len(GATE_YEARS) + len(GATE_STEMS))
print("GATE language: Portuguese")
print("HOLD", HOLD)
