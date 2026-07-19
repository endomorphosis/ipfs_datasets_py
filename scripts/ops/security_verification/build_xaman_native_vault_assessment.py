#!/usr/bin/env python3
"""Build the source-bound Xaman native-vault and rekey assessment."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT_DIR = Path(__file__).resolve().parents[3]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from ipfs_datasets_py.logic.security_models.crypto_exchange.reports.xaman_native_vault_assessment import (  # noqa: E402
    REPORT_PATH,
    SMTLIB_PATH,
    SOURCE_MANIFEST_PATH,
    REKEY_RECOVERY_SMTLIB,
    build_native_vault_assessment,
    run_rekey_solver_lane,
)


def _load_json(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(payload, dict):
        raise ValueError(f'expected JSON object: {path}')
    return payload


def _write(path: Path, value: str | dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(value, str):
        path.write_text(value, encoding='utf-8')
    else:
        path.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True) + '\n', encoding='utf-8')


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo-root', default=str(ROOT_DIR), help='Repository root.')
    parser.add_argument('--source-root', required=True, help='Pinned Xaman public-source checkout.')
    parser.add_argument('--out', default=REPORT_PATH, help='Assessment report path.')
    parser.add_argument('--smt-out', default=SMTLIB_PATH, help='SMT-LIB model path.')
    parser.add_argument('--timeout-seconds', type=int, default=15, help='Per-solver timeout.')
    args = parser.parse_args(argv)

    root = Path(args.repo_root).resolve()
    source_root = Path(args.source_root).resolve()
    report_path = Path(args.out)
    smt_path = Path(args.smt_out)
    if not report_path.is_absolute():
        report_path = root / report_path
    if not smt_path.is_absolute():
        smt_path = root / smt_path
    manifest = _load_json(root / SOURCE_MANIFEST_PATH)
    solver_lane = run_rekey_solver_lane(timeout_seconds=args.timeout_seconds)
    report = build_native_vault_assessment(
        source_root=source_root,
        manifest=manifest,
        solver_lane=solver_lane,
    )
    _write(smt_path, REKEY_RECOVERY_SMTLIB)
    _write(report_path, report)
    print(
        json.dumps(
            {
                'report_path': str(report_path.relative_to(root)) if report_path.is_relative_to(root) else str(report_path),
                'smt_path': str(smt_path.relative_to(root)) if smt_path.is_relative_to(root) else str(smt_path),
                'overall_status': report['overall_status'],
                'security_decision': report['security_decision'],
                'solver_statuses': {name: result['status'] for name, result in solver_lane.items()},
            },
            sort_keys=True,
        )
    )
    return 0 if report['overall_status'] == 'checked_source_bounded_with_runtime_boundaries' else 1


if __name__ == '__main__':  # pragma: no cover
    raise SystemExit(main())
