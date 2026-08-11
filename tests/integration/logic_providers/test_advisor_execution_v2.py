"""Integration tests: ErgoAI / SymbolicAI advisor deterministic parse gate (LFP2-035).

Acceptance (fail-closed):

* Confidence, fluent text, availability, or mock output cannot establish
  parse correctness, satisfiability, policy, or proof.
* Successful deterministic reparse yields typed unverified candidates only.
* Independent validation is required before any staged admission.

Interfaces: AdvisorProviderEvidence@2
"""

from __future__ import annotations

import pytest

from ipfs_datasets_py.logic.backends.advisor_execution_v2 import (
    ADVISOR_EXECUTION_V2_TASK_ID,
    ADVISOR_PROVIDER_EVIDENCE_V2_INTERFACE,
    AdvisorAuthorityError,
    AdvisorClaimKind,
    AdvisorExecutionError,
    AdvisorExecutionGateV2,
    AdvisorExecutionRequestV2,
    AdvisorGateDisposition,
    AdvisorProviderEvidenceV2,
    AdvisorProviderKind,
    AdvisorReparseRecord,
    advisor_never_establishes_proof,
    gate_advisor_proposal,
    gate_ergoai_proposal,
    gate_symbolicai_proposal,
    non_deterministic_signal_establishes,
    normalize_advisor_provider,
)
from ipfs_datasets_py.logic.backends.results import ResultAuthority, ResultStatus
from ipfs_datasets_py.logic.backends.toolchain_roles import (
    ToolRole,
    ToolchainAuthorityCeiling,
)
from ipfs_datasets_py.logic.formalization.advisor_parser_adapter import AdvisorNotation
from ipfs_datasets_py.logic.formalization.proposal_advisors import (
    UNVERIFIED_AUTHORITY,
    ProposalCandidate,
    ProposalKind,
    ProposalProvider,
)
from ipfs_datasets_py.logic.parsers.flogic_v2 import FLOGIC_FRONTEND_V2_INTERFACE


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_FLOGIC_BODY = 'rex[name -> "Rex", age -> 5] : Dog.\n'
_SMTLIB_BODY = (
    "(set-logic QF_UF)\n"
    "(declare-const p Bool)\n"
    "(assert p)\n"
    "(check-sat)\n"
)
_GARBAGE_BODY = "this is not a logic formula at all !!! @@@ ###"


def _ergo_request(**overrides: object) -> AdvisorExecutionRequestV2:
    payload: dict[str, object] = {
        "request_id": "req:ergo:1",
        "provider": AdvisorProviderKind.ERGOAI,
        "proposed_source": _FLOGIC_BODY,
        "source_ref_ids": ("source:fixture:flogic:1",),
        "notation": AdvisorNotation.FLOGIC,
        "features": ("flogic", "frame"),
        "candidate_id": "cand:ergo:1",
        "confidence": 0.99,
        "fluent_text": "Obviously this frame is correct and proved.",
        "available": True,
    }
    payload.update(overrides)
    return AdvisorExecutionRequestV2(**payload)  # type: ignore[arg-type]


def _symai_request(**overrides: object) -> AdvisorExecutionRequestV2:
    payload: dict[str, object] = {
        "request_id": "req:symai:1",
        "provider": AdvisorProviderKind.SYMBOLICAI,
        "proposed_source": _SMTLIB_BODY,
        "source_ref_ids": ("source:fixture:smt:1",),
        "notation": AdvisorNotation.SMTLIB2,
        "features": ("smtlib2",),
        "candidate_id": "cand:symai:1",
        "confidence": 0.99,
        "fluent_text": "High-confidence SMT proposal that looks fluent.",
        "available": True,
    }
    payload.update(overrides)
    return AdvisorExecutionRequestV2(**payload)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Interface / typing surface
# ---------------------------------------------------------------------------


def test_interface_identities() -> None:
    gate = AdvisorExecutionGateV2()
    assert gate.INTERFACE == ADVISOR_PROVIDER_EVIDENCE_V2_INTERFACE
    assert gate.interface == "AdvisorProviderEvidence@2"
    assert gate.TASK_ID == ADVISOR_EXECUTION_V2_TASK_ID
    assert AdvisorExecutionRequestV2.interface == "AdvisorExecutionRequest@2"


def test_provider_normalization() -> None:
    assert normalize_advisor_provider("ergoai") is AdvisorProviderKind.ERGOAI
    assert normalize_advisor_provider("symbolicai") is AdvisorProviderKind.SYMBOLICAI
    assert normalize_advisor_provider("symai") is AdvisorProviderKind.SYMAI
    assert normalize_advisor_provider(ProposalProvider.SYMAI) is AdvisorProviderKind.SYMAI
    with pytest.raises(AdvisorExecutionError):
        normalize_advisor_provider("leanstral")
    with pytest.raises(AdvisorExecutionError):
        normalize_advisor_provider("z3")


# ---------------------------------------------------------------------------
# ErgoAI deterministic reparse
# ---------------------------------------------------------------------------


def test_ergoai_valid_frame_becomes_typed_unverified_candidate() -> None:
    result = gate_ergoai_proposal(
        _FLOGIC_BODY,
        request_id="req:ergo:valid",
        source_ref_ids=("source:fixture:flogic:1",),
        features=("flogic", "frame"),
        confidence=0.99,
        fluent_text="This is clearly a valid and proved frame.",
        available=True,
        candidate_id="cand:ergo:valid",
    )
    assert result.disposition is AdvisorGateDisposition.TYPED_CANDIDATE
    assert result.parse_ok is True
    assert result.evidence.reparse.reparse_succeeded is True
    assert result.evidence.reparse.parser_interface == FLOGIC_FRONTEND_V2_INTERFACE
    assert result.evidence.authority == UNVERIFIED_AUTHORITY
    assert result.evidence.result_authority is ResultAuthority.CANDIDATE
    assert result.evidence.result_status is ResultStatus.CANDIDATE
    assert result.evidence.role is ToolRole.ADVISOR
    assert result.evidence.authority_ceiling is ToolchainAuthorityCeiling.ADVISORY
    assert result.remains_unverified_candidate is True
    assert result.is_proved is False
    assert result.evidence.parse_correctness_established is True
    assert result.evidence.satisfiability_established is False
    assert result.evidence.policy_established is False
    assert result.evidence.proof_established is False
    assert result.typed_expression is not None
    assert result.controlled_source is not None
    assert result.controlled_source.can_certify is False
    # Admission still requires independent validation.
    assert result.evidence.acceptance is not None
    assert result.evidence.acceptance.accepted is False
    assert "missing_independent_solver_or_kernel_validation" in (
        result.evidence.acceptance.reasons
    )


def test_ergoai_parse_failure_remains_unverified() -> None:
    result = gate_ergoai_proposal(
        _GARBAGE_BODY,
        request_id="req:ergo:bad",
        source_ref_ids=("source:fixture:bad:1",),
        confidence=1.0,
        available=True,
        candidate_id="cand:ergo:bad",
    )
    assert result.disposition is AdvisorGateDisposition.PARSE_FAILED
    assert result.parse_ok is False
    assert result.evidence.authority == UNVERIFIED_AUTHORITY
    assert result.evidence.parse_correctness_established is False
    assert result.evidence.proof_established is False
    assert result.is_proved is False


def test_ergoai_feature_mismatch() -> None:
    result = gate_ergoai_proposal(
        _FLOGIC_BODY,
        request_id="req:ergo:feat",
        source_ref_ids=("source:fixture:flogic:1",),
        features=("flogic", "nonexistent_feature_xyz"),
        candidate_id="cand:ergo:feat",
    )
    assert result.disposition is AdvisorGateDisposition.FEATURE_MISMATCH
    assert result.evidence.reparse.parse_ok is True
    assert result.evidence.reparse.features_ok is False
    assert "nonexistent_feature_xyz" in result.evidence.reparse.missing_features
    assert result.evidence.parse_correctness_established is False
    assert result.evidence.authority == UNVERIFIED_AUTHORITY


# ---------------------------------------------------------------------------
# SymbolicAI deterministic reparse
# ---------------------------------------------------------------------------


def test_symbolicai_smtlib_typed_unverified_candidate() -> None:
    result = gate_symbolicai_proposal(
        _SMTLIB_BODY,
        request_id="req:symai:smt",
        source_ref_ids=("source:fixture:smt:1",),
        notation=AdvisorNotation.SMTLIB2,
        features=("smtlib2",),
        confidence=0.95,
        fluent_text="Fluent natural language claiming satisfiability.",
        available=True,
        candidate_id="cand:symai:smt",
    )
    assert result.disposition is AdvisorGateDisposition.TYPED_CANDIDATE
    assert result.parse_ok is True
    assert result.evidence.provider in {
        AdvisorProviderKind.SYMBOLICAI,
        AdvisorProviderKind.SYMAI,
    }
    assert result.evidence.authority == UNVERIFIED_AUTHORITY
    assert result.evidence.parse_correctness_established is True
    assert result.evidence.satisfiability_established is False
    assert result.evidence.policy_established is False
    assert result.evidence.proof_established is False
    assert result.typed_document is not None


def test_symbolicai_parse_failure_stays_unverified() -> None:
    result = gate_symbolicai_proposal(
        _GARBAGE_BODY,
        request_id="req:symai:bad",
        source_ref_ids=("source:fixture:bad:2",),
        notation=AdvisorNotation.SMTLIB2,
        confidence=1.0,
        available=True,
        candidate_id="cand:symai:bad",
    )
    assert result.disposition is AdvisorGateDisposition.PARSE_FAILED
    assert result.evidence.authority == UNVERIFIED_AUTHORITY
    assert result.evidence.parse_correctness_established is False
    assert result.is_proved is False


def test_symbolicai_flogic_shares_frame_frontend() -> None:
    result = gate_symbolicai_proposal(
        _FLOGIC_BODY,
        request_id="req:symai:flogic",
        source_ref_ids=("source:fixture:flogic:2",),
        notation=AdvisorNotation.FLOGIC,
        features=("flogic",),
        candidate_id="cand:symai:flogic",
        provider=AdvisorProviderKind.SYMAI,
    )
    assert result.disposition is AdvisorGateDisposition.TYPED_CANDIDATE
    assert result.evidence.reparse.parser_interface == FLOGIC_FRONTEND_V2_INTERFACE
    assert result.evidence.provider is AdvisorProviderKind.SYMAI
    assert result.evidence.authority == UNVERIFIED_AUTHORITY


def test_gate_from_proposal_candidate() -> None:
    candidate = ProposalCandidate(
        candidate_id="cand:from-proposal",
        kind=ProposalKind.SPECIFICATION,
        body=_SMTLIB_BODY,
        source_ref_ids=("source:fixture:smt:2",),
        provider=ProposalProvider.SYMAI,
        confidence=0.88,
    )
    result = AdvisorExecutionGateV2().gate_proposal_candidate(
        candidate,
        request_id="req:from-proposal",
        notation=AdvisorNotation.SMTLIB2,
        features=("smtlib2",),
    )
    assert result.disposition is AdvisorGateDisposition.TYPED_CANDIDATE
    assert result.evidence.candidate_id == "cand:from-proposal"
    assert result.evidence.confidence == 0.88
    assert result.evidence.remains_unverified_candidate is True


# ---------------------------------------------------------------------------
# Non-deterministic signals cannot establish claims
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("claim", list(AdvisorClaimKind))
def test_non_deterministic_signals_never_establish_claims(
    claim: AdvisorClaimKind,
) -> None:
    assert (
        non_deterministic_signal_establishes(
            claim,
            confidence=1.0,
            fluent_text="This is a fluent, confident proof of everything.",
            available=True,
            mock_output={"status": "proved", "sat": "sat"},
            is_valid=True,
            similarity=1.0,
        )
        is False
    )


def test_confidence_fluent_availability_do_not_establish_on_evidence() -> None:
    result = gate_advisor_proposal(_ergo_request())
    evidence = result.evidence
    assert evidence.confidence == 0.99
    assert evidence.fluent_text_present is True
    assert evidence.available is True
    for claim in AdvisorClaimKind:
        assert evidence.non_deterministic_claim(claim) is False
    # Deterministic reparse may establish parse correctness only.
    assert evidence.claim_established(AdvisorClaimKind.PARSE_CORRECTNESS) is True
    assert evidence.claim_established(AdvisorClaimKind.SATISFIABILITY) is False
    assert evidence.claim_established(AdvisorClaimKind.POLICY) is False
    assert evidence.claim_established(AdvisorClaimKind.PROOF) is False
    assert advisor_never_establishes_proof(
        confidence=1.0,
        fluent_text="proved",
        available=True,
        mock_output={"ok": True},
        parse_ok=True,
        independently_validated=True,
    ) is False


def test_mock_output_rejected_and_never_establishes_claims() -> None:
    result = gate_ergoai_proposal(
        _FLOGIC_BODY,
        request_id="req:ergo:mock",
        source_ref_ids=("source:fixture:flogic:1",),
        features=("flogic", "frame"),
        confidence=1.0,
        available=True,
        mock_output={
            "parse_ok": True,
            "status": "proved",
            "satisfiable": True,
            "authorized": True,
        },
        candidate_id="cand:ergo:mock",
    )
    assert result.disposition is AdvisorGateDisposition.MOCK_REJECTED
    assert result.parse_ok is False
    assert result.evidence.mock_output_present is True
    assert result.evidence.parse_correctness_established is False
    assert result.evidence.satisfiability_established is False
    assert result.evidence.policy_established is False
    assert result.evidence.proof_established is False
    assert result.evidence.authority == UNVERIFIED_AUTHORITY
    wire = result.evidence.to_dict()
    assert wire["claim_parse_correctness"] is False
    assert wire["claim_satisfiability"] is False
    assert wire["claim_policy"] is False
    assert wire["claim_proof"] is False
    assert wire["is_proved"] is False
    assert wire["remains_unverified_candidate"] is True


def test_availability_alone_never_parses() -> None:
    result = gate_symbolicai_proposal(
        _GARBAGE_BODY,
        request_id="req:symai:avail",
        source_ref_ids=("source:fixture:bad:3",),
        notation=AdvisorNotation.SMTLIB2,
        available=True,
        confidence=0.0,
        candidate_id="cand:symai:avail",
    )
    assert result.evidence.available is True
    assert result.evidence.parse_correctness_established is False
    assert result.disposition is AdvisorGateDisposition.PARSE_FAILED


def test_fluent_text_alone_never_parses() -> None:
    result = gate_symbolicai_proposal(
        "just some natural language about a theorem being true",
        request_id="req:symai:fluent",
        source_ref_ids=("source:fixture:nl:1",),
        notation=AdvisorNotation.SMTLIB2,
        fluent_text="The formula is satisfiable and the policy authorizes access.",
        confidence=0.99,
        candidate_id="cand:symai:fluent",
    )
    assert result.evidence.fluent_text_present is True
    assert result.evidence.parse_correctness_established is False
    assert result.evidence.satisfiability_established is False
    assert result.evidence.policy_established is False
    assert result.evidence.proof_established is False


# ---------------------------------------------------------------------------
# Authority ceiling hard rules
# ---------------------------------------------------------------------------


def test_cannot_construct_evidence_with_theorem_authority() -> None:
    reparse = AdvisorReparseRecord(
        disposition=AdvisorGateDisposition.TYPED_CANDIDATE,
        parse_ok=True,
        type_ok=True,
        signature_ok=True,
        features_ok=True,
    )
    with pytest.raises(AdvisorAuthorityError):
        AdvisorProviderEvidenceV2(
            evidence_id="ev:bad",
            request_id="req:bad",
            request_digest="0" * 64,
            provider=AdvisorProviderKind.ERGOAI,
            reparse=reparse,
            candidate_id="cand:bad",
            source_ref_ids=("source:1",),
            source_digest="1" * 64,
            authority="theorem",
        )


def test_cannot_construct_evidence_with_satisfiability_result_authority() -> None:
    reparse = AdvisorReparseRecord(
        disposition=AdvisorGateDisposition.TYPED_CANDIDATE,
        parse_ok=True,
        type_ok=True,
        signature_ok=True,
        features_ok=True,
    )
    with pytest.raises(AdvisorAuthorityError):
        AdvisorProviderEvidenceV2(
            evidence_id="ev:bad2",
            request_id="req:bad2",
            request_digest="0" * 64,
            provider=AdvisorProviderKind.SYMBOLICAI,
            reparse=reparse,
            candidate_id="cand:bad2",
            source_ref_ids=("source:1",),
            source_digest="1" * 64,
            result_authority=ResultAuthority.SATISFIABILITY,
        )


def test_wire_dict_preserves_unverified_flags() -> None:
    result = gate_advisor_proposal(_symai_request())
    wire = result.to_dict()
    assert wire["interface"] == "AdvisorExecutionResult@2"
    assert wire["remains_unverified_candidate"] is True
    assert wire["is_proved"] is False
    assert wire["evidence"]["interface"] == ADVISOR_PROVIDER_EVIDENCE_V2_INTERFACE
    assert wire["evidence"]["authority"] == UNVERIFIED_AUTHORITY
    assert wire["evidence"]["result_authority"] == ResultAuthority.CANDIDATE.value
    assert wire["evidence"]["claim_proof"] is False
    assert wire["evidence"]["claim_satisfiability"] is False
    assert wire["evidence"]["claim_policy"] is False


def test_independent_validation_still_not_proof() -> None:
    result = gate_ergoai_proposal(
        _FLOGIC_BODY,
        request_id="req:ergo:validated",
        source_ref_ids=("source:fixture:flogic:1",),
        features=("flogic", "frame"),
        independently_validated=True,
        candidate_id="cand:ergo:validated",
    )
    assert result.disposition is AdvisorGateDisposition.TYPED_CANDIDATE
    assert result.evidence.independently_validated is True
    assert result.evidence.acceptance is not None
    assert result.evidence.acceptance.accepted is True
    # Even admitted candidates are not proofs.
    assert result.evidence.proof_established is False
    assert result.evidence.is_proved is False
    assert result.evidence.authority == UNVERIFIED_AUTHORITY
    assert result.evidence.acceptance.authority == "candidate_admitted_for_validation"


def test_empty_source_disposition() -> None:
    result = gate_ergoai_proposal(
        "",
        request_id="req:ergo:empty",
        source_ref_ids=("source:fixture:empty:1",),
        candidate_id="cand:ergo:empty",
    )
    assert result.disposition is AdvisorGateDisposition.EMPTY_SOURCE
    assert result.evidence.parse_correctness_established is False
    assert result.evidence.authority == UNVERIFIED_AUTHORITY


def test_request_round_trip_dict() -> None:
    request = _symai_request()
    restored = AdvisorExecutionRequestV2.from_dict(request.to_dict())
    assert restored.request_id == request.request_id
    assert restored.provider is request.provider
    assert restored.proposed_source == request.proposed_source
    assert restored.source_ref_ids == request.source_ref_ids
    assert restored.features == request.features
