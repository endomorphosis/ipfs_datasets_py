#!/usr/bin/env python3
"""Assemble a redacted Xaman XRPL Testnet transaction-lifecycle report.

The report consumes reviewed categorical lifecycle evidence and the already
reviewed Testnet device, network-selection, and native-Firebase boundary
reports. It intentionally stores only action categories, categorical outcomes,
source digests, dependency digests, and coverage gaps. It rejects account
addresses, seeds, credentials, raw payloads, transaction blobs, raw endpoint
URLs, and raw request/response bodies.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Mapping, Sequence


SCHEMA_VERSION = 'xaman-testnet-transaction-lifecycle-trial/v1'
EVIDENCE_SCHEMA_VERSION = 'xaman-testnet-transaction-lifecycle-evidence/v1'
TASK_ID = 'PORTAL-CXTP-130'
PINNED_XAMAN_COMMIT = '942f43876265a7af44f233288ad2b1d00841d5fa'
DEFAULT_VERIFIER_ROOT = Path('/home/barberb/.local/share/ipfs-datasets-xaman-testnet-verifier')
DEFAULT_APK = DEFAULT_VERIFIER_ROOT / 'xaman-app/android/app/build/outputs/apk/debug/app-x86_64-debug.apk'
DEFAULT_LIFECYCLE_EVIDENCE = Path(
    'security_ir_artifacts/corpora/xaman-app/runtime/testnet-transaction-lifecycle-evidence.json'
)
DEFAULT_DEVICE_REPORT = Path(
    'security_ir_artifacts/corpora/xaman-app/runtime/testnet-device-trial-report.json'
)
DEFAULT_NETWORK_REPORT = Path(
    'security_ir_artifacts/corpora/xaman-app/runtime/testnet-network-selection-report.json'
)
DEFAULT_NATIVE_FIREBASE_REPORT = Path(
    'security_ir_artifacts/corpora/xaman-app/runtime/native-firebase-boundary-report.json'
)
DEFAULT_OUT = Path(
    'security_ir_artifacts/corpora/xaman-app/runtime/testnet-transaction-trial-report.json'
)

REQUIRED_ACTIONS = (
    'payload_intake',
    'review',
    'auth_decision',
    'signing_decision',
    'submit_attempt',
    'submit_result',
    'decline',
    'cancel',
    'expiry',
    'reconnect',
    'network_switch',
)
REQUIRED_NETWORK_SELECTION_EVENT_CATEGORIES = frozenset(
    {
        'fresh_emulator_profile',
        'fresh_testnet_account_boundary',
        'fresh_testnet_account_created',
        'xaman_network_selected',
        'xrpl_server_info_observed',
    }
)
ACTION_CATEGORIES = {
    'payload_intake': 'payload_intake',
    'review': 'payload_review',
    'auth_decision': 'auth_decision',
    'signing_decision': 'signing_decision',
    'submit_attempt': 'submit_attempt',
    'submit_result': 'submit_result',
    'decline': 'decline',
    'cancel': 'cancel',
    'expiry': 'expiry',
    'reconnect': 'reconnect',
    'network_switch': 'network_switch',
}
ALLOWED_EVIDENCE_TYPES = frozenset({'reviewed_device_trace', 'reviewed_ui', 'reviewed_operator_trial'})
ALLOWED_SOURCE_KINDS = frozenset(
    {'reviewed_ui', 'reviewed_logcat_digest', 'reviewed_network_digest', 'reviewed_screenshot_digest'}
)
ALLOWED_LIFECYCLE_EVIDENCE_KEYS = frozenset(
    {
        'schema_version',
        'evidence_type',
        'reviewed_at_utc',
        'fresh_emulator_profile',
        'network_key',
        'fresh_account_boundary',
        'lifecycle_events',
        'coverage_gaps',
    }
)
ALLOWED_LIFECYCLE_EVENT_KEYS = frozenset(
    {
        'ordinal',
        'action',
        'category',
        'outcome',
        'source_kind',
        'source_sha256',
        'redaction_sha256',
        'raw_material_recorded',
    }
)
ALLOWED_COVERAGE_GAP_KEYS = frozenset({'action', 'reason_code', 'reviewer_note_sha256'})
ALLOWED_FRESH_ACCOUNT_BOUNDARY_KEYS = frozenset(
    {
        'fresh_account_created',
        'imported_account',
        'production_account',
        'account_material_recorded',
        'boundary',
    }
)
ALLOWED_OUTCOMES = frozenset(
    {
        'accepted',
        'authorized',
        'blocked',
        'cancelled',
        'declined',
        'expired',
        'failed',
        'not_observed',
        'observed',
        'reconnected',
        'reviewed',
        'signed',
        'submitted',
        'succeeded',
        'switched_to_testnet',
    }
)
ACTION_ALLOWED_OUTCOMES = {
    'payload_intake': frozenset({'accepted', 'blocked'}),
    'review': frozenset({'reviewed'}),
    'auth_decision': frozenset({'authorized', 'blocked', 'declined'}),
    'signing_decision': frozenset({'signed', 'blocked', 'declined'}),
    'submit_attempt': frozenset({'submitted', 'failed'}),
    'submit_result': frozenset({'succeeded', 'failed'}),
    'decline': frozenset({'declined'}),
    'cancel': frozenset({'cancelled'}),
    'expiry': frozenset({'expired'}),
    'reconnect': frozenset({'reconnected'}),
    'network_switch': frozenset({'switched_to_testnet'}),
}
ALLOWED_GAP_REASONS = frozenset(
    {
        'not_exercised_in_reviewed_trial',
        'not_reached_due_to_prior_decision',
        'not_observable_without_sensitive_material',
        'external_service_did_not_emit_observable_state',
        'operator_stopped_before_action',
    }
)

IDENTIFIER_RE = re.compile(r'^[A-Za-z0-9_.:-]{1,160}$')
GENERATED_AT_UTC_RE = re.compile(r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$')
SHA256_RE = re.compile(r'^[a-f0-9]{64}$')
SHA256_CID_RE = re.compile(r'^sha256:[a-f0-9]{64}$')
PLACEHOLDER_SHA256_RE = re.compile(r'^([a-f0-9])\1{63}$')
XRPL_ADDRESS_RE = re.compile(r'\br[1-9A-HJ-NP-Za-km-z]{24,35}\b')
XRPL_XADDRESS_RE = re.compile(r'\b[XT][1-9A-HJ-NP-Za-km-z]{40,60}\b')
XRPL_SEED_RE = re.compile(r'\bs[1-9A-HJ-NP-Za-km-z]{25,35}\b')
RAW_ENDPOINT_URL_RE = re.compile(r'\b(?:wss?|https?)://[^\s"\'<>]+', re.IGNORECASE)
JWT_RE = re.compile(r'\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b')
BEARER_TOKEN_RE = re.compile(r'\bBearer\s+[A-Za-z0-9._~+/=-]{8,}\b', re.IGNORECASE)
LONG_TRANSACTION_HEX_RE = re.compile(r'\b[A-Fa-f0-9]{128,}\b')
RAW_XRPL_TRANSACTION_JSON_RE = re.compile(
    r'["\'](?:TransactionType|SigningPubKey|TxnSignature|Account|Destination)["\']\s*:',
    re.IGNORECASE,
)
RAW_PAYLOAD_JSON_RE = re.compile(
    r'["\'](?:payload|tx[_-]?json|blob|signed[_-]?transaction|signed[_-]?blob)["\']\s*:',
    re.IGNORECASE,
)
RAW_XRPL_TRANSACTION_KEY_FORMS = frozenset(
    {
        'account',
        'destination',
        'signingpubkey',
        'transactiontype',
        'txnsignature',
    }
)

SENSITIVE_KEY_TOKEN_SEQUENCES = (
    ('account', 'material'),
    ('account', 'address'),
    ('address',),
    ('api', 'key'),
    ('apikey',),
    ('auth', 'token'),
    ('authorization',),
    ('bearer',),
    ('blob',),
    ('body',),
    ('credential',),
    ('endpoint', 'url'),
    ('jwt',),
    ('mnemonic',),
    ('passcode',),
    ('password',),
    ('payload',),
    ('private',),
    ('raw',),
    ('request', 'body'),
    ('request', 'payload'),
    ('response', 'body'),
    ('seed',),
    ('secret',),
    ('session',),
    ('signature',),
    ('signed', 'transaction'),
    ('signed', 'blob'),
    ('token',),
    ('transaction', 'blob'),
    ('tx', 'blob'),
    ('tx', 'json'),
    ('wallet', 'address'),
)
DIGEST_KEY_TOKENS = frozenset({'cid', 'digest', 'hash', 'sha256'})
KEY_TOKEN_CANONICAL_FORMS = {
    'addresses': 'address',
    'bodies': 'body',
    'blobs': 'blob',
    'credentials': 'credential',
    'endpoints': 'endpoint',
    'hashes': 'hash',
    'keys': 'key',
    'mnemonics': 'mnemonic',
    'passwords': 'password',
    'payloads': 'payload',
    'requests': 'request',
    'responses': 'response',
    'secrets': 'secret',
    'seeds': 'seed',
    'sessions': 'session',
    'signatures': 'signature',
    'tokens': 'token',
    'transactions': 'transaction',
}


class TransactionTrialError(ValueError):
    """Raised when lifecycle evidence is invalid or violates redaction."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _artifact_cid(payload: Mapping[str, Any]) -> str:
    canonical = json.dumps(
        {key: value for key, value in payload.items() if key != 'artifact_cid'},
        sort_keys=True,
        separators=(',', ':'),
    ).encode('utf-8')
    return 'sha256:' + _sha256_bytes(canonical)


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + '\n', encoding='utf-8')


def _load_json_bytes(path: Path) -> tuple[dict[str, Any], bytes]:
    raw = path.read_bytes()
    try:
        parsed = json.loads(raw.decode('utf-8'))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f'input is not valid UTF-8 JSON: {path}') from exc
    if not isinstance(parsed, dict):
        raise ValueError(f'input JSON must be an object: {path}')
    return parsed, raw


def _file_record(path: Path | None) -> dict[str, Any] | None:
    if path is None:
        return None
    resolved = path.resolve()
    if not resolved.is_file():
        return {'path_label': _path_label(resolved), 'present': False}
    return {
        'path_label': _path_label(resolved),
        'present': True,
        'sha256': _sha256_file(resolved),
        'size_bytes': resolved.stat().st_size,
    }


def _path_label(path: Any) -> str:
    text = str(path)
    parts = [part for part in re.split(r'[\\/]+', text) if part]
    return parts[-1] if parts else 'unavailable'


def _redact_local_paths(value: Any) -> Any:
    if isinstance(value, Mapping):
        redacted: dict[str, Any] = {}
        for key, nested in value.items():
            if str(key) == 'path':
                redacted['path_label'] = _path_label(nested)
            else:
                redacted[str(key)] = _redact_local_paths(nested)
        return redacted
    if isinstance(value, list):
        return [_redact_local_paths(item) for item in value]
    return value


def _report_record(path: Path, *, expected_task_id: str, expected_schema: str) -> dict[str, Any]:
    record = _file_record(path)
    if record is None or not record.get('present'):
        return {'path_label': _path_label(path.resolve()), 'present': False}
    payload, _raw = _load_json_bytes(path)
    _assert_no_sensitive_material(payload, context=path.as_posix())
    return {
        **record,
        'schema_version': payload.get('schema_version'),
        'task_id': payload.get('task_id'),
        'artifact_cid': payload.get('artifact_cid'),
        'artifact_cid_valid': payload.get('artifact_cid') == _artifact_cid(payload),
        'expected_schema_version': expected_schema,
        'expected_task_id': expected_task_id,
        'schema_matches_expected': payload.get('schema_version') == expected_schema,
        'task_matches_expected': payload.get('task_id') == expected_task_id,
    }


def _key_tokens(key: Any) -> list[str]:
    with_word_boundaries = re.sub(r'([a-z0-9])([A-Z])', r'\1_\2', str(key))
    return [
        KEY_TOKEN_CANONICAL_FORMS.get(token, token)
        for token in re.split(r'[^A-Za-z0-9]+', with_word_boundaries.lower())
        if token
    ]


def _contains_token_sequence(tokens: Sequence[str], sequence: Sequence[str]) -> bool:
    if not sequence or len(sequence) > len(tokens):
        return False
    return any(tokens[index : index + len(sequence)] == list(sequence) for index in range(len(tokens) - len(sequence) + 1))


def _sensitive_key_reason(key: Any) -> str | None:
    tokens = _key_tokens(key)
    if not tokens:
        return None
    compact_key = ''.join(tokens)
    if compact_key in RAW_XRPL_TRANSACTION_KEY_FORMS:
        return 'raw_xrpl_transaction_field'
    if tokens == ['fresh', 'testnet', 'credential']:
        return None
    if tokens in (['endpoint', 'allow', 'list', 'decision'], ['selected', 'endpoint', 'key']):
        return None
    if tokens[-1] in DIGEST_KEY_TOKENS:
        digest_subject = tokens[:-1]
        for sequence in SENSITIVE_KEY_TOKEN_SEQUENCES:
            if _contains_token_sequence(digest_subject, sequence):
                return '_'.join(sequence)
        return None
    for sequence in SENSITIVE_KEY_TOKEN_SEQUENCES:
        if _contains_token_sequence(tokens, sequence):
            return '_'.join(sequence)
    return None


def _assert_no_sensitive_material(value: Any, *, context: str) -> None:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            _assert_no_sensitive_string(str(key), context=context)
            reason = _sensitive_key_reason(key)
            if reason is not None:
                tokens = _key_tokens(key)
                if tokens[-1:] == ['recorded'] and nested is False:
                    continue
                raise TransactionTrialError(f'{context} contains forbidden key {key!r}: {reason}')
            _assert_no_sensitive_material(nested, context=context)
        return
    if isinstance(value, list):
        for item in value:
            _assert_no_sensitive_material(item, context=context)
        return
    if isinstance(value, str):
        _assert_no_sensitive_string(value, context=context)


def _assert_no_sensitive_string(value: str, *, context: str) -> None:
    if RAW_ENDPOINT_URL_RE.search(value):
        raise TransactionTrialError(f'{context} contains a raw endpoint URL')
    if XRPL_ADDRESS_RE.search(value):
        raise TransactionTrialError(f'{context} contains an account address')
    if XRPL_XADDRESS_RE.search(value):
        raise TransactionTrialError(f'{context} contains an X-address')
    if XRPL_SEED_RE.search(value):
        raise TransactionTrialError(f'{context} contains a family seed')
    if JWT_RE.search(value) or BEARER_TOKEN_RE.search(value):
        raise TransactionTrialError(f'{context} contains credential material')
    if LONG_TRANSACTION_HEX_RE.search(value):
        raise TransactionTrialError(f'{context} contains a transaction-sized hex blob')
    if RAW_XRPL_TRANSACTION_JSON_RE.search(value):
        raise TransactionTrialError(f'{context} contains raw XRPL transaction JSON')
    if RAW_PAYLOAD_JSON_RE.search(value):
        raise TransactionTrialError(f'{context} contains raw payload or transaction blob JSON')


def _assert_report_redaction_boundary(report: Mapping[str, Any]) -> None:
    _assert_no_sensitive_material(report, context='transaction lifecycle report')


def _dependency_payload(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    payload, _raw = _load_json_bytes(path)
    _assert_no_sensitive_material(payload, context=path.as_posix())
    return payload


def _dependency_summaries(
    *,
    device_report_path: Path,
    network_report_path: Path,
    native_firebase_report_path: Path,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    device = _dependency_payload(device_report_path)
    network = _dependency_payload(network_report_path)
    native = _dependency_payload(native_firebase_report_path)

    verifier = device.get('verifier_artifact') if isinstance(device.get('verifier_artifact'), Mapping) else {}
    device_profile = device.get('device_profile') if isinstance(device.get('device_profile'), Mapping) else {}
    emulator = (
        device_profile.get('isolated_android_emulator')
        if isinstance(device_profile.get('isolated_android_emulator'), Mapping)
        else {}
    )
    trial_scope = device.get('trial_scope') if isinstance(device.get('trial_scope'), Mapping) else {}
    approved_flow = (
        device.get('approved_non_production_wallet_flow')
        if isinstance(device.get('approved_non_production_wallet_flow'), Mapping)
        else {}
    )
    fresh_account = (
        approved_flow.get('fresh_testnet_credentials')
        if isinstance(approved_flow.get('fresh_testnet_credentials'), Mapping)
        else {}
    )
    endpoint_decision = (
        network.get('endpoint_allow_list_decision')
        if isinstance(network.get('endpoint_allow_list_decision'), Mapping)
        else {}
    )
    server_info = (
        network.get('xrpl_server_info_binding')
        if isinstance(network.get('xrpl_server_info_binding'), Mapping)
        else {}
    )

    device_summary = {
        'record': _report_record(
            device_report_path,
            expected_task_id='PORTAL-CXTP-121',
            expected_schema='xaman-testnet-device-trial/v1',
        ),
        'run_id': device.get('run_id'),
        'overall_status': device.get('overall_status'),
        'security_decision': device.get('security_decision'),
        'xaman_commit': device.get('xaman_commit'),
        'trial_scope': {
            'network': trial_scope.get('network'),
            'network_id': trial_scope.get('network_id'),
            'production_usable': trial_scope.get('production_usable'),
            'device_trial_label': trial_scope.get('device_trial_label'),
            'full_firebase_disabled_label_blocked': trial_scope.get('full_firebase_disabled_label_blocked'),
        },
        'verifier_apk': _redact_local_paths(verifier.get('apk')) if isinstance(verifier.get('apk'), Mapping) else None,
        'expected_apk_sha256': verifier.get('expected_apk_sha256'),
        'digest_matches_telemetry_report': verifier.get('digest_matches_telemetry_report'),
        'emulator_profile': {
            'present': emulator.get('present'),
            'profile_name': emulator.get('profile_name'),
            'path_label': _path_label(emulator.get('path') or emulator.get('profile_name') or 'unavailable'),
            'selected_file_records': _redact_local_paths(emulator.get('selected_file_records') or {}),
        },
        'fresh_account_boundary': _fresh_account_boundary_summary(fresh_account),
    }
    network_summary = {
        'record': _report_record(
            network_report_path,
            expected_task_id='PORTAL-CXTP-125',
            expected_schema='xaman-testnet-network-selection/v1',
        ),
        'run_id': network.get('run_id'),
        'overall_status': network.get('overall_status'),
        'security_decision': network.get('security_decision'),
        'xaman_commit': network.get('xaman_commit'),
        'build_provenance_sha256': network.get('build_provenance_sha256'),
        'selection': network.get('selection') if isinstance(network.get('selection'), Mapping) else {},
        'endpoint_allow_list_decision': {
            'allowed': endpoint_decision.get('allowed'),
            'matched_endpoint_key': endpoint_decision.get('matched_endpoint_key'),
            'matched_endpoint_sha256': endpoint_decision.get('matched_endpoint_sha256'),
            'allow_list_version': endpoint_decision.get('allow_list_version'),
            'allowed_endpoint_count': endpoint_decision.get('allowed_endpoint_count'),
        },
        'xrpl_server_info_binding': {
            'request_category': server_info.get('request_category'),
            'request_sha256': server_info.get('request_sha256'),
            'response_sha256': server_info.get('response_sha256'),
            'network_id': server_info.get('network_id'),
            'network_id_verified': server_info.get('network_id_verified'),
            'raw_request_body_recorded': server_info.get('raw_request_body_recorded'),
            'raw_response_recorded': server_info.get('raw_response_recorded'),
        },
        'fresh_account_boundary': _fresh_account_boundary_summary(
            network.get('fresh_account_boundary') if isinstance(network.get('fresh_account_boundary'), Mapping) else {}
        ),
    }
    native_summary = {
        'record': _report_record(
            native_firebase_report_path,
            expected_task_id='PORTAL-CXTP-126',
            expected_schema='xaman-native-firebase-boundary/v1',
        ),
        'run_id': native.get('run_id'),
        'overall_status': native.get('overall_status'),
        'security_decision': native.get('security_decision'),
        'xaman_commit': native.get('xaman_commit'),
        'native_firebase_fully_disabled': native.get('native_firebase_fully_disabled'),
        'native_firebase_evidence_present': native.get('native_firebase_evidence_present'),
        'native_packaging_present': native.get('native_packaging_present'),
        'device_trial_label_allowed': native.get('device_trial_label_allowed'),
        'blocker_codes': [
            blocker.get('code')
            for blocker in native.get('blockers', [])
            if isinstance(blocker, Mapping) and isinstance(blocker.get('code'), str)
        ],
    }
    return device_summary, network_summary, native_summary


def _load_lifecycle_evidence(path: Path) -> tuple[dict[str, Any], bytes]:
    evidence, raw = _load_json_bytes(path)
    _assert_no_sensitive_material(evidence, context='transaction lifecycle evidence')
    return evidence, raw


def _normalize_event(event: Mapping[str, Any]) -> dict[str, Any]:
    unknown_keys = sorted(str(key) for key in event if key not in ALLOWED_LIFECYCLE_EVENT_KEYS)
    if unknown_keys:
        raise ValueError(f'lifecycle event contains unknown keys: {unknown_keys}')
    action = event.get('action')
    category = event.get('category')
    outcome = event.get('outcome')
    source_kind = event.get('source_kind')
    ordinal = event.get('ordinal')
    source_sha256 = event.get('source_sha256')
    redaction_sha256 = event.get('redaction_sha256')

    if action not in REQUIRED_ACTIONS:
        raise ValueError(f'lifecycle event action is not allowed: {action!r}')
    if category != ACTION_CATEGORIES[action]:
        raise ValueError(f'lifecycle event category for {action!r} must be {ACTION_CATEGORIES[action]!r}')
    if outcome not in ALLOWED_OUTCOMES:
        raise ValueError(f'lifecycle event outcome is not allowed: {outcome!r}')
    if outcome not in ACTION_ALLOWED_OUTCOMES[action]:
        raise ValueError(f'lifecycle event outcome {outcome!r} is not valid for action {action!r}')
    if source_kind not in ALLOWED_SOURCE_KINDS:
        raise ValueError(f'lifecycle event source_kind is not allowed: {source_kind!r}')
    if not isinstance(ordinal, int) or ordinal <= 0:
        raise ValueError('lifecycle event ordinal must be a positive integer')
    _validate_reviewed_digest(source_sha256, 'lifecycle event source_sha256')
    _validate_reviewed_digest(redaction_sha256, 'lifecycle event redaction_sha256')
    if event.get('raw_material_recorded') is not False:
        raise ValueError('lifecycle event raw_material_recorded must be false')
    return {
        'ordinal': ordinal,
        'action': action,
        'category': category,
        'outcome': outcome,
        'source_kind': source_kind,
        'source_sha256': source_sha256,
        'redaction_sha256': redaction_sha256,
        'raw_material_recorded': False,
    }


def _normalize_gap(gap: Mapping[str, Any]) -> dict[str, Any]:
    unknown_keys = sorted(str(key) for key in gap if key not in ALLOWED_COVERAGE_GAP_KEYS)
    if unknown_keys:
        raise ValueError(f'coverage gap contains unknown keys: {unknown_keys}')
    action = gap.get('action')
    reason_code = gap.get('reason_code')
    reviewer_note_sha256 = gap.get('reviewer_note_sha256')
    if action not in REQUIRED_ACTIONS:
        raise ValueError(f'coverage gap action is not allowed: {action!r}')
    if reason_code not in ALLOWED_GAP_REASONS:
        raise ValueError(f'coverage gap reason_code is not allowed: {reason_code!r}')
    _validate_reviewed_digest(reviewer_note_sha256, 'coverage gap reviewer_note_sha256')
    return {
        'action': action,
        'category': ACTION_CATEGORIES[action],
        'reason_code': reason_code,
        'reviewer_note_sha256': reviewer_note_sha256,
    }


def _fresh_account_boundary_summary(boundary: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: boundary[key]
        for key in (
            'fresh_account_created',
            'imported_account',
            'production_account',
            'account_material_recorded',
            'boundary',
        )
        if key in boundary
    }


def _validate_reviewed_digest(value: Any, field_name: str) -> None:
    if not isinstance(value, str) or SHA256_RE.fullmatch(value) is None:
        raise ValueError(f'{field_name} must be a lowercase SHA-256 digest')
    if PLACEHOLDER_SHA256_RE.fullmatch(value) is not None:
        raise ValueError(f'{field_name} must not be a placeholder digest')


def _dependency_digest_blocker(value: Any, missing_code: str, placeholder_code: str) -> dict[str, Any] | None:
    if not isinstance(value, str) or SHA256_RE.fullmatch(value) is None:
        return {'code': missing_code}
    if PLACEHOLDER_SHA256_RE.fullmatch(value) is not None:
        return {'code': placeholder_code}
    return None


def _lifecycle_assessment(evidence: Mapping[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    blockers: list[dict[str, Any]] = []
    unknown_top_level_keys = sorted(str(key) for key in evidence if key not in ALLOWED_LIFECYCLE_EVIDENCE_KEYS)
    if unknown_top_level_keys:
        blockers.append({'code': 'LIFECYCLE_EVIDENCE_UNKNOWN_FIELDS', 'fields': unknown_top_level_keys})
    if evidence.get('schema_version') != EVIDENCE_SCHEMA_VERSION:
        blockers.append({'code': 'LIFECYCLE_EVIDENCE_SCHEMA_MISMATCH'})
    if evidence.get('evidence_type') not in ALLOWED_EVIDENCE_TYPES:
        blockers.append({'code': 'LIFECYCLE_EVIDENCE_TYPE_INVALID'})
    reviewed_at = evidence.get('reviewed_at_utc')
    if reviewed_at is None:
        blockers.append({'code': 'LIFECYCLE_REVIEWED_AT_MISSING'})
    elif not isinstance(reviewed_at, str) or GENERATED_AT_UTC_RE.fullmatch(reviewed_at) is None:
        blockers.append({'code': 'LIFECYCLE_REVIEWED_AT_INVALID'})
    if evidence.get('fresh_emulator_profile') is not True:
        blockers.append({'code': 'FRESH_EMULATOR_PROFILE_NOT_ESTABLISHED'})
    if evidence.get('network_key') != 'TESTNET':
        blockers.append({'code': 'LIFECYCLE_NETWORK_NOT_TESTNET'})

    fresh_account = evidence.get('fresh_account_boundary')
    if not isinstance(fresh_account, Mapping):
        blockers.append({'code': 'FRESH_ACCOUNT_BOUNDARY_MISSING'})
        fresh_account = {}
    else:
        unknown_boundary_keys = sorted(str(key) for key in fresh_account if key not in ALLOWED_FRESH_ACCOUNT_BOUNDARY_KEYS)
        if unknown_boundary_keys:
            blockers.append({'code': 'FRESH_ACCOUNT_BOUNDARY_UNKNOWN_FIELDS', 'fields': unknown_boundary_keys})
        if fresh_account.get('fresh_account_created') is not True:
            blockers.append({'code': 'FRESH_TESTNET_ACCOUNT_CREATION_NOT_EVIDENCED'})
        if fresh_account.get('imported_account') is not False:
            blockers.append({'code': 'FRESH_ACCOUNT_IMPORTED_OR_REUSED'})
        if fresh_account.get('production_account') is not False:
            blockers.append({'code': 'PRODUCTION_ACCOUNT_BOUNDARY_VIOLATED'})
        if fresh_account.get('account_material_recorded') is not False:
            blockers.append({'code': 'ACCOUNT_MATERIAL_RECORDED'})

    raw_events = evidence.get('lifecycle_events')
    normalized_events: list[dict[str, Any]] = []
    if not isinstance(raw_events, list):
        blockers.append({'code': 'LIFECYCLE_EVENTS_MISSING'})
    else:
        seen_ordinals: set[int] = set()
        seen_actions: set[str] = set()
        for raw_event in raw_events:
            if not isinstance(raw_event, Mapping):
                blockers.append({'code': 'LIFECYCLE_EVENT_INVALID'})
                continue
            try:
                event = _normalize_event(raw_event)
            except ValueError as exc:
                blockers.append({'code': 'LIFECYCLE_EVENT_INVALID', 'reason': str(exc)})
                continue
            if event['ordinal'] in seen_ordinals:
                blockers.append({'code': 'LIFECYCLE_EVENT_ORDINAL_DUPLICATE'})
            seen_ordinals.add(event['ordinal'])
            if event['action'] in seen_actions:
                blockers.append({'code': 'LIFECYCLE_ACTION_DUPLICATE', 'action': event['action']})
            seen_actions.add(event['action'])
            normalized_events.append(event)
        normalized_events.sort(key=lambda item: item['ordinal'])
        expected_ordinals = list(range(1, len(normalized_events) + 1))
        observed_ordinals = [event['ordinal'] for event in normalized_events]
        if observed_ordinals != expected_ordinals:
            blockers.append(
                {
                    'code': 'LIFECYCLE_EVENT_ORDINAL_SEQUENCE_INVALID',
                    'expected_ordinals': expected_ordinals,
                    'observed_ordinals': observed_ordinals,
                }
            )

    raw_gaps = evidence.get('coverage_gaps', [])
    normalized_gaps: list[dict[str, Any]] = []
    if not isinstance(raw_gaps, list):
        blockers.append({'code': 'COVERAGE_GAPS_INVALID'})
    else:
        seen_gap_actions: set[str] = set()
        for raw_gap in raw_gaps:
            if not isinstance(raw_gap, Mapping):
                blockers.append({'code': 'COVERAGE_GAP_INVALID'})
                continue
            try:
                gap = _normalize_gap(raw_gap)
            except ValueError as exc:
                blockers.append({'code': 'COVERAGE_GAP_INVALID', 'reason': str(exc)})
                continue
            if gap['action'] in seen_gap_actions:
                blockers.append({'code': 'COVERAGE_GAP_DUPLICATE', 'action': gap['action']})
            seen_gap_actions.add(gap['action'])
            normalized_gaps.append(gap)
        normalized_gaps.sort(key=lambda item: REQUIRED_ACTIONS.index(item['action']))

    observed_actions = {event['action'] for event in normalized_events}
    gap_actions = {gap['action'] for gap in normalized_gaps}
    missing_actions = sorted(set(REQUIRED_ACTIONS) - observed_actions - gap_actions, key=REQUIRED_ACTIONS.index)
    if missing_actions:
        blockers.append({'code': 'REQUIRED_LIFECYCLE_ACTION_UNACCOUNTED_FOR', 'actions': missing_actions})
    overlap_actions = sorted(observed_actions & gap_actions, key=REQUIRED_ACTIONS.index)
    if overlap_actions:
        blockers.append({'code': 'LIFECYCLE_ACTION_BOTH_OBSERVED_AND_GAP', 'actions': overlap_actions})

    action_coverage = []
    for action in REQUIRED_ACTIONS:
        event = next((item for item in normalized_events if item['action'] == action), None)
        gap = next((item for item in normalized_gaps if item['action'] == action), None)
        action_coverage.append(
            {
                'action': action,
                'category': ACTION_CATEGORIES[action],
                'status': 'observed' if event is not None else 'not_observed',
                'outcome': event.get('outcome') if event is not None else None,
                'source_kind': event.get('source_kind') if event is not None else None,
                'source_sha256': event.get('source_sha256') if event is not None else None,
                'redaction_sha256': event.get('redaction_sha256') if event is not None else None,
                'coverage_gap': gap if gap is not None else None,
            }
        )

    assessment = {
        'evidence_type': evidence.get('evidence_type'),
        'reviewed_at_utc': reviewed_at,
        'fresh_emulator_profile': evidence.get('fresh_emulator_profile') is True,
        'network_key': evidence.get('network_key'),
        'fresh_account_boundary': {
            'fresh_account_created': fresh_account.get('fresh_account_created'),
            'imported_account': fresh_account.get('imported_account'),
            'production_account': fresh_account.get('production_account'),
            'account_material_recorded': fresh_account.get('account_material_recorded'),
            'boundary': 'testnet_only_no_imported_or_persisted_account_material',
        },
        'required_actions': list(REQUIRED_ACTIONS),
        'observed_action_count': len(observed_actions),
        'coverage_gap_count': len(gap_actions),
        'categorical_events': normalized_events,
        'action_coverage': action_coverage,
        'coverage_gaps': normalized_gaps,
    }
    return assessment, _dedupe_blockers(blockers)


def _dedupe_blockers(blockers: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for blocker in blockers:
        fingerprint = json.dumps(blocker, sort_keys=True, separators=(',', ':'))
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        deduped.append(dict(blocker))
    return deduped


def _dependency_blockers(
    *,
    device: Mapping[str, Any],
    network: Mapping[str, Any],
    native: Mapping[str, Any],
    apk_record: Mapping[str, Any],
    xaman_commit: str,
) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    for name, summary in (
        ('TESTNET_DEVICE_TRIAL_REPORT', device),
        ('TESTNET_NETWORK_SELECTION_REPORT', network),
        ('NATIVE_FIREBASE_BOUNDARY_REPORT', native),
    ):
        record = summary.get('record') if isinstance(summary.get('record'), Mapping) else {}
        if record.get('present') is not True:
            blockers.append({'code': f'{name}_MISSING'})
            continue
        if record.get('schema_matches_expected') is not True:
            blockers.append({'code': f'{name}_SCHEMA_MISMATCH'})
        if record.get('task_matches_expected') is not True:
            blockers.append({'code': f'{name}_TASK_MISMATCH'})
        artifact_cid = record.get('artifact_cid')
        if not isinstance(artifact_cid, str) or SHA256_CID_RE.fullmatch(artifact_cid) is None:
            blockers.append({'code': f'{name}_ARTIFACT_CID_INVALID'})
        if record.get('artifact_cid_valid') is not True:
            blockers.append({'code': f'{name}_ARTIFACT_CID_MISMATCH'})

    apk_sha256 = None
    verifier_apk = device.get('verifier_apk') if isinstance(device.get('verifier_apk'), Mapping) else {}
    if isinstance(verifier_apk.get('sha256'), str) and SHA256_RE.fullmatch(verifier_apk['sha256']):
        apk_sha256 = verifier_apk['sha256']
    if apk_record.get('present') is not True:
        blockers.append({'code': 'VERIFIER_APK_MISSING'})
    if apk_record.get('present') is True and apk_sha256 is not None and apk_record.get('sha256') != apk_sha256:
        blockers.append({'code': 'VERIFIER_APK_DIGEST_MISMATCH'})
    if apk_sha256 is None:
        blockers.append({'code': 'DEVICE_VERIFIER_APK_DIGEST_MISSING'})
    else:
        blocker = _dependency_digest_blocker(
            apk_sha256,
            'DEVICE_VERIFIER_APK_DIGEST_MISSING',
            'DEVICE_VERIFIER_APK_DIGEST_PLACEHOLDER',
        )
        if blocker is not None:
            blockers.append(blocker)
    if isinstance(verifier_apk.get('sha256'), str) and SHA256_RE.fullmatch(verifier_apk['sha256']) is None:
        blockers.append({'code': 'DEVICE_VERIFIER_APK_DIGEST_INVALID'})
    if device.get('expected_apk_sha256') is not None and device.get('expected_apk_sha256') != apk_sha256:
        blockers.append({'code': 'DEVICE_EXPECTED_APK_DIGEST_MISMATCH'})
    if device.get('digest_matches_telemetry_report') is not True:
        blockers.append({'code': 'DEVICE_APK_DIGEST_NOT_BOUND_TO_TELEMETRY'})
    if network.get('build_provenance_sha256') != apk_sha256:
        blockers.append({'code': 'NETWORK_SELECTION_APK_DIGEST_MISMATCH'})

    if device.get('xaman_commit') != xaman_commit:
        blockers.append({'code': 'DEVICE_TRIAL_COMMIT_MISMATCH'})
    if network.get('xaman_commit') != xaman_commit:
        blockers.append({'code': 'NETWORK_SELECTION_COMMIT_MISMATCH'})
    if native.get('xaman_commit') != xaman_commit:
        blockers.append({'code': 'NATIVE_FIREBASE_COMMIT_MISMATCH'})
    if device.get('overall_status') != 'executed_with_boundaries':
        blockers.append({'code': 'DEVICE_TRIAL_NOT_EXECUTED'})
    if device.get('security_decision') != 'TESTNET_DEVICE_TRIAL_EXECUTED_JS_FIREBASE_STUBBED_NOT_PRODUCTION_EVIDENCE':
        blockers.append({'code': 'DEVICE_TRIAL_SECURITY_DECISION_INVALID'})
    trial_scope = device.get('trial_scope') if isinstance(device.get('trial_scope'), Mapping) else {}
    if trial_scope.get('network') != 'XRPL_TESTNET' or trial_scope.get('network_id') != 1:
        blockers.append({'code': 'DEVICE_TRIAL_NETWORK_NOT_TESTNET'})
    if trial_scope.get('production_usable') is not False:
        blockers.append({'code': 'DEVICE_TRIAL_PRODUCTION_BOUNDARY_NOT_FALSE'})
    emulator = device.get('emulator_profile') if isinstance(device.get('emulator_profile'), Mapping) else {}
    if emulator.get('present') is not True:
        blockers.append({'code': 'EMULATOR_PROFILE_MISSING'})
    selected_file_records = (
        emulator.get('selected_file_records') if isinstance(emulator.get('selected_file_records'), Mapping) else {}
    )
    if not selected_file_records:
        blockers.append({'code': 'EMULATOR_PROFILE_FILE_DIGESTS_MISSING'})
    for name, record in selected_file_records.items():
        if not isinstance(record, Mapping):
            blockers.append({'code': 'EMULATOR_PROFILE_FILE_RECORD_INVALID', 'file': str(name)})
            continue
        if record.get('present') is not True:
            blockers.append({'code': 'EMULATOR_PROFILE_FILE_MISSING', 'file': str(name)})
            continue
        blocker = _dependency_digest_blocker(
            record.get('sha256'),
            'EMULATOR_PROFILE_FILE_DIGEST_MISSING',
            'EMULATOR_PROFILE_FILE_DIGEST_PLACEHOLDER',
        )
        if blocker is not None:
            blockers.append({**blocker, 'file': str(name)})
    fresh = device.get('fresh_account_boundary') if isinstance(device.get('fresh_account_boundary'), Mapping) else {}
    if fresh.get('fresh_account_created') is not True:
        blockers.append({'code': 'DEVICE_FRESH_TESTNET_ACCOUNT_NOT_EVIDENCED'})
    if fresh.get('imported_account') is not False or fresh.get('production_account') is not False:
        blockers.append({'code': 'DEVICE_FRESH_ACCOUNT_BOUNDARY_VIOLATED'})
    if fresh.get('account_material_recorded') is not False:
        blockers.append({'code': 'DEVICE_ACCOUNT_MATERIAL_RECORDED'})

    if network.get('overall_status') != 'verified':
        blockers.append({'code': 'TESTNET_NETWORK_SELECTION_NOT_VERIFIED'})
    if network.get('security_decision') != 'TESTNET_NETWORK_SELECTION_VERIFIED_NOT_PRODUCTION_EVIDENCE':
        blockers.append({'code': 'TESTNET_NETWORK_SELECTION_SECURITY_DECISION_INVALID'})
    selection = network.get('selection') if isinstance(network.get('selection'), Mapping) else {}
    if selection.get('network_key') != 'TESTNET':
        blockers.append({'code': 'NETWORK_SELECTION_KEY_NOT_TESTNET'})
    event_categories = selection.get('event_categories')
    if not isinstance(event_categories, list):
        blockers.append({'code': 'NETWORK_SELECTION_EVENT_CATEGORIES_MISSING'})
        event_categories = []
    missing_event_categories = sorted(REQUIRED_NETWORK_SELECTION_EVENT_CATEGORIES - set(event_categories))
    if missing_event_categories:
        blockers.append(
            {
                'code': 'NETWORK_SELECTION_REQUIRED_EVENT_CATEGORIES_MISSING',
                'event_categories': missing_event_categories,
            }
        )
    endpoint_decision = (
        network.get('endpoint_allow_list_decision')
        if isinstance(network.get('endpoint_allow_list_decision'), Mapping)
        else {}
    )
    if endpoint_decision.get('allowed') is not True:
        blockers.append({'code': 'TESTNET_ENDPOINT_NOT_ALLOW_LISTED'})
    endpoint_key = endpoint_decision.get('matched_endpoint_key')
    if not isinstance(endpoint_key, str) or not IDENTIFIER_RE.fullmatch(endpoint_key):
        blockers.append({'code': 'TESTNET_ENDPOINT_KEY_MISSING'})
    allow_list_version = endpoint_decision.get('allow_list_version')
    if not isinstance(allow_list_version, str) or not IDENTIFIER_RE.fullmatch(allow_list_version):
        blockers.append({'code': 'TESTNET_ENDPOINT_ALLOW_LIST_VERSION_INVALID'})
    if not isinstance(endpoint_decision.get('allowed_endpoint_count'), int) or endpoint_decision.get(
        'allowed_endpoint_count'
    ) <= 0:
        blockers.append({'code': 'TESTNET_ENDPOINT_ALLOW_LIST_COUNT_INVALID'})
    blocker = _dependency_digest_blocker(
        endpoint_decision.get('matched_endpoint_sha256'),
        'TESTNET_ENDPOINT_DIGEST_MISSING',
        'TESTNET_ENDPOINT_DIGEST_PLACEHOLDER',
    )
    if blocker is not None:
        blockers.append(blocker)
    server_info = (
        network.get('xrpl_server_info_binding')
        if isinstance(network.get('xrpl_server_info_binding'), Mapping)
        else {}
    )
    if server_info.get('network_id') != 1 or server_info.get('network_id_verified') is not True:
        blockers.append({'code': 'SERVER_INFO_NETWORK_ID_NOT_TESTNET'})
    blocker = _dependency_digest_blocker(
        server_info.get('request_sha256'),
        'SERVER_INFO_REQUEST_DIGEST_MISSING',
        'SERVER_INFO_REQUEST_DIGEST_PLACEHOLDER',
    )
    if blocker is not None:
        blockers.append(blocker)
    blocker = _dependency_digest_blocker(
        server_info.get('response_sha256'),
        'SERVER_INFO_RESPONSE_DIGEST_MISSING',
        'SERVER_INFO_RESPONSE_DIGEST_PLACEHOLDER',
    )
    if blocker is not None:
        blockers.append(blocker)
    if server_info.get('raw_request_body_recorded') is not False or server_info.get('raw_response_recorded') is not False:
        blockers.append({'code': 'SERVER_INFO_RAW_BODY_RECORDED'})
    network_fresh = (
        network.get('fresh_account_boundary') if isinstance(network.get('fresh_account_boundary'), Mapping) else {}
    )
    if network_fresh.get('fresh_account_created') is not True:
        blockers.append({'code': 'NETWORK_FRESH_TESTNET_ACCOUNT_NOT_EVIDENCED'})
    if network_fresh.get('imported_account') is not False or network_fresh.get('production_account') is not False:
        blockers.append({'code': 'NETWORK_FRESH_ACCOUNT_BOUNDARY_VIOLATED'})
    if network_fresh.get('account_material_recorded') is not False:
        blockers.append({'code': 'NETWORK_ACCOUNT_MATERIAL_RECORDED'})

    if native.get('native_firebase_evidence_present') is not True:
        blockers.append({'code': 'NATIVE_FIREBASE_BOUNDARY_EVIDENCE_MISSING'})
    if native.get('overall_status') not in {'pass', 'blocked'}:
        blockers.append({'code': 'NATIVE_FIREBASE_BOUNDARY_STATUS_INVALID'})
    if native.get('security_decision') not in {
        'TESTNET_NATIVE_FIREBASE_REMOVAL_VERIFIED',
        'BLOCK_TESTNET_FULL_FIREBASE_DISABLED_LABEL_NATIVE_FIREBASE_EVIDENCE_INCOMPLETE',
        'BLOCK_TESTNET_FULL_FIREBASE_DISABLED_LABEL_NATIVE_FIREBASE_PACKAGED',
        'BLOCK_TESTNET_FULL_FIREBASE_DISABLED_LABEL_NATIVE_FIREBASE_STARTUP_INDICATORS',
        'BLOCK_TESTNET_FULL_FIREBASE_DISABLED_LABEL_NATIVE_FIREBASE_UNRESOLVED',
    }:
        blockers.append({'code': 'NATIVE_FIREBASE_SECURITY_DECISION_INVALID'})
    if native.get('native_firebase_fully_disabled') is True and native.get('overall_status') != 'pass':
        blockers.append({'code': 'NATIVE_FIREBASE_DISABLED_STATUS_CONFLICT'})
    if not isinstance(native.get('native_packaging_present'), bool):
        blockers.append({'code': 'NATIVE_FIREBASE_PACKAGING_STATUS_UNKNOWN'})
    if not isinstance(native.get('native_firebase_fully_disabled'), bool):
        blockers.append({'code': 'NATIVE_FIREBASE_DISABLED_STATUS_UNKNOWN'})
    if native.get('native_packaging_present') is True and native.get('native_firebase_fully_disabled') is True:
        blockers.append({'code': 'NATIVE_FIREBASE_PACKAGED_APK_MISLABELED_FULLY_DISABLED'})
    if native.get('native_packaging_present') is True and native.get('device_trial_label_allowed') != 'firebase_js_stubbed_only':
        blockers.append({'code': 'NATIVE_FIREBASE_PACKAGED_APK_MISLABELED_FULLY_DISABLED'})
    if (
        native.get('native_packaging_present') is True
        and native.get('security_decision') != 'BLOCK_TESTNET_FULL_FIREBASE_DISABLED_LABEL_NATIVE_FIREBASE_PACKAGED'
    ):
        blockers.append({'code': 'NATIVE_FIREBASE_PACKAGED_SECURITY_DECISION_MISMATCH'})
    if (
        native.get('native_packaging_present') is False
        and native.get('native_firebase_fully_disabled') is True
        and native.get('security_decision') != 'TESTNET_NATIVE_FIREBASE_REMOVAL_VERIFIED'
    ):
        blockers.append({'code': 'NATIVE_FIREBASE_REMOVAL_SECURITY_DECISION_MISMATCH'})
    if native.get('device_trial_label_allowed') not in {'firebase_js_stubbed_only', 'firebase_disabled'}:
        blockers.append({'code': 'NATIVE_FIREBASE_DEVICE_LABEL_NOT_ALLOWED'})
    return _dedupe_blockers(blockers)


def build_report(
    *,
    lifecycle_evidence_path: Path | str = DEFAULT_LIFECYCLE_EVIDENCE,
    device_report_path: Path | str = DEFAULT_DEVICE_REPORT,
    network_report_path: Path | str = DEFAULT_NETWORK_REPORT,
    native_firebase_report_path: Path | str = DEFAULT_NATIVE_FIREBASE_REPORT,
    apk_path: Path | str = DEFAULT_APK,
    run_id: str = 'xaman-testnet-transaction-lifecycle-20260710',
    xaman_commit: str = PINNED_XAMAN_COMMIT,
    generated_at_utc: str | None = None,
) -> dict[str, Any]:
    if not IDENTIFIER_RE.fullmatch(run_id):
        raise ValueError('run_id must be a short identifier containing only letters, digits, . _ : or -')
    if xaman_commit != PINNED_XAMAN_COMMIT:
        raise ValueError('xaman_commit must match the pinned Xaman corpus commit')
    if generated_at_utc is not None and not GENERATED_AT_UTC_RE.fullmatch(generated_at_utc):
        raise ValueError('generated_at_utc must use UTC second precision, e.g. 2026-07-10T00:00:00Z')

    lifecycle_evidence_path = Path(lifecycle_evidence_path).resolve()
    device_report_path = Path(device_report_path).resolve()
    network_report_path = Path(network_report_path).resolve()
    native_firebase_report_path = Path(native_firebase_report_path).resolve()
    apk_path = Path(apk_path).resolve()

    evidence, evidence_raw = _load_lifecycle_evidence(lifecycle_evidence_path)
    lifecycle, lifecycle_blockers = _lifecycle_assessment(evidence)
    device, network, native = _dependency_summaries(
        device_report_path=device_report_path,
        network_report_path=network_report_path,
        native_firebase_report_path=native_firebase_report_path,
    )
    apk_record = _file_record(apk_path) or {'present': False}
    dependency_blockers = _dependency_blockers(
        device=device,
        network=network,
        native=native,
        apk_record=apk_record,
        xaman_commit=xaman_commit,
    )
    blockers = _dedupe_blockers([*lifecycle_blockers, *dependency_blockers])

    verifier_apk = device.get('verifier_apk') if isinstance(device.get('verifier_apk'), Mapping) else {}
    apk_sha256 = apk_record.get('sha256') if apk_record.get('present') is True else verifier_apk.get('sha256')
    endpoint_decision = network.get('endpoint_allow_list_decision')
    endpoint_decision = endpoint_decision if isinstance(endpoint_decision, Mapping) else {}
    server_info = network.get('xrpl_server_info_binding')
    server_info = server_info if isinstance(server_info, Mapping) else {}
    coverage_gaps = lifecycle.get('coverage_gaps') if isinstance(lifecycle.get('coverage_gaps'), list) else []
    full_firebase_disabled_label_blocked = native.get('native_firebase_fully_disabled') is not True
    if blockers:
        overall_status = 'blocked'
        security_decision = 'BLOCK_TESTNET_TRANSACTION_LIFECYCLE_EVIDENCE_FAILURE'
    elif coverage_gaps:
        overall_status = 'executed_with_coverage_gaps'
        security_decision = 'TESTNET_TRANSACTION_LIFECYCLE_REVIEWED_WITH_COVERAGE_GAPS_NOT_PRODUCTION_EVIDENCE'
    else:
        overall_status = 'executed_complete'
        security_decision = 'TESTNET_TRANSACTION_LIFECYCLE_REVIEWED_NOT_PRODUCTION_EVIDENCE'

    report = {
        'schema_version': SCHEMA_VERSION,
        'task_id': TASK_ID,
        'generated_at_utc': generated_at_utc or _utc_now(),
        'run_id': run_id,
        'xaman_commit': xaman_commit,
        'overall_status': overall_status,
        'security_decision': security_decision,
        'production_release_blocked': True,
        'runtime_equivalence_status': 'not_proved',
        'trial_scope': {
            'network': 'XRPL_TESTNET',
            'network_id': 1,
            'production_usable': False,
            'real_assets_allowed': False,
            'account_policy': 'fresh_testnet_only_no_import_or_persistence_of_account_material',
            'verifier_apk_only': True,
            'native_firebase_packaged_apk_fully_disabled_label_blocked': full_firebase_disabled_label_blocked,
        },
        'evidence_inputs': {
            'lifecycle_evidence_sha256': _sha256_bytes(evidence_raw),
            'lifecycle_evidence_size_bytes': len(evidence_raw),
            'device_trial_report': device.get('record'),
            'network_selection_report': network.get('record'),
            'native_firebase_boundary_report': native.get('record'),
        },
        'verifier_artifact': {
            'apk': apk_record,
            'device_report_apk': verifier_apk,
            'apk_sha256': apk_sha256,
            'digest_matches_device_report': (
                apk_record.get('present') is True
                and isinstance(verifier_apk.get('sha256'), str)
                and apk_record.get('sha256') == verifier_apk.get('sha256')
            ),
        },
        'device_profile': {
            'isolated_android_emulator': device.get('emulator_profile'),
            'fresh_testnet_account_boundary': lifecycle.get('fresh_account_boundary'),
            'device_report_fresh_account_boundary': device.get('fresh_account_boundary'),
        },
        'testnet_network_binding': {
            'network_key': 'TESTNET',
            'endpoint_allow_list_decision': endpoint_decision,
            'xrpl_server_info_binding': server_info,
        },
        'transaction_lifecycle': lifecycle,
        'firebase_boundary': {
            'native_firebase_fully_disabled': native.get('native_firebase_fully_disabled'),
            'native_firebase_evidence_present': native.get('native_firebase_evidence_present'),
            'classification': (
                'firebase_js_stubbed_only'
                if full_firebase_disabled_label_blocked
                else 'firebase_disabled'
            ),
            'native_boundary': native,
        },
        'redaction_boundary': {
            'redaction_failure': False,
            'account_addresses_recorded': False,
            'seeds_recorded': False,
            'credentials_recorded': False,
            'raw_payloads_recorded': False,
            'transaction_blobs_recorded': False,
            'raw_request_bodies_recorded': False,
            'raw_xrpl_endpoint_recorded': False,
            'raw_server_info_response_recorded': False,
            'stored_values': [
                'required_action_names',
                'event_categories',
                'categorical_outcomes',
                'source_sha256',
                'redaction_sha256',
                'coverage_gap_reason_codes',
                'apk_sha256',
                'endpoint_key',
                'endpoint_sha256',
                'server_info_digest',
                'emulator_profile_file_sha256',
            ],
        },
        'blocking_gaps': blockers,
        'coverage_gaps': coverage_gaps,
        'residual_boundaries': [
            {
                'code': 'PRODUCTION_ACCEPTANCE_BLOCKED',
                'reason': 'This is public-Testnet verifier evidence only and cannot approve production release behavior.',
            },
            {
                'code': 'RUNTIME_EQUIVALENCE_NOT_PROVED',
                'reason': 'The verifier APK and emulator trial do not prove equivalence to a production runtime.',
            },
            {
                'code': 'FULL_FIREBASE_DISABLED_LABEL_BLOCKED',
                'active': full_firebase_disabled_label_blocked,
                'reason': (
                    'Native Firebase packaging remains present in the inspected APK.'
                    if full_firebase_disabled_label_blocked
                    else 'No native Firebase packaging boundary is active for this report.'
                ),
            },
            {
                'code': 'RAW_TRANSACTION_MATERIAL_EXCLUDED',
                'reason': 'The report cannot be used to reconstruct payload JSON, signatures, transaction blobs, or account identifiers.',
            },
        ],
    }
    _assert_report_redaction_boundary(report)
    report['artifact_cid'] = _artifact_cid(report)
    return report


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--lifecycle-evidence', type=Path, default=DEFAULT_LIFECYCLE_EVIDENCE)
    parser.add_argument('--device-report', type=Path, default=DEFAULT_DEVICE_REPORT)
    parser.add_argument('--network-report', type=Path, default=DEFAULT_NETWORK_REPORT)
    parser.add_argument('--native-firebase-report', type=Path, default=DEFAULT_NATIVE_FIREBASE_REPORT)
    parser.add_argument('--apk', type=Path, default=DEFAULT_APK)
    parser.add_argument('--run-id', default='xaman-testnet-transaction-lifecycle-20260710')
    parser.add_argument('--xaman-commit', default=PINNED_XAMAN_COMMIT)
    parser.add_argument('--generated-at-utc')
    parser.add_argument('--out', type=Path, default=DEFAULT_OUT)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    report = build_report(
        lifecycle_evidence_path=args.lifecycle_evidence,
        device_report_path=args.device_report,
        network_report_path=args.network_report,
        native_firebase_report_path=args.native_firebase_report,
        apk_path=args.apk,
        run_id=args.run_id,
        xaman_commit=args.xaman_commit,
        generated_at_utc=args.generated_at_utc,
    )
    _write_json(args.out, report)
    print(
        json.dumps(
            {
                'out': args.out.as_posix(),
                'overall_status': report['overall_status'],
                'security_decision': report['security_decision'],
                'artifact_cid': report['artifact_cid'],
                'coverage_gap_count': len(report['coverage_gaps']),
            },
            sort_keys=True,
        )
    )
    return 0 if report['overall_status'] in {'executed_complete', 'executed_with_coverage_gaps'} else 2


if __name__ == '__main__':
    raise SystemExit(main())
