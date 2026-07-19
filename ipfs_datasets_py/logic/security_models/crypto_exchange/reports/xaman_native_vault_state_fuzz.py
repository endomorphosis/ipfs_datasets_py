"""Source-bound exhaustive state fuzzing for Xaman native-vault rekey flows.

This is a model-level campaign.  It enumerates bounded fault locations in the
public rekey order and independently checks the single-vault implications with
Z3 and CVC5.  It is not a native runtime result or a product vulnerability
finding.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import subprocess
from typing import Any, Mapping

from ..ir.cid import calculate_artifact_cid


TASK_ID = 'PORTAL-CXTP-167'
SCHEMA_VERSION = 'xaman-native-vault-rekey-state-fuzz/v1'
SOURCE_MANIFEST_PATH = 'security_ir_artifacts/corpora/xaman-app/source-manifest.json'
ASSESSMENT_PATH = 'security_ir_artifacts/corpora/xaman-app/native-vault-public-source-assessment.json'
REPORT_PATH = 'security_ir_artifacts/corpora/xaman-app/native-vault/rekey-state-fuzz-report.json'
SMTLIB_PATH = 'security_ir_artifacts/corpora/xaman-app/native-vault/rekey-state-fuzz.smt2'
PINNED_XAMAN_COMMIT = '942f43876265a7af44f233288ad2b1d00841d5fa'
GENERATED_AT_UTC = '2026-07-19T00:00:00Z'

PHASES = ('recovery_snapshot_write', 'primary_purge', 'replacement_write', 'recovery_cleanup')
SOURCE_MARKERS: dict[str, tuple[str, ...]] = {
    'android/app/src/main/java/libs/security/vault/VaultManagerModule.java': (
        'createVault(recoveryVaultName, clearText, oldKey);',
        'purgeVault(vaultName);',
        'createVault(vaultName, clearText, newKey);',
        'purgeVault(recoveryVaultName);',
        'promise.resolve(result);',
        'rejectWithError(promise, e);',
        '// try to create the new vault under a temp recovery name with the old key for all vaults',
        '// remove old vault and create one',
        '// finally remove the created recovery vaults',
    ),
    'ios/Xaman/Libs/Security/Vault/VaultManager.m': (
        '[VaultManagerModule createVault:recoveryVaultName data:cleartext key:oldKey];',
        '[VaultManagerModule purgeVault:vaultName];',
        '[VaultManagerModule createVault:vaultName data:cleartext key:newKey];',
        '[VaultManagerModule purgeVault:recoveryVaultName];',
        'resolve(@(result));',
        'rejectWithError(reject, error);',
        'try to create the new vault under a temp recovery name with the old key for all vaults',
        'remove old vault and create one',
        'finally remove the created recovery vaults',
    ),
    'src/common/libs/vault.ts': (
        'VaultManagerModule.reKeyVault(name, oldKey, newKey)',
        'VaultManagerModule.reKeyBatchVaults(names, oldKey, newKey)',
        'reject(error);',
    ),
    'src/screens/Settings/Security/ChangePasscode/ChangePasscodeView.tsx': (
        'await Vault.reKeyBatch(passcodeVaultNames, passcode, newEncPasscode);',
        'await CoreRepository.setPasscode(passcode);',
    ),
}

REKEY_STATE_SMTLIB = r'''(set-logic QF_UF)
; PORTAL-CXTP-167. Public-source single-vault rekey order under injected exceptions.
(declare-const recovery_write_ok Bool)
(declare-const primary_purge_ok Bool)
(declare-const replacement_write_ok Bool)
(declare-const recovery_cleanup_ok Bool)
(declare-const primary_old_after Bool)
(declare-const primary_new_after Bool)
(declare-const recovery_old_after Bool)
(declare-const operation_success Bool)

; A phase failure stops the source method through its exception boundary.
(assert (= primary_old_after (or (not recovery_write_ok) (and recovery_write_ok (not primary_purge_ok)))))
(assert (= primary_new_after (and recovery_write_ok primary_purge_ok replacement_write_ok)))
(assert (= recovery_old_after
  (and recovery_write_ok
       (or (not primary_purge_ok)
           (not replacement_write_ok)
           (not recovery_cleanup_ok)))))
(assert (= operation_success
  (and recovery_write_ok primary_purge_ok replacement_write_ok recovery_cleanup_ok)))

; A reported success leaves exactly the new primary and no old-key recovery.
(push)
(assert (not (=> operation_success
  (and primary_new_after (not primary_old_after) (not recovery_old_after)))))
(check-sat)
(pop)

; Replacement failure after a successful snapshot and purge leaves old-key recovery.
(push)
(assert (not (=> (and recovery_write_ok primary_purge_ok (not replacement_write_ok))
  (and (not primary_old_after) (not primary_new_after) recovery_old_after (not operation_success)))))
(check-sat)
(pop)

; Cleanup failure after replacement leaves both new-primary and old-key recovery,
; and cannot be reported as successful.
(push)
(assert (not (=> (and recovery_write_ok primary_purge_ok replacement_write_ok (not recovery_cleanup_ok))
  (and primary_new_after recovery_old_after (not operation_success)))))
(check-sat)
(pop)

; Expected cleanup-failure witness. This is a runtime test obligation, not a defect claim.
(push)
(assert recovery_write_ok)
(assert primary_purge_ok)
(assert replacement_write_ok)
(assert (not recovery_cleanup_ok))
(assert primary_new_after)
(assert recovery_old_after)
(assert (not operation_success))
(check-sat)
(pop)
'''

CHECKS = (
    ('success_removes_old_key_recovery', 'unsat'),
    ('replacement_failure_retains_old_key_recovery', 'unsat'),
    ('cleanup_failure_is_reported_with_old_key_recovery', 'unsat'),
    ('cleanup_failure_has_expected_dual_access_witness', 'sat'),
)


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _line_for(source: str, marker: str) -> int:
    for number, line in enumerate(source.splitlines(), start=1):
        if marker in line:
            return number
    raise ValueError(f'missing source marker: {marker}')


def _bound_sources(source_root: Path, manifest: Mapping[str, Any]) -> list[dict[str, Any]]:
    manifest_entries = {
        str(entry.get('path')): entry
        for entry in manifest.get('files', [])
        if isinstance(entry, Mapping) and isinstance(entry.get('path'), str)
    }
    result: list[dict[str, Any]] = []
    for rel_path, markers in SOURCE_MARKERS.items():
        path = source_root / rel_path
        entry = manifest_entries.get(rel_path)
        if not path.is_file() or entry is None:
            raise ValueError(f'pinned source is missing or unbound: {rel_path}')
        raw = path.read_bytes()
        digest = _sha256_bytes(raw)
        if digest != entry.get('sha256'):
            raise ValueError(f'pinned source digest mismatch: {rel_path}')
        source = raw.decode('utf-8')
        result.append({
            'path': rel_path,
            'sha256': digest,
            'marker_lines': {marker: _line_for(source, marker) for marker in markers},
        })
    return result


def _run_solver(command: list[str], timeout_seconds: int) -> dict[str, Any]:
    try:
        completed = subprocess.run(
            command,
            input=REKEY_STATE_SMTLIB,
            text=True,
            capture_output=True,
            check=False,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired:
        return {'status': 'timeout', 'results': []}
    results = [line.strip() for line in completed.stdout.splitlines() if line.strip() in {'sat', 'unsat', 'unknown'}]
    expected = [expected for _, expected in CHECKS]
    return {
        'status': 'pass' if completed.returncode == 0 and results == expected else 'failed',
        'command': command,
        'returncode': completed.returncode,
        'results': results,
        'stdout': completed.stdout,
        'stderr': completed.stderr,
    }


def run_state_fuzz_solver_lane(*, timeout_seconds: int = 15) -> dict[str, Any]:
    """Run the source-derived state model through independent SMT solvers."""

    definitions = {'z3': ['z3', '-in'], 'cvc5': ['cvc5', '--lang=smt2', '--incremental']}
    results: dict[str, Any] = {}
    for name, command in definitions.items():
        executable = shutil.which(command[0])
        if executable is None:
            results[name] = {'status': 'unavailable', 'command': command, 'results': []}
            continue
        report = _run_solver([executable, *command[1:]], timeout_seconds)
        version = subprocess.run([executable, '--version'], text=True, capture_output=True, check=False, timeout=timeout_seconds)
        text = (version.stdout or version.stderr).strip()
        report['version'] = text.splitlines()[0] if text else ''
        results[name] = report
    return results


def _simulate(vault_count: int, fault_phase: str | None, fault_index: int | None) -> dict[str, Any]:
    if vault_count not in {1, 2} or (fault_phase is not None and fault_phase not in PHASES):
        raise ValueError('unsupported bounded fuzz input')
    if fault_phase is None and fault_index is not None:
        raise ValueError('a fault index requires a fault phase')
    if fault_phase is not None and (fault_index is None or not 0 <= fault_index < vault_count):
        raise ValueError('fault index is outside the bounded batch')
    primary = ['old_key'] * vault_count
    recovery = [False] * vault_count
    raised_at: str | None = None
    # The source snapshots every vault, then purges and replaces each vault in
    # the same loop, and only then removes recoveries.  In particular, a first
    # replacement-write failure does not purge a later vault's primary.
    events = [
        *[('recovery_snapshot_write', index) for index in range(vault_count)],
        *[
            event
            for index in range(vault_count)
            for event in (('primary_purge', index), ('replacement_write', index))
        ],
        *[('recovery_cleanup', index) for index in range(vault_count)],
    ]
    for phase, index in events:
        if phase == fault_phase and index == fault_index:
            raised_at = phase
            break
        if phase == 'recovery_snapshot_write':
            recovery[index] = True
        elif phase == 'primary_purge':
            primary[index] = 'absent'
        elif phase == 'replacement_write':
            primary[index] = 'new_key'
        else:
            recovery[index] = False
    vaults = [
        {
            'primary_state': primary[index],
            'old_key_recovery_present': recovery[index],
            'data_recoverable': primary[index] != 'absent' or recovery[index],
            'new_key_primary_accessible': primary[index] == 'new_key',
            'old_key_recovery_accessible': recovery[index],
        }
        for index in range(vault_count)
    ]
    return {
        'fault_phase': fault_phase,
        'fault_index': fault_index,
        'native_operation_reports_success': raised_at is None,
        'native_operation_reports_failure': raised_at is not None,
        'raised_at_phase': raised_at,
        'vaults': vaults,
        'all_data_recoverable': all(item['data_recoverable'] for item in vaults),
    }


def run_bounded_state_fuzz_campaign() -> list[dict[str, Any]]:
    """Enumerate every phase/index exception in one- and two-vault rekeys."""

    cases: list[dict[str, Any]] = []
    for vault_count, flow in ((1, 'single_rekey'), (2, 'batch_rekey_two_vaults')):
        candidates = [(None, None)] + [
            (phase, index) for phase in PHASES for index in range(vault_count)
        ]
        for ordinal, (phase, index) in enumerate(candidates, start=1):
            result = _simulate(vault_count, phase, index)
            primary_states = [item['primary_state'] for item in result['vaults']]
            recovery_count = sum(bool(item['old_key_recovery_present']) for item in result['vaults'])
            if phase is None:
                classification = 'SUCCESS_CLEANUP_COMPLETE'
            elif phase == 'replacement_write':
                classification = 'RECOVERY_ONLY_RUNTIME_OBLIGATION'
            elif phase == 'recovery_cleanup':
                classification = 'DUAL_OLD_NEW_ACCESS_RUNTIME_OBLIGATION'
            else:
                classification = 'PRE_DESTRUCTIVE_FAILURE_PRESERVES_PRIMARY'
            cases.append({
                'case_id': f'{flow}-{ordinal:02d}',
                'flow': flow,
                'vault_count': vault_count,
                'fault_phase': phase or 'none',
                'fault_index': index,
                'classification': classification,
                'native_operation_reports_success': result['native_operation_reports_success'],
                'all_data_recoverable': result['all_data_recoverable'],
                'primary_state_counts': {
                    'old_key': primary_states.count('old_key'),
                    'new_key': primary_states.count('new_key'),
                    'absent': primary_states.count('absent'),
                },
                'old_key_recovery_vault_count': recovery_count,
                'requires_runtime_fault_injection': phase in {'replacement_write', 'recovery_cleanup'},
            })
    return cases


def build_native_vault_state_fuzz_report(
    *,
    source_root: Path,
    manifest: Mapping[str, Any],
    assessment: Mapping[str, Any],
    solver_lane: Mapping[str, Any],
) -> dict[str, Any]:
    """Build a source-bound, fail-closed state-fuzz report."""

    if manifest.get('source', {}).get('commit_sha') != PINNED_XAMAN_COMMIT:
        raise ValueError('source manifest does not use the pinned Xaman commit')
    if assessment.get('task_id') != 'PORTAL-CXTP-162' or not assessment.get('artifact_cid'):
        raise ValueError('native-vault source assessment is missing')
    if assessment.get('scope', {}).get('source_commit') != PINNED_XAMAN_COMMIT:
        raise ValueError('native-vault source assessment is not commit bound')
    sources = _bound_sources(source_root, manifest)
    cases = run_bounded_state_fuzz_campaign()
    all_solvers_passed = all(solver_lane.get(name, {}).get('status') == 'pass' for name in ('z3', 'cvc5'))
    runtime_cases = [case for case in cases if case['requires_runtime_fault_injection']]
    report: dict[str, Any] = {
        'schema_version': SCHEMA_VERSION,
        'task_id': TASK_ID,
        'generated_at_utc': GENERATED_AT_UTC,
        'scope': {
            'public_source_only': True,
            'source_commit': PINNED_XAMAN_COMMIT,
            'vendor_release_equivalent': False,
            'production_security_result': False,
        },
        'inputs': {
            'native_vault_assessment_cid': assessment['artifact_cid'],
            'source_manifest_path': SOURCE_MANIFEST_PATH,
            'source_manifest_aggregate_sha256': manifest.get('reproducibility', {}).get('aggregate_sha256'),
            'source_inputs': sources,
        },
        'formal_state_model': {
            'path': SMTLIB_PATH,
            'sha256': 'sha256:' + _sha256_bytes(REKEY_STATE_SMTLIB.encode('utf-8')),
            'checks': [
                {'id': check_id, 'expected_result': expected}
                for check_id, expected in CHECKS
            ],
            'solvers': dict(solver_lane),
            'status': 'checked' if all_solvers_passed else 'blocked_solver_lane',
        },
        'bounded_fuzz_campaign': {
            'method': 'exhaustive-phase-index-state-fuzz/v1',
            'input_space': {
                'flows': ['single_rekey', 'batch_rekey_two_vaults'],
                'fault_phases': ['none', *PHASES],
                'batch_size_bound': 2,
            },
            'case_count': len(cases),
            'all_data_recoverable_in_model': all(case['all_data_recoverable'] for case in cases),
            'runtime_obligation_case_count': len(runtime_cases),
            'cases': cases,
        },
        'source_supported_conditions': [
            {
                'id': 'xaman-native-vault:condition:replacement-write-failure-leaves-old-key-recovery',
                'classification': 'SOURCE_BOUNDED_RUNTIME_TEST_OBLIGATION',
                'summary': 'A failure after primary purge and before replacement write has an old-key recovery-only state in the bounded model.',
                'confirmed_vulnerability': False,
            },
            {
                'id': 'xaman-native-vault:condition:cleanup-failure-retains-old-key-recovery',
                'classification': 'SOURCE_BOUNDED_RUNTIME_TEST_OBLIGATION',
                'summary': 'A recovery-cleanup exception after replacement yields a new-key primary together with old-key recovery in the bounded model; the native bridge and TypeScript wrapper source show error propagation, which must be checked under runtime injection.',
                'confirmed_vulnerability': False,
            },
            {
                'id': 'xaman-native-vault:condition:batch-failure-can-be-mixed-state',
                'classification': 'SOURCE_BOUNDED_RUNTIME_TEST_OBLIGATION',
                'summary': 'For a bounded two-vault batch, first- and later-vault failures can leave mixed old primary, absent primary with recovery, or new primary with recovery states. The public passcode flow visibly attempts rollback after rejected batch rekey, but runtime behavior remains unproved.',
                'confirmed_vulnerability': False,
            },
        ],
        'not_proved': [
            'native storage durability, exception behavior, and recovery behavior on Android or iOS',
            'whether old-key recovery is accessible after an injected cleanup failure on a released binary',
            'caller remediation and user-visible behavior after partial batch rekey failure',
            'vendor release equivalence or production wallet security',
        ],
        'production_release_blocked': True,
        'overall_status': 'checked_source_bounded_with_runtime_obligations' if all_solvers_passed else 'blocked_source_bounded_solver_lane',
        'security_decision': (
            'SOURCE_BOUNDED_NATIVE_VAULT_STATE_FUZZED_REQUIRES_RUNTIME_INJECTION'
            if all_solvers_passed else 'BLOCK_NATIVE_VAULT_STATE_FUZZ_SOLVER_LANE'
        ),
    }
    report['artifact_cid'] = calculate_artifact_cid(report)
    return report
