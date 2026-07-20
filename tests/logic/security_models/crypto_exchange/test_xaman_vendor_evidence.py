"""Tests for PORTAL-CXTP-153 vendor-evidence evidence schema and unblock behavior."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import hashlib

import pytest

from ipfs_datasets_py.logic.security_models.crypto_exchange.reports import xaman_gap_remediation_workflow
from ipfs_datasets_py.logic.security_models.crypto_exchange.reports.xaman_vendor_evidence import (
    build_vendor_evidence_placeholder_manifest,
    validate_vendor_evidence_manifest,
    validate_vendor_evidence_review,
    load_json,
    DEFAULT_REQUIRED_CLAIMS,
    REVIEW_SCHEMA_VERSION,
)


REPO_ROOT = Path(__file__).resolve().parents[4]
TEMPLATE_PATH = (
    REPO_ROOT
    / 'security_ir_artifacts'
    / 'corpora'
    / 'xaman-app'
    / 'vendor-evidence-intake-template.json'
)


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def _accepted_manifest() -> dict[str, object]:
    template = load_json(TEMPLATE_PATH)
    manifest = build_vendor_evidence_placeholder_manifest(
        template=template,
        generated_at_utc='2026-07-19T00:00:00Z',
        expires_at_utc='2026-08-10T00:00:00Z',
    )
    for category in manifest['category_evidence']:
        category['evidence_received'] = True
        category['redaction_review_passed'] = True
    return validate_vendor_evidence_manifest(manifest)


def _accepted_review(*, manifest: dict[str, object], reviewed_at_utc: str, expires_at_utc: str) -> dict[str, object]:
    return {
        'schema_version': REVIEW_SCHEMA_VERSION,
        'task_id': 'PORTAL-CXTP-153',
        'manifest_cid': manifest['artifact_cid'],
        'reviewed_at_utc': reviewed_at_utc,
        'expires_at_utc': expires_at_utc,
        'decision': 'accepted',
        'reviewer': {
            'reviewer_id_sha256': _sha256('vendor-reviewer'),
            'independent_of_vendor_author': True,
            'conflict_of_interest_declared': False,
        },
        'scope': {
            'vendor_release_equivalent': False,
            'production_security_result': False,
            'public_source_verifier_only': False,
        },
        'category_reviews': [
            {'claim_id': claim_id, 'category_ids': categories}
            for claim_id, categories in [
                (
                    'xaman-claim:backend-payload-service-is-trusted-not-proved',
                    ['backend_payload_semantics', 'test_device_trace_review'],
                ),
                (
                    'xaman-claim:runtime-equivalence-is-blocked-without-device-traces',
                    ['native_vault_biometric_policy', 'test_device_trace_review'],
                ),
            ]
        ],
    }


def test_placeholder_manifest_is_deterministic_and_nonaccepted() -> None:
    manifest = _accepted_manifest()

    assert manifest['schema_version'] == 'xaman-vendor-evidence-manifest/v1'
    assert manifest['task_id'] == 'PORTAL-CXTP-153'
    assert manifest['manifest_status'] == 'WAITING_FOR_REVIEW'
    assert set(DEFAULT_REQUIRED_CLAIMS).issubset({entry['claim_id'] for entry in manifest['claim_bindings']})
    assert manifest['category_evidence'][0]['evidence_received'] is True


@pytest.mark.parametrize(
    ('expires_at_utc', 'now_utc', 'accepted'),
    [
        ('2027-07-19T00:00:00Z', '2026-07-19T01:00:00Z', True),
        ('2026-07-18T23:59:59Z', '2026-07-19T01:00:00Z', False),
    ],
)
def test_review_validation_enforces_scope_and_expiry(expires_at_utc: str, now_utc: str, accepted: bool) -> None:
    manifest = _accepted_manifest()
    review = _accepted_review(
        manifest=manifest,
        reviewed_at_utc='2026-07-19T00:00:00Z',
        expires_at_utc=expires_at_utc,
    )
    report = validate_vendor_evidence_review(
        review,
        manifest=manifest,
        now=datetime.fromisoformat(now_utc.replace('Z', '+00:00')),
    )
    assert report['review_accepted_for_gap_clearance'] == accepted


def test_vendor_review_scope_requirements_fail_closed() -> None:
    manifest = _accepted_manifest()
    review = _accepted_review(
        manifest=manifest,
        reviewed_at_utc='2026-07-19T00:00:00Z',
        expires_at_utc='2027-07-19T00:00:00Z',
    )
    review['scope']['production_security_result'] = True
    with pytest.raises(Exception):
        validate_vendor_evidence_review(review, manifest=manifest, now=datetime(2026, 7, 19, 1, tzinfo=timezone.utc))

@pytest.mark.parametrize(
    ('clears', 'state'),
    [
        (lambda claim_id: True, 'ready'),
        (lambda claim_id: False, 'blocked'),
    ],
)
def test_gap_workflow_external_blocker_tracks_vendor_evidence(monkeypatch, clears, state) -> None:
    monkeypatch.setattr(xaman_gap_remediation_workflow, '_vendor_evidence_clears_claim', lambda claim_id, now=None: clears(claim_id))

    matrix = {
        'schema_version': 'xaman-gap-remediation-matrix/v1',
        'task_id': 'PORTAL-CXTP-170',
        'matrix': [
            {
                'entry_id': 'xaman-disproof:backend-double-use',
                'classification': 'EXTERNAL_EVIDENCE_REQUIRED',
                'claim_id': 'xaman-claim:backend-payload-service-is-trusted-not-proved',
                'origin': 'disproof_vector',
                'priority': 2,
                'next_task_ids': ['PORTAL-CXTP-152', 'PORTAL-CXTP-153'],
                'next_actions': [],
            }
        ],
        'matrix_task_count': 1,
        'required_task_ids': ['PORTAL-CXTP-152', 'PORTAL-CXTP-153'],
    }
    report = xaman_gap_remediation_workflow.build_gap_remediation_execution_manifest(
        gap_remediation_matrix=matrix,
        counterexample_report={'results': [{'vector_id': 'xaman-disproof:backend-double-use'}]},
        fuzz_report={'attack_mutations': []},
        fuzz_counterexample_manifest={'counterexamples': []},
        native_vault_state_fuzz={'source_supported_conditions': []},
        now=datetime(2026, 7, 19, 1, tzinfo=timezone.utc),
    )
    assert report['entries'][0]['execution_state'] == state
    if state == 'ready':
        assert 'blocked_by' not in report['entries'][0] or report['entries'][0]['blocked_by'] == []
    else:
        assert report['entries'][0]['blocked_by'] == ['EXTERNAL_EVIDENCE_REQUIRED']
        assert report['entries'][0]['next_actions']
        assert any('backend payload-service evidence' in action for action in report['entries'][0]['next_actions'])
