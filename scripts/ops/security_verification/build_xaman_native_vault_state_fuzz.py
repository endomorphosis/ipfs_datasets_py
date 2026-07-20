#!/usr/bin/env python3
"""Build the source-bound native-vault state fuzz and solver evidence."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT_DIR = Path(__file__).resolve().parents[3]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from ipfs_datasets_py.logic.security_models.crypto_exchange.reports.xaman_native_vault_state_fuzz import (  # noqa: E402
    ASSESSMENT_PATH,
    REKEY_STATE_SMTLIB,
    REPORT_PATH,
    SMTLIB_PATH,
    SOURCE_MANIFEST_PATH,
    build_native_vault_state_fuzz_report,
    run_state_fuzz_solver_lane,
)


def _load(path: Path) -> dict[str, object]:
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
    parser.add_argument('--repo-root', default=str(ROOT_DIR))
    parser.add_argument('--source-root', required=True)
    parser.add_argument('--out', default=REPORT_PATH)
    parser.add_argument('--smt-out', default=SMTLIB_PATH)
    parser.add_argument('--timeout-seconds', type=int, default=15)
    args = parser.parse_args(argv)
    root = Path(args.repo_root).resolve()
    out = Path(args.out)
    smt_out = Path(args.smt_out)
    if not out.is_absolute(): out = root / out
    if not smt_out.is_absolute(): smt_out = root / smt_out
    lane = run_state_fuzz_solver_lane(timeout_seconds=args.timeout_seconds)
    report = build_native_vault_state_fuzz_report(
        source_root=Path(args.source_root).resolve(),
        manifest=_load(root / SOURCE_MANIFEST_PATH),
        assessment=_load(root / ASSESSMENT_PATH),
        solver_lane=lane,
    )
    _write(smt_out, REKEY_STATE_SMTLIB)
    _write(out, report)
    print(json.dumps({
        'overall_status': report['overall_status'],
        'report_cid': report['artifact_cid'],
        'runtime_obligation_case_count': report['bounded_fuzz_campaign']['runtime_obligation_case_count'],
        'solver_statuses': {name: value['status'] for name, value in lane.items()},
    }, sort_keys=True))
    return 0 if report['overall_status'].startswith('checked_') else 1


if __name__ == '__main__':  # pragma: no cover
    raise SystemExit(main())
