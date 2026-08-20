"""Immutable interaction receipts and side-effect-free replay (UIR-056).

Records projection / event / fusion / state / policy / invocation / result /
verification / feedback / fallback lineage. Separates deterministic decision
data from observational telemetry. Validates chain integrity (tamper,
missing parent, identity mismatch, reorder). Replay reconstructs dispositions
without calling executors or re-issuing external effects.

Interfaces: ``UIInteractionReceipt@1``, ``UIReplayTrace@1``.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, Final, Mapping, Sequence

from ..schema import UIIRValidationError
from .mediator import MediationOutcome, UIMediationDecision

UI_INTERACTION_RECEIPT_INTERFACE: Final = "UIInteractionReceipt@1"
UI_REPLAY_TRACE_INTERFACE: Final = "UIReplayTrace@1"
RECEIPTS_ADAPTER_ID: Final = "runtime.receipts@1"
RECEIPTS_SCHEMA_VERSION: Final = "ui-runtime-receipts/v1"


class FeedbackKind(str, Enum):
    """User-visible feedback class for every mediation outcome."""

    SUCCESS = "success"
    DENIAL = "denial"
    CONFIRMATION = "confirmation"
    DEFER = "defer"
    REWRITE = "rewrite"
    FALLBACK = "fallback"
    RATE_LIMIT = "rate_limit"
    FAILURE = "failure"
    ERROR = "error"
    UNKNOWN = "unknown"
    INFO = "info"


class ResultDisposition(str, Enum):
    """Mapped invocation / action result (observational when from transport)."""

    NONE = "none"
    SUCCESS = "success"
    FAILURE = "failure"
    PARTIAL = "partial"
    CANCELLED = "cancelled"
    TIMEOUT = "timeout"


# Default user-visible feedback per mediation outcome.
_FEEDBACK_FOR_OUTCOME: Final[Mapping[MediationOutcome, FeedbackKind]] = MappingProxyType(
    {
        MediationOutcome.ALLOW: FeedbackKind.SUCCESS,
        MediationOutcome.DENY: FeedbackKind.DENIAL,
        MediationOutcome.CONFIRM: FeedbackKind.CONFIRMATION,
        MediationOutcome.DEFER: FeedbackKind.DEFER,
        MediationOutcome.REWRITE: FeedbackKind.REWRITE,
        MediationOutcome.FALLBACK: FeedbackKind.FALLBACK,
        MediationOutcome.RATE_LIMIT: FeedbackKind.RATE_LIMIT,
        MediationOutcome.ERROR: FeedbackKind.ERROR,
        MediationOutcome.UNKNOWN: FeedbackKind.UNKNOWN,
    }
)


def _canonical_json(payload: Mapping[str, Any]) -> bytes:
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _digest_payload(payload: Mapping[str, Any]) -> str:
    return f"sha256:{_sha256_hex(_canonical_json(payload))}"


@dataclass(frozen=True, slots=True)
class FeedbackMetadata:
    """User-visible feedback attached to every receipt (including denials)."""

    kind: FeedbackKind
    message_key: str
    detail: str = ""
    requires_user_action: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "detail": self.detail,
            "kind": self.kind.value,
            "message_key": self.message_key,
            "requires_user_action": self.requires_user_action,
        }


@dataclass(frozen=True, slots=True)
class LineageRefs:
    """Immutable lineage bindings for one interaction step."""

    declaration_digest: str
    projection_id: str = ""
    event_id: str = ""
    fusion_id: str = ""
    state_version: int = 0
    policy_norm_id: str = ""
    decision_id: str = ""
    invocation_request_id: str = ""
    verification_ids: tuple[str, ...] = ()
    rollback_ref: str = ""
    fallback_binding_id: str = ""
    rewrite_binding_id: str = ""
    parent_receipt_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision_id": self.decision_id,
            "declaration_digest": self.declaration_digest,
            "event_id": self.event_id,
            "fallback_binding_id": self.fallback_binding_id,
            "fusion_id": self.fusion_id,
            "invocation_request_id": self.invocation_request_id,
            "parent_receipt_id": self.parent_receipt_id,
            "policy_norm_id": self.policy_norm_id,
            "projection_id": self.projection_id,
            "rollback_ref": self.rollback_ref,
            "rewrite_binding_id": self.rewrite_binding_id,
            "state_version": self.state_version,
            "verification_ids": list(self.verification_ids),
        }


@dataclass(frozen=True, slots=True)
class UIInteractionReceipt:
    """Immutable interaction receipt (``UIInteractionReceipt@1``).

    Deterministic fields participate in ``content_digest``. Observational
    fields are excluded from the digest so telemetry cannot rewrite identity.
    """

    receipt_id: str
    sequence: int
    outcome: MediationOutcome
    disposition: ResultDisposition
    feedback: FeedbackMetadata
    lineage: LineageRefs
    # Deterministic decision payload (reasons, can_execute, binding ids).
    decision_payload: Mapping[str, Any] = field(
        default_factory=lambda: MappingProxyType({})
    )
    # Observational only — never part of content_digest.
    observational: Mapping[str, Any] = field(
        default_factory=lambda: MappingProxyType({})
    )
    content_digest: str = ""
    adapter_id: str = RECEIPTS_ADAPTER_ID
    interface: str = UI_INTERACTION_RECEIPT_INTERFACE
    schema_version: str = RECEIPTS_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if type(self.decision_payload) is not MappingProxyType:
            object.__setattr__(
                self, "decision_payload", MappingProxyType(dict(self.decision_payload))
            )
        if type(self.observational) is not MappingProxyType:
            object.__setattr__(
                self, "observational", MappingProxyType(dict(self.observational))
            )
        if not self.content_digest:
            object.__setattr__(self, "content_digest", self.compute_digest())

    def deterministic_payload(self) -> dict[str, Any]:
        """Fields that define receipt identity (excludes observational)."""

        return {
            "decision_payload": dict(self.decision_payload),
            "disposition": self.disposition.value,
            "feedback": self.feedback.to_dict(),
            "interface": self.interface,
            "lineage": self.lineage.to_dict(),
            "outcome": self.outcome.value,
            "receipt_id": self.receipt_id,
            "schema_version": self.schema_version,
            "sequence": self.sequence,
        }

    def compute_digest(self) -> str:
        return _digest_payload(self.deterministic_payload())

    def to_dict(self) -> dict[str, Any]:
        return {
            **self.deterministic_payload(),
            "adapter_id": self.adapter_id,
            "content_digest": self.content_digest,
            "observational": dict(self.observational),
        }


@dataclass(frozen=True, slots=True)
class UIReplayTrace:
    """Validated receipt chain with side-effect-free replay result."""

    trace_id: str
    receipts: tuple[UIInteractionReceipt, ...]
    final_outcome: MediationOutcome | None
    terminated: bool
    reason: str = ""
    interface: str = UI_REPLAY_TRACE_INTERFACE
    schema_version: str = RECEIPTS_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "final_outcome": None if self.final_outcome is None else self.final_outcome.value,
            "interface": self.interface,
            "reason": self.reason,
            "receipts": [r.to_dict() for r in self.receipts],
            "schema_version": self.schema_version,
            "terminated": self.terminated,
            "trace_id": self.trace_id,
        }


def feedback_for_outcome(
    outcome: MediationOutcome,
    *,
    detail: str = "",
) -> FeedbackMetadata:
    """Map every mediation outcome to user-visible feedback metadata."""

    kind = _FEEDBACK_FOR_OUTCOME.get(outcome, FeedbackKind.INFO)
    requires = outcome in {
        MediationOutcome.CONFIRM,
        MediationOutcome.DEFER,
        MediationOutcome.REWRITE,
        MediationOutcome.FALLBACK,
    }
    return FeedbackMetadata(
        kind=kind,
        message_key=f"ui.feedback.{outcome.value}",
        detail=detail,
        requires_user_action=requires,
    )


def build_receipt_from_decision(
    decision: UIMediationDecision,
    *,
    declaration_digest: str,
    projection_id: str = "",
    state_version: int = 0,
    fusion_id: str = "",
    sequence: int = 0,
    parent_receipt_id: str = "",
    disposition: ResultDisposition = ResultDisposition.NONE,
    observational: Mapping[str, Any] | None = None,
    verification_ids: Sequence[str] = (),
    rollback_ref: str = "",
) -> UIInteractionReceipt:
    """Build an immutable receipt for any mediation decision (including denials)."""

    inv = decision.invocation_request
    lineage = LineageRefs(
        declaration_digest=declaration_digest,
        projection_id=projection_id,
        event_id=decision.event_id,
        fusion_id=fusion_id,
        state_version=state_version,
        policy_norm_id=decision.selected_policy_norm_id,
        decision_id=decision.decision_id,
        invocation_request_id="" if inv is None else inv.request_id,
        verification_ids=tuple(verification_ids),
        rollback_ref=rollback_ref,
        fallback_binding_id=decision.fallback_binding_id,
        rewrite_binding_id=decision.rewrite_binding_id,
        parent_receipt_id=parent_receipt_id,
    )
    decision_payload = {
        "action_id": decision.action_id,
        "binding_id": decision.binding_id,
        "can_execute": decision.can_execute,
        "decision_id": decision.decision_id,
        "outcome": decision.outcome.value,
        "reasons": list(decision.reasons),
    }
    receipt_id = f"rcpt-{_sha256_hex(_canonical_json({
        'decision_id': decision.decision_id,
        'sequence': sequence,
        'parent': parent_receipt_id,
    }))[:24]}"
    return UIInteractionReceipt(
        receipt_id=receipt_id,
        sequence=sequence,
        outcome=decision.outcome,
        disposition=disposition,
        feedback=feedback_for_outcome(
            decision.outcome,
            detail="; ".join(decision.reasons[:4]),
        ),
        lineage=lineage,
        decision_payload=decision_payload,
        observational=dict(observational or {}),
    )


def validate_receipt(receipt: UIInteractionReceipt) -> UIInteractionReceipt:
    """Fail closed on empty identity, digest mismatch, or missing lineage."""

    if not receipt.receipt_id.strip():
        raise UIIRValidationError("receipt_id must not be empty")
    if receipt.sequence < 0:
        raise UIIRValidationError("sequence must be non-negative")
    if not receipt.lineage.declaration_digest.strip():
        raise UIIRValidationError("lineage.declaration_digest must not be empty")
    if not receipt.lineage.decision_id.strip():
        raise UIIRValidationError("lineage.decision_id must not be empty")
    expected = receipt.compute_digest()
    if receipt.content_digest != expected:
        raise UIIRValidationError(
            f"Receipt {receipt.receipt_id!r} content_digest mismatch "
            f"(tamper or identity rewrite detected)"
        )
    # Observational data must not equal declaration digest.
    obs_digest = receipt.observational.get("content_digest")
    if (
        isinstance(obs_digest, str)
        and obs_digest == receipt.lineage.declaration_digest
    ):
        raise UIIRValidationError(
            f"Receipt {receipt.receipt_id!r} observational payload must not "
            "claim declaration digest identity"
        )
    return receipt


def validate_receipt_chain(
    receipts: Sequence[UIInteractionReceipt],
    *,
    expected_declaration_digest: str | None = None,
) -> tuple[UIInteractionReceipt, ...]:
    """Validate integrity of an ordered receipt chain.

    Detects: digest tamper, missing parent, mismatched declaration identity,
    sequence reorder, and parent/child linkage breaks.
    """

    if not receipts:
        raise UIIRValidationError("receipt chain must not be empty")

    validated: list[UIInteractionReceipt] = []
    seen_ids: set[str] = set()
    prev: UIInteractionReceipt | None = None

    for index, receipt in enumerate(receipts):
        validate_receipt(receipt)
        if receipt.receipt_id in seen_ids:
            raise UIIRValidationError(
                f"Duplicate receipt_id in chain: {receipt.receipt_id!r}"
            )
        seen_ids.add(receipt.receipt_id)

        if receipt.sequence != index:
            raise UIIRValidationError(
                f"Receipt {receipt.receipt_id!r} sequence {receipt.sequence} "
                f"does not match chain index {index} (reorder detected)"
            )

        if expected_declaration_digest is not None:
            if receipt.lineage.declaration_digest != expected_declaration_digest:
                raise UIIRValidationError(
                    f"Receipt {receipt.receipt_id!r} declaration_digest mismatch "
                    "with chain declaration identity"
                )

        if prev is None:
            if receipt.lineage.parent_receipt_id:
                raise UIIRValidationError(
                    f"First receipt {receipt.receipt_id!r} must not have a parent"
                )
        else:
            parent = receipt.lineage.parent_receipt_id
            if not parent:
                raise UIIRValidationError(
                    f"Receipt {receipt.receipt_id!r} missing parent_receipt_id"
                )
            if parent != prev.receipt_id:
                raise UIIRValidationError(
                    f"Receipt {receipt.receipt_id!r} parent_receipt_id "
                    f"{parent!r} does not match previous {prev.receipt_id!r}"
                )
            if receipt.lineage.declaration_digest != prev.lineage.declaration_digest:
                raise UIIRValidationError(
                    f"Receipt {receipt.receipt_id!r} declaration_digest diverges "
                    "from parent (identity mismatch)"
                )

        validated.append(receipt)
        prev = receipt

    return tuple(validated)


def replay_receipts(
    receipts: Sequence[UIInteractionReceipt],
    *,
    expected_declaration_digest: str | None = None,
    executor: Any = None,
) -> UIReplayTrace:
    """Replay a receipt chain without side effects.

    Never calls ``executor`` even if provided. Reconstructs the sequence of
    decision outcomes/dispositions for integrity checking only.
    """

    if executor is not None:
        # Explicitly refuse to touch any executor during replay.
        pass

    validated = validate_receipt_chain(
        receipts,
        expected_declaration_digest=expected_declaration_digest,
    )
    # Deterministic reconstruction of outcomes (no transport, no effects).
    outcomes = tuple(r.outcome for r in validated)
    final = outcomes[-1] if outcomes else None
    material = {
        "outcomes": [o.value for o in outcomes],
        "receipt_ids": [r.receipt_id for r in validated],
        "digests": [r.content_digest for r in validated],
    }
    trace_id = f"replay-{_sha256_hex(_canonical_json(material))[:24]}"
    return UIReplayTrace(
        trace_id=trace_id,
        receipts=validated,
        final_outcome=final,
        terminated=True,
        reason="replay_ok_no_effects",
    )


def assert_replay_no_effects(
    receipts: Sequence[UIInteractionReceipt],
    *,
    executor_spy: list[Any] | None = None,
) -> UIReplayTrace:
    """Replay and assert no executor was invoked (spy stays empty)."""

    spy = executor_spy if executor_spy is not None else []

    def _forbidden(_req: Any) -> Any:
        spy.append(_req)
        raise AssertionError("replay must never call executor")

    # Even if a caller wires a spy, replay_receipts ignores it.
    trace = replay_receipts(receipts, executor=_forbidden)
    if spy:
        raise UIIRValidationError(
            f"Replay invoked executor {len(spy)} time(s); side-effect free invariant broken"
        )
    return trace


def tamper_receipt(
    receipt: UIInteractionReceipt,
    *,
    mutate_outcome: MediationOutcome | None = None,
    mutate_digest: str | None = None,
) -> UIInteractionReceipt:
    """Test helper: produce a tampered receipt (does not recompute digest)."""

    return UIInteractionReceipt(
        receipt_id=receipt.receipt_id,
        sequence=receipt.sequence,
        outcome=mutate_outcome if mutate_outcome is not None else receipt.outcome,
        disposition=receipt.disposition,
        feedback=receipt.feedback,
        lineage=receipt.lineage,
        decision_payload=dict(receipt.decision_payload),
        observational=dict(receipt.observational),
        content_digest=mutate_digest if mutate_digest is not None else receipt.content_digest,
    )
