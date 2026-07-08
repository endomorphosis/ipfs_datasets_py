#!/usr/bin/env python3
"""Probe theorem-prover dependencies for crypto_exchange proof evidence."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
from typing import Any, Callable, Mapping, Sequence


SCHEMA_VERSION = 'crypto-exchange-solver-dependency-probe/v1'
TASK_ID = 'PORTAL-CXTP-058'
DEFAULT_OUT = Path('security_ir_artifacts/environment/solver-dependency-probe.json')
DEFAULT_TIMEOUT_SECONDS = 8


@dataclass(frozen=True)
class DependencySpec:
    name: str
    display_name: str
    category: str
    required: bool
    candidates: tuple[str, ...]
    version_args: tuple[str, ...]
    capability: str
    env_var: str | None = None
    minimum_version: str | None = None


@dataclass(frozen=True)
class EnvVarSpec:
    name: str
    required: bool
    purpose: str
    path_like: bool = False


DEPENDENCIES: tuple[DependencySpec, ...] = (
    DependencySpec(
        name='python',
        display_name='Python',
        category='runtime',
        required=True,
        candidates=('python3', 'python'),
        version_args=('--version',),
        capability='Run security verification scripts and pytest-based proof gates.',
        minimum_version='3.10',
    ),
    DependencySpec(
        name='node',
        display_name='Node.js',
        category='runtime',
        required=True,
        candidates=('node',),
        version_args=('--version',),
        capability='Compile and validate TypeScript proof-consumer schemas.',
    ),
    DependencySpec(
        name='npm',
        display_name='npm',
        category='runtime',
        required=True,
        candidates=('npm',),
        version_args=('--version',),
        capability='Resolve JavaScript/TypeScript proof-consumer tooling.',
    ),
    DependencySpec(
        name='typescript',
        display_name='TypeScript compiler',
        category='runtime',
        required=True,
        candidates=('tsc',),
        version_args=('--version',),
        capability='Type-check emitted security proof schemas consumed by downstream clients.',
    ),
    DependencySpec(
        name='z3',
        display_name='Z3',
        category='smt_solver',
        required=True,
        candidates=('z3',),
        version_args=('--version',),
        capability='Primary SMT proof and disproof backend for crypto_exchange claims.',
        env_var='Z3_EXE',
    ),
    DependencySpec(
        name='cvc5',
        display_name='CVC5',
        category='smt_solver',
        required=True,
        candidates=('cvc5',),
        version_args=('--version',),
        capability='Required independent SMT differential backend for proof promotion.',
        env_var='CVC5_EXE',
    ),
    DependencySpec(
        name='apalache',
        display_name='Apalache',
        category='model_checker',
        required=False,
        candidates=('apalache-mc', 'apalache'),
        version_args=('version',),
        capability='Optional TLA+ workflow and interleaving model-checking coverage.',
        env_var='APALACHE_EXE',
    ),
    DependencySpec(
        name='tamarin',
        display_name='Tamarin Prover',
        category='protocol_prover',
        required=False,
        candidates=('tamarin-prover',),
        version_args=('--version',),
        capability='Optional protocol proof coverage for key custody and signing authority.',
        env_var='TAMARIN_EXE',
    ),
    DependencySpec(
        name='proverif',
        display_name='ProVerif',
        category='protocol_prover',
        required=False,
        candidates=('proverif',),
        version_args=('-version',),
        capability='Optional protocol proof coverage for replay and secrecy properties.',
        env_var='PROVERIF_EXE',
    ),
    DependencySpec(
        name='lean',
        display_name='Lean',
        category='proof_assistant',
        required=False,
        candidates=('lean',),
        version_args=('--version',),
        capability='Optional proof-consumer invariant checking in Lean.',
        env_var='LEAN_EXE',
    ),
    DependencySpec(
        name='coq',
        display_name='Coq',
        category='proof_assistant',
        required=False,
        candidates=('coqc',),
        version_args=('--version',),
        capability='Optional proof-consumer invariant checking in Coq.',
        env_var='COQC_EXE',
    ),
)


ENV_VARS: tuple[EnvVarSpec, ...] = (
    EnvVarSpec(
        name='PATH',
        required=True,
        purpose='Executable discovery path for Python, Node, SMT solvers, and proof assistants.',
        path_like=True,
    ),
    EnvVarSpec(
        name='PYTHONPATH',
        required=True,
        purpose='Repository import path used by the security verification validation commands.',
        path_like=True,
    ),
    EnvVarSpec(
        name='JAVA_HOME',
        required=False,
        purpose='JVM root used by Apalache and related model-checking tools when installed.',
        path_like=True,
    ),
    EnvVarSpec(
        name='Z3_EXE',
        required=False,
        purpose='Explicit Z3 executable override for reproducible proof runners.',
        path_like=True,
    ),
    EnvVarSpec(
        name='CVC5_EXE',
        required=False,
        purpose='Explicit CVC5 executable override for differential SMT runners.',
        path_like=True,
    ),
    EnvVarSpec(
        name='APALACHE_EXE',
        required=False,
        purpose='Explicit Apalache executable override for TLA+ model checking.',
        path_like=True,
    ),
    EnvVarSpec(
        name='TAMARIN_EXE',
        required=False,
        purpose='Explicit Tamarin executable override for protocol proofs.',
        path_like=True,
    ),
    EnvVarSpec(
        name='PROVERIF_EXE',
        required=False,
        purpose='Explicit ProVerif executable override for protocol proofs.',
        path_like=True,
    ),
    EnvVarSpec(
        name='LEAN_EXE',
        required=False,
        purpose='Explicit Lean executable override for proof-assistant checks.',
        path_like=True,
    ),
    EnvVarSpec(
        name='COQC_EXE',
        required=False,
        purpose='Explicit Coq compiler override for proof-assistant checks.',
        path_like=True,
    ),
    EnvVarSpec(
        name='COQPATH',
        required=False,
        purpose='Additional Coq library search path for proof-consumer checks.',
        path_like=True,
    ),
    EnvVarSpec(
        name='LEAN_PATH',
        required=False,
        purpose='Additional Lean library search path for proof-consumer checks.',
        path_like=True,
    ),
)


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


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


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


def _env_value_entry(spec: EnvVarSpec, environ: Mapping[str, str]) -> dict[str, Any]:
    value = environ.get(spec.name)
    present = value is not None and value != ''
    entry: dict[str, Any] = {
        'name': spec.name,
        'required': spec.required,
        'purpose': spec.purpose,
        'present': present,
        'status': 'present' if present else 'missing',
    }
    if present:
        entry['value_sha256'] = _sha256_text(value)
        entry['length'] = len(value)
        if spec.path_like:
            entry['entry_count'] = len([part for part in value.split(os.pathsep) if part])
    if spec.required and not present:
        entry['blocking'] = True
    return entry


def probe_env_vars(environ: Mapping[str, str] | None = None) -> list[dict[str, Any]]:
    env = os.environ if environ is None else environ
    return [_env_value_entry(spec, env) for spec in ENV_VARS]


def _candidate_from_env(spec: DependencySpec, environ: Mapping[str, str]) -> str | None:
    if spec.env_var is None:
        return None
    value = environ.get(spec.env_var)
    return value if value else None


def _resolve_executable(
    spec: DependencySpec,
    environ: Mapping[str, str],
    which: Which | None = None,
) -> tuple[str | None, str | None, list[str]]:
    which_fn = shutil.which if which is None else which
    searched: list[str] = []
    env_candidate = _candidate_from_env(spec, environ)
    if env_candidate:
        searched.append(env_candidate)
        if Path(env_candidate).is_file():
            return env_candidate, spec.env_var, searched
        resolved_env = which_fn(env_candidate)
        if resolved_env:
            return resolved_env, spec.env_var, searched

    if spec.name == 'python':
        return sys.executable, None, [sys.executable]

    for candidate in spec.candidates:
        searched.append(candidate)
        resolved = which_fn(candidate)
        if resolved:
            return resolved, None, searched
    return None, None, searched


def _dependency_status(
    spec: DependencySpec,
    executable: str | None,
    result: dict[str, Any] | None,
) -> str:
    if executable is None:
        return 'missing'
    if result is None:
        return 'error'
    if result.get('timed_out'):
        return 'error'
    if result.get('exit_code') == 0:
        return 'present'
    return 'error'


def probe_dependency(
    spec: DependencySpec,
    environ: Mapping[str, str] | None = None,
    runner: CommandRunner | None = None,
    which: Which | None = None,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    env = os.environ if environ is None else environ
    runner_fn = _default_runner if runner is None else runner
    executable, resolved_by, searched = _resolve_executable(spec, env, which)
    command = [executable, *spec.version_args] if executable else None
    command_result = runner_fn(command, timeout_seconds) if command else None
    raw_version = _first_line(
        str(command_result.get('stdout', '')) if command_result else '',
        str(command_result.get('stderr', '')) if command_result else '',
    )
    status = _dependency_status(spec, executable, command_result)

    entry: dict[str, Any] = {
        'name': spec.name,
        'display_name': spec.display_name,
        'category': spec.category,
        'required': spec.required,
        'capability': spec.capability,
        'minimum_version': spec.minimum_version,
        'status': status,
        'blocking': spec.required and status != 'present',
        'capability_gap': (not spec.required) and status != 'present',
        'executable': executable,
        'resolved_by_env_var': resolved_by,
        'searched_names': searched,
        'command': command,
        'version_raw': raw_version,
        'version': _version_token(raw_version),
    }

    if command_result is not None:
        entry['command_result'] = {
            'exit_code': command_result.get('exit_code'),
            'timed_out': bool(command_result.get('timed_out')),
            'error': command_result.get('error'),
            'stdout_first_line': _first_line(str(command_result.get('stdout', ''))),
            'stderr_first_line': _first_line(str(command_result.get('stderr', ''))),
        }
    return entry


def probe_dependencies(
    environ: Mapping[str, str] | None = None,
    runner: CommandRunner | None = None,
    which: Which | None = None,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
) -> list[dict[str, Any]]:
    return [
        probe_dependency(
            spec,
            environ=environ,
            runner=runner,
            which=which,
            timeout_seconds=timeout_seconds,
        )
        for spec in DEPENDENCIES
    ]


def probe_os() -> dict[str, Any]:
    uname = platform.uname()
    return {
        'system': uname.system,
        'node': uname.node,
        'release': uname.release,
        'version': uname.version,
        'machine': uname.machine,
        'processor': uname.processor,
        'platform': platform.platform(),
        'libc': platform.libc_ver(),
    }


def _linux_cpuinfo() -> dict[str, Any]:
    cpuinfo = Path('/proc/cpuinfo')
    if not cpuinfo.is_file():
        return {}
    model_name: str | None = None
    flags: set[str] = set()
    physical_ids: set[str] = set()
    core_ids: set[tuple[str, str]] = set()
    for line in cpuinfo.read_text(encoding='utf-8', errors='replace').splitlines():
        if ':' not in line:
            continue
        key, value = (part.strip() for part in line.split(':', 1))
        if key == 'model name' and model_name is None:
            model_name = value
        elif key == 'flags':
            flags.update(value.split())
        elif key == 'physical id':
            physical_ids.add(value)
        elif key == 'core id':
            core_ids.add((next(iter(physical_ids), 'unknown'), value))
    result: dict[str, Any] = {}
    if model_name:
        result['model_name'] = model_name
    if flags:
        selected_flags = ('aes', 'avx', 'avx2', 'sha_ni', 'sse4_2', 'vmx', 'svm')
        result['selected_flags'] = sorted(flag for flag in selected_flags if flag in flags)
    if physical_ids:
        result['physical_package_count'] = len(physical_ids)
    if core_ids:
        result['observed_core_id_count'] = len(core_ids)
    return result


def probe_cpu() -> dict[str, Any]:
    return {
        'architecture': platform.architecture(),
        'machine': platform.machine(),
        'processor': platform.processor(),
        'logical_cpu_count': os.cpu_count(),
        'linux_cpuinfo': _linux_cpuinfo(),
    }


def _blocking_evidence(
    dependencies: Sequence[dict[str, Any]],
    env_vars: Sequence[dict[str, Any]],
) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    for dependency in dependencies:
        if not dependency.get('blocking'):
            continue
        code = (
            'REQUIRED_DEPENDENCY_MISSING'
            if dependency.get('status') == 'missing'
            else 'REQUIRED_DEPENDENCY_UNUSABLE'
        )
        blockers.append(
            {
                'code': code,
                'component': dependency['name'],
                'display_name': dependency['display_name'],
                'category': dependency['category'],
                'status': dependency['status'],
                'capability': dependency['capability'],
                'remediation': f'Install {dependency["display_name"]} and ensure it is available on PATH.',
            }
        )
    for env_var in env_vars:
        if env_var.get('blocking'):
            blockers.append(
                {
                    'code': 'REQUIRED_ENV_VAR_MISSING',
                    'component': env_var['name'],
                    'status': env_var['status'],
                    'purpose': env_var['purpose'],
                    'remediation': f'Set {env_var["name"]} before running proof gates.',
                }
            )
    return blockers


def _capability_gaps(dependencies: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    gaps: list[dict[str, Any]] = []
    for dependency in dependencies:
        if not dependency.get('capability_gap'):
            continue
        code = (
            'OPTIONAL_DEPENDENCY_MISSING'
            if dependency.get('status') == 'missing'
            else 'OPTIONAL_DEPENDENCY_UNUSABLE'
        )
        gaps.append(
            {
                'code': code,
                'component': dependency['name'],
                'display_name': dependency['display_name'],
                'category': dependency['category'],
                'status': dependency['status'],
                'capability': dependency['capability'],
                'impact': 'Capability unavailable; do not claim this prover coverage for release evidence.',
            }
        )
    return gaps


def build_probe(
    repo_root: Path | str | None = None,
    environ: Mapping[str, str] | None = None,
    runner: CommandRunner | None = None,
    which: Which | None = None,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    generated_at_utc: str | None = None,
) -> dict[str, Any]:
    root = Path(repo_root) if repo_root is not None else _repo_root()
    env = os.environ if environ is None else environ
    dependencies = probe_dependencies(env, runner, which, timeout_seconds)
    env_vars = probe_env_vars(env)
    blockers = _blocking_evidence(dependencies, env_vars)
    capability_gaps = _capability_gaps(dependencies)
    blocked = bool(blockers)

    required_dependencies = [dependency for dependency in dependencies if dependency['required']]
    present_required_dependencies = [
        dependency for dependency in required_dependencies if dependency['status'] == 'present'
    ]

    return {
        'schema_version': SCHEMA_VERSION,
        'task_id': TASK_ID,
        'generated_at_utc': generated_at_utc or _utc_now(),
        'repo_root': _relative(root, root.parent),
        'probe_script': 'scripts/ops/security_verification/probe_theorem_prover_environment.py',
        'policy_document': 'docs/security_verification/solver_dependency_bootstrap.md',
        'overall_status': 'blocked' if blocked else 'ready',
        'proof_acceptance_blocked': blocked,
        'security_decision': (
            'BLOCK_PROOF_ACCEPTANCE_MISSING_SOLVER_DEPENDENCY'
            if blocked
            else (
                'SOLVER_DEPENDENCY_ENVIRONMENT_READY_WITH_CAPABILITY_GAPS'
                if capability_gaps
                else 'SOLVER_DEPENDENCY_ENVIRONMENT_READY'
            )
        ),
        'summary': {
            'dependency_count': len(dependencies),
            'required_dependency_count': len(required_dependencies),
            'present_required_dependency_count': len(present_required_dependencies),
            'blocking_evidence_count': len(blockers),
            'optional_capability_gap_count': len(capability_gaps),
            'env_var_count': len(env_vars),
            'required_env_var_count': len([entry for entry in env_vars if entry['required']]),
        },
        'os': probe_os(),
        'cpu': probe_cpu(),
        'dependencies': dependencies,
        'environment_variables': env_vars,
        'blocking_evidence': blockers,
        'optional_capability_gaps': capability_gaps,
    }


def write_json(document: dict[str, Any], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(document, indent=2, sort_keys=True) + '\n', encoding='utf-8')


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description='Probe crypto_exchange theorem-prover dependency availability.'
    )
    parser.add_argument('--repo-root', default=str(_repo_root()), help='repository root to describe')
    parser.add_argument('--out', default=DEFAULT_OUT.as_posix(), help='probe report JSON path')
    parser.add_argument(
        '--timeout-seconds',
        type=int,
        default=DEFAULT_TIMEOUT_SECONDS,
        help='per-command timeout for version probes',
    )
    parser.add_argument(
        '--fail-on-blocking',
        action='store_true',
        help='exit non-zero when required dependencies or required env vars are missing',
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    repo_root = Path(args.repo_root)
    out_path = Path(args.out)
    if not out_path.is_absolute():
        out_path = repo_root / out_path

    report = build_probe(repo_root=repo_root, timeout_seconds=args.timeout_seconds)
    write_json(report, out_path)
    print(
        json.dumps(
            {
                'out': _relative(out_path, repo_root),
                'schema_version': report['schema_version'],
                'overall_status': report['overall_status'],
                'proof_acceptance_blocked': report['proof_acceptance_blocked'],
                'blocking_evidence_count': report['summary']['blocking_evidence_count'],
                'optional_capability_gap_count': report['summary']['optional_capability_gap_count'],
            },
            sort_keys=True,
        )
    )
    if args.fail_on_blocking and report['proof_acceptance_blocked']:
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
