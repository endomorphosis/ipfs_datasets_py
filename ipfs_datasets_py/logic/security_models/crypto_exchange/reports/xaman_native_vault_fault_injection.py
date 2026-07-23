"""Prepare and validate redacted Xaman native-vault rekey fault evidence.

The public sources show a recovery snapshot created before the primary vault is
removed.  This module prepares a verifier-only test contract for both the
replacement-write and recovery-cleanup fault boundaries.  It does not patch,
execute, or make a claim about a vendor release.
"""

from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import Any, Mapping

from ..ir.cid import calculate_artifact_cid


TASK_PREPARATION = 'PORTAL-CXTP-165'
TASK_RUNTIME = 'PORTAL-CXTP-163'
PLAN_SCHEMA_VERSION = 'xaman-native-vault-rekey-fault-injection-plan/v1'
TEMPLATE_SCHEMA_VERSION = 'xaman-native-vault-rekey-fault-injection-template/v1'
REPORT_SCHEMA_VERSION = 'xaman-native-vault-rekey-fault-injection-report/v1'
PINNED_XAMAN_COMMIT = '942f43876265a7af44f233288ad2b1d00841d5fa'

ANDROID_VAULT_SOURCE = 'android/app/src/main/java/libs/security/vault/VaultManagerModule.java'
ANDROID_TEST_SOURCE = 'android/app/src/androidTest/java/libs/security/vault/VaultMangerTest.java'
IOS_VAULT_SOURCE = 'ios/Xaman/Libs/Security/Vault/VaultManager.m'
IOS_TEST_SOURCE = 'ios/XamanTests/VaultMangerTest.m'

REQUIRED_CASES = (
    ('android-single-rekey-replacement-write-failure', 'android', 'single_rekey', 'replacement_write', 'single'),
    ('android-single-rekey-recovery-cleanup-failure', 'android', 'single_rekey', 'recovery_cleanup', 'single'),
    ('android-batch-rekey-replacement-write-failure-first-vault', 'android', 'batch_rekey', 'replacement_write', 'first'),
    ('android-batch-rekey-replacement-write-failure-later-vault', 'android', 'batch_rekey', 'replacement_write', 'later'),
    ('android-batch-rekey-recovery-cleanup-failure-first-vault', 'android', 'batch_rekey', 'recovery_cleanup', 'first'),
    ('android-batch-rekey-recovery-cleanup-failure-later-vault', 'android', 'batch_rekey', 'recovery_cleanup', 'later'),
    ('ios-single-rekey-replacement-write-failure', 'ios', 'single_rekey', 'replacement_write', 'single'),
    ('ios-single-rekey-recovery-cleanup-failure', 'ios', 'single_rekey', 'recovery_cleanup', 'single'),
    ('ios-batch-rekey-replacement-write-failure-first-vault', 'ios', 'batch_rekey', 'replacement_write', 'first'),
    ('ios-batch-rekey-replacement-write-failure-later-vault', 'ios', 'batch_rekey', 'replacement_write', 'later'),
    ('ios-batch-rekey-recovery-cleanup-failure-first-vault', 'ios', 'batch_rekey', 'recovery_cleanup', 'first'),
    ('ios-batch-rekey-recovery-cleanup-failure-later-vault', 'ios', 'batch_rekey', 'recovery_cleanup', 'later'),
)

CID_RE = re.compile(r'^b[a-z2-7]{20,}$')
SHA256_RE = re.compile(r'^[a-f0-9]{64}$')
TIMESTAMP_RE = re.compile(r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$')
IDENTIFIER_RE = re.compile(r'^[A-Za-z0-9_.:-]{1,160}$')
RAW_ENDPOINT_RE = re.compile(r'\b(?:wss?|https?)://[^\s"\'<>]+', re.IGNORECASE)
XRPL_ADDRESS_RE = re.compile(r'\br[1-9A-HJ-NP-Za-km-z]{24,35}\b')
XRPL_SEED_RE = re.compile(r'\bs[1-9A-HJ-NP-Za-km-z]{25,35}\b')
LONG_HEX_RE = re.compile(r'\b[A-Fa-f0-9]{128,}\b')
SENSITIVE_KEYS = frozenset(
    {
        'account', 'address', 'body', 'credential', 'endpoint', 'keymaterial',
        'mnemonic', 'passcode', 'password', 'payload', 'privatekey', 'rawlog',
        'seed', 'secret', 'transaction', 'txblob', 'wallet',
    }
)


class NativeVaultFaultInjectionError(ValueError):
    """Raised when native-vault fault evidence is unsafe or incomplete."""


def _cid_without(payload: Mapping[str, Any]) -> str:
    return calculate_artifact_cid({key: value for key, value in payload.items() if key != 'artifact_cid'})


def _exact(value: Any, expected: frozenset[str], *, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise NativeVaultFaultInjectionError(f'{field} must be an object')
    missing = expected - set(value)
    extra = set(value) - expected
    if missing or extra:
        detail = []
        if missing:
            detail.append(f'missing {sorted(missing)}')
        if extra:
            detail.append(f'unexpected {sorted(extra)}')
        raise NativeVaultFaultInjectionError(f'{field} has ' + '; '.join(detail))
    return value


def _digest(value: Any, *, field: str, cid: bool = False) -> str:
    pattern = CID_RE if cid else SHA256_RE
    if not isinstance(value, str) or not pattern.fullmatch(value):
        expected = 'content identifier' if cid else 'lowercase SHA-256 digest'
        raise NativeVaultFaultInjectionError(f'{field} must be a {expected}')
    if not cid and len(set(value)) == 1:
        raise NativeVaultFaultInjectionError(f'{field} must not be a repeated-character placeholder')
    return value


def _timestamp(value: Any, *, field: str) -> datetime:
    if not isinstance(value, str) or not TIMESTAMP_RE.fullmatch(value):
        raise NativeVaultFaultInjectionError(f'{field} must be a UTC second-resolution timestamp')
    try:
        return datetime.strptime(value, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise NativeVaultFaultInjectionError(f'{field} is invalid') from exc


def _no_sensitive_material(value: Any, *, field: str = 'report') -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            normalized = re.sub(r'[^a-z0-9]+', '', str(key).lower())
            if normalized in SENSITIVE_KEYS:
                raise NativeVaultFaultInjectionError(f'{field} contains prohibited sensitive key {key!r}')
            _no_sensitive_material(item, field=f'{field}.{key}')
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _no_sensitive_material(item, field=f'{field}[{index}]')
    elif isinstance(value, str) and any(pattern.search(value) for pattern in (RAW_ENDPOINT_RE, XRPL_ADDRESS_RE, XRPL_SEED_RE, LONG_HEX_RE)):
        raise NativeVaultFaultInjectionError(f'{field} contains raw sensitive material')


def _source_inputs(assessment: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    if assessment.get('task_id') != 'PORTAL-CXTP-162':
        raise NativeVaultFaultInjectionError('assessment is not the native-vault source assessment')
    if assessment.get('artifact_cid') is None:
        raise NativeVaultFaultInjectionError('assessment must be content addressed')
    _digest(assessment.get('artifact_cid'), field='assessment.artifact_cid', cid=True)
    scope = assessment.get('scope')
    if not isinstance(scope, Mapping) or scope.get('source_commit') != PINNED_XAMAN_COMMIT:
        raise NativeVaultFaultInjectionError('assessment is not bound to the pinned public source commit')
    if scope.get('public_source_only') is not True or scope.get('vendor_release_equivalent') is not False:
        raise NativeVaultFaultInjectionError('assessment does not preserve source-only scope')
    inputs = assessment.get('source_inputs')
    if not isinstance(inputs, list):
        raise NativeVaultFaultInjectionError('assessment source inputs are missing')
    by_path = {
        str(item.get('path')): item
        for item in inputs
        if isinstance(item, Mapping) and isinstance(item.get('path'), str)
    }
    for path in (ANDROID_VAULT_SOURCE, ANDROID_TEST_SOURCE, IOS_VAULT_SOURCE, IOS_TEST_SOURCE):
        item = by_path.get(path)
        if item is None:
            raise NativeVaultFaultInjectionError(f'assessment does not bind required source {path}')
        _digest(item.get('sha256'), field=f'assessment source digest {path}')
        if not isinstance(item.get('marker_lines'), Mapping):
            raise NativeVaultFaultInjectionError(f'assessment does not record source markers for {path}')
    return by_path


def _source_reference(source: Mapping[str, Any], marker: str) -> dict[str, Any]:
    marker_lines = source['marker_lines']
    line = marker_lines.get(marker)
    if not isinstance(line, int) or line < 1:
        raise NativeVaultFaultInjectionError(f'assessment does not bind marker {marker!r}')
    return {'path': source['path'], 'sha256': source['sha256'], 'line': line, 'marker': marker}


def _required_observations(fault_phase: str) -> list[str]:
    common = [
        'fault_injected',
        'native_operation_reports_failure',
        'recovery_vault_present_after_failure',
        'old_key_recovers_vault',
        'new_key_does_not_open_old_key_recovery',
        'no_raw_sensitive_material_retained',
    ]
    if fault_phase == 'replacement_write':
        return [
            *common[:2],
            'primary_vault_absent_after_failure',
            'primary_vault_new_key_accessible_false',
            *common[2:],
        ]
    if fault_phase == 'recovery_cleanup':
        return [
            *common[:2],
            'primary_vault_present_after_failure',
            'primary_vault_new_key_accessible',
            *common[2:],
        ]
    raise NativeVaultFaultInjectionError('unsupported fault phase')


def build_fault_injection_plan(assessment: Mapping[str, Any]) -> dict[str, Any]:
    """Bind a test-only fault plan to the public source assessment."""

    sources = _source_inputs(assessment)
    android = sources[ANDROID_VAULT_SOURCE]
    ios = sources[IOS_VAULT_SOURCE]
    plan: dict[str, Any] = {
        'schema_version': PLAN_SCHEMA_VERSION,
        'task_id': TASK_PREPARATION,
        'plan_status': 'PREPARED_NOT_RUNTIME_EVIDENCE',
        'target_task_id': TASK_RUNTIME,
        'source_bindings': {
            'native_vault_assessment_cid': assessment['artifact_cid'],
            'source_commit': PINNED_XAMAN_COMMIT,
            'android_vault_source_sha256': android['sha256'],
            'android_test_source_sha256': sources[ANDROID_TEST_SOURCE]['sha256'],
            'ios_vault_source_sha256': ios['sha256'],
            'ios_test_source_sha256': sources[IOS_TEST_SOURCE]['sha256'],
        },
        'fault_injection_points': [
            {
                'platform': 'android',
                'source_order': [
                    _source_reference(android, 'createVault(recoveryVaultName, clearText, oldKey);'),
                    _source_reference(android, 'purgeVault(vaultName);'),
                    _source_reference(android, 'createVault(vaultName, clearText, newKey);'),
                    _source_reference(android, '// finally remove the created recovery vault'),
                ],
                'test_target': {'path': ANDROID_TEST_SOURCE, 'sha256': sources[ANDROID_TEST_SOURCE]['sha256']},
                'fault_boundary': 'Inject verifier-only replacement-write and recovery-cleanup failures; do not modify vendor release artifacts.',
            },
            {
                'platform': 'ios',
                'source_order': [
                    _source_reference(ios, '[VaultManagerModule createVault:recoveryVaultName data:cleartext key:oldKey];'),
                    _source_reference(ios, '[VaultManagerModule purgeVault:vaultName];'),
                    _source_reference(ios, '[VaultManagerModule createVault:vaultName data:cleartext key:newKey];'),
                    _source_reference(ios, 'finally remove the created recovery vault'),
                ],
                'test_target': {'path': IOS_TEST_SOURCE, 'sha256': sources[IOS_TEST_SOURCE]['sha256']},
                'fault_boundary': 'Inject verifier-only replacement-write and recovery-cleanup failures; do not modify vendor release artifacts.',
            },
        ],
        'required_cases': [
            {
                'case_id': case_id,
                'platform': platform,
                'flow': flow,
                'fault_phase': fault_phase,
                'fault_position': fault_position,
                'required_observations': _required_observations(fault_phase),
            }
            for case_id, platform, flow, fault_phase, fault_position in REQUIRED_CASES
        ],
        'execution_requirements': {
            'review': 'A valid PORTAL-CXTP-156 independent decision must authorize verifier-only runtime capture and remain unexpired.',
            'android': 'Use a fresh verifier-only debug emulator with adb, emulator, and sdkmanager available; preserve an evidence digest only.',
            'ios': 'Use an isolated macOS/Xcode XCTest host; preserve an evidence digest only.',
            'test_data': 'Generate ephemeral non-wallet fixture data in the test harness and do not retain it in reports, logs, screenshots, or artifacts.',
        },
        'scope': {
            'public_source_verifier_only': True,
            'vendor_release_equivalent': False,
            'production_security_result': False,
            'runtime_capture_recorded': False,
        },
        'acceptance_boundary': 'This source-bound plan is not a fault-injection result and cannot establish vendor-release or production wallet security.',
    }
    plan['artifact_cid'] = _cid_without(plan)
    return plan


def build_fault_injection_template(plan: Mapping[str, Any]) -> dict[str, Any]:
    """Create a non-evidence collection template from a bound test plan."""

    if plan.get('schema_version') != PLAN_SCHEMA_VERSION or plan.get('task_id') != TASK_PREPARATION:
        raise NativeVaultFaultInjectionError('fault-injection plan schema or task identifier is invalid')
    _digest(plan.get('artifact_cid'), field='plan.artifact_cid', cid=True)
    return {
        'schema_version': TEMPLATE_SCHEMA_VERSION,
        'task_id': TASK_PREPARATION,
        'target_task_id': TASK_RUNTIME,
        'template_status': 'NOT_RUNTIME_EVIDENCE',
        'fault_injection_plan_cid': plan['artifact_cid'],
        'required_cases': plan['required_cases'],
        'review_gate_requirements': {
            'independent_review_task_id': 'PORTAL-CXTP-156',
            'required_decision': 'ALLOW_VERIFIER_ONLY_RUNTIME_CAPTURE',
            'unexpired_review_required': True,
        },
        'redaction_requirements': {
            'raw_sensitive_material_retained': False,
            'prohibited_material': [
                'passcodes', 'keys', 'account identifiers', 'wallet material', 'payloads',
                'transaction blobs', 'credentials', 'raw endpoints', 'raw logs', 'screenshots containing sensitive material',
            ],
        },
        'scope_requirements': plan['scope'],
        'acceptance_boundary': 'This template cannot authorize execution or create a runtime, vendor-release, or production security claim.',
    }


def validate_fault_injection_report(report: Mapping[str, Any], *, now: datetime | None = None) -> None:
    """Fail closed unless reviewed evidence covers every required fault boundary."""

    _exact(
        report,
        frozenset({
            'schema_version', 'task_id', 'report_id', 'captured_at_utc', 'reviewed_at_utc',
            'scope', 'source_bindings', 'review_gate', 'cases', 'redaction', 'artifact_cid',
        }),
        field='report',
    )
    if report.get('schema_version') != REPORT_SCHEMA_VERSION or report.get('task_id') != TASK_RUNTIME:
        raise NativeVaultFaultInjectionError('report schema or task identifier is invalid')
    if not isinstance(report.get('report_id'), str) or not IDENTIFIER_RE.fullmatch(report['report_id']):
        raise NativeVaultFaultInjectionError('report_id is invalid')
    captured_at = _timestamp(report.get('captured_at_utc'), field='captured_at_utc')
    reviewed_at = _timestamp(report.get('reviewed_at_utc'), field='reviewed_at_utc')
    reference_time = now or datetime.now(timezone.utc)
    if captured_at > reviewed_at or reviewed_at > reference_time:
        raise NativeVaultFaultInjectionError('report timestamps are not credible')

    scope = _exact(
        report.get('scope'),
        frozenset({'public_source_verifier_only', 'vendor_release_equivalent', 'production_security_result'}),
        field='scope',
    )
    if dict(scope) != {
        'public_source_verifier_only': True,
        'vendor_release_equivalent': False,
        'production_security_result': False,
    }:
        raise NativeVaultFaultInjectionError('report scope exceeds verifier-only evidence')
    bindings = _exact(
        report.get('source_bindings'),
        frozenset({'fault_injection_plan_cid', 'native_vault_assessment_cid', 'source_commit'}),
        field='source_bindings',
    )
    _digest(bindings.get('fault_injection_plan_cid'), field='source_bindings.fault_injection_plan_cid', cid=True)
    _digest(bindings.get('native_vault_assessment_cid'), field='source_bindings.native_vault_assessment_cid', cid=True)
    if bindings.get('source_commit') != PINNED_XAMAN_COMMIT:
        raise NativeVaultFaultInjectionError('report source commit is not pinned')

    gate = _exact(
        report.get('review_gate'),
        frozenset({'review_decision_cid', 'decision', 'expires_at_utc', 'reviewer_id_sha256'}),
        field='review_gate',
    )
    _digest(gate.get('review_decision_cid'), field='review_gate.review_decision_cid', cid=True)
    _digest(gate.get('reviewer_id_sha256'), field='review_gate.reviewer_id_sha256')
    if gate.get('decision') != 'ALLOW_VERIFIER_ONLY_RUNTIME_CAPTURE':
        raise NativeVaultFaultInjectionError('independent review does not authorize verifier-only capture')
    if _timestamp(gate.get('expires_at_utc'), field='review_gate.expires_at_utc') <= reference_time:
        raise NativeVaultFaultInjectionError('independent review is expired')

    cases = report.get('cases')
    if not isinstance(cases, list) or len(cases) != len(REQUIRED_CASES):
        raise NativeVaultFaultInjectionError('report must contain every required fault-injection case exactly once')
    expected = {
        case_id: (platform, flow, fault_phase, fault_position)
        for case_id, platform, flow, fault_phase, fault_position in REQUIRED_CASES
    }
    observed: set[str] = set()
    required_case_keys = frozenset(
        {
            'case_id', 'platform', 'flow', 'fault_phase', 'fault_position', 'fault_injected',
            'native_operation_reports_failure', 'primary_vault_absent_after_failure',
            'primary_vault_new_key_accessible', 'recovery_vault_present_after_failure',
            'old_key_recovers_vault', 'new_key_does_not_open_old_key_recovery',
            'raw_sensitive_material_retained', 'evidence_sha256',
        }
    )
    for item in cases:
        item = _exact(item, required_case_keys, field='case')
        case_id = item.get('case_id')
        if case_id in observed or case_id not in expected:
            raise NativeVaultFaultInjectionError('report has duplicate or unknown fault-injection case')
        if (
            item.get('platform'), item.get('flow'), item.get('fault_phase'), item.get('fault_position')
        ) != expected[case_id]:
            raise NativeVaultFaultInjectionError('fault-injection case platform, flow, phase, or position does not match the plan')
        fault_phase = item['fault_phase']
        expected_flags = {
            'fault_injected': True,
            'native_operation_reports_failure': True,
            'primary_vault_absent_after_failure': fault_phase == 'replacement_write',
            'primary_vault_new_key_accessible': fault_phase == 'recovery_cleanup',
            'recovery_vault_present_after_failure': True,
            'old_key_recovers_vault': True,
            'new_key_does_not_open_old_key_recovery': True,
            'raw_sensitive_material_retained': False,
        }
        for flag, expected_value in expected_flags.items():
            if item.get(flag) is not expected_value:
                raise NativeVaultFaultInjectionError(f'fault-injection case does not satisfy {flag}')
        _digest(item.get('evidence_sha256'), field=f'case {case_id} evidence_sha256')
        observed.add(case_id)
    if observed != set(expected):
        raise NativeVaultFaultInjectionError('report is missing a required fault-injection case')

    redaction = _exact(
        report.get('redaction'),
        frozenset({'raw_sensitive_material_retained', 'redaction_review_sha256'}),
        field='redaction',
    )
    if redaction.get('raw_sensitive_material_retained') is not False:
        raise NativeVaultFaultInjectionError('report retains raw sensitive material')
    _digest(redaction.get('redaction_review_sha256'), field='redaction.redaction_review_sha256')
    _no_sensitive_material(report)
    if report.get('artifact_cid') != _cid_without(report):
        raise NativeVaultFaultInjectionError('report artifact CID is invalid')
