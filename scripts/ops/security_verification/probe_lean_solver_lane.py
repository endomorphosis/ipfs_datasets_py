#!/usr/bin/env python3
"""Probe the Lean proof-consumer solver lane for Xaman security evidence."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any, Mapping, Sequence


SCHEMA_VERSION = 'crypto-exchange-lean-solver-lane-report/v1'
TASK_ID = 'PORTAL-CXTP-090'
DEFAULT_OUT = Path('security_ir_artifacts/environment/lean-solver-lane-report.json')
DEFAULT_KERNEL = Path('security_ir_artifacts/corpora/xaman-app/proof-kernel/XamanReceipt.lean')
DEFAULT_PROOF_CONSUMER_REPORT = Path(
    'security_ir_artifacts/corpora/xaman-app/proof-kernel/proof-consumer-report.json'
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')


def _relative(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    return 'sha256:' + digest.hexdigest()


def _artifact_cid(payload: Mapping[str, Any]) -> str:
    canonical = json.dumps(
        {key: value for key, value in payload.items() if key != 'artifact_cid'},
        sort_keys=True,
        separators=(',', ':'),
    ).encode('utf-8')
    return 'sha256:' + hashlib.sha256(canonical).hexdigest()


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding='utf-8'))
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _version(executable: str | None, args: Sequence[str]) -> str:
    if not executable:
        return ''
    try:
        completed = subprocess.run(
            [executable, *args],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ''
    output = (completed.stdout or completed.stderr or '').strip().splitlines()
    return output[0] if output else ''


def _run(command: Sequence[str], *, timeout: int = 30) -> dict[str, Any]:
    try:
        completed = subprocess.run(
            list(command),
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        return {
            'status': 'timeout',
            'returncode': None,
            'stdout': exc.stdout or '',
            'stderr': exc.stderr or '',
            'command': list(command),
        }
    except OSError as exc:
        return {
            'status': 'unavailable',
            'returncode': None,
            'stdout': '',
            'stderr': str(exc),
            'command': list(command),
        }
    return {
        'status': 'passed' if completed.returncode == 0 else 'failed',
        'returncode': completed.returncode,
        'stdout': completed.stdout,
        'stderr': completed.stderr,
        'command': list(command),
    }


def build_lean_solver_lane_report(
    *,
    repo_root: Path | str | None = None,
    kernel_path: Path | str = DEFAULT_KERNEL,
    proof_consumer_report_path: Path | str = DEFAULT_PROOF_CONSUMER_REPORT,
) -> dict[str, Any]:
    root = Path(repo_root) if repo_root is not None else _repo_root()
    kernel = Path(kernel_path)
    if not kernel.is_absolute():
        kernel = root / kernel
    proof_report = Path(proof_consumer_report_path)
    if not proof_report.is_absolute():
        proof_report = root / proof_report

    lean = shutil.which('lean')
    lake = shutil.which('lake')
    proof_payload = _load_json(proof_report)

    blockers: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []

    if lean is None:
        blockers.append({'code': 'LEAN_EXECUTABLE_MISSING', 'message': 'lean executable is not on PATH'})
    if lake is None:
        blockers.append({'code': 'LAKE_EXECUTABLE_MISSING', 'message': 'lake executable is not on PATH'})
    if not kernel.is_file():
        blockers.append({'code': 'PROOF_KERNEL_MISSING', 'message': f'{_relative(kernel, root)} is missing'})
    if not proof_report.is_file():
        blockers.append({'code': 'PROOF_CONSUMER_REPORT_MISSING', 'message': f'{_relative(proof_report, root)} is missing'})
    elif proof_payload is None:
        blockers.append({'code': 'PROOF_CONSUMER_REPORT_INVALID_JSON', 'message': f'{_relative(proof_report, root)} is not valid JSON'})

    compile_result: dict[str, Any]
    if lean and kernel.is_file():
        compile_result = _run([lean, str(kernel)])
        if compile_result['status'] != 'passed':
            blockers.append({'code': 'LEAN_KERNEL_COMPILE_FAILED', 'message': compile_result.get('stderr') or 'Lean compile failed'})
    else:
        compile_result = {
            'status': 'not-run',
            'returncode': None,
            'stdout': '',
            'stderr': 'Lean executable or proof kernel is missing',
            'command': ['lean', _relative(kernel, root)],
        }

    if proof_payload is not None:
        if proof_payload.get('lean', {}).get('status') != 'compiled':
            blockers.append({
                'code': 'PROOF_CONSUMER_REPORT_NOT_LEAN_COMPILED',
                'message': 'proof-consumer-report.json does not record a compiled Lean kernel',
            })
        if proof_payload.get('kernel', {}).get('contains_sorry') is True:
            blockers.append({'code': 'LEAN_KERNEL_CONTAINS_SORRY', 'message': 'Lean kernel report detected sorry'})
        if proof_payload.get('kernel', {}).get('contains_admit') is True:
            blockers.append({'code': 'LEAN_KERNEL_CONTAINS_ADMIT', 'message': 'Lean kernel report detected admit'})
        if proof_payload.get('production_release_blocked') is True:
            warnings.append({
                'code': 'PRODUCTION_RELEASE_STILL_BLOCKED',
                'message': 'Lean lane is ready but Xaman release remains blocked by integration and assumptions',
            })

    report = {
        'schema_version': SCHEMA_VERSION,
        'task_id': TASK_ID,
        'generated_at': _utc_now(),
        'proof_kernel': {
            'path': _relative(kernel, root),
            'exists': kernel.is_file(),
            'sha256': _sha256(kernel),
        },
        'proof_consumer_report': {
            'path': _relative(proof_report, root),
            'exists': proof_report.is_file(),
            'sha256': _sha256(proof_report),
            'schema_version': proof_payload.get('schema_version') if proof_payload else None,
            'security_decision': proof_payload.get('security_decision') if proof_payload else None,
            'kernel_artifact_cid': proof_payload.get('kernel', {}).get('artifact_cid') if proof_payload else None,
        },
        'lean': {
            'present': lean is not None,
            'executable': lean,
            'version': _version(lean, ['--version']),
        },
        'lake': {
            'present': lake is not None,
            'executable': lake,
            'version': _version(lake, ['--version']),
        },
        'proof_kernel_check': compile_result,
        'summary': {
            'lean_present': lean is not None,
            'lake_present': lake is not None,
            'proof_kernel_checked': compile_result['status'] == 'passed',
            'proof_consumer_report_present': proof_payload is not None,
            'blocker_count': len(blockers),
            'warning_count': len(warnings),
        },
        'blockers': blockers,
        'warnings': warnings,
        'overall_status': 'ready' if not blockers else 'blocked',
        'security_decision': 'LEAN_SOLVER_LANE_READY' if not blockers else 'BLOCK_LEAN_SOLVER_LANE_NOT_READY',
    }
    report['artifact_cid'] = _artifact_cid(report)
    return report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, default=DEFAULT_OUT)
    parser.add_argument('--kernel', type=Path, default=DEFAULT_KERNEL)
    parser.add_argument('--proof-consumer-report', type=Path, default=DEFAULT_PROOF_CONSUMER_REPORT)
    args = parser.parse_args(argv)

    report = build_lean_solver_lane_report(
        kernel_path=args.kernel,
        proof_consumer_report_path=args.proof_consumer_report,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    print(json.dumps({'out': args.out.as_posix(), 'overall_status': report['overall_status']}, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
