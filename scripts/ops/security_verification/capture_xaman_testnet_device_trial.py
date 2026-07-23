#!/usr/bin/env python3
"""Assemble a redacted Xaman public-Testnet device-trial report.

This verifier consumes the Firebase-disabled Testnet build evidence, local
DuckDB telemetry, Testnet network-selection proof, and native Firebase boundary
audit. It records a Testnet-only device trial without raw credentials, account
addresses, endpoints, payloads, transaction blobs, or request bodies.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Mapping, Sequence


SCHEMA_VERSION = 'xaman-testnet-device-trial/v1'
TASK_ID = 'PORTAL-CXTP-121'
PINNED_XAMAN_COMMIT = '942f43876265a7af44f233288ad2b1d00841d5fa'
DEFAULT_VERIFIER_ROOT = Path('/home/barberb/.local/share/ipfs-datasets-xaman-testnet-verifier')
DEFAULT_APK = DEFAULT_VERIFIER_ROOT / 'xaman-app/android/app/build/outputs/apk/debug/app-x86_64-debug.apk'
DEFAULT_DUCKDB = DEFAULT_VERIFIER_ROOT / 'testnet-telemetry.duckdb'
DEFAULT_AVD = DEFAULT_VERIFIER_ROOT / 'avd/ipfs_xaman_api34_testnet.avd'
DEFAULT_BUILD_MANIFEST = DEFAULT_VERIFIER_ROOT / 'firebase-disabled-testnet-kit/testnet-build-manifest.json'
DEFAULT_OUTPUT_METADATA = DEFAULT_VERIFIER_ROOT / 'xaman-app/android/app/build/outputs/apk/debug/output-metadata.json'
DEFAULT_SIGNING_CONFIG = (
    DEFAULT_VERIFIER_ROOT
    / 'xaman-app/android/app/build/intermediates/signing_config_versions/debug/signing-config-versions.json'
)
DEFAULT_DEBUG_KEYSTORE = DEFAULT_VERIFIER_ROOT / 'xaman-app/android/app/debug.keystore'
DEFAULT_TELEMETRY_REPORT = Path(
    'security_ir_artifacts/corpora/xaman-app/runtime/testnet-telemetry-report.json'
)
DEFAULT_NETWORK_REPORT = Path(
    'security_ir_artifacts/corpora/xaman-app/runtime/testnet-network-selection-report.json'
)
DEFAULT_NATIVE_FIREBASE_REPORT = Path(
    'security_ir_artifacts/corpora/xaman-app/runtime/native-firebase-boundary-report.json'
)
DEFAULT_OUT = Path('security_ir_artifacts/corpora/xaman-app/runtime/testnet-device-trial-report.json')
DEFAULT_APK_DIGEST_OUT = DEFAULT_VERIFIER_ROOT / 'testnet-device-apk-digest.json'
DEFAULT_SCREENSHOTS = (
    DEFAULT_VERIFIER_ROOT / 'xaman-testnet-launch.png',
    DEFAULT_VERIFIER_ROOT / 'xaman-testnet-bundled.png',
    DEFAULT_VERIFIER_ROOT / 'xaman-testnet-firebase-disabled.png',
)

IDENTIFIER_RE = re.compile(r'^[A-Za-z0-9_.:-]{1,160}$')
GENERATED_AT_UTC_RE = re.compile(r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$')
SHA256_RE = re.compile(r'^[a-f0-9]{64}$')
SHA256_CID_RE = re.compile(r'^sha256:[a-f0-9]{64}$')
XRPL_ADDRESS_RE = re.compile(r'\br[1-9A-HJ-NP-Za-km-z]{24,35}\b')
XRPL_XADDRESS_RE = re.compile(r'\b[XT][1-9A-HJ-NP-Za-km-z]{40,60}\b')
XRPL_SEED_RE = re.compile(r'\bs[1-9A-HJ-NP-Za-km-z]{25,35}\b')
RAW_WSS_ENDPOINT_RE = re.compile(r'\bwss://[A-Za-z0-9.:-]+(?:/[^\s"\'<>]*)?\b')
JWT_RE = re.compile(r'\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b')
BEARER_TOKEN_RE = re.compile(r'\bBearer\s+[A-Za-z0-9._~+/=-]{8,}\b', re.IGNORECASE)
LONG_TRANSACTION_HEX_RE = re.compile(r'\b[A-Fa-f0-9]{128,}\b')


class TrialEvidenceError(ValueError):
    """Raised when input evidence crosses the redaction boundary."""


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


def _load_json(path: Path) -> dict[str, Any]:
    raw = path.read_bytes()
    try:
        parsed = json.loads(raw.decode('utf-8'))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f'input is not valid UTF-8 JSON: {path}') from exc
    if not isinstance(parsed, dict):
        raise ValueError(f'input JSON must be an object: {path}')
    return parsed


def _file_record(path: Path | None) -> dict[str, Any] | None:
    if path is None:
        return None
    resolved = path.resolve()
    if not resolved.is_file():
        return {'path': resolved.as_posix(), 'present': False}
    return {
        'path': resolved.as_posix(),
        'present': True,
        'sha256': _sha256_file(resolved),
        'size_bytes': resolved.stat().st_size,
    }


def _report_record(path: Path, *, expected_task_id: str, expected_schema: str) -> dict[str, Any]:
    record = _file_record(path)
    if record is None or not record.get('present'):
        return {'path': path.resolve().as_posix(), 'present': False}
    payload = _load_json(path)
    return {
        **record,
        'schema_version': payload.get('schema_version'),
        'task_id': payload.get('task_id'),
        'artifact_cid': payload.get('artifact_cid'),
        'expected_schema_version': expected_schema,
        'expected_task_id': expected_task_id,
        'schema_matches_expected': payload.get('schema_version') == expected_schema,
        'task_matches_expected': payload.get('task_id') == expected_task_id,
    }


def _safe_dependency_summaries(
    *,
    build_manifest_path: Path,
    telemetry_report_path: Path,
    network_report_path: Path,
    native_firebase_report_path: Path,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    build_manifest = _load_json(build_manifest_path)
    telemetry_report = _load_json(telemetry_report_path)
    network_report = _load_json(network_report_path)
    native_report = _load_json(native_firebase_report_path)

    telemetry_duckdb = telemetry_report.get('duckdb') if isinstance(telemetry_report.get('duckdb'), Mapping) else {}
    endpoint_decision = network_report.get('endpoint_allow_list_decision')
    endpoint_decision = endpoint_decision if isinstance(endpoint_decision, Mapping) else {}
    selection = network_report.get('selection') if isinstance(network_report.get('selection'), Mapping) else {}
    fresh_account = network_report.get('fresh_account_boundary')
    fresh_account = fresh_account if isinstance(fresh_account, Mapping) else {}
    xrpl = network_report.get('xrpl_server_info_binding')
    xrpl = xrpl if isinstance(xrpl, Mapping) else {}

    build_summary = {
        'record': _report_record(
            build_manifest_path,
            expected_task_id='PORTAL-CXTP-119',
            expected_schema='xaman-firebase-disabled-testnet-build/v1',
        ),
        'artifact_cid': build_manifest.get('artifact_cid'),
        'firebase_mode': build_manifest.get('firebase_mode'),
        'ledger_network': build_manifest.get('ledger_network'),
        'runtime_constraints': build_manifest.get('runtime_constraints') or {},
        'xaman_root_sha256': _sha256_bytes(str(build_manifest.get('xaman_root', '')).encode('utf-8')),
    }
    telemetry_summary = {
        'record': _report_record(
            telemetry_report_path,
            expected_task_id='PORTAL-CXTP-120',
            expected_schema='xaman-firebase-disabled-testnet-telemetry/v1',
        ),
        'run_id': telemetry_report.get('run_id'),
        'xaman_commit': telemetry_report.get('xaman_commit'),
        'build_provenance_sha256': telemetry_report.get('build_provenance_sha256'),
        'firebase_mode': telemetry_report.get('firebase_mode'),
        'telemetry_sink': telemetry_report.get('telemetry_sink'),
        'accepted_event_count': telemetry_report.get('accepted_event_count'),
        'rejected_event_count': telemetry_report.get('rejected_event_count'),
        'security_decision': telemetry_report.get('security_decision'),
        'duckdb_sha256': telemetry_duckdb.get('sha256'),
    }
    network_summary = {
        'record': _report_record(
            network_report_path,
            expected_task_id='PORTAL-CXTP-125',
            expected_schema='xaman-testnet-network-selection/v1',
        ),
        'run_id': network_report.get('run_id'),
        'overall_status': network_report.get('overall_status'),
        'security_decision': network_report.get('security_decision'),
        'xaman_commit': network_report.get('xaman_commit'),
        'build_provenance_sha256': network_report.get('build_provenance_sha256'),
        'selected_network_key': selection.get('network_key'),
        'selection_evidence_type': selection.get('evidence_type'),
        'event_categories': selection.get('event_categories') or [],
        'endpoint_allow_list_decision': {
            'allowed': endpoint_decision.get('allowed'),
            'matched_endpoint_key': endpoint_decision.get('matched_endpoint_key'),
            'matched_endpoint_sha256': endpoint_decision.get('matched_endpoint_sha256'),
            'allow_list_version': endpoint_decision.get('allow_list_version'),
        },
        'xrpl_server_info_binding': {
            'request_category': xrpl.get('request_category'),
            'request_sha256': xrpl.get('request_sha256'),
            'network_id': xrpl.get('network_id'),
            'network_id_verified': xrpl.get('network_id_verified'),
            'response_sha256': xrpl.get('response_sha256'),
            'raw_response_recorded': xrpl.get('raw_response_recorded'),
            'raw_request_body_recorded': xrpl.get('raw_request_body_recorded'),
        },
        'fresh_account_boundary': {
            'fresh_account_created': fresh_account.get('fresh_account_created'),
            'imported_account': fresh_account.get('imported_account'),
            'production_account': fresh_account.get('production_account'),
            'account_material_recorded': fresh_account.get('account_material_recorded'),
            'boundary': fresh_account.get('boundary'),
        },
    }
    native_summary = {
        'record': _report_record(
            native_firebase_report_path,
            expected_task_id='PORTAL-CXTP-126',
            expected_schema='xaman-native-firebase-boundary/v1',
        ),
        'run_id': native_report.get('run_id'),
        'overall_status': native_report.get('overall_status'),
        'security_decision': native_report.get('security_decision'),
        'xaman_commit': native_report.get('xaman_commit'),
        'native_firebase_fully_disabled': native_report.get('native_firebase_fully_disabled'),
        'native_firebase_evidence_present': native_report.get('native_firebase_evidence_present'),
        'native_packaging_present': native_report.get('native_packaging_present'),
        'native_startup_indicators_present': native_report.get('native_startup_indicators_present'),
        'device_trial_label_allowed': native_report.get('device_trial_label_allowed'),
        'blocker_codes': [
            blocker.get('code')
            for blocker in native_report.get('blockers', [])
            if isinstance(blocker, Mapping) and isinstance(blocker.get('code'), str)
        ],
    }
    return build_summary, telemetry_summary, network_summary, native_summary


def _output_metadata_summary(path: Path, apk_name: str) -> dict[str, Any]:
    record = _file_record(path)
    if record is None or not record.get('present'):
        return {'record': record, 'matched_output': None, 'variant_name': None}
    payload = _load_json(path)
    elements = payload.get('elements')
    matched: dict[str, Any] | None = None
    if isinstance(elements, list):
        for element in elements:
            if isinstance(element, Mapping) and element.get('outputFile') == apk_name:
                matched = {
                    'type': element.get('type'),
                    'filters': element.get('filters') or [],
                    'version_code': element.get('versionCode'),
                    'version_name': element.get('versionName'),
                    'output_file': element.get('outputFile'),
                }
                break
    return {
        'record': record,
        'variant_name': payload.get('variantName'),
        'application_id_sha256': _sha256_bytes(str(payload.get('applicationId', '')).encode('utf-8')),
        'matched_output': matched,
    }


def _signing_summary(
    *,
    apk_path: Path,
    output_metadata_path: Path,
    signing_config_path: Path,
    debug_keystore_path: Path,
) -> dict[str, Any]:
    output_metadata = _output_metadata_summary(output_metadata_path, apk_path.name)
    signing_config_record = _file_record(signing_config_path)
    debug_keystore_record = _file_record(debug_keystore_path)
    signing_config: dict[str, Any] = {}
    if signing_config_path.is_file():
        signing_config = _load_json(signing_config_path)

    debug_variant = output_metadata.get('variant_name') == 'debug'
    debug_named_apk = apk_path.name.endswith('-debug.apk')
    debug_keystore_present = bool(debug_keystore_record and debug_keystore_record.get('present'))
    signing_config_present = bool(signing_config_record and signing_config_record.get('present'))
    debug_signed_evidence_present = (
        debug_variant and debug_named_apk and debug_keystore_present and signing_config_present
    )
    return {
        'debug_signed_evidence_present': debug_signed_evidence_present,
        'debug_variant': debug_variant,
        'debug_named_apk': debug_named_apk,
        'output_metadata': output_metadata,
        'signing_config_versions': {
            'record': signing_config_record,
            'enable_v1_signing': signing_config.get('enableV1Signing'),
            'enable_v2_signing': signing_config.get('enableV2Signing'),
            'enable_v3_signing': signing_config.get('enableV3Signing'),
            'enable_v4_signing': signing_config.get('enableV4Signing'),
        },
        'debug_keystore': debug_keystore_record,
    }


def _avd_summary(path: Path) -> dict[str, Any]:
    resolved = path.resolve()
    if not resolved.is_dir():
        return {'path': resolved.as_posix(), 'present': False}
    selected_files = ['config.ini', 'hardware-qemu.ini', 'emu-launch-params.txt', 'bootcompleted.ini']
    return {
        'path': resolved.as_posix(),
        'present': True,
        'profile_name': resolved.name,
        'selected_file_records': {
            name: _file_record(resolved / name)
            for name in selected_files
            if (resolved / name).is_file()
        },
        'isolated_profile_evidence': 'local_external_verifier_avd_profile',
    }


def _screenshot_records(paths: Sequence[Path]) -> list[dict[str, Any]]:
    records = []
    for path in paths:
        record = _file_record(path)
        if record is not None:
            records.append(record)
    return records


def _duckdb_summary(path: Path) -> dict[str, Any]:
    record = _file_record(path)
    if record is None or not record.get('present'):
        return {'record': record, 'inspection_status': 'missing'}
    summary: dict[str, Any] = {'record': record, 'inspection_status': 'not_available'}
    try:
        import duckdb  # type: ignore
    except ImportError:
        summary['inspection_status'] = 'duckdb_python_unavailable'
        return summary

    try:
        con = duckdb.connect(path.as_posix(), read_only=True)
        tables = sorted(row[0] for row in con.execute('show tables').fetchall())
        summary['tables'] = tables
        required = {'xaman_testnet_events', 'xaman_testnet_rejections', 'xaman_testnet_runs'}
        summary['required_tables_present'] = sorted(required & set(tables))
        summary['missing_required_tables'] = sorted(required - set(tables))
        if not required <= set(tables):
            summary['inspection_status'] = 'required_tables_missing'
            return summary
        run = con.execute(
            'select run_id, xaman_commit, build_provenance_sha256, ledger_network, ledger_endpoint, '
            'firebase_mode, event_log_sha256, accepted_event_count, rejected_event_count '
            'from xaman_testnet_runs order by run_id limit 1'
        ).fetchone()
        event_rows = con.execute(
            'select category, event_name, outcome from xaman_testnet_events order by ordinal'
        ).fetchall()
        summary['inspection_status'] = 'read_only_verified'
        summary['event_count'] = con.execute('select count(*) from xaman_testnet_events').fetchone()[0]
        summary['rejection_count'] = con.execute('select count(*) from xaman_testnet_rejections').fetchone()[0]
        if run is not None:
            summary['run'] = {
                'run_id': run[0],
                'xaman_commit': run[1],
                'build_provenance_sha256': run[2],
                'ledger_network': run[3],
                'ledger_endpoint_sha256': _sha256_bytes(str(run[4]).encode('utf-8')),
                'firebase_mode': run[5],
                'event_log_sha256': run[6],
                'accepted_event_count': run[7],
                'rejected_event_count': run[8],
            }
        summary['observed_events'] = [
            {'category': row[0], 'event_name': row[1], 'outcome': row[2]} for row in event_rows
        ]
    except Exception as exc:  # pragma: no cover - depends on host DuckDB/runtime errors
        summary['inspection_status'] = 'read_only_inspection_failed'
        summary['error_class'] = type(exc).__name__
    return summary


def _dependency_blockers(
    *,
    apk_record: Mapping[str, Any],
    apk_expected_sha256: str | None,
    duckdb: Mapping[str, Any],
    telemetry: Mapping[str, Any],
    network: Mapping[str, Any],
    native: Mapping[str, Any],
    signing: Mapping[str, Any],
    avd: Mapping[str, Any],
    build: Mapping[str, Any],
) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    if apk_record.get('present') is not True:
        blockers.append({'code': 'VERIFIER_APK_MISSING'})
    elif apk_expected_sha256 and apk_record.get('sha256') != apk_expected_sha256:
        blockers.append({'code': 'VERIFIER_APK_DIGEST_MISMATCH'})

    for name, summary in (
        ('BUILD_MANIFEST', build),
        ('TESTNET_TELEMETRY_REPORT', telemetry),
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

    if signing.get('debug_signed_evidence_present') is not True:
        blockers.append({'code': 'DEBUG_SIGNED_VERIFIER_EVIDENCE_MISSING'})
    if avd.get('present') is not True:
        blockers.append({'code': 'ISOLATED_AVD_PROFILE_MISSING'})

    runtime_constraints = build.get('runtime_constraints') if isinstance(build.get('runtime_constraints'), Mapping) else {}
    if runtime_constraints.get('production_usable') is not False:
        blockers.append({'code': 'BUILD_MANIFEST_PRODUCTION_BOUNDARY_NOT_FALSE'})
    if runtime_constraints.get('firebase_gradle_tasks_disabled') is not True:
        blockers.append({'code': 'FIREBASE_GRADLE_TASK_DISABLEMENT_NOT_EVIDENCED'})
    if not runtime_constraints.get('firebase_js_modules_stubbed'):
        blockers.append({'code': 'FIREBASE_JS_STUBS_NOT_EVIDENCED'})

    if telemetry.get('xaman_commit') != PINNED_XAMAN_COMMIT:
        blockers.append({'code': 'TELEMETRY_COMMIT_MISMATCH'})
    if telemetry.get('build_provenance_sha256') != apk_expected_sha256:
        blockers.append({'code': 'TELEMETRY_APK_DIGEST_MISMATCH'})
    if telemetry.get('telemetry_sink') != 'duckdb':
        blockers.append({'code': 'TELEMETRY_SINK_NOT_DUCKDB'})
    if telemetry.get('accepted_event_count') != 4:
        blockers.append({'code': 'TELEMETRY_ACCEPTED_EVENT_COUNT_UNEXPECTED'})
    if telemetry.get('rejected_event_count') != 0:
        blockers.append({'code': 'TELEMETRY_REJECTIONS_PRESENT'})

    duckdb_record = duckdb.get('record') if isinstance(duckdb.get('record'), Mapping) else {}
    if duckdb_record.get('present') is not True:
        blockers.append({'code': 'LOCAL_DUCKDB_TELEMETRY_DATABASE_MISSING'})
    elif telemetry.get('duckdb_sha256') and duckdb_record.get('sha256') != telemetry.get('duckdb_sha256'):
        blockers.append({'code': 'LOCAL_DUCKDB_DIGEST_MISMATCH'})
    if duckdb.get('inspection_status') not in {'read_only_verified', 'duckdb_python_unavailable'}:
        blockers.append({'code': 'LOCAL_DUCKDB_READ_ONLY_INSPECTION_FAILED'})
    if duckdb.get('inspection_status') == 'read_only_verified':
        if duckdb.get('event_count') != telemetry.get('accepted_event_count'):
            blockers.append({'code': 'LOCAL_DUCKDB_EVENT_COUNT_MISMATCH'})
        if duckdb.get('rejection_count') != telemetry.get('rejected_event_count'):
            blockers.append({'code': 'LOCAL_DUCKDB_REJECTION_COUNT_MISMATCH'})
        run = duckdb.get('run') if isinstance(duckdb.get('run'), Mapping) else {}
        if run.get('xaman_commit') != PINNED_XAMAN_COMMIT:
            blockers.append({'code': 'LOCAL_DUCKDB_RUN_COMMIT_MISMATCH'})
        if run.get('build_provenance_sha256') != apk_expected_sha256:
            blockers.append({'code': 'LOCAL_DUCKDB_APK_DIGEST_MISMATCH'})
        if run.get('ledger_network') != 'testnet':
            blockers.append({'code': 'LOCAL_DUCKDB_LEDGER_NETWORK_NOT_TESTNET'})
        if run.get('firebase_mode') != 'disabled':
            blockers.append({'code': 'LOCAL_DUCKDB_FIREBASE_MODE_NOT_DISABLED'})

    if network.get('overall_status') != 'verified':
        blockers.append({'code': 'TESTNET_NETWORK_SELECTION_NOT_VERIFIED'})
    if network.get('selected_network_key') != 'TESTNET':
        blockers.append({'code': 'SELECTED_NETWORK_NOT_TESTNET'})
    endpoint_decision = network.get('endpoint_allow_list_decision')
    endpoint_decision = endpoint_decision if isinstance(endpoint_decision, Mapping) else {}
    if endpoint_decision.get('allowed') is not True:
        blockers.append({'code': 'XRPL_TESTNET_ENDPOINT_NOT_ALLOW_LISTED'})
    xrpl = network.get('xrpl_server_info_binding')
    xrpl = xrpl if isinstance(xrpl, Mapping) else {}
    if xrpl.get('network_id_verified') is not True or xrpl.get('network_id') != 1:
        blockers.append({'code': 'XRPL_SERVER_INFO_NETWORK_ID_NOT_TESTNET'})
    if xrpl.get('raw_response_recorded') is not False or xrpl.get('raw_request_body_recorded') is not False:
        blockers.append({'code': 'XRPL_RAW_REQUEST_OR_RESPONSE_RECORDED'})
    fresh = network.get('fresh_account_boundary')
    fresh = fresh if isinstance(fresh, Mapping) else {}
    if fresh.get('fresh_account_created') is not True:
        blockers.append({'code': 'FRESH_TESTNET_ACCOUNT_CREATION_NOT_EVIDENCED'})
    if fresh.get('imported_account') is not False or fresh.get('production_account') is not False:
        blockers.append({'code': 'FRESH_ACCOUNT_BOUNDARY_VIOLATED'})
    if fresh.get('account_material_recorded') is not False:
        blockers.append({'code': 'ACCOUNT_MATERIAL_RECORDED'})

    if native.get('native_firebase_evidence_present') is not True:
        blockers.append({'code': 'NATIVE_FIREBASE_BOUNDARY_EVIDENCE_MISSING'})
    if native.get('device_trial_label_allowed') not in {'firebase_js_stubbed_only', 'firebase_disabled'}:
        blockers.append({'code': 'NATIVE_FIREBASE_DEVICE_LABEL_NOT_ALLOWED'})

    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for blocker in blockers:
        code = str(blocker.get('code'))
        if code in seen:
            continue
        seen.add(code)
        deduped.append(blocker)
    return deduped


def _assert_report_redaction_boundary(report: Mapping[str, Any]) -> None:
    rendered = json.dumps(report, sort_keys=True, separators=(',', ':'))
    if RAW_WSS_ENDPOINT_RE.search(rendered):
        raise TrialEvidenceError('device trial report contains a raw WebSocket endpoint')
    if XRPL_ADDRESS_RE.search(rendered):
        raise TrialEvidenceError('device trial report contains an account address')
    if XRPL_XADDRESS_RE.search(rendered):
        raise TrialEvidenceError('device trial report contains an X-address')
    if XRPL_SEED_RE.search(rendered):
        raise TrialEvidenceError('device trial report contains a family seed')
    if JWT_RE.search(rendered) or BEARER_TOKEN_RE.search(rendered):
        raise TrialEvidenceError('device trial report contains credential material')
    if LONG_TRANSACTION_HEX_RE.search(rendered):
        raise TrialEvidenceError('device trial report contains a transaction-sized hex blob')


def build_report(
    *,
    apk_path: Path | str = DEFAULT_APK,
    duckdb_path: Path | str = DEFAULT_DUCKDB,
    avd_path: Path | str = DEFAULT_AVD,
    build_manifest_path: Path | str = DEFAULT_BUILD_MANIFEST,
    telemetry_report_path: Path | str = DEFAULT_TELEMETRY_REPORT,
    network_report_path: Path | str = DEFAULT_NETWORK_REPORT,
    native_firebase_report_path: Path | str = DEFAULT_NATIVE_FIREBASE_REPORT,
    output_metadata_path: Path | str = DEFAULT_OUTPUT_METADATA,
    signing_config_path: Path | str = DEFAULT_SIGNING_CONFIG,
    debug_keystore_path: Path | str = DEFAULT_DEBUG_KEYSTORE,
    screenshot_paths: Sequence[Path | str] = DEFAULT_SCREENSHOTS,
    run_id: str = 'xaman-testnet-device-trial-20260710',
    xaman_commit: str = PINNED_XAMAN_COMMIT,
    generated_at_utc: str | None = None,
) -> dict[str, Any]:
    if not IDENTIFIER_RE.fullmatch(run_id):
        raise ValueError('run_id must be a short identifier containing only letters, digits, . _ : or -')
    if xaman_commit != PINNED_XAMAN_COMMIT:
        raise ValueError('xaman_commit must match the pinned Xaman corpus commit')
    if generated_at_utc is not None and not GENERATED_AT_UTC_RE.fullmatch(generated_at_utc):
        raise ValueError('generated_at_utc must use UTC second precision, e.g. 2026-07-10T00:00:00Z')

    apk = Path(apk_path).resolve()
    duckdb_path = Path(duckdb_path).resolve()
    avd_path = Path(avd_path).resolve()
    build_manifest_path = Path(build_manifest_path).resolve()
    telemetry_report_path = Path(telemetry_report_path).resolve()
    network_report_path = Path(network_report_path).resolve()
    native_firebase_report_path = Path(native_firebase_report_path).resolve()
    output_metadata_path = Path(output_metadata_path).resolve()
    signing_config_path = Path(signing_config_path).resolve()
    debug_keystore_path = Path(debug_keystore_path).resolve()
    screenshot_paths = [Path(path).resolve() for path in screenshot_paths]

    build, telemetry, network, native = _safe_dependency_summaries(
        build_manifest_path=build_manifest_path,
        telemetry_report_path=telemetry_report_path,
        network_report_path=network_report_path,
        native_firebase_report_path=native_firebase_report_path,
    )
    apk_record = _file_record(apk) or {'present': False}
    apk_expected_sha256 = telemetry.get('build_provenance_sha256')
    if not isinstance(apk_expected_sha256, str) or SHA256_RE.fullmatch(apk_expected_sha256) is None:
        apk_expected_sha256 = None
    signing = _signing_summary(
        apk_path=apk,
        output_metadata_path=output_metadata_path,
        signing_config_path=signing_config_path,
        debug_keystore_path=debug_keystore_path,
    )
    avd = _avd_summary(avd_path)
    duckdb = _duckdb_summary(duckdb_path)
    screenshots = _screenshot_records(screenshot_paths)
    evidence_blockers = _dependency_blockers(
        apk_record=apk_record,
        apk_expected_sha256=apk_expected_sha256,
        duckdb=duckdb,
        telemetry=telemetry,
        network=network,
        native=native,
        signing=signing,
        avd=avd,
        build=build,
    )

    trial_evidence_complete = not evidence_blockers
    full_firebase_disabled_label_blocked = native.get('native_firebase_fully_disabled') is not True
    device_label = native.get('device_trial_label_allowed') or 'not_allowed'
    overall_status = 'executed_with_boundaries' if trial_evidence_complete else 'blocked'
    report = {
        'schema_version': SCHEMA_VERSION,
        'task_id': TASK_ID,
        'generated_at_utc': generated_at_utc or _utc_now(),
        'run_id': run_id,
        'xaman_commit': xaman_commit,
        'overall_status': overall_status,
        'security_decision': (
            'TESTNET_DEVICE_TRIAL_EXECUTED_JS_FIREBASE_STUBBED_NOT_PRODUCTION_EVIDENCE'
            if trial_evidence_complete
            else 'BLOCK_TESTNET_DEVICE_TRIAL_EVIDENCE_FAILURE'
        ),
        'trial_scope': {
            'network': 'XRPL_TESTNET',
            'network_id': 1,
            'production_usable': False,
            'real_assets_allowed': False,
            'account_policy': 'fresh_testnet_only_no_import_or_persistence_of_account_material',
            'device_trial_label': device_label,
            'full_firebase_disabled_label_blocked': full_firebase_disabled_label_blocked,
        },
        'verifier_artifact': {
            'apk': apk_record,
            'expected_apk_sha256': apk_expected_sha256,
            'digest_matches_telemetry_report': (
                apk_record.get('present') is True
                and isinstance(apk_expected_sha256, str)
                and apk_record.get('sha256') == apk_expected_sha256
            ),
            'signing': signing,
        },
        'device_profile': {
            'isolated_android_emulator': avd,
            'install_evidence': {
                'status': 'derived_from_local_device_capture_artifacts',
                'adb_install_transcript_recorded': False,
                'review_boundary': 'requires human review before production or runtime-equivalence acceptance',
            },
            'screenshots': screenshots,
        },
        'approved_non_production_wallet_flow': {
            'network_selection': network,
            'fresh_testnet_credentials': network.get('fresh_account_boundary'),
            'xrpl_request_trace': network.get('xrpl_server_info_binding'),
            'transaction_lifecycle_trace': {
                'status': 'not_captured_in_this_trial',
                'follow_on_task': 'PORTAL-CXTP-130',
            },
        },
        'telemetry': {
            'report': telemetry,
            'duckdb': duckdb,
            'redacted_local_telemetry_only': True,
        },
        'firebase_boundary': {
            'build_and_js_stub_evidence': build,
            'native_boundary_report': native,
            'native_firebase_fully_disabled': native.get('native_firebase_fully_disabled'),
            'classification': (
                'firebase_js_stubbed_only'
                if full_firebase_disabled_label_blocked
                else 'firebase_disabled'
            ),
        },
        'redaction_boundary': {
            'account_addresses_recorded': False,
            'seeds_recorded': False,
            'credentials_recorded': False,
            'payloads_recorded': False,
            'transaction_blobs_recorded': False,
            'raw_request_bodies_recorded': False,
            'raw_xrpl_endpoint_recorded': False,
            'raw_server_info_response_recorded': False,
            'stored_values': [
                'event_categories',
                'network_key',
                'endpoint_key',
                'file_sha256',
                'request_response_sha256',
                'aggregate_counts',
                'non_secret_local_paths',
            ],
        },
        'blocking_gaps': evidence_blockers,
        'residual_boundaries': [
            {
                'code': 'PRODUCTION_ACCEPTANCE_BLOCKED',
                'reason': 'This is public-Testnet verifier evidence only and cannot approve production release behavior.',
            },
            {
                'code': 'RUNTIME_EQUIVALENCE_NOT_PROVED',
                'reason': 'The debug verifier artifact and emulator capture do not prove equivalence to a production runtime.',
            },
            {
                'code': 'FULL_FIREBASE_DISABLED_LABEL_BLOCKED',
                'reason': (
                    'Native Firebase packaging remains present in the inspected APK.'
                    if full_firebase_disabled_label_blocked
                    else 'No native Firebase packaging boundary is active for this report.'
                ),
                'active': full_firebase_disabled_label_blocked,
            },
            {
                'code': 'TRANSACTION_LIFECYCLE_TRACE_NOT_CAPTURED',
                'reason': 'Payload review, signing, submit, decline, cancel, expiry, and reconnect flows are deferred to PORTAL-CXTP-130.',
            },
        ],
    }
    _assert_report_redaction_boundary(report)
    report['artifact_cid'] = _artifact_cid(report)
    return report


def _apk_digest_record(report: Mapping[str, Any]) -> dict[str, Any]:
    apk = report.get('verifier_artifact', {}).get('apk', {})  # type: ignore[union-attr]
    signing = report.get('verifier_artifact', {}).get('signing', {})  # type: ignore[union-attr]
    return {
        'schema_version': 'xaman-testnet-device-apk-digest/v1',
        'task_id': TASK_ID,
        'run_id': report.get('run_id'),
        'xaman_commit': report.get('xaman_commit'),
        'apk': apk,
        'debug_signed_evidence_present': signing.get('debug_signed_evidence_present')
        if isinstance(signing, Mapping)
        else None,
        'production_usable': False,
    }


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apk', type=Path, default=DEFAULT_APK)
    parser.add_argument('--duckdb', type=Path, default=DEFAULT_DUCKDB)
    parser.add_argument('--avd', type=Path, default=DEFAULT_AVD)
    parser.add_argument('--build-manifest', type=Path, default=DEFAULT_BUILD_MANIFEST)
    parser.add_argument('--telemetry-report', type=Path, default=DEFAULT_TELEMETRY_REPORT)
    parser.add_argument('--network-report', type=Path, default=DEFAULT_NETWORK_REPORT)
    parser.add_argument('--native-firebase-report', type=Path, default=DEFAULT_NATIVE_FIREBASE_REPORT)
    parser.add_argument('--output-metadata', type=Path, default=DEFAULT_OUTPUT_METADATA)
    parser.add_argument('--signing-config', type=Path, default=DEFAULT_SIGNING_CONFIG)
    parser.add_argument('--debug-keystore', type=Path, default=DEFAULT_DEBUG_KEYSTORE)
    parser.add_argument('--screenshot', action='append', type=Path, dest='screenshots')
    parser.add_argument('--run-id', default='xaman-testnet-device-trial-20260710')
    parser.add_argument('--xaman-commit', default=PINNED_XAMAN_COMMIT)
    parser.add_argument('--generated-at-utc')
    parser.add_argument('--out', type=Path, default=DEFAULT_OUT)
    parser.add_argument('--apk-digest-out', type=Path, default=DEFAULT_APK_DIGEST_OUT)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    report = build_report(
        apk_path=args.apk,
        duckdb_path=args.duckdb,
        avd_path=args.avd,
        build_manifest_path=args.build_manifest,
        telemetry_report_path=args.telemetry_report,
        network_report_path=args.network_report,
        native_firebase_report_path=args.native_firebase_report,
        output_metadata_path=args.output_metadata,
        signing_config_path=args.signing_config,
        debug_keystore_path=args.debug_keystore,
        screenshot_paths=args.screenshots or DEFAULT_SCREENSHOTS,
        run_id=args.run_id,
        xaman_commit=args.xaman_commit,
        generated_at_utc=args.generated_at_utc,
    )
    _write_json(args.out, report)
    _write_json(args.apk_digest_out, _apk_digest_record(report))
    print(
        json.dumps(
            {
                'out': args.out.as_posix(),
                'apk_digest_out': args.apk_digest_out.as_posix(),
                'overall_status': report['overall_status'],
                'security_decision': report['security_decision'],
                'artifact_cid': report['artifact_cid'],
            },
            sort_keys=True,
        )
    )
    return 0 if report['overall_status'] == 'executed_with_boundaries' else 2


if __name__ == '__main__':
    raise SystemExit(main())
