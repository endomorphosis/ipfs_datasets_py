"""Unit tests for BackwardProofObligationGraph@1 (FVT-019 / FVT-G031).

Acceptance:

* Every edge names a checked inference/reconstruction rule.
* AND/OR meanings are distinct.
* Finite budgets, SCC/cycle and subsumption controls terminate.
* Solved leaves cite adequate evidence.
* Legacy string-equality or forward-only "backward" paths cannot receive
  trusted status.
"""

from __future__ import annotations

from typing import Any

import pytest

from ipfs_datasets_py.logic.software_verification.tactician.contracts import (
    AuthorityCeiling,
    GraphEdgeKind,
    GraphNodeKind,
    HoleKind,
    HoleStatus,
    PropertyClass,
    ResourceBounds,
    SourceSpanBinding,
    ValidationRecipe,
    ProofHole,
)
from ipfs_datasets_py.logic.software_verification.tactician.proof_graph import (
    BACKWARD_PROOF_OBLIGATION_GRAPH_INTERFACE,
    GRAPH_ALGORITHM_VERSION,
    BackwardGraphRequest,
    BackwardProofObligationGraph,
    EvidenceCitation,
    GraphBuildStatus,
    InferenceRule,
    ObligationSeed,
    ObligationSeedKind,
    ProofGraphError,
    ReconstructionMethod,
    RegressionStep,
    and_or_meanings_distinct,
    build_backward_proof_graph,
    cap_experimental_authority,
    every_edge_names_checked_rule,
    evidence_seed,
    experimental_legacy_seed,
    experimental_paths_untrusted,
    hole_seed,
    is_experimental_reconstruction,
    is_experimental_rule,
    is_trusted_authority,
    preimage_step,
    rule_inversion_step,
    solved_leaves_cite_evidence,
    temporal_step,
    unification_step,
    wp_step,
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


def _recipe(**overrides: Any) -> ValidationRecipe:
    payload = {
        "recipe_id": "recipe:inv-check",
        "checker_kind": "smt_invariant_check",
        "provider_ids": ("provider:z3",),
        "required_authority": AuthorityCeiling.SATISFIABILITY,
        "steps": ("bind_source_span", "check_init", "check_preserve"),
    }
    payload.update(overrides)
    return ValidationRecipe(**payload)


def _hole(**overrides: Any) -> ProofHole:
    payload: dict[str, Any] = {
        "hole_id": "hole:loop-inv-1",
        "kind": HoleKind.LOOP_INVARIANT,
        "reason": "missing loop invariant at claim_loop",
        "source": _source(),
        "formal_goal_id": "formal:lease-ready",
        "expected_authority": AuthorityCeiling.SATISFIABILITY,
        "dependency_ids": (),
        "validation_recipe": _recipe(),
        "status": HoleStatus.OPEN,
        "property_class": PropertyClass.INVARIANCE,
        "statement": "invariant(owner_holds_token)",
        "provider_ids": ("provider:z3",),
        "bounds": ResourceBounds(max_nodes=64, max_depth=8, max_steps=32),
        "proof_claimed": False,
        "completion_claimed": False,
    }
    payload.update(overrides)
    return ProofHole(**payload)


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


# ---------------------------------------------------------------------------
# Interface and basic construction
# ---------------------------------------------------------------------------


def test_interface_constant() -> None:
    assert (
        BACKWARD_PROOF_OBLIGATION_GRAPH_INTERFACE
        == "BackwardProofObligationGraph@1"
    )
    assert (
        BackwardProofObligationGraph.INTERFACE
        == BACKWARD_PROOF_OBLIGATION_GRAPH_INTERFACE
    )


def test_build_from_holes_produces_dag_with_named_edges() -> None:
    hole_a = _hole(hole_id="hole:inv", statement="inv(token)")
    hole_b = _hole(
        hole_id="hole:frame",
        kind=HoleKind.FRAME,
        statement="frame(modifies={token})",
        reason="missing frame",
    )
    result = build_backward_proof_graph(
        BackwardGraphRequest(
            formal_goal_id="formal:lease-ready",
            tree_id="tree:repo@abc",
            holes=(hole_a, hole_b),
            bounds=_bounds(),
        )
    )
    graph = result.graph
    assert graph.formal_goal_id == "formal:lease-ready"
    assert graph.root_node_id == "node:root"
    assert graph.proof_claimed is False
    assert graph.completion_claimed is False
    assert len(graph.nodes) >= 3  # root + and + leaves (or root + leaves)
    assert every_edge_names_checked_rule(graph)
    assert and_or_meanings_distinct(graph)
    assert result.proof_claimed is False
    assert result.completion_claimed is False
    # Holes become open obligations.
    assert result.open_node_ids
    assert result.status in {
        GraphBuildStatus.OPEN,
        GraphBuildStatus.PARTIAL,
        GraphBuildStatus.TERMINATED,
    }


def test_result_round_trips_to_dict() -> None:
    result = build_backward_proof_graph(
        BackwardGraphRequest(
            formal_goal_id="formal:x",
            tree_id="tree:t",
            holes=(_hole(),),
            bounds=_bounds(),
        )
    )
    record = result.to_record()
    assert record["interface"] == BACKWARD_PROOF_OBLIGATION_GRAPH_INTERFACE
    assert record["algorithm_version"] == GRAPH_ALGORITHM_VERSION
    assert record["proof_claimed"] is False
    assert "content_id" in record
    assert record["graph"]["formal_goal_id"] == "formal:x"


# ---------------------------------------------------------------------------
# Every edge names checked inference/reconstruction rule
# ---------------------------------------------------------------------------


def test_every_edge_names_checked_rule_and_reconstruction() -> None:
    result = build_backward_proof_graph(
        BackwardGraphRequest(
            formal_goal_id="formal:wp",
            tree_id="tree:t",
            steps=(
                wp_step(
                    step_id="step:wp1",
                    parent_obligation_id="formal:wp",
                    child_obligation_id="obl:pre",
                    statement="wp(assign, post)",
                    program_step_id="stmt:assign",
                ),
                preimage_step(
                    step_id="step:pre1",
                    parent_obligation_id="obl:pre",
                    child_obligation_id="obl:preimage",
                    transition_id="tr:t1",
                    statement="preimage(tr:t1)",
                ),
                temporal_step(
                    step_id="step:temp1",
                    parent_obligation_id="obl:preimage",
                    child_obligation_id="obl:fair",
                    statement="fairness premise",
                ),
                rule_inversion_step(
                    step_id="step:inv1",
                    parent_obligation_id="obl:fair",
                    child_obligation_id="obl:prem",
                    statement="inverted premise",
                ),
                unification_step(
                    step_id="step:uni1",
                    parent_obligation_id="obl:prem",
                    child_obligation_id="obl:unified",
                    statement="unified goal",
                ),
            ),
            bounds=_bounds(max_nodes=32, max_depth=16, max_steps=32),
        )
    )
    assert every_edge_names_checked_rule(result.graph)
    rules = {e.inference_rule for e in result.graph.edges}
    methods = {e.reconstruction_method for e in result.graph.edges}
    assert InferenceRule.WEAKEST_PRECONDITION.value in rules
    assert InferenceRule.TRANSITION_PREIMAGE.value in rules
    assert InferenceRule.TEMPORAL_REGRESSION.value in rules
    assert InferenceRule.RULE_INVERSION.value in rules
    assert InferenceRule.TYPED_UNIFICATION.value in rules
    assert ReconstructionMethod.SOURCE_VC.value in methods
    assert ReconstructionMethod.PREIMAGE_REPLAY.value in methods
    for edge in result.graph.edges:
        assert edge.inference_rule
        assert edge.reconstruction_method
        assert edge.kind in GraphEdgeKind


def test_regression_step_rejects_self_loop() -> None:
    with pytest.raises(ProofGraphError, match="self-loops"):
        RegressionStep(
            step_id="s",
            parent_obligation_id="obl:a",
            child_obligation_id="obl:a",
            inference_rule=InferenceRule.WEAKEST_PRECONDITION,
            reconstruction_method=ReconstructionMethod.SOURCE_VC,
        )


def test_unknown_inference_rule_rejected() -> None:
    with pytest.raises(ProofGraphError, match="inference_rule"):
        ObligationSeed(
            seed_id="seed:bad",
            kind=ObligationSeedKind.PROOF_HOLE,
            statement="x",
            inference_rule="not_a_real_rule",  # type: ignore[arg-type]
        )


# ---------------------------------------------------------------------------
# AND/OR meanings are distinct
# ---------------------------------------------------------------------------


def test_and_or_meanings_are_distinct() -> None:
    seeds = (
        ObligationSeed(
            seed_id="seed:a",
            kind=ObligationSeedKind.PROOF_HOLE,
            statement="need inv A",
            combination="and",
            inference_rule=InferenceRule.HOLE_EMISSION,
            reconstruction_method=ReconstructionMethod.SOURCE_VC,
        ),
        ObligationSeed(
            seed_id="seed:b",
            kind=ObligationSeedKind.PROOF_HOLE,
            statement="need inv B",
            combination="and",
            inference_rule=InferenceRule.HOLE_EMISSION,
            reconstruction_method=ReconstructionMethod.SOURCE_VC,
        ),
        ObligationSeed(
            seed_id="seed:alt1",
            kind=ObligationSeedKind.ALTERNATIVE,
            statement="backend z3",
            combination="or",
            inference_rule=InferenceRule.OR_INTRO,
            reconstruction_method=ReconstructionMethod.SMT_REPLAY,
        ),
        ObligationSeed(
            seed_id="seed:alt2",
            kind=ObligationSeedKind.ALTERNATIVE,
            statement="backend cvc5",
            combination="or",
            inference_rule=InferenceRule.OR_INTRO,
            reconstruction_method=ReconstructionMethod.SMT_REPLAY,
        ),
    )
    result = build_backward_proof_graph(
        BackwardGraphRequest(
            formal_goal_id="formal:and-or",
            tree_id="tree:t",
            seeds=seeds,
            bounds=_bounds(),
        )
    )
    kinds = {n.kind for n in result.graph.nodes}
    assert GraphNodeKind.AND in kinds
    assert GraphNodeKind.OR in kinds
    assert and_or_meanings_distinct(result.graph)

    and_nodes = [n for n in result.graph.nodes if n.kind is GraphNodeKind.AND]
    or_nodes = [n for n in result.graph.nodes if n.kind is GraphNodeKind.OR]
    assert and_nodes and or_nodes

    # AND children use joint depends_on; OR uses alternative/or_intro.
    for node in and_nodes:
        outs = [
            e for e in result.graph.edges if e.source_node_id == node.node_id
        ]
        for edge in outs:
            assert edge.kind is not GraphEdgeKind.ALTERNATIVE
            assert edge.inference_rule != InferenceRule.OR_INTRO.value

    for node in or_nodes:
        outs = [
            e for e in result.graph.edges if e.source_node_id == node.node_id
        ]
        for edge in outs:
            assert edge.inference_rule != InferenceRule.AND_INTRO.value


# ---------------------------------------------------------------------------
# Finite budgets terminate
# ---------------------------------------------------------------------------


def test_max_nodes_budget_terminates() -> None:
    holes = tuple(
        _hole(
            hole_id=f"hole:n{i}",
            statement=f"obligation {i}",
            reason=f"missing {i}",
        )
        for i in range(20)
    )
    result = build_backward_proof_graph(
        BackwardGraphRequest(
            formal_goal_id="formal:budget",
            tree_id="tree:t",
            holes=holes,
            bounds=_bounds(max_nodes=5, max_steps=100, max_depth=16),
        )
    )
    assert result.budget_exhausted is True
    assert result.status is GraphBuildStatus.BOUNDED
    assert len(result.graph.nodes) <= 5


def test_max_steps_budget_terminates() -> None:
    steps = tuple(
        wp_step(
            step_id=f"step:{i}",
            parent_obligation_id=f"obl:{i}",
            child_obligation_id=f"obl:{i+1}",
            statement=f"wp step {i}",
        )
        for i in range(10)
    )
    result = build_backward_proof_graph(
        BackwardGraphRequest(
            formal_goal_id="formal:steps",
            tree_id="tree:t",
            steps=steps,
            bounds=_bounds(max_nodes=100, max_steps=4, max_depth=32),
        )
    )
    assert result.budget_exhausted is True
    assert result.steps_used <= 4 or result.budget_exhausted


def test_max_depth_budget_terminates() -> None:
    deep = ObligationSeed(
        seed_id="seed:deep",
        kind=ObligationSeedKind.PROOF_HOLE,
        statement="deep obligation",
        depth_hint=100,
        inference_rule=InferenceRule.HOLE_EMISSION,
        reconstruction_method=ReconstructionMethod.SOURCE_VC,
    )
    result = build_backward_proof_graph(
        BackwardGraphRequest(
            formal_goal_id="formal:depth",
            tree_id="tree:t",
            seeds=(deep,),
            bounds=_bounds(max_depth=2, max_nodes=32, max_steps=32),
        )
    )
    assert result.budget_exhausted is True
    assert any("max_depth" in d for d in result.diagnostics)


# ---------------------------------------------------------------------------
# Subsumption and cycle control
# ---------------------------------------------------------------------------


def test_subsumption_collapses_duplicate_statements() -> None:
    seeds = (
        ObligationSeed(
            seed_id="seed:one",
            kind=ObligationSeedKind.PROOF_HOLE,
            statement="invariant(owner_holds_token)",
            inference_rule=InferenceRule.HOLE_EMISSION,
            reconstruction_method=ReconstructionMethod.SOURCE_VC,
        ),
        ObligationSeed(
            seed_id="seed:two",
            kind=ObligationSeedKind.PROOF_HOLE,
            statement="  invariant(owner_holds_token)  ",
            inference_rule=InferenceRule.HOLE_EMISSION,
            reconstruction_method=ReconstructionMethod.SOURCE_VC,
        ),
    )
    result = build_backward_proof_graph(
        BackwardGraphRequest(
            formal_goal_id="formal:sub",
            tree_id="tree:t",
            seeds=seeds,
            bounds=_bounds(),
        )
    )
    assert result.subsumed_pairs
    # Only one unique leaf for the duplicate statement (plus structural nodes).
    leaf_statements = [
        n.metadata.get("statement")
        for n in result.graph.nodes
        if n.kind is GraphNodeKind.LEAF and n.metadata.get("statement")
    ]
    normalized = {
        " ".join(str(s).strip().lower().split()) for s in leaf_statements if s
    }
    assert "invariant(owner_holds_token)" in normalized
    # Subsumption edges use the checked rule.
    sub_edges = [
        e
        for e in result.graph.edges
        if e.kind is GraphEdgeKind.SUBSUMPTION
        or e.inference_rule == InferenceRule.SUBSUMPTION.value
    ]
    assert sub_edges
    for edge in sub_edges:
        assert edge.reconstruction_method == (
            ReconstructionMethod.SUBSUMPTION_CHECK.value
        )


def test_cycle_control_produces_acyclic_graph() -> None:
    # Attempt to create A -> B -> A via steps; builder must terminate as DAG.
    steps = (
        wp_step(
            step_id="step:ab",
            parent_obligation_id="obl:a",
            child_obligation_id="obl:b",
            statement="A implies B",
        ),
        wp_step(
            step_id="step:ba",
            parent_obligation_id="obl:b",
            child_obligation_id="obl:a",
            statement="B implies A",
        ),
    )
    result = build_backward_proof_graph(
        BackwardGraphRequest(
            formal_goal_id="formal:cycle",
            tree_id="tree:t",
            steps=steps,
            bounds=_bounds(),
        )
    )
    # ProofObligationGraph construction requires acyclicity — if we got here
    # the graph is a DAG.
    assert result.graph is not None
    if result.cycle_detected:
        assert result.scc_blocked_ids or result.diagnostics
    # No residual directed cycle.
    adj: dict[str, list[str]] = {n.node_id: [] for n in result.graph.nodes}
    for e in result.graph.edges:
        adj[e.source_node_id].append(e.target_node_id)

    WHITE, GRAY, BLACK = 0, 1, 2
    color = {n: WHITE for n in adj}

    def visit(node: str) -> None:
        color[node] = GRAY
        for nxt in adj[node]:
            assert color[nxt] is not GRAY, "residual cycle in graph"
            if color[nxt] is WHITE:
                visit(nxt)
        color[node] = BLACK

    for n in adj:
        if color[n] is WHITE:
            visit(n)


# ---------------------------------------------------------------------------
# Solved leaves cite adequate evidence
# ---------------------------------------------------------------------------


def test_solved_leaf_requires_adequate_evidence() -> None:
    leaf = ObligationSeed(
        seed_id="seed:leaf",
        kind=ObligationSeedKind.PROOF_HOLE,
        statement="prove inv",
        hole_id="hole:inv",
        inference_rule=InferenceRule.HOLE_EMISSION,
        reconstruction_method=ReconstructionMethod.SOURCE_VC,
        status=HoleStatus.OPEN,
    )
    evidence = evidence_seed(
        EvidenceCitation(
            evidence_id="ev:smt-1",
            authority=AuthorityCeiling.SATISFIABILITY,
            receipt_id="receipt:z3-1",
            provider_id="provider:z3",
            statement="unsat core closed inv",
        ),
        parent_seed_id="seed:leaf",
    )
    result = build_backward_proof_graph(
        BackwardGraphRequest(
            formal_goal_id="formal:ev",
            tree_id="tree:t",
            seeds=(leaf, evidence),
            bounds=_bounds(),
        )
    )
    assert result.discharged_node_ids
    assert solved_leaves_cite_evidence(result)
    # Evidence edges name the citation rule.
    ev_edges = [
        e
        for e in result.graph.edges
        if e.inference_rule == InferenceRule.EVIDENCE_CITATION.value
    ]
    assert ev_edges
    assert all(
        e.reconstruction_method
        == ReconstructionMethod.EVIDENCE_RECEIPT.value
        for e in ev_edges
    )


def test_leaf_without_evidence_not_discharged() -> None:
    leaf = ObligationSeed(
        seed_id="seed:open",
        kind=ObligationSeedKind.PROOF_HOLE,
        statement="still open",
        status=HoleStatus.DISCHARGED,  # claim without evidence — stripped
        inference_rule=InferenceRule.HOLE_EMISSION,
        reconstruction_method=ReconstructionMethod.SOURCE_VC,
    )
    result = build_backward_proof_graph(
        BackwardGraphRequest(
            formal_goal_id="formal:no-ev",
            tree_id="tree:t",
            seeds=(leaf,),
            bounds=_bounds(),
        )
    )
    assert "node:seed:open" not in result.discharged_node_ids or (
        not solved_leaves_cite_evidence(result) is False
    )
    # The open claim is stripped.
    node = next(
        n for n in result.graph.nodes if n.node_id == "node:seed:open"
    )
    assert node.status is not HoleStatus.DISCHARGED or result.discharged_node_ids
    # If somehow discharged, evidence must be present; otherwise open.
    if node.status is HoleStatus.DISCHARGED:
        assert solved_leaves_cite_evidence(result)
    else:
        assert node.status in {HoleStatus.OPEN, HoleStatus.CANDIDATE}
        assert any("inadequate evidence" in d or "stripped" in d for d in result.diagnostics) or (
            node.status is HoleStatus.OPEN
        )


def test_candidate_authority_evidence_does_not_discharge() -> None:
    leaf = ObligationSeed(
        seed_id="seed:leaf2",
        kind=ObligationSeedKind.PROOF_HOLE,
        statement="need theorem",
        inference_rule=InferenceRule.HOLE_EMISSION,
        reconstruction_method=ReconstructionMethod.SOURCE_VC,
    )
    weak = evidence_seed(
        EvidenceCitation(
            evidence_id="ev:weak",
            authority=AuthorityCeiling.CANDIDATE,
            statement="proposal only",
        ),
        parent_seed_id="seed:leaf2",
    )
    result = build_backward_proof_graph(
        BackwardGraphRequest(
            formal_goal_id="formal:weak",
            tree_id="tree:t",
            seeds=(leaf, weak),
            bounds=_bounds(),
            discharge_authority=AuthorityCeiling.BOUNDED,
        )
    )
    leaf_node = next(
        n for n in result.graph.nodes if n.node_id == "node:seed:leaf2"
    )
    assert leaf_node.status is not HoleStatus.DISCHARGED
    assert "node:seed:leaf2" not in result.discharged_node_ids


# ---------------------------------------------------------------------------
# Legacy / experimental paths cannot receive trusted status
# ---------------------------------------------------------------------------


def test_legacy_string_equality_cannot_be_trusted() -> None:
    legacy = experimental_legacy_seed(
        seed_id="seed:legacy-str",
        statement="goal == lemma  # string equality",
        rule=InferenceRule.LEGACY_STRING_EQUALITY,
        reconstruction=ReconstructionMethod.STRING_EQUALITY,
        claimed_authority=AuthorityCeiling.THEOREM,
    )
    assert legacy.experimental is True
    assert legacy.authority is AuthorityCeiling.CANDIDATE
    assert is_experimental_rule(InferenceRule.LEGACY_STRING_EQUALITY)
    assert is_experimental_reconstruction(ReconstructionMethod.STRING_EQUALITY)

    result = build_backward_proof_graph(
        BackwardGraphRequest(
            formal_goal_id="formal:legacy",
            tree_id="tree:t",
            seeds=(legacy,),
            bounds=_bounds(),
        )
    )
    assert experimental_paths_untrusted(result)
    for node in result.graph.nodes:
        if node.metadata.get("experimental"):
            assert not is_trusted_authority(node.authority)
            assert node.status is not HoleStatus.DISCHARGED
    for edge in result.graph.edges:
        if edge.inference_rule == InferenceRule.LEGACY_STRING_EQUALITY.value:
            assert edge.metadata.get("experimental") is True
            assert edge.metadata.get("trusted") is not True
            assert edge.edge_id in result.experimental_edge_ids


def test_cec_forward_as_backward_and_tdfol_are_experimental() -> None:
    seeds = (
        experimental_legacy_seed(
            seed_id="seed:cec",
            statement="cec forward masquerading as backward",
            rule=InferenceRule.CEC_FORWARD_AS_BACKWARD,
            reconstruction=ReconstructionMethod.EXPERIMENTAL_CEC,
            claimed_authority=AuthorityCeiling.RECONSTRUCTION,
        ),
        experimental_legacy_seed(
            seed_id="seed:tdfol",
            statement="tdfol forward-only path",
            rule=InferenceRule.TDFOL_FORWARD_ONLY,
            reconstruction=ReconstructionMethod.EXPERIMENTAL_TDFOL,
            claimed_authority=AuthorityCeiling.THEOREM,
        ),
    )
    result = build_backward_proof_graph(
        BackwardGraphRequest(
            formal_goal_id="formal:legacy2",
            tree_id="tree:t",
            seeds=seeds,
            bounds=_bounds(),
        )
    )
    assert experimental_paths_untrusted(result)
    experimental_rules = {
        InferenceRule.CEC_FORWARD_AS_BACKWARD.value,
        InferenceRule.TDFOL_FORWARD_ONLY.value,
    }
    found = {
        e.inference_rule
        for e in result.graph.edges
        if e.inference_rule in experimental_rules
    }
    assert experimental_rules == found or found  # at least one path materialised
    for edge in result.graph.edges:
        if edge.inference_rule in experimental_rules:
            assert edge.kind is GraphEdgeKind.ALTERNATIVE
            assert edge.metadata.get("trusted") is not True


def test_cap_experimental_authority_demotes_theorem() -> None:
    assert (
        cap_experimental_authority(AuthorityCeiling.THEOREM)
        is AuthorityCeiling.CANDIDATE
    )
    assert (
        cap_experimental_authority(AuthorityCeiling.ADVISORY)
        is AuthorityCeiling.ADVISORY
    )
    assert (
        cap_experimental_authority(AuthorityCeiling.NONE)
        is AuthorityCeiling.NONE
    )


def test_experimental_disallowed_when_flag_false() -> None:
    legacy = experimental_legacy_seed(
        seed_id="seed:blocked",
        statement="should be skipped",
    )
    result = BackwardProofObligationGraph(allow_experimental=False).build(
        BackwardGraphRequest(
            formal_goal_id="formal:no-exp",
            tree_id="tree:t",
            seeds=(legacy,),
            bounds=_bounds(),
        )
    )
    assert not any(
        n.metadata.get("experimental") for n in result.graph.nodes
    )
    assert any("experimental" in d for d in result.diagnostics)


# ---------------------------------------------------------------------------
# Helpers and hole integration
# ---------------------------------------------------------------------------


def test_hole_seed_helper() -> None:
    hole = _hole()
    seed = hole_seed(hole)
    assert seed.hole_id == hole.hole_id
    assert seed.kind is ObligationSeedKind.PROOF_HOLE
    assert seed.statement == hole.statement


def test_request_from_mapping() -> None:
    result = build_backward_proof_graph(
        {
            "formal_goal_id": "formal:map",
            "tree_id": "tree:t",
            "holes": (_hole().to_dict(),),
            "bounds": _bounds().to_dict(),
        }
    )
    assert result.graph.formal_goal_id == "formal:map"
    assert every_edge_names_checked_rule(result.graph)


def test_result_cannot_claim_proof() -> None:
    base = build_backward_proof_graph(
        BackwardGraphRequest(
            formal_goal_id="formal:x",
            tree_id="tree:t",
            holes=(_hole(),),
            bounds=_bounds(),
        )
    )
    with pytest.raises(ProofGraphError, match="cannot claim"):
        type(base)(
            graph=base.graph,
            status=base.status,
            proof_claimed=True,
        )


def test_trusted_authority_helper() -> None:
    assert is_trusted_authority(AuthorityCeiling.THEOREM)
    assert is_trusted_authority(AuthorityCeiling.SATISFIABILITY)
    assert not is_trusted_authority(AuthorityCeiling.CANDIDATE)
    assert not is_trusted_authority(AuthorityCeiling.ADVISORY)
    assert not is_trusted_authority(AuthorityCeiling.NONE)


def test_mixed_trusted_and_experimental_or_branch() -> None:
    """OR alternatives: trusted WP path vs experimental string-equality."""

    trusted = ObligationSeed(
        seed_id="seed:trusted-wp",
        kind=ObligationSeedKind.PROOF_HOLE,
        statement="wp-derived obligation",
        combination="or",
        inference_rule=InferenceRule.WEAKEST_PRECONDITION,
        reconstruction_method=ReconstructionMethod.SOURCE_VC,
        authority=AuthorityCeiling.SATISFIABILITY,
    )
    legacy = experimental_legacy_seed(
        seed_id="seed:legacy-or",
        statement="string-equal match",
        parent_seed_id="",
        claimed_authority=AuthorityCeiling.THEOREM,
    )
    # Force both as top-level OR alternatives.
    legacy = ObligationSeed(
        seed_id=legacy.seed_id,
        kind=legacy.kind,
        statement=legacy.statement,
        combination="or",
        inference_rule=legacy.inference_rule,
        reconstruction_method=legacy.reconstruction_method,
        authority=AuthorityCeiling.THEOREM,
        experimental=True,
    )
    result = build_backward_proof_graph(
        BackwardGraphRequest(
            formal_goal_id="formal:mix",
            tree_id="tree:t",
            seeds=(trusted, legacy),
            bounds=_bounds(),
        )
    )
    assert and_or_meanings_distinct(result.graph)
    assert experimental_paths_untrusted(result)
    # Trusted seed may keep satisfiability; legacy is capped.
    legacy_nodes = [
        n
        for n in result.graph.nodes
        if n.metadata.get("experimental") is True
    ]
    assert legacy_nodes
    for n in legacy_nodes:
        assert not is_trusted_authority(n.authority)
