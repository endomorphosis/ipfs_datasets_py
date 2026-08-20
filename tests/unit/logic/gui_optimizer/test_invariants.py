"""Unit tests for the bounded UI invariant engine (VGO-021)."""

from __future__ import annotations

from pathlib import Path

import pytest

from ipfs_datasets_py.logic.gui_optimizer.formal_adapter import (
    UiAsyncEffectPremise,
    UiConstraintSourceBinding,
)
from ipfs_datasets_py.logic.gui_optimizer.invariants import (
    ENGINE_AUTHORIZES_ACTIONS,
    ENGINE_SOLVER_ID,
    FORBIDDEN_CLAIM_KINDS,
    FULL_ACCESSIBILITY_PROOF,
    FULL_AESTHETIC_PROOF,
    FULL_SECURITY_PROOF,
    INVARIANT_DISCLAIMER,
    REQUIRED_INVARIANT_CHECK_IDS,
    REQUIRED_INVARIANT_PROPERTY_KINDS,
    REQUIRED_INVARIANT_RULES,
    UI_INVARIANT_ENGINE_INTERFACE,
    UI_INVARIANT_VIOLATION_INTERFACE,
    UI_INVARIANT_WORLD_INTERFACE,
    GuiInvariantEngineError,
    UiActionRuntimeObservation,
    UiBindingResolution,
    UiConfirmationObservation,
    UiDeonticStatus,
    UiDomNodeObservation,
    UiFormInputObservation,
    UiFormSubmissionObservation,
    UiImageKind,
    UiInvariantAcceptanceOutcome,
    UiInvariantEngine,
    UiInvariantReport,
    UiInvariantVerdict,
    UiInvariantViolation,
    UiInvariantWorld,
    UiModalFocusObservation,
    UiPolicyObservation,
    UiPresentationObservation,
    UiPresentationVisibility,
    UiUnsupportedPropertyMarker,
    UiValidationErrorObservation,
    create_ui_invariant_engine,
)
from ipfs_datasets_py.logic.gui_optimizer.models import (
    SourceSpan,
    UiActionBinding,
    UiConstraintReceipt,
    UiEventDefinition,
    UiStateDefinition,
    UiTransitionDefinition,
)
from ipfs_datasets_py.logic.gui_optimizer.schema import (
    SOURCE_SPAN_INTERFACE,
    SOURCE_SPAN_SCHEMA,
    UI_ACTION_BINDING_INTERFACE,
    UI_ACTION_BINDING_SCHEMA,
    UI_CONSTRAINT_RECEIPT_INTERFACE,
    UI_EVENT_DEFINITION_INTERFACE,
    UI_EVENT_DEFINITION_SCHEMA,
    UI_STATE_DEFINITION_INTERFACE,
    UI_STATE_DEFINITION_SCHEMA,
    UI_TRANSITION_DEFINITION_INTERFACE,
    UI_TRANSITION_DEFINITION_SCHEMA,
    AnalysisClassification,
    ConstraintCheckStatus,
    EvidenceLevel,
    VerificationStatus,
)

SCREEN = "screen:agent-supervisor"
APP = "app:agent-supervisor"
MACHINE = "machine:agent-supervisor"
REVISION = "deadbeef"
EMPTY_DIGEST = (
    "sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
)


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


def _binding(
    action_id: str,
    *,
    method: str = "method:dispatch",
    schema_id: str = "schema:dispatch",
    is_destructive: bool = False,
    requires_confirmation: bool = False,
    confirmation_id: str = "",
    component_id: str = "comp:goal-form",
) -> UiActionBinding:
    return UiActionBinding(
        action_id=action_id,
        method=method,
        schema_id=schema_id,
        requires_confirmation=requires_confirmation,
        confirmation_id=confirmation_id,
        policy_id="policy:host",
        depends_on_schema=True,
        is_destructive=is_destructive,
        component_id=component_id,
        interface=UI_ACTION_BINDING_INTERFACE,
        schema_version=UI_ACTION_BINDING_SCHEMA,
    )


def _runtime(
    action_id: str,
    *,
    method: str = "method:dispatch",
    schema_id: str = "schema:dispatch",
    visibility: str = "enabled",
    deontic: str = "permitted",
    resolution: str = "exact",
    target_count: int = 1,
    is_dispatchable: bool = True,
    has_hidden_dispatch_path: bool = False,
    runtime_reevaluated: bool = True,
    policy_fresh: bool = True,
    browser_policy_authoritative_claim: bool = False,
) -> UiActionRuntimeObservation:
    return UiActionRuntimeObservation(
        action_id=action_id,
        current_method=method,
        current_schema_id=schema_id,
        current_argument_digest=EMPTY_DIGEST,
        presentation_visibility=visibility,
        deontic_status=deontic,
        resolution=resolution,
        target_count=target_count,
        is_dispatchable=is_dispatchable,
        has_hidden_dispatch_path=has_hidden_dispatch_path,
        runtime_reevaluated=runtime_reevaluated,
        policy_fresh=policy_fresh,
        browser_policy_authoritative_claim=browser_policy_authoritative_claim,
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
        _transition("t:ready-loading", "state:ready", "state:loading", "event:load"),
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
        _transition("t:recovery-ready", "state:recovery", "state:ready", "event:load"),
    )
    return {
        "states": states,
        "events": events,
        "transitions": transitions,
        "initial_state_id": "state:initial",
    }


def _source_binding() -> UiConstraintSourceBinding:
    return UiConstraintSourceBinding(
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
    )


def _healthy_world(**overrides: object) -> UiInvariantWorld:
    machine = _healthy_machine()
    payload: dict[str, object] = {
        "application_id": APP,
        "screen_id": SCREEN,
        "machine_id": MACHINE,
        "repository_revision": REVISION,
        "initial_state_id": machine["initial_state_id"],
        "states": machine["states"],
        "events": machine["events"],
        "transitions": machine["transitions"],
        "analysis_classification": AnalysisClassification.EXACT,
        "async_effects": (
            UiAsyncEffectPremise(
                effect_id="effect:load",
                has_loading=True,
                has_success=True,
                has_failure=True,
            ),
        ),
        "required_action_ids": ("action:dispatch",),
        "action_state_ids": {
            "action:dispatch": "state:ready",
            "action:delete": "state:ready",
        },
        "action_bindings": (
            _binding("action:dispatch"),
            _binding(
                "action:delete",
                method="method:delete",
                schema_id="schema:delete",
                is_destructive=True,
                requires_confirmation=True,
                confirmation_id="confirm:delete",
            ),
        ),
        "confirmations": (
            UiConfirmationObservation(
                confirmation_id="confirm:delete",
                action_id="action:delete",
                argument_digest=EMPTY_DIGEST,
                granted=False,
                policy_decision_id="policy-decision:1",
            ),
        ),
        "runtime_observations": (
            _runtime("action:dispatch"),
            _runtime(
                "action:delete",
                method="method:delete",
                schema_id="schema:delete",
            ),
        ),
        "form_inputs": (
            UiFormInputObservation(
                input_id="input:goal",
                accessible_name="Goal",
                required=True,
                exposes_required_state=True,
                associated_error_ids=("error:goal-empty",),
            ),
        ),
        "validation_errors": (
            UiValidationErrorObservation(
                error_id="error:goal-empty",
                field_id="input:goal",
                message="Goal is required",
            ),
        ),
        "form_submission": UiFormSubmissionObservation(
            discards_validation_failure=False,
            success_follows_confirmed_effect=True,
        ),
        "modal_focus": (
            UiModalFocusObservation(
                modal_id="modal:confirm",
                opens_moves_focus_inside=True,
                tab_contained=True,
                escape_or_cancel_defined=True,
                close_restores_focus=True,
                hidden_not_focusable=True,
            ),
        ),
        "dom_nodes": (
            UiDomNodeObservation(
                node_id="node:heading",
                dom_id="heading-main",
                role="heading",
                heading_level=1,
                accessible_name="Agent Supervisor",
            ),
            UiDomNodeObservation(
                node_id="node:subheading",
                dom_id="heading-goals",
                role="heading",
                heading_level=2,
                accessible_name="Goals",
            ),
            UiDomNodeObservation(
                node_id="node:submit",
                dom_id="submit-goal",
                role="button",
                interactive=True,
                native_control=True,
                accessible_name="Submit goal",
                has_keyboard_activation=True,
            ),
            UiDomNodeObservation(
                node_id="node:toggle",
                dom_id="custom-toggle",
                role="switch",
                interactive=True,
                native_control=False,
                accessible_name="Compact layout",
                has_keyboard_activation=True,
            ),
            UiDomNodeObservation(
                node_id="node:chart",
                dom_id="status-chart",
                role="img",
                image_kind=UiImageKind.MEANINGFUL,
                has_text_alternative=True,
                accessible_name="Lane status",
            ),
            UiDomNodeObservation(
                node_id="node:decor",
                dom_id="spacer-mark",
                role="presentation",
                image_kind=UiImageKind.DECORATIVE,
                decorative_hidden=True,
            ),
        ),
        "presentation_components": (
            UiPresentationObservation(
                component_id="comp:goal-form",
                is_presentation=True,
                accesses_credentials=False,
            ),
        ),
        "policy": UiPolicyObservation(
            browser_policy_authoritative=False,
            host_authorization_authoritative=True,
        ),
        "source_bindings": (_source_binding(),),
        "unresolved": (),
    }
    payload.update(overrides)
    return UiInvariantWorld(**payload)  # type: ignore[arg-type]


def _machine_only_world() -> UiInvariantWorld:
    machine = _healthy_machine()
    return UiInvariantWorld(
        application_id=APP,
        screen_id=SCREEN,
        machine_id=MACHINE,
        repository_revision=REVISION,
        initial_state_id=str(machine["initial_state_id"]),
        states=machine["states"],  # type: ignore[arg-type]
        events=machine["events"],  # type: ignore[arg-type]
        transitions=machine["transitions"],  # type: ignore[arg-type]
        source_bindings=(_source_binding(),),
    )


# ---------------------------------------------------------------------------
# Catalog / interface identities
# ---------------------------------------------------------------------------


def test_engine_interface_identities_and_disclaimer() -> None:
    engine = create_ui_invariant_engine()
    assert engine.INTERFACE == UI_INVARIANT_ENGINE_INTERFACE
    assert UiInvariantViolation.INTERFACE == UI_INVARIANT_VIOLATION_INTERFACE
    assert UiInvariantWorld.INTERFACE == UI_INVARIANT_WORLD_INTERFACE
    assert UiConstraintReceipt.INTERFACE == UI_CONSTRAINT_RECEIPT_INTERFACE
    assert FULL_ACCESSIBILITY_PROOF is False
    assert FULL_SECURITY_PROOF is False
    assert FULL_AESTHETIC_PROOF is False
    assert ENGINE_AUTHORIZES_ACTIONS is False
    assert "not establish complete accessibility" in INVARIANT_DISCLAIMER
    assert "never authorizes" in INVARIANT_DISCLAIMER
    assert "beauty" in FORBIDDEN_CLAIM_KINDS
    assert "complete_accessibility" in FORBIDDEN_CLAIM_KINDS
    assert "complete_security" in FORBIDDEN_CLAIM_KINDS
    assert "unbounded_correctness" in FORBIDDEN_CLAIM_KINDS


def test_required_catalog_is_finite_and_covers_plan_obligations() -> None:
    kinds = {rule.property_kind for rule in REQUIRED_INVARIANT_RULES}
    assert kinds == REQUIRED_INVARIANT_PROPERTY_KINDS
    expected = {
        "defined_transition_targets",
        "event_outcome_coverage",
        "failure_recovery",
        "async_effect_completeness",
        "reachable_required_action",
        "single_initial_state",
        "no_duplicate_state_ids",
        "confirmation_bound_action",
        "presentation_no_credentials",
        "policy_not_browser_authoritative",
        "no_hidden_dispatch",
        "single_action_binding",
        "runtime_action_reevaluation",
        "stale_policy_cannot_authorize",
        "form_accessible_names",
        "form_required_state",
        "form_error_association",
        "form_submission_validation",
        "form_success_after_effect",
        "modal_focus_lifecycle",
        "unique_dom_ids",
        "interactive_accessible_names",
        "image_text_alternatives",
        "keyboard_activation",
        "heading_structure",
    }
    assert kinds == expected
    assert len(REQUIRED_INVARIANT_RULES) == 25
    assert len(REQUIRED_INVARIANT_CHECK_IDS) == 25
    assert len(set(REQUIRED_INVARIANT_CHECK_IDS)) == 25
    families = {rule.family.value for rule in REQUIRED_INVARIANT_RULES}
    assert families == {
        "state_completeness",
        "destructive_policy",
        "form_integrity",
        "structure_accessibility",
    }


# ---------------------------------------------------------------------------
# Healthy / incomplete worlds
# ---------------------------------------------------------------------------


def test_healthy_world_passes_every_required_rule() -> None:
    report = create_ui_invariant_engine().check(_healthy_world())
    assert len(report.check_results) == len(REQUIRED_INVARIANT_RULES)
    assert all(item.verdict is UiInvariantVerdict.PASS for item in report.check_results)
    assert report.may_auto_accept is True
    assert report.acceptance_outcome is UiInvariantAcceptanceOutcome.ALLOW_AUTOMATIC
    assert report.authorizes is False
    assert report.full_accessibility_proof is False
    assert report.full_security_proof is False
    assert report.bounded is True
    assert report.forbidden_claims_rejected is True
    assert report.verification_status is VerificationStatus.STRUCTURALLY_VALID
    assert report.receipt.solver_id == ENGINE_SOLVER_ID
    assert report.receipt.evidence_level is EvidenceLevel.STRUCTURAL
    assert report.receipt.interface == UI_CONSTRAINT_RECEIPT_INTERFACE
    assert [item.rule.check_id for item in report.check_results] == list(
        REQUIRED_INVARIANT_CHECK_IDS
    )
    assert report.receipt.statuses == (ConstraintCheckStatus.SATISFIED,)
    assert len(report.receipt.check_ids) == 1
    assert report.receipt.check_ids[0] in REQUIRED_INVARIANT_CHECK_IDS
    assert report.receipt.violated_check_ids == ()
    assert report.receipt.unsupported_check_ids == ()
    assert set(report.satisfying_rule_ids) == {rule.rule_id for rule in REQUIRED_INVARIANT_RULES}
    assert "not complete accessibility" in report.disclaimer or "complete accessibility" in report.disclaimer
    assert report.world_digest.startswith("sha256:")


def test_machine_only_world_is_unknown_for_observation_rules_and_blocks_accept() -> None:
    report = create_ui_invariant_engine().check(_machine_only_world())
    graph_kinds = {
        "defined_transition_targets",
        "event_outcome_coverage",
        "failure_recovery",
        "single_initial_state",
        "no_duplicate_state_ids",
    }
    for item in report.check_results:
        if item.rule.property_kind in graph_kinds:
            assert item.verdict is UiInvariantVerdict.PASS
        else:
            assert item.verdict is UiInvariantVerdict.UNKNOWN
            assert item.unsupported is not None
    assert report.may_auto_accept is False
    assert report.acceptance_outcome is UiInvariantAcceptanceOutcome.BLOCK_AUTOMATIC
    assert report.authorizes is False
    assert report.verification_status is VerificationStatus.UNVERIFIED
    assert report.unsupported_markers
    assert not report.violations


def test_uncertainty_never_auto_accepts_or_authorizes() -> None:
    exact_unknown = create_ui_invariant_engine().check(_machine_only_world())
    heuristic = create_ui_invariant_engine().check(
        _healthy_world(analysis_classification="heuristic")
    )
    opaque = create_ui_invariant_engine().check(
        _healthy_world(
            analysis_classification="opaque",
            unresolved=("opaque:dynamic-handler",),
        )
    )
    unresolved_only = create_ui_invariant_engine().check(
        _healthy_world(unresolved=("unresolved:async-target",))
    )
    for report in (exact_unknown, heuristic, opaque, unresolved_only):
        assert report.may_auto_accept is False
        assert report.acceptance_outcome is UiInvariantAcceptanceOutcome.BLOCK_AUTOMATIC
        assert report.authorizes is False
        assert report.verification_status is not VerificationStatus.VERIFIED


# ---------------------------------------------------------------------------
# Failures with counterexamples
# ---------------------------------------------------------------------------


def test_undefined_transition_target_is_fail_with_counterexample() -> None:
    machine = _healthy_machine()
    transitions = list(machine["transitions"])  # type: ignore[arg-type]
    transitions.append(
        _transition("t:bad", "state:ready", "state:does-not-exist", "event:load")
    )
    world = _healthy_world(transitions=tuple(transitions))
    report = create_ui_invariant_engine().check(world)
    result = report.result_for("defined_transition_targets")
    assert result.verdict is UiInvariantVerdict.FAIL
    assert result.violation is not None
    assert "state:does-not-exist" in result.violation.subject_ids
    assert report.receipt.violated_check_ids == ("check:defined-transition-targets",)
    assert report.may_auto_accept is False
    assert report.verification_status is VerificationStatus.INVALID


def test_failure_without_recovery_is_counterexample() -> None:
    world = _healthy_world(
        states=(
            _state("state:initial", "initial", is_initial=True),
            _state("state:failure", "failure"),
        ),
        events=(_event("event:fail", "network_failure"),),
        transitions=(
            _transition("t:init-fail", "state:initial", "state:failure", "event:fail"),
        ),
        initial_state_id="state:initial",
        required_action_ids=(),
        action_state_ids={},
    )
    result = create_ui_invariant_engine().check(world).result_for("failure_recovery")
    assert result.verdict is UiInvariantVerdict.FAIL
    assert result.violation is not None
    assert result.violation.property_kind == "failure_recovery"


def test_incomplete_async_effect_is_counterexample() -> None:
    world = _healthy_world(
        async_effects=(
            UiAsyncEffectPremise(
                effect_id="effect:submit",
                has_loading=True,
                has_success=True,
                has_failure=False,
            ),
        )
    )
    result = create_ui_invariant_engine().check(world).result_for(
        "async_effect_completeness"
    )
    assert result.verdict is UiInvariantVerdict.FAIL
    assert result.violation is not None
    assert result.violation.subject_ids == ("effect:submit",)


def test_unreachable_required_action_is_counterexample() -> None:
    world = _healthy_world(
        states=(
            _state("state:initial", "initial", is_initial=True),
            _state("state:ready", "ready"),
            _state("state:success", "success", is_terminal=True),
        ),
        events=(_event("event:load", "click", "load"),),
        transitions=(
            _transition("t:init-ready", "state:initial", "state:ready", "event:load"),
        ),
        required_action_ids=("action:submit",),
        action_state_ids={"action:submit": "state:success"},
        action_bindings=(_binding("action:submit", method="method:submit", schema_id="schema:submit"),),
        runtime_observations=(
            _runtime("action:submit", method="method:submit", schema_id="schema:submit"),
        ),
        confirmations=(),
    )
    result = create_ui_invariant_engine().check(world).result_for(
        "reachable_required_action"
    )
    assert result.verdict is UiInvariantVerdict.FAIL
    assert "unreachable" in result.message


def test_per_state_event_coverage_counterexample() -> None:
    world = _healthy_world(
        state_event_ids={
            "state:initial": ("event:load",),
            "state:ready": ("event:load", "event:missing"),
            "state:loading": ("event:network_success", "event:network_failure"),
            "state:failure": ("event:retry",),
            "state:recovery": ("event:load",),
        }
    )
    # event:missing is not declared; should fail as undefined or missing outcome.
    result = create_ui_invariant_engine().check(world).result_for("event_outcome_coverage")
    assert result.verdict is UiInvariantVerdict.FAIL
    assert result.violation is not None


@pytest.mark.parametrize(
    ("overrides", "property_kind", "subject_fragment"),
    [
        (
            {
                "action_bindings": (
                    _binding("action:dispatch"),
                    _binding(
                        "action:delete",
                        method="method:delete",
                        schema_id="schema:delete",
                        is_destructive=True,
                        requires_confirmation=False,
                    ),
                ),
                "confirmations": (),
            },
            "confirmation_bound_action",
            "action:delete",
        ),
        (
            {
                "presentation_components": (
                    UiPresentationObservation(
                        component_id="comp:goal-form",
                        is_presentation=True,
                        accesses_credentials=True,
                    ),
                )
            },
            "presentation_no_credentials",
            "comp:goal-form",
        ),
        (
            {
                "policy": UiPolicyObservation(
                    browser_policy_authoritative=True,
                    host_authorization_authoritative=True,
                )
            },
            "policy_not_browser_authoritative",
            "policy:browser",
        ),
        (
            {
                "runtime_observations": (
                    _runtime("action:dispatch"),
                    _runtime(
                        "action:delete",
                        method="method:delete",
                        schema_id="schema:delete",
                        deontic="prohibited",
                        visibility="hidden",
                        is_dispatchable=True,
                        has_hidden_dispatch_path=True,
                    ),
                )
            },
            "no_hidden_dispatch",
            "action:delete",
        ),
        (
            {
                "runtime_observations": (
                    _runtime("action:dispatch", target_count=2),
                    _runtime(
                        "action:delete",
                        method="method:delete",
                        schema_id="schema:delete",
                    ),
                )
            },
            "single_action_binding",
            "action:dispatch",
        ),
        (
            {
                "runtime_observations": (
                    _runtime("action:dispatch", runtime_reevaluated=False),
                    _runtime(
                        "action:delete",
                        method="method:delete",
                        schema_id="schema:delete",
                    ),
                )
            },
            "runtime_action_reevaluation",
            "action:dispatch",
        ),
        (
            {
                "runtime_observations": (
                    _runtime("action:dispatch", policy_fresh=False),
                    _runtime(
                        "action:delete",
                        method="method:delete",
                        schema_id="schema:delete",
                    ),
                )
            },
            "stale_policy_cannot_authorize",
            "action:dispatch",
        ),
        (
            {
                "form_inputs": (
                    UiFormInputObservation(
                        input_id="input:goal",
                        accessible_name="",
                        required=True,
                        exposes_required_state=True,
                    ),
                )
            },
            "form_accessible_names",
            "input:goal",
        ),
        (
            {
                "form_inputs": (
                    UiFormInputObservation(
                        input_id="input:goal",
                        accessible_name="Goal",
                        required=True,
                        exposes_required_state=False,
                    ),
                )
            },
            "form_required_state",
            "input:goal",
        ),
        (
            {
                "form_inputs": (
                    UiFormInputObservation(
                        input_id="input:goal",
                        accessible_name="Goal",
                        required=True,
                        exposes_required_state=True,
                        associated_error_ids=(),
                    ),
                )
            },
            "form_error_association",
            "error:goal-empty",
        ),
        (
            {
                "form_submission": UiFormSubmissionObservation(
                    discards_validation_failure=True,
                    success_follows_confirmed_effect=True,
                )
            },
            "form_submission_validation",
            "form:submission",
        ),
        (
            {
                "form_submission": UiFormSubmissionObservation(
                    discards_validation_failure=False,
                    success_follows_confirmed_effect=False,
                )
            },
            "form_success_after_effect",
            "form:success",
        ),
        (
            {
                "modal_focus": (
                    UiModalFocusObservation(
                        modal_id="modal:confirm",
                        opens_moves_focus_inside=True,
                        tab_contained=False,
                        escape_or_cancel_defined=True,
                        close_restores_focus=True,
                        hidden_not_focusable=True,
                    ),
                )
            },
            "modal_focus_lifecycle",
            "tab_contained",
        ),
        (
            {
                "dom_nodes": (
                    UiDomNodeObservation(
                        node_id="node:a",
                        dom_id="dup",
                        heading_level=1,
                    ),
                    UiDomNodeObservation(
                        node_id="node:b",
                        dom_id="dup",
                        heading_level=2,
                    ),
                )
            },
            "unique_dom_ids",
            "node:b",
        ),
        (
            {
                "dom_nodes": (
                    UiDomNodeObservation(
                        node_id="node:heading",
                        heading_level=1,
                    ),
                    UiDomNodeObservation(
                        node_id="node:button",
                        interactive=True,
                        native_control=True,
                        accessible_name="",
                    ),
                )
            },
            "interactive_accessible_names",
            "node:button",
        ),
        (
            {
                "dom_nodes": (
                    UiDomNodeObservation(
                        node_id="node:heading",
                        heading_level=1,
                    ),
                    UiDomNodeObservation(
                        node_id="node:chart",
                        image_kind=UiImageKind.MEANINGFUL,
                        has_text_alternative=False,
                    ),
                )
            },
            "image_text_alternatives",
            "node:chart",
        ),
        (
            {
                "dom_nodes": (
                    UiDomNodeObservation(
                        node_id="node:heading",
                        heading_level=1,
                    ),
                    UiDomNodeObservation(
                        node_id="node:toggle",
                        interactive=True,
                        native_control=False,
                        accessible_name="Toggle",
                        has_keyboard_activation=False,
                    ),
                )
            },
            "keyboard_activation",
            "node:toggle",
        ),
        (
            {
                "dom_nodes": (
                    UiDomNodeObservation(
                        node_id="node:h1",
                        heading_level=1,
                    ),
                    UiDomNodeObservation(
                        node_id="node:h3",
                        heading_level=3,
                    ),
                )
            },
            "heading_structure",
            "node:h3",
        ),
    ],
)
def test_each_local_rule_emits_fail_and_counterexample(
    overrides: dict[str, object],
    property_kind: str,
    subject_fragment: str,
) -> None:
    report = create_ui_invariant_engine().check(_healthy_world(**overrides))
    result = report.result_for(property_kind)
    assert result.verdict is UiInvariantVerdict.FAIL
    assert result.status is ConstraintCheckStatus.VIOLATED
    assert result.violation is not None
    assert result.violation.interface == UI_INVARIANT_VIOLATION_INTERFACE
    assert result.violation.rule_id == f"invariant:{property_kind.replace('_', '-')}"
    assert subject_fragment in result.violation.subject_ids
    assert report.may_auto_accept is False
    assert report.authorizes is False
    assert result.rule.check_id in report.receipt.violated_check_ids


def test_confirmation_requires_matching_action_and_argument_digest() -> None:
    world = _healthy_world(
        confirmations=(
            UiConfirmationObservation(
                confirmation_id="confirm:delete",
                action_id="action:other",
                argument_digest=EMPTY_DIGEST,
            ),
        )
    )
    result = create_ui_invariant_engine().check(world).result_for(
        "confirmation_bound_action"
    )
    assert result.verdict is UiInvariantVerdict.FAIL
    world_missing_digest = _healthy_world(
        confirmations=(
            UiConfirmationObservation(
                confirmation_id="confirm:delete",
                action_id="action:delete",
                argument_digest="",
            ),
        )
    )
    missing = create_ui_invariant_engine().check(world_missing_digest).result_for(
        "confirmation_bound_action"
    )
    assert missing.verdict is UiInvariantVerdict.FAIL


def test_host_authorization_must_remain_authoritative() -> None:
    world = _healthy_world(
        policy=UiPolicyObservation(
            browser_policy_authoritative=False,
            host_authorization_authoritative=False,
        )
    )
    result = create_ui_invariant_engine().check(world).result_for(
        "policy_not_browser_authoritative"
    )
    assert result.verdict is UiInvariantVerdict.FAIL
    assert "policy:host" in result.violation.subject_ids  # type: ignore[union-attr]


def test_decorative_image_not_hidden_is_counterexample() -> None:
    world = _healthy_world(
        dom_nodes=(
            UiDomNodeObservation(node_id="node:h1", heading_level=1),
            UiDomNodeObservation(
                node_id="node:decor",
                image_kind=UiImageKind.DECORATIVE,
                decorative_hidden=False,
            ),
        )
    )
    result = create_ui_invariant_engine().check(world).result_for(
        "image_text_alternatives"
    )
    assert result.verdict is UiInvariantVerdict.FAIL


# ---------------------------------------------------------------------------
# Unknown / unsupported markers
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "property_kind",
    [
        "async_effect_completeness",
        "reachable_required_action",
        "confirmation_bound_action",
        "presentation_no_credentials",
        "policy_not_browser_authoritative",
        "no_hidden_dispatch",
        "single_action_binding",
        "runtime_action_reevaluation",
        "stale_policy_cannot_authorize",
        "form_accessible_names",
        "form_required_state",
        "form_error_association",
        "form_submission_validation",
        "form_success_after_effect",
        "modal_focus_lifecycle",
        "unique_dom_ids",
        "interactive_accessible_names",
        "image_text_alternatives",
        "keyboard_activation",
        "heading_structure",
    ],
)
def test_observation_rules_are_unknown_without_premises(property_kind: str) -> None:
    result = create_ui_invariant_engine().check(_machine_only_world()).result_for(
        property_kind
    )
    assert result.verdict is UiInvariantVerdict.UNKNOWN
    assert result.status in {
        ConstraintCheckStatus.INCONCLUSIVE,
        ConstraintCheckStatus.UNSUPPORTED,
    }
    assert result.unsupported is not None
    assert result.unsupported.property_kind == property_kind
    assert result.violation is None


def test_ambiguous_binding_is_unknown_not_pass() -> None:
    world = _healthy_world(
        runtime_observations=(
            _runtime("action:dispatch", resolution="ambiguous"),
            _runtime(
                "action:delete",
                method="method:delete",
                schema_id="schema:delete",
            ),
        )
    )
    result = create_ui_invariant_engine().check(world).result_for("single_action_binding")
    assert result.verdict is UiInvariantVerdict.UNKNOWN
    report = create_ui_invariant_engine().check(world)
    assert report.may_auto_accept is False


def test_floating_declared_event_is_unknown_not_invented_noop() -> None:
    machine = _healthy_machine()
    events = list(machine["events"])  # type: ignore[arg-type]
    events.append(_event("event:orphan", "custom", "orphan"))
    world = _healthy_world(events=tuple(events))
    result = create_ui_invariant_engine().check(world).result_for("event_outcome_coverage")
    assert result.verdict is UiInvariantVerdict.UNKNOWN
    assert "not treated as no-ops" in result.message


def test_missing_required_state_observation_is_unknown() -> None:
    world = _healthy_world(
        form_inputs=(
            UiFormInputObservation(
                input_id="input:goal",
                accessible_name="Goal",
                required=True,
                exposes_required_state=None,
                associated_error_ids=("error:goal-empty",),
            ),
        )
    )
    result = create_ui_invariant_engine().check(world).result_for("form_required_state")
    assert result.verdict is UiInvariantVerdict.UNKNOWN


# ---------------------------------------------------------------------------
# Receipt contract and serialization
# ---------------------------------------------------------------------------


def test_receipt_violated_and_unsupported_ids_match_statuses() -> None:
    world = _healthy_world(
        form_inputs=(
            UiFormInputObservation(input_id="input:goal", accessible_name=""),
        )
    )
    report = create_ui_invariant_engine().check(world)
    receipt = report.receipt
    expected_violated = tuple(
        check_id
        for check_id, status in zip(receipt.check_ids, receipt.statuses, strict=True)
        if status is ConstraintCheckStatus.VIOLATED
    )
    expected_unsupported = tuple(
        check_id
        for check_id, status in zip(receipt.check_ids, receipt.statuses, strict=True)
        if status is ConstraintCheckStatus.UNSUPPORTED
    )
    assert receipt.violated_check_ids == expected_violated
    assert receipt.unsupported_check_ids == expected_unsupported
    restored = UiConstraintReceipt.from_dict(receipt.to_dict())
    assert restored.to_dict() == receipt.to_dict()


def test_world_and_report_round_trip() -> None:
    world = _healthy_world()
    encoded = world.to_dict()
    restored = UiInvariantWorld.from_dict(encoded)
    assert restored.to_dict() == encoded
    report = create_ui_invariant_engine().check(restored)
    report_restored = UiInvariantReport.from_dict(report.to_dict())
    assert report_restored.receipt.to_dict() == report.receipt.to_dict()
    assert [item.to_dict() for item in report_restored.violations] == [
        item.to_dict() for item in report.violations
    ]
    assert report_restored.may_auto_accept is True
    assert report_restored.authorizes is False
    assert report_restored.disclaimer == INVARIANT_DISCLAIMER


def test_world_rejects_unknown_fields() -> None:
    payload = _healthy_world().to_dict()
    payload["aesthetic_score"] = 11
    with pytest.raises(GuiInvariantEngineError, match="unknown"):
        UiInvariantWorld.from_dict(payload)


def test_violation_rejects_unknown_fields_and_non_violated_status() -> None:
    with pytest.raises(GuiInvariantEngineError, match="unknown"):
        UiInvariantViolation.from_dict(
            {
                "violation_id": "violation:1",
                "rule_id": "invariant:unique-dom-ids",
                "check_id": "check:unique-dom-ids",
                "property_kind": "unique_dom_ids",
                "subject_ids": ["node:a"],
                "message": "dup",
                "extra": True,
            }
        )
    with pytest.raises(GuiInvariantEngineError, match="violated"):
        UiInvariantViolation(
            violation_id="violation:1",
            rule_id="invariant:unique-dom-ids",
            check_id="check:unique-dom-ids",
            property_kind="unique_dom_ids",
            subject_ids=("node:a",),
            message="dup",
            status=ConstraintCheckStatus.SATISFIED,
        )


def test_report_never_uses_verified_status() -> None:
    report = create_ui_invariant_engine().check(_healthy_world())
    assert report.verification_status is VerificationStatus.STRUCTURALLY_VALID
    assert report.receipt.verification_status is VerificationStatus.STRUCTURALLY_VALID
    assert report.verification_status is not VerificationStatus.VERIFIED


def test_source_bindings_travel_with_violations() -> None:
    world = _healthy_world(
        form_inputs=(
            UiFormInputObservation(input_id="input:goal", accessible_name=""),
        )
    )
    report = create_ui_invariant_engine().check(world)
    assert report.violations
    assert report.violations[0].source_bindings[0].source_span is not None
    assert (
        report.violations[0].source_bindings[0].source_span.path
        == "swissknife/web/js/apps/agent-supervisor.js"
    )


def test_check_accepts_mapping_world() -> None:
    report = create_ui_invariant_engine().check(_healthy_world().to_dict())
    assert report.may_auto_accept is True


def test_engine_is_independent_of_aesthetic_scoring() -> None:
    module_source = (
        Path(__file__).resolve().parents[4]
        / "ipfs_datasets_py/logic/gui_optimizer/invariants.py"
    ).read_text(encoding="utf-8")
    assert "aesthetic_score" not in module_source
    assert "beauty_score" not in module_source
    report = create_ui_invariant_engine().check(_healthy_world())
    assert "aesthetic" not in report.receipt.to_dict()


def test_duplicate_state_ids_fail() -> None:
    machine = _healthy_machine()
    states = list(machine["states"])  # type: ignore[arg-type]
    states.append(_state("state:ready", "ready"))
    world = _healthy_world(states=tuple(states))
    result = create_ui_invariant_engine().check(world).result_for("no_duplicate_state_ids")
    assert result.verdict is UiInvariantVerdict.FAIL


def test_multiple_initial_states_fail() -> None:
    machine = _healthy_machine()
    states = list(machine["states"])  # type: ignore[arg-type]
    states[1] = _state("state:ready", "ready", is_initial=True)
    world = _healthy_world(states=tuple(states))
    result = create_ui_invariant_engine().check(world).result_for("single_initial_state")
    assert result.verdict is UiInvariantVerdict.FAIL


def test_pass_fail_unknown_are_the_only_verdicts() -> None:
    assert {item.value for item in UiInvariantVerdict} == {"pass", "fail", "unknown"}
    report = create_ui_invariant_engine().check(_machine_only_world())
    assert {item.verdict for item in report.check_results} <= set(UiInvariantVerdict)


def test_unsupported_marker_rejects_satisfied_status() -> None:
    with pytest.raises(GuiInvariantEngineError, match="unsupported marker"):
        UiUnsupportedPropertyMarker(
            rule_id="invariant:form-accessible-names",
            check_id="check:form-accessible-names",
            property_kind="form_accessible_names",
            status=ConstraintCheckStatus.SATISFIED,
            reason="nope",
        )


def test_runtime_enums_are_closed() -> None:
    assert {item.value for item in UiPresentationVisibility} == {
        "enabled",
        "disabled",
        "hidden",
    }
    assert {item.value for item in UiDeonticStatus} == {
        "permitted",
        "obligated",
        "prohibited",
        "unavailable",
    }
    assert {item.value for item in UiBindingResolution} == {
        "exact",
        "ambiguous",
        "dynamic",
        "unresolved",
    }
    with pytest.raises(GuiInvariantEngineError):
        UiActionRuntimeObservation(
            action_id="action:dispatch",
            current_method="method:dispatch",
            current_schema_id="schema:dispatch",
            presentation_visibility="visible",
        )


def test_factory_returns_engine_instance() -> None:
    engine = create_ui_invariant_engine()
    assert isinstance(engine, UiInvariantEngine)
    assert engine.required_rules == REQUIRED_INVARIANT_RULES
