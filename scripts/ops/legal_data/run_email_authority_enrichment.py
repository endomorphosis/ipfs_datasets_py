#!/usr/bin/env python3
"""Run email timeline authority enrichment with optional catalog overrides."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from ipfs_datasets_py.processors.legal_data import enrich_email_timeline_authorities


def _parse_args(args: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Enrich an email timeline handoff with legal authority queries and seed citations."
    )
    parser.add_argument(
        "--prefer-hacc-venv",
        action="store_true",
        help="Rerun with /home/barberb/HACC/.venv when available.",
    )
    parser.add_argument(
        "--input",
        required=True,
        help="Path to email_timeline_handoff.json.",
    )
    parser.add_argument(
        "--output-dir",
        default="",
        help="Directory where email_authority_enrichment.{json,md} should be written.",
    )
    parser.add_argument(
        "--jurisdiction",
        default="or",
        help="Jurisdiction code passed to legal-authority search (default: or).",
    )
    parser.add_argument(
        "--jurisdiction-label",
        default="Oregon",
        help="Human-readable jurisdiction label for query planning (default: Oregon).",
    )
    parser.add_argument(
        "--max-queries",
        type=int,
        default=8,
        help="Maximum number of live authority queries (default: 8).",
    )
    parser.add_argument(
        "--no-state-archives",
        action="store_true",
        help="Disable supplemental state web archive lookups.",
    )
    parser.add_argument(
        "--catalog-path",
        default="",
        help="Optional JSON catalog override path for topic hints and seed authorities.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON output.",
    )
    return parser.parse_args(args)


def main(args: list[str] | None = None) -> int:
    parsed = _parse_args(args)
    if parsed.prefer_hacc_venv:
        import os
        import sys

        target = "/home/barberb/HACC/.venv/bin/python"
        if sys.executable != target and os.path.exists(target):
            os.execv(target, [target, *sys.argv[1:]])

    try:
        payload = enrich_email_timeline_authorities(
            parsed.input,
            output_dir=(str(parsed.output_dir).strip() or None),
            jurisdiction=str(parsed.jurisdiction or "or"),
            jurisdiction_label=str(parsed.jurisdiction_label or "Oregon"),
            max_queries=max(1, int(parsed.max_queries or 8)),
            search_state_archives=not bool(parsed.no_state_archives),
            catalog_path=(str(parsed.catalog_path).strip() or None),
        )
    except Exception as exc:
        payload = {
            "status": "error",
            "error": str(exc),
            "input": str(parsed.input or ""),
            "catalog_path": str(parsed.catalog_path or ""),
        }
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 1

    if parsed.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        print(f"Status: {payload.get('status')}")
        print(f"Input: {payload.get('email_timeline_handoff_path')}")
        print(f"Claim type: {payload.get('claim_type')}")
        print(f"Claim element: {payload.get('claim_element_id')}")
        print(f"Catalog path: {payload.get('catalog_path') or '(default)'}")
        print(f"Query count: {((payload.get('summary') or {}).get('query_count'))}")
        print(f"Queries with hits: {((payload.get('summary') or {}).get('queries_with_hits'))}")
        print(f"Seed authority count: {((payload.get('summary') or {}).get('seed_authority_count'))}")
        print(f"JSON output: {payload.get('output_path')}")
        print(f"Markdown output: {payload.get('markdown_output_path')}")
    return 0 if payload.get("status") == "success" else 1


if __name__ == "__main__":
    raise SystemExit(main())
