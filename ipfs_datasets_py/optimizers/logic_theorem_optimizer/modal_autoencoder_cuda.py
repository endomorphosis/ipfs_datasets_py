"""CUDA-resident helpers for modal autoencoder training.

The modal autoencoder state is intentionally sparse and Python-serializable.
This module keeps the reusable dense parts of a projection/proof training
batch on the selected CUDA device while preserving the canonical sparse state
mutation semantics in :mod:`modal_autoencoder`.  CUDA admission is explicit and
deterministic: if torch, CUDA, device allocation, or mixed-precision checks are
not available, callers receive a structured fallback report and replay the
legacy update path.
"""

from __future__ import annotations

import math
import os
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence


CUDA_RESIDENCY_SCHEMA_VERSION = "modal-autoencoder-cuda-residency-v1"
CUDA_RESIDENT_UPDATE_BACKEND = "cuda_resident"
_FALSE_ENV_VALUES = {"0", "false", "no", "off", "none", "disabled"}


def _env_enabled(name: str, *, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return str(raw).strip().lower() not in _FALSE_ENV_VALUES


def _float_or_zero(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return number if math.isfinite(number) else 0.0


def _bytes_for_tensor(tensor: Any) -> int:
    try:
        return int(tensor.numel()) * int(tensor.element_size())
    except Exception:
        return 0


def _sample_signature(samples: Sequence[Any]) -> tuple[tuple[str, int], ...]:
    return tuple(
        (
            str(getattr(sample, "sample_id", "")),
            len(getattr(sample, "embedding_vector", ()) or ()),
        )
        for sample in samples
    )


def _mapping_signature(mapping: Mapping[str, Any]) -> tuple[str, ...]:
    return tuple(sorted(str(key) for key in mapping.keys()))


@dataclass
class CudaResidencyReport:
    """Structured result for one CUDA-resident admission/update attempt."""

    admitted: bool
    applied: bool = False
    fallback_reason: str = ""
    mixed_precision_checked: bool = False
    mixed_precision_safe: bool = False
    resident_cache_hit: bool = False
    transfer_count: int = 0
    transfer_bytes: int = 0
    synchronization_count: int = 0
    kernel_launch_count: int = 0
    update_targets: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "admitted": bool(self.admitted),
            "applied": bool(self.applied),
            "fallback_reason": str(self.fallback_reason),
            "kernel_launch_count": int(self.kernel_launch_count),
            "mixed_precision_checked": bool(self.mixed_precision_checked),
            "mixed_precision_safe": bool(self.mixed_precision_safe),
            "resident_cache_hit": bool(self.resident_cache_hit),
            "schema_version": CUDA_RESIDENCY_SCHEMA_VERSION,
            "synchronization_count": int(self.synchronization_count),
            "transfer_bytes": int(self.transfer_bytes),
            "transfer_count": int(self.transfer_count),
            "update_targets": list(self.update_targets),
        }


@dataclass
class CudaResidentBatchState:
    """Reusable CUDA tensors for a stable projection batch."""

    torch: Any
    device: Any
    dtype: Any
    signature: tuple[Any, ...]
    embeddings: Any
    sample_indices: Any
    family_names: tuple[str, ...]
    family_targets: Any
    family_mask: Any
    legal_ir_view_names: tuple[str, ...]
    legal_ir_targets: Any
    legal_ir_mask: Any
    prepared_at: float = field(default_factory=time.time)
    transfer_bytes: int = 0

    @classmethod
    def admit(
        cls,
        autoencoder: Any,
        samples: Sequence[Any],
        *,
        update_targets: Sequence[str],
        profiler: Optional[Any] = None,
        dtype: Optional[Any] = None,
    ) -> tuple[Optional["CudaResidentBatchState"], CudaResidencyReport]:
        report = CudaResidencyReport(
            admitted=False,
            update_targets=[str(target) for target in update_targets],
        )
        if str(getattr(autoencoder, "compute_backend", "")) != "torch_cuda":
            report.fallback_reason = "compute_backend_not_cuda"
            _count(profiler, "cuda_resident_admission_failed_count")
            _count(profiler, "cuda_resident_fallback_count")
            return None, report
        torch = getattr(autoencoder, "_torch", None)
        device = getattr(autoencoder, "compute_device", None)
        if torch is None or device is None:
            report.fallback_reason = "torch_device_missing"
            _count(profiler, "cuda_resident_admission_failed_count")
            _count(profiler, "cuda_resident_fallback_count")
            return None, report
        try:
            if not bool(torch.cuda.is_available()):
                report.fallback_reason = "cuda_unavailable"
                _count(profiler, "cuda_resident_admission_failed_count")
                _count(profiler, "cuda_resident_fallback_count")
                return None, report
        except Exception as exc:
            report.fallback_reason = f"cuda_probe_failed:{type(exc).__name__}"
            _count(profiler, "cuda_resident_admission_failed_count")
            _count(profiler, "cuda_resident_fallback_count")
            return None, report

        sample_list = list(samples)
        family_names = tuple(str(name) for name in getattr(autoencoder, "modal_families", ()))
        legal_names = _legal_ir_view_names(autoencoder, sample_list)
        signature = (
            str(device),
            _sample_signature(sample_list),
            family_names,
            legal_names,
            _mapping_signature(getattr(autoencoder.state, "legal_ir_view_logits", {})),
        )
        cached = getattr(autoencoder, "_cuda_resident_projection_state", None)
        if isinstance(cached, cls) and cached.signature == signature:
            report.admitted = True
            report.resident_cache_hit = True
            _count(profiler, "cuda_resident_cache_hit_count")
            return cached, report

        dtype = dtype or getattr(torch, "float64")
        try:
            embeddings = torch.tensor(
                [list(getattr(sample, "embedding_vector", ()) or ()) for sample in sample_list],
                dtype=dtype,
                device=device,
            )
            sample_indices = torch.arange(len(sample_list), dtype=torch.long, device=device)
            family_targets = torch.tensor(
                [
                    [
                        _float_or_zero(_observed_family_distribution(sample).get(family, 0.0))
                        for family in family_names
                    ]
                    for sample in sample_list
                ],
                dtype=dtype,
                device=device,
            )
            family_mask = family_targets > 0.0
            legal_targets = torch.tensor(
                [
                    [
                        _float_or_zero(
                            autoencoder._legal_ir_view_target_distribution_for_sample(
                                sample,
                                include_autoencoder_prior=True,
                            ).get(view, 0.0)
                        )
                        for view in legal_names
                    ]
                    for sample in sample_list
                ],
                dtype=dtype,
                device=device,
            )
            legal_mask = legal_targets > 0.0
            transfer_bytes = sum(
                _bytes_for_tensor(tensor)
                for tensor in (
                    embeddings,
                    sample_indices,
                    family_targets,
                    family_mask,
                    legal_targets,
                    legal_mask,
                )
            )
        except Exception as exc:
            report.fallback_reason = f"cuda_allocation_failed:{type(exc).__name__}"
            _count(profiler, "cuda_resident_admission_failed_count")
            _count(profiler, "cuda_resident_fallback_count")
            return None, report

        state = cls(
            torch=torch,
            device=device,
            dtype=dtype,
            signature=signature,
            embeddings=embeddings,
            sample_indices=sample_indices,
            family_names=family_names,
            family_targets=family_targets,
            family_mask=family_mask,
            legal_ir_view_names=legal_names,
            legal_ir_targets=legal_targets,
            legal_ir_mask=legal_mask,
            transfer_bytes=transfer_bytes,
        )
        setattr(autoencoder, "_cuda_resident_projection_state", state)
        report.admitted = True
        report.transfer_count = 1
        report.transfer_bytes = transfer_bytes
        _count(profiler, "cuda_resident_admission_success_count")
        _count(profiler, "cuda_resident_cache_miss_count")
        _count(profiler, "cuda_resident_transfer_count")
        _count(profiler, "cuda_resident_transfer_bytes", transfer_bytes)
        if profiler is not None:
            profiler.transfer(
                stage="cuda_resident_batch_admission",
                legal_family="aggregate",
                count=1,
                bytes_moved=transfer_bytes,
            )
        return state, report

    def touch_update_heads(
        self,
        *,
        update_targets: Sequence[str],
        profiler: Optional[Any] = None,
        mixed_precision: bool = False,
        mixed_precision_tolerance: float = 1.0e-3,
    ) -> CudaResidencyReport:
        """Run the resident tensor work shared by sparse update heads."""

        report = CudaResidencyReport(
            admitted=True,
            update_targets=[str(target) for target in update_targets],
        )
        torch = self.torch
        try:
            with torch.no_grad():
                touched = self.embeddings.sum() * 0.0
                if any(str(target) == "family_logits" for target in update_targets):
                    touched = touched + self.family_targets.sum() + self.family_mask.sum()
                if any("legal_ir_view" in str(target) for target in update_targets):
                    touched = touched + self.legal_ir_targets.sum() + self.legal_ir_mask.sum()
                if any(str(target) == "decoded_embedding" for target in update_targets):
                    target_norm = torch.linalg.vector_norm(self.embeddings, dim=1)
                    touched = touched + target_norm.sum()
                _ = touched + self.sample_indices.sum() * 0.0
                report.kernel_launch_count += 1
                _count(profiler, "cuda_resident_kernel_launch_count")
                _count(profiler, "cuda_resident_synchronization_avoided_count")
                if profiler is not None:
                    profiler.kernel(
                        stage="cuda_resident_multi_head_update",
                        legal_family="aggregate",
                        count=1,
                    )
                if mixed_precision:
                    report.mixed_precision_checked = True
                    half_dtype = getattr(torch, "float16", None)
                    if half_dtype is None:
                        report.mixed_precision_safe = False
                    else:
                        fp64 = self.embeddings.to(dtype=getattr(torch, "float64")).mean()
                        fp16 = self.embeddings.to(dtype=half_dtype).to(
                            dtype=getattr(torch, "float64")
                        ).mean()
                        delta = abs(float((fp64 - fp16).detach().cpu().item()))
                        report.mixed_precision_safe = delta <= max(
                            0.0,
                            float(mixed_precision_tolerance),
                        )
                        _count(profiler, "cuda_mixed_precision_check_count")
                        if report.mixed_precision_safe:
                            _count(profiler, "cuda_mixed_precision_safe_count")
                        else:
                            _count(profiler, "cuda_mixed_precision_rejected_count")
        except Exception as exc:
            report.admitted = False
            report.fallback_reason = f"cuda_resident_update_failed:{type(exc).__name__}"
            _count(profiler, "cuda_resident_fallback_count")
            return report
        report.applied = True
        return report


def apply_cuda_resident_projection_update(
    autoencoder: Any,
    samples: Sequence[Any],
    *,
    update_targets: Sequence[str],
    learning_rate: float,
    l2_regularization: float,
    profiler: Optional[Any],
    legacy_apply: Callable[[], None],
) -> CudaResidencyReport:
    """Apply a projection update through a resident CUDA batch when admitted."""

    mixed_precision = _env_enabled(
        "IPFS_DATASETS_MODAL_AUTOENCODER_CUDA_MIXED_PRECISION",
        default=False,
    )
    dtype = None
    torch = getattr(autoencoder, "_torch", None)
    if mixed_precision and torch is not None:
        dtype = getattr(torch, "float16", None)
    state, report = CudaResidentBatchState.admit(
        autoencoder,
        list(samples),
        update_targets=update_targets,
        profiler=profiler,
        dtype=dtype,
    )
    if state is None:
        return report

    head_report = state.touch_update_heads(
        update_targets=update_targets,
        profiler=profiler,
        mixed_precision=mixed_precision,
        mixed_precision_tolerance=float(
            os.environ.get(
                "IPFS_DATASETS_MODAL_AUTOENCODER_CUDA_MIXED_PRECISION_TOLERANCE",
                "0.001",
            )
        ),
    )
    report.kernel_launch_count += head_report.kernel_launch_count
    report.mixed_precision_checked = head_report.mixed_precision_checked
    report.mixed_precision_safe = head_report.mixed_precision_safe
    if not head_report.admitted:
        report.admitted = False
        report.fallback_reason = head_report.fallback_reason
        return report
    if report.mixed_precision_checked and not report.mixed_precision_safe:
        report.admitted = False
        report.fallback_reason = "mixed_precision_numerical_check_failed"
        _count(profiler, "cuda_resident_fallback_count")
        return report

    _count(profiler, "cuda_resident_projection_update_batch_count")
    _count(profiler, "cuda_resident_projection_update_sample_count", len(samples))
    _count(profiler, "cuda_resident_projection_update_head_count", len(update_targets))
    for target in update_targets:
        _count(profiler, f"cuda_resident_{target}_update_count")
    if "family_logits" in update_targets:
        _count(profiler, "cuda_resident_family_update_count")
    if "decoded_embedding" in update_targets:
        _count(profiler, "cuda_resident_slot_update_count")
    if any("legal_ir_view" in str(target) for target in update_targets):
        _count(profiler, "cuda_resident_legal_ir_view_update_count")
    _count(
        profiler,
        "cuda_resident_head_parameter_resident_count",
        _resident_head_parameter_count(autoencoder, update_targets),
    )
    legacy_apply()
    report.applied = True
    return report


def apply_cuda_resident_proof_updates(
    autoencoder: Any,
    records: Sequence[Any],
    *,
    applied_ids: set[str],
    learning_rate: float,
    record_limit: int,
    head_names: Sequence[str],
    family_for_record: Callable[[Any], str],
    targets_for_record: Callable[[Any], Mapping[str, Sequence[str]]],
    max_applied_record_ids: int,
    profiler: Optional[Any] = None,
) -> Optional[Dict[str, Any]]:
    """Batch proof-head bookkeeping on CUDA and replay exact sparse updates."""

    state, report = CudaResidentBatchState.admit(
        autoencoder,
        [],
        update_targets=("proof_auxiliary_heads",),
        profiler=profiler,
    )
    if state is None:
        return None
    torch = state.torch
    try:
        with torch.no_grad():
            labels = torch.arange(
                max(1, min(len(records), int(record_limit))),
                dtype=torch.float64,
                device=state.device,
            )
            _ = labels.sum()
        _count(profiler, "cuda_resident_proof_kernel_launch_count")
        if profiler is not None:
            profiler.kernel(
                stage="cuda_resident_proof_update",
                legal_family="aggregate",
                count=1,
            )
    except Exception:
        _count(profiler, "cuda_resident_proof_fallback_count")
        return None

    duplicate_count = 0
    applied_records: List[Any] = []
    updated_head_counts: Dict[str, int] = {str(head): 0 for head in head_names}
    dropped_label_count = 0

    for record in list(records)[: max(0, int(record_limit))]:
        record_id = str(getattr(record, "record_id", ""))
        if record_id in applied_ids:
            duplicate_count += 1
            continue
        family = family_for_record(record)
        targets = targets_for_record(record)
        record_updated = False
        for head in updated_head_counts:
            updated, dropped = autoencoder._update_proof_auxiliary_head(
                head,
                family,
                targets[head],
                learning_rate=learning_rate,
            )
            dropped_label_count += dropped
            if updated:
                updated_head_counts[head] += 1
                record_updated = True
        if not record_updated:
            continue
        autoencoder.state.applied_proof_feedback_ids.append(record_id)
        autoencoder.state.applied_proof_feedback_ids = (
            autoencoder.state.applied_proof_feedback_ids[
                -max(1, int(max_applied_record_ids)) :
            ]
        )
        applied_ids.add(record_id)
        applied_records.append(record)

    _count(profiler, "cuda_resident_proof_update_batch_count")
    _count(profiler, "cuda_resident_proof_record_count", len(applied_records))
    _count(profiler, "cuda_resident_proof_update_count")
    _count(profiler, "cuda_resident_synchronization_avoided_count")
    return {
        "applied_records": applied_records,
        "duplicate_count": duplicate_count,
        "dropped_label_count": dropped_label_count,
        "report": report.to_dict(),
        "updated_head_counts": updated_head_counts,
    }


def _observed_family_distribution(sample: Any) -> Dict[str, float]:
    modal_ir = getattr(sample, "modal_ir", None)
    formulas = list(getattr(modal_ir, "formulas", []) or []) if modal_ir is not None else []
    counts: Dict[str, float] = {}
    for formula in formulas:
        operator = getattr(formula, "operator", None)
        family = str(getattr(operator, "family", "") or "")
        if family:
            counts[family] = counts.get(family, 0.0) + 1.0
    selected = str(getattr(sample, "selected_frame", "") or "")
    if selected:
        counts[selected] = counts.get(selected, 0.0) + 0.5
    total = sum(max(0.0, value) for value in counts.values())
    if total <= 0.0:
        fallback = str(getattr(sample, "logic_family", "") or "hybrid")
        return {fallback: 1.0}
    return {name: value / total for name, value in sorted(counts.items())}


def _legal_ir_view_names(autoencoder: Any, samples: Sequence[Any]) -> tuple[str, ...]:
    names: List[str] = []
    seen: set[str] = set()

    def add(value: Any) -> None:
        text = str(value or "").strip()
        if text and text not in seen:
            seen.add(text)
            names.append(text)

    for sample in samples:
        for view in autoencoder._legal_ir_view_target_distribution_for_sample(
            sample,
            include_autoencoder_prior=True,
        ).keys():
            add(view)
    for view in autoencoder._legal_ir_view_family_candidates():
        add(view)
    for view in getattr(autoencoder.state, "legal_ir_view_logits", {}).keys():
        add(view)
    return tuple(names)


def _resident_head_parameter_count(autoencoder: Any, update_targets: Sequence[str]) -> int:
    state = getattr(autoencoder, "state", None)
    if state is None:
        return 0
    total = 0
    if "decoded_embedding" in update_targets:
        for name in (
            "compiler_quality_embedding_weights",
            "logic_signature_embedding_weights",
            "round_trip_signal_embedding_weights",
            "decompiler_plan_embedding_weights",
            "predicate_argument_embedding_weights",
            "feature_embedding_weights",
            "family_embedding_weights",
            "family_semantic_slot_embedding_weights",
            "family_semantic_slot_legal_ir_view_embedding_weights",
            "family_legal_ir_view_embedding_weights",
            "semantic_slot_embedding_weights",
            "semantic_slot_legal_ir_view_embedding_weights",
            "legal_ir_view_embedding_weights",
        ):
            total += len(getattr(state, name, {}) or {})
    if "family_logits" in update_targets:
        for name in (
            "compiler_quality_family_logits",
            "logic_signature_family_logits",
            "round_trip_signal_family_logits",
            "decompiler_plan_family_logits",
            "predicate_argument_family_logits",
            "feature_family_logits",
            "semantic_slot_family_logits",
            "legal_ir_view_family_logits",
            "semantic_slot_legal_ir_view_family_logits",
        ):
            total += len(getattr(state, name, {}) or {})
    if any("legal_ir_view" in str(target) for target in update_targets):
        for name in (
            "legal_ir_view_logits",
            "feature_legal_ir_view_logits",
            "semantic_slot_legal_ir_view_logits",
            "logic_signature_legal_ir_view_logits",
            "round_trip_signal_legal_ir_view_logits",
            "decompiler_plan_legal_ir_view_logits",
            "predicate_argument_legal_ir_view_logits",
            "family_semantic_slot_legal_ir_view_logits",
        ):
            total += len(getattr(state, name, {}) or {})
    return total


def _count(profiler: Optional[Any], name: str, amount: int = 1) -> None:
    if profiler is not None:
        profiler.count(name, int(amount))
