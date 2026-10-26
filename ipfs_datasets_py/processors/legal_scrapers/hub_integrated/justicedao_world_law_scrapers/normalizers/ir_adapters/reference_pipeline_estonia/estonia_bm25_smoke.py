#!/usr/bin/env python3
"""BM25 smoke for Estonia IR — Estonian legal corpus (Latin script); ASCII-after-diacritic-fold.

Tokenizer ([0-9A-Za-z]+) folds diacritics so paragrahvi/seaduse/määruse → paragrahvi/seaduse/maaruse.
GATE = attested years + roman numerals + Estonian Latin legal stems sampled from
articles.parquet HEAD tip 902b122cd27e (prefer years + attested Latin; Estonian-only may empty FTS
if diacritic fold fails; avoid URL-only www/gov; English law/article/shall query-only not GATE).
Pattern like FI: years + any Latin legal stems present.
"""
from __future__ import annotations
# Harvested collector path injection. Do not collect from /workspace.
import os as _ipfs_os
from pathlib import Path as _ipfs_Path
_CORPORA = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_CORPORA_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_corpora")))
_SCRAPERS = _ipfs_Path(_ipfs_os.environ.get("IPFS_DATASETS_LEGAL_COLLECTORS_ROOT", str(_ipfs_Path.home() / ".ipfs_datasets" / "legal_collectors"))) / "shared"
_HF_TOKEN_PATH = _ipfs_Path(_ipfs_os.environ.get("HF_TOKEN_PATH", str(_ipfs_Path.home() / ".cache" / "huggingface" / "token")))
import json, sys
from pathlib import Path
sys.path.insert(0, "/workspace/country-laws-ir")
from country_laws_ir.query import Release

ROOT = Path("/workspace/country-laws-ir/releases/ipfs_estonia_laws_ir")
OUT = Path("/workspace/country-laws-ir/reports/estonia_bm25_smoke_902b122cd27e.json")

# Attested ASCII/year/roman tokens from articles.parquet @ 902b122cd27e (sample 8000 rows)
QUERIES = [
    # Years (high attestation)
    "2014",
    "2015",
    "2016",
    "2017",
    "2018",
    "2019",
    "2020",
    "2021",
    "2022",
    "2023",
    "2024",
    "2025",
    # Roman chapter markers attested as tokens
    "ii",
    "iii",
    "iv",
    # Estonian Latin legal stems (ASCII after diacritic fold)
    "seadus",
    "seaduse",
    "paragrahv",
    "paragrahvi",
    "loike",
    "loige",
    "peatukk",
    "maarus",
    "maaruse",
    "eesti",
    "oigus",
    "riigi",
    "riigikogu",
    "kohus",
    "valitsus",
    "otsus",
    "otsuse",
    "minister",
    "artikli",
    "punkti",
    "joustumine",
    # URL-ish / English (informational; not GATE)
    "www",
    "gov",
    "ee",
    "law",
    "article",
    "shall",
]

GATE = [
    "2014",
    "2017",
    "2018",
    "2020",
    "2022",
    "2023",
    "2025",
    "ii",
    "iii",
    "seadus",
    "seaduse",
    "paragrahvi",
    "loike",
    "peatukk",
    "maaruse",
    "eesti",
    "oigus",
    "riigi",
    "kohus",
    "otsuse",
]


def main() -> int:
    rel = Release(ROOT)
    detail = {
        "queries": {},
        "ranked": [],
        "empty": [],
        "pass": False,
    }
    for q in QUERIES:
        hits = rel.bm25(q, top_k=5)
        top = [
            {
                "score": h.get("score"),
                "title": (h.get("title") or "")[:120],
                "instrument_id": h.get("instrument_id"),
                "record_type": h.get("record_type"),
                "instrument_title": (h.get("instrument_title") or "")[:80],
            }
            for h in hits[:3]
        ]
        detail["queries"][q] = {"n": len(hits), "top": top}
        if hits:
            detail["ranked"].append(q)
        else:
            detail["empty"].append(q)
    ok = all(q in detail["ranked"] for q in GATE)
    detail["pass"] = ok
    detail["tokenizer_note"] = (
        "ASCII-after-diacritic-fold tokenizer ([0-9A-Za-z]+); "
        "GATE = attested years 2014/2017/2018/2020/2022/2023/2025 + roman ii/iii + Estonian Latin "
        "(seadus/seaduse/paragrahvi/loike/peatukk/maaruse/eesti/oigus/riigi/kohus/otsuse) "
        "from articles.parquet HEAD tip 902b122cd27e (lang=et; Latin script); "
        "URL-only www/gov/ee and empty English law/article/shall query-only not GATE; "
        "Estonian-only may empty FTS if fold fails — prefer years + attested Latin (FI pattern)"
    )
    detail["estonia_pass"] = ok
    detail["estonia_gate"] = GATE
    detail["hub_commit_expected"] = None
    detail["tip"] = "902b122cd27e"
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(detail, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "pass": detail["pass"],
                "ranked": detail["ranked"],
                "empty": detail["empty"],
                "n_gate_ranked": sum(1 for q in GATE if q in detail["ranked"]),
                "n_gate": len(GATE),
                "gate": GATE,
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
