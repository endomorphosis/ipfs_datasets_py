"""Source-bound native-vault assessment and rekey recovery solver lane.

The model in this module is intentionally small.  It captures the ordering of
the public Android and iOS ``reKeyVault`` implementations, not their native
cryptographic primitives, the mobile operating systems, or a released build.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import subprocess
from typing import Any, Mapping

from ..ir.cid import calculate_artifact_cid


TASK_ID = 'PORTAL-CXTP-162'
SCHEMA_VERSION = 'xaman-native-vault-public-source-assessment/v1'
SOURCE_MANIFEST_PATH = 'security_ir_artifacts/corpora/xaman-app/source-manifest.json'
REPORT_PATH = 'security_ir_artifacts/corpora/xaman-app/native-vault-public-source-assessment.json'
SMTLIB_PATH = 'security_ir_artifacts/corpora/xaman-app/native-vault/rekey-recovery.smt2'
GENERATED_AT_UTC = '2026-07-18T00:00:00Z'

REQUIRED_SOURCE_MARKERS: dict[str, tuple[str, ...]] = {
    'android/app/src/main/java/libs/security/vault/VaultManagerModule.java': (
        'VAULT_ALREADY_EXIST',
        'createVault(recoveryVaultName, clearText, oldKey);',
        'purgeVault(vaultName);',
        'createVault(vaultName, clearText, newKey);',
        '// finally remove the created recovery vault',
    ),
    'android/app/src/main/java/libs/security/vault/cipher/CipherV2AesGcm.java': (
        'Crypto.PBKDF2(key.toCharArray(), passcodeSalt, 91337)',
        'Crypto.PBKDF2(preKey, encrKeySalt, 33)',
        'Crypto.AESAlgo.GCM',
    ),
    'android/app/src/main/java/libs/security/vault/storage/cipherStorage/CipherStorageKeystoreAesGcm.java': (
        '.setBlockModes(BLOCK_MODE_GCM)',
        '.setRandomizedEncryptionRequired(true)',
        '.setKeySize(ENCRYPTION_KEY_SIZE)',
    ),
    'android/app/src/androidTest/java/libs/security/vault/VaultMangerTest.java': (
        'VaultRecoveryTest',
        'VaultReKeyTest',
    ),
    'ios/Xaman/Libs/Security/Vault/VaultManager.m': (
        'VAULT_ALREADY_EXIST',
        '[VaultManagerModule createVault:recoveryVaultName data:cleartext key:oldKey];',
        '[VaultManagerModule purgeVault:vaultName];',
        '[VaultManagerModule createVault:vaultName data:cleartext key:newKey];',
        'finally remove the created recovery vault',
    ),
    'ios/Xaman/Libs/Security/Vault/Cipher/V2+AesGcm.m': (
        'iteration:91337',
        'iteration:33',
        'AESAlgoGCM',
    ),
    'ios/Xaman/Libs/Security/Vault/Storage/Keychain.m': (
        'kSecAttrAccessibleWhenUnlockedThisDeviceOnly',
    ),
    'ios/XamanTests/VaultMangerTest.m': (
        'testVaultRecovery',
        'testVaultReKey',
    ),
    'src/store/repositories/core.ts': (
        'const sha512Passcode = await SHA512(passcode);',
        'return await HMAC256(sha512Passcode, deviceUniqueId);',
    ),
}

REKEY_RECOVERY_SMTLIB = r'''(set-logic QF_UF)
; PORTAL-CXTP-162.  Abstract public-source rekey ordering only.
; A recovery snapshot is written under the old key before the primary vault is
; deleted.  A replacement write may fail after that deletion.
(declare-const recovery_snapshot_written Bool)
(declare-const replacement_write_succeeds Bool)
(declare-const primary_present_after Bool)
(declare-const recovery_present_after Bool)
(declare-const recovery_requires_old_key Bool)

(assert (= primary_present_after replacement_write_succeeds))
(assert (= recovery_present_after
  (and recovery_snapshot_written (not replacement_write_succeeds))))
(assert (= recovery_requires_old_key recovery_snapshot_written))

; Property 1: a successful replacement leaves the primary vault and removes
; the recovery vault in this abstraction.
(push)
(assert (not (=> replacement_write_succeeds
  (and primary_present_after (not recovery_present_after)))))
(check-sat)
(pop)

; Property 2: after a replacement-write failure, a written recovery snapshot
; remains and the primary vault is absent.  Recovery therefore needs old-key
; material; the model makes no claim that an application retains it.
(push)
(assert (not (=> (and recovery_snapshot_written (not replacement_write_succeeds))
  (and (not primary_present_after) recovery_present_after recovery_requires_old_key))))
(check-sat)
(pop)

; Expected partial-state witness.  It is a test obligation, not a vulnerability
; finding: a failed replacement can leave only the old-key recovery vault.
(push)
(assert recovery_snapshot_written)
(assert (not replacement_write_succeeds))
(assert (not primary_present_after))
(assert recovery_present_after)
(assert recovery_requires_old_key)
(check-sat)
(pop)
'''

CHECKS = (
    {
        'id': 'successful_rekey_cleans_recovery_state',
        'expected_result': 'unsat',
        'meaning': 'The abstraction preserves a primary vault and removes the recovery vault after a successful replacement write.',
    },
    {
        'id': 'replacement_failure_preserves_old_key_recovery_witness',
        'expected_result': 'unsat',
        'meaning': 'The abstraction preserves an old-key recovery vault after a replacement-write failure.',
    },
    {
        'id': 'replacement_failure_has_expected_partial_state_witness',
        'expected_result': 'sat',
        'meaning': 'The abstraction exposes the post-delete, old-key-recovery-only state that requires runtime fault-injection testing.',
    },
)


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(payload, dict):
        raise ValueError(f'expected JSON object: {path}')
    return payload


def _line_for(source: str, marker: str) -> int:
    for line_number, line in enumerate(source.splitlines(), start=1):
        if marker in line:
            return line_number
    raise ValueError(f'missing required source marker: {marker}')


def _source_inputs(source_root: Path, manifest: Mapping[str, Any]) -> tuple[list[dict[str, Any]], dict[str, str]]:
    manifest_files = {
        str(entry['path']): entry
        for entry in manifest.get('files', [])
        if isinstance(entry, Mapping) and isinstance(entry.get('path'), str)
    }
    inputs: list[dict[str, Any]] = []
    sources: dict[str, str] = {}
    for rel_path, markers in REQUIRED_SOURCE_MARKERS.items():
        path = source_root / rel_path
        if not path.is_file():
            raise ValueError(f'required public-source input is missing: {rel_path}')
        manifest_entry = manifest_files.get(rel_path)
        if manifest_entry is None:
            raise ValueError(f'public-source manifest does not bind required input: {rel_path}')
        raw = path.read_bytes()
        actual_sha256 = _sha256_bytes(raw)
        expected_sha256 = str(manifest_entry.get('sha256') or '')
        if actual_sha256 != expected_sha256:
            raise ValueError(
                f'public-source digest mismatch for {rel_path}: expected {expected_sha256}, got {actual_sha256}'
            )
        source = raw.decode('utf-8')
        marker_lines = {marker: _line_for(source, marker) for marker in markers}
        inputs.append(
            {
                'path': rel_path,
                'sha256': actual_sha256,
                'size_bytes': len(raw),
                'marker_lines': marker_lines,
            }
        )
        sources[rel_path] = source
    return inputs, sources


def _evidence(inputs_by_path: Mapping[str, Mapping[str, Any]], path: str, marker: str) -> dict[str, Any]:
    line = int(inputs_by_path[path]['marker_lines'][marker])
    return {
        'kind': 'source_code',
        'path': path,
        'line_start': line,
        'line_end': line,
        'sha256': inputs_by_path[path]['sha256'],
        'review_status': 'reviewed',
    }


def _run_solver(command: list[str], *, timeout_seconds: int) -> dict[str, Any]:
    try:
        completed = subprocess.run(
            command,
            input=REKEY_RECOVERY_SMTLIB,
            text=True,
            capture_output=True,
            check=False,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired:
        return {'status': 'timeout', 'results': [], 'stderr': 'solver timed out'}
    results = [line.strip() for line in completed.stdout.splitlines() if line.strip() in {'sat', 'unsat', 'unknown'}]
    status = 'pass' if completed.returncode == 0 and results == [item['expected_result'] for item in CHECKS] else 'failed'
    return {
        'status': status,
        'command': command,
        'returncode': completed.returncode,
        'results': results,
        'stdout': completed.stdout,
        'stderr': completed.stderr,
    }


def run_rekey_solver_lane(*, timeout_seconds: int = 15) -> dict[str, Any]:
    """Execute the independent Z3 and CVC5 checks for the abstract model."""

    definitions = {
        'z3': ['z3', '-in'],
        'cvc5': ['cvc5', '--lang=smt2', '--incremental'],
    }
    solvers: dict[str, Any] = {}
    for name, command in definitions.items():
        executable = shutil.which(command[0])
        if executable is None:
            solvers[name] = {'status': 'unavailable', 'command': command, 'results': []}
            continue
        result = _run_solver([executable, *command[1:]], timeout_seconds=timeout_seconds)
        version = subprocess.run(
            [executable, '--version'], text=True, capture_output=True, check=False, timeout=timeout_seconds
        )
        result['version'] = (version.stdout or version.stderr).strip().splitlines()[0] if (version.stdout or version.stderr).strip() else None
        solvers[name] = result
    return solvers


def build_native_vault_assessment(
    *,
    source_root: Path,
    manifest: Mapping[str, Any],
    solver_lane: Mapping[str, Any],
) -> dict[str, Any]:
    """Create a fail-closed assessment tied to the pinned public-source manifest."""

    inputs, _sources = _source_inputs(source_root, manifest)
    inputs_by_path = {entry['path']: entry for entry in inputs}
    all_solvers_passed = all(solver_lane.get(name, {}).get('status') == 'pass' for name in ('z3', 'cvc5'))
    facts = [
        {
            'id': 'xaman-native-vault:fact:android-v2-vault-cipher-uses-pbkdf2-and-aes-gcm',
            'status': 'SOURCE_SUPPORTED',
            'summary': 'The public Android V2 vault cipher derives keys with PBKDF2, records versioned salts, and invokes AES-GCM with a device identifier as associated data.',
            'evidence': [
                _evidence(inputs_by_path, 'android/app/src/main/java/libs/security/vault/cipher/CipherV2AesGcm.java', 'Crypto.PBKDF2(key.toCharArray(), passcodeSalt, 91337)'),
                _evidence(inputs_by_path, 'android/app/src/main/java/libs/security/vault/cipher/CipherV2AesGcm.java', 'Crypto.PBKDF2(preKey, encrKeySalt, 33)'),
                _evidence(inputs_by_path, 'android/app/src/main/java/libs/security/vault/cipher/CipherV2AesGcm.java', 'Crypto.AESAlgo.GCM'),
            ],
        },
        {
            'id': 'xaman-native-vault:fact:android-keychain-selects-keystore-aes-gcm',
            'status': 'SOURCE_SUPPORTED',
            'summary': 'The public Android keychain selects an AES-GCM Android KeyStore cipher storage with randomized encryption and a 256-bit key setting.',
            'evidence': [
                _evidence(inputs_by_path, 'android/app/src/main/java/libs/security/vault/storage/cipherStorage/CipherStorageKeystoreAesGcm.java', '.setBlockModes(BLOCK_MODE_GCM)'),
                _evidence(inputs_by_path, 'android/app/src/main/java/libs/security/vault/storage/cipherStorage/CipherStorageKeystoreAesGcm.java', '.setRandomizedEncryptionRequired(true)'),
                _evidence(inputs_by_path, 'android/app/src/main/java/libs/security/vault/storage/cipherStorage/CipherStorageKeystoreAesGcm.java', '.setKeySize(ENCRYPTION_KEY_SIZE)'),
            ],
        },
        {
            'id': 'xaman-native-vault:fact:ios-v2-vault-cipher-and-device-only-keychain',
            'status': 'SOURCE_SUPPORTED',
            'summary': 'The public iOS implementation uses V2 AES-GCM/PBKDF2 source paths and stores keychain records with WhenUnlockedThisDeviceOnly accessibility.',
            'evidence': [
                _evidence(inputs_by_path, 'ios/Xaman/Libs/Security/Vault/Cipher/V2+AesGcm.m', 'iteration:91337'),
                _evidence(inputs_by_path, 'ios/Xaman/Libs/Security/Vault/Cipher/V2+AesGcm.m', 'iteration:33'),
                _evidence(inputs_by_path, 'ios/Xaman/Libs/Security/Vault/Cipher/V2+AesGcm.m', 'AESAlgoGCM'),
                _evidence(inputs_by_path, 'ios/Xaman/Libs/Security/Vault/Storage/Keychain.m', 'kSecAttrAccessibleWhenUnlockedThisDeviceOnly'),
            ],
        },
        {
            'id': 'xaman-native-vault:fact:rekey-uses-an-old-key-recovery-vault-before-primary-delete',
            'status': 'SOURCE_SUPPORTED',
            'summary': 'Both public platform rekey implementations write an old-key recovery vault, delete the primary vault, write the new-key primary vault, then remove recovery on the success path.',
            'evidence': [
                _evidence(inputs_by_path, 'android/app/src/main/java/libs/security/vault/VaultManagerModule.java', 'createVault(recoveryVaultName, clearText, oldKey);'),
                _evidence(inputs_by_path, 'android/app/src/main/java/libs/security/vault/VaultManagerModule.java', 'createVault(vaultName, clearText, newKey);'),
                _evidence(inputs_by_path, 'ios/Xaman/Libs/Security/Vault/VaultManager.m', '[VaultManagerModule createVault:recoveryVaultName data:cleartext key:oldKey];'),
                _evidence(inputs_by_path, 'ios/Xaman/Libs/Security/Vault/VaultManager.m', '[VaultManagerModule createVault:vaultName data:cleartext key:newKey];'),
            ],
        },
        {
            'id': 'xaman-native-vault:fact:public-tests-cover-normal-recovery-and-rekey',
            'status': 'SOURCE_SUPPORTED',
            'summary': 'Public Android instrumentation and iOS XCTest sources contain normal recovery and rekey tests; this is not evidence of post-delete write-failure injection.',
            'evidence': [
                _evidence(inputs_by_path, 'android/app/src/androidTest/java/libs/security/vault/VaultMangerTest.java', 'VaultRecoveryTest'),
                _evidence(inputs_by_path, 'android/app/src/androidTest/java/libs/security/vault/VaultMangerTest.java', 'VaultReKeyTest'),
                _evidence(inputs_by_path, 'ios/XamanTests/VaultMangerTest.m', 'testVaultRecovery'),
                _evidence(inputs_by_path, 'ios/XamanTests/VaultMangerTest.m', 'testVaultReKey'),
            ],
        },
        {
            'id': 'xaman-native-vault:fact:typescript-passcode-hash-construction-is-source-visible',
            'status': 'SOURCE_SUPPORTED',
            'summary': 'The public TypeScript passcode helper hashes the passcode with SHA-512 and passes that value with a device identifier into HMAC256. This assessment does not quantify resistance to offline guessing or establish implementation correctness of either primitive.',
            'evidence': [
                _evidence(inputs_by_path, 'src/store/repositories/core.ts', 'const sha512Passcode = await SHA512(passcode);'),
                _evidence(inputs_by_path, 'src/store/repositories/core.ts', 'return await HMAC256(sha512Passcode, deviceUniqueId);'),
            ],
        },
    ]
    report: dict[str, Any] = {
        'schema_version': SCHEMA_VERSION,
        'task_id': TASK_ID,
        'generated_at_utc': GENERATED_AT_UTC,
        'scope': {
            'public_source_only': True,
            'source_commit': manifest.get('source', {}).get('commit_sha'),
            'vendor_release_equivalent': False,
            'production_security_result': False,
        },
        'source_manifest': {
            'path': SOURCE_MANIFEST_PATH,
            'aggregate_sha256': manifest.get('reproducibility', {}).get('aggregate_sha256'),
        },
        'source_inputs': inputs,
        'source_supported_facts': facts,
        'formal_rekey_model': {
            'path': SMTLIB_PATH,
            'sha256': 'sha256:' + _sha256_bytes(REKEY_RECOVERY_SMTLIB.encode('utf-8')),
            'abstraction': [
                'A recovery snapshot is written under the old key before primary deletion.',
                'The primary replacement write may fail after deletion.',
                'A successful replacement deletes recovery; a failed replacement leaves old-key recovery state.',
            ],
            'checks': list(CHECKS),
            'solvers': dict(solver_lane),
            'status': 'checked' if all_solvers_passed else 'blocked_solver_lane',
        },
        'source_supported_rekey_condition': {
            'status': 'REQUIRES_RUNTIME_FAULT_INJECTION',
            'summary': 'The public rekey sequence has an intentional intermediate state after primary deletion and before replacement creation. If replacement creation fails, recovery depends on the old-key recovery vault; runtime fault injection must verify the app preserves and exposes an appropriate recovery path.',
            'is_confirmed_vulnerability': False,
            'required_evidence_to_resolve': [
                'Android instrumentation test that injects failure after primary purge and before replacement create, then verifies old-key recovery without retaining secrets.',
                'iOS XCTest or equivalent fault-injection test for the same path.',
                'Reviewed emulator/device evidence binding the tested native artifacts to the public-source verifier build.',
            ],
        },
        'not_proved': [
            'native primitive implementation correctness',
            'Android hardware-backed KeyStore availability or device policy',
            'iOS Secure Enclave, backup, migration, and operating-system behavior',
            'passcode entropy or offline-guessing resistance',
            'Tangem SDK or firmware security',
            'vendor release or production wallet security',
        ],
        'production_release_blocked': True,
        'overall_status': 'checked_source_bounded_with_runtime_boundaries' if all_solvers_passed else 'blocked_source_bounded_solver_lane',
        'security_decision': (
            'SOURCE_BOUNDED_NATIVE_VAULT_REKEY_MODEL_CHECKED'
            if all_solvers_passed
            else 'BLOCK_NATIVE_VAULT_REKEY_MODEL_SOLVER_LANE'
        ),
    }
    report['artifact_cid'] = calculate_artifact_cid(report)
    return report
