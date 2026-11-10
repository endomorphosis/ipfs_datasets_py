#!/usr/bin/env python3
"""Adapt existing Portugal memsafe pack tip 7275937df8ec → tip ddf64fdbbf0c.

Same-country tip bump (NOT Ghana). RECONFIRM_FINAL tip_drift; floor ≥9942/110217.
Portuguese (pt) GATE from articles.parquet @ ddf64fdbbf0c (lei/artigo/decreto/…).
URL dre.pt/incm.pt/gov.pt query-only, NOT GATE.
HOLD 0 STRICT after_wave2 (PT); WAVE FIRST of after_wave2 (PT RECONFIRM; then
AL→TN→RS→AO→VN→BO→UY→QA→ZM→AZ→LK — do NOT start those).
Soft never-thin ON; soft_thin=false for PT. SKIP_US; AT queued-only; KW HOLD_THIN;
IT leave alone. Source endomorphosis/ipfs_portugal_laws → justicedao/ipfs_portugal_laws_ir.
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
SRC_TIP_FULL = "7275937df8ec956156382db1767cbdfcdba6be7b"
SRC_TIP_SHORT = "7275937df8ec"
DST_TIP_FULL = "ddf64fdbbf0c98154a0f89d8f4ce0b7a8d6e7117"
DST_TIP_SHORT = "ddf64fdbbf0c"
FLOOR_LAWS, FLOOR_ARTS = 9942, 110217
SRC_FLOOR_L, SRC_FLOOR_A = 6541, 52977

# Sampled articles.parquet @ ddf64fdbbf0c — ASCII-fold Portuguese legal stems + top years
GATE_YEARS = [
    "2017", "2008", "2007", "2009", "2014",
    "2018", "2016", "2006", "2015", "2013",
]
GATE_STEMS = [
    "lei", "artigo", "decreto", "republica", "portugal",
    "codigo", "diario", "governo", "assembleia", "regulamento", "ministerio",
]
YEARS_ATTESTED = [int(y) for y in GATE_YEARS] + [
    2012, 2004, 2003, 2000, 2001, 2019, 2011, 2010, 2005, 2020, 2021, 2022, 2023, 2024,
]
GATE_NOTE_YEARS = "/".join(GATE_YEARS)
GATE_NOTE_STEMS = "/".join(GATE_STEMS)
HOLD = "HOLD 0 STRICT after_wave2 (PT)"
WAVE_POS = (
    "FIRST of after_wave2 "
    "(PT RECONFIRM; then AL→TN→RS→AO→VN→BO→UY→QA→ZM→AZ→LK — do NOT start those)"
)
DEST_CHAIN = "PT"

FILES = [
    ("portugal_soft_filter.py", "portugal_soft_filter.py"),
    (f"portugal_corpus_stream_{SRC_TIP_SHORT}.py", f"portugal_corpus_stream_{DST_TIP_SHORT}.py"),
    (f"portugal_encode_memsafe_{SRC_TIP_SHORT}.py", f"portugal_encode_memsafe_{DST_TIP_SHORT}.py"),
    (f"portugal_finish_from_emb_{SRC_TIP_SHORT}.py", f"portugal_finish_from_emb_{DST_TIP_SHORT}.py"),
    (f"portugal_stream_graph_parts_{SRC_TIP_SHORT}.py", f"portugal_stream_graph_parts_{DST_TIP_SHORT}.py"),
    (f"portugal_package_stream_{SRC_TIP_SHORT}.py", f"portugal_package_stream_{DST_TIP_SHORT}.py"),
    ("portugal_upload.py", "portugal_upload.py"),
    ("portugal_bm25_smoke.py", "portugal_bm25_smoke.py"),
    ("portugal_write_publish_report.py", "portugal_write_publish_report.py"),
    ("portugal_tip_check.py", "portugal_tip_check.py"),
    (f"portugal_orchestrator_{SRC_TIP_SHORT}.py", f"portugal_orchestrator_{DST_TIP_SHORT}.py"),
]

DISPLAY = "Portugal"
SLUG = "portugal"


def adapt(text: str, dst_name: str) -> str:
    for bad in (
        "cient-data", "prent-data", "stent-data", "cvent-data", "scent-data",
        "carent-data", "yement-data", "portugalent-data",
    ):
        text = text.replace(f"/home/box/{bad}/", "/home/box/agent-data/")
        text = text.replace(bad, "agent-data")

    text = text.replace("BM25", "\x00BM25\x00").replace("bm25", "\x00bm25\x00")
    text = text.replace("bmjacency", "adjacency")

    # Mode: FIRST-IR / FIRST_IR → RECONFIRM_FINAL
    text = text.replace("RECONFIRM_FINAL", "\x00DESTMODE\x00")
    text = text.replace("FIRST_IR", "\x00DESTMODE\x00")
    text = text.replace("FIRST-IR", "\x00DESTMODE\x00")
    text = text.replace("FIRST IR", "\x00DESTMODE\x00")

    text = text.replace(HOLD, "\x00DESTHOLD\x00")
    text = text.replace(WAVE_POS, "\x00DESTWAVE\x00")
    text = text.replace(DEST_CHAIN, "\x00DESTCHAIN\x00")
    text = text.replace("67930c3f-c94b-445b-a5bc-01d3fc1135c1", "\x00UUID94\x00")

    # Tip swaps THEN protect tip SHA before any digit floor swaps
    text = text.replace(SRC_TIP_FULL, DST_TIP_FULL)
    text = text.replace(SRC_TIP_SHORT, DST_TIP_SHORT)
    text = text.replace(DST_TIP_FULL, "\x00TIPSHA_PROTECT\x00")
    text = text.replace(DST_TIP_SHORT, "\x00TIPSHORT_PROTECT\x00")

    # Floor 6541/52977 → 9942/110217 via placeholders
    text = text.replace("6541/52977", "\x00FLOOR_LA\x00")
    text = text.replace("6541 / 52977", "\x00FLOOR_LA_SP\x00")
    text = text.replace("6541, 52977", "\x00FLOOR_LA_C\x00")
    text = text.replace("FLOOR_LAWS, FLOOR_ARTS = 6541, 52977", "\x00FLOOR_ASSIGN\x00")
    text = text.replace("FLOOR_L, FLOOR_A = 6541, 52977", "\x00FLOOR_ASSIGN2\x00")
    text = text.replace('int(pack.get("n_laws") or 6541)', "\x00OR_LAWS\x00")
    text = text.replace('int(pack.get("n_articles") or 52977)', "\x00OR_ARTS\x00")
    text = text.replace("or 6541)", "\x00OR_LAWS_PAREN\x00")
    text = text.replace("or 52977)", "\x00OR_ARTS_PAREN\x00")
    text = text.replace("@ 6541/", "\x00AT_LAWS\x00")
    text = text.replace("floor 6541/", "\x00FLOOR_SLASH\x00")
    text = text.replace("(6541/", "\x00PAREN_LAWS\x00")
    text = text.replace("= 6541,", "\x00EQ_LAWS\x00")
    text = text.replace(" 52977", "\x00ARTS\x00")
    text = text.replace("52977", "\x00ARTS\x00")
    text = text.replace(" 6541", "\x00LAWS\x00")
    text = text.replace("6541", "\x00LAWS\x00")
    text = text.replace("\x00FLOOR_LA\x00", "9942/110217")
    text = text.replace("\x00FLOOR_LA_SP\x00", "9942 / 110217")
    text = text.replace("\x00FLOOR_LA_C\x00", "9942, 110217")
    text = text.replace("\x00FLOOR_ASSIGN\x00", "FLOOR_LAWS, FLOOR_ARTS = 9942, 110217")
    text = text.replace("\x00FLOOR_ASSIGN2\x00", "FLOOR_L, FLOOR_A = 9942, 110217")
    text = text.replace("\x00OR_LAWS\x00", 'int(pack.get("n_laws") or 9942)')
    text = text.replace("\x00OR_ARTS\x00", 'int(pack.get("n_articles") or 110217)')
    text = text.replace("\x00OR_LAWS_PAREN\x00", "or 9942)")
    text = text.replace("\x00OR_ARTS_PAREN\x00", "or 110217)")
    text = text.replace("\x00AT_LAWS\x00", "@ 9942/")
    text = text.replace("\x00FLOOR_SLASH\x00", "floor 9942/")
    text = text.replace("\x00PAREN_LAWS\x00", "(9942/")
    text = text.replace("\x00EQ_LAWS\x00", "= 9942,")
    text = text.replace("\x00ARTS\x00", "110217")
    text = text.replace("\x00LAWS\x00", "9942")

    reps = [
        ("\x00DESTHOLD\x00", HOLD),
        ("\x00DESTWAVE\x00", WAVE_POS),
        ("\x00DESTCHAIN\x00", DEST_CHAIN),
        ("\x00DESTMODE\x00", "RECONFIRM_FINAL"),
        ("Spanish Portugal", "Portuguese Portugal"),
        ("Spanish legal", "Portuguese legal"),
        ("EUR-Lex English legal terms", "Portuguese legal GATE (lei/artigo/decreto)"),
        ("EU tip", "Portugal tip"),
        ("EU FIRST", "PT RECONFIRM_FINAL"),
        ("during EU ", "during PT "),
        ("~50k (DO OOM lesson)", "~110k articles (memsafe)"),
    ]
    for a, b in reps:
        text = text.replace(a, b)

    text = text.replace("\x00BM25\x00", "BM25").replace("\x00bm25\x00", "bm25")
    text = text.replace("\x00TIPSHA_PROTECT\x00", DST_TIP_FULL)
    text = text.replace("\x00TIPSHORT_PROTECT\x00", DST_TIP_SHORT)
    text = text.replace("\x00UUID94\x00", "67930c3f-c94b-445b-a5bc-01d3fc1135c1")
    text = text.replace("\x00DESTHOLD\x00", HOLD)
    text = text.replace("\x00DESTCHAIN\x00", DEST_CHAIN)
    text = text.replace("\x00DESTWAVE\x00", WAVE_POS)
    text = text.replace("\x00DESTMODE\x00", "RECONFIRM_FINAL")

    for bad in ("cient-data", "prent-data", "portugalent-data"):
        text = text.replace(f"/home/box/{bad}/", "/home/box/agent-data/")
        text = text.replace(bad, "agent-data")

    if dst_name == "portugal_bm25_smoke.py":
        start = text.index("GATE = [")
        end = text.index("]", start) + 1
        years_line = ", ".join(f'"{y}"' for y in GATE_YEARS)
        stems_line = ", ".join(f'"{s}"' for s in GATE_STEMS)
        gate = f"GATE = [\n    {years_line},\n    {stems_line},\n]"
        text = text[:start] + gate + text[end:]
        # Rewrite QUERIES list (old style was QUERIES = [ stems... ] not GATE+)
        if "QUERIES = GATE +" in text:
            text = re.sub(
                r"QUERIES = GATE \+ \[[^\]]*\]",
                'QUERIES = GATE + ["www", "dre.pt", "incm.pt", "gov.pt", "www.dre.pt", "diario", "republica", "portaria", "despacho", "alinea"]',
                text,
                count=1,
            )
        else:
            # Replace QUERIES = [ ... ] block
            qstart = text.index("QUERIES = [")
            # find matching close bracket at indent 0-ish — first ] after list
            # careful: use bracket depth
            i = qstart + len("QUERIES = [")
            depth = 1
            while i < len(text) and depth:
                if text[i] == "[":
                    depth += 1
                elif text[i] == "]":
                    depth -= 1
                i += 1
            qnew = (
                "QUERIES = GATE + ["
                '"www", "dre.pt", "incm.pt", "gov.pt", "www.dre.pt", '
                '"portaria", "despacho", "alinea", "constituicao", "numero"]'
            )
            text = text[:qstart] + qnew + text[i:]
        text = re.sub(
            r'"""BM25 smoke for .*?"""',
            '"""BM25 smoke for Portugal IR — Portuguese legal corpus; years + Portuguese ASCII stems FTS gate.\n\n'
            "GATE is attested ASCII years plus Portuguese ASCII-fold stems. URL\n"
            "dre.pt / incm.pt / gov.pt is query-only, never GATE. Every GATE token must rank a hit.\n"
            '"""',
            text,
            count=1,
            flags=re.S,
        )
        note = (
            f"attested years {GATE_NOTE_YEARS} plus Portuguese ASCII stems {GATE_NOTE_STEMS} "
            f"from articles.parquet HEAD tip {DST_TIP_SHORT}; URL dre.pt/incm.pt/gov.pt "
            f"is query-only, not GATE."
        )
        text = re.sub(
            r'"tokenizer_note":\s*"[^"]*"',
            f'"tokenizer_note": "{note}"',
            text,
            count=1,
        )

    if dst_name == "portugal_write_publish_report.py":
        gate_note = (
            f"BM25 PASS on Portuguese GATE "
            f"(attested years {GATE_NOTE_YEARS} + stems {GATE_NOTE_STEMS}); "
            f"URL dre.pt/incm.pt/gov.pt is query-only, not GATE"
        )
        text = re.sub(
            r'"BM25 PASS on [^"]*"',
            f'"{gate_note}"',
            text,
            count=1,
        )
        text = re.sub(
            r"collectors HOLD 0 during [^\"\n]*",
            f"{HOLD}; collectors kept dead (pkill); soft never-thin ON; SKIP_US; Italy leave alone; {WAVE_POS}",
            text,
        )
        text = re.sub(r"[ \t]{2,}", " ", text)

    if dst_name == "portugal_soft_filter.py":
        text = text.replace(
            "tip pack through with floor checks only (FIRST-IR EXPAND).",
            "tip pack through with floor checks only (RECONFIRM_FINAL).",
        )
        text = text.replace(
            "tip pack through with floor checks only (RECONFIRM_FINAL EXPAND).",
            "tip pack through with floor checks only (RECONFIRM_FINAL).",
        )
        text = text.replace(
            "floor checks only (FIRST-IR EXPAND)",
            "floor checks only (RECONFIRM_FINAL)",
        )

    if dst_name == "portugal_orchestrator_ddf64fdbbf0c.py" or dst_name.endswith(f"orchestrator_{DST_TIP_SHORT}.py"):
        text = text.replace(
            f'portugal_corpus_stream_{SRC_TIP_SHORT}.py',
            f"portugal_corpus_stream_{DST_TIP_SHORT}.py",
        )
        # already tip-replaced; ensure RECONFIRM note in docstring
        text = re.sub(
            r'"""Portugal.*?"""',
            f'"""Portugal RECONFIRM_FINAL orchestrator tip {DST_TIP_SHORT} (memsafe corpus+encode; {HOLD})."""',
            text,
            count=1,
            flags=re.S,
        )

    if dst_name.endswith("_bm25_smoke.py"):
        gate_slice = text[text.index("GATE = ["): text.index("]", text.index("GATE = [")) + 1]
        for bad in (
            "spanish", "ordinance", "shall", "loi", "decret", "ghana", "iceland",
        ):
            if f'"{bad}"' in gate_slice:
                raise RuntimeError(f"non-PT token in GATE of {dst_name}: {bad}")
        for stem in GATE_STEMS:
            if f'"{stem}"' not in gate_slice:
                raise RuntimeError(f"missing Portuguese stem in GATE of {dst_name}: {stem}")
        for year in GATE_YEARS:
            if f'"{year}"' not in gate_slice:
                raise RuntimeError(f"missing year in GATE of {dst_name}: {year}")

    if SRC_TIP_SHORT in text:
        raise RuntimeError(f"src tip leftover in {dst_name}")
    if SRC_TIP_FULL in text:
        raise RuntimeError(f"src tip full leftover in {dst_name}")
    if "6541" in text or "52977" in text:
        # allow if inside unrelated numbers — flag
        raise RuntimeError(f"old floor leftover in {dst_name}")
    if DST_TIP_SHORT not in text and any(
        x in dst_name for x in ("soft_filter", "orchestrator", "bm25_smoke", "upload", "tip_check", "write_publish")
    ):
        raise RuntimeError(f"missing DST tip in {dst_name}")
    if "soft_filter" in dst_name or "corpus_stream" in dst_name:
        if "data/laws.parquet" not in text and 'data" / "laws.parquet"' not in text:
            if '"data"' not in text and "/data/" not in text:
                raise RuntimeError(f"missing data/ parquet paths in {dst_name}")
    if "\x00" in text:
        raise RuntimeError(f"null placeholder leftover in {dst_name}")
    # tip integrity
    if DST_TIP_FULL in text:
        corrupt = re.findall(rf"{DST_TIP_SHORT[:8]}[0-9a-f]{{4,}}", text)
        for c in corrupt:
            if c != DST_TIP_FULL and c != DST_TIP_SHORT and len(c) == 40:
                raise RuntimeError(f"corrupted tip SHA in {dst_name}: {c}")
    return text


for src_name, dst_name in FILES:
    src = ROOT / src_name
    if not src.is_file():
        raise FileNotFoundError(src)
    # For in-place files, read SRC first before overwrite
    raw = src.read_text(encoding="utf-8")
    (ROOT / dst_name).write_text(adapt(raw, dst_name), encoding="utf-8")
    print(f"wrote {dst_name}")

# Update wave JSON
wave = Path("/workspace/next_ir_ok_wave_after_wave2.json")
data = json.loads(wave.read_text(encoding="utf-8"))
for entry in data.get("queue", data if isinstance(data, list) else []):
    if not isinstance(entry, dict):
        continue
    if entry.get("slug") == SLUG or entry.get("iso2") == "PT":
        entry.update({
            "tip": DST_TIP_SHORT,
            "tip_full": DST_TIP_FULL,
            "laws": FLOOR_LAWS,
            "articles": FLOOR_ARTS,
            "floor_laws": FLOOR_LAWS,
            "floor_articles": FLOOR_ARTS,
            "L_A": f"{FLOOR_LAWS}/{FLOOR_ARTS}",
            "claim_tip": DST_TIP_SHORT,
            "match_claim": True,
            "ir_hub_head": "4c440e945c90",
            "label": "EXPAND",
            "soft_thin": False,
            "soft_never_thin": True,
            "skip_us": True,
            "italy_leave_alone": True,
            "language": "Portuguese",
            "lang": "Portuguese",
            "iso2": "PT",
            "slug": SLUG,
            "repo": "endomorphosis/ipfs_portugal_laws",
            "years_attested": YEARS_ATTESTED,
            "gate_years": [int(y) for y in GATE_YEARS],
            "gate_stems": GATE_STEMS,
            "note": (
                f"PT RECONFIRM_FINAL scaffold; tip MATCH {DST_TIP_SHORT}@9942/110217; {HOLD}; "
                f"soft never-thin ON; SKIP_US; Italy leave alone; {WAVE_POS}; "
                f"Portuguese GATE ({len(GATE_YEARS)} years + {len(GATE_STEMS)} stems); "
                f"do NOT start AL or any other country"
            ),
            "status": "CLAIMED",
            "mode": "RECONFIRM_FINAL",
            "wave_end": False,
            "do_not_start": False,
        })
        break
else:
    # try top-level countries list
    found = False
    for key in ("countries", "items", "entries"):
        for entry in data.get(key, []) or []:
            if isinstance(entry, dict) and (entry.get("slug") == SLUG or entry.get("iso2") == "PT"):
                entry["status"] = "CLAIMED"
                entry["tip"] = DST_TIP_SHORT
                found = True
                break
        if found:
            break
    if not found:
        print("WARN: PT entry shape not updated in wave JSON (non-fatal; cos_hold0 owns queue)")

data["hold"] = HOLD
data["current"] = SLUG
data["hold_note"] = (
    "HOLD 0 STRICT for PT RECONFIRM_FINAL build in progress (after_wave2 FIRST); "
    "do NOT start AL or any other country"
)
wave.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
triage = Path("/workspace/country-law-triage/next_ir_ok_wave_after_wave2.json")
if triage.parent.is_dir():
    triage.write_text(wave.read_text(encoding="utf-8"), encoding="utf-8")
print("updated wave JSON PT entry")
print("GATE years", GATE_YEARS)
print("GATE stems", GATE_STEMS)
print("n_gate", len(GATE_YEARS) + len(GATE_STEMS))
print("HOLD", HOLD)
print("floor", f"{FLOOR_LAWS}/{FLOOR_ARTS}; RECONFIRM_FINAL; only PT")
