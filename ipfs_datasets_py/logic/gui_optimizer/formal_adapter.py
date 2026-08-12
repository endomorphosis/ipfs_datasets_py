"""UiContextPack and nested context wire models (VGO-001)."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, ClassVar

from .schema import (
    UI_CONTEXT_ACCESSIBILITY_VIOLATION_INTERFACE,
    UI_CONTEXT_ACCESSIBILITY_VIOLATION_SCHEMA,
    UI_CONTEXT_FORMAL_FAILURE_INTERFACE,
    UI_CONTEXT_FORMAL_FAILURE_SCHEMA,
    UI_CONTEXT_METRIC_BASELINE_INTERFACE,
    UI_CONTEXT_METRIC_BASELINE_SCHEMA,
    UI_CONTEXT_PACK_INTERFACE,
    UI_CONTEXT_PACK_SCHEMA,
    UI_CONTEXT_ROUTE_INTERFACE,
    UI_CONTEXT_ROUTE_SCHEMA,
    UI_CONTEXT_SCREENSHOT_DESCRIPTION_INTERFACE,
    UI_CONTEXT_SCREENSHOT_DESCRIPTION_SCHEMA,
    UI_CONTEXT_SOURCE_INTERFACE,
    UI_CONTEXT_SOURCE_SCHEMA,
    UI_CONTEXT_STATE_MACHINE_INTERFACE,
    UI_CONTEXT_STATE_MACHINE_SCHEMA,
    UI_CONTEXT_STYLE_INTERFACE,
    UI_CONTEXT_STYLE_SCHEMA,
    UI_CONTEXT_TEST_INTERFACE,
    UI_CONTEXT_TEST_SCHEMA,
    UI_CONTEXT_VISUAL_REFERENCE_INTERFACE,
    UI_CONTEXT_VISUAL_REFERENCE_SCHEMA,
    AccessibilitySeverity,
    AnalysisClassification,
    ConstraintCheckStatus,
    GuiOptimizerDecodeError,
    StyleKind,
    VerificationStatus,
    decode_closed_record,
    decode_nested_record,
    field_value,
    nested_record_list,
    optional_identifier,
    optional_text,
    parse_enum,
    require_bool,
    require_closed_json_value,
    require_content_string,
    require_digest,
    require_finite_number,
    require_identifier,
    require_int,
    require_interface,
    require_mapping,
    require_repo_path,
    require_schema_version,
    require_text,
    store_attrs,
    unique_digests,
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


class UiContextSource(_Base):
    INTERFACE = UI_CONTEXT_SOURCE_INTERFACE
    SCHEMA_VERSION = UI_CONTEXT_SOURCE_SCHEMA
    _FIELDS = frozenset(
        {"component_id", "content", "editable", "interface", "path", "schema_version"}
    )
    __slots__ = ("path", "content", "component_id", "editable", "interface", "schema_version")

    def __init__(
        self,
        path: str,
        content: str,
        component_id: str,
        editable: bool,
        interface: str,
        schema_version: str,
    ) -> None:
        store_attrs(
            self,
            path=require_repo_path(path, "path"),
            content=require_content_string(content, "content"),
            component_id=optional_identifier(component_id, "component_id"),
            editable=require_bool(editable, "editable"),
            interface=require_interface(interface, UI_CONTEXT_SOURCE_INTERFACE),
            schema_version=require_schema_version(schema_version, UI_CONTEXT_SOURCE_SCHEMA),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "component_id": self.component_id,
            "content": self.content,
            "editable": self.editable,
            "interface": self.interface,
            "path": self.path,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any] | Any) -> UiContextSource:
        return decode_closed_record(
            cls,
            value,
            record_name="UiContextSource",
            builder=lambda p: cls(
                path=field_value(p, "path", ""),
                content=field_value(p, "content", ""),
                component_id=field_value(p, "component_id", ""),
                editable=field_value(p, "editable", False),
                interface=field_value(p, "interface", ""),
                schema_version=field_value(p, "schema_version", ""),
            ),
        )


class UiContextStyle(_Base):
    INTERFACE = UI_CONTEXT_STYLE_INTERFACE
    SCHEMA_VERSION = UI_CONTEXT_STYLE_SCHEMA
    _FIELDS = frozenset(
        {"content", "interface", "path", "schema_version", "style_kind"}
    )
    __slots__ = ("path", "content", "style_kind", "interface", "schema_version")

    def __init__(
        self,
        path: str,
        content: str,
        style_kind: Any,
        interface: str,
        schema_version: str,
    ) -> None:
        store_attrs(
            self,
            path=require_repo_path(path, "path"),
            content=require_content_string(content, "content"),
            style_kind=parse_enum(style_kind, StyleKind, "style_kind"),
            interface=require_interface(interface, UI_CONTEXT_STYLE_INTERFACE),
            schema_version=require_schema_version(schema_version, UI_CONTEXT_STYLE_SCHEMA),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "content": self.content,
            "interface": self.interface,
            "path": self.path,
            "schema_version": self.schema_version,
            "style_kind": self.style_kind.value,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any] | Any) -> UiContextStyle:
        return decode_closed_record(
            cls,
            value,
            record_name="UiContextStyle",
            builder=lambda p: cls(
                path=field_value(p, "path", ""),
                content=field_value(p, "content", ""),
                style_kind=field_value(p, "style_kind", ""),
                interface=field_value(p, "interface", ""),
                schema_version=field_value(p, "schema_version", ""),
            ),
        )


class UiContextTest(_Base):
    INTERFACE = UI_CONTEXT_TEST_INTERFACE
    SCHEMA_VERSION = UI_CONTEXT_TEST_SCHEMA
    _FIELDS = frozenset(
        {"content", "interface", "path", "schema_version", "test_id"}
    )
    __slots__ = ("path", "content", "test_id", "interface", "schema_version")

    def __init__(
        self,
        path: str,
        content: str,
        test_id: str,
        interface: str,
        schema_version: str,
    ) -> None:
        store_attrs(
            self,
            path=require_repo_path(path, "path"),
            content=require_content_string(content, "content"),
            test_id=require_identifier(test_id, "test_id"),
            interface=require_interface(interface, UI_CONTEXT_TEST_INTERFACE),
            schema_version=require_schema_version(schema_version, UI_CONTEXT_TEST_SCHEMA),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "content": self.content,
            "interface": self.interface,
            "path": self.path,
            "schema_version": self.schema_version,
            "test_id": self.test_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any] | Any) -> UiContextTest:
        return decode_closed_record(
            cls,
            value,
            record_name="UiContextTest",
            builder=lambda p: cls(
                path=field_value(p, "path", ""),
                content=field_value(p, "content", ""),
                test_id=field_value(p, "test_id", ""),
                interface=field_value(p, "interface", ""),
                schema_version=field_value(p, "schema_version", ""),
            ),
        )


class UiContextStateMachine(_Base):
    INTERFACE = UI_CONTEXT_STATE_MACHINE_INTERFACE
    SCHEMA_VERSION = UI_CONTEXT_STATE_MACHINE_SCHEMA
    _FIELDS = frozenset(
        {
            "events",
            "initial_state_id",
            "interface",
            "machine_id",
            "schema_version",
            "states",
            "transitions",
        }
    )
    __slots__ = (
        "machine_id",
        "initial_state_id",
        "states",
        "events",
        "transitions",
        "interface",
        "schema_version",
    )

    def __init__(
        self,
        machine_id: str,
        initial_state_id: str,
        states: Any,
        events: Any,
        transitions: Any,
        interface: str,
        schema_version: str,
    ) -> None:
        from .identity import UiEventDefinition, UiStateDefinition, UiTransitionDefinition

        store_attrs(
            self,
            machine_id=require_identifier(machine_id, "machine_id"),
            initial_state_id=require_identifier(initial_state_id, "initial_state_id"),
            states=nested_record_list(UiStateDefinition, states, "states", min_items=1),
            events=nested_record_list(UiEventDefinition, events, "events", min_items=1),
            transitions=nested_record_list(
                UiTransitionDefinition, transitions, "transitions", min_items=1
            ),
            interface=require_interface(interface, UI_CONTEXT_STATE_MACHINE_INTERFACE),
            schema_version=require_schema_version(
                schema_version, UI_CONTEXT_STATE_MACHINE_SCHEMA
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "events": [item.to_dict() for item in self.events],
            "initial_state_id": self.initial_state_id,
            "interface": self.interface,
            "machine_id": self.machine_id,
            "schema_version": self.schema_version,
            "states": [item.to_dict() for item in self.states],
            "transitions": [item.to_dict() for item in self.transitions],
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any] | Any) -> UiContextStateMachine:
        return decode_closed_record(
            cls,
            value,
            record_name="UiContextStateMachine",
            builder=lambda p: cls(
                machine_id=field_value(p, "machine_id", ""),
                initial_state_id=field_value(p, "initial_state_id", ""),
                states=field_value(p, "states", []),
                events=field_value(p, "events", []),
                transitions=field_value(p, "transitions", []),
                interface=field_value(p, "interface", ""),
                schema_version=field_value(p, "schema_version", ""),
            ),
        )


class UiContextFormalFailure(_Base):
    INTERFACE = UI_CONTEXT_FORMAL_FAILURE_INTERFACE
    SCHEMA_VERSION = UI_CONTEXT_FORMAL_FAILURE_SCHEMA
    _FIELDS = frozenset(
        {"description", "interface", "invariant_id", "schema_version", "status"}
    )
    __slots__ = ("invariant_id", "status", "description", "interface", "schema_version")

    def __init__(
        self,
        invariant_id: str,
        status: Any,
        description: str,
        interface: str,
        schema_version: str,
    ) -> None:
        store_attrs(
            self,
            invariant_id=require_identifier(invariant_id, "invariant_id"),
            status=parse_enum(status, ConstraintCheckStatus, "status"),
            description=require_text(description, "description"),
            interface=require_interface(interface, UI_CONTEXT_FORMAL_FAILURE_INTERFACE),
            schema_version=require_schema_version(
                schema_version, UI_CONTEXT_FORMAL_FAILURE_SCHEMA
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "description": self.description,
            "interface": self.interface,
            "invariant_id": self.invariant_id,
            "schema_version": self.schema_version,
            "status": self.status.value,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any] | Any) -> UiContextFormalFailure:
        return decode_closed_record(
            cls,
            value,
            record_name="UiContextFormalFailure",
            builder=lambda p: cls(
                invariant_id=field_value(p, "invariant_id", ""),
                status=field_value(p, "status", ""),
                description=field_value(p, "description", ""),
                interface=field_value(p, "interface", ""),
                schema_version=field_value(p, "schema_version", ""),
            ),
        )


class UiContextAccessibilityViolation(_Base):
    INTERFACE = UI_CONTEXT_ACCESSIBILITY_VIOLATION_INTERFACE
    SCHEMA_VERSION = UI_CONTEXT_ACCESSIBILITY_VIOLATION_SCHEMA
    _FIELDS = frozenset(
        {"description", "interface", "schema_version", "severity", "violation_id"}
    )
    __slots__ = ("violation_id", "severity", "description", "interface", "schema_version")

    def __init__(
        self,
        violation_id: str,
        severity: Any,
        description: str,
        interface: str,
        schema_version: str,
    ) -> None:
        store_attrs(
            self,
            violation_id=require_identifier(violation_id, "violation_id"),
            severity=parse_enum(severity, AccessibilitySeverity, "severity"),
            description=require_text(description, "description"),
            interface=require_interface(
                interface, UI_CONTEXT_ACCESSIBILITY_VIOLATION_INTERFACE
            ),
            schema_version=require_schema_version(
                schema_version, UI_CONTEXT_ACCESSIBILITY_VIOLATION_SCHEMA
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "description": self.description,
            "interface": self.interface,
            "schema_version": self.schema_version,
            "severity": self.severity.value,
            "violation_id": self.violation_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any] | Any) -> UiContextAccessibilityViolation:
        return decode_closed_record(
            cls,
            value,
            record_name="UiContextAccessibilityViolation",
            builder=lambda p: cls(
                violation_id=field_value(p, "violation_id", ""),
                severity=field_value(p, "severity", ""),
                description=field_value(p, "description", ""),
                interface=field_value(p, "interface", ""),
                schema_version=field_value(p, "schema_version", ""),
            ),
        )


class UiContextVisualReference(_Base):
    INTERFACE = UI_CONTEXT_VISUAL_REFERENCE_INTERFACE
    SCHEMA_VERSION = UI_CONTEXT_VISUAL_REFERENCE_SCHEMA
    _FIELDS = frozenset(
        {"artifact_digest", "description", "interface", "schema_version"}
    )
    __slots__ = ("artifact_digest", "description", "interface", "schema_version")

    def __init__(
        self,
        artifact_digest: str,
        description: str,
        interface: str,
        schema_version: str,
    ) -> None:
        store_attrs(
            self,
            artifact_digest=require_digest(artifact_digest, "artifact_digest"),
            description=require_text(description, "description"),
            interface=require_interface(interface, UI_CONTEXT_VISUAL_REFERENCE_INTERFACE),
            schema_version=require_schema_version(
                schema_version, UI_CONTEXT_VISUAL_REFERENCE_SCHEMA
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_digest": self.artifact_digest,
            "description": self.description,
            "interface": self.interface,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any] | Any) -> UiContextVisualReference:
        return decode_closed_record(
            cls,
            value,
            record_name="UiContextVisualReference",
            builder=lambda p: cls(
                artifact_digest=field_value(p, "artifact_digest", ""),
                description=field_value(p, "description", ""),
                interface=field_value(p, "interface", ""),
                schema_version=field_value(p, "schema_version", ""),
            ),
        )


class UiContextScreenshotDescription(_Base):
    INTERFACE = UI_CONTEXT_SCREENSHOT_DESCRIPTION_INTERFACE
    SCHEMA_VERSION = UI_CONTEXT_SCREENSHOT_DESCRIPTION_SCHEMA
    _FIELDS = frozenset(
        {
            "artifact_digest",
            "description",
            "interface",
            "scenario_id",
            "schema_version",
        }
    )
    __slots__ = (
        "scenario_id",
        "artifact_digest",
        "description",
        "interface",
        "schema_version",
    )

    def __init__(
        self,
        scenario_id: str,
        artifact_digest: str,
        description: str,
        interface: str,
        schema_version: str,
    ) -> None:
        store_attrs(
            self,
            scenario_id=require_identifier(scenario_id, "scenario_id"),
            artifact_digest=require_digest(artifact_digest, "artifact_digest"),
            description=require_text(description, "description"),
            interface=require_interface(
                interface, UI_CONTEXT_SCREENSHOT_DESCRIPTION_INTERFACE
            ),
            schema_version=require_schema_version(
                schema_version, UI_CONTEXT_SCREENSHOT_DESCRIPTION_SCHEMA
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_digest": self.artifact_digest,
            "description": self.description,
            "interface": self.interface,
            "scenario_id": self.scenario_id,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any] | Any) -> UiContextScreenshotDescription:
        return decode_closed_record(
            cls,
            value,
            record_name="UiContextScreenshotDescription",
            builder=lambda p: cls(
                scenario_id=field_value(p, "scenario_id", ""),
                artifact_digest=field_value(p, "artifact_digest", ""),
                description=field_value(p, "description", ""),
                interface=field_value(p, "interface", ""),
                schema_version=field_value(p, "schema_version", ""),
            ),
        )


class UiContextRoute(_Base):
    INTERFACE = UI_CONTEXT_ROUTE_INTERFACE
    SCHEMA_VERSION = UI_CONTEXT_ROUTE_SCHEMA
    _FIELDS = frozenset({"interface", "path", "route_id", "schema_version"})
    __slots__ = ("route_id", "path", "interface", "schema_version")

    def __init__(
        self,
        route_id: str,
        path: str,
        interface: str,
        schema_version: str,
    ) -> None:
        store_attrs(
            self,
            route_id=require_identifier(route_id, "route_id"),
            path=require_text(path, "path"),
            interface=require_interface(interface, UI_CONTEXT_ROUTE_INTERFACE),
            schema_version=require_schema_version(schema_version, UI_CONTEXT_ROUTE_SCHEMA),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "interface": self.interface,
            "path": self.path,
            "route_id": self.route_id,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any] | Any) -> UiContextRoute:
        return decode_closed_record(
            cls,
            value,
            record_name="UiContextRoute",
            builder=lambda p: cls(
                route_id=field_value(p, "route_id", ""),
                path=field_value(p, "path", ""),
                interface=field_value(p, "interface", ""),
                schema_version=field_value(p, "schema_version", ""),
            ),
        )


class UiContextMetricBaseline(_Base):
    INTERFACE = UI_CONTEXT_METRIC_BASELINE_INTERFACE
    SCHEMA_VERSION = UI_CONTEXT_METRIC_BASELINE_SCHEMA
    _FIELDS = frozenset({"interface", "metric_id", "metrics", "schema_version"})
    __slots__ = ("metric_id", "metrics", "interface", "schema_version")

    def __init__(
        self,
        metric_id: str,
        metrics: Any,
        interface: str,
        schema_version: str,
    ) -> None:
        mapping = require_mapping(metrics, "metrics")
        closed = require_closed_json_value(mapping, "metrics")
        store_attrs(
            self,
            metric_id=require_identifier(metric_id, "metric_id"),
            metrics=closed,
            interface=require_interface(interface, UI_CONTEXT_METRIC_BASELINE_INTERFACE),
            schema_version=require_schema_version(
                schema_version, UI_CONTEXT_METRIC_BASELINE_SCHEMA
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        from .schema import deep_copy_json

        return {
            "interface": self.interface,
            "metric_id": self.metric_id,
            "metrics": deep_copy_json(self.metrics),
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any] | Any) -> UiContextMetricBaseline:
        return decode_closed_record(
            cls,
            value,
            record_name="UiContextMetricBaseline",
            builder=lambda p: cls(
                metric_id=field_value(p, "metric_id", ""),
                metrics=field_value(p, "metrics", {}),
                interface=field_value(p, "interface", ""),
                schema_version=field_value(p, "schema_version", ""),
            ),
        )


class UiContextPack(_Base):
    INTERFACE = UI_CONTEXT_PACK_INTERFACE
    SCHEMA_VERSION = UI_CONTEXT_PACK_SCHEMA
    _FIELDS = frozenset(
        {
            "acceptance_criteria",
            "accessibility_violations",
            "action_bindings",
            "affected_routes",
            "affected_tests",
            "analysis_classification",
            "application_id",
            "artifact_digests",
            "baseline_id",
            "capsule_tokens",
            "child_capsules",
            "compression_ratio",
            "escalation_conditions",
            "excluded_context_explanation",
            "formal_invariant_failures",
            "interface",
            "metric_baseline",
            "objective",
            "ordinary_raw_dependency_tokens",
            "other_context_tokens",
            "pack_id",
            "parent_capsules",
            "raw_source_tokens",
            "raw_sources",
            "schema_version",
            "screen_id",
            "screenshot_analysis_tokens",
            "screenshot_descriptions",
            "source_tokens_replaced_by_capsules",
            "state_machine",
            "styles",
            "token_budget",
            "total_estimated_prompt_tokens",
            "verification_status",
            "visual_references",
        }
    )
    __slots__ = tuple(
        name
        for name in sorted(_FIELDS)
    )

    def __init__(self, **kwargs: Any) -> None:
        from .identity import UiActionBinding
        from .invariants import UiSemanticCapsule

        raw = kwargs["raw_source_tokens"]
        cap = kwargs["capsule_tokens"]
        shot = kwargs["screenshot_analysis_tokens"]
        other = kwargs["other_context_tokens"]
        replaced = kwargs["source_tokens_replaced_by_capsules"]
        raw_i = require_int(raw, "raw_source_tokens", minimum=0)
        cap_i = require_int(cap, "capsule_tokens", minimum=0)
        shot_i = require_int(shot, "screenshot_analysis_tokens", minimum=0)
        other_i = require_int(other, "other_context_tokens", minimum=0)
        replaced_i = require_int(replaced, "source_tokens_replaced_by_capsules", minimum=0)
        total = raw_i + cap_i + shot_i + other_i
        ordinary = raw_i + replaced_i + shot_i + other_i
        if ordinary <= 0:
            raise GuiOptimizerDecodeError("ordinary_raw_dependency_tokens must be positive")
        total_est = require_int(
            kwargs["total_estimated_prompt_tokens"],
            "total_estimated_prompt_tokens",
            minimum=0,
        )
        ordinary_est = require_int(
            kwargs["ordinary_raw_dependency_tokens"],
            "ordinary_raw_dependency_tokens",
            minimum=1,
        )
        if total_est != total:
            raise GuiOptimizerDecodeError(
                "total_estimated_prompt_tokens must equal raw+capsule+screenshot+other"
            )
        if ordinary_est != ordinary:
            raise GuiOptimizerDecodeError(
                "ordinary_raw_dependency_tokens equation mismatch"
            )
        budget = require_int(kwargs["token_budget"], "token_budget", minimum=1)
        if total_est > budget:
            raise GuiOptimizerDecodeError(
                "total_estimated_prompt_tokens cannot exceed token_budget"
            )
        derived = (ordinary - total) / ordinary
        from .schema import _MISSING

        ratio_raw = kwargs.get("compression_ratio", _MISSING)
        if ratio_raw is _MISSING:
            ratio = derived
        else:
            ratio = require_finite_number(ratio_raw, "compression_ratio")
            if ratio != derived:
                raise GuiOptimizerDecodeError(
                    "compression_ratio must equal the derived equation exactly"
                )
        store_attrs(
            self,
            pack_id=require_identifier(kwargs["pack_id"], "pack_id"),
            application_id=require_identifier(kwargs["application_id"], "application_id"),
            screen_id=require_identifier(kwargs["screen_id"], "screen_id"),
            objective=require_text(kwargs["objective"], "objective"),
            baseline_id=optional_identifier(kwargs.get("baseline_id", ""), "baseline_id"),
            raw_sources=nested_record_list(
                UiContextSource, kwargs["raw_sources"], "raw_sources", min_items=1
            ),
            styles=nested_record_list(UiContextStyle, kwargs["styles"], "styles", min_items=1),
            affected_tests=nested_record_list(
                UiContextTest, kwargs["affected_tests"], "affected_tests", min_items=1
            ),
            parent_capsules=nested_record_list(
                UiSemanticCapsule, kwargs["parent_capsules"], "parent_capsules", min_items=1
            ),
            child_capsules=nested_record_list(
                UiSemanticCapsule, kwargs["child_capsules"], "child_capsules", min_items=1
            ),
            state_machine=decode_nested_record(
                UiContextStateMachine, kwargs["state_machine"], "state_machine"
            ),
            formal_invariant_failures=nested_record_list(
                UiContextFormalFailure,
                kwargs["formal_invariant_failures"],
                "formal_invariant_failures",
                min_items=1,
            ),
            accessibility_violations=nested_record_list(
                UiContextAccessibilityViolation,
                kwargs["accessibility_violations"],
                "accessibility_violations",
                min_items=1,
            ),
            visual_references=nested_record_list(
                UiContextVisualReference,
                kwargs["visual_references"],
                "visual_references",
                min_items=1,
            ),
            screenshot_descriptions=nested_record_list(
                UiContextScreenshotDescription,
                kwargs["screenshot_descriptions"],
                "screenshot_descriptions",
                min_items=1,
            ),
            artifact_digests=unique_digests(kwargs["artifact_digests"], "artifact_digests"),
            affected_routes=nested_record_list(
                UiContextRoute, kwargs["affected_routes"], "affected_routes", min_items=1
            ),
            action_bindings=nested_record_list(
                UiActionBinding, kwargs["action_bindings"], "action_bindings", min_items=1
            ),
            metric_baseline=decode_nested_record(
                UiContextMetricBaseline, kwargs["metric_baseline"], "metric_baseline"
            ),
            acceptance_criteria=unique_texts(
                kwargs["acceptance_criteria"], "acceptance_criteria"
            ),
            excluded_context_explanation=optional_text(
                kwargs.get("excluded_context_explanation", ""),
                "excluded_context_explanation",
            ),
            escalation_conditions=unique_texts(
                kwargs["escalation_conditions"], "escalation_conditions"
            ),
            raw_source_tokens=raw_i,
            capsule_tokens=cap_i,
            screenshot_analysis_tokens=shot_i,
            other_context_tokens=other_i,
            source_tokens_replaced_by_capsules=replaced_i,
            ordinary_raw_dependency_tokens=ordinary_est,
            total_estimated_prompt_tokens=total_est,
            token_budget=budget,
            compression_ratio=ratio,
            analysis_classification=parse_enum(
                kwargs["analysis_classification"],
                AnalysisClassification,
                "analysis_classification",
            ),
            verification_status=parse_enum(
                kwargs["verification_status"], VerificationStatus, "verification_status"
            ),
            interface=require_interface(kwargs["interface"], UI_CONTEXT_PACK_INTERFACE),
            schema_version=require_schema_version(
                kwargs["schema_version"], UI_CONTEXT_PACK_SCHEMA
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "acceptance_criteria": list(self.acceptance_criteria),
            "accessibility_violations": [i.to_dict() for i in self.accessibility_violations],
            "action_bindings": [i.to_dict() for i in self.action_bindings],
            "affected_routes": [i.to_dict() for i in self.affected_routes],
            "affected_tests": [i.to_dict() for i in self.affected_tests],
            "analysis_classification": self.analysis_classification.value,
            "application_id": self.application_id,
            "artifact_digests": list(self.artifact_digests),
            "baseline_id": self.baseline_id,
            "capsule_tokens": self.capsule_tokens,
            "child_capsules": [i.to_dict() for i in self.child_capsules],
            "compression_ratio": self.compression_ratio,
            "escalation_conditions": list(self.escalation_conditions),
            "excluded_context_explanation": self.excluded_context_explanation,
            "formal_invariant_failures": [
                i.to_dict() for i in self.formal_invariant_failures
            ],
            "interface": self.interface,
            "metric_baseline": self.metric_baseline.to_dict(),
            "objective": self.objective,
            "ordinary_raw_dependency_tokens": self.ordinary_raw_dependency_tokens,
            "other_context_tokens": self.other_context_tokens,
            "pack_id": self.pack_id,
            "parent_capsules": [i.to_dict() for i in self.parent_capsules],
            "raw_source_tokens": self.raw_source_tokens,
            "raw_sources": [i.to_dict() for i in self.raw_sources],
            "schema_version": self.schema_version,
            "screen_id": self.screen_id,
            "screenshot_analysis_tokens": self.screenshot_analysis_tokens,
            "screenshot_descriptions": [i.to_dict() for i in self.screenshot_descriptions],
            "source_tokens_replaced_by_capsules": self.source_tokens_replaced_by_capsules,
            "state_machine": self.state_machine.to_dict(),
            "styles": [i.to_dict() for i in self.styles],
            "token_budget": self.token_budget,
            "total_estimated_prompt_tokens": self.total_estimated_prompt_tokens,
            "verification_status": self.verification_status.value,
            "visual_references": [i.to_dict() for i in self.visual_references],
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any] | Any) -> UiContextPack:
        from .schema import _MISSING

        return decode_closed_record(
            cls,
            value,
            record_name="UiContextPack",
            builder=lambda p: cls(
                pack_id=field_value(p, "pack_id", ""),
                application_id=field_value(p, "application_id", ""),
                screen_id=field_value(p, "screen_id", ""),
                objective=field_value(p, "objective", ""),
                baseline_id=field_value(p, "baseline_id", ""),
                raw_sources=field_value(p, "raw_sources", []),
                styles=field_value(p, "styles", []),
                affected_tests=field_value(p, "affected_tests", []),
                parent_capsules=field_value(p, "parent_capsules", []),
                child_capsules=field_value(p, "child_capsules", []),
                state_machine=field_value(p, "state_machine", {}),
                formal_invariant_failures=field_value(p, "formal_invariant_failures", []),
                accessibility_violations=field_value(p, "accessibility_violations", []),
                visual_references=field_value(p, "visual_references", []),
                screenshot_descriptions=field_value(p, "screenshot_descriptions", []),
                artifact_digests=field_value(p, "artifact_digests", []),
                affected_routes=field_value(p, "affected_routes", []),
                action_bindings=field_value(p, "action_bindings", []),
                metric_baseline=field_value(p, "metric_baseline", {}),
                acceptance_criteria=field_value(p, "acceptance_criteria", []),
                excluded_context_explanation=field_value(
                    p, "excluded_context_explanation", ""
                ),
                escalation_conditions=field_value(p, "escalation_conditions", []),
                raw_source_tokens=field_value(p, "raw_source_tokens", 0),
                capsule_tokens=field_value(p, "capsule_tokens", 0),
                screenshot_analysis_tokens=field_value(p, "screenshot_analysis_tokens", 0),
                other_context_tokens=field_value(p, "other_context_tokens", 0),
                source_tokens_replaced_by_capsules=field_value(
                    p, "source_tokens_replaced_by_capsules", 0
                ),
                ordinary_raw_dependency_tokens=field_value(
                    p, "ordinary_raw_dependency_tokens", 0
                ),
                total_estimated_prompt_tokens=field_value(
                    p, "total_estimated_prompt_tokens", 0
                ),
                token_budget=field_value(p, "token_budget", 0),
                compression_ratio=field_value(p, "compression_ratio", _MISSING),
                analysis_classification=field_value(p, "analysis_classification", ""),
                verification_status=field_value(p, "verification_status", ""),
                interface=field_value(p, "interface", ""),
                schema_version=field_value(p, "schema_version", ""),
            ),
        )


__all__ = [
    "UiContextSource",
    "UiContextStyle",
    "UiContextTest",
    "UiContextStateMachine",
    "UiContextFormalFailure",
    "UiContextAccessibilityViolation",
    "UiContextVisualReference",
    "UiContextScreenshotDescription",
    "UiContextRoute",
    "UiContextMetricBaseline",
    "UiContextPack",
]
