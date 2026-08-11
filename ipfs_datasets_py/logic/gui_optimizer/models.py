"""Versioned, closed GUI optimizer wire models (VGO-001).

Every required model is:

* versioned (``interface`` + ``schema_version``);
* deterministically serializable (canonical JSON profile);
* fail-closed on unknown fields, invalid enums, and unsupported versions;
* free of imports from semantic-index, semantic-capsule, proof-cache,
  model-routing, or the untracked datasets UI/UX IR tree.

Analysis classification and verification status are independent fields and
must never be collapsed into a single authority signal.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Any, ClassVar, Final, TypeVar

from .schema import (
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
    REQUIRED_MODEL_INTERFACES,
    SCHEMA_VERSION_BY_INTERFACE,
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
    UI_CONTEXT_PACK_INTERFACE,
    UI_CONTEXT_PACK_SCHEMA,
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
    VIEWPORT_SPEC_SCHEMA,
    VISUAL_REGRESSION_RECEIPT_INTERFACE,
    VISUAL_REGRESSION_RECEIPT_SCHEMA,
    AccessibilityRequirementKind,
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
    UiComponentKind,
    UiDependencyRelation,
    UiEventKind,
    UiStateKind,
    VerificationStatus,
    VisualDecision,
    optional_digest,
    optional_identifier,
    optional_int,
    optional_repo_path,
    optional_text,
    parse_enum,
    parse_enum_sequence,
    reject_unknown_fields,
    require_bool,
    require_digest,
    require_extractor_version,
    require_finite_number,
    require_identifier,
    require_int,
    require_interface,
    require_mapping,
    require_repo_path,
    require_schema_version,
    require_text,
    unique_digests,
    unique_identifiers,
    unique_repo_paths,
    unique_texts,
)

M = TypeVar("M", bound="GuiOptimizerModel")

# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------


def _json_ready(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {
            str(key): _json_ready(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (list, tuple)):
        return [_json_ready(item) for item in value]
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        return _json_ready(to_dict())
    raise GuiOptimizerDecodeError(
        f"value of type {type(value).__name__} is not JSON-serializable"
    )


def canonical_model_bytes(payload: Mapping[str, Any] | Any) -> bytes:
    """Serialize a model or mapping with the package canonical JSON profile."""

    if hasattr(payload, "to_dict") and callable(payload.to_dict):
        ready = _json_ready(payload.to_dict())
    elif isinstance(payload, Mapping):
        ready = _json_ready(dict(payload))
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


# ---------------------------------------------------------------------------
# Shared nested records
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SourceSpan:
    """Provenance span in a source file (never part of stable identity)."""

    path: str
    start_line: int
    start_column: int = 0
    end_line: int | None = None
    end_column: int | None = None
    schema_version: str = SOURCE_SPAN_SCHEMA

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "end_column",
            "end_line",
            "path",
            "schema_version",
            "start_column",
            "start_line",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "path", require_repo_path(self.path, "path"))
        object.__setattr__(
            self, "start_line", require_int(self.start_line, "start_line", minimum=1)
        )
        object.__setattr__(
            self,
            "start_column",
            require_int(self.start_column, "start_column", minimum=0),
        )
        end_line = optional_int(self.end_line, "end_line", minimum=1)
        end_column = optional_int(self.end_column, "end_column", minimum=0)
        object.__setattr__(self, "end_line", end_line)
        object.__setattr__(self, "end_column", end_column)
        object.__setattr__(
            self,
            "schema_version",
            require_schema_version(self.schema_version, SOURCE_SPAN_SCHEMA),
        )
        if end_line is not None and end_line < self.start_line:
            raise GuiOptimizerDecodeError("end_line must be >= start_line")

    def to_dict(self) -> dict[str, Any]:
        return {
            "end_column": self.end_column,
            "end_line": self.end_line,
            "path": self.path,
            "schema_version": self.schema_version,
            "start_column": self.start_column,
            "start_line": self.start_line,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any] | Any) -> SourceSpan:
        payload = require_mapping(value, "source span")
        reject_unknown_fields(payload, cls._FIELDS, "source span")
        return cls(
            path=payload.get("path", ""),
            start_line=payload.get("start_line", 0),
            start_column=payload.get("start_column", 0),
            end_line=payload.get("end_line"),
            end_column=payload.get("end_column"),
            schema_version=payload.get("schema_version", SOURCE_SPAN_SCHEMA),
        )


@dataclass(frozen=True, slots=True)
class ViewportSpec:
    """Closed viewport descriptor for scenarios and visual receipts."""

    width: int
    height: int
    device_scale_factor: float | int = 1
    schema_version: str = VIEWPORT_SPEC_SCHEMA

    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "device_scale_factor",
            "height",
            "schema_version",
            "width",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "width", require_int(self.width, "width", minimum=1, maximum=100_000)
        )
        object.__setattr__(
            self,
            "height",
            require_int(self.height, "height", minimum=1, maximum=100_000),
        )
        scale = require_finite_number(self.device_scale_factor, "device_scale_factor")
        if float(scale) <= 0:
            raise GuiOptimizerDecodeError("device_scale_factor must be > 0")
        object.__setattr__(self, "device_scale_factor", scale)
        object.__setattr__(
            self,
            "schema_version",
            require_schema_version(self.schema_version, VIEWPORT_SPEC_SCHEMA),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "device_scale_factor": self.device_scale_factor,
            "height": self.height,
            "schema_version": self.schema_version,
            "width": self.width,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any] | Any) -> ViewportSpec:
        payload = require_mapping(value, "viewport")
        reject_unknown_fields(payload, cls._FIELDS, "viewport")
        return cls(
            width=payload.get("width", 0),
            height=payload.get("height", 0),
            device_scale_factor=payload.get("device_scale_factor", 1),
            schema_version=payload.get("schema_version", VIEWPORT_SPEC_SCHEMA),
        )


def _optional_span(value: Any, name: str) -> SourceSpan | None:
    if value in (None, ""):
        return None
    if isinstance(value, SourceSpan):
        return value
    return SourceSpan.from_dict(require_mapping(value, name))


# ---------------------------------------------------------------------------
# Base model helpers
# ---------------------------------------------------------------------------


class GuiOptimizerModel:
    """Mixin protocol implemented by every closed GUI optimizer model."""

    INTERFACE: ClassVar[str]
    SCHEMA_VERSION: ClassVar[str]
    _FIELDS: ClassVar[frozenset[str]]

    def to_dict(self) -> dict[str, Any]:  # pragma: no cover - abstract
        raise NotImplementedError

    def canonical_bytes(self) -> bytes:
        return canonical_model_bytes(self)

    def canonical_json(self) -> str:
        return canonical_model_json(self)

    @classmethod
    def from_dict(cls: type[M], value: Mapping[str, Any] | Any) -> M:  # pragma: no cover
        raise NotImplementedError


def _decode_model(
    cls: type[M],
    value: Mapping[str, Any] | Any,
    *,
    record_name: str,
    builder: Callable[[Mapping[str, Any]], M],
) -> M:
    payload = require_mapping(value, record_name)
    reject_unknown_fields(payload, cls._FIELDS, record_name)
    return builder(payload)


# ---------------------------------------------------------------------------
# Identity models
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class GuiApplicationIdentity(GuiOptimizerModel):
    """Stable application identity (no line-number authority)."""

    application_id: str
    package_namespace: str
    display_name: str = ""
    repository_root: str = ""
    interface: str = GUI_APPLICATION_IDENTITY_INTERFACE
    schema_version: str = GUI_APPLICATION_IDENTITY_SCHEMA

    INTERFACE: ClassVar[str] = GUI_APPLICATION_IDENTITY_INTERFACE
    SCHEMA_VERSION: ClassVar[str] = GUI_APPLICATION_IDENTITY_SCHEMA
    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "application_id",
            "display_name",
            "interface",
            "package_namespace",
            "repository_root",
            "schema_version",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "application_id",
            require_identifier(self.application_id, "application_id"),
        )
        object.__setattr__(
            self,
            "package_namespace",
            require_identifier(self.package_namespace, "package_namespace"),
        )
        object.__setattr__(
            self, "display_name", optional_text(self.display_name, "display_name")
        )
        object.__setattr__(
            self,
            "repository_root",
            optional_repo_path(self.repository_root, "repository_root"),
        )
        object.__setattr__(
            self,
            "interface",
            require_interface(self.interface, GUI_APPLICATION_IDENTITY_INTERFACE),
        )
        object.__setattr__(
            self,
            "schema_version",
            require_schema_version(
                self.schema_version, GUI_APPLICATION_IDENTITY_SCHEMA
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
        return _decode_model(
            cls,
            value,
            record_name="GuiApplicationIdentity",
            builder=lambda p: cls(
                application_id=p.get("application_id", ""),
                package_namespace=p.get("package_namespace", ""),
                display_name=p.get("display_name", ""),
                repository_root=p.get("repository_root", ""),
                interface=p.get("interface", GUI_APPLICATION_IDENTITY_INTERFACE),
                schema_version=p.get(
                    "schema_version", GUI_APPLICATION_IDENTITY_SCHEMA
                ),
            ),
        )


@dataclass(frozen=True, slots=True)
class GuiScreenIdentity(GuiOptimizerModel):
    """Stable screen/route identity within an application."""

    application_id: str
    screen_id: str
    route_id: str = ""
    interface: str = GUI_SCREEN_IDENTITY_INTERFACE
    schema_version: str = GUI_SCREEN_IDENTITY_SCHEMA

    INTERFACE: ClassVar[str] = GUI_SCREEN_IDENTITY_INTERFACE
    SCHEMA_VERSION: ClassVar[str] = GUI_SCREEN_IDENTITY_SCHEMA
    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "application_id",
            "interface",
            "route_id",
            "schema_version",
            "screen_id",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "application_id",
            require_identifier(self.application_id, "application_id"),
        )
        object.__setattr__(
            self, "screen_id", require_identifier(self.screen_id, "screen_id")
        )
        object.__setattr__(
            self, "route_id", optional_identifier(self.route_id, "route_id")
        )
        object.__setattr__(
            self,
            "interface",
            require_interface(self.interface, GUI_SCREEN_IDENTITY_INTERFACE),
        )
        object.__setattr__(
            self,
            "schema_version",
            require_schema_version(self.schema_version, GUI_SCREEN_IDENTITY_SCHEMA),
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
        return _decode_model(
            cls,
            value,
            record_name="GuiScreenIdentity",
            builder=lambda p: cls(
                application_id=p.get("application_id", ""),
                screen_id=p.get("screen_id", ""),
                route_id=p.get("route_id", ""),
                interface=p.get("interface", GUI_SCREEN_IDENTITY_INTERFACE),
                schema_version=p.get("schema_version", GUI_SCREEN_IDENTITY_SCHEMA),
            ),
        )


@dataclass(frozen=True, slots=True)
class UiComponentIdentity(GuiOptimizerModel):
    """Stable logical component identity (line numbers are not identity)."""

    application_id: str
    qualified_name: str
    component_kind: UiComponentKind | str
    package_namespace: str
    screen_id: str = ""
    interface: str = UI_COMPONENT_IDENTITY_INTERFACE
    schema_version: str = UI_COMPONENT_IDENTITY_SCHEMA

    INTERFACE: ClassVar[str] = UI_COMPONENT_IDENTITY_INTERFACE
    SCHEMA_VERSION: ClassVar[str] = UI_COMPONENT_IDENTITY_SCHEMA
    _FIELDS: ClassVar[frozenset[str]] = frozenset(
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

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "application_id",
            require_identifier(self.application_id, "application_id"),
        )
        object.__setattr__(
            self,
            "qualified_name",
            require_identifier(self.qualified_name, "qualified_name"),
        )
        object.__setattr__(
            self,
            "component_kind",
            parse_enum(self.component_kind, UiComponentKind, "component_kind"),
        )
        object.__setattr__(
            self,
            "package_namespace",
            require_identifier(self.package_namespace, "package_namespace"),
        )
        object.__setattr__(
            self, "screen_id", optional_identifier(self.screen_id, "screen_id")
        )
        object.__setattr__(
            self,
            "interface",
            require_interface(self.interface, UI_COMPONENT_IDENTITY_INTERFACE),
        )
        object.__setattr__(
            self,
            "schema_version",
            require_schema_version(self.schema_version, UI_COMPONENT_IDENTITY_SCHEMA),
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
        return _decode_model(
            cls,
            value,
            record_name="UiComponentIdentity",
            builder=lambda p: cls(
                application_id=p.get("application_id", ""),
                qualified_name=p.get("qualified_name", ""),
                component_kind=p.get("component_kind", UiComponentKind.UNKNOWN),
                package_namespace=p.get("package_namespace", ""),
                screen_id=p.get("screen_id", ""),
                interface=p.get("interface", UI_COMPONENT_IDENTITY_INTERFACE),
                schema_version=p.get("schema_version", UI_COMPONENT_IDENTITY_SCHEMA),
            ),
        )


@dataclass(frozen=True, slots=True)
class UiComponentVersion(GuiOptimizerModel):
    """Content version identity for a component (meaningful material only)."""

    stable_identity: UiComponentIdentity | Mapping[str, Any]
    structure_digest: str
    props_digest: str
    state_digest: str
    handlers_digest: str
    accessibility_digest: str
    styles_digest: str
    actions_digest: str
    localization_digest: str = ""
    extractor_version: str = "1.0.0"
    optimizer_schema_version: str = UI_COMPONENT_VERSION_SCHEMA
    interface: str = UI_COMPONENT_VERSION_INTERFACE
    schema_version: str = UI_COMPONENT_VERSION_SCHEMA

    INTERFACE: ClassVar[str] = UI_COMPONENT_VERSION_INTERFACE
    SCHEMA_VERSION: ClassVar[str] = UI_COMPONENT_VERSION_SCHEMA
    _FIELDS: ClassVar[frozenset[str]] = frozenset(
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

    def __post_init__(self) -> None:
        identity = self.stable_identity
        if isinstance(identity, Mapping):
            identity = UiComponentIdentity.from_dict(identity)
        if not isinstance(identity, UiComponentIdentity):
            raise GuiOptimizerDecodeError(
                "stable_identity must be a UiComponentIdentity"
            )
        object.__setattr__(self, "stable_identity", identity)
        for field_name in (
            "structure_digest",
            "props_digest",
            "state_digest",
            "handlers_digest",
            "accessibility_digest",
            "styles_digest",
            "actions_digest",
        ):
            object.__setattr__(
                self,
                field_name,
                require_digest(getattr(self, field_name), field_name),
            )
        object.__setattr__(
            self,
            "localization_digest",
            optional_digest(self.localization_digest, "localization_digest"),
        )
        object.__setattr__(
            self,
            "extractor_version",
            require_extractor_version(self.extractor_version),
        )
        object.__setattr__(
            self,
            "optimizer_schema_version",
            require_text(
                self.optimizer_schema_version,
                "optimizer_schema_version",
                max_chars=128,
            ),
        )
        object.__setattr__(
            self,
            "interface",
            require_interface(self.interface, UI_COMPONENT_VERSION_INTERFACE),
        )
        object.__setattr__(
            self,
            "schema_version",
            require_schema_version(self.schema_version, UI_COMPONENT_VERSION_SCHEMA),
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
        return _decode_model(
            cls,
            value,
            record_name="UiComponentVersion",
            builder=lambda p: cls(
                stable_identity=p.get("stable_identity", {}),
                structure_digest=p.get("structure_digest", ""),
                props_digest=p.get("props_digest", ""),
                state_digest=p.get("state_digest", ""),
                handlers_digest=p.get("handlers_digest", ""),
                accessibility_digest=p.get("accessibility_digest", ""),
                styles_digest=p.get("styles_digest", ""),
                actions_digest=p.get("actions_digest", ""),
                localization_digest=p.get("localization_digest", ""),
                extractor_version=p.get("extractor_version", "1.0.0"),
                optimizer_schema_version=p.get(
                    "optimizer_schema_version", UI_COMPONENT_VERSION_SCHEMA
                ),
                interface=p.get("interface", UI_COMPONENT_VERSION_INTERFACE),
                schema_version=p.get("schema_version", UI_COMPONENT_VERSION_SCHEMA),
            ),
        )


# ---------------------------------------------------------------------------
# Graph / state / action models
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class UiDependencyEdge(GuiOptimizerModel):
    """Typed dependency edge with extraction confidence and provenance."""

    source_component_id: str
    target_component_id: str
    relation: UiDependencyRelation | str
    extraction_method: ExtractionMethod | str
    extractor_version: str
    confidence: ExtractionConfidence | str
    source_span: SourceSpan | Mapping[str, Any] | None = None
    notes: str = ""
    interface: str = UI_DEPENDENCY_EDGE_INTERFACE
    schema_version: str = UI_DEPENDENCY_EDGE_SCHEMA

    INTERFACE: ClassVar[str] = UI_DEPENDENCY_EDGE_INTERFACE
    SCHEMA_VERSION: ClassVar[str] = UI_DEPENDENCY_EDGE_SCHEMA
    _FIELDS: ClassVar[frozenset[str]] = frozenset(
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

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "source_component_id",
            require_identifier(self.source_component_id, "source_component_id"),
        )
        object.__setattr__(
            self,
            "target_component_id",
            require_identifier(self.target_component_id, "target_component_id"),
        )
        object.__setattr__(
            self,
            "relation",
            parse_enum(self.relation, UiDependencyRelation, "relation"),
        )
        object.__setattr__(
            self,
            "extraction_method",
            parse_enum(self.extraction_method, ExtractionMethod, "extraction_method"),
        )
        object.__setattr__(
            self,
            "extractor_version",
            require_extractor_version(self.extractor_version),
        )
        object.__setattr__(
            self,
            "confidence",
            parse_enum(self.confidence, ExtractionConfidence, "confidence"),
        )
        object.__setattr__(
            self, "source_span", _optional_span(self.source_span, "source_span")
        )
        object.__setattr__(self, "notes", optional_text(self.notes, "notes"))
        object.__setattr__(
            self,
            "interface",
            require_interface(self.interface, UI_DEPENDENCY_EDGE_INTERFACE),
        )
        object.__setattr__(
            self,
            "schema_version",
            require_schema_version(self.schema_version, UI_DEPENDENCY_EDGE_SCHEMA),
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
            "source_span": (
                self.source_span.to_dict() if self.source_span is not None else None
            ),
            "target_component_id": self.target_component_id,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any] | Any) -> UiDependencyEdge:
        return _decode_model(
            cls,
            value,
            record_name="UiDependencyEdge",
            builder=lambda p: cls(
                source_component_id=p.get("source_component_id", ""),
                target_component_id=p.get("target_component_id", ""),
                relation=p.get("relation", ""),
                extraction_method=p.get("extraction_method", ""),
                extractor_version=p.get("extractor_version", ""),
                confidence=p.get("confidence", ""),
                source_span=p.get("source_span"),
                notes=p.get("notes", ""),
                interface=p.get("interface", UI_DEPENDENCY_EDGE_INTERFACE),
                schema_version=p.get("schema_version", UI_DEPENDENCY_EDGE_SCHEMA),
            ),
        )


@dataclass(frozen=True, slots=True)
class UiStateDefinition(GuiOptimizerModel):
    """One explicit UI state in a screen state machine."""

    state_id: str
    kind: UiStateKind | str
    screen_id: str
    label: str = ""
    is_initial: bool = False
    is_terminal: bool = False
    description: str = ""
    interface: str = UI_STATE_DEFINITION_INTERFACE
    schema_version: str = UI_STATE_DEFINITION_SCHEMA

    INTERFACE: ClassVar[str] = UI_STATE_DEFINITION_INTERFACE
    SCHEMA_VERSION: ClassVar[str] = UI_STATE_DEFINITION_SCHEMA
    _FIELDS: ClassVar[frozenset[str]] = frozenset(
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

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "state_id", require_identifier(self.state_id, "state_id")
        )
        object.__setattr__(
            self, "kind", parse_enum(self.kind, UiStateKind, "kind")
        )
        object.__setattr__(
            self, "screen_id", require_identifier(self.screen_id, "screen_id")
        )
        object.__setattr__(self, "label", optional_text(self.label, "label"))
        object.__setattr__(
            self, "is_initial", require_bool(self.is_initial, "is_initial")
        )
        object.__setattr__(
            self, "is_terminal", require_bool(self.is_terminal, "is_terminal")
        )
        object.__setattr__(
            self, "description", optional_text(self.description, "description")
        )
        object.__setattr__(
            self,
            "interface",
            require_interface(self.interface, UI_STATE_DEFINITION_INTERFACE),
        )
        object.__setattr__(
            self,
            "schema_version",
            require_schema_version(self.schema_version, UI_STATE_DEFINITION_SCHEMA),
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
        return _decode_model(
            cls,
            value,
            record_name="UiStateDefinition",
            builder=lambda p: cls(
                state_id=p.get("state_id", ""),
                kind=p.get("kind", ""),
                screen_id=p.get("screen_id", ""),
                label=p.get("label", ""),
                is_initial=p.get("is_initial", False),
                is_terminal=p.get("is_terminal", False),
                description=p.get("description", ""),
                interface=p.get("interface", UI_STATE_DEFINITION_INTERFACE),
                schema_version=p.get("schema_version", UI_STATE_DEFINITION_SCHEMA),
            ),
        )


@dataclass(frozen=True, slots=True)
class UiEventDefinition(GuiOptimizerModel):
    """One declared UI event that may trigger transitions."""

    event_id: str
    kind: UiEventKind | str
    name: str
    description: str = ""
    interface: str = UI_EVENT_DEFINITION_INTERFACE
    schema_version: str = UI_EVENT_DEFINITION_SCHEMA

    INTERFACE: ClassVar[str] = UI_EVENT_DEFINITION_INTERFACE
    SCHEMA_VERSION: ClassVar[str] = UI_EVENT_DEFINITION_SCHEMA
    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "description",
            "event_id",
            "interface",
            "kind",
            "name",
            "schema_version",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "event_id", require_identifier(self.event_id, "event_id")
        )
        object.__setattr__(
            self, "kind", parse_enum(self.kind, UiEventKind, "kind")
        )
        object.__setattr__(self, "name", require_text(self.name, "name"))
        object.__setattr__(
            self, "description", optional_text(self.description, "description")
        )
        object.__setattr__(
            self,
            "interface",
            require_interface(self.interface, UI_EVENT_DEFINITION_INTERFACE),
        )
        object.__setattr__(
            self,
            "schema_version",
            require_schema_version(self.schema_version, UI_EVENT_DEFINITION_SCHEMA),
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
        return _decode_model(
            cls,
            value,
            record_name="UiEventDefinition",
            builder=lambda p: cls(
                event_id=p.get("event_id", ""),
                kind=p.get("kind", ""),
                name=p.get("name", ""),
                description=p.get("description", ""),
                interface=p.get("interface", UI_EVENT_DEFINITION_INTERFACE),
                schema_version=p.get("schema_version", UI_EVENT_DEFINITION_SCHEMA),
            ),
        )


@dataclass(frozen=True, slots=True)
class UiTransitionDefinition(GuiOptimizerModel):
    """One finite transition between declared states."""

    transition_id: str
    from_state_id: str
    to_state_id: str
    event_id: str
    guard: str = ""
    effect_ids: tuple[str, ...] = ()
    is_noop: bool = False
    interface: str = UI_TRANSITION_DEFINITION_INTERFACE
    schema_version: str = UI_TRANSITION_DEFINITION_SCHEMA

    INTERFACE: ClassVar[str] = UI_TRANSITION_DEFINITION_INTERFACE
    SCHEMA_VERSION: ClassVar[str] = UI_TRANSITION_DEFINITION_SCHEMA
    _FIELDS: ClassVar[frozenset[str]] = frozenset(
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

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "transition_id",
            require_identifier(self.transition_id, "transition_id"),
        )
        object.__setattr__(
            self,
            "from_state_id",
            require_identifier(self.from_state_id, "from_state_id"),
        )
        object.__setattr__(
            self,
            "to_state_id",
            require_identifier(self.to_state_id, "to_state_id"),
        )
        object.__setattr__(
            self, "event_id", require_identifier(self.event_id, "event_id")
        )
        object.__setattr__(self, "guard", optional_text(self.guard, "guard"))
        object.__setattr__(
            self,
            "effect_ids",
            unique_identifiers(self.effect_ids, "effect_ids"),
        )
        object.__setattr__(self, "is_noop", require_bool(self.is_noop, "is_noop"))
        object.__setattr__(
            self,
            "interface",
            require_interface(self.interface, UI_TRANSITION_DEFINITION_INTERFACE),
        )
        object.__setattr__(
            self,
            "schema_version",
            require_schema_version(
                self.schema_version, UI_TRANSITION_DEFINITION_SCHEMA
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
        return _decode_model(
            cls,
            value,
            record_name="UiTransitionDefinition",
            builder=lambda p: cls(
                transition_id=p.get("transition_id", ""),
                from_state_id=p.get("from_state_id", ""),
                to_state_id=p.get("to_state_id", ""),
                event_id=p.get("event_id", ""),
                guard=p.get("guard", ""),
                effect_ids=tuple(p.get("effect_ids", ())),
                is_noop=p.get("is_noop", False),
                interface=p.get("interface", UI_TRANSITION_DEFINITION_INTERFACE),
                schema_version=p.get(
                    "schema_version", UI_TRANSITION_DEFINITION_SCHEMA
                ),
            ),
        )


@dataclass(frozen=True, slots=True)
class UiActionBinding(GuiOptimizerModel):
    """Exact action/method/schema binding with confirmation/policy flags."""

    action_id: str
    method: str
    schema_id: str
    requires_confirmation: bool = False
    confirmation_id: str = ""
    policy_id: str = ""
    depends_on_schema: bool = False
    is_destructive: bool = False
    component_id: str = ""
    interface: str = UI_ACTION_BINDING_INTERFACE
    schema_version: str = UI_ACTION_BINDING_SCHEMA

    INTERFACE: ClassVar[str] = UI_ACTION_BINDING_INTERFACE
    SCHEMA_VERSION: ClassVar[str] = UI_ACTION_BINDING_SCHEMA
    _FIELDS: ClassVar[frozenset[str]] = frozenset(
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

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "action_id", require_identifier(self.action_id, "action_id")
        )
        object.__setattr__(self, "method", require_identifier(self.method, "method"))
        object.__setattr__(
            self, "schema_id", require_identifier(self.schema_id, "schema_id")
        )
        object.__setattr__(
            self,
            "requires_confirmation",
            require_bool(self.requires_confirmation, "requires_confirmation"),
        )
        object.__setattr__(
            self,
            "confirmation_id",
            optional_identifier(self.confirmation_id, "confirmation_id"),
        )
        object.__setattr__(
            self, "policy_id", optional_identifier(self.policy_id, "policy_id")
        )
        object.__setattr__(
            self,
            "depends_on_schema",
            require_bool(self.depends_on_schema, "depends_on_schema"),
        )
        object.__setattr__(
            self,
            "is_destructive",
            require_bool(self.is_destructive, "is_destructive"),
        )
        object.__setattr__(
            self,
            "component_id",
            optional_identifier(self.component_id, "component_id"),
        )
        if self.requires_confirmation and not self.confirmation_id:
            raise GuiOptimizerDecodeError(
                "confirmation_id is required when requires_confirmation is true"
            )
        object.__setattr__(
            self,
            "interface",
            require_interface(self.interface, UI_ACTION_BINDING_INTERFACE),
        )
        object.__setattr__(
            self,
            "schema_version",
            require_schema_version(self.schema_version, UI_ACTION_BINDING_SCHEMA),
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
        return _decode_model(
            cls,
            value,
            record_name="UiActionBinding",
            builder=lambda p: cls(
                action_id=p.get("action_id", ""),
                method=p.get("method", ""),
                schema_id=p.get("schema_id", ""),
                requires_confirmation=p.get("requires_confirmation", False),
                confirmation_id=p.get("confirmation_id", ""),
                policy_id=p.get("policy_id", ""),
                depends_on_schema=p.get("depends_on_schema", False),
                is_destructive=p.get("is_destructive", False),
                component_id=p.get("component_id", ""),
                interface=p.get("interface", UI_ACTION_BINDING_INTERFACE),
                schema_version=p.get("schema_version", UI_ACTION_BINDING_SCHEMA),
            ),
        )


@dataclass(frozen=True, slots=True)
class UiLayoutConstraint(GuiOptimizerModel):
    """Bounded layout or responsive constraint declaration."""

    constraint_id: str
    kind: LayoutConstraintKind | str
    expression: str
    component_id: str = ""
    breakpoint: str = ""
    lower_bound: int | None = None
    upper_bound: int | None = None
    interface: str = UI_LAYOUT_CONSTRAINT_INTERFACE
    schema_version: str = UI_LAYOUT_CONSTRAINT_SCHEMA

    INTERFACE: ClassVar[str] = UI_LAYOUT_CONSTRAINT_INTERFACE
    SCHEMA_VERSION: ClassVar[str] = UI_LAYOUT_CONSTRAINT_SCHEMA
    _FIELDS: ClassVar[frozenset[str]] = frozenset(
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

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "constraint_id",
            require_identifier(self.constraint_id, "constraint_id"),
        )
        object.__setattr__(
            self, "kind", parse_enum(self.kind, LayoutConstraintKind, "kind")
        )
        object.__setattr__(
            self, "expression", require_text(self.expression, "expression")
        )
        object.__setattr__(
            self,
            "component_id",
            optional_identifier(self.component_id, "component_id"),
        )
        object.__setattr__(
            self, "breakpoint", optional_text(self.breakpoint, "breakpoint")
        )
        lower = optional_int(self.lower_bound, "lower_bound")
        upper = optional_int(self.upper_bound, "upper_bound")
        if lower is not None and upper is not None and lower > upper:
            raise GuiOptimizerDecodeError("lower_bound must not exceed upper_bound")
        object.__setattr__(self, "lower_bound", lower)
        object.__setattr__(self, "upper_bound", upper)
        object.__setattr__(
            self,
            "interface",
            require_interface(self.interface, UI_LAYOUT_CONSTRAINT_INTERFACE),
        )
        object.__setattr__(
            self,
            "schema_version",
            require_schema_version(self.schema_version, UI_LAYOUT_CONSTRAINT_SCHEMA),
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
        return _decode_model(
            cls,
            value,
            record_name="UiLayoutConstraint",
            builder=lambda p: cls(
                constraint_id=p.get("constraint_id", ""),
                kind=p.get("kind", ""),
                expression=p.get("expression", ""),
                component_id=p.get("component_id", ""),
                breakpoint=p.get("breakpoint", ""),
                lower_bound=p.get("lower_bound"),
                upper_bound=p.get("upper_bound"),
                interface=p.get("interface", UI_LAYOUT_CONSTRAINT_INTERFACE),
                schema_version=p.get("schema_version", UI_LAYOUT_CONSTRAINT_SCHEMA),
            ),
        )


@dataclass(frozen=True, slots=True)
class UiAccessibilityContract(GuiOptimizerModel):
    """Declared accessibility obligations for a component or screen."""

    contract_id: str
    requirement_kinds: tuple[AccessibilityRequirementKind | str, ...]
    required_roles: tuple[str, ...] = ()
    required_names: tuple[str, ...] = ()
    component_id: str = ""
    notes: str = ""
    interface: str = UI_ACCESSIBILITY_CONTRACT_INTERFACE
    schema_version: str = UI_ACCESSIBILITY_CONTRACT_SCHEMA

    INTERFACE: ClassVar[str] = UI_ACCESSIBILITY_CONTRACT_INTERFACE
    SCHEMA_VERSION: ClassVar[str] = UI_ACCESSIBILITY_CONTRACT_SCHEMA
    _FIELDS: ClassVar[frozenset[str]] = frozenset(
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

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "contract_id",
            require_identifier(self.contract_id, "contract_id"),
        )
        kinds = parse_enum_sequence(
            self.requirement_kinds,
            AccessibilityRequirementKind,
            "requirement_kinds",
        )
        if not kinds:
            raise GuiOptimizerDecodeError(
                "requirement_kinds must contain at least one requirement"
            )
        object.__setattr__(self, "requirement_kinds", kinds)
        object.__setattr__(
            self,
            "required_roles",
            unique_texts(self.required_roles, "required_roles", preserve_order=True),
        )
        object.__setattr__(
            self,
            "required_names",
            unique_texts(self.required_names, "required_names", preserve_order=True),
        )
        object.__setattr__(
            self,
            "component_id",
            optional_identifier(self.component_id, "component_id"),
        )
        object.__setattr__(self, "notes", optional_text(self.notes, "notes"))
        object.__setattr__(
            self,
            "interface",
            require_interface(self.interface, UI_ACCESSIBILITY_CONTRACT_INTERFACE),
        )
        object.__setattr__(
            self,
            "schema_version",
            require_schema_version(
                self.schema_version, UI_ACCESSIBILITY_CONTRACT_SCHEMA
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
        return _decode_model(
            cls,
            value,
            record_name="UiAccessibilityContract",
            builder=lambda p: cls(
                contract_id=p.get("contract_id", ""),
                requirement_kinds=tuple(p.get("requirement_kinds", ())),
                required_roles=tuple(p.get("required_roles", ())),
                required_names=tuple(p.get("required_names", ())),
                component_id=p.get("component_id", ""),
                notes=p.get("notes", ""),
                interface=p.get("interface", UI_ACCESSIBILITY_CONTRACT_INTERFACE),
                schema_version=p.get(
                    "schema_version", UI_ACCESSIBILITY_CONTRACT_SCHEMA
                ),
            ),
        )


# ---------------------------------------------------------------------------
# Capsule / change / evaluation models
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class UiSemanticCapsule(GuiOptimizerModel):
    """Closed GUI-specific semantic capsule (not a prior semantic-capsule pkg)."""

    capsule_id: str
    stable_identity: UiComponentIdentity | Mapping[str, Any]
    version_identity: UiComponentVersion | Mapping[str, Any]
    application_id: str
    screen_id: str
    purpose: str
    component_type: str
    analysis_classification: AnalysisClassification | str
    verification_status: VerificationStatus | str
    completeness_boundary: CompletenessBoundary | str
    prop_names: tuple[str, ...] = ()
    emitted_event_ids: tuple[str, ...] = ()
    state_variable_ids: tuple[str, ...] = ()
    visible_state_ids: tuple[str, ...] = ()
    transition_ids: tuple[str, ...] = ()
    action_binding_ids: tuple[str, ...] = ()
    child_component_ids: tuple[str, ...] = ()
    dependency_edge_ids: tuple[str, ...] = ()
    test_ids: tuple[str, ...] = ()
    screenshot_ids: tuple[str, ...] = ()
    known_violation_ids: tuple[str, ...] = ()
    unresolved_dynamic_behavior: tuple[str, ...] = ()
    localization_keys: tuple[str, ...] = ()
    accessibility_contract_id: str = ""
    confirmation_required: bool = False
    loading_behavior: str = ""
    empty_behavior: str = ""
    success_behavior: str = ""
    error_behavior: str = ""
    source_revision: str = ""
    interface: str = UI_SEMANTIC_CAPSULE_INTERFACE
    schema_version: str = UI_SEMANTIC_CAPSULE_SCHEMA

    INTERFACE: ClassVar[str] = UI_SEMANTIC_CAPSULE_INTERFACE
    SCHEMA_VERSION: ClassVar[str] = UI_SEMANTIC_CAPSULE_SCHEMA
    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "accessibility_contract_id",
            "action_binding_ids",
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
            "interface",
            "known_violation_ids",
            "loading_behavior",
            "localization_keys",
            "prop_names",
            "purpose",
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

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "capsule_id", require_identifier(self.capsule_id, "capsule_id")
        )
        stable = self.stable_identity
        if isinstance(stable, Mapping):
            stable = UiComponentIdentity.from_dict(stable)
        if not isinstance(stable, UiComponentIdentity):
            raise GuiOptimizerDecodeError(
                "stable_identity must be a UiComponentIdentity"
            )
        object.__setattr__(self, "stable_identity", stable)
        version = self.version_identity
        if isinstance(version, Mapping):
            version = UiComponentVersion.from_dict(version)
        if not isinstance(version, UiComponentVersion):
            raise GuiOptimizerDecodeError(
                "version_identity must be a UiComponentVersion"
            )
        object.__setattr__(self, "version_identity", version)
        object.__setattr__(
            self,
            "application_id",
            require_identifier(self.application_id, "application_id"),
        )
        object.__setattr__(
            self, "screen_id", require_identifier(self.screen_id, "screen_id")
        )
        object.__setattr__(self, "purpose", require_text(self.purpose, "purpose"))
        object.__setattr__(
            self,
            "component_type",
            require_text(self.component_type, "component_type"),
        )
        object.__setattr__(
            self,
            "analysis_classification",
            parse_enum(
                self.analysis_classification,
                AnalysisClassification,
                "analysis_classification",
            ),
        )
        object.__setattr__(
            self,
            "verification_status",
            parse_enum(
                self.verification_status,
                VerificationStatus,
                "verification_status",
            ),
        )
        object.__setattr__(
            self,
            "completeness_boundary",
            parse_enum(
                self.completeness_boundary,
                CompletenessBoundary,
                "completeness_boundary",
            ),
        )
        for field_name in (
            "prop_names",
            "emitted_event_ids",
            "state_variable_ids",
            "visible_state_ids",
            "transition_ids",
            "action_binding_ids",
            "child_component_ids",
            "dependency_edge_ids",
            "test_ids",
            "screenshot_ids",
            "known_violation_ids",
            "unresolved_dynamic_behavior",
            "localization_keys",
        ):
            raw = getattr(self, field_name)
            if field_name in {"prop_names", "unresolved_dynamic_behavior", "localization_keys"}:
                object.__setattr__(
                    self,
                    field_name,
                    unique_texts(raw, field_name, preserve_order=True),
                )
            else:
                object.__setattr__(
                    self, field_name, unique_identifiers(raw, field_name)
                )
        object.__setattr__(
            self,
            "accessibility_contract_id",
            optional_identifier(
                self.accessibility_contract_id, "accessibility_contract_id"
            ),
        )
        object.__setattr__(
            self,
            "confirmation_required",
            require_bool(self.confirmation_required, "confirmation_required"),
        )
        for field_name in (
            "loading_behavior",
            "empty_behavior",
            "success_behavior",
            "error_behavior",
            "source_revision",
        ):
            object.__setattr__(
                self,
                field_name,
                optional_text(getattr(self, field_name), field_name),
            )
        object.__setattr__(
            self,
            "interface",
            require_interface(self.interface, UI_SEMANTIC_CAPSULE_INTERFACE),
        )
        object.__setattr__(
            self,
            "schema_version",
            require_schema_version(self.schema_version, UI_SEMANTIC_CAPSULE_SCHEMA),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "accessibility_contract_id": self.accessibility_contract_id,
            "action_binding_ids": list(self.action_binding_ids),
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
            "interface": self.interface,
            "known_violation_ids": list(self.known_violation_ids),
            "loading_behavior": self.loading_behavior,
            "localization_keys": list(self.localization_keys),
            "prop_names": list(self.prop_names),
            "purpose": self.purpose,
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
        return _decode_model(
            cls,
            value,
            record_name="UiSemanticCapsule",
            builder=lambda p: cls(
                capsule_id=p.get("capsule_id", ""),
                stable_identity=p.get("stable_identity", {}),
                version_identity=p.get("version_identity", {}),
                application_id=p.get("application_id", ""),
                screen_id=p.get("screen_id", ""),
                purpose=p.get("purpose", ""),
                component_type=p.get("component_type", ""),
                analysis_classification=p.get("analysis_classification", ""),
                verification_status=p.get("verification_status", ""),
                completeness_boundary=p.get("completeness_boundary", ""),
                prop_names=tuple(p.get("prop_names", ())),
                emitted_event_ids=tuple(p.get("emitted_event_ids", ())),
                state_variable_ids=tuple(p.get("state_variable_ids", ())),
                visible_state_ids=tuple(p.get("visible_state_ids", ())),
                transition_ids=tuple(p.get("transition_ids", ())),
                action_binding_ids=tuple(p.get("action_binding_ids", ())),
                child_component_ids=tuple(p.get("child_component_ids", ())),
                dependency_edge_ids=tuple(p.get("dependency_edge_ids", ())),
                test_ids=tuple(p.get("test_ids", ())),
                screenshot_ids=tuple(p.get("screenshot_ids", ())),
                known_violation_ids=tuple(p.get("known_violation_ids", ())),
                unresolved_dynamic_behavior=tuple(
                    p.get("unresolved_dynamic_behavior", ())
                ),
                localization_keys=tuple(p.get("localization_keys", ())),
                accessibility_contract_id=p.get("accessibility_contract_id", ""),
                confirmation_required=p.get("confirmation_required", False),
                loading_behavior=p.get("loading_behavior", ""),
                empty_behavior=p.get("empty_behavior", ""),
                success_behavior=p.get("success_behavior", ""),
                error_behavior=p.get("error_behavior", ""),
                source_revision=p.get("source_revision", ""),
                interface=p.get("interface", UI_SEMANTIC_CAPSULE_INTERFACE),
                schema_version=p.get("schema_version", UI_SEMANTIC_CAPSULE_SCHEMA),
            ),
        )


@dataclass(frozen=True, slots=True)
class UiChangeSet(GuiOptimizerModel):
    """Normalized set of intended or observed GUI changes."""

    change_set_id: str
    change_kinds: tuple[ChangeKind | str, ...]
    file_paths: tuple[str, ...]
    component_ids: tuple[str, ...] = ()
    state_ids: tuple[str, ...] = ()
    action_ids: tuple[str, ...] = ()
    summary: str = ""
    interface: str = UI_CHANGE_SET_INTERFACE
    schema_version: str = UI_CHANGE_SET_SCHEMA

    INTERFACE: ClassVar[str] = UI_CHANGE_SET_INTERFACE
    SCHEMA_VERSION: ClassVar[str] = UI_CHANGE_SET_SCHEMA
    _FIELDS: ClassVar[frozenset[str]] = frozenset(
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

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "change_set_id",
            require_identifier(self.change_set_id, "change_set_id"),
        )
        kinds = parse_enum_sequence(self.change_kinds, ChangeKind, "change_kinds")
        if not kinds:
            raise GuiOptimizerDecodeError("change_kinds must not be empty")
        object.__setattr__(self, "change_kinds", kinds)
        paths = unique_repo_paths(self.file_paths, "file_paths")
        if not paths:
            raise GuiOptimizerDecodeError("file_paths must not be empty")
        object.__setattr__(self, "file_paths", paths)
        object.__setattr__(
            self,
            "component_ids",
            unique_identifiers(self.component_ids, "component_ids"),
        )
        object.__setattr__(
            self, "state_ids", unique_identifiers(self.state_ids, "state_ids")
        )
        object.__setattr__(
            self, "action_ids", unique_identifiers(self.action_ids, "action_ids")
        )
        object.__setattr__(self, "summary", optional_text(self.summary, "summary"))
        object.__setattr__(
            self,
            "interface",
            require_interface(self.interface, UI_CHANGE_SET_INTERFACE),
        )
        object.__setattr__(
            self,
            "schema_version",
            require_schema_version(self.schema_version, UI_CHANGE_SET_SCHEMA),
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
        return _decode_model(
            cls,
            value,
            record_name="UiChangeSet",
            builder=lambda p: cls(
                change_set_id=p.get("change_set_id", ""),
                change_kinds=tuple(p.get("change_kinds", ())),
                file_paths=tuple(p.get("file_paths", ())),
                component_ids=tuple(p.get("component_ids", ())),
                state_ids=tuple(p.get("state_ids", ())),
                action_ids=tuple(p.get("action_ids", ())),
                summary=p.get("summary", ""),
                interface=p.get("interface", UI_CHANGE_SET_INTERFACE),
                schema_version=p.get("schema_version", UI_CHANGE_SET_SCHEMA),
            ),
        )


@dataclass(frozen=True, slots=True)
class UiInvalidationPlan(GuiOptimizerModel):
    """Explicit invalidation plan derived from a change set."""

    plan_id: str
    change_set_id: str
    reasons: tuple[InvalidationReason | str, ...]
    affected_component_ids: tuple[str, ...]
    affected_scenario_ids: tuple[str, ...] = ()
    affected_check_ids: tuple[str, ...] = ()
    confidence: ExtractionConfidence | str = ExtractionConfidence.CONSERVATIVE
    fallback_triggered: bool = False
    fallback_explanation: str = ""
    interface: str = UI_INVALIDATION_PLAN_INTERFACE
    schema_version: str = UI_INVALIDATION_PLAN_SCHEMA

    INTERFACE: ClassVar[str] = UI_INVALIDATION_PLAN_INTERFACE
    SCHEMA_VERSION: ClassVar[str] = UI_INVALIDATION_PLAN_SCHEMA
    _FIELDS: ClassVar[frozenset[str]] = frozenset(
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

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "plan_id", require_identifier(self.plan_id, "plan_id")
        )
        object.__setattr__(
            self,
            "change_set_id",
            require_identifier(self.change_set_id, "change_set_id"),
        )
        reasons = parse_enum_sequence(
            self.reasons, InvalidationReason, "reasons"
        )
        if not reasons:
            raise GuiOptimizerDecodeError("reasons must not be empty")
        object.__setattr__(self, "reasons", reasons)
        object.__setattr__(
            self,
            "affected_component_ids",
            unique_identifiers(self.affected_component_ids, "affected_component_ids"),
        )
        object.__setattr__(
            self,
            "affected_scenario_ids",
            unique_identifiers(self.affected_scenario_ids, "affected_scenario_ids"),
        )
        object.__setattr__(
            self,
            "affected_check_ids",
            unique_identifiers(self.affected_check_ids, "affected_check_ids"),
        )
        object.__setattr__(
            self,
            "confidence",
            parse_enum(self.confidence, ExtractionConfidence, "confidence"),
        )
        object.__setattr__(
            self,
            "fallback_triggered",
            require_bool(self.fallback_triggered, "fallback_triggered"),
        )
        object.__setattr__(
            self,
            "fallback_explanation",
            optional_text(self.fallback_explanation, "fallback_explanation"),
        )
        object.__setattr__(
            self,
            "interface",
            require_interface(self.interface, UI_INVALIDATION_PLAN_INTERFACE),
        )
        object.__setattr__(
            self,
            "schema_version",
            require_schema_version(self.schema_version, UI_INVALIDATION_PLAN_SCHEMA),
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
        return _decode_model(
            cls,
            value,
            record_name="UiInvalidationPlan",
            builder=lambda p: cls(
                plan_id=p.get("plan_id", ""),
                change_set_id=p.get("change_set_id", ""),
                reasons=tuple(p.get("reasons", ())),
                affected_component_ids=tuple(p.get("affected_component_ids", ())),
                affected_scenario_ids=tuple(p.get("affected_scenario_ids", ())),
                affected_check_ids=tuple(p.get("affected_check_ids", ())),
                confidence=p.get("confidence", ExtractionConfidence.CONSERVATIVE),
                fallback_triggered=p.get("fallback_triggered", False),
                fallback_explanation=p.get("fallback_explanation", ""),
                interface=p.get("interface", UI_INVALIDATION_PLAN_INTERFACE),
                schema_version=p.get("schema_version", UI_INVALIDATION_PLAN_SCHEMA),
            ),
        )


@dataclass(frozen=True, slots=True)
class UiEvaluationScenario(GuiOptimizerModel):
    """Deterministic evaluation scenario with frozen fixture bindings."""

    scenario_id: str
    name: str
    application_id: str
    screen_id: str
    fixture_digest: str
    viewport: ViewportSpec | Mapping[str, Any]
    locale: str = "en-US"
    timezone: str = "UTC"
    color_scheme: str = "light"
    text_scale_percent: int = 100
    reduced_motion: bool = False
    tags: tuple[str, ...] = ()
    interface: str = UI_EVALUATION_SCENARIO_INTERFACE
    schema_version: str = UI_EVALUATION_SCENARIO_SCHEMA

    INTERFACE: ClassVar[str] = UI_EVALUATION_SCENARIO_INTERFACE
    SCHEMA_VERSION: ClassVar[str] = UI_EVALUATION_SCENARIO_SCHEMA
    _FIELDS: ClassVar[frozenset[str]] = frozenset(
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

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "scenario_id",
            require_identifier(self.scenario_id, "scenario_id"),
        )
        object.__setattr__(self, "name", require_text(self.name, "name"))
        object.__setattr__(
            self,
            "application_id",
            require_identifier(self.application_id, "application_id"),
        )
        object.__setattr__(
            self, "screen_id", require_identifier(self.screen_id, "screen_id")
        )
        object.__setattr__(
            self,
            "fixture_digest",
            require_digest(self.fixture_digest, "fixture_digest"),
        )
        viewport = self.viewport
        if isinstance(viewport, Mapping):
            viewport = ViewportSpec.from_dict(viewport)
        if not isinstance(viewport, ViewportSpec):
            raise GuiOptimizerDecodeError("viewport must be a ViewportSpec")
        object.__setattr__(self, "viewport", viewport)
        object.__setattr__(self, "locale", require_text(self.locale, "locale"))
        object.__setattr__(
            self, "timezone", require_text(self.timezone, "timezone")
        )
        object.__setattr__(
            self, "color_scheme", require_text(self.color_scheme, "color_scheme")
        )
        object.__setattr__(
            self,
            "text_scale_percent",
            require_int(
                self.text_scale_percent,
                "text_scale_percent",
                minimum=25,
                maximum=500,
            ),
        )
        object.__setattr__(
            self,
            "reduced_motion",
            require_bool(self.reduced_motion, "reduced_motion"),
        )
        object.__setattr__(
            self, "tags", unique_texts(self.tags, "tags", preserve_order=True)
        )
        object.__setattr__(
            self,
            "interface",
            require_interface(self.interface, UI_EVALUATION_SCENARIO_INTERFACE),
        )
        object.__setattr__(
            self,
            "schema_version",
            require_schema_version(
                self.schema_version, UI_EVALUATION_SCENARIO_SCHEMA
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
        return _decode_model(
            cls,
            value,
            record_name="UiEvaluationScenario",
            builder=lambda p: cls(
                scenario_id=p.get("scenario_id", ""),
                name=p.get("name", ""),
                application_id=p.get("application_id", ""),
                screen_id=p.get("screen_id", ""),
                fixture_digest=p.get("fixture_digest", ""),
                viewport=p.get("viewport", {}),
                locale=p.get("locale", "en-US"),
                timezone=p.get("timezone", "UTC"),
                color_scheme=p.get("color_scheme", "light"),
                text_scale_percent=p.get("text_scale_percent", 100),
                reduced_motion=p.get("reduced_motion", False),
                tags=tuple(p.get("tags", ())),
                interface=p.get("interface", UI_EVALUATION_SCENARIO_INTERFACE),
                schema_version=p.get(
                    "schema_version", UI_EVALUATION_SCENARIO_SCHEMA
                ),
            ),
        )


@dataclass(frozen=True, slots=True)
class UiBaseline(GuiOptimizerModel):
    """Pinned metric and artifact baseline for a screen/scenario set."""

    baseline_id: str
    application_id: str
    screen_id: str
    repository_revision: str
    scenario_ids: tuple[str, ...]
    metric_digest: str
    artifact_digests: tuple[str, ...] = ()
    extractor_version: str = "1.0.0"
    interface: str = UI_BASELINE_INTERFACE
    schema_version: str = UI_BASELINE_SCHEMA

    INTERFACE: ClassVar[str] = UI_BASELINE_INTERFACE
    SCHEMA_VERSION: ClassVar[str] = UI_BASELINE_SCHEMA
    _FIELDS: ClassVar[frozenset[str]] = frozenset(
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

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "baseline_id",
            require_identifier(self.baseline_id, "baseline_id"),
        )
        object.__setattr__(
            self,
            "application_id",
            require_identifier(self.application_id, "application_id"),
        )
        object.__setattr__(
            self, "screen_id", require_identifier(self.screen_id, "screen_id")
        )
        object.__setattr__(
            self,
            "repository_revision",
            require_text(self.repository_revision, "repository_revision"),
        )
        scenarios = unique_identifiers(self.scenario_ids, "scenario_ids")
        if not scenarios:
            raise GuiOptimizerDecodeError("scenario_ids must not be empty")
        object.__setattr__(self, "scenario_ids", scenarios)
        object.__setattr__(
            self, "metric_digest", require_digest(self.metric_digest, "metric_digest")
        )
        object.__setattr__(
            self,
            "artifact_digests",
            unique_digests(self.artifact_digests, "artifact_digests"),
        )
        object.__setattr__(
            self,
            "extractor_version",
            require_extractor_version(self.extractor_version),
        )
        object.__setattr__(
            self,
            "interface",
            require_interface(self.interface, UI_BASELINE_INTERFACE),
        )
        object.__setattr__(
            self,
            "schema_version",
            require_schema_version(self.schema_version, UI_BASELINE_SCHEMA),
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
        return _decode_model(
            cls,
            value,
            record_name="UiBaseline",
            builder=lambda p: cls(
                baseline_id=p.get("baseline_id", ""),
                application_id=p.get("application_id", ""),
                screen_id=p.get("screen_id", ""),
                repository_revision=p.get("repository_revision", ""),
                scenario_ids=tuple(p.get("scenario_ids", ())),
                metric_digest=p.get("metric_digest", ""),
                artifact_digests=tuple(p.get("artifact_digests", ())),
                extractor_version=p.get("extractor_version", "1.0.0"),
                interface=p.get("interface", UI_BASELINE_INTERFACE),
                schema_version=p.get("schema_version", UI_BASELINE_SCHEMA),
            ),
        )


@dataclass(frozen=True, slots=True)
class UiContextPack(GuiOptimizerModel):
    """Compact, budgeted context pack for proposal generation."""

    pack_id: str
    application_id: str
    screen_id: str
    objective: str
    token_budget: int
    estimated_tokens: int
    raw_source_paths: tuple[str, ...]
    capsule_ids: tuple[str, ...] = ()
    baseline_id: str = ""
    acceptance_criteria: tuple[str, ...] = ()
    excluded_context_explanation: str = ""
    escalation_conditions: tuple[str, ...] = ()
    analysis_classification: AnalysisClassification | str = (
        AnalysisClassification.CONSERVATIVE
    )
    verification_status: VerificationStatus | str = VerificationStatus.UNVERIFIED
    interface: str = UI_CONTEXT_PACK_INTERFACE
    schema_version: str = UI_CONTEXT_PACK_SCHEMA

    INTERFACE: ClassVar[str] = UI_CONTEXT_PACK_INTERFACE
    SCHEMA_VERSION: ClassVar[str] = UI_CONTEXT_PACK_SCHEMA
    _FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "acceptance_criteria",
            "analysis_classification",
            "application_id",
            "baseline_id",
            "capsule_ids",
            "escalation_conditions",
            "estimated_tokens",
            "excluded_context_explanation",
            "interface",
            "objective",
            "pack_id",
            "raw_source_paths",
            "schema_version",
            "screen_id",
            "token_budget",
            "verification_status",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "pack_id", require_identifier(self.pack_id, "pack_id")
        )
        object.__setattr__(
            self,
            "application_id",
            require_identifier(self.application_id, "application_id"),
        )
        object.__setattr__(
            self, "screen_id", require_identifier(self.screen_id, "screen_id")
        )
        object.__setattr__(
            self, "objective", require_text(self.objective, "objective")
        )
        object.__setattr__(
            self,
            "token_budget",
            require_int(self.token_budget, "token_budget", minimum=1),
        )
        object.__setattr__(
            self,
            "estimated_tokens",
            require_int(self.estimated_tokens, "estimated_tokens", minimum=0),
        )
        paths = unique_repo_paths(self.raw_source_paths, "raw_source_paths")
        if not paths:
            raise GuiOptimizerDecodeError(
                "raw_source_paths must include at least one editable source path"
            )
        object.__setattr__(self, "raw_source_paths", paths)
        object.__setattr__(
            self, "capsule_ids", unique_identifiers(self.capsule_ids, "capsule_ids")
        )
        object.__setattr__(
            self, "baseline_id", optional_identifier(self.baseline_id, "baseline_id")
        )
        object.__setattr__(
            self,
            "acceptance_criteria",
            unique_texts(
                self.acceptance_criteria, "acceptance_criteria", preserve_order=True
            ),
        )
        object.__setattr__(
            self,
            "excluded_context_explanation",
            optional_text(
                self.excluded_context_explanation, "excluded_context_explanation"
            ),
        )
        object.__setattr__(
            self,
            "escalation_conditions",
            unique_texts(
                self.escalation_conditions,
                "escalation_conditions",
                preserve_order=True,
            ),
        )
        object.__setattr__(
            self,
            "analysis_classification",
            parse_enum(
                self.analysis_classification,
                AnalysisClassification,
                "analysis_classification",
            ),
        )
        object.__setattr__(
            self,
            "verification_status",
            parse_enum(
                self.verification_status,
                VerificationStatus,
                "verification_status",
            ),
        )
        object.__setattr__(
            self,
            "interface",
            require_interface(self.interface, UI_CONTEXT_PACK_INTERFACE),
        )
        object.__setattr__(
            self,
            "schema_version",
            require_schema_version(self.schema_version, UI_CONTEXT_PACK_SCHEMA),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "acceptance_criteria": list(self.acceptance_criteria),
            "analysis_classification": self.analysis_classification.value,
            "application_id": self.application_id,
            "baseline_id": self.baseline_id,
            "capsule_ids": list(self.capsule_ids),
            "escalation_conditions": list(self.escalation_conditions),
            "estimated_tokens": self.estimated_tokens,
            "excluded_context_explanation": self.excluded_context_explanation,
            "interface": self.interface,
            "objective": self.objective,
            "pack_id": self.pack_id,
            "raw_source_paths": list(self.raw_source_paths),
            "schema_version": self.schema_version,
            "screen_id": self.screen_id,
            "token_budget": self.token_budget,
            "verification_status": self.verification_status.value,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any] | Any) -> UiContextPack:
        return _decode_model(
            cls,
            value,
            record_name="UiContextPack",
            builder=lambda p: cls(
                pack_id=p.get("pack_id", ""),
                application_id=p.get("application_id", ""),
                screen_id=p.get("screen_id", ""),
                objective=p.get("objective", ""),
                token_budget=p.get("token_budget", 0),
                estimated_tokens=p.get("estimated_tokens", 0),
                raw_source_paths=tuple(p.get("raw_source_paths", ())),
                capsule_ids=tuple(p.get("capsule_ids", ())),
                baseline_id=p.get("baseline_id", ""),
                acceptance_criteria=tuple(p.get("acceptance_criteria", ())),
                excluded_context_explanation=p.get(
                    "excluded_context_explanation", ""
                ),
                escalation_conditions=tuple(p.get("escalation_conditions", ())),
                analysis_classification=p.get(
                    "analysis_classification", AnalysisClassification.CONSERVATIVE
                ),
                verification_status=p.get(
                    "verification_status", VerificationStatus.UNVERIFIED
                ),
                interface=p.get("interface", UI_CONTEXT_PACK_INTERFACE),
                schema_version=p.get("schema_version", UI_CONTEXT_PACK_SCHEMA),
            ),
        )


@dataclass(frozen=True, slots=True)
class GuiImprovementProposal(GuiOptimizerModel):
    """Declared improvement proposal with explicit scope and criteria."""

    proposal_id: str
    application_id: str
    screen_id: str
    objective: str
    intended_file_paths: tuple[str, ...]
    intended_component_ids: tuple[str, ...]
    acceptance_criteria: tuple[str, ...]
    expected_test_ids: tuple[str, ...] = ()
    expected_screenshot_ids: tuple[str, ...] = ()
    state_effect_ids: tuple[str, ...] = ()
    visual_effect_summary: str = ""
    route_kind: ProposalRouteKind | str = ProposalRouteKind.DETERMINISTIC_TRANSFORM
    context_pack_id: str = ""
    decision: ProposalDecision | str = ProposalDecision.PENDING
    analysis_classification: AnalysisClassification | str = (
        AnalysisClassification.HEURISTIC
    )
    verification_status: VerificationStatus | str = VerificationStatus.UNVERIFIED
    interface: str = GUI_IMPROVEMENT_PROPOSAL_INTERFACE
    schema_version: str = GUI_IMPROVEMENT_PROPOSAL_SCHEMA

    INTERFACE: ClassVar[str] = GUI_IMPROVEMENT_PROPOSAL_INTERFACE
    SCHEMA_VERSION: ClassVar[str] = GUI_IMPROVEMENT_PROPOSAL_SCHEMA
    _FIELDS: ClassVar[frozenset[str]] = frozenset(
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

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "proposal_id",
            require_identifier(self.proposal_id, "proposal_id"),
        )
        object.__setattr__(
            self,
            "application_id",
            require_identifier(self.application_id, "application_id"),
        )
        object.__setattr__(
            self, "screen_id", require_identifier(self.screen_id, "screen_id")
        )
        object.__setattr__(
            self, "objective", require_text(self.objective, "objective")
        )
        paths = unique_repo_paths(self.intended_file_paths, "intended_file_paths")
        if not paths:
            raise GuiOptimizerDecodeError("intended_file_paths must not be empty")
        object.__setattr__(self, "intended_file_paths", paths)
        components = unique_identifiers(
            self.intended_component_ids, "intended_component_ids"
        )
        if not components:
            raise GuiOptimizerDecodeError("intended_component_ids must not be empty")
        object.__setattr__(self, "intended_component_ids", components)
        criteria = unique_texts(
            self.acceptance_criteria, "acceptance_criteria", preserve_order=True
        )
        if not criteria:
            raise GuiOptimizerDecodeError("acceptance_criteria must not be empty")
        object.__setattr__(self, "acceptance_criteria", criteria)
        object.__setattr__(
            self,
            "expected_test_ids",
            unique_identifiers(self.expected_test_ids, "expected_test_ids"),
        )
        object.__setattr__(
            self,
            "expected_screenshot_ids",
            unique_identifiers(
                self.expected_screenshot_ids, "expected_screenshot_ids"
            ),
        )
        object.__setattr__(
            self,
            "state_effect_ids",
            unique_identifiers(self.state_effect_ids, "state_effect_ids"),
        )
        object.__setattr__(
            self,
            "visual_effect_summary",
            optional_text(self.visual_effect_summary, "visual_effect_summary"),
        )
        object.__setattr__(
            self,
            "route_kind",
            parse_enum(self.route_kind, ProposalRouteKind, "route_kind"),
        )
        object.__setattr__(
            self,
            "context_pack_id",
            optional_identifier(self.context_pack_id, "context_pack_id"),
        )
        object.__setattr__(
            self,
            "decision",
            parse_enum(self.decision, ProposalDecision, "decision"),
        )
        object.__setattr__(
            self,
            "analysis_classification",
            parse_enum(
                self.analysis_classification,
                AnalysisClassification,
                "analysis_classification",
            ),
        )
        object.__setattr__(
            self,
            "verification_status",
            parse_enum(
                self.verification_status,
                VerificationStatus,
                "verification_status",
            ),
        )
        object.__setattr__(
            self,
            "interface",
            require_interface(self.interface, GUI_IMPROVEMENT_PROPOSAL_INTERFACE),
        )
        object.__setattr__(
            self,
            "schema_version",
            require_schema_version(
                self.schema_version, GUI_IMPROVEMENT_PROPOSAL_SCHEMA
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
        return _decode_model(
            cls,
            value,
            record_name="GuiImprovementProposal",
            builder=lambda p: cls(
                proposal_id=p.get("proposal_id", ""),
                application_id=p.get("application_id", ""),
                screen_id=p.get("screen_id", ""),
                objective=p.get("objective", ""),
                intended_file_paths=tuple(p.get("intended_file_paths", ())),
                intended_component_ids=tuple(p.get("intended_component_ids", ())),
                acceptance_criteria=tuple(p.get("acceptance_criteria", ())),
                expected_test_ids=tuple(p.get("expected_test_ids", ())),
                expected_screenshot_ids=tuple(p.get("expected_screenshot_ids", ())),
                state_effect_ids=tuple(p.get("state_effect_ids", ())),
                visual_effect_summary=p.get("visual_effect_summary", ""),
                route_kind=p.get(
                    "route_kind", ProposalRouteKind.DETERMINISTIC_TRANSFORM
                ),
                context_pack_id=p.get("context_pack_id", ""),
                decision=p.get("decision", ProposalDecision.PENDING),
                analysis_classification=p.get(
                    "analysis_classification", AnalysisClassification.HEURISTIC
                ),
                verification_status=p.get(
                    "verification_status", VerificationStatus.UNVERIFIED
                ),
                interface=p.get("interface", GUI_IMPROVEMENT_PROPOSAL_INTERFACE),
                schema_version=p.get(
                    "schema_version", GUI_IMPROVEMENT_PROPOSAL_SCHEMA
                ),
            ),
        )


# ---------------------------------------------------------------------------
# Receipt models
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class VisualRegressionReceipt(GuiOptimizerModel):
    """Immutable visual comparison receipt for one scenario."""

    receipt_id: str
    application_id: str
    screen_id: str
    scenario_id: str
    repository_revision: str
    component_version_ids: tuple[str, ...]
    viewport: ViewportSpec | Mapping[str, Any]
    screenshot_digest: str
    baseline_digest: str
    decision: VisualDecision | str
    evidence_level: EvidenceLevel | str
    pixel_diff_percent: float | int = 0
    requires_human_review: bool = False
    color_scheme: str = "light"
    locale: str = "en-US"
    text_scale_percent: int = 100
    browser: str = ""
    browser_version: str = ""
    analysis_classification: AnalysisClassification | str = (
        AnalysisClassification.HEURISTIC
    )
    verification_status: VerificationStatus | str = VerificationStatus.UNVERIFIED
    interface: str = VISUAL_REGRESSION_RECEIPT_INTERFACE
    schema_version: str = VISUAL_REGRESSION_RECEIPT_SCHEMA

    INTERFACE: ClassVar[str] = VISUAL_REGRESSION_RECEIPT_INTERFACE
    SCHEMA_VERSION: ClassVar[str] = VISUAL_REGRESSION_RECEIPT_SCHEMA
    _FIELDS: ClassVar[frozenset[str]] = frozenset(
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
            "interface",
            "locale",
            "pixel_diff_percent",
            "receipt_id",
            "repository_revision",
            "requires_human_review",
            "scenario_id",
            "schema_version",
            "screen_id",
            "screenshot_digest",
            "text_scale_percent",
            "verification_status",
            "viewport",
        }
    )

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "receipt_id", require_identifier(self.receipt_id, "receipt_id")
        )
        object.__setattr__(
            self,
            "application_id",
            require_identifier(self.application_id, "application_id"),
        )
        object.__setattr__(
            self, "screen_id", require_identifier(self.screen_id, "screen_id")
        )
        object.__setattr__(
            self, "scenario_id", require_identifier(self.scenario_id, "scenario_id")
        )
        object.__setattr__(
            self,
            "repository_revision",
            require_text(self.repository_revision, "repository_revision"),
        )
        object.__setattr__(
            self,
            "component_version_ids",
            unique_identifiers(self.component_version_ids, "component_version_ids"),
        )
        viewport = self.viewport
        if isinstance(viewport, Mapping):
            viewport = ViewportSpec.from_dict(viewport)
        if not isinstance(viewport, ViewportSpec):
            raise GuiOptimizerDecodeError("viewport must be a ViewportSpec")
        object.__setattr__(self, "viewport", viewport)
        object.__setattr__(
            self,
            "screenshot_digest",
            require_digest(self.screenshot_digest, "screenshot_digest"),
        )
        object.__setattr__(
            self,
            "baseline_digest",
            require_digest(self.baseline_digest, "baseline_digest"),
        )
        object.__setattr__(
            self, "decision", parse_enum(self.decision, VisualDecision, "decision")
        )
        object.__setattr__(
            self,
            "evidence_level",
            parse_enum(self.evidence_level, EvidenceLevel, "evidence_level"),
        )
        diff = require_finite_number(self.pixel_diff_percent, "pixel_diff_percent")
        if float(diff) < 0 or float(diff) > 100:
            raise GuiOptimizerDecodeError(
                "pixel_diff_percent must be in the closed range 0..100"
            )
        object.__setattr__(self, "pixel_diff_percent", diff)
        object.__setattr__(
            self,
            "requires_human_review",
            require_bool(self.requires_human_review, "requires_human_review"),
        )
        object.__setattr__(
            self, "color_scheme", require_text(self.color_scheme, "color_scheme")
        )
        object.__setattr__(self, "locale", require_text(self.locale, "locale"))
        object.__setattr__(
            self,
            "text_scale_percent",
            require_int(
                self.text_scale_percent,
                "text_scale_percent",
                minimum=25,
                maximum=500,
            ),
        )
        object.__setattr__(self, "browser", optional_text(self.browser, "browser"))
        object.__setattr__(
            self,
            "browser_version",
            optional_text(self.browser_version, "browser_version"),
        )
        object.__setattr__(
            self,
            "analysis_classification",
            parse_enum(
                self.analysis_classification,
                AnalysisClassification,
                "analysis_classification",
            ),
        )
        object.__setattr__(
            self,
            "verification_status",
            parse_enum(
                self.verification_status,
                VerificationStatus,
                "verification_status",
            ),
        )
        object.__setattr__(
            self,
            "interface",
            require_interface(self.interface, VISUAL_REGRESSION_RECEIPT_INTERFACE),
        )
        object.__setattr__(
            self,
            "schema_version",
            require_schema_version(
                self.schema_version, VISUAL_REGRESSION_RECEIPT_SCHEMA
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
            "interface": self.interface,
            "locale": self.locale,
            "pixel_diff_percent": self.pixel_diff_percent,
            "receipt_id": self.receipt_id,
            "repository_revision": self.repository_revision,
            "requires_human_review": self.requires_human_review,
            "scenario_id": self.scenario_id,
            "schema_version": self.schema_version,
            "screen_id": self.screen_id,
            "screenshot_digest": self.screenshot_digest,
            "text_scale_percent": self.text_scale_percent,
            "verification_status": self.verification_status.value,
            "viewport": self.viewport.to_dict(),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any] | Any) -> VisualRegressionReceipt:
        return _decode_model(
            cls,
            value,
            record_name="VisualRegressionReceipt",
            builder=lambda p: cls(
                receipt_id=p.get("receipt_id", ""),
                application_id=p.get("application_id", ""),
                screen_id=p.get("screen_id", ""),
                scenario_id=p.get("scenario_id", ""),
                repository_revision=p.get("repository_revision", ""),
                component_version_ids=tuple(p.get("component_version_ids", ())),
                viewport=p.get("viewport", {}),
                screenshot_digest=p.get("screenshot_digest", ""),
                baseline_digest=p.get("baseline_digest", ""),
                decision=p.get("decision", ""),
                evidence_level=p.get("evidence_level", ""),
                pixel_diff_percent=p.get("pixel_diff_percent", 0),
                requires_human_review=p.get("requires_human_review", False),
                color_scheme=p.get("color_scheme", "light"),
                locale=p.get("locale", "en-US"),
                text_scale_percent=p.get("text_scale_percent", 100),
                browser=p.get("browser", ""),
                browser_version=p.get("browser_version", ""),
                analysis_classification=p.get(
                    "analysis_classification", AnalysisClassification.HEURISTIC
                ),
                verification_status=p.get(
                    "verification_status", VerificationStatus.UNVERIFIED
                ),
                interface=p.get("interface", VISUAL_REGRESSION_RECEIPT_INTERFACE),
                schema_version=p.get(
                    "schema_version", VISUAL_REGRESSION_RECEIPT_SCHEMA
                ),
            ),
        )


@dataclass(frozen=True, slots=True)
class AccessibilityReceipt(GuiOptimizerModel):
    """Accessibility evaluation receipt with explicit non-certification labels."""

    receipt_id: str
    application_id: str
    screen_id: str
    scenario_id: str
    repository_revision: str
    automated_pass_count: int
    violation_count: int
    violation_ids: tuple[str, ...]
    manual_check_ids: tuple[str, ...]
    unsupported_criteria: tuple[str, ...]
    keyboard_result: ConstraintCheckStatus | str
    screen_reader_reviewed: bool
    evidence_level: EvidenceLevel | str
    analysis_classification: AnalysisClassification | str = (
        AnalysisClassification.EXACT
    )
    verification_status: VerificationStatus | str = (
        VerificationStatus.STRUCTURALLY_VALID
    )
    interface: str = ACCESSIBILITY_RECEIPT_INTERFACE
    schema_version: str = ACCESSIBILITY_RECEIPT_SCHEMA

    INTERFACE: ClassVar[str] = ACCESSIBILITY_RECEIPT_INTERFACE
    SCHEMA_VERSION: ClassVar[str] = ACCESSIBILITY_RECEIPT_SCHEMA
    _FIELDS: ClassVar[frozenset[str]] = frozenset(
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

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "receipt_id", require_identifier(self.receipt_id, "receipt_id")
        )
        object.__setattr__(
            self,
            "application_id",
            require_identifier(self.application_id, "application_id"),
        )
        object.__setattr__(
            self, "screen_id", require_identifier(self.screen_id, "screen_id")
        )
        object.__setattr__(
            self, "scenario_id", require_identifier(self.scenario_id, "scenario_id")
        )
        object.__setattr__(
            self,
            "repository_revision",
            require_text(self.repository_revision, "repository_revision"),
        )
        object.__setattr__(
            self,
            "automated_pass_count",
            require_int(self.automated_pass_count, "automated_pass_count", minimum=0),
        )
        object.__setattr__(
            self,
            "violation_count",
            require_int(self.violation_count, "violation_count", minimum=0),
        )
        object.__setattr__(
            self,
            "violation_ids",
            unique_identifiers(self.violation_ids, "violation_ids"),
        )
        if self.violation_count != len(self.violation_ids):
            raise GuiOptimizerDecodeError(
                "violation_count must equal the number of violation_ids"
            )
        object.__setattr__(
            self,
            "manual_check_ids",
            unique_identifiers(self.manual_check_ids, "manual_check_ids"),
        )
        object.__setattr__(
            self,
            "unsupported_criteria",
            unique_texts(
                self.unsupported_criteria,
                "unsupported_criteria",
                preserve_order=True,
            ),
        )
        object.__setattr__(
            self,
            "keyboard_result",
            parse_enum(
                self.keyboard_result, ConstraintCheckStatus, "keyboard_result"
            ),
        )
        object.__setattr__(
            self,
            "screen_reader_reviewed",
            require_bool(self.screen_reader_reviewed, "screen_reader_reviewed"),
        )
        object.__setattr__(
            self,
            "evidence_level",
            parse_enum(self.evidence_level, EvidenceLevel, "evidence_level"),
        )
        object.__setattr__(
            self,
            "analysis_classification",
            parse_enum(
                self.analysis_classification,
                AnalysisClassification,
                "analysis_classification",
            ),
        )
        object.__setattr__(
            self,
            "verification_status",
            parse_enum(
                self.verification_status,
                VerificationStatus,
                "verification_status",
            ),
        )
        object.__setattr__(
            self,
            "interface",
            require_interface(self.interface, ACCESSIBILITY_RECEIPT_INTERFACE),
        )
        object.__setattr__(
            self,
            "schema_version",
            require_schema_version(self.schema_version, ACCESSIBILITY_RECEIPT_SCHEMA),
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
        return _decode_model(
            cls,
            value,
            record_name="AccessibilityReceipt",
            builder=lambda p: cls(
                receipt_id=p.get("receipt_id", ""),
                application_id=p.get("application_id", ""),
                screen_id=p.get("screen_id", ""),
                scenario_id=p.get("scenario_id", ""),
                repository_revision=p.get("repository_revision", ""),
                automated_pass_count=p.get("automated_pass_count", 0),
                violation_count=p.get("violation_count", 0),
                violation_ids=tuple(p.get("violation_ids", ())),
                manual_check_ids=tuple(p.get("manual_check_ids", ())),
                unsupported_criteria=tuple(p.get("unsupported_criteria", ())),
                keyboard_result=p.get("keyboard_result", ""),
                screen_reader_reviewed=p.get("screen_reader_reviewed", False),
                evidence_level=p.get("evidence_level", ""),
                analysis_classification=p.get(
                    "analysis_classification", AnalysisClassification.EXACT
                ),
                verification_status=p.get(
                    "verification_status",
                    VerificationStatus.STRUCTURALLY_VALID,
                ),
                interface=p.get("interface", ACCESSIBILITY_RECEIPT_INTERFACE),
                schema_version=p.get("schema_version", ACCESSIBILITY_RECEIPT_SCHEMA),
            ),
        )


@dataclass(frozen=True, slots=True)
class InteractionReceipt(GuiOptimizerModel):
    """Interaction / keyboard path receipt for a controlled scenario."""

    receipt_id: str
    application_id: str
    screen_id: str
    scenario_id: str
    repository_revision: str
    step_ids: tuple[str, ...]
    focus_sequence: tuple[str, ...]
    event_ids: tuple[str, ...]
    action_invocation_ids: tuple[str, ...]
    confirmation_id: str = ""
    recovery_ids: tuple[str, ...] = ()
    unresolved_observation_ids: tuple[str, ...] = ()
    evidence_level: EvidenceLevel | str = EvidenceLevel.AUTOMATED
    analysis_classification: AnalysisClassification | str = (
        AnalysisClassification.EXACT
    )
    verification_status: VerificationStatus | str = (
        VerificationStatus.STRUCTURALLY_VALID
    )
    interface: str = INTERACTION_RECEIPT_INTERFACE
    schema_version: str = INTERACTION_RECEIPT_SCHEMA

    INTERFACE: ClassVar[str] = INTERACTION_RECEIPT_INTERFACE
    SCHEMA_VERSION: ClassVar[str] = INTERACTION_RECEIPT_SCHEMA
    _FIELDS: ClassVar[frozenset[str]] = frozenset(
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

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "receipt_id", require_identifier(self.receipt_id, "receipt_id")
        )
        object.__setattr__(
            self,
            "application_id",
            require_identifier(self.application_id, "application_id"),
        )
        object.__setattr__(
            self, "screen_id", require_identifier(self.screen_id, "screen_id")
        )
        object.__setattr__(
            self, "scenario_id", require_identifier(self.scenario_id, "scenario_id")
        )
        object.__setattr__(
            self,
            "repository_revision",
            require_text(self.repository_revision, "repository_revision"),
        )
        steps = unique_identifiers(self.step_ids, "step_ids", preserve_order=True)
        if not steps:
            raise GuiOptimizerDecodeError("step_ids must not be empty")
        object.__setattr__(self, "step_ids", steps)
        object.__setattr__(
            self,
            "focus_sequence",
            unique_texts(
                self.focus_sequence, "focus_sequence", preserve_order=True
            ),
        )
        object.__setattr__(
            self,
            "event_ids",
            unique_identifiers(self.event_ids, "event_ids", preserve_order=True),
        )
        object.__setattr__(
            self,
            "action_invocation_ids",
            unique_identifiers(
                self.action_invocation_ids,
                "action_invocation_ids",
                preserve_order=True,
            ),
        )
        object.__setattr__(
            self,
            "confirmation_id",
            optional_identifier(self.confirmation_id, "confirmation_id"),
        )
        object.__setattr__(
            self,
            "recovery_ids",
            unique_identifiers(self.recovery_ids, "recovery_ids"),
        )
        object.__setattr__(
            self,
            "unresolved_observation_ids",
            unique_identifiers(
                self.unresolved_observation_ids, "unresolved_observation_ids"
            ),
        )
        object.__setattr__(
            self,
            "evidence_level",
            parse_enum(self.evidence_level, EvidenceLevel, "evidence_level"),
        )
        object.__setattr__(
            self,
            "analysis_classification",
            parse_enum(
                self.analysis_classification,
                AnalysisClassification,
                "analysis_classification",
            ),
        )
        object.__setattr__(
            self,
            "verification_status",
            parse_enum(
                self.verification_status,
                VerificationStatus,
                "verification_status",
            ),
        )
        object.__setattr__(
            self,
            "interface",
            require_interface(self.interface, INTERACTION_RECEIPT_INTERFACE),
        )
        object.__setattr__(
            self,
            "schema_version",
            require_schema_version(self.schema_version, INTERACTION_RECEIPT_SCHEMA),
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
        return _decode_model(
            cls,
            value,
            record_name="InteractionReceipt",
            builder=lambda p: cls(
                receipt_id=p.get("receipt_id", ""),
                application_id=p.get("application_id", ""),
                screen_id=p.get("screen_id", ""),
                scenario_id=p.get("scenario_id", ""),
                repository_revision=p.get("repository_revision", ""),
                step_ids=tuple(p.get("step_ids", ())),
                focus_sequence=tuple(p.get("focus_sequence", ())),
                event_ids=tuple(p.get("event_ids", ())),
                action_invocation_ids=tuple(p.get("action_invocation_ids", ())),
                confirmation_id=p.get("confirmation_id", ""),
                recovery_ids=tuple(p.get("recovery_ids", ())),
                unresolved_observation_ids=tuple(
                    p.get("unresolved_observation_ids", ())
                ),
                evidence_level=p.get("evidence_level", EvidenceLevel.AUTOMATED),
                analysis_classification=p.get(
                    "analysis_classification", AnalysisClassification.EXACT
                ),
                verification_status=p.get(
                    "verification_status",
                    VerificationStatus.STRUCTURALLY_VALID,
                ),
                interface=p.get("interface", INTERACTION_RECEIPT_INTERFACE),
                schema_version=p.get("schema_version", INTERACTION_RECEIPT_SCHEMA),
            ),
        )


@dataclass(frozen=True, slots=True)
class UiConstraintReceipt(GuiOptimizerModel):
    """Bounded formal/structural constraint check receipt."""

    receipt_id: str
    application_id: str
    screen_id: str
    repository_revision: str
    check_ids: tuple[str, ...]
    statuses: tuple[ConstraintCheckStatus | str, ...]
    violated_check_ids: tuple[str, ...] = ()
    unsupported_check_ids: tuple[str, ...] = ()
    solver_id: str = ""
    evidence_level: EvidenceLevel | str = EvidenceLevel.STRUCTURAL
    analysis_classification: AnalysisClassification | str = (
        AnalysisClassification.EXACT
    )
    verification_status: VerificationStatus | str = (
        VerificationStatus.STRUCTURALLY_VALID
    )
    interface: str = UI_CONSTRAINT_RECEIPT_INTERFACE
    schema_version: str = UI_CONSTRAINT_RECEIPT_SCHEMA

    INTERFACE: ClassVar[str] = UI_CONSTRAINT_RECEIPT_INTERFACE
    SCHEMA_VERSION: ClassVar[str] = UI_CONSTRAINT_RECEIPT_SCHEMA
    _FIELDS: ClassVar[frozenset[str]] = frozenset(
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

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "receipt_id", require_identifier(self.receipt_id, "receipt_id")
        )
        object.__setattr__(
            self,
            "application_id",
            require_identifier(self.application_id, "application_id"),
        )
        object.__setattr__(
            self, "screen_id", require_identifier(self.screen_id, "screen_id")
        )
        object.__setattr__(
            self,
            "repository_revision",
            require_text(self.repository_revision, "repository_revision"),
        )
        checks = unique_identifiers(
            self.check_ids, "check_ids", preserve_order=True
        )
        if not checks:
            raise GuiOptimizerDecodeError("check_ids must not be empty")
        object.__setattr__(self, "check_ids", checks)
        if isinstance(self.statuses, (str, bytes, bytearray)) or not isinstance(
            self.statuses, Sequence
        ):
            raise GuiOptimizerDecodeError("statuses must be a sequence")
        statuses = tuple(
            parse_enum(item, ConstraintCheckStatus, "statuses item")
            for item in self.statuses
        )
        if len(statuses) != len(checks):
            raise GuiOptimizerDecodeError(
                "statuses must align 1:1 with check_ids"
            )
        object.__setattr__(self, "statuses", statuses)
        object.__setattr__(
            self,
            "violated_check_ids",
            unique_identifiers(self.violated_check_ids, "violated_check_ids"),
        )
        object.__setattr__(
            self,
            "unsupported_check_ids",
            unique_identifiers(
                self.unsupported_check_ids, "unsupported_check_ids"
            ),
        )
        unknown_violations = sorted(set(self.violated_check_ids) - set(checks))
        if unknown_violations:
            raise GuiOptimizerDecodeError(
                f"violated_check_ids references unknown checks: "
                f"{', '.join(unknown_violations)}"
            )
        object.__setattr__(
            self, "solver_id", optional_identifier(self.solver_id, "solver_id")
        )
        object.__setattr__(
            self,
            "evidence_level",
            parse_enum(self.evidence_level, EvidenceLevel, "evidence_level"),
        )
        object.__setattr__(
            self,
            "analysis_classification",
            parse_enum(
                self.analysis_classification,
                AnalysisClassification,
                "analysis_classification",
            ),
        )
        object.__setattr__(
            self,
            "verification_status",
            parse_enum(
                self.verification_status,
                VerificationStatus,
                "verification_status",
            ),
        )
        object.__setattr__(
            self,
            "interface",
            require_interface(self.interface, UI_CONSTRAINT_RECEIPT_INTERFACE),
        )
        object.__setattr__(
            self,
            "schema_version",
            require_schema_version(self.schema_version, UI_CONSTRAINT_RECEIPT_SCHEMA),
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
        return _decode_model(
            cls,
            value,
            record_name="UiConstraintReceipt",
            builder=lambda p: cls(
                receipt_id=p.get("receipt_id", ""),
                application_id=p.get("application_id", ""),
                screen_id=p.get("screen_id", ""),
                repository_revision=p.get("repository_revision", ""),
                check_ids=tuple(p.get("check_ids", ())),
                statuses=tuple(p.get("statuses", ())),
                violated_check_ids=tuple(p.get("violated_check_ids", ())),
                unsupported_check_ids=tuple(p.get("unsupported_check_ids", ())),
                solver_id=p.get("solver_id", ""),
                evidence_level=p.get("evidence_level", EvidenceLevel.STRUCTURAL),
                analysis_classification=p.get(
                    "analysis_classification", AnalysisClassification.EXACT
                ),
                verification_status=p.get(
                    "verification_status",
                    VerificationStatus.STRUCTURALLY_VALID,
                ),
                interface=p.get("interface", UI_CONSTRAINT_RECEIPT_INTERFACE),
                schema_version=p.get("schema_version", UI_CONSTRAINT_RECEIPT_SCHEMA),
            ),
        )


@dataclass(frozen=True, slots=True)
class GuiImprovementReceipt(GuiOptimizerModel):
    """Aggregate improvement receipt binding all evidence classes."""

    receipt_id: str
    proposal_id: str
    application_id: str
    screen_id: str
    repository_revision: str
    decision: ProposalDecision | str
    visual_receipt_ids: tuple[str, ...]
    accessibility_receipt_ids: tuple[str, ...]
    interaction_receipt_ids: tuple[str, ...]
    constraint_receipt_ids: tuple[str, ...]
    invalidation_plan_id: str = ""
    context_pack_id: str = ""
    patch_digest: str = ""
    rejection_reasons: tuple[str, ...] = ()
    analysis_classification: AnalysisClassification | str = (
        AnalysisClassification.CONSERVATIVE
    )
    verification_status: VerificationStatus | str = VerificationStatus.UNVERIFIED
    interface: str = GUI_IMPROVEMENT_RECEIPT_INTERFACE
    schema_version: str = GUI_IMPROVEMENT_RECEIPT_SCHEMA

    INTERFACE: ClassVar[str] = GUI_IMPROVEMENT_RECEIPT_INTERFACE
    SCHEMA_VERSION: ClassVar[str] = GUI_IMPROVEMENT_RECEIPT_SCHEMA
    _FIELDS: ClassVar[frozenset[str]] = frozenset(
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

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "receipt_id", require_identifier(self.receipt_id, "receipt_id")
        )
        object.__setattr__(
            self,
            "proposal_id",
            require_identifier(self.proposal_id, "proposal_id"),
        )
        object.__setattr__(
            self,
            "application_id",
            require_identifier(self.application_id, "application_id"),
        )
        object.__setattr__(
            self, "screen_id", require_identifier(self.screen_id, "screen_id")
        )
        object.__setattr__(
            self,
            "repository_revision",
            require_text(self.repository_revision, "repository_revision"),
        )
        object.__setattr__(
            self,
            "decision",
            parse_enum(self.decision, ProposalDecision, "decision"),
        )
        object.__setattr__(
            self,
            "visual_receipt_ids",
            unique_identifiers(self.visual_receipt_ids, "visual_receipt_ids"),
        )
        object.__setattr__(
            self,
            "accessibility_receipt_ids",
            unique_identifiers(
                self.accessibility_receipt_ids, "accessibility_receipt_ids"
            ),
        )
        object.__setattr__(
            self,
            "interaction_receipt_ids",
            unique_identifiers(
                self.interaction_receipt_ids, "interaction_receipt_ids"
            ),
        )
        object.__setattr__(
            self,
            "constraint_receipt_ids",
            unique_identifiers(
                self.constraint_receipt_ids, "constraint_receipt_ids"
            ),
        )
        object.__setattr__(
            self,
            "invalidation_plan_id",
            optional_identifier(self.invalidation_plan_id, "invalidation_plan_id"),
        )
        object.__setattr__(
            self,
            "context_pack_id",
            optional_identifier(self.context_pack_id, "context_pack_id"),
        )
        object.__setattr__(
            self, "patch_digest", optional_digest(self.patch_digest, "patch_digest")
        )
        object.__setattr__(
            self,
            "rejection_reasons",
            unique_texts(
                self.rejection_reasons, "rejection_reasons", preserve_order=True
            ),
        )
        if self.decision is ProposalDecision.ACCEPT:
            missing = []
            if not self.visual_receipt_ids:
                missing.append("visual_receipt_ids")
            if not self.accessibility_receipt_ids:
                missing.append("accessibility_receipt_ids")
            if not self.interaction_receipt_ids:
                missing.append("interaction_receipt_ids")
            if not self.constraint_receipt_ids:
                missing.append("constraint_receipt_ids")
            if missing:
                raise GuiOptimizerDecodeError(
                    "accepted GuiImprovementReceipt requires all four receipt "
                    f"classes; missing: {', '.join(missing)}"
                )
        if (
            self.decision is ProposalDecision.REJECT
            and not self.rejection_reasons
        ):
            raise GuiOptimizerDecodeError(
                "rejected GuiImprovementReceipt requires rejection_reasons"
            )
        object.__setattr__(
            self,
            "analysis_classification",
            parse_enum(
                self.analysis_classification,
                AnalysisClassification,
                "analysis_classification",
            ),
        )
        object.__setattr__(
            self,
            "verification_status",
            parse_enum(
                self.verification_status,
                VerificationStatus,
                "verification_status",
            ),
        )
        object.__setattr__(
            self,
            "interface",
            require_interface(self.interface, GUI_IMPROVEMENT_RECEIPT_INTERFACE),
        )
        object.__setattr__(
            self,
            "schema_version",
            require_schema_version(
                self.schema_version, GUI_IMPROVEMENT_RECEIPT_SCHEMA
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
        return _decode_model(
            cls,
            value,
            record_name="GuiImprovementReceipt",
            builder=lambda p: cls(
                receipt_id=p.get("receipt_id", ""),
                proposal_id=p.get("proposal_id", ""),
                application_id=p.get("application_id", ""),
                screen_id=p.get("screen_id", ""),
                repository_revision=p.get("repository_revision", ""),
                decision=p.get("decision", ""),
                visual_receipt_ids=tuple(p.get("visual_receipt_ids", ())),
                accessibility_receipt_ids=tuple(
                    p.get("accessibility_receipt_ids", ())
                ),
                interaction_receipt_ids=tuple(p.get("interaction_receipt_ids", ())),
                constraint_receipt_ids=tuple(p.get("constraint_receipt_ids", ())),
                invalidation_plan_id=p.get("invalidation_plan_id", ""),
                context_pack_id=p.get("context_pack_id", ""),
                patch_digest=p.get("patch_digest", ""),
                rejection_reasons=tuple(p.get("rejection_reasons", ())),
                analysis_classification=p.get(
                    "analysis_classification",
                    AnalysisClassification.CONSERVATIVE,
                ),
                verification_status=p.get(
                    "verification_status", VerificationStatus.UNVERIFIED
                ),
                interface=p.get("interface", GUI_IMPROVEMENT_RECEIPT_INTERFACE),
                schema_version=p.get(
                    "schema_version", GUI_IMPROVEMENT_RECEIPT_SCHEMA
                ),
            ),
        )


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

MODEL_TYPES: Final[Mapping[str, type[GuiOptimizerModel]]] = {
    GUI_APPLICATION_IDENTITY_INTERFACE: GuiApplicationIdentity,
    GUI_SCREEN_IDENTITY_INTERFACE: GuiScreenIdentity,
    UI_COMPONENT_IDENTITY_INTERFACE: UiComponentIdentity,
    UI_COMPONENT_VERSION_INTERFACE: UiComponentVersion,
    UI_DEPENDENCY_EDGE_INTERFACE: UiDependencyEdge,
    UI_STATE_DEFINITION_INTERFACE: UiStateDefinition,
    UI_EVENT_DEFINITION_INTERFACE: UiEventDefinition,
    UI_TRANSITION_DEFINITION_INTERFACE: UiTransitionDefinition,
    UI_ACTION_BINDING_INTERFACE: UiActionBinding,
    UI_LAYOUT_CONSTRAINT_INTERFACE: UiLayoutConstraint,
    UI_ACCESSIBILITY_CONTRACT_INTERFACE: UiAccessibilityContract,
    UI_SEMANTIC_CAPSULE_INTERFACE: UiSemanticCapsule,
    UI_CHANGE_SET_INTERFACE: UiChangeSet,
    UI_INVALIDATION_PLAN_INTERFACE: UiInvalidationPlan,
    UI_EVALUATION_SCENARIO_INTERFACE: UiEvaluationScenario,
    UI_BASELINE_INTERFACE: UiBaseline,
    UI_CONTEXT_PACK_INTERFACE: UiContextPack,
    GUI_IMPROVEMENT_PROPOSAL_INTERFACE: GuiImprovementProposal,
    VISUAL_REGRESSION_RECEIPT_INTERFACE: VisualRegressionReceipt,
    ACCESSIBILITY_RECEIPT_INTERFACE: AccessibilityReceipt,
    INTERACTION_RECEIPT_INTERFACE: InteractionReceipt,
    UI_CONSTRAINT_RECEIPT_INTERFACE: UiConstraintReceipt,
    GUI_IMPROVEMENT_RECEIPT_INTERFACE: GuiImprovementReceipt,
}


def decode_model(value: Mapping[str, Any] | Any) -> GuiOptimizerModel:
    """Decode any required model by its closed interface field."""

    payload = require_mapping(value, "model")
    interface = require_text(payload.get("interface", ""), "interface")
    model_cls = MODEL_TYPES.get(interface)
    if model_cls is None:
        raise GuiOptimizerDecodeError(f"unsupported model interface: {interface!r}")
    return model_cls.from_dict(payload)


def required_model_inventory() -> tuple[str, ...]:
    """Return the sealed inventory of required model interfaces."""

    return REQUIRED_MODEL_INTERFACES


def assert_required_models_registered() -> None:
    """Fail closed if any required interface is missing from MODEL_TYPES."""

    missing = [
        interface
        for interface in REQUIRED_MODEL_INTERFACES
        if interface not in MODEL_TYPES
    ]
    if missing:
        raise GuiOptimizerDecodeError(
            f"missing required model registration(s): {', '.join(missing)}"
        )
    for interface, model_cls in MODEL_TYPES.items():
        expected_schema = SCHEMA_VERSION_BY_INTERFACE[interface]
        if model_cls.INTERFACE != interface:
            raise GuiOptimizerDecodeError(
                f"model {model_cls.__name__} interface mismatch"
            )
        if model_cls.SCHEMA_VERSION != expected_schema:
            raise GuiOptimizerDecodeError(
                f"model {model_cls.__name__} schema_version mismatch"
            )


__all__ = [
    "CANONICAL_JSON_PROFILE",
    "MODEL_TYPES",
    "SourceSpan",
    "ViewportSpec",
    "GuiOptimizerModel",
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
