#!/usr/bin/env python3
"""Project reviewed Xaman Testnet lifecycle evidence into SecurityModelIR."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Any, Mapping


ROOT_DIR = Path(__file__).resolve().parents[3]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from ipfs_datasets_py.logic.security_models.crypto_exchange.ir.canonicalize import (  # noqa: E402
    canonicalize_ir,
)
from ipfs_datasets_py.logic.security_models.crypto_exchange.ir.schema import (  # noqa: E402
    validate_ir,
)


CORPUS_DIR = ROOT_DIR / 'security_ir_artifacts' / 'corpora' / 'xaman-app'
RUNTIME_DIR = CORPUS_DIR / 'runtime'
TESTNET_DIR = CORPUS_DIR / 'testnet'
MODEL_PATH = TESTNET_DIR / 'security-model-ir.json'
MODEL_CID_PATH = TESTNET_DIR / 'security-model-ir.cid'
TRACE_MAP_PATH = TESTNET_DIR / 'claim-trace-map.json'
ASSUMPTIONS_PATH = TESTNET_DIR / 'assumptions.json'

LIFECYCLE_EVIDENCE_PATH = RUNTIME_DIR / 'testnet-transaction-lifecycle-evidence.json'
TRIAL_REPORT_PATH = RUNTIME_DIR / 'testnet-transaction-trial-report.json'
NETWORK_REPORT_PATH = RUNTIME_DIR / 'testnet-network-selection-report.json'
DEVICE_REPORT_PATH = RUNTIME_DIR / 'testnet-device-trial-report.json'
NATIVE_FIREBASE_REPORT_PATH = RUNTIME_DIR / 'native-firebase-boundary-report.json'
SECURITY_CLAIMS_PATH = CORPUS_DIR / 'security-claims.json'

XAMAN_COMMIT = '942f43876265a7af44f233288ad2b1d00841d5fa'
GENERATED_AT_UTC = '2026-07-11T00:00:00Z'
REVIEWED_AT_UTC = '2026-07-10T23:00:00Z'
EVIDENCE_EXPIRES_AT = '2027-01-11T00:00:00Z'
SHA256_RE = re.compile(r'^[0-9a-f]{64}$')

OBSERVED_EVENT_LINES = {
    'payload_intake': (28, 37),
    'review': (38, 47),
    'auth_decision': (48, 57),
    'signing_decision': (58, 67),
    'submit_attempt': (68, 77),
    'submit_result': (78, 87),
    'reconnect': (88, 97),
    'network_switch': (98, 107),
}

OBSERVED_EVENT_EXPECTATIONS = {
    'payload_intake': {'ordinal': 1, 'category': 'payload_intake', 'outcome': 'accepted'},
    'review': {'ordinal': 2, 'category': 'payload_review', 'outcome': 'reviewed'},
    'auth_decision': {'ordinal': 3, 'category': 'auth_decision', 'outcome': 'authorized'},
    'signing_decision': {'ordinal': 4, 'category': 'signing_decision', 'outcome': 'signed'},
    'submit_attempt': {'ordinal': 5, 'category': 'submit_attempt', 'outcome': 'submitted'},
    'submit_result': {'ordinal': 6, 'category': 'submit_result', 'outcome': 'succeeded'},
    'reconnect': {'ordinal': 7, 'category': 'reconnect', 'outcome': 'reconnected'},
    'network_switch': {'ordinal': 8, 'category': 'network_switch', 'outcome': 'switched_to_testnet'},
}

GAP_LINES = {
    'decline': (3, 7),
    'cancel': (8, 12),
    'expiry': (13, 17),
}

EVENT_TO_CLAIMS = {
    'payload_intake': [
        'xaman-testnet-claim:payload-intake-is-categorical-only',
        'xaman-testnet-claim:review-auth-sequence-observed',
        'xaman-testnet-claim:audit-redaction-boundary-is-preserved',
    ],
    'review': [
        'xaman-testnet-claim:review-auth-sequence-observed',
        'xaman-testnet-claim:audit-redaction-boundary-is-preserved',
    ],
    'auth_decision': [
        'xaman-testnet-claim:review-auth-sequence-observed',
        'xaman-testnet-claim:audit-redaction-boundary-is-preserved',
    ],
    'signing_decision': [
        'xaman-testnet-claim:signing-decision-is-observed-but-crypto-output-is-not-modeled',
        'xaman-testnet-claim:review-auth-sequence-observed',
        'xaman-testnet-claim:audit-redaction-boundary-is-preserved',
    ],
    'submit_attempt': [
        'xaman-testnet-claim:submission-ui-attempt-and-result-are-observed',
        'xaman-testnet-claim:broadcast-and-ledger-finality-are-not-modeled',
        'xaman-testnet-claim:audit-redaction-boundary-is-preserved',
    ],
    'submit_result': [
        'xaman-testnet-claim:submission-ui-attempt-and-result-are-observed',
        'xaman-testnet-claim:broadcast-and-ledger-finality-are-not-modeled',
        'xaman-testnet-claim:audit-redaction-boundary-is-preserved',
    ],
    'reconnect': [
        'xaman-testnet-claim:audit-redaction-boundary-is-preserved',
        'xaman-testnet-claim:network-binding-is-testnet-only',
    ],
    'network_switch': [
        'xaman-testnet-claim:network-binding-is-testnet-only',
        'xaman-testnet-claim:audit-redaction-boundary-is-preserved',
    ],
}

EVENT_TO_ASSUMPTIONS = {
    'payload_intake': [
        'xaman-testnet-assumption:redacted-categorical-evidence-only',
        'xaman-testnet-assumption:raw-payload-material-excluded',
    ],
    'review': [
        'xaman-testnet-assumption:redacted-categorical-evidence-only',
        'xaman-testnet-assumption:reviewed-ui-event-is-operator-attested',
    ],
    'auth_decision': [
        'xaman-testnet-assumption:reviewed-ui-event-is-operator-attested',
        'xaman-testnet-assumption:native-vault-and-biometric-security-not-proved',
    ],
    'signing_decision': [
        'xaman-testnet-assumption:native-vault-and-biometric-security-not-proved',
        'xaman-testnet-assumption:raw-signature-and-transaction-blob-excluded',
    ],
    'submit_attempt': [
        'xaman-testnet-assumption:xrpl-broadcast-finality-not-proved',
        'xaman-testnet-assumption:redacted-categorical-evidence-only',
    ],
    'submit_result': [
        'xaman-testnet-assumption:xrpl-broadcast-finality-not-proved',
        'xaman-testnet-assumption:redacted-categorical-evidence-only',
    ],
    'reconnect': [
        'xaman-testnet-assumption:deployed-runtime-equivalence-not-proved',
        'xaman-testnet-assumption:redacted-categorical-evidence-only',
    ],
    'network_switch': [
        'xaman-testnet-assumption:testnet-network-binding-is-verifier-only',
        'xaman-testnet-assumption:deployed-runtime-equivalence-not-proved',
    ],
}

CLAIMS = [
    {
        'id': 'xaman-testnet-claim:network-binding-is-testnet-only',
        'description': 'Reviewed verifier evidence binds the trial to XRPL Testnet network key TESTNET, network_id 1, and an allow-listed public Testnet endpoint digest.',
        'domain': 'ledger',
        'severity': 'high',
        'coverage_tags': ['network_binding'],
        'status': 'MODELED_WITH_TESTNET_SCOPE',
        'required_assumptions': [
            'xaman-testnet-assumption:testnet-network-binding-is-verifier-only',
            'xaman-testnet-assumption:deployed-runtime-equivalence-not-proved',
        ],
    },
    {
        'id': 'xaman-testnet-claim:account-provenance-is-fresh-testnet-only',
        'description': 'The trial records a fresh Testnet account boundary with no imported account, production account, credential, seed, or account material recorded.',
        'domain': 'store',
        'severity': 'blocking',
        'coverage_tags': ['account_provenance'],
        'status': 'MODELED_WITH_TESTNET_SCOPE',
        'required_assumptions': [
            'xaman-testnet-assumption:fresh-account-boundary-is-verifier-attested',
            'xaman-testnet-assumption:redacted-categorical-evidence-only',
        ],
    },
    {
        'id': 'xaman-testnet-claim:review-auth-sequence-observed',
        'description': 'The captured categorical trace orders payload intake, review, and an authorized auth decision before the signing decision.',
        'domain': 'auth_component',
        'severity': 'blocking',
        'coverage_tags': ['review_auth'],
        'status': 'MODELED_WITH_TESTNET_SCOPE',
        'required_assumptions': [
            'xaman-testnet-assumption:reviewed-ui-event-is-operator-attested',
            'xaman-testnet-assumption:native-vault-and-biometric-security-not-proved',
        ],
    },
    {
        'id': 'xaman-testnet-claim:signing-decision-is-observed-but-crypto-output-is-not-modeled',
        'description': 'The reviewed trace observes a signed signing decision, but raw signature bytes, signed transaction blobs, and native cryptographic correctness are intentionally not modeled.',
        'domain': 'vault',
        'severity': 'blocking',
        'coverage_tags': ['signing'],
        'status': 'MODELED_WITH_BLOCKING_NOT_MODELED_BOUNDARY',
        'required_assumptions': [
            'xaman-testnet-assumption:native-vault-and-biometric-security-not-proved',
            'xaman-testnet-assumption:raw-signature-and-transaction-blob-excluded',
        ],
    },
    {
        'id': 'xaman-testnet-claim:submission-ui-attempt-and-result-are-observed',
        'description': 'The reviewed trace observes categorical submit attempt and submit-result UI states only; it does not prove ledger broadcast, inclusion, queue, mempool, or finality.',
        'domain': 'ledger',
        'severity': 'blocking',
        'coverage_tags': ['submission'],
        'status': 'MODELED_WITH_BLOCKING_NOT_MODELED_BOUNDARY',
        'required_assumptions': [
            'xaman-testnet-assumption:xrpl-broadcast-finality-not-proved',
            'xaman-testnet-assumption:redacted-categorical-evidence-only',
        ],
    },
    {
        'id': 'xaman-testnet-claim:payload-intake-is-categorical-only',
        'description': 'Payload intake is represented only as a redacted accepted category; raw payload JSON, intent semantics, and digest-to-signed-byte binding are not represented by the reviewed Testnet evidence.',
        'domain': 'payload',
        'severity': 'blocking',
        'coverage_tags': ['payload'],
        'status': 'NOT_MODELED',
        'required_assumptions': [
            'xaman-testnet-assumption:raw-payload-material-excluded',
            'xaman-testnet-assumption:redacted-categorical-evidence-only',
        ],
    },
    {
        'id': 'xaman-testnet-claim:refusal-path-is-not-modeled',
        'description': 'The decline/refusal path was not exercised in the reviewed trial and remains an explicit NOT_MODELED Testnet lifecycle boundary.',
        'domain': 'e2e_flow',
        'severity': 'blocking',
        'coverage_tags': ['refusal'],
        'status': 'NOT_MODELED',
        'required_assumptions': [
            'xaman-testnet-assumption:decline-cancel-expiry-not-exercised',
        ],
    },
    {
        'id': 'xaman-testnet-claim:replay-controls-are-not-modeled',
        'description': 'The reviewed Testnet lifecycle trace does not exercise replay, duplicate submission, backend atomic single-use, or conflict behavior.',
        'domain': 'payload',
        'severity': 'blocking',
        'coverage_tags': ['replay'],
        'status': 'NOT_MODELED',
        'required_assumptions': [
            'xaman-testnet-assumption:backend-replay-single-use-not-exercised',
        ],
    },
    {
        'id': 'xaman-testnet-claim:expiry-path-is-not-modeled',
        'description': 'Payload expiry behavior was not exercised in the reviewed trial and remains an explicit NOT_MODELED boundary.',
        'domain': 'payload',
        'severity': 'blocking',
        'coverage_tags': ['expiry'],
        'status': 'NOT_MODELED',
        'required_assumptions': [
            'xaman-testnet-assumption:decline-cancel-expiry-not-exercised',
            'xaman-testnet-assumption:backend-replay-single-use-not-exercised',
        ],
    },
    {
        'id': 'xaman-testnet-claim:cancellation-path-is-not-modeled',
        'description': 'Cancellation behavior was not exercised in the reviewed trial and remains an explicit NOT_MODELED boundary.',
        'domain': 'e2e_flow',
        'severity': 'blocking',
        'coverage_tags': ['cancellation'],
        'status': 'NOT_MODELED',
        'required_assumptions': [
            'xaman-testnet-assumption:decline-cancel-expiry-not-exercised',
        ],
    },
    {
        'id': 'xaman-testnet-claim:broadcast-and-ledger-finality-are-not-modeled',
        'description': 'The trace records submit UI categories only; raw XRPL broadcast request, transaction blob, mempool, validated-ledger inclusion, and finality are NOT_MODELED.',
        'domain': 'ledger',
        'severity': 'blocking',
        'coverage_tags': ['broadcast'],
        'status': 'NOT_MODELED',
        'required_assumptions': [
            'xaman-testnet-assumption:xrpl-broadcast-finality-not-proved',
            'xaman-testnet-assumption:raw-signature-and-transaction-blob-excluded',
        ],
    },
    {
        'id': 'xaman-testnet-claim:audit-redaction-boundary-is-preserved',
        'description': 'The model preserves only categorical lifecycle events, source digests, redaction digests, coverage-gap reason codes, and dependency artifact CIDs; it excludes raw payloads, credentials, account addresses, seeds, endpoints, and blobs.',
        'domain': 'audit',
        'severity': 'blocking',
        'coverage_tags': ['audit_boundaries'],
        'status': 'MODELED_WITH_TESTNET_SCOPE',
        'required_assumptions': [
            'xaman-testnet-assumption:redacted-categorical-evidence-only',
            'xaman-testnet-assumption:testnet-verifier-evidence-is-not-production-evidence',
        ],
    },
]

ASSUMPTIONS = [
    {
        'id': 'xaman-testnet-assumption:testnet-verifier-evidence-is-not-production-evidence',
        'description': 'The Testnet verifier APK and emulator trial are public-Testnet evidence only and cannot approve production release behavior.',
        'owner': 'security-verification',
        'status': 'BLOCKING',
    },
    {
        'id': 'xaman-testnet-assumption:testnet-network-binding-is-verifier-only',
        'description': 'Network binding is limited to the reviewed Testnet verifier run, endpoint digest, server_info digest, and network_id 1 observation.',
        'owner': 'ledger-verification',
        'status': 'BLOCKING',
    },
    {
        'id': 'xaman-testnet-assumption:fresh-account-boundary-is-verifier-attested',
        'description': 'Fresh account provenance is accepted only as reviewed categorical verifier evidence; no account address, seed, or credential material is retained.',
        'owner': 'wallet-verification',
        'status': 'BLOCKING',
    },
    {
        'id': 'xaman-testnet-assumption:reviewed-ui-event-is-operator-attested',
        'description': 'Lifecycle action order is based on the reviewed operator UI trial, not on raw device automation logs or production telemetry.',
        'owner': 'runtime-verification',
        'status': 'BLOCKING',
    },
    {
        'id': 'xaman-testnet-assumption:redacted-categorical-evidence-only',
        'description': 'The artifacts retain categorical outcomes, source digests, and redaction digests only; raw security material is intentionally excluded.',
        'owner': 'security-verification',
        'status': 'BLOCKING',
    },
    {
        'id': 'xaman-testnet-assumption:raw-payload-material-excluded',
        'description': 'Raw payload JSON, request bodies, payload semantics, and digest-to-signed-byte reconstruction are outside this reviewed evidence set.',
        'owner': 'payload-verification',
        'status': 'BLOCKING',
    },
    {
        'id': 'xaman-testnet-assumption:native-vault-and-biometric-security-not-proved',
        'description': 'Native vault, biometric/passcode, keychain, and signing cryptography behavior is not proved by the reviewed Testnet lifecycle evidence.',
        'owner': 'wallet-key-management',
        'status': 'BLOCKING',
    },
    {
        'id': 'xaman-testnet-assumption:raw-signature-and-transaction-blob-excluded',
        'description': 'Raw signatures, signed transaction blobs, and account identifiers are redacted and cannot be reconstructed from this model.',
        'owner': 'wallet-transaction-signing',
        'status': 'BLOCKING',
    },
    {
        'id': 'xaman-testnet-assumption:xrpl-broadcast-finality-not-proved',
        'description': 'XRPL submission is modeled as UI submit categories only; node honesty, broadcast request material, mempool, queue, inclusion, and finality are not proved.',
        'owner': 'ledger-verification',
        'status': 'BLOCKING',
    },
    {
        'id': 'xaman-testnet-assumption:backend-replay-single-use-not-exercised',
        'description': 'Replay, backend atomic single-use, duplicate submission, expiration enforcement, and conflict handling were not exercised by the reviewed trial.',
        'owner': 'payload-backend-verification',
        'status': 'BLOCKING',
    },
    {
        'id': 'xaman-testnet-assumption:decline-cancel-expiry-not-exercised',
        'description': 'Decline/refusal, cancellation, and expiry actions appear only as reviewed coverage gaps and are not modeled as successful runtime paths.',
        'owner': 'runtime-verification',
        'status': 'BLOCKING',
    },
    {
        'id': 'xaman-testnet-assumption:deployed-runtime-equivalence-not-proved',
        'description': 'The verifier APK and emulator trace do not prove deployed production runtime equivalence.',
        'owner': 'release-security',
        'status': 'BLOCKING',
    },
    {
        'id': 'xaman-testnet-assumption:native-firebase-packaging-boundary',
        'description': 'Native Firebase packaging remains present; the trial may be described only as JavaScript-stubbed Firebase evidence, not fully Firebase-disabled runtime evidence.',
        'owner': 'mobile-build-security',
        'status': 'BLOCKING',
    },
    {
        'id': 'xaman-testnet-assumption:source-derived-facts-must-be-reviewed',
        'description': 'No source-derived fact is admitted into this Testnet model unless it is bound to a reviewed source, trial, or dependency artifact location.',
        'owner': 'formalization-review',
        'status': 'BLOCKING',
    },
]

NOT_MODELED_RECORDS = [
    {
        'id': 'xaman-testnet-not-modeled:payload-raw-json-and-semantic-validation',
        'category': 'payload',
        'claim_id': 'xaman-testnet-claim:payload-intake-is-categorical-only',
        'assumption_id': 'xaman-testnet-assumption:raw-payload-material-excluded',
        'source_path': TRIAL_REPORT_PATH,
        'line_start': 157,
        'line_end': 180,
        'reason': 'Raw payloads, request bodies, and transaction blobs were not recorded.',
    },
    {
        'id': 'xaman-testnet-not-modeled:signing-crypto-output',
        'category': 'signing',
        'claim_id': 'xaman-testnet-claim:signing-decision-is-observed-but-crypto-output-is-not-modeled',
        'assumption_id': 'xaman-testnet-assumption:raw-signature-and-transaction-blob-excluded',
        'source_path': TRIAL_REPORT_PATH,
        'line_start': 157,
        'line_end': 180,
        'reason': 'Raw signatures and signed transaction blobs were not retained.',
    },
    {
        'id': 'xaman-testnet-not-modeled:network-production-runtime-equivalence',
        'category': 'network',
        'claim_id': 'xaman-testnet-claim:network-binding-is-testnet-only',
        'assumption_id': 'xaman-testnet-assumption:deployed-runtime-equivalence-not-proved',
        'source_path': TRIAL_REPORT_PATH,
        'line_start': 181,
        'line_end': 203,
        'reason': 'The Testnet verifier run is not production runtime-equivalence evidence.',
    },
    {
        'id': 'xaman-testnet-not-modeled:replay-duplicate-submit-and-backend-single-use',
        'category': 'replay',
        'claim_id': 'xaman-testnet-claim:replay-controls-are-not-modeled',
        'assumption_id': 'xaman-testnet-assumption:backend-replay-single-use-not-exercised',
        'source_path': LIFECYCLE_EVIDENCE_PATH,
        'line_start': 27,
        'line_end': 108,
        'reason': 'The reviewed lifecycle event list has no replay or duplicate-submit exercise.',
    },
    {
        'id': 'xaman-testnet-not-modeled:cancellation-path',
        'category': 'cancellation',
        'claim_id': 'xaman-testnet-claim:cancellation-path-is-not-modeled',
        'assumption_id': 'xaman-testnet-assumption:decline-cancel-expiry-not-exercised',
        'source_path': LIFECYCLE_EVIDENCE_PATH,
        'line_start': 8,
        'line_end': 12,
        'reason': 'Cancellation is present only as a not-exercised reviewed coverage gap.',
        'gap_action': 'cancel',
    },
    {
        'id': 'xaman-testnet-not-modeled:expiry-path',
        'category': 'expiry',
        'claim_id': 'xaman-testnet-claim:expiry-path-is-not-modeled',
        'assumption_id': 'xaman-testnet-assumption:decline-cancel-expiry-not-exercised',
        'source_path': LIFECYCLE_EVIDENCE_PATH,
        'line_start': 13,
        'line_end': 17,
        'reason': 'Expiry is present only as a not-exercised reviewed coverage gap.',
        'gap_action': 'expiry',
    },
    {
        'id': 'xaman-testnet-not-modeled:broadcast-request-inclusion-and-finality',
        'category': 'broadcast',
        'claim_id': 'xaman-testnet-claim:broadcast-and-ledger-finality-are-not-modeled',
        'assumption_id': 'xaman-testnet-assumption:xrpl-broadcast-finality-not-proved',
        'source_path': TRIAL_REPORT_PATH,
        'line_start': 181,
        'line_end': 198,
        'reason': 'The report cannot reconstruct transaction blobs and does not prove XRPL broadcast, inclusion, or finality.',
    },
    {
        'id': 'xaman-testnet-not-modeled:refusal-decline-path',
        'category': 'refusal',
        'claim_id': 'xaman-testnet-claim:refusal-path-is-not-modeled',
        'assumption_id': 'xaman-testnet-assumption:decline-cancel-expiry-not-exercised',
        'source_path': LIFECYCLE_EVIDENCE_PATH,
        'line_start': 3,
        'line_end': 7,
        'reason': 'Refusal/decline is present only as a not-exercised reviewed coverage gap.',
        'gap_action': 'decline',
    },
]


def _rel(path: Path) -> str:
    return path.relative_to(ROOT_DIR).as_posix()


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding='utf-8'))


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True) + '\n',
        encoding='utf-8',
    )


def _sha256_json(payload: Mapping[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode('utf-8')
    return 'sha256:' + hashlib.sha256(canonical).hexdigest()


def _stable_model_cid(model: Mapping[str, Any]) -> str:
    return 'sha256:' + hashlib.sha256(canonicalize_ir(model)).hexdigest()


def _evidence_ref(
    path: Path,
    *,
    line_start: int | None = None,
    line_end: int | None = None,
    notes: str | None = None,
) -> dict[str, Any]:
    ref: dict[str, Any] = {
        'kind': 'manual_review',
        'path': _rel(path),
        'review_status': 'human_reviewed',
        'sha256': _sha256_file(path),
    }
    if line_start is not None:
        ref['line_start'] = line_start
    if line_end is not None:
        ref['line_end'] = line_end
    if notes:
        ref['notes'] = notes
    return ref


def _artifact_cid_without_self(payload: Mapping[str, Any]) -> str:
    return _sha256_json({key: value for key, value in payload.items() if key != 'artifact_cid'})


def _require_artifact_cid(payload: Mapping[str, Any], label: str) -> None:
    expected = _artifact_cid_without_self(payload)
    _require(payload.get('artifact_cid') == expected, f'{label} artifact_cid mismatch')


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _require_hex_digest(value: Any, label: str) -> str:
    _require(isinstance(value, str) and SHA256_RE.fullmatch(value) is not None, f'{label} must be a sha256 hex digest')
    return value


def _validate_inputs(
    lifecycle: Mapping[str, Any],
    trial: Mapping[str, Any],
    network: Mapping[str, Any],
    device: Mapping[str, Any],
    native: Mapping[str, Any],
) -> None:
    _require(lifecycle.get('schema_version') == 'xaman-testnet-transaction-lifecycle-evidence/v1', 'unexpected lifecycle evidence schema')
    _require(lifecycle.get('evidence_type') == 'reviewed_operator_trial', 'lifecycle evidence is not a reviewed operator trial')
    _require(lifecycle.get('network_key') == 'TESTNET', 'lifecycle evidence is not bound to TESTNET')
    _require(lifecycle.get('reviewed_at_utc') == REVIEWED_AT_UTC, 'unexpected lifecycle review timestamp')
    _require(lifecycle.get('fresh_emulator_profile') is True, 'fresh emulator profile is required')
    account = lifecycle.get('fresh_account_boundary')
    _require(isinstance(account, Mapping), 'fresh account boundary missing')
    _require(account.get('fresh_account_created') is True, 'fresh account was not created')
    _require(account.get('imported_account') is False, 'imported accounts are outside scope')
    _require(account.get('production_account') is False, 'production accounts are outside scope')
    _require(account.get('account_material_recorded') is False, 'account material must be redacted')

    _require(trial.get('schema_version') == 'xaman-testnet-transaction-lifecycle-trial/v1', 'unexpected trial schema')
    _require_artifact_cid(trial, 'trial report')
    _require(trial.get('task_id') == 'PORTAL-CXTP-130', 'trial task mismatch')
    _require(trial.get('overall_status') == 'executed_with_coverage_gaps', 'trial must retain coverage gaps')
    _require(trial.get('production_release_blocked') is True, 'trial must keep production release blocked')
    _require(trial.get('runtime_equivalence_status') == 'not_proved', 'runtime equivalence must remain not_proved')
    _require(trial.get('xaman_commit') == XAMAN_COMMIT, 'trial commit mismatch')
    _require(trial.get('redaction_boundary', {}).get('redaction_failure') is False, 'redaction failure blocks projection')
    _require(trial.get('redaction_boundary', {}).get('raw_payloads_recorded') is False, 'raw payloads must not be recorded')
    _require(trial.get('redaction_boundary', {}).get('transaction_blobs_recorded') is False, 'transaction blobs must not be recorded')
    _require(trial.get('redaction_boundary', {}).get('credentials_recorded') is False, 'credentials must not be recorded')
    _require(
        trial.get('evidence_inputs', {}).get('lifecycle_evidence_sha256') == _sha256_file(LIFECYCLE_EVIDENCE_PATH),
        'trial lifecycle evidence sha256 mismatch',
    )

    _require(network.get('schema_version') == 'xaman-testnet-network-selection/v1', 'unexpected network report schema')
    _require_artifact_cid(network, 'network report')
    _require(network.get('task_id') == 'PORTAL-CXTP-125', 'network task mismatch')
    _require(network.get('xaman_commit') == XAMAN_COMMIT, 'network commit mismatch')
    _require(network.get('overall_status') == 'verified', 'network report must be verified')
    _require(network.get('endpoint_allow_list_decision', {}).get('allowed') is True, 'endpoint allow-list decision must be allowed')
    _require(network.get('xrpl_server_info_binding', {}).get('network_id') == 1, 'network_id must be XRPL Testnet id 1')
    _require(network.get('xrpl_server_info_binding', {}).get('network_id_verified') is True, 'network_id must be verified')
    _require(network.get('redaction_boundary', {}).get('raw_request_bodies_recorded') is False, 'raw server_info request must be redacted')
    _require(network.get('redaction_boundary', {}).get('raw_server_info_response_recorded') is False, 'raw server_info response must be redacted')

    _require(device.get('schema_version') == 'xaman-testnet-device-trial/v1', 'unexpected device report schema')
    _require_artifact_cid(device, 'device report')
    _require(device.get('task_id') == 'PORTAL-CXTP-121', 'device task mismatch')
    _require(device.get('overall_status') == 'executed_with_boundaries', 'device report boundary status mismatch')
    _require(device.get('approved_non_production_wallet_flow', {}).get('fresh_testnet_credentials', {}).get('production_account') is False, 'device report production account boundary mismatch')

    _require(native.get('schema_version') == 'xaman-native-firebase-boundary/v1', 'unexpected native Firebase schema')
    _require_artifact_cid(native, 'native Firebase report')
    _require(native.get('task_id') == 'PORTAL-CXTP-126', 'native Firebase task mismatch')
    _require(native.get('native_firebase_fully_disabled') is False, 'native Firebase fully-disabled label must remain blocked')

    events = lifecycle.get('lifecycle_events')
    _require(isinstance(events, list), 'lifecycle_events must be a list')
    _require(len(events) == len(OBSERVED_EVENT_EXPECTATIONS), 'lifecycle evidence must contain exactly the reviewed observed event count')
    seen_ordinals: set[int] = set()
    seen_actions: set[str] = set()
    for event in events:
        _require(isinstance(event, Mapping), 'each lifecycle event must be a mapping')
        action = event.get('action')
        ordinal = event.get('ordinal')
        _require(isinstance(action, str) and action in OBSERVED_EVENT_LINES, f'unrecognized lifecycle action: {action!r}')
        _require(isinstance(ordinal, int) and ordinal > 0, f'lifecycle action {action} has invalid ordinal')
        _require(ordinal not in seen_ordinals, f'ambiguous duplicate lifecycle ordinal: {ordinal}')
        _require(action not in seen_actions, f'ambiguous duplicate lifecycle action: {action}')
        _require(event.get('source_kind') == 'reviewed_ui', f'lifecycle action {action} is not reviewed_ui evidence')
        _require(event.get('raw_material_recorded') is False, f'lifecycle action {action} retained raw material')
        expected = OBSERVED_EVENT_EXPECTATIONS[action]
        _require(event.get('category') == expected['category'], f'lifecycle action {action} category mismatch')
        _require(event.get('outcome') == expected['outcome'], f'lifecycle action {action} outcome mismatch')
        _require_hex_digest(event.get('source_sha256'), f'{action}.source_sha256')
        _require_hex_digest(event.get('redaction_sha256'), f'{action}.redaction_sha256')
        seen_ordinals.add(ordinal)
        seen_actions.add(action)
    _require(seen_actions == set(OBSERVED_EVENT_LINES), 'lifecycle evidence does not contain exactly the reviewed observed actions')
    _require(
        [event['action'] for event in events] == list(OBSERVED_EVENT_EXPECTATIONS),
        'lifecycle event order does not match reviewed trace',
    )
    _require(
        [event['ordinal'] for event in events] == [expectation['ordinal'] for expectation in OBSERVED_EVENT_EXPECTATIONS.values()],
        'lifecycle event ordinals do not match reviewed trace',
    )

    gap_actions = {gap.get('action') for gap in lifecycle.get('coverage_gaps', []) if isinstance(gap, Mapping)}
    _require(gap_actions == {'decline', 'cancel', 'expiry'}, 'coverage gaps must be exactly decline, cancel, and expiry')
    for gap in lifecycle.get('coverage_gaps', []):
        _require(gap.get('reason_code') == 'not_exercised_in_reviewed_trial', f'{gap.get("action")} coverage gap reason mismatch')
        _require_hex_digest(gap.get('reviewer_note_sha256'), f'{gap.get("action")}.reviewer_note_sha256')


def _assumption_evidence_refs(assumption_id: str) -> list[dict[str, Any]]:
    refs = [_evidence_ref(TRIAL_REPORT_PATH, line_start=181, line_end=203)]
    if 'network' in assumption_id:
        refs.append(_evidence_ref(NETWORK_REPORT_PATH, line_start=1, line_end=123))
    if 'fresh-account' in assumption_id:
        refs.append(_evidence_ref(DEVICE_REPORT_PATH, line_start=2, line_end=75))
    if 'firebase' in assumption_id:
        refs.append(_evidence_ref(NATIVE_FIREBASE_REPORT_PATH, line_start=1, line_end=220))
    if 'decline-cancel-expiry' in assumption_id or 'replay' in assumption_id:
        refs.append(_evidence_ref(LIFECYCLE_EVIDENCE_PATH, line_start=2, line_end=17))
    return refs


def _structured_assumptions() -> list[dict[str, Any]]:
    return [
        {
            **assumption,
            'custom': True,
            'evidence_refs': _assumption_evidence_refs(assumption['id']),
            'evidence_expires_at': EVIDENCE_EXPIRES_AT,
            'last_reviewed_at': REVIEWED_AT_UTC,
            'required_evidence_to_clear': _required_evidence_to_clear(assumption['id']),
        }
        for assumption in ASSUMPTIONS
    ]


def _required_evidence_to_clear(assumption_id: str) -> list[str]:
    if 'network' in assumption_id:
        return ['production runtime network trace', 'endpoint authenticity model', 'fresh server_info evidence']
    if 'fresh-account' in assumption_id:
        return ['reviewed wallet provenance trace with allowed account identifiers redacted by policy']
    if 'vault' in assumption_id or 'signature' in assumption_id:
        return ['native vault audit', 'signature-byte binding trace', 'cryptographic signing proof']
    if 'broadcast' in assumption_id:
        return ['raw-broadcast-safe digest evidence', 'XRPL validated-ledger inclusion proof', 'finality model']
    if 'replay' in assumption_id:
        return ['duplicate-submit negative trace', 'backend atomic single-use evidence', 'expiration enforcement trace']
    if 'decline-cancel-expiry' in assumption_id:
        return ['reviewed decline trace', 'reviewed cancel trace', 'reviewed expiry trace']
    if 'runtime-equivalence' in assumption_id:
        return ['production build provenance', 'real-device trace bundle', 'runtime equivalence review']
    if 'firebase' in assumption_id:
        return ['native Firebase-free APK proof or corrected label']
    if 'source-derived' in assumption_id:
        return ['reviewed source-to-model trace map for every source-derived fact']
    return ['reviewer signoff and replacement evidence bundle']


def _claim_evidence_refs(claim: Mapping[str, Any]) -> list[dict[str, Any]]:
    tags = set(claim['coverage_tags'])
    refs: list[dict[str, Any]] = []
    if tags & {'payload', 'review_auth', 'signing', 'submission', 'audit_boundaries'}:
        refs.append(_evidence_ref(LIFECYCLE_EVIDENCE_PATH, line_start=27, line_end=108))
        refs.append(_evidence_ref(TRIAL_REPORT_PATH, line_start=224, line_end=351))
    if 'network_binding' in tags:
        refs.append(_evidence_ref(NETWORK_REPORT_PATH, line_start=1, line_end=123))
        refs.append(_evidence_ref(TRIAL_REPORT_PATH, line_start=205, line_end=223))
    if 'account_provenance' in tags:
        refs.append(_evidence_ref(DEVICE_REPORT_PATH, line_start=2, line_end=75))
        refs.append(_evidence_ref(TRIAL_REPORT_PATH, line_start=24, line_end=38))
    if tags & {'refusal', 'cancellation', 'expiry'}:
        refs.append(_evidence_ref(LIFECYCLE_EVIDENCE_PATH, line_start=2, line_end=17))
    if 'replay' in tags:
        refs.append(_evidence_ref(LIFECYCLE_EVIDENCE_PATH, line_start=27, line_end=108))
    if 'broadcast' in tags:
        refs.append(_evidence_ref(TRIAL_REPORT_PATH, line_start=181, line_end=198))
    refs.append(_evidence_ref(SECURITY_CLAIMS_PATH, line_start=1, line_end=359, notes='Baseline Xaman claim registry used only as reviewed context.'))
    return refs


def _event_id(action: str) -> str:
    return f'xaman-testnet-event:{action.replace("_", "-")}'


def _fact_id(action: str) -> str:
    return f'xaman-testnet-fact:{action.replace("_", "-")}'


def _event_name(action: str) -> str:
    return f'xaman_testnet_{action}'


def _build_events(lifecycle: Mapping[str, Any]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for event in lifecycle['lifecycle_events']:
        action = str(event['action'])
        line_start, line_end = OBSERVED_EVENT_LINES[action]
        events.append(
            {
                'id': _event_id(action),
                'event': _event_name(action),
                'custom': True,
                'description': f'Redacted reviewed Testnet lifecycle action {action}.',
                'timestamp': f'2026-07-10T23:00:{int(event["ordinal"]):02d}Z',
                'ordinal': event['ordinal'],
                'testnet_action': action,
                'category': event['category'],
                'outcome': event['outcome'],
                'source_kind': event['source_kind'],
                'source_sha256': event['source_sha256'],
                'redaction_sha256': event['redaction_sha256'],
                'raw_material_recorded': event['raw_material_recorded'],
                'model_fact_id': _fact_id(action),
                'evidence_refs': [
                    _evidence_ref(LIFECYCLE_EVIDENCE_PATH, line_start=line_start, line_end=line_end),
                    _evidence_ref(TRIAL_REPORT_PATH, line_start=224, line_end=351),
                ],
            }
        )
    return events


def _build_metadata(
    lifecycle: Mapping[str, Any],
    trial: Mapping[str, Any],
    network: Mapping[str, Any],
    device: Mapping[str, Any],
    native: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        'task_id': 'PORTAL-CXTP-131',
        'track': 'formalization',
        'generated_at_utc': GENERATED_AT_UTC,
        'reviewed_at_utc': REVIEWED_AT_UTC,
        'source': {
            'repo_url': 'https://github.com/XRPL-Labs/Xaman-App',
            'commit_sha': XAMAN_COMMIT,
            'manifest_path': 'security_ir_artifacts/corpora/xaman-app/source-manifest.json',
        },
        'model_scope': {
            'network': 'XRPL_TESTNET',
            'network_key': 'TESTNET',
            'network_id': 1,
            'production_usable': False,
            'real_assets_allowed': False,
            'runtime_equivalence_status': 'not_proved',
            'firebase_classification': 'firebase_js_stubbed_only',
            'native_firebase_fully_disabled': False,
        },
        'security_decision': 'TESTNET_MODEL_PROJECTED_WITH_NOT_MODELED_BOUNDARIES_NOT_PRODUCTION_EVIDENCE',
        'production_release_blocked': True,
        'canonicalization': {
            'algorithm': 'security-model-ir canonicalize_ir sort_keys separators sha256 fallback',
            'cid_path': _rel(MODEL_CID_PATH),
        },
        'bound_artifacts': {
            'lifecycle_evidence': {
                'path': _rel(LIFECYCLE_EVIDENCE_PATH),
                'sha256': _sha256_file(LIFECYCLE_EVIDENCE_PATH),
                'schema_version': lifecycle['schema_version'],
            },
            'transaction_trial_report': {
                'path': _rel(TRIAL_REPORT_PATH),
                'sha256': _sha256_file(TRIAL_REPORT_PATH),
                'artifact_cid': trial['artifact_cid'],
                'schema_version': trial['schema_version'],
            },
            'network_selection_report': {
                'path': _rel(NETWORK_REPORT_PATH),
                'sha256': _sha256_file(NETWORK_REPORT_PATH),
                'artifact_cid': network['artifact_cid'],
                'schema_version': network['schema_version'],
            },
            'device_trial_report': {
                'path': _rel(DEVICE_REPORT_PATH),
                'sha256': _sha256_file(DEVICE_REPORT_PATH),
                'artifact_cid': device['artifact_cid'],
                'schema_version': device['schema_version'],
            },
            'native_firebase_boundary_report': {
                'path': _rel(NATIVE_FIREBASE_REPORT_PATH),
                'sha256': _sha256_file(NATIVE_FIREBASE_REPORT_PATH),
                'artifact_cid': native['artifact_cid'],
                'schema_version': native['schema_version'],
            },
            'security_claims': {
                'path': _rel(SECURITY_CLAIMS_PATH),
                'sha256': _sha256_file(SECURITY_CLAIMS_PATH),
            },
        },
        'testnet_network_binding': trial['testnet_network_binding'],
        'fresh_account_boundary': lifecycle['fresh_account_boundary'],
        'redaction_boundary': trial['redaction_boundary'],
        'ambiguity_policy': {
            'duplicate_event_actions_rejected': True,
            'duplicate_event_ordinals_rejected': True,
            'unreviewed_source_derived_facts_rejected': True,
            'raw_material_records_rejected': True,
        },
        'typed_model_facts': [
            {
                'id': _fact_id(event['action']),
                'type': 'TESTNET_LIFECYCLE_EVENT',
                'event_id': _event_id(event['action']),
                'action': event['action'],
                'category': event['category'],
                'outcome': event['outcome'],
                'ordinal': event['ordinal'],
                'claim_ids': EVENT_TO_CLAIMS[event['action']],
                'assumption_ids': EVENT_TO_ASSUMPTIONS[event['action']],
                'source_location': {
                    'path': _rel(LIFECYCLE_EVIDENCE_PATH),
                    'line_start': OBSERVED_EVENT_LINES[event['action']][0],
                    'line_end': OBSERVED_EVENT_LINES[event['action']][1],
                },
                'redaction_digest': event['redaction_sha256'],
            }
            for event in lifecycle['lifecycle_events']
        ],
        'not_modeled_records': [
            _not_modeled_record(record, lifecycle, trial, network) for record in NOT_MODELED_RECORDS
        ],
    }


def _not_modeled_record(
    record: Mapping[str, Any],
    lifecycle: Mapping[str, Any],
    trial: Mapping[str, Any],
    network: Mapping[str, Any],
) -> dict[str, Any]:
    gap_action = record.get('gap_action')
    redaction_digest = trial['evidence_inputs']['lifecycle_evidence_sha256']
    if gap_action:
        for gap in lifecycle['coverage_gaps']:
            if gap['action'] == gap_action:
                redaction_digest = gap['reviewer_note_sha256']
                break
    elif record['category'] == 'network':
        redaction_digest = network['xrpl_server_info_binding']['response_sha256']
    elif record['category'] == 'broadcast':
        redaction_digest = trial['evidence_inputs']['lifecycle_evidence_sha256']
    return {
        'id': record['id'],
        'status': 'NOT_MODELED',
        'category': record['category'],
        'claim_id': record['claim_id'],
        'assumption_id': record['assumption_id'],
        'reason': record['reason'],
        'source_location': {
            'path': _rel(record['source_path']),
            'line_start': record['line_start'],
            'line_end': record['line_end'],
        },
        'redaction_digest': redaction_digest,
        'evidence_review_status': 'human_reviewed',
    }


def _build_ir(
    lifecycle: Mapping[str, Any],
    trial: Mapping[str, Any],
    network: Mapping[str, Any],
    device: Mapping[str, Any],
    native: Mapping[str, Any],
) -> dict[str, Any]:
    events = _build_events(lifecycle)
    assumptions = _structured_assumptions()
    claims = [
        {
            'id': claim['id'],
            'description': claim['description'],
            'domain': claim['domain'],
            'severity': claim['severity'],
            'coverage_tags': claim['coverage_tags'],
            'status': claim['status'],
            'required_assumptions': claim['required_assumptions'],
            'evidence_refs': _claim_evidence_refs(claim),
            'custom': False,
        }
        for claim in CLAIMS
    ]
    model = {
        'schema_version': 'security-model-ir/xaman/v1',
        'model_id': 'xaman-app-testnet-transaction-lifecycle-security-model-ir',
        'entities': [
            {
                'id': 'xaman-app-testnet-verifier',
                'name': 'Xaman Testnet verifier APK and emulator trial',
                'kind': 'react_native_wallet_testnet_verifier',
                'evidence_refs': [_evidence_ref(TRIAL_REPORT_PATH, line_start=1, line_end=204)],
            }
        ],
        'assets': [
            {
                'id': 'xrp-testnet',
                'symbol': 'XRP',
                'network': 'XRPL_TESTNET',
                'network_id': 1,
                'real_asset': False,
            }
        ],
        'wallets': [
            {
                'id': 'xaman-testnet-fresh-wallet',
                'asset_id': 'xrp-testnet',
                'owner': 'xaman-testnet-operator',
                'status': 'active',
                'fresh_testnet_only': True,
            }
        ],
        'accounts': [
            {
                'id': 'xaman-testnet-fresh-account',
                'asset_id': 'xrp-testnet',
                'wallet_id': 'xaman-testnet-fresh-wallet',
                'owner': 'xaman-testnet-operator',
                'balance': 0,
                'fresh_account_created': True,
                'production_account': False,
                'account_material_recorded': False,
            }
        ],
        'roles': [
            {'id': 'testnet-operator-role', 'name': 'Reviewed Testnet Operator'},
            {'id': 'formalization-reviewer-role', 'name': 'Formalization Reviewer'},
        ],
        'principals': [
            {'id': 'xaman-testnet-operator', 'role': 'testnet-operator-role'},
            {'id': 'security-formalization-reviewer', 'role': 'formalization-reviewer-role'},
        ],
        'capabilities': [
            {
                'id': 'xaman-testnet-capability:approve-reviewed-payload',
                'principal_id': 'xaman-testnet-operator',
                'resource_id': 'xaman-testnet-fresh-wallet',
                'action': 'approve_xrpl_testnet_payload',
            },
            {
                'id': 'xaman-testnet-capability:review-redacted-trace',
                'principal_id': 'security-formalization-reviewer',
                'resource_id': 'xaman-app-testnet-verifier',
                'action': 'review_redacted_testnet_trace',
            },
        ],
        'policies': [
            {
                'id': 'xaman-testnet-policy:no-production-release',
                'name': 'Testnet model cannot approve production release',
                'enabled': True,
                'evidence_refs': [_evidence_ref(TRIAL_REPORT_PATH, line_start=181, line_end=204)],
            },
            {
                'id': 'xaman-testnet-policy:redacted-only',
                'name': 'Retain only redacted categorical lifecycle evidence',
                'enabled': True,
                'evidence_refs': [_evidence_ref(TRIAL_REPORT_PATH, line_start=157, line_end=180)],
            },
            {
                'id': 'xaman-testnet-policy:reject-ambiguous-unreviewed-mappings',
                'name': 'Reject ambiguous mappings and unreviewed source-derived facts',
                'enabled': True,
                'evidence_refs': [_evidence_ref(LIFECYCLE_EVIDENCE_PATH, line_start=1, line_end=112)],
            },
        ],
        'events': events,
        'state_machines': [
            {
                'id': 'xaman-testnet-state-machine:lifecycle-projection',
                'states': [
                    'payload_intake_observed',
                    'review_observed',
                    'auth_observed',
                    'signing_observed',
                    'submission_observed',
                    'coverage_gaps_retained',
                    'not_production_evidence',
                ],
                'current': 'not_production_evidence',
                'events_projected_in_order': [_event_id(event['action']) for event in lifecycle['lifecycle_events']],
                'not_modeled_actions': ['decline', 'cancel', 'expiry', 'replay', 'broadcast_finality'],
            }
        ],
        'invariants': [
            {
                'id': 'xaman-testnet-invariant:no-raw-sensitive-material',
                'description': 'No raw payload, credential, account address, seed, endpoint, request body, server_info response, signature, or transaction blob is retained in the Testnet model artifacts.',
                'evidence_refs': [_evidence_ref(TRIAL_REPORT_PATH, line_start=157, line_end=180)],
            },
            {
                'id': 'xaman-testnet-invariant:not-production-evidence',
                'description': 'The Testnet model remains production-blocking until runtime equivalence, raw-material-safe proof inputs, and gap coverage are reviewed.',
                'evidence_refs': [_evidence_ref(TRIAL_REPORT_PATH, line_start=181, line_end=204)],
            },
        ],
        'claims': claims,
        'proof_obligations': [
            {
                'id': f'xaman-testnet-obligation:{claim["id"].split(":", 1)[1]}',
                'claim_id': claim['id'],
                'prover': 'z3',
                'status': 'NOT_MODELED' if claim['status'] == 'NOT_MODELED' else 'UNKNOWN',
                'evidence_refs': _claim_evidence_refs(claim),
            }
            for claim in CLAIMS
        ],
        'disproof_vectors': [
            {
                'id': f'xaman-testnet-disproof:{claim["id"].split(":", 1)[1]}',
                'claim_id': claim['id'],
                'tactic': f'Attempt mutation against Testnet lifecycle claim tag(s): {", ".join(claim["coverage_tags"])}.',
                'status': 'UNKNOWN',
                'evidence_refs': _claim_evidence_refs(claim),
            }
            for claim in CLAIMS
        ],
        'runtime_traces': [
            {
                'id': 'xaman-testnet-runtime-trace:transaction-lifecycle-reviewed',
                'description': 'Reviewed redacted Testnet transaction lifecycle trace projected into typed model facts with explicit NOT_MODELED gap boundaries.',
                'domain': 'e2e_flow',
                'events': [_event_id(event['action']) for event in lifecycle['lifecycle_events']],
                'conformance_status': 'executed_with_coverage_gaps_not_production_evidence',
                'evidence_refs': [
                    _evidence_ref(LIFECYCLE_EVIDENCE_PATH, line_start=1, line_end=112),
                    _evidence_ref(TRIAL_REPORT_PATH, line_start=1, line_end=351),
                ],
            }
        ],
        'solver_results': [
            {
                'id': f'xaman-testnet-solver-result:{claim["id"].split(":", 1)[1]}',
                'claim_id': claim['id'],
                'solver_name': 'z3',
                'result': 'not-modeled' if claim['status'] == 'NOT_MODELED' else 'unknown',
                'evidence_refs': _claim_evidence_refs(claim),
            }
            for claim in CLAIMS
        ],
        'assumptions': assumptions,
        'prover_targets': ['z3', 'cvc5', 'lean', 'tla'],
        'metadata': _build_metadata(lifecycle, trial, network, device, native),
    }
    validate_ir(model)
    return model


def _build_trace_map(model: Mapping[str, Any], model_cid: str, lifecycle: Mapping[str, Any], trial: Mapping[str, Any], network: Mapping[str, Any]) -> dict[str, Any]:
    event_mappings = []
    for event in lifecycle['lifecycle_events']:
        action = event['action']
        line_start, line_end = OBSERVED_EVENT_LINES[action]
        event_mappings.append(
            {
                'source_event_key': f'lifecycle_events[{int(event["ordinal"]) - 1}].{action}',
                'source_action': action,
                'source_ordinal': event['ordinal'],
                'mapping_status': 'MODELED',
                'ambiguity_status': 'unambiguous',
                'typed_model_fact': {
                    'id': _fact_id(action),
                    'type': 'TESTNET_LIFECYCLE_EVENT',
                    'event_id': _event_id(action),
                    'ir_collection': 'events',
                },
                'source_location': {
                    'path': _rel(LIFECYCLE_EVIDENCE_PATH),
                    'line_start': line_start,
                    'line_end': line_end,
                    'source_sha256': event['source_sha256'],
                },
                'claim_ids': EVENT_TO_CLAIMS[action],
                'assumption_ids': EVENT_TO_ASSUMPTIONS[action],
                'redaction_digest': event['redaction_sha256'],
                'review_status': 'human_reviewed',
            }
        )

    coverage_gap_mappings = []
    for gap in lifecycle['coverage_gaps']:
        action = gap['action']
        line_start, line_end = GAP_LINES[action]
        claim_id = {
            'decline': 'xaman-testnet-claim:refusal-path-is-not-modeled',
            'cancel': 'xaman-testnet-claim:cancellation-path-is-not-modeled',
            'expiry': 'xaman-testnet-claim:expiry-path-is-not-modeled',
        }[action]
        coverage_gap_mappings.append(
            {
                'source_gap_key': f'coverage_gaps.{action}',
                'source_action': action,
                'mapping_status': 'NOT_MODELED',
                'ambiguity_status': 'unambiguous',
                'typed_model_fact': {
                    'id': f'xaman-testnet-gap:{action}',
                    'type': 'TESTNET_LIFECYCLE_COVERAGE_GAP',
                    'ir_collection': 'metadata.not_modeled_records',
                },
                'source_location': {
                    'path': _rel(LIFECYCLE_EVIDENCE_PATH),
                    'line_start': line_start,
                    'line_end': line_end,
                    'source_sha256': _sha256_file(LIFECYCLE_EVIDENCE_PATH),
                },
                'claim_ids': [claim_id],
                'assumption_ids': ['xaman-testnet-assumption:decline-cancel-expiry-not-exercised'],
                'redaction_digest': gap['reviewer_note_sha256'],
                'review_status': 'human_reviewed',
                'reason_code': gap['reason_code'],
            }
        )

    not_modeled_records = [
        _not_modeled_record(record, lifecycle, trial, network) for record in NOT_MODELED_RECORDS
    ]
    trace_map = {
        'schema_version': 'xaman-testnet-claim-trace-map/v1',
        'task_id': 'PORTAL-CXTP-131',
        'generated_at_utc': GENERATED_AT_UTC,
        'model_id': model['model_id'],
        'model_path': _rel(MODEL_PATH),
        'model_cid': model_cid,
        'source_evidence': {
            'lifecycle_evidence_path': _rel(LIFECYCLE_EVIDENCE_PATH),
            'lifecycle_evidence_sha256': _sha256_file(LIFECYCLE_EVIDENCE_PATH),
            'transaction_trial_report_path': _rel(TRIAL_REPORT_PATH),
            'transaction_trial_report_cid': trial['artifact_cid'],
            'network_selection_report_path': _rel(NETWORK_REPORT_PATH),
            'network_selection_report_cid': network['artifact_cid'],
        },
        'event_mappings': event_mappings,
        'coverage_gap_mappings': coverage_gap_mappings,
        'not_modeled_records': not_modeled_records,
        'claim_coverage': {
            tag: sorted(claim['id'] for claim in CLAIMS if tag in claim['coverage_tags'])
            for tag in [
                'network_binding',
                'account_provenance',
                'review_auth',
                'signing',
                'submission',
                'payload',
                'refusal',
                'replay',
                'expiry',
                'cancellation',
                'broadcast',
                'audit_boundaries',
            ]
        },
        'rejection_policy': {
            'reject_ambiguous_mappings': True,
            'reject_duplicate_source_actions': True,
            'reject_duplicate_source_ordinals': True,
            'reject_unreviewed_source_derived_facts': True,
            'reject_raw_material_records': True,
        },
    }
    trace_map['artifact_cid'] = _artifact_cid_without_self(trace_map)
    return trace_map


def _build_assumptions_artifact(model_cid: str, assumptions: list[Mapping[str, Any]]) -> dict[str, Any]:
    payload = {
        'schema_version': 'xaman-testnet-assumptions/v1',
        'task_id': 'PORTAL-CXTP-131',
        'generated_at_utc': GENERATED_AT_UTC,
        'model_path': _rel(MODEL_PATH),
        'model_cid': model_cid,
        'blocking_assumption_count': len(assumptions),
        'assumptions': [
            {
                **assumption,
                'blocks_production_release': True,
                'clears_only_with_reviewed_replacement_evidence': True,
            }
            for assumption in assumptions
        ],
    }
    payload['artifact_cid'] = _artifact_cid_without_self(payload)
    return payload


def build_artifacts() -> dict[str, Any]:
    lifecycle = _load_json(LIFECYCLE_EVIDENCE_PATH)
    trial = _load_json(TRIAL_REPORT_PATH)
    network = _load_json(NETWORK_REPORT_PATH)
    device = _load_json(DEVICE_REPORT_PATH)
    native = _load_json(NATIVE_FIREBASE_REPORT_PATH)
    _validate_inputs(lifecycle, trial, network, device, native)

    model = _build_ir(lifecycle, trial, network, device, native)
    model_cid = _stable_model_cid(model)
    trace_map = _build_trace_map(model, model_cid, lifecycle, trial, network)
    assumptions_artifact = _build_assumptions_artifact(model_cid, model['assumptions'])
    return {
        'model': model,
        'model_cid': model_cid,
        'trace_map': trace_map,
        'assumptions': assumptions_artifact,
    }


def write_artifacts() -> dict[str, Any]:
    artifacts = build_artifacts()
    _write_json(MODEL_PATH, artifacts['model'])
    MODEL_CID_PATH.write_text(artifacts['model_cid'] + '\n', encoding='utf-8')
    _write_json(TRACE_MAP_PATH, artifacts['trace_map'])
    _write_json(ASSUMPTIONS_PATH, artifacts['assumptions'])
    return artifacts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='Build and validate artifacts without writing files')
    args = parser.parse_args(argv)
    artifacts = build_artifacts() if args.check else write_artifacts()
    print(
        json.dumps(
            {
                'model_path': _rel(MODEL_PATH),
                'model_cid': artifacts['model_cid'],
                'trace_map_path': _rel(TRACE_MAP_PATH),
                'assumptions_path': _rel(ASSUMPTIONS_PATH),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
