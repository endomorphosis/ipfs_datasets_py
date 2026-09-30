"""Opt-in speed descendant of the frozen eight-dimensional legacy runtime.

Only touched-row norm bookkeeping differs. Update order, reconstruction
objective, candidate search, deadlines, compiler bridges, and all acceptance
checks remain the legacy implementation. This profile neither admits logic nor
turns diagnostic eight-dimensional vectors into semantic embeddings.

Port source: 03bf05a51992bd70c2e6f225e656babe9b0dfa2e. The small batch override
is intentionally explicit, not a process-global patch. A structural parity test
binds it to the frozen method and allows only the norm helper/import relocation.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from contextlib import nullcontext
import math
from typing import Any, Dict, Optional

from . import legacy_v1
from ._contract import load_local_checkpoint
from .legacy_v1._snapshot import modal_autoencoder as _legacy
from .legacy_v1._snapshot.modal_autoencoder_state_transaction import (
    StateTransactionConflictError, TouchedRow,
)

DIMENSION = legacy_v1.DIMENSION
LINEAGE_ID = legacy_v1.LINEAGE_ID
SOURCE_REVISION = legacy_v1.SOURCE_REVISION
RUNTIME_PROFILE = "legacy-v1-streamed-norms/v1"
PORT_REVISION = "03bf05a51992bd70c2e6f225e656babe9b0dfa2e"
TrainingState = legacy_v1.TrainingState
LegalSample = legacy_v1.LegalSample
build_sample = legacy_v1.build_sample
ProjectionProfiler = _legacy.ProjectionProfiler
LEGAL_IR_TRAINABLE_HEAD_FIELDS = _legacy.LEGAL_IR_TRAINABLE_HEAD_FIELDS
LEGAL_IR_TRAINABLE_OBJECTIVE_NORM_SCHEMA_VERSION = _legacy.LEGAL_IR_TRAINABLE_OBJECTIVE_NORM_SCHEMA_VERSION
_flatten_numeric_head_values = _legacy._flatten_numeric_head_values
_sqrt_norms = _legacy._sqrt_norms
_gradient_norms = _legacy._gradient_norms
_trainable_legal_ir_delta_family = _legacy._trainable_legal_ir_delta_family
_target_family = _legacy._target_family

FROZEN_BATCH_METHOD_SHA256 = 'd4c122f79fb533e233ed3173f3e35307f3096122e9ed3088ad7abd0ed72cfdd0'

def _borrow_norm_rows(transaction):
    """Read journal values synchronously; never expose or retain aliases.

    Match the frozen snapshot's row order and inclusion rules exactly, including
    a row journaled before replacement of its entire component. The historical
    report ignores standalone component deltas; this profile preserves that
    existing limitation rather than changing the metric while optimizing it.
    """
    transaction._require_owner()
    for (component, key), (before_exists, before_value) in sorted(
        ((marker, value) for marker, value in transaction._rows.items()
         if marker[0] in LEGAL_IR_TRAINABLE_HEAD_FIELDS),
        key=lambda item: (item[0][0], repr(item[0][1])),
    ):
        transaction._require_owner()
        mapping = getattr(transaction.state, component)
        after_exists = key in mapping
        yield TouchedRow(component, key, before_exists, before_value,
                         after_exists, mapping[key] if after_exists else None,
                         transaction.base_revision)


def legal_ir_trainable_head_transaction_delta_norm_report(
    transaction,
    state,
    *,
    learning_rate: float,
) -> Dict[str, Any]:
    """Return update norms from a transaction's sparse row journal."""

    if transaction.state is not state:
        raise StateTransactionConflictError(
            "update-norm transaction targets a different state object"
        )

    rows_by_field: Dict[str, list[Any]] = {}
    for row in _borrow_norm_rows(transaction):
        rows_by_field.setdefault(row.component, []).append(row)

    def deltas() -> Iterable[tuple[str, tuple[str, ...], float]]:
        for field_name in LEGAL_IR_TRAINABLE_HEAD_FIELDS:
            rows = rows_by_field.get(field_name, [])
            keys = [str(row.key) for row in rows]
            if len(keys) != len(set(keys)):
                # Historical flattening merges e.g. integer1 and string"1"
                # paths, retaining the last value at each colliding leaf. Keep
                # that uncommon behavior without materializing ordinary rows.
                before_values: Dict[tuple[str, ...], float] = {}
                after_values: Dict[tuple[str, ...], float] = {}
                for row in rows:
                    for exists, value, target in ((row.before_exists, row.before_value, before_values),
                                                   (row.after_exists, row.after_value, after_values)):
                        if exists:
                            for path, number in _flatten_numeric_head_values(value).items():
                                target[(str(row.key), *path)] = number
                for path in sorted(set(before_values) | set(after_values)):
                    yield field_name, path, after_values.get(path, 0.0) - before_values.get(path, 0.0)
                continue
            for row in sorted(rows, key=lambda item: str(item.key)):
                before = _iter_numeric_head_values_sorted(row.before_value) if row.before_exists else iter(())
                after = _iter_numeric_head_values_sorted(row.after_value) if row.after_exists else iter(())
                for path, delta in _merge_numeric_head_deltas(before, after):
                    yield field_name, (str(row.key), *path), delta

    return _legal_ir_trainable_ordered_delta_norm_report(deltas(), learning_rate=learning_rate)

def _iter_numeric_head_values_sorted(value: Any, path: tuple[str, ...] = ()) -> Iterable[tuple[tuple[str, ...], float]]:
    """Stream the legacy flattened leaf order, including string index sorting."""
    if isinstance(value, Mapping):
        children = [(str(key), nested) for key, nested in value.items()]
        if len(children) != len({key for key, _ in children}):
            # Stringified-key collisions can merge disjoint descendant leaves;
            # preserve the exact old last-write behavior for this subtree.
            for suffix, number in sorted(_flatten_numeric_head_values(value).items()):
                yield (*path, *suffix), number
        else:
            for key, nested in sorted(children, key=lambda item: item[0]):
                yield from _iter_numeric_head_values_sorted(nested, (*path, key))
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for index in sorted(range(len(value)), key=str):
            yield from _iter_numeric_head_values_sorted(value[index], (*path, str(index)))
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        number = float(value)
        yield path, number if math.isfinite(number) else float("nan")

def _merge_numeric_head_deltas(before: Iterable[Any], after: Iterable[Any]) -> Iterable[tuple[tuple[str, ...], float]]:
    left, right = iter(before), iter(after)
    a, b = next(left, None), next(right, None)
    while a is not None or b is not None:
        if b is None or (a is not None and a[0] < b[0]):
            yield a[0], 0.0 - a[1]
            a = next(left, None)
        elif a is None or b[0] < a[0]:
            yield b[0], b[1] - 0.0
            b = next(right, None)
        else:
            yield a[0], b[1] - a[1]
            a, b = next(left, None), next(right, None)

def _legal_ir_trainable_ordered_delta_norm_report(
    deltas: Iterable[tuple[str, tuple[str, ...], float]], *, learning_rate: float,
) -> Dict[str, Any]:
    step = abs(float(learning_rate)) if math.isfinite(float(learning_rate)) else 0.0
    update_squares_by_head: Dict[str, float] = {}
    update_squares_by_head_family: Dict[str, float] = {}
    update_squares_by_family: Dict[str, float] = {}
    scalar_count_by_head: Dict[str, int] = {}
    finite = True

    for field_name, path, delta in deltas:
        head_family = LEGAL_IR_TRAINABLE_HEAD_FIELDS[field_name]
        if not math.isfinite(delta):
            finite = False
            continue
        if abs(delta) <= 0.0:
            continue
        square = delta * delta
        family = _trainable_legal_ir_delta_family(field_name, path, head_family)
        update_squares_by_head[field_name] = (
            update_squares_by_head.get(field_name, 0.0) + square
        )
        update_squares_by_head_family[head_family] = (
            update_squares_by_head_family.get(head_family, 0.0) + square
        )
        update_squares_by_family[family] = update_squares_by_family.get(family, 0.0) + square
        scalar_count_by_head[field_name] = scalar_count_by_head.get(field_name, 0) + 1

    update_norms_by_head = _sqrt_norms(update_squares_by_head)
    update_norms_by_head_family = _sqrt_norms(update_squares_by_head_family)
    update_norms_by_family = _sqrt_norms(update_squares_by_family)
    gradient_norms_by_head = _gradient_norms(update_norms_by_head, step)
    gradient_norms_by_head_family = _gradient_norms(update_norms_by_head_family, step)
    gradient_norms_by_family = _gradient_norms(update_norms_by_family, step)
    total_update_norm = math.sqrt(sum(update_squares_by_head.values()))
    total_gradient_norm = total_update_norm / step if step > 0.0 else 0.0
    return {
        "finite": bool(finite),
        "gradient_norm": round(total_gradient_norm, 12),
        "gradient_norms_by_family": gradient_norms_by_family,
        "gradient_norms_by_head": gradient_norms_by_head,
        "head_family_gradient_norms": gradient_norms_by_head_family,
        "head_family_update_norms": update_norms_by_head_family,
        "learning_rate": float(learning_rate),
        "nonzero_gradient": bool(total_gradient_norm > 0.0),
        "nonzero_update": bool(total_update_norm > 0.0),
        "schema_version": LEGAL_IR_TRAINABLE_OBJECTIVE_NORM_SCHEMA_VERSION,
        "scalar_update_counts_by_head": dict(sorted(scalar_count_by_head.items())),
        "trainable_head_families": dict(sorted(LEGAL_IR_TRAINABLE_HEAD_FIELDS.items())),
        "update_norm": round(total_update_norm, 12),
        "update_norms_by_family": update_norms_by_family,
        "update_norms_by_head": update_norms_by_head,
    }

class Autoencoder(legacy_v1.Autoencoder):
    """Legacy training with exact, allocation-bounded norm accounting."""

    def describe(self):
        result = super().describe()
        result.update({
            "runtime_profile": RUNTIME_PROFILE,
            "speed_port_revision": PORT_REVISION,
            "frozen_batch_method_sha256": FROZEN_BATCH_METHOD_SHA256,
            "implementation_scope": "historical legacy runtime with streamed touched-row norm accounting; shared current canonical compiler, bridges, and proof infrastructure",
        })
        return result

    def _apply_projection_update_batch_in_transaction(
        self,
        samples: Sequence[LegalSample],
        *,
        update_targets: Sequence[str],
        learning_rate: float,
        l2_regularization: float,
        profiler: Optional[ProjectionProfiler] = None,
        update_backend: str = "native",
    ) -> Dict[str, Any]:
        """Apply compatible projection updates as one guarded optimizer batch.

        Native updates retain the historical sample-outer/head-inner order.
        The ``cuda_resident`` backend instead collates the complete batch into
        packed feature/parameter tensors and performs forward loss, backward,
        clipping, and the optimizer step on the selected CUDA device.  It never
        enters this method recursively or invokes a legacy per-sample updater.
        """
        sample_list = list(samples)
        target_tuple = tuple(str(target) for target in update_targets)
        normalized_backend = str(update_backend or "native").strip().lower()
        transaction = self.state._active_state_transaction
        if transaction is None:
            raise StateTransactionConflictError(
                "projection update batch requires an active state transaction"
            )
        if normalized_backend == "cuda_resident":
            try:
                from .legacy_v1._snapshot.modal_autoencoder_cuda import (
                    apply_cuda_resident_projection_update,
                )

                report = apply_cuda_resident_projection_update(
                    self,
                    sample_list,
                    update_targets=target_tuple,
                    learning_rate=learning_rate,
                    l2_regularization=l2_regularization,
                    profiler=profiler,
                )
                self._cuda_residency_reports.append(report.to_dict())
                self._cuda_residency_reports = self._cuda_residency_reports[-256:]
                if report.applied:
                    norm_report = legal_ir_trainable_head_transaction_delta_norm_report(
                        transaction,
                        self.state,
                        learning_rate=learning_rate,
                    )
                    norm_report["backend_report"] = report.to_dict()
                    norm_report["projection_update_backend"] = "cuda_resident"
                    return norm_report
                if profiler is not None:
                    profiler.count("cuda_resident_deterministic_fallback_count")
            except Exception:
                if profiler is not None:
                    profiler.count("cuda_resident_deterministic_fallback_count")
            normalized_backend = "native"
        use_sparse_python = normalized_backend == "python_sparse_batch"
        if profiler is not None:
            profiler.count("projection_update_batch_count", 1)
            profiler.count("projection_update_sample_count", len(sample_list))
            profiler.count("projection_update_head_count", len(target_tuple))
            if self.compute_backend == "torch_cuda":
                if use_sparse_python:
                    profiler.count("redundant_cuda_update_sync_avoided_count", 1)
                    profiler.count(
                        "host_device_transfer_avoided_count",
                        max(1, len(sample_list) * max(1, len(target_tuple))),
                    )
                else:
                    profiler.transfer(
                        stage="projection_update_batch",
                        legal_family="aggregate",
                        count=max(1, len(sample_list) * max(1, len(target_tuple))),
                        bytes_moved=sum(
                            len(getattr(sample, "embedding_vector", ()) or ()) * 8
                            for sample in sample_list
                        ),
                    )

        old_torch = self._torch
        old_device = self.compute_device
        if use_sparse_python:
            self._torch = None
            self.compute_device = None
        try:
            phase_context = (
                profiler.phase(
                    "optimizer",
                    stage="projection_update_batch",
                    legal_family="aggregate",
                    feature_head="+".join(target_tuple),
                    metadata={
                        "learning_rate": float(learning_rate),
                        "sample_count": len(sample_list),
                        "update_backend": normalized_backend,
                        "update_targets": list(target_tuple),
                    },
                )
                if profiler is not None
                else nullcontext()
            )
            with phase_context:
                for sample in sample_list:
                    legal_family = _target_family(sample) if profiler is not None else ""
                    for update_target in target_tuple:
                        head_context = (
                            profiler.phase(
                                "feature_head",
                                stage="projection_update_head",
                                legal_family=legal_family,
                                feature_head=update_target,
                            )
                            if profiler is not None
                            else nullcontext()
                        )
                        with head_context:
                            if update_target == "family_logits":
                                self._nudge_family_logits(
                                    sample,
                                    learning_rate=learning_rate,
                                    update_sample_memory=False,
                                )
                            elif update_target == "decoded_embedding":
                                self._nudge_decoded_embedding(
                                    sample,
                                    learning_rate=learning_rate,
                                    update_sample_memory=False,
                                )
                            elif update_target == "legal_ir_view_logits":
                                self._nudge_legal_ir_view_logits(
                                    sample,
                                    learning_rate=learning_rate,
                                    update_sample_memory=False,
                                )
                            elif update_target == "legal_ir_view_global_logits":
                                self._nudge_legal_ir_view_global_logits(
                                    sample,
                                    learning_rate=learning_rate,
                                )
                            else:
                                raise ValueError(
                                    f"unknown projection update target: {update_target}"
                                )
                if l2_regularization:
                    regularize_context = (
                        profiler.phase(
                            "optimizer",
                            stage="projection_l2_regularization",
                            legal_family="aggregate",
                        )
                        if profiler is not None
                        else nullcontext()
                    )
                    with regularize_context:
                        self._regularize_feature_state(l2_regularization)
        finally:
            if use_sparse_python:
                self._torch = old_torch
                self.compute_device = old_device
        norm_report = legal_ir_trainable_head_transaction_delta_norm_report(
            transaction,
            self.state,
            learning_rate=learning_rate,
        )
        norm_report["projection_update_backend"] = normalized_backend
        return norm_report


def load_checkpoint(path, *, expected_sha256, **model_options):
    """Load legacy weights locally under the unchanged eight-dimensional contract."""
    return load_local_checkpoint(Autoencoder, path, expected_sha256=expected_sha256,
                                 **model_options)


__all__ = ["Autoencoder", "TrainingState", "LegalSample", "DIMENSION", "LINEAGE_ID",
           "RUNTIME_PROFILE", "SOURCE_REVISION", "PORT_REVISION", "load_checkpoint",
           "build_sample"]
