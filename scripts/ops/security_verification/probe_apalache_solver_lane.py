#!/usr/bin/env python3
"""Probe the Apalache TLA model-checker lane for Xaman signing evidence."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any, Mapping, Sequence


SCHEMA_VERSION = 'crypto-exchange-apalache-solver-lane-report/v1'
TASK_ID = 'PORTAL-CXTP-091'
DEFAULT_OUT = Path('security_ir_artifacts/environment/apalache-solver-lane-report.json')
TLA_MODEL = Path('security_ir_artifacts/corpora/xaman-app/tla/XamanSigning.tla')
TLA_REPORT = Path('security_ir_artifacts/corpora/xaman-app/tla/apalache-report.json')


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


def _version(executable: str | None) -> str:
    if not executable:
        return ''
    for args in (['version'], ['--version'], []):
        try:
            completed = subprocess.run(
                [executable, *args],
                check=False,
                capture_output=True,
                text=True,
                timeout=5,
            )
        except (OSError, subprocess.TimeoutExpired):
            continue
        output = (completed.stdout or completed.stderr or '').strip().splitlines()
        if output:
            return output[0]
    return ''


def _run(command: Sequence[str], *, timeout: int = 60) -> dict[str, Any]:
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


def build_apalache_solver_lane_report(
    *,
    repo_root: Path | str | None = None,
    tla_model_path: Path | str = TLA_MODEL,
    tla_report_path: Path | str = TLA_REPORT,
    run_model_check: bool = False,
) -> dict[str, Any]:
    root = Path(repo_root) if repo_root is not None else _repo_root()
    model = Path(tla_model_path)
    if not model.is_absolute():
        model = root / model
    previous_report = Path(tla_report_path)
    if not previous_report.is_absolute():
        previous_report = root / previous_report
    previous_payload = _load_json(previous_report)

    candidates = [
        {'name': 'apalache-mc', 'path': shutil.which('apalache-mc')},
        {'name': 'apalache', 'path': shutil.which('apalache')},
    ]
    for candidate in candidates:
        candidate['present'] = candidate['path'] is not None
        candidate['version'] = _version(candidate['path'])

    selected = next((candidate for candidate in candidates if candidate['path']), None)
    blockers: list[dict[str, Any]] = []
    warnings: list[dict[str, str]] = []
    if selected is None:
        blockers.append({
            'code': 'APALACHE_EXECUTABLE_MISSING',
            'message': 'Neither apalache-mc nor apalache is available on PATH',
            'missing': ['apalache-mc', 'apalache'],
        })
    if not model.is_file():
        blockers.append({'code': 'TLA_MODEL_MISSING', 'message': f'{_relative(model, root)} is missing'})
    if previous_payload is None:
        warnings.append({
            'code': 'XAMAN_TLA_REPORT_MISSING',
            'message': f'{_relative(previous_report, root)} is missing or invalid',
        })

    command = [
        selected['path'] if selected and selected['path'] else 'apalache-mc',
        'check',
        '--inv=SigningGateInvariant',
        str(model),
    ]
    if run_model_check and selected and model.is_file():
        check = _run(command)
        if check['status'] != 'passed':
            blockers.append({'code': 'APALACHE_MODEL_CHECK_FAILED', 'message': check.get('stderr') or 'Apalache check failed'})
    else:
        check = {
            'status': 'not-run',
            'returncode': None,
            'stdout': '',
            'stderr': 'Model check not run because solver is unavailable or run_model_check is false',
            'command': command,
        }

    ready = not blockers and check['status'] == 'passed'
    report = {
        'schema_version': SCHEMA_VERSION,
        'task_id': TASK_ID,
        'generated_at': _utc_now(),
        'executables': candidates,
        'selected_executable': selected,
        'tla_model': {
            'path': _relative(model, root),
            'exists': model.is_file(),
            'sha256': _sha256(model),
        },
        'xaman_tla_report': {
            'path': _relative(previous_report, root),
            'exists': previous_payload is not None,
            'sha256': _sha256(previous_report),
            'overall_status': previous_payload.get('overall_status') if previous_payload else None,
            'security_decision': previous_payload.get('security_decision') if previous_payload else None,
            'invariants': previous_payload.get('tla_model', {}).get('invariants') if previous_payload else [],
        },
        'model_check': check,
        'install_plan': {
            'commands': [
                'cs install apalache',
                'nix profile install nixpkgs#apalache',
                'docker pull ghcr.io/apalache-mc/apalache:latest',
            ],
            'policy': 'Install Apalache outside this probe, rerun with --run-model-check, and commit exact version/output evidence.',
        },
        'blockers': blockers,
        'warnings': warnings,
        'summary': {
            'apalache_present': selected is not None,
            'tla_model_present': model.is_file(),
            'model_check_run': check['status'] != 'not-run',
            'model_check_passed': check['status'] == 'passed',
            'blocker_count': len(blockers),
            'warning_count': len(warnings),
        },
        'overall_status': 'ready' if ready else 'blocked_optional_lane',
        'security_decision': 'APALACHE_SOLVER_LANE_READY' if ready else 'BLOCK_APALACHE_SOLVER_LANE_UNAVAILABLE',
        'production_release_blocked_by_apalache_lane': not ready,
    }
    report['artifact_cid'] = _artifact_cid(report)
    return report


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
