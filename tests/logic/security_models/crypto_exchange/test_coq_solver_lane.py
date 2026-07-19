from __future__ import annotations

import importlib.util
import json
import stat
from pathlib import Path


ROOT = Path(__file__).resolve().parents[4]
SCRIPT_PATH = ROOT / 'scripts/ops/security_verification/probe_coq_solver_lane.py'
REPORT_PATH = ROOT / 'security_ir_artifacts/environment/coq-solver-lane-report.json'
DOC_PATH = ROOT / 'docs/security_verification/coq_proof_kernel_solver_lane.md'


def _module():
    spec = importlib.util.spec_from_file_location('probe_coq_solver_lane', SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding='utf-8'))


def _fake_executable(directory: Path, name: str, output: str = '') -> Path:
    executable = directory / name
    executable.write_text(
        '#!/bin/sh\n'
        f'printf "%s\\n" "{output}"\n',
        encoding='utf-8',
    )
    executable.chmod(executable.stat().st_mode | stat.S_IXUSR)
    return executable


def test_coq_solver_lane_probe_blocks_when_coq_artifacts_are_missing() -> None:
    module = _module()
    fake_coq_missing_kernel = Path('/tmp/does-not-exist-coq-kernel.v')
    report = module.build_coq_solver_lane_report(
        repo_root=ROOT,
        coq_kernel_path=fake_coq_missing_kernel,
    )

    assert report['task_id'] == 'PORTAL-CXTP-093'
    assert report['schema_version'] == 'crypto-exchange-coq-solver-lane-report/v1'
    assert report['overall_status'] == 'blocked_optional_lane'
    assert report['security_decision'] == 'BLOCK_COQ_SOLVER_LANE_UNAVAILABLE'
    assert report['summary']['coq_kernel_checked'] is False
    assert report['production_release_blocked_by_coq_lane'] is True
    assert report['artifact_cid'].startswith('sha256:')

    codes = {blocker['code'] for blocker in report['blockers']}
    assert 'COQ_KERNEL_ARTIFACT_MISSING' in codes


def test_coq_solver_lane_probe_can_report_ready_with_fake_toolchain(
    tmp_path: Path,
    monkeypatch,
) -> None:
    module = _module()
    bin_dir = tmp_path / 'bin'
    bin_dir.mkdir()
    _fake_executable(bin_dir, 'coqc', 'The Coq Proof Assistant, version 8.fixture')
    _fake_executable(bin_dir, 'coqtop', 'The Coq Proof Assistant, version 8.fixture')
    _fake_executable(bin_dir, 'opam', '2.fixture')
    monkeypatch.setenv('PATH', bin_dir.as_posix())
    coq_kernel = tmp_path / 'XamanReceipt.v'
    coq_kernel.write_text('(* fixture Coq kernel *)\n', encoding='utf-8')

    report = module.build_coq_solver_lane_report(
        repo_root=ROOT,
        coq_kernel_path=coq_kernel,
    )

    assert report['overall_status'] == 'ready'
    assert report['security_decision'] == 'COQ_SOLVER_LANE_READY'
    assert report['summary']['coqc_present'] is True
    assert report['summary']['coq_kernel_present'] is True
    assert report['summary']['coq_kernel_checked'] is True
    assert report['blockers'] == []


def test_coq_solver_lane_cli_writes_report(tmp_path: Path) -> None:
    module = _module()
    out = tmp_path / 'coq-solver-lane-report.json'

    exit_code = module.main(['--out', str(out)])

    assert exit_code == 0
    payload = _json(out)
    assert payload['task_id'] == 'PORTAL-CXTP-093'
    assert payload['overall_status'] in {'ready', 'blocked_optional_lane'}


def test_persisted_coq_solver_lane_report_is_fail_closed() -> None:
    report = _json(REPORT_PATH)

    assert report['task_id'] == 'PORTAL-CXTP-093'
    if report['overall_status'] == 'ready':
        assert report['security_decision'] == 'COQ_SOLVER_LANE_READY'
        assert report['summary']['blocker_count'] == 0
        assert report['summary']['coq_kernel_checked'] is True
        assert report['coq_kernel_check']['status'] == 'passed'
    else:
        assert report['overall_status'] == 'blocked_optional_lane'
        assert report['security_decision'] == 'BLOCK_COQ_SOLVER_LANE_UNAVAILABLE'
        assert report['summary']['blocker_count'] >= 1
        assert report['coq_kernel']['exists'] is False
        assert report['coq_kernel_check']['status'] == 'not-run'


def test_coq_solver_lane_documentation_includes_remediation_and_scope() -> None:
    doc = DOC_PATH.read_text(encoding='utf-8')

    assert 'PORTAL-CXTP-093' in doc
    assert 'blocked_optional_lane' in doc
    assert 'sudo apt-get install -y coq' in doc
    assert 'opam install coq' in doc
    assert 'does not invalidate the checked Lean kernel' in doc
