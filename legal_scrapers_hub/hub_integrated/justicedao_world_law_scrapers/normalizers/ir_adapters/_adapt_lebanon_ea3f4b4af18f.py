#!/usr/bin/env python3
"""Adapt Sudan Arabic memsafe SOFT_THIN_FINAL pack to Lebanon LB tip ea3f4b4af18f.

Arabic/French/English (laws mostly ar; article corpus English Special Tribunal +
leb. government text). GATE = attested ASCII years + stems in article title/body.
URL pcm.gov.lb query-only. SOFT_THIN_FINAL; HOLD 0 STRICT wave2 SEVENTH after
DZ+MC+SK+HR+TH+SD LIVE (LB; then FM→MM→IS). Soft never-thin ON except soft-thin OK;
SKIP_US; Italy LIVE leave alone; KW HOLD_THIN; AT queued-only; P1 CLOSED.
Do NOT rebuild priors. Do NOT start FSM.
CRITICAL:
- protect tip SHA (contains substring "283" inside ...b8283fa...)
- protect SOFT_THIN_FINAL BEFORE any ISO swaps (SD lesson: TH→SD ate THIN)
- floor 56/69 → 108/56: arts DST is 56 (= SRC laws 56) — use placeholders
Floor ≥108/56.
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
SRC_TIP_FULL = "6a063943f9df8c4b35026fc57aab1e50cef4d1a0"
SRC_TIP_SHORT = "6a063943f9df"
DST_TIP_FULL = "ea3f4b4af18f065b2d1d144254b8283fa52fd354"
DST_TIP_SHORT = "ea3f4b4af18f"
FLOOR_LAWS, FLOOR_ARTS = 108, 56
SRC_FLOOR_L, SRC_FLOOR_A = 56, 69

GATE_YEARS = [
    "2006", "2005", "2004", "1967", "1973",
    "2003", "1992",
]
GATE_STEMS = [
    "article", "shall", "tribunal", "lebanon", "government",
    "special", "justice", "law", "ministry", "prosecutor", "chamber",
]
YEARS_ATTESTED = [int(y) for y in GATE_YEARS] + [2007, 1961, 1958]
GATE_NOTE_YEARS = "/".join(GATE_YEARS)
GATE_NOTE_STEMS = "/".join(GATE_STEMS)
HOLD = "HOLD 0 STRICT wave2 after SD LIVE (LB)"
WAVE_POS = (
    "SEVENTH of wave2 after GH EMPTY "
    "(LB SOFT_THIN_FINAL after DZ+MC+SK+HR+TH+SD LIVE; then FM→MM→IS — do NOT start those)"
)
DEST_CHAIN = "LB"
SRC_HOLD = "HOLD 0 STRICT wave2 after TH LIVE (SD)"
SRC_WAVE = (
    "SIXTH of wave2 after GH EMPTY "
    "(SD SOFT_THIN_FINAL after DZ+MC+SK+HR+TH LIVE; then LB→FM→MM→IS — do NOT start those)"
)
SRC_CHAIN = "SD"

FILES = [
    ("sudan_soft_filter.py", "lebanon_soft_filter.py"),
    (f"sudan_corpus_stream_{SRC_TIP_SHORT}.py", f"lebanon_corpus_stream_{DST_TIP_SHORT}.py"),
    (f"sudan_encode_memsafe_{SRC_TIP_SHORT}.py", f"lebanon_encode_memsafe_{DST_TIP_SHORT}.py"),
    (f"sudan_finish_from_emb_{SRC_TIP_SHORT}.py", f"lebanon_finish_from_emb_{DST_TIP_SHORT}.py"),
    (f"sudan_stream_graph_parts_{SRC_TIP_SHORT}.py", f"lebanon_stream_graph_parts_{DST_TIP_SHORT}.py"),
    (f"sudan_package_memsafe_{SRC_TIP_SHORT}.py", f"lebanon_package_memsafe_{DST_TIP_SHORT}.py"),
    ("sudan_upload.py", "lebanon_upload.py"),
    ("sudan_bm25_smoke.py", "lebanon_bm25_smoke.py"),
    ("sudan_write_publish_report.py", "lebanon_write_publish_report.py"),
    (f"sudan_orchestrator_{SRC_TIP_SHORT}.py", f"lebanon_orchestrator_{DST_TIP_SHORT}.py"),
]

DISPLAY = "Lebanon"
SLUG = "lebanon"


def adapt(text: str, dst_name: str) -> str:
    for bad in (
        "cient-data", "sudanent-data", "lebanonent-data", "thailandent-data",
    ):
        text = text.replace(f"/home/box/{bad}/", "/home/box/agent-data/")
        text = text.replace(bad, "agent-data")

    text = text.replace("BM25", "\x00BM25\x00").replace("bm25", "\x00bm25\x00")
    text = text.replace("bmjacency", "adjacency")

    # CRITICAL: protect SOFT_THIN_FINAL BEFORE any ISO/chain swaps
    text = text.replace("SOFT_THIN_FINAL", "\x00DESTMODE\x00")

    text = text.replace(SRC_HOLD, "\x00DESTHOLD\x00")
    text = text.replace(SRC_WAVE, "\x00DESTWAVE\x00")
    text = text.replace(HOLD, "\x00DESTHOLD\x00")
    text = text.replace(WAVE_POS, "\x00DESTWAVE\x00")
    # Do NOT bare-replace SRC_CHAIN "SD" — could hit unrelated tokens; use quoted forms in reps
    text = text.replace("after-TH", "\x00AFTERTH\x00")
    text = text.replace("after TH ", "\x00AFTERTH_SP\x00")
    text = text.replace("TH LIVE", "\x00THLIVE\x00")
    text = text.replace("DZ+MC+SK+HR+TH+SD", "\x00PRIORS\x00")
    text = text.replace("DZ+MC+SK+HR+TH", "\x00DZMCSKHRTH\x00")
    text = text.replace("GH EMPTY", "\x00GHEMPTY\x00")
    text = text.replace("do NOT start Lebanon or any other country", "\x00DONOTSTART\x00")
    text = text.replace("do NOT start Lebanon or any other", "\x00DONOTSTART2\x00")
    text = text.replace("do NOT start LB/FM/MM/IS", "\x00DONOTREBUILD\x00")
    text = text.replace("do NOT start any other country", "\x00DONOTSTART\x00")
    text = text.replace("do NOT start any other", "\x00DONOTSTART2\x00")
    text = text.replace("67930c3f-c94b-445b-a5bc-01d3fc1135c1", "\x00UUID94\x00")

    # Tip swaps FIRST, then protect DST tip (contains "283" inside b8283)
    text = text.replace(SRC_TIP_FULL, DST_TIP_FULL)
    text = text.replace(SRC_TIP_SHORT, DST_TIP_SHORT)
    text = text.replace(DST_TIP_FULL, "\x00TIPSHA_PROTECT\x00")
    text = text.replace(DST_TIP_SHORT, "\x00TIPSHORT_PROTECT\x00")

    # Floor swap with placeholders: SRC 56/69 → DST 108/56 (56 is both SRC laws and DST arts)
    text = text.replace("56/69", "\x00FLOOR_LA\x00")
    text = text.replace("56 / 69", "\x00FLOOR_LA_SP\x00")
    text = text.replace("56, 69", "\x00FLOOR_LA_C\x00")
    text = text.replace("FLOOR_LAWS, FLOOR_ARTS = 56, 69", "\x00FLOOR_ASSIGN\x00")
    text = text.replace('int(pack.get("n_laws") or 56)', "\x00OR_LAWS\x00")
    text = text.replace('int(pack.get("n_articles") or 69)', "\x00OR_ARTS\x00")
    # remaining 69 → arts 56; remaining bare 56 → laws 108
    text = text.replace(" 69", "\x00ARTS\x00")
    text = text.replace("69", "\x00ARTS\x00")
    text = text.replace(" 56", "\x00LAWS\x00")
    text = text.replace("56", "\x00LAWS\x00")
    # restore floors
    text = text.replace("\x00FLOOR_LA\x00", "108/56")
    text = text.replace("\x00FLOOR_LA_SP\x00", "108 / 56")
    text = text.replace("\x00FLOOR_LA_C\x00", "108, 56")
    text = text.replace("\x00FLOOR_ASSIGN\x00", "FLOOR_LAWS, FLOOR_ARTS = 108, 56")
    text = text.replace("\x00OR_LAWS\x00", 'int(pack.get("n_laws") or 108)')
    text = text.replace("\x00OR_ARTS\x00", 'int(pack.get("n_articles") or 56)')
    text = text.replace("\x00ARTS\x00", "56")
    text = text.replace("\x00LAWS\x00", "108")

    reps = [
        ("endomorphosis/ipfs_sudan_laws", "endomorphosis/ipfs_lebanon_laws"),
        ("justicedao/ipfs_sudan_laws_ir", "justicedao/ipfs_lebanon_laws_ir"),
        ("ipfs_sudan_laws_ir", "ipfs_lebanon_laws_ir"),
        ("ipfs_sudan_laws", "ipfs_lebanon_laws"),
        ("\x00DESTHOLD\x00", HOLD),
        ("\x00DESTWAVE\x00", WAVE_POS),
        ("\x00DESTMODE\x00", "SOFT_THIN_FINAL"),
        ("\x00AFTERTH\x00", "after-SD"),
        ("\x00AFTERTH_SP\x00", "after SD "),
        ("\x00THLIVE\x00", "SD LIVE"),
        ("\x00PRIORS\x00", "DZ+MC+SK+HR+TH+SD"),
        ("\x00DZMCSKHRTH\x00", "DZ+MC+SK+HR+TH"),
        ("\x00GHEMPTY\x00", "GH EMPTY"),
        ("\x00DONOTSTART\x00", "do NOT start FSM or any other country"),
        ("\x00DONOTSTART2\x00", "do NOT start FSM or any other"),
        ("\x00DONOTREBUILD\x00", "do NOT start FM/MM/IS"),
        # URLs
        ("www/moj.gov.sd", "www/pcm.gov.lb"),
        ("moj.gov.sd", "pcm.gov.lb"),
        ("www.moj.gov.sd", "www.pcm.gov.lb"),
        ("gov.sd", "gov.lb"),
        # Language / country — display before slug
        ("Arabic/English (Sudan)", "Arabic/English (Lebanon)"),
        ("Arabic/English Sudan", "Arabic/English Lebanon"),
        ("ASCII-fold Sudan", "ASCII-fold Lebanon"),
        ("Sudan ASCII legal stems", "Lebanon ASCII legal stems"),
        ("Sudan legal corpus", "Lebanon legal corpus"),
        ("Sudan ASCII GATE", "Lebanon ASCII GATE"),
        ("Arabic script", "Arabic/English script"),
        ("Sudan", DISPLAY),
        ("sudan_ranked", "lebanon_ranked"),
        ("sudan_gate", "lebanon_gate"),
        ("sudan_pass", "lebanon_pass"),
        ("sudan_encode_memsafe", "lebanon_encode_memsafe"),
        ("sudan_package_memsafe", "lebanon_package_memsafe"),
        ("sudan_corpus_stream", "lebanon_corpus_stream"),
        ("sudan_encode_done", "lebanon_encode_done"),
        ("sudan_filtered_", "lebanon_filtered_"),
        ("sudan_", "lebanon_"),
        ('"SD"', '"LB"'),
        ("SD-attested", "LB-attested"),
        ("(SD)", "(LB)"),
        ('"sd"', '"lb"'),
        ('"language": "Arabic"', '"language": "Arabic"'),
        ('"lang": "Arabic"', '"lang": "Arabic"'),
    ]
    for a, b in reps:
        text = text.replace(a, b)

    text = text.replace("\x00TIPSHA_PROTECT\x00", DST_TIP_FULL)
    text = text.replace("\x00TIPSHORT_PROTECT\x00", DST_TIP_SHORT)

    text = re.sub(r"(?<![A-Za-z0-9_])sudan(?![A-Za-z0-9_])", SLUG, text)

    text = text.replace("\x00BM25\x00", "BM25").replace("\x00bm25\x00", "bm25")
    text = text.replace("\x00DESTHOLD\x00", HOLD)
    text = text.replace("\x00DESTWAVE\x00", WAVE_POS)
    text = text.replace("\x00DESTMODE\x00", "SOFT_THIN_FINAL")
    text = text.replace("\x00UUID94\x00", "67930c3f-c94b-445b-a5bc-01d3fc1135c1")

    text = text.replace(f'"name": "{SLUG}"', f'"name": "{DISPLAY}"')
    text = text.replace(f'"slug": "{DISPLAY}"', f'"slug": "{SLUG}"')
    text = text.replace(f'SLUG = "{DISPLAY}"', f'SLUG = "{SLUG}"')
    text = text.replace(f'"country": "{DISPLAY}"', f'"country": "{SLUG}"')
    text = text.replace('"country": "sudan"', f'"country": "{SLUG}"')
    text = text.replace(f"# {SLUG} filtered pack", f"# {DISPLAY} filtered pack")
    text = text.replace(f"{SLUG} laws IR release", f"{DISPLAY} laws IR release")

    for bad in ("cient-data", "sudanent-data", "lebanonent-data"):
        text = text.replace(f"/home/box/{bad}/", "/home/box/agent-data/")
        text = text.replace(bad, "agent-data")

    if dst_name == "lebanon_bm25_smoke.py":
        start = text.index("GATE = [")
        end = text.index("]", start) + 1
        years_line = ", ".join(f'"{y}"' for y in GATE_YEARS)
        stems_line = ", ".join(f'"{s}"' for s in GATE_STEMS)
        gate = f"GATE = [\n    {years_line},\n    {stems_line},\n]"
        text = text[:start] + gate + text[end:]
        text = re.sub(
            r"QUERIES = GATE \+ \[[^\]]*\]",
            'QUERIES = GATE + ["www", "pcm.gov.lb", "www.pcm.gov.lb", "jo.pcm.gov.lb", "pcm", "gov.lb", "lb", "housing", "compensation", "trial", "judges", "مادة", "قانون", "مرسوم"]',
            text,
            count=1,
        )
        text = re.sub(
            r'"""BM25 smoke for .*?"""',
            '"""BM25 smoke for Lebanon IR — Arabic/English legal corpus; ASCII-indexed FTS gate.\n\n'
            "GATE is attested ASCII years + stems from article title/body (article/shall/tribunal/…).\n"
            "Arabic script and URL pcm.gov.lb are query-only, never GATE.\n"
            '"""',
            text,
            count=1,
            flags=re.S,
        )
        note = (
            f"Lebanon ASCII GATE: attested years {GATE_NOTE_YEARS} plus stems {GATE_NOTE_STEMS} "
            f"from articles.parquet HEAD tip {DST_TIP_SHORT}; Arabic stems and URL pcm.gov.lb "
            f"are query-only, not GATE."
        )
        text = re.sub(r'"tokenizer_note":\s*"[^"]*"', f'"tokenizer_note": "{note}"', text, count=1)
        text = text.replace("sudan_pass", "lebanon_pass").replace("sudan_gate", "lebanon_gate")

    if dst_name == "lebanon_write_publish_report.py":
        gate_note = (
            f"BM25 PASS on Lebanon ASCII-fold Lebanon ASCII GATE "
            f"(attested years {GATE_NOTE_YEARS} + stems {GATE_NOTE_STEMS}); "
            f"URL pcm.gov.lb is query-only, not GATE"
        )
        text = re.sub(r'BM25 PASS on Lebanon[^"]*"', gate_note + '"', text, count=1)
        text = re.sub(r'BM25 PASS on [^"]*GATE[^"]*"', gate_note + '"', text, count=1)
        text = re.sub(
            r"HOLD 0 STRICT[^;]*; collectors kept dead \(pkill\); soft never-thin ON[^\"\n]*",
            f"{HOLD}; collectors kept dead (pkill); soft never-thin ON (LB soft-thin OK); SKIP_US; Italy LIVE leave alone; {WAVE_POS}",
            text,
        )
        text = re.sub(r"[ \t]{2,}", " ", text)

    found = []
    for x in ("Sudan", "sudan", "moj.gov.sd", "gazette", "SOFT_SDIN"):
        if x == "gazette":
            continue
        if re.search(rf"(?<![A-Za-z0-9_/-]){re.escape(x)}(?![A-Za-z0-9_])", text):
            if x in ("Sudan", "sudan", "moj.gov.sd", "SOFT_SDIN"):
                found.append(x)
    if found:
        raise RuntimeError(f"language/country leftovers in {dst_name}: {found}")

    if "\x00" in text:
        raise RuntimeError(f"null byte leftover in {dst_name}")
    if "SOFT_SDIN" in text or "SOFT_LBIN" in text:
        raise RuntimeError(f"SOFT_THIN corruption in {dst_name}")

    if dst_name.endswith("_bm25_smoke.py"):
        gate_slice = text[text.index("GATE = ["): text.index("]", text.index("GATE = [")) + 1]
        for bad in (
            "sudan", "republic", "gazette", "published", "authority", "issue",
            "2018", "2019", "1967", "1951", "1969",  # SD years may overlap 1967 — 1967 is OK for LB too
        ):
            if bad in ("1967",):
                continue  # shared year OK if in GATE_YEARS
            if f'"{bad}"' in gate_slice and bad not in GATE_STEMS and bad not in GATE_YEARS:
                raise RuntimeError(f"non-LB token in GATE of {dst_name}: {bad}")
        for stem in GATE_STEMS:
            if f'"{stem}"' not in gate_slice:
                raise RuntimeError(f"missing stem in GATE of {dst_name}: {stem}")
        for year in GATE_YEARS:
            if f'"{year}"' not in gate_slice:
                raise RuntimeError(f"missing year in GATE of {dst_name}: {year}")
        if "moj.gov.sd" in text:
            raise RuntimeError(f"leftover moj.gov.sd in {dst_name}")

    scrub = text
    for prot in (WAVE_POS, HOLD, DEST_CHAIN, SRC_HOLD, SRC_WAVE):
        scrub = scrub.replace(prot, "XX")
    scrub = scrub.replace("after-SD", "after-XX").replace("after SD ", "after XX ")
    scrub = scrub.replace("SD LIVE", "XX LIVE").replace("DZ+MC+SK+HR+TH+SD", "XX")
    scrub = scrub.replace("DZ+MC+SK+HR+TH", "XX").replace("GH EMPTY", "XX EMPTY")
    if re.search(r"(?<![A-Za-z0-9_])sudan(?![A-Za-z0-9_])", scrub):
        m = re.search(r"(?<![A-Za-z0-9_])sudan(?![A-Za-z0-9_])", scrub)
        raise RuntimeError(f"leftover sudan in {dst_name}: ...{scrub[max(0,m.start()-20):m.start()+20]}...")
    if re.search(r"(?<![A-Za-z%])SD(?![A-Za-z])", scrub):
        m = re.search(r"(?<![A-Za-z%])SD(?![A-Za-z])", scrub)
        raise RuntimeError(f"leftover SD in {dst_name}: ...{scrub[max(0,m.start()-30):m.start()+30]}...")
    if "ipfs_sudan" in text:
        raise RuntimeError(f"leftover sudan path in {dst_name}")
    if SRC_TIP_SHORT in text or SRC_TIP_FULL in text:
        raise RuntimeError(f"src tip leftover in {dst_name}")
    if DST_TIP_SHORT not in text and any(x in dst_name for x in ("soft_filter", "orchestrator", "bm25_smoke")):
        raise RuntimeError(f"missing DST tip in {dst_name}")
    for m in re.finditer(r"ea3f4b4af18f[0-9a-f]*", text):
        frag = m.group(0)
        if len(frag) >= 40 and frag != DST_TIP_FULL:
            raise RuntimeError(f"corrupted tip SHA in {dst_name}: {frag}")
        if 12 < len(frag) < 40:
            raise RuntimeError(f"truncated/partial tip SHA in {dst_name}: {frag}")
    # tip must still contain b8283fa (283 substring intact)
    if DST_TIP_FULL in text and "b8283fa52fd354" not in text:
        raise RuntimeError(f"tip 283-region corrupted in {dst_name}")
    if "soft_filter" in dst_name or "corpus_stream" in dst_name:
        if "data/laws.parquet" not in text and 'data" / "laws.parquet"' not in text:
            if '"data"' not in text and "/data/" not in text:
                raise RuntimeError(f"missing data/ parquet paths in {dst_name}")
    if "56/69" in text or "FLOOR_LAWS, FLOOR_ARTS = 56, 69" in text:
        raise RuntimeError(f"OLD sudan floor leftover in {dst_name}")
    if "FLOOR_LAWS, FLOOR_ARTS = 108, 56" not in text and "soft_filter" in dst_name:
        raise RuntimeError(f"missing DST floor assign in {dst_name}")
    if "write_publish" in dst_name or "bm25_smoke" in dst_name:
        if re.search(r"Sudan ASCII GATE|moj\.gov\.sd|ASCII-fold Sudan", text):
            raise RuntimeError(f"leftover Sudan phrasing in {dst_name}")
    return text


for src_name, dst_name in FILES:
    src = ROOT / src_name
    if not src.is_file():
        raise FileNotFoundError(src)
    (ROOT / dst_name).write_text(adapt(src.read_text(encoding="utf-8"), dst_name), encoding="utf-8")
    print(f"wrote {dst_name}")

for _, dst_name in FILES:
    raw = (ROOT / dst_name).read_bytes()
    if b"\x00" in raw:
        raise RuntimeError(f"null bytes in {dst_name}")
    t = raw.decode()
    for m in re.finditer(r"ea3f4b4af18f[0-9a-f]{20,}", t):
        if m.group(0) != DST_TIP_FULL:
            raise RuntimeError(f"post-write corrupted tip in {dst_name}: {m.group(0)}")
    if "SOFT_SDIN" in t or "SOFT_LBIN" in t:
        raise RuntimeError(f"SOFT_THIN corruption in {dst_name}")
    if DST_TIP_FULL in t and "b8283fa52fd354" not in t:
        raise RuntimeError(f"tip tail corrupted in {dst_name}")

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
        if entry.get("slug") == SLUG or entry.get("iso2") == "LB":
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
                "language": "Arabic",
                "lang": "Arabic",
                "iso2": "LB",
                "slug": SLUG,
                "repo": "endomorphosis/ipfs_lebanon_laws",
                "years_attested": YEARS_ATTESTED,
                "gate_years": [int(y) for y in GATE_YEARS],
                "gate_stems": GATE_STEMS,
                "note": (
                    f"LB SOFT_THIN_FINAL scaffold; tip MATCH {DST_TIP_SHORT}@108/56; {HOLD}; "
                    f"soft-thin OK; SKIP_US; Italy LIVE leave alone; {WAVE_POS}; "
                    f"Lebanon ASCII GATE ({len(GATE_YEARS)} years + {len(GATE_STEMS)} stems); "
                    f"memsafe only; do NOT start FSM or any other country"
                ),
                "status": "CLAIMED",
                "mode": "SOFT_THIN_FINAL",
                "wave_end": False,
                "do_not_start": False,
            })
            break
    else:
        raise RuntimeError(f"Lebanon / LB entry missing from wave JSON {wave}")
    data["wave_status"] = "IN_PROGRESS_LB"
    data["hold"] = HOLD
    data["current"] = SLUG
    data["do_not_start_next"] = "fsm"
    data["next"] = "fsm"
    data["hold_note"] = (
        "HOLD 0 STRICT for LB SOFT_THIN_FINAL build in progress; "
        "do NOT start FSM or any other country; priors LIVE leave alone"
    )
    wave.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"updated wave JSON {wave}")

print("GATE years", GATE_YEARS)
print("GATE stems", GATE_STEMS)
print("TIP_FULL", DST_TIP_FULL, "has_283_substr", "283" in DST_TIP_FULL)
print("soft-thin memsafe: 108/56; only LB")
