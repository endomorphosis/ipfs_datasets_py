#!/usr/bin/env python3
"""Adapt FSM English memsafe SOFT_THIN_FINAL pack to Myanmar MM tip b744df8f35b0.

Burmese laws.language=my; article corpus English (carriage/goods/carrier).
BM25 ASCII-only — Burmese unindexed. GATE = attested ASCII stems (+ sparse
years 1926/1945) from articles.parquet. URL moi.gov.mm query-only.
SOFT_THIN_FINAL; HOLD 0 STRICT wave2 NINTH after DZ…FM LIVE (MM; then IS).
Soft never-thin ON except soft-thin OK; SKIP_US; Italy LIVE leave alone;
KW HOLD_THIN; AT queued-only; P1 CLOSED. Do NOT rebuild priors. Do NOT start Iceland.
CRITICAL: protect tip SHA; protect SOFT_THIN_FINAL before ISO swaps;
floor 468/16 → 725/12 via placeholders (tiny arts floor).
Floor ≥725/12.
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
SRC_TIP_FULL = "aece546f4dbc9b58a6863229f2723e76f81e05a3"
SRC_TIP_SHORT = "aece546f4dbc"
DST_TIP_FULL = "b744df8f35b0f9eff35df4eeb57e3def96e80607"
DST_TIP_SHORT = "b744df8f35b0"
FLOOR_LAWS, FLOOR_ARTS = 725, 12
SRC_FLOOR_L, SRC_FLOOR_A = 468, 16

GATE_YEARS = ["1926", "1945"]
GATE_STEMS = [
    "shall", "goods", "carrier", "article", "act",
    "shipper", "bill", "lading", "carriage", "ship", "loss",
]
YEARS_ATTESTED = [1926, 1945]
GATE_NOTE_YEARS = "/".join(GATE_YEARS)
GATE_NOTE_STEMS = "/".join(GATE_STEMS)
HOLD = "HOLD 0 STRICT wave2 after FM LIVE (MM)"
WAVE_POS = (
    "NINTH of wave2 after GH EMPTY "
    "(MM SOFT_THIN_FINAL after DZ+MC+SK+HR+TH+SD+LB+FM LIVE; then IS — do NOT start those)"
)
DEST_CHAIN = "MM"
SRC_HOLD = "HOLD 0 STRICT wave2 after LB LIVE (FM)"
SRC_WAVE = (
    "EIGHTH of wave2 after GH EMPTY "
    "(FM SOFT_THIN_FINAL after DZ+MC+SK+HR+TH+SD+LB LIVE; then MM→IS — do NOT start those)"
)

FILES = [
    ("fsm_soft_filter.py", "myanmar_soft_filter.py"),
    (f"fsm_corpus_stream_{SRC_TIP_SHORT}.py", f"myanmar_corpus_stream_{DST_TIP_SHORT}.py"),
    (f"fsm_encode_memsafe_{SRC_TIP_SHORT}.py", f"myanmar_encode_memsafe_{DST_TIP_SHORT}.py"),
    (f"fsm_finish_from_emb_{SRC_TIP_SHORT}.py", f"myanmar_finish_from_emb_{DST_TIP_SHORT}.py"),
    (f"fsm_stream_graph_parts_{SRC_TIP_SHORT}.py", f"myanmar_stream_graph_parts_{DST_TIP_SHORT}.py"),
    (f"fsm_package_memsafe_{SRC_TIP_SHORT}.py", f"myanmar_package_memsafe_{DST_TIP_SHORT}.py"),
    ("fsm_upload.py", "myanmar_upload.py"),
    ("fsm_bm25_smoke.py", "myanmar_bm25_smoke.py"),
    ("fsm_write_publish_report.py", "myanmar_write_publish_report.py"),
    (f"fsm_orchestrator_{SRC_TIP_SHORT}.py", f"myanmar_orchestrator_{DST_TIP_SHORT}.py"),
]

DISPLAY = "Myanmar"
SLUG = "myanmar"


def adapt(text: str, dst_name: str) -> str:
    for bad in ("cient-data", "fsment-data", "myanmarent-data", "lebanonent-data"):
        text = text.replace(f"/home/box/{bad}/", "/home/box/agent-data/")
        text = text.replace(bad, "agent-data")

    text = text.replace("BM25", "\x00BM25\x00").replace("bm25", "\x00bm25\x00")
    text = text.replace("bmjacency", "adjacency")

    # CRITICAL: protect SOFT_THIN_FINAL BEFORE ISO swaps
    text = text.replace("SOFT_THIN_FINAL", "\x00DESTMODE\x00")

    text = text.replace(SRC_HOLD, "\x00DESTHOLD\x00")
    text = text.replace(SRC_WAVE, "\x00DESTWAVE\x00")
    text = text.replace(HOLD, "\x00DESTHOLD\x00")
    text = text.replace(WAVE_POS, "\x00DESTWAVE\x00")
    text = text.replace("after-LB", "\x00AFTERLB\x00")
    text = text.replace("after LB ", "\x00AFTERLB_SP\x00")
    text = text.replace("LB LIVE", "\x00LBLIVE\x00")
    text = text.replace("DZ+MC+SK+HR+TH+SD+LB+FM", "\x00PRIORS\x00")
    text = text.replace("DZ+MC+SK+HR+TH+SD+LB", "\x00DZMCSKHRTHSDLB\x00")
    text = text.replace("GH EMPTY", "\x00GHEMPTY\x00")
    text = text.replace("do NOT start Myanmar or any other country", "\x00DONOTSTART\x00")
    text = text.replace("do NOT start Myanmar or any other", "\x00DONOTSTART2\x00")
    text = text.replace("do NOT start MM/IS", "\x00DONOTREBUILD\x00")
    text = text.replace("do NOT start any other country", "\x00DONOTSTART\x00")
    text = text.replace("do NOT start any other", "\x00DONOTSTART2\x00")
    text = text.replace("67930c3f-c94b-445b-a5bc-01d3fc1135c1", "\x00UUID94\x00")

    # Tip swaps + protect (before any digit floor swaps)
    text = text.replace(SRC_TIP_FULL, DST_TIP_FULL)
    text = text.replace(SRC_TIP_SHORT, DST_TIP_SHORT)
    text = text.replace(DST_TIP_FULL, "\x00TIPSHA_PROTECT\x00")
    text = text.replace(DST_TIP_SHORT, "\x00TIPSHORT_PROTECT\x00")

    # Floor 468/16 → 725/12 via placeholders
    text = text.replace("468/16", "\x00FLOOR_LA\x00")
    text = text.replace("468 / 16", "\x00FLOOR_LA_SP\x00")
    text = text.replace("468, 16", "\x00FLOOR_LA_C\x00")
    text = text.replace("FLOOR_LAWS, FLOOR_ARTS = 468, 16", "\x00FLOOR_ASSIGN\x00")
    text = text.replace('int(pack.get("n_laws") or 468)', "\x00OR_LAWS\x00")
    text = text.replace('int(pack.get("n_articles") or 16)', "\x00OR_ARTS\x00")
    text = text.replace(" 16", "\x00ARTS\x00")
    text = text.replace("16", "\x00ARTS\x00")
    text = text.replace(" 468", "\x00LAWS\x00")
    text = text.replace("468", "\x00LAWS\x00")
    text = text.replace("\x00FLOOR_LA\x00", "725/12")
    text = text.replace("\x00FLOOR_LA_SP\x00", "725 / 12")
    text = text.replace("\x00FLOOR_LA_C\x00", "725, 12")
    text = text.replace("\x00FLOOR_ASSIGN\x00", "FLOOR_LAWS, FLOOR_ARTS = 725, 12")
    text = text.replace("\x00OR_LAWS\x00", 'int(pack.get("n_laws") or 725)')
    text = text.replace("\x00OR_ARTS\x00", 'int(pack.get("n_articles") or 12)')
    text = text.replace("\x00ARTS\x00", "12")
    text = text.replace("\x00LAWS\x00", "725")

    reps = [
        ("endomorphosis/ipfs_fsm_laws", "endomorphosis/ipfs_myanmar_laws"),
        ("justicedao/ipfs_fsm_laws_ir", "justicedao/ipfs_myanmar_laws_ir"),
        ("ipfs_fsm_laws_ir", "ipfs_myanmar_laws_ir"),
        ("ipfs_fsm_laws", "ipfs_myanmar_laws"),
        ("\x00DESTHOLD\x00", HOLD),
        ("\x00DESTWAVE\x00", WAVE_POS),
        ("\x00DESTMODE\x00", "SOFT_THIN_FINAL"),
        ("\x00AFTERLB\x00", "after-FM"),
        ("\x00AFTERLB_SP\x00", "after FM "),
        ("\x00LBLIVE\x00", "FM LIVE"),
        ("\x00PRIORS\x00", "DZ+MC+SK+HR+TH+SD+LB+FM"),
        ("\x00DZMCSKHRTHSDLB\x00", "DZ+MC+SK+HR+TH+SD+LB"),
        ("\x00GHEMPTY\x00", "GH EMPTY"),
        ("\x00DONOTSTART\x00", "do NOT start Iceland or any other country"),
        ("\x00DONOTSTART2\x00", "do NOT start Iceland or any other"),
        ("\x00DONOTREBUILD\x00", "do NOT start IS"),
        # URLs
        ("www/cfsm.gov.fm", "www/moi.gov.mm"),
        ("cfsm.gov.fm", "moi.gov.mm"),
        ("www.cfsm.gov.fm", "www.moi.gov.mm"),
        ("gov.fm", "gov.mm"),
        ("cfsm", "moi"),
        # Language / country — FSM display before slug
        ("English (FSM)", "English (Myanmar)"),
        ("English FSM", "English Myanmar"),
        ("ASCII-fold English", "ASCII-fold English"),
        ("English legal stems", "English legal stems"),
        ("English legal corpus", "English legal corpus"),
        ("English GATE", "English GATE"),
        ("English script", "English script"),
        ("FSM", DISPLAY),
        ("fsm_ranked", "myanmar_ranked"),
        ("fsm_gate", "myanmar_gate"),
        ("fsm_pass", "myanmar_pass"),
        ("fsm_encode_memsafe", "myanmar_encode_memsafe"),
        ("fsm_package_memsafe", "myanmar_package_memsafe"),
        ("fsm_corpus_stream", "myanmar_corpus_stream"),
        ("fsm_encode_done", "myanmar_encode_done"),
        ("fsm_filtered_", "myanmar_filtered_"),
        ("fsm_", "myanmar_"),
        ('"FM"', '"MM"'),
        ("FM-attested", "MM-attested"),
        ("(FM)", "(MM)"),
        ('"fm"', '"mm"'),
        ('"language": "English"', '"language": "English"'),
        ('"lang": "English"', '"lang": "English"'),
    ]
    for a, b in reps:
        text = text.replace(a, b)

    text = text.replace("\x00TIPSHA_PROTECT\x00", DST_TIP_FULL)
    text = text.replace("\x00TIPSHORT_PROTECT\x00", DST_TIP_SHORT)

    # bare fsm slug → myanmar (after fsm_ prefixes already done)
    text = re.sub(r"(?<![A-Za-z0-9_])fsm(?![A-Za-z0-9_])", SLUG, text)

    text = text.replace("\x00BM25\x00", "BM25").replace("\x00bm25\x00", "bm25")
    text = text.replace("\x00DESTHOLD\x00", HOLD)
    text = text.replace("\x00DESTWAVE\x00", WAVE_POS)
    text = text.replace("\x00DESTMODE\x00", "SOFT_THIN_FINAL")
    text = text.replace("\x00UUID94\x00", "67930c3f-c94b-445b-a5bc-01d3fc1135c1")

    text = text.replace(f'"name": "{SLUG}"', f'"name": "{DISPLAY}"')
    text = text.replace(f'"slug": "{DISPLAY}"', f'"slug": "{SLUG}"')
    text = text.replace(f'SLUG = "{DISPLAY}"', f'SLUG = "{SLUG}"')
    text = text.replace(f'"country": "{DISPLAY}"', f'"country": "{SLUG}"')
    text = text.replace('"country": "fsm"', f'"country": "{SLUG}"')
    text = text.replace(f"# {SLUG} filtered pack", f"# {DISPLAY} filtered pack")
    text = text.replace(f"{SLUG} laws IR release", f"{DISPLAY} laws IR release")

    for bad in ("cient-data", "fsment-data", "myanmarent-data"):
        text = text.replace(f"/home/box/{bad}/", "/home/box/agent-data/")
        text = text.replace(bad, "agent-data")

    if dst_name == "myanmar_bm25_smoke.py":
        start = text.index("GATE = [")
        end = text.index("]", start) + 1
        years_line = ", ".join(f'"{y}"' for y in GATE_YEARS)
        stems_line = ", ".join(f'"{s}"' for s in GATE_STEMS)
        gate = f"GATE = [\n    {years_line},\n    {stems_line},\n]"
        text = text[:start] + gate + text[end:]
        text = re.sub(
            r"QUERIES = GATE \+ \[[^\]]*\]",
            'QUERIES = GATE + ["www", "moi.gov.mm", "www.moi.gov.mm", "moi", "gov.mm", "mm", "sea", "cargo", "burma", "union", "state", "ooo"]',
            text,
            count=1,
        )
        text = re.sub(
            r'"""BM25 smoke for .*?"""',
            '"""BM25 smoke for Myanmar IR — English article corpus; ASCII-indexed FTS gate.\n\n'
            "GATE is attested ASCII years + stems from article title/body (shall/goods/carrier/…).\n"
            "Burmese script (laws) and URL moi.gov.mm are query-only, never GATE.\n"
            '"""',
            text,
            count=1,
            flags=re.S,
        )
        note = (
            f"Myanmar ASCII GATE: attested years {GATE_NOTE_YEARS} plus stems {GATE_NOTE_STEMS} "
            f"from articles.parquet HEAD tip {DST_TIP_SHORT}; Burmese and URL moi.gov.mm "
            f"are query-only, not GATE."
        )
        text = re.sub(r'"tokenizer_note":\s*"[^"]*"', f'"tokenizer_note": "{note}"', text, count=1)
        text = text.replace("fsm_pass", "myanmar_pass").replace("fsm_gate", "myanmar_gate")

    if dst_name == "myanmar_write_publish_report.py":
        gate_note = (
            f"BM25 PASS on Myanmar ASCII-fold English GATE "
            f"(attested years {GATE_NOTE_YEARS} + stems {GATE_NOTE_STEMS}); "
            f"URL moi.gov.mm is query-only, not GATE"
        )
        text = re.sub(r'BM25 PASS on Myanmar[^"]*"', gate_note + '"', text, count=1)
        text = re.sub(r'BM25 PASS on [^"]*GATE[^"]*"', gate_note + '"', text, count=1)
        text = re.sub(
            r"HOLD 0 STRICT[^;]*; collectors kept dead \(pkill\); soft never-thin ON[^\"\n]*",
            f"{HOLD}; collectors kept dead (pkill); soft never-thin ON (MM soft-thin OK); SKIP_US; Italy LIVE leave alone; {WAVE_POS}",
            text,
        )
        text = re.sub(r"[ \t]{2,}", " ", text)

    found = []
    for x in ("FSM", "fsm", "cfsm.gov.fm", "micronesia", "federated", "SOFT_FMIN", "SOFT_MMIN"):
        # micronesia/federated may appear only if GATE not rewritten
        if x in ("micronesia", "federated"):
            continue
        if re.search(rf"(?<![A-Za-z0-9_/-]){re.escape(x)}(?![A-Za-z0-9_])", text):
            if x in ("FSM", "fsm", "cfsm.gov.fm", "SOFT_FMIN", "SOFT_MMIN"):
                found.append(x)
    if found:
        raise RuntimeError(f"language/country leftovers in {dst_name}: {found}")
    if "\x00" in text:
        raise RuntimeError(f"null byte leftover in {dst_name}")
    if "SOFT_SDIN" in text or "SOFT_FMIN" in text or "SOFT_MMIN" in text:
        raise RuntimeError(f"SOFT_THIN corruption in {dst_name}")

    if dst_name.endswith("_bm25_smoke.py"):
        gate_slice = text[text.index("GATE = ["): text.index("]", text.index("GATE = [")) + 1]
        for bad in (
            "fsm", "federated", "micronesia", "congress", "public", "code", "section",
            "states", "kosrae", "pohnpei", "2024", "2025", "1979", "2016", "2026",
        ):
            if bad in GATE_STEMS or bad in GATE_YEARS:
                continue
            if f'"{bad}"' in gate_slice:
                raise RuntimeError(f"non-MM token in GATE of {dst_name}: {bad}")
        for stem in GATE_STEMS:
            if f'"{stem}"' not in gate_slice:
                raise RuntimeError(f"missing stem in GATE of {dst_name}: {stem}")
        for year in GATE_YEARS:
            if f'"{year}"' not in gate_slice:
                raise RuntimeError(f"missing year in GATE of {dst_name}: {year}")
        if "cfsm.gov.fm" in text:
            raise RuntimeError(f"leftover cfsm.gov.fm in {dst_name}")

    scrub = text
    for prot in (WAVE_POS, HOLD, DEST_CHAIN, SRC_HOLD, SRC_WAVE):
        scrub = scrub.replace(prot, "XX")
    scrub = scrub.replace("after-FM", "after-XX").replace("after FM ", "after XX ")
    scrub = scrub.replace("FM LIVE", "XX LIVE").replace("DZ+MC+SK+HR+TH+SD+LB+FM", "XX")
    scrub = scrub.replace("DZ+MC+SK+HR+TH+SD+LB", "XX").replace("GH EMPTY", "XX EMPTY")
    if re.search(r"(?<![A-Za-z0-9_])fsm(?![A-Za-z0-9_])", scrub):
        m = re.search(r"(?<![A-Za-z0-9_])fsm(?![A-Za-z0-9_])", scrub)
        raise RuntimeError(f"leftover fsm in {dst_name}: ...{scrub[max(0,m.start()-20):m.start()+20]}...")
    if re.search(r"(?<![A-Za-z%])FM(?![A-Za-z])", scrub):
        m = re.search(r"(?<![A-Za-z%])FM(?![A-Za-z])", scrub)
        raise RuntimeError(f"leftover FM in {dst_name}: ...{scrub[max(0,m.start()-30):m.start()+30]}...")
    if "ipfs_fsm" in text:
        raise RuntimeError(f"leftover fsm path in {dst_name}")
    if SRC_TIP_SHORT in text or SRC_TIP_FULL in text:
        raise RuntimeError(f"src tip leftover in {dst_name}")
    if DST_TIP_SHORT not in text and any(x in dst_name for x in ("soft_filter", "orchestrator", "bm25_smoke")):
        raise RuntimeError(f"missing DST tip in {dst_name}")
    for m in re.finditer(r"b744df8f35b0[0-9a-f]*", text):
        frag = m.group(0)
        if len(frag) >= 40 and frag != DST_TIP_FULL:
            raise RuntimeError(f"corrupted tip SHA in {dst_name}: {frag}")
        if 12 < len(frag) < 40:
            raise RuntimeError(f"truncated/partial tip SHA in {dst_name}: {frag}")
    if "soft_filter" in dst_name or "corpus_stream" in dst_name:
        if "data/laws.parquet" not in text and 'data" / "laws.parquet"' not in text:
            if '"data"' not in text and "/data/" not in text:
                raise RuntimeError(f"missing data/ parquet paths in {dst_name}")
    if "468/16" in text or "FLOOR_LAWS, FLOOR_ARTS = 468, 16" in text:
        raise RuntimeError(f"OLD fsm floor leftover in {dst_name}")
    if "FLOOR_LAWS, FLOOR_ARTS = 725, 12" not in text and "soft_filter" in dst_name:
        raise RuntimeError(f"missing DST floor assign in {dst_name}")
    if "write_publish" in dst_name or "bm25_smoke" in dst_name:
        if re.search(r"cfsm\.gov\.fm|micronesia|kosrae|Federated", text):
            raise RuntimeError(f"leftover FSM phrasing in {dst_name}")
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
    for m in re.finditer(r"b744df8f35b0[0-9a-f]{20,}", t):
        if m.group(0) != DST_TIP_FULL:
            raise RuntimeError(f"post-write corrupted tip in {dst_name}: {m.group(0)}")
    if "SOFT_FMIN" in t or "SOFT_MMIN" in t or "SOFT_SDIN" in t:
        raise RuntimeError(f"SOFT_THIN corruption in {dst_name}")

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
        if entry.get("slug") == SLUG or entry.get("iso2") == "MM":
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
                "language": "Burmese",
                "lang": "Burmese",
                "iso2": "MM",
                "slug": SLUG,
                "repo": "endomorphosis/ipfs_myanmar_laws",
                "years_attested": YEARS_ATTESTED,
                "gate_years": [int(y) for y in GATE_YEARS],
                "gate_stems": GATE_STEMS,
                "note": (
                    f"MM SOFT_THIN_FINAL scaffold; tip MATCH {DST_TIP_SHORT}@725/12; {HOLD}; "
                    f"soft-thin OK; SKIP_US; Italy LIVE leave alone; {WAVE_POS}; "
                    f"English GATE ({len(GATE_YEARS)} years + {len(GATE_STEMS)} stems); "
                    f"memsafe only; do NOT start Iceland or any other country"
                ),
                "status": "CLAIMED",
                "mode": "SOFT_THIN_FINAL",
                "wave_end": False,
                "do_not_start": False,
            })
            break
    else:
        raise RuntimeError(f"Myanmar / MM entry missing from wave JSON {wave}")
    data["wave_status"] = "IN_PROGRESS_MM"
    data["hold"] = HOLD
    data["current"] = SLUG
    data["do_not_start_next"] = "iceland"
    data["next"] = "iceland"
    data["hold_note"] = (
        "HOLD 0 STRICT for MM SOFT_THIN_FINAL build in progress; "
        "do NOT start Iceland or any other country; priors LIVE leave alone"
    )
    wave.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"updated wave JSON {wave}")

print("GATE years", GATE_YEARS)
print("GATE stems", GATE_STEMS)
print("TIP_FULL", DST_TIP_FULL)
print("soft-thin memsafe: 725/12; only MM")
