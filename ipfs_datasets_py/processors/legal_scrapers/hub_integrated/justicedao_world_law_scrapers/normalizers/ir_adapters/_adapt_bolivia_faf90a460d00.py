#!/usr/bin/env python3
"""Adapt Bolivia memsafe pack tip 1c3c200a1948 → tip faf90a460d00.

Same-country tip bump. RECONFIRM_FINAL tip_drift; floor ≥5335/39159.
Spanish GATE from articles.parquet @ faf90a460d00 (ley/decreto/articulo/…).
URL gacetaoficialdebolivia.gob.bo / diputados.gob.bo query-only, NOT GATE.

HOLD 0 STRICT continuous after_wave2 (BO after VN LIVE); WAVE SEVENTH of after_wave2
(BO RECONFIRM; prior six LIVE — do not rebuild; then UY→…→LK — do NOT start those).
Soft never-thin ON; soft_thin=false. SKIP_US; AT queued-only; KW HOLD_THIN; IT leave alone.
Source endomorphosis/ipfs_bolivia_laws → justicedao/ipfs_bolivia_laws_ir.
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
SRC_TIP_FULL = "1c3c200a19485c9c2faacb6691efabbb71ab4b94"
SRC_TIP_SHORT = "1c3c200a1948"
DST_TIP_FULL = "faf90a460d0033a3e442dc3eb5fa8e2d110c4427"
DST_TIP_SHORT = "faf90a460d00"
FLOOR_LAWS, FLOOR_ARTS = 5335, 39159
SRC_FLOOR_L, SRC_FLOOR_A = 2752, 21944

GATE_YEARS = [
    "2023", "2024", "2022", "2021", "2025",
    "2019", "2010", "2013", "2020", "2011",
]
GATE_STEMS = [
    "articulo", "ley", "estado", "constitucion", "plurinacional",
    "ministerio", "bolivia", "decreto", "reglamento", "asamblea",
    "resolucion", "codigo",
]
YEARS_ATTESTED = [int(y) for y in GATE_YEARS] + [
    2018, 2012, 2009, 2017, 1999, 2016, 2015, 2014, 2008, 2005,
]
GATE_NOTE_YEARS = "/".join(GATE_YEARS)
GATE_NOTE_STEMS = "/".join(GATE_STEMS)
HOLD = "HOLD 0 STRICT continuous after_wave2 (BO after VN LIVE)"
WAVE_POS = (
    "SEVENTH of after_wave2 "
    "(BO RECONFIRM; prior six LIVE — do not rebuild; then UY→QA→ZM→AZ→LK — do NOT start those)"
)
DEST_CHAIN = "BO"
SLUG = "bolivia"

FILES = [
    ("bolivia_soft_filter.py", "bolivia_soft_filter.py"),
    (f"bolivia_corpus_stream_{SRC_TIP_SHORT}.py", f"bolivia_corpus_stream_{DST_TIP_SHORT}.py"),
    (f"bolivia_encode_memsafe_{SRC_TIP_SHORT}.py", f"bolivia_encode_memsafe_{DST_TIP_SHORT}.py"),
    (f"bolivia_finish_from_emb_{SRC_TIP_SHORT}.py", f"bolivia_finish_from_emb_{DST_TIP_SHORT}.py"),
    (f"bolivia_stream_graph_parts_{SRC_TIP_SHORT}.py", f"bolivia_stream_graph_parts_{DST_TIP_SHORT}.py"),
    (f"bolivia_package_stream_{SRC_TIP_SHORT}.py", f"bolivia_package_stream_{DST_TIP_SHORT}.py"),
    ("bolivia_upload.py", "bolivia_upload.py"),
    ("bolivia_bm25_smoke.py", "bolivia_bm25_smoke.py"),
    ("bolivia_write_publish_report.py", "bolivia_write_publish_report.py"),
    ("bolivia_tip_check.py", "bolivia_tip_check.py"),
    (f"bolivia_orchestrator_{SRC_TIP_SHORT}.py", f"bolivia_orchestrator_{DST_TIP_SHORT}.py"),
]


def make_bm25() -> str:
    years_line = ", ".join(f'"{y}"' for y in GATE_YEARS)
    stems_line = ", ".join(f'"{s}"' for s in GATE_STEMS)
    note = (
        f"attested years {GATE_NOTE_YEARS} plus Spanish ASCII stems {GATE_NOTE_STEMS} "
        f"from articles.parquet HEAD tip {DST_TIP_SHORT}; URL gacetaoficialdebolivia.gob.bo/"
        f"diputados.gob.bo is query-only, not GATE."
    )
    return f'''#!/usr/bin/env python3
"""BM25 smoke for Bolivia IR — Spanish legal corpus; years + ASCII stems FTS gate.

GATE is attested ASCII years plus Spanish ASCII-fold stems. URL
gacetaoficialdebolivia.gob.bo / diputados.gob.bo is query-only, never GATE.
Every GATE token must rank a hit.
"""
from __future__ import annotations
import json, sys
from pathlib import Path
sys.path.insert(0, "/workspace/country-laws-ir")
from country_laws_ir.query import Release

ROOT = Path("/workspace/country-laws-ir/releases/ipfs_bolivia_laws_ir")
OUT = Path("/workspace/country-laws-ir/reports/bolivia_bm25_smoke_{DST_TIP_SHORT}.json")

GATE = [
    {years_line},
    {stems_line},
]
QUERIES = GATE + [
    "www", "gacetaoficialdebolivia.gob.bo", "diputados.gob.bo",
    "www.gacetaoficialdebolivia.gob.bo", "senado.gob.bo",
    "gaceta", "supremo", "norma", "plurinacional", "constitucion",
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
    detail["bolivia_pass"] = ok
    detail["bolivia_gate"] = GATE
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


def adapt(text: str, dst_name: str) -> str:
    for bad in (
        "cient-data", "prent-data", "stent-data", "cvent-data", "scent-data",
        "carent-data", "yement-data", "boliviaent-data", "sand-data",
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

    text = text.replace("2752/21944", "\x00FLOOR_LA\x00")
    text = text.replace("2752 / 21944", "\x00FLOOR_LA_SP\x00")
    text = text.replace("2752, 21944", "\x00FLOOR_LA_C\x00")
    text = text.replace("FLOOR_LAWS, FLOOR_ARTS = 2752, 21944", "\x00FLOOR_ASSIGN\x00")
    text = text.replace("FLOOR_L, FLOOR_A = 2752, 21944", "\x00FLOOR_ASSIGN2\x00")
    text = text.replace('int(pack.get("n_laws") or 2752)', "\x00OR_LAWS\x00")
    text = text.replace('int(pack.get("n_articles") or 21944)', "\x00OR_ARTS\x00")
    text = text.replace("or 2752)", "\x00OR_LAWS_PAREN\x00")
    text = text.replace("or 21944)", "\x00OR_ARTS_PAREN\x00")
    text = text.replace("@ 2752/", "\x00AT_LAWS\x00")
    text = text.replace("floor 2752/", "\x00FLOOR_SLASH\x00")
    text = text.replace("(2752/", "\x00PAREN_LAWS\x00")
    text = text.replace("= 2752,", "\x00EQ_LAWS\x00")
    text = text.replace(" 21944", "\x00ARTS\x00")
    text = text.replace("21944", "\x00ARTS\x00")
    text = text.replace(" 2752", "\x00LAWS\x00")
    text = text.replace("2752", "\x00LAWS\x00")
    # tip_check stale floors / tips
    text = text.replace("755/7805", "\x00FLOOR_LA\x00")
    text = text.replace("755, 7805", "\x00FLOOR_LA_C\x00")
    text = text.replace("FLOOR_L, FLOOR_A = 755, 7805", "\x00FLOOR_ASSIGN2\x00")
    text = text.replace(" 7805", "\x00ARTS\x00")
    text = text.replace("7805", "\x00ARTS\x00")
    text = text.replace(" 755", "\x00LAWS\x00")
    text = text.replace("755", "\x00LAWS\x00")
    text = text.replace("6c97669d2103f7013a9882b9d7b2e0263ce2fcad", DST_TIP_FULL)
    text = text.replace("6c97669d2103", DST_TIP_SHORT)

    text = text.replace("\x00FLOOR_LA\x00", "5335/39159")
    text = text.replace("\x00FLOOR_LA_SP\x00", "5335 / 39159")
    text = text.replace("\x00FLOOR_LA_C\x00", "5335, 39159")
    text = text.replace("\x00FLOOR_ASSIGN\x00", "FLOOR_LAWS, FLOOR_ARTS = 5335, 39159")
    text = text.replace("\x00FLOOR_ASSIGN2\x00", "FLOOR_L, FLOOR_A = 5335, 39159")
    text = text.replace("\x00OR_LAWS\x00", 'int(pack.get("n_laws") or 5335)')
    text = text.replace("\x00OR_ARTS\x00", 'int(pack.get("n_articles") or 39159)')
    text = text.replace("\x00OR_LAWS_PAREN\x00", "or 5335)")
    text = text.replace("\x00OR_ARTS_PAREN\x00", "or 39159)")
    text = text.replace("\x00AT_LAWS\x00", "@ 5335/")
    text = text.replace("\x00FLOOR_SLASH\x00", "floor 5335/")
    text = text.replace("\x00PAREN_LAWS\x00", "(5335/")
    text = text.replace("\x00EQ_LAWS\x00", "= 5335,")
    text = text.replace("\x00ARTS\x00", "39159")
    text = text.replace("\x00LAWS\x00", "5335")

    for a, b in [
        ("\x00DESTHOLD\x00", HOLD),
        ("\x00DESTWAVE\x00", WAVE_POS),
        ("\x00DESTCHAIN\x00", DEST_CHAIN),
        ("\x00DESTMODE\x00", "RECONFIRM_FINAL"),
        ("Soft filter for EU tip", "Soft filter for Bolivia tip"),
        ("during EU ", "during BO "),
        ("EU FIRST", "BO RECONFIRM_FINAL"),
        ("EU tip", "Bolivia tip"),
        ("FIRST-IR EXPAND", "RECONFIRM_FINAL"),
        ("FIRST_IR EXPAND", "RECONFIRM_FINAL"),
        ("(FIRST-IR EXPAND)", "(RECONFIRM_FINAL)"),
        ("(FIRST_IR EXPAND)", "(RECONFIRM_FINAL)"),
    ]:
        text = text.replace(a, b)

    text = text.replace("\x00BM25\x00", "BM25").replace("\x00bm25\x00", "bm25")
    text = text.replace("\x00TIPSHA_PROTECT\x00", DST_TIP_FULL)
    text = text.replace("\x00TIPSHORT_PROTECT\x00", DST_TIP_SHORT)
    text = text.replace("\x00DESTHOLD\x00", HOLD)
    text = text.replace("\x00DESTCHAIN\x00", DEST_CHAIN)
    text = text.replace("\x00DESTWAVE\x00", WAVE_POS)
    text = text.replace("\x00DESTMODE\x00", "RECONFIRM_FINAL")

    if dst_name == "bolivia_bm25_smoke.py":
        text = make_bm25()

    if dst_name == "bolivia_write_publish_report.py":
        gate_note = (
            f"BM25 PASS on Spanish GATE "
            f"(attested years {GATE_NOTE_YEARS} + stems {GATE_NOTE_STEMS}); "
            f"URL gacetaoficialdebolivia.gob.bo/diputados.gob.bo is query-only, not GATE"
        )
        text = re.sub(r'"BM25 PASS on [^"]*"', f'"{gate_note}"', text, count=1)
        text = text.replace("french_ranked", "gate_ranked")
        text = text.replace(
            "Arabic script empty under ASCII tokenizer as expected",
            "Spanish ASCII-fold GATE; URL hosts query-only",
        )
        text = text.replace(
            "Arabic script queries empty by tokenizer design",
            "Spanish ASCII-fold GATE; URL hosts query-only",
        )

    if dst_name == "bolivia_soft_filter.py":
        text = text.replace(
            "tip pack through with floor checks only (FIRST-IR EXPAND).",
            "tip pack through with floor checks only (RECONFIRM_FINAL).",
        )
        text = text.replace(
            "floor checks only (FIRST-IR EXPAND)",
            "floor checks only (RECONFIRM_FINAL)",
        )
        text = text.replace("FIRST-IR EXPAND", "RECONFIRM_FINAL")
        text = text.replace("FIRST_IR EXPAND", "RECONFIRM_FINAL")

    if dst_name.endswith(f"orchestrator_{DST_TIP_SHORT}.py"):
        text = re.sub(
            r'"""Bolivia.*?"""',
            f'"""Bolivia RECONFIRM_FINAL orchestrator tip {DST_TIP_SHORT} '
            f'(memsafe corpus+encode; {HOLD})."""',
            text,
            count=1,
            flags=re.S,
        )
        text = text.replace(
            '(CACHE / f"bolivia_filtered_{TIP_SHORT}" / "laws.parquet").is_file() '
            'or (CACHE / f"bolivia_filtered_{TIP_SHORT}").is_dir()',
            '(CACHE / f"bolivia_filtered_{TIP_SHORT}" / "data" / "laws.parquet").is_file() '
            'and (CACHE / f"bolivia_filtered_{TIP_SHORT}" / "pack_meta.json").is_file()',
        )
        text = text.replace(
            f'(CACHE / f"bolivia_filtered_{DST_TIP_SHORT}" / "laws.parquet").is_file() '
            f'or (CACHE / f"bolivia_filtered_{DST_TIP_SHORT}").is_dir()',
            f'(CACHE / f"bolivia_filtered_{DST_TIP_SHORT}" / "data" / "laws.parquet").is_file() '
            f'and (CACHE / f"bolivia_filtered_{DST_TIP_SHORT}" / "pack_meta.json").is_file()',
        )
        text = text.replace(
            f'(CACHE / "bolivia_filtered_{DST_TIP_SHORT}" / "laws.parquet").is_file() '
            f'or (CACHE / "bolivia_filtered_{DST_TIP_SHORT}").is_dir()',
            f'(CACHE / "bolivia_filtered_{DST_TIP_SHORT}" / "data" / "laws.parquet").is_file() '
            f'and (CACHE / "bolivia_filtered_{DST_TIP_SHORT}" / "pack_meta.json").is_file()',
        )

    if dst_name == "bolivia_bm25_smoke.py":
        for stem in GATE_STEMS:
            if f'"{stem}"' not in text:
                raise RuntimeError(f"missing Spanish stem in GATE of {dst_name}: {stem}")
        for year in GATE_YEARS:
            if f'"{year}"' not in text:
                raise RuntimeError(f"missing year in GATE of {dst_name}: {year}")

    if SRC_TIP_SHORT in text:
        raise RuntimeError(f"src tip leftover in {dst_name}")
    if SRC_TIP_FULL in text:
        raise RuntimeError(f"src tip full leftover in {dst_name}")
    if "21944" in text:
        raise RuntimeError(f"old arts floor leftover in {dst_name}")
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


def main() -> None:
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
            if isinstance(entry, dict) and (entry.get("slug") == SLUG or entry.get("iso2") == "BO"):
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
                    "ir_hub_head": "4e08ee8c8cb9",
                    "label": "EXPAND",
                    "soft_thin": False,
                    "soft_never_thin": True,
                    "skip_us": True,
                    "italy_leave_alone": True,
                    "language": "Spanish",
                    "lang": "es",
                    "iso2": "BO",
                    "slug": SLUG,
                    "repo": "endomorphosis/ipfs_bolivia_laws",
                    "years_attested": YEARS_ATTESTED,
                    "gate_years": [int(y) for y in GATE_YEARS],
                    "gate_stems": GATE_STEMS,
                    "note": (
                        f"BO RECONFIRM_FINAL scaffold; tip MATCH {DST_TIP_SHORT}@5335/39159; {HOLD}; "
                        f"soft never-thin ON; SKIP_US; Italy leave alone; {WAVE_POS}; "
                        f"Spanish GATE ({len(GATE_YEARS)} years + {len(GATE_STEMS)} stems); "
                        f"prior six LIVE — do not rebuild; do NOT start UY or any other country"
                    ),
                    "status": "CLAIMED",
                    "mode": "RECONFIRM_FINAL",
                    "wave_end": False,
                })
                break
        else:
            print("WARN: BO entry not updated in wave JSON (non-fatal)")
        data["hold"] = HOLD
        data["current"] = SLUG
        data["hold_note"] = (
            "HOLD 0 STRICT continuous for BO RECONFIRM_FINAL build (after_wave2 SEVENTH; "
            "prior six LIVE); do NOT start UY; no soft-lean refill until WAVE END after LK"
        )
        wave.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        for triage in (
            Path("/workspace/country-law-triage/next_ir_ok_wave_after_wave2.json"),
            Path("/workspace/cos_hold0_after_wave2.json"),
        ):
            try:
                if triage.name.startswith("cos_hold0"):
                    hold = {
                        "hold": HOLD,
                        "current": SLUG,
                        "wave": "next_ir_ok_wave_after_wave2",
                        "wave_position": WAVE_POS,
                        "do_not_start": "uruguay",
                        "soft_lean_refill": False,
                        "wave_end": False,
                    }
                    triage.write_text(json.dumps(hold, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
                elif triage.parent.is_dir():
                    triage.write_text(wave.read_text(encoding="utf-8"), encoding="utf-8")
            except Exception as e:
                print(f"WARN triage write {triage}: {e}")
        print("updated wave JSON BO entry")
    else:
        print("WARN: wave JSON missing")

    print("GATE years", GATE_YEARS)
    print("GATE stems", GATE_STEMS)
    print("n_gate", len(GATE_YEARS) + len(GATE_STEMS))
    print("HOLD", HOLD)
    print("floor", f"{FLOOR_LAWS}/{FLOOR_ARTS}; RECONFIRM_FINAL; only BO")


if __name__ == "__main__":
    main()
