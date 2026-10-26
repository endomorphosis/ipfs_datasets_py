#!/usr/bin/env python3
"""Adapt Vietnam memsafe pack tip 8e802a9acaee → tip 5088d10cf67c.

Same-country tip bump. RECONFIRM_FINAL tip_drift; floor ≥700/41042.
Vietnamese GATE from articles.parquet @ 5088d10cf67c (luat/khoan/quyet/…).
URL congbao.chinhphu.vn / vbpl.vn query-only, NOT GATE.

HOLD 0 STRICT continuous after_wave2 (VN after AO LIVE); WAVE SIXTH of after_wave2
(VN RECONFIRM; PT+AL+TN+RS+AO LIVE — do not rebuild; then BO→…→LK — do NOT start those).
Soft never-thin ON; soft_thin=false. SKIP_US; AT queued-only; KW HOLD_THIN; IT leave alone.
Source endomorphosis/ipfs_vietnam_laws → justicedao/ipfs_vietnam_laws_ir.
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
SRC_TIP_FULL = "8e802a9acaeec6ab78e887a64e56540a3bba6088"
SRC_TIP_SHORT = "8e802a9acaee"
DST_TIP_FULL = "5088d10cf67c8db7ebb77bfc0e46615422512fd2"
DST_TIP_SHORT = "5088d10cf67c"
FLOOR_LAWS, FLOOR_ARTS = 700, 41042
SRC_FLOOR_L, SRC_FLOOR_A = 700, 29215

GATE_YEARS = [
    "2024", "2015", "2014", "2025", "2012",
    "2013", "2010", "2020", "2022", "2018",
]
GATE_STEMS = [
    "luat", "khoan", "quyet", "chinh", "thong",
    "quoc", "phap", "hien", "nghi", "viet",
    "nam", "toan",
]
YEARS_ATTESTED = [int(y) for y in GATE_YEARS] + [
    2026, 2017, 2016, 2011, 2009, 2008, 2021, 2023, 2019, 2005,
]
GATE_NOTE_YEARS = "/".join(GATE_YEARS)
GATE_NOTE_STEMS = "/".join(GATE_STEMS)
HOLD = "HOLD 0 STRICT continuous after_wave2 (VN after AO LIVE)"
WAVE_POS = (
    "SIXTH of after_wave2 "
    "(VN RECONFIRM; PT+AL+TN+RS+AO LIVE — do not rebuild; then BO→UY→QA→ZM→AZ→LK — do NOT start those)"
)
DEST_CHAIN = "VN"
SLUG = "vietnam"

FILES = [
    ("vietnam_soft_filter.py", "vietnam_soft_filter.py"),
    (f"vietnam_corpus_stream_{SRC_TIP_SHORT}.py", f"vietnam_corpus_stream_{DST_TIP_SHORT}.py"),
    (f"vietnam_encode_memsafe_{SRC_TIP_SHORT}.py", f"vietnam_encode_memsafe_{DST_TIP_SHORT}.py"),
    (f"vietnam_finish_from_emb_{SRC_TIP_SHORT}.py", f"vietnam_finish_from_emb_{DST_TIP_SHORT}.py"),
    (f"vietnam_stream_graph_parts_{SRC_TIP_SHORT}.py", f"vietnam_stream_graph_parts_{DST_TIP_SHORT}.py"),
    (f"vietnam_package_stream_{SRC_TIP_SHORT}.py", f"vietnam_package_stream_{DST_TIP_SHORT}.py"),
    ("vietnam_upload.py", "vietnam_upload.py"),
    ("vietnam_bm25_smoke.py", "vietnam_bm25_smoke.py"),
    ("vietnam_write_publish_report.py", "vietnam_write_publish_report.py"),
    (f"vietnam_orchestrator_{SRC_TIP_SHORT}.py", f"vietnam_orchestrator_{DST_TIP_SHORT}.py"),
]


def adapt(text: str, dst_name: str) -> str:
    for bad in (
        "cient-data", "prent-data", "stent-data", "cvent-data", "scent-data",
        "carent-data", "yement-data", "vietnament-data", "sand-data",
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

    # Floor 700/29215 → 700/41042 (laws stay 700; protect tip then swap arts)
    text = text.replace("700/29215", "\x00FLOOR_LA\x00")
    text = text.replace("700 / 29215", "\x00FLOOR_LA_SP\x00")
    text = text.replace("700, 29215", "\x00FLOOR_LA_C\x00")
    text = text.replace("FLOOR_LAWS, FLOOR_ARTS = 700, 29215", "\x00FLOOR_ASSIGN\x00")
    text = text.replace("FLOOR_L, FLOOR_A = 700, 29215", "\x00FLOOR_ASSIGN2\x00")
    text = text.replace('int(pack.get("n_laws") or 700)', "\x00OR_LAWS\x00")
    text = text.replace('int(pack.get("n_articles") or 29215)', "\x00OR_ARTS\x00")
    text = text.replace("or 29215)", "\x00OR_ARTS_PAREN\x00")
    text = text.replace("or 700)", "\x00OR_LAWS_PAREN\x00")
    text = text.replace("@ 700/", "\x00AT_LAWS\x00")
    text = text.replace("floor 700/", "\x00FLOOR_SLASH\x00")
    text = text.replace("(700/", "\x00PAREN_LAWS\x00")
    text = text.replace("= 700,", "\x00EQ_LAWS\x00")
    text = text.replace(" 29215", "\x00ARTS\x00")
    text = text.replace("29215", "\x00ARTS\x00")
    # laws 700 — only after arts protected; tip already protected
    text = text.replace("FLOOR_LAWS, FLOOR_ARTS = 700,", "\x00FLOOR_ASSIGN_HEAD\x00")
    text = text.replace("\x00FLOOR_LA\x00", "700/41042")
    text = text.replace("\x00FLOOR_LA_SP\x00", "700 / 41042")
    text = text.replace("\x00FLOOR_LA_C\x00", "700, 41042")
    text = text.replace("\x00FLOOR_ASSIGN\x00", "FLOOR_LAWS, FLOOR_ARTS = 700, 41042")
    text = text.replace("\x00FLOOR_ASSIGN2\x00", "FLOOR_L, FLOOR_A = 700, 41042")
    text = text.replace("\x00FLOOR_ASSIGN_HEAD\x00", "FLOOR_LAWS, FLOOR_ARTS = 700,")
    text = text.replace("\x00OR_LAWS\x00", 'int(pack.get("n_laws") or 700)')
    text = text.replace("\x00OR_ARTS\x00", 'int(pack.get("n_articles") or 41042)')
    text = text.replace("\x00OR_ARTS_PAREN\x00", "or 41042)")
    text = text.replace("\x00OR_LAWS_PAREN\x00", "or 700)")
    text = text.replace("\x00AT_LAWS\x00", "@ 700/")
    text = text.replace("\x00FLOOR_SLASH\x00", "floor 700/")
    text = text.replace("\x00PAREN_LAWS\x00", "(700/")
    text = text.replace("\x00EQ_LAWS\x00", "= 700,")
    text = text.replace("\x00ARTS\x00", "41042")

    for a, b in [
        ("\x00DESTHOLD\x00", HOLD),
        ("\x00DESTWAVE\x00", WAVE_POS),
        ("\x00DESTCHAIN\x00", DEST_CHAIN),
        ("\x00DESTMODE\x00", "RECONFIRM_FINAL"),
        ("Soft filter for EU tip", "Soft filter for Vietnam tip"),
        ("during EU ", "during VN "),
        ("EU FIRST", "VN RECONFIRM_FINAL"),
        ("EU tip", "Vietnam tip"),
    ]:
        text = text.replace(a, b)

    text = text.replace("\x00BM25\x00", "BM25").replace("\x00bm25\x00", "bm25")
    text = text.replace("\x00TIPSHA_PROTECT\x00", DST_TIP_FULL)
    text = text.replace("\x00TIPSHORT_PROTECT\x00", DST_TIP_SHORT)
    text = text.replace("\x00DESTHOLD\x00", HOLD)
    text = text.replace("\x00DESTCHAIN\x00", DEST_CHAIN)
    text = text.replace("\x00DESTWAVE\x00", WAVE_POS)
    text = text.replace("\x00DESTMODE\x00", "RECONFIRM_FINAL")

    if dst_name == "vietnam_bm25_smoke.py":
        years_line = ", ".join(f'"{y}"' for y in GATE_YEARS)
        stems_line = ", ".join(f'"{s}"' for s in GATE_STEMS)
        note = (
            f"attested years {GATE_NOTE_YEARS} plus Vietnamese ASCII stems {GATE_NOTE_STEMS} "
            f"from articles.parquet HEAD tip {DST_TIP_SHORT}; URL congbao.chinhphu.vn/vbpl.vn "
            f"is query-only, not GATE."
        )
        text = f'''#!/usr/bin/env python3
"""BM25 smoke for Vietnam IR — Vietnamese legal corpus; years + ASCII stems FTS gate.

GATE is attested ASCII years plus Vietnamese ASCII-fold stems. URL
congbao.chinhphu.vn / vbpl.vn is query-only, never GATE. Every GATE token must rank a hit.
"""
from __future__ import annotations
import json, sys
from pathlib import Path
sys.path.insert(0, "/workspace/country-laws-ir")
from country_laws_ir.query import Release

ROOT = Path("/workspace/country-laws-ir/releases/ipfs_vietnam_laws_ir")
OUT = Path("/workspace/country-laws-ir/reports/vietnam_bm25_smoke_{DST_TIP_SHORT}.json")

GATE = [
    {years_line},
    {stems_line},
]
QUERIES = GATE + [
    "www", "congbao.chinhphu.vn", "vbpl.vn", "chinhphu.vn", "www.vbpl.vn",
    "dieu", "bo", "uy", "ban", "toaan", "xahoi",
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
    detail["vietnam_pass"] = ok
    detail["vietnam_gate"] = GATE
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

    if dst_name == "vietnam_write_publish_report.py":
        gate_note = (
            f"BM25 PASS on Vietnamese GATE "
            f"(attested years {GATE_NOTE_YEARS} + stems {GATE_NOTE_STEMS}); "
            f"URL congbao.chinhphu.vn/vbpl.vn is query-only, not GATE"
        )
        text = re.sub(r'"BM25 PASS on [^"]*"', f'"{gate_note}"', text, count=1)
        text = re.sub(
            r"collectors HOLD 0 during [^\"\n]*",
            f"{HOLD}; collectors kept dead (pkill); soft never-thin ON; SKIP_US; Italy leave alone; {WAVE_POS}",
            text,
        )
        text = re.sub(r"[ \t]{2,}", " ", text)

    if dst_name == "vietnam_soft_filter.py":
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
            r'"""Vietnam.*?"""',
            f'"""Vietnam RECONFIRM_FINAL orchestrator tip {DST_TIP_SHORT} (memsafe corpus+encode; {HOLD})."""',
            text,
            count=1,
            flags=re.S,
        )
        text = text.replace(
            f'(CACHE / f"vietnam_filtered_{{TIP_SHORT}}" / "laws.parquet").is_file() '
            f'or (CACHE / f"vietnam_filtered_{{TIP_SHORT}}").is_dir()',
            f'(CACHE / f"vietnam_filtered_{{TIP_SHORT}}" / "data" / "laws.parquet").is_file() '
            f'and (CACHE / f"vietnam_filtered_{{TIP_SHORT}}" / "pack_meta.json").is_file()',
        )
        text = text.replace(
            f'(CACHE / f"vietnam_filtered_{DST_TIP_SHORT}" / "laws.parquet").is_file() '
            f'or (CACHE / f"vietnam_filtered_{DST_TIP_SHORT}").is_dir()',
            f'(CACHE / f"vietnam_filtered_{DST_TIP_SHORT}" / "data" / "laws.parquet").is_file() '
            f'and (CACHE / f"vietnam_filtered_{DST_TIP_SHORT}" / "pack_meta.json").is_file()',
        )

    if dst_name.endswith("_bm25_smoke.py"):
        gate_slice = text[text.index("GATE = ["): text.index("]", text.index("GATE = [")) + 1]
        for bad in ("law", "article", "gov", "https", "iso", "qatar", "emir", "shall", "angola", "serbia"):
            if f'"{bad}"' in gate_slice:
                raise RuntimeError(f"non-VN token in GATE of {dst_name}: {bad}")
        for stem in GATE_STEMS:
            if f'"{stem}"' not in gate_slice:
                raise RuntimeError(f"missing Vietnamese stem in GATE of {dst_name}: {stem}")
        for year in GATE_YEARS:
            if f'"{year}"' not in gate_slice:
                raise RuntimeError(f"missing year in GATE of {dst_name}: {year}")

    if SRC_TIP_SHORT in text:
        raise RuntimeError(f"src tip leftover in {dst_name}")
    if SRC_TIP_FULL in text:
        raise RuntimeError(f"src tip full leftover in {dst_name}")
    if "29215" in text:
        raise RuntimeError(f"old arts floor leftover in {dst_name}")
    if DST_TIP_SHORT not in text and any(
        x in dst_name for x in ("soft_filter", "orchestrator", "bm25_smoke", "upload", "write_publish")
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
        if isinstance(entry, dict) and (entry.get("slug") == SLUG or entry.get("iso2") == "VN"):
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
                "ir_hub_head": "0d16f9356d1f",
                "label": "EXPAND",
                "soft_thin": False,
                "soft_never_thin": True,
                "skip_us": True,
                "italy_leave_alone": True,
                "language": "Vietnamese",
                "lang": "vi",
                "iso2": "VN",
                "slug": SLUG,
                "repo": "endomorphosis/ipfs_vietnam_laws",
                "years_attested": YEARS_ATTESTED,
                "gate_years": [int(y) for y in GATE_YEARS],
                "gate_stems": GATE_STEMS,
                "note": (
                    f"VN RECONFIRM_FINAL scaffold; tip MATCH {DST_TIP_SHORT}@700/41042; {HOLD}; "
                    f"soft never-thin ON; SKIP_US; Italy leave alone; {WAVE_POS}; "
                    f"Vietnamese GATE ({len(GATE_YEARS)} years + {len(GATE_STEMS)} stems); "
                    f"PT+AL+TN+RS+AO LIVE — do not rebuild; do NOT start BO or any other country"
                ),
                "status": "CLAIMED",
                "mode": "RECONFIRM_FINAL",
                "wave_end": False,
            })
            break
    else:
        print("WARN: VN entry not updated in wave JSON (non-fatal)")
    data["hold"] = HOLD
    data["current"] = SLUG
    data["hold_note"] = (
        "HOLD 0 STRICT continuous for VN RECONFIRM_FINAL build (after_wave2 SIXTH; PT+AL+TN+RS+AO LIVE); "
        "do NOT start BO; no soft-lean refill until WAVE END after LK"
    )
    wave.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    triage = Path("/workspace/country-law-triage/next_ir_ok_wave_after_wave2.json")
    if triage.parent.is_dir():
        triage.write_text(wave.read_text(encoding="utf-8"), encoding="utf-8")
    print("updated wave JSON VN entry")
else:
    print("WARN: wave JSON missing")

print("GATE years", GATE_YEARS)
print("GATE stems", GATE_STEMS)
print("n_gate", len(GATE_YEARS) + len(GATE_STEMS))
print("HOLD", HOLD)
print("floor", f"{FLOOR_LAWS}/{FLOOR_ARTS}; RECONFIRM_FINAL; only VN")
