"""Tests for PORTAL-CXTP-152 Xaman vendor-evidence intake request."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[4]
TEMPLATE_PATH = (
    REPO_ROOT
    / 'security_ir_artifacts'
    / 'corpora'
    / 'xaman-app'
    / 'vendor-evidence-intake-template.json'
)
DOC_PATH = REPO_ROOT / 'docs' / 'security_verification' / 'xaman_vendor_evidence_request.md'

TASK_ID = 'PORTAL-CXTP-152'
SCHEMA_VERSION = 'xaman-vendor-evidence-intake-template/v1'
CREATED_AT = '2026-07-11T00:00:00Z'
EXPIRES_AT = '2026-08-10T00:00:00Z'

REQUIRED_CATEGORIES = {
    'release_provenance',
    'native_vault_biometric_policy',
    'backend_payload_semantics',
    'signed_build_attestation',
    'test_device_trace_review',
    'xrpl_rpc_trust_assumptions',
    'responsible_disclosure_routing',
}

REQUIRED_ACCEPTANCE_PHRASES = {
    'release provenance',
    'native vault/biometric policy',
    'backend payload single-use/conflict/expiry semantics',
    'signed-build attestation',
    'test-device trace review',
    'XRPL/RPC trust assumptions',
    'responsible-disclosure routing',
    'accountable owners',
    'expiry',
    'review criteria',
}

REQUIRED_PROHIBITED_MATERIAL = {
    'seed_material',
    'private_keys',
    'passcodes',
    'biometric_templates',
    'production_credentials',
    'raw_payload_bodies',
    'raw_transaction_blobs',
    'unredacted_user_data',
    'private_backend_endpoints',
    'signing_keystore_material',
}


def _load_template() -> dict[str, Any]:
    return json.loads(TEMPLATE_PATH.read_text(encoding='utf-8'))


def _parse_utc(value: str) -> datetime:
    return datetime.fromisoformat(value.replace('Z', '+00:00')).astimezone(timezone.utc)


def test_template_declares_scope_dependencies_authorization_and_non_claims() -> None:
    template = _load_template()

    assert template['schema_version'] == SCHEMA_VERSION
    assert template['task_id'] == TASK_ID
    assert template['corpus'] == 'xaman-app'
    assert template['source_dependencies'] == ['PORTAL-CXTP-143', 'PORTAL-CXTP-145']
    assert template['created_at_utc'] == CREATED_AT

    authorization = template['authorization']
    assert authorization['status'] == 'prepared_not_sent_authorization_required'
    assert authorization['prepared_not_sent'] is True
    assert authorization['authorized_channel_required'] is True
    assert set(authorization['required_approvals_before_transmission']) == {
        'project_security_lead',
        'legal_or_vendor_relations',
        'verified_vendor_approved_channel',
    }
    assert REQUIRED_PROHIBITED_MATERIAL <= set(authorization['prohibited_material'])

    non_claims = template['non_claims']
    assert non_claims == {
        'backend_service_validated': False,
        'native_vault_or_biometric_validated': False,
        'production_release_approved': False,
        'vendor_evidence_access_claimed': False,
        'vendor_evidence_truth_claimed': False,
        'vendor_release_reproduced': False,
    }


def test_expiry_is_absolute_and_requires_reapproval_after_30_days() -> None:
    template = _load_template()
    expiry = template['expiry']

    assert expiry['expires_at_utc'] == EXPIRES_AT
    assert expiry['freshness_days'] == 30
    assert expiry['on_expiry'] == 'do_not_send_without_reapproval_and_date_refresh'
    assert (_parse_utc(expiry['expires_at_utc']) - _parse_utc(template['created_at_utc'])).days == 30


def test_every_required_evidence_category_has_redacted_requests_and_review_criteria() -> None:
    template = _load_template()
    categories = {entry['category_id']: entry for entry in template['evidence_request_categories']}

    assert set(categories) == REQUIRED_CATEGORIES
    all_acceptance_phrases = {
        phrase
        for category in categories.values()
        for phrase in category['acceptance_mapping']
    }
    assert REQUIRED_ACCEPTANCE_PHRASES <= all_acceptance_phrases

    for category_id, category in categories.items():
        assert category['description'], category_id
        assert 'not' in category['claim_boundary'].lower(), category_id
        assert 'until' in category['claim_boundary'].lower(), category_id
        assert len(category['requested_items']) >= 6, category_id
        assert len(category['redaction_required']) >= 4, category_id
        assert len(category['minimum_review_criteria']) >= 5, category_id

    backend = categories['backend_payload_semantics']
    backend_text = json.dumps(backend).lower()
    for phrase in ['single-use', 'conflict', 'expiry', 'cancellation', 'replay', 'concurrent']:
        assert phrase in backend_text

    native = categories['native_vault_biometric_policy']
    native_text = json.dumps(native).lower()
    for phrase in ['keystore', 'keychain', 'hardware-backed', 'biometric', 'enrollment-change']:
        assert phrase in native_text

    xrpl = categories['xrpl_rpc_trust_assumptions']
    xrpl_text = json.dumps(xrpl).lower()
    for phrase in ['endpoint', 'network identity', 'ledger finality', 'fallback', 'compromise']:
        assert phrase in xrpl_text


def test_accountable_owner_signoff_matches_all_categories() -> None:
    template = _load_template()
    owners = {entry['category_id']: entry for entry in template['accountable_owners']}

    assert set(owners) == REQUIRED_CATEGORIES
    for category_id, owner in owners.items():
        assert owner['signoff_required'] is True
        assert owner['required_vendor_owner_role'].startswith('vendor '), category_id
        assert owner['internal_reviewer_role'].startswith('internal '), category_id
        assert 'owner' in owner['required_vendor_owner_role'], category_id
        assert 'reviewer' in owner['internal_reviewer_role'] or 'approver' in owner['internal_reviewer_role']


def test_review_and_disclosure_rules_fail_closed() -> None:
    template = _load_template()
    review = template['review_criteria']
    routing = template['disclosure_routing']

    assert review['allowed_review_outcomes'] == ['accepted', 'needs_clarification', 'rejected']
    assert set(review['required_before_acceptance']) == {
        'verified_vendor_authorized_channel',
        'category_owner_signoff',
        'redaction_review_passed',
        'scope_and_date_recorded',
        'claim_binding_recorded',
        'retention_allowed_or_alternative_handling_recorded',
    }
    assert {
        'missing_authorization',
        'expired_request',
        'unverified_route',
        'missing_accountable_owner',
        'unredacted_secret_or_personal_data',
        'claim_not_bound_to_evidence',
        'public_testnet_build_used_as_vendor_release_equivalence',
        'responsible_disclosure_route_not_approved_for_sensitive_detail',
    } <= set(review['fail_closed_conditions'])
    assert review['promotion_rule'].startswith('Only PORTAL-CXTP-153 may promote')

    assert routing['route_verification_required'] is True
    assert routing['counterexample_detail_allowed_before_route_approval'] is False
    assert routing['vulnerability_detail_requires_written_authorization'] is True
    assert 'vendor-published security contact verified at send time' in routing['routing_options']


def test_document_records_request_boundary_outputs_and_all_acceptance_topics() -> None:
    doc = DOC_PATH.read_text(encoding='utf-8')

    assert TASK_ID in doc
    assert TEMPLATE_PATH.relative_to(REPO_ROOT).as_posix() in doc
    assert 'prepared_not_sent_authorization_required' in doc
    assert CREATED_AT in doc
    assert EXPIRES_AT in doc
    assert 'does not claim access to vendor-only systems' in doc
    assert 'does not assert that vendor-only evidence exists' in doc
    assert 'does not treat any requested statement as true' in doc
    assert 'does not prove Xaman secure' in doc
    assert 'does not reproduce a vendor release' in doc
    assert 'does not approve production release use' in doc

    for phrase in REQUIRED_ACCEPTANCE_PHRASES:
        assert phrase in doc
    for category_id in REQUIRED_CATEGORIES:
        assert category_id in doc

    assert 'TODO' not in doc
    assert 'TBD' not in doc
