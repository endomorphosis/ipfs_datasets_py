"""Tests for PORTAL-CXTP-151 public-source/Testnet assurance verdict."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.security_models.crypto_exchange.ir.cid import calculate_artifact_cid
from ipfs_datasets_py.logic.security_models.crypto_exchange.reports.xaman_public_source_testnet_assurance_verdict import (
    ALLOWED_VERDICTS,
    BUNDLE_SCHEMA_VERSION,
    FUZZ_CAMPAIGN_MANIFEST_PATH,
    FUZZ_COUNTEREXAMPLE_MANIFEST_PATH,
    FUZZ_REPORT_PATH,
    MODEL_CID_PATH,
    MODEL_PATH,
    NON_PRODUCTION_STATEMENT,
    PUBLIC_BUILD_ENVIRONMENT_PATH,
    PUBLIC_BUILD_REPRODUCTION_PATH,
    PUBLIC_SOURCE_ASSESSMENT_PATH,
    PUBLIC_SOURCE_TESTNET_ASSURANCE_BUNDLE_PATH,
    PUBLIC_SOURCE_TESTNET_ASSURANCE_DOC_PATH,
    PUBLIC_SOURCE_TESTNET_ASSURANCE_VERDICT_PATH,
    PublicSourceTestnetAssuranceError,
    RUNTIME_CONFORMANCE_REPORT_PATH,
    RUNTIME_CONFORMANCE_TRACE_MAP_PATH,
    SOLVER_PORTFOLIO_REPORT_PATH,
    TASK_ID,
    VERDICT_SCHEMA_VERSION,
    build_public_source_testnet_assurance_bundle,
    build_public_source_testnet_assurance_verdict,
    render_public_source_testnet_assurance_markdown,
    validate_public_source_testnet_assurance_verdict,
)


REPO_ROOT = Path(__file__).resolve().parents[4]
PINNED_MODEL_CID = 'sha256:4edaad61130b6851220b6a75fa86a52b17e1baf33a8631def2879b0464366b43'


def _load_json(path: str) -> dict:
    return json.loads((REPO_ROOT / path).read_text(encoding='utf-8'))


def _cid_without(payload: dict, key: str) -> str:
    return calculate_artifact_cid(
        {item_key: item_value for item_key, item_value in payload.items() if item_key != key}
    )


def _build() -> tuple[dict, dict, str]:
    model_payload = _load_json(MODEL_PATH)
    model_cid = (REPO_ROOT / MODEL_CID_PATH).read_text(encoding='utf-8').strip()
    bundle = build_public_source_testnet_assurance_bundle(
        model_payload=model_payload,
        model_cid=model_cid,
        public_source_assessment=_load_json(PUBLIC_SOURCE_ASSESSMENT_PATH),
        public_build_reproduction=_load_json(PUBLIC_BUILD_REPRODUCTION_PATH),
        public_build_environment=_load_json(PUBLIC_BUILD_ENVIRONMENT_PATH),
        solver_portfolio_report=_load_json(SOLVER_PORTFOLIO_REPORT_PATH),
        fuzz_campaign_manifest=_load_json(FUZZ_CAMPAIGN_MANIFEST_PATH),
        fuzz_counterexample_manifest=_load_json(FUZZ_COUNTEREXAMPLE_MANIFEST_PATH),
        fuzz_report=_load_json(FUZZ_REPORT_PATH),
        runtime_conformance_report=_load_json(RUNTIME_CONFORMANCE_REPORT_PATH),
        runtime_conformance_trace_map=_load_json(RUNTIME_CONFORMANCE_TRACE_MAP_PATH),
        repo_root=REPO_ROOT,
    )
    verdict = build_public_source_testnet_assurance_verdict(bundle)
    markdown = render_public_source_testnet_assurance_markdown(bundle, verdict)
    return bundle, verdict, markdown


def test_public_source_testnet_assurance_artifacts_are_regenerable() -> None:
    generated_bundle, generated_verdict, generated_doc = _build()
    bundle = _load_json(PUBLIC_SOURCE_TESTNET_ASSURANCE_BUNDLE_PATH)
    verdict = _load_json(PUBLIC_SOURCE_TESTNET_ASSURANCE_VERDICT_PATH)
    doc = (REPO_ROOT / PUBLIC_SOURCE_TESTNET_ASSURANCE_DOC_PATH).read_text(encoding='utf-8')

    assert generated_bundle == bundle
    assert generated_verdict == verdict
    assert generated_doc == doc
    assert bundle['schema_version'] == BUNDLE_SCHEMA_VERSION
    assert verdict['schema_version'] == VERDICT_SCHEMA_VERSION
    assert bundle['task_id'] == TASK_ID
    assert verdict['task_id'] == TASK_ID
    assert bundle['model']['cid'] == PINNED_MODEL_CID
    assert verdict['model']['cid'] == PINNED_MODEL_CID
    assert bundle['artifact_cid'] == _cid_without(bundle, 'artifact_cid')
    assert verdict['artifact_cid'] == _cid_without(verdict, 'artifact_cid')


def test_verdict_uses_only_cxtp_151_vocabulary_and_is_disproved_not_production() -> None:
    bundle = _load_json(PUBLIC_SOURCE_TESTNET_ASSURANCE_BUNDLE_PATH)
    verdict = _load_json(PUBLIC_SOURCE_TESTNET_ASSURANCE_VERDICT_PATH)

    assert bundle['allowed_verdicts'] == list(ALLOWED_VERDICTS)
    assert verdict['allowed_verdicts'] == list(ALLOWED_VERDICTS)
    assert verdict['verdict'] in ALLOWED_VERDICTS
    assert verdict['verdict'] == 'DISPROVED'
    assert 'TESTNET_SCOPE_NOT_SECURE' not in json.dumps(verdict)
    assert 'TESTNET_SCOPE_INCONCLUSIVE' not in json.dumps(verdict)
    assert verdict['not_a_production_or_vendor_release_security_decision'] is True
    assert NON_PRODUCTION_STATEMENT in verdict['non_production_statement']
    assert bundle['scope']['production_security_result'] is False
    assert bundle['scope']['vendor_release_security_decision'] is False
    assert bundle['scope']['vendor_release_equivalence_claimed'] is False


def test_testnet_scope_assured_gate_requires_source_runtime_solver_and_no_counterevidence() -> None:
    bundle = _load_json(PUBLIC_SOURCE_TESTNET_ASSURANCE_BUNDLE_PATH)
    gate = bundle['testnet_scope_assured_gate']

    assert gate['testnet_scope_assured_allowed'] is False
    assert gate['all_required_claims_have_current_reviewed_source_evidence'] is True
    assert gate['all_required_claims_have_current_reviewed_runtime_evidence'] is False
    assert gate['all_required_claims_have_required_solver_results'] is False
    assert gate['no_fuzz_counterexamples_for_required_claims'] is False
    assert gate['no_active_not_modeled_boundaries'] is False
    assert gate['no_disproof_counterevidence'] is False
    assert bundle['claim_summary']['required_claim_count'] == 12
    assert bundle['claim_summary']['claim_gate_counts'] == {'blocked': 12}
    assert bundle['claim_summary']['source_reviewed_claim_count'] == 12
    assert bundle['claim_summary']['runtime_reviewed_claim_count'] < 12
    assert bundle['claim_summary']['solver_accepted_claim_count'] == 0

    mutated_bundle = deepcopy(bundle)
    mutated_verdict = deepcopy(_load_json(PUBLIC_SOURCE_TESTNET_ASSURANCE_VERDICT_PATH))
    mutated_verdict['verdict'] = 'TESTNET_SCOPE_ASSURED'
    with pytest.raises(PublicSourceTestnetAssuranceError, match='requires every source/runtime/solver gate'):
        validate_public_source_testnet_assurance_verdict(mutated_verdict, mutated_bundle)


def test_bundle_preserves_disproof_blockers_and_dependency_artifact_boundaries() -> None:
    bundle = _load_json(PUBLIC_SOURCE_TESTNET_ASSURANCE_BUNDLE_PATH)
    blocker_codes = {blocker['code'] for blocker in bundle['blockers']}
    artifacts = {artifact['kind']: artifact for artifact in bundle['evidence_artifacts']}

    assert {
        'SOLVER_PORTFOLIO_COUNTEREVIDENCE',
        'ADVERSARIAL_FUZZ_COUNTEREXAMPLES',
        'PUBLIC_SOURCE_KNOWN_COUNTEREXAMPLES',
        'RUNTIME_CONFORMANCE_ASSURANCE_BLOCKS',
        'REQUIRED_CLAIMS_NOT_TESTNET_SCOPE_ASSURED',
        'ACTIVE_NOT_MODELED_BOUNDARIES',
        'PUBLIC_BUILD_NOT_VENDOR_RELEASE_EQUIVALENT',
        'PUBLIC_SOURCE_NOT_PRODUCTION_RELEASE_APPROVAL',
    } == blocker_codes
    assert next(
        blocker for blocker in bundle['blockers'] if blocker['code'] == 'SOLVER_PORTFOLIO_COUNTEREVIDENCE'
    )['count'] == 12
    assert next(
        blocker for blocker in bundle['blockers'] if blocker['code'] == 'ADVERSARIAL_FUZZ_COUNTEREXAMPLES'
    )['count'] == 25
    assert artifacts['public_source_assessment']['path'] == PUBLIC_SOURCE_ASSESSMENT_PATH
    assert artifacts['testnet_solver_portfolio']['path'] == SOLVER_PORTFOLIO_REPORT_PATH
    assert artifacts['runtime_conformance_report']['path'] == RUNTIME_CONFORMANCE_REPORT_PATH
    assert all(artifact['present'] is True for artifact in artifacts.values())
    assert all(artifact['sha256'] and artifact['sha256'].startswith('sha256:') for artifact in artifacts.values())


def test_required_claim_rows_explain_why_assurance_is_not_promoted() -> None:
    bundle = _load_json(PUBLIC_SOURCE_TESTNET_ASSURANCE_BUNDLE_PATH)

    for claim in bundle['required_claims']:
        assert claim['model_cid'] == PINNED_MODEL_CID
        assert claim['source_evidence']['current_reviewed'] is True
        assert claim['solver_evidence']['required_results_accepted'] is False
        assert claim['solver_evidence']['counterevidence']
        assert claim['assurance_ready_for_testnet_scope_assured'] is False

    by_claim = {claim['claim_id']: claim for claim in bundle['required_claims']}
    signing = by_claim['xaman-testnet-claim:signing-decision-is-observed-but-crypto-output-is-not-modeled']
    assert signing['runtime_evidence']['assurance_block_count'] >= 1
    assert signing['model_status'] == 'MODELED_WITH_BLOCKING_NOT_MODELED_BOUNDARY'
    replay = by_claim['xaman-testnet-claim:replay-controls-are-not-modeled']
    assert replay['model_status'] == 'NOT_MODELED'
    assert replay['runtime_evidence']['current_reviewed'] is False


def test_documentation_records_bounded_verdict_and_allowed_values() -> None:
    doc = (REPO_ROOT / PUBLIC_SOURCE_TESTNET_ASSURANCE_DOC_PATH).read_text(encoding='utf-8')

    assert TASK_ID in doc
    assert 'DISPROVED' in doc
    assert NON_PRODUCTION_STATEMENT in doc
    assert PUBLIC_SOURCE_TESTNET_ASSURANCE_BUNDLE_PATH in doc
    assert PUBLIC_SOURCE_TESTNET_ASSURANCE_VERDICT_PATH in doc
    assert SOLVER_PORTFOLIO_REPORT_PATH in doc
    assert RUNTIME_CONFORMANCE_REPORT_PATH in doc
    assert 'Allowed verdict values remain exactly `TESTNET_SCOPE_ASSURED`, `DISPROVED`, `UNKNOWN`, `NOT_MODELED`, or `BLOCKED`.' in doc
