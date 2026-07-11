#!/usr/bin/env python3
"""Generate Xaman Testnet TLA+/Apalache concurrency artifacts."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT_DIR = Path(__file__).resolve().parents[3]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from ipfs_datasets_py.logic.security_models.crypto_exchange.reports.xaman_testnet_apalache import (  # noqa: E402
    APALACHE_REPORT_PATH,
    ASSUMPTIONS_PATH,
    MODEL_CID_PATH,
    MODEL_PATH,
    TLA_ARTIFACT_PATH,
    TRACE_MAP_PATH,
    XAMAN_TESTNET_PAYLOAD_TLA,
    build_xaman_testnet_apalache_report,
    run_apalache_invariant_checks,
)


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding='utf-8'))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True) + '\n',
        encoding='utf-8',
    )


def _apalache_version(executable: str | None) -> str | None:
    if executable is None:
        return None
    try:
        completed = subprocess.run(
            [executable, 'version'],
            check=False,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    output = (completed.stdout or completed.stderr).strip()
    return output.splitlines()[0] if output else None


def generate(
    repo_root: Path,
    *,
    apalache_executable: str | None = None,
    run_solver: bool = True,
    timeout_seconds: int = 120,
) -> dict[str, Any]:
    tla_path = repo_root / TLA_ARTIFACT_PATH
    report_path = repo_root / APALACHE_REPORT_PATH
    tla_path.parent.mkdir(parents=True, exist_ok=True)
    tla_path.write_text(XAMAN_TESTNET_PAYLOAD_TLA + '\n', encoding='utf-8')

    executable = apalache_executable
    if executable is None:
        from ipfs_datasets_py.logic.external_provers.lazy_installer import (
            ensure_prover_executable,
            find_executable,
        )

        executable = (
            ensure_prover_executable(
                'apalache',
                reason='Xaman Testnet Apalache invariant execution',
            )
            if run_solver
            else find_executable('apalache-mc') or find_executable('apalache')
        )
    runs = None
    if run_solver and executable is not None:
        runs = run_apalache_invariant_checks(
            tla_path=tla_path,
            apalache_executable=executable,
            timeout_seconds=timeout_seconds,
            working_dir=tla_path.parent,
        )

    report = build_xaman_testnet_apalache_report(
        model_payload=_load_json(repo_root / MODEL_PATH),
        model_cid=(repo_root / MODEL_CID_PATH).read_text(encoding='utf-8').strip(),
        trace_map_payload=_load_json(repo_root / TRACE_MAP_PATH),
        assumptions_payload=_load_json(repo_root / ASSUMPTIONS_PATH),
        tla_source=tla_path.read_text(encoding='utf-8').rstrip('\n'),
        apalache_executable=executable,
        apalache_version=_apalache_version(executable),
        apalache_runs=runs,
    )
    _write_json(report_path, report)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo-root', default=str(ROOT_DIR), help='Repository root containing security_ir_artifacts.')
    parser.add_argument('--apalache-executable', default=None, help='Optional explicit Apalache executable.')
    parser.add_argument('--no-run', action='store_true', help='Emit a report without invoking Apalache.')
    parser.add_argument('--timeout-seconds', type=int, default=120, help='Per-invariant Apalache timeout.')
    args = parser.parse_args(argv)

    report = generate(
        Path(args.repo_root).resolve(),
        apalache_executable=args.apalache_executable,
        run_solver=not args.no_run,
        timeout_seconds=args.timeout_seconds,
    )
    print(
        json.dumps(
            {
                'tla_path': TLA_ARTIFACT_PATH,
                'apalache_report_path': APALACHE_REPORT_PATH,
                'overall_status': report['overall_status'],
                'security_decision': report['security_decision'],
                'checked_invariant_count': report['summary']['checked_invariant_count'],
                'unavailable_apalache_blocks_testnet_assurance': report['coverage_decision'][
                    'unavailable_apalache_blocks_testnet_assurance'
                ],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == '__main__':  # pragma: no cover
    raise SystemExit(main())
