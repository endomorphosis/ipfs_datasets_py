"""Versioned, closed GUI optimizer wire models (VGO-001)."""

from __future__ import annotations

import json
import math
import unicodedata
from collections.abc import Mapping
from enum import Enum
from types import MappingProxyType
from typing import Any, ClassVar, Final

from .schema import (
    ACCESSIBILITY_RECEIPT_INTERFACE,
    CANONICAL_JSON_PROFILE,
    GUI_APPLICATION_IDENTITY_INTERFACE,
    GUI_IMPROVEMENT_PROPOSAL_INTERFACE,
    GUI_IMPROVEMENT_RECEIPT_INTERFACE,
    GUI_SCREEN_IDENTITY_INTERFACE,
    INTERACTION_RECEIPT_INTERFACE,
    NESTED_SCHEMA_VERSION_BY_INTERFACE,
    REQUIRED_MODEL_INTERFACES,
    SCHEMA_VERSION_BY_INTERFACE,
    SOURCE_SPAN_INTERFACE,
    SOURCE_SPAN_SCHEMA,
    UI_ACCESSIBILITY_CONTRACT_INTERFACE,
    UI_ACTION_BINDING_INTERFACE,
    UI_BASELINE_INTERFACE,
    UI_CHANGE_SET_INTERFACE,
    UI_COMPONENT_IDENTITY_INTERFACE,
    UI_COMPONENT_VERSION_INTERFACE,
    UI_CONSTRAINT_RECEIPT_INTERFACE,
    UI_CONTEXT_ACCESSIBILITY_VIOLATION_INTERFACE,
    UI_CONTEXT_FORMAL_FAILURE_INTERFACE,
    UI_CONTEXT_METRIC_BASELINE_INTERFACE,
    UI_CONTEXT_PACK_INTERFACE,
    UI_CONTEXT_ROUTE_INTERFACE,
    UI_CONTEXT_SCREENSHOT_DESCRIPTION_INTERFACE,
    UI_CONTEXT_SOURCE_INTERFACE,
    UI_CONTEXT_STATE_MACHINE_INTERFACE,
    UI_CONTEXT_STYLE_INTERFACE,
    UI_CONTEXT_TEST_INTERFACE,
    UI_CONTEXT_VISUAL_REFERENCE_INTERFACE,
    UI_DEPENDENCY_EDGE_INTERFACE,
    UI_EVALUATION_SCENARIO_INTERFACE,
    UI_EVENT_DEFINITION_INTERFACE,
    UI_INVALIDATION_PLAN_INTERFACE,
    UI_LAYOUT_CONSTRAINT_INTERFACE,
    UI_SEMANTIC_CAPSULE_INTERFACE,
    UI_STATE_DEFINITION_INTERFACE,
    UI_TRANSITION_DEFINITION_INTERFACE,
    VIEWPORT_SPEC_INTERFACE,
    VIEWPORT_SPEC_SCHEMA,
    VISUAL_CHANGE_REGION_INTERFACE,
    VISUAL_CHANGE_REGION_SCHEMA,
    VISUAL_REGRESSION_RECEIPT_INTERFACE,
    GuiOptimizerDecodeError,
    decode_closed_record,
    field_value,
    require_finite_number,
    require_identifier,
    require_int,
    require_interface,
    require_mapping,
    require_repo_path,
    require_schema_version,
    require_text,
    store_attrs,
)
from .identity import (
    GuiApplicationIdentity,
    GuiScreenIdentity,
    UiAccessibilityContract,
    UiActionBinding,
    UiComponentIdentity,
    UiComponentVersion,
    UiDependencyEdge,
    UiEventDefinition,
    UiLayoutConstraint,
    UiStateDefinition,
    UiTransitionDefinition,
)


class GuiOptimizerModel:
    INTERFACE: ClassVar[str]
    SCHEMA_VERSION: ClassVar[str]
    _FIELDS: ClassVar[frozenset[str]]

    def to_dict(self) -> dict[str, Any]:
        raise NotImplementedError

    def canonical_bytes(self) -> bytes:
        return canonical_model_bytes(self)

    def canonical_json(self) -> str:
        return canonical_model_json(self)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any] | Any) -> GuiOptimizerModel:
        raise NotImplementedError


def _json_ready(value: Any) -> Any:
    if value is None or type(value) in (bool, int, str):
        return value
    if type(value) is float:
        if not math.isfinite(value):
            raise GuiOptimizerDecodeError("canonical JSON rejects non-finite numbers")
        return value
    if isinstance(value, Enum):
        raise GuiOptimizerDecodeError("canonical JSON rejects Python Enum instances")
    if type(value) is dict:
        ready: dict[str, Any] = {}
        seen_nfc: dict[str, str] = {}
        for key, item in value.items():
            if type(key) is not str:
                raise GuiOptimizerDecodeError("canonical JSON mapping keys must be strings")
            nfc = unicodedata.normalize("NFC", key)
            if key != nfc:
                raise GuiOptimizerDecodeError(
                    "canonical JSON mapping keys must be NFC-normalized"
                )
            if nfc in seen_nfc or key in ready:
                raise GuiOptimizerDecodeError(f"canonical-key collision for {key!r}")
            seen_nfc[nfc] = key
            ready[key] = _json_ready(item)
        return {key: ready[key] for key in sorted(ready)}
    if type(value) is list:
        return [_json_ready(item) for item in value]
    if type(value) is tuple:
        raise GuiOptimizerDecodeError("canonical JSON rejects tuple containers")
    raise GuiOptimizerDecodeError(
        f"value of type {type(value).__name__} is not JSON-serializable"
    )


def canonical_model_bytes(payload: Mapping[str, Any] | Any) -> bytes:
    if isinstance(payload, GuiOptimizerModel) or hasattr(payload, "to_dict"):
        if type(payload) is dict:
            ready = _json_ready(payload)
        else:
            ready = _json_ready(payload.to_dict())
    elif type(payload) is dict:
        ready = _json_ready(payload)
    else:
        raise GuiOptimizerDecodeError(
            "canonical serialization requires a mapping or model with to_dict()"
        )
    return json.dumps(
        ready,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def canonical_model_json(payload: Mapping[str, Any] | Any) -> str:
    return canonical_model_bytes(payload).decode("utf-8")


class SourceSpan(GuiOptimizerModel):
    INTERFACE = SOURCE_SPAN_INTERFACE
    SCHEMA_VERSION = SOURCE_SPAN_SCHEMA
    _FIELDS = frozenset(
        {
            "end_column",
            "end_line",
            "interface",
            "path",
            "schema_version",
            "start_column",
            "start_line",
        }
    )
    __slots__ = (
        "path",
        "start_line",
        "start_column",
        "end_line",
        "end_column",
        "interface",
        "schema_version",
    )

    def __init__(
        self,
        path: str,
        start_line: int,
        start_column: int,
        end_line: int | None,
        end_column: int | None,
        interface: str,
        schema_version: str,
    ) -> None:
        end_line_v = None if end_line is None else require_int(end_line, "end_line", minimum=1)
        end_column_v = (
            None if end_column is None else require_int(end_column, "end_column", minimum=0)
        )
        start = require_int(start_line, "start_line", minimum=1)
        if end_line_v is not None and end_line_v < start:
            raise GuiOptimizerDecodeError("end_line must be >= start_line")
        store_attrs(
            self,
            path=require_repo_path(path, "path"),
            start_line=start,
            start_column=require_int(start_column, "start_column", minimum=0),
            end_line=end_line_v,
            end_column=end_column_v,
            interface=require_interface(interface, SOURCE_SPAN_INTERFACE),
            schema_version=require_schema_version(schema_version, SOURCE_SPAN_SCHEMA),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "end_column": self.end_column,
            "end_line": self.end_line,
            "interface": self.interface,
            "path": self.path,
            "schema_version": self.schema_version,
            "start_column": self.start_column,
            "start_line": self.start_line,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any] | Any) -> SourceSpan:
        return decode_closed_record(
            cls,
            value,
            record_name="SourceSpan",
            builder=lambda p: cls(
                path=field_value(p, "path", ""),
                start_line=field_value(p, "start_line", 0),
                start_column=field_value(p, "start_column", 0),
                end_line=field_value(p, "end_line", None),
                end_column=field_value(p, "end_column", None),
                interface=field_value(p, "interface", ""),
                schema_version=field_value(p, "schema_version", ""),
            ),
        )


class ViewportSpec(GuiOptimizerModel):
    INTERFACE = VIEWPORT_SPEC_INTERFACE
    SCHEMA_VERSION = VIEWPORT_SPEC_SCHEMA
    _FIELDS = frozenset(
        {"device_scale_factor", "height", "interface", "schema_version", "width"}
    )
    __slots__ = ("width", "height", "device_scale_factor", "interface", "schema_version")

    def __init__(
        self,
        width: int,
        height: int,
        device_scale_factor: float | int,
        interface: str,
        schema_version: str,
    ) -> None:
        scale = require_finite_number(device_scale_factor, "device_scale_factor")
        if float(scale) <= 0:
            raise GuiOptimizerDecodeError("device_scale_factor must be > 0")
        store_attrs(
            self,
            width=require_int(width, "width", minimum=1, maximum=100_000),
            height=require_int(height, "height", minimum=1, maximum=100_000),
            device_scale_factor=scale,
            interface=require_interface(interface, VIEWPORT_SPEC_INTERFACE),
            schema_version=require_schema_version(schema_version, VIEWPORT_SPEC_SCHEMA),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "device_scale_factor": self.device_scale_factor,
            "height": self.height,
            "interface": self.interface,
            "schema_version": self.schema_version,
            "width": self.width,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any] | Any) -> ViewportSpec:
        return decode_closed_record(
            cls,
            value,
            record_name="ViewportSpec",
            builder=lambda p: cls(
                width=field_value(p, "width", 0),
                height=field_value(p, "height", 0),
                device_scale_factor=field_value(p, "device_scale_factor", 1),
                interface=field_value(p, "interface", ""),
                schema_version=field_value(p, "schema_version", ""),
            ),
        )


class VisualChangeRegion(GuiOptimizerModel):
    INTERFACE = VISUAL_CHANGE_REGION_INTERFACE
    SCHEMA_VERSION = VISUAL_CHANGE_REGION_SCHEMA
    _FIELDS = frozenset(
        {
            "evidence_reason",
            "height",
            "interface",
            "region_id",
            "schema_version",
            "width",
            "x",
            "y",
        }
    )
    __slots__ = (
        "region_id",
        "x",
        "y",
        "width",
        "height",
        "evidence_reason",
        "interface",
        "schema_version",
    )

    def __init__(
        self,
        region_id: str,
        x: float | int,
        y: float | int,
        width: float | int,
        height: float | int,
        evidence_reason: str,
        interface: str,
        schema_version: str,
    ) -> None:
        xv = require_finite_number(x, "x")
        yv = require_finite_number(y, "y")
        wv = require_finite_number(width, "width")
        hv = require_finite_number(height, "height")
        if float(xv) < 0:
            raise GuiOptimizerDecodeError("x must be >= 0")
        if float(yv) < 0:
            raise GuiOptimizerDecodeError("y must be >= 0")
        if float(wv) <= 0:
            raise GuiOptimizerDecodeError("width must be > 0")
        if float(hv) <= 0:
            raise GuiOptimizerDecodeError("height must be > 0")
        if float(xv) + float(wv) > 1:
            raise GuiOptimizerDecodeError("x + width must be <= 1")
        if float(yv) + float(hv) > 1:
            raise GuiOptimizerDecodeError("y + height must be <= 1")
        store_attrs(
            self,
            region_id=require_identifier(region_id, "region_id"),
            x=xv,
            y=yv,
            width=wv,
            height=hv,
            evidence_reason=require_text(evidence_reason, "evidence_reason"),
            interface=require_interface(interface, VISUAL_CHANGE_REGION_INTERFACE),
            schema_version=require_schema_version(
                schema_version, VISUAL_CHANGE_REGION_SCHEMA
            ),
        )

    def overlaps(self, other: VisualChangeRegion) -> bool:
        return not (
            float(self.x) + float(self.width) <= float(other.x)
            or float(other.x) + float(other.width) <= float(self.x)
            or float(self.y) + float(self.height) <= float(other.y)
            or float(other.y) + float(other.height) <= float(self.y)
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "evidence_reason": self.evidence_reason,
            "height": self.height,
            "interface": self.interface,
            "region_id": self.region_id,
            "schema_version": self.schema_version,
            "width": self.width,
            "x": self.x,
            "y": self.y,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any] | Any) -> VisualChangeRegion:
        return decode_closed_record(
            cls,
            value,
            record_name="VisualChangeRegion",
            builder=lambda p: cls(
                region_id=field_value(p, "region_id", ""),
                x=field_value(p, "x", -1),
                y=field_value(p, "y", -1),
                width=field_value(p, "width", 0),
                height=field_value(p, "height", 0),
                evidence_reason=field_value(p, "evidence_reason", ""),
                interface=field_value(p, "interface", ""),
                schema_version=field_value(p, "schema_version", ""),
            ),
        )


# Remaining models live in companion modules to keep each file maintainable.
from .formal_adapter import (  # noqa: E402
    UiContextAccessibilityViolation,
    UiContextFormalFailure,
    UiContextMetricBaseline,
    UiContextPack,
    UiContextRoute,
    UiContextScreenshotDescription,
    UiContextSource,
    UiContextStateMachine,
    UiContextStyle,
    UiContextTest,
    UiContextVisualReference,
)
from .invariants import (  # noqa: E402
    UiBaseline,
    UiChangeSet,
    UiEvaluationScenario,
    UiInvalidationPlan,
    UiSemanticCapsule,
)
from .receipts import (  # noqa: E402
    AccessibilityReceipt,
    GuiImprovementProposal,
    GuiImprovementReceipt,
    InteractionReceipt,
    UiConstraintReceipt,
    VisualRegressionReceipt,
)

MODEL_TYPES: Final[Mapping[str, type]] = MappingProxyType(
    {
        ACCESSIBILITY_RECEIPT_INTERFACE: AccessibilityReceipt,
        GUI_APPLICATION_IDENTITY_INTERFACE: GuiApplicationIdentity,
        GUI_IMPROVEMENT_PROPOSAL_INTERFACE: GuiImprovementProposal,
        GUI_IMPROVEMENT_RECEIPT_INTERFACE: GuiImprovementReceipt,
        GUI_SCREEN_IDENTITY_INTERFACE: GuiScreenIdentity,
        INTERACTION_RECEIPT_INTERFACE: InteractionReceipt,
        UI_ACCESSIBILITY_CONTRACT_INTERFACE: UiAccessibilityContract,
        UI_ACTION_BINDING_INTERFACE: UiActionBinding,
        UI_BASELINE_INTERFACE: UiBaseline,
        UI_CHANGE_SET_INTERFACE: UiChangeSet,
        UI_COMPONENT_IDENTITY_INTERFACE: UiComponentIdentity,
        UI_COMPONENT_VERSION_INTERFACE: UiComponentVersion,
        UI_CONSTRAINT_RECEIPT_INTERFACE: UiConstraintReceipt,
        UI_CONTEXT_PACK_INTERFACE: UiContextPack,
        UI_DEPENDENCY_EDGE_INTERFACE: UiDependencyEdge,
        UI_EVALUATION_SCENARIO_INTERFACE: UiEvaluationScenario,
        UI_EVENT_DEFINITION_INTERFACE: UiEventDefinition,
        UI_INVALIDATION_PLAN_INTERFACE: UiInvalidationPlan,
        UI_LAYOUT_CONSTRAINT_INTERFACE: UiLayoutConstraint,
        UI_SEMANTIC_CAPSULE_INTERFACE: UiSemanticCapsule,
        UI_STATE_DEFINITION_INTERFACE: UiStateDefinition,
        UI_TRANSITION_DEFINITION_INTERFACE: UiTransitionDefinition,
        VISUAL_REGRESSION_RECEIPT_INTERFACE: VisualRegressionReceipt,
    }
)

NESTED_MODEL_TYPES: Final[Mapping[str, type]] = MappingProxyType(
    {
        SOURCE_SPAN_INTERFACE: SourceSpan,
        UI_CONTEXT_ACCESSIBILITY_VIOLATION_INTERFACE: UiContextAccessibilityViolation,
        UI_CONTEXT_FORMAL_FAILURE_INTERFACE: UiContextFormalFailure,
        UI_CONTEXT_METRIC_BASELINE_INTERFACE: UiContextMetricBaseline,
        UI_CONTEXT_ROUTE_INTERFACE: UiContextRoute,
        UI_CONTEXT_SCREENSHOT_DESCRIPTION_INTERFACE: UiContextScreenshotDescription,
        UI_CONTEXT_SOURCE_INTERFACE: UiContextSource,
        UI_CONTEXT_STATE_MACHINE_INTERFACE: UiContextStateMachine,
        UI_CONTEXT_STYLE_INTERFACE: UiContextStyle,
        UI_CONTEXT_TEST_INTERFACE: UiContextTest,
        UI_CONTEXT_VISUAL_REFERENCE_INTERFACE: UiContextVisualReference,
        VIEWPORT_SPEC_INTERFACE: ViewportSpec,
        VISUAL_CHANGE_REGION_INTERFACE: VisualChangeRegion,
    }
)


def decode_model(value: Mapping[str, Any] | Any) -> Any:
    payload = require_mapping(value, "model")
    interface = payload.get("interface")
    if type(interface) is not str or interface not in MODEL_TYPES:
        raise GuiOptimizerDecodeError("unknown or missing model interface")
    return MODEL_TYPES[interface].from_dict(payload)


def required_model_inventory() -> tuple[str, ...]:
    return tuple(sorted(REQUIRED_MODEL_INTERFACES))


def assert_required_models_registered() -> None:
    if set(MODEL_TYPES) != set(REQUIRED_MODEL_INTERFACES):
        raise GuiOptimizerDecodeError("MODEL_TYPES must equal required interfaces")
    if set(NESTED_MODEL_TYPES) != set(NESTED_SCHEMA_VERSION_BY_INTERFACE):
        raise GuiOptimizerDecodeError(
            "NESTED_MODEL_TYPES must equal nested schema registry"
        )


__all__ = [
    "CANONICAL_JSON_PROFILE",
    "MODEL_TYPES",
    "NESTED_MODEL_TYPES",
    "GuiOptimizerModel",
    "SourceSpan",
    "ViewportSpec",
    "VisualChangeRegion",
    "GuiApplicationIdentity",
    "GuiScreenIdentity",
    "UiComponentIdentity",
    "UiComponentVersion",
    "UiDependencyEdge",
    "UiStateDefinition",
    "UiEventDefinition",
    "UiTransitionDefinition",
    "UiActionBinding",
    "UiLayoutConstraint",
    "UiAccessibilityContract",
    "UiSemanticCapsule",
    "UiChangeSet",
    "UiInvalidationPlan",
    "UiEvaluationScenario",
    "UiBaseline",
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
    "GuiImprovementProposal",
    "VisualRegressionReceipt",
    "AccessibilityReceipt",
    "InteractionReceipt",
    "UiConstraintReceipt",
    "GuiImprovementReceipt",
    "canonical_model_bytes",
    "canonical_model_json",
    "decode_model",
    "required_model_inventory",
    "assert_required_models_registered",
]
