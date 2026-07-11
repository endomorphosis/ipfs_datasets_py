"""Reconciled TLA+/Apalache workflow artifacts for Xaman signing."""

from __future__ import annotations

import hashlib
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Mapping, Sequence

from ipfs_datasets_py.logic.security_models.crypto_exchange.ir.cid import (
    calculate_artifact_cid,
)


SCHEMA_VERSION = 'xaman-tla-apalache-report/v1'
LANE_SCHEMA_VERSION = 'crypto-exchange-apalache-solver-lane-report/v1'
TASK_ID = 'PORTAL-CXTP-140'
DEPENDENCY_TASK_IDS = ('PORTAL-CXTP-071', 'PORTAL-CXTP-091')
GENERATED_AT_UTC = '2026-07-11T00:00:00Z'
MODULE_NAME = 'XamanSigning'
SPEC_OPERATOR = 'Spec'
INIT_OPERATOR = 'Init'
NEXT_OPERATOR = 'Next'
REQUIRED_APALACHE_VERSION = '0.58.3'
SCOPE_STATEMENT = 'bounded_model_only'
TLA_ARTIFACT_PATH = 'security_ir_artifacts/corpora/xaman-app/tla/XamanSigning.tla'
APALACHE_REPORT_PATH = 'security_ir_artifacts/corpora/xaman-app/tla/apalache-report.json'
APALACHE_SOLVER_LANE_REPORT_PATH = (
    'security_ir_artifacts/environment/apalache-solver-lane-report.json'
)

CHECKED_INVARIANTS = (
    'NoSignWithoutDigest',
    'NoSignWithoutAuthentication',
    'NoSignWithoutVault',
    'NoSignWithoutNetworkBinding',
    'NoBroadcastWithoutSignature',
    'NoBroadcastAfterReject',
    'SigningGateInvariant',
)

COVERED_CLAIM_IDS = (
    'xaman-claim:software-custody-requires-vault-authentication',
    'xaman-claim:signing-is-gated-by-auth-and-vault-overlay',
    'xaman-claim:payload-integrity-is-digest-checked-and-revalidated',
    'xaman-claim:network-binding-prevents-wrong-network-signing',
)

REQUIRED_OPERATORS = (
    'Init',
    'Review',
    'CheckDigest',
    'Authenticate',
    'OpenVault',
    'BindNetwork',
    'Sign',
    'Broadcast',
    'Reject',
    'Next',
    'Spec',
    *CHECKED_INVARIANTS,
)

XAMAN_SIGNING_TLA = r'''---- MODULE XamanSigning ----
EXTENDS Naturals, Sequences, TLC

\* PORTAL-CXTP-140 reconciled source. Scope statement: bounded_model_only.
\* This model is intentionally finite: it captures the proof obligations that
\* a signature or broadcast cannot occur unless review, digest, auth, vault,
\* and network-binding gates have all succeeded.

VARIABLES
  \* @type: Str;
  phase,
  \* @type: Bool;
  digestChecked,
  \* @type: Bool;
  authPassed,
  \* @type: Bool;
  vaultOpened,
  \* @type: Bool;
  networkBound,
  \* @type: Bool;
  signed,
  \* @type: Bool;
  broadcasted,
  \* @type: Bool;
  rejected

vars == << phase, digestChecked, authPassed, vaultOpened, networkBound, signed, broadcasted, rejected >>

Init ==
  /\ phase = "received"
  /\ digestChecked = FALSE
  /\ authPassed = FALSE
  /\ vaultOpened = FALSE
  /\ networkBound = FALSE
  /\ signed = FALSE
  /\ broadcasted = FALSE
  /\ rejected = FALSE

Review ==
  /\ phase = "received"
  /\ phase' = "reviewed"
  /\ UNCHANGED << digestChecked, authPassed, vaultOpened, networkBound, signed, broadcasted, rejected >>

CheckDigest ==
  /\ phase = "reviewed"
  /\ digestChecked' = TRUE
  /\ UNCHANGED << phase, authPassed, vaultOpened, networkBound, signed, broadcasted, rejected >>

Authenticate ==
  /\ phase = "reviewed"
  /\ authPassed' = TRUE
  /\ UNCHANGED << phase, digestChecked, vaultOpened, networkBound, signed, broadcasted, rejected >>

OpenVault ==
  /\ phase = "reviewed"
  /\ authPassed
  /\ vaultOpened' = TRUE
  /\ UNCHANGED << phase, digestChecked, authPassed, networkBound, signed, broadcasted, rejected >>

BindNetwork ==
  /\ phase = "reviewed"
  /\ networkBound' = TRUE
  /\ UNCHANGED << phase, digestChecked, authPassed, vaultOpened, signed, broadcasted, rejected >>

Sign ==
  /\ phase = "reviewed"
  /\ digestChecked
  /\ authPassed
  /\ vaultOpened
  /\ networkBound
  /\ signed' = TRUE
  /\ phase' = "signed"
  /\ UNCHANGED << digestChecked, authPassed, vaultOpened, networkBound, broadcasted, rejected >>

Broadcast ==
  /\ phase = "signed"
  /\ signed
  /\ broadcasted' = TRUE
  /\ phase' = "broadcasted"
  /\ UNCHANGED << digestChecked, authPassed, vaultOpened, networkBound, signed, rejected >>

Reject ==
  /\ phase \in { "received", "reviewed" }
  /\ rejected' = TRUE
  /\ phase' = "rejected"
  /\ UNCHANGED << digestChecked, authPassed, vaultOpened, networkBound, signed, broadcasted >>

Next ==
  \/ Review
  \/ CheckDigest
  \/ Authenticate
  \/ OpenVault
  \/ BindNetwork
  \/ Sign
  \/ Broadcast
  \/ Reject

Spec == Init /\ [][Next]_vars

NoSignWithoutDigest == signed => digestChecked
NoSignWithoutAuthentication == signed => authPassed
NoSignWithoutVault == signed => vaultOpened
NoSignWithoutNetworkBinding == signed => networkBound
NoBroadcastWithoutSignature == broadcasted => signed
NoBroadcastAfterReject == rejected => ~broadcasted

SigningGateInvariant ==
  /\ NoSignWithoutDigest
  /\ NoSignWithoutAuthentication
  /\ NoSignWithoutVault
  /\ NoSignWithoutNetworkBinding
  /\ NoBroadcastWithoutSignature
  /\ NoBroadcastAfterReject

====
'''


def generated_tla_source() -> str:
    """Return the exact source bytes that must be checked in and model-checked."""

    return XAMAN_SIGNING_TLA.rstrip('\n') + '\n'


def sha256_label(payload: str | bytes) -> str:
    encoded = payload.encode('utf-8') if isinstance(payload, str) else payload
    return 'sha256:' + hashlib.sha256(encoded).hexdigest()


def _without_cid(payload: Mapping[str, Any], cid_key: str) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if key != cid_key}


def _semantic_version(value: str | None) -> str | None:
    if not value:
        return None
    match = re.search(r'\b(\d+\.\d+\.\d+)\b', value)
    return match.group(1) if match else None


def discover_apalache_executable() -> str | None:
    """Resolve Apalache only when the TLA execution path requests it."""

    from ipfs_datasets_py.logic.external_provers.lazy_installer import (
        ensure_prover_executable,
    )

    return ensure_prover_executable(
        'apalache',
        reason='Xaman TLA model-check execution',
    )


def read_apalache_version(executable: str | None) -> str | None:
    if executable is None:
        return None
    for args in (['version'], ['--version'], []):
        try:
            completed = subprocess.run(
                [executable, *args],
                check=False,
                capture_output=True,
                text=True,
                timeout=15,
            )
        except (OSError, subprocess.TimeoutExpired):
            continue
        output = (completed.stdout or completed.stderr or '').strip()
        if output:
            return output.splitlines()[0].strip()
    return None


def _normalize_apalache_output(output: str) -> list[str]:
    markers: list[str] = []
    for raw_line in output.splitlines():
        line = re.sub(r'\s+[IEW]@\d\d:\d\d:\d\d\.\d{3}$', '', raw_line).rstrip()
        if (
            '# APALACHE version:' in line
            or line.startswith('PASS #0: SanyParser')
            or line.startswith('PASS #1: TypeCheckerSnowcat')
            or line.startswith('The outcome is:')
            or line.startswith('Checker reports no error')
            or line.startswith('EXITCODE:')
        ):
            markers.append(line)
    if markers:
        return markers
    return [line.rstrip() for line in output.splitlines()[-12:] if line.strip()]


def _run_single_apalache_check(
    *,
    executable: str,
    invariant: str,
    source: str,
    version_output: str | None,
) -> dict[str, Any]:
    display_command = [
        executable,
        'check',
        '--no-deadlock',
        f'--init={INIT_OPERATOR}',
        f'--next={NEXT_OPERATOR}',
        f'--inv={invariant}',
        TLA_ARTIFACT_PATH,
    ]
    with tempfile.TemporaryDirectory(prefix='xaman-tla-apalache-') as temp_dir:
        temp_path = Path(temp_dir) / Path(TLA_ARTIFACT_PATH).name
        temp_path.write_text(source, encoding='utf-8')
        executed_command = [
            executable,
            'check',
            '--no-deadlock',
            f'--init={INIT_OPERATOR}',
            f'--next={NEXT_OPERATOR}',
            f'--inv={invariant}',
            temp_path.name,
        ]
        try:
            completed = subprocess.run(
                executed_command,
                check=False,
                capture_output=True,
                text=True,
                cwd=temp_dir,
                timeout=120,
            )
        except subprocess.TimeoutExpired as exc:
            stdout = exc.stdout or ''
            stderr = exc.stderr or ''
            exit_code = None
            status = 'timeout'
        except OSError as exc:
            stdout = ''
            stderr = str(exc)
            exit_code = None
            status = 'unavailable'
        else:
            stdout = completed.stdout or ''
            stderr = completed.stderr or ''
            exit_code = completed.returncode
            status = 'pass' if completed.returncode == 0 else 'fail'

    combined_output = '\n'.join(part for part in (stdout, stderr) if part)
    markers = _normalize_apalache_output(combined_output)
    return {
        'invariant': invariant,
        'status': status,
        'exit_code': exit_code,
        'command': display_command,
        'apalache_version': _semantic_version(version_output),
        'version_output': version_output,
        'input_tla_sha256': sha256_label(source),
        'output_evidence': {
            'raw_output_retained': False,
            'normalized_output_sha256': sha256_label('\n'.join(markers) + '\n'),
            'normalized_markers': markers,
            'scope_statement': SCOPE_STATEMENT,
        },
        'reason': (
            'apalache completed the bounded invariant check without a counterexample'
            if status == 'pass'
            else 'apalache did not complete the bounded invariant check successfully'
        ),
    }


def run_apalache_checks(
    *,
    executable: str | None,
    source: str,
    invariants: Sequence[str] = CHECKED_INVARIANTS,
    version_output: str | None = None,
) -> list[dict[str, Any]] | None:
    """Run Apalache checks against an exact temporary copy of *source*."""

    if executable is None:
        return None
    version = version_output if version_output is not None else read_apalache_version(executable)
    return [
        _run_single_apalache_check(
            executable=executable,
            invariant=invariant,
            source=source,
            version_output=version,
        )
        for invariant in invariants
    ]


def _source_binding(tla_source: str) -> dict[str, Any]:
    generated_source = generated_tla_source()
    return {
        'source_of_truth': (
            'ipfs_datasets_py.logic.security_models.crypto_exchange.reports.'
            'xaman_tla_workflow.generated_tla_source'
        ),
        'checked_path': TLA_ARTIFACT_PATH,
        'generator_sha256': sha256_label(generated_source),
        'checked_source_sha256': sha256_label(tla_source),
        'generator_matches_checked_source': generated_source == tla_source,
        'mismatch_is_blocker': True,
    }


def _missing_claim_ids(model_payload: Mapping[str, Any]) -> list[str]:
    claim_ids = {claim.get('id') for claim in model_payload.get('claims', [])}
    return sorted(claim_id for claim_id in COVERED_CLAIM_IDS if claim_id not in claim_ids)


def _blockers(
    *,
    source_binding: Mapping[str, Any],
    apalache_executable: str | None,
    apalache_version: str | None,
    apalache_runs: Sequence[Mapping[str, Any]] | None,
    missing_claim_ids: Sequence[str],
) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    if not source_binding['generator_matches_checked_source']:
        blockers.append(
            {
                'code': 'TLA_GENERATOR_SOURCE_MISMATCH',
                'message': (
                    'The checked XamanSigning.tla source does not exactly match '
                    'the generator output; Apalache output is blocker evidence, '
                    'not proof evidence, until the files are reconciled.'
                ),
                'expected_sha256': source_binding['generator_sha256'],
                'actual_sha256': source_binding['checked_source_sha256'],
            }
        )
    if apalache_executable is None:
        blockers.append(
            {
                'code': 'APALACHE_EXECUTABLE_MISSING',
                'message': 'apalache-mc/apalache executable is not available on PATH',
                'missing': ['apalache-mc', 'apalache'],
            }
        )
    semantic_version = _semantic_version(apalache_version)
    if apalache_executable is not None and semantic_version != REQUIRED_APALACHE_VERSION:
        blockers.append(
            {
                'code': 'APALACHE_VERSION_MISMATCH',
                'message': f'Apalache {REQUIRED_APALACHE_VERSION} is required for this evidence lane',
                'expected': REQUIRED_APALACHE_VERSION,
                'actual': apalache_version,
            }
        )
    if apalache_executable is not None:
        run_by_invariant = {run.get('invariant'): run for run in apalache_runs or []}
        for invariant in CHECKED_INVARIANTS:
            run = run_by_invariant.get(invariant)
            if run is None:
                blockers.append(
                    {
                        'code': 'APALACHE_INVARIANT_RUN_MISSING',
                        'message': f'Missing Apalache output for {invariant}',
                        'invariant': invariant,
                    }
                )
            elif run.get('status') != 'pass' or run.get('exit_code') != 0:
                blockers.append(
                    {
                        'code': 'APALACHE_INVARIANT_RUN_FAILED',
                        'message': f'Apalache did not pass {invariant}',
                        'invariant': invariant,
                        'status': run.get('status'),
                        'exit_code': run.get('exit_code'),
                    }
                )
            elif run.get('input_tla_sha256') != source_binding['checked_source_sha256']:
                blockers.append(
                    {
                        'code': 'APALACHE_RUN_SOURCE_SHA_MISMATCH',
                        'message': f'Apalache output for {invariant} is not bound to the checked source SHA-256',
                        'invariant': invariant,
                        'expected_sha256': source_binding['checked_source_sha256'],
                        'actual_sha256': run.get('input_tla_sha256'),
                    }
                )
    if missing_claim_ids:
        blockers.append(
            {
                'code': 'TLA_CLAIM_BINDING_MISSING',
                'message': 'The model payload is missing claim IDs covered by the Xaman TLA workflow',
                'missing_claim_ids': list(missing_claim_ids),
            }
        )
    return blockers


def build_xaman_tla_workflow_report(
    *,
    model_payload: dict[str, Any],
    model_cid: str,
    lifecycle_facts: dict[str, Any] | None = None,
    tla_source: str | None = None,
    apalache_executable: str | None = None,
    apalache_version: str | None = None,
    apalache_runs: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build the deterministic reconciled Xaman TLA/Apalache report."""

    checked_source = generated_tla_source() if tla_source is None else tla_source
    source_binding = _source_binding(checked_source)
    missing_claims = _missing_claim_ids(model_payload)
    blockers = _blockers(
        source_binding=source_binding,
        apalache_executable=apalache_executable,
        apalache_version=apalache_version,
        apalache_runs=apalache_runs,
        missing_claim_ids=missing_claims,
    )
    all_checked = not blockers and apalache_runs is not None
    checked_count = sum(1 for run in apalache_runs or [] if run.get('status') == 'pass')
    blocked_count = 0 if all_checked else len(CHECKED_INVARIANTS)
    solver_blocker = None
    if blockers:
        solver_blocker = {
            'kind': 'blocked_reconciled_tla_lane',
            'message': blockers[0]['message'],
            'required_action': (
                'Regenerate XamanSigning.tla and both Apalache reports with '
                'Apalache 0.58.3 output bound to the exact checked source SHA-256.'
            ),
        }
    report = {
        'schema_version': SCHEMA_VERSION,
        'task_id': TASK_ID,
        'depends_on': list(DEPENDENCY_TASK_IDS),
        'generated_at_utc': GENERATED_AT_UTC,
        'model_id': model_payload.get('model_id'),
        'model_cid': model_cid,
        'corpus': 'xaman-app',
        'scope': {
            'statement': SCOPE_STATEMENT,
            'meaning': (
                'Apalache output is bounded model-checking evidence for the finite '
                'XamanSigning TLA model only; it is not an unbounded proof of the '
                'wallet, backend, XRPL network, or cryptographic implementation.'
            ),
        },
        'source_binding': source_binding,
        'tla_model': {
            'path': TLA_ARTIFACT_PATH,
            'module': MODULE_NAME,
            'module_name': MODULE_NAME,
            'spec': SPEC_OPERATOR,
            'sha256': source_binding['checked_source_sha256'],
            'generator_sha256': source_binding['generator_sha256'],
            'line_count': len(checked_source.splitlines()),
            'required_operators': list(REQUIRED_OPERATORS),
            'checked_invariants': list(CHECKED_INVARIANTS),
            'invariants': list(CHECKED_INVARIANTS),
        },
        'tla_module': {
            'module_name': MODULE_NAME,
            'path': TLA_ARTIFACT_PATH,
            'artifact_cid': calculate_artifact_cid(
                {'module_name': MODULE_NAME, 'source': checked_source}
            ),
            'source_sha256': source_binding['checked_source_sha256'],
            'line_count': len(checked_source.splitlines()),
            'required_operators': list(REQUIRED_OPERATORS),
        },
        'covered_claim_ids': list(COVERED_CLAIM_IDS),
        'missing_claim_ids': missing_claims,
        'lifecycle_evidence': {
            'path': 'security_ir_artifacts/corpora/xaman-app/payload-lifecycle-facts.json',
            'schema_version': (lifecycle_facts or {}).get('schema_version'),
            'task_id': (lifecycle_facts or {}).get('task_id'),
            'fact_count': len((lifecycle_facts or {}).get('modeled_facts', [])),
        },
        'apalache': {
            'solver': 'apalache',
            'required': True,
            'available': apalache_executable is not None,
            'executable': apalache_executable,
            'version': _semantic_version(apalache_version),
            'version_output': apalache_version,
            'required_version': REQUIRED_APALACHE_VERSION,
            'status': 'PASS' if all_checked else 'BLOCKED',
            'run_status': 'pass' if all_checked else 'blocked',
            'runs': list(apalache_runs or []),
            'blocker': solver_blocker,
            'scope_statement': SCOPE_STATEMENT,
        },
        'blockers': blockers,
        'summary': {
            'source_reconciled': source_binding['generator_matches_checked_source'],
            'all_required_invariants_checked': all_checked,
            'checked_invariant_count': checked_count,
            'required_invariant_count': len(CHECKED_INVARIANTS),
            'run_failure_count': sum(1 for run in apalache_runs or [] if run.get('status') != 'pass'),
            'property_count': len(CHECKED_INVARIANTS),
            'modeled_property_count': len(CHECKED_INVARIANTS),
            'checked_property_count': checked_count if all_checked else 0,
            'blocked_property_count': blocked_count,
            'missing_claim_count': len(missing_claims),
            'blocker_count': len(blockers),
            'release_ready': all_checked,
            'scope_statement': SCOPE_STATEMENT,
        },
        'overall_status': 'checked_bounded_model_only' if all_checked else 'blocked_reconciliation',
        'security_decision': (
            'ACCEPT_BOUNDED_MODEL_EVIDENCE_ONLY'
            if all_checked
            else 'BLOCK_TLA_APALACHE_RECONCILIATION'
        ),
        'production_release_blocked_by_tla_lane': not all_checked,
    }
    report['artifact_cid'] = calculate_artifact_cid(_without_cid(report, 'artifact_cid'))
    return report


def build_apalache_solver_lane_report(
    *,
    repo_root: Path | str,
    tla_source: str,
    xaman_tla_report: Mapping[str, Any] | None,
    apalache_executable: str | None,
    apalache_version: str | None,
    apalache_runs: Sequence[Mapping[str, Any]] | None,
) -> dict[str, Any]:
    """Build the environment-level Apalache lane report for the same evidence."""

    root = Path(repo_root)
    source_binding = _source_binding(tla_source)
    report_tla_sha = None
    report_source_reconciled = None
    report_scope = None
    report_status = None
    report_decision = None
    if xaman_tla_report is not None:
        report_tla_sha = xaman_tla_report.get('tla_model', {}).get('sha256')
        report_source_reconciled = xaman_tla_report.get('source_binding', {}).get(
            'generator_matches_checked_source'
        )
        report_scope = xaman_tla_report.get('scope', {}).get('statement')
        report_status = xaman_tla_report.get('overall_status')
        report_decision = xaman_tla_report.get('security_decision')

    blockers = _blockers(
        source_binding=source_binding,
        apalache_executable=apalache_executable,
        apalache_version=apalache_version,
        apalache_runs=apalache_runs,
        missing_claim_ids=[],
    )
    if xaman_tla_report is None:
        blockers.append(
            {
                'code': 'XAMAN_TLA_REPORT_MISSING',
                'message': f'{APALACHE_REPORT_PATH} is missing or invalid',
            }
        )
    elif report_tla_sha != source_binding['checked_source_sha256']:
        blockers.append(
            {
                'code': 'XAMAN_TLA_REPORT_SOURCE_SHA_MISMATCH',
                'message': 'The Xaman TLA report does not bind the checked TLA source SHA-256',
                'expected_sha256': source_binding['checked_source_sha256'],
                'actual_sha256': report_tla_sha,
            }
        )
    elif report_status != 'checked_bounded_model_only':
        blockers.append(
            {
                'code': 'XAMAN_TLA_REPORT_NOT_ACCEPTED',
                'message': 'The Xaman TLA report is not accepted as bounded model evidence',
                'overall_status': report_status,
                'security_decision': report_decision,
            }
        )

    all_checked = not blockers and apalache_runs is not None
    checked_count = sum(1 for run in apalache_runs or [] if run.get('status') == 'pass')
    report = {
        'schema_version': LANE_SCHEMA_VERSION,
        'task_id': TASK_ID,
        'depends_on': list(DEPENDENCY_TASK_IDS),
        'generated_at_utc': GENERATED_AT_UTC,
        'scope': {
            'statement': SCOPE_STATEMENT,
            'meaning': (
                'This lane records Apalache 0.58.3 bounded model-check output '
                'only and must not be interpreted as an unbounded proof.'
            ),
        },
        'executables': [
            {
                'name': 'apalache-mc',
                'path': shutil.which('apalache-mc'),
                'present': shutil.which('apalache-mc') is not None,
                'version': read_apalache_version(shutil.which('apalache-mc')) or '',
            },
            {
                'name': 'apalache',
                'path': shutil.which('apalache'),
                'present': shutil.which('apalache') is not None,
                'version': read_apalache_version(shutil.which('apalache')) or '',
            },
        ],
        'selected_executable': {
            'name': Path(apalache_executable).name if apalache_executable else None,
            'path': apalache_executable,
            'version': _semantic_version(apalache_version),
            'version_output': apalache_version,
        } if apalache_executable else None,
        'tla_model': {
            'path': TLA_ARTIFACT_PATH,
            'exists': (root / TLA_ARTIFACT_PATH).is_file(),
            'sha256': source_binding['checked_source_sha256'],
            'generator_sha256': source_binding['generator_sha256'],
            'generator_matches_checked_source': source_binding['generator_matches_checked_source'],
        },
        'xaman_tla_report': {
            'path': APALACHE_REPORT_PATH,
            'exists': xaman_tla_report is not None,
            'overall_status': report_status,
            'security_decision': report_decision,
            'reported_tla_sha256': report_tla_sha,
            'source_matches_report': report_tla_sha == source_binding['checked_source_sha256'],
            'source_reconciled': report_source_reconciled,
            'scope_statement': report_scope,
        },
        'model_check': {
            'required_version': REQUIRED_APALACHE_VERSION,
            'version': _semantic_version(apalache_version),
            'version_output': apalache_version,
            'checked_invariants': list(CHECKED_INVARIANTS),
            'runs': list(apalache_runs or []),
            'scope_statement': SCOPE_STATEMENT,
        },
        'blockers': blockers,
        'summary': {
            'apalache_present': apalache_executable is not None,
            'apalache_version_matches_required': _semantic_version(apalache_version) == REQUIRED_APALACHE_VERSION,
            'tla_model_present': (root / TLA_ARTIFACT_PATH).is_file(),
            'source_reconciled': source_binding['generator_matches_checked_source'],
            'report_source_bound': report_tla_sha == source_binding['checked_source_sha256'],
            'model_check_run': bool(apalache_runs),
            'model_check_passed': all_checked,
            'checked_invariant_count': checked_count,
            'required_invariant_count': len(CHECKED_INVARIANTS),
            'blocker_count': len(blockers),
            'scope_statement': SCOPE_STATEMENT,
        },
        'overall_status': 'ready_bounded_model_only' if all_checked else 'blocked_reconciliation',
        'security_decision': (
            'APALACHE_0583_BOUNDED_MODEL_OUTPUT_BOUND'
            if all_checked
            else 'BLOCK_APALACHE_TLA_RECONCILIATION'
        ),
        'production_release_blocked_by_apalache_lane': not all_checked,
    }
    report['artifact_cid'] = calculate_artifact_cid(_without_cid(report, 'artifact_cid'))
    return report


__all__ = [
    'APALACHE_REPORT_PATH',
    'APALACHE_SOLVER_LANE_REPORT_PATH',
    'CHECKED_INVARIANTS',
    'COVERED_CLAIM_IDS',
    'DEPENDENCY_TASK_IDS',
    'MODULE_NAME',
    'REQUIRED_APALACHE_VERSION',
    'REQUIRED_OPERATORS',
    'SCHEMA_VERSION',
    'SCOPE_STATEMENT',
    'TASK_ID',
    'TLA_ARTIFACT_PATH',
    'XAMAN_SIGNING_TLA',
    'build_apalache_solver_lane_report',
    'build_xaman_tla_workflow_report',
    'discover_apalache_executable',
    'generated_tla_source',
    'read_apalache_version',
    'run_apalache_checks',
    'sha256_label',
]
