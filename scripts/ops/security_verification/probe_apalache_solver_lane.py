#!/usr/bin/env python3
"""Probe the reconciled Apalache TLA model-checker lane for Xaman signing."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Sequence

from ipfs_datasets_py.logic.security_models.crypto_exchange.reports.xaman_tla_workflow import (
    APALACHE_REPORT_PATH,
    APALACHE_SOLVER_LANE_REPORT_PATH,
    TLA_ARTIFACT_PATH,
    build_apalache_solver_lane_report as _build_lane_report,
    discover_apalache_executable,
    read_apalache_version,
    run_apalache_checks,
)


DEFAULT_OUT = Path(APALACHE_SOLVER_LANE_REPORT_PATH)
TLA_MODEL = Path(TLA_ARTIFACT_PATH)
TLA_REPORT = Path(APALACHE_REPORT_PATH)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding='utf-8'))
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _resolve(root: Path, path: Path | str) -> Path:
    candidate = Path(path)
    return candidate if candidate.is_absolute() else root / candidate


def build_apalache_solver_lane_report(
    *,
    repo_root: Path | str | None = None,
    tla_model_path: Path | str = TLA_MODEL,
    tla_report_path: Path | str = TLA_REPORT,
    run_model_check: bool = False,
) -> dict[str, Any]:
    root = Path(repo_root) if repo_root is not None else _repo_root()
    model = _resolve(root, tla_model_path)
    report_path = _resolve(root, tla_report_path)
    tla_source = model.read_text(encoding='utf-8') if model.is_file() else ''
    xaman_tla_report = _load_json(report_path)
    apalache_executable = discover_apalache_executable()
    apalache_version = read_apalache_version(apalache_executable)
    apalache_runs = None
    if run_model_check:
        apalache_runs = run_apalache_checks(
            executable=apalache_executable,
            source=tla_source,
            version_output=apalache_version,
        )
    elif xaman_tla_report is not None:
        apalache_runs = xaman_tla_report.get('apalache', {}).get('runs')

    return _build_lane_report(
        repo_root=root,
        tla_source=tla_source,
        xaman_tla_report=xaman_tla_report,
        apalache_executable=apalache_executable,
        apalache_version=apalache_version,
        apalache_runs=apalache_runs,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, default=DEFAULT_OUT)
    parser.add_argument('--tla-model', type=Path, default=TLA_MODEL)
    parser.add_argument('--tla-report', type=Path, default=TLA_REPORT)
    parser.add_argument('--run-model-check', action='store_true')
    args = parser.parse_args(argv)

    report = build_apalache_solver_lane_report(
        tla_model_path=args.tla_model,
        tla_report_path=args.tla_report,
        run_model_check=args.run_model_check,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    print(json.dumps({'out': args.out.as_posix(), 'overall_status': report['overall_status']}, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
