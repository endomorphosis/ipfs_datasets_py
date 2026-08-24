"""Immutable DuckLake history projector (EAAEF-094).

Project authoritative DuckDB outbox cursors into frozen epoch bundles of
task/event/audit history, snapshots, lineage, benchmarks and recovery
manifests. DuckLake never grants or revokes current claims, leases, fences
or merge authority.

Import is side-effect free: no DuckDB connection, sockets, or network.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final, Protocol

from .capabilities import (
    PINNED_DUCKLAKE_EXTENSION_BUILD,
    PINNED_HTTPFS_EXTENSION_BUILD,
    PINNED_QUACK_EXTENSION_BUILD,
    REQUIRED_DUCKDB_VERSION_TEXT,
)

HISTORY_SCHEMA: Final[str] = "ipfs_datasets_py/ducklake/external-agent-history@1"
HISTORY_CURSOR_SCHEMA: Final[str] = "ipfs_datasets_py/ducklake/external-agent-history-cursor@1"
HISTORY_SNAPSHOT_SCHEMA: Final[str] = "ipfs_datasets_py/ducklake/external-agent-history-snapshot@1"
HISTORY_EPOCH_SCHEMA: Final[str] = "ipfs_datasets_py/ducklake/external-agent-history-epoch@1"
HISTORY_EVENT_SCHEMA: Final[str] = "ipfs_datasets_py/ducklake/external-agent-history-event@1"
HISTORY_OUTBOX_BATCH_SCHEMA: Final[str] = (
    "ipfs_datasets_py/ducklake/external-agent-history-outbox-batch@1"
)
HISTORY_PROJECTION_RECEIPT_SCHEMA: Final[str] = (
    "ipfs_datasets_py/ducklake/external-agent-history-projection-receipt@1"
)
HISTORY_PROJECTION_RESULT_SCHEMA: Final[str] = (
    "ipfs_datasets_py/ducklake/external-agent-history-projection-result@1"
)
HISTORY_ACTIVATION_SCHEMA: Final[str] = (
    "ipfs_datasets_py/ducklake/external-agent-history-activation@1"
)
HISTORY_OWNER_IDENTITY_SCHEMA: Final[str] = (
    "ipfs_datasets_py/ducklake/external-agent-history-owner-identity@1"
)
HISTORY_CONTROL_SEAM_CAPABILITY_SCHEMA: Final[str] = (
    "ipfs_accelerate_py/agent-supervisor/external-agent-history-control-seam-capability@1"
)
HISTORY_LAKE_CAPABILITY_SCHEMA: Final[str] = (
    "ipfs_datasets_py/ducklake/external-agent-history-lake-capability@1"
)
HISTORY_CONTROL_ACK_SCHEMA: Final[str] = (
    "ipfs_accelerate_py/agent-supervisor/external-agent-history-control-ack@1"
)
HISTORY_QUACK_REQUEST_SCHEMA: Final[str] = (
    "ipfs_datasets_py/ducklake/external-agent-history-quack-request@1"
)

CONTROL_HISTORY_CURSOR_READ_OPERATION: Final[str] = "history.projection.cursor.read"
CONTROL_HISTORY_OUTBOX_READ_OPERATION: Final[str] = "history.outbox.read.committed"
CONTROL_HISTORY_CURSOR_RECORD_OPERATION: Final[str] = "history.projection.cursor.record"
LAKE_HISTORY_CAPABILITY_OPERATION: Final[str] = "history.capability.read"
LAKE_HISTORY_CURSOR_OPERATION: Final[str] = "history.cursor.read"
LAKE_HISTORY_APPEND_OPERATION: Final[str] = "history.epoch.append"

REQUIRED_CONTROL_HISTORY_OPERATIONS: Final[frozenset[str]] = frozenset(
    {
        CONTROL_HISTORY_CURSOR_READ_OPERATION,
        CONTROL_HISTORY_OUTBOX_READ_OPERATION,
        CONTROL_HISTORY_CURSOR_RECORD_OPERATION,
    }
)
REQUIRED_LAKE_HISTORY_OPERATIONS: Final[frozenset[str]] = frozenset(
    {
        LAKE_HISTORY_CAPABILITY_OPERATION,
        LAKE_HISTORY_CURSOR_OPERATION,
        LAKE_HISTORY_APPEND_OPERATION,
    }
)

MAX_HISTORY_BATCH_EVENTS: Final[int] = 5_000
MAX_HISTORY_BATCH_BYTES: Final[int] = 16 * 1024 * 1024
MAX_HISTORY_BATCH_SECONDS: Final[int] = 10

EVENT_KINDS: Final[frozenset[str]] = frozenset(
    {
        "task",
        "event",
        "audit",
        "snapshot",
        "lineage",
        "benchmark",
        "recovery",
    }
)

_SHA256_RE: Final[re.Pattern[str]] = re.compile(r"^sha256:[0-9a-f]{64}$")
_ID_RE: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/=@+-]*$")

_HIDDEN_CHAIN_OF_THOUGHT_KEYS: Final[frozenset[str]] = frozenset(
    {
        "chain_of_thought",
        "cot",
        "hidden_chain_of_thought",
        "hidden_cot",
        "hidden_reasoning",
        "hidden_thoughts",
        "internal_monologue",
        "model_thoughts",
        "private_reasoning",
        "private_thinking",
        "scratchpad",
        "thinking",
        "thinking_blocks",
        "thinking_private",
        "thinking_text",
    }
)
_PRIVATE_FIELD_MARKERS: Final[frozenset[str]] = frozenset(
    {
        "access_token",
        "api_key",
        "authorization",
        "cookie",
        "credential",
        "hidden_witness",
        "password",
        "private_key",
        "private_premise",
        "private_witness",
        "refresh_token",
        "secret",
        "session_token",
        "transcript_body",
        "witness",
    }
)
_TRANSCRIPT_BODY_KEYS: Final[frozenset[str]] = frozenset(
    {
        "body",
        "full_transcript",
        "prompt",
        "raw_bytes",
        "raw_export",
        "raw_prompt",
        "raw_transcript",
        "source_body",
        "transcript",
        "transcript_body",
        "transcript_text",
    }
)


class HistoryError(ValueError):
    """Fail-closed DuckLake history projection rejection."""


class HistoryCursorError(HistoryError):
    """Authoritative outbox cursor is missing or malformed."""


class DuplicateEpochError(HistoryError):
    """An epoch identity was projected more than once."""


class HistoryAuthorityError(HistoryError):
    """DuckLake attempted to grant or revoke current authority."""


class HistoryPrivacyError(HistoryError):
    """Secrets, transcript bodies, or hidden reasoning appeared on history."""


class HistoryActivationError(HistoryError):
    """The typed control/lake projection chain is not safe to activate."""


class HistoryContentionError(HistoryActivationError):
    """A second process attempted to own the same DuckLake history catalog."""


class HistoryContinuityError(HistoryError):
    """The control cursor, outbox batch, and lake head do not form one chain."""


class HistoryTransportError(HistoryError):
    """A client attempted to bypass the typed Quack transport."""


class HistoryReceiptError(HistoryError):
    """A lake projection or control acknowledgement receipt is inconsistent."""


def _canonical_json(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def _sha256_text(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def _digest_of(payload: Any) -> str:
    return _sha256_text(_canonical_json(payload))


def _normalize_key(value: Any) -> str:
    return str(value).strip().lower().replace("-", "_")


def _key_is_forbidden(key: str) -> str | None:
    normalized = _normalize_key(key)
    if normalized in _HIDDEN_CHAIN_OF_THOUGHT_KEYS:
        return "hidden_chain_of_thought"
    if normalized in _TRANSCRIPT_BODY_KEYS:
        return "transcript_body"
    if any(
        normalized == marker or normalized.endswith("_" + marker) or marker in normalized
        for marker in _PRIVATE_FIELD_MARKERS
    ):
        return "private_material"
    return None


def _reject_forbidden_keys(value: Any, *, name: str) -> None:
    if isinstance(value, Mapping):
        for raw_key, item in value.items():
            reason = _key_is_forbidden(str(raw_key))
            if reason == "hidden_chain_of_thought":
                raise HistoryPrivacyError(f"{name} must not represent hidden chain-of-thought")
            if reason == "transcript_body":
                raise HistoryPrivacyError(f"{name} must not embed transcript bodies")
            if reason == "private_material":
                raise HistoryPrivacyError(f"{name} must not contain secrets or private material")
            _reject_forbidden_keys(item, name=name)
        return
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray, memoryview)):
        for item in value:
            _reject_forbidden_keys(item, name=name)


def _require_nonempty(value: Any, *, field_name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise HistoryError(f"{field_name} is required")
    return text


def _require_nonneg_int(value: Any, *, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise HistoryError(f"{field_name} must be a non-negative int")
    return value


def _require_pos_int(value: Any, *, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise HistoryError(f"{field_name} must be a positive int")
    return value


def _require_identity(value: Any, *, field_name: str) -> str:
    text = _require_nonempty(value, field_name=field_name)
    if _SHA256_RE.fullmatch(text) or _ID_RE.fullmatch(text):
        return text
    raise HistoryError(f"{field_name} is not a permitted identity")


def _require_sha256(value: Any, *, field_name: str) -> str:
    text = _require_nonempty(value, field_name=field_name)
    if not _SHA256_RE.fullmatch(text):
        raise HistoryError(f"{field_name} must be sha256:<64-hex>")
    return text


def _json_size(payload: Any) -> int:
    return len(_canonical_json(payload).encode("utf-8"))


_REMOTE_FORBIDDEN_KEYS: Final[frozenset[str]] = frozenset(
    {
        "sql",
        "raw_sql",
        "query",
        "attach",
        "catalog_path",
        "catalog_file",
        "catalog_metadata_path",
        "companion_registry_path",
        "control_database_path",
        "control_database_paths",
        "database_path",
        "lock_path",
        "owner_lock_path",
        "token",
        "auth_token",
        "endpoint_token",
        "capability_secret",
    }
)


def _reject_remote_bypass_fields(value: Any, *, name: str) -> None:
    """Keep paths, arbitrary SQL, and reusable credentials off Quack payloads."""

    if isinstance(value, Mapping):
        for raw_key, item in value.items():
            key = _normalize_key(raw_key)
            if key in _REMOTE_FORBIDDEN_KEYS or _key_is_forbidden(key) is not None:
                raise HistoryTransportError(
                    f"{name} contains forbidden direct-access field {raw_key!r}"
                )
            _reject_remote_bypass_fields(item, name=name)
        return
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray, memoryview)):
        for item in value:
            _reject_remote_bypass_fields(item, name=name)


def _freeze_mapping(value: Mapping[str, Any] | None) -> Mapping[str, Any]:
    return MappingProxyType(dict(value or {}))


def _authority_denied(action: str) -> None:
    raise HistoryAuthorityError(
        f"DuckLake projection cannot {action}; current claims, leases, "
        "fences and merge authority remain on the DuckDB/Quack owner"
    )


@dataclass(frozen=True, slots=True)
class HistoryCursor:
    """Authoritative DuckDB outbox cursor. Missing cursors fail closed."""

    outbox_ordinal: int
    owner_epoch: int
    fence: int
    source_digest: str
    owner_id: str = ""
    shard_id: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "outbox_ordinal",
            _require_nonneg_int(self.outbox_ordinal, field_name="outbox_ordinal"),
        )
        object.__setattr__(
            self,
            "owner_epoch",
            _require_pos_int(self.owner_epoch, field_name="owner_epoch"),
        )
        object.__setattr__(self, "fence", _require_pos_int(self.fence, field_name="fence"))
        digest = _require_nonempty(self.source_digest, field_name="source_digest")
        if not digest.startswith("sha256:"):
            if len(digest) == 64 and all(c in "0123456789abcdefABCDEF" for c in digest):
                digest = f"sha256:{digest.lower()}"
            else:
                raise HistoryCursorError("source_digest must be sha256:<64-hex>")
        if not _SHA256_RE.fullmatch(digest):
            raise HistoryCursorError("source_digest must be sha256:<64-hex>")
        object.__setattr__(self, "source_digest", digest)
        object.__setattr__(self, "owner_id", str(self.owner_id or "").strip())
        object.__setattr__(self, "shard_id", str(self.shard_id or "").strip())

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "schema": HISTORY_CURSOR_SCHEMA,
                "outbox_ordinal": self.outbox_ordinal,
                "owner_epoch": self.owner_epoch,
                "fence": self.fence,
                "source_digest": self.source_digest,
                "owner_id": self.owner_id,
                "shard_id": self.shard_id,
            }
        )

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any] | None) -> HistoryCursor:
        if value is None:
            raise HistoryCursorError("authoritative outbox cursor is missing")
        if not isinstance(value, Mapping):
            raise HistoryCursorError("outbox cursor must be an object")
        if not value:
            raise HistoryCursorError("authoritative outbox cursor is missing")
        return cls(
            outbox_ordinal=value.get("outbox_ordinal"),  # type: ignore[arg-type]
            owner_epoch=value.get("owner_epoch"),  # type: ignore[arg-type]
            fence=value.get("fence"),  # type: ignore[arg-type]
            source_digest=str(value.get("source_digest") or ""),
            owner_id=str(value.get("owner_id") or ""),
            shard_id=str(value.get("shard_id") or ""),
        )


def _coerce_cursor(cursor: HistoryCursor | Mapping[str, Any] | None) -> HistoryCursor:
    if cursor is None:
        raise HistoryCursorError("authoritative outbox cursor is missing")
    if isinstance(cursor, HistoryCursor):
        return cursor
    if isinstance(cursor, Mapping):
        return HistoryCursor.from_mapping(cursor)
    raise HistoryCursorError("authoritative outbox cursor is missing")


@dataclass(frozen=True, slots=True)
class HistoryEvent:
    """One privacy-safe projected history record."""

    event_id: str
    kind: str
    sequence: int
    identities: Mapping[str, str]
    payload: Mapping[str, Any] = MappingProxyType({})

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "event_id", _require_identity(self.event_id, field_name="event_id")
        )
        kind = _require_nonempty(self.kind, field_name="kind")
        if kind not in EVENT_KINDS:
            raise HistoryError(f"unknown history event kind {kind!r}")
        object.__setattr__(self, "kind", kind)
        object.__setattr__(
            self, "sequence", _require_nonneg_int(self.sequence, field_name="sequence")
        )
        identities = {
            _require_nonempty(key, field_name="identity key"): _require_identity(
                value, field_name=str(key)
            )
            for key, value in dict(self.identities or {}).items()
        }
        object.__setattr__(self, "identities", MappingProxyType(identities))
        payload = dict(self.payload or {})
        _reject_forbidden_keys(payload, name="history event")
        _reject_forbidden_keys(identities, name="history event identities")
        object.__setattr__(self, "payload", _freeze_mapping(payload))

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "schema": HISTORY_EVENT_SCHEMA,
                "event_id": self.event_id,
                "kind": self.kind,
                "sequence": self.sequence,
                "identities": dict(self.identities),
                "payload": dict(self.payload),
            }
        )


@dataclass(frozen=True, slots=True)
class HistorySnapshot:
    """Immutable snapshot bound to an outbox cursor and epoch."""

    snapshot_id: str
    epoch_id: str
    cursor: HistoryCursor
    content_digest: str
    lineage: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.cursor, HistoryCursor):
            raise HistoryError("snapshot cursor must be HistoryCursor")
        object.__setattr__(
            self,
            "snapshot_id",
            _require_identity(self.snapshot_id, field_name="snapshot_id"),
        )
        object.__setattr__(
            self, "epoch_id", _require_identity(self.epoch_id, field_name="epoch_id")
        )
        digest = _require_nonempty(self.content_digest, field_name="content_digest")
        if not _SHA256_RE.fullmatch(digest):
            raise HistoryError("content_digest must be sha256:<64-hex>")
        object.__setattr__(self, "content_digest", digest)
        object.__setattr__(
            self,
            "lineage",
            tuple(_require_identity(item, field_name="lineage") for item in self.lineage),
        )

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "schema": HISTORY_SNAPSHOT_SCHEMA,
                "snapshot_id": self.snapshot_id,
                "epoch_id": self.epoch_id,
                "cursor": dict(self.cursor.as_mapping()),
                "content_digest": self.content_digest,
                "lineage": list(self.lineage),
            }
        )


@dataclass(frozen=True, slots=True)
class HistoryEpoch:
    """Immutable epoch bundle. Never current coordination authority."""

    epoch_id: str
    cursor: HistoryCursor
    events: tuple[HistoryEvent, ...]
    snapshot: HistorySnapshot
    lineage: tuple[str, ...]
    benchmarks: tuple[Mapping[str, Any], ...]
    recovery_manifest: Mapping[str, Any]
    content_digest: str
    grants_current_authority: bool = False

    def __post_init__(self) -> None:
        if self.grants_current_authority:
            _authority_denied("grant current authority")
        object.__setattr__(self, "grants_current_authority", False)
        object.__setattr__(
            self, "epoch_id", _require_identity(self.epoch_id, field_name="epoch_id")
        )
        if not isinstance(self.cursor, HistoryCursor):
            raise HistoryError("epoch cursor must be HistoryCursor")
        if not isinstance(self.snapshot, HistorySnapshot):
            raise HistoryError("epoch snapshot must be HistorySnapshot")
        if self.snapshot.epoch_id != self.epoch_id:
            raise HistoryError("snapshot epoch_id must match the epoch")
        events = tuple(self.events)
        seen: set[str] = set()
        for event in events:
            if not isinstance(event, HistoryEvent):
                raise HistoryError("epoch events must be HistoryEvent records")
            if event.event_id in seen:
                raise HistoryError(f"duplicate history event {event.event_id!r}")
            seen.add(event.event_id)
        object.__setattr__(self, "events", events)
        object.__setattr__(
            self,
            "lineage",
            tuple(_require_identity(item, field_name="lineage") for item in self.lineage),
        )
        object.__setattr__(
            self,
            "benchmarks",
            tuple(_freeze_mapping(item) for item in self.benchmarks),
        )
        manifest = dict(self.recovery_manifest or {})
        _reject_forbidden_keys(manifest, name="recovery manifest")
        object.__setattr__(self, "recovery_manifest", _freeze_mapping(manifest))
        digest = _require_nonempty(self.content_digest, field_name="content_digest")
        if not _SHA256_RE.fullmatch(digest):
            raise HistoryError("content_digest must be sha256:<64-hex>")
        object.__setattr__(self, "content_digest", digest)

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "schema": HISTORY_EPOCH_SCHEMA,
                "history_schema": HISTORY_SCHEMA,
                "epoch_id": self.epoch_id,
                "cursor": dict(self.cursor.as_mapping()),
                "events": [dict(event.as_mapping()) for event in self.events],
                "snapshot": dict(self.snapshot.as_mapping()),
                "lineage": list(self.lineage),
                "benchmarks": [dict(item) for item in self.benchmarks],
                "recovery_manifest": dict(self.recovery_manifest),
                "content_digest": self.content_digest,
                "grants_current_authority": False,
                "authoritative": False,
            }
        )

    def grant_claim(self, *args: Any, **kwargs: Any) -> None:
        del args, kwargs
        _authority_denied("grant claims")

    def revoke_claim(self, *args: Any, **kwargs: Any) -> None:
        del args, kwargs
        _authority_denied("revoke claims")

    def grant_lease(self, *args: Any, **kwargs: Any) -> None:
        del args, kwargs
        _authority_denied("grant leases")

    def revoke_lease(self, *args: Any, **kwargs: Any) -> None:
        del args, kwargs
        _authority_denied("revoke leases")

    def grant_fence(self, *args: Any, **kwargs: Any) -> None:
        del args, kwargs
        _authority_denied("grant fences")

    def revoke_fence(self, *args: Any, **kwargs: Any) -> None:
        del args, kwargs
        _authority_denied("revoke fences")

    def grant_merge_authority(self, *args: Any, **kwargs: Any) -> None:
        del args, kwargs
        _authority_denied("grant merge authority")

    def revoke_merge_authority(self, *args: Any, **kwargs: Any) -> None:
        del args, kwargs
        _authority_denied("revoke merge authority")


def _coerce_event(raw: HistoryEvent | Mapping[str, Any], *, sequence: int) -> HistoryEvent:
    if isinstance(raw, HistoryEvent):
        return raw
    if not isinstance(raw, Mapping):
        raise HistoryError("history events must be objects")
    _reject_forbidden_keys(raw, name="history event")
    identities = dict(raw.get("identities") or {})
    for key in ("run_id", "task_id", "attempt_id", "fence_token", "fence_id"):
        if key in raw and key not in identities and raw.get(key):
            identities[key] = str(raw[key])
    event_id = str(raw.get("event_id") or raw.get("identity") or "")
    kind = str(raw.get("kind") or "event")
    payload = dict(raw.get("payload") or {})
    seq = raw.get("sequence", sequence)
    if not event_id:
        event_id = _digest_of(
            {"kind": kind, "sequence": seq, "identities": identities, "payload": payload}
        )
    return HistoryEvent(
        event_id=event_id,
        kind=kind,
        sequence=int(seq),
        identities=identities,
        payload=payload,
    )


def _split_events(
    events: Sequence[HistoryEvent | Mapping[str, Any]],
) -> tuple[
    tuple[HistoryEvent, ...],
    tuple[str, ...],
    tuple[Mapping[str, Any], ...],
    Mapping[str, Any],
]:
    history: list[HistoryEvent] = []
    lineage: list[str] = []
    benchmarks: list[Mapping[str, Any]] = []
    recovery: dict[str, Any] = {}
    for index, raw in enumerate(events):
        event = _coerce_event(raw, sequence=index)
        if event.kind == "lineage":
            parent = str(event.payload.get("parent_epoch_id") or event.event_id)
            lineage.append(parent)
        elif event.kind == "benchmark":
            benchmarks.append(event.payload or {"benchmark_id": event.event_id})
        elif event.kind == "recovery":
            recovery = dict(event.payload)
            recovery.setdefault("manifest_id", event.event_id)
        history.append(event)
    return tuple(history), tuple(lineage), tuple(benchmarks), MappingProxyType(recovery)


class HistoryProjector:
    """In-process fail-closed projector. Duplicate epoch ids fail closed."""

    def __init__(self) -> None:
        self._epoch_ids: set[str] = set()
        self._epochs: dict[str, HistoryEpoch] = {}

    @property
    def epoch_ids(self) -> frozenset[str]:
        return frozenset(self._epoch_ids)

    def project_outbox(
        self,
        cursor: HistoryCursor | Mapping[str, Any] | None,
        events: Sequence[HistoryEvent | Mapping[str, Any]] | None = None,
        *,
        epoch_id: str = "",
    ) -> HistoryEpoch:
        bound = _coerce_cursor(cursor)
        rows = tuple(events or ())
        history, lineage, benchmarks, recovery = _split_events(rows)
        claimed: set[str] = set()
        for raw in rows:
            if isinstance(raw, Mapping) and raw.get("epoch_id"):
                claimed.add(str(raw["epoch_id"]).strip())
        if len(claimed) > 1:
            raise DuplicateEpochError("events specify conflicting epoch ids")
        body = {
            "cursor": dict(bound.as_mapping()),
            "events": [dict(event.as_mapping()) for event in history],
        }
        digest = _digest_of(body)
        resolved = str(epoch_id or (next(iter(claimed)) if claimed else digest)).strip()
        if not resolved:
            raise HistoryError("epoch_id is required")
        if resolved in self._epoch_ids:
            raise DuplicateEpochError(f"duplicate epoch id {resolved!r}")
        snapshot = HistorySnapshot(
            snapshot_id=_digest_of({"epoch_id": resolved, "digest": digest}),
            epoch_id=resolved,
            cursor=bound,
            content_digest=digest,
            lineage=lineage,
        )
        if not recovery:
            recovery = MappingProxyType(
                {
                    "manifest_id": _digest_of({"recovery": resolved}),
                    "epoch_id": resolved,
                    "outbox_ordinal": bound.outbox_ordinal,
                    "authoritative": False,
                }
            )
        epoch = HistoryEpoch(
            epoch_id=resolved,
            cursor=bound,
            events=history,
            snapshot=snapshot,
            lineage=lineage,
            benchmarks=benchmarks,
            recovery_manifest=recovery,
            content_digest=digest,
            grants_current_authority=False,
        )
        self._epoch_ids.add(resolved)
        self._epochs[resolved] = epoch
        return epoch


def project_outbox(
    cursor: HistoryCursor | Mapping[str, Any] | None,
    events: Sequence[HistoryEvent | Mapping[str, Any]] | None = None,
    *,
    epoch_id: str = "",
    projector: HistoryProjector | None = None,
) -> HistoryEpoch:
    """Project an authoritative outbox cursor into an immutable epoch bundle."""

    owner = projector if projector is not None else HistoryProjector()
    return owner.project_outbox(cursor, events, epoch_id=epoch_id)


@dataclass(frozen=True, slots=True)
class HistoryProjectionLimits:
    """Hard projection bounds. Callers may lower but never raise them."""

    max_events: int = MAX_HISTORY_BATCH_EVENTS
    max_bytes: int = MAX_HISTORY_BATCH_BYTES
    timeout_seconds: int = MAX_HISTORY_BATCH_SECONDS

    def __post_init__(self) -> None:
        events = _require_pos_int(self.max_events, field_name="max_events")
        byte_count = _require_pos_int(self.max_bytes, field_name="max_bytes")
        seconds = _require_pos_int(self.timeout_seconds, field_name="timeout_seconds")
        if events > MAX_HISTORY_BATCH_EVENTS:
            raise HistoryActivationError(
                f"max_events exceeds the hard {MAX_HISTORY_BATCH_EVENTS} row bound"
            )
        if byte_count > MAX_HISTORY_BATCH_BYTES:
            raise HistoryActivationError(
                f"max_bytes exceeds the hard {MAX_HISTORY_BATCH_BYTES} byte bound"
            )
        if seconds > MAX_HISTORY_BATCH_SECONDS:
            raise HistoryActivationError(
                f"timeout_seconds exceeds the hard {MAX_HISTORY_BATCH_SECONDS}s bound"
            )

    def as_mapping(self) -> Mapping[str, int]:
        return MappingProxyType(
            {
                "max_events": self.max_events,
                "max_bytes": self.max_bytes,
                "timeout_seconds": self.timeout_seconds,
            }
        )


@dataclass(frozen=True, slots=True)
class HistoryOutboxBatch:
    """One committed batch returned by the sole control owner through Quack.

    ``control_receipt_cid`` is supplied by that owner. This package validates
    its shape and all content joins, but deliberately does not mint, sign, or
    claim to verify control-plane authority.
    """

    batch_id: str
    previous_outbox_ordinal: int
    cursor: HistoryCursor
    events: tuple[HistoryEvent | Mapping[str, Any], ...]
    batch_digest: str
    control_receipt_cid: str
    committed: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "batch_id", _require_identity(self.batch_id, field_name="batch_id")
        )
        before = _require_nonneg_int(
            self.previous_outbox_ordinal,
            field_name="previous_outbox_ordinal",
        )
        if not isinstance(self.cursor, HistoryCursor):
            raise HistoryCursorError("outbox batch cursor must be HistoryCursor")
        if self.cursor.outbox_ordinal <= before:
            raise HistoryContinuityError("committed outbox batch must advance its previous ordinal")
        rows = tuple(self.events)
        if not rows:
            raise HistoryContinuityError("committed outbox batch must not be empty")
        if len(rows) > MAX_HISTORY_BATCH_EVENTS:
            raise HistoryError(f"outbox batch exceeds {MAX_HISTORY_BATCH_EVENTS} events")
        _reject_forbidden_keys(rows, name="outbox batch")
        body = {
            "schema": HISTORY_OUTBOX_BATCH_SCHEMA,
            "batch_id": self.batch_id,
            "previous_outbox_ordinal": before,
            "cursor": dict(self.cursor.as_mapping()),
            "events": [
                dict(item.as_mapping()) if isinstance(item, HistoryEvent) else dict(item)
                for item in rows
            ],
            "committed": True,
        }
        if _json_size(body) > MAX_HISTORY_BATCH_BYTES:
            raise HistoryError(f"outbox batch exceeds {MAX_HISTORY_BATCH_BYTES} bytes")
        expected = _digest_of(body)
        supplied = _require_sha256(self.batch_digest, field_name="batch_digest")
        if supplied != expected:
            raise HistoryReceiptError("outbox batch digest does not match its content")
        if self.committed is not True:
            raise HistoryReceiptError("only owner-committed outbox batches may be projected")
        object.__setattr__(self, "events", rows)
        object.__setattr__(self, "batch_digest", supplied)
        object.__setattr__(
            self,
            "control_receipt_cid",
            _require_sha256(self.control_receipt_cid, field_name="control_receipt_cid"),
        )
        object.__setattr__(self, "committed", True)

    @classmethod
    def build(
        cls,
        *,
        batch_id: str,
        previous_outbox_ordinal: int,
        cursor: HistoryCursor,
        events: Sequence[HistoryEvent | Mapping[str, Any]],
        control_receipt_cid: str,
    ) -> HistoryOutboxBatch:
        """Build test/adapter content; never creates the control receipt CID."""

        rows = tuple(events)
        body = {
            "schema": HISTORY_OUTBOX_BATCH_SCHEMA,
            "batch_id": batch_id,
            "previous_outbox_ordinal": previous_outbox_ordinal,
            "cursor": dict(cursor.as_mapping()),
            "events": [
                dict(item.as_mapping()) if isinstance(item, HistoryEvent) else dict(item)
                for item in rows
            ],
            "committed": True,
        }
        return cls(
            batch_id=batch_id,
            previous_outbox_ordinal=previous_outbox_ordinal,
            cursor=cursor,
            events=rows,
            batch_digest=_digest_of(body),
            control_receipt_cid=control_receipt_cid,
            committed=True,
        )

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "schema": HISTORY_OUTBOX_BATCH_SCHEMA,
                "batch_id": self.batch_id,
                "previous_outbox_ordinal": self.previous_outbox_ordinal,
                "cursor": dict(self.cursor.as_mapping()),
                "events": [
                    dict(item.as_mapping()) if isinstance(item, HistoryEvent) else dict(item)
                    for item in self.events
                ],
                "batch_digest": self.batch_digest,
                "control_receipt_cid": self.control_receipt_cid,
                "committed": True,
                "authoritative": False,
            }
        )


@dataclass(frozen=True, slots=True)
class HistoryLakeOwnerIdentity:
    """Private, separately fenced identity for the one DuckLake owner."""

    owner_id: str
    catalog_id: str
    endpoint_id: str
    catalog_metadata_path: str
    companion_registry_path: str
    owner_lock_path: str
    owner_generation: int
    fencing_epoch: int
    control_database_paths: tuple[str, ...]
    generation_namespace: str = "eaaef-history-ducklake-owner"
    fence_namespace: str = "eaaef-history-ducklake-fence"

    def __post_init__(self) -> None:
        for field_name in ("owner_id", "catalog_id", "endpoint_id"):
            object.__setattr__(
                self,
                field_name,
                _require_identity(getattr(self, field_name), field_name=field_name),
            )
        object.__setattr__(
            self,
            "owner_generation",
            _require_pos_int(self.owner_generation, field_name="owner_generation"),
        )
        object.__setattr__(
            self,
            "fencing_epoch",
            _require_pos_int(self.fencing_epoch, field_name="fencing_epoch"),
        )
        generation_namespace = _require_identity(
            self.generation_namespace, field_name="generation_namespace"
        )
        fence_namespace = _require_identity(self.fence_namespace, field_name="fence_namespace")
        if generation_namespace == fence_namespace:
            raise HistoryActivationError(
                "DuckLake generation and fence namespaces must be distinct"
            )
        if "control" in generation_namespace.lower() or "control" in fence_namespace.lower():
            raise HistoryActivationError(
                "DuckLake generation/fence namespaces must be separate from control"
            )
        object.__setattr__(self, "generation_namespace", generation_namespace)
        object.__setattr__(self, "fence_namespace", fence_namespace)

        private_paths = {
            "catalog_metadata_path": self.catalog_metadata_path,
            "companion_registry_path": self.companion_registry_path,
            "owner_lock_path": self.owner_lock_path,
        }
        normalized: dict[str, str] = {}
        for name, raw_path in private_paths.items():
            text = _require_nonempty(raw_path, field_name=name)
            path = Path(text).expanduser().resolve(strict=False)
            if not path.is_absolute():  # pragma: no cover - resolve is absolute
                raise HistoryActivationError(f"{name} must be absolute")
            normalized[name] = str(path)
        if len(set(normalized.values())) != len(normalized):
            raise HistoryActivationError(
                "DuckLake catalog, companion registry, and owner lock paths must differ"
            )
        control_paths = tuple(
            str(
                Path(_require_nonempty(item, field_name="control_database_path"))
                .expanduser()
                .resolve(strict=False)
            )
            for item in self.control_database_paths
        )
        if not control_paths:
            raise HistoryActivationError(
                "control database paths are required only to prove physical separation"
            )
        overlap = set(normalized.values()).intersection(control_paths)
        if overlap:
            raise HistoryActivationError(
                "DuckLake catalog/registry/lock must not reuse a control database path"
            )
        for name, value in normalized.items():
            object.__setattr__(self, name, value)
        object.__setattr__(self, "control_database_paths", control_paths)

    @property
    def binding_digest(self) -> str:
        return _digest_of(
            {
                "owner_id": self.owner_id,
                "catalog_id": self.catalog_id,
                "endpoint_id": self.endpoint_id,
                "catalog_metadata_path": self.catalog_metadata_path,
                "companion_registry_path": self.companion_registry_path,
                "owner_lock_path": self.owner_lock_path,
                "owner_generation": self.owner_generation,
                "fencing_epoch": self.fencing_epoch,
                "generation_namespace": self.generation_namespace,
                "fence_namespace": self.fence_namespace,
            }
        )

    def as_public_mapping(self) -> Mapping[str, Any]:
        """Return identity evidence without paths or reusable credentials."""

        return MappingProxyType(
            {
                "schema": HISTORY_OWNER_IDENTITY_SCHEMA,
                "owner_id": self.owner_id,
                "catalog_id": self.catalog_id,
                "endpoint_id": self.endpoint_id,
                "owner_generation": self.owner_generation,
                "fencing_epoch": self.fencing_epoch,
                "generation_namespace": self.generation_namespace,
                "fence_namespace": self.fence_namespace,
                "binding_digest": self.binding_digest,
                "database_is_separate_from_control": True,
                "lock_is_separate_from_control": True,
                "authoritative": False,
            }
        )


_ACTIVE_HISTORY_OWNER_LOCKS: dict[str, tuple[str, int]] = {}
_ACTIVE_HISTORY_OWNER_LOCKS_GUARD = threading.RLock()


class ExclusiveHistoryOwnerLease:
    """Cross-process, non-blocking lease for exactly one lake owner.

    The lock is dedicated to the history catalog. It is neither the control
    DuckDB lock nor a substitute for DuckDB's native catalog-file lock; the
    backend capability must attest that native lock independently.
    """

    def __init__(self, identity: HistoryLakeOwnerIdentity) -> None:
        if not isinstance(identity, HistoryLakeOwnerIdentity):
            raise HistoryActivationError("exclusive owner lease requires HistoryLakeOwnerIdentity")
        self.identity = identity
        self._fd: int | None = None

    @property
    def held(self) -> bool:
        return self._fd is not None

    def acquire(self) -> ExclusiveHistoryOwnerLease:
        if self._fd is not None:
            return self
        path = self.identity.owner_lock_path
        with _ACTIVE_HISTORY_OWNER_LOCKS_GUARD:
            incumbent = _ACTIVE_HISTORY_OWNER_LOCKS.get(path)
            if incumbent is not None:
                raise HistoryContentionError(
                    "DuckLake history owner lock is already held in this process"
                )
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
            try:
                import fcntl

                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except (BlockingIOError, OSError) as exc:
                os.close(fd)
                raise HistoryContentionError(
                    "DuckLake history owner lock is already held by another process"
                ) from exc
            _ACTIVE_HISTORY_OWNER_LOCKS[path] = (
                self.identity.owner_id,
                os.getpid(),
            )
            self._fd = fd
        return self

    def release(self) -> None:
        fd = self._fd
        if fd is None:
            return
        with _ACTIVE_HISTORY_OWNER_LOCKS_GUARD:
            try:
                import fcntl

                fcntl.flock(fd, fcntl.LOCK_UN)
            finally:
                os.close(fd)
                self._fd = None
                incumbent = _ACTIVE_HISTORY_OWNER_LOCKS.get(self.identity.owner_lock_path)
                if incumbent == (self.identity.owner_id, os.getpid()):
                    _ACTIVE_HISTORY_OWNER_LOCKS.pop(self.identity.owner_lock_path, None)

    def __enter__(self) -> ExclusiveHistoryOwnerLease:
        return self.acquire()

    def __exit__(self, *exc_info: object) -> None:
        del exc_info
        self.release()


@dataclass(frozen=True, slots=True)
class HistoryActivationDecision:
    """Non-authoritative preflight result for the two independent Quack planes."""

    activated: bool
    blockers: tuple[str, ...]
    control_capability_cid: str = ""
    lake_capability_cid: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.activated, bool):
            raise HistoryActivationError("activated must be boolean")
        blockers = tuple(str(item).strip() for item in self.blockers if str(item).strip())
        if self.activated and blockers:
            raise HistoryActivationError("history projection cannot activate while blockers remain")
        if self.activated:
            _require_sha256(
                self.control_capability_cid,
                field_name="control_capability_cid",
            )
            _require_sha256(
                self.lake_capability_cid,
                field_name="lake_capability_cid",
            )
        object.__setattr__(self, "activated", self.activated and not blockers)
        object.__setattr__(self, "blockers", blockers)

    def require_activated(self) -> None:
        if not self.activated:
            reason = ",".join(self.blockers) or "projection_not_admitted"
            raise HistoryActivationError(
                f"DuckLake history projection is disabled fail-closed: {reason}"
            )

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "schema": HISTORY_ACTIVATION_SCHEMA,
                "activated": self.activated,
                "blockers": list(self.blockers),
                "control_capability_cid": self.control_capability_cid,
                "lake_capability_cid": self.lake_capability_cid,
                "control_plane": "one_fenced_duckdb_quack_owner",
                "history_plane": "one_separate_ducklake_quack_owner",
                "projection_is_authority": False,
                "ducklake_grants_current_authority": False,
            }
        )


def _capability_operations(value: Mapping[str, Any]) -> frozenset[str]:
    operations = value.get("operations")
    if not isinstance(operations, Sequence) or isinstance(
        operations, (str, bytes, bytearray, memoryview)
    ):
        return frozenset()
    return frozenset(str(item) for item in operations)


def _capability_cid_matches(value: Mapping[str, Any]) -> bool:
    supplied = str(value.get("capability_cid") or "")
    if not _SHA256_RE.fullmatch(supplied):
        return False
    body = dict(value)
    body.pop("capability_cid", None)
    return supplied == _digest_of(body)


def evaluate_history_activation(
    control_capability: Mapping[str, Any] | None,
    lake_capability: Mapping[str, Any] | None,
) -> HistoryActivationDecision:
    """Require the exact two-owner, Quack-only, history-only topology.

    The current EAAEF control gateway has no history outbox/cursor operations,
    so passing ``None`` (the production default) returns a typed held decision.
    Capability documents are provided by their respective owners; this
    function neither fabricates signatures nor promotes either document.
    """

    blockers: list[str] = []
    control = dict(control_capability or {})
    lake = dict(lake_capability or {})
    if not control:
        blockers.append("typed_control_outbox_cursor_seam_unavailable")
    else:
        try:
            _reject_remote_bypass_fields(control, name="control capability")
        except HistoryTransportError:
            blockers.append("control_capability_exposes_direct_access")
        if control.get("schema") != HISTORY_CONTROL_SEAM_CAPABILITY_SCHEMA:
            blockers.append("control_seam_schema_mismatch")
        if control.get("available") is not True:
            blockers.append("control_seam_unavailable")
        if control.get("transport") != "quack":
            blockers.append("control_transport_not_quack")
        if control.get("authority") != "one_fenced_duckdb_quack_owner":
            blockers.append("control_owner_authority_mismatch")
        if control.get("committed_only") is not True:
            blockers.append("control_outbox_not_committed_only")
        if control.get("owner_verifies_signed_envelopes") is not True:
            blockers.append("control_signed_envelope_verification_missing")
        if control.get("direct_database_access") is not False:
            blockers.append("control_direct_database_access_not_denied")
        if not REQUIRED_CONTROL_HISTORY_OPERATIONS.issubset(_capability_operations(control)):
            blockers.append("typed_control_outbox_cursor_operations_missing")

    if not lake:
        blockers.append("ducklake_quack_owner_unavailable")
    else:
        try:
            _reject_remote_bypass_fields(lake, name="lake capability")
        except HistoryTransportError:
            blockers.append("lake_capability_exposes_direct_access")
        if lake.get("schema") != HISTORY_LAKE_CAPABILITY_SCHEMA:
            blockers.append("lake_capability_schema_mismatch")
        if lake.get("available") is not True:
            blockers.append("lake_owner_unavailable")
        if lake.get("transport") != "quack":
            blockers.append("lake_transport_not_quack")
        if lake.get("database_kind") != "ducklake":
            blockers.append("lake_database_kind_mismatch")
        if lake.get("database_role") != "history_projection_only":
            blockers.append("lake_database_role_mismatch")
        if str(lake.get("duckdb_version") or "") != REQUIRED_DUCKDB_VERSION_TEXT:
            blockers.append("lake_duckdb_profile_mismatch")
        extension_builds = lake.get("extension_builds")
        if not isinstance(extension_builds, Mapping) or dict(extension_builds) != {
            "quack": PINNED_QUACK_EXTENSION_BUILD,
            "ducklake": PINNED_DUCKLAKE_EXTENSION_BUILD,
            "httpfs": PINNED_HTTPFS_EXTENSION_BUILD,
        }:
            blockers.append("lake_extension_profile_mismatch")
        if lake.get("automatic_extension_install") is not False:
            blockers.append("lake_automatic_extension_install_not_disabled")
        if lake.get("automatic_extension_load") is not False:
            blockers.append("lake_automatic_extension_load_not_disabled")
        if lake.get("automatic_catalog_migration") is not False:
            blockers.append("lake_automatic_catalog_migration_not_disabled")
        if lake.get("safe_attach_options") != {
            "CREATE_IF_NOT_EXISTS": False,
            "OVERRIDE_DATA_PATH": False,
            "AUTOMATIC_MIGRATION": False,
        }:
            blockers.append("lake_safe_attach_options_mismatch")
        for key, reason in (
            ("exclusive_owner", "lake_exclusive_owner_missing"),
            ("native_duckdb_file_lock", "lake_native_file_lock_missing"),
            ("separate_from_control_database", "lake_control_database_overlap"),
            ("separate_owner_lock", "lake_control_lock_overlap"),
            ("separate_generation_fence", "lake_control_fence_overlap"),
            ("remote_clients_quack_only", "lake_clients_not_quack_only"),
        ):
            if lake.get(key) is not True:
                blockers.append(reason)
        if lake.get("arbitrary_sql_allowed") is not False:
            blockers.append("lake_arbitrary_sql_not_denied")
        if lake.get("control_database_opened") is not False:
            blockers.append("lake_owner_opens_control_database")
        if lake.get("authoritative") is not False:
            blockers.append("ducklake_claims_current_authority")
        if not REQUIRED_LAKE_HISTORY_OPERATIONS.issubset(_capability_operations(lake)):
            blockers.append("typed_lake_history_operations_missing")
        for key in ("owner_generation", "fencing_epoch"):
            value = lake.get(key)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                blockers.append(f"lake_{key}_missing")
        for key in ("catalog_id", "endpoint_id"):
            if not str(lake.get(key) or "").strip():
                blockers.append(f"lake_{key}_missing")

    control_cid = str(control.get("capability_cid") or "")
    lake_cid = str(lake.get("capability_cid") or "")
    if control and not _capability_cid_matches(control):
        blockers.append("control_capability_cid_mismatch")
    if lake and not _capability_cid_matches(lake):
        blockers.append("lake_capability_cid_mismatch")
    unique = tuple(dict.fromkeys(blockers))
    return HistoryActivationDecision(
        activated=not unique,
        blockers=unique,
        control_capability_cid=control_cid,
        lake_capability_cid=lake_cid,
    )


class HistoryControlQuackGateway(Protocol):
    """Typed control-owner seam; implementations retain all credentials."""

    def capability(self) -> Mapping[str, Any]: ...

    def projection_cursor(self) -> HistoryCursor | Mapping[str, Any] | None: ...

    def read_committed_history(
        self,
        *,
        after_outbox_ordinal: int,
        limits: HistoryProjectionLimits,
    ) -> HistoryOutboxBatch | None: ...

    def record_projection_cursor(self, receipt: Mapping[str, Any]) -> Mapping[str, Any]: ...


@dataclass(frozen=True, slots=True)
class HistoryProjectionReceipt:
    """Observation returned by an actual lake append/replay through Quack."""

    operation_id: str
    batch_id: str
    batch_digest: str
    control_receipt_cid: str
    epoch_id: str
    cursor: HistoryCursor
    content_digest: str
    lake_snapshot: int
    owner_generation: int
    fencing_epoch: int
    catalog_id: str
    endpoint_id: str
    row_count: int
    replayed: bool
    receipt_digest: str

    def __post_init__(self) -> None:
        for field_name in (
            "operation_id",
            "batch_id",
            "epoch_id",
            "catalog_id",
            "endpoint_id",
        ):
            object.__setattr__(
                self,
                field_name,
                _require_identity(getattr(self, field_name), field_name=field_name),
            )
        if not isinstance(self.cursor, HistoryCursor):
            raise HistoryReceiptError("projection receipt cursor must be HistoryCursor")
        object.__setattr__(
            self,
            "content_digest",
            _require_sha256(self.content_digest, field_name="content_digest"),
        )
        object.__setattr__(
            self,
            "batch_digest",
            _require_sha256(self.batch_digest, field_name="batch_digest"),
        )
        object.__setattr__(
            self,
            "control_receipt_cid",
            _require_sha256(self.control_receipt_cid, field_name="control_receipt_cid"),
        )
        for field_name in (
            "lake_snapshot",
            "owner_generation",
            "fencing_epoch",
            "row_count",
        ):
            object.__setattr__(
                self,
                field_name,
                _require_pos_int(getattr(self, field_name), field_name=field_name),
            )
        expected = _digest_of(self._body_mapping())
        supplied = _require_sha256(self.receipt_digest, field_name="receipt_digest")
        if supplied != expected:
            raise HistoryReceiptError(
                "projection receipt digest does not match the observed append"
            )
        if not isinstance(self.replayed, bool):
            raise HistoryReceiptError("projection receipt replayed must be boolean")
        object.__setattr__(self, "receipt_digest", supplied)

    def _body_mapping(self) -> Mapping[str, Any]:
        return {
            "schema": HISTORY_PROJECTION_RECEIPT_SCHEMA,
            "operation_id": self.operation_id,
            "batch_id": self.batch_id,
            "batch_digest": self.batch_digest,
            "control_receipt_cid": self.control_receipt_cid,
            "epoch_id": self.epoch_id,
            "cursor": dict(self.cursor.as_mapping()),
            "content_digest": self.content_digest,
            "lake_snapshot": self.lake_snapshot,
            "owner_generation": self.owner_generation,
            "fencing_epoch": self.fencing_epoch,
            "catalog_id": self.catalog_id,
            "endpoint_id": self.endpoint_id,
            "row_count": self.row_count,
            "replayed": bool(self.replayed),
            "committed": True,
            "authoritative": False,
            "grants_current_authority": False,
            "control_cursor_recorded": False,
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> HistoryProjectionReceipt:
        if not isinstance(value, Mapping):
            raise HistoryReceiptError("projection receipt must be an object")
        if value.get("schema") != HISTORY_PROJECTION_RECEIPT_SCHEMA:
            raise HistoryReceiptError("projection receipt schema mismatch")
        if value.get("committed") is not True:
            raise HistoryReceiptError("projection receipt is not committed")
        if value.get("authoritative") is not False:
            raise HistoryAuthorityError("DuckLake receipt claims current authority")
        if value.get("grants_current_authority") is not False:
            raise HistoryAuthorityError("DuckLake receipt grants current authority")
        if value.get("control_cursor_recorded") is not False:
            raise HistoryReceiptError("lake owner cannot claim the control cursor was recorded")
        cursor = _coerce_cursor(value.get("cursor"))
        return cls(
            operation_id=str(value.get("operation_id") or ""),
            batch_id=str(value.get("batch_id") or ""),
            batch_digest=str(value.get("batch_digest") or ""),
            control_receipt_cid=str(value.get("control_receipt_cid") or ""),
            epoch_id=str(value.get("epoch_id") or ""),
            cursor=cursor,
            content_digest=str(value.get("content_digest") or ""),
            lake_snapshot=value.get("lake_snapshot"),  # type: ignore[arg-type]
            owner_generation=value.get("owner_generation"),  # type: ignore[arg-type]
            fencing_epoch=value.get("fencing_epoch"),  # type: ignore[arg-type]
            catalog_id=str(value.get("catalog_id") or ""),
            endpoint_id=str(value.get("endpoint_id") or ""),
            row_count=value.get("row_count"),  # type: ignore[arg-type]
            replayed=value.get("replayed", False),  # type: ignore[arg-type]
            receipt_digest=str(value.get("receipt_digest") or ""),
        )

    def as_mapping(self) -> Mapping[str, Any]:
        payload = dict(self._body_mapping())
        payload["receipt_digest"] = self.receipt_digest
        return MappingProxyType(payload)

    def grant_claim(self, *args: Any, **kwargs: Any) -> None:
        del args, kwargs
        _authority_denied("grant claims")

    def grant_lease(self, *args: Any, **kwargs: Any) -> None:
        del args, kwargs
        _authority_denied("grant leases")

    def grant_fence(self, *args: Any, **kwargs: Any) -> None:
        del args, kwargs
        _authority_denied("grant fences")

    def grant_merge_authority(self, *args: Any, **kwargs: Any) -> None:
        del args, kwargs
        _authority_denied("grant merge authority")


class HistoryLakeQuackClient:
    """Typed history client with no catalog path, SQL, or reusable token API."""

    def __init__(
        self,
        *,
        endpoint_id: str,
        catalog_id: str,
        owner_generation: int,
        fencing_epoch: int,
        invoke: Callable[[Mapping[str, Any]], Mapping[str, Any]],
    ) -> None:
        self.endpoint_id = _require_identity(endpoint_id, field_name="endpoint_id")
        self.catalog_id = _require_identity(catalog_id, field_name="catalog_id")
        self.owner_generation = _require_pos_int(owner_generation, field_name="owner_generation")
        self.fencing_epoch = _require_pos_int(fencing_epoch, field_name="fencing_epoch")
        if not callable(invoke):
            raise HistoryTransportError("Quack invoke transport is required")
        self._invoke = invoke

    def _request(self, operation: str, payload: Mapping[str, Any]) -> Mapping[str, Any]:
        request = {
            "schema": HISTORY_QUACK_REQUEST_SCHEMA,
            "operation": operation,
            "endpoint_id": self.endpoint_id,
            "catalog_id": self.catalog_id,
            "owner_generation": self.owner_generation,
            "fencing_epoch": self.fencing_epoch,
            "payload": dict(payload),
        }
        _reject_remote_bypass_fields(request, name="history Quack request")
        response = self._invoke(MappingProxyType(request))
        if not isinstance(response, Mapping):
            raise HistoryTransportError("history Quack response must be an object")
        _reject_remote_bypass_fields(response, name="history Quack response")
        return response

    def capability(self) -> Mapping[str, Any]:
        capability = self._request(LAKE_HISTORY_CAPABILITY_OPERATION, {})
        expected = {
            "endpoint_id": self.endpoint_id,
            "catalog_id": self.catalog_id,
            "owner_generation": self.owner_generation,
            "fencing_epoch": self.fencing_epoch,
        }
        if any(capability.get(key) != value for key, value in expected.items()):
            raise HistoryReceiptError(
                "lake capability does not match the bound endpoint generation/fence"
            )
        return capability

    def projection_head(self) -> HistoryProjectionReceipt | None:
        response = self._request(LAKE_HISTORY_CURSOR_OPERATION, {})
        if response.get("operation") != LAKE_HISTORY_CURSOR_OPERATION:
            raise HistoryTransportError("lake cursor response operation mismatch")
        receipt = response.get("receipt")
        if receipt is None:
            return None
        if not isinstance(receipt, Mapping):
            raise HistoryReceiptError("lake cursor receipt must be an object")
        return HistoryProjectionReceipt.from_mapping(receipt)

    def append_epoch(
        self,
        *,
        operation_id: str,
        batch: HistoryOutboxBatch,
        epoch: HistoryEpoch,
        expected_previous_outbox_ordinal: int,
    ) -> HistoryProjectionReceipt:
        if epoch.cursor != batch.cursor:
            raise HistoryContinuityError("epoch cursor differs from outbox batch")
        response = self._request(
            LAKE_HISTORY_APPEND_OPERATION,
            {
                "operation_id": _require_identity(operation_id, field_name="operation_id"),
                "batch_id": batch.batch_id,
                "batch_digest": batch.batch_digest,
                "control_receipt_cid": batch.control_receipt_cid,
                "expected_previous_outbox_ordinal": _require_nonneg_int(
                    expected_previous_outbox_ordinal,
                    field_name="expected_previous_outbox_ordinal",
                ),
                "epoch": dict(epoch.as_mapping()),
            },
        )
        receipt = HistoryProjectionReceipt.from_mapping(response)
        if receipt.operation_id != operation_id:
            raise HistoryReceiptError("lake receipt operation_id mismatch")
        if receipt.batch_id != batch.batch_id:
            raise HistoryReceiptError("lake receipt batch_id mismatch")
        if receipt.batch_digest != batch.batch_digest:
            raise HistoryReceiptError("lake receipt batch digest mismatch")
        if receipt.control_receipt_cid != batch.control_receipt_cid:
            raise HistoryReceiptError("lake receipt control source mismatch")
        if receipt.epoch_id != epoch.epoch_id:
            raise HistoryReceiptError("lake receipt epoch_id mismatch")
        if receipt.cursor != batch.cursor:
            raise HistoryReceiptError("lake receipt cursor mismatch")
        if receipt.content_digest != epoch.content_digest:
            raise HistoryReceiptError("lake receipt content digest mismatch")
        if receipt.owner_generation != self.owner_generation:
            raise HistoryReceiptError("lake receipt owner generation is stale")
        if receipt.fencing_epoch != self.fencing_epoch:
            raise HistoryReceiptError("lake receipt fencing epoch is stale")
        if receipt.catalog_id != self.catalog_id:
            raise HistoryReceiptError("lake receipt catalog identity mismatch")
        if receipt.endpoint_id != self.endpoint_id:
            raise HistoryReceiptError("lake receipt endpoint identity mismatch")
        return receipt


@dataclass(frozen=True, slots=True)
class HistoryProjectionResult:
    """Lake observation plus the distinct control-owner cursor acknowledgement."""

    projection: HistoryProjectionReceipt
    control_ack_receipt_cid: str

    def __post_init__(self) -> None:
        if not isinstance(self.projection, HistoryProjectionReceipt):
            raise HistoryReceiptError("projection result requires HistoryProjectionReceipt")
        object.__setattr__(
            self,
            "control_ack_receipt_cid",
            _require_sha256(
                self.control_ack_receipt_cid,
                field_name="control_ack_receipt_cid",
            ),
        )

    def as_mapping(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "schema": HISTORY_PROJECTION_RESULT_SCHEMA,
                "projection": dict(self.projection.as_mapping()),
                "control_ack_receipt_cid": self.control_ack_receipt_cid,
                "control_cursor_recorded": True,
                "projection_is_authority": False,
                "ducklake_grants_current_authority": False,
            }
        )


def _coerce_optional_cursor(
    value: HistoryCursor | Mapping[str, Any] | None,
) -> HistoryCursor | None:
    if value is None:
        return None
    return _coerce_cursor(value)


def _validate_cursor_chain(previous: HistoryCursor | None, current: HistoryCursor) -> None:
    if previous is None:
        return
    if current.outbox_ordinal <= previous.outbox_ordinal:
        raise HistoryContinuityError("outbox cursor did not advance")
    if current.owner_epoch < previous.owner_epoch:
        raise HistoryContinuityError("control owner epoch regressed")
    if current.owner_epoch == previous.owner_epoch and current.fence < previous.fence:
        raise HistoryContinuityError("control owner fence regressed")
    if previous.shard_id and current.shard_id != previous.shard_id:
        raise HistoryContinuityError("control outbox shard changed")


class HistoryProjectionService:
    """Serialize one committed control batch into one history-only lake epoch.

    The service receives no database paths or connection objects. It talks to
    the control owner through ``HistoryControlQuackGateway`` and to the lake
    owner through ``HistoryLakeQuackClient``. Both owners remain independent.
    """

    def __init__(
        self,
        *,
        control_gateway: HistoryControlQuackGateway | None = None,
        lake_client: HistoryLakeQuackClient | None = None,
        limits: HistoryProjectionLimits | None = None,
    ) -> None:
        self._control_gateway = control_gateway
        self._lake_client = lake_client
        self.limits = limits or HistoryProjectionLimits()
        self._lock = threading.RLock()

    def preflight(self) -> HistoryActivationDecision:
        control_capability: Mapping[str, Any] | None = None
        lake_capability: Mapping[str, Any] | None = None
        if self._control_gateway is not None:
            try:
                control_capability = self._control_gateway.capability()
            except Exception:
                control_capability = None
        if self._lake_client is not None:
            try:
                lake_capability = self._lake_client.capability()
            except Exception:
                lake_capability = None
        return evaluate_history_activation(control_capability, lake_capability)

    def project_next(self) -> HistoryProjectionResult | None:
        """Project and acknowledge at most one bounded batch.

        A lost acknowledgement is safe to retry: the control cursor remains
        behind, the deterministic operation id is reused, and the sole lake
        owner must return the existing exact receipt instead of appending a
        second row. Divergent replay fails closed.
        """

        with self._lock:
            decision = self.preflight()
            decision.require_activated()
            control = self._control_gateway
            lake = self._lake_client
            if control is None or lake is None:  # pragma: no cover - preflight closes
                raise HistoryActivationError("history projection gateways are absent")

            control_cursor = _coerce_optional_cursor(control.projection_cursor())
            lake_head = lake.projection_head()
            prior_ordinal = control_cursor.outbox_ordinal if control_cursor is not None else 0
            if control_cursor is not None and lake_head is None:
                raise HistoryContinuityError("control cursor is ahead of the absent DuckLake head")
            if lake_head is not None:
                if lake_head.cursor.outbox_ordinal < prior_ordinal:
                    raise HistoryContinuityError(
                        "control cursor is ahead of the committed DuckLake head"
                    )
                if (
                    lake_head.cursor.outbox_ordinal == prior_ordinal
                    and control_cursor is not None
                    and lake_head.cursor != control_cursor
                ):
                    raise HistoryContinuityError(
                        "control cursor and DuckLake head disagree at one ordinal"
                    )

            batch = control.read_committed_history(
                after_outbox_ordinal=prior_ordinal,
                limits=self.limits,
            )
            if batch is None:
                if lake_head is not None and lake_head.cursor.outbox_ordinal > prior_ordinal:
                    raise HistoryContinuityError(
                        "DuckLake has an unacknowledged head but control returned no batch"
                    )
                return None
            if not isinstance(batch, HistoryOutboxBatch):
                raise HistoryTransportError("control gateway must return typed HistoryOutboxBatch")
            if batch.previous_outbox_ordinal != prior_ordinal:
                raise HistoryContinuityError(
                    "outbox batch does not continue the acknowledged control cursor"
                )
            _validate_cursor_chain(control_cursor, batch.cursor)
            if len(batch.events) > self.limits.max_events:
                raise HistoryError("outbox batch exceeds configured event bound")
            if _json_size(batch.as_mapping()) > self.limits.max_bytes:
                raise HistoryError("outbox batch exceeds configured byte bound")
            if (
                lake_head is not None
                and lake_head.cursor.outbox_ordinal > batch.cursor.outbox_ordinal
            ):
                raise HistoryContinuityError("DuckLake head is ahead of the next control batch")
            if lake_head is not None and lake_head.cursor.outbox_ordinal not in {
                prior_ordinal,
                batch.cursor.outbox_ordinal,
            }:
                raise HistoryContinuityError(
                    "DuckLake has a different unacknowledged projection batch"
                )

            epoch = project_outbox(
                batch.cursor,
                batch.events,
                epoch_id=batch.batch_id,
            )
            if (
                lake_head is not None
                and lake_head.cursor.outbox_ordinal == batch.cursor.outbox_ordinal
                and (
                    lake_head.batch_id != batch.batch_id
                    or lake_head.cursor != batch.cursor
                    or lake_head.content_digest != epoch.content_digest
                )
            ):
                raise HistoryContinuityError(
                    "unacknowledged DuckLake replay differs from the control batch"
                )
            operation_id = _digest_of(
                {
                    "operation": LAKE_HISTORY_APPEND_OPERATION,
                    "batch_digest": batch.batch_digest,
                    "epoch_id": epoch.epoch_id,
                    "content_digest": epoch.content_digest,
                    "catalog_id": lake.catalog_id,
                    "owner_generation": lake.owner_generation,
                    "fencing_epoch": lake.fencing_epoch,
                }
            )
            projection = lake.append_epoch(
                operation_id=operation_id,
                batch=batch,
                epoch=epoch,
                expected_previous_outbox_ordinal=prior_ordinal,
            )
            acknowledgement = control.record_projection_cursor(projection.as_mapping())
            ack_cid = self._validate_control_ack(
                acknowledgement,
                projection=projection,
            )
            return HistoryProjectionResult(
                projection=projection,
                control_ack_receipt_cid=ack_cid,
            )

    @staticmethod
    def _validate_control_ack(
        value: Mapping[str, Any],
        *,
        projection: HistoryProjectionReceipt,
    ) -> str:
        if not isinstance(value, Mapping):
            raise HistoryReceiptError("control cursor acknowledgement must be an object")
        _reject_remote_bypass_fields(value, name="control cursor acknowledgement")
        if value.get("schema") != HISTORY_CONTROL_ACK_SCHEMA:
            raise HistoryReceiptError("control cursor acknowledgement schema mismatch")
        if value.get("recorded") is not True:
            raise HistoryReceiptError("control owner did not record projection cursor")
        if value.get("transport") != "quack":
            raise HistoryTransportError("control cursor acknowledgement bypassed Quack")
        if value.get("authority") != "one_fenced_duckdb_quack_owner":
            raise HistoryReceiptError("control cursor acknowledgement owner mismatch")
        if value.get("projection_is_authority") is not False:
            raise HistoryAuthorityError(
                "control acknowledgement promoted DuckLake projection authority"
            )
        if str(value.get("operation_id") or "") != projection.operation_id:
            raise HistoryReceiptError("control acknowledgement operation mismatch")
        if str(value.get("projection_receipt_digest") or "") != projection.receipt_digest:
            raise HistoryReceiptError("control acknowledgement projection receipt mismatch")
        if value.get("outbox_ordinal") != projection.cursor.outbox_ordinal:
            raise HistoryReceiptError("control acknowledgement cursor mismatch")
        return _require_sha256(value.get("ack_receipt_cid"), field_name="ack_receipt_cid")


__all__ = (
    "CONTROL_HISTORY_CURSOR_READ_OPERATION",
    "CONTROL_HISTORY_CURSOR_RECORD_OPERATION",
    "CONTROL_HISTORY_OUTBOX_READ_OPERATION",
    "EVENT_KINDS",
    "HISTORY_ACTIVATION_SCHEMA",
    "HISTORY_CONTROL_ACK_SCHEMA",
    "HISTORY_CONTROL_SEAM_CAPABILITY_SCHEMA",
    "HISTORY_CURSOR_SCHEMA",
    "HISTORY_EPOCH_SCHEMA",
    "HISTORY_EVENT_SCHEMA",
    "HISTORY_LAKE_CAPABILITY_SCHEMA",
    "HISTORY_OUTBOX_BATCH_SCHEMA",
    "HISTORY_OWNER_IDENTITY_SCHEMA",
    "HISTORY_PROJECTION_RECEIPT_SCHEMA",
    "HISTORY_PROJECTION_RESULT_SCHEMA",
    "HISTORY_QUACK_REQUEST_SCHEMA",
    "HISTORY_SCHEMA",
    "HISTORY_SNAPSHOT_SCHEMA",
    "LAKE_HISTORY_APPEND_OPERATION",
    "LAKE_HISTORY_CAPABILITY_OPERATION",
    "LAKE_HISTORY_CURSOR_OPERATION",
    "MAX_HISTORY_BATCH_BYTES",
    "MAX_HISTORY_BATCH_EVENTS",
    "MAX_HISTORY_BATCH_SECONDS",
    "REQUIRED_CONTROL_HISTORY_OPERATIONS",
    "REQUIRED_LAKE_HISTORY_OPERATIONS",
    "DuplicateEpochError",
    "ExclusiveHistoryOwnerLease",
    "HistoryActivationDecision",
    "HistoryActivationError",
    "HistoryAuthorityError",
    "HistoryContentionError",
    "HistoryContinuityError",
    "HistoryControlQuackGateway",
    "HistoryCursor",
    "HistoryCursorError",
    "HistoryEpoch",
    "HistoryError",
    "HistoryEvent",
    "HistoryLakeOwnerIdentity",
    "HistoryLakeQuackClient",
    "HistoryOutboxBatch",
    "HistoryPrivacyError",
    "HistoryProjectionLimits",
    "HistoryProjectionReceipt",
    "HistoryProjectionResult",
    "HistoryProjectionService",
    "HistoryProjector",
    "HistoryReceiptError",
    "HistorySnapshot",
    "HistoryTransportError",
    "evaluate_history_activation",
    "project_outbox",
)
