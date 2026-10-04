"""Unit tests for MissingProofAbduction@1 (FVT-023 / FVT-G032).

Acceptance:

* Candidates are relevant, consistent, source/scoped, non-circular,
  non-vacuous, and weak under the declared finite theory/budget.
* Arbitrary goal-entailing assumptions and contradictions are rejected.
* Impossible targets return a core/witness or honest unknown.
* Generated premises are never inserted into the trusted assumption set.
"""

from __future__ import annotations

from typing import Any

import pytest

from ipfs_datasets_py.logic.software_verification.tactician.contracts import (
    AssumptionBinding,
    AssumptionClass,
    AuthorityCeiling,
    HoleKind,
    HoleStatus,
    ProofHole,
    PropertyClass,
    ResourceBounds,
    SourceSpanBinding,
)
from ipfs_datasets_py.logic.software_verification.tactician.abduction import (
    ABDUCTION_ALGORITHM_VERSION,
    MISSING_PROOF_ABDUCTION_INTERFACE,
    AbductionCandidate,
    AbductionError,
    AbductionRequest,
    AbductionResult,
    AbductionStatus,
    FiniteTheory,
    MissingProofAbduction,
    PremiseClass,
    RejectionReason,
    UnsatCoreWitness,
    abduct_missing_premises,
    cap_candidate_authority,
    check_admissibility,
    classify_hole_kind,
    classify_premise_classes,
    detect_impossible_goal,
    is_contradiction_statement,
    is_goal_entailing_assumption,
    is_non_proof_premise_class,
    is_vacuous_statement,
)


# ---------------------------------------------------------------------------
# Fixtures
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
        "wall_time_ms": 30_000,
        "memory_bytes": 256 * 1024 * 1024,
        "max_steps": 64,
        "max_depth": 8,
        "max_nodes": 64,
        "max_candidates": 16,
        "network_allowed": False,
    }
    payload.update(overrides)
    return ResourceBounds(**payload)


def _theory(**overrides: Any) -> FiniteTheory:
    payload: dict[str, Any] = {
        "theory_id": "theory:lease-v1",
        "goal_statement": "lease_ready(owner, token)",
        "known_facts": (
            "owner_holds_token",
            "bound > 0",
        ),
        "axioms": ("token_unique",),
        "symbols": (
            "owner",
            "token",
            "lease_ready",
            "owner_holds_token",
            "bound",
            "claim_lease",
        ),
        "goal_id": "formal:lease-ready",
        "logic_family": "finite_fragment",
    }
    payload.update(overrides)
    return FiniteTheory(**payload)


def _hole(
    hole_id: str = "hole:loop-inv-1",
    *,
    kind: HoleKind = HoleKind.LOOP_INVARIANT,
    status: HoleStatus = HoleStatus.OPEN,
    reason: str = "missing loop invariant at claim_loop",
    statement: str = "missing loop_invariant",
    formal_goal_id: str = "formal:lease-ready",
    **overrides: Any,
) -> ProofHole:
    payload: dict[str, Any] = {
        "hole_id": hole_id,
        "kind": kind,
        "reason": reason,
        "source": _source(),
        "formal_goal_id": formal_goal_id,
        "expected_authority": AuthorityCeiling.SATISFIABILITY,
        "status": status,
        "property_class": PropertyClass.INVARIANCE,
        "statement": statement,
        "provider_ids": ("provider:z3",),
        "bounds": _bounds(),
        "proof_claimed": False,
        "completion_claimed": False,
    }
    payload.update(overrides)
    return ProofHole(**payload)


def _request(
    holes: tuple[ProofHole, ...] | None = None,
    *,
    theory: FiniteTheory | None = None,
    proposed: tuple[str, ...] = (),
    **overrides: Any,
) -> AbductionRequest:
    payload: dict[str, Any] = {
        "formal_goal_id": "formal:lease-ready",
        "theory": theory or _theory(),
        "holes": holes if holes is not None else (_hole(),),
        "bounds": _bounds(),
        "tree_id": "tree:repo@abc",
        "proposed_premises": proposed,
    }
    payload.update(overrides)
    return AbductionRequest(**payload)


# ---------------------------------------------------------------------------
# Interface / vocabulary
# ---------------------------------------------------------------------------


def test_interface_constant() -> None:
    assert MISSING_PROOF_ABDUCTION_INTERFACE == "MissingProofAbduction@1"
    assert (
        MissingProofAbduction.INTERFACE == MISSING_PROOF_ABDUCTION_INTERFACE
    )
    assert ABDUCTION_ALGORITHM_VERSION.startswith("missing-proof-abduction/")


def test_premise_classes_cover_required_taxonomy() -> None:
    classes = {c.value for c in classify_premise_classes()}
    required = {
        "fact_to_prove",
        "environment_assumption",
        "synthesize_invariant",
        "synthesize_contract",
        "synthesize_lemma",
        "unsupported_semantics",
        "unavailable_authority",
        "implementation_change",
    }
    assert required.issubset(classes)


def test_classify_hole_kind_mapping() -> None:
    assert (
        classify_hole_kind(HoleKind.LOOP_INVARIANT)
        is PremiseClass.SYNTHESIZE_INVARIANT
    )
    assert (
        classify_hole_kind(HoleKind.CALLEE_PRECONDITION)
        is PremiseClass.SYNTHESIZE_CONTRACT
    )
    assert (
        classify_hole_kind(HoleKind.BRIDGE_LEMMA)
        is PremiseClass.SYNTHESIZE_LEMMA
    )
    assert (
        classify_hole_kind(HoleKind.TEMPORAL_FAIRNESS)
        is PremiseClass.ENVIRONMENT_ASSUMPTION
    )
    assert (
        classify_hole_kind(HoleKind.MISSING_SOURCE_FACT)
        is PremiseClass.FACT_TO_PROVE
    )
    assert (
        classify_hole_kind(HoleKind.UNSUPPORTED_SEMANTICS)
        is PremiseClass.UNSUPPORTED_SEMANTICS
    )
    assert (
        classify_hole_kind(HoleKind.UNAVAILABLE_TOOL)
        is PremiseClass.UNAVAILABLE_AUTHORITY
    )
    assert (
        classify_hole_kind(HoleKind.REQUIRED_IMPLEMENTATION_CHANGE)
        is PremiseClass.IMPLEMENTATION_CHANGE
    )
    assert is_non_proof_premise_class(PremiseClass.UNSUPPORTED_SEMANTICS)
    assert not is_non_proof_premise_class(PremiseClass.FACT_TO_PROVE)


def test_cap_candidate_authority() -> None:
    assert (
        cap_candidate_authority(AuthorityCeiling.THEOREM)
        is AuthorityCeiling.CANDIDATE
    )
    assert (
        cap_candidate_authority(AuthorityCeiling.ADVISORY)
        is AuthorityCeiling.ADVISORY
    )
    assert (
        cap_candidate_authority(AuthorityCeiling.CANDIDATE)
        is AuthorityCeiling.CANDIDATE
    )


# ---------------------------------------------------------------------------
# Classification of holes into premise classes
# ---------------------------------------------------------------------------


def test_abduction_classifies_all_premise_kinds() -> None:
    holes = (
        _hole(
            "hole:inv",
            kind=HoleKind.LOOP_INVARIANT,
            statement="inv(owner_holds_token)",
            reason="need loop invariant over owner token",
        ),
        _hole(
            "hole:pre",
            kind=HoleKind.CALLEE_PRECONDITION,
            statement="requires(bound > 0)",
            reason="callee needs bound precondition",
            property_class=PropertyClass.CONTRACT,
        ),
        _hole(
            "hole:bridge",
            kind=HoleKind.BRIDGE_LEMMA,
            statement="lemma_bridge(smt, lean)",
            reason="bridge lemma between smt and lean",
        ),
        _hole(
            "hole:fair",
            kind=HoleKind.TEMPORAL_FAIRNESS,
            statement="fair(scheduler)",
            reason="fairness environment assumption",
            property_class=PropertyClass.LIVENESS,
        ),
        _hole(
            "hole:fact",
            kind=HoleKind.MISSING_SOURCE_FACT,
            statement="source_fact(lease_ready)",
            reason="missing source fact about lease",
        ),
        _hole(
            "hole:sem",
            kind=HoleKind.UNSUPPORTED_SEMANTICS,
            statement="unsupported_semantics(inline_asm)",
            reason="inline assembly unsupported",
            status=HoleStatus.UNSUPPORTED,
        ),
        _hole(
            "hole:tool",
            kind=HoleKind.UNAVAILABLE_TOOL,
            statement="unavailable_authority(provider:isabelle)",
            reason="isabelle unavailable",
            status=HoleStatus.UNAVAILABLE,
        ),
        _hole(
            "hole:impl",
            kind=HoleKind.REQUIRED_IMPLEMENTATION_CHANGE,
            statement="implementation_change(add_lock)",
            reason="implementation must add lock",
            status=HoleStatus.FALSE,
        ),
    )
    result = MissingProofAbduction().abduct(_request(holes=holes))
    classes_seen = {c.premise_class for c in result.candidates}
    assert PremiseClass.SYNTHESIZE_INVARIANT in classes_seen
    assert PremiseClass.SYNTHESIZE_CONTRACT in classes_seen
    assert PremiseClass.SYNTHESIZE_LEMMA in classes_seen
    assert PremiseClass.ENVIRONMENT_ASSUMPTION in classes_seen
    assert PremiseClass.FACT_TO_PROVE in classes_seen
    assert PremiseClass.UNSUPPORTED_SEMANTICS in classes_seen
    assert PremiseClass.UNAVAILABLE_AUTHORITY in classes_seen
    assert PremiseClass.IMPLEMENTATION_CHANGE in classes_seen
    # Classification index populated
    assert result.classified_by_class
    assert "synthesize_invariant" in result.classified_by_class


# ---------------------------------------------------------------------------
# Acceptance: relevant, consistent, source/scoped, non-circular, non-vacuous, weak
# ---------------------------------------------------------------------------


def test_admissible_candidates_satisfy_all_flags() -> None:
    hole = _hole(
        statement="inv(owner_holds_token)",
        reason="need invariant owner_holds_token for claim_lease",
    )
    result = abduct_missing_premises(
        _request(
            holes=(hole,),
            proposed=("owner_holds_token",),
        )
    )
    assert result.proof_claimed is False
    assert result.completion_claimed is False
    admissible = result.admissible_candidates
    assert admissible, f"expected admissible candidates; rejected={result.rejected}"
    for cand in admissible:
        assert cand.relevant is True
        assert cand.consistent is True
        assert cand.source_scoped is True
        assert cand.non_circular is True
        assert cand.non_vacuous is True
        assert cand.weak is True
        assert cand.admissible is True
        assert cand.admitted_to_trusted is False
        assert cand.proof_claimed is False
        assert cand.completion_claimed is False
        assert cand.authority in {
            AuthorityCeiling.NONE,
            AuthorityCeiling.ADVISORY,
            AuthorityCeiling.CANDIDATE,
        }
        flags = cand.admissibility_flags()
        assert all(flags.values())
        # Source scoped to hole
        assert cand.source.tree_id == hole.source.tree_id
        assert cand.hole_id == hole.hole_id


def test_irrelevant_premise_rejected() -> None:
    theory = _theory(symbols=("owner", "token"), known_facts=(), axioms=())
    report = check_admissibility(
        "completely_unrelated_xyzzy_foobar",
        theory=theory,
        hole=_hole(statement="inv(owner)", reason="owner invariant"),
        premise_class=PremiseClass.FACT_TO_PROVE,
    )
    assert report.ok is False
    assert report.rejection is RejectionReason.IRRELEVANT


def test_inconsistent_premise_rejected() -> None:
    theory = _theory(known_facts=("owner_holds_token",))
    report = check_admissibility(
        "not owner_holds_token",
        theory=theory,
        hole=_hole(
            statement="inv(owner_holds_token)",
            reason="need owner_holds_token",
        ),
        premise_class=PremiseClass.ENVIRONMENT_ASSUMPTION,
    )
    assert report.ok is False
    assert report.rejection is RejectionReason.INCONSISTENT


def test_unscoped_hole_rejected() -> None:
    bare = SourceSpanBinding()  # no tree / source refs
    hole = _hole(source=bare)
    report = check_admissibility(
        "owner_holds_token",
        theory=_theory(),
        hole=hole,
        premise_class=PremiseClass.SYNTHESIZE_INVARIANT,
    )
    assert report.ok is False
    assert report.rejection is RejectionReason.UNSCOPED


def test_circular_restatement_of_obligation_rejected() -> None:
    hole = _hole(
        kind=HoleKind.MISSING_SOURCE_FACT,
        statement="owner_holds_token",
        reason="need fact owner_holds_token",
    )
    report = check_admissibility(
        "owner_holds_token",
        theory=_theory(),
        hole=hole,
        premise_class=PremiseClass.FACT_TO_PROVE,
    )
    assert report.ok is False
    assert report.rejection is RejectionReason.CIRCULAR


def test_vacuous_premise_rejected() -> None:
    assert is_vacuous_statement("true")
    assert is_vacuous_statement("TRUE")
    assert is_vacuous_statement("⊤")
    report = check_admissibility(
        "true",
        theory=_theory(),
        hole=_hole(),
        premise_class=PremiseClass.ENVIRONMENT_ASSUMPTION,
    )
    assert report.ok is False
    assert report.rejection is RejectionReason.VACUOUS


def test_weaker_preferred_over_stronger() -> None:
    """When a weaker alternative exists, a stronger superstring is rejected."""

    theory = _theory()
    hole = _hole(
        statement="inv(owner_holds_token)",
        reason="need owner_holds_token invariant",
    )
    weaker = "owner_holds_token"
    stronger = "owner_holds_token and token_unique and bound > 0 and extra_strong"
    report_weak = check_admissibility(
        weaker,
        theory=theory,
        hole=hole,
        premise_class=PremiseClass.SYNTHESIZE_INVARIANT,
    )
    assert report_weak.ok is True
    report_strong = check_admissibility(
        stronger,
        theory=theory,
        hole=hole,
        premise_class=PremiseClass.SYNTHESIZE_INVARIANT,
        stronger_than=(weaker,),
    )
    assert report_strong.ok is False
    assert report_strong.rejection is RejectionReason.TOO_STRONG


def test_candidates_sorted_by_weakness() -> None:
    hole = _hole(
        statement="inv(owner_holds_token)",
        reason="owner token invariant for claim_lease",
    )
    result = MissingProofAbduction().abduct(
        _request(
            holes=(hole,),
            proposed=(
                "owner_holds_token",
                "owner_holds_token and token_unique",
            ),
        )
    )
    scores = [c.weakness_score_millionths for c in result.admissible_candidates]
    assert scores == sorted(scores, reverse=True)


# ---------------------------------------------------------------------------
# Acceptance: arbitrary goal-entailing assumptions and contradictions rejected
# ---------------------------------------------------------------------------


def test_goal_entailing_assumption_rejected() -> None:
    theory = _theory(goal_statement="lease_ready(owner, token)")
    assert is_goal_entailing_assumption(
        "lease_ready(owner, token)",
        theory.goal_statement,
        goal_ids=(theory.goal_id,),
    )
    assert is_goal_entailing_assumption(
        "assume lease_ready(owner, token)",
        theory.goal_statement,
    )
    assert is_goal_entailing_assumption("goal", theory.goal_statement)

    result = abduct_missing_premises(
        _request(
            holes=(),
            theory=theory,
            proposed=(
                "lease_ready(owner, token)",
                "assume lease_ready(owner, token)",
                "goal",
            ),
            tree_id="tree:repo@abc",
        )
    )
    reasons = {r.reason for r in result.rejected}
    assert RejectionReason.GOAL_ENTAILING in reasons
    # No admitted candidate is the goal itself
    for cand in result.candidates:
        assert (
            cand.statement.lower().strip()
            != theory.goal_statement.lower().strip()
        )


def test_contradiction_premise_rejected() -> None:
    assert is_contradiction_statement("false")
    assert is_contradiction_statement("⊥")
    report = check_admissibility(
        "false",
        theory=_theory(),
        hole=_hole(),
        premise_class=PremiseClass.ENVIRONMENT_ASSUMPTION,
    )
    assert report.ok is False
    assert report.rejection is RejectionReason.CONTRADICTION

    result = abduct_missing_premises(
        _request(
            holes=(),
            proposed=("false", "contradiction"),
            tree_id="tree:repo@abc",
        )
    )
    reasons = {r.reason for r in result.rejected}
    assert RejectionReason.CONTRADICTION in reasons
    assert all(not c.admissible or c.statement.lower() not in {"false", "contradiction"}
               for c in result.candidates)


def test_engine_rejects_goal_and_contradiction_in_mixed_batch() -> None:
    hole = _hole(
        statement="inv(owner_holds_token)",
        reason="need owner_holds_token",
    )
    result = MissingProofAbduction().abduct(
        _request(
            holes=(hole,),
            proposed=(
                "true",
                "false",
                "lease_ready(owner, token)",
                "owner_holds_token",
            ),
        )
    )
    rejected_reasons = {r.reason for r in result.rejected}
    assert RejectionReason.VACUOUS in rejected_reasons
    assert RejectionReason.CONTRADICTION in rejected_reasons
    assert RejectionReason.GOAL_ENTAILING in rejected_reasons
    # Good premise may still be admitted
    statements = {c.statement for c in result.admissible_candidates}
    assert any("owner_holds_token" in s for s in statements)


# ---------------------------------------------------------------------------
# Acceptance: impossible targets return core/witness or honest unknown
# ---------------------------------------------------------------------------


def test_impossible_goal_returns_unsat_core() -> None:
    theory = _theory(
        goal_statement="not owner_holds_token",
        known_facts=("owner_holds_token",),
    )
    core = detect_impossible_goal(theory)
    assert core is not None
    assert isinstance(core, UnsatCoreWitness)
    assert "owner_holds_token" in core.conflicting_statements

    result = MissingProofAbduction().abduct(
        _request(holes=(_hole(),), theory=theory)
    )
    assert result.status is AbductionStatus.IMPOSSIBLE
    assert result.unsat_core is not None
    assert result.unsat_core.conflicting_statements
    assert result.candidates == ()
    assert result.proof_claimed is False


def test_false_goal_returns_core() -> None:
    theory = _theory(goal_statement="false", known_facts=())
    result = abduct_missing_premises(_request(holes=(), theory=theory))
    assert result.status is AbductionStatus.IMPOSSIBLE
    assert result.unsat_core is not None
    assert result.unsat_core.witness_kind in {"false_goal", "unsat_core"}


def test_internally_inconsistent_theory_returns_core() -> None:
    theory = _theory(
        known_facts=("owner_holds_token", "not owner_holds_token"),
        goal_statement="lease_ready(owner, token)",
    )
    core = detect_impossible_goal(theory)
    assert core is not None
    assert core.witness_kind == "theory_inconsistency"


def test_all_rejected_returns_honest_unknown() -> None:
    theory = _theory()
    result = abduct_missing_premises(
        _request(
            holes=(),
            theory=theory,
            proposed=("true", "false", "lease_ready(owner, token)"),
            tree_id="tree:repo@abc",
        )
    )
    assert result.status in {
        AbductionStatus.UNKNOWN,
        AbductionStatus.EMPTY,
    }
    assert result.admissible_candidates == ()
    # Honest: diagnostics or rejected explain the outcome
    assert result.rejected or result.diagnostics


# ---------------------------------------------------------------------------
# Conflict policy: never insert into trusted assumption set
# ---------------------------------------------------------------------------


def test_candidate_cannot_be_admitted_to_trusted() -> None:
    with pytest.raises(AbductionError, match="admitted_to_trusted"):
        AbductionCandidate(
            candidate_id="abd:x",
            premise_class=PremiseClass.FACT_TO_PROVE,
            statement="owner_holds_token",
            hole_id="hole:x",
            source=_source(),
            admitted_to_trusted=True,
        )


def test_candidate_cannot_use_trusted_assumption_class() -> None:
    with pytest.raises(AbductionError, match="TRUSTED"):
        AbductionCandidate(
            candidate_id="abd:x",
            premise_class=PremiseClass.ENVIRONMENT_ASSUMPTION,
            statement="fair(scheduler)",
            hole_id="hole:fair",
            source=_source(),
            assumption_class=AssumptionClass.TRUSTED,
        )


def test_candidate_projects_only_hypothetical_assumption() -> None:
    cand = AbductionCandidate(
        candidate_id="abd:env",
        premise_class=PremiseClass.ENVIRONMENT_ASSUMPTION,
        statement="fair(scheduler)",
        hole_id="hole:fair",
        source=_source(),
        assumption_class=AssumptionClass.HYPOTHETICAL,
        reviewable=True,
    )
    binding = cand.to_assumption_binding()
    assert binding.assumption_class is AssumptionClass.HYPOTHETICAL
    assert binding.reviewable is True
    assert binding.authority in {
        AuthorityCeiling.NONE,
        AuthorityCeiling.ADVISORY,
        AuthorityCeiling.CANDIDATE,
    }


def test_theory_rejects_hypothetical_in_trusted_assumptions() -> None:
    with pytest.raises(AbductionError, match="hypothetical"):
        FiniteTheory(
            theory_id="theory:bad",
            goal_statement="G",
            trusted_assumptions=(
                AssumptionBinding(
                    assumption_id="a1",
                    assumption_class=AssumptionClass.HYPOTHETICAL,
                    statement="H",
                ),
            ),
        )


def test_result_and_candidate_reject_proof_claims() -> None:
    result = MissingProofAbduction().abduct(_request())
    payload = result.to_dict()
    payload["proof_claimed"] = True
    with pytest.raises(AbductionError, match="proof or completion"):
        AbductionResult.from_dict(payload)

    if result.candidates:
        cp = result.candidates[0].to_dict()
        cp["completion_claimed"] = True
        with pytest.raises(AbductionError, match="proof or completion"):
            AbductionCandidate.from_dict(cp)


def test_environment_assumptions_remain_reviewable() -> None:
    hole = _hole(
        kind=HoleKind.TEMPORAL_FAIRNESS,
        statement="fair(scheduler)",
        reason="fairness for scheduler liveness",
        property_class=PropertyClass.LIVENESS,
    )
    result = MissingProofAbduction().abduct(_request(holes=(hole,)))
    env = result.candidates_of_class(PremiseClass.ENVIRONMENT_ASSUMPTION)
    assert env
    for cand in env:
        assert cand.reviewable is True
        assert cand.admitted_to_trusted is False
        assert cand.assumption_class is not AssumptionClass.TRUSTED


# ---------------------------------------------------------------------------
# Budget / termination / round-trip
# ---------------------------------------------------------------------------


def test_budget_exhaustion_is_explicit() -> None:
    holes = tuple(
        _hole(
            f"hole:inv-{i}",
            statement=f"inv(owner_holds_token_{i})",
            reason=f"need owner token invariant {i}",
        )
        for i in range(20)
    )
    result = MissingProofAbduction(
        bounds=_bounds(max_steps=3, max_candidates=2),
        max_candidates_per_hole=1,
    ).abduct(
        _request(holes=holes, bounds=_bounds(max_steps=3, max_candidates=2))
    )
    assert result.budget_exhausted is True or result.status in {
        AbductionStatus.BOUNDED,
        AbductionStatus.PARTIAL,
        AbductionStatus.CANDIDATES,
    }
    assert result.steps_used >= 0


def test_result_round_trips_to_dict() -> None:
    result = MissingProofAbduction().abduct(_request())
    record = result.to_record()
    assert record["interface"] == MISSING_PROOF_ABDUCTION_INTERFACE
    assert record["algorithm_version"] == ABDUCTION_ALGORITHM_VERSION
    assert record["proof_claimed"] is False
    assert "content_id" in record
    restored = AbductionResult.from_dict(result.to_dict())
    assert restored.result_id == result.result_id
    assert restored.status is result.status
    assert len(restored.candidates) == len(result.candidates)
    assert restored.content_id == result.content_id


def test_empty_request_returns_empty_status() -> None:
    result = abduct_missing_premises(
        _request(holes=(), proposed=(), tree_id="tree:repo@abc")
    )
    assert result.status is AbductionStatus.EMPTY
    assert result.candidates == ()


def test_finite_theory_round_trip() -> None:
    theory = _theory(
        trusted_assumptions=(
            AssumptionBinding(
                assumption_id="a:trusted",
                assumption_class=AssumptionClass.TRUSTED,
                statement="token_unique",
                authority=AuthorityCeiling.BOUNDED,
                reviewable=False,
            ),
        )
    )
    restored = FiniteTheory.from_dict(theory.to_dict())
    assert restored.theory_id == theory.theory_id
    assert restored.goal_statement == theory.goal_statement
    assert len(restored.trusted_assumptions) == 1
    assert restored.content_id == theory.content_id


def test_module_level_abduct_helper() -> None:
    result = abduct_missing_premises(
        {
            "formal_goal_id": "formal:lease-ready",
            "theory": _theory().to_dict(),
            "holes": [_hole(statement="inv(owner_holds_token)").to_dict()],
            "bounds": _bounds().to_dict(),
            "tree_id": "tree:repo@abc",
            "proposed_premises": ["owner_holds_token"],
        }
    )
    assert result.INTERFACE == MISSING_PROOF_ABDUCTION_INTERFACE
    assert result.formal_goal_id == "formal:lease-ready"


def test_non_proof_diagnostics_are_not_admissible_premises() -> None:
    hole = _hole(
        kind=HoleKind.UNSUPPORTED_SEMANTICS,
        statement="unsupported_semantics(asm)",
        reason="inline asm",
        status=HoleStatus.UNSUPPORTED,
    )
    result = MissingProofAbduction().abduct(_request(holes=(hole,)))
    diags = result.candidates_of_class(PremiseClass.UNSUPPORTED_SEMANTICS)
    assert diags
    for d in diags:
        assert d.admissible is False
        assert is_non_proof_premise_class(d.premise_class)
