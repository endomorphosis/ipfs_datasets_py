"""Tests for PORTAL-CXTP-121 Xaman public-Testnet device trial."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys

import pytest


REPO_ROOT = Path(__file__).resolve().parents[4]
SCRIPT_PATH = (
    REPO_ROOT
    / 'scripts'
    / 'ops'
    / 'security_verification'
    / 'capture_xaman_testnet_device_trial.py'
)
ARTIFACT_PATH = (
    REPO_ROOT
    / 'security_ir_artifacts'
    / 'corpora'
    / 'xaman-app'
    / 'runtime'
    / 'testnet-device-trial-report.json'
)


def _load_module():
    spec = importlib.util.spec_from_file_location('capture_xaman_testnet_device_trial', SCRIPT_PATH)
    if spec is None or spec.loader is None:  # pragma: no cover
        raise AssertionError('failed to load device-trial capture script')
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _write_json(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, sort_keys=True), encoding='utf-8')
    return path


def _artifact_cid(prefix: str = 'a') -> str:
    return 'sha256:' + (prefix * 64)


def _build_manifest(path: Path) -> Path:
    return _write_json(
        path,
        {
            'schema_version': 'xaman-firebase-disabled-testnet-build/v1',
            'task_id': 'PORTAL-CXTP-119',
            'artifact_cid': _artifact_cid('a'),
            'firebase_mode': 'disabled_by_external_gradle_and_metro_overrides',
            'ledger_network': 'testnet_required',
            'runtime_constraints': {
                'android_build_variant': 'debug',
                'firebase_gradle_tasks_disabled': True,
                'firebase_js_modules_stubbed': [
                    '@react-native-firebase/analytics',
                    '@react-native-firebase/crashlytics',
                    '@react-native-firebase/messaging',
                ],
                'production_usable': False,
            },
            'xaman_root': '/fixture/xaman-app',
        },
    )


def _network_report(path: Path, *, apk_sha256: str, network_key: str = 'TESTNET') -> Path:
    return _write_json(
        path,
        {
            'schema_version': 'xaman-testnet-network-selection/v1',
            'task_id': 'PORTAL-CXTP-125',
            'artifact_cid': _artifact_cid('b'),
            'run_id': 'network-selection-fixture',
            'xaman_commit': '942f43876265a7af44f233288ad2b1d00841d5fa',
            'build_provenance_sha256': apk_sha256,
            'overall_status': 'verified',
            'security_decision': 'TESTNET_NETWORK_SELECTION_VERIFIED_NOT_PRODUCTION_EVIDENCE',
            'selection': {
                'network_key': network_key,
                'evidence_type': 'deterministic_local_state',
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
            },
            'fresh_account_boundary': {
                'fresh_account_created': True,
                'imported_account': False,
                'production_account': False,
                'account_material_recorded': False,
                'boundary': 'testnet_only_no_imported_or_persisted_account_material',
            },
            'xrpl_server_info_binding': {
                'request_category': 'xrpl_server_info',
                'request_sha256': 'd' * 64,
                'response_sha256': 'e' * 64,
                'network_id': 1,
                'network_id_verified': True,
                'raw_response_recorded': False,
                'raw_request_body_recorded': False,
            },
        },
    )


def _native_report(path: Path) -> Path:
    return _write_json(
        path,
        {
            'schema_version': 'xaman-native-firebase-boundary/v1',
            'task_id': 'PORTAL-CXTP-126',
            'artifact_cid': _artifact_cid('f'),
            'run_id': 'native-boundary-fixture',
            'xaman_commit': '942f43876265a7af44f233288ad2b1d00841d5fa',
            'overall_status': 'blocked',
            'security_decision': 'BLOCK_TESTNET_FULL_FIREBASE_DISABLED_LABEL_NATIVE_FIREBASE_PACKAGED',
            'native_firebase_fully_disabled': False,
            'native_firebase_evidence_present': True,
            'native_packaging_present': True,
            'native_startup_indicators_present': False,
            'device_trial_label_allowed': 'firebase_js_stubbed_only',
            'blockers': [{'code': 'FIREBASE_DEX_CLASSES_PRESENT'}],
        },
    )


def _output_metadata(path: Path) -> Path:
    return _write_json(
        path,
        {
            'variantName': 'debug',
            'applicationId': 'com.fixture.xaman',
            'elements': [
                {
                    'type': 'ONE_OF_MANY',
                    'filters': [{'filterType': 'ABI', 'value': 'x86_64'}],
                    'versionCode': 1,
                    'versionName': 'fixture',
                    'outputFile': 'app-x86_64-debug.apk',
                }
            ],
        },
    )


def _signing_config(path: Path) -> Path:
    return _write_json(
        path,
        {
            'enableV1Signing': False,
            'enableV2Signing': True,
            'enableV3Signing': False,
            'enableV4Signing': False,
        },
    )


def _duckdb(path: Path, *, apk_sha256: str, raw_event_name: str | None = None) -> Path:
    duckdb = pytest.importorskip('duckdb')
    con = duckdb.connect(path.as_posix())
    con.execute(
        'create table xaman_testnet_runs ('
        'run_id varchar primary key, captured_at_utc varchar, xaman_commit varchar, '
        'build_provenance_sha256 varchar, ledger_network varchar, ledger_endpoint varchar, '
        'firebase_mode varchar, event_log_sha256 varchar, accepted_event_count bigint, '
        'rejected_event_count bigint)'
    )
    con.execute(
        'create table xaman_testnet_events ('
        'run_id varchar, ordinal bigint, timestamp_utc varchar, category varchar, '
        'event_name varchar, outcome varchar, attributes_json varchar, source_line_sha256 varchar, '
        'primary key (run_id, ordinal))'
    )
    con.execute(
        'create table xaman_testnet_rejections ('
        'run_id varchar, source_line_number bigint, reason_code varchar, source_line_sha256 varchar, '
        'primary key (run_id, source_line_number))'
    )
    con.execute(
        'insert into xaman_testnet_runs values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
        [
            'telemetry-fixture',
            '2026-07-10T00:00:00Z',
            '942f43876265a7af44f233288ad2b1d00841d5fa',
            apk_sha256,
            'testnet',
            'wss://s.altnet.rippletest.net:51233',
            'disabled',
            '1' * 64,
            4,
            0,
        ],
    )
    event_names = [
        raw_event_name or 'messaging_operation',
        'firebase_analytics_operation',
        'messaging_has_permission',
        'firebase_analytics_operation',
    ]
    for index, name in enumerate(event_names, start=1):
        con.execute(
            'insert into xaman_testnet_events values (?, ?, ?, ?, ?, ?, ?, ?)',
            [
                'telemetry-fixture',
                index,
                '2026-07-10T00:00:00Z',
                'firebase_disabled',
                name,
                'stubbed',
                '{}',
                str(index) * 64,
            ],
        )
    con.close()
    return path


def _telemetry_report(path: Path, duckdb_path: Path, *, apk_sha256: str) -> Path:
    module = _load_module()
    return _write_json(
        path,
        {
            'schema_version': 'xaman-firebase-disabled-testnet-telemetry/v1',
            'task_id': 'PORTAL-CXTP-120',
            'artifact_cid': _artifact_cid('c'),
            'run_id': 'telemetry-fixture',
            'xaman_commit': '942f43876265a7af44f233288ad2b1d00841d5fa',
            'build_provenance_sha256': apk_sha256,
            'firebase_mode': 'disabled',
            'telemetry_sink': 'duckdb',
            'accepted_event_count': 4,
            'rejected_event_count': 0,
            'security_decision': 'TESTNET_FIREBASE_DISABLED_TELEMETRY_CAPTURED_NOT_PRODUCTION_EVIDENCE',
            'duckdb': {'sha256': module._sha256_file(duckdb_path), 'path': duckdb_path.as_posix()},
        },
    )


def _fixture_inputs(tmp_path: Path, *, network_key: str = 'TESTNET', raw_event_name: str | None = None) -> dict:
    module = _load_module()
    apk = tmp_path / 'app-x86_64-debug.apk'
    apk.write_bytes(b'fixture-apk')
    apk_sha256 = module._sha256_file(apk)
    duckdb_path = _duckdb(tmp_path / 'testnet-telemetry.duckdb', apk_sha256=apk_sha256, raw_event_name=raw_event_name)
    avd = tmp_path / 'ipfs_xaman_api34_testnet.avd'
    avd.mkdir()
    for name in ['config.ini', 'hardware-qemu.ini', 'emu-launch-params.txt', 'bootcompleted.ini']:
        (avd / name).write_text(f'{name}=fixture\n', encoding='utf-8')
    debug_keystore = tmp_path / 'debug.keystore'
    debug_keystore.write_bytes(b'fixture-debug-keystore')
    screenshot = tmp_path / 'xaman-testnet-launch.png'
    screenshot.write_bytes(b'png')

    return {
        'apk_path': apk,
        'duckdb_path': duckdb_path,
        'avd_path': avd,
        'build_manifest_path': _build_manifest(tmp_path / 'build-manifest.json'),
        'telemetry_report_path': _telemetry_report(tmp_path / 'telemetry.json', duckdb_path, apk_sha256=apk_sha256),
        'network_report_path': _network_report(tmp_path / 'network.json', apk_sha256=apk_sha256, network_key=network_key),
        'native_firebase_report_path': _native_report(tmp_path / 'native.json'),
        'output_metadata_path': _output_metadata(tmp_path / 'output-metadata.json'),
        'signing_config_path': _signing_config(tmp_path / 'signing-config-versions.json'),
        'debug_keystore_path': debug_keystore,
        'screenshot_paths': [screenshot],
        'generated_at_utc': '2026-07-10T00:00:00Z',
    }


def test_build_report_records_executed_trial_with_native_boundary(tmp_path: Path) -> None:
    module = _load_module()

    report = module.build_report(**_fixture_inputs(tmp_path))

    assert report['schema_version'] == 'xaman-testnet-device-trial/v1'
    assert report['task_id'] == 'PORTAL-CXTP-121'
    assert report['overall_status'] == 'executed_with_boundaries'
    assert report['blocking_gaps'] == []
    assert report['trial_scope']['device_trial_label'] == 'firebase_js_stubbed_only'
    assert report['trial_scope']['full_firebase_disabled_label_blocked'] is True
    assert report['verifier_artifact']['digest_matches_telemetry_report'] is True
    assert report['verifier_artifact']['signing']['debug_signed_evidence_present'] is True
    assert report['telemetry']['duckdb']['inspection_status'] == 'read_only_verified'
    assert report['telemetry']['duckdb']['event_count'] == 4
    assert report['approved_non_production_wallet_flow']['fresh_testnet_credentials'][
        'production_account'
    ] is False
    assert {boundary['code'] for boundary in report['residual_boundaries']} >= {
        'PRODUCTION_ACCEPTANCE_BLOCKED',
        'RUNTIME_EQUIVALENCE_NOT_PROVED',
        'FULL_FIREBASE_DISABLED_LABEL_BLOCKED',
    }
    rendered = json.dumps(report, sort_keys=True)
    assert 'wss://' not in rendered
    assert report['artifact_cid'].startswith('sha256:')


def test_build_report_fails_closed_when_network_selection_is_not_testnet(tmp_path: Path) -> None:
    module = _load_module()

    report = module.build_report(**_fixture_inputs(tmp_path, network_key='MAINNET'))

    assert report['overall_status'] == 'blocked'
    assert report['security_decision'] == 'BLOCK_TESTNET_DEVICE_TRIAL_EVIDENCE_FAILURE'
    assert {'SELECTED_NETWORK_NOT_TESTNET'} <= {gap['code'] for gap in report['blocking_gaps']}


def test_build_report_rejects_raw_endpoint_leaking_from_duckdb_event(tmp_path: Path) -> None:
    module = _load_module()

    with pytest.raises(module.TrialEvidenceError, match='raw WebSocket endpoint'):
        module.build_report(**_fixture_inputs(tmp_path, raw_event_name='wss://s.altnet.rippletest.net:51233'))


def test_checked_in_device_trial_artifact_preserves_required_boundaries() -> None:
    module = _load_module()
    report = json.loads(ARTIFACT_PATH.read_text(encoding='utf-8'))

    assert report['schema_version'] == 'xaman-testnet-device-trial/v1'
    assert report['task_id'] == 'PORTAL-CXTP-121'
    assert report['overall_status'] == 'executed_with_boundaries'
    assert report['blocking_gaps'] == []
    assert report['trial_scope']['network'] == 'XRPL_TESTNET'
    assert report['trial_scope']['production_usable'] is False
    assert report['approved_non_production_wallet_flow']['fresh_testnet_credentials'][
        'fresh_account_created'
    ] is True
    assert report['telemetry']['duckdb']['inspection_status'] == 'read_only_verified'
    assert report['firebase_boundary']['classification'] == 'firebase_js_stubbed_only'
    assert report['firebase_boundary']['native_firebase_fully_disabled'] is False
    assert report['redaction_boundary']['raw_xrpl_endpoint_recorded'] is False
    assert {boundary['code'] for boundary in report['residual_boundaries']} >= {
        'PRODUCTION_ACCEPTANCE_BLOCKED',
        'RUNTIME_EQUIVALENCE_NOT_PROVED',
        'FULL_FIREBASE_DISABLED_LABEL_BLOCKED',
    }
    canonical = json.dumps(
        {key: value for key, value in report.items() if key != 'artifact_cid'},
        sort_keys=True,
        separators=(',', ':'),
    ).encode('utf-8')
    assert report['artifact_cid'] == 'sha256:' + module._sha256_bytes(canonical)
