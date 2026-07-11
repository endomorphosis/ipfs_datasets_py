from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from scripts.ops.security_verification.build_xaman_xrpl_transaction_coverage import (
    build_xrpl_transaction_coverage,
)


ROOT = Path(__file__).resolve().parents[4]
COVERAGE_PATH = ROOT / 'security_ir_artifacts/corpora/xaman-app/xrpl-transaction-coverage.json'
FACTS_PATH = ROOT / 'security_ir_artifacts/corpora/xaman-app/xrpl-transaction-facts.json'
DISPROOF_PATH = ROOT / 'security_ir_artifacts/corpora/xaman-app/disproof-vectors.json'
COUNTEREXAMPLE_PATH = ROOT / 'security_ir_artifacts/corpora/xaman-app/counterexample-report.json'
DOC_PATH = ROOT / 'docs/security_verification/xaman_xrpl_transaction_model.md'

REQUIRED_CONSTRAINTS = {
    'TrustSet',
    'OfferCreate',
    'SignerListSet',
    'payment',
    'issued_currency',
    'destination_tag',
    'fee',
    'sequence',
    'multisign',
    'memo',
    'network',
    'canonicalization',
}


def _json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding='utf-8'))


def _canonical_sha256(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(',', ':')).encode('utf-8')
    return 'sha256:' + hashlib.sha256(encoded).hexdigest()


def _assert_artifact_cid(payload: dict[str, Any]) -> None:
    body = dict(payload)
    artifact_cid = body.pop('artifact_cid')
    assert artifact_cid == _canonical_sha256(body)


def test_xaman_xrpl_transaction_coverage_rebuilds_deterministically() -> None:
    checked_in = _json(COVERAGE_PATH)
    rebuilt = build_xrpl_transaction_coverage(ROOT)

    assert rebuilt == checked_in
    _assert_artifact_cid(checked_in)


def test_xaman_xrpl_transaction_coverage_schema_source_and_summary() -> None:
    coverage = _json(COVERAGE_PATH)
    facts = _json(FACTS_PATH)

    assert coverage['schema_version'] == 'xaman-xrpl-transaction-coverage/v1'
    assert coverage['task_id'] == 'PORTAL-CXTP-146'
    assert coverage['corpus'] == 'xaman-app'
    assert coverage['source']['repo_url'] == facts['source']['repo_url']
    assert coverage['source']['commit_sha'] == facts['source']['commit_sha']
    assert coverage['source']['facts_path'] == 'security_ir_artifacts/corpora/xaman-app/xrpl-transaction-facts.json'
    assert coverage['review']['depends_on'] == ['PORTAL-CXTP-143', 'PORTAL-CXTP-144']
    assert coverage['overall_status'] == 'blocked'
    assert coverage['production_release_blocked'] is True
    assert coverage['summary']['required_constraint_count'] == len(REQUIRED_CONSTRAINTS)
    assert coverage['summary']['production_release_approval_count'] == 0
    assert coverage['summary']['proof_eligible_unsupported_type_count'] == 0


def test_xaman_xrpl_transaction_coverage_covers_all_required_constraints() -> None:
    coverage = _json(COVERAGE_PATH)
    by_constraint = {entry['constraint']: entry for entry in coverage['constraint_coverage']}

    assert set(coverage['required_constraint_status']) == REQUIRED_CONSTRAINTS
    assert set(by_constraint) == REQUIRED_CONSTRAINTS
    assert all(entry['reachable_public_flow'] is True for entry in by_constraint.values())
    assert all(entry['evidence'] for entry in by_constraint.values())

    assert by_constraint['payment']['status'] == 'MODELED_WITH_BLOCKING_RUNTIME_ASSUMPTIONS'
    assert by_constraint['memo']['status'] == 'MODELED'
    assert by_constraint['fee']['status'] == 'MODELED_WITH_BLOCKING_RUNTIME_ASSUMPTIONS'
    assert by_constraint['sequence']['status'] == 'MODELED_WITH_BLOCKING_RUNTIME_ASSUMPTIONS'
    assert by_constraint['network']['status'] == 'MODELED_WITH_BLOCKING_RUNTIME_ASSUMPTIONS'
    assert by_constraint['destination_tag']['status'] == 'MODELED_FIELD_PRESERVATION'
    assert by_constraint['issued_currency']['status'] == 'PARTIALLY_MODELED_AND_PARTIALLY_REJECTED'
    assert by_constraint['canonicalization']['status'] == 'EXPLICITLY_REJECTED_FOR_FULL_XRPL_BINARY_PROOF'


def test_xaman_xrpl_transaction_coverage_rejects_todo_validation_flows() -> None:
    coverage = _json(COVERAGE_PATH)
    by_constraint = {entry['constraint']: entry for entry in coverage['constraint_coverage']}

    for constraint in ['TrustSet', 'OfferCreate', 'SignerListSet', 'multisign']:
        entry = by_constraint[constraint]
        assert entry['status'] == 'EXPLICITLY_REJECTED_FOR_PROOF'
        assert entry['proof_effect'] == 'counterexample_required_if_treated_as_proved'
        assert 'xaman-disproof:unsupported-xrpl-semantics' in entry['counterexample_vector_ids']
        assert 'xaman-xrpl-transaction:gap:trustset-offercreate-signerlistset-validation-is-todo' in entry['coverage_gap_ids']
        assert entry['explicitly_rejected_conditions']


def test_xaman_xrpl_transaction_coverage_unsupported_types_never_prove() -> None:
    coverage = _json(COVERAGE_PATH)
    policy = coverage['unsupported_transaction_policy']
    decisions = {entry['flow_id']: entry for entry in coverage['reachable_public_flow_decisions']}

    assert policy['decision'] == 'RECORD_GAP_OR_COUNTEREXAMPLE_NEVER_PROOF'
    assert policy['fallback_transaction_proof_eligible'] is False
    assert policy['unsupported_network_transaction_type_proof_eligible'] is False
    assert {
        item['required_result'] for item in policy['unsupported_type_handling']
    } >= {
        'counterexample_found',
        'coverage_gap',
        'client_rejects_before_signing',
    }

    unsupported = decisions['xaman-xrpl-flow:unsupported-or-unreviewed-type']
    assert unsupported['decision'] == 'COVERAGE_GAP_NEVER_PROOF'
    assert unsupported['proof_eligible'] is False
    assert all(decision['proof_eligible'] is False for decision in decisions.values())


def test_xaman_xrpl_disproof_vectors_bind_transaction_coverage() -> None:
    vectors = _json(DISPROOF_PATH)
    report = _json(COUNTEREXAMPLE_PATH)
    coverage = _json(COVERAGE_PATH)
    vector_by_id = {entry['id']: entry for entry in vectors['vectors']}
    report_by_id = {entry['vector_id']: entry for entry in report['results']}

    assert vectors['xrpl_transaction_coverage']['artifact_cid'] == coverage['artifact_cid']
    unsupported = vector_by_id['xaman-disproof:unsupported-xrpl-semantics']
    assert 'security_ir_artifacts/corpora/xaman-app/xrpl-transaction-coverage.json' in unsupported['evidence']
    assert unsupported['xrpl_transaction_coverage']['transaction_classes'] == [
        'TrustSet',
        'OfferCreate',
        'SignerListSet',
    ]
    assert report_by_id['xaman-disproof:unsupported-xrpl-semantics']['result'] == 'counterexample_found'
    assert report_by_id['xaman-disproof:unsupported-xrpl-semantics']['release_policy'] == 'block'


def test_xaman_xrpl_transaction_model_document_mentions_portal_146_coverage() -> None:
    doc = DOC_PATH.read_text(encoding='utf-8')

    assert 'PORTAL-CXTP-146' in doc
    assert 'security_ir_artifacts/corpora/xaman-app/xrpl-transaction-coverage.json' in doc
    assert 'RECORD_GAP_OR_COUNTEREXAMPLE_NEVER_PROOF' in doc
    for term in REQUIRED_CONSTRAINTS:
        assert term in doc
