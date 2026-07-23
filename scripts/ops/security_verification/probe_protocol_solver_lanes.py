#!/usr/bin/env python3
"""Probe Tamarin and ProVerif solver lanes for the Xaman payload protocol."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any, Mapping, Sequence

from ipfs_datasets_py.logic.external_provers.lazy_installer import (
    ensure_prover_executable,
    find_executable,
)


SCHEMA_VERSION = 'crypto-exchange-protocol-solver-lane-report/v1'
TASK_ID = 'PORTAL-CXTP-092'
DEFAULT_OUT = Path('security_ir_artifacts/environment/protocol-solver-lane-report.json')
TAMARIN_MODEL = Path('security_ir_artifacts/corpora/xaman-app/protocol/xaman_payload_protocol.spthy')
PROVERIF_MODEL = Path('security_ir_artifacts/corpora/xaman-app/protocol/xaman_payload_protocol.pv')
PROVERIF_MODEL_FALLBACK = Path('security_ir_artifacts/corpora/xaman-app/testnet/protocol/xaman_testnet_payload.pv')
PROTOCOL_REPORT = Path('security_ir_artifacts/corpora/xaman-app/protocol/protocol-report.json')


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
    for args in (['--version'], ['version'], []):
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


def build_protocol_solver_lane_report(
    *,
    repo_root: Path | str | None = None,
    tamarin_model_path: Path | str = TAMARIN_MODEL,
    proverif_model_path: Path | str = PROVERIF_MODEL,
    protocol_report_path: Path | str = PROTOCOL_REPORT,
    run_protocol_checks: bool = False,
) -> dict[str, Any]:
    root = Path(repo_root) if repo_root is not None else _repo_root()
    tamarin_model = Path(tamarin_model_path)
    if not tamarin_model.is_absolute():
        tamarin_model = root / tamarin_model
    proverif_model = Path(proverif_model_path)
    if not proverif_model.is_absolute():
        proverif_model = root / proverif_model
    fallback_model = PROVERIF_MODEL_FALLBACK
    if not fallback_model.is_absolute():
        fallback_model = root / fallback_model
    protocol_report = Path(protocol_report_path)
    if not protocol_report.is_absolute():
        protocol_report = root / protocol_report
    protocol_payload = _load_json(protocol_report)

    resolver = ensure_prover_executable if run_protocol_checks else find_executable
    if run_protocol_checks:
        tamarin = resolver('tamarin', reason='Xaman protocol solver lane execution')
        proverif = resolver('proverif', reason='Xaman protocol solver lane execution')
    else:
        tamarin = resolver('tamarin-prover')
        proverif = resolver('proverif')
    blockers: list[dict[str, Any]] = []
    warnings: list[dict[str, str]] = []
    if tamarin is None:
        blockers.append({'code': 'TAMARIN_EXECUTABLE_MISSING', 'message': 'tamarin-prover executable is not on PATH'})
    if proverif is None:
        blockers.append({'code': 'PROVERIF_EXECUTABLE_MISSING', 'message': 'proverif executable is not on PATH'})
    if run_protocol_checks and not proverif_model.is_file() and fallback_model.is_file():
        warnings.append(
            {
                'code': 'PROVERIF_MODEL_FALLBACK',
                'message': (
                    f'{_relative(proverif_model, root)} is missing; using '
                    f'{_relative(fallback_model, root)} as the protocol fallback source.'
                ),
            }
        )
        proverif_model = fallback_model
    if not tamarin_model.is_file():
        blockers.append({'code': 'TAMARIN_MODEL_MISSING', 'message': f'{_relative(tamarin_model, root)} is missing'})
    if not proverif_model.is_file():
        blockers.append({'code': 'PROVERIF_MODEL_MISSING', 'message': f'{_relative(proverif_model, root)} is missing'})
    if protocol_payload is None:
        warnings.append({'code': 'PROTOCOL_REPORT_MISSING', 'message': f'{_relative(protocol_report, root)} is missing or invalid'})

    tamarin_command = [tamarin or 'tamarin-prover', '--prove', str(tamarin_model)]
    proverif_command = [proverif or 'proverif', str(proverif_model)]
    if run_protocol_checks and tamarin and tamarin_model.is_file():
        tamarin_check = _run(tamarin_command)
        if tamarin_check['status'] != 'passed':
            blockers.append({'code': 'TAMARIN_CHECK_FAILED', 'message': tamarin_check.get('stderr') or 'Tamarin check failed'})
    else:
        tamarin_check = {
            'status': 'not-run',
            'returncode': None,
            'stdout': '',
            'stderr': 'Tamarin check not run because solver is unavailable or run_protocol_checks is false',
            'command': tamarin_command,
        }

    if run_protocol_checks and proverif and proverif_model.is_file():
        proverif_check = _run(proverif_command)
        if proverif_check['status'] != 'passed':
            blockers.append({'code': 'PROVERIF_CHECK_FAILED', 'message': proverif_check.get('stderr') or 'ProVerif check failed'})
    else:
        proverif_check = {
            'status': 'not-run',
            'returncode': None,
            'stdout': '',
            'stderr': 'ProVerif check not run because solver/model is unavailable or run_protocol_checks is false',
            'command': proverif_command,
        }

    ready = not blockers and tamarin_check['status'] == 'passed' and proverif_check['status'] == 'passed'
    protocol_overall_status = (
        protocol_payload.get('overall_status') if protocol_payload and isinstance(protocol_payload.get('overall_status'), str)
        else 'blocked_optional_lane'
    )
    protocol_security_decision = (
        protocol_payload.get('security_decision')
        if protocol_payload and isinstance(protocol_payload.get('security_decision'), str)
        else None
    )
    protocol_covered_claim_ids = (
        protocol_payload.get('covered_claim_ids') if protocol_payload and isinstance(protocol_payload.get('covered_claim_ids'), list)
        else []
    )

    report = {
        'schema_version': SCHEMA_VERSION,
        'task_id': TASK_ID,
        'generated_at': _utc_now(),
        'solvers': {
            'tamarin': {
                'present': tamarin is not None,
                'executable': tamarin,
                'version': _version(tamarin),
            },
            'proverif': {
                'present': proverif is not None,
                'executable': proverif,
                'version': _version(proverif),
            },
        },
        'models': {
            'tamarin': {
                'path': _relative(tamarin_model, root),
                'exists': tamarin_model.is_file(),
                'sha256': _sha256(tamarin_model),
            },
            'proverif': {
                'path': _relative(proverif_model, root),
                'exists': proverif_model.is_file(),
                'sha256': _sha256(proverif_model),
            },
        },
        'protocol_report': {
            'path': _relative(protocol_report, root),
            'exists': protocol_payload is not None,
            'sha256': _sha256(protocol_report),
            'overall_status': protocol_overall_status,
            'security_decision': protocol_security_decision,
            'covered_claim_ids': protocol_covered_claim_ids,
        },
        'checks': {
            'tamarin': tamarin_check,
            'proverif': proverif_check,
        },
        'install_plan': {
            'tamarin': ['nix profile install nixpkgs#tamarin-prover', 'stack install tamarin-prover'],
            'proverif': ['opam install proverif', 'nix profile install nixpkgs#proverif'],
            'policy': 'Install protocol solvers outside this probe, add a reviewed ProVerif model, rerun with --run-protocol-checks, and commit exact version/output evidence.',
        },
        'blockers': blockers,
        'warnings': warnings,
        'summary': {
            'tamarin_present': tamarin is not None,
            'proverif_present': proverif is not None,
            'tamarin_model_present': tamarin_model.is_file(),
            'proverif_model_present': proverif_model.is_file(),
            'tamarin_check_passed': tamarin_check['status'] == 'passed',
            'proverif_check_passed': proverif_check['status'] == 'passed',
            'blocker_count': len(blockers),
            'warning_count': len(warnings),
        },
        'overall_status': 'ready' if ready else 'blocked_optional_lane',
        'security_decision': 'PROTOCOL_SOLVER_LANES_READY' if ready else 'BLOCK_PROTOCOL_SOLVER_LANES_UNAVAILABLE',
        'production_release_blocked_by_protocol_solvers': not ready,
    }
    report['artifact_cid'] = _artifact_cid(report)
    return report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, default=DEFAULT_OUT)
    parser.add_argument('--tamarin-model', type=Path, default=TAMARIN_MODEL)
    parser.add_argument('--proverif-model', type=Path, default=PROVERIF_MODEL)
    parser.add_argument('--protocol-report', type=Path, default=PROTOCOL_REPORT)
    parser.add_argument('--run-protocol-checks', action='store_true')
    args = parser.parse_args(argv)

    report = build_protocol_solver_lane_report(
        tamarin_model_path=args.tamarin_model,
        proverif_model_path=args.proverif_model,
        protocol_report_path=args.protocol_report,
        run_protocol_checks=args.run_protocol_checks,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    print(json.dumps({'out': args.out.as_posix(), 'overall_status': report['overall_status']}, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
