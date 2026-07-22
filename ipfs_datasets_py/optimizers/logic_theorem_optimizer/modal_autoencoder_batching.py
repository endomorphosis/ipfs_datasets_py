"""Deterministic sparse minibatches and resource-safe batch execution.

The modal autoencoder has a large, sparse feature surface.  This module keeps
the batching boundary independent from torch so the exact same packing and
retry policy can be exercised on CPU and CUDA.  Packed rows use a conventional
CSR representation: ``row_offsets[n]:row_offsets[n + 1]`` selects one sample's
feature indices and weights.

Two safety properties are intentional:

* records from different dataset splits are never placed in one minibatch;
* an OOM retry is allowed only inside a state transaction (or for a stateless
  operation), so a failed larger attempt is rolled back before a smaller one
  starts and the canonical state object is never replaced.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from typing import Any, Callable, Iterator, Mapping, Optional, Sequence


MODAL_AUTOENCODER_BATCHING_SCHEMA_VERSION = "modal-autoencoder-batching-v1"
DEFAULT_BATCH_SIZE_CANDIDATES = (8, 16, 32, 64)


class BatchCollationError(ValueError):
    """Raised when sparse records cannot be packed without ambiguity."""


class SplitIsolationError(BatchCollationError):
    """Raised when one minibatch would cross an evaluation split boundary."""


class UnsafeBatchRetryError(RuntimeError):
    """Raised when a mutating workload cannot be rolled back for an OOM retry."""


class RecoverableBatchOOM(RuntimeError):
    """Internal normalized form of a device out-of-memory outcome."""


def _finite(value: Any, *, name: str) -> float:
    if isinstance(value, bool):
        raise BatchCollationError(f"{name} must be finite")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise BatchCollationError(f"{name} must be finite") from exc
    if not math.isfinite(result):
        raise BatchCollationError(f"{name} must be finite")
    return result


def _portable_key(value: Any) -> tuple[str, str]:
    """Return a total-order key without conflating integers and strings."""

    if isinstance(value, bool):
        return ("bool", "1" if value else "0")
    if isinstance(value, int):
        return ("int", f"{value:+030d}")
    if isinstance(value, float):
        if not math.isfinite(value):
            raise BatchCollationError("feature keys must be finite")
        return ("float", value.hex())
    if isinstance(value, str):
        if not value:
            raise BatchCollationError("feature keys must not be empty")
        return ("str", value)
    raise BatchCollationError(
        f"feature keys must be strings or finite numbers, got {type(value).__name__}"
    )


def _canonical_digest(value: Any) -> str:
    payload = json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _record_value(record: Any, *names: str, default: Any = None) -> Any:
    if isinstance(record, Mapping):
        for name in names:
            if name in record:
                return record[name]
        return default
    for name in names:
        if hasattr(record, name):
            return getattr(record, name)
    return default


def _record_split(record: Any, default: str) -> str:
    value = _record_value(record, "split", "dataset_split", default=None)
    if value is None:
        metadata = _record_value(record, "metadata", default={})
        if isinstance(metadata, Mapping):
            value = metadata.get("split", default)
    if value is None:
        value = default
    split = str(value or default).strip()
    if not split:
        raise BatchCollationError("dataset split must not be empty")
    return split


def _sparse_items(value: Any, *, name: str) -> tuple[tuple[Any, float], ...]:
    if value is None:
        return ()
    if isinstance(value, Mapping):
        raw_items = value.items()
    else:
        try:
            raw_items = iter(value)
        except TypeError as exc:
            raise BatchCollationError(f"{name} must be a mapping or key/value pairs") from exc
    merged: dict[tuple[str, str], tuple[Any, float]] = {}
    for position, item in enumerate(raw_items):
        try:
            key, raw_weight = item
        except (TypeError, ValueError) as exc:
            raise BatchCollationError(
                f"{name}[{position}] must contain exactly a key and weight"
            ) from exc
        order_key = _portable_key(key)
        weight = _finite(raw_weight, name=f"{name}[{key!r}]")
        previous = merged.get(order_key)
        combined = weight + (previous[1] if previous else 0.0)
        if not math.isfinite(combined):
            raise BatchCollationError(f"combined {name}[{key!r}] weight must be finite")
        merged[order_key] = (key, combined)
    return tuple(
        (merged[key][0], merged[key][1])
        for key in sorted(merged)
        if merged[key][1] != 0.0
    )


@dataclass(frozen=True, slots=True)
class SparseFeatureExample:
    """One source-free sparse feature row ready for deterministic packing."""

    sample_id: str
    features: Mapping[Any, float] | Sequence[tuple[Any, float]]
    targets: Mapping[Any, float] | Sequence[tuple[Any, float]] = field(default_factory=dict)
    split: str = "train"

    def __post_init__(self) -> None:
        if not str(self.sample_id or "").strip():
            raise BatchCollationError("sample_id must not be empty")
        if not str(self.split or "").strip():
            raise BatchCollationError("split must not be empty")
        # Validate eagerly; packing repeats this to combine duplicate keys.
        _sparse_items(self.features, name="features")
        _sparse_items(self.targets, name="targets")


# A shorter spelling is convenient for callers that already establish the
# modal-autoencoder context in their import path.
SparseFeatureRecord = SparseFeatureExample


@dataclass(frozen=True, slots=True)
class PackedSparseMinibatch:
    """Immutable deterministic CSR minibatch with target and split lineage."""

    sample_ids: tuple[str, ...]
    split: str
    feature_keys: tuple[Any, ...]
    row_offsets: tuple[int, ...]
    feature_indices: tuple[int, ...]
    feature_values: tuple[float, ...]
    target_keys: tuple[Any, ...] = ()
    target_row_offsets: tuple[int, ...] = (0,)
    target_indices: tuple[int, ...] = ()
    target_values: tuple[float, ...] = ()
    source_positions: tuple[int, ...] = ()
    schema_version: str = MODAL_AUTOENCODER_BATCHING_SCHEMA_VERSION

    def __post_init__(self) -> None:
        row_count = len(self.sample_ids)
        if len(set(self.sample_ids)) != row_count:
            raise BatchCollationError("sample IDs in a minibatch must be unique")
        if len(self.row_offsets) != row_count + 1 or not self.row_offsets:
            raise BatchCollationError("row_offsets must contain one boundary per row")
        if self.row_offsets[0] != 0 or self.row_offsets[-1] != len(self.feature_indices):
            raise BatchCollationError("feature row offsets do not bound packed indices")
        if len(self.feature_indices) != len(self.feature_values):
            raise BatchCollationError("feature indices and values must have equal length")
        if any(not math.isfinite(value) for value in self.feature_values):
            raise BatchCollationError("packed feature values must be finite")
        if any(left > right for left, right in zip(self.row_offsets, self.row_offsets[1:])):
            raise BatchCollationError("feature row offsets must be monotonic")
        if any(index < 0 or index >= len(self.feature_keys) for index in self.feature_indices):
            raise BatchCollationError("packed feature index is outside the vocabulary")
        if len(self.target_row_offsets) != row_count + 1:
            raise BatchCollationError("target_row_offsets must contain one boundary per row")
        if (
            self.target_row_offsets[0] != 0
            or self.target_row_offsets[-1] != len(self.target_indices)
        ):
            raise BatchCollationError("target row offsets do not bound packed indices")
        if len(self.target_indices) != len(self.target_values):
            raise BatchCollationError("target indices and values must have equal length")
        if any(not math.isfinite(value) for value in self.target_values):
            raise BatchCollationError("packed target values must be finite")
        if any(
            left > right
            for left, right in zip(
                self.target_row_offsets,
                self.target_row_offsets[1:],
            )
        ):
            raise BatchCollationError("target row offsets must be monotonic")
        if any(index < 0 or index >= len(self.target_keys) for index in self.target_indices):
            raise BatchCollationError("packed target index is outside the vocabulary")
        if self.source_positions and len(self.source_positions) != row_count:
            raise BatchCollationError("source_positions must correspond to sample_ids")

    @property
    def batch_size(self) -> int:
        return len(self.sample_ids)

    @property
    def nonzero_count(self) -> int:
        return len(self.feature_values)

    @property
    def indptr(self) -> tuple[int, ...]:
        """SciPy-style alias for :attr:`row_offsets`."""

        return self.row_offsets

    @property
    def indices(self) -> tuple[int, ...]:
        return self.feature_indices

    @property
    def values(self) -> tuple[float, ...]:
        return self.feature_values

    @property
    def split_fingerprint(self) -> str:
        return _canonical_digest(
            {
                "sample_ids": self.sample_ids,
                "schema_version": self.schema_version,
                "split": self.split,
            }
        )

    def row(self, index: int) -> tuple[tuple[Any, float], ...]:
        start, stop = self.row_offsets[index : index + 2]
        return tuple(
            (self.feature_keys[self.feature_indices[position]], self.feature_values[position])
            for position in range(start, stop)
        )

    def target_row(self, index: int) -> tuple[tuple[Any, float], ...]:
        start, stop = self.target_row_offsets[index : index + 2]
        return tuple(
            (self.target_keys[self.target_indices[position]], self.target_values[position])
            for position in range(start, stop)
        )

    def to_torch(self, *, device: Any = None, torch_module: Any = None) -> dict[str, Any]:
        """Materialize contiguous tensors lazily, keeping torch optional."""

        if torch_module is None:
            try:
                import torch as torch_module
            except ImportError as exc:  # pragma: no cover - environment dependent
                raise RuntimeError("torch is required to materialize a packed minibatch") from exc
        kwargs = {"device": device} if device is not None else {}
        return {
            "feature_indices": torch_module.tensor(
                self.feature_indices, dtype=torch_module.long, **kwargs
            ).contiguous(),
            "feature_values": torch_module.tensor(
                self.feature_values, dtype=torch_module.float32, **kwargs
            ).contiguous(),
            "row_offsets": torch_module.tensor(
                self.row_offsets, dtype=torch_module.long, **kwargs
            ).contiguous(),
            "target_indices": torch_module.tensor(
                self.target_indices, dtype=torch_module.long, **kwargs
            ).contiguous(),
            "target_values": torch_module.tensor(
                self.target_values, dtype=torch_module.float32, **kwargs
            ).contiguous(),
            "target_row_offsets": torch_module.tensor(
                self.target_row_offsets, dtype=torch_module.long, **kwargs
            ).contiguous(),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "batch_size": self.batch_size,
            "feature_count": len(self.feature_keys),
            "nonzero_count": self.nonzero_count,
            "sample_ids": list(self.sample_ids),
            "schema_version": self.schema_version,
            "split": self.split,
            "split_fingerprint": self.split_fingerprint,
            "target_count": len(self.target_keys),
        }


@dataclass(frozen=True, slots=True)
class BatchCollationConfig:
    """Determinism and isolation policy for one collator."""

    sort_samples: bool = True
    require_single_split: bool = True
    default_split: str = "train"

    def __post_init__(self) -> None:
        if not str(self.default_split or "").strip():
            raise BatchCollationError("default_split must not be empty")


class ModalAutoencoderBatchCollator:
    """Collate heterogeneous sparse feature rows into canonical CSR arrays."""

    def __init__(self, config: BatchCollationConfig | None = None) -> None:
        self.config = config or BatchCollationConfig()

    def __call__(self, records: Sequence[Any]) -> PackedSparseMinibatch:
        return self.collate(records)

    def collate(self, records: Sequence[Any]) -> PackedSparseMinibatch:
        rows: list[
            tuple[
                str,
                str,
                tuple[tuple[Any, float], ...],
                tuple[tuple[Any, float], ...],
                int,
            ]
        ] = []
        seen_ids: set[str] = set()
        for position, record in enumerate(records):
            sample_id = str(_record_value(record, "sample_id", "id", default="") or "").strip()
            if not sample_id:
                raise BatchCollationError(f"record {position} has no sample_id")
            if sample_id in seen_ids:
                raise BatchCollationError(f"duplicate sample_id in minibatch: {sample_id}")
            seen_ids.add(sample_id)
            split = _record_split(record, self.config.default_split)
            features = _record_value(
                record,
                "features",
                "sparse_features",
                "feature_weights",
                default=None,
            )
            if features is None:
                embedding = _record_value(record, "embedding_vector", default=None)
                if embedding is None:
                    raise BatchCollationError(f"record {sample_id!r} has no sparse features")
                features = tuple((index, value) for index, value in enumerate(embedding))
            targets = _record_value(record, "targets", "target", "target_weights", default={})
            rows.append(
                (
                    sample_id,
                    split,
                    _sparse_items(features, name=f"features[{sample_id}]"),
                    _sparse_items(targets, name=f"targets[{sample_id}]"),
                    position,
                )
            )
        if self.config.sort_samples:
            rows.sort(key=lambda row: (row[1], row[0], row[4]))
        splits = {row[1] for row in rows}
        if self.config.require_single_split and len(splits) > 1:
            raise SplitIsolationError(
                "one packed minibatch cannot mix dataset splits: " + ", ".join(sorted(splits))
            )
        split = "+".join(sorted(splits)) if splits else self.config.default_split

        feature_by_order: dict[tuple[str, str], Any] = {}
        target_by_order: dict[tuple[str, str], Any] = {}
        for _sample_id, _split, features, targets, _position in rows:
            for key, _weight in features:
                feature_by_order[_portable_key(key)] = key
            for key, _weight in targets:
                target_by_order[_portable_key(key)] = key
        feature_orders = tuple(sorted(feature_by_order))
        target_orders = tuple(sorted(target_by_order))
        feature_keys = tuple(feature_by_order[key] for key in feature_orders)
        target_keys = tuple(target_by_order[key] for key in target_orders)
        feature_index = {key: index for index, key in enumerate(feature_orders)}
        target_index = {key: index for index, key in enumerate(target_orders)}

        row_offsets = [0]
        feature_indices: list[int] = []
        feature_values: list[float] = []
        target_offsets = [0]
        target_indices: list[int] = []
        target_values: list[float] = []
        for _sample_id, _split, features, targets, _position in rows:
            feature_indices.extend(feature_index[_portable_key(key)] for key, _weight in features)
            feature_values.extend(weight for _key, weight in features)
            row_offsets.append(len(feature_indices))
            target_indices.extend(target_index[_portable_key(key)] for key, _weight in targets)
            target_values.extend(weight for _key, weight in targets)
            target_offsets.append(len(target_indices))

        return PackedSparseMinibatch(
            sample_ids=tuple(row[0] for row in rows),
            split=split,
            feature_keys=feature_keys,
            row_offsets=tuple(row_offsets),
            feature_indices=tuple(feature_indices),
            feature_values=tuple(feature_values),
            target_keys=target_keys,
            target_row_offsets=tuple(target_offsets),
            target_indices=tuple(target_indices),
            target_values=tuple(target_values),
            # The packed representation is canonical even when callers feed
            # the same records in a different order.  Original positions are
            # deliberately not lineage: sample IDs carry row identity.
            source_positions=tuple(range(len(rows))),
        )


def collate_sparse_minibatch(
    records: Sequence[Any],
    *,
    sort_samples: bool = True,
    require_single_split: bool = True,
    default_split: str = "train",
) -> PackedSparseMinibatch:
    """Functional entry point for deterministic sparse collation."""

    return ModalAutoencoderBatchCollator(
        BatchCollationConfig(
            sort_samples=sort_samples,
            require_single_split=require_single_split,
            default_split=default_split,
        )
    ).collate(records)


collate_sparse_features = collate_sparse_minibatch


@dataclass(frozen=True, slots=True)
class GradientAccumulationPlan:
    """Sample-weighted microbatch ranges for exactly one optimizer step."""

    sample_count: int
    microbatch_size: int
    ranges: tuple[tuple[int, int], ...]
    loss_scales: tuple[float, ...]

    @property
    def accumulation_steps(self) -> int:
        return len(self.ranges)

    @property
    def effective_batch_size(self) -> int:
        return self.sample_count


def plan_gradient_accumulation(
    sample_count: int,
    *,
    microbatch_size: Optional[int] = None,
    accumulation_steps: Optional[int] = None,
) -> GradientAccumulationPlan:
    """Build complete, non-overlapping microbatches with unbiased loss scales."""

    if isinstance(sample_count, bool) or int(sample_count) < 0:
        raise ValueError("sample_count must be a non-negative integer")
    count = int(sample_count)
    if microbatch_size is not None and accumulation_steps is not None:
        raise ValueError("specify microbatch_size or accumulation_steps, not both")
    if count == 0:
        return GradientAccumulationPlan(0, 0, (), ())
    if microbatch_size is None:
        steps = 1 if accumulation_steps is None else int(accumulation_steps)
        if steps < 1:
            raise ValueError("accumulation_steps must be positive")
        size = max(1, math.ceil(count / min(count, steps)))
    else:
        size = int(microbatch_size)
        if size < 1:
            raise ValueError("microbatch_size must be positive")
    ranges = tuple((start, min(count, start + size)) for start in range(0, count, size))
    scales = tuple((stop - start) / count for start, stop in ranges)
    return GradientAccumulationPlan(count, size, ranges, scales)


def iter_collated_minibatches(
    records: Sequence[Any],
    *,
    batch_size: int,
    collator: Optional[ModalAutoencoderBatchCollator] = None,
) -> Iterator[PackedSparseMinibatch]:
    """Yield deterministic split-isolated minibatches without dropping rows."""

    if isinstance(batch_size, bool) or int(batch_size) < 1:
        raise ValueError("batch_size must be a positive integer")
    selected = collator or ModalAutoencoderBatchCollator()
    by_split: dict[str, list[Any]] = {}
    seen_ids: set[str] = set()
    for record in records:
        sample_id = str(_record_value(record, "sample_id", "id", default="") or "").strip()
        if not sample_id:
            raise BatchCollationError("every minibatch record must have a sample_id")
        if sample_id in seen_ids:
            raise BatchCollationError(f"duplicate sample_id in batch stream: {sample_id}")
        seen_ids.add(sample_id)
        by_split.setdefault(_record_split(record, selected.config.default_split), []).append(record)
    for split in sorted(by_split):
        split_rows = by_split[split]
        if selected.config.sort_samples:
            split_rows = sorted(
                enumerate(split_rows),
                key=lambda item: (
                    str(_record_value(item[1], "sample_id", "id", default="")),
                    item[0],
                ),
            )
            split_rows = [row for _position, row in split_rows]
        for start in range(0, len(split_rows), int(batch_size)):
            yield selected.collate(split_rows[start : start + int(batch_size)])


def is_recoverable_oom(error: Any) -> bool:
    """Recognize CUDA/accelerator allocation failures without torch imports."""

    if error is None:
        return False
    name = type(error).__name__.lower()
    text = str(error).strip().lower()
    if "outofmemory" in name or "out_of_memory" in name:
        return True
    markers = (
        "out of memory",
        "outofmemory",
        "out_of_memory",
        "cuda out of memory",
        "cuda error: out of memory",
        "hip out of memory",
        "mps backend out of memory",
        "cublas_status_alloc_failed",
        "resource exhausted: oom",
    )
    return any(marker in text for marker in markers)


def _outcome_oom(outcome: Any) -> bool:
    if isinstance(outcome, Mapping):
        reason = outcome.get("fallback_reason", outcome.get("error", ""))
        admitted = outcome.get("admitted", True)
        applied = outcome.get("applied", True)
    else:
        reason = getattr(outcome, "fallback_reason", "")
        admitted = getattr(outcome, "admitted", True)
        applied = getattr(outcome, "applied", True)
    return (not bool(admitted) or not bool(applied)) and is_recoverable_oom(
        RuntimeError(str(reason))
    )


def _outcome_failure_reason(outcome: Any) -> str:
    if isinstance(outcome, Mapping):
        reason = outcome.get("fallback_reason", outcome.get("error", ""))
        admitted = outcome.get("admitted", True)
        applied = outcome.get("applied", True)
    else:
        reason = getattr(outcome, "fallback_reason", "")
        admitted = getattr(outcome, "admitted", True)
        applied = getattr(outcome, "applied", True)
    if reason and (not bool(admitted) or not bool(applied)):
        return str(reason)
    return ""


@dataclass(frozen=True, slots=True)
class BatchExecutionAttempt:
    batch_size: int
    completed_batch_count: int
    completed_sample_count: int
    recoverable_oom: bool
    state_identity_restored: bool


@dataclass(frozen=True, slots=True)
class BatchExecutionResult:
    """Outputs and audit evidence from a successful (possibly retried) run."""

    outputs: tuple[Any, ...]
    selected_batch_size: int
    attempts: tuple[BatchExecutionAttempt, ...]
    state_object_id: Optional[int]
    schema_version: str = MODAL_AUTOENCODER_BATCHING_SCHEMA_VERSION

    @property
    def retry_count(self) -> int:
        return max(0, len(self.attempts) - 1)

    @property
    def state_identity_preserved(self) -> bool:
        return all(attempt.state_identity_restored for attempt in self.attempts)

    @property
    def processed_sample_count(self) -> int:
        return sum(
            attempt.completed_sample_count
            for attempt in self.attempts
            if not attempt.recoverable_oom
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "attempts": [
                {
                    "batch_size": attempt.batch_size,
                    "completed_batch_count": attempt.completed_batch_count,
                    "completed_sample_count": attempt.completed_sample_count,
                    "recoverable_oom": attempt.recoverable_oom,
                    "state_identity_restored": attempt.state_identity_restored,
                }
                for attempt in self.attempts
            ],
            "retry_count": self.retry_count,
            "schema_version": self.schema_version,
            "selected_batch_size": self.selected_batch_size,
            "state_identity_preserved": self.state_identity_preserved,
            "state_object_id": self.state_object_id,
        }


class ResourceSafeBatchRunner:
    """Retry an entire batch workload at smaller sizes after recoverable OOM.

    ``operation`` receives one sequence slice.  If ``state`` is supplied it
    must expose the modal state ``transaction()`` API.  All slices in an
    attempt share one transaction; therefore an OOM in a later slice restores
    updates made by earlier slices before retrying from sample zero.
    """

    def __init__(
        self,
        *,
        candidate_batch_sizes: Sequence[int] = DEFAULT_BATCH_SIZE_CANDIDATES,
        empty_cache: Optional[Callable[[], None]] = None,
    ) -> None:
        candidates = sorted({int(size) for size in candidate_batch_sizes if int(size) > 0})
        if not candidates:
            raise ValueError("candidate_batch_sizes must contain a positive size")
        self.candidate_batch_sizes = tuple(candidates)
        self.empty_cache = empty_cache

    def _sizes_at_or_below(self, initial_batch_size: int) -> tuple[int, ...]:
        initial = int(initial_batch_size)
        if initial < 1:
            raise ValueError("initial_batch_size must be positive")
        candidates = {size for size in self.candidate_batch_sizes if size < initial}
        candidates.add(initial)
        candidates.add(1)
        return tuple(sorted(candidates, reverse=True))

    @staticmethod
    def _identity(state: Any) -> Any:
        record = getattr(state, "state_identity_record", None)
        return record() if callable(record) else None

    def _clear_cache(self) -> None:
        if self.empty_cache is not None:
            self.empty_cache()
            return
        try:  # pragma: no cover - depends on CUDA runtime
            import torch

            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:
            return

    def run(
        self,
        records: Sequence[Any],
        operation: Callable[[Sequence[Any]], Any],
        *,
        initial_batch_size: int,
        state: Any = None,
    ) -> BatchExecutionResult:
        rows = list(records)
        attempts: list[BatchExecutionAttempt] = []
        state_object_id = id(state) if state is not None else None
        initial_identity = self._identity(state) if state is not None else None
        last_oom: Optional[BaseException] = None

        for batch_size in self._sizes_at_or_below(initial_batch_size):
            transaction = None
            completed_batches = 0
            completed_samples = 0
            outputs: list[Any] = []
            if state is not None:
                if not callable(getattr(state, "transaction", None)):
                    raise UnsafeBatchRetryError(
                        "stateful batch retry requires a transaction-capable state"
                    )
                if getattr(state, "_active_state_transaction", None) is not None:
                    raise UnsafeBatchRetryError(
                        "resource-safe retry must own the outer state transaction"
                    )
                transaction = state.transaction(
                    label=f"resource-safe-batch:{batch_size}"
                ).begin()
            try:
                for start in range(0, len(rows), batch_size):
                    chunk = rows[start : start + batch_size]
                    outcome = operation(chunk)
                    if _outcome_oom(outcome):
                        raise RecoverableBatchOOM(str(getattr(outcome, "fallback_reason", outcome)))
                    failure_reason = _outcome_failure_reason(outcome)
                    if failure_reason:
                        raise RuntimeError(f"batch operation failed: {failure_reason}")
                    outputs.append(outcome)
                    completed_batches += 1
                    completed_samples += len(chunk)
                if transaction is not None:
                    transaction.commit()
                attempts.append(
                    BatchExecutionAttempt(
                        batch_size=batch_size,
                        completed_batch_count=completed_batches,
                        completed_sample_count=completed_samples,
                        recoverable_oom=False,
                        state_identity_restored=id(state) == state_object_id,
                    )
                )
                return BatchExecutionResult(
                    outputs=tuple(outputs),
                    selected_batch_size=batch_size,
                    attempts=tuple(attempts),
                    state_object_id=state_object_id,
                )
            except BaseException as exc:
                recoverable = isinstance(exc, RecoverableBatchOOM) or is_recoverable_oom(exc)
                if transaction is not None and transaction.active:
                    transaction.rollback()
                restored = (
                    state is None
                    or (
                        id(state) == state_object_id
                        and self._identity(state) == initial_identity
                    )
                )
                attempts.append(
                    BatchExecutionAttempt(
                        batch_size=batch_size,
                        completed_batch_count=completed_batches,
                        completed_sample_count=completed_samples,
                        recoverable_oom=recoverable,
                        state_identity_restored=restored,
                    )
                )
                if not recoverable:
                    raise
                if not restored:
                    raise UnsafeBatchRetryError(
                        "failed OOM attempt did not restore canonical state identity"
                    ) from exc
                last_oom = exc
                self._clear_cache()
        raise RecoverableBatchOOM("all batch sizes exhausted after recoverable OOM") from last_oom


OOMSafeBatchRunner = ResourceSafeBatchRunner
ResourceSafeBatchExecutor = ResourceSafeBatchRunner
SparseBatchCollator = ModalAutoencoderBatchCollator
PackedMinibatch = PackedSparseMinibatch
GradientAccumulationSchedule = GradientAccumulationPlan


__all__ = [
    "BatchCollationConfig",
    "BatchCollationError",
    "BatchExecutionAttempt",
    "BatchExecutionResult",
    "DEFAULT_BATCH_SIZE_CANDIDATES",
    "GradientAccumulationPlan",
    "GradientAccumulationSchedule",
    "MODAL_AUTOENCODER_BATCHING_SCHEMA_VERSION",
    "ModalAutoencoderBatchCollator",
    "OOMSafeBatchRunner",
    "PackedMinibatch",
    "PackedSparseMinibatch",
    "RecoverableBatchOOM",
    "ResourceSafeBatchRunner",
    "ResourceSafeBatchExecutor",
    "SparseBatchCollator",
    "SparseFeatureExample",
    "SparseFeatureRecord",
    "SplitIsolationError",
    "UnsafeBatchRetryError",
    "collate_sparse_features",
    "collate_sparse_minibatch",
    "is_recoverable_oom",
    "iter_collated_minibatches",
    "plan_gradient_accumulation",
]
