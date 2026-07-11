"""Tests for the Firebase-disabled Xaman Testnet verifier lane."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
import threading
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import duckdb
import pytest

from ipfs_datasets_py.logic.security_models.crypto_exchange.extractors.xaman_runtime_trace_ingestor import (
    build_report as build_runtime_trace_report,
)


REPO_ROOT = Path(__file__).resolve().parents[4]
SCRIPT_PATH = REPO_ROOT / 'scripts' / 'ops' / 'security_verification' / 'xaman_firebase_disabled_testnet.py'


def _load_module():
    spec = importlib.util.spec_from_file_location('xaman_firebase_disabled_testnet', SCRIPT_PATH)
    if spec is None or spec.loader is None:  # pragma: no cover
        raise AssertionError('failed to load Testnet verifier script')
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _xaman_root(tmp_path: Path) -> Path:
    root = tmp_path / 'xaman-app'
    (root / 'android' / 'app').mkdir(parents=True)
    (root / 'metro.config.js').write_text('module.exports = {};\n', encoding='utf-8')
    (root / 'android' / 'app' / 'build.gradle').write_text('// fixture\n', encoding='utf-8')
    rnn_source = root / 'node_modules' / 'react-native-navigation' / 'lib' / 'android' / 'app' / 'src' / 'main' / 'java' / 'com' / 'reactnativenavigation' / 'utils'
    rnn_source.mkdir(parents=True)
    (rnn_source / 'ReactTypefaceUtils.java').write_text(
        'public class ReactTypefaceUtils {\n'
        '  public static final int UNSET = -1;\n'
        '  int weight = ReactTextShadowNode.UNSET;\n'
        '  int style = ReactTextShadowNode.UNSET;\n'
        '}\n',
        encoding='utf-8',
    )
    return root


def _event(*, attributes: dict | None = None) -> dict:
    return {
        'schema_version': 'xaman-firebase-disabled-testnet-telemetry/v1',
        'timestamp_utc': '2026-07-10T00:00:00Z',
        'category': 'firebase_disabled',
        'event': 'firebase_analytics_operation',
        'outcome': 'stubbed',
        'attributes': attributes or {'operation': 'logEvent', 'arg_count': 1},
    }


def test_prepare_writes_external_firebase_disabled_kit(tmp_path: Path) -> None:
    module = _load_module()
    xaman = _xaman_root(tmp_path)
    kit = tmp_path / 'kit'
    react_native_debug_aar = tmp_path / 'ReactAndroid-debug.aar'
    react_native_debug_aar.write_bytes(b'original-react-native-debug-aar-fixture')

    manifest = module.prepare_testnet_kit(
        xaman_root=xaman,
        out_dir=kit,
        run_id='testnet-run-01',
        react_native_debug_aar=react_native_debug_aar,
        firebase_mock_endpoint='http://10.0.2.2:43127/v1/events',
    )

    assert manifest['schema_version'] == 'xaman-firebase-disabled-testnet-build/v1'
    assert manifest['firebase_mode'] == 'disabled_by_external_gradle_and_metro_overrides'
    assert manifest['runtime_constraints']['production_usable'] is False
    assert manifest['runtime_constraints']['react_native_navigation_compatibility_overlay'] is True
    assert manifest['runtime_constraints']['android_build_variant'] == 'debug'
    assert manifest['runtime_constraints']['firebase_mock_loopback_only'] is True
    assert manifest['runtime_constraints']['firebase_mock_endpoint'] == 'http://10.0.2.2:43127/v1/events'
    assert manifest['react_native_debug_aar']['sha256'] == module._sha256_file(react_native_debug_aar)
    assert manifest['artifact_cid'].startswith('sha256:')
    assert (kit / 'firebase-stubs' / 'analytics' / 'index.js').is_file()
    assert (kit / 'firebase-stubs' / 'crashlytics' / 'index.js').is_file()
    assert (kit / 'firebase-stubs' / 'messaging' / 'index.js').is_file()
    assert 'async ' not in (kit / 'firebase-stubs' / 'messaging' / 'index.js').read_text(encoding='utf-8')
    assert 'http://10.0.2.2:43127/v1/events' in (kit / 'firebase-stubs' / 'analytics' / 'index.js').read_text(encoding='utf-8')
    assert 'global.fetch' in (kit / 'firebase-stubs' / 'analytics' / 'index.js').read_text(encoding='utf-8')
    assert 'process.*GoogleServices' in (kit / 'firebase-disabled.init.gradle').read_text(encoding='utf-8')
    assert 'com.google.firebase.crashlytics' in (kit / 'firebase-disabled.init.gradle').read_text(encoding='utf-8')
    assert 'react-native-navigation' in (kit / 'firebase-disabled.init.gradle').read_text(encoding='utf-8')
    assert 'debugImplementation' in (kit / 'firebase-disabled.init.gradle').read_text(encoding='utf-8')
    assert '@react-native-firebase/messaging' in (kit / 'metro.config.js').read_text(encoding='utf-8')
    assert 'resolveRequest' in (kit / 'metro.config.js').read_text(encoding='utf-8')
    assert 'node_modules/metro-resolver' in (kit / 'metro.config.js').read_text(encoding='utf-8')
    assert 'watchFolders' in (kit / 'metro.config.js').read_text(encoding='utf-8')
    assert 'packager-status:running' in (kit / 'metro.config.js').read_text(encoding='utf-8')
    assert 'export CI=1' in (kit / 'build-xaman-testnet.sh').read_text(encoding='utf-8')
    assert 'app:assembleDebug' in (kit / 'build-xaman-testnet.sh').read_text(encoding='utf-8')
    compatibility = (kit / 'react-native-navigation-compat' / 'ReactTypefaceUtils.java').read_text(encoding='utf-8')
    assert 'ReactTextShadowNode.UNSET' not in compatibility
    assert compatibility.count('UNSET') >= 3
    assert not (xaman / 'android' / 'app' / 'google-services.json').exists()


def test_prepare_rejects_non_local_firebase_mock_endpoint(tmp_path: Path) -> None:
    module = _load_module()
    with pytest.raises(ValueError, match='loopback or Android-emulator'):
        module.prepare_testnet_kit(
            xaman_root=_xaman_root(tmp_path),
            out_dir=tmp_path / 'kit',
            run_id='testnet-run-nonlocal',
            firebase_mock_endpoint='https://telemetry.example.invalid/v1/events',
        )


def test_ingest_stores_redacted_events_in_duckdb(tmp_path: Path) -> None:
    module = _load_module()
    events = tmp_path / 'events.log'
    first = _event()
    second = _event(attributes={'operation': 'recordError', 'error_class': 'TypeError'})
    events.write_text(
        '\n'.join(
            [
                'I ReactNative: XAMAN_TESTNET_TELEMETRY:' + json.dumps(first),
                'XAMAN_TESTNET_TELEMETRY:' + json.dumps(second),
            ]
        )
        + '\n',
        encoding='utf-8',
    )
    database = tmp_path / 'telemetry.duckdb'

    report = module.ingest_telemetry(
        database_path=database,
        event_log_path=events,
        run_id='testnet-run-02',
        xaman_commit=module.PINNED_XAMAN_COMMIT,
        build_provenance_sha256='a' * 64,
        ledger_endpoint='wss://s.altnet.rippletest.net:51233',
        generated_at_utc='2026-07-10T00:00:00Z',
    )

    assert report['overall_status'] == 'captured_testnet_events'
    assert report['firebase_mode'] == 'disabled'
    assert report['production_release_blocked'] is True
    assert report['runtime_equivalence_status'] == 'not_proved'
    assert report['ledger']['target_binding_status'] == 'declared_not_runtime_verified'
    assert report['ledger']['runtime_connection_status'] == 'not_observed_by_firebase_stub_telemetry'
    assert report['accepted_event_count'] == 2
    assert report['rejected_event_count'] == 0
    connection = duckdb.connect(str(database), read_only=True)
    try:
        assert connection.execute('SELECT count(*) FROM xaman_testnet_runs').fetchone() == (1,)
        assert connection.execute('SELECT count(*) FROM xaman_testnet_events').fetchone() == (2,)
        assert connection.execute('SELECT count(*) FROM xaman_testnet_rejections').fetchone() == (0,)
    finally:
        connection.close()


def test_ingest_rejects_sensitive_event_fields_and_fails_closed(tmp_path: Path) -> None:
    module = _load_module()
    events = tmp_path / 'events.log'
    events.write_text(
        'XAMAN_TESTNET_TELEMETRY:' + json.dumps(_event(attributes={'seed': 'never-store-this'})) + '\n',
        encoding='utf-8',
    )
    database = tmp_path / 'telemetry.duckdb'

    report = module.ingest_telemetry(
        database_path=database,
        event_log_path=events,
        run_id='testnet-run-03',
        xaman_commit=module.PINNED_XAMAN_COMMIT,
        build_provenance_sha256='b' * 64,
        ledger_endpoint='wss://testnet.xrpl-labs.com/',
        generated_at_utc='2026-07-10T00:00:00Z',
    )

    assert report['overall_status'] == 'blocked'
    assert report['accepted_event_count'] == 0
    assert report['rejected_event_count'] == 1
    assert report['rejected_events'][0]['reason_code'] == 'TELEMETRY_ATTRIBUTE_KEY_NOT_ALLOWED'
    assert report['security_decision'] == 'BLOCK_TESTNET_TELEMETRY_REDACTION_FAILURE'


def test_cli_writes_report_for_valid_testnet_telemetry(tmp_path: Path) -> None:
    module = _load_module()
    events = tmp_path / 'events.log'
    events.write_text('XAMAN_TESTNET_TELEMETRY:' + json.dumps(_event()) + '\n', encoding='utf-8')
    out = tmp_path / 'report.json'

    rc = module.main(
        [
            'ingest',
            '--database',
            str(tmp_path / 'telemetry.duckdb'),
            '--events',
            str(events),
            '--run-id',
            'testnet-run-04',
            '--build-provenance-sha256',
            'c' * 64,
            '--ledger-endpoint',
            'wss://s.altnet.rippletest.net:51233',
            '--out',
            str(out),
        ]
    )

    assert rc == 0
    assert json.loads(out.read_text(encoding='utf-8'))['overall_status'] == 'captured_testnet_events'


def test_duckdb_firebase_mock_persists_redacted_events_over_http(tmp_path: Path) -> None:
    module = _load_module()
    database = tmp_path / 'firebase-mock.duckdb'
    server, store = module.create_firebase_mock_server(
        database_path=database,
        run_id='testnet-run-05',
        xaman_commit=module.PINNED_XAMAN_COMMIT,
        build_provenance_sha256='d' * 64,
        ledger_endpoint='wss://s.altnet.rippletest.net:51233',
        port=0,
    )
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    endpoint = f'http://127.0.0.1:{server.server_address[1]}/v1/events'
    health = f'http://127.0.0.1:{server.server_address[1]}/v1/health'
    try:
        request = Request(
            endpoint,
            data=json.dumps(_event()).encode('utf-8'),
            method='POST',
            headers={'Content-Type': 'application/json'},
        )
        with urlopen(request, timeout=5) as response:
            assert response.status == 202
            assert json.loads(response.read())['status'] == 'accepted'

        sensitive = Request(
            endpoint,
            data=json.dumps(_event(attributes={'token': 'never-store-this'})).encode('utf-8'),
            method='POST',
            headers={'Content-Type': 'application/json'},
        )
        try:
            urlopen(sensitive, timeout=5)
        except HTTPError as error:
            assert error.code == 422
            assert json.loads(error.read())['reason_code'] == 'TELEMETRY_ATTRIBUTE_KEY_NOT_ALLOWED'
        else:  # pragma: no cover - assertion if the mock accepted sensitive data
            raise AssertionError('mock accepted a sensitive telemetry attribute')

        with urlopen(health, timeout=5) as response:
            status = json.loads(response.read())
            assert status['accepted_event_count'] == 1
            assert status['rejected_event_count'] == 1
            assert status['storage'] == 'duckdb'
    finally:
        server.shutdown()
        worker.join(timeout=5)
        server.server_close()
        store.close()

    report = module.firebase_mock_report(
        database_path=database,
        run_id='testnet-run-05',
        generated_at_utc='2026-07-10T00:00:00Z',
    )
    assert report['overall_status'] == 'blocked'
    assert report['telemetry_sink'] == 'duckdb_firebase_mock'
    assert report['accepted_event_count'] == 1
    assert report['rejected_event_count'] == 1
    assert report['rejection_reason_codes'] == ['TELEMETRY_ATTRIBUTE_KEY_NOT_ALLOWED']
    runtime_report = build_runtime_trace_report(
        repo_root=REPO_ROOT,
        firebase_mock_database_path=database,
        firebase_mock_run_id='testnet-run-05',
        generated_at_utc='2026-07-10T00:00:00Z',
    )
    assert runtime_report['firebase_mock']['status'] == 'loaded'
    assert runtime_report['firebase_mock']['event_count'] == 1
    assert runtime_report['firebase_mock']['rejected_event_count'] == 1
    assert runtime_report['firebase_mock']['coverage'] == 'firebase_js_stub_telemetry_only'
    assert any(
        blocker['code'] == 'FIREBASE_MOCK_REJECTED_EVENTS_PRESENT'
        for blocker in runtime_report['blocking_gaps']
    )
    connection = duckdb.connect(str(database), read_only=True)
    try:
        assert connection.execute('SELECT count(*) FROM xaman_firebase_mock_events').fetchone() == (1,)
        assert connection.execute('SELECT count(*) FROM xaman_firebase_mock_rejections').fetchone() == (1,)
    finally:
        connection.close()
