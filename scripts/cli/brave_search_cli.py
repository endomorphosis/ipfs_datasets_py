#!/usr/bin/env python3
"""Minimal Brave search CLI for ipfs_datasets_py.

This wrapper uses the repo's in-tree Brave search implementation and reads the
API key from ``BRAVE_API_KEY`` unless one is passed explicitly.

Usage examples:
    BRAVE_API_KEY=your_key \
    /home/barberb/HACC/complaint-generator/.venv/bin/python scripts/cli/brave_search_cli.py \
        "Housing Authority of Clackamas County Hillside Manor Quantum Residential"

    /home/barberb/HACC/complaint-generator/.venv/bin/python scripts/cli/brave_search_cli.py \
        "Section 18 HUD relocation comparable housing" --count 5 --json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from brave_search import search_brave  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run a Brave web search from the ipfs_datasets_py project."
    )
    parser.add_argument("query", help="Search query")
    parser.add_argument("--count", type=int, default=5, help="Number of results (default: 5)")
    parser.add_argument("--offset", type=int, default=0, help="Result offset (default: 0)")
    parser.add_argument("--country", default="US", help="Country code (default: US)")
    parser.add_argument("--lang", default="en", help="Language code (default: en)")
    parser.add_argument(
        "--safesearch",
        default="moderate",
        choices=["off", "moderate", "strict"],
        help="Safesearch mode (default: moderate)",
    )
    parser.add_argument(
        "--freshness",
        choices=["pd", "pw", "pm", "py"],
        help="Optional freshness filter",
    )
    parser.add_argument("--api-key", help="Brave API key; otherwise uses BRAVE_API_KEY")
    parser.add_argument("--json", action="store_true", help="Print raw JSON output")
    return parser


async def _run(args: argparse.Namespace) -> dict:
    return await search_brave(
        query=args.query,
        api_key=args.api_key or os.environ.get("BRAVE_API_KEY"),
        count=args.count,
        offset=args.offset,
        country=args.country,
        search_lang=args.lang,
        safesearch=args.safesearch,
        freshness=args.freshness,
    )


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    result = asyncio.run(_run(args))

    if args.json:
        print(json.dumps(result, indent=2))
        return 0 if result.get("status") == "success" else 2

    if result.get("status") != "success":
        print(f"Brave search failed: {result.get('error', 'unknown error')}", file=sys.stderr)
        if not (args.api_key or os.environ.get("BRAVE_API_KEY")):
            print("Set BRAVE_API_KEY or pass --api-key.", file=sys.stderr)
        return 2

    results = result.get("results", [])
    print(f"Query: {args.query}")
    print(f"Results: {len(results)}")
    print()
    for index, item in enumerate(results, 1):
        title = item.get("title", "").strip() or "(no title)"
        url = item.get("url", "").strip() or "(no url)"
        description = item.get("description", "").strip()
        print(f"{index}. {title}")
        print(f"   {url}")
        if description:
            print(f"   {description}")
        print()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
