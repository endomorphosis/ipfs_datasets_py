#!/usr/bin/env python3
"""Adapt Tunisia memsafe pack tip d637219b87dd → tip 5ed74d548da1.

Same-country tip bump. RECONFIRM_FINAL tip_drift; floor ≥6395/84161.
Arabic/French Tunisian legal GATE from articles.parquet @ 5ed74d548da1
(decret/arrete/article/loi/republique/tunisienne/…). URL jort.tn /
legislation.tn / tunisie.gov.tn query-only, NOT GATE.

HOLD 0 STRICT after_wave2 (TN after AL LIVE); WAVE THIRD of after_wave2
(TN RECONFIRM; PT+AL LIVE — do not rebuild; then RS→…→LK — do NOT start those).
Soft never-thin ON; soft_thin=false. SKIP_US; AT queued-only; KW HOLD_THIN; IT leave alone.
Source endomorphosis/ipfs_tunisia_laws → justicedao/ipfs_tunisia_laws_ir.
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
SRC_TIP_FULL = "d637219b87ddc4d7590944ea9870387585bb6b2f"
SRC_TIP_SHORT = "d637219b87dd"
DST_TIP_FULL = "5ed74d548da1e4cab7778ac331cc8c264924acea"
DST_TIP_SHORT = "5ed74d548da1"
FLOOR_LAWS, FLOOR_ARTS = 6395, 84161
SRC_FLOOR_L, SRC_FLOOR_A = 3467, 76586

GATE_YEARS = [
    "2021", "2018", "2019", "2020", "2016",
    "2023", "2011", "2017", "2022", "2014",
]
GATE_STEMS = [
    "decret", "arrete", "article", "ministere", "loi",
    "republique", "tunisienne", "gouvernement", "officiel", "journal",
    "constitution", "code",
]
YEARS_ATTESTED = [int(y) for y in GATE_YEARS] + [
    2015, 2013, 2012, 2010, 2009, 2024, 2008, 2005, 2000, 1990, 1983,
]
GATE_NOTE_YEARS = "/".join(GATE_YEARS)
GATE_NOTE_STEMS = "/".join(GATE_STEMS)
HOLD = "HOLD 0 STRICT after_wave2 (TN after AL LIVE)"
WAVE_POS = (
    "THIRD of after_wave2 "
    "(TN RECONFIRM; PT+AL LIVE — do not rebuild; then RS→AO→VN→BO→UY→QA→ZM→AZ→LK — do NOT start those)"
)
DEST_CHAIN = "TN"
DISPLAY = "Tunisia"
SLUG = "tunisia"

FILES = [
    ("tunisia_soft_filter.py", "tunisia_soft_filter.py"),
    (f"tunisia_corpus_stream_{SRC_TIP_SHORT}.py", f"tunisia_corpus_stream_{DST_TIP_SHORT}.py"),
    (f"tunisia_encode_memsafe_{SRC_TIP_SHORT}.py", f"tunisia_encode_memsafe_{DST_TIP_SHORT}.py"),
    (f"tunisia_finish_from_emb_{SRC_TIP_SHORT}.py", f"tunisia_finish_from_emb_{DST_TIP_SHORT}.py"),
    (f"tunisia_stream_graph_parts_{SRC_TIP_SHORT}.py", f"tunisia_stream_graph_parts_{DST_TIP_SHORT}.py"),
    (f"tunisia_package_stream_{SRC_TIP_SHORT}.py", f"tunisia_package_stream_{DST_TIP_SHORT}.py"),
    ("tunisia_upload.py", "tunisia_upload.py"),
    ("tunisia_bm25_smoke.py", "tunisia_bm25_smoke.py"),
    ("tunisia_write_publish_report.py", "tunisia_write_publish_report.py"),
    (f"tunisia_orchestrator_{SRC_TIP_SHORT}.py", f"tunisia_orchestrator_{DST_TIP_SHORT}.py"),
]


def adapt(text: str, dst_name: str) -> str:
    for bad in (
        "cient-data", "prent-data", "stent-data", "cvent-data", "scent-data",
        "carent-data", "yement-data", "tunisiaent-data", "sand-data",
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

    # Tip swaps THEN protect
    text = text.replace(SRC_TIP_FULL, DST_TIP_FULL)
    text = text.replace(SRC_TIP_SHORT, DST_TIP_SHORT)
    text = text.replace(DST_TIP_FULL, "\x00TIPSHA_PROTECT\x00")
    text = text.replace(DST_TIP_SHORT, "\x00TIPSHORT_PROTECT\x00")

    # Floor 3467/76586 → 6395/84161
    text = text.replace("3467/76586", "\x00FLOOR_LA\x00")
    text = text.replace("3467 / 76586", "\x00FLOOR_LA_SP\x00")
    text = text.replace("3467, 76586", "\x00FLOOR_LA_C\x00")
    text = text.replace("FLOOR_LAWS, FLOOR_ARTS = 3467, 76586", "\x00FLOOR_ASSIGN\x00")
    text = text.replace("FLOOR_L, FLOOR_A = 3467, 76586", "\x00FLOOR_ASSIGN2\x00")
    text = text.replace('int(pack.get("n_laws") or 3467)', "\x00OR_LAWS\x00")
    text = text.replace('int(pack.get("n_articles") or 76586)', "\x00OR_ARTS\x00")
    text = text.replace("or 3467)", "\x00OR_LAWS_PAREN\x00")
    text = text.replace("or 76586)", "\x00OR_ARTS_PAREN\x00")
    text = text.replace("@ 3467/", "\x00AT_LAWS\x00")
    text = text.replace("floor 3467/", "\x00FLOOR_SLASH\x00")
    text = text.replace("(3467/", "\x00PAREN_LAWS\x00")
    text = text.replace("= 3467,", "\x00EQ_LAWS\x00")
    text = text.replace(" 76586", "\x00ARTS\x00")
    text = text.replace("76586", "\x00ARTS\x00")
    text = text.replace(" 3467", "\x00LAWS\x00")
    text = text.replace("3467", "\x00LAWS\x00")
    text = text.replace("\x00FLOOR_LA\x00", "6395/84161")
    text = text.replace("\x00FLOOR_LA_SP\x00", "6395 / 84161")
    text = text.replace("\x00FLOOR_LA_C\x00", "6395, 84161")
    text = text.replace("\x00FLOOR_ASSIGN\x00", "FLOOR_LAWS, FLOOR_ARTS = 6395, 84161")
    text = text.replace("\x00FLOOR_ASSIGN2\x00", "FLOOR_L, FLOOR_A = 6395, 84161")
    text = text.replace("\x00OR_LAWS\x00", 'int(pack.get("n_laws") or 6395)')
    text = text.replace("\x00OR_ARTS\x00", 'int(pack.get("n_articles") or 84161)')
    text = text.replace("\x00OR_LAWS_PAREN\x00", "or 6395)")
    text = text.replace("\x00OR_ARTS_PAREN\x00", "or 84161)")
    text = text.replace("\x00AT_LAWS\x00", "@ 6395/")
    text = text.replace("\x00FLOOR_SLASH\x00", "floor 6395/")
    text = text.replace("\x00PAREN_LAWS\x00", "(6395/")
    text = text.replace("\x00EQ_LAWS\x00", "= 6395,")
    text = text.replace("\x00ARTS\x00", "84161")
    text = text.replace("\x00LAWS\x00", "6395")

    reps = [
        ("\x00DESTHOLD\x00", HOLD),
        ("\x00DESTWAVE\x00", WAVE_POS),
        ("\x00DESTCHAIN\x00", DEST_CHAIN),
        ("\x00DESTMODE\x00", "RECONFIRM_FINAL"),
        ("Soft filter for EU tip", "Soft filter for Tunisia tip"),
        ("English/Arabic mix", "Arabic/French Tunisian legal corpus"),
        ("English/Arabic bodies", "Arabic/French Tunisian bodies"),
        ("gate = tunisia/muscat/sultan/decree/law/royal",
         f"gate = years {GATE_NOTE_YEARS} + stems {GATE_NOTE_STEMS}"),
        ("during EU ", "during TN "),
        ("EU FIRST", "TN RECONFIRM_FINAL"),
        ("EU tip", "Tunisia tip"),
    ]
    for a, b in reps:
        text = text.replace(a, b)

    text = text.replace("\x00BM25\x00", "BM25").replace("\x00bm25\x00", "bm25")
    text = text.replace("\x00TIPSHA_PROTECT\x00", DST_TIP_FULL)
    text = text.replace("\x00TIPSHORT_PROTECT\x00", DST_TIP_SHORT)
    text = text.replace("\x00DESTHOLD\x00", HOLD)
    text = text.replace("\x00DESTCHAIN\x00", DEST_CHAIN)
    text = text.replace("\x00DESTWAVE\x00", WAVE_POS)
    text = text.replace("\x00DESTMODE\x00", "RECONFIRM_FINAL")

    if dst_name == "tunisia_bm25_smoke.py":
        years_line = ", ".join(f'"{y}"' for y in GATE_YEARS)
        stems_line = ", ".join(f'"{s}"' for s in GATE_STEMS)
        note = (
            f"attested years {GATE_NOTE_YEARS} plus Tunisian French/Arabic ASCII stems "
            f"{GATE_NOTE_STEMS} from articles.parquet HEAD tip {DST_TIP_SHORT}; "
            f"URL jort.tn/legislation.tn/tunisie.gov.tn is query-only, not GATE."
        )
        text = f'''#!/usr/bin/env python3
"""BM25 smoke for Tunisia IR — Arabic/French Tunisian legal corpus; years + ASCII stems FTS gate.

GATE is attested ASCII years plus Tunisian French/Arabic ASCII-fold stems. URL
jort.tn / legislation.tn / tunisie.gov.tn is query-only, never GATE. Every GATE token must rank a hit.
"""
from __future__ import annotations
import json, sys
from pathlib import Path
sys.path.insert(0, "/workspace/country-laws-ir")
from country_laws_ir.query import Release

ROOT = Path("/workspace/country-laws-ir/releases/ipfs_tunisia_laws_ir")
OUT = Path("/workspace/country-laws-ir/reports/tunisia_bm25_smoke_{DST_TIP_SHORT}.json")

GATE = [
    {years_line},
    {stems_line},
]
QUERIES = GATE + [
    "www", "jort.tn", "legislation.tn", "tunisie.gov.tn", "www.legislation.tn",
    "www.jort.tn", "ministre", "portant", "tunisie", "tunis", "arretes",
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
    detail["tunisia_pass"] = ok
    detail["tunisia_gate"] = GATE
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

    if dst_name == "tunisia_write_publish_report.py":
        gate_note = (
            f"BM25 PASS on Tunisian French/Arabic GATE "
            f"(attested years {GATE_NOTE_YEARS} + stems {GATE_NOTE_STEMS}); "
            f"URL jort.tn/legislation.tn/tunisie.gov.tn is query-only, not GATE"
        )
        text = re.sub(r'"BM25 PASS on [^"]*"', f'"{gate_note}"', text, count=1)
        text = re.sub(
            r"collectors HOLD 0 during [^\"\n]*",
            f"{HOLD}; collectors kept dead (pkill); soft never-thin ON; SKIP_US; Italy leave alone; {WAVE_POS}",
            text,
        )
        text = re.sub(r"[ \t]{2,}", " ", text)

    if dst_name == "tunisia_soft_filter.py":
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
            r'"""Tunisia.*?"""',
            f'"""Tunisia RECONFIRM_FINAL orchestrator tip {DST_TIP_SHORT} (memsafe corpus+encode; {HOLD})."""',
            text,
            count=1,
            flags=re.S,
        )
        # Tighten soft_filter done-check to data/laws + pack_meta
        text = text.replace(
            f'(CACHE / f"tunisia_filtered_{{TIP_SHORT}}" / "laws.parquet").is_file() '
            f'or (CACHE / f"tunisia_filtered_{{TIP_SHORT}}").is_dir()',
            f'(CACHE / f"tunisia_filtered_{{TIP_SHORT}}" / "data" / "laws.parquet").is_file() '
            f'and (CACHE / f"tunisia_filtered_{{TIP_SHORT}}" / "pack_meta.json").is_file()',
        )
        # fallback if already tip-substituted form without braces
        text = text.replace(
            f'(CACHE / f"tunisia_filtered_{DST_TIP_SHORT}" / "laws.parquet").is_file() '
            f'or (CACHE / f"tunisia_filtered_{DST_TIP_SHORT}").is_dir()',
            f'(CACHE / f"tunisia_filtered_{DST_TIP_SHORT}" / "data" / "laws.parquet").is_file() '
            f'and (CACHE / f"tunisia_filtered_{DST_TIP_SHORT}" / "pack_meta.json").is_file()',
        )

    if dst_name.endswith("_bm25_smoke.py"):
        gate_slice = text[text.index("GATE = ["): text.index("]", text.index("GATE = [")) + 1]
        for bad in ("muscat", "sultan", "royal", "qatar", "ghana", "iceland", "emir"):
            if f'"{bad}"' in gate_slice:
                raise RuntimeError(f"non-TN token in GATE of {dst_name}: {bad}")
        for stem in GATE_STEMS:
            if f'"{stem}"' not in gate_slice:
                raise RuntimeError(f"missing Tunisian stem in GATE of {dst_name}: {stem}")
        for year in GATE_YEARS:
            if f'"{year}"' not in gate_slice:
                raise RuntimeError(f"missing year in GATE of {dst_name}: {year}")

    if SRC_TIP_SHORT in text:
        raise RuntimeError(f"src tip leftover in {dst_name}")
    if SRC_TIP_FULL in text:
        raise RuntimeError(f"src tip full leftover in {dst_name}")
    if "3467" in text or "76586" in text:
        raise RuntimeError(f"old floor leftover in {dst_name}")
    if DST_TIP_SHORT not in text and any(
        x in dst_name for x in ("soft_filter", "orchestrator", "bm25_smoke", "upload", "write_publish")
    ):
        raise RuntimeError(f"missing DST tip in {dst_name}")
    if "\x00" in text:
        raise RuntimeError(f"null placeholder leftover in {dst_name}")
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
    raw = src.read_text(encoding="utf-8")
    (ROOT / dst_name).write_text(adapt(raw, dst_name), encoding="utf-8")
    print(f"wrote {dst_name}")

# Update wave JSON TN entry (do not touch PT/AL LIVE)
wave = Path("/workspace/next_ir_ok_wave_after_wave2.json")
if wave.is_file():
    data = json.loads(wave.read_text(encoding="utf-8"))
    for entry in data.get("queue", []):
        if not isinstance(entry, dict):
            continue
        if entry.get("slug") == SLUG or entry.get("iso2") == "TN":
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
                "ir_hub_head": "3e09e2f18434",
                "label": "EXPAND",
                "soft_thin": False,
                "soft_never_thin": True,
                "skip_us": True,
                "italy_leave_alone": True,
                "language": "Arabic/French",
                "lang": "ar/fr",
                "iso2": "TN",
                "slug": SLUG,
                "repo": "endomorphosis/ipfs_tunisia_laws",
                "years_attested": YEARS_ATTESTED,
                "gate_years": [int(y) for y in GATE_YEARS],
                "gate_stems": GATE_STEMS,
                "note": (
                    f"TN RECONFIRM_FINAL scaffold; tip MATCH {DST_TIP_SHORT}@6395/84161; {HOLD}; "
                    f"soft never-thin ON; SKIP_US; Italy leave alone; {WAVE_POS}; "
                    f"Tunisian GATE ({len(GATE_YEARS)} years + {len(GATE_STEMS)} stems); "
                    f"PT+AL LIVE — do not rebuild; do NOT start RS or any other country"
                ),
                "status": "CLAIMED",
                "mode": "RECONFIRM_FINAL",
                "wave_end": False,
            })
            break
    else:
        print("WARN: TN entry shape not updated in wave JSON (non-fatal)")
    data["hold"] = HOLD
    data["current"] = SLUG
    data["hold_note"] = (
        "HOLD 0 STRICT for TN RECONFIRM_FINAL build in progress (after_wave2 THIRD; PT+AL LIVE); "
        "do NOT start RS or any other country"
    )
    wave.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    triage = Path("/workspace/country-law-triage/next_ir_ok_wave_after_wave2.json")
    if triage.parent.is_dir():
        triage.write_text(wave.read_text(encoding="utf-8"), encoding="utf-8")
    print("updated wave JSON TN entry")
else:
    print("WARN: wave JSON missing")

print("GATE years", GATE_YEARS)
print("GATE stems", GATE_STEMS)
print("n_gate", len(GATE_YEARS) + len(GATE_STEMS))
print("HOLD", HOLD)
print("floor", f"{FLOOR_LAWS}/{FLOOR_ARTS}; RECONFIRM_FINAL; only TN")
