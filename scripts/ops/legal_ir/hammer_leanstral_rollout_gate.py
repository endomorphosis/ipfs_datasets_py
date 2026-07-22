"""Rollout gates for hammer/Leanstral legal-IR optimizer runs."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_ir_eval_splits import (
    REPRESENTATION_PROMOTION_OPERATION,
    split_guard_blocks_operation,
    split_guard_from_payload,
)


DEFAULT_HARD_GUARDRAIL_METRICS = (
    "compiler_ir_cosine",
    "structural_validity",
    "source_copy_penalty",
    "source_copy_reward_hack_penalty",
    "hammer_proof_success_rate",
    "hammer_reconstruction_success_rate",
    "symbolic_validity_success_rate",
)

LEGAL_IR_VIEW_FAMILIES = (
    "deontic",
    "frame_logic",
    "tdfol",
    "kg",
    "cec",
    "external_provers",
    "decompiler",
)

LEGAL_IR_REPRESENTATION_METRICS = (
    "ir_cross_entropy_loss",
    "ir_cosine_similarity",
    "autoencoder_cross_entropy_loss",
    "autoencoder_cosine_similarity",
    "symbolic_validity_success_rate",
    "hammer_proof_success_rate",
    "reconstruction_success_rate",
    "source_copy_penalty",
)

REPRESENTATION_PROMOTION_SUMMARY_KEYS = (
    "latest_legal_ir_learned_guidance_promotion",
    "legal_ir_learned_guidance_promotion",
    "latest_learned_representation_promotion",
    "learned_representation_promotion",
    "latest_representation_promotion",
    "representation_promotion",
)

_LOWER_IS_BETTER_REPRESENTATION_METRICS = frozenset(
    {
        "ir_cross_entropy_loss",
        "autoencoder_cross_entropy_loss",
        "source_copy_penalty",
    }
)

_REPRESENTATION_METRIC_ALIASES = {
    "hammer_reconstruction_success_rate": "reconstruction_success_rate",
    "source_copy_loss": "source_copy_penalty",
    "source_copy_reward_hack_penalty": "source_copy_penalty",
    "structural_validity": "symbolic_validity_success_rate",
    "symbolic_validity": "symbolic_validity_success_rate",
}

DEFAULT_SOURCE_COPY_KEYS = (
    "latest_compiler_ir_source_copy_reward_hack_penalty",
    "latest_compiler_ir_guided_source_copy_reward_hack_penalty",
    "best_validation_ir_guided_source_copy_reward_hack_penalty",
    "compiler_ir_source_copy_reward_hack_penalty",
    "source_copy_reward_hack_penalty",
    "hammer_source_copy_penalty",
    "compiler_ir_hammer_source_copy_penalty",
    "source_copy_penalty",
    "compiler_ir_source_copy_penalty",
)

DEFAULT_FATAL_STOP_REASONS = frozenset(
    {
        "autoencoder_child_failed",
        "codex_child_failed",
        "main_apply_validation_failed",
        "main_apply_validation_failed_rolled_back",
        "paired_timeout_grace_exceeded",
        "target_metric_regression",
        "holdout-target-metric-regression",
        "unhandled_exception",
    }
)

DEFAULT_BACKEND_FATAL_STATUS_TOKENS = (
    "fatal",
    "crash",
    "segfault",
    "panic",
    "oom",
    "out_of_memory",
)

HAMMER_ALLOWED_STATUSES = frozenset(
    {
        "cache_hit",
        "completed",
        "completed_no_hammer_artifacts",
        "completed_persist_failed",
        "skipped_no_samples",
    }
)


STAGED_ROLLOUT_SCHEMA_VERSION = "legal-ir-hammer-leanstral-rollout-v1"
LEGAL_IR_LEARNED_GUIDANCE_PROMOTION_SCHEMA_VERSION = (
    "legal-ir-learned-guidance-promotion-v1"
)
LEGAL_IR_STABLE_FEATURE_EXPORT_SCHEMA_VERSION = (
    "legal-ir-stable-autoencoder-feature-export-v1"
)
MULTI_SEED_PROMOTION_SCHEMA_VERSION = (
    "legal-ir-hammer-leanstral-multi-seed-promotion-v1"
)
EXTERNAL_VALIDITY_PROMOTION_SCHEMA_VERSION = (
    "legal-ir-hammer-leanstral-external-validity-promotion-v1"
)
COMPILER_SYSTEM_PROMOTION_SCHEMA_VERSION = (
    "legal-ir-hammer-leanstral-compiler-system-promotion-v1"
)
THROUGHPUT_REMEDIATION_SCHEMA_VERSION = (
    "legal-ir-throughput-remediation-rollout-v1"
)

LEGAL_IR_EVAL_SPLITS_SCHEMA_VERSION = "legal-ir-eval-splits-v1"
LEGAL_IR_SEMANTIC_METRICS_SCHEMA_VERSION = (
    "legal-ir-semantic-equivalence-metrics-v1"
)
LEGAL_IR_GRAMMAR_DECODER_SCHEMA_VERSION = "legal-ir-typed-grammar-decoder-v1"
LEGAL_IR_UNCERTAINTY_SCHEMA_VERSION = "legal-ir-uncertainty-v1"
LEGAL_IR_FUZZING_SCHEMA_VERSION = "legal-ir-metamorphic-differential-fuzzing-v1"
LEGAL_IR_HARD_NEGATIVE_EFFECT_SCHEMA_VERSION = "legal-ir-hard-negative-effect-v1"
LEGAL_IR_HARD_NEGATIVE_SCHEMA_VERSION = "legal-ir-hard-negative-curriculum-v1"
LEGAL_IR_SCHEMA_EVOLUTION_SCHEMA_VERSION = "legal-ir-schema-evolution-v1"
LEGAL_IR_PREMISE_SECURITY_SCHEMA_VERSION = "legal-ir-premise-security-v1"
LEGAL_IR_EXTERNAL_BENCHMARK_REPORT_SCHEMA_VERSION = (
    "legal-ir-external-benchmark-report-v1"
)
LEGAL_IR_DRIFT_MONITOR_SCHEMA_VERSION = "legal-ir-drift-monitor-v1"
LEGAL_IR_LEARNED_GUIDANCE_ROLLBACK_SCHEMA_VERSION = (
    "legal-ir-learned-guidance-rollback-v1"
)
LEGAL_SOURCE_TEXT_DATA_RULE = "legal_source_text_is_data_not_instructions"
EXTERNAL_BENCHMARK_HARD_GUARDRAIL = "external_benchmark_never_training_data"
PRODUCTION_DRIFT_AND_ROLLBACK_HARD_GUARDRAIL = "learned_guidance_is_reversible"

EXTERNAL_VALIDITY_REQUIRED_DOMAINS = (
    "leak_free_splits",
    "semantic_metrics",
    "typed_decoding",
    "uncertainty",
    "fuzzing",
    "hard_negatives",
    "multi_seed_statistics",
    "schema_compatibility",
    "poisoning_defenses",
    "external_benchmark_scores",
    "rollback_readiness",
)

SEMANTIC_EQUIVALENCE_REQUIRED_METRICS = (
    "structural_equivalence",
    "obligation_equivalence",
    "counterexample_equivalence",
    "graph_isomorphism",
    "temporal_window_agreement",
    "decompiler_round_trip_preservation",
    "proof_obligation_delta_score",
)

EXTERNAL_VALIDITY_EVIDENCE_ALIASES = {
    "leak_free_splits": (
        "leak_free_splits",
        "eval_splits",
        "split_guard",
        "split_manifest",
        "latest_legal_ir_eval_splits",
    ),
    "semantic_metrics": (
        "semantic_metrics",
        "semantic_equivalence",
        "semantic_equivalence_report",
        "latest_legal_ir_semantic_metrics",
    ),
    "typed_decoding": (
        "typed_decoding",
        "typed_decoder",
        "grammar_decoder",
        "grammar_validation",
        "latest_legal_ir_typed_decoding",
    ),
    "uncertainty": (
        "uncertainty",
        "uncertainty_report",
        "latest_legal_ir_uncertainty",
    ),
    "fuzzing": (
        "fuzzing",
        "fuzzing_report",
        "metamorphic_fuzzing",
        "latest_legal_ir_fuzzing",
    ),
    "hard_negatives": (
        "hard_negatives",
        "hard_negative_effect",
        "hard_negative_curriculum",
        "latest_legal_ir_hard_negatives",
    ),
    "multi_seed_statistics": (
        "multi_seed_statistics",
        "multi_seed_statistical_promotion",
        "multi_seed_promotion_evidence",
        "latest_multi_seed_statistical_promotion",
    ),
    "schema_compatibility": (
        "schema_compatibility",
        "schema_evolution",
        "schema_compatibility_report",
        "latest_legal_ir_schema_compatibility",
    ),
    "poisoning_defenses": (
        "poisoning_defenses",
        "premise_security",
        "prompt_and_premise_security",
        "prompt_and_premise_poisoning_defense",
    ),
    "external_benchmark_scores": (
        "external_benchmark_scores",
        "external_benchmark_report",
        "external_validity",
        "latest_external_benchmark_report",
    ),
    "rollback_readiness": (
        "rollback_readiness",
        "drift_monitor",
        "production_drift_report",
        "rollback_evidence",
        "latest_legal_ir_drift_monitor",
    ),
}

EXTERNAL_VALIDITY_BINDING_FIELDS = (
    "promotion_id",
    "compiler_commit",
    "source_export_id",
    "fixed_canary_id",
    "split_manifest_digest",
)

COMPILER_SYSTEM_REQUIRED_DOMAINS = (
    "evaluation_integrity",
    "external_validity",
    "compiler_source_maps",
    "symbols",
    "citations",
    "temporal_authority",
    "ambiguity",
    "pass_management",
    "backend_conformance",
    "reproducible_builds",
    "incremental_compilation",
    "semantic_diffs",
    "proof_carrying_artifacts",
    "diagnostics",
    "apis",
    "interoperability",
    "conformance_evidence",
    "rollback_readiness",
)

COMPILER_SYSTEM_DOMAIN_SCHEMA_VERSIONS = {
    "compiler_source_maps": ("legal-ir-source-map-v1",),
    "symbols": ("legal-ir-symbol-table-v1",),
    "citations": ("legal-ir-citation-linker-v1",),
    "temporal_authority": ("legal-ir-temporal-authority-v1",),
    "ambiguity": ("legal-ir-ambiguity-v1",),
    "pass_management": ("legal-ir-pass-manager-v1", "legal-ir-pass-replay-v1"),
    "backend_conformance": ("legal-ir-backend-conformance-v1",),
    "reproducible_builds": ("legal-ir-build-manifest-v1",),
    "incremental_compilation": ("legal-ir-incremental-compiler-v1",),
    "semantic_diffs": ("legal-ir-semantic-diff-v1",),
    "proof_carrying_artifacts": ("legal-ir-proof-carrying-artifact-v1",),
    "diagnostics": ("legal-ir-diagnostics-v1",),
    "apis": ("legal-ir-compiler-api-v1",),
    "interoperability": (
        "legal-ir-interop-v1",
        "legal-ir-interop-round-trip-v1",
    ),
}

COMPILER_SYSTEM_DOMAIN_ALIASES = {
    "evaluation_integrity": (
        "evaluation_integrity",
        "eval_integrity",
        "split_guard",
        "leak_free_splits",
        "multi_seed_statistics",
    ),
    "external_validity": (
        "external_validity",
        "external_validity_promotion",
        "external_validity_gate",
    ),
    "compiler_source_maps": (
        "compiler_source_maps",
        "source_maps",
        "source_map",
        "legal_ir_source_maps",
    ),
    "symbols": ("symbols", "symbol_table", "legal_ir_symbols"),
    "citations": ("citations", "citation_graph", "citation_linker"),
    "temporal_authority": (
        "temporal_authority",
        "temporal_context",
        "authority_windows",
    ),
    "ambiguity": ("ambiguity", "ambiguity_report", "ambiguity_policy"),
    "pass_management": ("pass_management", "pass_manager", "pass_replay"),
    "backend_conformance": (
        "backend_conformance",
        "backend_conformance_report",
        "legal_ir_backend_conformance",
    ),
    "reproducible_builds": (
        "reproducible_builds",
        "build_manifest",
        "reproducibility",
    ),
    "incremental_compilation": (
        "incremental_compilation",
        "incremental_compiler",
        "incremental_snapshot",
    ),
    "semantic_diffs": ("semantic_diffs", "semantic_diff", "semantic_diff_report"),
    "proof_carrying_artifacts": (
        "proof_carrying_artifacts",
        "proof_carrying_artifact",
        "proof_artifact",
    ),
    "diagnostics": ("diagnostics", "diagnostic_report", "lsp_diagnostics"),
    "apis": ("apis", "api", "compiler_api", "cli_api"),
    "interoperability": ("interoperability", "interop", "standards_interop"),
    "conformance_evidence": (
        "conformance_evidence",
        "compiler_conformance",
        "compiler_conformance_report",
    ),
    "rollback_readiness": (
        "rollback_readiness",
        "rollback_evidence",
        "rollback",
        "drift_monitor",
    ),
}

COMPILER_SYSTEM_REQUIRED_CONFORMANCE_CAPABILITIES = (
    "compile",
    "proof-carrying artifacts",
    "decompile",
    "semantic diff",
    "diagnostics",
    "reproducibility",
    "external benchmark isolation",
    "hard negatives",
    "source maps",
    "backend conformance",
    "CLI/API behavior",
)

MULTI_SEED_PROMOTION_METRICS = (
    "learned_quality",
    "deterministic_compiler_quality",
    "semantic_equivalence",
    "proof_validity",
    "hard_negative_performance",
    "accepted_patch_rate",
)

MULTI_SEED_PROMOTION_SUMMARY_KEYS = (
    "latest_multi_seed_statistical_promotion",
    "multi_seed_statistical_promotion",
    "latest_multi_seed_promotion_evidence",
    "multi_seed_promotion_evidence",
    "statistical_promotion_evidence",
)

_MULTI_SEED_METRIC_ALIASES = {
    "learned_ir_quality": "learned_quality",
    "learned_representation_quality": "learned_quality",
    "deterministic_quality": "deterministic_compiler_quality",
    "compiler_quality": "deterministic_compiler_quality",
    "compiler_ir_quality": "deterministic_compiler_quality",
    "deterministic_compiler_ir_quality": "deterministic_compiler_quality",
    "semantic_equivalence_score": "semantic_equivalence",
    "semantic_equivalence_rate": "semantic_equivalence",
    "hammer_proof_validity": "proof_validity",
    "proof_success_rate": "proof_validity",
    "proof_validity_rate": "proof_validity",
    "hard_negative_score": "hard_negative_performance",
    "hard_negative_false_positive_reduction": "hard_negative_performance",
    "accepted_patches_per_hour": "accepted_patch_rate",
    "task_to_accepted_patch_rate": "accepted_patch_rate",
    "accepted_patch_ratio": "accepted_patch_rate",
}

_MULTI_SEED_HIGHER_IS_BETTER = frozenset(MULTI_SEED_PROMOTION_METRICS)


@dataclass(frozen=True)
class RolloutStageSpec:
    """One immutable step in the production rollout contract."""

    name: str
    duration_seconds: int


STAGED_ROLLOUT_STAGES = (
    RolloutStageSpec("short_smoke", 10 * 60),
    RolloutStageSpec("one_hour_hparam", 60 * 60),
    RolloutStageSpec("eight_hour_canary", 8 * 60 * 60),
    RolloutStageSpec("twenty_four_hour_production", 24 * 60 * 60),
)

STAGED_HARD_GUARDRAILS = (
    "semantic",
    "provenance",
    "anti_copy",
    "hammer_proof",
    "lean_reconstruction",
    "process_lifecycle",
    "queue_lag",
)

# ``matched_benchmark`` is an evidence-producing stage rather than a timed
# deployment.  Keeping it in the sequence makes it impossible to promote a
# long-running canary whose baseline was collected after (or with a different
# configuration from) the candidate run.
THROUGHPUT_REMEDIATION_STAGES = (
    RolloutStageSpec("matched_benchmark", 0),
    RolloutStageSpec("ten_minute_smoke", 10 * 60),
    RolloutStageSpec("one_hour_hparam", 60 * 60),
    RolloutStageSpec("eight_hour_canary", 8 * 60 * 60),
    RolloutStageSpec("twenty_four_hour_production", 24 * 60 * 60),
)

THROUGHPUT_REMEDIATION_QUALITY_METRICS = (
    "ir_cross_entropy_loss",
    "ir_cosine_similarity",
    "autoencoder_cross_entropy_loss",
    "autoencoder_cosine_similarity",
    "semantic_equivalence",
    "proof_success_rate",
    "reconstruction_success_rate",
    "provenance",
    "round_trip",
    "uncertainty",
    "holdout",
    "source_copy_penalty",
)

_THROUGHPUT_LOWER_IS_BETTER = frozenset(
    {
        "ir_cross_entropy_loss",
        "autoencoder_cross_entropy_loss",
        "uncertainty",
        "source_copy_penalty",
    }
)

_THROUGHPUT_QUALITY_ALIASES = {
    "ce": "ir_cross_entropy_loss",
    "cross_entropy": "ir_cross_entropy_loss",
    "cross_entropy_loss": "ir_cross_entropy_loss",
    "compiler_ir_cross_entropy_loss": "ir_cross_entropy_loss",
    "cosine": "ir_cosine_similarity",
    "compiler_ir_cosine": "ir_cosine_similarity",
    "semantic_equivalence_score": "semantic_equivalence",
    "semantic_equivalence_rate": "semantic_equivalence",
    "hammer_proof_success_rate": "proof_success_rate",
    "proof": "proof_success_rate",
    "hammer_reconstruction_success_rate": "reconstruction_success_rate",
    "reconstruction": "reconstruction_success_rate",
    "provenance_alignment": "provenance",
    "provenance_success_rate": "provenance",
    "round_trip_preservation": "round_trip",
    "decompiler_round_trip_preservation": "round_trip",
    "calibration_error": "uncertainty",
    "expected_calibration_error": "uncertainty",
    "uncertainty_error": "uncertainty",
    "holdout_score": "holdout",
    "holdout_success_rate": "holdout",
    "source_copy_rate": "source_copy_penalty",
    "source_copy_reward_hack_penalty": "source_copy_penalty",
}


@dataclass(frozen=True)
class StagedRolloutConfig:
    """Fail-closed policy for promotion through the four rollout stages."""

    require_all_stages: bool = True
    require_complete_snapshots: bool = True
    require_managed_process_evidence: bool = True
    require_trusted_feedback: bool = True
    require_rollback_evidence: bool = True
    require_promotion_lineage: bool = True
    require_representation_promotion_reports: bool = True
    require_successful_representation_promotion: bool = False
    require_complete_representation_evidence: bool = True
    require_multi_seed_statistical_promotion: bool = False
    verify_rollback_artifacts: bool = False
    duration_tolerance_seconds: float = 0.0
    max_queue_lag_p95_seconds: float = 120.0
    max_queue_lag_regression: float = 0.0
    max_accepted_patches_per_hour_regression: float = 0.0
    min_projection_p95_reduction: float = 0.40
    min_task_to_accepted_patch_rate_improvement: float = 0.20
    min_state_to_merged_patch_lag_reduction: float = 0.25
    required_families: tuple[str, ...] = LEGAL_IR_VIEW_FAMILIES
    required_guardrails: tuple[str, ...] = STAGED_HARD_GUARDRAILS


@dataclass(frozen=True)
class ThroughputRemediationConfig:
    """Fail-closed policy for quality-preserving throughput remediation.

    Ratios are always recomputed from paired measurements.  Claimed gains or
    precomputed ``passed`` flags are retained only as report metadata and can
    never authorize promotion.
    """

    min_warm_cycles_per_hour_ratio: float = 1.8
    min_samples_per_second_ratio: float = 1.5
    require_lower_state_to_accepted_patch_p95: bool = True
    max_checkpoint_bytes: int = 512 * 1024 * 1024
    max_summary_bytes: int = 16 * 1024 * 1024
    require_reproducible_benchmark: bool = True
    require_resume_evidence: bool = True
    require_rollback_evidence: bool = True
    verify_rollback_artifacts: bool = False
    require_ablation_attribution: bool = True
    duration_tolerance_seconds: float = 0.0
    required_families: tuple[str, ...] = LEGAL_IR_VIEW_FAMILIES
    required_quality_metrics: tuple[str, ...] = (
        THROUGHPUT_REMEDIATION_QUALITY_METRICS
    )

    def __post_init__(self) -> None:
        if self.min_warm_cycles_per_hour_ratio < 1.0:
            raise ValueError("min_warm_cycles_per_hour_ratio must be at least 1")
        if self.min_samples_per_second_ratio < 1.0:
            raise ValueError("min_samples_per_second_ratio must be at least 1")
        if isinstance(self.max_checkpoint_bytes, bool) or self.max_checkpoint_bytes < 1:
            raise ValueError("max_checkpoint_bytes must be a positive integer")
        if isinstance(self.max_summary_bytes, bool) or self.max_summary_bytes < 1:
            raise ValueError("max_summary_bytes must be a positive integer")
        if self.duration_tolerance_seconds < 0.0:
            raise ValueError("duration_tolerance_seconds must be non-negative")
        if not self.required_families or len(set(self.required_families)) != len(
            self.required_families
        ):
            raise ValueError("required_families must be non-empty and unique")
        if not self.required_quality_metrics or len(
            set(self.required_quality_metrics)
        ) != len(self.required_quality_metrics):
            raise ValueError("required_quality_metrics must be non-empty and unique")


@dataclass(frozen=True)
class RolloutGateConfig:
    """Thresholds used to reject a rollout summary."""

    max_validation_ce_regression: float = 0.02
    max_validation_cosine_regression: float = 0.02
    max_compiler_ir_ce_regression: float = 0.05
    max_compiler_ir_cosine_regression: float = 0.05
    max_source_copy_penalty: float = 0.35
    require_hammer_cycle: bool = True
    require_todo_activity: bool = True
    require_available_hammer_backend: bool = False
    max_hammer_backend_unavailable_ratio: float = 1.0
    min_cycles_for_todo_gate: int = 1
    require_representation_promotion: bool = False
    require_successful_representation_promotion: bool = False
    require_complete_representation_evidence: bool = True
    max_per_view_ir_metric_regression: float = 0.0
    max_symbolic_validity_regression: float = 0.0
    max_hammer_proof_rate_regression: float = 0.0
    max_reconstruction_rate_regression: float = 0.0
    max_source_copy_penalty_regression: float = 0.0
    max_todo_productivity_regression: float = 0.0
    require_multi_seed_statistical_promotion: bool = False
    required_representation_metrics: tuple[str, ...] = LEGAL_IR_REPRESENTATION_METRICS
    fatal_stop_reasons: frozenset[str] = DEFAULT_FATAL_STOP_REASONS
    source_copy_keys: tuple[str, ...] = DEFAULT_SOURCE_COPY_KEYS


@dataclass(frozen=True)
class MultiSeedMetricSpec:
    """Statistical promotion policy for one paired metric."""

    name: str
    direction: str = "higher"
    minimum_effect: float = 0.0

    @property
    def canonical_name(self) -> str:
        return _canonical_multi_seed_metric(self.name)


@dataclass(frozen=True)
class MultiSeedPromotionConfig:
    """Fail-closed policy for multi-seed promotion evidence."""

    min_seed_count: int = 3
    confidence_level: float = 0.95
    require_paired_seed_sets: bool = True
    require_effect_variance: bool = True
    require_failure_family_attribution: bool = True
    metric_specs: tuple[MultiSeedMetricSpec, ...] = tuple(
        MultiSeedMetricSpec(name) for name in MULTI_SEED_PROMOTION_METRICS
    )

    def spec_by_metric(self) -> dict[str, MultiSeedMetricSpec]:
        return {spec.canonical_name: spec for spec in self.metric_specs}


@dataclass(frozen=True)
class ExternalValidityPromotionConfig:
    """Fail-closed policy for the final external-validity promotion gate."""

    required_domains: tuple[str, ...] = EXTERNAL_VALIDITY_REQUIRED_DOMAINS
    required_binding_fields: tuple[str, ...] = EXTERNAL_VALIDITY_BINDING_FIELDS
    min_semantic_score: float = 1.0
    min_typed_decoding_success_rate: float = 1.0
    max_typed_decoding_source_copy_penalty: float = 0.0
    min_fuzzing_mutation_count: int = 1
    min_trusted_negative_count: int = 1
    min_hard_negative_false_positive_reduction: float = 0.05
    min_external_validity_score: float = 1.0
    min_external_packet_count: int = 1
    require_external_benchmark_separate_from_canary: bool = True
    require_multi_seed_statistics: bool = True
    require_schema_reusable: bool = True
    require_poisoning_hard_rule: bool = True


@dataclass(frozen=True)
class CompilerSystemPromotionConfig:
    """Fail-closed policy for final compiler-system promotion."""

    required_domains: tuple[str, ...] = COMPILER_SYSTEM_REQUIRED_DOMAINS
    required_conformance_capabilities: tuple[str, ...] = (
        COMPILER_SYSTEM_REQUIRED_CONFORMANCE_CAPABILITIES
    )
    required_binding_fields: tuple[str, ...] = EXTERNAL_VALIDITY_BINDING_FIELDS
    require_staged_rollout: bool = True
    require_external_validity: bool = True
    require_conformance_report: bool = True
    require_rollback_readiness: bool = True
    verify_rollback_artifacts: bool = False


@dataclass
class RolloutGateResult:
    """Structured result for CLI and unit-test callers."""

    accepted: bool
    failures: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "accepted": self.accepted,
            "failures": list(self.failures),
            "metrics": dict(self.metrics),
            "warnings": list(self.warnings),
        }


def multi_seed_promotion_gate(
    payload: Mapping[str, Any],
    config: MultiSeedPromotionConfig | None = None,
) -> RolloutGateResult:
    """Require paired multi-seed confidence intervals for promotion evidence.

    The gate evaluates paired baseline/candidate measurements per seed.  For
    higher-is-better metrics the effect is ``candidate - baseline``; for
    lower-is-better metrics the effect is ``baseline - candidate``.  Promotion
    requires every configured metric to have enough seeds and a lower confidence
    bound at or above the configured minimum effect.  This makes a single lucky
    seed and high-variance improvements fail closed even when the mean is good.
    """

    cfg = config or MultiSeedPromotionConfig()
    failures: list[str] = []
    warnings: list[str] = []
    metrics: dict[str, Any] = {
        "schema_version": MULTI_SEED_PROMOTION_SCHEMA_VERSION,
        "confidence_level": cfg.confidence_level,
        "min_seed_count": cfg.min_seed_count,
        "required_metrics": [spec.canonical_name for spec in cfg.metric_specs],
    }
    evidence_path, evidence = _multi_seed_promotion_evidence(payload)
    metrics["multi_seed_evidence_present"] = evidence is not None
    metrics["multi_seed_evidence_path"] = evidence_path
    if evidence is None:
        return RolloutGateResult(
            accepted=False,
            failures=["missing_multi_seed_statistical_evidence"],
            warnings=warnings,
            metrics=metrics,
        )

    schema = str(evidence.get("schema_version") or "").strip()
    if schema and schema != MULTI_SEED_PROMOTION_SCHEMA_VERSION:
        failures.append(f"multi_seed_schema_mismatch:{schema}")
    evidence_confidence = _finite_float(evidence.get("confidence_level"))
    confidence_level = evidence_confidence if evidence_confidence is not None else cfg.confidence_level
    if confidence_level <= 0.0 or confidence_level >= 1.0:
        failures.append(f"multi_seed_confidence_level_invalid:{confidence_level:g}")
        confidence_level = cfg.confidence_level
    metrics["confidence_level"] = confidence_level

    raw_min_seed_count = _finite_float(evidence.get("min_seed_count"))
    if raw_min_seed_count is not None:
        min_seed_count = max(cfg.min_seed_count, int(raw_min_seed_count))
    else:
        min_seed_count = cfg.min_seed_count
    metrics["min_seed_count"] = min_seed_count

    metric_payloads = _multi_seed_metric_payloads(evidence)
    metric_specs = cfg.spec_by_metric()
    metric_results: dict[str, Any] = {}
    all_seeds: set[str] = set()
    all_failure_attribution: dict[str, int] = {}

    required_metric_names = [spec.canonical_name for spec in cfg.metric_specs]
    for metric_name in required_metric_names:
        spec = metric_specs.get(metric_name, MultiSeedMetricSpec(metric_name))
        metric_payload = metric_payloads.get(metric_name)
        if not isinstance(metric_payload, Mapping):
            failures.append(f"multi_seed_metric_missing:{metric_name}")
            continue

        direction = _multi_seed_metric_direction(metric_payload, spec)
        minimum_effect = _multi_seed_minimum_effect(metric_payload, spec)
        paired, parse_failures = _multi_seed_paired_effects(metric_payload, direction)
        failures.extend(f"{failure}:{metric_name}" for failure in parse_failures)
        seed_ids = [seed for seed, _effect in paired]
        all_seeds.update(seed_ids)
        effects = [effect for _seed, effect in paired]
        sample_count = len(effects)
        if sample_count < min_seed_count:
            failures.append(
                f"multi_seed_metric_seed_count:{metric_name}:"
                f"{sample_count}<{min_seed_count}"
            )

        unique_seeds = set(seed_ids)
        if len(unique_seeds) != sample_count:
            failures.append(f"multi_seed_metric_duplicate_seed:{metric_name}")
        if cfg.require_paired_seed_sets:
            seed_failure = _multi_seed_pairing_failure(metric_payload, unique_seeds)
            if seed_failure:
                failures.append(f"{seed_failure}:{metric_name}")

        attribution, attribution_present = _multi_seed_failure_attribution(
            metric_payload,
            effects_by_seed=dict(paired),
        )
        for family, count in attribution.items():
            all_failure_attribution[family] = all_failure_attribution.get(family, 0) + count
        if cfg.require_failure_family_attribution and not attribution_present:
            failures.append(f"multi_seed_failure_family_attribution_missing:{metric_name}")

        stats = _effect_statistics(effects, confidence_level)
        metric_result = {
            "direction": direction,
            "minimum_effect": minimum_effect,
            "seed_set": seed_ids,
            "sample_count": sample_count,
            "effects": [round(effect, 12) for effect in effects],
            "effect_size": stats["mean"],
            "variance": stats["variance"],
            "standard_error": stats["standard_error"],
            "confidence_interval": {
                "level": confidence_level,
                "lower": stats["ci_lower"],
                "upper": stats["ci_upper"],
            },
            "failure_family_attribution": dict(sorted(attribution.items())),
        }
        metric_results[metric_name] = metric_result

        if cfg.require_effect_variance and sample_count >= 2 and stats["variance"] is None:
            failures.append(f"multi_seed_metric_variance_missing:{metric_name}")
        lower = stats["ci_lower"]
        if lower is None:
            failures.append(f"multi_seed_metric_ci_missing:{metric_name}")
        elif lower + 1.0e-12 < minimum_effect:
            failures.append(
                f"multi_seed_metric_ci_below_threshold:{metric_name}:"
                f"{lower:g}<{minimum_effect:g}"
            )

    metrics["multi_seed_metrics"] = metric_results
    metrics["seed_set"] = sorted(all_seeds, key=_seed_sort_key)
    metrics["failure_family_attribution"] = dict(sorted(all_failure_attribution.items()))
    metrics["promotion_id"] = str(evidence.get("promotion_id") or payload.get("promotion_id") or "")
    metrics["compiler_commit"] = str(evidence.get("compiler_commit") or payload.get("compiler_commit") or "")
    return RolloutGateResult(
        accepted=not failures,
        failures=list(dict.fromkeys(failures)),
        warnings=warnings,
        metrics=metrics,
    )


def staged_rollout_gate(
    snapshots: Sequence[Mapping[str, Any]] | Mapping[str, Any],
    config: StagedRolloutConfig | None = None,
) -> RolloutGateResult:
    """Evaluate a complete rollout or an explicitly allowed ordered prefix.

    The staged contract deliberately consumes persisted snapshots, rather than
    live process state.  A stage is promotable only when the snapshot proves
    its duration, guardrails, process cleanup, feedback delivery, productivity,
    and rollback point.  Missing evidence is a failure, never a warning.
    """

    cfg = config or StagedRolloutConfig()
    failures: list[str] = []
    warnings: list[str] = []
    metrics: dict[str, Any] = {
        "schema_version": STAGED_ROLLOUT_SCHEMA_VERSION,
        "expected_stage_sequence": [stage.name for stage in STAGED_ROLLOUT_STAGES],
    }
    items, envelope_failures = _staged_snapshot_items(snapshots)
    failures.extend(envelope_failures)
    expected_count = len(STAGED_ROLLOUT_STAGES)
    if not items:
        failures.append("stage_sequence:no_snapshots")
    if len(items) > expected_count:
        failures.append(f"stage_sequence:too_many_snapshots:{len(items)}>{expected_count}")
    if cfg.require_all_stages and len(items) != expected_count:
        failures.append(
            f"stage_sequence:incomplete:{len(items)}/{expected_count}"
        )

    completed: list[str] = []
    rates: dict[str, float] = {}
    queue_lags: dict[str, float] = {}
    rollback: dict[str, dict[str, Any]] = {}
    lineage: dict[str, dict[str, Any]] = {}
    previous_rate: float | None = None
    previous_queue_lag: float | None = None

    for index, snapshot in enumerate(items[:expected_count]):
        expected = STAGED_ROLLOUT_STAGES[index]
        stage_name = str(snapshot.get("stage") or snapshot.get("stage_name") or "").strip()
        if stage_name != expected.name:
            failures.append(
                f"stage_sequence:index_{index}:expected_{expected.name}:got_{stage_name or 'missing'}"
            )
            # Attribute subsequent failures to the expected slot so malformed
            # names cannot create ambiguous or attacker-controlled diagnostics.
        stage_label = expected.name
        completed.append(stage_name or stage_label)

        duration = _first_finite(snapshot, ("duration_seconds", "planned_duration_seconds"))
        if duration is None:
            failures.append(f"stage_duration_missing:{stage_label}")
        elif abs(duration - expected.duration_seconds) > max(0.0, cfg.duration_tolerance_seconds):
            failures.append(
                f"stage_duration:{stage_label}:{duration:g}!={expected.duration_seconds}"
            )

        elapsed = _first_finite(snapshot, ("elapsed_seconds", "wall_clock_seconds"))
        if elapsed is None or elapsed <= 0.0:
            failures.append(f"stage_wall_clock_missing:{stage_label}")
        elif elapsed + max(0.0, cfg.duration_tolerance_seconds) < expected.duration_seconds:
            failures.append(
                f"stage_duration:{stage_label}:elapsed_{elapsed:g}<"
                f"{expected.duration_seconds}"
            )
        status = str(snapshot.get("status") or "").strip().lower()
        if status not in {"completed", "passed", "succeeded", "success"}:
            failures.append(f"stage_status:{stage_label}:{status or 'missing'}")
        if cfg.require_complete_snapshots and snapshot.get("snapshot_complete") is not True:
            failures.append(f"incomplete_snapshot:{stage_label}")

        failures.extend(_managed_process_failures(snapshot, stage_label, cfg))
        failures.extend(_family_guardrail_failures(snapshot, stage_label, cfg))
        failures.extend(_trusted_feedback_failures(snapshot, stage_label, cfg))
        failures.extend(_representation_snapshot_failures(snapshot, stage_label, cfg))
        lineage_value, lineage_failures = _promotion_lineage_evidence(
            snapshot, stage_label, cfg
        )
        failures.extend(lineage_failures)
        if lineage_value is not None:
            lineage[stage_label] = lineage_value

        queue_lag = _stage_queue_lag(snapshot)
        if queue_lag is None:
            failures.append(f"queue_lag_evidence_missing:{stage_label}")
        else:
            queue_lags[stage_label] = queue_lag
            if queue_lag > cfg.max_queue_lag_p95_seconds:
                failures.append(
                    f"queue_lag_limit_exceeded:{stage_label}:{queue_lag:g}>"
                    f"{cfg.max_queue_lag_p95_seconds:g}"
                )
            if (
                previous_queue_lag is not None
                and queue_lag - previous_queue_lag > cfg.max_queue_lag_regression + 1.0e-12
            ):
                failures.append(
                    f"queue_lag_regression:{stage_label}:{previous_queue_lag:g}->"
                    f"{queue_lag:g}"
                )
            previous_queue_lag = queue_lag

        patch_count = _first_finite(
            snapshot,
            ("accepted_patches", "codex_accepted_patch_count", "codex_main_apply_count"),
        )
        wall_clock = _first_finite(snapshot, ("wall_clock_seconds", "elapsed_seconds"))
        if patch_count is None or patch_count < 0.0 or wall_clock is None or wall_clock <= 0.0:
            failures.append(f"accepted_patch_productivity_evidence_missing:{stage_label}")
        else:
            rate = patch_count * 3600.0 / wall_clock
            rates[stage_label] = round(rate, 12)
            if (
                previous_rate is not None
                and previous_rate - rate
                > cfg.max_accepted_patches_per_hour_regression + 1.0e-12
            ):
                failures.append(
                    f"accepted_patches_per_hour_regression:{stage_label}:"
                    f"{previous_rate:g}->{rate:g}"
                )
            previous_rate = rate

        rollback_value, rollback_failures = _validated_rollback_evidence(
            snapshot, stage_label, cfg
        )
        failures.extend(rollback_failures)
        if rollback_value is not None:
            rollback[stage_label] = rollback_value

        if index == expected_count - 1:
            threshold_metrics, threshold_failures = _promotion_threshold_failures(
                snapshot, stage_label, cfg
            )
            failures.extend(threshold_failures)
            if threshold_metrics:
                metrics["promotion_thresholds"] = threshold_metrics
            multi_seed_result = _staged_multi_seed_result(snapshot, cfg)
            if multi_seed_result is not None:
                metrics["multi_seed_statistical_promotion"] = multi_seed_result.metrics
                failures.extend(multi_seed_result.failures)

    next_stage = (
        STAGED_ROLLOUT_STAGES[len(items)].name
        if len(items) < expected_count
        else None
    )
    metrics.update(
        {
            "completed_stages": completed,
            "next_stage": next_stage,
            "accepted_patches_per_hour": rates,
            "accepted_patches_per_wall_clock_hour": rates,
            "queue_lag_p95_seconds": queue_lags,
            "rollback_evidence": rollback,
            "promotion_lineage": lineage,
            "trusted_feedback_reached_autoencoder": not any(
                item.startswith("trusted_feedback_") for item in failures
            ) and bool(items),
        }
    )
    return RolloutGateResult(
        accepted=not failures,
        failures=list(dict.fromkeys(failures)),
        warnings=warnings,
        metrics=metrics,
    )


def throughput_remediation_rollout_gate(
    payload: Mapping[str, Any],
    config: ThroughputRemediationConfig | None = None,
) -> RolloutGateResult:
    """Gate the complete quality-preserving throughput remediation rollout.

    This gate intentionally accepts only persisted, positive evidence.  It
    recomputes all ratios and per-family comparisons and never treats a
    supplied ``healthy``/``passed`` headline as a substitute for counters.
    """

    cfg = config or ThroughputRemediationConfig()
    failures: list[str] = []
    metrics: dict[str, Any] = {
        "schema_version": THROUGHPUT_REMEDIATION_SCHEMA_VERSION,
        "required_stages": [stage.name for stage in THROUGHPUT_REMEDIATION_STAGES],
        "minimum_warm_cycles_per_hour_ratio": cfg.min_warm_cycles_per_hour_ratio,
        "minimum_samples_per_second_ratio": cfg.min_samples_per_second_ratio,
    }
    if not isinstance(payload, Mapping):
        return RolloutGateResult(False, ["evidence_invalid:not_an_object"], metrics=metrics)
    schema = str(payload.get("schema_version") or "")
    if schema != THROUGHPUT_REMEDIATION_SCHEMA_VERSION:
        failures.append(f"schema_mismatch:{schema or 'missing'}")

    required_domains = (
        "stages", "matched_benchmark", "services", "artifacts",
        "quality_families", "ablations",
    )
    for domain in required_domains:
        if domain not in payload or payload.get(domain) in (None, {}, []):
            failures.append(f"evidence_missing:{domain}")

    stage_items = payload.get("stages")
    completed_stages: list[str] = []
    if isinstance(stage_items, Sequence) and not isinstance(
        stage_items, (str, bytes, bytearray)
    ):
        if len(stage_items) != len(THROUGHPUT_REMEDIATION_STAGES):
            failures.append(
                "stage_sequence:incomplete:"
                f"{len(stage_items)}/{len(THROUGHPUT_REMEDIATION_STAGES)}"
            )
        for index, spec in enumerate(THROUGHPUT_REMEDIATION_STAGES):
            if index >= len(stage_items):
                failures.append(f"evidence_missing:stage:{spec.name}")
                continue
            item = stage_items[index]
            if not isinstance(item, Mapping):
                failures.append(f"evidence_missing:stage:{spec.name}:not_an_object")
                continue
            completed_stages.append(_throughput_stage_failures(item, spec, cfg, failures))
    elif "stages" in payload:
        failures.append("evidence_invalid:stages")
    metrics["completed_stages"] = completed_stages

    benchmark = payload.get("matched_benchmark")
    if isinstance(benchmark, Mapping):
        _throughput_benchmark_failures(benchmark, cfg, failures, metrics)
    services = payload.get("services")
    if isinstance(services, Mapping):
        _throughput_service_failures(services, failures)
    artifacts = payload.get("artifacts")
    if isinstance(artifacts, Mapping):
        _throughput_artifact_failures(artifacts, cfg, failures, metrics)
    quality = payload.get("quality_families")
    if isinstance(quality, Mapping):
        _throughput_quality_failures(quality, cfg, failures, metrics)
    ablations = payload.get("ablations")
    if isinstance(ablations, Mapping):
        _throughput_ablation_failures(ablations, cfg, failures, metrics)

    metrics["evidence_complete"] = not failures
    return RolloutGateResult(
        accepted=not failures,
        failures=list(dict.fromkeys(failures)),
        warnings=[],
        metrics=metrics,
    )


def _throughput_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    return _finite_float(value)


def _throughput_positive(block: Mapping[str, Any], key: str) -> bool:
    value = _throughput_number(block.get(key))
    return value is not None and value > 0.0


def _throughput_stage_failures(
    item: Mapping[str, Any],
    spec: RolloutStageSpec,
    cfg: ThroughputRemediationConfig,
    failures: list[str],
) -> str:
    name = str(item.get("name") or item.get("stage") or "").strip()
    if name != spec.name:
        failures.append(f"stage_sequence:expected_{spec.name}:got_{name or 'missing'}")
    planned = _throughput_number(
        item.get("planned_duration_seconds", item.get("duration_seconds"))
    )
    if planned is None or abs(planned - spec.duration_seconds) > cfg.duration_tolerance_seconds:
        failures.append(f"stage_duration:{spec.name}:planned")
    active = _throughput_number(
        item.get("active_seconds", item.get("elapsed_seconds"))
    )
    if active is None or active + cfg.duration_tolerance_seconds < spec.duration_seconds:
        failures.append(f"stage_duration:{spec.name}:active")
    if str(item.get("status") or "").lower() not in {
        "completed", "passed", "succeeded", "success",
    }:
        failures.append(f"stage_status:{spec.name}")
    if item.get("snapshot_complete") is not True:
        failures.append(f"evidence_missing:stage:{spec.name}:snapshot_complete")

    lineage = item.get("lineage", item.get("promotion_lineage"))
    if not isinstance(lineage, Mapping):
        failures.append(f"evidence_missing:stage:{spec.name}:lineage")
    else:
        for key in ("run_id", "configuration_digest", "input_digest", "output_digest"):
            value = str(lineage.get(key) or "").strip()
            if not value or (key.endswith("digest") and not _valid_digest_ref(value)):
                failures.append(f"evidence_missing:stage:{spec.name}:lineage:{key}")
        if str(lineage.get("stage") or "") != spec.name:
            failures.append(f"lineage_mismatch:stage:{spec.name}")

    orphan_count = _throughput_number(item.get("orphaned_child_count"))
    if orphan_count is None or orphan_count != 0.0:
        failures.append(f"orphaned_children:{spec.name}")
    processes = item.get("managed_processes")
    if not isinstance(processes, Sequence) or isinstance(
        processes, (str, bytes, bytearray)
    ) or not processes:
        failures.append(f"evidence_missing:stage:{spec.name}:managed_processes")
    else:
        for process in processes:
            if not isinstance(process, Mapping):
                failures.append(f"managed_process_invalid:{spec.name}")
                continue
            state = str(process.get("status") or process.get("state") or "").lower()
            code = _throughput_number(process.get("exit_code", process.get("returncode")))
            if process.get("orphaned") is not False or state not in {
                "completed", "exited", "stopped", "terminated", "cleaned",
            } or code != 0.0:
                failures.append(
                    f"orphaned_or_failed_managed_process:{spec.name}:"
                    f"{process.get('name', 'unknown')}"
                )

    resume = item.get("resume_evidence")
    if cfg.require_resume_evidence:
        if not isinstance(resume, Mapping):
            failures.append(f"resume_evidence_missing:{spec.name}")
        else:
            explicit_resume = resume.get("resumed")
            if (
                resume.get("available") is not True
                or resume.get("lineage_verified") is not True
                or not isinstance(explicit_resume, bool)
                or not str(resume.get("checkpoint_path") or "").strip()
                or not _valid_digest_ref(str(resume.get("sha256") or ""))
            ):
                failures.append(f"resume_evidence_invalid:{spec.name}")
    rollback = item.get("rollback_evidence")
    if cfg.require_rollback_evidence:
        if not isinstance(rollback, Mapping):
            failures.append(f"rollback_evidence_missing:{spec.name}")
        else:
            path = str(rollback.get("artifact_path") or "").strip()
            digest = str(rollback.get("sha256") or "")
            valid = (
                rollback.get("available") is True
                and rollback.get("restorable") is True
                and rollback.get("rollback_tested") is True
                and bool(str(rollback.get("baseline_revision") or "").strip())
                and bool(path)
                and _valid_digest_ref(digest)
            )
            if cfg.verify_rollback_artifacts and valid:
                try:
                    valid = Path(path).is_file() and snapshot_sha256(path) == digest.removeprefix("sha256:")
                except OSError:
                    valid = False
            if not valid:
                failures.append(f"rollback_evidence_invalid:{spec.name}")
    return name or spec.name


def _throughput_benchmark_failures(
    benchmark: Mapping[str, Any],
    cfg: ThroughputRemediationConfig,
    failures: list[str],
    metrics: dict[str, Any],
) -> None:
    if benchmark.get("dry_run") is True:
        failures.append("matched_benchmark:dry_run_not_promotion_evidence")
    if cfg.require_reproducible_benchmark and benchmark.get("reproducible") is not True:
        failures.append("matched_benchmark:not_reproducible")
    for key in ("fixture_digest", "configuration_digest"):
        if not _valid_digest_ref(str(benchmark.get(key) or "")):
            failures.append(f"evidence_missing:matched_benchmark:{key}")
    values: dict[tuple[str, str], Mapping[str, Any]] = {}
    for cache in ("cold", "warm"):
        cache_block = benchmark.get(cache)
        if not isinstance(cache_block, Mapping):
            failures.append(f"evidence_missing:matched_benchmark:{cache}")
            continue
        for arm in ("baseline", "candidate"):
            block = cache_block.get(arm)
            if not isinstance(block, Mapping):
                failures.append(f"evidence_missing:matched_benchmark:{cache}:{arm}")
                continue
            values[(cache, arm)] = block
            for key in (
                "cycles_per_hour", "samples_per_second",
                "state_to_accepted_patch_lag_p95_seconds",
            ):
                number = _throughput_number(block.get(key))
                if number is None or number <= 0.0:
                    failures.append(f"evidence_missing:matched_benchmark:{cache}:{arm}:{key}")
    baseline = values.get(("warm", "baseline"))
    candidate = values.get(("warm", "candidate"))
    if baseline is None or candidate is None:
        return
    base_cycles = _throughput_number(baseline.get("cycles_per_hour")) or 0.0
    cand_cycles = _throughput_number(candidate.get("cycles_per_hour")) or 0.0
    base_samples = _throughput_number(baseline.get("samples_per_second")) or 0.0
    cand_samples = _throughput_number(candidate.get("samples_per_second")) or 0.0
    base_lag = _throughput_number(baseline.get("state_to_accepted_patch_lag_p95_seconds"))
    cand_lag = _throughput_number(candidate.get("state_to_accepted_patch_lag_p95_seconds"))
    cycle_ratio = cand_cycles / base_cycles if base_cycles > 0 else 0.0
    sample_ratio = cand_samples / base_samples if base_samples > 0 else 0.0
    metrics["warm_cycles_per_hour_ratio"] = cycle_ratio
    metrics["warm_samples_per_second_ratio"] = sample_ratio
    metrics["state_to_accepted_patch_lag_improved"] = (
        base_lag is not None and cand_lag is not None and cand_lag < base_lag
    )
    if cycle_ratio + 1e-12 < cfg.min_warm_cycles_per_hour_ratio:
        failures.append("throughput_threshold:warm_cycles_per_hour")
    if sample_ratio + 1e-12 < cfg.min_samples_per_second_ratio:
        failures.append("throughput_threshold:warm_samples_per_second")
    if cfg.require_lower_state_to_accepted_patch_p95 and not metrics[
        "state_to_accepted_patch_lag_improved"
    ]:
        failures.append("throughput_threshold:state_to_accepted_patch_lag_p95")


def _throughput_service_failures(
    services: Mapping[str, Any], failures: list[str]
) -> None:
    for name in ("cuda_autoencoder", "leanstral", "hammer", "codex"):
        if not isinstance(services.get(name), Mapping):
            failures.append(f"evidence_missing:services:{name}")
    auto = services.get("cuda_autoencoder")
    if isinstance(auto, Mapping):
        valid = (
            auto.get("healthy") is True
            and auto.get("training") is True
            and str(auto.get("device") or "").lower().startswith("cuda")
            and auto.get("cpu_fallback") is False
            and all(
                _throughput_positive(auto, key)
                for key in ("forward_count", "loss_count", "backward_count", "optimizer_step_count")
            )
        )
        if not valid:
            failures.append("service_invalid:cuda_autoencoder")
    lean = services.get("leanstral")
    if isinstance(lean, Mapping):
        valid = (
            lean.get("healthy") is True
            and lean.get("persistent") is True
            and str(lean.get("device") or "").lower().startswith("cuda")
            and lean.get("cpu_fallback") is False
            and _throughput_number(lean.get("model_load_count")) == 1.0
            and _throughput_positive(lean, "request_count")
            and _throughput_positive(lean, "reuse_count")
        )
        if not valid:
            failures.append("service_invalid:leanstral")
    hammer = services.get("hammer")
    if isinstance(hammer, Mapping):
        valid = (
            hammer.get("healthy") is True
            and hammer.get("backend_available") is True
            and all(
                _throughput_positive(hammer, key)
                for key in ("obligation_count", "proof_attempt_count", "reconstruction_count")
            )
            and _throughput_number(hammer.get("fatal_failure_count")) == 0.0
        )
        if not valid:
            failures.append("service_invalid:hammer")
    codex = services.get("codex")
    if isinstance(codex, Mapping):
        accepted = _throughput_number(codex.get("accepted_patch_count")) or 0.0
        rejected = _throughput_number(codex.get("safe_rejection_count")) or 0.0
        valid = (
            codex.get("healthy") is True
            and _throughput_positive(codex, "invocation_count")
            and _throughput_positive(codex, "focused_validation_count")
            and accepted + rejected > 0.0
            and _throughput_number(codex.get("fatal_failure_count")) == 0.0
        )
        if not valid:
            failures.append("service_invalid:codex")


def _throughput_artifact_failures(
    artifacts: Mapping[str, Any],
    cfg: ThroughputRemediationConfig,
    failures: list[str],
    metrics: dict[str, Any],
) -> None:
    for key, limit in (
        ("checkpoint_bytes", cfg.max_checkpoint_bytes),
        ("summary_bytes", cfg.max_summary_bytes),
    ):
        value = _throughput_number(artifacts.get(key))
        metrics[key] = value
        if value is None or value < 0.0:
            failures.append(f"artifact_evidence_missing:{key}")
        elif value > limit:
            failures.append(f"artifact_bound_exceeded:{key}:{value:g}>{limit}")
        digest_key = key.replace("bytes", "sha256")
        if not _valid_digest_ref(str(artifacts.get(digest_key) or "")):
            failures.append(f"artifact_evidence_missing:{digest_key}")


def _canonical_throughput_quality(block: Mapping[str, Any]) -> dict[str, float]:
    result: dict[str, float] = {}
    for key, value in block.items():
        canonical = _THROUGHPUT_QUALITY_ALIASES.get(str(key), str(key))
        number = _throughput_number(value)
        if number is not None:
            result[canonical] = number
    return result


def _throughput_quality_failures(
    quality: Mapping[str, Any],
    cfg: ThroughputRemediationConfig,
    failures: list[str],
    metrics: dict[str, Any],
) -> None:
    comparisons: dict[str, Any] = {}
    extra = sorted(set(quality) - set(cfg.required_families))
    if extra:
        failures.extend(f"quality_family_unknown:{name}" for name in extra)
    for family in cfg.required_families:
        pair = quality.get(family)
        if not isinstance(pair, Mapping):
            failures.append(f"evidence_missing:quality_families:{family}")
            continue
        before_raw, after_raw = pair.get("baseline"), pair.get("candidate")
        if not isinstance(before_raw, Mapping) or not isinstance(after_raw, Mapping):
            failures.append(f"evidence_missing:quality_families:{family}:paired_values")
            continue
        before = _canonical_throughput_quality(before_raw)
        after = _canonical_throughput_quality(after_raw)
        family_metrics: dict[str, Any] = {}
        for metric in cfg.required_quality_metrics:
            if metric not in before or metric not in after:
                failures.append(f"evidence_missing:quality_families:{family}:{metric}")
                continue
            regressed = (
                after[metric] > before[metric] + 1e-12
                if metric in _THROUGHPUT_LOWER_IS_BETTER
                else after[metric] + 1e-12 < before[metric]
            )
            family_metrics[metric] = {
                "baseline": before[metric], "candidate": after[metric],
                "regression": regressed,
            }
            if regressed:
                failures.append(f"quality_regression:{family}:{metric}")
        comparisons[family] = family_metrics
    metrics["quality_comparisons"] = comparisons


def _throughput_ablation_failures(
    ablations: Mapping[str, Any],
    cfg: ThroughputRemediationConfig,
    failures: list[str],
    metrics: dict[str, Any],
) -> None:
    if cfg.require_ablation_attribution and not ablations:
        failures.append("evidence_missing:ablations")
        return
    recorded: dict[str, Any] = {}
    for name, item in sorted(ablations.items()):
        if not isinstance(item, Mapping):
            failures.append(f"ablation_invalid:{name}")
            continue
        cycle_gain = _throughput_number(item.get("cycles_per_hour_gain"))
        sample_gain = _throughput_number(item.get("samples_per_second_gain"))
        valid = (
            item.get("attributed") is True
            and _valid_digest_ref(str(item.get("evidence_digest") or ""))
            and cycle_gain is not None
            and sample_gain is not None
        )
        if not valid:
            failures.append(f"ablation_invalid:{name}")
        recorded[str(name)] = {
            "cycles_per_hour_gain": cycle_gain,
            "samples_per_second_gain": sample_gain,
        }
    metrics["ablation_attribution"] = recorded


def render_throughput_remediation_report(result: RolloutGateResult) -> str:
    """Render a compact operator report without changing the decision."""

    decision = "accepted" if result.accepted else "blocked"
    metrics = result.metrics
    lines = [
        "# LegalIR Throughput Remediation Decision",
        "",
        f"Decision: `{decision}`",
        f"Schema: `{THROUGHPUT_REMEDIATION_SCHEMA_VERSION}`",
        f"Warm cycles/hour ratio: `{metrics.get('warm_cycles_per_hour_ratio')}` (minimum `1.8`)",
        f"Warm samples/second ratio: `{metrics.get('warm_samples_per_second_ratio')}` (minimum `1.5`)",
        f"State-to-accepted-patch p95 improved: `{metrics.get('state_to_accepted_patch_lag_improved')}`",
        "",
        "## Ablation attribution",
    ]
    for name, values in sorted((metrics.get("ablation_attribution") or {}).items()):
        lines.append(f"- `{name}`: `{values}`")
    lines.extend(["", "## Failures"])
    lines.extend(f"- `{failure}`" for failure in result.failures)
    if not result.failures:
        lines.append("- none")
    return "\n".join(lines) + "\n"


def _staged_snapshot_items(
    value: Sequence[Mapping[str, Any]] | Mapping[str, Any],
) -> tuple[list[Mapping[str, Any]], list[str]]:
    failures: list[str] = []
    raw: Any = value
    if isinstance(value, Mapping):
        schema = value.get("schema_version")
        if schema not in (None, "", STAGED_ROLLOUT_SCHEMA_VERSION):
            failures.append(f"snapshot_schema_unsupported:{schema}")
        raw = value.get("snapshots", value.get("stages"))
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes, bytearray)):
        return [], failures + ["snapshot_envelope_invalid"]
    items: list[Mapping[str, Any]] = []
    for index, item in enumerate(raw):
        if not isinstance(item, Mapping):
            failures.append(f"incomplete_snapshot:index_{index}:not_an_object")
            continue
        items.append(item)
    return items, failures


def _managed_process_failures(
    snapshot: Mapping[str, Any],
    stage: str,
    cfg: StagedRolloutConfig,
) -> list[str]:
    raw = snapshot.get("managed_processes", snapshot.get("process_lifecycle"))
    if isinstance(raw, Mapping):
        raw = raw.get("processes", raw.get("managed_processes"))
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes, bytearray)) or not raw:
        return [f"managed_process_evidence_missing:{stage}"] if cfg.require_managed_process_evidence else []
    failures: list[str] = []
    for index, process in enumerate(raw):
        if not isinstance(process, Mapping):
            failures.append(f"managed_process_evidence_incomplete:{stage}:index_{index}")
            continue
        name = str(
            process.get("name")
            or process.get("managed_process_id")
            or process.get("role")
            or f"index_{index}"
        )
        state = str(process.get("status") or process.get("state") or "").strip().lower()
        orphaned = process.get("orphaned") is True or state in {
            "orphaned", "running", "alive", "unknown", "leaked"
        }
        if orphaned:
            failures.append(f"orphaned_managed_process:{stage}:{name}")
        if state not in {"completed", "exited", "stopped", "terminated", "cleaned"}:
            failures.append(f"managed_process_not_reaped:{stage}:{name}:{state or 'missing'}")
        code = process.get("exit_code", process.get("returncode"))
        if code is None:
            failures.append(f"managed_process_exit_missing:{stage}:{name}")
        elif _is_nonzero_exit(code):
            failures.append(f"managed_process_failure:{stage}:{name}:exit_{code}")
    return failures


def _family_guardrail_failures(
    snapshot: Mapping[str, Any],
    stage: str,
    cfg: StagedRolloutConfig,
) -> list[str]:
    raw = snapshot.get("family_metrics", snapshot.get("per_family_guardrails"))
    if not isinstance(raw, Mapping):
        return [f"per_family_guardrail_evidence_missing:{stage}"]
    failures: list[str] = []
    for family in cfg.required_families:
        values = raw.get(family)
        if not isinstance(values, Mapping):
            failures.append(f"per_family_guardrail_evidence_missing:{stage}:{family}")
            continue
        for guardrail in cfg.required_guardrails:
            regression_key = f"{guardrail}_regression"
            regression = values.get(regression_key)
            calculated = _paired_guardrail_regression(values, guardrail)
            if regression is True or calculated is True:
                failures.append(f"{guardrail}_regression:{stage}:{family}")
            elif regression is not False and calculated is None:
                failures.append(
                    f"per_family_guardrail_evidence_missing:{stage}:{family}:{guardrail}"
                )
    return failures


def _paired_guardrail_regression(
    values: Mapping[str, Any], guardrail: str
) -> bool | None:
    """Recompute a declared family guardrail when paired values are present."""

    baseline = values.get("baseline")
    candidate = values.get("candidate")
    if not isinstance(baseline, Mapping) or not isinstance(candidate, Mapping):
        return None
    directions: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
        "semantic": (
            (
                "ir_cosine_similarity",
                "compiler_ir_cosine",
                "symbolic_validity_success_rate",
                "structural_validity",
            ),
            ("ir_cross_entropy_loss", "compiler_ir_cross_entropy_loss"),
        ),
        "provenance": (
            (
                "provenance_alignment",
                "provenance_alignment_score",
                "provenance_success_rate",
                "provenance_coverage",
            ),
            ("provenance_failure_count", "provenance_violation_rate"),
        ),
        "anti_copy": (
            ("anti_copy_success_rate",),
            (
                "source_copy_penalty",
                "source_copy_reward_hack_penalty",
                "source_copy_rate",
            ),
        ),
        "hammer_proof": (("hammer_proof_success_rate",), ("hammer_failure_rate",)),
        "lean_reconstruction": (
            ("reconstruction_success_rate", "hammer_reconstruction_success_rate"),
            ("reconstruction_failure_rate",),
        ),
        "process_lifecycle": (
            ("process_cleanup_success_rate",),
            ("process_failure_count", "orphan_process_count", "process_timeout_rate"),
        ),
        "queue_lag": ((), ("queue_lag_p95_seconds", "queue_lag_seconds")),
    }
    higher, lower = directions.get(guardrail, ((), ()))
    compared = False
    for name in higher:
        before = _finite_float(baseline.get(name))
        after = _finite_float(candidate.get(name))
        if before is not None and after is not None:
            compared = True
            if after < before - 1.0e-12:
                return True
    for name in lower:
        before = _finite_float(baseline.get(name))
        after = _finite_float(candidate.get(name))
        if before is not None and after is not None:
            compared = True
            if after > before + 1.0e-12:
                return True
    return False if compared else None


def _trusted_feedback_failures(
    snapshot: Mapping[str, Any],
    stage: str,
    cfg: StagedRolloutConfig,
) -> list[str]:
    if not cfg.require_trusted_feedback:
        return []
    value = snapshot.get("trusted_feedback")
    if not isinstance(value, Mapping):
        return [f"trusted_feedback_evidence_missing:{stage}"]
    trusted = _first_finite(
        value, ("trusted_count", "verified_count", "accepted_count", "produced_count")
    )
    received = _first_finite(
        value,
        (
            "autoencoder_received_count",
            "autoencoder_applied_count",
            "applied_count",
            "weight_update_count",
        ),
    )
    source_digest = str(value.get("source_digest") or value.get("feedback_digest") or "")
    received_digest = str(
        value.get("autoencoder_source_digest")
        or value.get("applied_feedback_digest")
        or ""
    )
    applied_ids = value.get("applied_feedback_ids", value.get("guidance_ids"))
    ids_prove_delivery = (
        isinstance(applied_ids, Sequence)
        and not isinstance(applied_ids, (str, bytes, bytearray))
        and received is not None
        and len(applied_ids) >= int(received)
    )
    digest_proves_delivery = bool(source_digest) and source_digest == received_digest
    weight_writes = value.get("write_to_autoencoder_weights")
    production_writes = value.get("production_weight_writes_enabled")
    ablation = value.get("ablation_evidence")
    ablation_passed = not isinstance(ablation, Mapping) or (
        ablation.get("passed") is True
        or ablation.get("guardrails_passed") is True
        or str(ablation.get("status") or "").lower() in {"passed", "accepted"}
    )
    if (
        trusted is None
        or trusted <= 0.0
        or received is None
        or received < trusted
        or not (digest_proves_delivery or ids_prove_delivery)
        or weight_writes is False
        or production_writes is False
        or not ablation_passed
    ):
        return [f"trusted_feedback_not_applied:{stage}"]
    return []


def _representation_snapshot_failures(
    snapshot: Mapping[str, Any],
    stage: str,
    cfg: StagedRolloutConfig,
) -> list[str]:
    if not cfg.require_representation_promotion_reports:
        return []
    if not _representation_snapshot_is_eligible(snapshot):
        return []
    metrics: dict[str, Any] = {}
    warnings: list[str] = []
    failures = _representation_promotion_failures(
        snapshot,
        RolloutGateConfig(
            require_representation_promotion=True,
            require_successful_representation_promotion=(
                cfg.require_successful_representation_promotion
            ),
            require_complete_representation_evidence=(
                cfg.require_complete_representation_evidence
            ),
        ),
        metrics,
        warnings,
    )
    return [f"{failure}:{stage}" for failure in failures]


def _representation_snapshot_is_eligible(snapshot: Mapping[str, Any]) -> bool:
    if snapshot.get("representation_promotion_eligible") is True:
        return True
    if snapshot.get("eligible_legal_ir_learned_guidance_snapshot") is True:
        return True
    if _representation_promotion_report(snapshot)[1] is not None:
        return True
    for key in (
        "latest_legal_ir_stable_feature_export",
        "legal_ir_stable_feature_export",
        "stable_legal_ir_feature_export",
        "learned_export",
        "source_export_id",
        "learned_export_id",
    ):
        value = snapshot.get(key)
        if isinstance(value, Mapping) and value:
            return True
        if isinstance(value, str) and value.strip():
            return True
    return False


def _stage_queue_lag(snapshot: Mapping[str, Any]) -> float | None:
    value = snapshot.get("queue_lag")
    if isinstance(value, Mapping):
        result = _first_finite(value, ("p95_seconds", "queue_lag_p95_seconds", "p95"))
        if result is not None:
            return result
    return _first_finite(snapshot, ("queue_lag_p95_seconds", "program_synthesis_queue_lag_p95_seconds"))


def _staged_multi_seed_result(
    snapshot: Mapping[str, Any],
    cfg: StagedRolloutConfig,
) -> RolloutGateResult | None:
    _evidence_path, evidence = _multi_seed_promotion_evidence(snapshot)
    if not cfg.require_multi_seed_statistical_promotion and evidence is None:
        return None
    return multi_seed_promotion_gate(snapshot)


def _validated_rollback_evidence(
    snapshot: Mapping[str, Any],
    stage: str,
    cfg: StagedRolloutConfig,
) -> tuple[dict[str, Any] | None, list[str]]:
    value = snapshot.get("rollback_evidence")
    if not isinstance(value, Mapping):
        return None, [f"rollback_evidence_missing:{stage}"] if cfg.require_rollback_evidence else []
    artifact_path = str(value.get("artifact_path") or value.get("snapshot_path") or "").strip()
    digest = str(value.get("sha256") or value.get("artifact_sha256") or "").strip().lower()
    revision = str(value.get("baseline_revision") or value.get("revision") or "").strip()
    restorable = value.get("restorable") is True
    valid_digest = len(digest) == 64 and all(char in "0123456789abcdef" for char in digest)
    if not artifact_path or not valid_digest or not revision or not restorable:
        return None, [f"rollback_evidence_missing:{stage}"]
    if cfg.verify_rollback_artifacts:
        artifact = Path(artifact_path)
        if not artifact.is_file():
            return None, [f"rollback_evidence_invalid:{stage}:artifact_missing"]
        try:
            observed_digest = snapshot_sha256(artifact)
        except OSError as exc:
            return None, [
                f"rollback_evidence_invalid:{stage}:artifact_unreadable:{type(exc).__name__}"
            ]
        if observed_digest != digest:
            return None, [f"rollback_evidence_invalid:{stage}:sha256_mismatch"]
    return {
        "artifact_path": artifact_path,
        "sha256": digest,
        "baseline_revision": revision,
        "restorable": True,
    }, []


def _promotion_lineage_evidence(
    snapshot: Mapping[str, Any],
    stage: str,
    cfg: StagedRolloutConfig,
) -> tuple[dict[str, Any] | None, list[str]]:
    value = snapshot.get("promotion_lineage", snapshot.get("lineage"))
    if not isinstance(value, Mapping):
        return None, [f"promotion_lineage_missing:{stage}"] if cfg.require_promotion_lineage else []

    rollout_id = str(value.get("rollout_id") or value.get("run_id") or "").strip()
    lineage_stage = str(value.get("stage") or value.get("stage_name") or "").strip()
    baseline_digest = str(
        value.get("baseline_digest") or value.get("baseline_sha256") or ""
    ).strip()
    input_digest = str(
        value.get("input_digest")
        or value.get("summary_digest")
        or value.get("snapshot_input_digest")
        or ""
    ).strip()
    output_digest = str(
        value.get("output_digest")
        or value.get("snapshot_digest")
        or value.get("evidence_digest")
        or ""
    ).strip()
    revision = str(
        value.get("promotion_revision")
        or value.get("compiler_commit")
        or value.get("git_revision")
        or value.get("revision")
        or ""
    ).strip()
    produced_by = str(
        value.get("produced_by")
        or value.get("producer")
        or value.get("tool")
        or ""
    ).strip()

    failures: list[str] = []
    if not rollout_id:
        failures.append(f"promotion_lineage_incomplete:{stage}:rollout_id")
    if lineage_stage and lineage_stage != stage:
        failures.append(
            f"promotion_lineage_stage_mismatch:{stage}:{lineage_stage}"
        )
    if not lineage_stage:
        failures.append(f"promotion_lineage_incomplete:{stage}:stage")
    for name, digest in (
        ("baseline_digest", baseline_digest),
        ("input_digest", input_digest),
        ("output_digest", output_digest),
    ):
        if not _valid_digest_ref(digest):
            failures.append(f"promotion_lineage_incomplete:{stage}:{name}")
    if not revision:
        failures.append(f"promotion_lineage_incomplete:{stage}:promotion_revision")
    if not produced_by:
        failures.append(f"promotion_lineage_incomplete:{stage}:produced_by")
    if failures:
        return None, failures
    return {
        "rollout_id": rollout_id,
        "stage": stage,
        "baseline_digest": _normalized_digest_ref(baseline_digest),
        "input_digest": _normalized_digest_ref(input_digest),
        "output_digest": _normalized_digest_ref(output_digest),
        "promotion_revision": revision,
        "produced_by": produced_by,
    }, []


def _promotion_threshold_failures(
    snapshot: Mapping[str, Any],
    stage: str,
    cfg: StagedRolloutConfig,
) -> tuple[dict[str, Any], list[str]]:
    container = snapshot.get("promotion_thresholds")
    if not isinstance(container, Mapping):
        container = snapshot.get("promotion_efficacy")
    if not isinstance(container, Mapping):
        container = snapshot

    checks = (
        (
            "projection_p95_reduction",
            "projection_p95_seconds",
            (
                "projection_p95_reduction",
                "projection_p95_relative_reduction",
                "projection_p95_relative_improvement",
                "projection_p95_seconds_relative_reduction",
            ),
            (
                "baseline_projection_p95_seconds",
                "cold_projection_p95_seconds",
                "before_projection_p95_seconds",
                "control_projection_p95_seconds",
            ),
            (
                "candidate_projection_p95_seconds",
                "warm_projection_p95_seconds",
                "promoted_projection_p95_seconds",
                "after_projection_p95_seconds",
                "projection_p95_seconds",
            ),
            cfg.min_projection_p95_reduction,
            "reduction",
        ),
        (
            "task_to_accepted_patch_rate_improvement",
            "task_to_accepted_patch_rate",
            (
                "task_to_accepted_patch_rate_improvement",
                "task_to_accepted_patch_rate_relative_improvement",
            ),
            (
                "baseline_task_to_accepted_patch_rate",
                "before_task_to_accepted_patch_rate",
                "control_task_to_accepted_patch_rate",
            ),
            (
                "candidate_task_to_accepted_patch_rate",
                "promoted_task_to_accepted_patch_rate",
                "after_task_to_accepted_patch_rate",
            ),
            cfg.min_task_to_accepted_patch_rate_improvement,
            "improvement",
        ),
        (
            "state_to_merged_patch_lag_reduction",
            "state_to_merged_patch_lag_seconds",
            (
                "state_to_merged_patch_lag_reduction",
                "state_to_merged_patch_lag_relative_reduction",
                "state_to_merged_patch_lag_relative_improvement",
                "state_to_accepted_patch_lag_reduction",
                "state_to_accepted_patch_lag_relative_reduction",
                "state_to_accepted_patch_lag_relative_improvement",
            ),
            (
                "baseline_state_to_merged_patch_lag_seconds",
                "before_state_to_merged_patch_lag_seconds",
                "control_state_to_merged_patch_lag_seconds",
            ),
            (
                "candidate_state_to_merged_patch_lag_seconds",
                "promoted_state_to_merged_patch_lag_seconds",
                "after_state_to_merged_patch_lag_seconds",
                "state_to_merged_patch_lag_seconds",
            ),
            cfg.min_state_to_merged_patch_lag_reduction,
            "reduction",
        ),
    )

    metrics: dict[str, Any] = {}
    failures: list[str] = []
    for (
        metric_name,
        pair_name,
        observed_keys,
        before_keys,
        after_keys,
        minimum,
        direction,
    ) in checks:
        before, after = _paired_threshold_values(
            container,
            pair_name,
            before_keys,
            after_keys,
        )
        if before is not None and after is not None:
            if before <= 0.0 or after < 0.0:
                failures.append(
                    f"{metric_name}_invalid:{stage}:{before:g}->{after:g}"
                )
                continue
            observed = (after - before) / before
            if direction == "reduction":
                observed = (before - after) / before
            metrics[metric_name] = {
                "baseline": before,
                "candidate": after,
                "observed": round(observed, 12),
                "required": minimum,
            }
        else:
            observed = _threshold_observed_value(container, pair_name, observed_keys)
            if observed is None:
                failures.append(f"{metric_name}_missing:{stage}")
                continue
            metrics[metric_name] = {
                "observed": round(observed, 12),
                "required": minimum,
            }
        if observed + 1.0e-12 < minimum:
            failures.append(
                f"{metric_name}_below_threshold:{stage}:"
                f"{observed:g}<{minimum:g}"
            )
    return metrics, failures


def _paired_threshold_values(
    container: Mapping[str, Any],
    pair_name: str,
    before_keys: Sequence[str],
    after_keys: Sequence[str],
) -> tuple[float | None, float | None]:
    paired = container.get(pair_name)
    if isinstance(paired, Mapping):
        before = _first_finite(
            paired,
            ("baseline", "before", "control", "fixed_baseline", "cold"),
        )
        after = _first_finite(
            paired,
            ("candidate", "after", "promoted", "selected", "warm"),
        )
        if before is not None or after is not None:
            return before, after
    return _first_finite(container, before_keys), _first_finite(container, after_keys)


def _threshold_observed_value(
    container: Mapping[str, Any],
    pair_name: str,
    observed_keys: Sequence[str],
) -> float | None:
    paired = container.get(pair_name)
    if isinstance(paired, Mapping):
        observed = _first_finite(
            paired,
            (
                "observed",
                "relative_improvement",
                "relative_reduction",
                "improvement",
                "reduction",
            ),
        )
        if observed is not None:
            return observed
    return _first_finite(container, observed_keys)


def _normalized_digest_ref(value: str) -> str:
    text = str(value or "").strip().lower()
    return text if text.startswith("sha256:") else f"sha256:{text}"


def _valid_digest_ref(value: str) -> bool:
    text = str(value or "").strip().lower()
    if text.startswith("sha256:"):
        text = text[7:]
    return _valid_sha256(text)


def write_rollout_evidence(path: str | Path, payload: Mapping[str, Any]) -> None:
    """Atomically persist a gate decision or rollback manifest."""

    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    rendered = json.dumps(payload, allow_nan=False, indent=2, sort_keys=True) + "\n"
    fd, temporary = tempfile.mkstemp(prefix=f".{destination.name}.", dir=str(destination.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(rendered)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def write_text_artifact(path: str | Path, text: str) -> None:
    """Atomically persist a UTF-8 text artifact."""

    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{destination.name}.", dir=str(destination.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            if not text.endswith("\n"):
                handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def snapshot_sha256(path: str | Path) -> str:
    """Return a streaming SHA-256 digest for operator rollback evidence."""

    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_summary(path: str | Path) -> dict[str, Any]:
    summary_path = Path(path)
    with summary_path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"summary is not a JSON object: {summary_path}")
    return data


def hard_guardrail_metrics_csv() -> str:
    return ",".join(DEFAULT_HARD_GUARDRAIL_METRICS)


def rollout_gate(summary: Mapping[str, Any], config: RolloutGateConfig | None = None) -> RolloutGateResult:
    cfg = config or RolloutGateConfig()
    failures: list[str] = []
    warnings: list[str] = []
    metrics: dict[str, Any] = {}

    failures.extend(_fatal_status_failures(summary, cfg))
    failures.extend(_metric_regression_failures(summary, cfg, metrics))
    failures.extend(_source_copy_failures(summary, cfg, metrics))
    failures.extend(_representation_promotion_failures(summary, cfg, metrics, warnings))
    failures.extend(_multi_seed_rollout_failures(summary, cfg, metrics, warnings))
    failures.extend(_hammer_cycle_failures(summary, cfg, metrics, warnings))
    failures.extend(_todo_activity_failures(summary, cfg, metrics))
    failures.extend(_backend_availability_failures(summary, cfg, metrics, warnings))

    return RolloutGateResult(
        accepted=not failures,
        failures=failures,
        warnings=warnings,
        metrics=metrics,
    )


def external_validity_promotion_gate(
    payload: Mapping[str, Any],
    config: ExternalValidityPromotionConfig | None = None,
) -> RolloutGateResult:
    """Gate the final Hammer/Leanstral promotion on external validity evidence.

    The external-validity gate is intentionally a binder over persisted reports.
    It does not trust a single headline flag: each evidence domain must expose
    the schema, status, metrics, and cross-artifact identifiers needed to prove
    that the candidate was evaluated leak-free and can be rolled back.
    """

    cfg = config or ExternalValidityPromotionConfig()
    failures: list[str] = []
    warnings: list[str] = []
    metrics: dict[str, Any] = {
        "schema_version": EXTERNAL_VALIDITY_PROMOTION_SCHEMA_VERSION,
        "required_domains": list(cfg.required_domains),
        "required_binding_fields": list(cfg.required_binding_fields),
    }

    schema = str(payload.get("schema_version") or "").strip()
    if schema and schema != EXTERNAL_VALIDITY_PROMOTION_SCHEMA_VERSION:
        failures.append(f"external_validity_schema_mismatch:{schema}")
    metrics["input_schema_version"] = schema

    evidence_packets: dict[str, Mapping[str, Any]] = {}
    domain_metrics: dict[str, Any] = {}
    domain_status: dict[str, bool] = {}
    for domain in cfg.required_domains:
        packet_path, packet = _external_validity_packet(payload, domain)
        domain_entry: dict[str, Any] = {"present": packet is not None}
        if packet_path:
            domain_entry["evidence_path"] = packet_path
        if packet is None:
            failures.append(f"external_validity_evidence_missing:{domain}")
            domain_status[domain] = False
            domain_metrics[domain] = domain_entry
            continue
        evidence_packets[domain] = packet
        domain_failures, domain_warnings, domain_details = _external_domain_failures(
            domain,
            packet,
            cfg,
        )
        failures.extend(domain_failures)
        warnings.extend(domain_warnings)
        domain_entry.update(domain_details)
        domain_status[domain] = not domain_failures
        domain_metrics[domain] = domain_entry

    binding_metrics, binding_failures = _external_validity_binding_failures(
        payload,
        evidence_packets,
        cfg,
    )
    failures.extend(binding_failures)
    metrics["evidence_domains"] = domain_metrics
    metrics["domain_status"] = domain_status
    metrics["bindings"] = binding_metrics
    metrics["evidence_complete"] = all(domain_status.get(domain) for domain in cfg.required_domains)

    return RolloutGateResult(
        accepted=not failures,
        failures=list(dict.fromkeys(failures)),
        warnings=list(dict.fromkeys(warnings)),
        metrics=metrics,
    )


def render_external_validity_report(
    result: RolloutGateResult,
    *,
    title: str = "Hammer/Leanstral External Validity Promotion Gate",
) -> str:
    """Render a concise Markdown promotion report for operator review."""

    metrics = result.metrics
    lines = [
        f"# {title}",
        "",
        f"- Schema: `{metrics.get('schema_version', EXTERNAL_VALIDITY_PROMOTION_SCHEMA_VERSION)}`",
        f"- Decision: `{'accepted' if result.accepted else 'blocked'}`",
        f"- Evidence complete: `{bool(metrics.get('evidence_complete'))}`",
        f"- Failure count: `{len(result.failures)}`",
        "",
        "## Evidence Domains",
        "",
        "| Domain | Status | Key Evidence |",
        "| --- | --- | --- |",
    ]
    domains = metrics.get("evidence_domains")
    if isinstance(domains, Mapping):
        for domain in EXTERNAL_VALIDITY_REQUIRED_DOMAINS:
            entry = domains.get(domain)
            if not isinstance(entry, Mapping):
                continue
            status = "passed" if metrics.get("domain_status", {}).get(domain) else "blocked"
            detail = _external_report_detail(domain, entry)
            lines.append(f"| `{domain}` | `{status}` | {detail} |")
    lines.extend(["", "## Bindings", ""])
    bindings = metrics.get("bindings")
    if isinstance(bindings, Mapping):
        for field in EXTERNAL_VALIDITY_BINDING_FIELDS:
            values = bindings.get(field)
            if isinstance(values, Mapping):
                canonical = values.get("canonical")
                sources = values.get("sources")
                source_count = len(sources) if isinstance(sources, Mapping) else 0
                lines.append(
                    f"- `{field}`: `{canonical or 'missing'}` from `{source_count}` source(s)"
                )
    if result.failures:
        lines.extend(["", "## Failures", ""])
        lines.extend(f"- `{failure}`" for failure in result.failures)
    if result.warnings:
        lines.extend(["", "## Warnings", ""])
        lines.extend(f"- `{warning}`" for warning in result.warnings)
    lines.extend(
        [
            "",
            "## Gate Contract",
            "",
            "Promotion fails closed unless the evidence envelope binds leak-free splits, semantic metrics, typed decoding, uncertainty, fuzzing, hard negatives, multi-seed statistics, schema compatibility, poisoning defenses, external benchmark scores, and rollback readiness.",
            "",
        ]
    )
    return "\n".join(lines)


def compiler_system_promotion_gate(
    payload: Mapping[str, Any],
    config: CompilerSystemPromotionConfig | None = None,
) -> RolloutGateResult:
    """Promote only when every compiler-system gate is complete and reversible."""

    cfg = config or CompilerSystemPromotionConfig()
    failures: list[str] = []
    warnings: list[str] = []
    metrics: dict[str, Any] = {
        "schema_version": COMPILER_SYSTEM_PROMOTION_SCHEMA_VERSION,
        "required_domains": list(cfg.required_domains),
        "required_binding_fields": list(cfg.required_binding_fields),
    }

    schema = str(payload.get("schema_version") or "").strip()
    if schema and schema != COMPILER_SYSTEM_PROMOTION_SCHEMA_VERSION:
        failures.append(f"compiler_system_schema_mismatch:{schema}")
    metrics["input_schema_version"] = schema

    staged_result = _compiler_system_staged_result(payload, cfg)
    external_result = _compiler_system_external_validity_result(payload, cfg)
    domain_metrics: dict[str, Any] = {}
    domain_status: dict[str, bool] = {}
    evidence_packets: dict[str, Mapping[str, Any]] = {}

    if staged_result is not None:
        metrics["staged_rollout"] = staged_result.metrics
        failures.extend(f"staged_rollout:{failure}" for failure in staged_result.failures)
        warnings.extend(f"staged_rollout:{warning}" for warning in staged_result.warnings)
    elif cfg.require_staged_rollout:
        failures.append("staged_rollout_evidence_missing")
    if external_result is not None:
        metrics["external_validity"] = external_result.metrics
        failures.extend(
            f"external_validity:{failure}" for failure in external_result.failures
        )
        warnings.extend(
            f"external_validity:{warning}" for warning in external_result.warnings
        )
    elif cfg.require_external_validity:
        failures.append("external_validity_promotion_evidence_missing")

    for domain in cfg.required_domains:
        packet_path, packet = _compiler_system_domain_packet(payload, domain)
        entry: dict[str, Any] = {
            "present": packet is not None,
        }
        if packet_path:
            entry["evidence_path"] = packet_path
        if packet is None and domain == "external_validity" and external_result is not None:
            entry.update(
                {
                    "present": True,
                    "accepted": external_result.accepted,
                    "schema_version": EXTERNAL_VALIDITY_PROMOTION_SCHEMA_VERSION,
                }
            )
            domain_status[domain] = external_result.accepted
            domain_metrics[domain] = entry
            continue
        if packet is None and domain == "rollback_readiness":
            packet = _compiler_system_rollback_packet_from_subgates(
                staged_result,
                external_result,
            )
            if packet is not None:
                packet_path = "subgate.rollback_readiness"
                entry["present"] = True
                entry["evidence_path"] = packet_path
        if packet is None:
            failures.append(f"compiler_system_evidence_missing:{domain}")
            domain_status[domain] = False
            domain_metrics[domain] = entry
            continue
        evidence_packets[domain] = packet
        domain_failures, domain_warnings, details = _compiler_system_domain_failures(
            domain,
            packet,
            cfg,
            staged_result=staged_result,
            external_result=external_result,
        )
        failures.extend(domain_failures)
        warnings.extend(domain_warnings)
        entry.update(details)
        domain_status[domain] = not domain_failures
        domain_metrics[domain] = entry

    binding_metrics, binding_failures = _compiler_system_binding_failures(
        payload,
        evidence_packets,
        cfg,
    )
    failures.extend(binding_failures)
    metrics["evidence_domains"] = domain_metrics
    metrics["domain_status"] = domain_status
    metrics["bindings"] = binding_metrics
    metrics["evidence_complete"] = all(
        domain_status.get(domain) for domain in cfg.required_domains
    )
    metrics["rollback_ready"] = bool(domain_status.get("rollback_readiness"))
    metrics["promotion_decision"] = "accepted" if not failures else "blocked"

    return RolloutGateResult(
        accepted=not failures,
        failures=list(dict.fromkeys(failures)),
        warnings=list(dict.fromkeys(warnings)),
        metrics=metrics,
    )


def render_compiler_system_promotion_report(
    result: RolloutGateResult,
    *,
    title: str = "Hammer/Leanstral LegalIR Compiler System Promotion",
) -> str:
    """Render the final promotion decision as an operator-facing report."""

    metrics = result.metrics
    lines = [
        f"# {title}",
        "",
        f"- Schema: `{metrics.get('schema_version', COMPILER_SYSTEM_PROMOTION_SCHEMA_VERSION)}`",
        f"- Decision: `{'accepted' if result.accepted else 'blocked'}`",
        f"- Evidence complete: `{bool(metrics.get('evidence_complete'))}`",
        f"- Rollback ready: `{bool(metrics.get('rollback_ready'))}`",
        f"- Failure count: `{len(result.failures)}`",
        "",
        "## Promotion Domains",
        "",
        "| Domain | Status | Evidence |",
        "| --- | --- | --- |",
    ]
    domains = metrics.get("evidence_domains")
    statuses = metrics.get("domain_status")
    if isinstance(domains, Mapping):
        for domain in COMPILER_SYSTEM_REQUIRED_DOMAINS:
            entry = domains.get(domain)
            if not isinstance(entry, Mapping):
                continue
            passed = isinstance(statuses, Mapping) and statuses.get(domain) is True
            lines.append(
                f"| `{domain}` | `{'passed' if passed else 'blocked'}` | "
                f"{_compiler_system_report_detail(domain, entry)} |"
            )
    lines.extend(["", "## Required Conformance Capabilities", ""])
    conformance = (
        domains.get("conformance_evidence")
        if isinstance(domains, Mapping)
        else None
    )
    capabilities = (
        conformance.get("capabilities")
        if isinstance(conformance, Mapping)
        else None
    )
    for capability in COMPILER_SYSTEM_REQUIRED_CONFORMANCE_CAPABILITIES:
        status = "unknown"
        if isinstance(capabilities, Mapping):
            status = "passed" if capabilities.get(capability) is True else "blocked"
        lines.append(f"- `{capability}`: `{status}`")
    bindings = metrics.get("bindings")
    if isinstance(bindings, Mapping):
        lines.extend(["", "## Evidence Bindings", ""])
        for field in EXTERNAL_VALIDITY_BINDING_FIELDS:
            values = bindings.get(field)
            if not isinstance(values, Mapping):
                continue
            canonical = values.get("canonical")
            sources = values.get("sources")
            source_count = len(sources) if isinstance(sources, Mapping) else 0
            lines.append(
                f"- `{field}`: `{canonical or 'missing'}` from `{source_count}` source(s)"
            )
    if result.failures:
        lines.extend(["", "## Promotion Blockers", ""])
        lines.extend(f"- `{failure}`" for failure in result.failures)
    if result.warnings:
        lines.extend(["", "## Warnings", ""])
        lines.extend(f"- `{warning}`" for warning in result.warnings)
    lines.extend(
        [
            "",
            "## Rollback Contract",
            "",
            "Promotion is allowed only when the same evidence envelope proves complete conformance and an operator can disable or restore the promoted compiler system from recorded rollback metadata.",
            "",
        ]
    )
    return "\n".join(lines)


def _compiler_system_staged_result(
    payload: Mapping[str, Any],
    cfg: CompilerSystemPromotionConfig,
) -> RolloutGateResult | None:
    packet = _first_mapping_value(
        payload,
        (
            "staged_rollout",
            "staged_rollout_evidence",
            "rollout_stages",
            "snapshot_manifest",
        ),
    )
    if packet is None:
        raw = payload.get("snapshots", payload.get("stages"))
        if isinstance(raw, Sequence) and not isinstance(raw, (str, bytes, bytearray)):
            packet = {"snapshots": raw}
    if packet is None:
        return None
    if _looks_like_gate_decision(packet, STAGED_ROLLOUT_SCHEMA_VERSION):
        return _rollout_result_from_decision(packet)
    return staged_rollout_gate(
        packet,
        StagedRolloutConfig(
            require_all_stages=True,
            require_multi_seed_statistical_promotion=True,
            verify_rollback_artifacts=cfg.verify_rollback_artifacts,
        ),
    )


def _compiler_system_external_validity_result(
    payload: Mapping[str, Any],
    cfg: CompilerSystemPromotionConfig,
) -> RolloutGateResult | None:
    packet = _first_mapping_value(
        payload,
        (
            "external_validity",
            "external_validity_promotion",
            "external_validity_gate",
            "external_validity_evidence",
        ),
    )
    if packet is None and str(payload.get("schema_version") or "") == EXTERNAL_VALIDITY_PROMOTION_SCHEMA_VERSION:
        packet = payload
    if packet is None:
        return None
    if _looks_like_gate_decision(packet, EXTERNAL_VALIDITY_PROMOTION_SCHEMA_VERSION):
        return _rollout_result_from_decision(packet)
    return external_validity_promotion_gate(packet)


def _compiler_system_domain_packet(
    payload: Mapping[str, Any],
    domain: str,
) -> tuple[str, Mapping[str, Any] | None]:
    evidence = payload.get("evidence")
    aliases = COMPILER_SYSTEM_DOMAIN_ALIASES.get(domain, (domain,))
    containers: tuple[tuple[str, Mapping[str, Any]], ...] = (("", payload),)
    if isinstance(evidence, Mapping):
        containers = (("evidence", evidence),) + containers
    for prefix, container in containers:
        for key in aliases:
            value = container.get(key)
            if isinstance(value, Mapping):
                return f"{prefix + '.' if prefix else ''}{key}", value
    allowed = set(COMPILER_SYSTEM_DOMAIN_SCHEMA_VERSIONS.get(domain, ()))
    if domain == "external_validity":
        allowed.add(EXTERNAL_VALIDITY_PROMOTION_SCHEMA_VERSION)
    for path, value in _walk(payload):
        if not isinstance(value, Mapping):
            continue
        schema = _schema_version(value)
        schema_id = str(value.get("schema_version_id") or "").strip()
        if schema in allowed or schema_id in allowed:
            return path, value
    return "", None


def _compiler_system_domain_failures(
    domain: str,
    packet: Mapping[str, Any],
    cfg: CompilerSystemPromotionConfig,
    *,
    staged_result: RolloutGateResult | None,
    external_result: RolloutGateResult | None,
) -> tuple[list[str], list[str], dict[str, Any]]:
    failures: list[str] = []
    warnings: list[str] = []
    details: dict[str, Any] = {"schema_version": _schema_version(packet)}
    failures.extend(_compiler_system_generic_status_failures(domain, packet))

    if domain == "evaluation_integrity":
        if staged_result is not None and not staged_result.accepted:
            failures.append("evaluation_integrity:staged_rollout_blocked")
        if external_result is not None:
            external_domains = external_result.metrics.get("domain_status")
            if isinstance(external_domains, Mapping):
                for required in (
                    "leak_free_splits",
                    "multi_seed_statistics",
                    "hard_negatives",
                ):
                    if external_domains.get(required) is not True:
                        failures.append(
                            f"evaluation_integrity:external_domain_blocked:{required}"
                        )
        leak_free = packet.get("leak_free_splits") is True or packet.get("leakage_count") in (0, 0.0)
        fixed_canary = packet.get("fixed_canary") is True or packet.get("fixed_sample_set") is True
        multi_seed = packet.get("multi_seed") is True or packet.get("multi_seed_statistics") is True
        if not leak_free:
            failures.append("evaluation_integrity:leak_free_split_evidence_missing")
        if not fixed_canary:
            failures.append("evaluation_integrity:fixed_canary_evidence_missing")
        if not multi_seed:
            failures.append("evaluation_integrity:multi_seed_evidence_missing")
        details.update(
            {
                "leak_free_splits": leak_free,
                "fixed_canary": fixed_canary,
                "multi_seed": multi_seed,
            }
        )
        return failures, warnings, details

    if domain == "external_validity":
        if external_result is not None and not external_result.accepted:
            failures.append("external_validity:promotion_gate_blocked")
        if packet.get("accepted") is False:
            failures.append("external_validity:accepted_false")
        details["accepted"] = packet.get("accepted", external_result.accepted if external_result else None)
        return failures, warnings, details

    expected_schemas = COMPILER_SYSTEM_DOMAIN_SCHEMA_VERSIONS.get(domain, ())
    if expected_schemas and _schema_version(packet) not in expected_schemas:
        schema_id = str(packet.get("schema_version_id") or "").strip()
        if schema_id not in expected_schemas:
            failures.append(
                f"{domain}:schema_mismatch:{_schema_version(packet) or schema_id or 'missing'}"
            )

    if domain == "compiler_source_maps":
        valid = _truthy_path(packet, ("valid", "source_map_validation.valid", "traceability_complete"))
        if not valid:
            failures.append("compiler_source_maps:traceability_not_validated")
        details["traceability_complete"] = valid
    elif domain == "symbols":
        unresolved = _first_finite(
            packet,
            ("unresolved_count", "unresolved_symbol_count", "error_count"),
        )
        if unresolved is None:
            unresolved = 0.0 if _truthy_path(packet, ("valid", "resolved", "allowed_for_use")) else None
        if unresolved is None or unresolved > 0:
            failures.append(
                f"symbols:unresolved_symbols:{'missing' if unresolved is None else f'{unresolved:g}'}"
            )
        details["unresolved_count"] = unresolved
    elif domain == "citations":
        unresolved = _first_finite(
            packet,
            ("unresolved_count", "unresolved_citation_count", "ambiguous_count"),
        )
        if unresolved is None:
            unresolved = 0.0 if _truthy_path(packet, ("valid", "resolved", "allowed_for_use")) else None
        if unresolved is None or unresolved > 0:
            failures.append(
                f"citations:unresolved_or_ambiguous:{'missing' if unresolved is None else f'{unresolved:g}'}"
            )
        details["unresolved_count"] = unresolved
    elif domain == "temporal_authority":
        complete = _truthy_path(packet, ("authority_complete", "valid", "accepted"))
        if not complete:
            failures.append("temporal_authority:authority_not_complete")
        for key in ("open_conflict_count", "expired_authority_count", "unresolved_count"):
            value = _finite_float(packet.get(key))
            if value is not None and value > 0:
                failures.append(f"temporal_authority:{key}:{value:g}")
        details["authority_complete"] = complete
    elif domain == "ambiguity":
        unresolved = _first_finite(packet, ("unresolved_count", "unresolved_ambiguity_count"))
        if unresolved is None:
            unresolved = 0.0 if _truthy_path(packet, ("resolved", "all_resolved", "accepted")) else None
        if unresolved is None or unresolved > 0:
            failures.append(
                f"ambiguity:unresolved:{'missing' if unresolved is None else f'{unresolved:g}'}"
            )
        if packet.get("learned_label_allowed") is True:
            failures.append("ambiguity:learned_label_allowed")
        details["unresolved_count"] = unresolved
    elif domain == "pass_management":
        if not _truthy_path(packet, ("deterministic_order", "deterministic_output_order", "valid")):
            failures.append("pass_management:deterministic_order_missing")
        if packet.get("source_map_preserved") is False:
            failures.append("pass_management:source_map_not_preserved")
        details["deterministic_order"] = _truthy_path(packet, ("deterministic_order", "deterministic_output_order", "valid"))
    elif domain == "backend_conformance":
        allowed = packet.get("promotion_allowed")
        if allowed is not True and not _truthy_path(packet, ("accepted", "valid")):
            failures.append("backend_conformance:promotion_not_allowed")
        details["promotion_allowed"] = allowed
    elif domain == "reproducible_builds":
        reproducible = _truthy_path(packet, ("reproducible", "deterministic", "valid"))
        digest = _first_summary_string(
            packet,
            ("build_digest", "compile_digest", "manifest_digest", "sha256"),
        )
        if not reproducible:
            failures.append("reproducible_builds:not_reproducible")
        if not digest:
            failures.append("reproducible_builds:digest_missing")
        details.update({"reproducible": reproducible, "digest_present": bool(digest)})
    elif domain == "incremental_compilation":
        correct = _truthy_path(packet, ("cache_correct", "invalidation_valid", "successful", "valid"))
        if not correct:
            failures.append("incremental_compilation:cache_or_invalidation_not_valid")
        details["cache_correct"] = correct
    elif domain == "semantic_diffs":
        available = _truthy_path(packet, ("available", "valid", "classified", "accepted"))
        unclassified = _first_finite(packet, ("unclassified_change_count", "unclassified_changes"))
        if not available:
            failures.append("semantic_diffs:not_available")
        if unclassified is not None and unclassified > 0:
            failures.append(f"semantic_diffs:unclassified_changes:{unclassified:g}")
        details["available"] = available
    elif domain == "proof_carrying_artifacts":
        valid = _truthy_path(packet, ("valid", "proof_checked", "trusted", "accepted"))
        if not valid:
            failures.append("proof_carrying_artifacts:not_validated")
        if packet.get("trusted") is False or packet.get("native_reconstruction_verified") is False:
            failures.append("proof_carrying_artifacts:trust_or_reconstruction_missing")
        details["valid"] = valid
    elif domain == "diagnostics":
        error_count = _first_finite(packet, ("error_count", "errors"))
        lsp_ready = _truthy_path(packet, ("lsp_ready", "lsp_diagnostics_ready", "valid", "accepted"))
        if not lsp_ready:
            failures.append("diagnostics:lsp_not_ready")
        if error_count is not None and error_count > 0:
            failures.append(f"diagnostics:open_errors:{error_count:g}")
        details.update({"lsp_ready": lsp_ready, "error_count": error_count})
    elif domain == "apis":
        parity = _truthy_path(packet, ("cli_api_parity", "daemon_free", "valid", "accepted"))
        if not parity:
            failures.append("apis:cli_api_parity_missing")
        details["cli_api_parity"] = parity
    elif domain == "interoperability":
        conformant = _truthy_path(packet, ("round_trip_conformant", "conformant", "valid", "accepted"))
        explicit_loss = _truthy_path(packet, ("loss_markers_explicit", "unsupported_diagnostics_explicit", "loss_explicit"))
        if not conformant:
            failures.append("interoperability:round_trip_not_conformant")
        if not explicit_loss:
            failures.append("interoperability:loss_markers_not_explicit")
        details.update({"round_trip_conformant": conformant, "loss_markers_explicit": explicit_loss})
    elif domain == "conformance_evidence":
        conformance_failures, conformance_details = _compiler_conformance_failures(
            packet,
            cfg,
        )
        failures.extend(conformance_failures)
        details.update(conformance_details)
    elif domain == "rollback_readiness":
        rollback_failures, rollback_details = _compiler_system_rollback_failures(packet)
        failures.extend(rollback_failures)
        details.update(rollback_details)
    return failures, warnings, details


def _compiler_conformance_failures(
    packet: Mapping[str, Any],
    cfg: CompilerSystemPromotionConfig,
) -> tuple[list[str], dict[str, Any]]:
    failures: list[str] = []
    capabilities = _compiler_conformance_capability_status(packet)
    details: dict[str, Any] = {"capabilities": capabilities}
    for capability in cfg.required_conformance_capabilities:
        if capabilities.get(capability) is not True:
            failures.append(f"conformance_evidence:capability_missing:{capability}")
    failed = _string_sequence(packet.get("failed_capabilities"))
    if failed:
        failures.append("conformance_evidence:failed_capabilities:" + ",".join(failed))
    if packet.get("conformance_suite_passed") is False or packet.get("passed") is False:
        failures.append("conformance_evidence:suite_not_passed")
    report_path = _first_summary_string(packet, ("report_path", "artifact_path", "path"))
    details["report_path"] = report_path
    if cfg.require_conformance_report and not report_path and not capabilities:
        failures.append("conformance_evidence:report_missing")
    return failures, details


def _compiler_conformance_capability_status(packet: Mapping[str, Any]) -> dict[str, bool]:
    result: dict[str, bool] = {}
    raw = packet.get("required_capabilities", packet.get("capabilities"))
    if isinstance(raw, Mapping):
        for capability in COMPILER_SYSTEM_REQUIRED_CONFORMANCE_CAPABILITIES:
            value = raw.get(capability)
            if isinstance(value, Mapping):
                status = str(value.get("status") or "").strip().lower()
                result[capability] = (
                    value.get("passed") is True
                    or value.get("required") is True
                    or status in {"passed", "implemented", "required", "accepted"}
                ) and value.get("failed") is not True
            elif isinstance(value, bool):
                result[capability] = value
            elif value is not None:
                result[capability] = str(value).strip().lower() in {
                    "passed",
                    "implemented",
                    "required",
                    "accepted",
                }
    elif isinstance(raw, Sequence) and not isinstance(raw, (str, bytes, bytearray)):
        seen = {str(item) for item in raw}
        for capability in COMPILER_SYSTEM_REQUIRED_CONFORMANCE_CAPABILITIES:
            result[capability] = capability in seen
    report_text = str(packet.get("report_text") or packet.get("markdown") or "")
    if not report_text:
        report_path = _first_summary_string(packet, ("report_path", "artifact_path", "path"))
        if report_path:
            try:
                candidate = Path(report_path)
                if candidate.is_file():
                    report_text = candidate.read_text(encoding="utf-8")
            except OSError:
                report_text = ""
    if report_text:
        for capability in COMPILER_SYSTEM_REQUIRED_CONFORMANCE_CAPABILITIES:
            if capability in report_text and "No failed capabilities" in report_text:
                result.setdefault(capability, True)
    return result


def _compiler_system_rollback_failures(
    packet: Mapping[str, Any],
) -> tuple[list[str], dict[str, Any]]:
    failures: list[str] = []
    rollback_id = _first_summary_string(
        packet,
        ("rollback_id", "rollback_metadata.rollback_id"),
    )
    disable_action = _first_summary_string(
        packet,
        ("disable_action", "rollback_metadata.disable_action"),
    )
    restorable = (
        packet.get("restorable") is True
        or _truthy_path(packet, ("rollback_metadata.restorable",))
        or bool(disable_action)
    )
    if not rollback_id:
        failures.append("rollback_readiness:rollback_id_missing")
    if not restorable:
        failures.append("rollback_readiness:not_restorable")
    if packet.get("rollback_required") is True:
        failures.append("rollback_readiness:rollback_already_required")
    return failures, {
        "rollback_id": rollback_id,
        "disable_action": disable_action,
        "restorable": restorable,
    }


def _compiler_system_rollback_packet_from_subgates(
    staged_result: RolloutGateResult | None,
    external_result: RolloutGateResult | None,
) -> Mapping[str, Any] | None:
    external_domains = (
        external_result.metrics.get("evidence_domains")
        if external_result is not None
        else None
    )
    if isinstance(external_domains, Mapping):
        rollback = external_domains.get("rollback_readiness")
        if isinstance(rollback, Mapping):
            return rollback
    if staged_result is None:
        return None
    rollback = staged_result.metrics.get("rollback_evidence")
    if not isinstance(rollback, Mapping) or not rollback:
        return None
    return {
        "rollback_id": "staged-rollout-rollback",
        "restorable": True,
        "stage_rollback_evidence": rollback,
    }


def _compiler_system_binding_failures(
    payload: Mapping[str, Any],
    evidence_packets: Mapping[str, Mapping[str, Any]],
    cfg: CompilerSystemPromotionConfig,
) -> tuple[dict[str, Any], list[str]]:
    relevant = {
        domain: packet
        for domain, packet in evidence_packets.items()
        if domain
        in {
            "evaluation_integrity",
            "external_validity",
            "conformance_evidence",
            "rollback_readiness",
        }
    }
    return _external_validity_binding_failures(
        payload,
        relevant,
        ExternalValidityPromotionConfig(
            required_binding_fields=cfg.required_binding_fields
        ),
    )


def _compiler_system_generic_status_failures(
    domain: str,
    packet: Mapping[str, Any],
) -> list[str]:
    failures = _status_failures(domain, packet)
    for key in ("missing_evidence", "missing_capabilities", "open_blockers"):
        items = _string_sequence(packet.get(key))
        if items:
            failures.append(f"{domain}:{key}:" + ",".join(items))
    return failures


def _compiler_system_report_detail(domain: str, entry: Mapping[str, Any]) -> str:
    if not entry.get("present"):
        return "`missing`"
    for key in (
        "schema_version",
        "promotion_allowed",
        "traceability_complete",
        "unresolved_count",
        "authority_complete",
        "rollback_id",
        "report_path",
    ):
        value = entry.get(key)
        if value not in (None, "", []):
            return f"`{key}={value}`"
    return "`present`"


def _first_mapping_value(
    payload: Mapping[str, Any],
    keys: Sequence[str],
) -> Mapping[str, Any] | None:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, Mapping):
            return value
    return None


def _looks_like_gate_decision(
    packet: Mapping[str, Any],
    schema_version: str,
) -> bool:
    return (
        "accepted" in packet
        and "metrics" in packet
        and str(packet.get("schema_version") or "") == schema_version
    )


def _rollout_result_from_decision(packet: Mapping[str, Any]) -> RolloutGateResult:
    metrics = packet.get("metrics")
    failures = _string_sequence(packet.get("failures"))
    warnings = _string_sequence(packet.get("warnings"))
    return RolloutGateResult(
        accepted=packet.get("accepted") is True and not failures,
        failures=failures,
        warnings=warnings,
        metrics=dict(metrics) if isinstance(metrics, Mapping) else {},
    )


def _truthy_path(payload: Mapping[str, Any], paths: Sequence[str]) -> bool:
    for path in paths:
        current: Any = payload
        for part in path.split("."):
            if not isinstance(current, Mapping):
                current = None
                break
            current = current.get(part)
        if current is True:
            return True
        if isinstance(current, str) and current.strip().lower() in {
            "true",
            "valid",
            "passed",
            "accepted",
            "complete",
            "conformant",
            "succeeded",
        }:
            return True
    return False


def _external_validity_packet(
    payload: Mapping[str, Any],
    domain: str,
) -> tuple[str, Mapping[str, Any] | None]:
    evidence = payload.get("evidence")
    aliases = EXTERNAL_VALIDITY_EVIDENCE_ALIASES.get(domain, (domain,))
    containers: tuple[tuple[str, Mapping[str, Any]], ...] = (("", payload),)
    if isinstance(evidence, Mapping):
        containers = (("evidence", evidence),) + containers
    for prefix, container in containers:
        for key in aliases:
            value = container.get(key)
            if isinstance(value, Mapping):
                return f"{prefix + '.' if prefix else ''}{key}", value
    schemas = _external_domain_schema_versions(domain)
    for path, value in _walk(payload):
        if not isinstance(value, Mapping):
            continue
        schema = _schema_version(value)
        schema_id = str(value.get("schema_version_id") or "").strip()
        if schema in schemas or schema_id in schemas:
            return path, value
    return "", None


def _external_domain_failures(
    domain: str,
    packet: Mapping[str, Any],
    cfg: ExternalValidityPromotionConfig,
) -> tuple[list[str], list[str], dict[str, Any]]:
    if domain == "leak_free_splits":
        return _leak_free_split_failures(packet)
    if domain == "semantic_metrics":
        return _semantic_metric_failures(packet, cfg)
    if domain == "typed_decoding":
        return _typed_decoding_failures(packet, cfg)
    if domain == "uncertainty":
        return _uncertainty_failures(packet)
    if domain == "fuzzing":
        return _fuzzing_failures(packet, cfg)
    if domain == "hard_negatives":
        return _hard_negative_failures(packet, cfg)
    if domain == "multi_seed_statistics":
        result = multi_seed_promotion_gate(packet)
        return (
            [f"multi_seed_statistics:{failure}" for failure in result.failures],
            list(result.warnings),
            {
                "schema_version": _schema_version(packet),
                "accepted": result.accepted,
                "metrics": result.metrics,
            },
        )
    if domain == "schema_compatibility":
        return _schema_compatibility_failures(packet, cfg)
    if domain == "poisoning_defenses":
        return _poisoning_defense_failures(packet, cfg)
    if domain == "external_benchmark_scores":
        return _external_benchmark_failures(packet, cfg)
    if domain == "rollback_readiness":
        return _rollback_readiness_failures(packet)
    return [f"external_validity_unknown_domain:{domain}"], [], {
        "schema_version": _schema_version(packet)
    }


def _leak_free_split_failures(
    packet: Mapping[str, Any],
) -> tuple[list[str], list[str], dict[str, Any]]:
    failures = _schema_failures("leak_free_splits", packet, (LEGAL_IR_EVAL_SPLITS_SCHEMA_VERSION,))
    failures.extend(_status_failures("leak_free_splits", packet))
    split_guard = split_guard_from_payload(packet)
    details: dict[str, Any] = {"schema_version": _schema_version(packet)}
    if split_guard is not None:
        details["split_guard"] = split_guard.to_dict()
    if split_guard_blocks_operation(packet, REPRESENTATION_PROMOTION_OPERATION):
        failures.append("leak_free_splits:representation_promotion_blocked")
    leakage_count = _first_finite(
        packet,
        (
            "leakage_count",
            "protected_split_leakage_count",
            "cross_split_leakage_count",
            "duplicate_leakage_count",
        ),
    )
    if leakage_count is not None:
        details["leakage_count"] = leakage_count
        if leakage_count > 0:
            failures.append(f"leak_free_splits:leakage_detected:{leakage_count:g}")
    for key in ("leaks", "leakage", "violations", "split_leaks"):
        value = packet.get(key)
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
            details[f"{key}_count"] = len(value)
            if value:
                failures.append(f"leak_free_splits:{key}_present:{len(value)}")
    allowed = packet.get("operation_allowed", packet.get("representation_promotion_allowed"))
    if allowed is False:
        failures.append("leak_free_splits:operation_not_authorized")
    return failures, [], details


def _semantic_metric_failures(
    packet: Mapping[str, Any],
    cfg: ExternalValidityPromotionConfig,
) -> tuple[list[str], list[str], dict[str, Any]]:
    failures = _schema_failures(
        "semantic_metrics",
        packet,
        (LEGAL_IR_SEMANTIC_METRICS_SCHEMA_VERSION,),
    )
    failures.extend(_status_failures("semantic_metrics", packet))
    values = _semantic_scores(packet)
    details: dict[str, Any] = {
        "schema_version": _schema_version(packet),
        "scores": dict(sorted(values.items())),
    }
    for metric in SEMANTIC_EQUIVALENCE_REQUIRED_METRICS:
        value = values.get(metric)
        if value is None:
            failures.append(f"semantic_metrics:metric_missing:{metric}")
        elif value + 1.0e-12 < cfg.min_semantic_score:
            failures.append(
                f"semantic_metrics:metric_below_threshold:{metric}:"
                f"{value:g}<{cfg.min_semantic_score:g}"
            )
    return failures, [], details


def _typed_decoding_failures(
    packet: Mapping[str, Any],
    cfg: ExternalValidityPromotionConfig,
) -> tuple[list[str], list[str], dict[str, Any]]:
    failures = _schema_failures(
        "typed_decoding",
        packet,
        (LEGAL_IR_GRAMMAR_DECODER_SCHEMA_VERSION,),
    )
    failures.extend(_status_failures("typed_decoding", packet))
    metrics = packet.get("metrics") if isinstance(packet.get("metrics"), Mapping) else {}
    success = _first_finite(
        packet,
        (
            "legal_ir_grammar_syntactic_validity_success_rate",
            "syntactic_validity_success_rate",
            "typed_decode_success_rate",
            "accepted_rate",
        ),
    )
    if success is None and isinstance(metrics, Mapping):
        success = _first_finite(
            metrics,
            (
                "legal_ir_grammar_syntactic_validity_success_rate",
                "syntactic_validity_success_rate",
                "typed_decode_success_rate",
                "accepted_rate",
            ),
        )
    source_copy = _first_finite(
        packet,
        (
            "legal_ir_grammar_source_copy_placeholder_penalty",
            "source_copy_placeholder_penalty",
            "source_copy_penalty",
        ),
    )
    if source_copy is None and isinstance(metrics, Mapping):
        source_copy = _first_finite(
            metrics,
            (
                "legal_ir_grammar_source_copy_placeholder_penalty",
                "source_copy_placeholder_penalty",
                "source_copy_penalty",
            ),
        )
    rejection_count = _first_finite(
        packet,
        ("rejection_count", "legal_ir_grammar_rejection_count", "invalid_count"),
    )
    if rejection_count is None and isinstance(metrics, Mapping):
        rejection_count = _first_finite(
            metrics,
            ("rejection_count", "legal_ir_grammar_rejection_count", "invalid_count"),
        )
    details = {
        "schema_version": _schema_version(packet),
        "success_rate": success,
        "source_copy_penalty": source_copy,
        "rejection_count": rejection_count,
    }
    if success is None:
        failures.append("typed_decoding:success_rate_missing")
    elif success + 1.0e-12 < cfg.min_typed_decoding_success_rate:
        failures.append(
            "typed_decoding:success_rate_below_threshold:"
            f"{success:g}<{cfg.min_typed_decoding_success_rate:g}"
        )
    if source_copy is None:
        failures.append("typed_decoding:source_copy_penalty_missing")
    elif source_copy > cfg.max_typed_decoding_source_copy_penalty + 1.0e-12:
        failures.append(
            "typed_decoding:source_copy_penalty:"
            f"{source_copy:g}>{cfg.max_typed_decoding_source_copy_penalty:g}"
        )
    if rejection_count is not None and rejection_count > 0:
        failures.append(f"typed_decoding:rejections_present:{rejection_count:g}")
    return failures, [], details


def _uncertainty_failures(
    packet: Mapping[str, Any],
) -> tuple[list[str], list[str], dict[str, Any]]:
    failures = _schema_failures("uncertainty", packet, (LEGAL_IR_UNCERTAINTY_SCHEMA_VERSION,))
    failures.extend(_status_failures("uncertainty", packet))
    block_reasons = _string_sequence(packet.get("block_reasons"))
    failed_families = _string_sequence(packet.get("failed_families"))
    unsupported = _string_sequence(packet.get("unsupported_guidance_ids"))
    if block_reasons:
        failures.append("uncertainty:block_reasons:" + ",".join(block_reasons))
    if failed_families:
        failures.append("uncertainty:failed_families:" + ",".join(failed_families))
    if unsupported:
        failures.append("uncertainty:unsupported_guidance:" + ",".join(unsupported))
    return failures, [], {
        "schema_version": _schema_version(packet),
        "block_reasons": block_reasons,
        "failed_families": failed_families,
        "unsupported_guidance_ids": unsupported,
    }


def _fuzzing_failures(
    packet: Mapping[str, Any],
    cfg: ExternalValidityPromotionConfig,
) -> tuple[list[str], list[str], dict[str, Any]]:
    failures = _schema_failures("fuzzing", packet, (LEGAL_IR_FUZZING_SCHEMA_VERSION,))
    failures.extend(_status_failures("fuzzing", packet))
    mutation_count = _first_finite(packet, ("mutation_count", "metamorphic_mutation_count"))
    trusted_negative_count = _first_finite(
        packet,
        ("trusted_negative_count", "trusted_negative_candidate_count"),
    )
    failed_mutations = _string_sequence(packet.get("failed_mutation_ids"))
    if mutation_count is None or mutation_count < cfg.min_fuzzing_mutation_count:
        failures.append(
            "fuzzing:mutation_count:"
            f"{0 if mutation_count is None else mutation_count:g}<"
            f"{cfg.min_fuzzing_mutation_count}"
        )
    if trusted_negative_count is None or trusted_negative_count < cfg.min_trusted_negative_count:
        failures.append(
            "fuzzing:trusted_negative_count:"
            f"{0 if trusted_negative_count is None else trusted_negative_count:g}<"
            f"{cfg.min_trusted_negative_count}"
        )
    if failed_mutations:
        failures.append("fuzzing:failed_mutations:" + ",".join(failed_mutations))
    return failures, [], {
        "schema_version": _schema_version(packet),
        "mutation_count": mutation_count,
        "trusted_negative_count": trusted_negative_count,
        "failed_mutation_ids": failed_mutations,
    }


def _hard_negative_failures(
    packet: Mapping[str, Any],
    cfg: ExternalValidityPromotionConfig,
) -> tuple[list[str], list[str], dict[str, Any]]:
    failures = _schema_failures(
        "hard_negatives",
        packet,
        (LEGAL_IR_HARD_NEGATIVE_EFFECT_SCHEMA_VERSION, LEGAL_IR_HARD_NEGATIVE_SCHEMA_VERSION),
    )
    failures.extend(_status_failures("hard_negatives", packet))
    reduction = _first_finite(packet, ("false_positive_reduction", "semantic_false_positive_reduction"))
    negative_count = _first_finite(packet, ("negative_example_count", "accepted_count"))
    trusted_positive_count = _first_finite(packet, ("trusted_positive_count",))
    if packet.get("hard_negative_guard_passed") is False:
        failures.append("hard_negatives:hard_negative_guard_failed")
    if packet.get("trusted_positive_guard_passed") is False:
        failures.append("hard_negatives:trusted_positive_guard_failed")
    if reduction is None:
        failures.append("hard_negatives:false_positive_reduction_missing")
    elif reduction + 1.0e-12 < cfg.min_hard_negative_false_positive_reduction:
        failures.append(
            "hard_negatives:false_positive_reduction_below_threshold:"
            f"{reduction:g}<{cfg.min_hard_negative_false_positive_reduction:g}"
        )
    if negative_count is None or negative_count <= 0:
        failures.append("hard_negatives:negative_examples_missing")
    if trusted_positive_count is None or trusted_positive_count <= 0:
        failures.append("hard_negatives:trusted_positive_evidence_missing")
    return failures, [], {
        "schema_version": _schema_version(packet),
        "false_positive_reduction": reduction,
        "negative_example_count": negative_count,
        "trusted_positive_count": trusted_positive_count,
    }


def _schema_compatibility_failures(
    packet: Mapping[str, Any],
    cfg: ExternalValidityPromotionConfig,
) -> tuple[list[str], list[str], dict[str, Any]]:
    failures: list[str] = []
    schema_id = str(packet.get("schema_version_id") or "").strip()
    schema = _schema_version(packet)
    if schema_id and schema_id != LEGAL_IR_SCHEMA_EVOLUTION_SCHEMA_VERSION:
        failures.append(f"schema_compatibility:schema_version_id_mismatch:{schema_id}")
    elif not schema_id and schema != LEGAL_IR_SCHEMA_EVOLUTION_SCHEMA_VERSION:
        failures.append(f"schema_compatibility:schema_mismatch:{schema or 'missing'}")
    failures.extend(_status_failures("schema_compatibility", packet))
    reusable = packet.get("reusable")
    compatibility = str(packet.get("compatibility") or "").strip()
    issues = packet.get("issues")
    issue_count = len(issues) if isinstance(issues, Sequence) and not isinstance(issues, (str, bytes, bytearray)) else None
    if cfg.require_schema_reusable and reusable is not True:
        failures.append("schema_compatibility:not_reusable")
    if compatibility and compatibility != "compatible":
        failures.append(f"schema_compatibility:not_compatible:{compatibility}")
    if isinstance(issues, Sequence) and not isinstance(issues, (str, bytes, bytearray)):
        for index, issue in enumerate(issues):
            if not isinstance(issue, Mapping):
                continue
            severity = str(issue.get("severity") or "").strip().lower()
            if severity == "error":
                code = str(issue.get("code") or index)
                failures.append(f"schema_compatibility:error_issue:{code}")
    return failures, [], {
        "schema_version": schema,
        "schema_version_id": schema_id,
        "compatibility": compatibility,
        "reusable": reusable,
        "issue_count": issue_count,
    }


def _poisoning_defense_failures(
    packet: Mapping[str, Any],
    cfg: ExternalValidityPromotionConfig,
) -> tuple[list[str], list[str], dict[str, Any]]:
    failures = _schema_failures(
        "poisoning_defenses",
        packet,
        (LEGAL_IR_PREMISE_SECURITY_SCHEMA_VERSION,),
    )
    failures.extend(_status_failures("poisoning_defenses", packet))
    hard_rule = _first_string(
        packet,
        ("hard_rule", "legal_source_text_rule", "data_rule"),
    )
    if not hard_rule:
        hard_rule = _find_string_value(packet, LEGAL_SOURCE_TEXT_DATA_RULE)
    if cfg.require_poisoning_hard_rule and hard_rule != LEGAL_SOURCE_TEXT_DATA_RULE:
        failures.append(
            "poisoning_defenses:hard_rule_missing:"
            f"{hard_rule or 'missing'}"
        )
    if packet.get("poisoned_payloads_rejected") is False:
        failures.append("poisoning_defenses:poisoned_payloads_not_rejected")
    if packet.get("blocks_training") is False:
        failures.append("poisoning_defenses:does_not_block_training")
    if packet.get("blocks_promotion") is False:
        failures.append("poisoning_defenses:does_not_block_promotion")
    rejected_count = _first_finite(packet, ("rejected_count", "poisoned_rejected_count"))
    tested = _string_sequence(packet.get("tested_poisoning_families"))
    if rejected_count is None and not tested and packet.get("poisoned_payloads_rejected") is not True:
        failures.append("poisoning_defenses:rejection_evidence_missing")
    return failures, [], {
        "schema_version": _schema_version(packet),
        "hard_rule": hard_rule,
        "rejected_count": rejected_count,
        "tested_poisoning_families": tested,
    }


def _external_benchmark_failures(
    packet: Mapping[str, Any],
    cfg: ExternalValidityPromotionConfig,
) -> tuple[list[str], list[str], dict[str, Any]]:
    failures = _schema_failures(
        "external_benchmark_scores",
        packet,
        (LEGAL_IR_EXTERNAL_BENCHMARK_REPORT_SCHEMA_VERSION,),
    )
    failures.extend(_status_failures("external_benchmark_scores", packet))
    external = packet.get("external_validity")
    if not isinstance(external, Mapping):
        external = packet
    score = _first_finite(external, ("external_validity_score", "score", "accepted_rate"))
    packet_count = _first_finite(external, ("packet_count", "sample_count", "evaluated_count"))
    failed_packets = _string_sequence(external.get("failed_packet_ids"))
    hard_guardrail = str(packet.get("hard_guardrail") or "").strip()
    separate = packet.get("separate_from_internal_canary_metrics")
    if score is None:
        failures.append("external_benchmark_scores:score_missing")
    elif score + 1.0e-12 < cfg.min_external_validity_score:
        failures.append(
            "external_benchmark_scores:score_below_threshold:"
            f"{score:g}<{cfg.min_external_validity_score:g}"
        )
    if packet_count is None or packet_count < cfg.min_external_packet_count:
        failures.append(
            "external_benchmark_scores:packet_count:"
            f"{0 if packet_count is None else packet_count:g}<"
            f"{cfg.min_external_packet_count}"
        )
    if failed_packets:
        failures.append("external_benchmark_scores:failed_packets:" + ",".join(failed_packets))
    if hard_guardrail and hard_guardrail != EXTERNAL_BENCHMARK_HARD_GUARDRAIL:
        failures.append(f"external_benchmark_scores:hard_guardrail_mismatch:{hard_guardrail}")
    elif not hard_guardrail:
        failures.append("external_benchmark_scores:hard_guardrail_missing")
    if cfg.require_external_benchmark_separate_from_canary and separate is not True:
        failures.append("external_benchmark_scores:not_separate_from_internal_canary")
    return failures, [], {
        "schema_version": _schema_version(packet),
        "external_validity_score": score,
        "packet_count": packet_count,
        "failed_packet_ids": failed_packets,
        "separate_from_internal_canary_metrics": separate,
    }


def _rollback_readiness_failures(
    packet: Mapping[str, Any],
) -> tuple[list[str], list[str], dict[str, Any]]:
    failures: list[str] = []
    schema = _schema_version(packet)
    schema_id = str(packet.get("schema_version_id") or "").strip()
    if schema not in {
        LEGAL_IR_DRIFT_MONITOR_SCHEMA_VERSION,
        LEGAL_IR_LEARNED_GUIDANCE_ROLLBACK_SCHEMA_VERSION,
        "",
    } and schema_id != LEGAL_IR_DRIFT_MONITOR_SCHEMA_VERSION:
        failures.append(f"rollback_readiness:schema_mismatch:{schema}")
    status = str(packet.get("status") or "").strip().lower()
    accepted = packet.get("accepted")
    hard_guardrail = str(packet.get("hard_guardrail") or "").strip()
    rollback_decision = packet.get("rollback_decision")
    rollback_required: Any = packet.get("rollback_required")
    if isinstance(rollback_decision, Mapping):
        rollback_required = rollback_decision.get("rollback_required", rollback_required)
    if hard_guardrail and hard_guardrail != PRODUCTION_DRIFT_AND_ROLLBACK_HARD_GUARDRAIL:
        failures.append(f"rollback_readiness:hard_guardrail_mismatch:{hard_guardrail}")
    if accepted is False or status in {"rollback_required", "blocked", "failed"}:
        failures.append(f"rollback_readiness:drift_monitor_blocked:{status or accepted}")
    if rollback_required is True:
        failures.append("rollback_readiness:rollback_already_required")
    rollback_metadata = packet.get("rollback_metadata")
    if not isinstance(rollback_metadata, Mapping):
        rollback_metadata = packet.get("rollback_evidence")
    if not isinstance(rollback_metadata, Mapping):
        rollback_metadata = {}
    rollback_id = str(rollback_metadata.get("rollback_id") or packet.get("rollback_id") or "").strip()
    disable_action = str(
        rollback_metadata.get("disable_action")
        or packet.get("disable_action")
        or ""
    ).strip()
    restorable = (
        rollback_metadata.get("restorable") is True
        or packet.get("restorable") is True
        or bool(disable_action)
    )
    if not rollback_id:
        failures.append("rollback_readiness:rollback_id_missing")
    if not (disable_action or restorable):
        failures.append("rollback_readiness:disable_or_restore_action_missing")
    return failures, [], {
        "schema_version": schema,
        "status": status,
        "accepted": accepted,
        "rollback_required": rollback_required,
        "rollback_id": rollback_id,
        "disable_action": disable_action,
        "restorable": restorable,
    }


def _external_validity_binding_failures(
    payload: Mapping[str, Any],
    evidence_packets: Mapping[str, Mapping[str, Any]],
    cfg: ExternalValidityPromotionConfig,
) -> tuple[dict[str, Any], list[str]]:
    failures: list[str] = []
    metrics: dict[str, Any] = {}
    envelope_bindings = payload.get("evidence_bindings")
    if not isinstance(envelope_bindings, Mapping):
        envelope_bindings = payload.get("bindings")
    if not isinstance(envelope_bindings, Mapping):
        envelope_bindings = {}
    for field in cfg.required_binding_fields:
        sources: dict[str, str] = {}
        expected = _binding_value(field, envelope_bindings)
        root_value = _binding_value(field, payload)
        if expected:
            sources["evidence_bindings"] = expected
        if root_value:
            sources["root"] = root_value
        for domain, packet in evidence_packets.items():
            value = _binding_value(field, packet)
            if value:
                sources[domain] = value
        normalized = {source: _normalize_binding_value(field, value) for source, value in sources.items()}
        unique_values = sorted(set(normalized.values()))
        canonical = unique_values[0] if len(unique_values) == 1 else ""
        metrics[field] = {
            "canonical": canonical,
            "sources": dict(sorted(normalized.items())),
        }
        if not expected and not root_value:
            failures.append(f"external_validity_binding_missing:{field}")
        if len(unique_values) > 1:
            failures.append(
                f"external_validity_binding_mismatch:{field}:"
                + ",".join(f"{source}={value}" for source, value in sorted(normalized.items()))
            )
    return metrics, failures


def _schema_failures(
    domain: str,
    packet: Mapping[str, Any],
    allowed: Sequence[str],
) -> list[str]:
    schema = _schema_version(packet)
    if schema not in set(allowed):
        return [f"{domain}:schema_mismatch:{schema or 'missing'}"]
    return []


def _status_failures(domain: str, packet: Mapping[str, Any]) -> list[str]:
    failures: list[str] = []
    status = str(packet.get("status") or "").strip().lower()
    accepted = packet.get("accepted")
    passed = packet.get("passed")
    promotion_allowed = packet.get("promotion_allowed")
    reusable = packet.get("reusable")
    if status in {"blocked", "failed", "rejected", "rollback_required"}:
        failures.append(f"{domain}:status_blocked:{status}")
    if accepted is False:
        failures.append(f"{domain}:accepted_false")
    if passed is False:
        failures.append(f"{domain}:passed_false")
    if promotion_allowed is False:
        failures.append(f"{domain}:promotion_allowed_false")
    if reusable is False:
        failures.append(f"{domain}:reusable_false")
    for key in ("failures", "block_reasons", "failed_packet_ids", "missing_guardrail_evidence"):
        items = _string_sequence(packet.get(key))
        if items:
            failures.append(f"{domain}:{key}:" + ",".join(items))
    return failures


def _semantic_scores(packet: Mapping[str, Any]) -> dict[str, float]:
    result: dict[str, float] = {}
    containers: list[Mapping[str, Any]] = [packet]
    for key in ("scores", "metric_scores", "minimum_scores"):
        value = packet.get(key)
        if isinstance(value, Mapping):
            containers.append(value)
    families = packet.get("family_results")
    if isinstance(families, Mapping):
        for value in families.values():
            if isinstance(value, Mapping):
                scores = value.get("scores")
                if isinstance(scores, Mapping):
                    containers.append(scores)
    for container in containers:
        for metric in SEMANTIC_EQUIVALENCE_REQUIRED_METRICS:
            number = _finite_float(container.get(metric))
            if number is not None:
                result[metric] = min(number, result.get(metric, number))
    return result


def _external_domain_schema_versions(domain: str) -> tuple[str, ...]:
    if domain == "hard_negatives":
        return (LEGAL_IR_HARD_NEGATIVE_EFFECT_SCHEMA_VERSION, LEGAL_IR_HARD_NEGATIVE_SCHEMA_VERSION)
    if domain == "rollback_readiness":
        return (LEGAL_IR_DRIFT_MONITOR_SCHEMA_VERSION, LEGAL_IR_LEARNED_GUIDANCE_ROLLBACK_SCHEMA_VERSION)
    mapping = {
        "leak_free_splits": LEGAL_IR_EVAL_SPLITS_SCHEMA_VERSION,
        "semantic_metrics": LEGAL_IR_SEMANTIC_METRICS_SCHEMA_VERSION,
        "typed_decoding": LEGAL_IR_GRAMMAR_DECODER_SCHEMA_VERSION,
        "uncertainty": LEGAL_IR_UNCERTAINTY_SCHEMA_VERSION,
        "fuzzing": LEGAL_IR_FUZZING_SCHEMA_VERSION,
        "multi_seed_statistics": MULTI_SEED_PROMOTION_SCHEMA_VERSION,
        "schema_compatibility": LEGAL_IR_SCHEMA_EVOLUTION_SCHEMA_VERSION,
        "poisoning_defenses": LEGAL_IR_PREMISE_SECURITY_SCHEMA_VERSION,
        "external_benchmark_scores": LEGAL_IR_EXTERNAL_BENCHMARK_REPORT_SCHEMA_VERSION,
    }
    value = mapping.get(domain)
    return (value,) if value else ()


def _external_report_detail(domain: str, entry: Mapping[str, Any]) -> str:
    if not entry.get("present"):
        return "`missing`"
    if domain == "external_benchmark_scores":
        return f"`score={entry.get('external_validity_score')}, packets={entry.get('packet_count')}`"
    if domain == "multi_seed_statistics":
        metrics = entry.get("metrics")
        if isinstance(metrics, Mapping):
            seed_set = metrics.get("seed_set")
            return f"`seeds={len(seed_set) if isinstance(seed_set, Sequence) else 0}`"
    for key in (
        "schema_version",
        "success_rate",
        "mutation_count",
        "false_positive_reduction",
        "rollback_id",
        "hard_rule",
    ):
        value = entry.get(key)
        if value not in (None, "", []):
            return f"`{key}={value}`"
    return "`present`"


def _schema_version(packet: Mapping[str, Any]) -> str:
    return str(packet.get("schema_version") or "").strip()


def _first_string(payload: Mapping[str, Any], keys: Sequence[str]) -> str:
    for key in keys:
        value = payload.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return ""


def _find_string_value(payload: Mapping[str, Any], wanted: str) -> str:
    for _path, value in _walk(payload):
        if str(value).strip() == wanted:
            return wanted
    return ""


def _binding_value(field: str, payload: Mapping[str, Any]) -> str:
    aliases = {
        "promotion_id": ("promotion_id", "active_promotion_id"),
        "compiler_commit": ("compiler_commit", "selected_compiler_commit", "git_revision"),
        "source_export_id": ("source_export_id", "learned_export_id", "export_id"),
        "fixed_canary_id": ("fixed_canary_id", "canary_id", "validation_canary_id"),
        "split_manifest_digest": (
            "split_manifest_digest",
            "split_manifest_sha256",
            "split_guard_digest",
            "manifest_digest",
        ),
    }.get(field, (field,))
    value = _first_string(payload, aliases)
    if value:
        return value
    if field == "source_export_id":
        learned_export = payload.get("learned_export")
        if isinstance(learned_export, Mapping):
            return _first_string(learned_export, ("export_id", "source_export_id"))
    if field == "fixed_canary_id":
        fixed_binding = payload.get("fixed_canary_binding")
        if isinstance(fixed_binding, Mapping):
            return _first_string(fixed_binding, ("canary_id", "fixed_canary_id"))
    return ""


def _normalize_binding_value(field: str, value: str) -> str:
    text = str(value or "").strip()
    if field == "split_manifest_digest":
        return _normalized_digest_ref(text) if _valid_digest_ref(text) else text
    return text


def _multi_seed_rollout_failures(
    summary: Mapping[str, Any],
    cfg: RolloutGateConfig,
    metrics: dict[str, Any],
    warnings: list[str],
) -> list[str]:
    evidence_path, evidence = _multi_seed_promotion_evidence(summary)
    metrics["multi_seed_statistical_promotion_present"] = evidence is not None
    if evidence_path:
        metrics["multi_seed_statistical_promotion_path"] = evidence_path
    if evidence is None and not cfg.require_multi_seed_statistical_promotion:
        return []
    result = multi_seed_promotion_gate(summary)
    metrics["multi_seed_statistical_promotion"] = result.metrics
    warnings.extend(result.warnings)
    if result.accepted:
        return []
    if not cfg.require_multi_seed_statistical_promotion and evidence is None:
        return []
    return result.failures


def _fatal_status_failures(summary: Mapping[str, Any], cfg: RolloutGateConfig) -> list[str]:
    failures: list[str] = []
    status = str(summary.get("status") or "").strip().lower()
    if status == "failed":
        failures.append("summary_status_failed")
    stop_reason = str(summary.get("latest_stop_reason") or "").strip()
    if stop_reason and stop_reason in cfg.fatal_stop_reasons:
        failures.append(f"fatal_stop_reason:{stop_reason}")
    autoencoder_exit_code = summary.get("autoencoder_exit_code")
    if _is_nonzero_exit(autoencoder_exit_code):
        failures.append(f"autoencoder_exit_code:{autoencoder_exit_code}")
    codex_exit_codes = summary.get("codex_exit_codes")
    if isinstance(codex_exit_codes, Mapping):
        for run_id, code in codex_exit_codes.items():
            if _is_nonzero_exit(code):
                failures.append(f"codex_exit_code:{run_id}:{code}")
    elif _is_nonzero_exit(summary.get("codex_exit_code")):
        failures.append(f"codex_exit_code:{summary.get('codex_exit_code')}")
    return failures


def _metric_regression_failures(
    summary: Mapping[str, Any],
    cfg: RolloutGateConfig,
    metrics: dict[str, Any],
) -> list[str]:
    failures: list[str] = []
    validation_ce_delta = _finite_float(summary.get("latest_validation_ce_delta"))
    if validation_ce_delta is not None:
        metrics["latest_validation_ce_delta"] = validation_ce_delta
        if validation_ce_delta > cfg.max_validation_ce_regression:
            failures.append(
                "validation_ce_regression:"
                f"{validation_ce_delta:g}>{cfg.max_validation_ce_regression:g}"
            )

    validation_cosine_delta = _finite_float(summary.get("latest_validation_cosine_delta"))
    if validation_cosine_delta is not None:
        metrics["latest_validation_cosine_delta"] = validation_cosine_delta
        if validation_cosine_delta < -cfg.max_validation_cosine_regression:
            failures.append(
                "validation_cosine_regression:"
                f"{validation_cosine_delta:g}<-{cfg.max_validation_cosine_regression:g}"
            )

    compiler_delta = summary.get("compiler_ir_validation_last_delta")
    if isinstance(compiler_delta, Mapping):
        ir_ce_delta = _finite_float(compiler_delta.get("compiler_ir_cross_entropy_loss"))
        if ir_ce_delta is not None:
            metrics["compiler_ir_cross_entropy_delta"] = ir_ce_delta
            if ir_ce_delta > cfg.max_compiler_ir_ce_regression:
                failures.append(
                    "compiler_ir_ce_regression:"
                    f"{ir_ce_delta:g}>{cfg.max_compiler_ir_ce_regression:g}"
                )
        ir_cos_delta = _finite_float(compiler_delta.get("compiler_ir_cosine_similarity"))
        if ir_cos_delta is not None:
            metrics["compiler_ir_cosine_delta"] = ir_cos_delta
            if ir_cos_delta < -cfg.max_compiler_ir_cosine_regression:
                failures.append(
                    "compiler_ir_cosine_regression:"
                    f"{ir_cos_delta:g}<-{cfg.max_compiler_ir_cosine_regression:g}"
                )
    return failures


def _source_copy_failures(
    summary: Mapping[str, Any],
    cfg: RolloutGateConfig,
    metrics: dict[str, Any],
) -> list[str]:
    failures: list[str] = []
    source_copy_values = {
        path: value
        for path, value in _collect_named_numeric_values(
            summary, cfg.source_copy_keys
        ).items()
        # Paired promotion baselines are comparison evidence, not the state that
        # would be activated by this rollout.
        if ".baseline." not in f".{path}."
    }
    if source_copy_values:
        metrics["source_copy_penalties"] = dict(sorted(source_copy_values.items()))
    for key, value in sorted(source_copy_values.items()):
        if value > cfg.max_source_copy_penalty:
            failures.append(f"source_copy_penalty:{key}:{value:g}>{cfg.max_source_copy_penalty:g}")
    return failures


def _representation_promotion_failures(
    summary: Mapping[str, Any],
    cfg: RolloutGateConfig,
    metrics: dict[str, Any],
    warnings: list[str],
) -> list[str]:
    """Fail closed around a learned-representation promotion decision.

    Promotion serializers include convenient pass/fail flags, but rollout safety
    must not depend on those flags being internally consistent.  This check
    therefore recomputes every paired fixed-canary delta from the serialized
    baseline and candidate values.
    """

    failures: list[str] = []
    report_path, report = _representation_promotion_report(summary)
    metrics["representation_promotion_report_present"] = report is not None
    if report is None:
        if cfg.require_representation_promotion:
            failures.append("missing_representation_promotion_report")
        return failures

    metrics["representation_promotion_report_path"] = report_path
    split_guard = split_guard_from_payload(report)
    if split_guard is not None:
        metrics["representation_split_guard"] = split_guard.to_dict()
    if split_guard_blocks_operation(report, REPRESENTATION_PROMOTION_OPERATION):
        failures.append("representation_split_guard_blocked")
    promoted = _promotion_was_allowed(report)
    metrics["representation_promotion_allowed"] = promoted
    block_reasons = _string_sequence(report.get("block_reasons"))
    if block_reasons:
        metrics["representation_promotion_block_reasons"] = block_reasons
    require_success = cfg.require_successful_representation_promotion
    schema = str(report.get("schema_version") or "").strip()
    metrics["representation_promotion_schema_version"] = schema
    if (
        (promoted or require_success or cfg.require_complete_representation_evidence)
        and schema != LEGAL_IR_LEARNED_GUIDANCE_PROMOTION_SCHEMA_VERSION
    ):
        failures.append(
            "representation_promotion_schema_mismatch:"
            f"{schema or 'missing'}"
        )
    report_outcome = str(
        report.get("report_outcome")
        or report.get("promotion_report_outcome")
        or report.get("outcome")
        or ""
    ).strip()
    if report_outcome:
        metrics["representation_promotion_report_outcome"] = report_outcome
    if report_outcome and report_outcome not in {
        "success",
        "rejection",
        "no_candidate",
    }:
        failures.append(f"representation_promotion_report_outcome_invalid:{report_outcome}")
    if promoted and report_outcome and report_outcome != "success":
        failures.append(
            f"representation_promotion_outcome_mismatch:{report_outcome}:promoted"
        )
    if not promoted and report_outcome == "success":
        failures.append("representation_promotion_outcome_mismatch:success:not_promoted")
    if require_success and not promoted:
        suffix = ",".join(block_reasons) if block_reasons else "unspecified"
        failures.append(f"representation_promotion_blocked:{suffix}")
    elif not promoted:
        warnings.append("representation_promotion_not_activated")

    raw_evidence = report.get("canary_evidence")
    evidence = raw_evidence if isinstance(raw_evidence, Mapping) else None
    evidence_required = promoted or require_success or (
        cfg.require_representation_promotion
        and cfg.require_complete_representation_evidence
    )
    if evidence is None:
        if evidence_required:
            failures.append("missing_representation_fixed_canary_evidence")
        else:
            warnings.append("representation_fixed_canary_evidence_absent")
        return failures

    canary_id = str(evidence.get("canary_id") or "").strip()
    fixed_sample_set = evidence.get("fixed_sample_set") is True
    metrics["representation_fixed_canary_id"] = canary_id
    metrics["representation_fixed_sample_set"] = fixed_sample_set
    if evidence_required and not canary_id:
        failures.append("representation_fixed_canary_identity_missing")
    if evidence_required and not fixed_sample_set:
        failures.append("representation_fixed_canary_sample_set_invalid")
    if cfg.require_complete_representation_evidence or promoted or require_success:
        failures.extend(
            _representation_report_binding_failures(
                summary,
                report,
                evidence,
                promoted=promoted,
                require_complete=cfg.require_complete_representation_evidence
                or promoted
                or require_success,
                metrics=metrics,
            )
        )

    raw_family_metrics = evidence.get("family_metrics")
    family_metrics = (
        raw_family_metrics if isinstance(raw_family_metrics, Mapping) else {}
    )
    represented_families = _represented_view_families(report, family_metrics)
    metrics["representation_view_families"] = list(represented_families)
    if evidence_required and not represented_families:
        failures.append("representation_fixed_canary_view_families_missing")

    enforce_complete = evidence_required and cfg.require_complete_representation_evidence
    family_deltas: dict[str, dict[str, float]] = {}
    for family in represented_families:
        raw_family = family_metrics.get(family)
        if not isinstance(raw_family, Mapping):
            if enforce_complete:
                failures.append(
                    f"representation_canary_family_evidence_missing:{family}"
                )
            continue
        baseline = _normalized_representation_metrics(raw_family.get("baseline"))
        candidate = _normalized_representation_metrics(raw_family.get("candidate"))
        deltas: dict[str, float] = {}
        for metric_name in cfg.required_representation_metrics:
            canonical_name = _REPRESENTATION_METRIC_ALIASES.get(
                metric_name, metric_name
            )
            before = baseline.get(canonical_name)
            after = candidate.get(canonical_name)
            if before is None or after is None:
                if enforce_complete:
                    failures.append(
                        "representation_canary_evidence_incomplete:"
                        f"{family}:{canonical_name}"
                    )
                continue
            improvement = (
                before - after
                if canonical_name in _LOWER_IS_BETTER_REPRESENTATION_METRICS
                else after - before
            )
            deltas[canonical_name] = round(improvement, 12)
            regression = max(0.0, -improvement)
            allowed = _representation_regression_limit(cfg, canonical_name)
            if regression > allowed + 1.0e-12:
                failures.append(
                    _representation_regression_failure(
                        family,
                        canonical_name,
                        before,
                        after,
                        regression,
                        allowed,
                    )
                )
        if deltas:
            family_deltas[family] = dict(sorted(deltas.items()))
    metrics["representation_fixed_canary_improvements"] = family_deltas

    declared_regressions = _declared_representation_regressions(evidence)
    if declared_regressions:
        metrics["representation_declared_regressions"] = declared_regressions
        calculated_markers = {
            failure.split(":", 1)[1].rsplit(":", 2)[0]
            for failure in failures
            if failure.startswith("representation_")
            and "_regression:" in failure
            and failure.count(":") >= 4
        }
        for marker in declared_regressions:
            if marker not in calculated_markers:
                failures.append(f"representation_declared_metric_regression:{marker}")

    missing_declared = _string_sequence(
        evidence.get("missing_guardrail_evidence")
    )
    if missing_declared and evidence_required:
        metrics["representation_declared_missing_evidence"] = missing_declared
        failures.extend(
            f"representation_declared_guardrail_evidence_missing:{item}"
            for item in missing_declared
        )

    productivity = _paired_todo_productivity(summary, report, evidence)
    if productivity is None:
        if enforce_complete:
            failures.append("representation_todo_productivity_evidence_missing")
    else:
        before_productivity, after_productivity, productivity_path = productivity
        improvement = after_productivity - before_productivity
        metrics["representation_todo_productivity"] = {
            "baseline": before_productivity,
            "candidate": after_productivity,
            "evidence_path": productivity_path,
            "improvement": round(improvement, 12),
        }
        regression = max(0.0, -improvement)
        allowed = max(0.0, cfg.max_todo_productivity_regression)
        if regression > allowed + 1.0e-12:
            failures.append(
                "representation_todo_productivity_regression:"
                f"{before_productivity:g}->{after_productivity:g}:"
                f"{regression:g}>{allowed:g}"
            )

    if promoted and evidence.get("guardrails_passed") is not True:
        failures.append("representation_promoted_without_passing_guardrails")
    for reason in block_reasons:
        if "regression" in reason and not any(reason in item for item in failures):
            failures.append(f"representation_promotion_regression:{reason}")
    return list(dict.fromkeys(failures))


def _representation_promotion_report(
    summary: Mapping[str, Any],
) -> tuple[str, Mapping[str, Any] | None]:
    for key in REPRESENTATION_PROMOTION_SUMMARY_KEYS:
        value = summary.get(key)
        if isinstance(value, Mapping):
            return key, value
    for path, value in _walk(summary):
        if not isinstance(value, Mapping):
            continue
        schema = str(value.get("schema_version") or "")
        if schema == "legal-ir-learned-guidance-promotion-v1":
            return path, value
    return "", None


def _representation_report_binding_failures(
    summary: Mapping[str, Any],
    report: Mapping[str, Any],
    evidence: Mapping[str, Any],
    *,
    promoted: bool,
    require_complete: bool,
    metrics: dict[str, Any],
) -> list[str]:
    failures: list[str] = []
    promotion_id = str(report.get("promotion_id") or "").strip()
    source_export_id = str(
        report.get("source_export_id") or report.get("learned_export_id") or ""
    ).strip()
    compiler_commit = str(report.get("compiler_commit") or "").strip()
    canary_id = str(evidence.get("canary_id") or "").strip()
    evidence_id = str(evidence.get("evidence_id") or "").strip()
    metrics["representation_promotion_id"] = promotion_id
    metrics["representation_source_export_id"] = source_export_id
    metrics["representation_compiler_commit"] = compiler_commit

    if require_complete and not promotion_id:
        failures.append("representation_promotion_id_missing")

    learned_export = report.get("learned_export")
    if not isinstance(learned_export, Mapping):
        failures.append("representation_learned_export_binding_missing")
        learned_export = {}
    else:
        export_id = str(learned_export.get("export_id") or "").strip()
        export_schema = str(learned_export.get("schema_version") or "").strip()
        export_sha = str(
            learned_export.get("sha256")
            or learned_export.get("export_sha256")
            or report.get("learned_export_sha256")
            or ""
        ).strip().lower()
        metrics["representation_learned_export_sha256"] = export_sha
        if require_complete and not export_id:
            failures.append("representation_learned_export_id_missing")
        if source_export_id and export_id and source_export_id != export_id:
            failures.append(
                "representation_learned_export_id_mismatch:"
                f"{source_export_id}!={export_id}"
            )
        if require_complete and export_schema != LEGAL_IR_STABLE_FEATURE_EXPORT_SCHEMA_VERSION:
            failures.append(
                "representation_learned_export_schema_mismatch:"
                f"{export_schema or 'missing'}"
            )
        if require_complete and not _valid_sha256(export_sha):
            failures.append("representation_learned_export_sha256_missing")
        if learned_export.get("sample_memory_included") is True:
            failures.append("representation_learned_export_contains_sample_memory")

    expected_export_id = _first_summary_string(
        summary,
        (
            "source_export_id",
            "learned_export_id",
            "latest_legal_ir_stable_feature_export.export_id",
            "legal_ir_stable_feature_export.export_id",
            "stable_legal_ir_feature_export.export_id",
            "learned_export.export_id",
        ),
    )
    if expected_export_id and source_export_id and expected_export_id != source_export_id:
        failures.append(
            "representation_promotion_report_stale:source_export_id:"
            f"{source_export_id}!={expected_export_id}"
        )

    if require_complete and not compiler_commit:
        failures.append("representation_compiler_commit_missing")
    expected_compiler_commit = _first_summary_string(
        summary,
        (
            "compiler_commit",
            "expected_compiler_commit",
            "selected_compiler_commit",
            "snapshot_selection.selected_compiler_commit",
            "snapshot_selection.compiler_commit",
            "context.compiler_commit",
            "latest_compiler_snapshot.compiler_commit",
        ),
    )
    if (
        expected_compiler_commit
        and compiler_commit
        and expected_compiler_commit != compiler_commit
    ):
        failures.append(
            "representation_promotion_report_stale:compiler_commit:"
            f"{compiler_commit}!={expected_compiler_commit}"
        )

    fixed_binding = report.get("fixed_canary_binding")
    if not isinstance(fixed_binding, Mapping):
        failures.append("representation_fixed_canary_binding_missing")
    else:
        bound_canary = str(fixed_binding.get("canary_id") or "").strip()
        bound_evidence = str(fixed_binding.get("evidence_id") or "").strip()
        if canary_id and bound_canary and bound_canary != canary_id:
            failures.append(
                "representation_fixed_canary_binding_mismatch:"
                f"{bound_canary}!={canary_id}"
            )
        if evidence_id and bound_evidence and bound_evidence != evidence_id:
            failures.append(
                "representation_fixed_canary_evidence_mismatch:"
                f"{bound_evidence}!={evidence_id}"
            )
        if require_complete and not bound_canary:
            failures.append("representation_fixed_canary_binding_id_missing")
    expected_canary_id = _first_summary_string(
        summary,
        (
            "fixed_canary_id",
            "validation_canary_id",
            "frozen_canary.canary_id",
            "latest_legal_ir_view_family_validation.canary_id",
            "latest_legal_ir_stable_feature_export.fixed_canary_id",
        ),
    )
    if expected_canary_id and canary_id and expected_canary_id != canary_id:
        failures.append(
            "representation_promotion_report_stale:fixed_canary:"
            f"{canary_id}!={expected_canary_id}"
        )

    proof_receipts = report.get("proof_receipts")
    if not isinstance(proof_receipts, Sequence) or isinstance(
        proof_receipts, (str, bytes, bytearray)
    ):
        failures.append("representation_proof_receipts_missing")
        proof_receipts = ()
    else:
        metrics["representation_proof_receipt_count"] = len(proof_receipts)
        if promoted and not proof_receipts:
            failures.append("representation_proof_receipts_missing")
        for index, receipt in enumerate(proof_receipts):
            if not isinstance(receipt, Mapping):
                failures.append(f"representation_proof_receipt_invalid:index_{index}")
                continue
            receipt_id = str(receipt.get("receipt_id") or receipt.get("id") or "").strip()
            if require_complete and not receipt_id:
                failures.append(
                    f"representation_proof_receipt_id_missing:index_{index}"
                )
            if promoted and receipt.get("trusted") is False:
                failures.append(f"representation_proof_receipt_untrusted:{receipt_id or index}")

    causal = report.get("causal_evidence")
    if not isinstance(causal, Mapping) or not causal:
        failures.append("representation_causal_evidence_missing")
    else:
        if require_complete and causal.get("fixed_canary_evidence_id") not in {
            None,
            "",
            evidence_id,
        }:
            failures.append("representation_causal_evidence_canary_mismatch")
        if require_complete and causal.get("metric_lineage_complete") is not True:
            failures.append("representation_causal_metric_lineage_incomplete")
        if promoted and causal.get("learned_path_responsive") is not True:
            failures.append("representation_causal_learned_path_unproven")

    source_copy = report.get("source_copy_checks")
    if not isinstance(source_copy, Mapping) or not source_copy:
        failures.append("representation_source_copy_checks_missing")
    else:
        if promoted and source_copy.get("guardrails_passed") is not True:
            failures.append("representation_source_copy_checks_failed")
        if source_copy.get("sample_memory_included") is True:
            failures.append("representation_source_copy_sample_memory_present")
        unsafe_count = _first_finite(
            source_copy,
            ("unsafe_feature_count", "forbidden_feature_marker_count"),
        )
        if unsafe_count is not None and unsafe_count > 0.0:
            failures.append(
                f"representation_source_copy_unsafe_features:{unsafe_count:g}"
            )
        regressions = _string_sequence(source_copy.get("source_copy_regressions"))
        if promoted and regressions:
            failures.append(
                "representation_source_copy_declared_regression:"
                + ",".join(regressions)
            )

    activation = report.get("activation_state")
    if not isinstance(activation, Mapping) or not activation:
        failures.append("representation_activation_state_missing")
    else:
        allowed = activation.get("activation_allowed")
        if allowed is not None and bool(allowed) != promoted:
            failures.append("representation_activation_state_mismatch")
        active_id = str(activation.get("active_promotion_id") or "").strip()
        if promoted and promotion_id and active_id and active_id != promotion_id:
            failures.append(
                "representation_activation_promotion_id_mismatch:"
                f"{active_id}!={promotion_id}"
            )
        if promoted and not active_id:
            failures.append("representation_activation_promotion_id_missing")

    rollback = report.get("rollback_metadata")
    if not isinstance(rollback, Mapping) or not rollback:
        failures.append("representation_rollback_metadata_missing")
    else:
        if require_complete and not str(rollback.get("rollback_id") or "").strip():
            failures.append("representation_rollback_id_missing")
        activation_key = str(rollback.get("activation_key") or "").strip()
        if promotion_id and activation_key and activation_key != promotion_id:
            failures.append(
                "representation_rollback_activation_key_mismatch:"
                f"{activation_key}!={promotion_id}"
            )
        rollback_export = str(rollback.get("source_export_id") or "").strip()
        if source_export_id and rollback_export and rollback_export != source_export_id:
            failures.append(
                "representation_rollback_source_export_mismatch:"
                f"{rollback_export}!={source_export_id}"
            )
        rollback_canary = str(rollback.get("canary_evidence_id") or "").strip()
        if evidence_id and rollback_canary and rollback_canary != evidence_id:
            failures.append(
                "representation_rollback_canary_evidence_mismatch:"
                f"{rollback_canary}!={evidence_id}"
            )

    report_path = str(report.get("report_artifact_path") or "").strip()
    expected_report_path = _first_summary_string(
        summary,
        (
            "representation_promotion_report_path",
            "latest_legal_ir_learned_guidance_promotion_path",
            "promotion_report_path",
            "promotion_artifact_path",
        ),
    )
    if expected_report_path and report_path and expected_report_path != report_path:
        failures.append(
            "representation_promotion_report_path_mismatch:"
            f"{report_path}!={expected_report_path}"
        )
    if expected_report_path and require_complete and not report_path:
        failures.append("representation_promotion_report_path_missing")

    snapshot_id = str(report.get("eligible_snapshot_id") or "").strip()
    expected_snapshot_id = _first_summary_string(
        summary,
        (
            "eligible_snapshot_id",
            "snapshot_id",
            "latest_published_snapshot.snapshot_id",
            "latest_promoted_snapshot_evaluation.snapshot_id",
        ),
    )
    if expected_snapshot_id and snapshot_id and expected_snapshot_id != snapshot_id:
        failures.append(
            "representation_promotion_report_stale:snapshot_id:"
            f"{snapshot_id}!={expected_snapshot_id}"
        )
    if expected_snapshot_id and require_complete and not snapshot_id:
        failures.append("representation_eligible_snapshot_id_missing")
    return failures


def _promotion_was_allowed(report: Mapping[str, Any]) -> bool:
    return bool(
        report.get("promoted") is True
        or report.get("promotion_allowed") is True
        or str(report.get("status") or "").strip().lower() == "promoted"
    )


def _represented_view_families(
    report: Mapping[str, Any], family_metrics: Mapping[str, Any]
) -> tuple[str, ...]:
    represented = {
        family for family in LEGAL_IR_VIEW_FAMILIES if family in family_metrics
    }
    records = report.get("guidance_records", report.get("records"))
    if isinstance(records, Sequence) and not isinstance(
        records, (str, bytes, bytearray)
    ):
        for record in records:
            if not isinstance(record, Mapping):
                continue
            family = _canonical_view_family(record.get("view_family"))
            if family:
                represented.add(family)
    required = report.get("required_view_families")
    if isinstance(required, Sequence) and not isinstance(
        required, (str, bytes, bytearray)
    ):
        for value in required:
            family = _canonical_view_family(value)
            if family:
                represented.add(family)
    return tuple(family for family in LEGAL_IR_VIEW_FAMILIES if family in represented)


def _canonical_view_family(value: Any) -> str:
    text = str(value or "").strip().lower().replace("-", "_")
    aliases = {
        "frame": "frame_logic",
        "knowledge_graph": "kg",
        "knowledge_graphs": "kg",
        "external_prover": "external_provers",
    }
    text = aliases.get(text, text)
    return text if text in LEGAL_IR_VIEW_FAMILIES else ""


def _normalized_representation_metrics(value: Any) -> dict[str, float]:
    if not isinstance(value, Mapping):
        return {}
    normalized: dict[str, float] = {}
    for raw_name, raw_value in value.items():
        name = _REPRESENTATION_METRIC_ALIASES.get(str(raw_name), str(raw_name))
        if name not in LEGAL_IR_REPRESENTATION_METRICS:
            continue
        number = _finite_float(raw_value)
        if number is not None:
            normalized[name] = number
    return normalized


def _representation_regression_limit(
    cfg: RolloutGateConfig, metric_name: str
) -> float:
    if metric_name == "symbolic_validity_success_rate":
        return max(0.0, cfg.max_symbolic_validity_regression)
    if metric_name == "hammer_proof_success_rate":
        return max(0.0, cfg.max_hammer_proof_rate_regression)
    if metric_name == "reconstruction_success_rate":
        return max(0.0, cfg.max_reconstruction_rate_regression)
    if metric_name == "source_copy_penalty":
        return max(0.0, cfg.max_source_copy_penalty_regression)
    return max(0.0, cfg.max_per_view_ir_metric_regression)


def _representation_regression_failure(
    family: str,
    metric_name: str,
    before: float,
    after: float,
    regression: float,
    allowed: float,
) -> str:
    prefixes = {
        "symbolic_validity_success_rate": "representation_symbolic_validity_regression",
        "hammer_proof_success_rate": "representation_hammer_proof_rate_regression",
        "reconstruction_success_rate": "representation_reconstruction_rate_regression",
        "source_copy_penalty": "representation_source_copy_penalty_regression",
    }
    prefix = prefixes.get(
        metric_name, "representation_per_view_ir_metric_regression"
    )
    return (
        f"{prefix}:{family}:{metric_name}:{before:g}->{after:g}:"
        f"{regression:g}>{allowed:g}"
    )


def _declared_representation_regressions(
    evidence: Mapping[str, Any],
) -> list[str]:
    result: list[str] = []
    declared_metrics = {
        "metric_regressions": "",
        "source_copy_regressions": "source_copy_penalty",
        "symbolic_validity_regressions": "symbolic_validity_success_rate",
    }
    for key, default_metric in declared_metrics.items():
        for item in _string_sequence(evidence.get(key)):
            marker = (
                item
                if ":" in item or not default_metric
                else f"{item}:{default_metric}"
            )
            if marker not in result:
                result.append(marker)
    return result


def _paired_todo_productivity(
    summary: Mapping[str, Any],
    report: Mapping[str, Any],
    evidence: Mapping[str, Any],
) -> tuple[float, float, str] | None:
    containers = (
        ("promotion", report),
        ("canary_evidence", evidence),
        ("summary", summary),
    )
    for container_name, container in containers:
        for key in (
            "todo_generation_productivity",
            "todo_productivity",
            "codex_projection_productivity",
            "todo_generation_productivity_evidence",
        ):
            value = container.get(key)
            if not isinstance(value, Mapping):
                continue
            before = _productivity_value(
                value.get("baseline", value.get("before", value.get("control")))
            )
            after = _productivity_value(
                value.get("candidate", value.get("after", value.get("promoted")))
            )
            if before is not None and after is not None:
                return before, after, f"{container_name}.{key}"
            before = _first_finite(
                value,
                ("baseline_rate", "baseline_count", "before_rate", "control_rate"),
            )
            after = _first_finite(
                value,
                ("candidate_rate", "candidate_count", "after_rate", "promoted_rate"),
            )
            if before is not None and after is not None:
                return before, after, f"{container_name}.{key}"
        before = _first_finite(
            container,
            (
                "baseline_todo_generation_productivity",
                "before_todo_generation_productivity",
                "control_todo_generation_productivity",
            ),
        )
        after = _first_finite(
            container,
            (
                "candidate_todo_generation_productivity",
                "after_todo_generation_productivity",
                "promoted_todo_generation_productivity",
            ),
        )
        if before is not None and after is not None:
            return before, after, container_name
    return None


def _productivity_value(value: Any) -> float | None:
    number = _finite_float(value)
    if number is not None:
        return number
    if not isinstance(value, Mapping):
        return None
    preferred = _first_finite(
        value,
        (
            "productivity",
            "productivity_rate",
            "todos_per_cycle",
            "todos_per_hour",
            "rate",
            "total",
        ),
    )
    if preferred is not None:
        return preferred
    productive_tokens = (
        "accepted",
        "actionable",
        "completed",
        "deduped",
        "generated",
        "projected",
        "seeded",
        "todo",
    )
    values = [
        number
        for key, raw in value.items()
        if any(token in str(key).lower() for token in productive_tokens)
        and (number := _finite_float(raw)) is not None
    ]
    return sum(values) if values else None


def _first_summary_string(
    payload: Mapping[str, Any], paths: Sequence[str]
) -> str:
    for path in paths:
        current: Any = payload
        for part in path.split("."):
            if not isinstance(current, Mapping):
                current = None
                break
            current = current.get(part)
        if current is None:
            continue
        text = str(current).strip()
        if text:
            return text
    return ""


def _valid_sha256(value: str) -> bool:
    text = str(value or "").strip().lower()
    return len(text) == 64 and all(char in "0123456789abcdef" for char in text)


def _first_finite(
    payload: Mapping[str, Any], keys: Sequence[str]
) -> float | None:
    for key in keys:
        number = _finite_float(payload.get(key))
        if number is not None:
            return number
    return None


def _string_sequence(value: Any) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(
        value, (str, bytes, bytearray)
    ):
        return []
    return [str(item) for item in value if str(item)]


def _hammer_cycle_failures(
    summary: Mapping[str, Any],
    cfg: RolloutGateConfig,
    metrics: dict[str, Any],
    warnings: list[str],
) -> list[str]:
    failures: list[str] = []
    hammer_report = summary.get("latest_daemon_hammer_guidance")
    has_hammer_report = isinstance(hammer_report, Mapping) and bool(hammer_report)
    metrics["hammer_report_present"] = has_hammer_report
    if not cfg.require_hammer_cycle:
        return failures
    if not has_hammer_report:
        failures.append("missing_daemon_hammer_guidance_report")
        return failures

    status = str(hammer_report.get("status") or "").strip()
    metrics["hammer_status"] = status
    if status not in HAMMER_ALLOWED_STATUSES:
        failures.append(f"hammer_status_unexpected:{status or 'empty'}")

    runtime_failure_count = int(_finite_float(hammer_report.get("runtime_failure_count"), 0.0) or 0)
    obligation_failure_count = int(
        _finite_float(hammer_report.get("obligation_failure_count"), 0.0) or 0
    )
    metrics["hammer_runtime_failure_count"] = runtime_failure_count
    metrics["hammer_obligation_failure_count"] = obligation_failure_count
    if runtime_failure_count > 0:
        warnings.append(f"hammer_runtime_failures_reported:{runtime_failure_count}")
    if obligation_failure_count > 0:
        warnings.append(f"hammer_obligation_failures_reported:{obligation_failure_count}")
    return failures


def _todo_activity_failures(
    summary: Mapping[str, Any],
    cfg: RolloutGateConfig,
    metrics: dict[str, Any],
) -> list[str]:
    failures: list[str] = []
    if not cfg.require_todo_activity:
        return failures

    cycles = int(_finite_float(summary.get("cycles"), 0.0) or 0)
    metrics["cycles"] = cycles
    if cycles < cfg.min_cycles_for_todo_gate:
        return failures

    active_todo_supervisor = summary.get("active_cycle_todo_supervisor")
    if isinstance(active_todo_supervisor, Mapping):
        skip_reason = str(active_todo_supervisor.get("skip_reason") or "")
        if skip_reason == "todo_supervisor_disabled":
            failures.append("todo_generation_disabled")

    queue_counts = {
        "pending": int(_finite_float(summary.get("program_synthesis_pending"), 0.0) or 0),
        "claimed": int(_finite_float(summary.get("program_synthesis_claimed"), 0.0) or 0),
        "completed": int(_finite_float(summary.get("program_synthesis_completed"), 0.0) or 0),
        "seeded": int(_finite_float(summary.get("program_synthesis_seeded"), 0.0) or 0),
        "deduped": int(_finite_float(summary.get("program_synthesis_deduped_total"), 0.0) or 0),
        "hammer_projected": int(
            _finite_float(summary.get("hammer_projected_todo_count_total"), 0.0) or 0
        ),
        "leanstral_projected": int(
            _finite_float(summary.get("leanstral_projection_seeded_total"), 0.0) or 0
        ),
    }
    latest_seeded = int(_finite_float(summary.get("latest_program_synthesis_seeded_count"), 0.0) or 0)
    latest_preinsert_deduped = int(
        _finite_float(summary.get("latest_program_synthesis_preinsert_deduped_count"), 0.0)
        or 0
    )
    queue_counts["latest_seeded"] = latest_seeded
    queue_counts["latest_preinsert_deduped"] = latest_preinsert_deduped
    metrics["program_synthesis_activity"] = dict(queue_counts)
    if sum(queue_counts.values()) <= 0:
        failures.append("todo_generation_stalled:no_program_synthesis_activity")
    return failures


def _backend_availability_failures(
    summary: Mapping[str, Any],
    cfg: RolloutGateConfig,
    metrics: dict[str, Any],
    warnings: list[str],
) -> list[str]:
    failures: list[str] = []
    fatal_paths = list(_find_backend_fatal_paths(summary))
    if fatal_paths:
        metrics["backend_fatal_paths"] = fatal_paths
        failures.extend(f"fatal_backend_availability:{path}" for path in fatal_paths)

    unavailable_ratio = _hammer_backend_unavailable_ratio(summary)
    if unavailable_ratio is not None:
        metrics["hammer_backend_unavailable_ratio"] = unavailable_ratio
        if unavailable_ratio >= 1.0:
            warnings.append("all_hammer_backends_unavailable")
        if (
            cfg.require_available_hammer_backend
            and unavailable_ratio > cfg.max_hammer_backend_unavailable_ratio
        ):
            failures.append(
                "hammer_backend_unavailable_ratio:"
                f"{unavailable_ratio:g}>{cfg.max_hammer_backend_unavailable_ratio:g}"
            )
    return failures


def _multi_seed_promotion_evidence(
    payload: Mapping[str, Any],
) -> tuple[str, Mapping[str, Any] | None]:
    for key in MULTI_SEED_PROMOTION_SUMMARY_KEYS:
        value = payload.get(key)
        if isinstance(value, Mapping):
            return key, value
    if _looks_like_multi_seed_evidence(payload):
        return "", payload
    for path, value in _walk(payload):
        if isinstance(value, Mapping) and _looks_like_multi_seed_evidence(value):
            return path, value
    return "", None


def _looks_like_multi_seed_evidence(value: Mapping[str, Any]) -> bool:
    schema = str(value.get("schema_version") or "").strip()
    if schema == MULTI_SEED_PROMOTION_SCHEMA_VERSION:
        return True
    metrics = value.get("metrics", value.get("metric_evidence"))
    if isinstance(metrics, Mapping):
        canonical = {
            _canonical_multi_seed_metric(key)
            for key in metrics
            if _canonical_multi_seed_metric(key)
        }
        return len(canonical.intersection(MULTI_SEED_PROMOTION_METRICS)) >= 2
    return False


def _multi_seed_metric_payloads(evidence: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    raw_metrics = evidence.get("metrics", evidence.get("metric_evidence"))
    if not isinstance(raw_metrics, Mapping):
        raw_metrics = evidence
    result: dict[str, Mapping[str, Any]] = {}
    for raw_name, raw_value in raw_metrics.items():
        metric_name = _canonical_multi_seed_metric(raw_name)
        if not metric_name or not isinstance(raw_value, Mapping):
            continue
        result[metric_name] = raw_value
    return result


def _canonical_multi_seed_metric(value: Any) -> str:
    text = str(value or "").strip().lower().replace("-", "_")
    text = _MULTI_SEED_METRIC_ALIASES.get(text, text)
    return text if text in MULTI_SEED_PROMOTION_METRICS else ""


def _multi_seed_metric_direction(
    payload: Mapping[str, Any],
    spec: MultiSeedMetricSpec,
) -> str:
    raw = str(payload.get("direction") or spec.direction or "higher").strip().lower()
    if raw in {"lower", "lower_is_better", "decrease", "reduction"}:
        return "lower"
    if raw in {"higher", "higher_is_better", "increase", "improvement"}:
        return "higher"
    return "higher" if spec.canonical_name in _MULTI_SEED_HIGHER_IS_BETTER else "lower"


def _multi_seed_minimum_effect(
    payload: Mapping[str, Any],
    spec: MultiSeedMetricSpec,
) -> float:
    value = _first_finite(
        payload,
        (
            "minimum_effect",
            "min_effect",
            "minimum_ci_lower_bound",
            "required_effect",
            "min_improvement",
        ),
    )
    if value is None:
        max_regression = _first_finite(payload, ("maximum_regression", "max_regression"))
        if max_regression is not None:
            return -abs(max_regression)
    return value if value is not None else spec.minimum_effect


def _multi_seed_paired_effects(
    payload: Mapping[str, Any],
    direction: str,
) -> tuple[list[tuple[str, float]], list[str]]:
    failures: list[str] = []
    paired: list[tuple[str, float]] = []
    records = _multi_seed_records(payload)
    if records:
        for index, record in enumerate(records):
            seed = _seed_id(record, index)
            effect = _record_effect(record, direction)
            if effect is None:
                failures.append(f"multi_seed_metric_sample_incomplete:index_{index}")
                continue
            paired.append((seed, effect))
        return paired, failures

    baseline_by_seed = _seed_value_mapping(
        payload.get("baseline_by_seed")
        or payload.get("control_by_seed")
        or payload.get("before_by_seed")
    )
    candidate_by_seed = _seed_value_mapping(
        payload.get("candidate_by_seed")
        or payload.get("promoted_by_seed")
        or payload.get("after_by_seed")
    )
    if baseline_by_seed or candidate_by_seed:
        common = sorted(set(baseline_by_seed).intersection(candidate_by_seed), key=_seed_sort_key)
        missing_baseline = sorted(set(candidate_by_seed).difference(baseline_by_seed), key=_seed_sort_key)
        missing_candidate = sorted(set(baseline_by_seed).difference(candidate_by_seed), key=_seed_sort_key)
        if missing_baseline:
            failures.append("multi_seed_metric_unpaired_baseline:" + ",".join(missing_baseline))
        if missing_candidate:
            failures.append("multi_seed_metric_unpaired_candidate:" + ",".join(missing_candidate))
        for seed in common:
            before = baseline_by_seed[seed]
            after = candidate_by_seed[seed]
            effect = after - before if direction == "higher" else before - after
            paired.append((seed, effect))
        return paired, failures

    effects_by_seed = _seed_value_mapping(payload.get("effects_by_seed"))
    if effects_by_seed:
        return sorted(effects_by_seed.items(), key=lambda item: _seed_sort_key(item[0])), failures
    return [], ["multi_seed_metric_samples_missing"]


def _multi_seed_records(payload: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    for key in (
        "seed_results",
        "seeds",
        "samples",
        "runs",
        "paired_results",
        "observations",
    ):
        value = payload.get(key)
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
            return [item for item in value if isinstance(item, Mapping)]
    return []


def _seed_id(record: Mapping[str, Any], index: int) -> str:
    for key in ("seed", "seed_id", "random_seed", "run_seed"):
        value = record.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return f"index_{index}"


def _record_effect(record: Mapping[str, Any], direction: str) -> float | None:
    direct = _finite_float(record.get("effect", record.get("improvement")))
    if direct is not None:
        return direct
    before = _first_finite(record, ("baseline", "control", "before"))
    after = _first_finite(record, ("candidate", "promoted", "after"))
    if before is None or after is None:
        return None
    return after - before if direction == "higher" else before - after


def _seed_value_mapping(value: Any) -> dict[str, float]:
    result: dict[str, float] = {}
    if isinstance(value, Mapping):
        for seed, raw in value.items():
            number = _finite_float(raw)
            if number is not None:
                result[str(seed)] = number
    return result


def _multi_seed_pairing_failure(
    payload: Mapping[str, Any],
    observed_seeds: set[str],
) -> str:
    declared = _string_seed_set(
        payload.get("seed_set")
        or payload.get("seeds_evaluated")
        or payload.get("configured_seeds")
    )
    if not declared:
        return ""
    if set(declared) != observed_seeds:
        return (
            "multi_seed_metric_seed_set_mismatch:"
            f"declared={','.join(declared)}:"
            f"observed={','.join(sorted(observed_seeds, key=_seed_sort_key))}"
        )
    return ""


def _string_seed_set(value: Any) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return []
    result = [str(item).strip() for item in value if str(item).strip()]
    return sorted(result, key=_seed_sort_key)


def _multi_seed_failure_attribution(
    payload: Mapping[str, Any],
    *,
    effects_by_seed: Mapping[str, float],
) -> tuple[dict[str, int], bool]:
    attribution: dict[str, int] = {}
    explicit = payload.get("failure_family_attribution")
    if isinstance(explicit, Mapping):
        for family, raw_count in explicit.items():
            count = _finite_float(raw_count)
            if count is not None and count > 0:
                attribution[str(family)] = attribution.get(str(family), 0) + int(count)
        return attribution, True

    present = False
    for index, record in enumerate(_multi_seed_records(payload)):
        seed = _seed_id(record, index)
        families = _failure_families_from_record(record)
        if families:
            present = True
        elif seed in effects_by_seed and effects_by_seed[seed] >= 0.0:
            families = ("none",)
            present = True
        elif seed in effects_by_seed:
            families = ("unattributed_regression",)
        for family in families:
            attribution[family] = attribution.get(family, 0) + 1
    return attribution, present


def _failure_families_from_record(record: Mapping[str, Any]) -> tuple[str, ...]:
    for key in (
        "failure_family",
        "failure_families",
        "failure_family_attribution",
        "family_failures",
        "failure_attribution",
        "block_reasons",
    ):
        value = record.get(key)
        if value is None:
            continue
        if isinstance(value, Mapping):
            return tuple(str(family) for family, count in value.items() if count)
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
            return tuple(str(item) for item in value if str(item))
        text = str(value).strip()
        if text:
            return (text,)
    return ()


def _effect_statistics(
    effects: Sequence[float],
    confidence_level: float,
) -> dict[str, float | None]:
    count = len(effects)
    if count == 0:
        return {
            "mean": None,
            "variance": None,
            "standard_error": None,
            "ci_lower": None,
            "ci_upper": None,
        }
    mean = sum(effects) / count
    variance = (
        sum((value - mean) ** 2 for value in effects) / (count - 1)
        if count > 1
        else None
    )
    if count > 1 and variance is not None:
        standard_error = math.sqrt(variance / count)
        critical = _t_critical(confidence_level, count - 1)
        half_width = critical * standard_error
    else:
        standard_error = None
        half_width = 0.0 if count > 1 else None
    return {
        "mean": round(mean, 12),
        "variance": round(variance, 12) if variance is not None else None,
        "standard_error": round(standard_error, 12) if standard_error is not None else None,
        "ci_lower": round(mean - half_width, 12) if half_width is not None else None,
        "ci_upper": round(mean + half_width, 12) if half_width is not None else None,
    }


def _t_critical(confidence_level: float, degrees_of_freedom: int) -> float:
    # Two-sided Student-t critical values for common promotion confidence levels.
    table = {
        0.80: (3.078, 1.886, 1.638, 1.533, 1.476, 1.440, 1.415, 1.397, 1.383, 1.372),
        0.90: (6.314, 2.920, 2.353, 2.132, 2.015, 1.943, 1.895, 1.860, 1.833, 1.812),
        0.95: (12.706, 4.303, 3.182, 2.776, 2.571, 2.447, 2.365, 2.306, 2.262, 2.228),
        0.98: (31.821, 6.965, 4.541, 3.747, 3.365, 3.143, 2.998, 2.896, 2.821, 2.764),
        0.99: (63.657, 9.925, 5.841, 4.604, 4.032, 3.707, 3.499, 3.355, 3.250, 3.169),
    }
    level = min(table, key=lambda candidate: abs(candidate - confidence_level))
    if degrees_of_freedom <= 0:
        return math.inf
    if degrees_of_freedom <= 10:
        return table[level][degrees_of_freedom - 1]
    normal = {0.80: 1.282, 0.90: 1.645, 0.95: 1.960, 0.98: 2.326, 0.99: 2.576}[level]
    # A first-order correction keeps df=11..30 conservative without carrying a
    # large lookup table in this operator script.
    return normal + (normal**3 + normal) / (4.0 * degrees_of_freedom)


def _seed_sort_key(value: Any) -> tuple[int, int | str]:
    text = str(value)
    try:
        return (0, int(text))
    except ValueError:
        return (1, text)


def _is_nonzero_exit(value: Any) -> bool:
    if value is None:
        return False
    number = _finite_float(value)
    return number is not None and int(number) != 0


def _finite_float(value: Any, default: float | None = None) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if math.isnan(number) or math.isinf(number):
        return default
    return number


def _collect_named_numeric_values(
    payload: Mapping[str, Any],
    keys: Sequence[str],
) -> dict[str, float]:
    wanted = set(keys)
    values: dict[str, float] = {}
    for path, value in _walk(payload):
        leaf = path.rsplit(".", 1)[-1]
        if leaf not in wanted:
            continue
        number = _finite_float(value)
        if number is not None:
            values[path] = number
    return values


def _hammer_backend_unavailable_ratio(summary: Mapping[str, Any]) -> float | None:
    for path, value in _walk(summary):
        if not path.endswith("hammer_backend_unavailable_ratio"):
            continue
        number = _finite_float(value)
        if number is not None:
            return number
    hammer_report = summary.get("latest_daemon_hammer_guidance")
    if isinstance(hammer_report, Mapping):
        metrics = hammer_report.get("hammer_metrics")
        if isinstance(metrics, Mapping):
            number = _finite_float(metrics.get("hammer_backend_unavailable_ratio"))
            if number is not None:
                return number
    return None


def _find_backend_fatal_paths(payload: Any, prefix: str = "") -> Iterable[str]:
    for path, value in _walk(payload, prefix=prefix):
        leaf = path.rsplit(".", 1)[-1].lower()
        if "backend" not in path.lower() and "solver" not in path.lower():
            continue
        if leaf in {"fatal", "fatal_error", "fatal_backend_error"} and bool(value):
            yield path
        if isinstance(value, str):
            lower = value.lower()
            if any(token in lower for token in DEFAULT_BACKEND_FATAL_STATUS_TOKENS):
                yield path


def _walk(payload: Any, prefix: str = "") -> Iterable[tuple[str, Any]]:
    if isinstance(payload, Mapping):
        for key, value in payload.items():
            key_text = str(key)
            child_prefix = f"{prefix}.{key_text}" if prefix else key_text
            yield child_prefix, value
            yield from _walk(value, prefix=child_prefix)
    elif isinstance(payload, Sequence) and not isinstance(payload, (str, bytes, bytearray)):
        for index, value in enumerate(payload):
            child_prefix = f"{prefix}[{index}]" if prefix else f"[{index}]"
            yield child_prefix, value
            yield from _walk(value, prefix=child_prefix)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    metrics_parser = subparsers.add_parser("guardrail-metrics")
    metrics_parser.set_defaults(func=_cmd_guardrail_metrics)

    gate_parser = subparsers.add_parser("gate")
    gate_parser.add_argument("--summary-path", required=True, type=Path)
    gate_parser.add_argument("--max-validation-ce-regression", type=float, default=0.02)
    gate_parser.add_argument("--max-validation-cosine-regression", type=float, default=0.02)
    gate_parser.add_argument("--max-compiler-ir-ce-regression", type=float, default=0.05)
    gate_parser.add_argument("--max-compiler-ir-cosine-regression", type=float, default=0.05)
    gate_parser.add_argument("--max-source-copy-penalty", type=float, default=0.35)
    gate_parser.add_argument("--require-hammer-cycle", action=argparse.BooleanOptionalAction, default=True)
    gate_parser.add_argument("--require-todo-activity", action=argparse.BooleanOptionalAction, default=True)
    gate_parser.add_argument(
        "--require-available-hammer-backend",
        action=argparse.BooleanOptionalAction,
        default=False,
    )
    gate_parser.add_argument("--max-hammer-backend-unavailable-ratio", type=float, default=1.0)
    gate_parser.add_argument("--min-cycles-for-todo-gate", type=int, default=1)
    gate_parser.add_argument(
        "--require-representation-promotion",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Require a learned-guidance promotion report in the run summary",
    )
    gate_parser.add_argument(
        "--require-successful-representation-promotion",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Reject a supervised run when representation promotion was blocked",
    )
    gate_parser.add_argument(
        "--require-complete-representation-evidence",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Require all eight metrics and paired TODO productivity evidence",
    )
    gate_parser.add_argument("--max-per-view-ir-metric-regression", type=float, default=0.0)
    gate_parser.add_argument("--max-symbolic-validity-regression", type=float, default=0.0)
    gate_parser.add_argument("--max-hammer-proof-rate-regression", type=float, default=0.0)
    gate_parser.add_argument("--max-reconstruction-rate-regression", type=float, default=0.0)
    gate_parser.add_argument("--max-source-copy-penalty-regression", type=float, default=0.0)
    gate_parser.add_argument("--max-todo-productivity-regression", type=float, default=0.0)
    gate_parser.add_argument(
        "--require-multi-seed-statistical-promotion",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Require paired multi-seed confidence-interval promotion evidence",
    )
    gate_parser.set_defaults(func=_cmd_gate)

    multi_seed_parser = subparsers.add_parser(
        "multi-seed-gate",
        help="Gate paired multi-seed statistical promotion evidence",
    )
    multi_seed_parser.add_argument("--evidence-path", "--summary-path", required=True, type=Path)
    multi_seed_parser.add_argument(
        "--evidence-output",
        type=Path,
        help="Atomically store the complete multi-seed promotion decision",
    )
    multi_seed_parser.add_argument("--min-seed-count", type=int, default=3)
    multi_seed_parser.add_argument("--confidence-level", type=float, default=0.95)
    multi_seed_parser.set_defaults(func=_cmd_multi_seed_gate)

    staged_parser = subparsers.add_parser(
        "staged-gate",
        help="Gate a persisted smoke/hparam/canary/production snapshot manifest",
    )
    staged_input = staged_parser.add_mutually_exclusive_group(required=True)
    staged_input.add_argument("--snapshot-path", type=Path)
    staged_input.add_argument("--manifest-path", type=Path)
    staged_parser.add_argument(
        "--evidence-output",
        type=Path,
        help="Atomically store the complete promotion decision",
    )
    staged_parser.add_argument(
        "--allow-prefix",
        action="store_true",
        help="Accept a valid ordered prefix so the launcher can authorize the next stage",
    )
    staged_parser.add_argument("--duration-tolerance-seconds", type=float, default=0.0)
    staged_parser.add_argument("--max-queue-lag-p95-seconds", type=float, default=120.0)
    staged_parser.add_argument("--max-queue-lag-regression", type=float, default=0.0)
    staged_parser.add_argument(
        "--max-accepted-patches-per-hour-regression", type=float, default=0.0
    )
    staged_parser.add_argument("--min-projection-p95-reduction", type=float, default=0.40)
    staged_parser.add_argument(
        "--min-task-to-accepted-patch-rate-improvement", type=float, default=0.20
    )
    staged_parser.add_argument(
        "--min-state-to-merged-patch-lag-reduction", type=float, default=0.25
    )
    staged_parser.add_argument(
        "--verify-rollback-artifacts",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Require rollback paths to exist and match their recorded SHA-256",
    )
    staged_parser.add_argument(
        "--require-multi-seed-statistical-promotion",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Require multi-seed statistical evidence in the final production snapshot",
    )
    staged_parser.set_defaults(func=_cmd_staged_gate)

    remediation_parser = subparsers.add_parser(
        "throughput-remediation-gate",
        help="Gate the complete matched benchmark and five-stage rollout envelope",
    )
    remediation_parser.add_argument(
        "--evidence-path", "--summary-path", required=True, type=Path
    )
    remediation_parser.add_argument(
        "--evidence-output", type=Path,
        help="Atomically store the machine-readable promotion decision",
    )
    remediation_parser.add_argument(
        "--report-output", type=Path,
        help="Atomically store the Markdown operator decision report",
    )
    remediation_parser.add_argument(
        "--verify-rollback-artifacts",
        action=argparse.BooleanOptionalAction,
        default=False,
    )
    remediation_parser.add_argument(
        "--max-checkpoint-bytes", type=int, default=512 * 1024 * 1024
    )
    remediation_parser.add_argument(
        "--max-summary-bytes", type=int, default=16 * 1024 * 1024
    )
    remediation_parser.set_defaults(func=_cmd_throughput_remediation_gate)

    external_parser = subparsers.add_parser(
        "external-validity-gate",
        help="Gate final promotion on bound external-validity evidence",
    )
    external_parser.add_argument("--evidence-path", "--summary-path", required=True, type=Path)
    external_parser.add_argument(
        "--evidence-output",
        type=Path,
        help="Atomically store the complete external-validity decision JSON",
    )
    external_parser.add_argument(
        "--report-output",
        type=Path,
        help="Atomically store a Markdown external-validity promotion report",
    )
    external_parser.add_argument("--min-semantic-score", type=float, default=1.0)
    external_parser.add_argument("--min-typed-decoding-success-rate", type=float, default=1.0)
    external_parser.add_argument(
        "--max-typed-decoding-source-copy-penalty",
        type=float,
        default=0.0,
    )
    external_parser.add_argument("--min-fuzzing-mutation-count", type=int, default=1)
    external_parser.add_argument("--min-trusted-negative-count", type=int, default=1)
    external_parser.add_argument(
        "--min-hard-negative-false-positive-reduction",
        type=float,
        default=0.05,
    )
    external_parser.add_argument("--min-external-validity-score", type=float, default=1.0)
    external_parser.add_argument("--min-external-packet-count", type=int, default=1)
    external_parser.set_defaults(func=_cmd_external_validity_gate)

    system_parser = subparsers.add_parser(
        "compiler-system-promotion-gate",
        help="Run the final LegalIR compiler-system promotion gate",
    )
    system_parser.add_argument(
        "--evidence-path", "--summary-path", required=True, type=Path
    )
    system_parser.add_argument(
        "--evidence-output",
        type=Path,
        help="Atomically store the complete compiler-system decision JSON",
    )
    system_parser.add_argument(
        "--report-output",
        type=Path,
        help="Atomically store a Markdown compiler-system promotion report",
    )
    system_parser.add_argument(
        "--verify-rollback-artifacts",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Require rollback paths to exist and match their recorded SHA-256",
    )
    system_parser.set_defaults(func=_cmd_compiler_system_promotion_gate)
    return parser


def _cmd_guardrail_metrics(args: argparse.Namespace) -> int:
    print(hard_guardrail_metrics_csv())
    return 0


def _cmd_gate(args: argparse.Namespace) -> int:
    summary = load_summary(args.summary_path)
    result = rollout_gate(
        summary,
        RolloutGateConfig(
            max_validation_ce_regression=args.max_validation_ce_regression,
            max_validation_cosine_regression=args.max_validation_cosine_regression,
            max_compiler_ir_ce_regression=args.max_compiler_ir_ce_regression,
            max_compiler_ir_cosine_regression=args.max_compiler_ir_cosine_regression,
            max_source_copy_penalty=args.max_source_copy_penalty,
            require_hammer_cycle=args.require_hammer_cycle,
            require_todo_activity=args.require_todo_activity,
            require_available_hammer_backend=args.require_available_hammer_backend,
            max_hammer_backend_unavailable_ratio=args.max_hammer_backend_unavailable_ratio,
            min_cycles_for_todo_gate=args.min_cycles_for_todo_gate,
            require_representation_promotion=args.require_representation_promotion,
            require_successful_representation_promotion=(
                args.require_successful_representation_promotion
            ),
            require_complete_representation_evidence=(
                args.require_complete_representation_evidence
            ),
            max_per_view_ir_metric_regression=(
                args.max_per_view_ir_metric_regression
            ),
            max_symbolic_validity_regression=args.max_symbolic_validity_regression,
            max_hammer_proof_rate_regression=args.max_hammer_proof_rate_regression,
            max_reconstruction_rate_regression=args.max_reconstruction_rate_regression,
            max_source_copy_penalty_regression=(
                args.max_source_copy_penalty_regression
            ),
            max_todo_productivity_regression=args.max_todo_productivity_regression,
            require_multi_seed_statistical_promotion=(
                args.require_multi_seed_statistical_promotion
            ),
        ),
    )
    print(json.dumps(result.to_dict(), indent=2, sort_keys=True))
    return 0 if result.accepted else 1


def _cmd_multi_seed_gate(args: argparse.Namespace) -> int:
    try:
        payload = load_summary(args.evidence_path)
        result = multi_seed_promotion_gate(
            payload,
            MultiSeedPromotionConfig(
                min_seed_count=args.min_seed_count,
                confidence_level=args.confidence_level,
            ),
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        result = RolloutGateResult(
            accepted=False,
            failures=[f"multi_seed_evidence_unreadable:{type(exc).__name__}:{exc}"],
            metrics={"schema_version": MULTI_SEED_PROMOTION_SCHEMA_VERSION},
        )
    decision = result.to_dict()
    decision["schema_version"] = MULTI_SEED_PROMOTION_SCHEMA_VERSION
    decision["evidence_path"] = str(args.evidence_path)
    if args.evidence_path.is_file():
        decision["evidence_sha256"] = snapshot_sha256(args.evidence_path)
    if args.evidence_output is not None:
        write_rollout_evidence(args.evidence_output, decision)
    print(json.dumps(decision, indent=2, sort_keys=True))
    return 0 if result.accepted else 1


def _cmd_staged_gate(args: argparse.Namespace) -> int:
    snapshot_path: Path = args.snapshot_path or args.manifest_path
    try:
        with snapshot_path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        if not isinstance(payload, (Mapping, list)):
            raise ValueError("snapshot manifest must be an object or array")
        result = staged_rollout_gate(
            payload,
            StagedRolloutConfig(
                require_all_stages=not args.allow_prefix,
                verify_rollback_artifacts=args.verify_rollback_artifacts,
                duration_tolerance_seconds=args.duration_tolerance_seconds,
                max_queue_lag_p95_seconds=args.max_queue_lag_p95_seconds,
                max_queue_lag_regression=args.max_queue_lag_regression,
                max_accepted_patches_per_hour_regression=(
                    args.max_accepted_patches_per_hour_regression
                ),
                min_projection_p95_reduction=args.min_projection_p95_reduction,
                min_task_to_accepted_patch_rate_improvement=(
                    args.min_task_to_accepted_patch_rate_improvement
                ),
                min_state_to_merged_patch_lag_reduction=(
                    args.min_state_to_merged_patch_lag_reduction
                ),
                require_multi_seed_statistical_promotion=(
                    args.require_multi_seed_statistical_promotion
                ),
            ),
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        result = RolloutGateResult(
            accepted=False,
            failures=[f"incomplete_snapshot_manifest:{type(exc).__name__}:{exc}"],
            metrics={"schema_version": STAGED_ROLLOUT_SCHEMA_VERSION},
        )
    decision = result.to_dict()
    decision["schema_version"] = STAGED_ROLLOUT_SCHEMA_VERSION
    decision["snapshot_path"] = str(snapshot_path)
    if snapshot_path.is_file():
        decision["snapshot_sha256"] = snapshot_sha256(snapshot_path)
    if args.evidence_output is not None:
        write_rollout_evidence(args.evidence_output, decision)
    print(json.dumps(decision, indent=2, sort_keys=True))
    return 0 if result.accepted else 1


def _cmd_throughput_remediation_gate(args: argparse.Namespace) -> int:
    try:
        payload = load_summary(args.evidence_path)
        result = throughput_remediation_rollout_gate(
            payload,
            ThroughputRemediationConfig(
                verify_rollback_artifacts=args.verify_rollback_artifacts,
                max_checkpoint_bytes=args.max_checkpoint_bytes,
                max_summary_bytes=args.max_summary_bytes,
            ),
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        result = RolloutGateResult(
            accepted=False,
            failures=[
                f"throughput_remediation_evidence_unreadable:"
                f"{type(exc).__name__}:{exc}"
            ],
            metrics={"schema_version": THROUGHPUT_REMEDIATION_SCHEMA_VERSION},
        )
    decision = result.to_dict()
    decision["schema_version"] = THROUGHPUT_REMEDIATION_SCHEMA_VERSION
    decision["evidence_path"] = str(args.evidence_path)
    if args.evidence_path.is_file():
        decision["evidence_sha256"] = snapshot_sha256(args.evidence_path)
    if args.evidence_output is not None:
        write_rollout_evidence(args.evidence_output, decision)
    if args.report_output is not None:
        write_text_artifact(
            args.report_output,
            render_throughput_remediation_report(result),
        )
    print(json.dumps(decision, indent=2, sort_keys=True))
    return 0 if result.accepted else 1


def _cmd_external_validity_gate(args: argparse.Namespace) -> int:
    try:
        payload = load_summary(args.evidence_path)
        result = external_validity_promotion_gate(
            payload,
            ExternalValidityPromotionConfig(
                min_semantic_score=args.min_semantic_score,
                min_typed_decoding_success_rate=(
                    args.min_typed_decoding_success_rate
                ),
                max_typed_decoding_source_copy_penalty=(
                    args.max_typed_decoding_source_copy_penalty
                ),
                min_fuzzing_mutation_count=args.min_fuzzing_mutation_count,
                min_trusted_negative_count=args.min_trusted_negative_count,
                min_hard_negative_false_positive_reduction=(
                    args.min_hard_negative_false_positive_reduction
                ),
                min_external_validity_score=args.min_external_validity_score,
                min_external_packet_count=args.min_external_packet_count,
            ),
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        result = RolloutGateResult(
            accepted=False,
            failures=[
                f"external_validity_evidence_unreadable:{type(exc).__name__}:{exc}"
            ],
            metrics={"schema_version": EXTERNAL_VALIDITY_PROMOTION_SCHEMA_VERSION},
        )
    decision = result.to_dict()
    decision["schema_version"] = EXTERNAL_VALIDITY_PROMOTION_SCHEMA_VERSION
    decision["evidence_path"] = str(args.evidence_path)
    if args.evidence_path.is_file():
        decision["evidence_sha256"] = snapshot_sha256(args.evidence_path)
    if args.evidence_output is not None:
        write_rollout_evidence(args.evidence_output, decision)
    if args.report_output is not None:
        write_text_artifact(args.report_output, render_external_validity_report(result))
    print(json.dumps(decision, indent=2, sort_keys=True))
    return 0 if result.accepted else 1


def _cmd_compiler_system_promotion_gate(args: argparse.Namespace) -> int:
    try:
        payload = load_summary(args.evidence_path)
        result = compiler_system_promotion_gate(
            payload,
            CompilerSystemPromotionConfig(
                verify_rollback_artifacts=args.verify_rollback_artifacts,
            ),
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        result = RolloutGateResult(
            accepted=False,
            failures=[
                f"compiler_system_evidence_unreadable:{type(exc).__name__}:{exc}"
            ],
            metrics={"schema_version": COMPILER_SYSTEM_PROMOTION_SCHEMA_VERSION},
        )
    decision = result.to_dict()
    decision["schema_version"] = COMPILER_SYSTEM_PROMOTION_SCHEMA_VERSION
    decision["evidence_path"] = str(args.evidence_path)
    if args.evidence_path.is_file():
        decision["evidence_sha256"] = snapshot_sha256(args.evidence_path)
    if args.evidence_output is not None:
        write_rollout_evidence(args.evidence_output, decision)
    if args.report_output is not None:
        write_text_artifact(
            args.report_output,
            render_compiler_system_promotion_report(result),
        )
    print(json.dumps(decision, indent=2, sort_keys=True))
    return 0 if result.accepted else 1


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
