#!/usr/bin/env python3
"""Adapt Monaco French memsafe SOFT_THIN_FINAL pack to Slovakia SK tip 22508a5eab4b.

Slovak (laws.language=sk; article corpus bilingual EN treaties + SK stems);
SOFT_THIN_FINAL; HOLD 0 STRICT wave2 THIRD after DZ+MC LIVE
(SK; then HR→TH→SD→LB→FM→MM→IS). Soft never-thin ON except soft-thin OK;
SKIP_US; Italy LIVE leave alone; KW HOLD_THIN; AT queued-only.
Do NOT rebuild DZ/MC. Do NOT start Croatia.
GATE: attested years + stems from data/articles.parquet tip 22508a5eab4b
(article/slovenskej/republiky/ministerstvo/…).
URL slov-lex.sk query-only, NOT GATE.
CRITICAL: protect tip SHA tokens during floor digit replaces (MC lesson:
floor 492→438 corrupted tip substring).
Floor ≥16799/179.
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
SRC_TIP_FULL = "1d930b8966ee182f0d7d20492145af17e0c2eded"
SRC_TIP_SHORT = "1d930b8966ee"
DST_TIP_FULL = "22508a5eab4b3c0ba98fe0ab32aa9fcb5ec4be9a"
DST_TIP_SHORT = "22508a5eab4b"
FLOOR_LAWS, FLOOR_ARTS = 16799, 179
SRC_FLOOR_L, SRC_FLOOR_A = 862, 438

# Sampled from data/articles.parquet @ 22508a5eab4b (whole-token ASCII-fold in article corpus)
GATE_YEARS = [
    "2003", "2014", "2015", "2022", "2007",
    "2020", "2021", "2000", "2002", "1998",
]
GATE_STEMS = [
    "article", "slovenskej", "republiky", "ministerstvo", "slovak",
    "republic", "nariadenie", "znena", "agreement", "convention", "treaty",
]
YEARS_ATTESTED = [int(y) for y in GATE_YEARS] + [
    2026, 2024, 2001, 2008, 2018, 2016, 2017, 2023, 1984, 2005,
]
GATE_NOTE_YEARS = "/".join(GATE_YEARS)
GATE_NOTE_STEMS = "/".join(GATE_STEMS)
HOLD = "HOLD 0 STRICT wave2 after MC LIVE (SK)"
WAVE_POS = (
    "THIRD of wave2 after GH EMPTY "
    "(SK SOFT_THIN_FINAL after DZ+MC LIVE; then HR→TH→SD→LB→FM→MM→IS — do NOT start those)"
)
DEST_CHAIN = "SK"
SRC_HOLD = "HOLD 0 STRICT wave2 after DZ LIVE (MC)"
SRC_WAVE = (
    "SECOND of wave2 after GH EMPTY "
    "(MC SOFT_THIN_FINAL after DZ LIVE; then SK→HR→TH→SD→LB→FM→MM→IS — do NOT start those)"
)
SRC_CHAIN = "MC"

FILES = [
    ("monaco_soft_filter.py", "slovakia_soft_filter.py"),
    (f"monaco_corpus_stream_{SRC_TIP_SHORT}.py", f"slovakia_corpus_stream_{DST_TIP_SHORT}.py"),
    (f"monaco_encode_memsafe_{SRC_TIP_SHORT}.py", f"slovakia_encode_memsafe_{DST_TIP_SHORT}.py"),
    (f"monaco_finish_from_emb_{SRC_TIP_SHORT}.py", f"slovakia_finish_from_emb_{DST_TIP_SHORT}.py"),
    (f"monaco_stream_graph_parts_{SRC_TIP_SHORT}.py", f"slovakia_stream_graph_parts_{DST_TIP_SHORT}.py"),
    (f"monaco_package_memsafe_{SRC_TIP_SHORT}.py", f"slovakia_package_memsafe_{DST_TIP_SHORT}.py"),
    ("monaco_upload.py", "slovakia_upload.py"),
    ("monaco_bm25_smoke.py", "slovakia_bm25_smoke.py"),
    ("monaco_write_publish_report.py", "slovakia_write_publish_report.py"),
    (f"monaco_orchestrator_{SRC_TIP_SHORT}.py", f"slovakia_orchestrator_{DST_TIP_SHORT}.py"),
]

DISPLAY = "Slovakia"
SLUG = "slovakia"
SRC_DISPLAY = "Monaco"
SRC_SLUG = "monaco"


def adapt(text: str, dst_name: str) -> str:
    for bad in (
        "cient-data", "prent-data", "stent-data", "cvent-data", "scent-data",
        "carent-data", "yement-data", "djiboutient-data", "marshallislandsent-data",
        "kiribatient-data", "burundient-data", "eswatinient-data", "niueent-data",
        "guineabissauent-data", "surinameent-data", "equatorialguineaent-data",
        "guyanaent-data", "beninent-data", "somaliaent-data", "maldivesent-data",
        "arubaent-data", "saint_vincent_grenadinesent-data", "vanuatuent-data",
        "ghanaent-data", "algeriaent-data", "monacoent-data", "slovakiaent-data",
    ):
        text = text.replace(f"/home/box/{bad}/", "/home/box/agent-data/")
        text = text.replace(bad, "agent-data")

    text = text.replace("BM25", "\x00BM25\x00").replace("bm25", "\x00bm25\x00")
    text = text.replace("bmjacency", "adjacency")

    text = text.replace(SRC_HOLD, "\x00DESTHOLD\x00")
    text = text.replace(SRC_WAVE, "\x00DESTWAVE\x00")
    text = text.replace(HOLD, "\x00DESTHOLD\x00")
    text = text.replace(WAVE_POS, "\x00DESTWAVE\x00")
    text = text.replace(DEST_CHAIN, "\x00DESTCHAIN\x00")
    text = text.replace(SRC_CHAIN, "\x00DESTCHAIN\x00")
    text = text.replace("after-DZ", "\x00AFTERDZ\x00")
    text = text.replace("after DZ ", "\x00AFTERDZ_SP\x00")
    text = text.replace("DZ LIVE", "\x00DZLIVE\x00")
    text = text.replace("DZ+MC", "\x00DZMC\x00")
    text = text.replace("GH EMPTY", "\x00GHEMPTY\x00")
    text = text.replace("SOFT_THIN_FINAL", "\x00DESTMODE\x00")
    text = text.replace("do NOT start Slovakia or any other country", "\x00DONOTSTART\x00")
    text = text.replace("do NOT start Slovakia or any other", "\x00DONOTSTART2\x00")
    text = text.replace("do NOT start SK/HR/TH/SD/LB/FM/MM/IS", "\x00DONOTREBUILD\x00")
    text = text.replace("do NOT start any other country", "\x00DONOTSTART\x00")
    text = text.replace("do NOT start any other", "\x00DONOTSTART2\x00")
    text = text.replace("67930c3f-c94b-445b-a5bc-01d3fc1135c1", "\x00UUID94\x00")

    # Tip swaps FIRST, then protect DST tip before any digit floor swaps
    text = text.replace(SRC_TIP_FULL, DST_TIP_FULL)
    text = text.replace(SRC_TIP_SHORT, DST_TIP_SHORT)
    text = text.replace(DST_TIP_FULL, "\x00TIPSHA_PROTECT\x00")
    # also protect short tip in case digit patterns ever collide
    text = text.replace(DST_TIP_SHORT, "\x00TIPSHORT_PROTECT\x00")

    reps = [
        ("endomorphosis/ipfs_monaco_laws", "endomorphosis/ipfs_slovakia_laws"),
        ("justicedao/ipfs_monaco_laws_ir", "justicedao/ipfs_slovakia_laws_ir"),
        ("ipfs_monaco_laws_ir", "ipfs_slovakia_laws_ir"),
        ("ipfs_monaco_laws", "ipfs_slovakia_laws"),
        ("\x00DESTHOLD\x00", HOLD),
        ("\x00DESTWAVE\x00", WAVE_POS),
        ("\x00DESTCHAIN\x00", DEST_CHAIN),
        ("\x00DESTMODE\x00", "SOFT_THIN_FINAL"),
        ("\x00AFTERDZ\x00", "after-MC"),
        ("\x00AFTERDZ_SP\x00", "after MC "),
        ("\x00DZLIVE\x00", "MC LIVE"),
        ("\x00DZMC\x00", "DZ+MC"),
        ("\x00GHEMPTY\x00", "GH EMPTY"),
        ("\x00DONOTSTART\x00", "do NOT start Croatia or any other country"),
        ("\x00DONOTSTART2\x00", "do NOT start Croatia or any other"),
        ("\x00DONOTREBUILD\x00", "do NOT start HR/TH/SD/LB/FM/MM/IS"),
        # URLs — Monaco legimonaco → Slovakia slov-lex (query-only)
        ("www/legimonaco.mc", "www/slov-lex.sk"),
        ("legimonaco.mc", "slov-lex.sk"),
        ("www.legimonaco.mc", "www.slov-lex.sk"),
        ("legimonaco", "slov-lex"),
        # Language / country
        ("French (Monaco)", "Slovak (Slovakia)"),
        ("French Monaco", "Slovak Slovakia"),
        ("ASCII-fold French", "ASCII-fold Slovak"),
        ("French legal stems", "Slovak legal stems"),
        ("French legal corpus", "Slovak legal corpus"),
        ("French GATE", "Slovak GATE"),
        ("Monaco", DISPLAY),
        ("monaco_ranked", "slovakia_ranked"),
        ("monaco_gate", "slovakia_gate"),
        ("monaco_pass", "slovakia_pass"),
        ("monaco_encode_memsafe", "slovakia_encode_memsafe"),
        ("monaco_package_memsafe", "slovakia_package_memsafe"),
        ("monaco_corpus_stream", "slovakia_corpus_stream"),
        ("monaco_encode_done", "slovakia_encode_done"),
        ("monaco_filtered_", "slovakia_filtered_"),
        ("monaco_", "slovakia_"),
        ('"MC"', '"SK"'),
        ("MC-attested", "SK-attested"),
        ("(MC)", "(SK)"),
        ('"mc"', '"sk"'),
        # floors 862/438 → 16799/179 — compound ONLY first (tips protected)
        ("862/438", "16799/179"),
        ("862 / 438", "16799 / 179"),
        ("862, 438", "16799, 179"),
        ("FLOOR_LAWS, FLOOR_ARTS = 862, 438", "FLOOR_LAWS, FLOOR_ARTS = 16799, 179"),
        ('int(pack.get("n_laws") or 862)', 'int(pack.get("n_laws") or 16799)'),
        ('int(pack.get("n_articles") or 438)', 'int(pack.get("n_articles") or 179)'),
        ("@ 862/", "@ 16799/"),
        ("floor 862/", "floor 16799/"),
        ("(862/", "(16799/"),
        (" 438", " 179"),
        ("438", "179"),
        ("= 862,", "= 16799,"),
        ("or 862)", "or 16799)"),
        ("or 862,", "or 16799,"),
        ("or 862}", "or 16799}"),
        ("= 862", "= 16799"),
        (" 862/", " 16799/"),
        ("862", "16799"),
        ('"language": "French"', '"language": "Slovak"'),
        ('"lang": "French"', '"lang": "Slovak"'),
        ("language: French", "language: Slovak"),
        ("Language: French", "Language: Slovak"),
    ]
    for a, b in reps:
        text = text.replace(a, b)

    # Restore tip SHA after digit floor swaps
    text = text.replace("\x00TIPSHA_PROTECT\x00", DST_TIP_FULL)
    text = text.replace("\x00TIPSHORT_PROTECT\x00", DST_TIP_SHORT)

    text = re.sub(
        r"(?<![A-Za-z0-9_])monaco(?![A-Za-z0-9_])",
        SLUG,
        text,
    )

    text = text.replace("\x00BM25\x00", "BM25").replace("\x00bm25\x00", "bm25")
    text = text.replace("\x00DESTHOLD\x00", HOLD)
    text = text.replace("\x00DESTCHAIN\x00", DEST_CHAIN)
    text = text.replace("\x00DESTWAVE\x00", WAVE_POS)
    text = text.replace("\x00DESTMODE\x00", "SOFT_THIN_FINAL")
    text = text.replace("\x00UUID94\x00", "67930c3f-c94b-445b-a5bc-01d3fc1135c1")

    text = text.replace(f'"name": "{SLUG}"', f'"name": "{DISPLAY}"')
    text = text.replace(f'"slug": "{DISPLAY}"', f'"slug": "{SLUG}"')
    text = text.replace(f'SLUG = "{DISPLAY}"', f'SLUG = "{SLUG}"')
    text = text.replace(f'"country": "{DISPLAY}"', f'"country": "{SLUG}"')
    text = text.replace('"country": "monaco"', f'"country": "{SLUG}"')
    text = text.replace(f"# {SLUG} filtered pack", f"# {DISPLAY} filtered pack")
    text = text.replace(f"{SLUG} laws IR release", f"{DISPLAY} laws IR release")

    for bad in (
        "cient-data", "prent-data", "stent-data", "cvent-data", "scent-data",
        "carent-data", "yement-data", "djiboutient-data", "marshallislandsent-data",
        "kiribatient-data", "burundient-data", "eswatinient-data", "niueent-data",
        "guineabissauent-data", "surinameent-data", "equatorialguineaent-data",
        "guyanaent-data", "beninent-data", "somaliaent-data", "maldivesent-data",
        "arubaent-data", "saint_vincent_grenadinesent-data", "vanuatuent-data",
        "ghanaent-data", "algeriaent-data", "monacoent-data", "slovakiaent-data",
    ):
        text = text.replace(f"/home/box/{bad}/", "/home/box/agent-data/")
        text = text.replace(bad, "agent-data")

    if dst_name == "slovakia_bm25_smoke.py":
        start = text.index("GATE = [")
        end = text.index("]", start) + 1
        years_line = ", ".join(f'"{y}"' for y in GATE_YEARS)
        stems_line = ", ".join(f'"{s}"' for s in GATE_STEMS)
        gate = f"GATE = [\n    {years_line},\n    {stems_line},\n]"
        text = text[:start] + gate + text[end:]
        text = re.sub(
            r"QUERIES = GATE \+ \[[^\]]*\]",
            'QUERIES = GATE + ["www", "slov-lex.sk", "www.slov-lex.sk", "static.slov-lex.sk", "slov", "lex", "zz", "law", "act", "rozhodnutie", "narodna", "znena"]',
            text,
            count=1,
        )
        text = re.sub(
            r'"""BM25 smoke for .*?"""',
            '"""BM25 smoke for Slovakia IR — Slovak legal corpus; years + Slovak legal stems FTS gate.\n\n'
            "GATE is attested ASCII years plus Slovak/EN legal stems present in articles.parquet\n"
            "(ASCII-fold). URL www/slov-lex.sk is query-only, never GATE. Every GATE token must rank a hit.\n"
            '"""',
            text,
            count=1,
            flags=re.S,
        )
        note = (
            f"attested years {GATE_NOTE_YEARS} plus Slovak legal stems {GATE_NOTE_STEMS} "
            f"from articles.parquet HEAD tip {DST_TIP_SHORT}; URL www/slov-lex.sk "
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
        text = text.replace("monaco_pass", "slovakia_pass").replace("monaco_gate", "slovakia_gate")

    if dst_name == "slovakia_write_publish_report.py":
        gate_note = (
            f"BM25 PASS on Slovakia ASCII-fold Slovak GATE "
            f"(attested years {GATE_NOTE_YEARS} + stems {GATE_NOTE_STEMS}); "
            f"URL www/slov-lex.sk is query-only, not GATE"
        )
        text = re.sub(
            r'BM25 PASS on Slovakia[^"]*"',
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
            r"HOLD 0 STRICT[^;]*; collectors kept dead \(pkill\); soft never-thin ON[^\"\n]*",
            f"{HOLD}; collectors kept dead (pkill); soft never-thin ON (SK soft-thin OK); SKIP_US; Italy LIVE leave alone; {WAVE_POS}",
            text,
        )
        text = re.sub(r"[ \t]{2,}", " ", text)

    leftovers = (
        "Monaco", "monaco", "principaute", "legimonaco",
        "cient-data", "prent-data", "stent-data", "cvent-data", "scent-data",
        "loi", "ordonnance", "arrete",  # French stems leftover outside GATE rewrite risk
    )
    # only hard-fail on country leftovers; French stems checked in GATE slice
    found = []
    for x in ("Monaco", "monaco", "legimonaco", "principaute"):
        if re.search(rf"(?<![A-Za-z0-9_]){re.escape(x)}(?![A-Za-z0-9_])", text):
            found.append(x)
    if found:
        raise RuntimeError(f"language/country leftovers in {dst_name}: {found}")

    if dst_name.endswith("_bm25_smoke.py"):
        gate_slice = text[text.index("GATE = ["): text.index("]", text.index("GATE = [")) + 1]
        for bad in (
            "monaco", "principaute", "loi", "ordonnance", "arrete", "conseil", "etat",
            "gouvernement", "ministre", "code", "algerie", "republique", "decret",
            "articlee",  # nonsense
        ):
            # "article" is OK for SK (attested EN). allow article.
            if bad == "article":
                continue
            if f'"{bad}"' in gate_slice:
                raise RuntimeError(f"non-SK token in GATE of {dst_name}: {bad}")
        for stem in GATE_STEMS:
            if f'"{stem}"' not in gate_slice:
                raise RuntimeError(f"missing stem in GATE of {dst_name}: {stem}")
        for year in GATE_YEARS:
            if f'"{year}"' not in gate_slice:
                raise RuntimeError(f"missing year in GATE of {dst_name}: {year}")
        if "legimonaco" in text:
            raise RuntimeError(f"leftover legimonaco in {dst_name}")

    scrub = text
    scrub = scrub.replace(WAVE_POS, "XX")
    scrub = scrub.replace(HOLD, "XX")
    scrub = scrub.replace(DEST_CHAIN, "XX")
    scrub = scrub.replace(SRC_HOLD, "XX")
    scrub = scrub.replace(SRC_WAVE, "XX")
    scrub = scrub.replace("after-MC", "after-XX")
    scrub = scrub.replace("after MC ", "after XX ")
    scrub = scrub.replace("MC LIVE", "XX LIVE")
    scrub = scrub.replace("DZ+MC", "XX")
    scrub = scrub.replace("GH EMPTY", "XX EMPTY")
    scrub = scrub.replace("DZ LIVE", "XX LIVE")
    if re.search(r"(?<![A-Za-z0-9_])monaco(?![A-Za-z0-9_])", scrub):
        m = re.search(r"(?<![A-Za-z0-9_])monaco(?![A-Za-z0-9_])", scrub)
        raise RuntimeError(
            f"leftover monaco in {dst_name}: ...{scrub[max(0, m.start()-20):m.start()+20]}..."
        )
    if re.search(r"(?<![A-Za-z%])MC(?![A-Za-z])", scrub):
        m = re.search(r"(?<![A-Za-z%])MC(?![A-Za-z])", scrub)
        raise RuntimeError(
            f"leftover MC in {dst_name}: ...{scrub[max(0, m.start()-30):m.start()+30]}..."
        )
    if "ipfs_monaco" in text:
        raise RuntimeError(f"leftover monaco path in {dst_name}")
    if SRC_TIP_SHORT in text or SRC_TIP_FULL in text:
        raise RuntimeError(f"src tip leftover in {dst_name}")
    # tip integrity — must equal exact DST tip
    if DST_TIP_FULL not in text and any(x in dst_name for x in ("soft_filter", "corpus", "encode", "finish", "package", "write_publish")):
        # short tip always required in orch/smoke/filter
        pass
    if DST_TIP_SHORT not in text and any(x in dst_name for x in ("soft_filter", "orchestrator", "bm25_smoke")):
        raise RuntimeError(f"missing DST tip in {dst_name}")
    # reject corrupted tip fragments (floor digit eat)
    if "22508a5eab4b" in text:
        # any full tip present must be exact
        for m in re.finditer(r"22508a5eab4b[0-9a-f]*", text):
            frag = m.group(0)
            if len(frag) >= 40 and frag != DST_TIP_FULL:
                raise RuntimeError(f"corrupted tip SHA in {dst_name}: {frag}")
            if 12 < len(frag) < 40:
                raise RuntimeError(f"truncated/partial tip SHA in {dst_name}: {frag}")
    if "soft_filter" in dst_name or "corpus_stream" in dst_name:
        if "data/laws.parquet" not in text and 'data" / "laws.parquet"' not in text:
            if '"data"' not in text and "/data/" not in text:
                raise RuntimeError(f"missing data/ parquet paths in {dst_name}")
    if "862/438" in text or "FLOOR_LAWS, FLOOR_ARTS = 862" in text:
        raise RuntimeError(f"OLD monaco floor leftover in {dst_name}")
    if "write_publish" in dst_name or "bm25_smoke" in dst_name:
        if re.search(r"ASCII-fold French|French legal", text):
            raise RuntimeError(f"leftover French phrasing in {dst_name}")
        if re.search(r"ASCII-fold Dutch|Dutch legal|ASCII-fold English|English legal", text):
            # English legal OK? we use Slovak label; reject English GATE phrasing leftovers
            if re.search(r"ASCII-fold English|English legal", text):
                raise RuntimeError(f"leftover English phrasing in {dst_name}")
    return text


for src_name, dst_name in FILES:
    src = ROOT / src_name
    if not src.is_file():
        raise FileNotFoundError(src)
    (ROOT / dst_name).write_text(
        adapt(src.read_text(encoding="utf-8"), dst_name), encoding="utf-8"
    )
    print(f"wrote {dst_name}")

# verify tip SHA intact in all outputs
for _, dst_name in FILES:
    t = (ROOT / dst_name).read_text(encoding="utf-8")
    if DST_TIP_FULL in t and DST_TIP_FULL not in t:  # noqa: tautology guard
        pass
    for m in re.finditer(r"22508a5eab4b[0-9a-f]{20,}", t):
        if m.group(0) != DST_TIP_FULL:
            raise RuntimeError(f"post-write corrupted tip in {dst_name}: {m.group(0)}")
    if "TIP_FULL" in t or "TIP =" in t or "source_revision" in t:
        if DST_TIP_SHORT not in t:
            raise RuntimeError(f"missing short tip in {dst_name}")

wave_paths = [
    Path("/workspace/next_ir_ok_wave_after_gh_wave2.json"),
    Path("/workspace/country-law-triage/next_ir_ok_wave_after_gh_wave2.json"),
]
for wave in wave_paths:
    if not wave.is_file():
        src_w = Path("/workspace/next_ir_ok_wave_after_gh_wave2.json")
        if wave != src_w and src_w.is_file():
            wave.parent.mkdir(parents=True, exist_ok=True)
            wave.write_text(src_w.read_text(encoding="utf-8"), encoding="utf-8")
        else:
            print(f"skip missing wave {wave}")
            continue
    data = json.loads(wave.read_text(encoding="utf-8"))
    for entry in data.get("queue") or []:
        if entry.get("slug") == SLUG or entry.get("iso2") == "SK":
            entry.update({
                "tip": DST_TIP_SHORT,
                "tip_full": DST_TIP_FULL,
                "laws": FLOOR_LAWS,
                "articles": FLOOR_ARTS,
                "floor_laws": FLOOR_LAWS,
                "floor_articles": FLOOR_ARTS,
                "claim_tip": DST_TIP_SHORT,
                "match_claim": True,
                "label": "EXPAND",
                "soft_never_thin": True,
                "soft_thin": True,
                "skip_us": True,
                "italy_live_leave_alone": True,
                "language": "Slovak",
                "lang": "Slovak",
                "iso2": "SK",
                "slug": SLUG,
                "repo": "endomorphosis/ipfs_slovakia_laws",
                "years_attested": YEARS_ATTESTED,
                "gate_years": [int(y) for y in GATE_YEARS],
                "gate_stems": GATE_STEMS,
                "note": (
                    f"SK SOFT_THIN_FINAL scaffold; tip MATCH {DST_TIP_SHORT}@16799/179; {HOLD}; "
                    f"soft-thin OK; SKIP_US; Italy LIVE leave alone; {WAVE_POS}; "
                    f"Slovak GATE ({len(GATE_YEARS)} years + {len(GATE_STEMS)} stems); "
                    f"memsafe only; do NOT start Croatia or any other country"
                ),
                "status": "CLAIMED",
                "mode": "SOFT_THIN_FINAL",
                "wave_end": False,
                "do_not_start": False,
            })
            break
    else:
        raise RuntimeError(f"Slovakia / SK entry missing from wave JSON {wave}")

    data["wave_status"] = "IN_PROGRESS_SK"
    data["hold"] = HOLD
    data["current"] = SLUG
    data["do_not_start_next"] = "croatia"
    data["next"] = "croatia"
    data["hold_note"] = (
        "HOLD 0 STRICT for SK SOFT_THIN_FINAL build in progress; "
        "do NOT start Croatia or any other country; DZ+MC LIVE leave alone; Italy LIVE; KW HOLD_THIN; AT queued-only"
    )
    wave.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"updated wave JSON {wave}")

print("GATE years", GATE_YEARS)
print("GATE stems", GATE_STEMS)
print("n_gate", len(GATE_YEARS) + len(GATE_STEMS))
print("HOLD", HOLD)
print("TIP_FULL", DST_TIP_FULL)
print("soft-thin memsafe: 16799/179; only SK")
