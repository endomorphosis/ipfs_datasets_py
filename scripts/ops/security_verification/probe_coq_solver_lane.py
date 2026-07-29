#!/usr/bin/env python3
"""Probe the Coq proof-kernel solver lane for Xaman security evidence."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any, Mapping, Sequence


SCHEMA_VERSION = 'crypto-exchange-coq-solver-lane-report/v1'
TASK_ID = 'PORTAL-CXTP-093'
DEFAULT_OUT = Path('security_ir_artifacts/environment/coq-solver-lane-report.json')
DEFAULT_COQ_KERNEL = Path('security_ir_artifacts/corpora/xaman-app/proof-kernel/XamanReceipt.v')
LEAN_KERNEL = Path('security_ir_artifacts/corpora/xaman-app/proof-kernel/XamanReceipt.lean')
PROOF_CONSUMER_REPORT = Path('security_ir_artifacts/corpora/xaman-app/proof-kernel/proof-consumer-report.json')


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


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding='utf-8'))
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _artifact_cid(payload: Mapping[str, Any]) -> str:
    canonical = json.dumps(
        {key: value for key, value in payload.items() if key != 'artifact_cid'},
        sort_keys=True,
        separators=(',', ':'),
    ).encode('utf-8')
    return 'sha256:' + hashlib.sha256(canonical).hexdigest()


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


def build_coq_solver_lane_report(
    *,
    repo_root: Path | str | None = None,
    coq_kernel_path: Path | str = DEFAULT_COQ_KERNEL,
) -> dict[str, Any]:
    root = Path(repo_root) if repo_root is not None else _repo_root()
    coq_kernel = Path(coq_kernel_path)
    if not coq_kernel.is_absolute():
        coq_kernel = root / coq_kernel
    lean_kernel = root / LEAN_KERNEL
    proof_report = root / PROOF_CONSUMER_REPORT
    proof_payload = _load_json(proof_report)

    coqc = shutil.which('coqc')
    coqtop = shutil.which('coqtop')
    opam = shutil.which('opam')
    blockers: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []

    if coqc is None:
        blockers.append({'code': 'COQC_EXECUTABLE_MISSING', 'message': 'coqc executable is not on PATH'})
    if not coq_kernel.is_file():
        blockers.append({
            'code': 'COQ_KERNEL_ARTIFACT_MISSING',
            'message': f'{_relative(coq_kernel, root)} is not present',
        })
    if not lean_kernel.is_file():
        warnings.append({'code': 'LEAN_KERNEL_MISSING', 'message': f'{_relative(lean_kernel, root)} is not present'})
    if proof_payload is None:
        warnings.append({
            'code': 'LEAN_PROOF_CONSUMER_REPORT_MISSING',
            'message': f'{_relative(proof_report, root)} is missing or invalid',
        })

    if coqc and coq_kernel.is_file():
        check = _run([coqc, str(coq_kernel)])
        if check['status'] != 'passed':
            blockers.append({'code': 'COQ_KERNEL_COMPILE_FAILED', 'message': check.get('stderr') or 'coqc failed'})
    else:
        check = {
            'status': 'not-run',
            'returncode': None,
            'stdout': '',
            'stderr': 'coqc executable or Coq kernel artifact is missing',
            'command': ['coqc', _relative(coq_kernel, root)],
        }

    install_plan = {
        'apt': 'sudo apt-get update && sudo apt-get install -y coq',
        'opam': 'opam init --disable-sandboxing && opam switch create coq-8.20 ocaml-base-compiler.5.2.0 && opam install coq',
        'policy': 'Run installation outside the proof task; rerun this probe and commit exact coqc version evidence.',
    }
    ready = not blockers
    report = {
        'schema_version': SCHEMA_VERSION,
        'task_id': TASK_ID,
        'generated_at': _utc_now(),
        'coq': {
            'coqc_present': coqc is not None,
            'coqc_executable': coqc,
            'coqc_version': _version(coqc, ['--version']),
            'coqtop_present': coqtop is not None,
            'coqtop_executable': coqtop,
            'coqtop_version': _version(coqtop, ['--version']),
            'opam_present': opam is not None,
            'opam_executable': opam,
            'opam_version': _version(opam, ['--version']),
        },
        'coq_kernel': {
            'path': _relative(coq_kernel, root),
            'exists': coq_kernel.is_file(),
            'sha256': _sha256(coq_kernel),
        },
        'lean_kernel_context': {
            'path': _relative(lean_kernel, root),
            'exists': lean_kernel.is_file(),
            'sha256': _sha256(lean_kernel),
            'proof_consumer_report_path': _relative(proof_report, root),
            'proof_consumer_report_exists': proof_payload is not None,
            'proof_consumer_security_decision': proof_payload.get('security_decision') if proof_payload else None,
        },
        'coq_kernel_check': check,
        'install_plan': install_plan,
        'blockers': blockers,
        'warnings': warnings,
        'summary': {
            'coqc_present': coqc is not None,
            'coq_kernel_present': coq_kernel.is_file(),
            'coq_kernel_checked': check['status'] == 'passed',
            'blocker_count': len(blockers),
            'warning_count': len(warnings),
        },
        'overall_status': 'ready' if ready else 'blocked_optional_lane',
        'security_decision': 'COQ_SOLVER_LANE_READY' if ready else 'BLOCK_COQ_SOLVER_LANE_UNAVAILABLE',
        'production_release_blocked_by_coq_lane': not ready,
    }
    report['artifact_cid'] = _artifact_cid(report)
    return report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, default=DEFAULT_OUT)
    parser.add_argument('--coq-kernel', type=Path, default=DEFAULT_COQ_KERNEL)
    args = parser.parse_args(argv)

    report = build_coq_solver_lane_report(coq_kernel_path=args.coq_kernel)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    print(json.dumps({'out': args.out.as_posix(), 'overall_status': report['overall_status']}, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
