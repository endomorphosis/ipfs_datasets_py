from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[4]
CORPUS_DIR = ROOT / 'security_ir_artifacts/corpora/xaman-app'
CLAIMS_PATH = CORPUS_DIR / 'security-claims.json'
MODEL_CID_PATH = CORPUS_DIR / 'security-model-ir.cid'
MANIFEST_PATH = CORPUS_DIR / 'smtlib/manifest.json'
REPORT_PATH = CORPUS_DIR / 'proof-reports/z3-cvc5-differential.json'


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding='utf-8'))


def test_xaman_smt_manifest_covers_every_blocking_or_high_claim() -> None:
    claims = _json(CLAIMS_PATH)['claims']
    manifest = _json(MANIFEST_PATH)
    expected_claim_ids = {
        claim['id']
        for claim in claims
        if claim['severity'] in {'blocking', 'high'}
    }

    assert manifest['task_id'] == 'PORTAL-CXTP-069'
    assert manifest['schema_version'] == 'xaman-smtlib-manifest/v1'
    assert manifest['model_cid'] == MODEL_CID_PATH.read_text(encoding='utf-8').strip()
    assert manifest['claim_count'] == len(expected_claim_ids)
    assert manifest['blocking_or_high_claim_count'] == len(expected_claim_ids)
    assert {entry['claim_id'] for entry in manifest['artifacts']} == expected_claim_ids


def test_xaman_smt_artifacts_are_parseable_fail_closed_queries() -> None:
    manifest = _json(MANIFEST_PATH)

    for entry in manifest['artifacts']:
        artifact_path = MANIFEST_PATH.parent / entry['path']
        body = artifact_path.read_text(encoding='utf-8')

        assert artifact_path.is_file()
        assert entry['modeled'] is True
        assert entry['logic'] == 'QF_LIA'
        assert entry['query_kind'] == 'blocking_assumption_satisfiability'
        assert entry['assumption_count'] >= 1
        assert entry['claim_id'] in body
        assert manifest['model_cid'] in body
        assert '(set-logic QF_LIA)' in body
        assert '(check-sat)' in body
        assert '(assert (>= blocking_assumption_count 1))' in body


def test_xaman_z3_cvc5_differential_report_blocks_unresolved_assumptions() -> None:
    manifest = _json(MANIFEST_PATH)
    report = _json(REPORT_PATH)
    manifest_claims = {entry['claim_id'] for entry in manifest['artifacts']}

    assert report['task_id'] == 'PORTAL-CXTP-069'
    assert report['schema_version'] == 'xaman-z3-cvc5-differential-report/v1'
    assert report['model_cid'] == manifest['model_cid']
    assert report['claim_count'] == manifest['claim_count']
    assert report['covered_claim_count'] == manifest['claim_count']
    assert report['agreement_failure_count'] == 0
    assert report['unsupported_or_error_count'] == 0
    assert report['blocked_claim_count'] == manifest['claim_count']
    assert report['overall_status'] == 'blocked'
    assert report['security_decision'] == 'BLOCK_XAMAN_RELEASE_UNRESOLVED_ASSUMPTIONS'
    assert report['production_release_blocked'] is True

    report_claims = {claim['claim_id'] for claim in report['claims']}
    assert report_claims == manifest_claims
    assert all(claim['solver_agreement'] is True for claim in report['claims'])
    assert all(claim['classification'] == 'blocked_assumption' for claim in report['claims'])
    assert all(claim['release_policy'] == 'block' for claim in report['claims'])
    assert all(claim['production_release_blocked'] is True for claim in report['claims'])
    assert all(claim['z3']['result'] == claim['cvc5']['result'] for claim in report['claims'])
    assert {claim['z3']['result'] for claim in report['claims']} <= {'sat', 'unsat', 'unknown'}
