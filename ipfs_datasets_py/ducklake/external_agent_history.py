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
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Final


HISTORY_SCHEMA: Final[str] = (
    "ipfs_datasets_py/ducklake/external-agent-history@1"
)
HISTORY_CURSOR_SCHEMA: Final[str] = (
    "ipfs_datasets_py/ducklake/external-agent-history-cursor@1"
)
HISTORY_SNAPSHOT_SCHEMA: Final[str] = (
    "ipfs_datasets_py/ducklake/external-agent-history-snapshot@1"
)
HISTORY_EPOCH_SCHEMA: Final[str] = (
    "ipfs_datasets_py/ducklake/external-agent-history-epoch@1"
)
HISTORY_EVENT_SCHEMA: Final[str] = (
    "ipfs_datasets_py/ducklake/external-agent-history-event@1"
)

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
_ID_RE: Final[re.Pattern[str]] = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9._:/=@+-]*$"
)

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
                raise HistoryPrivacyError(
                    f"{name} must not represent hidden chain-of-thought"
                )
            if reason == "transcript_body":
                raise HistoryPrivacyError(
                    f"{name} must not embed transcript bodies"
                )
            if reason == "private_material":
                raise HistoryPrivacyError(
                    f"{name} must not contain secrets or private material"
                )
            _reject_forbidden_keys(item, name=name)
        return
    if isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray, memoryview)
    ):
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
        object.__setattr__(
            self, "fence", _require_pos_int(self.fence, field_name="fence")
        )
        digest = _require_nonempty(self.source_digest, field_name="source_digest")
        if not digest.startswith("sha256:"):
            if len(digest) == 64 and all(c in "0123456789abcdefABCDEF" for c in digest):
                digest = f"sha256:{digest.lower()}"
            else:
                raise HistoryCursorError("source_digest must be sha256:<64-hex>")
        if not _SHA256_RE.fullmatch(digest):
            raise HistoryCursorError("source_digest must be sha256:<64-hex>")
        object.__setattr__(self, "source_digest", digest)
        object.__setattr__(
            self, "owner_id", str(self.owner_id or "").strip()
        )
        object.__setattr__(
            self, "shard_id", str(self.shard_id or "").strip()
        )

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
    def from_mapping(cls, value: Mapping[str, Any] | None) -> "HistoryCursor":
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


__all__ = (
    "EVENT_KINDS",
    "HISTORY_CURSOR_SCHEMA",
    "HISTORY_EPOCH_SCHEMA",
    "HISTORY_EVENT_SCHEMA",
    "HISTORY_SCHEMA",
    "HISTORY_SNAPSHOT_SCHEMA",
    "DuplicateEpochError",
    "HistoryAuthorityError",
    "HistoryCursor",
    "HistoryCursorError",
    "HistoryEpoch",
    "HistoryError",
    "HistoryEvent",
    "HistoryPrivacyError",
    "HistoryProjector",
    "HistorySnapshot",
    "project_outbox",
)
