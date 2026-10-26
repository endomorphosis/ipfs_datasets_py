#!/usr/bin/env python3
"""Adapt Serbia memsafe pack tip bf646390626d → tip d8fb5912006c.

Same-country tip bump. RECONFIRM_FINAL tip_drift; floor ≥6348/60111.
Serbian (sr) GATE from articles.parquet @ d8fb5912006c
(clan/zakon/srbije/republike/stav/…). URL parlament.gov.rs query-only, NOT GATE.

HOLD 0 STRICT after_wave2 (RS after TN LIVE); WAVE FOURTH of after_wave2
(RS RECONFIRM; PT+AL+TN LIVE — do not rebuild; then AO→…→LK — do NOT start those).
Soft never-thin ON; soft_thin=false. SKIP_US; AT queued-only; KW HOLD_THIN; IT leave alone.
Source endomorphosis/ipfs_serbia_laws → justicedao/ipfs_serbia_laws_ir.
"""
from __future__ import annotations
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
SRC_TIP_FULL = "bf646390626de16d8eda490e48b16c4a8916b776"
SRC_TIP_SHORT = "bf646390626d"
DST_TIP_FULL = "d8fb5912006cee94b8ab412fc7dd4ee49ff59ef0"
DST_TIP_SHORT = "d8fb5912006c"
FLOOR_LAWS, FLOOR_ARTS = 6348, 60111
SRC_FLOOR_L, SRC_FLOOR_A = 3412, 41579

GATE_YEARS = [
    "2025", "2024", "2021", "2026", "2023",
    "2022", "2013", "2018", "2015", "2014",
]
GATE_STEMS = [
    "clan", "clana", "zakon", "zakona", "republike",
    "srbije", "stav", "sluzbeni", "glasnik", "ministarstvo",
    "vlade", "odluka",
]
YEARS_ATTESTED = [int(y) for y in GATE_YEARS] + [
    2020, 2017, 2016, 2012, 2011, 2010, 2019, 2009, 2008, 2005,
]
GATE_NOTE_YEARS = "/".join(GATE_YEARS)
GATE_NOTE_STEMS = "/".join(GATE_STEMS)
HOLD = "HOLD 0 STRICT after_wave2 (RS after TN LIVE)"
WAVE_POS = (
    "FOURTH of after_wave2 "
    "(RS RECONFIRM; PT+AL+TN LIVE — do not rebuild; then AO→VN→BO→UY→QA→ZM→AZ→LK — do NOT start those)"
)
DEST_CHAIN = "RS"
SLUG = "serbia"

FILES = [
    ("serbia_soft_filter.py", "serbia_soft_filter.py"),
    (f"serbia_corpus_stream_{SRC_TIP_SHORT}.py", f"serbia_corpus_stream_{DST_TIP_SHORT}.py"),
    (f"serbia_encode_memsafe_{SRC_TIP_SHORT}.py", f"serbia_encode_memsafe_{DST_TIP_SHORT}.py"),
    (f"serbia_finish_from_emb_{SRC_TIP_SHORT}.py", f"serbia_finish_from_emb_{DST_TIP_SHORT}.py"),
    (f"serbia_stream_graph_parts_{SRC_TIP_SHORT}.py", f"serbia_stream_graph_parts_{DST_TIP_SHORT}.py"),
    (f"serbia_package_stream_{SRC_TIP_SHORT}.py", f"serbia_package_stream_{DST_TIP_SHORT}.py"),
    ("serbia_upload.py", "serbia_upload.py"),
    ("serbia_bm25_smoke.py", "serbia_bm25_smoke.py"),
    ("serbia_write_publish_report.py", "serbia_write_publish_report.py"),
    ("serbia_tip_check.py", "serbia_tip_check.py"),
    (f"serbia_orchestrator_{SRC_TIP_SHORT}.py", f"serbia_orchestrator_{DST_TIP_SHORT}.py"),
]


def adapt(text: str, dst_name: str) -> str:
    for bad in (
        "cient-data", "prent-data", "stent-data", "cvent-data", "scent-data",
        "carent-data", "yement-data", "serbiaent-data", "sand-data",
    ):
        text = text.replace(f"/home/box/{bad}/", "/home/box/agent-data/")
        text = text.replace(bad, "agent-data")

    text = text.replace("BM25", "\x00BM25\x00").replace("bm25", "\x00bm25\x00")
    text = text.replace("bmjacency", "adjacency")

    text = text.replace("RECONFIRM_FINAL", "\x00DESTMODE\x00")
    text = text.replace("FIRST_IR", "\x00DESTMODE\x00")
    text = text.replace("FIRST-IR", "\x00DESTMODE\x00")
    text = text.replace("FIRST IR", "\x00DESTMODE\x00")

    text = text.replace(HOLD, "\x00DESTHOLD\x00")
    text = text.replace(WAVE_POS, "\x00DESTWAVE\x00")
    text = text.replace(DEST_CHAIN, "\x00DESTCHAIN\x00")

    text = text.replace(SRC_TIP_FULL, DST_TIP_FULL)
    text = text.replace(SRC_TIP_SHORT, DST_TIP_SHORT)
    text = text.replace(DST_TIP_FULL, "\x00TIPSHA_PROTECT\x00")
    text = text.replace(DST_TIP_SHORT, "\x00TIPSHORT_PROTECT\x00")

    # Floor 3412/41579 → 6348/60111
    text = text.replace("3412/41579", "\x00FLOOR_LA\x00")
    text = text.replace("3412 / 41579", "\x00FLOOR_LA_SP\x00")
    text = text.replace("3412, 41579", "\x00FLOOR_LA_C\x00")
    text = text.replace("FLOOR_LAWS, FLOOR_ARTS = 3412, 41579", "\x00FLOOR_ASSIGN\x00")
    text = text.replace("FLOOR_L, FLOOR_A = 3412, 41579", "\x00FLOOR_ASSIGN2\x00")
    text = text.replace('int(pack.get("n_laws") or 3412)', "\x00OR_LAWS\x00")
    text = text.replace('int(pack.get("n_articles") or 41579)', "\x00OR_ARTS\x00")
    text = text.replace("or 3412)", "\x00OR_LAWS_PAREN\x00")
    text = text.replace("or 41579)", "\x00OR_ARTS_PAREN\x00")
    text = text.replace("@ 3412/", "\x00AT_LAWS\x00")
    text = text.replace("floor 3412/", "\x00FLOOR_SLASH\x00")
    text = text.replace("(3412/", "\x00PAREN_LAWS\x00")
    text = text.replace("= 3412,", "\x00EQ_LAWS\x00")
    text = text.replace(" 41579", "\x00ARTS\x00")
    text = text.replace("41579", "\x00ARTS\x00")
    text = text.replace(" 3412", "\x00LAWS\x00")
    text = text.replace("3412", "\x00LAWS\x00")
    text = text.replace("\x00FLOOR_LA\x00", "6348/60111")
    text = text.replace("\x00FLOOR_LA_SP\x00", "6348 / 60111")
    text = text.replace("\x00FLOOR_LA_C\x00", "6348, 60111")
    text = text.replace("\x00FLOOR_ASSIGN\x00", "FLOOR_LAWS, FLOOR_ARTS = 6348, 60111")
    text = text.replace("\x00FLOOR_ASSIGN2\x00", "FLOOR_L, FLOOR_A = 6348, 60111")
    text = text.replace("\x00OR_LAWS\x00", 'int(pack.get("n_laws") or 6348)')
    text = text.replace("\x00OR_ARTS\x00", 'int(pack.get("n_articles") or 60111)')
    text = text.replace("\x00OR_LAWS_PAREN\x00", "or 6348)")
    text = text.replace("\x00OR_ARTS_PAREN\x00", "or 60111)")
    text = text.replace("\x00AT_LAWS\x00", "@ 6348/")
    text = text.replace("\x00FLOOR_SLASH\x00", "floor 6348/")
    text = text.replace("\x00PAREN_LAWS\x00", "(6348/")
    text = text.replace("\x00EQ_LAWS\x00", "= 6348,")
    text = text.replace("\x00ARTS\x00", "60111")
    text = text.replace("\x00LAWS\x00", "6348")

    for a, b in [
        ("\x00DESTHOLD\x00", HOLD),
        ("\x00DESTWAVE\x00", WAVE_POS),
        ("\x00DESTCHAIN\x00", DEST_CHAIN),
        ("\x00DESTMODE\x00", "RECONFIRM_FINAL"),
        ("Soft filter for EU tip", "Soft filter for Serbia tip"),
        ("mixed Arabic/English corpus", "Serbian (sr) legal corpus"),
        ("during EU ", "during RS "),
        ("EU FIRST", "RS RECONFIRM_FINAL"),
        ("EU tip", "Serbia tip"),
    ]:
        text = text.replace(a, b)

    text = text.replace("\x00BM25\x00", "BM25").replace("\x00bm25\x00", "bm25")
    text = text.replace("\x00TIPSHA_PROTECT\x00", DST_TIP_FULL)
    text = text.replace("\x00TIPSHORT_PROTECT\x00", DST_TIP_SHORT)
    text = text.replace("\x00DESTHOLD\x00", HOLD)
    text = text.replace("\x00DESTCHAIN\x00", DEST_CHAIN)
    text = text.replace("\x00DESTWAVE\x00", WAVE_POS)
    text = text.replace("\x00DESTMODE\x00", "RECONFIRM_FINAL")

    if dst_name == "serbia_bm25_smoke.py":
        years_line = ", ".join(f'"{y}"' for y in GATE_YEARS)
        stems_line = ", ".join(f'"{s}"' for s in GATE_STEMS)
        note = (
            f"attested years {GATE_NOTE_YEARS} plus Serbian ASCII stems {GATE_NOTE_STEMS} "
            f"from articles.parquet HEAD tip {DST_TIP_SHORT}; URL parlament.gov.rs "
            f"is query-only, not GATE."
        )
        text = f'''#!/usr/bin/env python3
"""BM25 smoke for Serbia IR — Serbian legal corpus; years + Serbian ASCII stems FTS gate.

GATE is attested ASCII years plus Serbian ASCII-fold stems. URL
parlament.gov.rs is query-only, never GATE. Every GATE token must rank a hit.
"""
from __future__ import annotations
import json, sys
from pathlib import Path
sys.path.insert(0, "/workspace/country-laws-ir")
from country_laws_ir.query import Release

ROOT = Path("/workspace/country-laws-ir/releases/ipfs_serbia_laws_ir")
OUT = Path("/workspace/country-laws-ir/reports/serbia_bm25_smoke_{DST_TIP_SHORT}.json")

GATE = [
    {years_line},
    {stems_line},
]
QUERIES = GATE + [
    "www", "parlament.gov.rs", "www.parlament.gov.rs", "rik.parlament.gov.rs",
    "srbija", "uredba", "pravilnik", "resenje", "skupstina", "predsednik",
]


def main() -> int:
    rel = Release(ROOT)
    detail = {{"queries": {{}}, "ranked": [], "empty": [], "pass": False}}
    for q in QUERIES:
        hits = rel.bm25(q, top_k=5)
        top = [
            {{
                "score": h.get("score"),
                "title": (h.get("title") or "")[:120],
                "instrument_id": h.get("instrument_id"),
                "record_type": h.get("record_type"),
                "instrument_title": (h.get("instrument_title") or "")[:80],
            }}
            for h in hits[:3]
        ]
        detail["queries"][q] = {{"n": len(hits), "top": top}}
        if hits:
            detail["ranked"].append(q)
        else:
            detail["empty"].append(q)
    ok = all(q in detail["ranked"] for q in GATE)
    detail["pass"] = ok
    detail["tokenizer_note"] = {note!r}
    detail["serbia_pass"] = ok
    detail["serbia_gate"] = GATE
    detail["tip"] = "{DST_TIP_SHORT}"
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(detail, indent=2, ensure_ascii=False) + "\\n", encoding="utf-8")
    print(json.dumps({{
        "pass": detail["pass"],
        "ranked": detail["ranked"],
        "empty": detail["empty"],
        "n_gate_ranked": sum(1 for q in GATE if q in detail["ranked"]),
        "n_gate": len(GATE),
        "gate": GATE,
    }}, indent=2, ensure_ascii=False))
    return 0 if ok else 1

if __name__ == "__main__":
    raise SystemExit(main())
'''

    if dst_name == "serbia_write_publish_report.py":
        gate_note = (
            f"BM25 PASS on Serbian GATE "
            f"(attested years {GATE_NOTE_YEARS} + stems {GATE_NOTE_STEMS}); "
            f"URL parlament.gov.rs is query-only, not GATE"
        )
        text = re.sub(r'"BM25 PASS on [^"]*"', f'"{gate_note}"', text, count=1)
        text = re.sub(
            r"collectors HOLD 0 during [^\"\n]*",
            f"{HOLD}; collectors kept dead (pkill); soft never-thin ON; SKIP_US; Italy leave alone; {WAVE_POS}",
            text,
        )
        text = re.sub(r"[ \t]{2,}", " ", text)

    if dst_name == "serbia_soft_filter.py":
        text = text.replace(
            "tip pack through with floor checks only (FIRST-IR EXPAND).",
            "tip pack through with floor checks only (RECONFIRM_FINAL).",
        )
        text = text.replace(
            "floor checks only (FIRST-IR EXPAND)",
            "floor checks only (RECONFIRM_FINAL)",
        )

    if dst_name.endswith(f"orchestrator_{DST_TIP_SHORT}.py"):
        text = re.sub(
            r'"""Serbia.*?"""',
            f'"""Serbia RECONFIRM_FINAL orchestrator tip {DST_TIP_SHORT} (memsafe corpus+encode; {HOLD})."""',
            text,
            count=1,
            flags=re.S,
        )

    if dst_name.endswith("_bm25_smoke.py"):
        gate_slice = text[text.index("GATE = ["): text.index("]", text.index("GATE = [")) + 1]
        for bad in ("law", "article", "gov", "https", "iso", "qatar", "emir", "muscat", "arabic"):
            if f'"{bad}"' in gate_slice:
                raise RuntimeError(f"non-RS token in GATE of {dst_name}: {bad}")
        for stem in GATE_STEMS:
            if f'"{stem}"' not in gate_slice:
                raise RuntimeError(f"missing Serbian stem in GATE of {dst_name}: {stem}")
        for year in GATE_YEARS:
            if f'"{year}"' not in gate_slice:
                raise RuntimeError(f"missing year in GATE of {dst_name}: {year}")

    if SRC_TIP_SHORT in text:
        raise RuntimeError(f"src tip leftover in {dst_name}")
    if SRC_TIP_FULL in text:
        raise RuntimeError(f"src tip full leftover in {dst_name}")
    if "3412" in text or "41579" in text:
        raise RuntimeError(f"old floor leftover in {dst_name}")
    if DST_TIP_SHORT not in text and any(
        x in dst_name for x in ("soft_filter", "orchestrator", "bm25_smoke", "upload", "tip_check", "write_publish")
    ):
        raise RuntimeError(f"missing DST tip in {dst_name}")
    if "\x00" in text:
        raise RuntimeError(f"null placeholder leftover in {dst_name}")
    if DST_TIP_FULL in text:
        for c in re.findall(rf"{DST_TIP_SHORT[:8]}[0-9a-f]{{4,}}", text):
            if c != DST_TIP_FULL and c != DST_TIP_SHORT and len(c) == 40:
                raise RuntimeError(f"corrupted tip SHA in {dst_name}: {c}")
    return text


for src_name, dst_name in FILES:
    src = ROOT / src_name
    if not src.is_file():
        raise FileNotFoundError(src)
    (ROOT / dst_name).write_text(adapt(src.read_text(encoding="utf-8"), dst_name), encoding="utf-8")
    print(f"wrote {dst_name}")

wave = Path("/workspace/next_ir_ok_wave_after_wave2.json")
if wave.is_file():
    data = json.loads(wave.read_text(encoding="utf-8"))
    for entry in data.get("queue", []):
        if isinstance(entry, dict) and (entry.get("slug") == SLUG or entry.get("iso2") == "RS"):
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
                "ir_hub_head": "e946ae2d7541",
                "label": "EXPAND",
                "soft_thin": False,
                "soft_never_thin": True,
                "skip_us": True,
                "italy_leave_alone": True,
                "language": "Serbian",
                "lang": "sr",
                "iso2": "RS",
                "slug": SLUG,
                "repo": "endomorphosis/ipfs_serbia_laws",
                "years_attested": YEARS_ATTESTED,
                "gate_years": [int(y) for y in GATE_YEARS],
                "gate_stems": GATE_STEMS,
                "note": (
                    f"RS RECONFIRM_FINAL scaffold; tip MATCH {DST_TIP_SHORT}@6348/60111; {HOLD}; "
                    f"soft never-thin ON; SKIP_US; Italy leave alone; {WAVE_POS}; "
                    f"Serbian GATE ({len(GATE_YEARS)} years + {len(GATE_STEMS)} stems); "
                    f"PT+AL+TN LIVE — do not rebuild; do NOT start AO or any other country"
                ),
                "status": "CLAIMED",
                "mode": "RECONFIRM_FINAL",
                "wave_end": False,
            })
            break
    else:
        print("WARN: RS entry not updated in wave JSON (non-fatal)")
    data["hold"] = HOLD
    data["current"] = SLUG
    data["hold_note"] = (
        "HOLD 0 STRICT for RS RECONFIRM_FINAL build in progress (after_wave2 FOURTH; PT+AL+TN LIVE); "
        "do NOT start AO or any other country"
    )
    wave.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    triage = Path("/workspace/country-law-triage/next_ir_ok_wave_after_wave2.json")
    if triage.parent.is_dir():
        triage.write_text(wave.read_text(encoding="utf-8"), encoding="utf-8")
    print("updated wave JSON RS entry")
else:
    print("WARN: wave JSON missing")

print("GATE years", GATE_YEARS)
print("GATE stems", GATE_STEMS)
print("n_gate", len(GATE_YEARS) + len(GATE_STEMS))
print("HOLD", HOLD)
print("floor", f"{FLOOR_LAWS}/{FLOOR_ARTS}; RECONFIRM_FINAL; only RS")
