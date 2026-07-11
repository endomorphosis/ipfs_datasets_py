"""Tests for PORTAL-CXTP-130 Xaman Testnet transaction lifecycle trial."""

from __future__ import annotations

import importlib.util
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest


REPO_ROOT = Path(__file__).resolve().parents[4]
SCRIPT_PATH = (
    REPO_ROOT
    / 'scripts'
    / 'ops'
    / 'security_verification'
    / 'capture_xaman_testnet_transaction_trial.py'
)
ARTIFACT_PATH = (
    REPO_ROOT
    / 'security_ir_artifacts'
    / 'corpora'
    / 'xaman-app'
    / 'runtime'
    / 'testnet-transaction-trial-report.json'
)
EVIDENCE_PATH = (
    REPO_ROOT
    / 'security_ir_artifacts'
    / 'corpora'
    / 'xaman-app'
    / 'runtime'
    / 'testnet-transaction-lifecycle-evidence.json'
)
DOC_PATH = REPO_ROOT / 'docs' / 'security_verification' / 'xaman_testnet_transaction_trial.md'


def _load_module():
    spec = importlib.util.spec_from_file_location('capture_xaman_testnet_transaction_trial', SCRIPT_PATH)
    if spec is None or spec.loader is None:  # pragma: no cover
        raise AssertionError('failed to load transaction-trial capture script')
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _write_json(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if 'artifact_cid' in payload:
        payload = dict(payload)
        canonical = json.dumps(
            {key: value for key, value in payload.items() if key != 'artifact_cid'},
            sort_keys=True,
            separators=(',', ':'),
        ).encode('utf-8')
        payload['artifact_cid'] = 'sha256:' + hashlib.sha256(canonical).hexdigest()
    path.write_text(json.dumps(payload, sort_keys=True), encoding='utf-8')
    return path


def _artifact_cid(prefix: str = 'a') -> str:
    return 'sha256:' + (prefix * 64)


def _fixture_digest(*parts: object) -> str:
    return hashlib.sha256('|'.join(str(part) for part in parts).encode('utf-8')).hexdigest()


def _apk(tmp_path: Path) -> tuple[Path, str]:
    module = _load_module()
    apk = tmp_path / 'app-x86_64-debug.apk'
    apk.write_bytes(b'fixture-verifier-apk')
    return apk, module._sha256_file(apk)


def _device_report(path: Path, *, apk_path: Path, apk_sha256: str) -> Path:
    return _write_json(
        path,
        {
            'schema_version': 'xaman-testnet-device-trial/v1',
            'task_id': 'PORTAL-CXTP-121',
            'artifact_cid': _artifact_cid('a'),
            'run_id': 'device-fixture',
            'overall_status': 'executed_with_boundaries',
            'security_decision': 'TESTNET_DEVICE_TRIAL_EXECUTED_JS_FIREBASE_STUBBED_NOT_PRODUCTION_EVIDENCE',
            'xaman_commit': '942f43876265a7af44f233288ad2b1d00841d5fa',
            'trial_scope': {
                'network': 'XRPL_TESTNET',
                'network_id': 1,
                'production_usable': False,
                'device_trial_label': 'firebase_js_stubbed_only',
                'full_firebase_disabled_label_blocked': True,
            },
            'verifier_artifact': {
                'apk': {
                    'path': apk_path.as_posix(),
                    'present': True,
                    'sha256': apk_sha256,
                    'size_bytes': apk_path.stat().st_size,
                },
                'expected_apk_sha256': apk_sha256,
                'digest_matches_telemetry_report': True,
            },
            'device_profile': {
                'isolated_android_emulator': {
                    'present': True,
                    'profile_name': 'ipfs_xaman_api34_testnet.avd',
                    'path': (path.parent / 'ipfs_xaman_api34_testnet.avd').as_posix(),
                    'selected_file_records': {
                        'config.ini': {
                            'present': True,
                            'sha256': _fixture_digest('avd', 'config.ini'),
                            'size_bytes': 16,
                        }
                    },
                }
            },
            'approved_non_production_wallet_flow': {
                'fresh_testnet_credentials': {
                    'fresh_account_created': True,
                    'imported_account': False,
                    'production_account': False,
                    'account_material_recorded': False,
                    'boundary': 'testnet_only_no_imported_or_persisted_account_material',
                }
            },
        },
    )


def _network_report(path: Path, *, apk_sha256: str) -> Path:
    return _write_json(
        path,
        {
            'schema_version': 'xaman-testnet-network-selection/v1',
            'task_id': 'PORTAL-CXTP-125',
            'artifact_cid': _artifact_cid('b'),
            'run_id': 'network-fixture',
            'overall_status': 'verified',
            'security_decision': 'TESTNET_NETWORK_SELECTION_VERIFIED_NOT_PRODUCTION_EVIDENCE',
            'xaman_commit': '942f43876265a7af44f233288ad2b1d00841d5fa',
            'build_provenance_sha256': apk_sha256,
            'selection': {
                'network_key': 'TESTNET',
                'event_categories': [
                    'fresh_emulator_profile',
                    'fresh_testnet_account_boundary',
                    'fresh_testnet_account_created',
                    'xaman_network_selected',
                    'xrpl_server_info_observed',
                ],
            },
            'endpoint_allow_list_decision': {
                'allowed': True,
                'matched_endpoint_key': 'ripple_altnet_testnet',
                'matched_endpoint_sha256': 'a81289bc29208d10634e2b0c40a94ec0c664f0c3bb1574d742ce8054b7f9abca',
                'allow_list_version': 'xrpl-public-testnet-2026-07-10',
                'allowed_endpoint_count': 2,
            },
            'xrpl_server_info_binding': {
                'request_category': 'xrpl_server_info',
                'request_sha256': '6a1a5cf3644551cf735838bfa1ada32fe420c979bac41dd497fbc13f229070c3',
                'response_sha256': _fixture_digest('server-info', 'response'),
                'network_id': 1,
                'network_id_verified': True,
                'raw_request_body_recorded': False,
                'raw_response_recorded': False,
            },
            'fresh_account_boundary': {
                'fresh_account_created': True,
                'imported_account': False,
                'production_account': False,
                'account_material_recorded': False,
            },
        },
    )


def _native_report(path: Path) -> Path:
    return _write_json(
        path,
        {
            'schema_version': 'xaman-native-firebase-boundary/v1',
            'task_id': 'PORTAL-CXTP-126',
            'artifact_cid': _artifact_cid('c'),
            'run_id': 'native-fixture',
            'overall_status': 'blocked',
            'security_decision': 'BLOCK_TESTNET_FULL_FIREBASE_DISABLED_LABEL_NATIVE_FIREBASE_PACKAGED',
            'xaman_commit': '942f43876265a7af44f233288ad2b1d00841d5fa',
            'native_firebase_fully_disabled': False,
            'native_firebase_evidence_present': True,
            'native_packaging_present': True,
            'device_trial_label_allowed': 'firebase_js_stubbed_only',
            'blockers': [{'code': 'FIREBASE_DEX_CLASSES_PRESENT'}],
        },
    )


def _event(ordinal: int, action: str, outcome: str = 'observed') -> dict:
    module = _load_module()
    return {
        'ordinal': ordinal,
        'action': action,
        'category': module.ACTION_CATEGORIES[action],
        'outcome': outcome,
        'source_kind': 'reviewed_ui',
        'source_sha256': _fixture_digest('source', ordinal, action, outcome),
        'redaction_sha256': _fixture_digest('redaction', ordinal, action, outcome),
        'raw_material_recorded': False,
    }


def _lifecycle_evidence(path: Path, *, omit_gap_for: str | None = None, extra: dict | None = None) -> Path:
    observed = [
        ('payload_intake', 'accepted'),
        ('review', 'reviewed'),
        ('auth_decision', 'authorized'),
        ('signing_decision', 'signed'),
        ('submit_attempt', 'submitted'),
        ('submit_result', 'succeeded'),
        ('reconnect', 'reconnected'),
        ('network_switch', 'switched_to_testnet'),
    ]
    gaps = [
        {
            'action': action,
            'reason_code': 'not_exercised_in_reviewed_trial',
            'reviewer_note_sha256': _fixture_digest('gap', action, digest),
        }
        for action, digest in [('decline', 'a'), ('cancel', 'b'), ('expiry', 'c')]
        if action != omit_gap_for
    ]
    payload = {
        'schema_version': 'xaman-testnet-transaction-lifecycle-evidence/v1',
        'evidence_type': 'reviewed_operator_trial',
        'reviewed_at_utc': '2026-07-10T23:00:00Z',
        'fresh_emulator_profile': True,
        'network_key': 'TESTNET',
        'fresh_account_boundary': {
            'fresh_account_created': True,
            'imported_account': False,
            'production_account': False,
            'account_material_recorded': False,
        },
        'lifecycle_events': [
            _event(index, action, outcome) for index, (action, outcome) in enumerate(observed, start=1)
        ],
        'coverage_gaps': gaps,
    }
    if extra:
        payload.update(extra)
    return _write_json(path, payload)


def _fixture_inputs(tmp_path: Path, *, lifecycle_extra: dict | None = None, omit_gap_for: str | None = None) -> dict:
    apk_path, apk_sha256 = _apk(tmp_path)
    return {
        'lifecycle_evidence_path': _lifecycle_evidence(
            tmp_path / 'lifecycle-evidence.json',
            extra=lifecycle_extra,
            omit_gap_for=omit_gap_for,
        ),
        'device_report_path': _device_report(tmp_path / 'device.json', apk_path=apk_path, apk_sha256=apk_sha256),
        'network_report_path': _network_report(tmp_path / 'network.json', apk_sha256=apk_sha256),
        'native_firebase_report_path': _native_report(tmp_path / 'native.json'),
        'apk_path': apk_path,
        'generated_at_utc': '2026-07-10T23:30:00Z',
    }


def test_build_report_records_redacted_lifecycle_with_explicit_gaps(tmp_path: Path) -> None:
    module = _load_module()

    report = module.build_report(**_fixture_inputs(tmp_path))

    assert report['schema_version'] == 'xaman-testnet-transaction-lifecycle-trial/v1'
    assert report['task_id'] == 'PORTAL-CXTP-130'
    assert report['overall_status'] == 'executed_with_coverage_gaps'
    assert report['blocking_gaps'] == []
    assert report['trial_scope']['network'] == 'XRPL_TESTNET'
    assert report['verifier_artifact']['digest_matches_device_report'] is True
    assert report['testnet_network_binding']['endpoint_allow_list_decision']['matched_endpoint_key'] == (
        'ripple_altnet_testnet'
    )
    assert report['testnet_network_binding']['xrpl_server_info_binding']['response_sha256'] == _fixture_digest(
        'server-info',
        'response',
    )
    assert report['device_profile']['fresh_testnet_account_boundary']['production_account'] is False
    assert {gap['action'] for gap in report['coverage_gaps']} == {'decline', 'cancel', 'expiry'}
    assert report['transaction_lifecycle']['observed_action_count'] == 8
    assert report['transaction_lifecycle']['coverage_gap_count'] == 3
    assert {item['action'] for item in report['transaction_lifecycle']['action_coverage']} == set(
        module.REQUIRED_ACTIONS
    )
    rendered = json.dumps(report, sort_keys=True)
    assert 'wss://' not in rendered
    assert str(tmp_path) not in rendered
    assert '"path":' not in rendered
    assert report['verifier_artifact']['apk']['path_label'] == 'app-x86_64-debug.apk'
    assert report['verifier_artifact']['device_report_apk']['path_label'] == 'app-x86_64-debug.apk'
    assert report['device_profile']['isolated_android_emulator']['path_label'] == 'ipfs_xaman_api34_testnet.avd'
    assert report['redaction_boundary']['redaction_failure'] is False
    assert report['artifact_cid'].startswith('sha256:')


def test_build_report_fails_closed_when_required_action_has_no_event_or_gap(tmp_path: Path) -> None:
    module = _load_module()

    report = module.build_report(**_fixture_inputs(tmp_path, omit_gap_for='cancel'))

    assert report['overall_status'] == 'blocked'
    assert report['security_decision'] == 'BLOCK_TESTNET_TRANSACTION_LIFECYCLE_EVIDENCE_FAILURE'
    assert {'REQUIRED_LIFECYCLE_ACTION_UNACCOUNTED_FOR'} <= {gap['code'] for gap in report['blocking_gaps']}


def test_build_report_requires_reviewed_event_and_gap_digests(tmp_path: Path) -> None:
    module = _load_module()
    inputs = _fixture_inputs(tmp_path)
    lifecycle_path = Path(inputs['lifecycle_evidence_path'])
    lifecycle = json.loads(lifecycle_path.read_text(encoding='utf-8'))
    lifecycle['lifecycle_events'][0].pop('source_sha256')
    lifecycle['lifecycle_events'][1].pop('redaction_sha256')
    lifecycle['coverage_gaps'][0].pop('reviewer_note_sha256')
    _write_json(lifecycle_path, lifecycle)

    report = module.build_report(**inputs)

    assert report['overall_status'] == 'blocked'
    blocker_reasons = {
        blocker.get('reason')
        for blocker in report['blocking_gaps']
        if blocker.get('code') in {'LIFECYCLE_EVENT_INVALID', 'COVERAGE_GAP_INVALID'}
    }
    assert 'lifecycle event source_sha256 must be a lowercase SHA-256 digest' in blocker_reasons
    assert 'lifecycle event redaction_sha256 must be a lowercase SHA-256 digest' in blocker_reasons
    assert 'coverage gap reviewer_note_sha256 must be a lowercase SHA-256 digest' in blocker_reasons


def test_build_report_requires_review_timestamp_and_contiguous_event_ordinals(tmp_path: Path) -> None:
    module = _load_module()
    inputs = _fixture_inputs(tmp_path)
    lifecycle_path = Path(inputs['lifecycle_evidence_path'])
    lifecycle = json.loads(lifecycle_path.read_text(encoding='utf-8'))
    lifecycle.pop('reviewed_at_utc')
    lifecycle['lifecycle_events'][1]['ordinal'] = 9
    _write_json(lifecycle_path, lifecycle)

    report = module.build_report(**inputs)

    assert report['overall_status'] == 'blocked'
    assert {'LIFECYCLE_REVIEWED_AT_MISSING', 'LIFECYCLE_EVENT_ORDINAL_SEQUENCE_INVALID'} <= {
        gap['code'] for gap in report['blocking_gaps']
    }


def test_build_report_rejects_placeholder_reviewed_digests(tmp_path: Path) -> None:
    module = _load_module()
    inputs = _fixture_inputs(tmp_path)
    lifecycle_path = Path(inputs['lifecycle_evidence_path'])
    lifecycle = json.loads(lifecycle_path.read_text(encoding='utf-8'))
    lifecycle['lifecycle_events'][0]['source_sha256'] = '1' * 64
    lifecycle['lifecycle_events'][1]['redaction_sha256'] = 'a' * 64
    lifecycle['coverage_gaps'][0]['reviewer_note_sha256'] = 'f' * 64
    _write_json(lifecycle_path, lifecycle)

    report = module.build_report(**inputs)

    assert report['overall_status'] == 'blocked'
    blocker_reasons = {
        blocker.get('reason')
        for blocker in report['blocking_gaps']
        if blocker.get('code') in {'LIFECYCLE_EVENT_INVALID', 'COVERAGE_GAP_INVALID'}
    }
    assert 'lifecycle event source_sha256 must not be a placeholder digest' in blocker_reasons
    assert 'lifecycle event redaction_sha256 must not be a placeholder digest' in blocker_reasons
    assert 'coverage gap reviewer_note_sha256 must not be a placeholder digest' in blocker_reasons


def test_build_report_rejects_action_outcome_mismatch(tmp_path: Path) -> None:
    module = _load_module()
    inputs = _fixture_inputs(tmp_path)
    lifecycle_path = Path(inputs['lifecycle_evidence_path'])
    lifecycle = json.loads(lifecycle_path.read_text(encoding='utf-8'))
    lifecycle['lifecycle_events'][0]['outcome'] = 'signed'
    _write_json(lifecycle_path, lifecycle)

    report = module.build_report(**inputs)

    assert report['overall_status'] == 'blocked'
    assert {
        "lifecycle event outcome 'signed' is not valid for action 'payload_intake'"
    } <= {
        blocker.get('reason')
        for blocker in report['blocking_gaps']
        if blocker.get('code') == 'LIFECYCLE_EVENT_INVALID'
    }


def test_build_report_rejects_sensitive_lifecycle_evidence(tmp_path: Path) -> None:
    module = _load_module()

    with pytest.raises(module.TransactionTrialError, match='raw endpoint URL'):
        module.build_report(
            **_fixture_inputs(
                tmp_path,
                lifecycle_extra={'reviewer_note': 'selected wss://s.altnet.rippletest.net:51233'},
            )
        )
    with pytest.raises(module.TransactionTrialError, match='raw endpoint URL'):
        module.build_report(
            **_fixture_inputs(
                tmp_path,
                lifecycle_extra={'reviewer_note': 'selected https://s.altnet.rippletest.net:51234'},
            )
        )
    with pytest.raises(module.TransactionTrialError, match='raw XRPL transaction JSON'):
        module.build_report(
            **_fixture_inputs(
                tmp_path,
                lifecycle_extra={'reviewer_note': '{"TransactionType":"Payment","Destination":"redacted"}'},
            )
        )
    with pytest.raises(module.TransactionTrialError, match='raw payload or transaction blob JSON'):
        module.build_report(
            **_fixture_inputs(
                tmp_path,
                lifecycle_extra={'reviewer_note': '{"payload":{"tx_json":"redacted"}}'},
            )
        )
    with pytest.raises(module.TransactionTrialError, match='raw payload or transaction blob JSON'):
        module.build_report(
            **_fixture_inputs(
                tmp_path,
                lifecycle_extra={'reviewer_note': '{"signed_blob":"redacted"}'},
            )
        )
    with pytest.raises(module.TransactionTrialError, match="forbidden key 'payload'"):
        module.build_report(
            **_fixture_inputs(
                tmp_path,
                lifecycle_extra={'payload': {'amount': 'redacted-but-wrong-field'}},
            )
        )
    with pytest.raises(module.TransactionTrialError, match="forbidden key 'account_address_sha256'"):
        module.build_report(
            **_fixture_inputs(
                tmp_path,
                lifecycle_extra={'account_address_sha256': 'a' * 64},
            )
        )
    with pytest.raises(module.TransactionTrialError, match="forbidden key 'seed_hash'"):
        module.build_report(
            **_fixture_inputs(
                tmp_path,
                lifecycle_extra={'seed_hash': 'b' * 64},
            )
        )
    with pytest.raises(module.TransactionTrialError, match="forbidden key 'transaction_blob_digest'"):
        module.build_report(
            **_fixture_inputs(
                tmp_path,
                lifecycle_extra={'transaction_blob_digest': 'c' * 64},
            )
        )
    with pytest.raises(module.TransactionTrialError, match="forbidden key 'signed_blob_sha256'"):
        module.build_report(
            **_fixture_inputs(
                tmp_path,
                lifecycle_extra={'signed_blob_sha256': _fixture_digest('signed-blob')},
            )
        )
    with pytest.raises(module.TransactionTrialError, match="forbidden key 'blob'"):
        module.build_report(
            **_fixture_inputs(
                tmp_path,
                lifecycle_extra={'blob': 'redacted-but-wrong-field'},
            )
        )
    with pytest.raises(module.TransactionTrialError, match="forbidden key 'wallet_address_sha256'"):
        module.build_report(
            **_fixture_inputs(
                tmp_path,
                lifecycle_extra={'wallet_address_sha256': _fixture_digest('wallet-address')},
            )
        )
    with pytest.raises(module.TransactionTrialError, match="forbidden key 'account_material_sha256'"):
        module.build_report(
            **_fixture_inputs(
                tmp_path,
                lifecycle_extra={'account_material_sha256': _fixture_digest('account-material')},
            )
        )


def test_build_report_blocks_unknown_lifecycle_schema_fields(tmp_path: Path) -> None:
    module = _load_module()
    inputs = _fixture_inputs(tmp_path)
    lifecycle_path = Path(inputs['lifecycle_evidence_path'])
    lifecycle = json.loads(lifecycle_path.read_text(encoding='utf-8'))
    lifecycle['operator_comment_sha256'] = _fixture_digest('unknown-top-level')
    lifecycle['lifecycle_events'][0]['reviewer_alias'] = 'reviewed-ui-operator'
    lifecycle['coverage_gaps'][0]['note_category'] = 'negative-path-not-run'
    _write_json(lifecycle_path, lifecycle)

    report = module.build_report(**inputs)

    assert report['overall_status'] == 'blocked'
    assert {'LIFECYCLE_EVIDENCE_UNKNOWN_FIELDS'} <= {gap['code'] for gap in report['blocking_gaps']}
    blocker_reasons = {
        blocker.get('reason')
        for blocker in report['blocking_gaps']
        if blocker.get('code') in {'LIFECYCLE_EVENT_INVALID', 'COVERAGE_GAP_INVALID'}
    }
    assert "lifecycle event contains unknown keys: ['reviewer_alias']" in blocker_reasons
    assert "coverage gap contains unknown keys: ['note_category']" in blocker_reasons


def test_build_report_blocks_lifecycle_schema_mismatch(tmp_path: Path) -> None:
    module = _load_module()
    inputs = _fixture_inputs(tmp_path)
    lifecycle_path = Path(inputs['lifecycle_evidence_path'])
    lifecycle = json.loads(lifecycle_path.read_text(encoding='utf-8'))
    lifecycle['schema_version'] = 'xaman-testnet-transaction-lifecycle-evidence/v0'
    _write_json(lifecycle_path, lifecycle)

    report = module.build_report(**inputs)

    assert report['overall_status'] == 'blocked'
    assert report['security_decision'] == 'BLOCK_TESTNET_TRANSACTION_LIFECYCLE_EVIDENCE_FAILURE'
    assert {'LIFECYCLE_EVIDENCE_SCHEMA_MISMATCH'} <= {gap['code'] for gap in report['blocking_gaps']}


def test_build_report_rejects_sensitive_material_in_json_keys(tmp_path: Path) -> None:
    module = _load_module()

    with pytest.raises(module.TransactionTrialError, match='raw endpoint URL'):
        module.build_report(
            **_fixture_inputs(
                tmp_path,
                lifecycle_extra={'reviewed_notes': {'wss://s.altnet.rippletest.net:51233': 'redacted'}},
            )
        )
    with pytest.raises(module.TransactionTrialError, match='account address'):
        module.build_report(
            **_fixture_inputs(
                tmp_path,
                lifecycle_extra={'reviewed_notes': {'rHb9CJAWyB4rj91VRWn96DkukG4bwdtyTh': 'redacted'}},
            )
        )
    for raw_transaction_key in ('TransactionType', 'Destination', 'SigningPubKey', 'Account'):
        with pytest.raises(module.TransactionTrialError, match='raw_xrpl_transaction_field'):
            module.build_report(
                **_fixture_inputs(
                    tmp_path,
                    lifecycle_extra={'reviewed_notes': {raw_transaction_key: 'redacted'}},
                )
            )


def test_build_report_blocks_production_account_boundary(tmp_path: Path) -> None:
    module = _load_module()
    inputs = _fixture_inputs(
        tmp_path,
        lifecycle_extra={
            'fresh_account_boundary': {
                'fresh_account_created': True,
                'imported_account': False,
                'production_account': True,
                'account_material_recorded': False,
            }
        },
    )

    report = module.build_report(**inputs)

    assert report['overall_status'] == 'blocked'
    assert {'PRODUCTION_ACCOUNT_BOUNDARY_VIOLATED'} <= {gap['code'] for gap in report['blocking_gaps']}


def test_build_report_blocks_unknown_fresh_account_boundary_fields(tmp_path: Path) -> None:
    module = _load_module()
    inputs = _fixture_inputs(
        tmp_path,
        lifecycle_extra={
            'fresh_account_boundary': {
                'fresh_account_created': True,
                'imported_account': False,
                'production_account': False,
                'account_material_recorded': False,
                'reused_account_state': False,
            }
        },
    )

    report = module.build_report(**inputs)

    assert report['overall_status'] == 'blocked'
    blockers = {
        gap['code']: gap
        for gap in report['blocking_gaps']
        if gap['code'] == 'FRESH_ACCOUNT_BOUNDARY_UNKNOWN_FIELDS'
    }
    assert blockers['FRESH_ACCOUNT_BOUNDARY_UNKNOWN_FIELDS']['fields'] == ['reused_account_state']


def test_build_report_blocks_dependency_digest_and_network_boundary_failures(tmp_path: Path) -> None:
    module = _load_module()
    inputs = _fixture_inputs(tmp_path)
    network_report = json.loads(Path(inputs['network_report_path']).read_text(encoding='utf-8'))
    network_report['build_provenance_sha256'] = '0' * 64
    network_report['xrpl_server_info_binding']['request_sha256'] = 'not-a-digest'
    network_report['fresh_account_boundary']['production_account'] = True
    _write_json(Path(inputs['network_report_path']), network_report)

    report = module.build_report(**inputs)

    assert report['overall_status'] == 'blocked'
    assert {
        'NETWORK_SELECTION_APK_DIGEST_MISMATCH',
        'SERVER_INFO_REQUEST_DIGEST_MISSING',
        'NETWORK_FRESH_ACCOUNT_BOUNDARY_VIOLATED',
    } <= {gap['code'] for gap in report['blocking_gaps']}


def test_build_report_blocks_missing_network_selection_event_categories(tmp_path: Path) -> None:
    module = _load_module()
    inputs = _fixture_inputs(tmp_path)
    network_report = json.loads(Path(inputs['network_report_path']).read_text(encoding='utf-8'))
    network_report['selection']['event_categories'] = [
        'fresh_emulator_profile',
        'fresh_testnet_account_boundary',
    ]
    _write_json(Path(inputs['network_report_path']), network_report)

    report = module.build_report(**inputs)

    assert report['overall_status'] == 'blocked'
    blockers = {
        gap['code']: gap
        for gap in report['blocking_gaps']
        if gap['code'] == 'NETWORK_SELECTION_REQUIRED_EVENT_CATEGORIES_MISSING'
    }
    assert set(blockers['NETWORK_SELECTION_REQUIRED_EVENT_CATEGORIES_MISSING']['event_categories']) == {
        'fresh_testnet_account_created',
        'xaman_network_selected',
        'xrpl_server_info_observed',
    }


def test_build_report_blocks_malformed_endpoint_allow_list_metadata(tmp_path: Path) -> None:
    module = _load_module()
    inputs = _fixture_inputs(tmp_path)
    network_report = json.loads(Path(inputs['network_report_path']).read_text(encoding='utf-8'))
    network_report['endpoint_allow_list_decision']['matched_endpoint_key'] = 'raw url not allowed'
    network_report['endpoint_allow_list_decision']['allow_list_version'] = '2026/07/10'
    network_report['endpoint_allow_list_decision']['allowed_endpoint_count'] = 0
    _write_json(Path(inputs['network_report_path']), network_report)

    report = module.build_report(**inputs)

    assert report['overall_status'] == 'blocked'
    assert {
        'TESTNET_ENDPOINT_KEY_MISSING',
        'TESTNET_ENDPOINT_ALLOW_LIST_VERSION_INVALID',
        'TESTNET_ENDPOINT_ALLOW_LIST_COUNT_INVALID',
    } <= {gap['code'] for gap in report['blocking_gaps']}


def test_build_report_blocks_dependency_security_decision_mismatches(tmp_path: Path) -> None:
    module = _load_module()
    inputs = _fixture_inputs(tmp_path)
    device_report = json.loads(Path(inputs['device_report_path']).read_text(encoding='utf-8'))
    network_report = json.loads(Path(inputs['network_report_path']).read_text(encoding='utf-8'))
    native_report = json.loads(Path(inputs['native_firebase_report_path']).read_text(encoding='utf-8'))
    device_report['security_decision'] = 'BLOCK_TESTNET_DEVICE_TRIAL_EVIDENCE_FAILURE'
    network_report['security_decision'] = 'BLOCK_TESTNET_NETWORK_SELECTION_EVIDENCE_FAILURE'
    native_report['security_decision'] = 'TESTNET_NATIVE_FIREBASE_REMOVAL_VERIFIED'
    _write_json(Path(inputs['device_report_path']), device_report)
    _write_json(Path(inputs['network_report_path']), network_report)
    _write_json(Path(inputs['native_firebase_report_path']), native_report)

    report = module.build_report(**inputs)

    assert report['overall_status'] == 'blocked'
    assert {
        'DEVICE_TRIAL_SECURITY_DECISION_INVALID',
        'TESTNET_NETWORK_SELECTION_SECURITY_DECISION_INVALID',
        'NATIVE_FIREBASE_PACKAGED_SECURITY_DECISION_MISMATCH',
    } <= {gap['code'] for gap in report['blocking_gaps']}


def test_build_report_blocks_placeholder_dependency_digests(tmp_path: Path) -> None:
    module = _load_module()
    inputs = _fixture_inputs(tmp_path)
    device_report = json.loads(Path(inputs['device_report_path']).read_text(encoding='utf-8'))
    network_report = json.loads(Path(inputs['network_report_path']).read_text(encoding='utf-8'))
    device_report['device_profile']['isolated_android_emulator']['selected_file_records']['config.ini'][
        'sha256'
    ] = '1' * 64
    network_report['endpoint_allow_list_decision']['matched_endpoint_sha256'] = 'a' * 64
    network_report['xrpl_server_info_binding']['response_sha256'] = 'd' * 64
    _write_json(Path(inputs['device_report_path']), device_report)
    _write_json(Path(inputs['network_report_path']), network_report)

    report = module.build_report(**inputs)

    assert report['overall_status'] == 'blocked'
    assert {
        'EMULATOR_PROFILE_FILE_DIGEST_PLACEHOLDER',
        'TESTNET_ENDPOINT_DIGEST_PLACEHOLDER',
        'SERVER_INFO_RESPONSE_DIGEST_PLACEHOLDER',
    } <= {gap['code'] for gap in report['blocking_gaps']}


def test_build_report_blocks_missing_verifier_apk(tmp_path: Path) -> None:
    module = _load_module()
    inputs = _fixture_inputs(tmp_path)
    Path(inputs['apk_path']).unlink()

    report = module.build_report(**inputs)

    assert report['overall_status'] == 'blocked'
    assert {'VERIFIER_APK_MISSING'} <= {gap['code'] for gap in report['blocking_gaps']}


def test_build_report_blocks_missing_dependency_report(tmp_path: Path) -> None:
    module = _load_module()
    inputs = _fixture_inputs(tmp_path)
    Path(inputs['device_report_path']).unlink()

    report = module.build_report(**inputs)

    assert report['overall_status'] == 'blocked'
    assert {'TESTNET_DEVICE_TRIAL_REPORT_MISSING', 'DEVICE_VERIFIER_APK_DIGEST_MISSING'} <= {
        gap['code'] for gap in report['blocking_gaps']
    }


def test_build_report_blocks_dependency_artifact_cid_mismatch(tmp_path: Path) -> None:
    module = _load_module()
    inputs = _fixture_inputs(tmp_path)
    device_report = json.loads(Path(inputs['device_report_path']).read_text(encoding='utf-8'))
    device_report['artifact_cid'] = _artifact_cid('f')
    Path(inputs['device_report_path']).write_text(json.dumps(device_report, sort_keys=True), encoding='utf-8')

    report = module.build_report(**inputs)

    assert report['overall_status'] == 'blocked'
    assert {'TESTNET_DEVICE_TRIAL_REPORT_ARTIFACT_CID_MISMATCH'} <= {
        gap['code'] for gap in report['blocking_gaps']
    }


def test_build_report_blocks_native_firebase_packaging_mislabeled_fully_disabled(tmp_path: Path) -> None:
    module = _load_module()
    inputs = _fixture_inputs(tmp_path)
    native_report = json.loads(Path(inputs['native_firebase_report_path']).read_text(encoding='utf-8'))
    native_report['native_packaging_present'] = True
    native_report['native_firebase_fully_disabled'] = True
    native_report['device_trial_label_allowed'] = 'firebase_disabled'
    _write_json(Path(inputs['native_firebase_report_path']), native_report)

    report = module.build_report(**inputs)

    assert report['overall_status'] == 'blocked'
    assert {'NATIVE_FIREBASE_PACKAGED_APK_MISLABELED_FULLY_DISABLED'} <= {
        gap['code'] for gap in report['blocking_gaps']
    }


def test_build_report_blocks_unknown_native_firebase_boundary_status(tmp_path: Path) -> None:
    module = _load_module()
    inputs = _fixture_inputs(tmp_path)
    native_report = json.loads(Path(inputs['native_firebase_report_path']).read_text(encoding='utf-8'))
    native_report.pop('native_packaging_present')
    native_report.pop('native_firebase_fully_disabled')
    _write_json(Path(inputs['native_firebase_report_path']), native_report)

    report = module.build_report(**inputs)

    assert report['overall_status'] == 'blocked'
    assert {'NATIVE_FIREBASE_PACKAGING_STATUS_UNKNOWN', 'NATIVE_FIREBASE_DISABLED_STATUS_UNKNOWN'} <= {
        gap['code'] for gap in report['blocking_gaps']
    }


def test_build_report_blocks_invalid_native_firebase_boundary_status(tmp_path: Path) -> None:
    module = _load_module()
    inputs = _fixture_inputs(tmp_path)
    native_report = json.loads(Path(inputs['native_firebase_report_path']).read_text(encoding='utf-8'))
    native_report['overall_status'] = 'unknown'
    _write_json(Path(inputs['native_firebase_report_path']), native_report)

    report = module.build_report(**inputs)

    assert report['overall_status'] == 'blocked'
    assert {'NATIVE_FIREBASE_BOUNDARY_STATUS_INVALID'} <= {
        gap['code'] for gap in report['blocking_gaps']
    }


def test_build_report_blocks_native_firebase_disabled_status_conflict(tmp_path: Path) -> None:
    module = _load_module()
    inputs = _fixture_inputs(tmp_path)
    native_report = json.loads(Path(inputs['native_firebase_report_path']).read_text(encoding='utf-8'))
    native_report['overall_status'] = 'blocked'
    native_report['native_packaging_present'] = False
    native_report['native_firebase_fully_disabled'] = True
    native_report['device_trial_label_allowed'] = 'firebase_disabled'
    _write_json(Path(inputs['native_firebase_report_path']), native_report)

    report = module.build_report(**inputs)

    assert report['overall_status'] == 'blocked'
    assert {'NATIVE_FIREBASE_DISABLED_STATUS_CONFLICT'} <= {
        gap['code'] for gap in report['blocking_gaps']
    }


def test_build_report_blocks_native_firebase_packaging_label_only_mismatch(tmp_path: Path) -> None:
    module = _load_module()
    inputs = _fixture_inputs(tmp_path)
    native_report = json.loads(Path(inputs['native_firebase_report_path']).read_text(encoding='utf-8'))
    native_report['native_packaging_present'] = True
    native_report['native_firebase_fully_disabled'] = False
    native_report['device_trial_label_allowed'] = 'firebase_disabled'
    _write_json(Path(inputs['native_firebase_report_path']), native_report)

    report = module.build_report(**inputs)

    assert report['overall_status'] == 'blocked'
    assert {'NATIVE_FIREBASE_PACKAGED_APK_MISLABELED_FULLY_DISABLED'} <= {
        gap['code'] for gap in report['blocking_gaps']
    }


def test_checked_in_transaction_trial_artifact_preserves_required_boundaries() -> None:
    module = _load_module()
    report = json.loads(ARTIFACT_PATH.read_text(encoding='utf-8'))
    evidence_raw = EVIDENCE_PATH.read_bytes()
    evidence = json.loads(evidence_raw.decode('utf-8'))
    doc = DOC_PATH.read_text(encoding='utf-8')

    assert report['schema_version'] == 'xaman-testnet-transaction-lifecycle-trial/v1'
    assert report['task_id'] == 'PORTAL-CXTP-130'
    assert EVIDENCE_PATH.exists()
    assert evidence['schema_version'] == module.EVIDENCE_SCHEMA_VERSION
    module._assert_no_sensitive_material(evidence, context='checked-in transaction lifecycle evidence')
    assert report['evidence_inputs']['lifecycle_evidence_sha256'] == module._sha256_bytes(evidence_raw)
    assert report['xaman_commit'] == module.PINNED_XAMAN_COMMIT
    assert report['overall_status'] in {'executed_complete', 'executed_with_coverage_gaps'}
    assert report['blocking_gaps'] == []
    assert report['trial_scope']['network'] == 'XRPL_TESTNET'
    assert report['trial_scope']['production_usable'] is False
    assert report['verifier_artifact']['apk_sha256']
    assert report['device_profile']['fresh_testnet_account_boundary']['production_account'] is False
    assert report['testnet_network_binding']['endpoint_allow_list_decision']['allowed'] is True
    assert report['testnet_network_binding']['endpoint_allow_list_decision']['matched_endpoint_key']
    assert report['testnet_network_binding']['xrpl_server_info_binding']['network_id_verified'] is True
    assert report['testnet_network_binding']['xrpl_server_info_binding']['response_sha256']
    assert report['redaction_boundary']['redaction_failure'] is False
    assert report['redaction_boundary']['account_addresses_recorded'] is False
    assert report['redaction_boundary']['seeds_recorded'] is False
    assert report['redaction_boundary']['credentials_recorded'] is False
    assert report['redaction_boundary']['raw_payloads_recorded'] is False
    assert report['redaction_boundary']['transaction_blobs_recorded'] is False
    assert report['redaction_boundary']['raw_xrpl_endpoint_recorded'] is False
    module._assert_report_redaction_boundary(report)
    assert {item['action'] for item in report['transaction_lifecycle']['action_coverage']} == set(
        module.REQUIRED_ACTIONS
    )
    assert {gap['action'] for gap in report['coverage_gaps']} == {
        item['action']
        for item in report['transaction_lifecycle']['action_coverage']
        if item['status'] == 'not_observed'
    }
    assert 'fully Firebase-disabled' in doc
    rendered = json.dumps(report, sort_keys=True)
    assert 'wss://' not in rendered
    assert 'http://' not in rendered
    assert 'https://' not in rendered
    assert '/home/barberb/' not in rendered
    assert '"path":' not in rendered
    assert report['verifier_artifact']['apk']['path_label'] == 'app-x86_64-debug.apk'
    assert report['device_profile']['isolated_android_emulator']['path_label'] == 'ipfs_xaman_api34_testnet.avd'
    assert not module.XRPL_ADDRESS_RE.search(rendered)
    assert not module.XRPL_XADDRESS_RE.search(rendered)
    assert not module.XRPL_SEED_RE.search(rendered)
    assert not module.JWT_RE.search(rendered)
    assert not module.BEARER_TOKEN_RE.search(rendered)
    canonical = json.dumps(
        {key: value for key, value in report.items() if key != 'artifact_cid'},
        sort_keys=True,
        separators=(',', ':'),
    ).encode('utf-8')
    assert report['artifact_cid'] == 'sha256:' + module._sha256_bytes(canonical)


def test_cli_writes_regenerated_report_with_fixture_inputs(tmp_path: Path) -> None:
    module = _load_module()
    inputs = _fixture_inputs(tmp_path)
    out_path = tmp_path / 'trial-report.json'

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT_PATH),
            '--lifecycle-evidence',
            str(inputs['lifecycle_evidence_path']),
            '--device-report',
            str(inputs['device_report_path']),
            '--network-report',
            str(inputs['network_report_path']),
            '--native-firebase-report',
            str(inputs['native_firebase_report_path']),
            '--apk',
            str(inputs['apk_path']),
            '--generated-at-utc',
            inputs['generated_at_utc'],
            '--out',
            str(out_path),
        ],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    summary = json.loads(result.stdout)
    written = json.loads(out_path.read_text(encoding='utf-8'))
    assert summary['out'] == out_path.as_posix()
    assert summary['overall_status'] == 'executed_with_coverage_gaps'
    assert written['overall_status'] == 'executed_with_coverage_gaps'
    assert written['blocking_gaps'] == []
    assert written['artifact_cid'] == summary['artifact_cid']
    module._assert_report_redaction_boundary(written)
