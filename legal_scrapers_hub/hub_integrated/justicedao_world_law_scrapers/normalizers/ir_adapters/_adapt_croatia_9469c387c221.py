#!/usr/bin/env python3
"""Adapt Slovakia Slovak memsafe SOFT_THIN_FINAL pack to Croatia HR tip 9469c387c221.

Croatian (laws.language=hr); SOFT_THIN_FINAL; HOLD 0 STRICT wave2 FOURTH after
DZ+MC+SK LIVE (HR; then TH→SD→LB→FM→MM→IS). Soft never-thin ON except soft-thin OK;
SKIP_US; Italy LIVE leave alone; KW HOLD_THIN; AT queued-only; P1 404 PARKED.
Do NOT rebuild DZ/MC/SK. Do NOT start Thailand.
GATE: attested years + Croatian stems from data/articles.parquet tip 9469c387c221
(clanak/hrvatske/republike/zakon/…).
URL narodne-novine.nn.hr query-only, NOT GATE.
CRITICAL: protect tip SHA tokens during floor digit replaces.
Floor ≥30315/108.
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
SRC_TIP_FULL = "22508a5eab4b3c0ba98fe0ab32aa9fcb5ec4be9a"
SRC_TIP_SHORT = "22508a5eab4b"
DST_TIP_FULL = "9469c387c221cf5ab435b0c4cabb9426213a48ee"
DST_TIP_SHORT = "9469c387c221"
FLOOR_LAWS, FLOOR_ARTS = 30315, 108
SRC_FLOOR_L, SRC_FLOOR_A = 16799, 179

GATE_YEARS = [
    "2009", "2011", "2014", "2010", "2013",
    "2008", "2017", "2012", "2015", "2003",
]
GATE_STEMS = [
    "clanak", "hrvatske", "republike", "zakon", "odluka",
    "stavak", "sud", "narodne", "novine", "vlada", "ustav",
]
YEARS_ATTESTED = [int(y) for y in GATE_YEARS] + [
    2026, 2019, 2002, 2020, 2006, 1990, 1991, 2007, 2016, 2001,
]
GATE_NOTE_YEARS = "/".join(GATE_YEARS)
GATE_NOTE_STEMS = "/".join(GATE_STEMS)
HOLD = "HOLD 0 STRICT wave2 after SK LIVE (HR)"
WAVE_POS = (
    "FOURTH of wave2 after GH EMPTY "
    "(HR SOFT_THIN_FINAL after DZ+MC+SK LIVE; then TH→SD→LB→FM→MM→IS — do NOT start those)"
)
DEST_CHAIN = "HR"
SRC_HOLD = "HOLD 0 STRICT wave2 after MC LIVE (SK)"
SRC_WAVE = (
    "THIRD of wave2 after GH EMPTY "
    "(SK SOFT_THIN_FINAL after DZ+MC LIVE; then HR→TH→SD→LB→FM→MM→IS — do NOT start those)"
)
SRC_CHAIN = "SK"

FILES = [
    ("slovakia_soft_filter.py", "croatia_soft_filter.py"),
    (f"slovakia_corpus_stream_{SRC_TIP_SHORT}.py", f"croatia_corpus_stream_{DST_TIP_SHORT}.py"),
    (f"slovakia_encode_memsafe_{SRC_TIP_SHORT}.py", f"croatia_encode_memsafe_{DST_TIP_SHORT}.py"),
    (f"slovakia_finish_from_emb_{SRC_TIP_SHORT}.py", f"croatia_finish_from_emb_{DST_TIP_SHORT}.py"),
    (f"slovakia_stream_graph_parts_{SRC_TIP_SHORT}.py", f"croatia_stream_graph_parts_{DST_TIP_SHORT}.py"),
    (f"slovakia_package_memsafe_{SRC_TIP_SHORT}.py", f"croatia_package_memsafe_{DST_TIP_SHORT}.py"),
    ("slovakia_upload.py", "croatia_upload.py"),
    ("slovakia_bm25_smoke.py", "croatia_bm25_smoke.py"),
    ("slovakia_write_publish_report.py", "croatia_write_publish_report.py"),
    (f"slovakia_orchestrator_{SRC_TIP_SHORT}.py", f"croatia_orchestrator_{DST_TIP_SHORT}.py"),
]

DISPLAY = "Croatia"
SLUG = "croatia"


def adapt(text: str, dst_name: str) -> str:
    for bad in (
        "cient-data", "prent-data", "stent-data", "cvent-data", "scent-data",
        "carent-data", "yement-data", "djiboutient-data", "marshallislandsent-data",
        "kiribatient-data", "burundient-data", "eswatinient-data", "niueent-data",
        "guineabissauent-data", "surinameent-data", "equatorialguineaent-data",
        "guyanaent-data", "beninent-data", "somaliaent-data", "maldivesent-data",
        "arubaent-data", "saint_vincent_grenadinesent-data", "vanuatuent-data",
        "ghanaent-data", "algeriaent-data", "monacoent-data", "slovakiaent-data",
        "croatiaent-data",
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
    text = text.replace("after-MC", "\x00AFTERMC\x00")
    text = text.replace("after MC ", "\x00AFTERMC_SP\x00")
    text = text.replace("MC LIVE", "\x00MCLIVE\x00")
    text = text.replace("DZ+MC+SK", "\x00DZMCSK\x00")
    text = text.replace("DZ+MC", "\x00DZMC\x00")
    text = text.replace("GH EMPTY", "\x00GHEMPTY\x00")
    text = text.replace("SOFT_THIN_FINAL", "\x00DESTMODE\x00")
    text = text.replace("do NOT start Croatia or any other country", "\x00DONOTSTART\x00")
    text = text.replace("do NOT start Croatia or any other", "\x00DONOTSTART2\x00")
    text = text.replace("do NOT start HR/TH/SD/LB/FM/MM/IS", "\x00DONOTREBUILD\x00")
    text = text.replace("do NOT start any other country", "\x00DONOTSTART\x00")
    text = text.replace("do NOT start any other", "\x00DONOTSTART2\x00")
    text = text.replace("67930c3f-c94b-445b-a5bc-01d3fc1135c1", "\x00UUID94\x00")

    # Tip swaps FIRST, then protect DST tip before digit floor swaps
    text = text.replace(SRC_TIP_FULL, DST_TIP_FULL)
    text = text.replace(SRC_TIP_SHORT, DST_TIP_SHORT)
    text = text.replace(DST_TIP_FULL, "\x00TIPSHA_PROTECT\x00")
    text = text.replace(DST_TIP_SHORT, "\x00TIPSHORT_PROTECT\x00")

    reps = [
        ("endomorphosis/ipfs_slovakia_laws", "endomorphosis/ipfs_croatia_laws"),
        ("justicedao/ipfs_slovakia_laws_ir", "justicedao/ipfs_croatia_laws_ir"),
        ("ipfs_slovakia_laws_ir", "ipfs_croatia_laws_ir"),
        ("ipfs_slovakia_laws", "ipfs_croatia_laws"),
        ("\x00DESTHOLD\x00", HOLD),
        ("\x00DESTWAVE\x00", WAVE_POS),
        ("\x00DESTCHAIN\x00", DEST_CHAIN),
        ("\x00DESTMODE\x00", "SOFT_THIN_FINAL"),
        ("\x00AFTERMC\x00", "after-SK"),
        ("\x00AFTERMC_SP\x00", "after SK "),
        ("\x00MCLIVE\x00", "SK LIVE"),
        ("\x00DZMCSK\x00", "DZ+MC+SK"),
        ("\x00DZMC\x00", "DZ+MC"),
        ("\x00GHEMPTY\x00", "GH EMPTY"),
        ("\x00DONOTSTART\x00", "do NOT start Thailand or any other country"),
        ("\x00DONOTSTART2\x00", "do NOT start Thailand or any other"),
        ("\x00DONOTREBUILD\x00", "do NOT start TH/SD/LB/FM/MM/IS"),
        # URLs
        ("www/slov-lex.sk", "www/narodne-novine.nn.hr"),
        ("static.slov-lex.sk", "narodne-novine.nn.hr"),
        ("slov-lex.sk", "narodne-novine.nn.hr"),
        ("www.slov-lex.sk", "www.narodne-novine.nn.hr"),
        ("slov-lex", "narodne-novine"),
        # Language / country
        ("Slovak (Slovakia)", "Croatian (Croatia)"),
        ("Slovak Slovakia", "Croatian Croatia"),
        ("ASCII-fold Slovak", "ASCII-fold Croatian"),
        ("Slovak legal stems", "Croatian legal stems"),
        ("Slovak legal corpus", "Croatian legal corpus"),
        ("Slovak/EN legal stems", "Croatian legal stems"),
        ("Slovak GATE", "Croatian GATE"),
        ("Slovakia", DISPLAY),
        ("slovakia_ranked", "croatia_ranked"),
        ("slovakia_gate", "croatia_gate"),
        ("slovakia_pass", "croatia_pass"),
        ("slovakia_encode_memsafe", "croatia_encode_memsafe"),
        ("slovakia_package_memsafe", "croatia_package_memsafe"),
        ("slovakia_corpus_stream", "croatia_corpus_stream"),
        ("slovakia_encode_done", "croatia_encode_done"),
        ("slovakia_filtered_", "croatia_filtered_"),
        ("slovakia_", "croatia_"),
        ('"SK"', '"HR"'),
        ("SK-attested", "HR-attested"),
        ("(SK)", "(HR)"),
        ('"sk"', '"hr"'),
        # floors 16799/179 → 30315/108 — compound first (tips protected)
        ("16799/179", "30315/108"),
        ("16799 / 179", "30315 / 108"),
        ("16799, 179", "30315, 108"),
        ("FLOOR_LAWS, FLOOR_ARTS = 16799, 179", "FLOOR_LAWS, FLOOR_ARTS = 30315, 108"),
        ('int(pack.get("n_laws") or 16799)', 'int(pack.get("n_laws") or 30315)'),
        ('int(pack.get("n_articles") or 179)', 'int(pack.get("n_articles") or 108)'),
        ("@ 16799/", "@ 30315/"),
        ("floor 16799/", "floor 30315/"),
        ("(16799/", "(30315/"),
        (" 179", " 108"),
        ("179", "108"),
        ("= 16799,", "= 30315,"),
        ("or 16799)", "or 30315)"),
        ("or 16799,", "or 30315,"),
        ("or 16799}", "or 30315}"),
        ("= 16799", "= 30315"),
        (" 16799/", " 30315/"),
        ("16799", "30315"),
        ('"language": "Slovak"', '"language": "Croatian"'),
        ('"lang": "Slovak"', '"lang": "Croatian"'),
        ("language: Slovak", "language: Croatian"),
        ("Language: Slovak", "Language: Croatian"),
    ]
    for a, b in reps:
        text = text.replace(a, b)

    text = text.replace("\x00TIPSHA_PROTECT\x00", DST_TIP_FULL)
    text = text.replace("\x00TIPSHORT_PROTECT\x00", DST_TIP_SHORT)

    text = re.sub(r"(?<![A-Za-z0-9_])slovakia(?![A-Za-z0-9_])", SLUG, text)

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
    text = text.replace('"country": "slovakia"', f'"country": "{SLUG}"')
    text = text.replace(f"# {SLUG} filtered pack", f"# {DISPLAY} filtered pack")
    text = text.replace(f"{SLUG} laws IR release", f"{DISPLAY} laws IR release")

    for bad in (
        "cient-data", "prent-data", "stent-data", "cvent-data", "scent-data",
        "slovakiaent-data", "croatiaent-data",
    ):
        text = text.replace(f"/home/box/{bad}/", "/home/box/agent-data/")
        text = text.replace(bad, "agent-data")

    if dst_name == "croatia_bm25_smoke.py":
        start = text.index("GATE = [")
        end = text.index("]", start) + 1
        years_line = ", ".join(f'"{y}"' for y in GATE_YEARS)
        stems_line = ", ".join(f'"{s}"' for s in GATE_STEMS)
        gate = f"GATE = [\n    {years_line},\n    {stems_line},\n]"
        text = text[:start] + gate + text[end:]
        text = re.sub(
            r"QUERIES = GATE \+ \[[^\]]*\]",
            'QUERIES = GATE + ["www", "narodne-novine.nn.hr", "www.narodne-novine.nn.hr", "nn.hr", "nn", "hr", "clan", "zakona", "clanka", "sabor", "predsjednik", "kazneni"]',
            text,
            count=1,
        )
        text = re.sub(
            r'"""BM25 smoke for .*?"""',
            '"""BM25 smoke for Croatia IR — Croatian legal corpus; years + Croatian legal stems FTS gate.\n\n'
            "GATE is attested ASCII years plus Croatian legal stems present in articles.parquet\n"
            "(ASCII-fold). URL narodne-novine.nn.hr is query-only, never GATE. Every GATE token must rank a hit.\n"
            '"""',
            text,
            count=1,
            flags=re.S,
        )
        note = (
            f"attested years {GATE_NOTE_YEARS} plus Croatian legal stems {GATE_NOTE_STEMS} "
            f"from articles.parquet HEAD tip {DST_TIP_SHORT}; URL narodne-novine.nn.hr "
            f"is query-only, not GATE."
        )
        text = re.sub(r'"tokenizer_note":\s*"[^"]*"', f'"tokenizer_note": "{note}"', text, count=1)
        text = re.sub(r"GATE = attested years [^\"\n]+", f"GATE = {note}", text, count=1)
        text = text.replace("slovakia_pass", "croatia_pass").replace("slovakia_gate", "croatia_gate")

    if dst_name == "croatia_write_publish_report.py":
        gate_note = (
            f"BM25 PASS on Croatia ASCII-fold Croatian GATE "
            f"(attested years {GATE_NOTE_YEARS} + stems {GATE_NOTE_STEMS}); "
            f"URL narodne-novine.nn.hr is query-only, not GATE"
        )
        text = re.sub(r'BM25 PASS on Croatia[^"]*"', gate_note + '"', text, count=1)
        text = re.sub(r'BM25 PASS on [^"]*GATE[^"]*"', gate_note + '"', text, count=1)
        text = re.sub(
            r"HOLD 0 STRICT[^;]*; collectors kept dead \(pkill\); soft never-thin ON[^\"\n]*",
            f"{HOLD}; collectors kept dead (pkill); soft never-thin ON (HR soft-thin OK); SKIP_US; Italy LIVE leave alone; {WAVE_POS}",
            text,
        )
        text = re.sub(r"[ \t]{2,}", " ", text)

    found = []
    for x in ("Slovakia", "slovakia", "slovenskej", "slov-lex", "znena", "nariadenie"):
        if re.search(rf"(?<![A-Za-z0-9_/-]){re.escape(x)}(?![A-Za-z0-9_])", text):
            # allow in QUERIES leftovers only if smoke not yet rewritten — hard fail country
            if x in ("Slovakia", "slovakia", "slov-lex"):
                found.append(x)
    if found:
        raise RuntimeError(f"language/country leftovers in {dst_name}: {found}")

    if dst_name.endswith("_bm25_smoke.py"):
        gate_slice = text[text.index("GATE = ["): text.index("]", text.index("GATE = [")) + 1]
        for bad in (
            "slovakia", "slovenskej", "republiky", "ministerstvo", "slovak", "republic",
            "nariadenie", "znena", "agreement", "convention", "treaty", "article",
            "monaco", "loi", "zakona",  # zakona is query-only for HR, not GATE
        ):
            if f'"{bad}"' in gate_slice:
                raise RuntimeError(f"non-HR token in GATE of {dst_name}: {bad}")
        for stem in GATE_STEMS:
            if f'"{stem}"' not in gate_slice:
                raise RuntimeError(f"missing stem in GATE of {dst_name}: {stem}")
        for year in GATE_YEARS:
            if f'"{year}"' not in gate_slice:
                raise RuntimeError(f"missing year in GATE of {dst_name}: {year}")
        if "slov-lex" in text:
            raise RuntimeError(f"leftover slov-lex in {dst_name}")

    scrub = text
    for prot in (WAVE_POS, HOLD, DEST_CHAIN, SRC_HOLD, SRC_WAVE):
        scrub = scrub.replace(prot, "XX")
    scrub = scrub.replace("after-SK", "after-XX").replace("after SK ", "after XX ")
    scrub = scrub.replace("SK LIVE", "XX LIVE").replace("DZ+MC+SK", "XX").replace("DZ+MC", "XX")
    scrub = scrub.replace("GH EMPTY", "XX EMPTY")
    if re.search(r"(?<![A-Za-z0-9_])slovakia(?![A-Za-z0-9_])", scrub):
        m = re.search(r"(?<![A-Za-z0-9_])slovakia(?![A-Za-z0-9_])", scrub)
        raise RuntimeError(f"leftover slovakia in {dst_name}: ...{scrub[max(0,m.start()-20):m.start()+20]}...")
    if re.search(r"(?<![A-Za-z%])SK(?![A-Za-z])", scrub):
        m = re.search(r"(?<![A-Za-z%])SK(?![A-Za-z])", scrub)
        raise RuntimeError(f"leftover SK in {dst_name}: ...{scrub[max(0,m.start()-30):m.start()+30]}...")
    if "ipfs_slovakia" in text:
        raise RuntimeError(f"leftover slovakia path in {dst_name}")
    if SRC_TIP_SHORT in text or SRC_TIP_FULL in text:
        raise RuntimeError(f"src tip leftover in {dst_name}")
    if DST_TIP_SHORT not in text and any(x in dst_name for x in ("soft_filter", "orchestrator", "bm25_smoke")):
        raise RuntimeError(f"missing DST tip in {dst_name}")
    for m in re.finditer(r"9469c387c221[0-9a-f]*", text):
        frag = m.group(0)
        if len(frag) >= 40 and frag != DST_TIP_FULL:
            raise RuntimeError(f"corrupted tip SHA in {dst_name}: {frag}")
        if 12 < len(frag) < 40:
            raise RuntimeError(f"truncated/partial tip SHA in {dst_name}: {frag}")
    if "soft_filter" in dst_name or "corpus_stream" in dst_name:
        if "data/laws.parquet" not in text and 'data" / "laws.parquet"' not in text:
            if '"data"' not in text and "/data/" not in text:
                raise RuntimeError(f"missing data/ parquet paths in {dst_name}")
    if "16799/179" in text or "FLOOR_LAWS, FLOOR_ARTS = 16799" in text:
        raise RuntimeError(f"OLD slovakia floor leftover in {dst_name}")
    if "write_publish" in dst_name or "bm25_smoke" in dst_name:
        if re.search(r"ASCII-fold Slovak|Slovak legal|ASCII-fold French|French legal", text):
            raise RuntimeError(f"leftover prior-language phrasing in {dst_name}")
    return text


for src_name, dst_name in FILES:
    src = ROOT / src_name
    if not src.is_file():
        raise FileNotFoundError(src)
    (ROOT / dst_name).write_text(adapt(src.read_text(encoding="utf-8"), dst_name), encoding="utf-8")
    print(f"wrote {dst_name}")

for _, dst_name in FILES:
    t = (ROOT / dst_name).read_text(encoding="utf-8")
    for m in re.finditer(r"9469c387c221[0-9a-f]{20,}", t):
        if m.group(0) != DST_TIP_FULL:
            raise RuntimeError(f"post-write corrupted tip in {dst_name}: {m.group(0)}")

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
        if entry.get("slug") == SLUG or entry.get("iso2") == "HR":
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
                "language": "Croatian",
                "lang": "Croatian",
                "iso2": "HR",
                "slug": SLUG,
                "repo": "endomorphosis/ipfs_croatia_laws",
                "years_attested": YEARS_ATTESTED,
                "gate_years": [int(y) for y in GATE_YEARS],
                "gate_stems": GATE_STEMS,
                "note": (
                    f"HR SOFT_THIN_FINAL scaffold; tip MATCH {DST_TIP_SHORT}@30315/108; {HOLD}; "
                    f"soft-thin OK; SKIP_US; Italy LIVE leave alone; {WAVE_POS}; "
                    f"Croatian GATE ({len(GATE_YEARS)} years + {len(GATE_STEMS)} stems); "
                    f"memsafe only; do NOT start Thailand or any other country"
                ),
                "status": "CLAIMED",
                "mode": "SOFT_THIN_FINAL",
                "wave_end": False,
                "do_not_start": False,
            })
            break
    else:
        raise RuntimeError(f"Croatia / HR entry missing from wave JSON {wave}")
    data["wave_status"] = "IN_PROGRESS_HR"
    data["hold"] = HOLD
    data["current"] = SLUG
    data["do_not_start_next"] = "thailand"
    data["next"] = "thailand"
    data["hold_note"] = (
        "HOLD 0 STRICT for HR SOFT_THIN_FINAL build in progress; "
        "do NOT start Thailand or any other country; DZ+MC+SK LIVE leave alone"
    )
    wave.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"updated wave JSON {wave}")

print("GATE years", GATE_YEARS)
print("GATE stems", GATE_STEMS)
print("TIP_FULL", DST_TIP_FULL)
print("soft-thin memsafe: 30315/108; only HR")
