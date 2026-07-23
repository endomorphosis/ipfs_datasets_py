"""Measured CUDA execution for the LegalIR successive-halving scheduler.

The policy scheduler deliberately does not start processes.  This module is
the production execution boundary: it binds every candidate to one immutable
smoke-approved state, runs every candidate with the complete deterministic
seed set, and records only measured summaries.  Missing, stale, CPU-backed, or
partial seed evidence is passed to the scheduler as ineligible evidence rather
than repaired or filled with synthetic values.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import math
import os
import signal
import statistics
import subprocess
import sys
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_ir_hparam_scheduler import (
    DEFAULT_PARAM_SETS,
    DEFAULT_REQUIRED_FAMILIES,
    CompilerArtifactSet,
    FamilyGuardrailConfig,
    HParamCandidate,
    HParamSearchConfig,
    LegalIRHParamScheduler,
    SharedBaseline,
    TrialSnapshot,
    TrialWorkItem,
)


SCHEMA_VERSION = "legal-ir-hparam-execution-v2"
IMMUTABLE_BUDGET_SECONDS = 3600
DEFAULT_CANDIDATE_COUNT = 6
DEFAULT_SEEDS_PER_CANDIDATE = 3
DEFAULT_RUNG_BUDGETS = (180, 360, 1350)
TRIAL_WALL_CAP_SECONDS = 900
TRIAL_TIMEOUT_SECONDS = 1200
METRIC_NAMES = (
    "ir_cross_entropy_loss",
    "ir_cosine_similarity",
    "autoencoder_cross_entropy_loss",
    "autoencoder_cosine_similarity",
    "symbolic_validity_success_rate",
    "hammer_proof_success_rate",
    "reconstruction_success_rate",
    "round_trip_success_rate",
    "calibration_error",
    "source_copy_penalty",
)
LOWER_IS_BETTER = frozenset(
    {
        "ir_cross_entropy_loss",
        "autoencoder_cross_entropy_loss",
        "calibration_error",
        "source_copy_penalty",
    }
)
FAMILY_METRIC_NAMES = METRIC_NAMES + ("semantic_equivalence",)
REQUIRED_FAMILY_OBSERVED_METRICS = frozenset(
    {"ir_cross_entropy_loss", "ir_cosine_similarity"}
)
_STOP_REQUESTED = threading.Event()
_ACTIVE_PROCESS_GROUPS: set[int] = set()
_ACTIVE_PROCESS_GROUPS_LOCK = threading.Lock()


@dataclass(frozen=True)
class FidelityProfile:
    rung_index: int
    name: str
    validation_canary_indices: tuple[int, ...]
    train_count: int
    validation_count: int
    max_sample_text_chars: int
    max_cycles: int = 1
    wall_cap_seconds: int = TRIAL_WALL_CAP_SECONDS

    def to_dict(self) -> dict[str, Any]:
        return {
            "rung_index": self.rung_index,
            "name": self.name,
            "validation_canary_indices": list(self.validation_canary_indices),
            "validation_canary_count": len(self.validation_canary_indices),
            "train_count": self.train_count,
            "validation_count": self.validation_count,
            "max_sample_text_chars": self.max_sample_text_chars,
            "max_cycles": self.max_cycles,
            "wall_cap_seconds": self.wall_cap_seconds,
        }


def build_fidelity_profiles(
    baseline_summary: Mapping[str, Any],
    validation_canary_indices: Sequence[int],
) -> tuple[FidelityProfile, ...]:
    """Build nested, baseline-bound holdouts for the three search rungs."""

    records = _nested(
        baseline_summary,
        "latest_compiler_ir_validation",
    ).get("sample_metric_records")
    if not isinstance(records, list) or len(records) != len(validation_canary_indices):
        records = _nested(
            baseline_summary,
            "latest_rollout_baseline_snapshot",
            "compiler_ir_validation",
        ).get("sample_metric_records")
    if not isinstance(records, list) or len(records) != len(validation_canary_indices):
        raise ValueError(
            "baseline summary does not bind every validation canary to a metric record"
        )
    indexed_lengths: list[tuple[int, int]] = []
    for index, record in zip(validation_canary_indices, records, strict=True):
        length = _finite(_mapping(record).get("original_text_length"))
        if length is None or length < 1:
            raise ValueError(f"baseline canary {index} has no source-text length")
        indexed_lengths.append((int(index), int(length)))
    shortest = sorted(indexed_lengths, key=lambda item: (item[1], item[0]))
    if shortest[-1][1] > 2500:
        raise ValueError("task-117 canary exceeds the final 2500-character fidelity cap")
    one = (shortest[0][0],)
    two = tuple(index for index, _length in shortest[:2])
    return (
        FidelityProfile(
            rung_index=0,
            name="nested_shortest_1",
            validation_canary_indices=one,
            train_count=1,
            validation_count=1,
            max_sample_text_chars=max(600, shortest[0][1]),
        ),
        FidelityProfile(
            rung_index=1,
            name="nested_shortest_2",
            validation_canary_indices=two,
            train_count=2,
            validation_count=2,
            max_sample_text_chars=max(600, *(length for _index, length in shortest[:2])),
        ),
        FidelityProfile(
            rung_index=2,
            name="task_117_full_8",
            validation_canary_indices=tuple(int(index) for index in validation_canary_indices),
            train_count=4,
            validation_count=4,
            max_sample_text_chars=2500,
        ),
    )


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("ascii")


def _sha256_value(value: Any) -> str:
    return "sha256:" + hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON artifact is not an object: {path}")
    return value


def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=True, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def _finite(value: Any, default: float | None = None) -> float | None:
    if isinstance(value, bool):
        return default
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _nested(value: Mapping[str, Any], *names: str) -> Mapping[str, Any]:
    current: Mapping[str, Any] = value
    for name in names:
        current = _mapping(current.get(name))
    return current


def _metric(row: Mapping[str, Any], name: str, default: float = 0.0) -> float:
    value = _finite(row.get(name), default)
    assert value is not None
    return value


def _required_metric(
    row: Mapping[str, Any],
    name: str,
    *,
    context: str,
) -> float:
    value = _finite(row.get(name))
    if value is None:
        raise ValueError(f"missing or non-finite metric {context}.{name}")
    return value


def _family_rows(summary: Mapping[str, Any]) -> Mapping[str, Any]:
    candidates = (
        _nested(summary, "latest_legal_ir_view_family_validation", "view_family_metrics"),
        _nested(summary, "latest_learned_ir_validation", "view_family_metrics"),
        _nested(summary, "latest_compiler_ir_validation", "view_family_metrics"),
    )
    for candidate in candidates:
        if set(DEFAULT_REQUIRED_FAMILIES).issubset(candidate):
            return candidate
    return {}


def extract_summary_metrics(
    summary: Mapping[str, Any],
) -> tuple[dict[str, float], dict[str, dict[str, float]]]:
    """Extract observed metrics under one baseline/candidate policy.

    Family rows sometimes contain zero placeholders for unobserved autoencoder
    metrics.  Those placeholders are never ranked: an observed family value is
    used when present, otherwise the real global validation value is broadcast
    and the policy is recorded in the final report.  Calibration is the
    measured absolute gap between the family score and symbolic-validity rate
    until the model emits a dedicated ECE head.
    """

    rows = _family_rows(summary)
    if set(rows) != set(DEFAULT_REQUIRED_FAMILIES):
        raise ValueError("summary does not contain the exact LegalIR family set")
    validation = _mapping(summary.get("latest_autoencoder_validation"))
    global_auto_ce = _required_metric(
        validation,
        "cross_entropy_loss",
        context="latest_autoencoder_validation",
    )
    global_auto_cosine = _required_metric(
        validation,
        "cosine_similarity",
        context="latest_autoencoder_validation",
    )
    families: dict[str, dict[str, float]] = {}
    for family in DEFAULT_REQUIRED_FAMILIES:
        row = _mapping(rows.get(family))
        context = f"view_family_metrics.{family}"
        sample_count = _finite(row.get("sample_count"))
        coverage = _finite(row.get("metric_coverage"))
        observed = {
            str(name)
            for name in row.get("observed_metrics", ())
            if isinstance(name, str) and name
        }
        if sample_count is None or sample_count < 1:
            raise ValueError(f"missing sample coverage for {context}")
        if coverage is None or coverage <= 0:
            raise ValueError(f"missing metric coverage for {context}")
        if not REQUIRED_FAMILY_OBSERVED_METRICS.issubset(observed):
            raise ValueError(f"IR metrics were not observed for {context}")
        ir_ce = _required_metric(row, "ir_cross_entropy_loss", context=context)
        ir_cosine = _required_metric(row, "ir_cosine_similarity", context=context)
        reconstruction = _required_metric(
            row,
            "reconstruction_success_rate",
            context=context,
        )
        symbolic = _required_metric(
            row,
            "symbolic_validity_success_rate",
            context=context,
        )
        proof = _required_metric(row, "hammer_proof_success_rate", context=context)
        score = _required_metric(row, "score", context=context)
        source_copy_values = [
            value
            for value in (
                _finite(row.get("source_copy_penalty")),
                _finite(row.get("source_copy_reward_hack_penalty")),
            )
            if value is not None
        ]
        if not source_copy_values:
            raise ValueError(f"missing source-copy metric for {context}")
        family_auto_observed = {
            "autoencoder_cross_entropy_loss",
            "autoencoder_cosine_similarity",
        }.issubset(observed)
        auto_ce = (
            _required_metric(
                row,
                "autoencoder_cross_entropy_loss",
                context=context,
            )
            if family_auto_observed
            else global_auto_ce
        )
        auto_cosine = (
            _required_metric(
                row,
                "autoencoder_cosine_similarity",
                context=context,
            )
            if family_auto_observed
            else global_auto_cosine
        )
        families[family] = {
            "ir_cross_entropy_loss": ir_ce,
            "ir_cosine_similarity": ir_cosine,
            "autoencoder_cross_entropy_loss": auto_ce,
            "autoencoder_cosine_similarity": auto_cosine,
            "semantic_equivalence": max(0.0, min(1.0, symbolic)),
            "symbolic_validity_success_rate": symbolic,
            "hammer_proof_success_rate": proof,
            "reconstruction_success_rate": reconstruction,
            "round_trip_success_rate": reconstruction,
            "calibration_error": abs(score - symbolic),
            "source_copy_penalty": max(source_copy_values),
        }

    def macro(name: str) -> float:
        return statistics.fmean(families[family][name] for family in families)

    learned = _mapping(summary.get("latest_learned_ir_validation"))
    learned_ce = _finite(learned.get("view_cross_entropy_loss"))
    learned_cos = _finite(learned.get("view_cosine_similarity"))
    if learned_ce is None:
        learned_ce = _finite(summary.get("best_validation_learned_ir_view_ce"))
    if learned_cos is None:
        learned_cos = _finite(summary.get("best_validation_learned_ir_view_cosine"))
    if learned_ce is None or learned_cos is None:
        raise ValueError("learned IR global metrics are absent")
    metrics = {
        "ir_cross_entropy_loss": learned_ce,
        "ir_cosine_similarity": learned_cos,
        "autoencoder_cross_entropy_loss": global_auto_ce,
        "autoencoder_cosine_similarity": global_auto_cosine,
        "symbolic_validity_success_rate": macro(
            "symbolic_validity_success_rate"
        ),
        "hammer_proof_success_rate": macro("hammer_proof_success_rate"),
        "reconstruction_success_rate": macro("reconstruction_success_rate"),
        "round_trip_success_rate": macro("round_trip_success_rate"),
        "calibration_error": macro("calibration_error"),
        "source_copy_penalty": macro("source_copy_penalty"),
    }
    return metrics, families


def _confidence_interval(values: Sequence[float]) -> tuple[float, float, float]:
    """Return mean and a conservative 95% Student-t interval."""

    if not values:
        raise ValueError("confidence interval requires observations")
    mean = statistics.fmean(values)
    if len(values) == 1:
        return mean, mean, mean
    # t(0.975, 2)=4.303 is conservative for the required three seeds and also
    # remains conservative if an operator requests more seeds.
    margin = 4.303 * statistics.stdev(values) / math.sqrt(len(values))
    return mean, mean - margin, mean + margin


def _aggregate_seed_metrics(
    seed_metrics: Sequence[Mapping[str, float]],
    baseline_metrics: Mapping[str, float],
) -> tuple[dict[str, float], dict[str, dict[str, float]]]:
    aggregate: dict[str, float] = {}
    confidence: dict[str, dict[str, float]] = {}
    for name in METRIC_NAMES:
        values = [float(item[name]) for item in seed_metrics]
        mean, lower, upper = _confidence_interval(values)
        aggregate[name] = mean
        confidence[name] = {
            "confidence_level": 0.95,
            "baseline_lower_bound": float(baseline_metrics[name]),
            "baseline_upper_bound": float(baseline_metrics[name]),
            "candidate_lower_bound": lower,
            "candidate_upper_bound": upper,
            "mean": mean,
            "sample_count": float(len(values)),
        }
    return aggregate, confidence


def _aggregate_family_metrics(
    seed_families: Sequence[Mapping[str, Mapping[str, float]]],
    baseline_families: Mapping[str, Mapping[str, float]],
) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for family in DEFAULT_REQUIRED_FAMILIES:
        candidate = {
            name: statistics.fmean(
                float(seed[family][name]) for seed in seed_families
            )
            for name in FAMILY_METRIC_NAMES
        }
        result[family] = {
            "baseline": dict(baseline_families[family]),
            "candidate": candidate,
            "confidence": 0.95,
            "sample_confidence": 0.95,
            "confidence_lower_bound": 0.95,
            "seed_count": len(seed_families),
        }
    return result


def _compiler_artifact_set(
    *,
    evidence: Mapping[str, Any],
    baseline_summary: Path,
    baseline_state: Path,
) -> CompilerArtifactSet:
    lineage = _mapping(evidence.get("lineage"))
    return CompilerArtifactSet(
        compiler_revision=str(lineage.get("code_revision") or ""),
        compiler_config_digest=str(lineage.get("configuration_sha256") or ""),
        dataset_digest=str(lineage.get("fixture_sha256") or ""),
        artifacts={
            "baseline_evidence": str(evidence.get("manifest_sha256") or ""),
            "baseline_summary": _sha256_file(baseline_summary),
            "baseline_state": _sha256_file(baseline_state),
        },
        deterministic=True,
        complete=True,
    )


def verify_baseline_receipt(
    *,
    evidence: Mapping[str, Any],
    baseline_summary: Path,
    baseline_state: Path,
) -> tuple[int, ...]:
    """Bind execution to the accepted task-117 bytes and fixed holdout rows."""

    if evidence.get("stage") != "ten_minute_smoke" or evidence.get("decision") != "passed":
        raise ValueError("task-117 baseline evidence is not an accepted smoke")
    receipt_body = dict(evidence)
    claimed_manifest = str(receipt_body.pop("manifest_sha256", ""))
    calculated_manifest = "sha256:" + hashlib.sha256(
        json.dumps(
            receipt_body,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest()
    if claimed_manifest != calculated_manifest:
        raise ValueError("task-117 evidence manifest digest mismatch")
    artifacts = _mapping(evidence.get("artifacts"))
    summary_artifact = _mapping(artifacts.get("autoencoder_summary"))
    state_artifact = _mapping(artifacts.get("checkpoint"))
    summary_sha = _sha256_file(baseline_summary)
    state_sha = _sha256_file(baseline_state)
    lineage = _mapping(evidence.get("lineage"))
    if summary_artifact.get("sha256") != summary_sha:
        raise ValueError("baseline summary does not match task-117 evidence")
    if (
        state_artifact.get("sha256") != state_sha
        or lineage.get("final_state_sha256") != state_sha
    ):
        raise ValueError("baseline state does not match task-117 evidence")
    summary = _load_json(baseline_summary)
    expected_summary_run_id = f"{evidence.get('run_id')}-autoencoder"
    if (
        summary.get("final") is not True
        or summary.get("run_id") != expected_summary_run_id
    ):
        raise ValueError("baseline summary identity or completion marker is invalid")
    raw_indices = summary.get("validation_canary_indices")
    if not isinstance(raw_indices, list):
        raise ValueError("baseline summary has no fixed validation canary indices")
    try:
        indices = tuple(int(item) for item in raw_indices)
    except (TypeError, ValueError) as exc:
        raise ValueError("baseline validation canary indices are invalid") from exc
    selected = _mapping(evidence.get("selected_configuration"))
    expected_count = int(selected.get("validation_canary_count", 0) or 0)
    if (
        expected_count < 1
        or len(indices) != expected_count
        or len(indices) != len(set(indices))
        or any(index < 0 for index in indices)
    ):
        raise ValueError("baseline validation canary set is incomplete or inconsistent")
    extract_summary_metrics(summary)
    return indices


def build_scheduler_from_baseline(
    *,
    evidence: Mapping[str, Any],
    baseline_summary: Path,
    baseline_state: Path,
    candidate_count: int = DEFAULT_CANDIDATE_COUNT,
    seeds_per_candidate: int = DEFAULT_SEEDS_PER_CANDIDATE,
    max_concurrent_trainers: int = 2,
) -> tuple[LegalIRHParamScheduler, dict[str, Any]]:
    summary = _load_json(baseline_summary)
    baseline_metrics, baseline_families = extract_summary_metrics(summary)
    lineage = _mapping(evidence.get("lineage"))
    baseline = SharedBaseline(
        baseline_id=str(lineage.get("baseline_state_id") or "task-117-baseline"),
        revision=str(lineage.get("final_state_revision") or ""),
        dataset_digest=str(lineage.get("fixture_sha256") or ""),
        metric_lineage_id="legal-ir-tensorized-objective-v3-measured-multiseed",
        metrics=baseline_metrics,
        family_metrics=baseline_families,
        compiler_artifact_set=_compiler_artifact_set(
            evidence=evidence,
            baseline_summary=baseline_summary,
            baseline_state=baseline_state,
        ),
    )
    config = HParamSearchConfig(
        baseline=baseline,
        total_budget_seconds=IMMUTABLE_BUDGET_SECONDS,
        initial_candidate_count=candidate_count,
        rung_budgets_seconds=DEFAULT_RUNG_BUDGETS,
        reduction_factor=2,
        base_seed=8675309,
        max_concurrent_evaluations=4,
        max_concurrent_trainers=max_concurrent_trainers,
        allow_concurrent_trainers=max_concurrent_trainers > 1,
        seeds_per_candidate=seeds_per_candidate,
        require_multi_seed_evidence=True,
        require_cuda_evidence=True,
        require_compiler_artifact_set=True,
        require_complete_parallel_lanes=True,
        require_tensorized_objective=True,
        max_evidence_age_seconds=12 * 60 * 60,
        require_measured_second_trainer_pressure=True,
        guardrails=FamilyGuardrailConfig(
            required_families=DEFAULT_REQUIRED_FAMILIES,
            min_confidence=0.80,
            require_paired_metrics=True,
        ),
    )
    return LegalIRHParamScheduler(
        config,
        candidates=DEFAULT_PARAM_SETS[:candidate_count],
    ), {
        "metrics": baseline_metrics,
        "family_metrics": baseline_families,
        "summary_sha256": _sha256_file(baseline_summary),
        "state_sha256": _sha256_file(baseline_state),
        "evidence_manifest_sha256": evidence.get("manifest_sha256"),
    }


def _memory_pressure() -> tuple[float, int]:
    values: dict[str, int] = {}
    for line in Path("/proc/meminfo").read_text(encoding="ascii").splitlines():
        name, _, raw = line.partition(":")
        if name in {"MemTotal", "MemAvailable"}:
            values[name] = int(raw.strip().split()[0]) * 1024
    total = values.get("MemTotal", 0)
    available = values.get("MemAvailable", 0)
    if total <= 0:
        return 1.0, 0
    return max(0.0, min(1.0, 1.0 - available / total)), available


def measured_trainer_limit(requested: int) -> tuple[int, dict[str, Any]]:
    pressure, available = _memory_pressure()
    cuda_ok = False
    cuda_name = ""
    try:
        import torch

        cuda_ok = bool(torch.cuda.is_available())
        if cuda_ok:
            cuda_name = str(torch.cuda.get_device_name(0))
            probe = torch.ones(1, device="cuda")
            torch.cuda.synchronize()
            if float(probe.item()) != 1.0:
                cuda_ok = False
    except Exception:
        cuda_ok = False
    if not cuda_ok:
        raise RuntimeError("CUDA preflight failed; CPU fallback is forbidden")
    # The GB10 reports unified memory rather than a useful dedicated-memory
    # counter.  Admit trainer two only with at least 32 GiB available and host
    # pressure no greater than the scheduler's 0.65 policy threshold.
    admitted = 2 if requested >= 2 and available >= 32 * 1024**3 and pressure <= 0.65 else 1
    return admitted, {
        "measured_at_epoch": time.time(),
        "telemetry_known": True,
        "cuda_available": True,
        "cuda_device_name": cuda_name,
        "host_memory_pressure": pressure,
        "host_memory_available_bytes": available,
        "requested_trainers": requested,
        "admitted_trainers": admitted,
        "second_trainer_policy": {
            "maximum_host_memory_pressure": 0.65,
            "minimum_available_unified_memory_bytes": 32 * 1024**3,
        },
    }


@dataclass(frozen=True)
class SeedRun:
    candidate_id: str
    rung_index: int
    seed: int
    run_id: str
    requested_seconds: int
    returncode: int
    elapsed_wall_seconds: float
    summary_path: Path
    state_path: Path
    stdout_path: Path
    stderr_path: Path
    summary: Mapping[str, Any]
    expected_validation_canary_indices: tuple[int, ...]
    fidelity_profile: FidelityProfile
    error: str = ""

    @property
    def metric_evidence_complete(self) -> bool:
        try:
            extract_rollout_baseline_metrics(self.summary)
            extract_summary_metrics(self.summary)
        except ValueError:
            return False
        return True

    @property
    def succeeded(self) -> bool:
        return (
            self.returncode == 0
            and not self.error
            and self.summary.get("final") is True
            and self.summary.get("run_id") == self.run_id
            and self.summary.get("autoencoder_compute_backend") == "torch_cuda"
            and self.summary.get("autoencoder_compute_device_request") == "cuda"
            and self.summary.get("autoencoder_cuda_residency_applied") == "true"
            and int(self.summary.get("cycles", 0) or 0) == self.fidelity_profile.max_cycles
            and int(self.summary.get("max_cycles", 0) or 0)
            == self.fidelity_profile.max_cycles
            and tuple(self.summary.get("validation_canary_indices", ()))
            == self.expected_validation_canary_indices
            and int(self.summary.get("validation_canary_count", 0) or 0)
            == len(self.expected_validation_canary_indices)
            and self.summary.get("validation_canary_indices_source")
            == "operator_pinned"
            and int(self.summary.get("max_sample_text_chars", 0) or 0)
            == self.fidelity_profile.max_sample_text_chars
            and self.active_seconds > 0
            and self.metric_evidence_complete
            and self.state_path.is_file()
        )

    @property
    def active_seconds(self) -> float:
        value = _finite(self.summary.get("latest_cycle_seconds"), 0.0)
        return max(0.0, float(value or 0.0))

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "rung_index": self.rung_index,
            "seed": self.seed,
            "run_id": self.run_id,
            "requested_seconds": self.requested_seconds,
            "returncode": self.returncode,
            "elapsed_wall_seconds": self.elapsed_wall_seconds,
            "active_seconds": self.active_seconds,
            "active_seconds_source": "latest_cycle_seconds",
            "metric_evidence_complete": self.metric_evidence_complete,
            "succeeded": self.succeeded,
            "error": self.error or None,
            "cycles": int(self.summary.get("cycles", 0) or 0),
            "compute_backend": self.summary.get("autoencoder_compute_backend"),
            "fidelity_profile": self.fidelity_profile.to_dict(),
            "summary_path": str(self.summary_path),
            "summary_sha256": (
                _sha256_file(self.summary_path) if self.summary_path.is_file() else None
            ),
            "state_path": str(self.state_path),
            "state_sha256": (
                _sha256_file(self.state_path) if self.state_path.is_file() else None
            ),
            "stdout_path": str(self.stdout_path),
            "stderr_path": str(self.stderr_path),
        }


def _trial_command(
    *,
    python: Path,
    run_id: str,
    seed: int,
    params: Mapping[str, float],
    warm_state: Path,
    fidelity_profile: FidelityProfile,
) -> list[str]:
    validation_canary_indices = fidelity_profile.validation_canary_indices
    return [
        str(python),
        "-m",
        "ipfs_datasets_py.optimizers.logic_theorem_optimizer.uscode_modal_daemon_runner",
        "--loop-role",
        "autoencoder",
        "--run-id",
        run_id,
        "--duration-seconds",
        str(fidelity_profile.wall_cap_seconds),
        "--max-cycles",
        str(fidelity_profile.max_cycles),
        "--train-count",
        str(fidelity_profile.train_count),
        "--validation-count",
        str(fidelity_profile.validation_count),
        "--validation-canary-count",
        str(len(validation_canary_indices)),
        "--validation-canary-indices",
        ",".join(str(index) for index in validation_canary_indices),
        "--max-sample-text-chars",
        str(fidelity_profile.max_sample_text_chars),
        "--compiler-ir-metric-max-sample-text-chars",
        "600",
        "--compiler-ir-metric-sample-timeout-seconds",
        "30",
        "--max-inner-iterations",
        "1",
        "--max-items",
        "4",
        "--sampling-seed",
        str(seed),
        "--learning-rate",
        str(params["lr"]),
        "--generalizable-projection-objective-cross-entropy-weight",
        str(params["ce"]),
        "--generalizable-projection-objective-reconstruction-weight",
        str(params["rec"]),
        "--generalizable-projection-objective-cosine-gap-weight",
        str(params["cos"]),
        "--generalizable-projection-objective-legal-ir-weight",
        str(params["legal"]),
        "--generalizable-projection-hard-example-fraction",
        str(params["hard"]),
        "--autoencoder-feature-family-logit-scale",
        str(params["fam"]),
        "--autoencoder-feature-embedding-weight-scale",
        str(params["emb"]),
        "--generalizable-projection-epochs",
        "1",
        "--generalizable-projection-timeout-seconds",
        "90",
        "--generalizable-projection-max-line-search-attempts",
        "1",
        "--generalizable-projection-max-update-families",
        "1",
        "--autoencoder-projection-deadband-mode",
        "enforce",
        "--autoencoder-max-ce-deadband",
        "0.0001",
        "--test-every-cycles",
        "0",
        "--autoencoder-device",
        "cuda",
        "--autoencoder-bridge-workers",
        "2",
        "--autoencoder-metric-bridge-adapters",
        "modal_frame_logic,deontic_norms,fol_tdfol,cec_dcec,external_prover_router",
        "--bridge-loss-adapters",
        "modal_frame_logic,deontic_norms",
        "--bridge-evaluate-provers",
        "false",
        "--autoencoder-introspection-mode",
        "seed",
        "--autoencoder-introspection-every-n-cycles",
        "1",
        "--autoencoder-max-audits-per-cycle",
        "2",
        "--daemon-hammer-guidance-enabled",
        "true",
        "--daemon-hammer-guidance-cache-enabled",
        "true",
        "--daemon-hammer-guidance-max-samples-per-cycle",
        "1",
        "--daemon-hammer-guidance-max-obligations-per-sample",
        "4",
        "--daemon-hammer-guidance-max-premises",
        "32",
        "--daemon-hammer-guidance-timeout-seconds",
        "3",
        "--daemon-hammer-guidance-parallel-workers",
        "2",
        "--daemon-hammer-guidance-verify-reconstruction",
        "true",
        "--daemon-hammer-guidance-trusted-requires-reconstruction",
        "true",
        "--async-artifact-full-checkpoint-every-n-cycles",
        "2",
        "--warm-start-state",
        str(warm_state),
    ]


def _register_process_group(process_group_id: int) -> None:
    with _ACTIVE_PROCESS_GROUPS_LOCK:
        _ACTIVE_PROCESS_GROUPS.add(process_group_id)


def _unregister_process_group(process_group_id: int) -> None:
    with _ACTIVE_PROCESS_GROUPS_LOCK:
        _ACTIVE_PROCESS_GROUPS.discard(process_group_id)


def _signal_process_groups(signum: int) -> None:
    with _ACTIVE_PROCESS_GROUPS_LOCK:
        process_group_ids = tuple(_ACTIVE_PROCESS_GROUPS)
    for process_group_id in process_group_ids:
        try:
            os.killpg(process_group_id, signum)
        except ProcessLookupError:
            _unregister_process_group(process_group_id)


def _terminate_process_group(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait(timeout=10)


def _execute_seed(
    *,
    repo_root: Path,
    python: Path,
    work_root: Path,
    base_run_id: str,
    item: TrialWorkItem,
    seed: int,
    warm_state: Path,
    fidelity_profile: FidelityProfile,
) -> SeedRun:
    seconds = max(1, math.ceil(item.additional_budget_seconds / len(item.candidate.seeds)))
    run_id = (
        f"{base_run_id}-{item.candidate.candidate_id}-"
        f"r{item.rung.index:02d}-s{seed}"
    )
    summary_path = repo_root / "workspace/test-logs" / f"{run_id}.summary"
    state_path = repo_root / "workspace/todo-queues" / f"{run_id}.state.json"
    stdout_path = work_root / f"{run_id}.stdout.log"
    stderr_path = work_root / f"{run_id}.stderr.log"
    if summary_path.exists() or state_path.exists():
        raise FileExistsError(f"refusing to reuse trial lineage: {run_id}")
    command = _trial_command(
        python=python,
        run_id=run_id,
        seed=seed,
        params=item.candidate.param_dict(),
        warm_state=warm_state,
        fidelity_profile=fidelity_profile,
    )
    started = time.monotonic()
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(
        filter(None, (str(repo_root), str(repo_root.parent / "ipfs_accelerate_py"), env.get("PYTHONPATH", "")))
    )
    returncode = 125
    error = ""
    try:
        if _STOP_REQUESTED.is_set():
            raise InterruptedError("search stop requested before seed launch")
        with stdout_path.open("wb") as stdout, stderr_path.open("wb") as stderr:
            process = subprocess.Popen(
                command,
                cwd=repo_root,
                env=env,
                stdout=stdout,
                stderr=stderr,
                start_new_session=True,
            )
            _register_process_group(process.pid)
            try:
                returncode = process.wait(timeout=TRIAL_TIMEOUT_SECONDS)
            except subprocess.TimeoutExpired:
                _terminate_process_group(process)
                raise
            finally:
                _unregister_process_group(process.pid)
    except subprocess.TimeoutExpired:
        returncode = 124
        error = f"timeout:{TRIAL_TIMEOUT_SECONDS}"
    except Exception as exc:  # preserve a fail-closed seed receipt
        error = f"{type(exc).__name__}:{exc}"
    try:
        summary = _load_json(summary_path) if summary_path.is_file() else {}
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        summary = {}
        error = error or f"summary:{type(exc).__name__}:{exc}"
    return SeedRun(
        candidate_id=item.candidate.candidate_id,
        rung_index=item.rung.index,
        seed=seed,
        run_id=run_id,
        requested_seconds=seconds,
        returncode=returncode,
        elapsed_wall_seconds=time.monotonic() - started,
        summary_path=summary_path,
        state_path=state_path,
        stdout_path=stdout_path,
        stderr_path=stderr_path,
        summary=summary,
        expected_validation_canary_indices=fidelity_profile.validation_canary_indices,
        fidelity_profile=fidelity_profile,
        error=error,
    )


def extract_rollout_baseline_metrics(
    summary: Mapping[str, Any],
) -> tuple[dict[str, float], dict[str, dict[str, float]]]:
    """Extract the pre-update metrics captured inside a completed cycle."""

    snapshot = _mapping(summary.get("latest_rollout_baseline_snapshot"))
    if not snapshot:
        raise ValueError("summary has no rollout baseline snapshot")
    normalized = {
        "latest_autoencoder_validation": snapshot.get("validation"),
        "latest_learned_ir_validation": snapshot.get("learned_ir_view_validation"),
        "latest_legal_ir_view_family_validation": snapshot.get(
            "legal_ir_view_family_validation"
        ),
    }
    return extract_summary_metrics(normalized)


def _bounded_estimate(name: str, value: float) -> float:
    if name in {
        "autoencoder_cosine_similarity",
        "ir_cosine_similarity",
    }:
        return max(-1.0, min(1.0, value))
    if name in {
        "semantic_equivalence",
        "symbolic_validity_success_rate",
        "hammer_proof_success_rate",
        "reconstruction_success_rate",
        "round_trip_success_rate",
        "calibration_error",
        "source_copy_penalty",
    }:
        return max(0.0, min(1.0, value))
    return max(0.0, value)


def _paired_delta_estimate(
    *,
    runs: Sequence[SeedRun],
    baseline_metrics: Mapping[str, float],
    baseline_families: Mapping[str, Mapping[str, float]],
) -> tuple[dict[str, float], dict[str, dict[str, float]]]:
    """Anchor measured within-run deltas to the task-117 full baseline."""

    metrics = {name: float(baseline_metrics[name]) for name in METRIC_NAMES}
    families = {
        family: {
            name: float(baseline_families[family][name])
            for name in FAMILY_METRIC_NAMES
        }
        for family in DEFAULT_REQUIRED_FAMILIES
    }
    for run in sorted(runs, key=lambda item: item.rung_index):
        before_metrics, before_families = extract_rollout_baseline_metrics(run.summary)
        after_metrics, after_families = extract_summary_metrics(run.summary)
        for name in METRIC_NAMES:
            metrics[name] += after_metrics[name] - before_metrics[name]
        for family in DEFAULT_REQUIRED_FAMILIES:
            for name in FAMILY_METRIC_NAMES:
                families[family][name] += (
                    after_families[family][name] - before_families[family][name]
                )
    return (
        {name: _bounded_estimate(name, value) for name, value in metrics.items()},
        {
            family: {
                name: _bounded_estimate(name, value)
                for name, value in values.items()
            }
            for family, values in families.items()
        },
    )


def _snapshot_from_runs(
    *,
    scheduler: LegalIRHParamScheduler,
    item: TrialWorkItem,
    runs: Sequence[SeedRun],
    prior_runs: Sequence[SeedRun],
    baseline_metrics: Mapping[str, float],
    baseline_families: Mapping[str, Mapping[str, float]],
    final_rung_index: int,
) -> TrialSnapshot:
    complete = len(runs) == len(item.candidate.seeds) and all(run.succeeded for run in runs)
    all_runs = [*prior_runs, *runs]
    elapsed = sum(run.active_seconds for run in all_runs)
    seed_metrics: list[Mapping[str, float]] = []
    seed_families: list[Mapping[str, Mapping[str, float]]] = []
    for run in runs:
        if not run.succeeded:
            continue
        try:
            if item.rung.index == final_rung_index:
                metrics, families = extract_summary_metrics(run.summary)
            else:
                metrics, families = _paired_delta_estimate(
                    runs=[
                        *(
                            prior
                            for prior in prior_runs
                            if prior.seed == run.seed and prior.succeeded
                        ),
                        run,
                    ],
                    baseline_metrics=baseline_metrics,
                    baseline_families=baseline_families,
                )
        except ValueError:
            continue
        if set(metrics) == set(METRIC_NAMES) and set(families) == set(DEFAULT_REQUIRED_FAMILIES):
            seed_metrics.append(metrics)
            seed_families.append(families)
    if len(seed_metrics) == len(item.candidate.seeds):
        metrics, confidence = _aggregate_seed_metrics(seed_metrics, baseline_metrics)
        families = _aggregate_family_metrics(
            seed_families,
            baseline_families,
        )
    else:
        metrics, confidence, families = {}, {}, {}
    return TrialSnapshot(
        candidate_id=item.candidate.candidate_id,
        rung_index=item.rung.index,
        budget_seconds=item.rung.budget_seconds,
        elapsed_seconds=elapsed,
        status="succeeded" if complete else "failed",
        snapshot_complete=complete,
        baseline_digest=scheduler.config.baseline.digest,
        lineage_digest=scheduler.config.baseline.lineage_digest,
        metrics=metrics,
        family_metrics=families,
        snapshot_id=f"{item.run_id_suffix}-snapshot",
        compiler_artifact_set_digest=scheduler.config.baseline.compiler_artifact_set_digest,
        seed_ids=tuple(run.seed for run in runs if run.succeeded),
        multi_seed_evidence_complete=complete,
        compute_backend="torch_cuda" if complete else "",
        cpu_fallback_used=any(
            run.summary.get("autoencoder_compute_backend") != "torch_cuda"
            for run in runs
        ),
        state_revision=scheduler.config.baseline.revision,
        evidence_created_at_epoch=time.time(),
        stale=False,
        evaluation_lane_complete=complete and all(
            bool(_family_rows(run.summary)) for run in runs
        ),
        proof_lane_complete=complete and all(
            bool(
                _mapping(
                    _mapping(
                        run.summary.get("latest_daemon_hammer_guidance")
                        or run.summary.get("active_cycle_hammer_guidance")
                    ).get("hammer_metrics")
                )
            )
            for run in runs
        ),
        metric_confidence=confidence,
    )


def execute_search(
    *,
    repo_root: Path,
    python: Path,
    run_id: str,
    baseline_evidence: Path,
    baseline_summary: Path,
    baseline_state: Path,
    output: Path,
    work_root: Path,
    candidate_count: int,
    seeds_per_candidate: int,
    requested_trainers: int,
) -> dict[str, Any]:
    if output.exists() or work_root.exists():
        raise FileExistsError("refusing to reuse hparam output or work directory")
    evidence = _load_json(baseline_evidence)
    for path in (baseline_summary, baseline_state):
        if not path.is_file():
            raise FileNotFoundError(path)
    validation_canary_indices = verify_baseline_receipt(
        evidence=evidence,
        baseline_summary=baseline_summary,
        baseline_state=baseline_state,
    )
    baseline_summary_payload = _load_json(baseline_summary)
    fidelity_profiles = build_fidelity_profiles(
        baseline_summary_payload,
        validation_canary_indices,
    )
    if tuple(profile.rung_index for profile in fidelity_profiles) != tuple(
        range(len(DEFAULT_RUNG_BUDGETS))
    ):
        raise ValueError("fidelity profile ladder does not match the scheduler rungs")
    scheduler, baseline_record = build_scheduler_from_baseline(
        evidence=evidence,
        baseline_summary=baseline_summary,
        baseline_state=baseline_state,
        candidate_count=candidate_count,
        seeds_per_candidate=seeds_per_candidate,
        max_concurrent_trainers=requested_trainers,
    )
    trainer_limit, pressure = measured_trainer_limit(requested_trainers)
    work_root.mkdir(parents=True)
    started_at = time.time()
    run_records: list[dict[str, Any]] = []
    histories: dict[tuple[str, int], list[SeedRun]] = {}
    latest_state: dict[tuple[str, int], Path] = {}

    while scheduler.current_rung_index() is not None:
        if _STOP_REQUESTED.is_set():
            raise InterruptedError("search stop requested")
        ready = scheduler.ready_work()
        if not ready:
            break
        rung_index = ready[0].rung.index
        if any(item.rung.index != rung_index for item in ready):
            raise RuntimeError("scheduler returned work from multiple rungs")
        fidelity_profile = fidelity_profiles[rung_index]
        futures: dict[Future[SeedRun], tuple[TrialWorkItem, int]] = {}
        completed_by_candidate: dict[str, list[SeedRun]] = {
            item.candidate.candidate_id: [] for item in ready
        }
        with ThreadPoolExecutor(
            max_workers=trainer_limit,
            thread_name_prefix="legal-ir-hparam-trainer",
        ) as pool:
            for item in ready:
                for seed in item.candidate.seeds:
                    warm_state = latest_state.get(
                        (item.candidate.candidate_id, seed),
                        baseline_state,
                    )
                    future = pool.submit(
                        _execute_seed,
                        repo_root=repo_root,
                        python=python,
                        work_root=work_root,
                        base_run_id=run_id,
                        item=item,
                        seed=seed,
                        warm_state=warm_state,
                        fidelity_profile=fidelity_profile,
                    )
                    futures[future] = (item, seed)
            for future in as_completed(futures):
                item, seed = futures[future]
                run = future.result()
                completed_by_candidate[item.candidate.candidate_id].append(run)
                run_records.append(run.to_dict())
                if run.succeeded:
                    latest_state[(item.candidate.candidate_id, seed)] = run.state_path

        if _STOP_REQUESTED.is_set():
            raise InterruptedError("search stop requested")

        for item in ready:
            candidate_id = item.candidate.candidate_id
            current_runs = sorted(
                completed_by_candidate[candidate_id],
                key=lambda run: run.seed,
            )
            prior_runs = [
                run
                for (history_candidate, _), history in histories.items()
                if history_candidate == candidate_id
                for run in history
            ]
            snapshot = _snapshot_from_runs(
                scheduler=scheduler,
                item=item,
                runs=current_runs,
                prior_runs=prior_runs,
                baseline_metrics=baseline_record["metrics"],
                baseline_families=baseline_record["family_metrics"],
                final_rung_index=len(fidelity_profiles) - 1,
            )
            scheduler.record_result(snapshot)
            histories[(candidate_id, item.rung.index)] = current_runs

    scheduler_report = scheduler.report_dict()
    selected = scheduler.selected_candidate()
    selected_states = (
        {
            str(seed): str(latest_state[(selected.candidate_id, seed)])
            for seed in selected.seeds
        }
        if selected is not None
        else {}
    )
    report: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "started_at_epoch": started_at,
        "finished_at_epoch": time.time(),
        "wall_seconds": time.time() - started_at,
        "requested_budget_seconds": IMMUTABLE_BUDGET_SECONDS,
        "requested_resource_seconds_executed": sum(
            int(item["requested_seconds"]) for item in run_records
        ),
        "measured_active_seconds_executed": sum(
            float(item["active_seconds"]) for item in run_records
        ),
        "search_plan": scheduler.plan_dict(),
        "baseline": baseline_record,
        "baseline_evidence_path": str(baseline_evidence),
        "baseline_summary_path": str(baseline_summary),
        "baseline_state_path": str(baseline_state),
        "resource_admission": pressure,
        "trainer_limit": trainer_limit,
        "fidelity_profiles": [profile.to_dict() for profile in fidelity_profiles],
        "validation_canary_indices": list(validation_canary_indices),
        "validation_canary_indices_sha256": _sha256_value(
            list(validation_canary_indices)
        ),
        "run_records": sorted(
            run_records,
            key=lambda item: (item["rung_index"], item["candidate_id"], item["seed"]),
        ),
        "scheduler_report": scheduler_report,
        "search_complete": scheduler_report["search_complete"],
        "promotion_eligible": scheduler_report["promotion_eligible"],
        "selected_candidate": (
            None if selected is None else selected.to_dict()
        ),
        "selected_seed_states": selected_states,
        "metric_extraction_policy": {
            "ir_metrics": "learned_ir_view_with_family_macro_fallback",
            "family_autoencoder_metrics": (
                "observed_family_value_else_global_validation_broadcast"
            ),
            "calibration_error": (
                "absolute_family_score_minus_symbolic_validity_proxy_until_ece_head_exists"
            ),
            "round_trip_success_rate": "family_reconstruction_success_rate",
            "confidence": "three_seed_student_t_95_percent",
            "early_rung_comparison": (
                "task_117_baseline_plus_cumulative_paired_before_after_deltas"
            ),
            "final_rung_comparison": "absolute_task_117_full_8_canary_metrics",
            "resource_accounting": (
                "latest_cycle_seconds_excludes_dataset_and_precycle_evaluation_startup"
            ),
            "missing_values": "fail_closed_no_imputation",
        },
    }
    report["report_sha256"] = _sha256_value(report)
    _atomic_json(output, report)
    return report


def _default_paths(repo_root: Path, run_id: str) -> dict[str, Path]:
    evidence = (
        repo_root
        / "docs/implementation/reports/evidence/legal_ir_10_minute_integrated_smoke.json"
    )
    smoke_run_id = "legal-ir-10m-smoke-20260723T033130Z"
    return {
        "evidence": evidence,
        "summary": repo_root / "workspace/test-logs" / f"{smoke_run_id}-autoencoder.summary",
        "state": repo_root / "workspace/todo-queues" / f"{smoke_run_id}-autoencoder.state.json",
        "output": repo_root / "workspace/test-logs" / f"{run_id}-hparam-selection.json",
        "work_root": repo_root / "workspace/legal-ir-hparam" / run_id,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--repo-root", type=Path)
    parser.add_argument("--python", type=Path)
    parser.add_argument("--baseline-evidence", type=Path)
    parser.add_argument("--baseline-summary", type=Path)
    parser.add_argument("--baseline-state", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--work-root", type=Path)
    parser.add_argument("--candidate-count", type=int, default=DEFAULT_CANDIDATE_COUNT)
    parser.add_argument(
        "--seeds-per-candidate",
        type=int,
        default=DEFAULT_SEEDS_PER_CANDIDATE,
    )
    parser.add_argument("--max-concurrent-trainers", type=int, default=2)
    parser.add_argument("--dry-run", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    repo_root = (
        args.repo_root.resolve()
        if args.repo_root
        else Path(__file__).resolve().parents[3]
    )
    python = args.python or repo_root / ".venv-cuda/bin/python"
    defaults = _default_paths(repo_root, args.run_id)
    baseline_evidence = (args.baseline_evidence or defaults["evidence"]).resolve()
    baseline_summary = (args.baseline_summary or defaults["summary"]).resolve()
    baseline_state = (args.baseline_state or defaults["state"]).resolve()
    output = (args.output or defaults["output"]).resolve()
    work_root = (args.work_root or defaults["work_root"]).resolve()
    if args.candidate_count != DEFAULT_CANDIDATE_COUNT:
        raise SystemExit(
            f"the immutable one-hour plan requires {DEFAULT_CANDIDATE_COUNT} candidates"
        )
    if args.seeds_per_candidate != DEFAULT_SEEDS_PER_CANDIDATE:
        raise SystemExit(
            f"the immutable confidence plan requires {DEFAULT_SEEDS_PER_CANDIDATE} seeds"
        )
    if args.max_concurrent_trainers not in {1, 2}:
        raise SystemExit("max concurrent trainers must be one or two")
    if args.dry_run:
        evidence = _load_json(baseline_evidence)
        scheduler, baseline = build_scheduler_from_baseline(
            evidence=evidence,
            baseline_summary=baseline_summary,
            baseline_state=baseline_state,
            candidate_count=args.candidate_count,
            seeds_per_candidate=args.seeds_per_candidate,
            max_concurrent_trainers=args.max_concurrent_trainers,
        )
        print(
            json.dumps(
                {
                    "execution": False,
                    "promotable_evidence": False,
                    "run_id": args.run_id,
                    "output": str(output),
                    "work_root": str(work_root),
                    "baseline": baseline,
                    "plan": scheduler.plan_dict(),
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0

    lock_path = repo_root / "workspace/.legal-ir-canonical-writer.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    _STOP_REQUESTED.clear()
    received_signal = [0]

    def request_stop(signum: int, _frame: Any) -> None:
        received_signal[0] = signum
        _STOP_REQUESTED.set()
        _signal_process_groups(signal.SIGTERM)

    previous_handlers = {
        signum: signal.signal(signum, request_stop)
        for signum in (signal.SIGINT, signal.SIGTERM)
    }
    try:
        with lock_path.open("a+") as lock:
            try:
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                print("another canonical LegalIR writer holds the lock", file=sys.stderr)
                return 2
            report = execute_search(
                repo_root=repo_root,
                python=python,
                run_id=args.run_id,
                baseline_evidence=baseline_evidence,
                baseline_summary=baseline_summary,
                baseline_state=baseline_state,
                output=output,
                work_root=work_root,
                candidate_count=args.candidate_count,
                seeds_per_candidate=args.seeds_per_candidate,
                requested_trainers=args.max_concurrent_trainers,
            )
    except InterruptedError:
        return 128 + (received_signal[0] or signal.SIGTERM)
    finally:
        _signal_process_groups(signal.SIGTERM)
        for signum, handler in previous_handlers.items():
            signal.signal(signum, handler)
        _STOP_REQUESTED.clear()
    print(
        "legal_ir_hparam_search_completed "
        f"run_id={args.run_id} promotion_eligible={str(report['promotion_eligible']).lower()} "
        f"output={output} report_sha256={report['report_sha256']}"
    )
    return 0 if report["promotion_eligible"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
