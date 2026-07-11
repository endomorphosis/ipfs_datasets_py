"""Untrusted Leanstral assistant lock and candidate audit for Xaman Testnet."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from ..ir.cid import calculate_artifact_cid


TASK_ID = 'PORTAL-CXTP-137'
GENERATED_AT_UTC = '2026-07-11T00:00:00Z'
LOCK_SCHEMA_VERSION = 'xaman-testnet-leanstral-assistant-lock/v1'
AUDIT_SCHEMA_VERSION = 'xaman-testnet-leanstral-candidate-audit/v1'

MODEL_PATH = 'security_ir_artifacts/corpora/xaman-app/testnet/security-model-ir.json'
MODEL_CID_PATH = 'security_ir_artifacts/corpora/xaman-app/testnet/security-model-ir.cid'
ASSUMPTIONS_PATH = 'security_ir_artifacts/corpora/xaman-app/testnet/assumptions.json'
TRACE_MAP_PATH = 'security_ir_artifacts/corpora/xaman-app/testnet/claim-trace-map.json'
LEANSTRAL_ENV_REPORT_PATH = 'security_ir_artifacts/environment/leanstral-proof-assistant-report.json'
LEAN_SOLVER_LANE_REPORT_PATH = 'security_ir_artifacts/environment/lean-solver-lane-report.json'
TESTNET_LEAN_REPORT_PATH = 'security_ir_artifacts/corpora/xaman-app/testnet/proof-kernel/lean-report.json'
TESTNET_LEAN_KERNEL_PATH = 'security_ir_artifacts/corpora/xaman-app/testnet/proof-kernel/XamanTestnet.lean'
TESTNET_SMT_REPORT_PATH = 'security_ir_artifacts/corpora/xaman-app/testnet/proof-reports/z3-cvc5-differential.json'
TESTNET_SMT_WORKER_LOCK_PATH = 'security_ir_artifacts/corpora/xaman-app/testnet/proof-worker-lock.json'
TESTNET_COQ_DECISION_PATH = 'security_ir_artifacts/corpora/xaman-app/testnet/coq-coverage-decision.json'
TESTNET_PLAN_PATH = 'docs/security_verification/xaman_xrpl_testnet_theorem_prover_assurance_plan.md'
POLICY_DOC_PATH = 'docs/security_verification/xaman_testnet_leanstral_policy.md'
LOCK_PATH = 'security_ir_artifacts/corpora/xaman-app/testnet/leanstral-assistant-lock.json'
AUDIT_PATH = 'security_ir_artifacts/corpora/xaman-app/testnet/leanstral-candidate-audit.json'

APPROVED_MODEL_ROUTES = ('labs-leanstral-1-5', 'labs-leanstral-2603')
APPROVED_CHECKERS = ('Lean', 'Z3', 'CVC5', 'Apalache', 'Tamarin', 'ProVerif', 'Coq')
ALLOWED_PROPOSAL_TYPES = ('lean_proof_term', 'security_model_edit', 'counterexample_hypothesis')
FORBIDDEN_PROMOTION_EFFECTS = (
    'set_security_decision',
    'clear_assumption',
    'mark_claim_proved',
    'mark_testnet_assured',
    'change_release_gate',
)


def build_xaman_testnet_leanstral_lock(
    *,
    model_payload: Mapping[str, Any],
    model_cid: str,
    assumptions_payload: Mapping[str, Any],
    trace_map_payload: Mapping[str, Any],
    leanstral_report: Mapping[str, Any] | None,
    lean_solver_report: Mapping[str, Any] | None,
    testnet_lean_report: Mapping[str, Any],
    smt_report: Mapping[str, Any],
    coq_decision: Mapping[str, Any],
) -> dict[str, Any]:
    """Build the deterministic untrusted assistant lane lock."""

    _validate_bound_inputs(model_payload, model_cid, assumptions_payload, trace_map_payload)
    claim_ids = _claim_ids(model_payload)
    blocking_assumption_ids = _blocking_assumption_ids(assumptions_payload)
    prompt_archive = _prompt_archive(model_payload)
    checker_state = _checker_state(
        lean_solver_report=lean_solver_report,
        testnet_lean_report=testnet_lean_report,
        smt_report=smt_report,
        coq_decision=coq_decision,
    )

    lock: dict[str, Any] = {
        'schema_version': LOCK_SCHEMA_VERSION,
        'task_id': TASK_ID,
        'generated_at_utc': GENERATED_AT_UTC,
        'policy_document': POLICY_DOC_PATH,
        'assistant': {
            'id': 'xaman-testnet-leanstral-untrusted-assistant',
            'lane_class': 'untrusted-proof-assistant',
            'track': 'assistant',
            'locked': True,
            'default_mode': 'offline-prompt-archive-no-network',
            'network_calls_by_default': False,
            'approved_model_routes': list(APPROVED_MODEL_ROUTES),
            'configured_status': _nested(leanstral_report, 'configuration', 'status'),
            'general_lane_status': _nested(leanstral_report, 'overall_status'),
            'general_lane_security_decision': _nested(leanstral_report, 'security_decision'),
        },
        'model': {
            'path': MODEL_PATH,
            'cid_path': MODEL_CID_PATH,
            'id': model_payload['model_id'],
            'schema_version': model_payload['schema_version'],
            'cid': model_cid,
            'allowed_model_cids': [model_cid],
            'claim_count': len(claim_ids),
            'claim_ids': claim_ids,
        },
        'trust_boundary': {
            'leanstral_is_proof_authority': False,
            'leanstral_is_security_decision_authority': False,
            'may_propose': list(ALLOWED_PROPOSAL_TYPES),
            'forbidden_promotion_effects': list(FORBIDDEN_PROMOTION_EFFECTS),
            'no_candidate_changes_security_decision_until_independent_checker_accepts': True,
            'raw_wallet_material_allowed_in_prompts': False,
            'raw_payload_or_signature_material_allowed_in_prompts': False,
            'production_credentials_allowed_in_prompts': False,
        },
        'promotion_gate': {
            'candidate_default_state': 'untrusted_pending_independent_check',
            'required_before_any_security_decision_change': [
                'candidate is bound to the pinned Testnet model CID',
                'candidate is classified as one allowed proposal type',
                'candidate preserves redaction and prompt-material limits',
                'candidate passes an approved independent checker',
                'checker report is committed with path, command, result, and artifact CID',
                'existing blocking assumptions are unchanged unless reviewed replacement evidence clears them',
            ],
            'approved_checkers': list(APPROVED_CHECKERS),
            'proof_term_acceptance_authorities': ['Lean', 'Coq'],
            'model_edit_acceptance_authorities': ['Z3', 'CVC5', 'Apalache', 'Tamarin', 'ProVerif', 'Lean', 'Coq'],
            'counterexample_acceptance_authorities': [
                'Z3',
                'CVC5',
                'Apalache',
                'Tamarin',
                'ProVerif',
                'reviewed runtime trace',
                'registered fuzz harness',
            ],
            'single_model_output_never_sufficient': True,
            'security_decision_changes_require_independent_checker_acceptance': True,
        },
        'inputs': {
            'security_model_ir': {
                'path': MODEL_PATH,
                'cid': model_cid,
                'artifact_cid': calculate_artifact_cid(model_payload),
            },
            'assumptions': {
                'path': ASSUMPTIONS_PATH,
                'model_cid': assumptions_payload['model_cid'],
                'artifact_cid': assumptions_payload.get('artifact_cid') or calculate_artifact_cid(assumptions_payload),
                'blocking_assumption_count': len(blocking_assumption_ids),
                'blocking_assumption_ids': blocking_assumption_ids,
            },
            'claim_trace_map': {
                'path': TRACE_MAP_PATH,
                'model_cid': trace_map_payload['model_cid'],
                'artifact_cid': trace_map_payload.get('artifact_cid') or calculate_artifact_cid(trace_map_payload),
            },
            'leanstral_general_lane_report': _report_ref(
                LEANSTRAL_ENV_REPORT_PATH,
                leanstral_report,
                include_sha=True,
            ),
            'lean_solver_lane_report': _report_ref(LEAN_SOLVER_LANE_REPORT_PATH, lean_solver_report),
            'testnet_lean_kernel_report': _report_ref(TESTNET_LEAN_REPORT_PATH, testnet_lean_report),
            'testnet_smt_differential_report': _report_ref(TESTNET_SMT_REPORT_PATH, smt_report),
            'testnet_smt_worker_lock': {'path': TESTNET_SMT_WORKER_LOCK_PATH},
            'testnet_coq_coverage_decision': _report_ref(TESTNET_COQ_DECISION_PATH, coq_decision),
            'reviewed_testnet_plan': {
                'path': TESTNET_PLAN_PATH,
                'leanstral_rule': (
                    'Use Leanstral only to propose proof terms, model edits, or counterexample hypotheses. '
                    'Lean, Z3, CVC5, Apalache, Tamarin, ProVerif, or Coq remain the acceptance authorities.'
                ),
            },
        },
        'checker_state': checker_state,
        'prompt_archive': prompt_archive,
        'outputs': {
            'assistant_lock': LOCK_PATH,
            'candidate_audit': AUDIT_PATH,
            'policy_document': POLICY_DOC_PATH,
        },
        'summary': {
            'prompt_count': len(prompt_archive),
            'claim_count': len(claim_ids),
            'blocking_assumption_count': len(blocking_assumption_ids),
            'approved_checker_count': len(APPROVED_CHECKERS),
            'security_decision_authority': 'approved-independent-checker-only',
            'testnet_assurance_blocked_before_candidates': True,
        },
        'overall_status': 'configured_untrusted_advisory_lane',
        'security_decision': 'NO_SECURITY_DECISION_AUTHORITY_LEANSTRAL_UNTRUSTED_ONLY',
        'testnet_assurance_blocked': True,
        'production_release_blocked': True,
    }
    lock['lock_cid'] = calculate_artifact_cid(_without_key(lock, 'lock_cid'))
    return lock


def build_xaman_testnet_leanstral_candidate_audit(
    *,
    lock: Mapping[str, Any],
    model_payload: Mapping[str, Any],
    model_cid: str,
    testnet_lean_report: Mapping[str, Any],
    smt_report: Mapping[str, Any],
    coq_decision: Mapping[str, Any],
) -> dict[str, Any]:
    """Build an audit showing Leanstral candidates have no promotion authority."""

    if lock.get('model', {}).get('cid') != model_cid:
        raise ValueError('Leanstral lock model CID does not match the pinned Testnet model CID')
    if testnet_lean_report.get('model', {}).get('cid') != model_cid:
        raise ValueError('Lean report model CID does not match the pinned Testnet model CID')
    if smt_report.get('model', {}).get('cid') != model_cid:
        raise ValueError('SMT report model CID does not match the pinned Testnet model CID')
    if coq_decision.get('model', {}).get('cid') != model_cid:
        raise ValueError('Coq decision model CID does not match the pinned Testnet model CID')

    prompt_archive = list(lock.get('prompt_archive', []))
    intake_records = [_empty_intake_record(prompt) for prompt in prompt_archive]
    existing_security_decisions = [
        {
            'source': TESTNET_LEAN_REPORT_PATH,
            'security_decision': testnet_lean_report.get('security_decision'),
            'overall_status': testnet_lean_report.get('overall_status'),
        },
        {
            'source': TESTNET_SMT_REPORT_PATH,
            'security_decision': smt_report.get('security_decision'),
            'overall_status': smt_report.get('overall_status'),
        },
        {
            'source': TESTNET_COQ_DECISION_PATH,
            'security_decision': coq_decision.get('security_decision'),
            'overall_status': coq_decision.get('overall_status'),
        },
    ]

    audit: dict[str, Any] = {
        'schema_version': AUDIT_SCHEMA_VERSION,
        'task_id': TASK_ID,
        'generated_at_utc': GENERATED_AT_UTC,
        'policy_document': POLICY_DOC_PATH,
        'assistant_lock': {
            'path': LOCK_PATH,
            'lock_cid': lock['lock_cid'],
            'assistant_id': lock['assistant']['id'],
            'trust_boundary': 'untrusted-proof-assistant',
        },
        'model': {
            'path': MODEL_PATH,
            'cid_path': MODEL_CID_PATH,
            'id': model_payload['model_id'],
            'schema_version': model_payload['schema_version'],
            'cid': model_cid,
        },
        'candidate_intake_records': intake_records,
        'promotion_audit': {
            'candidate_count': 0,
            'submitted_candidate_count': 0,
            'independent_checker_accepted_candidate_count': 0,
            'promoted_candidate_count': 0,
            'security_decision_change_count': 0,
            'candidate_changed_security_decision': False,
            'all_candidates_remain_untrusted_until_checker_acceptance': True,
            'current_decision_change_allowed': False,
            'reason': (
                'No Leanstral candidate has been submitted with an independent Lean, SMT, Coq, '
                'or other approved-checker acceptance report.'
            ),
        },
        'checker_evidence_review': {
            'accepted_checker_reports_for_leanstral_candidates': [],
            'existing_security_decisions': existing_security_decisions,
            'lean_scope': {
                'path': TESTNET_LEAN_REPORT_PATH,
                'formalized_invariant_only': True,
                'covered_claim_ids': testnet_lean_report.get('coverage', {}).get('covered_claim_ids', []),
                'rejected_scope_claim_ids': testnet_lean_report.get('coverage', {}).get('rejected_scope_claim_ids', []),
                'security_decision': testnet_lean_report.get('security_decision'),
            },
            'smt_scope': {
                'path': TESTNET_SMT_REPORT_PATH,
                'security_decision': smt_report.get('security_decision'),
                'overall_status': smt_report.get('overall_status'),
                'solver_disagreement_blocks': True,
            },
            'coq_scope': {
                'path': TESTNET_COQ_DECISION_PATH,
                'security_decision': coq_decision.get('security_decision'),
                'overall_status': coq_decision.get('overall_status'),
                'missing_coq_declared_coverage_gap': coq_decision.get('coverage_gap', {}).get(
                    'missing_coq_declared_coverage_gap'
                ),
            },
        },
        'blockers_to_promotion': [
            {
                'code': 'NO_LEANSTRAL_CANDIDATE_SUBMITTED',
                'effect': 'nothing available for independent checker acceptance',
            },
            {
                'code': 'NO_INDEPENDENT_CHECKER_ACCEPTANCE_FOR_LEANSTRAL_CANDIDATE',
                'effect': 'no proof term, model edit, or counterexample hypothesis may change a security decision',
            },
            {
                'code': 'TESTNET_ASSURANCE_ALREADY_BLOCKED_BY_FORMAL_SCOPE',
                'effect': 'Lean scope limits, unresolved assumptions, and missing independent Coq coverage remain in force',
            },
        ],
        'overall_status': 'no_candidate_promoted',
        'security_decision': 'UNCHANGED_BY_LEANSTRAL_UNTRUSTED_LANE',
        'testnet_assurance_blocked': True,
        'production_release_blocked': True,
        'summary': {
            'prompt_count': len(prompt_archive),
            'candidate_count': 0,
            'promoted_candidate_count': 0,
            'security_decision_change_count': 0,
            'approved_checker_acceptance_count': 0,
        },
    }
    audit['audit_cid'] = calculate_artifact_cid(_without_key(audit, 'audit_cid'))
    return audit


def load_json(path: Path) -> dict[str, Any]:
    """Load a JSON object from *path*."""

    payload = path.read_text(encoding='utf-8')
    loaded = json.loads(payload)
    if not isinstance(loaded, dict):
        raise ValueError(f'{path} did not contain a JSON object')
    return loaded


def _validate_bound_inputs(
    model_payload: Mapping[str, Any],
    model_cid: str,
    assumptions_payload: Mapping[str, Any],
    trace_map_payload: Mapping[str, Any],
) -> None:
    if assumptions_payload.get('model_cid') != model_cid:
        raise ValueError('assumptions model_cid does not match the pinned Testnet model CID')
    if trace_map_payload.get('model_cid') != model_cid:
        raise ValueError('claim-trace-map model_cid does not match the pinned Testnet model CID')
    if model_payload.get('metadata', {}).get('production_release_blocked') is not True:
        raise ValueError('Leanstral Testnet lock must bind to a production-blocking Testnet model')


def _claim_ids(model_payload: Mapping[str, Any]) -> list[str]:
    return [claim['id'] for claim in model_payload.get('claims', [])]


def _blocking_assumption_ids(assumptions_payload: Mapping[str, Any]) -> list[str]:
    return [
        assumption['id']
        for assumption in assumptions_payload.get('assumptions', [])
        if assumption.get('status') == 'BLOCKING'
    ]


def _prompt_archive(model_payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    claims = list(model_payload.get('claims', []))
    modeled_claim_ids = [claim['id'] for claim in claims if claim.get('status') == 'MODELED_WITH_TESTNET_SCOPE']
    boundary_claim_ids = [
        claim['id']
        for claim in claims
        if claim.get('status') in {'MODELED_WITH_BLOCKING_NOT_MODELED_BOUNDARY', 'NOT_MODELED'}
    ]
    all_claim_ids = [claim['id'] for claim in claims]
    return [
        {
            'prompt_id': 'leanstral-testnet:lean-proof-term-review',
            'proposal_type': 'lean_proof_term',
            'target_path': TESTNET_LEAN_KERNEL_PATH,
            'claim_ids': modeled_claim_ids,
            'required_acceptance_authority': ['Lean', 'Coq'],
            'verification_command': f'lean {TESTNET_LEAN_KERNEL_PATH}',
            'redaction_policy': 'categorical-testnet-evidence-only',
            'prompt': (
                'Suggest Lean 4 proof terms for the existing XamanTestnet.lean predicates only. '
                'Do not add axiom, admit, sorry, unsafe shortcuts, or claims outside the pinned Testnet model CID. '
                'The suggestion is untrusted until Lean or Coq independently accepts it.'
            ),
        },
        {
            'prompt_id': 'leanstral-testnet:model-edit-hypothesis',
            'proposal_type': 'security_model_edit',
            'target_path': MODEL_PATH,
            'claim_ids': boundary_claim_ids,
            'required_acceptance_authority': ['Z3', 'CVC5', 'Apalache', 'Tamarin', 'ProVerif', 'Lean', 'Coq'],
            'verification_command': 'regenerate model, rerun the relevant approved checker, and compare against the pinned CID',
            'redaction_policy': 'no raw wallet, payload, signature, or production credential material',
            'prompt': (
                'Propose minimal model edits or missing semantics for Testnet NOT_MODELED boundaries. '
                'Return hypotheses only; do not mark any claim proved or clear assumptions. '
                'Every edit must be accepted by the applicable approved checker before promotion.'
            ),
        },
        {
            'prompt_id': 'leanstral-testnet:counterexample-hypothesis',
            'proposal_type': 'counterexample_hypothesis',
            'target_path': 'security_ir_artifacts/corpora/xaman-app/testnet/counterexamples/',
            'claim_ids': all_claim_ids,
            'required_acceptance_authority': [
                'Z3',
                'CVC5',
                'Apalache',
                'Tamarin',
                'ProVerif',
                'reviewed runtime trace',
                'registered fuzz harness',
            ],
            'verification_command': 'materialize as a redacted counterexample and rerun the relevant checker or fuzz harness',
            'redaction_policy': 'counterexamples must preserve categorical-only Testnet evidence',
            'prompt': (
                'Suggest counterexample hypotheses for the pinned Testnet claims. '
                'The hypothesis must not include raw payloads, signatures, account secrets, or production accounts. '
                'It is non-authoritative until reproduced by an approved checker or reviewed trace.'
            ),
        },
    ]


def _checker_state(
    *,
    lean_solver_report: Mapping[str, Any] | None,
    testnet_lean_report: Mapping[str, Any],
    smt_report: Mapping[str, Any],
    coq_decision: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        'lean_solver_lane': {
            'path': LEAN_SOLVER_LANE_REPORT_PATH,
            'overall_status': _nested(lean_solver_report, 'overall_status'),
            'security_decision': _nested(lean_solver_report, 'security_decision'),
            'proof_kernel_checked': _nested(lean_solver_report, 'summary', 'proof_kernel_checked'),
        },
        'testnet_lean_kernel': {
            'path': TESTNET_LEAN_REPORT_PATH,
            'overall_status': testnet_lean_report.get('overall_status'),
            'security_decision': testnet_lean_report.get('security_decision'),
            'formalized_invariant_only': True,
            'candidate_acceptance_for_current_audit': 'none',
        },
        'testnet_smt_differential': {
            'path': TESTNET_SMT_REPORT_PATH,
            'overall_status': smt_report.get('overall_status'),
            'security_decision': smt_report.get('security_decision'),
            'candidate_acceptance_for_current_audit': 'none',
        },
        'testnet_coq_coverage': {
            'path': TESTNET_COQ_DECISION_PATH,
            'overall_status': coq_decision.get('overall_status'),
            'security_decision': coq_decision.get('security_decision'),
            'candidate_acceptance_for_current_audit': 'none',
        },
    }


def _report_ref(path: str, payload: Mapping[str, Any] | None, *, include_sha: bool = False) -> dict[str, Any]:
    ref: dict[str, Any] = {
        'path': path,
        'present': payload is not None,
        'schema_version': payload.get('schema_version') if payload else None,
        'task_id': payload.get('task_id') if payload else None,
        'overall_status': payload.get('overall_status') if payload else None,
        'security_decision': payload.get('security_decision') if payload else None,
        'artifact_cid': (
            payload.get('artifact_cid')
            or payload.get('report_cid')
            or payload.get('lock_cid')
            or payload.get('audit_cid')
            if payload
            else None
        ),
    }
    if include_sha and payload is not None:
        encoded = json.dumps(payload, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode('utf-8')
        ref['sha256'] = 'sha256:' + hashlib.sha256(encoded).hexdigest()
    return ref


def _empty_intake_record(prompt: Mapping[str, Any]) -> dict[str, Any]:
    return {
        'prompt_id': prompt['prompt_id'],
        'proposal_type': prompt['proposal_type'],
        'target_path': prompt['target_path'],
        'submitted_candidate_present': False,
        'candidate_artifact_path': None,
        'candidate_artifact_cid': None,
        'independent_checker': None,
        'checker_report_path': None,
        'checker_acceptance_status': 'not-submitted',
        'promotion_status': 'not-promoted',
        'security_decision_changed': False,
        'required_acceptance_authority': list(prompt.get('required_acceptance_authority', [])),
    }


def _nested(payload: Mapping[str, Any] | None, *keys: str) -> Any:
    current: Any = payload
    for key in keys:
        if not isinstance(current, Mapping):
            return None
        current = current.get(key)
    return current


def _without_key(payload: Mapping[str, Any], key: str) -> dict[str, Any]:
    return {item_key: value for item_key, value in payload.items() if item_key != key}
