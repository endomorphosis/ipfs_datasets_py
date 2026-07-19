#!/usr/bin/env python3
"""Run a no-mutation Leanstral shadow canary over LegalIR disagreement clusters.

The canary is deliberately report-only.  It ranks the highest-impact
autoencoder/compiler disagreement clusters, builds structured Leanstral audit
requests, checks verified cache entries, optionally calls Leanstral when not in
dry-run mode, and writes a promotion report.  It never seeds TODO queues and
never applies source patches.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import sys
import time
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

REPO_ROOT = Path(__file__).resolve().parents[3]
ACCELERATE_ROOT = REPO_ROOT.parent / "ipfs_accelerate_py"
for import_root in (ACCELERATE_ROOT, REPO_ROOT):
    if import_root.exists():
        import_root_text = str(import_root)
        if import_root_text not in sys.path:
            sys.path.insert(0, import_root_text)

from ipfs_datasets_py.logic.modal import (
    INTROSPECTION_ANALYSIS_SCHEMA_VERSION,
    LEANSTRAL_AUDIT_RESPONSE_SCHEMA_VERSION,
    LEANSTRAL_VERIFIER_SCHEMA_VERSION,
    OWNED_COMPILER_SURFACES,
    OWNED_LEANSTRAL_RULE_GAP_SURFACES,
    IntrospectionAnalysisConfig,
    IntrospectionAnalysisSchemaError,
    LeanstralAuditConfig,
    LeanstralAuditRequest,
    LeanstralAuditResult,
    LeanstralAuditRunner,
    LeanstralAuditVerifier,
    LeanstralAuditValidation,
    LeanstralAuditWorker,
    LeanstralAuditWorkerConfig,
    LeanstralAuditWorkItem,
    LeanstralAuditWorkResult,
    LeanstralVerifierConfig,
    LegalIRGapCluster,
    analyze_introspection_disagreements,
    build_leanstral_audit_work_items,
    validate_disagreement_packet,
    verify_leanstral_audit,
)
from ipfs_datasets_py.logic.modal.leanstral_audit import (
    LEANSTRAL_EVIDENCE_REFRESH_POLICIES,
    canonical_sha256,
)
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.uscode_dataset import (
    HF_USCODE_DATASET_ID,
    USCODE_LAWS_PARQUET,
    USCodeParquetRecord,
)


SHADOW_CANARY_SCHEMA_VERSION = "legal-ir-leanstral-shadow-canary-v1"
REAL_SHADOW_CANARY_SCHEMA_VERSION = "legal-ir-leanstral-real-shadow-canary-v1"
DEFAULT_REPORT_PATH = Path("docs/implementation/reports/leanstral_real_shadow_canary.md")
LEGACY_REPORT_PATH = Path("docs/implementation/reports/leanstral_shadow_canary.md")
DEFAULT_CANONICAL_PACKET_LOG_DIR = Path("workspace/test-logs")
DEFAULT_LEAN_PROOF_CACHE_PATH = Path(
    "workspace/leanstral-audit-worker/lean-proof-cache.json"
)
MAX_CANARY_CLUSTERS = 50
MIN_REAL_CANARY_PACKETS = 25
DEFAULT_LEAN_MAX_FORMULAS = 12
DEFAULT_LEAN_PARALLEL_WORKERS = 2
DEFAULT_LEAN_SLICE_SIZE = 6
DEFAULT_LEAN_TIMEOUT_SECONDS = 30.0
GUARDRAIL_CODES = (
    "provenance",
    "anti_copy",
    "schema",
    "verifier",
)
SYNTHETIC_FIXTURE_PACKET = "synthetic_fixture"
CACHED_REAL_PACKET = "cached_real_packet"
LIVE_CANONICAL_STATE_PACKET = "live_canonical_state_packet"
REAL_PACKET_WITHOUT_PROMOTION_EVIDENCE = "real_packet_without_provider_or_verified_cache"
UNKNOWN_PACKET_PROVENANCE = "unknown_packet_provenance"
PRODUCTION_PACKET_KINDS = frozenset({CACHED_REAL_PACKET, LIVE_CANONICAL_STATE_PACKET})
LATEST_INPUT_SENTINELS = frozenset({"latest", "@latest", "latest-real", "latest_real"})


@dataclass(frozen=True)
class ShadowCanaryConfig:
    """Runtime controls for the no-mutation Leanstral shadow canary."""

    max_clusters: int = MAX_CANARY_CLUSTERS
    dry_run: bool = True
    cache_dir: str = ""
    report_path: str = str(DEFAULT_REPORT_PATH)
    require_local_verifier: bool = True
    max_source_span_copy_ratio: float = 0.25
    provider: str = "mistral_vibe"
    model: str = "Leanstral"
    vibe_agent: str = "lean"
    timeout_seconds: float = 300.0
    validation_repair_retries: int = 1

    def bounded_max_clusters(self) -> int:
        return max(0, min(MAX_CANARY_CLUSTERS, int(self.max_clusters or 0)))

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ProjectedTodoSpecificity:
    """Report-only projection of how narrow a TODO would be if promoted."""

    action: str
    target_component: str
    allowed_paths: Sequence[str]
    target_metrics: Sequence[str]
    theorem_templates: Sequence[str]
    mutation_cases: Sequence[str]
    validation_commands: Sequence[str]
    dedup_key: str
    specificity_score: float
    missing_axes: Sequence[str] = field(default_factory=tuple)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "action": self.action,
            "allowed_paths": list(self.allowed_paths),
            "dedup_key": self.dedup_key,
            "missing_axes": list(self.missing_axes),
            "mutation_cases": list(self.mutation_cases),
            "specificity_score": round(float(self.specificity_score), 6),
            "target_component": self.target_component,
            "target_metrics": list(self.target_metrics),
            "theorem_templates": list(self.theorem_templates),
            "validation_commands": list(self.validation_commands),
        }


@dataclass(frozen=True)
class ShadowClusterAudit:
    """Canary result for one selected disagreement cluster."""

    cluster_id: str
    rank: int
    semantic_family: str
    compiler_surface: str
    semantic_signature: str
    rank_score: float
    recurrence: int
    heldout_impact: float
    confidence: float
    formal_severity: float
    cache_hit: bool
    llm_called: bool
    audit_valid: bool
    audit_verified: bool
    audit_reasons: Sequence[str]
    theorem_outcomes: Mapping[str, Any]
    disagreement_categories: Sequence[str]
    projected_todo: ProjectedTodoSpecificity
    estimated_compiler_impact: Mapping[str, float]
    guardrails: Mapping[str, Any]
    evidence_provenance: Mapping[str, Any]
    request_id: str = ""
    response_hash: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "audit_reasons": list(self.audit_reasons),
            "audit_valid": self.audit_valid,
            "audit_verified": self.audit_verified,
            "cache_hit": self.cache_hit,
            "cluster_id": self.cluster_id,
            "compiler_surface": self.compiler_surface,
            "confidence": round(float(self.confidence), 6),
            "disagreement_categories": list(self.disagreement_categories),
            "estimated_compiler_impact": {
                key: round(float(value), 6)
                for key, value in sorted(self.estimated_compiler_impact.items())
            },
            "evidence_provenance": _json_ready(self.evidence_provenance),
            "formal_severity": round(float(self.formal_severity), 6),
            "guardrails": _json_ready(self.guardrails),
            "heldout_impact": round(float(self.heldout_impact), 6),
            "llm_called": self.llm_called,
            "projected_todo": self.projected_todo.to_dict(),
            "rank": self.rank,
            "rank_score": round(float(self.rank_score), 6),
            "recurrence": self.recurrence,
            "request_id": self.request_id,
            "response_hash": self.response_hash,
            "semantic_family": self.semantic_family,
            "semantic_signature": self.semantic_signature,
            "theorem_outcomes": _json_ready(self.theorem_outcomes),
        }


@dataclass(frozen=True)
class ShadowCanaryResult:
    """Full promotion report for one shadow canary run."""

    schema_version: str
    config: ShadowCanaryConfig
    selected_cluster_count: int
    source_record_count: int
    audits: Sequence[ShadowClusterAudit]
    promotion_allowed: bool
    promotion_blockers: Sequence[str]
    cache_summary: Mapping[str, int]
    evidence_provenance_summary: Mapping[str, Any]
    audit_validity: Mapping[str, int]
    theorem_outcomes: Mapping[str, int]
    disagreement_categories: Mapping[str, int]
    projected_todo_specificity: Mapping[str, float]
    runtime_seconds: float
    estimated_compiler_impact: Mapping[str, float]
    no_mutation: Mapping[str, Any]
    analysis_error: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "analysis_error": self.analysis_error,
            "audit_validity": dict(sorted(self.audit_validity.items())),
            "audits": [audit.to_dict() for audit in self.audits],
            "cache_summary": dict(sorted(self.cache_summary.items())),
            "config": self.config.to_dict(),
            "disagreement_categories": dict(sorted(self.disagreement_categories.items())),
            "estimated_compiler_impact": {
                key: round(float(value), 6)
                for key, value in sorted(self.estimated_compiler_impact.items())
            },
            "evidence_provenance_summary": _json_ready(self.evidence_provenance_summary),
            "no_mutation": _json_ready(self.no_mutation),
            "projected_todo_specificity": {
                key: round(float(value), 6)
                for key, value in sorted(self.projected_todo_specificity.items())
            },
            "promotion_allowed": self.promotion_allowed,
            "promotion_blockers": list(self.promotion_blockers),
            "runtime_seconds": round(float(self.runtime_seconds), 6),
            "schema_version": self.schema_version,
            "selected_cluster_count": self.selected_cluster_count,
            "source_record_count": self.source_record_count,
            "theorem_outcomes": dict(sorted(self.theorem_outcomes.items())),
        }


@dataclass(frozen=True)
class RealShadowCanaryConfig:
    """Runtime controls for the real canonical-state shadow canary."""

    min_real_packets: int = MIN_REAL_CANARY_PACKETS
    max_records: int = 0
    max_clusters: int = MAX_CANARY_CLUSTERS
    provider_enabled: bool = False
    cache_dir: str = ""
    checkpoint_path: str = ""
    report_path: str = str(DEFAULT_REPORT_PATH)
    expected_state_hash: str = ""
    expected_compiler_commit: str = ""
    evidence_refresh_policy: str = "latest_compiler_snapshot"
    max_evidence_packets_per_item: int = 1
    max_concurrency: int = 2
    max_retries: int = 0
    timeout_seconds: float = 300.0
    retry_backoff_seconds: float = 0.25
    provider: str = "mistral_vibe"
    provider_fallbacks: str = ""
    model: str = "Leanstral"
    vibe_agent: str = "lean"
    validation_repair_retries: int = 1
    require_leanstral_model: bool = True
    require_local_verifier: bool = True
    resolve_verifier_examples: bool = False
    verifier_dataset_repo_id: str = HF_USCODE_DATASET_ID
    verifier_laws_path: str = USCODE_LAWS_PARQUET
    run_lean: bool = False
    run_modal_bridge: bool = False
    run_syntax_check: bool = True
    run_graph_check: bool = True
    run_provenance_check: bool = True
    lean_max_formulas: int = DEFAULT_LEAN_MAX_FORMULAS
    lean_parallel_workers: int = DEFAULT_LEAN_PARALLEL_WORKERS
    lean_proof_cache_max_entries: int = 4096
    lean_proof_cache_path: str = str(DEFAULT_LEAN_PROOF_CACHE_PATH)
    lean_proof_cache_ttl_seconds: int = 2_592_000
    lean_slice_size: int = DEFAULT_LEAN_SLICE_SIZE
    lean_timeout_seconds: float = DEFAULT_LEAN_TIMEOUT_SECONDS
    modal_bridge_require_proof: bool = False

    def bounded_min_real_packets(self) -> int:
        return max(1, int(self.min_real_packets or 1))

    def bounded_max_clusters(self) -> int:
        return max(1, min(MAX_CANARY_CLUSTERS, int(self.max_clusters or 1)))

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def worker_config(self) -> LeanstralAuditWorkerConfig:
        return LeanstralAuditWorkerConfig(
            cache_dir=self.cache_dir or None,
            checkpoint_path=self.checkpoint_path or None,
            expected_state_hash=self.expected_state_hash,
            evidence_refresh_policy=self.evidence_refresh_policy,
            max_evidence_packets_per_item=max(
                1, int(self.max_evidence_packets_per_item or 1)
            ),
            max_concurrency=self.max_concurrency,
            max_records=self.max_records,
            max_work_items=self.bounded_max_clusters(),
            max_retries=self.max_retries,
            model=self.model,
            provider=self.provider,
            provider_enabled=self.provider_enabled,
            provider_fallbacks=self.provider_fallbacks,
            request_timeout_seconds=self.timeout_seconds,
            require_leanstral_model=self.require_leanstral_model,
            retry_backoff_seconds=self.retry_backoff_seconds,
            validation_repair_retries=self.validation_repair_retries,
            vibe_agent=self.vibe_agent,
        )

    def verifier_config(self) -> LeanstralVerifierConfig:
        return LeanstralVerifierConfig(
            allow_partial_source_span_evidence=True,
            canonical_recompile_backend="packet_canonical",
            lean_max_formulas=max(0, int(self.lean_max_formulas or 0)),
            lean_parallel_workers=max(1, int(self.lean_parallel_workers or 1)),
            lean_proof_cache_max_entries=max(
                1, int(self.lean_proof_cache_max_entries or 1)
            ),
            lean_proof_cache_path=(
                self.lean_proof_cache_path if self.run_lean else None
            ),
            lean_proof_cache_ttl_seconds=max(
                1, int(self.lean_proof_cache_ttl_seconds or 1)
            ),
            lean_slice_size=max(0, int(self.lean_slice_size or 0)),
            lean_timeout_seconds=max(0.001, float(self.lean_timeout_seconds or 0.0)),
            modal_bridge_require_proof=self.modal_bridge_require_proof,
            run_graph_check=self.run_graph_check,
            run_lean=self.run_lean,
            run_modal_bridge=self.run_modal_bridge,
            run_provenance_check=self.run_provenance_check,
            run_syntax_check=self.run_syntax_check,
        )


@dataclass(frozen=True)
class RealShadowAudit:
    """Audit, cache, and local-verifier evidence for one real work item."""

    work_key: str
    request_id: str
    cache_key: str
    status: str
    compiler_commit: str
    state_hashes: Sequence[str]
    semantic_family: str
    compiler_surface: str
    semantic_signature: str
    evidence_ids: Sequence[str]
    source_record_hashes: Sequence[str]
    cache_hit: bool
    llm_called: bool
    generation_attempts: int
    repair_reasons: Sequence[str]
    audit_valid: bool
    audit_verified: bool
    response_hash: str
    local_verifier_outcome: str
    local_verifier_accepted: bool
    local_verifier_reasons: Sequence[str]
    local_check_count: int
    lean_cache_hit_count: int = 0
    lean_cache_miss_count: int = 0
    lean_parallel_workers: int = 0
    lean_slice_count: int = 0
    lean_verified_formula_count: int = 0
    state_to_verified_audit_lag_seconds: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "audit_valid": self.audit_valid,
            "audit_verified": self.audit_verified,
            "cache_hit": self.cache_hit,
            "cache_key": self.cache_key,
            "compiler_commit": self.compiler_commit,
            "compiler_surface": self.compiler_surface,
            "evidence_ids": list(self.evidence_ids),
            "generation_attempts": int(self.generation_attempts),
            "llm_called": self.llm_called,
            "local_check_count": int(self.local_check_count),
            "local_verifier_accepted": self.local_verifier_accepted,
            "local_verifier_outcome": self.local_verifier_outcome,
            "local_verifier_reasons": list(self.local_verifier_reasons),
            "lean_cache_hit_count": int(self.lean_cache_hit_count),
            "lean_cache_miss_count": int(self.lean_cache_miss_count),
            "lean_parallel_workers": int(self.lean_parallel_workers),
            "lean_slice_count": int(self.lean_slice_count),
            "lean_verified_formula_count": int(self.lean_verified_formula_count),
            "request_id": self.request_id,
            "repair_reasons": list(self.repair_reasons),
            "response_hash": self.response_hash,
            "semantic_family": self.semantic_family,
            "semantic_signature": self.semantic_signature,
            "source_record_hashes": list(self.source_record_hashes),
            "state_hashes": list(self.state_hashes),
            "state_to_verified_audit_lag_seconds": (
                round(float(self.state_to_verified_audit_lag_seconds), 6)
                if self.state_to_verified_audit_lag_seconds is not None
                else None
            ),
            "status": self.status,
            "work_key": self.work_key,
        }


@dataclass(frozen=True)
class RealShadowCanaryResult:
    """Fail-closed real shadow canary report."""

    schema_version: str
    config: RealShadowCanaryConfig
    status: str
    blocked_reasons: Sequence[str]
    source_record_count: int
    valid_real_packet_count: int
    invalid_packet_count: int
    packet_validity: Mapping[str, Any]
    canonical_state: Mapping[str, Any]
    coverage: Mapping[str, Any]
    cache_summary: Mapping[str, int]
    audit_validity: Mapping[str, int]
    verifier_outcomes: Mapping[str, Any]
    state_to_verified_audit_lag_seconds: Mapping[str, Any]
    runtime_seconds: float
    audits: Sequence[RealShadowAudit]
    worker_summary: Mapping[str, Any]
    no_mutation: Mapping[str, Any]
    source_digest: str = ""
    promotion_allowed: bool = False
    synthetic_promotion_evidence_generated: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "audit_validity": dict(sorted(self.audit_validity.items())),
            "audits": [audit.to_dict() for audit in self.audits],
            "blocked_reasons": list(self.blocked_reasons),
            "cache_summary": dict(sorted(self.cache_summary.items())),
            "canonical_state": _json_ready(self.canonical_state),
            "config": self.config.to_dict(),
            "coverage": _json_ready(self.coverage),
            "invalid_packet_count": int(self.invalid_packet_count),
            "no_mutation": _json_ready(self.no_mutation),
            "packet_validity": _json_ready(self.packet_validity),
            "promotion_allowed": self.promotion_allowed,
            "runtime_seconds": round(float(self.runtime_seconds), 6),
            "schema_version": self.schema_version,
            "source_digest": self.source_digest,
            "source_record_count": int(self.source_record_count),
            "state_to_verified_audit_lag_seconds": _json_ready(
                self.state_to_verified_audit_lag_seconds
            ),
            "status": self.status,
            "synthetic_promotion_evidence_generated": (
                self.synthetic_promotion_evidence_generated
            ),
            "valid_real_packet_count": int(self.valid_real_packet_count),
            "verifier_outcomes": _json_ready(self.verifier_outcomes),
            "worker_summary": _json_ready(self.worker_summary),
        }


def run_shadow_canary(
    records: Sequence[Mapping[str, Any]],
    *,
    config: Optional[ShadowCanaryConfig] = None,
    audit_runner: Optional[LeanstralAuditRunner] = None,
    llm_generate: Optional[Any] = None,
) -> ShadowCanaryResult:
    """Run the full no-mutation shadow canary over ranked disagreement records."""

    started = time.monotonic()
    cfg = config or ShadowCanaryConfig()
    max_clusters = cfg.bounded_max_clusters()
    packet_index = _packet_index(records)
    analysis_error = ""
    audits: List[ShadowClusterAudit] = []
    try:
        analysis = analyze_introspection_disagreements(
            records,
            config=IntrospectionAnalysisConfig(max_gaps_per_cluster=50),
        )
        selected_clusters = list(analysis.clusters[:max_clusters])
    except IntrospectionAnalysisSchemaError as exc:
        analysis_error = str(exc)
        selected_clusters = []

    runner = audit_runner or LeanstralAuditRunner(
        LeanstralAuditConfig(
            enabled=not cfg.dry_run,
            provider=cfg.provider,
            model=cfg.model,
            vibe_agent=cfg.vibe_agent,
            timeout_seconds=cfg.timeout_seconds,
            cache_dir=cfg.cache_dir or None,
            validation_repair_retries=cfg.validation_repair_retries,
        ),
        llm_generate=llm_generate,
    )

    for rank, cluster in enumerate(selected_clusters, start=1):
        audits.append(
            _audit_cluster(
                cluster,
                rank=rank,
                records_by_evidence_id=packet_index,
                config=cfg,
                runner=runner,
            )
        )

    runtime = time.monotonic() - started
    promotion_allowed, blockers = _promotion_decision(
        audits,
        dry_run=cfg.dry_run,
        analysis_error=analysis_error,
        selected_cluster_count=len(selected_clusters),
    )
    return ShadowCanaryResult(
        schema_version=SHADOW_CANARY_SCHEMA_VERSION,
        config=cfg,
        selected_cluster_count=len(selected_clusters),
        source_record_count=len(records),
        audits=tuple(audits),
        promotion_allowed=promotion_allowed,
        promotion_blockers=tuple(blockers),
        cache_summary=_cache_summary(audits),
        evidence_provenance_summary=_evidence_provenance_summary(audits),
        audit_validity=_audit_validity_summary(audits),
        theorem_outcomes=_theorem_summary(audits),
        disagreement_categories=dict(Counter(cat for audit in audits for cat in audit.disagreement_categories)),
        projected_todo_specificity=_specificity_summary(audits),
        runtime_seconds=runtime,
        estimated_compiler_impact=_impact_summary(audits),
        no_mutation={
            "queue_seeded_count": 0,
            "source_mutation_count": 0,
            "source_mutation_detected": False,
            "todo_queue_seeded": False,
            "mode": "shadow",
            "report_only": True,
            "dry_run_non_production": bool(cfg.dry_run),
            "production_promotion_eligible": False,
        },
        analysis_error=analysis_error,
    )


def run_real_shadow_canary(
    records: Sequence[Mapping[str, Any]],
    *,
    config: Optional[RealShadowCanaryConfig] = None,
    worker: Optional[LeanstralAuditWorker] = None,
    llm_generate: Optional[Any] = None,
    verifier_examples_by_sample_id: Optional[Mapping[str, Mapping[str, Any]]] = None,
) -> RealShadowCanaryResult:
    """Run the real no-mutation canary over canonical-state packets.

    This path accepts only production-shaped disagreement packets.  Synthetic
    dry-run fixtures are invalid input here and cannot contribute to promotion
    evidence.
    """

    started = time.monotonic()
    cfg = config or RealShadowCanaryConfig()
    source_records = [dict(_mapping(record.get("payload")) or record) for record in records]

    candidate_records, invalid_records = _validate_real_packets(
        source_records,
        config=cfg,
        enforce_expected_state=False,
    )
    valid_records, snapshot_selection = _select_real_canary_snapshot(
        candidate_records,
        config=cfg,
    )
    selected_valid_records, selected_invalid_records = _validate_real_packets(
        valid_records,
        config=cfg,
        enforce_expected_state=True,
    )
    valid_records = selected_valid_records
    invalid_records = list(invalid_records) + list(selected_invalid_records)
    source_digest = canonical_sha256(
        {
            "records": [canonical_sha256(record) for record in valid_records],
            "source_record_count": len(source_records),
            "source_valid_packet_count": len(candidate_records),
            "snapshot_selection": snapshot_selection,
            "valid_real_packet_count": len(valid_records),
        }
    )
    canonical_state = _canonical_state_summary(valid_records, config=cfg)
    canonical_state["snapshot_selection"] = snapshot_selection
    blocked_reasons: List[str] = []
    if not source_records:
        blocked_reasons.append("no_canonical_packet_input")
    if len(valid_records) < cfg.bounded_min_real_packets():
        blocked_reasons.append("insufficient_real_canonical_packets")
    if canonical_state["state_hash_count"] != 1:
        blocked_reasons.append("canonical_state_not_unique")
    if canonical_state["compiler_commit_count"] != 1:
        blocked_reasons.append("compiler_commit_not_unique")
    if canonical_state.get("expected_state_hash_mismatch"):
        blocked_reasons.append("expected_state_hash_mismatch")
    if canonical_state.get("expected_compiler_commit_mismatch"):
        blocked_reasons.append("expected_compiler_commit_mismatch")

    worker_config = cfg.worker_config()
    canary_worker = worker or LeanstralAuditWorker(
        worker_config,
        llm_generate=llm_generate,
    )
    worker_summary = None
    items: List[LeanstralAuditWorkItem] = []
    stale_rejections: Sequence[Mapping[str, Any]] = ()
    if valid_records and not any(
        reason
        in {
            "canonical_state_not_unique",
            "compiler_commit_not_unique",
            "expected_state_hash_mismatch",
            "expected_compiler_commit_mismatch",
        }
        for reason in blocked_reasons
    ):
        worker_summary = asyncio.run(
            canary_worker.run_records(valid_records, source_digest=source_digest)
        )
        items, stale_rejections = build_leanstral_audit_work_items(
            valid_records,
            config=worker_config,
        )
    else:
        items, stale_rejections = build_leanstral_audit_work_items(
            valid_records,
            config=worker_config,
        )

    work_results_by_key = {
        result.work_key: result
        for result in (tuple(worker_summary.results) if worker_summary is not None else ())
    }
    verifier_example_resolution: Dict[str, Any] = {
        "enabled": bool(cfg.resolve_verifier_examples),
        "failure_count": 0,
        "failures": [],
        "requested_sample_count": 0,
        "resolved_sample_count": 0,
        "source": "disabled",
    }
    resolved_verifier_examples: Mapping[str, Mapping[str, Any]] = (
        verifier_examples_by_sample_id or {}
    )
    if verifier_examples_by_sample_id is not None:
        verifier_example_resolution.update(
            {
                "enabled": True,
                "requested_sample_count": len(verifier_examples_by_sample_id),
                "resolved_sample_count": len(verifier_examples_by_sample_id),
                "source": "provided",
            }
        )
    elif cfg.resolve_verifier_examples and valid_records:
        try:
            resolved_verifier_examples, verifier_example_resolution = (
                _load_hf_verifier_examples(valid_records, config=cfg)
            )
        except Exception as exc:  # pragma: no cover - external I/O fail-closed path
            verifier_example_resolution.update(
                {
                    "failure_count": 1,
                    "failures": [f"{exc.__class__.__name__}: {str(exc)[:240]}"],
                    "source": "huggingface_error",
                }
            )
    real_audits = _verify_real_shadow_audits(
        items,
        results_by_key=work_results_by_key,
        records=valid_records,
        worker=canary_worker,
        config=cfg,
        verifier_examples_by_sample_id=resolved_verifier_examples,
    )
    if worker_summary is not None and worker_summary.unavailable_count:
        blocked_reasons.append("leanstral_labs_access_unavailable")
    if worker_summary is not None and worker_summary.failed_count:
        blocked_reasons.append("leanstral_worker_failures")
    if any(audit.status == "timeout" for audit in real_audits):
        blocked_reasons.append("leanstral_worker_timeouts")
    if stale_rejections:
        blocked_reasons.append("stale_state_rejections")
    if worker_summary is not None and worker_summary.work_item_count == 0:
        blocked_reasons.append("no_audit_work_items")
    if not any(audit.cache_hit or audit.llm_called for audit in real_audits):
        blocked_reasons.append("no_provider_or_verified_cache_evidence")
    if not any(audit.local_verifier_accepted for audit in real_audits):
        blocked_reasons.append("no_local_verifier_acceptance")
        if cfg.resolve_verifier_examples and not resolved_verifier_examples:
            blocked_reasons.append("verifier_example_resolution_failed")
    if not any(audit.audit_valid and audit.audit_verified for audit in real_audits):
        blocked_reasons.append("no_verified_audit_responses")
    if invalid_records:
        blocked_reasons.append("invalid_packets_present")

    runtime = time.monotonic() - started
    worker_payload = (
        worker_summary.to_dict()
        if worker_summary is not None
        else {
            "completed_count": 0,
            "failed_count": 0,
            "llm_call_count": 0,
            "results": [],
            "skipped": True,
            "unavailable_count": 0,
            "work_item_count": len(items),
        }
    )
    if stale_rejections:
        worker_payload["stale_state_rejections"] = [
            _json_ready(item) for item in stale_rejections
        ]
    worker_payload["verifier_example_resolution"] = _json_ready(
        verifier_example_resolution
    )
    blocked = sorted(set(blocked_reasons))
    return RealShadowCanaryResult(
        schema_version=REAL_SHADOW_CANARY_SCHEMA_VERSION,
        config=cfg,
        status="blocked" if blocked else "passed",
        blocked_reasons=tuple(blocked),
        source_record_count=len(source_records),
        valid_real_packet_count=len(valid_records),
        invalid_packet_count=len(invalid_records),
        packet_validity=_packet_validity_summary(
            valid_records,
            invalid_records,
            min_packets=cfg.bounded_min_real_packets(),
        ),
        canonical_state=canonical_state,
        coverage=_real_coverage_summary(valid_records, items),
        cache_summary=_real_cache_summary(real_audits, worker_payload),
        audit_validity=_real_audit_validity_summary(real_audits),
        verifier_outcomes=_real_verifier_summary(real_audits),
        state_to_verified_audit_lag_seconds=_lag_summary(
            [
                audit.state_to_verified_audit_lag_seconds
                for audit in real_audits
                if audit.local_verifier_accepted
            ]
        ),
        runtime_seconds=runtime,
        audits=tuple(real_audits),
        worker_summary=worker_payload,
        no_mutation={
            "mode": "real_shadow",
            "report_only": True,
            "queue_seeded_count": 0,
            "source_mutation_count": 0,
            "source_mutation_detected": False,
            "todo_queue_seeded": False,
            "provider_cache_writes_allowed": bool(cfg.provider_enabled),
            "promotion_evidence_generated": not bool(blocked),
        },
        source_digest=source_digest,
        promotion_allowed=False,
        synthetic_promotion_evidence_generated=False,
    )


def write_markdown_report(
    result: ShadowCanaryResult | RealShadowCanaryResult,
    path: str | Path,
) -> Path:
    """Write a human-readable canary report."""

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(render_markdown_report(result), encoding="utf-8")
    return target


def render_markdown_report(result: ShadowCanaryResult | RealShadowCanaryResult) -> str:
    """Render a compact Markdown report with the required acceptance sections."""

    if isinstance(result, RealShadowCanaryResult):
        return render_real_markdown_report(result)
    payload = result.to_dict()
    lines = [
        "# Leanstral Shadow Canary",
        "",
        f"- Schema: `{result.schema_version}`",
        f"- Mode: `{'dry-run' if result.config.dry_run else 'shadow'}`",
        f"- Production evidence: `{'non-production dry run' if result.config.dry_run else 'shadow evidence only'}`",
        f"- Selected clusters: {result.selected_cluster_count} of {result.source_record_count} source records",
        f"- Runtime seconds: {result.runtime_seconds:.6f}",
        f"- Promotion allowed: `{str(result.promotion_allowed).lower()}`",
    ]
    if result.promotion_blockers:
        lines.append(f"- Promotion blockers: {', '.join(f'`{item}`' for item in result.promotion_blockers)}")
    if result.analysis_error:
        lines.append(f"- Analysis error: `{result.analysis_error}`")
    lines.extend(
        [
            "",
            "## Cache Use",
            _markdown_kv(result.cache_summary),
            "",
            "## Evidence Provenance",
            _markdown_kv(result.evidence_provenance_summary),
            "",
            "## Audit Validity",
            _markdown_kv(result.audit_validity),
            "",
            "## Theorem Outcomes",
            _markdown_kv(result.theorem_outcomes),
            "",
            "## Disagreement Categories",
            _markdown_kv(result.disagreement_categories),
            "",
            "## Projected TODO Specificity",
            _markdown_kv(result.projected_todo_specificity),
            "",
            "## Estimated Compiler Impact",
            _markdown_kv(result.estimated_compiler_impact),
            "",
            "## No-Mutation Contract",
            _markdown_kv(result.no_mutation),
            "",
            "## Cluster Audits",
        ]
    )
    if not result.audits:
        lines.append("")
        lines.append("No clusters were selected.")
    for audit in result.audits:
        lines.extend(
            [
                "",
                f"### {audit.rank}. `{audit.cluster_id}`",
                f"- Surface: `{audit.compiler_surface}`",
                f"- Family: `{audit.semantic_family}`",
                f"- Signature: `{audit.semantic_signature}`",
                f"- Score: {audit.rank_score:.6f}; recurrence: {audit.recurrence}; held-out impact: {audit.heldout_impact:.6f}",
                f"- Cache hit: `{str(audit.cache_hit).lower()}`; LLM called: `{str(audit.llm_called).lower()}`",
                f"- Audit valid: `{str(audit.audit_valid).lower()}`; verified: `{str(audit.audit_verified).lower()}`",
                f"- Evidence provenance: `{audit.evidence_provenance.get('dominant_kind', UNKNOWN_PACKET_PROVENANCE)}`; production eligible: `{str(bool(audit.evidence_provenance.get('production_eligible', False))).lower()}`",
                f"- Guardrails: `{_guardrail_status(audit.guardrails)}`",
                f"- Projected TODO: `{audit.projected_todo.action}` on `{audit.projected_todo.target_component}`; specificity {audit.projected_todo.specificity_score:.3f}",
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


def render_real_markdown_report(result: RealShadowCanaryResult) -> str:
    """Render the real canonical-state shadow canary report."""

    payload = result.to_dict()
    lines = [
        "# Leanstral Real Shadow Canary",
        "",
        f"- Schema: `{result.schema_version}`",
        "- Mode: `real-shadow`",
        f"- Status: `{result.status}`",
        f"- Source records: {result.source_record_count}",
        f"- Valid real packets: {result.valid_real_packet_count}",
        f"- Invalid packets: {result.invalid_packet_count}",
        f"- Runtime seconds: {result.runtime_seconds:.6f}",
        f"- Promotion allowed: `{str(result.promotion_allowed).lower()}`",
        f"- Synthetic promotion evidence generated: `{str(result.synthetic_promotion_evidence_generated).lower()}`",
    ]
    if result.blocked_reasons:
        lines.append(
            "- Blocked reasons: "
            + ", ".join(f"`{reason}`" for reason in result.blocked_reasons)
        )
    lines.extend(
        [
            "",
            "## Real Packet Validity",
            _markdown_kv(result.packet_validity),
            "",
            "## Canonical State And Compiler Commit",
            _markdown_kv(result.canonical_state),
            "",
            "## Family And Surface Coverage",
            _markdown_kv(result.coverage),
            "",
            "## Cache Behavior",
            _markdown_kv(result.cache_summary),
            "",
            "## Audit Validity",
            _markdown_kv(result.audit_validity),
            "",
            "## Verifier Outcomes",
            _markdown_kv(result.verifier_outcomes),
            "",
            "## State-To-Verified-Audit Lag",
            _markdown_kv(result.state_to_verified_audit_lag_seconds),
            "",
            "## No-Mutation Contract",
            _markdown_kv(result.no_mutation),
            "",
            "## Audit Work Items",
        ]
    )
    if not result.audits:
        lines.append("")
        lines.append("No audit work items produced verified promotion evidence.")
    for index, audit in enumerate(result.audits, start=1):
        lines.extend(
            [
                "",
                f"### {index}. `{audit.work_key[:16]}`",
                f"- Status: `{audit.status}`",
                f"- Request: `{audit.request_id}`",
                f"- Surface: `{audit.compiler_surface}`",
                f"- Family: `{audit.semantic_family}`",
                f"- State hashes: {', '.join(f'`{value}`' for value in audit.state_hashes) or '`none`'}",
                f"- Compiler commit: `{audit.compiler_commit}`",
                f"- Cache hit: `{str(audit.cache_hit).lower()}`; LLM called: `{str(audit.llm_called).lower()}`",
                f"- Audit valid: `{str(audit.audit_valid).lower()}`; verified: `{str(audit.audit_verified).lower()}`",
                f"- Local verifier: `{audit.local_verifier_outcome}`; accepted: `{str(audit.local_verifier_accepted).lower()}`; checks: {audit.local_check_count}",
            ]
        )
        if audit.lean_slice_count:
            lines.append(
                "- Lean slices: "
                f"{audit.lean_slice_count}; proof-cache hits/misses: "
                f"{audit.lean_cache_hit_count}/{audit.lean_cache_miss_count}; "
                f"workers: {audit.lean_parallel_workers}; "
                f"verified formulas: {audit.lean_verified_formula_count}"
            )
        if audit.state_to_verified_audit_lag_seconds is not None:
            lines.append(
                f"- State-to-verified-audit lag seconds: {audit.state_to_verified_audit_lag_seconds:.6f}"
            )
        if audit.local_verifier_reasons:
            lines.append(
                "- Verifier reasons: "
                + ", ".join(f"`{reason}`" for reason in audit.local_verifier_reasons)
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


def load_disagreement_records(paths: Sequence[str | Path]) -> List[Dict[str, Any]]:
    """Load JSON/JSONL disagreement packet records from files or directories."""

    records: List[Dict[str, Any]] = []
    for raw_path in paths:
        path = Path(raw_path).expanduser()
        if not path.exists():
            raise FileNotFoundError(str(path))
        files = sorted(path.rglob("*.json")) + sorted(path.rglob("*.jsonl")) if path.is_dir() else [path]
        for file_path in files:
            records.extend(_records_from_file(file_path))
    return records


def discover_latest_disagreement_inputs(
    log_dir: str | Path = DEFAULT_CANONICAL_PACKET_LOG_DIR,
    *,
    min_records: int = 1,
) -> List[str]:
    """Return the newest canonical disagreement export with enough records."""

    root = Path(log_dir).expanduser()
    if not root.is_absolute():
        root = REPO_ROOT / root
    if not root.is_dir():
        return []
    minimum = max(1, int(min_records or 1))
    candidates = [
        path
        for path in root.glob("*.canonical-disagreements.jsonl")
        if path.is_file() and path.stat().st_size > 0
    ]
    candidates.sort(key=lambda path: (path.stat().st_mtime, path.name), reverse=True)
    for path in candidates:
        if _jsonl_record_count(path) >= minimum:
            return [str(path)]
    return []


def resolve_disagreement_input_paths(
    paths: Sequence[str | Path],
    *,
    min_records: int = 1,
) -> List[str]:
    """Resolve operator-friendly input aliases without hiding missing explicit paths."""

    resolved: List[str] = []
    for raw_path in paths:
        value = str(raw_path).strip()
        if value in LATEST_INPUT_SENTINELS:
            resolved.extend(
                discover_latest_disagreement_inputs(
                    DEFAULT_CANONICAL_PACKET_LOG_DIR,
                    min_records=min_records,
                )
            )
        elif value:
            resolved.append(value)
    return resolved


def _jsonl_record_count(path: Path) -> int:
    count = 0
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    count += 1
    except OSError:
        return 0
    return count


def build_dry_run_fixture_records(count: int = 8) -> List[Dict[str, Any]]:
    """Return deterministic canary packets used when dry-run has no input."""

    families = [
        ("deontic.ir", "deontic", "obligation_scope"),
        ("external_provers.router", "prover", "proof_route_failure_ratio"),
        ("knowledge_graphs.neo4j_compat", "knowledge_graph", "edge_role"),
        ("modal.ir_decompiler", "decompiler", "exception_reconstruction"),
        ("modal.temporal", "temporal", "deadline_order"),
        ("modal.source_provenance", "provenance", "source_span_hash"),
        ("modal.frame_logic", "frame_logic", "slot_alignment"),
        ("event_calculus.core", "event_calculus", "fluent_interval"),
    ]
    records: List[Dict[str, Any]] = []
    for index in range(max(1, int(count))):
        surface, family, component = families[index % len(families)]
        sample_id = f"dry-run-sample-{index + 1:03d}"
        evidence_id = f"dry-run-evidence-{index + 1:03d}"
        impact = max(0.05, 0.92 - index * 0.045)
        confidence = max(0.55, 0.9 - index * 0.02)
        records.append(
            {
                "anti_copy_evidence": {
                    "dense_weight_tables_included": False,
                    "source_span_copy_ratio": 0.0,
                    "stripped_dense_input_key_hashes": [],
                },
                "evidence_id": evidence_id,
                "evidence_provenance": {
                    "kind": SYNTHETIC_FIXTURE_PACKET,
                    "metric_observation_kind": "synthetic_projection",
                    "production_eligible": False,
                    "generated_by": "run_leanstral_shadow_canary.build_dry_run_fixture_records",
                    "dry_run_fixture": True,
                },
                "heldout_impact_by_surface": {surface: impact},
                "legal_ir_component_gaps": {f"{surface}.{component}": 0.35 + index * 0.01},
                "legal_ir_views": {
                    "canonical": {
                        "family_distribution": {family: 1.0},
                        "modal_ir_hash": canonical_sha256({"sample_id": sample_id, "index": index}),
                    },
                    "predicted": {
                        "family_distribution": {"temporal" if family != "temporal" else "deontic": confidence},
                        "predicted_family": "temporal" if family != "temporal" else "deontic",
                        "target_family": family,
                    },
                },
                "proof_route_status": {
                    "attempted_count": 2,
                    "compiles": family != "prover",
                    "failure_ratio": 0.25 if family == "prover" else 0.0,
                    "route_status": "failed" if family == "prover" else "compiled",
                    "valid_count": 1 if family == "prover" else 2,
                },
                "sample_hashes": {
                    "modal_ir_hash": canonical_sha256({"modal_ir": sample_id}),
                    "normalized_text_hash": canonical_sha256({"normalized": sample_id}),
                    "sample_id": sample_id,
                    "source_span_hashes": {
                        f"formula-{index + 1:03d}": canonical_sha256({"span": sample_id})
                    },
                    "source_text_hash": canonical_sha256({"source": sample_id}),
                },
                "schema_version": "legal-ir-introspection-packet-v1",
                "synthesis_focus": [component],
                "versions": {
                    "canary_manifest_version": "dry-run-fixture-v1",
                    "export_schema_version": "legal-ir-introspection-packet-v1",
                    "evidence_provenance_kind": SYNTHETIC_FIXTURE_PACKET,
                },
            }
        )
    return records


def _audit_cluster(
    cluster: LegalIRGapCluster,
    *,
    rank: int,
    records_by_evidence_id: Mapping[str, Mapping[str, Any]],
    config: ShadowCanaryConfig,
    runner: LeanstralAuditRunner,
) -> ShadowClusterAudit:
    records = [
        records_by_evidence_id[evidence_id]
        for evidence_id in cluster.evidence_ids
        if evidence_id in records_by_evidence_id
    ]
    request = _build_audit_request(
        cluster,
        records,
        model={
            "provider": config.provider,
            "model": config.model,
            "vibe_agent": config.vibe_agent,
        },
    )
    cache_entry = runner.cache.get_accepted_entry(request)
    if cache_entry is not None:
        audit_result = LeanstralAuditResult(
            request=request,
            response=cache_entry.response,
            validation=LeanstralAuditValidation(
                accepted=True,
                verified=True,
                response_hash=cache_entry.response_hash,
                cache_key=request.cache_key,
                verified_by=("leanstral-audit-schema-v2", "leanstral-audit-cache-v1"),
            ),
            llm_called=False,
            cache_hit=True,
        )
    elif config.dry_run:
        audit_result = LeanstralAuditResult(
            request=request,
            response=None,
            validation=LeanstralAuditValidation(
                accepted=False,
                verified=False,
                reasons=("dry_run_no_provider_audit",),
                cache_key=request.cache_key,
            ),
            llm_called=False,
            cache_hit=False,
        )
    else:
        audit_result = runner.run(
            evidence=request.evidence,
            prompt=request.prompt,
            theorem_registry_hash=request.theorem_registry_hash,
            proof_obligation_ids=request.proof_obligation_ids,
        )

    verification = None
    if audit_result.response is not None and config.require_local_verifier:
        try:
            verification = verify_leanstral_audit(
                audit_result.request,
                audit_result.response,
                config=LeanstralVerifierConfig(
                    run_lean=False,
                    run_modal_bridge=False,
                ),
            )
        except Exception as exc:  # pragma: no cover - defensive fail-closed path
            verification = {
                "accepted": False,
                "outcome": "rejected",
                "reasons": (f"verifier_error:{exc.__class__.__name__}",),
                "schema_version": LEANSTRAL_VERIFIER_SCHEMA_VERSION,
            }

    guardrails = _guardrail_report(
        cluster,
        records,
        audit_result=audit_result,
        verification=verification,
        config=config,
    )
    evidence_provenance = _audit_evidence_provenance(records, audit_result=audit_result)
    theorem_outcomes = _cluster_theorem_outcomes(cluster, records, verification=verification)
    projected = _project_todo_specificity(cluster)
    return ShadowClusterAudit(
        cluster_id=cluster.cluster_id or cluster.expected_cluster_id(),
        rank=rank,
        semantic_family=cluster.semantic_family,
        compiler_surface=cluster.compiler_surface,
        semantic_signature=cluster.semantic_signature,
        rank_score=float(cluster.rank_score),
        recurrence=int(cluster.recurrence),
        heldout_impact=float(cluster.heldout_impact),
        confidence=float(cluster.confidence),
        formal_severity=float(cluster.formal_severity),
        cache_hit=bool(audit_result.cache_hit),
        llm_called=bool(audit_result.llm_called),
        audit_valid=bool(audit_result.validation.accepted),
        audit_verified=bool(audit_result.validation.verified),
        audit_reasons=tuple(audit_result.validation.reasons),
        theorem_outcomes=theorem_outcomes,
        disagreement_categories=_disagreement_categories(cluster),
        projected_todo=projected,
        estimated_compiler_impact=_estimated_cluster_impact(cluster),
        guardrails=guardrails,
        evidence_provenance=evidence_provenance,
        request_id=audit_result.request.request_id,
        response_hash=audit_result.validation.response_hash,
    )


def _build_audit_request(
    cluster: LegalIRGapCluster,
    records: Sequence[Mapping[str, Any]],
    *,
    model: Optional[Mapping[str, Any]] = None,
) -> LeanstralAuditRequest:
    evidence = {
        "cluster": cluster.to_dict(include_gaps=True),
        "evidence_packets": [_compact_packet(record) for record in records],
        "evidence_provenance": _records_evidence_provenance(records),
        "guardrail_requirements": list(GUARDRAIL_CODES),
        "no_mutation_contract": {
            "queue_seeded": False,
            "source_mutation_allowed": False,
        },
    }
    prompt = {
        "template": "leanstral-shadow-canary-cluster-audit-v1",
        "instructions": [
            "Audit this ranked LegalIR disagreement cluster in shadow mode only.",
            "Do not seed TODO queues, mutate source files, or propose unbounded work.",
            "Classify the disagreement using the allowed audit response schema.",
            "Bind every finding to provenance hashes, anti-copy evidence, and verifier-owned proof obligations.",
        ],
    }
    proof_obligations = _proof_obligation_ids(cluster)
    theorem_registry_hash = canonical_sha256(
        {
            "cluster_id": cluster.cluster_id or cluster.expected_cluster_id(),
            "formal_severity": cluster.formal_severity,
            "proof_obligation_ids": proof_obligations,
            "schema_version": "leanstral-shadow-canary-theorem-registry-v1",
            "semantic_family": cluster.semantic_family,
        }
    )
    return LeanstralAuditRequest.build(
        evidence=evidence,
        prompt=prompt,
        model=model or {"provider": "mistral_vibe", "model": "Leanstral", "vibe_agent": "lean"},
        theorem_registry_hash=theorem_registry_hash,
        proof_obligation_ids=proof_obligations,
    )


def _project_todo_specificity(cluster: LegalIRGapCluster) -> ProjectedTodoSpecificity:
    surface = OWNED_LEANSTRAL_RULE_GAP_SURFACES.get(cluster.compiler_surface)
    fallback = OWNED_COMPILER_SURFACES.get(cluster.compiler_surface)
    if surface is not None:
        action = surface.action
        target_component = surface.component
        allowed_paths = tuple(surface.allowed_paths)
        metrics = tuple(surface.target_metrics)
        theorem_templates = tuple(surface.theorem_templates)
        mutation_cases = tuple(surface.mutation_cases)
    elif fallback is not None:
        action = f"review_{fallback.semantic_family}_legal_ir_gap"
        target_component = fallback.surface
        allowed_paths = tuple(fallback.code_paths)
        metrics = (f"{fallback.semantic_family}_heldout_impact",)
        theorem_templates = ("source_provenance_preserved",)
        mutation_cases = (f"{fallback.semantic_family}_semantic_regression",)
    else:
        action = "review_legal_ir_gap"
        target_component = cluster.compiler_surface
        allowed_paths = tuple(cluster.owned_code_paths)
        metrics = ()
        theorem_templates = ()
        mutation_cases = ()
    validation_commands = (
        "PYTHONPATH=. python -m pytest tests/unit_tests/logic/modal/test_leanstral_validation.py -q",
        "PYTHONPATH=. python -m pytest tests/unit_tests/logic/modal/test_leanstral_verifier.py -q",
    )
    axes = {
        "allowed_paths": bool(allowed_paths),
        "target_metrics": bool(metrics),
        "theorem_templates": bool(theorem_templates),
        "mutation_cases": bool(mutation_cases),
        "evidence_ids": bool(cluster.evidence_ids),
        "sample_ids": bool(cluster.sample_ids),
        "validation_commands": bool(validation_commands),
    }
    missing = tuple(key for key, present in axes.items() if not present)
    score = sum(1 for present in axes.values() if present) / len(axes)
    dedup_key = canonical_sha256(
        {
            "action": action,
            "cluster_id": cluster.cluster_id or cluster.expected_cluster_id(),
            "surface": target_component,
            "signature": cluster.semantic_signature,
        }
    )[:16]
    return ProjectedTodoSpecificity(
        action=action,
        target_component=target_component,
        allowed_paths=allowed_paths,
        target_metrics=metrics,
        theorem_templates=theorem_templates,
        mutation_cases=mutation_cases,
        validation_commands=validation_commands,
        dedup_key=f"leanstral-shadow-{dedup_key}",
        specificity_score=score,
        missing_axes=missing,
    )


def _guardrail_report(
    cluster: LegalIRGapCluster,
    records: Sequence[Mapping[str, Any]],
    *,
    audit_result: LeanstralAuditResult,
    verification: Any,
    config: ShadowCanaryConfig,
) -> Dict[str, Any]:
    provenance = _provenance_guardrail(records, cluster)
    anti_copy = _anti_copy_guardrail(records, max_ratio=config.max_source_span_copy_ratio)
    schema = {
        "passed": (
            cluster.schema_version == INTROSPECTION_ANALYSIS_SCHEMA_VERSION
            and all(_schema_record_valid(record) for record in records)
            and (
                audit_result.response is None
                or audit_result.response.schema_version == LEANSTRAL_AUDIT_RESPONSE_SCHEMA_VERSION
            )
        ),
        "cluster_schema_version": cluster.schema_version,
        "audit_response_schema_version": audit_result.response.schema_version
        if audit_result.response
        else "",
    }
    verifier = _verifier_guardrail(audit_result, verification, dry_run=config.dry_run)
    return {
        "anti_copy": anti_copy,
        "provenance": provenance,
        "schema": schema,
        "verifier": verifier,
        "passed": bool(
            provenance["passed"]
            and anti_copy["passed"]
            and schema["passed"]
            and verifier["passed"]
        ),
    }


def _provenance_guardrail(
    records: Sequence[Mapping[str, Any]],
    cluster: LegalIRGapCluster,
) -> Dict[str, Any]:
    missing: List[str] = []
    if not cluster.evidence_ids:
        missing.append("cluster_evidence_ids")
    if not cluster.sample_ids:
        missing.append("cluster_sample_ids")
    if not cluster.owned_code_paths:
        missing.append("owned_code_paths")
    if not records:
        missing.append("evidence_packets")
    for index, record in enumerate(records):
        hashes = _mapping(record.get("sample_hashes"))
        span_hashes = _mapping(hashes.get("source_span_hashes") or record.get("source_span_hashes"))
        modal_hash = str(hashes.get("modal_ir_hash") or _mapping(record.get("legal_ir_views")).get("modal_ir_hash") or "")
        if not modal_hash:
            missing.append(f"record[{index}].modal_ir_hash")
        if not span_hashes:
            missing.append(f"record[{index}].source_span_hashes")
    return {
        "missing": tuple(dict.fromkeys(missing)),
        "passed": not missing,
    }


def _anti_copy_guardrail(
    records: Sequence[Mapping[str, Any]],
    *,
    max_ratio: float,
) -> Dict[str, Any]:
    reasons: List[str] = []
    ratios: List[float] = []
    if not records:
        reasons.append("missing_evidence_packets")
    for index, record in enumerate(records):
        anti_copy = _mapping(record.get("anti_copy_evidence") or record.get("anti_copy"))
        if not anti_copy:
            reasons.append(f"record[{index}].missing_anti_copy_evidence")
            continue
        if bool(anti_copy.get("dense_weight_tables_included", False)):
            reasons.append(f"record[{index}].dense_weight_tables_included")
        ratio = _finite_float(anti_copy.get("source_span_copy_ratio"), 0.0)
        ratios.append(ratio)
        if ratio > max_ratio:
            reasons.append(f"record[{index}].source_span_copy_ratio_exceeded")
    return {
        "max_observed_source_span_copy_ratio": max(ratios) if ratios else 0.0,
        "passed": not reasons,
        "reasons": tuple(dict.fromkeys(reasons)),
    }


def _verifier_guardrail(
    audit_result: LeanstralAuditResult,
    verification: Any,
    *,
    dry_run: bool,
) -> Dict[str, Any]:
    if dry_run and audit_result.response is None:
        return {
            "passed": False,
            "reasons": ("dry_run_no_provider_audit",),
            "verifier_outcome": "not-run",
        }
    reasons = list(audit_result.validation.reasons)
    audit_ok = bool(audit_result.validation.accepted and audit_result.validation.verified)
    verifier_ok = True
    outcome = "schema-only"
    if verification is not None:
        verifier_ok = bool(_get_attr_or_key(verification, "accepted", False))
        outcome = str(_get_attr_or_key(verification, "outcome", "") or "")
        if not verifier_ok:
            reasons.extend(str(reason) for reason in _get_attr_or_key(verification, "reasons", ()) or ())
    return {
        "audit_validation_verified_by": tuple(audit_result.validation.verified_by),
        "passed": bool(audit_ok and verifier_ok),
        "reasons": tuple(dict.fromkeys(reasons)),
        "verifier_outcome": outcome,
    }


def _cluster_theorem_outcomes(
    cluster: LegalIRGapCluster,
    records: Sequence[Mapping[str, Any]],
    *,
    verification: Any,
) -> Dict[str, Any]:
    proof_routes = [_mapping(record.get("proof_route_status") or record.get("prover_signal")) for record in records]
    attempted = sum(int(_finite_float(route.get("attempted_count"), 0.0)) for route in proof_routes)
    valid = sum(int(_finite_float(route.get("valid_count"), 0.0)) for route in proof_routes)
    failures = sum(1 for route in proof_routes if route and not bool(route.get("compiles", True)))
    local_checks = _get_attr_or_key(verification, "local_checks", ()) if verification is not None else ()
    verifier_outcome = str(_get_attr_or_key(verification, "outcome", "") or "not-run")
    return {
        "cluster_formal_severity": float(cluster.formal_severity),
        "local_check_count": len(local_checks or ()),
        "proof_route_attempted_count": attempted,
        "proof_route_failed_records": failures,
        "proof_route_valid_count": valid,
        "verifier_outcome": verifier_outcome,
    }


def _promotion_decision(
    audits: Sequence[ShadowClusterAudit],
    *,
    dry_run: bool,
    analysis_error: str,
    selected_cluster_count: int,
) -> tuple[bool, List[str]]:
    blockers: List[str] = []
    if analysis_error:
        blockers.append("analysis_schema_error")
    if selected_cluster_count == 0:
        blockers.append("no_clusters_selected")
    if dry_run:
        blockers.append("dry_run_no_promotion")
    provenance = _evidence_provenance_summary(audits)
    if int(provenance.get("real_record_count", 0)) <= 0:
        blockers.append("no_real_evidence_records")
    if int(provenance.get("provider_or_verified_cache_audit_count", 0)) <= 0:
        blockers.append("no_provider_or_verified_cache_evidence")
    if int(provenance.get("verifier_passed_audit_count", 0)) <= 0:
        blockers.append("no_verifier_evidence")
    for audit in audits:
        for code in GUARDRAIL_CODES:
            guardrail = _mapping(audit.guardrails.get(code))
            if not bool(guardrail.get("passed", False)):
                blockers.append(f"{code}_guardrail_not_satisfied")
        if audit.projected_todo.specificity_score < 1.0:
            blockers.append("projected_todo_specificity_incomplete")
    return not blockers, sorted(set(blockers))


def _estimated_cluster_impact(cluster: LegalIRGapCluster) -> Dict[str, float]:
    recurrence_norm = min(1.0, math.log1p(max(1, cluster.recurrence)) / math.log1p(MAX_CANARY_CLUSTERS))
    promotion_value = (
        0.45 * float(cluster.heldout_impact)
        + 0.35 * min(1.0, float(cluster.rank_score))
        + 0.20 * recurrence_norm
    )
    return {
        "heldout_impact": float(cluster.heldout_impact),
        "promotion_value": max(0.0, min(1.0, promotion_value)),
        "rank_score": float(cluster.rank_score),
        "recurrence_norm": recurrence_norm,
    }


def _impact_summary(audits: Sequence[ShadowClusterAudit]) -> Dict[str, float]:
    if not audits:
        return {
            "mean_promotion_value": 0.0,
            "top_promotion_value": 0.0,
            "total_projected_impact": 0.0,
        }
    values = [float(audit.estimated_compiler_impact.get("promotion_value", 0.0)) for audit in audits]
    return {
        "mean_promotion_value": sum(values) / len(values),
        "top_promotion_value": max(values),
        "total_projected_impact": sum(values),
    }


def _cache_summary(audits: Sequence[ShadowClusterAudit]) -> Dict[str, int]:
    return {
        "cache_hits": sum(1 for audit in audits if audit.cache_hit),
        "cache_misses": sum(1 for audit in audits if not audit.cache_hit),
        "llm_calls": sum(1 for audit in audits if audit.llm_called),
        "requests": len(audits),
    }


def _evidence_provenance_summary(audits: Sequence[ShadowClusterAudit]) -> Dict[str, Any]:
    kind_counts: Counter[str] = Counter()
    real_record_count = 0
    synthetic_record_count = 0
    cached_real_count = 0
    live_canonical_count = 0
    unknown_count = 0
    provider_or_verified_cache_count = 0
    verifier_passed_count = 0
    production_eligible_count = 0
    for audit in audits:
        provenance = _mapping(audit.evidence_provenance)
        for kind, count in _mapping(provenance.get("packet_kind_counts")).items():
            kind_counts[str(kind)] += int(_finite_float(count, 0.0))
        real_record_count += int(_finite_float(provenance.get("real_record_count"), 0.0))
        synthetic_record_count += int(_finite_float(provenance.get("synthetic_fixture_record_count"), 0.0))
        cached_real_count += int(_finite_float(provenance.get("cached_real_packet_count"), 0.0))
        live_canonical_count += int(_finite_float(provenance.get("live_canonical_state_packet_count"), 0.0))
        unknown_count += int(_finite_float(provenance.get("unknown_record_count"), 0.0))
        if bool(provenance.get("provider_or_verified_cache", False)):
            provider_or_verified_cache_count += 1
        verifier = _mapping(audit.guardrails.get("verifier"))
        if bool(verifier.get("passed", False)):
            verifier_passed_count += 1
        if bool(provenance.get("production_eligible", False)):
            production_eligible_count += 1
    return {
        "cached_real_packet_count": cached_real_count,
        "dry_run_reports_are_non_production": True,
        "live_canonical_state_packet_count": live_canonical_count,
        "packet_kind_counts": dict(sorted(kind_counts.items())),
        "production_eligible_audit_count": production_eligible_count,
        "provider_or_verified_cache_audit_count": provider_or_verified_cache_count,
        "real_record_count": real_record_count,
        "synthetic_fixture_record_count": synthetic_record_count,
        "unknown_record_count": unknown_count,
        "verifier_passed_audit_count": verifier_passed_count,
    }


def _audit_validity_summary(audits: Sequence[ShadowClusterAudit]) -> Dict[str, int]:
    return {
        "invalid": sum(1 for audit in audits if not audit.audit_valid),
        "valid": sum(1 for audit in audits if audit.audit_valid),
        "verified": sum(1 for audit in audits if audit.audit_verified),
    }


def _theorem_summary(audits: Sequence[ShadowClusterAudit]) -> Dict[str, int]:
    return {
        "local_checks": sum(int(audit.theorem_outcomes.get("local_check_count", 0)) for audit in audits),
        "proof_route_attempted": sum(int(audit.theorem_outcomes.get("proof_route_attempted_count", 0)) for audit in audits),
        "proof_route_failures": sum(int(audit.theorem_outcomes.get("proof_route_failed_records", 0)) for audit in audits),
        "proof_route_valid": sum(int(audit.theorem_outcomes.get("proof_route_valid_count", 0)) for audit in audits),
    }


def _specificity_summary(audits: Sequence[ShadowClusterAudit]) -> Dict[str, float]:
    if not audits:
        return {"mean": 0.0, "min": 0.0, "complete_count": 0.0}
    scores = [audit.projected_todo.specificity_score for audit in audits]
    return {
        "complete_count": float(sum(1 for score in scores if score >= 1.0)),
        "mean": sum(scores) / len(scores),
        "min": min(scores),
    }


def _validate_real_packets(
    records: Sequence[Mapping[str, Any]],
    *,
    config: RealShadowCanaryConfig,
    enforce_expected_state: bool = True,
) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    valid: List[Dict[str, Any]] = []
    invalid: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for index, record in enumerate(records):
        root = dict(_mapping(record.get("payload")) or record)
        failures = list(validate_disagreement_packet(root))
        evidence_id = str(root.get("evidence_id") or "")
        if not evidence_id:
            failures.append("missing_evidence_id")
        elif evidence_id in seen:
            failures.append("duplicate_evidence_id")
        seen.add(evidence_id)
        if _record_is_synthetic_fixture(root):
            failures.append("synthetic_fixture_not_allowed")
        context = _mapping(root.get("run_context"))
        evidence_hashes = _mapping(root.get("evidence_hashes"))
        state_hash = str(context.get("state_hash") or "")
        if state_hash and str(evidence_hashes.get("state_hash") or "") != state_hash:
            failures.append("state_hash_evidence_mismatch")
        if (
            enforce_expected_state
            and config.expected_state_hash
            and state_hash != config.expected_state_hash
        ):
            failures.append("expected_state_hash_mismatch")
        commit = str(context.get("compiler_commit") or "")
        if (
            enforce_expected_state
            and config.expected_compiler_commit
            and commit != config.expected_compiler_commit
        ):
            failures.append("expected_compiler_commit_mismatch")
        if failures:
            invalid.append(
                {
                    "evidence_id": evidence_id,
                    "failures": tuple(sorted(set(failures))),
                    "index": index,
                }
            )
        else:
            valid.append(root)
    return valid, invalid


def _select_real_canary_snapshot(
    records: Sequence[Mapping[str, Any]],
    *,
    config: RealShadowCanaryConfig,
) -> tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Select one coherent canonical state/commit snapshot from append-only logs."""

    groups: Dict[tuple[str, str], List[Dict[str, Any]]] = {}
    for record in records:
        root = dict(record)
        groups.setdefault(_real_snapshot_key(root), []).append(root)
    if not groups:
        return [], {
            "dropped_valid_packet_count": 0,
            "max_records_applied": 0,
            "candidate_snapshot_count": 0,
            "selected_group_packet_count": 0,
            "selected_packet_count": 0,
            "selection_reason": "no_valid_canonical_packets",
            "source_valid_packet_count": 0,
        }

    pool = groups
    expected_filters: Dict[str, str] = {}
    if config.expected_state_hash:
        expected_filters["state_hash"] = config.expected_state_hash
    if config.expected_compiler_commit:
        expected_filters["compiler_commit"] = config.expected_compiler_commit
    if expected_filters:
        expected_pool = {
            key: group
            for key, group in groups.items()
            if (not config.expected_state_hash or key[0] == config.expected_state_hash)
            and (
                not config.expected_compiler_commit
                or key[1] == config.expected_compiler_commit
            )
        }
        if expected_pool:
            pool = expected_pool

    minimum = config.bounded_min_real_packets()
    sufficient = {key: group for key, group in pool.items() if len(group) >= minimum}
    candidates = pool
    selected_key = max(candidates, key=lambda key: _real_snapshot_rank(candidates[key]))
    selected_group = list(candidates[selected_key])
    selected_group.sort(key=_real_record_rank)
    limit = max(0, int(config.max_records or 0))
    selected_records = selected_group[-limit:] if limit else selected_group
    reason_parts = []
    if expected_filters and pool is not groups:
        reason_parts.append("expected")
    reason_parts.append("newest")
    reason_parts.append("min_satisfying" if selected_key in sufficient else "available")
    reason_parts.append("snapshot")
    selection_reason = "_".join(reason_parts)
    top_candidates = [
        _real_snapshot_candidate_summary(key, group)
        for key, group in sorted(
            groups.items(),
            key=lambda item: _real_snapshot_rank(item[1]),
            reverse=True,
        )[:10]
    ]
    return selected_records, {
        "candidate_snapshot_count": len(groups),
        "dropped_valid_packet_count": max(0, len(records) - len(selected_records)),
        "expected_filters": expected_filters,
        "max_records_applied": limit,
        "selected_compiler_commit": selected_key[1],
        "selected_group_packet_count": len(selected_group),
        "selected_packet_count": len(selected_records),
        "selected_state_hash": selected_key[0],
        "selection_reason": selection_reason,
        "snapshot_candidates": top_candidates,
        "source_valid_packet_count": len(records),
    }


def _real_snapshot_key(record: Mapping[str, Any]) -> tuple[str, str]:
    context = _mapping(record.get("run_context"))
    evidence_hashes = _mapping(record.get("evidence_hashes"))
    return (
        str(context.get("state_hash") or evidence_hashes.get("state_hash") or ""),
        str(context.get("compiler_commit") or ""),
    )


def _real_snapshot_rank(records: Sequence[Mapping[str, Any]]) -> tuple[float, float, int]:
    if not records:
        return (0.0, 0.0, 0)
    ranks = [_real_record_rank(record) for record in records]
    return max(ranks)


def _real_record_rank(record: Mapping[str, Any]) -> tuple[float, float, int]:
    context = _mapping(record.get("run_context"))
    exported_at = _timestamp_rank(
        context.get("exported_at", record.get("exported_at"))
    )
    cycle = _finite_float(context.get("cycle"), 0.0)
    frozen_canary = _mapping(context.get("frozen_canary"))
    canary_index = int(_finite_float(frozen_canary.get("index"), 0.0))
    return (exported_at, cycle, canary_index)


def _real_snapshot_candidate_summary(
    key: tuple[str, str],
    records: Sequence[Mapping[str, Any]],
) -> Dict[str, Any]:
    cycles = sorted(
        {
            int(_finite_float(_mapping(record.get("run_context")).get("cycle"), 0.0))
            for record in records
        }
    )
    return {
        "compiler_commit": key[1],
        "cycle_max": max(cycles) if cycles else None,
        "cycle_min": min(cycles) if cycles else None,
        "packet_count": len(records),
        "state_hash": key[0],
    }


def _timestamp_rank(value: Any) -> float:
    number = _finite_float(value, float("nan"))
    if math.isfinite(number):
        return number
    if isinstance(value, str):
        text = value.strip()
        if text:
            try:
                if text.endswith("Z"):
                    text = text[:-1] + "+00:00"
                parsed = datetime.fromisoformat(text)
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=timezone.utc)
                return parsed.timestamp()
            except ValueError:
                return 0.0
    return 0.0


def _canonical_state_summary(
    records: Sequence[Mapping[str, Any]],
    *,
    config: RealShadowCanaryConfig,
) -> Dict[str, Any]:
    state_hashes = sorted(
        {
            str(_mapping(record.get("run_context")).get("state_hash") or "")
            for record in records
            if str(_mapping(record.get("run_context")).get("state_hash") or "")
        }
    )
    compiler_commits = sorted(
        {
            str(_mapping(record.get("run_context")).get("compiler_commit") or "")
            for record in records
            if str(_mapping(record.get("run_context")).get("compiler_commit") or "")
        }
    )
    cycles = [
        int(_finite_float(_mapping(record.get("run_context")).get("cycle"), 0.0))
        for record in records
    ]
    return {
        "compiler_commit": compiler_commits[0] if len(compiler_commits) == 1 else "",
        "compiler_commit_count": len(compiler_commits),
        "compiler_commits": compiler_commits,
        "cycle_max": max(cycles) if cycles else None,
        "cycle_min": min(cycles) if cycles else None,
        "expected_compiler_commit": config.expected_compiler_commit,
        "expected_compiler_commit_mismatch": bool(
            config.expected_compiler_commit
            and compiler_commits != [config.expected_compiler_commit]
        ),
        "expected_state_hash": config.expected_state_hash,
        "expected_state_hash_mismatch": bool(
            config.expected_state_hash and state_hashes != [config.expected_state_hash]
        ),
        "packet_count": len(records),
        "state_hash": state_hashes[0] if len(state_hashes) == 1 else "",
        "state_hash_count": len(state_hashes),
        "state_hashes": state_hashes,
    }


def _verify_real_shadow_audits(
    items: Sequence[LeanstralAuditWorkItem],
    *,
    results_by_key: Mapping[str, LeanstralAuditWorkResult],
    records: Sequence[Mapping[str, Any]],
    worker: LeanstralAuditWorker,
    config: RealShadowCanaryConfig,
    verifier_examples_by_sample_id: Mapping[str, Mapping[str, Any]],
) -> List[RealShadowAudit]:
    records_by_evidence_id = {
        str(record.get("evidence_id") or ""): record
        for record in records
        if str(record.get("evidence_id") or "")
    }
    audits: List[RealShadowAudit] = []
    verification_time = time.time()
    local_verifier = LeanstralAuditVerifier(config.verifier_config())
    for item in items:
        result = results_by_key.get(item.work_key)
        entry = worker.runner.cache.get_entry(item.request)
        verification = None
        if entry is not None and config.require_local_verifier:
            try:
                referenced_evidence_ids = _response_evidence_ids(entry.response)
                item_examples = [
                    verifier_examples_by_sample_id[sample_id]
                    for sample_id in _item_sample_ids(
                        item,
                        records_by_evidence_id,
                        evidence_ids=referenced_evidence_ids or item.evidence_ids,
                    )
                    if sample_id in verifier_examples_by_sample_id
                ]
                verification = local_verifier.verify(
                    item.request,
                    entry.response,
                    examples=item_examples,
                )
            except Exception as exc:  # pragma: no cover - defensive fail-closed path
                verification = {
                    "accepted": False,
                    "outcome": "rejected",
                    "reasons": (f"verifier_error:{exc.__class__.__name__}",),
                    "local_checks": (),
                }
        validation = entry.validation if entry is not None else {}
        result_validation = result.validation if result is not None else None
        audit_valid = bool(
            validation.get("accepted")
            or (result_validation is not None and result_validation.accepted)
        )
        audit_verified = bool(
            validation.get("verified")
            or (result_validation is not None and result_validation.verified)
        )
        verifier_outcome = str(_get_attr_or_key(verification, "outcome", "not-run") or "not-run")
        local_checks = _get_attr_or_key(verification, "local_checks", ()) or ()
        lean_details: Mapping[str, Any] = {}
        for local_check in local_checks:
            if str(_get_attr_or_key(local_check, "checker_name", "")) == "lean":
                lean_details = _mapping(_get_attr_or_key(local_check, "details", {}))
                break
        item_records = [
            records_by_evidence_id[evidence_id]
            for evidence_id in item.evidence_ids
            if evidence_id in records_by_evidence_id
        ]
        lag = _item_state_to_verified_lag(
            item_records,
            verification_time=verification_time,
            verified=bool(_get_attr_or_key(verification, "accepted", False)),
        )
        cluster = _mapping(item.cluster)
        audits.append(
            RealShadowAudit(
                work_key=item.work_key,
                request_id=item.request.request_id,
                cache_key=item.request.cache_key,
                status=result.status if result is not None else "not-run",
                compiler_commit=item.compiler_commit,
                state_hashes=tuple(item.state_hashes),
                semantic_family=str(cluster.get("semantic_family") or ""),
                compiler_surface=str(cluster.get("compiler_surface") or ""),
                semantic_signature=item.semantic_signature,
                evidence_ids=tuple(item.evidence_ids),
                source_record_hashes=tuple(item.source_record_hashes),
                cache_hit=bool(result.cache_hit if result is not None else entry is not None),
                llm_called=bool(result.llm_called if result is not None else False),
                generation_attempts=int(
                    result.generation_attempts if result is not None else 0
                ),
                repair_reasons=tuple(
                    result.repair_reasons if result is not None else ()
                ),
                audit_valid=audit_valid,
                audit_verified=audit_verified,
                response_hash=str(
                    validation.get("response_hash")
                    or (result.response_hash if result is not None else "")
                ),
                local_verifier_outcome=verifier_outcome,
                local_verifier_accepted=bool(
                    _get_attr_or_key(verification, "accepted", False)
                ),
                local_verifier_reasons=tuple(
                    str(reason)
                    for reason in (_get_attr_or_key(verification, "reasons", ()) or ())
                ),
                local_check_count=len(local_checks),
                lean_cache_hit_count=int(
                    _finite_float(lean_details.get("cache_hit_count"), 0.0)
                ),
                lean_cache_miss_count=int(
                    _finite_float(lean_details.get("cache_miss_count"), 0.0)
                ),
                lean_parallel_workers=int(
                    _finite_float(lean_details.get("parallel_workers"), 0.0)
                ),
                lean_slice_count=int(
                    _finite_float(lean_details.get("slice_count"), 0.0)
                ),
                lean_verified_formula_count=int(
                    _finite_float(lean_details.get("verified_formula_count"), 0.0)
                ),
                state_to_verified_audit_lag_seconds=lag,
            )
        )
    return audits


def _item_sample_ids(
    item: LeanstralAuditWorkItem,
    records_by_evidence_id: Mapping[str, Mapping[str, Any]],
    *,
    evidence_ids: Sequence[str],
) -> Sequence[str]:
    return tuple(
        dict.fromkeys(
            str(_mapping(records_by_evidence_id[evidence_id].get("sample_hashes")).get("sample_id") or "")
            for evidence_id in evidence_ids
            if evidence_id in records_by_evidence_id
            and str(
                _mapping(records_by_evidence_id[evidence_id].get("sample_hashes")).get("sample_id")
                or ""
            )
        )
    )


def _response_evidence_ids(response: Any) -> Sequence[str]:
    for payload in (
        getattr(response, "counterexample", None),
        getattr(response, "witness", None),
    ):
        if isinstance(payload, Mapping) and str(payload.get("evidence_id") or ""):
            return (str(payload["evidence_id"]),)
    return ()


def _load_hf_verifier_examples(
    records: Sequence[Mapping[str, Any]],
    *,
    config: RealShadowCanaryConfig,
) -> tuple[Dict[str, Dict[str, Any]], Dict[str, Any]]:
    """Resolve hash-checked verifier examples without exposing text to Leanstral."""

    import pyarrow.parquet as pq
    from huggingface_hub import HfFileSystem

    targets: Dict[int, List[Mapping[str, Any]]] = {}
    failures: List[str] = []
    requested_sample_ids: set[str] = set()
    for record in records:
        sample_id = str(_mapping(record.get("sample_hashes")).get("sample_id") or "")
        raw_index = _mapping(_mapping(record.get("run_context")).get("frozen_canary")).get(
            "index"
        )
        if not sample_id or raw_index is None:
            failures.append(f"missing_frozen_reference:{sample_id or 'unknown'}")
            continue
        try:
            row_index = int(raw_index)
        except (TypeError, ValueError):
            failures.append(f"invalid_frozen_index:{sample_id}")
            continue
        requested_sample_ids.add(sample_id)
        targets.setdefault(row_index, []).append(record)

    examples: Dict[str, Dict[str, Any]] = {}
    hf_path = f"datasets/{config.verifier_dataset_repo_id}/{config.verifier_laws_path}"
    columns = (
        "ipfs_cid",
        "title_number",
        "title_name",
        "section_number",
        "law_name",
        "source_url",
        "text",
        "citation_text",
        "normalized_citation",
    )
    remaining_indices = set(targets)
    with HfFileSystem().open(hf_path, "rb") as laws_file:
        parquet_file = pq.ParquetFile(laws_file)
        row_group_start = 0
        for row_group in range(parquet_file.num_row_groups):
            row_count = parquet_file.metadata.row_group(row_group).num_rows
            selected = sorted(
                index
                for index in remaining_indices
                if row_group_start <= index < row_group_start + row_count
            )
            if selected:
                table = parquet_file.read_row_group(row_group, columns=list(columns))
                for row_index in selected:
                    row = table.slice(row_index - row_group_start, 1).to_pylist()[0]
                    packets_by_sample_id = {
                        str(_mapping(packet.get("sample_hashes")).get("sample_id") or ""): packet
                        for packet in targets[row_index]
                    }
                    for packet in packets_by_sample_id.values():
                        reference, reference_failures = _verifier_reference_from_row(
                            packet,
                            row,
                        )
                        if reference is not None:
                            examples[str(reference["example_id"])] = reference
                        failures.extend(reference_failures)
                    remaining_indices.discard(row_index)
            row_group_start += row_count
            if not remaining_indices:
                break
    failures.extend(f"frozen_index_not_found:{index}" for index in sorted(remaining_indices))
    return examples, {
        "enabled": True,
        "failure_count": len(failures),
        "failures": failures[:32],
        "requested_sample_count": len(requested_sample_ids),
        "resolved_sample_count": len(examples),
        "source": hf_path,
    }


def _verifier_reference_from_row(
    packet: Mapping[str, Any],
    row: Mapping[str, Any],
) -> tuple[Optional[Dict[str, Any]], Sequence[str]]:
    sample_hashes = _mapping(packet.get("sample_hashes"))
    expected_sample_id = str(sample_hashes.get("sample_id") or "")
    record = USCodeParquetRecord.from_row(row)
    normalized_text = " ".join(record.text.split())
    digest = hashlib.sha256(
        f"{record.title_number}:{record.section_number}:{normalized_text}".encode("utf-8")
    ).hexdigest()[:16]
    resolved_sample_id = (
        f"us-code-{record.title_number}-{record.section_number}-{digest}"
    )
    failures: List[str] = []
    if resolved_sample_id != expected_sample_id:
        failures.append(f"sample_id_mismatch:{expected_sample_id}")
    if hashlib.sha256(record.text.encode("utf-8")).hexdigest() != str(
        sample_hashes.get("source_text_hash") or ""
    ):
        failures.append(f"source_text_hash_mismatch:{expected_sample_id}")
    if hashlib.sha256(normalized_text.encode("utf-8")).hexdigest() != str(
        sample_hashes.get("normalized_text_hash") or ""
    ):
        failures.append(f"normalized_text_hash_mismatch:{expected_sample_id}")
    if failures:
        return None, tuple(failures)
    return (
        {
            "citation": record.citation,
            "example_id": resolved_sample_id,
            "expected_modal_ir_hash": str(sample_hashes.get("modal_ir_hash") or ""),
            "section": record.section_number,
            "source_span_hashes": dict(_mapping(sample_hashes.get("source_span_hashes"))),
            "source_span_hash_format": "introspection_packet_v1",
            "source_text": record.text,
            "title": record.title_number,
        },
        (),
    )


def _packet_validity_summary(
    valid_records: Sequence[Mapping[str, Any]],
    invalid_records: Sequence[Mapping[str, Any]],
    *,
    min_packets: int,
) -> Dict[str, Any]:
    failure_counts: Counter[str] = Counter()
    for record in invalid_records:
        for failure in record.get("failures", ()) or ():
            failure_counts[str(failure)] += 1
    return {
        "invalid_packet_count": len(invalid_records),
        "invalid_reasons": dict(sorted(failure_counts.items())),
        "meets_minimum_real_packet_count": len(valid_records) >= min_packets,
        "min_required_real_packets": int(min_packets),
        "valid_real_packet_count": len(valid_records),
    }


def _real_coverage_summary(
    records: Sequence[Mapping[str, Any]],
    items: Sequence[LeanstralAuditWorkItem],
) -> Dict[str, Any]:
    family_counts: Counter[str] = Counter()
    surface_counts: Counter[str] = Counter()
    sample_roles: Counter[str] = Counter()
    evaluation_roles: Counter[str] = Counter()
    for record in records:
        canonical = _mapping(_mapping(record.get("legal_ir_views")).get("canonical"))
        for family, value in _mapping(canonical.get("family_distribution")).items():
            if _finite_float(value, 0.0) > 0.0:
                family_counts[str(family)] += 1
        for component in _mapping(record.get("legal_ir_component_gaps")).keys():
            surface = ".".join(str(component).split(".")[:2]) or str(component)
            surface_counts[surface] += 1
        context = _mapping(record.get("run_context"))
        sample_roles[str(context.get("sample_role") or "unknown")] += 1
        evaluation_roles[str(context.get("evaluation_role") or "unknown")] += 1
    item_families: Counter[str] = Counter()
    item_surfaces: Counter[str] = Counter()
    for item in items:
        cluster = _mapping(item.cluster)
        item_families[str(cluster.get("semantic_family") or "unknown")] += 1
        item_surfaces[str(cluster.get("compiler_surface") or "unknown")] += 1
    return {
        "audit_item_count": len(items),
        "audit_item_family_counts": dict(sorted(item_families.items())),
        "audit_item_surface_counts": dict(sorted(item_surfaces.items())),
        "evaluation_role_counts": dict(sorted(evaluation_roles.items())),
        "family_counts": dict(sorted(family_counts.items())),
        "family_count": len(family_counts),
        "sample_role_counts": dict(sorted(sample_roles.items())),
        "surface_count": len(surface_counts),
        "surface_counts": dict(sorted(surface_counts.items())),
    }


def _real_cache_summary(
    audits: Sequence[RealShadowAudit],
    worker_summary: Mapping[str, Any],
) -> Dict[str, int]:
    return {
        "cache_hits": sum(1 for audit in audits if audit.cache_hit),
        "cache_misses": max(0, len(audits) - sum(1 for audit in audits if audit.cache_hit)),
        "checkpoint_skips": int(_finite_float(worker_summary.get("skipped_checkpoint_count"), 0.0)),
        "failed": int(_finite_float(worker_summary.get("failed_count"), 0.0)),
        "generation_attempts": sum(audit.generation_attempts for audit in audits),
        "llm_calls": sum(1 for audit in audits if audit.llm_called),
        "provider_disabled_or_missed": sum(
            1 for audit in audits if audit.status == "provider_disabled"
        ),
        "repair_attempts": sum(
            max(0, int(audit.generation_attempts) - 1) for audit in audits
        ),
        "repaired_audits": sum(1 for audit in audits if audit.repair_reasons),
        "requests": len(audits),
        "timeouts": sum(1 for audit in audits if audit.status == "timeout"),
        "unavailable": int(_finite_float(worker_summary.get("unavailable_count"), 0.0)),
    }


def _real_audit_validity_summary(audits: Sequence[RealShadowAudit]) -> Dict[str, int]:
    return {
        "invalid": sum(1 for audit in audits if not audit.audit_valid),
        "valid": sum(1 for audit in audits if audit.audit_valid),
        "verified": sum(1 for audit in audits if audit.audit_verified),
    }


def _real_verifier_summary(audits: Sequence[RealShadowAudit]) -> Dict[str, Any]:
    outcomes = Counter(audit.local_verifier_outcome for audit in audits)
    reasons: Counter[str] = Counter()
    for audit in audits:
        for reason in audit.local_verifier_reasons:
            reasons[str(reason)] += 1
    return {
        "accepted": sum(1 for audit in audits if audit.local_verifier_accepted),
        "local_check_count": sum(audit.local_check_count for audit in audits),
        "lean_cache_hit_count": sum(audit.lean_cache_hit_count for audit in audits),
        "lean_cache_miss_count": sum(audit.lean_cache_miss_count for audit in audits),
        "lean_max_parallel_workers": max(
            (audit.lean_parallel_workers for audit in audits), default=0
        ),
        "lean_slice_count": sum(audit.lean_slice_count for audit in audits),
        "lean_verified_formula_count": sum(
            audit.lean_verified_formula_count for audit in audits
        ),
        "outcomes": dict(sorted(outcomes.items())),
        "reasons": dict(sorted(reasons.items())),
        "rejected_or_unsupported": sum(
            1 for audit in audits if not audit.local_verifier_accepted
        ),
    }


def _item_state_to_verified_lag(
    records: Sequence[Mapping[str, Any]],
    *,
    verification_time: float,
    verified: bool,
) -> Optional[float]:
    if not verified:
        return None
    timestamps = [
        timestamp
        for timestamp in (_packet_state_timestamp(record) for record in records)
        if timestamp is not None
    ]
    if not timestamps:
        return None
    return max(0.0, float(verification_time) - max(timestamps))


def _packet_state_timestamp(record: Mapping[str, Any]) -> Optional[float]:
    root = _mapping(record.get("payload")) or dict(record)
    context = _mapping(root.get("run_context"))
    for key in (
        "state_exported_at",
        "exported_at",
        "created_at",
        "timestamp",
        "state_timestamp",
    ):
        parsed = _parse_timestamp(context.get(key))
        if parsed is not None:
            return parsed
        parsed = _parse_timestamp(root.get(key))
        if parsed is not None:
            return parsed
    return None


def _parse_timestamp(value: Any) -> Optional[float]:
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        return number if math.isfinite(number) and number > 0.0 else None
    text = str(value).strip()
    if not text:
        return None
    try:
        number = float(text)
    except ValueError:
        normalized = text[:-1] + "+00:00" if text.endswith("Z") else text
        try:
            parsed = datetime.fromisoformat(normalized)
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.timestamp()
    return number if math.isfinite(number) and number > 0.0 else None


def _lag_summary(values: Sequence[Optional[float]]) -> Dict[str, Any]:
    observed = [float(value) for value in values if value is not None]
    missing = len(values) - len(observed)
    if not observed:
        return {
            "count": 0,
            "max": None,
            "mean": None,
            "min": None,
            "missing_count": missing,
        }
    return {
        "count": len(observed),
        "max": max(observed),
        "mean": sum(observed) / len(observed),
        "min": min(observed),
        "missing_count": missing,
    }


def _packet_index(records: Sequence[Mapping[str, Any]]) -> Dict[str, Mapping[str, Any]]:
    index: Dict[str, Mapping[str, Any]] = {}
    for record in records:
        evidence_id = str(record.get("evidence_id") or _mapping(record.get("payload")).get("evidence_id") or "")
        if evidence_id:
            index[evidence_id] = record
    return index


def _records_from_file(path: Path) -> List[Dict[str, Any]]:
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".jsonl":
        return [
            dict(value)
            for value in (json.loads(line) for line in text.splitlines() if line.strip())
            if isinstance(value, Mapping)
        ]
    data = json.loads(text)
    if isinstance(data, list):
        return [dict(item) for item in data if isinstance(item, Mapping)]
    if isinstance(data, Mapping):
        for key in ("packets", "records", "disagreements", "items"):
            value = data.get(key)
            if isinstance(value, list):
                return [dict(item) for item in value if isinstance(item, Mapping)]
        return [dict(data)]
    return []


def _compact_packet(record: Mapping[str, Any]) -> Dict[str, Any]:
    root = _mapping(record.get("payload")) or dict(record)
    return {
        "anti_copy_evidence": _mapping(root.get("anti_copy_evidence") or root.get("anti_copy")),
        "evidence_id": str(root.get("evidence_id") or ""),
        "evidence_provenance": _record_declared_provenance(root),
        "legal_ir_views": _mapping(root.get("legal_ir_views")),
        "sample_hashes": _mapping(root.get("sample_hashes")),
        "schema_version": str(root.get("schema_version") or ""),
        "versions": _mapping(root.get("versions")),
    }


def _audit_evidence_provenance(
    records: Sequence[Mapping[str, Any]],
    *,
    audit_result: LeanstralAuditResult,
) -> Dict[str, Any]:
    packet_kinds = [
        _record_provenance_kind(
            record,
            cache_hit=bool(audit_result.cache_hit),
            llm_called=bool(audit_result.llm_called),
        )
        for record in records
    ]
    counts = Counter(packet_kinds)
    real_count = sum(count for kind, count in counts.items() if kind != SYNTHETIC_FIXTURE_PACKET)
    provider_or_verified_cache = bool(
        audit_result.llm_called
        or (
            audit_result.cache_hit
            and audit_result.validation.accepted
            and audit_result.validation.verified
        )
    )
    dominant_kind = packet_kinds[0] if packet_kinds else UNKNOWN_PACKET_PROVENANCE
    if packet_kinds:
        dominant_kind = sorted(counts.items(), key=lambda item: (-item[1], item[0]))[0][0]
    return {
        "cached_real_packet_count": counts.get(CACHED_REAL_PACKET, 0),
        "dominant_kind": dominant_kind,
        "live_canonical_state_packet_count": counts.get(LIVE_CANONICAL_STATE_PACKET, 0),
        "packet_kind_counts": dict(sorted(counts.items())),
        "production_eligible": bool(
            real_count > 0
            and provider_or_verified_cache
            and all(kind in PRODUCTION_PACKET_KINDS for kind in packet_kinds)
        ),
        "provider_or_verified_cache": provider_or_verified_cache,
        "real_record_count": real_count,
        "record_count": len(records),
        "synthetic_fixture_record_count": counts.get(SYNTHETIC_FIXTURE_PACKET, 0),
        "unknown_record_count": counts.get(UNKNOWN_PACKET_PROVENANCE, 0)
        + counts.get(REAL_PACKET_WITHOUT_PROMOTION_EVIDENCE, 0),
        "verified_cache_used": bool(
            audit_result.cache_hit
            and audit_result.validation.accepted
            and audit_result.validation.verified
        ),
        "live_provider_used": bool(audit_result.llm_called),
    }


def _records_evidence_provenance(records: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    counts = Counter(_record_provenance_kind(record) for record in records)
    return {
        "packet_kind_counts": dict(sorted(counts.items())),
        "record_count": len(records),
        "synthetic_fixture_record_count": counts.get(SYNTHETIC_FIXTURE_PACKET, 0),
    }


def _record_provenance_kind(
    record: Mapping[str, Any],
    *,
    cache_hit: bool = False,
    llm_called: bool = False,
) -> str:
    root = _mapping(record.get("payload")) or dict(record)
    declared = str(_record_declared_provenance(root).get("kind") or "").strip()
    if declared:
        if declared == SYNTHETIC_FIXTURE_PACKET:
            return SYNTHETIC_FIXTURE_PACKET
        if declared in PRODUCTION_PACKET_KINDS:
            return declared
    if _record_is_synthetic_fixture(root):
        return SYNTHETIC_FIXTURE_PACKET
    if llm_called:
        return LIVE_CANONICAL_STATE_PACKET
    if cache_hit:
        return CACHED_REAL_PACKET
    if _record_has_live_canonical_state(root):
        return LIVE_CANONICAL_STATE_PACKET
    if _record_has_canonical_hash_evidence(root):
        return REAL_PACKET_WITHOUT_PROMOTION_EVIDENCE
    return UNKNOWN_PACKET_PROVENANCE


def _record_declared_provenance(record: Mapping[str, Any]) -> Dict[str, Any]:
    provenance = _mapping(record.get("evidence_provenance") or record.get("packet_provenance"))
    if provenance:
        return provenance
    versions = _mapping(record.get("versions"))
    kind = str(versions.get("evidence_provenance_kind") or "").strip()
    return {"kind": kind} if kind else {}


def _record_is_synthetic_fixture(record: Mapping[str, Any]) -> bool:
    provenance = _record_declared_provenance(record)
    if str(provenance.get("kind") or "") == SYNTHETIC_FIXTURE_PACKET:
        return True
    versions = _mapping(record.get("versions"))
    evidence_id = str(record.get("evidence_id") or "")
    hashes = _mapping(record.get("sample_hashes"))
    sample_id = str(hashes.get("sample_id") or record.get("sample_id") or "")
    return (
        str(versions.get("canary_manifest_version") or "") == "dry-run-fixture-v1"
        or evidence_id.startswith("dry-run-")
        or sample_id.startswith("dry-run-")
    )


def _record_has_live_canonical_state(record: Mapping[str, Any]) -> bool:
    versions = _mapping(record.get("versions"))
    return bool(
        str(versions.get("state_version") or "").strip()
        and _record_has_canonical_hash_evidence(record)
    )


def _record_has_canonical_hash_evidence(record: Mapping[str, Any]) -> bool:
    hashes = _mapping(record.get("sample_hashes"))
    views = _mapping(record.get("legal_ir_views"))
    canonical = _mapping(views.get("canonical"))
    span_hashes = _mapping(hashes.get("source_span_hashes") or record.get("source_span_hashes"))
    modal_hash = str(hashes.get("modal_ir_hash") or canonical.get("modal_ir_hash") or "")
    return bool(str(record.get("evidence_id") or "").strip() and modal_hash and span_hashes)


def _proof_obligation_ids(cluster: LegalIRGapCluster) -> tuple[str, ...]:
    material = canonical_sha256(
        {
            "cluster_id": cluster.cluster_id or cluster.expected_cluster_id(),
            "signature": cluster.semantic_signature,
            "surface": cluster.compiler_surface,
        }
    )[:10]
    family = cluster.semantic_family.replace("_", "-")
    return (f"PO-shadow-{family}-{material}",)


def _disagreement_categories(cluster: LegalIRGapCluster) -> tuple[str, ...]:
    categories = {cluster.semantic_family, cluster.compiler_surface}
    for gap in cluster.gaps:
        if gap.gap_kind:
            categories.add(gap.gap_kind)
        if gap.metric_name:
            categories.add(gap.metric_name)
    return tuple(sorted(categories))


def _schema_record_valid(record: Mapping[str, Any]) -> bool:
    schema_version = str(record.get("schema_version") or _mapping(record.get("payload")).get("schema_version") or "")
    return not schema_version or schema_version == "legal-ir-introspection-packet-v1"


def _guardrail_status(guardrails: Mapping[str, Any]) -> str:
    if bool(guardrails.get("passed", False)):
        return "passed"
    failed = [
        key
        for key in GUARDRAIL_CODES
        if not bool(_mapping(guardrails.get(key)).get("passed", False))
    ]
    return "failed:" + ",".join(failed)


def _markdown_kv(values: Mapping[str, Any]) -> str:
    if not values:
        return "- none"
    return "\n".join(
        f"- `{key}`: {json.dumps(_json_ready(value), ensure_ascii=True, sort_keys=True)}"
        for key, value in sorted(values.items())
    )


def _mapping(value: Any) -> Dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _finite_float(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _get_attr_or_key(value: Any, key: str, default: Any = None) -> Any:
    if isinstance(value, Mapping):
        return value.get(key, default)
    return getattr(value, key, default)


def _json_ready(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_ready(item) for item in value]
    if hasattr(value, "value"):
        return str(value.value)
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
    parser.add_argument("--max-clusters", type=int, default=MAX_CANARY_CLUSTERS)
    parser.add_argument("--max-records", type=int, default=0)
    parser.add_argument("--min-real-packets", type=int, default=MIN_REAL_CANARY_PACKETS)
    parser.add_argument("--max-evidence-packets-per-item", type=int, default=1)
    parser.add_argument(
        "--evidence-refresh-policy",
        choices=LEANSTRAL_EVIDENCE_REFRESH_POLICIES,
        default="latest_compiler_snapshot",
        help=(
            "Use latest_compiler_snapshot to match the production Leanstral "
            "audit watcher, or full_manifest for strict append-only attestation."
        ),
    )
    parser.add_argument("--cache-dir", default="", help="Leanstral audit cache directory")
    parser.add_argument("--checkpoint-path", default="", help="Optional Leanstral worker checkpoint path")
    parser.add_argument("--report-path", default="")
    parser.add_argument("--dry-run", action="store_true", help="Do not call Leanstral; use cache-only shadow audit")
    parser.add_argument("--run-provider", action="store_true", help="Call Leanstral for cache misses")
    parser.add_argument("--provider", default="mistral_vibe")
    parser.add_argument(
        "--provider-fallbacks",
        default="",
        help="Comma- or colon-separated fallback providers explicitly enabled for this canary run.",
    )
    parser.add_argument("--model", default="Leanstral")
    parser.add_argument("--vibe-agent", default="lean")
    parser.add_argument("--expected-state-hash", default="")
    parser.add_argument("--expected-compiler-commit", default="")
    parser.add_argument("--max-concurrency", type=int, default=2)
    parser.add_argument("--max-retries", type=int, default=0)
    parser.add_argument("--validation-repair-retries", type=int, default=1)
    parser.add_argument("--timeout-seconds", type=float, default=300.0)
    parser.add_argument("--retry-backoff-seconds", type=float, default=0.25)
    parser.add_argument(
        "--legacy-cluster-canary",
        action="store_true",
        help="Run the legacy synthetic/disagreement-cluster report instead of the real canary.",
    )
    parser.add_argument("--skip-syntax-check", action="store_true")
    parser.add_argument("--skip-graph-check", action="store_true")
    parser.add_argument("--skip-provenance-check", action="store_true")
    parser.add_argument("--run-lean", action="store_true")
    parser.add_argument(
        "--lean-max-formulas",
        type=int,
        default=DEFAULT_LEAN_MAX_FORMULAS,
    )
    parser.add_argument(
        "--lean-parallel-workers",
        type=int,
        default=DEFAULT_LEAN_PARALLEL_WORKERS,
    )
    parser.add_argument("--lean-proof-cache-max-entries", type=int, default=4096)
    parser.add_argument(
        "--lean-proof-cache-path",
        default=str(DEFAULT_LEAN_PROOF_CACHE_PATH),
    )
    parser.add_argument("--lean-proof-cache-ttl-seconds", type=int, default=2_592_000)
    parser.add_argument(
        "--lean-slice-size",
        type=int,
        default=DEFAULT_LEAN_SLICE_SIZE,
    )
    parser.add_argument(
        "--lean-timeout-seconds",
        type=float,
        default=DEFAULT_LEAN_TIMEOUT_SECONDS,
    )
    parser.add_argument("--run-modal-bridge", action="store_true")
    parser.add_argument("--require-modal-bridge-proof", action="store_true")
    parser.add_argument(
        "--resolve-verifier-examples",
        action="store_true",
        help="Resolve frozen canary source rows from Hugging Face for local verification only.",
    )
    parser.add_argument("--verifier-dataset-repo-id", default=HF_USCODE_DATASET_ID)
    parser.add_argument("--verifier-laws-path", default=USCODE_LAWS_PARQUET)
    parser.add_argument("--require-promotion", action="store_true", help="Exit non-zero when promotion is blocked")
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    explicit_input_requested = bool(args.input)
    legacy_mode = bool(
        args.legacy_cluster_canary
        or (not explicit_input_requested and not args.run_provider)
    )
    input_paths = resolve_disagreement_input_paths(
        args.input,
        min_records=1 if legacy_mode else args.min_real_packets,
    )
    if legacy_mode:
        report_path_arg = args.report_path or str(LEGACY_REPORT_PATH)
        dry_run = True if args.dry_run or not args.run_provider else False
        records = load_disagreement_records(input_paths) if input_paths else []
        if not records and dry_run and not explicit_input_requested:
            records = build_dry_run_fixture_records(
                count=max(1, min(args.max_clusters, MAX_CANARY_CLUSTERS))
            )
        config = ShadowCanaryConfig(
            max_clusters=args.max_clusters,
            dry_run=dry_run,
            cache_dir=args.cache_dir,
            report_path=report_path_arg,
            provider=args.provider,
            model=args.model,
            vibe_agent=args.vibe_agent,
            timeout_seconds=args.timeout_seconds,
            validation_repair_retries=args.validation_repair_retries,
        )
        result = run_shadow_canary(records, config=config)
        report_path = write_markdown_report(result, report_path_arg)
        print(
            json.dumps(
                {
                    "cache_summary": result.cache_summary,
                    "promotion_allowed": result.promotion_allowed,
                    "promotion_blockers": result.promotion_blockers,
                    "report_path": str(report_path),
                    "runtime_seconds": round(result.runtime_seconds, 6),
                    "selected_cluster_count": result.selected_cluster_count,
                },
                ensure_ascii=True,
                sort_keys=True,
            )
        )
        if args.require_promotion and not result.promotion_allowed:
            return 2
        return 0

    records = load_disagreement_records(input_paths) if input_paths else []
    if not records:
        raise SystemExit("--input is required for the real shadow canary")
    report_path_arg = args.report_path or str(DEFAULT_REPORT_PATH)
    config = RealShadowCanaryConfig(
        cache_dir=args.cache_dir,
        checkpoint_path=args.checkpoint_path,
        evidence_refresh_policy=args.evidence_refresh_policy,
        expected_compiler_commit=args.expected_compiler_commit,
        expected_state_hash=args.expected_state_hash,
        max_concurrency=args.max_concurrency,
        max_clusters=args.max_clusters,
        max_evidence_packets_per_item=args.max_evidence_packets_per_item,
        max_records=args.max_records,
        max_retries=args.max_retries,
        min_real_packets=args.min_real_packets,
        lean_max_formulas=args.lean_max_formulas,
        lean_parallel_workers=args.lean_parallel_workers,
        lean_proof_cache_max_entries=args.lean_proof_cache_max_entries,
        lean_proof_cache_path=args.lean_proof_cache_path,
        lean_proof_cache_ttl_seconds=args.lean_proof_cache_ttl_seconds,
        lean_slice_size=args.lean_slice_size,
        lean_timeout_seconds=args.lean_timeout_seconds,
        modal_bridge_require_proof=bool(args.require_modal_bridge_proof),
        model=args.model,
        provider=args.provider,
        provider_enabled=bool(args.run_provider and not args.dry_run),
        provider_fallbacks=args.provider_fallbacks,
        report_path=report_path_arg,
        retry_backoff_seconds=args.retry_backoff_seconds,
        run_graph_check=not args.skip_graph_check,
        run_lean=bool(args.run_lean),
        run_modal_bridge=bool(args.run_modal_bridge),
        run_provenance_check=not args.skip_provenance_check,
        run_syntax_check=not args.skip_syntax_check,
        resolve_verifier_examples=bool(args.resolve_verifier_examples),
        timeout_seconds=args.timeout_seconds,
        validation_repair_retries=args.validation_repair_retries,
        verifier_dataset_repo_id=args.verifier_dataset_repo_id,
        verifier_laws_path=args.verifier_laws_path,
        vibe_agent=args.vibe_agent,
    )
    result = run_real_shadow_canary(records, config=config)
    report_path = write_markdown_report(result, report_path_arg)
    print(
        json.dumps(
            {
                "audit_validity": result.audit_validity,
                "blocked_reasons": result.blocked_reasons,
                "cache_summary": result.cache_summary,
                "canonical_state": result.canonical_state,
                "report_path": str(report_path),
                "runtime_seconds": round(result.runtime_seconds, 6),
                "status": result.status,
                "valid_real_packet_count": result.valid_real_packet_count,
            },
            ensure_ascii=True,
            sort_keys=True,
        )
    )
    if args.require_promotion and result.status != "passed":
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
