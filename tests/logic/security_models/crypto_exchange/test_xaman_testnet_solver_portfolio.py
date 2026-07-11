"""Tests for PORTAL-CXTP-147 Xaman Testnet multi-solver portfolio."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

from ipfs_datasets_py.logic.security_models.crypto_exchange.reports.xaman_testnet_solver_portfolio import (
    APALACHE_REPORT_PATH,
    ASSUMPTIONS_PATH,
    CLAIM_TRACE_MAP_PATH,
    COQ_DECISION_PATH,
    CVC5_RUNNER_REPORT_PATH,
    DISPROOF_VECTORS_PATH,
    FUZZ_COUNTEREXAMPLE_MANIFEST_PATH,
    FUZZ_REPORT_PATH,
    LEAN_REPORT_PATH,
    MANIFEST_SCHEMA_VERSION,
    MODEL_CID_PATH,
    MODEL_PATH,
    PORTFOLIO_DOC_PATH,
    PORTFOLIO_MANIFEST_PATH,
    PORTFOLIO_REPORT_PATH,
    PROOF_WORKER_LOCK_PATH,
    PROTOCOL_REPORT_PATH,
    REPORT_SCHEMA_VERSION,
    SMT_REPORT_PATH,
    SOURCE_CLAIM_MAP_PATH,
    SOURCE_MANIFEST_PATH,
    TASK_ID,
    XRPL_TRANSACTION_COVERAGE_PATH,
    build_xaman_testnet_solver_portfolio_manifest,
    build_xaman_testnet_solver_portfolio_report,
)


REPO_ROOT = Path(__file__).resolve().parents[4]
PINNED_MODEL_CID = 'sha256:4edaad61130b6851220b6a75fa86a52b17e1baf33a8631def2879b0464366b43'


def _load_json(path: str) -> dict:
    return json.loads((REPO_ROOT / path).read_text(encoding='utf-8'))


def _build_manifest_and_report(
    *,
    smt_report: dict | None = None,
) -> tuple[dict, dict]:
    model_payload = _load_json(MODEL_PATH)
    model_cid = (REPO_ROOT / MODEL_CID_PATH).read_text(encoding='utf-8').strip()
    assumptions_payload = _load_json(ASSUMPTIONS_PATH)
    claim_trace_map = _load_json(CLAIM_TRACE_MAP_PATH)
    proof_worker_lock = _load_json(PROOF_WORKER_LOCK_PATH)
    cvc5_runner_report = _load_json(CVC5_RUNNER_REPORT_PATH)
    smt = smt_report or _load_json(SMT_REPORT_PATH)
    apalache_report = _load_json(APALACHE_REPORT_PATH)
    protocol_report = _load_json(PROTOCOL_REPORT_PATH)
    lean_report = _load_json(LEAN_REPORT_PATH)
    coq_decision = _load_json(COQ_DECISION_PATH)
    fuzz_report = _load_json(FUZZ_REPORT_PATH)
    fuzz_counterexample_manifest = _load_json(FUZZ_COUNTEREXAMPLE_MANIFEST_PATH)

    manifest = build_xaman_testnet_solver_portfolio_manifest(
        model_payload=model_payload,
        model_cid=model_cid,
        assumptions_payload=assumptions_payload,
        claim_trace_map=claim_trace_map,
        proof_worker_lock=proof_worker_lock,
        cvc5_runner_report=cvc5_runner_report,
        smt_report=smt,
        apalache_report=apalache_report,
        protocol_report=protocol_report,
        lean_report=lean_report,
        coq_decision=coq_decision,
        fuzz_report=fuzz_report,
        fuzz_counterexample_manifest=fuzz_counterexample_manifest,
        source_manifest=_load_json(SOURCE_MANIFEST_PATH),
        source_claim_map=_load_json(SOURCE_CLAIM_MAP_PATH),
        xrpl_transaction_coverage=_load_json(XRPL_TRANSACTION_COVERAGE_PATH),
        disproof_vectors=_load_json(DISPROOF_VECTORS_PATH),
        repo_root=REPO_ROOT,
    )
    report = build_xaman_testnet_solver_portfolio_report(
        manifest=manifest,
        model_payload=model_payload,
        model_cid=model_cid,
        assumptions_payload=assumptions_payload,
        smt_report=smt,
        apalache_report=apalache_report,
        protocol_report=protocol_report,
        lean_report=lean_report,
        coq_decision=coq_decision,
        fuzz_report=fuzz_report,
        fuzz_counterexample_manifest=fuzz_counterexample_manifest,
    )
    return manifest, report


def test_portfolio_artifacts_are_regenerable_and_bound_to_frozen_model() -> None:
    generated_manifest, generated_report = _build_manifest_and_report()
    manifest = _load_json(PORTFOLIO_MANIFEST_PATH)
    report = _load_json(PORTFOLIO_REPORT_PATH)

    assert generated_manifest == manifest
    assert generated_report == report
    assert manifest['schema_version'] == MANIFEST_SCHEMA_VERSION
    assert report['schema_version'] == REPORT_SCHEMA_VERSION
    assert manifest['task_id'] == TASK_ID
    assert report['task_id'] == TASK_ID
    assert manifest['model']['cid'] == PINNED_MODEL_CID
    assert report['model']['cid'] == PINNED_MODEL_CID
    assert report['manifest']['artifact_cid'] == manifest['artifact_cid']


def test_manifest_records_versions_command_digests_timeouts_and_reviewer_status() -> None:
    manifest = _load_json(PORTFOLIO_MANIFEST_PATH)

    assert [lane['lane_id'] for lane in manifest['lane_inventory']] == [
        'z3_cvc5_differential',
        'apalache_state',
        'tamarin_protocol',
        'proverif_protocol',
        'lean_kernel',
        'rocq_kernel',
        'fuzz_consumption',
    ]
    for lane in manifest['lane_inventory']:
        assert lane['command_digest'].startswith('sha256:')
        assert lane['timeout_seconds'] is not None
        assert lane['reviewer_status'] in {'human_reviewed', 'mixed_or_unreviewed', 'not_recorded'}
        assert lane['fail_closed_result_for_unavailable_or_disagreeing_lane']
        assert lane['solvers']
        assert all('version' in solver for solver in lane['solvers'])

    smt = next(lane for lane in manifest['lane_inventory'] if lane['lane_id'] == 'z3_cvc5_differential')
    assert {solver['name'] for solver in smt['solvers']} == {'z3', 'cvc5'}
    assert smt['timeout_seconds'] == 5
    assert smt['reviewer_status'] == 'human_reviewed'


def test_every_claim_has_frozen_model_cid_and_evidence_digest_set() -> None:
    manifest = _load_json(PORTFOLIO_MANIFEST_PATH)
    report = _load_json(PORTFOLIO_REPORT_PATH)

    assert len(manifest['claim_evidence']) == 12
    assert len(report['claims']) == 12
    for claim in report['claims']:
        assert claim['model_cid'] == PINNED_MODEL_CID
        assert claim['evidence_digest_set']['digest_set_cid'].startswith('baf') or claim['evidence_digest_set']['digest_set_cid'].startswith('sha256:')
        assert claim['evidence_digest_set']['evidence_ref_count'] >= 1
        assert claim['evidence_digest_set']['all_human_reviewed'] is True
        assert claim['applicable_lane_results']
        assert {lane['result'] for lane in claim['skipped_lanes']} == {'NOT_APPLICABLE'}


def test_portfolio_reconciles_current_fail_closed_lane_results() -> None:
    report = _load_json(PORTFOLIO_REPORT_PATH)

    assert report['overall_status'] == 'non_secure_with_counterevidence'
    assert report['security_decision'] == 'BLOCK_TESTNET_ASSURANCE_SOLVER_PORTFOLIO_COUNTEREVIDENCE'
    assert report['summary']['claim_count'] == 12
    assert report['summary']['proved_claim_count'] == 0
    assert report['summary']['fail_closed_claim_count'] == 12
    assert report['summary']['lane_result_counts']['COUNTEREXAMPLE'] >= 12
    assert report['summary']['lane_result_counts']['REQUIRED_MISSING_ARTIFACT'] >= 4
    assert report['summary']['lane_result_counts']['NOT_RUN'] >= 1
    assert all(claim['proof_promotion_allowed'] is False for claim in report['claims'])
    assert all(claim['fail_closed'] is True for claim in report['claims'])

    first = report['claims'][0]
    lane_by_id = {lane['lane_id']: lane for lane in first['applicable_lane_results']}
    assert lane_by_id['z3_cvc5_differential']['result'] == 'COUNTEREXAMPLE'
    assert lane_by_id['tamarin_protocol']['result'] == 'NOT_RUN'
    assert lane_by_id['proverif_protocol']['result'] == 'REQUIRED_MISSING_ARTIFACT'
    assert lane_by_id['lean_kernel']['result'] == 'ACCEPTED'
    assert lane_by_id['rocq_kernel']['result'] == 'REQUIRED_MISSING_ARTIFACT'


def test_disagreeing_smt_lane_fails_closed_not_proved() -> None:
    smt = deepcopy(_load_json(SMT_REPORT_PATH))
    first = smt['claims'][0]
    first['result'] = 'INCOMPLETE'
    first['solver_tuple'] = {'z3': 'unsat', 'cvc5': 'sat', 'agreement': False}
    first['solver_blockers'] = ['z3/cvc5 disagreement']
    first['worker_classification'] = 'solver_disagreement'
    first['worker_classification_reason'] = 'Z3 and CVC5 disagreed on the locked claim query'

    _manifest, report = _build_manifest_and_report(smt_report=smt)
    first_result = report['claims'][0]
    smt_lane = next(lane for lane in first_result['applicable_lane_results'] if lane['lane_id'] == 'z3_cvc5_differential')

    assert smt_lane['result'] == 'INCOMPLETE'
    assert smt_lane['fail_closed'] is True
    assert first_result['proof_promotion_allowed'] is False
    assert any(blocker['code'] == 'Z3_CVC5_DIFFERENTIAL_INCOMPLETE' for blocker in first_result['blockers'])


def test_documentation_records_portfolio_policy_and_current_blockers() -> None:
    doc = (REPO_ROOT / PORTFOLIO_DOC_PATH).read_text(encoding='utf-8')

    assert 'PORTAL-CXTP-147' in doc
    assert PORTFOLIO_MANIFEST_PATH in doc
    assert PORTFOLIO_REPORT_PATH in doc
    assert PINNED_MODEL_CID in doc
    assert 'Z3/CVC5' in doc or 'z3_cvc5_differential' in doc
    assert 'Tamarin/ProVerif' in doc
    assert 'Rocq/Coq' in doc
    assert 'fail-closed' in doc
    assert 'BLOCK_TESTNET_ASSURANCE_SOLVER_PORTFOLIO_COUNTEREVIDENCE' in doc
