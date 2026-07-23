#!/usr/bin/env python3
"""Capture redacted Xaman XRPL Testnet network-selection evidence.

This verifier accepts either reviewed local-state/UI evidence plus a supplied
XRPL ``server_info`` response, or it performs the ``server_info`` request
itself over an allow-listed public Testnet WebSocket endpoint. Reports contain
only event categories, the selected network key, endpoint allow-list decisions,
and request/response digests. Account material, payloads, transaction blobs, raw
request bodies, credentials, and raw XRPL responses are rejected or omitted.
"""

from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from typing import Any
from urllib.parse import urlparse


SCHEMA_VERSION = 'xaman-testnet-network-selection/v1'
SELECTION_EVIDENCE_SCHEMA_VERSION = 'xaman-testnet-selection-evidence/v1'
TASK_ID = 'PORTAL-CXTP-125'
PINNED_XAMAN_COMMIT = '942f43876265a7af44f233288ad2b1d00841d5fa'
DEFAULT_OUT = Path('security_ir_artifacts/corpora/xaman-app/runtime/testnet-network-selection-report.json')
DEFAULT_NETWORK_CONSTANTS = Path(
    '/home/barberb/.local/share/ipfs-datasets-xaman-testnet-verifier/xaman-app/src/common/constants/network.ts'
)
DEFAULT_BUILD_KIT_MANIFEST = Path(
    '/home/barberb/.local/share/ipfs-datasets-xaman-testnet-verifier/firebase-disabled-testnet-kit/testnet-build-manifest.json'
)
DEFAULT_TELEMETRY_REPORT = Path(
    'security_ir_artifacts/corpora/xaman-app/runtime/testnet-telemetry-report.json'
)
DEFAULT_RNN_COMPAT_OVERLAY = Path(
    '/home/barberb/.local/share/ipfs-datasets-xaman-testnet-verifier/firebase-disabled-testnet-kit/'
    'react-native-navigation-compat/ReactTypefaceUtils.java'
)
ALLOWED_TESTNET_ENDPOINTS = {
    'xrpl_labs_testnet': 'wss://testnet.xrpl-labs.com',
    'ripple_altnet_testnet': 'wss://s.altnet.rippletest.net:51233',
}
ALLOWED_TESTNET_ENDPOINT_BY_VALUE = {value: key for key, value in ALLOWED_TESTNET_ENDPOINTS.items()}
SERVER_INFO_REQUEST = {'id': 'server_info', 'command': 'server_info'}
SERVER_INFO_REQUEST_BYTES = json.dumps(SERVER_INFO_REQUEST, sort_keys=True, separators=(',', ':')).encode('utf-8')
ALLOWED_EVENT_CATEGORIES = frozenset(
    {
        'fresh_emulator_profile',
        'deterministic_testnet_local_state',
        'reviewed_ui_testnet_selection',
        'xaman_network_selected',
        'xrpl_server_info_observed',
        'fresh_testnet_account_boundary',
        'fresh_testnet_account_created',
    }
)
ALLOWED_EVIDENCE_TYPES = frozenset({'deterministic_local_state', 'reviewed_ui'})
IDENTIFIER_RE = re.compile(r'^[A-Za-z0-9_.:-]{1,160}$')
GENERATED_AT_UTC_RE = re.compile(r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$')
SHA256_RE = re.compile(r'^[a-f0-9]{64}$')
SHA256_CID_RE = re.compile(r'^sha256:[a-f0-9]{64}$')
XRPL_ADDRESS_RE = re.compile(r'\br[1-9A-HJ-NP-Za-km-z]{24,35}\b')
XRPL_XADDRESS_RE = re.compile(r'\b[XT][1-9A-HJ-NP-Za-km-z]{40,60}\b')
XRPL_SEED_RE = re.compile(r'\bs[1-9A-HJ-NP-Za-km-z]{25,35}\b')
LONG_HEX_RE = re.compile(r'\b[A-Fa-f0-9]{128,}\b')
RAW_WSS_ENDPOINT_RE = re.compile(r'\bwss://[A-Za-z0-9.:-]+(?:/[^\s"\'<>]*)?\b')
RAW_SERVER_INFO_REQUEST_RE = re.compile(
    r'(?=.*\\?["\']command\\?["\']\s*:\s*\\?["\']server_info\\?["\'])'
    r'(?=.*\\?["\']id\\?["\']\s*:\s*\\?["\']server_info\\?["\'])',
    re.DOTALL,
)
JWT_RE = re.compile(r'\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b')
BEARER_TOKEN_RE = re.compile(r'\bBearer\s+[A-Za-z0-9._~+/=-]{8,}\b', re.IGNORECASE)
SENSITIVE_KEY_TOKEN_SEQUENCES = (
    ('account', 'address'),
    ('api', 'key'),
    ('apikey',),
    ('auth',),
    ('authorization',),
    ('bearer',),
    ('body',),
    ('credential',),
    ('jwt',),
    ('mnemonic',),
    ('passcode',),
    ('password',),
    ('payload',),
    ('private',),
    ('raw', 'response'),
    ('raw', 'request'),
    ('request',),
    ('request', 'body'),
    ('request', 'payload'),
    ('response',),
    ('response', 'body'),
    ('seed',),
    ('secret',),
    ('session',),
    ('signature',),
    ('signed', 'transaction'),
    ('token',),
    ('transaction',),
    ('tx', 'blob'),
    ('tx', 'json'),
)
DIGEST_KEY_TOKENS = frozenset({'cid', 'digest', 'hash', 'sha256'})
KEY_TOKEN_CANONICAL_FORMS = {
    'addresses': 'address',
    'bodies': 'body',
    'blobs': 'blob',
    'credentials': 'credential',
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


class RedactionBoundaryError(ValueError):
    """Raised when an input attempts to cross the redaction boundary."""


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

    # Digests are allowed evidence; raw bodies and account/credential material are not.
    if tokens[-1] in DIGEST_KEY_TOKENS:
        digest_prefix = tokens[:-1]
        if digest_prefix and all(token in {'endpoint', 'request', 'response', 'server', 'info'} for token in digest_prefix):
            return None

    for sequence in SENSITIVE_KEY_TOKEN_SEQUENCES:
        if _contains_token_sequence(tokens, sequence):
            return '_'.join(sequence)
    return None


def _assert_no_sensitive_material(value: Any, *, context: str) -> None:
    if isinstance(value, Mapping):
        if value.get('command') == 'server_info':
            raise RedactionBoundaryError(f'{context} contains a raw server_info request body')
        for key, nested in value.items():
            if _sensitive_key_reason(key) is not None:
                raise RedactionBoundaryError(f'{context} contains forbidden key: {key}')
            _assert_no_sensitive_material(nested, context=context)
        return
    if isinstance(value, list):
        for item in value:
            _assert_no_sensitive_material(item, context=context)
        return
    if isinstance(value, str):
        if RAW_SERVER_INFO_REQUEST_RE.search(value):
            raise RedactionBoundaryError(f'{context} contains a raw server_info request body')
        if XRPL_ADDRESS_RE.search(value):
            raise RedactionBoundaryError(f'{context} contains an account address')
        if XRPL_XADDRESS_RE.search(value):
            raise RedactionBoundaryError(f'{context} contains an X-address')
        if XRPL_SEED_RE.search(value):
            raise RedactionBoundaryError(f'{context} contains a family seed')
        if LONG_HEX_RE.search(value):
            raise RedactionBoundaryError(f'{context} contains a transaction-sized hex blob')
        if JWT_RE.search(value):
            raise RedactionBoundaryError(f'{context} contains a credential token')
        if BEARER_TOKEN_RE.search(value):
            raise RedactionBoundaryError(f'{context} contains a bearer credential')


def _contains_raw_server_info_response(value: Any) -> bool:
    if isinstance(value, Mapping):
        result = value.get('result')
        info = result.get('info') if isinstance(result, Mapping) else None
        if (
            value.get('status') == 'success'
            and isinstance(result, Mapping)
            and isinstance(info, Mapping)
            and 'network_id' in info
            and (value.get('type') == 'response' or value.get('id') == 'server_info' or 'validated_ledger' in info)
        ):
            return True
        return any(_contains_raw_server_info_response(nested) for nested in value.values())
    if isinstance(value, list):
        return any(_contains_raw_server_info_response(item) for item in value)
    return False


def _assert_report_redaction_boundary(report: Mapping[str, Any]) -> None:
    if _contains_raw_server_info_response(report):
        raise RedactionBoundaryError('report contains a raw server_info response body')
    rendered = json.dumps(report, sort_keys=True, separators=(',', ':'))
    if RAW_WSS_ENDPOINT_RE.search(rendered):
        raise RedactionBoundaryError('report contains a raw WebSocket endpoint')
    if RAW_SERVER_INFO_REQUEST_RE.search(rendered):
        raise RedactionBoundaryError('report contains a raw server_info request body')
    if XRPL_ADDRESS_RE.search(rendered):
        raise RedactionBoundaryError('report contains an account address')
    if XRPL_XADDRESS_RE.search(rendered):
        raise RedactionBoundaryError('report contains an X-address')
    if XRPL_SEED_RE.search(rendered):
        raise RedactionBoundaryError('report contains a family seed')
    if LONG_HEX_RE.search(rendered):
        raise RedactionBoundaryError('report contains a transaction-sized hex blob')
    if JWT_RE.search(rendered):
        raise RedactionBoundaryError('report contains a credential token')
    if BEARER_TOKEN_RE.search(rendered):
        raise RedactionBoundaryError('report contains a bearer credential')


def _normalize_endpoint(endpoint: str) -> str:
    parsed = urlparse(endpoint)
    if parsed.scheme != 'wss' or not parsed.hostname:
        raise ValueError('endpoint must be a wss URL')
    if parsed.username or parsed.password or parsed.params or parsed.query or parsed.fragment:
        raise ValueError('endpoint must not include credentials, params, query, or fragment')
    if parsed.path:
        raise ValueError('endpoint must not include a path')
    host = parsed.hostname.lower()
    port = f':{parsed.port}' if parsed.port is not None else ''
    return f'wss://{host}{port}'


def _endpoint_decision(endpoint: str) -> dict[str, Any]:
    normalized = _normalize_endpoint(endpoint)
    matched_key = ALLOWED_TESTNET_ENDPOINT_BY_VALUE.get(normalized)
    return {
        'allowed': matched_key is not None,
        'matched_endpoint_key': matched_key,
        'matched_endpoint_sha256': _sha256_bytes(normalized.encode('utf-8')),
        'allow_list_version': 'xrpl-public-testnet-2026-07-10',
        'allowed_endpoint_count': len(ALLOWED_TESTNET_ENDPOINTS),
    }


def _extract_network_id(response: Mapping[str, Any]) -> int | None:
    candidates: list[Any] = [
        response.get('network_id'),
        response.get('info', {}).get('network_id') if isinstance(response.get('info'), Mapping) else None,
    ]
    result = response.get('result')
    if isinstance(result, Mapping):
        candidates.append(result.get('network_id'))
        info = result.get('info')
        if isinstance(info, Mapping):
            candidates.append(info.get('network_id'))
    for candidate in candidates:
        if isinstance(candidate, int):
            return candidate
        if isinstance(candidate, str) and candidate.isdigit():
            return int(candidate)
    return None


def _server_info_shape_blockers(response: Mapping[str, Any]) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    if response.get('status') != 'success':
        blockers.append({'code': 'XRPL_SERVER_INFO_STATUS_NOT_SUCCESS'})
    if 'type' in response and response.get('type') != 'response':
        blockers.append({'code': 'XRPL_SERVER_INFO_TYPE_NOT_RESPONSE'})
    if 'id' in response and response.get('id') != 'server_info':
        blockers.append({'code': 'XRPL_SERVER_INFO_ID_NOT_BOUND_TO_REQUEST'})
    result = response.get('result')
    info = response.get('info')
    if isinstance(result, Mapping):
        info = result.get('info')
    if not isinstance(result, Mapping) or not isinstance(info, Mapping):
        blockers.append({'code': 'XRPL_SERVER_INFO_SHAPE_INVALID'})
    return blockers


def _dedupe_blockers(blockers: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for blocker in blockers:
        code = blocker.get('code')
        fingerprint = json.dumps(blocker, sort_keys=True, separators=(',', ':'))
        key = str(code) if isinstance(code, str) and set(blocker) == {'code'} else fingerprint
        if key in seen:
            continue
        seen.add(key)
        deduped.append(dict(blocker))
    return deduped


def _load_selection_evidence(path: Path) -> tuple[dict[str, Any], bytes]:
    evidence, raw = _load_json_bytes(path)
    _assert_no_sensitive_material(evidence, context='selection evidence')
    if evidence.get('schema_version') != SELECTION_EVIDENCE_SCHEMA_VERSION:
        raise ValueError('selection evidence schema_version is invalid')
    return evidence, raw


def _selection_blockers(evidence: Mapping[str, Any]) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    evidence_type = evidence.get('evidence_type')
    if evidence_type not in ALLOWED_EVIDENCE_TYPES:
        blockers.append({'code': 'NETWORK_SELECTION_EVIDENCE_TYPE_INVALID'})
    if evidence.get('fresh_emulator_profile') is not True:
        blockers.append({'code': 'FRESH_EMULATOR_PROFILE_NOT_ESTABLISHED'})
    if evidence.get('network_key') != 'TESTNET':
        blockers.append({'code': 'XAMAN_SELECTED_NETWORK_NOT_TESTNET'})
    categories = evidence.get('event_categories')
    if not isinstance(categories, list) or not categories or not all(isinstance(item, str) for item in categories):
        blockers.append({'code': 'EVENT_CATEGORIES_INVALID'})
    else:
        unknown = sorted(set(categories) - ALLOWED_EVENT_CATEGORIES)
        if unknown:
            blockers.append({'code': 'EVENT_CATEGORIES_NOT_ALLOWED', 'count': len(unknown)})
        missing = sorted(
            {
                'fresh_emulator_profile',
                'fresh_testnet_account_boundary',
                'xaman_network_selected',
                'xrpl_server_info_observed',
            }
            - set(categories)
        )
        if missing:
            blockers.append({'code': 'REQUIRED_EVENT_CATEGORIES_MISSING', 'count': len(missing)})
        if evidence_type == 'deterministic_local_state' and 'deterministic_testnet_local_state' not in categories:
            blockers.append({'code': 'DETERMINISTIC_TESTNET_LOCAL_STATE_EVENT_MISSING'})
        if evidence_type == 'reviewed_ui' and 'reviewed_ui_testnet_selection' not in categories:
            blockers.append({'code': 'REVIEWED_UI_TESTNET_SELECTION_EVENT_MISSING'})
    fresh_account = evidence.get('fresh_account')
    if not isinstance(fresh_account, Mapping):
        blockers.append({'code': 'FRESH_ACCOUNT_BOUNDARY_MISSING'})
    else:
        if fresh_account.get('imported_account') is not False:
            blockers.append({'code': 'FRESH_ACCOUNT_IMPORTED_OR_REUSED'})
        if fresh_account.get('production_account') is not False:
            blockers.append({'code': 'PRODUCTION_ACCOUNT_BOUNDARY_NOT_ESTABLISHED'})
        if fresh_account.get('account_material_recorded') is not False:
            blockers.append({'code': 'ACCOUNT_MATERIAL_REDACTION_NOT_ESTABLISHED'})
        if not isinstance(fresh_account.get('created'), bool):
            blockers.append({'code': 'FRESH_ACCOUNT_CREATED_FLAG_INVALID'})
        elif isinstance(categories, list):
            created_category_present = 'fresh_testnet_account_created' in categories
            if fresh_account.get('created') is True and not created_category_present:
                blockers.append({'code': 'FRESH_ACCOUNT_CREATED_EVENT_MISSING'})
            if fresh_account.get('created') is False and created_category_present:
                blockers.append({'code': 'FRESH_ACCOUNT_CREATED_EVENT_INCONSISTENT'})
    return blockers


def _extract_object_around_index(source: str, index: int) -> str | None:
    candidates: list[tuple[int, int]] = []
    in_string: str | None = None
    escaped = False
    depth = 0
    stack: list[int] = []
    for position, character in enumerate(source):
        if in_string is not None:
            if escaped:
                escaped = False
            elif character == '\\':
                escaped = True
            elif character == in_string:
                in_string = None
            continue
        if character in {"'", '"', '`'}:
            in_string = character
        elif character == '{':
            stack.append(position)
            depth += 1
        elif character == '}':
            if not stack:
                return None
            start = stack.pop()
            depth -= 1
            if start <= index <= position:
                candidates.append((start, position))
    if depth != 0 or not candidates:
        return None
    start, end = min(candidates, key=lambda item: item[1] - item[0])
    return source[start : end + 1]


def _network_constants_assessment(path: Path | None) -> dict[str, Any]:
    if path is None or not path.is_file():
        return {'status': 'missing', 'blocker': 'XAMAN_NETWORK_CONSTANTS_NOT_SUPPLIED'}
    source = path.read_text(encoding='utf-8', errors='replace')
    marker_match = re.search(r'\bkey\s*:\s*([\'"])TESTNET\1', source)
    if marker_match is None:
        return {
            'status': 'blocked',
            'source_sha256': _sha256_bytes(source.encode('utf-8', errors='replace')),
            'blocker': 'XAMAN_TESTNET_NETWORK_DEFINITION_MISSING',
        }
    window = _extract_object_around_index(source, marker_match.start())
    if window is None:
        return {
            'status': 'blocked',
            'source_sha256': _sha256_file(path),
            'testnet_marker_present': True,
            'source_network_key': 'TESTNET',
            'source_network_id': None,
            'source_endpoint_count': 0,
            'nodes_match_allow_list': False,
            'blocker': 'XAMAN_TESTNET_NETWORK_DEFINITION_UNPARSEABLE',
        }
    network_id_match = re.search(r'\bnetworkId\s*:\s*([0-9]+)', window)
    nodes_match = re.search(r'\bnodes\s*:\s*\[([^\]]+)\]', window)
    nodes = re.findall(r"'([^']+)'|\"([^\"]+)\"", nodes_match.group(1) if nodes_match else '')
    node_values = [first or second for first, second in nodes]
    normalized_nodes: list[str] = []
    for node in node_values:
        try:
            normalized_nodes.append(_normalize_endpoint(node))
        except ValueError:
            normalized_nodes.append(node)
    expected = list(ALLOWED_TESTNET_ENDPOINTS.values())
    known_source_endpoint_keys = sorted(
        key for node in normalized_nodes if (key := ALLOWED_TESTNET_ENDPOINT_BY_VALUE.get(node)) is not None
    )
    source_endpoint_sha256 = sorted(_sha256_bytes(node.encode('utf-8')) for node in normalized_nodes)
    source_network_id = int(network_id_match.group(1)) if network_id_match else None
    nodes_match_allow_list = set(normalized_nodes) == set(expected) and len(normalized_nodes) == len(expected)
    return {
        'status': 'pass' if source_network_id == 1 and nodes_match_allow_list else 'blocked',
        'source_sha256': _sha256_file(path),
        'testnet_marker_present': True,
        'source_network_key': 'TESTNET',
        'source_network_id': source_network_id,
        'source_endpoint_count': len(normalized_nodes),
        'source_endpoint_keys': known_source_endpoint_keys,
        'source_endpoint_sha256': source_endpoint_sha256,
        'nodes_match_allow_list': nodes_match_allow_list,
        'blocker': None if source_network_id == 1 and nodes_match_allow_list else 'XAMAN_TESTNET_SOURCE_ALLOW_LIST_MISMATCH',
    }


def _build_manifest_record(path: Path | None) -> dict[str, Any] | None:
    if path is None or not path.is_file():
        return None
    manifest, _raw = _load_json_bytes(path)
    _assert_no_sensitive_material(manifest, context='build kit manifest')
    return {
        'schema_version': manifest.get('schema_version'),
        'task_id': manifest.get('task_id'),
        'artifact_cid': manifest.get('artifact_cid'),
        'sha256': _sha256_file(path),
    }


def _telemetry_report_record(path: Path | None) -> dict[str, Any] | None:
    if path is None or not path.is_file():
        return None
    report, _raw = _load_json_bytes(path)
    _assert_no_sensitive_material(report, context='telemetry report')
    return {
        'schema_version': report.get('schema_version'),
        'task_id': report.get('task_id'),
        'artifact_cid': report.get('artifact_cid'),
        'sha256': _sha256_file(path),
        'xaman_commit': report.get('xaman_commit'),
        'build_provenance_sha256': report.get('build_provenance_sha256'),
        'firebase_mode': report.get('firebase_mode'),
        'telemetry_sink': report.get('telemetry_sink'),
        'accepted_event_count': report.get('accepted_event_count'),
        'rejected_event_count': report.get('rejected_event_count'),
        'security_decision': report.get('security_decision'),
    }


def _rnn_compat_overlay_record(path: Path | None) -> dict[str, Any] | None:
    if path is None or not path.is_file():
        return None
    source = path.read_text(encoding='utf-8', errors='replace')
    return {
        'task_id': 'PORTAL-CXTP-123',
        'sha256': _sha256_file(path),
        'react_text_shadow_node_unset_references': source.count('ReactTextShadowNode.UNSET'),
        'package_local_unset_references': source.count('UNSET'),
        'reviewed_two_reference_replacement_present': (
            source.count('ReactTextShadowNode.UNSET') == 0 and source.count('UNSET') >= 3
        ),
    }


def _dependency_evidence_blockers(
    *,
    build_manifest: Mapping[str, Any] | None,
    telemetry_report: Mapping[str, Any] | None,
    rnn_compat_overlay: Mapping[str, Any] | None,
    xaman_commit: str,
    build_provenance_sha256: str | None,
) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    if build_manifest is not None:
        if build_manifest.get('schema_version') != 'xaman-firebase-disabled-testnet-build/v1':
            blockers.append({'code': 'TESTNET_BUILD_MANIFEST_SCHEMA_INVALID'})
        if build_manifest.get('task_id') != 'PORTAL-CXTP-119':
            blockers.append({'code': 'TESTNET_BUILD_MANIFEST_TASK_MISMATCH'})
        if not isinstance(build_manifest.get('artifact_cid'), str):
            blockers.append({'code': 'TESTNET_BUILD_MANIFEST_ARTIFACT_CID_MISSING'})
        elif SHA256_CID_RE.fullmatch(build_manifest['artifact_cid']) is None:
            blockers.append({'code': 'TESTNET_BUILD_MANIFEST_ARTIFACT_CID_INVALID'})
    if telemetry_report is not None:
        if telemetry_report.get('schema_version') != 'xaman-firebase-disabled-testnet-telemetry/v1':
            blockers.append({'code': 'TESTNET_TELEMETRY_REPORT_SCHEMA_INVALID'})
        if telemetry_report.get('task_id') != 'PORTAL-CXTP-120':
            blockers.append({'code': 'TESTNET_TELEMETRY_REPORT_TASK_MISMATCH'})
        if not isinstance(telemetry_report.get('artifact_cid'), str):
            blockers.append({'code': 'TESTNET_TELEMETRY_REPORT_ARTIFACT_CID_MISSING'})
        elif SHA256_CID_RE.fullmatch(telemetry_report['artifact_cid']) is None:
            blockers.append({'code': 'TESTNET_TELEMETRY_REPORT_ARTIFACT_CID_INVALID'})
        if telemetry_report.get('xaman_commit') != xaman_commit:
            blockers.append({'code': 'TESTNET_TELEMETRY_REPORT_COMMIT_MISMATCH'})
        if telemetry_report.get('firebase_mode') != 'disabled':
            blockers.append({'code': 'TESTNET_TELEMETRY_REPORT_FIREBASE_MODE_INVALID'})
        if telemetry_report.get('security_decision') != (
            'TESTNET_FIREBASE_DISABLED_TELEMETRY_CAPTURED_NOT_PRODUCTION_EVIDENCE'
        ):
            blockers.append({'code': 'TESTNET_TELEMETRY_REPORT_DECISION_INVALID'})
        if build_provenance_sha256 is not None and telemetry_report.get('build_provenance_sha256') not in {
            None,
            build_provenance_sha256,
        }:
            blockers.append({'code': 'TESTNET_TELEMETRY_REPORT_BUILD_DIGEST_MISMATCH'})
    if rnn_compat_overlay is not None:
        if rnn_compat_overlay.get('task_id') != 'PORTAL-CXTP-123':
            blockers.append({'code': 'RNN_COMPAT_OVERLAY_TASK_MISMATCH'})
        if rnn_compat_overlay.get('reviewed_two_reference_replacement_present') is not True:
            blockers.append({'code': 'RNN_COMPAT_OVERLAY_NOT_REVIEWED_REPLACEMENT'})
    return blockers


def _server_info_from_file(path: Path) -> tuple[dict[str, Any], bytes, str]:
    response, raw = _load_json_bytes(path)
    _assert_no_sensitive_material(response, context='server_info response')
    return response, raw, 'supplied_server_info_response'


def _capture_server_info(endpoint: str, *, timeout: float) -> tuple[dict[str, Any], bytes, str]:
    decision = _endpoint_decision(endpoint)
    if not decision['allowed']:
        raise ValueError('endpoint is not an allow-listed XRPL Testnet endpoint')
    try:
        import websocket  # type: ignore
    except ImportError as exc:  # pragma: no cover - dependent on verifier host
        raise RuntimeError('websocket-client is required for live server_info capture') from exc

    ws = websocket.create_connection(_normalize_endpoint(endpoint), timeout=timeout)
    try:
        ws.send(SERVER_INFO_REQUEST_BYTES.decode('ascii'))
        raw_text = ws.recv()
    finally:
        ws.close()
    raw = raw_text.encode('utf-8') if isinstance(raw_text, str) else bytes(raw_text)
    try:
        response = json.loads(raw.decode('utf-8'))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError('server_info response is not valid UTF-8 JSON') from exc
    if not isinstance(response, dict):
        raise ValueError('server_info response must be a JSON object')
    _assert_no_sensitive_material(response, context='server_info response')
    return response, raw, 'live_websocket_server_info'


def build_report(
    *,
    selection_evidence_path: Path | str,
    server_info_response_path: Path | str | None = None,
    live_endpoint: str | None = None,
    network_constants_path: Path | str | None = None,
    build_kit_manifest_path: Path | str | None = None,
    telemetry_report_path: Path | str | None = None,
    rnn_compat_overlay_path: Path | str | None = None,
    run_id: str = 'xaman-testnet-network-selection',
    xaman_commit: str = PINNED_XAMAN_COMMIT,
    build_provenance_sha256: str | None = None,
    generated_at_utc: str | None = None,
    live_timeout: float = 20.0,
) -> dict[str, Any]:
    if not IDENTIFIER_RE.fullmatch(run_id):
        raise ValueError('run_id must be a short identifier containing only letters, digits, . _ : or -')
    if xaman_commit != PINNED_XAMAN_COMMIT:
        raise ValueError('xaman_commit must match the pinned Xaman corpus commit')
    if build_provenance_sha256 is not None and not SHA256_RE.fullmatch(build_provenance_sha256):
        raise ValueError('build_provenance_sha256 must be a lowercase SHA-256 hex digest')
    if generated_at_utc is not None and not GENERATED_AT_UTC_RE.fullmatch(generated_at_utc):
        raise ValueError('generated_at_utc must use UTC second precision, e.g. 2026-07-10T00:00:00Z')
    if bool(server_info_response_path) == bool(live_endpoint):
        raise ValueError('supply exactly one of server_info_response_path or live_endpoint')

    selection_path = Path(selection_evidence_path).resolve()
    selection, selection_raw = _load_selection_evidence(selection_path)
    endpoint = selection.get('endpoint')
    if not isinstance(endpoint, str):
        raise ValueError('selection evidence endpoint must be a string')
    endpoint_decision = _endpoint_decision(endpoint)
    if live_endpoint is not None and _normalize_endpoint(live_endpoint) != _normalize_endpoint(endpoint):
        raise ValueError('live endpoint must match the selected endpoint evidence')

    if live_endpoint is not None:
        server_info, server_info_raw, response_source = _capture_server_info(live_endpoint, timeout=live_timeout)
    else:
        server_info, server_info_raw, response_source = _server_info_from_file(Path(server_info_response_path).resolve())

    source_assessment = _network_constants_assessment(
        Path(network_constants_path).resolve() if network_constants_path is not None else None
    )
    server_network_id = _extract_network_id(server_info)
    categories = sorted(set(selection.get('event_categories', []))) if isinstance(selection.get('event_categories'), list) else []
    fresh_account = selection.get('fresh_account') if isinstance(selection.get('fresh_account'), Mapping) else {}
    build_manifest_record = _build_manifest_record(
        Path(build_kit_manifest_path).resolve() if build_kit_manifest_path is not None else None
    )
    telemetry_report_record = _telemetry_report_record(
        Path(telemetry_report_path).resolve() if telemetry_report_path is not None else None
    )
    rnn_compat_overlay_record = _rnn_compat_overlay_record(
        Path(rnn_compat_overlay_path).resolve() if rnn_compat_overlay_path is not None else None
    )

    blockers = _selection_blockers(selection)
    blockers.extend(
        _dependency_evidence_blockers(
            build_manifest=build_manifest_record,
            telemetry_report=telemetry_report_record,
            rnn_compat_overlay=rnn_compat_overlay_record,
            xaman_commit=xaman_commit,
            build_provenance_sha256=build_provenance_sha256,
        )
    )
    if not endpoint_decision['allowed']:
        blockers.append({'code': 'ENDPOINT_NOT_ALLOW_LISTED'})
    selected_endpoint_in_source = bool(
        endpoint_decision['matched_endpoint_sha256'] in source_assessment.get('source_endpoint_sha256', [])
    )
    if endpoint_decision['allowed'] and source_assessment.get('status') == 'pass' and not selected_endpoint_in_source:
        blockers.append({'code': 'SELECTED_ENDPOINT_NOT_IN_XAMAN_TESTNET_SOURCE'})
    if source_assessment.get('status') != 'pass':
        blockers.append({'code': source_assessment.get('blocker') or 'XAMAN_TESTNET_SOURCE_NOT_PROVED'})
    blockers.extend(_server_info_shape_blockers(server_info))
    if server_network_id != 1:
        blockers.append({'code': 'XRPL_SERVER_INFO_NETWORK_ID_NOT_TESTNET'})
    if 'xrpl_server_info_observed' not in categories:
        blockers.append({'code': 'SERVER_INFO_EVENT_CATEGORY_MISSING'})
    blockers = _dedupe_blockers(blockers)

    overall_status = 'verified' if not blockers else 'blocked'
    residual_boundaries = [
        {
            'code': 'RUNTIME_EQUIVALENCE_NOT_PROVED',
            'reason': 'A Testnet network-selection proof is verifier-only evidence, not production or runtime-equivalence proof.',
        }
    ]
    report = {
        'schema_version': SCHEMA_VERSION,
        'task_id': TASK_ID,
        'generated_at_utc': generated_at_utc or _utc_now(),
        'run_id': run_id,
        'xaman_commit': xaman_commit,
        'build_provenance_sha256': build_provenance_sha256,
        'production_release_blocked': True,
        'runtime_equivalence_status': 'not_proved',
        'overall_status': overall_status,
        'security_decision': (
            'TESTNET_NETWORK_SELECTION_VERIFIED_NOT_PRODUCTION_EVIDENCE'
            if overall_status == 'verified'
            else 'BLOCK_TESTNET_NETWORK_SELECTION_EVIDENCE_FAILURE'
        ),
        'evidence_inputs': {
            'selection_evidence_sha256': _sha256_bytes(selection_raw),
            'selection_evidence_size_bytes': len(selection_raw),
            'server_info_request_sha256': _sha256_bytes(SERVER_INFO_REQUEST_BYTES),
            'server_info_response_sha256': _sha256_bytes(server_info_raw),
            'server_info_response_size_bytes': len(server_info_raw),
            'server_info_response_source': response_source,
            'build_kit_manifest': build_manifest_record,
            'testnet_telemetry_report': telemetry_report_record,
            'react_native_navigation_compat_overlay': rnn_compat_overlay_record,
        },
        'source_network_definition': source_assessment,
        'selection': {
            'evidence_type': selection.get('evidence_type'),
            'fresh_emulator_profile': selection.get('fresh_emulator_profile') is True,
            'network_key': selection.get('network_key'),
            'event_categories': categories,
        },
        'endpoint_allow_list_decision': endpoint_decision,
        'selected_endpoint_source_binding': {
            'selected_endpoint_key': endpoint_decision['matched_endpoint_key'],
            'selected_endpoint_sha256': endpoint_decision['matched_endpoint_sha256'],
            'source_nodes_include_selected_endpoint': selected_endpoint_in_source,
        },
        'xrpl_server_info_binding': {
            'request_category': 'xrpl_server_info',
            'request_sha256': _sha256_bytes(SERVER_INFO_REQUEST_BYTES),
            'network_id': server_network_id,
            'network_id_verified': server_network_id == 1,
            'response_sha256': _sha256_bytes(server_info_raw),
            'raw_response_recorded': False,
            'raw_request_body_recorded': False,
        },
        'fresh_account_boundary': {
            'fresh_account_created': fresh_account.get('created'),
            'imported_account': fresh_account.get('imported_account'),
            'production_account': fresh_account.get('production_account'),
            'account_material_recorded': fresh_account.get('account_material_recorded'),
            'boundary': 'testnet_only_no_imported_or_persisted_account_material',
        },
        'redaction_boundary': {
            'records_only_event_categories_network_key_endpoint_decision_and_digests': True,
            'account_addresses_recorded': False,
            'seeds_recorded': False,
            'credentials_recorded': False,
            'payloads_recorded': False,
            'transaction_blobs_recorded': False,
            'raw_request_bodies_recorded': False,
            'raw_server_info_response_recorded': False,
        },
        'blocking_gaps': blockers,
        'residual_boundaries': residual_boundaries,
    }
    _assert_report_redaction_boundary(report)
    report['artifact_cid'] = _artifact_cid(report)
    return report


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest='command', required=True)

    common_parent = argparse.ArgumentParser(add_help=False)
    common_parent.add_argument('--selection-evidence', type=Path, required=True)
    common_parent.add_argument('--network-constants', type=Path, default=DEFAULT_NETWORK_CONSTANTS)
    common_parent.add_argument('--build-kit-manifest', type=Path, default=DEFAULT_BUILD_KIT_MANIFEST)
    common_parent.add_argument('--telemetry-report', type=Path, default=DEFAULT_TELEMETRY_REPORT)
    common_parent.add_argument('--rnn-compat-overlay', type=Path, default=DEFAULT_RNN_COMPAT_OVERLAY)
    common_parent.add_argument('--run-id', default='xaman-testnet-network-selection')
    common_parent.add_argument('--xaman-commit', default=PINNED_XAMAN_COMMIT)
    common_parent.add_argument('--build-provenance-sha256')
    common_parent.add_argument('--generated-at-utc')
    common_parent.add_argument('--out', type=Path, default=DEFAULT_OUT)

    report = subparsers.add_parser('report', parents=[common_parent], help='write a report from reviewed JSON inputs')
    report.add_argument('--server-info-response', type=Path, required=True)

    capture = subparsers.add_parser(
        'capture',
        parents=[common_parent],
        help='perform an allow-listed live server_info request and write a redacted report',
    )
    capture.add_argument('--endpoint', required=True)
    capture.add_argument('--timeout', type=float, default=20.0)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    if args.command == 'capture':
        payload = build_report(
            selection_evidence_path=args.selection_evidence,
            live_endpoint=args.endpoint,
            network_constants_path=args.network_constants,
            build_kit_manifest_path=args.build_kit_manifest,
            telemetry_report_path=args.telemetry_report,
            rnn_compat_overlay_path=args.rnn_compat_overlay,
            run_id=args.run_id,
            xaman_commit=args.xaman_commit,
            build_provenance_sha256=args.build_provenance_sha256,
            generated_at_utc=args.generated_at_utc,
            live_timeout=args.timeout,
        )
    else:
        payload = build_report(
            selection_evidence_path=args.selection_evidence,
            server_info_response_path=args.server_info_response,
            network_constants_path=args.network_constants,
            build_kit_manifest_path=args.build_kit_manifest,
            telemetry_report_path=args.telemetry_report,
            rnn_compat_overlay_path=args.rnn_compat_overlay,
            run_id=args.run_id,
            xaman_commit=args.xaman_commit,
            build_provenance_sha256=args.build_provenance_sha256,
            generated_at_utc=args.generated_at_utc,
        )
    _write_json(args.out, payload)
    print(
        json.dumps(
            {
                'out': args.out.as_posix(),
                'overall_status': payload['overall_status'],
                'security_decision': payload['security_decision'],
                'artifact_cid': payload['artifact_cid'],
            },
            sort_keys=True,
        )
    )
    return 0 if payload['overall_status'] == 'verified' else 2


if __name__ == '__main__':
    raise SystemExit(main())
