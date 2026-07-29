from __future__ import annotations

import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[4]
SCRIPT_PATH = ROOT / 'scripts/ops/security_verification/probe_lean_solver_lane.py'
REPORT_PATH = ROOT / 'security_ir_artifacts/environment/lean-solver-lane-report.json'
KERNEL_PATH = ROOT / 'security_ir_artifacts/corpora/xaman-app/proof-kernel/XamanReceipt.lean'
PROOF_CONSUMER_REPORT_PATH = (
    ROOT / 'security_ir_artifacts/corpora/xaman-app/proof-kernel/proof-consumer-report.json'
)
DOC_PATH = ROOT / 'docs/security_verification/lean_proof_consumer_solver_lane.md'


def _module():
    spec = importlib.util.spec_from_file_location('probe_lean_solver_lane', SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding='utf-8'))


def test_lean_solver_lane_probe_reports_ready_for_current_kernel() -> None:
    module = _module()

    report = module.build_lean_solver_lane_report(
        repo_root=ROOT,
        kernel_path=KERNEL_PATH,
        proof_consumer_report_path=PROOF_CONSUMER_REPORT_PATH,
    )

    assert report['task_id'] == 'PORTAL-CXTP-090'
    assert report['schema_version'] == 'crypto-exchange-lean-solver-lane-report/v1'
    assert report['overall_status'] == 'ready'
    assert report['security_decision'] == 'LEAN_SOLVER_LANE_READY'
    assert report['summary']['lean_present'] is True
    assert report['summary']['lake_present'] is True
    assert report['summary']['proof_kernel_checked'] is True
    assert report['summary']['blocker_count'] == 0
    assert report['proof_kernel_check']['returncode'] == 0
    assert report['proof_consumer_report']['security_decision'] == (
        'LEAN_PROOF_CONSUMER_KERNEL_CHECKED_RELEASE_STILL_BLOCKED_BY_INTEGRATION_AND_ASSUMPTIONS'
    )
    assert report['artifact_cid'].startswith('sha256:')


def test_lean_solver_lane_probe_fails_closed_when_toolchain_is_missing(monkeypatch) -> None:
    module = _module()
    monkeypatch.setenv('PATH', '/path/that/does/not/exist')

    report = module.build_lean_solver_lane_report(
        repo_root=ROOT,
        kernel_path=KERNEL_PATH,
        proof_consumer_report_path=PROOF_CONSUMER_REPORT_PATH,
    )

    codes = {blocker['code'] for blocker in report['blockers']}
    assert report['overall_status'] == 'blocked'
    assert report['security_decision'] == 'BLOCK_LEAN_SOLVER_LANE_NOT_READY'
    assert 'LEAN_EXECUTABLE_MISSING' in codes
    assert 'LAKE_EXECUTABLE_MISSING' in codes
    assert report['summary']['proof_kernel_checked'] is False


def test_lean_solver_lane_cli_writes_report(tmp_path: Path) -> None:
    module = _module()
    out = tmp_path / 'lean-solver-lane-report.json'

    exit_code = module.main(['--out', str(out)])

    assert exit_code == 0
    payload = _json(out)
    assert payload['task_id'] == 'PORTAL-CXTP-090'
    assert payload['summary']['proof_kernel_checked'] is True


def test_persisted_lean_solver_lane_report_is_ready() -> None:
    report = _json(REPORT_PATH)

    assert report['task_id'] == 'PORTAL-CXTP-090'
    assert report['overall_status'] == 'ready'
    assert report['security_decision'] == 'LEAN_SOLVER_LANE_READY'
    assert report['summary']['blocker_count'] == 0
    assert report['proof_kernel']['exists'] is True
    assert report['proof_consumer_report']['exists'] is True
    assert report['proof_kernel_check']['status'] == 'passed'


def test_lean_solver_lane_documentation_describes_fail_closed_semantics() -> None:
    doc = DOC_PATH.read_text(encoding='utf-8')

    assert 'PORTAL-CXTP-090' in doc
    assert 'XamanReceipt.lean' in doc
    assert 'overall_status: ready' in doc
    assert 'does not mean Xaman is secure or release-ready' in doc
    assert 'must not treat a report file by itself as evidence' in doc
