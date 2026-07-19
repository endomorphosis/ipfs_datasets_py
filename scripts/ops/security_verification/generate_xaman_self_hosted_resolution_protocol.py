#!/usr/bin/env python3
"""Generate and optionally check the conditional self-hosted resolver model."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT_DIR = Path(__file__).resolve().parents[3]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from ipfs_datasets_py.logic.security_models.crypto_exchange.reports.xaman_self_hosted_resolution_protocol import (  # noqa: E402
    PROTOCOL_REPORT_PATH,
    run_resolution_protocol,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo-root', default=str(ROOT_DIR), help='Repository root.')
    parser.add_argument('--run-solver', action='store_true', help='Run Tamarin and ProVerif after materializing the models.')
    parser.add_argument('--timeout-seconds', type=int, default=120, help='Per-solver timeout.')
    args = parser.parse_args(argv)
    root = Path(args.repo_root).resolve()
    report = run_resolution_protocol(root, run_solver=args.run_solver, timeout_seconds=args.timeout_seconds)
    print(
        json.dumps(
            {
                'report_path': PROTOCOL_REPORT_PATH,
                'overall_status': report['overall_status'],
                'security_decision': report['security_decision'],
                'production_release_blocked': report['production_release_blocked'],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == '__main__':  # pragma: no cover
    raise SystemExit(main())
