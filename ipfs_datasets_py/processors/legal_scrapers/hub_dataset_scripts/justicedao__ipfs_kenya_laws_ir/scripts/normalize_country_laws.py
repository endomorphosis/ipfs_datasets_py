#!/usr/bin/env python3
"""Normalize a country-law source into a CID-keyed corpus report (no GraphRAG, no upload)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from country_laws_ir.build import CACHE, REPORTS  # noqa: E402
from country_laws_ir.catalog import get_country  # noqa: E402
from country_laws_ir.normalize import build_corpus, load_source  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--source-repo", "--source", dest="source", default="endomorphosis/ipfs_malta_laws")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    country = get_country(args.source)
    laws, articles, source_meta = load_source(country["repo"], CACHE)
    corpus, report = build_corpus(laws, articles, source_meta)
    out = Path(args.out) if args.out else REPORTS / f"{country['slug']}_normalization.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({
        "out": str(out),
        "n_out": int(len(corpus)),
        "unit": report["unit"],
        "drops": report["drops"],
        "language_breakdown": report.get("language_breakdown"),
        "quality_flags": report.get("quality_flags"),
        "schema_surprises": report.get("schema_surprises"),
    }, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
