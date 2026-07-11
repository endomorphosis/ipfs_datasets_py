#!/usr/bin/env python3
"""Audit native Firebase packaging in the Xaman Testnet verifier APK.

This verifier distinguishes JavaScript-level Firebase stubbing from packaged
Android native behavior.  It reads the generated debug APK, the Gradle merged
manifest, and a startup log, then emits a redacted boundary report.  The report
passes only when native Firebase providers, component registrars, DEX classes,
Crashlytics native libraries, and native startup-log indicators are absent from
the inspected evidence.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Mapping, Sequence
from zipfile import ZipFile
import xml.etree.ElementTree as ET


SCHEMA_VERSION = 'xaman-native-firebase-boundary/v1'
TASK_ID = 'PORTAL-CXTP-126'
PINNED_XAMAN_COMMIT = '942f43876265a7af44f233288ad2b1d00841d5fa'
DEFAULT_OUT = Path('security_ir_artifacts/corpora/xaman-app/runtime/native-firebase-boundary-report.json')
TELEMETRY_MARKER = 'XAMAN_TESTNET_TELEMETRY:'
IDENTIFIER_RE = re.compile(r'^[A-Za-z0-9_.:-]{1,160}$')
ANDROID_NS = '{http://schemas.android.com/apk/res/android}'

MANIFEST_FIREBASE_PATTERNS = {
    'react_native_firebase_init_provider_generic': 'ReactNativeFirebaseInitProvider',
    'react_native_firebase_app_init_provider': 'io.invertase.firebase.app.ReactNativeFirebaseAppInitProvider',
    'react_native_firebase_crashlytics_init_provider': (
        'io.invertase.firebase.crashlytics.ReactNativeFirebaseCrashlyticsInitProvider'
    ),
    'firebase_init_provider': 'com.google.firebase.provider.FirebaseInitProvider',
    'firebase_component_discovery_service': 'com.google.firebase.components.ComponentDiscoveryService',
    'firebase_messaging_service': 'com.google.firebase.messaging.FirebaseMessagingService',
    'firebase_instance_id_receiver': 'com.google.firebase.iid.FirebaseInstanceIdReceiver',
    'react_native_firebase_messaging_service': (
        'io.invertase.firebase.messaging.ReactNativeFirebaseMessagingService'
    ),
    'react_native_firebase_messaging_receiver': (
        'io.invertase.firebase.messaging.ReactNativeFirebaseMessagingReceiver'
    ),
}
DEX_FIREBASE_PATTERNS = {
    'react_native_firebase_init_provider_generic': b'ReactNativeFirebaseInitProvider',
    'react_native_firebase_app_init_provider': b'ReactNativeFirebaseAppInitProvider',
    'react_native_firebase_crashlytics_init_provider': b'ReactNativeFirebaseCrashlyticsInitProvider',
    'react_native_firebase_app_package': b'io/invertase/firebase/app',
    'react_native_firebase_messaging_package': b'io/invertase/firebase/messaging',
    'react_native_firebase_crashlytics_package': b'io/invertase/firebase/crashlytics',
    'firebase_core_package': b'com/google/firebase/',
    'firebase_crashlytics_class': b'com/google/firebase/crashlytics/',
    'firebase_messaging_class': b'com/google/firebase/messaging/',
}
APK_FIREBASE_RESOURCE_PREFIXES = (
    'firebase-',
    'res/raw/firebase_',
)
APK_FIREBASE_RESOURCE_SUBSTRINGS = (
    '/firebase-',
    '/firebase_',
    'google-services',
)
CRASHLYTICS_NATIVE_RE = re.compile(r'(^|/)libcrashlytics[^/]*\.so$')
STARTUP_LOG_PATTERNS = {
    'firebase': re.compile(r'firebase', re.IGNORECASE),
    'firebase_app_initialization': re.compile(r'FirebaseApp initialization|Initializing Firebase', re.IGNORECASE),
    'crashlytics': re.compile(r'crashlytics', re.IGNORECASE),
    'firebase_init_provider': re.compile(r'FirebaseInitProvider|ReactNativeFirebase.*InitProvider'),
    'component_discovery': re.compile(r'ComponentDiscoveryService|ComponentRegistrar'),
    'js_stub_marker': re.compile(re.escape(TELEMETRY_MARKER)),
}
NATIVE_STARTUP_LOG_INDICATORS = frozenset(
    {
        'firebase_app_initialization',
        'crashlytics',
        'firebase_init_provider',
        'component_discovery',
    }
)
SENSITIVE_LOG_PARTS = (
    'address',
    'authorization',
    'credential',
    'mnemonic',
    'passcode',
    'password',
    'payload',
    'private',
    'seed',
    'secret',
    'token',
    'transaction',
    'tx_blob',
)


@dataclass(frozen=True)
class InputFile:
    path: Path
    required: bool = True


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


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


def _load_json(path: Path | None) -> dict[str, Any] | None:
    if path is None or not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding='utf-8'))
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def _optional_file_record(path: Path | None) -> dict[str, Any] | None:
    if path is None:
        return None
    return _input_record(InputFile(path, required=False))


def _input_record(input_file: InputFile | None) -> dict[str, Any] | None:
    if input_file is None:
        return None
    path = input_file.path.resolve()
    if not path.is_file():
        if input_file.required:
            raise ValueError(f'required input file is missing: {path}')
        return {'path': path.as_posix(), 'present': False}
    return {
        'path': path.as_posix(),
        'present': True,
        'sha256': _sha256_file(path),
        'size_bytes': path.stat().st_size,
    }


def _android_name(element: ET.Element) -> str | None:
    value = element.attrib.get(ANDROID_NS + 'name') or element.attrib.get('android:name')
    return value if isinstance(value, str) else None


def _bytes_pattern_count(data: bytes, value: str) -> int:
    return (
        data.count(value.encode('utf-8'))
        + data.count(value.encode('utf-16le'))
        + data.count(value.encode('utf-16be'))
    )


def _manifest_components(manifest_path: Path | None) -> dict[str, Any]:
    if manifest_path is None or not manifest_path.is_file():
        return {
            'status': 'missing',
            'providers': [],
            'services': [],
            'receivers': [],
            'firebase_component_registrars': [],
            'firebase_metadata': [],
            'indicator_counts': {},
            'blocker': 'MERGED_MANIFEST_MISSING',
        }

    text = manifest_path.read_text(encoding='utf-8', errors='replace')
    providers: list[str] = []
    services: list[str] = []
    receivers: list[str] = []
    registrars: list[str] = []
    metadata: list[str] = []
    parse_status = 'parsed_xml'
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        parse_status = 'plain_text_scan'
        root = None

    if root is not None:
        for element in root.iter():
            tag = element.tag.rsplit('}', 1)[-1]
            name = _android_name(element)
            if not name:
                continue
            if tag == 'provider':
                providers.append(name)
            elif tag == 'service':
                services.append(name)
            elif tag == 'receiver':
                receivers.append(name)
            elif tag == 'meta-data':
                metadata.append(name)
                if name.startswith('com.google.firebase.components:'):
                    registrars.append(name.removeprefix('com.google.firebase.components:'))
    else:
        for pattern in MANIFEST_FIREBASE_PATTERNS.values():
            if pattern in text:
                if 'Provider' in pattern:
                    providers.append(pattern)
                elif 'Receiver' in pattern:
                    receivers.append(pattern)
                else:
                    services.append(pattern)
        registrars = sorted(set(re.findall(r'com\.google\.firebase\.components:([A-Za-z0-9_.$]+)', text)))
        metadata = sorted(set(re.findall(r'android:name="([^"]*firebase[^"]*)"', text, flags=re.IGNORECASE)))

    indicator_counts = {
        key: text.count(pattern)
        for key, pattern in MANIFEST_FIREBASE_PATTERNS.items()
        if text.count(pattern)
    }
    firebase_metadata = sorted({item for item in metadata if 'firebase' in item.lower()})
    return {
        'status': parse_status,
        'providers': sorted(set(providers)),
        'services': sorted(set(services)),
        'receivers': sorted(set(receivers)),
        'firebase_component_registrars': sorted(set(registrars)),
        'firebase_metadata': firebase_metadata,
        'indicator_counts': indicator_counts,
    }


def _scan_apk(apk_path: Path) -> dict[str, Any]:
    if not apk_path.is_file():
        raise ValueError(f'apk is missing: {apk_path}')
    dex_entries: list[dict[str, Any]] = []
    crashlytics_native_libraries: list[dict[str, Any]] = []
    firebase_packaged_resources: list[dict[str, Any]] = []
    manifest_binary_hits: dict[str, int] = {}
    with ZipFile(apk_path) as archive:
        for info in archive.infolist():
            name = info.filename
            if name.startswith('classes') and name.endswith('.dex'):
                data = archive.read(info)
                matches = sorted(key for key, pattern in DEX_FIREBASE_PATTERNS.items() if pattern in data)
                if matches:
                    dex_entries.append(
                        {
                            'entry': name,
                            'sha256': _sha256_bytes(data),
                            'size_bytes': info.file_size,
                            'matched_indicators': matches,
                        }
                    )
            if CRASHLYTICS_NATIVE_RE.search(name):
                crashlytics_native_libraries.append(
                    {'entry': name, 'compressed_size_bytes': info.compress_size, 'size_bytes': info.file_size}
                )
            lower_name = name.lower()
            if any(lower_name.startswith(pattern) for pattern in APK_FIREBASE_RESOURCE_PREFIXES) or any(
                pattern in lower_name for pattern in APK_FIREBASE_RESOURCE_SUBSTRINGS
            ):
                firebase_packaged_resources.append(
                    {'entry': name, 'compressed_size_bytes': info.compress_size, 'size_bytes': info.file_size}
                )
            if name == 'AndroidManifest.xml':
                data = archive.read(info)
                manifest_binary_hits = {
                    key: _bytes_pattern_count(data, pattern)
                    for key, pattern in MANIFEST_FIREBASE_PATTERNS.items()
                    if _bytes_pattern_count(data, pattern)
                }
    return {
        'dex_entries_with_firebase_indicators': dex_entries,
        'dex_entry_count_with_indicators': len(dex_entries),
        'crashlytics_native_libraries': crashlytics_native_libraries,
        'crashlytics_native_library_count': len(crashlytics_native_libraries),
        'firebase_packaged_resources': firebase_packaged_resources,
        'firebase_packaged_resource_count': len(firebase_packaged_resources),
        'binary_manifest_indicator_counts': manifest_binary_hits,
    }


def _line_has_sensitive_key(line: str) -> bool:
    normalized = line.replace('-', '_').lower()
    return any(part in normalized for part in SENSITIVE_LOG_PARTS)


def _startup_log_summary(log_path: Path | None) -> dict[str, Any]:
    if log_path is None or not log_path.is_file():
        return {
            'status': 'missing',
            'line_count': 0,
            'indicator_counts': {},
            'redacted_matches': [],
            'js_stub_event_count': 0,
            'blocker': 'STARTUP_LOG_MISSING',
        }
    indicator_counts = {key: 0 for key in STARTUP_LOG_PATTERNS}
    redacted_matches: list[dict[str, Any]] = []
    js_stub_event_count = 0
    line_count = 0
    for line_number, line in enumerate(log_path.read_text(encoding='utf-8', errors='replace').splitlines(), start=1):
        line_count = line_number
        matched = [key for key, pattern in STARTUP_LOG_PATTERNS.items() if pattern.search(line)]
        if not matched:
            continue
        for key in matched:
            indicator_counts[key] += 1
        if 'js_stub_marker' in matched:
            js_stub_event_count += 1
        redacted_matches.append(
            {
                'line_number': line_number,
                'line_sha256': _sha256_bytes(line.encode('utf-8', errors='replace')),
                'matched_indicators': matched,
                'redaction': 'raw_line_omitted',
                'sensitive_key_seen': _line_has_sensitive_key(line),
            }
        )
    return {
        'status': 'scanned',
        'line_count': line_count,
        'indicator_counts': {key: count for key, count in indicator_counts.items() if count},
        'native_indicator_counts': {
            key: indicator_counts[key]
            for key in sorted(NATIVE_STARTUP_LOG_INDICATORS)
            if indicator_counts.get(key)
        },
        'redacted_matches': redacted_matches[:80],
        'redacted_match_count': len(redacted_matches),
        'redacted_match_truncated': len(redacted_matches) > 80,
        'js_stub_event_count': js_stub_event_count,
    }


def _js_boundary(
    *,
    build_kit_manifest_path: Path | None,
    telemetry_report_path: Path | None,
) -> dict[str, Any]:
    build_manifest = _load_json(build_kit_manifest_path)
    telemetry_report = _load_json(telemetry_report_path)
    constraints = build_manifest.get('runtime_constraints') if isinstance(build_manifest, Mapping) else {}
    constraints = constraints if isinstance(constraints, Mapping) else {}
    return {
        'status': 'inspected' if build_manifest or telemetry_report else 'not_provided',
        'build_manifest_present': build_manifest is not None,
        'telemetry_report_present': telemetry_report is not None,
        'firebase_js_modules_stubbed': constraints.get('firebase_js_modules_stubbed') or [],
        'firebase_gradle_tasks_disabled': constraints.get('firebase_gradle_tasks_disabled'),
        'firebase_mock_loopback_only': constraints.get('firebase_mock_loopback_only'),
        'telemetry_security_decision': (
            telemetry_report.get('security_decision') if isinstance(telemetry_report, Mapping) else None
        ),
        'accepted_stub_event_count': (
            telemetry_report.get('accepted_event_count') if isinstance(telemetry_report, Mapping) else None
        ),
        'boundary_conclusion': (
            'javascript_calls_stubbed_only_native_packaging_separately_audited'
            if build_manifest or telemetry_report
            else 'javascript_boundary_evidence_not_supplied'
        ),
    }


def _external_removal_status(
    *,
    fully_disabled: bool,
    native_packaging_present: bool,
    native_startup_indicators_present: bool,
    missing_evidence: Sequence[Mapping[str, Any]],
    overlay_evidence_present: bool,
) -> str:
    if fully_disabled:
        return 'verified_absent_after_external_overlay' if overlay_evidence_present else 'verified_absent'
    if missing_evidence:
        return 'missing_required_evidence'
    if overlay_evidence_present and native_packaging_present:
        return 'overlay_supplied_but_native_firebase_still_packaged'
    if native_packaging_present:
        return 'not_effective_or_not_supplied'
    if native_startup_indicators_present:
        return 'apk_clean_but_startup_native_indicators_present'
    return 'blocked_unknown'


def _security_decision(
    *,
    fully_disabled: bool,
    native_packaging_present: bool,
    native_startup_indicators_present: bool,
    missing_evidence: Sequence[Mapping[str, Any]],
) -> str:
    if fully_disabled:
        return 'TESTNET_NATIVE_FIREBASE_REMOVAL_VERIFIED'
    if missing_evidence:
        return 'BLOCK_TESTNET_FULL_FIREBASE_DISABLED_LABEL_NATIVE_FIREBASE_EVIDENCE_INCOMPLETE'
    if native_packaging_present:
        return 'BLOCK_TESTNET_FULL_FIREBASE_DISABLED_LABEL_NATIVE_FIREBASE_PACKAGED'
    if native_startup_indicators_present:
        return 'BLOCK_TESTNET_FULL_FIREBASE_DISABLED_LABEL_NATIVE_FIREBASE_STARTUP_INDICATORS'
    return 'BLOCK_TESTNET_FULL_FIREBASE_DISABLED_LABEL_NATIVE_FIREBASE_UNRESOLVED'


def _device_trial_label(
    *,
    fully_disabled: bool,
    missing_evidence: Sequence[Mapping[str, Any]],
) -> str:
    if fully_disabled:
        return 'firebase_disabled'
    if missing_evidence:
        return 'not_allowed_missing_native_firebase_evidence'
    return 'firebase_js_stubbed_only'


def _boundary_statement(
    *,
    fully_disabled: bool,
    native_firebase_evidence_present: bool,
    missing_evidence: Sequence[Mapping[str, Any]],
) -> str:
    if fully_disabled:
        return 'No native Firebase packaging indicators were found in the inspected APK and startup evidence.'
    if missing_evidence:
        return (
            'Required native Firebase evidence is incomplete; the Testnet device trial cannot be labeled fully '
            'Firebase-disabled until the generated APK, merged manifest, and startup log all pass this audit.'
        )
    if native_firebase_evidence_present:
        return (
            'JavaScript Firebase calls may be stubbed, but the inspected APK or startup evidence still shows '
            'native Firebase initialization and/or Crashlytics artifacts; the Testnet device trial cannot be '
            'labeled fully Firebase-disabled.'
        )
    return (
        'No native Firebase indicators were found, but the audit remains blocked by unresolved evidence state; '
        'do not label the device trial fully Firebase-disabled.'
    )


def build_report(
    *,
    apk_path: Path | str,
    merged_manifest_path: Path | str | None = None,
    startup_log_path: Path | str | None = None,
    build_kit_manifest_path: Path | str | None = None,
    telemetry_report_path: Path | str | None = None,
    manifest_removal_overlay_path: Path | str | None = None,
    dependency_removal_overlay_path: Path | str | None = None,
    run_id: str = 'xaman-native-firebase-boundary',
    xaman_commit: str = PINNED_XAMAN_COMMIT,
    generated_at_utc: str | None = None,
) -> dict[str, Any]:
    """Build the native Firebase boundary report."""
    if not IDENTIFIER_RE.fullmatch(run_id):
        raise ValueError('run_id must be a short identifier containing only letters, digits, . _ : or -')
    if xaman_commit != PINNED_XAMAN_COMMIT:
        raise ValueError('xaman_commit must match the pinned Xaman corpus commit')
    apk = Path(apk_path).resolve()
    manifest = Path(merged_manifest_path).resolve() if merged_manifest_path is not None else None
    startup_log = Path(startup_log_path).resolve() if startup_log_path is not None else None
    build_kit_manifest = Path(build_kit_manifest_path).resolve() if build_kit_manifest_path is not None else None
    telemetry_report = Path(telemetry_report_path).resolve() if telemetry_report_path is not None else None
    manifest_removal_overlay = (
        Path(manifest_removal_overlay_path).resolve() if manifest_removal_overlay_path is not None else None
    )
    dependency_removal_overlay = (
        Path(dependency_removal_overlay_path).resolve() if dependency_removal_overlay_path is not None else None
    )

    manifest_inspection = _manifest_components(manifest)
    apk_inspection = _scan_apk(apk)
    startup_inspection = _startup_log_summary(startup_log)
    js_boundary = _js_boundary(
        build_kit_manifest_path=build_kit_manifest,
        telemetry_report_path=telemetry_report,
    )

    native_packaging_findings: list[dict[str, Any]] = []
    if manifest_inspection['indicator_counts']:
        native_packaging_findings.append(
            {
                'code': 'NATIVE_FIREBASE_MANIFEST_COMPONENTS_PRESENT',
                'indicator_counts': manifest_inspection['indicator_counts'],
            }
        )
    if apk_inspection['binary_manifest_indicator_counts']:
        native_packaging_findings.append(
            {
                'code': 'NATIVE_FIREBASE_APK_BINARY_MANIFEST_INDICATORS_PRESENT',
                'indicator_counts': apk_inspection['binary_manifest_indicator_counts'],
            }
        )
    if manifest_inspection['firebase_component_registrars']:
        native_packaging_findings.append(
            {
                'code': 'FIREBASE_COMPONENT_REGISTRARS_PRESENT',
                'count': len(manifest_inspection['firebase_component_registrars']),
            }
        )
    if apk_inspection['dex_entry_count_with_indicators']:
        native_packaging_findings.append(
            {
                'code': 'FIREBASE_DEX_CLASSES_PRESENT',
                'dex_entry_count': apk_inspection['dex_entry_count_with_indicators'],
            }
        )
    if apk_inspection['crashlytics_native_library_count']:
        native_packaging_findings.append(
            {
                'code': 'CRASHLYTICS_NATIVE_LIBRARIES_PRESENT',
                'library_count': apk_inspection['crashlytics_native_library_count'],
            }
        )
    if apk_inspection['firebase_packaged_resource_count']:
        native_packaging_findings.append(
            {
                'code': 'FIREBASE_PACKAGED_RESOURCES_PRESENT',
                'resource_count': apk_inspection['firebase_packaged_resource_count'],
            }
        )

    native_startup_findings: list[dict[str, Any]] = []
    if startup_inspection.get('native_indicator_counts'):
        native_startup_findings.append(
            {
                'code': 'NATIVE_FIREBASE_STARTUP_LOG_INDICATORS_PRESENT',
                'indicator_counts': startup_inspection['native_indicator_counts'],
            }
        )

    missing_evidence = []
    if manifest_inspection.get('status') == 'missing':
        missing_evidence.append({'code': 'MERGED_MANIFEST_NOT_SUPPLIED'})
    if startup_inspection.get('status') == 'missing':
        missing_evidence.append({'code': 'STARTUP_LOG_NOT_SUPPLIED'})
    required_evidence = {
        'apk_present': True,
        'merged_manifest_present': manifest_inspection.get('status') != 'missing',
        'startup_log_present': startup_inspection.get('status') != 'missing',
        'complete': not missing_evidence,
    }

    native_packaging_present = bool(native_packaging_findings)
    native_startup_indicators_present = bool(native_startup_findings)
    native_firebase_evidence_present = native_packaging_present or native_startup_indicators_present
    fully_disabled = not native_firebase_evidence_present and not missing_evidence
    manifest_overlay_record = _optional_file_record(manifest_removal_overlay)
    dependency_overlay_record = _optional_file_record(dependency_removal_overlay)
    overlay_evidence_present = bool(
        (manifest_overlay_record and manifest_overlay_record.get('present'))
        or (dependency_overlay_record and dependency_overlay_record.get('present'))
    )
    report = {
        'schema_version': SCHEMA_VERSION,
        'task_id': TASK_ID,
        'generated_at_utc': generated_at_utc or _utc_now(),
        'run_id': run_id,
        'xaman_commit': xaman_commit,
        'inspection_scope': {
            'android_variant': 'debug',
            'artifact_role': 'testnet_verifier_apk',
            'claim_under_test': 'native Firebase initialization is absent or classified as a hard boundary',
            'production_usable': False,
        },
        'inputs': {
            'apk': _input_record(InputFile(apk)),
            'merged_manifest': _input_record(InputFile(manifest, required=False)) if manifest else None,
            'startup_log': _input_record(InputFile(startup_log, required=False)) if startup_log else None,
            'build_kit_manifest': (
                _input_record(InputFile(build_kit_manifest, required=False)) if build_kit_manifest else None
            ),
            'testnet_js_telemetry_report': (
                _input_record(InputFile(telemetry_report, required=False)) if telemetry_report else None
            ),
            'manifest_removal_overlay': manifest_overlay_record,
            'dependency_removal_overlay': dependency_overlay_record,
        },
        'inspection_methods': [
            'APK ZIP central-directory scan for DEX, packaged resources, and native libraries',
            'raw DEX byte scan for Firebase and React Native Firebase class descriptors',
            'Gradle merged-manifest XML parse for providers, services, receivers, and component registrars',
            'startup-log indicator counts with raw lines omitted and line hashes retained',
        ],
        'required_evidence': required_evidence,
        'javascript_boundary': js_boundary,
        'manifest_inspection': manifest_inspection,
        'apk_inspection': apk_inspection,
        'startup_log_inspection': startup_inspection,
        'external_removal_assessment': {
            'status': _external_removal_status(
                fully_disabled=fully_disabled,
                native_packaging_present=native_packaging_present,
                native_startup_indicators_present=native_startup_indicators_present,
                missing_evidence=missing_evidence,
                overlay_evidence_present=overlay_evidence_present,
            ),
            'overlay_evidence_present': overlay_evidence_present,
            'manifest_removal_overlay_present': bool(
                manifest_overlay_record and manifest_overlay_record.get('present')
            ),
            'dependency_removal_overlay_present': bool(
                dependency_overlay_record and dependency_overlay_record.get('present')
            ),
            'proof_requirement': (
                'A verifier-only manifest/dependency overlay must be followed by this audit showing zero native '
                'Firebase manifest indicators, DEX indicators, packaged Firebase resources, and Crashlytics '
                'native libraries, plus no native Firebase startup-log indicators.'
            ),
        },
        'native_packaging_present': native_packaging_present,
        'native_startup_indicators_present': native_startup_indicators_present,
        'native_firebase_evidence_present': native_firebase_evidence_present,
        'native_firebase_fully_disabled': fully_disabled,
        'overall_status': 'pass' if fully_disabled else 'blocked',
        'security_decision': _security_decision(
            fully_disabled=fully_disabled,
            native_packaging_present=native_packaging_present,
            native_startup_indicators_present=native_startup_indicators_present,
            missing_evidence=missing_evidence,
        ),
        'device_trial_label_allowed': _device_trial_label(
            fully_disabled=fully_disabled,
            missing_evidence=missing_evidence,
        ),
        'blockers': native_packaging_findings + native_startup_findings + missing_evidence,
        'boundary_statement': _boundary_statement(
            fully_disabled=fully_disabled,
            native_firebase_evidence_present=native_firebase_evidence_present,
            missing_evidence=missing_evidence,
        ),
    }
    report['artifact_cid'] = _artifact_cid(report)
    return report


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apk', type=Path, required=True, help='generated debug APK to inspect')
    parser.add_argument('--merged-manifest', type=Path, help='plain Gradle merged AndroidManifest.xml')
    parser.add_argument('--startup-log', type=Path, help='startup logcat capture to inspect')
    parser.add_argument('--build-kit-manifest', type=Path, help='PORTAL-CXTP-119 generated kit manifest')
    parser.add_argument('--telemetry-report', type=Path, help='PORTAL-CXTP-120 JavaScript stub telemetry report')
    parser.add_argument(
        '--manifest-removal-overlay',
        type=Path,
        help='optional verifier-only Android manifest overlay used to remove native Firebase components',
    )
    parser.add_argument(
        '--dependency-removal-overlay',
        type=Path,
        help='optional verifier-only Gradle/dependency overlay used to remove native Firebase packaging',
    )
    parser.add_argument('--run-id', default='xaman-native-firebase-boundary')
    parser.add_argument('--xaman-commit', default=PINNED_XAMAN_COMMIT)
    parser.add_argument('--generated-at-utc')
    parser.add_argument('--out', type=Path, default=DEFAULT_OUT)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    report = build_report(
        apk_path=args.apk,
        merged_manifest_path=args.merged_manifest,
        startup_log_path=args.startup_log,
        build_kit_manifest_path=args.build_kit_manifest,
        telemetry_report_path=args.telemetry_report,
        manifest_removal_overlay_path=args.manifest_removal_overlay,
        dependency_removal_overlay_path=args.dependency_removal_overlay,
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
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == '__main__':  # pragma: no cover
    raise SystemExit(main())
