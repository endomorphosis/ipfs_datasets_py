"""Continuous, fair batching primitives for Leanstral audit inference.

The audit contracts and validation code live in :mod:`leanstral_audit`.  This
module deliberately keeps scheduling separate from those trust decisions: it
only decides which compatible requests may share an inference call.  Every
response is still admitted by the request-specific deterministic validator.

The scheduler is synchronous and thread safe.  Producers may enqueue work as
it arrives while an async worker periodically calls :meth:`pop_ready_batch`.
That small interface also makes scheduling deterministic and easy to test
without an event-loop or a model server.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import threading
import time
from collections import defaultdict, deque
from dataclasses import asdict, dataclass, field
from typing import Any, AsyncIterator, Awaitable, Deque, Dict, List, Mapping, Optional, Sequence, Tuple

from ipfs_datasets_py.utils import anyio_compat as anyio_runtime


LEANSTRAL_BATCH_SCHEDULER_SCHEMA_VERSION = "legal-ir-leanstral-batch-scheduler-v1"
LEANSTRAL_BATCH_TELEMETRY_SCHEMA_VERSION = "legal-ir-leanstral-batch-telemetry-v1"
LEANSTRAL_CONTINUOUS_SERVICE_SCHEMA_VERSION = "legal-ir-leanstral-continuous-service-v1"


class LeanstralQueueBackpressureError(RuntimeError):
    """Raised when a Leanstral request is rejected before provider admission."""

    def __init__(self, *, queued_count: int, max_queue_items: int) -> None:
        self.queued_count = max(0, int(queued_count))
        self.max_queue_items = max(0, int(max_queue_items))
        self.reason = "leanstral_queue_backpressure"
        super().__init__(
            "Leanstral audit queue backpressure: "
            f"queued={self.queued_count} max_queue_items={self.max_queue_items}"
        )


@dataclass(frozen=True, order=True)
class LeanstralBatchKey:
    """The compatibility identity for one provider batch.

    Provider and prompt mode are included in addition to the required model,
    theorem-template, logic-family, token-budget, and deadline axes.  Sending
    unlike provider modes in one call would make mesh/local routing ambiguous.
    """

    model: str
    theorem_template: str
    logic_family: str
    token_budget_bucket: int
    deadline_bucket: int
    provider: str = "leanstral_local"
    prompt_kind: str = "audit"
    use_mesh: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class LeanstralBatchSchedulerConfig:
    """Bounds used while continuously forming inference batches."""

    min_batch_size: int = 4
    max_batch_size: int = 8
    max_queue_items: int = 0
    max_wait_seconds: float = 0.050
    token_budget_bucket_size: int = 256
    deadline_bucket_seconds: float = 1.0
    deadline_guard_seconds: float = 0.010

    def bounded_min_batch_size(self) -> int:
        return min(self.bounded_max_batch_size(), max(1, int(self.min_batch_size or 1)))

    def bounded_max_batch_size(self) -> int:
        return max(1, min(64, int(self.max_batch_size or 1)))

    def bounded_max_queue_items(self) -> int:
        return max(0, int(self.max_queue_items or 0))

    def bounded_max_wait_seconds(self) -> float:
        return _finite_nonnegative(self.max_wait_seconds, 0.050)

    def bounded_token_bucket_size(self) -> int:
        return max(1, int(self.token_budget_bucket_size or 1))

    def bounded_deadline_bucket_seconds(self) -> float:
        value = _finite_nonnegative(self.deadline_bucket_seconds, 1.0)
        return value if value > 0.0 else 1.0

    def bounded_deadline_guard_seconds(self) -> float:
        return _finite_nonnegative(self.deadline_guard_seconds, 0.010)


@dataclass(frozen=True)
class LeanstralScheduledItem:
    """One queued request plus scheduling-only metadata."""

    work_item: Any
    request_id: str
    key: LeanstralBatchKey
    token_budget: int
    deadline_monotonic: float
    enqueued_monotonic: float
    sequence: int

    @property
    def logic_family(self) -> str:
        return self.key.logic_family


@dataclass(frozen=True)
class LeanstralInferenceBatch:
    """A bounded ordered group safe to submit in one inference call."""

    batch_id: str
    key: LeanstralBatchKey
    items: Sequence[LeanstralScheduledItem]
    formed_monotonic: float
    formation_reason: str

    @property
    def request_ids(self) -> Tuple[str, ...]:
        return tuple(item.request_id for item in self.items)

    @property
    def work_items(self) -> Tuple[Any, ...]:
        return tuple(item.work_item for item in self.items)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "batch_id": self.batch_id,
            "formation_reason": self.formation_reason,
            "key": self.key.to_dict(),
            "request_ids": list(self.request_ids),
            "size": len(self.items),
        }


@dataclass
class LeanstralBatchTelemetry:
    """Source-free aggregate telemetry for a scheduler run."""

    enqueued_count: int = 0
    backpressure_rejection_count: int = 0
    cache_hit_count: int = 0
    cancelled_count: int = 0
    deadline_expired_count: int = 0
    formed_batch_count: int = 0
    dispatched_item_count: int = 0
    forced_batch_count: int = 0
    full_batch_count: int = 0
    wait_flush_count: int = 0
    reassociated_response_count: int = 0
    retry_count: int = 0
    schema_repair_count: int = 0
    provider_error_count: int = 0
    mesh_batch_count: int = 0
    direct_local_batch_count: int = 0
    estimated_prompt_tokens: int = 0
    estimated_completion_token_budget: int = 0
    estimated_total_tokens: int = 0
    verified_audit_count: int = 0
    cache_value_tokens: int = 0
    marginal_information: float = 0.0
    gpu_seconds: float = 0.0
    healthy_cuda_service_reused: bool = False
    batch_sizes: List[int] = field(default_factory=list)
    family_dispatch_counts: Dict[str, int] = field(default_factory=dict)

    def record_batch(self, batch: LeanstralInferenceBatch) -> None:
        size = len(batch.items)
        self.formed_batch_count += 1
        self.dispatched_item_count += size
        self.batch_sizes.append(size)
        family = batch.key.logic_family
        self.family_dispatch_counts[family] = self.family_dispatch_counts.get(family, 0) + size
        if batch.key.use_mesh:
            self.mesh_batch_count += 1
        else:
            self.direct_local_batch_count += 1
        if batch.formation_reason == "full":
            self.full_batch_count += 1
        elif batch.formation_reason == "forced":
            self.forced_batch_count += 1
        elif batch.formation_reason in {"max_wait", "deadline"}:
            self.wait_flush_count += 1

    def record_backpressure_rejection(self) -> None:
        self.backpressure_rejection_count += 1

    def record_cache_hit(self, *, tokens: int = 0, marginal_information: float = 0.0) -> None:
        self.cache_hit_count += 1
        self.cache_value_tokens += max(0, int(tokens or 0))
        self.marginal_information += _finite_nonnegative(marginal_information, 0.0)

    def record_efficiency(
        self,
        *,
        prompt_tokens: int = 0,
        completion_token_budget: int = 0,
        verified_audits: int = 0,
        cache_value_tokens: int = 0,
        marginal_information: float = 0.0,
        gpu_seconds: float = 0.0,
    ) -> None:
        prompt = max(0, int(prompt_tokens or 0))
        completion = max(0, int(completion_token_budget or 0))
        self.estimated_prompt_tokens += prompt
        self.estimated_completion_token_budget += completion
        self.estimated_total_tokens += prompt + completion
        self.verified_audit_count += max(0, int(verified_audits or 0))
        self.cache_value_tokens += max(0, int(cache_value_tokens or 0))
        self.marginal_information += _finite_nonnegative(marginal_information, 0.0)
        self.gpu_seconds += _finite_nonnegative(gpu_seconds, 0.0)

    def to_dict(self, *, queued_count: int = 0) -> Dict[str, Any]:
        sizes = list(self.batch_sizes)
        dispatched = max(0, int(self.dispatched_item_count))
        gpu_seconds = _finite_nonnegative(self.gpu_seconds, 0.0)
        total_tokens = max(0, int(self.estimated_total_tokens))
        return {
            "average_batch_size": round(dispatched / len(sizes), 6) if sizes else 0.0,
            "backpressure_rejection_count": int(self.backpressure_rejection_count),
            "batch_sizes": sizes,
            "cache_hit_count": int(self.cache_hit_count),
            "cache_value_per_gpu_second": _per_second(self.cache_value_tokens, gpu_seconds),
            "cache_value_tokens": int(self.cache_value_tokens),
            "cancelled_count": int(self.cancelled_count),
            "deadline_expired_count": int(self.deadline_expired_count),
            "direct_local_batch_count": int(self.direct_local_batch_count),
            "dispatched_item_count": dispatched,
            "enqueued_count": int(self.enqueued_count),
            "estimated_completion_token_budget": int(self.estimated_completion_token_budget),
            "estimated_prompt_tokens": int(self.estimated_prompt_tokens),
            "estimated_total_tokens": total_tokens,
            "family_dispatch_counts": dict(sorted(self.family_dispatch_counts.items())),
            "forced_batch_count": int(self.forced_batch_count),
            "formed_batch_count": int(self.formed_batch_count),
            "full_batch_count": int(self.full_batch_count),
            "gpu_seconds": round(gpu_seconds, 6),
            "healthy_cuda_service_reused": bool(self.healthy_cuda_service_reused),
            "marginal_information": round(float(self.marginal_information), 6),
            "marginal_information_per_gpu_second": _per_second(
                self.marginal_information,
                gpu_seconds,
            ),
            "mesh_batch_count": int(self.mesh_batch_count),
            "proof_authority": False,
            "provider_error_count": int(self.provider_error_count),
            "queued_count": max(0, int(queued_count)),
            "reassociated_response_count": int(self.reassociated_response_count),
            "retry_count": int(self.retry_count),
            "schema_repair_count": int(self.schema_repair_count),
            "schema_version": LEANSTRAL_BATCH_TELEMETRY_SCHEMA_VERSION,
            "tokens_per_gpu_second": _per_second(total_tokens, gpu_seconds),
            "verified_audit_count": int(self.verified_audit_count),
            "verified_audits_per_gpu_second": _per_second(
                self.verified_audit_count,
                gpu_seconds,
            ),
            "wait_flush_count": int(self.wait_flush_count),
        }


class LeanstralBatchScheduler:
    """Continuously form compatible batches with round-robin family fairness."""

    def __init__(
        self,
        config: Optional[LeanstralBatchSchedulerConfig] = None,
        *,
        clock: Optional[Any] = None,
    ) -> None:
        self.config = config or LeanstralBatchSchedulerConfig()
        self._clock = clock or time.monotonic
        self._queues: Dict[LeanstralBatchKey, Deque[LeanstralScheduledItem]] = defaultdict(deque)
        self._request_keys: Dict[str, LeanstralBatchKey] = {}
        self._cancelled: set[str] = set()
        self._terminal: List[Tuple[LeanstralScheduledItem, str]] = []
        self._family_ring: List[str] = []
        self._family_cursor = 0
        self._sequence = 0
        self._closed = False
        self._lock = threading.RLock()
        self.telemetry = LeanstralBatchTelemetry()

    def enqueue(
        self,
        work_item: Any,
        *,
        model: Optional[str] = None,
        theorem_template: Optional[str] = None,
        logic_family: Optional[str] = None,
        token_budget: Optional[int] = None,
        deadline_monotonic: Optional[float] = None,
        provider: Optional[str] = None,
        prompt_kind: Optional[str] = None,
        use_mesh: bool = True,
        now: Optional[float] = None,
    ) -> LeanstralScheduledItem:
        """Queue a work item, deriving safe defaults from its audit request."""

        current = self._now(now)
        metadata = leanstral_batch_metadata(work_item)
        request_id = str(metadata["request_id"])
        if not request_id:
            raise ValueError("Leanstral batch items require a stable request_id")
        budget = max(1, int(token_budget or metadata["token_budget"] or 1))
        deadline = _finite_deadline(deadline_monotonic, current + 300.0)
        bucket_size = self.config.bounded_token_bucket_size()
        deadline_width = self.config.bounded_deadline_bucket_seconds()
        key = LeanstralBatchKey(
            model=_token(model or metadata["model"], "Leanstral"),
            theorem_template=_token(
                theorem_template or metadata["theorem_template"], "leanstral-audit"
            ),
            logic_family=_token(logic_family or metadata["logic_family"], "legal_ir"),
            token_budget_bucket=int(math.ceil(budget / bucket_size) * bucket_size),
            deadline_bucket=int(math.floor(deadline / deadline_width)),
            provider=_token(provider or metadata["provider"], "leanstral_local"),
            prompt_kind=_token(prompt_kind or metadata["prompt_kind"], "audit"),
            use_mesh=bool(use_mesh),
        )
        with self._lock:
            if self._closed:
                raise RuntimeError("cannot enqueue into a closed Leanstral batch scheduler")
            if request_id in self._request_keys:
                raise ValueError(f"duplicate queued Leanstral request_id: {request_id}")
            max_queue_items = self.config.bounded_max_queue_items()
            queued = self.queued_count
            if max_queue_items and queued >= max_queue_items:
                self.telemetry.record_backpressure_rejection()
                raise LeanstralQueueBackpressureError(
                    queued_count=queued,
                    max_queue_items=max_queue_items,
                )
            self._sequence += 1
            item = LeanstralScheduledItem(
                work_item=work_item,
                request_id=request_id,
                key=key,
                token_budget=budget,
                deadline_monotonic=deadline,
                enqueued_monotonic=current,
                sequence=self._sequence,
            )
            self._queues[key].append(item)
            self._request_keys[request_id] = key
            if key.logic_family not in self._family_ring:
                self._family_ring.append(key.logic_family)
            self.telemetry.enqueued_count += 1
            return item

    # Friendly aliases for producer-oriented callers.
    submit = enqueue

    def cancel(self, request_id: str) -> bool:
        """Cancel a queued request without disturbing other batch members."""

        value = str(request_id or "").strip()
        with self._lock:
            if not value or value not in self._request_keys:
                return False
            self._cancelled.add(value)
            return True

    cancel_request = cancel

    def close(self) -> None:
        """Mark the producer side complete so partial batches may be flushed."""

        with self._lock:
            self._closed = True

    @property
    def closed(self) -> bool:
        with self._lock:
            return self._closed

    def pop_ready_batch(
        self,
        *,
        force: bool = False,
        now: Optional[float] = None,
    ) -> Optional[LeanstralInferenceBatch]:
        """Return the next fair compatible batch, or ``None`` if none is ready."""

        current = self._now(now)
        with self._lock:
            self._purge_terminal(current)
            candidates = self._ready_keys(current, force=force)
            if not candidates:
                return None
            family = self._choose_family(candidates)
            family_keys = [key for key in candidates if key.logic_family == family]
            key = min(
                family_keys,
                key=lambda candidate: (
                    self._queues[candidate][0].deadline_monotonic,
                    self._queues[candidate][0].sequence,
                    candidate,
                ),
            )
            queue = self._queues[key]
            limit = self.config.bounded_max_batch_size()
            items = tuple(queue.popleft() for _ in range(min(limit, len(queue))))
            for item in items:
                self._request_keys.pop(item.request_id, None)
            if not queue:
                self._queues.pop(key, None)
            reason = self._formation_reason(items, current, force=force)
            batch = LeanstralInferenceBatch(
                batch_id=_batch_id(key, items),
                key=key,
                items=items,
                formed_monotonic=current,
                formation_reason=reason,
            )
            self.telemetry.record_batch(batch)
            self._compact_family_ring()
            return batch

    next_batch = pop_ready_batch

    async def wait_for_batch(
        self,
        *,
        poll_interval_seconds: float = 0.005,
    ) -> Optional[LeanstralInferenceBatch]:
        """Wait for a full, aged, urgent, or end-of-stream partial batch."""

        poll = max(0.001, _finite_nonnegative(poll_interval_seconds, 0.005))
        while True:
            batch = self.pop_ready_batch(force=self.closed)
            if batch is not None:
                return batch
            if self.closed and self.queued_count == 0:
                return None
            await anyio_runtime.sleep(poll)

    async def iter_batches(
        self,
        *,
        poll_interval_seconds: float = 0.005,
    ) -> AsyncIterator[LeanstralInferenceBatch]:
        """Yield batches continuously until :meth:`close` drains the queue."""

        while True:
            batch = await self.wait_for_batch(
                poll_interval_seconds=poll_interval_seconds,
            )
            if batch is None:
                return
            yield batch

    def drain(
        self,
        *,
        force: bool = True,
        now: Optional[float] = None,
    ) -> Tuple[LeanstralInferenceBatch, ...]:
        batches: List[LeanstralInferenceBatch] = []
        while True:
            batch = self.pop_ready_batch(force=force, now=now)
            if batch is None:
                return tuple(batches)
            batches.append(batch)

    def take_terminal_items(self) -> Tuple[Tuple[LeanstralScheduledItem, str], ...]:
        """Return and clear items removed by cancellation or deadline expiry."""

        with self._lock:
            values = tuple(self._terminal)
            self._terminal.clear()
            return values

    @property
    def queued_count(self) -> int:
        with self._lock:
            return sum(len(queue) for queue in self._queues.values())

    def telemetry_snapshot(self) -> Dict[str, Any]:
        with self._lock:
            return self.telemetry.to_dict(queued_count=self.queued_count)

    def _ready_keys(self, now: float, *, force: bool) -> List[LeanstralBatchKey]:
        minimum = self.config.bounded_min_batch_size()
        maximum = self.config.bounded_max_batch_size()
        wait = self.config.bounded_max_wait_seconds()
        guard = self.config.bounded_deadline_guard_seconds()
        ready: List[LeanstralBatchKey] = []
        for key, queue in self._queues.items():
            if not queue:
                continue
            oldest = queue[0]
            if (
                force
                or len(queue) >= maximum
                or len(queue) >= minimum
                or now - oldest.enqueued_monotonic >= wait
                or oldest.deadline_monotonic - now <= guard
            ):
                ready.append(key)
        return ready

    def _choose_family(self, candidates: Sequence[LeanstralBatchKey]) -> str:
        available = {key.logic_family for key in candidates}
        if not self._family_ring:
            return min(available)
        for offset in range(len(self._family_ring)):
            index = (self._family_cursor + offset) % len(self._family_ring)
            family = self._family_ring[index]
            if family in available:
                self._family_cursor = (index + 1) % len(self._family_ring)
                return family
        return min(available)

    def _purge_terminal(self, now: float) -> None:
        for key in list(self._queues):
            queue = self._queues[key]
            retained: Deque[LeanstralScheduledItem] = deque()
            while queue:
                item = queue.popleft()
                reason = ""
                if item.request_id in self._cancelled:
                    reason = "caller_cancelled"
                    self.telemetry.cancelled_count += 1
                elif item.deadline_monotonic <= now:
                    reason = "deadline_expired"
                    self.telemetry.deadline_expired_count += 1
                if reason:
                    self._terminal.append((item, reason))
                    self._request_keys.pop(item.request_id, None)
                    self._cancelled.discard(item.request_id)
                else:
                    retained.append(item)
            if retained:
                self._queues[key] = retained
            else:
                self._queues.pop(key, None)
        self._compact_family_ring()

    def _compact_family_ring(self) -> None:
        active = {key.logic_family for key, queue in self._queues.items() if queue}
        if not active:
            self._family_ring = []
            self._family_cursor = 0
            return
        old_next = (
            self._family_ring[self._family_cursor % len(self._family_ring)]
            if self._family_ring
            else ""
        )
        self._family_ring = [family for family in self._family_ring if family in active]
        for family in sorted(active):
            if family not in self._family_ring:
                self._family_ring.append(family)
        self._family_cursor = (
            self._family_ring.index(old_next)
            if old_next in self._family_ring
            else self._family_cursor % len(self._family_ring)
        )

    def _formation_reason(
        self,
        items: Sequence[LeanstralScheduledItem],
        now: float,
        *,
        force: bool,
    ) -> str:
        if len(items) >= self.config.bounded_max_batch_size():
            return "full"
        if any(
            item.deadline_monotonic - now <= self.config.bounded_deadline_guard_seconds()
            for item in items
        ):
            return "deadline"
        if any(
            now - item.enqueued_monotonic >= self.config.bounded_max_wait_seconds()
            for item in items
        ):
            return "max_wait"
        return "forced" if force else "minimum"

    def _now(self, value: Optional[float]) -> float:
        return _finite_deadline(value, float(self._clock()))


def leanstral_batch_metadata(work_item: Any) -> Dict[str, Any]:
    """Extract scheduling axes from audit or failure-subgoal work."""

    request = getattr(work_item, "request", work_item)
    prompt = _mapping(getattr(request, "prompt", None))
    evidence = _mapping(getattr(request, "evidence", None))
    model_data = _mapping(getattr(request, "model", None))
    cluster = _mapping(evidence.get("cluster"))
    failure = _mapping(evidence.get("failure_subgoal"))
    request_id = str(
        getattr(request, "request_id", "")
        or _mapping(request).get("request_id")
        or ""
    ).strip()
    theorem_template = str(
        failure.get("theorem_template")
        or failure.get("template_id")
        or prompt.get("theorem_template")
        or prompt.get("template")
        or "leanstral-audit"
    ).strip()
    logic_family = str(
        failure.get("logic_family")
        or failure.get("semantic_family")
        or cluster.get("semantic_family")
        or prompt.get("logic_family")
        or "legal_ir"
    ).strip()
    prompt_kind = "failure_branch" if failure else str(prompt.get("prompt_kind") or "audit")
    return {
        "logic_family": logic_family,
        "model": str(model_data.get("model") or "Leanstral"),
        "prompt_kind": prompt_kind,
        "provider": str(model_data.get("provider") or "leanstral_local"),
        "request_id": request_id,
        "theorem_template": theorem_template,
        "token_budget": int(
            _finite_nonnegative(
                failure.get("token_budget", prompt.get("token_budget", 1800)),
                1800.0,
            )
            or 1800
        ),
    }


def _mapping(value: Any) -> Dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _finite_nonnegative(value: Any, default: float) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) and result >= 0.0 else default


def _finite_deadline(value: Any, default: float) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def _per_second(value: float | int, seconds: float) -> float:
    denominator = _finite_nonnegative(seconds, 0.0)
    if denominator <= 0.0:
        return 0.0
    return round(float(value or 0.0) / denominator, 6)


def _token(value: Any, default: str) -> str:
    text = str(value or "").strip()
    return text or default


def _batch_id(
    key: LeanstralBatchKey,
    items: Sequence[LeanstralScheduledItem],
) -> str:
    payload = {
        "key": key.to_dict(),
        "request_ids": [item.request_id for item in items],
        "sequences": [item.sequence for item in items],
    }
    digest = hashlib.sha256(
        json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode(
            "utf-8"
        )
    ).hexdigest()
    return f"leanstral-batch-{digest[:24]}"


@dataclass(frozen=True)
class LeanstralServiceHealth:
    """Provider health metadata for the reusable Leanstral serving process."""

    status: str = "unknown"
    cuda_backed: bool = False
    provider: str = "leanstral_local"
    model: str = "Leanstral"
    base_url: str = ""
    service_id: str = ""
    proof_authority: bool = False

    @property
    def healthy_cuda_backed(self) -> bool:
        return self.status == "healthy" and self.cuda_backed

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class LeanstralContinuousBatchServiceConfig:
    """Operational bounds for the cache-first continuous batching service."""

    scheduler: LeanstralBatchSchedulerConfig = field(
        default_factory=LeanstralBatchSchedulerConfig
    )
    max_queue_items: int = 0
    poll_interval_seconds: float = 0.005
    require_cuda_backed_service: bool = False

    def scheduler_config(self) -> LeanstralBatchSchedulerConfig:
        queue_bound = max(0, int(self.max_queue_items or 0))
        scheduler_queue_bound = self.scheduler.bounded_max_queue_items()
        if scheduler_queue_bound:
            queue_bound = (
                min(queue_bound, scheduler_queue_bound)
                if queue_bound
                else scheduler_queue_bound
            )
        return LeanstralBatchSchedulerConfig(
            min_batch_size=self.scheduler.min_batch_size,
            max_batch_size=self.scheduler.max_batch_size,
            max_queue_items=queue_bound,
            max_wait_seconds=self.scheduler.max_wait_seconds,
            token_budget_bucket_size=self.scheduler.token_budget_bucket_size,
            deadline_bucket_seconds=self.scheduler.deadline_bucket_seconds,
            deadline_guard_seconds=self.scheduler.deadline_guard_seconds,
        )

    def bounded_poll_interval_seconds(self) -> float:
        return max(0.001, _finite_nonnegative(self.poll_interval_seconds, 0.005))


def probe_reusable_cuda_leanstral_service(
    *,
    provider: str = "leanstral_local",
    model: str = "Leanstral",
    env: Optional[Mapping[str, str]] = None,
) -> LeanstralServiceHealth:
    """Infer whether the process is configured to reuse a CUDA Leanstral server."""

    values = dict(os.environ if env is None else env)
    provider_name = _token(provider, "leanstral_local")
    model_name = _token(model, "Leanstral")
    base_url = str(values.get("IPFS_ACCELERATE_LLAMA_CPP_BASE_URL") or "").strip()
    accelerator = str(
        values.get("LEANSTRAL_AUDIT_LLAMA_CPP_RESOLVED_ACCELERATOR")
        or values.get("IPFS_ACCELERATE_LLAMA_CPP_RESOLVED_ACCELERATOR")
        or ""
    ).strip().lower()
    reused = str(values.get("LEANSTRAL_AUDIT_REUSED_LLAMA_SERVER") or "").strip().lower()
    gpu_layers = str(values.get("IPFS_ACCELERATE_LLAMA_CPP_GPU_LAYERS") or "").strip().lower()
    cuda_backed = (
        accelerator == "cuda"
        or reused in {"1", "true", "yes", "on"}
        or (base_url and gpu_layers not in {"", "0", "none", "false"})
    )
    status = "healthy" if cuda_backed and _looks_like_leanstral_model(model_name) else "unknown"
    service_identity = {
        "base_url": base_url,
        "cuda_backed": cuda_backed,
        "model": model_name,
        "provider": provider_name,
    }
    service_id = hashlib.sha256(
        json.dumps(service_identity, ensure_ascii=True, sort_keys=True).encode("utf-8")
    ).hexdigest()[:24]
    return LeanstralServiceHealth(
        status=status,
        cuda_backed=cuda_backed,
        provider=provider_name,
        model=model_name,
        base_url=base_url,
        service_id=f"leanstral-service-{service_id}",
        proof_authority=False,
    )


class LeanstralContinuousBatchService:
    """Cache-first admission and continuous fair batching for audit work items."""

    def __init__(
        self,
        worker: Any,
        config: Optional[LeanstralContinuousBatchServiceConfig] = None,
        *,
        health: Optional[LeanstralServiceHealth] = None,
    ) -> None:
        self.worker = worker
        self.config = config or LeanstralContinuousBatchServiceConfig()
        self.scheduler = LeanstralBatchScheduler(self.config.scheduler_config())
        provider = str(getattr(getattr(worker, "config", None), "provider", "leanstral_local"))
        model = str(getattr(getattr(worker, "config", None), "model", "Leanstral"))
        self.health = health or probe_reusable_cuda_leanstral_service(
            provider=provider,
            model=model,
        )
        self.scheduler.telemetry.healthy_cuda_service_reused = bool(
            self.health.healthy_cuda_backed
        )
        if self.config.require_cuda_backed_service and not self.health.healthy_cuda_backed:
            raise RuntimeError("healthy CUDA-backed Leanstral service is required")
        self._futures_by_request_id: Dict[str, Awaitable[Any]] = {}
        self._work_by_request_id: Dict[str, Any] = {}
        self._accepted_request_ids: List[str] = []
        self._closed = False
        self._lock = threading.RLock()

    @property
    def queued_count(self) -> int:
        return self.scheduler.queued_count

    def submit(self, item: Any, *, now: Optional[float] = None) -> Awaitable[Any]:
        """Admit one item after verified content-addressed cache lookup."""

        from .leanstral_audit import (
            _work_result,
            validate_leanstral_audit_response,
        )

        request = getattr(item, "request", None)
        request_id = str(getattr(request, "request_id", "") or "").strip()
        if not request_id:
            raise ValueError("Leanstral continuous service items require request.request_id")
        future = anyio_runtime.get_event_loop().create_future()
        started = time.monotonic()
        if getattr(self.worker, "is_cancelled", lambda _request_id: False)(request_id):
            future.set_result(
                _work_result(
                    item,
                    status="cancelled",
                    attempts=0,
                    reasons=("caller_cancelled",),
                    elapsed=0.0,
                )
            )
            return future
        cached = self.worker.runner.cache.get_accepted_entry(request)
        if cached is not None:
            tokens = estimate_leanstral_audit_tokens(
                request,
                max_new_tokens=_worker_max_new_tokens(self.worker),
            )
            self.scheduler.telemetry.record_cache_hit(
                tokens=tokens,
                marginal_information=estimate_leanstral_marginal_information(item),
            )
            future.set_result(
                _work_result(
                    item,
                    status="cache_hit",
                    attempts=0,
                    reasons=("cache_hit",),
                    cache_hit=True,
                    llm_called=False,
                    response_hash=cached.response_hash,
                    validation=validate_leanstral_audit_response(request, cached.response),
                    elapsed=time.monotonic() - started,
                )
            )
            return future
        with self._lock:
            if self._closed:
                raise RuntimeError("cannot submit into a closed Leanstral continuous service")
            scheduled = self.scheduler.enqueue(
                item,
                model=getattr(self.worker.config, "model", None),
                token_budget=_worker_max_new_tokens(self.worker),
                deadline_monotonic=time.monotonic()
                + float(getattr(self.worker.config, "timeout", lambda: 300.0)()),
                provider=getattr(self.worker.config, "provider", None),
                use_mesh=bool(getattr(self.worker.config, "batch_use_mesh", True)),
                now=now,
            )
            self._futures_by_request_id[scheduled.request_id] = future
            self._work_by_request_id[scheduled.request_id] = item
            self._accepted_request_ids.append(scheduled.request_id)
        return future

    enqueue = submit

    async def run_until_idle(self, *, close: bool = True) -> None:
        """Dispatch ready batches until the service has no queued work."""

        if close:
            with self._lock:
                self._closed = True
                self.scheduler.close()
        while True:
            batch = await self.scheduler.wait_for_batch(
                poll_interval_seconds=self.config.bounded_poll_interval_seconds(),
            )
            if batch is None:
                self._resolve_terminal_items()
                return
            await self._dispatch_batch(batch)
            self._resolve_terminal_items()

    async def run_items(self, items: Sequence[Any]) -> Tuple[Any, ...]:
        """Submit a finite set of items and return results in submission order."""

        futures: List[Awaitable[Any]] = []
        for item in items:
            futures.append(self.submit(item))
        await self.run_until_idle(close=True)
        return tuple([await future for future in futures])

    async def _dispatch_batch(self, batch: LeanstralInferenceBatch) -> None:
        started = time.monotonic()
        results = tuple(await self.worker._run_items_batch(batch.work_items))
        elapsed = max(0.0, time.monotonic() - started)
        for result in results:
            request_id = str(getattr(result, "request_id", "") or "").strip()
            future = self._futures_by_request_id.pop(request_id, None)
            self._work_by_request_id.pop(request_id, None)
            if future is not None and not future.done():
                future.set_result(result)
        prompt_tokens = sum(
            estimate_leanstral_audit_tokens(
                item.request,
                max_new_tokens=0,
            )
            for item in batch.work_items
        )
        completion_budget = sum(max(0, int(item.token_budget)) for item in batch.items)
        verified = sum(
            1
            for result in results
            if getattr(getattr(result, "validation", None), "accepted", False)
            and getattr(getattr(result, "validation", None), "verified", False)
        )
        marginal = sum(
            estimate_leanstral_marginal_information(item)
            for item in batch.work_items
        )
        self.scheduler.telemetry.record_efficiency(
            prompt_tokens=prompt_tokens,
            completion_token_budget=completion_budget,
            verified_audits=verified,
            marginal_information=marginal,
            gpu_seconds=elapsed if self.health.cuda_backed else 0.0,
        )

    def _resolve_terminal_items(self) -> None:
        from .leanstral_audit import _work_result

        for scheduled, reason in self.scheduler.take_terminal_items():
            future = self._futures_by_request_id.pop(scheduled.request_id, None)
            self._work_by_request_id.pop(scheduled.request_id, None)
            if future is not None and not future.done():
                future.set_result(
                    _work_result(
                        scheduled.work_item,
                        status="cancelled" if reason == "caller_cancelled" else "timeout",
                        attempts=0,
                        reasons=(reason,),
                        elapsed=0.0,
                    )
                )

    def telemetry_snapshot(self) -> Dict[str, Any]:
        payload = self.scheduler.telemetry_snapshot()
        payload["continuous_service"] = {
            "accepted_request_count": len(self._accepted_request_ids),
            "health": self.health.to_dict(),
            "schema_version": LEANSTRAL_CONTINUOUS_SERVICE_SCHEMA_VERSION,
        }
        return payload


def estimate_leanstral_audit_tokens(request: Any, *, max_new_tokens: int = 0) -> int:
    """Return a deterministic local token estimate for efficiency telemetry."""

    try:
        from .leanstral_audit import _leanstral_audit_prompt_text

        prompt = _leanstral_audit_prompt_text(request, payload_mode="daemon")
    except Exception:
        prompt = json.dumps(
            {
                "evidence": _jsonable(getattr(request, "evidence", {})),
                "model": _jsonable(getattr(request, "model", {})),
                "prompt": _jsonable(getattr(request, "prompt", {})),
                "request_id": getattr(request, "request_id", ""),
            },
            ensure_ascii=True,
            sort_keys=True,
        )
    estimated_prompt_tokens = max(1, int(math.ceil(len(prompt.encode("utf-8")) / 4.0)))
    return estimated_prompt_tokens + max(0, int(max_new_tokens or 0))


def estimate_leanstral_marginal_information(item: Any) -> float:
    """Estimate source-free audit value from policy scores and gap magnitudes."""

    cluster = _mapping(getattr(item, "cluster", None))
    request = getattr(item, "request", item)
    evidence = _mapping(getattr(request, "evidence", None))
    if not cluster:
        cluster = _mapping(evidence.get("cluster"))
    policy = _mapping(cluster.get("leanstral_audit_policy"))
    score_fields = (
        "rank_score",
        "mean_normalized_score",
        "heldout_impact",
        "formal_severity",
        "uncertainty",
        "marginal_information",
    )
    score = sum(_finite_nonnegative(policy.get(field), 0.0) for field in score_fields)
    gaps = cluster.get("gaps")
    if isinstance(gaps, Sequence) and not isinstance(gaps, (str, bytes)):
        score += min(1.0, len(gaps) / 10.0)
    learned = _mapping(evidence.get("learned_view_gaps"))
    if learned:
        score += max((_finite_nonnegative(value, 0.0) for value in learned.values()), default=0.0)
    return round(float(score), 6)


def _worker_max_new_tokens(worker: Any) -> int:
    config = getattr(worker, "config", None)
    bounded = getattr(config, "bounded_max_new_tokens", None)
    if callable(bounded):
        return int(bounded())
    return max(32, int(getattr(config, "max_new_tokens", 1800) or 1800))


def _looks_like_leanstral_model(value: Any) -> bool:
    return "leanstral" in str(value or "").strip().lower()


def _jsonable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


# Compatibility exports: callers historically import the operational worker
# from this path even though its audit/checkpoint contracts remain in
# ``leanstral_audit``.
from .leanstral_audit import (  # noqa: E402  (intentional late import)
    LeanstralAuditWorker,
    LeanstralAuditWorkerConfig,
    LeanstralAuditWorkerSummary,
    LeanstralAuditWorkItem,
    LeanstralAuditWorkResult,
)
from .leanstral_audit_policy import (  # noqa: E402  (compatibility exports)
    LEANSTRAL_AUDIT_POLICY_SCHEMA_VERSION,
    LeanstralAuditPolicyConfig,
    LeanstralAuditPolicyDecision,
    LeanstralAuditPolicyOutcome,
    LeanstralAuditPolicyReport,
    leanstral_policy_report_with_cache_hits,
    policy_decision_by_candidate_id,
    select_informative_leanstral_audit_clusters,
)


__all__ = [
    "LEANSTRAL_BATCH_SCHEDULER_SCHEMA_VERSION",
    "LEANSTRAL_BATCH_TELEMETRY_SCHEMA_VERSION",
    "LEANSTRAL_AUDIT_POLICY_SCHEMA_VERSION",
    "LeanstralAuditWorker",
    "LeanstralAuditWorkerConfig",
    "LeanstralAuditPolicyConfig",
    "LeanstralAuditPolicyDecision",
    "LeanstralAuditPolicyOutcome",
    "LeanstralAuditPolicyReport",
    "LeanstralAuditWorkerSummary",
    "LeanstralAuditWorkItem",
    "LeanstralAuditWorkResult",
    "LeanstralBatchKey",
    "LeanstralBatchScheduler",
    "LeanstralBatchSchedulerConfig",
    "LeanstralBatchTelemetry",
    "LeanstralInferenceBatch",
    "LeanstralScheduledItem",
    "leanstral_batch_metadata",
    "leanstral_policy_report_with_cache_hits",
    "policy_decision_by_candidate_id",
    "select_informative_leanstral_audit_clusters",
]
