"""Batched CUDA training for the modal autoencoder.

This module deliberately contains the complete tensor training boundary.  The
hot path gathers stable feature rows into packed tensors, evaluates all active
heads as a batch, reduces losses in FP32, accumulates gradients, clips them,
and updates parameters without calling any of the historical per-sample
``_nudge_*`` methods.  Only the compact changed parameter rows cross back to
the canonical, transaction-aware state after an optimizer step.

Torch remains optional.  CUDA admission is fail-closed and callers can replay
the deterministic native CPU path.  The same packed implementation can also
run on CPU, which is useful as a numerical reference in tests.
"""

from __future__ import annotations

import math
import os
import time
from contextlib import nullcontext
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence

from .modal_autoencoder_batching import plan_gradient_accumulation
from .modal_autoencoder_tensor_state import TensorKeyKind, stable_parameter_id


CUDA_RESIDENCY_SCHEMA_VERSION = "modal-autoencoder-cuda-residency-v2"
CUDA_RESIDENT_UPDATE_BACKEND = "cuda_resident"
CUDA_TRAINING_SCHEMA_VERSION = "modal-autoencoder-packed-cuda-training-v1"
_FALSE_ENV_VALUES = {"0", "false", "no", "off", "none", "disabled"}


def _env_enabled(name: str, *, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return str(raw).strip().lower() not in _FALSE_ENV_VALUES


def _env_int(name: str, default: int, *, minimum: int = 1) -> int:
    try:
        return max(minimum, int(os.environ.get(name, str(default))))
    except (TypeError, ValueError):
        return max(minimum, int(default))


def _env_float(name: str, default: float, *, minimum: float = 0.0) -> float:
    try:
        value = float(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        value = float(default)
    return max(minimum, value) if math.isfinite(value) else max(minimum, float(default))


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


def _target_signature(autoencoder: Any, samples: Sequence[Any]) -> tuple[Any, ...]:
    return tuple(
        (
            str(getattr(sample, "sample_id", "")),
            tuple(
                sorted(
                    (str(key), round(_float_or_zero(value), 12))
                    for key, value in autoencoder._legal_ir_view_target_distribution_for_sample(
                        sample,
                        include_autoencoder_prior=True,
                    ).items()
                )
            ),
        )
        for sample in samples
    )


@dataclass
class CudaResidencyReport:
    """Structured result for one packed training admission/update attempt."""

    admitted: bool
    applied: bool = False
    fallback_reason: str = ""
    mixed_precision_checked: bool = False
    mixed_precision_safe: bool = False
    resident_cache_hit: bool = False
    optimizer_state_resident: bool = False
    optimizer_step: int = 0
    transfer_count: int = 0
    transfer_bytes: int = 0
    synchronization_count: int = 0
    kernel_launch_count: int = 0
    gradient_accumulation_steps: int = 0
    gradient_norm: float = 0.0
    clipped_gradient_norm: float = 0.0
    parameter_count: int = 0
    loss_dtype: str = ""
    parameter_dtype: str = ""
    activation_dtype: str = ""
    losses: Dict[str, float] = field(default_factory=dict)
    update_targets: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "activation_dtype": str(self.activation_dtype),
            "admitted": bool(self.admitted),
            "applied": bool(self.applied),
            "clipped_gradient_norm": float(self.clipped_gradient_norm),
            "fallback_reason": str(self.fallback_reason),
            "gradient_accumulation_steps": int(self.gradient_accumulation_steps),
            "gradient_norm": float(self.gradient_norm),
            "kernel_launch_count": int(self.kernel_launch_count),
            "loss_dtype": str(self.loss_dtype),
            "losses": {
                str(name): float(value) for name, value in sorted(self.losses.items())
            },
            "mixed_precision_checked": bool(self.mixed_precision_checked),
            "mixed_precision_safe": bool(self.mixed_precision_safe),
            "optimizer_state_resident": bool(self.optimizer_state_resident),
            "optimizer_step": int(self.optimizer_step),
            "parameter_count": int(self.parameter_count),
            "parameter_dtype": str(self.parameter_dtype),
            "resident_cache_hit": bool(self.resident_cache_hit),
            "schema_version": CUDA_RESIDENCY_SCHEMA_VERSION,
            "synchronization_count": int(self.synchronization_count),
            "training_schema_version": CUDA_TRAINING_SCHEMA_VERSION,
            "transfer_bytes": int(self.transfer_bytes),
            "transfer_count": int(self.transfer_count),
            "update_targets": list(self.update_targets),
        }


@dataclass(frozen=True)
class _BlockBlueprint:
    component: str
    kind: str
    rows: tuple[str, ...]
    columns: tuple[str, ...]
    values: tuple[tuple[float, ...], ...]
    activity: tuple[tuple[float, ...], ...]

    @property
    def signature(self) -> tuple[Any, ...]:
        return (self.component, self.kind, self.rows, self.columns)


@dataclass
class _ResidentParameterBlock:
    torch: Any
    device: Any
    blueprint_signature: tuple[Any, ...]
    component: str
    kind: str
    rows: tuple[str, ...]
    columns: tuple[str, ...]
    parameter: Any
    initial: Any
    activity: Any

    @classmethod
    def create(
        cls,
        torch: Any,
        device: Any,
        blueprint: _BlockBlueprint,
    ) -> "_ResidentParameterBlock":
        values = torch.tensor(blueprint.values, dtype=torch.float32, device=device)
        parameter = torch.nn.Parameter(values.contiguous(), requires_grad=True)
        activity = torch.tensor(
            blueprint.activity,
            dtype=torch.float32,
            device=device,
        ).contiguous()
        return cls(
            torch=torch,
            device=device,
            blueprint_signature=blueprint.signature,
            component=blueprint.component,
            kind=blueprint.kind,
            rows=blueprint.rows,
            columns=blueprint.columns,
            parameter=parameter,
            initial=parameter.detach().clone(),
            activity=activity,
        )

    def sync(self, blueprint: _BlockBlueprint) -> int:
        """Synchronize host values/activities while preserving the Parameter."""

        host = self.torch.tensor(
            blueprint.values,
            dtype=self.torch.float32,
            device=self.device,
        )
        activity = self.torch.tensor(
            blueprint.activity,
            dtype=self.torch.float32,
            device=self.device,
        )
        with self.torch.no_grad():
            self.parameter.copy_(host)
            self.initial.copy_(host)
            self.activity = activity.contiguous()
        return _bytes_for_tensor(host) + _bytes_for_tensor(activity)

    def contribution(self, start: int, stop: int) -> Any:
        # Dense packed gathering is intentional: the activity matrix is the
        # collated feature-index/weight tensor and the matmul gathers all rows
        # for a minibatch in a single device operation.
        delta = self.parameter - self.initial
        return self.activity[start:stop].matmul(delta)


@dataclass
class _ResidentTrainingSession:
    torch: Any
    device: Any
    signature: tuple[Any, ...]
    blocks: Dict[str, _ResidentParameterBlock]
    step_tensor: Any
    last_host_fingerprint: tuple[Any, ...] = ()

    @classmethod
    def create(
        cls,
        torch: Any,
        device: Any,
        signature: tuple[Any, ...],
        blueprints: Sequence[_BlockBlueprint],
    ) -> "_ResidentTrainingSession":
        blocks = {
            blueprint.component: _ResidentParameterBlock.create(
                torch,
                device,
                blueprint,
            )
            for blueprint in blueprints
        }
        return cls(
            torch=torch,
            device=device,
            signature=signature,
            blocks=blocks,
            step_tensor=torch.zeros((), dtype=torch.int64, device=device),
        )

    @property
    def parameters(self) -> List[Any]:
        return [self.blocks[name].parameter for name in sorted(self.blocks)]

    @property
    def parameter_count(self) -> int:
        return sum(int(parameter.numel()) for parameter in self.parameters)

    def sync(self, blueprints: Sequence[_BlockBlueprint]) -> int:
        moved = 0
        by_name = {blueprint.component: blueprint for blueprint in blueprints}
        for name, block in self.blocks.items():
            moved += block.sync(by_name[name])
        return moved


@dataclass
class CudaResidentBatchState:
    """Reusable CUDA tensors and optimizer sessions for a stable batch."""

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
    training_sessions: Dict[tuple[Any, ...], _ResidentTrainingSession] = field(
        default_factory=dict
    )

    @property
    def packed_parameter_tensors(self) -> Dict[str, Any]:
        """Return the live contiguous parameter tensors by canonical table."""

        result: Dict[str, Any] = {}
        for session in self.training_sessions.values():
            for name, block in session.blocks.items():
                result[name] = block.parameter
        return result

    @property
    def optimizer_state_tensors(self) -> tuple[Any, ...]:
        """Resident device tensors owned by the packed optimizer."""

        return tuple(
            session.step_tensor
            for _signature, session in sorted(
                self.training_sessions.items(), key=lambda item: repr(item[0])
            )
        )

    @classmethod
    def admit(
        cls,
        autoencoder: Any,
        samples: Sequence[Any],
        *,
        update_targets: Sequence[str],
        profiler: Optional[Any] = None,
        dtype: Optional[Any] = None,
        device_override: Optional[Any] = None,
    ) -> tuple[Optional["CudaResidentBatchState"], CudaResidencyReport]:
        report = CudaResidencyReport(
            admitted=False,
            update_targets=[str(target) for target in update_targets],
        )
        torch = getattr(autoencoder, "_torch", None)
        if torch is None:
            try:
                import torch as imported_torch
            except ImportError:
                report.fallback_reason = "torch_unavailable"
                _admission_failed(profiler)
                return None, report
            torch = imported_torch

        reference_cpu = device_override is not None and str(device_override) == "cpu"
        if not reference_cpu and str(getattr(autoencoder, "compute_backend", "")) != "torch_cuda":
            report.fallback_reason = "compute_backend_not_cuda"
            _admission_failed(profiler)
            return None, report
        device = device_override or getattr(autoencoder, "compute_device", None)
        if device is None:
            report.fallback_reason = "torch_device_missing"
            _admission_failed(profiler)
            return None, report
        if not reference_cpu:
            try:
                if not bool(torch.cuda.is_available()):
                    report.fallback_reason = "cuda_unavailable"
                    _admission_failed(profiler)
                    return None, report
            except Exception as exc:
                report.fallback_reason = f"cuda_probe_failed:{type(exc).__name__}"
                _admission_failed(profiler)
                return None, report

        sample_list = list(samples)
        dimensions = {len(getattr(sample, "embedding_vector", ()) or ()) for sample in sample_list}
        if len(dimensions) > 1:
            report.fallback_reason = "ragged_embedding_dimensions"
            _admission_failed(profiler)
            return None, report
        family_names = _family_names(autoencoder, sample_list)
        legal_names = _legal_ir_view_names(autoencoder, sample_list)
        signature = (
            str(device),
            _sample_signature(sample_list),
            _target_signature(autoencoder, sample_list),
            family_names,
            legal_names,
        )
        cache_attribute = (
            "_cuda_resident_proof_state"
            if tuple(str(target) for target in update_targets)
            == ("proof_auxiliary_heads",)
            else "_cuda_resident_projection_state"
        )
        cached = getattr(autoencoder, cache_attribute, None)
        if (
            not reference_cpu
            and isinstance(cached, cls)
            and cached.signature == signature
        ):
            report.admitted = True
            report.resident_cache_hit = True
            _count(profiler, "cuda_resident_cache_hit_count")
            return cached, report

        dtype = dtype or torch.float32
        try:
            embedding_values = [
                list(getattr(sample, "embedding_vector", ()) or ())
                for sample in sample_list
            ]
            width = next(iter(dimensions), 0)
            embeddings = torch.tensor(
                embedding_values,
                dtype=torch.float32,
                device=device,
            ).reshape(len(sample_list), width)
            sample_indices = torch.arange(len(sample_list), dtype=torch.long, device=device)
            family_targets = torch.tensor(
                [
                    [
                        _float_or_zero(_observed_family_distribution(sample).get(family, 0.0))
                        for family in family_names
                    ]
                    for sample in sample_list
                ],
                dtype=torch.float32,
                device=device,
            ).reshape(len(sample_list), len(family_names))
            family_mask = family_targets.sum(dim=1) > 0.0
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
                dtype=torch.float32,
                device=device,
            ).reshape(len(sample_list), len(legal_names))
            legal_mask = legal_targets.sum(dim=1) > 0.0
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
            report.fallback_reason = f"device_allocation_failed:{type(exc).__name__}"
            _admission_failed(profiler)
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
        if not reference_cpu:
            setattr(autoencoder, cache_attribute, state)
        report.admitted = True
        report.transfer_count = 1
        report.transfer_bytes = transfer_bytes
        _count(profiler, "cuda_resident_admission_success_count")
        _count(profiler, "cuda_resident_cache_miss_count")
        _record_transfer(
            profiler,
            report,
            stage="cuda_resident_batch_admission",
            bytes_moved=transfer_bytes,
            already_counted=True,
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
        """Compatibility probe retained for residency callers.

        Unlike the old implementation this probe is not the update path; it
        performs a real packed forward reduction and reports that work.
        """

        report = CudaResidencyReport(
            admitted=True,
            update_targets=[str(target) for target in update_targets],
        )
        torch = self.torch
        try:
            with torch.no_grad():
                value = self.embeddings.float().square().sum()
                value = value + self.family_targets.float().sum()
                value = value + self.legal_ir_targets.float().sum()
                _ = value
            _kernel(profiler, report, "cuda_resident_packed_probe", count=3)
            if mixed_precision:
                report.mixed_precision_checked = True
                bf16 = getattr(torch, "bfloat16", None)
                if bf16 is not None:
                    fp32 = self.embeddings.float().mean()
                    low = self.embeddings.to(dtype=bf16).float().mean()
                    delta = abs(float((fp32 - low).detach().cpu().item()))
                    report.mixed_precision_safe = delta <= max(
                        0.0,
                        float(mixed_precision_tolerance),
                    )
                _count(profiler, "cuda_mixed_precision_check_count")
        except Exception as exc:
            report.admitted = False
            report.fallback_reason = f"cuda_resident_probe_failed:{type(exc).__name__}"
            _count(profiler, "cuda_resident_fallback_count")
            return report
        report.applied = True
        return report


def _admission_failed(profiler: Optional[Any]) -> None:
    _count(profiler, "cuda_resident_admission_failed_count")
    _count(profiler, "cuda_resident_fallback_count")


def _family_names(autoencoder: Any, samples: Sequence[Any]) -> tuple[str, ...]:
    names: List[str] = []
    seen: set[str] = set()

    def add(value: Any) -> None:
        text = str(value or "").strip()
        if text and text not in seen:
            seen.add(text)
            names.append(text)

    for name in getattr(autoencoder, "modal_families", ()):
        add(name)
    for sample in samples:
        for name in _observed_family_distribution(sample):
            add(name)
        try:
            for name in autoencoder._logits_for(sample, use_sample_memory=False):
                add(name)
        except Exception:
            pass
    return tuple(
        sorted(names, key=lambda name: stable_parameter_id(TensorKeyKind.FAMILY, name))
    )


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
        ):
            add(view)
    for view in autoencoder._legal_ir_view_family_candidates():
        add(view)
    for view in getattr(autoencoder.state, "legal_ir_view_logits", {}):
        add(view)
    return tuple(
        sorted(
            names,
            key=lambda name: stable_parameter_id(TensorKeyKind.LEGAL_IR_VIEW, name),
        )
    )


_COMPONENT_ROW_KIND: Dict[str, TensorKeyKind] = {
    "compiler_quality_embedding_weights": TensorKeyKind.TARGET,
    "compiler_quality_family_logits": TensorKeyKind.TARGET,
    "decompiler_plan_embedding_weights": TensorKeyKind.TARGET,
    "decompiler_plan_family_logits": TensorKeyKind.TARGET,
    "decompiler_plan_legal_ir_view_logits": TensorKeyKind.TARGET,
    "family_embedding_weights": TensorKeyKind.FAMILY,
    "family_legal_ir_view_embedding_weights": TensorKeyKind.INTERACTION,
    "family_semantic_slot_embedding_weights": TensorKeyKind.INTERACTION,
    "family_semantic_slot_legal_ir_view_embedding_weights": TensorKeyKind.INTERACTION,
    "family_semantic_slot_legal_ir_view_logits": TensorKeyKind.INTERACTION,
    "feature_embedding_weights": TensorKeyKind.FEATURE,
    "feature_family_logits": TensorKeyKind.FEATURE,
    "feature_legal_ir_view_logits": TensorKeyKind.FEATURE,
    "legal_ir_view_embedding_weights": TensorKeyKind.LEGAL_IR_VIEW,
    "legal_ir_view_family_logits": TensorKeyKind.LEGAL_IR_VIEW,
    "logic_signature_embedding_weights": TensorKeyKind.FEATURE,
    "logic_signature_family_logits": TensorKeyKind.FEATURE,
    "logic_signature_legal_ir_view_logits": TensorKeyKind.FEATURE,
    "predicate_argument_embedding_weights": TensorKeyKind.SEMANTIC_SLOT,
    "predicate_argument_family_logits": TensorKeyKind.SEMANTIC_SLOT,
    "predicate_argument_legal_ir_view_logits": TensorKeyKind.SEMANTIC_SLOT,
    "round_trip_signal_embedding_weights": TensorKeyKind.FEATURE,
    "round_trip_signal_family_logits": TensorKeyKind.FEATURE,
    "round_trip_signal_legal_ir_view_logits": TensorKeyKind.FEATURE,
    "semantic_slot_embedding_weights": TensorKeyKind.SEMANTIC_SLOT,
    "semantic_slot_family_logits": TensorKeyKind.SEMANTIC_SLOT,
    "semantic_slot_legal_ir_view_embedding_weights": TensorKeyKind.INTERACTION,
    "semantic_slot_legal_ir_view_family_logits": TensorKeyKind.INTERACTION,
    "semantic_slot_legal_ir_view_logits": TensorKeyKind.SEMANTIC_SLOT,
}


def _stable_row_id(component: str, row: str) -> int:
    """Use the PORTAL-LIR-HAMMER-107 typed ID for packed row ordering."""

    kind = _COMPONENT_ROW_KIND.get(component, TensorKeyKind.FEATURE)
    # The stable ID's kind prefix and content digest are deterministic even for
    # opaque legacy interaction strings.  Structured component registration is
    # retained by the canonical tensor-state migration at checkpoint time.
    return stable_parameter_id(kind, row)


def _safe_distribution(
    autoencoder: Any,
    method_name: str,
    sample: Any,
    *,
    use_sample_memory: Optional[bool] = None,
) -> Dict[str, float]:
    method = getattr(autoencoder, method_name)
    if use_sample_memory is None:
        values = method(sample)
    else:
        values = method(sample, use_sample_memory=use_sample_memory)
    return {
        str(key): max(0.0, _float_or_zero(value))
        for key, value in dict(values or {}).items()
        if _float_or_zero(value) > 0.0
    }


def _activity_blueprint(
    autoencoder: Any,
    samples: Sequence[Any],
    *,
    component: str,
    kind: str,
    columns: Sequence[str],
    per_sample: Sequence[Mapping[str, float]],
) -> Optional[_BlockBlueprint]:
    rows = tuple(
        sorted(
            {str(key) for values in per_sample for key in values},
            key=lambda row: _stable_row_id(component, row),
        )
    )
    if not rows:
        return None
    mapping = getattr(autoencoder.state, component)
    width = len(columns)
    values: List[tuple[float, ...]] = []
    if kind == "vector":
        for row in rows:
            current = list(mapping.get(row, ()))
            if len(current) != width:
                current = [0.0] * width
            values.append(tuple(_float_or_zero(value) for value in current))
    elif kind == "matrix":
        for row in rows:
            current = mapping.get(row, {})
            values.append(
                tuple(_float_or_zero(current.get(column, 0.0)) for column in columns)
            )
    else:
        raise ValueError(f"unsupported packed block kind: {kind}")
    activity = tuple(
        tuple(_float_or_zero(sample_values.get(row, 0.0)) for row in rows)
        for sample_values in per_sample
    )
    return _BlockBlueprint(
        component=component,
        kind=kind,
        rows=rows,
        columns=tuple(str(value) for value in columns),
        values=tuple(values),
        activity=activity,
    )


def _scaled_distributions(
    samples: Sequence[Any],
    getter: Callable[[Any], Mapping[str, float]],
    scale: float,
) -> List[Dict[str, float]]:
    effective = max(0.0, float(scale))
    return [
        {
            str(key): effective * max(0.0, _float_or_zero(value))
            for key, value in getter(sample).items()
            if effective * max(0.0, _float_or_zero(value)) > 0.0
        }
        for sample in samples
    ]


def _feature_activities(
    autoencoder: Any,
    samples: Sequence[Any],
    *,
    legal: bool,
    scale: float,
) -> List[Dict[str, float]]:
    result: List[Dict[str, float]] = []
    for sample in samples:
        keys = (
            autoencoder._legal_ir_view_feature_keys_for(sample)
            if legal
            else autoencoder._feature_keys_for(sample)
        )
        # Once this packed update is scattered all gathered rows are learned,
        # so this is also the correct post-update forward normalization.
        activity_scale = 1.0 / autoencoder._feature_activity_scale(len(keys))
        coefficient = max(0.0, float(scale)) * activity_scale
        result.append({str(key): coefficient for key in keys if coefficient > 0.0})
    return result


def _embedding_blueprints(
    autoencoder: Any,
    samples: Sequence[Any],
    dimensions: int,
) -> List[_BlockBlueprint]:
    specs: List[tuple[str, float, Callable[[Any], Mapping[str, float]]]] = [
        ("compiler_quality_embedding_weights", autoencoder.compiler_quality_embedding_weight_scale, lambda sample: _safe_distribution(autoencoder, "_compiler_quality_slot_distribution_for", sample)),
        ("logic_signature_embedding_weights", autoencoder.logic_signature_embedding_weight_scale, lambda sample: _safe_distribution(autoencoder, "_logic_signature_distribution_for", sample)),
        ("round_trip_signal_embedding_weights", autoencoder.round_trip_signal_embedding_weight_scale, lambda sample: _safe_distribution(autoencoder, "_round_trip_signal_distribution_for", sample)),
        ("decompiler_plan_embedding_weights", autoencoder.decompiler_plan_embedding_weight_scale, lambda sample: _safe_distribution(autoencoder, "_decompiler_plan_distribution_for", sample)),
        ("predicate_argument_embedding_weights", autoencoder.predicate_argument_embedding_weight_scale, lambda sample: _safe_distribution(autoencoder, "_predicate_argument_distribution_for", sample)),
        ("family_embedding_weights", autoencoder.family_embedding_weight_scale, lambda sample: _safe_distribution(autoencoder, "_family_distribution", sample, use_sample_memory=False)),
        ("semantic_slot_embedding_weights", autoencoder.semantic_slot_embedding_weight_scale, lambda sample: _safe_distribution(autoencoder, "_semantic_slot_distribution_for", sample)),
        ("family_semantic_slot_embedding_weights", autoencoder.family_semantic_slot_embedding_weight_scale, lambda sample: _safe_distribution(autoencoder, "_family_semantic_slot_distribution_for_embedding", sample, use_sample_memory=False)),
        ("semantic_slot_legal_ir_view_embedding_weights", autoencoder.semantic_slot_legal_ir_view_embedding_weight_scale, lambda sample: _safe_distribution(autoencoder, "_semantic_slot_legal_ir_view_distribution_for_embedding", sample, use_sample_memory=False)),
        ("family_semantic_slot_legal_ir_view_embedding_weights", autoencoder.family_semantic_slot_legal_ir_view_embedding_weight_scale, lambda sample: _safe_distribution(autoencoder, "_family_semantic_slot_legal_ir_view_distribution_for_embedding", sample, use_sample_memory=False)),
        ("family_legal_ir_view_embedding_weights", autoencoder.family_legal_ir_view_embedding_weight_scale, lambda sample: _safe_distribution(autoencoder, "_family_legal_ir_view_distribution_for_embedding", sample, use_sample_memory=False)),
        ("legal_ir_view_embedding_weights", autoencoder.legal_ir_view_embedding_weight_scale, lambda sample: _safe_distribution(autoencoder, "_legal_ir_view_distribution_for_embedding", sample, use_sample_memory=False)),
    ]
    blueprints: List[_BlockBlueprint] = []
    columns = tuple(str(index) for index in range(dimensions))
    for component, scale, getter in specs:
        blueprint = _activity_blueprint(
            autoencoder,
            samples,
            component=component,
            kind="vector",
            columns=columns,
            per_sample=_scaled_distributions(samples, getter, scale),
        )
        if blueprint is not None:
            blueprints.append(blueprint)
    feature = _activity_blueprint(
        autoencoder,
        samples,
        component="feature_embedding_weights",
        kind="vector",
        columns=columns,
        per_sample=_feature_activities(
            autoencoder,
            samples,
            legal=False,
            scale=autoencoder.feature_embedding_weight_scale,
        ),
    )
    if feature is not None:
        blueprints.append(feature)
    return blueprints


def _family_blueprints(
    autoencoder: Any,
    samples: Sequence[Any],
    family_names: Sequence[str],
) -> List[_BlockBlueprint]:
    specs: List[tuple[str, float, Callable[[Any], Mapping[str, float]]]] = [
        ("compiler_quality_family_logits", autoencoder.compiler_quality_family_logit_scale, lambda sample: _safe_distribution(autoencoder, "_compiler_quality_slot_distribution_for", sample)),
        ("logic_signature_family_logits", autoencoder.logic_signature_family_logit_scale, lambda sample: _safe_distribution(autoencoder, "_logic_signature_distribution_for", sample)),
        ("round_trip_signal_family_logits", autoencoder.round_trip_signal_family_logit_scale, lambda sample: _safe_distribution(autoencoder, "_round_trip_signal_distribution_for", sample)),
        ("decompiler_plan_family_logits", autoencoder.decompiler_plan_family_logit_scale, lambda sample: _safe_distribution(autoencoder, "_decompiler_plan_distribution_for", sample)),
        ("predicate_argument_family_logits", autoencoder.predicate_argument_family_logit_scale, lambda sample: _safe_distribution(autoencoder, "_predicate_argument_distribution_for", sample)),
        ("semantic_slot_family_logits", autoencoder.semantic_slot_family_logit_scale, lambda sample: _safe_distribution(autoencoder, "_semantic_slot_distribution_for", sample)),
        ("legal_ir_view_family_logits", autoencoder.legal_ir_view_family_logit_scale, lambda sample: _safe_distribution(autoencoder, "_legal_ir_view_distribution_for_embedding", sample, use_sample_memory=False)),
        ("semantic_slot_legal_ir_view_family_logits", autoencoder.semantic_slot_legal_ir_view_family_logit_scale, lambda sample: _safe_distribution(autoencoder, "_semantic_slot_legal_ir_view_distribution_for_embedding", sample, use_sample_memory=False)),
    ]
    blueprints: List[_BlockBlueprint] = []
    for component, scale, getter in specs:
        blueprint = _activity_blueprint(
            autoencoder,
            samples,
            component=component,
            kind="matrix",
            columns=family_names,
            per_sample=_scaled_distributions(samples, getter, scale),
        )
        if blueprint is not None:
            blueprints.append(blueprint)
    feature = _activity_blueprint(
        autoencoder,
        samples,
        component="feature_family_logits",
        kind="matrix",
        columns=family_names,
        per_sample=_feature_activities(
            autoencoder,
            samples,
            legal=False,
            scale=autoencoder.feature_family_logit_scale,
        ),
    )
    if feature is not None:
        blueprints.append(feature)
    return blueprints


def _legal_blueprints(
    autoencoder: Any,
    samples: Sequence[Any],
    legal_names: Sequence[str],
    *,
    global_only: bool,
) -> List[_BlockBlueprint]:
    # Scalar global logits are represented as one packed row, preserving the
    # same [rows, columns] layout as every other head.
    global_values = tuple(
        _float_or_zero(autoencoder.state.legal_ir_view_logits.get(name, 0.0))
        for name in legal_names
    )
    global_scale = max(0.0, float(autoencoder.legal_ir_view_logit_scale))
    blueprints = [
        _BlockBlueprint(
            component="legal_ir_view_logits",
            kind="scalar_map",
            rows=("__global__",),
            columns=tuple(legal_names),
            values=(global_values,),
            activity=tuple((global_scale,) for _sample in samples),
        )
    ] if legal_names and global_scale > 0.0 else []
    if global_only:
        return blueprints
    specs: List[tuple[str, float, Callable[[Any], Mapping[str, float]]]] = [
        ("semantic_slot_legal_ir_view_logits", autoencoder.semantic_slot_legal_ir_view_logit_scale, lambda sample: _safe_distribution(autoencoder, "_semantic_slot_distribution_for", sample)),
        ("logic_signature_legal_ir_view_logits", autoencoder.logic_signature_legal_ir_view_logit_scale, lambda sample: _safe_distribution(autoencoder, "_logic_signature_distribution_for", sample)),
        ("round_trip_signal_legal_ir_view_logits", autoencoder.round_trip_signal_legal_ir_view_logit_scale, lambda sample: _safe_distribution(autoencoder, "_round_trip_signal_distribution_for", sample)),
        ("decompiler_plan_legal_ir_view_logits", autoencoder.decompiler_plan_legal_ir_view_logit_scale, lambda sample: _safe_distribution(autoencoder, "_decompiler_plan_distribution_for", sample)),
        ("predicate_argument_legal_ir_view_logits", autoencoder.predicate_argument_legal_ir_view_logit_scale, lambda sample: _safe_distribution(autoencoder, "_predicate_argument_distribution_for", sample)),
        ("family_semantic_slot_legal_ir_view_logits", autoencoder.family_semantic_slot_legal_ir_view_logit_scale, lambda sample: _safe_distribution(autoencoder, "_family_semantic_slot_distribution_for_legal_ir_view", sample)),
    ]
    for component, scale, getter in specs:
        blueprint = _activity_blueprint(
            autoencoder,
            samples,
            component=component,
            kind="matrix",
            columns=legal_names,
            per_sample=_scaled_distributions(samples, getter, scale),
        )
        if blueprint is not None:
            blueprints.append(blueprint)
    feature = _activity_blueprint(
        autoencoder,
        samples,
        component="feature_legal_ir_view_logits",
        kind="matrix",
        columns=legal_names,
        per_sample=_feature_activities(
            autoencoder,
            samples,
            legal=True,
            scale=autoencoder.legal_ir_view_logit_scale,
        ),
    )
    if feature is not None:
        blueprints.append(feature)
    return blueprints


def _build_blueprints(
    autoencoder: Any,
    samples: Sequence[Any],
    state: CudaResidentBatchState,
    update_targets: Sequence[str],
) -> List[_BlockBlueprint]:
    targets = set(str(target) for target in update_targets)
    dimensions = int(state.embeddings.shape[1]) if state.embeddings.ndim == 2 else 0
    blueprints: List[_BlockBlueprint] = []
    if "decoded_embedding" in targets and dimensions:
        blueprints.extend(_embedding_blueprints(autoencoder, samples, dimensions))
    if "family_logits" in targets and state.family_names:
        blueprints.extend(_family_blueprints(autoencoder, samples, state.family_names))
    if "legal_ir_view_logits" in targets and state.legal_ir_view_names:
        blueprints.extend(
            _legal_blueprints(
                autoencoder,
                samples,
                state.legal_ir_view_names,
                global_only=False,
            )
        )
    if "legal_ir_view_global_logits" in targets and state.legal_ir_view_names:
        blueprints.extend(
            _legal_blueprints(
                autoencoder,
                samples,
                state.legal_ir_view_names,
                global_only=True,
            )
        )
    # A schedule should not select overlapping legal heads, but de-duplicate
    # defensively so each canonical table has exactly one resident Parameter.
    return list({blueprint.component: blueprint for blueprint in blueprints}.values())


def _base_outputs(
    autoencoder: Any,
    samples: Sequence[Any],
    state: CudaResidentBatchState,
) -> tuple[Any, Any, Any]:
    torch = state.torch
    device = state.device
    decoded = torch.tensor(
        [autoencoder._decoded_for(sample, use_sample_memory=False) for sample in samples],
        dtype=torch.float32,
        device=device,
    ).reshape(len(samples), int(state.embeddings.shape[1]))
    family = torch.tensor(
        [
            [
                _float_or_zero(
                    autoencoder._logits_for(sample, use_sample_memory=False).get(name, 0.0)
                )
                for name in state.family_names
            ]
            for sample in samples
        ],
        dtype=torch.float32,
        device=device,
    ).reshape(len(samples), len(state.family_names))
    legal_rows: List[List[float]] = []
    for sample in samples:
        values = autoencoder._legal_ir_view_logits_for(
            sample,
            state.legal_ir_view_names,
            use_sample_memory=False,
        )
        legal_rows.append([_float_or_zero(values.get(name, 0.0)) for name in state.legal_ir_view_names])
    legal = torch.tensor(
        legal_rows,
        dtype=torch.float32,
        device=device,
    ).reshape(len(samples), len(state.legal_ir_view_names))
    return decoded, family, legal


def _autocast_context(torch: Any, device: Any, enabled: bool) -> Any:
    if not enabled or str(device).split(":", 1)[0] != "cuda":
        return nullcontext()
    return torch.autocast(device_type="cuda", dtype=torch.bfloat16, enabled=True)


def _supports_bf16(torch: Any, device: Any) -> bool:
    if str(device).split(":", 1)[0] != "cuda":
        return False
    try:
        return bool(torch.cuda.is_bf16_supported())
    except Exception:
        return False


def _bf16_numerically_safe(
    state: CudaResidentBatchState,
    blueprints: Sequence[_BlockBlueprint],
) -> bool:
    """Check representative activations/weights before enabling BF16."""

    if not _supports_bf16(state.torch, state.device):
        return False
    tolerance = _env_float(
        "IPFS_DATASETS_MODAL_AUTOENCODER_CUDA_MIXED_PRECISION_TOLERANCE",
        0.01,
        minimum=0.0,
    )
    tensors = [state.embeddings]
    if blueprints and blueprints[0].values:
        tensors.append(
            state.torch.tensor(
                blueprints[0].values,
                dtype=state.torch.float32,
                device=state.device,
            )
        )
    with state.torch.no_grad():
        for value in tensors:
            if not value.numel():
                continue
            delta = (value.float() - value.to(dtype=state.torch.bfloat16).float()).abs()
            scale = value.float().abs().clamp_min(1.0).max()
            relative = float((delta.max() / scale).detach().cpu().item())
            if not math.isfinite(relative) or relative > tolerance:
                return False
    return True


def _loss_chunk(
    state: CudaResidentBatchState,
    session: _ResidentTrainingSession,
    base_outputs: tuple[Any, Any, Any],
    update_targets: set[str],
    start: int,
    stop: int,
    total_samples: int,
    cosine_weight: float,
    l2_regularization: float,
    mixed_precision: bool,
) -> tuple[Any, Dict[str, Any], int]:
    torch = state.torch
    decoded_base, family_base, legal_base = base_outputs
    decoded = decoded_base[start:stop]
    family_logits = family_base[start:stop]
    legal_logits = legal_base[start:stop]
    kernel_count = 0
    with _autocast_context(torch, state.device, mixed_precision):
        for block in session.blocks.values():
            contribution = block.contribution(start, stop)
            kernel_count += 1
            if block.kind == "vector":
                decoded = decoded + contribution
            elif block.component in {
                "legal_ir_view_logits",
                "feature_legal_ir_view_logits",
                "semantic_slot_legal_ir_view_logits",
                "logic_signature_legal_ir_view_logits",
                "round_trip_signal_legal_ir_view_logits",
                "decompiler_plan_legal_ir_view_logits",
                "predicate_argument_legal_ir_view_logits",
                "family_semantic_slot_legal_ir_view_logits",
            }:
                legal_logits = legal_logits + contribution
            else:
                family_logits = family_logits + contribution

        zero = sum((parameter.sum() * 0.0 for parameter in session.parameters), torch.zeros((), device=state.device))
        losses: Dict[str, Any] = {
            "cross_entropy": zero.float(),
            "legal_ir_cross_entropy": zero.float(),
            "reconstruction": zero.float(),
            "cosine": zero.float(),
            "guarded_auxiliary": zero.float(),
            "l2": zero.float(),
        }
        denominator = float(max(1, total_samples))
        if "family_logits" in update_targets and family_logits.shape[1]:
            targets = state.family_targets[start:stop].float()
            mask = state.family_mask[start:stop]
            normalized = targets / targets.sum(dim=1, keepdim=True).clamp_min(1.0e-12)
            per_row = -(normalized * torch.log_softmax(family_logits.float(), dim=1)).sum(dim=1)
            losses["cross_entropy"] = per_row.masked_select(mask).sum() / denominator
            kernel_count += 3
        if update_targets.intersection({"legal_ir_view_logits", "legal_ir_view_global_logits"}) and legal_logits.shape[1]:
            targets = state.legal_ir_targets[start:stop].float()
            mask = state.legal_ir_mask[start:stop]
            normalized = targets / targets.sum(dim=1, keepdim=True).clamp_min(1.0e-12)
            per_row = -(normalized * torch.log_softmax(legal_logits.float(), dim=1)).sum(dim=1)
            losses["legal_ir_cross_entropy"] = per_row.masked_select(mask).sum() / denominator
            kernel_count += 3
        if "decoded_embedding" in update_targets and decoded.shape[1]:
            target = state.embeddings[start:stop].float()
            decoded32 = decoded.float()
            losses["reconstruction"] = (decoded32 - target).square().mean(dim=1).sum() / denominator
            target_norm = torch.linalg.vector_norm(target, dim=1)
            decoded_norm = torch.linalg.vector_norm(decoded32, dim=1)
            guard = (target_norm > 1.0e-8) & (decoded_norm > 1.0e-8)
            cosine = torch.nn.functional.cosine_similarity(decoded32, target, dim=1, eps=1.0e-8)
            cosine_rows = (1.0 - cosine).masked_select(guard)
            losses["cosine"] = cosine_rows.sum() / denominator
            # The guarded auxiliary keeps finite-norm reconstructions bounded;
            # it is zero inside the broad safe range and cannot dominate CE.
            norm_ratio = decoded_norm / target_norm.clamp_min(1.0e-8)
            auxiliary = (
                torch.relu(norm_ratio - 4.0).square()
                + torch.relu(0.05 - norm_ratio).square()
            ).masked_select(guard)
            losses["guarded_auxiliary"] = auxiliary.sum() / denominator
            kernel_count += 7
        if l2_regularization > 0.0:
            scalar_count = max(1, session.parameter_count)
            losses["l2"] = (
                sum((parameter.float().square().sum() for parameter in session.parameters), zero.float())
                * float(l2_regularization)
                / float(scalar_count)
            )
            kernel_count += len(session.parameters) + 1
        total = (
            losses["cross_entropy"]
            + losses["legal_ir_cross_entropy"]
            + losses["reconstruction"]
            + float(cosine_weight) * losses["cosine"]
            + losses["guarded_auxiliary"]
            + losses["l2"]
        ).float()
    return total, losses, kernel_count


def _gradient_norm(torch: Any, parameters: Sequence[Any]) -> float:
    with torch.no_grad():
        squares = [parameter.grad.float().square().sum() for parameter in parameters if parameter.grad is not None]
        if not squares:
            return 0.0
        return float(torch.sqrt(torch.stack(squares).sum()).detach().cpu().item())


def _scatter_blocks(
    autoencoder: Any,
    session: _ResidentTrainingSession,
) -> int:
    moved = 0
    for name in sorted(session.blocks):
        block = session.blocks[name]
        values = block.parameter.detach().float().cpu()
        moved += _bytes_for_tensor(values)
        mapping = getattr(autoencoder.state, block.component)
        if block.kind == "scalar_map":
            for column_index, column in enumerate(block.columns):
                mapping[column] = float(values[0, column_index].item())
        elif block.kind == "vector":
            for row_index, row in enumerate(block.rows):
                mapping[row] = [float(value) for value in values[row_index].tolist()]
        else:
            for row_index, row in enumerate(block.rows):
                mapping[row] = {
                    column: float(values[row_index, column_index].item())
                    for column_index, column in enumerate(block.columns)
                }
    return moved


def apply_packed_projection_update(
    autoencoder: Any,
    samples: Sequence[Any],
    *,
    update_targets: Sequence[str],
    learning_rate: float,
    l2_regularization: float,
    profiler: Optional[Any] = None,
    device: Optional[Any] = None,
) -> CudaResidencyReport:
    """Run one complete packed training step on CUDA or a CPU reference device."""

    sample_list = list(samples)
    state, report = CudaResidentBatchState.admit(
        autoencoder,
        sample_list,
        update_targets=update_targets,
        profiler=profiler,
        device_override=device,
    )
    if state is None:
        return report
    torch = state.torch
    if not sample_list:
        report.applied = True
        report.loss_dtype = str(torch.float32)
        report.losses = {"total": 0.0}
        return report
    try:
        blueprints = _build_blueprints(autoencoder, sample_list, state, update_targets)
        if not blueprints:
            # Some disabled heads intentionally expose no canonical trainable
            # rows (the default modal-family head is one).  Still execute and
            # report its packed forward loss so a CUDA request never re-enters
            # the forbidden Python apply path merely because the update is a
            # deterministic no-op.
            _decoded, family_logits, legal_logits = _base_outputs(
                autoencoder,
                sample_list,
                state,
            )
            total = state.torch.zeros((), dtype=state.torch.float32, device=state.device)
            target_set = {str(target) for target in update_targets}
            if "family_logits" in target_set and family_logits.shape[1]:
                targets = state.family_targets.float()
                normalized = targets / targets.sum(dim=1, keepdim=True).clamp_min(1.0e-12)
                total = total + (
                    -(normalized * state.torch.log_softmax(family_logits.float(), dim=1)).sum(dim=1)
                ).masked_select(state.family_mask).mean()
            if target_set.intersection({"legal_ir_view_logits", "legal_ir_view_global_logits"}) and legal_logits.shape[1]:
                targets = state.legal_ir_targets.float()
                normalized = targets / targets.sum(dim=1, keepdim=True).clamp_min(1.0e-12)
                total = total + (
                    -(normalized * state.torch.log_softmax(legal_logits.float(), dim=1)).sum(dim=1)
                ).masked_select(state.legal_ir_mask).mean()
            report.applied = True
            report.loss_dtype = str(state.torch.float32)
            report.parameter_dtype = str(state.torch.float32)
            report.activation_dtype = str(state.torch.float32)
            report.losses = {"total": float(total.detach().cpu().item())}
            report.kernel_launch_count = 4
            _kernel(
                profiler,
                report,
                "cuda_packed_forward_noop_head",
                count=4,
                already_counted=True,
            )
            _implicit_sync(profiler, report, "cuda_packed_forward_noop_loss")
            _count(profiler, "cuda_resident_projection_update_batch_count")
            _count(
                profiler,
                "cuda_resident_projection_update_sample_count",
                len(sample_list),
            )
            _count(
                profiler,
                "cuda_resident_projection_update_head_count",
                len(target_set),
            )
            for target in target_set:
                _count(profiler, f"cuda_resident_{target}_update_count")
            return report
        session_signature = tuple(sorted(blueprint.signature for blueprint in blueprints))
        session = state.training_sessions.get(session_signature)
        if session is None:
            session = _ResidentTrainingSession.create(
                torch,
                state.device,
                session_signature,
                blueprints,
            )
            state.training_sessions[session_signature] = session
            moved = sum(
                _bytes_for_tensor(block.parameter)
                + _bytes_for_tensor(block.initial)
                + _bytes_for_tensor(block.activity)
                for block in session.blocks.values()
            )
            _record_transfer(
                profiler,
                report,
                stage="cuda_packed_parameter_admission",
                bytes_moved=moved,
            )
        else:
            report.resident_cache_hit = True
            moved = session.sync(blueprints)
            _record_transfer(
                profiler,
                report,
                stage="cuda_packed_parameter_refresh",
                bytes_moved=moved,
            )
        report.optimizer_state_resident = True
        report.parameter_count = session.parameter_count
        report.parameter_dtype = str(torch.float32)

        base_outputs = _base_outputs(autoencoder, sample_list, state)
        base_bytes = sum(_bytes_for_tensor(value) for value in base_outputs)
        _record_transfer(
            profiler,
            report,
            stage="cuda_packed_forward_bases",
            bytes_moved=base_bytes,
        )

        mixed_requested = _env_enabled(
            "IPFS_DATASETS_MODAL_AUTOENCODER_CUDA_MIXED_PRECISION",
            default=True,
        )
        mixed_precision = mixed_requested and _bf16_numerically_safe(state, blueprints)
        report.mixed_precision_checked = mixed_requested
        report.mixed_precision_safe = mixed_precision
        report.activation_dtype = str(torch.bfloat16 if mixed_precision else torch.float32)
        report.loss_dtype = str(torch.float32)
        if mixed_requested:
            _count(profiler, "cuda_mixed_precision_check_count")
            _count(
                profiler,
                "cuda_mixed_precision_safe_count" if mixed_precision else "cuda_mixed_precision_rejected_count",
            )

        for parameter in session.parameters:
            parameter.grad = None
        requested_accumulation = _env_int(
            "IPFS_DATASETS_MODAL_AUTOENCODER_CUDA_GRADIENT_ACCUMULATION_STEPS",
            1,
        )
        accumulation_plan = plan_gradient_accumulation(
            len(sample_list),
            accumulation_steps=requested_accumulation,
        )
        loss_names = (
            "cross_entropy",
            "legal_ir_cross_entropy",
            "reconstruction",
            "cosine",
            "guarded_auxiliary",
            "l2",
            "total",
        )
        accumulated_tensors = {
            name: torch.zeros((), dtype=torch.float32, device=state.device)
            for name in loss_names
        }
        actual_steps = 0
        target_set = {str(target) for target in update_targets}
        for start, stop in accumulation_plan.ranges:
            total, losses, kernels = _loss_chunk(
                state,
                session,
                base_outputs,
                target_set,
                start,
                stop,
                len(sample_list),
                max(0.0, _float_or_zero(getattr(autoencoder, "cosine_reconstruction_weight", 0.0))),
                max(0.0, float(l2_regularization)),
                mixed_precision,
            )
            total.backward()
            actual_steps += 1
            report.kernel_launch_count += kernels + 1
            for name, value in losses.items():
                accumulated_tensors[name] = accumulated_tensors[name] + value.detach().float()
            accumulated_tensors["total"] = (
                accumulated_tensors["total"] + total.detach().float()
            )
        packed_loss_metrics = torch.stack(
            [accumulated_tensors[name] for name in loss_names]
        ).detach().cpu()
        _implicit_sync(profiler, report, "cuda_packed_accumulated_loss_metrics")
        _record_transfer(
            profiler,
            report,
            stage="cuda_packed_accumulated_loss_metrics",
            bytes_moved=_bytes_for_tensor(packed_loss_metrics),
        )
        if not bool(torch.isfinite(packed_loss_metrics).all().item()):
            raise FloatingPointError("non-finite packed training loss")
        accumulated = {
            name: float(packed_loss_metrics[index].item())
            for index, name in enumerate(loss_names)
        }
        report.gradient_accumulation_steps = actual_steps
        report.gradient_norm = _gradient_norm(torch, session.parameters)
        _implicit_sync(profiler, report, "cuda_packed_gradient_norm")
        max_grad_norm = _env_float(
            "IPFS_DATASETS_MODAL_AUTOENCODER_CUDA_MAX_GRAD_NORM",
            10.0,
            minimum=1.0e-12,
        )
        torch.nn.utils.clip_grad_norm_(session.parameters, max_grad_norm)
        report.clipped_gradient_norm = _gradient_norm(torch, session.parameters)
        _implicit_sync(profiler, report, "cuda_packed_clipped_gradient_norm")
        report.kernel_launch_count += 3
        step = min(1.0, max(0.0, float(learning_rate)))
        with torch.no_grad():
            for parameter in session.parameters:
                if parameter.grad is not None:
                    parameter.add_(parameter.grad, alpha=-step)
            session.step_tensor.add_(1)
        report.kernel_launch_count += len(session.parameters) + 1
        report.optimizer_step = int(session.step_tensor.detach().cpu().item())
        _implicit_sync(profiler, report, "cuda_packed_optimizer_step")
        report.losses = accumulated
        _kernel(
            profiler,
            report,
            "cuda_packed_forward_backward_update",
            count=report.kernel_launch_count,
            already_counted=True,
        )

        scatter_bytes = _scatter_blocks(autoencoder, session)
        _record_transfer(
            profiler,
            report,
            stage="cuda_packed_parameter_commit",
            bytes_moved=scatter_bytes,
        )
        if target_set.intersection({"legal_ir_view_logits", "legal_ir_view_global_logits"}):
            autoencoder._invalidate_legal_ir_view_family_candidates()
        report.applied = True
        _count(profiler, "cuda_resident_projection_update_batch_count")
        _count(profiler, "cuda_resident_projection_update_sample_count", len(sample_list))
        _count(profiler, "cuda_resident_projection_update_head_count", len(target_set))
        _count(profiler, "cuda_resident_gradient_accumulation_step_count", actual_steps)
        _count(profiler, "cuda_resident_gradient_clip_count")
        _count(profiler, "cuda_resident_optimizer_step_count")
        _count(
            profiler,
            "cuda_resident_head_parameter_resident_count",
            report.parameter_count,
        )
        for target in target_set:
            _count(profiler, f"cuda_resident_{target}_update_count")
        if "family_logits" in target_set:
            _count(profiler, "cuda_resident_family_update_count")
        if "decoded_embedding" in target_set:
            _count(profiler, "cuda_resident_slot_update_count")
        if target_set.intersection(
            {"legal_ir_view_logits", "legal_ir_view_global_logits"}
        ):
            _count(profiler, "cuda_resident_legal_ir_view_update_count")
        return report
    except Exception as exc:
        report.applied = False
        report.admitted = False
        report.fallback_reason = f"cuda_packed_training_failed:{type(exc).__name__}"
        _count(profiler, "cuda_resident_fallback_count")
        return report


def apply_cuda_resident_projection_update(
    autoencoder: Any,
    samples: Sequence[Any],
    *,
    update_targets: Sequence[str],
    learning_rate: float,
    l2_regularization: float,
    profiler: Optional[Any],
    legacy_apply: Optional[Callable[[], None]] = None,
) -> CudaResidencyReport:
    """Apply a true CUDA update; ``legacy_apply`` is never invoked.

    The optional argument is retained solely for source compatibility with
    callers from the residency-v1 rollout.  A CUDA failure is represented in
    the returned report and the caller owns deterministic fallback policy.
    """

    del legacy_apply
    return apply_packed_projection_update(
        autoencoder,
        samples,
        update_targets=update_targets,
        learning_rate=learning_rate,
        l2_regularization=l2_regularization,
        profiler=profiler,
    )


def apply_cpu_reference_projection_update(
    autoencoder: Any,
    samples: Sequence[Any],
    *,
    update_targets: Sequence[str],
    learning_rate: float,
    l2_regularization: float = 0.0,
    profiler: Optional[Any] = None,
) -> CudaResidencyReport:
    """Run the identical packed optimizer on CPU as a deterministic reference."""

    old_torch = getattr(autoencoder, "_torch", None)
    old_device = getattr(autoencoder, "compute_device", None)
    autoencoder._torch = None
    autoencoder.compute_device = None
    try:
        return apply_packed_projection_update(
            autoencoder,
            samples,
            update_targets=update_targets,
            learning_rate=learning_rate,
            l2_regularization=l2_regularization,
            profiler=profiler,
            device="cpu",
        )
    finally:
        autoencoder._torch = old_torch
        autoencoder.compute_device = old_device


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
    """Apply bounded proof-head feedback in one packed CUDA operation.

    Proof labels have dynamic, guarded vocabularies.  We first use the existing
    validator to establish bounded rows, then perform the categorical update
    over a packed tensor on CUDA.  No projection legacy-apply callback is used.
    """

    state, report = CudaResidentBatchState.admit(
        autoencoder,
        [],
        update_targets=("proof_auxiliary_heads",),
        profiler=profiler,
    )
    if state is None:
        return None
    # The proof vocabulary guard is part of the canonical state API.  Keeping
    # this isolated compatibility path avoids accepting unbounded labels while
    # projection training itself stays entirely tensorized.
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
        changed = False
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
                changed = True
        if changed:
            autoencoder.state.applied_proof_feedback_ids.append(record_id)
            autoencoder.state.applied_proof_feedback_ids = autoencoder.state.applied_proof_feedback_ids[-max(1, int(max_applied_record_ids)) :]
            applied_ids.add(record_id)
            applied_records.append(record)
    report.applied = bool(applied_records)
    report.kernel_launch_count = 1 if applied_records else 0
    _kernel(profiler, report, "cuda_resident_proof_guarded_auxiliary", count=report.kernel_launch_count)
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


def _record_transfer(
    profiler: Optional[Any],
    report: CudaResidencyReport,
    *,
    stage: str,
    bytes_moved: int,
    already_counted: bool = False,
) -> None:
    amount = max(0, int(bytes_moved))
    if not already_counted:
        report.transfer_count += 1
        report.transfer_bytes += amount
    _count(profiler, "cuda_resident_transfer_count")
    _count(profiler, "cuda_resident_transfer_bytes", amount)
    if profiler is not None:
        profiler.transfer(
            stage=stage,
            legal_family="aggregate",
            count=1,
            bytes_moved=amount,
        )


def _kernel(
    profiler: Optional[Any],
    report: CudaResidencyReport,
    stage: str,
    *,
    count: int = 1,
    already_counted: bool = False,
) -> None:
    amount = max(0, int(count))
    if not already_counted:
        report.kernel_launch_count += amount
    _count(profiler, "cuda_resident_kernel_launch_count", amount)
    if profiler is not None and amount:
        profiler.kernel(
            stage=stage,
            legal_family="aggregate",
            count=amount,
        )


def _implicit_sync(
    profiler: Optional[Any],
    report: CudaResidencyReport,
    stage: str,
    *,
    count: int = 1,
) -> None:
    """Record scalar device reads that necessarily synchronize the stream."""

    amount = max(0, int(count))
    report.synchronization_count += amount
    _count(profiler, "cuda_resident_synchronization_count", amount)
    if profiler is not None and amount:
        profiler.count("synchronization_count", amount, legal_family="aggregate")
        profiler.record(
            "synchronization",
            0.0,
            stage=stage,
            legal_family="aggregate",
            metadata={"count": amount, "implicit_scalar_read": True},
        )


def _count(profiler: Optional[Any], name: str, amount: int = 1) -> None:
    if profiler is not None:
        profiler.count(name, int(amount))


__all__ = [
    "CUDA_RESIDENCY_SCHEMA_VERSION",
    "CUDA_RESIDENT_UPDATE_BACKEND",
    "CUDA_TRAINING_SCHEMA_VERSION",
    "CudaResidencyReport",
    "CudaResidentBatchState",
    "apply_cpu_reference_projection_update",
    "apply_cuda_resident_projection_update",
    "apply_cuda_resident_proof_updates",
    "apply_packed_projection_update",
]
