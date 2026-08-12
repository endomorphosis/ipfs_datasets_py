"""Capsule, change, invalidation, scenario, and baseline wire models (VGO-001)."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, ClassVar

from .schema import (
    UI_BASELINE_INTERFACE,
    UI_BASELINE_SCHEMA,
    UI_CHANGE_SET_INTERFACE,
    UI_CHANGE_SET_SCHEMA,
    UI_EVALUATION_SCENARIO_INTERFACE,
    UI_EVALUATION_SCENARIO_SCHEMA,
    UI_INVALIDATION_PLAN_INTERFACE,
    UI_INVALIDATION_PLAN_SCHEMA,
    UI_SEMANTIC_CAPSULE_INTERFACE,
    UI_SEMANTIC_CAPSULE_SCHEMA,
    AnalysisClassification,
    ChangeKind,
    CompletenessBoundary,
    ExtractionConfidence,
    GuiOptimizerDecodeError,
    InvalidationReason,
    VerificationStatus,
    decode_closed_record,
    decode_nested_record,
    field_value,
    optional_identifier,
    optional_text,
    parse_enum,
    parse_enum_sequence,
    require_bool,
    require_digest,
    require_extractor_version,
    require_identifier,
    require_int,
    require_interface,
    require_schema_version,
    require_text,
    store_attrs,
    unique_digests,
    unique_identifiers,
    unique_repo_paths,
    unique_texts,
)


class _Base:
    INTERFACE: ClassVar[str]
    SCHEMA_VERSION: ClassVar[str]
    _FIELDS: ClassVar[frozenset[str]]

    def canonical_bytes(self) -> bytes:
        from .models import canonical_model_bytes

        return canonical_model_bytes(self)

    def canonical_json(self) -> str:
        from .models import canonical_model_json

        return canonical_model_json(self)


class UiSemanticCapsule(_Base):
    INTERFACE = UI_SEMANTIC_CAPSULE_INTERFACE
    SCHEMA_VERSION = UI_SEMANTIC_CAPSULE_SCHEMA
    _FIELDS = frozenset(
        {
            "accessibility_contract_id",
            "action_binding_ids",
            "action_side_effects",
            "analysis_classification",
            "application_id",
            "capsule_id",
            "child_component_ids",
            "completeness_boundary",
            "component_type",
            "confirmation_required",
            "dependency_edge_ids",
            "emitted_event_ids",
            "empty_behavior",
            "error_behavior",
            "focus_behavior",
            "interface",
            "keyboard_interactions",
            "known_violation_ids",
            "layout_role",
            "loading_behavior",
            "localization_keys",
            "prop_names",
            "purpose",
            "responsive_behavior",
            "schema_version",
            "screen_id",
            "screenshot_ids",
            "source_revision",
            "stable_identity",
            "state_variable_ids",
            "success_behavior",
            "test_ids",
            "transition_ids",
            "unresolved_dynamic_behavior",
            "verification_status",
            "version_identity",
            "visible_state_ids",
        }
    )
    __slots__ = (
        "capsule_id",
        "stable_identity",
        "version_identity",
        "application_id",
        "screen_id",
        "purpose",
        "component_type",
        "analysis_classification",
        "verification_status",
        "completeness_boundary",
        "prop_names",
        "emitted_event_ids",
        "state_variable_ids",
        "visible_state_ids",
        "transition_ids",
        "action_binding_ids",
        "action_side_effects",
        "layout_role",
        "responsive_behavior",
        "keyboard_interactions",
        "focus_behavior",
        "child_component_ids",
        "dependency_edge_ids",
        "test_ids",
        "screenshot_ids",
        "known_violation_ids",
        "unresolved_dynamic_behavior",
        "localization_keys",
        "accessibility_contract_id",
        "confirmation_required",
        "loading_behavior",
        "empty_behavior",
        "success_behavior",
        "error_behavior",
        "source_revision",
        "interface",
        "schema_version",
    )

    def __init__(
        self,
        capsule_id: str,
        stable_identity: Any,
        version_identity: Any,
        application_id: str,
        screen_id: str,
        purpose: str,
        component_type: str,
        analysis_classification: Any,
        verification_status: Any,
        completeness_boundary: Any,
        prop_names: Any,
        emitted_event_ids: Any,
        state_variable_ids: Any,
        visible_state_ids: Any,
        transition_ids: Any,
        action_binding_ids: Any,
        action_side_effects: Any,
        layout_role: str,
        responsive_behavior: Any,
        keyboard_interactions: Any,
        focus_behavior: Any,
        child_component_ids: Any,
        dependency_edge_ids: Any,
        test_ids: Any,
        screenshot_ids: Any,
        known_violation_ids: Any,
        unresolved_dynamic_behavior: Any,
        localization_keys: Any,
        accessibility_contract_id: str,
        confirmation_required: bool,
        loading_behavior: str,
        empty_behavior: str,
        success_behavior: str,
        error_behavior: str,
        source_revision: str,
        interface: str,
        schema_version: str,
    ) -> None:
        from .identity import UiComponentIdentity, UiComponentVersion

        store_attrs(
            self,
            capsule_id=require_identifier(capsule_id, "capsule_id"),
            stable_identity=decode_nested_record(
                UiComponentIdentity, stable_identity, "stable_identity"
            ),
            version_identity=decode_nested_record(
                UiComponentVersion, version_identity, "version_identity"
            ),
            application_id=require_identifier(application_id, "application_id"),
            screen_id=require_identifier(screen_id, "screen_id"),
            purpose=require_text(purpose, "purpose"),
            component_type=require_text(component_type, "component_type"),
            analysis_classification=parse_enum(
                analysis_classification, AnalysisClassification, "analysis_classification"
            ),
            verification_status=parse_enum(
                verification_status, VerificationStatus, "verification_status"
            ),
            completeness_boundary=parse_enum(
                completeness_boundary, CompletenessBoundary, "completeness_boundary"
            ),
            prop_names=unique_texts(prop_names, "prop_names"),
            emitted_event_ids=unique_identifiers(emitted_event_ids, "emitted_event_ids"),
            state_variable_ids=unique_identifiers(state_variable_ids, "state_variable_ids"),
            visible_state_ids=unique_identifiers(visible_state_ids, "visible_state_ids"),
            transition_ids=unique_identifiers(transition_ids, "transition_ids"),
            action_binding_ids=unique_identifiers(action_binding_ids, "action_binding_ids"),
            action_side_effects=unique_texts(action_side_effects, "action_side_effects"),
            layout_role=require_text(layout_role, "layout_role"),
            responsive_behavior=unique_texts(responsive_behavior, "responsive_behavior"),
            keyboard_interactions=unique_texts(keyboard_interactions, "keyboard_interactions"),
            focus_behavior=unique_texts(focus_behavior, "focus_behavior"),
            child_component_ids=unique_identifiers(child_component_ids, "child_component_ids"),
            dependency_edge_ids=unique_identifiers(dependency_edge_ids, "dependency_edge_ids"),
            test_ids=unique_identifiers(test_ids, "test_ids"),
            screenshot_ids=unique_identifiers(screenshot_ids, "screenshot_ids"),
            known_violation_ids=unique_identifiers(known_violation_ids, "known_violation_ids"),
            unresolved_dynamic_behavior=unique_texts(
                unresolved_dynamic_behavior, "unresolved_dynamic_behavior"
            ),
            localization_keys=unique_texts(localization_keys, "localization_keys"),
            accessibility_contract_id=optional_identifier(
                accessibility_contract_id, "accessibility_contract_id"
            ),
            confirmation_required=require_bool(confirmation_required, "confirmation_required"),
            loading_behavior=optional_text(loading_behavior, "loading_behavior"),
            empty_behavior=optional_text(empty_behavior, "empty_behavior"),
            success_behavior=optional_text(success_behavior, "success_behavior"),
            error_behavior=optional_text(error_behavior, "error_behavior"),
            source_revision=optional_text(source_revision, "source_revision"),
            interface=require_interface(interface, UI_SEMANTIC_CAPSULE_INTERFACE),
            schema_version=require_schema_version(schema_version, UI_SEMANTIC_CAPSULE_SCHEMA),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "accessibility_contract_id": self.accessibility_contract_id,
            "action_binding_ids": list(self.action_binding_ids),
            "action_side_effects": list(self.action_side_effects),
            "analysis_classification": self.analysis_classification.value,
            "application_id": self.application_id,
            "capsule_id": self.capsule_id,
            "child_component_ids": list(self.child_component_ids),
            "completeness_boundary": self.completeness_boundary.value,
            "component_type": self.component_type,
            "confirmation_required": self.confirmation_required,
            "dependency_edge_ids": list(self.dependency_edge_ids),
            "emitted_event_ids": list(self.emitted_event_ids),
            "empty_behavior": self.empty_behavior,
            "error_behavior": self.error_behavior,
            "focus_behavior": list(self.focus_behavior),
            "interface": self.interface,
            "keyboard_interactions": list(self.keyboard_interactions),
            "known_violation_ids": list(self.known_violation_ids),
            "layout_role": self.layout_role,
            "loading_behavior": self.loading_behavior,
            "localization_keys": list(self.localization_keys),
            "prop_names": list(self.prop_names),
            "purpose": self.purpose,
            "responsive_behavior": list(self.responsive_behavior),
            "schema_version": self.schema_version,
            "screen_id": self.screen_id,
            "screenshot_ids": list(self.screenshot_ids),
            "source_revision": self.source_revision,
            "stable_identity": self.stable_identity.to_dict(),
            "state_variable_ids": list(self.state_variable_ids),
            "success_behavior": self.success_behavior,
            "test_ids": list(self.test_ids),
            "transition_ids": list(self.transition_ids),
            "unresolved_dynamic_behavior": list(self.unresolved_dynamic_behavior),
            "verification_status": self.verification_status.value,
            "version_identity": self.version_identity.to_dict(),
            "visible_state_ids": list(self.visible_state_ids),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any] | Any) -> UiSemanticCapsule:
        return decode_closed_record(
            cls,
            value,
            record_name="UiSemanticCapsule",
            builder=lambda p: cls(
                capsule_id=field_value(p, "capsule_id", ""),
                stable_identity=field_value(p, "stable_identity", {}),
                version_identity=field_value(p, "version_identity", {}),
                application_id=field_value(p, "application_id", ""),
                screen_id=field_value(p, "screen_id", ""),
                purpose=field_value(p, "purpose", ""),
                component_type=field_value(p, "component_type", ""),
                analysis_classification=field_value(p, "analysis_classification", ""),
                verification_status=field_value(p, "verification_status", ""),
                completeness_boundary=field_value(p, "completeness_boundary", ""),
                prop_names=field_value(p, "prop_names", []),
                emitted_event_ids=field_value(p, "emitted_event_ids", []),
                state_variable_ids=field_value(p, "state_variable_ids", []),
                visible_state_ids=field_value(p, "visible_state_ids", []),
                transition_ids=field_value(p, "transition_ids", []),
                action_binding_ids=field_value(p, "action_binding_ids", []),
                action_side_effects=field_value(p, "action_side_effects", []),
                layout_role=field_value(p, "layout_role", ""),
                responsive_behavior=field_value(p, "responsive_behavior", []),
                keyboard_interactions=field_value(p, "keyboard_interactions", []),
                focus_behavior=field_value(p, "focus_behavior", []),
                child_component_ids=field_value(p, "child_component_ids", []),
                dependency_edge_ids=field_value(p, "dependency_edge_ids", []),
                test_ids=field_value(p, "test_ids", []),
                screenshot_ids=field_value(p, "screenshot_ids", []),
                known_violation_ids=field_value(p, "known_violation_ids", []),
                unresolved_dynamic_behavior=field_value(
                    p, "unresolved_dynamic_behavior", []
                ),
                localization_keys=field_value(p, "localization_keys", []),
                accessibility_contract_id=field_value(p, "accessibility_contract_id", ""),
                confirmation_required=field_value(p, "confirmation_required", False),
                loading_behavior=field_value(p, "loading_behavior", ""),
                empty_behavior=field_value(p, "empty_behavior", ""),
                success_behavior=field_value(p, "success_behavior", ""),
                error_behavior=field_value(p, "error_behavior", ""),
                source_revision=field_value(p, "source_revision", ""),
                interface=field_value(p, "interface", ""),
                schema_version=field_value(p, "schema_version", ""),
            ),
        )


class UiChangeSet(_Base):
    INTERFACE = UI_CHANGE_SET_INTERFACE
    SCHEMA_VERSION = UI_CHANGE_SET_SCHEMA
    _FIELDS = frozenset(
        {
            "action_ids",
            "change_kinds",
            "change_set_id",
            "component_ids",
            "file_paths",
            "interface",
            "schema_version",
            "state_ids",
            "summary",
        }
    )
    __slots__ = (
        "change_set_id",
        "change_kinds",
        "file_paths",
        "component_ids",
        "state_ids",
        "action_ids",
        "summary",
        "interface",
        "schema_version",
    )

    def __init__(
        self,
        change_set_id: str,
        change_kinds: Any,
        file_paths: Any,
        component_ids: Any,
        state_ids: Any,
        action_ids: Any,
        summary: str,
        interface: str,
        schema_version: str,
    ) -> None:
        kinds = parse_enum_sequence(change_kinds, ChangeKind, "change_kinds")
        if not kinds:
            raise GuiOptimizerDecodeError("change_kinds must not be empty")
        paths = unique_repo_paths(file_paths, "file_paths")
        if not paths:
            raise GuiOptimizerDecodeError("file_paths must not be empty")
        store_attrs(
            self,
            change_set_id=require_identifier(change_set_id, "change_set_id"),
            change_kinds=kinds,
            file_paths=paths,
            component_ids=unique_identifiers(component_ids, "component_ids"),
            state_ids=unique_identifiers(state_ids, "state_ids"),
            action_ids=unique_identifiers(action_ids, "action_ids"),
            summary=optional_text(summary, "summary"),
            interface=require_interface(interface, UI_CHANGE_SET_INTERFACE),
            schema_version=require_schema_version(schema_version, UI_CHANGE_SET_SCHEMA),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "action_ids": list(self.action_ids),
            "change_kinds": [item.value for item in self.change_kinds],
            "change_set_id": self.change_set_id,
            "component_ids": list(self.component_ids),
            "file_paths": list(self.file_paths),
            "interface": self.interface,
            "schema_version": self.schema_version,
            "state_ids": list(self.state_ids),
            "summary": self.summary,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any] | Any) -> UiChangeSet:
        return decode_closed_record(
            cls,
            value,
            record_name="UiChangeSet",
            builder=lambda p: cls(
                change_set_id=field_value(p, "change_set_id", ""),
                change_kinds=field_value(p, "change_kinds", []),
                file_paths=field_value(p, "file_paths", []),
                component_ids=field_value(p, "component_ids", []),
                state_ids=field_value(p, "state_ids", []),
                action_ids=field_value(p, "action_ids", []),
                summary=field_value(p, "summary", ""),
                interface=field_value(p, "interface", ""),
                schema_version=field_value(p, "schema_version", ""),
            ),
        )


class UiInvalidationPlan(_Base):
    INTERFACE = UI_INVALIDATION_PLAN_INTERFACE
    SCHEMA_VERSION = UI_INVALIDATION_PLAN_SCHEMA
    _FIELDS = frozenset(
        {
            "affected_check_ids",
            "affected_component_ids",
            "affected_scenario_ids",
            "change_set_id",
            "confidence",
            "fallback_explanation",
            "fallback_triggered",
            "interface",
            "plan_id",
            "reasons",
            "schema_version",
        }
    )
    __slots__ = (
        "plan_id",
        "change_set_id",
        "reasons",
        "affected_component_ids",
        "affected_scenario_ids",
        "affected_check_ids",
        "confidence",
        "fallback_triggered",
        "fallback_explanation",
        "interface",
        "schema_version",
    )

    def __init__(
        self,
        plan_id: str,
        change_set_id: str,
        reasons: Any,
        affected_component_ids: Any,
        affected_scenario_ids: Any,
        affected_check_ids: Any,
        confidence: Any,
        fallback_triggered: bool,
        fallback_explanation: str,
        interface: str,
        schema_version: str,
    ) -> None:
        reason_items = parse_enum_sequence(reasons, InvalidationReason, "reasons")
        if not reason_items:
            raise GuiOptimizerDecodeError("reasons must not be empty")
        store_attrs(
            self,
            plan_id=require_identifier(plan_id, "plan_id"),
            change_set_id=require_identifier(change_set_id, "change_set_id"),
            reasons=reason_items,
            affected_component_ids=unique_identifiers(
                affected_component_ids, "affected_component_ids"
            ),
            affected_scenario_ids=unique_identifiers(
                affected_scenario_ids, "affected_scenario_ids"
            ),
            affected_check_ids=unique_identifiers(affected_check_ids, "affected_check_ids"),
            confidence=parse_enum(confidence, ExtractionConfidence, "confidence"),
            fallback_triggered=require_bool(fallback_triggered, "fallback_triggered"),
            fallback_explanation=optional_text(fallback_explanation, "fallback_explanation"),
            interface=require_interface(interface, UI_INVALIDATION_PLAN_INTERFACE),
            schema_version=require_schema_version(schema_version, UI_INVALIDATION_PLAN_SCHEMA),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "affected_check_ids": list(self.affected_check_ids),
            "affected_component_ids": list(self.affected_component_ids),
            "affected_scenario_ids": list(self.affected_scenario_ids),
            "change_set_id": self.change_set_id,
            "confidence": self.confidence.value,
            "fallback_explanation": self.fallback_explanation,
            "fallback_triggered": self.fallback_triggered,
            "interface": self.interface,
            "plan_id": self.plan_id,
            "reasons": [item.value for item in self.reasons],
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any] | Any) -> UiInvalidationPlan:
        return decode_closed_record(
            cls,
            value,
            record_name="UiInvalidationPlan",
            builder=lambda p: cls(
                plan_id=field_value(p, "plan_id", ""),
                change_set_id=field_value(p, "change_set_id", ""),
                reasons=field_value(p, "reasons", []),
                affected_component_ids=field_value(p, "affected_component_ids", []),
                affected_scenario_ids=field_value(p, "affected_scenario_ids", []),
                affected_check_ids=field_value(p, "affected_check_ids", []),
                confidence=field_value(p, "confidence", ""),
                fallback_triggered=field_value(p, "fallback_triggered", False),
                fallback_explanation=field_value(p, "fallback_explanation", ""),
                interface=field_value(p, "interface", ""),
                schema_version=field_value(p, "schema_version", ""),
            ),
        )


class UiEvaluationScenario(_Base):
    INTERFACE = UI_EVALUATION_SCENARIO_INTERFACE
    SCHEMA_VERSION = UI_EVALUATION_SCENARIO_SCHEMA
    _FIELDS = frozenset(
        {
            "application_id",
            "color_scheme",
            "fixture_digest",
            "interface",
            "locale",
            "name",
            "reduced_motion",
            "scenario_id",
            "schema_version",
            "screen_id",
            "tags",
            "text_scale_percent",
            "timezone",
            "viewport",
        }
    )
    __slots__ = (
        "scenario_id",
        "name",
        "application_id",
        "screen_id",
        "fixture_digest",
        "viewport",
        "locale",
        "timezone",
        "color_scheme",
        "text_scale_percent",
        "reduced_motion",
        "tags",
        "interface",
        "schema_version",
    )

    def __init__(
        self,
        scenario_id: str,
        name: str,
        application_id: str,
        screen_id: str,
        fixture_digest: str,
        viewport: Any,
        locale: str,
        timezone: str,
        color_scheme: str,
        text_scale_percent: int,
        reduced_motion: bool,
        tags: Any,
        interface: str,
        schema_version: str,
    ) -> None:
        from .models import ViewportSpec

        store_attrs(
            self,
            scenario_id=require_identifier(scenario_id, "scenario_id"),
            name=require_text(name, "name"),
            application_id=require_identifier(application_id, "application_id"),
            screen_id=require_identifier(screen_id, "screen_id"),
            fixture_digest=require_digest(fixture_digest, "fixture_digest"),
            viewport=decode_nested_record(ViewportSpec, viewport, "viewport"),
            locale=require_text(locale, "locale"),
            timezone=require_text(timezone, "timezone"),
            color_scheme=require_text(color_scheme, "color_scheme"),
            text_scale_percent=require_int(
                text_scale_percent, "text_scale_percent", minimum=25, maximum=500
            ),
            reduced_motion=require_bool(reduced_motion, "reduced_motion"),
            tags=unique_texts(tags, "tags"),
            interface=require_interface(interface, UI_EVALUATION_SCENARIO_INTERFACE),
            schema_version=require_schema_version(
                schema_version, UI_EVALUATION_SCENARIO_SCHEMA
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "application_id": self.application_id,
            "color_scheme": self.color_scheme,
            "fixture_digest": self.fixture_digest,
            "interface": self.interface,
            "locale": self.locale,
            "name": self.name,
            "reduced_motion": self.reduced_motion,
            "scenario_id": self.scenario_id,
            "schema_version": self.schema_version,
            "screen_id": self.screen_id,
            "tags": list(self.tags),
            "text_scale_percent": self.text_scale_percent,
            "timezone": self.timezone,
            "viewport": self.viewport.to_dict(),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any] | Any) -> UiEvaluationScenario:
        return decode_closed_record(
            cls,
            value,
            record_name="UiEvaluationScenario",
            builder=lambda p: cls(
                scenario_id=field_value(p, "scenario_id", ""),
                name=field_value(p, "name", ""),
                application_id=field_value(p, "application_id", ""),
                screen_id=field_value(p, "screen_id", ""),
                fixture_digest=field_value(p, "fixture_digest", ""),
                viewport=field_value(p, "viewport", {}),
                locale=field_value(p, "locale", "en-US"),
                timezone=field_value(p, "timezone", "UTC"),
                color_scheme=field_value(p, "color_scheme", "light"),
                text_scale_percent=field_value(p, "text_scale_percent", 100),
                reduced_motion=field_value(p, "reduced_motion", False),
                tags=field_value(p, "tags", []),
                interface=field_value(p, "interface", ""),
                schema_version=field_value(p, "schema_version", ""),
            ),
        )


class UiBaseline(_Base):
    INTERFACE = UI_BASELINE_INTERFACE
    SCHEMA_VERSION = UI_BASELINE_SCHEMA
    _FIELDS = frozenset(
        {
            "application_id",
            "artifact_digests",
            "baseline_id",
            "extractor_version",
            "interface",
            "metric_digest",
            "repository_revision",
            "scenario_ids",
            "schema_version",
            "screen_id",
        }
    )
    __slots__ = (
        "baseline_id",
        "application_id",
        "screen_id",
        "repository_revision",
        "scenario_ids",
        "metric_digest",
        "artifact_digests",
        "extractor_version",
        "interface",
        "schema_version",
    )

    def __init__(
        self,
        baseline_id: str,
        application_id: str,
        screen_id: str,
        repository_revision: str,
        scenario_ids: Any,
        metric_digest: str,
        artifact_digests: Any,
        extractor_version: str,
        interface: str,
        schema_version: str,
    ) -> None:
        scenarios = unique_identifiers(scenario_ids, "scenario_ids")
        if not scenarios:
            raise GuiOptimizerDecodeError("scenario_ids must not be empty")
        store_attrs(
            self,
            baseline_id=require_identifier(baseline_id, "baseline_id"),
            application_id=require_identifier(application_id, "application_id"),
            screen_id=require_identifier(screen_id, "screen_id"),
            repository_revision=require_text(repository_revision, "repository_revision"),
            scenario_ids=scenarios,
            metric_digest=require_digest(metric_digest, "metric_digest"),
            artifact_digests=unique_digests(artifact_digests, "artifact_digests"),
            extractor_version=require_extractor_version(extractor_version),
            interface=require_interface(interface, UI_BASELINE_INTERFACE),
            schema_version=require_schema_version(schema_version, UI_BASELINE_SCHEMA),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "application_id": self.application_id,
            "artifact_digests": list(self.artifact_digests),
            "baseline_id": self.baseline_id,
            "extractor_version": self.extractor_version,
            "interface": self.interface,
            "metric_digest": self.metric_digest,
            "repository_revision": self.repository_revision,
            "scenario_ids": list(self.scenario_ids),
            "schema_version": self.schema_version,
            "screen_id": self.screen_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any] | Any) -> UiBaseline:
        return decode_closed_record(
            cls,
            value,
            record_name="UiBaseline",
            builder=lambda p: cls(
                baseline_id=field_value(p, "baseline_id", ""),
                application_id=field_value(p, "application_id", ""),
                screen_id=field_value(p, "screen_id", ""),
                repository_revision=field_value(p, "repository_revision", ""),
                scenario_ids=field_value(p, "scenario_ids", []),
                metric_digest=field_value(p, "metric_digest", ""),
                artifact_digests=field_value(p, "artifact_digests", []),
                extractor_version=field_value(p, "extractor_version", "1.0.0"),
                interface=field_value(p, "interface", ""),
                schema_version=field_value(p, "schema_version", ""),
            ),
        )


__all__ = [
    "UiSemanticCapsule",
    "UiChangeSet",
    "UiInvalidationPlan",
    "UiEvaluationScenario",
    "UiBaseline",
]
