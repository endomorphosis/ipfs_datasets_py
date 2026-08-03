"""Integration tests for untrusted Leanstral/SymAI proposal advisors (LFV-G061).

Covers:
* LeanstralAdvisor@1 and SymAIAdvisor@1 interfaces
* specification / lemma / tactic / premise / repair proposal kinds
* bounded, sanitized, source-bound, inert prompts and responses
* confidence / is_valid / similarity never yield proof
* acceptance requires deterministic compilation + independent validation
* prover_router no longer elevates bare is_valid or untrusted providers
* reasoning_coordinator neural/hybrid paths never prove from confidence
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from ipfs_datasets_py.logic.external_provers.prover_router import (
    ProverRouter,
    SyntacticProofResult,
)
from ipfs_datasets_py.logic.formalization.proposal_advisors import (
    LEANSTRAL_ADVISOR_INTERFACE,
    SYMAI_ADVISOR_INTERFACE,
    UNVERIFIED_AUTHORITY,
    LeanstralAdvisor,
    LeanstralProposalAdvisor,
    ProposalAcceptance,
    ProposalAdvisorConfig,
    ProposalAdvisorRequest,
    ProposalAdvisorValidationError,
    ProposalCandidate,
    ProposalKind,
    ProposalProvider,
    StaticProposalModel,
    SymAIAdvisor,
    SymAIProposalAdvisor,
    accept_candidate,
    build_json_candidates_response,
    confidence_never_yields_proof,
    is_untrusted_proposal_provider,
    sanitize_inert_text,
)
from ipfs_datasets_py.logic.integration.symbolic.neurosymbolic.reasoning_coordinator import (
    CoordinatedResult,
    NeuralSymbolicCoordinator,
    ReasoningStrategy,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _request(
    kind: ProposalKind = ProposalKind.LEMMA,
    **overrides: Any,
) -> ProposalAdvisorRequest:
    payload: dict[str, Any] = {
        "request_id": "req:lemma-1",
        "goal_id": "goal:swap-correct",
        "logic_family": "hoare",
        "kind": kind,
        "source_ref_ids": ("source:module.py", "source:spec.md"),
        "context_text": "Prove that swap preserves the multiset of elements.",
        "goal_text": "forall xs, permute (swap xs) xs",
        "formula_id": "formula:swap",
        "notes": "proposal only",
    }
    payload.update(overrides)
    return ProposalAdvisorRequest(**payload)


def _candidate_record(
    *,
    provider: str,
    kind: str = "lemma",
    candidate_id: str = "cand:1",
    confidence: float = 0.99,
) -> dict[str, Any]:
    return {
        "candidate_id": candidate_id,
        "kind": kind,
        "body": "lemma swap_preserves : forall xs, permute (swap xs) xs",
        "source_ref_ids": ["source:module.py", "source:spec.md"],
        "provider": provider,
        "confidence": confidence,
        "rationale": "pattern match on swap definition",
    }


# ---------------------------------------------------------------------------
# Interface and contract surface
# ---------------------------------------------------------------------------


def test_interfaces_are_versioned() -> None:
    assert LEANSTRAL_ADVISOR_INTERFACE == "LeanstralAdvisor@1"
    assert SYMAI_ADVISOR_INTERFACE == "SymAIAdvisor@1"
    leanstral = LeanstralProposalAdvisor(
        StaticProposalModel(
            build_json_candidates_response(
                [_candidate_record(provider="leanstral")]
            )
        )
    )
    symai = SymAIProposalAdvisor(
        StaticProposalModel(
            build_json_candidates_response(
                [_candidate_record(provider="symai")]
            )
        )
    )
    assert isinstance(leanstral, LeanstralAdvisor)
    assert isinstance(symai, SymAIAdvisor)
    assert leanstral.config.interface_id == LEANSTRAL_ADVISOR_INTERFACE
    assert symai.config.interface_id == SYMAI_ADVISOR_INTERFACE


@pytest.mark.parametrize(
    "kind",
    [
        ProposalKind.SPECIFICATION,
        ProposalKind.LEMMA,
        ProposalKind.TACTIC,
        ProposalKind.PREMISE,
        ProposalKind.REPAIR,
    ],
)
def test_all_proposal_kinds_supported(kind: ProposalKind) -> None:
    body = {
        ProposalKind.SPECIFICATION: "requires xs.length > 0 ensures result.sorted",
        ProposalKind.LEMMA: "lemma len_nonneg : forall xs, length xs >= 0",
        ProposalKind.TACTIC: "apply Nat.le_refl",
        ProposalKind.PREMISE: "axiom: list permutation is equivalence",
        ProposalKind.REPAIR: "replace /goal/quantifier with forall",
    }[kind]
    response = build_json_candidates_response(
        [
            {
                "candidate_id": f"cand:{kind.value}",
                "kind": kind.value,
                "body": body,
                "source_ref_ids": ["source:module.py", "source:spec.md"],
                "provider": "leanstral",
                "confidence": 0.5,
            }
        ]
    )
    advisor = LeanstralProposalAdvisor(StaticProposalModel(response))
    result = advisor.propose(_request(kind=kind, request_id=f"req:{kind.value}"))
    assert len(result.candidates) == 1
    assert result.candidates[0].kind is kind
    assert result.authority == UNVERIFIED_AUTHORITY
    assert result.candidates[0].is_proved is False
    assert result.candidates[0].confidence == 0.5


# ---------------------------------------------------------------------------
# Bounds, sanitization, source binding, inert prompts
# ---------------------------------------------------------------------------


def test_prompts_and_responses_are_inert_and_source_bound() -> None:
    advisor = LeanstralProposalAdvisor(
        StaticProposalModel(
            build_json_candidates_response(
                [_candidate_record(provider="leanstral", confidence=0.8)]
            )
        )
    )
    result = advisor.propose(_request())
    assert "propose_only_never_prove" in result.prompt
    assert "authority=unverified_candidate_only" in result.prompt
    assert "source:module.py" in result.prompt
    assert "source:spec.md" in result.prompt
    assert "os.system" not in result.prompt
    assert result.candidates[0].source_ref_ids == (
        "source:module.py",
        "source:spec.md",
    )
    # Response round-trips as sanitized text (no control chars introduced).
    sanitize_inert_text(result.raw_response, "raw_response", maximum=16_384)


def test_rejects_executable_markers_in_body() -> None:
    response = build_json_candidates_response(
        [
            {
                "candidate_id": "cand:evil",
                "kind": "lemma",
                "body": "lemma x : True := by\n```python\nimport os\nos.system('id')\n```",
                "source_ref_ids": ["source:module.py"],
                "provider": "leanstral",
            }
        ]
    )
    advisor = LeanstralProposalAdvisor(StaticProposalModel(response))
    with pytest.raises(ProposalAdvisorValidationError, match="executable marker"):
        advisor.propose(
            _request(source_ref_ids=("source:module.py",), notes="")
        )


def test_rejects_ungrounded_request() -> None:
    with pytest.raises(ProposalAdvisorValidationError, match="source-bound"):
        _request(source_ref_ids=())


def test_rejects_candidate_with_unknown_source_refs() -> None:
    response = build_json_candidates_response(
        [
            {
                "candidate_id": "cand:bad-src",
                "kind": "lemma",
                "body": "lemma ok : True",
                "source_ref_ids": ["source:module.py", "source:forged"],
                "provider": "symai",
            }
        ]
    )
    advisor = SymAIProposalAdvisor(StaticProposalModel(response))
    with pytest.raises(ProposalAdvisorValidationError, match="subset"):
        advisor.propose(_request())


def test_rejects_authority_claims_in_candidate_metadata() -> None:
    # Build raw JSON so the wire payload still carries banned authority keys;
    # the advisor must reject them during decode/validation.
    response = (
        '{"candidates":[{'
        '"candidate_id":"cand:claim",'
        '"kind":"lemma",'
        '"body":"lemma ok : True",'
        '"source_ref_ids":["source:module.py","source:spec.md"],'
        '"provider":"leanstral",'
        '"metadata":{"is_valid":true,"proof_status":"proved"}'
        "}]}"
    )
    advisor = LeanstralProposalAdvisor(StaticProposalModel(response))
    with pytest.raises(ProposalAdvisorValidationError, match="authority"):
        advisor.propose(_request())


def test_rejects_oversized_body() -> None:
    huge = "x" * 9000
    response = build_json_candidates_response(
        [
            {
                "candidate_id": "cand:huge",
                "kind": "lemma",
                "body": huge,
                "source_ref_ids": ["source:module.py", "source:spec.md"],
                "provider": "leanstral",
            }
        ]
    )
    advisor = LeanstralProposalAdvisor(StaticProposalModel(response))
    with pytest.raises(ProposalAdvisorValidationError, match="hard limit"):
        advisor.propose(_request())


def test_max_candidates_bound() -> None:
    records = [
        _candidate_record(
            provider="symai",
            candidate_id=f"cand:{index}",
            confidence=0.1,
        )
        for index in range(5)
    ]
    advisor = SymAIProposalAdvisor(
        StaticProposalModel(build_json_candidates_response(records)),
        ProposalAdvisorConfig.symai_default(max_candidates=3),
    )
    with pytest.raises(ProposalAdvisorValidationError, match="more than 3"):
        advisor.propose(_request())


# ---------------------------------------------------------------------------
# Confidence / is_valid never yields proof; acceptance gates
# ---------------------------------------------------------------------------


def test_confidence_never_yields_proof() -> None:
    assert confidence_never_yields_proof(is_valid=True, confidence=1.0) is False
    assert (
        confidence_never_yields_proof(similarity=0.99, confidence=0.99) is False
    )
    candidate = ProposalCandidate(
        candidate_id="cand:hi-conf",
        kind=ProposalKind.LEMMA,
        body="lemma t : True",
        source_ref_ids=("source:module.py",),
        provider=ProposalProvider.LEANSTRAL,
        confidence=1.0,
    )
    assert candidate.is_proved is False
    assert candidate.authority == UNVERIFIED_AUTHORITY


def test_accept_candidate_requires_compilation_and_independent_validation() -> None:
    candidate = ProposalCandidate(
        candidate_id="cand:accept",
        kind=ProposalKind.TACTIC,
        body="exact rfl",
        source_ref_ids=("source:module.py",),
        provider=ProposalProvider.SYMAI,
        confidence=0.99,
    )
    rejected = accept_candidate(
        candidate, compiled=True, independently_validated=False
    )
    assert rejected.accepted is False
    assert rejected.authority == UNVERIFIED_AUTHORITY
    assert "missing_independent_solver_or_kernel_validation" in rejected.reasons

    rejected2 = accept_candidate(
        candidate, compiled=False, independently_validated=True
    )
    assert rejected2.accepted is False

    admitted = accept_candidate(
        candidate, compiled=True, independently_validated=True
    )
    assert admitted.accepted is True
    assert admitted.authority == "candidate_admitted_for_validation"
    # Admission is not proof — still not theorem authority.
    assert admitted.authority != "proved"


def test_proposal_acceptance_fails_closed_on_false_accepted_flag() -> None:
    with pytest.raises(ProposalAdvisorValidationError, match="require"):
        ProposalAcceptance(
            candidate_id="cand:bad",
            accepted=True,
            compiled=True,
            independently_validated=False,
        )


# ---------------------------------------------------------------------------
# End-to-end leanstral + symai propose paths
# ---------------------------------------------------------------------------


def test_leanstral_and_symai_propose_round_trip() -> None:
    leanstral = LeanstralProposalAdvisor(
        StaticProposalModel(
            build_json_candidates_response(
                [
                    _candidate_record(
                        provider="leanstral",
                        kind="specification",
                        candidate_id="cand:spec",
                    )
                ]
            )
        )
    )
    symai = SymAIProposalAdvisor(
        StaticProposalModel(
            build_json_candidates_response(
                [
                    _candidate_record(
                        provider="symai",
                        kind="premise",
                        candidate_id="cand:prem",
                        confidence=0.4,
                    )
                ]
            )
        )
    )
    lean_result = leanstral.propose(
        _request(kind=ProposalKind.SPECIFICATION, request_id="req:spec")
    )
    sym_result = symai.propose(
        _request(kind=ProposalKind.PREMISE, request_id="req:prem")
    )
    assert lean_result.provider is ProposalProvider.LEANSTRAL
    assert sym_result.provider is ProposalProvider.SYMAI
    assert lean_result.interface_id == LEANSTRAL_ADVISOR_INTERFACE
    assert sym_result.interface_id == SYMAI_ADVISOR_INTERFACE
    assert lean_result.candidates[0].kind is ProposalKind.SPECIFICATION
    assert sym_result.candidates[0].kind is ProposalKind.PREMISE
    # High confidence still untrusted.
    assert lean_result.candidates[0].is_proved is False
    assert sym_result.candidates[0].is_proved is False


def test_freeform_response_becomes_source_bound_candidate() -> None:
    advisor = LeanstralProposalAdvisor(
        StaticProposalModel("apply Nat.add_comm")
    )
    result = advisor.propose(_request(kind=ProposalKind.TACTIC))
    assert len(result.candidates) == 1
    assert result.candidates[0].body == "apply Nat.add_comm"
    assert result.candidates[0].source_ref_ids == (
        "source:module.py",
        "source:spec.md",
    )
    assert result.candidates[0].authority == UNVERIFIED_AUTHORITY


def test_request_and_result_dicts_round_trip() -> None:
    request = _request()
    restored = ProposalAdvisorRequest.from_dict(request.to_dict())
    assert restored.digest == request.digest
    advisor = SymAIProposalAdvisor(
        StaticProposalModel(
            build_json_candidates_response(
                [_candidate_record(provider="symai", confidence=0.2)]
            )
        )
    )
    result = advisor.propose(request)
    again = type(result).from_dict(result.to_dict())
    assert again.to_dict() == result.to_dict()


# ---------------------------------------------------------------------------
# prover_router: is_valid / untrusted providers never yield proof
# ---------------------------------------------------------------------------


@dataclass
class _LegacyValidOnlyResult:
    """Legacy payload with is_valid but no is_proved (must not prove)."""

    is_valid: bool
    confidence: float = 0.95


@dataclass
class _NeuralConfidenceResult:
    """Mimics SymbolicAI neural result that used confidence as proof."""

    is_valid: bool
    confidence: float
    method: str = "neural_guided"

    def is_proved(self) -> bool:
        return self.is_valid and self.confidence >= 0.8


@dataclass
class _TrustedProvedResult:
    formula: str = "P"

    def is_proved(self) -> bool:
        return True


def test_router_never_treats_bare_is_valid_as_proof() -> None:
    assert (
        ProverRouter._result_is_proved(_LegacyValidOnlyResult(is_valid=True))
        is False
    )
    assert (
        ProverRouter._result_is_proved(
            SyntacticProofResult(formula="P", is_valid=True, message="ok")
        )
        is False
    )
    # Explicit is_proved from a trusted class still works.
    assert ProverRouter._result_is_proved(_TrustedProvedResult()) is True


def test_router_never_treats_symbolicai_or_neural_as_proof() -> None:
    neural = _NeuralConfidenceResult(is_valid=True, confidence=0.99)
    assert (
        ProverRouter._result_is_proved(neural, prover_name="symbolicai") is False
    )
    assert ProverRouter._result_is_proved(neural, prover_name="leanstral") is False
    assert ProverRouter._result_is_proved(neural, prover_name="neural") is False
    # Class-name / method heuristics also fence when prover_name omitted.
    assert ProverRouter._result_is_proved(neural) is False
    assert is_untrusted_proposal_provider("symbolicai") is True
    assert is_untrusted_proposal_provider("leanstral") is True
    assert is_untrusted_proposal_provider("z3") is False


def test_router_select_best_skips_untrusted_providers() -> None:
    from ipfs_datasets_py.logic.external_provers.prover_router import (
        RouterProofResult,
    )

    router = ProverRouter(
        enable_z3=False,
        enable_cvc5=False,
        enable_lean=False,
        enable_coq=False,
        enable_native=False,
        enable_symbolicai=False,
        enable_syntactic_fallback=False,
    )
    result = RouterProofResult(
        is_proved=False,
        prover_used="symbolicai",
        proof_time=0.0,
        all_results={
            "symbolicai": _NeuralConfidenceResult(
                is_valid=True, confidence=1.0
            ),
            "native": _TrustedProvedResult(),
        },
        strategy_used="parallel",
        reason="fixture",
    )
    best = router.select_best(result)
    assert isinstance(best, _TrustedProvedResult)


# ---------------------------------------------------------------------------
# reasoning_coordinator: neural confidence never sets is_proved
# ---------------------------------------------------------------------------


class _FakeEmbeddingProver:
    def compute_similarity(self, goal: Any, axioms: Any) -> float:
        del goal, axioms
        return 0.99


def test_coordinator_neural_path_never_proves_from_confidence() -> None:
    coordinator = NeuralSymbolicCoordinator(
        use_cec=False,
        use_modal=False,
        use_embeddings=True,
        confidence_threshold=0.5,
    )
    coordinator.embedding_prover = _FakeEmbeddingProver()
    coordinator.use_embeddings = True

    # Bypass formula parsing: call _prove_neural with plain strings via stubs.
    result = coordinator._prove_neural("P -> P", [])  # type: ignore[arg-type]
    assert isinstance(result, CoordinatedResult)
    assert result.is_proved is False
    assert result.neural_confidence == pytest.approx(0.99)
    assert result.confidence == pytest.approx(0.99)
    assert result.metadata.get("proof_from_neural") is False
    assert result.metadata.get("authority") == "unverified_candidate_only"
    assert result.strategy_used is ReasoningStrategy.NEURAL_ONLY


def test_coordinator_hybrid_path_requires_symbolic_for_proof() -> None:
    coordinator = NeuralSymbolicCoordinator(
        use_cec=False,
        use_modal=False,
        use_embeddings=True,
        confidence_threshold=0.1,
    )
    coordinator.embedding_prover = _FakeEmbeddingProver()
    coordinator.use_embeddings = True

    # Force symbolic failure while neural confidence is high.
    class _FailingReasoner:
        def add_knowledge(self, *_args: Any, **_kwargs: Any) -> None:
            return None

        def prove(self, *_args: Any, **_kwargs: Any) -> Any:
            class _R:
                def is_proved(self) -> bool:
                    return False

                proof_steps: list[str] = []

            return _R()

    coordinator.symbolic_reasoner = _FailingReasoner()  # type: ignore[assignment]
    result = coordinator._prove_hybrid("P -> Q", [], timeout_ms=100)  # type: ignore[arg-type]
    assert result.is_proved is False
    assert result.neural_confidence == pytest.approx(0.99)
    assert result.metadata.get("proof_from_neural") is False
    assert result.strategy_used is ReasoningStrategy.HYBRID


def test_coordinator_capabilities_declare_no_neural_proof_authority() -> None:
    coordinator = NeuralSymbolicCoordinator(
        use_cec=False, use_modal=False, use_embeddings=False
    )
    caps = coordinator.get_capabilities()
    assert caps["neural_proof_authority"] is False
    assert caps["neural_role"] == "untrusted_proposal_provider"


def test_coordinator_hybrid_preserves_symbolic_proof() -> None:
    coordinator = NeuralSymbolicCoordinator(
        use_cec=False,
        use_modal=False,
        use_embeddings=True,
        confidence_threshold=0.9,
    )
    coordinator.embedding_prover = _FakeEmbeddingProver()
    coordinator.use_embeddings = True

    class _ProvingReasoner:
        def add_knowledge(self, *_args: Any, **_kwargs: Any) -> None:
            return None

        def prove(self, *_args: Any, **_kwargs: Any) -> Any:
            class _R:
                def is_proved(self) -> bool:
                    return True

                proof_steps = ["axiom"]

            return _R()

    coordinator.symbolic_reasoner = _ProvingReasoner()  # type: ignore[assignment]
    result = coordinator._prove_hybrid("P -> P", [], timeout_ms=100)  # type: ignore[arg-type]
    assert result.is_proved is True
    assert result.strategy_used is ReasoningStrategy.HYBRID
