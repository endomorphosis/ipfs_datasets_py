#!/usr/bin/env python3
"""Plan and probe optional theorem-prover solver lanes."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
from typing import Any, Mapping, Sequence


SCHEMA_VERSION = 'optional-theorem-solver-install-report/v1'
TASK_ID = 'PORTAL-CXTP-086'
DEFAULT_SOLVER_PROBE = Path('security_ir_artifacts/environment/solver-dependency-probe.json')
DEFAULT_OUT = Path('security_ir_artifacts/environment/optional-solver-install-report.json')
POLICY_DOCUMENT = 'docs/security_verification/optional_solver_installation.md'


SOLVER_LANES: dict[str, dict[str, Any]] = {
    'apalache': {
        'executables': ['apalache-mc', 'apalache'],
        'version_args': ['version'],
        'proof_lane': 'TLA model checking',
        'install_commands': {
            'linux': [
                'cs install apalache',
                'nix profile install nixpkgs#apalache',
                'docker pull ghcr.io/apalache-mc/apalache:latest',
            ],
            'darwin': [
                'brew install apalache',
                'cs install apalache',
            ],
            'unsupported': ['Use the Apalache release artifacts or container image for this platform.'],
        },
    },
    'tamarin': {
        'executables': ['tamarin-prover'],
        'version_args': ['--version'],
        'proof_lane': 'protocol model checking',
        'install_commands': {
            'linux': [
                'nix profile install nixpkgs#tamarin-prover',
                'stack install tamarin-prover',
            ],
            'darwin': [
                'brew install tamarin-prover',
                'nix profile install nixpkgs#tamarin-prover',
            ],
            'unsupported': ['Use Tamarin upstream build instructions for this platform.'],
        },
    },
    'proverif': {
        'executables': ['proverif'],
        'version_args': ['-version'],
        'proof_lane': 'symbolic protocol verification',
        'install_commands': {
            'linux': [
                'opam install proverif',
                'nix profile install nixpkgs#proverif',
            ],
            'darwin': [
                'brew install proverif',
                'opam install proverif',
            ],
            'unsupported': ['Use ProVerif upstream or OPAM build instructions for this platform.'],
        },
    },
    'lean': {
        'executables': ['lean', 'lake'],
        'version_args_by_executable': {
            'lean': ['--version'],
            'lake': ['--version'],
        },
        'proof_lane': 'Lean proof-consumer kernel',
        'install_commands': {
            'linux': [
                'curl https://raw.githubusercontent.com/leanprover/elan/master/elan-init.sh -sSf | sh -s -- -y',
                'elan default stable',
            ],
            'darwin': [
                'brew install elan-init',
                'elan default stable',
            ],
            'unsupported': ['Install elan from https://github.com/leanprover/elan for this platform.'],
        },
    },
    'coq': {
        'executables': ['coqc'],
        'version_args': ['--version'],
        'proof_lane': 'Coq proof-kernel cross-check',
        'install_commands': {
            'linux': [
                'opam install coq',
                'nix profile install nixpkgs#coq',
                'sudo apt-get install coq',
            ],
            'darwin': [
                'brew install coq',
                'opam install coq',
            ],
            'unsupported': ['Use Coq platform packages or OPAM for this platform.'],
        },
    },
}


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding='utf-8'))
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _write_json(payload: Mapping[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + '\n', encoding='utf-8')


def _relative(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _platform_key() -> str:
    system = platform.system().lower()
    if system == 'linux':
        return 'linux'
    if system == 'darwin':
        return 'darwin'
    return 'unsupported'


def _dependency_statuses(solver_probe: Mapping[str, Any] | None) -> dict[str, dict[str, Any]]:
    deps = solver_probe.get('dependencies') if isinstance(solver_probe, Mapping) else None
    if not isinstance(deps, list):
        return {}
    return {
        str(dep.get('name')): dict(dep)
        for dep in deps
        if isinstance(dep, Mapping) and isinstance(dep.get('name'), str)
    }


def _version_command(config: Mapping[str, Any], executable_name: str, executable: str) -> list[str]:
    by_exec = config.get('version_args_by_executable')
    if isinstance(by_exec, Mapping) and executable_name in by_exec:
        return [executable, *[str(arg) for arg in by_exec[executable_name]]]
    args = config.get('version_args', ['--version'])
    return [executable, *[str(arg) for arg in args]]


def _run_version(command: Sequence[str]) -> dict[str, Any]:
    try:
        completed = subprocess.run(
            list(command),
            check=False,
            capture_output=True,
            text=True,
            timeout=8,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {'status': 'error', 'command': list(command), 'error': exc.__class__.__name__}
    version = next(
        (
            line.strip()
            for value in (completed.stdout, completed.stderr)
            for line in value.splitlines()
            if line.strip()
        ),
        None,
    )
    return {
        'status': 'present' if completed.returncode == 0 else 'error',
        'command': list(command),
        'exit_code': completed.returncode,
        'version_raw': version,
    }


def _probe_lane(name: str, config: Mapping[str, Any], *, path_env: str | None, platform_key: str) -> dict[str, Any]:
    executable_reports: list[dict[str, Any]] = []
    for executable_name in config['executables']:
        resolved = shutil.which(str(executable_name), path=path_env)
        version_report = _run_version(_version_command(config, str(executable_name), resolved)) if resolved else None
        executable_reports.append(
            {
                'name': executable_name,
                'path': resolved,
                'status': 'present' if resolved else 'missing',
                'version': version_report.get('version_raw') if version_report else None,
                'version_probe': version_report,
            }
        )

    present_count = sum(1 for item in executable_reports if item['status'] == 'present')
    required_count = len(executable_reports)
    if present_count == required_count:
        lane_status = 'ready'
        proof_acceptance = 'may_accept_reports_after_lane_specific_validation'
    elif present_count == 0:
        lane_status = 'blocked_optional_lane'
        proof_acceptance = 'do_not_accept_reports_for_missing_solver_lane'
    else:
        lane_status = 'degraded_optional_lane'
        proof_acceptance = 'do_not_accept_reports_until_all_required_tools_are_present'

    install_commands = config['install_commands'].get(platform_key) or config['install_commands']['unsupported']
    return {
        'name': name,
        'proof_lane': config['proof_lane'],
        'status': lane_status,
        'required_executables': list(config['executables']),
        'executables': executable_reports,
        'install_plan': {
            'mode': 'plan_only',
            'platform': platform_key,
            'commands': install_commands,
            'requires_manual_review': True,
            'network_access_may_be_required': True,
        },
        'proof_acceptance_policy': proof_acceptance,
    }


def build_report(
    *,
    repo_root: Path | str | None = None,
    solver_probe_path: Path | str = DEFAULT_SOLVER_PROBE,
    path_env: str | None = None,
    generated_at_utc: str | None = None,
) -> dict[str, Any]:
    root = Path(repo_root) if repo_root is not None else _repo_root()
    solver_probe_abs = Path(solver_probe_path)
    if not solver_probe_abs.is_absolute():
        solver_probe_abs = root / solver_probe_abs
    solver_probe = _load_json(solver_probe_abs)
    deps = _dependency_statuses(solver_probe)
    platform_key = _platform_key()
    path_value = path_env if path_env is not None else os.environ.get('PATH')

    lanes = [_probe_lane(name, config, path_env=path_value, platform_key=platform_key) for name, config in SOLVER_LANES.items()]
    missing_or_degraded = [lane for lane in lanes if lane['status'] != 'ready']
    present_lanes = [lane for lane in lanes if lane['status'] == 'ready']

    warnings: list[dict[str, Any]] = []
    if solver_probe is None:
        warnings.append({'code': 'SOLVER_DEPENDENCY_PROBE_MISSING', 'path': _relative(root, solver_probe_abs)})
    for lane in lanes:
        probe_status = deps.get(lane['name'], {}).get('status')
        if probe_status and probe_status != 'present' and lane['status'] == 'ready':
            warnings.append(
                {
                    'code': 'OPTIONAL_LANE_READY_BUT_BASE_PROBE_STALE',
                    'solver': lane['name'],
                    'base_probe_status': probe_status,
                }
            )

    report = {
        'schema_version': SCHEMA_VERSION,
        'task_id': TASK_ID,
        'generated_at_utc': generated_at_utc or _utc_now(),
        'policy_document': POLICY_DOCUMENT,
        'solver_probe': {
            'path': _relative(root, solver_probe_abs),
            'exists': solver_probe_abs.is_file(),
            'overall_status': solver_probe.get('overall_status') if isinstance(solver_probe, Mapping) else None,
            'security_decision': solver_probe.get('security_decision') if isinstance(solver_probe, Mapping) else None,
        },
        'installer_mode': 'plan_only',
        'platform': platform_key,
        'lanes': lanes,
        'ready_lane_count': len(present_lanes),
        'missing_or_degraded_lane_count': len(missing_or_degraded),
        'warnings': warnings,
        'warning_count': len(warnings),
        'overall_status': 'ready_with_blocked_optional_lanes' if missing_or_degraded else 'ready',
        'proof_acceptance_blocked': False,
        'security_decision': 'OPTIONAL_SOLVER_LANES_EXPLICITLY_BLOCKED_OR_READY',
    }
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='Probe optional theorem-prover lanes and emit install plans.')
    parser.add_argument('--solver-probe', default=str(DEFAULT_SOLVER_PROBE))
    parser.add_argument('--out', default=str(DEFAULT_OUT))
    parser.add_argument('--repo-root', default='.')
    args = parser.parse_args(argv)

    root = Path(args.repo_root).resolve()
    report = build_report(repo_root=root, solver_probe_path=args.solver_probe)
    out_path = Path(args.out)
    if not out_path.is_absolute():
        out_path = root / out_path
    _write_json(report, out_path)
    print(
        json.dumps(
            {
                'overall_status': report['overall_status'],
                'ready_lane_count': report['ready_lane_count'],
                'missing_or_degraded_lane_count': report['missing_or_degraded_lane_count'],
                'security_decision': report['security_decision'],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
