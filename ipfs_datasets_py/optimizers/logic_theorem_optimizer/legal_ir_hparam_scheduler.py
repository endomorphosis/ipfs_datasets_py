"""Resource-aware successive-halving scheduler for LegalIR hparam search.

The scheduler owns policy and evidence validation only.  It does not train
models, mutate baselines, or decide proof authority.  Runtime wrappers can use
it to pick deterministic candidate/rung work, admit that work through the
host-global resource scheduler, and rank only complete snapshots that share the
same immutable baseline and metric lineage.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final, Mapping, Sequence

from ipfs_datasets_py.optimizers.logic_theorem_optimizer.resource_scheduler import (
    GlobalResourceScheduler,
    ResourceLane,
    ResourceLease,
    ResourceSchedulerConfig,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_ir_eval_splits import (
    HPARAM_SELECTION_OPERATION,
    split_guard_blocks_operation,
)


LEGAL_IR_HPARAM_SCHEDULER_SCHEMA_VERSION: Final = "legal-ir-hparam-scheduler-v1"

DEFAULT_REQUIRED_FAMILIES: Final = (
    "deontic",
    "frame_logic",
    "tdfol",
    "kg",
    "cec",
    "external_provers",
    "decompiler",
)
HIGHER_IS_BETTER: Final = frozenset(
    {
        "compiler_ir_cosine",
        "ir_cosine_similarity",
        "structural_validity",
        "symbolic_validity_success_rate",
        "hammer_proof_success_rate",
        "hammer_reconstruction_success_rate",
        "reconstruction_success_rate",
        "anti_copy_success_rate",
    }
)
LOWER_IS_BETTER: Final = frozenset(
    {
        "compiler_ir_cross_entropy_loss",
        "ir_cross_entropy_loss",
        "source_copy_penalty",
        "source_copy_reward_hack_penalty",
        "source_copy_rate",
        "hammer_failure_rate",
        "reconstruction_failure_rate",
    }
)
GUARDRAIL_BOOLEAN_KEYS: Final = (
    "semantic_regression",
    "provenance_regression",
    "anti_copy_regression",
    "hammer_proof_regression",
    "lean_reconstruction_regression",
    "process_lifecycle_regression",
    "queue_lag_regression",
)

DEFAULT_PARAM_SETS: Final = (
    {"lr": 0.28, "ce": 1.75, "rec": 0.60, "cos": 0.60, "legal": 1.35, "hard": 0.55, "fam": 1.05, "emb": 0.45},
    {"lr": 0.30, "ce": 1.50, "rec": 0.70, "cos": 0.70, "legal": 1.25, "hard": 0.60, "fam": 0.95, "emb": 0.55},
    {"lr": 0.33, "ce": 1.35, "rec": 0.80, "cos": 0.80, "legal": 1.15, "hard": 0.70, "fam": 1.15, "emb": 0.50},
    {"lr": 0.26, "ce": 2.00, "rec": 0.50, "cos": 0.50, "legal": 1.50, "hard": 0.45, "fam": 0.85, "emb": 0.65},
    {"lr": 0.31, "ce": 1.60, "rec": 0.65, "cos": 0.75, "legal": 1.40, "hard": 0.50, "fam": 1.10, "emb": 0.40},
    {"lr": 0.29, "ce": 1.40, "rec": 0.75, "cos": 0.65, "legal": 1.30, "hard": 0.65, "fam": 1.00, "emb": 0.60},
    {"lr": 0.24, "ce": 2.15, "rec": 0.55, "cos": 0.85, "legal": 1.55, "hard": 0.40, "fam": 1.20, "emb": 0.35},
    {"lr": 0.35, "ce": 1.25, "rec": 0.90, "cos": 0.95, "legal": 1.05, "hard": 0.75, "fam": 0.90, "emb": 0.70},
    {"lr": 0.27, "ce": 1.90, "rec": 0.85, "cos": 0.55, "legal": 1.45, "hard": 0.50, "fam": 1.25, "emb": 0.50},
    {"lr": 0.32, "ce": 1.70, "rec": 0.60, "cos": 0.90, "legal": 1.20, "hard": 0.80, "fam": 0.80, "emb": 0.55},
    {"lr": 0.25, "ce": 1.30, "rec": 0.95, "cos": 0.70, "legal": 1.60, "hard": 0.60, "fam": 1.05, "emb": 0.75},
    {"lr": 0.34, "ce": 1.85, "rec": 0.45, "cos": 0.65, "legal": 1.10, "hard": 0.35, "fam": 1.30, "emb": 0.45},
)


def _canonical_json(value: Any) -> str:
    return json.dumps(value, allow_nan=False, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _finite(value: Any, *, name: str, minimum: float | None = None) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a finite number")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a finite number") from exc
    if not math.isfinite(result) or (minimum is not None and result < minimum):
        suffix = f" >= {minimum:g}" if minimum is not None else ""
        raise ValueError(f"{name} must be finite{suffix}")
    return result


def _int(value: Any, *, name: str, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"{name} must be an integer >= {minimum}")
    return value


def _immutable_mapping(value: Mapping[str, Any]) -> Mapping[str, Any]:
    return MappingProxyType(dict(sorted(value.items())))


@dataclass(frozen=True, slots=True)
class SharedBaseline:
    """Immutable baseline identity shared by every hparam candidate."""

    baseline_id: str
    revision: str
    dataset_digest: str
    metric_lineage_id: str
    metrics: Mapping[str, Any] = field(default_factory=dict)
    family_metrics: Mapping[str, Any] = field(default_factory=dict)
    split_guard: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in ("baseline_id", "revision", "dataset_digest", "metric_lineage_id"):
            value = str(getattr(self, name) or "").strip()
            if not value:
                raise ValueError(f"{name} must be non-empty")
            object.__setattr__(self, name, value)
        object.__setattr__(self, "metrics", _immutable_mapping(self.metrics))
        object.__setattr__(self, "family_metrics", _immutable_mapping(self.family_metrics))
        object.__setattr__(self, "split_guard", _immutable_mapping(self.split_guard))

    @property
    def digest(self) -> str:
        return _digest(self.to_dict(include_digest=False))

    @property
    def lineage_digest(self) -> str:
        return _digest(
            {
                "baseline_digest": self.digest,
                "metric_lineage_id": self.metric_lineage_id,
                "schema_version": LEGAL_IR_HPARAM_SCHEDULER_SCHEMA_VERSION,
            }
        )

    def to_dict(self, *, include_digest: bool = True) -> dict[str, Any]:
        result = {
            "baseline_id": self.baseline_id,
            "revision": self.revision,
            "dataset_digest": self.dataset_digest,
            "metric_lineage_id": self.metric_lineage_id,
            "metrics": dict(self.metrics),
            "family_metrics": dict(self.family_metrics),
            "split_guard": dict(self.split_guard),
        }
        if include_digest:
            result["baseline_digest"] = self.digest
            result["lineage_digest"] = self.lineage_digest
        return result


@dataclass(frozen=True, slots=True)
class HParamCandidate:
    """Deterministic candidate with a baseline-bound seed."""

    candidate_id: str
    index: int
    seed: int
    params: tuple[tuple[str, float], ...]
    baseline_digest: str
    lineage_digest: str

    @classmethod
    def build(
        cls,
        *,
        index: int,
        seed: int,
        params: Mapping[str, Any],
        baseline: SharedBaseline,
    ) -> "HParamCandidate":
        _int(index, name="index")
        _int(seed, name="seed")
        stable_params = tuple(
            (str(key), _finite(value, name=f"params.{key}"))
            for key, value in sorted(dict(params).items())
        )
        candidate_id = "hparam-" + _digest(
            {
                "baseline_digest": baseline.digest,
                "index": index,
                "params": stable_params,
                "seed": seed,
            }
        )[:16]
        return cls(
            candidate_id=candidate_id,
            index=index,
            seed=seed,
            params=stable_params,
            baseline_digest=baseline.digest,
            lineage_digest=baseline.lineage_digest,
        )

    def param_dict(self) -> dict[str, float]:
        return dict(self.params)

    def config_string(self) -> str:
        return " ".join(f"{key}={value:g}" for key, value in self.params)

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "index": self.index,
            "seed": self.seed,
            "params": self.param_dict(),
            "baseline_digest": self.baseline_digest,
            "lineage_digest": self.lineage_digest,
            "config_string": self.config_string(),
        }


@dataclass(frozen=True, slots=True)
class HParamRung:
    index: int
    budget_seconds: int
    survivor_count: int

    def __post_init__(self) -> None:
        _int(self.index, name="rung.index")
        _int(self.budget_seconds, name="rung.budget_seconds", minimum=1)
        _int(self.survivor_count, name="rung.survivor_count", minimum=1)

    def to_dict(self) -> dict[str, int]:
        return {
            "index": self.index,
            "budget_seconds": self.budget_seconds,
            "survivor_count": self.survivor_count,
        }


@dataclass(frozen=True, slots=True)
class FamilyGuardrailConfig:
    required_families: tuple[str, ...] = DEFAULT_REQUIRED_FAMILIES
    min_confidence: float = 0.80
    require_paired_metrics: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "required_families",
            tuple(str(family).strip() for family in self.required_families if str(family).strip()),
        )
        if not self.required_families:
            raise ValueError("required_families must be non-empty")
        value = _finite(self.min_confidence, name="min_confidence", minimum=0.0)
        if value > 1.0:
            raise ValueError("min_confidence must be between 0 and 1")


@dataclass(frozen=True, slots=True)
class ResourceRequirements:
    evaluation_cpu_slots: int = 1
    evaluation_memory_mb: int = 1024
    trainer_cpu_slots: int = 2
    trainer_memory_mb: int = 8192
    trainer_gpu_memory_mb: int = 12288
    lease_timeout_seconds: float = 0.0

    def __post_init__(self) -> None:
        for name in (
            "evaluation_cpu_slots",
            "evaluation_memory_mb",
            "trainer_cpu_slots",
            "trainer_memory_mb",
            "trainer_gpu_memory_mb",
        ):
            minimum = 1 if name.endswith("cpu_slots") else 0
            _int(getattr(self, name), name=name, minimum=minimum)
        _finite(self.lease_timeout_seconds, name="lease_timeout_seconds", minimum=0.0)


@dataclass(frozen=True, slots=True)
class HParamSearchConfig:
    baseline: SharedBaseline
    total_budget_seconds: int = 3600
    initial_candidate_count: int = 12
    rung_budgets_seconds: tuple[int, ...] = (150, 300, 600)
    reduction_factor: int = 2
    base_seed: int = 8675309
    max_concurrent_evaluations: int = 4
    max_concurrent_trainers: int = 1
    allow_concurrent_trainers: bool = False
    min_validation_cosine: float = 0.0
    cosine_penalty: float = 4.0
    ir_ce_weight: float = 0.25
    ir_cosine_penalty: float = 2.0
    guardrails: FamilyGuardrailConfig = field(default_factory=FamilyGuardrailConfig)
    resources: ResourceRequirements = field(default_factory=ResourceRequirements)

    def __post_init__(self) -> None:
        if split_guard_blocks_operation(
            self.baseline.split_guard,
            HPARAM_SELECTION_OPERATION,
        ):
            raise ValueError("LegalIR split guard blocks hparam selection")
        _int(self.total_budget_seconds, name="total_budget_seconds", minimum=1)
        _int(self.initial_candidate_count, name="initial_candidate_count", minimum=2)
        _int(self.reduction_factor, name="reduction_factor", minimum=2)
        _int(self.base_seed, name="base_seed")
        _int(self.max_concurrent_evaluations, name="max_concurrent_evaluations", minimum=1)
        _int(self.max_concurrent_trainers, name="max_concurrent_trainers", minimum=1)
        budgets = tuple(int(value) for value in self.rung_budgets_seconds)
        if len(budgets) < 2 or any(value <= 0 for value in budgets):
            raise ValueError("rung_budgets_seconds must contain at least two positive budgets")
        if tuple(sorted(budgets)) != budgets or len(set(budgets)) != len(budgets):
            raise ValueError("rung_budgets_seconds must be strictly increasing")
        object.__setattr__(self, "rung_budgets_seconds", budgets)
        for name in ("min_validation_cosine", "cosine_penalty", "ir_ce_weight", "ir_cosine_penalty"):
            _finite(getattr(self, name), name=name, minimum=0.0)
        if self.planned_resource_seconds > self.total_budget_seconds:
            raise ValueError(
                f"successive-halving plan spends {self.planned_resource_seconds}s "
                f"above fixed budget {self.total_budget_seconds}s"
            )

    @property
    def rungs(self) -> tuple[HParamRung, ...]:
        survivor_count = self.initial_candidate_count
        rungs: list[HParamRung] = []
        for index, budget in enumerate(self.rung_budgets_seconds):
            rungs.append(HParamRung(index=index, budget_seconds=budget, survivor_count=survivor_count))
            survivor_count = max(1, math.ceil(survivor_count / self.reduction_factor))
        return tuple(rungs)

    @property
    def planned_resource_seconds(self) -> int:
        total = 0
        previous = 0
        for rung in self.rungs:
            total += rung.survivor_count * (rung.budget_seconds - previous)
            previous = rung.budget_seconds
        return total


@dataclass(frozen=True, slots=True)
class TrialWorkItem:
    candidate: HParamCandidate
    rung: HParamRung
    previous_budget_seconds: int = 0

    @property
    def run_id_suffix(self) -> str:
        return f"{self.candidate.candidate_id}-rung-{self.rung.index:02d}"

    @property
    def additional_budget_seconds(self) -> int:
        return self.rung.budget_seconds - self.previous_budget_seconds

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate": self.candidate.to_dict(),
            "rung": self.rung.to_dict(),
            "previous_budget_seconds": self.previous_budget_seconds,
            "additional_budget_seconds": self.additional_budget_seconds,
            "run_id_suffix": self.run_id_suffix,
        }


@dataclass(frozen=True, slots=True)
class TrialSnapshot:
    candidate_id: str
    rung_index: int
    budget_seconds: int
    elapsed_seconds: float
    status: str
    snapshot_complete: bool
    baseline_digest: str
    lineage_digest: str
    metrics: Mapping[str, Any] = field(default_factory=dict)
    family_metrics: Mapping[str, Any] = field(default_factory=dict)
    snapshot_id: str = ""

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "TrialSnapshot":
        return cls(
            candidate_id=str(value.get("candidate_id") or value.get("hparam_candidate_id") or ""),
            rung_index=int(value.get("rung_index", value.get("hparam_rung_index", -1))),
            budget_seconds=int(value.get("budget_seconds", value.get("duration_seconds", 0)) or 0),
            elapsed_seconds=float(value.get("elapsed_seconds", value.get("wall_clock_seconds", 0.0)) or 0.0),
            status=str(value.get("status") or ""),
            snapshot_complete=value.get("snapshot_complete") is True,
            baseline_digest=str(value.get("baseline_digest") or ""),
            lineage_digest=str(value.get("lineage_digest") or value.get("metric_lineage_digest") or ""),
            metrics=value.get("metrics", value) if isinstance(value.get("metrics", value), Mapping) else {},
            family_metrics=value.get("family_metrics", {}) if isinstance(value.get("family_metrics", {}), Mapping) else {},
            snapshot_id=str(value.get("snapshot_id") or value.get("run_id") or ""),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "rung_index": self.rung_index,
            "budget_seconds": self.budget_seconds,
            "elapsed_seconds": self.elapsed_seconds,
            "status": self.status,
            "snapshot_complete": self.snapshot_complete,
            "baseline_digest": self.baseline_digest,
            "lineage_digest": self.lineage_digest,
            "metrics": dict(self.metrics),
            "family_metrics": dict(self.family_metrics),
            "snapshot_id": self.snapshot_id,
        }


@dataclass(frozen=True, slots=True)
class TrialDecision:
    snapshot: TrialSnapshot
    eligible: bool
    score: float
    failures: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.snapshot.candidate_id,
            "rung_index": self.snapshot.rung_index,
            "eligible": self.eligible,
            "score": self.score,
            "failures": list(self.failures),
            "snapshot_id": self.snapshot.snapshot_id,
        }


@dataclass(slots=True)
class TrialLeaseBundle:
    work_item: TrialWorkItem
    evaluation_lease: ResourceLease
    trainer_lease: ResourceLease | None = None

    def release(self) -> None:
        if self.trainer_lease is not None:
            self.trainer_lease.release()
        self.evaluation_lease.release()

    def to_dict(self) -> dict[str, Any]:
        return {
            "work_item": self.work_item.to_dict(),
            "evaluation_lease": self.evaluation_lease.to_dict(),
            "trainer_lease": None if self.trainer_lease is None else self.trainer_lease.to_dict(),
        }


class LegalIRHParamScheduler:
    """Deterministic successive-halving scheduler with fail-closed evidence gates."""

    def __init__(
        self,
        config: HParamSearchConfig,
        *,
        candidates: Sequence[Mapping[str, Any]] | None = None,
    ) -> None:
        self.config = config
        param_sets = tuple(candidates or DEFAULT_PARAM_SETS)
        if len(param_sets) < config.initial_candidate_count:
            raise ValueError("not enough parameter sets for initial_candidate_count")
        self.candidates = tuple(
            HParamCandidate.build(
                index=index,
                seed=self._candidate_seed(index, params),
                params=params,
                baseline=config.baseline,
            )
            for index, params in enumerate(param_sets[: config.initial_candidate_count])
        )
        self._candidate_by_id = {candidate.candidate_id: candidate for candidate in self.candidates}
        self._results: dict[tuple[int, str], TrialSnapshot] = {}
        self._active_candidate_ids_by_rung: dict[int, tuple[str, ...]] = {
            0: tuple(candidate.candidate_id for candidate in self.candidates)
        }

    def _candidate_seed(self, index: int, params: Mapping[str, Any]) -> int:
        digest = _digest(
            {
                "base_seed": self.config.base_seed,
                "baseline_digest": self.config.baseline.digest,
                "index": index,
                "params": dict(sorted(params.items())),
            }
        )
        return int(digest[:8], 16)

    def plan_dict(self) -> dict[str, Any]:
        return {
            "schema_version": LEGAL_IR_HPARAM_SCHEDULER_SCHEMA_VERSION,
            "baseline": self.config.baseline.to_dict(),
            "total_budget_seconds": self.config.total_budget_seconds,
            "planned_resource_seconds": self.config.planned_resource_seconds,
            "successive_halving": {
                "reduction_factor": self.config.reduction_factor,
                "rungs": [rung.to_dict() for rung in self.config.rungs],
            },
            "candidate_count": len(self.candidates),
            "candidates": [candidate.to_dict() for candidate in self.candidates],
            "resource_policy": {
                "max_concurrent_evaluations": self.config.max_concurrent_evaluations,
                "max_concurrent_trainers": self.config.max_concurrent_trainers,
                "allow_concurrent_trainers": self.config.allow_concurrent_trainers,
                "default_cuda_trainers": 1,
                "parallel_lanes": ["snapshot_evaluation", "proof", "validation"],
            },
        }

    def ready_work(self) -> tuple[TrialWorkItem, ...]:
        rung_index = self.current_rung_index()
        if rung_index is None:
            return ()
        rung = self.config.rungs[rung_index]
        previous_budget = 0 if rung_index == 0 else self.config.rungs[rung_index - 1].budget_seconds
        ready: list[TrialWorkItem] = []
        for candidate_id in self._active_candidate_ids_by_rung[rung_index]:
            if (rung_index, candidate_id) in self._results:
                continue
            ready.append(
                TrialWorkItem(
                    candidate=self._candidate_by_id[candidate_id],
                    rung=rung,
                    previous_budget_seconds=previous_budget,
                )
            )
        return tuple(ready)

    def current_rung_index(self) -> int | None:
        for rung in self.config.rungs:
            ids = self._active_candidate_ids_by_rung.get(rung.index)
            if not ids:
                return None
            if any((rung.index, candidate_id) not in self._results for candidate_id in ids):
                return rung.index
        return None

    def record_result(self, snapshot: TrialSnapshot | Mapping[str, Any]) -> TrialDecision:
        trial = snapshot if isinstance(snapshot, TrialSnapshot) else TrialSnapshot.from_mapping(snapshot)
        if trial.candidate_id not in self._candidate_by_id:
            raise ValueError(f"unknown candidate_id: {trial.candidate_id!r}")
        if trial.rung_index < 0 or trial.rung_index >= len(self.config.rungs):
            raise ValueError(f"unknown rung_index: {trial.rung_index!r}")
        expected_ids = self._active_candidate_ids_by_rung.get(trial.rung_index, ())
        if trial.candidate_id not in expected_ids:
            raise ValueError("candidate is not active for this rung")
        expected_budget = self.config.rungs[trial.rung_index].budget_seconds
        if trial.budget_seconds != expected_budget:
            raise ValueError(
                f"trial budget mismatch for rung {trial.rung_index}: "
                f"{trial.budget_seconds} != {expected_budget}"
            )
        candidate = self._candidate_by_id[trial.candidate_id]
        if trial.baseline_digest != candidate.baseline_digest:
            raise ValueError("baseline digest mismatch")
        if trial.lineage_digest != candidate.lineage_digest:
            raise ValueError("metric lineage digest mismatch")
        decision = self.score_snapshot(trial)
        self._results[(trial.rung_index, trial.candidate_id)] = trial
        self._maybe_promote_locked(trial.rung_index)
        return decision

    def _maybe_promote_locked(self, rung_index: int) -> None:
        next_index = rung_index + 1
        if next_index >= len(self.config.rungs) or next_index in self._active_candidate_ids_by_rung:
            return
        active_ids = self._active_candidate_ids_by_rung.get(rung_index, ())
        if not active_ids or any((rung_index, candidate_id) not in self._results for candidate_id in active_ids):
            return
        decisions = [
            self.score_snapshot(self._results[(rung_index, candidate_id)])
            for candidate_id in active_ids
        ]
        eligible = [decision for decision in decisions if decision.eligible]
        if not eligible:
            self._active_candidate_ids_by_rung[next_index] = ()
            return
        survivor_count = self.config.rungs[next_index].survivor_count
        promoted = sorted(
            eligible,
            key=lambda decision: (
                decision.score,
                self._candidate_by_id[decision.snapshot.candidate_id].seed,
                decision.snapshot.candidate_id,
            ),
        )[:survivor_count]
        self._active_candidate_ids_by_rung[next_index] = tuple(
            decision.snapshot.candidate_id for decision in promoted
        )

    def score_snapshot(self, snapshot: TrialSnapshot) -> TrialDecision:
        failures: list[str] = []
        if not snapshot.snapshot_complete:
            failures.append("incomplete_snapshot")
        if snapshot.status.lower() not in {"succeeded", "success", "completed"}:
            failures.append(f"status:{snapshot.status or 'missing'}")
        if snapshot.elapsed_seconds <= 0 or snapshot.elapsed_seconds > snapshot.budget_seconds * 1.50:
            failures.append("elapsed_seconds_invalid")
        failures.extend(self._family_guardrail_failures(snapshot.family_metrics))
        score = self._objective_score(snapshot.metrics)
        return TrialDecision(
            snapshot=snapshot,
            eligible=not failures and math.isfinite(score),
            score=score,
            failures=tuple(failures),
        )

    def _objective_score(self, metrics: Mapping[str, Any]) -> float:
        ce = _metric(metrics, "best_validation_ce", "validation_ce", default=1e12)
        cosine = _metric(metrics, "best_validation_cosine", "validation_cosine", default=-1.0)
        ir_ce = _metric(metrics, "best_validation_ir_ce", "compiler_ir_cross_entropy_loss", default=ce)
        ir_cosine = _metric(metrics, "best_validation_ir_cosine", "compiler_ir_cosine", default=cosine)
        score = ce + self.config.ir_ce_weight * ir_ce
        score += self.config.cosine_penalty * max(0.0, self.config.min_validation_cosine - cosine)
        score += self.config.ir_cosine_penalty * max(0.0, self.config.min_validation_cosine - ir_cosine)
        return score if math.isfinite(score) else 1e12

    def _family_guardrail_failures(self, family_metrics: Mapping[str, Any]) -> list[str]:
        failures: list[str] = []
        for family in self.config.guardrails.required_families:
            raw = family_metrics.get(family)
            if not isinstance(raw, Mapping):
                failures.append(f"family_guardrail_missing:{family}")
                continue
            for key in GUARDRAIL_BOOLEAN_KEYS:
                if raw.get(key) is True:
                    failures.append(f"{key}:{family}")
            confidence = _confidence(raw)
            if confidence is None or confidence < self.config.guardrails.min_confidence:
                failures.append(f"family_confidence:{family}:{confidence if confidence is not None else 'missing'}")
            baseline = raw.get("baseline")
            candidate = raw.get("candidate")
            compared = False
            if isinstance(baseline, Mapping) and isinstance(candidate, Mapping):
                for metric in HIGHER_IS_BETTER:
                    before = _maybe_float(baseline.get(metric))
                    after = _maybe_float(candidate.get(metric))
                    if before is not None and after is not None:
                        compared = True
                        if after < before - 1e-12:
                            failures.append(f"family_metric_regression:{family}:{metric}")
                for metric in LOWER_IS_BETTER:
                    before = _maybe_float(baseline.get(metric))
                    after = _maybe_float(candidate.get(metric))
                    if before is not None and after is not None:
                        compared = True
                        if after > before + 1e-12:
                            failures.append(f"family_metric_regression:{family}:{metric}")
            if self.config.guardrails.require_paired_metrics and not compared:
                failures.append(f"family_paired_metric_missing:{family}")
        return failures

    def rung_decisions(self, rung_index: int) -> tuple[TrialDecision, ...]:
        ids = self._active_candidate_ids_by_rung.get(rung_index, ())
        return tuple(
            self.score_snapshot(self._results[(rung_index, candidate_id)])
            for candidate_id in ids
            if (rung_index, candidate_id) in self._results
        )

    def selected_candidate(self) -> HParamCandidate | None:
        final_index = len(self.config.rungs) - 1
        decisions = [decision for decision in self.rung_decisions(final_index) if decision.eligible]
        if not decisions:
            return None
        best = min(
            decisions,
            key=lambda decision: (
                decision.score,
                self._candidate_by_id[decision.snapshot.candidate_id].seed,
                decision.snapshot.candidate_id,
            ),
        )
        return self._candidate_by_id[best.snapshot.candidate_id]

    def admit_work(
        self,
        scheduler: GlobalResourceScheduler,
        work_items: Sequence[TrialWorkItem] | None = None,
    ) -> tuple[TrialLeaseBundle, ...]:
        """Acquire resource leases for ready work without overcommitting memory."""

        selected = tuple(work_items or self.ready_work())
        bundles: list[TrialLeaseBundle] = []
        trainer_count = 0
        safe_trainer_limit = self._safe_trainer_limit(scheduler)
        for item in selected:
            if len(bundles) >= self.config.max_concurrent_evaluations:
                break
            eval_lease = scheduler.try_acquire(
                ResourceLane.VALIDATION,
                cpu_slots=self.config.resources.evaluation_cpu_slots,
                memory_mb=self.config.resources.evaluation_memory_mb,
                timeout=self.config.resources.lease_timeout_seconds,
                request_id=f"{item.run_id_suffix}:evaluation",
            )
            if eval_lease is None:
                break
            trainer_lease = None
            if trainer_count < safe_trainer_limit:
                trainer_lease = scheduler.try_acquire(
                    ResourceLane.HAMMER_LEAN,
                    cpu_slots=self.config.resources.trainer_cpu_slots,
                    memory_mb=self.config.resources.trainer_memory_mb,
                    gpu_memory_mb=self.config.resources.trainer_gpu_memory_mb,
                    requires_gpu=self.config.resources.trainer_gpu_memory_mb > 0,
                    timeout=self.config.resources.lease_timeout_seconds,
                    request_id=f"{item.run_id_suffix}:trainer",
                )
                if trainer_lease is not None:
                    trainer_count += 1
            if trainer_lease is None:
                eval_lease.release()
                if bundles:
                    break
                break
            bundles.append(TrialLeaseBundle(item, eval_lease, trainer_lease))
        return tuple(bundles)

    def _safe_trainer_limit(self, scheduler: GlobalResourceScheduler) -> int:
        if self.config.max_concurrent_trainers <= 1 or not self.config.allow_concurrent_trainers:
            return 1
        snapshot = scheduler.snapshot()
        capacity = snapshot.get("capacity", {})
        available = snapshot.get("available", {})
        total_gpu = capacity.get("usable_gpu_memory_mb")
        available_gpu = available.get("gpu_memory_mb")
        if total_gpu is None or available_gpu is None:
            return 1
        per_trainer = max(1, self.config.resources.trainer_gpu_memory_mb)
        memory_fit = max(1, int(float(available_gpu) // per_trainer))
        return max(1, min(self.config.max_concurrent_trainers, memory_fit))


def _metric(metrics: Mapping[str, Any], *keys: str, default: float) -> float:
    for key in keys:
        value = _maybe_float(metrics.get(key))
        if value is not None:
            return value
    return default


def _maybe_float(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _confidence(raw: Mapping[str, Any]) -> float | None:
    for key in ("confidence_lower_bound", "sample_confidence", "confidence"):
        value = _maybe_float(raw.get(key))
        if value is not None:
            return max(0.0, min(1.0, value))
    candidate = raw.get("candidate")
    if isinstance(candidate, Mapping):
        for key in ("confidence_lower_bound", "sample_confidence", "confidence"):
            value = _maybe_float(candidate.get(key))
            if value is not None:
                return max(0.0, min(1.0, value))
    return None


def default_baseline_from_env() -> SharedBaseline:
    return SharedBaseline(
        baseline_id=os.environ.get("LEGAL_IR_HPARAM_BASELINE_ID", "legal-ir-shared-baseline"),
        revision=os.environ.get("LEGAL_IR_HPARAM_BASELINE_REVISION", "workspace"),
        dataset_digest=os.environ.get("LEGAL_IR_HPARAM_DATASET_DIGEST", "sha256:unknown-dataset"),
        metric_lineage_id=os.environ.get("LEGAL_IR_HPARAM_METRIC_LINEAGE_ID", "legal-ir-current-metrics"),
    )


def build_default_scheduler(
    *,
    total_budget_seconds: int = 3600,
    candidate_count: int = 12,
    base_seed: int = 8675309,
    allow_concurrent_trainers: bool = False,
    max_concurrent_trainers: int = 1,
) -> LegalIRHParamScheduler:
    config = HParamSearchConfig(
        baseline=default_baseline_from_env(),
        total_budget_seconds=total_budget_seconds,
        initial_candidate_count=candidate_count,
        base_seed=base_seed,
        allow_concurrent_trainers=allow_concurrent_trainers,
        max_concurrent_trainers=max_concurrent_trainers,
    )
    return LegalIRHParamScheduler(config)


def _format_env(plan: Mapping[str, Any], *, run_id: str) -> str:
    rungs = plan["successive_halving"]["rungs"]
    return "\n".join(
        [
            f"hparam_scheduler_schema={plan['schema_version']}",
            f"hparam_run_id={run_id}",
            f"hparam_candidate_count={plan['candidate_count']}",
            f"hparam_planned_resource_seconds={plan['planned_resource_seconds']}",
            f"hparam_total_budget_seconds={plan['total_budget_seconds']}",
            "hparam_rung_budgets="
            + ",".join(str(rung["budget_seconds"]) for rung in rungs),
            "hparam_rung_survivors="
            + ",".join(str(rung["survivor_count"]) for rung in rungs),
            "hparam_parallel_lanes="
            + ",".join(plan["resource_policy"]["parallel_lanes"]),
            f"hparam_default_cuda_trainers={plan['resource_policy']['default_cuda_trainers']}",
            f"hparam_allow_concurrent_trainers={str(plan['resource_policy']['allow_concurrent_trainers']).lower()}",
        ]
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    plan_parser = subparsers.add_parser("plan", help="emit deterministic hparam search plan")
    plan_parser.add_argument("--run-id", default="legal-ir-hparam")
    plan_parser.add_argument("--budget-seconds", type=int, default=3600)
    plan_parser.add_argument("--candidate-count", type=int, default=12)
    plan_parser.add_argument("--base-seed", type=int, default=8675309)
    plan_parser.add_argument("--allow-concurrent-trainers", action="store_true")
    plan_parser.add_argument("--max-concurrent-trainers", type=int, default=1)
    plan_parser.add_argument("--format", choices=("json", "env"), default="json")
    plan_parser.add_argument("--resource-state-path", default="")
    args = parser.parse_args(argv)

    if args.command == "plan":
        scheduler = build_default_scheduler(
            total_budget_seconds=args.budget_seconds,
            candidate_count=args.candidate_count,
            base_seed=args.base_seed,
            allow_concurrent_trainers=args.allow_concurrent_trainers,
            max_concurrent_trainers=args.max_concurrent_trainers,
        )
        plan = scheduler.plan_dict()
        if args.resource_state_path:
            resource_scheduler = GlobalResourceScheduler(
                ResourceSchedulerConfig(state_path=Path(args.resource_state_path))
            )
            plan["resource_scheduler"] = resource_scheduler.snapshot()
        if args.format == "env":
            print(_format_env(plan, run_id=args.run_id))
        else:
            print(_canonical_json({"run_id": args.run_id, **plan}))
        return 0
    return 2


__all__ = [
    "LEGAL_IR_HPARAM_SCHEDULER_SCHEMA_VERSION",
    "SharedBaseline",
    "HParamCandidate",
    "HParamRung",
    "FamilyGuardrailConfig",
    "ResourceRequirements",
    "HParamSearchConfig",
    "TrialWorkItem",
    "TrialSnapshot",
    "TrialDecision",
    "TrialLeaseBundle",
    "LegalIRHParamScheduler",
    "build_default_scheduler",
    "default_baseline_from_env",
    "main",
]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
