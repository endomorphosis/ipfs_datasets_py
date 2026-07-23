"""Vendor-evidence manifest/review validation for Xaman security blockers.

This module is used by the gap-remediation workflow to decide whether EXTERNAL
evidence blockers can be cleared after an authorized vendor package is submitted,
reviewed, and mapped to blocker claims.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from typing import Any

from ..ir.cid import calculate_artifact_cid


TASK_ID = 'PORTAL-CXTP-153'
TASK_REVIEW_ID = 'PORTAL-CXTP-153'
MANIFEST_SCHEMA_VERSION = 'xaman-vendor-evidence-manifest/v1'
REVIEW_SCHEMA_VERSION = 'xaman-vendor-evidence-review/v1'
REVIEW_VERIFICATION_SCHEMA_VERSION = 'xaman-vendor-evidence-review-verification/v1'
REVIEW_TEMPLATE_SCHEMA_VERSION = 'xaman-vendor-evidence-review-template/v1'

MANIFEST_PATH = 'security_ir_artifacts/corpora/xaman-app/vendor-evidence-manifest.json'
REVIEW_PATH = 'security_ir_artifacts/corpora/xaman-app/vendor-evidence-review.json'
REVIEW_VERIFICATION_PATH = 'security_ir_artifacts/corpora/xaman-app/vendor-evidence-review-verification.json'
REVIEW_TEMPLATE_PATH = 'security_ir_artifacts/corpora/xaman-app/vendor-evidence-review-template.json'
INTAKE_TEMPLATE_PATH = 'security_ir_artifacts/corpora/xaman-app/vendor-evidence-intake-template.json'
DOCUMENT_PATH = 'docs/security_verification/xaman_vendor_evidence_review.md'

REQUIRED_CATEGORIES = (
    'release_provenance',
    'native_vault_biometric_policy',
    'backend_payload_semantics',
    'signed_build_attestation',
    'test_device_trace_review',
    'xrpl_rpc_trust_assumptions',
    'responsible_disclosure_routing',
)

DEFAULT_REQUIRED_CLAIMS = (
    'xaman-claim:backend-payload-service-is-trusted-not-proved',
    'xaman-claim:runtime-equivalence-is-blocked-without-device-traces',
)

MANIFEST_REQUIRED_KEYS = frozenset(
    {
        'schema_version',
        'task_id',
        'manifest_status',
        'corpus',
        'generated_at_utc',
        'expires_at_utc',
        'intake_template_path',
        'category_evidence',
        'claim_bindings',
    }
)
REVIEW_REQUIRED_KEYS = frozenset(
    {
        'schema_version',
        'task_id',
        'manifest_cid',
        'reviewed_at_utc',
        'expires_at_utc',
        'decision',
        'reviewer',
        'scope',
        'category_reviews',
    }
)
REVIEW_TEMPLATE_REQUIRED_KEYS = frozenset(
    {
        'schema_version',
        'task_id',
        'template_status',
        'manifest_cid',
        'required_scope',
        'required_review_criteria',
    }
)

SHA256_RE = re.compile(r'^[a-f0-9]{64}$')
TIMESTAMP_RE = re.compile(r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$')
CID_RE = re.compile(r'^(?:sha256:[a-f0-9]{64}|baf[a-z2-7]{20,})$')
SENSITIVE_VALUE_PATTERNS = (
    re.compile(r"\b(?:wss?|https?)://[^\s\"'<>]+", re.IGNORECASE),
    re.compile(r'\b[XT][1-9A-HJ-NP-Za-km-z]{40,60}\b'),
    re.compile(r'\br[1-9A-HJ-NP-Za-km-z]{24,35}\b'),
    re.compile(r'\b[A-Fa-f0-9]{128,}\b'),
)


class VendorEvidenceError(ValueError):
    """Raised when vendor evidence objects violate their review/evidence schema."""


def _cid_without(payload: Mapping[str, Any], *, ignore: str = 'artifact_cid') -> str:
    return calculate_artifact_cid(
        {key: value for key, value in payload.items() if key != ignore}
    )


def _load_object(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError) as exc:
        raise VendorEvidenceError(f'cannot load JSON object from {path}') from exc
    if not isinstance(payload, dict):
        raise VendorEvidenceError(f'expected JSON object from {path}')
    return payload


def load_json(path: Path) -> dict[str, Any]:
    return _load_object(path)


def _require_exact_keys(
    value: Any,
    expected: frozenset[str],
    *,
    field: str,
    allowed_extra: frozenset[str] | None = None,
) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise VendorEvidenceError(f'{field} must be an object')
    missing = expected - set(value)
    extra = set(value) - expected
    if allowed_extra:
        extra = extra - set(allowed_extra)
    if missing or extra:
        details: list[str] = []
        if missing:
            details.append(f'missing {sorted(missing)}')
        if extra:
            details.append(f'unexpected {sorted(extra)}')
        raise VendorEvidenceError(f'{field} has ' + '; '.join(details))
    return value


def _require_string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise VendorEvidenceError(f'{field} must be a non-empty string')
    return value


def _require_bool(value: Any, field: str) -> bool:
    if not isinstance(value, bool):
        raise VendorEvidenceError(f'{field} must be a boolean')
    return value


def _parse_timestamp(value: Any, *, field: str) -> datetime:
    if not isinstance(value, str) or not TIMESTAMP_RE.match(value):
        raise VendorEvidenceError(f'{field} must be UTC timestamp in YYYY-MM-DDTHH:MM:SSZ format')
    try:
        return datetime.strptime(value, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise VendorEvidenceError(f'{field} is invalid') from exc


def _assert_no_sensitive_material(value: Any, *, field: str) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            normalized = re.sub(r'[^a-z0-9]+', '', str(key).lower())
            if normalized in {'address', 'privatekey', 'seed', 'password', 'token', 'secret', 'payload', 'transaction'}:
                raise VendorEvidenceError(f'{field} contains sensitive key {key!r}')
            _assert_no_sensitive_material(item, field=f'{field}.{key}')
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _assert_no_sensitive_material(item, field=f'{field}[{index}]')
    elif isinstance(value, str) and any(pattern.search(value) for pattern in SENSITIVE_VALUE_PATTERNS):
        raise VendorEvidenceError(f'{field} contains raw sensitive material')


def _validate_manifest_category(category: Mapping[str, Any], *, field: str) -> dict[str, Any]:
    required = {'category_id', 'status', 'evidence_received', 'redaction_review_passed', 'owner_signoff'}
    optional = {'evidence_references'}
    payload_keys = set(category)
    missing = required - payload_keys
    extra = payload_keys - (required | optional)
    if missing or extra:
        messages: list[str] = []
        if missing:
            messages.append(f'missing {sorted(missing)}')
        if extra:
            messages.append(f'unexpected {sorted(extra)}')
        raise VendorEvidenceError(f'{field} has ' + '; '.join(messages))
    payload = dict(category)

    category_id = _require_string(payload['category_id'], field=f'{field}.category_id')
    if category_id not in REQUIRED_CATEGORIES:
        raise VendorEvidenceError(f'{field}.category_id is not a required evidence category: {category_id}')

    status = _require_string(payload['status'], field=f'{field}.status')
    if status not in {'pending_submission', 'received', 'reviewed', 'rejected'}:
        raise VendorEvidenceError(f'{field}.status is invalid: {status}')

    _require_bool(payload['evidence_received'], field=f'{field}.evidence_received')
    _require_bool(payload['redaction_review_passed'], field=f'{field}.redaction_review_passed')

    owner_signoff = payload['owner_signoff']
    if not isinstance(owner_signoff, Mapping):
        raise VendorEvidenceError(f'{field}.owner_signoff must be an object')
    owner_required = {'owner_role', 'owner_name', 'signed_at_utc', 'authorized_channel'}
    if set(owner_signoff) != owner_required:
        missing = owner_required - set(owner_signoff)
        extra = set(owner_signoff) - owner_required
        messages = []
        if missing:
            messages.append(f'missing {sorted(missing)}')
        if extra:
            messages.append(f'unexpected {sorted(extra)}')
        raise VendorEvidenceError(f'{field}.owner_signoff has ' + '; '.join(messages))

    if owner_signoff['authorized_channel'] not in {
        'verified_vendor_approved_channel',
        'vendor_documented_route',
        'pending_vendor_authorization',
    }:
        raise VendorEvidenceError(f'{field}.owner_signoff.authorized_channel is invalid')
    _parse_timestamp(owner_signoff['signed_at_utc'], field=f'{field}.owner_signoff.signed_at_utc')
    _require_string(owner_signoff['owner_role'], field=f'{field}.owner_signoff.owner_role')
    _require_string(owner_signoff['owner_name'], field=f'{field}.owner_signoff.owner_name')
    _assert_no_sensitive_material(owner_signoff['owner_role'], field=f'{field}.owner_signoff.owner_role')
    _assert_no_sensitive_material(owner_signoff['owner_name'], field=f'{field}.owner_signoff.owner_name')

    evidence_refs = payload.get('evidence_references', [])
    if not isinstance(evidence_refs, list):
        raise VendorEvidenceError(f'{field}.evidence_references must be an array')
    for index, item in enumerate(evidence_refs):
        if not isinstance(item, Mapping):
            raise VendorEvidenceError(f'{field}.evidence_references[{index}] must be an object')
        ev = item
        if not {'path', 'sha256', 'description'} <= set(ev):
            raise VendorEvidenceError(f'{field}.evidence_references[{index}] is missing required keys')
        if not isinstance(ev['path'], str):
            raise VendorEvidenceError(f'{field}.evidence_references[{index}].path must be string')
        sha256 = _require_string(ev['sha256'], field=f'{field}.evidence_references[{index}].sha256')
        if not (len(sha256) == 64 and SHA256_RE.match(sha256)):
            raise VendorEvidenceError(f'{field}.evidence_references[{index}].sha256 is not a plain hex digest')
        _require_string(ev['description'], field=f'{field}.evidence_references[{index}].description')

    return {
        'category_id': category_id,
        'status': status,
        'evidence_received': bool(payload['evidence_received']),
        'redaction_review_passed': bool(payload['redaction_review_passed']),
        'owner_signoff': dict(owner_signoff),
        'evidence_references': evidence_refs,
    }


def _validate_claim_bindings(bindings: Any, *, field: str) -> dict[str, list[str]]:
    if not isinstance(bindings, list):
        raise VendorEvidenceError(f'{field} must be an array')
    out: dict[str, list[str]] = {}
    for index, item in enumerate(bindings):
        if not isinstance(item, Mapping):
            raise VendorEvidenceError(f'{field}[{index}] must be an object')
        if set(item) != {'claim_id', 'category_ids'}:
            raise VendorEvidenceError(f'{field}[{index}] has unexpected keys')
        claim_id = _require_string(item['claim_id'], field=f'{field}[{index}].claim_id')
        category_ids = item['category_ids']
        if not isinstance(category_ids, list) or not category_ids:
            raise VendorEvidenceError(f'{field}[{index}].category_ids must be a non-empty array')
        normalized: list[str] = []
        for category_id in category_ids:
            if not isinstance(category_id, str):
                raise VendorEvidenceError(f'{field}[{index}].category_ids contains a non-string')
            if category_id not in REQUIRED_CATEGORIES:
                raise VendorEvidenceError(
                    f'{field}[{index}].category_ids contains unexpected category {category_id!r}'
                )
            if category_id not in normalized:
                normalized.append(category_id)
        out[claim_id] = normalized
    return out


def _cid(value: Mapping[str, Any]) -> str:
    value = {key: value[key] for key in value if key != 'artifact_cid'}
    return calculate_artifact_cid(value)


def build_vendor_evidence_placeholder_manifest(
    *,
    template: Mapping[str, Any],
    generated_at_utc: str = '2026-07-19T00:00:00Z',
    expires_at_utc: str = '2026-08-10T00:00:00Z',
) -> dict[str, Any]:
    """Build a strict, non-accepted placeholder manifest for task PORTAL-CXTP-153."""

    if _require_string(template.get('schema_version'), field='template.schema_version') != 'xaman-vendor-evidence-intake-template/v1':
        raise VendorEvidenceError('template schema version is unexpected')

    category_evidence: list[dict[str, Any]] = []
    owner_ref = {
        'owner_role': 'vendor release evidence owner',
        'owner_name': 'pending_vendor_owner',
        'signed_at_utc': generated_at_utc,
        'authorized_channel': 'pending_vendor_authorization',
    }
    for category_id in REQUIRED_CATEGORIES:
        category_evidence.append(
            {
                'category_id': category_id,
                'status': 'pending_submission',
                'evidence_received': False,
                'redaction_review_passed': False,
                'owner_signoff': owner_ref,
                'evidence_references': [],
            }
        )

    claim_bindings = [
        {
            'claim_id': 'xaman-claim:backend-payload-service-is-trusted-not-proved',
            'category_ids': ['backend_payload_semantics', 'test_device_trace_review'],
        },
        {
            'claim_id': 'xaman-claim:runtime-equivalence-is-blocked-without-device-traces',
            'category_ids': ['test_device_trace_review', 'native_vault_biometric_policy'],
        },
    ]

    manifest = {
        'schema_version': MANIFEST_SCHEMA_VERSION,
        'task_id': TASK_ID,
        'manifest_status': 'WAITING_FOR_REVIEW',
        'corpus': 'xaman-app',
        'generated_at_utc': generated_at_utc,
        'expires_at_utc': expires_at_utc,
        'intake_template_path': INTAKE_TEMPLATE_PATH,
        'category_evidence': category_evidence,
        'claim_bindings': claim_bindings,
    }
    return validate_vendor_evidence_manifest(manifest)


def validate_vendor_evidence_manifest(manifest: Mapping[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
    """Validate a vendor-evidence manifest and return normalized payload."""

    payload = _require_exact_keys(
        manifest,
        MANIFEST_REQUIRED_KEYS,
        field='manifest',
        allowed_extra=frozenset({'artifact_cid'}),
    )


    if payload['schema_version'] != MANIFEST_SCHEMA_VERSION:
        raise VendorEvidenceError('manifest has unexpected schema version')
    if payload['task_id'] != TASK_ID:
        raise VendorEvidenceError('manifest has unexpected task identifier')
    if payload['corpus'] != 'xaman-app':
        raise VendorEvidenceError('manifest must reference xaman-app corpus')

    _parse_timestamp(payload['generated_at_utc'], field='manifest.generated_at_utc')
    expires = _parse_timestamp(payload['expires_at_utc'], field='manifest.expires_at_utc')
    if now and expires <= now:
        raise VendorEvidenceError('manifest is expired')

    if _require_string(payload['intake_template_path'], field='manifest.intake_template_path') != INTAKE_TEMPLATE_PATH:
        raise VendorEvidenceError('manifest intake template path is unexpected')

    if payload['manifest_status'] not in {'WAITING_FOR_REVIEW', 'REVIEW_REJECTED', 'REVIEWED_PENDING_RESHARE'}:
        raise VendorEvidenceError('manifest status is invalid for this lane')

    category_list = payload.get('category_evidence')
    if not isinstance(category_list, list) or not category_list:
        raise VendorEvidenceError('manifest.category_evidence must be a non-empty array')
    normalized_categories: dict[str, Any] = {}
    for index, item in enumerate(category_list):
        category_id = str(item.get('category_id'))
        normalized_categories[category_id] = _validate_manifest_category(
            item,
            field=f'manifest.category_evidence[{index}]',
        )
    if set(normalized_categories) != set(REQUIRED_CATEGORIES):
        missing = set(REQUIRED_CATEGORIES) - set(normalized_categories)
        raise VendorEvidenceError(f'manifest.category_evidence missing required category ids: {sorted(missing)}')

    claim_bindings = _validate_claim_bindings(payload['claim_bindings'], field='manifest.claim_bindings')
    if not all(claim in claim_bindings for claim in DEFAULT_REQUIRED_CLAIMS):
        missing = sorted(set(DEFAULT_REQUIRED_CLAIMS) - set(claim_bindings))
        raise VendorEvidenceError(f'manifest.claim_bindings missing required claims {missing}')

    normalized = {
        'schema_version': MANIFEST_SCHEMA_VERSION,
        'task_id': TASK_ID,
        'manifest_status': payload['manifest_status'],
        'corpus': payload['corpus'],
        'generated_at_utc': _require_string(payload['generated_at_utc'], field='manifest.generated_at_utc'),
        'expires_at_utc': _require_string(payload['expires_at_utc'], field='manifest.expires_at_utc'),
        'intake_template_path': INTAKE_TEMPLATE_PATH,
        'category_evidence': [value for _, value in sorted(normalized_categories.items())],
        'claim_bindings': [
            {'claim_id': claim, 'category_ids': categories}
            for claim, categories in sorted((key, value) for key, value in claim_bindings.items())
        ],
    }
    normalized['artifact_cid'] = _cid({key: value for key, value in normalized.items()})

    _assert_no_sensitive_material(normalized, field='manifest')
    return normalized


def build_vendor_evidence_review_template(manifest: Mapping[str, Any]) -> dict[str, Any]:
    manifest = validate_vendor_evidence_manifest(manifest)
    template = {
        'schema_version': REVIEW_TEMPLATE_SCHEMA_VERSION,
        'task_id': TASK_REVIEW_ID,
        'template_status': 'REVIEW_REQUIRED',
        'manifest_cid': manifest['artifact_cid'],
        'required_scope': {
            'vendor_release_equivalent': False,
            'production_security_result': False,
            'public_source_verifier_only': False,
        },
        'required_review_criteria': [
            'accepted',
            'all_required_claims_bound',
            'all_required_categories_reviewed',
            'no_sensitive_material_present',
            'request_authorized_channel_evidence',
        ],
    }
    template['artifact_cid'] = _cid_without(template)
    return template


def validate_vendor_evidence_review(
    review: Mapping[str, Any],
    *,
    manifest: Mapping[str, Any],
    now: datetime | None = None,
) -> dict[str, Any]:
    """Validate a vendor evidence review and return a verification outcome."""

    normalized_manifest = validate_vendor_evidence_manifest(manifest)
    value = _require_exact_keys(review, REVIEW_REQUIRED_KEYS, field='review')

    if value['schema_version'] != REVIEW_SCHEMA_VERSION:
        raise VendorEvidenceError('review has unexpected schema version')
    if value['task_id'] != TASK_REVIEW_ID:
        raise VendorEvidenceError('review task id is invalid')

    manifest_cid = _require_string(value['manifest_cid'], field='review.manifest_cid')
    if manifest_cid != normalized_manifest['artifact_cid']:
        raise VendorEvidenceError('review is not bound to the supplied manifest')

    reviewed_at = _parse_timestamp(value['reviewed_at_utc'], field='review.reviewed_at_utc')
    expires_at = _parse_timestamp(value['expires_at_utc'], field='review.expires_at_utc')

    reviewer = value['reviewer']
    if not isinstance(reviewer, Mapping):
        raise VendorEvidenceError('review.reviewer must be an object')
    for key in {'reviewer_id_sha256', 'independent_of_vendor_author', 'conflict_of_interest_declared'}:
        if key not in reviewer:
            raise VendorEvidenceError(f'review.reviewer is missing {key}')
    if not isinstance(reviewer['reviewer_id_sha256'], str) or not SHA256_RE.match(reviewer['reviewer_id_sha256']):
        raise VendorEvidenceError('review.reviewer.reviewer_id_sha256 must be SHA-256')
    _require_bool(reviewer['independent_of_vendor_author'], field='review.reviewer.independent_of_vendor_author')
    _require_bool(reviewer['conflict_of_interest_declared'], field='review.reviewer.conflict_of_interest_declared')
    if reviewer['independent_of_vendor_author'] is not True:
        raise VendorEvidenceError('reviewer independence is required')
    if reviewer['conflict_of_interest_declared'] is not False:
        raise VendorEvidenceError('reviewer conflict-of-interest must be declared false')

    scope = value['scope']
    if not isinstance(scope, Mapping):
        raise VendorEvidenceError('review.scope must be an object')
    scope_keys = {'vendor_release_equivalent', 'production_security_result', 'public_source_verifier_only'}
    if set(scope) != scope_keys:
        raise VendorEvidenceError('review.scope has unexpected keys')
    if scope['vendor_release_equivalent'] is not False:
        raise VendorEvidenceError('review.scope must not assert vendor-release equivalence')
    if scope['production_security_result'] is not False:
        raise VendorEvidenceError('review.scope must not assert production-security result')

    review_decision = _require_string(value['decision'], field='review.decision')
    if review_decision not in {'accepted', 'needs_clarification', 'rejected'}:
        raise VendorEvidenceError('review.decision must be accepted/needs_clarification/rejected')

    category_bindings = _validate_claim_bindings(value.get('category_reviews', []), field='review.category_reviews')
    if review_decision == 'accepted':
        required_claims = sorted(DEFAULT_REQUIRED_CLAIMS)
        missing = [claim for claim in required_claims if claim not in category_bindings]
        if missing:
            raise VendorEvidenceError(f'review must bind required claims before acceptance: {missing}')
        for claim_id in required_claims:
            bound = False
            for cat in category_bindings[claim_id]:
                cat_entry = {item['category_id']: item for item in normalized_manifest['category_evidence']}.get(cat)
                if cat_entry is None:
                    raise VendorEvidenceError(f'review references unknown category {cat!r} for claim {claim_id!r}')
                if cat_entry['evidence_received'] and cat_entry['redaction_review_passed']:
                    bound = True
            if not bound:
                raise VendorEvidenceError(f'claim {claim_id} is not backed by accepted category evidence')

    _assert_no_sensitive_material(value, field='review')

    review_is_time_valid = expires_at > reviewed_at
    accepted = review_decision == 'accepted' and review_is_time_valid
    if now is not None:
        accepted = accepted and now <= expires_at

    report = {
        'schema_version': REVIEW_VERIFICATION_SCHEMA_VERSION,
        'task_id': TASK_REVIEW_ID,
        'manifest_cid': manifest_cid,
        'review_task_id': value['task_id'],
        'reviewer_id_sha256': reviewer['reviewer_id_sha256'],
        'reviewed_at_utc': reviewed_at.strftime('%Y-%m-%dT%H:%M:%SZ'),
        'expires_at_utc': expires_at.strftime('%Y-%m-%dT%H:%M:%SZ'),
        'decision': review_decision,
        'overall_status': 'accepted' if accepted else ('expired' if review_decision == 'accepted' else 'pending_review'),
        'review_accepted_for_gap_clearance': accepted,
        'required_claims_present': [claim for claim in sorted(category_bindings)],
        'all_required_claims_bound': all(claim in category_bindings for claim in DEFAULT_REQUIRED_CLAIMS),
        'scope': {
            'vendor_release_equivalent': scope['vendor_release_equivalent'],
            'production_security_result': scope['production_security_result'],
            'public_source_verifier_only': scope.get('public_source_verifier_only'),
        },
    }
    report['artifact_cid'] = _cid_without(report)
    if not review_is_time_valid and review_decision == 'accepted':
        report['overall_status'] = 'expired'
    return report


def review_clears_external_claim(
    manifest: Mapping[str, Any],
    review: Mapping[str, Any],
    claim_id: str,
    *,
    now: datetime | None = None,
) -> bool:
    """Return True when this claim is cleared by a valid accepted vendor review."""

    if claim_id not in DEFAULT_REQUIRED_CLAIMS and claim_id not in {
        key for key in _validate_claim_bindings(manifest.get('claim_bindings', []), field='manifest.claim_bindings')
    }:
        return False
    verification = validate_vendor_evidence_review(review, manifest=manifest, now=now)
    if not verification['review_accepted_for_gap_clearance']:
        return False
    bound_claims = set(verification['required_claims_present'])
    return claim_id in bound_claims
