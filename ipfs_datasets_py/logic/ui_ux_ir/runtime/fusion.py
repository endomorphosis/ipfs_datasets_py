"""Deterministic multimodal fusion and arbitration (UIR-053).

Fusion may select or clarify a candidate intent/event but never authorizes or
invokes it. One physical/logical action is admitted at most once. Human
priority does not bypass runtime policy. Inconsistent high-impact events
require clarification. Late/stale events cannot override newer state.
Order-stable and deterministic.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Any, Final, Mapping, Sequence

from ..schema import UIIRValidationError
from .events import CanonicalInteractionEvent, EventKind, EventProvenance, validate_event

FUSION_ADAPTER_ID: Final = "runtime.fusion@1"
FUSION_INTERFACE: Final = "MultimodalFusion@1"
FUSION_SCHEMA_VERSION: Final = "ui-runtime-fusion/v1"

# Kinds treated as high-impact for multi-source inconsistency checks.
_HIGH_IMPACT_KINDS: Final = frozenset(
    {
        EventKind.ACTIVATE,
        EventKind.CONFIRM,
        EventKind.CANCEL,
        EventKind.SELECT,
        EventKind.NAVIGATE,
    }
)


class FusionDecision(str, Enum):
    SELECT = "select"
    CLARIFY = "clarify"
    SUPPRESS_DUPLICATE = "suppress_duplicate"
    REJECT_STALE = "reject_stale"
    REJECT_INCONSISTENT = "reject_inconsistent"


class FusionPriority(str, Enum):
    """Relative source priority. Human ranks above agent/synthetic but never
    bypasses consent/policy gates (fusion does not authorize)."""

    HUMAN = "human"
    SYSTEM = "system"
    AGENT = "agent"
    SYNTHETIC = "synthetic"
    UNKNOWN = "unknown"


_PROVENANCE_PRIORITY: Mapping[EventProvenance, int] = MappingProxyType(
    {
        EventProvenance.HUMAN: 40,
        EventProvenance.SYSTEM: 30,
        EventProvenance.AGENT: 20,
        EventProvenance.SYNTHETIC: 10,
        EventProvenance.UNKNOWN: 0,
    }
)


@dataclass(frozen=True, slots=True)
class FusionCandidate:
    event: CanonicalInteractionEvent
    source_modality: str = ""
    risk_hint: str = "low"  # low | medium | high | critical


@dataclass(frozen=True, slots=True)
class FusionResult:
    decision: FusionDecision
    selected: CanonicalInteractionEvent | None
    clarification_reason: str = ""
    suppressed: tuple[CanonicalInteractionEvent, ...] = ()
    alternatives: tuple[CanonicalInteractionEvent, ...] = ()
    fusion_id: str = ""
    adapter_id: str = FUSION_ADAPTER_ID
    interface: str = FUSION_INTERFACE
    schema_version: str = FUSION_SCHEMA_VERSION
    notes: str = ""


def _risk_rank(hint: str) -> int:
    return {"low": 1, "medium": 2, "high": 3, "critical": 4}.get(str(hint).lower(), 1)


def _event_key(event: CanonicalInteractionEvent) -> tuple[str, str, str]:
    return (event.kind.value, event.target_component_id, event.capability_id)


def fuse_events(
    candidates: Sequence[FusionCandidate | CanonicalInteractionEvent],
    *,
    fusion_id: str = "fusion:1",
    latest_state_timestamp_ms: int | None = None,
    debounce_window_ms: int = 250,
) -> FusionResult:
    """Fuse multimodal candidates into one select/clarify/suppress decision.

    Parameters
    ----------
    candidates:
        Injected recognized events or fusion candidates. Raw sensors stay out.
    latest_state_timestamp_ms:
        If set, candidates with timestamp_ms strictly less than this value are
        treated as stale and cannot override newer state.
    debounce_window_ms:
        Window used to suppress duplicate activations of the same logical action.
    """

    if not candidates:
        raise UIIRValidationError("fusion requires at least one candidate")

    normalized: list[FusionCandidate] = []
    for item in candidates:
        if isinstance(item, FusionCandidate):
            event = validate_event(item.event)
            normalized.append(
                FusionCandidate(
                    event=event,
                    source_modality=item.source_modality or event.capability_id,
                    risk_hint=item.risk_hint,
                )
            )
        elif isinstance(item, CanonicalInteractionEvent):
            event = validate_event(item)
            normalized.append(
                FusionCandidate(
                    event=event,
                    source_modality=event.capability_id,
                    risk_hint="low",
                )
            )
        else:
            raise UIIRValidationError("fusion candidates must be events or FusionCandidate")

    # Reject stale against newer state.
    fresh: list[FusionCandidate] = []
    stale: list[CanonicalInteractionEvent] = []
    for cand in normalized:
        if (
            latest_state_timestamp_ms is not None
            and cand.event.timestamp_ms < latest_state_timestamp_ms
        ):
            stale.append(cand.event)
        else:
            fresh.append(cand)
    if not fresh:
        return FusionResult(
            decision=FusionDecision.REJECT_STALE,
            selected=None,
            clarification_reason="all_candidates_stale",
            suppressed=tuple(stale),
            fusion_id=fusion_id,
            notes="Late/stale events cannot override newer state",
        )

    # Deterministic order: higher priority, then higher confidence, then earlier sequence, then event_id.
    def sort_key(c: FusionCandidate) -> tuple:
        conf = c.event.confidence if c.event.confidence is not None else 0.0
        return (
            -_PROVENANCE_PRIORITY.get(c.event.provenance, 0),
            -conf,
            c.event.sequence,
            c.event.timestamp_ms,
            c.event.event_id,
        )

    ordered = sorted(fresh, key=sort_key)
    primary = ordered[0]

    # Suppress duplicates of the same logical action within debounce window.
    suppressed: list[CanonicalInteractionEvent] = list(stale)
    unique: list[FusionCandidate] = []
    seen_keys: dict[tuple[str, str, str], FusionCandidate] = {}
    for cand in ordered:
        key = _event_key(cand.event)
        prior = seen_keys.get(key)
        if prior is not None:
            delta = abs(cand.event.timestamp_ms - prior.event.timestamp_ms)
            if delta <= debounce_window_ms and cand.event.kind in _HIGH_IMPACT_KINDS:
                suppressed.append(cand.event)
                continue
        seen_keys[key] = cand
        unique.append(cand)

    if not unique:
        return FusionResult(
            decision=FusionDecision.SUPPRESS_DUPLICATE,
            selected=None,
            clarification_reason="duplicate_action_debounced",
            suppressed=tuple(suppressed),
            fusion_id=fusion_id,
            notes="One physical/logical action invokes at most once",
        )

    primary = unique[0]
    rest = unique[1:]

    # Inconsistent high-impact multi-target/multi-kind under high risk → clarify.
    high_risk = any(_risk_rank(c.risk_hint) >= 3 for c in unique)
    high_impact = [c for c in unique if c.event.kind in _HIGH_IMPACT_KINDS]
    targets = {c.event.target_component_id for c in high_impact}
    kinds = {c.event.kind for c in high_impact}
    if high_risk and (len(targets) > 1 or len(kinds) > 1):
        return FusionResult(
            decision=FusionDecision.CLARIFY,
            selected=None,
            clarification_reason="inconsistent_high_impact_events",
            alternatives=tuple(c.event for c in unique),
            suppressed=tuple(suppressed),
            fusion_id=fusion_id,
            notes="Inconsistent high-impact events require clarification; fusion cannot authorize",
        )

    # Human priority ranks candidates but does not skip consent (already validated).
    # Multi-source same action collapses to one selection.
    return FusionResult(
        decision=FusionDecision.SELECT,
        selected=primary.event,
        alternatives=tuple(c.event for c in rest),
        suppressed=tuple(suppressed),
        fusion_id=fusion_id,
        notes=(
            "Selected by provenance priority + confidence; "
            "fusion does not authorize or invoke"
        ),
    )


__all__ = [
    "FUSION_ADAPTER_ID",
    "FUSION_INTERFACE",
    "FusionCandidate",
    "FusionDecision",
    "FusionPriority",
    "FusionResult",
    "fuse_events",
]
