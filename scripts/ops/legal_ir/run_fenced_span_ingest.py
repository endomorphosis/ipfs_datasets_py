#!/usr/bin/env python3
"""Own one native-reserved fenced ingestion attempt; never grant legal admission."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from ipfs_datasets_py.logic.autoformal.span_ingest_runtime import (
    FALSE, MAX_CONTROL_BYTES, SpanIngestHeadroomDeferred, child_main, parse_json, run_fenced_ingest_runtime,
)
from ipfs_datasets_py.logic.autoformal.span_cache_exchange import _read_regular_snapshot
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.resource_scheduler import ResourceUnavailableError, LeaseTimeoutError


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--spec", type=Path, help="Closed spec using the existing native policy and disk roots.")
    group.add_argument("--child", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    try:
        if args.child:
            # Block before inference/cache/pool work. Only the external owner
            # writes this bounded pipe after recording the child identity.
            raw = sys.stdin.buffer.readline(MAX_CONTROL_BYTES+2)
            return child_main(parse_json(raw))
        spec = parse_json(_read_regular_snapshot(args.spec, max_bytes=MAX_CONTROL_BYTES))
        report = run_fenced_ingest_runtime(spec)
        print(json.dumps(report, sort_keys=True), flush=True)
        return 0
    except Exception as error:
        status = ("deferred_fenced_runtime_headroom" if isinstance(error, (SpanIngestHeadroomDeferred, ResourceUnavailableError, LeaseTimeoutError))
                  else "refused_fenced_runtime")
        print(json.dumps(dict(status=status, error_type=type(error).__name__,
                              reason=str(error), **FALSE), sort_keys=True), flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
