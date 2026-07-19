"""Tests for the redacted native-vault fault-injection evidence contract."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

import pytest

from ipfs_datasets_py.logic.security_models.crypto_exchange.ir.cid import calculate_artifact_cid
from ipfs_datasets_py.logic.security_models.crypto_exchange.reports.xaman_native_vault_fault_injection import (
    NativeVaultFaultInjectionError,
    REQUIRED_CASES,
    build_fault_injection_plan,
    build_fault_injection_template,
    validate_fault_injection_report,
)


REPO_ROOT = Path(__file__).resolve().parents[4]
ASSESSMENT_PATH = REPO_ROOT / 'security_ir_artifacts/corpora/xaman-app/native-vault-public-source-assessment.json'
PLAN_PATH = REPO_ROOT / 'security_ir_artifacts/corpora/xaman-app/native-vault/fault-injection-plan.json'
TEMPLATE_PATH = REPO_ROOT / 'security_ir_artifacts/corpora/xaman-app/runtime/native-vault-rekey-fault-injection-template.json'
SCRIPT_PATH = REPO_ROOT / 'scripts/ops/security_verification/prepare_xaman_native_vault_fault_injection.py'


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode('ascii')).hexdigest()


def _assessment() -> dict[str, object]:
    return json.loads(ASSESSMENT_PATH.read_text(encoding='utf-8'))


def _report(plan: dict[str, object]) -> dict[str, object]:
    cases = []
    for ordinal, (case_id, platform, flow, fault_phase, fault_position) in enumerate(REQUIRED_CASES, start=1):
        cases.append({
            'case_id': case_id,
            'platform': platform,
            'flow': flow,
            'fault_phase': fault_phase,
            'fault_position': fault_position,
            'fault_injected': True,
            'native_operation_reports_failure': True,
            'primary_vault_absent_after_failure': fault_phase == 'replacement_write',
            'primary_vault_new_key_accessible': fault_phase == 'recovery_cleanup',
            'recovery_vault_present_after_failure': True,
            'old_key_recovers_vault': True,
            'new_key_does_not_open_old_key_recovery': True,
            'raw_sensitive_material_retained': False,
            'evidence_sha256': _digest(str(ordinal)),
        })
    payload: dict[str, object] = {
        'schema_version': 'xaman-native-vault-rekey-fault-injection-report/v1',
        'task_id': 'PORTAL-CXTP-163',
        'report_id': 'native-vault-fault-injection-001',
        'captured_at_utc': '2026-07-18T20:00:00Z',
        'reviewed_at_utc': '2026-07-18T20:05:00Z',
        'scope': {
            'public_source_verifier_only': True,
            'vendor_release_equivalent': False,
            'production_security_result': False,
        },
        'source_bindings': {
            'fault_injection_plan_cid': plan['artifact_cid'],
            'native_vault_assessment_cid': _assessment()['artifact_cid'],
            'source_commit': '942f43876265a7af44f233288ad2b1d00841d5fa',
        },
        'review_gate': {
            'review_decision_cid': plan['artifact_cid'],
            'decision': 'ALLOW_VERIFIER_ONLY_RUNTIME_CAPTURE',
            'expires_at_utc': '2027-07-18T20:05:00Z',
            'reviewer_id_sha256': _digest('reviewer'),
        },
        'cases': cases,
        'redaction': {
            'raw_sensitive_material_retained': False,
            'redaction_review_sha256': _digest('redaction'),
        },
    }
    payload['artifact_cid'] = calculate_artifact_cid(payload)
    return payload


def _load_script():
    spec = importlib.util.spec_from_file_location('prepare_xaman_native_vault_fault_injection', SCRIPT_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_prepared_plan_binds_exact_source_windows_and_preserves_boundary() -> None:
    plan = build_fault_injection_plan(_assessment())

    assert plan['plan_status'] == 'PREPARED_NOT_RUNTIME_EVIDENCE'
    assert plan['scope']['runtime_capture_recorded'] is False
    assert len(plan['fault_injection_points']) == 2
    assert len(plan['required_cases']) == 12
    assert [item['platform'] for item in plan['fault_injection_points']] == ['android', 'ios']
    for item in plan['fault_injection_points']:
        markers = [entry['marker'] for entry in item['source_order']]
        assert markers[-1].endswith('finally remove the created recovery vault')
        assert markers[1] in {'purgeVault(vaultName);', '[VaultManagerModule purgeVault:vaultName];'}
    assert build_fault_injection_template(plan)['template_status'] == 'NOT_RUNTIME_EVIDENCE'


def test_checked_in_plan_and_template_are_current_and_non_evidence() -> None:
    plan = json.loads(PLAN_PATH.read_text(encoding='utf-8'))
    template = json.loads(TEMPLATE_PATH.read_text(encoding='utf-8'))

    assert plan == build_fault_injection_plan(_assessment())
    assert plan['artifact_cid'] == calculate_artifact_cid({key: value for key, value in plan.items() if key != 'artifact_cid'})
    assert template == build_fault_injection_template(plan)
    assert template['template_status'] == 'NOT_RUNTIME_EVIDENCE'


def test_reviewed_complete_report_can_be_validated_without_promoting_production() -> None:
    plan = build_fault_injection_plan(_assessment())
    report = _report(plan)

    validate_fault_injection_report(report, now=datetime(2026, 7, 18, 21, 0, tzinfo=timezone.utc))
    assert report['scope']['vendor_release_equivalent'] is False


@pytest.mark.parametrize(
    ('mutator', 'message'),
    [
        (lambda report: report['review_gate'].__setitem__('decision', 'PENDING'), 'does not authorize'),
        (lambda report: report['cases'].pop(), 'every required'),
        (lambda report: report['cases'][0].__setitem__('raw_sensitive_material_retained', True), 'does not satisfy'),
        (lambda report: next(case for case in report['cases'] if case['fault_phase'] == 'recovery_cleanup').__setitem__('primary_vault_new_key_accessible', False), 'does not satisfy'),
        (lambda report: report.__setitem__('raw_log', 'not-permitted'), 'unexpected'),
    ],
)
def test_incomplete_or_unsafe_runtime_claims_fail_closed(mutator, message: str) -> None:
    report = _report(build_fault_injection_plan(_assessment()))
    mutator(report)
    report['artifact_cid'] = calculate_artifact_cid({key: value for key, value in report.items() if key != 'artifact_cid'})
    with pytest.raises(NativeVaultFaultInjectionError, match=message):
        validate_fault_injection_report(report, now=datetime(2026, 7, 18, 21, 0, tzinfo=timezone.utc))


def test_script_writes_only_plan_and_non_evidence_template(tmp_path: Path) -> None:
    module = _load_script()
    plan = tmp_path / 'plan.json'
    template = tmp_path / 'template.json'

    assert module.main(['--repo-root', str(REPO_ROOT), '--plan-out', str(plan), '--template-out', str(template)]) == 0
    assert json.loads(plan.read_text(encoding='utf-8'))['plan_status'] == 'PREPARED_NOT_RUNTIME_EVIDENCE'
    assert json.loads(template.read_text(encoding='utf-8'))['template_status'] == 'NOT_RUNTIME_EVIDENCE'
