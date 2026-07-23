"""Continuous, fair batching primitives for Leanstral audit inference.

The audit contracts and validation code live in :mod:`leanstral_audit`.  This
module deliberately keeps scheduling separate from those trust decisions: it
only decides which compatible requests may share an inference call.  Every
response is still admitted by the request-specific deterministic validator.

The scheduler is synchronous and thread safe.  Producers may enqueue work as
it arrives while an async worker periodically calls :meth:`pop_ready_batch`.
The generation-aware lease manager in this module owns the complementary
runtime contract: one exact model/context identity, one load and preflight per
healthy CUDA generation, and bounded health-triggered replacement.  Neither
scheduling nor service health grants proof authority to model output.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import threading
import time
from collections import defaultdict, deque
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Awaitable, Callable, Deque, Dict, List, Mapping, Optional, Sequence, Tuple

from ipfs_datasets_py.utils import anyio_compat as anyio_runtime


LEANSTRAL_BATCH_SCHEDULER_SCHEMA_VERSION = "legal-ir-leanstral-batch-scheduler-v1"
LEANSTRAL_BATCH_TELEMETRY_SCHEMA_VERSION = "legal-ir-leanstral-batch-telemetry-v1"
LEANSTRAL_CONTINUOUS_SERVICE_SCHEMA_VERSION = "legal-ir-leanstral-continuous-service-v1"
LEANSTRAL_PERSISTENT_SERVICE_SCHEMA_VERSION = "legal-ir-leanstral-persistent-service-v1"
LEANSTRAL_CYCLE_PIPELINE_SCHEMA_VERSION = "legal-ir-leanstral-cycle-pipeline-v1"


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
    queue_seconds: float = 0.0
    inference_seconds: float = 0.0
    verification_seconds: float = 0.0
    restart_seconds: float = 0.0
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

    def record_request_timing(
        self,
        *,
        queue_seconds: float = 0.0,
        inference_seconds: float = 0.0,
        verification_seconds: float = 0.0,
        restart_seconds: float = 0.0,
    ) -> None:
        """Record non-overlapping service phases for throughput diagnosis."""

        self.queue_seconds += _finite_nonnegative(queue_seconds, 0.0)
        self.inference_seconds += _finite_nonnegative(inference_seconds, 0.0)
        self.verification_seconds += _finite_nonnegative(verification_seconds, 0.0)
        self.restart_seconds += _finite_nonnegative(restart_seconds, 0.0)

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
            "inference_seconds": round(_finite_nonnegative(self.inference_seconds, 0.0), 6),
            "leanstral_inference_seconds": round(
                _finite_nonnegative(self.inference_seconds, 0.0), 6
            ),
            "marginal_information": round(float(self.marginal_information), 6),
            "marginal_information_per_gpu_second": _per_second(
                self.marginal_information,
                gpu_seconds,
            ),
            "mesh_batch_count": int(self.mesh_batch_count),
            "proof_authority": False,
            "provider_error_count": int(self.provider_error_count),
            "queue_seconds": round(_finite_nonnegative(self.queue_seconds, 0.0), 6),
            "queued_count": max(0, int(queued_count)),
            "reassociated_response_count": int(self.reassociated_response_count),
            "retry_count": int(self.retry_count),
            "schema_repair_count": int(self.schema_repair_count),
            "schema_version": LEANSTRAL_BATCH_TELEMETRY_SCHEMA_VERSION,
            "restart_seconds": round(_finite_nonnegative(self.restart_seconds, 0.0), 6),
            "tokens_per_gpu_second": _per_second(total_tokens, gpu_seconds),
            "verified_audit_count": int(self.verified_audit_count),
            "verified_audits_per_gpu_second": _per_second(
                self.verified_audit_count,
                gpu_seconds,
            ),
            "wait_flush_count": int(self.wait_flush_count),
            "verification_seconds": round(
                _finite_nonnegative(self.verification_seconds, 0.0), 6
            ),
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
    context_size: int = 0
    context_fingerprint: str = ""
    generation: int = 0
    proof_authority: bool = False

    @property
    def healthy_cuda_backed(self) -> bool:
        return self.status == "healthy" and self.cuda_backed

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class LeanstralServiceIdentityError(RuntimeError):
    """Raised before reuse when model or serving-context identity differs."""


class LeanstralServiceHealthError(RuntimeError):
    """Raised when a newly loaded service generation fails preflight."""


@dataclass(frozen=True)
class LeanstralServiceIdentity:
    """Exact identity of weights and context that may share one CUDA lease.

    Context size alone is insufficient: tokenizer, prompt-template, rope, slot,
    and other serving settings can change semantics without changing the token
    limit.  Callers therefore provide a stable fingerprint of the complete
    context configuration in addition to its explicit size.
    """

    model: str
    context_size: int
    context_fingerprint: str
    provider: str = "leanstral_local"

    def __post_init__(self) -> None:
        object.__setattr__(self, "model", str(self.model or "").strip())
        object.__setattr__(self, "provider", str(self.provider or "").strip())
        object.__setattr__(
            self,
            "context_fingerprint",
            str(self.context_fingerprint or "").strip(),
        )
        object.__setattr__(self, "context_size", int(self.context_size or 0))
        if not self.model:
            raise ValueError("Leanstral service identity requires a model")
        if not self.provider:
            raise ValueError("Leanstral service identity requires a provider")
        if self.context_size <= 0:
            raise ValueError("Leanstral service identity requires a positive context_size")
        if not self.context_fingerprint:
            raise ValueError("Leanstral service identity requires a context_fingerprint")

    def compatible_with(self, other: "LeanstralServiceIdentity") -> bool:
        """Return true only for an exact model/provider/context match."""

        return self == other

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class LeanstralPersistentServiceConfig:
    """Bounds for one process-wide, generation-aware CUDA model lease."""

    max_consecutive_health_failures: int = 2
    require_cuda_backed: bool = True

    def bounded_health_failures(self) -> int:
        return max(1, int(self.max_consecutive_health_failures or 1))


class LeanstralServiceLease:
    """Stable lease object whose service advances atomically by generation.

    Compatible callers receive this same object.  Its properties deliberately
    resolve through the manager so a caller cannot retain a stale model handle
    after the bounded health policy replaces a failed generation.
    """

    def __init__(self, manager: "LeanstralPersistentServiceManager") -> None:
        self._manager = manager

    @property
    def identity(self) -> LeanstralServiceIdentity:
        return self._manager.identity

    @property
    def service(self) -> Any:
        return self._manager.service

    @property
    def service_id(self) -> str:
        return self._manager.service_id

    @property
    def generation(self) -> int:
        return self._manager.generation

    @property
    def health(self) -> LeanstralServiceHealth:
        return self._manager.health


class LeanstralPersistentServiceManager:
    """Own exactly one reusable CUDA Leanstral service and its health policy.

    Loading and preflight are lazy and occur exactly once for each successful
    generation.  A request-level failure never reloads weights: only the
    configured number of *consecutive* health failures advances the generation.
    Model responses remain untrusted and retain ``proof_authority=False``.
    """

    def __init__(
        self,
        identity: LeanstralServiceIdentity,
        *,
        loader: Callable[[LeanstralServiceIdentity], Any],
        preflight: Callable[[Any, LeanstralServiceIdentity], LeanstralServiceHealth],
        restarter: Optional[Callable[[Any, LeanstralServiceIdentity], Any]] = None,
        config: Optional[LeanstralPersistentServiceConfig] = None,
        clock: Optional[Callable[[], float]] = None,
    ) -> None:
        if not isinstance(identity, LeanstralServiceIdentity):
            raise TypeError("identity must be a LeanstralServiceIdentity")
        if not callable(loader):
            raise TypeError("loader must be callable")
        if not callable(preflight):
            raise TypeError("preflight must be callable")
        if restarter is not None and not callable(restarter):
            raise TypeError("restarter must be callable")
        self.identity = identity
        self.config = config or LeanstralPersistentServiceConfig()
        self._loader = loader
        self._preflight = preflight
        self._restarter = restarter
        self._clock = clock or time.monotonic
        self._service: Any = None
        self._health: Optional[LeanstralServiceHealth] = None
        self._lease = LeanstralServiceLease(self)
        self._generation = 0
        self._model_load_count = 0
        self._preflight_count = 0
        self._restart_count = 0
        self._acquire_count = 0
        self._reuse_count = 0
        self._health_failure_count = 0
        self._consecutive_health_failures = 0
        self._healthy_cuda_service_reused = False
        self._queue_seconds = 0.0
        self._inference_seconds = 0.0
        self._verification_seconds = 0.0
        self._restart_seconds = 0.0
        self._last_health_failure_reason = ""
        self._lock = threading.RLock()

    @property
    def service(self) -> Any:
        with self._lock:
            if self._generation <= 0 or self._service is None:
                raise RuntimeError("Leanstral service has not been acquired")
            return self._service

    @property
    def health(self) -> LeanstralServiceHealth:
        with self._lock:
            if self._health is None:
                raise RuntimeError("Leanstral service has not been acquired")
            return self._health

    @property
    def service_id(self) -> str:
        return self.health.service_id

    @property
    def generation(self) -> int:
        with self._lock:
            return self._generation

    def acquire(
        self,
        identity: Optional[LeanstralServiceIdentity] = None,
    ) -> LeanstralServiceLease:
        """Load once or return the one lease after exact identity validation."""

        requested = self.identity if identity is None else identity
        if not isinstance(requested, LeanstralServiceIdentity):
            raise TypeError("identity must be a LeanstralServiceIdentity")
        with self._lock:
            self._validate_identity(requested)
            if self._generation == 0:
                loaded = self._loader(self.identity)
                self._install_generation(loaded, generation=1)
            else:
                self._reuse_count += 1
                self._healthy_cuda_service_reused = bool(
                    self._health is not None and self._health.healthy_cuda_backed
                )
            self._acquire_count += 1
            return self._lease

    # Operational terminology used by schedulers which explicitly lease lanes.
    lease = acquire

    def report_healthy(self) -> None:
        """Clear the consecutive-failure window after a successful health check."""

        with self._lock:
            self._consecutive_health_failures = 0
            self._last_health_failure_reason = ""

    def report_health_failure(self, reason: str = "health_check_failed") -> bool:
        """Record one health failure and restart only at the bounded threshold.

        Returns ``True`` when this call successfully installed a new generation.
        Inference/schema/proof rejection must not be reported here: service
        health is operational and confers no trust on model output.
        """

        with self._lock:
            if self._generation <= 0 or self._service is None:
                raise RuntimeError("cannot report health before service acquisition")
            self._health_failure_count += 1
            self._consecutive_health_failures += 1
            self._last_health_failure_reason = _token(reason, "health_check_failed")
            if (
                self._consecutive_health_failures
                < self.config.bounded_health_failures()
            ):
                return False
            self._restart_locked()
            return True

    def record_request_timing(
        self,
        *,
        queue_seconds: float = 0.0,
        inference_seconds: float = 0.0,
        verification_seconds: float = 0.0,
        restart_seconds: float = 0.0,
    ) -> None:
        """Accumulate mutually named phases without folding queue into inference."""

        with self._lock:
            self._queue_seconds += _finite_nonnegative(queue_seconds, 0.0)
            self._inference_seconds += _finite_nonnegative(inference_seconds, 0.0)
            self._verification_seconds += _finite_nonnegative(verification_seconds, 0.0)
            self._restart_seconds += _finite_nonnegative(restart_seconds, 0.0)

    def telemetry_snapshot(self) -> Dict[str, Any]:
        with self._lock:
            health = self._health.to_dict() if self._health is not None else {}
            return {
                "acquire_count": self._acquire_count,
                "consecutive_health_failures": self._consecutive_health_failures,
                "generation": self._generation,
                "health": health,
                "health_failure_count": self._health_failure_count,
                "healthy_cuda_service_reused": self._healthy_cuda_service_reused,
                "identity": self.identity.to_dict(),
                "inference_seconds": round(self._inference_seconds, 6),
                "leanstral_inference_seconds": round(self._inference_seconds, 6),
                "leanstral_request_count": self._acquire_count,
                "leanstral_reuse_count": self._reuse_count,
                "leanstral_service_startup_count": self._model_load_count,
                "last_health_failure_reason": self._last_health_failure_reason,
                "model_load_count": self._model_load_count,
                "model_reload_count": max(0, self._model_load_count - 1),
                "preflight_count": self._preflight_count,
                "proof_authority": False,
                "queue_seconds": round(self._queue_seconds, 6),
                "restart_count": self._restart_count,
                "restart_seconds": round(self._restart_seconds, 6),
                "reuse_count": self._reuse_count,
                "schema_version": LEANSTRAL_PERSISTENT_SERVICE_SCHEMA_VERSION,
                "service_generation": self._generation,
                "service_id": str(health.get("service_id") or ""),
                "verification_seconds": round(self._verification_seconds, 6),
            }

    def _validate_identity(self, requested: LeanstralServiceIdentity) -> None:
        if not self.identity.compatible_with(requested):
            raise LeanstralServiceIdentityError(
                "incompatible Leanstral service identity: "
                f"leased={self.identity.to_dict()} requested={requested.to_dict()}"
            )

    def _restart_locked(self) -> None:
        started = float(self._clock())
        old_service = self._service
        next_generation = self._generation + 1
        try:
            loaded = (
                self._restarter(old_service, self.identity)
                if self._restarter is not None
                else self._loader(self.identity)
            )
            self._install_generation(loaded, generation=next_generation)
        finally:
            self._restart_seconds += max(0.0, float(self._clock()) - started)
        self._restart_count += 1
        self._consecutive_health_failures = 0
        self._last_health_failure_reason = ""
        # The replacement is not considered reused until another compatible
        # request actually acquires it.
        self._healthy_cuda_service_reused = False

    def _install_generation(self, loaded: Any, *, generation: int) -> None:
        if loaded is None:
            raise LeanstralServiceHealthError("Leanstral model loader returned no service")
        self._model_load_count += 1
        self._preflight_count += 1
        raw_health = self._preflight(loaded, self.identity)
        health = self._validated_health(raw_health, generation=generation)
        self._service = loaded
        self._health = health
        self._generation = generation

    def _validated_health(
        self,
        health: LeanstralServiceHealth,
        *,
        generation: int,
    ) -> LeanstralServiceHealth:
        if not isinstance(health, LeanstralServiceHealth):
            raise LeanstralServiceHealthError(
                "Leanstral preflight must return LeanstralServiceHealth"
            )
        if health.status != "healthy":
            raise LeanstralServiceHealthError(
                f"Leanstral generation preflight is not healthy: {health.status!r}"
            )
        if self.config.require_cuda_backed and not health.cuda_backed:
            raise LeanstralServiceHealthError(
                "Leanstral generation preflight is not CUDA-backed"
            )
        if _token(health.model, "") != self.identity.model:
            raise LeanstralServiceIdentityError(
                f"preflight model mismatch: {health.model!r} != {self.identity.model!r}"
            )
        if _token(health.provider, "") != self.identity.provider:
            raise LeanstralServiceIdentityError(
                "preflight provider mismatch: "
                f"{health.provider!r} != {self.identity.provider!r}"
            )
        if int(health.context_size or 0) != self.identity.context_size:
            raise LeanstralServiceIdentityError(
                "preflight context_size mismatch: "
                f"{health.context_size!r} != {self.identity.context_size!r}"
            )
        if _token(health.context_fingerprint, "") != self.identity.context_fingerprint:
            raise LeanstralServiceIdentityError(
                "preflight context_fingerprint mismatch: "
                f"{health.context_fingerprint!r} != "
                f"{self.identity.context_fingerprint!r}"
            )
        service_id = _token(
            health.service_id,
            self._generation_service_id(generation),
        )
        return replace(
            health,
            service_id=service_id,
            context_size=self.identity.context_size,
            context_fingerprint=self.identity.context_fingerprint,
            generation=generation,
            proof_authority=False,
        )

    def _generation_service_id(self, generation: int) -> str:
        payload = {"generation": generation, "identity": self.identity.to_dict()}
        digest = hashlib.sha256(
            json.dumps(payload, ensure_ascii=True, sort_keys=True).encode("utf-8")
        ).hexdigest()[:24]
        return f"leanstral-service-{digest}"


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
    try:
        context_size = max(
            0,
            int(str(values.get("IPFS_ACCELERATE_LLAMA_CPP_CONTEXT_SIZE") or "0").strip()),
        )
    except ValueError:
        context_size = 0
    context_fingerprint = str(
        values.get("LEANSTRAL_AUDIT_CONTEXT_FINGERPRINT") or base_url
    ).strip()
    cuda_backed = (
        accelerator == "cuda"
        or reused in {"1", "true", "yes", "on"}
        or (base_url and gpu_layers not in {"", "0", "none", "false"})
    )
    status = "healthy" if cuda_backed and _looks_like_leanstral_model(model_name) else "unknown"
    service_identity = {
        "base_url": base_url,
        "cuda_backed": cuda_backed,
        "context_fingerprint": context_fingerprint,
        "context_size": context_size,
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
        context_size=context_size,
        context_fingerprint=context_fingerprint,
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
        persistent_service: Optional[LeanstralPersistentServiceManager] = None,
        service_identity: Optional[LeanstralServiceIdentity] = None,
    ) -> None:
        self.worker = worker
        self.config = config or LeanstralContinuousBatchServiceConfig()
        self.scheduler = LeanstralBatchScheduler(self.config.scheduler_config())
        provider = str(getattr(getattr(worker, "config", None), "provider", "leanstral_local"))
        model = str(getattr(getattr(worker, "config", None), "model", "Leanstral"))
        self.persistent_service = persistent_service
        self.service_lease: Optional[LeanstralServiceLease] = None
        if persistent_service is not None:
            self.service_lease = persistent_service.acquire(service_identity)
            self.health = self.service_lease.health
        else:
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
        if self.service_lease is not None:
            # A bounded external health restart advances this stable lease in
            # place.  Refresh metadata before attributing GPU work.
            self.health = self.service_lease.health
        queue_seconds = sum(
            max(0.0, batch.formed_monotonic - item.enqueued_monotonic)
            for item in batch.items
        )
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
        self.scheduler.telemetry.record_request_timing(
            queue_seconds=queue_seconds,
            inference_seconds=elapsed,
            # Local verification currently occurs inside _run_items_batch.  It
            # remains a distinct field (rather than being mislabeled queue or
            # restart time) until the runner exposes its inner phase clock.
            verification_seconds=0.0,
        )
        if self.persistent_service is not None:
            self.persistent_service.record_request_timing(
                queue_seconds=queue_seconds,
                inference_seconds=elapsed,
                verification_seconds=0.0,
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
        if self.service_lease is not None:
            self.health = self.service_lease.health
        payload = self.scheduler.telemetry_snapshot()
        persistent_payload: Dict[str, Any] = {}
        if self.persistent_service is not None:
            persistent_payload = self.persistent_service.telemetry_snapshot()
            payload["healthy_cuda_service_reused"] = bool(
                persistent_payload["healthy_cuda_service_reused"]
            )
            for field_name in (
                "queue_seconds",
                "inference_seconds",
                "verification_seconds",
                "restart_seconds",
            ):
                payload[field_name] = persistent_payload[field_name]
        payload["continuous_service"] = {
            "accepted_request_count": len(self._accepted_request_ids),
            "health": self.health.to_dict(),
            "persistent_service": persistent_payload,
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


def _cycle_utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical_json_bytes(value: Any) -> bytes:
    """Serialize one pipeline value into an isolated, deterministic snapshot."""

    return json.dumps(
        _jsonable(value),
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


@dataclass(frozen=True, slots=True)
class LeanstralCycleLineage:
    """Complete trust identity for one cycle's Leanstral guidance.

    These axes intentionally remain separate.  Folding them into one hash
    would make a rejection impossible to diagnose and makes it too easy for a
    caller to forget a dimension when constructing the expected boundary.
    """

    schema_version: str
    model: str
    source_revision: str
    state_revision: str
    proof_lineage: str

    def __post_init__(self) -> None:
        for name in (
            "schema_version",
            "model",
            "source_revision",
            "state_revision",
            "proof_lineage",
        ):
            value = str(getattr(self, name) or "").strip()
            if not value:
                raise ValueError(f"{name} must be non-empty")
            object.__setattr__(self, name, value)

    def mismatch_fields(self, other: "LeanstralCycleLineage") -> Tuple[str, ...]:
        if not isinstance(other, LeanstralCycleLineage):
            return (
                "schema_version",
                "model",
                "source_revision",
                "state_revision",
                "proof_lineage",
            )
        return tuple(
            name
            for name in (
                "schema_version",
                "model",
                "source_revision",
                "state_revision",
                "proof_lineage",
            )
            if getattr(self, name) != getattr(other, name)
        )

    def to_dict(self) -> Dict[str, str]:
        return asdict(self)

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "LeanstralCycleLineage":
        return cls(
            schema_version=str(value.get("schema_version") or ""),
            model=str(value.get("model") or ""),
            source_revision=str(value.get("source_revision") or ""),
            state_revision=str(
                value.get("state_revision") or value.get("state_hash") or ""
            ),
            proof_lineage=str(
                value.get("proof_lineage") or value.get("proof_lineage_hash") or ""
            ),
        )


# Compatibility terminology for callers that name this object after its role.
LeanstralGuidanceLineage = LeanstralCycleLineage


@dataclass(frozen=True, slots=True)
class LeanstralCycleGuidanceRequest:
    """Immutable inference input published at one trainer revision."""

    cycle: int
    lineage: LeanstralCycleLineage
    input_payload: bytes
    input_digest: str = ""
    created_at: str = field(default_factory=_cycle_utc_now)
    created_monotonic: float = field(default_factory=time.monotonic)

    def __post_init__(self) -> None:
        if int(self.cycle) < 1:
            raise ValueError("cycle must be at least one")
        if not isinstance(self.lineage, LeanstralCycleLineage):
            raise TypeError("lineage must be a LeanstralCycleLineage")
        payload = bytes(self.input_payload)
        try:
            json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("input_payload must contain UTF-8 JSON") from exc
        digest = hashlib.sha256(payload).hexdigest()
        if self.input_digest and str(self.input_digest) != digest:
            raise ValueError("input_payload does not match input_digest")
        object.__setattr__(self, "cycle", int(self.cycle))
        object.__setattr__(self, "input_payload", payload)
        object.__setattr__(self, "input_digest", digest)

    @classmethod
    def from_payload(
        cls,
        payload: Any,
        *,
        cycle: int,
        lineage: LeanstralCycleLineage,
    ) -> "LeanstralCycleGuidanceRequest":
        return cls(
            cycle=cycle,
            lineage=lineage,
            input_payload=_canonical_json_bytes(payload),
        )

    @property
    def request_id(self) -> str:
        identity = {
            "cycle": self.cycle,
            "input_digest": self.input_digest,
            "lineage": self.lineage.to_dict(),
            "pipeline_schema": LEANSTRAL_CYCLE_PIPELINE_SCHEMA_VERSION,
        }
        digest = hashlib.sha256(_canonical_json_bytes(identity)).hexdigest()
        return f"leanstral-cycle-{self.cycle}-{digest[:24]}"

    def payload(self) -> Any:
        """Decode a fresh evaluator-owned copy of the immutable input."""

        return json.loads(self.input_payload.decode("utf-8"))

    def to_dict(self, *, include_input: bool = False) -> Dict[str, Any]:
        value: Dict[str, Any] = {
            "created_at": self.created_at,
            "cycle": self.cycle,
            "input_digest": self.input_digest,
            "input_size_bytes": len(self.input_payload),
            "lineage": self.lineage.to_dict(),
            "request_id": self.request_id,
            "schema_version": LEANSTRAL_CYCLE_PIPELINE_SCHEMA_VERSION,
        }
        if include_input:
            value["input"] = self.payload()
        return value


@dataclass(frozen=True, slots=True)
class LeanstralCycleGuidanceResult:
    """Locally verified model output carrying the request's complete lineage."""

    cycle: int
    lineage: LeanstralCycleLineage
    request_id: str
    input_digest: str
    guidance_payload: bytes
    verified: bool = False
    verified_by: Sequence[str] = field(default_factory=tuple)
    error: str = ""
    diagnostics: Sequence[str] = field(default_factory=tuple)
    finished_at: str = field(default_factory=_cycle_utc_now)
    elapsed_seconds: float = 0.0

    def __post_init__(self) -> None:
        if int(self.cycle) < 1:
            raise ValueError("cycle must be at least one")
        if not isinstance(self.lineage, LeanstralCycleLineage):
            raise TypeError("lineage must be a LeanstralCycleLineage")
        elapsed = float(self.elapsed_seconds)
        if not math.isfinite(elapsed) or elapsed < 0.0:
            raise ValueError("elapsed_seconds must be finite and non-negative")
        object.__setattr__(self, "cycle", int(self.cycle))
        object.__setattr__(self, "request_id", str(self.request_id or "").strip())
        object.__setattr__(self, "input_digest", str(self.input_digest or "").strip())
        guidance_payload = bytes(self.guidance_payload)
        try:
            json.loads(guidance_payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("guidance_payload must contain UTF-8 JSON") from exc
        object.__setattr__(self, "guidance_payload", guidance_payload)
        object.__setattr__(
            self,
            "verified_by",
            tuple(str(value) for value in self.verified_by if str(value).strip()),
        )
        object.__setattr__(
            self,
            "diagnostics",
            tuple(str(value) for value in self.diagnostics if str(value).strip()),
        )
        object.__setattr__(self, "error", str(self.error or ""))
        object.__setattr__(self, "elapsed_seconds", elapsed)

    @classmethod
    def for_request(
        cls,
        request: LeanstralCycleGuidanceRequest,
        guidance: Any,
        *,
        verified: bool,
        verified_by: Sequence[str] = (),
        error: str = "",
        diagnostics: Sequence[str] = (),
        elapsed_seconds: float = 0.0,
    ) -> "LeanstralCycleGuidanceResult":
        return cls(
            cycle=request.cycle,
            lineage=request.lineage,
            request_id=request.request_id,
            input_digest=request.input_digest,
            guidance_payload=_canonical_json_bytes(guidance),
            verified=verified,
            verified_by=verified_by,
            error=error,
            diagnostics=diagnostics,
            elapsed_seconds=elapsed_seconds,
        )

    @classmethod
    def from_mapping(
        cls,
        value: Mapping[str, Any],
    ) -> "LeanstralCycleGuidanceResult":
        lineage_value = value.get("lineage")
        if not isinstance(lineage_value, Mapping):
            lineage_value = value
        verified_by_value = value.get("verified_by", ())
        if not isinstance(verified_by_value, Sequence) or isinstance(
            verified_by_value, (str, bytes, bytearray)
        ):
            verified_by_value = ()
        diagnostics_value = value.get("diagnostics", ())
        if not isinstance(diagnostics_value, Sequence) or isinstance(
            diagnostics_value, (str, bytes, bytearray)
        ):
            diagnostics_value = ()
        return cls(
            cycle=int(value.get("cycle", 0) or 0),
            lineage=LeanstralCycleLineage.from_mapping(lineage_value),
            request_id=str(value.get("request_id") or ""),
            input_digest=str(value.get("input_digest") or ""),
            guidance_payload=_canonical_json_bytes(
                value.get("guidance", value.get("guidance_payload", {}))
            ),
            # Fail closed for JSON values such as ``"false"`` or ``1``.
            verified=value.get("verified") is True,
            verified_by=tuple(verified_by_value),
            error=str(value.get("error") or ""),
            diagnostics=tuple(diagnostics_value),
            elapsed_seconds=float(value.get("elapsed_seconds", 0.0) or 0.0),
        )

    @property
    def succeeded(self) -> bool:
        return not self.error

    def guidance(self) -> Any:
        return json.loads(self.guidance_payload.decode("utf-8"))

    def to_dict(self, *, include_guidance: bool = True) -> Dict[str, Any]:
        value: Dict[str, Any] = {
            "cycle": self.cycle,
            "diagnostics": list(self.diagnostics),
            "elapsed_seconds": round(self.elapsed_seconds, 9),
            "error": self.error,
            "finished_at": self.finished_at,
            "input_digest": self.input_digest,
            "lineage": self.lineage.to_dict(),
            "request_id": self.request_id,
            "schema_version": LEANSTRAL_CYCLE_PIPELINE_SCHEMA_VERSION,
            "status": "succeeded" if self.succeeded else "failed",
            "verified": bool(self.verified),
            "verified_by": list(self.verified_by),
        }
        if include_guidance:
            value["guidance"] = self.guidance()
        return value


@dataclass(frozen=True, slots=True)
class LeanstralCyclePipelineConfig:
    """Queue and optional debug-wait bounds for cycle guidance."""

    queue_capacity: int = 2
    synchronous: bool = False
    synchronous_timeout_seconds: float = 30.0

    def __post_init__(self) -> None:
        if int(self.queue_capacity) < 1:
            raise ValueError("queue_capacity must be at least one")
        timeout = float(self.synchronous_timeout_seconds)
        if not math.isfinite(timeout) or timeout < 0.0:
            raise ValueError("synchronous_timeout_seconds must be finite and non-negative")
        object.__setattr__(self, "queue_capacity", int(self.queue_capacity))
        object.__setattr__(self, "synchronous_timeout_seconds", timeout)


@dataclass(frozen=True, slots=True)
class LeanstralCycleEnqueueDecision:
    enqueued: bool
    status: str
    cycle: int
    request_id: str = ""
    waited_seconds: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class LeanstralCycleConsumptionDecision:
    """Fail-closed outcome of polling the exact previous cycle."""

    consumed: bool
    status: str
    current_cycle: int
    target_cycle: int
    result: Optional[LeanstralCycleGuidanceResult] = None
    mismatch_fields: Sequence[str] = field(default_factory=tuple)
    diagnostics: Sequence[str] = field(default_factory=tuple)
    waited_seconds: float = 0.0

    @property
    def guidance(self) -> Any:
        return self.result.guidance() if self.consumed and self.result else None

    def to_dict(self, *, include_guidance: bool = False) -> Dict[str, Any]:
        value = {
            "consumed": self.consumed,
            "current_cycle": self.current_cycle,
            "diagnostics": list(self.diagnostics),
            "mismatch_fields": list(self.mismatch_fields),
            "status": self.status,
            "target_cycle": self.target_cycle,
            "waited_seconds": round(float(self.waited_seconds), 9),
        }
        if self.result is not None:
            value["result"] = self.result.to_dict(include_guidance=include_guidance)
        return value


class LeanstralCyclePipelineClosed(RuntimeError):
    pass


class LeanstralCyclePipeline:
    """Single-lane, non-blocking Leanstral guidance pipeline.

    The worker thread is daemonized and owns no trainer state.  The evaluator
    receives only immutable request bytes.  Normal ``enqueue`` and
    ``consume_previous`` calls do not wait; synchronous waiting is an explicit,
    bounded debugging option.  Results are single-use and only promotion can
    invoke a state/TODO callback.
    """

    def __init__(
        self,
        evaluate: Callable[
            [LeanstralCycleGuidanceRequest],
            Mapping[str, Any] | LeanstralCycleGuidanceResult,
        ],
        *,
        config: Optional[LeanstralCyclePipelineConfig] = None,
        name: str = "leanstral-cycle-pipeline",
        autostart: bool = True,
    ) -> None:
        if not callable(evaluate):
            raise TypeError("evaluate must be callable")
        self.evaluate = evaluate
        self.config = config or LeanstralCyclePipelineConfig()
        self.name = str(name or "leanstral-cycle-pipeline")
        self._condition = threading.Condition(threading.RLock())
        self._pending: Deque[LeanstralCycleGuidanceRequest] = deque()
        self._inflight: Optional[LeanstralCycleGuidanceRequest] = None
        self._requests: Dict[int, LeanstralCycleGuidanceRequest] = {}
        self._results: Dict[int, LeanstralCycleGuidanceResult] = {}
        self._diagnostics: List[Dict[str, Any]] = []
        self._stats: Dict[str, int] = defaultdict(int)
        self._highest_enqueued_cycle = 0
        self._closed = False
        self._stop_requested = False
        self._worker: Optional[threading.Thread] = None
        if autostart:
            self.start()

    def __enter__(self) -> "LeanstralCyclePipeline":
        self.start()
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        self.close(wait=True)

    def start(self) -> None:
        with self._condition:
            if self._closed:
                raise LeanstralCyclePipelineClosed("Leanstral cycle pipeline is closed")
            if self._worker is not None and self._worker.is_alive():
                return
            self._worker = threading.Thread(
                target=self._worker_main,
                name=self.name,
                daemon=True,
            )
            self._worker.start()

    def close(self, *, wait: bool = True, cancel_pending: bool = False) -> None:
        with self._condition:
            if cancel_pending:
                while self._pending:
                    request = self._pending.popleft()
                    self._record_locked("shutdown_cancelled", request.cycle)
                    self._stats["cancelled"] += 1
            self._closed = True
            self._stop_requested = True
            worker = self._worker
            self._condition.notify_all()
        if wait and worker is not None and worker is not threading.current_thread():
            worker.join()

    def enqueue(
        self,
        request: LeanstralCycleGuidanceRequest,
        *,
        synchronous: Optional[bool] = None,
        timeout: Optional[float] = None,
    ) -> LeanstralCycleEnqueueDecision:
        """Publish without waiting, unless bounded debug mode is explicit."""

        if not isinstance(request, LeanstralCycleGuidanceRequest):
            raise TypeError("request must be a LeanstralCycleGuidanceRequest")
        started = time.monotonic()
        with self._condition:
            if self._closed:
                raise LeanstralCyclePipelineClosed("Leanstral cycle pipeline is closed")
            if request.cycle in self._requests:
                self._stats["duplicate"] += 1
                return LeanstralCycleEnqueueDecision(
                    False, "duplicate_cycle", request.cycle, request.request_id
                )
            if request.cycle <= self._highest_enqueued_cycle:
                self._stats["stale_enqueue"] += 1
                self._record_locked("non_monotonic_cycle", request.cycle)
                return LeanstralCycleEnqueueDecision(
                    False, "stale_cycle", request.cycle, request.request_id
                )
            outstanding = len(self._pending) + (1 if self._inflight is not None else 0)
            if outstanding >= self.config.queue_capacity:
                self._stats["queue_full"] += 1
                self._record_locked("queue_full", request.cycle)
                return LeanstralCycleEnqueueDecision(
                    False, "queue_full", request.cycle, request.request_id
                )
            self._pending.append(request)
            self._requests[request.cycle] = request
            self._highest_enqueued_cycle = request.cycle
            self._stats["enqueued"] += 1
            self._condition.notify_all()

        should_wait = self.config.synchronous if synchronous is None else bool(synchronous)
        if should_wait:
            wait_bound = self._bounded_timeout(timeout)
            with self._condition:
                self._condition.wait_for(
                    lambda: request.cycle in self._results or self._closed,
                    timeout=wait_bound,
                )
                ready = request.cycle in self._results
            waited = time.monotonic() - started
            self._stats["synchronous_wait"] += 1
            if not ready:
                self._stats["synchronous_timeout"] += 1
            return LeanstralCycleEnqueueDecision(
                True,
                "completed" if ready else "synchronous_timeout",
                request.cycle,
                request.request_id,
                waited,
            )
        return LeanstralCycleEnqueueDecision(
            True,
            "enqueued",
            request.cycle,
            request.request_id,
            time.monotonic() - started,
        )

    # Familiar queue terminology used by daemon integrations.
    publish = enqueue

    def consume_previous(
        self,
        *,
        current_cycle: int,
        expected_lineage: LeanstralCycleLineage,
        synchronous: Optional[bool] = None,
        timeout: Optional[float] = None,
    ) -> LeanstralCycleConsumptionDecision:
        """Poll and validate exactly cycle ``current_cycle - 1``.

        A late N-1 result is useful only at boundary N.  Once boundary N+1 is
        observed it is diagnosed as stale and removed, never promoted.
        """

        current = int(current_cycle)
        if current < 1:
            raise ValueError("current_cycle must be at least one")
        if not isinstance(expected_lineage, LeanstralCycleLineage):
            raise TypeError("expected_lineage must be a LeanstralCycleLineage")
        target = current - 1
        started = time.monotonic()
        with self._condition:
            self._discard_stale_locked(target)
            request = self._requests.get(target)
            if target < 1 or request is None:
                return self._decision_locked(
                    False,
                    "missing_previous_cycle",
                    current,
                    target,
                    diagnostics=("no_request_for_previous_cycle",),
                )
            should_wait = self.config.synchronous if synchronous is None else bool(synchronous)
            if target not in self._results and should_wait:
                self._condition.wait_for(
                    lambda: target in self._results or self._closed,
                    timeout=self._bounded_timeout(timeout),
                )
            result = self._results.get(target)
            waited = time.monotonic() - started
            if result is None:
                status = "late_previous_cycle"
                diagnostic = "result_not_ready_without_blocking"
                if should_wait:
                    status = "synchronous_timeout"
                    diagnostic = "result_not_ready_within_synchronous_timeout"
                return self._decision_locked(
                    False,
                    status,
                    current,
                    target,
                    diagnostics=(diagnostic,),
                    waited_seconds=waited,
                )

            mismatch = list(request.lineage.mismatch_fields(expected_lineage))
            mismatch.extend(
                name
                for name in result.lineage.mismatch_fields(expected_lineage)
                if name not in mismatch
            )
            if result.cycle != target:
                mismatch.append("cycle")
            if result.request_id != request.request_id:
                mismatch.append("request_id")
            if result.input_digest != request.input_digest:
                mismatch.append("input_digest")
            if mismatch:
                self._drop_cycle_locked(target)
                return self._decision_locked(
                    False,
                    "lineage_mismatch",
                    current,
                    target,
                    result=result,
                    mismatch_fields=tuple(dict.fromkeys(mismatch)),
                    diagnostics=("result_rejected_before_promotion",),
                    waited_seconds=waited,
                )
            if result.error:
                self._drop_cycle_locked(target)
                return self._decision_locked(
                    False,
                    "inference_failed",
                    current,
                    target,
                    result=result,
                    diagnostics=(result.error,),
                    waited_seconds=waited,
                )
            if not result.verified or not result.verified_by:
                self._drop_cycle_locked(target)
                return self._decision_locked(
                    False,
                    "unverified_result",
                    current,
                    target,
                    result=result,
                    diagnostics=("verified_and_verified_by_are_required",),
                    waited_seconds=waited,
                )
            self._drop_cycle_locked(target)
            return self._decision_locked(
                True,
                "consumed_previous_cycle",
                current,
                target,
                result=result,
                diagnostics=("all_revision_and_verification_gates_matched",),
                waited_seconds=waited,
            )

    def promote_previous(
        self,
        *,
        current_cycle: int,
        expected_lineage: LeanstralCycleLineage,
        promote: Callable[[Any], Any],
        synchronous: Optional[bool] = None,
        timeout: Optional[float] = None,
    ) -> LeanstralCycleConsumptionDecision:
        """Invoke ``promote`` only for a fully admitted N-1 result."""

        if not callable(promote):
            raise TypeError("promote must be callable")
        decision = self.consume_previous(
            current_cycle=current_cycle,
            expected_lineage=expected_lineage,
            synchronous=synchronous,
            timeout=timeout,
        )
        if decision.consumed:
            promote(decision.guidance)
            with self._condition:
                self._stats["promoted"] += 1
        return decision

    def wait_until_idle(self, timeout: Optional[float] = None) -> bool:
        with self._condition:
            return self._condition.wait_for(
                lambda: not self._pending and self._inflight is None,
                timeout=timeout,
            )

    @property
    def pending_count(self) -> int:
        with self._condition:
            return len(self._pending) + (1 if self._inflight is not None else 0)

    @property
    def diagnostics(self) -> Tuple[Dict[str, Any], ...]:
        with self._condition:
            return tuple(dict(value) for value in self._diagnostics)

    def request_for_cycle(
        self, cycle: int
    ) -> Optional[LeanstralCycleGuidanceRequest]:
        """Return the immutable publication receipt retained for ``cycle``."""

        with self._condition:
            return self._requests.get(int(cycle))

    def summary(self) -> Dict[str, Any]:
        with self._condition:
            return {
                "closed": self._closed,
                "diagnostics": [dict(value) for value in self._diagnostics[-32:]],
                "highest_enqueued_cycle": self._highest_enqueued_cycle,
                "mode": "synchronous" if self.config.synchronous else "asynchronous",
                "pending_count": len(self._pending) + (1 if self._inflight else 0),
                "queue_capacity": self.config.queue_capacity,
                "ready_result_count": len(self._results),
                "schema_version": LEANSTRAL_CYCLE_PIPELINE_SCHEMA_VERSION,
                "stats": dict(sorted(self._stats.items())),
                "synchronous_timeout_seconds": self.config.synchronous_timeout_seconds,
            }

    def _worker_main(self) -> None:
        while True:
            with self._condition:
                self._condition.wait_for(lambda: self._pending or self._stop_requested)
                if not self._pending:
                    if self._stop_requested:
                        return
                    continue
                request = self._pending.popleft()
                self._inflight = request
            started = time.monotonic()
            try:
                raw_result = self.evaluate(request)
                if isinstance(raw_result, LeanstralCycleGuidanceResult):
                    result = raw_result
                elif isinstance(raw_result, Mapping):
                    result = LeanstralCycleGuidanceResult.from_mapping(raw_result)
                else:
                    raise TypeError(
                        "Leanstral cycle evaluator must return a result or mapping"
                    )
            except Exception as exc:
                result = LeanstralCycleGuidanceResult.for_request(
                    request,
                    {},
                    verified=False,
                    error=f"{type(exc).__name__}: {str(exc)[:500]}",
                    diagnostics=("cycle_evaluator_exception",),
                    elapsed_seconds=time.monotonic() - started,
                )
            with self._condition:
                self._inflight = None
                retained_request = self._requests.get(request.cycle)
                if (
                    retained_request is None
                    or retained_request.request_id != request.request_id
                ):
                    self._stats["late_result_discarded"] += 1
                    self._record_locked(
                        "late_result_discarded",
                        request.cycle,
                        request_id=request.request_id,
                    )
                else:
                    self._results[request.cycle] = result
                    self._stats["completed"] += 1
                    if result.error:
                        self._stats["failed"] += 1
                self._condition.notify_all()
                if self._stop_requested and not self._pending:
                    return

    def _bounded_timeout(self, value: Optional[float]) -> float:
        timeout = (
            self.config.synchronous_timeout_seconds
            if value is None
            else float(value)
        )
        if not math.isfinite(timeout):
            return self.config.synchronous_timeout_seconds
        return max(0.0, min(timeout, self.config.synchronous_timeout_seconds))

    def _discard_stale_locked(self, target_cycle: int) -> None:
        for cycle in sorted(value for value in self._requests if value < target_cycle):
            self._record_locked("stale_late_result", cycle, target_cycle=target_cycle)
            self._stats["stale"] += 1
            self._drop_cycle_locked(cycle)

    def _drop_cycle_locked(self, cycle: int) -> None:
        self._requests.pop(cycle, None)
        self._results.pop(cycle, None)
        if self._pending:
            self._pending = deque(
                request for request in self._pending if request.cycle != cycle
            )

    def _decision_locked(
        self,
        consumed: bool,
        status: str,
        current_cycle: int,
        target_cycle: int,
        *,
        result: Optional[LeanstralCycleGuidanceResult] = None,
        mismatch_fields: Sequence[str] = (),
        diagnostics: Sequence[str] = (),
        waited_seconds: float = 0.0,
    ) -> LeanstralCycleConsumptionDecision:
        self._stats["consumed" if consumed else "skipped"] += 1
        self._record_locked(
            status,
            target_cycle,
            current_cycle=current_cycle,
            mismatch_fields=list(mismatch_fields),
        )
        return LeanstralCycleConsumptionDecision(
            consumed=consumed,
            status=status,
            current_cycle=current_cycle,
            target_cycle=target_cycle,
            result=result,
            mismatch_fields=tuple(mismatch_fields),
            diagnostics=tuple(diagnostics),
            waited_seconds=waited_seconds,
        )

    def _record_locked(self, reason: str, cycle: int, **details: Any) -> None:
        self._diagnostics.append(
            {
                "at": _cycle_utc_now(),
                "cycle": int(cycle),
                "reason": str(reason),
                **_jsonable(details),
            }
        )
        if len(self._diagnostics) > 256:
            del self._diagnostics[:-256]


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
    "LEANSTRAL_CYCLE_PIPELINE_SCHEMA_VERSION",
    "LEANSTRAL_CONTINUOUS_SERVICE_SCHEMA_VERSION",
    "LEANSTRAL_BATCH_SCHEDULER_SCHEMA_VERSION",
    "LEANSTRAL_BATCH_TELEMETRY_SCHEMA_VERSION",
    "LEANSTRAL_PERSISTENT_SERVICE_SCHEMA_VERSION",
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
    "LeanstralContinuousBatchService",
    "LeanstralContinuousBatchServiceConfig",
    "LeanstralCycleConsumptionDecision",
    "LeanstralCycleEnqueueDecision",
    "LeanstralCycleGuidanceRequest",
    "LeanstralCycleGuidanceResult",
    "LeanstralCycleLineage",
    "LeanstralCyclePipeline",
    "LeanstralCyclePipelineClosed",
    "LeanstralCyclePipelineConfig",
    "LeanstralGuidanceLineage",
    "LeanstralInferenceBatch",
    "LeanstralPersistentServiceConfig",
    "LeanstralPersistentServiceManager",
    "LeanstralQueueBackpressureError",
    "LeanstralScheduledItem",
    "LeanstralServiceHealth",
    "LeanstralServiceHealthError",
    "LeanstralServiceIdentity",
    "LeanstralServiceIdentityError",
    "LeanstralServiceLease",
    "estimate_leanstral_audit_tokens",
    "estimate_leanstral_marginal_information",
    "leanstral_batch_metadata",
    "leanstral_policy_report_with_cache_hits",
    "policy_decision_by_candidate_id",
    "probe_reusable_cuda_leanstral_service",
    "select_informative_leanstral_audit_clusters",
]
