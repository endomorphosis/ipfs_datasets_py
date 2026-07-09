#!/usr/bin/env python3
"""Plan and probe optional theorem-solver installation lanes.

``PORTAL-CXTP-086`` does not make optional theorem provers silently pass.
This script records safe install/probe commands for Apalache, Tamarin,
ProVerif, Lean, and Coq, then turns the current host state into explicit
proof-lane decisions:

* ``ready`` when the solver is present and usable.
* ``degraded`` when the solver is absent on a supported platform.
* ``blocked`` when the platform is unsupported or a discovered solver is
  unusable.

The default mode is non-destructive. It runs only version probes and writes a
JSON report. Installation commands are emitted as operator-reviewed command
plans with privilege/network flags; they are not executed by this script.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import platform
import sys
from typing import Any, Callable, Mapping, Sequence


SCRIPT_DIR = Path(__file__).resolve().parent
ROOT_DIR = Path(__file__).resolve().parents[3]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import probe_theorem_prover_environment as dependency_probe  # noqa: E402


SCHEMA_VERSION = 'crypto-exchange-optional-solver-install-report/v1'
TASK_ID = 'PORTAL-CXTP-086'
DEFAULT_OUT = Path('security_ir_artifacts/environment/optional-solver-install-report.json')
POLICY_DOCUMENT = 'docs/security_verification/optional_solver_installation.md'
DEPENDENCY_PROBE_DOCUMENT = 'docs/security_verification/solver_dependency_bootstrap.md'
DEFAULT_TIMEOUT_SECONDS = 8

OPTIONAL_SOLVER_NAMES = ('apalache', 'tamarin', 'proverif', 'lean', 'coq')
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


@dataclass(frozen=True)
class SolverInstallSpec:
    name: str
    display_name: str
    proof_lane_id: str
    proof_lane_name: str
    category: str
    capability: str
    executable_names: tuple[str, ...]
    probe_commands: tuple[CommandPlan, ...]
    linux_install_commands: tuple[CommandPlan, ...]
    macos_install_commands: tuple[CommandPlan, ...]
    unsupported_platform_note: str
    source_url: str

    def install_commands_for(self, system_key: str) -> tuple[CommandPlan, ...]:
        if system_key == 'linux':
            return self.linux_install_commands
        if system_key == 'darwin':
            return self.macos_install_commands
        return ()


SOLVER_INSTALL_SPECS: tuple[SolverInstallSpec, ...] = (
    SolverInstallSpec(
        name='apalache',
        display_name='Apalache',
        proof_lane_id='tla_apalache_state_machine',
        proof_lane_name='TLA+/Apalache temporal state-machine checks',
        category='model_checker',
        capability='Temporal workflow and interleaving model checking for withdrawal, reservation, freeze, signing, and broadcast states.',
        executable_names=('apalache-mc', 'apalache'),
        source_url='https://apalache-mc.org/docs/apalache/installation/index.html',
        unsupported_platform_note='Native Apalache proof lanes are supported on Linux and macOS workers. Use a Linux proof worker rather than treating Windows-native absence as coverage.',
        probe_commands=(
            CommandPlan(
                step='probe-java',
                command='java -version',
                purpose='Confirm the JVM required by the Apalache launcher is available.',
                review_required=False,
            ),
            CommandPlan(
                step='probe-apalache',
                command='apalache-mc version',
                purpose='Confirm the Apalache launcher resolves and reports a version.',
                review_required=False,
            ),
        ),
        linux_install_commands=(
            CommandPlan(
                step='install-jvm-conda',
                command='conda install -c conda-forge openjdk=17',
                purpose='Install a user-scoped OpenJDK 17 runtime when this proof worker uses conda.',
                requires_network=True,
            ),
            CommandPlan(
                step='install-reviewed-prebuilt',
                command='install -d "$HOME/.local/opt/apalache" "$HOME/.local/bin" && tar -xzf "$APALACHE_TGZ" -C "$HOME/.local/opt/apalache" --strip-components=1 && ln -sf "$HOME/.local/opt/apalache/bin/apalache-mc" "$HOME/.local/bin/apalache-mc"',
                purpose='Install a previously downloaded, checksum-reviewed Apalache prebuilt archive from $APALACHE_TGZ.',
            ),
        ),
        macos_install_commands=(
            CommandPlan(
                step='install-jvm-brew',
                command='brew install --cask temurin@17',
                purpose='Install the recommended Java 17 runtime for Apalache on macOS.',
                requires_network=True,
            ),
            CommandPlan(
                step='install-reviewed-prebuilt',
                command='mkdir -p "$HOME/.local/opt/apalache" "$HOME/.local/bin" && tar -xzf "$APALACHE_TGZ" -C "$HOME/.local/opt/apalache" --strip-components=1 && ln -sf "$HOME/.local/opt/apalache/bin/apalache-mc" "$HOME/.local/bin/apalache-mc"',
                purpose='Install a previously downloaded, checksum-reviewed Apalache prebuilt archive from $APALACHE_TGZ.',
            ),
        ),
    ),
    SolverInstallSpec(
        name='tamarin',
        display_name='Tamarin Prover',
        proof_lane_id='tamarin_symbolic_protocol',
        proof_lane_name='Tamarin symbolic protocol checks',
        category='protocol_prover',
        capability='Symbolic protocol proof coverage for key custody, signing authority, replay, and capability flows.',
        executable_names=('tamarin-prover',),
        source_url='https://tamarin-prover.com/manual/master/book/002_installation.html',
        unsupported_platform_note='Native Tamarin proof lanes are supported on Linux and macOS. Windows operators should use WSL2/Linux and record the Linux probe.',
        probe_commands=(
            CommandPlan(
                step='probe-tamarin',
                command='tamarin-prover --version',
                purpose='Confirm the Tamarin executable resolves and reports a version.',
                review_required=False,
            ),
        ),
        linux_install_commands=(
            CommandPlan(
                step='install-homebrew',
                command='brew install tamarin-prover/tap/tamarin-prover',
                purpose='Install the upstream Homebrew-packaged Tamarin release on Linuxbrew/Homebrew.',
                requires_network=True,
            ),
            CommandPlan(
                step='install-nix',
                command='nix-env -iA nixpkgs.tamarin-prover',
                purpose='Install Tamarin from Nixpkgs when the proof worker is Nix-managed.',
                requires_network=True,
            ),
        ),
        macos_install_commands=(
            CommandPlan(
                step='install-homebrew',
                command='brew install tamarin-prover/tap/tamarin-prover',
                purpose='Install the upstream Homebrew-packaged Tamarin release.',
                requires_network=True,
            ),
        ),
    ),
    SolverInstallSpec(
        name='proverif',
        display_name='ProVerif',
        proof_lane_id='proverif_symbolic_protocol',
        proof_lane_name='ProVerif symbolic protocol checks',
        category='protocol_prover',
        capability='Cryptographic protocol reachability and secrecy checks for payload, session, and secret-flow models.',
        executable_names=('proverif',),
        source_url='https://bblanche.gitlabpages.inria.fr/proverif/',
        unsupported_platform_note='Native ProVerif proof lanes are supported on Linux and macOS through OPAM-managed OCaml environments. Use WSL2/Linux for Windows release proofs.',
        probe_commands=(
            CommandPlan(
                step='probe-proverif',
                command='proverif -version',
                purpose='Confirm the ProVerif executable resolves and reports a version.',
                review_required=False,
            ),
        ),
        linux_install_commands=(
            CommandPlan(
                step='install-opam',
                command='opam update && opam install -y proverif',
                purpose='Install ProVerif into the active OPAM switch.',
                requires_network=True,
            ),
            CommandPlan(
                step='install-conda-opam-prereq',
                command='conda install -c conda-forge opam ocaml',
                purpose='Provision OPAM/OCaml without system package-manager privileges when conda owns the worker environment.',
                requires_network=True,
            ),
        ),
        macos_install_commands=(
            CommandPlan(
                step='install-opam-brew-prereq',
                command='brew install opam ocaml',
                purpose='Provision OPAM/OCaml before installing ProVerif.',
                requires_network=True,
            ),
            CommandPlan(
                step='install-opam',
                command='opam update && opam install -y proverif',
                purpose='Install ProVerif into the active OPAM switch.',
                requires_network=True,
            ),
        ),
    ),
    SolverInstallSpec(
        name='lean',
        display_name='Lean',
        proof_lane_id='lean_proof_consumer_invariants',
        proof_lane_name='Lean proof-consumer invariant checks',
        category='proof_assistant',
        capability='Proof receipt, canonicalization, and proof-consumer invariant checking.',
        executable_names=('lean', 'lake'),
        source_url='https://lean-lang.org/install/',
        unsupported_platform_note='Native Lean proof lanes are supported on Linux and macOS workers. Windows release workers should record a WSL2/Linux probe or a reviewed native Lean probe before claiming coverage.',
        probe_commands=(
            CommandPlan(
                step='probe-lean',
                command='lean --version',
                purpose='Confirm Lean resolves and reports a version.',
                review_required=False,
            ),
            CommandPlan(
                step='probe-lake',
                command='lake --version',
                purpose='Confirm Lake resolves for Lean project checks.',
                review_required=False,
            ),
        ),
        linux_install_commands=(
            CommandPlan(
                step='install-elan-reviewed-script',
                command='curl -fsSLo /tmp/elan-init.sh https://raw.githubusercontent.com/leanprover/elan/master/elan-init.sh && sh /tmp/elan-init.sh -y --default-toolchain leanprover/lean4:stable',
                purpose='Install Lean through elan after reviewing the fetched installer script.',
                requires_network=True,
            ),
            CommandPlan(
                step='activate-elan-path',
                command='export PATH="$HOME/.elan/bin:$PATH"',
                purpose='Expose elan-managed lean and lake executables to the current shell.',
            ),
        ),
        macos_install_commands=(
            CommandPlan(
                step='install-elan-reviewed-script',
                command='curl -fsSLo /tmp/elan-init.sh https://raw.githubusercontent.com/leanprover/elan/master/elan-init.sh && sh /tmp/elan-init.sh -y --default-toolchain leanprover/lean4:stable',
                purpose='Install Lean through elan after reviewing the fetched installer script.',
                requires_network=True,
            ),
            CommandPlan(
                step='activate-elan-path',
                command='export PATH="$HOME/.elan/bin:$PATH"',
                purpose='Expose elan-managed lean and lake executables to the current shell.',
            ),
        ),
    ),
    SolverInstallSpec(
        name='coq',
        display_name='Coq',
        proof_lane_id='coq_proof_consumer_invariants',
        proof_lane_name='Coq proof-consumer invariant checks',
        category='proof_assistant',
        capability='Independent proof receipt and proof-consumer invariant checking.',
        executable_names=('coqc', 'coqtop'),
        source_url='https://rocq-prover.org/doc/V8.17.1/refman/practical-tools/utilities.html',
        unsupported_platform_note='Native Coq proof lanes are supported on Linux and macOS through OPAM, conda, Homebrew, or reviewed system packages. Use a Linux proof worker for unsupported native hosts.',
        probe_commands=(
            CommandPlan(
                step='probe-coqc',
                command='coqc --version',
                purpose='Confirm the Coq compiler resolves and reports a version.',
                review_required=False,
            ),
            CommandPlan(
                step='probe-coqtop',
                command='coqtop --version',
                purpose='Confirm the Coq toplevel resolves and reports a version.',
                review_required=False,
            ),
        ),
        linux_install_commands=(
            CommandPlan(
                step='install-conda',
                command='conda install -c conda-forge coq',
                purpose='Install Coq in a user-scoped conda proof environment.',
                requires_network=True,
            ),
            CommandPlan(
                step='install-opam',
                command='opam update && opam install -y coq',
                purpose='Install Coq into the active OPAM switch.',
                requires_network=True,
            ),
            CommandPlan(
                step='install-apt-reviewed',
                command='sudo apt-get update && sudo apt-get install -y coq',
                purpose='Install the distribution-packaged Coq compiler on Debian/Ubuntu after OS-owner approval.',
                requires_network=True,
                requires_privilege=True,
            ),
        ),
        macos_install_commands=(
            CommandPlan(
                step='install-homebrew',
                command='brew install coq',
                purpose='Install Homebrew-packaged Coq.',
                requires_network=True,
            ),
            CommandPlan(
                step='install-opam',
                command='opam update && opam install -y coq',
                purpose='Install Coq into the active OPAM switch.',
                requires_network=True,
            ),
        ),
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
        'macos': 'darwin',
        'mac': 'darwin',
        'linux': 'linux',
        'windows': 'windows',
        'win32': 'windows',
        'cygwin': 'windows',
        'msys': 'windows',
    }
    return aliases.get(text, text or 'unknown')


def _normalize_machine(value: str | None) -> str:
    text = (value or '').strip().lower()
    aliases = {
        'x64': 'x86_64',
        'amd64': 'x86_64',
        'arm64': 'arm64',
        'aarch64': 'arm64',
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
            f'Optional theorem-solver lanes are only approved for native Linux/macOS '
            f'on {", ".join(sorted(SUPPORTED_MACHINES))}; observed {system_raw}/{machine_raw}.'
        ),
    }


def _dependency_specs_by_name() -> dict[str, dependency_probe.DependencySpec]:
    return {spec.name: spec for spec in dependency_probe.DEPENDENCIES}


def _optional_dependency_entries(
    *,
    repo_root: Path,
    environ: Mapping[str, str] | None,
    runner: CommandRunner | None,
    which: Which | None,
    timeout_seconds: int,
    selected_solvers: set[str],
) -> dict[str, dict[str, Any]]:
    specs = _dependency_specs_by_name()
    entries: dict[str, dict[str, Any]] = {}
    for name in OPTIONAL_SOLVER_NAMES:
        if name not in selected_solvers:
            continue
        entries[name] = dependency_probe.probe_dependency(
            specs[name],
            environ=environ,
            runner=runner,
            which=which,
            timeout_seconds=timeout_seconds,
            repo_root=repo_root,
        )
    return entries


def _lane_status(platform_report: Mapping[str, Any], dependency: Mapping[str, Any]) -> str:
    if not platform_report.get('supported'):
        return 'blocked'
    status = dependency.get('status')
    if status == 'present':
        return 'ready'
    if status == 'missing':
        return 'degraded'
    return 'blocked'


def _lane_release_effect(lane_status: str) -> str:
    if lane_status == 'ready':
        return 'coverage-available'
    if lane_status == 'degraded':
        return 'degraded-optional-coverage'
    return 'blocked-proof-lane'


def _lane_decision(lane_status: str) -> str:
    if lane_status == 'ready':
        return 'OPTIONAL_SOLVER_LANE_READY'
    if lane_status == 'degraded':
        return 'DEGRADE_OPTIONAL_SOLVER_LANE_MISSING_SOLVER'
    return 'BLOCK_OPTIONAL_SOLVER_LANE'


def _solver_entry(
    spec: SolverInstallSpec,
    *,
    platform_report: Mapping[str, Any],
    dependency_entry: Mapping[str, Any],
) -> dict[str, Any]:
    system_key = str(platform_report.get('system_key', 'unknown'))
    supported = bool(platform_report.get('supported'))
    lane_status = _lane_status(platform_report, dependency_entry)
    dependency_status = str(dependency_entry.get('status', 'missing'))
    install_commands = spec.install_commands_for(system_key)
    unsupported = [] if supported else [
        {
            'system': platform_report.get('system'),
            'machine': platform_report.get('machine'),
            'reason': platform_report.get('unsupported_reason'),
            'remediation': spec.unsupported_platform_note,
        }
    ]
    blocker_code = None
    if lane_status == 'blocked':
        blocker_code = 'OPTIONAL_SOLVER_PLATFORM_UNSUPPORTED' if not supported else 'OPTIONAL_SOLVER_UNUSABLE'

    return {
        'name': spec.name,
        'display_name': spec.display_name,
        'category': spec.category,
        'capability': spec.capability,
        'source_url': spec.source_url,
        'executable_names': list(spec.executable_names),
        'dependency_probe': dependency_entry,
        'platform_supported': supported,
        'unsupported_platforms': unsupported,
        'install_commands': [command.to_dict() for command in install_commands],
        'probe_commands': [command.to_dict() for command in spec.probe_commands],
        'proof_lane': {
            'lane_id': spec.proof_lane_id,
            'name': spec.proof_lane_name,
            'status': lane_status,
            'release_effect': _lane_release_effect(lane_status),
            'security_decision': _lane_decision(lane_status),
            'required_for_global_release': False,
            'missing_solver_outcome': 'missing-solver' if lane_status != 'ready' else None,
            'operator_action': _operator_action(spec, lane_status, dependency_status, supported),
        },
        'blocker': None
        if blocker_code is None
        else {
            'code': blocker_code,
            'component': spec.name,
            'lane_id': spec.proof_lane_id,
            'status': lane_status,
            'remediation': _operator_action(spec, lane_status, dependency_status, supported),
        },
    }


def _operator_action(
    spec: SolverInstallSpec,
    lane_status: str,
    dependency_status: str,
    platform_supported: bool,
) -> str:
    if lane_status == 'ready':
        return f'{spec.display_name} is available; this optional proof lane may claim coverage after proofs run.'
    if not platform_supported:
        return f'Move this lane to a supported Linux/macOS proof worker or record it as blocked; do not claim {spec.display_name} coverage.'
    if dependency_status == 'missing':
        return f'Run a reviewed install command for {spec.display_name}, rerun the installer report, and keep the lane degraded until the probe is present.'
    return f'Fix the {spec.display_name} executable or version probe and keep the lane blocked until it reports a usable version.'


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
    solvers: Sequence[str] = OPTIONAL_SOLVER_NAMES,
) -> dict[str, Any]:
    root = Path(repo_root) if repo_root is not None else _repo_root()
    selected_solvers = set(solvers)
    invalid = sorted(selected_solvers - set(OPTIONAL_SOLVER_NAMES))
    if invalid:
        raise ValueError(f'unknown optional solver(s): {", ".join(invalid)}')

    platform_report = detect_platform(platform_system, platform_machine)
    dependency_entries = _optional_dependency_entries(
        repo_root=root,
        environ=environ,
        runner=runner,
        which=which,
        timeout_seconds=timeout_seconds,
        selected_solvers=selected_solvers,
    )
    solvers_report = [
        _solver_entry(spec, platform_report=platform_report, dependency_entry=dependency_entries[spec.name])
        for spec in SOLVER_INSTALL_SPECS
        if spec.name in selected_solvers
    ]
    proof_lanes = [entry['proof_lane'] for entry in solvers_report]
    blockers = [entry['blocker'] for entry in solvers_report if entry.get('blocker')]
    degraded = [lane for lane in proof_lanes if lane['status'] == 'degraded']
    ready = [lane for lane in proof_lanes if lane['status'] == 'ready']

    if blockers:
        overall_status = 'blocked'
        security_decision = 'BLOCK_OPTIONAL_SOLVER_INSTALLATION_LANES'
    elif degraded:
        overall_status = 'degraded'
        security_decision = 'OPTIONAL_SOLVER_INSTALLATION_HAS_DEGRADED_LANES'
    else:
        overall_status = 'ready'
        security_decision = 'OPTIONAL_SOLVER_INSTALLATION_READY'

    return {
        'schema_version': SCHEMA_VERSION,
        'task_id': TASK_ID,
        'generated_at_utc': generated_at_utc or _utc_now(),
        'policy_document': POLICY_DOCUMENT,
        'dependency_probe_document': DEPENDENCY_PROBE_DOCUMENT,
        'repo_root': root.as_posix(),
        'default_mode': 'probe-and-plan-only',
        'commands_executed_by_default': 'version probes only',
        'overall_status': overall_status,
        'security_decision': security_decision,
        'platform': platform_report,
        'solvers': solvers_report,
        'proof_lanes': proof_lanes,
        'blockers': blockers,
        'summary': {
            'solver_count': len(solvers_report),
            'ready_lane_count': len(ready),
            'degraded_lane_count': len(degraded),
            'blocked_lane_count': len(blockers),
            'unsupported_platform_count': sum(1 for entry in solvers_report if not entry['platform_supported']),
            'missing_solver_count': sum(
                1
                for entry in solvers_report
                if entry['dependency_probe'].get('status') == 'missing'
            ),
            'unusable_solver_count': sum(
                1
                for entry in solvers_report
                if entry['dependency_probe'].get('status') not in {'present', 'missing'}
            ),
        },
        'acceptance_policy': {
            'silent_success_allowed': False,
            'missing_optional_solver_effect': 'degraded proof lane on supported platforms; missing-solver outcome for any claim that requires that lane',
            'unsupported_platform_effect': 'blocked proof lane until rerun on a supported Linux/macOS worker',
            'release_claim_rule': 'Do not claim solver-backed coverage unless the corresponding proof_lane.status is ready and the proof artifacts were produced.',
        },
    }


def write_report(report: Mapping[str, Any], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2, sort_keys=True) + '\n', encoding='utf-8')


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description='Plan installation and probe optional crypto-exchange theorem solvers.'
    )
    parser.add_argument('--repo-root', default=_repo_root().as_posix(), help='repository root')
    parser.add_argument('--out', default=DEFAULT_OUT.as_posix(), help='JSON report output path')
    parser.add_argument(
        '--timeout-seconds',
        type=int,
        default=DEFAULT_TIMEOUT_SECONDS,
        help='timeout for each version probe',
    )
    parser.add_argument(
        '--solver',
        action='append',
        choices=OPTIONAL_SOLVER_NAMES,
        help='optional solver to include; repeat to restrict the default all-solver report',
    )
    parser.add_argument('--platform-system', help='override detected platform system, for CI/testing')
    parser.add_argument('--platform-machine', help='override detected platform machine, for CI/testing')
    parser.add_argument(
        '--strict',
        action='store_true',
        help='return non-zero when the generated report has blocked lanes',
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    selected_solvers = tuple(args.solver) if args.solver else OPTIONAL_SOLVER_NAMES
    report = build_report(
        repo_root=Path(args.repo_root),
        timeout_seconds=args.timeout_seconds,
        platform_system=args.platform_system,
        platform_machine=args.platform_machine,
        solvers=selected_solvers,
    )
    out_path = Path(args.out)
    write_report(report, out_path)

    summary = report['summary']
    print(
        json.dumps(
            {
                'report': out_path.as_posix(),
                'overall_status': report['overall_status'],
                'security_decision': report['security_decision'],
                'ready_lane_count': summary['ready_lane_count'],
                'degraded_lane_count': summary['degraded_lane_count'],
                'blocked_lane_count': summary['blocked_lane_count'],
            },
            sort_keys=True,
        )
    )
    return 2 if args.strict and report['overall_status'] == 'blocked' else 0


if __name__ == '__main__':  # pragma: no cover
    raise SystemExit(main())
