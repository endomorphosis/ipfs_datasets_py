#!/usr/bin/env python3
"""Adapt Croatia Croatian memsafe SOFT_THIN_FINAL pack to Thailand TH tip cde9df4f9b72.

Thai (laws.language=th); article corpus Thai-script-heavy. BM25 tokenizer is
ASCII-only ([0-9A-Za-z]+ after NFKD) so Thai stems/years are unindexed —
GATE uses attested ASCII tokens present in article title/body (loan/rate/gsb/…).
Thai script + URL ratchakitcha.soc.go.th are query-only, never GATE.
SOFT_THIN_FINAL; HOLD 0 STRICT wave2 FIFTH after DZ+MC+SK+HR LIVE
(TH; then SD→LB→FM→MM→IS). Soft never-thin ON except soft-thin OK;
SKIP_US; Italy LIVE leave alone; KW HOLD_THIN; AT queued-only; P1 CLOSED.
Do NOT rebuild priors. Do NOT start Sudan.
CRITICAL: protect tip SHA during floor digit replaces — DST tip CONTAINS
substring "78" (…c78c1b63); floor arts also 78.
Floor ≥283/78.
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
SRC_TIP_FULL = "9469c387c221cf5ab435b0c4cabb9426213a48ee"
SRC_TIP_SHORT = "9469c387c221"
DST_TIP_FULL = "cde9df4f9b72950a3bbdfd7b5e605213c78c1b63"
DST_TIP_SHORT = "cde9df4f9b72"
FLOOR_LAWS, FLOOR_ARTS = 283, 78
SRC_FLOOR_L, SRC_FLOOR_A = 30315, 108

# ASCII tokens attested in article title/body after BM25 tokenize (Thai stripped)
GATE_YEARS = []  # no Gregorian ASCII years in article title/body
GATE_STEMS = [
    "loan", "rate", "effective", "gsb", "mlr",
    "clean", "salary", "mortgage", "flat", "mrr", "plus",
]
YEARS_ATTESTED = []  # BE years 2566/2567 exist as Thai digits only — unindexed
GATE_NOTE_YEARS = "(none — Thai-digit BE years unindexed by ASCII FTS)"
GATE_NOTE_STEMS = "/".join(GATE_STEMS)
HOLD = "HOLD 0 STRICT wave2 after HR LIVE (TH)"
WAVE_POS = (
    "FIFTH of wave2 after GH EMPTY "
    "(TH SOFT_THIN_FINAL after DZ+MC+SK+HR LIVE; then SD→LB→FM→MM→IS — do NOT start those)"
)
DEST_CHAIN = "TH"
SRC_HOLD = "HOLD 0 STRICT wave2 after SK LIVE (HR)"
SRC_WAVE = (
    "FOURTH of wave2 after GH EMPTY "
    "(HR SOFT_THIN_FINAL after DZ+MC+SK LIVE; then TH→SD→LB→FM→MM→IS — do NOT start those)"
)
SRC_CHAIN = "HR"

FILES = [
    ("croatia_soft_filter.py", "thailand_soft_filter.py"),
    (f"croatia_corpus_stream_{SRC_TIP_SHORT}.py", f"thailand_corpus_stream_{DST_TIP_SHORT}.py"),
    (f"croatia_encode_memsafe_{SRC_TIP_SHORT}.py", f"thailand_encode_memsafe_{DST_TIP_SHORT}.py"),
    (f"croatia_finish_from_emb_{SRC_TIP_SHORT}.py", f"thailand_finish_from_emb_{DST_TIP_SHORT}.py"),
    (f"croatia_stream_graph_parts_{SRC_TIP_SHORT}.py", f"thailand_stream_graph_parts_{DST_TIP_SHORT}.py"),
    (f"croatia_package_memsafe_{SRC_TIP_SHORT}.py", f"thailand_package_memsafe_{DST_TIP_SHORT}.py"),
    ("croatia_upload.py", "thailand_upload.py"),
    ("croatia_bm25_smoke.py", "thailand_bm25_smoke.py"),
    ("croatia_write_publish_report.py", "thailand_write_publish_report.py"),
    (f"croatia_orchestrator_{SRC_TIP_SHORT}.py", f"thailand_orchestrator_{DST_TIP_SHORT}.py"),
]

DISPLAY = "Thailand"
SLUG = "thailand"


def adapt(text: str, dst_name: str) -> str:
    for bad in (
        "cient-data", "prent-data", "stent-data", "cvent-data", "scent-data",
        "croatiaent-data", "thailandent-data", "slovakiaent-data",
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
    text = text.replace("after-SK", "\x00AFTERSK\x00")
    text = text.replace("after SK ", "\x00AFTERSK_SP\x00")
    text = text.replace("SK LIVE", "\x00SKLIVE\x00")
    text = text.replace("DZ+MC+SK+HR", "\x00PRIORS\x00")
    text = text.replace("DZ+MC+SK", "\x00DZMCSK\x00")
    text = text.replace("GH EMPTY", "\x00GHEMPTY\x00")
    text = text.replace("SOFT_THIN_FINAL", "\x00DESTMODE\x00")
    text = text.replace("do NOT start Thailand or any other country", "\x00DONOTSTART\x00")
    text = text.replace("do NOT start Thailand or any other", "\x00DONOTSTART2\x00")
    text = text.replace("do NOT start TH/SD/LB/FM/MM/IS", "\x00DONOTREBUILD\x00")
    text = text.replace("do NOT start any other country", "\x00DONOTSTART\x00")
    text = text.replace("do NOT start any other", "\x00DONOTSTART2\x00")
    text = text.replace("67930c3f-c94b-445b-a5bc-01d3fc1135c1", "\x00UUID94\x00")

    # Tip swaps FIRST, then protect DST tip (contains "78") before digit floor swaps
    text = text.replace(SRC_TIP_FULL, DST_TIP_FULL)
    text = text.replace(SRC_TIP_SHORT, DST_TIP_SHORT)
    text = text.replace(DST_TIP_FULL, "\x00TIPSHA_PROTECT\x00")
    text = text.replace(DST_TIP_SHORT, "\x00TIPSHORT_PROTECT\x00")

    reps = [
        ("endomorphosis/ipfs_croatia_laws", "endomorphosis/ipfs_thailand_laws"),
        ("justicedao/ipfs_croatia_laws_ir", "justicedao/ipfs_thailand_laws_ir"),
        ("ipfs_croatia_laws_ir", "ipfs_thailand_laws_ir"),
        ("ipfs_croatia_laws", "ipfs_thailand_laws"),
        ("\x00DESTHOLD\x00", HOLD),
        ("\x00DESTWAVE\x00", WAVE_POS),
        ("\x00DESTCHAIN\x00", DEST_CHAIN),
        ("\x00DESTMODE\x00", "SOFT_THIN_FINAL"),
        ("\x00AFTERSK\x00", "after-HR"),
        ("\x00AFTERSK_SP\x00", "after HR "),
        ("\x00SKLIVE\x00", "HR LIVE"),
        ("\x00PRIORS\x00", "DZ+MC+SK+HR"),
        ("\x00DZMCSK\x00", "DZ+MC+SK"),
        ("\x00GHEMPTY\x00", "GH EMPTY"),
        ("\x00DONOTSTART\x00", "do NOT start Sudan or any other country"),
        ("\x00DONOTSTART2\x00", "do NOT start Sudan or any other"),
        ("\x00DONOTREBUILD\x00", "do NOT start SD/LB/FM/MM/IS"),
        # URLs
        ("www/narodne-novine.nn.hr", "www/ratchakitcha.soc.go.th"),
        ("narodne-novine.nn.hr", "ratchakitcha.soc.go.th"),
        ("www.narodne-novine.nn.hr", "www.ratchakitcha.soc.go.th"),
        ("narodne-novine", "ratchakitcha"),
        # Language / country
        ("Croatian (Croatia)", "Thai (Thailand)"),
        ("Croatian Croatia", "Thai Thailand"),
        ("ASCII-fold Croatian", "ASCII-fold Thai"),
        ("Croatian legal stems", "Thai/ASCII legal stems"),
        ("Croatian legal corpus", "Thai legal corpus"),
        ("Croatian GATE", "Thai ASCII GATE"),
        ("Croatia", DISPLAY),
        ("croatia_ranked", "thailand_ranked"),
        ("croatia_gate", "thailand_gate"),
        ("croatia_pass", "thailand_pass"),
        ("croatia_encode_memsafe", "thailand_encode_memsafe"),
        ("croatia_package_memsafe", "thailand_package_memsafe"),
        ("croatia_corpus_stream", "thailand_corpus_stream"),
        ("croatia_encode_done", "thailand_encode_done"),
        ("croatia_filtered_", "thailand_filtered_"),
        ("croatia_", "thailand_"),
        ('"HR"', '"TH"'),
        ("HR-attested", "TH-attested"),
        ("(HR)", "(TH)"),
        ('"hr"', '"th"'),
        # floors 30315/108 → 283/78 — compound first (tips protected; tip contains 78)
        ("30315/108", "283/78"),
        ("30315 / 108", "283 / 78"),
        ("30315, 108", "283, 108".replace("108", "78") if False else "283, 78"),
        ("FLOOR_LAWS, FLOOR_ARTS = 30315, 108", "FLOOR_LAWS, FLOOR_ARTS = 283, 78"),
        ('int(pack.get("n_laws") or 30315)', 'int(pack.get("n_laws") or 283)'),
        ('int(pack.get("n_articles") or 108)', 'int(pack.get("n_articles") or 78)'),
        ("@ 30315/", "@ 283/"),
        ("floor 30315/", "floor 283/"),
        ("(30315/", "(283/"),
        (" 108", " 78"),
        ("108", "78"),
        ("= 30315,", "= 283,"),
        ("or 30315)", "or 283)"),
        ("or 30315,", "or 283,"),
        ("or 30315}", "or 283}"),
        ("= 30315", "= 283"),
        (" 30315/", " 283/"),
        ("30315", "283"),
        ('"language": "Croatian"', '"language": "Thai"'),
        ('"lang": "Croatian"', '"lang": "Thai"'),
        ("language: Croatian", "language: Thai"),
        ("Language: Croatian", "Language: Thai"),
    ]
    for a, b in reps:
        text = text.replace(a, b)

    text = text.replace("\x00TIPSHA_PROTECT\x00", DST_TIP_FULL)
    text = text.replace("\x00TIPSHORT_PROTECT\x00", DST_TIP_SHORT)

    text = re.sub(r"(?<![A-Za-z0-9_])croatia(?![A-Za-z0-9_])", SLUG, text)

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
    text = text.replace('"country": "croatia"', f'"country": "{SLUG}"')
    text = text.replace(f"# {SLUG} filtered pack", f"# {DISPLAY} filtered pack")
    text = text.replace(f"{SLUG} laws IR release", f"{DISPLAY} laws IR release")

    for bad in ("cient-data", "croatiaent-data", "thailandent-data"):
        text = text.replace(f"/home/box/{bad}/", "/home/box/agent-data/")
        text = text.replace(bad, "agent-data")

    if dst_name == "thailand_bm25_smoke.py":
        start = text.index("GATE = [")
        end = text.index("]", start) + 1
        stems_line = ", ".join(f'"{s}"' for s in GATE_STEMS)
        gate = f"GATE = [\n    {stems_line},\n]"
        text = text[:start] + gate + text[end:]
        text = re.sub(
            r"QUERIES = GATE \+ \[[^\]]*\]",
            'QUERIES = GATE + ["www", "ratchakitcha.soc.go.th", "www.ratchakitcha.soc.go.th", "ratchakitcha", "soc", "go.th", "krisdika", "th", "pdf", "tcpdf", "powered", "org", "2566", "2567", "ข้อ", "ประกาศ", "พระราชบัญญัติ"]',
            text,
            count=1,
        )
        text = re.sub(
            r'"""BM25 smoke for .*?"""',
            '"""BM25 smoke for Thailand IR — Thai legal corpus; ASCII-indexed FTS gate.\n\n'
            "Tokenizer strips Thai script (ASCII [0-9A-Za-z]+ only). GATE is attested ASCII\n"
            "stems from article title/body (loan/rate/gsb/…). Thai script, BE Thai-digit years,\n"
            "and URL ratchakitcha.soc.go.th are query-only, never GATE.\n"
            '"""',
            text,
            count=1,
            flags=re.S,
        )
        note = (
            f"Thai ASCII GATE (Thai script unindexed by FTS): attested stems {GATE_NOTE_STEMS} "
            f"from articles.parquet HEAD tip {DST_TIP_SHORT}; no Gregorian ASCII years in "
            f"title/body; Thai/BE years and URL ratchakitcha.soc.go.th are query-only, not GATE."
        )
        text = re.sub(r'"tokenizer_note":\s*"[^"]*"', f'"tokenizer_note": "{note}"', text, count=1)
        text = re.sub(r"GATE = attested years [^\"\n]+", f"GATE = {note}", text, count=1)
        text = text.replace("croatia_pass", "thailand_pass").replace("croatia_gate", "thailand_gate")

    if dst_name == "thailand_write_publish_report.py":
        gate_note = (
            f"BM25 PASS on Thailand ASCII-fold Thai ASCII GATE "
            f"(stems {GATE_NOTE_STEMS}; no Gregorian ASCII years in corpus); "
            f"URL ratchakitcha.soc.go.th is query-only, not GATE"
        )
        text = re.sub(r'BM25 PASS on Thailand[^"]*"', gate_note + '"', text, count=1)
        text = re.sub(r'BM25 PASS on [^"]*GATE[^"]*"', gate_note + '"', text, count=1)
        text = re.sub(
            r"HOLD 0 STRICT[^;]*; collectors kept dead \(pkill\); soft never-thin ON[^\"\n]*",
            f"{HOLD}; collectors kept dead (pkill); soft never-thin ON (TH soft-thin OK); SKIP_US; Italy LIVE leave alone; {WAVE_POS}",
            text,
        )
        text = re.sub(r"[ \t]{2,}", " ", text)

    found = []
    for x in ("Croatia", "croatia", "clanak", "hrvatske", "narodne-novine"):
        if re.search(rf"(?<![A-Za-z0-9_/-]){re.escape(x)}(?![A-Za-z0-9_])", text):
            if x in ("Croatia", "croatia", "narodne-novine"):
                found.append(x)
    if found:
        raise RuntimeError(f"language/country leftovers in {dst_name}: {found}")

    if dst_name.endswith("_bm25_smoke.py"):
        gate_slice = text[text.index("GATE = ["): text.index("]", text.index("GATE = [")) + 1]
        for bad in (
            "clanak", "hrvatske", "republike", "zakon", "odluka", "stavak", "sud",
            "narodne", "novine", "vlada", "ustav", "croatia",
            "2009", "2011", "2014",  # HR years — not in TH ASCII corpus
        ):
            if f'"{bad}"' in gate_slice:
                raise RuntimeError(f"non-TH token in GATE of {dst_name}: {bad}")
        for stem in GATE_STEMS:
            if f'"{stem}"' not in gate_slice:
                raise RuntimeError(f"missing stem in GATE of {dst_name}: {stem}")
        if "narodne-novine" in text:
            raise RuntimeError(f"leftover narodne-novine in {dst_name}")

    scrub = text
    for prot in (WAVE_POS, HOLD, DEST_CHAIN, SRC_HOLD, SRC_WAVE):
        scrub = scrub.replace(prot, "XX")
    scrub = scrub.replace("after-HR", "after-XX").replace("after HR ", "after XX ")
    scrub = scrub.replace("HR LIVE", "XX LIVE").replace("DZ+MC+SK+HR", "XX").replace("DZ+MC+SK", "XX")
    scrub = scrub.replace("GH EMPTY", "XX EMPTY")
    if re.search(r"(?<![A-Za-z0-9_])croatia(?![A-Za-z0-9_])", scrub):
        m = re.search(r"(?<![A-Za-z0-9_])croatia(?![A-Za-z0-9_])", scrub)
        raise RuntimeError(f"leftover croatia in {dst_name}: ...{scrub[max(0,m.start()-20):m.start()+20]}...")
    if re.search(r"(?<![A-Za-z%])HR(?![A-Za-z])", scrub):
        m = re.search(r"(?<![A-Za-z%])HR(?![A-Za-z])", scrub)
        raise RuntimeError(f"leftover HR in {dst_name}: ...{scrub[max(0,m.start()-30):m.start()+30]}...")
    if "ipfs_croatia" in text:
        raise RuntimeError(f"leftover croatia path in {dst_name}")
    if SRC_TIP_SHORT in text or SRC_TIP_FULL in text:
        raise RuntimeError(f"src tip leftover in {dst_name}")
    if DST_TIP_SHORT not in text and any(x in dst_name for x in ("soft_filter", "orchestrator", "bm25_smoke")):
        raise RuntimeError(f"missing DST tip in {dst_name}")
    # tip integrity — must be exact; tip contains "78"
    for m in re.finditer(r"cde9df4f9b72[0-9a-f]*", text):
        frag = m.group(0)
        if len(frag) >= 40 and frag != DST_TIP_FULL:
            raise RuntimeError(f"corrupted tip SHA in {dst_name}: {frag}")
        if 12 < len(frag) < 40:
            raise RuntimeError(f"truncated/partial tip SHA in {dst_name}: {frag}")
    if DST_TIP_FULL in text and "c78c1b63" not in text.split(DST_TIP_FULL)[0] + DST_TIP_FULL:
        # ensure full tip still has c78c1b63 suffix intact
        if DST_TIP_FULL not in text:
            raise RuntimeError(f"missing full tip in {dst_name}")
    if "c78c1b63" not in DST_TIP_FULL:
        raise RuntimeError("internal tip constant broken")
    if DST_TIP_FULL in text and not re.search(re.escape(DST_TIP_FULL), text):
        raise RuntimeError(f"tip mismatch in {dst_name}")
    if "soft_filter" in dst_name or "corpus_stream" in dst_name:
        if "data/laws.parquet" not in text and 'data" / "laws.parquet"' not in text:
            if '"data"' not in text and "/data/" not in text:
                raise RuntimeError(f"missing data/ parquet paths in {dst_name}")
    if "30315/108" in text or "FLOOR_LAWS, FLOOR_ARTS = 30315" in text:
        raise RuntimeError(f"OLD croatia floor leftover in {dst_name}")
    if "write_publish" in dst_name or "bm25_smoke" in dst_name:
        if re.search(r"ASCII-fold Croatian|Croatian legal", text):
            raise RuntimeError(f"leftover Croatian phrasing in {dst_name}")
    return text


for src_name, dst_name in FILES:
    src = ROOT / src_name
    if not src.is_file():
        raise FileNotFoundError(src)
    (ROOT / dst_name).write_text(adapt(src.read_text(encoding="utf-8"), dst_name), encoding="utf-8")
    print(f"wrote {dst_name}")

for _, dst_name in FILES:
    t = (ROOT / dst_name).read_text(encoding="utf-8")
    for m in re.finditer(r"cde9df4f9b72[0-9a-f]{20,}", t):
        if m.group(0) != DST_TIP_FULL:
            raise RuntimeError(f"post-write corrupted tip in {dst_name}: {m.group(0)}")
    # specifically verify tip still ends with c78c1b63 when full tip present
    if DST_TIP_FULL in t and not t.count(DST_TIP_FULL):
        pass
    if "TIP_FULL" in t or re.search(r'TIP = "cde9', t):
        if DST_TIP_FULL not in t and "soft_filter" in dst_name:
            raise RuntimeError(f"soft_filter missing full tip")
        if DST_TIP_FULL in t and "c78c1b63" not in DST_TIP_FULL:
            raise RuntimeError("bad")
        if DST_TIP_FULL in t:
            idx = t.index(DST_TIP_FULL)
            got = t[idx:idx+40]
            if got != DST_TIP_FULL:
                raise RuntimeError(f"tip slice mismatch in {dst_name}: {got}")

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
        if entry.get("slug") == SLUG or entry.get("iso2") == "TH":
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
                "language": "Thai",
                "lang": "Thai",
                "iso2": "TH",
                "slug": SLUG,
                "repo": "endomorphosis/ipfs_thailand_laws",
                "years_attested": YEARS_ATTESTED,
                "gate_years": [],
                "gate_stems": GATE_STEMS,
                "note": (
                    f"TH SOFT_THIN_FINAL scaffold; tip MATCH {DST_TIP_SHORT}@283/78; {HOLD}; "
                    f"soft-thin OK; SKIP_US; Italy LIVE leave alone; {WAVE_POS}; "
                    f"Thai ASCII GATE (0 years + {len(GATE_STEMS)} stems; Thai script unindexed); "
                    f"memsafe only; do NOT start Sudan or any other country"
                ),
                "status": "CLAIMED",
                "mode": "SOFT_THIN_FINAL",
                "wave_end": False,
                "do_not_start": False,
            })
            break
    else:
        raise RuntimeError(f"Thailand / TH entry missing from wave JSON {wave}")
    data["wave_status"] = "IN_PROGRESS_TH"
    data["hold"] = HOLD
    data["current"] = SLUG
    data["do_not_start_next"] = "sudan"
    data["next"] = "sudan"
    data["hold_note"] = (
        "HOLD 0 STRICT for TH SOFT_THIN_FINAL build in progress; "
        "do NOT start Sudan or any other country; DZ+MC+SK+HR LIVE leave alone"
    )
    wave.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"updated wave JSON {wave}")

print("GATE stems", GATE_STEMS)
print("TIP_FULL", DST_TIP_FULL, "contains_78", "78" in DST_TIP_FULL)
print("soft-thin memsafe: 283/78; only TH")
