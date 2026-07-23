"""Deterministic Xaman mutation and disproof evidence generation.

The checked-in Xaman SecurityModelIR intentionally uses a small, public-source
schema.  This module keeps the mutation suite bound to that schema: each
vector must name a claim in the frozen model and every result blocks release.
It produces counterexamples for deliberately removed guards and records
missing-evidence cases without treating either kind of result as a proof of
the deployed application.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


SCHEMA_VERSION = 'xaman-disproof-vectors/v1'
REPORT_SCHEMA_VERSION = 'xaman-counterexample-report/v1'
TASK_ID = 'PORTAL-CXTP-070'
MODEL_PATH = 'security_ir_artifacts/corpora/xaman-app/security-model-ir.json'
MODEL_CID_PATH = 'security_ir_artifacts/corpora/xaman-app/security-model-ir.cid'
XRPL_TRANSACTION_COVERAGE_PATH = (
    'security_ir_artifacts/corpora/xaman-app/xrpl-transaction-coverage.json'
)


@dataclass(frozen=True, slots=True)
class XamanDisproofScenario:
    """One fail-closed mutation against a frozen Xaman claim."""

    vector_id: str
    claim_id: str
    tactic: str
    mutation: str
    expected_outcome: str
    evidence: tuple[str, ...]
    counterexample: Mapping[str, Any] | None = None
    missing_evidence: tuple[str, ...] = ()


SCENARIOS: tuple[XamanDisproofScenario, ...] = (
    XamanDisproofScenario(
        vector_id='xaman-disproof:assumption-mutation-native-vault',
        claim_id='xaman-claim:software-custody-requires-vault-authentication',
        tactic='assumption_mutation',
        mutation='mark native vault cryptography assumption as cleared without evidence',
        expected_outcome='counterexample_found',
        evidence=('security_ir_artifacts/corpora/xaman-app/wallet-auth-facts.json',),
        counterexample={
            'cleared_assumption_without_evidence': (
                'xaman-assumption:native-vault-crypto-and-biometric-security'
            ),
            'violated_policy': 'blocking assumptions cannot be cleared without evidence',
        },
    ),
    XamanDisproofScenario(
        vector_id='xaman-disproof:auth-precondition-removal',
        claim_id='xaman-claim:signing-is-gated-by-auth-and-vault-overlay',
        tactic='auth_precondition_removal',
        mutation='remove auth/vault overlay precondition from signing path',
        expected_outcome='counterexample_found',
        evidence=(
            'security_ir_artifacts/corpora/xaman-app/wallet-auth-facts.json',
            'security_ir_artifacts/corpora/xaman-app/payload-lifecycle-facts.json',
        ),
        counterexample={
            'removed_precondition': 'auth_or_vault_overlay',
            'invalid_path': 'review_acceptance_to_signed_blob_without_auth',
        },
    ),
    XamanDisproofScenario(
        vector_id='xaman-disproof:stale-evidence-acceptance',
        claim_id='xaman-claim:proof-consumer-must-reject-non-proved-results',
        tactic='stale_evidence',
        mutation='accept proof receipt with expired environment evidence',
        expected_outcome='counterexample_found',
        evidence=('security_ir_artifacts/corpora/xaman-app/security-claims.json',),
        counterexample={
            'receipt_result': 'proved',
            'evidence_status': 'stale_evidence',
            'expected_consumer_action': 'reject',
        },
    ),
    XamanDisproofScenario(
        vector_id='xaman-disproof:wrong-network-signing',
        claim_id='xaman-claim:network-binding-prevents-wrong-network-signing',
        tactic='wrong_network',
        mutation='allow signing when payload force_network mismatches active network',
        expected_outcome='counterexample_found',
        evidence=(
            'security_ir_artifacts/corpora/xaman-app/payload-lifecycle-facts.json',
            'security_ir_artifacts/corpora/xaman-app/xrpl-transaction-facts.json',
        ),
        counterexample={
            'payload_force_network': 'mainnet',
            'active_network': 'testnet',
            'mutated_guard': 'force_network_check_removed',
        },
    ),
    XamanDisproofScenario(
        vector_id='xaman-disproof:replay-resolved-payload',
        claim_id=(
            'xaman-claim:client-replay-controls-exist-but-backend-single-use-is-blocking'
        ),
        tactic='replay_payload',
        mutation='skip resolved_at and expired checks before review or signing',
        expected_outcome='counterexample_found',
        evidence=('security_ir_artifacts/corpora/xaman-app/payload-lifecycle-facts.json',),
        counterexample={
            'payload_state': 'resolved_at_present',
            'mutated_guard': 'resolved_or_expired_check_removed',
        },
    ),
    XamanDisproofScenario(
        vector_id='xaman-disproof:downgraded-solver-result',
        claim_id='xaman-claim:proof-consumer-must-reject-non-proved-results',
        tactic='downgraded_solver',
        mutation='accept missing optional solver lane report as proof authority',
        expected_outcome='counterexample_found',
        evidence=(
            'security_ir_artifacts/environment/optional-solver-install-report.json',
        ),
        counterexample={
            'solver_lane': 'blocked_optional_lane',
            'mutated_consumer_action': 'accept_report',
        },
    ),
    XamanDisproofScenario(
        vector_id='xaman-disproof:unsupported-xrpl-semantics',
        claim_id='xaman-claim:transaction-validation-is-incomplete-for-selected-classes',
        tactic='unsupported_xrpl_semantics',
        mutation=(
            'treat TODO validation for TrustSet, OfferCreate, or SignerListSet as proved'
        ),
        expected_outcome='counterexample_found',
        evidence=(
            'security_ir_artifacts/corpora/xaman-app/xrpl-transaction-facts.json',
            XRPL_TRANSACTION_COVERAGE_PATH,
        ),
        counterexample={
            'transaction_classes': ['TrustSet', 'OfferCreate', 'SignerListSet'],
            'validation_status': 'TODO_RESOLVES_WITHOUT_CHECKS',
        },
    ),
    XamanDisproofScenario(
        vector_id='xaman-disproof:backend-double-use',
        claim_id='xaman-claim:backend-payload-service-is-trusted-not-proved',
        tactic='backend_trust_failure',
        mutation='allow same backend payload to be accepted from two devices',
        expected_outcome='blocked_by_missing_evidence',
        evidence=('security_ir_artifacts/corpora/xaman-app/payload-lifecycle-facts.json',),
        missing_evidence=(
            'backend source snapshot',
            'single-use enforcement trace',
            'PATCH conflict behavior',
        ),
    ),
    XamanDisproofScenario(
        vector_id='xaman-disproof:runtime-equivalence-missing',
        claim_id='xaman-claim:runtime-equivalence-is-blocked-without-device-traces',
        tactic='stale_evidence',
        mutation=(
            'treat source review as deployed runtime equivalence without real-device traces'
        ),
        expected_outcome='blocked_by_missing_evidence',
        evidence=('security_ir_artifacts/corpora/xaman-app/runtime-trace-report.json',),
        missing_evidence=(
            'real-device trace bundle',
            'build provenance',
            'runtime environment snapshot',
        ),
    ),
)


def _claims_by_id(model_payload: Mapping[str, Any]) -> set[str]:
    claims = model_payload.get('claims')
    if not isinstance(claims, list):
        raise ValueError('model payload claims must be a list')
    claim_ids = {
        str(claim['id'])
        for claim in claims
        if isinstance(claim, Mapping) and isinstance(claim.get('id'), str)
    }
    if not claim_ids:
        raise ValueError('model payload does not contain claim identifiers')
    return claim_ids


def _scenario_vector(
    scenario: XamanDisproofScenario,
    *,
    xrpl_transaction_coverage: Mapping[str, Any] | None,
) -> dict[str, Any]:
    vector: dict[str, Any] = {
        'id': scenario.vector_id,
        'claim_id': scenario.claim_id,
        'tactic': scenario.tactic,
        'mutation': scenario.mutation,
        'expected_outcome': scenario.expected_outcome,
        'evidence': list(scenario.evidence),
    }
    if scenario.vector_id == 'xaman-disproof:unsupported-xrpl-semantics':
        if xrpl_transaction_coverage is None:
            raise ValueError('XRPL transaction coverage is required for unsupported semantics')
        vector['xrpl_transaction_coverage'] = {
            'path': XRPL_TRANSACTION_COVERAGE_PATH,
            'artifact_cid': xrpl_transaction_coverage['artifact_cid'],
            'transaction_classes': ['TrustSet', 'OfferCreate', 'SignerListSet'],
        }
    return vector


def _scenario_result(scenario: XamanDisproofScenario) -> dict[str, Any]:
    result: dict[str, Any] = {
        'vector_id': scenario.vector_id,
        'claim_id': scenario.claim_id,
        'result': scenario.expected_outcome,
        'counterexample': dict(scenario.counterexample)
        if scenario.counterexample is not None
        else None,
        'release_policy': 'block',
    }
    if scenario.missing_evidence:
        result['missing_evidence'] = list(scenario.missing_evidence)
    return result


def build_xaman_disproof_artifacts(
    model_payload: Mapping[str, Any],
    *,
    model_cid: str,
    xrpl_transaction_coverage: Mapping[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Build deterministic vectors and a release-blocking result report."""

    if not model_cid:
        raise ValueError('model CID is required')
    claim_ids = _claims_by_id(model_payload)
    unknown_claims = sorted(
        scenario.claim_id for scenario in SCENARIOS if scenario.claim_id not in claim_ids
    )
    if unknown_claims:
        raise ValueError(f'disproof scenarios reference unknown model claims: {unknown_claims}')

    vectors = [
        _scenario_vector(
            scenario,
            xrpl_transaction_coverage=xrpl_transaction_coverage,
        )
        for scenario in SCENARIOS
    ]
    results = [_scenario_result(scenario) for scenario in SCENARIOS]
    counterexample_found_count = sum(
        result['result'] == 'counterexample_found' for result in results
    )
    blocked_count = sum(
        result['result'] == 'blocked_by_missing_evidence' for result in results
    )

    vectors_artifact: dict[str, Any] = {
        'schema_version': SCHEMA_VERSION,
        'task_id': TASK_ID,
        'model': {'path': MODEL_PATH, 'cid': model_cid},
        'vectors': vectors,
        'security_decision': 'DISPROOF_SUITE_FAIL_CLOSED',
    }
    if xrpl_transaction_coverage is None:
        raise ValueError('XRPL transaction coverage is required for the disproof suite')
    vectors_artifact['xrpl_transaction_coverage'] = {
        'path': XRPL_TRANSACTION_COVERAGE_PATH,
        'artifact_cid': xrpl_transaction_coverage['artifact_cid'],
    }
    report: dict[str, Any] = {
        'schema_version': REPORT_SCHEMA_VERSION,
        'task_id': TASK_ID,
        'model': {'path': MODEL_PATH, 'cid': model_cid},
        'results': results,
        'summary': {
            'vector_count': len(vectors),
            'counterexample_found_count': counterexample_found_count,
            'blocked_count': blocked_count,
            'release_acceptable_count': 0,
        },
        'overall_status': 'blocked',
        'production_release_blocked': True,
        'security_decision': 'BLOCK_COUNTEREXAMPLES_AND_MISSING_EVIDENCE',
    }
    return vectors_artifact, report
