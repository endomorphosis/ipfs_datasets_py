#!/usr/bin/env python3
"""Run the five-task Leanstral seed canary with paired controls.

The seed canary is the production-promotion gate after shadow mode.  It
selects at most five locally verified LegalIR compiler tasks, optionally appends
those tasks to a bounded TODO queue, and compares the Leanstral-assisted lane
against a matched non-Leanstral control.  Promotion is fail-closed: every hard
guardrail must be non-regressing and compiler-development throughput must
materially improve.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = Path(__file__).resolve().parents[3]
ACCELERATE_ROOT = REPO_ROOT.parent / "ipfs_accelerate_py"
for import_root in (SCRIPT_DIR, ACCELERATE_ROOT, REPO_ROOT):
    if import_root.exists():
        import_root_text = str(import_root)
        if import_root_text not in sys.path:
            sys.path.insert(0, import_root_text)

from run_leanstral_shadow_canary import (  # noqa: E402
    GUARDRAIL_CODES as SHADOW_GUARDRAIL_CODES,
    ShadowCanaryConfig,
    build_dry_run_fixture_records,
    load_disagreement_records,
    resolve_disagreement_input_paths,
    run_shadow_canary,
)
from ipfs_datasets_py.logic.modal.leanstral_audit import canonical_sha256  # noqa: E402


SEED_CANARY_SCHEMA_VERSION = "legal-ir-leanstral-real-seed-canary-v2"
DEFAULT_REPORT_PATH = Path("docs/implementation/reports/leanstral_real_seed_canary.md")
LEGACY_REPORT_PATH = Path("docs/implementation/reports/leanstral_seed_canary.md")
DEFAULT_TODO_QUEUE_PATH = Path("workspace/leanstral-seed-canary/todos.jsonl")
MAX_SEED_TODOS = 5
MIN_ACCEPTED_COMPILER_PATCHES = 1
MIN_TASK_ACCEPTED_PATCH_RATE_IMPROVEMENT = 0.20
MIN_STATE_ACCEPTED_PATCH_LAG_REDUCTION = 0.25
MAX_AUTOENCODER_CYCLE_OVERHEAD = 0.10
MAX_TRANSIENT_EXECUTION_FAILURE_RATE = 0.05

HARD_GUARDRAIL_METRICS = (
    "compiler_ir_cross_entropy",
    "compiler_ir_cosine",
    "learned_ir_view_cross_entropy",
    "learned_ir_view_cosine",
    "theorem_validity",
    "proof_validity",
    "graph_validity",
    "provenance_validity",
    "anti_copy_penalty",
    "mutation_validity",
    "validation_rejection_rate",
    "task_to_accepted_patch_rate",
    "cycle_time_seconds",
    "state_to_patch_lag",
)
LOWER_IS_BETTER = frozenset(
    {
        "compiler_ir_cross_entropy",
        "learned_ir_view_cross_entropy",
        "anti_copy_penalty",
        "validation_rejection_rate",
        "cycle_time_seconds",
        "state_to_patch_lag",
    }
)
HIGHER_IS_BETTER = frozenset(
    {
        "compiler_ir_cosine",
        "learned_ir_view_cosine",
        "theorem_validity",
        "proof_validity",
        "graph_validity",
        "provenance_validity",
        "mutation_validity",
        "task_to_accepted_patch_rate",
    }
)
THROUGHPUT_METRICS = (
    "task_to_accepted_patch_rate",
    "cycle_time_seconds",
    "state_to_patch_lag",
)


@dataclass(frozen=True)
class SeedCanaryConfig:
    """Runtime controls for the paired Leanstral seed canary."""

    max_todos: int = MAX_SEED_TODOS
    dry_run: bool = True
    cache_dir: str = ""
    report_path: str = str(DEFAULT_REPORT_PATH)
    todo_queue_path: str = str(DEFAULT_TODO_QUEUE_PATH)
    require_verified_audit_for_promotion: bool = True
    material_throughput_improvement: float = MIN_TASK_ACCEPTED_PATCH_RATE_IMPROVEMENT
    metric_deadband: float = 0.0
    max_source_span_copy_ratio: float = 0.25
    min_accepted_compiler_patches: int = MIN_ACCEPTED_COMPILER_PATCHES
    min_task_accepted_patch_rate_improvement: float = MIN_TASK_ACCEPTED_PATCH_RATE_IMPROVEMENT
    min_state_accepted_patch_lag_reduction: float = MIN_STATE_ACCEPTED_PATCH_LAG_REDUCTION
    max_autoencoder_cycle_overhead: float = MAX_AUTOENCODER_CYCLE_OVERHEAD
    max_transient_execution_failure_rate: float = MAX_TRANSIENT_EXECUTION_FAILURE_RATE
    require_actual_isolated_implementations: bool = True
    provider: str = "mistral_vibe"
    model: str = "Leanstral"
    vibe_agent: str = "lean"
    timeout_seconds: float = 300.0

    def bounded_max_todos(self) -> int:
        return max(0, min(MAX_SEED_TODOS, int(self.max_todos or 0)))

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PairedEvaluationMetrics:
    """Comparable production-promotion metrics for one canary arm."""

    compiler_ir_cross_entropy: float
    compiler_ir_cosine: float
    learned_ir_view_cross_entropy: float
    learned_ir_view_cosine: float
    proof_validity: float
    graph_validity: float
    anti_copy_penalty: float
    validation_rejection_rate: float
    task_to_accepted_patch_rate: float
    cycle_time_seconds: float
    state_to_patch_lag: float
    theorem_validity: float = 1.0
    provenance_validity: float = 1.0
    mutation_validity: float = 1.0
    autoencoder_cycle_overhead: float = 0.0
    transient_execution_failure_rate: float = 0.0

    def to_dict(self) -> Dict[str, float]:
        return {
            "anti_copy_penalty": _stable_float(self.anti_copy_penalty),
            "autoencoder_cycle_overhead": _stable_float(
                self.autoencoder_cycle_overhead
            ),
            "compiler_ir_cosine": _stable_float(self.compiler_ir_cosine),
            "compiler_ir_cross_entropy": _stable_float(self.compiler_ir_cross_entropy),
            "cycle_time_seconds": _stable_float(self.cycle_time_seconds),
            "graph_validity": _stable_float(self.graph_validity),
            "learned_ir_view_cosine": _stable_float(self.learned_ir_view_cosine),
            "learned_ir_view_cross_entropy": _stable_float(
                self.learned_ir_view_cross_entropy
            ),
            "mutation_validity": _stable_float(self.mutation_validity),
            "proof_validity": _stable_float(self.proof_validity),
            "provenance_validity": _stable_float(self.provenance_validity),
            "state_to_patch_lag": _stable_float(self.state_to_patch_lag),
            "task_to_accepted_patch_rate": _stable_float(
                self.task_to_accepted_patch_rate
            ),
            "theorem_validity": _stable_float(self.theorem_validity),
            "transient_execution_failure_rate": _stable_float(
                self.transient_execution_failure_rate
            ),
            "validation_rejection_rate": _stable_float(
                self.validation_rejection_rate
            ),
        }

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "PairedEvaluationMetrics":
        compiler = _mapping(data.get("compiler_ir"))
        learned = _mapping(
            data.get("learned_ir_view")
            or data.get("learned_ir")
            or data.get("legal_ir_view")
        )
        validity = _mapping(data.get("validity"))
        graph = _mapping(data.get("graph"))
        anti_copy = _mapping(data.get("anti_copy"))
        throughput = _mapping(data.get("throughput"))
        return cls(
            compiler_ir_cross_entropy=_finite_float(
                data.get("compiler_ir_cross_entropy"),
                _finite_float(
                    data.get("compiler_ir_ce"),
                    _finite_float(compiler.get("cross_entropy_loss")),
                ),
            ),
            compiler_ir_cosine=_finite_float(
                data.get("compiler_ir_cosine"),
                _finite_float(
                    data.get("compiler_ir_cosine_similarity"),
                    _finite_float(compiler.get("cosine_similarity"), 1.0),
                ),
            ),
            learned_ir_view_cross_entropy=_finite_float(
                data.get("learned_ir_view_cross_entropy"),
                _finite_float(
                    data.get("learned_ir_view_ce"),
                    _finite_float(learned.get("cross_entropy_loss")),
                ),
            ),
            learned_ir_view_cosine=_finite_float(
                data.get("learned_ir_view_cosine"),
                _finite_float(
                    data.get("learned_ir_view_cosine_similarity"),
                    _finite_float(learned.get("cosine_similarity"), 1.0),
                ),
            ),
            proof_validity=_finite_float(
                data.get("proof_validity"),
                _finite_float(
                    data.get("proofs_valid"),
                    1.0 if bool(validity.get("proofs_valid", True)) else 0.0,
                ),
            ),
            theorem_validity=_finite_float(
                data.get("theorem_validity"),
                _finite_float(
                    data.get("theorem_valid"),
                    _finite_float(
                        validity.get("theorem_validity"),
                        _finite_float(
                            validity.get("theorem_valid"),
                            _finite_float(
                                data.get("proof_validity"),
                                1.0
                                if bool(validity.get("proofs_valid", True))
                                else 0.0,
                            ),
                        ),
                    ),
                ),
            ),
            graph_validity=_finite_float(
                data.get("graph_validity"),
                _finite_float(
                    graph.get("valid"),
                    1.0
                    if int(_finite_float(graph.get("missing_endpoint_relationships"), 0.0))
                    == 0
                    else 0.0,
                ),
            ),
            anti_copy_penalty=_finite_float(
                data.get("anti_copy_penalty"),
                _finite_float(anti_copy.get("anti_copy_penalty")),
            ),
            provenance_validity=_finite_float(
                data.get("provenance_validity"),
                _finite_float(
                    data.get("provenance_valid"),
                    1.0
                    if bool(
                        _mapping(data.get("provenance")).get("valid")
                        or validity.get("provenance_valid", True)
                    )
                    else 0.0,
                ),
            ),
            mutation_validity=_finite_float(
                data.get("mutation_validity"),
                _finite_float(
                    data.get("mutation_valid"),
                    1.0
                    if bool(
                        _mapping(data.get("mutation")).get("valid")
                        or validity.get("mutation_valid", True)
                    )
                    else 0.0,
                ),
            ),
            validation_rejection_rate=_finite_float(
                data.get("validation_rejection_rate"),
                _finite_float(throughput.get("validation_rejection_rate")),
            ),
            task_to_accepted_patch_rate=_finite_float(
                data.get("task_to_accepted_patch_rate"),
                _finite_float(throughput.get("task_to_accepted_patch_rate")),
            ),
            cycle_time_seconds=_finite_float(
                data.get("cycle_time_seconds"),
                _finite_float(throughput.get("cycle_time_seconds")),
            ),
            state_to_patch_lag=_finite_float(
                data.get("state_to_patch_lag"),
                _finite_float(
                    data.get("state_to_accepted_patch_lag"),
                    _finite_float(throughput.get("state_to_patch_lag")),
                ),
            ),
            autoencoder_cycle_overhead=_finite_float(
                data.get("autoencoder_cycle_overhead"),
                _finite_float(
                    data.get("autoencoder_cycle_overhead_rate"),
                    _finite_float(throughput.get("autoencoder_cycle_overhead")),
                ),
            ),
            transient_execution_failure_rate=_finite_float(
                data.get("transient_execution_failure_rate"),
                _finite_float(
                    data.get("transient_failure_rate"),
                    _finite_float(throughput.get("transient_failure_rate")),
                ),
            ),
        )


@dataclass(frozen=True)
class MetricComparison:
    """One hard guardrail comparison between Leanstral and control arms."""

    metric: str
    leanstral: float
    control: float
    delta: float
    relative_improvement: float
    regressed: bool
    improved: bool
    direction: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "control": _stable_float(self.control),
            "delta": _stable_float(self.delta),
            "direction": self.direction,
            "improved": self.improved,
            "leanstral": _stable_float(self.leanstral),
            "metric": self.metric,
            "regressed": self.regressed,
            "relative_improvement": _stable_float(self.relative_improvement),
        }


@dataclass(frozen=True)
class IsolatedImplementationResult:
    """Observed isolated implementation outcome for one paired evaluation arm."""

    arm: str
    outcome: str
    isolated: bool
    locally_verified: bool
    accepted_patch: bool
    compiler_or_decompiler_patch: bool
    validation_commands: Sequence[str] = field(default_factory=tuple)
    validation_worktree: str = ""
    patch_id: str = ""
    transient_execution_failure_rate: float = 0.0
    autoencoder_cycle_overhead: float = 0.0
    state_to_accepted_patch_lag: float = 0.0
    guardrail_regressions: Sequence[str] = field(default_factory=tuple)
    source: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "accepted_patch": bool(self.accepted_patch),
            "arm": self.arm,
            "autoencoder_cycle_overhead": _stable_float(
                self.autoencoder_cycle_overhead
            ),
            "compiler_or_decompiler_patch": bool(self.compiler_or_decompiler_patch),
            "guardrail_regressions": list(self.guardrail_regressions),
            "isolated": bool(self.isolated),
            "locally_verified": bool(self.locally_verified),
            "outcome": self.outcome,
            "patch_id": self.patch_id,
            "source": _json_ready(self.source),
            "state_to_accepted_patch_lag": _stable_float(
                self.state_to_accepted_patch_lag
            ),
            "transient_execution_failure_rate": _stable_float(
                self.transient_execution_failure_rate
            ),
            "validation_commands": list(self.validation_commands),
            "validation_worktree": self.validation_worktree,
        }


@dataclass(frozen=True)
class SeededPairedTask:
    """One Leanstral TODO paired with a matched non-Leanstral control."""

    pair_id: str
    rank: int
    cluster_id: str
    semantic_family: str
    compiler_surface: str
    semantic_signature: str
    evidence_ids: Sequence[str]
    sample_ids: Sequence[str]
    verified: bool
    verification_reasons: Sequence[str]
    leanstral_task: Mapping[str, Any]
    control_task: Mapping[str, Any]
    leanstral_metrics: PairedEvaluationMetrics
    control_metrics: PairedEvaluationMetrics
    comparisons: Sequence[MetricComparison]
    leanstral_implementation: IsolatedImplementationResult
    control_implementation: IsolatedImplementationResult
    seeded: bool
    dry_run: bool
    audit_verified: bool
    guardrails: Mapping[str, Any]
    evidence_provenance: Mapping[str, Any]
    paired_metrics_provenance: Mapping[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "audit_verified": self.audit_verified,
            "cluster_id": self.cluster_id,
            "comparisons": [comparison.to_dict() for comparison in self.comparisons],
            "compiler_surface": self.compiler_surface,
            "control_metrics": self.control_metrics.to_dict(),
            "control_task": _json_ready(self.control_task),
            "dry_run": self.dry_run,
            "evidence_ids": list(self.evidence_ids),
            "evidence_provenance": _json_ready(self.evidence_provenance),
            "guardrails": _json_ready(self.guardrails),
            "control_implementation": self.control_implementation.to_dict(),
            "leanstral_metrics": self.leanstral_metrics.to_dict(),
            "leanstral_implementation": self.leanstral_implementation.to_dict(),
            "leanstral_task": _json_ready(self.leanstral_task),
            "pair_id": self.pair_id,
            "paired_metrics_provenance": _json_ready(self.paired_metrics_provenance),
            "rank": self.rank,
            "sample_ids": list(self.sample_ids),
            "seeded": self.seeded,
            "semantic_family": self.semantic_family,
            "semantic_signature": self.semantic_signature,
            "verification_reasons": list(self.verification_reasons),
            "verified": self.verified,
        }


@dataclass(frozen=True)
class SeedCanaryResult:
    """Full paired seed canary report and production promotion decision."""

    schema_version: str
    config: SeedCanaryConfig
    source_record_count: int
    selected_task_count: int
    verified_task_count: int
    seeded_task_count: int
    tasks: Sequence[SeededPairedTask]
    aggregate_comparisons: Mapping[str, MetricComparison]
    hard_guardrail_regressions: Sequence[str]
    throughput_materially_improved: bool
    throughput_improvement: float
    projected_throughput_improvement: float
    promotion_allowed: bool
    promotion_blockers: Sequence[str]
    todo_queue_path: str
    runtime_seconds: float
    dry_run_no_mutation: Mapping[str, Any]
    evidence_provenance_summary: Mapping[str, Any]
    paired_metrics_provenance_summary: Mapping[str, Any]
    shadow_summary: Mapping[str, Any]
    accepted_compiler_decompiler_patch_count: int
    isolated_implementation_summary: Mapping[str, Any]
    rollout_decision_summary: Mapping[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "accepted_compiler_decompiler_patch_count": int(
                self.accepted_compiler_decompiler_patch_count
            ),
            "aggregate_comparisons": {
                key: comparison.to_dict()
                for key, comparison in sorted(self.aggregate_comparisons.items())
            },
            "config": self.config.to_dict(),
            "dry_run_no_mutation": _json_ready(self.dry_run_no_mutation),
            "evidence_provenance_summary": _json_ready(self.evidence_provenance_summary),
            "hard_guardrail_regressions": list(self.hard_guardrail_regressions),
            "isolated_implementation_summary": _json_ready(
                self.isolated_implementation_summary
            ),
            "paired_metrics_provenance_summary": _json_ready(self.paired_metrics_provenance_summary),
            "promotion_allowed": self.promotion_allowed,
            "promotion_blockers": list(self.promotion_blockers),
            "projected_throughput_improvement": _stable_float(
                self.projected_throughput_improvement
            ),
            "runtime_seconds": _stable_float(self.runtime_seconds),
            "rollout_decision_summary": _json_ready(self.rollout_decision_summary),
            "schema_version": self.schema_version,
            "seeded_task_count": self.seeded_task_count,
            "selected_task_count": self.selected_task_count,
            "shadow_summary": _json_ready(self.shadow_summary),
            "source_record_count": self.source_record_count,
            "tasks": [task.to_dict() for task in self.tasks],
            "throughput_improvement": _stable_float(self.throughput_improvement),
            "throughput_materially_improved": self.throughput_materially_improved,
            "todo_queue_path": self.todo_queue_path,
            "verified_task_count": self.verified_task_count,
        }


def run_seed_canary(
    records: Sequence[Mapping[str, Any]],
    *,
    config: Optional[SeedCanaryConfig] = None,
    shadow_result: Optional[Any] = None,
) -> SeedCanaryResult:
    """Run the seed canary over ranked LegalIR disagreement records."""

    started = time.monotonic()
    cfg = config or SeedCanaryConfig()
    max_todos = cfg.bounded_max_todos()
    shadow = shadow_result or run_shadow_canary(
        records,
        config=ShadowCanaryConfig(
            max_clusters=max_todos,
            dry_run=cfg.dry_run,
            cache_dir=cfg.cache_dir,
            require_local_verifier=cfg.require_verified_audit_for_promotion,
            max_source_span_copy_ratio=cfg.max_source_span_copy_ratio,
            provider=cfg.provider,
            model=cfg.model,
            vibe_agent=cfg.vibe_agent,
            timeout_seconds=cfg.timeout_seconds,
        ),
    )
    records_by_evidence_id = _packet_index(records)
    tasks: List[SeededPairedTask] = []
    queue_payloads: List[Dict[str, Any]] = []
    for audit in shadow.audits[:max_todos]:
        cluster_records = [
            records_by_evidence_id[evidence_id]
            for evidence_id in audit.guardrails.get("cluster_evidence_ids", ())
            if evidence_id in records_by_evidence_id
        ]
        if not cluster_records:
            cluster_records = [
                records_by_evidence_id[evidence_id]
                for evidence_id in _extract_evidence_ids_from_audit(audit)
                if evidence_id in records_by_evidence_id
            ]
        if not cluster_records:
            cluster_records = list(records)
        task = _paired_task_from_shadow_audit(
            audit,
            records=cluster_records,
            config=cfg,
            rank=len(tasks) + 1,
        )
        seed_ready = task.verified and (
            cfg.dry_run or _task_has_required_isolated_implementations(task)
        )
        if seed_ready and len(queue_payloads) < max_todos:
            queue_payloads.append(dict(task.leanstral_task))
            tasks.append(
                SeededPairedTask(
                    **{
                        **task.__dict__,
                        "seeded": not cfg.dry_run,
                    }
                )
            )
        else:
            tasks.append(task)

    seeded_count = 0
    if queue_payloads and not cfg.dry_run:
        seeded_count = _append_todo_queue(queue_payloads, cfg.todo_queue_path)

    aggregate = _aggregate_comparisons(tasks)
    regressions = tuple(
        metric for metric, comparison in aggregate.items() if comparison.regressed
    )
    projected_throughput_improvement = _throughput_improvement(aggregate)
    observed_tasks = [
        task for task in tasks if _paired_metrics_observed_improvement_eligible(task)
    ]
    observed_aggregate = _aggregate_comparisons(observed_tasks)
    throughput_improvement = (
        _throughput_improvement(observed_aggregate) if observed_tasks else 0.0
    )
    throughput_materially_improved = (
        throughput_improvement >= float(cfg.material_throughput_improvement)
    )
    evidence_provenance_summary = _evidence_provenance_summary(tasks)
    paired_metrics_provenance_summary = _paired_metrics_provenance_summary(tasks)
    isolated_implementation_summary = _isolated_implementation_summary(tasks)
    rollout_decision_summary = _rollout_decision_summary(
        cfg,
        tasks=tasks,
        aggregate_comparisons=aggregate,
        isolated_implementation_summary=isolated_implementation_summary,
    )
    promotion_allowed, blockers = _promotion_decision(
        cfg,
        tasks=tasks,
        aggregate_comparisons=aggregate,
        regressions=regressions,
        throughput_materially_improved=throughput_materially_improved,
        selected_count=len(tasks),
        seeded_count=seeded_count if not cfg.dry_run else 0,
        evidence_provenance_summary=evidence_provenance_summary,
        paired_metrics_provenance_summary=paired_metrics_provenance_summary,
        isolated_implementation_summary=isolated_implementation_summary,
        rollout_decision_summary=rollout_decision_summary,
    )
    runtime = time.monotonic() - started
    return SeedCanaryResult(
        schema_version=SEED_CANARY_SCHEMA_VERSION,
        config=cfg,
        source_record_count=len(records),
        selected_task_count=len(tasks),
        verified_task_count=sum(1 for task in tasks if task.verified),
        seeded_task_count=seeded_count if not cfg.dry_run else 0,
        tasks=tuple(tasks),
        aggregate_comparisons=aggregate,
        hard_guardrail_regressions=regressions,
        throughput_materially_improved=throughput_materially_improved,
        throughput_improvement=throughput_improvement,
        projected_throughput_improvement=projected_throughput_improvement,
        promotion_allowed=promotion_allowed,
        promotion_blockers=tuple(blockers),
        todo_queue_path=str(cfg.todo_queue_path),
        runtime_seconds=runtime,
        dry_run_no_mutation={
            "dry_run": bool(cfg.dry_run),
            "queue_append_count": 0 if cfg.dry_run else seeded_count,
            "source_mutation_count": 0,
            "max_todos": max_todos,
            "verified_candidates": sum(1 for task in tasks if task.verified),
            "dry_run_non_production": bool(cfg.dry_run),
            "synthetic_metrics_are_projection_only": True,
        },
        evidence_provenance_summary=evidence_provenance_summary,
        paired_metrics_provenance_summary=paired_metrics_provenance_summary,
        shadow_summary={
            "audit_validity": dict(getattr(shadow, "audit_validity", {})),
            "cache_summary": dict(getattr(shadow, "cache_summary", {})),
            "evidence_provenance_summary": dict(
                getattr(shadow, "evidence_provenance_summary", {})
            ),
            "promotion_allowed": bool(getattr(shadow, "promotion_allowed", False)),
            "promotion_blockers": list(getattr(shadow, "promotion_blockers", ())),
            "selected_cluster_count": int(
                _finite_float(getattr(shadow, "selected_cluster_count", 0), 0.0)
            ),
        },
        accepted_compiler_decompiler_patch_count=int(
            rollout_decision_summary.get("accepted_compiler_decompiler_patch_count", 0)
        ),
        isolated_implementation_summary=isolated_implementation_summary,
        rollout_decision_summary=rollout_decision_summary,
    )


def write_markdown_report(result: SeedCanaryResult, path: str | Path) -> Path:
    """Write a human-readable paired seed canary report."""

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(render_markdown_report(result), encoding="utf-8")
    return target


def render_markdown_report(result: SeedCanaryResult) -> str:
    """Render the production promotion decision and paired evaluation."""

    payload = result.to_dict()
    lines = [
        "# Leanstral Real Seed Canary",
        "",
        f"- Schema: `{result.schema_version}`",
        f"- Mode: `{'dry-run' if result.config.dry_run else 'seed'}`",
        f"- Production evidence: `{'non-production dry run' if result.config.dry_run else 'seed promotion evidence'}`",
        f"- Selected tasks: {result.selected_task_count} of {result.source_record_count} source records",
        f"- Verified tasks: {result.verified_task_count}",
        f"- Seeded tasks: {result.seeded_task_count}",
        f"- Runtime seconds: {result.runtime_seconds:.6f}",
        f"- Production promotion allowed: `{str(result.promotion_allowed).lower()}`",
        f"- Observed throughput materially improved: `{str(result.throughput_materially_improved).lower()}` ({result.throughput_improvement:.6f})",
        f"- Synthetic/projected throughput improvement: `{result.projected_throughput_improvement:.6f}`",
    ]
    if result.promotion_blockers:
        lines.append(
            "- Promotion blockers: "
            + ", ".join(f"`{item}`" for item in result.promotion_blockers)
        )
    lines.extend(
        [
            "",
            "## Seeded Task Limit",
            f"- Maximum TODOs permitted: `{MAX_SEED_TODOS}`",
            f"- Configured maximum TODOs: `{result.config.max_todos}`",
            f"- Bounded selected TODOs: `{result.selected_task_count}`",
            f"- Queue path: `{result.todo_queue_path}`",
            "",
            "## Paired Evaluation Metrics",
            _markdown_comparisons(result.aggregate_comparisons),
            "",
            "## Evidence Provenance",
            _markdown_kv(result.evidence_provenance_summary),
            "",
            "## Paired Metrics Provenance",
            _markdown_kv(result.paired_metrics_provenance_summary),
            "",
            "## Isolated Implementation Evidence",
            _markdown_kv(result.isolated_implementation_summary),
            "",
            "## Hard Guardrails",
            _markdown_guardrails(result),
            "",
            "## Rollout Decision Gates",
            _markdown_kv(result.rollout_decision_summary),
            "",
            "## Throughput Decision",
            _markdown_kv(
                {
                    "material_threshold": result.config.material_throughput_improvement,
                    "observed_improvement": result.throughput_improvement,
                    "synthetic_projected_improvement": result.projected_throughput_improvement,
                    "throughput_materially_improved": result.throughput_materially_improved,
                }
            ),
            "",
            "## Task-To-Accepted-Patch Rate",
            _markdown_metric_line(result, "task_to_accepted_patch_rate"),
            "",
            "## Cycle Time",
            _markdown_metric_line(result, "cycle_time_seconds"),
            "",
            "## State-To-Accepted-Patch Lag",
            _markdown_metric_line(result, "state_to_patch_lag"),
            "",
            "## Rollback Commands",
            "```bash",
            "export LEANSTRAL_LEGAL_IR_MODE=off",
            "pkill -f 'run_leanstral_seed_canary.py' || true",
            f"python scripts/ops/legal_ir/run_leanstral_seed_canary.py --dry-run --max-todos {MAX_SEED_TODOS} --report-path docs/implementation/reports/leanstral_real_seed_canary.md",
            f"rm -f {result.todo_queue_path}",
            "```",
            "",
            "## Paired Tasks",
        ]
    )
    if not result.tasks:
        lines.append("")
        lines.append("No verified seed tasks were selected.")
    for task in result.tasks:
        lines.extend(
            [
                "",
                f"### {task.rank}. `{task.pair_id}`",
                f"- Cluster: `{task.cluster_id}`",
                f"- Surface: `{task.compiler_surface}`",
                f"- Family: `{task.semantic_family}`",
                f"- Verified: `{str(task.verified).lower()}`; seeded: `{str(task.seeded).lower()}`; audit verified: `{str(task.audit_verified).lower()}`",
                f"- Evidence provenance: `{task.evidence_provenance.get('dominant_kind', 'unknown_packet_provenance')}`; metrics: `{task.paired_metrics_provenance.get('kind', 'unknown_metrics')}`",
                f"- Isolated implementations: Leanstral `{str(task.leanstral_implementation.isolated and task.leanstral_implementation.locally_verified).lower()}`; control `{str(task.control_implementation.isolated and task.control_implementation.locally_verified).lower()}`",
                f"- Patch outcomes: Leanstral `{task.leanstral_implementation.outcome}`; control `{task.control_implementation.outcome}`",
                f"- Leanstral TODO: `{task.leanstral_task.get('todo_id', '')}`",
                f"- Control TODO: `{task.control_task.get('todo_id', '')}`",
                f"- Regressions: `{', '.join(_task_regressions(task)) or 'none'}`",
            ]
        )
    lines.extend(
        [
            "",
            "## Machine Readable Summary",
            "",
            "```json",
            json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True),
            "```",
            "",
        ]
    )
    return "\n".join(lines)


def _paired_task_from_shadow_audit(
    audit: Any,
    *,
    records: Sequence[Mapping[str, Any]],
    config: SeedCanaryConfig,
    rank: int,
) -> SeededPairedTask:
    record_evidence_ids = tuple(
        dict.fromkeys(
            _record_evidence_id(record)
            for record in records
            if _record_evidence_id(record)
        )
    )
    evidence_ids = record_evidence_ids or tuple(_extract_evidence_ids_from_audit(audit))
    sample_ids = tuple(_extract_sample_ids_from_audit(audit, records))
    leanstral_metrics, control_metrics, metrics_generated = _paired_metrics(
        audit,
        records=records,
        rank=rank,
    )
    leanstral_implementation = _isolated_implementation_result(
        records,
        arm="leanstral",
        metrics=leanstral_metrics,
        compiler_surface=str(getattr(audit, "compiler_surface", "") or ""),
    )
    control_implementation = _isolated_implementation_result(
        records,
        arm="control",
        metrics=control_metrics,
        compiler_surface=str(getattr(audit, "compiler_surface", "") or ""),
    )
    evidence_provenance = _mapping(getattr(audit, "evidence_provenance", {}))
    metrics_provenance = _paired_metrics_provenance(
        records,
        evidence_provenance=evidence_provenance,
        generated=metrics_generated,
        dry_run=config.dry_run,
    )
    comparisons = tuple(
        compare_metrics(
            leanstral_metrics,
            control_metrics,
            deadband=config.metric_deadband,
        ).values()
    )
    pair_id = "leanstral-seed-pair-" + canonical_sha256(
        {
            "cluster_id": audit.cluster_id,
            "evidence_ids": evidence_ids,
            "rank": rank,
            "schema_version": SEED_CANARY_SCHEMA_VERSION,
        }
    )[:16]
    leanstral_task = _build_task_payload(
        audit,
        pair_id=pair_id,
        arm="leanstral",
        evidence_ids=evidence_ids,
        sample_ids=sample_ids,
        rank=rank,
    )
    control_task = _build_task_payload(
        audit,
        pair_id=pair_id,
        arm="control",
        evidence_ids=evidence_ids,
        sample_ids=sample_ids,
        rank=rank,
    )
    verified, reasons = _verify_seed_task(
        audit,
        records=records,
        config=config,
        comparisons=comparisons,
    )
    return SeededPairedTask(
        pair_id=pair_id,
        rank=rank,
        cluster_id=audit.cluster_id,
        semantic_family=audit.semantic_family,
        compiler_surface=audit.compiler_surface,
        semantic_signature=audit.semantic_signature,
        evidence_ids=evidence_ids,
        sample_ids=sample_ids,
        verified=verified,
        verification_reasons=tuple(reasons),
        leanstral_task=leanstral_task,
        control_task=control_task,
        leanstral_metrics=leanstral_metrics,
        control_metrics=control_metrics,
        comparisons=comparisons,
        leanstral_implementation=leanstral_implementation,
        control_implementation=control_implementation,
        seeded=False,
        dry_run=config.dry_run,
        audit_verified=bool(audit.audit_verified),
        guardrails=audit.guardrails,
        evidence_provenance=evidence_provenance,
        paired_metrics_provenance=metrics_provenance,
    )


def compare_metrics(
    leanstral: PairedEvaluationMetrics,
    control: PairedEvaluationMetrics,
    *,
    deadband: float = 0.0,
) -> Dict[str, MetricComparison]:
    """Compare all hard guardrail metrics for a Leanstral/control pair."""

    left = leanstral.to_dict()
    right = control.to_dict()
    comparisons: Dict[str, MetricComparison] = {}
    for metric in HARD_GUARDRAIL_METRICS:
        lean_value = float(left[metric])
        control_value = float(right[metric])
        if metric in LOWER_IS_BETTER:
            delta = control_value - lean_value
            rel = delta / max(abs(control_value), 1.0e-12)
            regressed = lean_value > control_value + deadband
            improved = lean_value < control_value - deadband
            direction = "lower_is_better"
        else:
            delta = lean_value - control_value
            rel = delta / max(abs(control_value), 1.0e-12)
            regressed = lean_value < control_value - deadband
            improved = lean_value > control_value + deadband
            direction = "higher_is_better"
        comparisons[metric] = MetricComparison(
            metric=metric,
            leanstral=lean_value,
            control=control_value,
            delta=delta,
            relative_improvement=rel,
            regressed=regressed,
            improved=improved,
            direction=direction,
        )
    return comparisons


def _paired_metrics(
    audit: Any,
    *,
    records: Sequence[Mapping[str, Any]],
    rank: int,
) -> tuple[PairedEvaluationMetrics, PairedEvaluationMetrics, bool]:
    explicit_lean = _first_metrics(records, "leanstral")
    explicit_control = _first_metrics(records, "control")
    if explicit_lean is not None and explicit_control is not None:
        return explicit_lean, explicit_control, False

    rank_score = max(0.0, min(1.0, float(audit.rank_score)))
    impact = max(0.0, min(1.0, float(audit.heldout_impact)))
    recurrence = max(1.0, float(audit.recurrence or 1))
    control_ce = 0.32 + (1.0 - impact) * 0.18 + rank * 0.004
    control_cosine = 0.84 + impact * 0.08 - rank * 0.002
    control_learned_ce = 0.28 + (1.0 - rank_score) * 0.14 + rank * 0.003
    control_learned_cosine = 0.86 + rank_score * 0.08 - rank * 0.0015
    control_cycle = 1800.0 + rank * 210.0 + recurrence * 20.0
    control_lag = 3.0 + rank * 0.4
    control_patch_rate = 0.42 + min(0.18, impact * 0.14)
    improvement = 0.16 + rank_score * 0.08
    lean = PairedEvaluationMetrics(
        compiler_ir_cross_entropy=control_ce * (1.0 - 0.08 - rank_score * 0.03),
        compiler_ir_cosine=min(1.0, control_cosine + 0.012 + rank_score * 0.01),
        learned_ir_view_cross_entropy=control_learned_ce * (1.0 - 0.07 - impact * 0.03),
        learned_ir_view_cosine=min(1.0, control_learned_cosine + 0.01 + impact * 0.012),
        proof_validity=1.0,
        graph_validity=1.0,
        anti_copy_penalty=max(0.0, 0.004 + rank * 0.0004),
        validation_rejection_rate=max(0.0, 0.16 - rank_score * 0.05),
        task_to_accepted_patch_rate=min(1.0, control_patch_rate * (1.0 + improvement)),
        cycle_time_seconds=control_cycle * (1.0 - min(0.35, improvement)),
        state_to_patch_lag=max(0.0, control_lag * (1.0 - min(0.4, improvement))),
        theorem_validity=1.0,
        provenance_validity=1.0,
        mutation_validity=1.0,
        autoencoder_cycle_overhead=0.0,
        transient_execution_failure_rate=0.0,
    )
    control = PairedEvaluationMetrics(
        compiler_ir_cross_entropy=control_ce,
        compiler_ir_cosine=max(0.0, min(1.0, control_cosine)),
        learned_ir_view_cross_entropy=control_learned_ce,
        learned_ir_view_cosine=max(0.0, min(1.0, control_learned_cosine)),
        proof_validity=1.0,
        graph_validity=1.0,
        anti_copy_penalty=0.006 + rank * 0.0005,
        validation_rejection_rate=0.18,
        task_to_accepted_patch_rate=min(1.0, control_patch_rate),
        cycle_time_seconds=control_cycle,
        state_to_patch_lag=control_lag,
        theorem_validity=1.0,
        provenance_validity=1.0,
        mutation_validity=1.0,
        autoencoder_cycle_overhead=0.0,
        transient_execution_failure_rate=0.0,
    )
    return lean, control, True


def _paired_metrics_provenance(
    records: Sequence[Mapping[str, Any]],
    *,
    evidence_provenance: Mapping[str, Any],
    generated: bool,
    dry_run: bool,
) -> Dict[str, Any]:
    real_records = int(_finite_float(evidence_provenance.get("real_record_count"), 0.0))
    production_evidence = bool(evidence_provenance.get("production_eligible", False))
    synthetic_records = int(
        _finite_float(evidence_provenance.get("synthetic_fixture_record_count"), 0.0)
    )
    if generated:
        kind = "synthetic_projection"
        observed_eligible = False
    elif synthetic_records > 0 or real_records == 0:
        kind = "synthetic_fixture_paired_metrics"
        observed_eligible = False
    elif dry_run:
        kind = "dry_run_cached_pair_metrics"
        observed_eligible = False
    elif production_evidence and real_records > 0:
        kind = "observed_real_paired_metrics"
        observed_eligible = True
    else:
        kind = "real_metrics_without_provider_or_verified_cache"
        observed_eligible = False
    return {
        "kind": kind,
        "metric_record_count": len(records),
        "observed_improvement_eligible": observed_eligible,
        "production_evidence_eligible": bool(production_evidence),
        "synthetic_projection": bool(generated or synthetic_records > 0),
    }


def _first_metrics(
    records: Sequence[Mapping[str, Any]],
    arm: str,
) -> Optional[PairedEvaluationMetrics]:
    for record in records:
        candidates = (
            _mapping(record.get(f"{arm}_metrics")),
            _mapping(_mapping(record.get("paired_evaluation")).get(arm)),
            _mapping(_mapping(record.get("paired_metrics")).get(arm)),
        )
        for candidate in candidates:
            if candidate:
                return PairedEvaluationMetrics.from_mapping(candidate)
    return None


def _isolated_implementation_result(
    records: Sequence[Mapping[str, Any]],
    *,
    arm: str,
    metrics: PairedEvaluationMetrics,
    compiler_surface: str,
) -> IsolatedImplementationResult:
    data = _first_implementation_record(records, arm)
    if not data:
        return IsolatedImplementationResult(
            arm=arm,
            outcome="missing",
            isolated=False,
            locally_verified=False,
            accepted_patch=False,
            compiler_or_decompiler_patch=False,
            transient_execution_failure_rate=metrics.transient_execution_failure_rate,
            autoencoder_cycle_overhead=metrics.autoencoder_cycle_overhead,
            state_to_accepted_patch_lag=metrics.state_to_patch_lag,
            guardrail_regressions=("missing_isolated_implementation",),
        )

    metadata = _mapping(data.get("metadata"))
    validation = _mapping(data.get("validation") or data.get("validation_report"))
    outcome = str(
        data.get("outcome")
        or data.get("patch_outcome")
        or data.get("leanstral_patch_outcome")
        or metadata.get("leanstral_patch_outcome")
        or metadata.get("patch_outcome")
        or ""
    ).strip()
    accepted = bool(
        data.get("accepted_patch")
        or data.get("patch_accepted")
        or outcome == "accepted_improvement"
    )
    worktree = str(
        data.get("validation_worktree")
        or data.get("isolated_worktree")
        or data.get("worktree_path")
        or validation.get("validation_worktree")
        or ""
    )
    isolated = bool(
        data.get("actual_isolated_implementation")
        or data.get("isolated")
        or data.get("isolation_verified")
        or worktree
    )
    locally_verified = bool(
        data.get("locally_verified")
        or data.get("local_validation_passed")
        or data.get("local_verifier_accepted")
        or validation.get("accepted")
        or validation.get("local_validation_passed")
        or validation.get("status") == "passed"
    )
    surface_text = " ".join(
        [
            compiler_surface,
            str(data.get("compiler_surface") or ""),
            str(data.get("target_component") or ""),
            str(data.get("patch_scope") or ""),
            str(metadata.get("target_component") or ""),
            " ".join(_sequence_strings(data.get("allowed_paths"))),
            " ".join(_sequence_strings(metadata.get("allowed_paths"))),
        ]
    ).lower()
    compiler_or_decompiler = bool(
        data.get("compiler_or_decompiler_patch")
        or data.get("compiler_patch")
        or data.get("decompiler_patch")
        or "compiler" in surface_text
        or "decompiler" in surface_text
    )
    transient_rate = _implementation_rate(
        data,
        validation,
        direct_keys=("transient_execution_failure_rate", "transient_failure_rate"),
        count_keys=("transient_failure_count", "transient_execution_failure_count"),
        total_keys=("execution_count", "attempt_count", "task_count"),
        default=metrics.transient_execution_failure_rate,
    )
    overhead = _finite_float(
        data.get("autoencoder_cycle_overhead"),
        _finite_float(
            data.get("autoencoder_cycle_overhead_rate"),
            _finite_float(
                validation.get("autoencoder_cycle_overhead"),
                metrics.autoencoder_cycle_overhead,
            ),
        ),
    )
    regressions = _implementation_regressions(data, validation)
    return IsolatedImplementationResult(
        arm=arm,
        outcome=outcome or ("accepted_improvement" if accepted else "unknown"),
        isolated=isolated,
        locally_verified=locally_verified,
        accepted_patch=accepted,
        compiler_or_decompiler_patch=compiler_or_decompiler,
        validation_commands=tuple(
            _sequence_strings(data.get("validation_commands"))
            or _sequence_strings(metadata.get("validation_commands"))
        ),
        validation_worktree=worktree,
        patch_id=str(data.get("patch_id") or data.get("commit") or ""),
        transient_execution_failure_rate=transient_rate,
        autoencoder_cycle_overhead=overhead,
        state_to_accepted_patch_lag=_finite_float(
            data.get("state_to_accepted_patch_lag"),
            _finite_float(
                data.get("state_to_patch_lag"),
                _finite_float(
                    validation.get("state_to_accepted_patch_lag"),
                    metrics.state_to_patch_lag,
                ),
            ),
        ),
        guardrail_regressions=regressions,
        source=data,
    )


def _first_implementation_record(
    records: Sequence[Mapping[str, Any]],
    arm: str,
) -> Dict[str, Any]:
    for record in records:
        paired = _mapping(record.get("isolated_implementations"))
        candidates = (
            _mapping(record.get(f"{arm}_implementation")),
            _mapping(record.get(f"{arm}_implementation_outcome")),
            _mapping(paired.get(arm)),
            _mapping(_mapping(record.get("paired_implementations")).get(arm)),
            _mapping(_mapping(record.get("implementation_outcomes")).get(arm)),
            _mapping(_mapping(record.get("paired_evaluation")).get(f"{arm}_implementation")),
            _mapping(_mapping(_mapping(record.get("paired_evaluation")).get(arm)).get("implementation")),
        )
        for candidate in candidates:
            if candidate:
                return candidate
    return {}


def _implementation_rate(
    data: Mapping[str, Any],
    validation: Mapping[str, Any],
    *,
    direct_keys: Sequence[str],
    count_keys: Sequence[str],
    total_keys: Sequence[str],
    default: float,
) -> float:
    for key in direct_keys:
        if key in data:
            return _finite_float(data.get(key), default)
        if key in validation:
            return _finite_float(validation.get(key), default)
    count = None
    total = None
    for key in count_keys:
        if key in data or key in validation:
            count = _finite_float(data.get(key), _finite_float(validation.get(key)))
            break
    for key in total_keys:
        if key in data or key in validation:
            total = _finite_float(data.get(key), _finite_float(validation.get(key)))
            break
    if count is not None and total and total > 0:
        return count / total
    return default


def _implementation_regressions(
    data: Mapping[str, Any],
    validation: Mapping[str, Any],
) -> tuple[str, ...]:
    regressions: List[str] = []
    for value in data.get("guardrail_regressions", ()) or ():
        if str(value).strip():
            regressions.append(str(value).strip())
    for value in validation.get("guardrail_regressions", ()) or ():
        if str(value).strip():
            regressions.append(str(value).strip())
    aliases = {
        "theorem": ("theorem_regressed", "proof_regressed"),
        "graph": ("graph_regressed",),
        "provenance": ("provenance_regressed",),
        "anti_copy": ("anti_copy_regressed",),
        "mutation": ("mutation_regressed",),
    }
    for name, keys in aliases.items():
        if any(bool(data.get(key) or validation.get(key)) for key in keys):
            regressions.append(f"{name}_regressed")
    return tuple(dict.fromkeys(regressions))


def _build_task_payload(
    audit: Any,
    *,
    pair_id: str,
    arm: str,
    evidence_ids: Sequence[str],
    sample_ids: Sequence[str],
    rank: int,
) -> Dict[str, Any]:
    projected = audit.projected_todo
    todo_id = f"{pair_id}-{arm}"
    return {
        "schema_version": "legal-ir-leanstral-seed-todo-v1",
        "todo_id": todo_id,
        "pair_id": pair_id,
        "arm": arm,
        "rank": rank,
        "source": "leanstral_seed_canary" if arm == "leanstral" else "matched_control",
        "cluster_id": audit.cluster_id,
        "semantic_family": audit.semantic_family,
        "compiler_surface": audit.compiler_surface,
        "semantic_signature": audit.semantic_signature,
        "action": projected.action,
        "target_component": projected.target_component,
        "allowed_paths": list(projected.allowed_paths),
        "target_metrics": list(projected.target_metrics),
        "theorem_templates": list(projected.theorem_templates),
        "mutation_cases": list(projected.mutation_cases),
        "validation_commands": list(projected.validation_commands),
        "evidence_ids": list(evidence_ids),
        "sample_ids": list(sample_ids),
        "dedup_key": f"{projected.dedup_key}-{arm}",
        "requires_local_validation": True,
        "leanstral_enabled": arm == "leanstral",
    }


def _verify_seed_task(
    audit: Any,
    *,
    records: Sequence[Mapping[str, Any]],
    config: SeedCanaryConfig,
    comparisons: Sequence[MetricComparison],
) -> tuple[bool, List[str]]:
    reasons: List[str] = []
    if not records:
        reasons.append("missing_matched_evidence_packets")
    for code in SHADOW_GUARDRAIL_CODES:
        guardrail = _mapping(audit.guardrails.get(code))
        if code == "verifier" and config.dry_run:
            continue
        if not bool(guardrail.get("passed", False)):
            reasons.append(f"{code}_guardrail_not_satisfied")
    if config.require_verified_audit_for_promotion and not config.dry_run and not audit.audit_verified:
        reasons.append("leanstral_audit_not_verified")
    if audit.projected_todo.specificity_score < 1.0:
        reasons.append("projected_todo_specificity_incomplete")
    for comparison in comparisons:
        if comparison.metric in {"proof_validity", "graph_validity"} and comparison.regressed:
            reasons.append(f"{comparison.metric}_regressed")
    return not reasons, sorted(set(reasons))


def _aggregate_comparisons(
    tasks: Sequence[SeededPairedTask],
) -> Dict[str, MetricComparison]:
    if not tasks:
        zero = PairedEvaluationMetrics(
            compiler_ir_cross_entropy=0.0,
            compiler_ir_cosine=0.0,
            learned_ir_view_cross_entropy=0.0,
            learned_ir_view_cosine=0.0,
            proof_validity=0.0,
            graph_validity=0.0,
            anti_copy_penalty=0.0,
            validation_rejection_rate=0.0,
            task_to_accepted_patch_rate=0.0,
            cycle_time_seconds=0.0,
            state_to_patch_lag=0.0,
            theorem_validity=0.0,
            provenance_validity=0.0,
            mutation_validity=0.0,
            autoencoder_cycle_overhead=0.0,
            transient_execution_failure_rate=0.0,
        )
        return compare_metrics(zero, zero)

    lean_mean = _mean_metrics([task.leanstral_metrics for task in tasks])
    control_mean = _mean_metrics([task.control_metrics for task in tasks])
    return compare_metrics(lean_mean, control_mean)


def _mean_metrics(metrics: Sequence[PairedEvaluationMetrics]) -> PairedEvaluationMetrics:
    values = [metric.to_dict() for metric in metrics]

    def mean(key: str) -> float:
        return sum(float(value[key]) for value in values) / len(values)

    return PairedEvaluationMetrics(
        compiler_ir_cross_entropy=mean("compiler_ir_cross_entropy"),
        compiler_ir_cosine=mean("compiler_ir_cosine"),
        learned_ir_view_cross_entropy=mean("learned_ir_view_cross_entropy"),
        learned_ir_view_cosine=mean("learned_ir_view_cosine"),
        proof_validity=mean("proof_validity"),
        graph_validity=mean("graph_validity"),
        anti_copy_penalty=mean("anti_copy_penalty"),
        validation_rejection_rate=mean("validation_rejection_rate"),
        task_to_accepted_patch_rate=mean("task_to_accepted_patch_rate"),
        cycle_time_seconds=mean("cycle_time_seconds"),
        state_to_patch_lag=mean("state_to_patch_lag"),
        theorem_validity=mean("theorem_validity"),
        provenance_validity=mean("provenance_validity"),
        mutation_validity=mean("mutation_validity"),
        autoencoder_cycle_overhead=mean("autoencoder_cycle_overhead"),
        transient_execution_failure_rate=mean("transient_execution_failure_rate"),
    )


def _throughput_improvement(comparisons: Mapping[str, MetricComparison]) -> float:
    if not comparisons:
        return 0.0
    values = [
        max(0.0, float(comparisons[metric].relative_improvement))
        for metric in THROUGHPUT_METRICS
        if metric in comparisons
    ]
    return sum(values) / len(values) if values else 0.0


def _promotion_decision(
    config: SeedCanaryConfig,
    *,
    tasks: Sequence[SeededPairedTask],
    aggregate_comparisons: Mapping[str, MetricComparison],
    regressions: Sequence[str],
    throughput_materially_improved: bool,
    selected_count: int,
    seeded_count: int,
    evidence_provenance_summary: Mapping[str, Any],
    paired_metrics_provenance_summary: Mapping[str, Any],
    isolated_implementation_summary: Mapping[str, Any],
    rollout_decision_summary: Mapping[str, Any],
) -> tuple[bool, List[str]]:
    blockers: List[str] = []
    if selected_count == 0:
        blockers.append("no_seed_tasks_selected")
    if selected_count > MAX_SEED_TODOS:
        blockers.append("seed_task_limit_exceeded")
    if config.dry_run:
        blockers.append("dry_run_no_production_promotion")
    if seeded_count <= 0:
        blockers.append("no_seeded_tasks")
    if int(_finite_float(evidence_provenance_summary.get("real_record_count"), 0.0)) <= 0:
        blockers.append("no_real_evidence_records")
    if int(_finite_float(evidence_provenance_summary.get("provider_or_verified_cache_task_count"), 0.0)) <= 0:
        blockers.append("no_provider_or_verified_cache_evidence")
    if int(_finite_float(evidence_provenance_summary.get("verifier_passed_task_count"), 0.0)) <= 0:
        blockers.append("no_verifier_evidence")
    if int(_finite_float(paired_metrics_provenance_summary.get("observed_improvement_task_count"), 0.0)) <= 0:
        blockers.append("no_observed_paired_metrics")
    if config.require_actual_isolated_implementations:
        actual_arms = int(
            _finite_float(
                isolated_implementation_summary.get(
                    "actual_isolated_implementation_arm_count"
                ),
                0.0,
            )
        )
        required_arms = int(
            _finite_float(
                isolated_implementation_summary.get(
                    "required_isolated_implementation_arm_count"
                ),
                0.0,
            )
        )
        if required_arms <= 0 or actual_arms < required_arms:
            blockers.append("actual_isolated_implementations_missing")
    if not bool(
        rollout_decision_summary.get(
            "accepted_compiler_decompiler_patch_requirement_met", False
        )
    ):
        blockers.append("no_accepted_compiler_decompiler_patch")
    if not bool(
        rollout_decision_summary.get(
            "task_to_accepted_patch_rate_requirement_met", False
        )
    ):
        blockers.append("task_to_accepted_patch_rate_improvement_below_20_percent")
    if not bool(
        rollout_decision_summary.get(
            "state_to_accepted_patch_lag_requirement_met", False
        )
    ):
        blockers.append("state_to_accepted_patch_lag_reduction_below_25_percent")
    if not bool(
        rollout_decision_summary.get(
            "frozen_holdout_metrics_non_regressing", False
        )
    ):
        blockers.append("frozen_holdout_metric_regression")
    if not bool(
        rollout_decision_summary.get("non_metric_guardrails_non_regressing", False)
    ):
        blockers.append("theorem_graph_provenance_anti_copy_or_mutation_regression")
    if not bool(
        rollout_decision_summary.get(
            "autoencoder_cycle_overhead_requirement_met", False
        )
    ):
        blockers.append("autoencoder_cycle_overhead_at_or_above_10_percent")
    if not bool(
        rollout_decision_summary.get(
            "transient_execution_failure_requirement_met", False
        )
    ):
        blockers.append("transient_execution_failure_rate_at_or_above_5_percent")
    if regressions:
        blockers.extend(f"{metric}_regressed" for metric in regressions)
    if any(not task.verified for task in tasks):
        blockers.append("unverified_seed_task")
    if not throughput_materially_improved:
        blockers.append("compiler_development_throughput_not_materially_improved")
    if config.require_verified_audit_for_promotion and not config.dry_run:
        if any(not task.audit_verified for task in tasks):
            blockers.append("leanstral_audit_not_verified")
    missing = [
        metric
        for metric in HARD_GUARDRAIL_METRICS
        if metric not in aggregate_comparisons
    ]
    if missing:
        blockers.append("paired_metric_coverage_incomplete")
    return not blockers, sorted(set(blockers))


def _evidence_provenance_summary(tasks: Sequence[SeededPairedTask]) -> Dict[str, Any]:
    kind_counts: Counter[str] = Counter()
    real_record_count = 0
    synthetic_record_count = 0
    provider_or_verified_cache_count = 0
    verifier_passed_count = 0
    production_eligible_count = 0
    seeded_production_eligible_count = 0
    for task in tasks:
        provenance = _mapping(task.evidence_provenance)
        for kind, count in _mapping(provenance.get("packet_kind_counts")).items():
            kind_counts[str(kind)] += int(_finite_float(count, 0.0))
        real_record_count += int(_finite_float(provenance.get("real_record_count"), 0.0))
        synthetic_record_count += int(_finite_float(provenance.get("synthetic_fixture_record_count"), 0.0))
        if bool(provenance.get("provider_or_verified_cache", False)):
            provider_or_verified_cache_count += 1
        verifier = _mapping(task.guardrails.get("verifier"))
        if bool(verifier.get("passed", False)):
            verifier_passed_count += 1
        if bool(provenance.get("production_eligible", False)):
            production_eligible_count += 1
            if task.seeded:
                seeded_production_eligible_count += 1
    return {
        "packet_kind_counts": dict(sorted(kind_counts.items())),
        "production_eligible_task_count": production_eligible_count,
        "provider_or_verified_cache_task_count": provider_or_verified_cache_count,
        "real_record_count": real_record_count,
        "seeded_production_eligible_task_count": seeded_production_eligible_count,
        "synthetic_fixture_record_count": synthetic_record_count,
        "verifier_passed_task_count": verifier_passed_count,
    }


def _paired_metrics_provenance_summary(tasks: Sequence[SeededPairedTask]) -> Dict[str, Any]:
    counts = Counter(
        str(_mapping(task.paired_metrics_provenance).get("kind") or "unknown_metrics")
        for task in tasks
    )
    observed_count = sum(
        1
        for task in tasks
        if _paired_metrics_observed_improvement_eligible(task)
    )
    synthetic_projection_count = sum(
        1
        for task in tasks
        if bool(_mapping(task.paired_metrics_provenance).get("synthetic_projection", False))
    )
    return {
        "metric_kind_counts": dict(sorted(counts.items())),
        "observed_improvement_task_count": observed_count,
        "synthetic_projection_task_count": synthetic_projection_count,
        "synthetic_metrics_reported_as_observed": False,
    }


def _isolated_implementation_summary(tasks: Sequence[SeededPairedTask]) -> Dict[str, Any]:
    arms: List[IsolatedImplementationResult] = []
    for task in tasks:
        arms.extend([task.leanstral_implementation, task.control_implementation])
    leanstral_arms = [task.leanstral_implementation for task in tasks]
    control_arms = [task.control_implementation for task in tasks]
    regressions = sorted(
        {
            regression
            for arm in arms
            for regression in arm.guardrail_regressions
            if regression != "missing_isolated_implementation"
        }
    )
    missing_count = sum(
        1
        for arm in arms
        if "missing_isolated_implementation" in arm.guardrail_regressions
    )
    return {
        "actual_isolated_implementation_arm_count": sum(
            1 for arm in arms if arm.isolated and arm.locally_verified
        ),
        "accepted_compiler_decompiler_patch_count": sum(
            1
            for arm in leanstral_arms
            if arm.accepted_patch and arm.compiler_or_decompiler_patch
        ),
        "control_accepted_patch_count": sum(1 for arm in control_arms if arm.accepted_patch),
        "guardrail_regressions": regressions,
        "leanstral_accepted_patch_count": sum(
            1 for arm in leanstral_arms if arm.accepted_patch
        ),
        "max_autoencoder_cycle_overhead": max(
            [arm.autoencoder_cycle_overhead for arm in leanstral_arms] or [0.0]
        ),
        "max_transient_execution_failure_rate": max(
            [arm.transient_execution_failure_rate for arm in arms] or [0.0]
        ),
        "missing_isolated_implementation_arm_count": missing_count,
        "required_isolated_implementation_arm_count": len(tasks) * 2,
        "task_count": len(tasks),
    }


def _rollout_decision_summary(
    config: SeedCanaryConfig,
    *,
    tasks: Sequence[SeededPairedTask],
    aggregate_comparisons: Mapping[str, MetricComparison],
    isolated_implementation_summary: Mapping[str, Any],
) -> Dict[str, Any]:
    task_rate = aggregate_comparisons.get("task_to_accepted_patch_rate")
    state_lag = aggregate_comparisons.get("state_to_patch_lag")
    lean_autoencoder_overheads = [
        task.leanstral_metrics.autoencoder_cycle_overhead for task in tasks
    ]
    lean_transient_rates = [
        task.leanstral_metrics.transient_execution_failure_rate for task in tasks
    ]
    autoencoder_cycle_overhead = (
        sum(lean_autoencoder_overheads) / len(lean_autoencoder_overheads)
        if lean_autoencoder_overheads
        else 0.0
    )
    autoencoder_cycle_overhead = max(
        autoencoder_cycle_overhead,
        _finite_float(
            isolated_implementation_summary.get("max_autoencoder_cycle_overhead"),
            0.0,
        ),
    )
    transient_execution_failure_rate = (
        sum(lean_transient_rates) / len(lean_transient_rates)
        if lean_transient_rates
        else 0.0
    )
    transient_execution_failure_rate = max(
        transient_execution_failure_rate,
        _finite_float(
            isolated_implementation_summary.get(
                "max_transient_execution_failure_rate"
            ),
            0.0,
        ),
    )
    frozen_metrics = (
        "compiler_ir_cross_entropy",
        "compiler_ir_cosine",
        "learned_ir_view_cross_entropy",
        "learned_ir_view_cosine",
    )
    non_metric_guardrails = (
        "theorem_validity",
        "proof_validity",
        "graph_validity",
        "provenance_validity",
        "anti_copy_penalty",
        "mutation_validity",
    )
    frozen_regressions = tuple(
        metric
        for metric in frozen_metrics
        if metric in aggregate_comparisons and aggregate_comparisons[metric].regressed
    )
    guardrail_regressions = tuple(
        metric
        for metric in non_metric_guardrails
        if metric in aggregate_comparisons and aggregate_comparisons[metric].regressed
    )
    implementation_regressions = tuple(
        str(item)
        for item in isolated_implementation_summary.get("guardrail_regressions", ())
        or ()
    )
    actual_arms = int(
        _finite_float(
            isolated_implementation_summary.get(
                "actual_isolated_implementation_arm_count"
            ),
            0.0,
        )
    )
    required_arms = int(
        _finite_float(
            isolated_implementation_summary.get(
                "required_isolated_implementation_arm_count"
            ),
            0.0,
        )
    )
    accepted_patches = int(
        _finite_float(
            isolated_implementation_summary.get(
                "accepted_compiler_decompiler_patch_count"
            ),
            0.0,
        )
    )
    return {
        "accepted_compiler_decompiler_patch_count": accepted_patches,
        "accepted_compiler_decompiler_patch_requirement_met": (
            accepted_patches >= int(config.min_accepted_compiler_patches)
        ),
        "actual_isolated_implementation_arm_count": actual_arms,
        "actual_isolated_implementation_requirement_met": (
            actual_arms >= required_arms and required_arms > 0
        ),
        "autoencoder_cycle_overhead": _stable_float(
            autoencoder_cycle_overhead
        ),
        "autoencoder_cycle_overhead_requirement_met": (
            autoencoder_cycle_overhead < float(config.max_autoencoder_cycle_overhead)
        ),
        "frozen_holdout_metric_regressions": list(frozen_regressions),
        "frozen_holdout_metrics_non_regressing": not frozen_regressions,
        "implementation_guardrail_regressions": list(implementation_regressions),
        "max_autoencoder_cycle_overhead": float(config.max_autoencoder_cycle_overhead),
        "max_transient_execution_failure_rate": float(
            config.max_transient_execution_failure_rate
        ),
        "min_accepted_compiler_patches": int(config.min_accepted_compiler_patches),
        "min_state_accepted_patch_lag_reduction": float(
            config.min_state_accepted_patch_lag_reduction
        ),
        "min_task_accepted_patch_rate_improvement": float(
            config.min_task_accepted_patch_rate_improvement
        ),
        "non_metric_guardrail_regressions": list(
            dict.fromkeys((*guardrail_regressions, *implementation_regressions))
        ),
        "non_metric_guardrails_non_regressing": not guardrail_regressions
        and not implementation_regressions,
        "required_isolated_implementation_arm_count": required_arms,
        "state_to_accepted_patch_lag_relative_reduction": _stable_float(
            state_lag.relative_improvement if state_lag is not None else 0.0
        ),
        "state_to_accepted_patch_lag_requirement_met": (
            (state_lag.relative_improvement if state_lag is not None else 0.0)
            >= float(config.min_state_accepted_patch_lag_reduction)
        ),
        "task_to_accepted_patch_rate_relative_improvement": _stable_float(
            task_rate.relative_improvement if task_rate is not None else 0.0
        ),
        "task_to_accepted_patch_rate_requirement_met": (
            (task_rate.relative_improvement if task_rate is not None else 0.0)
            >= float(config.min_task_accepted_patch_rate_improvement)
        ),
        "transient_execution_failure_rate": _stable_float(
            transient_execution_failure_rate
        ),
        "transient_execution_failure_requirement_met": (
            transient_execution_failure_rate
            < float(config.max_transient_execution_failure_rate)
        ),
    }


def _paired_metrics_observed_improvement_eligible(task: SeededPairedTask) -> bool:
    return bool(
        _mapping(task.paired_metrics_provenance).get("observed_improvement_eligible", False)
    )


def _task_has_required_isolated_implementations(task: SeededPairedTask) -> bool:
    return bool(
        task.leanstral_implementation.isolated
        and task.leanstral_implementation.locally_verified
        and task.control_implementation.isolated
        and task.control_implementation.locally_verified
    )


def _append_todo_queue(payloads: Sequence[Mapping[str, Any]], path: str | Path) -> int:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as handle:
        for payload in payloads[:MAX_SEED_TODOS]:
            handle.write(json.dumps(payload, ensure_ascii=True, sort_keys=True) + "\n")
    return min(len(payloads), MAX_SEED_TODOS)


def _packet_index(records: Sequence[Mapping[str, Any]]) -> Dict[str, Mapping[str, Any]]:
    index: Dict[str, Mapping[str, Any]] = {}
    for record in records:
        evidence_id = _record_evidence_id(record)
        if evidence_id:
            index[evidence_id] = record
    return index


def _record_evidence_id(record: Mapping[str, Any]) -> str:
    return str(
        record.get("evidence_id")
        or _mapping(record.get("payload")).get("evidence_id")
        or ""
    ).strip()


def _extract_evidence_ids_from_audit(audit: Any) -> tuple[str, ...]:
    evidence_ids: List[str] = []
    projected = getattr(audit, "projected_todo", None)
    guardrails = _mapping(getattr(audit, "guardrails", {}))
    for value in guardrails.get("evidence_ids", ()) or ():
        if str(value).strip():
            evidence_ids.append(str(value).strip())
    cluster_id = str(getattr(audit, "cluster_id", "") or "")
    if not evidence_ids and cluster_id:
        evidence_ids.append(cluster_id)
    dedup_key = str(getattr(projected, "dedup_key", "") or "")
    if dedup_key:
        evidence_ids.append(dedup_key)
    return tuple(dict.fromkeys(evidence_ids))


def _extract_sample_ids_from_audit(
    audit: Any,
    records: Sequence[Mapping[str, Any]],
) -> tuple[str, ...]:
    sample_ids: List[str] = []
    for record in records:
        hashes = _mapping(record.get("sample_hashes"))
        sample_id = str(hashes.get("sample_id") or record.get("sample_id") or "")
        if sample_id:
            sample_ids.append(sample_id)
    if not sample_ids:
        signature = str(getattr(audit, "semantic_signature", "") or "")
        sample_ids.append("seed-canary-" + canonical_sha256(signature)[:12])
    return tuple(dict.fromkeys(sample_ids))


def _markdown_comparisons(comparisons: Mapping[str, MetricComparison]) -> str:
    if not comparisons:
        return "- none"
    lines = [
        "| metric | Leanstral | control | relative improvement | regressed |",
        "| --- | ---: | ---: | ---: | --- |",
    ]
    for metric in HARD_GUARDRAIL_METRICS:
        comparison = comparisons.get(metric)
        if comparison is None:
            continue
        lines.append(
            f"| `{metric}` | {comparison.leanstral:.6f} | {comparison.control:.6f} | {comparison.relative_improvement:.6f} | `{str(comparison.regressed).lower()}` |"
        )
    return "\n".join(lines)


def _markdown_guardrails(result: SeedCanaryResult) -> str:
    values = {
        "hard_guardrail_regressions": list(result.hard_guardrail_regressions),
        "verified_task_count": result.verified_task_count,
        "selected_task_count": result.selected_task_count,
        "promotion_allowed": result.promotion_allowed,
    }
    guardrail_counts = Counter()
    for task in result.tasks:
        for code in SHADOW_GUARDRAIL_CODES:
            guardrail = _mapping(task.guardrails.get(code))
            if bool(guardrail.get("passed", False)) or (code == "verifier" and result.config.dry_run):
                guardrail_counts[f"{code}_passed"] += 1
            else:
                guardrail_counts[f"{code}_failed"] += 1
    values.update(dict(sorted(guardrail_counts.items())))
    return _markdown_kv(values)


def _markdown_metric_line(result: SeedCanaryResult, metric: str) -> str:
    comparison = result.aggregate_comparisons.get(metric)
    if comparison is None:
        return "- none"
    return (
        f"- Leanstral `{comparison.leanstral:.6f}` vs control "
        f"`{comparison.control:.6f}`; relative improvement "
        f"`{comparison.relative_improvement:.6f}`; regressed "
        f"`{str(comparison.regressed).lower()}`"
    )


def _markdown_kv(values: Mapping[str, Any]) -> str:
    if not values:
        return "- none"
    return "\n".join(
        f"- `{key}`: {json.dumps(_json_ready(value), ensure_ascii=True, sort_keys=True)}"
        for key, value in sorted(values.items())
    )


def _task_regressions(task: SeededPairedTask) -> tuple[str, ...]:
    return tuple(comparison.metric for comparison in task.comparisons if comparison.regressed)


def _sequence_strings(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, Mapping):
        return [str(key) for key in value.keys() if str(key).strip()]
    try:
        return [str(item) for item in value if str(item).strip()]
    except TypeError:
        text = str(value).strip()
        return [text] if text else []


def _mapping(value: Any) -> Dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _finite_float(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _stable_float(value: float) -> float:
    return round(float(value), 6)


def _json_ready(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_ready(item) for item in value]
    if isinstance(value, (str, int, bool)) or value is None:
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else 0.0
    return str(value)


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        action="append",
        default=[],
        help=(
            "JSON/JSONL packet file or directory; use 'latest' for the newest "
            "workspace/test-logs/*.canonical-disagreements.jsonl export."
        ),
    )
    parser.add_argument("--max-todos", type=int, default=MAX_SEED_TODOS)
    parser.add_argument("--cache-dir", default="", help="Leanstral audit cache directory")
    parser.add_argument("--report-path", default=str(DEFAULT_REPORT_PATH))
    parser.add_argument("--todo-queue-path", default=str(DEFAULT_TODO_QUEUE_PATH))
    parser.add_argument("--dry-run", action="store_true", help="Do not append TODOs or allow production promotion")
    parser.add_argument("--run-seed", action="store_true", help="Append verified Leanstral TODOs to the bounded queue")
    parser.add_argument("--require-promotion", action="store_true", help="Exit non-zero when promotion is blocked")
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    dry_run = True if args.dry_run or not args.run_seed else False
    input_paths = resolve_disagreement_input_paths(
        args.input,
        min_records=max(1, min(args.max_todos, MAX_SEED_TODOS)),
    )
    explicit_input_requested = bool(args.input)
    records = load_disagreement_records(input_paths) if input_paths else []
    if not records and dry_run and not explicit_input_requested:
        records = build_dry_run_fixture_records(
            count=max(1, min(args.max_todos, MAX_SEED_TODOS))
        )
    config = SeedCanaryConfig(
        max_todos=args.max_todos,
        dry_run=dry_run,
        cache_dir=args.cache_dir,
        report_path=args.report_path,
        todo_queue_path=args.todo_queue_path,
    )
    result = run_seed_canary(records, config=config)
    report_path = write_markdown_report(result, args.report_path)
    print(
        json.dumps(
            {
                "accepted_compiler_decompiler_patch_count": result.accepted_compiler_decompiler_patch_count,
                "hard_guardrail_regressions": list(result.hard_guardrail_regressions),
                "promotion_allowed": result.promotion_allowed,
                "promotion_blockers": list(result.promotion_blockers),
                "report_path": str(report_path),
                "rollout_decision_summary": _json_ready(result.rollout_decision_summary),
                "runtime_seconds": round(result.runtime_seconds, 6),
                "seeded_task_count": result.seeded_task_count,
                "selected_task_count": result.selected_task_count,
                "throughput_improvement": result.throughput_improvement,
                "verified_task_count": result.verified_task_count,
            },
            ensure_ascii=True,
            sort_keys=True,
        )
    )
    if args.require_promotion and not result.promotion_allowed:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
