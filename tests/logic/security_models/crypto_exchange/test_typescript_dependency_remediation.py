"""Tests for PORTAL-CXTP-089 TypeScript dependency remediation."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
from typing import Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[4]
SCRIPT_PATH = (
    REPO_ROOT
    / 'scripts'
    / 'ops'
    / 'security_verification'
    / 'provision_required_typescript_toolchain.py'
)
DOC_PATH = REPO_ROOT / 'docs' / 'security_verification' / 'typescript_solver_dependency_remediation.md'
REPORT_PATH = REPO_ROOT / 'security_ir_artifacts' / 'environment' / 'typescript-remediation-report.json'


def _load_script_module():
    spec = importlib.util.spec_from_file_location(
        'provision_required_typescript_toolchain',
        SCRIPT_PATH,
    )
    if spec is None or spec.loader is None:  # pragma: no cover
        raise AssertionError('failed to load TypeScript remediation script')
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + '\n', encoding='utf-8')


def _fake_runner(command: Sequence[str], timeout_seconds: int, environ: Mapping[str, str]) -> dict[str, object]:
    assert command[-1] == '--version'
    assert 'typescript_toolchain/node_modules/.bin' in environ['PATH']
    return {
        'exit_code': 0,
        'stdout': 'Version 5.5.4\n',
        'stderr': '',
        'timed_out': False,
        'error': None,
    }


def _fake_probe_builder(**kwargs) -> dict:
    return {
        'schema_version': 'crypto-exchange-solver-dependency-probe/v1',
        'task_id': 'PORTAL-CXTP-058',
        'overall_status': 'ready',
        'proof_acceptance_blocked': False,
        'blocking_evidence': [],
        'optional_capability_gaps': [{'component': 'apalache'}],
        'dependencies': [
            {
                'name': 'typescript',
                'status': 'present',
                'executable': 'security_ir_artifacts/environment/typescript_toolchain/node_modules/.bin/tsc',
            }
        ],
    }


def test_missing_repo_scoped_tsc_blocks_remediation(tmp_path: Path) -> None:
    module = _load_script_module()
    probe = tmp_path / 'probe.json'
    _write_json(
        probe,
        {
            'dependencies': [{'name': 'typescript', 'status': 'missing'}],
            'blocking_evidence': [{'component': 'typescript'}],
        },
    )

    report, refreshed = module.build_report(
        repo_root=tmp_path,
        probe_path=probe,
        toolchain_dir=tmp_path / 'typescript_toolchain',
        runner=_fake_runner,
        probe_builder=_fake_probe_builder,
        generated_at_utc='2026-07-10T00:00:00Z',
    )

    assert refreshed is None
    assert report['overall_status'] == 'blocked'
    assert report['typescript']['status'] == 'missing'
    assert {blocker['code'] for blocker in report['blockers']} == {'REPO_SCOPED_TSC_MISSING'}


def test_repo_scoped_tsc_refreshes_probe_and_removes_blocker(tmp_path: Path) -> None:
    module = _load_script_module()
    toolchain = tmp_path / 'security_ir_artifacts' / 'environment' / 'typescript_toolchain'
    tsc = toolchain / 'node_modules' / '.bin' / 'tsc'
    tsc.parent.mkdir(parents=True)
    tsc.write_text('#!/usr/bin/env node\n', encoding='utf-8')
    probe = tmp_path / 'probe.json'
    _write_json(
        probe,
        {
            'dependencies': [{'name': 'typescript', 'status': 'missing'}],
            'blocking_evidence': [{'component': 'typescript'}],
        },
    )

    report, refreshed = module.build_report(
        repo_root=tmp_path,
        probe_path=probe,
        toolchain_dir=toolchain,
        environ={'PATH': '/usr/bin', 'PYTHONPATH': '.'},
        runner=_fake_runner,
        probe_builder=_fake_probe_builder,
        generated_at_utc='2026-07-10T00:00:00Z',
    )

    assert refreshed is not None
    assert report['overall_status'] == 'ready'
    assert report['security_decision'] == 'TYPESCRIPT_DEPENDENCY_REMEDIATED'
    assert report['typescript']['version'] == '5.5.4'
    assert report['probe_refresh']['typescript_status_before'] == 'missing'
    assert report['probe_refresh']['typescript_status_after'] == 'present'
    assert report['summary']['typescript_blocker_removed'] is True
    assert report['summary']['required_blocking_components_remaining'] == []


def test_checked_in_remediation_report_records_ready_typescript() -> None:
    report = json.loads(REPORT_PATH.read_text(encoding='utf-8'))

    assert report['schema_version'] == 'crypto-exchange-typescript-remediation/v1'
    assert report['task_id'] == 'PORTAL-CXTP-089'
    assert report['overall_status'] == 'ready'
    assert report['typescript']['status'] == 'present'
    assert report['summary']['typescript_blocker_removed'] is True
    assert 'typescript' not in report['summary']['required_blocking_components_remaining']


def test_document_records_repo_scoped_toolchain_and_validation_command() -> None:
    doc = DOC_PATH.read_text(encoding='utf-8')

    assert 'PORTAL-CXTP-089' in doc
    assert 'security_ir_artifacts/environment/typescript_toolchain/node_modules/.bin/tsc' in doc
    assert 'provision_required_typescript_toolchain.py' in doc
    assert 'typescript-remediation-report.json' in doc
