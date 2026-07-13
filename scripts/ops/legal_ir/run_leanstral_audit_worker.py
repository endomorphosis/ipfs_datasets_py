#!/usr/bin/env python3
"""Run the bounded asynchronous Leanstral audit worker over JSONL packets."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Optional, Sequence

from ipfs_datasets_py.logic.modal import (
    LeanstralAuditWorker,
    LeanstralAuditWorkerConfig,
)


DEFAULT_CHECKPOINT_PATH = Path("workspace/leanstral-audit-worker/checkpoint.json")
DEFAULT_CACHE_DIR = Path("workspace/leanstral-audit-worker/cache")


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        action="append",
        default=[],
        help="Immutable disagreement packet JSON/JSONL file or directory.",
    )
    parser.add_argument("--cache-dir", default=str(DEFAULT_CACHE_DIR))
    parser.add_argument("--checkpoint-path", default=str(DEFAULT_CHECKPOINT_PATH))
    parser.add_argument("--max-concurrency", type=int, default=2)
    parser.add_argument("--max-retries", type=int, default=2)
    parser.add_argument("--timeout-seconds", type=float, default=300.0)
    parser.add_argument("--retry-backoff-seconds", type=float, default=0.25)
    parser.add_argument("--expected-state-hash", default="")
    parser.add_argument("--max-records", type=int, default=0)
    parser.add_argument("--provider", default="mistral_vibe")
    parser.add_argument("--model", default="Leanstral")
    parser.add_argument("--vibe-agent", default="lean")
    parser.add_argument(
        "--cache-only",
        action="store_true",
        help="Do not call Leanstral for cache misses.",
    )
    parser.add_argument(
        "--allow-non-leanstral-model",
        action="store_true",
        help="Disable fail-closed protection against substituting another model.",
    )
    return parser.parse_args(argv)


async def async_main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    if not args.input:
        raise SystemExit("--input is required")
    config = LeanstralAuditWorkerConfig(
        max_concurrency=args.max_concurrency,
        max_retries=args.max_retries,
        request_timeout_seconds=args.timeout_seconds,
        retry_backoff_seconds=args.retry_backoff_seconds,
        cache_dir=args.cache_dir,
        checkpoint_path=args.checkpoint_path,
        expected_state_hash=args.expected_state_hash,
        max_records=args.max_records,
        provider_enabled=not args.cache_only,
        provider=args.provider,
        model=args.model,
        vibe_agent=args.vibe_agent,
        require_leanstral_model=not args.allow_non_leanstral_model,
    )
    worker = LeanstralAuditWorker(config)
    summary = await worker.run_paths(args.input)
    print(json.dumps(summary.to_dict(), ensure_ascii=True, sort_keys=True))
    return 1 if summary.failed_count or summary.unavailable_count else 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    return asyncio.run(async_main(argv))


if __name__ == "__main__":
    raise SystemExit(main())
