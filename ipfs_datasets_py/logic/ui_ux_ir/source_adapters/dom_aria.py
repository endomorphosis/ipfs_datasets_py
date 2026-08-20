"""Bounded DOM/ARIA → UI/UX IR source adapter (DOMARIAUIIRAdapter@1).

Imports a reviewed semantic DOM/ARIA subset into UI/UX IR fragments with
source maps. Never executes markup or scripts. CSS, framework class names,
and unsupported source details are retained only as source metadata or
explicit loss receipts.

Supported semantic subset (v1):
- roles: button, link, textbox, checkbox, radio, switch, combobox, listbox,
  option, form, dialog, alertdialog, alert, status, log, progressbar,
  slider, spinbutton, tab, tablist, tabpanel, navigation, main, banner,
  contentinfo, complementary, region, group, list, listitem, heading,
  img, separator, presentation, none, document, application, search,
  table, row, cell, columnheader, rowheader, grid, gridcell, menu,
  menubar, menuitem, toolbar, tooltip, tree, treeitem
- accessible name / description / value
- states: checked, disabled, expanded, selected, pressed, invalid,
  required, readonly, busy, hidden, current, haspopup, multiline,
  multiselectable, orientation, level, valuemin/valuemax/valuenow/valuetext
- relationships: labelledby, describedby, controls, owns, flowto, activedescendant
- actions: click/activate, submit, toggle, select, edit, dismiss, confirm
- form validation messages
- live region feedback (aria-live / atomic / relevant)
- explicit focus / reading order

Non-goals:
- Arbitrary React/CSS/source reconstruction
- Script or event-handler execution
- Pixel-perfect or style-identical rendering claims
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Any, Final, Mapping, Sequence

from ..schema import (
    CompositionEdgeKind,
    ReviewStatus,
    SourceSpan,
    UIAccessibilityBinding,
    UIComponent,
    UICompositionEdge,
    UIFeedbackContract,
    UILocalizationBinding,
    UISourceRef,
    UIIRValidationError,
)

DOMARIA_UIIR_ADAPTER: Final = "DOMARIAUIIRAdapter@1"
DOMARIA_UIIR_ADAPTER_VERSION: Final = "dom-aria-uiir-adapter/v1"
DOMARIA_SOURCE_METADATA_VERSION: Final = "dom-aria-source-metadata/v1"

_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$")
_ROLE_TOKEN_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,63}$")

# Closed supported ARIA / implicit HTML role subset.
SUPPORTED_ARIA_ROLES: Final[frozenset[str]] = frozenset(
    {
        "alert",
        "alertdialog",
        "application",
        "banner",
        "button",
        "cell",
        "checkbox",
        "columnheader",
        "combobox",
        "complementary",
        "contentinfo",
        "dialog",
        "document",
        "form",
        "grid",
        "gridcell",
        "group",
        "heading",
        "img",
        "link",
        "list",
        "listbox",
        "listitem",
        "log",
        "main",
        "menu",
        "menubar",
        "menuitem",
        "navigation",
        "none",
        "option",
        "presentation",
        "progressbar",
        "radio",
        "region",
        "row",
        "rowheader",
        "search",
        "separator",
        "slider",
        "spinbutton",
        "status",
        "switch",
        "tab",
        "table",
        "tablist",
        "tabpanel",
        "textbox",
        "toolbar",
        "tooltip",
        "tree",
        "treeitem",
    }
)

# HTML tag → default ARIA role (supported subset only).
_HTML_IMPLICIT_ROLES: Final[Mapping[str, str]] = MappingProxyType(
    {
        "a": "link",
        "article": "document",
        "aside": "complementary",
        "button": "button",
        "dialog": "dialog",
        "footer": "contentinfo",
        "form": "form",
        "h1": "heading",
        "h2": "heading",
        "h3": "heading",
        "h4": "heading",
        "h5": "heading",
        "h6": "heading",
        "header": "banner",
        "hr": "separator",
        "img": "img",
        "input": "textbox",  # refined by type below
        "li": "listitem",
        "main": "main",
        "menu": "menu",
        "nav": "navigation",
        "ol": "list",
        "option": "option",
        "output": "status",
        "progress": "progressbar",
        "search": "search",
        "select": "listbox",
        "table": "table",
        "tbody": "rowgroup",
        "td": "cell",
        "textarea": "textbox",
        "th": "columnheader",
        "tr": "row",
        "ul": "list",
    }
)

_INPUT_TYPE_ROLES: Final[Mapping[str, str]] = MappingProxyType(
    {
        "button": "button",
        "checkbox": "checkbox",
        "email": "textbox",
        "number": "spinbutton",
        "password": "textbox",
        "radio": "radio",
        "range": "slider",
        "reset": "button",
        "search": "searchbox",
        "submit": "button",
        "tel": "textbox",
        "text": "textbox",
        "url": "textbox",
    }
)

# Roles that map to searchbox are normalized to textbox (searchbox not in v1 set).
_ROLE_ALIASES: Final[Mapping[str, str]] = MappingProxyType(
    {
        "searchbox": "textbox",
        "rowgroup": "group",
    }
)

SUPPORTED_STATE_KEYS: Final[frozenset[str]] = frozenset(
    {
        "busy",
        "checked",
        "current",
        "disabled",
        "expanded",
        "haspopup",
        "hidden",
        "invalid",
        "level",
        "multiline",
        "multiselectable",
        "orientation",
        "pressed",
        "readonly",
        "required",
        "selected",
        "valuemax",
        "valuemin",
        "valuenow",
        "valuetext",
    }
)

SUPPORTED_RELATIONSHIP_KEYS: Final[frozenset[str]] = frozenset(
    {
        "activedescendant",
        "controls",
        "describedby",
        "flowto",
        "labelledby",
        "owns",
    }
)

_RELATIONSHIP_TO_EDGE: Final[Mapping[str, CompositionEdgeKind]] = MappingProxyType(
    {
        "labelledby": CompositionEdgeKind.LABEL,
        "describedby": CompositionEdgeKind.DESCRIBED_BY,
        "owns": CompositionEdgeKind.OWNS,
        "flowto": CompositionEdgeKind.FLOW,
        # controls / activedescendant retained as accessibility relationships only
    }
)

SUPPORTED_ACTION_KINDS: Final[frozenset[str]] = frozenset(
    {
        "activate",
        "click",
        "confirm",
        "dismiss",
        "edit",
        "select",
        "submit",
        "toggle",
    }
)

_FORBIDDEN_TAGS: Final[frozenset[str]] = frozenset(
    {
        "script",
        "style",
        "iframe",
        "object",
        "embed",
        "applet",
        "link",
        "meta",
        "base",
        "template",
        "noscript",
    }
)

_EXECUTABLE_ATTR_PREFIXES: Final = ("on",)
_EXECUTABLE_ATTRS: Final[frozenset[str]] = frozenset(
    {
        "href",
        "src",
        "action",
        "formaction",
        "xlink:href",
        "poster",
        "data",
        "codebase",
    }
)
_EXECUTABLE_URI_SCHEMES: Final = (
    "javascript:",
    "vbscript:",
    "data:text/html",
    "data:application/",
)

_EXECUTABLE_TEXT_MARKERS: Final = (
    "<script",
    "</script",
    "javascript:",
    "vbscript:",
    "onerror=",
    "onload=",
    "onclick=",
    "eval(",
    "Function(",
    "document.write",
    "innerHTML",
    "__proto__",
)

_CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


class DomAriaAdapterError(UIIRValidationError):
    """Raised when a DOM/ARIA snapshot cannot be safely adapted."""


class DomAriaLossCategory(str, Enum):
    """How an unsupported source detail was handled."""

    SOURCE_METADATA = "source_metadata"
    UNSUPPORTED = "unsupported"
    SANITIZED = "sanitized"
    REJECTED = "rejected"


@dataclass(frozen=True, slots=True)
class DomAriaLoss:
    """Explicit loss or retained-metadata receipt for one source detail."""

    loss_id: str
    path: str
    reason: str
    category: DomAriaLossCategory = DomAriaLossCategory.UNSUPPORTED
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "category": self.category.value,
            "detail": self.detail,
            "loss_id": self.loss_id,
            "path": self.path,
            "reason": self.reason,
        }


@dataclass(frozen=True, slots=True)
class DomAriaSourceMetadata:
    """Retained non-semantic source details (CSS/framework/spans)."""

    metadata_id: str
    node_id: str
    tag_name: str = ""
    css_classes: tuple[str, ...] = ()
    css_inline_summary: str = ""
    framework_hints: Mapping[str, str] = MappingProxyType({})
    attributes_retained: Mapping[str, str] = MappingProxyType({})
    source_span: SourceSpan | None = None
    schema_version: str = DOMARIA_SOURCE_METADATA_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.framework_hints, Mapping):
            raise DomAriaAdapterError("framework_hints must be a mapping")
        if not isinstance(self.attributes_retained, Mapping):
            raise DomAriaAdapterError("attributes_retained must be a mapping")
        object.__setattr__(
            self,
            "framework_hints",
            MappingProxyType(dict(self.framework_hints)),
        )
        object.__setattr__(
            self,
            "attributes_retained",
            MappingProxyType(dict(self.attributes_retained)),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "attributes_retained": dict(self.attributes_retained),
            "css_classes": list(self.css_classes),
            "css_inline_summary": self.css_inline_summary,
            "framework_hints": dict(self.framework_hints),
            "metadata_id": self.metadata_id,
            "node_id": self.node_id,
            "schema_version": self.schema_version,
            "source_span": self.source_span.to_dict() if self.source_span else None,
            "tag_name": self.tag_name,
        }


@dataclass(frozen=True, slots=True)
class DomAriaNodeState:
    """Normalized ARIA state bundle for one node."""

    values: Mapping[str, str] = MappingProxyType({})

    def __post_init__(self) -> None:
        if not isinstance(self.values, Mapping):
            raise DomAriaAdapterError("DomAriaNodeState.values must be a mapping")
        object.__setattr__(
            self, "values", MappingProxyType({str(k): str(v) for k, v in self.values.items()})
        )

    def to_dict(self) -> dict[str, str]:
        return dict(self.values)


@dataclass(frozen=True, slots=True)
class DomAriaValidation:
    """Form validation semantics for a field-like node."""

    valid: bool | None = None
    message: str = ""
    required: bool = False
    invalid_state: str = ""  # "", "true", "false", "grammar", "spelling"

    def to_dict(self) -> dict[str, Any]:
        return {
            "invalid_state": self.invalid_state,
            "message": self.message,
            "required": self.required,
            "valid": self.valid,
        }


@dataclass(frozen=True, slots=True)
class DomAriaLiveRegion:
    """Live feedback region configuration."""

    politeness: str = "off"  # off | polite | assertive
    atomic: bool = False
    relevant: str = "additions text"

    def to_dict(self) -> dict[str, Any]:
        return {
            "atomic": self.atomic,
            "politeness": self.politeness,
            "relevant": self.relevant,
        }


@dataclass(frozen=True, slots=True)
class DomAriaNode:
    """One sanitized semantic DOM/ARIA node in the supported subset."""

    node_id: str
    role: str
    name: str = ""
    description: str = ""
    value: str = ""
    states: DomAriaNodeState = DomAriaNodeState()
    relationships: Mapping[str, tuple[str, ...]] = MappingProxyType({})
    actions: tuple[str, ...] = ()
    children: tuple["DomAriaNode", ...] = ()
    focus_order: int | None = None
    validation: DomAriaValidation = DomAriaValidation()
    live: DomAriaLiveRegion = DomAriaLiveRegion()
    tag_name: str = ""
    css_classes: tuple[str, ...] = ()
    css_inline: str = ""
    framework_hints: Mapping[str, str] = MappingProxyType({})
    attributes: Mapping[str, str] = MappingProxyType({})
    text_content: str = ""
    source_span: SourceSpan | None = None

    def __post_init__(self) -> None:
        for field_name in ("relationships", "framework_hints", "attributes"):
            value = getattr(self, field_name)
            if not isinstance(value, Mapping):
                raise DomAriaAdapterError(f"{field_name} must be a mapping")
        frozen_rels: dict[str, tuple[str, ...]] = {}
        for key, refs in self.relationships.items():
            if isinstance(refs, str):
                frozen_rels[str(key)] = (refs,)
            elif isinstance(refs, Sequence):
                frozen_rels[str(key)] = tuple(str(r) for r in refs)
            else:
                raise DomAriaAdapterError(
                    f"relationships[{key!r}] must be a string or sequence"
                )
        object.__setattr__(self, "relationships", MappingProxyType(frozen_rels))
        object.__setattr__(
            self,
            "framework_hints",
            MappingProxyType({str(k): str(v) for k, v in self.framework_hints.items()}),
        )
        object.__setattr__(
            self,
            "attributes",
            MappingProxyType({str(k): str(v) for k, v in self.attributes.items()}),
        )


@dataclass(frozen=True, slots=True)
class DomAriaDocument:
    """Root DOM/ARIA snapshot document for import."""

    document_id: str
    title: str
    root: DomAriaNode
    source_uri: str = "dom-aria://snapshot"
    source_id: str = "dom-aria-snapshot"
    source_revision: str = "1"
    content_sha256: str = ""
    locale: str = "en"
    review_status: ReviewStatus = ReviewStatus.MACHINE_EXTRACTED

    def validate_identity(self) -> None:
        if not isinstance(self.document_id, str) or not self.document_id.strip():
            raise DomAriaAdapterError("document_id must be non-empty")
        if not isinstance(self.title, str) or not self.title.strip():
            raise DomAriaAdapterError("title must be non-empty")


@dataclass(frozen=True, slots=True)
class DomAriaAdapterResult:
    """UI/UX IR fragments projected from a DOM/ARIA snapshot."""

    document_id: str
    components: tuple[UIComponent, ...]
    composition_edges: tuple[UICompositionEdge, ...]
    accessibility: tuple[UIAccessibilityBinding, ...]
    feedback_contracts: tuple[UIFeedbackContract, ...]
    localization: tuple[UILocalizationBinding, ...]
    sources: tuple[UISourceRef, ...]
    entry_components: tuple[str, ...]
    focus_order: tuple[str, ...]
    node_states: Mapping[str, Mapping[str, str]]
    node_values: Mapping[str, str]
    node_validations: Mapping[str, Mapping[str, Any]]
    live_regions: Mapping[str, Mapping[str, Any]]
    actions_by_node: Mapping[str, tuple[str, ...]]
    source_metadata: tuple[DomAriaSourceMetadata, ...]
    losses: tuple[DomAriaLoss, ...]
    adapter: str = DOMARIA_UIIR_ADAPTER
    schema_version: str = DOMARIA_UIIR_ADAPTER_VERSION
    execution_performed: bool = False  # always False

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "node_states",
            MappingProxyType({k: dict(v) for k, v in self.node_states.items()}),
        )
        object.__setattr__(
            self,
            "node_values",
            MappingProxyType(dict(self.node_values)),
        )
        object.__setattr__(
            self,
            "node_validations",
            MappingProxyType({k: dict(v) for k, v in self.node_validations.items()}),
        )
        object.__setattr__(
            self,
            "live_regions",
            MappingProxyType({k: dict(v) for k, v in self.live_regions.items()}),
        )
        object.__setattr__(
            self,
            "actions_by_node",
            MappingProxyType({k: tuple(v) for k, v in self.actions_by_node.items()}),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "accessibility": [item.to_dict() for item in self.accessibility],
            "actions_by_node": {
                key: list(value) for key, value in sorted(self.actions_by_node.items())
            },
            "adapter": self.adapter,
            "components": [item.to_dict() for item in self.components],
            "composition_edges": [item.to_dict() for item in self.composition_edges],
            "document_id": self.document_id,
            "entry_components": list(self.entry_components),
            "execution_performed": self.execution_performed,
            "feedback_contracts": [item.to_dict() for item in self.feedback_contracts],
            "focus_order": list(self.focus_order),
            "live_regions": {
                key: dict(value) for key, value in sorted(self.live_regions.items())
            },
            "localization": [item.to_dict() for item in self.localization],
            "losses": [item.to_dict() for item in self.losses],
            "node_states": {
                key: dict(value) for key, value in sorted(self.node_states.items())
            },
            "node_validations": {
                key: dict(value)
                for key, value in sorted(self.node_validations.items())
            },
            "node_values": dict(sorted(self.node_values.items())),
            "schema_version": self.schema_version,
            "source_metadata": [item.to_dict() for item in self.source_metadata],
            "sources": [item.to_dict() for item in self.sources],
        }


class DOMARIAUIIRAdapter:
    """Side-effect-free DOM/ARIA → UIIR adapter."""

    interface: str = DOMARIA_UIIR_ADAPTER

    def adapt(
        self,
        document: DomAriaDocument | Mapping[str, Any],
    ) -> DomAriaAdapterResult:
        return adapt_dom_aria_to_uiir(document)


def adapt_dom_aria_to_uiir(
    document: DomAriaDocument | Mapping[str, Any],
) -> DomAriaAdapterResult:
    """Adapt a sanitized DOM/ARIA snapshot into UI/UX IR fragments + losses."""

    snapshot = (
        document
        if isinstance(document, DomAriaDocument)
        else _document_from_mapping(document)
    )
    snapshot.validate_identity()

    components: list[UIComponent] = []
    edges: list[UICompositionEdge] = []
    accessibility: list[UIAccessibilityBinding] = []
    feedback: list[UIFeedbackContract] = []
    localization: list[UILocalizationBinding] = []
    source_metadata: list[DomAriaSourceMetadata] = []
    losses: list[DomAriaLoss] = []
    focus_entries: list[tuple[int, str]] = ()
    focus_entries = []
    node_states: dict[str, dict[str, str]] = {}
    node_values: dict[str, str] = {}
    node_validations: dict[str, dict[str, Any]] = {}
    live_regions: dict[str, dict[str, Any]] = {}
    actions_by_node: dict[str, tuple[str, ...]] = {}
    seen_ids: set[str] = set()

    content_digest = snapshot.content_sha256
    if not content_digest:
        content_digest = _digest_snapshot(snapshot)
    source_ref = UISourceRef(
        ref_id=f"source:dom-aria:{_slug(snapshot.document_id)}",
        source_uri=snapshot.source_uri,
        source_id=snapshot.source_id,
        source_revision=snapshot.source_revision,
        content_sha256=content_digest,
        review_status=snapshot.review_status,
    )
    source_ref.validate()

    def walk(node: DomAriaNode, parent_id: str, path: str) -> str | None:
        node_id, role, node_losses, meta, sanitized = _sanitize_node(node, path)
        losses.extend(node_losses)
        if sanitized is None:
            return None
        if node_id in seen_ids:
            raise DomAriaAdapterError(f"Duplicate node_id: {node_id}")
        seen_ids.add(node_id)

        source_metadata.append(meta)

        name = _sanitize_text(sanitized.name) or _sanitize_text(sanitized.text_content)
        description = _sanitize_text(sanitized.description)
        value = _sanitize_text(sanitized.value)

        name_ref = ""
        desc_ref = ""
        if name:
            name_ref = f"loc:name:{node_id}"
            localization.append(
                UILocalizationBinding(
                    localization_id=name_ref,
                    message_id=f"msg:name:{node_id}",
                    default_text=name,
                    source_ref_ids=(source_ref.ref_id,),
                )
            )
        if description:
            desc_ref = f"loc:desc:{node_id}"
            localization.append(
                UILocalizationBinding(
                    localization_id=desc_ref,
                    message_id=f"msg:desc:{node_id}",
                    default_text=description,
                    source_ref_ids=(source_ref.ref_id,),
                )
            )

        child_component_ids: list[str] = []
        for index, child in enumerate(sanitized.children):
            child_id = walk(child, node_id, f"{path}/children[{index}]")
            if child_id:
                child_component_ids.append(child_id)
                edges.append(
                    UICompositionEdge(
                        edge_id=f"edge:child:{node_id}:{child_id}",
                        kind=CompositionEdgeKind.CHILD,
                        source_component_id=node_id,
                        target_component_id=child_id,
                        source_ref_ids=(source_ref.ref_id,),
                    )
                )

        presentation = _presentation_for_role(role)
        privacy = "high" if _is_sensitive(sanitized) else "none"
        component = UIComponent(
            component_id=node_id,
            role=f"aria:{role}",
            purpose=_purpose_for(role, name, sanitized.text_content),
            accessible_name_ref=name_ref,
            accessible_description_ref=desc_ref,
            parent_id=parent_id,
            child_ids=tuple(child_component_ids),
            feedback_ids=(),
            privacy_sensitivity=privacy,
            presentation_classification=presentation,
            source_ref_ids=(source_ref.ref_id,),
        )
        component.validate()

        relationship_ids: list[str] = []
        for rel_key, targets in sanitized.relationships.items():
            if rel_key not in SUPPORTED_RELATIONSHIP_KEYS:
                losses.append(
                    DomAriaLoss(
                        loss_id=f"loss:rel-unsupported:{node_id}:{rel_key}",
                        path=f"{path}/relationships/{rel_key}",
                        reason=f"Relationship {rel_key!r} is outside the supported subset",
                        category=DomAriaLossCategory.UNSUPPORTED,
                        detail=rel_key,
                    )
                )
                continue
            for target in targets:
                target_id = _normalize_id(target, f"{path}/relationships/{rel_key}")
                relationship_ids.append(f"{rel_key}:{target_id}")
                edge_kind = _RELATIONSHIP_TO_EDGE.get(rel_key)
                if edge_kind is not None:
                    edges.append(
                        UICompositionEdge(
                            edge_id=f"edge:{rel_key}:{node_id}:{target_id}",
                            kind=edge_kind,
                            source_component_id=node_id,
                            target_component_id=target_id,
                            source_ref_ids=(source_ref.ref_id,),
                        )
                    )

        a11y = UIAccessibilityBinding(
            accessibility_id=f"a11y:{node_id}",
            component_id=node_id,
            role=f"aria:{role}",
            name_ref=name_ref,
            description_ref=desc_ref,
            relationship_ids=tuple(sorted(set(relationship_ids))),
            live_region=sanitized.live.politeness in {"polite", "assertive"},
            source_ref_ids=(source_ref.ref_id,),
        )
        a11y.validate()
        accessibility.append(a11y)

        feedback_ids: list[str] = []
        if sanitized.live.politeness in {"polite", "assertive"}:
            feedback_id = f"feedback:live:{node_id}"
            channel = f"live:{sanitized.live.politeness}"
            fb = UIFeedbackContract(
                feedback_id=feedback_id,
                channel=channel,
                component_id=node_id,
                source_ref_ids=(source_ref.ref_id,),
            )
            fb.validate()
            feedback.append(fb)
            feedback_ids.append(feedback_id)
            live_regions[node_id] = sanitized.live.to_dict()

        if sanitized.validation.message or sanitized.validation.invalid_state == "true":
            feedback_id = f"feedback:validation:{node_id}"
            fb = UIFeedbackContract(
                feedback_id=feedback_id,
                channel="validation",
                component_id=node_id,
                source_ref_ids=(source_ref.ref_id,),
            )
            fb.validate()
            feedback.append(fb)
            feedback_ids.append(feedback_id)
            if sanitized.validation.message:
                loc_id = f"loc:validation:{node_id}"
                localization.append(
                    UILocalizationBinding(
                        localization_id=loc_id,
                        message_id=f"msg:validation:{node_id}",
                        default_text=_sanitize_text(sanitized.validation.message),
                        source_ref_ids=(source_ref.ref_id,),
                    )
                )

        if feedback_ids:
            component = UIComponent(
                component_id=component.component_id,
                role=component.role,
                purpose=component.purpose,
                accessible_name_ref=component.accessible_name_ref,
                accessible_description_ref=component.accessible_description_ref,
                parent_id=component.parent_id,
                child_ids=component.child_ids,
                feedback_ids=tuple(feedback_ids),
                privacy_sensitivity=component.privacy_sensitivity,
                presentation_classification=component.presentation_classification,
                source_ref_ids=component.source_ref_ids,
            )
            component.validate()

        components.append(component)
        node_states[node_id] = dict(sanitized.states.values)
        if value:
            node_values[node_id] = value
        node_validations[node_id] = sanitized.validation.to_dict()
        if sanitized.actions:
            actions_by_node[node_id] = sanitized.actions
        if sanitized.focus_order is not None:
            focus_entries.append((sanitized.focus_order, node_id))
        return node_id

    root_id = walk(snapshot.root, "", "root")
    if not root_id:
        raise DomAriaAdapterError("Root node was rejected; refuse empty adaptation")

    # Stable focus order: explicit indices first, then document order of remaining.
    focus_entries.sort(key=lambda item: (item[0], item[1]))
    focus_order = [node_id for _, node_id in focus_entries]
    seen_focus = set(focus_order)
    for component in components:
        if component.component_id not in seen_focus and _is_focusable(
            component.role, node_states.get(component.component_id, {})
        ):
            focus_order.append(component.component_id)
            seen_focus.add(component.component_id)

    # Emit FLOW edges for sequential focus order.
    for index in range(len(focus_order) - 1):
        src = focus_order[index]
        dst = focus_order[index + 1]
        edges.append(
            UICompositionEdge(
                edge_id=f"edge:focus-flow:{src}:{dst}",
                kind=CompositionEdgeKind.FLOW,
                source_component_id=src,
                target_component_id=dst,
                slot_name="focus_order",
                source_ref_ids=(source_ref.ref_id,),
            )
        )

    result = DomAriaAdapterResult(
        document_id=snapshot.document_id,
        components=tuple(components),
        composition_edges=tuple(edges),
        accessibility=tuple(accessibility),
        feedback_contracts=tuple(feedback),
        localization=tuple(localization),
        sources=(source_ref,),
        entry_components=(root_id,),
        focus_order=tuple(focus_order),
        node_states=node_states,
        node_values=node_values,
        node_validations=node_validations,
        live_regions=live_regions,
        actions_by_node=actions_by_node,
        source_metadata=tuple(source_metadata),
        losses=tuple(losses),
        execution_performed=False,
    )
    return result


def parse_dom_aria_node(payload: Mapping[str, Any], *, path: str = "node") -> DomAriaNode:
    """Parse one node mapping into a :class:`DomAriaNode` (no execution)."""

    if not isinstance(payload, Mapping):
        raise DomAriaAdapterError(f"{path} must be a mapping")
    node_id = str(payload.get("node_id") or payload.get("id") or "").strip()
    if not node_id:
        raise DomAriaAdapterError(f"{path}.node_id must not be empty")

    children_raw = payload.get("children") or ()
    if not isinstance(children_raw, Sequence) or isinstance(children_raw, (str, bytes)):
        raise DomAriaAdapterError(f"{path}.children must be an array")
    children = tuple(
        parse_dom_aria_node(child, path=f"{path}/children[{index}]")
        for index, child in enumerate(children_raw)
        if isinstance(child, Mapping)
    )

    states_raw = payload.get("states") or payload.get("aria_states") or {}
    if not isinstance(states_raw, Mapping):
        raise DomAriaAdapterError(f"{path}.states must be a mapping")
    states = DomAriaNodeState(
        values={str(k): str(v) for k, v in states_raw.items()}
    )

    relationships_raw = (
        payload.get("relationships") or payload.get("aria_relationships") or {}
    )
    if not isinstance(relationships_raw, Mapping):
        raise DomAriaAdapterError(f"{path}.relationships must be a mapping")

    validation_raw = payload.get("validation") or {}
    if validation_raw and not isinstance(validation_raw, Mapping):
        raise DomAriaAdapterError(f"{path}.validation must be a mapping")
    validation = DomAriaValidation(
        valid=_optional_bool(validation_raw.get("valid")) if validation_raw else None,
        message=str(validation_raw.get("message") or "") if validation_raw else "",
        required=bool(validation_raw.get("required")) if validation_raw else False,
        invalid_state=str(validation_raw.get("invalid_state") or "")
        if validation_raw
        else str(states.values.get("invalid") or ""),
    )

    live_raw = payload.get("live") or payload.get("aria_live") or {}
    if live_raw and not isinstance(live_raw, Mapping):
        if isinstance(live_raw, str):
            live_raw = {"politeness": live_raw}
        else:
            raise DomAriaAdapterError(f"{path}.live must be a mapping or string")
    live = DomAriaLiveRegion(
        politeness=str(live_raw.get("politeness") or live_raw.get("aria-live") or "off"),
        atomic=bool(live_raw.get("atomic", False)),
        relevant=str(live_raw.get("relevant") or "additions text"),
    )

    actions_raw = payload.get("actions") or ()
    if isinstance(actions_raw, str):
        actions = (actions_raw,)
    elif isinstance(actions_raw, Sequence):
        actions = tuple(str(a) for a in actions_raw)
    else:
        raise DomAriaAdapterError(f"{path}.actions must be a string or array")

    focus_order = payload.get("focus_order")
    if focus_order is not None and (
        isinstance(focus_order, bool) or not isinstance(focus_order, int)
    ):
        raise DomAriaAdapterError(f"{path}.focus_order must be an integer or null")

    span = None
    span_raw = payload.get("source_span") or payload.get("span")
    if isinstance(span_raw, Mapping):
        span = SourceSpan(
            start_char=int(span_raw.get("start_char", 0)),
            end_char=int(span_raw.get("end_char", 0)),
        )
        span.validate()

    framework_raw = payload.get("framework_hints") or payload.get("framework") or {}
    if not isinstance(framework_raw, Mapping):
        framework_raw = {"hint": str(framework_raw)}

    attributes_raw = payload.get("attributes") or {}
    if not isinstance(attributes_raw, Mapping):
        raise DomAriaAdapterError(f"{path}.attributes must be a mapping")

    css_classes_raw = payload.get("css_classes") or payload.get("classList") or ()
    if isinstance(css_classes_raw, str):
        css_classes = tuple(c for c in css_classes_raw.split() if c)
    elif isinstance(css_classes_raw, Sequence):
        css_classes = tuple(str(c) for c in css_classes_raw)
    else:
        raise DomAriaAdapterError(f"{path}.css_classes must be a string or array")

    role = str(payload.get("role") or "").strip()
    tag_name = str(payload.get("tag_name") or payload.get("tag") or "").strip().lower()
    input_type = str(
        payload.get("input_type")
        or attributes_raw.get("type")
        or ""
    ).strip().lower()
    if not role:
        role = _infer_role(tag_name, input_type)

    return DomAriaNode(
        node_id=node_id,
        role=role,
        name=str(payload.get("name") or payload.get("accessible_name") or ""),
        description=str(
            payload.get("description") or payload.get("accessible_description") or ""
        ),
        value=str(payload.get("value") or ""),
        states=states,
        relationships={str(k): v for k, v in relationships_raw.items()},
        actions=actions,
        children=children,
        focus_order=focus_order,
        validation=validation,
        live=live,
        tag_name=tag_name,
        css_classes=css_classes,
        css_inline=str(payload.get("css_inline") or payload.get("style") or ""),
        framework_hints={str(k): str(v) for k, v in framework_raw.items()},
        attributes={str(k): str(v) for k, v in attributes_raw.items()},
        text_content=str(payload.get("text_content") or payload.get("text") or ""),
        source_span=span,
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _document_from_mapping(payload: Mapping[str, Any]) -> DomAriaDocument:
    if not isinstance(payload, Mapping):
        raise DomAriaAdapterError("DOM/ARIA document must be a mapping")
    root_raw = payload.get("root") or payload.get("tree")
    if not isinstance(root_raw, Mapping):
        raise DomAriaAdapterError("document.root must be a mapping")
    root = parse_dom_aria_node(root_raw, path="root")
    review_raw = str(payload.get("review_status") or ReviewStatus.MACHINE_EXTRACTED.value)
    try:
        review = ReviewStatus(review_raw)
    except ValueError as exc:
        raise DomAriaAdapterError(f"Invalid review_status: {review_raw!r}") from exc
    return DomAriaDocument(
        document_id=str(payload.get("document_id") or "").strip(),
        title=str(payload.get("title") or "").strip(),
        root=root,
        source_uri=str(payload.get("source_uri") or "dom-aria://snapshot"),
        source_id=str(payload.get("source_id") or "dom-aria-snapshot"),
        source_revision=str(payload.get("source_revision") or "1"),
        content_sha256=str(payload.get("content_sha256") or ""),
        locale=str(payload.get("locale") or "en"),
        review_status=review,
    )


def _sanitize_node(
    node: DomAriaNode,
    path: str,
) -> tuple[str, str, list[DomAriaLoss], DomAriaSourceMetadata, DomAriaNode | None]:
    losses: list[DomAriaLoss] = []
    node_id = _normalize_id(node.node_id, f"{path}.node_id")

    tag = (node.tag_name or "").strip().lower()
    if tag in _FORBIDDEN_TAGS:
        losses.append(
            DomAriaLoss(
                loss_id=f"loss:rejected-tag:{node_id}",
                path=path,
                reason=f"Tag {tag!r} is forbidden and never imported or executed",
                category=DomAriaLossCategory.REJECTED,
                detail=tag,
            )
        )
        meta = DomAriaSourceMetadata(
            metadata_id=f"meta:{node_id}",
            node_id=node_id,
            tag_name=tag,
            css_classes=node.css_classes,
            css_inline_summary=_summarize_css(node.css_inline),
            framework_hints=node.framework_hints,
            source_span=node.source_span,
        )
        return node_id, "", losses, meta, None

    # Reject executable attributes / URI schemes without executing them.
    for attr, value in node.attributes.items():
        attr_l = attr.lower()
        if attr_l.startswith(_EXECUTABLE_ATTR_PREFIXES) and attr_l not in {
            "orientation",
            "owns",
        }:
            if attr_l.startswith("on") and len(attr_l) > 2:
                losses.append(
                    DomAriaLoss(
                        loss_id=f"loss:sanitized-attr:{node_id}:{attr_l}",
                        path=f"{path}/attributes/{attr}",
                        reason="Event-handler attributes are stripped and never executed",
                        category=DomAriaLossCategory.SANITIZED,
                        detail=attr,
                    )
                )
                continue
        value_l = value.strip().lower()
        if any(value_l.startswith(scheme) for scheme in _EXECUTABLE_URI_SCHEMES):
            # Never echo the raw executable URI into receipts/tests: only the
            # attribute name and a scheme class label (no javascript: payload).
            scheme_label = next(
                (
                    scheme.rstrip(":")
                    for scheme in _EXECUTABLE_URI_SCHEMES
                    if value_l.startswith(scheme)
                ),
                "executable-uri",
            )
            losses.append(
                DomAriaLoss(
                    loss_id=f"loss:sanitized-uri:{node_id}:{attr_l}",
                    path=f"{path}/attributes/{attr}",
                    reason="Executable URI scheme stripped; markup is never executed",
                    category=DomAriaLossCategory.SANITIZED,
                    detail=f"{attr_l}:{scheme_label}",
                )
            )

    for text_field, text_value in (
        ("name", node.name),
        ("description", node.description),
        ("value", node.value),
        ("text_content", node.text_content),
    ):
        if any(marker in text_value.lower() for marker in _EXECUTABLE_TEXT_MARKERS):
            losses.append(
                DomAriaLoss(
                    loss_id=f"loss:sanitized-text:{node_id}:{text_field}",
                    path=f"{path}/{text_field}",
                    reason="Executable markup markers stripped from text fields",
                    category=DomAriaLossCategory.SANITIZED,
                    detail=text_field,
                )
            )

    role = _normalize_role(node.role, tag, node.attributes.get("type", ""), path, losses)
    if role is None:
        meta = DomAriaSourceMetadata(
            metadata_id=f"meta:{node_id}",
            node_id=node_id,
            tag_name=tag,
            css_classes=node.css_classes,
            css_inline_summary=_summarize_css(node.css_inline),
            framework_hints=node.framework_hints,
            attributes_retained=_safe_attributes(node.attributes),
            source_span=node.source_span,
        )
        return node_id, "", losses, meta, None

    # CSS / framework → source metadata (never semantic roles).
    if node.css_classes or node.css_inline:
        losses.append(
            DomAriaLoss(
                loss_id=f"loss:css-metadata:{node_id}",
                path=f"{path}/css",
                reason="CSS class/style retained as source metadata only; not reconstructed",
                category=DomAriaLossCategory.SOURCE_METADATA,
                detail=_summarize_css(
                    " ".join(node.css_classes) + " " + node.css_inline
                ),
            )
        )
    if node.framework_hints:
        losses.append(
            DomAriaLoss(
                loss_id=f"loss:framework-metadata:{node_id}",
                path=f"{path}/framework_hints",
                reason="Framework hints retained as source metadata only",
                category=DomAriaLossCategory.SOURCE_METADATA,
                detail=",".join(f"{k}={v}" for k, v in sorted(node.framework_hints.items())),
            )
        )

    state_values: dict[str, str] = {}
    for key, value in node.states.values.items():
        key_l = key.lower().removeprefix("aria-")
        if key_l not in SUPPORTED_STATE_KEYS:
            losses.append(
                DomAriaLoss(
                    loss_id=f"loss:state-unsupported:{node_id}:{key_l}",
                    path=f"{path}/states/{key}",
                    reason=f"State {key_l!r} is outside the supported subset",
                    category=DomAriaLossCategory.UNSUPPORTED,
                    detail=key_l,
                )
            )
            continue
        state_values[key_l] = _sanitize_text(str(value))

    actions: list[str] = []
    for action in node.actions:
        action_l = action.strip().lower()
        if action_l == "click":
            action_l = "activate"
        if action_l not in SUPPORTED_ACTION_KINDS:
            losses.append(
                DomAriaLoss(
                    loss_id=f"loss:action-unsupported:{node_id}:{action_l}",
                    path=f"{path}/actions",
                    reason=f"Action {action!r} is outside the supported subset",
                    category=DomAriaLossCategory.UNSUPPORTED,
                    detail=action,
                )
            )
            continue
        actions.append(action_l)
    # Infer default actions for interactive roles when none declared.
    if not actions and role in {"button", "link", "menuitem", "tab"}:
        actions.append("activate")
    if not actions and role in {"checkbox", "switch", "radio"}:
        actions.append("toggle")
    if not actions and role == "textbox":
        actions.append("edit")

    live_politeness = (node.live.politeness or "off").strip().lower()
    if live_politeness not in {"off", "polite", "assertive"}:
        losses.append(
            DomAriaLoss(
                loss_id=f"loss:live-unsupported:{node_id}",
                path=f"{path}/live",
                reason=f"aria-live value {node.live.politeness!r} not in off|polite|assertive",
                category=DomAriaLossCategory.UNSUPPORTED,
                detail=node.live.politeness,
            )
        )
        live_politeness = "off"
    # Role-implied live regions.
    if role in {"alert", "status", "log"} and live_politeness == "off":
        live_politeness = "assertive" if role == "alert" else "polite"

    validation = DomAriaValidation(
        valid=node.validation.valid,
        message=_sanitize_text(node.validation.message),
        required=node.validation.required
        or state_values.get("required", "").lower() in {"true", "1", "required"},
        invalid_state=_sanitize_text(
            node.validation.invalid_state or state_values.get("invalid", "")
        ),
    )

    safe_attrs = _safe_attributes(node.attributes)
    meta = DomAriaSourceMetadata(
        metadata_id=f"meta:{node_id}",
        node_id=node_id,
        tag_name=tag,
        css_classes=tuple(_sanitize_text(c) for c in node.css_classes if c),
        css_inline_summary=_summarize_css(node.css_inline),
        framework_hints={
            _sanitize_text(k): _sanitize_text(v) for k, v in node.framework_hints.items()
        },
        attributes_retained=safe_attrs,
        source_span=node.source_span,
    )

    sanitized = DomAriaNode(
        node_id=node_id,
        role=role,
        name=_sanitize_text(node.name),
        description=_sanitize_text(node.description),
        value=_sanitize_text(node.value),
        states=DomAriaNodeState(values=state_values),
        relationships=node.relationships,
        actions=tuple(dict.fromkeys(actions)),
        children=node.children,
        focus_order=node.focus_order,
        validation=validation,
        live=DomAriaLiveRegion(
            politeness=live_politeness,
            atomic=bool(node.live.atomic),
            relevant=_sanitize_text(node.live.relevant) or "additions text",
        ),
        tag_name=tag,
        css_classes=meta.css_classes,
        css_inline=meta.css_inline_summary,
        framework_hints=meta.framework_hints,
        attributes=safe_attrs,
        text_content=_sanitize_text(node.text_content),
        source_span=node.source_span,
    )
    return node_id, role, losses, meta, sanitized


def _normalize_role(
    role: str,
    tag: str,
    input_type: str,
    path: str,
    losses: list[DomAriaLoss],
) -> str | None:
    raw = (role or "").strip().lower()
    if raw.startswith("aria:"):
        raw = raw[5:]
    if not raw:
        raw = _infer_role(tag, input_type)
    raw = _ROLE_ALIASES.get(raw, raw)
    if not raw:
        losses.append(
            DomAriaLoss(
                loss_id=f"loss:role-missing:{path}",
                path=f"{path}/role",
                reason="Node has no resolvable ARIA/HTML role in the supported subset",
                category=DomAriaLossCategory.UNSUPPORTED,
            )
        )
        return None
    if not _ROLE_TOKEN_RE.fullmatch(raw):
        losses.append(
            DomAriaLoss(
                loss_id=f"loss:role-invalid:{path}",
                path=f"{path}/role",
                reason=f"Role token {raw!r} is not a stable ARIA role token",
                category=DomAriaLossCategory.REJECTED,
                detail=raw,
            )
        )
        return None
    if raw not in SUPPORTED_ARIA_ROLES:
        losses.append(
            DomAriaLoss(
                loss_id=f"loss:role-unsupported:{path}",
                path=f"{path}/role",
                reason=f"Role {raw!r} is outside the reviewed DOM/ARIA subset",
                category=DomAriaLossCategory.UNSUPPORTED,
                detail=raw,
            )
        )
        return None
    return raw


def _infer_role(tag: str, input_type: str) -> str:
    tag_l = (tag or "").lower()
    if tag_l == "input":
        role = _INPUT_TYPE_ROLES.get((input_type or "text").lower(), "textbox")
        return _ROLE_ALIASES.get(role, role)
    role = _HTML_IMPLICIT_ROLES.get(tag_l, "")
    return _ROLE_ALIASES.get(role, role)


def _normalize_id(value: str, path: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise DomAriaAdapterError(f"{path} id must not be empty")
    # Allow raw ids; normalize to component: prefix for stability when needed.
    if not text.startswith("component:"):
        candidate = f"component:{_slug(text)}"
    else:
        candidate = text
    if not _IDENTIFIER_RE.fullmatch(candidate):
        # Fallback slug
        candidate = f"component:{_slug(text)}"
        if not _IDENTIFIER_RE.fullmatch(candidate):
            raise DomAriaAdapterError(f"{path} is not a stable identifier: {value!r}")
    return candidate


def _slug(value: str) -> str:
    text = re.sub(r"[^A-Za-z0-9._:/-]+", "-", value.strip())
    text = text.strip("-")
    return text[:200] or "node"


def _sanitize_text(value: str) -> str:
    if not isinstance(value, str):
        value = str(value)
    text = _CONTROL_CHARS_RE.sub("", value)
    # Strip obvious executable markup markers without interpreting HTML.
    lower = text.lower()
    for marker in _EXECUTABLE_TEXT_MARKERS:
        if marker in lower:
            # Remove script-like substrings case-insensitively.
            pattern = re.compile(re.escape(marker), re.IGNORECASE)
            text = pattern.sub("", text)
            lower = text.lower()
    # Collapse dangerous angle-bracket script shells.
    text = re.sub(r"<\s*/?\s*script[^>]*>", "", text, flags=re.IGNORECASE)
    return text.strip()


def _safe_attributes(attributes: Mapping[str, str]) -> dict[str, str]:
    safe: dict[str, str] = {}
    for key, value in attributes.items():
        key_l = key.lower()
        if key_l.startswith("on") and len(key_l) > 2:
            continue
        value_s = _sanitize_text(str(value))
        value_l = value_s.strip().lower()
        if any(value_l.startswith(scheme) for scheme in _EXECUTABLE_URI_SCHEMES):
            continue
        # Retain only non-executable descriptive attributes as metadata.
        if key_l in {
            "id",
            "name",
            "type",
            "for",
            "placeholder",
            "title",
            "alt",
            "aria-label",
            "aria-labelledby",
            "aria-describedby",
            "aria-controls",
            "aria-owns",
            "aria-live",
            "aria-invalid",
            "aria-required",
            "aria-checked",
            "aria-disabled",
            "aria-expanded",
            "aria-selected",
            "aria-pressed",
            "aria-busy",
            "aria-hidden",
            "aria-current",
            "aria-haspopup",
            "aria-valuemin",
            "aria-valuemax",
            "aria-valuenow",
            "aria-valuetext",
            "aria-level",
            "aria-orientation",
            "aria-multiline",
            "aria-multiselectable",
            "aria-activedescendant",
            "aria-atomic",
            "aria-relevant",
            "role",
            "tabindex",
            "required",
            "disabled",
            "readonly",
            "checked",
            "value",
            "min",
            "max",
            "step",
            "data-testid",
            "data-component",
        } or key_l.startswith("data-"):
            safe[key_l] = value_s
    return safe


def _summarize_css(value: str) -> str:
    text = _sanitize_text(value)
    if len(text) > 120:
        return text[:117] + "..."
    return text


def _presentation_for_role(role: str) -> str:
    if role in {"alert", "alertdialog"}:
        return "alert"
    if role in {"status", "log", "progressbar"}:
        return "status"
    if role in {
        "banner",
        "complementary",
        "contentinfo",
        "main",
        "navigation",
        "region",
        "search",
    }:
        return "landmark"
    if role in {"img", "separator", "presentation", "none"}:
        return "decorative" if role in {"presentation", "none", "separator"} else "media"
    if role in {"heading", "list", "listitem", "table", "row", "cell", "group"}:
        return "structure"
    return "interactive"


def _purpose_for(role: str, name: str, text: str) -> str:
    label = name or text or role
    return f"{role}: {label}"[:256]


def _is_sensitive(node: DomAriaNode) -> bool:
    attrs = {k.lower(): v.lower() for k, v in node.attributes.items()}
    if attrs.get("type") == "password":
        return True
    name = (node.name + " " + node.tag_name).lower()
    return any(
        token in name
        for token in ("password", "secret", "token", "ssn", "credit-card")
    )


def _is_focusable(role: str, states: Mapping[str, str]) -> bool:
    role_l = role.removeprefix("aria:")
    if states.get("disabled", "").lower() in {"true", "1", "disabled"}:
        return False
    if states.get("hidden", "").lower() in {"true", "1", "hidden"}:
        return False
    return role_l in {
        "button",
        "link",
        "textbox",
        "checkbox",
        "radio",
        "switch",
        "combobox",
        "listbox",
        "option",
        "slider",
        "spinbutton",
        "tab",
        "menuitem",
        "treeitem",
        "search",
        "dialog",
        "alertdialog",
    }


def _optional_bool(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"true", "1", "yes"}:
        return True
    if text in {"false", "0", "no"}:
        return False
    return None


def _digest_snapshot(snapshot: DomAriaDocument) -> str:
    payload = {
        "document_id": snapshot.document_id,
        "title": snapshot.title,
        "root": _node_digest_payload(snapshot.root),
    }
    text = repr(payload)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _node_digest_payload(node: DomAriaNode) -> dict[str, Any]:
    return {
        "actions": list(node.actions),
        "children": [_node_digest_payload(child) for child in node.children],
        "name": node.name,
        "node_id": node.node_id,
        "role": node.role,
        "states": dict(node.states.values),
        "value": node.value,
    }


__all__ = [
    "DOMARIAUIIRAdapter",
    "DOMARIA_UIIR_ADAPTER",
    "DOMARIA_UIIR_ADAPTER_VERSION",
    "DomAriaAdapterError",
    "DomAriaAdapterResult",
    "DomAriaDocument",
    "DomAriaLiveRegion",
    "DomAriaLoss",
    "DomAriaLossCategory",
    "DomAriaNode",
    "DomAriaNodeState",
    "DomAriaSourceMetadata",
    "DomAriaValidation",
    "SUPPORTED_ACTION_KINDS",
    "SUPPORTED_ARIA_ROLES",
    "SUPPORTED_RELATIONSHIP_KEYS",
    "SUPPORTED_STATE_KEYS",
    "adapt_dom_aria_to_uiir",
    "parse_dom_aria_node",
]
