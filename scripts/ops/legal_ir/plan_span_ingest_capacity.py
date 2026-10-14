#!/usr/bin/env python3
"""Plan an explicit idle-only native process-capacity expansion."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ipfs_datasets_py.optimizers.logic_theorem_optimizer.existing_resource_scheduler import (
    expand_idle_process_capacity,
)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scheduler-state', type=Path, required=True)
    parser.add_argument('--expected-policy-sha256', required=True)
    parser.add_argument('--process-slots', type=int, required=True)
    parser.add_argument('--apply', action='store_true', help='Require idle state and deliberately replace only the process capacity')
    args = parser.parse_args(argv)
    result = expand_idle_process_capacity(args.scheduler_state, args.expected_policy_sha256,
        args.process_slots, apply=args.apply)
    print(json.dumps(result, sort_keys=True, allow_nan=False))
    return 0 if result['status'] != 'held_native_activity' else 2


if __name__ == '__main__':
    raise SystemExit(main())
