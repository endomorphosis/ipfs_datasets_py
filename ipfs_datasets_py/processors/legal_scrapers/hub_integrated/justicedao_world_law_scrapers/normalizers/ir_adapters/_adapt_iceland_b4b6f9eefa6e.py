#!/usr/bin/env python3
"""Adapt Ghana English LARGE memsafe FIRST_IR pack to Iceland IS tip b4b6f9eefa6e.

RECONFIRM_FINAL (NOT soft-thin); floor ≥917/23768. Icelandic corpus (lang=is);
BM25 ASCII-fold GATE from attested years + Icelandic ASCII stems (þ/ð strip).
URL www.althingi.is query-only. HOLD 0 STRICT wave2 TENTH/LAST after DZ…MM LIVE.
Soft never-thin ON (IS is RECONFIRM not soft-thin exception); SKIP_US; Italy LIVE
leave alone; KW HOLD_THIN; AT queued-only; P1 CLOSED. Do NOT rebuild priors.
Do NOT start Austria or any other country.
CRITICAL: protect tip SHA during floor digit replaces; FIRST_IR→RECONFIRM_FINAL
before ISO swaps; LARGE memsafe from Ghana (101/8572) NOT soft-thin packs.
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
SRC_TIP_FULL = "c19c1fb59bc2e749460093823acf99da8a5b0c35"
SRC_TIP_SHORT = "c19c1fb59bc2"
DST_TIP_FULL = "b4b6f9eefa6e55700542280294699bb06b94de44"
DST_TIP_SHORT = "b4b6f9eefa6e"
FLOOR_LAWS, FLOOR_ARTS = 917, 23768
SRC_FLOOR_L, SRC_FLOOR_A = 101, 8572

# Sampled articles.parquet @ b4b6f9eefa6e — ASCII tokens survive BM25 [0-9A-Za-z]+
# (Icelandic þ/ð/ö strip). Years by doc hits; stems legal ASCII survivors.
GATE_YEARS = [
    "2021", "2024", "2022", "2025", "2019",
    "2023", "2011", "2010", "2020", "2013",
]
GATE_STEMS = [
    "laga", "grein", "skal", "skulu", "regluger",
    "heimilt", "samkv", "mgr", "sbr", "fyrir", "eftir",
]
YEARS_ATTESTED = [int(y) for y in GATE_YEARS] + [
    2018, 2015, 2014, 2009, 2003, 2017, 2016, 2007, 2012, 1944,
]
GATE_NOTE_YEARS = "/".join(GATE_YEARS)
GATE_NOTE_STEMS = "/".join(GATE_STEMS)
HOLD = "HOLD 0 STRICT wave2 after MM LIVE (IS)"
WAVE_POS = (
    "TENTH/LAST of wave2 after GH EMPTY "
    "(IS RECONFIRM_FINAL after DZ+MC+SK+HR+TH+SD+LB+FM+MM LIVE — WAVE END; do NOT start Austria)"
)
DEST_CHAIN = "IS"
SRC_HOLD = "HOLD 0 STRICT after-VU unlock (GH)"
SRC_WAVE = (
    "first country of after_vu_unlock wave "
    "(GH FIRST_IR; soft-thin six + NG already LIVE — do not rebuild)"
)

FILES = [
    ("ghana_soft_filter.py", "iceland_soft_filter.py"),
    (f"ghana_corpus_stream_{SRC_TIP_SHORT}.py", f"iceland_corpus_stream_{DST_TIP_SHORT}.py"),
    (f"ghana_encode_memsafe_{SRC_TIP_SHORT}.py", f"iceland_encode_memsafe_{DST_TIP_SHORT}.py"),
    (f"ghana_finish_from_emb_{SRC_TIP_SHORT}.py", f"iceland_finish_from_emb_{DST_TIP_SHORT}.py"),
    (f"ghana_stream_graph_parts_{SRC_TIP_SHORT}.py", f"iceland_stream_graph_parts_{DST_TIP_SHORT}.py"),
    (f"ghana_package_memsafe_{SRC_TIP_SHORT}.py", f"iceland_package_memsafe_{DST_TIP_SHORT}.py"),
    ("ghana_upload.py", "iceland_upload.py"),
    ("ghana_bm25_smoke.py", "iceland_bm25_smoke.py"),
    ("ghana_write_publish_report.py", "iceland_write_publish_report.py"),
    (f"ghana_orchestrator_{SRC_TIP_SHORT}.py", f"iceland_orchestrator_{DST_TIP_SHORT}.py"),
]

DISPLAY = "Iceland"
SLUG = "iceland"
SRC_DISPLAY = "Ghana"
SRC_SLUG = "ghana"


def adapt(text: str, dst_name: str) -> str:
    for bad in (
        "cient-data", "prent-data", "stent-data", "cvent-data", "scent-data",
        "carent-data", "yement-data", "ghanaent-data", "icelandent-data",
        "vanuatuent-data",
    ):
        text = text.replace(f"/home/box/{bad}/", "/home/box/agent-data/")
        text = text.replace(bad, "agent-data")

    text = text.replace("BM25", "\x00BM25\x00").replace("bm25", "\x00bm25\x00")
    text = text.replace("bmjacency", "adjacency")

    # Protect mode tokens BEFORE ISO/slug swaps
    text = text.replace("RECONFIRM_FINAL", "\x00DESTMODE\x00")
    text = text.replace("FIRST_IR", "\x00DESTMODE\x00")
    text = text.replace("SOFT_THIN_FINAL", "\x00SOFTMODE_KEEP\x00")  # should not appear; park if any

    text = text.replace(SRC_HOLD, "\x00DESTHOLD\x00")
    text = text.replace(SRC_WAVE, "\x00DESTWAVE\x00")
    text = text.replace(HOLD, "\x00DESTHOLD\x00")
    text = text.replace(WAVE_POS, "\x00DESTWAVE\x00")
    text = text.replace(DEST_CHAIN, "\x00DESTCHAIN\x00")
    text = text.replace("after-VU", "\x00AFTERVU\x00")
    text = text.replace("after VU ", "\x00AFTERVU_SP\x00")
    text = text.replace("after_vu_unlock", "\x00AFTERVUUNLOCK_US\x00")
    text = text.replace("after_mv", "\x00AFTERMV_US\x00")
    text = text.replace("soft-thin six + NG already LIVE — do not rebuild", "\x00SOFTSIX\x00")
    text = text.replace("do NOT start any other country", "\x00DONOTSTART\x00")
    text = text.replace("do NOT start any other", "\x00DONOTSTART2\x00")
    text = text.replace("WAVE END", "\x00WE\x00")
    text = text.replace("Italy BLOCKED", "\x00ITALY\x00")
    text = text.replace("67930c3f-c94b-445b-a5bc-01d3fc1135c1", "\x00UUID94\x00")

    # Tip swaps THEN protect tip SHA before any digit floor swaps
    text = text.replace(SRC_TIP_FULL, DST_TIP_FULL)
    text = text.replace(SRC_TIP_SHORT, DST_TIP_SHORT)
    text = text.replace(DST_TIP_FULL, "\x00TIPSHA_PROTECT\x00")
    text = text.replace(DST_TIP_SHORT, "\x00TIPSHORT_PROTECT\x00")

    # Floor 101/8572 → 917/23768 via placeholders (avoid tip digit collisions)
    text = text.replace("101/8572", "\x00FLOOR_LA\x00")
    text = text.replace("101 / 8572", "\x00FLOOR_LA_SP\x00")
    text = text.replace("101, 8572", "\x00FLOOR_LA_C\x00")
    text = text.replace("FLOOR_LAWS, FLOOR_ARTS = 101, 8572", "\x00FLOOR_ASSIGN\x00")
    text = text.replace('int(pack.get("n_laws") or 101)', "\x00OR_LAWS\x00")
    text = text.replace('int(pack.get("n_articles") or 8572)', "\x00OR_ARTS\x00")
    text = text.replace("or 101)", "\x00OR_LAWS_PAREN\x00")
    text = text.replace("or 8572)", "\x00OR_ARTS_PAREN\x00")
    text = text.replace("@ 101/", "\x00AT_LAWS\x00")
    text = text.replace("floor 101/", "\x00FLOOR_SLASH\x00")
    text = text.replace("(101/", "\x00PAREN_LAWS\x00")
    text = text.replace("= 101,", "\x00EQ_LAWS\x00")
    text = text.replace(" 8572", "\x00ARTS\x00")
    text = text.replace("8572", "\x00ARTS\x00")
    text = text.replace(" 101", "\x00LAWS\x00")
    text = text.replace("101", "\x00LAWS\x00")
    text = text.replace("\x00FLOOR_LA\x00", "917/23768")
    text = text.replace("\x00FLOOR_LA_SP\x00", "917 / 23768")
    text = text.replace("\x00FLOOR_LA_C\x00", "917, 23768")
    text = text.replace("\x00FLOOR_ASSIGN\x00", "FLOOR_LAWS, FLOOR_ARTS = 917, 23768")
    text = text.replace("\x00OR_LAWS\x00", 'int(pack.get("n_laws") or 917)')
    text = text.replace("\x00OR_ARTS\x00", 'int(pack.get("n_articles") or 23768)')
    text = text.replace("\x00OR_LAWS_PAREN\x00", "or 917)")
    text = text.replace("\x00OR_ARTS_PAREN\x00", "or 23768)")
    text = text.replace("\x00AT_LAWS\x00", "@ 917/")
    text = text.replace("\x00FLOOR_SLASH\x00", "floor 917/")
    text = text.replace("\x00PAREN_LAWS\x00", "(917/")
    text = text.replace("\x00EQ_LAWS\x00", "= 917,")
    text = text.replace("\x00ARTS\x00", "23768")
    text = text.replace("\x00LAWS\x00", "917")

    reps = [
        ("endomorphosis/ipfs_ghana_laws", "endomorphosis/ipfs_iceland_laws"),
        ("justicedao/ipfs_ghana_laws_ir", "justicedao/ipfs_iceland_laws_ir"),
        ("ipfs_ghana_laws_ir", "ipfs_iceland_laws_ir"),
        ("ipfs_ghana_laws", "ipfs_iceland_laws"),
        ("\x00DESTHOLD\x00", HOLD),
        ("\x00DESTWAVE\x00", WAVE_POS),
        ("\x00DESTCHAIN\x00", DEST_CHAIN),
        ("\x00DESTMODE\x00", "RECONFIRM_FINAL"),
        ("\x00SOFTMODE_KEEP\x00", "SOFT_THIN_FINAL"),
        ("\x00AFTERVU\x00", "after-MM"),
        ("\x00AFTERVU_SP\x00", "after MM "),
        ("\x00AFTERVUUNLOCK_US\x00", "after_mm_wave2"),
        ("\x00AFTERMV_US\x00", "after_mv"),
        ("\x00SOFTSIX\x00", "priors DZ…MM LIVE leave alone — WAVE END"),
        ("\x00WE\x00", "WAVE END"),
        ("\x00DONOTSTART\x00", "do NOT start Austria or any other country"),
        ("\x00DONOTSTART2\x00", "do NOT start Austria or any other"),
        ("\x00ITALY\x00", "Italy LIVE leave alone"),
        # URLs
        ("www/gov.gh", "www/althingi.is"),
        ("parliament.gh", "althingi.is"),
        ("www.parliament.gh", "www.althingi.is"),
        ("www.gov.gh", "www.althingi.is"),
        ("gov.gh", "althingi.is"),
        # Language / country — display BEFORE slug
        ("English (Ghana)", "Icelandic (Iceland)"),
        ("English Ghana", "Icelandic Iceland"),
        ("English legal", "Icelandic ASCII-fold legal"),
        ("ASCII-fold English", "ASCII-fold Icelandic"),
        ("Ghana", DISPLAY),
        ("ghana_ranked", "iceland_ranked"),
        ("ghana_gate", "iceland_gate"),
        ("ghana_pass", "iceland_pass"),
        ("ghana_encode_memsafe", "iceland_encode_memsafe"),
        ("ghana_package_memsafe", "iceland_package_memsafe"),
        ("ghana_corpus_stream", "iceland_corpus_stream"),
        ("ghana_encode_done", "iceland_encode_done"),
        ("ghana_filtered_", "iceland_filtered_"),
        ("ghana_", "iceland_"),
        # ISO whole-token only (never bare English "is")
        ('"GH"', '"IS"'),
        ("GH-attested", "IS-attested"),
        ("(GH)", "(IS)"),
        ('"gh"', '"is"'),
        (" GH ", " IS "),
        (" GH;", " IS;"),
        (" GH.", " IS."),
        ("GH FIRST_IR", "IS RECONFIRM_FINAL"),
        ("GH RECONFIRM_FINAL", "IS RECONFIRM_FINAL"),
    ]
    for a, b in reps:
        text = text.replace(a, b)

    text = re.sub(r"(?<![A-Za-z0-9_])ghana(?![A-Za-z0-9_])", SLUG, text)

    text = text.replace("\x00BM25\x00", "BM25").replace("\x00bm25\x00", "bm25")
    text = text.replace("\x00TIPSHA_PROTECT\x00", DST_TIP_FULL)
    text = text.replace("\x00TIPSHORT_PROTECT\x00", DST_TIP_SHORT)
    text = text.replace("\x00UUID94\x00", "67930c3f-c94b-445b-a5bc-01d3fc1135c1")
    text = text.replace("\x00DESTHOLD\x00", HOLD)
    text = text.replace("\x00DESTCHAIN\x00", DEST_CHAIN)
    text = text.replace("\x00DESTWAVE\x00", WAVE_POS)
    text = text.replace("\x00DESTMODE\x00", "RECONFIRM_FINAL")

    text = text.replace(f'"name": "{SLUG}"', f'"name": "{DISPLAY}"')
    text = text.replace(f'"slug": "{DISPLAY}"', f'"slug": "{SLUG}"')
    text = text.replace(f'SLUG = "{DISPLAY}"', f'SLUG = "{SLUG}"')
    text = text.replace(f'"country": "{DISPLAY}"', f'"country": "{SLUG}"')
    text = text.replace('"country": "ghana"', f'"country": "{SLUG}"')
    text = text.replace(f"# {SLUG} filtered pack", f"# {DISPLAY} filtered pack")
    text = text.replace(f"{SLUG} laws IR release", f"{DISPLAY} laws IR release")

    for bad in (
        "cient-data", "prent-data", "ghanaent-data", "icelandent-data", "vanuatuent-data",
    ):
        text = text.replace(f"/home/box/{bad}/", "/home/box/agent-data/")
        text = text.replace(bad, "agent-data")

    if dst_name == "iceland_bm25_smoke.py":
        start = text.index("GATE = [")
        end = text.index("]", start) + 1
        years_line = ", ".join(f'"{y}"' for y in GATE_YEARS)
        stems_line = ", ".join(f'"{s}"' for s in GATE_STEMS)
        gate = f"GATE = [\n    {years_line},\n    {stems_line},\n]"
        text = text[:start] + gate + text[end:]
        text = re.sub(
            r"QUERIES = GATE \+ \[[^\]]*\]",
            'QUERIES = GATE + ["www", "althingi.is", "www.althingi.is", "althingi", "island", "reykjavik", "stjorn", "raduneyti", "logum", "greinar"]',
            text,
            count=1,
        )
        text = re.sub(
            r'"""BM25 smoke for .*?"""',
            '"""BM25 smoke for Iceland IR — Icelandic legal corpus; years + Icelandic ASCII stems FTS gate.\n\n'
            "GATE is attested ASCII years plus Icelandic ASCII-fold stems (þ/ð stripped). URL\n"
            "www.althingi.is is query-only, never GATE. Every GATE token must rank a hit.\n"
            '"""',
            text,
            count=1,
            flags=re.S,
        )
        note = (
            f"attested years {GATE_NOTE_YEARS} plus Icelandic ASCII stems {GATE_NOTE_STEMS} "
            f"from articles.parquet HEAD tip {DST_TIP_SHORT}; URL www.althingi.is "
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

    if dst_name == "iceland_write_publish_report.py":
        gate_note = (
            f"BM25 PASS on Iceland ASCII-fold Icelandic GATE "
            f"(attested years {GATE_NOTE_YEARS} + stems {GATE_NOTE_STEMS}); "
            f"URL www.althingi.is is query-only, not GATE"
        )
        text = re.sub(
            r'BM25 PASS on Iceland[^"]*"',
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
        text = re.sub(
            r"HOLD 0 STRICT[^;]*; collectors kept dead \(pkill\); soft never-thin ON; SKIP_US; Italy[^\"\n]*",
            f"{HOLD}; collectors kept dead (pkill); soft never-thin ON; SKIP_US; Italy LIVE leave alone; {WAVE_POS}",
            text,
        )
        text = re.sub(r"[ \t]{2,}", " ", text)

    if dst_name == "iceland_soft_filter.py":
        text = text.replace(
            "Copy tip pack through with floor checks only (RECONFIRM_FINAL).",
            "Copy tip pack through with floor checks only (RECONFIRM_FINAL).",
        )
        text = text.replace(
            "Copy tip pack through with floor checks only (FIRST_IR).",
            "Copy tip pack through with floor checks only (RECONFIRM_FINAL).",
        )

    leftovers = (
        "Ghana", "ghana",
        "cient-data", "gov.gh", "www.gov.gh", "parliament.gh",
    )
    found = []
    for x in leftovers:
        if x in ("ghana", "Ghana"):
            if re.search(rf"(?<![A-Za-z0-9_]){re.escape(x)}(?![A-Za-z0-9_])", text):
                found.append(x)
            continue
        if x in text:
            found.append(x)
    if found:
        raise RuntimeError(f"language/country leftovers in {dst_name}: {found}")

    if dst_name.endswith("_bm25_smoke.py"):
        gate_slice = text[text.index("GATE = ["): text.index("]", text.index("GATE = [")) + 1]
        for bad in (
            "ghana", "ordinance", "republic", "government", "person", "order",
            "act", "article", "section", "law", "code",  # English GH stems — not IS GATE
            "shall", "loi", "decret", "aruba", "vanuatu",
        ):
            if f'"{bad}"' in gate_slice:
                raise RuntimeError(f"non-IS token in GATE of {dst_name}: {bad}")
        for stem in GATE_STEMS:
            if f'"{stem}"' not in gate_slice:
                raise RuntimeError(f"missing Icelandic stem in GATE of {dst_name}: {stem}")
        for year in GATE_YEARS:
            if f'"{year}"' not in gate_slice:
                raise RuntimeError(f"missing year in GATE of {dst_name}: {year}")
        if "gov.gh" in text:
            raise RuntimeError(f"leftover gov.gh in {dst_name}")

    scrub = text
    scrub = scrub.replace(WAVE_POS, "XX")
    scrub = scrub.replace(HOLD, "XX")
    scrub = scrub.replace(DEST_CHAIN, "XX")
    scrub = scrub.replace("after-MM", "after-XX")
    scrub = scrub.replace("after MM ", "after XX ")
    scrub = scrub.replace("after_mm_wave2", "after_xx")
    scrub = scrub.replace("MM LIVE", "XX LIVE")
    scrub = scrub.replace("RECONFIRM_FINAL", "XX")
    if re.search(r"(?<![A-Za-z0-9_])ghana(?![A-Za-z0-9_])", scrub):
        m = re.search(r"(?<![A-Za-z0-9_])ghana(?![A-Za-z0-9_])", scrub)
        raise RuntimeError(
            f"leftover ghana in {dst_name}: ...{scrub[max(0, m.start()-20):m.start()+20]}..."
        )
    if re.search(r"(?<![A-Za-z%])GH(?![A-Za-z])", scrub):
        m = re.search(r"(?<![A-Za-z%])GH(?![A-Za-z])", scrub)
        raise RuntimeError(
            f"leftover GH in {dst_name}: ...{scrub[max(0, m.start()-30):m.start()+30]}..."
        )
    if "ipfs_ghana" in text:
        raise RuntimeError(f"leftover ghana path in {dst_name}")
    if SRC_TIP_SHORT in text:
        raise RuntimeError(f"src tip leftover in {dst_name}")
    if "67930c3f-c86b-" in text:
        raise RuntimeError(f"UUID c94b corrupted to c86b in {dst_name}")
    if DST_TIP_SHORT not in text and any(
        x in dst_name for x in ("soft_filter", "orchestrator", "bm25_smoke")
    ):
        raise RuntimeError(f"missing DST tip in {dst_name}")
    # tip integrity: full tip must be intact wherever short appears in tip-bearing files
    if DST_TIP_FULL in text:
        # ensure no digit corruption of tip
        if DST_TIP_FULL.replace("917", "XXX") != DST_TIP_FULL:  # tip has no 917
            pass
        corrupt = re.findall(rf"{DST_TIP_SHORT[:8]}[0-9a-f]{{4,}}", text)
        for c in corrupt:
            if c != DST_TIP_FULL and c != DST_TIP_SHORT and len(c) > 12:
                if not c.startswith(DST_TIP_SHORT):
                    raise RuntimeError(f"suspicious tip fragment in {dst_name}: {c}")
                if c != DST_TIP_FULL and len(c) == 40:
                    raise RuntimeError(f"corrupted tip SHA in {dst_name}: {c}")
    if "soft_filter" in dst_name or "corpus_stream" in dst_name:
        if "data/laws.parquet" not in text and 'data" / "laws.parquet"' not in text:
            if '"data"' not in text and "/data/" not in text:
                raise RuntimeError(f"missing data/ parquet paths in {dst_name}")
    if "\x00" in text:
        raise RuntimeError(f"null placeholder leftover in {dst_name}")
    return text


for src_name, dst_name in FILES:
    src = ROOT / src_name
    if not src.is_file():
        raise FileNotFoundError(src)
    (ROOT / dst_name).write_text(
        adapt(src.read_text(encoding="utf-8"), dst_name), encoding="utf-8"
    )
    print(f"wrote {dst_name}")

# Update wave JSON
wave = Path("/workspace/next_ir_ok_wave_after_gh_wave2.json")
data = json.loads(wave.read_text(encoding="utf-8"))
for entry in data["queue"]:
    if entry.get("slug") == SLUG or entry.get("iso2") == "IS":
        entry.update({
            "tip": DST_TIP_SHORT,
            "tip_full": DST_TIP_FULL,
            "laws": FLOOR_LAWS,
            "articles": FLOOR_ARTS,
            "floor_laws": FLOOR_LAWS,
            "floor_articles": FLOOR_ARTS,
            "claim_tip": DST_TIP_SHORT,
            "match_claim": True,
            "ir_hub_head": "1fad37194d42",
            "label": "EXPAND",
            "soft_thin": False,
            "soft_never_thin": True,
            "skip_us": True,
            "italy_live_leave_alone": True,
            "language": "Icelandic",
            "lang": "Icelandic",
            "iso2": "IS",
            "slug": SLUG,
            "repo": "endomorphosis/ipfs_iceland_laws",
            "years_attested": YEARS_ATTESTED,
            "gate_years": [int(y) for y in GATE_YEARS],
            "gate_stems": GATE_STEMS,
            "note": (
                f"IS RECONFIRM_FINAL scaffold; tip MATCH {DST_TIP_SHORT}@917/23768; {HOLD}; "
                f"soft never-thin ON (RECONFIRM not soft-thin); SKIP_US; Italy LIVE leave alone; "
                f"{WAVE_POS}; Icelandic ASCII GATE ({len(GATE_YEARS)} years + {len(GATE_STEMS)} stems); "
                f"LARGE memsafe only; do NOT start Austria or any other country"
            ),
            "status": "CLAIMED",
            "mode": "RECONFIRM_FINAL",
            "wave_end": True,
            "do_not_start": False,
        })
        break
else:
    raise RuntimeError("Iceland / IS entry missing from wave JSON")

data["wave_status"] = "IN_PROGRESS_IS"
data["hold"] = HOLD
data["current"] = SLUG
data["do_not_start_next"] = None
data["next"] = None
data["hold_note"] = (
    "HOLD 0 STRICT for IS RECONFIRM_FINAL build in progress (wave2 LAST); "
    "do NOT start Austria or any other country; priors DZ…MM LIVE leave alone"
)
wave.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
triage = Path("/workspace/country-law-triage/next_ir_ok_wave_after_gh_wave2.json")
triage.write_text(wave.read_text(encoding="utf-8"), encoding="utf-8")
print("updated wave JSON IS entry")
print("GATE years", GATE_YEARS)
print("GATE stems", GATE_STEMS)
print("n_gate", len(GATE_YEARS) + len(GATE_STEMS))
print("HOLD", HOLD)
print("LARGE memsafe: 917/23768; RECONFIRM_FINAL; only IS")
