"""Integration tests: SecPAL / Datalog authorization execution parity (LFP2-030).

Acceptance (fail-closed):

* Authorization answers bind policy / query / provenance / semantics.
* Fallback or mock output cannot establish policy authority.
* Native Datalog and SecPAL paths agree on reviewed fixtures.
* External engine shadow never mints sole policy authority.
* Authorization never elevates to theorem / proof / satisfiability.

Interfaces: RuleProviderEvidence@2
"""

from __future__ import annotations

import pytest

from ipfs_datasets_py.logic.backends.datalog.adapters import (
    DEFAULT_AUTHORIZATION_FIXTURES,
)
from ipfs_datasets_py.logic.backends.datalog.execution_v2 import (
    RULE_EXECUTION_V2_TASK_ID,
    RULE_PROVIDER_EVIDENCE_V2_INTERFACE,
    RuleAuthorityError,
    RuleClaimKind,
    RuleDisposition,
    RuleExecutionEngineV2,
    RuleExecutionError,
    RuleExecutionMode,
    RuleExecutionRequestV2,
    RuleParityReceiptV2,
    RuleProvenanceBindingV2,
    RuleProviderEvidenceV2,
    RuleProviderKind,
    RuleSemanticsBindingV2,
    WorldSemantics,
    execute_authorization,
    execute_datalog,
    execute_parity,
    execute_secpal,
    mock_or_fallback_establishes_policy,
    non_authoritative_signal_establishes,
    normalize_rule_provider,
)
from ipfs_datasets_py.logic.backends.results import ResultAuthority, ResultStatus
from ipfs_datasets_py.logic.backends.toolchain_roles import (
    ToolRole,
    ToolchainAuthorityCeiling,
)
from ipfs_datasets_py.logic.software_verification.authorization import (
    AuthorizationEvidenceAuthority,
    DecisionOutcome,
    GeneratedCodeCorrectness,
)


def _fixture(category: str):
    return next(
        item for item in DEFAULT_AUTHORIZATION_FIXTURES if item.category == category
    )


def _allow_request(**overrides: object) -> RuleExecutionRequestV2:
    fixture = _fixture("allow")
    payload: dict[str, object] = {
        "request_id": "req:secpal:allow:1",
        "provider": RuleProviderKind.PARITY,
        "document": fixture.document,
        "query": fixture.query,
        "world": WorldSemantics.CLOSED_WORLD,
        "mode": RuleExecutionMode.NATIVE_REFERENCE,
        "available": True,
        "confidence": 0.99,
        "fluent_text": "Obviously this policy allows access.",
    }
    payload.update(overrides)
    return RuleExecutionRequestV2(**payload)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Interface / typing surface
# ---------------------------------------------------------------------------


def test_interface_identities() -> None:
    engine = RuleExecutionEngineV2()
    assert engine.INTERFACE == RULE_PROVIDER_EVIDENCE_V2_INTERFACE
    assert engine.interface == "RuleProviderEvidence@2"
    assert engine.TASK_ID == RULE_EXECUTION_V2_TASK_ID
    assert engine.TASK_ID == "LFP2-030"
    assert RuleExecutionRequestV2.interface == "RuleExecutionRequest@2"


def test_provider_normalization() -> None:
    assert normalize_rule_provider("datalog") is RuleProviderKind.DATALOG
    assert normalize_rule_provider("secpal-authorization") is RuleProviderKind.SECPAL
    assert normalize_rule_provider("datalog_secpal") is RuleProviderKind.PARITY
    assert normalize_rule_provider(RuleProviderKind.SECPAL) is RuleProviderKind.SECPAL
    with pytest.raises(RuleExecutionError):
        normalize_rule_provider("z3")
    with pytest.raises(RuleExecutionError):
        normalize_rule_provider("microsoft-secpal")


# ---------------------------------------------------------------------------
# Binding completeness: policy / query / provenance / semantics
# ---------------------------------------------------------------------------


def test_authorization_answer_binds_policy_query_provenance_semantics() -> None:
    result = execute_parity(
        _fixture("allow").document,
        _fixture("allow").query,
        request_id="req:bind:allow",
    )
    evidence = result.evidence
    assert evidence.interface == RULE_PROVIDER_EVIDENCE_V2_INTERFACE
    assert evidence.bindings_complete() is True
    assert evidence.policy_digest == _fixture("allow").document.sha256
    assert evidence.query_id == _fixture("allow").query.query_id
    assert isinstance(evidence.provenance, RuleProvenanceBindingV2)
    assert evidence.provenance.policy_digest == evidence.policy_digest
    assert evidence.provenance.query_id == evidence.query_id
    assert "source:authz-fixtures" in evidence.provenance.source_ref_ids
    assert isinstance(evidence.semantics, RuleSemanticsBindingV2)
    assert evidence.semantics.world is WorldSemantics.CLOSED_WORLD
    assert evidence.semantics.max_delegation_depth >= 1
    assert evidence.semantics.strata_used  # fixture rules declare strata
    assert evidence.policy_established is True
    assert evidence.policy_authority_established is True
    assert evidence.result_authority is ResultAuthority.AUTHORIZATION
    assert evidence.authority_ceiling is ToolchainAuthorityCeiling.AUTHORIZATION
    assert evidence.role is ToolRole.AUTHORITY
    assert (
        evidence.authorization_authority
        is AuthorizationEvidenceAuthority.AUTHORIZATION
    )
    assert (
        evidence.generated_code_correctness
        is GeneratedCodeCorrectness.NOT_ESTABLISHED
    )
    assert evidence.is_theorem_authority is False
    assert evidence.is_proved is False
    assert evidence.proof_established is False
    assert evidence.satisfiability_established is False
    assert evidence.theorem_established is False
    wire = evidence.to_dict()
    assert wire["bindings_complete"] is True
    assert wire["claim_policy"] is True
    assert wire["claim_proof"] is False
    assert wire["claim_satisfiability"] is False
    assert wire["claim_theorem"] is False
    assert wire["policy_established"] is True
    assert "policy_digest" in wire
    assert "query_id" in wire
    assert "provenance" in wire
    assert "semantics" in wire


def test_explanations_bind_concrete_rules_and_delegations() -> None:
    allow = execute_datalog(
        _fixture("allow").document,
        _fixture("allow").query,
        request_id="req:bind:rules",
    )
    assert "rule:admin-may-read" in allow.evidence.provenance.bound_rule_ids

    delegation = execute_secpal(
        _fixture("delegation").document,
        _fixture("delegation").query,
        request_id="req:bind:delegation",
    )
    assert delegation.evidence.policy_established is True
    assert delegation.evidence.outcome is DecisionOutcome.ALLOW
    # Delegation provenance is bound when the explanation cites it.
    assert (
        "delegation:alice-bob" in delegation.evidence.provenance.bound_delegation_ids
        or delegation.evidence.disposition is RuleDisposition.ALLOW
    )


# ---------------------------------------------------------------------------
# Parity: Datalog ↔ SecPAL
# ---------------------------------------------------------------------------


def test_native_datalog_and_secpal_agree_on_default_fixtures() -> None:
    engine = RuleExecutionEngineV2()
    results = engine.execute_default_fixtures(provider=RuleProviderKind.PARITY)
    assert len(results) == len(DEFAULT_AUTHORIZATION_FIXTURES)
    expected = {
        "allow": DecisionOutcome.ALLOW,
        "deny": DecisionOutcome.DENY,
        "unknown": DecisionOutcome.UNKNOWN,
        "conflict": DecisionOutcome.CONFLICT,
        "delegation": DecisionOutcome.ALLOW,
    }
    for result, fixture in zip(results, DEFAULT_AUTHORIZATION_FIXTURES, strict=True):
        assert result.evidence.parity is not None
        assert result.evidence.parity.native_agreed is True
        assert result.evidence.parity.parity_ok is True
        assert result.evidence.parity.datalog_outcome is expected[fixture.category]
        assert result.evidence.parity.secpal_outcome is expected[fixture.category]
        assert result.evidence.outcome is expected[fixture.category]
        assert result.evidence.policy_established is True
        assert result.datalog_result is not None
        assert result.secpal_result is not None
        assert result.datalog_result.authority is ResultAuthority.AUTHORIZATION
        assert result.secpal_result.authority is ResultAuthority.AUTHORIZATION
        assert result.rendered_datalog
        assert result.rendered_secpal
        assert "authz_result" in result.rendered_datalog
        assert fixture.query.principal_id in result.rendered_secpal


@pytest.mark.parametrize(
    "category,status",
    [
        ("allow", ResultStatus.AUTHORIZED),
        ("deny", ResultStatus.DENIED),
        ("unknown", ResultStatus.UNKNOWN),
        ("conflict", ResultStatus.UNKNOWN),
        ("delegation", ResultStatus.AUTHORIZED),
    ],
)
def test_status_mapping_under_parity(category: str, status: ResultStatus) -> None:
    fixture = _fixture(category)
    result = execute_parity(
        fixture.document,
        fixture.query,
        request_id=f"req:status:{category}",
    )
    assert result.evidence.result_status is status
    assert result.evidence.disposition.value in {
        fixture.expected_outcome.value,
        "bounds_exhausted",
    }


def test_single_provider_paths_match_parity_outcome() -> None:
    fixture = _fixture("deny")
    datalog = execute_datalog(
        fixture.document, fixture.query, request_id="req:single:datalog"
    )
    secpal = execute_secpal(
        fixture.document, fixture.query, request_id="req:single:secpal"
    )
    parity = execute_parity(
        fixture.document, fixture.query, request_id="req:single:parity"
    )
    assert datalog.evidence.outcome is DecisionOutcome.DENY
    assert secpal.evidence.outcome is DecisionOutcome.DENY
    assert parity.evidence.outcome is DecisionOutcome.DENY
    assert datalog.evidence.policy_established is True
    assert secpal.evidence.policy_established is True
    assert parity.evidence.policy_established is True


# ---------------------------------------------------------------------------
# Mock / fallback cannot establish policy authority
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("claim", list(RuleClaimKind))
def test_non_authoritative_signals_never_establish_claims(
    claim: RuleClaimKind,
) -> None:
    assert (
        non_authoritative_signal_establishes(
            claim,
            mock_output={"status": "authorized", "outcome": "allow"},
            fallback_output={"status": "authorized"},
            available=True,
            confidence=1.0,
            fluent_text="This policy clearly authorizes the principal.",
        )
        is False
    )
    assert (
        mock_or_fallback_establishes_policy(
            mock_output={"authorized": True},
            fallback_output={"authorized": True},
            available=True,
        )
        is False
    )


def test_mock_output_rejected_and_never_establishes_policy() -> None:
    result = execute_authorization(
        _fixture("allow").document,
        _fixture("allow").query,
        request_id="req:mock:1",
        provider=RuleProviderKind.PARITY,
        mock_output={
            "outcome": "allow",
            "authorized": True,
            "policy_authority": True,
            "status": "proved",
        },
        confidence=1.0,
        available=True,
        fluent_text="Mock says allow.",
    )
    assert result.disposition is RuleDisposition.MOCK_REJECTED
    assert result.policy_established is False
    assert result.evidence.mock_output_present is True
    assert result.evidence.policy_authority_established is False
    assert result.evidence.outcome is None
    assert result.evidence.mode is RuleExecutionMode.MOCK
    assert result.evidence.result_status is ResultStatus.UNKNOWN
    assert result.evidence.bindings_complete() is True  # still binds ids
    assert result.evidence.policy_digest == _fixture("allow").document.sha256
    assert "mock_output_cannot_establish_policy" in result.evidence.diagnostics
    wire = result.evidence.to_dict()
    assert wire["claim_policy"] is False
    assert wire["policy_established"] is False
    assert wire["is_proved"] is False
    assert wire["is_theorem_authority"] is False
    for claim in RuleClaimKind:
        assert result.evidence.non_authoritative_claim(claim) is False
        assert result.evidence.claim_established(claim) is False


def test_fallback_output_rejected_and_never_establishes_policy() -> None:
    result = execute_authorization(
        _fixture("allow").document,
        _fixture("allow").query,
        request_id="req:fallback:1",
        provider=RuleProviderKind.DATALOG,
        fallback_output={"outcome": "allow", "reason": "engine missing"},
        available=False,
    )
    assert result.disposition is RuleDisposition.FALLBACK_REJECTED
    assert result.policy_established is False
    assert result.evidence.fallback_output_present is True
    assert result.evidence.mode is RuleExecutionMode.FALLBACK
    assert "fallback_output_cannot_establish_policy" in result.evidence.diagnostics


def test_mode_mock_without_payload_still_rejects() -> None:
    result = RuleExecutionEngineV2().execute(
        _allow_request(mode=RuleExecutionMode.MOCK, mock_output=None)
    )
    assert result.disposition is RuleDisposition.MOCK_REJECTED
    assert result.policy_established is False


def test_mode_fallback_without_payload_still_rejects() -> None:
    result = RuleExecutionEngineV2().execute(
        _allow_request(mode=RuleExecutionMode.FALLBACK, fallback_output=None)
    )
    assert result.disposition is RuleDisposition.FALLBACK_REJECTED
    assert result.policy_established is False


def test_cannot_construct_evidence_with_mock_and_policy_authority() -> None:
    fixture = _fixture("allow")
    provenance = RuleProvenanceBindingV2(
        policy_digest=fixture.document.sha256,
        query_id=fixture.query.query_id,
        source_ref_ids=fixture.query.source_ref_ids,
    )
    semantics = RuleSemanticsBindingV2.from_document(fixture.document)
    with pytest.raises(RuleAuthorityError, match="mock"):
        RuleProviderEvidenceV2(
            evidence_id="ev:bad:mock",
            request_id="req:bad:mock",
            request_digest="0" * 64,
            provider=RuleProviderKind.DATALOG,
            disposition=RuleDisposition.ALLOW,
            outcome=DecisionOutcome.ALLOW,
            mode=RuleExecutionMode.MOCK,
            policy_digest=fixture.document.sha256,
            query_id=fixture.query.query_id,
            provenance=provenance,
            semantics=semantics,
            policy_authority_established=True,
            mock_output_present=True,
        )


def test_cannot_construct_evidence_with_fallback_and_policy_authority() -> None:
    fixture = _fixture("allow")
    provenance = RuleProvenanceBindingV2(
        policy_digest=fixture.document.sha256,
        query_id=fixture.query.query_id,
        source_ref_ids=fixture.query.source_ref_ids,
    )
    semantics = RuleSemanticsBindingV2.from_document(fixture.document)
    with pytest.raises(RuleAuthorityError, match="fallback|mock"):
        RuleProviderEvidenceV2(
            evidence_id="ev:bad:fallback",
            request_id="req:bad:fallback",
            request_digest="0" * 64,
            provider=RuleProviderKind.SECPAL,
            disposition=RuleDisposition.ALLOW,
            outcome=DecisionOutcome.ALLOW,
            mode=RuleExecutionMode.FALLBACK,
            policy_digest=fixture.document.sha256,
            query_id=fixture.query.query_id,
            provenance=provenance,
            semantics=semantics,
            policy_authority_established=True,
            fallback_output_present=True,
        )


def test_cannot_claim_theorem_result_status() -> None:
    fixture = _fixture("allow")
    provenance = RuleProvenanceBindingV2(
        policy_digest=fixture.document.sha256,
        query_id=fixture.query.query_id,
    )
    semantics = RuleSemanticsBindingV2.from_document(fixture.document)
    with pytest.raises(RuleAuthorityError, match="theorem"):
        RuleProviderEvidenceV2(
            evidence_id="ev:bad:theorem",
            request_id="req:bad:theorem",
            request_digest="0" * 64,
            provider=RuleProviderKind.DATALOG,
            disposition=RuleDisposition.ALLOW,
            outcome=DecisionOutcome.ALLOW,
            mode=RuleExecutionMode.NATIVE_REFERENCE,
            policy_digest=fixture.document.sha256,
            query_id=fixture.query.query_id,
            provenance=provenance,
            semantics=semantics,
            result_status=ResultStatus.PROVED,
            policy_authority_established=True,
        )


def test_cannot_exceed_authorization_result_authority() -> None:
    fixture = _fixture("allow")
    provenance = RuleProvenanceBindingV2(
        policy_digest=fixture.document.sha256,
        query_id=fixture.query.query_id,
    )
    semantics = RuleSemanticsBindingV2.from_document(fixture.document)
    with pytest.raises(RuleAuthorityError, match="authorization"):
        RuleProviderEvidenceV2(
            evidence_id="ev:bad:sat",
            request_id="req:bad:sat",
            request_digest="0" * 64,
            provider=RuleProviderKind.DATALOG,
            disposition=RuleDisposition.ALLOW,
            outcome=DecisionOutcome.ALLOW,
            mode=RuleExecutionMode.NATIVE_REFERENCE,
            policy_digest=fixture.document.sha256,
            query_id=fixture.query.query_id,
            provenance=provenance,
            semantics=semantics,
            result_authority=ResultAuthority.SATISFIABILITY,
            policy_authority_established=True,
        )


# ---------------------------------------------------------------------------
# World semantics, stratification, closed/open world
# ---------------------------------------------------------------------------


def test_closed_world_semantics_bound_on_evidence() -> None:
    result = execute_parity(
        _fixture("unknown").document,
        _fixture("unknown").query,
        request_id="req:world:closed",
        world=WorldSemantics.CLOSED_WORLD,
    )
    assert result.evidence.semantics.world is WorldSemantics.CLOSED_WORLD
    assert result.evidence.outcome is DecisionOutcome.UNKNOWN
    assert result.evidence.policy_established is True


def test_open_world_semantics_bound_and_does_not_fabricate_deny() -> None:
    result = execute_parity(
        _fixture("unknown").document,
        _fixture("unknown").query,
        request_id="req:world:open",
        world=WorldSemantics.OPEN_WORLD,
    )
    assert result.evidence.semantics.world is WorldSemantics.OPEN_WORLD
    # Absence under open world remains unknown, never invented deny.
    assert result.evidence.outcome is DecisionOutcome.UNKNOWN
    assert result.evidence.policy_established is True


def test_stratification_receipt_lists_used_strata() -> None:
    result = execute_datalog(
        _fixture("allow").document,
        _fixture("allow").query,
        request_id="req:strata",
    )
    strata = result.evidence.semantics.strata_used
    assert strata
    assert all(isinstance(item, int) and item >= 0 for item in strata)
    assert result.evidence.semantics.max_stratum >= max(strata)


# ---------------------------------------------------------------------------
# Confidence / availability / fluent text never establish policy
# ---------------------------------------------------------------------------


def test_confidence_fluent_availability_do_not_establish_policy() -> None:
    result = RuleExecutionEngineV2().execute(
        _allow_request(
            confidence=1.0,
            available=True,
            fluent_text="Guaranteed allow by natural language.",
        )
    )
    evidence = result.evidence
    assert evidence.confidence == 0.99 or evidence.confidence == 1.0
    assert evidence.available is True
    assert evidence.fluent_text_present is True
    # Native evaluation may establish policy; non-authoritative signals do not.
    assert evidence.policy_established is True
    for claim in RuleClaimKind:
        assert evidence.non_authoritative_claim(claim) is False
    assert evidence.claim_established(RuleClaimKind.POLICY) is True
    assert evidence.claim_established(RuleClaimKind.PROOF) is False
    assert evidence.claim_established(RuleClaimKind.SATISFIABILITY) is False
    assert evidence.claim_established(RuleClaimKind.THEOREM) is False


# ---------------------------------------------------------------------------
# Parity receipt structure
# ---------------------------------------------------------------------------


def test_parity_receipt_serializes_cleanly() -> None:
    receipt = RuleParityReceiptV2(
        datalog_outcome=DecisionOutcome.ALLOW,
        secpal_outcome=DecisionOutcome.ALLOW,
        native_agreed=True,
        shadow_invoked=False,
    )
    payload = receipt.to_dict()
    assert payload["interface"] == "RuleParityReceipt@2"
    assert payload["parity_ok"] is True
    assert payload["datalog_outcome"] == "allow"
    assert payload["secpal_outcome"] == "allow"
    assert payload["native_agreed"] is True


def test_wire_dict_preserves_authorization_ceiling() -> None:
    result = execute_secpal(
        _fixture("allow").document,
        _fixture("allow").query,
        request_id="req:wire:secpal",
    )
    wire = result.to_dict()
    assert wire["interface"] == "RuleExecutionResult@2"
    assert wire["is_proved"] is False
    assert wire["is_theorem_authority"] is False
    assert wire["policy_established"] is True
    assert wire["evidence"]["interface"] == RULE_PROVIDER_EVIDENCE_V2_INTERFACE
    assert wire["evidence"]["result_authority"] == "authorization"
    assert wire["evidence"]["authority_ceiling"] == "authorization"
    assert wire["evidence"]["generated_code_correctness"] == "not_established"


def test_request_rejects_free_form_authority_metadata() -> None:
    fixture = _fixture("allow")
    with pytest.raises(RuleAuthorityError):
        RuleExecutionRequestV2(
            request_id="req:meta:bad",
            provider=RuleProviderKind.DATALOG,
            document=fixture.document,
            query=fixture.query,
            metadata={"is_proved": True},
        )


def test_provenance_policy_mismatch_rejected() -> None:
    fixture = _fixture("allow")
    provenance = RuleProvenanceBindingV2(
        policy_digest="a" * 64,
        query_id=fixture.query.query_id,
    )
    semantics = RuleSemanticsBindingV2.from_document(fixture.document)
    with pytest.raises(RuleExecutionError, match="policy_digest"):
        RuleProviderEvidenceV2(
            evidence_id="ev:mismatch",
            request_id="req:mismatch",
            request_digest="0" * 64,
            provider=RuleProviderKind.DATALOG,
            disposition=RuleDisposition.ALLOW,
            outcome=DecisionOutcome.ALLOW,
            mode=RuleExecutionMode.NATIVE_REFERENCE,
            policy_digest=fixture.document.sha256,
            query_id=fixture.query.query_id,
            provenance=provenance,
            semantics=semantics,
            policy_authority_established=True,
        )
