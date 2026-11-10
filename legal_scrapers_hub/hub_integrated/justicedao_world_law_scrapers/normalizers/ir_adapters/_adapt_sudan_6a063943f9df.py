#!/usr/bin/env python3
"""Adapt Thailand Thai memsafe SOFT_THIN_FINAL pack to Sudan SD tip 6a063943f9df.

Arabic/English (laws.language ar/en); article corpus Arabic-script-heavy with
English gazette boilerplate. BM25 tokenizer is ASCII-only — Arabic stems
unindexed. GATE = attested ASCII years + stems in article title/body
(sudan/republic/gazette/… + years 2018/…). Arabic + URL moj.gov.sd query-only.
SOFT_THIN_FINAL; HOLD 0 STRICT wave2 SIXTH after DZ+MC+SK+HR+TH LIVE
(SD; then LB→FM→MM→IS). Soft never-thin ON except soft-thin OK;
SKIP_US; Italy LIVE leave alone; KW HOLD_THIN; AT queued-only; P1 CLOSED.
Do NOT rebuild priors. Do NOT start Lebanon.
CRITICAL: protect tip SHA during floor digit replaces (TH tip contains "78").
Floor ≥56/69.
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
SRC_TIP_FULL = "cde9df4f9b72950a3bbdfd7b5e605213c78c1b63"
SRC_TIP_SHORT = "cde9df4f9b72"
DST_TIP_FULL = "6a063943f9df8c4b35026fc57aab1e50cef4d1a0"
DST_TIP_SHORT = "6a063943f9df"
FLOOR_LAWS, FLOOR_ARTS = 56, 69
SRC_FLOOR_L, SRC_FLOOR_A = 283, 78

GATE_YEARS = [
    "2018", "2019", "1967", "1951", "1969",
    "2005", "2014",
]
GATE_STEMS = [
    "sudan", "republic", "gazette", "published", "authority",
    "issue", "justice",
]
YEARS_ATTESTED = [int(y) for y in GATE_YEARS] + [1955, 1901, 1994, 1961, 1974, 1981, 2017, 1948, 1966, 1950, 1980]
GATE_NOTE_YEARS = "/".join(GATE_YEARS)
GATE_NOTE_STEMS = "/".join(GATE_STEMS)
HOLD = "HOLD 0 STRICT wave2 after TH LIVE (SD)"
WAVE_POS = (
    "SIXTH of wave2 after GH EMPTY "
    "(SD SOFT_THIN_FINAL after DZ+MC+SK+HR+TH LIVE; then LB→FM→MM→IS — do NOT start those)"
)
DEST_CHAIN = "SD"
SRC_HOLD = "HOLD 0 STRICT wave2 after HR LIVE (TH)"
SRC_WAVE = (
    "FIFTH of wave2 after GH EMPTY "
    "(TH SOFT_THIN_FINAL after DZ+MC+SK+HR LIVE; then SD→LB→FM→MM→IS — do NOT start those)"
)
SRC_CHAIN = "TH"

FILES = [
    ("thailand_soft_filter.py", "sudan_soft_filter.py"),
    (f"thailand_corpus_stream_{SRC_TIP_SHORT}.py", f"sudan_corpus_stream_{DST_TIP_SHORT}.py"),
    (f"thailand_encode_memsafe_{SRC_TIP_SHORT}.py", f"sudan_encode_memsafe_{DST_TIP_SHORT}.py"),
    (f"thailand_finish_from_emb_{SRC_TIP_SHORT}.py", f"sudan_finish_from_emb_{DST_TIP_SHORT}.py"),
    (f"thailand_stream_graph_parts_{SRC_TIP_SHORT}.py", f"sudan_stream_graph_parts_{DST_TIP_SHORT}.py"),
    (f"thailand_package_memsafe_{SRC_TIP_SHORT}.py", f"sudan_package_memsafe_{DST_TIP_SHORT}.py"),
    ("thailand_upload.py", "sudan_upload.py"),
    ("thailand_bm25_smoke.py", "sudan_bm25_smoke.py"),
    ("thailand_write_publish_report.py", "sudan_write_publish_report.py"),
    (f"thailand_orchestrator_{SRC_TIP_SHORT}.py", f"sudan_orchestrator_{DST_TIP_SHORT}.py"),
]

DISPLAY = "Sudan"
SLUG = "sudan"


def adapt(text: str, dst_name: str) -> str:
    for bad in (
        "cient-data", "prent-data", "thailandent-data", "sudanent-data", "croatiaent-data",
    ):
        text = text.replace(f"/home/box/{bad}/", "/home/box/agent-data/")
        text = text.replace(bad, "agent-data")

    text = text.replace("BM25", "\x00BM25\x00").replace("bm25", "\x00bm25\x00")
    text = text.replace("bmjacency", "adjacency")

    text = text.replace(SRC_HOLD, "\x00DESTHOLD\x00")
    text = text.replace(SRC_WAVE, "\x00DESTWAVE\x00")
    text = text.replace(HOLD, "\x00DESTHOLD\x00")
    text = text.replace(WAVE_POS, "\x00DESTWAVE\x00")
    text = text.replace("SOFT_THIN_FINAL", "\x00DESTMODE\x00")
    text = text.replace(DEST_CHAIN, "\x00DESTCHAIN\x00")
    # SRC_CHAIN "TH" must NOT eat THIN — only whole-token / quoted / paren forms via reps
    # Do NOT bare-replace SRC_CHAIN="TH" globally.
    text = text.replace("after-HR", "\x00AFTERHR\x00")
    text = text.replace("after HR ", "\x00AFTERHR_SP\x00")
    text = text.replace("HR LIVE", "\x00HRLIVE\x00")
    text = text.replace("DZ+MC+SK+HR+TH", "\x00PRIORS\x00")
    text = text.replace("DZ+MC+SK+HR", "\x00DZMCSKHR\x00")
    text = text.replace("GH EMPTY", "\x00GHEMPTY\x00")
    text = text.replace("do NOT start Sudan or any other country", "\x00DONOTSTART\x00")
    text = text.replace("do NOT start Sudan or any other", "\x00DONOTSTART2\x00")
    text = text.replace("do NOT start SD/LB/FM/MM/IS", "\x00DONOTREBUILD\x00")
    text = text.replace("do NOT start any other country", "\x00DONOTSTART\x00")
    text = text.replace("do NOT start any other", "\x00DONOTSTART2\x00")
    text = text.replace("67930c3f-c94b-445b-a5bc-01d3fc1135c1", "\x00UUID94\x00")

    # Tip swaps FIRST — SRC tip contains "78"; remove before floor 78→69
    text = text.replace(SRC_TIP_FULL, DST_TIP_FULL)
    text = text.replace(SRC_TIP_SHORT, DST_TIP_SHORT)
    text = text.replace(DST_TIP_FULL, "\x00TIPSHA_PROTECT\x00")
    text = text.replace(DST_TIP_SHORT, "\x00TIPSHORT_PROTECT\x00")

    reps = [
        ("endomorphosis/ipfs_thailand_laws", "endomorphosis/ipfs_sudan_laws"),
        ("justicedao/ipfs_thailand_laws_ir", "justicedao/ipfs_sudan_laws_ir"),
        ("ipfs_thailand_laws_ir", "ipfs_sudan_laws_ir"),
        ("ipfs_thailand_laws", "ipfs_sudan_laws"),
        ("\x00DESTHOLD\x00", HOLD),
        ("\x00DESTWAVE\x00", WAVE_POS),
        ("\x00DESTCHAIN\x00", DEST_CHAIN),
        ("\x00DESTMODE\x00", "SOFT_THIN_FINAL"),
        ("\x00AFTERHR\x00", "after-TH"),
        ("\x00AFTERHR_SP\x00", "after TH "),
        ("\x00HRLIVE\x00", "TH LIVE"),
        ("\x00PRIORS\x00", "DZ+MC+SK+HR+TH"),
        ("\x00DZMCSKHR\x00", "DZ+MC+SK+HR"),
        ("\x00GHEMPTY\x00", "GH EMPTY"),
        ("\x00DONOTSTART\x00", "do NOT start Lebanon or any other country"),
        ("\x00DONOTSTART2\x00", "do NOT start Lebanon or any other"),
        ("\x00DONOTREBUILD\x00", "do NOT start LB/FM/MM/IS"),
        # URLs
        ("www/ratchakitcha.soc.go.th", "www/moj.gov.sd"),
        ("ratchakitcha.soc.go.th", "moj.gov.sd"),
        ("www.ratchakitcha.soc.go.th", "www.moj.gov.sd"),
        ("ratchakitcha", "moj"),
        # Language / country
        ("Thai (Thailand)", "Arabic/English (Sudan)"),
        ("Thai Thailand", "Arabic/English Sudan"),
        ("ASCII-fold Thai", "ASCII-fold Sudan"),
        ("Thai/ASCII legal stems", "Sudan ASCII legal stems"),
        ("Thai legal corpus", "Sudan legal corpus"),
        ("Thai ASCII GATE", "Sudan ASCII GATE"),
        ("Thai script", "Arabic script"),
        ("Thailand", DISPLAY),
        ("thailand_ranked", "sudan_ranked"),
        ("thailand_gate", "sudan_gate"),
        ("thailand_pass", "sudan_pass"),
        ("thailand_encode_memsafe", "sudan_encode_memsafe"),
        ("thailand_package_memsafe", "sudan_package_memsafe"),
        ("thailand_corpus_stream", "sudan_corpus_stream"),
        ("thailand_encode_done", "sudan_encode_done"),
        ("thailand_filtered_", "sudan_filtered_"),
        ("thailand_", "sudan_"),
        ('"TH"', '"SD"'),
        ("TH-attested", "SD-attested"),
        ("(TH)", "(SD)"),
        ('"th"', '"sd"'),
        # floors 283/78 → 56/69 — tips protected (SRC tip had 78)
        ("283/78", "56/69"),
        ("283 / 78", "56 / 69"),
        ("283, 78", "56, 69"),
        ("FLOOR_LAWS, FLOOR_ARTS = 283, 78", "FLOOR_LAWS, FLOOR_ARTS = 56, 69"),
        ('int(pack.get("n_laws") or 283)', 'int(pack.get("n_laws") or 56)'),
        ('int(pack.get("n_articles") or 78)', 'int(pack.get("n_articles") or 69)'),
        ("@ 283/", "@ 56/"),
        ("floor 283/", "floor 56/"),
        ("(283/", "(56/"),
        (" 78", " 69"),
        ("78", "69"),
        ("= 283,", "= 56,"),
        ("or 283)", "or 56)"),
        ("or 283,", "or 56,"),
        ("or 283}", "or 56}"),
        ("= 283", "= 56"),
        (" 283/", " 56/"),
        ("283", "56"),
        ('"language": "Thai"', '"language": "Arabic"'),
        ('"lang": "Thai"', '"lang": "Arabic"'),
        ("language: Thai", "language: Arabic"),
        ("Language: Thai", "Language: Arabic"),
    ]
    for a, b in reps:
        text = text.replace(a, b)

    text = text.replace("\x00TIPSHA_PROTECT\x00", DST_TIP_FULL)
    text = text.replace("\x00TIPSHORT_PROTECT\x00", DST_TIP_SHORT)

    text = re.sub(r"(?<![A-Za-z0-9_])thailand(?![A-Za-z0-9_])", SLUG, text)

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
    text = text.replace('"country": "thailand"', f'"country": "{SLUG}"')
    text = text.replace(f"# {SLUG} filtered pack", f"# {DISPLAY} filtered pack")
    text = text.replace(f"{SLUG} laws IR release", f"{DISPLAY} laws IR release")

    for bad in ("cient-data", "thailandent-data", "sudanent-data"):
        text = text.replace(f"/home/box/{bad}/", "/home/box/agent-data/")
        text = text.replace(bad, "agent-data")

    if dst_name == "sudan_bm25_smoke.py":
        start = text.index("GATE = [")
        end = text.index("]", start) + 1
        years_line = ", ".join(f'"{y}"' for y in GATE_YEARS)
        stems_line = ", ".join(f'"{s}"' for s in GATE_STEMS)
        gate = f"GATE = [\n    {years_line},\n    {stems_line},\n]"
        text = text[:start] + gate + text[end:]
        text = re.sub(
            r"QUERIES = GATE \+ \[[^\]]*\]",
            'QUERIES = GATE + ["www", "moj.gov.sd", "www.moj.gov.sd", "moj", "gov.sd", "sd", "wipo", "مادة", "قانون", "وزير", "قرار", "جمهورية", "السودان", "دستور"]',
            text,
            count=1,
        )
        text = re.sub(
            r'"""BM25 smoke for .*?"""',
            '"""BM25 smoke for Sudan IR — Arabic/English legal corpus; ASCII-indexed FTS gate.\n\n'
            "Tokenizer strips Arabic script. GATE is attested ASCII years + stems from article\n"
            "title/body (sudan/republic/gazette/… + years). Arabic script and URL moj.gov.sd\n"
            "are query-only, never GATE.\n"
            '"""',
            text,
            count=1,
            flags=re.S,
        )
        note = (
            f"Sudan ASCII GATE (Arabic script unindexed by FTS): attested years {GATE_NOTE_YEARS} "
            f"plus stems {GATE_NOTE_STEMS} from articles.parquet HEAD tip {DST_TIP_SHORT}; "
            f"Arabic stems and URL moj.gov.sd are query-only, not GATE."
        )
        text = re.sub(r'"tokenizer_note":\s*"[^"]*"', f'"tokenizer_note": "{note}"', text, count=1)
        text = re.sub(r"GATE = attested years [^\"\n]+", f"GATE = {note}", text, count=1)
        # scrub TH-specific note leftovers
        text = re.sub(
            r'"tokenizer_note":\s*"[^"]*"',
            f'"tokenizer_note": "{note}"',
            text,
            count=1,
        )
        text = text.replace("thailand_pass", "sudan_pass").replace("thailand_gate", "sudan_gate")

    if dst_name == "sudan_write_publish_report.py":
        gate_note = (
            f"BM25 PASS on Sudan ASCII-fold Sudan ASCII GATE "
            f"(attested years {GATE_NOTE_YEARS} + stems {GATE_NOTE_STEMS}); "
            f"URL moj.gov.sd is query-only, not GATE"
        )
        text = re.sub(r'BM25 PASS on Sudan[^"]*"', gate_note + '"', text, count=1)
        text = re.sub(r'BM25 PASS on [^"]*GATE[^"]*"', gate_note + '"', text, count=1)
        text = re.sub(
            r"HOLD 0 STRICT[^;]*; collectors kept dead \(pkill\); soft never-thin ON[^\"\n]*",
            f"{HOLD}; collectors kept dead (pkill); soft never-thin ON (SD soft-thin OK); SKIP_US; Italy LIVE leave alone; {WAVE_POS}",
            text,
        )
        text = re.sub(r"[ \t]{2,}", " ", text)

    found = []
    for x in ("Thailand", "thailand", "ratchakitcha", "loan", "gsb", "mlr"):
        if x in ("loan", "gsb", "mlr"):
            continue  # may appear only if GATE not rewritten
        if re.search(rf"(?<![A-Za-z0-9_/-]){re.escape(x)}(?![A-Za-z0-9_])", text):
            if x in ("Thailand", "thailand", "ratchakitcha"):
                found.append(x)
    if found:
        raise RuntimeError(f"language/country leftovers in {dst_name}: {found}")

    if dst_name.endswith("_bm25_smoke.py"):
        gate_slice = text[text.index("GATE = ["): text.index("]", text.index("GATE = [")) + 1]
        for bad in (
            "loan", "rate", "effective", "gsb", "mlr", "clean", "salary", "mortgage",
            "flat", "mrr", "plus", "thailand", "ratchakitcha",
        ):
            if f'"{bad}"' in gate_slice:
                raise RuntimeError(f"non-SD token in GATE of {dst_name}: {bad}")
        for stem in GATE_STEMS:
            if f'"{stem}"' not in gate_slice:
                raise RuntimeError(f"missing stem in GATE of {dst_name}: {stem}")
        for year in GATE_YEARS:
            if f'"{year}"' not in gate_slice:
                raise RuntimeError(f"missing year in GATE of {dst_name}: {year}")
        if "ratchakitcha" in text:
            raise RuntimeError(f"leftover ratchakitcha in {dst_name}")

    scrub = text
    for prot in (WAVE_POS, HOLD, DEST_CHAIN, SRC_HOLD, SRC_WAVE):
        scrub = scrub.replace(prot, "XX")
    scrub = scrub.replace("after-TH", "after-XX").replace("after TH ", "after XX ")
    scrub = scrub.replace("TH LIVE", "XX LIVE").replace("DZ+MC+SK+HR+TH", "XX").replace("DZ+MC+SK+HR", "XX")
    scrub = scrub.replace("GH EMPTY", "XX EMPTY")
    if re.search(r"(?<![A-Za-z0-9_])thailand(?![A-Za-z0-9_])", scrub):
        m = re.search(r"(?<![A-Za-z0-9_])thailand(?![A-Za-z0-9_])", scrub)
        raise RuntimeError(f"leftover thailand in {dst_name}: ...{scrub[max(0,m.start()-20):m.start()+20]}...")
    if re.search(r"(?<![A-Za-z%])TH(?![A-Za-z])", scrub):
        m = re.search(r"(?<![A-Za-z%])TH(?![A-Za-z])", scrub)
        raise RuntimeError(f"leftover TH in {dst_name}: ...{scrub[max(0,m.start()-30):m.start()+30]}...")
    if "ipfs_thailand" in text:
        raise RuntimeError(f"leftover thailand path in {dst_name}")
    if SRC_TIP_SHORT in text or SRC_TIP_FULL in text:
        raise RuntimeError(f"src tip leftover in {dst_name}")
    if "c78c1b63" in text:
        raise RuntimeError(f"SRC tip fragment c78c1b63 leftover in {dst_name}")
    if DST_TIP_SHORT not in text and any(x in dst_name for x in ("soft_filter", "orchestrator", "bm25_smoke")):
        raise RuntimeError(f"missing DST tip in {dst_name}")
    for m in re.finditer(r"6a063943f9df[0-9a-f]*", text):
        frag = m.group(0)
        if len(frag) >= 40 and frag != DST_TIP_FULL:
            raise RuntimeError(f"corrupted tip SHA in {dst_name}: {frag}")
        if 12 < len(frag) < 40:
            raise RuntimeError(f"truncated/partial tip SHA in {dst_name}: {frag}")
    if "soft_filter" in dst_name or "corpus_stream" in dst_name:
        if "data/laws.parquet" not in text and 'data" / "laws.parquet"' not in text:
            if '"data"' not in text and "/data/" not in text:
                raise RuntimeError(f"missing data/ parquet paths in {dst_name}")
    if "SOFT_SDIN" in text or "\x00" in text:
        raise RuntimeError(f"SOFT_THIN/null corruption in {dst_name}")
    if "SOFT_THIN_FINAL" not in text and "orchestrator" in dst_name:
        # docstring should have it
        if "SOFT_" in text and "SOFT_THIN_FINAL" not in text:
            raise RuntimeError(f"missing SOFT_THIN_FINAL in {dst_name}")
    if "283/78" in text or "FLOOR_LAWS, FLOOR_ARTS = 283" in text:
        raise RuntimeError(f"OLD thailand floor leftover in {dst_name}")
    if "write_publish" in dst_name or "bm25_smoke" in dst_name:
        if re.search(r"ASCII-fold Thai|Thai legal|Thai ASCII GATE|ratchakitcha", text):
            raise RuntimeError(f"leftover Thai phrasing in {dst_name}")
    return text


for src_name, dst_name in FILES:
    src = ROOT / src_name
    if not src.is_file():
        raise FileNotFoundError(src)
    (ROOT / dst_name).write_text(adapt(src.read_text(encoding="utf-8"), dst_name), encoding="utf-8")
    print(f"wrote {dst_name}")

for _, dst_name in FILES:
    t = (ROOT / dst_name).read_text(encoding="utf-8")
    for m in re.finditer(r"6a063943f9df[0-9a-f]{20,}", t):
        if m.group(0) != DST_TIP_FULL:
            raise RuntimeError(f"post-write corrupted tip in {dst_name}: {m.group(0)}")
    if "c78c1b63" in t or "cde9df4f9b72" in t:
        raise RuntimeError(f"SRC tip leftover in {dst_name}")

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
        if entry.get("slug") == SLUG or entry.get("iso2") == "SD":
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
                "iso2": "SD",
                "slug": SLUG,
                "repo": "endomorphosis/ipfs_sudan_laws",
                "years_attested": YEARS_ATTESTED,
                "gate_years": [int(y) for y in GATE_YEARS],
                "gate_stems": GATE_STEMS,
                "note": (
                    f"SD SOFT_THIN_FINAL scaffold; tip MATCH {DST_TIP_SHORT}@56/69; {HOLD}; "
                    f"soft-thin OK; SKIP_US; Italy LIVE leave alone; {WAVE_POS}; "
                    f"Sudan ASCII GATE ({len(GATE_YEARS)} years + {len(GATE_STEMS)} stems); "
                    f"memsafe only; do NOT start Lebanon or any other country"
                ),
                "status": "CLAIMED",
                "mode": "SOFT_THIN_FINAL",
                "wave_end": False,
                "do_not_start": False,
            })
            break
    else:
        raise RuntimeError(f"Sudan / SD entry missing from wave JSON {wave}")
    data["wave_status"] = "IN_PROGRESS_SD"
    data["hold"] = HOLD
    data["current"] = SLUG
    data["do_not_start_next"] = "lebanon"
    data["next"] = "lebanon"
    data["hold_note"] = (
        "HOLD 0 STRICT for SD SOFT_THIN_FINAL build in progress; "
        "do NOT start Lebanon or any other country; priors LIVE leave alone"
    )
    wave.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"updated wave JSON {wave}")

print("GATE years", GATE_YEARS)
print("GATE stems", GATE_STEMS)
print("TIP_FULL", DST_TIP_FULL)
print("soft-thin memsafe: 56/69; only SD")
