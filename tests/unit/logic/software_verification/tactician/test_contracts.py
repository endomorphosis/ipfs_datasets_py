"""Unit tests for closed tactician contracts (FVT-007 / FVT-G021).

Covers EndGoalSpec@1, ProofHole@1, ProofObligationGraph@1, and
GoalDirectedProofPlan@1 plus interpretation, FormalGoal, candidate,
validation, and completion contracts:

* closed schemas bind tree/source spans/current/target state/property/
  quantifiers/environment/assumptions by class/logic/providers/bounds/
  ambiguity/provenance/authority/status;
* identities change under every semantic binding; and
* proposals cannot claim proof or completion.
"""

from __future__ import annotations

import copy
from typing import Any

import pytest

from ipfs_datasets_py.logic.software_verification.tactician.contracts import (
    END_GOAL_SPEC_INTERFACE,
    END_GOAL_SPEC_SCHEMA,
    GOAL_COMPLETION_SCHEMA,
    GOAL_DIRECTED_PROOF_PLAN_INTERFACE,
    GOAL_DIRECTED_PROOF_PLAN_SCHEMA,
    PROOF_HOLE_INTERFACE,
    PROOF_HOLE_SCHEMA,
    PROOF_OBLIGATION_GRAPH_INTERFACE,
    PROOF_OBLIGATION_GRAPH_SCHEMA,
    AmbiguityStatus,
    AssumptionBinding,
    AssumptionClass,
    AuthorityCeiling,
    CandidateProofStep,
    CandidateStatus,
    CandidateValidation,
    CompletionVerdict,
    EndGoalInterpretation,
    EndGoalSpec,
    FormalGoal,
    GoalCompletion,
    GoalDirectedProofPlan,
    GraphEdgeKind,
    GraphNodeKind,
    HoleKind,
    HoleStatus,
    PhraseProvenance,
    PlanStatus,
    ProofGraphEdge,
    ProofGraphNode,
    ProofHole,
    ProofObligationGraph,
    PropertyClass,
    QuantifierKind,
    ResourceBounds,
    SourceSpanBinding,
    TacticianContractError,
    ValidationRecipe,
    ValidationVerdict,
    content_identity,
    end_goal_spec_from_goal_development_mapping,
    goal_directed_plan_from_supervisor_proof_plan,
)


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
        "wall_time_ms": 5_000,
        "memory_bytes": 64 * 1024 * 1024,
        "max_steps": 32,
        "max_depth": 8,
        "max_nodes": 64,
        "max_candidates": 16,
        "network_allowed": False,
    }
    payload.update(overrides)
    return ResourceBounds(**payload)


def _assumption(
    assumption_id: str = "assumption:token-order",
    *,
    assumption_class: AssumptionClass = AssumptionClass.MUST_PROVE,
) -> AssumptionBinding:
    return AssumptionBinding(
        assumption_id=assumption_id,
        assumption_class=assumption_class,
        kind="semantic",
        statement="tokens are totally ordered",
        source=_source(),
        authority=AuthorityCeiling.NONE,
        reviewable=True,
    )


def _interpretation(
    interpretation_id: str = "interp:exists-ready",
    *,
    property_class: PropertyClass = PropertyClass.EXISTENTIAL_REACHABILITY,
    selected: bool = False,
) -> EndGoalInterpretation:
    return EndGoalInterpretation(
        interpretation_id=interpretation_id,
        controlled_english="Some execution reaches ready.",
        property_class=property_class,
        quantifiers=(QuantifierKind.EXISTS, QuantifierKind.EVENTUALLY),
        current_state={"phase": "init"},
        target_state={"phase": "ready"},
        environment={"scheduler": "fair"},
        semantic_diff={"vs_invariant": "does not require all executions"},
        unresolved_fields=(),
        selected=selected,
    )


def _end_goal(**overrides: Any) -> EndGoalSpec:
    payload: dict[str, Any] = {
        "goal_id": "goal:lease-ready",
        "root_goal_id": "goal:lease-ready",
        "caller_text": "the system reaches ready",
        "source": _source(),
        "property_class": PropertyClass.EXISTENTIAL_REACHABILITY,
        "quantifiers": (QuantifierKind.EXISTS, QuantifierKind.EVENTUALLY),
        "actors": ("scheduler", "worker"),
        "state_variables": ("phase", "owner"),
        "current_state": {"phase": "init"},
        "target_state": {"phase": "ready"},
        "transitions": ("claim", "release"),
        "environment": {"network": "async"},
        "interference": {"preempt": True},
        "assumptions": (_assumption(),),
        "logic_family": "temporal.ltl",
        "provider_ids": ("provider:z3",),
        "assurance_target": AuthorityCeiling.BOUNDED,
        "bounds": _bounds(),
        "provenance": (
            PhraseProvenance(
                phrase="reaches ready",
                clause_id="clause:target-ready",
                source_ref_ids=("source:prompt",),
                span_ids=("span:prompt-1",),
                start_offset=11,
                end_offset=24,
            ),
        ),
        "interpretations": (
            _interpretation("interp:exists-ready"),
            _interpretation(
                "interp:forall-ready",
                property_class=PropertyClass.UNIVERSAL_REACHABILITY,
            ),
        ),
        "ambiguity_status": AmbiguityStatus.REQUIRES_SELECTION,
        "unsupported_semantics": (),
        "translation_loss": (),
        "acceptance_evidence": ("receipt:kernel",),
        "expected_receipt_classes": ("proof-receipt", "counterexample"),
        "status": "draft",
        "authority": AuthorityCeiling.ADVISORY,
        "proof_claimed": False,
        "completion_claimed": False,
    }
    payload.update(overrides)
    return EndGoalSpec(**payload)


def _formal_goal(end_goal: EndGoalSpec | None = None) -> FormalGoal:
    goal = end_goal or _end_goal(
        ambiguity_status=AmbiguityStatus.RESOLVED,
        interpretations=(
            _interpretation("interp:exists-ready", selected=True),
        ),
    )
    return FormalGoal(
        formal_goal_id="formal:lease-ready",
        end_goal=goal,
        selected_interpretation_id="interp:exists-ready",
        confirmation_receipt_id="receipt:confirm-1",
        status="confirmed",
        authority=AuthorityCeiling.DECLARATIVE,
        proof_claimed=False,
        completion_claimed=False,
    )


def _recipe() -> ValidationRecipe:
    return ValidationRecipe(
        recipe_id="recipe:smt-replay",
        checker_kind="smt_replay",
        provider_ids=("provider:z3",),
        required_authority=AuthorityCeiling.SATISFIABILITY,
        bounds=_bounds(max_steps=8),
        steps=("parse", "typecheck", "replay"),
        oracle_id="oracle:violation",
    )


def _hole(**overrides: Any) -> ProofHole:
    payload: dict[str, Any] = {
        "hole_id": "hole:loop-inv-1",
        "kind": HoleKind.LOOP_INVARIANT,
        "reason": "missing loop invariant for claim_lease",
        "source": _source(),
        "formal_goal_id": "formal:lease-ready",
        "expected_authority": AuthorityCeiling.SATISFIABILITY,
        "dependency_ids": ("hole:pre-1",),
        "validation_recipe": _recipe(),
        "status": HoleStatus.OPEN,
        "property_class": PropertyClass.INVARIANCE,
        "statement": "invariant(owner_holds_token)",
        "provider_ids": ("provider:z3",),
        "bounds": _bounds(),
        "proof_claimed": False,
        "completion_claimed": False,
    }
    payload.update(overrides)
    return ProofHole(**payload)


def _graph(**overrides: Any) -> ProofObligationGraph:
    root = ProofGraphNode(
        node_id="node:root",
        kind=GraphNodeKind.ROOT,
        obligation_id="obl:root",
        label="end goal",
        status=HoleStatus.OPEN,
        authority=AuthorityCeiling.NONE,
    )
    leaf = ProofGraphNode(
        node_id="node:leaf",
        kind=GraphNodeKind.LEAF,
        obligation_id="obl:inv",
        hole_id="hole:loop-inv-1",
        label="loop invariant",
        status=HoleStatus.OPEN,
        authority=AuthorityCeiling.CANDIDATE,
    )
    and_node = ProofGraphNode(
        node_id="node:and",
        kind=GraphNodeKind.AND,
        obligation_id="obl:and",
        label="joint obligations",
        status=HoleStatus.OPEN,
    )
    edge1 = ProofGraphEdge(
        edge_id="edge:root-and",
        source_node_id="node:root",
        target_node_id="node:and",
        kind=GraphEdgeKind.REGRESSION,
        inference_rule="weakest_precondition",
        reconstruction_method="source_vc",
    )
    edge2 = ProofGraphEdge(
        edge_id="edge:and-leaf",
        source_node_id="node:and",
        target_node_id="node:leaf",
        kind=GraphEdgeKind.DEPENDS_ON,
        inference_rule="and_intro",
        reconstruction_method="kernel",
    )
    payload: dict[str, Any] = {
        "graph_id": "graph:lease-1",
        "formal_goal_id": "formal:lease-ready",
        "root_node_id": "node:root",
        "nodes": (root, and_node, leaf),
        "edges": (edge1, edge2),
        "tree_id": "tree:repo@abc",
        "bounds": _bounds(max_nodes=32),
        "status": "open",
        "authority": AuthorityCeiling.NONE,
        "proof_claimed": False,
        "completion_claimed": False,
    }
    payload.update(overrides)
    return ProofObligationGraph(**payload)


def _candidate(**overrides: Any) -> CandidateProofStep:
    payload: dict[str, Any] = {
        "candidate_id": "cand:inv-a",
        "hole_id": "hole:loop-inv-1",
        "kind": "loop_invariant",
        "statement": "owner != null ==> holds(token)",
        "status": CandidateStatus.PROPOSED,
        "source": _source(),
        "provider_ids": ("provider:leanstral",),
        "authority": AuthorityCeiling.CANDIDATE,
        "rank_score_millionths": 750_000,
        "new_assumption_ids": (),
        "evidence_ids": (),
        "provenance": {"source": "template:houdini"},
        "proof_claimed": False,
        "completion_claimed": False,
    }
    payload.update(overrides)
    return CandidateProofStep(**payload)


def _plan(**overrides: Any) -> GoalDirectedProofPlan:
    cand_a = _candidate(candidate_id="cand:inv-a")
    cand_b = _candidate(
        candidate_id="cand:inv-b",
        statement="token_epoch increases",
        rank_score_millionths=500_000,
    )
    payload: dict[str, Any] = {
        "plan_id": "plan:lease-1",
        "formal_goal_id": "formal:lease-ready",
        "graph_id": "graph:lease-1",
        "tree_id": "tree:repo@abc",
        "candidates": (cand_a, cand_b),
        "step_order": ("cand:inv-a", "cand:inv-b"),
        "status": PlanStatus.RANKED,
        "bounds": _bounds(),
        "provider_ids": ("provider:z3", "provider:leanstral"),
        "rank_score_millionths": 800_000,
        "root_goal_id": "goal:lease-ready",
        "authority": AuthorityCeiling.CANDIDATE,
        "proof_claimed": False,
        "completion_claimed": False,
        "metadata": {"ranker": "utility-v1"},
    }
    payload.update(overrides)
    return GoalDirectedProofPlan(**payload)


# ---------------------------------------------------------------------------
# Interface and schema constants
# ---------------------------------------------------------------------------


def test_interface_and_schema_constants() -> None:
    assert END_GOAL_SPEC_INTERFACE == "EndGoalSpec@1"
    assert PROOF_HOLE_INTERFACE == "ProofHole@1"
    assert PROOF_OBLIGATION_GRAPH_INTERFACE == "ProofObligationGraph@1"
    assert GOAL_DIRECTED_PROOF_PLAN_INTERFACE == "GoalDirectedProofPlan@1"
    assert END_GOAL_SPEC_SCHEMA.endswith("@1")
    assert PROOF_HOLE_SCHEMA.endswith("@1")
    assert PROOF_OBLIGATION_GRAPH_SCHEMA.endswith("@1")
    assert GOAL_DIRECTED_PROOF_PLAN_SCHEMA.endswith("@1")
    assert GOAL_COMPLETION_SCHEMA.endswith("@1")


# ---------------------------------------------------------------------------
# EndGoalSpec closed bindings
# ---------------------------------------------------------------------------


def test_end_goal_spec_binds_required_semantic_fields() -> None:
    goal = _end_goal()
    record = goal.to_record()

    assert record["interface"] == END_GOAL_SPEC_INTERFACE
    assert record["schema"] == END_GOAL_SPEC_SCHEMA
    assert record["source"]["tree_id"] == "tree:repo@abc"
    assert "source:lease.py" in record["source"]["source_ref_ids"]
    assert "span:claim" in record["source"]["span_ids"]
    assert record["current_state"]["phase"] == "init"
    assert record["target_state"]["phase"] == "ready"
    assert record["property_class"] == PropertyClass.EXISTENTIAL_REACHABILITY.value
    assert QuantifierKind.EXISTS.value in record["quantifiers"]
    assert record["environment"]["network"] == "async"
    assert record["assumptions"][0]["assumption_class"] == (
        AssumptionClass.MUST_PROVE.value
    )
    assert record["logic_family"] == "temporal.ltl"
    assert "provider:z3" in record["provider_ids"]
    assert record["bounds"]["max_steps"] == 32
    assert record["ambiguity_status"] == AmbiguityStatus.REQUIRES_SELECTION.value
    assert record["provenance"][0]["clause_id"] == "clause:target-ready"
    assert record["authority"] == AuthorityCeiling.ADVISORY.value
    assert record["status"] == "draft"
    assert record["proof_claimed"] is False
    assert record["completion_claimed"] is False
    assert record["content_id"].startswith("sha256:")
    assert record["content_id"] == goal.content_id


def test_end_goal_requires_source_or_tree_binding() -> None:
    with pytest.raises(TacticianContractError, match="tree_id or source"):
        _end_goal(source=SourceSpanBinding())


def test_end_goal_round_trip_is_identity_stable() -> None:
    goal = _end_goal()
    restored = EndGoalSpec.from_dict(goal.to_dict())
    assert restored.content_id == goal.content_id
    assert restored.to_dict() == goal.to_dict()


def test_end_goal_rejects_unknown_fields() -> None:
    payload = _end_goal().to_dict()
    payload["smuggled_proof"] = True
    with pytest.raises(TacticianContractError, match="unsupported fields"):
        EndGoalSpec.from_dict(payload)


def test_end_goal_rejects_proof_and_completion_claims() -> None:
    with pytest.raises(TacticianContractError, match="cannot claim proof"):
        _end_goal(proof_claimed=True)
    with pytest.raises(TacticianContractError, match="cannot claim"):
        _end_goal(completion_claimed=True)

    payload = _end_goal().to_dict()
    payload["proof_claimed"] = True
    with pytest.raises(TacticianContractError, match="cannot claim"):
        EndGoalSpec.from_dict(payload)


def test_end_goal_rejects_elevated_self_authority() -> None:
    with pytest.raises(TacticianContractError, match="proof-level authority"):
        _end_goal(authority=AuthorityCeiling.THEOREM)


def test_identity_changes_under_every_semantic_binding() -> None:
    base = _end_goal()
    base_id = base.content_id

    variants = [
        _end_goal(source=_source(tree_id="tree:other")),
        _end_goal(source=_source(span_ids=("span:other",))),
        _end_goal(current_state={"phase": "running"}),
        _end_goal(target_state={"phase": "done"}),
        _end_goal(property_class=PropertyClass.SAFETY),
        _end_goal(quantifiers=(QuantifierKind.FORALL,)),
        _end_goal(environment={"network": "sync"}),
        _end_goal(
            assumptions=(
                _assumption(
                    "assumption:other",
                    assumption_class=AssumptionClass.TRUSTED,
                ),
            )
        ),
        _end_goal(logic_family="smt.qf_lia"),
        _end_goal(provider_ids=("provider:cvc5",)),
        _end_goal(bounds=_bounds(max_steps=1)),
        _end_goal(
            provenance=(
                PhraseProvenance(
                    phrase="ready forever",
                    clause_id="clause:other",
                    start_offset=0,
                    end_offset=12,
                ),
            )
        ),
        _end_goal(authority=AuthorityCeiling.NONE),
        _end_goal(status="confirmed-pending"),
        _end_goal(
            ambiguity_status=AmbiguityStatus.RESOLVED,
            interpretations=(_interpretation(selected=True),),
        ),
    ]
    for variant in variants:
        assert variant.content_id != base_id, variant.to_dict()


def test_forged_content_id_is_rejected() -> None:
    payload = _end_goal().to_dict()
    payload["content_id"] = "sha256:" + ("00" * 32)
    with pytest.raises(TacticianContractError, match="content identity"):
        EndGoalSpec.from_dict(payload)


# ---------------------------------------------------------------------------
# FormalGoal / interpretation
# ---------------------------------------------------------------------------


def test_formal_goal_requires_known_interpretation() -> None:
    with pytest.raises(TacticianContractError, match="selected_interpretation"):
        FormalGoal(
            formal_goal_id="formal:x",
            end_goal=_end_goal(
                ambiguity_status=AmbiguityStatus.RESOLVED,
                interpretations=(_interpretation("interp:a"),),
            ),
            selected_interpretation_id="interp:missing",
        )


def test_formal_goal_blocks_unresolved_ambiguity() -> None:
    with pytest.raises(TacticianContractError, match="ambiguity"):
        FormalGoal(
            formal_goal_id="formal:x",
            end_goal=_end_goal(
                ambiguity_status=AmbiguityStatus.REQUIRES_SELECTION
            ),
            selected_interpretation_id="interp:exists-ready",
        )


def test_formal_goal_preserves_root_goal_identity() -> None:
    formal = _formal_goal()
    assert formal.root_goal_id == "goal:lease-ready"
    assert formal.to_dict()["root_goal_id"] == "goal:lease-ready"
    assert formal.proof_claimed is False
    assert formal.completion_claimed is False


# ---------------------------------------------------------------------------
# ProofHole
# ---------------------------------------------------------------------------


def test_proof_hole_closed_fields_and_round_trip() -> None:
    hole = _hole()
    record = hole.to_record()
    assert record["interface"] == PROOF_HOLE_INTERFACE
    assert record["schema"] == PROOF_HOLE_SCHEMA
    assert record["kind"] == HoleKind.LOOP_INVARIANT.value
    assert record["source"]["span_ids"] == ["span:claim"]
    assert record["validation_recipe"]["checker_kind"] == "smt_replay"
    assert record["status"] == HoleStatus.OPEN.value
    assert record["proof_claimed"] is False
    restored = ProofHole.from_dict(hole.to_dict())
    assert restored.content_id == hole.content_id


def test_proof_hole_rejects_proof_claims() -> None:
    with pytest.raises(TacticianContractError, match="cannot claim"):
        _hole(proof_claimed=True)
    payload = _hole().to_dict()
    payload["completion_claimed"] = True
    with pytest.raises(TacticianContractError, match="cannot claim"):
        ProofHole.from_dict(payload)


def test_proof_hole_identity_changes_with_bindings() -> None:
    base = _hole()
    changed = [
        _hole(source=_source(tree_id="tree:other")),
        _hole(kind=HoleKind.FRAME),
        _hole(expected_authority=AuthorityCeiling.THEOREM),
        _hole(status=HoleStatus.CANDIDATE),
        _hole(statement="different"),
        _hole(provider_ids=("provider:cvc5",)),
        _hole(bounds=_bounds(max_depth=1)),
    ]
    for item in changed:
        assert item.content_id != base.content_id


# ---------------------------------------------------------------------------
# Proof obligation graph
# ---------------------------------------------------------------------------


def test_proof_graph_is_acyclic_and_round_trips() -> None:
    graph = _graph()
    record = graph.to_record()
    assert record["interface"] == PROOF_OBLIGATION_GRAPH_INTERFACE
    assert record["schema"] == PROOF_OBLIGATION_GRAPH_SCHEMA
    assert "hole:loop-inv-1" in record["hole_ids"]
    assert record["proof_claimed"] is False
    restored = ProofObligationGraph.from_dict(graph.to_dict())
    assert restored.content_id == graph.content_id


def test_proof_graph_rejects_cycles() -> None:
    with pytest.raises(TacticianContractError, match="acyclic"):
        _graph(
            edges=(
                ProofGraphEdge(
                    edge_id="e1",
                    source_node_id="node:root",
                    target_node_id="node:and",
                    kind=GraphEdgeKind.DEPENDS_ON,
                ),
                ProofGraphEdge(
                    edge_id="e2",
                    source_node_id="node:and",
                    target_node_id="node:leaf",
                    kind=GraphEdgeKind.DEPENDS_ON,
                ),
                ProofGraphEdge(
                    edge_id="e3",
                    source_node_id="node:leaf",
                    target_node_id="node:root",
                    kind=GraphEdgeKind.DEPENDS_ON,
                ),
            )
        )


def test_proof_graph_rejects_self_loop_edges() -> None:
    with pytest.raises(TacticianContractError, match="self-loops"):
        ProofGraphEdge(
            edge_id="e",
            source_node_id="n",
            target_node_id="n",
            kind=GraphEdgeKind.DEPENDS_ON,
        )


def test_proof_graph_rejects_proof_claims_and_unknown_root() -> None:
    with pytest.raises(TacticianContractError, match="cannot claim"):
        _graph(completion_claimed=True)
    with pytest.raises(TacticianContractError, match="root_node_id"):
        _graph(root_node_id="node:missing")


def test_proof_graph_identity_changes_with_structure() -> None:
    base = _graph()
    other = _graph(tree_id="tree:other")
    assert other.content_id != base.content_id
    other_nodes = _graph(
        nodes=(
            ProofGraphNode(
                node_id="node:root",
                kind=GraphNodeKind.ROOT,
                obligation_id="obl:root",
            ),
        ),
        edges=(),
        root_node_id="node:root",
    )
    assert other_nodes.content_id != base.content_id


# ---------------------------------------------------------------------------
# Candidates and plans
# ---------------------------------------------------------------------------


def test_candidate_cannot_claim_proof_or_elevated_authority() -> None:
    with pytest.raises(TacticianContractError, match="cannot claim"):
        _candidate(proof_claimed=True)
    with pytest.raises(TacticianContractError, match="capped at candidate"):
        _candidate(authority=AuthorityCeiling.THEOREM)


def test_plan_round_trip_and_interface() -> None:
    plan = _plan()
    record = plan.to_record()
    assert record["interface"] == GOAL_DIRECTED_PROOF_PLAN_INTERFACE
    assert record["schema"] == GOAL_DIRECTED_PROOF_PLAN_SCHEMA
    assert record["step_order"] == ["cand:inv-a", "cand:inv-b"]
    assert record["proof_claimed"] is False
    assert record["completion_claimed"] is False
    assert "COMPLETE" not in PlanStatus.__members__
    restored = GoalDirectedProofPlan.from_dict(plan.to_dict())
    assert restored.content_id == plan.content_id


def test_plan_rejects_proof_completion_and_smuggled_metadata() -> None:
    with pytest.raises(TacticianContractError, match="cannot claim"):
        _plan(completion_claimed=True)
    with pytest.raises(TacticianContractError, match="metadata"):
        _plan(metadata={"complete": True})
    payload = _plan().to_dict()
    payload["proof_claimed"] = True
    with pytest.raises(TacticianContractError, match="cannot claim"):
        GoalDirectedProofPlan.from_dict(payload)


def test_plan_identity_changes_with_candidates_and_bindings() -> None:
    base = _plan()
    changed = _plan(
        candidates=(
            _candidate(candidate_id="cand:inv-a", statement="other"),
        ),
        step_order=("cand:inv-a",),
    )
    assert changed.content_id != base.content_id
    assert _plan(tree_id="tree:other").content_id != base.content_id
    assert (
        _plan(status=PlanStatus.SELECTED).content_id != base.content_id
    )


def test_plan_rejects_unknown_step_order() -> None:
    with pytest.raises(TacticianContractError, match="unknown candidates"):
        _plan(step_order=("cand:missing",))


# ---------------------------------------------------------------------------
# Validation and completion
# ---------------------------------------------------------------------------


def test_candidate_validation_cannot_claim_goal_completion() -> None:
    validation = CandidateValidation(
        validation_id="val:1",
        candidate_id="cand:inv-a",
        hole_id="hole:loop-inv-1",
        verdict=ValidationVerdict.ACCEPTED,
        tree_id="tree:repo@abc",
        provider_id="provider:z3",
        provider_version="4.13.0",
        authority=AuthorityCeiling.SATISFIABILITY,
        recipe=_recipe(),
        assumption_ids=("assumption:token-order",),
        evidence_ids=("evidence:core-1",),
        minimality="bounded",
        proof_claimed=False,
        completion_claimed=False,
    )
    assert validation.to_dict()["proof_claimed"] is False
    assert validation.to_dict()["completion_claimed"] is False
    with pytest.raises(TacticianContractError, match="cannot claim"):
        CandidateValidation(
            validation_id="val:2",
            candidate_id="cand:inv-a",
            hole_id="hole:loop-inv-1",
            verdict=ValidationVerdict.ACCEPTED,
            tree_id="tree:repo@abc",
            authority=AuthorityCeiling.SATISFIABILITY,
            proof_claimed=True,
        )


def test_goal_completion_is_only_completion_surface() -> None:
    completion = GoalCompletion(
        completion_id="complete:1",
        formal_goal_id="formal:lease-ready",
        root_goal_id="goal:lease-ready",
        tree_id="tree:repo@abc",
        verdict=CompletionVerdict.COMPLETE,
        authority=AuthorityCeiling.THEOREM,
        evidence_ids=("evidence:kernel-1",),
        receipt_ids=("receipt:kernel-1",),
        plan_id="plan:lease-1",
        graph_id="graph:lease-1",
        bounds=_bounds(),
        proof_claimed=True,
    )
    assert completion.completion_claimed is True
    assert completion.proof_claimed is True
    restored = GoalCompletion.from_dict(completion.to_dict())
    assert restored.content_id == completion.content_id

    # Non-complete cannot claim proof.
    with pytest.raises(TacticianContractError, match="cannot claim proof"):
        GoalCompletion(
            completion_id="complete:2",
            formal_goal_id="formal:lease-ready",
            root_goal_id="goal:lease-ready",
            tree_id="tree:repo@abc",
            verdict=CompletionVerdict.NOT_COMPLETE,
            authority=AuthorityCeiling.NONE,
            proof_claimed=True,
        )

    # Complete without evidence fails closed.
    with pytest.raises(TacticianContractError, match="evidence"):
        GoalCompletion(
            completion_id="complete:3",
            formal_goal_id="formal:lease-ready",
            root_goal_id="goal:lease-ready",
            tree_id="tree:repo@abc",
            verdict=CompletionVerdict.COMPLETE,
            authority=AuthorityCeiling.THEOREM,
            proof_claimed=True,
        )


def test_goal_completion_identity_changes_with_verdict() -> None:
    base = GoalCompletion(
        completion_id="complete:1",
        formal_goal_id="formal:lease-ready",
        root_goal_id="goal:lease-ready",
        tree_id="tree:repo@abc",
        verdict=CompletionVerdict.NOT_COMPLETE,
        authority=AuthorityCeiling.NONE,
    )
    other = GoalCompletion(
        completion_id="complete:1",
        formal_goal_id="formal:lease-ready",
        root_goal_id="goal:lease-ready",
        tree_id="tree:repo@abc",
        verdict=CompletionVerdict.DISPROVED,
        authority=AuthorityCeiling.SATISFIABILITY,
        evidence_ids=("evidence:cex-1",),
    )
    assert base.content_id != other.content_id


# ---------------------------------------------------------------------------
# Conversion adapters (no competing root identity)
# ---------------------------------------------------------------------------


def test_goal_development_adapter_preserves_root_identity() -> None:
    adapted = end_goal_spec_from_goal_development_mapping(
        {
            "goal_id": "goal:root-1",
            "root_objective_id": "goal:root-1",
            "repository_tree_id": "tree:repo@1",
            "prompt": "workers never deadlock",
            "property_class": "safety",
            "assumption_ids": ["assumption:fair-scheduler"],
            "proof_claimed": True,  # stripped
            "completion_claimed": True,  # stripped
        }
    )
    assert adapted.root_goal_id == "goal:root-1"
    assert adapted.goal_id == "goal:root-1"
    assert adapted.proof_claimed is False
    assert adapted.completion_claimed is False
    assert adapted.source.tree_id == "tree:repo@1"
    assert adapted.property_class is PropertyClass.SAFETY
    assert adapted.assumptions[0].assumption_id == "assumption:fair-scheduler"


def test_supervisor_plan_adapter_emits_candidate_only_plan() -> None:
    plan = goal_directed_plan_from_supervisor_proof_plan(
        {
            "schema": "ipfs_accelerate_py/agent-supervisor/proof-plan@1",
            "plan_id": "sup-plan-1",
            "repository_tree_id": "tree:repo@1",
            "steps": [
                {
                    "step_id": "s1",
                    "obligation_id": "obl:1",
                    "stage": "solve",
                    "provider_id": "provider:z3",
                },
                {
                    "step_id": "s2",
                    "obligation_id": "obl:2",
                    "stage": "kernel_verify",
                    "provider_id": "provider:lean",
                },
            ],
            "proof_claimed": True,
            "complete": True,
        },
        formal_goal_id="formal:lease-ready",
        root_goal_id="goal:lease-ready",
    )
    assert plan.root_goal_id == "goal:lease-ready"
    assert plan.formal_goal_id == "formal:lease-ready"
    assert plan.proof_claimed is False
    assert plan.completion_claimed is False
    assert plan.authority is AuthorityCeiling.CANDIDATE
    assert len(plan.candidates) == 2
    assert all(c.authority is AuthorityCeiling.CANDIDATE for c in plan.candidates)
    assert plan.metadata["adapted_from"] == "supervisor_proof_plan"


def test_content_identity_helper_matches_contract_ids() -> None:
    goal = _end_goal()
    assert content_identity(goal.to_dict()) == goal.content_id


def test_floats_are_rejected_in_canonical_payloads() -> None:
    with pytest.raises(TacticianContractError, match="floating-point"):
        _end_goal(current_state={"temp": 1.5})


def test_deep_copy_dict_round_trip_for_nested_graph_and_plan() -> None:
    """Ensure nested closed objects survive serialize/deserialize."""

    graph = _graph()
    plan = _plan()
    formal = _formal_goal()
    blob = {
        "formal_goal": formal.to_dict(),
        "graph": graph.to_dict(),
        "plan": plan.to_dict(),
        "hole": _hole().to_dict(),
    }
    restored = copy.deepcopy(blob)
    assert FormalGoal.from_dict(restored["formal_goal"]).content_id == formal.content_id
    assert (
        ProofObligationGraph.from_dict(restored["graph"]).content_id
        == graph.content_id
    )
    assert (
        GoalDirectedProofPlan.from_dict(restored["plan"]).content_id
        == plan.content_id
    )
    assert ProofHole.from_dict(restored["hole"]).content_id == _hole().content_id
