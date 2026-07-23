"""Independent-review packet and fail-closed decision validator for Xaman."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Mapping

from ..ir.cid import calculate_artifact_cid


TASK_PACKET = 'PORTAL-CXTP-160'
TASK_REVIEW = 'PORTAL-CXTP-161'
PACKET_SCHEMA_VERSION = 'xaman-self-hosted-independent-review-packet/v1'
TEMPLATE_SCHEMA_VERSION = 'xaman-self-hosted-independent-review-template/v1'
REVIEW_SCHEMA_VERSION = 'xaman-self-hosted-endpoint-rebind-review/v1'
VERIFICATION_SCHEMA_VERSION = 'xaman-self-hosted-independent-review-verification/v1'
PINNED_XAMAN_COMMIT = '942f43876265a7af44f233288ad2b1d00841d5fa'
NETWORK_ID = 777777

REQUIRED_CHECKS = (
    'candidate_source_diff',
    'bridge_isolation',
    'external_egress_denied',
    'vendor_fallback_absent',
    'non_local_network_rejected',
    'emulator_loopback_bridge',
)
PACKET_REQUIRED_KEYS = frozenset(
    {
        'schema_version',
        'task_id',
        'packet_status',
        'candidate',
        'bridge_evidence',
        'review_requirements',
        'assurance_boundary',
        'artifact_cid',
    }
)
REVIEW_REQUIRED_KEYS = frozenset(
    {
        'schema_version',
        'task_id',
        'review_packet_cid',
        'reviewed_at_utc',
        'expires_at_utc',
        'reviewer',
        'scope',
        'checklist',
        'decision',
        'reviewer_note_sha256',
        'artifact_cid',
    }
)
SHA256_RE = re.compile(r'^[a-f0-9]{64}$')
CID_RE = re.compile(r'^(?:sha256:[a-f0-9]{64}|baf[a-z2-7]{20,})$')
TIMESTAMP_RE = re.compile(r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$')
SENSITIVE_VALUE_PATTERNS = (
    re.compile(r'\b(?:wss?|https?)://[^\s"\'<>]+', re.IGNORECASE),
    re.compile(r'\br[1-9A-HJ-NP-Za-km-z]{24,35}\b'),
    re.compile(r'\b[XT][1-9A-HJ-NP-Za-km-z]{40,60}\b'),
    re.compile(r'\bs[1-9A-HJ-NP-Za-km-z]{25,35}\b'),
    re.compile(r'\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b'),
    re.compile(r'\b[A-Fa-f0-9]{128,}\b'),
)
SENSITIVE_KEY_TOKENS = frozenset(
    {
        'account', 'address', 'blob', 'body', 'credential', 'endpoint', 'mnemonic', 'password',
        'payload', 'private', 'request', 'response', 'seed', 'secret', 'signature', 'token',
        'transaction', 'wallet',
    }
)


class IndependentReviewError(ValueError):
    """Raised when review evidence is malformed, stale, or unsafe."""


def _cid_without(payload: Mapping[str, Any]) -> str:
    return calculate_artifact_cid({key: value for key, value in payload.items() if key != 'artifact_cid'})


def _load_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError) as exc:
        raise IndependentReviewError(f'cannot load JSON object: {path}') from exc
    if not isinstance(value, dict):
        raise IndependentReviewError(f'expected JSON object: {path}')
    return value


def _require_exact_keys(value: Any, expected: frozenset[str], *, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise IndependentReviewError(f'{field} must be an object')
    missing = expected - set(value)
    extra = set(value) - expected
    if missing or extra:
        details = []
        if missing:
            details.append(f'missing {sorted(missing)}')
        if extra:
            details.append(f'unexpected {sorted(extra)}')
        raise IndependentReviewError(f'{field} has ' + '; '.join(details))
    return value


def _require_digest(value: Any, *, field: str, cid: bool = False) -> str:
    if not isinstance(value, str) or not (CID_RE if cid else SHA256_RE).fullmatch(value):
        raise IndependentReviewError(f'{field} must be a valid lowercase ' + ('artifact CID' if cid else 'SHA-256 digest'))
    if not cid and len(set(value)) == 1:
        raise IndependentReviewError(f'{field} must not be a repeated-character placeholder')
    return value


def _utc(value: Any, *, field: str) -> datetime:
    if not isinstance(value, str) or not TIMESTAMP_RE.fullmatch(value):
        raise IndependentReviewError(f'{field} must be a UTC second-resolution timestamp')
    try:
        return datetime.strptime(value, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise IndependentReviewError(f'{field} is invalid') from exc


def _assert_no_sensitive_material(value: Any, *, field: str = 'review') -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            normalized = re.sub(r'[^a-z0-9]+', '', str(key).lower())
            if normalized in SENSITIVE_KEY_TOKENS:
                raise IndependentReviewError(f'{field} contains sensitive key {key!r}')
            _assert_no_sensitive_material(item, field=f'{field}.{key}')
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _assert_no_sensitive_material(item, field=f'{field}[{index}]')
    elif isinstance(value, str) and any(pattern.search(value) for pattern in SENSITIVE_VALUE_PATTERNS):
        raise IndependentReviewError(f'{field} contains raw sensitive material')


def build_review_packet(*, candidate: Mapping[str, Any], health: Mapping[str, Any], isolation: Mapping[str, Any]) -> dict[str, Any]:
    """Bind the available local evidence into a packet for a separate reviewer."""

    if candidate.get('artifact_cid') is None or health.get('artifact_cid') is None or isolation.get('artifact_cid') is None:
        raise IndependentReviewError('every input evidence artifact must be content addressed')
    if candidate.get('scope', {}).get('public_source_commit') != PINNED_XAMAN_COMMIT:
        raise IndependentReviewError('candidate is not bound to the pinned public Xaman commit')
    if candidate.get('scope', {}).get('verifier_only') is not True or candidate.get('scope', {}).get('vendor_release_equivalent') is not False:
        raise IndependentReviewError('candidate does not preserve verifier-only scope')
    if candidate.get('candidate_controls', {}).get('network_id') != NETWORK_ID:
        raise IndependentReviewError('candidate uses an unexpected local network ID')
    if health.get('overall_status') != 'daemon_healthy_standalone_full' or health.get('self_hosted_network_id') != NETWORK_ID:
        raise IndependentReviewError('daemon health evidence is not a healthy local standalone result')
    if isolation.get('overall_status') != 'bridge_isolated_loopback_only_no_public_ingress_or_egress':
        raise IndependentReviewError('bridge isolation evidence is not accepted')
    if isolation.get('egress_probe', {}).get('public_egress_denied') is not True:
        raise IndependentReviewError('bridge evidence does not deny public egress')
    if isolation.get('port_publication', {}).get('reviewed_ledger_bridge_published_loopback_only') is not True:
        raise IndependentReviewError('bridge evidence does not bind a loopback-only listener')

    packet: dict[str, Any] = {
        'schema_version': PACKET_SCHEMA_VERSION,
        'task_id': TASK_PACKET,
        'packet_status': 'PENDING_INDEPENDENT_REVIEW',
        'candidate': {
            'candidate_manifest_cid': candidate['artifact_cid'],
            'public_source_commit': PINNED_XAMAN_COMMIT,
            'self_hosted_network_id': NETWORK_ID,
            'changed_file_count': len(candidate.get('changed_files', [])),
        },
        'bridge_evidence': {
            'daemon_health_cid': health['artifact_cid'],
            'bridge_isolation_cid': isolation['artifact_cid'],
            'standalone_daemon_healthy': True,
            'loopback_only_listener': True,
            'public_egress_denied': True,
        },
        'review_requirements': {
            'reviewer_must_be_independent': True,
            'unexpired_decision_required': True,
            'required_check_ids': list(REQUIRED_CHECKS),
            'pass_decision_requires_all_checks_pass': True,
        },
        'assurance_boundary': {
            'public_source_verifier_only': True,
            'vendor_release_equivalent': False,
            'production_security_result': False,
            'runtime_trace_recorded': False,
        },
    }
    _assert_no_sensitive_material(packet, field='packet')
    packet['artifact_cid'] = _cid_without(packet)
    return packet


def build_review_template(packet: Mapping[str, Any]) -> dict[str, Any]:
    """Return a non-evidence reviewer template bound to an existing packet."""

    _require_exact_keys(packet, PACKET_REQUIRED_KEYS, field='packet')
    return {
        'schema_version': TEMPLATE_SCHEMA_VERSION,
        'task_id': TASK_REVIEW,
        'template_status': 'PENDING_INDEPENDENT_REVIEW',
        'review_packet_cid': packet['artifact_cid'],
        'required_check_ids': list(REQUIRED_CHECKS),
        'required_scope': {
            'public_source_verifier_only': True,
            'vendor_release_equivalent': False,
            'production_security_result': False,
        },
        'required_reviewer_attestations': {
            'independent_of_candidate_author': True,
            'conflict_of_interest_declared': False,
            'reviewer_identity_digest_only': True,
        },
        'acceptance_boundary': 'This template is not a review decision and cannot authorize runtime capture or a security claim.',
    }


def validate_review_decision(
    review: Mapping[str, Any],
    *,
    packet: Mapping[str, Any],
    now: datetime | None = None,
) -> dict[str, Any]:
    """Validate a reviewed decision and return a redacted verification report."""

    _require_exact_keys(packet, PACKET_REQUIRED_KEYS, field='packet')
    _require_exact_keys(review, REVIEW_REQUIRED_KEYS, field='review')
    if review.get('schema_version') != REVIEW_SCHEMA_VERSION or review.get('task_id') != 'PORTAL-CXTP-156':
        raise IndependentReviewError('review schema or task identifier is invalid')
    if review.get('review_packet_cid') != packet.get('artifact_cid'):
        raise IndependentReviewError('review is not bound to the supplied review packet')
    _utc(review.get('reviewed_at_utc'), field='reviewed_at_utc')
    expires_at = _utc(review.get('expires_at_utc'), field='expires_at_utc')
    reference_time = now or datetime.now(timezone.utc)

    reviewer = _require_exact_keys(
        review.get('reviewer'),
        frozenset({'reviewer_id_sha256', 'independent_of_candidate_author', 'conflict_of_interest_declared'}),
        field='reviewer',
    )
    _require_digest(reviewer.get('reviewer_id_sha256'), field='reviewer.reviewer_id_sha256')
    if reviewer.get('independent_of_candidate_author') is not True or reviewer.get('conflict_of_interest_declared') is not False:
        raise IndependentReviewError('reviewer independence attestation is invalid')

    scope = _require_exact_keys(
        review.get('scope'),
        frozenset({'public_source_verifier_only', 'vendor_release_equivalent', 'production_security_result'}),
        field='scope',
    )
    if dict(scope) != {
        'public_source_verifier_only': True,
        'vendor_release_equivalent': False,
        'production_security_result': False,
    }:
        raise IndependentReviewError('review scope attempts to exceed verifier-only evidence')

    checklist = review.get('checklist')
    if not isinstance(checklist, list) or len(checklist) != len(REQUIRED_CHECKS):
        raise IndependentReviewError('review checklist must contain every required check exactly once')
    check_ids: list[str] = []
    for index, item in enumerate(checklist):
        if not isinstance(item, Mapping) or set(item) != {'check_id', 'status', 'evidence_sha256'}:
            raise IndependentReviewError(f'checklist[{index}] has an invalid shape')
        check_id = item.get('check_id')
        if check_id not in REQUIRED_CHECKS or item.get('status') not in {'pass', 'fail'}:
            raise IndependentReviewError(f'checklist[{index}] is invalid')
        _require_digest(item.get('evidence_sha256'), field=f'checklist[{index}].evidence_sha256')
        check_ids.append(str(check_id))
    if tuple(check_ids) != REQUIRED_CHECKS:
        raise IndependentReviewError('review checklist order or coverage is invalid')
    if review.get('decision') not in {'pass', 'fail'}:
        raise IndependentReviewError('review decision must be pass or fail')
    if review.get('decision') == 'pass' and any(item['status'] != 'pass' for item in checklist):
        raise IndependentReviewError('a passing decision requires every check to pass')
    _require_digest(review.get('reviewer_note_sha256'), field='reviewer_note_sha256')
    _assert_no_sensitive_material(review)
    if review.get('artifact_cid') != _cid_without(review):
        raise IndependentReviewError('review artifact CID does not match canonical payload')

    accepted = review['decision'] == 'pass' and expires_at > reference_time
    report: dict[str, Any] = {
        'schema_version': VERIFICATION_SCHEMA_VERSION,
        'task_id': TASK_REVIEW,
        'review_artifact_cid': review['artifact_cid'],
        'review_packet_cid': packet['artifact_cid'],
        'reviewer_id_sha256': reviewer['reviewer_id_sha256'],
        'reviewed_at_utc': review['reviewed_at_utc'],
        'expires_at_utc': review['expires_at_utc'],
        'decision': review['decision'],
        'all_required_checks_passed': all(item['status'] == 'pass' for item in checklist),
        'review_accepted_for_verifier_runtime_capture': accepted,
        'overall_status': 'independent_review_passed' if accepted else ('independent_review_expired' if expires_at <= reference_time else 'independent_review_not_passed'),
        'security_decision': 'ALLOW_VERIFIER_ONLY_RUNTIME_CAPTURE' if accepted else 'BLOCK_VERIFIER_RUNTIME_CAPTURE_PENDING_REVIEW',
        'production_release_blocked': True,
        'assurance_boundary': {
            'vendor_release_equivalent': False,
            'production_security_result': False,
            'vendor_backend_assumptions_cleared': False,
        },
    }
    _assert_no_sensitive_material(report, field='verification_report')
    report['artifact_cid'] = _cid_without(report)
    return report


def load_json(path: Path) -> dict[str, Any]:
    return _load_object(path)
