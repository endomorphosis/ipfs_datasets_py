"""Tests for PORTAL-CXTP-086 optional theorem-solver installer."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
from typing import Sequence


REPO_ROOT = Path(__file__).resolve().parents[4]
SCRIPT_PATH = (
    REPO_ROOT
    / 'scripts'
    / 'ops'
    / 'security_verification'
    / 'install_optional_theorem_solvers.py'
)
DOC_PATH = REPO_ROOT / 'docs' / 'security_verification' / 'optional_solver_installation.md'
ARTIFACT_PATH = (
    REPO_ROOT
    / 'security_ir_artifacts'
    / 'environment'
    / 'optional-solver-install-report.json'
)


def _load_script_module():
    spec = importlib.util.spec_from_file_location(
        'install_optional_theorem_solvers',
        SCRIPT_PATH,
    )
    if spec is None or spec.loader is None:  # pragma: no cover
        raise AssertionError('failed to load optional solver installer')
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _fake_runner(command: Sequence[str], timeout_seconds: int) -> dict[str, object]:
    executable = Path(command[0]).name
    outputs = {
        'apalache-mc': 'Apalache 0.50.0',
        'tamarin-prover': 'tamarin-prover 1.10.0',
        'proverif': 'ProVerif 2.05',
        'lean': 'Lean (version 4.12.0, x86_64-unknown-linux-gnu)',
        'coqc': 'The Coq Proof Assistant, version 8.20.0',
    }
    return {
        'exit_code': 0,
        'stdout': outputs.get(executable, f'{executable} version 1.0.0'),
        'stderr': '',
        'timed_out': False,
        'error': None,
    }


def test_build_report_records_safe_commands_for_every_optional_solver() -> None:
    module = _load_script_module()
    report = module.build_report(
        repo_root=REPO_ROOT,
        environ={'PATH': '/usr/bin', 'PYTHONPATH': '.'},
        runner=_fake_runner,
        which=lambda candidate: None,
        generated_at_utc='2026-07-08T00:00:00Z',
        platform_system='Linux',
        platform_machine='x86_64',
    )

    assert report['schema_version'] == 'crypto-exchange-optional-solver-install-report/v1'
    assert report['task_id'] == 'PORTAL-CXTP-086'
    assert report['default_mode'] == 'probe-and-plan-only'
    assert report['commands_executed_by_default'] == 'version probes only'
    assert report['overall_status'] == 'degraded'
    assert report['security_decision'] == 'OPTIONAL_SOLVER_INSTALLATION_HAS_DEGRADED_LANES'
    assert report['acceptance_policy']['silent_success_allowed'] is False

    solvers = {solver['name']: solver for solver in report['solvers']}
    assert set(solvers) == {'apalache', 'tamarin', 'proverif', 'lean', 'coq'}
    for name, solver in solvers.items():
        assert solver['platform_supported'] is True
        assert solver['install_commands'], name
        assert solver['probe_commands'], name
        assert all(command['review_required'] for command in solver['install_commands'])
        assert all(command['destructive'] is False for command in solver['install_commands'])
        assert solver['proof_lane']['status'] == 'degraded'
        assert solver['proof_lane']['missing_solver_outcome'] == 'missing-solver'
        assert solver['proof_lane']['release_effect'] == 'degraded-optional-coverage'


def test_present_solvers_make_corresponding_lanes_ready() -> None:
    module = _load_script_module()
    available = {
        'apalache-mc': '/opt/apalache/bin/apalache-mc',
        'tamarin-prover': '/usr/local/bin/tamarin-prover',
        'proverif': '/usr/local/bin/proverif',
        'lean': '/home/me/.elan/bin/lean',
        'coqc': '/home/me/.opam/default/bin/coqc',
    }

    report = module.build_report(
        repo_root=REPO_ROOT,
        environ={'PATH': '/usr/bin', 'PYTHONPATH': '.'},
        runner=_fake_runner,
        which=lambda candidate: available.get(candidate),
        generated_at_utc='2026-07-08T00:00:00Z',
        platform_system='Linux',
        platform_machine='x86_64',
    )

    assert report['overall_status'] == 'ready'
    assert report['security_decision'] == 'OPTIONAL_SOLVER_INSTALLATION_READY'
    assert report['summary']['ready_lane_count'] == 5
    assert report['summary']['degraded_lane_count'] == 0
    assert report['blockers'] == []
    assert {
        lane['security_decision'] for lane in report['proof_lanes']
    } == {'OPTIONAL_SOLVER_LANE_READY'}


def test_unsupported_platform_blocks_lanes_and_records_remediation() -> None:
    module = _load_script_module()

    report = module.build_report(
        repo_root=REPO_ROOT,
        environ={'PATH': '/usr/bin', 'PYTHONPATH': '.'},
        runner=_fake_runner,
        which=lambda candidate: None,
        generated_at_utc='2026-07-08T00:00:00Z',
        platform_system='Windows',
        platform_machine='AMD64',
    )

    assert report['overall_status'] == 'blocked'
    assert report['security_decision'] == 'BLOCK_OPTIONAL_SOLVER_INSTALLATION_LANES'
    assert report['platform']['support_level'] == 'unsupported-native'
    assert report['summary']['unsupported_platform_count'] == 5
    assert report['summary']['blocked_lane_count'] == 5
    assert {
        blocker['code'] for blocker in report['blockers']
    } == {'OPTIONAL_SOLVER_PLATFORM_UNSUPPORTED'}
    assert all(solver['unsupported_platforms'] for solver in report['solvers'])
    assert all(lane['release_effect'] == 'blocked-proof-lane' for lane in report['proof_lanes'])


def test_unusable_discovered_solver_blocks_that_lane() -> None:
    module = _load_script_module()

    def failing_runner(command: Sequence[str], timeout_seconds: int) -> dict[str, object]:
        return {
            'exit_code': 1,
            'stdout': '',
            'stderr': 'broken install',
            'timed_out': False,
            'error': None,
        }

    report = module.build_report(
        repo_root=REPO_ROOT,
        environ={'PATH': '/usr/bin', 'PYTHONPATH': '.'},
        runner=failing_runner,
        which=lambda candidate: '/usr/local/bin/apalache-mc' if candidate == 'apalache-mc' else None,
        generated_at_utc='2026-07-08T00:00:00Z',
        platform_system='Linux',
        platform_machine='x86_64',
        solvers=('apalache',),
    )

    assert report['overall_status'] == 'blocked'
    assert report['summary']['blocked_lane_count'] == 1
    assert report['solvers'][0]['dependency_probe']['status'] == 'error'
    assert report['solvers'][0]['blocker']['code'] == 'OPTIONAL_SOLVER_UNUSABLE'
    assert report['proof_lanes'][0]['security_decision'] == 'BLOCK_OPTIONAL_SOLVER_LANE'


def test_cli_writes_report_and_stays_zero_for_degraded_supported_platform(tmp_path: Path) -> None:
    module = _load_script_module()
    out_path = tmp_path / 'optional-solvers.json'

    rc = module.main(
        [
            '--repo-root',
            REPO_ROOT.as_posix(),
            '--out',
            out_path.as_posix(),
            '--platform-system',
            'Linux',
            '--platform-machine',
            'x86_64',
            '--timeout-seconds',
            '1',
        ]
    )

    report = json.loads(out_path.read_text(encoding='utf-8'))
    assert rc == 0
    assert report['schema_version'] == 'crypto-exchange-optional-solver-install-report/v1'
    assert report['task_id'] == 'PORTAL-CXTP-086'
    assert {solver['name'] for solver in report['solvers']} == {
        'apalache',
        'tamarin',
        'proverif',
        'lean',
        'coq',
    }


def test_checked_in_artifact_and_doc_cover_required_outputs() -> None:
    report = json.loads(ARTIFACT_PATH.read_text(encoding='utf-8'))
    doc = DOC_PATH.read_text(encoding='utf-8')

    assert report['schema_version'] == 'crypto-exchange-optional-solver-install-report/v1'
    assert report['task_id'] == 'PORTAL-CXTP-086'
    assert report['policy_document'] == 'docs/security_verification/optional_solver_installation.md'
    assert isinstance(report['proof_lanes'], list)
    assert report['acceptance_policy']['silent_success_allowed'] is False

    solvers = {solver['name']: solver for solver in report['solvers']}
    for name in ('apalache', 'tamarin', 'proverif', 'lean', 'coq'):
        assert name in solvers
        assert solvers[name]['install_commands']
        assert solvers[name]['probe_commands']
        assert solvers[name]['proof_lane']['status'] in {'ready', 'degraded', 'blocked'}
        assert name.capitalize() in doc or solvers[name]['display_name'] in doc

    assert 'missing-solver' in doc
    assert 'degraded' in doc
    assert 'blocked' in doc
