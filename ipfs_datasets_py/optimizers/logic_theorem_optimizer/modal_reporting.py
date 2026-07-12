"""Reporting helpers for deterministic modal legal parser runs."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Optional

from .legal_samples import LegalSample
from .modal_autoencoder import AutoencoderEvaluation
from .modal_prover_router import ModalProverRouteResult


@dataclass(frozen=True)
class ModalParserReport:
    """Compact report for modal parser quality dashboards."""

    sample_count: int
    modal_family_counts: Dict[str, int]
    frame_top1_accuracy: float
    reconstruction_loss: float
    parser_failures: List[str] = field(default_factory=list)
    prover_availability: Dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "frame_top1_accuracy": self.frame_top1_accuracy,
            "modal_family_counts": dict(sorted(self.modal_family_counts.items())),
            "parser_failures": list(self.parser_failures),
            "prover_availability": dict(sorted(self.prover_availability.items())),
            "reconstruction_loss": self.reconstruction_loss,
            "sample_count": self.sample_count,
        }

    def to_markdown(self) -> str:
        """Render a short human-readable report."""
        lines = [
            "# Modal Parser Report",
            "",
            f"- Samples: {self.sample_count}",
            f"- Frame top-1 accuracy: {self.frame_top1_accuracy:.3f}",
            f"- Reconstruction loss: {self.reconstruction_loss:.6f}",
            f"- Parser failures: {len(self.parser_failures)}",
            "",
            "## Modal Families",
        ]
        for family, count in sorted(self.modal_family_counts.items()):
            lines.append(f"- {family}: {count}")
        lines.append("")
        lines.append("## Prover Availability")
        for status, count in sorted(self.prover_availability.items()):
            lines.append(f"- {status}: {count}")
        return "\n".join(lines)


@dataclass(frozen=True)
class ModalSupervisorHealthReport:
    """Compact health report for the modal autoencoder supervisor loop."""

    alive: bool
    productive: bool
    cycles: int
    active_phase: str = ""
    latest_cycle_seconds: float = 0.0
    latest_heartbeat_age_seconds: Optional[float] = None
    latest_phase_timings: Dict[str, float] = field(default_factory=dict)
    cache_counters: Dict[str, int] = field(default_factory=dict)
    state_to_compiler_patch_lag: Dict[str, int] = field(default_factory=dict)
    queue_counts: Dict[str, int] = field(default_factory=dict)
    reasons: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "active_phase": self.active_phase,
            "alive": bool(self.alive),
            "cache_counters": dict(sorted(self.cache_counters.items())),
            "cycles": int(self.cycles),
            "latest_cycle_seconds": float(self.latest_cycle_seconds),
            "latest_heartbeat_age_seconds": self.latest_heartbeat_age_seconds,
            "latest_phase_timings": dict(sorted(self.latest_phase_timings.items())),
            "productive": bool(self.productive),
            "queue_counts": dict(sorted(self.queue_counts.items())),
            "reasons": list(self.reasons),
            "state_to_compiler_patch_lag": dict(
                sorted(self.state_to_compiler_patch_lag.items())
            ),
        }


def build_modal_parser_report(
    *,
    samples: Iterable[LegalSample],
    autoencoder: AutoencoderEvaluation | None = None,
    prover_results: Iterable[ModalProverRouteResult] = (),
    expected_frames: Mapping[str, str] | None = None,
) -> ModalParserReport:
    """Build a report from sample, reconstruction, and prover outputs."""
    sample_list = list(samples)
    expected = expected_frames or {}
    family_counts: Dict[str, int] = {}
    parser_failures: List[str] = []
    top1_hits = 0
    top1_total = 0

    for sample in sample_list:
        if not sample.modal_ir.formulas:
            parser_failures.append(sample.sample_id)
        for formula in sample.modal_ir.formulas:
            family_counts[formula.operator.family] = family_counts.get(formula.operator.family, 0) + 1
        if sample.sample_id in expected:
            top1_total += 1
            if sample.selected_frame == expected[sample.sample_id]:
                top1_hits += 1

    availability: Dict[str, int] = {}
    for result in prover_results:
        status = result.status.value
        availability[status] = availability.get(status, 0) + 1

    return ModalParserReport(
        sample_count=len(sample_list),
        modal_family_counts=family_counts,
        frame_top1_accuracy=(top1_hits / top1_total) if top1_total else 0.0,
        reconstruction_loss=autoencoder.reconstruction_loss if autoencoder else 0.0,
        parser_failures=parser_failures,
        prover_availability=availability,
    )


def build_modal_supervisor_health_report(
    summary: Mapping[str, Any],
    *,
    heartbeat_age_seconds: Optional[float] = None,
) -> ModalSupervisorHealthReport:
    """Summarize whether a daemon is merely alive or producing useful work."""

    data = dict(summary or {})
    cycles = _safe_int(data.get("cycles"))
    phase = str(data.get("active_cycle_phase") or "")
    phase_timings = _float_mapping(
        data.get("latest_cycle_phase_timings")
        or data.get("active_cycle_phase_timings")
        or {}
    )
    queue_counts = _int_mapping(data.get("latest_queue_counts") or {})
    cache_counters = _cache_counters_from_summary(data)
    lag = state_to_compiler_patch_lag(data)
    reasons: List[str] = []

    alive = bool(cycles > 0 or phase or data.get("active_cycle_last_heartbeat_at"))
    if alive:
        reasons.append("heartbeat_or_completed_cycle")
    else:
        reasons.append("no_heartbeat_or_cycle")

    productive_signals = {
        "applied_todo_count": _safe_int(data.get("applied_todo_ids"))
        or _safe_int(_mapping(data.get("latest_autoencoder_state_telemetry")).get("applied_todo_count")),
        "compiler_guidance_improved_cycles": _safe_int(
            data.get("compiler_guidance_improved_cycles")
        ),
        "program_synthesis_seeded": _safe_int(data.get("program_synthesis_seeded")),
        "validation_ce_improved_cycles": _safe_int(data.get("validation_ce_improved_cycles")),
        "validation_cosine_improved_cycles": _safe_int(
            data.get("validation_cosine_improved_cycles")
        ),
    }
    productive = any(value > 0 for value in productive_signals.values())
    if productive:
        reasons.append("productive_signal")
    else:
        reasons.append("no_productive_signal")

    return ModalSupervisorHealthReport(
        alive=alive,
        productive=productive,
        cycles=cycles,
        active_phase=phase,
        latest_cycle_seconds=_safe_float(data.get("latest_cycle_seconds")),
        latest_heartbeat_age_seconds=heartbeat_age_seconds,
        latest_phase_timings=phase_timings,
        cache_counters=cache_counters,
        state_to_compiler_patch_lag=lag,
        queue_counts=queue_counts,
        reasons=reasons,
    )


def state_to_compiler_patch_lag(
    summary: Mapping[str, Any] | None = None,
    *,
    state_update_count: Optional[int] = None,
    compiler_patch_count: Optional[int] = None,
) -> Dict[str, int]:
    """Return the lag between learned-state updates and compiler patch output."""

    data = dict(summary or {})
    state_telemetry = _mapping(data.get("latest_autoencoder_state_telemetry"))
    if state_update_count is None:
        state_update_count = (
            _safe_int(state_telemetry.get("applied_todo_count"))
            + _safe_int(state_telemetry.get("generalizable_entry_count"))
        )
        if state_update_count <= 0:
            state_update_count = _safe_int(data.get("applied_todo_ids"))
    if compiler_patch_count is None:
        compiler_patch_count = max(
            _safe_int(data.get("program_synthesis_completed_count")),
            _safe_int(data.get("latest_program_synthesis_seeded_count"))
            + _safe_int(data.get("latest_compiler_ir_guidance_activation_seeded_count"))
            + _safe_int(data.get("latest_compiler_ir_guidance_distillation_seeded_count"))
            + _safe_int(data.get("latest_compiler_ir_guidance_guardrail_seeded_count")),
            _recursive_status_count(data.get("latest_role_queue_counts"), "completed"),
            _recursive_status_count(data.get("latest_queue_counts"), "completed"),
        )
    state_updates = max(0, int(state_update_count or 0))
    compiler_patches = max(0, int(compiler_patch_count or 0))
    return {
        "compiler_patch_count": compiler_patches,
        "lag": max(0, state_updates - compiler_patches),
        "state_update_count": state_updates,
    }


def _cache_counters_from_summary(summary: Mapping[str, Any]) -> Dict[str, int]:
    cache = _mapping(summary.get("cache_counters"))
    if cache:
        return _int_mapping(cache)
    compiler = _mapping(summary.get("latest_compiler_ir_validation"))
    return {
        "compiler_ir_persistent_cache_hit": int(bool(compiler.get("persistent_cache_hit"))),
        "compiler_ir_persistent_sample_cache_hits": _safe_int(
            compiler.get("persistent_sample_cache_hits")
        ),
        "compiler_ir_persistent_sample_cache_misses": _safe_int(
            compiler.get("persistent_sample_cache_misses")
        ),
    }


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _safe_float(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _int_mapping(value: Any) -> Dict[str, int]:
    return {str(key): _safe_int(raw) for key, raw in _mapping(value).items()}


def _float_mapping(value: Any) -> Dict[str, float]:
    return {str(key): _safe_float(raw) for key, raw in _mapping(value).items()}


def _recursive_status_count(value: Any, status: str) -> int:
    if isinstance(value, Mapping):
        total = 0
        for key, item in value.items():
            if str(key) == status:
                total += _safe_int(item)
            elif isinstance(item, Mapping):
                total += _recursive_status_count(item, status)
        return total
    return 0


__all__ = [
    "ModalSupervisorHealthReport",
    "ModalParserReport",
    "build_modal_supervisor_health_report",
    "build_modal_parser_report",
    "state_to_compiler_patch_lag",
]
