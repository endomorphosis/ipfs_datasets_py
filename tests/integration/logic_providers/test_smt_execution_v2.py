"""Integration tests: typed Z3 / cvc5 SMT/CHC execution + replay (LFP2-028).

Acceptance (fail-closed):

* Solver disagreement is a typed outcome (never majority-voted success).
* Unsupported theory and unsupported proof features are typed outcomes.
* Success is never promoted beyond the evidence receipt.
* Mock / fallback / availability / confidence never establish satisfiability,
  theorem, or proof authority.
* Models and unsat cores bind when produced; proofs remain unsupported.
* Hermetic fixture and differential paths agree on reviewed obligations.

Interfaces: SMTProviderEvidence@2
"""

from __future__ import annotations

import pytest

from ipfs_datasets_py.logic.backends.results import ResultAuthority, ResultStatus
from ipfs_datasets_py.logic.backends.smt.compiler import (
    BOOL_SORT,
    INT_SORT,
    HornClause,
    SmtFunDecl,
    SmtNamedAssertion,
    SmtObligation,
    SmtQueryMode,
    SmtTerm,
    SmtTermKind,
    term_apply,
    term_eq,
    term_false,
    term_int,
    term_symbol,
    term_true,
)
from ipfs_datasets_py.logic.backends.smt.differential import (
    DifferentialClassification,
)
from ipfs_datasets_py.logic.backends.smt.execution_v2 import (
    SMT_EXECUTION_V2_TASK_ID,
    SMT_PROVIDER_EVIDENCE_V2_INTERFACE,
    SmtAuthorityError,
    SmtClaimKind,
    SmtDisposition,
    SmtExecutionEngineV2,
    SmtExecutionError,
    SmtExecutionMode,
    SmtExecutionRequestV2,
    SmtProviderEvidenceV2,
    SmtProviderKind,
    SmtReplayReceiptV2,
    execute_cvc5,
    execute_differential,
    execute_smt,
    execute_z3,
    hermetic_engine,
    mock_or_fallback_establishes_satisfiability,
    non_authoritative_signal_establishes,
    normalize_smt_provider,
)
from ipfs_datasets_py.logic.backends.toolchain_roles import (
    ToolRole,
    ToolchainAuthorityCeiling,
)
from ipfs_datasets_py.logic.families.models import EvidenceAuthority


# ---------------------------------------------------------------------------
# Compact obligation recipes
# ---------------------------------------------------------------------------


def _arith_vc_obligation() -> SmtObligation:
    """Reviewed fixture: x >= 1 entails x > 0 (theorem-by-negation + core)."""

    x = term_symbol("x")
    return SmtObligation(
        obligation_id="obl:vc-x-positive",
        query_mode=SmtQueryMode.THEOREM_BY_NEGATION,
        features=("arithmetic", "equality", "verification_conditions"),
        goal=SmtTerm(SmtTermKind.GT, arguments=(x, term_int(0))),
        assumptions=(
            SmtNamedAssertion(
                formula=SmtTerm(SmtTermKind.GE, arguments=(x, term_int(1))),
                name="assume_ge_one",
            ),
        ),
        functions=(SmtFunDecl(name="x", range=INT_SORT, is_const=True),),
        request_unsat_core=True,
        property_ids=("property:vc-x-positive",),
    )


def _sat_bool_obligation() -> SmtObligation:
    return SmtObligation(
        obligation_id="obl:sat-p-true",
        query_mode=SmtQueryMode.SATISFIABILITY,
        features=("equality",),
        goal=term_eq(term_symbol("p"), term_true()),
        functions=(SmtFunDecl("p", range=BOOL_SORT, is_const=True),),
        request_model=True,
    )


def _unsupported_theory_mapping() -> dict[str, object]:
    """Obligation mapping that declares a hard-unsupported theory feature."""

    return {
        "obligation_id": "obl:temporal-unsupported",
        "query_mode": "satisfiability",
        "features": ("temporal", "equality"),
        "goal": {"kind": "true", "arguments": [], "name": "", "value": None},
        "functions": [],
        "assumptions": [],
        "request_model": False,
        "request_unsat_core": False,
    }


def _vc_request(**overrides: object) -> SmtExecutionRequestV2:
    payload: dict[str, object] = {
        "request_id": "req:smt:vc:1",
        "obligation": _arith_vc_obligation(),
        "provider": SmtProviderKind.DIFFERENTIAL,
        "mode": SmtExecutionMode.HERMETIC_FIXTURE,
        "source_ref_ids": ("source:fixture:smt:vc-x-positive",),
        "available": True,
        "confidence": 0.99,
        "fluent_text": "Obviously this VC is proved by Z3 and cvc5.",
    }
    payload.update(overrides)
    return SmtExecutionRequestV2(**payload)  # type: ignore[arg-type]


def _agree_proved_engine() -> SmtExecutionEngineV2:
    return hermetic_engine(
        z3_stdout="unsat\n(assume_ge_one)\n",
        cvc5_stdout="unsat\n(assume_ge_one)\n",
        z3_kwargs={"solver_version": "z3-hermetic"},
        cvc5_kwargs={"solver_version": "cvc5-hermetic"},
    )


def _agree_sat_engine() -> SmtExecutionEngineV2:
    model = "sat\n(\n(define-fun p () Bool true)\n)\n"
    return hermetic_engine(
        z3_stdout=model,
        cvc5_stdout=model,
        z3_kwargs={"solver_version": "z3-hermetic"},
        cvc5_kwargs={"solver_version": "cvc5-hermetic"},
    )


def _disagree_engine() -> SmtExecutionEngineV2:
    return hermetic_engine(
        z3_stdout="unsat\n",
        cvc5_stdout="sat\n(\n(define-fun x () Int 0)\n)\n",
    )


# ---------------------------------------------------------------------------
# Interface / typing surface
# ---------------------------------------------------------------------------


def test_interface_identities() -> None:
    engine = SmtExecutionEngineV2()
    assert engine.INTERFACE == SMT_PROVIDER_EVIDENCE_V2_INTERFACE
    assert engine.interface == "SMTProviderEvidence@2"
    assert engine.TASK_ID == SMT_EXECUTION_V2_TASK_ID
    assert engine.TASK_ID == "LFP2-028"
    assert SmtExecutionRequestV2.interface == "SmtExecutionRequest@2"
    assert SmtProviderEvidenceV2.interface == "SMTProviderEvidence@2"


def test_provider_normalization() -> None:
    assert normalize_smt_provider("z3") is SmtProviderKind.Z3
    assert normalize_smt_provider("cvc5") is SmtProviderKind.CVC5
    assert normalize_smt_provider("z3-cvc5") is SmtProviderKind.DIFFERENTIAL
    assert normalize_smt_provider(SmtProviderKind.Z3) is SmtProviderKind.Z3
    with pytest.raises(SmtExecutionError):
        normalize_smt_provider("vampire")
    with pytest.raises(SmtExecutionError):
        normalize_smt_provider("lean")


# ---------------------------------------------------------------------------
# Hermetic conclusive execution + artifacts + replay
# ---------------------------------------------------------------------------


def test_differential_agree_proved_binds_core_and_replay() -> None:
    engine = _agree_proved_engine()
    result = engine.execute(_vc_request())
    evidence = result.evidence

    assert evidence.interface == SMT_PROVIDER_EVIDENCE_V2_INTERFACE
    assert evidence.disposition is SmtDisposition.PROVED
    assert evidence.result_status is ResultStatus.PROVED
    assert evidence.result_authority is ResultAuthority.THEOREM
    assert evidence.authority_ceiling is ToolchainAuthorityCeiling.SATISFIABILITY
    assert evidence.role is ToolRole.AUTHORITY
    assert evidence.translation_ceiling is EvidenceAuthority.BOUNDED
    assert evidence.theorem_established is True
    assert evidence.satisfiability_established is True
    assert evidence.proof_established is False
    assert evidence.is_proved is True
    assert evidence.is_conclusive is True
    assert evidence.script_digest
    assert evidence.compilation_id
    assert evidence.translation_receipt_id
    assert evidence.unsat_core is not None
    assert evidence.unsat_core.present is True
    assert "assume_ge_one" in evidence.unsat_core.atoms
    assert evidence.differential is not None
    assert evidence.differential.agreement is True
    assert (
        evidence.differential.classification
        is DifferentialClassification.AGREE_PROVED
    )
    assert evidence.replay is not None
    assert evidence.replay.matched is True
    assert evidence.replay.replay_claimed is True
    wire = evidence.to_dict()
    assert wire["claim_theorem"] is True
    assert wire["claim_proof"] is False
    assert wire["is_proved"] is True
    assert "success_never_promoted_beyond_evidence_receipt" in wire["diagnostics"]


def test_differential_agree_sat_binds_model() -> None:
    engine = _agree_sat_engine()
    result = execute_smt(
        _sat_bool_obligation(),
        request_id="req:smt:sat:1",
        provider=SmtProviderKind.DIFFERENTIAL,
        engine=engine,
        source_ref_ids=("source:fixture:smt:sat-p",),
    )
    evidence = result.evidence
    assert evidence.disposition is SmtDisposition.SATISFIABLE
    assert evidence.result_status is ResultStatus.SATISFIABLE
    assert evidence.result_authority is ResultAuthority.SATISFIABILITY
    assert evidence.satisfiability_established is True
    assert evidence.theorem_established is False
    assert evidence.proof_established is False
    assert evidence.model is not None
    assert evidence.model.present is True
    assert "define-fun" in evidence.model.text_excerpt
    assert evidence.differential is not None
    assert (
        evidence.differential.classification
        is DifferentialClassification.AGREE_SATISFIABLE
    )


def test_single_solver_z3_and_cvc5_paths() -> None:
    engine = _agree_proved_engine()
    z3_result = execute_z3(
        _arith_vc_obligation(),
        request_id="req:smt:z3:1",
        engine=engine,
        source_ref_ids=("source:fixture:smt:z3",),
    )
    assert z3_result.evidence.provider is SmtProviderKind.Z3
    assert z3_result.evidence.disposition is SmtDisposition.PROVED
    assert z3_result.evidence.solver_backend_id == "z3"
    assert z3_result.evidence.differential is None

    cvc5_result = execute_cvc5(
        _arith_vc_obligation(),
        request_id="req:smt:cvc5:1",
        engine=engine,
        source_ref_ids=("source:fixture:smt:cvc5",),
    )
    assert cvc5_result.evidence.provider is SmtProviderKind.CVC5
    assert cvc5_result.evidence.disposition is SmtDisposition.PROVED
    assert cvc5_result.evidence.solver_backend_id == "cvc5"


def test_engine_replay_matches_hermetic_outcome() -> None:
    engine = _agree_proved_engine()
    result = engine.execute(_vc_request(request_id="req:smt:replay:1"))
    replay = engine.replay(result)
    assert isinstance(replay, SmtReplayReceiptV2)
    assert replay.matched is True
    assert replay.replay_claimed is True
    assert replay.original_disposition is SmtDisposition.PROVED
    assert replay.replayed_disposition is SmtDisposition.PROVED
    assert replay.obligation_digest == result.evidence.obligation_digest


# ---------------------------------------------------------------------------
# Typed non-success outcomes
# ---------------------------------------------------------------------------


def test_solver_disagreement_is_typed_not_success() -> None:
    engine = _disagree_engine()
    result = engine.execute(_vc_request(request_id="req:smt:disagree:1"))
    evidence = result.evidence
    assert evidence.disposition is SmtDisposition.SOLVER_DISAGREEMENT
    assert evidence.result_status is ResultStatus.UNKNOWN
    assert evidence.satisfiability_established is False
    assert evidence.theorem_established is False
    assert evidence.proof_established is False
    assert evidence.is_proved is False
    assert evidence.differential is not None
    assert evidence.differential.agreement is False
    assert (
        evidence.differential.classification is DifferentialClassification.DISAGREE
    )
    assert evidence.differential.disagreement_preserved is True
    assert "solver_disagreement_typed_outcome" in evidence.diagnostics
    assert "disagreement_never_majority_voted" in evidence.diagnostics


def test_unsupported_theory_is_typed_outcome() -> None:
    engine = _agree_proved_engine()
    result = engine.execute(
        SmtExecutionRequestV2(
            request_id="req:smt:theory:1",
            obligation=_unsupported_theory_mapping(),
            provider=SmtProviderKind.DIFFERENTIAL,
            mode=SmtExecutionMode.HERMETIC_FIXTURE,
            source_ref_ids=("source:fixture:smt:temporal",),
        )
    )
    evidence = result.evidence
    assert evidence.disposition is SmtDisposition.UNSUPPORTED_THEORY
    assert evidence.result_status is ResultStatus.UNSUPPORTED
    assert evidence.satisfiability_established is False
    assert evidence.theorem_established is False
    assert any(item.startswith("unsupported_theory:") for item in evidence.diagnostics)


def test_unsupported_proof_feature_is_typed_outcome() -> None:
    engine = _agree_proved_engine()
    result = engine.execute(
        _vc_request(request_id="req:smt:proof:1", request_proof=True)
    )
    evidence = result.evidence
    assert evidence.disposition is SmtDisposition.UNSUPPORTED_PROOF_FEATURE
    assert evidence.result_status is ResultStatus.UNSUPPORTED
    assert evidence.proof_established is False
    assert evidence.theorem_established is False
    assert evidence.proof is not None
    assert evidence.proof.supported is False
    assert evidence.proof.present is False
    assert any(
        "unsupported_proof_feature" in item for item in evidence.diagnostics
    )


def test_partial_unavailability_is_typed() -> None:
    engine = hermetic_engine(
        z3_stdout="unsat\n(assume_ge_one)\n",
        cvc5_stdout="",
        cvc5_kwargs={"unavailable": True, "stderr": "cvc5 missing"},
    )
    result = engine.execute(_vc_request(request_id="req:smt:partial:1"))
    evidence = result.evidence
    assert evidence.disposition is SmtDisposition.PARTIAL_UNAVAILABLE
    assert evidence.satisfiability_established is False
    assert evidence.theorem_established is False
    assert evidence.differential is not None
    assert (
        evidence.differential.classification
        is DifferentialClassification.PARTIAL_UNAVAILABLE
    )


def test_timeout_and_malformed_are_typed() -> None:
    timeout_engine = hermetic_engine(
        z3_stdout="",
        cvc5_stdout="",
        z3_kwargs={"timed_out": True, "elapsed_ms": 5_000},
        cvc5_kwargs={"timed_out": True, "elapsed_ms": 5_000},
    )
    timed = timeout_engine.execute(
        _vc_request(
            request_id="req:smt:timeout:1",
            provider=SmtProviderKind.Z3,
        )
    )
    assert timed.evidence.disposition is SmtDisposition.TIMEOUT
    assert timed.evidence.result_status is ResultStatus.TIMEOUT
    assert timed.evidence.bounds_exhausted is True
    assert timed.evidence.theorem_established is False

    malformed_engine = hermetic_engine(
        z3_stdout="sat\nunsat\n",
        cvc5_stdout="sat\nunsat\n",
    )
    bad = malformed_engine.execute(
        _vc_request(
            request_id="req:smt:malformed:1",
            provider=SmtProviderKind.Z3,
        )
    )
    assert bad.evidence.disposition is SmtDisposition.MALFORMED
    assert bad.evidence.result_status is ResultStatus.MALFORMED


# ---------------------------------------------------------------------------
# Authority fail-closed: mock / fallback / signals never promote
# ---------------------------------------------------------------------------


def test_mock_output_cannot_establish_authority() -> None:
    engine = _agree_proved_engine()
    result = engine.execute(
        _vc_request(
            request_id="req:smt:mock:1",
            mock_output={"status": "proved", "verdict": "unsat"},
            confidence=1.0,
            available=True,
            fluent_text="Mock claims this is proved.",
        )
    )
    evidence = result.evidence
    assert evidence.disposition is SmtDisposition.MOCK_REJECTED
    assert evidence.satisfiability_established is False
    assert evidence.theorem_established is False
    assert evidence.proof_established is False
    assert evidence.is_proved is False
    assert evidence.mock_output_present is True
    assert mock_or_fallback_establishes_satisfiability(
        mock_output={"status": "proved"}, available=True
    ) is False
    assert non_authoritative_signal_establishes(
        SmtClaimKind.THEOREM,
        mock_output={"ok": True},
        confidence=1.0,
        fluent_text="proved",
        available=True,
    ) is False


def test_fallback_output_cannot_establish_authority() -> None:
    engine = _agree_proved_engine()
    result = engine.execute(
        _vc_request(
            request_id="req:smt:fallback:1",
            fallback_output={"status": "sat"},
            mode=SmtExecutionMode.FALLBACK,
        )
    )
    evidence = result.evidence
    assert evidence.disposition is SmtDisposition.FALLBACK_REJECTED
    assert evidence.satisfiability_established is False
    assert evidence.theorem_established is False
    assert evidence.fallback_output_present is True


def test_evidence_rejects_authority_promotion_beyond_receipt() -> None:
    """Constructing evidence that claims theorem without proved disposition fails."""

    with pytest.raises(SmtAuthorityError):
        SmtProviderEvidenceV2(
            evidence_id="ev:smt:bad:1",
            request_id="req:smt:bad:1",
            request_digest="a" * 64,
            provider=SmtProviderKind.Z3,
            disposition=SmtDisposition.UNKNOWN,
            mode=SmtExecutionMode.HERMETIC_FIXTURE,
            query_mode=SmtQueryMode.THEOREM_BY_NEGATION,
            obligation_digest="b" * 64,
            theorem_established=True,
            satisfiability_established=False,
        )

    with pytest.raises(SmtAuthorityError):
        SmtProviderEvidenceV2(
            evidence_id="ev:smt:bad:2",
            request_id="req:smt:bad:2",
            request_digest="a" * 64,
            provider=SmtProviderKind.Z3,
            disposition=SmtDisposition.SOLVER_DISAGREEMENT,
            mode=SmtExecutionMode.HERMETIC_FIXTURE,
            query_mode=SmtQueryMode.SATISFIABILITY,
            obligation_digest="b" * 64,
            satisfiability_established=True,
        )

    with pytest.raises(SmtAuthorityError):
        SmtProviderEvidenceV2(
            evidence_id="ev:smt:bad:3",
            request_id="req:smt:bad:3",
            request_digest="a" * 64,
            provider=SmtProviderKind.Z3,
            disposition=SmtDisposition.PROVED,
            mode=SmtExecutionMode.MOCK,
            query_mode=SmtQueryMode.THEOREM_BY_NEGATION,
            obligation_digest="b" * 64,
            theorem_established=True,
            mock_output_present=True,
        )


def test_metadata_rejects_free_form_authority_keys() -> None:
    with pytest.raises(SmtAuthorityError):
        SmtExecutionRequestV2(
            request_id="req:smt:meta:1",
            obligation=_sat_bool_obligation(),
            metadata={"claimed_proof": True},
        )


def test_availability_and_confidence_do_not_establish_claims() -> None:
    assert non_authoritative_signal_establishes(
        SmtClaimKind.SATISFIABILITY, available=True, confidence=1.0
    ) is False
    assert non_authoritative_signal_establishes(
        SmtClaimKind.PROOF, available=True, fluent_text="proved"
    ) is False
    # Even when solvers agree, absence of authoritative mode is rejected at
    # the request layer via mock/fallback; availability alone is inert.
    engine = _agree_proved_engine()
    result = engine.execute(
        _vc_request(
            request_id="req:smt:avail:1",
            available=False,
            confidence=0.0,
        )
    )
    # Hermetic runners still execute; availability flag is recorded only.
    assert result.evidence.available is False
    assert result.evidence.theorem_established is True
    assert result.evidence.disposition is SmtDisposition.PROVED


# ---------------------------------------------------------------------------
# Wire / digest stability
# ---------------------------------------------------------------------------


def test_request_and_result_wire_shapes() -> None:
    engine = _agree_proved_engine()
    result = engine.execute(_vc_request(request_id="req:smt:wire:1"))
    request_wire = result.request.to_dict()
    assert request_wire["interface"] == "SmtExecutionRequest@2"
    assert "obligation" in request_wire
    assert request_wire["provider"] == "differential"

    result_wire = result.to_dict()
    assert result_wire["interface"] == "SmtExecutionResult@2"
    assert result_wire["evidence"]["interface"] == "SMTProviderEvidence@2"
    assert result_wire["evidence"]["content_digest"]
    assert result.evidence.content_digest == result_wire["evidence"]["content_digest"]


def test_execute_differential_helper() -> None:
    engine = _agree_proved_engine()
    result = execute_differential(
        _arith_vc_obligation(),
        request_id="req:smt:helper:1",
        engine=engine,
    )
    assert result.evidence.provider is SmtProviderKind.DIFFERENTIAL
    assert result.evidence.disposition is SmtDisposition.PROVED
    assert result.differential_report is not None
    assert result.differential_report.agreement is True


def test_chc_fixed_point_obligation_executes_hermetically() -> None:
    """CHC reachability is a first-class query mode under SMTProviderEvidence@2."""

    n = term_symbol("n")
    obligation = SmtObligation(
        obligation_id="obl:horn-reach",
        query_mode=SmtQueryMode.FIXED_POINT,
        features=("horn_chc_reachability", "arithmetic"),
        horn_clauses=(
            HornClause("c:init", head=term_apply("Inv", term_int(0))),
            HornClause(
                "c:step",
                head=term_apply(
                    "Inv",
                    SmtTerm(SmtTermKind.ADD, arguments=(n, term_int(1))),
                ),
                body=(term_apply("Inv", n),),
            ),
            HornClause(
                "c:query",
                head=term_false(),
                body=(
                    term_apply("Inv", n),
                    SmtTerm(SmtTermKind.LT, arguments=(n, term_int(0))),
                ),
                is_query=True,
            ),
        ),
        functions=(
            SmtFunDecl("Inv", domain=(INT_SORT,), range=BOOL_SORT),
            SmtFunDecl("n", range=INT_SORT, is_const=True),
        ),
    )
    engine = hermetic_engine(
        z3_stdout="unsat\n",
        cvc5_stdout="unsat\n",
    )
    result = engine.execute(
        SmtExecutionRequestV2(
            request_id="req:smt:chc:1",
            obligation=obligation,
            provider=SmtProviderKind.DIFFERENTIAL,
            mode=SmtExecutionMode.HERMETIC_FIXTURE,
            source_ref_ids=("source:fixture:smt:chc",),
        )
    )
    evidence = result.evidence
    assert evidence.query_mode is SmtQueryMode.FIXED_POINT
    assert evidence.disposition is SmtDisposition.UNSATISFIABLE
    assert evidence.satisfiability_established is True
    assert evidence.theorem_established is False
    assert evidence.proof_established is False
    assert evidence.result_authority is ResultAuthority.SATISFIABILITY
    assert evidence.script_digest
    assert evidence.differential is not None
    assert evidence.differential.agreement is True
