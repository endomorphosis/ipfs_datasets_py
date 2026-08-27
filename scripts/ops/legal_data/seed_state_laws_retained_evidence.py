#!/usr/bin/env python3
"""Seed a fresh state-law evidence generation without network acquisition."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from ipfs_datasets_py.processors.legal_data.state_laws_retained_evidence_seed import (
    RetainedEvidenceSeedSource,
    seed_retained_evidence_generation,
    seed_retained_evidence_union,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Verify retained parser inputs and atomically seed only the allowed "
            "transport projection into a fresh evidence generation."
        )
    )
    parser.add_argument("--source-root", type=Path)
    parser.add_argument(
        "--source-manifest",
        type=Path,
        help=(
            "JSON state-laws-retained-evidence-union-plan-v1 manifest. "
            "Mutually exclusive with --source-root."
        ),
    )
    parser.add_argument("--destination-root", required=True, type=Path)
    parser.add_argument("--jurisdiction", required=True)
    parser.add_argument("--parser-name", required=True)
    parser.add_argument(
        "--allowed-source-transport",
        action="append",
        dest="allowed_source_transports",
        help=(
            "Exact verified source_transport to retain; repeat as needed. "
            "Defaults to direct only."
        ),
    )
    parser.add_argument(
        "--include-url",
        action="append",
        dest="include_urls",
        help=(
            "Restrict the seed to this exact retained official URL; repeat as "
            "needed. Every requested URL must exist under an allowed transport."
        ),
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if (args.source_root is None) == (args.source_manifest is None):
        raise SystemExit(
            "exactly one of --source-root or --source-manifest is required"
        )
    if args.source_manifest is not None:
        if args.allowed_source_transports or args.include_urls:
            raise SystemExit(
                "manifest sources own transport/URL bounds; legacy source flags are invalid"
            )
        payload = json.loads(args.source_manifest.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or payload.get("schema_version") != (
            "state-laws-retained-evidence-union-plan-v1"
        ):
            raise SystemExit("retained evidence source manifest has the wrong schema")
        raw_sources = payload.get("sources")
        if not isinstance(raw_sources, list) or not raw_sources:
            raise SystemExit("retained evidence source manifest has no sources")
        sources = []
        for row in raw_sources:
            if not isinstance(row, dict):
                raise SystemExit("retained evidence source manifest row is invalid")
            sources.append(
                RetainedEvidenceSeedSource(
                    source_root=str(row.get("source_root") or ""),
                    parser_name=str(row.get("parser_name") or ""),
                    allowed_source_transports=tuple(
                        str(value or "").strip()
                        for value in list(
                            row.get("allowed_source_transports") or []
                        )
                        if str(value or "").strip()
                    ),
                    include_urls=tuple(
                        str(value or "").strip()
                        for value in list(row.get("include_urls") or [])
                        if str(value or "").strip()
                    ),
                )
            )
        report = seed_retained_evidence_union(
            sources=sources,
            destination_root=args.destination_root,
            jurisdiction=args.jurisdiction,
            parser_name=args.parser_name,
        )
    else:
        report = seed_retained_evidence_generation(
            source_root=args.source_root,
            destination_root=args.destination_root,
            jurisdiction=args.jurisdiction,
            parser_name=args.parser_name,
            allowed_source_transports=(
                tuple(args.allowed_source_transports)
                if args.allowed_source_transports
                else ("direct",)
            ),
            include_urls=(
                tuple(args.include_urls) if args.include_urls else None
            ),
        )
    print(json.dumps(report.to_dict(), sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
