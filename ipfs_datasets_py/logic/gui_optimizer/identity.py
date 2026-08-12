"""Identity and graph closed wire models (VGO-001)."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, ClassVar

from .schema import (
    GUI_APPLICATION_IDENTITY_INTERFACE,
    GUI_APPLICATION_IDENTITY_SCHEMA,
    GUI_SCREEN_IDENTITY_INTERFACE,
    GUI_SCREEN_IDENTITY_SCHEMA,
    UI_ACCESSIBILITY_CONTRACT_INTERFACE,
    UI_ACCESSIBILITY_CONTRACT_SCHEMA,
    UI_ACTION_BINDING_INTERFACE,
    UI_ACTION_BINDING_SCHEMA,
    UI_COMPONENT_IDENTITY_INTERFACE,
    UI_COMPONENT_IDENTITY_SCHEMA,
    UI_COMPONENT_VERSION_INTERFACE,
    UI_COMPONENT_VERSION_SCHEMA,
    UI_DEPENDENCY_EDGE_INTERFACE,
    UI_DEPENDENCY_EDGE_SCHEMA,
    UI_EVENT_DEFINITION_INTERFACE,
    UI_EVENT_DEFINITION_SCHEMA,
    UI_LAYOUT_CONSTRAINT_INTERFACE,
    UI_LAYOUT_CONSTRAINT_SCHEMA,
    UI_STATE_DEFINITION_INTERFACE,
    UI_STATE_DEFINITION_SCHEMA,
    UI_TRANSITION_DEFINITION_INTERFACE,
    UI_TRANSITION_DEFINITION_SCHEMA,
    AccessibilityRequirementKind,
    ExtractionConfidence,
    ExtractionMethod,
    GuiOptimizerDecodeError,
    LayoutConstraintKind,
    UiComponentKind,
    UiDependencyRelation,
    UiEventKind,
    UiStateKind,
    decode_closed_record,
    decode_nested_record,
    field_value,
    optional_digest,
    optional_identifier,
    optional_nested_record,
    optional_repo_path,
    optional_text,
    parse_enum,
    parse_enum_sequence,
    require_bool,
    require_digest,
    require_extractor_version,
    require_identifier,
    require_int,
    require_interface,
    require_registered_optimizer_schema_version,
    require_schema_version,
    require_text,
    store_attrs,
    unique_identifiers,
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


class GuiApplicationIdentity(_Base):
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


class GuiScreenIdentity(_Base):
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


class UiComponentIdentity(_Base):
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


class UiComponentVersion(_Base):
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
            localization_digest=optional_digest(localization_digest, "localization_digest"),
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


class UiDependencyEdge(_Base):
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
        from .models import SourceSpan

        store_attrs(
            self,
            source_component_id=require_identifier(source_component_id, "source_component_id"),
            target_component_id=require_identifier(target_component_id, "target_component_id"),
            relation=parse_enum(relation, UiDependencyRelation, "relation"),
            extraction_method=parse_enum(extraction_method, ExtractionMethod, "extraction_method"),
            extractor_version=require_extractor_version(extractor_version),
            confidence=parse_enum(confidence, ExtractionConfidence, "confidence"),
            source_span=optional_nested_record(SourceSpan, source_span, "source_span"),
            notes=optional_text(notes if notes is not None else "", "notes"),
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


class UiStateDefinition(_Base):
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


class UiEventDefinition(_Base):
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


class UiTransitionDefinition(_Base):
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


class UiActionBinding(_Base):
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


class UiLayoutConstraint(_Base):
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
        breakpoint: str,
        lower_bound: int | None,
        upper_bound: int | None,
        interface: str,
        schema_version: str,
    ) -> None:
        lower = None if lower_bound is None else require_int(lower_bound, "lower_bound")
        upper = None if upper_bound is None else require_int(upper_bound, "upper_bound")
        if lower is not None and upper is not None and lower > upper:
            raise GuiOptimizerDecodeError("lower_bound must not exceed upper_bound")
        store_attrs(
            self,
            constraint_id=require_identifier(constraint_id, "constraint_id"),
            kind=parse_enum(kind, LayoutConstraintKind, "kind"),
            expression=require_text(expression, "expression"),
            component_id=optional_identifier(component_id, "component_id"),
            breakpoint=optional_text(breakpoint, "breakpoint"),
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
                breakpoint=field_value(p, "breakpoint", ""),
                lower_bound=field_value(p, "lower_bound", None),
                upper_bound=field_value(p, "upper_bound", None),
                interface=field_value(p, "interface", ""),
                schema_version=field_value(p, "schema_version", ""),
            ),
        )


class UiAccessibilityContract(_Base):
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


__all__ = [
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
]
