"""Chain-specific finality policy, reorg rewind, and orphan projection.

Finality is an explicit state-machine enum (:class:`~models.Finality`), never a
boolean. Shallow reorganizations locate a common ancestor within the configured
safety window and emit orphan/tombstone corrections. Deep reorganizations fail
closed for operator review. Provisional (non-finalized) export requires an
explicit opt-in.

Importing this module performs no I/O.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Any

from .checkpoints import (
    CheckpointIdentity,
    CheckpointRecord,
    HashAnchor,
    build_checkpoint,
    new_revision,
)
from .errors import CheckpointError, InvalidRequestError
from .models import Finality, LedgerPosition
from .protocols import Capabilities, Capability, OperationContext


class ReorgKind(StrEnum):
    """Classification of a chain reorganization relative to a checkpoint."""

    NONE = "none"
    SHALLOW = "shallow"
    DEEP = "deep"


class ReorgReviewRequired(CheckpointError):
    """Deep reorganization exceeded the safety window; stop for review."""


class ProvisionalExportNotAllowed(InvalidRequestError):
    """Export attempted with provisional finality without explicit opt-in."""


# Allowed finality transitions. Terminal correction states may still move
# between ORPHANED and REVERTED; FAILED is terminal for invalid records.
_ALLOWED_TRANSITIONS: Mapping[Finality, frozenset[Finality]] = MappingProxyType(
    {
        Finality.UNKNOWN: frozenset(
            {
                Finality.OBSERVED,
                Finality.PENDING,
                Finality.CONFIRMED,
                Finality.SAFE,
                Finality.FINALIZED,
                Finality.FAILED,
                Finality.ORPHANED,
                Finality.REVERTED,
            }
        ),
        Finality.OBSERVED: frozenset(
            {
                Finality.PENDING,
                Finality.CONFIRMED,
                Finality.SAFE,
                Finality.FINALIZED,
                Finality.ORPHANED,
                Finality.REVERTED,
                Finality.FAILED,
            }
        ),
        Finality.PENDING: frozenset(
            {
                Finality.CONFIRMED,
                Finality.SAFE,
                Finality.FINALIZED,
                Finality.ORPHANED,
                Finality.REVERTED,
                Finality.FAILED,
            }
        ),
        Finality.CONFIRMED: frozenset(
            {
                Finality.SAFE,
                Finality.FINALIZED,
                Finality.ORPHANED,
                Finality.REVERTED,
            }
        ),
        Finality.SAFE: frozenset(
            {
                Finality.FINALIZED,
                Finality.ORPHANED,
                Finality.REVERTED,
            }
        ),
        Finality.FINALIZED: frozenset(
            {
                # Extremely rare on some chains; still modeled as a state change.
                Finality.ORPHANED,
                Finality.REVERTED,
            }
        ),
        Finality.ORPHANED: frozenset({Finality.REVERTED}),
        Finality.REVERTED: frozenset({Finality.ORPHANED}),
        Finality.FAILED: frozenset(),
    }
)

_PROVISIONAL_STATES = frozenset(
    {
        Finality.UNKNOWN,
        Finality.OBSERVED,
        Finality.PENDING,
        Finality.CONFIRMED,
        Finality.SAFE,
    }
)

_EXPORTABLE_DEFAULT = frozenset({Finality.FINALIZED})


def is_provisional(state: Finality) -> bool:
    """Return whether *state* is not yet chain-finalized."""

    if not isinstance(state, Finality):
        raise InvalidRequestError("state must be a Finality value")
    return state in _PROVISIONAL_STATES


def is_correction_state(state: Finality) -> bool:
    """Return whether *state* is an orphan/revert correction."""

    return state in {Finality.ORPHANED, Finality.REVERTED}


def can_transition(current: Finality, target: Finality) -> bool:
    """Return whether the finality state machine permits *current* → *target*."""

    if not isinstance(current, Finality) or not isinstance(target, Finality):
        raise InvalidRequestError("current and target must be Finality values")
    if current == target:
        return True
    return target in _ALLOWED_TRANSITIONS.get(current, frozenset())


def transition(current: Finality, target: Finality) -> Finality:
    """Apply a finality state transition or raise on illegal moves."""

    if not can_transition(current, target):
        raise InvalidRequestError(
            f"illegal finality transition {current.value!r} -> {target.value!r}"
        )
    return target


@dataclass(frozen=True, slots=True)
class FinalityClassification:
    """Result of classifying a record against the current ledger head."""

    state: Finality
    confirmations: int
    head_sequence: int
    record_sequence: int | None
    reason: str

    def __post_init__(self) -> None:
        if not isinstance(self.state, Finality):
            raise InvalidRequestError("state must be a Finality value")
        if isinstance(self.confirmations, bool) or not isinstance(
            self.confirmations, int
        ) or self.confirmations < 0:
            raise InvalidRequestError("confirmations must be a non-negative integer")

    def to_dict(self) -> dict[str, Any]:
        return {
            "state": self.state.value,
            "confirmations": self.confirmations,
            "head_sequence": self.head_sequence,
            "record_sequence": self.record_sequence,
            "reason": self.reason,
        }


@dataclass(frozen=True, slots=True)
class OrphanCorrection:
    """Projection that a previously observed record is no longer canonical."""

    record_id: str
    prior_finality: Finality
    new_finality: Finality
    orphaned_anchor: HashAnchor
    ancestor_anchor: HashAnchor | None
    tombstone: bool = True

    def __post_init__(self) -> None:
        if not self.record_id.strip():
            raise InvalidRequestError("record_id must not be empty")
        if not isinstance(self.prior_finality, Finality):
            raise InvalidRequestError("prior_finality must be a Finality value")
        if not isinstance(self.new_finality, Finality):
            raise InvalidRequestError("new_finality must be a Finality value")
        if self.new_finality not in {Finality.ORPHANED, Finality.REVERTED}:
            raise InvalidRequestError(
                "orphan corrections must target ORPHANED or REVERTED"
            )
        transition(self.prior_finality, self.new_finality)

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "record_id": self.record_id,
            "prior_finality": self.prior_finality.value,
            "new_finality": self.new_finality.value,
            "orphaned_anchor": self.orphaned_anchor.to_dict(),
            "tombstone": self.tombstone,
        }
        if self.ancestor_anchor is not None:
            result["ancestor_anchor"] = self.ancestor_anchor.to_dict()
        return result


@dataclass(frozen=True, slots=True)
class ReorgDecision:
    """Outcome of comparing a checkpoint against an observed tip."""

    kind: ReorgKind
    checkpoint_anchor: HashAnchor
    observed_anchor: HashAnchor
    common_ancestor: HashAnchor | None
    orphaned_anchors: tuple[HashAnchor, ...] = ()
    corrections: tuple[OrphanCorrection, ...] = ()
    rewind_sequence: int | None = None
    review_required: bool = False
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            "checkpoint_anchor": self.checkpoint_anchor.to_dict(),
            "observed_anchor": self.observed_anchor.to_dict(),
            "common_ancestor": (
                None
                if self.common_ancestor is None
                else self.common_ancestor.to_dict()
            ),
            "orphaned_anchors": [a.to_dict() for a in self.orphaned_anchors],
            "corrections": [c.to_dict() for c in self.corrections],
            "rewind_sequence": self.rewind_sequence,
            "review_required": self.review_required,
            "reason": self.reason,
        }


@dataclass(frozen=True, slots=True)
class CanonicalHistory:
    """Bounded sequence of canonical hash anchors for common-ancestor search."""

    anchors: tuple[HashAnchor, ...] = ()

    def __post_init__(self) -> None:
        for anchor in self.anchors:
            if not isinstance(anchor, HashAnchor):
                raise InvalidRequestError("anchors must be HashAnchor values")

    def __len__(self) -> int:
        return len(self.anchors)

    def by_sequence(self) -> Mapping[int, HashAnchor]:
        return MappingProxyType({a.sequence: a for a in self.anchors})

    def hashes(self) -> frozenset[str]:
        return frozenset(a.block_hash for a in self.anchors)

    def append(self, anchor: HashAnchor, *, limit: int = 256) -> "CanonicalHistory":
        items = list(self.anchors)
        if items and items[-1].matches(anchor):
            return self
        if items and items[-1].sequence == anchor.sequence:
            items[-1] = anchor
        else:
            items.append(anchor)
        if limit <= 0:
            raise InvalidRequestError("limit must be a positive integer")
        return CanonicalHistory(anchors=tuple(items[-limit:]))

    @classmethod
    def from_checkpoint(cls, checkpoint: CheckpointRecord) -> "CanonicalHistory":
        return cls(anchors=checkpoint.history)

    @classmethod
    def from_pairs(
        cls, pairs: Sequence[tuple[int, str]]
    ) -> "CanonicalHistory":
        return cls(anchors=tuple(HashAnchor(seq, h) for seq, h in pairs))


def common_ancestor(
    local: CanonicalHistory | Sequence[HashAnchor],
    remote: CanonicalHistory | Sequence[HashAnchor],
) -> HashAnchor | None:
    """Return the highest-sequence shared hash anchor, or ``None``."""

    local_anchors = (
        local.anchors if isinstance(local, CanonicalHistory) else tuple(local)
    )
    remote_anchors = (
        remote.anchors if isinstance(remote, CanonicalHistory) else tuple(remote)
    )
    remote_by_hash = {a.block_hash: a for a in remote_anchors}
    best: HashAnchor | None = None
    for anchor in local_anchors:
        match = remote_by_hash.get(anchor.block_hash)
        if match is None:
            continue
        if match.sequence != anchor.sequence:
            continue
        if best is None or anchor.sequence > best.sequence:
            best = anchor
    return best


def project_orphan_corrections(
    *,
    orphaned_anchors: Sequence[HashAnchor],
    record_ids_by_hash: Mapping[str, Sequence[str]],
    prior_finality_by_id: Mapping[str, Finality],
    ancestor: HashAnchor | None,
    target: Finality = Finality.ORPHANED,
) -> tuple[OrphanCorrection, ...]:
    """Build tombstone corrections for records on orphaned anchors."""

    if target not in {Finality.ORPHANED, Finality.REVERTED}:
        raise InvalidRequestError("target must be ORPHANED or REVERTED")
    corrections: list[OrphanCorrection] = []
    for anchor in orphaned_anchors:
        for record_id in record_ids_by_hash.get(anchor.block_hash, ()):
            prior = prior_finality_by_id.get(record_id, Finality.OBSERVED)
            if is_correction_state(prior):
                continue
            corrections.append(
                OrphanCorrection(
                    record_id=record_id,
                    prior_finality=prior,
                    new_finality=transition(prior, target),
                    orphaned_anchor=anchor,
                    ancestor_anchor=ancestor,
                    tombstone=True,
                )
            )
    return tuple(corrections)


def orphaned_suffix(
    history: Sequence[HashAnchor],
    ancestor: HashAnchor | None,
) -> tuple[HashAnchor, ...]:
    """Return anchors strictly after *ancestor* (all if ancestor is missing)."""

    if ancestor is None:
        return tuple(history)
    result: list[HashAnchor] = []
    seen_ancestor = False
    for anchor in history:
        if anchor.matches(ancestor):
            seen_ancestor = True
            result = []
            continue
        if seen_ancestor:
            result.append(anchor)
    if not seen_ancestor:
        # Ancestor not in this window: treat entire history as potentially orphaned.
        return tuple(history)
    return tuple(result)


@dataclass(frozen=True, slots=True)
class DepthThresholds:
    """Confirmation-depth thresholds that map to finality states.

    Depth alone is never labeled "finalized" without an explicit finalized
    threshold or provider-reported finality tag.
    """

    confirmed: int = 1
    safe: int = 12
    finalized: int | None = 64

    def __post_init__(self) -> None:
        for name in ("confirmed", "safe"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise InvalidRequestError(f"{name} must be a non-negative integer")
        if self.finalized is not None:
            if (
                isinstance(self.finalized, bool)
                or not isinstance(self.finalized, int)
                or self.finalized < 0
            ):
                raise InvalidRequestError("finalized must be a non-negative integer")
        if self.safe < self.confirmed:
            raise InvalidRequestError("safe threshold must be >= confirmed")
        if self.finalized is not None and self.finalized < self.safe:
            raise InvalidRequestError("finalized threshold must be >= safe")


@dataclass
class DepthFinalityPolicy:
    """Reference :class:`~protocols.FinalityPolicy` driven by confirmation depth.

    Chains may wrap or replace this policy; the surface remains pure and free
    of I/O.
    """

    chain_namespaces: frozenset[str]
    thresholds: DepthThresholds = field(default_factory=DepthThresholds)
    max_reorg_depth: int = 64
    provider: str = "depth-finality"

    def __post_init__(self) -> None:
        if not self.chain_namespaces:
            raise InvalidRequestError("chain_namespaces must not be empty")
        if any(not ns.strip() for ns in self.chain_namespaces):
            raise InvalidRequestError("chain namespaces must not be empty")
        if not isinstance(self.thresholds, DepthThresholds):
            raise InvalidRequestError("thresholds must be a DepthThresholds value")
        if (
            isinstance(self.max_reorg_depth, bool)
            or not isinstance(self.max_reorg_depth, int)
            or self.max_reorg_depth < 0
        ):
            raise InvalidRequestError("max_reorg_depth must be a non-negative integer")
        if not self.provider.strip():
            raise InvalidRequestError("provider must not be empty")

    @property
    def capabilities(self) -> Capabilities:
        return Capabilities(
            provider=self.provider,
            chain_namespaces=self.chain_namespaces,
            features=frozenset({Capability.FINALITY, Capability.REORG_RECOVERY}),
            metadata={
                "max_reorg_depth": self.max_reorg_depth,
                "thresholds": {
                    "confirmed": self.thresholds.confirmed,
                    "safe": self.thresholds.safe,
                    "finalized": self.thresholds.finalized,
                },
            },
        )

    def classify(
        self,
        record: object,
        *,
        head: object,
        context: OperationContext,
    ) -> FinalityClassification:
        """Classify *record* finality against *head* using depth thresholds."""

        context.check_active()
        record_seq, record_hash, prior_state = _extract_record_position(record)
        head_seq, _head_hash = _extract_head(head)
        if record_seq is None:
            return FinalityClassification(
                state=prior_state or Finality.UNKNOWN,
                confirmations=0,
                head_sequence=head_seq,
                record_sequence=None,
                reason="record lacks a ledger sequence",
            )
        if record_seq > head_seq:
            return FinalityClassification(
                state=Finality.PENDING,
                confirmations=0,
                head_sequence=head_seq,
                record_sequence=record_seq,
                reason="record sequence is ahead of observed head",
            )
        confirmations = head_seq - record_seq
        state = self._state_for_confirmations(confirmations)
        if prior_state is not None and is_correction_state(prior_state):
            state = prior_state
        elif prior_state is not None and not can_transition(prior_state, state):
            # Do not silently downgrade without a reorg path.
            state = prior_state
        return FinalityClassification(
            state=state,
            confirmations=confirmations,
            head_sequence=head_seq,
            record_sequence=record_seq,
            reason=f"depth={confirmations}",
        )

    def _state_for_confirmations(self, confirmations: int) -> Finality:
        finalized_at = self.thresholds.finalized
        if finalized_at is not None and confirmations >= finalized_at:
            return Finality.FINALIZED
        if confirmations >= self.thresholds.safe:
            return Finality.SAFE
        if confirmations >= self.thresholds.confirmed:
            return Finality.CONFIRMED
        if confirmations >= 0:
            return Finality.OBSERVED
        return Finality.UNKNOWN

    def rewind_position(
        self,
        checkpoint: object,
        *,
        observed_anchor: object,
        context: OperationContext,
    ) -> int | None:
        """Return a safe replay sequence when the checkpoint anchor diverges.

        Returns ``None`` when no rewind is required (anchors still match).
        Raises :class:`ReorgReviewRequired` for deep reorgs.
        """

        context.check_active()
        decision = self.evaluate_reorg(
            checkpoint,
            observed_anchor=observed_anchor,
            context=context,
        )
        if decision.kind is ReorgKind.NONE:
            return None
        if decision.review_required:
            raise ReorgReviewRequired(
                decision.reason
                or "deep reorganization requires operator review"
            )
        return decision.rewind_sequence

    def evaluate_reorg(
        self,
        checkpoint: object,
        *,
        observed_anchor: object,
        context: OperationContext,
        remote_history: CanonicalHistory | Sequence[HashAnchor] | None = None,
        record_ids_by_hash: Mapping[str, Sequence[str]] | None = None,
        prior_finality_by_id: Mapping[str, Finality] | None = None,
    ) -> ReorgDecision:
        """Compare *checkpoint* to *observed_anchor* and classify the reorg."""

        context.check_active()
        cp = _as_checkpoint(checkpoint)
        observed = _as_hash_anchor(observed_anchor)
        local_history = CanonicalHistory.from_checkpoint(cp)

        if cp.anchor.matches(observed):
            return ReorgDecision(
                kind=ReorgKind.NONE,
                checkpoint_anchor=cp.anchor,
                observed_anchor=observed,
                common_ancestor=cp.anchor,
                rewind_sequence=None,
                reason="checkpoint anchor matches observed tip",
            )

        remote = (
            CanonicalHistory(anchors=tuple(remote_history))
            if isinstance(remote_history, Sequence)
            and not isinstance(remote_history, CanonicalHistory)
            else remote_history
        )
        if remote is None:
            # Without remote history, use the observed tip alone.
            remote = CanonicalHistory(anchors=(observed,))
        elif isinstance(remote, CanonicalHistory):
            if not any(a.matches(observed) for a in remote.anchors):
                remote = remote.append(observed)

        ancestor = common_ancestor(local_history, remote)
        if ancestor is None:
            # Fail closed: no shared anchor inside the retained history window.
            return ReorgDecision(
                kind=ReorgKind.DEEP,
                checkpoint_anchor=cp.anchor,
                observed_anchor=observed,
                common_ancestor=None,
                orphaned_anchors=local_history.anchors,
                corrections=(),
                rewind_sequence=None,
                review_required=True,
                reason=(
                    "no common ancestor within bounded history; "
                    "deep reorg requires operator review"
                ),
            )

        orphans = orphaned_suffix(local_history.anchors, ancestor)
        depth = len(orphans)
        if depth == 0 and not cp.anchor.matches(observed):
            # Tip hash changed at same height (single-block replacement).
            orphans = (cp.anchor,)
            depth = 1

        safety = max(self.max_reorg_depth, cp.safety_depth)
        if depth > safety:
            return ReorgDecision(
                kind=ReorgKind.DEEP,
                checkpoint_anchor=cp.anchor,
                observed_anchor=observed,
                common_ancestor=ancestor,
                orphaned_anchors=orphans,
                corrections=(),
                rewind_sequence=ancestor.sequence,
                review_required=True,
                reason=(
                    f"reorg depth {depth} exceeds safety window {safety}; "
                    "deep reorg requires operator review"
                ),
            )

        corrections = project_orphan_corrections(
            orphaned_anchors=orphans,
            record_ids_by_hash=record_ids_by_hash or {},
            prior_finality_by_id=prior_finality_by_id or {},
            ancestor=ancestor,
            target=Finality.ORPHANED,
        )
        return ReorgDecision(
            kind=ReorgKind.SHALLOW,
            checkpoint_anchor=cp.anchor,
            observed_anchor=observed,
            common_ancestor=ancestor,
            orphaned_anchors=orphans,
            corrections=corrections,
            rewind_sequence=ancestor.sequence,
            review_required=False,
            reason=f"shallow reorg depth={depth}; rewind to common ancestor",
        )

    def apply_shallow_rewind(
        self,
        checkpoint: CheckpointRecord,
        decision: ReorgDecision,
        *,
        identity: CheckpointIdentity | None = None,
    ) -> CheckpointRecord:
        """Build a rewound checkpoint at the common ancestor after a shallow reorg.

        Continuation tokens from the old tip are dropped; only the hash anchor
        of the ancestor is retained for resume.
        """

        if decision.review_required or decision.kind is ReorgKind.DEEP:
            raise ReorgReviewRequired(
                decision.reason
                or "deep reorganization requires operator review"
            )
        if decision.kind is not ReorgKind.SHALLOW:
            raise CheckpointError(
                "apply_shallow_rewind requires a shallow reorg decision"
            )
        if decision.common_ancestor is None or decision.rewind_sequence is None:
            raise CheckpointError("shallow reorg decision lacks a common ancestor")
        target_identity = identity or checkpoint.identity
        if not checkpoint.identity.compatible_with(target_identity):
            raise CheckpointError("identity mismatch during rewind")
        retained = tuple(
            a
            for a in checkpoint.history
            if a.sequence <= decision.common_ancestor.sequence
        )
        if not retained or not retained[-1].matches(decision.common_ancestor):
            retained = retained + (decision.common_ancestor,)
        return build_checkpoint(
            target_identity,
            sequence=decision.common_ancestor.sequence,
            block_hash=decision.common_ancestor.block_hash,
            revision=new_revision(),
            safety_depth=checkpoint.safety_depth,
            continuation_token=None,
            sink_commit_id=None,
            prior_history=retained[:-1],
            metadata={
                **dict(checkpoint.metadata),
                "rewound_from": checkpoint.anchor.to_dict(),
                "reorg_kind": decision.kind.value,
            },
        )


def assert_export_finality(
    states: Sequence[Finality] | Mapping[Finality, int],
    *,
    allow_provisional: bool = False,
    permitted: frozenset[Finality] | None = None,
) -> None:
    """Fail closed when exporting provisional states without explicit opt-in.

    *allow_provisional* must be set deliberately by the caller; silent export of
    observed/pending/confirmed/safe data is rejected.
    """

    permitted_states = permitted or _EXPORTABLE_DEFAULT
    if isinstance(states, Mapping):
        present = {state for state, count in states.items() if count}
    else:
        present = set(states)
    for state in present:
        if not isinstance(state, Finality):
            raise InvalidRequestError("export finality states must be Finality values")
        if state in permitted_states:
            continue
        if is_provisional(state) and not allow_provisional:
            raise ProvisionalExportNotAllowed(
                f"provisional finality {state.value!r} requires explicit "
                "allow_provisional=True opt-in for export"
            )
        if is_correction_state(state) and state not in permitted_states:
            # Corrections are exportable by default so consumers see tombstones.
            continue
        if state is Finality.FAILED and state not in permitted_states:
            continue
        if state not in permitted_states and not allow_provisional:
            raise ProvisionalExportNotAllowed(
                f"finality {state.value!r} is not permitted for export without opt-in"
            )


def _extract_head(head: object) -> tuple[int, str | None]:
    if isinstance(head, HashAnchor):
        return head.sequence, head.block_hash
    if isinstance(head, LedgerPosition):
        if head.sequence is None:
            raise InvalidRequestError("head position requires a sequence")
        return head.sequence, head.hash
    if isinstance(head, Mapping):
        seq = head.get("sequence", head.get("height", head.get("slot")))
        h = head.get("hash", head.get("block_hash"))
        if seq is None:
            raise InvalidRequestError("head mapping requires sequence/height/slot")
        return int(seq), None if h is None else str(h)
    sequence = getattr(head, "sequence", None)
    if sequence is None:
        sequence = getattr(head, "height", None)
    block_hash = getattr(head, "hash", None)
    if block_hash is None:
        block_hash = getattr(head, "block_hash", None)
    if sequence is None:
        raise InvalidRequestError("unable to extract head sequence")
    return int(sequence), None if block_hash is None else str(block_hash)


def _extract_record_position(
    record: object,
) -> tuple[int | None, str | None, Finality | None]:
    if isinstance(record, Mapping):
        pos = record.get("ledger_position") or record.get("position") or record
        seq = None
        h = None
        if isinstance(pos, Mapping):
            seq = pos.get("sequence")
            h = pos.get("hash")
        elif isinstance(pos, LedgerPosition):
            seq = pos.sequence
            h = pos.hash
        finality = record.get("finality")
        if isinstance(finality, str):
            finality = Finality(finality)
        return (
            None if seq is None else int(seq),
            None if h is None else str(h),
            finality if isinstance(finality, Finality) else None,
        )
    position = getattr(record, "ledger_position", None)
    if position is None:
        position = getattr(record, "position", None)
    seq = getattr(position, "sequence", None) if position is not None else None
    h = getattr(position, "hash", None) if position is not None else None
    finality = getattr(record, "finality", None)
    if isinstance(finality, str):
        finality = Finality(finality)
    return (
        None if seq is None else int(seq),
        None if h is None else str(h),
        finality if isinstance(finality, Finality) else None,
    )


def _as_checkpoint(checkpoint: object) -> CheckpointRecord:
    if isinstance(checkpoint, CheckpointRecord):
        return checkpoint
    raise InvalidRequestError("checkpoint must be a CheckpointRecord")


def _as_hash_anchor(value: object) -> HashAnchor:
    if isinstance(value, HashAnchor):
        return value
    if isinstance(value, LedgerPosition):
        if value.sequence is None or not value.hash:
            raise CheckpointError(
                "observed anchor requires sequence and canonical hash; "
                "provider continuation tokens never replace hash anchors"
            )
        return HashAnchor(sequence=value.sequence, block_hash=value.hash)
    if isinstance(value, Mapping):
        seq = value.get("sequence", value.get("height", value.get("slot")))
        h = value.get("block_hash", value.get("hash"))
        if seq is None or h is None or not str(h).strip():
            raise CheckpointError(
                "observed anchor requires sequence and canonical hash"
            )
        return HashAnchor(sequence=int(seq), block_hash=str(h))
    raise InvalidRequestError("observed_anchor must provide sequence and hash")


# Backwards-compatible alias matching the protocol method name used in AST queries.
rewind = DepthFinalityPolicy.rewind_position


__all__ = [
    "CanonicalHistory",
    "DepthFinalityPolicy",
    "DepthThresholds",
    "FinalityClassification",
    "OrphanCorrection",
    "ProvisionalExportNotAllowed",
    "ReorgDecision",
    "ReorgKind",
    "ReorgReviewRequired",
    "assert_export_finality",
    "can_transition",
    "common_ancestor",
    "is_correction_state",
    "is_provisional",
    "orphaned_suffix",
    "project_orphan_corrections",
    "rewind",
    "transition",
]
