"""Tests for PORTAL-CXTP-090 Lean proof-consumer solver lane."""

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
    / 'probe_lean_solver_lane.py'
)
DOC_PATH = REPO_ROOT / 'docs' / 'security_verification' / 'lean_proof_consumer_solver_lane.md'
ARTIFACT_PATH = (
    REPO_ROOT
    / 'security_ir_artifacts'
    / 'environment'
    / 'lean-solver-lane-report.json'
)


def _load_script_module():
    spec = importlib.util.spec_from_file_location(
        'probe_lean_solver_lane',
        SCRIPT_PATH,
    )
    if spec is None or spec.loader is None:  # pragma: no cover
        raise AssertionError('failed to load Lean solver lane probe')
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _successful_runner(command: Sequence[str], timeout_seconds: int) -> dict[str, object]:
    executable = Path(command[0]).name
    args = tuple(command[1:])
    if executable == 'lean' and args == ('--version',):
        stdout = 'Lean (version 4.31.0, x86_64-unknown-linux-gnu, commit abcdef)'
    elif executable == 'lean' and args == ('--print-prefix',):
        stdout = '/home/me/.elan/toolchains/leanprover--lean4---v4.31.0'
    elif executable == 'lean' and args == ('--print-libdir',):
        stdout = '/home/me/.elan/toolchains/leanprover--lean4---v4.31.0/lib/lean'
    elif executable == 'lake':
        stdout = 'Lake version 5.0.0 (Lean version 4.31.0)'
    elif executable == 'elan':
        stdout = 'elan 4.2.3'
    elif executable == 'lean' and command[1].endswith('XamanReceipt.lean'):
        stdout = ''
    else:  # pragma: no cover
        raise AssertionError(f'unexpected command: {command!r}')
    return {
        'exit_code': 0,
        'stdout': stdout,
        'stderr': '',
        'timed_out': False,
        'error': None,
    }


def _write_fixture_artifacts(tmp_path: Path) -> tuple[Path, Path]:
    kernel_path = Path('proof-kernel') / 'XamanReceipt.lean'
    report_path = Path('proof-kernel') / 'proof-consumer-report.json'
    absolute_kernel = tmp_path / kernel_path
    absolute_report = tmp_path / report_path
    absolute_kernel.parent.mkdir(parents=True, exist_ok=True)
    absolute_kernel.write_text('namespace XamanReceipt\n#check True\nend XamanReceipt\n', encoding='utf-8')
    absolute_report.write_text(
        json.dumps(
            {
                'schema_version': 'xaman-proof-consumer-report/v1',
                'claim_id': 'xaman-security:claim:proof-consumers-fail-closed-for-xaman-security-claims',
                'model_cid': 'cid:fixture',
                'artifact_cid': 'cid:report',
                'proof_kernel_cid': 'cid:kernel',
                'rejected_fixtures': [
                    {'outcome': 'DISPROVED'},
                    {'outcome': 'UNKNOWN'},
                    {'outcome': 'NOT_MODELED'},
                    {'outcome': 'MISSING_SOLVER'},
                ],
            }
        )
        + '\n',
        encoding='utf-8',
    )
    return kernel_path, report_path


def test_missing_lean_degrades_lane_and_emits_reproducible_guidance() -> None:
    module = _load_script_module()

    report = module.build_report(
        repo_root=REPO_ROOT,
        environ={'PATH': '/usr/bin', 'PYTHONPATH': '.'},
        runner=_successful_runner,
        which=lambda candidate: None,
        generated_at_utc='2026-07-08T00:00:00Z',
        platform_system='Linux',
        platform_machine='x86_64',
    )

    assert report['schema_version'] == 'crypto-exchange-lean-solver-lane-report/v1'
    assert report['task_id'] == 'PORTAL-CXTP-090'
    assert report['overall_status'] == 'degraded'
    assert report['security_decision'] == 'DEGRADE_OPTIONAL_SOLVER_LANE_MISSING_SOLVER'
    assert report['proof_lane']['lane_id'] == 'lean_proof_consumer_invariants'
    assert report['proof_lane']['missing_solver_outcome'] == 'missing-solver'
    assert report['proof_consumer_claims']['silent_acceptance_allowed'] is False
    assert report['proof_consumer_claims']['receipt_acceptance'] == 'blocked-or-degraded-no-lean-receipt'
    assert report['acceptance_policy']['silent_success_allowed'] is False

    guidance = report['installation_guidance']
    assert guidance['reproducible'] is True
    assert guidance['pinned_toolchain'] == 'leanprover/lean4:v4.31.0'
    commands = [entry['command'] for entry in guidance['commands']]
    assert any('leanprover/lean4:v4.31.0' in command for command in commands)
    assert not any('leanprover/lean4:stable' in command for command in commands)


def test_ready_lane_records_exact_versions_paths_and_checks_kernel(tmp_path: Path) -> None:
    module = _load_script_module()
    kernel_path, report_path = _write_fixture_artifacts(tmp_path)
    available = {
        'lean': '/home/me/.elan/bin/lean',
        'lake': '/home/me/.elan/bin/lake',
        'elan': '/home/me/.elan/bin/elan',
    }

    report = module.build_report(
        repo_root=tmp_path,
        environ={'PATH': '/usr/bin', 'PYTHONPATH': '.'},
        runner=_successful_runner,
        which=lambda candidate: available.get(candidate),
        generated_at_utc='2026-07-08T00:00:00Z',
        platform_system='Linux',
        platform_machine='x86_64',
        proof_kernel_path=kernel_path,
        proof_consumer_report_path=report_path,
    )

    assert report['overall_status'] == 'ready'
    assert report['security_decision'] == 'OPTIONAL_SOLVER_LANE_READY'
    assert report['proof_lane']['release_effect'] == 'coverage-available'
    assert report['tools']['lean']['version'] == '4.31.0'
    assert report['tools']['lean']['version_raw'].startswith('Lean (version 4.31.0')
    assert report['tools']['lake']['executable'] == '/home/me/.elan/bin/lake'
    assert report['tools']['lake']['version'] == '5.0.0'
    assert report['tools']['elan']['version'] == '4.2.3'
    assert report['toolchain_paths']['lean_prefix']['value'].endswith('v4.31.0')
    assert report['toolchain_paths']['lean_libdir']['value'].endswith('/lib/lean')
    assert report['toolchain_paths']['lake_executable'] == '/home/me/.elan/bin/lake'
    assert report['proof_kernel_check']['status'] == 'checked'
    assert report['proof_kernel_check']['sha256']
    assert report['proof_consumer_claims']['claim_status'] == 'claimable-with-lean-receipt'
    assert report['proof_consumer_claims']['receipt_acceptance'] == (
        'allowed-only-after-matching-lean-kernel-check'
    )


def test_unusable_discovered_lean_blocks_lane_without_reporting_lean_version() -> None:
    module = _load_script_module()

    def failing_runner(command: Sequence[str], timeout_seconds: int) -> dict[str, object]:
        return {
            'exit_code': None,
            'stdout': '',
            'stderr': 'info: Version 4.2.3 of elan is available',
            'timed_out': True,
            'error': 'timeout',
        }

    report = module.build_report(
        repo_root=REPO_ROOT,
        environ={'PATH': '/usr/bin', 'PYTHONPATH': '.'},
        runner=failing_runner,
        which=lambda candidate: '/home/me/.elan/bin/lean' if candidate == 'lean' else None,
        generated_at_utc='2026-07-08T00:00:00Z',
        platform_system='Linux',
        platform_machine='x86_64',
    )

    assert report['overall_status'] == 'blocked'
    assert report['security_decision'] == 'BLOCK_OPTIONAL_SOLVER_LANE'
    assert report['tools']['lean']['status'] == 'error'
    assert report['tools']['lean']['version'] is None
    assert {blocker['code'] for blocker in report['blockers']} == {'LEAN_EXECUTABLE_UNUSABLE'}
    assert report['proof_consumer_claims']['missing_lean_receipt_outcome'] == 'missing-solver'


def test_missing_lake_degrades_even_when_standalone_lean_kernel_checks(tmp_path: Path) -> None:
    module = _load_script_module()
    kernel_path, report_path = _write_fixture_artifacts(tmp_path)

    report = module.build_report(
        repo_root=tmp_path,
        environ={'PATH': '/usr/bin', 'PYTHONPATH': '.'},
        runner=_successful_runner,
        which=lambda candidate: {
            'lean': '/home/me/.elan/bin/lean',
            'elan': '/home/me/.elan/bin/elan',
        }.get(candidate),
        generated_at_utc='2026-07-08T00:00:00Z',
        platform_system='Linux',
        platform_machine='x86_64',
        proof_kernel_path=kernel_path,
        proof_consumer_report_path=report_path,
    )

    assert report['overall_status'] == 'degraded'
    assert report['tools']['lean']['status'] == 'present'
    assert report['tools']['lake']['status'] == 'missing'
    assert report['proof_kernel_check']['status'] == 'checked'
    assert report['degraded_reasons'] == [
        {
            'code': 'LAKE_EXECUTABLE_MISSING',
            'component': 'lake',
            'effect': 'lean-kernel-only-without-lake-project-checks',
        }
    ]


def test_cli_writes_report_and_returns_zero_for_degraded_or_blocked_lane(tmp_path: Path) -> None:
    module = _load_script_module()
    out_path = tmp_path / 'lean-lane.json'

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
    assert report['schema_version'] == 'crypto-exchange-lean-solver-lane-report/v1'
    assert report['task_id'] == 'PORTAL-CXTP-090'
    assert report['overall_status'] in {'ready', 'degraded', 'blocked'}
    assert report['proof_lane']['missing_solver_outcome'] in {'missing-solver', None}
    assert report['acceptance_policy']['silent_success_allowed'] is False


def test_checked_in_artifact_and_doc_cover_required_outputs() -> None:
    report = json.loads(ARTIFACT_PATH.read_text(encoding='utf-8'))
    doc = DOC_PATH.read_text(encoding='utf-8')

    assert report['schema_version'] == 'crypto-exchange-lean-solver-lane-report/v1'
    assert report['task_id'] == 'PORTAL-CXTP-090'
    assert report['policy_document'] == 'docs/security_verification/lean_proof_consumer_solver_lane.md'
    assert report['proof_lane']['lane_id'] == 'lean_proof_consumer_invariants'
    assert report['proof_lane']['status'] in {'ready', 'degraded', 'blocked'}
    assert report['proof_lane']['release_effect'] in {
        'coverage-available',
        'degraded-optional-coverage',
        'blocked-proof-lane',
    }
    assert report['acceptance_policy']['silent_success_allowed'] is False
    assert report['installation_guidance']['reproducible'] is True
    assert report['installation_guidance']['pinned_toolchain'] == 'leanprover/lean4:v4.31.0'
    assert report['tools']['lean']['status'] in {'present', 'missing', 'error'}
    assert 'lake' in report['tools']
    assert 'toolchain_paths' in report
    assert report['proof_consumer_claims']['silent_acceptance_allowed'] is False
    assert report['proof_consumer_claims']['missing_lean_receipt_outcome'] == 'missing-solver'

    assert 'lean_proof_consumer_invariants' in doc
    assert 'missing-solver' in doc
    assert 'degraded' in doc
    assert 'blocked' in doc
    assert 'leanprover/lean4:v4.31.0' in doc
