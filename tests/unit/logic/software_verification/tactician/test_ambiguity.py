"""Unit tests for GoalInterpretationSet@1 and GoalAmbiguityGate@1 (FVT-014 / FVT-G023).

Acceptance coverage:

* existential reachability, universal reachability, eventual inevitability,
  invariance, termination, and refinement cannot collapse;
* ambiguous corpus prompts return at least two visibly different candidates; and
* no material ambiguity is silently selected.
"""

from __future__ import annotations

from typing import Any

import pytest

from ipfs_datasets_py.logic.software_verification.tactician.ambiguity import (
    AMBIGUITY_ALGORITHM_VERSION,
    GOAL_AMBIGUITY_GATE_INTERFACE,
    GOAL_INTERPRETATION_SET_INTERFACE,
    NON_COLLAPSIBLE_PROPERTY_CLASSES,
    ConfirmationKind,
    GateStatus,
    GoalAmbiguityError,
    GoalAmbiguityGate,
    GoalAmbiguityReport,
    GoalInterpretationSet,
    SemanticDiff,
    build_interpretation_set,
    compare_goal_interpretations,
    compare_interpretations,
    controlled_english_for,
    expand_ambiguous_prompt,
    expand_from_end_goal,
    expose_ambiguity,
    is_ambiguous_prompt,
    material_identity,
    property_classes_cannot_collapse,
    quantifiers_for_property_class,
)
from ipfs_datasets_py.logic.software_verification.tactician.contracts import (
    AmbiguityStatus,
    AuthorityCeiling,
    EndGoalInterpretation,
    EndGoalSpec,
    PropertyClass,
    QuantifierKind,
    ResourceBounds,
    SourceSpanBinding,
)


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------


def _source(**overrides: Any) -> SourceSpanBinding:
    payload = {
        "tree_id": "tree:repo@abc",
        "source_ref_ids": ("source:prompt", "source:lease.py"),
        "span_ids": ("span:caller",),
        "ast_scope_ids": ("symbol:claim_lease",),
        "snapshot_id": "snap:1",
    }
    payload.update(overrides)
    return SourceSpanBinding(**payload)


def _interp(
    interpretation_id: str,
    property_class: PropertyClass,
    *,
    selected: bool = False,
    target: str = "ready",
) -> EndGoalInterpretation:
    return EndGoalInterpretation(
        interpretation_id=interpretation_id,
        controlled_english=controlled_english_for(
            property_class,
            target_state={"phase": target},
            current_state={"phase": "init"},
        ),
        property_class=property_class,
        quantifiers=quantifiers_for_property_class(property_class),
        current_state={"phase": "init"},
        target_state={"phase": target},
        environment={},
        semantic_diff={"property_class": property_class.value},
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
        "assumptions": (),
        "logic_family": "temporal.ltl",
        "provider_ids": ("provider:z3",),
        "assurance_target": AuthorityCeiling.BOUNDED,
        "bounds": ResourceBounds(
            wall_time_ms=5_000,
            max_steps=32,
            network_allowed=False,
        ),
        "provenance": (),
        "interpretations": (),
        "ambiguity_status": AmbiguityStatus.NONE,
        "unsupported_semantics": (),
        "translation_loss": (),
        "acceptance_evidence": ("receipt:kernel",),
        "expected_receipt_classes": ("proof-receipt",),
        "status": "draft",
        "authority": AuthorityCeiling.ADVISORY,
        "proof_claimed": False,
        "completion_claimed": False,
    }
    payload.update(overrides)
    return EndGoalSpec(**payload)


@pytest.fixture
def gate() -> GoalAmbiguityGate:
    return GoalAmbiguityGate()


# ---------------------------------------------------------------------------
# Interface constants
# ---------------------------------------------------------------------------


def test_interface_constants() -> None:
    assert GOAL_INTERPRETATION_SET_INTERFACE == "GoalInterpretationSet@1"
    assert GOAL_AMBIGUITY_GATE_INTERFACE == "GoalAmbiguityGate@1"
    assert GoalAmbiguityGate.INTERFACE == "GoalAmbiguityGate@1"
    assert GoalInterpretationSet.INTERFACE == "GoalInterpretationSet@1"
    assert AMBIGUITY_ALGORITHM_VERSION.startswith("goal-ambiguity-gate/")


# ---------------------------------------------------------------------------
# Non-collapse of the six material property classes
# ---------------------------------------------------------------------------


def test_non_collapsible_property_classes_are_distinct() -> None:
    identities = property_classes_cannot_collapse()
    assert set(identities) == {item.value for item in NON_COLLAPSIBLE_PROPERTY_CLASSES}
    assert len(set(identities.values())) == len(NON_COLLAPSIBLE_PROPERTY_CLASSES)


@pytest.mark.parametrize(
    "left,right",
    [
        (PropertyClass.EXISTENTIAL_REACHABILITY, PropertyClass.UNIVERSAL_REACHABILITY),
        (PropertyClass.EXISTENTIAL_REACHABILITY, PropertyClass.INEVITABILITY),
        (PropertyClass.EXISTENTIAL_REACHABILITY, PropertyClass.INVARIANCE),
        (PropertyClass.EXISTENTIAL_REACHABILITY, PropertyClass.TERMINATION),
        (PropertyClass.EXISTENTIAL_REACHABILITY, PropertyClass.REFINEMENT),
        (PropertyClass.UNIVERSAL_REACHABILITY, PropertyClass.INEVITABILITY),
        (PropertyClass.UNIVERSAL_REACHABILITY, PropertyClass.INVARIANCE),
        (PropertyClass.UNIVERSAL_REACHABILITY, PropertyClass.TERMINATION),
        (PropertyClass.UNIVERSAL_REACHABILITY, PropertyClass.REFINEMENT),
        (PropertyClass.INEVITABILITY, PropertyClass.INVARIANCE),
        (PropertyClass.INEVITABILITY, PropertyClass.TERMINATION),
        (PropertyClass.INEVITABILITY, PropertyClass.REFINEMENT),
        (PropertyClass.INVARIANCE, PropertyClass.TERMINATION),
        (PropertyClass.INVARIANCE, PropertyClass.REFINEMENT),
        (PropertyClass.TERMINATION, PropertyClass.REFINEMENT),
    ],
)
def test_pairwise_property_classes_do_not_collapse(
    left: PropertyClass, right: PropertyClass
) -> None:
    a = _interp(f"interp:{left.value}", left)
    b = _interp(f"interp:{right.value}", right)
    assert material_identity(a) != material_identity(b)
    diff = compare_interpretations(a, b)
    assert diff.material is True
    assert "property_class" in diff.changed_fields
    assert a.controlled_english != b.controlled_english


def test_quantifier_bundles_differ_across_non_collapsible_classes() -> None:
    """Classes may share some quantifiers but not the full material identity."""

    bundles = {
        prop: quantifiers_for_property_class(prop)
        for prop in NON_COLLAPSIBLE_PROPERTY_CLASSES
    }
    # Existential vs universal must differ on path quantifier.
    assert QuantifierKind.EXISTS in bundles[PropertyClass.EXISTENTIAL_REACHABILITY]
    assert QuantifierKind.FORALL in bundles[PropertyClass.UNIVERSAL_REACHABILITY]
    assert bundles[PropertyClass.INVARIANCE] == (QuantifierKind.ALWAYS,)
    assert bundles[PropertyClass.REFINEMENT] == (QuantifierKind.NONE,)


# ---------------------------------------------------------------------------
# Ambiguous corpus prompts → ≥2 visibly different candidates
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "prompt",
    [
        "the system reaches ready",
        "The system reaches the ready state",
        "worker reaches ready",
        "system reaches done",
        "the lease ends in ready",
        "phase becomes ready under fair scheduling for eventual progress",
        "the protocol is safe",
        "the module works correctly",
    ],
)
def test_ambiguous_corpus_prompts_return_at_least_two_candidates(prompt: str) -> None:
    assert is_ambiguous_prompt(prompt)
    interpretation_set = expand_ambiguous_prompt(prompt, goal_id="goal:corpus")
    assert interpretation_set.material_count >= 2
    assert len(interpretation_set.interpretations) >= 2
    assert len(interpretation_set.visible_differences()) >= 2
    assert interpretation_set.ambiguity_status is AmbiguityStatus.REQUIRES_SELECTION
    assert interpretation_set.selected_id == ""
    assert all(not item.selected for item in interpretation_set.interpretations)


def test_reaches_ready_expands_to_material_alternatives() -> None:
    """Canonical plan example: reaches ready → exists / forall / inevitable / invariant."""

    interpretation_set = expand_ambiguous_prompt(
        "the system reaches ready",
        goal_id="goal:lease-ready",
    )
    classes = {item.property_class for item in interpretation_set.interpretations}
    assert PropertyClass.EXISTENTIAL_REACHABILITY in classes
    assert PropertyClass.UNIVERSAL_REACHABILITY in classes
    assert PropertyClass.INEVITABILITY in classes
    assert PropertyClass.INVARIANCE in classes
    # Every pairwise material diff must be material.
    material_diffs = [d for d in interpretation_set.pairwise_diffs if d.material]
    assert material_diffs
    assert interpretation_set.confirmation_requirements
    assert any(
        req.kind is ConfirmationKind.SELECT_INTERPRETATION and req.required
        for req in interpretation_set.confirmation_requirements
    )


def test_fairness_ambiguity_expands_liveness_family() -> None:
    interpretation_set = expand_ambiguous_prompt(
        "under fairness the system eventually reaches ready",
        goal_id="goal:fair-ready",
    )
    classes = {item.property_class for item in interpretation_set.interpretations}
    assert PropertyClass.UNIVERSAL_REACHABILITY in classes
    assert PropertyClass.INEVITABILITY in classes or PropertyClass.LIVENESS in classes
    assert interpretation_set.material_count >= 2


# ---------------------------------------------------------------------------
# No silent selection
# ---------------------------------------------------------------------------


def test_gate_does_not_silently_select(gate: GoalAmbiguityGate) -> None:
    report = gate.analyze_prompt("the system reaches ready", goal_id="goal:x")
    assert report.status is GateStatus.REQUIRES_SELECTION
    assert report.requires_selection is True
    assert report.selected_interpretation_id == ""
    assert report.admitted is False
    assert report.interpretation_set.selected_id == ""
    assert all(
        not item.selected for item in report.interpretation_set.interpretations
    )


def test_require_selection_or_raise_blocks_progress(
    gate: GoalAmbiguityGate,
) -> None:
    report = gate.analyze_prompt("the system reaches ready")
    with pytest.raises(GoalAmbiguityError, match="requires interpretation selection"):
        gate.require_selection_or_raise(report)


def test_explicit_select_resolves_ambiguity(gate: GoalAmbiguityGate) -> None:
    report = gate.analyze_prompt("the system reaches ready", goal_id="goal:sel")
    assert report.requires_selection
    chosen_id = report.interpretation_set.material_candidate_ids[0]
    resolved = gate.select(report.interpretation_set, chosen_id)
    assert resolved.status is GateStatus.RESOLVED
    assert resolved.selected_interpretation_id == chosen_id
    assert resolved.interpretation_set.ambiguity_status is AmbiguityStatus.RESOLVED
    assert resolved.interpretation_set.selected_id == chosen_id
    selected = [
        item
        for item in resolved.interpretation_set.interpretations
        if item.selected
    ]
    assert len(selected) == 1
    assert selected[0].interpretation_id == chosen_id
    # Gate no longer blocks.
    gate.require_selection_or_raise(resolved)


def test_select_unknown_id_fails(gate: GoalAmbiguityGate) -> None:
    report = gate.analyze_prompt("the system reaches ready")
    with pytest.raises(GoalAmbiguityError, match="unknown interpretation_id"):
        gate.select(report.interpretation_set, "interp:does-not-exist")


def test_set_rejects_preselected_while_requires_selection() -> None:
    a = _interp("interp:a", PropertyClass.EXISTENTIAL_REACHABILITY, selected=True)
    b = _interp("interp:b", PropertyClass.UNIVERSAL_REACHABILITY, selected=False)
    with pytest.raises(GoalAmbiguityError, match="requires selection"):
        GoalInterpretationSet(
            set_id="iset:bad",
            goal_id="goal:x",
            caller_text="the system reaches ready",
            interpretations=(a, b),
            ambiguity_status=AmbiguityStatus.REQUIRES_SELECTION,
            selected_id="",
            material_candidate_ids=("interp:a", "interp:b"),
        )


def test_set_rejects_selected_id_while_requires_selection() -> None:
    a = _interp("interp:a", PropertyClass.EXISTENTIAL_REACHABILITY)
    b = _interp("interp:b", PropertyClass.UNIVERSAL_REACHABILITY)
    with pytest.raises(GoalAmbiguityError, match="selected_id must be empty"):
        GoalInterpretationSet(
            set_id="iset:bad",
            goal_id="goal:x",
            caller_text="the system reaches ready",
            interpretations=(a, b),
            ambiguity_status=AmbiguityStatus.REQUIRES_SELECTION,
            selected_id="interp:a",
            material_candidate_ids=("interp:a", "interp:b"),
        )


def test_report_cannot_admit() -> None:
    interpretation_set = expand_ambiguous_prompt("the system reaches ready")
    with pytest.raises(GoalAmbiguityError, match="cannot admit"):
        GoalAmbiguityReport(
            status=GateStatus.REQUIRES_SELECTION,
            interpretation_set=interpretation_set,
            admitted=True,
        )


def test_report_from_dict_rejects_admission() -> None:
    interpretation_set = expand_ambiguous_prompt("the system reaches ready")
    payload = {
        "status": "requires_selection",
        "interpretation_set": interpretation_set.to_dict(),
        "admitted": True,
    }
    with pytest.raises(GoalAmbiguityError, match="cannot admit"):
        GoalAmbiguityReport.from_dict(payload)


def test_meta_cannot_claim_auto_selected() -> None:
    a = _interp("interp:a", PropertyClass.EXISTENTIAL_REACHABILITY)
    with pytest.raises(GoalAmbiguityError, match="forbidden admission"):
        build_interpretation_set(
            goal_id="goal:x",
            caller_text="x",
            interpretations=(a,),
            meta={"auto_selected": True},
        )


# ---------------------------------------------------------------------------
# EndGoalSpec integration
# ---------------------------------------------------------------------------


def test_analyze_end_goal_expands_ambiguous_caller_text(
    gate: GoalAmbiguityGate,
) -> None:
    end_goal = _end_goal(
        caller_text="the system reaches ready",
        interpretations=(),
    )
    report = gate.analyze_end_goal(end_goal)
    assert report.requires_selection
    assert report.interpretation_set.material_count >= 2


def test_analyze_end_goal_uses_existing_multi_interpretations(
    gate: GoalAmbiguityGate,
) -> None:
    end_goal = _end_goal(
        interpretations=(
            _interp("interp:exists", PropertyClass.EXISTENTIAL_REACHABILITY),
            _interp("interp:forall", PropertyClass.UNIVERSAL_REACHABILITY),
        ),
        ambiguity_status=AmbiguityStatus.REQUIRES_SELECTION,
    )
    report = gate.analyze_end_goal(end_goal)
    assert report.requires_selection
    ids = {item.interpretation_id for item in report.interpretation_set.interpretations}
    assert "interp:exists" in ids
    assert "interp:forall" in ids


def test_apply_to_end_goal_preserves_requires_selection(
    gate: GoalAmbiguityGate,
) -> None:
    end_goal = _end_goal()
    report = gate.analyze_end_goal(end_goal)
    updated = gate.apply_to_end_goal(end_goal, report)
    assert updated.ambiguity_status is AmbiguityStatus.REQUIRES_SELECTION
    assert len(updated.interpretations) >= 2
    assert updated.proof_claimed is False
    assert updated.completion_claimed is False


def test_apply_to_end_goal_after_explicit_select(
    gate: GoalAmbiguityGate,
) -> None:
    end_goal = _end_goal()
    report = gate.analyze_end_goal(end_goal)
    # Prefer universal reachability if present.
    chosen = next(
        item
        for item in report.interpretation_set.interpretations
        if item.property_class is PropertyClass.UNIVERSAL_REACHABILITY
    )
    resolved = gate.select(report.interpretation_set, chosen.interpretation_id)
    updated = gate.apply_to_end_goal(end_goal, resolved)
    assert updated.ambiguity_status is AmbiguityStatus.RESOLVED
    assert updated.property_class is PropertyClass.UNIVERSAL_REACHABILITY
    assert QuantifierKind.FORALL in updated.quantifiers


def test_expand_from_end_goal_strips_silent_selection_flags() -> None:
    end_goal = _end_goal(
        interpretations=(
            _interp(
                "interp:exists",
                PropertyClass.EXISTENTIAL_REACHABILITY,
                selected=True,
            ),
            _interp("interp:forall", PropertyClass.UNIVERSAL_REACHABILITY),
        ),
        ambiguity_status=AmbiguityStatus.CANDIDATES_PRESENT,
    )
    interpretation_set = expand_from_end_goal(end_goal)
    assert all(not item.selected for item in interpretation_set.interpretations)
    assert interpretation_set.ambiguity_status is AmbiguityStatus.REQUIRES_SELECTION


# ---------------------------------------------------------------------------
# Semantic diff purity / round-trips
# ---------------------------------------------------------------------------


def test_semantic_diff_is_deterministic() -> None:
    a = _interp("interp:a", PropertyClass.EXISTENTIAL_REACHABILITY)
    b = _interp("interp:b", PropertyClass.INVARIANCE)
    d1 = compare_interpretations(a, b)
    d2 = compare_goal_interpretations(a, b)
    assert d1.fingerprint == d2.fingerprint
    assert d1.material is True
    assert d1.to_dict()["schema"] == SemanticDiff.SCHEMA
    rebuilt = SemanticDiff.from_dict(d1.to_dict())
    assert rebuilt.fingerprint == d1.fingerprint
    assert rebuilt.changed_fields == d1.changed_fields


def test_identical_interpretations_are_not_material() -> None:
    a = _interp("interp:a", PropertyClass.TERMINATION)
    b = _interp("interp:b", PropertyClass.TERMINATION)
    # Same material bindings, different ids.
    diff = compare_interpretations(a, b)
    assert diff.material is False
    assert material_identity(a) == material_identity(b)


def test_interpretation_set_round_trip() -> None:
    original = expand_ambiguous_prompt("the system reaches ready")
    rebuilt = GoalInterpretationSet.from_dict(original.to_dict())
    assert rebuilt.set_id == original.set_id
    assert rebuilt.ambiguity_status == original.ambiguity_status
    assert len(rebuilt.interpretations) == len(original.interpretations)
    assert rebuilt.material_count == original.material_count
    assert rebuilt.requires_selection is True


def test_report_round_trip(gate: GoalAmbiguityGate) -> None:
    report = gate.analyze_prompt("the system reaches ready")
    rebuilt = GoalAmbiguityReport.from_dict(report.to_dict())
    assert rebuilt.status is report.status
    assert rebuilt.admitted is False
    assert rebuilt.requires_selection is True


def test_expose_ambiguity_convenience() -> None:
    report = expose_ambiguity("the system reaches ready", goal_id="goal:conv")
    assert report.requires_selection
    assert report.interpretation_set.goal_id == "goal:conv"


def test_gate_analyze_dispatch(gate: GoalAmbiguityGate) -> None:
    from_text = gate.analyze("the system reaches ready", goal_id="goal:d1")
    from_goal = gate.analyze(_end_goal(), goal_id="goal:d2")
    from_set = gate.analyze(from_text.interpretation_set)
    assert from_text.requires_selection
    assert from_goal.requires_selection
    assert from_set.requires_selection


# ---------------------------------------------------------------------------
# Unambiguous / underspecified paths
# ---------------------------------------------------------------------------


def test_non_ambiguous_prompt_single_candidate(gate: GoalAmbiguityGate) -> None:
    report = gate.analyze_prompt(
        "PROPERTY existential_reachability QUANTIFIER exists",
        goal_id="goal:ctl",
    )
    # Controlled-language-looking text is not in the ambiguous corpus patterns.
    assert not is_ambiguous_prompt(
        "PROPERTY existential_reachability QUANTIFIER exists"
    )
    assert report.interpretation_set.material_count == 1
    assert report.status in {
        GateStatus.CANDIDATES_PRESENT,
        GateStatus.UNAMBIGUOUS,
    }
    assert report.selected_interpretation_id == ""


def test_controlled_english_includes_property_class() -> None:
    for prop in NON_COLLAPSIBLE_PROPERTY_CLASSES:
        text = controlled_english_for(prop, target_state={"phase": "ready"})
        assert text
        # Visibly names the class or its distinctive wording.
        assert prop.value.replace("_", " ") in text or {
            PropertyClass.EXISTENTIAL_REACHABILITY: "existential",
            PropertyClass.UNIVERSAL_REACHABILITY: "universal",
            PropertyClass.INEVITABILITY: "inevitable",
            PropertyClass.INVARIANCE: "invariant",
            PropertyClass.TERMINATION: "terminat",
            PropertyClass.REFINEMENT: "refin",
        }[prop].lower() in text.lower()


def test_build_interpretation_set_requires_members() -> None:
    with pytest.raises(GoalAmbiguityError, match="at least one"):
        build_interpretation_set(
            goal_id="goal:x",
            caller_text="x",
            interpretations=(),
        )


def test_duplicate_interpretation_ids_rejected() -> None:
    a = _interp("interp:dup", PropertyClass.EXISTENTIAL_REACHABILITY)
    b = _interp("interp:dup", PropertyClass.UNIVERSAL_REACHABILITY)
    with pytest.raises(GoalAmbiguityError, match="unique"):
        GoalInterpretationSet(
            set_id="iset:dup",
            goal_id="goal:x",
            caller_text="x",
            interpretations=(a, b),
            ambiguity_status=AmbiguityStatus.REQUIRES_SELECTION,
            material_candidate_ids=("interp:dup",),
        )


# ---------------------------------------------------------------------------
# Collapse helper negative path
# ---------------------------------------------------------------------------


def test_collapse_helper_raises_on_forced_duplicate_class() -> None:
    # Passing the same class twice with identical bindings must fail.
    with pytest.raises(GoalAmbiguityError, match="collapse"):
        property_classes_cannot_collapse(
            (
                PropertyClass.INVARIANCE,
                PropertyClass.INVARIANCE,
            )
        )
