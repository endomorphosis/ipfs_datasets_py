"""Hash-anchored compare-and-set checkpoints for wallet ledger ingestion.

Checkpoints bind an exact scan identity (chain, network, genesis, provider,
scope, schema major, normalizer version) to a canonical hash anchor. Provider
continuation tokens are optional pagination hints only; they never replace the
hash-anchored position for resume or CAS advance.

Importing this module performs no I/O.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from types import MappingProxyType
from typing import Any
from uuid import uuid4

from .canonical import content_digest, deterministic_id
from .errors import CheckpointError, InvalidRequestError
from .models import ChainRef, LedgerCursor, LedgerPosition
from .protocols import OperationContext


CHECKPOINT_SCHEMA_VERSION = "wallet-checkpoint-v1"
DEFAULT_HISTORY_LIMIT = 256


def _required_str(value: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise InvalidRequestError(f"{name} must not be empty")
    return value


def _positive_int(value: int, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise InvalidRequestError(f"{name} must be a positive integer")
    return value


def _non_negative_int(value: int, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise InvalidRequestError(f"{name} must be a non-negative integer")
    return value


@dataclass(frozen=True, slots=True)
class CheckpointIdentity:
    """Exact ingestion identity that a durable checkpoint must bind.

    Two scans with different chain/network/genesis, provider, scope, schema
    major, or normalizer version never share a checkpoint key.
    """

    chain: ChainRef
    provider: str
    scope: str
    normalized_schema_major: int
    normalizer_version: str

    def __post_init__(self) -> None:
        if not isinstance(self.chain, ChainRef):
            raise InvalidRequestError("chain must be a ChainRef")
        object.__setattr__(self, "provider", _required_str(self.provider, "provider"))
        object.__setattr__(self, "scope", _required_str(self.scope, "scope"))
        _positive_int(self.normalized_schema_major, "normalized_schema_major")
        object.__setattr__(
            self,
            "normalizer_version",
            _required_str(self.normalizer_version, "normalizer_version"),
        )

    @property
    def key(self) -> str:
        """Stable opaque key used by :class:`CheckpointStore` implementations."""

        return deterministic_id(
            "checkpoint-scope",
            {
                "chain": self.chain.identity_dict(),
                "provider": self.provider,
                "scope": self.scope,
                "normalized_schema_major": self.normalized_schema_major,
                "normalizer_version": self.normalizer_version,
            },
        )

    def matches_scope_key(self, scope: str) -> bool:
        """Return whether *scope* is this identity's store key or raw scope."""

        return scope == self.key or scope == self.scope

    def to_dict(self) -> dict[str, Any]:
        return {
            "chain": self.chain.to_dict(),
            "provider": self.provider,
            "scope": self.scope,
            "normalized_schema_major": self.normalized_schema_major,
            "normalizer_version": self.normalizer_version,
            "key": self.key,
        }

    def to_cursor_fields(self) -> dict[str, Any]:
        return {
            "chain": self.chain,
            "provider": self.provider,
            "scope": self.scope,
            "normalized_schema_major": self.normalized_schema_major,
            "normalizer_version": self.normalizer_version,
        }

    def compatible_with(self, other: "CheckpointIdentity") -> bool:
        return (
            self.chain.identity_dict() == other.chain.identity_dict()
            and self.provider == other.provider
            and self.scope == other.scope
            and self.normalized_schema_major == other.normalized_schema_major
            and self.normalizer_version == other.normalizer_version
        )


@dataclass(frozen=True, slots=True)
class HashAnchor:
    """Canonical block/slot/ledger hash coordinate.

    Continuation tokens must never be treated as substitutes for this anchor.
    """

    sequence: int
    block_hash: str

    def __post_init__(self) -> None:
        _non_negative_int(self.sequence, "sequence")
        object.__setattr__(
            self, "block_hash", _required_str(self.block_hash, "block_hash")
        )

    def to_position(self) -> LedgerPosition:
        return LedgerPosition(sequence=self.sequence, hash=self.block_hash)

    def to_dict(self) -> dict[str, Any]:
        return {"sequence": self.sequence, "block_hash": self.block_hash}

    @classmethod
    def from_position(cls, position: LedgerPosition) -> "HashAnchor":
        if position.sequence is None:
            raise CheckpointError("checkpoint position requires a sequence")
        if position.hash is None or not str(position.hash).strip():
            raise CheckpointError(
                "checkpoint position requires a canonical hash anchor; "
                "provider continuation tokens never replace hash anchors"
            )
        return cls(sequence=position.sequence, block_hash=position.hash)

    def matches(self, other: "HashAnchor") -> bool:
        return self.sequence == other.sequence and self.block_hash == other.block_hash


@dataclass(frozen=True, slots=True)
class CheckpointRecord:
    """Durable, hash-anchored checkpoint for one exact scan identity."""

    identity: CheckpointIdentity
    anchor: HashAnchor
    revision: str
    safety_depth: int = 0
    continuation_token: str | None = None
    sink_commit_id: str | None = None
    history: tuple[HashAnchor, ...] = ()
    metadata: Mapping[str, object] = field(default_factory=dict)
    schema_version: str = field(default=CHECKPOINT_SCHEMA_VERSION, init=False)
    checkpoint_id: str = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.identity, CheckpointIdentity):
            raise InvalidRequestError("identity must be a CheckpointIdentity")
        if not isinstance(self.anchor, HashAnchor):
            raise InvalidRequestError("anchor must be a HashAnchor")
        object.__setattr__(self, "revision", _required_str(self.revision, "revision"))
        _non_negative_int(self.safety_depth, "safety_depth")
        if self.continuation_token is not None:
            object.__setattr__(
                self,
                "continuation_token",
                _required_str(self.continuation_token, "continuation_token"),
            )
        if self.sink_commit_id is not None:
            object.__setattr__(
                self,
                "sink_commit_id",
                _required_str(self.sink_commit_id, "sink_commit_id"),
            )
        history = tuple(self.history)
        for item in history:
            if not isinstance(item, HashAnchor):
                raise InvalidRequestError("history entries must be HashAnchor values")
        if not history or history[-1] != self.anchor:
            history = history + (self.anchor,)
        object.__setattr__(self, "history", history)
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))
        object.__setattr__(
            self,
            "checkpoint_id",
            deterministic_id(
                "checkpoint",
                {
                    "identity": self.identity.to_dict(),
                    "anchor": self.anchor.to_dict(),
                    "revision": self.revision,
                },
            ),
        )

    def to_cursor(self) -> LedgerCursor:
        """Project this checkpoint into the shared :class:`LedgerCursor` model.

        The optional continuation token is preserved as a provider pagination
        hint only; resume validation always uses the hash anchor.
        """

        return LedgerCursor(
            **self.identity.to_cursor_fields(),
            position=self.anchor.to_position(),
            revision=self.revision,
            continuation_token=self.continuation_token,
        )

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "schema_version": self.schema_version,
            "checkpoint_id": self.checkpoint_id,
            "identity": self.identity.to_dict(),
            "anchor": self.anchor.to_dict(),
            "revision": self.revision,
            "safety_depth": self.safety_depth,
            "history": [item.to_dict() for item in self.history],
            "metadata": dict(self.metadata),
        }
        if self.continuation_token is not None:
            result["continuation_token"] = self.continuation_token
        if self.sink_commit_id is not None:
            result["sink_commit_id"] = self.sink_commit_id
        return result

    def with_history_limit(self, limit: int) -> "CheckpointRecord":
        """Return a copy retaining at most *limit* trailing anchors."""

        _positive_int(limit, "limit")
        trimmed = self.history[-limit:]
        if trimmed[-1] != self.anchor:
            trimmed = trimmed + (self.anchor,)
        return replace(self, history=trimmed)


def new_revision() -> str:
    """Allocate a unique CAS revision token."""

    return f"rev:{uuid4().hex}"


def assert_hash_anchor_present(
    position: LedgerPosition,
    *,
    continuation_token: str | None = None,
) -> HashAnchor:
    """Require a canonical hash anchor; reject token-only advances."""

    try:
        return HashAnchor.from_position(position)
    except CheckpointError:
        if continuation_token is not None:
            raise CheckpointError(
                "provider continuation tokens never replace canonical hash "
                "anchors; checkpoint advance requires a block/slot/ledger hash"
            ) from None
        raise


def validate_resume(
    checkpoint: CheckpointRecord,
    *,
    observed_anchor: HashAnchor,
    identity: CheckpointIdentity | None = None,
) -> None:
    """Validate that a loaded checkpoint may resume against *observed_anchor*.

    When the observed tip still matches the stored anchor, resume is a no-op.
    When the tip diverges, callers must run reorg/rewind logic rather than
    blindly advancing from a continuation token.
    """

    if identity is not None and not checkpoint.identity.compatible_with(identity):
        raise CheckpointError(
            "checkpoint identity does not match the requested scan "
            "(chain/network/genesis/provider/scope/schema/normalizer)"
        )
    if checkpoint.anchor.matches(observed_anchor):
        return
    # Divergence is not itself an error here; reorg resolution handles it.
    # Missing hashes on the stored checkpoint are always fatal.
    if not checkpoint.anchor.block_hash.strip():
        raise CheckpointError(
            "stored checkpoint is missing a canonical hash anchor"
        )


@dataclass(frozen=True, slots=True)
class SinkCommitReceipt:
    """Proof that a dataset sink committed data before checkpoint CAS."""

    commit_id: str
    scope_key: str
    record_count: int
    content_digest: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "commit_id", _required_str(self.commit_id, "commit_id"))
        object.__setattr__(self, "scope_key", _required_str(self.scope_key, "scope_key"))
        _non_negative_int(self.record_count, "record_count")


class CheckpointCommitCoordinator:
    """Enforces the sink-commit-before-checkpoint-CAS ordering invariant.

    Pipelines stage batches into a sink, obtain a commit receipt, then call
    :meth:`compare_and_set_after_commit`. A CAS without a matching sink receipt
    fails closed.
    """

    def __init__(self, store: "InMemoryCheckpointStore") -> None:
        self._store = store
        self._pending: dict[str, SinkCommitReceipt] = {}

    def note_sink_commit(self, receipt: SinkCommitReceipt) -> None:
        """Record that the sink committed for *receipt.scope_key*."""

        self._pending[receipt.scope_key] = receipt

    def pending_commit(self, scope_key: str) -> SinkCommitReceipt | None:
        return self._pending.get(scope_key)

    async def compare_and_set_after_commit(
        self,
        identity: CheckpointIdentity,
        *,
        expected_revision: str | None,
        checkpoint: CheckpointRecord,
        context: OperationContext,
        require_commit: bool = True,
    ) -> bool:
        """CAS only after a matching sink commit for the identity key."""

        context.check_active()
        if not checkpoint.identity.compatible_with(identity):
            raise CheckpointError(
                "checkpoint identity does not match the store key identity"
            )
        scope_key = identity.key
        receipt = self._pending.get(scope_key)
        if require_commit:
            if receipt is None:
                raise CheckpointError(
                    "sink commit must precede checkpoint compare-and-set"
                )
            if checkpoint.sink_commit_id is None:
                raise CheckpointError(
                    "checkpoint is missing sink_commit_id from the prior sink commit"
                )
            if checkpoint.sink_commit_id != receipt.commit_id:
                raise CheckpointError(
                    "checkpoint sink_commit_id does not match the pending sink receipt"
                )
        accepted = await self._store.compare_and_set(
            scope_key,
            expected_revision=expected_revision,
            checkpoint=checkpoint,
            context=context,
        )
        if accepted and scope_key in self._pending:
            del self._pending[scope_key]
        return accepted


class InMemoryCheckpointStore:
    """Reference :class:`~protocols.CheckpointStore` with optimistic CAS.

    Suitable for unit tests and single-process pipelines. Concurrent writers
    lose the CAS when their expected revision is stale. Crash replay is
    idempotent: repeating a successful CAS with the same expected revision
    fails, while reloading the stored revision and replaying yields the same
    durable state.
    """

    def __init__(self, *, history_limit: int = DEFAULT_HISTORY_LIMIT) -> None:
        self._history_limit = _positive_int(history_limit, "history_limit")
        self._entries: dict[str, CheckpointRecord] = {}
        self._cas_attempts: int = 0
        self._cas_successes: int = 0

    @property
    def cas_attempts(self) -> int:
        return self._cas_attempts

    @property
    def cas_successes(self) -> int:
        return self._cas_successes

    def keys(self) -> frozenset[str]:
        return frozenset(self._entries)

    async def load(
        self,
        scope: str,
        *,
        context: OperationContext,
    ) -> CheckpointRecord | None:
        """Load the checkpoint for an exact ingestion scope key or raw scope."""

        context.check_active()
        _required_str(scope, "scope")
        if scope in self._entries:
            return self._entries[scope]
        for record in self._entries.values():
            if record.identity.matches_scope_key(scope):
                return record
        return None

    async def compare_and_set(
        self,
        scope: str,
        *,
        expected_revision: str | None,
        checkpoint: object,
        context: OperationContext,
    ) -> bool:
        """Atomically store *checkpoint* when the revision still matches."""

        context.check_active()
        self._cas_attempts += 1
        _required_str(scope, "scope")
        if not isinstance(checkpoint, CheckpointRecord):
            raise CheckpointError("checkpoint must be a CheckpointRecord")
        # Identity must bind to the store key: either the computed key or the
        # human scope string the identity advertises.
        if not checkpoint.identity.matches_scope_key(scope):
            raise CheckpointError(
                "checkpoint identity does not bind to the provided scope key"
            )
        store_key = checkpoint.identity.key
        current = self._entries.get(store_key)
        current_revision = None if current is None else current.revision
        if current_revision != expected_revision:
            return False
        if current is not None and not current.identity.compatible_with(
            checkpoint.identity
        ):
            raise CheckpointError(
                "refusing to overwrite checkpoint with incompatible identity "
                "(chain/network/genesis/provider/scope/schema/normalizer)"
            )
        # Hash anchors are mandatory; continuation tokens alone are rejected.
        assert_hash_anchor_present(
            checkpoint.anchor.to_position(),
            continuation_token=checkpoint.continuation_token,
        )
        stored = checkpoint.with_history_limit(self._history_limit)
        self._entries[store_key] = stored
        self._cas_successes += 1
        return True

    async def replace_after_rewind(
        self,
        identity: CheckpointIdentity,
        *,
        expected_revision: str,
        rewound: CheckpointRecord,
        context: OperationContext,
    ) -> bool:
        """CAS a rewound checkpoint for the same identity after reorg handling."""

        if not rewound.identity.compatible_with(identity):
            raise CheckpointError("rewound checkpoint identity mismatch")
        return await self.compare_and_set(
            identity.key,
            expected_revision=expected_revision,
            checkpoint=rewound,
            context=context,
        )


def append_anchor_history(
    history: Sequence[HashAnchor],
    anchor: HashAnchor,
    *,
    limit: int = DEFAULT_HISTORY_LIMIT,
) -> tuple[HashAnchor, ...]:
    """Append *anchor* to a bounded canonical history window."""

    _positive_int(limit, "limit")
    items = list(history)
    if items and items[-1].matches(anchor):
        return tuple(items[-limit:])
    # Replace same-sequence divergences (reorg tip rewrite).
    if items and items[-1].sequence == anchor.sequence:
        items[-1] = anchor
    else:
        items.append(anchor)
    return tuple(items[-limit:])


def build_checkpoint(
    identity: CheckpointIdentity,
    *,
    sequence: int,
    block_hash: str,
    revision: str | None = None,
    safety_depth: int = 0,
    continuation_token: str | None = None,
    sink_commit_id: str | None = None,
    prior_history: Sequence[HashAnchor] = (),
    history_limit: int = DEFAULT_HISTORY_LIMIT,
    metadata: Mapping[str, object] | None = None,
) -> CheckpointRecord:
    """Construct a hash-anchored checkpoint with bounded history."""

    anchor = HashAnchor(sequence=sequence, block_hash=block_hash)
    history = append_anchor_history(prior_history, anchor, limit=history_limit)
    return CheckpointRecord(
        identity=identity,
        anchor=anchor,
        revision=revision or new_revision(),
        safety_depth=safety_depth,
        continuation_token=continuation_token,
        sink_commit_id=sink_commit_id,
        history=history,
        metadata=dict(metadata or {}),
    )


def checkpoint_content_fingerprint(checkpoint: CheckpointRecord) -> str:
    """Deterministic content digest for crash-replay equality checks."""

    payload = checkpoint.to_dict()
    # Revision and checkpoint_id change every CAS; fingerprint durable fields.
    durable = {
        "identity": payload["identity"],
        "anchor": payload["anchor"],
        "safety_depth": payload["safety_depth"],
        "history": payload["history"],
        "continuation_token": payload.get("continuation_token"),
        "sink_commit_id": payload.get("sink_commit_id"),
        "metadata": payload["metadata"],
    }
    return content_digest(durable)


__all__ = [
    "CHECKPOINT_SCHEMA_VERSION",
    "DEFAULT_HISTORY_LIMIT",
    "CheckpointCommitCoordinator",
    "CheckpointIdentity",
    "CheckpointRecord",
    "HashAnchor",
    "InMemoryCheckpointStore",
    "SinkCommitReceipt",
    "append_anchor_history",
    "assert_hash_anchor_present",
    "build_checkpoint",
    "checkpoint_content_fingerprint",
    "new_revision",
    "validate_resume",
]
