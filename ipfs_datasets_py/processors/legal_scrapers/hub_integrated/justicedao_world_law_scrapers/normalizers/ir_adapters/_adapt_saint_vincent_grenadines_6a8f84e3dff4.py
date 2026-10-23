#!/usr/bin/env python3
"""Adapt the Aruba Dutch memsafe FIRST_IR pack to Saint Vincent and the Grenadines VC tip 6a8f84e3dff4.

English (Saint Vincent and the Grenadines); FIRST_IR; HOLD 0 STRICT after-AW (VC→VU).
Soft never-thin ON; SKIP_US; Italy BLOCKED. Wave after_mv: AW LIVE → VC → VU (VC only).
GATE: attested years + English legal stems from data/articles.parquet tip 6a8f84e3dff4
(act/article/section/law/ordinance/code/republic; include vincent/grenadines).
URL gov.vc query-only, NOT GATE.
Source tip 06c2b343c859 (Aruba Dutch memsafe with data/ paths)
— flip language Dutch→English (Saint Vincent and the Grenadines).
Keep data/articles.parquet + data/laws.parquet; agent-data not cient-data.
Do NOT start VU/Vanuatu. Floors 157 laws / 1140 articles.
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
SRC_TIP_FULL = "06c2b343c85997d75dcc1ee98bd76e249c21ca09"
SRC_TIP_SHORT = "06c2b343c859"
DST_TIP_FULL = "6a8f84e3dff4a35f7073490336b6c94e4f872fff"
DST_TIP_SHORT = "6a8f84e3dff4"
FLOOR_LAWS, FLOOR_ARTS = 157, 1140
SRC_FLOOR_L, SRC_FLOOR_A = 175, 1419

# Sampled from data/articles+laws.parquet @ 6a8f84e3dff4 (~10 years + English stems)
# Whole-word ASCII-fold FTS hits; laws=157 articles=1140.
# Top years by doc hits; English legal stems (+ vincent/grenadines).
# Note: singular "grenadine" has 0 whole-word hits; use attested "grenadines".
GATE_YEARS = [
    "2021", "2020", "2018", "2009", "2016",
    "2019", "2023", "2003", "2015", "2026",
]
GATE_STEMS = [
    "act", "article", "section", "law", "ordinance", "code", "republic",
    "vincent", "grenadines", "government", "person", "order",
]
YEARS_ATTESTED = [int(y) for y in GATE_YEARS] + [
    2009, 2003, 1980, 2000, 2008, 2001, 1981, 1992, 1987, 1990,
]
GATE_NOTE_YEARS = "/".join(GATE_YEARS)
GATE_NOTE_STEMS = "/".join(GATE_STEMS)
HOLD = "HOLD 0 STRICT after-AW (VC→VU)"
WAVE_POS = (
    "second country of after_mv wave "
    "(after AW LIVE → VC → VU; NOT wave end)"
)
DEST_CHAIN = "VC→VU"
SRC_HOLD = "HOLD 0 STRICT after-MV (AW→VC→VU)"
SRC_WAVE = (
    "first country of after_mv wave "
    "(after MV LIVE → AW → VC → VU; NOT wave end)"
)
SRC_CHAIN = "AW→VC→VU"

FILES = [
    ("aruba_soft_filter.py", "saint_vincent_grenadines_soft_filter.py"),
    (f"aruba_corpus_stream_{SRC_TIP_SHORT}.py", f"saint_vincent_grenadines_corpus_stream_{DST_TIP_SHORT}.py"),
    (f"aruba_encode_memsafe_{SRC_TIP_SHORT}.py", f"saint_vincent_grenadines_encode_memsafe_{DST_TIP_SHORT}.py"),
    (f"aruba_finish_from_emb_{SRC_TIP_SHORT}.py", f"saint_vincent_grenadines_finish_from_emb_{DST_TIP_SHORT}.py"),
    (f"aruba_stream_graph_parts_{SRC_TIP_SHORT}.py", f"saint_vincent_grenadines_stream_graph_parts_{DST_TIP_SHORT}.py"),
    (f"aruba_package_memsafe_{SRC_TIP_SHORT}.py", f"saint_vincent_grenadines_package_memsafe_{DST_TIP_SHORT}.py"),
    ("aruba_upload.py", "saint_vincent_grenadines_upload.py"),
    ("aruba_bm25_smoke.py", "saint_vincent_grenadines_bm25_smoke.py"),
    ("aruba_write_publish_report.py", "saint_vincent_grenadines_write_publish_report.py"),
    (f"aruba_orchestrator_{SRC_TIP_SHORT}.py", f"saint_vincent_grenadines_orchestrator_{DST_TIP_SHORT}.py"),
]

DISPLAY = "Saint Vincent and the Grenadines"
SLUG = "saint_vincent_grenadines"


def adapt(text: str, dst_name: str) -> str:
    # Repair path corruption from prior adapts
    for bad in (
        "cient-data", "prent-data", "stent-data", "cvent-data", "scent-data",
        "carent-data", "yement-data", "djiboutient-data", "marshallislandsent-data",
        "kiribatient-data", "burundient-data", "eswatinient-data", "niueent-data",
        "guineabissauent-data", "surinameent-data", "equatorialguineaent-data",
        "guyanaent-data", "beninent-data", "somaliaent-data", "maldivesent-data",
        "arubaent-data", "saint_vincent_grenadinesent-data",
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
    text = text.replace("after-MV", "\x00AFTERAW\x00")
    text = text.replace("after MV ", "\x00AFTERAW_SP\x00")
    text = text.replace("after_mv", "\x00AFTERMV_US\x00")
    text = text.replace("after_dj", "\x00AFTERDJ_US\x00")
    text = text.replace(
        "after MV LIVE → AW → VC → VU",
        "\x00SRCCHAIN_FULL\x00",
    )
    text = text.replace("AW FIRST_IR", "\x00DESTFIRST\x00")
    text = text.replace("AW→VC→VU", "\x00DESTCHAIN\x00")
    text = text.replace("do NOT start VC/VU", "\x00DONOTSTART\x00")
    text = text.replace("do NOT start VC or VU", "\x00DONOTSTART2\x00")
    text = text.replace("NOT wave end", "\x00NOTWE\x00")

    reps = [
        (SRC_TIP_FULL, DST_TIP_FULL),
        (SRC_TIP_SHORT, DST_TIP_SHORT),
        ("endomorphosis/ipfs_aruba_laws", "endomorphosis/ipfs_saint_vincent_grenadines_laws"),
        ("justicedao/ipfs_aruba_laws_ir", "justicedao/ipfs_saint_vincent_grenadines_laws_ir"),
        ("ipfs_aruba_laws_ir", "ipfs_saint_vincent_grenadines_laws_ir"),
        ("ipfs_aruba_laws", "ipfs_saint_vincent_grenadines_laws"),
        # HOLD / wave restore
        ("\x00DESTHOLD\x00", HOLD),
        ("\x00DESTWAVE\x00", WAVE_POS),
        ("\x00DESTCHAIN\x00", DEST_CHAIN),
        ("\x00SRCCHAIN_FULL\x00", "after AW LIVE → VC → VU"),
        ("\x00AFTERAW\x00", "after-AW"),
        ("\x00AFTERAW_SP\x00", "after AW "),
        ("\x00DESTFIRST\x00", "VC FIRST_IR"),
        ("\x00NOTWE\x00", "NOT wave end"),
        ("\x00DONOTSTART\x00", "do NOT start VU/Vanuatu"),
        ("\x00DONOTSTART2\x00", "do NOT start VU"),
        ("AW FIRST_IR (not wave end)", "VC FIRST_IR (not wave end)"),
        ("www/overheid.aw", "www/gov.vc"),
        ("overheid.aw", "gov.vc"),
        ("www.overheid.aw", "www.gov.vc"),
        ("gobierno.aw", "gov.vc"),
        ("www.gobierno.aw", "www.gov.vc"),
        ("afkondigingsblad", "constitution"),
        ("landsbesluit", "minister"),
        ("staatsblad", "parliament"),
        ("hoofdstuk", "chapter"),
        # Language / country
        ("Dutch (Aruba)", "English (Saint Vincent and the Grenadines)"),
        ("Dutch Aruba", "English Saint Vincent and the Grenadines"),
        ("Dutch legal", "English legal"),
        ("ASCII-fold Dutch", "ASCII-fold English"),
        ("Dutch GATE", "English GATE"),
        ("Dutch stems", "English stems"),
        ("language Dutch", "keep language English"),
        ("Aruba", DISPLAY),
        # slug / path forms BEFORE bare aruba
        ("aruba_ranked", "saint_vincent_grenadines_ranked"),
        ("aruba_gate", "saint_vincent_grenadines_gate"),
        ("aruba_pass", "saint_vincent_grenadines_pass"),
        ("aruba_encode_memsafe", "saint_vincent_grenadines_encode_memsafe"),
        ("aruba_package_memsafe", "saint_vincent_grenadines_package_memsafe"),
        ("aruba_corpus_stream", "saint_vincent_grenadines_corpus_stream"),
        ("aruba_encode_done", "saint_vincent_grenadines_encode_done"),
        ("aruba_filtered_", "saint_vincent_grenadines_filtered_"),
        ("aruba_", "saint_vincent_grenadines_"),
        # ISO whole-token / path forms only (AW already protected in HOLD)
        ('"AW"', '"VC"'),
        ("AW-attested", "VC-attested"),
        ("(AW)", "(VC)"),
        ('"aw"', '"vc"'),
        # floors 175/1419 → 157/1140 — compound ONLY first
        ("175/1419", "157/1140"),
        ("175 / 1419", "157 / 1140"),
        ("175, 1419", "157, 1140"),
        ("FLOOR_LAWS, FLOOR_ARTS = 175, 1419", "FLOOR_LAWS, FLOOR_ARTS = 157, 1140"),
        ('int(pack.get("n_laws") or 175)', 'int(pack.get("n_laws") or 157)'),
        ('int(pack.get("n_articles") or 1419)', 'int(pack.get("n_articles") or 1140)'),
        ("@ 175/", "@ 157/"),
        ("floor 175/", "floor 157/"),
        ("(175/", "(157/"),
        (" 1419", " 1140"),
        ("1419", "1140"),
        ("= 175,", "= 157,"),
        ("or 175)", "or 157)"),
        ("175", "157"),
    ]
    for a, b in reps:
        text = text.replace(a, b)

    # Bare slug "aruba" → "saint_vincent_grenadines"
    text = re.sub(r"(?<![A-Za-z0-9_])aruba(?![A-Za-z0-9_])", SLUG, text)

    text = text.replace("\x00BM25\x00", "BM25").replace("\x00bm25\x00", "bm25")
    text = text.replace("\x00AFTERDJ_US\x00", "after_dj")
    text = text.replace("\x00AFTERMV_US\x00", "after_mv")
    text = text.replace("\x00DESTHOLD\x00", HOLD)
    text = text.replace("\x00DESTCHAIN\x00", DEST_CHAIN)
    text = text.replace("\x00DESTWAVE\x00", WAVE_POS)

    # display name / slug fixes
    # After Aruba→DISPLAY, slug fields may have gotten the display name
    text = text.replace(f'"name": "{SLUG}"', f'"name": "{DISPLAY}"')
    text = text.replace(f'"name": "{DISPLAY}"', f'"name": "{DISPLAY}"')
    text = text.replace(f'"slug": "{DISPLAY}"', f'"slug": "{SLUG}"')
    text = text.replace(f'SLUG = "{DISPLAY}"', f'SLUG = "{SLUG}"')
    text = text.replace(f'SLUG = "{SLUG}"', f'SLUG = "{SLUG}"')
    text = text.replace(f'"country": "{DISPLAY}"', f'"country": "{SLUG}"')
    text = text.replace('"country": "aruba"', f'"country": "{SLUG}"')
    # README / prose: keep display name
    text = text.replace(f"# {SLUG} filtered pack", f"# {DISPLAY} filtered pack")
    text = text.replace(f"{SLUG} laws IR release", f"{DISPLAY} laws IR release")

    # Ensure agent-data survived
    for bad in (
        "cient-data", "prent-data", "stent-data", "cvent-data", "scent-data",
        "carent-data", "yement-data", "djiboutient-data", "marshallislandsent-data",
        "kiribatient-data", "burundient-data", "eswatinient-data", "niueent-data",
        "guineabissauent-data", "surinameent-data", "equatorialguineaent-data",
        "guyanaent-data", "beninent-data", "somaliaent-data", "maldivesent-data",
        "arubaent-data", "saint_vincent_grenadinesent-data",
    ):
        text = text.replace(f"/home/box/{bad}/", "/home/box/agent-data/")
        text = text.replace(bad, "agent-data")

    if dst_name == "saint_vincent_grenadines_bm25_smoke.py":
        start = text.index("GATE = [")
        end = text.index("]", start) + 1
        years_line = ", ".join(f'"{y}"' for y in GATE_YEARS)
        stems_line = ", ".join(f'"{s}"' for s in GATE_STEMS)
        gate = f"GATE = [\n    {years_line},\n    {stems_line},\n]"
        text = text[:start] + gate + text[end:]
        text = re.sub(
            r"QUERIES = GATE \+ \[[^\]]*\]",
            'QUERIES = GATE + ["www", "gov.vc", "www.gov.vc", "constitution", "minister", "parliament", "shall", "chapter", "assembly", "schedule"]',
            text,
            count=1,
        )
        text = re.sub(
            r'"""BM25 smoke for .*?"""',
            '"""BM25 smoke for Saint Vincent and the Grenadines IR — English legal corpus; years + English legal stems FTS gate.\n\n'
            "GATE is attested ASCII years plus English legal stems (ASCII-fold). URL www/gov.vc\n"
            "is query-only, never GATE. Every GATE token must rank a hit.\n"
            '"""',
            text,
            count=1,
            flags=re.S,
        )
        note = (
            f"attested years {GATE_NOTE_YEARS} plus English legal stems {GATE_NOTE_STEMS} "
            f"from articles.parquet HEAD tip {DST_TIP_SHORT}; URL www/gov.vc "
            f"is query-only, not GATE."
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

    if dst_name == "saint_vincent_grenadines_write_publish_report.py":
        gate_note = (
            f"BM25 PASS on Saint Vincent and the Grenadines ASCII-fold English GATE "
            f"(attested years {GATE_NOTE_YEARS} + stems {GATE_NOTE_STEMS}); "
            f"URL www/gov.vc is query-only, not GATE"
        )
        text = re.sub(
            r'BM25 PASS on Saint Vincent[^"]*"',
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
        text = text.replace("www/overheid.aw is query-only", "www/gov.vc is query-only")
        text = text.replace("www/gov.vc is query-only", "www/gov.vc is query-only")
        text = re.sub(
            r"HOLD 0 STRICT after-MV[^;]*; collectors kept dead \(pkill\); soft never-thin ON; SKIP_US; Italy BLOCKED;[^\"\n]*",
            f"{HOLD}; collectors kept dead (pkill); soft never-thin ON; SKIP_US; Italy BLOCKED; {WAVE_POS}",
            text,
        )
        text = re.sub(
            r"HOLD 0 STRICT after-AW[^;]*; collectors kept dead \(pkill\); soft never-thin ON; SKIP_US; Italy BLOCKED;[^\"\n]*",
            f"{HOLD}; collectors kept dead (pkill); soft never-thin ON; SKIP_US; Italy BLOCKED; {WAVE_POS}",
            text,
        )
        text = re.sub(r"[ \t]{2,}", " ", text)

    leftovers = (
        "Aruba", "aruba",
        "cient-data", "prent-data", "stent-data", "cvent-data", "scent-data",
        "carent-data", "yement-data", "djiboutient-data", "marshallislandsent-data",
        "kiribatient-data", "burundient-data", "eswatinient-data", "niueent-data",
        "guineabissauent-data", "surinameent-data", "equatorialguineaent-data",
        "guyanaent-data", "beninent-data", "somaliaent-data", "maldivesent-data",
        "overheid.aw", "www.overheid.aw", "gobierno.aw",
    )
    found = []
    for x in leftovers:
        if x == "aruba":
            if re.search(r"(?<![A-Za-z0-9_])aruba(?![A-Za-z0-9_])", text):
                found.append(x)
            continue
        if x in text:
            found.append(x)
    if found:
        raise RuntimeError(f"language/country leftovers in {dst_name}: {found}")

    # Reject non-VC tokens in GATE; require English stems
    if dst_name.endswith("_bm25_smoke.py"):
        gate_slice = text[text.index("GATE = ["): text.index("]", text.index("GATE = [")) + 1]
        for bad in (
            "aruba", "artikel", "wet", "besluit", "landsverordening", "verordening",
            "koninkrijk", "regering", "persoon", "minister",
            "maldives", "maldivian", "ruling",
            "loi", "decret", "ordonnance", "republique", "benin", "gouvernement", "personne",
            "articulo", "ley", "decreto", "codigo", "seccion",
            "artigo", "lei", "suriname", "curacao", "guyana",
        ):
            if f'"{bad}"' in gate_slice:
                raise RuntimeError(f"non-VC token in GATE of {dst_name}: {bad}")
        for stem in GATE_STEMS:
            if f'"{stem}"' not in gate_slice:
                raise RuntimeError(f"missing English stem in GATE of {dst_name}: {stem}")
        for year in GATE_YEARS:
            if f'"{year}"' not in gate_slice:
                raise RuntimeError(f"missing year in GATE of {dst_name}: {year}")
        if '", "aw"' in text or '", "AW"' in text:
            raise RuntimeError(f"leftover aw query token in {dst_name}")
        if "overheid.aw" in text or "gobierno.aw" in text:
            raise RuntimeError(f"leftover overheid.aw in {dst_name}")

    # reject bare aruba / AW leftovers outside protected HOLD/wave
    scrub = text
    scrub = scrub.replace(WAVE_POS, "XX")
    scrub = scrub.replace(HOLD, "XX")
    scrub = scrub.replace(DEST_CHAIN, "XX")
    scrub = scrub.replace(SRC_CHAIN, "XX")
    scrub = scrub.replace(SRC_HOLD, "XX")
    scrub = scrub.replace(SRC_WAVE, "XX")
    scrub = scrub.replace("after-AW", "after-XX")
    scrub = scrub.replace("after AW ", "after XX ")
    scrub = scrub.replace("after_mv", "after_xx")
    scrub = scrub.replace("after_dj", "after_xx")
    scrub = scrub.replace("AW LIVE", "XX LIVE")
    scrub = scrub.replace("→AW ", "→XX ")
    scrub = scrub.replace("MV→AW", "XX")
    scrub = scrub.replace("AW→VC→VU", "XX")
    if re.search(r"(?<![A-Za-z0-9_])aruba(?![A-Za-z0-9_])", scrub):
        m = re.search(r"(?<![A-Za-z0-9_])aruba(?![A-Za-z0-9_])", scrub)
        raise RuntimeError(
            f"leftover aruba in {dst_name}: ...{scrub[max(0, m.start()-20):m.start()+20]}..."
        )
    if re.search(r"(?<![A-Za-z%])AW(?![A-Za-z])", scrub):
        m = re.search(r"(?<![A-Za-z%])AW(?![A-Za-z])", scrub)
        raise RuntimeError(
            f"leftover AW in {dst_name}: ...{scrub[max(0, m.start()-30):m.start()+30]}..."
        )
    if "ipfs_aruba" in text:
        raise RuntimeError(f"leftover aruba path in {dst_name}")
    if "agent-data" not in text and "SECRET" in text.upper():
        if any(x in dst_name for x in ("soft_filter", "upload", "orchestrator")):
            if "/home/box/" in text and "agent-data" not in text:
                raise RuntimeError(f"missing agent-data secret path in {dst_name}")
    # data/ paths must survive
    if "soft_filter" in dst_name or "corpus_stream" in dst_name:
        if "data/laws.parquet" not in text and 'data" / "laws.parquet"' not in text:
            if '"data"' not in text and "/data/" not in text:
                raise RuntimeError(f"missing data/ parquet paths in {dst_name}")
    # tip integrity
    if SRC_TIP_SHORT in text:
        raise RuntimeError(f"src tip leftover in {dst_name}")
    if "67930c3f-c86b-" in text:
        raise RuntimeError(f"UUID c94b corrupted to c86b in {dst_name}")
    if DST_TIP_SHORT not in text and any(x in dst_name for x in ("soft_filter", "orchestrator", "bm25_smoke")):
        raise RuntimeError(f"missing DST tip in {dst_name}")
    # english language must remain for VC
    if "write_publish" in dst_name or "bm25_smoke" in dst_name:
        if re.search(r"ASCII-fold Dutch|Dutch legal", text):
            raise RuntimeError(f"leftover Dutch phrasing in {dst_name}")
        if re.search(r"ASCII-fold French|French legal", text):
            raise RuntimeError(f"leftover French phrasing in {dst_name}")
    return text


for src_name, dst_name in FILES:
    src = ROOT / src_name
    if not src.is_file():
        raise FileNotFoundError(src)
    (ROOT / dst_name).write_text(
        adapt(src.read_text(encoding="utf-8"), dst_name), encoding="utf-8"
    )
    print(f"wrote {dst_name}")

wave = Path("/workspace/country-law-triage/next_ir_ok_wave_after_mv.json")
data = json.loads(wave.read_text(encoding="utf-8"))
for entry in data["queue"]:
    if entry.get("slug") == SLUG or entry.get("iso2") == "VC":
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
            "iso2": "VC",
            "slug": SLUG,
            "repo": "endomorphosis/ipfs_saint_vincent_grenadines_laws",
            "years_attested": YEARS_ATTESTED,
            "gate_years": [int(y) for y in GATE_YEARS],
            "gate_stems": GATE_STEMS,
            "note": (
                f"VC FIRST_IR scaffold; tip MATCH {DST_TIP_SHORT}@157/1140; {HOLD}; "
                f"soft never-thin ON; SKIP_US; Italy BLOCKED; {WAVE_POS}; "
                f"English GATE ({len(GATE_YEARS)} years + {len(GATE_STEMS)} stems); do NOT start VU"
            ),
            "status": "CLAIMED",
            "mode": "FIRST_IR",
            "wave_end": False,
            "do_not_start": False,
        })
        break
else:
    raise RuntimeError("Saint Vincent / VC entry missing from wave JSON")

# Keep VU do_not_start
for entry in data["queue"]:
    if entry.get("iso2") == "VU" or entry.get("slug") == "vanuatu":
        entry["do_not_start"] = True
        entry["status"] = entry.get("status") or "HOLD_QUEUED"
        break

data["wave_status"] = "IN_PROGRESS_VC"
data["hold"] = HOLD
data["current"] = SLUG
data["do_not_start_next"] = "vanuatu"
data["next"] = "vanuatu"
data["hold_note"] = (
    "HOLD 0 STRICT for VC FIRST_IR build in progress; collectors/deepeners dead; "
    "do NOT start VU until VC LIVE and separately green-lit"
)
wave.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print("updated wave JSON VC entry")
print("GATE years", GATE_YEARS)
print("GATE stems", GATE_STEMS)
print("n_gate", len(GATE_YEARS) + len(GATE_STEMS))
print("HOLD", HOLD)
print("GATE language: English years+stems")
