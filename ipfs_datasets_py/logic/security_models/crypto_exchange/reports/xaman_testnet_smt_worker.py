"""Deterministic SMT worker lock and CVC5 differential report for Xaman Testnet."""

from __future__ import annotations

import hashlib
from dataclasses import replace
from pathlib import Path
from typing import Any, Mapping

from ..compilers.to_smtlib import (
    SMTLIB_LOGIC,
    XAMAN_CRITICAL_SEVERITIES,
    XAMAN_SMTLIB_QUERY_KIND,
    compile_ir_claims_to_smtlib,
)
from ..ir.canonicalize import canonicalize_ir
from ..ir.cid import calculate_artifact_cid
from ..ir.schema import SecurityModelIR, validate_ir
from ..runners.cvc5_runner import (
    CVC5Runner,
    SMTLIBSolverRun,
    SUPPORTED_SMTLIB_LOGICS,
    run_z3_smtlib_artifact,
)


MODEL_PATH = 'security_ir_artifacts/corpora/xaman-app/testnet/security-model-ir.json'
MODEL_CID_PATH = 'security_ir_artifacts/corpora/xaman-app/testnet/security-model-ir.cid'
TRACE_MAP_PATH = 'security_ir_artifacts/corpora/xaman-app/testnet/claim-trace-map.json'
ASSUMPTIONS_PATH = 'security_ir_artifacts/corpora/xaman-app/testnet/assumptions.json'
SMTLIB_DIR = 'security_ir_artifacts/corpora/xaman-app/testnet/smtlib'
PROOF_WORKER_LOCK_PATH = 'security_ir_artifacts/corpora/xaman-app/testnet/proof-worker-lock.json'
CVC5_RUNNER_REPORT_PATH = 'security_ir_artifacts/corpora/xaman-app/testnet/cvc5-runner-report.json'
SOLVER_DEPENDENCY_PROBE_PATH = 'security_ir_artifacts/environment/solver-dependency-probe.json'

TASK_ID = 'PORTAL-CXTP-132'
GENERATED_AT_UTC = '2026-07-11T00:00:00Z'
WORKER_ID = 'xaman-testnet-smt-proof-worker'
WORKER_VERSION = 'xaman-testnet-smt-proof-worker/v1'
LOCK_SCHEMA_VERSION = 'xaman-testnet-proof-worker-lock/v1'
RUNNER_REPORT_SCHEMA_VERSION = 'xaman-testnet-cvc5-runner-report/v1'
SELECTED_PROVERS = ('z3', 'cvc5')
FAIL_CLOSED_SOLVER_RESULTS = frozenset(
    {
        'unknown',
        'timeout',
        'unsupported',
        'parser_error',
        'error',
        'unavailable',
    }
)


def build_xaman_testnet_smt_worker_artifacts(
    model_payload: Mapping[str, Any],
    *,
    model_cid: str,
    trace_map_payload: Mapping[str, Any],
    assumptions_payload: Mapping[str, Any],
    timeout_ms: int = 5_000,
    cvc5_executable: str | None = None,
) -> dict[str, dict[str, Any]]:
    """Build the worker lock and differential execution report without writing files."""

    model = validate_ir(SecurityModelIR.from_untrusted_dict(dict(model_payload), strict=True))
    calculated_model_cid = stable_sha256_model_cid(model)
    if calculated_model_cid != model_cid:
        raise ValueError(f'Testnet model CID mismatch: expected {model_cid}, calculated {calculated_model_cid}')
    if trace_map_payload.get('model_cid') != model_cid:
        raise ValueError('claim-trace-map model_cid does not match the pinned Testnet model CID')
    if assumptions_payload.get('model_cid') != model_cid:
        raise ValueError('assumptions model_cid does not match the pinned Testnet model CID')

    artifacts = compile_pinned_testnet_smtlib_artifacts(model, model_cid=model_cid)
    claim_ids = [artifact.claim_id for artifact in artifacts]
    lock = _build_worker_lock(
        model,
        model_cid=model_cid,
        claim_ids=claim_ids,
        trace_map_payload=trace_map_payload,
        assumptions_payload=assumptions_payload,
        timeout_ms=timeout_ms,
    )
    runner_report = _build_runner_report(
        model,
        model_cid=model_cid,
        artifacts=artifacts,
        lock=lock,
        timeout_ms=timeout_ms,
        cvc5_executable=cvc5_executable,
    )
    return {
        'proof_worker_lock': lock,
        'cvc5_runner_report': runner_report,
    }


def stable_sha256_model_cid(model: SecurityModelIR | Mapping[str, Any]) -> str:
    """Return the sha256 CID format used by the Testnet model projection."""

    return 'sha256:' + hashlib.sha256(canonicalize_ir(model)).hexdigest()


def compile_pinned_testnet_smtlib_artifacts(
    model: SecurityModelIR | Mapping[str, Any],
    *,
    model_cid: str,
) -> list[Any]:
    """Compile Testnet SMT-LIB artifacts and bind their headers to *model_cid*."""

    artifacts = compile_ir_claims_to_smtlib(model, severities=XAMAN_CRITICAL_SEVERITIES)
    rebound = []
    for artifact in artifacts:
        if artifact.model_cid == model_cid:
            rebound.append(artifact)
            continue
        metadata = dict(artifact.metadata)
        metadata['model_cid'] = model_cid
        rebound.append(
            replace(
                artifact,
                model_cid=model_cid,
                metadata=metadata,
                smtlib=artifact.smtlib.replace(artifact.model_cid, model_cid),
            )
        )
    return rebound


def _build_worker_lock(
    model: SecurityModelIR,
    *,
    model_cid: str,
    claim_ids: list[str],
    trace_map_payload: Mapping[str, Any],
    assumptions_payload: Mapping[str, Any],
    timeout_ms: int,
) -> dict[str, Any]:
    lock: dict[str, Any] = {
        'schema_version': LOCK_SCHEMA_VERSION,
        'task_id': TASK_ID,
        'generated_at_utc': GENERATED_AT_UTC,
        'worker': {
            'id': WORKER_ID,
            'version': WORKER_VERSION,
            'track': 'solver',
            'locked': True,
        },
        'model': {
            'path': MODEL_PATH,
            'cid_path': MODEL_CID_PATH,
            'id': model.model_id,
            'schema_version': model.schema_version,
            'cid': model_cid,
            'allowed_model_cids': [model_cid],
        },
        'claim_scope': {
            'selection': 'all-blocking-and-high-testnet-claims',
            'severities': sorted(XAMAN_CRITICAL_SEVERITIES),
            'claim_count': len(claim_ids),
            'claim_ids': claim_ids,
        },
        'smt_contract': {
            'query_kind': XAMAN_SMTLIB_QUERY_KIND,
            'logic': SMTLIB_LOGIC,
            'supported_smtlib_logics': sorted(SUPPORTED_SMTLIB_LOGICS),
            'selected_provers': list(SELECTED_PROVERS),
            'timeout_ms': timeout_ms,
            'fail_closed_solver_results': sorted(FAIL_CLOSED_SOLVER_RESULTS),
            'z3_cvc5_disagreement_blocks_testnet_assurance': True,
            'unknown_timeout_unsupported_blocks_testnet_assurance': True,
        },
        'inputs': {
            'security_model_ir': {
                'path': MODEL_PATH,
                'cid': model_cid,
                'artifact_cid': calculate_artifact_cid(model.to_dict()),
            },
            'claim_trace_map': {
                'path': TRACE_MAP_PATH,
                'model_cid': trace_map_payload['model_cid'],
                'artifact_cid': calculate_artifact_cid(trace_map_payload),
            },
            'assumptions': {
                'path': ASSUMPTIONS_PATH,
                'model_cid': assumptions_payload['model_cid'],
                'artifact_cid': calculate_artifact_cid(assumptions_payload),
                'blocking_assumption_count': assumptions_payload.get('blocking_assumption_count'),
            },
            'solver_dependency_probe': {
                'path': SOLVER_DEPENDENCY_PROBE_PATH,
                'required_for_task': ['z3', 'cvc5'],
            },
        },
        'outputs': {
            'proof_worker_lock': PROOF_WORKER_LOCK_PATH,
            'cvc5_runner_report': CVC5_RUNNER_REPORT_PATH,
            'smtlib_dir': SMTLIB_DIR,
        },
    }
    lock['lock_cid'] = _artifact_cid_without_self(lock, 'lock_cid')
    return lock


def _build_runner_report(
    model: SecurityModelIR,
    *,
    model_cid: str,
    artifacts: list[Any],
    lock: Mapping[str, Any],
    timeout_ms: int,
    cvc5_executable: str | None,
) -> dict[str, Any]:
    cvc5_runner = CVC5Runner(timeout_ms=timeout_ms, executable=cvc5_executable)
    claim_reports: list[dict[str, Any]] = []
    for artifact in artifacts:
        logic = str(artifact.metadata.get('logic') or '')
        unsupported_theory = logic not in SUPPORTED_SMTLIB_LOGICS
        if unsupported_theory:
            z3_result = _unsupported_solver_run('z3', logic)
            cvc5_result = _unsupported_solver_run('cvc5', logic)
        else:
            z3_result = run_z3_smtlib_artifact(artifact, timeout_ms=timeout_ms)
            cvc5_result = cvc5_runner.run_smtlib_artifact(artifact)
        claim_reports.append(
            classify_testnet_smt_claim(
                artifact,
                z3_result=z3_result,
                cvc5_result=cvc5_result,
                unsupported_theory=unsupported_theory,
            )
        )

    summary = summarize_testnet_smt_claims(claim_reports)
    report: dict[str, Any] = {
        'schema_version': RUNNER_REPORT_SCHEMA_VERSION,
        'task_id': TASK_ID,
        'generated_at_utc': GENERATED_AT_UTC,
        'model': {
            'path': MODEL_PATH,
            'cid_path': MODEL_CID_PATH,
            'id': model.model_id,
            'schema_version': model.schema_version,
            'cid': model_cid,
        },
        'proof_worker_lock': {
            'path': PROOF_WORKER_LOCK_PATH,
            'lock_cid': lock['lock_cid'],
            'worker_id': lock['worker']['id'],
            'worker_version': lock['worker']['version'],
        },
        'selected_provers': list(SELECTED_PROVERS),
        'timeout_ms': timeout_ms,
        'smtlib_dir': SMTLIB_DIR,
        'supported_smtlib_logics': sorted(SUPPORTED_SMTLIB_LOGICS),
        'cvc5': {
            'executable': cvc5_runner._executable_path(),
            'version': cvc5_runner._solver_version(),
        },
        'summary': summary,
        'claims': claim_reports,
    }
    report['overall_status'] = summary['overall_status']
    report['security_decision'] = summary['security_decision']
    report['production_release_blocked'] = True
    report['report_cid'] = _artifact_cid_without_self(report, 'report_cid')
    return report


def classify_testnet_smt_claim(
    artifact: Any,
    *,
    z3_result: SMTLIBSolverRun,
    cvc5_result: SMTLIBSolverRun,
    unsupported_theory: bool,
) -> dict[str, Any]:
    """Classify one locked Testnet claim under the Z3/CVC5 fail-closed policy."""

    solver_results = {
        'z3': _solver_run_dict(z3_result),
        'cvc5': _solver_run_dict(cvc5_result),
    }
    z3_value = z3_result.solver_result
    cvc5_value = cvc5_result.solver_result
    comparable = z3_value in {'sat', 'unsat', 'unknown'} and cvc5_value in {'sat', 'unsat', 'unknown'}
    disagreement = comparable and z3_value != cvc5_value
    solver_blockers = _solver_blockers(
        z3_result=z3_result,
        cvc5_result=cvc5_result,
        unsupported_theory=unsupported_theory,
        disagreement=disagreement,
    )
    assumption_blockers = list(artifact.metadata.get('blocking_assumption_ids', []))
    if solver_blockers:
        classification = 'solver_blocked'
        release_policy = 'block'
        reason = '; '.join(solver_blockers)
    elif assumption_blockers and z3_value == cvc5_value == 'sat':
        classification = 'blocked_assumption'
        release_policy = 'block'
        reason = 'both solvers found unresolved blocking assumptions'
    elif z3_value == cvc5_value == 'unsat':
        classification = 'proved_candidate'
        release_policy = 'allow-proof-promotion'
        reason = 'both solvers found no satisfiable blocking acceptance condition'
    elif z3_value == cvc5_value == 'sat':
        classification = 'disproved'
        release_policy = 'block'
        reason = 'both solvers found a satisfiable violation without declared assumption blockers'
    else:
        classification = 'solver_blocked'
        release_policy = 'block'
        reason = 'solver result combination is not accepted by the Testnet worker'

    return {
        'claim_id': artifact.claim_id,
        'claim_version': artifact.claim_version,
        'severity': artifact.metadata['severity'],
        'domain': artifact.metadata.get('domain'),
        'query_kind': artifact.metadata['query_kind'],
        'logic': artifact.metadata['logic'],
        'smtlib_artifact': {
            'path': f'{SMTLIB_DIR}/{_safe_filename(artifact.claim_id)}.smt2',
            'artifact_cid': artifact.artifact_cid,
            'assertion_count': artifact.metadata['assertion_count'],
        },
        'blocked_by_assumptions': assumption_blockers,
        'solver_results': solver_results,
        'solver_agreement': not disagreement,
        'unsupported_theory': unsupported_theory,
        'solver_blockers': solver_blockers,
        'classification': classification,
        'classification_reason': reason,
        'release_policy': release_policy,
        'testnet_assurance_blocked': release_policy == 'block',
        'evidence_refs': list(artifact.metadata.get('evidence_refs', [])),
        'soundness_notes': list(artifact.metadata.get('soundness_notes', [])),
    }


def summarize_testnet_smt_claims(claim_reports: list[Mapping[str, Any]]) -> dict[str, Any]:
    """Summarize deterministic Testnet SMT classifications."""

    solver_blocked = [claim for claim in claim_reports if claim['classification'] == 'solver_blocked']
    assumption_blocked = [claim for claim in claim_reports if claim['classification'] == 'blocked_assumption']
    disproved = [claim for claim in claim_reports if claim['classification'] == 'disproved']
    proved = [claim for claim in claim_reports if claim['classification'] == 'proved_candidate']
    if solver_blocked:
        overall_status = 'blocked_by_solver_differential_failure'
        security_decision = 'BLOCK_TESTNET_ASSURANCE_SOLVER_DIFFERENTIAL_FAILURE'
    elif assumption_blocked or disproved:
        overall_status = 'blocked_by_unresolved_assumptions'
        security_decision = 'BLOCK_TESTNET_ASSURANCE_UNRESOLVED_ASSUMPTIONS'
    else:
        overall_status = 'differential_execution_ready'
        security_decision = 'READY_FOR_TESTNET_CLAIM_PROOF_PROMOTION'
    return {
        'claim_count': len(claim_reports),
        'covered_claim_count': len(claim_reports),
        'proved_candidate_count': len(proved),
        'blocked_assumption_count': len(assumption_blocked),
        'disproved_count': len(disproved),
        'solver_blocker_count': len(solver_blocked),
        'unsupported_theory_count': sum(bool(claim['unsupported_theory']) for claim in claim_reports),
        'timeout_count': _count_solver_result(claim_reports, 'timeout'),
        'unknown_count': _count_solver_result(claim_reports, 'unknown'),
        'disagreement_count': sum(not bool(claim['solver_agreement']) for claim in claim_reports),
        'cvc5_executed_claim_count': sum(
            claim['solver_results']['cvc5']['solver_result'] in {'sat', 'unsat', 'unknown'}
            for claim in claim_reports
        ),
        'overall_status': overall_status,
        'security_decision': security_decision,
        'testnet_assurance_blocked': overall_status != 'differential_execution_ready',
    }


def _unsupported_solver_run(prover: str, logic: str) -> SMTLIBSolverRun:
    return SMTLIBSolverRun(
        prover=prover,
        solver_result='unsupported',
        reason_unknown=f'unsupported SMT-LIB logic {logic}',
    )


def _solver_blockers(
    *,
    z3_result: SMTLIBSolverRun,
    cvc5_result: SMTLIBSolverRun,
    unsupported_theory: bool,
    disagreement: bool,
) -> list[str]:
    blockers: list[str] = []
    if unsupported_theory:
        blockers.append('unsupported SMT-LIB theory')
    if disagreement:
        blockers.append('Z3/CVC5 solver result disagreement')
    for result in (z3_result, cvc5_result):
        if result.solver_result in FAIL_CLOSED_SOLVER_RESULTS:
            reason = result.reason_unknown or result.solver_result
            blockers.append(f'{result.prover} returned {result.solver_result}: {reason}')
    return blockers


def _solver_run_dict(result: SMTLIBSolverRun) -> dict[str, Any]:
    return {
        'prover': result.prover,
        'solver_result': result.solver_result,
        'returncode': result.returncode,
        'reason_unknown': result.reason_unknown,
        'solver_version': result.solver_version,
        'stdout': result.stdout,
        'stderr': result.stderr,
    }


def _count_solver_result(claim_reports: list[Mapping[str, Any]], solver_result: str) -> int:
    return sum(
        claim['solver_results'][prover]['solver_result'] == solver_result
        for claim in claim_reports
        for prover in SELECTED_PROVERS
    )


def _artifact_cid_without_self(payload: Mapping[str, Any], self_key: str) -> str:
    return calculate_artifact_cid({key: value for key, value in payload.items() if key != self_key})


def _safe_filename(claim_id: str) -> str:
    safe = ''.join(character if character.isalnum() or character in {'-', '_'} else '_' for character in claim_id)
    return safe or 'claim'


__all__ = [
    'ASSUMPTIONS_PATH',
    'CVC5_RUNNER_REPORT_PATH',
    'FAIL_CLOSED_SOLVER_RESULTS',
    'LOCK_SCHEMA_VERSION',
    'MODEL_CID_PATH',
    'MODEL_PATH',
    'PROOF_WORKER_LOCK_PATH',
    'RUNNER_REPORT_SCHEMA_VERSION',
    'SMTLIB_DIR',
    'TASK_ID',
    'TRACE_MAP_PATH',
    'build_xaman_testnet_smt_worker_artifacts',
    'classify_testnet_smt_claim',
    'compile_pinned_testnet_smtlib_artifacts',
    'stable_sha256_model_cid',
    'summarize_testnet_smt_claims',
]
