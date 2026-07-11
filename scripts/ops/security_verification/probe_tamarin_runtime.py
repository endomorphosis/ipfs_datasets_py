#!/usr/bin/env python3
"""Probe the pinned Tamarin/Maude runtime for Testnet protocol checking."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Mapping, Sequence


SCHEMA_VERSION = 'crypto-exchange-tamarin-runtime-report/v1'
TASK_ID = 'PORTAL-CXTP-141'
PINNED_TAMARIN_VERSION = '1.12.0'
REJECTED_MAUDE_VERSIONS = {'3.2'}
DEFAULT_OUT = Path('security_ir_artifacts/environment/tamarin-runtime-report.json')
USER_LOCAL_SOLVER_ROOT = Path.home() / '.local/share/xaman-proof-solvers'
DEFAULT_TAMARIN_BINARY = USER_LOCAL_SOLVER_ROOT / 'opt/tamarin-prover'
DEFAULT_MAUDE_RUNTIME_DIR = USER_LOCAL_SOLVER_ROOT / 'opt/maude-3.5.1'
DEFAULT_MAUDE_BINARY = DEFAULT_MAUDE_RUNTIME_DIR / 'maude'
DEFAULT_TAMARIN_ARCHIVE = USER_LOCAL_SOLVER_ROOT / 'downloads/tamarin-prover-1.12.0-linux64-ubuntu.tar.gz'
DEFAULT_MAUDE_ARCHIVE = USER_LOCAL_SOLVER_ROOT / 'downloads/Maude-3.5.1-linux-x86_64.zip'

MINIMAL_THEORY = '''theory TamarinRuntimeSmoke
begin

builtins: hashing

rule Runtime_Smoke:
  [ Fr(~x) ]
  --[ RuntimeReady(~x) ]->
  [ Out(h(~x)) ]

lemma runtime_smoke_exists:
  exists-trace
  "Ex x #i. RuntimeReady(x) @ i"

end
'''


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')


def _relative(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _sha256_bytes(payload: bytes) -> str:
    return 'sha256:' + hashlib.sha256(payload).hexdigest()


def _sha256_text(payload: str) -> str:
    return _sha256_bytes(payload.encode('utf-8'))


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


def _path_or_none(value: str | None) -> Path | None:
    return Path(value) if value else None


def _resolve_executable(explicit: Path | str | None, name: str) -> Path | None:
    if explicit is not None:
        candidate = Path(explicit).expanduser()
        return candidate if candidate.is_file() else None
    resolved = shutil.which(name)
    return Path(resolved) if resolved else None


def _run(command: Sequence[str], *, env: Mapping[str, str] | None = None, timeout: int = 60) -> dict[str, Any]:
    try:
        completed = subprocess.run(
            list(command),
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=dict(env) if env is not None else None,
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


def _runtime_env(maude: Path | None) -> dict[str, str]:
    env = os.environ.copy()
    if maude is not None:
        env['PATH'] = maude.parent.as_posix() + os.pathsep + env.get('PATH', '')
        if DEFAULT_MAUDE_RUNTIME_DIR.is_dir():
            env['MAUDE_LIB'] = DEFAULT_MAUDE_RUNTIME_DIR.as_posix() + (
                os.pathsep + env['MAUDE_LIB'] if env.get('MAUDE_LIB') else ''
            )
    return env


def _first_match(pattern: str, text: str) -> str | None:
    match = re.search(pattern, text, flags=re.MULTILINE)
    return match.group(1) if match else None


def _version_summary(tamarin_version_output: str, maude_version_output: str) -> dict[str, Any]:
    tamarin_version = _first_match(r'Tamarin version\s+([^\s]+)', tamarin_version_output)
    if tamarin_version is None:
        tamarin_version = _first_match(r'tamarin-prover\s+([0-9]+(?:\.[0-9]+)+)', tamarin_version_output)
    maude_version_from_tamarin = _first_match(r'Maude version\s+([^\s]+)', tamarin_version_output)
    maude_version = maude_version_output.strip().splitlines()[0] if maude_version_output.strip() else None
    if maude_version_from_tamarin is None:
        maude_version_from_tamarin = _first_match(r'^\s*([0-9]+(?:\.[0-9]+)+)\.\s+OK\.', tamarin_version_output)
    acceptance_ok = bool(
        maude_version_from_tamarin
        and (
            re.search(rf'(^|\n)\s*{re.escape(maude_version_from_tamarin)}\.\s+OK\.', tamarin_version_output)
            or re.search(rf'checking version:\s*{re.escape(maude_version_from_tamarin)}\.\s+OK\.', tamarin_version_output)
        )
        and 'checking installation: OK' in tamarin_version_output
    )
    return {
        'tamarin_version': tamarin_version,
        'maude_version': maude_version,
        'maude_version_reported_by_tamarin': maude_version_from_tamarin,
        'tamarin_acceptance_marker': f'{maude_version_from_tamarin}. OK.' if maude_version_from_tamarin else None,
        'tamarin_accepts_maude': acceptance_ok,
    }


def _executable_record(name: str, wrapper: Path | None, resolved_binary: Path | None, root: Path) -> dict[str, Any]:
    return {
        'name': name,
        'path': wrapper.as_posix() if wrapper else None,
        'exists': wrapper.is_file() if wrapper else False,
        'sha256': _sha256(wrapper) if wrapper else None,
        'resolved_binary': resolved_binary.as_posix() if resolved_binary and resolved_binary.is_file() else None,
        'resolved_binary_exists': resolved_binary.is_file() if resolved_binary else False,
        'resolved_binary_sha256': _sha256(resolved_binary) if resolved_binary else None,
        'relative_path': _relative(wrapper, root) if wrapper else None,
    }


def _artifact_record(path: Path, root: Path) -> dict[str, Any]:
    return {
        'path': path.as_posix(),
        'relative_path': _relative(path, root),
        'exists': path.is_file(),
        'sha256': _sha256(path),
    }


def _run_minimal_theory(tamarin: Path | None, maude: Path | None, env: Mapping[str, str]) -> dict[str, Any]:
    if tamarin is None or maude is None:
        return {
            'status': 'not-run',
            'returncode': None,
            'stdout': '',
            'stderr': 'Minimal theory was not run because tamarin-prover or maude is missing',
            'command': [tamarin.as_posix() if tamarin else 'tamarin-prover', f'--with-maude={maude.as_posix()}' if maude else '--with-maude=maude', '--prove', 'runtime_smoke.spthy'],
        }

    with tempfile.TemporaryDirectory(prefix='tamarin-runtime-') as tmp:
        theory_path = Path(tmp) / 'runtime_smoke.spthy'
        theory_path.write_text(MINIMAL_THEORY, encoding='utf-8')
        command = [tamarin.as_posix(), f'--with-maude={maude.as_posix()}', '--prove', theory_path.as_posix()]
        return _run(command, env=env, timeout=60)


def build_tamarin_runtime_report(
    *,
    repo_root: Path | str | None = None,
    tamarin_executable: Path | str | None = None,
    maude_executable: Path | str | None = None,
    tamarin_binary: Path | str = DEFAULT_TAMARIN_BINARY,
    maude_binary: Path | str = DEFAULT_MAUDE_BINARY,
    tamarin_archive: Path | str = DEFAULT_TAMARIN_ARCHIVE,
    maude_archive: Path | str = DEFAULT_MAUDE_ARCHIVE,
    run_smoke: bool = True,
) -> dict[str, Any]:
    root = Path(repo_root) if repo_root is not None else _repo_root()
    tamarin = _resolve_executable(tamarin_executable, 'tamarin-prover')
    maude = _resolve_executable(maude_executable, 'maude')
    tamarin_target = Path(tamarin_binary).expanduser()
    maude_target = Path(maude_binary).expanduser()
    tamarin_archive_path = Path(tamarin_archive).expanduser()
    maude_archive_path = Path(maude_archive).expanduser()
    env = _runtime_env(maude)

    blockers: list[dict[str, Any]] = []
    warnings: list[dict[str, str]] = []
    if tamarin is None:
        blockers.append({'code': 'TAMARIN_EXECUTABLE_MISSING', 'message': 'tamarin-prover executable is not on PATH'})
    if maude is None:
        blockers.append({'code': 'MAUDE_EXECUTABLE_MISSING', 'message': 'maude executable is not on PATH'})
    if not tamarin_target.is_file():
        warnings.append({'code': 'TAMARIN_TARGET_BINARY_MISSING', 'message': f'{tamarin_target.as_posix()} is missing'})
    if not maude_target.is_file():
        warnings.append({'code': 'MAUDE_TARGET_BINARY_MISSING', 'message': f'{maude_target.as_posix()} is missing'})
    if not tamarin_archive_path.is_file():
        warnings.append({'code': 'TAMARIN_ARCHIVE_MISSING', 'message': f'{tamarin_archive_path.as_posix()} is missing'})
    if not maude_archive_path.is_file():
        warnings.append({'code': 'MAUDE_ARCHIVE_MISSING', 'message': f'{maude_archive_path.as_posix()} is missing'})

    maude_version_check = _run([maude.as_posix(), '--version'], env=env, timeout=10) if maude else {
        'status': 'not-run',
        'returncode': None,
        'stdout': '',
        'stderr': 'maude executable is missing',
        'command': ['maude', '--version'],
    }
    tamarin_version_check = (
        _run([tamarin.as_posix(), f'--with-maude={maude.as_posix()}', '--version'], env=env, timeout=20)
        if tamarin and maude
        else {
            'status': 'not-run',
            'returncode': None,
            'stdout': '',
            'stderr': 'tamarin-prover or maude executable is missing',
            'command': [tamarin.as_posix() if tamarin else 'tamarin-prover', f'--with-maude={maude.as_posix()}' if maude else '--with-maude=maude', '--version'],
        }
    )
    version_output = (tamarin_version_check.get('stdout') or '') + (tamarin_version_check.get('stderr') or '')
    maude_output = (maude_version_check.get('stdout') or '') + (maude_version_check.get('stderr') or '')
    versions = _version_summary(version_output, maude_output)

    if tamarin_version_check['status'] != 'passed':
        blockers.append({'code': 'TAMARIN_VERSION_CHECK_FAILED', 'message': tamarin_version_check.get('stderr') or 'tamarin-prover --version failed'})
    if maude_version_check['status'] != 'passed':
        blockers.append({'code': 'MAUDE_VERSION_CHECK_FAILED', 'message': maude_version_check.get('stderr') or 'maude --version failed'})
    if versions['tamarin_version'] != PINNED_TAMARIN_VERSION:
        blockers.append({
            'code': 'TAMARIN_VERSION_NOT_PINNED',
            'message': f"Expected Tamarin {PINNED_TAMARIN_VERSION}, observed {versions['tamarin_version']!r}",
        })
    observed_maude = versions['maude_version_reported_by_tamarin'] or versions['maude_version']
    if observed_maude in REJECTED_MAUDE_VERSIONS:
        blockers.append({
            'code': 'MAUDE_3_2_NOT_ACCEPTED',
            'message': 'Maude 3.2 warning evidence is explicitly rejected for this Testnet protocol-proof lane',
        })
    if not versions['tamarin_accepts_maude']:
        blockers.append({
            'code': 'TAMARIN_DID_NOT_ACCEPT_MAUDE',
            'message': 'Tamarin version output did not include an explicit Maude OK marker and installation OK result',
        })

    smoke = _run_minimal_theory(tamarin, maude, env) if run_smoke else {
        'status': 'not-run',
        'returncode': None,
        'stdout': '',
        'stderr': 'Minimal theory run disabled by caller',
        'command': [tamarin.as_posix() if tamarin else 'tamarin-prover', f'--with-maude={maude.as_posix()}' if maude else '--with-maude=maude', '--prove', 'runtime_smoke.spthy'],
    }
    smoke_output = (smoke.get('stdout') or '') + (smoke.get('stderr') or '')
    smoke_verified = smoke['status'] == 'passed' and 'runtime_smoke_exists (exists-trace): verified' in smoke_output
    if not smoke_verified:
        blockers.append({'code': 'TAMARIN_MINIMAL_THEORY_FAILED', 'message': smoke.get('stderr') or 'Minimal theory was not verified'})

    ready = not blockers
    report = {
        'schema_version': SCHEMA_VERSION,
        'task_id': TASK_ID,
        'depends_on': ['PORTAL-CXTP-092'],
        'generated_at': _utc_now(),
        'pinned_runtime': {
            'tamarin_version': PINNED_TAMARIN_VERSION,
            'rejected_maude_versions': sorted(REJECTED_MAUDE_VERSIONS),
            'acceptance_policy': 'Use Tamarin 1.12.0 only when its own --with-maude version check reports the selected Maude version as OK and installation OK.',
        },
        'executables': {
            'tamarin_prover': _executable_record('tamarin-prover', tamarin, tamarin_target, root),
            'maude': _executable_record('maude', maude, maude_target, root),
        },
        'runtime_artifacts': {
            'solver_root': USER_LOCAL_SOLVER_ROOT.as_posix(),
            'tamarin_archive': _artifact_record(tamarin_archive_path, root),
            'maude_archive': _artifact_record(maude_archive_path, root),
            'maude_runtime_dir': {
                'path': DEFAULT_MAUDE_RUNTIME_DIR.as_posix(),
                'exists': DEFAULT_MAUDE_RUNTIME_DIR.is_dir(),
            },
        },
        'version_checks': {
            'maude': maude_version_check,
            'tamarin_with_maude': tamarin_version_check,
            'parsed': versions,
        },
        'minimal_theory': {
            'name': 'TamarinRuntimeSmoke',
            'source': MINIMAL_THEORY,
            'source_sha256': _sha256_text(MINIMAL_THEORY),
            'run': smoke,
            'verified': smoke_verified,
        },
        'blockers': blockers,
        'warnings': warnings,
        'summary': {
            'tamarin_present': tamarin is not None,
            'maude_present': maude is not None,
            'tamarin_version_pinned': versions['tamarin_version'] == PINNED_TAMARIN_VERSION,
            'maude_version': observed_maude,
            'maude_version_rejected': observed_maude in REJECTED_MAUDE_VERSIONS,
            'tamarin_accepts_maude': versions['tamarin_accepts_maude'],
            'minimal_theory_passed': smoke_verified,
            'blocker_count': len(blockers),
            'warning_count': len(warnings),
        },
        'overall_status': 'ready' if ready else 'blocked_runtime',
        'security_decision': 'TAMARIN_MAUDE_RUNTIME_READY' if ready else 'BLOCK_TAMARIN_MAUDE_RUNTIME_UNAVAILABLE',
        'testnet_protocol_checking_blocked_by_tamarin_runtime': not ready,
    }
    report['artifact_cid'] = _artifact_cid(report)
    return report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, default=DEFAULT_OUT)
    parser.add_argument('--tamarin-executable', type=Path)
    parser.add_argument('--maude-executable', type=Path)
    parser.add_argument('--tamarin-binary', type=Path, default=DEFAULT_TAMARIN_BINARY)
    parser.add_argument('--maude-binary', type=Path, default=DEFAULT_MAUDE_BINARY)
    parser.add_argument('--tamarin-archive', type=Path, default=DEFAULT_TAMARIN_ARCHIVE)
    parser.add_argument('--maude-archive', type=Path, default=DEFAULT_MAUDE_ARCHIVE)
    parser.add_argument('--skip-smoke', action='store_true')
    args = parser.parse_args(argv)

    report = build_tamarin_runtime_report(
        tamarin_executable=args.tamarin_executable,
        maude_executable=args.maude_executable,
        tamarin_binary=args.tamarin_binary,
        maude_binary=args.maude_binary,
        tamarin_archive=args.tamarin_archive,
        maude_archive=args.maude_archive,
        run_smoke=not args.skip_smoke,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    print(json.dumps({'out': args.out.as_posix(), 'overall_status': report['overall_status']}, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
