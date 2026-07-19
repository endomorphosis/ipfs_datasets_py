"""Fail-closed validation for a redacted self-hosted Xaman runtime trace.

This module deliberately validates an evidence *envelope*, not Xaman's runtime
itself.  A valid envelope proves only that a reviewed operator recorded the
required categorical paths against the separately reviewed self-hosted
candidate.  It cannot establish vendor-release equivalence or production
wallet security.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import re
from typing import Any, Mapping, Sequence

from ..ir.cid import calculate_artifact_cid


TASK_ID = 'PORTAL-CXTP-158'
TRACE_SCHEMA_VERSION = 'xaman-self-hosted-runtime-trace-review/v1'
REPORT_SCHEMA_VERSION = 'xaman-self-hosted-runtime-conformance-report/v1'
TEMPLATE_SCHEMA_VERSION = 'xaman-self-hosted-runtime-trace-template/v1'
PINNED_XAMAN_COMMIT = '942f43876265a7af44f233288ad2b1d00841d5fa'
SELF_HOSTED_NETWORK_ID = 777777

REQUIRED_ACTIONS = (
    'onboarding',
    'local_network_selection',
    'review',
    'signature_decision',
    'submit_result',
    'cancellation',
    'expiry',
    'replay',
    'reconnect',
    'network_change',
)

ACTION_OUTCOMES = {
    'onboarding': frozenset({'completed'}),
    'local_network_selection': frozenset({'local_network_selected'}),
    'review': frozenset({'reviewed'}),
    'signature_decision': frozenset({'approved', 'declined'}),
    'submit_result': frozenset({'submitted', 'rejected'}),
    'cancellation': frozenset({'cancelled'}),
    'expiry': frozenset({'expired'}),
    'replay': frozenset({'blocked'}),
    'reconnect': frozenset({'reconnected'}),
    'network_change': frozenset({'local_network_retained'}),
}

ALLOWED_SOURCE_KINDS = frozenset(
    {'reviewed_ui', 'reviewed_logcat_digest', 'reviewed_network_digest', 'reviewed_screenshot_digest'}
)
ALLOWED_TOP_LEVEL_KEYS = frozenset(
    {
        'schema_version',
        'task_id',
        'trace_id',
        'captured_at_utc',
        'reviewed_at_utc',
        'scope',
        'dependency_cids',
        'review_gate',
        'lifecycle_events',
        'redaction',
        'artifact_cid',
    }
)
ALLOWED_SCOPE_KEYS = frozenset(
    {
        'public_source_verifier_only',
        'vendor_release_equivalent',
        'production_security_result',
        'source_commit',
        'network_id',
        'fresh_debug_emulator',
        'external_egress_observed',
        'vendor_fallback_observed',
    }
)
REQUIRED_DEPENDENCIES = (
    'endpoint_rebound_candidate',
    'bridge_isolation_report',
    'daemon_health',
    'security_model',
)
ALLOWED_DEPENDENCY_KEYS = frozenset(REQUIRED_DEPENDENCIES)
ALLOWED_REVIEW_GATE_KEYS = frozenset(
    {'endpoint_rebind_review', 'status', 'expires_at_utc', 'reviewer_id_sha256'}
)
ALLOWED_EVENT_KEYS = frozenset(
    {'ordinal', 'action', 'outcome', 'source_kind', 'source_sha256', 'redaction_sha256', 'raw_material_recorded'}
)
ALLOWED_REDACTION_KEYS = frozenset({'raw_sensitive_material_retained', 'redaction_review_sha256'})

SHA256_RE = re.compile(r'^[a-f0-9]{64}$')
CID_RE = re.compile(r'^sha256:[a-f0-9]{64}$')
IDENTIFIER_RE = re.compile(r'^[A-Za-z0-9_.:-]{1,160}$')
TIMESTAMP_RE = re.compile(r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$')
XRPL_ADDRESS_RE = re.compile(r'\br[1-9A-HJ-NP-Za-km-z]{24,35}\b')
XRPL_XADDRESS_RE = re.compile(r'\b[XT][1-9A-HJ-NP-Za-km-z]{40,60}\b')
XRPL_SEED_RE = re.compile(r'\bs[1-9A-HJ-NP-Za-km-z]{25,35}\b')
RAW_ENDPOINT_RE = re.compile(r'\b(?:wss?|https?)://[^\s"\'<>]+', re.IGNORECASE)
JWT_RE = re.compile(r'\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b')
BEARER_RE = re.compile(r'\bBearer\s+[A-Za-z0-9._~+/=-]{8,}\b', re.IGNORECASE)
LONG_HEX_RE = re.compile(r'\b[A-Fa-f0-9]{128,}\b')

SENSITIVE_KEY_TOKENS = frozenset(
    {
        'account',
        'address',
        'apikey',
        'authorization',
        'blob',
        'body',
        'credential',
        'endpoint',
        'jwt',
        'mnemonic',
        'password',
        'payload',
        'private',
        'request',
        'response',
        'seed',
        'secret',
        'session',
        'token',
        'transaction',
        'txjson',
        'wallet',
    }
)


class SelfHostedRuntimeTraceError(ValueError):
    """Raised when a self-hosted runtime trace is incomplete or unsafe."""


def _cid_without(payload: Mapping[str, Any]) -> str:
    return calculate_artifact_cid({key: value for key, value in payload.items() if key != 'artifact_cid'})


def _parse_timestamp(value: Any, *, field: str) -> datetime:
    if not isinstance(value, str) or not TIMESTAMP_RE.fullmatch(value):
        raise SelfHostedRuntimeTraceError(f'{field} must be a UTC second-resolution timestamp')
    try:
        return datetime.strptime(value, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise SelfHostedRuntimeTraceError(f'{field} is not a valid timestamp') from exc


def _require_exact_keys(value: Any, keys: frozenset[str], *, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise SelfHostedRuntimeTraceError(f'{field} must be an object')
    actual = set(value)
    missing = keys - actual
    extra = actual - keys
    if missing or extra:
        details: list[str] = []
        if missing:
            details.append(f'missing {sorted(missing)}')
        if extra:
            details.append(f'unexpected {sorted(extra)}')
        raise SelfHostedRuntimeTraceError(f'{field} has ' + '; '.join(details))
    return value


def _assert_digest(value: Any, *, field: str, cid: bool = False) -> str:
    pattern = CID_RE if cid else SHA256_RE
    if not isinstance(value, str) or not pattern.fullmatch(value):
        expected = 'sha256 CID' if cid else 'SHA-256 digest'
        raise SelfHostedRuntimeTraceError(f'{field} must be a lowercase {expected}')
    if not cid and len(set(value)) == 1:
        raise SelfHostedRuntimeTraceError(f'{field} must not use a repeated-character placeholder')
    return value


def _assert_no_sensitive_material(value: Any, *, field: str = 'trace') -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            normalized = re.sub(r'[^a-z0-9]+', '', str(key).lower())
            if normalized in SENSITIVE_KEY_TOKENS:
                raise SelfHostedRuntimeTraceError(f'{field} contains prohibited sensitive key {key!r}')
            _assert_no_sensitive_material(item, field=f'{field}.{key}')
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _assert_no_sensitive_material(item, field=f'{field}[{index}]')
        return
    if not isinstance(value, str):
        return
    patterns = (XRPL_ADDRESS_RE, XRPL_XADDRESS_RE, XRPL_SEED_RE, RAW_ENDPOINT_RE, JWT_RE, BEARER_RE, LONG_HEX_RE)
    if any(pattern.search(value) for pattern in patterns):
        raise SelfHostedRuntimeTraceError(f'{field} contains raw sensitive material')


def validate_runtime_trace(
    trace: Mapping[str, Any],
    *,
    now: datetime | None = None,
) -> None:
    """Validate a reviewed trace and fail closed for every missing path or gate."""

    _require_exact_keys(trace, ALLOWED_TOP_LEVEL_KEYS, field='trace')
    if trace.get('schema_version') != TRACE_SCHEMA_VERSION:
        raise SelfHostedRuntimeTraceError('trace schema_version is invalid')
    if trace.get('task_id') != TASK_ID:
        raise SelfHostedRuntimeTraceError('trace task_id is invalid')
    trace_id = trace.get('trace_id')
    if not isinstance(trace_id, str) or not IDENTIFIER_RE.fullmatch(trace_id):
        raise SelfHostedRuntimeTraceError('trace_id is invalid')
    _parse_timestamp(trace.get('captured_at_utc'), field='captured_at_utc')
    reviewed_at = _parse_timestamp(trace.get('reviewed_at_utc'), field='reviewed_at_utc')

    scope = _require_exact_keys(trace.get('scope'), ALLOWED_SCOPE_KEYS, field='scope')
    expected_scope = {
        'public_source_verifier_only': True,
        'vendor_release_equivalent': False,
        'production_security_result': False,
        'source_commit': PINNED_XAMAN_COMMIT,
        'network_id': SELF_HOSTED_NETWORK_ID,
        'fresh_debug_emulator': True,
        'external_egress_observed': False,
        'vendor_fallback_observed': False,
    }
    if dict(scope) != expected_scope:
        raise SelfHostedRuntimeTraceError('trace scope does not preserve the required self-hosted boundary')

    dependencies = _require_exact_keys(trace.get('dependency_cids'), ALLOWED_DEPENDENCY_KEYS, field='dependency_cids')
    for key, value in dependencies.items():
        _assert_digest(value, field=f'dependency_cids.{key}', cid=True)

    review_gate = _require_exact_keys(trace.get('review_gate'), ALLOWED_REVIEW_GATE_KEYS, field='review_gate')
    _assert_digest(review_gate.get('endpoint_rebind_review'), field='review_gate.endpoint_rebind_review', cid=True)
    _assert_digest(review_gate.get('reviewer_id_sha256'), field='review_gate.reviewer_id_sha256')
    if review_gate.get('status') != 'passed':
        raise SelfHostedRuntimeTraceError('independent endpoint-rebind review has not passed')
    expires_at = _parse_timestamp(review_gate.get('expires_at_utc'), field='review_gate.expires_at_utc')
    reference_time = now or datetime.now(timezone.utc)
    if expires_at <= reference_time:
        raise SelfHostedRuntimeTraceError('independent endpoint-rebind review is expired')
    if reviewed_at > reference_time:
        raise SelfHostedRuntimeTraceError('trace review timestamp is in the future')

    events = trace.get('lifecycle_events')
    if not isinstance(events, list) or len(events) != len(REQUIRED_ACTIONS):
        raise SelfHostedRuntimeTraceError('lifecycle_events must contain every required action exactly once')
    actions: list[str] = []
    for ordinal, event in enumerate(events, start=1):
        event = _require_exact_keys(event, ALLOWED_EVENT_KEYS, field=f'lifecycle_events[{ordinal - 1}]')
        if event.get('ordinal') != ordinal:
            raise SelfHostedRuntimeTraceError('lifecycle event ordinals must be contiguous and ordered')
        action = event.get('action')
        if action not in ACTION_OUTCOMES:
            raise SelfHostedRuntimeTraceError(f'unsupported lifecycle action {action!r}')
        if event.get('outcome') not in ACTION_OUTCOMES[action]:
            raise SelfHostedRuntimeTraceError(f'unsupported outcome for lifecycle action {action!r}')
        if event.get('source_kind') not in ALLOWED_SOURCE_KINDS:
            raise SelfHostedRuntimeTraceError(f'unsupported source kind for lifecycle action {action!r}')
        _assert_digest(event.get('source_sha256'), field=f'lifecycle_events[{ordinal - 1}].source_sha256')
        _assert_digest(event.get('redaction_sha256'), field=f'lifecycle_events[{ordinal - 1}].redaction_sha256')
        if event.get('raw_material_recorded') is not False:
            raise SelfHostedRuntimeTraceError('lifecycle events must not retain raw material')
        actions.append(action)
    if tuple(actions) != REQUIRED_ACTIONS:
        raise SelfHostedRuntimeTraceError('lifecycle event order or coverage does not match the required trace contract')

    redaction = _require_exact_keys(trace.get('redaction'), ALLOWED_REDACTION_KEYS, field='redaction')
    if redaction.get('raw_sensitive_material_retained') is not False:
        raise SelfHostedRuntimeTraceError('trace redaction boundary is invalid')
    _assert_digest(redaction.get('redaction_review_sha256'), field='redaction.redaction_review_sha256')

    _assert_no_sensitive_material(trace)
    if trace.get('artifact_cid') != _cid_without(trace):
        raise SelfHostedRuntimeTraceError('trace artifact CID does not match canonical payload')


def build_runtime_conformance_report(trace: Mapping[str, Any]) -> dict[str, Any]:
    """Build a small redacted report after :func:`validate_runtime_trace` succeeds."""

    validate_runtime_trace(trace)
    report: dict[str, Any] = {
        'schema_version': REPORT_SCHEMA_VERSION,
        'task_id': TASK_ID,
        'trace_artifact_cid': trace['artifact_cid'],
        'dependency_cids': dict(trace['dependency_cids']),
        'scope': {
            'public_source_verifier_only': True,
            'vendor_release_equivalent': False,
            'production_security_result': False,
            'network_id': SELF_HOSTED_NETWORK_ID,
        },
        'review_gate': {
            'endpoint_rebind_review': trace['review_gate']['endpoint_rebind_review'],
            'status': 'passed',
            'expires_at_utc': trace['review_gate']['expires_at_utc'],
        },
        'covered_actions': list(REQUIRED_ACTIONS),
        'redaction_boundary': {
            'raw_sensitive_material_retained': False,
            'raw_material_reintroduction_rejected': True,
        },
        'overall_status': 'reviewed_self_hosted_verifier_trace',
        'security_decision': 'VERIFIER_ONLY_RUNTIME_TRACE_RECORDED',
        'production_release_blocked': True,
        'verdict_policy': {
            'vendor_release_assurance_allowed': False,
            'production_security_assurance_allowed': False,
            'trace_does_not_clear_vendor_or_backend_assumptions': True,
        },
    }
    _assert_no_sensitive_material(report, field='report')
    report['artifact_cid'] = _cid_without(report)
    return report


def build_trace_template() -> dict[str, Any]:
    """Return a non-evidence template for an independently reviewed capture."""

    return {
        'schema_version': TEMPLATE_SCHEMA_VERSION,
        'task_id': TASK_ID,
        'template_status': 'NOT_RUNTIME_EVIDENCE',
        'required_actions': list(REQUIRED_ACTIONS),
        'scope_requirements': {
            'public_source_verifier_only': True,
            'vendor_release_equivalent': False,
            'production_security_result': False,
            'source_commit': PINNED_XAMAN_COMMIT,
            'network_id': SELF_HOSTED_NETWORK_ID,
            'fresh_debug_emulator': True,
            'external_egress_observed': False,
            'vendor_fallback_observed': False,
        },
        'dependency_requirements': list(REQUIRED_DEPENDENCIES),
        'review_gate_requirements': {
            'status': 'passed',
            'independent_review_required': True,
            'unexpired_review_required': True,
        },
        'redaction_requirements': {
            'raw_sensitive_material_retained': False,
            'prohibited_material': [
                'seeds',
                'account identifiers',
                'payloads',
                'transaction blobs',
                'credentials',
                'raw endpoints',
                'raw request or response bodies',
            ],
        },
        'acceptance_boundary': 'A completed trace is verifier-only evidence and cannot claim vendor-release equivalence or production wallet security.',
    }


def load_trace(path: str) -> dict[str, Any]:
    try:
        parsed = json.loads(open(path, encoding='utf-8').read())
    except (OSError, json.JSONDecodeError) as exc:
        raise SelfHostedRuntimeTraceError(f'cannot load runtime trace {path}') from exc
    if not isinstance(parsed, dict):
        raise SelfHostedRuntimeTraceError('runtime trace must be a JSON object')
    return parsed
