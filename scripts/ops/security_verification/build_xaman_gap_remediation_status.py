#!/usr/bin/env python3
"""Build the Xaman source-bounded gap remediation status artifact."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any


ROOT_DIR = Path(__file__).resolve().parents[3]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from ipfs_datasets_py.logic.security_models.crypto_exchange.reports.xaman_gap_remediation_status import (  # noqa: E402
    build_gap_remediation_status,
)


GAP_MANIFEST_PATH = Path('security_ir_artifacts/corpora/xaman-app/testnet/fuzz/final-gap-remediation-manifest.json')
SOLVER_PORTFOLIO_REPORT_PATH = Path('security_ir_artifacts/corpora/xaman-app/testnet/solver-portfolio-report.json')
FUZZ_REPORT_PATH = Path('security_ir_artifacts/corpora/xaman-app/testnet/fuzz/fuzz-report.json')
OUTPUT_PATH = Path('security_ir_artifacts/corpora/xaman-app/testnet/fuzz/gap-remediation-status.json')


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(payload, dict):
        raise ValueError(f'{path} did not contain a JSON object')
    return payload


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True) + '\n', encoding='utf-8')


def generate(
    repo_root: Path,
    *,
    gap_manifest_path: Path = GAP_MANIFEST_PATH,
    solver_portfolio_report_path: Path = SOLVER_PORTFOLIO_REPORT_PATH,
    fuzz_report_path: Path = FUZZ_REPORT_PATH,
    out_path: Path = OUTPUT_PATH,
) -> dict[str, Any]:
    report = build_gap_remediation_status(
        gap_manifest=_load_json(repo_root / gap_manifest_path),
        solver_portfolio_report=_load_json(repo_root / solver_portfolio_report_path),
        fuzz_report=_load_json(repo_root / fuzz_report_path),
    )
    out = out_path if out_path.is_absolute() else repo_root / out_path
    _write_json(out, report)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo-root', default=str(ROOT_DIR), help='Repository root containing security_ir_artifacts.')
    parser.add_argument('--gap-manifest', default=str(GAP_MANIFEST_PATH), help='Final gap remediation manifest path.')
    parser.add_argument('--solver-portfolio-report', default=str(SOLVER_PORTFOLIO_REPORT_PATH), help='Solver portfolio report path.')
    parser.add_argument('--fuzz-report', default=str(FUZZ_REPORT_PATH), help='Fuzz report path.')
    parser.add_argument('--out', default=str(OUTPUT_PATH), help='Output status report path.')
    args = parser.parse_args(argv)

    repo_root = Path(args.repo_root).resolve()

    def _path(value: str) -> Path:
        candidate = Path(value)
        return candidate if candidate.is_absolute() else Path(value)

    report = generate(
        repo_root,
        gap_manifest_path=_path(args.gap_manifest),
        solver_portfolio_report_path=_path(args.solver_portfolio_report),
        fuzz_report_path=_path(args.fuzz_report),
        out_path=_path(args.out),
    )
    print(
        json.dumps(
            {
                'out': str(Path(args.out)),
                'overall_status': report['overall_status'],
                'local_remediated_count': report['summary']['local_remediated_count'],
                'external_blocked_count': report['summary']['external_blocked_count'],
                'security_decision': report['security_decision'],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == '__main__':  # pragma: no cover
    raise SystemExit(main())
