#!/usr/bin/env python3
"""Adapt Angola memsafe pack tip 66f6d7ad9b80 → tip 98bcdcd60620.

Same-country tip bump. RECONFIRM_FINAL tip_drift; floor ≥5480/53019.
Portuguese (Angola) GATE from articles.parquet @ 98bcdcd60620
(artigo/lei/decreto/angola/republica/…). URL sme.ao/parlamento.ao/minfin.gov.ao
query-only, NOT GATE.

HOLD 0 STRICT after_wave2 (AO after RS LIVE); WAVE FIFTH of after_wave2
(AO RECONFIRM; PT+AL+TN+RS LIVE — do not rebuild; then VN→…→LK — do NOT start those).
Soft never-thin ON; soft_thin=false. SKIP_US; AT queued-only; KW HOLD_THIN; IT leave alone.
Source endomorphosis/ipfs_angola_laws → justicedao/ipfs_angola_laws_ir.
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
SRC_TIP_FULL = "66f6d7ad9b809ab535ae1cf3a3f8af6601850fe3"
SRC_TIP_SHORT = "66f6d7ad9b80"
DST_TIP_FULL = "98bcdcd606203dfceb4e47600ca8757ba0af775b"
DST_TIP_SHORT = "98bcdcd60620"
FLOOR_LAWS, FLOOR_ARTS = 5480, 53019
SRC_FLOOR_L, SRC_FLOOR_A = 2856, 31073

GATE_YEARS = [
    "2025", "2017", "2018", "2022", "2016",
    "2015", "2023", "2014", "2024", "2019",
]
GATE_STEMS = [
    "artigo", "nacional", "angola", "lei", "republica",
    "ministerio", "diario", "decreto", "executivo", "assembleia",
    "constituicao", "codigo",
]
YEARS_ATTESTED = [int(y) for y in GATE_YEARS] + [
    2013, 2020, 2021, 2012, 2011, 2010, 2009, 2008, 2005, 2000,
]
GATE_NOTE_YEARS = "/".join(GATE_YEARS)
GATE_NOTE_STEMS = "/".join(GATE_STEMS)
HOLD = "HOLD 0 STRICT after_wave2 (AO after RS LIVE)"
WAVE_POS = (
    "FIFTH of after_wave2 "
    "(AO RECONFIRM; PT+AL+TN+RS LIVE — do not rebuild; then VN→BO→UY→QA→ZM→AZ→LK — do NOT start those)"
)
DEST_CHAIN = "AO"
SLUG = "angola"

FILES = [
    ("angola_soft_filter.py", "angola_soft_filter.py"),
    (f"angola_corpus_stream_{SRC_TIP_SHORT}.py", f"angola_corpus_stream_{DST_TIP_SHORT}.py"),
    (f"angola_encode_memsafe_{SRC_TIP_SHORT}.py", f"angola_encode_memsafe_{DST_TIP_SHORT}.py"),
    (f"angola_finish_from_emb_{SRC_TIP_SHORT}.py", f"angola_finish_from_emb_{DST_TIP_SHORT}.py"),
    (f"angola_stream_graph_parts_{SRC_TIP_SHORT}.py", f"angola_stream_graph_parts_{DST_TIP_SHORT}.py"),
    (f"angola_package_stream_{SRC_TIP_SHORT}.py", f"angola_package_stream_{DST_TIP_SHORT}.py"),
    ("angola_upload.py", "angola_upload.py"),
    ("angola_bm25_smoke.py", "angola_bm25_smoke.py"),
    ("angola_write_publish_report.py", "angola_write_publish_report.py"),
    ("angola_tip_check.py", "angola_tip_check.py"),
    (f"angola_orchestrator_{SRC_TIP_SHORT}.py", f"angola_orchestrator_{DST_TIP_SHORT}.py"),
]


def adapt(text: str, dst_name: str) -> str:
    for bad in (
        "cient-data", "prent-data", "stent-data", "cvent-data", "scent-data",
        "carent-data", "yement-data", "angolaent-data", "sand-data",
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

    # Floor 2856/31073 → 5480/53019
    text = text.replace("2856/31073", "\x00FLOOR_LA\x00")
    text = text.replace("2856 / 31073", "\x00FLOOR_LA_SP\x00")
    text = text.replace("2856, 31073", "\x00FLOOR_LA_C\x00")
    text = text.replace("FLOOR_LAWS, FLOOR_ARTS = 2856, 31073", "\x00FLOOR_ASSIGN\x00")
    text = text.replace("FLOOR_L, FLOOR_A = 2856, 31073", "\x00FLOOR_ASSIGN2\x00")
    text = text.replace('int(pack.get("n_laws") or 2856)', "\x00OR_LAWS\x00")
    text = text.replace('int(pack.get("n_articles") or 31073)', "\x00OR_ARTS\x00")
    text = text.replace("or 2856)", "\x00OR_LAWS_PAREN\x00")
    text = text.replace("or 31073)", "\x00OR_ARTS_PAREN\x00")
    text = text.replace("@ 2856/", "\x00AT_LAWS\x00")
    text = text.replace("floor 2856/", "\x00FLOOR_SLASH\x00")
    text = text.replace("(2856/", "\x00PAREN_LAWS\x00")
    text = text.replace("= 2856,", "\x00EQ_LAWS\x00")
    text = text.replace(" 31073", "\x00ARTS\x00")
    text = text.replace("31073", "\x00ARTS\x00")
    text = text.replace(" 2856", "\x00LAWS\x00")
    text = text.replace("2856", "\x00LAWS\x00")
    # tip_check stale floors
    text = text.replace("1012/17715", "\x00FLOOR_LA\x00")
    text = text.replace("1012, 17715", "\x00FLOOR_LA_C\x00")
    text = text.replace("FLOOR_L, FLOOR_A = 1012, 17715", "\x00FLOOR_ASSIGN2\x00")
    text = text.replace(" 17715", "\x00ARTS\x00")
    text = text.replace("17715", "\x00ARTS\x00")
    text = text.replace(" 1012", "\x00LAWS\x00")
    text = text.replace("1012", "\x00LAWS\x00")
    text = text.replace("\x00FLOOR_LA\x00", "5480/53019")
    text = text.replace("\x00FLOOR_LA_SP\x00", "5480 / 53019")
    text = text.replace("\x00FLOOR_LA_C\x00", "5480, 53019")
    text = text.replace("\x00FLOOR_ASSIGN\x00", "FLOOR_LAWS, FLOOR_ARTS = 5480, 53019")
    text = text.replace("\x00FLOOR_ASSIGN2\x00", "FLOOR_L, FLOOR_A = 5480, 53019")
    text = text.replace("\x00OR_LAWS\x00", 'int(pack.get("n_laws") or 5480)')
    text = text.replace("\x00OR_ARTS\x00", 'int(pack.get("n_articles") or 53019)')
    text = text.replace("\x00OR_LAWS_PAREN\x00", "or 5480)")
    text = text.replace("\x00OR_ARTS_PAREN\x00", "or 53019)")
    text = text.replace("\x00AT_LAWS\x00", "@ 5480/")
    text = text.replace("\x00FLOOR_SLASH\x00", "floor 5480/")
    text = text.replace("\x00PAREN_LAWS\x00", "(5480/")
    text = text.replace("\x00EQ_LAWS\x00", "= 5480,")
    text = text.replace("\x00ARTS\x00", "53019")
    text = text.replace("\x00LAWS\x00", "5480")

    # tip_check may still have old tip c8bf70a80aea
    text = text.replace("c8bf70a80aea8d8840e13ae40bc6d81ffaebcb96", DST_TIP_FULL)
    text = text.replace("c8bf70a80aea", DST_TIP_SHORT)

    for a, b in [
        ("\x00DESTHOLD\x00", HOLD),
        ("\x00DESTWAVE\x00", WAVE_POS),
        ("\x00DESTCHAIN\x00", DEST_CHAIN),
        ("\x00DESTMODE\x00", "RECONFIRM_FINAL"),
        ("Soft filter for EU tip", "Soft filter for Angola tip"),
        ("during EU ", "during AO "),
        ("EU FIRST", "AO RECONFIRM_FINAL"),
        ("EU tip", "Angola tip"),
    ]:
        text = text.replace(a, b)

    text = text.replace("\x00BM25\x00", "BM25").replace("\x00bm25\x00", "bm25")
    text = text.replace("\x00TIPSHA_PROTECT\x00", DST_TIP_FULL)
    text = text.replace("\x00TIPSHORT_PROTECT\x00", DST_TIP_SHORT)
    text = text.replace("\x00DESTHOLD\x00", HOLD)
    text = text.replace("\x00DESTCHAIN\x00", DEST_CHAIN)
    text = text.replace("\x00DESTWAVE\x00", WAVE_POS)
    text = text.replace("\x00DESTMODE\x00", "RECONFIRM_FINAL")

    if dst_name == "angola_bm25_smoke.py":
        years_line = ", ".join(f'"{y}"' for y in GATE_YEARS)
        stems_line = ", ".join(f'"{s}"' for s in GATE_STEMS)
        note = (
            f"attested years {GATE_NOTE_YEARS} plus Angolan Portuguese ASCII stems {GATE_NOTE_STEMS} "
            f"from articles.parquet HEAD tip {DST_TIP_SHORT}; URL sme.ao/parlamento.ao/minfin.gov.ao "
            f"is query-only, not GATE."
        )
        text = f'''#!/usr/bin/env python3
"""BM25 smoke for Angola IR — Portuguese (Angola) legal corpus; years + ASCII stems FTS gate.

GATE is attested ASCII years plus Angolan Portuguese ASCII-fold stems. URL
sme.ao / parlamento.ao / minfin.gov.ao is query-only, never GATE. Every GATE token must rank a hit.
"""
from __future__ import annotations
import json, sys
from pathlib import Path
sys.path.insert(0, "/workspace/country-laws-ir")
from country_laws_ir.query import Release

ROOT = Path("/workspace/country-laws-ir/releases/ipfs_angola_laws_ir")
OUT = Path("/workspace/country-laws-ir/reports/angola_bm25_smoke_{DST_TIP_SHORT}.json")

GATE = [
    {years_line},
    {stems_line},
]
QUERIES = GATE + [
    "www", "sme.ao", "parlamento.ao", "minfin.gov.ao", "www.parlamento.ao",
    "portais.gov.ao", "despacho", "portaria", "resolucao", "presidencia",
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
    detail["angola_pass"] = ok
    detail["angola_gate"] = GATE
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

    if dst_name == "angola_write_publish_report.py":
        gate_note = (
            f"BM25 PASS on Angolan Portuguese GATE "
            f"(attested years {GATE_NOTE_YEARS} + stems {GATE_NOTE_STEMS}); "
            f"URL sme.ao/parlamento.ao/minfin.gov.ao is query-only, not GATE"
        )
        text = re.sub(r'"BM25 PASS on [^"]*"', f'"{gate_note}"', text, count=1)
        text = re.sub(
            r"collectors HOLD 0 during [^\"\n]*",
            f"{HOLD}; collectors kept dead (pkill); soft never-thin ON; SKIP_US; Italy leave alone; {WAVE_POS}",
            text,
        )
        text = re.sub(r"[ \t]{2,}", " ", text)

    if dst_name == "angola_soft_filter.py":
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
            r'"""Angola.*?"""',
            f'"""Angola RECONFIRM_FINAL orchestrator tip {DST_TIP_SHORT} (memsafe corpus+encode; {HOLD})."""',
            text,
            count=1,
            flags=re.S,
        )
        # Tighten soft_filter done-check
        text = text.replace(
            f'(CACHE / f"angola_filtered_{{TIP_SHORT}}" / "laws.parquet").is_file() '
            f'or (CACHE / f"angola_filtered_{{TIP_SHORT}}").is_dir()',
            f'(CACHE / f"angola_filtered_{{TIP_SHORT}}" / "data" / "laws.parquet").is_file() '
            f'and (CACHE / f"angola_filtered_{{TIP_SHORT}}" / "pack_meta.json").is_file()',
        )
        text = text.replace(
            f'(CACHE / f"angola_filtered_{DST_TIP_SHORT}" / "laws.parquet").is_file() '
            f'or (CACHE / f"angola_filtered_{DST_TIP_SHORT}").is_dir()',
            f'(CACHE / f"angola_filtered_{DST_TIP_SHORT}" / "data" / "laws.parquet").is_file() '
            f'and (CACHE / f"angola_filtered_{DST_TIP_SHORT}" / "pack_meta.json").is_file()',
        )

    if dst_name.endswith("_bm25_smoke.py"):
        gate_slice = text[text.index("GATE = ["): text.index("]", text.index("GATE = [")) + 1]
        for bad in ("law", "article", "gov", "https", "iso", "qatar", "emir", "muscat", "serbia", "clan"):
            if f'"{bad}"' in gate_slice:
                raise RuntimeError(f"non-AO token in GATE of {dst_name}: {bad}")
        for stem in GATE_STEMS:
            if f'"{stem}"' not in gate_slice:
                raise RuntimeError(f"missing Angolan stem in GATE of {dst_name}: {stem}")
        for year in GATE_YEARS:
            if f'"{year}"' not in gate_slice:
                raise RuntimeError(f"missing year in GATE of {dst_name}: {year}")

    if SRC_TIP_SHORT in text:
        raise RuntimeError(f"src tip leftover in {dst_name}")
    if SRC_TIP_FULL in text:
        raise RuntimeError(f"src tip full leftover in {dst_name}")
    if "2856" in text or "31073" in text:
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
        if isinstance(entry, dict) and (entry.get("slug") == SLUG or entry.get("iso2") == "AO"):
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
                "ir_hub_head": "16a0645305fa",
                "label": "EXPAND",
                "soft_thin": False,
                "soft_never_thin": True,
                "skip_us": True,
                "italy_leave_alone": True,
                "language": "Portuguese",
                "lang": "pt",
                "iso2": "AO",
                "slug": SLUG,
                "repo": "endomorphosis/ipfs_angola_laws",
                "years_attested": YEARS_ATTESTED,
                "gate_years": [int(y) for y in GATE_YEARS],
                "gate_stems": GATE_STEMS,
                "note": (
                    f"AO RECONFIRM_FINAL scaffold; tip MATCH {DST_TIP_SHORT}@5480/53019; {HOLD}; "
                    f"soft never-thin ON; SKIP_US; Italy leave alone; {WAVE_POS}; "
                    f"Angolan Portuguese GATE ({len(GATE_YEARS)} years + {len(GATE_STEMS)} stems); "
                    f"PT+AL+TN+RS LIVE — do not rebuild; do NOT start VN or any other country"
                ),
                "status": "CLAIMED",
                "mode": "RECONFIRM_FINAL",
                "wave_end": False,
            })
            break
    else:
        print("WARN: AO entry not updated in wave JSON (non-fatal)")
    data["hold"] = HOLD
    data["current"] = SLUG
    data["hold_note"] = (
        "HOLD 0 STRICT for AO RECONFIRM_FINAL build in progress (after_wave2 FIFTH; PT+AL+TN+RS LIVE); "
        "do NOT start VN or any other country"
    )
    wave.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    triage = Path("/workspace/country-law-triage/next_ir_ok_wave_after_wave2.json")
    if triage.parent.is_dir():
        triage.write_text(wave.read_text(encoding="utf-8"), encoding="utf-8")
    print("updated wave JSON AO entry")
else:
    print("WARN: wave JSON missing")

print("GATE years", GATE_YEARS)
print("GATE stems", GATE_STEMS)
print("n_gate", len(GATE_YEARS) + len(GATE_STEMS))
print("HOLD", HOLD)
print("floor", f"{FLOOR_LAWS}/{FLOOR_ARTS}; RECONFIRM_FINAL; only AO")
