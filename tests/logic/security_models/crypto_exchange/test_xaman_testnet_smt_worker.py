"""Tests for PORTAL-CXTP-132 Xaman Testnet SMT worker lock."""

from __future__ import annotations

import json
from pathlib import Path

from ipfs_datasets_py.logic.security_models.crypto_exchange.ir.cid import calculate_artifact_cid
from ipfs_datasets_py.logic.security_models.crypto_exchange.ir.schema import SecurityModelIR, validate_ir
from ipfs_datasets_py.logic.security_models.crypto_exchange.reports.xaman_testnet_smt_worker import (
    ASSUMPTIONS_PATH,
    CVC5_RUNNER_REPORT_PATH,
    FAIL_CLOSED_SOLVER_RESULTS,
    LOCK_SCHEMA_VERSION,
    MODEL_CID_PATH,
    MODEL_PATH,
    PROOF_WORKER_LOCK_PATH,
    RUNNER_REPORT_SCHEMA_VERSION,
    SMTLIB_DIR,
    TASK_ID,
    TRACE_MAP_PATH,
    build_xaman_testnet_smt_worker_artifacts,
    classify_testnet_smt_claim,
    compile_pinned_testnet_smtlib_artifacts,
    stable_sha256_model_cid,
)
from ipfs_datasets_py.logic.security_models.crypto_exchange.runners.cvc5_runner import SMTLIBSolverRun


REPO_ROOT = Path(__file__).resolve().parents[4]
LOCK_PATH = REPO_ROOT / PROOF_WORKER_LOCK_PATH
REPORT_PATH = REPO_ROOT / CVC5_RUNNER_REPORT_PATH
DOC_PATH = REPO_ROOT / 'docs' / 'security_verification' / 'xaman_testnet_smt_worker.md'
PINNED_MODEL_CID = 'sha256:4edaad61130b6851220b6a75fa86a52b17e1baf33a8631def2879b0464366b43'


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding='utf-8'))


def _cid_without(payload: dict, key: str) -> str:
    return calculate_artifact_cid({item_key: item for item_key, item in payload.items() if item_key != key})


def test_worker_lock_and_runner_report_are_regenerable() -> None:
    model = _load_json(REPO_ROOT / MODEL_PATH)
    model_cid = (REPO_ROOT / MODEL_CID_PATH).read_text(encoding='utf-8').strip()
    trace_map = _load_json(REPO_ROOT / TRACE_MAP_PATH)
    assumptions = _load_json(REPO_ROOT / ASSUMPTIONS_PATH)

    generated = build_xaman_testnet_smt_worker_artifacts(
        model,
        model_cid=model_cid,
        trace_map_payload=trace_map,
        assumptions_payload=assumptions,
    )

    assert generated['proof_worker_lock'] == _load_json(LOCK_PATH)
    assert generated['cvc5_runner_report'] == _load_json(REPORT_PATH)
    assert stable_sha256_model_cid(model) == PINNED_MODEL_CID == model_cid


def test_proof_worker_lock_pins_one_model_cid_and_fail_closed_policy() -> None:
    lock = _load_json(LOCK_PATH)
    model = _load_json(REPO_ROOT / MODEL_PATH)
    blocking_or_high_claims = [
        claim
        for claim in model['claims']
        if claim['severity'] in {'blocking', 'high'}
    ]

    assert lock['schema_version'] == LOCK_SCHEMA_VERSION
    assert lock['task_id'] == TASK_ID
    assert lock['worker']['locked'] is True
    assert lock['model']['cid'] == PINNED_MODEL_CID
    assert lock['model']['allowed_model_cids'] == [PINNED_MODEL_CID]
    assert lock['claim_scope']['claim_count'] == len(blocking_or_high_claims) == 12
    assert lock['claim_scope']['claim_ids'] == [claim['id'] for claim in blocking_or_high_claims]
    assert lock['smt_contract']['logic'] == 'QF_LIA'
    assert lock['smt_contract']['selected_provers'] == ['z3', 'cvc5']
    assert set(lock['smt_contract']['fail_closed_solver_results']) == FAIL_CLOSED_SOLVER_RESULTS
    assert lock['smt_contract']['unknown_timeout_unsupported_blocks_testnet_assurance'] is True
    assert lock['smt_contract']['z3_cvc5_disagreement_blocks_testnet_assurance'] is True
    assert lock['lock_cid'] == _cid_without(lock, 'lock_cid')


def test_cvc5_runner_report_records_differential_execution_and_current_blocker() -> None:
    report = _load_json(REPORT_PATH)
    lock = _load_json(LOCK_PATH)

    assert report['schema_version'] == RUNNER_REPORT_SCHEMA_VERSION
    assert report['task_id'] == TASK_ID
    assert report['model']['cid'] == PINNED_MODEL_CID
    assert report['proof_worker_lock']['lock_cid'] == lock['lock_cid']
    assert report['selected_provers'] == ['z3', 'cvc5']
    assert report['summary']['claim_count'] == lock['claim_scope']['claim_count'] == 12
    assert report['summary']['covered_claim_count'] == 12
    assert report['summary']['solver_blocker_count'] == 0
    assert report['summary']['unsupported_theory_count'] == 0
    assert report['summary']['timeout_count'] == 0
    assert report['summary']['unknown_count'] == 0
    assert report['summary']['disagreement_count'] == 0
    assert report['overall_status'] == 'blocked_by_unresolved_assumptions'
    assert report['security_decision'] == 'BLOCK_TESTNET_ASSURANCE_UNRESOLVED_ASSUMPTIONS'
    assert report['production_release_blocked'] is True
    assert report['report_cid'] == _cid_without(report, 'report_cid')

    for claim in report['claims']:
        assert claim['classification'] == 'blocked_assumption'
        assert claim['release_policy'] == 'block'
        assert claim['solver_agreement'] is True
        assert claim['solver_blockers'] == []
        assert claim['unsupported_theory'] is False
        assert claim['solver_results']['z3']['solver_result'] == 'sat'
        assert claim['solver_results']['cvc5']['solver_result'] == 'sat'
        assert claim['blocked_by_assumptions']


def test_smtlib_manifest_and_artifacts_are_bound_to_the_pinned_model_cid() -> None:
    model_payload = _load_json(REPO_ROOT / MODEL_PATH)
    model = validate_ir(SecurityModelIR.from_untrusted_dict(model_payload, strict=True))
    generated_artifacts = {
        artifact.claim_id: artifact
        for artifact in compile_pinned_testnet_smtlib_artifacts(model, model_cid=PINNED_MODEL_CID)
    }
    manifest = _load_json(REPO_ROOT / SMTLIB_DIR / 'manifest.json')

    assert manifest['schema_version'] == 'xaman-testnet-smtlib-manifest/v1'
    assert manifest['task_id'] == TASK_ID
    assert manifest['model_cid'] == PINNED_MODEL_CID
    assert manifest['claim_count'] == 12
    assert set(generated_artifacts) == {entry['claim_id'] for entry in manifest['artifacts']}

    for entry in manifest['artifacts']:
        path = REPO_ROOT / SMTLIB_DIR / entry['path']
        artifact = generated_artifacts[entry['claim_id']]
        body = path.read_text(encoding='utf-8')
        assert path.is_file()
        assert entry['artifact_cid'] == artifact.artifact_cid
        assert entry['blocking_assumption_count'] >= 1
        assert PINNED_MODEL_CID in body
        assert '(set-logic QF_LIA)' in body
        assert '(check-sat)' in body


def test_classifier_keeps_unknown_timeout_unsupported_and_disagreement_blocking() -> None:
    model = validate_ir(SecurityModelIR.from_untrusted_dict(_load_json(REPO_ROOT / MODEL_PATH), strict=True))
    artifact = compile_pinned_testnet_smtlib_artifacts(model, model_cid=PINNED_MODEL_CID)[0]
    z3_sat = SMTLIBSolverRun(prover='z3', solver_result='sat')

    unknown = classify_testnet_smt_claim(
        artifact,
        z3_result=z3_sat,
        cvc5_result=SMTLIBSolverRun(prover='cvc5', solver_result='unknown', reason_unknown='incomplete'),
        unsupported_theory=False,
    )
    timeout = classify_testnet_smt_claim(
        artifact,
        z3_result=z3_sat,
        cvc5_result=SMTLIBSolverRun(prover='cvc5', solver_result='timeout', reason_unknown='timeout'),
        unsupported_theory=False,
    )
    unsupported = classify_testnet_smt_claim(
        artifact,
        z3_result=SMTLIBSolverRun(prover='z3', solver_result='unsupported'),
        cvc5_result=SMTLIBSolverRun(prover='cvc5', solver_result='unsupported'),
        unsupported_theory=True,
    )
    disagreement = classify_testnet_smt_claim(
        artifact,
        z3_result=z3_sat,
        cvc5_result=SMTLIBSolverRun(prover='cvc5', solver_result='unsat'),
        unsupported_theory=False,
    )

    for claim in (unknown, timeout, unsupported, disagreement):
        assert claim['classification'] == 'solver_blocked'
        assert claim['release_policy'] == 'block'
        assert claim['testnet_assurance_blocked'] is True
        assert claim['solver_blockers']


def test_documentation_describes_lock_and_differential_blockers() -> None:
    doc = DOC_PATH.read_text(encoding='utf-8')

    assert 'PORTAL-CXTP-132' in doc
    assert PROOF_WORKER_LOCK_PATH in doc
    assert CVC5_RUNNER_REPORT_PATH in doc
    assert PINNED_MODEL_CID in doc
    assert 'UNKNOWN' in doc
    assert 'timeout' in doc
    assert 'unsupported theory' in doc
    assert 'Z3/CVC5 disagreement' in doc
