"""CLI for harvesting collectors and running the unified legal scrape API."""

from __future__ import annotations

import argparse
import json
from typing import Any

from .api import harvest_legal_collectors, list_legal_sources, scrape_legal_data, snapshot_catalog_summary
from .catalog import get_snapshot_corpus


def _print(payload: Any) -> None:
    print(json.dumps(payload, indent=2, default=str))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Unified legal scrape / harvest CLI. Not legal advice.")
    sub = parser.add_subparsers(dest="command", required=True)

    catalog = sub.add_parser("catalog", help="Summarize parked Hugging Face gazette snapshots")
    catalog.add_argument("--jurisdiction", help="Show one snapshot corpus")

    sources = sub.add_parser("sources", help="List native and harvested legal sources")
    sources.add_argument("--native-only", action="store_true")

    harvest = sub.add_parser("harvest", help="Download parked collectors and rewrite sandbox paths")
    harvest.add_argument("--jurisdiction")
    harvest.add_argument("--dest")
    harvest.add_argument("--limit", type=int)
    harvest.add_argument("--skip-legal-scrapers", action="store_true")
    harvest.add_argument("--all", dest="harvest_all", action="store_true", help="Re-scan every dataset, not only missing collectors")
    harvest.add_argument("--workers", type=int, default=8)

    scrape = sub.add_parser("scrape", help="Load a snapshot or run a harvested collector")
    scrape.add_argument("jurisdiction")
    scrape.add_argument(
        "--mode",
        default="snapshot",
        choices=("snapshot", "collect", "resume", "native", "inspect", "sync"),
    )
    scrape.add_argument("--force-resync", action="store_true")
    scrape.add_argument("--output-dir")
    scrape.add_argument("--dry-run", action="store_true")

    args = parser.parse_args(argv)
    if args.command == "catalog":
        if args.jurisdiction:
            entry = get_snapshot_corpus(args.jurisdiction)
            _print(
                {
                    "slug": entry.slug,
                    "country_code": entry.country_code,
                    "display_name": entry.display_name,
                    "collector": entry.collector,
                    "source_dataset_id": entry.source_dataset_id,
                    "ir_dataset_id": entry.ir_dataset_id,
                    "quality": entry.quality,
                }
            )
        else:
            _print(snapshot_catalog_summary())
        return 0
    if args.command == "sources":
        _print(
            [
                {
                    "key": source.key,
                    "kind": source.kind,
                    "handler": source.handler,
                    "country_code": source.country_code,
                    "dataset_id": source.dataset_id,
                    "quality": source.quality,
                }
                for source in list_legal_sources(include_snapshots=not args.native_only)
            ]
        )
        return 0
    if args.command == "harvest":
        _print(
            harvest_legal_collectors(
                jurisdiction=args.jurisdiction,
                dest_root=args.dest,
                include_legal_scrapers=not args.skip_legal_scrapers,
                limit=args.limit,
                missing_only=not args.harvest_all,
                max_workers=args.workers,
            )
        )
        return 0
    result = scrape_legal_data(
        args.jurisdiction,
        mode=args.mode,
        output_dir=args.output_dir,
        dry_run=args.dry_run,
        parameters={"force_resync": getattr(args, "force_resync", False)},
    )
    _print(result)
    return 0 if str(result.get("status") or "") in {"ok", "success", "snapshot", "dry_run", "skipped", "partial"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
