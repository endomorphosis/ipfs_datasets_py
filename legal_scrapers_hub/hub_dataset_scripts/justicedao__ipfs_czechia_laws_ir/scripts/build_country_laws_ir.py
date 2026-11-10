#!/usr/bin/env python3
"""CLI: build a country-laws IR release (local; does not upload)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from country_laws_ir.build import build_country  # noqa: E402
from country_laws_ir.catalog import target_repo  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--source-repo", "--source", dest="source", default="endomorphosis/ipfs_malta_laws",
                    help="Hub dataset id or country slug (default: Malta pilot)")
    ap.add_argument("--out", default=None, help="Release output directory")
    ap.add_argument("--device", default="cpu")
    ap.add_argument("--neighbor-k", type=int, default=8)
    ap.add_argument("--skip-vectors", action="store_true")
    ap.add_argument("--upload", action="store_true", help="Opt-in Hub upload (default: off)")
    args = ap.parse_args()
    result = build_country(
        args.source,
        out=Path(args.out) if args.out else None,
        upload=bool(args.upload),
        device=args.device,
        neighbor_k=args.neighbor_k,
        skip_vectors=args.skip_vectors,
    )
    print(json.dumps({
        "out": result["out"],
        "target_hub_id": result.get("target_hub_id") or target_repo(result["country"]),
        "counts": result["counts"],
        "normalization": {
            "n_laws_in": result["normalization"]["n_laws_in"],
            "n_articles_in": result["normalization"]["n_articles_in"],
            "n_out": result["normalization"]["n_out"],
            "unit": result["normalization"]["unit"],
            "drops": result["normalization"]["drops"],
        },
        "vector_blocker": result.get("vector_blocker"),
        "schema_version": result.get("schema_version"),
    }, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
