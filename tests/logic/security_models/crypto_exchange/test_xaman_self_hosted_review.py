"""Tests for the self-hosted Xaman independent-review packet and validator."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib

import pytest

from ipfs_datasets_py.logic.security_models.crypto_exchange.ir.cid import calculate_artifact_cid
from ipfs_datasets_py.logic.security_models.crypto_exchange.reports.xaman_self_hosted_review import (
    IndependentReviewError,
    REQUIRED_CHECKS,
    build_review_packet,
    build_review_template,
    validate_review_decision,
)


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode('ascii')).hexdigest()


def _with_cid(payload: dict) -> dict:
    payload['artifact_cid'] = calculate_artifact_cid(payload)
    return payload


def _packet() -> dict:
    candidate = _with_cid(
        {
            'scope': {'public_source_commit': '942f43876265a7af44f233288ad2b1d00841d5fa', 'verifier_only': True, 'vendor_release_equivalent': False},
            'candidate_controls': {'network_id': 777777},
            'changed_files': [{}, {}, {}, {}],
        }
    )
    health = _with_cid({'overall_status': 'daemon_healthy_standalone_full', 'self_hosted_network_id': 777777})
    isolation = _with_cid(
        {
            'overall_status': 'bridge_isolated_loopback_only_no_public_ingress_or_egress',
            'egress_probe': {'public_egress_denied': True},
            'port_publication': {'reviewed_ledger_bridge_published_loopback_only': True},
        }
    )
    return build_review_packet(candidate=candidate, health=health, isolation=isolation)


def _review(packet: dict) -> dict:
    review = {
        'schema_version': 'xaman-self-hosted-endpoint-rebind-review/v1',
        'task_id': 'PORTAL-CXTP-156',
        'review_packet_cid': packet['artifact_cid'],
        'reviewed_at_utc': '2026-07-18T21:00:00Z',
        'expires_at_utc': '2027-07-18T21:00:00Z',
        'reviewer': {'reviewer_id_sha256': _digest('independent-reviewer'), 'independent_of_candidate_author': True, 'conflict_of_interest_declared': False},
        'scope': {'public_source_verifier_only': True, 'vendor_release_equivalent': False, 'production_security_result': False},
        'checklist': [
            {'check_id': check_id, 'status': 'pass', 'evidence_sha256': _digest(check_id)}
            for check_id in REQUIRED_CHECKS
        ],
        'decision': 'pass',
        'reviewer_note_sha256': _digest('review-note'),
    }
    return _with_cid(review)


def test_packet_and_template_are_explicitly_pending_review() -> None:
    packet = _packet()
    template = build_review_template(packet)

    assert packet['packet_status'] == 'PENDING_INDEPENDENT_REVIEW'
    assert template['template_status'] == 'PENDING_INDEPENDENT_REVIEW'
    assert template['review_packet_cid'] == packet['artifact_cid']


def test_valid_independent_review_only_allows_verifier_runtime_capture() -> None:
    packet = _packet()
    report = validate_review_decision(_review(packet), packet=packet, now=datetime(2026, 7, 18, 22, tzinfo=timezone.utc))

    assert report['security_decision'] == 'ALLOW_VERIFIER_ONLY_RUNTIME_CAPTURE'
    assert report['production_release_blocked'] is True
    assert report['assurance_boundary']['vendor_backend_assumptions_cleared'] is False


@pytest.mark.parametrize(
    ('mutator', 'message'),
    [
        (lambda review: review['reviewer'].__setitem__('independent_of_candidate_author', False), 'independence'),
        (lambda review: review.__setitem__('review_packet_cid', 'sha256:' + _digest('wrong')), 'not bound'),
        (lambda review: review['checklist'][0].__setitem__('status', 'fail'), 'requires every check'),
        (lambda review: review['scope'].__setitem__('production_security_result', True), 'exceed verifier-only'),
    ],
)
def test_invalid_review_fails_closed(mutator, message: str) -> None:
    packet = _packet()
    review = _review(packet)
    mutator(review)
    review['artifact_cid'] = calculate_artifact_cid({key: value for key, value in review.items() if key != 'artifact_cid'})
    with pytest.raises(IndependentReviewError, match=message):
        validate_review_decision(review, packet=packet, now=datetime(2026, 7, 18, 22, tzinfo=timezone.utc))
