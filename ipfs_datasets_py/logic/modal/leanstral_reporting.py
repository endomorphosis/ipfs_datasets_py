"""Aggregate verified Leanstral audits into bounded rule-gap reports.

The verifier says whether one Leanstral audit is admissible evidence.  This
module performs the next deterministic step: collapse repeated admissible
audits into one compiler/decompiler rule gap, retain conflicts, and bind each
gap to exactly one owned implementation surface with a focused validation set.
Free-form architecture recommendations are reported as rejected inputs rather
than converted into synthesis work.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

from .leanstral_audit import (
    ISSUE_AUDIT_CLASSIFICATIONS,
    LeanstralAuditResponse,
    canonical_sha256,
)
from .leanstral_verifier import (
    LeanstralAuditVerificationResult,
    LeanstralHammerVerificationReport,
    LeanstralVerificationOutcome,
)


LEANSTRAL_RULE_GAP_REPORT_SCHEMA_VERSION = "legal-ir-leanstral-rule-gap-report-v1"
LEANSTRAL_PATCH_FEEDBACK_REPORT_SCHEMA_VERSION = (
    "legal-ir-leanstral-patch-feedback-report-v1"
)
LEANSTRAL_PATCH_OUTCOME_ACCEPTED_IMPROVEMENT = "accepted_improvement"
LEANSTRAL_PATCH_OUTCOME_QUALITY_REGRESSION = "quality_regression"
LEANSTRAL_PATCH_OUTCOME_UNSUPPORTED_HYPOTHESIS = "unsupported_hypothesis"
LEANSTRAL_PATCH_OUTCOME_OPERATIONAL_FAILURE = "operational_failure"
LEANSTRAL_PATCH_OUTCOME_STALE_EVIDENCE = "stale_evidence"
LEANSTRAL_PATCH_OUTCOME_STATUSES = {
    LEANSTRAL_PATCH_OUTCOME_ACCEPTED_IMPROVEMENT,
    LEANSTRAL_PATCH_OUTCOME_QUALITY_REGRESSION,
    LEANSTRAL_PATCH_OUTCOME_UNSUPPORTED_HYPOTHESIS,
    LEANSTRAL_PATCH_OUTCOME_OPERATIONAL_FAILURE,
    LEANSTRAL_PATCH_OUTCOME_STALE_EVIDENCE,
}

_FREE_FORM_SURFACE_PATTERN = re.compile(
    r"\b(?:architecture|architectural|brainstorm|design doc|epic|platform|"
    r"project|roadmap|system-wide|strategy|technical debt|rewrite)\b",
    re.IGNORECASE,
)
_TOKEN_PATTERN = re.compile(r"[^a-z0-9]+")


@dataclass(frozen=True)
class LeanstralOwnedSurface:
    """One owned compiler/decompiler surface that may receive rule-gap work."""

    component: str
    action: str
    allowed_paths: Sequence[str]
    target_metrics: Sequence[str]
    theorem_templates: Sequence[str]
    mutation_cases: Sequence[str]
    target_file_lane: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "action": self.action,
            "allowed_paths": list(self.allowed_paths),
            "component": self.component,
            "mutation_cases": list(self.mutation_cases),
            "target_file_lane": self.target_file_lane,
            "target_metrics": list(self.target_metrics),
            "theorem_templates": list(self.theorem_templates),
        }


OWNED_LEANSTRAL_RULE_GAP_SURFACES: Dict[str, LeanstralOwnedSurface] = {
    "modal.compiler": LeanstralOwnedSurface(
        component="modal.compiler",
        action="add_deterministic_parser_rule",
        allowed_paths=("ipfs_datasets_py/logic/modal/compiler.py",),
        target_metrics=("compiler_ir_parse_coverage", "modal_ir_formula_recall"),
        theorem_templates=("modal_operator_preserved", "source_provenance_preserved"),
        mutation_cases=("remove_modal_cue", "alter_scope"),
        target_file_lane="compiler_parser",
    ),
    "modal.compiler.registry": LeanstralOwnedSurface(
        component="modal.compiler.registry",
        action="refine_modal_family_cue_rules",
        allowed_paths=("ipfs_datasets_py/logic/modal/codec.py",),
        target_metrics=("cross_entropy_loss", "legal_ir_view_cross_entropy_loss"),
        theorem_templates=("modal_operator_preserved", "source_provenance_preserved"),
        mutation_cases=("invert_modality", "remove_modal_cue"),
        target_file_lane="compiler_registry",
    ),
    "modal.compiler.ambiguity": LeanstralOwnedSurface(
        component="modal.compiler.ambiguity",
        action="add_or_review_modal_ambiguity_policy",
        allowed_paths=("ipfs_datasets_py/logic/modal/compiler.py",),
        target_metrics=("compiler_ir_ambiguity_precision", "modal_family_margin"),
        theorem_templates=("modal_operator_preserved", "source_provenance_preserved"),
        mutation_cases=("ambiguous_modal_cue", "conflicting_exception_scope"),
        target_file_lane="compiler_ambiguity",
    ),
    "modal.ir_decompiler": LeanstralOwnedSurface(
        component="modal.ir_decompiler",
        action="refine_semantic_decompiler_reconstruction",
        allowed_paths=(
            "ipfs_datasets_py/logic/modal/codec.py",
            "ipfs_datasets_py/logic/modal/decompiler.py",
        ),
        target_metrics=(
            "reconstruction_loss",
            "source_decompiled_text_embedding_cosine_loss",
            "source_decompiled_text_token_loss",
        ),
        theorem_templates=("decompiler_round_trip", "exception_scope_preserved"),
        mutation_cases=("invert_modality", "remove_exception", "alter_deadline"),
        target_file_lane="ir_decompiler",
    ),
    "bridge.contracts": LeanstralOwnedSurface(
        component="bridge.contracts",
        action="repair_multiview_legal_ir_loss",
        allowed_paths=(
            "ipfs_datasets_py/logic/modal/codec.py",
            "ipfs_datasets_py/optimizers/logic_theorem_optimizer/modal_autoencoder.py",
        ),
        target_metrics=("legal_ir_view_cross_entropy_loss", "legal_ir_multiview_total_loss"),
        theorem_templates=("modal_operator_preserved", "decompiler_round_trip"),
        mutation_cases=("invert_modality", "alter_scope"),
        target_file_lane="bridge",
    ),
    "deontic.ir": LeanstralOwnedSurface(
        component="deontic.ir",
        action="repair_deontic_bridge_quality_gate",
        allowed_paths=(
            "ipfs_datasets_py/logic/modal/codec.py",
            "ipfs_datasets_py/logic/modal/decompiler.py",
        ),
        target_metrics=("deontic_decoder_slot_loss", "legal_ir_view_cross_entropy_loss"),
        theorem_templates=("modal_operator_preserved", "exception_scope_preserved"),
        mutation_cases=("invert_modality", "remove_exception"),
        target_file_lane="deontic",
    ),
    "external_provers.router": LeanstralOwnedSurface(
        component="external_provers.router",
        action="repair_multiview_legal_ir_prover_gate",
        allowed_paths=(
            "ipfs_datasets_py/optimizers/logic_theorem_optimizer/prover_integration.py",
            "ipfs_datasets_py/logic/external_provers/interactive/lean_prover_bridge.py",
        ),
        target_metrics=("legal_ir_multiview_proof_failure_ratio",),
        theorem_templates=("modal_operator_preserved", "proof_route_is_distinct_from_proof"),
        mutation_cases=("unsupported_modal_system",),
        target_file_lane="external_provers",
    ),
    "TDFOL.prover": LeanstralOwnedSurface(
        component="TDFOL.prover",
        action="repair_tdfol_bridge_parse_and_proof_gate",
        allowed_paths=(
            "ipfs_datasets_py/logic/bridge/fol_tdfol.py",
            "ipfs_datasets_py/logic/TDFOL/tdfol_parser.py",
            "ipfs_datasets_py/logic/TDFOL/tdfol_prover.py",
        ),
        target_metrics=(
            "tdfol_parse_failure_ratio",
            "legal_ir_multiview_proof_failure_ratio",
        ),
        theorem_templates=(
            "proof_route_is_distinct_from_proof",
            "source_provenance_preserved",
        ),
        mutation_cases=("unsupported_quantifier_scope", "alter_predicate_arity"),
        target_file_lane="tdfol_prover",
    ),
    "CEC.native": LeanstralOwnedSurface(
        component="CEC.native",
        action="repair_cec_dcec_bridge_projection",
        allowed_paths=(
            "ipfs_datasets_py/logic/bridge/cec_dcec.py",
            "ipfs_datasets_py/logic/CEC/native/dcec_parsing.py",
            "ipfs_datasets_py/logic/CEC/native/event_calculus.py",
        ),
        target_metrics=(
            "cec_event_projection_loss",
            "legal_ir_view_cross_entropy_loss",
        ),
        theorem_templates=("event_interval_preserved", "source_provenance_preserved"),
        mutation_cases=("alter_event_time", "remove_event_precondition"),
        target_file_lane="cec_native",
    ),
    "zkp.circuits": LeanstralOwnedSurface(
        component="zkp.circuits",
        action="repair_zkp_attestation_bridge",
        allowed_paths=(
            "ipfs_datasets_py/logic/bridge/zkp_attestation.py",
            "ipfs_datasets_py/logic/TDFOL/zkp_integration.py",
            "ipfs_datasets_py/logic/zkp/zkp_prover.py",
        ),
        target_metrics=(
            "zkp_attestation_failure_ratio",
            "legal_ir_multiview_graph_failure_penalty",
        ),
        theorem_templates=(
            "proof_route_is_distinct_from_proof",
            "source_provenance_preserved",
        ),
        mutation_cases=("tamper_attestation_hash", "remove_frame_relation"),
        target_file_lane="zkp_circuits",
    ),
    "knowledge_graphs.neo4j_compat": LeanstralOwnedSurface(
        component="knowledge_graphs.neo4j_compat",
        action="repair_multiview_legal_ir_graph_projection",
        allowed_paths=("ipfs_datasets_py/logic/modal/kg_bridge.py",),
        target_metrics=("legal_ir_multiview_graph_failure_penalty",),
        theorem_templates=("graph_has_no_dangling_edges", "source_provenance_preserved"),
        mutation_cases=("remove_relation_endpoint",),
        target_file_lane="knowledge_graph",
    ),
    "modal.frame_logic": LeanstralOwnedSurface(
        component="modal.frame_logic",
        action="repair_flogic_ontology_constraints",
        allowed_paths=("ipfs_datasets_py/logic/modal/kg_bridge.py",),
        target_metrics=("flogic_similarity_loss", "legal_ir_view_cross_entropy_loss"),
        theorem_templates=("source_provenance_preserved", "frame_terms_preserved"),
        mutation_cases=("remove_frame_relation", "alter_scope"),
        target_file_lane="frame_logic",
    ),
}


@dataclass(frozen=True)
class LeanstralRuleGapEvidence:
    """Bounded evidence retained for one supporting or conflicting audit."""

    evidence_id: str
    role: str
    request_id: str
    response_hash: str
    verification_outcome: str
    classification: str
    confidence: float
    proof_obligation_ids: Sequence[str]
    affected_ir_families: Sequence[str]
    drafted_logic_candidates: Sequence[Dict[str, Any]] = field(default_factory=tuple)
    hammer_guidance_artifacts: Sequence[Dict[str, Any]] = field(default_factory=tuple)
    hammer_backend_health: Mapping[str, Any] = field(default_factory=dict)
    hammer_proof_status: Mapping[str, Any] = field(default_factory=dict)
    hammer_reconstruction_status: Mapping[str, Any] = field(default_factory=dict)
    codex_projection: Mapping[str, Any] = field(default_factory=dict)
    examples: Sequence[Dict[str, Any]] = field(default_factory=tuple)
    metric_attribution: Mapping[str, Any] = field(default_factory=dict)
    reasons: Sequence[str] = field(default_factory=tuple)
    verified_by: Sequence[str] = field(default_factory=tuple)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "affected_ir_families": list(self.affected_ir_families),
            "classification": self.classification,
            "confidence": self.confidence,
            "drafted_logic_candidates": [
                dict(candidate) for candidate in self.drafted_logic_candidates
            ],
            "evidence_id": self.evidence_id,
            "codex_projection": _json_ready(self.codex_projection),
            "examples": [dict(example) for example in self.examples],
            "hammer_backend_health": _json_ready(self.hammer_backend_health),
            "hammer_guidance_artifacts": [
                dict(artifact) for artifact in self.hammer_guidance_artifacts
            ],
            "hammer_proof_status": _json_ready(self.hammer_proof_status),
            "hammer_reconstruction_status": _json_ready(
                self.hammer_reconstruction_status
            ),
            "metric_attribution": _json_ready(self.metric_attribution),
            "proof_obligation_ids": list(self.proof_obligation_ids),
            "reasons": list(self.reasons),
            "request_id": self.request_id,
            "response_hash": self.response_hash,
            "role": self.role,
            "verification_outcome": self.verification_outcome,
            "verified_by": list(self.verified_by),
        }


@dataclass(frozen=True)
class LeanstralRuleGap:
    """One deduplicated, evidence-backed compiler rule gap."""

    gap_id: str
    status: str
    title: str
    normalized_rule_key: str
    missing_semantic_rule: Dict[str, Any]
    affected_ir_families: Sequence[str]
    target_surface: LeanstralOwnedSurface
    priority: float
    validation_set: Dict[str, Any]
    supporting_evidence: Sequence[LeanstralRuleGapEvidence]
    conflicting_evidence: Sequence[LeanstralRuleGapEvidence] = field(default_factory=tuple)

    @property
    def action(self) -> str:
        return self.target_surface.action

    @property
    def target_component(self) -> str:
        return self.target_surface.component

    def to_dict(self) -> Dict[str, Any]:
        return {
            "action": self.action,
            "affected_ir_families": list(self.affected_ir_families),
            "conflicting_evidence": [
                evidence.to_dict() for evidence in self.conflicting_evidence
            ],
            "gap_id": self.gap_id,
            "missing_semantic_rule": dict(self.missing_semantic_rule),
            "normalized_rule_key": self.normalized_rule_key,
            "priority": self.priority,
            "status": self.status,
            "supporting_evidence": [
                evidence.to_dict() for evidence in self.supporting_evidence
            ],
            "target_component": self.target_component,
            "target_surface": self.target_surface.to_dict(),
            "title": self.title,
            "validation_set": _json_ready(self.validation_set),
        }


@dataclass(frozen=True)
class LeanstralRejectedAudit:
    """An audit that was not allowed to become a rule-gap task."""

    audit_id: str
    reasons: Sequence[str]
    status: str = "rejected"
    request_id: str = ""
    response_hash: str = ""
    verification_outcome: str = ""
    classification: str = ""
    proposed_surfaces: Sequence[Dict[str, Any]] = field(default_factory=tuple)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "audit_id": self.audit_id,
            "classification": self.classification,
            "proposed_surfaces": [dict(surface) for surface in self.proposed_surfaces],
            "reasons": list(self.reasons),
            "request_id": self.request_id,
            "response_hash": self.response_hash,
            "status": self.status,
            "verification_outcome": self.verification_outcome,
        }


@dataclass(frozen=True)
class LeanstralRuleGapReport:
    """Bounded report consumed by the synthesis/TODO projection lane."""

    schema_version: str
    gaps: Sequence[LeanstralRuleGap]
    rejected_audits: Sequence[LeanstralRejectedAudit]
    source_audit_count: int
    accepted_supporting_audit_count: int
    conflicting_audit_count: int
    max_gaps: int
    max_examples_per_gap: int

    def to_dict(self) -> Dict[str, Any]:
        return {
            "accepted_supporting_audit_count": self.accepted_supporting_audit_count,
            "conflicting_audit_count": self.conflicting_audit_count,
            "gaps": [gap.to_dict() for gap in self.gaps],
            "max_examples_per_gap": self.max_examples_per_gap,
            "max_gaps": self.max_gaps,
            "rejected_audits": [audit.to_dict() for audit in self.rejected_audits],
            "schema_version": self.schema_version,
            "source_audit_count": self.source_audit_count,
        }


@dataclass(frozen=True)
class LeanstralRuleGapReportConfig:
    """Bounds for deterministic rule-gap aggregation."""

    max_gaps: int = 25
    max_examples_per_gap: int = 5
    max_conflicts_per_gap: int = 5


@dataclass(frozen=True)
class LeanstralPatchLineage:
    """State-to-audit-to-TODO-to-patch lineage for one compiler patch result."""

    state_hash: str = ""
    compiler_commit: str = ""
    gap_id: str = ""
    normalized_rule_key: str = ""
    feature_cluster_id: str = ""
    target_component: str = ""
    owned_ast_scope: str = ""
    todo_id: str = ""
    todo_status: str = ""
    todo_action: str = ""
    audit_request_ids: Sequence[str] = field(default_factory=tuple)
    audit_response_hashes: Sequence[str] = field(default_factory=tuple)
    evidence_ids: Sequence[str] = field(default_factory=tuple)
    proof_ids: Sequence[str] = field(default_factory=tuple)
    patch_status: str = ""
    codex_exec_status: str = ""
    validation_commands: Sequence[str] = field(default_factory=tuple)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "audit_request_ids": list(self.audit_request_ids),
            "audit_response_hashes": list(self.audit_response_hashes),
            "codex_exec_status": self.codex_exec_status,
            "compiler_commit": self.compiler_commit,
            "evidence_ids": list(self.evidence_ids),
            "feature_cluster_id": self.feature_cluster_id,
            "gap_id": self.gap_id,
            "normalized_rule_key": self.normalized_rule_key,
            "owned_ast_scope": self.owned_ast_scope,
            "patch_status": self.patch_status,
            "proof_ids": list(self.proof_ids),
            "state_hash": self.state_hash,
            "target_component": self.target_component,
            "todo_action": self.todo_action,
            "todo_id": self.todo_id,
            "todo_status": self.todo_status,
            "validation_commands": list(self.validation_commands),
        }


@dataclass(frozen=True)
class LeanstralPatchOutcomeRecord:
    """Attribution of one accepted or rejected compiler patch to a feature cluster."""

    outcome_id: str
    outcome: str
    feature_cluster_id: str
    lineage: LeanstralPatchLineage
    target_metrics: Sequence[str] = field(default_factory=tuple)
    metric_deltas: Mapping[str, float] = field(default_factory=dict)
    reasons: Sequence[str] = field(default_factory=tuple)
    compiler_target: Optional[Dict[str, Any]] = None
    suppress_cluster: bool = False
    verified_for_autoencoder: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "compiler_target": _json_ready(self.compiler_target or {}),
            "feature_cluster_id": self.feature_cluster_id,
            "lineage": self.lineage.to_dict(),
            "metric_deltas": {
                str(key): float(value)
                for key, value in sorted(self.metric_deltas.items())
            },
            "outcome": self.outcome,
            "outcome_id": self.outcome_id,
            "reasons": list(self.reasons),
            "suppress_cluster": bool(self.suppress_cluster),
            "target_metrics": list(self.target_metrics),
            "verified_for_autoencoder": bool(self.verified_for_autoencoder),
        }


@dataclass(frozen=True)
class LeanstralPatchFeedbackReport:
    """Feedback report consumed by projection and compiler-target evaluation."""

    schema_version: str
    outcomes: Sequence[LeanstralPatchOutcomeRecord]
    suppressed_feature_clusters: Sequence[str] = field(default_factory=tuple)
    compiler_targets_for_autoencoder_evaluation: Sequence[Dict[str, Any]] = field(
        default_factory=tuple
    )

    def to_dict(self) -> Dict[str, Any]:
        counts: Dict[str, int] = {}
        for outcome in self.outcomes:
            counts[outcome.outcome] = counts.get(outcome.outcome, 0) + 1
        return {
            "compiler_targets_for_autoencoder_evaluation": _json_ready(
                list(self.compiler_targets_for_autoencoder_evaluation)
            ),
            "outcome_counts": dict(sorted(counts.items())),
            "outcomes": [outcome.to_dict() for outcome in self.outcomes],
            "schema_version": self.schema_version,
            "suppressed_feature_clusters": list(self.suppressed_feature_clusters),
        }


@dataclass
class _GapAccumulator:
    response: LeanstralAuditResponse
    rule_key: str
    surface: LeanstralOwnedSurface
    families: Sequence[str]
    supporting: List[LeanstralRuleGapEvidence] = field(default_factory=list)
    conflicting: List[LeanstralRuleGapEvidence] = field(default_factory=list)


@dataclass(frozen=True)
class _AuditRecord:
    response: Optional[LeanstralAuditResponse]
    verification: Any
    request_id: str = ""
    request: Mapping[str, Any] = field(default_factory=dict)
    hammer_verification: Any = None


def build_leanstral_rule_gap_report(
    audits: Iterable[Any],
    *,
    config: Optional[LeanstralRuleGapReportConfig] = None,
) -> LeanstralRuleGapReport:
    """Collapse verified audits into bounded compiler rule-gap reports."""

    return aggregate_verified_audits(audits, config=config)


def aggregate_verified_audits(
    audits: Iterable[Any],
    *,
    config: Optional[LeanstralRuleGapReportConfig] = None,
) -> LeanstralRuleGapReport:
    """Return deduplicated rule gaps from verified Leanstral audit records.

    ``audits`` accepts typed ``(response, verification)`` tuples, dictionaries
    with ``response`` and ``verification`` keys, or equivalent JSON-ready
    payloads.  A record must contain a structured audit response and local
    verification result to become supporting evidence.
    """

    cfg = config or LeanstralRuleGapReportConfig()
    max_gaps = max(1, int(cfg.max_gaps))
    max_examples = max(1, int(cfg.max_examples_per_gap))
    max_conflicts = max(0, int(cfg.max_conflicts_per_gap))
    source_count = 0
    supporting_count = 0
    conflict_count = 0
    rejected: List[LeanstralRejectedAudit] = []
    accumulators: Dict[str, _GapAccumulator] = {}
    pending_conflicts: Dict[str, List[LeanstralRuleGapEvidence]] = {}
    pending_orphan_rejections: Dict[str, List[LeanstralRejectedAudit]] = {}

    for item in audits:
        source_count += 1
        record = _coerce_audit_record(item)
        response = record.response
        verification = record.verification
        if response is None:
            rejected.append(
                _rejected_audit(
                    record,
                    ("missing_audit_response",),
                )
            )
            continue

        surface, surface_reasons = _surface_for_response(response)
        if surface is None:
            rejected.append(_rejected_audit(record, surface_reasons))
            continue

        accepted = _verification_accepted(verification)
        is_issue = response.classification in ISSUE_AUDIT_CLASSIFICATIONS
        families = _families(response)
        rule_key, signature_families = _rule_identity(
            response,
            surface=surface,
            families=families,
        )
        if not rule_key:
            rejected.append(_rejected_audit(record, ("missing_rule_key",)))
            continue
        signature = _gap_signature(
            rule_key,
            surface.component,
            signature_families,
        )
        evidence = _evidence_from_record(
            record,
            role="supporting" if accepted and is_issue else "conflicting",
            max_examples=max_examples,
        )
        if accepted and is_issue:
            accumulator = accumulators.get(signature)
            if accumulator is None:
                accumulator = _GapAccumulator(
                    response=response,
                    rule_key=rule_key,
                    surface=surface,
                    families=families,
                )
                accumulators[signature] = accumulator
            else:
                accumulator.families = _dedupe_strings(
                    [*accumulator.families, *families]
                )
            accumulator.supporting.append(evidence)
            supporting_count += 1
            for conflict in pending_conflicts.pop(signature, []):
                if len(accumulator.conflicting) < max_conflicts:
                    accumulator.conflicting.append(conflict)
            pending_orphan_rejections.pop(signature, None)
            continue

        conflict_count += 1
        if signature in accumulators:
            accumulator = accumulators[signature]
            if len(accumulator.conflicting) < max_conflicts:
                accumulator.conflicting.append(evidence)
        else:
            pending_conflicts.setdefault(signature, []).append(evidence)
            pending_orphan_rejections.setdefault(signature, []).append(
                _rejected_audit(
                    record,
                    tuple(_verification_reasons(verification))
                    or ("no_verified_supporting_audit",),
                )
            )

    gaps = [_gap_from_accumulator(acc, max_examples=max_examples) for acc in accumulators.values()]
    gaps = sorted(gaps, key=lambda gap: (-gap.priority, gap.gap_id))[:max_gaps]
    for orphan_group in pending_orphan_rejections.values():
        rejected.extend(orphan_group)
    rejected = sorted(rejected, key=lambda audit: audit.audit_id)
    return LeanstralRuleGapReport(
        schema_version=LEANSTRAL_RULE_GAP_REPORT_SCHEMA_VERSION,
        gaps=tuple(gaps),
        rejected_audits=tuple(rejected),
        source_audit_count=source_count,
        accepted_supporting_audit_count=supporting_count,
        conflicting_audit_count=conflict_count,
        max_gaps=max_gaps,
        max_examples_per_gap=max_examples,
    )


def leanstral_rule_gap_report_to_json(report: LeanstralRuleGapReport) -> str:
    """Serialize a rule-gap report with stable key ordering."""

    return json.dumps(report.to_dict(), ensure_ascii=True, sort_keys=True, indent=2)


def build_leanstral_patch_feedback_report(
    patch_results: Iterable[Any],
    *,
    suppression_threshold: int = 2,
) -> LeanstralPatchFeedbackReport:
    """Attribute compiler patch outcomes back to Leanstral feature clusters.

    The input may be ``ModalTodo`` objects, TODO dictionaries, or explicit
    dictionaries with ``todo``/``validation_report`` keys.  Only verified,
    completed program-synthesis patches become compiler targets for later
    autoencoder evaluation; unverified Leanstral assertions remain journaled
    evidence and are never emitted as trainable weight updates.
    """

    threshold = max(1, int(suppression_threshold))
    outcomes: List[LeanstralPatchOutcomeRecord] = []
    disproved_counts: Dict[str, int] = {}
    for item in patch_results:
        record = _patch_feedback_record(item)
        if record is None:
            continue
        outcomes.append(record)
        if record.outcome in {
            LEANSTRAL_PATCH_OUTCOME_QUALITY_REGRESSION,
            LEANSTRAL_PATCH_OUTCOME_UNSUPPORTED_HYPOTHESIS,
        }:
            disproved_counts[record.feature_cluster_id] = (
                disproved_counts.get(record.feature_cluster_id, 0) + 1
            )

    suppressed = tuple(
        sorted(
            cluster_id
            for cluster_id, count in disproved_counts.items()
            if cluster_id and count >= threshold
        )
    )
    compiler_targets = tuple(
        record.compiler_target
        for record in outcomes
        if record.compiler_target
        and record.outcome == LEANSTRAL_PATCH_OUTCOME_ACCEPTED_IMPROVEMENT
    )
    return LeanstralPatchFeedbackReport(
        schema_version=LEANSTRAL_PATCH_FEEDBACK_REPORT_SCHEMA_VERSION,
        outcomes=tuple(outcomes),
        suppressed_feature_clusters=suppressed,
        compiler_targets_for_autoencoder_evaluation=compiler_targets,
    )


def leanstral_patch_feedback_report_to_json(
    report: LeanstralPatchFeedbackReport,
) -> str:
    """Serialize a patch feedback report with stable key ordering."""

    return json.dumps(report.to_dict(), ensure_ascii=True, sort_keys=True, indent=2)


def classify_leanstral_patch_outcome(record: Any) -> str:
    """Return the deterministic feedback classification for one patch record."""

    data, metadata = _patch_feedback_data(record)
    status = str(data.get("status") or data.get("todo_status") or "").strip()
    if bool(metadata.get("leanstral_stale_evidence")) or status == "stale":
        return LEANSTRAL_PATCH_OUTCOME_STALE_EVIDENCE

    patch_status = str(
        data.get("patch_status")
        or metadata.get("completed_patch_status")
        or metadata.get("failed_validation_patch_status")
        or metadata.get("last_transient_patch_status")
        or ""
    ).strip().lower()
    exec_status = str(
        data.get("codex_exec_status")
        or metadata.get("completed_codex_exec_status")
        or metadata.get("failed_validation_codex_exec_status")
        or metadata.get("last_transient_codex_exec_status")
        or ""
    ).strip().lower()
    validation = _patch_feedback_validation_report(data, metadata)
    validation_status = str(
        validation.get("main_apply_validation_status")
        or validation.get("validation_status")
        or validation.get("status")
        or ""
    ).strip().lower()
    target_status = str(validation.get("target_metric_status") or "").strip().lower()
    holdout_status = str(
        validation.get("holdout_target_metric_status") or ""
    ).strip().lower()
    regressed = bool(
        _sequence_values(validation.get("regressed_metrics"))
        or _sequence_values(validation.get("hard_regressed_metrics"))
        or _sequence_values(validation.get("target_metric_hard_regressed_metrics"))
        or target_status == "regressed"
        or holdout_status == "regressed"
    )
    if regressed:
        return LEANSTRAL_PATCH_OUTCOME_QUALITY_REGRESSION

    if status == "completed":
        if _leanstral_patch_verified(metadata, validation):
            return LEANSTRAL_PATCH_OUTCOME_ACCEPTED_IMPROVEMENT
        return LEANSTRAL_PATCH_OUTCOME_UNSUPPORTED_HYPOTHESIS

    if status == "failed_validation":
        failure_reason = str(
            data.get("failure_reason")
            or metadata.get("failure_reason")
            or metadata.get("failed_validation_reason")
            or ""
        )
        if "regression" in failure_reason:
            return LEANSTRAL_PATCH_OUTCOME_QUALITY_REGRESSION
        if validation_status == "failed" or patch_status in {
            "created",
            "applied_to_main",
            "main_apply_no_merged_delta",
        }:
            return LEANSTRAL_PATCH_OUTCOME_UNSUPPORTED_HYPOTHESIS
        return LEANSTRAL_PATCH_OUTCOME_OPERATIONAL_FAILURE

    if patch_status in {
        "awaiting_codex_changes",
        "main_apply_baseline_validation_failed_rolled_back",
        "main_apply_target_metric_unavailable_rolled_back",
    } or exec_status in {"failed", "timeout", "transient_failure"}:
        return LEANSTRAL_PATCH_OUTCOME_OPERATIONAL_FAILURE
    return LEANSTRAL_PATCH_OUTCOME_UNSUPPORTED_HYPOTHESIS


def leanstral_compiler_target_from_patch_record(record: Any) -> Optional[Dict[str, Any]]:
    """Return a deterministic compiler target only for verified accepted patches."""

    data, metadata = _patch_feedback_data(record)
    validation = _patch_feedback_validation_report(data, metadata)
    if classify_leanstral_patch_outcome(record) != LEANSTRAL_PATCH_OUTCOME_ACCEPTED_IMPROVEMENT:
        return None
    if not _leanstral_patch_verified(metadata, validation):
        return None
    target_metrics = _dedupe_strings(_sequence_values(metadata.get("target_metrics")))
    attribution = (
        metadata.get("leanstral_metric_attribution")
        if isinstance(metadata.get("leanstral_metric_attribution"), Mapping)
        else {}
    )
    pre_patch_metrics = _numeric_metric_map(
        metadata.get("pre_patch_metrics")
        or attribution.get("pre_patch_metrics")
        or {}
    )
    post_patch_metrics = _numeric_metric_map(
        metadata.get("post_patch_metrics")
        or attribution.get("post_patch_metrics")
        or validation.get("post_patch_metrics")
        or validation.get("metrics_after")
        or {}
    )
    metric_deltas = _metric_deltas(validation)
    return {
        "allowed_paths": list(_dedupe_strings(_sequence_values(metadata.get("allowed_paths")))),
        "audit_request_ids": list(
            _dedupe_strings(_sequence_values(metadata.get("audit_request_ids")))
        ),
        "audit_response_hashes": list(
            _dedupe_strings(_sequence_values(metadata.get("audit_response_hashes")))
        ),
        "evidence_ids": list(_dedupe_strings(_sequence_values(metadata.get("evidence_ids")))),
        "feature_cluster_id": _feature_cluster_id(data, metadata),
        "gap_id": str(metadata.get("leanstral_gap_id") or ""),
        "leanstral_drafted_logic_candidates": _drafted_logic_candidates_from_metadata(
            metadata
        ),
        "leanstral_guidance_mode": str(
            metadata.get("leanstral_guidance_mode")
            or "draft_logic_guidance_only"
        ),
        "mutation_cases": list(_dedupe_strings(_sequence_values(metadata.get("mutation_cases")))),
        "normalized_rule_key": str(metadata.get("normalized_rule_key") or ""),
        "owned_ast_scope": str(metadata.get("owned_ast_scope") or metadata.get("program_synthesis_scope") or ""),
        "metric_attribution": {
            "metric_deltas": metric_deltas,
            "post_patch_metrics": post_patch_metrics,
            "pre_patch_metrics": pre_patch_metrics,
            "schema_version": "legal-ir-leanstral-metric-attribution-v1",
            "source": "leanstral_patch_feedback",
            "status": "post_patch_observed"
            if post_patch_metrics or metric_deltas
            else "pre_patch_observed"
            if pre_patch_metrics
            else "missing_pre_patch_metrics",
        },
        "target_component": str(metadata.get("target_component") or ""),
        "target_metrics": list(target_metrics),
        "todo_id": str(data.get("todo_id") or ""),
        "validation_commands": list(
            _dedupe_strings(_sequence_values(metadata.get("validation_commands")))
        ),
        "validation_gate": _json_ready(metadata.get("validation_gate") or {}),
        "verified_compiler_rule": True,
        "write_to_autoencoder_weights": False,
    }


def _patch_feedback_record(item: Any) -> Optional[LeanstralPatchOutcomeRecord]:
    data, metadata = _patch_feedback_data(item)
    if not bool(metadata.get("leanstral_projection")) and not metadata.get("leanstral_gap_id"):
        return None
    lineage = _patch_feedback_lineage(data, metadata)
    outcome = classify_leanstral_patch_outcome(item)
    feature_cluster_id = lineage.feature_cluster_id
    validation = _patch_feedback_validation_report(data, metadata)
    reasons = _patch_feedback_reasons(data, metadata, validation, outcome)
    compiler_target = leanstral_compiler_target_from_patch_record(item)
    payload = {
        "feature_cluster_id": feature_cluster_id,
        "outcome": outcome,
        "patch_status": lineage.patch_status,
        "todo_id": lineage.todo_id,
    }
    outcome_id = "leanstral-patch-outcome-" + hashlib.sha256(
        json.dumps(payload, ensure_ascii=True, sort_keys=True).encode("utf-8")
    ).hexdigest()[:16]
    return LeanstralPatchOutcomeRecord(
        outcome_id=outcome_id,
        outcome=outcome,
        feature_cluster_id=feature_cluster_id,
        lineage=lineage,
        target_metrics=tuple(_dedupe_strings(_sequence_values(metadata.get("target_metrics")))),
        metric_deltas=_metric_deltas(validation),
        reasons=tuple(reasons),
        compiler_target=compiler_target,
        suppress_cluster=outcome
        in {
            LEANSTRAL_PATCH_OUTCOME_QUALITY_REGRESSION,
            LEANSTRAL_PATCH_OUTCOME_UNSUPPORTED_HYPOTHESIS,
        },
        verified_for_autoencoder=bool(compiler_target),
    )


def _patch_feedback_data(item: Any) -> tuple[Dict[str, Any], Dict[str, Any]]:
    if hasattr(item, "to_dict"):
        data = item.to_dict()
    elif isinstance(item, Mapping):
        if "todo" in item and isinstance(item.get("todo"), Mapping):
            data = dict(item["todo"])
            data.update(
                {
                    key: value
                    for key, value in item.items()
                    if key not in {"todo", "metadata"}
                }
            )
        else:
            data = dict(item)
    else:
        data = {
            "action": getattr(item, "action", ""),
            "metadata": getattr(item, "metadata", {}),
            "status": getattr(item, "status", ""),
            "todo_id": getattr(item, "todo_id", ""),
        }
    metadata = dict(data.get("metadata") or {})
    if isinstance(item, Mapping) and isinstance(item.get("metadata"), Mapping):
        metadata.update(dict(item.get("metadata") or {}))
    return data, metadata


def _patch_feedback_lineage(
    data: Mapping[str, Any],
    metadata: Mapping[str, Any],
) -> LeanstralPatchLineage:
    validation = _patch_feedback_validation_report(data, metadata)
    return LeanstralPatchLineage(
        state_hash=str(
            metadata.get("state_hash")
            or metadata.get("autoencoder_state_hash")
            or data.get("state_hash")
            or ""
        ),
        compiler_commit=str(
            metadata.get("compiler_commit")
            or data.get("compiler_commit")
            or validation.get("compiler_commit")
            or ""
        ),
        gap_id=str(metadata.get("leanstral_gap_id") or metadata.get("gap_id") or ""),
        normalized_rule_key=str(metadata.get("normalized_rule_key") or ""),
        feature_cluster_id=_feature_cluster_id(data, metadata),
        target_component=str(metadata.get("target_component") or data.get("target_component") or ""),
        owned_ast_scope=str(
            metadata.get("owned_ast_scope")
            or metadata.get("program_synthesis_scope")
            or ""
        ),
        todo_id=str(data.get("todo_id") or ""),
        todo_status=str(data.get("status") or data.get("todo_status") or ""),
        todo_action=str(data.get("action") or ""),
        audit_request_ids=tuple(
            _dedupe_strings(_sequence_values(metadata.get("audit_request_ids")))
        ),
        audit_response_hashes=tuple(
            _dedupe_strings(_sequence_values(metadata.get("audit_response_hashes")))
        ),
        evidence_ids=tuple(_dedupe_strings(_sequence_values(metadata.get("evidence_ids")))),
        proof_ids=tuple(_dedupe_strings(_sequence_values(metadata.get("proof_ids")))),
        patch_status=str(
            data.get("patch_status")
            or metadata.get("completed_patch_status")
            or metadata.get("failed_validation_patch_status")
            or metadata.get("last_transient_patch_status")
            or ""
        ),
        codex_exec_status=str(
            data.get("codex_exec_status")
            or metadata.get("completed_codex_exec_status")
            or metadata.get("failed_validation_codex_exec_status")
            or metadata.get("last_transient_codex_exec_status")
            or ""
        ),
        validation_commands=tuple(
            _dedupe_strings(_sequence_values(metadata.get("validation_commands")))
        ),
    )


def _patch_feedback_validation_report(
    data: Mapping[str, Any],
    metadata: Mapping[str, Any],
) -> Dict[str, Any]:
    for value in (
        data.get("validation_report"),
        metadata.get("completed_validation_report"),
        metadata.get("failed_validation_report"),
        metadata.get("last_transient_validation_report"),
    ):
        if isinstance(value, Mapping):
            return dict(value)
    return {}


def _feature_cluster_id(data: Mapping[str, Any], metadata: Mapping[str, Any]) -> str:
    explicit = str(
        metadata.get("feature_cluster_id")
        or metadata.get("semantic_bundle_key")
        or metadata.get("leanstral_dedup_key")
        or metadata.get("dedupe_signature")
        or ""
    ).strip()
    if explicit:
        return explicit
    payload = {
        "action": str(data.get("action") or ""),
        "gap_id": str(metadata.get("leanstral_gap_id") or ""),
        "normalized_rule_key": str(metadata.get("normalized_rule_key") or ""),
        "scope": str(metadata.get("program_synthesis_scope") or ""),
        "target_component": str(metadata.get("target_component") or ""),
    }
    digest = hashlib.sha256(
        json.dumps(payload, ensure_ascii=True, sort_keys=True).encode("utf-8")
    ).hexdigest()[:20]
    return f"leanstral-feature-cluster:{digest}"


def _leanstral_patch_verified(
    metadata: Mapping[str, Any],
    validation: Mapping[str, Any],
) -> bool:
    if not bool(metadata.get("leanstral_verified")):
        return False
    if not _sequence_values(metadata.get("leanstral_local_verifiers")):
        return False
    gate = metadata.get("validation_gate")
    if isinstance(gate, Mapping) and gate.get("accepted") is False:
        return False
    target_status = str(validation.get("target_metric_status") or "").strip().lower()
    holdout_status = str(
        validation.get("holdout_target_metric_status") or ""
    ).strip().lower()
    validation_status = str(
        validation.get("main_apply_validation_status")
        or validation.get("validation_status")
        or validation.get("status")
        or ""
    ).strip().lower()
    if target_status in {"regressed", "failed", "timeout", "unavailable"}:
        return False
    if holdout_status in {"regressed", "failed", "timeout", "unavailable"}:
        return False
    if validation_status in {"failed", "timeout"}:
        return False
    return True


def _patch_feedback_reasons(
    data: Mapping[str, Any],
    metadata: Mapping[str, Any],
    validation: Mapping[str, Any],
    outcome: str,
) -> Sequence[str]:
    reasons: List[str] = []
    for key in (
        "failure_reason",
        "failed_validation_reason",
        "transient_failure_reason",
        "stale_claim_requeue_reason",
    ):
        value = data.get(key) or metadata.get(key)
        if value:
            reasons.append(str(value))
    for key in (
        "regressed_metrics",
        "target_metric_hard_regressed_metrics",
        "holdout_hard_regressed_metrics",
    ):
        values = _sequence_values(validation.get(key))
        if values:
            reasons.append(f"{key}:{','.join(values)}")
    if not reasons:
        reasons.append(outcome)
    return _dedupe_strings(reasons)


def _metric_deltas(validation: Mapping[str, Any]) -> Dict[str, float]:
    deltas: Dict[str, float] = {}
    for key in ("metric_deltas", "holdout_metric_deltas"):
        raw = validation.get(key)
        if not isinstance(raw, Mapping):
            continue
        for metric, value in raw.items():
            try:
                deltas[str(metric)] = float(value)
            except (TypeError, ValueError):
                continue
    return dict(sorted(deltas.items()))


def _drafted_logic_candidates_from_metadata(
    metadata: Mapping[str, Any],
    *,
    max_candidates: int = 12,
) -> List[Dict[str, Any]]:
    raw = metadata.get("leanstral_drafted_logic_candidates")
    if raw is None:
        raw = metadata.get("drafted_logic_candidates")
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes, bytearray)):
        return []
    candidates: List[Dict[str, Any]] = []
    seen: set[str] = set()
    allowed_keys = {
        "audit_evidence_id",
        "candidate",
        "compiler_surface",
        "confidence",
        "evidence_id",
        "example_id",
        "expected_failure_mode",
        "guidance_only",
        "intended_use",
        "logic_family",
        "premise_hints",
        "proof_obligation_id",
        "proof_obligation_ids",
        "request_id",
        "schema_version",
        "source_copy_policy",
        "source_copy_rejected",
        "source_span_hash",
        "target_component",
        "target_metric",
        "target_metrics",
        "target_view",
    }
    for item in raw:
        if not isinstance(item, Mapping):
            continue
        candidate_text = _bounded_string(item.get("candidate"), 240)
        if not candidate_text:
            continue
        payload = {
            str(key): value
            for key, value in dict(item).items()
            if str(key) in allowed_keys
        }
        payload["candidate"] = candidate_text
        payload["guidance_only"] = True
        payload["intended_use"] = "guidance_only"
        identity = json.dumps(payload, ensure_ascii=True, sort_keys=True, default=str)
        if identity in seen:
            continue
        seen.add(identity)
        candidates.append(payload)
        if len(candidates) >= max(0, int(max_candidates)):
            break
    return candidates


def _sequence_values(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, Mapping):
        return [
            str(key)
            for key, item in value.items()
            if item not in (None, "", [], {})
        ]
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [str(item) for item in value if str(item)]
    text = str(value).strip()
    return [text] if text else []


def _gap_from_accumulator(
    accumulator: _GapAccumulator,
    *,
    max_examples: int,
) -> LeanstralRuleGap:
    response = accumulator.response
    support = _dedupe_evidence(accumulator.supporting)
    conflicts = _dedupe_evidence(accumulator.conflicting)
    all_obligations = _dedupe_strings(
        obligation
        for evidence in support
        for obligation in evidence.proof_obligation_ids
    )
    validation_set = _validation_set(
        accumulator.surface,
        support,
        accumulator.families,
        proof_obligation_ids=all_obligations,
        max_examples=max_examples,
    )
    payload = {
        "families": list(accumulator.families),
        "rule_key": accumulator.rule_key,
        "surface": accumulator.surface.component,
        "supporting": [evidence.response_hash for evidence in support],
    }
    gap_id = "leanstral-gap-" + hashlib.sha256(
        json.dumps(payload, ensure_ascii=True, sort_keys=True).encode("utf-8")
    ).hexdigest()[:16]
    return LeanstralRuleGap(
        gap_id=gap_id,
        status=LeanstralVerificationOutcome.ACCEPTED.value,
        title=_gap_title(response, accumulator.surface),
        normalized_rule_key=accumulator.rule_key,
        missing_semantic_rule=dict(response.missing_semantic_rule),
        affected_ir_families=tuple(accumulator.families),
        target_surface=accumulator.surface,
        priority=_priority(accumulator.surface, support, conflicts),
        validation_set=validation_set,
        supporting_evidence=tuple(support),
        conflicting_evidence=tuple(conflicts),
    )


def _validation_set(
    surface: LeanstralOwnedSurface,
    supporting: Sequence[LeanstralRuleGapEvidence],
    families: Sequence[str],
    *,
    proof_obligation_ids: Sequence[str],
    max_examples: int,
) -> Dict[str, Any]:
    examples: List[Dict[str, Any]] = []
    for evidence in supporting:
        examples.extend(dict(example) for example in evidence.examples)
    examples = _dedupe_examples(examples)[:max_examples]
    metric_attribution = _merge_metric_attributions(
        evidence.metric_attribution for evidence in supporting
    )
    return {
        "allowed_paths": list(surface.allowed_paths),
        "affected_ir_families": list(families),
        "formal_validity_checks": list(surface.theorem_templates),
        "held_out_compiler_ir_metrics": list(surface.target_metrics),
        "metric_attribution": metric_attribution,
        "mutation_cases": list(surface.mutation_cases),
        "proof_obligation_ids": list(proof_obligation_ids),
        "regression_examples": examples,
        "target_file_lane": surface.target_file_lane,
    }


def _priority(
    surface: LeanstralOwnedSurface,
    supporting: Sequence[LeanstralRuleGapEvidence],
    conflicts: Sequence[LeanstralRuleGapEvidence],
) -> float:
    if not supporting:
        return 0.0
    confidence = sum(evidence.confidence for evidence in supporting) / len(supporting)
    support_bonus = min(0.18, 0.06 * len(supporting))
    formal_bonus = 0.12 if surface.theorem_templates else 0.0
    metric_bonus = 0.12 if surface.target_metrics else 0.0
    verifier_bonus = 0.08 if any(evidence.verified_by for evidence in supporting) else 0.0
    conflict_penalty = min(0.15, 0.04 * len(conflicts))
    value = confidence * 0.5 + support_bonus + formal_bonus + metric_bonus + verifier_bonus
    return round(max(0.0, min(1.0, value - conflict_penalty)), 12)


def _surface_for_response(
    response: LeanstralAuditResponse,
) -> tuple[Optional[LeanstralOwnedSurface], Sequence[str]]:
    surfaces = list(response.proposed_compiler_surface or ())
    if not surfaces:
        inferred = _infer_surface_from_response(response)
        if inferred:
            return inferred, ()
        return None, ("missing_proposed_compiler_surface",)

    rejected_reasons: List[str] = []
    for surface in surfaces:
        component_text = _surface_text(surface)
        if _FREE_FORM_SURFACE_PATTERN.search(component_text):
            rejected_reasons.append("free_form_architecture_task")
            continue
        component = _normalize_component(surface)
        component = _owned_surface_alias(component, surface, response)
        if component in OWNED_LEANSTRAL_RULE_GAP_SURFACES:
            owned = OWNED_LEANSTRAL_RULE_GAP_SURFACES[component]
            action = str(surface.get("action", surface.get("operation", ""))).strip()
            if action and _FREE_FORM_SURFACE_PATTERN.search(action):
                rejected_reasons.append("free_form_architecture_task")
                continue
            return _surface_adjusted_for_rule(owned, response), ()
        rejected_reasons.append("unowned_compiler_surface")
    return None, tuple(dict.fromkeys(rejected_reasons)) or ("unowned_compiler_surface",)


def _surface_adjusted_for_rule(
    surface: LeanstralOwnedSurface,
    response: LeanstralAuditResponse,
) -> LeanstralOwnedSurface:
    if surface.component != "modal.ir_decompiler":
        return surface
    rule_text = json.dumps(response.missing_semantic_rule, ensure_ascii=True).lower()
    if any(token in rule_text for token in ("exception", "unless", "deadline", "within")):
        return surface
    return LeanstralOwnedSurface(
        component=surface.component,
        action="refine_typed_ir_or_decompiler_slots",
        allowed_paths=surface.allowed_paths,
        target_metrics=(
            "reconstruction_loss",
            "source_decompiled_text_embedding_cosine_loss",
        ),
        theorem_templates=("decompiler_round_trip", "source_provenance_preserved"),
        mutation_cases=("remove_exception", "alter_deadline"),
        target_file_lane=surface.target_file_lane,
    )


def _infer_surface_from_response(
    response: LeanstralAuditResponse,
) -> Optional[LeanstralOwnedSurface]:
    families = {family.lower() for family in response.affected_ir_families}
    rule_text = json.dumps(response.missing_semantic_rule, ensure_ascii=True).lower()
    if (
        "tdfol" in families
        or "tdfol" in rule_text
        or "t.d.fol" in rule_text
        or "first-order" in rule_text
        or "temporal deontic" in rule_text
    ):
        return OWNED_LEANSTRAL_RULE_GAP_SURFACES["TDFOL.prover"]
    if (
        "cec" in families
        or "dcec" in families
        or "event_calculus" in families
        or "event calculus" in rule_text
        or "dcec" in rule_text
        or "event interval" in rule_text
    ):
        return OWNED_LEANSTRAL_RULE_GAP_SURFACES["CEC.native"]
    if (
        "zkp" in families
        or "zkp" in rule_text
        or "zero knowledge" in rule_text
        or "zero-knowledge" in rule_text
        or "attestation" in rule_text
        or "circuit" in rule_text
    ):
        return OWNED_LEANSTRAL_RULE_GAP_SURFACES["zkp.circuits"]
    if "proof" in rule_text or "prover" in rule_text:
        return OWNED_LEANSTRAL_RULE_GAP_SURFACES["external_provers.router"]
    if "graph" in rule_text:
        return OWNED_LEANSTRAL_RULE_GAP_SURFACES["knowledge_graphs.neo4j_compat"]
    if "deontic" in families or "obligation" in rule_text or "permission" in rule_text:
        return OWNED_LEANSTRAL_RULE_GAP_SURFACES["modal.ir_decompiler"]
    if "frame" in rule_text:
        return OWNED_LEANSTRAL_RULE_GAP_SURFACES["modal.frame_logic"]
    return None


def _normalize_component(surface: Mapping[str, Any]) -> str:
    component = str(surface.get("component", surface.get("target_component", ""))).strip()
    path_text = " ".join(str(path) for path in surface.get("paths", ()) or ())
    lowered = re.sub(r"[^a-z0-9]+", ".", component.lower()).strip(".")
    aliases = {
        "compiler": "modal.compiler",
        "modal.compiler.parser": "modal.compiler",
        "modal.compiler.registry": "modal.compiler.registry",
        "compiler.registry": "modal.compiler.registry",
        "modal.registry": "modal.compiler.registry",
        "modal.compiler.ambiguity": "modal.compiler.ambiguity",
        "compiler.ambiguity": "modal.compiler.ambiguity",
        "modal.decompiler": "modal.ir_decompiler",
        "modal.ir.decompiler": "modal.ir_decompiler",
        "modal.ir_decompiler": "modal.ir_decompiler",
        "decompiler": "modal.ir_decompiler",
        "bridge.contracts": "bridge.contracts",
        "deontic.ir": "deontic.ir",
        "external.provers.router": "external_provers.router",
        "external_provers.router": "external_provers.router",
        "external.prover": "external_provers.router",
        "external.prover.router": "external_provers.router",
        "knowledge.graphs.neo4j.compat": "knowledge_graphs.neo4j_compat",
        "knowledge_graphs.neo4j_compat": "knowledge_graphs.neo4j_compat",
        "frame.logic": "modal.frame_logic",
        "flogic": "modal.frame_logic",
        "modal.frame.logic": "modal.frame_logic",
        "modal.frame_logic": "modal.frame_logic",
        "prover": "external_provers.router",
        "tdfol": "TDFOL.prover",
        "tdfol.prover": "TDFOL.prover",
        "t.d.fol": "TDFOL.prover",
        "t.d.fol.prover": "TDFOL.prover",
        "cec": "CEC.native",
        "cec.native": "CEC.native",
        "dcec": "CEC.native",
        "event.calculus": "CEC.native",
        "event.calculus.native": "CEC.native",
        "zkp": "zkp.circuits",
        "zkp.circuit": "zkp.circuits",
        "zkp.circuits": "zkp.circuits",
        "zero.knowledge": "zkp.circuits",
        "zero.knowledge.circuit": "zkp.circuits",
        "zero.knowledge.circuits": "zkp.circuits",
    }
    if lowered in aliases:
        return aliases[lowered]
    if "decompiler.py" in path_text:
        return "modal.ir_decompiler"
    if "kg_bridge.py" in path_text:
        return "knowledge_graphs.neo4j_compat"
    if "compiler.py" in path_text:
        return "modal.compiler"
    if "codec.py" in path_text:
        return "modal.compiler.registry"
    return component


def _owned_surface_alias(
    component: str,
    surface: Mapping[str, Any],
    response: LeanstralAuditResponse,
) -> str:
    normalized = component.lower().replace("_", ".").replace("-", ".")
    raw_normalized = str(
        surface.get("component", surface.get("target_component", ""))
    ).strip().lower()
    raw_normalized = re.sub(r"[^a-z0-9]+", ".", raw_normalized).strip(".")
    rule_text = json.dumps(response.missing_semantic_rule, ensure_ascii=True).lower()
    surface_text = _surface_text(surface).lower()
    combined = f"{raw_normalized} {normalized} {surface_text} {rule_text}"
    if raw_normalized in {"tdfol", "tdfol.prover", "t.d.fol", "t.d.fol.prover"}:
        if any(
            token in combined
            for token in (
                "decompil",
                "family preservation",
                "frame-family",
                "reconstruct",
                "round trip",
                "round-trip",
            )
        ):
            return "modal.ir_decompiler"
        return "TDFOL.prover"
    if raw_normalized in {
        "cec",
        "cec.native",
        "dcec",
        "event.calculus",
        "event.calculus.native",
    }:
        return "CEC.native"
    if raw_normalized in {
        "zkp",
        "zkp.circuit",
        "zkp.circuits",
        "zero.knowledge",
        "zero.knowledge.circuit",
        "zero.knowledge.circuits",
    }:
        return "zkp.circuits"
    if raw_normalized in {"external.prover", "external.prover.router", "prover"}:
        return "external_provers.router"
    if raw_normalized in {"flogic", "frame.logic"}:
        return "modal.frame_logic"
    return component


def _surface_text(surface: Mapping[str, Any]) -> str:
    return " ".join(
        str(value)
        for value in (
            surface.get("component", ""),
            surface.get("target_component", ""),
            surface.get("operation", ""),
            surface.get("action", ""),
            surface.get("rationale", ""),
            surface.get("description", ""),
        )
    )


def _coerce_audit_record(item: Any) -> _AuditRecord:
    if isinstance(item, tuple) or (
        isinstance(item, list) and not isinstance(item, (str, bytes))
    ):
        values = list(item)
        if len(values) >= 4:
            request_id = str(getattr(values[0], "request_id", "") or "")
            return _AuditRecord(
                _coerce_response(values[1]),
                values[2],
                request_id=request_id,
                request=_coerce_request_payload(values[0]),
                hammer_verification=values[3],
            )
        if len(values) == 3 and _coerce_response(values[1]) is not None:
            request_id = str(getattr(values[0], "request_id", "") or "")
            return _AuditRecord(
                _coerce_response(values[1]),
                values[2],
                request_id=request_id,
                request=_coerce_request_payload(values[0]),
            )
        if len(values) == 3:
            return _AuditRecord(
                _coerce_response(values[0]),
                values[1],
                hammer_verification=values[2],
            )
        if len(values) == 2:
            return _AuditRecord(_coerce_response(values[0]), values[1])
    if isinstance(item, Mapping):
        response = _coerce_response(
            item.get("response")
            or item.get("audit_response")
            or item.get("leanstral_response")
        )
        verification = (
            item.get("verification")
            or item.get("verification_result")
            or item.get("verifier_result")
            or item.get("result")
        )
        hammer_verification = (
            item.get("hammer_verification")
            or item.get("hammer_verification_report")
            or item.get("leanstral_hammer_verification")
            or item.get("hammer_report")
        )
        request_id = str(item.get("request_id", "")).strip()
        return _AuditRecord(
            response,
            verification,
            request_id=request_id,
            request=_coerce_request_payload(item.get("request") or {}),
            hammer_verification=hammer_verification,
        )
    response = _coerce_response(getattr(item, "response", None))
    verification = getattr(item, "verification", None) or getattr(item, "verification_result", None)
    request_id = str(getattr(item, "request_id", "") or "").strip()
    hammer_verification = (
        getattr(item, "hammer_verification", None)
        or getattr(item, "hammer_verification_report", None)
    )
    return _AuditRecord(
        response,
        verification,
        request_id=request_id,
        hammer_verification=hammer_verification,
    )


def _coerce_response(value: Any) -> Optional[LeanstralAuditResponse]:
    if isinstance(value, LeanstralAuditResponse):
        return value
    if isinstance(value, Mapping):
        return LeanstralAuditResponse.from_mapping(value)
    return None


def _coerce_request_payload(value: Any) -> Dict[str, Any]:
    if hasattr(value, "to_dict"):
        payload = value.to_dict()
        return dict(payload) if isinstance(payload, Mapping) else {}
    if isinstance(value, Mapping):
        return dict(value)
    return {}


def _verification_accepted(value: Any) -> bool:
    if isinstance(value, LeanstralAuditVerificationResult):
        return bool(value.accepted)
    if isinstance(value, Mapping):
        return bool(value.get("accepted", False)) or _verification_outcome(value) == "accepted"
    return bool(getattr(value, "accepted", False)) or _verification_outcome(value) == "accepted"


def _verification_outcome(value: Any) -> str:
    outcome = value.get("outcome", "") if isinstance(value, Mapping) else getattr(value, "outcome", "")
    if isinstance(outcome, LeanstralVerificationOutcome):
        return outcome.value
    return _normalize_record_status(outcome)


def _rejected_record_status(record: _AuditRecord) -> str:
    outcome = _verification_outcome(record.verification)
    if outcome in {
        LeanstralVerificationOutcome.UNSUPPORTED.value,
        LeanstralVerificationOutcome.TIMED_OUT.value,
    }:
        return outcome
    return LeanstralVerificationOutcome.REJECTED.value


def _normalize_record_status(value: Any) -> str:
    status = str(value or "").strip().lower().replace("_", "-")
    allowed = {item.value for item in LeanstralVerificationOutcome}
    if status in allowed:
        return status
    if status in {"timeout", "timedout"}:
        return LeanstralVerificationOutcome.TIMED_OUT.value
    if not status:
        return ""
    return LeanstralVerificationOutcome.REJECTED.value


def _verification_reasons(value: Any) -> Sequence[str]:
    reasons = value.get("reasons", ()) if isinstance(value, Mapping) else getattr(value, "reasons", ())
    return _dedupe_strings(str(reason) for reason in reasons or () if str(reason).strip())


def _verification_verified_by(value: Any) -> Sequence[str]:
    verified_by = (
        value.get("verified_by", ()) if isinstance(value, Mapping) else getattr(value, "verified_by", ())
    )
    return _dedupe_strings(str(name) for name in verified_by or () if str(name).strip())


def _hammer_payload(value: Any) -> Dict[str, Any]:
    if isinstance(value, LeanstralHammerVerificationReport):
        return value.to_dict()
    if hasattr(value, "to_dict"):
        payload = value.to_dict()
        return dict(payload) if isinstance(payload, Mapping) else {}
    if isinstance(value, Mapping):
        return dict(value)
    return {}


def _hammer_guidance_artifacts_from_value(
    value: Any,
    *,
    max_artifacts: int = 12,
) -> List[Dict[str, Any]]:
    payload = _hammer_payload(value)
    raw_artifacts: List[Mapping[str, Any]] = []
    for key in ("hammer_guidance_artifacts", "verified_guidance", "guidance_artifacts"):
        raw = payload.get(key)
        if isinstance(raw, Sequence) and not isinstance(raw, (str, bytes, bytearray)):
            raw_artifacts.extend(item for item in raw if isinstance(item, Mapping))
    for candidate in payload.get("candidate_results", []) or []:
        if not isinstance(candidate, Mapping):
            continue
        verified = candidate.get("verified_guidance")
        if isinstance(verified, Sequence) and not isinstance(verified, (str, bytes, bytearray)):
            raw_artifacts.extend(item for item in verified if isinstance(item, Mapping))
        hammer_report = candidate.get("hammer_report")
        if isinstance(hammer_report, Mapping):
            artifacts = hammer_report.get("artifacts")
            if isinstance(artifacts, Sequence) and not isinstance(artifacts, (str, bytes, bytearray)):
                raw_artifacts.extend(
                    item
                    for item in artifacts
                    if isinstance(item, Mapping) and bool(item.get("trusted"))
                )
    artifacts: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for item in raw_artifacts:
        artifact = _json_ready(dict(item))
        if not isinstance(artifact, Mapping):
            continue
        artifact = dict(artifact)
        digest = canonical_sha256(artifact)
        artifact.setdefault("artifact_sha256", digest)
        key = str(artifact.get("guidance_id") or digest)
        if key in seen:
            continue
        seen.add(key)
        artifacts.append(artifact)
        if len(artifacts) >= max_artifacts:
            break
    return artifacts


def _hammer_backend_health_from_value(value: Any) -> Dict[str, Any]:
    payload = _hammer_payload(value)
    direct = payload.get("hammer_backend_health") or payload.get("backend_health")
    if isinstance(direct, Mapping):
        return _json_ready(dict(direct))
    for candidate in payload.get("candidate_results", []) or []:
        if not isinstance(candidate, Mapping):
            continue
        hammer_report = candidate.get("hammer_report")
        if not isinstance(hammer_report, Mapping):
            continue
        metadata = hammer_report.get("metadata")
        if isinstance(metadata, Mapping) and isinstance(metadata.get("backend_health"), Mapping):
            return _json_ready(dict(metadata["backend_health"]))
    return {}


def _hammer_proof_status_from_value(value: Any) -> Dict[str, Any]:
    payload = _hammer_payload(value)
    if not payload:
        return {}
    candidate_results = [
        item for item in payload.get("candidate_results", []) or [] if isinstance(item, Mapping)
    ]
    proof_reports = [
        item.get("hammer_report")
        for item in candidate_results
        if isinstance(item.get("hammer_report"), Mapping)
    ]
    obligation_count = sum(int(report.get("obligation_count", 0) or 0) for report in proof_reports)
    proved_count = sum(int(report.get("proved_count", 0) or 0) for report in proof_reports)
    trusted_count = sum(int(report.get("trusted_count", 0) or 0) for report in proof_reports)
    return {
        "accepted": bool(payload.get("accepted")),
        "candidate_count": int(payload.get("candidate_count", len(candidate_results)) or 0),
        "obligation_count": obligation_count,
        "proved_count": proved_count,
        "proof_success_rate": round(proved_count / obligation_count, 12)
        if obligation_count
        else 0.0,
        "trusted": bool(payload.get("trusted")),
        "trusted_count": trusted_count,
        "trusted_success_rate": round(trusted_count / obligation_count, 12)
        if obligation_count
        else 0.0,
    }


def _hammer_reconstruction_status_from_value(value: Any) -> Dict[str, Any]:
    artifacts = _hammer_guidance_artifacts_from_value(value)
    statuses = _dedupe_strings(
        str(artifact.get("reconstruction_status") or "")
        for artifact in artifacts
        if str(artifact.get("reconstruction_status") or "").strip()
    )
    checked = sum(1 for artifact in artifacts if bool(artifact.get("proof_checked")))
    return {
        "proof_checked_count": checked,
        "reconstruction_statuses": list(statuses),
        "trusted_artifact_count": len(artifacts),
    }


def _hammer_codex_projection_from_artifacts(
    artifacts: Sequence[Mapping[str, Any]],
    *,
    fallback_reasons: Sequence[str] = (),
) -> Dict[str, Any]:
    if not artifacts:
        return {}
    return {
        "guidance_ids": _dedupe_strings(
            str(artifact.get("guidance_id") or "") for artifact in artifacts
        ),
        "projection_source": "hammer_verified_guidance",
        "proof_obligation_ids": _dedupe_strings(
            obligation_id
            for artifact in artifacts
            for obligation_id in _sequence_values(artifact.get("proof_obligation_ids"))
        ),
        "reasons": list(_dedupe_strings(fallback_reasons)),
        "target_components": _dedupe_strings(
            str(artifact.get("target_component") or artifact.get("legal_ir_view") or "")
            for artifact in artifacts
        ),
        "target_metrics": _dedupe_strings(
            metric
            for artifact in artifacts
            for metric in _sequence_values(artifact.get("target_metrics"))
        ),
        "trusted_guidance_count": len(artifacts),
    }


def _record_request_id(record: _AuditRecord) -> str:
    if record.request_id:
        return record.request_id
    response = record.response
    if response is not None and response.request_id:
        return response.request_id
    verification = record.verification
    request_id = (
        verification.get("request_id", "")
        if isinstance(verification, Mapping)
        else getattr(verification, "request_id", "")
    )
    return str(request_id or "").strip()


def _record_response_hash(record: _AuditRecord) -> str:
    verification = record.verification
    response_hash = (
        verification.get("response_hash", "")
        if isinstance(verification, Mapping)
        else getattr(verification, "response_hash", "")
    )
    if response_hash:
        return str(response_hash)
    if record.response is not None:
        return record.response.content_hash
    return ""


def _evidence_from_record(
    record: _AuditRecord,
    *,
    role: str,
    max_examples: int,
) -> LeanstralRuleGapEvidence:
    response = record.response
    if response is None:
        raise ValueError("evidence requires response")
    response_hash = _record_response_hash(record)
    payload = {
        "request_id": _record_request_id(record),
        "response_hash": response_hash,
        "role": role,
    }
    evidence_id = "leanstral-evidence-" + hashlib.sha256(
        json.dumps(payload, ensure_ascii=True, sort_keys=True).encode("utf-8")
    ).hexdigest()[:16]
    hammer_artifacts = _hammer_guidance_artifacts_from_value(record.hammer_verification)
    hammer_reasons = _verification_reasons(record.hammer_verification)
    return LeanstralRuleGapEvidence(
        evidence_id=evidence_id,
        role=role,
        request_id=_record_request_id(record),
        response_hash=response_hash,
        verification_outcome=_verification_outcome(record.verification),
        classification=response.classification,
        confidence=_finite_float(response.confidence),
        proof_obligation_ids=_dedupe_strings(response.proof_obligation_ids),
        affected_ir_families=_families(response),
        drafted_logic_candidates=tuple(
            _drafted_logic_candidates_from_response(
                response,
                audit_evidence_id=evidence_id,
            )
        ),
        hammer_guidance_artifacts=tuple(hammer_artifacts),
        hammer_backend_health=_hammer_backend_health_from_value(record.hammer_verification),
        hammer_proof_status=_hammer_proof_status_from_value(record.hammer_verification),
        hammer_reconstruction_status=_hammer_reconstruction_status_from_value(
            record.hammer_verification
        ),
        codex_projection=_hammer_codex_projection_from_artifacts(
            hammer_artifacts,
            fallback_reasons=hammer_reasons,
        ),
        examples=tuple(_examples_from_record(record)[:max_examples]),
        metric_attribution=_metric_attribution_from_record(record),
        reasons=_dedupe_strings(
            [
                *_verification_reasons(record.verification),
                *hammer_reasons,
            ]
        ),
        verified_by=_verification_verified_by(record.verification),
    )


def _drafted_logic_candidates_from_response(
    response: LeanstralAuditResponse,
    *,
    audit_evidence_id: str,
    max_candidates: int = 6,
) -> List[Dict[str, Any]]:
    candidates: List[Dict[str, Any]] = []
    seen: set[str] = set()
    allowed_obligations = set(_dedupe_strings(response.proof_obligation_ids))
    for item in response.drafted_logic_candidates or ():
        if not isinstance(item, Mapping):
            continue
        candidate_text = _bounded_string(item.get("candidate"), 240)
        if not candidate_text:
            continue
        proof_obligation_id = str(item.get("proof_obligation_id") or "").strip()
        if proof_obligation_id and proof_obligation_id not in allowed_obligations:
            continue
        if not proof_obligation_id and response.proof_obligation_ids:
            proof_obligation_id = str(response.proof_obligation_ids[0])
        payload: Dict[str, Any] = {
            "audit_evidence_id": audit_evidence_id,
            "candidate": candidate_text,
            "guidance_only": True,
            "intended_use": "guidance_only",
            "logic_family": _slug(
                str(item.get("logic_family") or item.get("family") or "legal_ir")
            )
            or "legal_ir",
            "request_id": response.request_id,
        }
        if proof_obligation_id:
            payload["proof_obligation_id"] = proof_obligation_id
        for key in (
            "compiler_surface",
            "evidence_id",
            "example_id",
            "expected_failure_mode",
            "schema_version",
            "source_copy_policy",
            "source_span_hash",
            "target_component",
            "target_metric",
            "target_view",
        ):
            text = _bounded_string(item.get(key), 140)
            if text:
                payload[key] = text
        if "source_copy_rejected" in item:
            raw_rejected = item.get("source_copy_rejected")
            payload["source_copy_rejected"] = (
                raw_rejected
                if isinstance(raw_rejected, bool)
                else str(raw_rejected).strip().lower() in {"1", "true", "yes", "y"}
            )
        for key in ("premise_hints", "proof_obligation_ids", "target_metrics"):
            values = _dedupe_strings(_sequence_values(item.get(key)))[:12]
            if values:
                payload[key] = values
        confidence = _finite_float(item.get("confidence"))
        if confidence:
            payload["confidence"] = confidence
        identity = json.dumps(
            {
                "candidate": payload.get("candidate"),
                "logic_family": payload.get("logic_family"),
                "proof_obligation_id": payload.get("proof_obligation_id"),
            },
            ensure_ascii=True,
            sort_keys=True,
        )
        if identity in seen:
            continue
        seen.add(identity)
        candidates.append(payload)
        if len(candidates) >= max(0, int(max_candidates)):
            break
    return candidates


def _rejected_audit(
    record: _AuditRecord,
    reasons: Sequence[str],
) -> LeanstralRejectedAudit:
    response = record.response
    material = {
        "request_id": _record_request_id(record),
        "response_hash": _record_response_hash(record),
        "reasons": list(reasons),
    }
    audit_id = "leanstral-rejected-" + hashlib.sha256(
        json.dumps(material, ensure_ascii=True, sort_keys=True).encode("utf-8")
    ).hexdigest()[:16]
    return LeanstralRejectedAudit(
        audit_id=audit_id,
        reasons=tuple(dict.fromkeys(str(reason) for reason in reasons if reason)),
        status=_rejected_record_status(record),
        request_id=_record_request_id(record),
        response_hash=_record_response_hash(record),
        verification_outcome=_verification_outcome(record.verification),
        classification=response.classification if response is not None else "",
        proposed_surfaces=tuple(
            dict(surface)
            for surface in (response.proposed_compiler_surface if response else ())
        ),
    )


def _examples_from_response(response: LeanstralAuditResponse) -> List[Dict[str, Any]]:
    examples: List[Dict[str, Any]] = []
    for role, payload in (
        ("counterexample", response.counterexample),
        ("witness", response.witness),
    ):
        if not isinstance(payload, Mapping):
            continue
        normalized = _json_ready(payload)
        normalized["example_role"] = role
        normalized.setdefault("example_hash", canonical_sha256(normalized))
        examples.append(normalized)
    return examples


def _examples_from_record(record: _AuditRecord) -> List[Dict[str, Any]]:
    response = record.response
    if response is None:
        return []
    examples = _examples_from_response(response)
    response_ids = _response_example_ids(response)
    for example in _request_referenced_examples(record):
        ids = {
            str(example.get("example_id") or "").strip(),
            str(example.get("sample_id") or "").strip(),
            str(example.get("evidence_id") or "").strip(),
        }
        if response_ids and not (response_ids & {value for value in ids if value}):
            continue
        payload = {"example_role": "request_reference", **dict(example)}
        payload.setdefault("example_hash", canonical_sha256(payload))
        examples.append(payload)
    return _dedupe_examples(examples)


def _request_referenced_examples(record: _AuditRecord) -> List[Dict[str, Any]]:
    evidence = dict(record.request or {}).get("evidence")
    if not isinstance(evidence, Mapping):
        return []
    explicit = [
        dict(item)
        for item in evidence.get("referenced_examples", []) or []
        if isinstance(item, Mapping)
    ]
    if explicit:
        return explicit
    packets: List[Dict[str, Any]] = []
    for packet in evidence.get("evidence_packets", []) or []:
        if not isinstance(packet, Mapping):
            continue
        sample_hashes = packet.get("sample_hashes")
        if not isinstance(sample_hashes, Mapping):
            sample_hashes = {}
        span_hashes = sample_hashes.get("source_span_hashes")
        packets.append(
            {
                "compiler_decompiler_metrics": dict(
                    packet.get("compiler_decompiler_metrics") or {}
                )
                if isinstance(packet.get("compiler_decompiler_metrics"), Mapping)
                else {},
                "evidence_id": str(packet.get("evidence_id") or ""),
                "expected_modal_ir_hash": str(sample_hashes.get("modal_ir_hash") or ""),
                "sample_id": str(sample_hashes.get("sample_id") or ""),
                "source_span_hashes": dict(span_hashes)
                if isinstance(span_hashes, Mapping)
                else {},
            }
        )
    return packets


def _response_example_ids(response: LeanstralAuditResponse) -> set[str]:
    values: set[str] = set()
    for payload in (response.counterexample, response.witness):
        if not isinstance(payload, Mapping):
            continue
        for key in ("evidence_id", "example_id", "sample_id", "id"):
            value = str(payload.get(key) or "").strip()
            if value:
                values.add(value)
    return values


def _metric_attribution_from_record(record: _AuditRecord) -> Dict[str, Any]:
    pre_patch_metrics: Dict[str, float] = {}
    evidence_ids: List[str] = []
    for example in _examples_from_record(record):
        evidence_id = str(example.get("evidence_id") or "").strip()
        if evidence_id:
            evidence_ids.append(evidence_id)
        pre_patch_metrics.update(
            _numeric_metric_map(
                example.get("compiler_decompiler_metrics")
                or example.get("pre_patch_metrics")
                or example.get("metric_baseline")
                or example.get("metrics")
                or {}
            )
        )
    response = record.response
    if response is not None:
        for payload in (response.counterexample, response.witness):
            if isinstance(payload, Mapping):
                pre_patch_metrics.update(
                    _numeric_metric_map(
                        payload.get("compiler_decompiler_metrics")
                        or payload.get("pre_patch_metrics")
                        or payload.get("metric_baseline")
                        or payload.get("metrics")
                        or {}
                    )
                )
    return {
        "evidence_ids": list(_dedupe_strings(evidence_ids)),
        "metric_deltas": {},
        "post_patch_metrics": {},
        "pre_patch_metrics": dict(sorted(pre_patch_metrics.items())),
        "schema_version": "legal-ir-leanstral-metric-attribution-v1",
        "source": "leanstral_audit_evidence",
        "status": "pre_patch_observed"
        if pre_patch_metrics
        else "missing_pre_patch_metrics",
    }


def _merge_metric_attributions(values: Iterable[Mapping[str, Any]]) -> Dict[str, Any]:
    pre_patch_metrics: Dict[str, float] = {}
    post_patch_metrics: Dict[str, float] = {}
    metric_deltas: Dict[str, float] = {}
    evidence_ids: List[str] = []
    statuses: List[str] = []
    for value in values:
        if not isinstance(value, Mapping):
            continue
        pre_patch_metrics.update(_numeric_metric_map(value.get("pre_patch_metrics") or {}))
        post_patch_metrics.update(_numeric_metric_map(value.get("post_patch_metrics") or {}))
        metric_deltas.update(_numeric_metric_map(value.get("metric_deltas") or {}))
        evidence_ids.extend(_sequence_values(value.get("evidence_ids")))
        status = str(value.get("status") or "").strip()
        if status:
            statuses.append(status)
    return {
        "evidence_ids": list(_dedupe_strings(evidence_ids)),
        "metric_deltas": dict(sorted(metric_deltas.items())),
        "post_patch_metrics": dict(sorted(post_patch_metrics.items())),
        "pre_patch_metrics": dict(sorted(pre_patch_metrics.items())),
        "schema_version": "legal-ir-leanstral-metric-attribution-v1",
        "source": "leanstral_rule_gap_report",
        "status": "pre_patch_observed"
        if pre_patch_metrics
        else (statuses[0] if statuses else "missing_pre_patch_metrics"),
    }


def _numeric_metric_map(value: Any, prefix: str = "") -> Dict[str, float]:
    metrics: Dict[str, float] = {}
    if isinstance(value, Mapping):
        for key, item in value.items():
            child_key = f"{prefix}.{key}" if prefix else str(key)
            metrics.update(_numeric_metric_map(item, child_key))
        return metrics
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for index, item in enumerate(value):
            child_key = f"{prefix}.{index}" if prefix else str(index)
            metrics.update(_numeric_metric_map(item, child_key))
        return metrics
    if not prefix:
        return metrics
    try:
        number = float(value)
    except (TypeError, ValueError):
        return metrics
    if math.isnan(number) or math.isinf(number):
        return metrics
    key = prefix.replace(" ", "_")
    if _looks_like_metric_key(key):
        metrics[key] = number
    return metrics


def _looks_like_metric_key(key: str) -> bool:
    lowered = key.lower()
    return any(
        token in lowered
        for token in (
            "ce",
            "cosine",
            "cross_entropy",
            "loss",
            "metric",
            "precision",
            "ratio",
            "recall",
            "similarity",
            "validation",
        )
    )


def _dedupe_evidence(
    evidence: Sequence[LeanstralRuleGapEvidence],
) -> List[LeanstralRuleGapEvidence]:
    by_id: Dict[str, LeanstralRuleGapEvidence] = {}
    for item in evidence:
        by_id[item.evidence_id] = item
    return [by_id[key] for key in sorted(by_id)]


def _dedupe_examples(examples: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    by_hash: Dict[str, Dict[str, Any]] = {}
    for example in examples:
        normalized = _json_ready(example)
        key = str(normalized.get("example_hash") or canonical_sha256(normalized))
        by_hash[key] = normalized
    return [by_hash[key] for key in sorted(by_hash)]


def _families(response: LeanstralAuditResponse) -> Sequence[str]:
    component_labels = {"compiler", "decoder", "decompiler", "encoder", "parser"}
    families = _dedupe_strings(
        str(family).strip().lower()
        for family in response.affected_ir_families
        if str(family).strip()
        and str(family).strip().lower() not in component_labels
    )
    return families or ("modal",)


def _rule_key(rule: Mapping[str, Any]) -> str:
    for key in ("rule_id", "id", "name", "semantic_rule_id"):
        value = str(rule.get(key, "")).strip()
        if value:
            return _slug(value)
    description = str(rule.get("description", rule.get("summary", ""))).strip()
    if not description:
        return ""
    return _slug(" ".join(description.split()[:12]))


def _rule_identity(
    response: LeanstralAuditResponse,
    *,
    surface: LeanstralOwnedSurface,
    families: Sequence[str],
) -> tuple[str, Sequence[str]]:
    """Return a stable semantic identity and optional family disambiguator.

    Model-written descriptions are frequently paraphrases of the same defect.
    Explicit rule IDs are already stable. For decompiler family-preservation
    findings, derive an identity from the expected source family so shifts to
    different wrong families aggregate into one evidence-rich compiler task.
    Other free-form findings retain their family set as a conservative guard.
    """
    rule = response.missing_semantic_rule
    for key in ("rule_id", "id", "name", "semantic_rule_id"):
        value = str(rule.get(key, "")).strip()
        if value:
            return _slug(value), ()

    description = str(rule.get("description", rule.get("summary", ""))).strip()
    normalized_description = description.lower()
    if (
        surface.component == "modal.ir_decompiler"
        and "preserv" in normalized_description
        and (
            "family" in normalized_description
            or "classification" in normalized_description
        )
    ):
        counterexample = response.counterexample
        expected = (
            str(counterexample.get("expected", ""))
            if isinstance(counterexample, Mapping)
            else ""
        ).lower()
        search_text = expected or normalized_description
        ignored = {"compiler", "decompiler", "modal", "unknown"}
        positioned = [
            (search_text.find(str(family).lower()), str(family).lower())
            for family in families
            if str(family).lower() not in ignored
            and search_text.find(str(family).lower()) >= 0
        ]
        if positioned:
            _position, source_family = min(positioned)
            return _slug(f"round_trip_family_preservation:{source_family}"), ()

    return _rule_key(rule), tuple(families)


def _gap_signature(rule_key: str, component: str, families: Sequence[str]) -> str:
    payload = {
        "component": component,
        "families": sorted(families),
        "rule_key": rule_key,
    }
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=True, sort_keys=True).encode("utf-8")
    ).hexdigest()


def _gap_title(response: LeanstralAuditResponse, surface: LeanstralOwnedSurface) -> str:
    rule = response.missing_semantic_rule
    label = str(rule.get("description") or rule.get("rule_id") or "Leanstral rule gap").strip()
    if len(label) > 120:
        label = label[:117].rstrip() + "..."
    return f"{label} ({surface.component})"


def _slug(value: str) -> str:
    slug = _TOKEN_PATTERN.sub("_", value.lower()).strip("_")
    return slug[:96]


def _bounded_string(value: Any, max_chars: int) -> str:
    text = str(value or "").strip()
    if len(text) <= max(0, int(max_chars)):
        return text
    return text[: max(0, int(max_chars))].rstrip()


def _finite_float(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    if math.isnan(number) or math.isinf(number):
        return 0.0
    return max(0.0, min(1.0, number))


def _dedupe_strings(values: Iterable[Any]) -> Sequence[str]:
    return tuple(dict.fromkeys(str(value).strip() for value in values if str(value).strip()))


def _json_ready(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _json_ready(val)
            for key, val in sorted(value.items(), key=lambda item: str(item[0]))
        }
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_json_ready(item) for item in value]
    if hasattr(value, "to_dict"):
        return _json_ready(value.to_dict())
    if hasattr(value, "__dataclass_fields__"):
        return _json_ready(asdict(value))
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


__all__ = [
    "LEANSTRAL_PATCH_FEEDBACK_REPORT_SCHEMA_VERSION",
    "LEANSTRAL_PATCH_OUTCOME_ACCEPTED_IMPROVEMENT",
    "LEANSTRAL_PATCH_OUTCOME_OPERATIONAL_FAILURE",
    "LEANSTRAL_PATCH_OUTCOME_QUALITY_REGRESSION",
    "LEANSTRAL_PATCH_OUTCOME_STALE_EVIDENCE",
    "LEANSTRAL_PATCH_OUTCOME_STATUSES",
    "LEANSTRAL_PATCH_OUTCOME_UNSUPPORTED_HYPOTHESIS",
    "LEANSTRAL_RULE_GAP_REPORT_SCHEMA_VERSION",
    "OWNED_LEANSTRAL_RULE_GAP_SURFACES",
    "LeanstralPatchFeedbackReport",
    "LeanstralPatchLineage",
    "LeanstralPatchOutcomeRecord",
    "LeanstralOwnedSurface",
    "LeanstralRejectedAudit",
    "LeanstralRuleGap",
    "LeanstralRuleGapEvidence",
    "LeanstralRuleGapReport",
    "LeanstralRuleGapReportConfig",
    "aggregate_verified_audits",
    "build_leanstral_rule_gap_report",
    "build_leanstral_patch_feedback_report",
    "classify_leanstral_patch_outcome",
    "leanstral_compiler_target_from_patch_record",
    "leanstral_patch_feedback_report_to_json",
    "leanstral_rule_gap_report_to_json",
]
