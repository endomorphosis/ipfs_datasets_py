"""Tests for PORTAL-CXTP-126 native Firebase boundary audit."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
from zipfile import ZipFile


REPO_ROOT = Path(__file__).resolve().parents[4]
SCRIPT_PATH = (
    REPO_ROOT
    / 'scripts'
    / 'ops'
    / 'security_verification'
    / 'audit_xaman_native_firebase_boundary.py'
)
ARTIFACT_PATH = (
    REPO_ROOT
    / 'security_ir_artifacts'
    / 'corpora'
    / 'xaman-app'
    / 'runtime'
    / 'native-firebase-boundary-report.json'
)
DOC_PATH = REPO_ROOT / 'docs' / 'security_verification' / 'xaman_testnet_native_firebase_boundary.md'


def _load_module():
    spec = importlib.util.spec_from_file_location('audit_xaman_native_firebase_boundary', SCRIPT_PATH)
    if spec is None or spec.loader is None:  # pragma: no cover
        raise AssertionError('failed to load native Firebase boundary auditor')
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _write_fixture_apk(path: Path, *, native_firebase: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(path, 'w') as archive:
        if native_firebase:
            archive.writestr(
                'AndroidManifest.xml',
                b'binary-manifest-placeholder '
                b'io.invertase.firebase.app.ReactNativeFirebaseAppInitProvider '
                b'com.google.firebase.provider.FirebaseInitProvider',
            )
            archive.writestr(
                'classes.dex',
                b'dex\n'
                b'io/invertase/firebase/app/ReactNativeFirebaseAppInitProvider\n'
                b'com/google/firebase/crashlytics/FirebaseCrashlytics\n',
            )
            archive.writestr('lib/x86_64/libcrashlytics.so', b'native-crashlytics')
            archive.writestr('res/raw/firebase_crashlytics_keep.xml', b'<keep />')
            archive.writestr('firebase-analytics.properties', b'version=fixture')
        else:
            archive.writestr('AndroidManifest.xml', b'binary-manifest-placeholder')
            archive.writestr('classes.dex', b'dex\ncom/example/verifier/MainActivity\n')
            archive.writestr('lib/x86_64/libreactnativejni.so', b'native-react')


def _write_utf16_manifest_indicator_apk(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(path, 'w') as archive:
        archive.writestr(
            'AndroidManifest.xml',
            'io.invertase.firebase.app.ReactNativeFirebaseAppInitProvider'.encode('utf-16le'),
        )
        archive.writestr('classes.dex', b'dex\ncom/example/verifier/MainActivity\n')


def _manifest(path: Path, *, native_firebase: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if native_firebase:
        body = '''
        <manifest xmlns:android="http://schemas.android.com/apk/res/android">
          <application>
            <provider
              android:name="io.invertase.firebase.app.ReactNativeFirebaseAppInitProvider"
              android:authorities="fixture.reactnativefirebaseappinitprovider" />
            <provider
              android:name="com.google.firebase.provider.FirebaseInitProvider"
              android:authorities="fixture.firebaseinitprovider" />
            <service android:name="com.google.firebase.components.ComponentDiscoveryService">
              <meta-data
                android:name="com.google.firebase.components:com.google.firebase.crashlytics.CrashlyticsRegistrar"
                android:value="com.google.firebase.components.ComponentRegistrar" />
            </service>
            <service android:name="com.google.firebase.messaging.FirebaseMessagingService" />
          </application>
        </manifest>
        '''
    else:
        body = '''
        <manifest xmlns:android="http://schemas.android.com/apk/res/android">
          <application>
            <activity android:name="com.example.verifier.MainActivity" />
          </application>
        </manifest>
        '''
    path.write_text(body, encoding='utf-8')


def _startup_log(path: Path) -> None:
    path.write_text(
        '\n'.join(
            [
                'I/ReactNativeJS: XAMAN_TESTNET_TELEMETRY:{"category":"firebase_disabled","event":"messaging_has_permission"}',
                'I/FirebaseInitProvider: FirebaseApp initialization successful',
                'I/CrashlyticsCore: Initializing Crashlytics',
            ]
        )
        + '\n',
        encoding='utf-8',
    )


def test_audit_blocks_when_native_firebase_is_packaged(tmp_path: Path) -> None:
    module = _load_module()
    apk = tmp_path / 'app-x86_64-debug.apk'
    manifest = tmp_path / 'AndroidManifest.xml'
    log = tmp_path / 'startup.log'
    _write_fixture_apk(apk, native_firebase=True)
    _manifest(manifest, native_firebase=True)
    _startup_log(log)

    report = module.build_report(
        apk_path=apk,
        merged_manifest_path=manifest,
        startup_log_path=log,
        generated_at_utc='2026-07-10T00:00:00Z',
    )

    assert report['schema_version'] == 'xaman-native-firebase-boundary/v1'
    assert report['task_id'] == 'PORTAL-CXTP-126'
    assert report['overall_status'] == 'blocked'
    assert report['native_packaging_present'] is True
    assert report['native_startup_indicators_present'] is True
    assert report['native_firebase_evidence_present'] is True
    assert report['native_firebase_fully_disabled'] is False
    assert report['required_evidence']['complete'] is True
    assert report['device_trial_label_allowed'] == 'firebase_js_stubbed_only'
    blocker_codes = {blocker['code'] for blocker in report['blockers']}
    assert 'NATIVE_FIREBASE_MANIFEST_COMPONENTS_PRESENT' in blocker_codes
    assert 'NATIVE_FIREBASE_APK_BINARY_MANIFEST_INDICATORS_PRESENT' in blocker_codes
    assert 'FIREBASE_COMPONENT_REGISTRARS_PRESENT' in blocker_codes
    assert 'FIREBASE_DEX_CLASSES_PRESENT' in blocker_codes
    assert 'CRASHLYTICS_NATIVE_LIBRARIES_PRESENT' in blocker_codes
    assert 'NATIVE_FIREBASE_STARTUP_LOG_INDICATORS_PRESENT' in blocker_codes
    assert report['startup_log_inspection']['js_stub_event_count'] == 1
    assert report['startup_log_inspection']['native_indicator_counts']['firebase_init_provider'] == 1
    assert report['startup_log_inspection']['native_indicator_counts']['crashlytics'] == 1
    assert all('line_sha256' in item and 'raw' not in item for item in report['startup_log_inspection']['redacted_matches'])


def test_audit_scans_apk_binary_manifest_with_utf16_strings(tmp_path: Path) -> None:
    module = _load_module()
    apk = tmp_path / 'app-x86_64-debug.apk'
    manifest = tmp_path / 'AndroidManifest.xml'
    log = tmp_path / 'startup.log'
    _write_utf16_manifest_indicator_apk(apk)
    _manifest(manifest, native_firebase=False)
    log.write_text('I/App: verifier startup complete\n', encoding='utf-8')

    report = module.build_report(
        apk_path=apk,
        merged_manifest_path=manifest,
        startup_log_path=log,
        generated_at_utc='2026-07-10T00:00:00Z',
    )

    assert report['overall_status'] == 'blocked'
    assert report['apk_inspection']['binary_manifest_indicator_counts'] == {
        'react_native_firebase_app_init_provider': 1,
    }
    assert {blocker['code'] for blocker in report['blockers']} == {
        'NATIVE_FIREBASE_APK_BINARY_MANIFEST_INDICATORS_PRESENT',
    }


def test_audit_blocks_clean_apk_when_startup_log_shows_native_firebase(tmp_path: Path) -> None:
    module = _load_module()
    apk = tmp_path / 'app-x86_64-debug.apk'
    manifest = tmp_path / 'AndroidManifest.xml'
    log = tmp_path / 'startup.log'
    _write_fixture_apk(apk, native_firebase=False)
    _manifest(manifest, native_firebase=False)
    _startup_log(log)

    report = module.build_report(
        apk_path=apk,
        merged_manifest_path=manifest,
        startup_log_path=log,
        generated_at_utc='2026-07-10T00:00:00Z',
    )

    assert report['overall_status'] == 'blocked'
    assert report['native_packaging_present'] is False
    assert report['native_startup_indicators_present'] is True
    assert report['native_firebase_evidence_present'] is True
    assert report['native_firebase_fully_disabled'] is False
    blocker_codes = {blocker['code'] for blocker in report['blockers']}
    assert blocker_codes == {'NATIVE_FIREBASE_STARTUP_LOG_INDICATORS_PRESENT'}


def test_audit_passes_when_external_removal_outputs_clean_apk(tmp_path: Path) -> None:
    module = _load_module()
    apk = tmp_path / 'app-x86_64-debug.apk'
    manifest = tmp_path / 'AndroidManifest.xml'
    log = tmp_path / 'startup.log'
    _write_fixture_apk(apk, native_firebase=False)
    _manifest(manifest, native_firebase=False)
    log.write_text('I/App: verifier startup complete\n', encoding='utf-8')

    report = module.build_report(
        apk_path=apk,
        merged_manifest_path=manifest,
        startup_log_path=log,
        generated_at_utc='2026-07-10T00:00:00Z',
    )

    assert report['overall_status'] == 'pass'
    assert report['required_evidence']['complete'] is True
    assert report['native_packaging_present'] is False
    assert report['native_startup_indicators_present'] is False
    assert report['native_firebase_evidence_present'] is False
    assert report['native_firebase_fully_disabled'] is True
    assert report['security_decision'] == 'TESTNET_NATIVE_FIREBASE_REMOVAL_VERIFIED'
    assert report['blockers'] == []


def test_audit_records_external_overlay_proof_only_when_clean(tmp_path: Path) -> None:
    module = _load_module()
    apk = tmp_path / 'app-x86_64-debug.apk'
    manifest = tmp_path / 'AndroidManifest.xml'
    log = tmp_path / 'startup.log'
    overlay = tmp_path / 'firebase-removal-manifest.xml'
    dependency_overlay = tmp_path / 'firebase-removal.gradle'
    _write_fixture_apk(apk, native_firebase=False)
    _manifest(manifest, native_firebase=False)
    log.write_text('I/App: verifier startup complete\n', encoding='utf-8')
    overlay.write_text('<manifest />\n', encoding='utf-8')
    dependency_overlay.write_text('configurations.configureEach { }\n', encoding='utf-8')

    report = module.build_report(
        apk_path=apk,
        merged_manifest_path=manifest,
        startup_log_path=log,
        manifest_removal_overlay_path=overlay,
        dependency_removal_overlay_path=dependency_overlay,
        generated_at_utc='2026-07-10T00:00:00Z',
    )

    assert report['overall_status'] == 'pass'
    assert report['external_removal_assessment']['status'] == 'verified_absent_after_external_overlay'
    assert report['external_removal_assessment']['overlay_evidence_present'] is True
    assert report['inputs']['manifest_removal_overlay']['present'] is True
    assert report['inputs']['dependency_removal_overlay']['present'] is True


def test_audit_fails_closed_when_required_native_evidence_is_missing(tmp_path: Path) -> None:
    module = _load_module()
    apk = tmp_path / 'app-x86_64-debug.apk'
    _write_fixture_apk(apk, native_firebase=False)

    report = module.build_report(
        apk_path=apk,
        generated_at_utc='2026-07-10T00:00:00Z',
    )

    assert report['overall_status'] == 'blocked'
    assert report['required_evidence'] == {
        'apk_present': True,
        'merged_manifest_present': False,
        'startup_log_present': False,
        'complete': False,
    }
    assert report['native_packaging_present'] is False
    assert report['native_startup_indicators_present'] is False
    assert report['native_firebase_fully_disabled'] is False
    assert report['device_trial_label_allowed'] == 'not_allowed_missing_native_firebase_evidence'
    assert report['security_decision'] == (
        'BLOCK_TESTNET_FULL_FIREBASE_DISABLED_LABEL_NATIVE_FIREBASE_EVIDENCE_INCOMPLETE'
    )
    assert report['external_removal_assessment']['status'] == 'missing_required_evidence'
    assert {blocker['code'] for blocker in report['blockers']} == {
        'MERGED_MANIFEST_NOT_SUPPLIED',
        'STARTUP_LOG_NOT_SUPPLIED',
    }
    assert 'evidence is incomplete' in report['boundary_statement']


def test_cli_writes_redacted_boundary_report(tmp_path: Path) -> None:
    module = _load_module()
    apk = tmp_path / 'app-x86_64-debug.apk'
    manifest = tmp_path / 'AndroidManifest.xml'
    log = tmp_path / 'startup.log'
    out = tmp_path / 'report.json'
    _write_fixture_apk(apk, native_firebase=True)
    _manifest(manifest, native_firebase=True)
    _startup_log(log)

    rc = module.main(
        [
            '--apk',
            apk.as_posix(),
            '--merged-manifest',
            manifest.as_posix(),
            '--startup-log',
            log.as_posix(),
            '--generated-at-utc',
            '2026-07-10T00:00:00Z',
            '--out',
            out.as_posix(),
        ]
    )

    report = json.loads(out.read_text(encoding='utf-8'))
    assert rc == 0
    assert report['overall_status'] == 'blocked'
    assert report['security_decision'] == 'BLOCK_TESTNET_FULL_FIREBASE_DISABLED_LABEL_NATIVE_FIREBASE_PACKAGED'
    assert 'artifact_cid' in report


def test_checked_in_boundary_artifact_blocks_full_firebase_disabled_label() -> None:
    module = _load_module()
    report = json.loads(ARTIFACT_PATH.read_text(encoding='utf-8'))

    assert report['schema_version'] == 'xaman-native-firebase-boundary/v1'
    assert report['task_id'] == 'PORTAL-CXTP-126'
    assert report['overall_status'] == 'blocked'
    assert report['native_packaging_present'] is True
    assert report['native_firebase_evidence_present'] is True
    assert report['required_evidence']['complete'] is True
    assert report['native_firebase_fully_disabled'] is False
    assert report['device_trial_label_allowed'] == 'firebase_js_stubbed_only'
    assert report['javascript_boundary']['boundary_conclusion'].startswith('javascript_calls_stubbed_only')
    blocker_codes = {blocker['code'] for blocker in report['blockers']}
    assert 'NATIVE_FIREBASE_MANIFEST_COMPONENTS_PRESENT' in blocker_codes
    assert 'FIREBASE_DEX_CLASSES_PRESENT' in blocker_codes
    assert 'CRASHLYTICS_NATIVE_LIBRARIES_PRESENT' in blocker_codes

    canonical = json.dumps(
        {key: value for key, value in report.items() if key != 'artifact_cid'},
        sort_keys=True,
        separators=(',', ':'),
    ).encode('utf-8')
    assert report['artifact_cid'] == 'sha256:' + module._sha256_bytes(canonical)


def test_document_records_native_boundary_and_validation_command() -> None:
    doc = DOC_PATH.read_text(encoding='utf-8')

    assert 'PORTAL-CXTP-126' in doc
    assert 'native-firebase-boundary-report.json' in doc
    assert 'audit_xaman_native_firebase_boundary.py' in doc
    assert 'ReactNativeFirebaseAppInitProvider' in doc
    assert 'Crashlytics native libraries' in doc
    assert 'UTF-16LE' in doc
    assert '--manifest-removal-overlay' in doc
    assert 'verified_absent_after_external_overlay' in doc
