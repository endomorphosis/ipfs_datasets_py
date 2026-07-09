#!/usr/bin/env python3
"""Probe the optional Lean proof-consumer solver lane.

PORTAL-CXTP-090 keeps Lean proof-consumer coverage explicit.  Missing Lean
does not silently accept proof receipts; it produces a degraded optional lane on
supported hosts.  A discovered but unusable Lean install blocks the lane until
the executable, toolchain, or proof kernel is fixed.
"""

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


SCHEMA_VERSION = 'crypto-exchange-lean-solver-lane-report/v1'
TASK_ID = 'PORTAL-CXTP-090'
LANE_ID = 'lean_proof_consumer_invariants'
LANE_NAME = 'Lean proof-consumer invariant checks'
DEFAULT_OUT = Path('security_ir_artifacts/environment/lean-solver-lane-report.json')
POLICY_DOCUMENT = 'docs/security_verification/lean_proof_consumer_solver_lane.md'
OPTIONAL_INSTALLER_DOCUMENT = 'docs/security_verification/optional_solver_installation.md'
PROOF_CONSUMER_DOCUMENT = 'docs/security_verification/xaman_proof_consumer_invariants.md'
PROOF_KERNEL_PATH = Path('security_ir_artifacts/corpora/xaman-app/proof-kernel/XamanReceipt.lean')
PROOF_CONSUMER_REPORT_PATH = Path(
    'security_ir_artifacts/corpora/xaman-app/proof-kernel/proof-consumer-report.json'
)
DEFAULT_TIMEOUT_SECONDS = 8
PINNED_LEAN_TOOLCHAIN = 'leanprover/lean4:v4.31.0'
SUPPORTED_SYSTEMS = {'linux', 'darwin'}
SUPPORTED_MACHINES = {'x86_64', 'amd64', 'aarch64', 'arm64'}

CommandRunner = Callable[[Sequence[str], int], dict[str, Any]]
Which = Callable[[str], str | None]


@dataclass(frozen=True)
class CommandPlan:
    step: str
    command: str
    purpose: str
    requires_network: bool = False
    requires_privilege: bool = False
    destructive: bool = False
    review_required: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            'step': self.step,
            'command': self.command,
            'purpose': self.purpose,
            'requires_network': self.requires_network,
            'requires_privilege': self.requires_privilege,
            'destructive': self.destructive,
            'review_required': self.review_required,
        }


INSTALL_COMMANDS: tuple[CommandPlan, ...] = (
    CommandPlan(
        step='install-elan-reviewed-script',
        command=(
            'curl -fsSLo /tmp/elan-init.sh '
            'https://raw.githubusercontent.com/leanprover/elan/master/elan-init.sh '
            f'&& sh /tmp/elan-init.sh -y --default-toolchain {PINNED_LEAN_TOOLCHAIN}'
        ),
        purpose=(
            'Install Lean through elan with the lane-pinned Lean 4 toolchain '
            'after reviewing the fetched installer script.'
        ),
        requires_network=True,
    ),
    CommandPlan(
        step='pin-project-toolchain',
        command=f'printf "%s\\n" "{PINNED_LEAN_TOOLCHAIN}" > lean-toolchain',
        purpose='Pin the Lean toolchain used for reproducible proof-kernel checks.',
    ),
    CommandPlan(
        step='activate-elan-path',
        command='export PATH="$HOME/.elan/bin:$PATH"',
        purpose='Expose elan-managed lean, lake, and elan executables to the current shell.',
    ),
    CommandPlan(
        step='verify-lean-lane',
        command=(
            'PYTHONPATH=. /home/barberb/miniforge3/bin/python '
            'scripts/ops/security_verification/probe_lean_solver_lane.py '
            '--out security_ir_artifacts/environment/lean-solver-lane-report.json'
        ),
        purpose='Regenerate the Lean lane report after installation.',
        review_required=False,
    ),
)

PROBE_COMMANDS: tuple[CommandPlan, ...] = (
    CommandPlan(
        step='probe-lean-version',
        command='lean --version',
        purpose='Record the exact Lean executable version.',
        review_required=False,
    ),
    CommandPlan(
        step='probe-lake-version',
        command='lake --version',
        purpose='Record the exact Lake executable version when available.',
        review_required=False,
    ),
    CommandPlan(
        step='probe-elan-version',
        command='elan --version',
        purpose='Record the elan toolchain manager version when available.',
        review_required=False,
    ),
    CommandPlan(
        step='probe-lean-prefix',
        command='lean --print-prefix',
        purpose='Record the active Lean toolchain prefix path.',
        review_required=False,
    ),
    CommandPlan(
        step='check-proof-kernel',
        command=f'lean {PROOF_KERNEL_PATH.as_posix()}',
        purpose='Compile-check the proof-consumer Lean kernel.',
        review_required=False,
    ),
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _normalize_system(value: str | None) -> str:
    text = (value or '').strip().lower()
    aliases = {
        'darwin': 'darwin',
        'mac': 'darwin',
        'macos': 'darwin',
        'linux': 'linux',
        'windows': 'windows',
        'win32': 'windows',
    }
    return aliases.get(text, text or 'unknown')


def _normalize_machine(value: str | None) -> str:
    text = (value or '').strip().lower()
    aliases = {
        'x64': 'x86_64',
        'amd64': 'x86_64',
        'aarch64': 'arm64',
        'arm64': 'arm64',
    }
    return aliases.get(text, text or 'unknown')


def detect_platform(
    system_override: str | None = None,
    machine_override: str | None = None,
) -> dict[str, Any]:
    system_raw = system_override or platform.system()
    machine_raw = machine_override or platform.machine()
    system_key = _normalize_system(system_raw)
    machine_key = _normalize_machine(machine_raw)
    supported = system_key in SUPPORTED_SYSTEMS and machine_key in SUPPORTED_MACHINES
    return {
        'system': system_raw,
        'machine': machine_raw,
        'system_key': system_key,
        'machine_key': machine_key,
        'supported': supported,
        'support_level': 'native' if supported else 'unsupported-native',
        'unsupported_reason': None
        if supported
        else (
            'Lean proof-consumer lanes are approved for native Linux/macOS '
            f'on {", ".join(sorted(SUPPORTED_MACHINES))}; observed '
            f'{system_raw}/{machine_raw}.'
        ),
    }


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


def _coerce_text(value: Any) -> str:
    if isinstance(value, bytes):
        return value.decode('utf-8', errors='replace')
    return str(value or '')


def _first_line(*values: Any) -> str | None:
    for value in values:
        for line in _coerce_text(value).splitlines():
            stripped = line.strip()
            if stripped:
                return stripped
    return None


def _version_token(raw: str | None, *, tool_name: str) -> str | None:
    if not raw:
        return None
    if tool_name == 'lean' and 'Lean' not in raw:
        return None
    match = re.search(r'(?<!\d)(\d+(?:\.\d+){1,3})(?!\d)', raw)
    return match.group(1) if match else None


def _sha256_file(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(65536), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _resolve_executable(
    *,
    candidates: Sequence[str],
    env_var: str,
    environ: Mapping[str, str],
    which: Which | None,
) -> tuple[str | None, str | None, list[str]]:
    which_fn = shutil.which if which is None else which
    searched: list[str] = []
    env_candidate = environ.get(env_var)
    if env_candidate:
        searched.append(env_candidate)
        candidate_path = Path(env_candidate)
        if candidate_path.is_file():
            return env_candidate, env_var, searched
        resolved = which_fn(env_candidate)
        if resolved:
            return resolved, env_var, searched

    for candidate in candidates:
        searched.append(candidate)
        resolved = which_fn(candidate)
        if resolved:
            return resolved, None, searched
    return None, None, searched


def _probe_tool(
    *,
    name: str,
    display_name: str,
    candidates: Sequence[str],
    env_var: str,
    version_args: Sequence[str],
    environ: Mapping[str, str],
    runner: CommandRunner,
    which: Which | None,
    timeout_seconds: int,
) -> dict[str, Any]:
    executable, resolved_by, searched = _resolve_executable(
        candidates=candidates,
        env_var=env_var,
        environ=environ,
        which=which,
    )
    command = [executable, *version_args] if executable else None
    command_result = runner(command, timeout_seconds) if command else None
    raw_version = _first_line(
        command_result.get('stdout') if command_result else '',
        command_result.get('stderr') if command_result else '',
    )
    if executable is None:
        status = 'missing'
    elif command_result is None or command_result.get('timed_out') or command_result.get('exit_code') != 0:
        status = 'error'
    else:
        status = 'present'
    version = _version_token(raw_version, tool_name=name) if status == 'present' else None
    entry: dict[str, Any] = {
        'name': name,
        'display_name': display_name,
        'status': status,
        'required_for_lane': name in {'lean'},
        'executable': executable,
        'resolved_by_env_var': resolved_by,
        'searched_names': searched,
        'command': command,
        'version_raw': raw_version,
        'version': version,
    }
    if command_result is not None:
        entry['command_result'] = {
            'exit_code': command_result.get('exit_code'),
            'timed_out': bool(command_result.get('timed_out')),
            'error': command_result.get('error'),
            'stdout_first_line': _first_line(command_result.get('stdout', '')),
            'stderr_first_line': _first_line(command_result.get('stderr', '')),
        }
    return entry


def _run_path_probe(
    *,
    executable: str | None,
    args: Sequence[str],
    runner: CommandRunner,
    timeout_seconds: int,
) -> dict[str, Any] | None:
    if not executable:
        return None
    command = [executable, *args]
    result = runner(command, timeout_seconds)
    return {
        'command': command,
        'status': 'present'
        if result.get('exit_code') == 0 and not result.get('timed_out')
        else 'error',
        'value': _first_line(result.get('stdout', ''), result.get('stderr', '')),
        'command_result': {
            'exit_code': result.get('exit_code'),
            'timed_out': bool(result.get('timed_out')),
            'error': result.get('error'),
            'stdout_first_line': _first_line(result.get('stdout', '')),
            'stderr_first_line': _first_line(result.get('stderr', '')),
        },
    }


def _run_kernel_check(
    *,
    repo_root: Path,
    lean_executable: str | None,
    runner: CommandRunner,
    timeout_seconds: int,
    proof_kernel_path: Path,
) -> dict[str, Any]:
    kernel = repo_root / proof_kernel_path
    entry: dict[str, Any] = {
        'path': proof_kernel_path.as_posix(),
        'path_absolute': kernel.as_posix(),
        'exists': kernel.is_file(),
        'sha256': _sha256_file(kernel),
        'status': 'not-run',
        'command': None,
    }
    if not lean_executable:
        entry['status'] = 'missing-lean'
        entry['reason'] = 'Lean executable is not available.'
        return entry
    if not kernel.is_file():
        entry['status'] = 'blocked'
        entry['reason'] = 'Proof kernel source is missing.'
        return entry

    command = [lean_executable, kernel.as_posix()]
    result = runner(command, timeout_seconds)
    entry['command'] = command
    entry['command_result'] = {
        'exit_code': result.get('exit_code'),
        'timed_out': bool(result.get('timed_out')),
        'error': result.get('error'),
        'stdout_first_line': _first_line(result.get('stdout', '')),
        'stderr_first_line': _first_line(result.get('stderr', '')),
    }
    entry['status'] = 'checked' if result.get('exit_code') == 0 and not result.get('timed_out') else 'blocked'
    if entry['status'] == 'blocked':
        entry['reason'] = 'Lean could not compile-check the proof-consumer kernel.'
    return entry


def _load_proof_consumer_context(repo_root: Path, report_path: Path) -> dict[str, Any]:
    absolute = repo_root / report_path
    context: dict[str, Any] = {
        'proof_consumer_report_path': report_path.as_posix(),
        'proof_consumer_report_exists': absolute.is_file(),
        'proof_consumer_report_sha256': _sha256_file(absolute),
    }
    if not absolute.is_file():
        return context
    try:
        payload = json.loads(absolute.read_text(encoding='utf-8'))
    except json.JSONDecodeError as exc:
        context['proof_consumer_report_parse_error'] = str(exc)
        return context
    context['schema_version'] = payload.get('schema_version')
    context['claim_id'] = payload.get('claim_id')
    context['model_cid'] = payload.get('model_cid')
    context['artifact_cid'] = payload.get('artifact_cid')
    context['proof_kernel_cid'] = payload.get('proof_kernel_cid')
    fixtures = payload.get('rejected_fixtures')
    if isinstance(fixtures, list):
        context['rejected_fixture_outcomes'] = sorted(
            {
                str(entry.get('outcome'))
                for entry in fixtures
                if isinstance(entry, Mapping) and entry.get('outcome')
            }
        )
        context['rejected_fixture_count'] = len(fixtures)
    return context


def _lane_status(
    *,
    platform_report: Mapping[str, Any],
    lean: Mapping[str, Any],
    lake: Mapping[str, Any],
    kernel_check: Mapping[str, Any],
) -> str:
    if not platform_report.get('supported'):
        return 'blocked'
    if lean.get('status') == 'missing':
        return 'degraded'
    if lean.get('status') != 'present':
        return 'blocked'
    if kernel_check.get('status') != 'checked':
        return 'blocked'
    if lake.get('status') == 'error':
        return 'blocked'
    if lake.get('status') == 'missing':
        return 'degraded'
    return 'ready'


def _security_decision(status: str) -> str:
    if status == 'ready':
        return 'OPTIONAL_SOLVER_LANE_READY'
    if status == 'degraded':
        return 'DEGRADE_OPTIONAL_SOLVER_LANE_MISSING_SOLVER'
    return 'BLOCK_OPTIONAL_SOLVER_LANE'


def _release_effect(status: str) -> str:
    if status == 'ready':
        return 'coverage-available'
    if status == 'degraded':
        return 'degraded-optional-coverage'
    return 'blocked-proof-lane'


def _operator_action(status: str, platform_report: Mapping[str, Any], lean: Mapping[str, Any], lake: Mapping[str, Any]) -> str:
    if status == 'ready':
        return 'Lean and Lake are available and the Lean proof kernel compile-checks; receipt coverage may be claimed only with this report and matching proof artifacts.'
    if not platform_report.get('supported'):
        return 'Move the Lean lane to a supported Linux/macOS proof worker or keep proof-consumer Lean coverage blocked.'
    if lean.get('status') == 'missing':
        return 'Install the pinned Lean toolchain with the recorded guidance and keep proof-consumer Lean coverage degraded until the probe is ready.'
    if lake.get('status') == 'missing':
        return 'Install or expose Lake for Lean project checks; keep the lane degraded even if the standalone Lean kernel compiles.'
    return 'Fix the Lean executable, active toolchain, Lake executable, or proof-kernel compile error before claiming Lean proof-consumer coverage.'


def _blockers(
    *,
    status: str,
    platform_report: Mapping[str, Any],
    lean: Mapping[str, Any],
    lake: Mapping[str, Any],
    kernel_check: Mapping[str, Any],
) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    if status != 'blocked':
        return blockers
    if not platform_report.get('supported'):
        blockers.append(
            {
                'code': 'LEAN_SOLVER_PLATFORM_UNSUPPORTED',
                'component': 'platform',
                'status': 'blocked',
                'remediation': _operator_action(status, platform_report, lean, lake),
            }
        )
    if lean.get('status') == 'error':
        blockers.append(
            {
                'code': 'LEAN_EXECUTABLE_UNUSABLE',
                'component': 'lean',
                'status': 'blocked',
                'remediation': _operator_action(status, platform_report, lean, lake),
            }
        )
    if lake.get('status') == 'error':
        blockers.append(
            {
                'code': 'LAKE_EXECUTABLE_UNUSABLE',
                'component': 'lake',
                'status': 'blocked',
                'remediation': _operator_action(status, platform_report, lean, lake),
            }
        )
    if lean.get('status') == 'present' and kernel_check.get('status') == 'blocked':
        blockers.append(
            {
                'code': 'LEAN_PROOF_KERNEL_CHECK_FAILED',
                'component': 'proof_kernel',
                'status': 'blocked',
                'remediation': _operator_action(status, platform_report, lean, lake),
            }
        )
    if not blockers:
        blockers.append(
            {
                'code': 'LEAN_PROOF_CONSUMER_LANE_BLOCKED',
                'component': 'lean_solver_lane',
                'status': 'blocked',
                'remediation': _operator_action(status, platform_report, lean, lake),
            }
        )
    return blockers


def build_report(
    *,
    repo_root: Path | str | None = None,
    environ: Mapping[str, str] | None = None,
    runner: CommandRunner | None = None,
    which: Which | None = None,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    generated_at_utc: str | None = None,
    platform_system: str | None = None,
    platform_machine: str | None = None,
    proof_kernel_path: Path = PROOF_KERNEL_PATH,
    proof_consumer_report_path: Path = PROOF_CONSUMER_REPORT_PATH,
) -> dict[str, Any]:
    root = Path(repo_root) if repo_root is not None else _repo_root()
    env = os.environ if environ is None else environ
    runner_fn = _default_runner if runner is None else runner
    platform_report = detect_platform(platform_system, platform_machine)

    lean = _probe_tool(
        name='lean',
        display_name='Lean',
        candidates=('lean',),
        env_var='LEAN_EXE',
        version_args=('--version',),
        environ=env,
        runner=runner_fn,
        which=which,
        timeout_seconds=timeout_seconds,
    )
    lake = _probe_tool(
        name='lake',
        display_name='Lake',
        candidates=('lake',),
        env_var='LAKE_EXE',
        version_args=('--version',),
        environ=env,
        runner=runner_fn,
        which=which,
        timeout_seconds=timeout_seconds,
    )
    elan = _probe_tool(
        name='elan',
        display_name='elan',
        candidates=('elan',),
        env_var='ELAN_EXE',
        version_args=('--version',),
        environ=env,
        runner=runner_fn,
        which=which,
        timeout_seconds=timeout_seconds,
    )

    lean_prefix = _run_path_probe(
        executable=lean.get('executable') if lean.get('status') == 'present' else None,
        args=('--print-prefix',),
        runner=runner_fn,
        timeout_seconds=timeout_seconds,
    )
    lean_libdir = _run_path_probe(
        executable=lean.get('executable') if lean.get('status') == 'present' else None,
        args=('--print-libdir',),
        runner=runner_fn,
        timeout_seconds=timeout_seconds,
    )
    kernel_check = _run_kernel_check(
        repo_root=root,
        lean_executable=lean.get('executable') if lean.get('status') == 'present' else None,
        runner=runner_fn,
        timeout_seconds=timeout_seconds,
        proof_kernel_path=proof_kernel_path,
    )
    proof_context = _load_proof_consumer_context(root, proof_consumer_report_path)

    status = _lane_status(
        platform_report=platform_report,
        lean=lean,
        lake=lake,
        kernel_check=kernel_check,
    )
    security_decision = _security_decision(status)
    blockers = _blockers(
        status=status,
        platform_report=platform_report,
        lean=lean,
        lake=lake,
        kernel_check=kernel_check,
    )
    degraded_reasons: list[dict[str, Any]] = []
    if status == 'degraded':
        if lean.get('status') == 'missing':
            degraded_reasons.append(
                {
                    'code': 'LEAN_EXECUTABLE_MISSING',
                    'component': 'lean',
                    'effect': 'missing-solver',
                }
            )
        if lake.get('status') == 'missing':
            degraded_reasons.append(
                {
                    'code': 'LAKE_EXECUTABLE_MISSING',
                    'component': 'lake',
                    'effect': 'lean-kernel-only-without-lake-project-checks',
                }
            )

    lane = {
        'lane_id': LANE_ID,
        'name': LANE_NAME,
        'status': status,
        'release_effect': _release_effect(status),
        'security_decision': security_decision,
        'required_for_global_release': False,
        'missing_solver_outcome': 'missing-solver' if status != 'ready' else None,
        'operator_action': _operator_action(status, platform_report, lean, lake),
    }

    proof_claims = {
        'claim_id': proof_context.get('claim_id')
        or 'xaman-security:claim:proof-consumers-fail-closed-for-xaman-security-claims',
        'proof_consumer_report': proof_context,
        'claim_status': 'claimable-with-lean-receipt' if status == 'ready' else status,
        'receipt_acceptance': 'allowed-only-after-matching-lean-kernel-check'
        if status == 'ready'
        else 'blocked-or-degraded-no-lean-receipt',
        'missing_lean_receipt_outcome': 'missing-solver',
        'xaman_rejected_fixture_outcome': 'MISSING_SOLVER',
        'silent_acceptance_allowed': False,
    }

    return {
        'schema_version': SCHEMA_VERSION,
        'task_id': TASK_ID,
        'generated_at_utc': generated_at_utc or _utc_now(),
        'policy_document': POLICY_DOCUMENT,
        'optional_installer_document': OPTIONAL_INSTALLER_DOCUMENT,
        'proof_consumer_document': PROOF_CONSUMER_DOCUMENT,
        'repo_root': root.as_posix(),
        'default_mode': 'probe-only',
        'commands_executed_by_default': 'Lean/Lake/elan version probes and Lean proof-kernel compile check only',
        'overall_status': status,
        'security_decision': security_decision,
        'platform': platform_report,
        'tools': {
            'lean': lean,
            'lake': lake,
            'elan': elan,
        },
        'toolchain_paths': {
            'lean_prefix': lean_prefix,
            'lean_libdir': lean_libdir,
            'elan_toolchains_root': str(Path.home() / '.elan' / 'toolchains'),
            'lake_executable': lake.get('executable'),
        },
        'proof_kernel_check': kernel_check,
        'proof_lane': lane,
        'proof_consumer_claims': proof_claims,
        'blockers': blockers,
        'degraded_reasons': degraded_reasons,
        'probe_commands': [command.to_dict() for command in PROBE_COMMANDS],
        'installation_guidance': {
            'source_url': 'https://lean-lang.org/install/',
            'pinned_toolchain': PINNED_LEAN_TOOLCHAIN,
            'reproducible': True,
            'commands': [command.to_dict() for command in INSTALL_COMMANDS],
        },
        'acceptance_policy': {
            'silent_success_allowed': False,
            'missing_lean_effect': 'degraded optional proof-consumer lane on supported hosts; emit missing-solver for Lean-backed receipt claims',
            'unusable_lean_effect': 'blocked proof-consumer lane until lean --version and kernel compile checks succeed',
            'missing_lake_effect': 'degraded lane; standalone Lean kernel may compile, but project-level Lake coverage is not claimable',
            'release_claim_rule': 'Do not claim Lean proof-consumer coverage unless proof_lane.status is ready and proof_kernel_check.status is checked.',
        },
        'summary': {
            'ready_lane_count': 1 if status == 'ready' else 0,
            'degraded_lane_count': 1 if status == 'degraded' else 0,
            'blocked_lane_count': 1 if status == 'blocked' else 0,
            'lean_present': lean.get('status') == 'present',
            'lake_present': lake.get('status') == 'present',
            'elan_present': elan.get('status') == 'present',
            'proof_kernel_checked': kernel_check.get('status') == 'checked',
            'silent_success_allowed': False,
        },
    }


def write_report(report: Mapping[str, Any], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2, sort_keys=True) + '\n', encoding='utf-8')


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Probe the Lean proof-consumer solver lane.')
    parser.add_argument('--repo-root', default=_repo_root().as_posix(), help='repository root')
    parser.add_argument('--out', default=DEFAULT_OUT.as_posix(), help='JSON report output path')
    parser.add_argument(
        '--timeout-seconds',
        type=int,
        default=DEFAULT_TIMEOUT_SECONDS,
        help='timeout for each Lean/Lake/elan command',
    )
    parser.add_argument('--platform-system', help='override detected platform system, for CI/testing')
    parser.add_argument('--platform-machine', help='override detected platform machine, for CI/testing')
    parser.add_argument(
        '--strict',
        action='store_true',
        help='return non-zero when the Lean lane is blocked',
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    report = build_report(
        repo_root=Path(args.repo_root),
        timeout_seconds=args.timeout_seconds,
        platform_system=args.platform_system,
        platform_machine=args.platform_machine,
    )
    out_path = Path(args.out)
    write_report(report, out_path)
    print(
        json.dumps(
            {
                'report': out_path.as_posix(),
                'overall_status': report['overall_status'],
                'security_decision': report['security_decision'],
                'lean_present': report['summary']['lean_present'],
                'lake_present': report['summary']['lake_present'],
                'proof_kernel_checked': report['summary']['proof_kernel_checked'],
            },
            sort_keys=True,
        )
    )
    return 2 if args.strict and report['overall_status'] == 'blocked' else 0


if __name__ == '__main__':  # pragma: no cover
    raise SystemExit(main())
