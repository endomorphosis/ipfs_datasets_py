"""Unit tests for the bounded GUI formal adapter (VGO-020)."""

from __future__ import annotations

import pytest
from ipfs_datasets_py.logic.gui_optimizer.formal_adapter import (
    ADAPTER_SOLVER_ID_CVC5,
    ADAPTER_SOLVER_ID_FINITE_GRAPH,
    FORBIDDEN_CLAIM_KINDS,
    GUI_FORMAL_ADAPTER_INTERFACE,
    UI_CONSTRAINT_PROBLEM_INTERFACE,
    UI_CONSTRAINT_RESULT_INTERFACE,
    Cvc5Capability,
    GuiFormalAdapter,
    GuiFormalAdapterError,
    UiAsyncEffectPremise,
    UiConstraintBackend,
    UiConstraintProblem,
    UiConstraintPropertyKind,
    UiConstraintResult,
    UiConstraintResultKind,
    UiConstraintSourceBinding,
    create_gui_formal_adapter,
    probe_cvc5,
)
from ipfs_datasets_py.logic.gui_optimizer.models import (
    SourceSpan,
    UiEventDefinition,
    UiStateDefinition,
    UiTransitionDefinition,
)
from ipfs_datasets_py.logic.gui_optimizer.schema import (
    AnalysisClassification,
    ConstraintCheckStatus,
    EvidenceLevel,
    UI_EVENT_DEFINITION_INTERFACE,
    UI_EVENT_DEFINITION_SCHEMA,
    UI_STATE_DEFINITION_INTERFACE,
    UI_STATE_DEFINITION_SCHEMA,
    UI_TRANSITION_DEFINITION_INTERFACE,
    UI_TRANSITION_DEFINITION_SCHEMA,
    SOURCE_SPAN_INTERFACE,
    SOURCE_SPAN_SCHEMA,
    VerificationStatus,
)

SCREEN = "screen:agent-supervisor"
APP = "app:agent-supervisor"
MACHINE = "machine:agent-supervisor"


def _state(
    state_id: str,
    kind: str,
    *,
    is_initial: bool = False,
    is_terminal: bool = False,
) -> UiStateDefinition:
    return UiStateDefinition(
        state_id=state_id,
        kind=kind,
        screen_id=SCREEN,
        label=kind,
        is_initial=is_initial,
        is_terminal=is_terminal,
        description="",
        interface=UI_STATE_DEFINITION_INTERFACE,
        schema_version=UI_STATE_DEFINITION_SCHEMA,
    )


def _event(event_id: str, kind: str, name: str | None = None) -> UiEventDefinition:
    return UiEventDefinition(
        event_id=event_id,
        kind=kind,
        name=name or kind,
        description="",
        interface=UI_EVENT_DEFINITION_INTERFACE,
        schema_version=UI_EVENT_DEFINITION_SCHEMA,
    )


def _transition(
    transition_id: str,
    from_state_id: str,
    to_state_id: str,
    event_id: str,
    *,
    is_noop: bool = False,
) -> UiTransitionDefinition:
    return UiTransitionDefinition(
        transition_id=transition_id,
        from_state_id=from_state_id,
        to_state_id=to_state_id,
        event_id=event_id,
        guard="",
        effect_ids=[],
        is_noop=is_noop,
        interface=UI_TRANSITION_DEFINITION_INTERFACE,
        schema_version=UI_TRANSITION_DEFINITION_SCHEMA,
    )


def _healthy_machine() -> dict[str, object]:
    states = (
        _state("state:initial", "initial", is_initial=True),
        _state("state:ready", "ready"),
        _state("state:loading", "loading"),
        _state("state:success", "success", is_terminal=True),
        _state("state:failure", "failure"),
        _state("state:recovery", "recovery"),
    )
    events = (
        _event("event:load", "click", "load"),
        _event("event:network_success", "network_success"),
        _event("event:network_failure", "network_failure"),
        _event("event:retry", "click", "retry"),
    )
    transitions = (
        _transition("t:init-ready", "state:initial", "state:ready", "event:load"),
        _transition(
            "t:ready-loading", "state:ready", "state:loading", "event:load"
        ),
        _transition(
            "t:loading-success",
            "state:loading",
            "state:success",
            "event:network_success",
        ),
        _transition(
            "t:loading-failure",
            "state:loading",
            "state:failure",
            "event:network_failure",
        ),
        _transition(
            "t:failure-recovery",
            "state:failure",
            "state:recovery",
            "event:retry",
        ),
        _transition(
            "t:recovery-ready", "state:recovery", "state:ready", "event:load"
        ),
    )
    return {
        "states": states,
        "events": events,
        "transitions": transitions,
        "initial_state_id": "state:initial",
    }


def _problem(
    property_kind: str,
    *,
    backend: str = "auto",
    claim_kind: str = "bounded_ui_invariant",
    analysis_classification: str = "exact",
    async_effects: tuple = (),
    required_action_ids: tuple = (),
    premises: dict | None = None,
    unresolved: tuple = (),
    machine: dict | None = None,
    check_id: str = "check:default",
) -> UiConstraintProblem:
    machine = machine or _healthy_machine()
    adapter = create_gui_formal_adapter()
    return adapter.build_problem(
        problem_id=f"problem:{property_kind}",
        check_id=check_id,
        property_kind=property_kind,
        application_id=APP,
        screen_id=SCREEN,
        machine_id=MACHINE,
        initial_state_id=str(machine["initial_state_id"]),
        states=machine["states"],  # type: ignore[arg-type]
        events=machine["events"],  # type: ignore[arg-type]
        transitions=machine["transitions"],  # type: ignore[arg-type]
        backend=backend,
        claim_kind=claim_kind,
        analysis_classification=analysis_classification,
        async_effects=async_effects,
        required_action_ids=required_action_ids,
        premises=premises or {},
        unresolved=unresolved,
        source_bindings=(
            UiConstraintSourceBinding(
                binding_id="binding:machine",
                subject_id=MACHINE,
                source_span=SourceSpan(
                    path="swissknife/web/js/apps/agent-supervisor.js",
                    start_line=1,
                    start_column=0,
                    end_line=10,
                    end_column=1,
                    interface=SOURCE_SPAN_INTERFACE,
                    schema_version=SOURCE_SPAN_SCHEMA,
                ),
                evidence="state-machine wire record",
            ),
        ),
    )


# ---------------------------------------------------------------------------
# Interfaces and forbidden claims
# ---------------------------------------------------------------------------


def test_adapter_interface_identities() -> None:
    adapter = create_gui_formal_adapter()
    assert adapter.INTERFACE == GUI_FORMAL_ADAPTER_INTERFACE
    assert UiConstraintProblem.INTERFACE == UI_CONSTRAINT_PROBLEM_INTERFACE
    assert UiConstraintResult.INTERFACE == UI_CONSTRAINT_RESULT_INTERFACE
    assert FORBIDDEN_CLAIM_KINDS == frozenset(
        {
            "beauty",
            "complete_accessibility",
            "complete_security",
            "unbounded_correctness",
        }
    )


@pytest.mark.parametrize("claim", sorted(FORBIDDEN_CLAIM_KINDS))
def test_forbidden_claim_kinds_rejected_at_problem_construction(claim: str) -> None:
    with pytest.raises(GuiFormalAdapterError, match="forbidden"):
        _problem("defined_transition_targets", claim_kind=claim)


def test_result_always_rejects_forbidden_claims() -> None:
    result = create_gui_formal_adapter().solve(
        _problem("defined_transition_targets")
    )
    assert result.forbidden_claims_rejected is True
    assert result.bounded is True
    assert result.property_kind not in FORBIDDEN_CLAIM_KINDS
    assert result.kind is UiConstraintResultKind.PROVED_BOUNDED_PROPERTY
    # Structural proof authority stays structural — never aesthetic/security elevation.
    assert result.verification_status is VerificationStatus.STRUCTURALLY_VALID
    assert result.evidence_level is EvidenceLevel.STRUCTURAL


# ---------------------------------------------------------------------------
# Result kinds: proved / counterexample / structural / unavailable / unknown
# ---------------------------------------------------------------------------


def test_proved_bounded_property_on_defined_transition_targets() -> None:
    result = create_gui_formal_adapter().solve(
        _problem("defined_transition_targets")
    )
    assert result.kind is UiConstraintResultKind.PROVED_BOUNDED_PROPERTY
    assert result.status is ConstraintCheckStatus.SATISFIED
    assert result.backend is UiConstraintBackend.FINITE_GRAPH
    assert result.solver_id == ADAPTER_SOLVER_ID_FINITE_GRAPH
    assert result.counterexample is None
    assert result.source_bindings[0].subject_id == MACHINE


def test_counterexample_undefined_transition_destination() -> None:
    machine = _healthy_machine()
    transitions = list(machine["transitions"])  # type: ignore[arg-type]
    transitions.append(
        _transition(
            "t:bad",
            "state:ready",
            "state:does-not-exist",
            "event:load",
        )
    )
    machine["transitions"] = tuple(transitions)
    result = create_gui_formal_adapter().solve(
        _problem("defined_transition_targets", machine=machine)
    )
    assert result.kind is UiConstraintResultKind.COUNTEREXAMPLE
    assert result.status is ConstraintCheckStatus.VIOLATED
    assert result.counterexample is not None
    assert "state:does-not-exist" in result.counterexample.subject_ids
    assert result.verification_status is VerificationStatus.INVALID


def test_counterexample_failure_without_recovery() -> None:
    machine = {
        "states": (
            _state("state:initial", "initial", is_initial=True),
            _state("state:failure", "failure"),
        ),
        "events": (_event("event:fail", "network_failure"),),
        "transitions": (
            _transition(
                "t:init-fail",
                "state:initial",
                "state:failure",
                "event:fail",
            ),
        ),
        "initial_state_id": "state:initial",
    }
    result = create_gui_formal_adapter().solve(
        _problem("failure_recovery", machine=machine)
    )
    assert result.kind is UiConstraintResultKind.COUNTEREXAMPLE
    assert result.counterexample is not None
    assert result.counterexample.property_kind == "failure_recovery"


def test_structural_result_for_form_accessible_names() -> None:
    result = create_gui_formal_adapter().solve(
        _problem(
            "form_accessible_names",
            premises={
                "form_inputs": [
                    {"input_id": "input:goal", "accessible_name": "Goal"},
                    {"input_id": "input:notes", "accessible_name": "Notes"},
                ]
            },
        )
    )
    assert result.kind is UiConstraintResultKind.STRUCTURAL_RESULT
    assert result.status is ConstraintCheckStatus.SATISFIED
    assert "not complete accessibility" in result.message
    assert result.bounded is True


def test_unavailable_when_cvc5_missing() -> None:
    adapter = GuiFormalAdapter(
        cvc5_probe=lambda: Cvc5Capability(
            available=False, reason="cvc5 executable not found on PATH"
        )
    )
    result = adapter.solve(
        _problem("defined_transition_targets", backend="cvc5_smt")
    )
    assert result.kind is UiConstraintResultKind.UNAVAILABLE
    assert result.status is ConstraintCheckStatus.UNSUPPORTED
    assert result.backend is UiConstraintBackend.CVC5_SMT
    assert result.solver_id == ADAPTER_SOLVER_ID_CVC5
    assert result.smtlib
    assert "(set-logic" in result.smtlib or "declare-const" in result.smtlib
    assert result.smt_compilation_digest.startswith("sha256:")
    assert result.verification_status is VerificationStatus.UNVERIFIED


def test_unknown_when_async_premises_missing() -> None:
    result = create_gui_formal_adapter().solve(
        _problem("async_effect_completeness")
    )
    assert result.kind is UiConstraintResultKind.UNKNOWN
    assert result.status is ConstraintCheckStatus.INCONCLUSIVE
    assert "requires explicit async_effects" in result.message


def test_unknown_for_opaque_unresolved_premises() -> None:
    result = create_gui_formal_adapter().solve(
        _problem(
            "defined_transition_targets",
            analysis_classification="opaque",
            unresolved=("opaque:dynamic-handler",),
        )
    )
    assert result.kind is UiConstraintResultKind.UNKNOWN
    assert result.evidence_level is EvidenceLevel.HEURISTIC
    assert result.verification_status is VerificationStatus.UNVERIFIED


# ---------------------------------------------------------------------------
# Graph fallback properties
# ---------------------------------------------------------------------------


def test_async_effect_completeness_counterexample() -> None:
    result = create_gui_formal_adapter().solve(
        _problem(
            "async_effect_completeness",
            async_effects=(
                UiAsyncEffectPremise(
                    effect_id="effect:submit",
                    has_loading=True,
                    has_success=True,
                    has_failure=False,
                ),
            ),
        )
    )
    assert result.kind is UiConstraintResultKind.COUNTEREXAMPLE
    assert result.counterexample is not None
    assert result.counterexample.subject_ids == ("effect:submit",)


def test_async_effect_completeness_proved_structurally() -> None:
    result = create_gui_formal_adapter().solve(
        _problem(
            "async_effect_completeness",
            async_effects=(
                UiAsyncEffectPremise(
                    effect_id="effect:submit",
                    has_loading=True,
                    has_success=True,
                    has_failure=True,
                ),
            ),
        )
    )
    # Non-exhaustive premise-backed checks stay structural_result.
    assert result.kind is UiConstraintResultKind.STRUCTURAL_RESULT
    assert result.status is ConstraintCheckStatus.SATISFIED


def test_reachable_required_action_counterexample() -> None:
    machine = _healthy_machine()
    # Drop transitions so success is unreachable.
    machine["transitions"] = (
        _transition("t:init-ready", "state:initial", "state:ready", "event:load"),
    )
    machine["events"] = (_event("event:load", "click", "load"),)
    machine["states"] = (
        _state("state:initial", "initial", is_initial=True),
        _state("state:ready", "ready"),
        _state("state:success", "success", is_terminal=True),
    )
    result = create_gui_formal_adapter().solve(
        _problem(
            "reachable_required_action",
            machine=machine,
            required_action_ids=("action:submit",),
            premises={"action_state_ids": {"action:submit": "state:success"}},
        )
    )
    assert result.kind is UiConstraintResultKind.COUNTEREXAMPLE
    assert "unreachable" in result.message


def test_confirmation_bound_action_and_policy() -> None:
    adapter = create_gui_formal_adapter()
    ok = adapter.solve(
        _problem(
            "confirmation_bound_action",
            premises={
                "destructive_action_ids": ["action:delete"],
                "confirmation_by_action": {"action:delete": "confirm:delete"},
            },
        )
    )
    assert ok.kind is UiConstraintResultKind.STRUCTURAL_RESULT

    bad = adapter.solve(
        _problem(
            "confirmation_bound_action",
            premises={
                "destructive_action_ids": ["action:delete"],
                "confirmation_by_action": {},
            },
        )
    )
    assert bad.kind is UiConstraintResultKind.COUNTEREXAMPLE

    policy_ok = adapter.solve(
        _problem(
            "policy_not_browser_authoritative",
            premises={
                "policy": {
                    "browser_policy_authoritative": False,
                    "host_authorization_authoritative": True,
                }
            },
        )
    )
    assert policy_ok.kind is UiConstraintResultKind.STRUCTURAL_RESULT
    assert "not a complete security proof" in policy_ok.message

    policy_bad = adapter.solve(
        _problem(
            "policy_not_browser_authoritative",
            premises={"policy": {"browser_policy_authoritative": True}},
        )
    )
    assert policy_bad.kind is UiConstraintResultKind.COUNTEREXAMPLE


def test_modal_focus_lifecycle() -> None:
    result = create_gui_formal_adapter().solve(
        _problem(
            "modal_focus_lifecycle",
            premises={
                "modal_focus": {
                    "opens_moves_focus_inside": True,
                    "tab_contained": True,
                    "escape_or_cancel_defined": True,
                    "close_restores_focus": True,
                    "hidden_not_focusable": True,
                }
            },
        )
    )
    assert result.kind is UiConstraintResultKind.STRUCTURAL_RESULT
    assert "not complete accessibility" in result.message


# ---------------------------------------------------------------------------
# cvc5-compatible vectors and optional solver execution
# ---------------------------------------------------------------------------


def test_compile_cvc5_vector_without_running_solver() -> None:
    adapter = create_gui_formal_adapter(
        cvc5_probe=lambda: Cvc5Capability(available=False, reason="absent")
    )
    problem = _problem("defined_transition_targets")
    vector = adapter.compile_cvc5_vector(problem)
    assert "smtlib" in vector
    assert vector["smt_compilation_digest"].startswith("sha256:")
    assert vector["solver_id"] == ADAPTER_SOLVER_ID_CVC5
    assert vector["bounded"] == "true"
    assert "declare-const" in vector["smtlib"] or "declare-fun" in vector["smtlib"]
    assert "check-sat" in vector["smtlib"]


def test_cvc5_proved_when_runner_returns_unsat() -> None:
    adapter = GuiFormalAdapter(
        cvc5_probe=lambda: Cvc5Capability(
            available=True, executable="/usr/bin/cvc5", version="1.3.3"
        ),
        smt_runner=lambda _script: "unsat\n",
    )
    result = adapter.solve(
        _problem("defined_transition_targets", backend="cvc5_smt")
    )
    assert result.kind is UiConstraintResultKind.PROVED_BOUNDED_PROPERTY
    assert result.status is ConstraintCheckStatus.SATISFIED
    assert result.verification_status is VerificationStatus.VERIFIED
    assert result.evidence_level is EvidenceLevel.AUTOMATED
    assert result.bounded is True
    assert result.forbidden_claims_rejected is True
    assert "not beauty" in result.message


def test_cvc5_counterexample_when_runner_returns_sat() -> None:
    adapter = GuiFormalAdapter(
        cvc5_probe=lambda: Cvc5Capability(available=True, executable="/usr/bin/cvc5"),
        smt_runner=lambda _script: "sat\n",
    )
    result = adapter.solve(
        _problem("defined_transition_targets", backend="cvc5_smt")
    )
    assert result.kind is UiConstraintResultKind.COUNTEREXAMPLE
    assert result.counterexample is not None


def test_cvc5_unknown_when_runner_returns_unknown() -> None:
    adapter = GuiFormalAdapter(
        cvc5_probe=lambda: Cvc5Capability(available=True, executable="/usr/bin/cvc5"),
        smt_runner=lambda _script: "unknown\n",
    )
    result = adapter.solve(
        _problem("defined_transition_targets", backend="cvc5_smt")
    )
    assert result.kind is UiConstraintResultKind.UNKNOWN
    assert result.status is ConstraintCheckStatus.INCONCLUSIVE


def test_probe_cvc5_injected_which() -> None:
    missing = probe_cvc5(which=lambda _name: None)
    assert missing.available is False
    present = probe_cvc5(
        which=lambda _name: "/usr/bin/cvc5",
        version_runner=lambda _path: "cvc5 version 1.3.3",
    )
    assert present.available is True
    assert present.version == "cvc5 version 1.3.3"


# ---------------------------------------------------------------------------
# Round-trip serialization and provenance
# ---------------------------------------------------------------------------


def test_problem_and_result_round_trip() -> None:
    problem = _problem(
        "defined_transition_targets",
        check_id="check:round-trip",
    )
    encoded = problem.to_dict()
    restored = UiConstraintProblem.from_dict(encoded)
    assert restored.to_dict() == encoded
    assert restored.interface == UI_CONSTRAINT_PROBLEM_INTERFACE

    result = create_gui_formal_adapter().solve(restored)
    result_restored = UiConstraintResult.from_dict(result.to_dict())
    assert result_restored.to_dict() == result.to_dict()
    assert result_restored.source_bindings[0].source_span is not None
    assert (
        result_restored.source_bindings[0].source_span.path
        == "swissknife/web/js/apps/agent-supervisor.js"
    )


def test_result_kinds_are_closed_and_distinct() -> None:
    kinds = {item.value for item in UiConstraintResultKind}
    assert kinds == {
        "proved_bounded_property",
        "counterexample",
        "structural_result",
        "unavailable",
        "unknown",
    }


def test_no_proof_cache_surface_on_adapter() -> None:
    adapter = create_gui_formal_adapter()
    assert not hasattr(adapter, "proof_cache")
    assert not hasattr(adapter, "cache_proof")
    assert not hasattr(adapter, "get_cached_proof")


def test_event_outcome_coverage_unknown_for_floating_events() -> None:
    machine = _healthy_machine()
    events = list(machine["events"])  # type: ignore[arg-type]
    events.append(_event("event:orphan", "custom", "orphan"))
    machine["events"] = tuple(events)
    result = create_gui_formal_adapter().solve(
        _problem("event_outcome_coverage", machine=machine)
    )
    assert result.kind is UiConstraintResultKind.UNKNOWN
    assert "not treated as no-ops" in result.message


def test_single_initial_state_and_duplicates() -> None:
    adapter = create_gui_formal_adapter()
    ok = adapter.solve(_problem("single_initial_state"))
    assert ok.kind is UiConstraintResultKind.PROVED_BOUNDED_PROPERTY

    machine = _healthy_machine()
    states = list(machine["states"])  # type: ignore[arg-type]
    states.append(states[1])  # duplicate ready
    machine["states"] = tuple(states)
    dup = adapter.solve(_problem("no_duplicate_state_ids", machine=machine))
    assert dup.kind is UiConstraintResultKind.COUNTEREXAMPLE


def test_unknown_fields_rejected_on_problem() -> None:
    problem = _problem("defined_transition_targets")
    payload = problem.to_dict()
    payload["extra_field"] = "nope"
    with pytest.raises(GuiFormalAdapterError, match="unknown"):
        UiConstraintProblem.from_dict(payload)


def test_all_result_kinds_emitted_in_suite() -> None:
    """Acceptance: suite distinguishes all five closed result kinds."""

    adapter = GuiFormalAdapter(
        cvc5_probe=lambda: Cvc5Capability(available=False, reason="missing"),
    )
    observed: set[str] = set()

    observed.add(
        adapter.solve(_problem("defined_transition_targets")).kind.value
    )
    machine = _healthy_machine()
    transitions = list(machine["transitions"])  # type: ignore[arg-type]
    transitions.append(
        _transition("t:bad", "state:ready", "state:missing", "event:load")
    )
    machine["transitions"] = tuple(transitions)
    observed.add(
        adapter.solve(
            _problem("defined_transition_targets", machine=machine)
        ).kind.value
    )
    observed.add(
        adapter.solve(
            _problem(
                "form_accessible_names",
                premises={
                    "form_inputs": [
                        {"input_id": "input:a", "accessible_name": "A"}
                    ]
                },
            )
        ).kind.value
    )
    observed.add(
        adapter.solve(
            _problem("defined_transition_targets", backend="cvc5_smt")
        ).kind.value
    )
    observed.add(
        adapter.solve(_problem("async_effect_completeness")).kind.value
    )

    assert observed == {
        "proved_bounded_property",
        "counterexample",
        "structural_result",
        "unavailable",
        "unknown",
    }


def test_property_kind_enum_covers_supported_set() -> None:
    assert {item.value for item in UiConstraintPropertyKind} == {
        "defined_transition_targets",
        "failure_recovery",
        "async_effect_completeness",
        "event_outcome_coverage",
        "reachable_required_action",
        "single_initial_state",
        "no_duplicate_state_ids",
        "confirmation_bound_action",
        "form_accessible_names",
        "modal_focus_lifecycle",
        "policy_not_browser_authoritative",
    }


def test_analysis_classification_independent_of_verification() -> None:
    result = create_gui_formal_adapter().solve(
        _problem(
            "form_accessible_names",
            analysis_classification="conservative",
            premises={
                "form_inputs": [
                    {"input_id": "input:goal", "accessible_name": "Goal"}
                ]
            },
        )
    )
    assert result.analysis_classification is AnalysisClassification.CONSERVATIVE
    assert result.kind is UiConstraintResultKind.STRUCTURAL_RESULT
    # Conservative analysis must not be promoted to verified theorem status.
    assert result.verification_status is not VerificationStatus.VERIFIED
