"""Tests for the fail-closed self-hosted Xaman runtime-trace contract."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

import pytest

from ipfs_datasets_py.logic.security_models.crypto_exchange.ir.cid import calculate_artifact_cid
from ipfs_datasets_py.logic.security_models.crypto_exchange.reports.xaman_self_hosted_runtime_trace import (
    REQUIRED_ACTIONS,
    SelfHostedRuntimeTraceError,
    build_runtime_conformance_report,
    validate_runtime_trace,
)


REPO_ROOT = Path(__file__).resolve().parents[4]
SCRIPT_PATH = REPO_ROOT / 'scripts/ops/security_verification/validate_xaman_self_hosted_runtime_trace.py'


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode('ascii')).hexdigest()


def _trace() -> dict[str, object]:
    events = []
    outcome_by_action = {
        'onboarding': 'completed',
        'local_network_selection': 'local_network_selected',
        'review': 'reviewed',
        'signature_decision': 'approved',
        'submit_result': 'submitted',
        'cancellation': 'cancelled',
        'expiry': 'expired',
        'replay': 'blocked',
        'reconnect': 'reconnected',
        'network_change': 'local_network_retained',
    }
    for ordinal, action in enumerate(REQUIRED_ACTIONS, start=1):
        events.append(
            {
                'ordinal': ordinal,
                'action': action,
                'outcome': outcome_by_action[action],
                'source_kind': 'reviewed_ui',
                'source_sha256': _digest(format(ordinal, 'x')),
                'redaction_sha256': _digest(format(ordinal + 10, 'x')),
                'raw_material_recorded': False,
            }
        )
    payload: dict[str, object] = {
        'schema_version': 'xaman-self-hosted-runtime-trace-review/v1',
        'task_id': 'PORTAL-CXTP-158',
        'trace_id': 'self-hosted-local-lifecycle-001',
        'captured_at_utc': '2026-07-18T20:00:00Z',
        'reviewed_at_utc': '2026-07-18T20:05:00Z',
        'scope': {
            'public_source_verifier_only': True,
            'vendor_release_equivalent': False,
            'production_security_result': False,
            'source_commit': '942f43876265a7af44f233288ad2b1d00841d5fa',
            'network_id': 777777,
            'fresh_debug_emulator': True,
            'external_egress_observed': False,
            'vendor_fallback_observed': False,
        },
        'dependency_cids': {
            'endpoint_rebound_candidate': 'sha256:' + _digest('a'),
            'bridge_isolation_report': 'sha256:' + _digest('b'),
            'daemon_health': 'sha256:' + _digest('c'),
            'security_model': 'sha256:' + _digest('d'),
        },
        'review_gate': {
            'endpoint_rebind_review': 'sha256:' + _digest('e'),
            'status': 'passed',
            'expires_at_utc': '2027-07-18T20:05:00Z',
            'reviewer_id_sha256': _digest('f'),
        },
        'lifecycle_events': events,
        'redaction': {
            'raw_sensitive_material_retained': False,
            'redaction_review_sha256': _digest('9'),
        },
    }
    payload['artifact_cid'] = calculate_artifact_cid(payload)
    return payload


def _load_script():
    spec = importlib.util.spec_from_file_location('validate_xaman_self_hosted_runtime_trace', SCRIPT_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_valid_trace_builds_verifier_only_report() -> None:
    trace = _trace()
    validate_runtime_trace(trace, now=datetime(2026, 7, 18, 21, 0, tzinfo=timezone.utc))
    report = build_runtime_conformance_report(trace)

    assert report['overall_status'] == 'reviewed_self_hosted_verifier_trace'
    assert report['production_release_blocked'] is True
    assert report['covered_actions'] == list(REQUIRED_ACTIONS)


@pytest.mark.parametrize(
    ('mutator', 'message'),
    [
        (lambda trace: trace['lifecycle_events'].pop(), 'every required action'),
        (lambda trace: trace['lifecycle_events'].__setitem__(7, {**trace['lifecycle_events'][7], 'outcome': 'submitted'}), 'unsupported outcome'),
        (lambda trace: trace['review_gate'].__setitem__('status', 'pending'), 'has not passed'),
        (lambda trace: trace['scope'].__setitem__('vendor_release_equivalent', True), 'required self-hosted boundary'),
        (lambda trace: trace.__setitem__('endpoint_url', 'ws://127.0.0.1'), 'unexpected'),
    ],
)
def test_invalid_trace_fails_closed(mutator, message: str) -> None:
    trace = _trace()
    mutator(trace)
    if 'artifact_cid' in trace:
        trace['artifact_cid'] = calculate_artifact_cid({key: value for key, value in trace.items() if key != 'artifact_cid'})
    with pytest.raises(SelfHostedRuntimeTraceError, match=message):
        validate_runtime_trace(trace, now=datetime(2026, 7, 18, 21, 0, tzinfo=timezone.utc))


def test_expired_review_and_sensitive_material_are_rejected() -> None:
    trace = _trace()
    trace['review_gate']['expires_at_utc'] = '2026-07-18T20:59:59Z'
    trace['artifact_cid'] = calculate_artifact_cid({key: value for key, value in trace.items() if key != 'artifact_cid'})
    with pytest.raises(SelfHostedRuntimeTraceError, match='expired'):
        validate_runtime_trace(trace, now=datetime(2026, 7, 18, 21, 0, tzinfo=timezone.utc))

    trace = _trace()
    trace['lifecycle_events'][0]['source_sha256'] = 'rHb9CJAWyB4rj91VRWn96DkukG4bwdtyTh'
    trace['artifact_cid'] = calculate_artifact_cid({key: value for key, value in trace.items() if key != 'artifact_cid'})
    with pytest.raises(SelfHostedRuntimeTraceError, match='SHA-256 digest'):
        validate_runtime_trace(trace, now=datetime(2026, 7, 18, 21, 0, tzinfo=timezone.utc))


def test_script_writes_only_non_evidence_template(tmp_path: Path) -> None:
    module = _load_script()
    template = tmp_path / 'runtime-trace-template.json'

    assert module.main(['--repo-root', str(REPO_ROOT), '--write-template', '--template-out', str(template)]) == 0
    payload = json.loads(template.read_text(encoding='utf-8'))
    assert payload['template_status'] == 'NOT_RUNTIME_EVIDENCE'
    assert payload['required_actions'] == list(REQUIRED_ACTIONS)
