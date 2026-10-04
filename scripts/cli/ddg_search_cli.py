#!/usr/bin/env python3
"""Minimal DuckDuckGo search CLI for ipfs_datasets_py.

This script uses the ``ddgs`` library directly because DuckDuckGo does not
require an API key and it is already available in the working project venv.

Usage examples:
    /home/barberb/HACC/complaint-generator/.venv/bin/python scripts/cli/ddg_search_cli.py \
        "Housing Authority of Clackamas County Hillside Manor Quantum Residential"

    /home/barberb/HACC/complaint-generator/.venv/bin/python scripts/cli/ddg_search_cli.py \
        "site:clackamas.us Blossom Community Apartments PBV waitlist" --max-results 5 --json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run a DuckDuckGo search from the ipfs_datasets_py project."
    )
    parser.add_argument("query", help="Search query")
    parser.add_argument(
        "--max-results",
        type=int,
        default=5,
        help="Maximum number of results to return (default: 5)",
    )
    parser.add_argument(
        "--region",
        default="us-en",
        help="DuckDuckGo region code (default: us-en)",
    )
    parser.add_argument(
        "--safesearch",
        default="moderate",
        choices=["on", "moderate", "off"],
        help="Safesearch mode (default: moderate)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print raw JSON results",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    try:
        from ddgs import DDGS
    except Exception as exc:
        print(
            "DuckDuckGo support is unavailable in this Python environment. "
            "Use the complaint-generator venv or install ddgs.",
            file=sys.stderr,
        )
        print(f"Import error: {exc}", file=sys.stderr)
        return 1

    try:
        with DDGS() as ddgs:
            results = list(
                ddgs.text(
                    args.query,
                    region=args.region,
                    safesearch=args.safesearch,
                    max_results=args.max_results,
                )
            )
    except Exception as exc:
        print(f"DuckDuckGo search failed: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(results, indent=2))
        return 0

    print(f"Query: {args.query}")
    print(f"Results: {len(results)}")
    print()
    for index, result in enumerate(results, 1):
        title = result.get("title", "").strip() or "(no title)"
        href = result.get("href", "").strip() or "(no url)"
        body = result.get("body", "").strip()
        print(f"{index}. {title}")
        print(f"   {href}")
        if body:
            print(f"   {body}")
        print()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
