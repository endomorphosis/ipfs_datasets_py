#!/usr/bin/env python3
"""Adapt the Ghana English memsafe FIRST_IR pack to Algeria DZ tip e01c7f983e00.

French (Algeria; bilingual FR/AR corpus, laws.language=fr); SOFT_THIN_FINAL;
HOLD 0 STRICT wave2 after GH EMPTY (DZ first; then MC→SK→HR→TH→SD→LB→FM→MM→IS).
Soft never-thin ON except CoS soft-thin exceptions (DZ is soft-thin OK);
SKIP_US; Italy unlocked already LIVE — leave alone; KW HOLD_THIN leave alone;
AT tip d35cc16226a7 queued-only leave alone.
GATE: attested years + French legal stems from data/articles.parquet tip
e01c7f983e00 (article/loi/decret/ordonnance/republique/algerie/…).
URL www.joradp.dz query-only, NOT GATE.
Source tip c19c1fb59bc2 (Ghana English memsafe with data/ paths)
— override language to French (Algeria).
Keep data/articles.parquet + data/laws.parquet; agent-data not cient-data.
Floor ≥100/492. Do NOT start Monaco or any other country.
Old algeria_* scripts targeted tip d19ae6411729 @ 280/12423 — DO NOT reuse.
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
DST_TIP_FULL = "e01c7f983e00d03cd9c8319c37e831bc0eaf0caf"
DST_TIP_SHORT = "e01c7f983e00"
FLOOR_LAWS, FLOOR_ARTS = 100, 492
SRC_FLOOR_L, SRC_FLOOR_A = 101, 8572

# Sampled from data/articles.parquet @ e01c7f983e00 (top years + French stems present)
# Whole-word ASCII-fold FTS hits; laws=100 articles=492.
GATE_YEARS = [
    "2002", "2003", "2013", "2015", "2016",
    "2012", "2006", "2005", "2004", "2007",
]
GATE_STEMS = [
    "article", "loi", "ordonnance", "republique", "algerie",
    "ministre", "etat", "gouvernement", "president", "arrete", "assemblee",
]
YEARS_ATTESTED = [int(y) for y in GATE_YEARS] + [
    2011, 2014, 2010, 2017, 2009, 2008, 2018, 2001, 2000, 1997,
]
GATE_NOTE_YEARS = "/".join(GATE_YEARS)
GATE_NOTE_STEMS = "/".join(GATE_STEMS)
HOLD = "HOLD 0 STRICT wave2 after GH EMPTY (DZ)"
WAVE_POS = (
    "FIRST of wave2 after GH EMPTY "
    "(DZ SOFT_THIN_FINAL; then MC→SK→HR→TH→SD→LB→FM→MM→IS — do NOT start those)"
)
DEST_CHAIN = "DZ"
SRC_HOLD = "HOLD 0 STRICT after-VU unlock (GH)"
SRC_WAVE = (
    "first country of after_vu_unlock wave "
    "(GH FIRST_IR; soft-thin six + NG already LIVE — do not rebuild)"
)
SRC_CHAIN = "GH"

FILES = [
    ("ghana_soft_filter.py", "algeria_soft_filter.py"),
    (f"ghana_corpus_stream_{SRC_TIP_SHORT}.py", f"algeria_corpus_stream_{DST_TIP_SHORT}.py"),
    (f"ghana_encode_memsafe_{SRC_TIP_SHORT}.py", f"algeria_encode_memsafe_{DST_TIP_SHORT}.py"),
    (f"ghana_finish_from_emb_{SRC_TIP_SHORT}.py", f"algeria_finish_from_emb_{DST_TIP_SHORT}.py"),
    (f"ghana_stream_graph_parts_{SRC_TIP_SHORT}.py", f"algeria_stream_graph_parts_{DST_TIP_SHORT}.py"),
    (f"ghana_package_memsafe_{SRC_TIP_SHORT}.py", f"algeria_package_memsafe_{DST_TIP_SHORT}.py"),
    ("ghana_upload.py", "algeria_upload.py"),
    ("ghana_bm25_smoke.py", "algeria_bm25_smoke.py"),
    ("ghana_write_publish_report.py", "algeria_write_publish_report.py"),
    (f"ghana_orchestrator_{SRC_TIP_SHORT}.py", f"algeria_orchestrator_{DST_TIP_SHORT}.py"),
]

DISPLAY = "Algeria"
SLUG = "algeria"
SRC_DISPLAY = "Ghana"
SRC_SLUG = "ghana"


def adapt(text: str, dst_name: str) -> str:
    # Repair path corruption from prior adapts
    for bad in (
        "cient-data", "prent-data", "stent-data", "cvent-data", "scent-data",
        "carent-data", "yement-data", "djiboutient-data", "marshallislandsent-data",
        "kiribatient-data", "burundient-data", "eswatinient-data", "niueent-data",
        "guineabissauent-data", "surinameent-data", "equatorialguineaent-data",
        "guyanaent-data", "beninent-data", "somaliaent-data", "maldivesent-data",
        "arubaent-data", "saint_vincent_grenadinesent-data", "vanuatuent-data",
        "ghanaent-data", "algeriaent-data",
    ):
        text = text.replace(f"/home/box/{bad}/", "/home/box/agent-data/")
        text = text.replace(bad, "agent-data")

    # Protect BM25
    text = text.replace("BM25", "\x00BM25\x00").replace("bm25", "\x00bm25\x00")
    text = text.replace("bmjacency", "adjacency")

    # Protect HOLD / wave / chains BEFORE ISO/slug swaps
    text = text.replace(SRC_HOLD, "\x00DESTHOLD\x00")
    text = text.replace(SRC_WAVE, "\x00DESTWAVE\x00")
    text = text.replace(HOLD, "\x00DESTHOLD\x00")
    text = text.replace(WAVE_POS, "\x00DESTWAVE\x00")
    text = text.replace(DEST_CHAIN, "\x00DESTCHAIN\x00")
    text = text.replace("after-VU unlock (GH)", "\x00DESTHOLD\x00")
    text = text.replace("after-VU", "\x00AFTERDZ\x00")
    text = text.replace("after VU ", "\x00AFTERDZ_SP\x00")
    text = text.replace("after_vu_unlock", "\x00AFTERVUUNLOCK_US\x00")
    text = text.replace("after_mv", "\x00AFTERMV_US\x00")
    text = text.replace("after_dj", "\x00AFTERDJ_US\x00")
    text = text.replace("GH FIRST_IR", "\x00DESTMODE\x00")
    text = text.replace("FIRST_IR", "\x00DESTMODE\x00")
    text = text.replace("do NOT start any other country", "\x00DONOTSTART\x00")
    text = text.replace("do NOT start any other", "\x00DONOTSTART2\x00")
    text = text.replace("do not rebuild", "\x00DONOTREBUILD\x00")

    # Protect UUID fragment before digit floor swaps
    text = text.replace("67930c3f-c94b-445b-a5bc-01d3fc1135c1", "\x00UUID94\x00")

    reps = [
        (SRC_TIP_FULL, DST_TIP_FULL),
        (SRC_TIP_SHORT, DST_TIP_SHORT),
        ("endomorphosis/ipfs_ghana_laws", "endomorphosis/ipfs_algeria_laws"),
        ("justicedao/ipfs_ghana_laws_ir", "justicedao/ipfs_algeria_laws_ir"),
        ("ipfs_ghana_laws_ir", "ipfs_algeria_laws_ir"),
        ("ipfs_ghana_laws", "ipfs_algeria_laws"),
        # HOLD / wave restore
        ("\x00DESTHOLD\x00", HOLD),
        ("\x00DESTWAVE\x00", WAVE_POS),
        ("\x00DESTCHAIN\x00", DEST_CHAIN),
        ("\x00DESTMODE\x00", "SOFT_THIN_FINAL"),
        ("\x00AFTERDZ\x00", "after-GH"),
        ("\x00AFTERDZ_SP\x00", "after GH "),
        ("\x00DONOTSTART\x00", "do NOT start Monaco or any other country"),
        ("\x00DONOTSTART2\x00", "do NOT start Monaco or any other"),
        ("\x00DONOTREBUILD\x00", "do NOT start MC/SK/HR/TH/SD/LB/FM/MM/IS"),
        # URLs — Ghana domains → Algeria joradp.dz (query-only)
        ("www/gov.gh", "www/joradp.dz"),
        ("gov.gh", "joradp.dz"),
        ("www.gov.gh", "www.joradp.dz"),
        ("parliament.gh", "joradp.dz"),
        ("www.parliament.gh", "www.joradp.dz"),
        # Language / country — display name BEFORE slug
        ("English (Ghana)", "French (Algeria)"),
        ("English Ghana", "French Algeria"),
        ("ASCII-fold English", "ASCII-fold French"),
        ("English legal stems", "French legal stems"),
        ("English legal corpus", "French legal corpus"),
        ("English GATE", "French GATE"),
        ("Ghana", DISPLAY),
        # slug / path forms BEFORE bare ghana
        ("ghana_ranked", "algeria_ranked"),
        ("ghana_gate", "algeria_gate"),
        ("ghana_pass", "algeria_pass"),
        ("ghana_encode_memsafe", "algeria_encode_memsafe"),
        ("ghana_package_memsafe", "algeria_package_memsafe"),
        ("ghana_corpus_stream", "algeria_corpus_stream"),
        ("ghana_encode_done", "algeria_encode_done"),
        ("ghana_filtered_", "algeria_filtered_"),
        ("ghana_", "algeria_"),
        # ISO whole-token / path forms only
        ('"GH"', '"DZ"'),
        ("GH-attested", "DZ-attested"),
        ("(GH)", "(DZ)"),
        ('"gh"', '"dz"'),
        # floors 101/8572 → 100/492 — compound ONLY first
        ("101/8572", "100/492"),
        ("101 / 8572", "100 / 492"),
        ("101, 8572", "100, 492"),
        ("FLOOR_LAWS, FLOOR_ARTS = 101, 8572", "FLOOR_LAWS, FLOOR_ARTS = 100, 492"),
        ('int(pack.get("n_laws") or 101)', 'int(pack.get("n_laws") or 100)'),
        ('int(pack.get("n_articles") or 8572)', 'int(pack.get("n_articles") or 492)'),
        ("@ 101/", "@ 100/"),
        ("floor 101/", "floor 100/"),
        ("(101/", "(100/"),
        (" 8572", " 492"),
        ("8572", "492"),
        ("= 101,", "= 100,"),
        ("or 101)", "or 100)"),
        ("or 101,", "or 100,"),
        ("or 101}", "or 100}"),
        ("= 101", "= 100"),
        (" 101/", " 100/"),
        # language field leftovers
        ('"language": "English"', '"language": "French"'),
        ('"lang": "English"', '"lang": "French"'),
        ("language: English", "language: French"),
        ("Language: English", "Language: French"),
    ]
    for a, b in reps:
        text = text.replace(a, b)

    # Bare slug
    text = re.sub(
        r"(?<![A-Za-z0-9_])ghana(?![A-Za-z0-9_])",
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
    text = text.replace("\x00DESTMODE\x00", "SOFT_THIN_FINAL")
    text = text.replace("\x00UUID94\x00", "67930c3f-c94b-445b-a5bc-01d3fc1135c1")

    # display name / slug fixes
    text = text.replace(f'"name": "{SLUG}"', f'"name": "{DISPLAY}"')
    text = text.replace(f'"slug": "{DISPLAY}"', f'"slug": "{SLUG}"')
    text = text.replace(f'SLUG = "{DISPLAY}"', f'SLUG = "{SLUG}"')
    text = text.replace(f'"country": "{DISPLAY}"', f'"country": "{SLUG}"')
    text = text.replace('"country": "ghana"', f'"country": "{SLUG}"')
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
        "ghanaent-data", "algeriaent-data",
    ):
        text = text.replace(f"/home/box/{bad}/", "/home/box/agent-data/")
        text = text.replace(bad, "agent-data")

    if dst_name == "algeria_bm25_smoke.py":
        start = text.index("GATE = [")
        end = text.index("]", start) + 1
        years_line = ", ".join(f'"{y}"' for y in GATE_YEARS)
        stems_line = ", ".join(f'"{s}"' for s in GATE_STEMS)
        gate = f"GATE = [\n    {years_line},\n    {stems_line},\n]"
        text = text[:start] + gate + text[end:]
        text = re.sub(
            r"QUERIES = GATE \+ \[[^\]]*\]",
            'QUERIES = GATE + ["www", "joradp.dz", "www.joradp.dz", "joradp", "officiel", "tribunal", "justice", "penal", "constitution", "assemblee", "journal"]',
            text,
            count=1,
        )
        text = re.sub(
            r'"""BM25 smoke for .*?"""',
            '"""BM25 smoke for Algeria IR — French legal corpus; years + French legal stems FTS gate.\n\n'
            "GATE is attested ASCII years plus French legal stems (ASCII-fold). URL www/joradp.dz\n"
            "is query-only, never GATE. Every GATE token must rank a hit.\n"
            '"""',
            text,
            count=1,
            flags=re.S,
        )
        note = (
            f"attested years {GATE_NOTE_YEARS} plus French legal stems {GATE_NOTE_STEMS} "
            f"from articles.parquet HEAD tip {DST_TIP_SHORT}; URL www/joradp.dz "
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

    if dst_name == "algeria_write_publish_report.py":
        gate_note = (
            f"BM25 PASS on Algeria ASCII-fold French GATE "
            f"(attested years {GATE_NOTE_YEARS} + stems {GATE_NOTE_STEMS}); "
            f"URL www/joradp.dz is query-only, not GATE"
        )
        text = re.sub(
            r'BM25 PASS on Algeria[^"]*"',
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
            r"HOLD 0 STRICT[^;]*; collectors kept dead \(pkill\); soft never-thin ON; SKIP_US; Italy BLOCKED;[^\"\n]*",
            f"{HOLD}; collectors kept dead (pkill); soft never-thin ON (DZ soft-thin OK); SKIP_US; Italy LIVE leave alone; {WAVE_POS}",
            text,
        )
        text = re.sub(r"[ \t]{2,}", " ", text)

    leftovers = (
        "Ghana", "ghana",
        "cient-data", "prent-data", "stent-data", "cvent-data", "scent-data",
        "carent-data", "yement-data", "djiboutient-data", "marshallislandsent-data",
        "kiribatient-data", "burundient-data", "eswatinient-data", "niueent-data",
        "guineabissauent-data", "surinameent-data", "equatorialguineaent-data",
        "guyanaent-data", "beninent-data", "somaliaent-data", "maldivesent-data",
        "gov.gh", "www.gov.gh", "parliament.gh",
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

    # Reject non-DZ tokens in GATE; require French stems
    if dst_name.endswith("_bm25_smoke.py"):
        gate_slice = text[text.index("GATE = ["): text.index("]", text.index("GATE = [")) + 1]
        for bad in (
            "aruba", "artikel", "wet", "besluit", "landsverordening", "verordening",
            "koninkrijk", "regering", "persoon",
            "maldives", "maldivian", "ruling",
            "benin", "ivoire", "ghana", "act", "section", "law", "ordinance",
            "republic", "government", "person", "order",
            "articulo", "ley", "decreto", "codigo", "seccion",
            "artigo", "lei", "suriname", "curacao", "guyana",
            "vanuatu", "vincent", "grenadines",
        ):
            if f'"{bad}"' in gate_slice:
                raise RuntimeError(f"non-DZ token in GATE of {dst_name}: {bad}")
        for stem in GATE_STEMS:
            if f'"{stem}"' not in gate_slice:
                raise RuntimeError(f"missing French stem in GATE of {dst_name}: {stem}")
        for year in GATE_YEARS:
            if f'"{year}"' not in gate_slice:
                raise RuntimeError(f"missing year in GATE of {dst_name}: {year}")
        if '", "gh"' in text or '", "GH"' in text:
            raise RuntimeError(f"leftover gh query token in {dst_name}")
        if "gov.gh" in text:
            raise RuntimeError(f"leftover gov.gh in {dst_name}")

    # reject bare ghana / GH leftovers outside protected HOLD/wave
    scrub = text
    scrub = scrub.replace(WAVE_POS, "XX")
    scrub = scrub.replace(HOLD, "XX")
    scrub = scrub.replace(DEST_CHAIN, "XX")
    scrub = scrub.replace(SRC_HOLD, "XX")
    scrub = scrub.replace(SRC_WAVE, "XX")
    scrub = scrub.replace("after-GH", "after-XX")
    scrub = scrub.replace("after GH ", "after XX ")
    scrub = scrub.replace("after_vu_unlock", "after_xx")
    scrub = scrub.replace("after_mv", "after_xx")
    scrub = scrub.replace("after_dj", "after_xx")
    scrub = scrub.replace("GH EMPTY", "XX EMPTY")
    scrub = scrub.replace("GH LIVE", "XX LIVE")
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
    if "agent-data" not in text and "SECRET" in text.upper():
        if any(x in dst_name for x in ("soft_filter", "upload", "orchestrator")):
            if "/home/box/" in text and "agent-data" not in text:
                raise RuntimeError(f"missing agent-data secret path in {dst_name}")
    # data/ paths must survive
    if "soft_filter" in dst_name or "corpus_stream" in dst_name:
        if "data/laws.parquet" not in text and 'data" / "laws.parquet"' not in text:
            if '"data"' not in text and "/data/" not in text:
                raise RuntimeError(f"missing data/ parquet paths in {dst_name}")
    # tip integrity — reject OLD algeria tip floors
    if SRC_TIP_SHORT in text:
        raise RuntimeError(f"src tip leftover in {dst_name}")
    if "d19ae6411729" in text:
        raise RuntimeError(f"OLD algeria tip d19ae6411729 in {dst_name}")
    if "280/12423" in text or "12423" in text:
        raise RuntimeError(f"OLD algeria floor leftover in {dst_name}")
    if "67930c3f-c86b-" in text:
        raise RuntimeError(f"UUID c94b corrupted to c86b in {dst_name}")
    if DST_TIP_SHORT not in text and any(x in dst_name for x in ("soft_filter", "orchestrator", "bm25_smoke")):
        raise RuntimeError(f"missing DST tip in {dst_name}")
    # french language must remain for DZ
    if "write_publish" in dst_name or "bm25_smoke" in dst_name:
        if re.search(r"ASCII-fold Dutch|Dutch legal", text):
            raise RuntimeError(f"leftover Dutch phrasing in {dst_name}")
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

# Update wave JSON status for DZ in progress
wave_paths = [
    Path("/workspace/next_ir_ok_wave_after_gh_wave2.json"),
    Path("/workspace/country-law-triage/next_ir_ok_wave_after_gh_wave2.json"),
]
for wave in wave_paths:
    if not wave.is_file():
        # seed from workspace copy if triage mirror missing
        src_w = Path("/workspace/next_ir_ok_wave_after_gh_wave2.json")
        if wave != src_w and src_w.is_file():
            wave.parent.mkdir(parents=True, exist_ok=True)
            wave.write_text(src_w.read_text(encoding="utf-8"), encoding="utf-8")
        else:
            print(f"skip missing wave {wave}")
            continue
    data = json.loads(wave.read_text(encoding="utf-8"))
    for entry in data.get("queue") or []:
        if entry.get("slug") == SLUG or entry.get("iso2") == "DZ":
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
                "language": "French",
                "lang": "French",
                "iso2": "DZ",
                "slug": SLUG,
                "repo": "endomorphosis/ipfs_algeria_laws",
                "years_attested": YEARS_ATTESTED,
                "gate_years": [int(y) for y in GATE_YEARS],
                "gate_stems": GATE_STEMS,
                "note": (
                    f"DZ SOFT_THIN_FINAL scaffold; tip MATCH {DST_TIP_SHORT}@100/492; {HOLD}; "
                    f"soft-thin OK; SKIP_US; Italy LIVE leave alone; {WAVE_POS}; "
                    f"French GATE ({len(GATE_YEARS)} years + {len(GATE_STEMS)} stems); "
                    f"memsafe only; do NOT start Monaco or any other country"
                ),
                "status": "CLAIMED",
                "mode": "SOFT_THIN_FINAL",
                "wave_end": False,
                "do_not_start": False,
            })
            break
    else:
        raise RuntimeError(f"Algeria / DZ entry missing from wave JSON {wave}")

    data["wave_status"] = "IN_PROGRESS_DZ"
    data["hold"] = HOLD
    data["current"] = SLUG
    data["do_not_start_next"] = "monaco"
    data["next"] = "monaco"
    data["hold_note"] = (
        "HOLD 0 STRICT for DZ SOFT_THIN_FINAL build in progress; "
        "do NOT start Monaco or any other country; Italy LIVE leave alone; KW HOLD_THIN; AT queued-only"
    )
    wave.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"updated wave JSON {wave}")

print("GATE years", GATE_YEARS)
print("GATE stems", GATE_STEMS)
print("n_gate", len(GATE_YEARS) + len(GATE_STEMS))
print("HOLD", HOLD)
print("GATE language: French years+stems")
print("soft-thin memsafe: 100/492; only DZ")
