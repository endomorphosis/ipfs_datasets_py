"""Conformance tests for the deterministic Intent formalization compiler."""

from __future__ import annotations

from dataclasses import replace

import pytest

from ipfs_datasets_py.logic.formalization.compiler import (
    FormalizationArtifact,
    FormalizationCompiler,
    UnsupportedSemanticsPolicy,
)
from ipfs_datasets_py.logic.intent_ir.formalize.compiler import (
    INTENT_ACTION_VIEW_ID,
    INTENT_FACT_VIEW_ID,
    INTENT_FAILURE_VIEW_ID,
    INTENT_FORMALIZATION_VIEW_REGISTRY,
    INTENT_INVARIANT_VIEW_ID,
    INTENT_MODAL_VIEW_ID,
    INTENT_VERIFICATION_VIEW_ID,
    INTENT_WORKFLOW_VIEW_ID,
    IntentFormalizationCompiler,
    IntentFormalizationCompilerError,
)
from ipfs_datasets_py.logic.intent_ir.schema import (
    ControlEdgeKind,
    IntentAction,
    IntentControlEdge,
    IntentIRDocument,
    IntentKind,
    IntentModality,
    IntentStatement,
    NodeGrounding,
    SourceRef,
    StatementKind,
)


def _document(*, opaque_goal: bool = False) -> IntentIRDocument:
    statements = (
        IntentStatement(
            statement_id="statement:goal",
            kind=StatementKind.GOAL,
            modality=IntentModality.INTENDED,
            normalized_text="Publish the result",
            predicate="" if opaque_goal else "publish",
            arguments=("result",),
            source_ref_ids=("source:one",),
            confidence=0.75,
        ),
        IntentStatement(
            statement_id="statement:assumption",
            kind=StatementKind.ASSUMPTION,
            modality=IntentModality.ASSERTED,
            normalized_text="The result exists",
            predicate="exists",
            arguments=("result",),
            source_ref_ids=("source:one",),
        ),
        IntentStatement(
            statement_id="statement:effect",
            kind=StatementKind.EFFECT,
            modality=IntentModality.ASSERTED,
            normalized_text="The result is published",
            predicate="published",
            arguments=("result",),
            source_ref_ids=("source:two",),
        ),
        IntentStatement(
            statement_id="statement:guard",
            kind=StatementKind.GUARD,
            modality=IntentModality.REQUIRED,
            normalized_text="Publication is allowed",
            predicate="allowed",
            arguments=("result",),
            source_ref_ids=("source:one",),
        ),
        IntentStatement(
            statement_id="statement:invariant",
            kind=StatementKind.INVARIANT,
            modality=IntentModality.REQUIRED,
            normalized_text="The source remains available",
            predicate="available",
            arguments=("source",),
            source_ref_ids=("source:one",),
        ),
        IntentStatement(
            statement_id="statement:failure",
            kind=StatementKind.FAILURE,
            modality=IntentModality.PROHIBITED,
            normalized_text="Publication fails",
            predicate="publication_failed",
            arguments=("result",),
            source_ref_ids=("source:two",),
        ),
        IntentStatement(
            statement_id="statement:verify",
            kind=StatementKind.VERIFICATION,
            modality=IntentModality.REQUIRED,
            normalized_text="Observe the published result",
            predicate="observed",
            arguments=("result",),
            source_ref_ids=("source:two",),
            grounding=NodeGrounding.INFERRED,
        ),
    )
    document = IntentIRDocument(
        document_id="intent:publish",
        title="Publish a result",
        intent_kind=IntentKind.PROCEDURE,
        sources=(
            SourceRef(
                ref_id="source:two",
                source_uri="urn:test:two",
                source_id="two",
                source_revision="v1",
                content_sha256="b" * 64,
            ),
            SourceRef(
                ref_id="source:one",
                source_uri="urn:test:one",
                source_id="one",
                source_revision="v1",
                content_sha256="a" * 64,
            ),
        ),
        statements=tuple(reversed(statements)),
        actions=(
            IntentAction(
                action_id="action:publish",
                actor="agent",
                verb="publish",
                object_refs=("result",),
                source_ref_ids=("source:one", "source:two"),
                precondition_ids=("statement:assumption",),
                effect_ids=("statement:effect",),
                verification_ids=("statement:verify", "statement:invariant"),
            ),
            IntentAction(
                action_id="action:retry",
                actor="agent",
                verb="retry",
                object_refs=("publication",),
                source_ref_ids=("source:two",),
            ),
        ),
        control_edges=(
            IntentControlEdge(
                edge_id="edge:retry",
                source_action_id="action:retry",
                target_action_id="action:retry",
                kind=ControlEdgeKind.RETRY,
                source_ref_ids=("source:two",),
            ),
            IntentControlEdge(
                edge_id="edge:next",
                source_action_id="action:publish",
                target_action_id="action:retry",
                kind=ControlEdgeKind.ON_FAILURE,
                guard_statement_id="statement:guard",
                source_ref_ids=("source:one",),
            ),
        ),
        entry_action_ids=("action:publish",),
        terminal_action_ids=("action:retry",),
        tags=("test",),
    )
    document.validate()
    return document


def _graph_context() -> dict:
    return {
        "authority": "context_only",
        "graph_digest": "sha256:" + ("c" * 64),
        "premises": [
            {
                "authority": "context_only",
                "edge_id": "edge:graph",
                "edge_type": "NEIGHBOR_OF",
                "graph_cid": "bafyfixture",
                "graph_digest": "sha256:" + ("c" * 64),
                "node_id": "graph-node:neighbor",
                "node_type": "skill",
                "partition": "evaluation",
                "proof_authority": False,
                "properties": {"title": "Neighbor"},
                "score": 0.75,
                "source_digest": "sha256:" + ("d" * 64),
                "source_family": "other-family",
                "source_ids": ["source:one"],
            }
        ],
    }


def test_complete_multiview_lowering_is_source_and_node_grounded() -> None:
    compiler = IntentFormalizationCompiler()
    document = _document()
    sample = compiler.adapt_sample(document)
    artifact = compiler.compile(
        sample,
        compiler.default_config(sample),
        graph_context=_graph_context(),
    )

    assert isinstance(compiler, FormalizationCompiler)
    assert isinstance(artifact, FormalizationArtifact)
    assert set(artifact.compiler_config.target_view_ids) == {
        INTENT_FACT_VIEW_ID,
        INTENT_MODAL_VIEW_ID,
        INTENT_ACTION_VIEW_ID,
        INTENT_WORKFLOW_VIEW_ID,
        INTENT_INVARIANT_VIEW_ID,
        INTENT_FAILURE_VIEW_ID,
        INTENT_VERIFICATION_VIEW_ID,
    }
    assert set(INTENT_FORMALIZATION_VIEW_REGISTRY.view_ids) == set(
        artifact.compiler_config.target_view_ids
    )
    assert {formula.view_id for formula in artifact.formulas} == set(
        artifact.compiler_config.target_view_ids
    )

    bindings = {
        binding.subject_id: binding for binding in artifact.source_map.bindings
    }
    for formula in artifact.formulas:
        assert formula.input_node_ids
        assert formula.source_ref_ids
        assert set(formula.input_node_ids).issubset(bindings)
        assert set(formula.source_ref_ids).issubset(
            bindings[formula.formula_id].source_ref_ids
        )
        assert formula.metadata["intent_node_ids"]

    retrieved = [
        item
        for item in artifact.assumptions
        if item.metadata.get("authority") == "context_only"
    ]
    assert len(retrieved) == 1
    assert retrieved[0].metadata["proof_authority"] is False
    assert artifact.metadata["retrieved_premise_count"] == 1
    assert artifact.metadata["retrieved_premises_have_proof_authority"] is False
    assert all(
        retrieved[0].assumption_id not in obligation.assumption_ids
        for obligation in artifact.proof_obligations
    )
    assert all(
        retrieved[0].assumption_id not in formula.assumption_ids
        for formula in artifact.formulas
    )
    uncertain_goal = next(
        item
        for item in artifact.assumptions
        if item.metadata.get("intent_node_id") == "statement:goal"
    )
    assert uncertain_goal.metadata["uncertain"] is True
    assert any(
        uncertain_goal.assumption_id in formula.assumption_ids
        for formula in artifact.formulas
        if "statement:goal" in formula.metadata["intent_node_ids"]
    )
    assert {
        obligation.metadata["intent_node_id"]
        for obligation in artifact.proof_obligations
    } == {
        "statement:invariant",
        "statement:failure",
        "statement:verify",
    }
    assert artifact.cross_view_links
    assert artifact.diagnostics.error_count == 0
    assert artifact.diagnostics.warning_count == 0


def test_graph_context_is_optional_and_compilation_is_byte_stable() -> None:
    compiler = IntentFormalizationCompiler()
    document = _document()

    first = compiler.compile(document)
    second = compiler.compile(document)
    round_trip = compiler.compile(
        compiler.adapt_sample(document),
        compiler.default_config(document),
    )

    assert first.canonical_bytes() == second.canonical_bytes()
    assert first.canonical_bytes() == round_trip.canonical_bytes()
    assert first.digest == second.digest == round_trip.digest
    assert first.metadata["graph_context_present"] is False
    assert "graph_context" not in first.metadata
    assert first.metadata["retrieved_premise_count"] == 0


def test_untyped_semantics_are_retained_as_opaque_diagnostics() -> None:
    compiler = IntentFormalizationCompiler()
    document = _document(opaque_goal=True)
    artifact = compiler.compile(document)
    goal_formulas = [
        formula
        for formula in artifact.formulas
        if "statement:goal" in formula.metadata["intent_node_ids"]
    ]

    assert goal_formulas
    assert all(formula.opaque for formula in goal_formulas)
    assert all(
        formula.to_dict()["expression"]["body"]["text"]
        == "Publish the result"
        if "body" in formula.to_dict()["expression"]
        else formula.to_dict()["expression"]["text"] == "Publish the result"
        for formula in goal_formulas
    )
    assert {
        diagnostic.metadata["opaque_formula_id"]
        for diagnostic in artifact.unsupported_diagnostics
        if diagnostic.metadata.get("opaque_formula_id")
    } == {formula.formula_id for formula in goal_formulas}
    assert all(
        diagnostic.location.traceable
        for diagnostic in artifact.unsupported_diagnostics
    )

    strict = replace(
        compiler.default_config(document),
        unsupported_policy=UnsupportedSemanticsPolicy.ERROR,
    )
    strict_artifact = compiler.compile(document, strict)
    assert strict_artifact.diagnostics.error_count == len(goal_formulas)


def test_invalid_context_foreign_sample_tamper_and_unknown_views_fail_closed() -> None:
    compiler = IntentFormalizationCompiler()
    sample = compiler.adapt_sample(_document())

    with pytest.raises(
        IntentFormalizationCompilerError, match="proof authority"
    ):
        compiler.compile(
            sample,
            graph_context={
                "premises": [
                    {
                        "node_id": "graph:bad",
                        "proof_authority": True,
                        "source_ids": [],
                    }
                ]
            },
        )

    with pytest.raises(
        IntentFormalizationCompilerError, match="Intent FormalizationSample"
    ):
        compiler.compile(
            replace(sample, domain="legal"),
            compiler.default_config(sample),
        )

    payload = sample.payload.to_dict()
    payload["declaration"]["title"] = "Tampered title"
    with pytest.raises(
        IntentFormalizationCompilerError, match="digest"
    ):
        compiler.compile(
            replace(sample, payload=payload),
            compiler.default_config(sample),
        )

    unknown = replace(
        compiler.default_config(sample),
        target_view_ids=("intent-ir-view/unknown/v1",),
    )
    with pytest.raises(
        IntentFormalizationCompilerError, match="unknown views"
    ):
        compiler.compile(sample, unknown)
