"""Locked public-build reproduction record for the Xaman Testnet verifier."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from ..ir.cid import calculate_artifact_cid


TASK_ID = 'PORTAL-CXTP-149'
GENERATED_AT_UTC = '2026-07-11T00:00:00Z'
ENVIRONMENT_SCHEMA_VERSION = 'xaman-testnet-public-build-environment/v1'
REPRODUCTION_SCHEMA_VERSION = 'xaman-testnet-public-build-reproduction/v1'

XAMAN_ROOT = 'security_ir_artifacts/corpora/xaman-app'
TESTNET_ROOT = f'{XAMAN_ROOT}/testnet'
RUNTIME_ROOT = f'{XAMAN_ROOT}/runtime'
SOURCE_MANIFEST_PATH = f'{XAMAN_ROOT}/source-manifest.json'
SOURCE_COVERAGE_PATH = f'{XAMAN_ROOT}/source-coverage.json'
ENVIRONMENT_PROBE_PATH = f'{XAMAN_ROOT}/environment-probe.json'
PUBLIC_SOURCE_REFRESH_PATH = f'{XAMAN_ROOT}/public-source-refresh.json'
TESTNET_DEVICE_TRIAL_PATH = f'{RUNTIME_ROOT}/testnet-device-trial-report.json'
TESTNET_TRANSACTION_TRIAL_PATH = f'{RUNTIME_ROOT}/testnet-transaction-trial-report.json'
NATIVE_FIREBASE_BOUNDARY_PATH = f'{RUNTIME_ROOT}/native-firebase-boundary-report.json'
RELEASE_R8_REPORT_PATH = f'{RUNTIME_ROOT}/release-r8-dependency-report.json'

PUBLIC_BUILD_ENVIRONMENT_PATH = f'{TESTNET_ROOT}/public-build-environment.json'
PUBLIC_BUILD_REPRODUCTION_PATH = f'{TESTNET_ROOT}/public-build-reproduction.json'
PUBLIC_BUILD_DOC_PATH = 'docs/security_verification/xaman_testnet_public_build_reproduction.md'

PINNED_XAMAN_COMMIT = '942f43876265a7af44f233288ad2b1d00841d5fa'
TESTNET_DEBUG_APK_SHA256 = 'c22cd33b580dd0ecd8b8c5529b42169dccb79676ac396cda8af448d31810a41d'

ANDROID_BUILD_FILES = (
    'android/build.gradle',
    'android/app/build.gradle',
    'android/settings.gradle',
    'android/gradle.properties',
    'android/gradle/wrapper/gradle-wrapper.properties',
    'android/gradle/wrapper/gradle-wrapper.jar',
    'android/gradlew',
    'package.json',
    'package-lock.json',
)

MISSING_CREDENTIALS_AND_SERVICES = (
    {
        'id': 'production_android_signing_keystore',
        'kind': 'credential',
        'required_for': 'vendor release equivalence and production distribution signing',
        'public_reproduction_status': 'absent',
        'verifier_substitute': 'debug keystore for Testnet debug APK and verifier-only one-day release keystore for R8 evidence',
        'blocks_vendor_release_equivalence': True,
    },
    {
        'id': 'production_android_signing_passwords',
        'kind': 'credential',
        'required_for': 'unlocking the vendor signing key and proving signing lineage',
        'public_reproduction_status': 'absent',
        'verifier_substitute': 'temporary verifier signing inputs only',
        'blocks_vendor_release_equivalence': True,
    },
    {
        'id': 'android_google_services_json',
        'kind': 'credential_or_service_config',
        'required_for': 'Google Services Gradle processing against the vendor Firebase project',
        'public_reproduction_status': 'absent',
        'verifier_substitute': 'Google Services Gradle tasks disabled for the verifier build',
        'blocks_vendor_release_equivalence': True,
    },
    {
        'id': 'crashlytics_upload_mapping_credentials',
        'kind': 'credential_or_service_config',
        'required_for': 'Crashlytics mapping upload and release crash reporting integration',
        'public_reproduction_status': 'absent',
        'verifier_substitute': 'Crashlytics upload tasks disabled for the verifier build',
        'blocks_vendor_release_equivalence': True,
    },
    {
        'id': 'firebase_analytics_messaging_crashlytics_project',
        'kind': 'service_dependency',
        'required_for': 'runtime equivalence for Firebase-backed analytics, messaging, installation, and crash reporting components',
        'public_reproduction_status': 'not_connected_to_vendor_project',
        'verifier_substitute': 'JavaScript Firebase module stubs with native Firebase packaging still present',
        'blocks_vendor_release_equivalence': True,
    },
    {
        'id': 'xaman_backend_payload_api',
        'kind': 'service_dependency',
        'required_for': 'payload creation, payload status, backend single-use, expiry, and submission semantics',
        'public_reproduction_status': 'not_available_from_public_source',
        'verifier_substitute': 'redacted Testnet lifecycle observations only',
        'blocks_vendor_release_equivalence': True,
    },
    {
        'id': 'vendor_ci_release_environment',
        'kind': 'service_dependency',
        'required_for': 'proving the public checkout was built with the same CI variables, caches, secrets, and release orchestration as the vendor release',
        'public_reproduction_status': 'absent',
        'verifier_substitute': 'local locked verifier environment recorded in this artifact',
        'blocks_vendor_release_equivalence': True,
    },
    {
        'id': 'vendor_release_binary_or_store_bundle',
        'kind': 'evidence_dependency',
        'required_for': 'byte or signature comparison against a distributed vendor APK/AAB',
        'public_reproduction_status': 'absent',
        'verifier_substitute': 'locally recorded Testnet verifier APK digest only',
        'blocks_vendor_release_equivalence': True,
    },
    {
        'id': 'xrpl_testnet_public_endpoint_availability',
        'kind': 'service_dependency',
        'required_for': 'runtime Testnet network probing and transaction lifecycle observations',
        'public_reproduction_status': 'observed_as_redacted_endpoint_digest_only',
        'verifier_substitute': 'endpoint key and request/response digests; no raw endpoint or payload retained',
        'blocks_vendor_release_equivalence': False,
    },
)


def _file_sha256(repo_root: Path, rel_path: str) -> str | None:
    path = repo_root / rel_path
    if not path.is_file():
        return None
    return 'sha256:' + hashlib.sha256(path.read_bytes()).hexdigest()


def _load_json(repo_root: Path, rel_path: str, *, required: bool = True) -> dict[str, Any] | None:
    path = repo_root / rel_path
    if not path.is_file():
        if required:
            raise FileNotFoundError(rel_path)
        return None
    payload = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(payload, dict):
        raise ValueError(f'{rel_path} did not contain a JSON object')
    return payload


def _artifact_cid_without_self(payload: Mapping[str, Any]) -> str:
    return calculate_artifact_cid({key: value for key, value in payload.items() if key != 'artifact_cid'})


def _artifact_ref(repo_root: Path, rel_path: str, payload: Mapping[str, Any] | None, *, kind: str) -> dict[str, Any]:
    return {
        'kind': kind,
        'path': rel_path,
        'present': payload is not None,
        'schema_version': payload.get('schema_version') if payload else None,
        'task_id': payload.get('task_id') if payload else None,
        'artifact_cid': payload.get('artifact_cid') if payload else None,
        'sha256': _file_sha256(repo_root, rel_path),
    }


def _manifest_file_index(manifest: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    return {
        str(entry['path']): entry
        for entry in manifest.get('files', [])
        if isinstance(entry, Mapping) and isinstance(entry.get('path'), str)
    }


def _manifest_entries(manifest: Mapping[str, Any], paths: Sequence[str]) -> list[dict[str, Any]]:
    index = _manifest_file_index(manifest)
    entries = []
    for path in paths:
        record = index.get(path)
        entries.append(
            {
                'path': path,
                'present_in_public_source_manifest': record is not None,
                'git_blob_sha1': record.get('git_blob_sha1') if record else None,
                'sha256': record.get('sha256') if record else None,
                'size_bytes': record.get('size_bytes') if record else None,
            }
        )
    return entries


def _lockfile_entries(manifest: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            'path': str(entry['path']),
            'sha256': entry.get('sha256'),
            'git_blob_sha1': entry.get('git_blob_sha1'),
            'size_bytes': entry.get('size_bytes'),
        }
        for entry in manifest.get('dependency_lockfiles', [])
        if isinstance(entry, Mapping) and isinstance(entry.get('path'), str)
    ]


def _env_probe_tool(env_probe: Mapping[str, Any], key: str) -> dict[str, Any]:
    assumptions = env_probe.get('assumptions', {})
    value = assumptions.get(key, {}) if isinstance(assumptions, Mapping) else {}
    value = value if isinstance(value, Mapping) else {}
    return {
        'status': value.get('status'),
        'executable': value.get('executable'),
        'version': value.get('version'),
        'source': ENVIRONMENT_PROBE_PATH,
    }


def _release_environment(release_r8_report: Mapping[str, Any]) -> Mapping[str, Any]:
    value = release_r8_report.get('build_environment', {})
    return value if isinstance(value, Mapping) else {}


def build_public_build_environment(
    *,
    repo_root: Path,
    source_manifest: Mapping[str, Any],
    source_coverage: Mapping[str, Any],
    environment_probe: Mapping[str, Any],
    release_r8_report: Mapping[str, Any],
    native_firebase_boundary: Mapping[str, Any],
) -> dict[str, Any]:
    """Build the locked environment record for the public Testnet verifier build."""

    release_env = _release_environment(release_r8_report)
    restored_graph = release_r8_report.get('restored_release_runtime_graph', [])
    restoration = release_r8_report.get('restoration', {})
    source = source_manifest.get('source', {})
    source = source if isinstance(source, Mapping) else {}
    summary = source_manifest.get('manifest_summary', {})
    summary = summary if isinstance(summary, Mapping) else {}

    payload: dict[str, Any] = {
        'schema_version': ENVIRONMENT_SCHEMA_VERSION,
        'task_id': TASK_ID,
        'generated_at_utc': GENERATED_AT_UTC,
        'corpus': 'xaman-app',
        'scope': {
            'platform': 'Android',
            'network': 'XRPL Testnet',
            'network_id': 1,
            'build_kind': 'public_source_testnet_verifier',
            'public_source_only': True,
            'vendor_release_equivalence_claimed': False,
            'production_security_result': False,
        },
        'source_pin': {
            'repo_url': source.get('repo_url'),
            'commit_sha': source.get('commit_sha'),
            'requested_ref': source.get('requested_ref'),
            'expected_commit_sha': PINNED_XAMAN_COMMIT,
            'exact_commit_required': True,
            'commit_matches_expected': source.get('commit_sha') == PINNED_XAMAN_COMMIT,
            'manifest_path': SOURCE_MANIFEST_PATH,
            'manifest_schema_version': source_manifest.get('schema_version'),
            'manifest_aggregate_sha256': summary.get('aggregate_sha256'),
            'manifest_file_count': summary.get('file_count'),
            'source_coverage_path': SOURCE_COVERAGE_PATH,
            'source_coverage_analysis_mode': source_coverage.get('analysis_mode'),
            'source_coverage_parsed_source_available': source_coverage.get('parsed_source_available', False),
        },
        'locked_toolchain': {
            'java': {
                'home': release_env.get('java_home'),
                'required_major_version': 17,
                'recorded_version': '17.0.18+8',
                'source': RELEASE_R8_REPORT_PATH,
            },
            'android_sdk': {
                'android_home': release_env.get('android_home'),
                'emulator_profile_api_level': 34,
                'source': RELEASE_R8_REPORT_PATH,
            },
            'gradle': {
                'wrapper': 'android/gradlew',
                'wrapper_properties': 'android/gradle/wrapper/gradle-wrapper.properties',
                'wrapper_jar': 'android/gradle/wrapper/gradle-wrapper.jar',
                'locked_by_public_source_manifest': True,
                'version_source': 'Gradle wrapper files are pinned by manifest digests; wrapper file contents are not embedded in this artifact.',
            },
            'node': _env_probe_tool(environment_probe, 'node_runtime'),
            'npm': _env_probe_tool(environment_probe, 'npm_runtime'),
            'typescript': _env_probe_tool(environment_probe, 'typescript_compiler'),
        },
        'build_inputs': {
            'android_build_files': _manifest_entries(source_manifest, ANDROID_BUILD_FILES),
            'dependency_lockfiles': _lockfile_entries(source_manifest),
            'required_dependency_lockfiles': summary.get('required_dependency_lockfiles', ['package-lock.json']),
        },
        'dependency_resolution': {
            'npm': {
                'method': 'package-lock based npm dependency resolution',
                'lockfile_path': 'package-lock.json',
                'lockfile_sha256': next(
                    (entry.get('sha256') for entry in _lockfile_entries(source_manifest) if entry['path'] == 'package-lock.json'),
                    None,
                ),
                'node_modules_embedded_in_artifact': False,
            },
            'gradle': {
                'method': 'Gradle wrapper with verifier-only init script overlays where production credentials are absent',
                'build_files': _manifest_entries(
                    source_manifest,
                    (
                        'android/build.gradle',
                        'android/app/build.gradle',
                        'android/settings.gradle',
                        'android/gradle.properties',
                    ),
                ),
                'restored_release_runtime_graph': restored_graph,
            },
            'native_local_inputs': restoration.get('tangem_local_dependency_inputs', []),
        },
        'verifier_only_patches': [
            {
                'id': 'firebase_gradle_tasks_disabled',
                'classification': 'verifier_only',
                'source': TESTNET_DEVICE_TRIAL_PATH,
                'purpose': 'Avoid requiring absent vendor Firebase configuration while producing a Testnet verifier APK.',
                'production_equivalence_preserved': False,
            },
            {
                'id': 'firebase_js_module_stubs',
                'classification': 'verifier_only',
                'source': TESTNET_DEVICE_TRIAL_PATH,
                'patched_modules': [
                    '@react-native-firebase/analytics',
                    '@react-native-firebase/crashlytics',
                    '@react-native-firebase/messaging',
                ],
                'native_firebase_fully_disabled': native_firebase_boundary.get('native_firebase_fully_disabled', False),
                'production_equivalence_preserved': False,
            },
            {
                'id': 'react_native_navigation_compatibility_overlay',
                'classification': 'verifier_only',
                'source': RELEASE_R8_REPORT_PATH,
                'sha256': (
                    restoration.get('non_mlkit_compatibility_overlay', {})
                    if isinstance(restoration.get('non_mlkit_compatibility_overlay', {}), Mapping)
                    else {}
                ).get('sha256'),
                'production_equivalence_preserved': False,
            },
            {
                'id': 'mlkit_dependency_resolution_strategy',
                'classification': 'verifier_only_release_r8',
                'source': RELEASE_R8_REPORT_PATH,
                'restored_versions': restoration.get('restored_versions', []),
                'production_equivalence_preserved': False,
            },
        ],
        'missing_credentials_and_service_dependencies': list(MISSING_CREDENTIALS_AND_SERVICES),
        'policy': {
            'public_build_must_not_be_classified_as_vendor_release': True,
            'vendor_release_equivalence_allowed': False,
            'production_release_approval': False,
            'raw_credentials_recorded': False,
            'fail_closed_when_credentials_or_service_dependencies_are_missing': True,
        },
    }
    payload['artifact_cid'] = _artifact_cid_without_self(payload)
    return payload


def build_public_build_reproduction(
    *,
    repo_root: Path,
    source_manifest: Mapping[str, Any],
    public_source_refresh: Mapping[str, Any],
    environment: Mapping[str, Any],
    testnet_device_trial: Mapping[str, Any],
    testnet_transaction_trial: Mapping[str, Any],
    native_firebase_boundary: Mapping[str, Any],
    release_r8_report: Mapping[str, Any],
) -> dict[str, Any]:
    """Build the fail-closed public-build reproduction record."""

    source = source_manifest.get('source', {})
    source = source if isinstance(source, Mapping) else {}
    verifier_artifact = testnet_device_trial.get('verifier_artifact', {})
    verifier_apk = {}
    if isinstance(verifier_artifact, Mapping):
        apk = verifier_artifact.get('apk', {})
        verifier_apk = apk if isinstance(apk, Mapping) else {}
    release_apks = release_r8_report.get('release_apks', [])
    release_apks = release_apks if isinstance(release_apks, list) else []

    missing = list(environment.get('missing_credentials_and_service_dependencies', []))
    build_outcome = {
        'status': 'blocked_public_reproduction_not_vendor_equivalent',
        'command_executed_by_this_artifact': False,
        'recorded_prior_verifier_build_evidence': True,
        'testnet_debug_apk_recorded': verifier_apk.get('sha256') == TESTNET_DEBUG_APK_SHA256,
        'release_r8_verifier_build_recorded': release_r8_report.get('status') == 'resolved_for_release_r8_verifier_build',
        'blocker_codes': [
            'PUBLIC_SOURCE_CHECKOUT_NOT_EMBEDDED_IN_REPOSITORY',
            'PRODUCTION_CREDENTIALS_AND_SERVICE_CONFIGS_ABSENT',
            'VERIFIER_ONLY_PATCHES_APPLIED',
            'VENDOR_RELEASE_BINARY_ABSENT',
        ],
    }
    payload: dict[str, Any] = {
        'schema_version': REPRODUCTION_SCHEMA_VERSION,
        'task_id': TASK_ID,
        'generated_at_utc': GENERATED_AT_UTC,
        'corpus': 'xaman-app',
        'taskboard': {
            'path': 'docs/security_verification/crypto_exchange_theorem_prover_taskboard.todo.md',
            'source_line': 1164,
            'depends_on': ['PORTAL-CXTP-143', 'PORTAL-CXTP-144'],
        },
        'scope': {
            'platform': 'Android',
            'network': 'XRPL Testnet',
            'network_id': 1,
            'public_source_only': True,
            'verifier_build_only': True,
            'vendor_release_equivalence_claimed': False,
            'vendor_release_equivalent': False,
            'production_release_approval': False,
            'production_security_result': False,
        },
        'source': {
            'repo_url': source.get('repo_url'),
            'commit_sha': source.get('commit_sha'),
            'requested_ref': source.get('requested_ref'),
            'expected_commit_sha': PINNED_XAMAN_COMMIT,
            'commit_matches_expected': source.get('commit_sha') == PINNED_XAMAN_COMMIT,
            'manifest_path': SOURCE_MANIFEST_PATH,
        },
        'input_artifacts': [
            _artifact_ref(repo_root, SOURCE_MANIFEST_PATH, source_manifest, kind='source_manifest'),
            _artifact_ref(repo_root, SOURCE_COVERAGE_PATH, _load_json(repo_root, SOURCE_COVERAGE_PATH, required=False), kind='source_coverage'),
            _artifact_ref(repo_root, ENVIRONMENT_PROBE_PATH, _load_json(repo_root, ENVIRONMENT_PROBE_PATH, required=False), kind='environment_probe'),
            _artifact_ref(repo_root, PUBLIC_SOURCE_REFRESH_PATH, public_source_refresh, kind='public_source_refresh'),
            _artifact_ref(repo_root, TESTNET_DEVICE_TRIAL_PATH, testnet_device_trial, kind='testnet_device_trial'),
            _artifact_ref(repo_root, TESTNET_TRANSACTION_TRIAL_PATH, testnet_transaction_trial, kind='testnet_transaction_trial'),
            _artifact_ref(repo_root, NATIVE_FIREBASE_BOUNDARY_PATH, native_firebase_boundary, kind='native_firebase_boundary'),
            _artifact_ref(repo_root, RELEASE_R8_REPORT_PATH, release_r8_report, kind='release_r8_dependency_report'),
            _artifact_ref(repo_root, PUBLIC_BUILD_ENVIRONMENT_PATH, environment, kind='public_build_environment'),
        ],
        'locked_environment': {
            'path': PUBLIC_BUILD_ENVIRONMENT_PATH,
            'schema_version': environment.get('schema_version'),
            'artifact_cid': environment.get('artifact_cid'),
            'toolchain': environment.get('locked_toolchain', {}),
        },
        'dependency_resolution': environment.get('dependency_resolution', {}),
        'verifier_only_patches': environment.get('verifier_only_patches', []),
        'build_plan': {
            'source_checkout': 'git clone --filter=blob:none --no-checkout https://github.com/XRPL-Labs/Xaman-App && git checkout 942f43876265a7af44f233288ad2b1d00841d5fa',
            'dependency_install': 'npm ci using the pinned package-lock.json',
            'android_debug_build': 'JAVA_HOME=<locked jdk17> ANDROID_HOME=<locked android sdk> ./gradlew app:assembleDebug --warning-mode=all',
            'release_r8_verifier_build': 'JAVA_HOME=<locked jdk17> ANDROID_HOME=<locked android sdk> ./gradlew app:assembleRelease --warning-mode=all --init-script <verifier-only init script>',
            'default_cli_behavior': 'record-only; no network clone or Gradle build is performed unless an external verifier runs the plan in the locked environment',
        },
        'build_outcome': build_outcome,
        'apk_digest': {
            'primary_testnet_debug_verifier_apk': {
                'path_label': 'android/app/build/outputs/apk/debug/app-x86_64-debug.apk',
                'sha256': verifier_apk.get('sha256'),
                'expected_sha256': TESTNET_DEBUG_APK_SHA256,
                'size_bytes': verifier_apk.get('size_bytes'),
                'present_in_prior_verifier_evidence': bool(verifier_apk.get('present')),
                'digest_matches_expected': verifier_apk.get('sha256') == TESTNET_DEBUG_APK_SHA256,
                'production_usable': False,
                'source_artifact': TESTNET_DEVICE_TRIAL_PATH,
            },
            'transaction_trial_digest_matches': testnet_transaction_trial.get('verifier_artifact', {}).get('digest_matches_device_report')
            if isinstance(testnet_transaction_trial.get('verifier_artifact', {}), Mapping)
            else None,
            'release_r8_verifier_apks': [
                {
                    'file': apk.get('file'),
                    'type': apk.get('type'),
                    'abi': apk.get('abi'),
                    'version_code': apk.get('version_code'),
                    'version_name': apk.get('version_name'),
                    'sha256': apk.get('sha256'),
                    'size_bytes': apk.get('size_bytes'),
                    'production_signing_claim': False,
                }
                for apk in release_apks
                if isinstance(apk, Mapping)
            ],
        },
        'missing_credentials_and_service_dependencies': missing,
        'equivalence_policy': {
            'public_build_equivalent_to_vendor_release': False,
            'vendor_release_equivalence_claim_allowed': False,
            'reason': 'The build uses public source and verifier-only substitutions, lacks vendor signing/Firebase/backend/CI evidence, and has no vendor release binary for byte or signature comparison.',
            'forbidden_classifications': [
                'vendor_release_equivalent',
                'production_release_approved',
                'production_security_approved',
                'app_store_binary_reproduced',
            ],
        },
        'summary': {
            'public_source_commit_recorded': source.get('commit_sha') == PINNED_XAMAN_COMMIT,
            'locked_environment_recorded': environment.get('schema_version') == ENVIRONMENT_SCHEMA_VERSION,
            'dependency_resolution_recorded': True,
            'verifier_only_patch_count': len(environment.get('verifier_only_patches', [])),
            'missing_credential_or_service_dependency_count': len(missing),
            'apk_digest_recorded': verifier_apk.get('sha256') == TESTNET_DEBUG_APK_SHA256,
            'vendor_release_equivalence': False,
        },
        'overall_status': 'blocked',
        'security_decision': 'BLOCK_PUBLIC_TESTNET_BUILD_REPRODUCTION_NOT_VENDOR_RELEASE_EQUIVALENT',
    }
    payload['artifact_cid'] = _artifact_cid_without_self(payload)
    return payload


def render_public_build_reproduction_markdown(environment: Mapping[str, Any], reproduction: Mapping[str, Any]) -> str:
    """Render the human-readable public-build reproduction note."""

    source = reproduction.get('source', {})
    apk = reproduction.get('apk_digest', {}).get('primary_testnet_debug_verifier_apk', {})
    missing = reproduction.get('missing_credentials_and_service_dependencies', [])
    patches = reproduction.get('verifier_only_patches', [])
    return f"""# Xaman Testnet Public Build Reproduction

Task: {TASK_ID}

This record reproduces the public Android Testnet verifier build evidence in a locked, fail-closed form. It is not a vendor release reproduction, not a production release approval, and not a production security decision.

## Source Pin

- Repository: `{source.get('repo_url')}`
- Commit: `{source.get('commit_sha')}`
- Manifest: `{SOURCE_MANIFEST_PATH}`
- Environment: `{PUBLIC_BUILD_ENVIRONMENT_PATH}`
- Reproduction report: `{PUBLIC_BUILD_REPRODUCTION_PATH}`

## Locked Environment

- Java: `{environment.get('locked_toolchain', {}).get('java', {}).get('recorded_version')}` at `{environment.get('locked_toolchain', {}).get('java', {}).get('home')}`
- Android SDK: `{environment.get('locked_toolchain', {}).get('android_sdk', {}).get('android_home')}`
- Gradle: wrapper-pinned by `android/gradlew` and `android/gradle/wrapper/gradle-wrapper.properties`
- Node: `{environment.get('locked_toolchain', {}).get('node', {}).get('version')}`
- npm: `{environment.get('locked_toolchain', {}).get('npm', {}).get('version')}`

## Build Outcome

The checked-in CLI records the build plan and prior verifier evidence without performing network clone, dependency download, or Gradle execution. The current result is `{reproduction.get('overall_status')}` with decision `{reproduction.get('security_decision')}`.

The recorded Testnet debug verifier APK digest is `{apk.get('sha256')}` for `{apk.get('path_label')}`. This digest is verifier evidence only and is marked `production_usable: false`.

## Verifier-Only Patches

{chr(10).join(f"- `{patch.get('id')}`: {patch.get('purpose') or patch.get('classification')}" for patch in patches)}

## Missing Credentials And Services

{chr(10).join(f"- `{item.get('id')}` ({item.get('kind')}): {item.get('required_for')}" for item in missing)}

## Non-Equivalence Policy

`public_build_equivalent_to_vendor_release` is `false`. The build lacks vendor signing keys, vendor Firebase configuration, backend service evidence, vendor CI provenance, and a vendor release binary for byte/signature comparison. It must never be promoted to `vendor_release_equivalent`, `production_release_approved`, or `app_store_binary_reproduced`.
"""


def generate_public_build_reproduction(repo_root: Path) -> tuple[dict[str, Any], dict[str, Any], str]:
    source_manifest = _load_json(repo_root, SOURCE_MANIFEST_PATH)
    source_coverage = _load_json(repo_root, SOURCE_COVERAGE_PATH)
    environment_probe = _load_json(repo_root, ENVIRONMENT_PROBE_PATH)
    public_source_refresh = _load_json(repo_root, PUBLIC_SOURCE_REFRESH_PATH)
    testnet_device_trial = _load_json(repo_root, TESTNET_DEVICE_TRIAL_PATH)
    testnet_transaction_trial = _load_json(repo_root, TESTNET_TRANSACTION_TRIAL_PATH)
    native_firebase_boundary = _load_json(repo_root, NATIVE_FIREBASE_BOUNDARY_PATH)
    release_r8_report = _load_json(repo_root, RELEASE_R8_REPORT_PATH)

    if (
        source_manifest is None
        or source_coverage is None
        or environment_probe is None
        or public_source_refresh is None
        or testnet_device_trial is None
        or testnet_transaction_trial is None
        or native_firebase_boundary is None
        or release_r8_report is None
    ):
        raise FileNotFoundError('required public build reproduction input artifact is missing')

    environment = build_public_build_environment(
        repo_root=repo_root,
        source_manifest=source_manifest,
        source_coverage=source_coverage,
        environment_probe=environment_probe,
        release_r8_report=release_r8_report,
        native_firebase_boundary=native_firebase_boundary,
    )
    reproduction = build_public_build_reproduction(
        repo_root=repo_root,
        source_manifest=source_manifest,
        public_source_refresh=public_source_refresh,
        environment=environment,
        testnet_device_trial=testnet_device_trial,
        testnet_transaction_trial=testnet_transaction_trial,
        native_firebase_boundary=native_firebase_boundary,
        release_r8_report=release_r8_report,
    )
    markdown = render_public_build_reproduction_markdown(environment, reproduction)
    return environment, reproduction, markdown
