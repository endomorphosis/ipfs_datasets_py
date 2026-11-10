#!/usr/bin/env python3
"""Adapt the Saint Vincent English memsafe FIRST_IR pack to Vanuatu VU tip 755173efca8c.

English (Vanuatu); FIRST_IR; HOLD 0 STRICT after-VC (VU WAVE END).
Soft never-thin ON; SKIP_US; Italy BLOCKED. Wave after_mv: AW LIVE → VC LIVE → VU
(WAVE END). GATE: attested years + English legal stems from data/articles.parquet
tip 755173efca8c (act/article/section/law/ordinance/code/republic/vanuatu/
government/person/order/bill). URL gov.vu / parliament.gov.vu query-only, NOT GATE.
Source tip 6a8f84e3dff4 (Saint Vincent English memsafe with data/ paths)
— keep language English (Vanuatu).
Keep data/articles.parquet + data/laws.parquet; agent-data not cient-data.
Do NOT start any next country after LIVE. Floors 89 laws / 1062 articles.
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
SRC_TIP_FULL = "6a8f84e3dff4a35f7073490336b6c94e4f872fff"
SRC_TIP_SHORT = "6a8f84e3dff4"
DST_TIP_FULL = "755173efca8c3d23ab196666274d042cc6c2478d"
DST_TIP_SHORT = "755173efca8c"
FLOOR_LAWS, FLOOR_ARTS = 89, 1062
SRC_FLOOR_L, SRC_FLOOR_A = 157, 1140

# Sampled from data/articles.parquet @ 755173efca8c (~10 years + English stems)
# Whole-word ASCII-fold FTS hits; laws=89 articles=1062.
# Top years by doc hits in article body; English legal stems (+ vanuatu/bill).
GATE_YEARS = [
    "2024", "2025", "2017", "2018", "2014",
    "2016", "2001", "2000", "2007", "2003",
]
GATE_STEMS = [
    "act", "article", "section", "law", "regulation", "code", "republic",
    "vanuatu", "government", "person", "order", "bill",
]
YEARS_ATTESTED = [int(y) for y in GATE_YEARS] + [
    2023, 2020, 2021, 2026, 2019, 2012, 2013, 2008, 1998, 1997,
]
GATE_NOTE_YEARS = "/".join(GATE_YEARS)
GATE_NOTE_STEMS = "/".join(GATE_STEMS)
HOLD = "HOLD 0 STRICT after-VC (VU WAVE END)"
WAVE_POS = (
    "WAVE END of after_mv wave "
    "(after AW LIVE → VC LIVE → VU)"
)
DEST_CHAIN = "VU WAVE END"
SRC_HOLD = "HOLD 0 STRICT after-AW (VC→VU)"
SRC_WAVE = (
    "second country of after_mv wave "
    "(after AW LIVE → VC → VU; NOT wave end)"
)
SRC_CHAIN = "VC→VU"

FILES = [
    ("saint_vincent_grenadines_soft_filter.py", "vanuatu_soft_filter.py"),
    (f"saint_vincent_grenadines_corpus_stream_{SRC_TIP_SHORT}.py", f"vanuatu_corpus_stream_{DST_TIP_SHORT}.py"),
    (f"saint_vincent_grenadines_encode_memsafe_{SRC_TIP_SHORT}.py", f"vanuatu_encode_memsafe_{DST_TIP_SHORT}.py"),
    (f"saint_vincent_grenadines_finish_from_emb_{SRC_TIP_SHORT}.py", f"vanuatu_finish_from_emb_{DST_TIP_SHORT}.py"),
    (f"saint_vincent_grenadines_stream_graph_parts_{SRC_TIP_SHORT}.py", f"vanuatu_stream_graph_parts_{DST_TIP_SHORT}.py"),
    (f"saint_vincent_grenadines_package_memsafe_{SRC_TIP_SHORT}.py", f"vanuatu_package_memsafe_{DST_TIP_SHORT}.py"),
    ("saint_vincent_grenadines_upload.py", "vanuatu_upload.py"),
    ("saint_vincent_grenadines_bm25_smoke.py", "vanuatu_bm25_smoke.py"),
    ("saint_vincent_grenadines_write_publish_report.py", "vanuatu_write_publish_report.py"),
    (f"saint_vincent_grenadines_orchestrator_{SRC_TIP_SHORT}.py", f"vanuatu_orchestrator_{DST_TIP_SHORT}.py"),
]

DISPLAY = "Vanuatu"
SLUG = "vanuatu"
SRC_DISPLAY = "Saint Vincent and the Grenadines"
SRC_SLUG = "saint_vincent_grenadines"


def adapt(text: str, dst_name: str) -> str:
    # Repair path corruption from prior adapts
    for bad in (
        "cient-data", "prent-data", "stent-data", "cvent-data", "scent-data",
        "carent-data", "yement-data", "djiboutient-data", "marshallislandsent-data",
        "kiribatient-data", "burundient-data", "eswatinient-data", "niueent-data",
        "guineabissauent-data", "surinameent-data", "equatorialguineaent-data",
        "guyanaent-data", "beninent-data", "somaliaent-data", "maldivesent-data",
        "arubaent-data", "saint_vincent_grenadinesent-data", "vanuatuent-data",
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
    text = text.replace("after-AW", "\x00AFTERVC\x00")
    text = text.replace("after AW ", "\x00AFTERVC_SP\x00")
    text = text.replace("after_mv", "\x00AFTERMV_US\x00")
    text = text.replace("after_dj", "\x00AFTERDJ_US\x00")
    text = text.replace(
        "after AW LIVE → VC → VU",
        "\x00SRCCHAIN_FULL\x00",
    )
    text = text.replace("VC FIRST_IR", "\x00DESTFIRST\x00")
    text = text.replace("VC→VU", "\x00DESTCHAIN\x00")
    text = text.replace("do NOT start VU/Vanuatu", "\x00DONOTSTART\x00")
    text = text.replace("do NOT start VU", "\x00DONOTSTART2\x00")
    text = text.replace("NOT wave end", "\x00NOTWE\x00")

    # Protect UUID fragment before digit floor swaps (c94b must not become c86b via 1140→1062 or 94)
    text = text.replace("67930c3f-c94b-445b-a5bc-01d3fc1135c1", "\x00UUID94\x00")

    reps = [
        (SRC_TIP_FULL, DST_TIP_FULL),
        (SRC_TIP_SHORT, DST_TIP_SHORT),
        ("endomorphosis/ipfs_saint_vincent_grenadines_laws", "endomorphosis/ipfs_vanuatu_laws"),
        ("justicedao/ipfs_saint_vincent_grenadines_laws_ir", "justicedao/ipfs_vanuatu_laws_ir"),
        ("ipfs_saint_vincent_grenadines_laws_ir", "ipfs_vanuatu_laws_ir"),
        ("ipfs_saint_vincent_grenadines_laws", "ipfs_vanuatu_laws"),
        # HOLD / wave restore
        ("\x00DESTHOLD\x00", HOLD),
        ("\x00DESTWAVE\x00", WAVE_POS),
        ("\x00DESTCHAIN\x00", DEST_CHAIN),
        ("\x00SRCCHAIN_FULL\x00", "after VC LIVE → VU"),
        ("\x00AFTERVC\x00", "after-VC"),
        ("\x00AFTERVC_SP\x00", "after VC "),
        ("\x00DESTFIRST\x00", "VU FIRST_IR"),
        ("\x00NOTWE\x00", "WAVE END"),
        ("\x00DONOTSTART\x00", "do NOT start any next country"),
        ("\x00DONOTSTART2\x00", "do NOT start any next"),
        ("VC FIRST_IR (not wave end)", "VU FIRST_IR (WAVE END)"),
        ("VC FIRST_IR (WAVE END)", "VU FIRST_IR (WAVE END)"),
        # URLs
        ("www/gov.vc", "www/gov.vu"),
        ("gov.vc", "gov.vu"),
        ("www.gov.vc", "www.gov.vu"),
        # Language / country — display name BEFORE slug
        ("English (Saint Vincent and the Grenadines)", "English (Vanuatu)"),
        ("English Saint Vincent and the Grenadines", "English Vanuatu"),
        ("Saint Vincent and the Grenadines", DISPLAY),
        # slug / path forms BEFORE bare saint_vincent_grenadines
        ("saint_vincent_grenadines_ranked", "vanuatu_ranked"),
        ("saint_vincent_grenadines_gate", "vanuatu_gate"),
        ("saint_vincent_grenadines_pass", "vanuatu_pass"),
        ("saint_vincent_grenadines_encode_memsafe", "vanuatu_encode_memsafe"),
        ("saint_vincent_grenadines_package_memsafe", "vanuatu_package_memsafe"),
        ("saint_vincent_grenadines_corpus_stream", "vanuatu_corpus_stream"),
        ("saint_vincent_grenadines_encode_done", "vanuatu_encode_done"),
        ("saint_vincent_grenadines_filtered_", "vanuatu_filtered_"),
        ("saint_vincent_grenadines_", "vanuatu_"),
        # ISO whole-token / path forms only (VC already protected in HOLD)
        ('"VC"', '"VU"'),
        ("VC-attested", "VU-attested"),
        ("(VC)", "(VU)"),
        ('"vc"', '"vu"'),
        # floors 157/1140 → 89/1062 — compound ONLY first
        ("157/1140", "89/1062"),
        ("157 / 1140", "89 / 1062"),
        ("157, 1140", "89, 1062"),
        ("FLOOR_LAWS, FLOOR_ARTS = 157, 1140", "FLOOR_LAWS, FLOOR_ARTS = 89, 1062"),
        ('int(pack.get("n_laws") or 157)', 'int(pack.get("n_laws") or 89)'),
        ('int(pack.get("n_articles") or 1140)', 'int(pack.get("n_articles") or 1062)'),
        ("@ 157/", "@ 89/"),
        ("floor 157/", "floor 89/"),
        ("(157/", "(89/"),
        (" 1140", " 1062"),
        ("1140", "1062"),
        ("= 157,", "= 89,"),
        ("or 157)", "or 89)"),
        ("157", "89"),
    ]
    for a, b in reps:
        text = text.replace(a, b)

    # Bare slug
    text = re.sub(
        r"(?<![A-Za-z0-9_])saint_vincent_grenadines(?![A-Za-z0-9_])",
        SLUG,
        text,
    )

    text = text.replace("\x00BM25\x00", "BM25").replace("\x00bm25\x00", "bm25")
    text = text.replace("\x00AFTERDJ_US\x00", "after_dj")
    text = text.replace("\x00AFTERMV_US\x00", "after_mv")
    text = text.replace("\x00DESTHOLD\x00", HOLD)
    text = text.replace("\x00DESTCHAIN\x00", DEST_CHAIN)
    text = text.replace("\x00DESTWAVE\x00", WAVE_POS)
    text = text.replace("\x00UUID94\x00", "67930c3f-c94b-445b-a5bc-01d3fc1135c1")

    # display name / slug fixes
    text = text.replace(f'"name": "{SLUG}"', f'"name": "{DISPLAY}"')
    text = text.replace(f'"slug": "{DISPLAY}"', f'"slug": "{SLUG}"')
    text = text.replace(f'SLUG = "{DISPLAY}"', f'SLUG = "{SLUG}"')
    text = text.replace(f'"country": "{DISPLAY}"', f'"country": "{SLUG}"')
    text = text.replace('"country": "saint_vincent_grenadines"', f'"country": "{SLUG}"')
    text = text.replace(f"# {SLUG} filtered pack", f"# {DISPLAY} filtered pack")
    text = text.replace(f"{SLUG} laws IR release", f"{DISPLAY} laws IR release")

    # Ensure agent-data survived
    for bad in (
        "cient-data", "prent-data", "stent-data", "cvent-data", "scent-data",
        "carent-data", "yement-data", "djiboutient-data", "marshallislandsent-data",
        "kiribatient-data", "burundient-data", "eswatinient-data", "niueent-data",
        "guineabissauent-data", "surinameent-data", "equatorialguineaent-data",
        "guyanaent-data", "beninent-data", "somaliaent-data", "maldivesent-data",
        "arubaent-data", "saint_vincent_grenadinesent-data", "vanuatuent-data",
    ):
        text = text.replace(f"/home/box/{bad}/", "/home/box/agent-data/")
        text = text.replace(bad, "agent-data")

    if dst_name == "vanuatu_bm25_smoke.py":
        start = text.index("GATE = [")
        end = text.index("]", start) + 1
        years_line = ", ".join(f'"{y}"' for y in GATE_YEARS)
        stems_line = ", ".join(f'"{s}"' for s in GATE_STEMS)
        gate = f"GATE = [\n    {years_line},\n    {stems_line},\n]"
        text = text[:start] + gate + text[end:]
        text = re.sub(
            r"QUERIES = GATE \+ \[[^\]]*\]",
            'QUERIES = GATE + ["www", "gov.vu", "www.gov.vu", "parliament.gov.vu", "constitution", "minister", "parliament", "shall", "chapter", "assembly", "schedule"]',
            text,
            count=1,
        )
        text = re.sub(
            r'"""BM25 smoke for .*?"""',
            '"""BM25 smoke for Vanuatu IR — English legal corpus; years + English legal stems FTS gate.\n\n'
            "GATE is attested ASCII years plus English legal stems (ASCII-fold). URL www/gov.vu\n"
            "and parliament.gov.vu are query-only, never GATE. Every GATE token must rank a hit.\n"
            '"""',
            text,
            count=1,
            flags=re.S,
        )
        note = (
            f"attested years {GATE_NOTE_YEARS} plus English legal stems {GATE_NOTE_STEMS} "
            f"from articles.parquet HEAD tip {DST_TIP_SHORT}; URL www/gov.vu / parliament.gov.vu "
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

    if dst_name == "vanuatu_write_publish_report.py":
        gate_note = (
            f"BM25 PASS on Vanuatu ASCII-fold English GATE "
            f"(attested years {GATE_NOTE_YEARS} + stems {GATE_NOTE_STEMS}); "
            f"URL www/gov.vu / parliament.gov.vu is query-only, not GATE"
        )
        text = re.sub(
            r'BM25 PASS on Vanuatu[^"]*"',
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
        text = text.replace("www/gov.vu is query-only", "www/gov.vu / parliament.gov.vu is query-only")
        text = re.sub(
            r"HOLD 0 STRICT after-AW[^;]*; collectors kept dead \(pkill\); soft never-thin ON; SKIP_US; Italy BLOCKED;[^\"\n]*",
            f"{HOLD}; collectors kept dead (pkill); soft never-thin ON; SKIP_US; Italy BLOCKED; {WAVE_POS}",
            text,
        )
        text = re.sub(
            r"HOLD 0 STRICT after-VC[^;]*; collectors kept dead \(pkill\); soft never-thin ON; SKIP_US; Italy BLOCKED;[^\"\n]*",
            f"{HOLD}; collectors kept dead (pkill); soft never-thin ON; SKIP_US; Italy BLOCKED; {WAVE_POS}",
            text,
        )
        text = re.sub(r"[ \t]{2,}", " ", text)

    leftovers = (
        "Saint Vincent", "saint_vincent_grenadines", "grenadines", "vincent",
        "cient-data", "prent-data", "stent-data", "cvent-data", "scent-data",
        "carent-data", "yement-data", "djiboutient-data", "marshallislandsent-data",
        "kiribatient-data", "burundient-data", "eswatinient-data", "niueent-data",
        "guineabissauent-data", "surinameent-data", "equatorialguineaent-data",
        "guyanaent-data", "beninent-data", "somaliaent-data", "maldivesent-data",
        "gov.vc", "www.gov.vc",
    )
    found = []
    for x in leftovers:
        if x in ("vincent", "grenadines", "saint_vincent_grenadines"):
            if re.search(rf"(?<![A-Za-z0-9_]){re.escape(x)}(?![A-Za-z0-9_])", text):
                found.append(x)
            continue
        if x in text:
            found.append(x)
    if found:
        raise RuntimeError(f"language/country leftovers in {dst_name}: {found}")

    # Reject non-VU tokens in GATE; require English stems
    if dst_name.endswith("_bm25_smoke.py"):
        gate_slice = text[text.index("GATE = ["): text.index("]", text.index("GATE = [")) + 1]
        for bad in (
            "aruba", "artikel", "wet", "besluit", "landsverordening", "verordening",
            "koninkrijk", "regering", "persoon", "minister",
            "maldives", "maldivian", "ruling",
            "loi", "decret", "ordonnance", "republique", "benin", "gouvernement", "personne",
            "articulo", "ley", "decreto", "codigo", "seccion",
            "artigo", "lei", "suriname", "curacao", "guyana",
            "vincent", "grenadines", "saint_vincent",
        ):
            if f'"{bad}"' in gate_slice:
                raise RuntimeError(f"non-VU token in GATE of {dst_name}: {bad}")
        for stem in GATE_STEMS:
            if f'"{stem}"' not in gate_slice:
                raise RuntimeError(f"missing English stem in GATE of {dst_name}: {stem}")
        for year in GATE_YEARS:
            if f'"{year}"' not in gate_slice:
                raise RuntimeError(f"missing year in GATE of {dst_name}: {year}")
        if '", "vc"' in text or '", "VC"' in text:
            raise RuntimeError(f"leftover vc query token in {dst_name}")
        if "gov.vc" in text:
            raise RuntimeError(f"leftover gov.vc in {dst_name}")

    # reject bare saint_vincent / VC leftovers outside protected HOLD/wave
    scrub = text
    scrub = scrub.replace(WAVE_POS, "XX")
    scrub = scrub.replace(HOLD, "XX")
    scrub = scrub.replace(DEST_CHAIN, "XX")
    scrub = scrub.replace(SRC_CHAIN, "XX")
    scrub = scrub.replace(SRC_HOLD, "XX")
    scrub = scrub.replace(SRC_WAVE, "XX")
    scrub = scrub.replace("after-VC", "after-XX")
    scrub = scrub.replace("after VC ", "after XX ")
    scrub = scrub.replace("after_mv", "after_xx")
    scrub = scrub.replace("after_dj", "after_xx")
    scrub = scrub.replace("VC LIVE", "XX LIVE")
    scrub = scrub.replace("→VC ", "→XX ")
    scrub = scrub.replace("AW→VC→VU", "XX")
    scrub = scrub.replace("VC→VU", "XX")
    if re.search(r"(?<![A-Za-z0-9_])saint_vincent_grenadines(?![A-Za-z0-9_])", scrub):
        m = re.search(r"(?<![A-Za-z0-9_])saint_vincent_grenadines(?![A-Za-z0-9_])", scrub)
        raise RuntimeError(
            f"leftover saint_vincent_grenadines in {dst_name}: ...{scrub[max(0, m.start()-20):m.start()+20]}..."
        )
    if re.search(r"(?<![A-Za-z%])VC(?![A-Za-z])", scrub):
        m = re.search(r"(?<![A-Za-z%])VC(?![A-Za-z])", scrub)
        raise RuntimeError(
            f"leftover VC in {dst_name}: ...{scrub[max(0, m.start()-30):m.start()+30]}..."
        )
    if "ipfs_saint_vincent" in text:
        raise RuntimeError(f"leftover saint_vincent path in {dst_name}")
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
    # english language must remain for VU
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
    if entry.get("slug") == SLUG or entry.get("iso2") == "VU":
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
            "iso2": "VU",
            "slug": SLUG,
            "repo": "endomorphosis/ipfs_vanuatu_laws",
            "years_attested": YEARS_ATTESTED,
            "gate_years": [int(y) for y in GATE_YEARS],
            "gate_stems": GATE_STEMS,
            "note": (
                f"VU FIRST_IR scaffold; tip MATCH {DST_TIP_SHORT}@89/1062; {HOLD}; "
                f"soft never-thin ON; SKIP_US; Italy BLOCKED; {WAVE_POS}; "
                f"English GATE ({len(GATE_YEARS)} years + {len(GATE_STEMS)} stems); "
                f"do NOT start any next country"
            ),
            "status": "CLAIMED",
            "mode": "FIRST_IR",
            "wave_end": True,
            "do_not_start": False,
        })
        break
else:
    raise RuntimeError("Vanuatu / VU entry missing from wave JSON")

data["wave_status"] = "IN_PROGRESS_VU"
data["hold"] = HOLD
data["current"] = SLUG
data["do_not_start_next"] = None
data["next"] = None
data["hold_note"] = (
    "HOLD 0 STRICT for VU FIRST_IR WAVE END build in progress; collectors/deepeners dead; "
    "do NOT start any next country after VU LIVE"
)
wave.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print("updated wave JSON VU entry")
print("GATE years", GATE_YEARS)
print("GATE stems", GATE_STEMS)
print("n_gate", len(GATE_YEARS) + len(GATE_STEMS))
print("HOLD", HOLD)
print("GATE language: English years+stems")
print("WAVE END: true; next/do_not_start_next=null")
