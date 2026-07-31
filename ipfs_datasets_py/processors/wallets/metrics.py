"""Payload-free structured metrics and run receipts for wallet processors.

WALPROC-G640 implements observability for the multi-chain wallet processor
kernel: provider call/retry/throttle counters, byte and record throughput,
normalization and provider errors, checkpoint age, head lag, reorg rewinds,
finality distribution, and export throughput.

Design constraints (fail closed for privacy and ops safety):

* Metrics and receipts **never** store wallet addresses, raw payloads,
  provider secrets, API keys, memos, calldata, or response bodies.
* Labels are limited to chain namespace, network id, provider name, endpoint
  fingerprints, finality enum values, and opaque run identifiers.
* Resource budgets used for alerts and benchmark gates are derived from
  deterministic fixture measurements and declared operator limits — never
  from live provider latency alone.

Importing this module performs no I/O and opens no network sockets.
"""

from __future__ import annotations

import math
import re
import threading
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from types import MappingProxyType
from typing import Any
from uuid import uuid4

from .errors import InvalidRequestError
from .models import Finality
from .security import endpoint_fingerprint


METRICS_SCHEMA_VERSION = "wallet-processor-metrics-v1"
INGEST_RUN_RECEIPT_SCHEMA_VERSION = "wallet-ingest-run-receipt-v1"
RESOURCE_BUDGET_SCHEMA_VERSION = "wallet-resource-budget-v1"

# Labels that may appear in metric dimensions or receipts.  Anything outside
# this allowlist is rejected so operators cannot accidentally emit secrets.
_SAFE_LABEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@/-]{0,127}$")
_FORBIDDEN_LABEL_FRAGMENTS = frozenset(
    {
        "address",
        "secret",
        "password",
        "apikey",
        "api_key",
        "token",
        "private_key",
        "mnemonic",
        "payload",
        "raw_body",
        "authorization",
        "bearer",
        "seed",
    }
)


class MetricErrorCategory(StrEnum):
    """Coarse error buckets safe for logs and dashboards."""

    PROVIDER = "provider"
    NORMALIZATION = "normalization"
    CHECKPOINT = "checkpoint"
    SINK = "sink"
    EXPORT = "export"
    RESOURCE = "resource"
    CANCELLED = "cancelled"
    DEADLINE = "deadline"
    REORG = "reorg"
    UNKNOWN = "unknown"


class LiveSmokeGate(StrEnum):
    """Whether optional live-provider smoke is allowed for a process."""

    DISABLED = "disabled"
    APPROVED = "approved"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _non_negative_int(value: int, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise InvalidRequestError(f"{name} must be a non-negative integer")
    return value


def _positive_int(value: int, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise InvalidRequestError(f"{name} must be a positive integer")
    return value


def _finite_nonnegative_float(value: float, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise InvalidRequestError(f"{name} must be a finite non-negative number")
    result = float(value)
    if not math.isfinite(result) or result < 0:
        raise InvalidRequestError(f"{name} must be a finite non-negative number")
    return result


def _safe_label(value: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise InvalidRequestError(f"{name} must be a non-empty safe label")
    cleaned = value.strip()
    if not _SAFE_LABEL_RE.fullmatch(cleaned):
        raise InvalidRequestError(f"{name} contains disallowed characters")
    lowered = cleaned.lower()
    for fragment in _FORBIDDEN_LABEL_FRAGMENTS:
        if fragment in lowered:
            raise InvalidRequestError(
                f"{name} must not look like a secret or address field"
            )
    # Hex-looking 0x… blobs of wallet-address length are rejected explicitly.
    if cleaned.startswith("0x") and len(cleaned) >= 40:
        raise InvalidRequestError(f"{name} must not contain wallet addresses")
    return cleaned


def _require_finality(value: Finality | str) -> Finality:
    if isinstance(value, Finality):
        return value
    if isinstance(value, str):
        try:
            return Finality(value)
        except ValueError as exc:
            raise InvalidRequestError(f"unknown finality value: {value!r}") from exc
    raise InvalidRequestError("finality must be a Finality enum or string value")


@dataclass(frozen=True, slots=True)
class ResourceBudget:
    """Declared operational ceilings for a run or benchmark gate.

    Budgets are operator-declared or fixture-derived.  They must **not** be
    inferred solely from live provider latency samples.
    """

    max_pages: int = 256
    max_items: int = 50_000
    max_requests: int = 1_000
    max_bytes: int = 64 * 1024 * 1024
    max_wall_seconds: float = 300.0
    max_peak_memory_bytes: int = 512 * 1024 * 1024
    min_records_per_second: float = 0.0
    source: str = "operator-declared"
    schema_version: str = field(default=RESOURCE_BUDGET_SCHEMA_VERSION, init=False)

    def __post_init__(self) -> None:
        _positive_int(self.max_pages, "max_pages")
        _positive_int(self.max_items, "max_items")
        _positive_int(self.max_requests, "max_requests")
        _positive_int(self.max_bytes, "max_bytes")
        object.__setattr__(
            self,
            "max_wall_seconds",
            _finite_nonnegative_float(self.max_wall_seconds, "max_wall_seconds"),
        )
        if self.max_wall_seconds <= 0:
            raise InvalidRequestError("max_wall_seconds must be positive")
        _positive_int(self.max_peak_memory_bytes, "max_peak_memory_bytes")
        object.__setattr__(
            self,
            "min_records_per_second",
            _finite_nonnegative_float(
                self.min_records_per_second, "min_records_per_second"
            ),
        )
        object.__setattr__(self, "source", _safe_label(self.source, "source"))
        if self.source in {"live-provider-latency", "live_provider_latency"}:
            raise InvalidRequestError(
                "resource budgets must not be sourced from live provider "
                "latency alone; use fixture benchmarks or operator policy"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "max_pages": self.max_pages,
            "max_items": self.max_items,
            "max_requests": self.max_requests,
            "max_bytes": self.max_bytes,
            "max_wall_seconds": self.max_wall_seconds,
            "max_peak_memory_bytes": self.max_peak_memory_bytes,
            "min_records_per_second": self.min_records_per_second,
            "source": self.source,
        }

    @classmethod
    def fixture_default(cls) -> "ResourceBudget":
        """Conservative budget calibrated for offline fixture runs only."""

        return cls(
            max_pages=64,
            max_items=10_000,
            max_requests=256,
            max_bytes=16 * 1024 * 1024,
            max_wall_seconds=60.0,
            max_peak_memory_bytes=256 * 1024 * 1024,
            min_records_per_second=100.0,
            source="fixture-benchmark",
        )


@dataclass(frozen=True, slots=True)
class LiveSmokePolicy:
    """Gate for optional live-provider smoke exercises.

    Live smoke remains **disabled** unless both an explicit endpoint allowlist
    entry and an operator network-approval token are supplied.
    """

    gate: LiveSmokeGate = LiveSmokeGate.DISABLED
    approved_endpoint_fingerprints: tuple[str, ...] = ()
    network_approval_id: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.gate, LiveSmokeGate):
            raise InvalidRequestError("gate must be a LiveSmokeGate")
        fps: list[str] = []
        for item in self.approved_endpoint_fingerprints:
            if not isinstance(item, str) or not item.startswith("endpoint:"):
                raise InvalidRequestError(
                    "approved_endpoint_fingerprints must use endpoint:<digest> form"
                )
            fps.append(item)
        object.__setattr__(self, "approved_endpoint_fingerprints", tuple(fps))
        if self.network_approval_id is not None:
            object.__setattr__(
                self,
                "network_approval_id",
                _safe_label(self.network_approval_id, "network_approval_id"),
            )
        if self.gate is LiveSmokeGate.APPROVED:
            if not self.approved_endpoint_fingerprints:
                raise InvalidRequestError(
                    "live smoke approval requires at least one endpoint fingerprint"
                )
            if not self.network_approval_id:
                raise InvalidRequestError(
                    "live smoke approval requires an explicit network_approval_id"
                )

    @property
    def is_enabled(self) -> bool:
        return self.gate is LiveSmokeGate.APPROVED

    def allows_endpoint(self, url: str) -> bool:
        if not self.is_enabled:
            return False
        return endpoint_fingerprint(url) in self.approved_endpoint_fingerprints

    def to_dict(self) -> dict[str, Any]:
        return {
            "gate": self.gate.value,
            "approved_endpoint_fingerprints": list(self.approved_endpoint_fingerprints),
            "network_approval_id": self.network_approval_id,
            "is_enabled": self.is_enabled,
        }

    @classmethod
    def disabled(cls) -> "LiveSmokePolicy":
        return cls(gate=LiveSmokeGate.DISABLED)


@dataclass(frozen=True, slots=True)
class MetricsSnapshot:
    """Immutable point-in-time view of :class:`WalletProcessorMetrics`."""

    schema_version: str
    provider_calls: int
    retries: int
    throttles: int
    bytes_in: int
    bytes_out: int
    records_seen: int
    records_normalized: int
    records_accepted: int
    records_duplicate: int
    records_exported: int
    normalization_errors: int
    provider_errors: int
    checkpoint_errors: int
    sink_errors: int
    export_errors: int
    other_errors: int
    reorg_rewinds: int
    shallow_reorgs: int
    deep_reorgs: int
    finality_counts: Mapping[str, int]
    error_category_counts: Mapping[str, int]
    checkpoint_age_seconds: float | None
    head_lag_units: int | None
    head_lag_unit_name: str | None
    last_checkpoint_revision: str | None
    wall_time_seconds: float
    records_per_second: float
    export_records_per_second: float
    peak_memory_bytes: int | None
    labels: Mapping[str, str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "provider_calls": self.provider_calls,
            "retries": self.retries,
            "throttles": self.throttles,
            "bytes_in": self.bytes_in,
            "bytes_out": self.bytes_out,
            "records_seen": self.records_seen,
            "records_normalized": self.records_normalized,
            "records_accepted": self.records_accepted,
            "records_duplicate": self.records_duplicate,
            "records_exported": self.records_exported,
            "normalization_errors": self.normalization_errors,
            "provider_errors": self.provider_errors,
            "checkpoint_errors": self.checkpoint_errors,
            "sink_errors": self.sink_errors,
            "export_errors": self.export_errors,
            "other_errors": self.other_errors,
            "reorg_rewinds": self.reorg_rewinds,
            "shallow_reorgs": self.shallow_reorgs,
            "deep_reorgs": self.deep_reorgs,
            "finality_counts": dict(self.finality_counts),
            "error_category_counts": dict(self.error_category_counts),
            "checkpoint_age_seconds": self.checkpoint_age_seconds,
            "head_lag_units": self.head_lag_units,
            "head_lag_unit_name": self.head_lag_unit_name,
            "last_checkpoint_revision": self.last_checkpoint_revision,
            "wall_time_seconds": self.wall_time_seconds,
            "records_per_second": self.records_per_second,
            "export_records_per_second": self.export_records_per_second,
            "peak_memory_bytes": self.peak_memory_bytes,
            "labels": dict(self.labels),
        }


class WalletProcessorMetrics:
    """Thread-safe, payload-free counters for one processor run or process.

    All mutators accept only numeric deltas and allowlisted labels.  Callers
    must never pass addresses, raw payloads, or secrets into labels.
    """

    __slots__ = (
        "_lock",
        "_started_monotonic",
        "_ended_monotonic",
        "_provider_calls",
        "_retries",
        "_throttles",
        "_bytes_in",
        "_bytes_out",
        "_records_seen",
        "_records_normalized",
        "_records_accepted",
        "_records_duplicate",
        "_records_exported",
        "_normalization_errors",
        "_provider_errors",
        "_checkpoint_errors",
        "_sink_errors",
        "_export_errors",
        "_other_errors",
        "_reorg_rewinds",
        "_shallow_reorgs",
        "_deep_reorgs",
        "_finality_counts",
        "_error_category_counts",
        "_checkpoint_age_seconds",
        "_head_lag_units",
        "_head_lag_unit_name",
        "_last_checkpoint_revision",
        "_peak_memory_bytes",
        "_labels",
    )

    def __init__(self, *, labels: Mapping[str, str] | None = None) -> None:
        self._lock = threading.RLock()
        self._started_monotonic = time.monotonic()
        self._ended_monotonic: float | None = None
        self._provider_calls = 0
        self._retries = 0
        self._throttles = 0
        self._bytes_in = 0
        self._bytes_out = 0
        self._records_seen = 0
        self._records_normalized = 0
        self._records_accepted = 0
        self._records_duplicate = 0
        self._records_exported = 0
        self._normalization_errors = 0
        self._provider_errors = 0
        self._checkpoint_errors = 0
        self._sink_errors = 0
        self._export_errors = 0
        self._other_errors = 0
        self._reorg_rewinds = 0
        self._shallow_reorgs = 0
        self._deep_reorgs = 0
        self._finality_counts: dict[str, int] = {
            state.value: 0 for state in Finality
        }
        self._error_category_counts: dict[str, int] = {
            cat.value: 0 for cat in MetricErrorCategory
        }
        self._checkpoint_age_seconds: float | None = None
        self._head_lag_units: int | None = None
        self._head_lag_unit_name: str | None = None
        self._last_checkpoint_revision: str | None = None
        self._peak_memory_bytes: int | None = None
        safe_labels: dict[str, str] = {}
        if labels:
            for key, value in labels.items():
                safe_labels[_safe_label(str(key), "label key")] = _safe_label(
                    str(value), f"label[{key}]"
                )
        self._labels = safe_labels

    # -- recording helpers -------------------------------------------------

    def record_provider_call(self, count: int = 1) -> None:
        with self._lock:
            self._provider_calls += _non_negative_int(count, "count")

    def record_retry(self, count: int = 1) -> None:
        with self._lock:
            self._retries += _non_negative_int(count, "count")

    def record_throttle(self, count: int = 1) -> None:
        with self._lock:
            self._throttles += _non_negative_int(count, "count")

    def record_bytes(self, *, inbound: int = 0, outbound: int = 0) -> None:
        with self._lock:
            self._bytes_in += _non_negative_int(inbound, "inbound")
            self._bytes_out += _non_negative_int(outbound, "outbound")

    def record_records(
        self,
        *,
        seen: int = 0,
        normalized: int = 0,
        accepted: int = 0,
        duplicate: int = 0,
        exported: int = 0,
    ) -> None:
        with self._lock:
            self._records_seen += _non_negative_int(seen, "seen")
            self._records_normalized += _non_negative_int(normalized, "normalized")
            self._records_accepted += _non_negative_int(accepted, "accepted")
            self._records_duplicate += _non_negative_int(duplicate, "duplicate")
            self._records_exported += _non_negative_int(exported, "exported")

    def record_error(
        self,
        category: MetricErrorCategory | str,
        count: int = 1,
    ) -> None:
        if isinstance(category, str):
            try:
                category = MetricErrorCategory(category)
            except ValueError as exc:
                raise InvalidRequestError(
                    f"unknown error category: {category!r}"
                ) from exc
        if not isinstance(category, MetricErrorCategory):
            raise InvalidRequestError("category must be a MetricErrorCategory")
        n = _non_negative_int(count, "count")
        with self._lock:
            self._error_category_counts[category.value] = (
                self._error_category_counts.get(category.value, 0) + n
            )
            if category is MetricErrorCategory.PROVIDER:
                self._provider_errors += n
            elif category is MetricErrorCategory.NORMALIZATION:
                self._normalization_errors += n
            elif category is MetricErrorCategory.CHECKPOINT:
                self._checkpoint_errors += n
            elif category is MetricErrorCategory.SINK:
                self._sink_errors += n
            elif category is MetricErrorCategory.EXPORT:
                self._export_errors += n
            else:
                self._other_errors += n

    def record_finality(self, finality: Finality | str, count: int = 1) -> None:
        state = _require_finality(finality)
        n = _non_negative_int(count, "count")
        with self._lock:
            self._finality_counts[state.value] = (
                self._finality_counts.get(state.value, 0) + n
            )

    def record_reorg_rewind(
        self,
        *,
        depth_units: int = 0,
        shallow: bool = True,
    ) -> None:
        """Record one reorg rewind event (depth is unit count, never an address)."""

        _non_negative_int(depth_units, "depth_units")
        with self._lock:
            self._reorg_rewinds += 1
            if shallow:
                self._shallow_reorgs += 1
            else:
                self._deep_reorgs += 1

    def observe_checkpoint(
        self,
        *,
        age_seconds: float | None = None,
        revision: str | None = None,
        observed_at: datetime | None = None,
        checkpoint_committed_at: datetime | None = None,
    ) -> None:
        """Update checkpoint age and opaque revision label.

        Prefer supplying ``age_seconds`` directly.  When only timestamps are
        available, age is derived as ``observed_at - checkpoint_committed_at``.
        Revision strings must be opaque (UUIDs / digests), not scopes.
        """

        with self._lock:
            if age_seconds is not None:
                self._checkpoint_age_seconds = _finite_nonnegative_float(
                    age_seconds, "age_seconds"
                )
            elif (
                observed_at is not None
                and checkpoint_committed_at is not None
            ):
                if (
                    not isinstance(observed_at, datetime)
                    or observed_at.tzinfo is None
                    or not isinstance(checkpoint_committed_at, datetime)
                    or checkpoint_committed_at.tzinfo is None
                ):
                    raise InvalidRequestError(
                        "checkpoint timestamps must be timezone-aware datetimes"
                    )
                delta = (observed_at - checkpoint_committed_at).total_seconds()
                self._checkpoint_age_seconds = max(0.0, float(delta))
            if revision is not None:
                self._last_checkpoint_revision = _safe_label(
                    revision, "revision"
                )

    def observe_head_lag(
        self,
        *,
        units: int,
        unit_name: str = "blocks",
    ) -> None:
        """Record numeric head lag (blocks/slots/ledgers) without hashes."""

        with self._lock:
            self._head_lag_units = _non_negative_int(units, "units")
            self._head_lag_unit_name = _safe_label(unit_name, "unit_name")

    def observe_peak_memory(self, bytes_used: int) -> None:
        with self._lock:
            value = _non_negative_int(bytes_used, "bytes_used")
            if self._peak_memory_bytes is None or value > self._peak_memory_bytes:
                self._peak_memory_bytes = value

    def mark_finished(self) -> None:
        with self._lock:
            if self._ended_monotonic is None:
                self._ended_monotonic = time.monotonic()

    def reset(self) -> None:
        """Clear counters while preserving allowlisted labels."""

        with self._lock:
            self._started_monotonic = time.monotonic()
            self._ended_monotonic = None
            self._provider_calls = 0
            self._retries = 0
            self._throttles = 0
            self._bytes_in = 0
            self._bytes_out = 0
            self._records_seen = 0
            self._records_normalized = 0
            self._records_accepted = 0
            self._records_duplicate = 0
            self._records_exported = 0
            self._normalization_errors = 0
            self._provider_errors = 0
            self._checkpoint_errors = 0
            self._sink_errors = 0
            self._export_errors = 0
            self._other_errors = 0
            self._reorg_rewinds = 0
            self._shallow_reorgs = 0
            self._deep_reorgs = 0
            self._finality_counts = {state.value: 0 for state in Finality}
            self._error_category_counts = {
                cat.value: 0 for cat in MetricErrorCategory
            }
            self._checkpoint_age_seconds = None
            self._head_lag_units = None
            self._head_lag_unit_name = None
            self._last_checkpoint_revision = None
            self._peak_memory_bytes = None

    def _wall_time_unlocked(self) -> float:
        end = (
            self._ended_monotonic
            if self._ended_monotonic is not None
            else time.monotonic()
        )
        return max(0.0, end - self._started_monotonic)

    def _throughput_unlocked(self, numerator: int, wall: float) -> float:
        if wall <= 0.0:
            return 0.0 if numerator == 0 else float("inf")
        return float(numerator) / wall

    def snapshot(self) -> MetricsSnapshot:
        with self._lock:
            wall = self._wall_time_unlocked()
            return MetricsSnapshot(
                schema_version=METRICS_SCHEMA_VERSION,
                provider_calls=self._provider_calls,
                retries=self._retries,
                throttles=self._throttles,
                bytes_in=self._bytes_in,
                bytes_out=self._bytes_out,
                records_seen=self._records_seen,
                records_normalized=self._records_normalized,
                records_accepted=self._records_accepted,
                records_duplicate=self._records_duplicate,
                records_exported=self._records_exported,
                normalization_errors=self._normalization_errors,
                provider_errors=self._provider_errors,
                checkpoint_errors=self._checkpoint_errors,
                sink_errors=self._sink_errors,
                export_errors=self._export_errors,
                other_errors=self._other_errors,
                reorg_rewinds=self._reorg_rewinds,
                shallow_reorgs=self._shallow_reorgs,
                deep_reorgs=self._deep_reorgs,
                finality_counts=MappingProxyType(dict(self._finality_counts)),
                error_category_counts=MappingProxyType(
                    dict(self._error_category_counts)
                ),
                checkpoint_age_seconds=self._checkpoint_age_seconds,
                head_lag_units=self._head_lag_units,
                head_lag_unit_name=self._head_lag_unit_name,
                last_checkpoint_revision=self._last_checkpoint_revision,
                wall_time_seconds=wall,
                records_per_second=self._throughput_unlocked(
                    self._records_accepted, wall
                ),
                export_records_per_second=self._throughput_unlocked(
                    self._records_exported, wall
                ),
                peak_memory_bytes=self._peak_memory_bytes,
                labels=MappingProxyType(dict(self._labels)),
            )

    def to_dict(self) -> dict[str, Any]:
        return self.snapshot().to_dict()


@dataclass(frozen=True, slots=True)
class IngestRunReceipt:
    """Structured, payload-free receipt for one ingest or export run.

    Receipts intentionally omit scope strings that may embed addresses.  Use
    an opaque ``run_id`` and the checkpoint revision for correlation instead.
    """

    run_id: str
    status: str
    chain_namespace: str
    network: str
    provider: str
    metrics: MetricsSnapshot
    budget: ResourceBudget | None = None
    live_smoke: LiveSmokePolicy = field(default_factory=LiveSmokePolicy.disabled)
    mode: str = "wallet"
    warnings: tuple[str, ...] = ()
    error_category: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    schema_version: str = field(
        default=INGEST_RUN_RECEIPT_SCHEMA_VERSION, init=False
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "run_id", _safe_label(self.run_id, "run_id"))
        object.__setattr__(self, "status", _safe_label(self.status, "status"))
        object.__setattr__(
            self,
            "chain_namespace",
            _safe_label(self.chain_namespace, "chain_namespace"),
        )
        object.__setattr__(self, "network", _safe_label(self.network, "network"))
        object.__setattr__(self, "provider", _safe_label(self.provider, "provider"))
        object.__setattr__(self, "mode", _safe_label(self.mode, "mode"))
        if not isinstance(self.metrics, MetricsSnapshot):
            raise InvalidRequestError("metrics must be a MetricsSnapshot")
        if self.budget is not None and not isinstance(self.budget, ResourceBudget):
            raise InvalidRequestError("budget must be a ResourceBudget or None")
        if not isinstance(self.live_smoke, LiveSmokePolicy):
            raise InvalidRequestError("live_smoke must be a LiveSmokePolicy")
        cleaned_warnings: list[str] = []
        for warning in self.warnings:
            cleaned_warnings.append(_safe_label(str(warning), "warning"))
        object.__setattr__(self, "warnings", tuple(cleaned_warnings))
        if self.error_category is not None:
            # Accept enum values only.
            try:
                MetricErrorCategory(self.error_category)
            except ValueError as exc:
                raise InvalidRequestError(
                    f"unknown error_category: {self.error_category!r}"
                ) from exc
        for ts_name in ("started_at", "finished_at"):
            value = getattr(self, ts_name)
            if value is not None and (
                not isinstance(value, datetime) or value.tzinfo is None
            ):
                raise InvalidRequestError(
                    f"{ts_name} must be a timezone-aware datetime or None"
                )

    @classmethod
    def from_metrics(
        cls,
        metrics: WalletProcessorMetrics,
        *,
        status: str,
        chain_namespace: str,
        network: str,
        provider: str,
        mode: str = "wallet",
        budget: ResourceBudget | None = None,
        live_smoke: LiveSmokePolicy | None = None,
        warnings: tuple[str, ...] = (),
        error_category: str | None = None,
        run_id: str | None = None,
        started_at: datetime | None = None,
        finished_at: datetime | None = None,
    ) -> "IngestRunReceipt":
        metrics.mark_finished()
        return cls(
            run_id=run_id or f"run-{uuid4().hex[:16]}",
            status=status,
            chain_namespace=chain_namespace,
            network=network,
            provider=provider,
            metrics=metrics.snapshot(),
            budget=budget,
            live_smoke=live_smoke or LiveSmokePolicy.disabled(),
            mode=mode,
            warnings=warnings,
            error_category=error_category,
            started_at=started_at or _utc_now(),
            finished_at=finished_at or _utc_now(),
        )

    def assert_payload_free(self) -> None:
        """Raise if the serialized form contains forbidden privacy fields."""

        payload = self.to_dict()
        forbidden = (
            "address",
            "secret",
            "payload",
            "api_key",
            "private_key",
            "mnemonic",
            "authorization",
            "raw_body",
            "bearer",
        )

        def _walk(node: Any, path: str = "") -> None:
            if isinstance(node, Mapping):
                for key, value in node.items():
                    key_l = str(key).lower()
                    for frag in forbidden:
                        if frag in key_l:
                            raise InvalidRequestError(
                                f"receipt field {path}.{key} is not payload-free"
                            )
                    _walk(value, f"{path}.{key}" if path else str(key))
            elif isinstance(node, (list, tuple)):
                for idx, value in enumerate(node):
                    _walk(value, f"{path}[{idx}]")
            elif isinstance(node, str):
                lowered = node.lower()
                if node.startswith("0x") and len(node) >= 40:
                    raise InvalidRequestError(
                        f"receipt value at {path} looks like an address"
                    )
                for frag in ("begin private", "api_key=", "authorization: bearer"):
                    if frag in lowered:
                        raise InvalidRequestError(
                            f"receipt value at {path} looks like a secret"
                        )

        _walk(payload)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "status": self.status,
            "mode": self.mode,
            "chain_namespace": self.chain_namespace,
            "network": self.network,
            "provider": self.provider,
            "metrics": self.metrics.to_dict(),
            "budget": self.budget.to_dict() if self.budget else None,
            "live_smoke": self.live_smoke.to_dict(),
            "warnings": list(self.warnings),
            "error_category": self.error_category,
            "started_at": (
                self.started_at.isoformat() if self.started_at is not None else None
            ),
            "finished_at": (
                self.finished_at.isoformat() if self.finished_at is not None else None
            ),
        }


def new_run_metrics(
    *,
    chain_namespace: str,
    network: str,
    provider: str,
) -> WalletProcessorMetrics:
    """Construct metrics pre-labeled with safe chain/provider dimensions."""

    return WalletProcessorMetrics(
        labels={
            "chain_namespace": chain_namespace,
            "network": network,
            "provider": provider,
        }
    )


__all__ = [
    "INGEST_RUN_RECEIPT_SCHEMA_VERSION",
    "METRICS_SCHEMA_VERSION",
    "RESOURCE_BUDGET_SCHEMA_VERSION",
    "IngestRunReceipt",
    "LiveSmokeGate",
    "LiveSmokePolicy",
    "MetricErrorCategory",
    "MetricsSnapshot",
    "ResourceBudget",
    "WalletProcessorMetrics",
    "endpoint_fingerprint",
    "new_run_metrics",
]
