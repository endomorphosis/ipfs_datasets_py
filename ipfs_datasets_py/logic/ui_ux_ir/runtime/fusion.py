"""Deterministic multimodal fusion and arbitration (UIR-053).

UIMultimodalFusion@1 correlates simultaneous canonical interaction events,
deduplicates equivalent physical/logical actions, prioritizes live human input
over agent proposals, rejects late/stale events against newer state, and
requires clarification for inconsistent high-impact signals.

Fusion may select or clarify a candidate but never authorizes or invokes it.
Human interaction priority never bypasses runtime policy mediation.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Any, Final, Mapping, Sequence

from ..schema import UIIRValidationError
from .events import (
    CanonicalInteractionEvent,
    EventKind,
    EventProvenance,
    assert_not_authority,
    validate_event,
)

UI_MULTIMODAL_FUSION_INTERFACE: Final = "UIMultimodalFusion@1"
FUSION_ADAPTER_ID: Final = "runtime.fusion@1"

# Default temporal gates (milliseconds).
DEFAULT_CORRELATION_WINDOW_MS: Final = 250
DEFAULT_MAX_EVENT_AGE_MS: Final = 30_000
DEFAULT_CONFIDENCE_FLOOR: Final = 0.55

# Provenance ranking for deterministic arbitration (higher wins).
# Live human outranks agent proposals; system/synthetic are observational.
_PROVENANCE_RANK: Final[Mapping[EventProvenance, int]] = MappingProxyType(
    {
        EventProvenance.HUMAN: 40,
        EventProvenance.SYSTEM: 20,
        EventProvenance.SYNTHETIC: 10,
        EventProvenance.AGENT: 5,
        EventProvenance.UNKNOWN: 0,
    }
)

_HIGH_IMPACT_RISKS: Final = frozenset({"high", "critical", "destructive"})
_ACTIONABLE_KINDS: Final = frozenset(
    {
        EventKind.ACTIVATE,
        EventKind.SELECT,
        EventKind.CONFIRM,
        EventKind.NAVIGATE,
        EventKind.INPUT_VALUE,
        EventKind.CANCEL,
    }
)


class FusionOutcome(str, Enum):
    """Closed set of fusion decisions (selection is never authorization)."""

    EMPTY = "empty"
    SELECT = "select"
    DEDUPLICATE = "deduplicate"
    CLARIFY = "clarify"
    CANCEL = "cancel"
    REJECT_STALE = "reject_stale"
    SUPPRESS = "suppress"


@dataclass(frozen=True, slots=True)
class FusionConfig:
    """Declared correlation and freshness windows for order-stable fusion."""

    correlation_window_ms: int = DEFAULT_CORRELATION_WINDOW_MS
    max_event_age_ms: int = DEFAULT_MAX_EVENT_AGE_MS
    confidence_floor: float = DEFAULT_CONFIDENCE_FLOOR

    def __post_init__(self) -> None:
        if self.correlation_window_ms < 0:
            raise UIIRValidationError("correlation_window_ms must be non-negative")
        if self.max_event_age_ms < 0:
            raise UIIRValidationError("max_event_age_ms must be non-negative")
        if not (0.0 <= float(self.confidence_floor) <= 1.0):
            raise UIIRValidationError("confidence_floor must be in [0, 1]")


@dataclass(frozen=True, slots=True)
class FusionExplanation:
    """Deterministic, privacy-safe explanation of a fusion decision."""

    outcome: FusionOutcome
    reasons: tuple[str, ...]
    correlated_event_ids: tuple[str, ...]
    selected_event_id: str | None = None
    suppressed_event_ids: tuple[str, ...] = ()
    stale_event_ids: tuple[str, ...] = ()
    human_priority_applied: bool = False
    policy_bypass_allowed: bool = False
    correlation_window_ms: int = DEFAULT_CORRELATION_WINDOW_MS
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "correlated_event_ids": list(self.correlated_event_ids),
            "correlation_window_ms": self.correlation_window_ms,
            "detail": self.detail,
            "human_priority_applied": self.human_priority_applied,
            "outcome": self.outcome.value,
            "policy_bypass_allowed": self.policy_bypass_allowed,
            "reasons": list(self.reasons),
            "selected_event_id": self.selected_event_id,
            "stale_event_ids": list(self.stale_event_ids),
            "suppressed_event_ids": list(self.suppressed_event_ids),
        }


@dataclass(frozen=True, slots=True)
class FusionResult:
    """Bounded fusion receipt. Never an authorization or invocation grant."""

    selected: CanonicalInteractionEvent | None
    outcome: FusionOutcome
    requires_clarification: bool
    requires_policy_mediation: bool
    explanation: FusionExplanation
    candidates: tuple[CanonicalInteractionEvent, ...] = ()
    interface: str = UI_MULTIMODAL_FUSION_INTERFACE

    @property
    def authorizes_invocation(self) -> bool:
        """Fusion never authorizes; mediator owns invocation admission."""

        return False

    def to_dict(self) -> dict[str, Any]:
        return {
            "authorizes_invocation": self.authorizes_invocation,
            "candidates": [e.event_id for e in self.candidates],
            "explanation": self.explanation.to_dict(),
            "interface": self.interface,
            "outcome": self.outcome.value,
            "requires_clarification": self.requires_clarification,
            "requires_policy_mediation": self.requires_policy_mediation,
            "selected_event_id": None if self.selected is None else self.selected.event_id,
        }


def _sort_key(event: CanonicalInteractionEvent) -> tuple[int, int, str]:
    """Canonical order for order-stable fusion under a correlation window."""

    return (int(event.timestamp_ms), int(event.sequence), str(event.event_id))


def _confidence(event: CanonicalInteractionEvent) -> float:
    if event.confidence is None:
        return 1.0
    return float(event.confidence)


def _risk_class(event: CanonicalInteractionEvent) -> str:
    payload = event.raw_payload or {}
    raw = (
        payload.get("risk_class")
        or payload.get("risk_hint")
        or payload.get("risk")
        or "low"
    )
    return str(raw).strip().lower() or "low"


def _is_high_impact(event: CanonicalInteractionEvent) -> bool:
    if _risk_class(event) in _HIGH_IMPACT_RISKS:
        return True
    # Confirm/activate without explicit low risk still treated carefully when
    # the payload marks destructive intent tokens.
    payload = event.raw_payload or {}
    intent = str(
        payload.get("intent")
        or payload.get("intent_id")
        or payload.get("primary_text")
        or ""
    ).lower()
    destructive_markers = (
        "delete",
        "destroy",
        "transfer",
        "purchase",
        "send_funds",
        "wipe",
        "format",
    )
    return any(m in intent for m in destructive_markers)


def _logical_action_key(event: CanonicalInteractionEvent) -> str:
    """Identity of a physical/logical action for deduplication."""

    # Cancel is its own action class so it can supersede activations.
    if event.kind is EventKind.CANCEL:
        return f"cancel|{event.target_component_id}"
    return f"{event.kind.value}|{event.target_component_id}"


def _provenance_rank(event: CanonicalInteractionEvent) -> int:
    return int(_PROVENANCE_RANK.get(event.provenance, 0))


def _pick_best(events: Sequence[CanonicalInteractionEvent]) -> CanonicalInteractionEvent:
    """Deterministic winner among candidates (order-stable tie-breakers)."""

    return max(
        events,
        key=lambda e: (
            _provenance_rank(e),
            _confidence(e),
            int(e.timestamp_ms),
            int(e.sequence),
            # Prefer lexicographically smaller event_id when ranks tie.
            tuple(-ord(c) for c in e.event_id),
        ),
    )


def _is_stale(
    event: CanonicalInteractionEvent,
    *,
    now_ms: int | None,
    max_event_age_ms: int,
    state_watermark_ms: int | None,
    state_sequence: int | None,
) -> tuple[bool, str]:
    if now_ms is not None:
        age = int(now_ms) - int(event.timestamp_ms)
        if age > max_event_age_ms:
            return True, f"age_ms={age}>{max_event_age_ms}"
        if age < 0 and abs(age) > max_event_age_ms:
            # Far-future timestamps treated as inconsistent/stale for safety.
            return True, f"future_skew_ms={abs(age)}"
    if state_watermark_ms is not None and int(event.timestamp_ms) < int(
        state_watermark_ms
    ):
        return (
            True,
            f"timestamp_ms={event.timestamp_ms}<state_watermark_ms={state_watermark_ms}",
        )
    if state_sequence is not None and int(event.sequence) < int(state_sequence):
        return (
            True,
            f"sequence={event.sequence}<state_sequence={state_sequence}",
        )
    return False, ""


def _cluster_by_window(
    events: Sequence[CanonicalInteractionEvent],
    *,
    window_ms: int,
) -> list[list[CanonicalInteractionEvent]]:
    """Group events whose timestamps fall within a declared correlation window.

    Clustering is order-stable: input is assumed pre-sorted by ``_sort_key``.
    Two events correlate when the span of the cluster stays within ``window_ms``.
    """

    if not events:
        return []
    clusters: list[list[CanonicalInteractionEvent]] = []
    current: list[CanonicalInteractionEvent] = [events[0]]
    cluster_start = int(events[0].timestamp_ms)
    for event in events[1:]:
        ts = int(event.timestamp_ms)
        if ts - cluster_start <= window_ms:
            current.append(event)
        else:
            clusters.append(current)
            current = [event]
            cluster_start = ts
    clusters.append(current)
    return clusters


def _equivalent_action(
    a: CanonicalInteractionEvent, b: CanonicalInteractionEvent
) -> bool:
    """True when two events represent the same physical/logical action."""

    if a.kind is EventKind.CANCEL and b.kind is EventKind.CANCEL:
        # Cancels on the same target (or empty target) collapse.
        return a.target_component_id == b.target_component_id or (
            not a.target_component_id or not b.target_component_id
        )
    return (
        a.kind is b.kind
        and a.target_component_id == b.target_component_id
        and a.kind in _ACTIONABLE_KINDS
    )


def _arbitrate_cluster(
    cluster: Sequence[CanonicalInteractionEvent],
    *,
    config: FusionConfig,
) -> FusionResult:
    """Resolve one correlated cluster into a single decision."""

    ordered = tuple(sorted(cluster, key=_sort_key))
    ids = tuple(e.event_id for e in ordered)
    reasons: list[str] = [
        f"correlation_window_ms={config.correlation_window_ms}",
        f"cluster_size={len(ordered)}",
    ]

    # Cancel supersedes competing activations in the same window (safety).
    cancels = [e for e in ordered if e.kind is EventKind.CANCEL]
    if cancels:
        winner = _pick_best(cancels)
        suppressed = tuple(
            e.event_id for e in ordered if e.event_id != winner.event_id
        )
        human_priority = any(
            e.provenance is EventProvenance.HUMAN for e in cancels
        ) and any(
            e.provenance is EventProvenance.AGENT for e in ordered
        )
        reasons.append("cancel_supersedes_competing_actions")
        if human_priority:
            reasons.append("human_priority_applied")
            reasons.append("human_priority_does_not_bypass_policy")
        explanation = FusionExplanation(
            outcome=FusionOutcome.CANCEL,
            reasons=tuple(reasons),
            correlated_event_ids=ids,
            selected_event_id=winner.event_id,
            suppressed_event_ids=suppressed,
            human_priority_applied=human_priority,
            policy_bypass_allowed=False,
            correlation_window_ms=config.correlation_window_ms,
            detail=(
                "Cancel selected within correlation window; "
                "policy mediation still required"
            ),
        )
        return FusionResult(
            selected=winner,
            outcome=FusionOutcome.CANCEL,
            requires_clarification=False,
            requires_policy_mediation=True,
            explanation=explanation,
            candidates=ordered,
        )

    # Low-confidence candidates force clarification before selection.
    low_conf = [
        e
        for e in ordered
        if e.confidence is not None and float(e.confidence) < config.confidence_floor
    ]
    if low_conf and all(
        e.confidence is not None and float(e.confidence) < config.confidence_floor
        for e in ordered
    ):
        reasons.append(
            f"all_candidates_below_confidence_floor:{config.confidence_floor}"
        )
        explanation = FusionExplanation(
            outcome=FusionOutcome.CLARIFY,
            reasons=tuple(reasons),
            correlated_event_ids=ids,
            policy_bypass_allowed=False,
            correlation_window_ms=config.correlation_window_ms,
            detail="Low-confidence multimodal cluster requires clarification",
        )
        return FusionResult(
            selected=None,
            outcome=FusionOutcome.CLARIFY,
            requires_clarification=True,
            requires_policy_mediation=True,
            explanation=explanation,
            candidates=ordered,
        )

    # Partition by logical action identity.
    by_action: dict[str, list[CanonicalInteractionEvent]] = {}
    for event in ordered:
        key = _logical_action_key(event)
        by_action.setdefault(key, []).append(event)

    action_keys = sorted(by_action.keys())
    high_impact_events = [e for e in ordered if _is_high_impact(e)]

    # Inconsistent high-impact targets/kinds within the window → clarify.
    if len(action_keys) > 1:
        targets = {e.target_component_id for e in ordered}
        if high_impact_events or (
            len(targets) > 1
            and any(
                e.kind in {EventKind.ACTIVATE, EventKind.CONFIRM, EventKind.SELECT}
                for e in ordered
            )
        ):
            reasons.append("inconsistent_high_impact_or_conflicting_targets")
            reasons.append(f"action_keys={','.join(action_keys)}")
            explanation = FusionExplanation(
                outcome=FusionOutcome.CLARIFY,
                reasons=tuple(reasons),
                correlated_event_ids=ids,
                policy_bypass_allowed=False,
                correlation_window_ms=config.correlation_window_ms,
                detail=(
                    "Correlated events disagree on target/kind under high impact; "
                    "clarification required (no auto-selection)"
                ),
            )
            return FusionResult(
                selected=None,
                outcome=FusionOutcome.CLARIFY,
                requires_clarification=True,
                requires_policy_mediation=True,
                explanation=explanation,
                candidates=ordered,
            )
        # Non-high-impact multi-action cluster: prefer human actionable, else best.
        # Still only emit one selected action (at most once).
        reasons.append("multi_action_cluster_selecting_single_winner")

    # Flatten equivalent groups: pick one winner overall, suppress the rest.
    # Prefer groups with human provenance when present.
    human_events = [e for e in ordered if e.provenance is EventProvenance.HUMAN]
    agent_events = [e for e in ordered if e.provenance is EventProvenance.AGENT]
    human_priority_applied = bool(human_events) and bool(agent_events)

    if human_priority_applied:
        # Live human priority over agent proposals for selection only.
        pool = human_events
        reasons.append("human_priority_over_agent_proposals")
    else:
        pool = list(ordered)

    # Within pool, collapse equivalent actions first.
    unique_actions: list[CanonicalInteractionEvent] = []
    seen_keys: set[str] = set()
    for event in sorted(pool, key=_sort_key):
        key = _logical_action_key(event)
        if key in seen_keys:
            continue
        group = [e for e in pool if _logical_action_key(e) == key]
        unique_actions.append(_pick_best(group))
        seen_keys.add(key)

    if len(unique_actions) > 1 and high_impact_events:
        reasons.append("multiple_distinct_actions_high_impact")
        explanation = FusionExplanation(
            outcome=FusionOutcome.CLARIFY,
            reasons=tuple(reasons),
            correlated_event_ids=ids,
            human_priority_applied=human_priority_applied,
            policy_bypass_allowed=False,
            correlation_window_ms=config.correlation_window_ms,
            detail="Distinct high-impact actions in one window require clarification",
        )
        return FusionResult(
            selected=None,
            outcome=FusionOutcome.CLARIFY,
            requires_clarification=True,
            requires_policy_mediation=True,
            explanation=explanation,
            candidates=ordered,
        )

    winner = _pick_best(unique_actions if unique_actions else ordered)
    suppressed = tuple(e.event_id for e in ordered if e.event_id != winner.event_id)

    # Detect pure duplicate equivalence (same logical action, multi-modality).
    all_equivalent = all(_equivalent_action(winner, e) for e in ordered)
    if all_equivalent and len(ordered) > 1:
        outcome = FusionOutcome.DEDUPLICATE
        reasons.append("equivalent_actions_deduplicated")
        reasons.append("one_physical_logical_action_at_most_once")
        detail = (
            "Equivalent multimodal signals for one logical action collapsed to "
            "a single candidate; invocation still requires policy mediation"
        )
    elif human_priority_applied:
        outcome = FusionOutcome.SELECT
        reasons.append("agent_proposals_suppressed")
        detail = (
            "Live human input selected over agent proposal; "
            "human priority does not bypass runtime policy"
        )
    else:
        outcome = FusionOutcome.SELECT
        detail = "Single fused candidate selected for policy mediation"

    if human_priority_applied:
        reasons.append("human_priority_does_not_bypass_policy")

    # Always require policy mediation; never authorize.
    reasons.append("policy_mediation_required")
    reasons.append("fusion_does_not_authorize_invocation")

    explanation = FusionExplanation(
        outcome=outcome,
        reasons=tuple(reasons),
        correlated_event_ids=ids,
        selected_event_id=winner.event_id,
        suppressed_event_ids=suppressed,
        human_priority_applied=human_priority_applied,
        policy_bypass_allowed=False,
        correlation_window_ms=config.correlation_window_ms,
        detail=detail,
    )
    return FusionResult(
        selected=winner,
        outcome=outcome,
        requires_clarification=False,
        requires_policy_mediation=True,
        explanation=explanation,
        candidates=ordered,
    )


def fuse_interactions(
    events: Sequence[CanonicalInteractionEvent],
    *,
    now_ms: int | None = None,
    correlation_window_ms: int = DEFAULT_CORRELATION_WINDOW_MS,
    max_event_age_ms: int = DEFAULT_MAX_EVENT_AGE_MS,
    confidence_floor: float = DEFAULT_CONFIDENCE_FLOOR,
    state_watermark_ms: int | None = None,
    state_sequence: int | None = None,
    config: FusionConfig | None = None,
) -> FusionResult:
    """Fuse a batch of canonical events into one arbitrated decision.

    Parameters
    ----------
    events:
        Canonical interaction events from any modality adapter. Order of the
        input sequence does not affect the result (order-stable under the
        declared correlation window).
    now_ms:
        Observation clock for age checks. When omitted, age-based staleness is
        not applied (state watermarks still apply).
    state_watermark_ms / state_sequence:
        Newer committed runtime state. Events behind either watermark cannot
        override newer state.
    config:
        Optional closed ``FusionConfig``; overrides the individual window args
        when provided.

    Returns
    -------
    FusionResult
        At most one selected event (or clarification / stale rejection).
        ``authorizes_invocation`` is always False; ``requires_policy_mediation``
        is True whenever a candidate is selected or clarification is needed.
    """

    if config is None:
        config = FusionConfig(
            correlation_window_ms=correlation_window_ms,
            max_event_age_ms=max_event_age_ms,
            confidence_floor=confidence_floor,
        )
    else:
        # Validate via __post_init__ already done; re-check windows for safety.
        if config.correlation_window_ms < 0 or config.max_event_age_ms < 0:
            raise UIIRValidationError("fusion config windows must be non-negative")

    if not isinstance(events, Sequence) or isinstance(events, (str, bytes, bytearray)):
        raise UIIRValidationError("fuse_interactions events must be a sequence")

    if not events:
        explanation = FusionExplanation(
            outcome=FusionOutcome.EMPTY,
            reasons=("no_events",),
            correlated_event_ids=(),
            policy_bypass_allowed=False,
            correlation_window_ms=config.correlation_window_ms,
            detail="No interaction events to fuse",
        )
        return FusionResult(
            selected=None,
            outcome=FusionOutcome.EMPTY,
            requires_clarification=False,
            requires_policy_mediation=False,
            explanation=explanation,
            candidates=(),
        )

    validated: list[CanonicalInteractionEvent] = []
    for event in events:
        if not isinstance(event, CanonicalInteractionEvent):
            raise UIIRValidationError(
                "fuse_interactions requires CanonicalInteractionEvent instances"
            )
        validated_event = validate_event(event)
        assert_not_authority(validated_event)
        validated.append(validated_event)

    # Order-stable: sort before any clustering or selection.
    ordered = sorted(validated, key=_sort_key)

    fresh: list[CanonicalInteractionEvent] = []
    stale: list[CanonicalInteractionEvent] = []
    stale_reasons: list[str] = []
    for event in ordered:
        is_stale, reason = _is_stale(
            event,
            now_ms=now_ms,
            max_event_age_ms=config.max_event_age_ms,
            state_watermark_ms=state_watermark_ms,
            state_sequence=state_sequence,
        )
        if is_stale:
            stale.append(event)
            stale_reasons.append(f"{event.event_id}:{reason}")
        else:
            fresh.append(event)

    if not fresh:
        explanation = FusionExplanation(
            outcome=FusionOutcome.REJECT_STALE,
            reasons=(
                "all_events_stale_or_behind_state",
                *stale_reasons,
                "late_stale_events_cannot_override_newer_state",
            ),
            correlated_event_ids=tuple(e.event_id for e in ordered),
            stale_event_ids=tuple(e.event_id for e in stale),
            policy_bypass_allowed=False,
            correlation_window_ms=config.correlation_window_ms,
            detail="Late/stale events rejected; newer state preserved",
        )
        return FusionResult(
            selected=None,
            outcome=FusionOutcome.REJECT_STALE,
            requires_clarification=False,
            requires_policy_mediation=False,
            explanation=explanation,
            candidates=tuple(ordered),
        )

    clusters = _cluster_by_window(fresh, window_ms=config.correlation_window_ms)

    # Arbitrate each cluster; if multiple clusters, only the newest cluster
    # yields a candidate (older clusters are suppressed as superseded by time).
    # This keeps "at most one" physical/logical action from a batch.
    cluster_results = [_arbitrate_cluster(c, config=config) for c in clusters]
    # Prefer the last (newest) non-clarify select/dedupe/cancel; if any cluster
    # in the newest window clarifies, surface that.
    primary = cluster_results[-1]

    # Fold stale ids into explanation when mixed with fresh.
    if stale:
        reasons = primary.explanation.reasons + (
            "stale_events_suppressed",
            *stale_reasons,
            "late_stale_events_cannot_override_newer_state",
        )
        explanation = FusionExplanation(
            outcome=primary.explanation.outcome,
            reasons=reasons,
            correlated_event_ids=primary.explanation.correlated_event_ids,
            selected_event_id=primary.explanation.selected_event_id,
            suppressed_event_ids=tuple(
                dict.fromkeys(
                    (
                        *primary.explanation.suppressed_event_ids,
                        *(e.event_id for e in stale),
                        *(
                            eid
                            for r in cluster_results[:-1]
                            if r.selected is not None
                            for eid in (r.selected.event_id,)
                        ),
                    )
                )
            ),
            stale_event_ids=tuple(e.event_id for e in stale),
            human_priority_applied=primary.explanation.human_priority_applied,
            policy_bypass_allowed=False,
            correlation_window_ms=config.correlation_window_ms,
            detail=primary.explanation.detail,
        )
        return FusionResult(
            selected=primary.selected,
            outcome=primary.outcome,
            requires_clarification=primary.requires_clarification,
            requires_policy_mediation=primary.requires_policy_mediation
            or primary.selected is not None
            or primary.requires_clarification,
            explanation=explanation,
            candidates=tuple(ordered),
        )

    if len(cluster_results) > 1:
        # Older clusters suppressed so one batch yields at most one action.
        older_ids = tuple(
            e.event_id
            for r in cluster_results[:-1]
            for e in r.candidates
        )
        reasons = primary.explanation.reasons + (
            "older_correlation_clusters_suppressed",
            "one_physical_logical_action_at_most_once",
        )
        explanation = FusionExplanation(
            outcome=primary.explanation.outcome,
            reasons=reasons,
            correlated_event_ids=primary.explanation.correlated_event_ids,
            selected_event_id=primary.explanation.selected_event_id,
            suppressed_event_ids=tuple(
                dict.fromkeys((*primary.explanation.suppressed_event_ids, *older_ids))
            ),
            stale_event_ids=(),
            human_priority_applied=primary.explanation.human_priority_applied,
            policy_bypass_allowed=False,
            correlation_window_ms=config.correlation_window_ms,
            detail=primary.explanation.detail,
        )
        return FusionResult(
            selected=primary.selected,
            outcome=primary.outcome,
            requires_clarification=primary.requires_clarification,
            requires_policy_mediation=(
                primary.requires_policy_mediation
                or primary.selected is not None
                or primary.requires_clarification
            ),
            explanation=explanation,
            candidates=tuple(ordered),
        )

    # Single cluster — return with full candidate set in canonical order.
    return FusionResult(
        selected=primary.selected,
        outcome=primary.outcome,
        requires_clarification=primary.requires_clarification,
        requires_policy_mediation=(
            primary.requires_policy_mediation
            or primary.selected is not None
            or primary.requires_clarification
        ),
        explanation=primary.explanation,
        candidates=tuple(ordered),
    )


class UIMultimodalFusion:
    """Stateful fusion helper holding a declared correlation configuration.

    Stateless ``fuse_interactions`` is the primary API; this class reuses a
    fixed config and optional state watermark for sequential batches.
    """

    interface: Final = UI_MULTIMODAL_FUSION_INTERFACE

    def __init__(
        self,
        config: FusionConfig | None = None,
        *,
        state_watermark_ms: int | None = None,
        state_sequence: int | None = None,
    ) -> None:
        self.config = config or FusionConfig()
        self.state_watermark_ms = state_watermark_ms
        self.state_sequence = state_sequence

    def fuse(
        self,
        events: Sequence[CanonicalInteractionEvent],
        *,
        now_ms: int | None = None,
    ) -> FusionResult:
        return fuse_interactions(
            events,
            now_ms=now_ms,
            config=self.config,
            state_watermark_ms=self.state_watermark_ms,
            state_sequence=self.state_sequence,
        )

    def advance_state(
        self,
        *,
        watermark_ms: int | None = None,
        sequence: int | None = None,
    ) -> None:
        """Record newer committed state so late events cannot override it."""

        if watermark_ms is not None:
            if watermark_ms < 0:
                raise UIIRValidationError("watermark_ms must be non-negative")
            if (
                self.state_watermark_ms is None
                or watermark_ms >= self.state_watermark_ms
            ):
                self.state_watermark_ms = watermark_ms
        if sequence is not None:
            if sequence < 0:
                raise UIIRValidationError("sequence must be non-negative")
            if self.state_sequence is None or sequence >= self.state_sequence:
                self.state_sequence = sequence


__all__ = [
    "DEFAULT_CONFIDENCE_FLOOR",
    "DEFAULT_CORRELATION_WINDOW_MS",
    "DEFAULT_MAX_EVENT_AGE_MS",
    "FUSION_ADAPTER_ID",
    "FusionConfig",
    "FusionExplanation",
    "FusionOutcome",
    "FusionResult",
    "UIMultimodalFusion",
    "UI_MULTIMODAL_FUSION_INTERFACE",
    "fuse_interactions",
]
