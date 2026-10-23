#!/usr/bin/env python3
"""Adapt the Vanuatu English memsafe FIRST_IR pack to Ghana GH tip c19c1fb59bc2.

English (Ghana); FIRST_IR; HOLD 0 STRICT after-VU unlock (GH).
Soft never-thin ON; SKIP_US; Italy BLOCKED; KW HOLD_THIN leave alone.
GATE: attested years + English legal stems from data/articles.parquet
tip c19c1fb59bc2 (act/article/section/law/ordinance/code/republic/ghana/
government/person/order). URL gov.gh / parliament.gh query-only, NOT GATE.
Source tip 755173efca8c (Vanuatu English memsafe with data/ paths)
— keep language English (Ghana).
Keep data/articles.parquet + data/laws.parquet; agent-data not cient-data.
LARGE memsafe only (≥101/8572). Do NOT start any other country.
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
SRC_TIP_FULL = "755173efca8c3d23ab196666274d042cc6c2478d"
SRC_TIP_SHORT = "755173efca8c"
DST_TIP_FULL = "c19c1fb59bc2e749460093823acf99da8a5b0c35"
DST_TIP_SHORT = "c19c1fb59bc2"
FLOOR_LAWS, FLOOR_ARTS = 101, 8572
SRC_FLOOR_L, SRC_FLOOR_A = 89, 1062

# Sampled from data/articles.parquet @ c19c1fb59bc2 (~10 years + English stems)
# Whole-word ASCII-fold FTS hits; laws=101 articles=8572.
# Top years by doc hits in article body; English legal stems (+ ghana/ordinance).
GATE_YEARS = [
    "2020", "2018", "2019", "2013", "2014",
    "2015", "2017", "1963", "2003", "2023",
]
GATE_STEMS = [
    "act", "article", "section", "law", "ordinance", "code", "republic",
    "ghana", "government", "person", "order",
]
YEARS_ATTESTED = [int(y) for y in GATE_YEARS] + [
    2016, 2010, 2006, 1992, 1962, 2021, 2022, 2024, 2001, 2000,
]
GATE_NOTE_YEARS = "/".join(GATE_YEARS)
GATE_NOTE_STEMS = "/".join(GATE_STEMS)
HOLD = "HOLD 0 STRICT after-VU unlock (GH)"
WAVE_POS = (
    "first country of after_vu_unlock wave "
    "(GH FIRST_IR; soft-thin six + NG already LIVE — do not rebuild)"
)
DEST_CHAIN = "GH"
SRC_HOLD = "HOLD 0 STRICT after-VC (VU WAVE END)"
SRC_WAVE = (
    "WAVE END of after_mv wave "
    "(after AW LIVE → VC LIVE → VU)"
)
SRC_CHAIN = "VU WAVE END"

FILES = [
    ("vanuatu_soft_filter.py", "ghana_soft_filter.py"),
    (f"vanuatu_corpus_stream_{SRC_TIP_SHORT}.py", f"ghana_corpus_stream_{DST_TIP_SHORT}.py"),
    (f"vanuatu_encode_memsafe_{SRC_TIP_SHORT}.py", f"ghana_encode_memsafe_{DST_TIP_SHORT}.py"),
    (f"vanuatu_finish_from_emb_{SRC_TIP_SHORT}.py", f"ghana_finish_from_emb_{DST_TIP_SHORT}.py"),
    (f"vanuatu_stream_graph_parts_{SRC_TIP_SHORT}.py", f"ghana_stream_graph_parts_{DST_TIP_SHORT}.py"),
    (f"vanuatu_package_memsafe_{SRC_TIP_SHORT}.py", f"ghana_package_memsafe_{DST_TIP_SHORT}.py"),
    ("vanuatu_upload.py", "ghana_upload.py"),
    ("vanuatu_bm25_smoke.py", "ghana_bm25_smoke.py"),
    ("vanuatu_write_publish_report.py", "ghana_write_publish_report.py"),
    (f"vanuatu_orchestrator_{SRC_TIP_SHORT}.py", f"ghana_orchestrator_{DST_TIP_SHORT}.py"),
]

DISPLAY = "Ghana"
SLUG = "ghana"
SRC_DISPLAY = "Vanuatu"
SRC_SLUG = "vanuatu"


def adapt(text: str, dst_name: str) -> str:
    # Repair path corruption from prior adapts
    for bad in (
        "cient-data", "prent-data", "stent-data", "cvent-data", "scent-data",
        "carent-data", "yement-data", "djiboutient-data", "marshallislandsent-data",
        "kiribatient-data", "burundient-data", "eswatinient-data", "niueent-data",
        "guineabissauent-data", "surinameent-data", "equatorialguineaent-data",
        "guyanaent-data", "beninent-data", "somaliaent-data", "maldivesent-data",
        "arubaent-data", "saint_vincent_grenadinesent-data", "vanuatuent-data",
        "ghanaent-data",
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
    text = text.replace("after-VC", "\x00AFTERVU\x00")
    text = text.replace("after VC ", "\x00AFTERVU_SP\x00")
    text = text.replace("after_mv", "\x00AFTERMV_US\x00")
    text = text.replace("after_vu_unlock", "\x00AFTERVUUNLOCK_US\x00")
    text = text.replace("after_dj", "\x00AFTERDJ_US\x00")
    text = text.replace(
        "after AW LIVE → VC LIVE → VU",
        "\x00SRCCHAIN_FULL\x00",
    )
    text = text.replace("VU FIRST_IR", "\x00DESTFIRST\x00")
    text = text.replace("VU WAVE END", "\x00DESTCHAIN\x00")
    text = text.replace("do NOT start any next country", "\x00DONOTSTART\x00")
    text = text.replace("do NOT start any next", "\x00DONOTSTART2\x00")
    text = text.replace("WAVE END", "\x00WE\x00")

    # Protect UUID fragment before digit floor swaps (c94b must not become c86b)
    text = text.replace("67930c3f-c94b-445b-a5bc-01d3fc1135c1", "\x00UUID94\x00")

    reps = [
        (SRC_TIP_FULL, DST_TIP_FULL),
        (SRC_TIP_SHORT, DST_TIP_SHORT),
        ("endomorphosis/ipfs_vanuatu_laws", "endomorphosis/ipfs_ghana_laws"),
        ("justicedao/ipfs_vanuatu_laws_ir", "justicedao/ipfs_ghana_laws_ir"),
        ("ipfs_vanuatu_laws_ir", "ipfs_ghana_laws_ir"),
        ("ipfs_vanuatu_laws", "ipfs_ghana_laws"),
        # HOLD / wave restore
        ("\x00DESTHOLD\x00", HOLD),
        ("\x00DESTWAVE\x00", WAVE_POS),
        ("\x00DESTCHAIN\x00", DEST_CHAIN),
        ("\x00SRCCHAIN_FULL\x00", "after VU LIVE → GH"),
        ("\x00AFTERVU\x00", "after-VU"),
        ("\x00AFTERVU_SP\x00", "after VU "),
        ("\x00DESTFIRST\x00", "GH FIRST_IR"),
        ("\x00WE\x00", "FIRST_IR"),
        ("\x00DONOTSTART\x00", "do NOT start any other country"),
        ("\x00DONOTSTART2\x00", "do NOT start any other"),
        ("VU FIRST_IR (WAVE END)", "GH FIRST_IR"),
        ("VU FIRST_IR (not wave end)", "GH FIRST_IR"),
        # URLs
        ("www/gov.vu", "www/gov.gh"),
        ("gov.vu", "gov.gh"),
        ("www.gov.vu", "www.gov.gh"),
        ("parliament.gov.vu", "parliament.gh"),
        # Language / country — display name BEFORE slug
        ("English (Vanuatu)", "English (Ghana)"),
        ("English Vanuatu", "English Ghana"),
        ("Vanuatu", DISPLAY),
        # slug / path forms BEFORE bare vanuatu
        ("vanuatu_ranked", "ghana_ranked"),
        ("vanuatu_gate", "ghana_gate"),
        ("vanuatu_pass", "ghana_pass"),
        ("vanuatu_encode_memsafe", "ghana_encode_memsafe"),
        ("vanuatu_package_memsafe", "ghana_package_memsafe"),
        ("vanuatu_corpus_stream", "ghana_corpus_stream"),
        ("vanuatu_encode_done", "ghana_encode_done"),
        ("vanuatu_filtered_", "ghana_filtered_"),
        ("vanuatu_", "ghana_"),
        # ISO whole-token / path forms only (VU already protected in HOLD)
        ('"VU"', '"GH"'),
        ("VU-attested", "GH-attested"),
        ("(VU)", "(GH)"),
        ('"vu"', '"gh"'),
        # floors 89/1062 → 101/8572 — compound ONLY first
        ("89/1062", "101/8572"),
        ("89 / 1062", "101 / 8572"),
        ("89, 1062", "101, 8572"),
        ("FLOOR_LAWS, FLOOR_ARTS = 89, 1062", "FLOOR_LAWS, FLOOR_ARTS = 101, 8572"),
        ('int(pack.get("n_laws") or 89)', 'int(pack.get("n_laws") or 101)'),
        ('int(pack.get("n_articles") or 1062)', 'int(pack.get("n_articles") or 8572)'),
        ("@ 89/", "@ 101/"),
        ("floor 89/", "floor 101/"),
        ("(89/", "(101/"),
        (" 1062", " 8572"),
        ("1062", "8572"),
        ("= 89,", "= 101,"),
        ("or 89)", "or 101)"),
        ("89", "101"),
    ]
    for a, b in reps:
        text = text.replace(a, b)

    # Bare slug
    text = re.sub(
        r"(?<![A-Za-z0-9_])vanuatu(?![A-Za-z0-9_])",
        SLUG,
        text,
    )

    text = text.replace("\x00BM25\x00", "BM25").replace("\x00bm25\x00", "bm25")
    text = text.replace("\x00AFTERDJ_US\x00", "after_dj")
    text = text.replace("\x00AFTERMV_US\x00", "after_mv")
    text = text.replace("\x00AFTERVUUNLOCK_US\x00", "after_vu_unlock")
    text = text.replace("\x00DESTHOLD\x00", HOLD)
    text = text.replace("\x00DESTCHAIN\x00", DEST_CHAIN)
    text = text.replace("\x00DESTWAVE\x00", WAVE_POS)
    text = text.replace("\x00UUID94\x00", "67930c3f-c94b-445b-a5bc-01d3fc1135c1")

    # display name / slug fixes
    text = text.replace(f'"name": "{SLUG}"', f'"name": "{DISPLAY}"')
    text = text.replace(f'"slug": "{DISPLAY}"', f'"slug": "{SLUG}"')
    text = text.replace(f'SLUG = "{DISPLAY}"', f'SLUG = "{SLUG}"')
    text = text.replace(f'"country": "{DISPLAY}"', f'"country": "{SLUG}"')
    text = text.replace('"country": "vanuatu"', f'"country": "{SLUG}"')
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
        "ghanaent-data",
    ):
        text = text.replace(f"/home/box/{bad}/", "/home/box/agent-data/")
        text = text.replace(bad, "agent-data")

    if dst_name == "ghana_bm25_smoke.py":
        start = text.index("GATE = [")
        end = text.index("]", start) + 1
        years_line = ", ".join(f'"{y}"' for y in GATE_YEARS)
        stems_line = ", ".join(f'"{s}"' for s in GATE_STEMS)
        gate = f"GATE = [\n    {years_line},\n    {stems_line},\n]"
        text = text[:start] + gate + text[end:]
        text = re.sub(
            r"QUERIES = GATE \+ \[[^\]]*\]",
            'QUERIES = GATE + ["www", "gov.gh", "www.gov.gh", "parliament.gh", "www.parliament.gh", "constitution", "minister", "parliament", "shall", "chapter", "assembly", "schedule", "regulation", "bill"]',
            text,
            count=1,
        )
        text = re.sub(
            r'"""BM25 smoke for .*?"""',
            '"""BM25 smoke for Ghana IR — English legal corpus; years + English legal stems FTS gate.\n\n'
            "GATE is attested ASCII years plus English legal stems (ASCII-fold). URL www/gov.gh\n"
            "and parliament.gh are query-only, never GATE. Every GATE token must rank a hit.\n"
            '"""',
            text,
            count=1,
            flags=re.S,
        )
        note = (
            f"attested years {GATE_NOTE_YEARS} plus English legal stems {GATE_NOTE_STEMS} "
            f"from articles.parquet HEAD tip {DST_TIP_SHORT}; URL www/gov.gh / parliament.gh "
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

    if dst_name == "ghana_write_publish_report.py":
        gate_note = (
            f"BM25 PASS on Ghana ASCII-fold English GATE "
            f"(attested years {GATE_NOTE_YEARS} + stems {GATE_NOTE_STEMS}); "
            f"URL www/gov.gh / parliament.gh is query-only, not GATE"
        )
        text = re.sub(
            r'BM25 PASS on Ghana[^"]*"',
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
        text = text.replace("www/gov.gh is query-only", "www/gov.gh / parliament.gh is query-only")
        text = re.sub(
            r"HOLD 0 STRICT after-VC[^;]*; collectors kept dead \(pkill\); soft never-thin ON; SKIP_US; Italy BLOCKED;[^\"\n]*",
            f"{HOLD}; collectors kept dead (pkill); soft never-thin ON; SKIP_US; Italy BLOCKED; {WAVE_POS}",
            text,
        )
        text = re.sub(
            r"HOLD 0 STRICT after-VU[^;]*; collectors kept dead \(pkill\); soft never-thin ON; SKIP_US; Italy BLOCKED;[^\"\n]*",
            f"{HOLD}; collectors kept dead (pkill); soft never-thin ON; SKIP_US; Italy BLOCKED; {WAVE_POS}",
            text,
        )
        text = re.sub(r"[ \t]{2,}", " ", text)

    leftovers = (
        "Vanuatu", "vanuatu",
        "cient-data", "prent-data", "stent-data", "cvent-data", "scent-data",
        "carent-data", "yement-data", "djiboutient-data", "marshallislandsent-data",
        "kiribatient-data", "burundient-data", "eswatinient-data", "niueent-data",
        "guineabissauent-data", "surinameent-data", "equatorialguineaent-data",
        "guyanaent-data", "beninent-data", "somaliaent-data", "maldivesent-data",
        "gov.vu", "www.gov.vu",
    )
    found = []
    for x in leftovers:
        if x in ("vanuatu", "Vanuatu"):
            if re.search(rf"(?<![A-Za-z0-9_]){re.escape(x)}(?![A-Za-z0-9_])", text):
                found.append(x)
            continue
        if x in text:
            found.append(x)
    if found:
        raise RuntimeError(f"language/country leftovers in {dst_name}: {found}")

    # Reject non-GH tokens in GATE; require English stems
    if dst_name.endswith("_bm25_smoke.py"):
        gate_slice = text[text.index("GATE = ["): text.index("]", text.index("GATE = [")) + 1]
        for bad in (
            "aruba", "artikel", "wet", "besluit", "landsverordening", "verordening",
            "koninkrijk", "regering", "persoon", "minister",
            "maldives", "maldivian", "ruling",
            "loi", "decret", "ordonnance", "republique", "benin", "gouvernement", "personne",
            "articulo", "ley", "decreto", "codigo", "seccion",
            "artigo", "lei", "suriname", "curacao", "guyana",
            "vanuatu", "vincent", "grenadines",
            "regulation", "bill",  # query-only for GH; ordinance is GATE
        ):
            if f'"{bad}"' in gate_slice:
                raise RuntimeError(f"non-GH token in GATE of {dst_name}: {bad}")
        for stem in GATE_STEMS:
            if f'"{stem}"' not in gate_slice:
                raise RuntimeError(f"missing English stem in GATE of {dst_name}: {stem}")
        for year in GATE_YEARS:
            if f'"{year}"' not in gate_slice:
                raise RuntimeError(f"missing year in GATE of {dst_name}: {year}")
        if '", "vu"' in text or '", "VU"' in text:
            raise RuntimeError(f"leftover vu query token in {dst_name}")
        if "gov.vu" in text:
            raise RuntimeError(f"leftover gov.vu in {dst_name}")

    # reject bare vanuatu / VU leftovers outside protected HOLD/wave
    scrub = text
    scrub = scrub.replace(WAVE_POS, "XX")
    scrub = scrub.replace(HOLD, "XX")
    scrub = scrub.replace(DEST_CHAIN, "XX")
    scrub = scrub.replace(SRC_CHAIN, "XX")
    scrub = scrub.replace(SRC_HOLD, "XX")
    scrub = scrub.replace(SRC_WAVE, "XX")
    scrub = scrub.replace("after-VU", "after-XX")
    scrub = scrub.replace("after VU ", "after XX ")
    scrub = scrub.replace("after_mv", "after_xx")
    scrub = scrub.replace("after_vu_unlock", "after_xx")
    scrub = scrub.replace("after_dj", "after_xx")
    scrub = scrub.replace("VU LIVE", "XX LIVE")
    scrub = scrub.replace("→VU ", "→XX ")
    scrub = scrub.replace("AW→VC→VU", "XX")
    scrub = scrub.replace("VC→VU", "XX")
    if re.search(r"(?<![A-Za-z0-9_])vanuatu(?![A-Za-z0-9_])", scrub):
        m = re.search(r"(?<![A-Za-z0-9_])vanuatu(?![A-Za-z0-9_])", scrub)
        raise RuntimeError(
            f"leftover vanuatu in {dst_name}: ...{scrub[max(0, m.start()-20):m.start()+20]}..."
        )
    if re.search(r"(?<![A-Za-z%])VU(?![A-Za-z])", scrub):
        m = re.search(r"(?<![A-Za-z%])VU(?![A-Za-z])", scrub)
        raise RuntimeError(
            f"leftover VU in {dst_name}: ...{scrub[max(0, m.start()-30):m.start()+30]}..."
        )
    if "ipfs_vanuatu" in text:
        raise RuntimeError(f"leftover vanuatu path in {dst_name}")
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
    # english language must remain for GH
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

wave = Path("/workspace/country-law-triage/next_ir_ok_wave_after_vu_unlock.json")
data = json.loads(wave.read_text(encoding="utf-8"))
for entry in data["queue"]:
    if entry.get("slug") == SLUG or entry.get("iso2") == "GH":
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
            "iso2": "GH",
            "slug": SLUG,
            "repo": "endomorphosis/ipfs_ghana_laws",
            "years_attested": YEARS_ATTESTED,
            "gate_years": [int(y) for y in GATE_YEARS],
            "gate_stems": GATE_STEMS,
            "note": (
                f"GH FIRST_IR scaffold; tip MATCH {DST_TIP_SHORT}@101/8572; {HOLD}; "
                f"soft never-thin ON; SKIP_US; Italy BLOCKED; {WAVE_POS}; "
                f"English GATE ({len(GATE_YEARS)} years + {len(GATE_STEMS)} stems); "
                f"LARGE memsafe only; do NOT start any other country"
            ),
            "status": "CLAIMED",
            "mode": "FIRST_IR",
            "was_blocked": True,
            "wave_end": False,
            "do_not_start": False,
        })
        break
else:
    raise RuntimeError("Ghana / GH entry missing from wave JSON")

data["wave_status"] = "IN_PROGRESS_GH"
data["hold"] = HOLD
data["current"] = SLUG
data["do_not_start_next"] = None
data["next"] = None
data["hold_note"] = (
    "HOLD 0 STRICT for GH FIRST_IR build in progress; collectors/deepeners dead; "
    "do NOT start any other country; soft-thin six + NG already LIVE — leave alone; KW HOLD_THIN"
)
wave.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print("updated wave JSON GH entry")
print("GATE years", GATE_YEARS)
print("GATE stems", GATE_STEMS)
print("n_gate", len(GATE_YEARS) + len(GATE_STEMS))
print("HOLD", HOLD)
print("GATE language: English years+stems")
print("LARGE memsafe: 101/8572; only GH")
