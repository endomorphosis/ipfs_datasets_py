"""Integration tests for FormalGoalCompiler@1 (FVT-018 / FVT-G024).

Acceptance criteria covered:

* exact targets and bounds reproduce from content identities;
* source spans and assumption classes survive compilation;
* material translation loss or ambiguity fails closed; and
* backend choice cannot raise assurance above the translation ceiling.
"""

from __future__ import annotations

from typing import Any

import pytest

from ipfs_datasets_py.logic.families.models import EvidenceAuthority
from ipfs_datasets_py.logic.software_verification.ir import (
    DeclarationKind,
    SoftwareVerificationIR,
)
from ipfs_datasets_py.logic.software_verification.properties import (
    AssumptionKind,
    PropertyKind,
)
from ipfs_datasets_py.logic.software_verification.receipts import (
    LogicTranslationReceipt,
)
from ipfs_datasets_py.logic.software_verification.tactician.contracts import (
    AmbiguityStatus,
    AssumptionBinding,
    AssumptionClass,
    AuthorityCeiling,
    EndGoalInterpretation,
    EndGoalSpec,
    FormalGoal,
    PhraseProvenance,
    PropertyClass,
    QuantifierKind,
    ResourceBounds,
    SourceSpanBinding,
    TacticianContractError,
)
from ipfs_datasets_py.logic.software_verification.tactician.goal_compiler import (
    FORMAL_GOAL_COMPILER_INTERFACE,
    FormalGoalCompiler,
    GoalCompilationResult,
    GoalCompilerError,
    RootObligation,
    compile_formal_goal,
    map_assumption_kind,
    map_property_kind,
)
from ipfs_datasets_py.logic.software_verification.translations import (
    PreservationKind,
    maximum_authority_for,
)


# ---------------------------------------------------------------------------
# Fixtures / factories
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
    selected: bool = True,
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
        "assumptions": (
            _assumption(),
            _assumption(
                "assumption:fair-scheduler",
                assumption_class=AssumptionClass.TRUSTED,
            ),
            _assumption(
                "assumption:what-if-crash",
                assumption_class=AssumptionClass.HYPOTHETICAL,
            ),
        ),
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
        "interpretations": (_interpretation("interp:exists-ready", selected=True),),
        "ambiguity_status": AmbiguityStatus.RESOLVED,
        "unsupported_semantics": (),
        "translation_loss": (),
        "acceptance_evidence": ("receipt:kernel",),
        "expected_receipt_classes": ("proof-receipt", "counterexample"),
        "status": "confirmed",
        "authority": AuthorityCeiling.DECLARATIVE,
        "proof_claimed": False,
        "completion_claimed": False,
    }
    payload.update(overrides)
    return EndGoalSpec(**payload)


def _formal_goal(end_goal: EndGoalSpec | None = None, **overrides: Any) -> FormalGoal:
    goal = end_goal or _end_goal()
    payload = {
        "formal_goal_id": "formal:lease-ready",
        "end_goal": goal,
        "selected_interpretation_id": "interp:exists-ready",
        "confirmation_receipt_id": "receipt:confirm-1",
        "status": "confirmed",
        "authority": AuthorityCeiling.DECLARATIVE,
        "proof_claimed": False,
        "completion_claimed": False,
    }
    payload.update(overrides)
    return FormalGoal(**payload)


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_compiler_interface_and_successful_compile() -> None:
    compiler = FormalGoalCompiler()
    result = compiler.compile(_formal_goal())

    assert compiler.INTERFACE == FORMAL_GOAL_COMPILER_INTERFACE
    assert isinstance(result, GoalCompilationResult)
    assert result.status.value == "success"
    assert isinstance(result.ir, SoftwareVerificationIR)
    assert isinstance(result.translation_receipt, LogicTranslationReceipt)
    assert len(result.root_obligations) == 1
    assert result.root_obligations[0].backend_neutral is True


def test_compile_module_wrapper_matches_class() -> None:
    formal = _formal_goal()
    via_class = FormalGoalCompiler().compile(formal)
    via_fn = compile_formal_goal(formal)
    assert via_class.ir.document_id == via_fn.ir.document_id
    assert via_class.receipt_id == via_fn.receipt_id


def test_exact_targets_and_bounds_reproduce_from_content_identities() -> None:
    formal = _formal_goal()
    first = FormalGoalCompiler().compile(formal)
    second = FormalGoalCompiler().compile(formal)

    # Content identities are stable across identical compilations.
    assert first.ir.document_id == second.ir.document_id
    assert first.translation_receipt.receipt_id == second.translation_receipt.receipt_id
    assert first.content_id == second.content_id
    assert first.formal_goal_content_id == formal.content_id
    assert first.end_goal_content_id == formal.end_goal.content_id

    # Target state and resource bounds round-trip through the IR.
    contract = next(
        item
        for item in first.ir.declarations
        if item.kind is DeclarationKind.CONTRACT
    )
    assert contract.payload["target_state"]["phase"] == "ready"
    assert contract.payload["current_state"]["phase"] == "init"

    assert first.ir.bounds, "finite EndGoalSpec bounds must compile into IR bounds"
    bound = first.ir.bounds[0]
    assert bound.limits["max_steps"] == 32
    assert bound.limits["wall_time_ms"] == 5_000
    assert bound.limits["memory_bytes"] == 64 * 1024 * 1024

    # Rebuilding from the receipt + IR identities preserves the binding.
    receipt = LogicTranslationReceipt.from_dict(first.translation_receipt.to_dict())
    ir = SoftwareVerificationIR.from_dict(first.ir.to_dict())
    assert receipt.target_identity == ir.document_id
    assert receipt.source_identity == formal.content_id


def test_source_spans_and_assumption_classes_survive() -> None:
    result = FormalGoalCompiler().compile(_formal_goal())
    ir = result.ir

    # Source spans from the end-goal binding and phrase provenance survive.
    span_ids = {span.span_id for span in ir.spans}
    assert "span:claim" in span_ids
    assert "span:prompt-1" in span_ids
    source_ids = {source.ref_id for source in ir.sources}
    assert "source:lease.py" in source_ids
    assert "source:prompt" in source_ids

    # Every property / assumption remains source-mapped.
    for prop in ir.properties:
        assert prop.source_ref_ids or prop.span_ids
        assert "span:claim" in prop.span_ids or prop.source_ref_ids
    for assumption in ir.assumptions:
        assert assumption.source_ref_ids or assumption.span_ids

    # Assumption classes survive on expression + namespaced extension.
    by_id = {item.assumption_id: item for item in ir.assumptions}
    assert by_id["assumption:token-order"].expression["assumption_class"] == (
        AssumptionClass.MUST_PROVE.value
    )
    assert by_id["assumption:token-order"].extensions[
        "tactician.assumption_class"
    ] == AssumptionClass.MUST_PROVE.value
    assert by_id["assumption:token-order"].kind is AssumptionKind.SEMANTIC

    assert by_id["assumption:fair-scheduler"].expression["assumption_class"] == (
        AssumptionClass.TRUSTED.value
    )
    assert by_id["assumption:fair-scheduler"].kind is AssumptionKind.TRUST

    assert by_id["assumption:what-if-crash"].expression["assumption_class"] == (
        AssumptionClass.HYPOTHETICAL.value
    )
    assert by_id["assumption:what-if-crash"].kind is AssumptionKind.MODELING

    assert map_assumption_kind(AssumptionClass.MUST_PROVE) is AssumptionKind.SEMANTIC


def test_emits_state_transition_environment_contract_and_root_obligation() -> None:
    result = FormalGoalCompiler().compile(_formal_goal())
    kinds = {item.kind for item in result.ir.declarations}
    assert DeclarationKind.STATE in kinds
    assert DeclarationKind.TRANSITION in kinds
    assert DeclarationKind.POLICY in kinds
    assert DeclarationKind.CONTRACT in kinds

    prop = result.ir.properties[0]
    assert prop.kind is PropertyKind.REACHABILITY
    assert prop.expression["target_state"]["phase"] == "ready"
    assert prop.expression["property_class"] == (
        PropertyClass.EXISTENTIAL_REACHABILITY.value
    )
    assert map_property_kind(PropertyClass.EXISTENTIAL_REACHABILITY) is (
        PropertyKind.REACHABILITY
    )

    obligation = result.root_obligations[0]
    assert isinstance(obligation, RootObligation)
    assert obligation.property_id == prop.property_id
    assert obligation.backend_neutral is True
    assert obligation.provider_ids == ("provider:z3",)
    assert "(assert" not in obligation.statement.casefold()

    # Transition names survive as declarations.
    transition_names = {
        item.name
        for item in result.ir.declarations
        if item.kind is DeclarationKind.TRANSITION
    }
    assert transition_names == {"claim", "release"}


def test_loss_aware_receipt_binds_goal_and_ir_with_bounded_preservation() -> None:
    result = FormalGoalCompiler().compile(_formal_goal())
    receipt = result.translation_receipt

    assert receipt.source_identity == result.formal_goal_content_id
    assert receipt.target_identity == result.ir.document_id
    assert receipt.source_family_id == "end_goal_spec"
    assert receipt.target_family_id == "software_verification"
    assert receipt.preservation_claim.kind is PreservationKind.BOUNDED
    assert result.preservation_kind is PreservationKind.BOUNDED
    assert receipt.authority_ceiling is result.assurance_ceiling
    assert receipt.authority_ceiling is EvidenceAuthority.BOUNDED
    assert receipt.bounds, "bounded preservation requires explicit bounds"
    assert receipt.semantic_mutations
    assert all(
        item.kind.value == "bound_introduced" for item in receipt.semantic_mutations
    )


def test_unbounded_goal_compiles_as_exact_preservation() -> None:
    end_goal = _end_goal(
        bounds=ResourceBounds(),  # all-zero bounds
        assurance_target=AuthorityCeiling.BOUNDED,
    )
    result = FormalGoalCompiler().compile(_formal_goal(end_goal))
    assert result.preservation_kind is PreservationKind.EXACT
    assert result.translation_receipt.preservation_claim.kind is PreservationKind.EXACT
    assert not result.translation_receipt.bounds
    assert not result.ir.bounds
    # Exact permits authoritative, but assurance_target BOUNDED caps the ceiling.
    assert result.assurance_ceiling is EvidenceAuthority.BOUNDED


# ---------------------------------------------------------------------------
# Fail-closed paths
# ---------------------------------------------------------------------------


def test_material_ambiguity_requires_selection_fails_closed() -> None:
    end_goal = _end_goal(
        ambiguity_status=AmbiguityStatus.REQUIRES_SELECTION,
        interpretations=(
            _interpretation("interp:exists-ready", selected=False),
            _interpretation(
                "interp:forall-ready",
                property_class=PropertyClass.UNIVERSAL_REACHABILITY,
                selected=False,
            ),
        ),
    )
    # Fail-closed begins at FormalGoal confirmation: unresolved material
    # ambiguity never becomes a compilable formal goal.
    with pytest.raises(TacticianContractError, match="ambiguity resolution"):
        FormalGoal(
            formal_goal_id="formal:ambiguous",
            end_goal=end_goal,
            selected_interpretation_id="interp:exists-ready",
            status="confirmed",
        )


def test_candidates_present_without_resolution_fails_closed() -> None:
    end_goal = _end_goal(
        ambiguity_status=AmbiguityStatus.CANDIDATES_PRESENT,
        interpretations=(
            _interpretation("interp:exists-ready", selected=False),
            _interpretation(
                "interp:forall-ready",
                property_class=PropertyClass.UNIVERSAL_REACHABILITY,
                selected=False,
            ),
        ),
    )
    formal = FormalGoal(
        formal_goal_id="formal:candidates",
        end_goal=end_goal,
        selected_interpretation_id="interp:exists-ready",
        status="confirmed",
    )
    with pytest.raises(GoalCompilerError, match="ambiguity"):
        FormalGoalCompiler().compile(formal)


def test_material_translation_loss_fails_closed() -> None:
    end_goal = _end_goal(
        translation_loss=("material:quantifier-erasure",),
    )
    with pytest.raises(GoalCompilerError, match="translation loss"):
        FormalGoalCompiler().compile(_formal_goal(end_goal))


def test_unsupported_semantics_fail_closed() -> None:
    end_goal = _end_goal(
        unsupported_semantics=("hyperproperty:noninterference",),
    )
    with pytest.raises(GoalCompilerError, match="unsupported semantics"):
        FormalGoalCompiler().compile(_formal_goal(end_goal))


def test_unspecified_property_class_fails_closed() -> None:
    end_goal = _end_goal(
        property_class=PropertyClass.UNSPECIFIED,
        interpretations=(),
        ambiguity_status=AmbiguityStatus.NONE,
    )
    formal = FormalGoal(
        formal_goal_id="formal:unspecified",
        end_goal=end_goal,
        selected_interpretation_id="interp:none",
        status="confirmed",
    )
    # FormalGoal requires selected interpretation to exist when interpretations
    # are present; with empty interpretations, selected_id is free-form.
    with pytest.raises(GoalCompilerError, match="unspecified property"):
        FormalGoalCompiler().compile(formal)


# ---------------------------------------------------------------------------
# Backend cannot raise assurance
# ---------------------------------------------------------------------------


def test_backend_choice_cannot_raise_assurance_above_translation_ceiling() -> None:
    # Bounded goal + resource bounds ⇒ preservation BOUNDED ⇒ max BOUNDED.
    formal = _formal_goal()
    weak = FormalGoalCompiler().compile(formal, requested_backend=None)
    strong = FormalGoalCompiler().compile(
        formal, requested_backend="backend:lean4-kernel"
    )
    stronger = FormalGoalCompiler().compile(
        formal, requested_backend="backend:isabelle-kernel"
    )

    assert weak.assurance_ceiling is EvidenceAuthority.BOUNDED
    assert strong.assurance_ceiling is EvidenceAuthority.BOUNDED
    assert stronger.assurance_ceiling is EvidenceAuthority.BOUNDED
    assert strong.assurance_ceiling == weak.assurance_ceiling
    assert maximum_authority_for(strong.preservation_kind) is EvidenceAuthority.BOUNDED

    # Metadata records the request without elevating the receipt ceiling.
    assert strong.metadata["requested_backend"] == "backend:lean4-kernel"
    assert (
        strong.translation_receipt.metadata["requested_backend"]
        == "backend:lean4-kernel"
    )
    assert strong.translation_receipt.authority_ceiling is EvidenceAuthority.BOUNDED


def test_provider_ids_cannot_inflate_authority_ceiling() -> None:
    end_goal = _end_goal(
        provider_ids=("provider:lean4", "provider:isabelle", "provider:hol4"),
        assurance_target=AuthorityCeiling.ADVISORY,
        bounds=ResourceBounds(),  # exact preservation would allow authoritative
    )
    result = FormalGoalCompiler().compile(
        _formal_goal(end_goal),
        requested_backend="backend:kernel",
    )
    # Assurance target ADVISORY caps even exact preservation.
    assert result.preservation_kind is PreservationKind.EXACT
    assert result.assurance_ceiling is EvidenceAuthority.ADVISORY
    assert result.translation_receipt.authority_ceiling is EvidenceAuthority.ADVISORY


def test_root_obligation_rejects_provider_syntax_in_statement() -> None:
    with pytest.raises(GoalCompilerError, match="provider syntax"):
        RootObligation(
            obligation_id="obligation:bad",
            property_id="property:bad",
            statement="prove (assert true) in smt-lib",
            kind=PropertyKind.SAFETY,
            source_ref_ids=("source:lease.py",),
        )


def test_dict_round_trip_of_formal_goal_compiles() -> None:
    formal = _formal_goal()
    result = FormalGoalCompiler().compile(formal.to_dict())
    assert result.formal_goal_id == formal.formal_goal_id
    assert result.ir.properties[0].kind is PropertyKind.REACHABILITY


def test_semantic_change_to_target_state_changes_ir_identity() -> None:
    base = FormalGoalCompiler().compile(_formal_goal())
    alt_end = _end_goal(target_state={"phase": "done"})
    # Keep interpretation aligned so effective fields pick the interpretation.
    alt_end = _end_goal(
        target_state={"phase": "done"},
        interpretations=(
            EndGoalInterpretation(
                interpretation_id="interp:exists-ready",
                controlled_english="Some execution reaches done.",
                property_class=PropertyClass.EXISTENTIAL_REACHABILITY,
                quantifiers=(QuantifierKind.EXISTS, QuantifierKind.EVENTUALLY),
                current_state={"phase": "init"},
                target_state={"phase": "done"},
                environment={"scheduler": "fair"},
                selected=True,
            ),
        ),
    )
    alt = FormalGoalCompiler().compile(_formal_goal(alt_end))
    assert alt.ir.document_id != base.ir.document_id
    assert alt.ir.properties[0].expression["target_state"]["phase"] == "done"
