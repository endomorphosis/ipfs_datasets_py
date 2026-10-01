#!/usr/bin/env python3
"""Explicit bounded formula-decoder branches, one DuckDB owner, scoped Quack."""
from __future__ import annotations
import argparse
import json
import signal
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    fleet = sub.add_parser('run')
    fleet.add_argument('--plan-file', type=Path, required=True)
    fleet.add_argument('--registry', type=Path, required=True)
    fleet.add_argument('--artifact-root', type=Path, required=True)
    fleet.add_argument('--state-directory', type=Path, required=True)
    fleet.add_argument('--resource-ledger', type=Path, required=True)
    fleet.add_argument('--max-workers', type=int, default=4)
    fleet.add_argument('--memory-budget-mb', type=int, default=8192)
    fleet.add_argument('--worker-storage-bytes', type=int, default=750_000_000)
    fleet.add_argument('--plan-only', action='store_true')
    fleet.add_argument('--upload', action='store_true', help='Publish unqualified sparse branches explicitly; never promotes weights')
    worker = sub.add_parser('worker')
    worker.add_argument('--assignment', type=Path, required=True)
    args = parser.parse_args(argv)
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_formula_fleet as profile
    def halt(signum, frame):
        raise KeyboardInterrupt('formula process termination requested')
    previous = signal.signal(signal.SIGTERM, halt)
    try:
        if args.command == 'run':
            if not 1 <= args.max_workers <= 8 or args.memory_budget_mb < 1024 or not 1 <= args.worker_storage_bytes <= 50_000_000_000:
                parser.error('bounded workers, memory and storage required')
            result = profile.run_fleet(args)
        else:
            result = profile.execute_assignment(args.assignment)
    finally:
        signal.signal(signal.SIGTERM, previous)
    # Worker result includes no credential; only paths, hashes and owner lease metadata.
    print(json.dumps(result, sort_keys=True, allow_nan=False))
    return 2 if result.get('status') == 'no_capacity' else 0


if __name__ == '__main__':
    raise SystemExit(main())
