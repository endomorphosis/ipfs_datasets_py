#!/usr/bin/env python3
"""Remediate the required TypeScript compiler (`tsc`) dependency for crypto_exchange proofs.

`PORTAL-CXTP-058` probes the theorem-prover environment and marks a missing
`tsc` executable as a *required* blocking dependency (schemas emitted for
downstream proof consumers must type-check). This script is the
`PORTAL-CXTP-089` remediation: it provisions a reproducible, repo-scoped
TypeScript compiler under
`security_ir_artifacts/environment/typescript_toolchain/` using a pinned
`npm` install, re-resolves `tsc` (honoring an explicit `TSC_EXE` override
first), refreshes the checked-in solver dependency probe evidence, and
writes a machine-readable remediation report.

If TypeScript still cannot be resolved after remediation is attempted (for
example because `npm` itself is unavailable or the install fails), the
report and the refreshed probe both keep `proof_acceptance_blocked: true`.
Nothing in this script silently "clears" the blocker; it either produces a
working `tsc` and evidence that a real command succeeded, or it reports why
remediation failed.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
from typing import Any, Callable, Mapping, Sequence


SCHEMA_VERSION = 'crypto-exchange-typescript-dependency-remediation/v1'
TASK_ID = 'PORTAL-CXTP-089'
UPSTREAM_PROBE_TASK_ID = 'PORTAL-CXTP-058'
STABILITY_TASK_ID = 'PORTAL-CXTP-088'

DEFAULT_PROBE_IN = Path('security_ir_artifacts/environment/solver-dependency-probe.json')
DEFAULT_REPORT_OUT = Path('security_ir_artifacts/environment/typescript-remediation-report.json')
DEFAULT_TOOLCHAIN_DIR = Path('security_ir_artifacts/environment/typescript_toolchain')
DEFAULT_TYPESCRIPT_VERSION = '5.6.3'
DEFAULT_NPM_TIMEOUT_SECONDS = 300
DEFAULT_VERSION_TIMEOUT_SECONDS = 15
PROBE_SCRIPT_RELATIVE_PATH = Path('scripts/ops/security_verification/probe_theorem_prover_environment.py')
POLICY_DOCUMENT = 'docs/security_verification/typescript_solver_dependency_remediation.md'
TAIL_CHARACTER_LIMIT = 2000

CommandRunner = Callable[[Sequence[str], int], dict[str, Any]]
Which = Callable[[str], str | None]


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _relative(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _tail(value: str, limit: int = TAIL_CHARACTER_LIMIT) -> str:
    return value if len(value) <= limit else value[-limit:]


def _first_line(*values: str) -> str | None:
    for value in values:
        for line in value.splitlines():
            stripped = line.strip()
            if stripped:
                return stripped
    return None


def _version_token(raw: str | None) -> str | None:
    if not raw:
        return None
    match = re.search(r'(?<!\d)(\d+(?:\.\d+){1,3})(?!\d)', raw)
    return match.group(1) if match else None


def _default_runner(command: Sequence[str], timeout_seconds: int) -> dict[str, Any]:
    try:
        completed = subprocess.run(
            list(command),
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except FileNotFoundError as exc:
        return {'exit_code': None, 'stdout': '', 'stderr': str(exc), 'timed_out': False, 'error': 'file_not_found'}
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


def _load_probe_module(repo_root: Path | None = None):
    root = repo_root if repo_root is not None else _repo_root()
    script_path = root / PROBE_SCRIPT_RELATIVE_PATH
    if not script_path.is_file():
        # Fall back to this script's own repository location. Callers may pass
        # a synthetic `repo_root` (for example, an isolated tmp_path fixture in
        # tests) that does not contain a full checkout of the probe script.
        script_path = _repo_root() / PROBE_SCRIPT_RELATIVE_PATH
    spec = importlib.util.spec_from_file_location(
        'probe_theorem_prover_environment_for_typescript_remediation',
        script_path,
    )
    if spec is None or spec.loader is None:  # pragma: no cover - defensive
        raise RuntimeError(f'unable to load probe module from {script_path}')
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _load_json_if_exists(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        return None


def _find_dependency(probe: Mapping[str, Any] | None, name: str) -> dict[str, Any] | None:
    if not probe:
        return None
    for dependency in probe.get('dependencies', []):
        if dependency.get('name') == name:
            return dependency
    return None


def toolchain_bin_dir(toolchain_dir: Path) -> Path:
    return toolchain_dir / 'node_modules' / '.bin'


def toolchain_tsc_path(toolchain_dir: Path) -> Path:
    return toolchain_bin_dir(toolchain_dir) / 'tsc'


def _package_json_document(typescript_version: str) -> dict[str, Any]:
    return {
        'name': 'crypto-exchange-typescript-toolchain',
        'private': True,
        'version': '1.0.0',
        'description': (
            'Repo-scoped TypeScript compiler toolchain provisioned for '
            'PORTAL-CXTP-089 so crypto_exchange proof-consumer schemas can be '
            'type-checked without a machine-wide TypeScript install.'
        ),
        'devDependencies': {
            'typescript': typescript_version,
        },
    }


def ensure_package_json(toolchain_dir: Path, typescript_version: str) -> tuple[Path, bool]:
    """Write (or refresh) the pinned package.json used to install TypeScript.

    Returns (path, changed) where changed is True when the file was created or
    its pinned typescript version differed from the requested version.
    """
    toolchain_dir.mkdir(parents=True, exist_ok=True)
    package_json_path = toolchain_dir / 'package.json'
    document = _package_json_document(typescript_version)
    existing_raw = package_json_path.read_text(encoding='utf-8') if package_json_path.is_file() else None
    existing = json.loads(existing_raw) if existing_raw else None
    changed = existing is None or existing.get('devDependencies', {}).get('typescript') != typescript_version
    if changed:
        package_json_path.write_text(json.dumps(document, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    return package_json_path, changed


def resolve_npm(environ: Mapping[str, str], which: Which) -> tuple[str | None, list[str]]:
    searched = ['npm']
    resolved = which('npm')
    return resolved, searched


def resolve_tsc(
    toolchain_dir: Path,
    environ: Mapping[str, str],
    which: Which,
) -> tuple[str | None, str | None, list[str]]:
    """Resolve a usable `tsc` executable.

    Resolution order: explicit `TSC_EXE` override, the repo-scoped toolchain
    directory provisioned by this script, then `PATH`.
    """
    searched: list[str] = []
    tsc_exe = environ.get('TSC_EXE')
    if tsc_exe:
        searched.append(tsc_exe)
        if Path(tsc_exe).is_file():
            return tsc_exe, 'TSC_EXE', searched
        resolved_env = which(tsc_exe)
        if resolved_env:
            return resolved_env, 'TSC_EXE', searched

    toolchain_bin = toolchain_tsc_path(toolchain_dir)
    searched.append(toolchain_bin.as_posix())
    if toolchain_bin.is_file():
        return toolchain_bin.as_posix(), 'toolchain_dir', searched

    searched.append('tsc')
    on_path = which('tsc')
    if on_path:
        return on_path, 'PATH', searched
    return None, None, searched


def run_npm_install(
    npm_executable: str,
    toolchain_dir: Path,
    runner: CommandRunner,
    timeout_seconds: int,
) -> dict[str, Any]:
    command = [npm_executable, 'install', '--no-audit', '--no-fund', '--prefix', str(toolchain_dir)]
    start = time.monotonic()
    result = runner(command, timeout_seconds)
    duration_seconds = time.monotonic() - start
    ok = result.get('exit_code') == 0 and not result.get('timed_out')
    return {
        'action': 'npm_install',
        'status': 'ok' if ok else 'error',
        'command': command,
        'exit_code': result.get('exit_code'),
        'timed_out': bool(result.get('timed_out')),
        'error': result.get('error'),
        'duration_seconds': round(duration_seconds, 3),
        'stdout_tail': _tail(str(result.get('stdout', ''))),
        'stderr_tail': _tail(str(result.get('stderr', ''))),
    }


def verify_tsc_version(
    executable: str,
    runner: CommandRunner,
    timeout_seconds: int = DEFAULT_VERSION_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    command = [executable, '--version']
    result = runner(command, timeout_seconds)
    version_raw = _first_line(str(result.get('stdout', '')), str(result.get('stderr', '')))
    ok = result.get('exit_code') == 0 and not result.get('timed_out')
    return {
        'action': 'verify_tsc_version',
        'status': 'ok' if ok else 'error',
        'command': command,
        'exit_code': result.get('exit_code'),
        'timed_out': bool(result.get('timed_out')),
        'error': result.get('error'),
        'version_raw': version_raw,
        'version': _version_token(version_raw),
    }


def _reproduction_instructions(toolchain_dir_rel: str, typescript_version: str) -> list[str]:
    return [
        f'mkdir -p {toolchain_dir_rel}',
        (
            f'cat > {toolchain_dir_rel}/package.json <<\'JSON\'\n'
            + json.dumps(_package_json_document(typescript_version), indent=2, sort_keys=True)
            + '\nJSON'
        ),
        f'npm install --no-audit --no-fund --prefix {toolchain_dir_rel}',
        f'{toolchain_dir_rel}/node_modules/.bin/tsc --version',
        f'export TSC_EXE="$PWD/{toolchain_dir_rel}/node_modules/.bin/tsc"',
        (
            'PYTHONPATH=. python scripts/ops/security_verification/'
            'probe_theorem_prover_environment.py '
            '--out security_ir_artifacts/environment/solver-dependency-probe.json'
        ),
    ]


def provision_typescript_toolchain(
    repo_root: Path,
    probe_in_path: Path,
    toolchain_dir: Path,
    refresh_probe_out: Path | None,
    typescript_version: str = DEFAULT_TYPESCRIPT_VERSION,
    environ: Mapping[str, str] | None = None,
    runner: CommandRunner | None = None,
    which: Which | None = None,
    skip_install: bool = False,
    npm_timeout_seconds: int = DEFAULT_NPM_TIMEOUT_SECONDS,
    generated_at_utc: str | None = None,
    probe_module: Any | None = None,
) -> dict[str, Any]:
    env = dict(os.environ if environ is None else environ)
    runner_fn = _default_runner if runner is None else runner
    which_fn = shutil.which if which is None else which

    input_probe = _load_json_if_exists(probe_in_path)
    typescript_status_before = _find_dependency(input_probe, 'typescript')

    actions: list[dict[str, Any]] = []

    executable, resolved_by, searched = resolve_tsc(toolchain_dir, env, which_fn)

    if executable is not None:
        actions.append(
            {
                'action': 'check_existing_tsc',
                'status': 'already_present',
                'executable': executable,
                'resolved_by': resolved_by,
                'searched': searched,
            }
        )
        remediation_status = 'skipped_already_present'
    elif skip_install:
        actions.append({'action': 'check_existing_tsc', 'status': 'missing', 'searched': searched})
        actions.append({'action': 'npm_install', 'status': 'skipped', 'reason': 'skip_install requested'})
        remediation_status = 'skipped_install_disabled'
    else:
        actions.append({'action': 'check_existing_tsc', 'status': 'missing', 'searched': searched})
        npm_executable, npm_searched = resolve_npm(env, which_fn)
        if npm_executable is None:
            actions.append({'action': 'resolve_npm', 'status': 'missing', 'searched': npm_searched})
            remediation_status = 'failed_no_npm'
        else:
            actions.append({'action': 'resolve_npm', 'status': 'present', 'executable': npm_executable})
            package_json_path, package_json_changed = ensure_package_json(toolchain_dir, typescript_version)
            actions.append(
                {
                    'action': 'write_package_json',
                    'status': 'ok',
                    'path': _relative(package_json_path, repo_root),
                    'pinned_typescript_version': typescript_version,
                    'changed': package_json_changed,
                }
            )

            install_action = run_npm_install(npm_executable, toolchain_dir, runner_fn, npm_timeout_seconds)
            actions.append(install_action)
            install_ok = install_action['status'] == 'ok'

            executable, resolved_by, searched = resolve_tsc(toolchain_dir, env, which_fn)
            if executable is None:
                actions.append({'action': 'resolve_tsc_after_install', 'status': 'missing', 'searched': searched})
                remediation_status = 'failed_still_missing' if install_ok else 'failed_install_error'
            else:
                actions.append(
                    {
                        'action': 'resolve_tsc_after_install',
                        'status': 'present',
                        'executable': executable,
                        'resolved_by': resolved_by,
                    }
                )
                remediation_status = 'resolved'

    version_raw: str | None = None
    version: str | None = None
    verify_ok = False
    if executable is not None:
        verify_action = verify_tsc_version(executable, runner_fn)
        actions.append(verify_action)
        version_raw = verify_action['version_raw']
        version = verify_action['version']
        verify_ok = verify_action['status'] == 'ok'
        if not verify_ok and remediation_status in ('resolved', 'skipped_already_present'):
            remediation_status = 'resolved_but_unverified'

    typescript_present = executable is not None and verify_ok
    typescript_status_after = {
        'name': 'typescript',
        'display_name': 'TypeScript compiler',
        'status': 'present' if typescript_present else ('present_unverified' if executable else 'missing'),
        'executable': executable,
        'resolved_by': resolved_by,
        'version_raw': version_raw,
        'version': version,
        'blocking': not typescript_present,
    }

    refreshed_probe_summary: dict[str, Any] | None = None
    if refresh_probe_out is not None:
        module = probe_module if probe_module is not None else _load_probe_module(repo_root)
        refreshed_env = dict(env)
        bin_dir = toolchain_bin_dir(toolchain_dir).as_posix()
        refreshed_env['PATH'] = os.pathsep.join(
            part for part in (bin_dir, refreshed_env.get('PATH', '')) if part
        )
        if executable is not None and executable != 'tsc':
            refreshed_env.setdefault('TSC_EXE', executable)
        refreshed_report = module.build_probe(repo_root=repo_root, environ=refreshed_env)
        module.write_json(refreshed_report, refresh_probe_out)
        refreshed_probe_summary = {
            'path': _relative(refresh_probe_out, repo_root),
            'written': True,
            'overall_status': refreshed_report['overall_status'],
            'proof_acceptance_blocked': refreshed_report['proof_acceptance_blocked'],
            'blocking_evidence_count': refreshed_report['summary']['blocking_evidence_count'],
            'optional_capability_gap_count': refreshed_report['summary']['optional_capability_gap_count'],
        }

    if refreshed_probe_summary is not None:
        proof_acceptance_blocked = bool(refreshed_probe_summary['proof_acceptance_blocked'])
    else:
        proof_acceptance_blocked = typescript_status_after['blocking']

    if typescript_status_after['blocking']:
        security_decision = 'BLOCK_PROOF_ACCEPTANCE_TYPESCRIPT_DEPENDENCY_UNAVAILABLE'
    elif proof_acceptance_blocked:
        security_decision = 'BLOCK_PROOF_ACCEPTANCE_OTHER_REQUIRED_DEPENDENCY_MISSING'
    else:
        security_decision = 'TYPESCRIPT_DEPENDENCY_REMEDIATED'

    return {
        'schema_version': SCHEMA_VERSION,
        'task_id': TASK_ID,
        'upstream_probe_task_id': UPSTREAM_PROBE_TASK_ID,
        'stability_task_id': STABILITY_TASK_ID,
        'generated_at_utc': generated_at_utc or _utc_now(),
        'repo_root': _relative(repo_root, repo_root.parent),
        'policy_document': POLICY_DOCUMENT,
        'input_probe_path': _relative(probe_in_path, repo_root),
        'input_probe_found': input_probe is not None,
        'typescript_status_before': typescript_status_before,
        'remediation_strategy': 'repo_scoped_npm_install',
        'toolchain': {
            'toolchain_dir': _relative(toolchain_dir, repo_root),
            'package_json_path': _relative(toolchain_dir / 'package.json', repo_root),
            'bin_path': _relative(toolchain_tsc_path(toolchain_dir), repo_root),
            'pinned_typescript_version': typescript_version,
            'override_env_var': 'TSC_EXE',
        },
        'remediation_actions': actions,
        'remediation_status': remediation_status,
        'typescript_status_after': typescript_status_after,
        'refreshed_probe': refreshed_probe_summary,
        'overall_status': 'blocked' if proof_acceptance_blocked else 'remediated',
        'proof_acceptance_blocked': proof_acceptance_blocked,
        'security_decision': security_decision,
        'reproduction_instructions': _reproduction_instructions(
            _relative(toolchain_dir, repo_root), typescript_version
        ),
    }


def write_json(document: dict[str, Any], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(document, indent=2, sort_keys=True) + '\n', encoding='utf-8')


def _resolve_path(value: str, repo_root: Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else repo_root / path


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            'Provision a reproducible, repo-scoped TypeScript compiler and refresh '
            'the crypto_exchange solver dependency probe evidence.'
        )
    )
    parser.add_argument('--repo-root', default=str(_repo_root()), help='repository root to operate on')
    parser.add_argument(
        '--probe',
        default=DEFAULT_PROBE_IN.as_posix(),
        help='input solver dependency probe JSON path (baseline evidence from PORTAL-CXTP-058)',
    )
    parser.add_argument(
        '--out',
        default=DEFAULT_REPORT_OUT.as_posix(),
        help='remediation report JSON path to write',
    )
    parser.add_argument(
        '--toolchain-dir',
        default=DEFAULT_TOOLCHAIN_DIR.as_posix(),
        help='repo-scoped directory used to install the TypeScript compiler',
    )
    parser.add_argument(
        '--typescript-version',
        default=DEFAULT_TYPESCRIPT_VERSION,
        help='pinned npm typescript package version to install',
    )
    parser.add_argument(
        '--refresh-probe-out',
        default=None,
        help='path to (re)write refreshed solver dependency probe evidence (defaults to --probe)',
    )
    parser.add_argument(
        '--skip-refresh-probe',
        action='store_true',
        help='do not refresh the solver dependency probe evidence',
    )
    parser.add_argument(
        '--skip-install',
        action='store_true',
        help='only check for an existing tsc; do not attempt npm install',
    )
    parser.add_argument(
        '--npm-timeout-seconds',
        type=int,
        default=DEFAULT_NPM_TIMEOUT_SECONDS,
        help='timeout in seconds for the npm install command',
    )
    parser.add_argument(
        '--fail-on-blocking',
        action='store_true',
        help='exit non-zero when proof acceptance remains blocked after remediation',
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    repo_root = Path(args.repo_root)
    probe_in_path = _resolve_path(args.probe, repo_root)
    report_out_path = _resolve_path(args.out, repo_root)
    toolchain_dir = _resolve_path(args.toolchain_dir, repo_root)
    refresh_probe_out = None
    if not args.skip_refresh_probe:
        refresh_target = args.refresh_probe_out if args.refresh_probe_out is not None else args.probe
        refresh_probe_out = _resolve_path(refresh_target, repo_root)

    report = provision_typescript_toolchain(
        repo_root=repo_root,
        probe_in_path=probe_in_path,
        toolchain_dir=toolchain_dir,
        refresh_probe_out=refresh_probe_out,
        typescript_version=args.typescript_version,
        skip_install=args.skip_install,
        npm_timeout_seconds=args.npm_timeout_seconds,
    )
    write_json(report, report_out_path)
    print(
        json.dumps(
            {
                'out': _relative(report_out_path, repo_root),
                'schema_version': report['schema_version'],
                'remediation_status': report['remediation_status'],
                'overall_status': report['overall_status'],
                'proof_acceptance_blocked': report['proof_acceptance_blocked'],
                'security_decision': report['security_decision'],
            },
            sort_keys=True,
        )
    )
    if args.fail_on_blocking and report['proof_acceptance_blocked']:
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
