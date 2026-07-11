"""Runtime conformance evidence binding for the frozen Xaman Testnet model."""

from __future__ import annotations

from collections import Counter
import json
import re
from pathlib import Path
from typing import Any, Mapping, Sequence

from ..ir.cid import calculate_artifact_cid


TASK_ID = 'PORTAL-CXTP-150'
GENERATED_AT_UTC = '2026-07-11T00:00:00Z'
REPORT_SCHEMA_VERSION = 'xaman-testnet-runtime-conformance-report/v1'
TRACE_MAP_SCHEMA_VERSION = 'xaman-testnet-runtime-conformance-trace-map/v1'

XAMAN_ROOT = 'security_ir_artifacts/corpora/xaman-app'
TESTNET_ROOT = f'{XAMAN_ROOT}/testnet'
RUNTIME_ROOT = f'{XAMAN_ROOT}/runtime'
MODEL_PATH = f'{TESTNET_ROOT}/security-model-ir.json'
MODEL_CID_PATH = f'{TESTNET_ROOT}/security-model-ir.cid'
CLAIM_TRACE_MAP_PATH = f'{TESTNET_ROOT}/claim-trace-map.json'
TRANSACTION_TRIAL_PATH = f'{RUNTIME_ROOT}/testnet-transaction-trial-report.json'
LIFECYCLE_EVIDENCE_PATH = f'{RUNTIME_ROOT}/testnet-transaction-lifecycle-evidence.json'
NETWORK_SELECTION_PATH = f'{RUNTIME_ROOT}/testnet-network-selection-report.json'
DEVICE_TRIAL_PATH = f'{RUNTIME_ROOT}/testnet-device-trial-report.json'
PUBLIC_BUILD_REPRODUCTION_PATH = f'{TESTNET_ROOT}/public-build-reproduction.json'
PUBLIC_BUILD_ENVIRONMENT_PATH = f'{TESTNET_ROOT}/public-build-environment.json'
SOLVER_PORTFOLIO_REPORT_PATH = f'{TESTNET_ROOT}/solver-portfolio-report.json'
FUZZ_COUNTEREXAMPLE_MANIFEST_PATH = f'{TESTNET_ROOT}/fuzz/counterexamples/manifest.json'

RUNTIME_CONFORMANCE_REPORT_PATH = f'{TESTNET_ROOT}/runtime-conformance-report.json'
RUNTIME_CONFORMANCE_TRACE_MAP_PATH = f'{TESTNET_ROOT}/runtime-conformance-trace-map.json'
RUNTIME_CONFORMANCE_DOC_PATH = 'docs/security_verification/xaman_testnet_runtime_conformance.md'

CLAIMS = {
    'network': 'xaman-testnet-claim:network-binding-is-testnet-only',
    'account': 'xaman-testnet-claim:account-provenance-is-fresh-testnet-only',
    'review_auth': 'xaman-testnet-claim:review-auth-sequence-observed',
    'signing': 'xaman-testnet-claim:signing-decision-is-observed-but-crypto-output-is-not-modeled',
    'submission': 'xaman-testnet-claim:submission-ui-attempt-and-result-are-observed',
    'payload': 'xaman-testnet-claim:payload-intake-is-categorical-only',
    'refusal': 'xaman-testnet-claim:refusal-path-is-not-modeled',
    'replay': 'xaman-testnet-claim:replay-controls-are-not-modeled',
    'expiry': 'xaman-testnet-claim:expiry-path-is-not-modeled',
    'cancellation': 'xaman-testnet-claim:cancellation-path-is-not-modeled',
    'broadcast': 'xaman-testnet-claim:broadcast-and-ledger-finality-are-not-modeled',
    'audit': 'xaman-testnet-claim:audit-redaction-boundary-is-preserved',
}

REQUIRED_RUNTIME_CATEGORIES = (
    'fresh_emulator',
    'testnet_only_network',
    'fresh_account',
    'review',
    'authentication',
    'signing_decision',
    'submit_attempt',
    'submit_result',
    'cancellation',
    'expiry',
    'replay',
    'reconnect',
    'network_change',
)

CATEGORY_SPECS: dict[str, dict[str, Any]] = {
    'fresh_emulator': {
        'display_name': 'fresh-emulator',
        'source_kind': 'device_profile',
        'source_action': None,
        'required_status': 'observed',
        'claim_keys': ('account', 'audit'),
        'assumption_ids': (
            'xaman-testnet-assumption:fresh-account-boundary-is-verifier-attested',
            'xaman-testnet-assumption:testnet-verifier-evidence-is-not-production-evidence',
        ),
        'model_fact_refs': ('metadata.model_scope', 'metadata.bound_artifacts.device_trial_report'),
    },
    'testnet_only_network': {
        'display_name': 'Testnet-only network',
        'source_kind': 'network_binding',
        'source_action': 'network_switch',
        'required_status': 'observed',
        'claim_keys': ('network', 'audit'),
        'assumption_ids': (
            'xaman-testnet-assumption:testnet-network-binding-is-verifier-only',
            'xaman-testnet-assumption:deployed-runtime-equivalence-not-proved',
        ),
        'model_fact_refs': ('metadata.model_scope.network_key', 'metadata.typed_model_facts.network-switch'),
    },
    'fresh_account': {
        'display_name': 'fresh-account',
        'source_kind': 'fresh_account_boundary',
        'source_action': None,
        'required_status': 'observed',
        'claim_keys': ('account', 'audit'),
        'assumption_ids': (
            'xaman-testnet-assumption:fresh-account-boundary-is-verifier-attested',
            'xaman-testnet-assumption:redacted-categorical-evidence-only',
        ),
        'model_fact_refs': ('metadata.fresh_account_boundary',),
    },
    'review': {
        'display_name': 'review',
        'source_kind': 'lifecycle_event',
        'source_action': 'review',
        'required_status': 'observed',
        'claim_keys': ('review_auth', 'audit'),
        'assumption_ids': (
            'xaman-testnet-assumption:reviewed-ui-event-is-operator-attested',
            'xaman-testnet-assumption:redacted-categorical-evidence-only',
        ),
        'model_fact_refs': ('metadata.typed_model_facts.review',),
    },
    'authentication': {
        'display_name': 'authentication',
        'source_kind': 'lifecycle_event',
        'source_action': 'auth_decision',
        'required_status': 'observed',
        'claim_keys': ('review_auth', 'audit'),
        'assumption_ids': (
            'xaman-testnet-assumption:reviewed-ui-event-is-operator-attested',
            'xaman-testnet-assumption:native-vault-and-biometric-security-not-proved',
        ),
        'model_fact_refs': ('metadata.typed_model_facts.auth-decision',),
    },
    'signing_decision': {
        'display_name': 'signing decision',
        'source_kind': 'lifecycle_event',
        'source_action': 'signing_decision',
        'required_status': 'observed_with_blocking_boundary',
        'claim_keys': ('signing', 'review_auth', 'audit'),
        'assumption_ids': (
            'xaman-testnet-assumption:native-vault-and-biometric-security-not-proved',
            'xaman-testnet-assumption:raw-signature-and-transaction-blob-excluded',
        ),
        'model_fact_refs': ('metadata.typed_model_facts.signing-decision',),
    },
    'submit_attempt': {
        'display_name': 'submit attempt',
        'source_kind': 'lifecycle_event',
        'source_action': 'submit_attempt',
        'required_status': 'observed_with_blocking_boundary',
        'claim_keys': ('submission', 'broadcast', 'audit'),
        'assumption_ids': (
            'xaman-testnet-assumption:xrpl-broadcast-finality-not-proved',
            'xaman-testnet-assumption:redacted-categorical-evidence-only',
        ),
        'model_fact_refs': ('metadata.typed_model_facts.submit-attempt',),
    },
    'submit_result': {
        'display_name': 'submit result',
        'source_kind': 'lifecycle_event',
        'source_action': 'submit_result',
        'required_status': 'observed_with_blocking_boundary',
        'claim_keys': ('submission', 'broadcast', 'audit'),
        'assumption_ids': (
            'xaman-testnet-assumption:xrpl-broadcast-finality-not-proved',
            'xaman-testnet-assumption:redacted-categorical-evidence-only',
        ),
        'model_fact_refs': ('metadata.typed_model_facts.submit-result',),
    },
    'cancellation': {
        'display_name': 'cancellation',
        'source_kind': 'coverage_gap',
        'source_action': 'cancel',
        'required_status': 'blocked_missing_path',
        'claim_keys': ('cancellation',),
        'assumption_ids': ('xaman-testnet-assumption:decline-cancel-expiry-not-exercised',),
        'model_fact_refs': ('metadata.not_modeled_records.cancellation-path',),
    },
    'expiry': {
        'display_name': 'expiry',
        'source_kind': 'coverage_gap',
        'source_action': 'expiry',
        'required_status': 'blocked_missing_path',
        'claim_keys': ('expiry',),
        'assumption_ids': (
            'xaman-testnet-assumption:decline-cancel-expiry-not-exercised',
            'xaman-testnet-assumption:backend-replay-single-use-not-exercised',
        ),
        'model_fact_refs': ('metadata.not_modeled_records.expiry-path',),
    },
    'replay': {
        'display_name': 'replay',
        'source_kind': 'not_modeled_record',
        'source_action': None,
        'required_status': 'blocked_missing_path',
        'claim_keys': ('replay',),
        'assumption_ids': ('xaman-testnet-assumption:backend-replay-single-use-not-exercised',),
        'model_fact_refs': ('metadata.not_modeled_records.replay-duplicate-submit-and-backend-single-use',),
    },
    'reconnect': {
        'display_name': 'reconnect',
        'source_kind': 'lifecycle_event',
        'source_action': 'reconnect',
        'required_status': 'observed',
        'claim_keys': ('network', 'audit'),
        'assumption_ids': (
            'xaman-testnet-assumption:deployed-runtime-equivalence-not-proved',
            'xaman-testnet-assumption:redacted-categorical-evidence-only',
        ),
        'model_fact_refs': ('metadata.typed_model_facts.reconnect',),
    },
    'network_change': {
        'display_name': 'network-change',
        'source_kind': 'lifecycle_event',
        'source_action': 'network_switch',
        'required_status': 'observed',
        'claim_keys': ('network', 'audit'),
        'assumption_ids': (
            'xaman-testnet-assumption:testnet-network-binding-is-verifier-only',
            'xaman-testnet-assumption:deployed-runtime-equivalence-not-proved',
        ),
        'model_fact_refs': ('metadata.typed_model_facts.network-switch',),
    },
}

SENSITIVE_VALUE_PATTERNS = (
    re.compile(r'\b(?:wss?|https?)://[^\s"\'<>]+', re.IGNORECASE),
    re.compile(r'\br[1-9A-HJ-NP-Za-km-z]{24,35}\b'),
    re.compile(r'\b[XT][1-9A-HJ-NP-Za-km-z]{40,60}\b'),
    re.compile(r'\bs[1-9A-HJ-NP-Za-km-z]{25,35}\b'),
    re.compile(r'\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b'),
    re.compile(r'\bBearer\s+[A-Za-z0-9._~+/=-]{8,}\b', re.IGNORECASE),
    re.compile(r'\b[A-Fa-f0-9]{128,}\b'),
    re.compile(r'["\'](?:TransactionType|SigningPubKey|TxnSignature|Account|Destination)["\']\s*:', re.IGNORECASE),
    re.compile(r'["\'](?:payload|tx[_-]?json|blob|signed[_-]?transaction|signed[_-]?blob)["\']\s*:', re.IGNORECASE),
)


class RuntimeConformanceError(ValueError):
    """Raised when runtime conformance evidence is inconsistent or unsafe."""


def _cid_without(payload: Mapping[str, Any], *keys: str) -> str:
    skipped = set(keys)
    return calculate_artifact_cid({key: value for key, value in payload.items() if key not in skipped})


def _sha256_file(repo_root: Path, rel_path: str) -> str | None:
    path = repo_root / rel_path
    if not path.is_file():
        return None
    import hashlib

    return 'sha256:' + hashlib.sha256(path.read_bytes()).hexdigest()


def _artifact_record(repo_root: Path, rel_path: str, payload: Mapping[str, Any] | None, *, kind: str) -> dict[str, Any]:
    return {
        'kind': kind,
        'path': rel_path,
        'present': payload is not None,
        'schema_version': payload.get('schema_version') if payload else None,
        'task_id': payload.get('task_id') if payload else None,
        'artifact_cid': payload.get('artifact_cid') if payload else None,
        'sha256': _sha256_file(repo_root, rel_path),
    }


def _claim_index(model_payload: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    return {
        str(claim['id']): claim
        for claim in model_payload.get('claims', [])
        if isinstance(claim, Mapping) and isinstance(claim.get('id'), str)
    }


def _event_index(transaction_trial: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    lifecycle = transaction_trial.get('transaction_lifecycle', {})
    return {
        str(event.get('action')): event
        for event in lifecycle.get('categorical_events', [])
        if isinstance(event, Mapping) and isinstance(event.get('action'), str)
    }


def _coverage_gap_index(transaction_trial: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    return {
        str(gap.get('action')): gap
        for gap in transaction_trial.get('coverage_gaps', [])
        if isinstance(gap, Mapping) and isinstance(gap.get('action'), str)
    }


def _not_modeled_index(model_payload: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    records = model_payload.get('metadata', {}).get('not_modeled_records', [])
    return {
        str(record.get('id')).removeprefix('xaman-testnet-not-modeled:'): record
        for record in records
        if isinstance(record, Mapping) and isinstance(record.get('id'), str)
    }


def _typed_fact_index(model_payload: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    facts = model_payload.get('metadata', {}).get('typed_model_facts', [])
    return {
        str(fact.get('event_id')).removeprefix('xaman-testnet-event:'): fact
        for fact in facts
        if isinstance(fact, Mapping) and isinstance(fact.get('event_id'), str)
    }


def _redaction_checks(transaction_trial: Mapping[str, Any]) -> dict[str, Any]:
    boundary = transaction_trial.get('redaction_boundary', {})
    boundary = boundary if isinstance(boundary, Mapping) else {}
    flags = {
        'seeds_retained': bool(boundary.get('seeds_recorded')),
        'addresses_retained': bool(boundary.get('account_addresses_recorded')),
        'payloads_retained': bool(boundary.get('raw_payloads_recorded')),
        'transaction_material_retained': bool(boundary.get('transaction_blobs_recorded')),
        'credentials_retained': bool(boundary.get('credentials_recorded')),
        'endpoint_values_retained': bool(boundary.get('raw_xrpl_endpoint_recorded')),
        'request_response_bodies_retained': bool(
            boundary.get('raw_request_bodies_recorded') or boundary.get('raw_server_info_response_recorded')
        ),
    }
    return {
        **flags,
        'all_sensitive_material_excluded': not any(flags.values()),
        'allowed_retained_material': [
            'category identifiers',
            'categorical outcomes',
            'review status',
            'source digests',
            'redaction digests',
            'artifact CIDs',
            'file digests',
            'endpoint keys and endpoint digests',
        ],
    }


def _category_observation(
    category_id: str,
    *,
    model_payload: Mapping[str, Any],
    transaction_trial: Mapping[str, Any],
) -> dict[str, Any]:
    spec = CATEGORY_SPECS[category_id]
    events = _event_index(transaction_trial)
    gaps = _coverage_gap_index(transaction_trial)
    not_modeled = _not_modeled_index(model_payload)
    typed_facts = _typed_fact_index(model_payload)
    action = spec['source_action']
    source: Mapping[str, Any] | None = None
    evidence_state = 'not_observed'

    if spec['source_kind'] == 'lifecycle_event' and action in events:
        source = events[action]
        evidence_state = 'observed'
    elif spec['source_kind'] == 'coverage_gap' and action in gaps:
        source = gaps[action]
        evidence_state = 'coverage_gap'
    elif spec['source_kind'] == 'not_modeled_record':
        source = not_modeled.get('replay-duplicate-submit-and-backend-single-use')
        evidence_state = 'not_modeled'
    elif spec['source_kind'] == 'device_profile':
        emulator = transaction_trial.get('device_profile', {}).get('isolated_android_emulator', {})
        source = emulator if isinstance(emulator, Mapping) else None
        evidence_state = 'observed' if source and source.get('present') is True else 'not_observed'
    elif spec['source_kind'] == 'fresh_account_boundary':
        fresh = transaction_trial.get('device_profile', {}).get('fresh_testnet_account_boundary', {})
        source = fresh if isinstance(fresh, Mapping) else None
        evidence_state = (
            'observed'
            if source
            and source.get('fresh_account_created') is True
            and source.get('imported_account') is False
            and source.get('production_account') is False
            and source.get('account_material_recorded') is False
            else 'not_observed'
        )
    elif spec['source_kind'] == 'network_binding':
        binding = transaction_trial.get('testnet_network_binding', {})
        source = binding if isinstance(binding, Mapping) else None
        server_info = source.get('xrpl_server_info_binding', {}) if source else {}
        evidence_state = (
            'observed'
            if source
            and source.get('network_key') == 'TESTNET'
            and isinstance(server_info, Mapping)
            and server_info.get('network_id') == 1
            and server_info.get('network_id_verified') is True
            else 'not_observed'
        )

    required_status = spec['required_status']
    if evidence_state == 'observed' and required_status == 'observed_with_blocking_boundary':
        conformance_status = 'observed_with_blocking_boundary'
    elif evidence_state == 'observed':
        conformance_status = 'observed'
    elif evidence_state in {'coverage_gap', 'not_modeled'}:
        conformance_status = 'blocked_missing_path'
    else:
        conformance_status = 'blocked_missing_evidence'

    claim_ids = [CLAIMS[key] for key in spec['claim_keys']]
    claim_records = _claim_index(model_payload)
    typed_fact = None
    if action:
        typed_fact = typed_facts.get(action.replace('_', '-'))
    if typed_fact is None and category_id == 'replay':
        typed_fact = not_modeled.get('replay-duplicate-submit-and-backend-single-use')

    observed_digest = None
    redaction_digest = None
    reason_code = None
    if source is not None:
        observed_digest = source.get('source_sha256') or source.get('redaction_digest')
        redaction_digest = source.get('redaction_sha256') or source.get('reviewer_note_sha256') or source.get('redaction_digest')
        reason_code = source.get('reason_code') or source.get('status')

    return {
        'category_id': category_id,
        'display_name': spec['display_name'],
        'model_cid_bound': True,
        'model_fact_refs': list(spec['model_fact_refs']),
        'claim_ids': claim_ids,
        'claim_statuses': {
            claim_id: claim_records.get(claim_id, {}).get('status')
            for claim_id in claim_ids
        },
        'assumption_ids': list(spec['assumption_ids']),
        'source_kind': spec['source_kind'],
        'source_action': action,
        'evidence_state': evidence_state,
        'conformance_status': conformance_status,
        'assurance_block': conformance_status in {'blocked_missing_path', 'blocked_missing_evidence'}
        or required_status == 'observed_with_blocking_boundary',
        'source_digest': observed_digest,
        'redaction_digest': redaction_digest,
        'reason_code': reason_code,
        'typed_model_fact_id': typed_fact.get('id') if isinstance(typed_fact, Mapping) else None,
        'raw_material_retained': False,
    }


def build_runtime_conformance_trace_map(
    *,
    model_payload: Mapping[str, Any],
    model_cid: str,
    claim_trace_map: Mapping[str, Any],
    transaction_trial: Mapping[str, Any],
    repo_root: Path,
) -> dict[str, Any]:
    """Build the redacted category-to-model trace map."""

    if claim_trace_map.get('model_cid') != model_cid:
        raise RuntimeConformanceError('claim trace map model CID does not match frozen model CID')
    categories = [
        _category_observation(
            category_id,
            model_payload=model_payload,
            transaction_trial=transaction_trial,
        )
        for category_id in REQUIRED_RUNTIME_CATEGORIES
    ]
    trace_map: dict[str, Any] = {
        'schema_version': TRACE_MAP_SCHEMA_VERSION,
        'task_id': TASK_ID,
        'generated_at_utc': GENERATED_AT_UTC,
        'model': {
            'path': MODEL_PATH,
            'cid_path': MODEL_CID_PATH,
            'cid': model_cid,
            'model_id': model_payload.get('model_id'),
            'schema_version': model_payload.get('schema_version'),
            'source_claim_trace_map_path': CLAIM_TRACE_MAP_PATH,
            'source_claim_trace_map_cid': claim_trace_map.get('artifact_cid'),
        },
        'source_evidence': {
            'transaction_trial': _artifact_record(repo_root, TRANSACTION_TRIAL_PATH, transaction_trial, kind='runtime_report'),
            'lifecycle_evidence_path': LIFECYCLE_EVIDENCE_PATH,
            'lifecycle_evidence_sha256': transaction_trial.get('evidence_inputs', {}).get('lifecycle_evidence_sha256'),
            'claim_trace_map': _artifact_record(repo_root, CLAIM_TRACE_MAP_PATH, claim_trace_map, kind='model_trace_map'),
        },
        'category_bindings': categories,
        'binding_policy': {
            'required_categories': list(REQUIRED_RUNTIME_CATEGORIES),
            'frozen_model_cid_required': True,
            'review_status_required': 'human_reviewed',
            'raw_sensitive_material_allowed': False,
            'missing_paths_remain_testnet_assurance_block': True,
        },
    }
    _assert_no_sensitive_material(trace_map, context='runtime conformance trace map')
    trace_map['artifact_cid'] = _cid_without(trace_map, 'artifact_cid')
    return trace_map


def build_runtime_conformance_report(
    *,
    model_payload: Mapping[str, Any],
    model_cid: str,
    claim_trace_map: Mapping[str, Any],
    transaction_trial: Mapping[str, Any],
    public_build_reproduction: Mapping[str, Any],
    public_build_environment: Mapping[str, Any],
    solver_portfolio_report: Mapping[str, Any],
    fuzz_counterexample_manifest: Mapping[str, Any],
    trace_map: Mapping[str, Any],
    repo_root: Path,
) -> dict[str, Any]:
    """Build the runtime conformance report for the Xaman Testnet lifecycle evidence."""

    _validate_inputs(
        model_payload=model_payload,
        model_cid=model_cid,
        claim_trace_map=claim_trace_map,
        transaction_trial=transaction_trial,
        public_build_reproduction=public_build_reproduction,
        public_build_environment=public_build_environment,
        solver_portfolio_report=solver_portfolio_report,
        trace_map=trace_map,
    )
    category_bindings = list(trace_map.get('category_bindings', []))
    status_counts = Counter(binding.get('conformance_status') for binding in category_bindings)
    assurance_blocks = _assurance_blocks(
        model_payload=model_payload,
        category_bindings=category_bindings,
        solver_portfolio_report=solver_portfolio_report,
        transaction_trial=transaction_trial,
        public_build_reproduction=public_build_reproduction,
    )
    redaction = _redaction_checks(transaction_trial)
    report: dict[str, Any] = {
        'schema_version': REPORT_SCHEMA_VERSION,
        'task_id': TASK_ID,
        'generated_at_utc': GENERATED_AT_UTC,
        'corpus': 'xaman-app',
        'scope': {
            'network': 'XRPL Testnet',
            'network_id': 1,
            'public_source_only': True,
            'fresh_emulator_required': True,
            'fresh_account_required': True,
            'production_security_result': False,
            'vendor_release_equivalence_claimed': False,
        },
        'model': {
            'path': MODEL_PATH,
            'cid_path': MODEL_CID_PATH,
            'cid': model_cid,
            'model_id': model_payload.get('model_id'),
            'schema_version': model_payload.get('schema_version'),
            'claim_count': len(model_payload.get('claims', [])),
        },
        'dependency_artifacts': [
            _artifact_record(repo_root, MODEL_PATH, model_payload, kind='frozen_model'),
            _artifact_record(repo_root, CLAIM_TRACE_MAP_PATH, claim_trace_map, kind='source_trace_map'),
            _artifact_record(repo_root, TRANSACTION_TRIAL_PATH, transaction_trial, kind='runtime_report'),
            _artifact_record(repo_root, PUBLIC_BUILD_REPRODUCTION_PATH, public_build_reproduction, kind='build_reproduction'),
            _artifact_record(repo_root, PUBLIC_BUILD_ENVIRONMENT_PATH, public_build_environment, kind='build_environment'),
            _artifact_record(repo_root, SOLVER_PORTFOLIO_REPORT_PATH, solver_portfolio_report, kind='solver_portfolio'),
            _artifact_record(repo_root, FUZZ_COUNTEREXAMPLE_MANIFEST_PATH, fuzz_counterexample_manifest, kind='fuzz_manifest'),
            _artifact_record(repo_root, RUNTIME_CONFORMANCE_TRACE_MAP_PATH, trace_map, kind='runtime_conformance_trace_map'),
        ],
        'runtime_categories': category_bindings,
        'summary': {
            'required_category_count': len(REQUIRED_RUNTIME_CATEGORIES),
            'observed_category_count': status_counts['observed'],
            'observed_with_blocking_boundary_count': status_counts['observed_with_blocking_boundary'],
            'blocked_missing_path_count': status_counts['blocked_missing_path'],
            'blocked_missing_evidence_count': status_counts['blocked_missing_evidence'],
            'assurance_block_count': len(assurance_blocks),
            'sensitive_material_excluded': redaction['all_sensitive_material_excluded'],
        },
        'redaction_boundary': redaction,
        'testnet_network_binding': {
            'network_key': transaction_trial.get('testnet_network_binding', {}).get('network_key'),
            'network_id': transaction_trial.get('testnet_network_binding', {})
            .get('xrpl_server_info_binding', {})
            .get('network_id'),
            'network_id_verified': transaction_trial.get('testnet_network_binding', {})
            .get('xrpl_server_info_binding', {})
            .get('network_id_verified'),
            'raw_endpoint_retained': False,
            'endpoint_digest_only': True,
        },
        'freshness': {
            'fresh_emulator_observed': _category_status(category_bindings, 'fresh_emulator') == 'observed',
            'fresh_account_observed': _category_status(category_bindings, 'fresh_account') == 'observed',
            'testnet_only_network_observed': _category_status(category_bindings, 'testnet_only_network') == 'observed',
        },
        'assurance_blocks': assurance_blocks,
        'overall_status': 'blocked_testnet_runtime_conformance',
        'security_decision': 'BLOCK_TESTNET_ASSURANCE_RUNTIME_CONFORMANCE_GAPS',
        'production_release_blocked': True,
        'verdict_policy': {
            'testnet_scope_assured_allowed': False,
            'blocked_until_missing_paths_are_evidenced': True,
            'raw_material_reintroduction_rejected': True,
            'production_or_vendor_release_decision': False,
        },
    }
    if not redaction['all_sensitive_material_excluded']:
        report['overall_status'] = 'rejected_redaction_failure'
        report['security_decision'] = 'REJECT_RUNTIME_CONFORMANCE_REDACTION_FAILURE'
    _assert_no_sensitive_material(report, context='runtime conformance report')
    report['artifact_cid'] = _cid_without(report, 'artifact_cid')
    return report


def _category_status(bindings: Sequence[Mapping[str, Any]], category_id: str) -> str | None:
    return next((str(binding.get('conformance_status')) for binding in bindings if binding.get('category_id') == category_id), None)


def _assurance_blocks(
    *,
    model_payload: Mapping[str, Any],
    category_bindings: Sequence[Mapping[str, Any]],
    solver_portfolio_report: Mapping[str, Any],
    transaction_trial: Mapping[str, Any],
    public_build_reproduction: Mapping[str, Any],
) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    for binding in category_bindings:
        if binding.get('conformance_status') in {'blocked_missing_path', 'blocked_missing_evidence'}:
            blocks.append(
                {
                    'code': f"RUNTIME_CATEGORY_{str(binding['category_id']).upper()}_BLOCKED",
                    'category_id': binding['category_id'],
                    'claim_ids': binding['claim_ids'],
                    'assumption_ids': binding['assumption_ids'],
                    'reason': 'Required Testnet lifecycle path is not evidenced as an observed runtime path.',
                }
            )
        elif binding.get('conformance_status') == 'observed_with_blocking_boundary':
            blocks.append(
                {
                    'code': f"RUNTIME_CATEGORY_{str(binding['category_id']).upper()}_BOUNDARY",
                    'category_id': binding['category_id'],
                    'claim_ids': binding['claim_ids'],
                    'assumption_ids': binding['assumption_ids'],
                    'reason': 'Observed categorical runtime evidence remains bounded by a NOT_MODELED cryptographic, backend, or ledger boundary.',
                }
            )
    for record in model_payload.get('metadata', {}).get('not_modeled_records', []):
        if isinstance(record, Mapping):
            blocks.append(
                {
                    'code': 'MODEL_NOT_MODELED_RECORD_ACTIVE',
                    'category': record.get('category'),
                    'claim_id': record.get('claim_id'),
                    'assumption_id': record.get('assumption_id'),
                    'reason': record.get('reason'),
                }
            )
    if solver_portfolio_report.get('overall_status') != 'secure':
        blocks.append(
            {
                'code': 'SOLVER_PORTFOLIO_NOT_SECURE',
                'source_status': solver_portfolio_report.get('overall_status'),
                'source_decision': solver_portfolio_report.get('security_decision'),
                'reason': 'Runtime conformance cannot override fail-closed solver portfolio counterevidence.',
            }
        )
    if transaction_trial.get('overall_status') != 'executed_complete':
        blocks.append(
            {
                'code': 'TRANSACTION_TRIAL_HAS_COVERAGE_GAPS',
                'source_status': transaction_trial.get('overall_status'),
                'reason': 'The reviewed transaction trial did not exercise every required lifecycle path.',
            }
        )
    if public_build_reproduction.get('scope', {}).get('vendor_release_equivalent') is not False:
        blocks.append(
            {
                'code': 'PUBLIC_BUILD_EQUIVALENCE_SCOPE_INVALID',
                'reason': 'Runtime conformance requires public build evidence to remain non-equivalent to vendor release.',
            }
        )
    else:
        blocks.append(
            {
                'code': 'PUBLIC_BUILD_NOT_VENDOR_RELEASE_EQUIVALENT',
                'reason': 'Public-source Testnet verifier evidence is intentionally not a production/vendor release decision.',
            }
        )
    return _dedupe(blocks)


def _dedupe(items: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    for item in items:
        fingerprint = json.dumps(item, sort_keys=True, separators=(',', ':'), ensure_ascii=True)
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        result.append(dict(item))
    return result


def _validate_inputs(
    *,
    model_payload: Mapping[str, Any],
    model_cid: str,
    claim_trace_map: Mapping[str, Any],
    transaction_trial: Mapping[str, Any],
    public_build_reproduction: Mapping[str, Any],
    public_build_environment: Mapping[str, Any],
    solver_portfolio_report: Mapping[str, Any],
    trace_map: Mapping[str, Any],
) -> None:
    if model_payload.get('model_id') != 'xaman-app-testnet-transaction-lifecycle-security-model-ir':
        raise RuntimeConformanceError('unexpected Xaman Testnet model id')
    if claim_trace_map.get('model_cid') != model_cid:
        raise RuntimeConformanceError('claim trace map is not bound to the frozen model CID')
    if solver_portfolio_report.get('model', {}).get('cid') != model_cid:
        raise RuntimeConformanceError('solver portfolio report is not bound to the frozen model CID')
    if trace_map.get('model', {}).get('cid') != model_cid:
        raise RuntimeConformanceError('runtime conformance trace map is not bound to the frozen model CID')
    if transaction_trial.get('trial_scope', {}).get('network') != 'XRPL_TESTNET':
        raise RuntimeConformanceError('transaction trial is not scoped to XRPL Testnet')
    if transaction_trial.get('trial_scope', {}).get('production_usable') is not False:
        raise RuntimeConformanceError('transaction trial production boundary is invalid')
    if public_build_reproduction.get('scope', {}).get('vendor_release_equivalent') is not False:
        raise RuntimeConformanceError('public build reproduction must not claim vendor release equivalence')
    if public_build_environment.get('scope', {}).get('vendor_release_equivalence_claimed') is not False:
        raise RuntimeConformanceError('public build environment must not claim vendor release equivalence')
    if set(REQUIRED_RUNTIME_CATEGORIES) != {binding.get('category_id') for binding in trace_map.get('category_bindings', [])}:
        raise RuntimeConformanceError('runtime conformance trace map does not cover every required category')


def validate_runtime_conformance_artifacts(
    *,
    report: Mapping[str, Any],
    trace_map: Mapping[str, Any],
    model_cid: str,
) -> None:
    """Validate generated runtime conformance artifacts."""

    if report.get('schema_version') != REPORT_SCHEMA_VERSION:
        raise RuntimeConformanceError('runtime conformance report schema mismatch')
    if trace_map.get('schema_version') != TRACE_MAP_SCHEMA_VERSION:
        raise RuntimeConformanceError('runtime conformance trace map schema mismatch')
    if report.get('task_id') != TASK_ID or trace_map.get('task_id') != TASK_ID:
        raise RuntimeConformanceError('runtime conformance task id mismatch')
    if report.get('model', {}).get('cid') != model_cid or trace_map.get('model', {}).get('cid') != model_cid:
        raise RuntimeConformanceError('runtime conformance artifacts are not bound to the frozen model CID')
    _assert_no_sensitive_material(report, context='runtime conformance report')
    _assert_no_sensitive_material(trace_map, context='runtime conformance trace map')
    category_ids = [binding.get('category_id') for binding in report.get('runtime_categories', [])]
    if tuple(category_ids) != REQUIRED_RUNTIME_CATEGORIES:
        raise RuntimeConformanceError('runtime conformance report category order or coverage mismatch')
    trace_category_ids = [binding.get('category_id') for binding in trace_map.get('category_bindings', [])]
    if tuple(trace_category_ids) != REQUIRED_RUNTIME_CATEGORIES:
        raise RuntimeConformanceError('runtime conformance trace map category order or coverage mismatch')
    blocked = [
        binding
        for binding in report.get('runtime_categories', [])
        if binding.get('conformance_status') in {'blocked_missing_path', 'blocked_missing_evidence'}
    ]
    if not blocked:
        raise RuntimeConformanceError('missing lifecycle paths must remain an explicit Testnet assurance block')
    if report.get('production_release_blocked') is not True:
        raise RuntimeConformanceError('runtime conformance report must block production release')
    if report.get('redaction_boundary', {}).get('all_sensitive_material_excluded') is not True:
        raise RuntimeConformanceError('runtime conformance report redaction boundary failed')
    if report.get('artifact_cid') != _cid_without(report, 'artifact_cid'):
        raise RuntimeConformanceError('runtime conformance report artifact CID mismatch')
    if trace_map.get('artifact_cid') != _cid_without(trace_map, 'artifact_cid'):
        raise RuntimeConformanceError('runtime conformance trace map artifact CID mismatch')


def render_runtime_conformance_markdown(report: Mapping[str, Any], trace_map: Mapping[str, Any]) -> str:
    """Render deterministic operator documentation for PORTAL-CXTP-150."""

    lines = [
        '# Xaman Testnet Runtime Conformance',
        '',
        f'Task: `{TASK_ID}`',
        '',
        'This document records the redacted XRPL Testnet lifecycle conformance check for the frozen Xaman public-source Testnet model. It is not a production or vendor-release security decision.',
        '',
        '## Artifacts',
        '',
        f'- Report: `{RUNTIME_CONFORMANCE_REPORT_PATH}`',
        f'- Trace map: `{RUNTIME_CONFORMANCE_TRACE_MAP_PATH}`',
        f'- Frozen model: `{MODEL_PATH}`',
        f'- Model CID: `{report["model"]["cid"]}`',
        f'- Source claim trace map: `{CLAIM_TRACE_MAP_PATH}`',
        f'- Transaction trial: `{TRANSACTION_TRIAL_PATH}`',
        '',
        '## Decision',
        '',
        f'- Overall status: `{report["overall_status"]}`',
        f'- Security decision: `{report["security_decision"]}`',
        f'- Production release blocked: `{str(report["production_release_blocked"]).lower()}`',
        f'- Assurance block count: `{report["summary"]["assurance_block_count"]}`',
        '',
        '## Runtime Categories',
        '',
    ]
    for binding in report.get('runtime_categories', []):
        lines.append(
            f'- `{binding["category_id"]}` ({binding["display_name"]}): '
            f'`{binding["conformance_status"]}`; claims `{", ".join(binding["claim_ids"])}`'
        )
    lines.extend(
        [
            '',
            '## Redaction Boundary',
            '',
            'The artifacts retain only categories, outcomes, source digests, redaction digests, artifact CIDs, endpoint keys, and endpoint digests. They do not retain seeds, addresses, payloads, transaction blobs, credentials, or raw endpoints.',
            '',
            '## Testnet Assurance Blocks',
            '',
        ]
    )
    for block in report.get('assurance_blocks', [])[:12]:
        lines.append(f'- `{block["code"]}`: {block["reason"]}')
    lines.extend(
        [
            '',
            '## Validation',
            '',
            '```bash',
            'PYTHONPATH=. /home/barberb/miniforge3/bin/python -m pytest tests/logic/security_models/crypto_exchange/test_xaman_testnet_runtime_conformance.py -q',
            f'PYTHONPATH=. /home/barberb/miniforge3/bin/python scripts/ops/security_verification/validate_xaman_testnet_runtime_conformance.py --out {RUNTIME_CONFORMANCE_REPORT_PATH}',
            '```',
            '',
        ]
    )
    _ = trace_map
    return '\n'.join(lines)


def _assert_no_sensitive_material(value: Any, *, context: str) -> None:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            _assert_no_sensitive_string(str(key), context=context)
            _assert_no_sensitive_material(nested, context=context)
    elif isinstance(value, list):
        for item in value:
            _assert_no_sensitive_material(item, context=context)
    elif isinstance(value, str):
        _assert_no_sensitive_string(value, context=context)


def _assert_no_sensitive_string(value: str, *, context: str) -> None:
    for pattern in SENSITIVE_VALUE_PATTERNS:
        if pattern.search(value):
            raise RuntimeConformanceError(f'{context} contains forbidden sensitive material')
