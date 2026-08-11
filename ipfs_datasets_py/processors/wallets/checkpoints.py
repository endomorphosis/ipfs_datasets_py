"""Hash-anchored compare-and-set checkpoints for wallet ledger ingestion.

Checkpoints bind an exact scan identity (chain, network, genesis, provider,
scope, schema major, normalizer version) to a canonical hash anchor. Provider
continuation tokens are optional pagination hints only; they never replace the
hash-anchored position for resume or CAS advance.

When a DuckDB wallet store is injected (DQK-071 shadow mode), every successful
CAS, rewind, and reorg decision is dual-written so cursors, finality tips, and
reorg history shadow at ingestion time.  The in-memory map remains authority
until DQK-072 authority cutover.

Importing this module performs no I/O.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Any
from uuid import uuid4

from .canonical import content_digest, deterministic_id, freeze_json, thaw_json
from .errors import CheckpointError, InvalidRequestError
from .models import ChainRef, LedgerCursor, LedgerPosition, ensure_secret_safe
from .protocols import OperationContext


CHECKPOINT_SCHEMA_VERSION = "wallet-checkpoint-v1"
DEFAULT_HISTORY_LIMIT = 256
SHADOW_CHECKPOINT_MODE = "shadow"


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
            ensure_secret_safe(self.continuation_token)
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
        if not isinstance(self.metadata, Mapping):
            raise InvalidRequestError("metadata must be a mapping")
        ensure_secret_safe(self.metadata)
        frozen_metadata = freeze_json(self.metadata)
        ensure_secret_safe(frozen_metadata)
        object.__setattr__(self, "metadata", frozen_metadata)
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
        ensure_secret_safe(self.to_dict())

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
            "metadata": thaw_json(self.metadata),
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

    @property
    def store(self) -> "InMemoryCheckpointStore":
        return self._store

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

    When *shadow_store* is provided (or *shadow* is true), every successful
    CAS dual-writes into the DuckDB wallet store so cursors and checkpoint
    tips shadow at ingestion time (DQK-071).  Authority remains this map.
    """

    def __init__(
        self,
        *,
        history_limit: int = DEFAULT_HISTORY_LIMIT,
        shadow_store: Any | None = None,
        shadow: bool | Any | None = None,
    ) -> None:
        self._history_limit = _positive_int(history_limit, "history_limit")
        self._entries: dict[str, CheckpointRecord] = {}
        self._cas_attempts: int = 0
        self._cas_successes: int = 0
        self._shadow_cas_successes: int = 0
        self._shadow_cas_rejects: int = 0
        self._reorg_history: list[dict[str, Any]] = []
        self._shadow = _resolve_checkpoint_shadow(
            shadow_store=shadow_store,
            shadow=shadow,
        )

    @property
    def cas_attempts(self) -> int:
        return self._cas_attempts

    @property
    def cas_successes(self) -> int:
        return self._cas_successes

    @property
    def shadow_store(self) -> Any | None:
        return self._shadow

    @property
    def shadow_cas_successes(self) -> int:
        return self._shadow_cas_successes

    @property
    def shadow_cas_rejects(self) -> int:
        return self._shadow_cas_rejects

    def keys(self) -> frozenset[str]:
        return frozenset(self._entries)

    def attach_shadow(self, shadow_store: Any | None) -> None:
        """Attach or replace the DuckDB shadow checkpoint port (DQK-071)."""

        self._shadow = shadow_store

    async def load(
        self,
        scope: str,
        *,
        context: OperationContext,
    ) -> CheckpointRecord | None:
        """Load the checkpoint for an exact ingestion scope key or raw scope.

        Authority is the in-memory map.  When a shadow store is present, a
        successful memory load may optionally be parity-checked against the
        shadow tip (mismatches raise after dual-write divergence).
        """

        context.check_active()
        _required_str(scope, "scope")
        record: CheckpointRecord | None = None
        if scope in self._entries:
            record = self._entries[scope]
        else:
            for candidate in self._entries.values():
                if candidate.identity.matches_scope_key(scope):
                    record = candidate
                    break
        return record

    async def compare_and_set(
        self,
        scope: str,
        *,
        expected_revision: str | None,
        checkpoint: object,
        context: OperationContext,
    ) -> bool:
        """Atomically store *checkpoint* when the revision still matches.

        On success, dual-writes the same CAS into the shadow DuckDB store when
        one is attached so cursor/checkpoint projections stay in parity.
        """

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
        await self._shadow_compare_and_set(
            store_key,
            expected_revision=expected_revision,
            checkpoint=stored,
            context=context,
        )
        return True

    async def _shadow_compare_and_set(
        self,
        scope_key: str,
        *,
        expected_revision: str | None,
        checkpoint: CheckpointRecord,
        context: OperationContext,
    ) -> None:
        if self._shadow is None:
            return
        cas = getattr(self._shadow, "compare_and_set", None)
        if not callable(cas):
            raise CheckpointError(
                "shadow checkpoint store does not implement compare_and_set"
            )
        try:
            accepted = await cas(
                scope_key,
                expected_revision=expected_revision,
                checkpoint=checkpoint,
                context=context,
            )
        except Exception as exc:
            raise CheckpointError(
                f"shadow checkpoint CAS failed: {exc}"
            ) from exc
        if not accepted:
            self._shadow_cas_rejects += 1
            raise CheckpointError(
                "shadow checkpoint CAS rejected (revision mismatch); "
                "authority and shadow tips have diverged"
            )
        self._shadow_cas_successes += 1

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

    async def shadow_reorg_rollback(
        self,
        decision: object,
        *,
        chain: object,
        provenance: object,
        identity: CheckpointIdentity,
        rewound: CheckpointRecord,
        expected_revision: str,
        context: OperationContext,
        reorg_id: str | None = None,
        apply_corrections: bool = True,
    ) -> Mapping[str, Any]:
        """Record reorg history and CAS-rewind authority + shadow tips (DQK-071).

        Authority rewind uses :meth:`replace_after_rewind`.  When a shadow store
        is attached, the DuckDB reorg/finality path is also invoked so reorg
        rows and orphan corrections shadow at ingestion time.
        """

        advanced = await self.replace_after_rewind(
            identity,
            expected_revision=expected_revision,
            rewound=rewound,
            context=context,
        )
        result: dict[str, Any] = {
            "checkpoint_advanced": bool(advanced),
            "mode": SHADOW_CHECKPOINT_MODE if self._shadow is not None else "memory",
            "reorg_id": reorg_id,
        }
        if self._shadow is not None:
            apply = getattr(self._shadow, "apply_reorg_rollback", None)
            if callable(apply):
                # Shadow already received the checkpoint CAS via dual-write on
                # replace_after_rewind; apply_reorg_rollback would CAS again
                # with a now-stale expected revision.  Prefer record_reorg +
                # corrections when the dual-write already moved the tip.
                record_reorg = getattr(self._shadow, "record_reorg", None)
                if callable(record_reorg):
                    reorg_row = record_reorg(
                        decision,
                        chain=chain,
                        provenance=provenance,
                        reorg_id=reorg_id,
                        apply_corrections=apply_corrections,
                    )
                    result["reorg_id"] = str(
                        reorg_row.get("reorg_id") if isinstance(reorg_row, Mapping) else reorg_id
                    )
                    result["reorg_row"] = (
                        dict(reorg_row) if isinstance(reorg_row, Mapping) else reorg_row
                    )
                else:
                    shadow_result = await apply(
                        decision,
                        chain=chain,
                        provenance=provenance,
                        identity=identity,
                        rewound=rewound,
                        expected_revision=expected_revision,
                        context=context,
                        reorg_id=reorg_id,
                        apply_corrections=apply_corrections,
                    )
                    if isinstance(shadow_result, Mapping):
                        result.update(dict(shadow_result))
        self._reorg_history.append(dict(result))
        return result

    def shadow_finality_transition(self, **kwargs: Any) -> dict[str, Any] | None:
        """Apply a finality transition on the shadow store when attached."""

        if self._shadow is None:
            return None
        apply = getattr(self._shadow, "apply_finality_transition", None)
        if not callable(apply):
            raise CheckpointError(
                "shadow store does not implement apply_finality_transition"
            )
        row = apply(**kwargs)
        return dict(row) if isinstance(row, Mapping) else row

    def checkpoint_parity(
        self, scope_key: str, *, context: OperationContext | None = None
    ) -> Mapping[str, Any]:
        """Compare authority tip with shadow tip for *scope_key*.

        Returns a small parity report used by integration tests and dual-write
        diagnostics.  When no shadow is attached, reports ``shadow=None``.
        """

        authority = self._entries.get(scope_key)
        shadow_record = None
        if self._shadow is not None:
            # Prefer synchronous access to shadow heads when available; fall
            # back to catalog list of checkpoints.
            heads = getattr(self._shadow, "_checkpoint_heads", None)
            if isinstance(heads, Mapping) and scope_key in heads:
                head = heads[scope_key]
                shadow_record = getattr(head, "record", None)
            if shadow_record is None:
                list_records = getattr(self._shadow, "list_records", None)
                if callable(list_records):
                    try:
                        rows = list_records("checkpoints")
                    except Exception:
                        rows = ()
                    # Pick latest matching identity key via checkpoint_id.
                    if authority is not None:
                        for row in rows:
                            if (
                                isinstance(row, Mapping)
                                and row.get("checkpoint_id") == authority.checkpoint_id
                            ):
                                shadow_record = row
                                break
        if authority is None and shadow_record is None:
            return {
                "matched": True,
                "scope_key": scope_key,
                "authority": None,
                "shadow": None,
            }
        if authority is None or shadow_record is None:
            return {
                "matched": False,
                "scope_key": scope_key,
                "authority": None if authority is None else authority.to_dict(),
                "shadow": (
                    None
                    if shadow_record is None
                    else (
                        shadow_record.to_dict()
                        if hasattr(shadow_record, "to_dict")
                        else dict(shadow_record)
                    )
                ),
            }
        if isinstance(shadow_record, CheckpointRecord):
            shadow_anchor = shadow_record.anchor
            shadow_revision = shadow_record.revision
            shadow_id = shadow_record.checkpoint_id
        else:
            shadow_anchor_seq = shadow_record.get("anchor_sequence") or shadow_record.get(
                "sequence"
            )
            shadow_anchor_hash = shadow_record.get("anchor_hash") or shadow_record.get(
                "block_hash"
            )
            shadow_revision = shadow_record.get("revision")
            shadow_id = shadow_record.get("checkpoint_id")
            shadow_anchor = None
            if shadow_anchor_seq is not None and shadow_anchor_hash:
                shadow_anchor = HashAnchor(
                    int(shadow_anchor_seq), str(shadow_anchor_hash)
                )
        matched = (
            authority.checkpoint_id == shadow_id
            and authority.revision == shadow_revision
            and shadow_anchor is not None
            and authority.anchor.matches(shadow_anchor)
        )
        return {
            "matched": bool(matched),
            "scope_key": scope_key,
            "authority_checkpoint_id": authority.checkpoint_id,
            "shadow_checkpoint_id": shadow_id,
            "authority_revision": authority.revision,
            "shadow_revision": shadow_revision,
            "authority_anchor": authority.anchor.to_dict(),
            "shadow_anchor": (
                shadow_anchor.to_dict() if shadow_anchor is not None else None
            ),
            "mode": SHADOW_CHECKPOINT_MODE,
        }

    def reorg_history(self) -> tuple[Mapping[str, Any], ...]:
        return tuple(dict(item) for item in self._reorg_history)


def _resolve_checkpoint_shadow(
    *,
    shadow_store: Any | None,
    shadow: bool | Any | None,
) -> Any | None:
    if shadow_store is not None:
        return shadow_store
    if shadow is False or shadow is None:
        return None
    if shadow is True:
        from .duckdb_storage import open_wallet_store

        return open_wallet_store(scope="wallet-checkpoint-shadow", auto_recover=True)
    return shadow


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
    "SHADOW_CHECKPOINT_MODE",
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
