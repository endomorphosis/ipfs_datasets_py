#!/usr/bin/env python3
"""Remediate the required TypeScript compiler dependency for crypto_exchange.

PORTAL-CXTP-089 uses a repo-scoped TypeScript toolchain instead of requiring a
global npm install. The script verifies the local ``tsc`` executable, prepends
its directory to ``PATH`` for the solver dependency probe, refreshes the probe
artifact, and writes a remediation report that records whether the required
TypeScript blocker was removed.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from typing import Any, Callable, Mapping, Sequence


SCHEMA_VERSION = 'crypto-exchange-typescript-remediation/v1'
TASK_ID = 'PORTAL-CXTP-089'
DEFAULT_PROBE = Path('security_ir_artifacts/environment/solver-dependency-probe.json')
DEFAULT_OUT = Path('security_ir_artifacts/environment/typescript-remediation-report.json')
DEFAULT_TOOLCHAIN_DIR = Path('security_ir_artifacts/environment/typescript_toolchain')
POLICY_DOCUMENT = 'docs/security_verification/typescript_solver_dependency_remediation.md'
PROBE_SCRIPT = Path('scripts/ops/security_verification/probe_theorem_prover_environment.py')
TSC_RELATIVE_PATH = Path('node_modules/.bin/tsc')
DEFAULT_TIMEOUT_SECONDS = 10

CommandRunner = Callable[[Sequence[str], int, Mapping[str, str]], dict[str, Any]]
ProbeBuilder = Callable[..., dict[str, Any]]


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')


def _relative(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _sha256_file(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


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


def _write_json(document: Mapping[str, Any], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(document, indent=2, sort_keys=True) + '\n', encoding='utf-8')


def _default_runner(
    command: Sequence[str],
    timeout_seconds: int,
    environ: Mapping[str, str],
) -> dict[str, Any]:
    try:
        completed = subprocess.run(
            list(command),
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            env=dict(environ),
        )
    except FileNotFoundError as exc:
        return {
            'exit_code': None,
            'stdout': '',
            'stderr': str(exc),
            'timed_out': False,
            'error': 'file_not_found',
        }
    except subprocess.TimeoutExpired as exc:
        return {
            'exit_code': None,
            'stdout': exc.stdout or '',
            'stderr': exc.stderr or '',
            'timed_out': True,
            'error': 'timeout',
        }
    except OSError as exc:
        return {
            'exit_code': None,
            'stdout': '',
            'stderr': str(exc),
            'timed_out': False,
            'error': exc.__class__.__name__,
        }
    return {
        'exit_code': completed.returncode,
        'stdout': completed.stdout,
        'stderr': completed.stderr,
        'timed_out': False,
        'error': None,
    }


def _first_line(*values: Any) -> str | None:
    for value in values:
        for line in str(value or '').splitlines():
            stripped = line.strip()
            if stripped:
                return stripped
    return None


def _version_token(raw: str | None) -> str | None:
    if not raw:
        return None
    match = re.search(r'(?<!\d)(\d+(?:\.\d+){1,3})(?!\d)', raw)
    return match.group(1) if match else None


def _load_probe_builder(repo_root: Path) -> ProbeBuilder:
    script = repo_root / PROBE_SCRIPT
    spec = importlib.util.spec_from_file_location('probe_theorem_prover_environment', script)
    if spec is None or spec.loader is None:
        raise RuntimeError(f'failed to load {script.as_posix()}')
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.build_probe


def _dependency_by_name(probe: Mapping[str, Any] | None, name: str) -> dict[str, Any] | None:
    if not probe:
        return None
    dependencies = probe.get('dependencies')
    if not isinstance(dependencies, list):
        return None
    for dependency in dependencies:
        if isinstance(dependency, dict) and dependency.get('name') == name:
            return dependency
    return None


def _blocking_components(probe: Mapping[str, Any] | None) -> list[str]:
    if not probe:
        return []
    blockers = probe.get('blocking_evidence')
    if not isinstance(blockers, list):
        return []
    return sorted(
        str(blocker.get('component'))
        for blocker in blockers
        if isinstance(blocker, Mapping) and blocker.get('component')
    )


def _path_with_toolchain(environ: Mapping[str, str], tsc_dir: Path) -> str:
    existing = environ.get('PATH', '')
    parts = [tsc_dir.as_posix()]
    parts.extend(part for part in existing.split(os.pathsep) if part)
    return os.pathsep.join(parts)


def build_report(
    *,
    repo_root: Path | str | None = None,
    probe_path: Path | str = DEFAULT_PROBE,
    toolchain_dir: Path | str = DEFAULT_TOOLCHAIN_DIR,
    environ: Mapping[str, str] | None = None,
    runner: CommandRunner | None = None,
    probe_builder: ProbeBuilder | None = None,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    generated_at_utc: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    root = Path(repo_root) if repo_root is not None else _repo_root()
    env = dict(os.environ if environ is None else environ)
    runner_fn = _default_runner if runner is None else runner
    probe_abs = Path(probe_path)
    toolchain_abs = Path(toolchain_dir)
    if not probe_abs.is_absolute():
        probe_abs = root / probe_abs
    if not toolchain_abs.is_absolute():
        toolchain_abs = root / toolchain_abs

    existing_probe = _load_json(probe_abs)
    tsc_path = toolchain_abs / TSC_RELATIVE_PATH
    tsc_dir = tsc_path.parent
    remediated_env = {**env, 'PATH': _path_with_toolchain(env, tsc_dir)}
    command = [tsc_path.as_posix(), '--version']
    command_result = runner_fn(command, timeout_seconds, remediated_env) if tsc_path.is_file() else None
    version_raw = _first_line(
        command_result.get('stdout') if command_result else '',
        command_result.get('stderr') if command_result else '',
    )
    tsc_status = (
        'present'
        if command_result is not None
        and command_result.get('exit_code') == 0
        and not command_result.get('timed_out')
        else 'missing'
        if not tsc_path.is_file()
        else 'error'
    )

    refreshed_probe: dict[str, Any] | None = None
    refresh_error: str | None = None
    if tsc_status == 'present':
        try:
            builder = probe_builder if probe_builder is not None else _load_probe_builder(root)
            refreshed_probe = builder(
                repo_root=root,
                environ=remediated_env,
                which=lambda candidate: shutil.which(candidate, path=remediated_env.get('PATH', '')),
                timeout_seconds=timeout_seconds,
                generated_at_utc=generated_at_utc or _utc_now(),
            )
        except Exception as exc:  # pragma: no cover - defensive runtime guard
            refresh_error = f'{exc.__class__.__name__}: {exc}'

    before = _dependency_by_name(existing_probe, 'typescript')
    after = _dependency_by_name(refreshed_probe, 'typescript')
    before_status = before.get('status') if before else None
    after_status = after.get('status') if after else None
    after_blockers = _blocking_components(refreshed_probe)
    typescript_blocker_removed = after_status == 'present' and 'typescript' not in after_blockers
    ready = tsc_status == 'present' and typescript_blocker_removed and refresh_error is None

    blockers: list[dict[str, Any]] = []
    if not tsc_path.is_file():
        blockers.append(
            {
                'code': 'REPO_SCOPED_TSC_MISSING',
                'path': _relative(tsc_path, root),
                'remediation': 'Run npm install --prefix security_ir_artifacts/environment/typescript_toolchain typescript@5.5.4 after review.',
            }
        )
    elif tsc_status != 'present':
        blockers.append(
            {
                'code': 'REPO_SCOPED_TSC_UNUSABLE',
                'path': _relative(tsc_path, root),
                'command_result': command_result,
            }
        )
    if refresh_error:
        blockers.append({'code': 'SOLVER_DEPENDENCY_PROBE_REFRESH_FAILED', 'error': refresh_error})
    if refreshed_probe is not None and 'typescript' in after_blockers:
        blockers.append({'code': 'TYPESCRIPT_BLOCKER_STILL_PRESENT', 'blocking_components': after_blockers})

    report = {
        'schema_version': SCHEMA_VERSION,
        'task_id': TASK_ID,
        'generated_at_utc': generated_at_utc or _utc_now(),
        'policy_document': POLICY_DOCUMENT,
        'repo_root': root.as_posix(),
        'overall_status': 'ready' if ready else 'blocked',
        'proof_acceptance_blocked': bool(refreshed_probe.get('proof_acceptance_blocked')) if refreshed_probe else True,
        'security_decision': (
            'TYPESCRIPT_DEPENDENCY_REMEDIATED'
            if ready
            else 'BLOCK_TYPESCRIPT_DEPENDENCY_REMEDIATION'
        ),
        'typescript': {
            'toolchain_dir': _relative(toolchain_abs, root),
            'tsc_path': _relative(tsc_path, root),
            'tsc_sha256': _sha256_file(tsc_path),
            'status': tsc_status,
            'version_raw': version_raw,
            'version': _version_token(version_raw),
            'command': command,
            'command_result': {
                'exit_code': command_result.get('exit_code') if command_result else None,
                'timed_out': bool(command_result.get('timed_out')) if command_result else False,
                'error': command_result.get('error') if command_result else None,
                'stdout_first_line': _first_line(command_result.get('stdout', '')) if command_result else None,
                'stderr_first_line': _first_line(command_result.get('stderr', '')) if command_result else None,
            },
        },
        'probe_refresh': {
            'probe_path': _relative(probe_abs, root),
            'probe_existed_before': existing_probe is not None,
            'path_prepend': _relative(tsc_dir, root),
            'typescript_status_before': before_status,
            'typescript_status_after': after_status,
            'blocking_components_after': after_blockers,
            'proof_acceptance_blocked_after': refreshed_probe.get('proof_acceptance_blocked') if refreshed_probe else None,
            'refresh_error': refresh_error,
        },
        'operator_environment': {
            'path_prepend_command': f'export PATH="{_relative(tsc_dir, root)}:$PATH"',
            'validation_command': (
                'PYTHONPATH=. /home/barberb/miniforge3/bin/python '
                'scripts/ops/security_verification/provision_required_typescript_toolchain.py '
                '--probe security_ir_artifacts/environment/solver-dependency-probe.json '
                '--out security_ir_artifacts/environment/typescript-remediation-report.json'
            ),
        },
        'summary': {
            'typescript_blocker_removed': typescript_blocker_removed,
            'required_blocking_components_remaining': after_blockers,
            'optional_capability_gap_count': len(refreshed_probe.get('optional_capability_gaps', []))
            if refreshed_probe
            else None,
        },
        'blockers': blockers,
    }
    report['artifact_cid'] = _artifact_cid(report)
    return report, refreshed_probe


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Provision repo-scoped TypeScript compiler evidence.')
    parser.add_argument('--repo-root', default=_repo_root().as_posix(), help='repository root')
    parser.add_argument(
        '--probe',
        default=DEFAULT_PROBE.as_posix(),
        help='solver dependency probe path to read and refresh',
    )
    parser.add_argument(
        '--toolchain-dir',
        default=DEFAULT_TOOLCHAIN_DIR.as_posix(),
        help='repo-scoped TypeScript toolchain directory',
    )
    parser.add_argument('--out', default=DEFAULT_OUT.as_posix(), help='remediation report output path')
    parser.add_argument(
        '--timeout-seconds',
        type=int,
        default=DEFAULT_TIMEOUT_SECONDS,
        help='timeout for tsc and dependency probes',
    )
    parser.add_argument(
        '--no-refresh-probe',
        action='store_true',
        help='write only the remediation report and do not overwrite the probe artifact',
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    root = Path(args.repo_root)
    probe_path = Path(args.probe)
    if not probe_path.is_absolute():
        probe_path = root / probe_path
    out_path = Path(args.out)
    if not out_path.is_absolute():
        out_path = root / out_path

    report, refreshed_probe = build_report(
        repo_root=root,
        probe_path=probe_path,
        toolchain_dir=args.toolchain_dir,
        timeout_seconds=args.timeout_seconds,
    )
    if refreshed_probe is not None and not args.no_refresh_probe:
        _write_json(refreshed_probe, probe_path)
    _write_json(report, out_path)
    print(
        json.dumps(
            {
                'report': _relative(out_path, root),
                'probe': _relative(probe_path, root),
                'overall_status': report['overall_status'],
                'typescript_status': report['typescript']['status'],
                'typescript_version': report['typescript']['version'],
                'typescript_blocker_removed': report['summary']['typescript_blocker_removed'],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == '__main__':  # pragma: no cover
    raise SystemExit(main())
