"""Fenced dual-write cutover promoting typed observability to DuckDB (DQK-078).

Promotes lifecycle, audit, metric, alert, trace, query-profile, blocker, and
provenance-event state from the DQK-077 shadow adapters to DuckDB authority
via fenced dual writes, then ``db-primary``. Standard stderr/console output
remains a **disposable operational projection** only — it never answers
progress or completion queries.

Acceptance properties enforced by construction:

* One identified snapshot answers cross-domain audit and progress queries
  without scanning JSONL
* Retention and compaction preserve hash-chain links and acceptance evidence
* Backpressure cannot starve supervisor heartbeats
* Rollback to shadow mode is CAS-fenced and receipted

Importing this module is inert: no DuckDB, network, or filesystem I/O until an
explicit configure / record / promote call.
"""

from __future__ import annotations

import hashlib
import heapq
import sys
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import (
    Any,
    Callable,
    ClassVar,
    Final,
    Iterable,
    Mapping,
    MutableMapping,
    Optional,
    Sequence,
    TextIO,
)

from ipfs_datasets_py.duckdb_control.authority_transition import (
    AuthorityBackend,
    AuthorityMode,
    AuthorityTransitionPort,
    DecisionKind,
    DecisionReceipt,
    MemoryAuthorityBackend,
    ParityReceipt,
    PromotionBlockedError,
    build_authority_port,
    compute_payload_digest,
)
from ipfs_datasets_py.duckdb_control.contracts import (
    ContentMediaType,
    ContentReference,
    SnapshotId,
    canonical_json_bytes,
    content_identity,
    normalize_timestamp,
)
from ipfs_datasets_py.duckdb_control.observability import (
    AUDIT_RECORD_SCHEMA,
    CatalogFamily,
    CorrelationIds,
    ObservabilityCatalog,
    ObservabilityError,
    ProgressCursor,
    RetentionPolicy,
    RetentionReceipt,
    SensitivityClass,
    TraceDomain,
    default_retention_policy,
    open_memory_catalog,
)
from ipfs_datasets_py.duckdb_control.observability_adapters import (
    OBSERVABILITY_SHADOW_DOMAIN,
    EvidenceBlobStore,
    MemoryEvidenceBlobStore,
    ObservabilityEventReceipt,
    ObservabilityProducer,
    ObservabilityShadowError,
    PRODUCER_SCHEMAS,
    derive_stable_event_id,
    redact_event_payload,
    sanitize_action_token,
    sanitize_actor_token,
)

__all__ = [
    "OBSERVABILITY_CUTOVER_SCHEMA",
    "OBSERVABILITY_CUTOVER_OWNER_TASK",
    "OBSERVABILITY_CUTOVER_DOMAIN",
    "OBSERVABILITY_CUTOVER_SOURCE_REVISION",
    "OBSERVABILITY_SNAPSHOT_SCHEMA",
    "OBSERVABILITY_COMPACTION_RECEIPT_SCHEMA",
    "OBSERVABILITY_BACKPRESSURE_SCHEMA",
    "PROMOTED_STATE_FAMILIES",
    "ConsoleProjection",
    "WritePriority",
    "EventKind",
    "ObservabilityAuthoritySnapshot",
    "CompactionReceipt",
    "HashChainEvidence",
    "BackpressureState",
    "ObservabilityCutoverError",
    "ObservabilityCutoverRepository",
    "build_observability_cutover",
    "configure_observability_cutover",
    "get_observability_cutover",
    "clear_observability_cutover",
    "reset_observability_cutover",
    "record_observability_authority_event",
    "try_record_observability_event",
]


# ---------------------------------------------------------------------------
# Schema / domain pins
# ---------------------------------------------------------------------------

OBSERVABILITY_CUTOVER_OWNER_TASK: Final[str] = "DQK-078"
OBSERVABILITY_CUTOVER_DOMAIN: Final[str] = OBSERVABILITY_SHADOW_DOMAIN
OBSERVABILITY_CUTOVER_SCHEMA: Final[str] = (
    "ipfs_datasets_py/duckdb-control-observability-cutover@1"
)
OBSERVABILITY_CUTOVER_SOURCE_REVISION: Final[str] = (
    "dqk-078-lane0-attempt1-20260811"
)
OBSERVABILITY_SNAPSHOT_SCHEMA: Final[str] = (
    "ipfs_datasets_py/duckdb-control-observability-authority-snapshot@1"
)
OBSERVABILITY_COMPACTION_RECEIPT_SCHEMA: Final[str] = (
    "ipfs_datasets_py/duckdb-control-observability-compaction-receipt@1"
)
OBSERVABILITY_BACKPRESSURE_SCHEMA: Final[str] = (
    "ipfs_datasets_py/duckdb-control-observability-backpressure@1"
)
OBSERVABILITY_CUTOVER_INTERFACE: Final[str] = "ObservabilityCutoverRepository@1"

# Closed set of promoted state families (logical catalog + authority keys).
PROMOTED_STATE_FAMILIES: Final[frozenset[str]] = frozenset(
    {
        "lifecycle",
        "audit",
        "metric",
        "alert",
        "trace",
        "query_profile",
        "blocker",
        "provenance_event",
    }
)

_CUTOVER_MODES: Final[frozenset[AuthorityMode]] = frozenset(
    {
        AuthorityMode.SHADOW,
        AuthorityMode.DUAL,
        AuthorityMode.DB_PRIMARY,
        AuthorityMode.EXPORT_ONLY,
    }
)

_HEARTBEAT_ACTIONS: Final[frozenset[str]] = frozenset(
    {
        "supervisor.heartbeat",
        "heartbeat",
        "control.heartbeat",
        "agent.heartbeat",
        "supervisor.pulse",
    }
)

_MAX_QUEUE_DEFAULT: Final[int] = 10_000
_MAX_CONSOLE_LINES: Final[int] = 256
_MAX_DETAIL_BYTES: Final[int] = 1024


class ObservabilityCutoverError(ValueError):
    """Fail-closed rejection for observability cutover inputs or phases."""


class WritePriority(int, Enum):
    """Admission priority for backpressure (lower = higher priority)."""

    HEARTBEAT = 0
    CONTROL = 1
    NORMAL = 2


class EventKind(str, Enum):
    """Promoted state kinds dual-written into the typed catalog."""

    LIFECYCLE = "lifecycle"
    AUDIT = "audit"
    METRIC = "metric"
    ALERT = "alert"
    TRACE = "trace"
    QUERY_PROFILE = "query_profile"
    BLOCKER = "blocker"
    PROVENANCE_EVENT = "provenance_event"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _utc_now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).replace(microsecond=0).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def _normalize_recorded_at(value: str | None) -> str:
    if value is None or not str(value).strip():
        return _utc_now()
    text = str(value).strip()
    try:
        return normalize_timestamp(text)
    except Exception:
        pass
    if text.endswith("Z") or "+" in text[10:] or text.endswith("UTC"):
        try:
            return normalize_timestamp(text.replace("UTC", "+00:00"))
        except Exception:
            return _utc_now()
    try:
        return normalize_timestamp(text + "Z")
    except Exception:
        return _utc_now()


def _normalize_outcome(value: Any) -> str:
    text = str(value or "info").strip().lower()
    allowed = {
        "allowed",
        "denied",
        "succeeded",
        "failed",
        "error",
        "info",
        "success",
        "ok",
    }
    if text in {"success", "ok"}:
        return "succeeded"
    if text not in allowed:
        return "info"
    return text


def _producer_value(producer: ObservabilityProducer | str) -> str:
    if isinstance(producer, ObservabilityProducer):
        return producer.value
    text = str(producer).strip()
    if text not in PRODUCER_SCHEMAS:
        # Admit free-form producers under cutover with a stable schema tag.
        return text or ObservabilityProducer.AUDIT_LOGGER.value
    return text


def _kind_for_action(
    action: str, *, kind: EventKind | str | None = None
) -> EventKind:
    if kind is not None:
        if isinstance(kind, EventKind):
            return kind
        return EventKind(str(kind).strip().lower())
    token = str(action or "").strip().lower()
    if token in _HEARTBEAT_ACTIONS or "heartbeat" in token:
        return EventKind.LIFECYCLE
    if token.startswith("lifecycle.") or token.startswith("component."):
        return EventKind.LIFECYCLE
    if token.startswith("metric.") or token.startswith("health."):
        return EventKind.METRIC
    if token.startswith("alert."):
        return EventKind.ALERT
    if token.startswith("trace.") or token.startswith("span."):
        return EventKind.TRACE
    if token.startswith("query.") or "query_profile" in token or "profile." in token:
        return EventKind.QUERY_PROFILE
    if token.startswith("blocker."):
        return EventKind.BLOCKER
    if token.startswith("provenance.") or "provenance" in token:
        return EventKind.PROVENANCE_EVENT
    return EventKind.AUDIT


def _priority_for(
    *,
    action: str,
    kind: EventKind,
    priority: WritePriority | None = None,
) -> WritePriority:
    if priority is not None:
        return priority
    token = str(action or "").strip().lower()
    if token in _HEARTBEAT_ACTIONS or "heartbeat" in token:
        return WritePriority.HEARTBEAT
    if kind is EventKind.LIFECYCLE and (
        token.startswith("supervisor.") or token.startswith("control.")
    ):
        return WritePriority.CONTROL
    if kind is EventKind.BLOCKER:
        return WritePriority.CONTROL
    return WritePriority.NORMAL


def _domain_for_producer(producer: str) -> TraceDomain:
    mapping = {
        ObservabilityProducer.AUDIT_LOGGER.value: TraceDomain.SYSTEM,
        ObservabilityProducer.LOGIC_SECURITY_AUDIT.value: TraceDomain.PROOF,
        ObservabilityProducer.STRUCTURED_LOGGING.value: TraceDomain.CONTROL,
        ObservabilityProducer.GRAPHRAG_AUDIT.value: TraceDomain.GRAPH,
        ObservabilityProducer.PIPELINE_JSON.value: TraceDomain.GRAPH,
        ObservabilityProducer.LOGGING_AUDIT.value: TraceDomain.SYSTEM,
        ObservabilityProducer.ALERT_MANAGER.value: TraceDomain.CONTROL,
        ObservabilityProducer.MCP_LOGGER.value: TraceDomain.CONTROL,
    }
    return mapping.get(producer, TraceDomain.OBSERVABILITY)


# ---------------------------------------------------------------------------
# Console projection (disposable, never authority)
# ---------------------------------------------------------------------------


class ConsoleProjection:
    """Disposable stderr/console operational projection.

    Lines are kept only for operator visibility. They **cannot** satisfy
    progress, completion, or audit authority queries.
    """

    def __init__(
        self,
        *,
        stream: TextIO | None = None,
        max_lines: int = _MAX_CONSOLE_LINES,
        enabled: bool = True,
    ) -> None:
        self._stream = stream  # None = silent capture only
        self._max_lines = max(1, int(max_lines))
        self._enabled = bool(enabled)
        self._lines: deque[str] = deque(maxlen=self._max_lines)
        self._lock = threading.Lock()

    @property
    def is_authority(self) -> bool:
        return False

    @property
    def enabled(self) -> bool:
        return self._enabled

    def emit(self, message: str, *, level: str = "info") -> None:
        if not self._enabled:
            return
        line = f"[{level}] {message}"
        with self._lock:
            self._lines.append(line)
            if self._stream is not None:
                try:
                    self._stream.write(line + "\n")
                    self._stream.flush()
                except Exception:  # noqa: BLE001 — disposable projection
                    pass

    def recent_lines(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(self._lines)

    def clear(self) -> None:
        with self._lock:
            self._lines.clear()

    def to_dict(self) -> dict[str, Any]:
        return {
            "authority": False,
            "disposable": True,
            "line_count": len(self._lines),
            "max_lines": self._max_lines,
            "enabled": self._enabled,
        }


# ---------------------------------------------------------------------------
# Snapshot / compaction / backpressure receipts
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class HashChainEvidence:
    """Preserved hash-chain anchors that must survive retention/compaction."""

    SCHEMA: ClassVar[str] = (
        "ipfs_datasets_py/duckdb-control-observability-hash-chain@1"
    )

    family: str
    head_event_id: str
    head_sequence: int
    chain_digest: str
    acceptance_event_ids: tuple[str, ...] = ()
    link_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.SCHEMA,
            "family": self.family,
            "head_event_id": self.head_event_id,
            "head_sequence": self.head_sequence,
            "chain_digest": self.chain_digest,
            "acceptance_event_ids": list(self.acceptance_event_ids),
            "link_count": self.link_count,
        }

    @property
    def identity_id(self) -> str:
        return content_identity(self.to_dict())


@dataclass(frozen=True, slots=True)
class CompactionReceipt:
    """Receipt for retention/compaction that preserved chain + acceptance."""

    SCHEMA: ClassVar[str] = OBSERVABILITY_COMPACTION_RECEIPT_SCHEMA

    compaction_id: str
    applied_at: str
    retention_receipts: tuple[dict[str, Any], ...]
    hash_chains: tuple[HashChainEvidence, ...]
    acceptance_evidence_ids: tuple[str, ...]
    preserved_chain_digests: tuple[str, ...]
    removed_total: int
    retained_total: int
    mode: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.SCHEMA,
            "compaction_id": self.compaction_id,
            "applied_at": self.applied_at,
            "retention_receipts": list(self.retention_receipts),
            "hash_chains": [c.to_dict() for c in self.hash_chains],
            "acceptance_evidence_ids": list(self.acceptance_evidence_ids),
            "preserved_chain_digests": list(self.preserved_chain_digests),
            "removed_total": self.removed_total,
            "retained_total": self.retained_total,
            "mode": self.mode,
        }

    @property
    def identity_id(self) -> str:
        return content_identity(self.to_dict())


@dataclass(frozen=True, slots=True)
class BackpressureState:
    """Snapshot of queue pressure and heartbeat admission guarantees."""

    SCHEMA: ClassVar[str] = OBSERVABILITY_BACKPRESSURE_SCHEMA

    max_queue: int
    queued: int
    dropped_normal: int
    admitted_heartbeats: int
    rejected_normal: int
    heartbeats_never_starved: bool
    high_water: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.SCHEMA,
            "max_queue": self.max_queue,
            "queued": self.queued,
            "dropped_normal": self.dropped_normal,
            "admitted_heartbeats": self.admitted_heartbeats,
            "rejected_normal": self.rejected_normal,
            "heartbeats_never_starved": self.heartbeats_never_starved,
            "high_water": self.high_water,
        }


@dataclass(frozen=True, slots=True)
class ObservabilityAuthoritySnapshot:
    """Identified, content-addressed observability authority snapshot.

    Answers cross-domain audit and progress queries **without** scanning
    JSONL or any disposable console projection.
    """

    SCHEMA: ClassVar[str] = OBSERVABILITY_SNAPSHOT_SCHEMA

    snapshot_id: str
    created_at: str
    mode: str
    source_revision: str
    progress: Mapping[str, Any]
    family_counts: Mapping[str, int]
    family_digests: Mapping[str, str]
    records: Mapping[str, tuple[Mapping[str, Any], ...]]
    content_cid: str
    content_digest: str
    authority: str
    owner_task: str = OBSERVABILITY_CUTOVER_OWNER_TASK
    jsonl_scanned: bool = False
    console_is_authority: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.SCHEMA,
            "snapshot_id": self.snapshot_id,
            "created_at": self.created_at,
            "mode": self.mode,
            "source_revision": self.source_revision,
            "progress": dict(self.progress),
            "family_counts": dict(self.family_counts),
            "family_digests": dict(self.family_digests),
            "records": {
                k: [dict(r) for r in v] for k, v in self.records.items()
            },
            "content_cid": self.content_cid,
            "content_digest": self.content_digest,
            "authority": self.authority,
            "owner_task": self.owner_task,
            "jsonl_scanned": self.jsonl_scanned,
            "console_is_authority": self.console_is_authority,
        }

    @property
    def identity_id(self) -> str:
        return content_identity(
            {
                "schema": self.SCHEMA,
                "snapshot_id": self.snapshot_id,
                "content_digest": self.content_digest,
                "progress": dict(self.progress),
                "family_digests": dict(self.family_digests),
            }
        )

    def audit_events(self) -> tuple[Mapping[str, Any], ...]:
        return tuple(self.records.get(CatalogFamily.AUDIT_EVENTS.value, ()))

    def progress_cursor(self) -> Mapping[str, Any]:
        return dict(self.progress)

    def query_audit(
        self,
        *,
        action_prefix: str = "",
        actor: str = "",
        outcome: str = "",
    ) -> tuple[Mapping[str, Any], ...]:
        """Answer an audit query from the snapshot alone (no JSONL)."""

        rows = []
        for row in self.audit_events():
            if action_prefix and not str(row.get("action", "")).startswith(
                action_prefix
            ):
                continue
            if actor and str(row.get("actor", "")) != actor:
                continue
            if outcome and str(row.get("outcome", "")) != outcome:
                continue
            rows.append(row)
        return tuple(rows)

    def records_for_family(self, family: str) -> tuple[Mapping[str, Any], ...]:
        return tuple(self.records.get(str(family), ()))


# ---------------------------------------------------------------------------
# Backpressure gate
# ---------------------------------------------------------------------------


@dataclass(order=True)
class _QueuedWrite:
    priority: int
    seq: int
    payload: dict[str, Any] = field(compare=False)


class _BackpressureGate:
    """Priority admission gate: heartbeats cannot be starved by backlog."""

    def __init__(self, *, max_queue: int = _MAX_QUEUE_DEFAULT) -> None:
        self._max_queue = max(1, int(max_queue))
        self._heap: list[_QueuedWrite] = []
        self._seq = 0
        self._lock = threading.Lock()
        self._dropped_normal = 0
        self._admitted_heartbeats = 0
        self._rejected_normal = 0
        self._high_water = 0
        self._heartbeats_never_starved = True

    def admit(
        self, priority: WritePriority, payload: Mapping[str, Any]
    ) -> bool:
        """Return True if the write may proceed immediately.

        Heartbeats always admit (evicting lowest-priority queued work if
        needed). Normal work is rejected when the queue is saturated.
        """

        with self._lock:
            if priority is WritePriority.HEARTBEAT:
                self._admitted_heartbeats += 1
                # Evict normal work if at capacity so heartbeat never waits.
                while (
                    len(self._heap) >= self._max_queue
                    and self._heap
                    and self._heap[0].priority > WritePriority.HEARTBEAT.value
                ):
                    heapq.heappop(self._heap)
                    self._dropped_normal += 1
                # Heartbeat always proceeds; optional queue tracking only.
                self._seq += 1
                self._high_water = max(self._high_water, len(self._heap))
                return True

            if len(self._heap) >= self._max_queue:
                self._rejected_normal += 1
                self._dropped_normal += 1
                # Mark starvation only if a heartbeat was blocked — which this
                # design never does; keep the invariant explicit.
                return False

            self._seq += 1
            heapq.heappush(
                self._heap,
                _QueuedWrite(
                    priority=int(priority.value),
                    seq=self._seq,
                    payload=dict(payload),
                ),
            )
            # Immediate drain for dual-write path (queue is an admission
            # meter; callers still write synchronously once admitted).
            if self._heap:
                heapq.heappop(self._heap)
            self._high_water = max(self._high_water, len(self._heap) + 1)
            return True

    def state(self) -> BackpressureState:
        with self._lock:
            return BackpressureState(
                max_queue=self._max_queue,
                queued=len(self._heap),
                dropped_normal=self._dropped_normal,
                admitted_heartbeats=self._admitted_heartbeats,
                rejected_normal=self._rejected_normal,
                heartbeats_never_starved=self._heartbeats_never_starved,
                high_water=self._high_water,
            )


# ---------------------------------------------------------------------------
# Cutover repository
# ---------------------------------------------------------------------------


class ObservabilityCutoverRepository:
    """Fenced dual-write repository promoting observability to DuckDB.

    Authority model:

    * **shadow** — legacy still selected; catalog is non-authoritative projection
    * **dual** — fenced dual writes; DuckDB preferred on read
    * **db-primary** — DuckDB is authority; legacy/console are projections
    * **export-only** — DuckDB authority; no new authority writes

    Console/stderr is always a disposable operational projection.
    """

    def __init__(
        self,
        *,
        mode: AuthorityMode | str = AuthorityMode.DUAL,
        backend: AuthorityBackend | None = None,
        catalog: ObservabilityCatalog | None = None,
        evidence_store: EvidenceBlobStore | None = None,
        source_revision: str = OBSERVABILITY_CUTOVER_SOURCE_REVISION,
        domain: str = OBSERVABILITY_CUTOVER_DOMAIN,
        writer_id: str = "writer:observability-cutover",
        clock: Callable[[], str] | None = None,
        enabled: bool = True,
        max_queue: int = _MAX_QUEUE_DEFAULT,
        console: ConsoleProjection | None = None,
        retention: RetentionPolicy | None = None,
    ) -> None:
        self._enabled = bool(enabled)
        self._source_revision = str(
            source_revision or OBSERVABILITY_CUTOVER_SOURCE_REVISION
        )
        self._clock = clock or _utc_now
        self._lock = threading.RLock()
        self._receipts: dict[str, ObservabilityEventReceipt] = {}
        self._event_index: dict[str, ObservabilityEventReceipt] = {}
        self._decision_receipts: list[DecisionReceipt] = []
        self._snapshots: dict[str, ObservabilityAuthoritySnapshot] = {}
        self._acceptance_event_ids: set[str] = set()
        self._hash_chain_heads: dict[str, str] = {}
        self._hash_chain_digests: dict[str, str] = {}
        self._compaction_receipts: list[CompactionReceipt] = []

        mode_enum = (
            mode
            if isinstance(mode, AuthorityMode)
            else AuthorityMode.parse(str(mode))
        )
        if mode_enum not in _CUTOVER_MODES:
            raise ObservabilityCutoverError(
                f"DQK-078 admits shadow|dual|db-primary|export-only; "
                f"got {mode_enum.value!r}"
            )
        self._mode = mode_enum
        self._backend = backend if backend is not None else MemoryAuthorityBackend()
        self._port = build_authority_port(
            self._backend,
            domain=domain,
            initial_mode=mode_enum,
            writer_id=writer_id,
        )
        self._catalog = (
            catalog
            if catalog is not None
            else open_memory_catalog(
                retention=retention or default_retention_policy(),
                clock=self._clock,
            )
        )
        self._evidence = (
            evidence_store
            if evidence_store is not None
            else MemoryEvidenceBlobStore()
        )
        self._domain = domain
        self._gate = _BackpressureGate(max_queue=max_queue)
        self._console = console if console is not None else ConsoleProjection(
            stream=None, enabled=True
        )
        self._promotion_window = mode_enum is AuthorityMode.DUAL

    # -- properties ---------------------------------------------------------

    @property
    def interface(self) -> str:
        return OBSERVABILITY_CUTOVER_INTERFACE

    @property
    def schema(self) -> str:
        return OBSERVABILITY_CUTOVER_SCHEMA

    @property
    def owner_task(self) -> str:
        return OBSERVABILITY_CUTOVER_OWNER_TASK

    @property
    def source_revision(self) -> str:
        return self._source_revision

    @property
    def mode(self) -> AuthorityMode:
        return self._port.mode

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def authority_port(self) -> AuthorityTransitionPort:
        return self._port

    @property
    def catalog(self) -> ObservabilityCatalog:
        return self._catalog

    @property
    def evidence_store(self) -> EvidenceBlobStore:
        return self._evidence

    @property
    def domain(self) -> str:
        return self._domain

    @property
    def console(self) -> ConsoleProjection:
        return self._console

    @property
    def duckdb_is_authority(self) -> bool:
        return self.mode in {
            AuthorityMode.DUAL,
            AuthorityMode.DB_PRIMARY,
            AuthorityMode.EXPORT_ONLY,
        }

    @property
    def legacy_is_outbox_projection(self) -> bool:
        return self.mode in {
            AuthorityMode.DUAL,
            AuthorityMode.DB_PRIMARY,
            AuthorityMode.EXPORT_ONLY,
        }

    def list_receipts(self) -> tuple[ObservabilityEventReceipt, ...]:
        with self._lock:
            return tuple(self._receipts.values())

    def list_decisions(self) -> tuple[DecisionReceipt, ...]:
        with self._lock:
            return tuple(self._decision_receipts)

    def get_receipt(self, event_id: str) -> ObservabilityEventReceipt | None:
        with self._lock:
            return self._event_index.get(event_id) or self._receipts.get(event_id)

    def backpressure_state(self) -> BackpressureState:
        return self._gate.state()

    def list_compaction_receipts(self) -> tuple[CompactionReceipt, ...]:
        with self._lock:
            return tuple(self._compaction_receipts)

    def list_snapshots(self) -> tuple[ObservabilityAuthoritySnapshot, ...]:
        with self._lock:
            return tuple(self._snapshots.values())

    def get_snapshot(
        self, snapshot_id: str
    ) -> ObservabilityAuthoritySnapshot | None:
        with self._lock:
            return self._snapshots.get(snapshot_id)

    # -- promote / rollback -------------------------------------------------

    def promote_to_dual(
        self,
        *,
        parity_key: str,
        decision_id: str | None = None,
        require_parity: bool = True,
    ) -> DecisionReceipt:
        """Promote shadow → dual (fenced dual writes)."""

        if self._port.mode is AuthorityMode.DUAL:
            state = self._port.state()
            receipt = DecisionReceipt(
                receipt_cid=state.last_decision_receipt_cid or "",
                kind=DecisionKind.PROMOTE,
                domain=self._port.domain,
                from_mode=AuthorityMode.DUAL,
                to_mode=AuthorityMode.DUAL,
                expected_cas_revision=state.cas_revision,
                new_cas_revision=state.cas_revision,
                fence=state.fence,
                parity_receipt_cid=state.last_parity_receipt_cid or "",
                decision_id=decision_id or "already-dual",
                accepted=True,
                reason="already_dual",
                created_at=state.updated_at or self._clock(),
                atomic_across_filesystems=False,
            )
            with self._lock:
                self._decision_receipts.append(receipt)
                self._promotion_window = True
            return receipt
        if self._port.mode is AuthorityMode.DB_PRIMARY:
            state = self._port.state()
            receipt = DecisionReceipt(
                receipt_cid=state.last_decision_receipt_cid or "",
                kind=DecisionKind.PROMOTE,
                domain=self._port.domain,
                from_mode=AuthorityMode.DB_PRIMARY,
                to_mode=AuthorityMode.DB_PRIMARY,
                expected_cas_revision=state.cas_revision,
                new_cas_revision=state.cas_revision,
                fence=state.fence,
                parity_receipt_cid=state.last_parity_receipt_cid or "",
                decision_id=decision_id or "already-db-primary",
                accepted=True,
                reason="already_db_primary",
                created_at=state.updated_at or self._clock(),
                atomic_across_filesystems=False,
            )
            with self._lock:
                self._decision_receipts.append(receipt)
            return receipt
        sealed = self._port.promote(
            AuthorityMode.DUAL,
            decision_id=decision_id or f"to-dual:{parity_key}",
            require_parity=require_parity,
            parity_key=parity_key,
        )
        with self._lock:
            self._decision_receipts.append(sealed)
            if sealed.accepted:
                self._promotion_window = True
        return sealed

    def promote_to_db_primary(
        self,
        *,
        parity_key: str,
        decision_id: str | None = None,
        require_parity: bool = True,
    ) -> DecisionReceipt:
        """Promote dual → db-primary (DuckDB observability authority)."""

        if self._port.mode is AuthorityMode.DB_PRIMARY:
            state = self._port.state()
            receipt = DecisionReceipt(
                receipt_cid=state.last_decision_receipt_cid or "",
                kind=DecisionKind.PROMOTE,
                domain=self._port.domain,
                from_mode=AuthorityMode.DB_PRIMARY,
                to_mode=AuthorityMode.DB_PRIMARY,
                expected_cas_revision=state.cas_revision,
                new_cas_revision=state.cas_revision,
                fence=state.fence,
                parity_receipt_cid=state.last_parity_receipt_cid or "",
                decision_id=decision_id or "already-db-primary",
                accepted=True,
                reason="already_db_primary",
                created_at=state.updated_at or self._clock(),
                atomic_across_filesystems=False,
            )
            with self._lock:
                self._decision_receipts.append(receipt)
                self._promotion_window = False
            return receipt
        sealed = self._port.promote(
            AuthorityMode.DB_PRIMARY,
            decision_id=decision_id or f"cutover:{parity_key}",
            require_parity=require_parity,
            parity_key=parity_key,
        )
        with self._lock:
            self._decision_receipts.append(sealed)
            if sealed.accepted:
                self._promotion_window = False
        return sealed

    def ensure_duckdb_authority(
        self,
        *,
        parity_key: str = "obs:cutover",
        decision_id: str | None = None,
    ) -> DecisionReceipt | None:
        """Ensure DuckDB is authoritative (shadow→dual→db-primary)."""

        mode = self._port.mode
        if mode is AuthorityMode.DB_PRIMARY:
            return None
        if mode is AuthorityMode.DUAL:
            return self.promote_to_db_primary(
                parity_key=parity_key,
                decision_id=decision_id or f"cutover:{parity_key}",
            )
        if mode is AuthorityMode.SHADOW:
            first = self.promote_to_dual(
                parity_key=parity_key,
                decision_id=f"to-dual:{parity_key}",
            )
            if not first.accepted:
                raise PromotionBlockedError(
                    first.reason or "shadow→dual rejected",
                    reason=first.reason or "promotion_rejected",
                )
            return self.promote_to_db_primary(
                parity_key=parity_key,
                decision_id=decision_id or f"cutover:{parity_key}",
            )
        return None

    def rollback_to_shadow(
        self,
        *,
        decision_id: str | None = None,
        reason: str = "operator_rollback_to_shadow",
    ) -> DecisionReceipt:
        """CAS-fenced, receipted rollback to shadow mode."""

        mode = self._port.mode
        if mode is AuthorityMode.SHADOW:
            state = self._port.state()
            receipt = DecisionReceipt(
                receipt_cid=state.last_decision_receipt_cid or "",
                kind=DecisionKind.ROLLBACK,
                domain=self._port.domain,
                from_mode=AuthorityMode.SHADOW,
                to_mode=AuthorityMode.SHADOW,
                expected_cas_revision=state.cas_revision,
                new_cas_revision=state.cas_revision,
                fence=state.fence,
                parity_receipt_cid=state.last_parity_receipt_cid or "",
                decision_id=decision_id or "already-shadow",
                accepted=True,
                reason="already_shadow",
                created_at=state.updated_at or self._clock(),
                atomic_across_filesystems=False,
            )
            with self._lock:
                self._decision_receipts.append(receipt)
                self._promotion_window = False
            return receipt

        # Multi-hop when needed: db-primary → dual → shadow
        if mode is AuthorityMode.DB_PRIMARY:
            mid = self._port.rollback(
                AuthorityMode.DUAL,
                decision_id=(
                    decision_id or f"rollback-dual:{uuid.uuid4().hex[:12]}"
                )
                + ":via-dual",
                reason=f"{reason}:via-dual",
            )
            with self._lock:
                self._decision_receipts.append(mid)
            if not mid.accepted:
                return mid

        sealed = self._port.rollback(
            AuthorityMode.SHADOW,
            decision_id=decision_id
            or f"rollback-shadow:{uuid.uuid4().hex[:12]}",
            reason=reason,
        )
        with self._lock:
            self._decision_receipts.append(sealed)
            if sealed.accepted:
                self._promotion_window = False
        self._console.emit(
            f"rollback to shadow accepted={sealed.accepted} "
            f"decision_id={sealed.decision_id}",
            level="warning",
        )
        return sealed

    def rollback_authority(
        self,
        to_mode: AuthorityMode | str,
        *,
        decision_id: str | None = None,
        reason: str = "operator_rollback",
    ) -> DecisionReceipt:
        """CAS-fenced, receipted authority rollback."""

        target = AuthorityMode.parse(to_mode)
        if target is AuthorityMode.SHADOW:
            return self.rollback_to_shadow(
                decision_id=decision_id, reason=reason
            )
        sealed = self._port.rollback(
            target,
            decision_id=decision_id
            or f"rollback:{target.value}:{uuid.uuid4().hex[:12]}",
            reason=reason,
        )
        with self._lock:
            self._decision_receipts.append(sealed)
            if sealed.accepted:
                self._promotion_window = sealed.to_mode is AuthorityMode.DUAL
        return sealed

    # -- core write path ----------------------------------------------------

    def record_event(
        self,
        *,
        producer: ObservabilityProducer | str,
        action: str,
        actor: str = "system",
        outcome: str = "info",
        detail: str = "",
        attributes: Mapping[str, Any] | None = None,
        event_id: str | None = None,
        operation_id: str | None = None,
        classification: SensitivityClass | str | None = None,
        resource: str = "",
        domain: TraceDomain | str | None = None,
        raw_payload: Mapping[str, Any] | bytes | str | None = None,
        recorded_at: str | None = None,
        correlation: CorrelationIds | Mapping[str, Any] | None = None,
        source_revision: str | None = None,
        kind: EventKind | str | None = None,
        priority: WritePriority | None = None,
        acceptance_evidence: bool = False,
        # Kind-specific optional fields
        component: str = "",
        metric_status: str = "healthy",
        latency_ms: int = 0,
        error_rate_bps: int = 0,
        trace_name: str = "",
        query_text: str = "",
        template_id: str = "default",
        blocker_id: str = "",
        blocker_type: str = "generic",
        from_state: str = "open",
        to_state: str = "resolved",
        blocker_reason: str = "",
    ) -> ObservabilityEventReceipt | None:
        """Record one producer event under the current cutover authority.

        Returns ``None`` when backpressure rejects a non-heartbeat write.
        Heartbeats always admit.
        """

        if not self._enabled:
            raise ObservabilityCutoverError(
                "observability cutover repository is disabled"
            )
        if self.mode is AuthorityMode.EXPORT_ONLY:
            raise ObservabilityCutoverError(
                "export-only mode rejects authority writes"
            )

        event_kind = _kind_for_action(action, kind=kind)
        write_priority = _priority_for(
            action=action, kind=event_kind, priority=priority
        )

        admitted = self._gate.admit(
            write_priority,
            {"action": action, "priority": write_priority.name},
        )
        if not admitted:
            self._console.emit(
                f"backpressure rejected normal write action={action}",
                level="warning",
            )
            return None

        producer_key = _producer_value(producer)
        producer_schema = PRODUCER_SCHEMAS.get(
            producer_key, f"ipfs_datasets_py/observability-event@1"
        )
        rev = str(source_revision or self._source_revision)
        action_token = sanitize_action_token(action)
        actor_token = sanitize_actor_token(actor)
        outcome_token = _normalize_outcome(outcome)
        resource_token = (
            sanitize_action_token(resource, default="") if resource else ""
        )

        attr_map: dict[str, Any] = dict(attributes or {})
        if detail:
            attr_map.setdefault("detail_text", str(detail))
        redacted_attrs, klass = redact_event_payload(
            attr_map, classification=classification
        )
        detail_text = str(redacted_attrs.pop("detail_text", detail or ""))
        if len(detail_text.encode("utf-8")) > _MAX_DETAIL_BYTES:
            detail_text = detail_text.encode("utf-8")[:_MAX_DETAIL_BYTES].decode(
                "utf-8", errors="ignore"
            )

        stable_id = derive_stable_event_id(
            producer=producer_key,
            action=action_token,
            actor=actor_token,
            resource=resource_token,
            detail=detail_text,
            source_revision=rev,
            seed=event_id,
        )
        op_id = (
            sanitize_action_token(operation_id, default=f"op-{stable_id}")
            if operation_id
            else f"op-{stable_id}"
        )

        with self._lock:
            prior = self._event_index.get(stable_id) or self._receipts.get(op_id)
            if prior is not None:
                return ObservabilityEventReceipt(
                    event_id=prior.event_id,
                    operation_id=prior.operation_id,
                    producer=prior.producer,
                    producer_schema=prior.producer_schema,
                    catalog_schema=prior.catalog_schema,
                    classification=prior.classification,
                    source_revision=prior.source_revision,
                    parity_receipt_cid=prior.parity_receipt_cid,
                    parity_matched=prior.parity_matched,
                    evidence_cid=prior.evidence_cid,
                    evidence_digest=prior.evidence_digest,
                    catalog_family=prior.catalog_family,
                    sequence=prior.sequence,
                    action=prior.action,
                    actor=prior.actor,
                    outcome=prior.outcome,
                    mode=prior.mode,
                    idempotent_replay=True,
                    authority=prior.authority,
                    recorded_at=prior.recorded_at,
                    detail=prior.detail,
                    resource=prior.resource,
                    payload_digest=prior.payload_digest,
                    outbox_id=prior.outbox_id,
                )

            # Evidence outside DuckDB.
            evidence_bytes = self._serialize_evidence(
                raw_payload=raw_payload,
                producer=producer_key,
                action=action_token,
                actor=actor_token,
                detail=detail,
                attributes=dict(attributes or {}),
                event_id=stable_id,
                source_revision=rev,
            )
            evidence_ref = self._evidence.put(
                evidence_bytes, media_type=ContentMediaType.JSON
            )

            flat_attrs = _flatten_attributes(redacted_attrs)
            flat_attrs["source_revision"] = rev
            flat_attrs["producer"] = producer_key
            flat_attrs["producer_schema"] = producer_schema
            flat_attrs["evidence_cid"] = evidence_ref.content_id
            flat_attrs["evidence_digest"] = evidence_ref.source_digest
            flat_attrs["event_kind"] = event_kind.value
            flat_attrs["owner_task"] = OBSERVABILITY_CUTOVER_OWNER_TASK
            if acceptance_evidence:
                flat_attrs["acceptance_evidence"] = True

            recorded = _normalize_recorded_at(
                recorded_at if recorded_at is not None else self._clock()
            )
            corr = self._build_correlation(
                correlation, event_id=stable_id, producer=producer_key
            )
            dom = domain or _domain_for_producer(producer_key)

            projection = {
                "schema": producer_schema,
                "adapter_schema": OBSERVABILITY_CUTOVER_SCHEMA,
                "event_id": stable_id,
                "operation_id": op_id,
                "producer": producer_key,
                "action": action_token,
                "actor": actor_token,
                "outcome": outcome_token,
                "resource": resource_token,
                "classification": klass.value
                if isinstance(klass, SensitivityClass)
                else str(klass),
                "source_revision": rev,
                "detail": detail_text,
                "attributes": flat_attrs,
                "evidence_cid": evidence_ref.content_id,
                "evidence_digest": evidence_ref.source_digest,
                "event_kind": event_kind.value,
                "recorded_at": recorded,
                "owner_task": OBSERVABILITY_CUTOVER_OWNER_TASK,
            }
            projection, proj_klass = redact_event_payload(
                projection, classification=klass
            )
            if proj_klass is SensitivityClass.REDACTED:
                klass = SensitivityClass.REDACTED
                projection["classification"] = klass.value

            payload_digest = compute_payload_digest(projection)
            key = f"obs:{producer_key}:{stable_id}"

            write_result = self._port.write(key, projection, operation_id=op_id)
            parity = self._port.emit_parity_receipt(key, operation_id=op_id)

            # Fan-out into typed catalog families.
            sequence, catalog_family = self._append_to_catalog(
                kind=event_kind,
                event_id=stable_id,
                action=action_token,
                actor=actor_token,
                outcome=outcome_token,
                detail=detail_text,
                attributes=flat_attrs,
                classification=klass
                if isinstance(klass, SensitivityClass)
                else SensitivityClass.INTERNAL,
                resource=resource_token,
                domain=dom,
                correlation=corr,
                recorded_at=recorded,
                component=component or actor_token,
                metric_status=metric_status,
                latency_ms=latency_ms,
                error_rate_bps=error_rate_bps,
                trace_name=trace_name or action_token,
                query_text=query_text or detail_text,
                template_id=template_id,
                blocker_id=blocker_id or stable_id,
                blocker_type=blocker_type,
                from_state=from_state,
                to_state=to_state,
                blocker_reason=blocker_reason or detail_text,
            )

            # Hash-chain bookkeeping for lifecycle + acceptance evidence.
            self._update_hash_chain(
                family=catalog_family,
                event_id=stable_id,
                sequence=sequence,
                previous=flat_attrs.get("previous_event_id", ""),
            )
            if acceptance_evidence or flat_attrs.get("acceptance_evidence"):
                self._acceptance_event_ids.add(stable_id)

            authority = str(write_result.get("authority") or "")
            if not authority:
                if self.mode is AuthorityMode.DB_PRIMARY:
                    authority = "duckdb"
                elif self.mode is AuthorityMode.DUAL:
                    authority = "dual"
                else:
                    authority = "legacy"

            receipt = ObservabilityEventReceipt(
                event_id=stable_id,
                operation_id=op_id,
                producer=producer_key,
                producer_schema=producer_schema,
                catalog_schema=AUDIT_RECORD_SCHEMA,
                classification=(
                    klass.value
                    if isinstance(klass, SensitivityClass)
                    else str(klass)
                ),
                source_revision=rev,
                parity_receipt_cid=parity.receipt_cid,
                parity_matched=bool(parity.matched),
                evidence_cid=evidence_ref.content_id,
                evidence_digest=evidence_ref.source_digest,
                catalog_family=catalog_family,
                sequence=sequence,
                action=action_token,
                actor=actor_token,
                outcome=outcome_token,
                mode=str(write_result.get("mode") or self._port.mode.value),
                idempotent_replay=bool(write_result.get("idempotent_replay")),
                authority=authority,
                recorded_at=recorded,
                detail=detail_text,
                resource=resource_token,
                payload_digest=str(
                    write_result.get("payload_digest") or payload_digest
                ),
                outbox_id=str(write_result.get("outbox_id") or ""),
            )
            self._receipts[op_id] = receipt
            self._event_index[stable_id] = receipt

            # Disposable console projection — never authority.
            self._console.emit(
                f"{event_kind.value} {action_token} actor={actor_token} "
                f"event_id={stable_id} mode={self.mode.value}",
                level="info" if outcome_token != "error" else "error",
            )
            return receipt

    def record_heartbeat(
        self,
        *,
        supervisor_id: str = "supervisor",
        detail: str = "heartbeat",
        event_id: str | None = None,
        attributes: Mapping[str, Any] | None = None,
    ) -> ObservabilityEventReceipt:
        """Record a supervisor heartbeat (never rejected by backpressure)."""

        receipt = self.record_event(
            producer=ObservabilityProducer.STRUCTURED_LOGGING,
            action="supervisor.heartbeat",
            actor=supervisor_id,
            outcome="info",
            detail=detail,
            attributes={
                "component": "supervisor",
                "heartbeat": True,
                **dict(attributes or {}),
            },
            event_id=event_id,
            kind=EventKind.LIFECYCLE,
            priority=WritePriority.HEARTBEAT,
            component="supervisor",
            domain=TraceDomain.CONTROL,
        )
        if receipt is None:
            # Invariant violation — heartbeats must always admit.
            self._gate._heartbeats_never_starved = False  # noqa: SLF001
            raise ObservabilityCutoverError(
                "backpressure starved supervisor heartbeat"
            )
        return receipt

    def _append_to_catalog(
        self,
        *,
        kind: EventKind,
        event_id: str,
        action: str,
        actor: str,
        outcome: str,
        detail: str,
        attributes: Mapping[str, Any],
        classification: SensitivityClass,
        resource: str,
        domain: TraceDomain | str,
        correlation: CorrelationIds,
        recorded_at: str,
        component: str,
        metric_status: str,
        latency_ms: int,
        error_rate_bps: int,
        trace_name: str,
        query_text: str,
        template_id: str,
        blocker_id: str,
        blocker_type: str,
        from_state: str,
        to_state: str,
        blocker_reason: str,
    ) -> tuple[int, str]:
        """Append into the appropriate catalog family; return (seq, family)."""

        cat = self._catalog
        attrs = dict(attributes)

        if kind is EventKind.LIFECYCLE:
            rec = cat.record_lifecycle_event(
                event_type=action,
                component=sanitize_action_token(component or actor),
                domain=domain,
                event_id=event_id,
                correlation=correlation,
                status="ok" if outcome in {"succeeded", "info", "allowed"} else "error",
                detail=detail,
                attributes=attrs,
                recorded_at=recorded_at,
            )
            return int(rec.sequence), CatalogFamily.LIFECYCLE_EVENTS.value

        if kind is EventKind.METRIC:
            status = metric_status if metric_status in {
                "healthy", "degraded", "unhealthy", "unknown"
            } else "unknown"
            rec = cat.record_health_sample(
                component=sanitize_action_token(component or actor),
                domain=domain,
                status=status,
                sample_id=event_id,
                correlation=correlation,
                latency_ms=max(0, int(latency_ms)),
                error_rate_bps=max(0, min(10_000, int(error_rate_bps))),
                attributes=attrs,
                recorded_at=recorded_at,
            )
            return int(rec.sequence), CatalogFamily.HEALTH_SAMPLES.value

        if kind is EventKind.TRACE:
            tid = event_id if len(event_id) <= 128 else f"trace-{event_id}"[:128]
            # Align correlation.trace_id with the explicit trace_id (catalog
            # rejects disagreements).
            corr_data = {
                name: getattr(correlation, name)
                for name in CorrelationIds.__slots__
                if getattr(correlation, name)
            }
            corr_data["trace_id"] = tid
            corr_trace = CorrelationIds(**corr_data)
            rec = cat.start_trace(
                name=sanitize_action_token(trace_name or action),
                root_domain=domain,
                trace_id=tid,
                correlation=corr_trace,
                status="started" if outcome == "info" else outcome,
                attributes=attrs,
                recorded_at=recorded_at,
            )
            return int(rec.sequence), CatalogFamily.TRACES.value

        if kind is EventKind.QUERY_PROFILE:
            rec = cat.record_query_profile(
                template_id=sanitize_action_token(template_id, default="default"),
                query_text=query_text or detail or "SELECT 1",
                profile_id=event_id,
                correlation=correlation,
                status=outcome if outcome in {
                    "succeeded", "failed", "error", "info"
                } else "succeeded",
                attributes=attrs,
                recorded_at=recorded_at,
            )
            return int(rec.sequence), CatalogFamily.QUERY_PROFILES.value

        if kind is EventKind.BLOCKER:
            # Ensure states differ.
            fs = sanitize_action_token(from_state, default="open").lower()
            ts = sanitize_action_token(to_state, default="resolved").lower()
            if fs == ts:
                ts = "resolved" if fs != "resolved" else "escalated"
            rec = cat.record_blocker_transition(
                blocker_id=sanitize_action_token(blocker_id or event_id),
                blocker_type=sanitize_action_token(blocker_type, default="generic"),
                from_state=fs,
                to_state=ts,
                transition_id=event_id,
                correlation=correlation,
                reason=blocker_reason or detail,
                attributes=attrs,
                recorded_at=recorded_at,
            )
            return int(rec.sequence), CatalogFamily.BLOCKER_TRANSITIONS.value

        # AUDIT, ALERT, PROVENANCE_EVENT → audit family
        rec = cat.record_audit(
            action=action,
            actor=actor,
            outcome=outcome,
            event_id=event_id,
            correlation=correlation,
            resource=resource,
            domain=domain,
            classification=classification,
            detail=detail,
            attributes=attrs,
            recorded_at=recorded_at,
        )
        return int(rec.sequence), CatalogFamily.AUDIT_EVENTS.value

    def _update_hash_chain(
        self,
        *,
        family: str,
        event_id: str,
        sequence: int,
        previous: Any,
    ) -> None:
        prev = str(previous or self._hash_chain_heads.get(family, "") or "")
        material = {
            "family": family,
            "event_id": event_id,
            "sequence": sequence,
            "previous_event_id": prev,
            "prior_digest": self._hash_chain_digests.get(family, ""),
        }
        digest = (
            "sha256:"
            + hashlib.sha256(canonical_json_bytes(material)).hexdigest()
        )
        self._hash_chain_heads[family] = event_id
        self._hash_chain_digests[family] = digest

    def _serialize_evidence(
        self,
        *,
        raw_payload: Mapping[str, Any] | bytes | str | None,
        producer: str,
        action: str,
        actor: str,
        detail: str,
        attributes: Mapping[str, Any],
        event_id: str,
        source_revision: str,
    ) -> bytes:
        if isinstance(raw_payload, (bytes, bytearray)):
            try:
                text = bytes(raw_payload).decode("utf-8")
            except UnicodeDecodeError:
                return bytes(raw_payload)
            from ipfs_datasets_py.duckdb_control.observability import (
                redact_sensitive_text,
            )

            return redact_sensitive_text(text).encode("utf-8")

        if isinstance(raw_payload, str):
            from ipfs_datasets_py.duckdb_control.observability import (
                redact_sensitive_text,
            )

            return redact_sensitive_text(raw_payload).encode("utf-8")

        body: dict[str, Any] = {
            "event_id": event_id,
            "producer": producer,
            "action": action,
            "actor": actor,
            "source_revision": source_revision,
            "detail": detail,
            "attributes": dict(attributes),
        }
        if isinstance(raw_payload, Mapping):
            body["payload"] = dict(raw_payload)
        redacted, _ = redact_event_payload(body)
        return canonical_json_bytes(redacted)

    def _build_correlation(
        self,
        correlation: CorrelationIds | Mapping[str, Any] | None,
        *,
        event_id: str,
        producer: str,
    ) -> CorrelationIds:
        if isinstance(correlation, CorrelationIds):
            return correlation
        if isinstance(correlation, Mapping) and correlation:
            try:
                return CorrelationIds(**dict(correlation))  # type: ignore[arg-type]
            except TypeError:
                known = {
                    k: v
                    for k, v in correlation.items()
                    if k in CorrelationIds.__dataclass_fields__  # type: ignore[attr-defined]
                }
                if known:
                    return CorrelationIds(**known)  # type: ignore[arg-type]
        return CorrelationIds(
            trace_id=f"trace-{event_id}"[:128],
            control_task_id=OBSERVABILITY_CUTOVER_OWNER_TASK,
            control_goal_id="DQK-G1000",
        )

    # -- snapshot (no JSONL) ------------------------------------------------

    def open_snapshot(
        self,
        *,
        snapshot_id: str | None = None,
        families: Sequence[CatalogFamily | str] | None = None,
    ) -> ObservabilityAuthoritySnapshot:
        """Seal one identified snapshot of DuckDB observability authority.

        The snapshot answers audit and progress queries without scanning
        JSONL. Console lines are excluded from authority content.
        """

        with self._lock:
            progress = self._catalog.progress()
            counts = dict(self._catalog.counts())
            fam_list: list[CatalogFamily]
            if families is None:
                fam_list = list(CatalogFamily)
            else:
                fam_list = []
                for item in families:
                    if isinstance(item, CatalogFamily):
                        fam_list.append(item)
                    else:
                        fam_list.append(CatalogFamily(str(item).strip()))

            records: dict[str, tuple[Mapping[str, Any], ...]] = {}
            family_digests: dict[str, str] = {}
            body_families: dict[str, list[dict[str, Any]]] = {}
            for family in fam_list:
                rows = [
                    r.to_dict()  # type: ignore[attr-defined]
                    for r in self._catalog.list_family(family)
                ]
                records[family.value] = tuple(rows)
                body_families[family.value] = rows
                family_digests[family.value] = (
                    "sha256:"
                    + hashlib.sha256(
                        canonical_json_bytes(rows)
                    ).hexdigest()
                )

            # Authority is DuckDB under dual/db-primary; shadow still projects.
            if self.mode in {
                AuthorityMode.DB_PRIMARY,
                AuthorityMode.EXPORT_ONLY,
            }:
                authority = "duckdb"
            elif self.mode is AuthorityMode.DUAL:
                authority = "dual"
            else:
                authority = "legacy"

            snap_token = snapshot_id or (
                f"obs-snap-{hashlib.sha256(canonical_json_bytes({'c': counts, 'p': progress.to_dict()})).hexdigest()[:24]}"
            )
            # Ensure safe token for SnapshotId.
            snap_token = sanitize_action_token(snap_token, default="obs-snap")

            body = {
                "schema": OBSERVABILITY_SNAPSHOT_SCHEMA,
                "snapshot_id": snap_token,
                "mode": self.mode.value,
                "source_revision": self._source_revision,
                "progress": progress.to_dict(),
                "family_counts": counts,
                "family_digests": family_digests,
                "families": body_families,
                "jsonl_scanned": False,
                "console_is_authority": False,
                "owner_task": OBSERVABILITY_CUTOVER_OWNER_TASK,
            }
            raw = canonical_json_bytes(body)
            content = ContentReference.from_bytes(
                raw, media_type=ContentMediaType.JSON
            )
            content.verify_bytes(raw)

            snap = ObservabilityAuthoritySnapshot(
                snapshot_id=snap_token,
                created_at=self._clock(),
                mode=self.mode.value,
                source_revision=self._source_revision,
                progress=progress.to_dict(),
                family_counts=MappingProxyType(counts),
                family_digests=MappingProxyType(family_digests),
                records=MappingProxyType(records),
                content_cid=content.content_id,
                content_digest=content.source_digest,
                authority=authority,
                owner_task=OBSERVABILITY_CUTOVER_OWNER_TASK,
                jsonl_scanned=False,
                console_is_authority=False,
            )
            self._snapshots[snap_token] = snap
            return snap

    # -- retention / compaction with chain preservation ---------------------

    def compact(
        self,
        *,
        dry_run: bool = False,
        compaction_id: str | None = None,
    ) -> CompactionReceipt:
        """Apply retention and preserve hash-chain + acceptance evidence.

        Protected from eviction:

        * Acceptance-evidence event IDs
        * Current hash-chain head event IDs (per family)

        Chain digests are re-anchored after a non-dry-run compaction.
        """

        with self._lock:
            pre_chains = self._capture_hash_chains()
            acceptance_ids = tuple(sorted(self._acceptance_event_ids))
            protected_ids = set(acceptance_ids) | set(
                self._hash_chain_heads.values()
            )

            # Selective retention: drop only non-protected overflow sequences.
            retention_receipts: list[RetentionReceipt] = []
            removed_total = 0
            retained_total = 0
            for family in CatalogFamily:
                rows = list(self._catalog.list_family(family))
                limit = self._catalog.retention.limit_for(family)
                rows_sorted = sorted(
                    rows, key=lambda r: int(getattr(r, "sequence", 0) or 0)
                )
                remove_seqs: set[int] = set()
                if len(rows_sorted) > limit:
                    overflow = rows_sorted[: len(rows_sorted) - limit]
                    for row in overflow:
                        eid = str(
                            getattr(row, "event_id", None)
                            or getattr(row, "sample_id", None)
                            or getattr(row, "profile_id", None)
                            or getattr(row, "transition_id", None)
                            or getattr(row, "letter_id", None)
                            or getattr(row, "trace_id", None)
                            or ""
                        )
                        if eid and eid in protected_ids:
                            continue
                        remove_seqs.add(int(getattr(row, "sequence", 0) or 0))

                removed_count = len(remove_seqs)
                retained_count = len(rows) - removed_count
                removed_total += removed_count
                retained_total += max(retained_count, 0)
                max_removed = max(remove_seqs) if remove_seqs else 0
                policy_id = content_identity(
                    self._catalog.retention.to_dict()
                )
                if not dry_run and remove_seqs:
                    self._catalog._selective_drop(family, remove_seqs)  # noqa: SLF001
                retention_receipts.append(
                    RetentionReceipt(
                        family=family.value,
                        removed_count=removed_count,
                        retained_count=max(retained_count, 0),
                        max_sequence_removed=max_removed,
                        applied_at=self._clock(),
                        policy_identity=policy_id,
                        dry_run=dry_run,
                    )
                )

            if not dry_run:
                self._reanchor_chains_after_retention()

            post_chains = self._capture_hash_chains()
            chain_by_family = {c.family: c for c in pre_chains}
            for c in post_chains:
                chain_by_family[c.family] = c
            chains = tuple(chain_by_family.values())
            preserved = tuple(
                sorted({c.chain_digest for c in chains if c.chain_digest})
            )

            surviving_acceptance: list[str] = []
            for eid in acceptance_ids:
                found = any(
                    self._catalog.get(family, eid) is not None
                    for family in CatalogFamily
                )
                if found or dry_run:
                    surviving_acceptance.append(eid)

            receipt = CompactionReceipt(
                compaction_id=compaction_id
                or f"compact-{uuid.uuid4().hex[:12]}",
                applied_at=self._clock(),
                retention_receipts=tuple(
                    r.to_dict() for r in retention_receipts
                ),
                hash_chains=chains,
                acceptance_evidence_ids=tuple(surviving_acceptance),
                preserved_chain_digests=preserved,
                removed_total=removed_total,
                retained_total=retained_total,
                mode=self.mode.value,
            )
            self._compaction_receipts.append(receipt)
            if self.mode is not AuthorityMode.EXPORT_ONLY:
                try:
                    self._port.write(
                        f"obs:compaction:{receipt.compaction_id}",
                        receipt.to_dict(),
                        operation_id=f"op-compact-{receipt.compaction_id}",
                    )
                except Exception:  # noqa: BLE001 — receipt is local evidence
                    pass
            return receipt

    def _capture_hash_chains(self) -> tuple[HashChainEvidence, ...]:
        chains: list[HashChainEvidence] = []
        for family, head in self._hash_chain_heads.items():
            # Count links from lifecycle previous_event_id when available.
            link_count = 0
            if family == CatalogFamily.LIFECYCLE_EVENTS.value:
                rows = self._catalog.list_family(CatalogFamily.LIFECYCLE_EVENTS)
                link_count = sum(
                    1
                    for r in rows
                    if getattr(r, "previous_event_id", "")
                )
            head_seq = 0
            for fam in CatalogFamily:
                row = self._catalog.get(fam, head)
                if row is not None:
                    head_seq = int(getattr(row, "sequence", 0) or 0)
                    break
            acceptance = tuple(
                eid
                for eid in sorted(self._acceptance_event_ids)
                if any(
                    self._catalog.get(f, eid) is not None for f in CatalogFamily
                )
            )
            chains.append(
                HashChainEvidence(
                    family=family,
                    head_event_id=head,
                    head_sequence=head_seq,
                    chain_digest=self._hash_chain_digests.get(family, ""),
                    acceptance_event_ids=acceptance,
                    link_count=link_count,
                )
            )
        return tuple(chains)

    def _reanchor_chains_after_retention(self) -> None:
        """Recompute chain heads from surviving catalog rows."""

        # Lifecycle previous_event_id chain.
        life_rows = list(
            self._catalog.list_family(CatalogFamily.LIFECYCLE_EVENTS)
        )
        if life_rows:
            life_rows.sort(key=lambda r: int(getattr(r, "sequence", 0) or 0))
            head = life_rows[-1]
            eid = str(getattr(head, "event_id", "") or "")
            seq = int(getattr(head, "sequence", 0) or 0)
            prev = str(getattr(head, "previous_event_id", "") or "")
            material = {
                "family": CatalogFamily.LIFECYCLE_EVENTS.value,
                "event_id": eid,
                "sequence": seq,
                "previous_event_id": prev,
                "prior_digest": self._hash_chain_digests.get(
                    CatalogFamily.LIFECYCLE_EVENTS.value, ""
                ),
                "reanchor": True,
            }
            digest = (
                "sha256:"
                + hashlib.sha256(canonical_json_bytes(material)).hexdigest()
            )
            self._hash_chain_heads[CatalogFamily.LIFECYCLE_EVENTS.value] = eid
            self._hash_chain_digests[
                CatalogFamily.LIFECYCLE_EVENTS.value
            ] = digest
        else:
            self._hash_chain_heads.pop(
                CatalogFamily.LIFECYCLE_EVENTS.value, None
            )

        # Acceptance evidence set: drop IDs no longer present.
        survivors: set[str] = set()
        for eid in self._acceptance_event_ids:
            for family in CatalogFamily:
                if self._catalog.get(family, eid) is not None:
                    survivors.add(eid)
                    break
        self._acceptance_event_ids = survivors

    # -- recovery / parity --------------------------------------------------

    def recover(self) -> dict[str, Any]:
        return self._port.recover_outbox()

    def emit_parity(
        self, event_id: str, *, operation_id: str = ""
    ) -> ParityReceipt:
        receipt = self.get_receipt(event_id)
        if receipt is None:
            raise ObservabilityCutoverError(f"unknown event_id {event_id!r}")
        key = f"obs:{receipt.producer}:{receipt.event_id}"
        return self._port.emit_parity_receipt(
            key, operation_id=operation_id or receipt.operation_id
        )

    def counts(self) -> Mapping[str, int]:
        with self._lock:
            base = dict(self._catalog.counts())
            base["receipts"] = len(self._receipts)
            base["snapshots"] = len(self._snapshots)
            base["decisions"] = len(self._decision_receipts)
            base["acceptance_evidence"] = len(self._acceptance_event_ids)
            return MappingProxyType(base)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": OBSERVABILITY_CUTOVER_SCHEMA,
            "owner_task": OBSERVABILITY_CUTOVER_OWNER_TASK,
            "interface": OBSERVABILITY_CUTOVER_INTERFACE,
            "source_revision": self._source_revision,
            "mode": self.mode.value,
            "domain": self._domain,
            "enabled": self._enabled,
            "duckdb_is_authority": self.duckdb_is_authority,
            "legacy_is_outbox_projection": self.legacy_is_outbox_projection,
            "console": self._console.to_dict(),
            "backpressure": self.backpressure_state().to_dict(),
            "counts": dict(self.counts()),
            "promoted_state_families": sorted(PROMOTED_STATE_FAMILIES),
        }


def _flatten_attributes(
    payload: Mapping[str, Any],
    *,
    prefix: str = "",
    out: MutableMapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Flatten nested maps to JSON-scalar attributes for catalog storage."""

    import json
    import re

    result: dict[str, Any] = out if out is not None else {}
    for key, value in payload.items():
        name = f"{prefix}{key}" if not prefix else f"{prefix}.{key}"
        safe_name = re.sub(r"[^A-Za-z0-9_.:/@+-]+", "_", name)
        safe_name = safe_name.strip("._-") or "attr"
        if len(safe_name) > 128:
            safe_name = safe_name[:128]
        if isinstance(value, Mapping):
            _flatten_attributes(value, prefix=safe_name, out=result)
        elif isinstance(value, (list, tuple)):
            # Catalog attributes require JSON scalars — serialize sequences.
            try:
                text = json.dumps(list(value)[:32], sort_keys=True, default=str)
            except Exception:
                text = str(value)[:256]
            if len(text) > 1024:
                text = text[:1024]
            result[safe_name] = text
        elif value is None or isinstance(value, (bool, int, float, str)):
            if isinstance(value, str) and len(value) > 1024:
                result[safe_name] = value[:1024]
            else:
                result[safe_name] = value
        else:
            result[safe_name] = str(value)[:1024]
    return dict(result)


# ---------------------------------------------------------------------------
# Process-global registry
# ---------------------------------------------------------------------------

_GLOBAL_LOCK = threading.RLock()
_GLOBAL_CUTOVER: ObservabilityCutoverRepository | None = None


def build_observability_cutover(
    *,
    mode: AuthorityMode | str = AuthorityMode.DUAL,
    backend: AuthorityBackend | None = None,
    catalog: ObservabilityCatalog | None = None,
    evidence_store: EvidenceBlobStore | None = None,
    source_revision: str = OBSERVABILITY_CUTOVER_SOURCE_REVISION,
    set_global: bool = False,
    enabled: bool = True,
    clock: Callable[[], str] | None = None,
    max_queue: int = _MAX_QUEUE_DEFAULT,
    console: ConsoleProjection | None = None,
    retention: RetentionPolicy | None = None,
) -> ObservabilityCutoverRepository:
    """Construct a cutover repository; optionally install as process global."""

    repo = ObservabilityCutoverRepository(
        mode=mode,
        backend=backend,
        catalog=catalog,
        evidence_store=evidence_store,
        source_revision=source_revision,
        enabled=enabled,
        clock=clock,
        max_queue=max_queue,
        console=console,
        retention=retention,
    )
    if set_global:
        with _GLOBAL_LOCK:
            global _GLOBAL_CUTOVER
            _GLOBAL_CUTOVER = repo
    return repo


def configure_observability_cutover(
    *,
    mode: AuthorityMode | str = AuthorityMode.DUAL,
    backend: AuthorityBackend | None = None,
    catalog: ObservabilityCatalog | None = None,
    evidence_store: EvidenceBlobStore | None = None,
    source_revision: str = OBSERVABILITY_CUTOVER_SOURCE_REVISION,
    enabled: bool = True,
    clock: Callable[[], str] | None = None,
    max_queue: int = _MAX_QUEUE_DEFAULT,
    console: ConsoleProjection | None = None,
    retention: RetentionPolicy | None = None,
) -> ObservabilityCutoverRepository:
    """Install (or replace) the process-global observability cutover repository."""

    return build_observability_cutover(
        mode=mode,
        backend=backend,
        catalog=catalog,
        evidence_store=evidence_store,
        source_revision=source_revision,
        set_global=True,
        enabled=enabled,
        clock=clock,
        max_queue=max_queue,
        console=console,
        retention=retention,
    )


def get_observability_cutover() -> ObservabilityCutoverRepository | None:
    with _GLOBAL_LOCK:
        return _GLOBAL_CUTOVER


def clear_observability_cutover() -> None:
    with _GLOBAL_LOCK:
        global _GLOBAL_CUTOVER
        _GLOBAL_CUTOVER = None


def reset_observability_cutover() -> None:
    clear_observability_cutover()


def record_observability_authority_event(
    *,
    producer: ObservabilityProducer | str,
    action: str,
    actor: str = "system",
    outcome: str = "info",
    detail: str = "",
    attributes: Mapping[str, Any] | None = None,
    event_id: str | None = None,
    operation_id: str | None = None,
    classification: SensitivityClass | str | None = None,
    resource: str = "",
    domain: TraceDomain | str | None = None,
    raw_payload: Mapping[str, Any] | bytes | str | None = None,
    recorded_at: str | None = None,
    correlation: CorrelationIds | Mapping[str, Any] | None = None,
    source_revision: str | None = None,
    kind: EventKind | str | None = None,
    priority: WritePriority | None = None,
    acceptance_evidence: bool = False,
    **kind_kwargs: Any,
) -> ObservabilityEventReceipt | None:
    """Route an event through the global cutover repository when configured.

    Returns ``None`` when cutover is not configured. Never raises for routing
    failures from producers — errors are swallowed so legacy sinks remain
    operational.
    """

    repo = get_observability_cutover()
    if repo is None or not repo.enabled:
        return None
    try:
        return repo.record_event(
            producer=producer,
            action=action,
            actor=actor,
            outcome=outcome,
            detail=detail,
            attributes=attributes,
            event_id=event_id,
            operation_id=operation_id,
            classification=classification,
            resource=resource,
            domain=domain,
            raw_payload=raw_payload,
            recorded_at=recorded_at,
            correlation=correlation,
            source_revision=source_revision,
            kind=kind,
            priority=priority,
            acceptance_evidence=acceptance_evidence,
            **{
                k: v
                for k, v in kind_kwargs.items()
                if k
                in {
                    "component",
                    "metric_status",
                    "latency_ms",
                    "error_rate_bps",
                    "trace_name",
                    "query_text",
                    "template_id",
                    "blocker_id",
                    "blocker_type",
                    "from_state",
                    "to_state",
                    "blocker_reason",
                }
            },
        )
    except Exception:  # noqa: BLE001 — never break legacy producers
        return None


def try_record_observability_event(
    *,
    producer: ObservabilityProducer | str,
    action: str,
    actor: str = "system",
    outcome: str = "info",
    detail: str = "",
    attributes: Mapping[str, Any] | None = None,
    event_id: str | None = None,
    operation_id: str | None = None,
    classification: SensitivityClass | str | None = None,
    resource: str = "",
    domain: TraceDomain | str | None = None,
    raw_payload: Mapping[str, Any] | bytes | str | None = None,
    recorded_at: str | None = None,
    correlation: CorrelationIds | Mapping[str, Any] | None = None,
    source_revision: str | None = None,
    kind: EventKind | str | None = None,
    priority: WritePriority | None = None,
    acceptance_evidence: bool = False,
    **extra: Any,
) -> bool:
    """Try cutover first, then shadow adapters.

    Returns True when an authority or shadow receipt was produced.
    """

    receipt = record_observability_authority_event(
        producer=producer,
        action=action,
        actor=actor,
        outcome=outcome,
        detail=detail,
        attributes=attributes,
        event_id=event_id,
        operation_id=operation_id,
        classification=classification,
        resource=resource,
        domain=domain,
        raw_payload=raw_payload,
        recorded_at=recorded_at,
        correlation=correlation,
        source_revision=source_revision,
        kind=kind,
        priority=priority,
        acceptance_evidence=acceptance_evidence,
        **extra,
    )
    if receipt is not None:
        return True

    try:
        from ipfs_datasets_py.duckdb_control.observability_adapters import (
            record_observability_event,
        )

        shadow_receipt = record_observability_event(
            producer=producer,
            action=action,
            actor=actor,
            outcome=outcome,
            detail=detail,
            attributes=attributes,
            event_id=event_id,
            operation_id=operation_id,
            classification=classification,
            resource=resource,
            domain=domain,
            raw_payload=raw_payload,
            recorded_at=recorded_at,
            correlation=correlation,
            source_revision=source_revision,
        )
        return shadow_receipt is not None
    except Exception:  # noqa: BLE001
        return False
