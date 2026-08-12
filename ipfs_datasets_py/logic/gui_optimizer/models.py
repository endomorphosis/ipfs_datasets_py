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
    _MISSING,
    ACCESSIBILITY_RECEIPT_INTERFACE,
    ACCESSIBILITY_RECEIPT_SCHEMA,
    CANONICAL_JSON_PROFILE,
    GUI_APPLICATION_IDENTITY_INTERFACE,
    GUI_APPLICATION_IDENTITY_SCHEMA,
    GUI_IMPROVEMENT_PROPOSAL_INTERFACE,
    GUI_IMPROVEMENT_PROPOSAL_SCHEMA,
    GUI_IMPROVEMENT_RECEIPT_INTERFACE,
    GUI_IMPROVEMENT_RECEIPT_SCHEMA,
    GUI_SCREEN_IDENTITY_INTERFACE,
    GUI_SCREEN_IDENTITY_SCHEMA,
    INTERACTION_RECEIPT_INTERFACE,
    INTERACTION_RECEIPT_SCHEMA,
    NESTED_SCHEMA_VERSION_BY_INTERFACE,
    REQUIRED_MODEL_INTERFACES,
    SOURCE_SPAN_INTERFACE,
    SOURCE_SPAN_SCHEMA,
    UI_ACCESSIBILITY_CONTRACT_INTERFACE,
    UI_ACCESSIBILITY_CONTRACT_SCHEMA,
    UI_ACTION_BINDING_INTERFACE,
    UI_ACTION_BINDING_SCHEMA,
    UI_BASELINE_INTERFACE,
    UI_BASELINE_SCHEMA,
    UI_CHANGE_SET_INTERFACE,
    UI_CHANGE_SET_SCHEMA,
    UI_COMPONENT_IDENTITY_INTERFACE,
    UI_COMPONENT_IDENTITY_SCHEMA,
    UI_COMPONENT_VERSION_INTERFACE,
    UI_COMPONENT_VERSION_SCHEMA,
    UI_CONSTRAINT_RECEIPT_INTERFACE,
    UI_CONSTRAINT_RECEIPT_SCHEMA,
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
    UI_DEPENDENCY_EDGE_INTERFACE,
    UI_DEPENDENCY_EDGE_SCHEMA,
    UI_EVALUATION_SCENARIO_INTERFACE,
    UI_EVALUATION_SCENARIO_SCHEMA,
    UI_EVENT_DEFINITION_INTERFACE,
    UI_EVENT_DEFINITION_SCHEMA,
    UI_INVALIDATION_PLAN_INTERFACE,
    UI_INVALIDATION_PLAN_SCHEMA,
    UI_LAYOUT_CONSTRAINT_INTERFACE,
    UI_LAYOUT_CONSTRAINT_SCHEMA,
    UI_SEMANTIC_CAPSULE_INTERFACE,
    UI_SEMANTIC_CAPSULE_SCHEMA,
    UI_STATE_DEFINITION_INTERFACE,
    UI_STATE_DEFINITION_SCHEMA,
    UI_TRANSITION_DEFINITION_INTERFACE,
    UI_TRANSITION_DEFINITION_SCHEMA,
    VIEWPORT_SPEC_INTERFACE,
    VIEWPORT_SPEC_SCHEMA,
    VISUAL_CHANGE_REGION_INTERFACE,
    VISUAL_CHANGE_REGION_SCHEMA,
    VISUAL_REGRESSION_RECEIPT_INTERFACE,
    VISUAL_REGRESSION_RECEIPT_SCHEMA,
    AccessibilityRequirementKind,
    AccessibilitySeverity,
    AnalysisClassification,
    ChangeKind,
    CompletenessBoundary,
    ConstraintCheckStatus,
    EvidenceLevel,
    ExtractionConfidence,
    ExtractionMethod,
    GuiOptimizerDecodeError,
    InvalidationReason,
    LayoutConstraintKind,
    ProposalDecision,
    ProposalRouteKind,
    StyleKind,
    UiComponentKind,
    UiDependencyRelation,
    UiEventKind,
    UiStateKind,
    VerificationStatus,
    VisualDecision,
    decode_closed_record,
    decode_nested_record,
    deep_copy_json,
    field_value,
    nested_record_list,
    optional_digest,
    optional_identifier,
    optional_nested_record,
    optional_repo_path,
    optional_text,
    parse_enum,
    parse_enum_sequence,
    require_bool,
    require_content_string,
    require_digest,
    require_extractor_version,
    require_finite_number,
    require_identifier,
    require_int,
    require_interface,
    require_mapping,
    require_registered_optimizer_schema_version,
    require_repo_path,
    require_schema_version,
    require_text,
    store_attrs,
    unique_digests,
    unique_identifiers,
    unique_repo_paths,
    unique_texts,
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
        end_line_v = require_int(end_line, "end_line", minimum=1)
        end_column_v = require_int(end_column, "end_column", minimum=0)
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
        scale = require_int(device_scale_factor, "device_scale_factor", minimum=1)
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


class _IdentityBase:
    INTERFACE: ClassVar[str]
    SCHEMA_VERSION: ClassVar[str]
    _FIELDS: ClassVar[frozenset[str]]

    def canonical_bytes(self) -> bytes:
        return canonical_model_bytes(self)

    def canonical_json(self) -> str:
        return canonical_model_json(self)


class GuiApplicationIdentity(_IdentityBase):
    INTERFACE = GUI_APPLICATION_IDENTITY_INTERFACE
    SCHEMA_VERSION = GUI_APPLICATION_IDENTITY_SCHEMA
    _FIELDS = frozenset(
        {
            "application_id",
            "display_name",
            "interface",
            "package_namespace",
            "repository_root",
            "schema_version",
        }
    )
    __slots__ = (
        "application_id",
        "package_namespace",
        "display_name",
        "repository_root",
        "interface",
        "schema_version",
    )

    def __init__(
        self,
        application_id: str,
        package_namespace: str,
        display_name: str,
        repository_root: str,
        interface: str,
        schema_version: str,
    ) -> None:
        store_attrs(
            self,
            application_id=require_identifier(application_id, "application_id"),
            package_namespace=require_identifier(package_namespace, "package_namespace"),
            display_name=optional_text(display_name, "display_name"),
            repository_root=optional_repo_path(repository_root, "repository_root"),
            interface=require_interface(interface, GUI_APPLICATION_IDENTITY_INTERFACE),
            schema_version=require_schema_version(
                schema_version, GUI_APPLICATION_IDENTITY_SCHEMA
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "application_id": self.application_id,
            "display_name": self.display_name,
            "interface": self.interface,
            "package_namespace": self.package_namespace,
            "repository_root": self.repository_root,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any] | Any) -> GuiApplicationIdentity:
        return decode_closed_record(
            cls,
            value,
            record_name="GuiApplicationIdentity",
            builder=lambda p: cls(
                application_id=field_value(p, "application_id", ""),
                package_namespace=field_value(p, "package_namespace", ""),
                display_name=field_value(p, "display_name", ""),
                repository_root=field_value(p, "repository_root", ""),
                interface=field_value(p, "interface", ""),
                schema_version=field_value(p, "schema_version", ""),
            ),
        )


class GuiScreenIdentity(_IdentityBase):
    INTERFACE = GUI_SCREEN_IDENTITY_INTERFACE
    SCHEMA_VERSION = GUI_SCREEN_IDENTITY_SCHEMA
    _FIELDS = frozenset(
        {"application_id", "interface", "route_id", "schema_version", "screen_id"}
    )
    __slots__ = ("application_id", "screen_id", "route_id", "interface", "schema_version")

    def __init__(
        self,
        application_id: str,
        screen_id: str,
        route_id: str,
        interface: str,
        schema_version: str,
    ) -> None:
        store_attrs(
            self,
            application_id=require_identifier(application_id, "application_id"),
            screen_id=require_identifier(screen_id, "screen_id"),
            route_id=optional_identifier(route_id, "route_id"),
            interface=require_interface(interface, GUI_SCREEN_IDENTITY_INTERFACE),
            schema_version=require_schema_version(schema_version, GUI_SCREEN_IDENTITY_SCHEMA),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "application_id": self.application_id,
            "interface": self.interface,
            "route_id": self.route_id,
            "schema_version": self.schema_version,
            "screen_id": self.screen_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any] | Any) -> GuiScreenIdentity:
        return decode_closed_record(
            cls,
            value,
            record_name="GuiScreenIdentity",
            builder=lambda p: cls(
                application_id=field_value(p, "application_id", ""),
                screen_id=field_value(p, "screen_id", ""),
                route_id=field_value(p, "route_id", ""),
                interface=field_value(p, "interface", ""),
                schema_version=field_value(p, "schema_version", ""),
            ),
        )


class UiComponentIdentity(_IdentityBase):
    INTERFACE = UI_COMPONENT_IDENTITY_INTERFACE
    SCHEMA_VERSION = UI_COMPONENT_IDENTITY_SCHEMA
    _FIELDS = frozenset(
        {
            "application_id",
            "component_kind",
            "interface",
            "package_namespace",
            "qualified_name",
            "schema_version",
            "screen_id",
        }
    )
    __slots__ = (
        "application_id",
        "qualified_name",
        "component_kind",
        "package_namespace",
        "screen_id",
        "interface",
        "schema_version",
    )

    def __init__(
        self,
        application_id: str,
        qualified_name: str,
        component_kind: Any,
        package_namespace: str,
        screen_id: str,
        interface: str,
        schema_version: str,
    ) -> None:
        store_attrs(
            self,
            application_id=require_identifier(application_id, "application_id"),
            qualified_name=require_identifier(qualified_name, "qualified_name"),
            component_kind=parse_enum(component_kind, UiComponentKind, "component_kind"),
            package_namespace=require_identifier(package_namespace, "package_namespace"),
            screen_id=optional_identifier(screen_id, "screen_id"),
            interface=require_interface(interface, UI_COMPONENT_IDENTITY_INTERFACE),
            schema_version=require_schema_version(schema_version, UI_COMPONENT_IDENTITY_SCHEMA),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "application_id": self.application_id,
            "component_kind": self.component_kind.value,
            "interface": self.interface,
            "package_namespace": self.package_namespace,
            "qualified_name": self.qualified_name,
            "schema_version": self.schema_version,
            "screen_id": self.screen_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any] | Any) -> UiComponentIdentity:
        return decode_closed_record(
            cls,
            value,
            record_name="UiComponentIdentity",
            builder=lambda p: cls(
                application_id=field_value(p, "application_id", ""),
                qualified_name=field_value(p, "qualified_name", ""),
                component_kind=field_value(p, "component_kind", ""),
                package_namespace=field_value(p, "package_namespace", ""),
                screen_id=field_value(p, "screen_id", ""),
                interface=field_value(p, "interface", ""),
                schema_version=field_value(p, "schema_version", ""),
            ),
        )


class UiComponentVersion(_IdentityBase):
    INTERFACE = UI_COMPONENT_VERSION_INTERFACE
    SCHEMA_VERSION = UI_COMPONENT_VERSION_SCHEMA
    _FIELDS = frozenset(
        {
            "accessibility_digest",
            "actions_digest",
            "extractor_version",
            "handlers_digest",
            "interface",
            "localization_digest",
            "optimizer_schema_version",
            "props_digest",
            "schema_version",
            "stable_identity",
            "state_digest",
            "structure_digest",
            "styles_digest",
        }
    )
    __slots__ = (
        "stable_identity",
        "structure_digest",
        "props_digest",
        "state_digest",
        "handlers_digest",
        "accessibility_digest",
        "styles_digest",
        "actions_digest",
        "localization_digest",
        "extractor_version",
        "optimizer_schema_version",
        "interface",
        "schema_version",
    )

    def __init__(
        self,
        stable_identity: Any,
        structure_digest: str,
        props_digest: str,
        state_digest: str,
        handlers_digest: str,
        accessibility_digest: str,
        styles_digest: str,
        actions_digest: str,
        localization_digest: str,
        extractor_version: str,
        optimizer_schema_version: str,
        interface: str,
        schema_version: str,
    ) -> None:
        digests = {
            name: require_digest(value, name)
            for name, value in (
                ("structure_digest", structure_digest),
                ("props_digest", props_digest),
                ("state_digest", state_digest),
                ("handlers_digest", handlers_digest),
                ("accessibility_digest", accessibility_digest),
                ("styles_digest", styles_digest),
                ("actions_digest", actions_digest),
            )
        }
        store_attrs(
            self,
            stable_identity=decode_nested_record(
                UiComponentIdentity, stable_identity, "stable_identity"
            ),
            **digests,
            localization_digest=require_digest(localization_digest, "localization_digest"),
            extractor_version=require_extractor_version(extractor_version),
            optimizer_schema_version=require_registered_optimizer_schema_version(
                optimizer_schema_version, "optimizer_schema_version"
            ),
            interface=require_interface(interface, UI_COMPONENT_VERSION_INTERFACE),
            schema_version=require_schema_version(schema_version, UI_COMPONENT_VERSION_SCHEMA),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "accessibility_digest": self.accessibility_digest,
            "actions_digest": self.actions_digest,
            "extractor_version": self.extractor_version,
            "handlers_digest": self.handlers_digest,
            "interface": self.interface,
            "localization_digest": self.localization_digest,
            "optimizer_schema_version": self.optimizer_schema_version,
            "props_digest": self.props_digest,
            "schema_version": self.schema_version,
            "stable_identity": self.stable_identity.to_dict(),
            "state_digest": self.state_digest,
            "structure_digest": self.structure_digest,
            "styles_digest": self.styles_digest,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any] | Any) -> UiComponentVersion:
        return decode_closed_record(
            cls,
            value,
            record_name="UiComponentVersion",
            builder=lambda p: cls(
                stable_identity=field_value(p, "stable_identity", {}),
                structure_digest=field_value(p, "structure_digest", ""),
                props_digest=field_value(p, "props_digest", ""),
                state_digest=field_value(p, "state_digest", ""),
                handlers_digest=field_value(p, "handlers_digest", ""),
                accessibility_digest=field_value(p, "accessibility_digest", ""),
                styles_digest=field_value(p, "styles_digest", ""),
                actions_digest=field_value(p, "actions_digest", ""),
                localization_digest=field_value(p, "localization_digest", ""),
                extractor_version=field_value(p, "extractor_version", ""),
                optimizer_schema_version=field_value(p, "optimizer_schema_version", ""),
                interface=field_value(p, "interface", ""),
                schema_version=field_value(p, "schema_version", ""),
            ),
        )


class UiDependencyEdge(_IdentityBase):
    INTERFACE = UI_DEPENDENCY_EDGE_INTERFACE
    SCHEMA_VERSION = UI_DEPENDENCY_EDGE_SCHEMA
    _FIELDS = frozenset(
        {
            "confidence",
            "extraction_method",
            "extractor_version",
            "interface",
            "notes",
            "relation",
            "schema_version",
            "source_component_id",
            "source_span",
            "target_component_id",
        }
    )
    __slots__ = (
        "source_component_id",
        "target_component_id",
        "relation",
        "extraction_method",
        "extractor_version",
        "confidence",
        "source_span",
        "notes",
        "interface",
        "schema_version",
    )

    def __init__(
        self,
        source_component_id: str,
        target_component_id: str,
        relation: Any,
        extraction_method: Any,
        extractor_version: str,
        confidence: Any,
        source_span: Any,
        notes: str,
        interface: str,
        schema_version: str,
    ) -> None:
        store_attrs(
            self,
            source_component_id=require_identifier(source_component_id, "source_component_id"),
            target_component_id=require_identifier(target_component_id, "target_component_id"),
            relation=parse_enum(relation, UiDependencyRelation, "relation"),
            extraction_method=parse_enum(extraction_method, ExtractionMethod, "extraction_method"),
            extractor_version=require_extractor_version(extractor_version),
            confidence=parse_enum(confidence, ExtractionConfidence, "confidence"),
            source_span=optional_nested_record(SourceSpan, source_span, "source_span"),
            notes=optional_text(notes, "notes"),
            interface=require_interface(interface, UI_DEPENDENCY_EDGE_INTERFACE),
            schema_version=require_schema_version(schema_version, UI_DEPENDENCY_EDGE_SCHEMA),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "confidence": self.confidence.value,
            "extraction_method": self.extraction_method.value,
            "extractor_version": self.extractor_version,
            "interface": self.interface,
            "notes": self.notes,
            "relation": self.relation.value,
            "schema_version": self.schema_version,
            "source_component_id": self.source_component_id,
            "source_span": None if self.source_span is None else self.source_span.to_dict(),
            "target_component_id": self.target_component_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any] | Any) -> UiDependencyEdge:
        return decode_closed_record(
            cls,
            value,
            record_name="UiDependencyEdge",
            builder=lambda p: cls(
                source_component_id=field_value(p, "source_component_id", ""),
                target_component_id=field_value(p, "target_component_id", ""),
                relation=field_value(p, "relation", ""),
                extraction_method=field_value(p, "extraction_method", ""),
                extractor_version=field_value(p, "extractor_version", ""),
                confidence=field_value(p, "confidence", ""),
                source_span=field_value(p, "source_span"),
                notes=field_value(p, "notes", ""),
                interface=field_value(p, "interface", ""),
                schema_version=field_value(p, "schema_version", ""),
            ),
        )


class UiStateDefinition(_IdentityBase):
    INTERFACE = UI_STATE_DEFINITION_INTERFACE
    SCHEMA_VERSION = UI_STATE_DEFINITION_SCHEMA
    _FIELDS = frozenset(
        {
            "description",
            "interface",
            "is_initial",
            "is_terminal",
            "kind",
            "label",
            "schema_version",
            "screen_id",
            "state_id",
        }
    )
    __slots__ = (
        "state_id",
        "kind",
        "screen_id",
        "label",
        "is_initial",
        "is_terminal",
        "description",
        "interface",
        "schema_version",
    )

    def __init__(
        self,
        state_id: str,
        kind: Any,
        screen_id: str,
        label: str,
        is_initial: bool,
        is_terminal: bool,
        description: str,
        interface: str,
        schema_version: str,
    ) -> None:
        store_attrs(
            self,
            state_id=require_identifier(state_id, "state_id"),
            kind=parse_enum(kind, UiStateKind, "kind"),
            screen_id=require_identifier(screen_id, "screen_id"),
            label=optional_text(label, "label"),
            is_initial=require_bool(is_initial, "is_initial"),
            is_terminal=require_bool(is_terminal, "is_terminal"),
            description=optional_text(description, "description"),
            interface=require_interface(interface, UI_STATE_DEFINITION_INTERFACE),
            schema_version=require_schema_version(schema_version, UI_STATE_DEFINITION_SCHEMA),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "description": self.description,
            "interface": self.interface,
            "is_initial": self.is_initial,
            "is_terminal": self.is_terminal,
            "kind": self.kind.value,
            "label": self.label,
            "schema_version": self.schema_version,
            "screen_id": self.screen_id,
            "state_id": self.state_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any] | Any) -> UiStateDefinition:
        return decode_closed_record(
            cls,
            value,
            record_name="UiStateDefinition",
            builder=lambda p: cls(
                state_id=field_value(p, "state_id", ""),
                kind=field_value(p, "kind", ""),
                screen_id=field_value(p, "screen_id", ""),
                label=field_value(p, "label", ""),
                is_initial=field_value(p, "is_initial", False),
                is_terminal=field_value(p, "is_terminal", False),
                description=field_value(p, "description", ""),
                interface=field_value(p, "interface", ""),
                schema_version=field_value(p, "schema_version", ""),
            ),
        )


class UiEventDefinition(_IdentityBase):
    INTERFACE = UI_EVENT_DEFINITION_INTERFACE
    SCHEMA_VERSION = UI_EVENT_DEFINITION_SCHEMA
    _FIELDS = frozenset(
        {"description", "event_id", "interface", "kind", "name", "schema_version"}
    )
    __slots__ = ("event_id", "kind", "name", "description", "interface", "schema_version")

    def __init__(
        self,
        event_id: str,
        kind: Any,
        name: str,
        description: str,
        interface: str,
        schema_version: str,
    ) -> None:
        store_attrs(
            self,
            event_id=require_identifier(event_id, "event_id"),
            kind=parse_enum(kind, UiEventKind, "kind"),
            name=require_text(name, "name"),
            description=optional_text(description, "description"),
            interface=require_interface(interface, UI_EVENT_DEFINITION_INTERFACE),
            schema_version=require_schema_version(schema_version, UI_EVENT_DEFINITION_SCHEMA),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "description": self.description,
            "event_id": self.event_id,
            "interface": self.interface,
            "kind": self.kind.value,
            "name": self.name,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any] | Any) -> UiEventDefinition:
        return decode_closed_record(
            cls,
            value,
            record_name="UiEventDefinition",
            builder=lambda p: cls(
                event_id=field_value(p, "event_id", ""),
                kind=field_value(p, "kind", ""),
                name=field_value(p, "name", ""),
                description=field_value(p, "description", ""),
                interface=field_value(p, "interface", ""),
                schema_version=field_value(p, "schema_version", ""),
            ),
        )


class UiTransitionDefinition(_IdentityBase):
    INTERFACE = UI_TRANSITION_DEFINITION_INTERFACE
    SCHEMA_VERSION = UI_TRANSITION_DEFINITION_SCHEMA
    _FIELDS = frozenset(
        {
            "effect_ids",
            "event_id",
            "from_state_id",
            "guard",
            "interface",
            "is_noop",
            "schema_version",
            "to_state_id",
            "transition_id",
        }
    )
    __slots__ = (
        "transition_id",
        "from_state_id",
        "to_state_id",
        "event_id",
        "guard",
        "effect_ids",
        "is_noop",
        "interface",
        "schema_version",
    )

    def __init__(
        self,
        transition_id: str,
        from_state_id: str,
        to_state_id: str,
        event_id: str,
        guard: str,
        effect_ids: Any,
        is_noop: bool,
        interface: str,
        schema_version: str,
    ) -> None:
        store_attrs(
            self,
            transition_id=require_identifier(transition_id, "transition_id"),
            from_state_id=require_identifier(from_state_id, "from_state_id"),
            to_state_id=require_identifier(to_state_id, "to_state_id"),
            event_id=require_identifier(event_id, "event_id"),
            guard=optional_text(guard, "guard"),
            effect_ids=unique_identifiers(effect_ids, "effect_ids"),
            is_noop=require_bool(is_noop, "is_noop"),
            interface=require_interface(interface, UI_TRANSITION_DEFINITION_INTERFACE),
            schema_version=require_schema_version(
                schema_version, UI_TRANSITION_DEFINITION_SCHEMA
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "effect_ids": list(self.effect_ids),
            "event_id": self.event_id,
            "from_state_id": self.from_state_id,
            "guard": self.guard,
            "interface": self.interface,
            "is_noop": self.is_noop,
            "schema_version": self.schema_version,
            "to_state_id": self.to_state_id,
            "transition_id": self.transition_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any] | Any) -> UiTransitionDefinition:
        return decode_closed_record(
            cls,
            value,
            record_name="UiTransitionDefinition",
            builder=lambda p: cls(
                transition_id=field_value(p, "transition_id", ""),
                from_state_id=field_value(p, "from_state_id", ""),
                to_state_id=field_value(p, "to_state_id", ""),
                event_id=field_value(p, "event_id", ""),
                guard=field_value(p, "guard", ""),
                effect_ids=field_value(p, "effect_ids", []),
                is_noop=field_value(p, "is_noop", False),
                interface=field_value(p, "interface", ""),
                schema_version=field_value(p, "schema_version", ""),
            ),
        )


class UiActionBinding(_IdentityBase):
    INTERFACE = UI_ACTION_BINDING_INTERFACE
    SCHEMA_VERSION = UI_ACTION_BINDING_SCHEMA
    _FIELDS = frozenset(
        {
            "action_id",
            "component_id",
            "confirmation_id",
            "depends_on_schema",
            "interface",
            "is_destructive",
            "method",
            "policy_id",
            "requires_confirmation",
            "schema_id",
            "schema_version",
        }
    )
    __slots__ = (
        "action_id",
        "method",
        "schema_id",
        "requires_confirmation",
        "confirmation_id",
        "policy_id",
        "depends_on_schema",
        "is_destructive",
        "component_id",
        "interface",
        "schema_version",
    )

    def __init__(
        self,
        action_id: str,
        method: str,
        schema_id: str,
        requires_confirmation: bool,
        confirmation_id: str,
        policy_id: str,
        depends_on_schema: bool,
        is_destructive: bool,
        component_id: str,
        interface: str,
        schema_version: str,
    ) -> None:
        conf = optional_identifier(confirmation_id, "confirmation_id")
        req = require_bool(requires_confirmation, "requires_confirmation")
        if req and not conf:
            raise GuiOptimizerDecodeError(
                "confirmation_id is required when requires_confirmation is true"
            )
        store_attrs(
            self,
            action_id=require_identifier(action_id, "action_id"),
            method=require_identifier(method, "method"),
            schema_id=require_identifier(schema_id, "schema_id"),
            requires_confirmation=req,
            confirmation_id=conf,
            policy_id=optional_identifier(policy_id, "policy_id"),
            depends_on_schema=require_bool(depends_on_schema, "depends_on_schema"),
            is_destructive=require_bool(is_destructive, "is_destructive"),
            component_id=optional_identifier(component_id, "component_id"),
            interface=require_interface(interface, UI_ACTION_BINDING_INTERFACE),
            schema_version=require_schema_version(schema_version, UI_ACTION_BINDING_SCHEMA),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "action_id": self.action_id,
            "component_id": self.component_id,
            "confirmation_id": self.confirmation_id,
            "depends_on_schema": self.depends_on_schema,
            "interface": self.interface,
            "is_destructive": self.is_destructive,
            "method": self.method,
            "policy_id": self.policy_id,
            "requires_confirmation": self.requires_confirmation,
            "schema_id": self.schema_id,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any] | Any) -> UiActionBinding:
        return decode_closed_record(
            cls,
            value,
            record_name="UiActionBinding",
            builder=lambda p: cls(
                action_id=field_value(p, "action_id", ""),
                method=field_value(p, "method", ""),
                schema_id=field_value(p, "schema_id", ""),
                requires_confirmation=field_value(p, "requires_confirmation", False),
                confirmation_id=field_value(p, "confirmation_id", ""),
                policy_id=field_value(p, "policy_id", ""),
                depends_on_schema=field_value(p, "depends_on_schema", False),
                is_destructive=field_value(p, "is_destructive", False),
                component_id=field_value(p, "component_id", ""),
                interface=field_value(p, "interface", ""),
                schema_version=field_value(p, "schema_version", ""),
            ),
        )


class UiLayoutConstraint(_IdentityBase):
    INTERFACE = UI_LAYOUT_CONSTRAINT_INTERFACE
    SCHEMA_VERSION = UI_LAYOUT_CONSTRAINT_SCHEMA
    _FIELDS = frozenset(
        {
            "breakpoint",
            "component_id",
            "constraint_id",
            "expression",
            "interface",
            "kind",
            "lower_bound",
            "schema_version",
            "upper_bound",
        }
    )
    __slots__ = (
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

    def __init__(
        self,
        constraint_id: str,
        kind: Any,
        expression: str,
        component_id: str,
        breakpoint_value: str,
        lower_bound: int | None,
        upper_bound: int | None,
        interface: str,
        schema_version: str,
    ) -> None:
        lower = require_int(lower_bound, "lower_bound")
        upper = require_int(upper_bound, "upper_bound")
        if lower > upper:
            raise GuiOptimizerDecodeError("lower_bound must not exceed upper_bound")
        store_attrs(
            self,
            constraint_id=require_identifier(constraint_id, "constraint_id"),
            kind=parse_enum(kind, LayoutConstraintKind, "kind"),
            expression=require_text(expression, "expression"),
            component_id=optional_identifier(component_id, "component_id"),
            breakpoint=optional_text(breakpoint_value, "breakpoint"),
            lower_bound=lower,
            upper_bound=upper,
            interface=require_interface(interface, UI_LAYOUT_CONSTRAINT_INTERFACE),
            schema_version=require_schema_version(schema_version, UI_LAYOUT_CONSTRAINT_SCHEMA),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "breakpoint": self.breakpoint,
            "component_id": self.component_id,
            "constraint_id": self.constraint_id,
            "expression": self.expression,
            "interface": self.interface,
            "kind": self.kind.value,
            "lower_bound": self.lower_bound,
            "schema_version": self.schema_version,
            "upper_bound": self.upper_bound,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any] | Any) -> UiLayoutConstraint:
        return decode_closed_record(
            cls,
            value,
            record_name="UiLayoutConstraint",
            builder=lambda p: cls(
                constraint_id=field_value(p, "constraint_id", ""),
                kind=field_value(p, "kind", ""),
                expression=field_value(p, "expression", ""),
                component_id=field_value(p, "component_id", ""),
                breakpoint_value=field_value(p, "breakpoint", ""),
                lower_bound=field_value(p, "lower_bound", None),
                upper_bound=field_value(p, "upper_bound", None),
                interface=field_value(p, "interface", ""),
                schema_version=field_value(p, "schema_version", ""),
            ),
        )


class UiAccessibilityContract(_IdentityBase):
    INTERFACE = UI_ACCESSIBILITY_CONTRACT_INTERFACE
    SCHEMA_VERSION = UI_ACCESSIBILITY_CONTRACT_SCHEMA
    _FIELDS = frozenset(
        {
            "component_id",
            "contract_id",
            "interface",
            "notes",
            "required_names",
            "required_roles",
            "requirement_kinds",
            "schema_version",
        }
    )
    __slots__ = (
        "contract_id",
        "requirement_kinds",
        "required_roles",
        "required_names",
        "component_id",
        "notes",
        "interface",
        "schema_version",
    )

    def __init__(
        self,
        contract_id: str,
        requirement_kinds: Any,
        required_roles: Any,
        required_names: Any,
        component_id: str,
        notes: str,
        interface: str,
        schema_version: str,
    ) -> None:
        kinds = parse_enum_sequence(
            requirement_kinds, AccessibilityRequirementKind, "requirement_kinds"
        )
        if not kinds:
            raise GuiOptimizerDecodeError(
                "requirement_kinds must contain at least one requirement"
            )
        store_attrs(
            self,
            contract_id=require_identifier(contract_id, "contract_id"),
            requirement_kinds=kinds,
            required_roles=unique_texts(required_roles, "required_roles"),
            required_names=unique_texts(required_names, "required_names"),
            component_id=optional_identifier(component_id, "component_id"),
            notes=optional_text(notes, "notes"),
            interface=require_interface(interface, UI_ACCESSIBILITY_CONTRACT_INTERFACE),
            schema_version=require_schema_version(
                schema_version, UI_ACCESSIBILITY_CONTRACT_SCHEMA
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "component_id": self.component_id,
            "contract_id": self.contract_id,
            "interface": self.interface,
            "notes": self.notes,
            "required_names": list(self.required_names),
            "required_roles": list(self.required_roles),
            "requirement_kinds": [item.value for item in self.requirement_kinds],
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any] | Any) -> UiAccessibilityContract:
        return decode_closed_record(
            cls,
            value,
            record_name="UiAccessibilityContract",
            builder=lambda p: cls(
                contract_id=field_value(p, "contract_id", ""),
                requirement_kinds=field_value(p, "requirement_kinds", []),
                required_roles=field_value(p, "required_roles", []),
                required_names=field_value(p, "required_names", []),
                component_id=field_value(p, "component_id", ""),
                notes=field_value(p, "notes", ""),
                interface=field_value(p, "interface", ""),
                schema_version=field_value(p, "schema_version", ""),
            ),
        )

class _FormalBase:
    INTERFACE: ClassVar[str]
    SCHEMA_VERSION: ClassVar[str]
    _FIELDS: ClassVar[frozenset[str]]

    def canonical_bytes(self) -> bytes:
        return canonical_model_bytes(self)

    def canonical_json(self) -> str:
        return canonical_model_json(self)


class UiContextSource(_FormalBase):
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


class UiContextStyle(_FormalBase):
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


class UiContextTest(_FormalBase):
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


class UiContextStateMachine(_FormalBase):
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


class UiContextFormalFailure(_FormalBase):
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


class UiContextAccessibilityViolation(_FormalBase):
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


class UiContextVisualReference(_FormalBase):
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


class UiContextScreenshotDescription(_FormalBase):
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


class UiContextRoute(_FormalBase):
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


class UiContextMetricBaseline(_FormalBase):
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
        closed = {
            key: require_int(item, f"metrics.{key}")
            for key, item in mapping.items()
        }
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


class UiContextPack(_FormalBase):
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

class _InvariantBase:
    INTERFACE: ClassVar[str]
    SCHEMA_VERSION: ClassVar[str]
    _FIELDS: ClassVar[frozenset[str]]

    def canonical_bytes(self) -> bytes:
        return canonical_model_bytes(self)

    def canonical_json(self) -> str:
        return canonical_model_json(self)


class UiSemanticCapsule(_InvariantBase):
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


class UiChangeSet(_InvariantBase):
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


class UiInvalidationPlan(_InvariantBase):
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


class UiEvaluationScenario(_InvariantBase):
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


class UiBaseline(_InvariantBase):
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

class _ReceiptBase:
    INTERFACE: ClassVar[str]
    SCHEMA_VERSION: ClassVar[str]
    _FIELDS: ClassVar[frozenset[str]]

    def canonical_bytes(self) -> bytes:
        return canonical_model_bytes(self)

    def canonical_json(self) -> str:
        return canonical_model_json(self)


def _pct(value: Any, name: str) -> float | int:
    number = require_finite_number(value, name)
    if float(number) < 0 or float(number) > 100:
        raise GuiOptimizerDecodeError(f"{name} must be in the closed range 0..100")
    return number


class GuiImprovementProposal(_ReceiptBase):
    INTERFACE = GUI_IMPROVEMENT_PROPOSAL_INTERFACE
    SCHEMA_VERSION = GUI_IMPROVEMENT_PROPOSAL_SCHEMA
    _FIELDS = frozenset(
        {
            "acceptance_criteria",
            "analysis_classification",
            "application_id",
            "context_pack_id",
            "decision",
            "expected_screenshot_ids",
            "expected_test_ids",
            "intended_component_ids",
            "intended_file_paths",
            "interface",
            "objective",
            "proposal_id",
            "route_kind",
            "schema_version",
            "screen_id",
            "state_effect_ids",
            "verification_status",
            "visual_effect_summary",
        }
    )
    __slots__ = (
        "proposal_id",
        "application_id",
        "screen_id",
        "objective",
        "intended_file_paths",
        "intended_component_ids",
        "acceptance_criteria",
        "expected_test_ids",
        "expected_screenshot_ids",
        "state_effect_ids",
        "visual_effect_summary",
        "route_kind",
        "context_pack_id",
        "decision",
        "analysis_classification",
        "verification_status",
        "interface",
        "schema_version",
    )

    def __init__(
        self,
        proposal_id: str,
        application_id: str,
        screen_id: str,
        objective: str,
        intended_file_paths: Any,
        intended_component_ids: Any,
        acceptance_criteria: Any,
        expected_test_ids: Any,
        expected_screenshot_ids: Any,
        state_effect_ids: Any,
        visual_effect_summary: str,
        route_kind: Any,
        context_pack_id: str,
        decision: Any,
        analysis_classification: Any,
        verification_status: Any,
        interface: str,
        schema_version: str,
    ) -> None:
        paths = unique_repo_paths(intended_file_paths, "intended_file_paths")
        if not paths:
            raise GuiOptimizerDecodeError("intended_file_paths must not be empty")
        components = unique_identifiers(intended_component_ids, "intended_component_ids")
        if not components:
            raise GuiOptimizerDecodeError("intended_component_ids must not be empty")
        criteria = unique_texts(acceptance_criteria, "acceptance_criteria")
        if not criteria:
            raise GuiOptimizerDecodeError("acceptance_criteria must not be empty")
        store_attrs(
            self,
            proposal_id=require_identifier(proposal_id, "proposal_id"),
            application_id=require_identifier(application_id, "application_id"),
            screen_id=require_identifier(screen_id, "screen_id"),
            objective=require_text(objective, "objective"),
            intended_file_paths=paths,
            intended_component_ids=components,
            acceptance_criteria=criteria,
            expected_test_ids=unique_identifiers(expected_test_ids, "expected_test_ids"),
            expected_screenshot_ids=unique_identifiers(
                expected_screenshot_ids, "expected_screenshot_ids"
            ),
            state_effect_ids=unique_identifiers(state_effect_ids, "state_effect_ids"),
            visual_effect_summary=optional_text(visual_effect_summary, "visual_effect_summary"),
            route_kind=parse_enum(route_kind, ProposalRouteKind, "route_kind"),
            context_pack_id=optional_identifier(context_pack_id, "context_pack_id"),
            decision=parse_enum(decision, ProposalDecision, "decision"),
            analysis_classification=parse_enum(
                analysis_classification, AnalysisClassification, "analysis_classification"
            ),
            verification_status=parse_enum(
                verification_status, VerificationStatus, "verification_status"
            ),
            interface=require_interface(interface, GUI_IMPROVEMENT_PROPOSAL_INTERFACE),
            schema_version=require_schema_version(
                schema_version, GUI_IMPROVEMENT_PROPOSAL_SCHEMA
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "acceptance_criteria": list(self.acceptance_criteria),
            "analysis_classification": self.analysis_classification.value,
            "application_id": self.application_id,
            "context_pack_id": self.context_pack_id,
            "decision": self.decision.value,
            "expected_screenshot_ids": list(self.expected_screenshot_ids),
            "expected_test_ids": list(self.expected_test_ids),
            "intended_component_ids": list(self.intended_component_ids),
            "intended_file_paths": list(self.intended_file_paths),
            "interface": self.interface,
            "objective": self.objective,
            "proposal_id": self.proposal_id,
            "route_kind": self.route_kind.value,
            "schema_version": self.schema_version,
            "screen_id": self.screen_id,
            "state_effect_ids": list(self.state_effect_ids),
            "verification_status": self.verification_status.value,
            "visual_effect_summary": self.visual_effect_summary,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any] | Any) -> GuiImprovementProposal:
        return decode_closed_record(
            cls,
            value,
            record_name="GuiImprovementProposal",
            builder=lambda p: cls(
                proposal_id=field_value(p, "proposal_id", ""),
                application_id=field_value(p, "application_id", ""),
                screen_id=field_value(p, "screen_id", ""),
                objective=field_value(p, "objective", ""),
                intended_file_paths=field_value(p, "intended_file_paths", []),
                intended_component_ids=field_value(p, "intended_component_ids", []),
                acceptance_criteria=field_value(p, "acceptance_criteria", []),
                expected_test_ids=field_value(p, "expected_test_ids", []),
                expected_screenshot_ids=field_value(p, "expected_screenshot_ids", []),
                state_effect_ids=field_value(p, "state_effect_ids", []),
                visual_effect_summary=field_value(p, "visual_effect_summary", ""),
                route_kind=field_value(p, "route_kind", ""),
                context_pack_id=field_value(p, "context_pack_id", ""),
                decision=field_value(p, "decision", "pending"),
                analysis_classification=field_value(p, "analysis_classification", ""),
                verification_status=field_value(p, "verification_status", ""),
                interface=field_value(p, "interface", ""),
                schema_version=field_value(p, "schema_version", ""),
            ),
        )


class VisualRegressionReceipt(_ReceiptBase):
    INTERFACE = VISUAL_REGRESSION_RECEIPT_INTERFACE
    SCHEMA_VERSION = VISUAL_REGRESSION_RECEIPT_SCHEMA
    _FIELDS = frozenset(
        {
            "analysis_classification",
            "application_id",
            "baseline_digest",
            "browser",
            "browser_version",
            "color_scheme",
            "component_version_ids",
            "decision",
            "evidence_level",
            "expected_change_regions",
            "extra_control_count",
            "forbidden_change_regions",
            "interface",
            "locale",
            "manual_review_threshold_percent",
            "max_unexplained_diff_percent",
            "missing_control_count",
            "pixel_diff_percent",
            "receipt_id",
            "repository_revision",
            "requires_human_review",
            "scenario_id",
            "schema_version",
            "screen_id",
            "screenshot_digest",
            "screenshot_height",
            "screenshot_width",
            "structural_diff_percent",
            "text_scale_percent",
            "unexpected_layout_shift_count",
            "verification_status",
            "viewport",
        }
    )
    __slots__ = tuple(sorted(_FIELDS))

    def __init__(self, **kwargs: Any) -> None:
        decision = parse_enum(kwargs["decision"], VisualDecision, "decision")
        requires_review = require_bool(
            kwargs["requires_human_review"], "requires_human_review"
        )
        browser = optional_text(kwargs.get("browser", ""), "browser")
        browser_version = optional_text(
            kwargs.get("browser_version", ""), "browser_version"
        )
        if not browser or not browser_version:
            raise GuiOptimizerDecodeError("browser and browser_version must be nonempty")
        pixel = _pct(kwargs["pixel_diff_percent"], "pixel_diff_percent")
        structural = _pct(kwargs["structural_diff_percent"], "structural_diff_percent")
        max_unexplained = _pct(
            kwargs["max_unexplained_diff_percent"], "max_unexplained_diff_percent"
        )
        manual_threshold = _pct(
            kwargs["manual_review_threshold_percent"],
            "manual_review_threshold_percent",
        )
        if decision is VisualDecision.PASS and requires_review:
            raise GuiOptimizerDecodeError("PASS visual receipt cannot require human review")
        if decision is VisualDecision.REVIEW and not requires_review:
            raise GuiOptimizerDecodeError("REVIEW visual receipt requires human review")
        if decision is VisualDecision.PASS and float(pixel) > float(max_unexplained):
            raise GuiOptimizerDecodeError(
                "pixel_diff_percent exceeds max_unexplained_diff_percent but decision is pass"
            )
        if float(pixel) >= float(manual_threshold) and not requires_review:
            raise GuiOptimizerDecodeError(
                "pixel_diff_percent at/above manual_review_threshold_percent requires human review"
            )
        expected = nested_record_list(
            VisualChangeRegion,
            kwargs["expected_change_regions"],
            "expected_change_regions",
        )
        forbidden = nested_record_list(
            VisualChangeRegion,
            kwargs["forbidden_change_regions"],
            "forbidden_change_regions",
        )
        expected_ids = [item.region_id for item in expected]
        forbidden_ids = [item.region_id for item in forbidden]
        if len(expected_ids) != len(set(expected_ids)):
            raise GuiOptimizerDecodeError("expected_change_regions region_ids must be unique")
        if len(forbidden_ids) != len(set(forbidden_ids)):
            raise GuiOptimizerDecodeError("forbidden_change_regions region_ids must be unique")
        overlap_ids = sorted(set(expected_ids) & set(forbidden_ids))
        if overlap_ids:
            raise GuiOptimizerDecodeError(
                "expected and forbidden region IDs must be disjoint"
            )
        for left in expected:
            for right in forbidden:
                if left.overlaps(right):
                    raise GuiOptimizerDecodeError(
                        "expected and forbidden regions geometrically overlap"
                    )
        store_attrs(
            self,
            receipt_id=require_identifier(kwargs["receipt_id"], "receipt_id"),
            application_id=require_identifier(kwargs["application_id"], "application_id"),
            screen_id=require_identifier(kwargs["screen_id"], "screen_id"),
            scenario_id=require_identifier(kwargs["scenario_id"], "scenario_id"),
            repository_revision=require_text(
                kwargs["repository_revision"], "repository_revision"
            ),
            component_version_ids=unique_identifiers(
                kwargs["component_version_ids"], "component_version_ids"
            ),
            viewport=decode_nested_record(ViewportSpec, kwargs["viewport"], "viewport"),
            screenshot_digest=require_digest(kwargs["screenshot_digest"], "screenshot_digest"),
            baseline_digest=require_digest(kwargs["baseline_digest"], "baseline_digest"),
            decision=decision,
            evidence_level=parse_enum(kwargs["evidence_level"], EvidenceLevel, "evidence_level"),
            pixel_diff_percent=pixel,
            structural_diff_percent=structural,
            unexpected_layout_shift_count=require_int(
                kwargs["unexpected_layout_shift_count"],
                "unexpected_layout_shift_count",
                minimum=0,
            ),
            missing_control_count=require_int(
                kwargs["missing_control_count"], "missing_control_count", minimum=0
            ),
            extra_control_count=require_int(
                kwargs["extra_control_count"], "extra_control_count", minimum=0
            ),
            screenshot_width=require_int(
                kwargs["screenshot_width"], "screenshot_width", minimum=1
            ),
            screenshot_height=require_int(
                kwargs["screenshot_height"], "screenshot_height", minimum=1
            ),
            expected_change_regions=expected,
            forbidden_change_regions=forbidden,
            max_unexplained_diff_percent=max_unexplained,
            manual_review_threshold_percent=manual_threshold,
            requires_human_review=requires_review,
            color_scheme=require_text(kwargs["color_scheme"], "color_scheme"),
            locale=require_text(kwargs["locale"], "locale"),
            text_scale_percent=require_int(
                kwargs["text_scale_percent"], "text_scale_percent", minimum=25, maximum=500
            ),
            browser=browser,
            browser_version=browser_version,
            analysis_classification=parse_enum(
                kwargs["analysis_classification"],
                AnalysisClassification,
                "analysis_classification",
            ),
            verification_status=parse_enum(
                kwargs["verification_status"], VerificationStatus, "verification_status"
            ),
            interface=require_interface(
                kwargs["interface"], VISUAL_REGRESSION_RECEIPT_INTERFACE
            ),
            schema_version=require_schema_version(
                kwargs["schema_version"], VISUAL_REGRESSION_RECEIPT_SCHEMA
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "analysis_classification": self.analysis_classification.value,
            "application_id": self.application_id,
            "baseline_digest": self.baseline_digest,
            "browser": self.browser,
            "browser_version": self.browser_version,
            "color_scheme": self.color_scheme,
            "component_version_ids": list(self.component_version_ids),
            "decision": self.decision.value,
            "evidence_level": self.evidence_level.value,
            "expected_change_regions": [i.to_dict() for i in self.expected_change_regions],
            "extra_control_count": self.extra_control_count,
            "forbidden_change_regions": [i.to_dict() for i in self.forbidden_change_regions],
            "interface": self.interface,
            "locale": self.locale,
            "manual_review_threshold_percent": self.manual_review_threshold_percent,
            "max_unexplained_diff_percent": self.max_unexplained_diff_percent,
            "missing_control_count": self.missing_control_count,
            "pixel_diff_percent": self.pixel_diff_percent,
            "receipt_id": self.receipt_id,
            "repository_revision": self.repository_revision,
            "requires_human_review": self.requires_human_review,
            "scenario_id": self.scenario_id,
            "schema_version": self.schema_version,
            "screen_id": self.screen_id,
            "screenshot_digest": self.screenshot_digest,
            "screenshot_height": self.screenshot_height,
            "screenshot_width": self.screenshot_width,
            "structural_diff_percent": self.structural_diff_percent,
            "text_scale_percent": self.text_scale_percent,
            "unexpected_layout_shift_count": self.unexpected_layout_shift_count,
            "verification_status": self.verification_status.value,
            "viewport": self.viewport.to_dict(),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any] | Any) -> VisualRegressionReceipt:
        return decode_closed_record(
            cls,
            value,
            record_name="VisualRegressionReceipt",
            builder=lambda p: cls(
                receipt_id=field_value(p, "receipt_id", ""),
                application_id=field_value(p, "application_id", ""),
                screen_id=field_value(p, "screen_id", ""),
                scenario_id=field_value(p, "scenario_id", ""),
                repository_revision=field_value(p, "repository_revision", ""),
                component_version_ids=field_value(p, "component_version_ids", []),
                viewport=field_value(p, "viewport", {}),
                screenshot_digest=field_value(p, "screenshot_digest", ""),
                baseline_digest=field_value(p, "baseline_digest", ""),
                decision=field_value(p, "decision", ""),
                evidence_level=field_value(p, "evidence_level", ""),
                pixel_diff_percent=field_value(p, "pixel_diff_percent", 0.0),
                structural_diff_percent=field_value(p, "structural_diff_percent", 0.0),
                unexpected_layout_shift_count=field_value(
                    p, "unexpected_layout_shift_count", 0
                ),
                missing_control_count=field_value(p, "missing_control_count", 0),
                extra_control_count=field_value(p, "extra_control_count", 0),
                screenshot_width=field_value(p, "screenshot_width", 0),
                screenshot_height=field_value(p, "screenshot_height", 0),
                expected_change_regions=field_value(p, "expected_change_regions", []),
                forbidden_change_regions=field_value(p, "forbidden_change_regions", []),
                max_unexplained_diff_percent=field_value(
                    p, "max_unexplained_diff_percent", 100.0
                ),
                manual_review_threshold_percent=field_value(
                    p, "manual_review_threshold_percent", 100.0
                ),
                requires_human_review=field_value(p, "requires_human_review", False),
                color_scheme=field_value(p, "color_scheme", "light"),
                locale=field_value(p, "locale", "en-US"),
                text_scale_percent=field_value(p, "text_scale_percent", 100),
                browser=field_value(p, "browser", ""),
                browser_version=field_value(p, "browser_version", ""),
                analysis_classification=field_value(p, "analysis_classification", ""),
                verification_status=field_value(p, "verification_status", ""),
                interface=field_value(p, "interface", ""),
                schema_version=field_value(p, "schema_version", ""),
            ),
        )


class AccessibilityReceipt(_ReceiptBase):
    INTERFACE = ACCESSIBILITY_RECEIPT_INTERFACE
    SCHEMA_VERSION = ACCESSIBILITY_RECEIPT_SCHEMA
    _FIELDS = frozenset(
        {
            "analysis_classification",
            "application_id",
            "automated_pass_count",
            "evidence_level",
            "interface",
            "keyboard_result",
            "manual_check_ids",
            "receipt_id",
            "repository_revision",
            "scenario_id",
            "schema_version",
            "screen_id",
            "screen_reader_reviewed",
            "unsupported_criteria",
            "verification_status",
            "violation_count",
            "violation_ids",
        }
    )
    __slots__ = tuple(sorted(_FIELDS))

    def __init__(self, **kwargs: Any) -> None:
        violation_ids = unique_identifiers(kwargs["violation_ids"], "violation_ids")
        violation_count = require_int(kwargs["violation_count"], "violation_count", minimum=0)
        if violation_count != len(violation_ids):
            raise GuiOptimizerDecodeError(
                "violation_count must equal len(violation_ids)"
            )
        store_attrs(
            self,
            receipt_id=require_identifier(kwargs["receipt_id"], "receipt_id"),
            application_id=require_identifier(kwargs["application_id"], "application_id"),
            screen_id=require_identifier(kwargs["screen_id"], "screen_id"),
            scenario_id=require_identifier(kwargs["scenario_id"], "scenario_id"),
            repository_revision=require_text(
                kwargs["repository_revision"], "repository_revision"
            ),
            automated_pass_count=require_int(
                kwargs["automated_pass_count"], "automated_pass_count", minimum=0
            ),
            violation_count=violation_count,
            violation_ids=violation_ids,
            manual_check_ids=unique_identifiers(
                kwargs["manual_check_ids"], "manual_check_ids"
            ),
            unsupported_criteria=unique_texts(
                kwargs["unsupported_criteria"], "unsupported_criteria"
            ),
            keyboard_result=parse_enum(
                kwargs["keyboard_result"], ConstraintCheckStatus, "keyboard_result"
            ),
            screen_reader_reviewed=require_bool(
                kwargs["screen_reader_reviewed"], "screen_reader_reviewed"
            ),
            evidence_level=parse_enum(
                kwargs["evidence_level"], EvidenceLevel, "evidence_level"
            ),
            analysis_classification=parse_enum(
                kwargs["analysis_classification"],
                AnalysisClassification,
                "analysis_classification",
            ),
            verification_status=parse_enum(
                kwargs["verification_status"], VerificationStatus, "verification_status"
            ),
            interface=require_interface(kwargs["interface"], ACCESSIBILITY_RECEIPT_INTERFACE),
            schema_version=require_schema_version(
                kwargs["schema_version"], ACCESSIBILITY_RECEIPT_SCHEMA
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "analysis_classification": self.analysis_classification.value,
            "application_id": self.application_id,
            "automated_pass_count": self.automated_pass_count,
            "evidence_level": self.evidence_level.value,
            "interface": self.interface,
            "keyboard_result": self.keyboard_result.value,
            "manual_check_ids": list(self.manual_check_ids),
            "receipt_id": self.receipt_id,
            "repository_revision": self.repository_revision,
            "scenario_id": self.scenario_id,
            "schema_version": self.schema_version,
            "screen_id": self.screen_id,
            "screen_reader_reviewed": self.screen_reader_reviewed,
            "unsupported_criteria": list(self.unsupported_criteria),
            "verification_status": self.verification_status.value,
            "violation_count": self.violation_count,
            "violation_ids": list(self.violation_ids),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any] | Any) -> AccessibilityReceipt:
        return decode_closed_record(
            cls,
            value,
            record_name="AccessibilityReceipt",
            builder=lambda p: cls(
                receipt_id=field_value(p, "receipt_id", ""),
                application_id=field_value(p, "application_id", ""),
                screen_id=field_value(p, "screen_id", ""),
                scenario_id=field_value(p, "scenario_id", ""),
                repository_revision=field_value(p, "repository_revision", ""),
                automated_pass_count=field_value(p, "automated_pass_count", 0),
                violation_count=field_value(p, "violation_count", 0),
                violation_ids=field_value(p, "violation_ids", []),
                manual_check_ids=field_value(p, "manual_check_ids", []),
                unsupported_criteria=field_value(p, "unsupported_criteria", []),
                keyboard_result=field_value(p, "keyboard_result", ""),
                screen_reader_reviewed=field_value(p, "screen_reader_reviewed", False),
                evidence_level=field_value(p, "evidence_level", ""),
                analysis_classification=field_value(p, "analysis_classification", ""),
                verification_status=field_value(p, "verification_status", ""),
                interface=field_value(p, "interface", ""),
                schema_version=field_value(p, "schema_version", ""),
            ),
        )


class InteractionReceipt(_ReceiptBase):
    INTERFACE = INTERACTION_RECEIPT_INTERFACE
    SCHEMA_VERSION = INTERACTION_RECEIPT_SCHEMA
    _FIELDS = frozenset(
        {
            "action_invocation_ids",
            "analysis_classification",
            "application_id",
            "confirmation_id",
            "event_ids",
            "evidence_level",
            "focus_sequence",
            "interface",
            "receipt_id",
            "recovery_ids",
            "repository_revision",
            "scenario_id",
            "schema_version",
            "screen_id",
            "step_ids",
            "unresolved_observation_ids",
            "verification_status",
        }
    )
    __slots__ = tuple(sorted(_FIELDS))

    def __init__(self, **kwargs: Any) -> None:
        store_attrs(
            self,
            receipt_id=require_identifier(kwargs["receipt_id"], "receipt_id"),
            application_id=require_identifier(kwargs["application_id"], "application_id"),
            screen_id=require_identifier(kwargs["screen_id"], "screen_id"),
            scenario_id=require_identifier(kwargs["scenario_id"], "scenario_id"),
            repository_revision=require_text(
                kwargs["repository_revision"], "repository_revision"
            ),
            step_ids=unique_identifiers(kwargs["step_ids"], "step_ids"),
            focus_sequence=unique_texts(kwargs["focus_sequence"], "focus_sequence"),
            event_ids=unique_identifiers(kwargs["event_ids"], "event_ids"),
            action_invocation_ids=unique_identifiers(
                kwargs["action_invocation_ids"], "action_invocation_ids"
            ),
            confirmation_id=optional_identifier(
                kwargs.get("confirmation_id", ""), "confirmation_id"
            ),
            recovery_ids=unique_identifiers(kwargs["recovery_ids"], "recovery_ids"),
            unresolved_observation_ids=unique_identifiers(
                kwargs["unresolved_observation_ids"], "unresolved_observation_ids"
            ),
            evidence_level=parse_enum(
                kwargs["evidence_level"], EvidenceLevel, "evidence_level"
            ),
            analysis_classification=parse_enum(
                kwargs["analysis_classification"],
                AnalysisClassification,
                "analysis_classification",
            ),
            verification_status=parse_enum(
                kwargs["verification_status"], VerificationStatus, "verification_status"
            ),
            interface=require_interface(kwargs["interface"], INTERACTION_RECEIPT_INTERFACE),
            schema_version=require_schema_version(
                kwargs["schema_version"], INTERACTION_RECEIPT_SCHEMA
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "action_invocation_ids": list(self.action_invocation_ids),
            "analysis_classification": self.analysis_classification.value,
            "application_id": self.application_id,
            "confirmation_id": self.confirmation_id,
            "event_ids": list(self.event_ids),
            "evidence_level": self.evidence_level.value,
            "focus_sequence": list(self.focus_sequence),
            "interface": self.interface,
            "receipt_id": self.receipt_id,
            "recovery_ids": list(self.recovery_ids),
            "repository_revision": self.repository_revision,
            "scenario_id": self.scenario_id,
            "schema_version": self.schema_version,
            "screen_id": self.screen_id,
            "step_ids": list(self.step_ids),
            "unresolved_observation_ids": list(self.unresolved_observation_ids),
            "verification_status": self.verification_status.value,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any] | Any) -> InteractionReceipt:
        return decode_closed_record(
            cls,
            value,
            record_name="InteractionReceipt",
            builder=lambda p: cls(
                receipt_id=field_value(p, "receipt_id", ""),
                application_id=field_value(p, "application_id", ""),
                screen_id=field_value(p, "screen_id", ""),
                scenario_id=field_value(p, "scenario_id", ""),
                repository_revision=field_value(p, "repository_revision", ""),
                step_ids=field_value(p, "step_ids", []),
                focus_sequence=field_value(p, "focus_sequence", []),
                event_ids=field_value(p, "event_ids", []),
                action_invocation_ids=field_value(p, "action_invocation_ids", []),
                confirmation_id=field_value(p, "confirmation_id", ""),
                recovery_ids=field_value(p, "recovery_ids", []),
                unresolved_observation_ids=field_value(
                    p, "unresolved_observation_ids", []
                ),
                evidence_level=field_value(p, "evidence_level", ""),
                analysis_classification=field_value(p, "analysis_classification", ""),
                verification_status=field_value(p, "verification_status", ""),
                interface=field_value(p, "interface", ""),
                schema_version=field_value(p, "schema_version", ""),
            ),
        )


class UiConstraintReceipt(_ReceiptBase):
    INTERFACE = UI_CONSTRAINT_RECEIPT_INTERFACE
    SCHEMA_VERSION = UI_CONSTRAINT_RECEIPT_SCHEMA
    _FIELDS = frozenset(
        {
            "analysis_classification",
            "application_id",
            "check_ids",
            "evidence_level",
            "interface",
            "receipt_id",
            "repository_revision",
            "schema_version",
            "screen_id",
            "solver_id",
            "statuses",
            "unsupported_check_ids",
            "verification_status",
            "violated_check_ids",
        }
    )
    __slots__ = tuple(sorted(_FIELDS))

    def __init__(self, **kwargs: Any) -> None:
        check_ids = unique_identifiers(kwargs["check_ids"], "check_ids")
        statuses = parse_enum_sequence(
            kwargs["statuses"], ConstraintCheckStatus, "statuses"
        )
        if len(check_ids) != len(statuses):
            raise GuiOptimizerDecodeError("check_ids and statuses lengths must agree")
        expected_violated = tuple(
            check_id
            for check_id, status in zip(check_ids, statuses, strict=True)
            if status is ConstraintCheckStatus.VIOLATED
        )
        expected_unsupported = tuple(
            check_id
            for check_id, status in zip(check_ids, statuses, strict=True)
            if status is ConstraintCheckStatus.UNSUPPORTED
        )
        violated = unique_identifiers(kwargs["violated_check_ids"], "violated_check_ids")
        unsupported = unique_identifiers(
            kwargs["unsupported_check_ids"], "unsupported_check_ids"
        )
        if violated != expected_violated:
            raise GuiOptimizerDecodeError(
                "violated_check_ids must exactly match statuses"
            )
        if unsupported != expected_unsupported:
            raise GuiOptimizerDecodeError(
                "unsupported_check_ids must exactly match statuses"
            )
        store_attrs(
            self,
            receipt_id=require_identifier(kwargs["receipt_id"], "receipt_id"),
            application_id=require_identifier(kwargs["application_id"], "application_id"),
            screen_id=require_identifier(kwargs["screen_id"], "screen_id"),
            repository_revision=require_text(
                kwargs["repository_revision"], "repository_revision"
            ),
            check_ids=check_ids,
            statuses=statuses,
            violated_check_ids=violated,
            unsupported_check_ids=unsupported,
            solver_id=optional_identifier(kwargs.get("solver_id", ""), "solver_id"),
            evidence_level=parse_enum(
                kwargs["evidence_level"], EvidenceLevel, "evidence_level"
            ),
            analysis_classification=parse_enum(
                kwargs["analysis_classification"],
                AnalysisClassification,
                "analysis_classification",
            ),
            verification_status=parse_enum(
                kwargs["verification_status"], VerificationStatus, "verification_status"
            ),
            interface=require_interface(kwargs["interface"], UI_CONSTRAINT_RECEIPT_INTERFACE),
            schema_version=require_schema_version(
                kwargs["schema_version"], UI_CONSTRAINT_RECEIPT_SCHEMA
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "analysis_classification": self.analysis_classification.value,
            "application_id": self.application_id,
            "check_ids": list(self.check_ids),
            "evidence_level": self.evidence_level.value,
            "interface": self.interface,
            "receipt_id": self.receipt_id,
            "repository_revision": self.repository_revision,
            "schema_version": self.schema_version,
            "screen_id": self.screen_id,
            "solver_id": self.solver_id,
            "statuses": [item.value for item in self.statuses],
            "unsupported_check_ids": list(self.unsupported_check_ids),
            "verification_status": self.verification_status.value,
            "violated_check_ids": list(self.violated_check_ids),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any] | Any) -> UiConstraintReceipt:
        return decode_closed_record(
            cls,
            value,
            record_name="UiConstraintReceipt",
            builder=lambda p: cls(
                receipt_id=field_value(p, "receipt_id", ""),
                application_id=field_value(p, "application_id", ""),
                screen_id=field_value(p, "screen_id", ""),
                repository_revision=field_value(p, "repository_revision", ""),
                check_ids=field_value(p, "check_ids", []),
                statuses=field_value(p, "statuses", []),
                violated_check_ids=field_value(p, "violated_check_ids", []),
                unsupported_check_ids=field_value(p, "unsupported_check_ids", []),
                solver_id=field_value(p, "solver_id", ""),
                evidence_level=field_value(p, "evidence_level", ""),
                analysis_classification=field_value(p, "analysis_classification", ""),
                verification_status=field_value(p, "verification_status", ""),
                interface=field_value(p, "interface", ""),
                schema_version=field_value(p, "schema_version", ""),
            ),
        )


class GuiImprovementReceipt(_ReceiptBase):
    INTERFACE = GUI_IMPROVEMENT_RECEIPT_INTERFACE
    SCHEMA_VERSION = GUI_IMPROVEMENT_RECEIPT_SCHEMA
    _FIELDS = frozenset(
        {
            "accessibility_receipt_ids",
            "analysis_classification",
            "application_id",
            "constraint_receipt_ids",
            "context_pack_id",
            "decision",
            "interaction_receipt_ids",
            "interface",
            "invalidation_plan_id",
            "patch_digest",
            "proposal_id",
            "receipt_id",
            "rejection_reasons",
            "repository_revision",
            "schema_version",
            "screen_id",
            "verification_status",
            "visual_receipt_ids",
        }
    )
    __slots__ = tuple(sorted(_FIELDS))

    def __init__(self, **kwargs: Any) -> None:
        decision = parse_enum(kwargs["decision"], ProposalDecision, "decision")
        verification = parse_enum(
            kwargs["verification_status"], VerificationStatus, "verification_status"
        )
        invalidation_plan_id = optional_identifier(
            kwargs.get("invalidation_plan_id", ""), "invalidation_plan_id"
        )
        context_pack_id = optional_identifier(
            kwargs.get("context_pack_id", ""), "context_pack_id"
        )
        patch_digest = optional_digest(kwargs.get("patch_digest", ""), "patch_digest")
        visual = unique_identifiers(kwargs["visual_receipt_ids"], "visual_receipt_ids")
        a11y = unique_identifiers(
            kwargs["accessibility_receipt_ids"], "accessibility_receipt_ids"
        )
        interaction = unique_identifiers(
            kwargs["interaction_receipt_ids"], "interaction_receipt_ids"
        )
        constraint = unique_identifiers(
            kwargs["constraint_receipt_ids"], "constraint_receipt_ids"
        )
        reasons = unique_texts(kwargs["rejection_reasons"], "rejection_reasons")
        if decision is ProposalDecision.ACCEPT:
            if verification not in (
                VerificationStatus.VERIFIED,
                VerificationStatus.INTEGRITY_VALID,
            ):
                raise GuiOptimizerDecodeError(
                    "accepted receipt requires verified or integrity_valid status"
                )
            if not invalidation_plan_id or not context_pack_id or not patch_digest:
                raise GuiOptimizerDecodeError(
                    "accepted receipt requires nonempty invalidation_plan_id, "
                    "context_pack_id, and patch_digest"
                )
            if not visual or not a11y or not interaction or not constraint:
                raise GuiOptimizerDecodeError(
                    "accepted receipt requires nonempty evidence receipt lists"
                )
            if reasons:
                raise GuiOptimizerDecodeError(
                    "accepted receipt cannot carry rejection reasons"
                )
        if decision is ProposalDecision.REJECT and not reasons:
            raise GuiOptimizerDecodeError(
                "rejected receipt requires nonempty rejection reasons"
            )
        store_attrs(
            self,
            receipt_id=require_identifier(kwargs["receipt_id"], "receipt_id"),
            proposal_id=require_identifier(kwargs["proposal_id"], "proposal_id"),
            application_id=require_identifier(kwargs["application_id"], "application_id"),
            screen_id=require_identifier(kwargs["screen_id"], "screen_id"),
            repository_revision=require_text(
                kwargs["repository_revision"], "repository_revision"
            ),
            decision=decision,
            visual_receipt_ids=visual,
            accessibility_receipt_ids=a11y,
            interaction_receipt_ids=interaction,
            constraint_receipt_ids=constraint,
            invalidation_plan_id=invalidation_plan_id,
            context_pack_id=context_pack_id,
            patch_digest=patch_digest,
            rejection_reasons=reasons,
            analysis_classification=parse_enum(
                kwargs["analysis_classification"],
                AnalysisClassification,
                "analysis_classification",
            ),
            verification_status=verification,
            interface=require_interface(
                kwargs["interface"], GUI_IMPROVEMENT_RECEIPT_INTERFACE
            ),
            schema_version=require_schema_version(
                kwargs["schema_version"], GUI_IMPROVEMENT_RECEIPT_SCHEMA
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "accessibility_receipt_ids": list(self.accessibility_receipt_ids),
            "analysis_classification": self.analysis_classification.value,
            "application_id": self.application_id,
            "constraint_receipt_ids": list(self.constraint_receipt_ids),
            "context_pack_id": self.context_pack_id,
            "decision": self.decision.value,
            "interaction_receipt_ids": list(self.interaction_receipt_ids),
            "interface": self.interface,
            "invalidation_plan_id": self.invalidation_plan_id,
            "patch_digest": self.patch_digest,
            "proposal_id": self.proposal_id,
            "receipt_id": self.receipt_id,
            "rejection_reasons": list(self.rejection_reasons),
            "repository_revision": self.repository_revision,
            "schema_version": self.schema_version,
            "screen_id": self.screen_id,
            "verification_status": self.verification_status.value,
            "visual_receipt_ids": list(self.visual_receipt_ids),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any] | Any) -> GuiImprovementReceipt:
        return decode_closed_record(
            cls,
            value,
            record_name="GuiImprovementReceipt",
            builder=lambda p: cls(
                receipt_id=field_value(p, "receipt_id", ""),
                proposal_id=field_value(p, "proposal_id", ""),
                application_id=field_value(p, "application_id", ""),
                screen_id=field_value(p, "screen_id", ""),
                repository_revision=field_value(p, "repository_revision", ""),
                decision=field_value(p, "decision", ""),
                visual_receipt_ids=field_value(p, "visual_receipt_ids", []),
                accessibility_receipt_ids=field_value(
                    p, "accessibility_receipt_ids", []
                ),
                interaction_receipt_ids=field_value(p, "interaction_receipt_ids", []),
                constraint_receipt_ids=field_value(p, "constraint_receipt_ids", []),
                invalidation_plan_id=field_value(p, "invalidation_plan_id", ""),
                context_pack_id=field_value(p, "context_pack_id", ""),
                patch_digest=field_value(p, "patch_digest", ""),
                rejection_reasons=field_value(p, "rejection_reasons", []),
                analysis_classification=field_value(p, "analysis_classification", ""),
                verification_status=field_value(p, "verification_status", ""),
                interface=field_value(p, "interface", ""),
                schema_version=field_value(p, "schema_version", ""),
            ),
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
