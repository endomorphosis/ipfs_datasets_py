"""Tests for PORTAL-CXTP-137 Xaman Testnet Leanstral assistant lane."""

from __future__ import annotations

import json
from pathlib import Path

from ipfs_datasets_py.logic.security_models.crypto_exchange.ir.cid import calculate_artifact_cid
from ipfs_datasets_py.logic.security_models.crypto_exchange.reports.xaman_testnet_leanstral import (
    ASSUMPTIONS_PATH,
    AUDIT_PATH,
    AUDIT_SCHEMA_VERSION,
    LEAN_SOLVER_LANE_REPORT_PATH,
    LEANSTRAL_ENV_REPORT_PATH,
    LOCK_PATH,
    LOCK_SCHEMA_VERSION,
    MODEL_CID_PATH,
    MODEL_PATH,
    POLICY_DOC_PATH,
    TASK_ID,
    TESTNET_COQ_DECISION_PATH,
    TESTNET_LEAN_REPORT_PATH,
    TESTNET_SMT_REPORT_PATH,
    TRACE_MAP_PATH,
    build_xaman_testnet_leanstral_candidate_audit,
    build_xaman_testnet_leanstral_lock,
)


REPO_ROOT = Path(__file__).resolve().parents[4]
PINNED_MODEL_CID = 'sha256:4edaad61130b6851220b6a75fa86a52b17e1baf33a8631def2879b0464366b43'


def _load_json(path: Path, *, required: bool = True) -> dict | None:
    if not path.is_file():
        if required:
            raise FileNotFoundError(path)
        return None
    return json.loads(path.read_text(encoding='utf-8'))


def _cid_without(payload: dict, key: str) -> str:
    return calculate_artifact_cid({item_key: item for item_key, item in payload.items() if item_key != key})


def _inputs() -> tuple[dict, str, dict, dict, dict | None, dict | None, dict, dict, dict]:
    return (
        _load_json(REPO_ROOT / MODEL_PATH),
        (REPO_ROOT / MODEL_CID_PATH).read_text(encoding='utf-8').strip(),
        _load_json(REPO_ROOT / ASSUMPTIONS_PATH),
        _load_json(REPO_ROOT / TRACE_MAP_PATH),
        _load_json(REPO_ROOT / LEANSTRAL_ENV_REPORT_PATH, required=False),
        _load_json(REPO_ROOT / LEAN_SOLVER_LANE_REPORT_PATH, required=False),
        _load_json(REPO_ROOT / TESTNET_LEAN_REPORT_PATH),
        _load_json(REPO_ROOT / TESTNET_SMT_REPORT_PATH),
        _load_json(REPO_ROOT / TESTNET_COQ_DECISION_PATH),
    )


def test_lock_and_audit_are_regenerable() -> None:
    (
        model,
        model_cid,
        assumptions,
        trace_map,
        leanstral_report,
        lean_solver_report,
        testnet_lean_report,
        smt_report,
        coq_decision,
    ) = _inputs()
    lock = build_xaman_testnet_leanstral_lock(
        model_payload=model,
        model_cid=model_cid,
        assumptions_payload=assumptions,
        trace_map_payload=trace_map,
        leanstral_report=leanstral_report,
        lean_solver_report=lean_solver_report,
        testnet_lean_report=testnet_lean_report,
        smt_report=smt_report,
        coq_decision=coq_decision,
    )
    audit = build_xaman_testnet_leanstral_candidate_audit(
        lock=lock,
        model_payload=model,
        model_cid=model_cid,
        testnet_lean_report=testnet_lean_report,
        smt_report=smt_report,
        coq_decision=coq_decision,
    )

    assert lock == _load_json(REPO_ROOT / LOCK_PATH)
    assert audit == _load_json(REPO_ROOT / AUDIT_PATH)


def test_assistant_lock_is_untrusted_and_bound_to_pinned_model() -> None:
    lock = _load_json(REPO_ROOT / LOCK_PATH)

    assert lock['schema_version'] == LOCK_SCHEMA_VERSION
    assert lock['task_id'] == TASK_ID
    assert lock['model']['cid'] == PINNED_MODEL_CID
    assert lock['model']['allowed_model_cids'] == [PINNED_MODEL_CID]
    assert lock['assistant']['lane_class'] == 'untrusted-proof-assistant'
    assert lock['assistant']['network_calls_by_default'] is False
    assert lock['trust_boundary']['leanstral_is_proof_authority'] is False
    assert lock['trust_boundary']['leanstral_is_security_decision_authority'] is False
    assert lock['trust_boundary']['no_candidate_changes_security_decision_until_independent_checker_accepts'] is True
    assert set(lock['trust_boundary']['may_propose']) == {
        'lean_proof_term',
        'security_model_edit',
        'counterexample_hypothesis',
    }
    assert lock['promotion_gate']['security_decision_changes_require_independent_checker_acceptance'] is True
    assert lock['promotion_gate']['single_model_output_never_sufficient'] is True
    assert lock['lock_cid'] == _cid_without(lock, 'lock_cid')


def test_prompt_archive_preserves_redaction_and_checker_requirements() -> None:
    lock = _load_json(REPO_ROOT / LOCK_PATH)
    prompts = lock['prompt_archive']

    assert {prompt['proposal_type'] for prompt in prompts} == {
        'lean_proof_term',
        'security_model_edit',
        'counterexample_hypothesis',
    }
    assert len(prompts) == 3
    for prompt in prompts:
        assert prompt['claim_ids']
        assert prompt['required_acceptance_authority']
        assert 'raw' not in prompt['redaction_policy'] or 'no raw' in prompt['redaction_policy']
        assert 'security_ir_artifacts/corpora/xaman-app/testnet' in prompt['target_path']


def test_candidate_audit_promotes_nothing_and_changes_no_decision() -> None:
    audit = _load_json(REPO_ROOT / AUDIT_PATH)

    assert audit['schema_version'] == AUDIT_SCHEMA_VERSION
    assert audit['task_id'] == TASK_ID
    assert audit['model']['cid'] == PINNED_MODEL_CID
    assert audit['overall_status'] == 'no_candidate_promoted'
    assert audit['security_decision'] == 'UNCHANGED_BY_LEANSTRAL_UNTRUSTED_LANE'
    assert audit['promotion_audit']['candidate_changed_security_decision'] is False
    assert audit['promotion_audit']['current_decision_change_allowed'] is False
    assert audit['promotion_audit']['promoted_candidate_count'] == 0
    assert audit['promotion_audit']['independent_checker_accepted_candidate_count'] == 0
    assert audit['summary']['security_decision_change_count'] == 0
    assert audit['checker_evidence_review']['accepted_checker_reports_for_leanstral_candidates'] == []
    assert audit['audit_cid'] == _cid_without(audit, 'audit_cid')

    for record in audit['candidate_intake_records']:
        assert record['submitted_candidate_present'] is False
        assert record['checker_acceptance_status'] == 'not-submitted'
        assert record['promotion_status'] == 'not-promoted'
        assert record['security_decision_changed'] is False


def test_policy_document_states_untrusted_boundary_and_validation() -> None:
    doc = (REPO_ROOT / POLICY_DOC_PATH).read_text(encoding='utf-8')

    assert 'PORTAL-CXTP-137' in doc
    assert LOCK_PATH in doc
    assert AUDIT_PATH in doc
    assert PINNED_MODEL_CID in doc
    assert 'never a proof authority' in doc
    assert 'No candidate may set `PROVED`' in doc
    assert 'UNCHANGED_BY_LEANSTRAL_UNTRUSTED_LANE' in doc
