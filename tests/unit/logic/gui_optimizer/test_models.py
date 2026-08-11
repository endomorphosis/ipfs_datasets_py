"""Unit tests for closed GUI optimizer data models (VGO-001).

Evidence subset:

* required-model inventory
* closed-schema rejection vectors
* enum and finite-bound tests
* analysis-class vs verification-status separation
* parameterized wrong-container vectors for array and mapping fields
* required schema/interface vectors
* registered optimizer-schema vectors
* canonical mapping-key collision vectors
* cross-field receipt-consistency vectors
* exact round-trip type preservation
* required capsule/context/visual-receipt field inventory
* undeclared-artifact absence
* standalone package import boundary
"""

from __future__ import annotations

import ast
import importlib
import inspect
import json
from pathlib import Path
from typing import Any

import pytest

from ipfs_datasets_py.logic.gui_optimizer import (
    REGISTERED_OPTIMIZER_SCHEMA_VERSIONS,
    REQUIRED_MODEL_INTERFACES,
    SCHEMA_VERSION_BY_INTERFACE,
    AccessibilityReceipt,
    AccessibilityRequirementKind,
    AnalysisClassification,
    ChangeKind,
    CompletenessBoundary,
    ConstraintCheckStatus,
    EvidenceLevel,
    ExtractionConfidence,
    ExtractionMethod,
    GuiApplicationIdentity,
    GuiImprovementProposal,
    GuiImprovementReceipt,
    GuiOptimizerDecodeError,
    GuiScreenIdentity,
    InteractionReceipt,
    InvalidationReason,
    LayoutConstraintKind,
    MODEL_TYPES,
    ProposalDecision,
    ProposalRouteKind,
    SourceSpan,
    UiAccessibilityContract,
    UiActionBinding,
    UiBaseline,
    UiChangeSet,
    UiComponentIdentity,
    UiComponentKind,
    UiComponentVersion,
    UiConstraintReceipt,
    UiContextPack,
    UiDependencyEdge,
    UiDependencyRelation,
    UiEvaluationScenario,
    UiEventDefinition,
    UiEventKind,
    UiInvalidationPlan,
    UiLayoutConstraint,
    UiSemanticCapsule,
    UiStateDefinition,
    UiStateKind,
    UiTransitionDefinition,
    VerificationStatus,
    ViewportSpec,
    VisualDecision,
    VisualRegressionReceipt,
    assert_required_models_registered,
    canonical_model_bytes,
    canonical_model_json,
    decode_model,
    required_model_inventory,
)


DIGEST_A = "sha256:" + ("a" * 64)
DIGEST_B = "sha256:" + ("b" * 64)
DIGEST_C = "sha256:" + ("c" * 64)
DIGEST_D = "sha256:" + ("d" * 64)
DIGEST_E = "sha256:" + ("e" * 64)
DIGEST_F = "sha256:" + ("f" * 64)
DIGEST_1 = "sha256:" + ("1" * 64)
DIGEST_2 = "sha256:" + ("2" * 64)
DIGEST_3 = "sha256:" + ("3" * 64)
DIGEST_4 = "sha256:" + ("4" * 64)
DIGEST_5 = "sha256:" + ("5" * 64)
DIGEST_6 = "sha256:" + ("6" * 64)
DIGEST_7 = "sha256:" + ("7" * 64)
DIGEST_8 = "sha256:" + ("8" * 64)

PACKAGE_ROOT = (
    Path(__file__).resolve().parents[4]
    / "ipfs_datasets_py"
    / "logic"
    / "gui_optimizer"
)

EXCLUDED_IMPORT_SUBSTRINGS = (
    "semantic_index",
    "semantic_capsule",
    "proof_cache",
    "proof_corpus",
    "model_routing",
    "ui_ux_ir",
)

REQUIRED_CAPSULE_FIELDS = frozenset(
    {
        "action_side_effects",
        "layout_responsive_behavior",
        "keyboard_focus_behavior",
        "analysis_classification",
        "verification_status",
    }
)

REQUIRED_CONTEXT_PACK_FIELDS = frozenset(
    {
        "raw_source_paths",
        "style_token_paths",
        "affected_test_ids",
        "state_machine_ids",
        "invariant_failure_ids",
        "artifact_digests",
        "raw_source_tokens",
        "capsule_tokens",
        "screenshot_analysis_tokens",
        "replaced_source_tokens",
        "estimated_tokens",
        "compression_ratio",
        "token_budget",
    }
)

REQUIRED_VISUAL_RECEIPT_FIELDS = frozenset(
    {
        "structural_diff_percent",
        "expected_change_regions",
        "forbidden_change_regions",
        "max_unexplained_diff_percent",
        "manual_review_threshold_percent",
        "pixel_diff_percent",
    }
)


def _component_identity(**overrides: Any) -> UiComponentIdentity:
    base = {
        "application_id": "app:agent-supervisor",
        "qualified_name": "apps.agent-supervisor.ConsoleRoot",
        "component_kind": UiComponentKind.SCREEN,
        "package_namespace": "swissknife.web.js.apps",
        "screen_id": "screen:agent-supervisor",
    }
    base.update(overrides)
    return UiComponentIdentity(**base)


def _component_version(**overrides: Any) -> UiComponentVersion:
    base = {
        "stable_identity": _component_identity(),
        "structure_digest": DIGEST_A,
        "props_digest": DIGEST_B,
        "state_digest": DIGEST_C,
        "handlers_digest": DIGEST_D,
        "accessibility_digest": DIGEST_E,
        "styles_digest": DIGEST_F,
        "actions_digest": DIGEST_1,
        "localization_digest": DIGEST_2,
        "extractor_version": "1.0.0",
    }
    base.update(overrides)
    return UiComponentVersion(**base)


def _viewport() -> ViewportSpec:
    return ViewportSpec(width=1280, height=800, device_scale_factor=1)


def _sample_instances() -> dict[str, Any]:
    identity = _component_identity()
    version = _component_version()
    return {
        "GuiApplicationIdentity@1": GuiApplicationIdentity(
            application_id="app:agent-supervisor",
            package_namespace="swissknife.web.js.apps",
            display_name="Agent Supervisor",
            repository_root="swissknife",
        ),
        "GuiScreenIdentity@1": GuiScreenIdentity(
            application_id="app:agent-supervisor",
            screen_id="screen:agent-supervisor",
            route_id="route:agent-supervisor",
        ),
        "UiComponentIdentity@1": identity,
        "UiComponentVersion@1": version,
        "UiDependencyEdge@1": UiDependencyEdge(
            source_component_id="comp:root",
            target_component_id="comp:goal-form",
            relation=UiDependencyRelation.CONTAINS,
            extraction_method=ExtractionMethod.TYPESCRIPT_COMPILER_API,
            extractor_version="1.0.0",
            confidence=ExtractionConfidence.EXACT,
            source_span=SourceSpan(
                path="swissknife/web/js/apps/agent-supervisor.js",
                start_line=10,
                start_column=0,
                end_line=40,
            ),
        ),
        "UiStateDefinition@1": UiStateDefinition(
            state_id="state:ready",
            kind=UiStateKind.READY,
            screen_id="screen:agent-supervisor",
            label="Ready",
            is_initial=False,
            is_terminal=False,
        ),
        "UiEventDefinition@1": UiEventDefinition(
            event_id="event:submit",
            kind=UiEventKind.SUBMIT,
            name="submit-goal",
        ),
        "UiTransitionDefinition@1": UiTransitionDefinition(
            transition_id="transition:ready-to-loading",
            from_state_id="state:ready",
            to_state_id="state:loading",
            event_id="event:submit",
        ),
        "UiActionBinding@1": UiActionBinding(
            action_id="action:dispatch",
            method="agentSupervisor.dispatch",
            schema_id="schema:dispatch@1",
            requires_confirmation=True,
            confirmation_id="confirm:dispatch",
            is_destructive=False,
            component_id="comp:goal-form",
        ),
        "UiLayoutConstraint@1": UiLayoutConstraint(
            constraint_id="layout:no-overflow",
            kind=LayoutConstraintKind.NO_HORIZONTAL_OVERFLOW,
            expression="content.width <= viewport.width",
            component_id="comp:root",
        ),
        "UiAccessibilityContract@1": UiAccessibilityContract(
            contract_id="a11y:goal-form",
            requirement_kinds=(
                AccessibilityRequirementKind.ACCESSIBLE_NAME,
                AccessibilityRequirementKind.KEYBOARD_ACTIVATION,
            ),
            required_roles=("form", "button"),
            component_id="comp:goal-form",
        ),
        "UiSemanticCapsule@1": UiSemanticCapsule(
            capsule_id="capsule:console-root",
            stable_identity=identity,
            version_identity=version,
            application_id="app:agent-supervisor",
            screen_id="screen:agent-supervisor",
            purpose="Primary Agent Supervisor console surface",
            component_type="screen-root",
            analysis_classification=AnalysisClassification.EXACT,
            verification_status=VerificationStatus.UNVERIFIED,
            completeness_boundary=CompletenessBoundary.COMPLETE_WITHIN_BOUNDARY,
            prop_names=("goals", "tasks"),
            action_side_effects=("dispatch-goal", "invalidate-cache"),
            layout_responsive_behavior=(
                "stack-on-narrow",
                "preserve-primary-action",
            ),
            keyboard_focus_behavior=(
                "tab-order-form-then-submit",
                "escape-cancels-dialog",
            ),
            visible_state_ids=("state:ready", "state:loading"),
            confirmation_required=True,
            source_revision="deadbeef",
        ),
        "UiChangeSet@1": UiChangeSet(
            change_set_id="change:label-fix",
            change_kinds=(ChangeKind.COMPONENT_IMPLEMENTATION, ChangeKind.ACCESSIBILITY),
            file_paths=("swissknife/web/js/apps/agent-supervisor.js",),
            component_ids=("comp:goal-form",),
            summary="Add accessible name to goal form",
        ),
        "UiInvalidationPlan@1": UiInvalidationPlan(
            plan_id="invalidate:label-form",
            change_set_id="change:label-form",
            reasons=(InvalidationReason.COMPONENT_CHANGED,),
            affected_component_ids=("comp:goal-form",),
            affected_scenario_ids=("scenario:keyboard-only",),
            confidence=ExtractionConfidence.EXACT,
        ),
        "UiEvaluationScenario@1": UiEvaluationScenario(
            scenario_id="scenario:keyboard-only",
            name="Keyboard-only navigation",
            application_id="app:agent-supervisor",
            screen_id="screen:agent-supervisor",
            fixture_digest=DIGEST_3,
            viewport=_viewport(),
            tags=("keyboard", "a11y"),
        ),
        "UiBaseline@1": UiBaseline(
            baseline_id="baseline:agent-supervisor-v1",
            application_id="app:agent-supervisor",
            screen_id="screen:agent-supervisor",
            repository_revision="deadbeef",
            scenario_ids=("scenario:keyboard-only", "scenario:initial-load"),
            metric_digest=DIGEST_4,
            artifact_digests=(DIGEST_5,),
        ),
        "UiContextPack@1": UiContextPack(
            pack_id="pack:label-form",
            application_id="app:agent-supervisor",
            screen_id="screen:agent-supervisor",
            objective="Ensure goal form has an accessible name",
            token_budget=4000,
            estimated_tokens=1200,
            raw_source_paths=("swissknife/web/js/apps/agent-supervisor.js",),
            style_token_paths=("swissknife/web/css/tokens.css",),
            affected_test_ids=("test:goal-form-a11y",),
            state_machine_ids=("sm:agent-supervisor",),
            invariant_failure_ids=(),
            artifact_digests=(DIGEST_5,),
            capsule_ids=("capsule:console-root",),
            acceptance_criteria=("form has accessible name",),
            raw_source_tokens=800,
            capsule_tokens=200,
            screenshot_analysis_tokens=100,
            replaced_source_tokens=50,
            compression_ratio=0.42,
            analysis_classification=AnalysisClassification.CONSERVATIVE,
            verification_status=VerificationStatus.UNVERIFIED,
        ),
        "GuiImprovementProposal@1": GuiImprovementProposal(
            proposal_id="proposal:label-form",
            application_id="app:agent-supervisor",
            screen_id="screen:agent-supervisor",
            objective="Ensure goal form has an accessible name",
            intended_file_paths=("swissknife/web/js/apps/agent-supervisor.js",),
            intended_component_ids=("comp:goal-form",),
            acceptance_criteria=("form has accessible name",),
            route_kind=ProposalRouteKind.DETERMINISTIC_TRANSFORM,
            context_pack_id="pack:label-form",
        ),
        "VisualRegressionReceipt@1": VisualRegressionReceipt(
            receipt_id="receipt:visual-1",
            application_id="app:agent-supervisor",
            screen_id="screen:agent-supervisor",
            scenario_id="scenario:keyboard-only",
            repository_revision="deadbeef",
            component_version_ids=("version:console-root",),
            viewport=_viewport(),
            screenshot_digest=DIGEST_6,
            baseline_digest=DIGEST_7,
            decision=VisualDecision.PASS,
            evidence_level=EvidenceLevel.HEURISTIC,
            pixel_diff_percent=0.25,
            structural_diff_percent=0.1,
            expected_change_regions=("region:label",),
            forbidden_change_regions=("region:nav",),
            max_unexplained_diff_percent=1.0,
            manual_review_threshold_percent=2.0,
            analysis_classification=AnalysisClassification.HEURISTIC,
            verification_status=VerificationStatus.SIMULATED,
        ),
        "AccessibilityReceipt@1": AccessibilityReceipt(
            receipt_id="receipt:a11y-1",
            application_id="app:agent-supervisor",
            screen_id="screen:agent-supervisor",
            scenario_id="scenario:keyboard-only",
            repository_revision="deadbeef",
            automated_pass_count=12,
            violation_count=0,
            violation_ids=(),
            manual_check_ids=("manual:focus-order",),
            unsupported_criteria=("WCAG-1.3.5",),
            keyboard_result=ConstraintCheckStatus.SATISFIED,
            screen_reader_reviewed=False,
            evidence_level=EvidenceLevel.AUTOMATED,
        ),
        "InteractionReceipt@1": InteractionReceipt(
            receipt_id="receipt:interaction-1",
            application_id="app:agent-supervisor",
            screen_id="screen:agent-supervisor",
            scenario_id="scenario:keyboard-only",
            repository_revision="deadbeef",
            step_ids=("step:focus-input", "step:activate-submit"),
            focus_sequence=("goal-input", "submit-button"),
            event_ids=("event:focus", "event:keyboard_activation"),
            action_invocation_ids=("invoke:dispatch",),
            confirmation_id="confirm:dispatch",
        ),
        "UiConstraintReceipt@1": UiConstraintReceipt(
            receipt_id="receipt:constraint-1",
            application_id="app:agent-supervisor",
            screen_id="screen:agent-supervisor",
            repository_revision="deadbeef",
            check_ids=("check:every-event-has-outcome", "check:no-hidden-dispatch"),
            statuses=(
                ConstraintCheckStatus.SATISFIED,
                ConstraintCheckStatus.SATISFIED,
            ),
            solver_id="solver:finite-graph",
        ),
        "GuiImprovementReceipt@1": GuiImprovementReceipt(
            receipt_id="receipt:improvement-1",
            proposal_id="proposal:label-form",
            application_id="app:agent-supervisor",
            screen_id="screen:agent-supervisor",
            repository_revision="deadbeef",
            decision=ProposalDecision.ACCEPT,
            visual_receipt_ids=("receipt:visual-1",),
            accessibility_receipt_ids=("receipt:a11y-1",),
            interaction_receipt_ids=("receipt:interaction-1",),
            constraint_receipt_ids=("receipt:constraint-1",),
            invalidation_plan_id="invalidate:label-form",
            context_pack_id="pack:label-form",
            patch_digest=DIGEST_8,
            analysis_classification=AnalysisClassification.EXACT,
            verification_status=VerificationStatus.STRUCTURALLY_VALID,
        ),
    }


# ---------------------------------------------------------------------------
# Inventory / versioning
# ---------------------------------------------------------------------------


def test_required_model_inventory_is_complete_and_registered() -> None:
    inventory = required_model_inventory()
    assert inventory == REQUIRED_MODEL_INTERFACES
    assert len(inventory) == 23
    assert_required_models_registered()
    assert set(MODEL_TYPES) == set(REQUIRED_MODEL_INTERFACES)
    for interface in REQUIRED_MODEL_INTERFACES:
        model_cls = MODEL_TYPES[interface]
        assert model_cls.INTERFACE == interface
        assert model_cls.SCHEMA_VERSION == SCHEMA_VERSION_BY_INTERFACE[interface]
        assert model_cls.SCHEMA_VERSION.endswith("/v1")
        assert model_cls.SCHEMA_VERSION in REGISTERED_OPTIMIZER_SCHEMA_VERSIONS


def test_every_required_model_round_trips_and_is_versioned() -> None:
    samples = _sample_instances()
    assert set(samples) == set(REQUIRED_MODEL_INTERFACES)
    for interface, instance in samples.items():
        payload = instance.to_dict()
        assert payload["interface"] == interface
        assert payload["schema_version"] == SCHEMA_VERSION_BY_INTERFACE[interface]
        restored = type(instance).from_dict(payload)
        assert restored.to_dict() == payload
        assert decode_model(payload).to_dict() == payload


def test_round_trip_preserves_exact_wire_types() -> None:
    for instance in _sample_instances().values():
        payload = instance.to_dict()
        restored = type(instance).from_dict(payload).to_dict()
        for key, value in payload.items():
            assert type(restored[key]) is type(value), key
            if isinstance(value, list):
                assert all(
                    type(left) is type(right)
                    for left, right in zip(value, restored[key], strict=True)
                ), key
            if isinstance(value, dict):
                assert list(restored[key].keys()) == list(value.keys())


# ---------------------------------------------------------------------------
# Deterministic serialization
# ---------------------------------------------------------------------------


def test_canonical_serialization_is_deterministic_and_key_sorted() -> None:
    samples = _sample_instances()
    for instance in samples.values():
        first = instance.canonical_bytes()
        second = canonical_model_bytes(instance.to_dict())
        third = canonical_model_json(instance).encode("utf-8")
        assert first == second == third
        decoded = json.loads(first.decode("utf-8"))
        assert list(decoded.keys()) == sorted(decoded.keys())
        # Re-encode with the same profile must not drift.
        assert canonical_model_bytes(decoded) == first


def test_canonical_serialization_rejects_non_finite_numbers() -> None:
    payload = _sample_instances()["VisualRegressionReceipt@1"].to_dict()
    payload["pixel_diff_percent"] = float("nan")
    with pytest.raises(GuiOptimizerDecodeError, match="finite"):
        VisualRegressionReceipt.from_dict(payload)
    with pytest.raises(GuiOptimizerDecodeError, match="finite|non-finite"):
        canonical_model_bytes({"x": float("inf")})


def test_canonical_serialization_rejects_non_string_mapping_keys() -> None:
    with pytest.raises(GuiOptimizerDecodeError, match="keys must be strings"):
        canonical_model_bytes({1: "bad"})  # type: ignore[dict-item]


# ---------------------------------------------------------------------------
# Closed-schema rejection
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("interface", REQUIRED_MODEL_INTERFACES)
def test_unknown_fields_are_rejected(interface: str) -> None:
    instance = _sample_instances()[interface]
    payload = instance.to_dict()
    payload["unexpected_extension_bag"] = {"x": 1}
    with pytest.raises(GuiOptimizerDecodeError, match="unknown .* field"):
        type(instance).from_dict(payload)


@pytest.mark.parametrize("interface", REQUIRED_MODEL_INTERFACES)
def test_unsupported_schema_version_is_rejected(interface: str) -> None:
    instance = _sample_instances()[interface]
    payload = instance.to_dict()
    payload["schema_version"] = "not-a-supported-version/v9"
    with pytest.raises(
        GuiOptimizerDecodeError,
        match="unregistered optimizer schema version|unsupported schema_version",
    ):
        type(instance).from_dict(payload)


@pytest.mark.parametrize("interface", REQUIRED_MODEL_INTERFACES)
def test_missing_interface_on_wire_is_rejected(interface: str) -> None:
    instance = _sample_instances()[interface]
    payload = instance.to_dict()
    del payload["interface"]
    with pytest.raises(GuiOptimizerDecodeError, match="interface is required"):
        type(instance).from_dict(payload)


@pytest.mark.parametrize("interface", REQUIRED_MODEL_INTERFACES)
def test_missing_schema_version_on_wire_is_rejected(interface: str) -> None:
    instance = _sample_instances()[interface]
    payload = instance.to_dict()
    del payload["schema_version"]
    with pytest.raises(GuiOptimizerDecodeError, match="schema_version is required"):
        type(instance).from_dict(payload)


@pytest.mark.parametrize("interface", REQUIRED_MODEL_INTERFACES)
def test_wrong_interface_identity_is_rejected(interface: str) -> None:
    instance = _sample_instances()[interface]
    payload = instance.to_dict()
    payload["interface"] = "NotARealInterface@9"
    with pytest.raises(GuiOptimizerDecodeError, match="unsupported interface"):
        type(instance).from_dict(payload)


def test_invalid_enum_values_are_rejected() -> None:
    with pytest.raises(GuiOptimizerDecodeError, match="component_kind must be one of"):
        UiComponentIdentity(
            application_id="app:x",
            qualified_name="x.Y",
            component_kind="not-a-kind",
            package_namespace="ns",
        )
    with pytest.raises(
        GuiOptimizerDecodeError, match="analysis_classification must be one of"
    ):
        payload = _sample_instances()["UiSemanticCapsule@1"].to_dict()
        payload["analysis_classification"] = "proven"
        UiSemanticCapsule.from_dict(payload)
    with pytest.raises(
        GuiOptimizerDecodeError, match="verification_status must be one of"
    ):
        payload = _sample_instances()["UiSemanticCapsule@1"].to_dict()
        payload["verification_status"] = "trusted"
        UiSemanticCapsule.from_dict(payload)
    with pytest.raises(GuiOptimizerDecodeError, match="relation must be one of"):
        payload = _sample_instances()["UiDependencyEdge@1"].to_dict()
        payload["relation"] = "depends_on_magic"
        UiDependencyEdge.from_dict(payload)


def test_malformed_paths_and_digests_are_rejected() -> None:
    with pytest.raises(GuiOptimizerDecodeError, match="repository-relative path"):
        SourceSpan(path="../secret", start_line=1)
    with pytest.raises(GuiOptimizerDecodeError, match="repository-relative path"):
        UiChangeSet(
            change_set_id="change:x",
            change_kinds=(ChangeKind.OTHER,),
            file_paths=("/absolute/path.js",),
        )
    with pytest.raises(GuiOptimizerDecodeError, match="sha256"):
        _component_version(structure_digest="not-a-digest")


def test_unregistered_optimizer_schema_version_is_rejected() -> None:
    with pytest.raises(
        GuiOptimizerDecodeError, match="unregistered optimizer schema version"
    ):
        _component_version(optimizer_schema_version="optimizer/not-registered/v99")


# ---------------------------------------------------------------------------
# Wrong JSON container types (before coercion)
# ---------------------------------------------------------------------------


ARRAY_FIELD_CASES: list[tuple[str, str]] = [
    ("UiTransitionDefinition@1", "effect_ids"),
    ("UiAccessibilityContract@1", "requirement_kinds"),
    ("UiSemanticCapsule@1", "prop_names"),
    ("UiSemanticCapsule@1", "action_side_effects"),
    ("UiSemanticCapsule@1", "layout_responsive_behavior"),
    ("UiSemanticCapsule@1", "keyboard_focus_behavior"),
    ("UiChangeSet@1", "file_paths"),
    ("UiInvalidationPlan@1", "reasons"),
    ("UiEvaluationScenario@1", "tags"),
    ("UiBaseline@1", "scenario_ids"),
    ("UiContextPack@1", "raw_source_paths"),
    ("UiContextPack@1", "style_token_paths"),
    ("UiContextPack@1", "affected_test_ids"),
    ("UiContextPack@1", "artifact_digests"),
    ("GuiImprovementProposal@1", "intended_file_paths"),
    ("VisualRegressionReceipt@1", "component_version_ids"),
    ("VisualRegressionReceipt@1", "expected_change_regions"),
    ("VisualRegressionReceipt@1", "forbidden_change_regions"),
    ("AccessibilityReceipt@1", "violation_ids"),
    ("InteractionReceipt@1", "step_ids"),
    ("UiConstraintReceipt@1", "check_ids"),
    ("UiConstraintReceipt@1", "statuses"),
    ("GuiImprovementReceipt@1", "visual_receipt_ids"),
]


MAPPING_FIELD_CASES: list[tuple[str, str]] = [
    ("UiComponentVersion@1", "stable_identity"),
    ("UiDependencyEdge@1", "source_span"),
    ("UiSemanticCapsule@1", "stable_identity"),
    ("UiSemanticCapsule@1", "version_identity"),
    ("UiEvaluationScenario@1", "viewport"),
    ("VisualRegressionReceipt@1", "viewport"),
]


@pytest.mark.parametrize(("interface", "field"), ARRAY_FIELD_CASES)
def test_array_fields_reject_strings_and_mappings(interface: str, field: str) -> None:
    instance = _sample_instances()[interface]
    payload = instance.to_dict()
    payload[field] = "not-an-array"
    with pytest.raises(GuiOptimizerDecodeError, match="must be a sequence"):
        type(instance).from_dict(payload)
    payload[field] = {"not": "an-array"}
    with pytest.raises(GuiOptimizerDecodeError, match="must be a sequence"):
        type(instance).from_dict(payload)


@pytest.mark.parametrize(("interface", "field"), MAPPING_FIELD_CASES)
def test_mapping_fields_reject_arrays_and_strings(interface: str, field: str) -> None:
    instance = _sample_instances()[interface]
    payload = instance.to_dict()
    payload[field] = ["not", "a", "mapping"]
    with pytest.raises(GuiOptimizerDecodeError, match="must be a mapping"):
        type(instance).from_dict(payload)
    payload[field] = "not-a-mapping"
    with pytest.raises(GuiOptimizerDecodeError, match="must be a mapping"):
        type(instance).from_dict(payload)


@pytest.mark.parametrize("interface", REQUIRED_MODEL_INTERFACES)
def test_top_level_payload_rejects_array_container(interface: str) -> None:
    instance = _sample_instances()[interface]
    with pytest.raises(GuiOptimizerDecodeError, match="must be a mapping"):
        type(instance).from_dict(["not", "a", "mapping"])  # type: ignore[arg-type]
    with pytest.raises(GuiOptimizerDecodeError, match="must be a mapping"):
        type(instance).from_dict("not-a-mapping")  # type: ignore[arg-type]


def test_string_array_field_does_not_coerce_characters() -> None:
    """Regression: tuple(\"ab\") must never become ('a', 'b') identifiers."""

    payload = _sample_instances()["UiTransitionDefinition@1"].to_dict()
    payload["effect_ids"] = "ab"
    with pytest.raises(GuiOptimizerDecodeError, match="must be a sequence"):
        UiTransitionDefinition.from_dict(payload)


# ---------------------------------------------------------------------------
# Analysis classification vs verification status
# ---------------------------------------------------------------------------


def test_analysis_classification_is_independent_of_verification_status() -> None:
    # Exact analysis may still be unverified / simulated.
    capsule = _sample_instances()["UiSemanticCapsule@1"]
    exact_unverified = UiSemanticCapsule.from_dict(
        {
            **capsule.to_dict(),
            "analysis_classification": AnalysisClassification.EXACT.value,
            "verification_status": VerificationStatus.UNVERIFIED.value,
        }
    )
    heuristic_verified_like = UiSemanticCapsule.from_dict(
        {
            **capsule.to_dict(),
            "analysis_classification": AnalysisClassification.HEURISTIC.value,
            "verification_status": VerificationStatus.INTEGRITY_VALID.value,
        }
    )
    assert exact_unverified.analysis_classification is AnalysisClassification.EXACT
    assert exact_unverified.verification_status is VerificationStatus.UNVERIFIED
    assert (
        heuristic_verified_like.analysis_classification
        is AnalysisClassification.HEURISTIC
    )
    assert (
        heuristic_verified_like.verification_status
        is VerificationStatus.INTEGRITY_VALID
    )

    visual = _sample_instances()["VisualRegressionReceipt@1"]
    assert visual.analysis_classification is AnalysisClassification.HEURISTIC
    assert visual.verification_status is VerificationStatus.SIMULATED
    # Content identity / digests do not promote heuristic visual claims.
    assert visual.evidence_level is EvidenceLevel.HEURISTIC
    assert visual.decision is VisualDecision.PASS


def test_closed_analysis_and_verification_vocabularies() -> None:
    assert {item.value for item in AnalysisClassification} == {
        "exact",
        "conservative",
        "heuristic",
        "opaque",
    }
    assert {item.value for item in VerificationStatus} == {
        "verified",
        "structurally_valid",
        "integrity_valid",
        "unverified",
        "stale",
        "invalid",
        "simulated",
    }
    # The two dimensions share no promotion path: values are distinct enums.
    assert AnalysisClassification is not VerificationStatus


# ---------------------------------------------------------------------------
# Finite bounds / structural guards / cross-field consistency
# ---------------------------------------------------------------------------


def test_action_binding_requires_confirmation_id_when_flagged() -> None:
    with pytest.raises(GuiOptimizerDecodeError, match="confirmation_id is required"):
        UiActionBinding(
            action_id="action:x",
            method="m",
            schema_id="schema:x",
            requires_confirmation=True,
        )


def test_accepted_improvement_receipt_requires_all_four_receipt_classes() -> None:
    with pytest.raises(GuiOptimizerDecodeError, match="all four receipt classes"):
        GuiImprovementReceipt(
            receipt_id="receipt:x",
            proposal_id="proposal:x",
            application_id="app:x",
            screen_id="screen:x",
            repository_revision="rev",
            decision=ProposalDecision.ACCEPT,
            visual_receipt_ids=("v",),
            accessibility_receipt_ids=(),
            interaction_receipt_ids=("i",),
            constraint_receipt_ids=("c",),
        )


def test_rejected_improvement_receipt_requires_reasons() -> None:
    with pytest.raises(GuiOptimizerDecodeError, match="rejection_reasons"):
        GuiImprovementReceipt(
            receipt_id="receipt:x",
            proposal_id="proposal:x",
            application_id="app:x",
            screen_id="screen:x",
            repository_revision="rev",
            decision=ProposalDecision.REJECT,
            visual_receipt_ids=(),
            accessibility_receipt_ids=(),
            interaction_receipt_ids=(),
            constraint_receipt_ids=(),
        )


def test_constraint_receipt_statuses_align_with_checks() -> None:
    with pytest.raises(GuiOptimizerDecodeError, match="1:1"):
        UiConstraintReceipt(
            receipt_id="receipt:x",
            application_id="app:x",
            screen_id="screen:x",
            repository_revision="rev",
            check_ids=("check:a", "check:b"),
            statuses=(ConstraintCheckStatus.SATISFIED,),
        )


def test_accessibility_receipt_violation_count_matches_ids() -> None:
    with pytest.raises(GuiOptimizerDecodeError, match="violation_count"):
        AccessibilityReceipt(
            receipt_id="receipt:x",
            application_id="app:x",
            screen_id="screen:x",
            scenario_id="scenario:x",
            repository_revision="rev",
            automated_pass_count=0,
            violation_count=2,
            violation_ids=("v1",),
            manual_check_ids=(),
            unsupported_criteria=(),
            keyboard_result=ConstraintCheckStatus.SATISFIED,
            screen_reader_reviewed=False,
            evidence_level=EvidenceLevel.AUTOMATED,
        )


def test_visual_receipt_rejects_region_overlap_and_threshold_contradictions() -> None:
    with pytest.raises(GuiOptimizerDecodeError, match="must not overlap"):
        VisualRegressionReceipt(
            receipt_id="receipt:x",
            application_id="app:x",
            screen_id="screen:x",
            scenario_id="scenario:x",
            repository_revision="rev",
            component_version_ids=("v1",),
            viewport=_viewport(),
            screenshot_digest=DIGEST_6,
            baseline_digest=DIGEST_7,
            decision=VisualDecision.PASS,
            evidence_level=EvidenceLevel.HEURISTIC,
            expected_change_regions=("region:a",),
            forbidden_change_regions=("region:a",),
        )
    with pytest.raises(GuiOptimizerDecodeError, match="max_unexplained_diff_percent"):
        VisualRegressionReceipt(
            receipt_id="receipt:x",
            application_id="app:x",
            screen_id="screen:x",
            scenario_id="scenario:x",
            repository_revision="rev",
            component_version_ids=("v1",),
            viewport=_viewport(),
            screenshot_digest=DIGEST_6,
            baseline_digest=DIGEST_7,
            decision=VisualDecision.PASS,
            evidence_level=EvidenceLevel.HEURISTIC,
            pixel_diff_percent=5.0,
            max_unexplained_diff_percent=1.0,
        )


def test_context_pack_token_accounting_consistency() -> None:
    with pytest.raises(GuiOptimizerDecodeError, match="token-accounting"):
        UiContextPack(
            pack_id="pack:x",
            application_id="app:x",
            screen_id="screen:x",
            objective="obj",
            token_budget=100,
            estimated_tokens=10,
            raw_source_paths=("a.js",),
            raw_source_tokens=20,
            capsule_tokens=5,
        )


# ---------------------------------------------------------------------------
# Required field inventory for capsule / context / visual receipt
# ---------------------------------------------------------------------------


def test_required_capsule_context_visual_field_inventory() -> None:
    capsule = _sample_instances()["UiSemanticCapsule@1"].to_dict()
    assert REQUIRED_CAPSULE_FIELDS.issubset(capsule)
    assert capsule["action_side_effects"]
    assert capsule["layout_responsive_behavior"]
    assert capsule["keyboard_focus_behavior"]

    pack = _sample_instances()["UiContextPack@1"].to_dict()
    assert REQUIRED_CONTEXT_PACK_FIELDS.issubset(pack)
    assert pack["raw_source_paths"]
    assert pack["style_token_paths"]
    assert pack["affected_test_ids"]

    visual = _sample_instances()["VisualRegressionReceipt@1"].to_dict()
    assert REQUIRED_VISUAL_RECEIPT_FIELDS.issubset(visual)
    assert "structural_diff_percent" in visual
    assert visual["expected_change_regions"]
    assert visual["forbidden_change_regions"]


# ---------------------------------------------------------------------------
# Import boundary: no excluded prior subsystems / undeclared artifacts
# ---------------------------------------------------------------------------


def test_package_has_no_excluded_subsystem_imports() -> None:
    assert PACKAGE_ROOT.is_dir()
    for path in sorted(PACKAGE_ROOT.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                modules = [node.module or ""]
            else:
                continue
            for module in modules:
                lowered = module.replace(".", "_").lower()
                for forbidden in EXCLUDED_IMPORT_SUBSTRINGS:
                    assert forbidden not in lowered, (
                        f"{path.name} imports excluded subsystem via {module!r}"
                    )


def test_package_import_is_standalone_stdlib_only_for_schema() -> None:
    schema_mod = importlib.import_module(
        "ipfs_datasets_py.logic.gui_optimizer.schema"
    )
    # schema.py must stay free of third-party and excluded packages.
    source = inspect.getsource(schema_mod)
    for forbidden in EXCLUDED_IMPORT_SUBSTRINGS:
        assert forbidden not in source
    models_mod = importlib.import_module(
        "ipfs_datasets_py.logic.gui_optimizer.models"
    )
    models_source = inspect.getsource(models_mod)
    for forbidden in EXCLUDED_IMPORT_SUBSTRINGS:
        assert forbidden not in models_source


def test_no_undeclared_package_artifacts() -> None:
    """Package tree may only contain the declared VGO-001 modules."""

    allowed = {"__init__.py", "models.py", "schema.py", "__pycache__"}
    present = {path.name for path in PACKAGE_ROOT.iterdir()}
    unexpected = present - allowed
    assert not unexpected, f"undeclared package artifacts: {sorted(unexpected)}"
    # No smoke/fixture leftovers under the package.
    for path in PACKAGE_ROOT.rglob("*"):
        if path.is_dir():
            continue
        if path.name.endswith(".pyc"):
            continue
        assert path.name in {"__init__.py", "models.py", "schema.py"}
        assert "smoke" not in path.name.lower()
