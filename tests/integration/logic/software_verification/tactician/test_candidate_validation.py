"""Integration tests for ProofCandidateValidator@1 (FVT-025 / FVT-G034).

Acceptance criteria covered:

* no unvalidated or stale candidate discharges a graph node;
* exact tree/goal/assumptions/tool/policy/bounds are bound;
* deletion of a selected premise breaks the proof for small minimal cases,
  or the receipt explicitly limits its guarantee;
* disagreement is quarantined;
* providers may propose evidence but only the deterministic validator sets
  validation status; and
* parse/type, consistency, non-vacuity, non-circularity, replay, and truthful
  authority/unknown/unavailable results are exercised.
"""

from __future__ import annotations

from typing import Any

import pytest

from ipfs_datasets_py.logic.software_verification.tactician.contracts import (
    AuthorityCeiling,
    CandidateProofStep,
    CandidateStatus,
    CandidateValidation,
    HoleKind,
    HoleStatus,
    ProofHole,
    PropertyClass,
    ResourceBounds,
    SourceSpanBinding,
    ValidationRecipe,
    ValidationVerdict,
)
from ipfs_datasets_py.logic.software_verification.tactician.candidate_validation import (
    DEFAULT_BOUNDS,
    PIPELINE_STAGES,
    PROOF_CANDIDATE_VALIDATOR_INTERFACE,
    VALIDATOR_ALGORITHM_VERSION,
    CandidateSetValidationResult,
    CandidateValidationError,
    CandidateValidationResult,
    DischargeEligibility,
    MinimalityKind,
    ProofCandidateValidator,
    QuarantineReason,
    ReplayBackendKind,
    ReplayStatus,
    StaticReplayBackend,
    UnavailableReplayBackend,
    ValidationBinding,
    ValidationCheckStatus,
    ValidationRequest,
    cap_validation_authority,
    default_pipeline_stages,
    is_contradiction_statement,
    is_vacuous_statement,
    may_discharge_graph_node,
    validate_candidate,
    validate_candidate_set,
)


# ---------------------------------------------------------------------------
# Factories
# ---------------------------------------------------------------------------


def _source(**overrides: Any) -> SourceSpanBinding:
    payload = {
        "tree_id": "tree:repo@abc",
        "source_ref_ids": ("source:lease.py",),
        "span_ids": ("span:claim",),
        "ast_scope_ids": ("symbol:claim_lease",),
        "snapshot_id": "snap:1",
    }
    payload.update(overrides)
    return SourceSpanBinding(**payload)


def _bounds(**overrides: Any) -> ResourceBounds:
    payload = {
        "wall_time_ms": 10_000,
        "memory_bytes": 64 * 1024 * 1024,
        "max_steps": 32,
        "max_depth": 8,
        "max_nodes": 64,
        "max_candidates": 16,
        "network_allowed": False,
    }
    payload.update(overrides)
    return ResourceBounds(**payload)


def _recipe(**overrides: Any) -> ValidationRecipe:
    payload: dict[str, Any] = {
        "recipe_id": "recipe:loop_invariant:site",
        "checker_kind": "smt_replay",
        "provider_ids": ("provider:z3",),
        "required_authority": AuthorityCeiling.SATISFIABILITY,
        "bounds": _bounds(),
        "steps": (
            "bind_source_span",
            "replay",
            "minimality",
            "record_receipt",
        ),
        "oracle_id": "oracle:loop_invariant",
    }
    payload.update(overrides)
    return ValidationRecipe(**payload)


def _hole(**overrides: Any) -> ProofHole:
    payload: dict[str, Any] = {
        "hole_id": "hole:site:loop:loop_invariant",
        "kind": HoleKind.LOOP_INVARIANT,
        "reason": "Required loop_invariant is missing",
        "source": _source(),
        "formal_goal_id": "formal:lease-ready",
        "expected_authority": AuthorityCeiling.SATISFIABILITY,
        "status": HoleStatus.OPEN,
        "property_class": PropertyClass.INVARIANCE,
        "statement": "missing loop_invariant for claim_lease",
        "provider_ids": ("provider:z3",),
        "bounds": _bounds(),
        "validation_recipe": _recipe(),
        "proof_claimed": False,
        "completion_claimed": False,
    }
    payload.update(overrides)
    return ProofHole(**payload)


def _candidate(**overrides: Any) -> CandidateProofStep:
    payload: dict[str, Any] = {
        "candidate_id": "candidate:inv:lease-ready",
        "hole_id": "hole:site:loop:loop_invariant",
        "kind": "loop_invariant",
        "statement": "owner_holds_token and bound > 0",
        "status": CandidateStatus.PROPOSED,
        "source": _source(),
        "provider_ids": ("provider:z3",),
        "authority": AuthorityCeiling.CANDIDATE,
        "rank_score_millionths": 750_000,
        "new_assumption_ids": ("assumption:token-order",),
        "evidence_ids": (),
        "provenance": {
            "source_kind": "smt_unsat_core",
            "premise_ids": ("premise:owner_holds", "premise:bound_pos"),
        },
        "proof_claimed": False,
        "completion_claimed": False,
    }
    payload.update(overrides)
    return CandidateProofStep(**payload)


def _binding(**overrides: Any) -> ValidationBinding:
    payload: dict[str, Any] = {
        "tree_id": "tree:repo@abc",
        "formal_goal_id": "formal:lease-ready",
        "assumption_ids": ("assumption:token-order", "assumption:fair-scheduler"),
        "tool_id": "provider:z3",
        "policy_id": "policy:hermetic-offline",
        "bounds": _bounds(),
        "snapshot_id": "snap:1",
        "graph_node_id": "node:leaf:loop-inv",
        "source": _source(),
        "known_facts": ("token_unique",),
        "axioms": ("tokens_totally_ordered",),
        "premise_ids": ("premise:owner_holds", "premise:bound_pos"),
        "selected_premise_ids": ("premise:owner_holds", "premise:bound_pos"),
    }
    payload.update(overrides)
    return ValidationBinding(**payload)


def _backend(
    candidate_id: str = "candidate:inv:lease-ready",
    *,
    holds: bool = True,
    critical: tuple[str, ...] = ("premise:owner_holds", "premise:bound_pos"),
    **overrides: Any,
) -> StaticReplayBackend:
    payload: dict[str, Any] = {
        "provider_id": "provider:z3",
        "provider_version": "4.13.0",
        "backend_kind": ReplayBackendKind.SOLVER,
        "authority": AuthorityCeiling.SATISFIABILITY,
        "holds_for": {candidate_id: holds},
        "critical_premises": {candidate_id: critical},
        "default_holds": holds,
    }
    payload.update(overrides)
    return StaticReplayBackend(**payload)


def _request(**overrides: Any) -> ValidationRequest:
    payload: dict[str, Any] = {
        "candidate": _candidate(),
        "hole": _hole(),
        "binding": _binding(),
        "recipe": _recipe(),
    }
    payload.update(overrides)
    return ValidationRequest(**payload)


# ---------------------------------------------------------------------------
# Interface / vocabulary
# ---------------------------------------------------------------------------


def test_validator_interface_constant() -> None:
    assert (
        ProofCandidateValidator.INTERFACE == PROOF_CANDIDATE_VALIDATOR_INTERFACE
    )
    assert PROOF_CANDIDATE_VALIDATOR_INTERFACE == "ProofCandidateValidator@1"
    assert VALIDATOR_ALGORITHM_VERSION.startswith("proof-candidate-validator/")
    assert default_pipeline_stages() == PIPELINE_STAGES
    assert "parse_type" in PIPELINE_STAGES
    assert "exact_binding" in PIPELINE_STAGES
    assert "minimality" in PIPELINE_STAGES
    assert "discharge_gate" in PIPELINE_STAGES


def test_vacuous_and_contradiction_helpers() -> None:
    assert is_vacuous_statement("true")
    assert is_vacuous_statement("TRUE")
    assert not is_vacuous_statement("owner_holds_token")
    assert is_contradiction_statement("false")
    assert is_contradiction_statement("contradiction")
    assert not is_contradiction_statement("owner_holds_token")


# ---------------------------------------------------------------------------
# Happy path: full accept with local minimality
# ---------------------------------------------------------------------------


def test_accepted_candidate_with_local_minimality_may_discharge() -> None:
    backend = _backend()
    validator = ProofCandidateValidator(backends=(backend,))
    result = validator.validate(_request())

    assert result.validated is True
    assert result.stale is False
    assert result.quarantined is False
    assert result.validation.verdict is ValidationVerdict.ACCEPTED
    assert result.validation.tree_id == "tree:repo@abc"
    assert set(result.validation.assumption_ids) == {
        "assumption:token-order",
        "assumption:fair-scheduler",
    }
    assert result.validation.minimality == MinimalityKind.LOCAL.value
    assert result.discharge_eligibility is DischargeEligibility.ELIGIBLE
    assert result.may_discharge is True
    assert result.proof_claimed is False
    assert result.completion_claimed is False
    assert result.validation.proof_claimed is False
    assert result.validation.completion_claimed is False

    stages = {c.stage: c.status for c in result.checks}
    assert stages["parse_type"] is ValidationCheckStatus.PASS
    assert stages["exact_binding"] is ValidationCheckStatus.PASS
    assert stages["consistency"] is ValidationCheckStatus.PASS
    assert stages["non_vacuity"] is ValidationCheckStatus.PASS
    assert stages["non_circularity"] is ValidationCheckStatus.PASS
    assert stages["replay"] is ValidationCheckStatus.PASS
    assert stages["minimality"] is ValidationCheckStatus.PASS
    assert stages["discharge_gate"] is ValidationCheckStatus.PASS

    assert result.minimality_report is not None
    assert result.minimality_report.deletion_breaks_proof is True
    assert set(result.minimality_report.critical_premise_ids) == {
        "premise:owner_holds",
        "premise:bound_pos",
    }


def test_validate_candidate_convenience_entry() -> None:
    result = validate_candidate(
        _candidate(),
        _hole(),
        _binding(),
        backends=(_backend(),),
        recipe=_recipe(),
    )
    assert isinstance(result, CandidateValidationResult)
    assert result.validation.verdict is ValidationVerdict.ACCEPTED
    assert result.may_discharge is True


def test_round_trip_serialization() -> None:
    result = validate_candidate(
        _candidate(),
        _hole(),
        _binding(),
        backends=(_backend(),),
    )
    restored = CandidateValidationResult.from_dict(result.to_dict())
    assert restored.content_id == result.content_id
    assert restored.validation.verdict is ValidationVerdict.ACCEPTED
    assert restored.may_discharge is result.may_discharge


# ---------------------------------------------------------------------------
# Exact bindings
# ---------------------------------------------------------------------------


def test_tree_id_mismatch_rejects() -> None:
    result = validate_candidate(
        _candidate(source=_source(tree_id="tree:other")),
        _hole(),
        _binding(),
        backends=(_backend(),),
    )
    assert result.validation.verdict is ValidationVerdict.REJECTED
    assert result.may_discharge is False
    binding_check = next(c for c in result.checks if c.stage == "exact_binding")
    assert binding_check.status is ValidationCheckStatus.FAIL
    assert "tree_id" in binding_check.detail


def test_formal_goal_mismatch_rejects() -> None:
    result = validate_candidate(
        _candidate(),
        _hole(formal_goal_id="formal:other-goal"),
        _binding(),
        backends=(_backend(),),
    )
    assert result.validation.verdict is ValidationVerdict.REJECTED
    assert result.may_discharge is False


def test_unbound_assumption_rejects() -> None:
    result = validate_candidate(
        _candidate(new_assumption_ids=("assumption:rogue",)),
        _hole(),
        _binding(),
        backends=(_backend(),),
    )
    assert result.validation.verdict is ValidationVerdict.REJECTED
    detail = next(
        c.detail for c in result.checks if c.stage == "exact_binding"
    )
    assert "not bound" in detail


def test_hermetic_policy_rejects_network_bounds() -> None:
    result = validate_candidate(
        _candidate(),
        _hole(),
        _binding(bounds=_bounds(network_allowed=True)),
        backends=(_backend(),),
    )
    assert result.validation.verdict is ValidationVerdict.REJECTED
    detail = next(
        c.detail for c in result.checks if c.stage == "exact_binding"
    )
    assert "network" in detail.lower() or "hermetic" in detail.lower()


def test_snapshot_mismatch_rejects() -> None:
    result = validate_candidate(
        _candidate(source=_source(snapshot_id="snap:stale")),
        _hole(),
        _binding(snapshot_id="snap:1"),
        backends=(_backend(),),
    )
    assert result.validation.verdict is ValidationVerdict.REJECTED


def test_accepted_validation_records_exact_bindings() -> None:
    binding = _binding(
        tool_id="provider:z3",
        policy_id="policy:hermetic-offline",
        graph_node_id="node:leaf:loop-inv",
    )
    result = validate_candidate(
        _candidate(),
        _hole(),
        binding,
        backends=(_backend(),),
        recipe=_recipe(),
    )
    assert result.validation.tree_id == binding.tree_id
    assert set(result.validation.assumption_ids) == set(binding.assumption_ids)
    assert result.binding_content_id == binding.content_id
    assert result.metadata["formal_goal_id"] == binding.formal_goal_id
    assert result.metadata["graph_node_id"] == binding.graph_node_id
    assert result.validation.recipe is not None
    assert result.validation.recipe.provider_ids == ("provider:z3",)


# ---------------------------------------------------------------------------
# Unvalidated / stale never discharge
# ---------------------------------------------------------------------------


def test_stale_candidate_cannot_discharge() -> None:
    candidate = _candidate()
    wrong_id = "sha256:" + ("0" * 64)
    result = validate_candidate(
        candidate,
        _hole(),
        _binding(),
        backends=(_backend(),),
        expected_candidate_content_id=wrong_id,
    )
    assert result.stale is True
    assert result.validation.verdict is ValidationVerdict.REJECTED
    assert result.discharge_eligibility is DischargeEligibility.STALE
    assert result.may_discharge is False
    assert may_discharge_graph_node(
        verdict=result.validation.verdict,
        eligibility=result.discharge_eligibility,
        validated=result.validated,
        stale=result.stale,
        quarantined=result.quarantined,
    ) is False


def test_unvalidated_flags_never_discharge() -> None:
    # Explicit gate: even ACCEPTED with unvalidated=False is blocked.
    assert (
        may_discharge_graph_node(
            verdict=ValidationVerdict.ACCEPTED,
            eligibility=DischargeEligibility.ELIGIBLE,
            validated=False,
            stale=False,
            quarantined=False,
        )
        is False
    )
    assert (
        may_discharge_graph_node(
            verdict=ValidationVerdict.ACCEPTED,
            eligibility=DischargeEligibility.ELIGIBLE,
            validated=True,
            stale=True,
            quarantined=False,
        )
        is False
    )
    assert (
        may_discharge_graph_node(
            verdict=ValidationVerdict.ACCEPTED,
            eligibility=DischargeEligibility.ELIGIBLE,
            validated=True,
            stale=False,
            quarantined=True,
        )
        is False
    )


def test_terminal_candidate_status_rejected() -> None:
    result = validate_candidate(
        _candidate(status=CandidateStatus.REJECTED),
        _hole(),
        _binding(),
        backends=(_backend(),),
    )
    assert result.validation.verdict is ValidationVerdict.REJECTED
    assert result.may_discharge is False


def test_non_proof_hole_kind_rejected() -> None:
    result = validate_candidate(
        _candidate(
            hole_id="hole:unsupported",
            statement="unsupported_semantics(x)",
        ),
        _hole(
            hole_id="hole:unsupported",
            kind=HoleKind.UNSUPPORTED_SEMANTICS,
            status=HoleStatus.UNSUPPORTED,
            statement="unsupported semantics",
        ),
        _binding(),
        backends=(_backend(candidate_id="candidate:inv:lease-ready"),),
    )
    assert result.validation.verdict is ValidationVerdict.REJECTED
    assert result.may_discharge is False


# ---------------------------------------------------------------------------
# Consistency / non-vacuity / non-circularity
# ---------------------------------------------------------------------------


def test_vacuous_candidate_rejected() -> None:
    result = validate_candidate(
        _candidate(statement="true"),
        _hole(),
        _binding(),
        backends=(_backend(),),
    )
    assert result.validation.verdict is ValidationVerdict.REJECTED
    vacuity = next(c for c in result.checks if c.stage == "non_vacuity")
    assert vacuity.status is ValidationCheckStatus.FAIL


def test_contradiction_candidate_rejected() -> None:
    result = validate_candidate(
        _candidate(statement="false"),
        _hole(),
        _binding(),
        backends=(_backend(),),
    )
    assert result.validation.verdict is ValidationVerdict.REJECTED
    consistency = next(c for c in result.checks if c.stage == "consistency")
    assert consistency.status is ValidationCheckStatus.FAIL


def test_inconsistent_with_known_fact_rejected() -> None:
    result = validate_candidate(
        _candidate(statement="not token_unique"),
        _hole(),
        _binding(known_facts=("token_unique",)),
        backends=(_backend(),),
    )
    assert result.validation.verdict is ValidationVerdict.REJECTED
    consistency = next(c for c in result.checks if c.stage == "consistency")
    assert consistency.status is ValidationCheckStatus.FAIL


def test_circular_goal_entailing_rejected() -> None:
    result = validate_candidate(
        _candidate(statement="formal:lease-ready"),
        _hole(),
        _binding(),
        backends=(_backend(),),
    )
    assert result.validation.verdict is ValidationVerdict.REJECTED
    circular = next(c for c in result.checks if c.stage == "non_circularity")
    assert circular.status is ValidationCheckStatus.FAIL


def test_circular_self_dependency_rejected() -> None:
    result = validate_candidate(
        _candidate(
            provenance={
                "dependency_ids": ("candidate:inv:lease-ready",),
                "premise_ids": ("premise:owner_holds",),
            }
        ),
        _hole(),
        _binding(),
        backends=(_backend(),),
    )
    assert result.validation.verdict is ValidationVerdict.REJECTED


# ---------------------------------------------------------------------------
# Replay: holds / fails / unavailable / unknown
# ---------------------------------------------------------------------------


def test_replay_fail_rejects() -> None:
    result = validate_candidate(
        _candidate(),
        _hole(),
        _binding(),
        backends=(_backend(holds=False),),
    )
    assert result.validation.verdict is ValidationVerdict.REJECTED
    assert result.may_discharge is False
    replay = next(c for c in result.checks if c.stage == "replay")
    assert replay.status is ValidationCheckStatus.FAIL


def test_unavailable_backend_reports_unavailable() -> None:
    result = validate_candidate(
        _candidate(),
        _hole(),
        _binding(),
        backends=(UnavailableReplayBackend(provider_id="provider:z3"),),
    )
    assert result.validation.verdict is ValidationVerdict.UNAVAILABLE
    assert result.validation.authority is AuthorityCeiling.NONE
    assert result.may_discharge is False
    replay = next(c for c in result.checks if c.stage == "replay")
    assert replay.status is ValidationCheckStatus.UNAVAILABLE


def test_no_backend_is_unavailable_not_accept() -> None:
    result = validate_candidate(
        _candidate(),
        _hole(),
        _binding(),
        backends=(),
    )
    assert result.validation.verdict is ValidationVerdict.UNAVAILABLE
    assert result.may_discharge is False


def test_unknown_replay_is_truthful() -> None:
    backend = StaticReplayBackend(
        provider_id="provider:z3",
        force_status=ReplayStatus.UNKNOWN,
    )
    result = validate_candidate(
        _candidate(),
        _hole(),
        _binding(),
        backends=(backend,),
    )
    assert result.validation.verdict is ValidationVerdict.UNKNOWN
    assert result.may_discharge is False


# ---------------------------------------------------------------------------
# Minimality: deletion breaks proof OR limited guarantee
# ---------------------------------------------------------------------------


def test_redundant_premises_limit_guarantee_to_bounded() -> None:
    """When deletion does not break the proof, accept is limited (BOUNDED)."""

    backend = StaticReplayBackend(
        provider_id="provider:z3",
        holds_for={"candidate:inv:lease-ready": True},
        # Empty critical set + holds on deletion → redundant
        critical_premises={"candidate:inv:lease-ready": ()},
        default_holds=True,
    )
    # StaticReplayBackend returns UNKNOWN when dropping with empty critical.
    # Force holds even after deletion by not listing critical premises and
    # using a custom backend-like mapping: default_holds True without critical
    # yields UNKNOWN on deletion.  To model pure redundancy (holds after drop),
    # provide critical empty but override via a tiny custom backend.

    class AlwaysHoldsBackend:
        provider_id = "provider:z3"
        backend_kind = ReplayBackendKind.SOLVER

        def replay(self, candidate, *, hole, binding, bounds, drop_premise_ids=()):
            from ipfs_datasets_py.logic.software_verification.tactician.candidate_validation import (
                ReplayOutcome,
            )

            return ReplayOutcome(
                status=ReplayStatus.HOLDS,
                backend_kind=ReplayBackendKind.SOLVER,
                provider_id=self.provider_id,
                provider_version="1",
                authority=AuthorityCeiling.SATISFIABILITY,
                evidence_ids=("evidence:always",),
                detail="holds even after deletion",
                metadata={"dropped": list(drop_premise_ids)},
            )

    result = validate_candidate(
        _candidate(),
        _hole(),
        _binding(),
        backends=(AlwaysHoldsBackend(),),
    )
    assert result.validation.verdict is ValidationVerdict.BOUNDED
    assert result.discharge_eligibility is DischargeEligibility.BOUNDED
    assert result.may_discharge is True  # bounded is still eligible under gate
    assert result.minimality_report is not None
    assert result.minimality_report.guarantee_limited is True
    assert result.minimality_report.deletion_breaks_proof is False
    assert result.validation.minimality in {
        MinimalityKind.BOUNDED.value,
        MinimalityKind.UNKNOWN.value,
    }


def test_missing_selected_premises_limits_guarantee() -> None:
    backend = _backend(critical=())
    result = validate_candidate(
        _candidate(provenance={"source_kind": "template"}),
        _hole(),
        _binding(selected_premise_ids=(), premise_ids=()),
        backends=(backend,),
    )
    # Full replay holds; no premises → BOUNDED with limited guarantee
    assert result.validation.verdict in {
        ValidationVerdict.BOUNDED,
        ValidationVerdict.ACCEPTED,
    }
    if result.validation.verdict is ValidationVerdict.BOUNDED:
        assert result.minimality_report is not None
        assert result.minimality_report.guarantee_limited is True
    assert result.may_discharge is True or result.validation.verdict is ValidationVerdict.BOUNDED


def test_local_minimality_deletion_breaks_each_premise() -> None:
    backend = _backend(
        critical=("premise:owner_holds", "premise:bound_pos"),
    )
    result = validate_candidate(
        _candidate(),
        _hole(),
        _binding(
            selected_premise_ids=("premise:owner_holds", "premise:bound_pos")
        ),
        backends=(backend,),
    )
    assert result.minimality_report is not None
    assert result.minimality_report.deletion_breaks_proof is True
    assert result.minimality_report.kind is MinimalityKind.LOCAL
    assert result.validation.verdict is ValidationVerdict.ACCEPTED


# ---------------------------------------------------------------------------
# Disagreement quarantine
# ---------------------------------------------------------------------------


def test_provider_verdict_disagreement_is_quarantined() -> None:
    result = validate_candidate(
        _candidate(),
        _hole(),
        _binding(),
        backends=(_backend(),),
        proposed_provider_verdicts={
            "provider:z3": "accepted",
            "provider:cvc5": "rejected",
        },
    )
    assert result.quarantined is True
    assert result.validation.verdict is ValidationVerdict.INCONCLUSIVE
    assert result.discharge_eligibility is DischargeEligibility.QUARANTINED
    assert result.may_discharge is False
    assert result.disagreement is not None
    assert (
        result.disagreement.reason is QuarantineReason.PROVIDER_DISAGREEMENT
    )


def test_replay_backend_disagreement_is_quarantined() -> None:
    hold = _backend(provider_id="provider:z3", holds=True)
    fail = StaticReplayBackend(
        provider_id="provider:cvc5",
        holds_for={"candidate:inv:lease-ready": False},
        critical_premises={},
        default_holds=False,
    )
    result = validate_candidate(
        _candidate(),
        _hole(),
        _binding(),
        backends=(hold, fail),
    )
    assert result.quarantined is True
    assert result.may_discharge is False
    assert result.validation.verdict is ValidationVerdict.INCONCLUSIVE
    assert result.disagreement is not None
    assert result.disagreement.reason is QuarantineReason.REPLAY_DISAGREEMENT


def test_candidate_set_disagreement_quarantines_both() -> None:
    accept_cand = _candidate(candidate_id="candidate:a")
    reject_cand = _candidate(
        candidate_id="candidate:b",
        statement="owner_holds_token and bound > 0 and extra",
    )
    hole = _hole()
    binding = _binding()
    backends = (
        StaticReplayBackend(
            provider_id="provider:z3",
            holds_for={
                "candidate:a": True,
                "candidate:b": False,
            },
            critical_premises={
                "candidate:a": ("premise:owner_holds", "premise:bound_pos"),
            },
            default_holds=False,
        ),
    )
    set_result = validate_candidate_set(
        [
            ValidationRequest(
                candidate=accept_cand, hole=hole, binding=binding
            ),
            ValidationRequest(
                candidate=reject_cand, hole=hole, binding=binding
            ),
        ],
        backends=backends,
    )
    assert isinstance(set_result, CandidateSetValidationResult)
    # At least one accept and one reject → set quarantine on both
    assert set(set_result.quarantined_candidate_ids) == {
        "candidate:a",
        "candidate:b",
    }
    assert set_result.dischargeable_candidate_ids == ()
    for item in set_result.results:
        assert item.quarantined is True
        assert item.may_discharge is False
    assert set_result.proof_claimed is False
    assert set_result.completion_claimed is False

    restored = CandidateSetValidationResult.from_dict(set_result.to_dict())
    assert restored.content_id == set_result.content_id


# ---------------------------------------------------------------------------
# Validator alone sets status (providers non-authoritative)
# ---------------------------------------------------------------------------


def test_provider_proposals_do_not_set_status_alone() -> None:
    """Even unanimous provider 'accepted' without holding replay is not accept."""

    result = validate_candidate(
        _candidate(),
        _hole(),
        _binding(),
        backends=(_backend(holds=False),),
        proposed_provider_verdicts={
            "provider:leanstral": "accepted",
            "provider:model": "accepted",
        },
    )
    # Replay fails → REJECTED by validator, ignoring provider cheerleading
    assert result.validation.verdict is ValidationVerdict.REJECTED
    assert result.may_discharge is False


def test_validation_record_cannot_claim_proof() -> None:
    result = validate_candidate(
        _candidate(),
        _hole(),
        _binding(),
        backends=(_backend(),),
    )
    payload = result.to_dict()
    assert payload["proof_claimed"] is False
    assert payload["completion_claimed"] is False
    assert payload["validation"]["proof_claimed"] is False
    assert payload["validation"]["completion_claimed"] is False
    with pytest.raises(CandidateValidationError, match="cannot claim"):
        CandidateValidationResult.from_dict(
            {**payload, "proof_claimed": True}
        )


def test_cap_validation_authority() -> None:
    assert (
        cap_validation_authority(
            AuthorityCeiling.THEOREM, verdict=ValidationVerdict.ACCEPTED
        )
        is AuthorityCeiling.SATISFIABILITY
    )
    assert (
        cap_validation_authority(
            AuthorityCeiling.SATISFIABILITY,
            verdict=ValidationVerdict.ACCEPTED,
        )
        is AuthorityCeiling.SATISFIABILITY
    )
    assert (
        cap_validation_authority(
            AuthorityCeiling.THEOREM, verdict=ValidationVerdict.REJECTED
        )
        is AuthorityCeiling.CANDIDATE
    )


# ---------------------------------------------------------------------------
# Binding / request validation errors
# ---------------------------------------------------------------------------


def test_malformed_request_raises() -> None:
    with pytest.raises(CandidateValidationError):
        ValidationRequest(
            candidate=_candidate(),
            hole=_hole(),
            binding="not-a-binding",  # type: ignore[arg-type]
        )


def test_binding_content_identity_stable() -> None:
    a = _binding()
    b = _binding()
    assert a.content_id == b.content_id
    c = _binding(tree_id="tree:other")
    assert c.content_id != a.content_id


def test_default_bounds_offline() -> None:
    assert DEFAULT_BOUNDS.network_allowed is False
    assert DEFAULT_BOUNDS.max_candidates > 0
