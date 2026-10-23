#!/usr/bin/env python3
"""Adapt the Côte d'Ivoire French memsafe FIRST_IR pack to Puerto Rico PR.

Spanish Puerto Rico; FIRST_IR; HOLD 0 STRICT after-CI (PR→ST→CV→SC→CF→YE→DJ).
Soft never-thin ON; SKIP_US; Italy BLOCKED. WAVE after_tj sixth country (after
DM→SL→GM→AG→CI LIVE), NOT wave end. GATE: attested years + Spanish legal stems from
data/articles.parquet tip f50550af2585 (Spanish; include puerto/estado/asociado).
URL www/pr.gov query-only, NOT GATE.
Source tip 67ef43d5e4b3 (Côte d'Ivoire French) — override language to Spanish.
Also repair cient-data → agent-data path corruption from prior AG→CI /ag swap.
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
SRC_TIP_FULL = "67ef43d5e4b3053bccc68b9a6bebbbc1f4e98bd3"
SRC_TIP_SHORT = "67ef43d5e4b3"
DST_TIP_FULL = "f50550af2585dd63c0f0901fc291bf05ac12855c"
DST_TIP_SHORT = "f50550af2585"
FLOOR_LAWS, FLOOR_ARTS = 175, 3677
SRC_FLOOR_L, SRC_FLOOR_A = 71, 3771

# Sampled from data/articles.parquet @ f50550af2585 (~10 years + ~11 Spanish stems)
# Prefer law-year attestations (Ley N-YYYY); skip form-rev-only years as primary.
GATE_YEARS = ["2020", "2018", "2017", "2019", "2015", "2014", "2004", "2003", "2011", "2009"]
GATE_STEMS = [
    "articulo", "ley", "decreto", "codigo", "seccion", "gobierno",
    "puerto", "estado", "asociado", "constitucion", "persona",
]
GATE_NOTE_YEARS = "/".join(GATE_YEARS)
GATE_NOTE_STEMS = "/".join(GATE_STEMS)
HOLD = "HOLD 0 STRICT after-CI (PR→ST→CV→SC→CF→YE→DJ)"
WAVE_POS = (
    "sixth country of after_tj wave "
    "(after DM→SL→GM→AG→CI LIVE; PR→ST→CV→SC→CF→YE→DJ; NOT wave end)"
)
DEST_CHAIN = "PR→ST→CV→SC→CF→YE→DJ"
SRC_CHAIN = "CI→PR→ST→CV→SC→CF→YE→DJ"
SRC_HOLD = "HOLD 0 STRICT after-AG (CI→PR→ST→CV→SC→CF→YE→DJ)"
SRC_WAVE = (
    "fifth country of after_tj wave "
    "(after DM→SL→GM→AG LIVE; CI→PR→ST→CV→SC→CF→YE→DJ; NOT wave end)"
)

FILES = [
    ("cotedivoire_soft_filter.py", "puerto_rico_soft_filter.py"),
    (f"cotedivoire_corpus_stream_{SRC_TIP_SHORT}.py", f"puerto_rico_corpus_stream_{DST_TIP_SHORT}.py"),
    (f"cotedivoire_encode_memsafe_{SRC_TIP_SHORT}.py", f"puerto_rico_encode_memsafe_{DST_TIP_SHORT}.py"),
    (f"cotedivoire_finish_from_emb_{SRC_TIP_SHORT}.py", f"puerto_rico_finish_from_emb_{DST_TIP_SHORT}.py"),
    (f"cotedivoire_stream_graph_parts_{SRC_TIP_SHORT}.py", f"puerto_rico_stream_graph_parts_{DST_TIP_SHORT}.py"),
    (f"cotedivoire_package_memsafe_{SRC_TIP_SHORT}.py", f"puerto_rico_package_memsafe_{DST_TIP_SHORT}.py"),
    ("cotedivoire_upload.py", "puerto_rico_upload.py"),
    ("cotedivoire_bm25_smoke.py", "puerto_rico_bm25_smoke.py"),
    ("cotedivoire_write_publish_report.py", "puerto_rico_write_publish_report.py"),
    (f"cotedivoire_orchestrator_{SRC_TIP_SHORT}.py", f"puerto_rico_orchestrator_{DST_TIP_SHORT}.py"),
]


def adapt(text: str, dst_name: str) -> str:
    # Repair path corruption from prior AG→CI adapt (/ag → /ci broke agent-data)
    text = text.replace("/home/box/cient-data/", "/home/box/agent-data/")
    text = text.replace("cient-data", "agent-data")

    # Protect BM25 / bm25
    text = text.replace("BM25", "\x00BM25\x00").replace("bm25", "\x00bm25\x00")
    text = text.replace("bmjacency", "adjacency")

    # Protect / rewrite HOLD + wave BEFORE ISO/slug swaps (CI appears in SRC_CHAIN)
    text = text.replace(SRC_HOLD, "\x00DESTHOLD\x00")
    text = text.replace(SRC_WAVE, "\x00DESTWAVE\x00")
    text = text.replace(SRC_CHAIN, "\x00DESTCHAIN\x00")
    text = text.replace(HOLD, "\x00DESTHOLD\x00")
    text = text.replace(DEST_CHAIN, "\x00DESTCHAIN\x00")
    text = text.replace(WAVE_POS, "\x00DESTWAVE\x00")
    text = text.replace("after-AG", "\x00AFTERCI\x00")
    text = text.replace("after AG ", "\x00AFTERCI_SP\x00")
    text = text.replace("after_tj", "\x00AFTERTJ_US\x00")
    text = text.replace("DM→SL→GM→AG LIVE", "\x00DMSLGMAGCI\x00")
    text = text.replace("fifth country of \x00AFTERTJ_US\x00 wave", "\x00DESTWAVE_SHORT\x00")
    text = text.replace("fifth country of after_tj wave", "\x00DESTWAVE_SHORT\x00")

    reps = [
        (SRC_TIP_FULL, DST_TIP_FULL),
        (SRC_TIP_SHORT, DST_TIP_SHORT),
        ("endomorphosis/ipfs_cotedivoire_laws", "endomorphosis/ipfs_puerto_rico_laws"),
        ("justicedao/ipfs_cotedivoire_laws_ir", "justicedao/ipfs_puerto_rico_laws_ir"),
        ("ipfs_cotedivoire_laws_ir", "ipfs_puerto_rico_laws_ir"),
        ("ipfs_cotedivoire_laws", "ipfs_puerto_rico_laws"),
        # HOLD / wave restore tokens mapped to dest
        ("\x00DESTHOLD\x00", HOLD),
        ("\x00DESTWAVE\x00", WAVE_POS),
        ("\x00DESTWAVE_SHORT\x00", WAVE_POS),
        ("\x00DESTCHAIN\x00", DEST_CHAIN),
        ("\x00AFTERCI\x00", "after-CI"),
        ("\x00AFTERCI_SP\x00", "after CI "),
        ("\x00DMSLGMAGCI\x00", "DM→SL→GM→AG→CI LIVE"),
        ("CI FIRST_IR (not wave end)", "PR FIRST_IR (not wave end)"),
        ("www/gov/ci", "www/pr.gov"),
        # Language override French → Spanish BEFORE country name swaps
        ("French (Côte d'Ivoire)", "Spanish (Puerto Rico)"),
        ("French Côte d'Ivoire", "Spanish Puerto Rico"),
        ("ASCII-fold French", "ASCII-fold Spanish"),
        ("French legal stems", "Spanish legal stems"),
        ("French legal corpus", "Spanish legal corpus"),
        ("Côte d'Ivoire", "Puerto Rico"),
        ("Cote d'Ivoire", "Puerto Rico"),
        ("Cote dIvoire", "Puerto Rico"),
        # slug / path forms
        ("cotedivoire_ranked", "puerto_rico_ranked"),
        ("cotedivoire_gate", "puerto_rico_gate"),
        ("cotedivoire_pass", "puerto_rico_pass"),
        ("cotedivoire_encode_memsafe", "puerto_rico_encode_memsafe"),
        ("cotedivoire_package_memsafe", "puerto_rico_package_memsafe"),
        ("cotedivoire_corpus_stream", "puerto_rico_corpus_stream"),
        ("cotedivoire_encode_done", "puerto_rico_encode_done"),
        ("cotedivoire_", "puerto_rico_"),
        ("cotedivoire", "puerto_rico"),
        # ISO whole-token / path forms only (avoid agent-data /ci corruption)
        ('"CI"', '"PR"'),
        ("CI-attested", "PR-attested"),
        ("(CI)", "(PR)"),
        ('"ci"', '"pr"'),
        # floors 71/3771 → 175/3677
        ("71/3771", "175/3677"),
        ("71 / 3771", "175 / 3677"),
        ("71, 3771", "175, 3677"),
        ("FLOOR_LAWS, FLOOR_ARTS = 71, 3771", "FLOOR_LAWS, FLOOR_ARTS = 175, 3677"),
        ("or 71)", "or 175)"),
        ("or 71,", "or 175,"),
        ("or 71}", "or 175}"),
        ("= 71,", "= 175,"),
        ("= 71", "= 175"),
        ("@ 71/", "@ 175/"),
        (" 71/", " 175/"),
        ("floor 71/", "floor 175/"),
        ("(71/", "(175/"),
        (" or 71", " or 175"),
        (" 3771", " 3677"),
        ("3771", "3677"),
        # language field leftovers
        ('"language": "French"', '"language": "Spanish"'),
        ('"lang": "French"', '"lang": "Spanish"'),
        ("language: French", "language: Spanish"),
        ("Language: French", "Language: Spanish"),
    ]
    for a, b in reps:
        text = text.replace(a, b)

    text = text.replace("\x00BM25\x00", "BM25").replace("\x00bm25\x00", "bm25")
    text = text.replace("\x00AFTERTJ_US\x00", "after_tj")
    text = text.replace("\x00DESTHOLD\x00", HOLD)
    text = text.replace("\x00DESTCHAIN\x00", DEST_CHAIN)
    text = text.replace("\x00DESTWAVE\x00", WAVE_POS)

    text = text.replace("FLOOR_LAWS, FLOOR_ARTS = 71, 3677", "FLOOR_LAWS, FLOOR_ARTS = 175, 3677")
    text = text.replace("FLOOR_LAWS, FLOOR_ARTS = 175, 3771", "FLOOR_LAWS, FLOOR_ARTS = 175, 3677")
    text = text.replace('int(pack.get("n_articles") or 3771)', 'int(pack.get("n_articles") or 3677)')
    text = text.replace('int(pack.get("n_articles") or 3677)', 'int(pack.get("n_articles") or 3677)')
    text = text.replace('int(pack.get("n_laws") or 71)', 'int(pack.get("n_laws") or 175)')
    text = text.replace('int(pack.get("n_laws") or 175)', 'int(pack.get("n_laws") or 175)')

    # display name fixes
    text = text.replace('"name": "puerto_rico"', '"name": "Puerto Rico"')
    text = text.replace('"name": "Puerto Rico"', '"name": "Puerto Rico"')
    text = text.replace('"slug": "Puerto Rico"', '"slug": "puerto_rico"')

    # Ensure agent-data survived any residual swaps
    text = text.replace("/home/box/prent-data/", "/home/box/agent-data/")
    text = text.replace("prent-data", "agent-data")
    text = text.replace("/home/box/cient-data/", "/home/box/agent-data/")

    if dst_name == "puerto_rico_bm25_smoke.py":
        start = text.index("GATE = [")
        end = text.index("]", start) + 1
        years_line = ", ".join(f'"{y}"' for y in GATE_YEARS)
        stems_line = ", ".join(f'"{s}"' for s in GATE_STEMS)
        gate = f"GATE = [\n    {years_line},\n    {stems_line},\n]"
        text = text[:start] + gate + text[end:]
        # Replace QUERIES line entirely
        text = re.sub(
            r'QUERIES = GATE \+ \[[^\]]*\]',
            'QUERIES = GATE + ["www", "pr.gov", "gobierno", "tribunal", "justicia", "penal", "asamblea", "constitucion"]',
            text,
        )
        note = (
            f"attested years {GATE_NOTE_YEARS} plus Spanish legal stems {GATE_NOTE_STEMS} "
            f"from articles.parquet HEAD tip {DST_TIP_SHORT}; URL www/pr.gov is query-only, not GATE."
        )
        text = re.sub(
            r"GATE = attested years [^;]+; URL www/(?:gov/ci|pr\.gov) is query-only, not GATE\.",
            f"GATE = {note}",
            text,
        )
        # also fix tokenizer_note if still French-ish after generic replace
        text = re.sub(
            r"GATE = attested years [^\"\n]+",
            f"GATE = {note}",
            text,
            count=1,
        )
        text = text.replace('"cotedivoire_pass"', '"puerto_rico_pass"')
        text = text.replace('"puerto_rico_pass"', '"puerto_rico_pass"')
        text = text.replace('"cotedivoire_gate"', '"puerto_rico_gate"')
        text = text.replace('"puerto_rico_gate"', '"puerto_rico_gate"')
        text = text.replace(
            "attested Côte d'Ivoire years and French legal stems",
            "attested Puerto Rico years and Spanish legal stems",
        )
        text = text.replace(
            "attested Puerto Rico years and French legal stems",
            "attested Puerto Rico years and Spanish legal stems",
        )
        text = text.replace(
            "attested Puerto Rico years and Spanish legal stems",
            "attested Puerto Rico years and Spanish legal stems",
        )
        text = text.replace("— French legal corpus", "— Spanish legal corpus")
        text = text.replace("French legal corpus", "Spanish legal corpus")
        text = text.replace("French Puerto Rico", "Spanish Puerto Rico")
        # drop leftover French GATE tokens if any slipped
        for fr, es in [
            ('"article"', '"articulo"'),
            ('"loi"', '"ley"'),
            ('"decret"', '"decreto"'),
            ('"ministre"', '"gobierno"'),
            ('"code"', '"codigo"'),
            ('"section"', '"seccion"'),
            ('"ordonnance"', '"decreto"'),
            ('"ivoire"', '"puerto"'),
            ('"republique"', '"gobierno"'),
            ('"etat"', '"estado"'),
            ('"officiel"', '"gobierno"'),
            ('"constitution"', '"constitucion"'),
            ('"justice"', '"justicia"'),
        ]:
            # only in GATE/QUERIES context already rewritten; skip mass replace of personne etc.
            pass

    if dst_name == "puerto_rico_write_publish_report.py":
        new_gate = f"{GATE_NOTE_YEARS} + stems {GATE_NOTE_STEMS}"
        text = re.sub(
            r"attested years [0-9/]+ \+ stems [a-z_/]+",
            f"attested years {new_gate}",
            text,
        )
        text = text.replace("French GATE", "Spanish (Puerto Rico) GATE")
        text = text.replace(
            "ASCII-fold Spanish (Puerto Rico) GATE",
            "ASCII-fold Spanish (Puerto Rico) GATE",
        )
        text = text.replace(
            "ASCII-fold French (Puerto Rico) GATE",
            "ASCII-fold Spanish (Puerto Rico) GATE",
        )
        text = re.sub(
            r"HOLD 0 STRICT after-AG[^;]*; collectors kept dead \(pkill\); soft never-thin ON; SKIP_US; Italy BLOCKED;[^\"\n]*",
            f"{HOLD}; collectors kept dead (pkill); soft never-thin ON; SKIP_US; Italy BLOCKED; {WAVE_POS}",
            text,
        )
        text = re.sub(
            r"HOLD 0 STRICT after-CI[^;]*; collectors kept dead \(pkill\); soft never-thin ON; SKIP_US; Italy BLOCKED;[^\"\n]*",
            f"{HOLD}; collectors kept dead (pkill); soft never-thin ON; SKIP_US; Italy BLOCKED; {WAVE_POS}",
            text,
        )
        text = text.replace("www/gov/ci is query-only", "www/pr.gov is query-only")
        text = text.replace("cotedivoire/", "puerto_rico/")
        text = re.sub(
            r"BM25 PASS on Puerto Rico ASCII-fold (?:English|French|Spanish) \(Puerto Rico\) GATE \([^)]+\); URL www/pr\.gov is query-only, not GATE",
            f"BM25 PASS on Puerto Rico ASCII-fold Spanish GATE (attested years {GATE_NOTE_YEARS} + stems {GATE_NOTE_STEMS}); URL www/pr.gov is query-only, not GATE",
            text,
        )
        text = re.sub(
            r"BM25 PASS on Puerto Rico ASCII-fold Spanish GATE \([^)]+\); URL www/pr\.gov is query-only, not GATE",
            f"BM25 PASS on Puerto Rico ASCII-fold Spanish GATE (attested years {GATE_NOTE_YEARS} + stems {GATE_NOTE_STEMS}); URL www/pr.gov is query-only, not GATE",
            text,
        )

    leftovers = (
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
        "French (Côte", "French Côte", "French (Puerto",
        "Tajikistan", "tajikistan",
        "Barbuda", "barbuda",
        "cient-data", "prent-data",
    )
    found = [x for x in leftovers if x in text]
    if found:
        raise RuntimeError(f"language/country leftovers in {dst_name}: {found}")
    if re.search(r'\bFrench\b', text):
        raise RuntimeError(f"leftover French token in {dst_name}")
    if re.search(r'\bEnglish\b', text):
        raise RuntimeError(f"leftover English token in {dst_name}")
    if dst_name.endswith("_bm25_smoke.py") and '", "ci"' in text:
        raise RuntimeError(f"leftover ci query token in {dst_name}")
    if dst_name.endswith("_bm25_smoke.py") and "www/gov/ci" in text:
        raise RuntimeError(f"leftover gov/ci in {dst_name}")
    # reject bare ISO leftovers that should have been swapped
    scrub = text
    scrub = scrub.replace(DEST_CHAIN, "XX")
    scrub = scrub.replace(HOLD, "XX")
    scrub = scrub.replace(WAVE_POS, "XX")
    scrub = scrub.replace("after-CI", "after-XX")
    scrub = scrub.replace("after CI ", "after XX ")
    scrub = scrub.replace("after_tj", "after_xx")
    scrub = scrub.replace("DM→SL→GM→AG→CI LIVE", "XX→XX→XX→XX→XX LIVE")
    scrub = scrub.replace("after DM→SL→GM→AG→CI LIVE", "after XX→XX→XX→XX→XX LIVE")
    if '"CI"' in scrub or "(CI)" in scrub or "CI→" in scrub or "CI-attested" in scrub:
        tmp = scrub
        if re.search(r'(?<![A-Za-z])CI(?![A-Za-z])', tmp):
            raise RuntimeError(f"leftover CI tokens in {dst_name}: ...{tmp[max(0,tmp.find('CI')-20):tmp.find('CI')+20]}...")
    if "Côte" in text or "cotedivoire" in text or "Ivoire" in text:
        raise RuntimeError(f"leftover Côte d'Ivoire in {dst_name}")
    if "ipfs_cotedivoire" in text:
        raise RuntimeError(f"leftover cotedivoire path in {dst_name}")
    if "agent-data" not in text and "SECRET" in text.upper():
        # soft_filter/upload/orch must keep agent-data
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
    if entry.get("slug") == "puerto_rico" or entry.get("iso2") == "PR":
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
            "language": "Spanish",
            "lang": "Spanish",
            "iso2": "PR",
            "repo": "endomorphosis/ipfs_puerto_rico_laws",
            "years_attested": [int(y) for y in GATE_YEARS],
            "gate_years": [int(y) for y in GATE_YEARS],
            "gate_stems": GATE_STEMS,
            "note": (
                f"PR FIRST_IR scaffold; tip MATCH {DST_TIP_SHORT}@175/3677; {HOLD}; "
                f"soft never-thin ON; SKIP_US; Italy BLOCKED; {WAVE_POS}"
            ),
            "status": "CLAIMED",
        })
        break
else:
    raise RuntimeError("Puerto Rico entry missing from wave JSON")
wave.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print("updated wave JSON Puerto Rico entry")
print("GATE years", GATE_YEARS)
print("GATE stems", GATE_STEMS)
print("n_gate", len(GATE_YEARS) + len(GATE_STEMS))
print("GATE language: Spanish")
print("HOLD", HOLD)
