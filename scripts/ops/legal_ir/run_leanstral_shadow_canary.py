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
import json
import math
import time
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

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
    LeanstralAuditValidation,
    LeanstralVerifierConfig,
    LegalIRGapCluster,
    analyze_introspection_disagreements,
    verify_leanstral_audit,
)
from ipfs_datasets_py.logic.modal.leanstral_audit import canonical_sha256


SHADOW_CANARY_SCHEMA_VERSION = "legal-ir-leanstral-shadow-canary-v1"
DEFAULT_REPORT_PATH = Path("docs/implementation/reports/leanstral_shadow_canary.md")
MAX_CANARY_CLUSTERS = 50
GUARDRAIL_CODES = (
    "provenance",
    "anti_copy",
    "schema",
    "verifier",
)
EVIDENCE_PROVENANCE_KINDS = (
    "synthetic_fixture",
    "cached_real_packet",
    "live_canonical_state_packet",
    "unknown",
)
PRODUCTION_RECORD_KINDS = frozenset(
    {
        "cached_real_packet",
        "live_canonical_state_packet",
    }
)


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
    audit_validity: Mapping[str, int]
    theorem_outcomes: Mapping[str, int]
    disagreement_categories: Mapping[str, int]
    projected_todo_specificity: Mapping[str, float]
    runtime_seconds: float
    estimated_compiler_impact: Mapping[str, float]
    no_mutation: Mapping[str, Any]
    evidence_provenance: Mapping[str, Any]
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
            "evidence_provenance": _json_ready(self.evidence_provenance),
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
    evidence_provenance = _shadow_evidence_provenance_summary(
        records,
        audits=audits,
        dry_run=cfg.dry_run,
    )
    promotion_allowed, blockers = _promotion_decision(
        audits,
        dry_run=cfg.dry_run,
        analysis_error=analysis_error,
        selected_cluster_count=len(selected_clusters),
        evidence_provenance=evidence_provenance,
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
            "production_eligible": False,
            "non_production_reason": "dry_run" if cfg.dry_run else "",
        },
        evidence_provenance=evidence_provenance,
        analysis_error=analysis_error,
    )


def write_markdown_report(result: ShadowCanaryResult, path: str | Path) -> Path:
    """Write a human-readable canary report."""

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(render_markdown_report(result), encoding="utf-8")
    return target


def render_markdown_report(result: ShadowCanaryResult) -> str:
    """Render a compact Markdown report with the required acceptance sections."""

    payload = result.to_dict()
    lines = [
        "# Leanstral Shadow Canary",
        "",
        f"- Schema: `{result.schema_version}`",
        f"- Mode: `{'dry-run' if result.config.dry_run else 'shadow'}`",
        f"- Production evidence eligible: `{str(bool(result.evidence_provenance.get('production_eligible', False))).lower()}`",
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
            "## Evidence Provenance",
            _markdown_kv(result.evidence_provenance),
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
                f"- Evidence provenance: `{audit.evidence_provenance.get('dominant_record_kind', 'unknown')}`; production eligible records `{audit.evidence_provenance.get('real_record_count', 0)}`",
                f"- Audit valid: `{str(audit.audit_valid).lower()}`; verified: `{str(audit.audit_verified).lower()}`",
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
                verified_by=("leanstral-audit-schema-v1", "leanstral-audit-cache-v1"),
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
        "legal_ir_views": _mapping(root.get("legal_ir_views")),
        "sample_hashes": _mapping(root.get("sample_hashes")),
        "schema_version": str(root.get("schema_version") or ""),
        "versions": _mapping(root.get("versions")),
    }


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
    parser.add_argument("--input", action="append", default=[], help="JSON/JSONL packet file or directory")
    parser.add_argument("--max-clusters", type=int, default=MAX_CANARY_CLUSTERS)
    parser.add_argument("--cache-dir", default="", help="Leanstral audit cache directory")
    parser.add_argument("--report-path", default=str(DEFAULT_REPORT_PATH))
    parser.add_argument("--dry-run", action="store_true", help="Do not call Leanstral; use cache-only shadow audit")
    parser.add_argument("--run-provider", action="store_true", help="Call Leanstral for cache misses")
    parser.add_argument("--require-promotion", action="store_true", help="Exit non-zero when promotion is blocked")
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    dry_run = True if args.dry_run or not args.run_provider else False
    records = load_disagreement_records(args.input) if args.input else []
    if not records and dry_run:
        records = build_dry_run_fixture_records(
            count=max(1, min(args.max_clusters, MAX_CANARY_CLUSTERS))
        )
    config = ShadowCanaryConfig(
        max_clusters=args.max_clusters,
        dry_run=dry_run,
        cache_dir=args.cache_dir,
        report_path=args.report_path,
    )
    result = run_shadow_canary(records, config=config)
    report_path = write_markdown_report(result, args.report_path)
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


if __name__ == "__main__":
    raise SystemExit(main())
