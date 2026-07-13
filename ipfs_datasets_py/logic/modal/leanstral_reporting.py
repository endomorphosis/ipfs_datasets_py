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
    LeanstralVerificationOutcome,
)


LEANSTRAL_RULE_GAP_REPORT_SCHEMA_VERSION = "legal-ir-leanstral-rule-gap-report-v1"

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
    examples: Sequence[Dict[str, Any]] = field(default_factory=tuple)
    reasons: Sequence[str] = field(default_factory=tuple)
    verified_by: Sequence[str] = field(default_factory=tuple)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "affected_ir_families": list(self.affected_ir_families),
            "classification": self.classification,
            "confidence": self.confidence,
            "evidence_id": self.evidence_id,
            "examples": [dict(example) for example in self.examples],
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
        rule_key = _rule_key(response.missing_semantic_rule)
        if not rule_key:
            rejected.append(_rejected_audit(record, ("missing_rule_key",)))
            continue
        families = _families(response)
        signature = _gap_signature(rule_key, surface.component, families)
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
    return {
        "allowed_paths": list(surface.allowed_paths),
        "affected_ir_families": list(families),
        "formal_validity_checks": list(surface.theorem_templates),
        "held_out_compiler_ir_metrics": list(surface.target_metrics),
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
    lowered = component.lower().replace("_", ".").replace("-", ".")
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
        "knowledge.graphs.neo4j.compat": "knowledge_graphs.neo4j_compat",
        "knowledge_graphs.neo4j_compat": "knowledge_graphs.neo4j_compat",
        "modal.frame.logic": "modal.frame_logic",
        "modal.frame_logic": "modal.frame_logic",
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
        if len(values) >= 3:
            request_id = str(getattr(values[0], "request_id", "") or "")
            return _AuditRecord(_coerce_response(values[1]), values[2], request_id=request_id)
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
        request_id = str(item.get("request_id", "")).strip()
        return _AuditRecord(response, verification, request_id=request_id)
    response = _coerce_response(getattr(item, "response", None))
    verification = getattr(item, "verification", None) or getattr(item, "verification_result", None)
    request_id = str(getattr(item, "request_id", "") or "").strip()
    return _AuditRecord(response, verification, request_id=request_id)


def _coerce_response(value: Any) -> Optional[LeanstralAuditResponse]:
    if isinstance(value, LeanstralAuditResponse):
        return value
    if isinstance(value, Mapping):
        return LeanstralAuditResponse.from_mapping(value)
    return None


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
        examples=tuple(_examples_from_response(response)[:max_examples]),
        reasons=_verification_reasons(record.verification),
        verified_by=_verification_verified_by(record.verification),
    )


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
    families = _dedupe_strings(
        str(family).strip().lower()
        for family in response.affected_ir_families
        if str(family).strip()
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
    "LEANSTRAL_RULE_GAP_REPORT_SCHEMA_VERSION",
    "OWNED_LEANSTRAL_RULE_GAP_SURFACES",
    "LeanstralOwnedSurface",
    "LeanstralRejectedAudit",
    "LeanstralRuleGap",
    "LeanstralRuleGapEvidence",
    "LeanstralRuleGapReport",
    "LeanstralRuleGapReportConfig",
    "aggregate_verified_audits",
    "build_leanstral_rule_gap_report",
    "leanstral_rule_gap_report_to_json",
]
