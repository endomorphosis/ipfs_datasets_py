"""Abstract layout constraints and adaptation (UILayoutConstraints@1).

Layout is expressed as constraints over regions, order axes, containment,
alignment, budgets, and capability predicates. Logical reading order and focus
order are first-class axes distinct from visual order. Responsive breakpoints
are capability predicates, never target CSS media queries.

Target-specific CSS, pixel recipes, and executable layout expressions are
rejected. Required actions and feedback must carry ``preserve`` or ``fallback``
adaptation policies so projection cannot silently drop them.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Any, Final, Iterable, Mapping, Sequence

from ..schema import (
    AdaptationPolicy,
    LayoutRegionKind,
    UIDesignTokenRef,
    UILayoutConstraint,
    UILayoutRegion,
    UIIRValidationError,
)

UI_LAYOUT_CONSTRAINTS_INTERFACE: Final = "UILayoutConstraints@1"

# Closed vocabulary of abstract constraint kinds (not CSS properties).
LAYOUT_CONSTRAINT_KINDS: Final = frozenset(
    {
        "order",
        "containment",
        "alignment",
        "adjacency",
        "priority",
        "visibility",
        "minimum_readable_size",
        "resource_budget",
        "capability_predicate",
        "safe_area",
        "field_of_view",
        "text_density",
        "action_count",
        "update_rate",
        "latency",
        "attention_budget",
        "logical_reading_order",
        "focus_order",
        "visual_order",
    }
)

DESIGN_TOKEN_CATEGORIES: Final = frozenset(
    {
        "type",
        "spacing",
        "color_intent",
        "emphasis",
        "motion",
        "haptics",
        "audio_cues",
    }
)

# Required semantics must not use omit (or unconstrained adapt without fallback).
_REQUIRED_SAFE_POLICIES: Final = frozenset(
    {
        AdaptationPolicy.PRESERVE,
        AdaptationPolicy.FALLBACK,
    }
)

_CSS_OR_EXECUTABLE_PATTERNS: Final = (
    re.compile(r"(?i)@media\b"),
    re.compile(r"(?i)\bmedia\s*query\b"),
    re.compile(r"(?i)\b(?:px|em|rem|vw|vh|vmin|vmax)\b"),
    re.compile(r"(?i)\bcalc\s*\("),
    re.compile(r"(?i)\bvar\s*\(--"),
    re.compile(r"(?i)\b(?:display|flex|grid|position|z-index|margin|padding)\s*:"),
    re.compile(r"(?i)\bstyle\s*="),
    re.compile(r"(?i)<style\b"),
    re.compile(r"(?i)\.css\b"),
    re.compile(r"(?i)\bjavascript\b"),
    re.compile(r"(?i)\beval\s*\("),
    re.compile(r"(?i)\bfunction\s*\("),
    re.compile(r"(?i)\b=>\s*\{"),
    re.compile(r"(?i)\bon[a-z]+\s*="),
    re.compile(r"(?i)\bdocument\.(?:querySelector|getElementById)\b"),
    re.compile(r"(?i)\bwindow\."),
    re.compile(r"(?i)\bSwiftUI\b"),
    re.compile(r"(?i)\bCompose\b"),
    re.compile(r"(?i)\bFlutter\b"),
)

_FORBIDDEN_LAYOUT_KEYS: Final = frozenset(
    {
        "css",
        "stylesheet",
        "style",
        "styles",
        "className",
        "class_name",
        "inline_style",
        "media_query",
        "mediaQuery",
        "breakpoint_css",
        "javascript",
        "script",
        "callback",
        "handler",
        "on_click",
        "onclick",
        "expression",
        "expr",
        "code",
        "eval",
        "exec",
        "lambda",
        "function",
        "jsx",
        "tsx",
    }
)


class OrderAxis(str, Enum):
    """Distinct ordering axes; reading/focus are never equated to visual."""

    VISUAL = "visual"
    READING = "reading"
    FOCUS = "focus"


class ResourceBudgetKind(str, Enum):
    """Resource and attention budgets for adaptive projection."""

    ATTENTION = "attention"
    ACTION_COUNT = "action_count"
    TEXT_DENSITY = "text_density"
    UPDATE_RATE = "update_rate"
    LATENCY = "latency"
    FIELD_OF_VIEW = "field_of_view"
    SAFE_AREA = "safe_area"
    MEMORY = "memory"
    BANDWIDTH = "bandwidth"


@dataclass(frozen=True, slots=True)
class CapabilityPredicate:
    """Responsive condition expressed only over capability identifiers."""

    predicate_id: str
    required_capability_ids: tuple[str, ...]
    forbidden_capability_ids: tuple[str, ...] = ()
    description: str = ""

    def validate(self) -> None:
        if not isinstance(self.predicate_id, str) or not self.predicate_id:
            raise UIIRValidationError(
                "CapabilityPredicate.predicate_id must be a non-empty string"
            )
        if not isinstance(self.required_capability_ids, tuple):
            raise UIIRValidationError(
                "CapabilityPredicate.required_capability_ids must be an "
                "immutable tuple"
            )
        if not self.required_capability_ids and not self.forbidden_capability_ids:
            raise UIIRValidationError(
                f"CapabilityPredicate {self.predicate_id!r} must declare at "
                "least one capability condition"
            )
        _require_unique_ids(
            self.required_capability_ids,
            "CapabilityPredicate.required_capability_ids",
        )
        if not isinstance(self.forbidden_capability_ids, tuple):
            raise UIIRValidationError(
                "CapabilityPredicate.forbidden_capability_ids must be an "
                "immutable tuple"
            )
        _require_unique_ids(
            self.forbidden_capability_ids,
            "CapabilityPredicate.forbidden_capability_ids",
        )
        overlap = set(self.required_capability_ids) & set(
            self.forbidden_capability_ids
        )
        if overlap:
            raise UIIRValidationError(
                f"CapabilityPredicate {self.predicate_id!r} has capabilities "
                f"both required and forbidden: {', '.join(sorted(overlap))}"
            )
        if not isinstance(self.description, str):
            raise UIIRValidationError(
                "CapabilityPredicate.description must be a string"
            )
        _reject_css_or_executable_text(
            self.description, f"CapabilityPredicate {self.predicate_id!r}.description"
        )
        for cap in self.required_capability_ids + self.forbidden_capability_ids:
            _reject_css_or_executable_text(
                cap, f"CapabilityPredicate {self.predicate_id!r} capability"
            )
            if _looks_like_css_breakpoint(cap):
                raise UIIRValidationError(
                    f"CapabilityPredicate {self.predicate_id!r} capability "
                    f"{cap!r} looks like a CSS breakpoint; use device "
                    "capabilities instead"
                )

    def to_dict(self) -> dict[str, Any]:
        return {
            "description": self.description,
            "forbidden_capability_ids": sorted(set(self.forbidden_capability_ids)),
            "predicate_id": self.predicate_id,
            "required_capability_ids": sorted(set(self.required_capability_ids)),
        }


@dataclass(frozen=True, slots=True)
class LayoutOrder:
    """Ordered component sequence on a single order axis."""

    axis: OrderAxis
    component_ids: tuple[str, ...]
    region_id: str = ""

    def validate(self) -> None:
        if not isinstance(self.axis, OrderAxis):
            raise UIIRValidationError("LayoutOrder.axis must be an OrderAxis")
        if not isinstance(self.component_ids, tuple):
            raise UIIRValidationError(
                "LayoutOrder.component_ids must be an immutable tuple"
            )
        if not self.component_ids:
            raise UIIRValidationError(
                f"LayoutOrder on axis {self.axis.value!r} must list components"
            )
        _require_unique_ids(self.component_ids, f"LayoutOrder.{self.axis.value}")
        if not isinstance(self.region_id, str):
            raise UIIRValidationError("LayoutOrder.region_id must be a string")

    def to_dict(self) -> dict[str, Any]:
        return {
            "axis": self.axis.value,
            "component_ids": list(self.component_ids),
            "region_id": self.region_id,
        }


@dataclass(frozen=True, slots=True)
class ResourceBudget:
    """Bounded resource or attention budget for a region or document."""

    budget_id: str
    kind: ResourceBudgetKind
    limit: int
    unit: str = "count"
    region_id: str = ""

    def validate(self) -> None:
        if not isinstance(self.budget_id, str) or not self.budget_id:
            raise UIIRValidationError(
                "ResourceBudget.budget_id must be a non-empty string"
            )
        if not isinstance(self.kind, ResourceBudgetKind):
            raise UIIRValidationError(
                "ResourceBudget.kind must be a ResourceBudgetKind"
            )
        if not isinstance(self.limit, int) or self.limit < 0:
            raise UIIRValidationError(
                "ResourceBudget.limit must be a non-negative integer"
            )
        if not isinstance(self.unit, str) or not self.unit:
            raise UIIRValidationError("ResourceBudget.unit must be a non-empty string")
        if not isinstance(self.region_id, str):
            raise UIIRValidationError("ResourceBudget.region_id must be a string")
        _reject_css_or_executable_text(
            self.unit, f"ResourceBudget {self.budget_id!r}.unit"
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "budget_id": self.budget_id,
            "kind": self.kind.value,
            "limit": self.limit,
            "region_id": self.region_id,
            "unit": self.unit,
        }


@dataclass(frozen=True, slots=True)
class RequiredSemanticPolicy:
    """Adaptation policy attached to a required action or feedback surface."""

    semantic_id: str
    semantic_kind: str
    adaptation_policy: AdaptationPolicy
    fallback_ref: str = ""
    required: bool = True

    def validate(self) -> None:
        if not isinstance(self.semantic_id, str) or not self.semantic_id:
            raise UIIRValidationError(
                "RequiredSemanticPolicy.semantic_id must be a non-empty string"
            )
        if self.semantic_kind not in {"action", "feedback", "confirmation", "error", "privacy", "accessibility"}:
            raise UIIRValidationError(
                f"RequiredSemanticPolicy.semantic_kind {self.semantic_kind!r} "
                "is not a supported required-semantic kind"
            )
        if not isinstance(self.adaptation_policy, AdaptationPolicy):
            raise UIIRValidationError(
                "RequiredSemanticPolicy.adaptation_policy must be an "
                "AdaptationPolicy"
            )
        if not isinstance(self.required, bool):
            raise UIIRValidationError(
                "RequiredSemanticPolicy.required must be a boolean"
            )
        if not isinstance(self.fallback_ref, str):
            raise UIIRValidationError(
                "RequiredSemanticPolicy.fallback_ref must be a string"
            )
        if self.required:
            if self.adaptation_policy not in _REQUIRED_SAFE_POLICIES:
                raise UIIRValidationError(
                    f"required {self.semantic_kind} {self.semantic_id!r} must use "
                    f"preserve or fallback adaptation policy, not "
                    f"{self.adaptation_policy.value!r}"
                )
            if (
                self.adaptation_policy is AdaptationPolicy.FALLBACK
                and not self.fallback_ref
            ):
                raise UIIRValidationError(
                    f"required {self.semantic_kind} {self.semantic_id!r} with "
                    "fallback policy must declare fallback_ref"
                )

    def to_dict(self) -> dict[str, Any]:
        return {
            "adaptation_policy": self.adaptation_policy.value,
            "fallback_ref": self.fallback_ref,
            "required": self.required,
            "semantic_id": self.semantic_id,
            "semantic_kind": self.semantic_kind,
        }


@dataclass(frozen=True, slots=True)
class AbstractLayoutConstraint:
    """Typed abstract layout constraint (not a CSS rule)."""

    constraint_id: str
    kind: str
    region_ids: tuple[str, ...] = ()
    component_ids: tuple[str, ...] = ()
    adaptation_policy: AdaptationPolicy = AdaptationPolicy.PRESERVE
    capability_predicate_id: str = ""
    order_axis: OrderAxis | None = None
    token_ref_ids: tuple[str, ...] = ()
    expression_ref: str = ""
    metadata: Mapping[str, str] = MappingProxyType({})

    def __post_init__(self) -> None:
        if not isinstance(self.metadata, MappingProxyType):
            object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))

    def validate(self) -> None:
        if not isinstance(self.constraint_id, str) or not self.constraint_id:
            raise UIIRValidationError(
                "AbstractLayoutConstraint.constraint_id must be a non-empty string"
            )
        if self.kind not in LAYOUT_CONSTRAINT_KINDS:
            raise UIIRValidationError(
                f"AbstractLayoutConstraint {self.constraint_id!r}.kind "
                f"{self.kind!r} is not in the closed abstract vocabulary"
            )
        if not isinstance(self.adaptation_policy, AdaptationPolicy):
            raise UIIRValidationError(
                "AbstractLayoutConstraint.adaptation_policy must be an "
                "AdaptationPolicy"
            )
        for field_name in ("region_ids", "component_ids", "token_ref_ids"):
            values = getattr(self, field_name)
            if not isinstance(values, tuple):
                raise UIIRValidationError(
                    f"AbstractLayoutConstraint.{field_name} must be an "
                    "immutable tuple"
                )
            _require_unique_ids(values, f"AbstractLayoutConstraint.{field_name}")
        if self.order_axis is not None and not isinstance(self.order_axis, OrderAxis):
            raise UIIRValidationError(
                "AbstractLayoutConstraint.order_axis must be OrderAxis or None"
            )
        if self.kind in {"logical_reading_order", "focus_order", "visual_order", "order"}:
            if self.order_axis is None and self.kind != "order":
                # Map kind to axis when order_axis omitted.
                pass
            if self.kind == "logical_reading_order" and self.order_axis not in (
                None,
                OrderAxis.READING,
            ):
                raise UIIRValidationError(
                    f"constraint {self.constraint_id!r} kind logical_reading_order "
                    "cannot use a non-reading order_axis"
                )
            if self.kind == "focus_order" and self.order_axis not in (
                None,
                OrderAxis.FOCUS,
            ):
                raise UIIRValidationError(
                    f"constraint {self.constraint_id!r} kind focus_order cannot "
                    "use a non-focus order_axis"
                )
            if self.kind == "visual_order" and self.order_axis not in (
                None,
                OrderAxis.VISUAL,
            ):
                raise UIIRValidationError(
                    f"constraint {self.constraint_id!r} kind visual_order cannot "
                    "use a non-visual order_axis"
                )
        if self.kind == "capability_predicate" and not self.capability_predicate_id:
            raise UIIRValidationError(
                f"constraint {self.constraint_id!r} kind=capability_predicate "
                "requires capability_predicate_id"
            )
        if not isinstance(self.capability_predicate_id, str):
            raise UIIRValidationError(
                "AbstractLayoutConstraint.capability_predicate_id must be a string"
            )
        if not isinstance(self.expression_ref, str):
            raise UIIRValidationError(
                "AbstractLayoutConstraint.expression_ref must be a string"
            )
        if self.expression_ref:
            _reject_css_or_executable_text(
                self.expression_ref,
                f"AbstractLayoutConstraint {self.constraint_id!r}.expression_ref",
            )
            if _looks_like_css_breakpoint(self.expression_ref) or any(
                marker in self.expression_ref.lower()
                for marker in ("css", "calc(", "px", "media")
            ):
                raise UIIRValidationError(
                    f"AbstractLayoutConstraint {self.constraint_id!r}.expression_ref "
                    "must not embed CSS or executable layout expressions; use a "
                    "stable formal expression_ref identifier only"
                )
        if not isinstance(self.metadata, Mapping):
            raise UIIRValidationError(
                "AbstractLayoutConstraint.metadata must be a mapping"
            )
        for key, value in self.metadata.items():
            if not isinstance(key, str) or not isinstance(value, str):
                raise UIIRValidationError(
                    "AbstractLayoutConstraint.metadata keys and values must be strings"
                )
            if key in _FORBIDDEN_LAYOUT_KEYS or key.lower() in _FORBIDDEN_LAYOUT_KEYS:
                raise UIIRValidationError(
                    f"AbstractLayoutConstraint {self.constraint_id!r} metadata "
                    f"key {key!r} is a forbidden CSS/executable field"
                )
            _reject_css_or_executable_text(
                value,
                f"AbstractLayoutConstraint {self.constraint_id!r}.metadata/{key}",
            )

    def to_envelope_constraint(self) -> UILayoutConstraint:
        """Project to the closed envelope ``UILayoutConstraint`` record."""

        return UILayoutConstraint(
            constraint_id=self.constraint_id,
            kind=self.kind,
            region_ids=self.region_ids,
            component_ids=self.component_ids,
            adaptation_policy=self.adaptation_policy,
            expression_ref=self.expression_ref,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "adaptation_policy": self.adaptation_policy.value,
            "capability_predicate_id": self.capability_predicate_id,
            "component_ids": sorted(set(self.component_ids)),
            "constraint_id": self.constraint_id,
            "expression_ref": self.expression_ref,
            "kind": self.kind,
            "metadata": dict(self.metadata),
            "order_axis": self.order_axis.value if self.order_axis else "",
            "region_ids": sorted(set(self.region_ids)),
            "token_ref_ids": sorted(set(self.token_ref_ids)),
        }


@dataclass(frozen=True, slots=True)
class UILayoutConstraints:
    """Validated abstract layout model (UILayoutConstraints@1)."""

    regions: tuple[UILayoutRegion, ...]
    constraints: tuple[AbstractLayoutConstraint, ...] = ()
    orders: tuple[LayoutOrder, ...] = ()
    capability_predicates: tuple[CapabilityPredicate, ...] = ()
    design_token_refs: tuple[UIDesignTokenRef, ...] = ()
    resource_budgets: tuple[ResourceBudget, ...] = ()
    required_semantics: tuple[RequiredSemanticPolicy, ...] = ()
    known_component_ids: tuple[str, ...] = ()

    def validate(self) -> "UILayoutConstraints":
        """Validate orders, predicates, budgets, and reject CSS/executable forms."""

        if not isinstance(self.regions, tuple):
            raise UIIRValidationError(
                "UILayoutConstraints.regions must be an immutable tuple"
            )
        region_ids: set[str] = set()
        component_ids_from_regions: set[str] = set()
        for region in self.regions:
            if not isinstance(region, UILayoutRegion):
                raise UIIRValidationError(
                    "UILayoutConstraints.regions members must be UILayoutRegion"
                )
            region.validate()
            if region.region_id in region_ids:
                raise UIIRValidationError(
                    f"Duplicate layout region id: {region.region_id}"
                )
            region_ids.add(region.region_id)
            if not isinstance(region.kind, LayoutRegionKind):
                raise UIIRValidationError(
                    f"region {region.region_id!r} kind must be LayoutRegionKind"
                )
            component_ids_from_regions.update(region.component_ids)

        known_components = set(self.known_component_ids) | component_ids_from_regions
        for component_id in self.known_component_ids:
            if not isinstance(component_id, str) or not component_id:
                raise UIIRValidationError(
                    "UILayoutConstraints.known_component_ids members must be "
                    "non-empty strings"
                )

        predicate_ids: set[str] = set()
        for predicate in self.capability_predicates:
            if not isinstance(predicate, CapabilityPredicate):
                raise UIIRValidationError(
                    "UILayoutConstraints.capability_predicates members must be "
                    "CapabilityPredicate"
                )
            predicate.validate()
            if predicate.predicate_id in predicate_ids:
                raise UIIRValidationError(
                    f"Duplicate capability predicate id: {predicate.predicate_id}"
                )
            predicate_ids.add(predicate.predicate_id)

        token_ids: set[str] = set()
        for token in self.design_token_refs:
            if not isinstance(token, UIDesignTokenRef):
                raise UIIRValidationError(
                    "UILayoutConstraints.design_token_refs members must be "
                    "UIDesignTokenRef"
                )
            token.validate()
            if token.token_id in token_ids:
                raise UIIRValidationError(
                    f"Duplicate design token id: {token.token_id}"
                )
            token_ids.add(token.token_id)
            if token.category not in DESIGN_TOKEN_CATEGORIES:
                raise UIIRValidationError(
                    f"design token {token.token_id!r} category "
                    f"{token.category!r} is not in the closed design-token "
                    "vocabulary"
                )
            _reject_css_or_executable_text(
                token.token_name, f"UIDesignTokenRef {token.token_id!r}.token_name"
            )
            if re.search(r"(?i)\d+px\b", token.token_name):
                raise UIIRValidationError(
                    f"design token {token.token_id!r} must not encode device "
                    "pixel values"
                )

        budget_ids: set[str] = set()
        for budget in self.resource_budgets:
            if not isinstance(budget, ResourceBudget):
                raise UIIRValidationError(
                    "UILayoutConstraints.resource_budgets members must be "
                    "ResourceBudget"
                )
            budget.validate()
            if budget.budget_id in budget_ids:
                raise UIIRValidationError(
                    f"Duplicate resource budget id: {budget.budget_id}"
                )
            budget_ids.add(budget.budget_id)
            if budget.region_id and budget.region_id not in region_ids:
                raise UIIRValidationError(
                    f"ResourceBudget {budget.budget_id!r} references unknown "
                    f"region {budget.region_id!r}"
                )

        constraint_ids: set[str] = set()
        for constraint in self.constraints:
            if not isinstance(constraint, AbstractLayoutConstraint):
                raise UIIRValidationError(
                    "UILayoutConstraints.constraints members must be "
                    "AbstractLayoutConstraint"
                )
            constraint.validate()
            if constraint.constraint_id in constraint_ids:
                raise UIIRValidationError(
                    f"Duplicate layout constraint id: {constraint.constraint_id}"
                )
            constraint_ids.add(constraint.constraint_id)
            for region_id in constraint.region_ids:
                if region_id not in region_ids:
                    raise UIIRValidationError(
                        f"constraint {constraint.constraint_id!r} references "
                        f"unknown region {region_id!r}"
                    )
            for component_id in constraint.component_ids:
                if known_components and component_id not in known_components:
                    raise UIIRValidationError(
                        f"constraint {constraint.constraint_id!r} references "
                        f"unknown component {component_id!r}"
                    )
            for token_id in constraint.token_ref_ids:
                if token_id not in token_ids:
                    raise UIIRValidationError(
                        f"constraint {constraint.constraint_id!r} references "
                        f"unknown design token {token_id!r}"
                    )
            if (
                constraint.capability_predicate_id
                and constraint.capability_predicate_id not in predicate_ids
            ):
                raise UIIRValidationError(
                    f"constraint {constraint.constraint_id!r} references "
                    f"unknown capability predicate "
                    f"{constraint.capability_predicate_id!r}"
                )

        _validate_order_axes(self.orders, region_ids, known_components)

        semantic_ids: set[str] = set()
        for policy in self.required_semantics:
            if not isinstance(policy, RequiredSemanticPolicy):
                raise UIIRValidationError(
                    "UILayoutConstraints.required_semantics members must be "
                    "RequiredSemanticPolicy"
                )
            policy.validate()
            key = f"{policy.semantic_kind}:{policy.semantic_id}"
            if key in semantic_ids:
                raise UIIRValidationError(
                    f"Duplicate required semantic policy: {key}"
                )
            semantic_ids.add(key)

        return self

    def order_for(self, axis: OrderAxis) -> tuple[LayoutOrder, ...]:
        return tuple(order for order in self.orders if order.axis is axis)

    def reading_order_ids(self) -> tuple[str, ...]:
        orders = self.order_for(OrderAxis.READING)
        if not orders:
            return ()
        return orders[0].component_ids

    def focus_order_ids(self) -> tuple[str, ...]:
        orders = self.order_for(OrderAxis.FOCUS)
        if not orders:
            return ()
        return orders[0].component_ids

    def visual_order_ids(self) -> tuple[str, ...]:
        orders = self.order_for(OrderAxis.VISUAL)
        if not orders:
            return ()
        return orders[0].component_ids

    def to_envelope_constraints(self) -> tuple[UILayoutConstraint, ...]:
        return tuple(
            constraint.to_envelope_constraint() for constraint in self.constraints
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "capability_predicates": [
                item.to_dict()
                for item in sorted(
                    self.capability_predicates, key=lambda p: p.predicate_id
                )
            ],
            "constraints": [
                item.to_dict()
                for item in sorted(self.constraints, key=lambda c: c.constraint_id)
            ],
            "design_token_refs": [
                item.to_dict()
                for item in sorted(self.design_token_refs, key=lambda t: t.token_id)
            ],
            "interface": UI_LAYOUT_CONSTRAINTS_INTERFACE,
            "known_component_ids": sorted(set(self.known_component_ids)),
            "orders": [item.to_dict() for item in self.orders],
            "regions": [
                item.to_dict()
                for item in sorted(self.regions, key=lambda r: r.region_id)
            ],
            "required_semantics": [
                item.to_dict()
                for item in sorted(
                    self.required_semantics, key=lambda s: s.semantic_id
                )
            ],
            "resource_budgets": [
                item.to_dict()
                for item in sorted(self.resource_budgets, key=lambda b: b.budget_id)
            ],
        }


def validate_layout_constraints(model: UILayoutConstraints) -> UILayoutConstraints:
    """Validate and return a closed abstract layout model."""

    if not isinstance(model, UILayoutConstraints):
        raise UIIRValidationError("expected UILayoutConstraints")
    return model.validate()


def reject_css_or_executable_layout(value: Any, label: str = "layout payload") -> None:
    """Public fail-closed scan for CSS and executable layout expressions."""

    if callable(value) or isinstance(value, type):
        raise UIIRValidationError(f"{label} contains an executable callback")
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise UIIRValidationError(f"{label} map keys must be strings")
            if key in _FORBIDDEN_LAYOUT_KEYS or key.lower() in {
                k.lower() for k in _FORBIDDEN_LAYOUT_KEYS
            }:
                raise UIIRValidationError(
                    f"{label}/{key} is a forbidden CSS or executable layout field"
                )
            reject_css_or_executable_layout(item, f"{label}/{key}")
        return
    if isinstance(value, str):
        _reject_css_or_executable_text(value, label)
        return
    if isinstance(value, (bytes, bytearray)) or value is None:
        return
    if isinstance(value, (set, frozenset)):
        for index, item in enumerate(sorted(value, key=repr)):
            reject_css_or_executable_layout(item, f"{label}{{{index}}}")
        return
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for index, item in enumerate(value):
            reject_css_or_executable_layout(item, f"{label}[{index}]")
        return


def _validate_order_axes(
    orders: Sequence[LayoutOrder],
    region_ids: set[str],
    known_components: set[str],
) -> None:
    if not isinstance(orders, tuple):
        raise UIIRValidationError(
            "UILayoutConstraints.orders must be an immutable tuple"
        )
    seen_scopes: set[tuple[OrderAxis, str]] = set()
    for order in orders:
        if not isinstance(order, LayoutOrder):
            raise UIIRValidationError(
                "UILayoutConstraints.orders members must be LayoutOrder"
            )
        order.validate()
        if order.region_id and order.region_id not in region_ids:
            raise UIIRValidationError(
                f"LayoutOrder axis {order.axis.value!r} references unknown "
                f"region {order.region_id!r}"
            )
        for component_id in order.component_ids:
            if known_components and component_id not in known_components:
                raise UIIRValidationError(
                    f"LayoutOrder axis {order.axis.value!r} references unknown "
                    f"component {component_id!r}"
                )
        scope = (order.axis, order.region_id)
        if scope in seen_scopes:
            raise UIIRValidationError(
                f"duplicate LayoutOrder for axis {order.axis.value!r} "
                f"region {order.region_id!r}"
            )
        seen_scopes.add(scope)


def _require_unique_ids(values: Iterable[str], label: str) -> None:
    seen: set[str] = set()
    for value in values:
        if not isinstance(value, str) or not value:
            raise UIIRValidationError(f"{label} members must be non-empty strings")
        if value in seen:
            raise UIIRValidationError(f"Duplicate {label} id: {value}")
        seen.add(value)


def _looks_like_css_breakpoint(text: str) -> bool:
    lowered = text.lower()
    if "max-width" in lowered or "min-width" in lowered:
        return True
    if re.search(r"\d+px", lowered):
        return True
    if "@media" in lowered:
        return True
    if re.search(r"\b(?:sm|md|lg|xl|xxl)-\d+", lowered):
        # Bootstrap-style CSS breakpoint tokens
        return "bootstrap" in lowered or "breakpoint" in lowered
    return False


def _reject_css_or_executable_text(text: str, label: str) -> None:
    if not isinstance(text, str):
        return
    for pattern in _CSS_OR_EXECUTABLE_PATTERNS:
        if pattern.search(text):
            raise UIIRValidationError(
                f"{label} contains forbidden CSS or executable layout content"
            )


__all__ = [
    "AbstractLayoutConstraint",
    "CapabilityPredicate",
    "DESIGN_TOKEN_CATEGORIES",
    "LAYOUT_CONSTRAINT_KINDS",
    "LayoutOrder",
    "OrderAxis",
    "RequiredSemanticPolicy",
    "ResourceBudget",
    "ResourceBudgetKind",
    "UI_LAYOUT_CONSTRAINTS_INTERFACE",
    "UILayoutConstraints",
    "reject_css_or_executable_layout",
    "validate_layout_constraints",
]
