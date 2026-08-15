"""Bounded capability-constrained projection solver (UIProjectionSolver@1).

Negotiates capabilities, enforces action/text/update/FOV/latency/attention/
safe-area budgets, ranks valid presentation variants, and emits deterministic
projection artifacts with explicit loss receipts. Mandatory semantics are never
silently omitted; unsatisfiable cores produce an explicit result.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Final, Mapping, Sequence

from ..schema import AdaptationPolicy, UIIRDocument, UIIRValidationError
from .capabilities import (
    BudgetKind,
    CapabilityNegotiationResult,
    CapabilityRequirement,
    NegotiationStatus,
    UIDeviceProfile,
    negotiate_capabilities,
    validate_device_profile,
)
from .loss import (
    LossCategory,
    MANDATORY_SEMANTIC_KINDS,
    MandatorySemanticKind,
    ProjectionLoss,
    ProjectionLossReport,
    assert_no_silent_mandatory_omission,
    build_loss_report,
    make_loss,
)

UI_PROJECTION_SOLVER_INTERFACE: Final = "UIProjectionSolver@1"
UI_PROJECTION_ARTIFACT_INTERFACE: Final = "UIProjectionArtifact@1"
UI_PROJECTION_ARTIFACT_SCHEMA_VERSION: Final = "ui-projection-artifact/v1"
UI_PROJECTION_POLICY_SCHEMA_VERSION: Final = "ui-projection-policy/v1"

# Attention cost defaults by mandatory semantic kind (points).
_DEFAULT_ATTENTION_COST: Final[dict[str, int]] = {
    MandatorySemanticKind.ACTION.value: 5,
    MandatorySemanticKind.CONSENT.value: 8,
    MandatorySemanticKind.CONSEQUENCE.value: 6,
    MandatorySemanticKind.ERROR.value: 4,
    MandatorySemanticKind.CONFIRMATION.value: 7,
    MandatorySemanticKind.FEEDBACK.value: 3,
    MandatorySemanticKind.ACCESSIBILITY.value: 2,
    MandatorySemanticKind.PRIVACY.value: 4,
}


class ProjectionStatus(str, Enum):
    """Top-level projection solve outcome."""

    SATISFIED = "satisfied"
    DEGRADED = "degraded"
    FALLBACK = "fallback"
    UNSATISFIABLE = "unsatisfiable"
    BOUND_EXCEEDED = "bound_exceeded"


class PresentationDisposition(str, Enum):
    """How one projected item appears in the selected variant."""

    PRESERVED = "preserved"
    ADAPTED = "adapted"
    SUMMARIZED = "summarized"
    FALLBACK = "fallback"
    OMITTED = "omitted"
    UNSATISFIABLE = "unsatisfiable"


@dataclass(frozen=True, slots=True)
class ProjectionItem:
    """One projectable semantic unit with budget weights and adaptation policy."""

    item_id: str
    semantic_kind: str
    mandatory: bool = False
    required_capability_ids: tuple[str, ...] = ()
    alternative_capability_ids: tuple[str, ...] = ()
    fallback_capability_ids: tuple[str, ...] = ()
    fallback_ref: str = ""
    adaptation_policy: AdaptationPolicy = AdaptationPolicy.PRESERVE
    action_cost: int = 1
    text_chars: int = 0
    update_rate: int = 0
    latency_ms: int = 0
    attention_cost: int | None = None
    field_of_view_share: int = 0
    safe_area_share: int = 0
    memory_nodes: int = 1
    priority: int = 100
    component_id: str = ""
    label: str = ""

    def validate(self) -> None:
        if not isinstance(self.item_id, str) or not self.item_id.strip():
            raise UIIRValidationError("ProjectionItem.item_id must be non-empty")
        if not isinstance(self.semantic_kind, str) or not self.semantic_kind.strip():
            raise UIIRValidationError(
                "ProjectionItem.semantic_kind must be non-empty"
            )
        if not isinstance(self.mandatory, bool):
            raise UIIRValidationError("ProjectionItem.mandatory must be a boolean")
        is_mandatory = self.mandatory or self.semantic_kind in MANDATORY_SEMANTIC_KINDS
        if is_mandatory and self.adaptation_policy is AdaptationPolicy.OMIT:
            raise UIIRValidationError(
                f"ProjectionItem {self.item_id!r} is mandatory and cannot declare "
                "adaptation_policy omit"
            )
        if (
            is_mandatory
            and self.adaptation_policy is AdaptationPolicy.FALLBACK
            and not self.fallback_ref
            and not self.fallback_capability_ids
        ):
            raise UIIRValidationError(
                f"ProjectionItem {self.item_id!r} fallback policy requires "
                "fallback_ref or fallback_capability_ids"
            )
        for name in (
            "action_cost",
            "text_chars",
            "update_rate",
            "latency_ms",
            "field_of_view_share",
            "safe_area_share",
            "memory_nodes",
            "priority",
        ):
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise UIIRValidationError(
                    f"ProjectionItem.{name} must be a non-negative integer"
                )
        for field_name in (
            "required_capability_ids",
            "alternative_capability_ids",
            "fallback_capability_ids",
        ):
            values = getattr(self, field_name)
            if not isinstance(values, tuple):
                raise UIIRValidationError(
                    f"ProjectionItem.{field_name} must be an immutable tuple"
                )
        if not isinstance(self.adaptation_policy, AdaptationPolicy):
            raise UIIRValidationError(
                "ProjectionItem.adaptation_policy must be an AdaptationPolicy"
            )
        if self.attention_cost is not None:
            if (
                not isinstance(self.attention_cost, int)
                or isinstance(self.attention_cost, bool)
                or self.attention_cost < 0
            ):
                raise UIIRValidationError(
                    "ProjectionItem.attention_cost must be a non-negative integer or None"
                )

    def effective_attention(self) -> int:
        if self.attention_cost is not None:
            return self.attention_cost
        if self.semantic_kind in _DEFAULT_ATTENTION_COST:
            return _DEFAULT_ATTENTION_COST[self.semantic_kind]
        return 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "action_cost": self.action_cost,
            "adaptation_policy": self.adaptation_policy.value,
            "alternative_capability_ids": list(self.alternative_capability_ids),
            "attention_cost": self.effective_attention(),
            "component_id": self.component_id,
            "fallback_capability_ids": list(self.fallback_capability_ids),
            "fallback_ref": self.fallback_ref,
            "field_of_view_share": self.field_of_view_share,
            "item_id": self.item_id,
            "label": self.label,
            "latency_ms": self.latency_ms,
            "mandatory": self.mandatory or self.semantic_kind in MANDATORY_SEMANTIC_KINDS,
            "memory_nodes": self.memory_nodes,
            "priority": self.priority,
            "required_capability_ids": list(self.required_capability_ids),
            "safe_area_share": self.safe_area_share,
            "semantic_kind": self.semantic_kind,
            "text_chars": self.text_chars,
            "update_rate": self.update_rate,
        }


@dataclass(frozen=True, slots=True)
class ProjectionProblem:
    """Bounded projection problem independent of full document wiring."""

    problem_id: str
    items: tuple[ProjectionItem, ...]
    document_id: str = ""
    capability_requirements: tuple[CapabilityRequirement, ...] = ()
    notes: tuple[str, ...] = ()

    def validate(self) -> "ProjectionProblem":
        if not isinstance(self.problem_id, str) or not self.problem_id.strip():
            raise UIIRValidationError(
                "ProjectionProblem.problem_id must be non-empty"
            )
        if not isinstance(self.items, tuple):
            raise UIIRValidationError(
                "ProjectionProblem.items must be an immutable tuple"
            )
        if not self.items:
            raise UIIRValidationError(
                "ProjectionProblem.items must not be empty"
            )
        seen: set[str] = set()
        for item in self.items:
            if not isinstance(item, ProjectionItem):
                raise UIIRValidationError(
                    "ProjectionProblem.items members must be ProjectionItem"
                )
            item.validate()
            if item.item_id in seen:
                raise UIIRValidationError(
                    f"Duplicate ProjectionItem id: {item.item_id}"
                )
            seen.add(item.item_id)
        if not isinstance(self.capability_requirements, tuple):
            raise UIIRValidationError(
                "ProjectionProblem.capability_requirements must be an immutable tuple"
            )
        for requirement in self.capability_requirements:
            if not isinstance(requirement, CapabilityRequirement):
                raise UIIRValidationError(
                    "capability_requirements members must be CapabilityRequirement"
                )
            requirement.validate()
        return self

    def to_dict(self) -> dict[str, Any]:
        return {
            "capability_requirements": [
                item.to_dict()
                for item in sorted(
                    self.capability_requirements, key=lambda r: r.requirement_id
                )
            ],
            "document_id": self.document_id,
            "items": [
                item.to_dict()
                for item in sorted(self.items, key=lambda i: i.item_id)
            ],
            "notes": list(self.notes),
            "problem_id": self.problem_id,
        }


@dataclass(frozen=True, slots=True)
class ProjectionPolicy:
    """Solver policy knobs (time/step/memory bounds and ranking preferences)."""

    policy_id: str = "policy:default"
    prefer_fallback_over_unsatisfiable: bool = True
    allow_summarize_optional: bool = True
    allow_omit_optional: bool = True
    max_variants: int = 32
    schema_version: str = UI_PROJECTION_POLICY_SCHEMA_VERSION

    def validate(self) -> "ProjectionPolicy":
        if not isinstance(self.policy_id, str) or not self.policy_id.strip():
            raise UIIRValidationError("ProjectionPolicy.policy_id must be non-empty")
        if not isinstance(self.max_variants, int) or self.max_variants < 1:
            raise UIIRValidationError(
                "ProjectionPolicy.max_variants must be a positive integer"
            )
        for name in (
            "prefer_fallback_over_unsatisfiable",
            "allow_summarize_optional",
            "allow_omit_optional",
        ):
            if not isinstance(getattr(self, name), bool):
                raise UIIRValidationError(f"ProjectionPolicy.{name} must be a boolean")
        return self

    def to_dict(self) -> dict[str, Any]:
        return {
            "allow_omit_optional": self.allow_omit_optional,
            "allow_summarize_optional": self.allow_summarize_optional,
            "max_variants": self.max_variants,
            "policy_id": self.policy_id,
            "prefer_fallback_over_unsatisfiable": self.prefer_fallback_over_unsatisfiable,
            "schema_version": self.schema_version,
        }


@dataclass(frozen=True, slots=True)
class ProjectedNode:
    """One item in the selected projection variant."""

    item_id: str
    semantic_kind: str
    disposition: PresentationDisposition
    mandatory: bool
    order: int
    fallback_ref: str = ""
    component_id: str = ""
    label: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "component_id": self.component_id,
            "disposition": self.disposition.value,
            "fallback_ref": self.fallback_ref,
            "item_id": self.item_id,
            "label": self.label,
            "mandatory": self.mandatory,
            "order": self.order,
            "semantic_kind": self.semantic_kind,
        }


@dataclass(frozen=True, slots=True)
class BudgetUsage:
    """Measured usage versus a profile budget."""

    kind: str
    used: int
    limit: int | None
    exceeded: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "exceeded": self.exceeded,
            "kind": self.kind,
            "limit": self.limit,
            "used": self.used,
        }


@dataclass(frozen=True, slots=True)
class SolverBoundsReceipt:
    """Explicit time/step/memory bound usage for the solve."""

    max_solve_ms: int
    max_solve_steps: int
    max_memory_nodes: int
    elapsed_ms: int
    steps_used: int
    memory_nodes_used: int
    bound_exceeded: bool
    exceeded_bounds: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "bound_exceeded": self.bound_exceeded,
            "elapsed_ms": self.elapsed_ms,
            "exceeded_bounds": list(self.exceeded_bounds),
            "max_memory_nodes": self.max_memory_nodes,
            "max_solve_ms": self.max_solve_ms,
            "max_solve_steps": self.max_solve_steps,
            "memory_nodes_used": self.memory_nodes_used,
            "steps_used": self.steps_used,
        }


@dataclass(frozen=True, slots=True)
class UIProjectionArtifact:
    """Deterministic projection result with negotiation and loss receipts.

    Interface identity: ``UIProjectionArtifact@1``.
    """

    artifact_id: str
    status: ProjectionStatus
    profile_id: str
    problem_id: str
    nodes: tuple[ProjectedNode, ...]
    loss_report: ProjectionLossReport
    negotiation: CapabilityNegotiationResult
    budget_usage: tuple[BudgetUsage, ...]
    bounds: SolverBoundsReceipt
    ranked_variant_scores: tuple[int, ...] = ()
    selected_variant_index: int = 0
    document_id: str = ""
    policy_id: str = ""
    schema_version: str = UI_PROJECTION_ARTIFACT_SCHEMA_VERSION
    interface: str = UI_PROJECTION_ARTIFACT_INTERFACE

    def validate(self) -> "UIProjectionArtifact":
        if not self.artifact_id.strip():
            raise UIIRValidationError(
                "UIProjectionArtifact.artifact_id must be non-empty"
            )
        if not isinstance(self.status, ProjectionStatus):
            raise UIIRValidationError(
                "UIProjectionArtifact.status must be a ProjectionStatus"
            )
        if not isinstance(self.nodes, tuple):
            raise UIIRValidationError(
                "UIProjectionArtifact.nodes must be an immutable tuple"
            )
        self.loss_report.validate()
        if self.schema_version != UI_PROJECTION_ARTIFACT_SCHEMA_VERSION:
            raise UIIRValidationError(
                f"Unsupported projection artifact schema_version: "
                f"{self.schema_version!r}"
            )
        return self

    def digest(self) -> str:
        text = json.dumps(
            self.to_dict(), ensure_ascii=True, separators=(",", ":"), sort_keys=True
        )
        return f"sha256:{hashlib.sha256(text.encode('utf-8')).hexdigest()}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "bounds": self.bounds.to_dict(),
            "budget_usage": [
                item.to_dict()
                for item in sorted(self.budget_usage, key=lambda b: b.kind)
            ],
            "document_id": self.document_id,
            "interface": self.interface,
            "loss_report": self.loss_report.to_dict(),
            "negotiation": self.negotiation.to_dict(),
            "nodes": [node.to_dict() for node in self.nodes],
            "policy_id": self.policy_id,
            "problem_id": self.problem_id,
            "profile_id": self.profile_id,
            "ranked_variant_scores": list(self.ranked_variant_scores),
            "schema_version": self.schema_version,
            "selected_variant_index": self.selected_variant_index,
            "status": self.status.value,
        }


@dataclass
class _SolveState:
    steps: int = 0
    started_monotonic: float = field(default_factory=time.monotonic)

    def tick(self, profile: UIDeviceProfile) -> None:
        self.steps += 1
        if self.steps > profile.max_solve_steps:
            raise _BoundExceeded("max_solve_steps")
        elapsed_ms = int((time.monotonic() - self.started_monotonic) * 1000)
        if elapsed_ms > profile.max_solve_ms:
            raise _BoundExceeded("max_solve_ms")


class _BoundExceeded(Exception):
    def __init__(self, bound_name: str) -> None:
        super().__init__(bound_name)
        self.bound_name = bound_name


@dataclass(frozen=True, slots=True)
class _Placement:
    item: ProjectionItem
    disposition: PresentationDisposition
    loss: ProjectionLoss | None


def _item_is_mandatory(item: ProjectionItem) -> bool:
    return item.mandatory or item.semantic_kind in MANDATORY_SEMANTIC_KINDS


def _capability_available(
    item: ProjectionItem,
    available: set[str],
) -> tuple[str, tuple[str, ...]]:
    """Return match tier and hit capabilities: primary|alternative|fallback|none."""

    primary = tuple(c for c in item.required_capability_ids if c in available)
    if primary or not item.required_capability_ids:
        return "primary", primary
    alt = tuple(c for c in item.alternative_capability_ids if c in available)
    if alt:
        return "alternative", alt
    fallback = tuple(c for c in item.fallback_capability_ids if c in available)
    if fallback:
        return "fallback", fallback
    return "none", ()


def _measure_usage(
    placements: Sequence[_Placement],
    profile: UIDeviceProfile,
) -> tuple[BudgetUsage, ...]:
    included = [
        p
        for p in placements
        if p.disposition
        not in {PresentationDisposition.OMITTED, PresentationDisposition.UNSATISFIABLE}
    ]

    def used(kind: BudgetKind, extractor) -> BudgetUsage:
        total = sum(extractor(p.item) for p in included)
        limit = profile.budget_limit(kind)
        exceeded = limit is not None and total > limit
        return BudgetUsage(
            kind=kind.value, used=total, limit=limit, exceeded=exceeded
        )

    # Latency is max, not sum (pipeline critical path style).
    latency_used = max((p.item.latency_ms for p in included), default=0)
    latency_limit = profile.budget_limit(BudgetKind.LATENCY)
    latency_usage = BudgetUsage(
        kind=BudgetKind.LATENCY.value,
        used=latency_used,
        limit=latency_limit,
        exceeded=latency_limit is not None and latency_used > latency_limit,
    )
    update_used = max((p.item.update_rate for p in included), default=0)
    update_limit = profile.budget_limit(BudgetKind.UPDATE_RATE)
    update_usage = BudgetUsage(
        kind=BudgetKind.UPDATE_RATE.value,
        used=update_used,
        limit=update_limit,
        exceeded=update_limit is not None and update_used > update_limit,
    )

    return (
        used(BudgetKind.ACTION_COUNT, lambda i: i.action_cost),
        used(BudgetKind.TEXT_DENSITY, lambda i: i.text_chars),
        update_usage,
        latency_usage,
        used(BudgetKind.ATTENTION, lambda i: i.effective_attention()),
        used(BudgetKind.FIELD_OF_VIEW, lambda i: i.field_of_view_share),
        used(BudgetKind.SAFE_AREA, lambda i: i.safe_area_share),
        used(BudgetKind.MEMORY, lambda i: i.memory_nodes),
    )


def _usage_exceeded(usage: Sequence[BudgetUsage]) -> tuple[BudgetUsage, ...]:
    return tuple(item for item in usage if item.exceeded)


def _placement_for_policy(
    item: ProjectionItem,
    *,
    tier: str,
    reason_suffix: str,
) -> _Placement:
    """Place an item given capability match tier.

    ``AdaptationPolicy.FALLBACK`` means "may fall back when primary is unavailable",
    not "always fall back". Primary matches preserve presentation.
    """

    mandatory = _item_is_mandatory(item)
    policy = item.adaptation_policy

    if tier == "primary":
        # Primary capabilities available: preserve. ADAPT/FALLBACK policies are
        # permissions to degrade under later budget pressure, not forced loss.
        if policy is AdaptationPolicy.SUMMARIZE:
            loss = make_loss(
                loss_id=f"loss:summarize:{item.item_id}",
                semantic_id=item.item_id,
                semantic_kind=item.semantic_kind,
                category=LossCategory.SUMMARIZED,
                reason=f"Summarized by declared policy ({reason_suffix})",
                mandatory=mandatory,
                adaptation_policy=AdaptationPolicy.SUMMARIZE,
            )
            return _Placement(item, PresentationDisposition.SUMMARIZED, loss)
        return _Placement(item, PresentationDisposition.PRESERVED, None)

    if tier == "alternative":
        loss = make_loss(
            loss_id=f"loss:degrade:{item.item_id}",
            semantic_id=item.item_id,
            semantic_kind=item.semantic_kind,
            category=LossCategory.DEGRADED,
            reason=(
                f"Primary capability unavailable; alternative used ({reason_suffix})"
            ),
            mandatory=mandatory,
            adaptation_policy=AdaptationPolicy.ADAPT,
        )
        return _Placement(item, PresentationDisposition.ADAPTED, loss)

    if tier == "fallback":
        fallback_ref = item.fallback_ref or (
            item.fallback_capability_ids[0]
            if item.fallback_capability_ids
            else "fallback:generic"
        )
        loss = make_loss(
            loss_id=f"loss:fallback:{item.item_id}",
            semantic_id=item.item_id,
            semantic_kind=item.semantic_kind,
            category=LossCategory.FALLBACK,
            reason=f"Projected via fallback ({reason_suffix})",
            mandatory=mandatory,
            adaptation_policy=AdaptationPolicy.FALLBACK,
            fallback_ref=fallback_ref,
        )
        return _Placement(item, PresentationDisposition.FALLBACK, loss)

    # No capability match.
    if mandatory:
        # Last-chance: declared fallback_ref with FALLBACK policy still needs a
        # capability hit above. Without it the core is unsatisfiable.
        loss = make_loss(
            loss_id=f"loss:unsat:{item.item_id}",
            semantic_id=item.item_id,
            semantic_kind=item.semantic_kind,
            category=LossCategory.UNSATISFIABLE,
            reason=(
                f"Mandatory {item.semantic_kind} {item.item_id!r} has no available "
                f"capability or fallback ({reason_suffix})"
            ),
            mandatory=True,
            adaptation_policy=policy,
            fallback_ref=item.fallback_ref,
        )
        return _Placement(item, PresentationDisposition.UNSATISFIABLE, loss)

    if policy is AdaptationPolicy.OMIT:
        loss = make_loss(
            loss_id=f"loss:omit:{item.item_id}",
            semantic_id=item.item_id,
            semantic_kind=item.semantic_kind,
            category=LossCategory.OMITTED,
            reason=f"Optional item omitted ({reason_suffix})",
            mandatory=False,
            adaptation_policy=AdaptationPolicy.OMIT,
        )
        return _Placement(item, PresentationDisposition.OMITTED, loss)

    loss = make_loss(
        loss_id=f"loss:unsupported:{item.item_id}",
        semantic_id=item.item_id,
        semantic_kind=item.semantic_kind,
        category=LossCategory.UNSUPPORTED,
        reason=f"Unsupported without matching capability ({reason_suffix})",
        mandatory=False,
        adaptation_policy=policy,
    )
    return _Placement(item, PresentationDisposition.OMITTED, loss)


def _try_omit_or_summarize_optional(
    placements: list[_Placement],
    exceeded: Sequence[BudgetUsage],
    policy: ProjectionPolicy,
) -> list[_Placement] | None:
    """Deterministically drop/summarize lowest-priority optional items to fit budgets."""

    if not exceeded:
        return placements

    # Prefer summarizing optional items first, then omitting if allowed.
    optionals = sorted(
        [
            p
            for p in placements
            if not _item_is_mandatory(p.item)
            and p.disposition
            not in {
                PresentationDisposition.OMITTED,
                PresentationDisposition.UNSATISFIABLE,
            }
        ],
        key=lambda p: (-p.item.priority, p.item.item_id),
    )
    if not optionals:
        return None

    working = list(placements)
    for candidate in optionals:
        idx = next(i for i, p in enumerate(working) if p.item.item_id == candidate.item.item_id)
        item = candidate.item
        if (
            policy.allow_summarize_optional
            and candidate.disposition is not PresentationDisposition.SUMMARIZED
            and item.adaptation_policy
            in {AdaptationPolicy.SUMMARIZE, AdaptationPolicy.ADAPT, AdaptationPolicy.PRESERVE}
        ):
            # Summarize reduces text/attention/FOV costs by half (integer floor).
            reduced = ProjectionItem(
                item_id=item.item_id,
                semantic_kind=item.semantic_kind,
                mandatory=item.mandatory,
                required_capability_ids=item.required_capability_ids,
                alternative_capability_ids=item.alternative_capability_ids,
                fallback_capability_ids=item.fallback_capability_ids,
                fallback_ref=item.fallback_ref,
                adaptation_policy=AdaptationPolicy.SUMMARIZE,
                action_cost=item.action_cost,
                text_chars=max(0, item.text_chars // 2),
                update_rate=item.update_rate,
                latency_ms=item.latency_ms,
                attention_cost=max(0, item.effective_attention() // 2),
                field_of_view_share=max(0, item.field_of_view_share // 2),
                safe_area_share=item.safe_area_share,
                memory_nodes=item.memory_nodes,
                priority=item.priority,
                component_id=item.component_id,
                label=item.label,
            )
            loss = make_loss(
                loss_id=f"loss:summarize-budget:{item.item_id}",
                semantic_id=item.item_id,
                semantic_kind=item.semantic_kind,
                category=LossCategory.SUMMARIZED,
                reason=(
                    "Summarized optional item to respect budgets: "
                    + ",".join(u.kind for u in exceeded)
                ),
                mandatory=False,
                adaptation_policy=AdaptationPolicy.SUMMARIZE,
                budget_kind=exceeded[0].kind if exceeded else "",
            )
            working[idx] = _Placement(
                reduced, PresentationDisposition.SUMMARIZED, loss
            )
            return working

        if policy.allow_omit_optional:
            loss = make_loss(
                loss_id=f"loss:omit-budget:{item.item_id}",
                semantic_id=item.item_id,
                semantic_kind=item.semantic_kind,
                category=LossCategory.OMITTED,
                reason=(
                    "Omitted optional item to respect budgets: "
                    + ",".join(u.kind for u in exceeded)
                ),
                mandatory=False,
                adaptation_policy=AdaptationPolicy.OMIT,
                budget_kind=exceeded[0].kind if exceeded else "",
            )
            working[idx] = _Placement(
                item, PresentationDisposition.OMITTED, loss
            )
            return working
    return None


def _force_mandatory_budget_resolution(
    placements: list[_Placement],
    exceeded: Sequence[BudgetUsage],
    policy: ProjectionPolicy,
) -> list[_Placement]:
    """When budgets still exceed after optional cuts, fallback or unsat mandatories."""

    working = list(placements)
    # Only apply to included mandatory items, highest priority first for fallback,
    # lowest priority first for unsatisfiable pressure.
    mandatories = [
        p
        for p in working
        if _item_is_mandatory(p.item)
        and p.disposition
        not in {
            PresentationDisposition.OMITTED,
            PresentationDisposition.UNSATISFIABLE,
        }
    ]
    if not mandatories:
        return working

    # Try fallback for mandatory items that declare fallback.
    for placement in sorted(
        mandatories, key=lambda p: (p.item.priority, p.item.item_id)
    ):
        item = placement.item
        if placement.disposition is PresentationDisposition.FALLBACK:
            continue
        if item.fallback_ref or item.fallback_capability_ids:
            if not policy.prefer_fallback_over_unsatisfiable:
                continue
            fallback_ref = item.fallback_ref or item.fallback_capability_ids[0]
            # Fallback reduces FOV/text costs.
            reduced = ProjectionItem(
                item_id=item.item_id,
                semantic_kind=item.semantic_kind,
                mandatory=True,
                required_capability_ids=item.required_capability_ids,
                alternative_capability_ids=item.alternative_capability_ids,
                fallback_capability_ids=item.fallback_capability_ids,
                fallback_ref=fallback_ref,
                adaptation_policy=AdaptationPolicy.FALLBACK,
                action_cost=max(1, item.action_cost // 2) if item.action_cost else 0,
                text_chars=max(0, item.text_chars // 3),
                update_rate=item.update_rate,
                latency_ms=item.latency_ms,
                attention_cost=max(1, item.effective_attention() // 2),
                field_of_view_share=max(0, item.field_of_view_share // 3),
                safe_area_share=max(0, item.safe_area_share // 2),
                memory_nodes=max(1, item.memory_nodes // 2),
                priority=item.priority,
                component_id=item.component_id,
                label=item.label,
            )
            loss = make_loss(
                loss_id=f"loss:fallback-budget:{item.item_id}",
                semantic_id=item.item_id,
                semantic_kind=item.semantic_kind,
                category=LossCategory.FALLBACK,
                reason=(
                    "Mandatory semantic projected via fallback to respect budgets: "
                    + ",".join(u.kind for u in exceeded)
                ),
                mandatory=True,
                adaptation_policy=AdaptationPolicy.FALLBACK,
                fallback_ref=fallback_ref,
                budget_kind=exceeded[0].kind if exceeded else "",
            )
            idx = next(
                i for i, p in enumerate(working) if p.item.item_id == item.item_id
            )
            working[idx] = _Placement(
                reduced, PresentationDisposition.FALLBACK, loss
            )
            return working

    # No fallback available: mark lowest-priority mandatory as unsatisfiable
    # (explicit failure — never silent omit).
    victim = sorted(
        mandatories, key=lambda p: (-p.item.priority, p.item.item_id)
    )[0]
    item = victim.item
    loss = make_loss(
        loss_id=f"loss:unsat-budget:{item.item_id}",
        semantic_id=item.item_id,
        semantic_kind=item.semantic_kind,
        category=LossCategory.UNSATISFIABLE,
        reason=(
            "Mandatory semantic cannot fit remaining budgets without silent omit: "
            + ",".join(u.kind for u in exceeded)
        ),
        mandatory=True,
        adaptation_policy=item.adaptation_policy,
        budget_kind=exceeded[0].kind if exceeded else "",
        fallback_ref=item.fallback_ref,
    )
    idx = next(i for i, p in enumerate(working) if p.item.item_id == item.item_id)
    working[idx] = _Placement(item, PresentationDisposition.UNSATISFIABLE, loss)
    return working


def _score_placements(placements: Sequence[_Placement]) -> int:
    score = 0
    for placement in placements:
        if placement.loss is not None:
            from .loss import loss_score

            score += loss_score(
                placement.loss.category, mandatory=placement.loss.mandatory
            )
        elif placement.disposition is PresentationDisposition.PRESERVED:
            score += 0
        else:
            score += 1
    return score


def _status_for(
    placements: Sequence[_Placement],
    negotiation: CapabilityNegotiationResult,
    bounds: SolverBoundsReceipt,
) -> ProjectionStatus:
    if bounds.bound_exceeded:
        return ProjectionStatus.BOUND_EXCEEDED
    if any(
        p.disposition is PresentationDisposition.UNSATISFIABLE for p in placements
    ) or negotiation.status is NegotiationStatus.UNSATISFIABLE:
        return ProjectionStatus.UNSATISFIABLE
    if any(
        p.disposition is PresentationDisposition.FALLBACK for p in placements
    ) or negotiation.status is NegotiationStatus.FALLBACK:
        return ProjectionStatus.FALLBACK
    if any(
        p.disposition
        in {
            PresentationDisposition.ADAPTED,
            PresentationDisposition.SUMMARIZED,
            PresentationDisposition.OMITTED,
        }
        for p in placements
    ) or negotiation.status is NegotiationStatus.DEGRADED:
        return ProjectionStatus.DEGRADED
    return ProjectionStatus.SATISFIED


def _nodes_from_placements(placements: Sequence[_Placement]) -> tuple[ProjectedNode, ...]:
    # Stable order: preserved/adapted/summarized/fallback first by priority, then id.
    def sort_key(p: _Placement) -> tuple[int, int, str]:
        rank = {
            PresentationDisposition.PRESERVED: 0,
            PresentationDisposition.ADAPTED: 1,
            PresentationDisposition.SUMMARIZED: 2,
            PresentationDisposition.FALLBACK: 3,
            PresentationDisposition.OMITTED: 4,
            PresentationDisposition.UNSATISFIABLE: 5,
        }[p.disposition]
        return (rank, p.item.priority, p.item.item_id)

    ordered = sorted(placements, key=sort_key)
    nodes: list[ProjectedNode] = []
    for index, placement in enumerate(ordered):
        nodes.append(
            ProjectedNode(
                item_id=placement.item.item_id,
                semantic_kind=placement.item.semantic_kind,
                disposition=placement.disposition,
                mandatory=_item_is_mandatory(placement.item),
                order=index,
                fallback_ref=placement.item.fallback_ref,
                component_id=placement.item.component_id,
                label=placement.item.label,
            )
        )
    return tuple(nodes)


def solve_projection(
    problem: ProjectionProblem,
    profile: UIDeviceProfile,
    policy: ProjectionPolicy | None = None,
) -> UIProjectionArtifact:
    """Solve a bounded projection problem against a device profile.

    Returns a deterministic :class:`UIProjectionArtifact` with negotiation,
    budget usage, loss receipts, and explicit unsatisfiable/fallback outcomes.
    """

    problem = problem.validate()
    profile = validate_device_profile(profile)
    policy = (policy or ProjectionPolicy()).validate()
    state = _SolveState()
    started = state.started_monotonic
    exceeded_bounds: list[str] = []

    # 1) Capability negotiation (document-level + per-item derived).
    requirements = list(problem.capability_requirements)
    for item in problem.items:
        if item.required_capability_ids:
            requirements.append(
                CapabilityRequirement(
                    requirement_id=f"req:item:{item.item_id}",
                    capability_ids=item.required_capability_ids,
                    essential=_item_is_mandatory(item),
                    alternative_capability_ids=item.alternative_capability_ids,
                    fallback_capability_ids=item.fallback_capability_ids,
                )
            )
    # De-dupe by requirement_id, keep first.
    deduped: list[CapabilityRequirement] = []
    seen_req: set[str] = set()
    for requirement in sorted(requirements, key=lambda r: r.requirement_id):
        if requirement.requirement_id in seen_req:
            continue
        seen_req.add(requirement.requirement_id)
        deduped.append(requirement)

    try:
        state.tick(profile)
        negotiation = negotiate_capabilities(profile, deduped)
    except _BoundExceeded as exc:
        exceeded_bounds.append(exc.bound_name)
        negotiation = CapabilityNegotiationResult(
            profile_id=profile.profile_id,
            status=NegotiationStatus.UNSATISFIABLE,
            satisfied_requirement_ids=(),
            degraded_requirement_ids=(),
            fallback_requirement_ids=(),
            unsatisfiable_requirement_ids=tuple(
                r.requirement_id for r in deduped if r.essential
            ),
            available_capability_ids=tuple(sorted(profile.available_capability_ids)),
            used_capability_ids=(),
            notes=(f"negotiation aborted: {exc.bound_name}",),
        )

    available = set(negotiation.available_capability_ids)

    # 2) Initial placement from capability tiers + adaptation policies.
    placements: list[_Placement] = []
    try:
        for item in sorted(
            problem.items, key=lambda i: (i.priority, i.item_id)
        ):
            state.tick(profile)
            tier, _hits = _capability_available(item, available)
            placements.append(
                _placement_for_policy(
                    item,
                    tier=tier,
                    reason_suffix=f"tier={tier}",
                )
            )
    except _BoundExceeded as exc:
        exceeded_bounds.append(exc.bound_name)

    # Memory bound on projected node count.
    memory_nodes_used = sum(
        p.item.memory_nodes
        for p in placements
        if p.disposition
        not in {
            PresentationDisposition.OMITTED,
            PresentationDisposition.UNSATISFIABLE,
        }
    )
    if memory_nodes_used > profile.max_memory_nodes:
        exceeded_bounds.append("max_memory_nodes")

    # 3) Budget repair loop (deterministic; bounded by max_variants / steps).
    variant_scores: list[int] = []
    selected = list(placements)
    try:
        for _variant in range(policy.max_variants):
            state.tick(profile)
            usage = _measure_usage(selected, profile)
            exceeded = _usage_exceeded(usage)
            variant_scores.append(_score_placements(selected))
            if not exceeded:
                break
            repaired = _try_omit_or_summarize_optional(selected, exceeded, policy)
            if repaired is not None:
                selected = repaired
                continue
            selected = _force_mandatory_budget_resolution(selected, exceeded, policy)
            # Loop continues to re-measure; unsatisfiable removes cost.
        else:
            # max_variants exhausted with remaining budget pressure.
            usage = _measure_usage(selected, profile)
            if _usage_exceeded(usage):
                # Force unsatisfiable on remaining over-budget mandatories.
                still = _usage_exceeded(usage)
                selected = _force_mandatory_budget_resolution(
                    selected, still, policy
                )
    except _BoundExceeded as exc:
        exceeded_bounds.append(exc.bound_name)

    # 4) Mandatory silent-omission gate.
    required_map = {
        p.item.item_id: p.item.semantic_kind
        for p in selected
        if _item_is_mandatory(p.item)
    }
    preserved_ids = [
        p.item.item_id
        for p in selected
        if p.disposition
        in {
            PresentationDisposition.PRESERVED,
            PresentationDisposition.ADAPTED,
            PresentationDisposition.SUMMARIZED,
            PresentationDisposition.FALLBACK,
        }
    ]
    losses = [p.loss for p in selected if p.loss is not None]
    # Also add budget-exceeded receipts for remaining exceeded budgets with
    # unsatisfiable status.
    final_usage = _measure_usage(selected, profile)
    for budget in _usage_exceeded(final_usage):
        losses.append(
            make_loss(
                loss_id=f"loss:budget:{budget.kind}",
                semantic_id=f"budget:{budget.kind}",
                semantic_kind="budget",
                category=LossCategory.BUDGET_EXCEEDED,
                reason=(
                    f"Budget {budget.kind} used {budget.used} exceeds limit "
                    f"{budget.limit}"
                ),
                mandatory=False,
                budget_kind=budget.kind,
            )
        )

    assert_no_silent_mandatory_omission(required_map, losses, preserved_ids)

    loss_report = build_loss_report(
        report_id=f"loss-report:{problem.problem_id}:{profile.profile_id}",
        losses=losses,
    )

    elapsed_ms = int((time.monotonic() - started) * 1000)
    # Recompute memory after final placement.
    memory_nodes_used = sum(
        p.item.memory_nodes
        for p in selected
        if p.disposition
        not in {
            PresentationDisposition.OMITTED,
            PresentationDisposition.UNSATISFIABLE,
        }
    )
    if memory_nodes_used > profile.max_memory_nodes and "max_memory_nodes" not in exceeded_bounds:
        exceeded_bounds.append("max_memory_nodes")

    bounds = SolverBoundsReceipt(
        max_solve_ms=profile.max_solve_ms,
        max_solve_steps=profile.max_solve_steps,
        max_memory_nodes=profile.max_memory_nodes,
        elapsed_ms=elapsed_ms,
        steps_used=state.steps,
        memory_nodes_used=memory_nodes_used,
        bound_exceeded=bool(exceeded_bounds),
        exceeded_bounds=tuple(sorted(set(exceeded_bounds))),
    )

    nodes = _nodes_from_placements(selected)
    status = _status_for(selected, negotiation, bounds)
    # Prefer lowest score variant index (we only keep the repaired path score trail).
    selected_index = 0
    if variant_scores:
        selected_index = min(
            range(len(variant_scores)), key=lambda i: (variant_scores[i], i)
        )

    artifact = UIProjectionArtifact(
        artifact_id=f"proj:{problem.problem_id}:{profile.profile_id}",
        status=status,
        profile_id=profile.profile_id,
        problem_id=problem.problem_id,
        nodes=nodes,
        loss_report=loss_report,
        negotiation=negotiation,
        budget_usage=final_usage,
        bounds=bounds,
        ranked_variant_scores=tuple(variant_scores),
        selected_variant_index=selected_index,
        document_id=problem.document_id,
        policy_id=policy.policy_id,
    )
    return artifact.validate()


def projection_problem_from_document(
    document: UIIRDocument | Mapping[str, Any],
    *,
    problem_id: str = "",
) -> ProjectionProblem:
    """Derive a :class:`ProjectionProblem` from a UIIR document or mapping.

    Extracts feedback, accessibility, modality, and lightweight component
    actions as projection items. This is intentionally conservative: target
    adapters (web/mobile/glasses/voice) refine presentation later.
    """

    if isinstance(document, UIIRDocument):
        payload = document.to_dict()
        doc_id = document.document_id
    elif isinstance(document, Mapping):
        payload = dict(document)
        doc_id = str(payload.get("document_id") or "")
    else:
        raise UIIRValidationError(
            "projection_problem_from_document expects UIIRDocument or mapping"
        )

    items: list[ProjectionItem] = []
    requirements: list[CapabilityRequirement] = []

    for component in payload.get("components") or ():
        if not isinstance(component, Mapping):
            continue
        component_id = str(component.get("component_id") or "")
        if not component_id:
            continue
        role = str(component.get("role") or "component")
        # Treat interactive components as optional actions unless role is button-like.
        mandatory = role in {"button", "aria:button", "link", "aria:link"} or bool(
            component.get("program_binding_ids")
        )
        items.append(
            ProjectionItem(
                item_id=f"action:{component_id}",
                semantic_kind=MandatorySemanticKind.ACTION.value
                if mandatory
                else "component",
                mandatory=mandatory,
                required_capability_ids=("display",),
                alternative_capability_ids=("spatial_display", "mobile_companion"),
                fallback_capability_ids=("audio", "speech_output", "agent_structured"),
                fallback_ref=f"fallback:audio:{component_id}",
                adaptation_policy=(
                    AdaptationPolicy.FALLBACK if mandatory else AdaptationPolicy.ADAPT
                ),
                action_cost=1 if mandatory else 0,
                text_chars=max(16, len(str(component.get("purpose") or role))),
                attention_cost=5 if mandatory else 1,
                field_of_view_share=10 if mandatory else 4,
                safe_area_share=5,
                component_id=component_id,
                label=str(component.get("purpose") or component_id),
                priority=50 if mandatory else 200,
            )
        )

    for feedback in payload.get("feedback_contracts") or ():
        if not isinstance(feedback, Mapping):
            continue
        feedback_id = str(feedback.get("feedback_id") or "")
        if not feedback_id:
            continue
        items.append(
            ProjectionItem(
                item_id=f"feedback:{feedback_id}",
                semantic_kind=MandatorySemanticKind.FEEDBACK.value,
                mandatory=True,
                required_capability_ids=("display",),
                alternative_capability_ids=("audio", "speech_output", "haptic"),
                fallback_capability_ids=("notification", "agent_structured"),
                fallback_ref=f"fallback:feedback:{feedback_id}",
                adaptation_policy=AdaptationPolicy.FALLBACK,
                action_cost=0,
                text_chars=40,
                attention_cost=3,
                field_of_view_share=5,
                component_id=str(feedback.get("component_id") or ""),
                label=str(feedback.get("channel") or feedback_id),
                priority=20,
            )
        )

    for accessibility in payload.get("accessibility") or ():
        if not isinstance(accessibility, Mapping):
            continue
        accessibility_id = str(accessibility.get("accessibility_id") or "")
        if not accessibility_id:
            continue
        items.append(
            ProjectionItem(
                item_id=f"a11y:{accessibility_id}",
                semantic_kind=MandatorySemanticKind.ACCESSIBILITY.value,
                mandatory=True,
                required_capability_ids=("display",),
                alternative_capability_ids=("audio", "speech_output", "haptic"),
                fallback_capability_ids=("agent_structured", "fallback"),
                fallback_ref=f"fallback:a11y:{accessibility_id}",
                adaptation_policy=AdaptationPolicy.FALLBACK,
                action_cost=0,
                text_chars=24,
                attention_cost=2,
                field_of_view_share=2,
                component_id=str(accessibility.get("component_id") or ""),
                label=str(accessibility.get("role") or accessibility_id),
                priority=10,
            )
        )

    for requirement in payload.get("input_modality_requirements") or ():
        if not isinstance(requirement, Mapping):
            continue
        req_id = str(requirement.get("requirement_id") or "")
        caps = tuple(str(c) for c in (requirement.get("capability_ids") or ()))
        if not req_id or not caps:
            continue
        requirements.append(
            CapabilityRequirement(
                requirement_id=req_id,
                capability_ids=caps,
                essential=bool(requirement.get("essential", True)),
                direction="input",
            )
        )
    for requirement in payload.get("output_modality_requirements") or ():
        if not isinstance(requirement, Mapping):
            continue
        req_id = str(requirement.get("requirement_id") or "")
        caps = tuple(str(c) for c in (requirement.get("capability_ids") or ()))
        if not req_id or not caps:
            continue
        requirements.append(
            CapabilityRequirement(
                requirement_id=req_id,
                capability_ids=caps,
                essential=bool(requirement.get("essential", True)),
                direction="output",
            )
        )

    if not items:
        # Minimal placeholder so empty documents fail closed with explicit problem.
        raise UIIRValidationError(
            "document produced no projection items; refuse empty projection"
        )

    return ProjectionProblem(
        problem_id=problem_id or f"problem:{doc_id or 'anonymous'}",
        items=tuple(items),
        document_id=doc_id,
        capability_requirements=tuple(requirements),
    ).validate()


def project_ui_ir(
    document: UIIRDocument | Mapping[str, Any] | ProjectionProblem,
    device_profile: UIDeviceProfile,
    policy: ProjectionPolicy | None = None,
) -> UIProjectionArtifact:
    """Project a UI/UX IR document (or problem) under a device capability profile.

    Public entry aligned with the architecture contract
    ``project_ui_ir(document, device_profile, policy) -> UIProjectionArtifact``.
    """

    if isinstance(document, ProjectionProblem):
        problem = document
    else:
        problem = projection_problem_from_document(document)
    return solve_projection(problem, device_profile, policy)


class UIProjectionSolver:
    """Reference projection solver implementing UIProjectionSolver@1."""

    interface: str = UI_PROJECTION_SOLVER_INTERFACE

    def solve(
        self,
        problem: ProjectionProblem,
        profile: UIDeviceProfile,
        policy: ProjectionPolicy | None = None,
    ) -> UIProjectionArtifact:
        return solve_projection(problem, profile, policy)

    def project(
        self,
        document: UIIRDocument | Mapping[str, Any] | ProjectionProblem,
        device_profile: UIDeviceProfile,
        policy: ProjectionPolicy | None = None,
    ) -> UIProjectionArtifact:
        return project_ui_ir(document, device_profile, policy)


__all__ = [
    "BudgetUsage",
    "PresentationDisposition",
    "ProjectedNode",
    "ProjectionItem",
    "ProjectionPolicy",
    "ProjectionProblem",
    "ProjectionStatus",
    "SolverBoundsReceipt",
    "UI_PROJECTION_ARTIFACT_INTERFACE",
    "UI_PROJECTION_ARTIFACT_SCHEMA_VERSION",
    "UI_PROJECTION_POLICY_SCHEMA_VERSION",
    "UI_PROJECTION_SOLVER_INTERFACE",
    "UIProjectionArtifact",
    "UIProjectionSolver",
    "project_ui_ir",
    "projection_problem_from_document",
    "solve_projection",
]
