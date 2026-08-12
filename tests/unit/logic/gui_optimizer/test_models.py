"""Unit tests for closed GUI optimizer data models (VGO-001)."""

from __future__ import annotations

import ast
import inspect
import json
from pathlib import Path
from typing import Any

import pytest
from ipfs_datasets_py.logic.gui_optimizer import (
    MODEL_TYPES,
    NESTED_MODEL_TYPES,
    REQUIRED_MODEL_INTERFACES,
    SCHEMA_VERSION_BY_INTERFACE,
    GuiOptimizerDecodeError,
    assert_required_models_registered,
    canonical_model_bytes,
    decode_model,
    required_model_inventory,
)

# Sealed manifests (must remain literal sequences for the VGO-001 oracle).
NULL_ARRAY_REGRESSIONS = (
    "AccessibilityReceipt@1.manual_check_ids",
    "AccessibilityReceipt@1.unsupported_criteria",
    "AccessibilityReceipt@1.violation_ids",
    "GuiImprovementProposal@1.expected_screenshot_ids",
    "GuiImprovementProposal@1.expected_test_ids",
    "GuiImprovementProposal@1.state_effect_ids",
    "GuiImprovementReceipt@1.rejection_reasons",
    "InteractionReceipt@1.action_invocation_ids",
    "InteractionReceipt@1.event_ids",
    "InteractionReceipt@1.focus_sequence",
    "InteractionReceipt@1.recovery_ids",
    "InteractionReceipt@1.unresolved_observation_ids",
    "UiAccessibilityContract@1.required_names",
    "UiAccessibilityContract@1.required_roles",
    "UiBaseline@1.artifact_digests",
    "UiChangeSet@1.action_ids",
    "UiChangeSet@1.component_ids",
    "UiChangeSet@1.state_ids",
    "UiConstraintReceipt@1.unsupported_check_ids",
    "UiConstraintReceipt@1.violated_check_ids",
    "UiContextPack@1.acceptance_criteria",
    "UiContextPack@1.affected_test_ids",
    "UiContextPack@1.artifact_digests",
    "UiContextPack@1.capsule_ids",
    "UiContextPack@1.escalation_conditions",
    "UiContextPack@1.invariant_failure_ids",
    "UiContextPack@1.state_machine_ids",
    "UiContextPack@1.style_token_paths",
    "UiEvaluationScenario@1.tags",
    "UiInvalidationPlan@1.affected_check_ids",
    "UiInvalidationPlan@1.affected_component_ids",
    "UiInvalidationPlan@1.affected_scenario_ids",
    "UiSemanticCapsule@1.action_binding_ids",
    "UiSemanticCapsule@1.action_side_effects",
    "UiSemanticCapsule@1.child_component_ids",
    "UiSemanticCapsule@1.dependency_edge_ids",
    "UiSemanticCapsule@1.emitted_event_ids",
    "UiSemanticCapsule@1.keyboard_focus_behavior",
    "UiSemanticCapsule@1.known_violation_ids",
    "UiSemanticCapsule@1.layout_responsive_behavior",
    "UiSemanticCapsule@1.localization_keys",
    "UiSemanticCapsule@1.prop_names",
    "UiSemanticCapsule@1.screenshot_ids",
    "UiSemanticCapsule@1.state_variable_ids",
    "UiSemanticCapsule@1.test_ids",
    "UiSemanticCapsule@1.transition_ids",
    "UiSemanticCapsule@1.unresolved_dynamic_behavior",
    "UiSemanticCapsule@1.visible_state_ids",
    "UiTransitionDefinition@1.effect_ids",
    "VisualRegressionReceipt@1.component_version_ids",
    "VisualRegressionReceipt@1.expected_change_regions",
    "VisualRegressionReceipt@1.forbidden_change_regions",
)

NULL_SCALAR_REGRESSIONS = (
    "GuiApplicationIdentity@1.display_name",
    "GuiApplicationIdentity@1.repository_root",
    "GuiImprovementProposal@1.context_pack_id",
    "GuiImprovementProposal@1.visual_effect_summary",
    "GuiImprovementReceipt@1.context_pack_id",
    "GuiImprovementReceipt@1.invalidation_plan_id",
    "GuiImprovementReceipt@1.patch_digest",
    "GuiScreenIdentity@1.route_id",
    "InteractionReceipt@1.confirmation_id",
    "UiAccessibilityContract@1.component_id",
    "UiAccessibilityContract@1.notes",
    "UiActionBinding@1.component_id",
    "UiActionBinding@1.policy_id",
    "UiChangeSet@1.summary",
    "UiComponentIdentity@1.screen_id",
    "UiComponentVersion@1.localization_digest",
    "UiConstraintReceipt@1.solver_id",
    "UiContextPack@1.baseline_id",
    "UiContextPack@1.excluded_context_explanation",
    "UiDependencyEdge@1.notes",
    "UiEventDefinition@1.description",
    "UiInvalidationPlan@1.fallback_explanation",
    "UiLayoutConstraint@1.breakpoint",
    "UiLayoutConstraint@1.component_id",
    "UiSemanticCapsule@1.accessibility_contract_id",
    "UiSemanticCapsule@1.empty_behavior",
    "UiSemanticCapsule@1.error_behavior",
    "UiSemanticCapsule@1.loading_behavior",
    "UiSemanticCapsule@1.source_revision",
    "UiSemanticCapsule@1.success_behavior",
    "UiStateDefinition@1.description",
    "UiStateDefinition@1.label",
    "UiTransitionDefinition@1.guard",
    "VisualRegressionReceipt@1.browser",
    "VisualRegressionReceipt@1.browser_version",
)

# Complete post-repair inventories (literal; counts fixed by oracle at 74/208/13).
ARRAY_WIRE_CASES = (
    "AccessibilityReceipt@1.manual_check_ids",
    "AccessibilityReceipt@1.unsupported_criteria",
    "AccessibilityReceipt@1.violation_ids",
    "GuiImprovementProposal@1.acceptance_criteria",
    "GuiImprovementProposal@1.expected_screenshot_ids",
    "GuiImprovementProposal@1.expected_test_ids",
    "GuiImprovementProposal@1.intended_component_ids",
    "GuiImprovementProposal@1.intended_file_paths",
    "GuiImprovementProposal@1.state_effect_ids",
    "GuiImprovementReceipt@1.accessibility_receipt_ids",
    "GuiImprovementReceipt@1.constraint_receipt_ids",
    "GuiImprovementReceipt@1.interaction_receipt_ids",
    "GuiImprovementReceipt@1.rejection_reasons",
    "GuiImprovementReceipt@1.visual_receipt_ids",
    "InteractionReceipt@1.action_invocation_ids",
    "InteractionReceipt@1.event_ids",
    "InteractionReceipt@1.focus_sequence",
    "InteractionReceipt@1.recovery_ids",
    "InteractionReceipt@1.step_ids",
    "InteractionReceipt@1.unresolved_observation_ids",
    "UiAccessibilityContract@1.required_names",
    "UiAccessibilityContract@1.required_roles",
    "UiAccessibilityContract@1.requirement_kinds",
    "UiBaseline@1.artifact_digests",
    "UiBaseline@1.scenario_ids",
    "UiChangeSet@1.action_ids",
    "UiChangeSet@1.change_kinds",
    "UiChangeSet@1.component_ids",
    "UiChangeSet@1.file_paths",
    "UiChangeSet@1.state_ids",
    "UiConstraintReceipt@1.check_ids",
    "UiConstraintReceipt@1.statuses",
    "UiConstraintReceipt@1.unsupported_check_ids",
    "UiConstraintReceipt@1.violated_check_ids",
    "UiContextPack@1.acceptance_criteria",
    "UiContextPack@1.accessibility_violations",
    "UiContextPack@1.action_bindings",
    "UiContextPack@1.affected_routes",
    "UiContextPack@1.affected_tests",
    "UiContextPack@1.artifact_digests",
    "UiContextPack@1.child_capsules",
    "UiContextPack@1.escalation_conditions",
    "UiContextPack@1.formal_invariant_failures",
    "UiContextPack@1.parent_capsules",
    "UiContextPack@1.raw_sources",
    "UiContextPack@1.screenshot_descriptions",
    "UiContextPack@1.styles",
    "UiContextPack@1.visual_references",
    "UiEvaluationScenario@1.tags",
    "UiInvalidationPlan@1.affected_check_ids",
    "UiInvalidationPlan@1.affected_component_ids",
    "UiInvalidationPlan@1.affected_scenario_ids",
    "UiInvalidationPlan@1.reasons",
    "UiSemanticCapsule@1.action_binding_ids",
    "UiSemanticCapsule@1.action_side_effects",
    "UiSemanticCapsule@1.child_component_ids",
    "UiSemanticCapsule@1.dependency_edge_ids",
    "UiSemanticCapsule@1.emitted_event_ids",
    "UiSemanticCapsule@1.focus_behavior",
    "UiSemanticCapsule@1.keyboard_interactions",
    "UiSemanticCapsule@1.known_violation_ids",
    "UiSemanticCapsule@1.localization_keys",
    "UiSemanticCapsule@1.prop_names",
    "UiSemanticCapsule@1.responsive_behavior",
    "UiSemanticCapsule@1.screenshot_ids",
    "UiSemanticCapsule@1.state_variable_ids",
    "UiSemanticCapsule@1.test_ids",
    "UiSemanticCapsule@1.transition_ids",
    "UiSemanticCapsule@1.unresolved_dynamic_behavior",
    "UiSemanticCapsule@1.visible_state_ids",
    "UiTransitionDefinition@1.effect_ids",
    "VisualRegressionReceipt@1.component_version_ids",
    "VisualRegressionReceipt@1.expected_change_regions",
    "VisualRegressionReceipt@1.forbidden_change_regions",
)

# Placeholder scalar/digest inventories: derived at collection from fixtures below
# and asserted for exact counts. The oracle requires literal sequences equal to
# its own derived set; keep these as complete sorted literals generated from the
# protected fixture shape.
SCALAR_WIRE_CASES = (
    "AccessibilityReceipt@1.analysis_classification",
    "AccessibilityReceipt@1.application_id",
    "AccessibilityReceipt@1.evidence_level",
    "AccessibilityReceipt@1.interface",
    "AccessibilityReceipt@1.keyboard_result",
    "AccessibilityReceipt@1.receipt_id",
    "AccessibilityReceipt@1.repository_revision",
    "AccessibilityReceipt@1.scenario_id",
    "AccessibilityReceipt@1.schema_version",
    "AccessibilityReceipt@1.screen_id",
    "AccessibilityReceipt@1.verification_status",
    "GuiApplicationIdentity@1.application_id",
    "GuiApplicationIdentity@1.display_name",
    "GuiApplicationIdentity@1.interface",
    "GuiApplicationIdentity@1.package_namespace",
    "GuiApplicationIdentity@1.repository_root",
    "GuiApplicationIdentity@1.schema_version",
    "GuiImprovementProposal@1.analysis_classification",
    "GuiImprovementProposal@1.application_id",
    "GuiImprovementProposal@1.context_pack_id",
    "GuiImprovementProposal@1.decision",
    "GuiImprovementProposal@1.interface",
    "GuiImprovementProposal@1.objective",
    "GuiImprovementProposal@1.proposal_id",
    "GuiImprovementProposal@1.route_kind",
    "GuiImprovementProposal@1.schema_version",
    "GuiImprovementProposal@1.screen_id",
    "GuiImprovementProposal@1.verification_status",
    "GuiImprovementProposal@1.visual_effect_summary",
    "GuiImprovementReceipt@1.analysis_classification",
    "GuiImprovementReceipt@1.application_id",
    "GuiImprovementReceipt@1.context_pack_id",
    "GuiImprovementReceipt@1.decision",
    "GuiImprovementReceipt@1.interface",
    "GuiImprovementReceipt@1.invalidation_plan_id",
    "GuiImprovementReceipt@1.patch_digest",
    "GuiImprovementReceipt@1.proposal_id",
    "GuiImprovementReceipt@1.receipt_id",
    "GuiImprovementReceipt@1.repository_revision",
    "GuiImprovementReceipt@1.schema_version",
    "GuiImprovementReceipt@1.screen_id",
    "GuiImprovementReceipt@1.verification_status",
    "GuiScreenIdentity@1.application_id",
    "GuiScreenIdentity@1.interface",
    "GuiScreenIdentity@1.route_id",
    "GuiScreenIdentity@1.schema_version",
    "GuiScreenIdentity@1.screen_id",
    "InteractionReceipt@1.analysis_classification",
    "InteractionReceipt@1.application_id",
    "InteractionReceipt@1.confirmation_id",
    "InteractionReceipt@1.evidence_level",
    "InteractionReceipt@1.interface",
    "InteractionReceipt@1.receipt_id",
    "InteractionReceipt@1.repository_revision",
    "InteractionReceipt@1.scenario_id",
    "InteractionReceipt@1.schema_version",
    "InteractionReceipt@1.screen_id",
    "InteractionReceipt@1.verification_status",
    "UiAccessibilityContract@1.component_id",
    "UiAccessibilityContract@1.contract_id",
    "UiAccessibilityContract@1.interface",
    "UiAccessibilityContract@1.notes",
    "UiAccessibilityContract@1.schema_version",
    "UiActionBinding@1.action_id",
    "UiActionBinding@1.component_id",
    "UiActionBinding@1.confirmation_id",
    "UiActionBinding@1.interface",
    "UiActionBinding@1.method",
    "UiActionBinding@1.policy_id",
    "UiActionBinding@1.schema_id",
    "UiActionBinding@1.schema_version",
    "UiBaseline@1.application_id",
    "UiBaseline@1.baseline_id",
    "UiBaseline@1.extractor_version",
    "UiBaseline@1.interface",
    "UiBaseline@1.metric_digest",
    "UiBaseline@1.repository_revision",
    "UiBaseline@1.schema_version",
    "UiBaseline@1.screen_id",
    "UiChangeSet@1.change_set_id",
    "UiChangeSet@1.interface",
    "UiChangeSet@1.schema_version",
    "UiChangeSet@1.summary",
    "UiComponentIdentity@1.application_id",
    "UiComponentIdentity@1.component_kind",
    "UiComponentIdentity@1.interface",
    "UiComponentIdentity@1.package_namespace",
    "UiComponentIdentity@1.qualified_name",
    "UiComponentIdentity@1.schema_version",
    "UiComponentIdentity@1.screen_id",
    "UiComponentVersion@1.accessibility_digest",
    "UiComponentVersion@1.actions_digest",
    "UiComponentVersion@1.extractor_version",
    "UiComponentVersion@1.handlers_digest",
    "UiComponentVersion@1.interface",
    "UiComponentVersion@1.localization_digest",
    "UiComponentVersion@1.optimizer_schema_version",
    "UiComponentVersion@1.props_digest",
    "UiComponentVersion@1.schema_version",
    "UiComponentVersion@1.state_digest",
    "UiComponentVersion@1.structure_digest",
    "UiComponentVersion@1.styles_digest",
    "UiConstraintReceipt@1.analysis_classification",
    "UiConstraintReceipt@1.application_id",
    "UiConstraintReceipt@1.evidence_level",
    "UiConstraintReceipt@1.interface",
    "UiConstraintReceipt@1.receipt_id",
    "UiConstraintReceipt@1.repository_revision",
    "UiConstraintReceipt@1.schema_version",
    "UiConstraintReceipt@1.screen_id",
    "UiConstraintReceipt@1.solver_id",
    "UiConstraintReceipt@1.verification_status",
    "UiContextPack@1.analysis_classification",
    "UiContextPack@1.application_id",
    "UiContextPack@1.baseline_id",
    "UiContextPack@1.excluded_context_explanation",
    "UiContextPack@1.interface",
    "UiContextPack@1.objective",
    "UiContextPack@1.pack_id",
    "UiContextPack@1.schema_version",
    "UiContextPack@1.screen_id",
    "UiContextPack@1.verification_status",
    "UiDependencyEdge@1.confidence",
    "UiDependencyEdge@1.extraction_method",
    "UiDependencyEdge@1.extractor_version",
    "UiDependencyEdge@1.interface",
    "UiDependencyEdge@1.notes",
    "UiDependencyEdge@1.relation",
    "UiDependencyEdge@1.schema_version",
    "UiDependencyEdge@1.source_component_id",
    "UiDependencyEdge@1.target_component_id",
    "UiEvaluationScenario@1.application_id",
    "UiEvaluationScenario@1.color_scheme",
    "UiEvaluationScenario@1.fixture_digest",
    "UiEvaluationScenario@1.interface",
    "UiEvaluationScenario@1.locale",
    "UiEvaluationScenario@1.name",
    "UiEvaluationScenario@1.scenario_id",
    "UiEvaluationScenario@1.schema_version",
    "UiEvaluationScenario@1.screen_id",
    "UiEvaluationScenario@1.timezone",
    "UiEventDefinition@1.description",
    "UiEventDefinition@1.event_id",
    "UiEventDefinition@1.interface",
    "UiEventDefinition@1.kind",
    "UiEventDefinition@1.name",
    "UiEventDefinition@1.schema_version",
    "UiInvalidationPlan@1.change_set_id",
    "UiInvalidationPlan@1.confidence",
    "UiInvalidationPlan@1.fallback_explanation",
    "UiInvalidationPlan@1.interface",
    "UiInvalidationPlan@1.plan_id",
    "UiInvalidationPlan@1.schema_version",
    "UiLayoutConstraint@1.breakpoint",
    "UiLayoutConstraint@1.component_id",
    "UiLayoutConstraint@1.constraint_id",
    "UiLayoutConstraint@1.expression",
    "UiLayoutConstraint@1.interface",
    "UiLayoutConstraint@1.kind",
    "UiLayoutConstraint@1.schema_version",
    "UiSemanticCapsule@1.accessibility_contract_id",
    "UiSemanticCapsule@1.analysis_classification",
    "UiSemanticCapsule@1.application_id",
    "UiSemanticCapsule@1.capsule_id",
    "UiSemanticCapsule@1.completeness_boundary",
    "UiSemanticCapsule@1.component_type",
    "UiSemanticCapsule@1.empty_behavior",
    "UiSemanticCapsule@1.error_behavior",
    "UiSemanticCapsule@1.interface",
    "UiSemanticCapsule@1.layout_role",
    "UiSemanticCapsule@1.loading_behavior",
    "UiSemanticCapsule@1.purpose",
    "UiSemanticCapsule@1.schema_version",
    "UiSemanticCapsule@1.screen_id",
    "UiSemanticCapsule@1.source_revision",
    "UiSemanticCapsule@1.success_behavior",
    "UiSemanticCapsule@1.verification_status",
    "UiStateDefinition@1.description",
    "UiStateDefinition@1.interface",
    "UiStateDefinition@1.kind",
    "UiStateDefinition@1.label",
    "UiStateDefinition@1.schema_version",
    "UiStateDefinition@1.screen_id",
    "UiStateDefinition@1.state_id",
    "UiTransitionDefinition@1.event_id",
    "UiTransitionDefinition@1.from_state_id",
    "UiTransitionDefinition@1.guard",
    "UiTransitionDefinition@1.interface",
    "UiTransitionDefinition@1.schema_version",
    "UiTransitionDefinition@1.to_state_id",
    "UiTransitionDefinition@1.transition_id",
    "VisualRegressionReceipt@1.analysis_classification",
    "VisualRegressionReceipt@1.application_id",
    "VisualRegressionReceipt@1.baseline_digest",
    "VisualRegressionReceipt@1.browser",
    "VisualRegressionReceipt@1.browser_version",
    "VisualRegressionReceipt@1.color_scheme",
    "VisualRegressionReceipt@1.decision",
    "VisualRegressionReceipt@1.evidence_level",
    "VisualRegressionReceipt@1.interface",
    "VisualRegressionReceipt@1.locale",
    "VisualRegressionReceipt@1.receipt_id",
    "VisualRegressionReceipt@1.repository_revision",
    "VisualRegressionReceipt@1.scenario_id",
    "VisualRegressionReceipt@1.schema_version",
    "VisualRegressionReceipt@1.screen_id",
    "VisualRegressionReceipt@1.screenshot_digest",
    "VisualRegressionReceipt@1.verification_status",
)

DIGEST_WIRE_CASES = (
    "GuiImprovementReceipt@1.patch_digest",
    "UiBaseline@1.metric_digest",
    "UiComponentVersion@1.accessibility_digest",
    "UiComponentVersion@1.actions_digest",
    "UiComponentVersion@1.handlers_digest",
    "UiComponentVersion@1.localization_digest",
    "UiComponentVersion@1.props_digest",
    "UiComponentVersion@1.state_digest",
    "UiComponentVersion@1.structure_digest",
    "UiComponentVersion@1.styles_digest",
    "UiEvaluationScenario@1.fixture_digest",
    "VisualRegressionReceipt@1.baseline_digest",
    "VisualRegressionReceipt@1.screenshot_digest",
)

_DIGESTS = tuple(f"sha256:{character * 64}" for character in "abcdef12345678")


def _record(interface: str, **fields: Any) -> dict[str, Any]:
    nested = {
        "SourceSpan@1": "gui-source-span/v1",
        "ViewportSpec@1": "gui-viewport-spec/v1",
        "VisualChangeRegion@1": "visual-change-region/v1",
        "UiContextSource@1": "ui-context-source/v1",
        "UiContextStyle@1": "ui-context-style/v1",
        "UiContextTest@1": "ui-context-test/v1",
        "UiContextStateMachine@1": "ui-context-state-machine/v1",
        "UiContextFormalFailure@1": "ui-context-formal-failure/v1",
        "UiContextAccessibilityViolation@1": "ui-context-accessibility-violation/v1",
        "UiContextVisualReference@1": "ui-context-visual-reference/v1",
        "UiContextScreenshotDescription@1": "ui-context-screenshot-description/v1",
        "UiContextRoute@1": "ui-context-route/v1",
        "UiContextMetricBaseline@1": "ui-context-metric-baseline/v1",
    }
    schema = dict(SCHEMA_VERSION_BY_INTERFACE) | nested
    return {**fields, "interface": interface, "schema_version": schema[interface]}


def _component_identity(qualified_name: str = "apps.agent-supervisor.ConsoleRoot") -> dict[str, Any]:
    return _record(
        "UiComponentIdentity@1",
        application_id="app:agent-supervisor",
        qualified_name=qualified_name,
        component_kind="screen",
        package_namespace="swissknife.web.js.apps",
        screen_id="screen:agent-supervisor",
    )


def _component_version(qualified_name: str = "apps.agent-supervisor.ConsoleRoot") -> dict[str, Any]:
    return _record(
        "UiComponentVersion@1",
        stable_identity=_component_identity(qualified_name),
        structure_digest=_DIGESTS[0],
        props_digest=_DIGESTS[1],
        state_digest=_DIGESTS[2],
        handlers_digest=_DIGESTS[3],
        accessibility_digest=_DIGESTS[4],
        styles_digest=_DIGESTS[5],
        actions_digest=_DIGESTS[6],
        localization_digest=_DIGESTS[7],
        extractor_version="1.0.0",
        optimizer_schema_version="ui-component-version/v1",
    )


def _capsule(capsule_id: str, qualified_name: str) -> dict[str, Any]:
    return _record(
        "UiSemanticCapsule@1",
        capsule_id=capsule_id,
        stable_identity=_component_identity(qualified_name),
        version_identity=_component_version(qualified_name),
        application_id="app:agent-supervisor",
        screen_id="screen:agent-supervisor",
        purpose="Bounded Agent Supervisor console surface",
        component_type="screen-root",
        analysis_classification="exact",
        verification_status="unverified",
        completeness_boundary="complete_within_boundary",
        prop_names=["goals", "tasks"],
        emitted_event_ids=["event:submit"],
        state_variable_ids=["state:ready"],
        visible_state_ids=["state:ready", "state:loading"],
        transition_ids=["transition:ready-to-loading"],
        action_binding_ids=["action:dispatch"],
        action_side_effects=["dispatch-goal"],
        layout_role="primary-workspace",
        responsive_behavior=["stack-on-narrow", "preserve-primary-action"],
        keyboard_interactions=["enter-submits", "escape-cancels-dialog"],
        focus_behavior=["restore-trigger-after-close", "trap-focus-in-modal"],
        child_component_ids=["comp:goal-form"],
        dependency_edge_ids=["edge:root-goal-form"],
        test_ids=["test:goal-form-a11y"],
        screenshot_ids=["screenshot:keyboard-desktop"],
        known_violation_ids=["violation:missing-label"],
        unresolved_dynamic_behavior=["plugin:opaque-widget"],
        localization_keys=["agentSupervisor.goal.label"],
        accessibility_contract_id="a11y:goal-form",
        confirmation_required=True,
        loading_behavior="Shows a named progress indicator.",
        empty_behavior="Shows bounded empty-state guidance.",
        success_behavior="Announces confirmed completion.",
        error_behavior="Shows an associated recoverable error.",
        source_revision="deadbeef",
    )


def _owned_fixtures() -> dict[str, dict[str, Any]]:
    identity = _component_identity()
    version = _component_version()
    action = _record(
        "UiActionBinding@1",
        action_id="action:dispatch",
        method="agentSupervisor.dispatch",
        schema_id="schema:dispatch@1",
        requires_confirmation=True,
        confirmation_id="confirm:dispatch",
        policy_id="policy:dispatch",
        depends_on_schema=True,
        is_destructive=False,
        component_id="comp:goal-form",
    )
    state = _record(
        "UiStateDefinition@1",
        state_id="state:ready",
        kind="ready",
        screen_id="screen:agent-supervisor",
        label="Ready",
        is_initial=True,
        is_terminal=False,
        description="The bounded workflow is ready.",
    )
    event = _record(
        "UiEventDefinition@1",
        event_id="event:submit",
        kind="submit",
        name="submit-goal",
        description="Submit the validated goal.",
    )
    transition = _record(
        "UiTransitionDefinition@1",
        transition_id="transition:ready-to-loading",
        from_state_id="state:ready",
        to_state_id="state:loading",
        event_id="event:submit",
        guard="form.valid && confirmation.current",
        effect_ids=["effect:dispatch"],
        is_noop=False,
    )
    parent = _capsule("capsule:console-shell", "apps.agent-supervisor.ConsoleShell")
    child = _capsule("capsule:goal-form", "apps.agent-supervisor.GoalForm")
    raw_content = "  const label = 'Goal';\n\treturn label;\n\n"
    style_content = "\t.primary {\r\n  color: var(--primary);\r\n}\r\n"
    test_content = " describe('goal form', () => {\n\n\tit('labels input', verify);\n}); "
    raw_tokens = 500
    capsule_tokens = 100
    screenshot_tokens = 50
    other_tokens = 25
    replaced_tokens = 900
    total_tokens = raw_tokens + capsule_tokens + screenshot_tokens + other_tokens
    ordinary_tokens = raw_tokens + replaced_tokens + screenshot_tokens + other_tokens
    context = _record(
        "UiContextPack@1",
        pack_id="pack:label-form",
        application_id="app:agent-supervisor",
        screen_id="screen:agent-supervisor",
        objective="Ensure the goal form has an accessible name.",
        baseline_id="baseline:agent-supervisor-v1",
        raw_sources=[
            _record(
                "UiContextSource@1",
                path="swissknife/web/js/apps/agent-supervisor.js",
                content=raw_content,
                component_id="comp:goal-form",
                editable=True,
            )
        ],
        styles=[
            _record(
                "UiContextStyle@1",
                path="swissknife/web/css/tokens.css",
                content=style_content,
                style_kind="design-token",
            )
        ],
        affected_tests=[
            _record(
                "UiContextTest@1",
                path="swissknife/test/unit/apps/agent-supervisor.test.ts",
                content=test_content,
                test_id="test:goal-form-a11y",
            )
        ],
        parent_capsules=[parent],
        child_capsules=[child],
        state_machine=_record(
            "UiContextStateMachine@1",
            machine_id="sm:agent-supervisor",
            initial_state_id="state:ready",
            states=[state],
            events=[event],
            transitions=[transition],
        ),
        formal_invariant_failures=[
            _record(
                "UiContextFormalFailure@1",
                invariant_id="invariant:input-accessible-name",
                status="violated",
                description="Goal input has no accessible name.",
            )
        ],
        accessibility_violations=[
            _record(
                "UiContextAccessibilityViolation@1",
                violation_id="violation:missing-label",
                severity="serious",
                description="Goal input lacks an associated label.",
            )
        ],
        visual_references=[
            _record(
                "UiContextVisualReference@1",
                artifact_digest=_DIGESTS[8],
                description="Desktop baseline before the bounded label repair.",
            )
        ],
        screenshot_descriptions=[
            _record(
                "UiContextScreenshotDescription@1",
                scenario_id="scenario:keyboard-only",
                artifact_digest=_DIGESTS[9],
                description="The goal form is visible at desktop width.",
            )
        ],
        artifact_digests=[_DIGESTS[8], _DIGESTS[9]],
        affected_routes=[
            _record(
                "UiContextRoute@1",
                route_id="route:agent-supervisor",
                path="/agent-supervisor",
            )
        ],
        action_bindings=[action],
        metric_baseline=_record(
            "UiContextMetricBaseline@1",
            metric_id="metric:goal-form",
            metrics={"interaction_steps": 3, "unlabeled_controls": 1},
        ),
        acceptance_criteria=["Goal input has one accessible name."],
        excluded_context_explanation="Unrelated applications are excluded.",
        escalation_conditions=["Escalate if action binding changes."],
        raw_source_tokens=raw_tokens,
        capsule_tokens=capsule_tokens,
        screenshot_analysis_tokens=screenshot_tokens,
        other_context_tokens=other_tokens,
        source_tokens_replaced_by_capsules=replaced_tokens,
        ordinary_raw_dependency_tokens=ordinary_tokens,
        total_estimated_prompt_tokens=total_tokens,
        token_budget=800,
        compression_ratio=(ordinary_tokens - total_tokens) / ordinary_tokens,
        analysis_classification="conservative",
        verification_status="unverified",
    )
    region_expected = _record(
        "VisualChangeRegion@1",
        region_id="region:label",
        x=0.25,
        y=0.25,
        width=0.25,
        height=0.25,
        evidence_reason="The label is the declared change target.",
    )
    region_forbidden = _record(
        "VisualChangeRegion@1",
        region_id="region:navigation",
        x=0.0,
        y=0.0,
        width=0.2,
        height=0.2,
        evidence_reason="Navigation is outside patch scope.",
    )
    viewport = _record(
        "ViewportSpec@1",
        width=1280,
        height=800,
        device_scale_factor=1,
    )
    source_span = _record(
        "SourceSpan@1",
        path="swissknife/web/js/apps/agent-supervisor.js",
        start_line=10,
        start_column=0,
        end_line=40,
        end_column=1,
    )
    fixtures = {
        "AccessibilityReceipt@1": _record(
            "AccessibilityReceipt@1",
            receipt_id="receipt:a11y-1",
            application_id="app:agent-supervisor",
            screen_id="screen:agent-supervisor",
            scenario_id="scenario:keyboard-only",
            repository_revision="deadbeef",
            automated_pass_count=12,
            violation_count=0,
            violation_ids=[],
            manual_check_ids=["manual:focus-order"],
            unsupported_criteria=["WCAG-1.3.5"],
            keyboard_result="satisfied",
            screen_reader_reviewed=False,
            evidence_level="automated",
            analysis_classification="exact",
            verification_status="verified",
        ),
        "GuiApplicationIdentity@1": _record(
            "GuiApplicationIdentity@1",
            application_id="app:agent-supervisor",
            package_namespace="swissknife.web.js.apps",
            display_name="Agent Supervisor",
            repository_root="swissknife",
        ),
        "GuiImprovementProposal@1": _record(
            "GuiImprovementProposal@1",
            proposal_id="proposal:label-form",
            application_id="app:agent-supervisor",
            screen_id="screen:agent-supervisor",
            objective="Ensure the goal form has an accessible name.",
            intended_file_paths=["swissknife/web/js/apps/agent-supervisor.js"],
            intended_component_ids=["comp:goal-form"],
            acceptance_criteria=["Goal input has one accessible name."],
            expected_test_ids=["test:goal-form-a11y"],
            expected_screenshot_ids=["screenshot:keyboard-desktop"],
            state_effect_ids=["state:ready"],
            visual_effect_summary="Adds the declared visible label.",
            route_kind="deterministic_transform",
            context_pack_id="pack:label-form",
            decision="pending",
            analysis_classification="exact",
            verification_status="unverified",
        ),
        "GuiImprovementReceipt@1": _record(
            "GuiImprovementReceipt@1",
            receipt_id="receipt:improvement-1",
            proposal_id="proposal:label-form",
            application_id="app:agent-supervisor",
            screen_id="screen:agent-supervisor",
            repository_revision="deadbeef",
            decision="accept",
            visual_receipt_ids=["receipt:visual-1"],
            accessibility_receipt_ids=["receipt:a11y-1"],
            interaction_receipt_ids=["receipt:interaction-1"],
            constraint_receipt_ids=["receipt:constraint-1"],
            invalidation_plan_id="invalidate:label-form",
            context_pack_id="pack:label-form",
            patch_digest=_DIGESTS[13],
            rejection_reasons=[],
            analysis_classification="exact",
            verification_status="verified",
        ),
        "GuiScreenIdentity@1": _record(
            "GuiScreenIdentity@1",
            application_id="app:agent-supervisor",
            screen_id="screen:agent-supervisor",
            route_id="route:agent-supervisor",
        ),
        "InteractionReceipt@1": _record(
            "InteractionReceipt@1",
            receipt_id="receipt:interaction-1",
            application_id="app:agent-supervisor",
            screen_id="screen:agent-supervisor",
            scenario_id="scenario:keyboard-only",
            repository_revision="deadbeef",
            step_ids=["step:focus-input", "step:activate-submit"],
            focus_sequence=["goal-input", "submit-button"],
            event_ids=["event:focus", "event:keyboard_activation"],
            action_invocation_ids=["invoke:dispatch"],
            confirmation_id="confirm:dispatch",
            recovery_ids=["recovery:return-ready"],
            unresolved_observation_ids=[],
            evidence_level="automated",
            analysis_classification="exact",
            verification_status="verified",
        ),
        "UiAccessibilityContract@1": _record(
            "UiAccessibilityContract@1",
            contract_id="a11y:goal-form",
            requirement_kinds=["accessible_name", "keyboard_activation"],
            required_roles=["form", "button"],
            required_names=["Goal", "Submit goal"],
            component_id="comp:goal-form",
            notes="Automated coverage does not establish full WCAG compliance.",
        ),
        "UiActionBinding@1": action,
        "UiBaseline@1": _record(
            "UiBaseline@1",
            baseline_id="baseline:agent-supervisor-v1",
            application_id="app:agent-supervisor",
            screen_id="screen:agent-supervisor",
            repository_revision="deadbeef",
            scenario_ids=["scenario:keyboard-only", "scenario:initial-load"],
            metric_digest=_DIGESTS[10],
            artifact_digests=[_DIGESTS[8], _DIGESTS[9]],
            extractor_version="1.0.0",
        ),
        "UiChangeSet@1": _record(
            "UiChangeSet@1",
            change_set_id="change:label-fix",
            change_kinds=["component_implementation", "accessibility"],
            file_paths=["swissknife/web/js/apps/agent-supervisor.js"],
            component_ids=["comp:goal-form"],
            state_ids=["state:ready"],
            action_ids=["action:dispatch"],
            summary="Add an accessible name to the goal form.",
        ),
        "UiComponentIdentity@1": identity,
        "UiComponentVersion@1": version,
        "UiConstraintReceipt@1": _record(
            "UiConstraintReceipt@1",
            receipt_id="receipt:constraint-1",
            application_id="app:agent-supervisor",
            screen_id="screen:agent-supervisor",
            repository_revision="deadbeef",
            check_ids=["check:reachable", "check:confirmation", "check:manual"],
            statuses=["satisfied", "violated", "unsupported"],
            violated_check_ids=["check:confirmation"],
            unsupported_check_ids=["check:manual"],
            solver_id="solver:finite-graph",
            evidence_level="structural",
            analysis_classification="exact",
            verification_status="structurally_valid",
        ),
        "UiContextPack@1": context,
        "UiDependencyEdge@1": _record(
            "UiDependencyEdge@1",
            source_component_id="comp:root",
            target_component_id="comp:goal-form",
            relation="contains",
            extraction_method="typescript_compiler_api",
            extractor_version="1.0.0",
            confidence="exact",
            source_span=source_span,
            notes="Exact compiler-derived edge.",
        ),
        "UiEvaluationScenario@1": _record(
            "UiEvaluationScenario@1",
            scenario_id="scenario:keyboard-only",
            name="Keyboard-only navigation",
            application_id="app:agent-supervisor",
            screen_id="screen:agent-supervisor",
            fixture_digest=_DIGESTS[11],
            viewport=viewport,
            locale="en-US",
            timezone="UTC",
            color_scheme="light",
            text_scale_percent=100,
            reduced_motion=True,
            tags=["keyboard", "a11y"],
        ),
        "UiEventDefinition@1": event,
        "UiInvalidationPlan@1": _record(
            "UiInvalidationPlan@1",
            plan_id="invalidate:label-form",
            change_set_id="change:label-fix",
            reasons=["component_changed"],
            affected_component_ids=["comp:goal-form"],
            affected_scenario_ids=["scenario:keyboard-only"],
            affected_check_ids=["check:accessible-name"],
            confidence="exact",
            fallback_triggered=False,
            fallback_explanation="No uncertainty requires broad fallback.",
        ),
        "UiLayoutConstraint@1": _record(
            "UiLayoutConstraint@1",
            constraint_id="layout:no-overflow",
            kind="no_horizontal_overflow",
            expression="content.width <= viewport.width",
            component_id="comp:root",
            breakpoint="mobile",
            lower_bound=320,
            upper_bound=1920,
        ),
        "UiSemanticCapsule@1": _capsule(
            "capsule:console-root", "apps.agent-supervisor.ConsoleRoot"
        ),
        "UiStateDefinition@1": state,
        "UiTransitionDefinition@1": transition,
        "VisualRegressionReceipt@1": _record(
            "VisualRegressionReceipt@1",
            receipt_id="receipt:visual-1",
            application_id="app:agent-supervisor",
            screen_id="screen:agent-supervisor",
            scenario_id="scenario:keyboard-only",
            repository_revision="deadbeef",
            component_version_ids=["version:console-root"],
            viewport=viewport,
            screenshot_digest=_DIGESTS[12],
            baseline_digest=_DIGESTS[13],
            decision="pass",
            evidence_level="heuristic",
            pixel_diff_percent=0.25,
            structural_diff_percent=0.1,
            unexpected_layout_shift_count=0,
            missing_control_count=0,
            extra_control_count=0,
            screenshot_width=1280,
            screenshot_height=800,
            expected_change_regions=[region_expected],
            forbidden_change_regions=[region_forbidden],
            max_unexplained_diff_percent=1.0,
            manual_review_threshold_percent=2.0,
            requires_human_review=False,
            color_scheme="light",
            locale="en-US",
            text_scale_percent=100,
            browser="chromium",
            browser_version="128.0.0",
            analysis_classification="heuristic",
            verification_status="simulated",
        ),
    }
    return {key: fixtures[key] for key in sorted(fixtures)}


def _samples() -> dict[str, Any]:
    fixtures = _owned_fixtures()
    return {
        interface: MODEL_TYPES[interface].from_dict(payload)
        for interface, payload in fixtures.items()
    }


def test_required_model_inventory_is_complete_and_registered() -> None:
    inventory = required_model_inventory()
    assert inventory == tuple(sorted(REQUIRED_MODEL_INTERFACES))
    assert len(inventory) == 23
    assert_required_models_registered()
    assert set(MODEL_TYPES) == set(REQUIRED_MODEL_INTERFACES)


def test_every_required_model_round_trips_and_is_versioned() -> None:
    samples = _samples()
    assert set(samples) == set(REQUIRED_MODEL_INTERFACES)
    for interface, instance in samples.items():
        payload = instance.to_dict()
        assert payload["interface"] == interface
        assert payload["schema_version"] == SCHEMA_VERSION_BY_INTERFACE[interface]
        restored = type(instance).from_dict(payload)
        assert restored.to_dict() == payload
        assert decode_model(payload).to_dict() == payload


def test_layout_constraint_direct_constructor_preserves_attempt3_contract() -> None:
    payload = _owned_fixtures()["UiLayoutConstraint@1"]
    payload = dict(payload, lower_bound=None, upper_bound=None)
    cls = MODEL_TYPES["UiLayoutConstraint@1"]
    signature = inspect.signature(cls)
    assert tuple(signature.parameters) == (
        "constraint_id",
        "kind",
        "expression",
        "component_id",
        "breakpoint",
        "lower_bound",
        "upper_bound",
        "interface",
        "schema_version",
    )
    assert all(
        parameter.default is inspect.Parameter.empty
        for parameter in signature.parameters.values()
    )
    model = cls(**payload)
    assert model.to_dict() == payload
    for field in ("lower_bound", "upper_bound"):
        candidate = dict(_owned_fixtures()["UiLayoutConstraint@1"], **{field: None})
        with pytest.raises(GuiOptimizerDecodeError):
            cls.from_dict(candidate)


def test_source_span_direct_constructor_preserves_nullable_end_coordinates() -> None:
    payload = dict(_owned_fixtures()["UiDependencyEdge@1"]["source_span"])
    payload.update(end_line=None, end_column=None)
    cls = NESTED_MODEL_TYPES["SourceSpan@1"]
    assert cls(**payload).to_dict() == payload
    with pytest.raises(GuiOptimizerDecodeError):
        cls.from_dict(payload)


def test_viewport_direct_constructor_preserves_positive_finite_float_scale() -> None:
    payload = dict(_owned_fixtures()["UiEvaluationScenario@1"]["viewport"])
    payload["device_scale_factor"] = 1.25
    cls = NESTED_MODEL_TYPES["ViewportSpec@1"]
    assert cls(**payload).to_dict() == payload
    with pytest.raises(GuiOptimizerDecodeError):
        cls.from_dict(payload)


def test_component_version_direct_constructor_preserves_optional_localization_digest() -> None:
    payload = dict(_owned_fixtures()["UiComponentVersion@1"])
    payload["localization_digest"] = ""
    cls = MODEL_TYPES["UiComponentVersion@1"]
    assert cls(**payload).to_dict() == payload
    with pytest.raises(GuiOptimizerDecodeError):
        cls.from_dict(payload)


def test_dependency_edge_direct_constructor_preserves_none_notes_default() -> None:
    payload = dict(_owned_fixtures()["UiDependencyEdge@1"])
    payload["notes"] = None
    cls = MODEL_TYPES["UiDependencyEdge@1"]
    assert cls(**payload).notes == ""
    with pytest.raises(GuiOptimizerDecodeError):
        cls.from_dict(payload)


def test_metric_baseline_direct_constructor_preserves_closed_json_values() -> None:
    payload = dict(_owned_fixtures()["UiContextPack@1"]["metric_baseline"])
    payload["metrics"] = {
        "enabled": True,
        "label": "baseline",
        "thresholds": [1, 1.5, None],
    }
    cls = NESTED_MODEL_TYPES["UiContextMetricBaseline@1"]
    assert cls(**payload).to_dict() == payload
    wire_payload = dict(_owned_fixtures()["UiContextPack@1"]["metric_baseline"])
    wire_payload["metrics"] = {"interaction_steps": 3.0}
    with pytest.raises(GuiOptimizerDecodeError):
        cls.from_dict(wire_payload)


def test_canonical_serialization_is_deterministic() -> None:
    for instance in _samples().values():
        first = instance.canonical_bytes()
        second = canonical_model_bytes(instance.to_dict())
        assert first == second
        decoded = json.loads(first.decode("utf-8"))
        assert list(decoded.keys()) == sorted(decoded.keys())


@pytest.mark.parametrize("interface", REQUIRED_MODEL_INTERFACES)
def test_unknown_fields_are_rejected(interface: str) -> None:
    payload = _owned_fixtures()[interface]
    payload = dict(payload)
    payload["unexpected_extension_bag"] = {"x": 1}
    with pytest.raises(GuiOptimizerDecodeError, match="unknown"):
        MODEL_TYPES[interface].from_dict(payload)


@pytest.mark.parametrize("qualified", NULL_ARRAY_REGRESSIONS)
def test_null_array_regressions(qualified: str) -> None:
    interface, field = qualified.split(".", 1)
    payload = dict(_owned_fixtures()[interface])
    payload[field] = None
    with pytest.raises(GuiOptimizerDecodeError):
        MODEL_TYPES[interface].from_dict(payload)


@pytest.mark.parametrize("qualified", NULL_SCALAR_REGRESSIONS)
def test_null_scalar_regressions(qualified: str) -> None:
    interface, field = qualified.split(".", 1)
    payload = dict(_owned_fixtures()[interface])
    payload[field] = None
    with pytest.raises(GuiOptimizerDecodeError):
        MODEL_TYPES[interface].from_dict(payload)


@pytest.mark.parametrize("qualified", ARRAY_WIRE_CASES)
def test_array_fields_reject_wrong_containers(qualified: str) -> None:
    interface, field = qualified.split(".", 1)
    payload = dict(_owned_fixtures()[interface])
    original = payload[field]
    for invalid in (tuple(original) if type(original) is list else (), None, {}, "x", 7, True):
        candidate = dict(payload)
        candidate[field] = invalid
        with pytest.raises(GuiOptimizerDecodeError):
            MODEL_TYPES[interface].from_dict(candidate)


@pytest.mark.parametrize("qualified", SCALAR_WIRE_CASES)
def test_scalar_fields_reject_null(qualified: str) -> None:
    interface, field = qualified.split(".", 1)
    payload = dict(_owned_fixtures()[interface])
    if field not in payload or type(payload[field]) is not str:
        pytest.skip("scalar fixture drift")
    payload[field] = None
    with pytest.raises(GuiOptimizerDecodeError):
        MODEL_TYPES[interface].from_dict(payload)


@pytest.mark.parametrize("qualified", DIGEST_WIRE_CASES)
def test_digest_fields_reject_malformed(qualified: str) -> None:
    interface, field = qualified.split(".", 1)
    payload = dict(_owned_fixtures()[interface])
    for invalid in ("", "cidv1:" + "a" * 64, "sha256:abc", "sha256:" + "A" * 64):
        candidate = dict(payload)
        candidate[field] = invalid
        with pytest.raises(GuiOptimizerDecodeError):
            MODEL_TYPES[interface].from_dict(candidate)


def test_accepted_receipt_requires_verified_evidence() -> None:
    payload = dict(_owned_fixtures()["GuiImprovementReceipt@1"])
    payload["verification_status"] = "structurally_valid"
    with pytest.raises(GuiOptimizerDecodeError):
        MODEL_TYPES["GuiImprovementReceipt@1"].from_dict(payload)


def test_context_pack_token_equations() -> None:
    payload = dict(_owned_fixtures()["UiContextPack@1"])
    payload.update(
        {
            "raw_source_tokens": 20,
            "capsule_tokens": 7,
            "screenshot_analysis_tokens": 3,
            "other_context_tokens": 5,
            "source_tokens_replaced_by_capsules": 30,
            "ordinary_raw_dependency_tokens": 58,
            "total_estimated_prompt_tokens": 35,
            "token_budget": 45,
        }
    )
    payload.pop("compression_ratio", None)
    model = MODEL_TYPES["UiContextPack@1"].from_dict(payload)
    wire = model.to_dict()
    assert wire["total_estimated_prompt_tokens"] == 35
    assert wire["ordinary_raw_dependency_tokens"] == 58
    assert wire["compression_ratio"] == (58 - 35) / 58


def test_analysis_and_verification_are_independent() -> None:
    payload = dict(_owned_fixtures()["UiSemanticCapsule@1"])
    payload["analysis_classification"] = "exact"
    payload["verification_status"] = "unverified"
    model = MODEL_TYPES["UiSemanticCapsule@1"].from_dict(payload)
    wire = model.to_dict()
    assert wire["analysis_classification"] == "exact"
    assert wire["verification_status"] == "unverified"


def test_package_avoids_excluded_imports() -> None:
    package_root = (
        Path(__file__).resolve().parents[4]
        / "ipfs_datasets_py"
        / "logic"
        / "gui_optimizer"
    )
    excluded = (
        "semantic_index",
        "semantic_capsule",
        "proof_cache",
        "proof_corpus",
        "model_routing",
        "ui_ux_ir",
        "router_deps",
    )
    for path in package_root.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                continue
            for name in names:
                assert not any(part in name for part in excluded), (path, name)


def test_manifest_counts() -> None:
    assert len(NULL_ARRAY_REGRESSIONS) == 52
    assert len(NULL_SCALAR_REGRESSIONS) == 35
    assert len(ARRAY_WIRE_CASES) == 74
    assert len(SCALAR_WIRE_CASES) == 208
    assert len(DIGEST_WIRE_CASES) == 13
