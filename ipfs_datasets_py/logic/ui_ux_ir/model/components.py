"""Semantic component composition graph (UIComponentGraph@1).

Components are semantic nodes, not framework widgets. This module models:

- stable IDs and ARIA-aligned / namespaced roles;
- purpose, accessible name/description references;
- value, selection, validation, and enabled/visible semantics;
- parent/child/slot/label/described-by/owns/flow relationships;
- action affordances and modality/data/program/feedback bindings;
- privacy sensitivity and presentation classification; and
- optional target hints that cannot override semantic requirements.

Hierarchical relationships (parent, child, owns) must be acyclic. Label,
described-by, slot, and flow edges may form non-tree graphs but still require
closed references. Executable callbacks and framework class names as canonical
roles are rejected.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Any, Final, Iterable, Mapping, Sequence

from ..schema import (
    CompositionEdgeKind,
    UIComponent,
    UICompositionEdge,
    UIIRValidationError,
)

UI_COMPONENT_GRAPH_INTERFACE: Final = "UIComponentGraph@1"
UI_COMPONENT_GRAPH_SCHEMA_VERSION: Final = "ui-component-graph/v1"

_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$")
_ROLE_RE = re.compile(
    r"^(aria:[A-Za-z][A-Za-z0-9_-]{0,63}"
    r"|[A-Za-z][A-Za-z0-9_-]{0,63}"
    r"|[A-Za-z][A-Za-z0-9_-]{0,63}(\.[A-Za-z][A-Za-z0-9_-]{0,63})+"
    r"|[A-Za-z][A-Za-z0-9_-]{0,63}:[A-Za-z][A-Za-z0-9._-]{0,127})$"
)

# Hierarchical edge kinds that must not introduce cycles.
_HIERARCHICAL_EDGE_KINDS: Final = frozenset(
    {
        CompositionEdgeKind.PARENT,
        CompositionEdgeKind.CHILD,
        CompositionEdgeKind.OWNS,
    }
)

# Framework / target class names must never be used as canonical roles.
_FORBIDDEN_ROLE_TOKENS: Final = frozenset(
    {
        "React.Component",
        "React.FC",
        "HTMLElement",
        "HTMLButtonElement",
        "HTMLDivElement",
        "UIView",
        "UIViewController",
        "android.view.View",
        "android.widget.Button",
        "SwiftUI.View",
        "Vue.Component",
        "Angular.Component",
    }
)

_FORBIDDEN_EXECUTABLE_KEYS: Final = frozenset(
    {
        "callback",
        "callbacks",
        "code",
        "eval",
        "exec",
        "executable",
        "fn",
        "function",
        "handler",
        "handlers",
        "javascript",
        "jsx",
        "lambda",
        "listener",
        "listeners",
        "on_blur",
        "on_change",
        "on_click",
        "on_focus",
        "on_input",
        "on_submit",
        "onchange",
        "onclick",
        "onsubmit",
        "script",
        "scripts",
        "tsx",
    }
)
_FORBIDDEN_EXECUTABLE_KEY_PREFIXES: Final = ("on_", "handle_")

# Canonical privacy / presentation vocabularies (closed for v1).
PRIVACY_SENSITIVITY_VALUES: Final = frozenset(
    {"none", "low", "moderate", "high", "restricted", "secret"}
)
PRESENTATION_CLASSIFICATION_VALUES: Final = frozenset(
    {
        "interactive",
        "static",
        "decorative",
        "landmark",
        "status",
        "alert",
        "structure",
        "media",
    }
)


class ComponentGraphValidationError(UIIRValidationError):
    """Raised when a component graph violates composition contracts."""


class ValueStateKind(str, Enum):
    """Closed value-state vocabulary for form-like components."""

    NONE = "none"
    TEXT = "text"
    NUMBER = "number"
    BOOLEAN = "boolean"
    ENUM = "enum"
    MULTI_ENUM = "multi_enum"
    STRUCTURED = "structured"
    OPAQUE_REF = "opaque_ref"


class SelectionStateKind(str, Enum):
    """Closed selection-state vocabulary."""

    NONE = "none"
    SINGLE = "single"
    MULTIPLE = "multiple"
    RANGE = "range"


class ValidationStateKind(str, Enum):
    """Closed validation-state vocabulary."""

    NONE = "none"
    VALID = "valid"
    INVALID = "invalid"
    PENDING = "pending"
    UNKNOWN = "unknown"


class VisibilityState(str, Enum):
    """Closed visibility vocabulary (semantic, not CSS)."""

    VISIBLE = "visible"
    HIDDEN = "hidden"
    COLLAPSED = "collapsed"
    DEFERRED = "deferred"


class EnabledState(str, Enum):
    """Closed enabled/disabled vocabulary."""

    ENABLED = "enabled"
    DISABLED = "disabled"
    READ_ONLY = "read_only"


class ActionAffordanceKind(str, Enum):
    """Semantic action affordance families on a component."""

    INVOKE = "invoke"
    SUBMIT = "submit"
    CANCEL = "cancel"
    NAVIGATE = "navigate"
    TOGGLE = "toggle"
    SELECT = "select"
    EDIT = "edit"
    DISMISS = "dismiss"
    CONFIRM = "confirm"
    RETRY = "retry"
    UNDO = "undo"
    CUSTOM = "custom"


def _validate_identifier(name: str, value: str) -> None:
    if not isinstance(value, str) or not _IDENTIFIER_RE.fullmatch(value):
        raise ComponentGraphValidationError(f"{name} is not a stable identifier")


def _validate_string(name: str, value: Any) -> None:
    if not isinstance(value, str):
        raise ComponentGraphValidationError(f"{name} must be a string")


def _validate_non_empty_string(name: str, value: Any) -> None:
    _validate_string(name, value)
    if not value.strip():
        raise ComponentGraphValidationError(f"{name} must not be empty")


def _require_tuple(name: str, value: Any) -> None:
    if not isinstance(value, tuple):
        raise ComponentGraphValidationError(
            f"{name} must be an immutable tuple"
        )


def _validate_identifier_items(name: str, values: Iterable[Any]) -> None:
    for index, value in enumerate(values):
        _validate_identifier(f"{name}[{index}]", value)


def _require_unique(values: Iterable[str], label: str) -> None:
    seen: set[str] = set()
    for value in values:
        if value in seen:
            raise ComponentGraphValidationError(f"Duplicate {label} id: {value}")
        seen.add(value)


def _require_known_refs(
    values: Iterable[str], known: set[str], label: str
) -> None:
    missing = sorted({value for value in values if value not in known})
    if missing:
        raise ComponentGraphValidationError(
            f"{label} references unknown ids: {', '.join(missing)}"
        )


def _is_forbidden_executable_key(key: str) -> bool:
    lowered = key.lower()
    if lowered in _FORBIDDEN_EXECUTABLE_KEYS:
        return True
    return any(lowered.startswith(prefix) for prefix in _FORBIDDEN_EXECUTABLE_KEY_PREFIXES)


def _reject_executable_payload(value: Any, label: str, *, _path: str = "") -> None:
    if callable(value) or isinstance(value, type):
        raise ComponentGraphValidationError(
            f"{label}{_path} contains an executable callback"
        )
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ComponentGraphValidationError(
                    f"{label}{_path} map keys must be strings"
                )
            if _is_forbidden_executable_key(key):
                raise ComponentGraphValidationError(
                    f"{label}{_path}/{key} is an executable callback field"
                )
            _reject_executable_payload(item, label, _path=f"{_path}/{key}")
        return
    if isinstance(value, (str, bytes, bytearray)) or value is None:
        return
    if isinstance(value, (set, frozenset)):
        for index, item in enumerate(sorted(value, key=repr)):
            _reject_executable_payload(item, label, _path=f"{_path}{{{index}}}")
        return
    if isinstance(value, Sequence):
        for index, item in enumerate(value):
            _reject_executable_payload(item, label, _path=f"{_path}[{index}]")


def _freeze_mapping(value: Mapping[str, Any] | None, label: str) -> Mapping[str, Any]:
    if value is None:
        return MappingProxyType({})
    if not isinstance(value, Mapping):
        raise ComponentGraphValidationError(f"{label} must be a mapping")
    frozen: dict[str, Any] = {}
    for key, item in value.items():
        if not isinstance(key, str):
            raise ComponentGraphValidationError(f"{label} map keys must be strings")
        if _is_forbidden_executable_key(key):
            raise ComponentGraphValidationError(
                f"{label}/{key} is an executable callback field"
            )
        if callable(item) or isinstance(item, type):
            raise ComponentGraphValidationError(
                f"{label}/{key} contains an executable callback"
            )
        if isinstance(item, Mapping):
            frozen[key] = _freeze_mapping(item, f"{label}/{key}")
        elif isinstance(item, (list, tuple)):
            frozen[key] = tuple(item)
        elif isinstance(item, (str, int, float, bool)) or item is None:
            frozen[key] = item
        else:
            raise ComponentGraphValidationError(
                f"{label}/{key} contains a non-JSON declaration value"
            )
    return MappingProxyType(frozen)


def _validate_role(component_id: str, role: str) -> None:
    _validate_non_empty_string(f"SemanticComponent {component_id!r}.role", role)
    if role in _FORBIDDEN_ROLE_TOKENS or role.startswith(
        ("React.", "HTML", "android.", "SwiftUI.", "Vue.", "Angular.")
    ):
        raise ComponentGraphValidationError(
            f"SemanticComponent {component_id!r}.role must not be a framework "
            f"widget class; got {role!r}"
        )
    if not _ROLE_RE.fullmatch(role) and not _IDENTIFIER_RE.fullmatch(role):
        raise ComponentGraphValidationError(
            f"SemanticComponent {component_id!r}.role is not a stable role token"
        )


@dataclass(frozen=True, slots=True)
class ComponentSlot:
    """Named composition slot on a container component."""

    slot_name: str
    required: bool = False
    accepts_roles: tuple[str, ...] = ()
    max_items: int = 0  # 0 means unbounded

    def validate(self) -> None:
        _validate_non_empty_string("ComponentSlot.slot_name", self.slot_name)
        if not isinstance(self.required, bool):
            raise ComponentGraphValidationError(
                "ComponentSlot.required must be a boolean"
            )
        _require_tuple("ComponentSlot.accepts_roles", self.accepts_roles)
        for index, role in enumerate(self.accepts_roles):
            _validate_non_empty_string(
                f"ComponentSlot.accepts_roles[{index}]", role
            )
        if not isinstance(self.max_items, int) or self.max_items < 0:
            raise ComponentGraphValidationError(
                "ComponentSlot.max_items must be a non-negative integer"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "accepts_roles": list(self.accepts_roles),
            "max_items": self.max_items,
            "required": self.required,
            "slot_name": self.slot_name,
        }


@dataclass(frozen=True, slots=True)
class ActionAffordance:
    """Declared action surface on a component (no executable handlers)."""

    action_id: str
    kind: ActionAffordanceKind
    required: bool = False
    program_binding_id: str = ""
    label_ref: str = ""
    adaptation_policy: str = "preserve"

    def validate(self) -> None:
        _validate_identifier("ActionAffordance.action_id", self.action_id)
        if not isinstance(self.kind, ActionAffordanceKind):
            raise ComponentGraphValidationError(
                "ActionAffordance.kind must be an ActionAffordanceKind"
            )
        if not isinstance(self.required, bool):
            raise ComponentGraphValidationError(
                "ActionAffordance.required must be a boolean"
            )
        _validate_string(
            "ActionAffordance.program_binding_id", self.program_binding_id
        )
        if self.program_binding_id:
            _validate_identifier(
                "ActionAffordance.program_binding_id", self.program_binding_id
            )
        _validate_string("ActionAffordance.label_ref", self.label_ref)
        _validate_non_empty_string(
            "ActionAffordance.adaptation_policy", self.adaptation_policy
        )
        if self.required and self.adaptation_policy not in (
            "preserve",
            "fallback",
        ):
            raise ComponentGraphValidationError(
                f"ActionAffordance {self.action_id!r} is required and must use "
                f"adaptation_policy 'preserve' or 'fallback'; got "
                f"{self.adaptation_policy!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "action_id": self.action_id,
            "adaptation_policy": self.adaptation_policy,
            "kind": self.kind.value,
            "label_ref": self.label_ref,
            "program_binding_id": self.program_binding_id,
            "required": self.required,
        }


@dataclass(frozen=True, slots=True)
class ComponentValueSemantics:
    """Value / selection / validation / enabled / visible state bundle."""

    value_kind: ValueStateKind = ValueStateKind.NONE
    selection_kind: SelectionStateKind = SelectionStateKind.NONE
    validation_kind: ValidationStateKind = ValidationStateKind.NONE
    enabled: EnabledState = EnabledState.ENABLED
    visibility: VisibilityState = VisibilityState.VISIBLE
    value_binding_id: str = ""
    validation_message_ref: str = ""

    def validate(self) -> None:
        for name, enum_type, value in (
            ("value_kind", ValueStateKind, self.value_kind),
            ("selection_kind", SelectionStateKind, self.selection_kind),
            ("validation_kind", ValidationStateKind, self.validation_kind),
            ("enabled", EnabledState, self.enabled),
            ("visibility", VisibilityState, self.visibility),
        ):
            if not isinstance(value, enum_type):
                raise ComponentGraphValidationError(
                    f"ComponentValueSemantics.{name} must be a {enum_type.__name__}"
                )
        _validate_string(
            "ComponentValueSemantics.value_binding_id", self.value_binding_id
        )
        if self.value_binding_id:
            _validate_identifier(
                "ComponentValueSemantics.value_binding_id", self.value_binding_id
            )
        _validate_string(
            "ComponentValueSemantics.validation_message_ref",
            self.validation_message_ref,
        )

    def to_dict(self) -> dict[str, str]:
        return {
            "enabled": self.enabled.value,
            "selection_kind": self.selection_kind.value,
            "validation_kind": self.validation_kind.value,
            "validation_message_ref": self.validation_message_ref,
            "value_binding_id": self.value_binding_id,
            "value_kind": self.value_kind.value,
            "visibility": self.visibility.value,
        }


@dataclass(frozen=True, slots=True)
class SemanticComponent:
    """Full semantic component node for the composition graph."""

    component_id: str
    role: str
    purpose: str = ""
    accessible_name_ref: str = ""
    accessible_description_ref: str = ""
    parent_id: str = ""
    child_ids: tuple[str, ...] = ()
    slots: tuple[ComponentSlot, ...] = ()
    value_semantics: ComponentValueSemantics = ComponentValueSemantics()
    action_affordances: tuple[ActionAffordance, ...] = ()
    modality_binding_ids: tuple[str, ...] = ()
    data_binding_ids: tuple[str, ...] = ()
    program_binding_ids: tuple[str, ...] = ()
    feedback_ids: tuple[str, ...] = ()
    privacy_sensitivity: str = "none"
    presentation_classification: str = "interactive"
    target_hints: Mapping[str, Any] = MappingProxyType({})
    source_ref_ids: tuple[str, ...] = ()

    def validate(self) -> None:
        _validate_identifier("SemanticComponent.component_id", self.component_id)
        _validate_role(self.component_id, self.role)
        for name in (
            "purpose",
            "accessible_name_ref",
            "accessible_description_ref",
            "parent_id",
        ):
            _validate_string(f"SemanticComponent.{name}", getattr(self, name))
        if self.parent_id:
            _validate_identifier("SemanticComponent.parent_id", self.parent_id)
            if self.parent_id == self.component_id:
                raise ComponentGraphValidationError(
                    f"SemanticComponent {self.component_id!r} cannot be its own parent"
                )
        _require_tuple("SemanticComponent.child_ids", self.child_ids)
        _validate_identifier_items("SemanticComponent.child_ids", self.child_ids)
        if self.component_id in self.child_ids:
            raise ComponentGraphValidationError(
                f"SemanticComponent {self.component_id!r} cannot list itself as a child"
            )
        _require_tuple("SemanticComponent.slots", self.slots)
        slot_names: list[str] = []
        for slot in self.slots:
            if not isinstance(slot, ComponentSlot):
                raise ComponentGraphValidationError(
                    "SemanticComponent.slots members must be ComponentSlot"
                )
            slot.validate()
            slot_names.append(slot.slot_name)
        _require_unique(slot_names, "slot name")
        if not isinstance(self.value_semantics, ComponentValueSemantics):
            raise ComponentGraphValidationError(
                "SemanticComponent.value_semantics must be ComponentValueSemantics"
            )
        self.value_semantics.validate()
        _require_tuple(
            "SemanticComponent.action_affordances", self.action_affordances
        )
        action_ids: list[str] = []
        for action in self.action_affordances:
            if not isinstance(action, ActionAffordance):
                raise ComponentGraphValidationError(
                    "SemanticComponent.action_affordances members must be "
                    "ActionAffordance"
                )
            action.validate()
            action_ids.append(action.action_id)
        _require_unique(action_ids, "action affordance")
        for field_name in (
            "modality_binding_ids",
            "data_binding_ids",
            "program_binding_ids",
            "feedback_ids",
            "source_ref_ids",
        ):
            values = getattr(self, field_name)
            _require_tuple(f"SemanticComponent.{field_name}", values)
            _validate_identifier_items(f"SemanticComponent.{field_name}", values)
            _require_unique(values, f"SemanticComponent.{field_name} member")
        _validate_non_empty_string(
            "SemanticComponent.privacy_sensitivity", self.privacy_sensitivity
        )
        if self.privacy_sensitivity not in PRIVACY_SENSITIVITY_VALUES:
            raise ComponentGraphValidationError(
                f"SemanticComponent {self.component_id!r}.privacy_sensitivity "
                f"is not a closed vocabulary value: {self.privacy_sensitivity!r}"
            )
        _validate_non_empty_string(
            "SemanticComponent.presentation_classification",
            self.presentation_classification,
        )
        if self.presentation_classification not in PRESENTATION_CLASSIFICATION_VALUES:
            raise ComponentGraphValidationError(
                f"SemanticComponent {self.component_id!r}."
                f"presentation_classification is not a closed vocabulary value: "
                f"{self.presentation_classification!r}"
            )
        if not isinstance(self.target_hints, Mapping):
            raise ComponentGraphValidationError(
                "SemanticComponent.target_hints must be a mapping"
            )
        # Target hints are adapter metadata only; they must never carry
        # semantic overrides or executable payloads.
        for forbidden_key in (
            "role",
            "required",
            "program_binding_ids",
            "action_affordances",
            "privacy_sensitivity",
            "override_semantics",
            "css",
            "style",
            "className",
            "class_name",
        ):
            if forbidden_key in self.target_hints:
                raise ComponentGraphValidationError(
                    f"SemanticComponent {self.component_id!r}.target_hints must "
                    f"not override semantic requirements via {forbidden_key!r}"
                )
        _reject_executable_payload(
            self.to_dict(), f"SemanticComponent {self.component_id}"
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "accessible_description_ref": self.accessible_description_ref,
            "accessible_name_ref": self.accessible_name_ref,
            "action_affordances": [
                action.to_dict() for action in self.action_affordances
            ],
            "child_ids": list(self.child_ids),
            "component_id": self.component_id,
            "data_binding_ids": sorted(set(self.data_binding_ids)),
            "feedback_ids": sorted(set(self.feedback_ids)),
            "modality_binding_ids": sorted(set(self.modality_binding_ids)),
            "parent_id": self.parent_id,
            "presentation_classification": self.presentation_classification,
            "privacy_sensitivity": self.privacy_sensitivity,
            "program_binding_ids": sorted(set(self.program_binding_ids)),
            "purpose": self.purpose,
            "role": self.role,
            "slots": [slot.to_dict() for slot in self.slots],
            "source_ref_ids": sorted(set(self.source_ref_ids)),
            "target_hints": dict(self.target_hints),
            "value_semantics": self.value_semantics.to_dict(),
        }

    @classmethod
    def from_envelope(cls, component: UIComponent) -> SemanticComponent:
        """Lift an envelope ``UIComponent`` into a semantic graph node."""

        return cls(
            component_id=component.component_id,
            role=component.role,
            purpose=component.purpose,
            accessible_name_ref=component.accessible_name_ref,
            accessible_description_ref=component.accessible_description_ref,
            parent_id=component.parent_id,
            child_ids=component.child_ids,
            modality_binding_ids=component.modality_binding_ids,
            data_binding_ids=component.data_binding_ids,
            program_binding_ids=component.program_binding_ids,
            feedback_ids=component.feedback_ids,
            privacy_sensitivity=component.privacy_sensitivity,
            presentation_classification=component.presentation_classification,
            source_ref_ids=component.source_ref_ids,
        )


@dataclass(frozen=True, slots=True)
class CompositionRelationship:
    """Typed edge in the semantic composition graph."""

    edge_id: str
    kind: CompositionEdgeKind
    source_component_id: str
    target_component_id: str
    slot_name: str = ""
    source_ref_ids: tuple[str, ...] = ()

    def validate(self) -> None:
        _validate_identifier("CompositionRelationship.edge_id", self.edge_id)
        if not isinstance(self.kind, CompositionEdgeKind):
            raise ComponentGraphValidationError(
                "CompositionRelationship.kind must be a CompositionEdgeKind"
            )
        _validate_identifier(
            "CompositionRelationship.source_component_id",
            self.source_component_id,
        )
        _validate_identifier(
            "CompositionRelationship.target_component_id",
            self.target_component_id,
        )
        if self.source_component_id == self.target_component_id:
            raise ComponentGraphValidationError(
                f"CompositionRelationship {self.edge_id!r} is a self-loop, "
                f"which is forbidden"
            )
        _validate_string("CompositionRelationship.slot_name", self.slot_name)
        if self.kind is CompositionEdgeKind.SLOT and not self.slot_name.strip():
            raise ComponentGraphValidationError(
                f"CompositionRelationship {self.edge_id!r} of kind 'slot' "
                f"requires slot_name"
            )
        _require_tuple(
            "CompositionRelationship.source_ref_ids", self.source_ref_ids
        )
        _validate_identifier_items(
            "CompositionRelationship.source_ref_ids", self.source_ref_ids
        )
        _require_unique(
            self.source_ref_ids, "CompositionRelationship.source_ref_ids member"
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "edge_id": self.edge_id,
            "kind": self.kind.value,
            "slot_name": self.slot_name,
            "source_component_id": self.source_component_id,
            "source_ref_ids": sorted(set(self.source_ref_ids)),
            "target_component_id": self.target_component_id,
        }

    @classmethod
    def from_envelope(cls, edge: UICompositionEdge) -> CompositionRelationship:
        return cls(
            edge_id=edge.edge_id,
            kind=edge.kind,
            source_component_id=edge.source_component_id,
            target_component_id=edge.target_component_id,
            slot_name=edge.slot_name,
            source_ref_ids=edge.source_ref_ids,
        )


def _hierarchical_successor(
    kind: CompositionEdgeKind, source: str, target: str
) -> tuple[str, str] | None:
    """Return (parent, child) directed edge for hierarchical kinds."""

    if kind is CompositionEdgeKind.PARENT:
        # source is parent of target
        return source, target
    if kind is CompositionEdgeKind.CHILD:
        # source has child target
        return source, target
    if kind is CompositionEdgeKind.OWNS:
        return source, target
    return None


def detect_hierarchical_cycles(
    components: Sequence[SemanticComponent],
    relationships: Sequence[CompositionRelationship],
) -> list[str]:
    """Return component ids that participate in a hierarchical cycle."""

    adjacency: dict[str, set[str]] = {
        component.component_id: set() for component in components
    }
    for component in components:
        if component.parent_id and component.parent_id in adjacency:
            adjacency[component.parent_id].add(component.component_id)
        for child_id in component.child_ids:
            if child_id in adjacency:
                adjacency[component.component_id].add(child_id)
    for edge in relationships:
        if edge.kind not in _HIERARCHICAL_EDGE_KINDS:
            continue
        directed = _hierarchical_successor(
            edge.kind, edge.source_component_id, edge.target_component_id
        )
        if directed is None:
            continue
        parent, child = directed
        if parent in adjacency and child in adjacency:
            adjacency[parent].add(child)

    WHITE, GRAY, BLACK = 0, 1, 2
    color: dict[str, int] = {node: WHITE for node in adjacency}
    cyclic: set[str] = set()

    def visit(node: str, stack: list[str]) -> None:
        color[node] = GRAY
        stack.append(node)
        for neighbor in sorted(adjacency[node]):
            if color[neighbor] is GRAY:
                # Capture the cycle path members.
                if neighbor in stack:
                    start = stack.index(neighbor)
                    cyclic.update(stack[start:])
                cyclic.add(neighbor)
                cyclic.add(node)
            elif color[neighbor] is WHITE:
                visit(neighbor, stack)
        stack.pop()
        color[node] = BLACK

    for node in sorted(adjacency):
        if color[node] is WHITE:
            visit(node, [])
    return sorted(cyclic)


@dataclass(frozen=True, slots=True)
class UIComponentGraph:
    """Validated, immutable semantic component composition graph."""

    components: tuple[SemanticComponent, ...]
    relationships: tuple[CompositionRelationship, ...] = ()
    entry_component_ids: tuple[str, ...] = ()
    known_feedback_ids: frozenset[str] = frozenset()
    known_data_binding_ids: frozenset[str] = frozenset()
    known_program_binding_ids: frozenset[str] = frozenset()
    known_modality_binding_ids: frozenset[str] = frozenset()
    schema_version: str = UI_COMPONENT_GRAPH_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "known_feedback_ids", frozenset(self.known_feedback_ids)
        )
        object.__setattr__(
            self,
            "known_data_binding_ids",
            frozenset(self.known_data_binding_ids),
        )
        object.__setattr__(
            self,
            "known_program_binding_ids",
            frozenset(self.known_program_binding_ids),
        )
        object.__setattr__(
            self,
            "known_modality_binding_ids",
            frozenset(self.known_modality_binding_ids),
        )

    def validate(self) -> None:
        if self.schema_version != UI_COMPONENT_GRAPH_SCHEMA_VERSION:
            raise ComponentGraphValidationError(
                f"Unsupported component graph schema_version "
                f"{self.schema_version!r}; expected "
                f"{UI_COMPONENT_GRAPH_SCHEMA_VERSION!r}"
            )
        _require_tuple("UIComponentGraph.components", self.components)
        if not self.components:
            raise ComponentGraphValidationError(
                "UIComponentGraph.components must not be empty"
            )
        for component in self.components:
            if not isinstance(component, SemanticComponent):
                raise ComponentGraphValidationError(
                    "UIComponentGraph.components members must be SemanticComponent"
                )
            component.validate()
        component_ids = [item.component_id for item in self.components]
        _require_unique(component_ids, "component")
        id_set = set(component_ids)

        _require_tuple("UIComponentGraph.relationships", self.relationships)
        edge_ids: list[str] = []
        for edge in self.relationships:
            if not isinstance(edge, CompositionRelationship):
                raise ComponentGraphValidationError(
                    "UIComponentGraph.relationships members must be "
                    "CompositionRelationship"
                )
            edge.validate()
            edge_ids.append(edge.edge_id)
            _require_known_refs(
                (edge.source_component_id, edge.target_component_id),
                id_set,
                f"CompositionRelationship {edge.edge_id!r}",
            )
            if edge.kind is CompositionEdgeKind.SLOT:
                source = next(
                    c
                    for c in self.components
                    if c.component_id == edge.source_component_id
                )
                declared = {slot.slot_name for slot in source.slots}
                if declared and edge.slot_name not in declared:
                    raise ComponentGraphValidationError(
                        f"CompositionRelationship {edge.edge_id!r} references "
                        f"undeclared slot {edge.slot_name!r} on "
                        f"{edge.source_component_id!r}"
                    )
        _require_unique(edge_ids, "composition edge")

        for component in self.components:
            if component.parent_id:
                _require_known_refs(
                    (component.parent_id,),
                    id_set,
                    f"SemanticComponent {component.component_id!r}.parent_id",
                )
            _require_known_refs(
                component.child_ids,
                id_set,
                f"SemanticComponent {component.component_id!r}.child_ids",
            )
            if self.known_feedback_ids:
                _require_known_refs(
                    component.feedback_ids,
                    set(self.known_feedback_ids),
                    f"SemanticComponent {component.component_id!r}.feedback_ids",
                )
            if self.known_data_binding_ids:
                _require_known_refs(
                    component.data_binding_ids,
                    set(self.known_data_binding_ids),
                    f"SemanticComponent {component.component_id!r}.data_binding_ids",
                )
            if self.known_program_binding_ids:
                _require_known_refs(
                    component.program_binding_ids,
                    set(self.known_program_binding_ids),
                    f"SemanticComponent {component.component_id!r}."
                    f"program_binding_ids",
                )
                for action in component.action_affordances:
                    if action.program_binding_id:
                        _require_known_refs(
                            (action.program_binding_id,),
                            set(self.known_program_binding_ids),
                            f"ActionAffordance {action.action_id!r}."
                            f"program_binding_id",
                        )
            if self.known_modality_binding_ids:
                _require_known_refs(
                    component.modality_binding_ids,
                    set(self.known_modality_binding_ids),
                    f"SemanticComponent {component.component_id!r}."
                    f"modality_binding_ids",
                )

        cyclic = detect_hierarchical_cycles(self.components, self.relationships)
        if cyclic:
            raise ComponentGraphValidationError(
                "Hierarchical component relationships contain a cycle involving: "
                + ", ".join(cyclic)
            )

        _require_tuple(
            "UIComponentGraph.entry_component_ids", self.entry_component_ids
        )
        if self.entry_component_ids:
            _validate_identifier_items(
                "UIComponentGraph.entry_component_ids", self.entry_component_ids
            )
            _require_unique(
                self.entry_component_ids, "entry_component_ids member"
            )
            _require_known_refs(
                self.entry_component_ids,
                id_set,
                "UIComponentGraph.entry_component_ids",
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "components": [
                item.to_dict()
                for item in sorted(
                    self.components, key=lambda c: c.component_id
                )
            ],
            "entry_component_ids": sorted(set(self.entry_component_ids)),
            "interface": UI_COMPONENT_GRAPH_INTERFACE,
            "relationships": [
                item.to_dict()
                for item in sorted(self.relationships, key=lambda e: e.edge_id)
            ],
            "schema_version": self.schema_version,
        }

    def required_actions(self) -> tuple[ActionAffordance, ...]:
        """Return required action affordances across the graph."""

        actions: list[ActionAffordance] = []
        for component in self.components:
            for action in component.action_affordances:
                if action.required:
                    actions.append(action)
        return tuple(actions)


def validate_component_graph(graph: UIComponentGraph) -> UIComponentGraph:
    """Validate and return a component graph (fail-closed)."""

    if not isinstance(graph, UIComponentGraph):
        raise ComponentGraphValidationError(
            "validate_component_graph expects a UIComponentGraph"
        )
    graph.validate()
    return graph


__all__ = [
    "ActionAffordance",
    "ActionAffordanceKind",
    "ComponentGraphValidationError",
    "ComponentSlot",
    "ComponentValueSemantics",
    "CompositionRelationship",
    "EnabledState",
    "PRESENTATION_CLASSIFICATION_VALUES",
    "PRIVACY_SENSITIVITY_VALUES",
    "SelectionStateKind",
    "SemanticComponent",
    "UI_COMPONENT_GRAPH_INTERFACE",
    "UI_COMPONENT_GRAPH_SCHEMA_VERSION",
    "UIComponentGraph",
    "ValidationStateKind",
    "ValueStateKind",
    "VisibilityState",
    "detect_hierarchical_cycles",
    "validate_component_graph",
]
