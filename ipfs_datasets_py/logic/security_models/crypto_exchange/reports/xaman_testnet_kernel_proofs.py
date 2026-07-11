"""Lean kernel report and Coq coverage decision for Xaman Testnet invariants."""

from __future__ import annotations

import hashlib
import shutil
import subprocess
from pathlib import Path
from typing import Any, Mapping, Sequence

from ..ir.cid import calculate_artifact_cid


TASK_ID = 'PORTAL-CXTP-136'
GENERATED_AT_UTC = '2026-07-11T00:00:00Z'
LEAN_REPORT_SCHEMA_VERSION = 'xaman-testnet-lean-kernel-report/v1'
COQ_DECISION_SCHEMA_VERSION = 'xaman-testnet-coq-coverage-decision/v1'
MODEL_PATH = 'security_ir_artifacts/corpora/xaman-app/testnet/security-model-ir.json'
MODEL_CID_PATH = 'security_ir_artifacts/corpora/xaman-app/testnet/security-model-ir.cid'
TRACE_MAP_PATH = 'security_ir_artifacts/corpora/xaman-app/testnet/claim-trace-map.json'
ASSUMPTIONS_PATH = 'security_ir_artifacts/corpora/xaman-app/testnet/assumptions.json'
LEAN_KERNEL_PATH = 'security_ir_artifacts/corpora/xaman-app/testnet/proof-kernel/XamanTestnet.lean'
LEAN_REPORT_PATH = 'security_ir_artifacts/corpora/xaman-app/testnet/proof-kernel/lean-report.json'
COQ_KERNEL_PATH = 'security_ir_artifacts/corpora/xaman-app/testnet/proof-kernel/XamanTestnet.v'
COQ_DECISION_PATH = 'security_ir_artifacts/corpora/xaman-app/testnet/coq-coverage-decision.json'
TESTNET_PLAN_PATH = 'docs/security_verification/xaman_xrpl_testnet_theorem_prover_assurance_plan.md'

FORMALIZED_INVARIANTS = (
    'testnetNetworkBoundary',
    'freshAccountBoundary',
    'observedLifecycleOrder',
    'auditRedactionBoundary',
    'formalizedInvariantHolds',
    'canUseLeanEvidenceForClaim',
    'canCloseTestnetAssurance',
)
LEAN_THEOREMS = (
    'reject_counterexample_result',
    'reject_incomplete_result',
    'reject_not_modeled_claim',
    'reject_blocking_not_modeled_boundary',
    'reject_model_cid_mismatch',
    'reject_claim_outside_frozen_model',
    'reject_unreviewed_evidence',
    'reject_wrong_network_key',
    'reject_wrong_network_id',
    'reject_non_allowlisted_endpoint',
    'reject_imported_or_production_account',
    'reject_account_material_retained',
    'reject_missing_payload_intake',
    'reject_missing_review',
    'reject_missing_auth',
    'reject_missing_signing_decision',
    'reject_missing_submit_result',
    'reject_misordered_lifecycle',
    'reject_raw_payload_retained',
    'reject_raw_signature_blob_retained',
    'reject_redaction_failure',
    'missing_assumptions_prevent_assurance',
    'missing_runtime_equivalence_prevents_assurance',
    'missing_independent_kernel_prevents_assurance',
)
LEAN_COVERED_CLAIM_IDS = (
    'xaman-testnet-claim:network-binding-is-testnet-only',
    'xaman-testnet-claim:account-provenance-is-fresh-testnet-only',
    'xaman-testnet-claim:review-auth-sequence-observed',
    'xaman-testnet-claim:audit-redaction-boundary-is-preserved',
)
LEAN_REJECTED_SCOPE_CLAIM_IDS = (
    'xaman-testnet-claim:signing-decision-is-observed-but-crypto-output-is-not-modeled',
    'xaman-testnet-claim:submission-ui-attempt-and-result-are-observed',
    'xaman-testnet-claim:payload-intake-is-categorical-only',
    'xaman-testnet-claim:refusal-path-is-not-modeled',
    'xaman-testnet-claim:replay-controls-are-not-modeled',
    'xaman-testnet-claim:expiry-path-is-not-modeled',
    'xaman-testnet-claim:cancellation-path-is-not-modeled',
    'xaman-testnet-claim:broadcast-and-ledger-finality-are-not-modeled',
)


def build_xaman_testnet_lean_report(
    *,
    model_payload: Mapping[str, Any],
    model_cid: str,
    trace_map_payload: Mapping[str, Any],
    assumptions_payload: Mapping[str, Any],
    lean_source: str,
    lean_executable: str | None = None,
    lean_version: str | None = None,
    lean_compile: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a deterministic Lean report for the Testnet kernel."""

    _validate_bound_inputs(model_payload, model_cid, trace_map_payload, assumptions_payload)
    claims_by_id = {claim['id']: claim for claim in model_payload.get('claims', [])}
    assumption_ids = [
        assumption['id']
        for assumption in assumptions_payload.get('assumptions', model_payload.get('assumptions', []))
        if assumption.get('status') == 'BLOCKING'
    ]
    missing_claim_ids = sorted((set(LEAN_COVERED_CLAIM_IDS) | set(LEAN_REJECTED_SCOPE_CLAIM_IDS)) - set(claims_by_id))
    contains_forbidden = _contains_forbidden_placeholder(lean_source)
    compile_payload = dict(lean_compile or _not_run_compile(lean_executable))
    compile_passed = compile_payload.get('returncode') == 0 and compile_payload.get('status') == 'passed'

    if contains_forbidden:
        overall_status = 'blocked_placeholder_in_kernel'
        security_decision = 'BLOCK_TESTNET_LEAN_KERNEL_PLACEHOLDER'
    elif not compile_passed:
        overall_status = 'blocked_lean_kernel_not_checked'
        security_decision = 'BLOCK_TESTNET_LEAN_KERNEL_NOT_CHECKED'
    else:
        overall_status = 'checked_with_scope_limits'
        security_decision = 'LEAN_TESTNET_KERNEL_CHECKED_FORMALIZED_INVARIANTS_ONLY'

    report: dict[str, Any] = {
        'schema_version': LEAN_REPORT_SCHEMA_VERSION,
        'task_id': TASK_ID,
        'generated_at_utc': GENERATED_AT_UTC,
        'model': {
            'path': MODEL_PATH,
            'cid_path': MODEL_CID_PATH,
            'id': model_payload['model_id'],
            'schema_version': model_payload['schema_version'],
            'cid': model_cid,
        },
        'inputs': {
            'claim_trace_map': {
                'path': TRACE_MAP_PATH,
                'model_cid': trace_map_payload['model_cid'],
                'artifact_cid': trace_map_payload.get('artifact_cid') or calculate_artifact_cid(trace_map_payload),
            },
            'assumptions': {
                'path': ASSUMPTIONS_PATH,
                'model_cid': assumptions_payload['model_cid'],
                'artifact_cid': assumptions_payload.get('artifact_cid') or calculate_artifact_cid(assumptions_payload),
                'blocking_assumption_count': len(assumption_ids),
            },
            'reviewed_testnet_plan': {
                'path': TESTNET_PLAN_PATH,
                'coq_decision_rule': 'Coq is required when the reviewed threat model requires an independent kernel.',
            },
        },
        'kernel': {
            'language': 'Lean 4',
            'path': LEAN_KERNEL_PATH,
            'artifact_cid': 'sha256:' + hashlib.sha256(lean_source.encode('utf-8')).hexdigest(),
            'line_count': len(lean_source.splitlines()),
            'contains_sorry': 'sorry' in lean_source,
            'contains_admit': 'admit' in lean_source,
            'formalized_invariants': list(FORMALIZED_INVARIANTS),
            'theorems': list(LEAN_THEOREMS),
        },
        'lean': {
            'status': 'compiled' if compile_passed else 'not_checked',
            'executable': lean_executable,
            'version': lean_version or '',
            'compile': compile_payload,
        },
        'coverage': {
            'scope_statement': (
                'Lean evidence is accepted only for the Boolean predicates formalized in XamanTestnet.lean. '
                'It does not prove native vault cryptography, raw payload semantics, backend single-use, '
                'XRPL finality, deployed runtime equivalence, or production security.'
            ),
            'covered_claim_ids': list(LEAN_COVERED_CLAIM_IDS),
            'rejected_scope_claim_ids': list(LEAN_REJECTED_SCOPE_CLAIM_IDS),
            'missing_claim_ids': missing_claim_ids,
            'result_policy': {
                'accepted_kernel_results': ['proved'],
                'rejected_kernel_results': ['counterexample', 'incomplete'],
                'claim_status_required': 'MODELED_WITH_TESTNET_SCOPE',
                'model_cid_match_required': True,
                'frozen_claim_membership_required': True,
                'human_reviewed_evidence_required': True,
                'blocking_assumptions_clearance_required_for_assurance': True,
                'runtime_equivalence_required_for_assurance': True,
                'independent_kernel_required_for_assurance': True,
            },
        },
        'summary': {
            'lean_kernel_checked': compile_passed,
            'formalized_invariant_count': len(FORMALIZED_INVARIANTS),
            'theorem_count': len(LEAN_THEOREMS),
            'covered_claim_count': len(LEAN_COVERED_CLAIM_IDS),
            'rejected_scope_claim_count': len(LEAN_REJECTED_SCOPE_CLAIM_IDS),
            'blocking_assumption_count': len(assumption_ids),
            'missing_claim_count': len(missing_claim_ids),
        },
        'overall_status': overall_status,
        'security_decision': security_decision,
        'testnet_assurance_blocked': True,
        'production_release_blocked': True,
    }
    report['report_cid'] = calculate_artifact_cid(_without_key(report, 'report_cid'))
    return report


def build_xaman_testnet_coq_coverage_decision(
    *,
    model_payload: Mapping[str, Any],
    model_cid: str,
    lean_report: Mapping[str, Any],
    coq_kernel_source: str | None = None,
    coqc_executable: str | None = None,
    coqc_version: str | None = None,
    coq_check: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the Coq independent-kernel coverage decision."""

    if lean_report.get('model', {}).get('cid') != model_cid:
        raise ValueError('Lean report model CID does not match the pinned Testnet model CID')

    coq_required = True
    coq_kernel_present = coq_kernel_source is not None
    check_payload = dict(coq_check or _not_run_coq_check(coqc_executable, coq_kernel_present))
    coq_checked = check_payload.get('returncode') == 0 and check_payload.get('status') == 'passed'
    if coq_required and not coq_checked:
        overall_status = 'coverage_gap_required_independent_kernel_missing'
        security_decision = 'BLOCK_TESTNET_ASSURANCE_INDEPENDENT_COQ_KERNEL_MISSING'
        decision = 'required_missing_artifact' if not coq_kernel_present else 'required_check_failed'
    else:
        overall_status = 'independent_kernel_checked'
        security_decision = 'COQ_INDEPENDENT_KERNEL_CHECKED'
        decision = 'required_checked'

    report: dict[str, Any] = {
        'schema_version': COQ_DECISION_SCHEMA_VERSION,
        'task_id': TASK_ID,
        'generated_at_utc': GENERATED_AT_UTC,
        'model': {
            'path': MODEL_PATH,
            'cid_path': MODEL_CID_PATH,
            'id': model_payload['model_id'],
            'schema_version': model_payload['schema_version'],
            'cid': model_cid,
        },
        'lean_report': {
            'path': LEAN_REPORT_PATH,
            'schema_version': lean_report.get('schema_version'),
            'report_cid': lean_report.get('report_cid'),
            'security_decision': lean_report.get('security_decision'),
            'formalized_invariant_only': True,
        },
        'decision': decision,
        'coq_required_by_reviewed_threat_model': coq_required,
        'requirement_source': {
            'path': TESTNET_PLAN_PATH,
            'rule': (
                'The reviewed Testnet plan requires Coq when independent kernel coverage is needed; '
                'this task records that Lean-only evidence is insufficient for the independent-kernel lane.'
            ),
        },
        'coq': {
            'coqc_present': coqc_executable is not None,
            'coqc_executable': coqc_executable,
            'coqc_version': coqc_version or '',
            'kernel_path': COQ_KERNEL_PATH,
            'kernel_present': coq_kernel_present,
            'kernel_artifact_cid': (
                'sha256:' + hashlib.sha256(coq_kernel_source.encode('utf-8')).hexdigest()
                if coq_kernel_source is not None
                else None
            ),
            'check': check_payload,
        },
        'coverage_gap': {
            'missing_coq_declared_coverage_gap': not coq_checked,
            'unavailable_or_missing_coq_blocks_testnet_assurance': coq_required and not coq_checked,
            'does_not_invalidate_checked_lean_formalized_invariant': True,
            'scope': (
                'Coq would provide an independent kernel check for the same formalized invariant family; '
                'it would still not prove facts outside the model or raw/runtime behavior not represented there.'
            ),
        },
        'overall_status': overall_status,
        'security_decision': security_decision,
        'testnet_assurance_blocked': coq_required and not coq_checked,
        'production_release_blocked': True,
    }
    report['artifact_cid'] = calculate_artifact_cid(_without_key(report, 'artifact_cid'))
    return report


def run_lean_kernel_check(*, repo_root: Path, lean_executable: str | None = None) -> tuple[str | None, str, dict[str, Any]]:
    """Run Lean on the checked-in Testnet kernel and return executable, version, and result."""

    kernel_path = repo_root / LEAN_KERNEL_PATH
    executable = lean_executable or shutil.which('lean')
    if executable is None and kernel_path.is_file():
        from ipfs_datasets_py.logic.external_provers.lazy_installer import ensure_prover_executable

        executable = ensure_prover_executable(
            'lean',
            reason='Xaman Testnet Lean kernel execution',
        )
    version = _version(executable, ['--version'])
    if executable is None:
        return None, '', _not_run_compile(None)
    try:
        completed = subprocess.run(
            [executable, str(kernel_path)],
            check=False,
            capture_output=True,
            text=True,
            timeout=90,
        )
    except subprocess.TimeoutExpired as exc:
        return executable, version, {
            'command': [executable, LEAN_KERNEL_PATH],
            'returncode': None,
            'status': 'timeout',
            'stdout': exc.stdout or '',
            'stderr': exc.stderr or '',
        }
    return executable, version, {
        'command': [executable, LEAN_KERNEL_PATH],
        'returncode': completed.returncode,
        'status': 'passed' if completed.returncode == 0 else 'failed',
        'stdout': completed.stdout,
        'stderr': completed.stderr,
    }


def run_coq_kernel_check(*, repo_root: Path, coqc_executable: str | None = None) -> tuple[str | None, str, str | None, dict[str, Any]]:
    """Run Coq only when the Testnet Coq artifact exists."""

    kernel_path = repo_root / COQ_KERNEL_PATH
    if not kernel_path.is_file():
        executable = coqc_executable or shutil.which('coqc')
        version = _version(executable, ['--version'])
        return executable, version, None, _not_run_coq_check(executable, False)
    source = kernel_path.read_text(encoding='utf-8')
    executable = coqc_executable or shutil.which('coqc')
    if executable is None:
        from ipfs_datasets_py.logic.external_provers.lazy_installer import ensure_prover_executable

        executable = ensure_prover_executable(
            'coq',
            reason='Xaman Testnet Coq kernel execution',
        )
    version = _version(executable, ['--version'])
    if executable is None:
        return None, '', source, _not_run_coq_check(None, True)
    try:
        completed = subprocess.run(
            [executable, str(kernel_path)],
            check=False,
            capture_output=True,
            text=True,
            timeout=90,
        )
    except subprocess.TimeoutExpired as exc:
        return executable, version, source, {
            'command': [executable, COQ_KERNEL_PATH],
            'returncode': None,
            'status': 'timeout',
            'stdout': exc.stdout or '',
            'stderr': exc.stderr or '',
        }
    return executable, version, source, {
        'command': [executable, COQ_KERNEL_PATH],
        'returncode': completed.returncode,
        'status': 'passed' if completed.returncode == 0 else 'failed',
        'stdout': completed.stdout,
        'stderr': completed.stderr,
    }


def _validate_bound_inputs(
    model_payload: Mapping[str, Any],
    model_cid: str,
    trace_map_payload: Mapping[str, Any],
    assumptions_payload: Mapping[str, Any],
) -> None:
    if trace_map_payload.get('model_cid') != model_cid:
        raise ValueError('claim-trace-map model_cid does not match the pinned Testnet model CID')
    if assumptions_payload.get('model_cid') != model_cid:
        raise ValueError('assumptions model_cid does not match the pinned Testnet model CID')
    if model_payload.get('metadata', {}).get('production_release_blocked') is not True:
        raise ValueError('Testnet kernel report must bind to a production-blocking Testnet model')


def _contains_forbidden_placeholder(source: str) -> bool:
    return 'sorry' in source or 'admit' in source


def _without_key(payload: Mapping[str, Any], key: str) -> dict[str, Any]:
    return {item_key: value for item_key, value in payload.items() if item_key != key}


def _not_run_compile(lean_executable: str | None) -> dict[str, Any]:
    return {
        'command': [lean_executable or 'lean', LEAN_KERNEL_PATH],
        'returncode': None,
        'status': 'not-run',
        'stdout': '',
        'stderr': 'lean executable missing or compile result not supplied',
    }


def _not_run_coq_check(coqc_executable: str | None, coq_kernel_present: bool) -> dict[str, Any]:
    reason = 'coq kernel artifact is missing'
    if coqc_executable is None:
        reason = 'coqc executable is missing'
    if coqc_executable is None and not coq_kernel_present:
        reason = 'coqc executable or coq kernel artifact is missing'
    return {
        'command': [coqc_executable or 'coqc', COQ_KERNEL_PATH],
        'returncode': None,
        'status': 'not-run',
        'stdout': '',
        'stderr': reason,
    }


def _version(executable: str | None, args: Sequence[str]) -> str:
    if executable is None:
        return ''
    try:
        completed = subprocess.run(
            [executable, *args],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ''
    output = (completed.stdout or completed.stderr or '').strip()
    return output.splitlines()[0] if output else ''
