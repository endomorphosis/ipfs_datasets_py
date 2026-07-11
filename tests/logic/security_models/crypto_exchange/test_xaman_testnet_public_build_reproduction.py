"""Tests for PORTAL-CXTP-149 Xaman public Testnet build reproduction."""

from __future__ import annotations

import json
from pathlib import Path

from ipfs_datasets_py.logic.security_models.crypto_exchange.reports.xaman_testnet_public_build_reproduction import (
    ENVIRONMENT_SCHEMA_VERSION,
    PINNED_XAMAN_COMMIT,
    PUBLIC_BUILD_DOC_PATH,
    PUBLIC_BUILD_ENVIRONMENT_PATH,
    PUBLIC_BUILD_REPRODUCTION_PATH,
    REPRODUCTION_SCHEMA_VERSION,
    TASK_ID,
    TESTNET_DEBUG_APK_SHA256,
    generate_public_build_reproduction,
)


REPO_ROOT = Path(__file__).resolve().parents[4]


def _load_json(rel_path: str) -> dict:
    return json.loads((REPO_ROOT / rel_path).read_text(encoding='utf-8'))


def test_public_build_reproduction_artifacts_are_regenerable() -> None:
    generated_environment, generated_reproduction, generated_doc = generate_public_build_reproduction(REPO_ROOT)
    checked_environment = _load_json(PUBLIC_BUILD_ENVIRONMENT_PATH)
    checked_reproduction = _load_json(PUBLIC_BUILD_REPRODUCTION_PATH)
    checked_doc = (REPO_ROOT / PUBLIC_BUILD_DOC_PATH).read_text(encoding='utf-8')

    assert generated_environment == checked_environment
    assert generated_reproduction == checked_reproduction
    assert generated_doc == checked_doc
    assert checked_environment['schema_version'] == ENVIRONMENT_SCHEMA_VERSION
    assert checked_reproduction['schema_version'] == REPRODUCTION_SCHEMA_VERSION
    assert checked_environment['task_id'] == TASK_ID
    assert checked_reproduction['task_id'] == TASK_ID
    assert checked_environment['artifact_cid']
    assert checked_reproduction['artifact_cid']


def test_locked_environment_records_android_gradle_node_java_and_sdk_inputs() -> None:
    environment = _load_json(PUBLIC_BUILD_ENVIRONMENT_PATH)
    toolchain = environment['locked_toolchain']

    assert environment['source_pin']['commit_sha'] == PINNED_XAMAN_COMMIT
    assert environment['source_pin']['commit_matches_expected'] is True
    assert toolchain['java']['required_major_version'] == 17
    assert toolchain['java']['recorded_version'] == '17.0.18+8'
    assert toolchain['android_sdk']['android_home']
    assert toolchain['gradle']['wrapper'] == 'android/gradlew'
    assert toolchain['gradle']['wrapper_properties'] == 'android/gradle/wrapper/gradle-wrapper.properties'
    assert toolchain['node']['version'] == '24.18.0'
    assert toolchain['npm']['version'] == '11.16.0'

    build_files = {
        entry['path']: entry
        for entry in environment['build_inputs']['android_build_files']
    }
    for path in {
        'android/build.gradle',
        'android/app/build.gradle',
        'android/settings.gradle',
        'android/gradle.properties',
        'android/gradle/wrapper/gradle-wrapper.properties',
        'android/gradlew',
        'package.json',
        'package-lock.json',
    }:
        assert build_files[path]['present_in_public_source_manifest'] is True
        assert build_files[path]['sha256']


def test_dependency_resolution_and_verifier_only_patches_are_explicit() -> None:
    environment = _load_json(PUBLIC_BUILD_ENVIRONMENT_PATH)
    reproduction = _load_json(PUBLIC_BUILD_REPRODUCTION_PATH)

    assert environment['dependency_resolution']['npm']['lockfile_path'] == 'package-lock.json'
    assert environment['dependency_resolution']['npm']['lockfile_sha256'] == (
        'f27be60a558a178d6fefec5fb0cab13ff4c196d13b96c3406d600f32277b458a'
    )
    gradle_graph = environment['dependency_resolution']['gradle']['restored_release_runtime_graph']
    assert {entry['module'] for entry in gradle_graph} >= {
        'com.google.mlkit:barcode-scanning',
        'com.google.android.gms:play-services-mlkit-text-recognition',
        'com.google.mlkit:vision-common',
    }

    patch_ids = {patch['id'] for patch in environment['verifier_only_patches']}
    assert patch_ids == {
        'firebase_gradle_tasks_disabled',
        'firebase_js_module_stubs',
        'react_native_navigation_compatibility_overlay',
        'mlkit_dependency_resolution_strategy',
    }
    assert reproduction['verifier_only_patches'] == environment['verifier_only_patches']
    assert all(patch['production_equivalence_preserved'] is False for patch in environment['verifier_only_patches'])


def test_build_outcome_apk_digest_and_missing_dependencies_fail_closed() -> None:
    reproduction = _load_json(PUBLIC_BUILD_REPRODUCTION_PATH)
    apk = reproduction['apk_digest']['primary_testnet_debug_verifier_apk']
    missing = reproduction['missing_credentials_and_service_dependencies']

    assert reproduction['overall_status'] == 'blocked'
    assert reproduction['security_decision'] == 'BLOCK_PUBLIC_TESTNET_BUILD_REPRODUCTION_NOT_VENDOR_RELEASE_EQUIVALENT'
    assert reproduction['build_outcome']['status'] == 'blocked_public_reproduction_not_vendor_equivalent'
    assert reproduction['build_outcome']['command_executed_by_this_artifact'] is False
    assert reproduction['build_outcome']['recorded_prior_verifier_build_evidence'] is True
    assert reproduction['summary']['missing_credential_or_service_dependency_count'] == len(missing) >= 8

    assert apk['sha256'] == TESTNET_DEBUG_APK_SHA256
    assert apk['digest_matches_expected'] is True
    assert apk['production_usable'] is False
    assert reproduction['apk_digest']['transaction_trial_digest_matches'] is True
    assert len(reproduction['apk_digest']['release_r8_verifier_apks']) == 5
    assert all(
        apk_entry['production_signing_claim'] is False
        for apk_entry in reproduction['apk_digest']['release_r8_verifier_apks']
    )

    missing_ids = {entry['id'] for entry in missing}
    assert {
        'production_android_signing_keystore',
        'production_android_signing_passwords',
        'android_google_services_json',
        'crashlytics_upload_mapping_credentials',
        'firebase_analytics_messaging_crashlytics_project',
        'xaman_backend_payload_api',
        'vendor_ci_release_environment',
        'vendor_release_binary_or_store_bundle',
        'xrpl_testnet_public_endpoint_availability',
    } <= missing_ids


def test_public_build_is_never_classified_as_vendor_release_equivalent() -> None:
    environment = _load_json(PUBLIC_BUILD_ENVIRONMENT_PATH)
    reproduction = _load_json(PUBLIC_BUILD_REPRODUCTION_PATH)

    assert environment['scope']['vendor_release_equivalence_claimed'] is False
    assert environment['policy']['vendor_release_equivalence_allowed'] is False
    assert environment['policy']['production_release_approval'] is False
    assert reproduction['scope']['vendor_release_equivalent'] is False
    assert reproduction['scope']['vendor_release_equivalence_claimed'] is False
    assert reproduction['scope']['production_release_approval'] is False
    assert reproduction['equivalence_policy']['public_build_equivalent_to_vendor_release'] is False
    assert reproduction['equivalence_policy']['vendor_release_equivalence_claim_allowed'] is False
    assert 'vendor_release_equivalent' in reproduction['equivalence_policy']['forbidden_classifications']


def test_documentation_records_locked_reproduction_and_non_equivalence() -> None:
    doc = (REPO_ROOT / PUBLIC_BUILD_DOC_PATH).read_text(encoding='utf-8')

    assert TASK_ID in doc
    assert PUBLIC_BUILD_ENVIRONMENT_PATH in doc
    assert PUBLIC_BUILD_REPRODUCTION_PATH in doc
    assert PINNED_XAMAN_COMMIT in doc
    assert TESTNET_DEBUG_APK_SHA256 in doc
    assert 'not a vendor release reproduction' in doc
    assert 'public_build_equivalent_to_vendor_release' in doc
    assert 'vendor_release_equivalent' in doc
