"""Tests for PORTAL-CXTP-133 frozen Xaman Testnet SMT claim-set results."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

from ipfs_datasets_py.logic.security_models.crypto_exchange.reports.xaman_testnet_smt_results import (
    ASSUMPTIONS_PATH,
    COUNTEREXAMPLE_DIR,
    COUNTEREXAMPLE_MANIFEST_PATH,
    PROOF_REPORT_PATH,
    SCHEMA_VERSION,
    TASK_ID,
    build_xaman_testnet_smt_results,
    counterexample_artifacts,
)
from ipfs_datasets_py.logic.security_models.crypto_exchange.reports.xaman_testnet_smt_worker import (
    CVC5_RUNNER_REPORT_PATH,
    MODEL_CID_PATH,
    MODEL_PATH,
    PROOF_WORKER_LOCK_PATH,
)


REPO_ROOT = Path(__file__).resolve().parents[4]
REPORT_PATH = REPO_ROOT / PROOF_REPORT_PATH
COUNTEREXAMPLES_PATH = REPO_ROOT / COUNTEREXAMPLE_DIR
DOC_PATH = REPO_ROOT / 'docs' / 'security_verification' / 'xaman_testnet_smt_results.md'
PINNED_MODEL_CID = 'sha256:4edaad61130b6851220b6a75fa86a52b17e1baf33a8631def2879b0464366b43'


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding='utf-8'))


def _build_report(cvc5_runner_report: dict | None = None) -> dict:
    model = _load_json(REPO_ROOT / MODEL_PATH)
    model_cid = (REPO_ROOT / MODEL_CID_PATH).read_text(encoding='utf-8').strip()
    assumptions = _load_json(REPO_ROOT / ASSUMPTIONS_PATH)
    worker_lock = _load_json(REPO_ROOT / PROOF_WORKER_LOCK_PATH)
    runner = cvc5_runner_report or _load_json(REPO_ROOT / CVC5_RUNNER_REPORT_PATH)
    return build_xaman_testnet_smt_results(
        model,
        model_cid=model_cid,
        assumptions_payload=assumptions,
        proof_worker_lock=worker_lock,
        cvc5_runner_report=runner,
    )


def test_smt_results_report_is_regenerable_and_bound_to_frozen_model() -> None:
    generated = _build_report()
    report = _load_json(REPORT_PATH)

    assert generated == report
    assert report['schema_version'] == SCHEMA_VERSION
    assert report['task_id'] == TASK_ID
    assert report['model']['cid'] == PINNED_MODEL_CID
    assert report['inputs']['cvc5_runner_report']['path'] == CVC5_RUNNER_REPORT_PATH
    assert report['proof_policy']['required_smt_lanes'] == ['z3', 'cvc5']
    assert 'PROVED only' in report['proof_policy']['proved_rule']


def test_no_current_testnet_claim_is_marked_proved() -> None:
    report = _load_json(REPORT_PATH)

    assert report['overall_status'] == 'non_secure_with_counterexamples'
    assert report['security_decision'] == 'BLOCK_TESTNET_ASSURANCE_COUNTEREXAMPLES'
    assert report['summary']['claim_count'] == 12
    assert report['summary']['proved_count'] == 0
    assert report['summary']['counterexample_count'] == 12
    assert report['summary']['incomplete_count'] == 0
    assert report['testnet_assurance_blocked'] is True
    assert all(claim['result'] == 'COUNTEREXAMPLE' for claim in report['claims'])
    assert all(claim['security_result'] == 'NON_SECURE_TESTNET_RESULT' for claim in report['claims'])
    assert all(claim['proof_promotion_allowed'] is False for claim in report['claims'])
    assert all(claim['solver_tuple'] == {'z3': 'sat', 'cvc5': 'sat', 'agreement': True} for claim in report['claims'])
    assert all(claim['owner_actions'] for claim in report['claims'])
    assert all(claim['counterexample_path'] for claim in report['claims'])


def test_counterexample_directory_matches_report_and_contains_owner_actions() -> None:
    report = _load_json(REPORT_PATH)
    generated = counterexample_artifacts(report)

    assert COUNTEREXAMPLES_PATH.is_dir()
    assert set(generated) == {
        *(claim['counterexample_path'] for claim in report['claims']),
        COUNTEREXAMPLE_MANIFEST_PATH,
    }
    for rel_path, expected in generated.items():
        assert _load_json(REPO_ROOT / rel_path) == expected

    manifest = _load_json(REPO_ROOT / COUNTEREXAMPLE_MANIFEST_PATH)
    assert manifest['schema_version'] == 'xaman-testnet-smt-counterexample-manifest/v1'
    assert manifest['counterexample_count'] == 12
    assert set(manifest['counterexamples']) == {claim['counterexample_path'] for claim in report['claims']}

    first_witness = _load_json(REPO_ROOT / report['claims'][0]['counterexample_path'])
    assert first_witness['schema_version'] == 'xaman-testnet-smt-counterexample/v1'
    assert first_witness['acceptance_decision'] == 'REJECT_PROOF_PROMOTION'
    assert first_witness['raw_sensitive_material_recorded'] is False
    assert first_witness['owner_actions']
    assert all(action['owner'] and action['required_evidence_to_clear'] for action in first_witness['owner_actions'])


def test_proved_requires_both_smt_lanes_unsat_and_no_blocking_assumptions() -> None:
    runner = deepcopy(_load_json(REPO_ROOT / CVC5_RUNNER_REPORT_PATH))
    first_claim = runner['claims'][0]
    first_claim['classification'] = 'proved_candidate'
    first_claim['classification_reason'] = 'both solvers found no satisfiable blocking acceptance condition'
    first_claim['blocked_by_assumptions'] = []
    first_claim['solver_results']['z3']['solver_result'] = 'unsat'
    first_claim['solver_results']['cvc5']['solver_result'] = 'unsat'

    report = _build_report(runner)
    proved = report['claims'][0]
    remaining = report['claims'][1:]

    assert proved['result'] == 'PROVED'
    assert proved['proof_promotion_allowed'] is True
    assert proved['counterexample_path'] is None
    assert report['summary']['proved_count'] == 1
    assert all(claim['result'] == 'COUNTEREXAMPLE' for claim in remaining)


def test_unknown_or_disagreement_remains_incomplete_not_proved() -> None:
    runner = deepcopy(_load_json(REPO_ROOT / CVC5_RUNNER_REPORT_PATH))
    first_claim = runner['claims'][0]
    first_claim['classification'] = 'solver_blocked'
    first_claim['solver_results']['cvc5']['solver_result'] = 'unknown'
    first_claim['solver_tuple'] = None
    first_claim['solver_agreement'] = False
    first_claim['solver_blockers'] = ['cvc5 returned unknown: incomplete']

    report = _build_report(runner)
    incomplete = report['claims'][0]

    assert incomplete['result'] == 'INCOMPLETE'
    assert incomplete['security_result'] == 'NON_SECURE_TESTNET_RESULT'
    assert incomplete['proof_promotion_allowed'] is False
    assert incomplete['owner_actions']
    assert report['summary']['incomplete_count'] == 1
    assert report['security_decision'] == 'BLOCK_TESTNET_ASSURANCE_INCOMPLETE_SMT_CLAIMS'


def test_documentation_records_non_secure_result_and_validation_paths() -> None:
    doc = DOC_PATH.read_text(encoding='utf-8')

    assert 'PORTAL-CXTP-133' in doc
    assert PROOF_REPORT_PATH in doc
    assert COUNTEREXAMPLE_DIR in doc
    assert PINNED_MODEL_CID in doc
    assert '`PROVED` is reserved' in doc
    assert 'BLOCK_TESTNET_ASSURANCE_COUNTEREXAMPLES' in doc
