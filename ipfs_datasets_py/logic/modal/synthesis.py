"""Typed synthesis hints from adaptive modal autoencoder introspection.

The adaptive layer is allowed to point at friction, not to rewrite law.  This
module converts autoencoder introspection evidence into explicit deterministic
compiler/decompiler/frame-logic work items that can be reviewed, tested, and
implemented as normal typed rules.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Sequence

from ipfs_datasets_py.optimizers.logic_theorem_optimizer.frame_bm25_selector import (
    frame_ontology_feature_keys,
)


@dataclass(frozen=True)
class ModalProgramSynthesisHint:
    """A reviewable proposal for deterministic modal compiler work."""

    hint_id: str
    action: str
    target_component: str
    rationale: str
    priority: float
    evidence: Dict[str, Any] = field(default_factory=dict)
    status: str = "proposed"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ModalResidualRepairRoute:
    """Deterministic route from a stable autoencoder residual to repair code."""

    action: str
    target_component: str
    rationale: str
    priority: float = 0.05


RESIDUAL_REPAIR_ROUTES: Dict[str, ModalResidualRepairRoute] = {
    "cross_entropy_loss": ModalResidualRepairRoute(
        action="refine_modal_family_cue_rules",
        target_component="modal.compiler.registry",
        rationale="Cross-entropy residuals indicate modal-family cue or registry ambiguity.",
        priority=0.5,
    ),
    "cosine_loss": ModalResidualRepairRoute(
        action="improve_encoder_decoder_reconstruction",
        target_component="modal.autoencoder",
        rationale="Cosine residuals indicate the learned embedding head is not preserving reusable compiler/decompiler features.",
        priority=0.5,
    ),
    "reconstruction_loss": ModalResidualRepairRoute(
        action="refine_typed_ir_or_decompiler_slots",
        target_component="modal.ir_decompiler",
        rationale="Reconstruction residuals indicate typed IR/decompiler slots are losing source semantics.",
        priority=0.5,
    ),
    "source_decompiled_text_embedding_cosine_loss": ModalResidualRepairRoute(
        action="refine_semantic_decompiler_reconstruction",
        target_component="modal.ir_decompiler",
        rationale=(
            "Source/decompiled text cosine residuals indicate the deterministic "
            "IR decoder is not reconstructing source semantics from typed slots."
        ),
        priority=0.65,
    ),
    "source_decompiled_text_token_loss": ModalResidualRepairRoute(
        action="refine_semantic_decompiler_reconstruction",
        target_component="modal.ir_decompiler",
        rationale=(
            "Source/decompiled token residuals indicate the deterministic IR "
            "decoder is missing source legal text structure."
        ),
        priority=0.55,
    ),
    "legal_ir_view_cross_entropy_loss": ModalResidualRepairRoute(
        action="repair_multiview_legal_ir_loss",
        target_component="bridge.contracts",
        rationale="LegalIR view residuals indicate canonical multiview bridge alignment needs repair.",
        priority=0.5,
    ),
    "legal_ir_multiview_proof_failure_ratio": ModalResidualRepairRoute(
        action="repair_multiview_legal_ir_prover_gate",
        target_component="external_provers.router",
        rationale="Proof-gate residuals indicate external theorem prover routing needs repair.",
        priority=0.5,
    ),
    "legal_ir_multiview_graph_failure_penalty": ModalResidualRepairRoute(
        action="repair_multiview_legal_ir_graph_projection",
        target_component="knowledge_graphs.neo4j_compat",
        rationale="Graph residuals indicate Neo4j-compatible LegalIR projection needs repair.",
        priority=0.5,
    ),
    "deontic_decoder_slot_loss": ModalResidualRepairRoute(
        action="repair_deontic_bridge_quality_gate",
        target_component="deontic.ir",
        rationale="Deontic slot residuals indicate LegalNormIR bridge reconstruction needs repair.",
        priority=0.5,
    ),
}


def route_autoencoder_residual(
    loss_name: str,
    *,
    focus: Sequence[str] = (),
) -> ModalResidualRepairRoute | None:
    """Return the deterministic code-repair route for a persistent residual."""
    normalized = str(loss_name or "").strip()
    if normalized in RESIDUAL_REPAIR_ROUTES:
        return RESIDUAL_REPAIR_ROUTES[normalized]
    focus_set = {str(item) for item in focus}
    if "repair_deontic_bridge_quality_gate" in focus_set:
        return RESIDUAL_REPAIR_ROUTES["deontic_decoder_slot_loss"]
    if "repair_multiview_legal_ir_graph_projection" in focus_set:
        return RESIDUAL_REPAIR_ROUTES["legal_ir_multiview_graph_failure_penalty"]
    if "repair_external_prover_router" in focus_set:
        return RESIDUAL_REPAIR_ROUTES["legal_ir_multiview_proof_failure_ratio"]
    return None


def residual_signature_for_hint(hint: ModalProgramSynthesisHint) -> str:
    """Return a stable signature for clustering repeated residual repair hints."""
    evidence = dict(hint.evidence or {})
    payload = {
        "action": hint.action,
        "bridge_failure_name": evidence.get("bridge_failure_name")
        or evidence.get("loss_name"),
        "component_gap": evidence.get("primary_legal_ir_component_gap"),
        "family_pair": [
            evidence.get("predicted_family"),
            evidence.get("target_family"),
        ],
        "frame_features": sorted(map(str, evidence.get("frame_features", []) or []))[:8],
        "pipeline_stage": evidence.get("primary_pipeline_stage"),
        "pipeline_stage_focus": sorted(
            map(str, evidence.get("pipeline_stage_focus", []) or [])
        )[:8],
        "target_file_lane": evidence.get("target_file_lane")
        or _target_file_lane(hint.target_component, hint.action),
        "target_component": hint.target_component,
        "target_view": evidence.get("target_view"),
        "predicted_view": evidence.get("predicted_view"),
        "underrepresented_components": sorted(
            map(str, evidence.get("legal_ir_underrepresented_components", []) or [])
        )[:8],
        "component_gaps": _top_component_gap_items(
            evidence.get("legal_ir_component_gaps", {}),
        ),
        "top_embedding_features": sorted(
            map(str, evidence.get("top_embedding_features", []) or [])
        )[:8],
        "top_family_features": sorted(
            map(str, evidence.get("top_family_features", []) or [])
        )[:8],
        "top_predicted_views": sorted(
            map(str, evidence.get("top_predicted_views", []) or [])
        )[:8],
        "top_target_views": sorted(map(str, evidence.get("top_target_views", []) or []))[:8],
    }
    digest = hashlib.sha256(
        json.dumps(payload, ensure_ascii=True, sort_keys=True).encode("utf-8")
    ).hexdigest()[:16]
    return f"residual-{digest}"


def synthesis_hints_from_autoencoder_introspection(
    introspection: Mapping[str, Any],
) -> List[ModalProgramSynthesisHint]:
    """Convert one introspection record into typed synthesis hints."""
    sample_id = str(introspection.get("sample_id") or "")
    focus = [str(value) for value in introspection.get("synthesis_focus", [])]
    legal_ir_losses = dict(introspection.get("legal_ir_losses") or {})
    hints: List[ModalProgramSynthesisHint] = []
    routed_loss_names = [
        "cross_entropy_loss",
        "cosine_loss",
        "reconstruction_loss",
        "source_decompiled_text_embedding_cosine_loss",
        "source_decompiled_text_token_loss",
        "legal_ir_view_cross_entropy_loss",
        "legal_ir_multiview_proof_failure_ratio",
        "legal_ir_multiview_graph_failure_penalty",
        "deontic_decoder_slot_loss",
    ]

    for loss_name in routed_loss_names:
        value = introspection.get(loss_name)
        if value in (None, ""):
            value = legal_ir_losses.get(loss_name)
        if value in (None, "", 0, 0.0):
            continue
        if (
            loss_name == "legal_ir_view_cross_entropy_loss"
            and _legal_ir_specific_focus_items(focus)
        ):
            continue
        route = route_autoencoder_residual(loss_name, focus=focus)
        if route is None:
            continue
        target_distribution = dict(introspection.get("legal_ir_view_distribution") or {})
        predicted_distribution = dict(
            introspection.get("legal_ir_predicted_view_distribution") or {}
        )
        component_gaps = dict(introspection.get("legal_ir_component_gaps") or {})
        pipeline_evidence = _pipeline_evidence(introspection)
        primary_view = _primary_view_for_component(
            route.target_component,
            target_distribution,
            component_gaps,
        )
        hints.append(
            _hint(
                sample_id,
                action=route.action,
                target_component=route.target_component,
                rationale=route.rationale,
                priority=max(route.priority, float(value or 0.0)),
                evidence={
                    "loss_name": loss_name,
                    "loss_value": value,
                    **pipeline_evidence,
                    "source_decompiled_text_embedding_cosine_loss": introspection.get(
                        "source_decompiled_text_embedding_cosine_loss"
                    ),
                    "source_decompiled_text_token_loss": introspection.get(
                        "source_decompiled_text_token_loss"
                    ),
                    "bridge_failure_name": _bridge_failure_name_for_route(
                        route.action,
                        route.target_component,
                        loss_name=loss_name,
                    ),
                    "predicted_family": introspection.get("predicted_family"),
                    "target_family": introspection.get("target_family"),
                    "target_file_lane": _target_file_lane(
                        route.target_component,
                        route.action,
                    ),
                    "top_embedding_features": _feature_names(
                        introspection.get("top_embedding_contributions", [])
                    ),
                    "top_family_features": _feature_names(
                        introspection.get("top_family_contributions", [])
                    ),
                    "legal_ir_component_gaps": dict(
                        introspection.get("legal_ir_component_gaps") or {}
                    ),
                    "legal_ir_underrepresented_components": list(
                        introspection.get("legal_ir_underrepresented_components") or []
                    ),
                    "predicted_view": _primary_view_for_component(
                        route.target_component,
                        predicted_distribution,
                        component_gaps,
                    ),
                    "primary_legal_ir_component_gap": _component_gap_value(
                        primary_view,
                        component_gaps,
                    ),
                    "target_view": primary_view,
                    "top_predicted_views": _top_distribution_names(predicted_distribution),
                    "top_target_views": _top_distribution_names(target_distribution),
                },
            )
        )

    if "add_deterministic_parser_rule" in focus:
        hints.append(
            _hint(
                sample_id,
                action="add_deterministic_parser_rule",
                target_component="modal.compiler",
                rationale="The deterministic compiler produced no modal formulas for this sample.",
                priority=1.0,
                evidence={
                    **_pipeline_evidence(introspection),
                    "target_family": introspection.get("target_family"),
                    "predicted_family": introspection.get("predicted_family"),
                    "target_file_lane": _target_file_lane(
                        "modal.compiler",
                        "add_deterministic_parser_rule",
                    ),
                },
            )
        )

    if "refine_modal_family_cue_rules" in focus:
        hints.append(
            _hint(
                sample_id,
                action="refine_modal_family_cue_rules",
                target_component="modal.compiler.registry",
                rationale="Adaptive family evidence disagrees with, or is weak for, the typed modal family.",
                priority=_priority_from_probability_gap(introspection),
                evidence={
                    **_pipeline_evidence(introspection),
                    "family_margin": introspection.get("family_margin"),
                    "predicted_family": introspection.get("predicted_family"),
                    "target_family": introspection.get("target_family"),
                    "target_file_lane": _target_file_lane(
                        "modal.compiler.registry",
                        "refine_modal_family_cue_rules",
                    ),
                    "target_probability": introspection.get("target_probability"),
                    "top_family_features": _feature_names(
                        introspection.get("top_family_contributions", [])
                    ),
                },
            )
        )

    top_embedding_features = _feature_names(
        introspection.get("top_embedding_contributions", [])
    )
    if "refine_typed_ir_or_decompiler_slots" in focus or top_embedding_features:
        hints.append(
            _hint(
                sample_id,
                action="refine_typed_ir_or_decompiler_slots",
                target_component="modal.ir_decompiler",
                rationale="Embedding residuals point to information not well represented by the typed IR/decompiler.",
                priority=max(
                    float(introspection.get("reconstruction_loss") or 0.0),
                    float(introspection.get("cosine_loss") or 0.0),
                    float(
                        introspection.get(
                            "source_decompiled_text_embedding_cosine_loss",
                        )
                        or 0.0
                    ),
                    float(introspection.get("source_decompiled_text_token_loss") or 0.0),
                    0.01 if top_embedding_features else 0.0,
                ),
                evidence={
                    **_pipeline_evidence(introspection),
                    "cosine_similarity": introspection.get("cosine_similarity"),
                    "cosine_loss": introspection.get("cosine_loss"),
                    "reconstruction_loss": introspection.get("reconstruction_loss"),
                    "target_file_lane": _target_file_lane(
                        "modal.ir_decompiler",
                        "refine_typed_ir_or_decompiler_slots",
                    ),
                    "top_embedding_features": top_embedding_features,
                },
            )
        )

    if "repair_multiview_legal_ir_loss" in focus:
        target_distribution = dict(
            introspection.get("legal_ir_view_distribution") or {}
        )
        predicted_distribution = dict(
            introspection.get("legal_ir_predicted_view_distribution") or {}
        )
        generic_priority = max(
            0.05,
            float(introspection.get("legal_ir_view_cross_entropy_loss") or 0.0),
        )
        generic_bridge_priority_backoff = bool(_legal_ir_specific_focus_items(focus))
        if generic_bridge_priority_backoff:
            generic_priority = max(0.05, generic_priority * 0.35)
        primary_view = _primary_view_for_component(
            "bridge.contracts",
            target_distribution,
            introspection.get("legal_ir_component_gaps") or {},
        )
        hints.append(
            _hint(
                sample_id,
                action="repair_multiview_legal_ir_loss",
                target_component="bridge.contracts",
                rationale="Adaptive LegalIR evidence shows the compiler/decompiler view distribution is not aligned with the canonical multiview target.",
                priority=generic_priority,
                evidence={
                    **_pipeline_evidence(introspection),
                    "generic_bridge_priority_backoff": generic_bridge_priority_backoff,
                    "legal_ir_predicted_view_distribution": predicted_distribution,
                    "legal_ir_component_gaps": dict(
                        introspection.get("legal_ir_component_gaps") or {}
                    ),
                    "bridge_failure_name": "legal_ir_view_cross_entropy_loss",
                    "legal_ir_underrepresented_components": list(
                        introspection.get("legal_ir_underrepresented_components") or []
                    ),
                    "legal_ir_view_cross_entropy_loss": introspection.get(
                        "legal_ir_view_cross_entropy_loss"
                    ),
                    "legal_ir_view_distribution": target_distribution,
                    "predicted_view": _primary_view_for_component(
                        "bridge.contracts",
                        predicted_distribution,
                        introspection.get("legal_ir_component_gaps") or {},
                    ),
                    "primary_legal_ir_component_gap": _component_gap_value(
                        primary_view,
                        introspection.get("legal_ir_component_gaps") or {},
                    ),
                    "target_file_lane": _target_file_lane(
                        "bridge.contracts",
                        "repair_multiview_legal_ir_loss",
                    ),
                    "target_view": primary_view,
                    "top_predicted_views": _top_distribution_names(
                        predicted_distribution,
                    ),
                    "top_target_views": _top_distribution_names(
                        target_distribution,
                    ),
                },
            )
        )

    if "repair_deontic_bridge_quality_gate" in focus:
        hints.append(
            _logic_view_hint(
                sample_id,
                introspection,
                action="repair_deontic_bridge_quality_gate",
                target_component="deontic.ir",
                rationale="The canonical multiview LegalIR target includes deontic structure that the adaptive view model cannot yet reconstruct confidently.",
            )
        )

    if "repair_tdfol_bridge_parse" in focus:
        hints.append(
            _logic_view_hint(
                sample_id,
                introspection,
                action="repair_tdfol_bridge_parse",
                target_component="TDFOL.prover",
                rationale="The canonical LegalIR target includes TDFOL proof-obligation views that the adaptive view model cannot yet reconstruct confidently.",
            )
        )

    if "repair_cec_dcec_bridge" in focus:
        hints.append(
            _logic_view_hint(
                sample_id,
                introspection,
                action="repair_cec_dcec_bridge",
                target_component="CEC.native",
                rationale="The canonical LegalIR target includes CEC/DCEC event-calculus views that the adaptive view model cannot yet reconstruct confidently.",
            )
        )

    if "repair_external_prover_router" in focus:
        hints.append(
            _logic_view_hint(
                sample_id,
                introspection,
                action="repair_external_prover_router",
                target_component="external_provers.router",
                rationale="The canonical LegalIR target includes external prover-router views that the adaptive view model cannot yet reconstruct confidently.",
            )
        )

    if "repair_multiview_legal_ir_graph_projection" in focus:
        hints.append(
            _logic_view_hint(
                sample_id,
                introspection,
                action="repair_multiview_legal_ir_graph_projection",
                target_component="knowledge_graphs.neo4j_compat",
                rationale="The canonical LegalIR target includes graph projection views that need better alignment with frame-logic IR.",
            )
        )

    if "repair_flogic_ontology_constraints" in focus:
        hints.append(
            _logic_view_hint(
                sample_id,
                introspection,
                action="repair_flogic_ontology_constraints",
                target_component="modal.frame_logic",
                rationale="The canonical LegalIR target includes frame-logic views that need stronger ontology constraints.",
            )
        )

    if "repair_zkp_attestation_bridge" in focus:
        hints.append(
            _logic_view_hint(
                sample_id,
                introspection,
                action="repair_zkp_attestation_bridge",
                target_component="zkp.circuits",
                rationale="The canonical LegalIR target includes ZKP proof-attestation views that the adaptive view model cannot yet reconstruct confidently.",
            )
        )

    if "audit_frame_logic_terms" in focus:
        frame_features = _frame_features(introspection)
        hints.append(
            _hint(
                sample_id,
                action="audit_frame_logic_terms",
                target_component="modal.frame_logic",
                rationale="Frame-linked features influenced reconstruction or family scoring and should be audited as ontology terms.",
                priority=max(0.05, float(introspection.get("reconstruction_loss") or 0.0)),
                evidence={
                    **_pipeline_evidence(introspection),
                    "frame_features": frame_features,
                    "target_file_lane": _target_file_lane(
                        "modal.frame_logic",
                        "audit_frame_logic_terms",
                    ),
                    "top_family_features": _feature_names(
                        introspection.get("top_family_contributions", [])
                    ),
                },
            )
        )

    if _family_margin(introspection) < 0.15:
        hints.append(
            _hint(
                sample_id,
                action="add_or_review_modal_ambiguity_policy",
                target_component="modal.compiler.ambiguity",
                rationale="The adaptive family margin is small, so the compiler should expose an explicit ambiguity.",
                priority=0.15 - _family_margin(introspection),
                evidence={
                    **_pipeline_evidence(introspection),
                    "family_margin": introspection.get("family_margin"),
                    "predicted_family": introspection.get("predicted_family"),
                    "target_family": introspection.get("target_family"),
                    "target_file_lane": _target_file_lane(
                        "modal.compiler.ambiguity",
                        "add_or_review_modal_ambiguity_policy",
                    ),
                },
            )
        )

    return sorted(hints, key=lambda hint: (-hint.priority, hint.hint_id))


def synthesis_hints_from_autoencoder_introspections(
    introspections: Iterable[Mapping[str, Any]],
) -> List[ModalProgramSynthesisHint]:
    """Convert multiple introspection records into deterministic hints."""
    hints: Dict[str, ModalProgramSynthesisHint] = {}
    for introspection in introspections:
        for hint in synthesis_hints_from_autoencoder_introspection(introspection):
            hints[hint.hint_id] = hint
    return sorted(hints.values(), key=lambda hint: (-hint.priority, hint.hint_id))


def synthesis_hints_from_leanstral_rule_gap_report(
    report: Any,
) -> List[ModalProgramSynthesisHint]:
    """Convert a Leanstral rule-gap report into typed synthesis hints."""

    gaps = getattr(report, "gaps", None)
    if gaps is None and isinstance(report, Mapping):
        gaps = report.get("gaps", ())
    return synthesis_hints_from_leanstral_rule_gaps(gaps or ())


def synthesis_hints_from_leanstral_rule_gaps(
    gaps: Iterable[Any],
) -> List[ModalProgramSynthesisHint]:
    """Convert accepted rule gaps into existing program-synthesis hint records."""

    hints: Dict[str, ModalProgramSynthesisHint] = {}
    for gap in gaps:
        gap_data = gap.to_dict() if hasattr(gap, "to_dict") else dict(gap or {})
        target_surface = gap_data.get("target_surface") or {}
        if not isinstance(target_surface, Mapping):
            target_surface = {}
        target_component = str(
            gap_data.get("target_component")
            or target_surface.get("component", "")
        ).strip()
        action = str(
            gap_data.get("action") or target_surface.get("action", "")
        ).strip()
        if not action or not target_component:
            continue
        validation_set = dict(gap_data.get("validation_set") or {})
        support = _mapping_items(gap_data.get("supporting_evidence") or [])
        conflicts = _mapping_items(gap_data.get("conflicting_evidence") or [])
        surface = dict(target_surface)
        gap_id = str(gap_data.get("gap_id") or "").strip()
        normalized_rule_key = str(gap_data.get("normalized_rule_key") or "").strip()
        proof_obligation_ids = _dedupe_string_values(
            [
                *[
                    value
                    for evidence in support
                    for value in list(evidence.get("proof_obligation_ids") or [])
                ],
                *list(validation_set.get("proof_obligation_ids") or []),
            ]
        )
        theorem_templates = _dedupe_string_values(
            surface.get("theorem_templates")
            or validation_set.get("formal_validity_checks")
            or ()
        )
        allowed_paths = _dedupe_string_values(
            surface.get("allowed_paths")
            or validation_set.get("allowed_paths")
            or ()
        )
        target_metrics = _dedupe_string_values(
            surface.get("target_metrics")
            or validation_set.get("held_out_compiler_ir_metrics")
            or ()
        )
        metric_attribution = dict(validation_set.get("metric_attribution") or {})
        counterexamples = _rule_gap_counterexamples(
            support,
            conflicts,
            validation_set=validation_set,
        )
        drafted_logic_candidates = _rule_gap_drafted_logic_candidates(support)
        evidence_ids = _dedupe_string_values(
            evidence.get("evidence_id") for evidence in support
        )
        audit_request_ids = _dedupe_string_values(
            evidence.get("request_id") for evidence in support
        )
        audit_response_hashes = _dedupe_string_values(
            evidence.get("response_hash") for evidence in support
        )
        supporting_verification_outcomes = _dedupe_string_values(
            evidence.get("verification_outcome") for evidence in support
        )
        supporting_verified_by = _dedupe_string_values(
            checker
            for evidence in support
            for checker in list(evidence.get("verified_by") or [])
        )
        conflicting_evidence_ids = _dedupe_string_values(
            evidence.get("evidence_id") for evidence in conflicts
        )
        proof_ids = _dedupe_string_values([*proof_obligation_ids, *theorem_templates])
        leanstral_verified = bool(support) and all(
            str(evidence.get("verification_outcome") or "").strip() == "accepted"
            for evidence in support
        )
        dedupe_key = _leanstral_rule_gap_dedup_key(
            gap_id=gap_id,
            normalized_rule_key=normalized_rule_key,
            target_component=target_component,
            action=action,
        )
        evidence = {
            "allowed_paths": allowed_paths,
            "audit_request_ids": audit_request_ids,
            "audit_response_hashes": audit_response_hashes,
            "counterexamples": counterexamples,
            "conflicting_evidence_count": len(conflicts),
            "conflicting_evidence_ids": conflicting_evidence_ids,
            "dedupe_key": dedupe_key,
            "evidence_ids": evidence_ids,
            "gap_id": gap_id,
            "leanstral_dedup_key": dedupe_key,
            "leanstral_drafted_logic_candidates": drafted_logic_candidates,
            "leanstral_guidance_mode": "draft_logic_guidance_only",
            "leanstral_report_only": False,
            "leanstral_source": "verified_rule_gap_report",
            "leanstral_verified": leanstral_verified,
            "metric_attribution": metric_attribution,
            "missing_semantic_rule": dict(gap_data.get("missing_semantic_rule") or {}),
            "normalized_rule_key": normalized_rule_key,
            "post_patch_metrics": dict(metric_attribution.get("post_patch_metrics") or {}),
            "pre_patch_metrics": dict(metric_attribution.get("pre_patch_metrics") or {}),
            "proof_ids": proof_ids,
            "proof_obligation_ids": proof_obligation_ids,
            "spec_id": gap_id or normalized_rule_key,
            "spec_ids": _dedupe_string_values([gap_id, normalized_rule_key]),
            "supporting_evidence_count": len(support),
            "supporting_evidence_ids": evidence_ids,
            "supporting_examples": _rule_gap_examples(support),
            "supporting_verified_by": supporting_verified_by,
            "supporting_verification_outcomes": supporting_verification_outcomes,
            "validation_set": validation_set,
            "mutation_cases": _dedupe_string_values(
                surface.get("mutation_cases")
                or validation_set.get("mutation_cases")
                or ()
            ),
            "target_file_lane": surface.get("target_file_lane")
            or validation_set.get("target_file_lane")
            or _target_file_lane(target_component, action),
            "target_metrics": target_metrics,
            "theorem_templates": theorem_templates,
        }
        hint = _hint(
            gap_id,
            action=action,
            target_component=target_component,
            rationale=str(gap_data.get("title") or "Verified Leanstral rule gap."),
            priority=float(gap_data.get("priority") or 0.0),
            evidence=evidence,
        )
        hints[hint.hint_id] = hint
    return sorted(hints.values(), key=lambda hint: (-hint.priority, hint.hint_id))


def synthesis_hints_from_leanstral_guidance(
    guidance: Any,
    *,
    require_trusted: bool = True,
) -> List[ModalProgramSynthesisHint]:
    """Convert direct Leanstral draft guidance into program-synthesis hints."""

    hints: Dict[str, ModalProgramSynthesisHint] = {}
    for item in _leanstral_guidance_items(guidance):
        trusted = bool(item.get("trusted") or item.get("accepted"))
        if require_trusted and not trusted:
            continue
        action = str(item.get("action") or "").strip()
        target_component = str(item.get("target_component") or "").strip()
        if not action or not target_component:
            continue
        guidance_id = str(item.get("guidance_id") or item.get("task_id") or "").strip()
        dedupe_key = guidance_id or (
            "leanstral-guidance:"
            + hashlib.sha256(
                json.dumps(item, ensure_ascii=True, sort_keys=True, default=str).encode(
                    "utf-8"
                )
            ).hexdigest()[:20]
        )
        proof_obligation_ids = _dedupe_string_values(
            item.get("proof_obligation_ids") or ()
        )
        theorem_templates = _dedupe_string_values(item.get("theorem_templates") or ())
        target_metrics = _dedupe_string_values(item.get("target_metrics") or ())
        drafted_logic_candidates = _rule_gap_drafted_logic_candidates(
            [{"drafted_logic_candidates": item.get("drafted_logic_candidates") or ()}]
        )
        metric_attribution = {
            "pre_patch_metrics": dict(item.get("legal_ir_view_metrics") or {}),
            "schema_version": "legal-ir-leanstral-metric-attribution-v1",
            "source": "leanstral_direct_guidance",
            "status": "pre_patch_observed"
            if item.get("legal_ir_view_metrics")
            else "missing_pre_patch_metrics",
            "target_metrics": list(target_metrics),
        }
        evidence = {
            "allowed_paths": _dedupe_string_values(item.get("allowed_paths") or ()),
            "audit_request_ids": [],
            "audit_response_hashes": [],
            "dedupe_key": dedupe_key,
            "evidence_ids": _dedupe_string_values([guidance_id]),
            "gap_id": guidance_id,
            "leanstral_dedup_key": dedupe_key,
            "leanstral_drafted_logic_candidates": drafted_logic_candidates,
            "leanstral_guidance_mode": str(
                item.get("guidance_mode") or "draft_logic_guidance_only"
            ),
            "leanstral_report_only": not trusted,
            "leanstral_source": str(item.get("source") or "leanstral_shadow_proof"),
            "leanstral_verified": trusted,
            "metric_attribution": metric_attribution,
            "missing_semantic_rule": {
                "description": "Leanstral drafted logic guidance for deterministic IR repair.",
                "source_guidance_id": guidance_id,
            },
            "mutation_cases": _dedupe_string_values(item.get("mutation_cases") or ()),
            "normalized_rule_key": dedupe_key,
            "post_patch_metrics": {},
            "pre_patch_metrics": dict(metric_attribution["pre_patch_metrics"]),
            "proof_ids": _dedupe_string_values(
                [*proof_obligation_ids, *theorem_templates]
            ),
            "proof_obligation_ids": proof_obligation_ids,
            "sample_id": str(item.get("sample_id") or ""),
            "spec_id": guidance_id,
            "spec_ids": _dedupe_string_values([guidance_id, dedupe_key]),
            "supporting_evidence_count": 1 if trusted else 0,
            "supporting_examples": [],
            "supporting_verified_by": ["leanstral_shadow_validation"] if trusted else [],
            "supporting_verification_outcomes": ["accepted"]
            if trusted
            else _dedupe_string_values(item.get("validation_reasons") or ()),
            "target_component": target_component,
            "target_file_lane": _target_file_lane(target_component, action),
            "target_metrics": target_metrics,
            "theorem_templates": theorem_templates,
            "validation_set": {
                "allowed_paths": _dedupe_string_values(item.get("allowed_paths") or ()),
                "formal_validity_checks": theorem_templates,
                "held_out_compiler_ir_metrics": target_metrics,
                "mutation_cases": _dedupe_string_values(item.get("mutation_cases") or ()),
                "proof_obligation_ids": proof_obligation_ids,
                "target_file_lane": _target_file_lane(target_component, action),
            },
        }
        priority = max(
            0.05 if trusted else 0.0,
            max(
                (
                    float(feature.get("score") or 0.0)
                    for feature in _mapping_items(item.get("ranked_guidance_features") or ())
                ),
                default=0.0,
            ),
        )
        rationale = (
            "Use verified Leanstral-drafted logic as guidance for deterministic "
            "compiler/decompiler repair."
        )
        hint = _hint(
            str(item.get("sample_id") or guidance_id),
            action=action,
            target_component=target_component,
            rationale=rationale,
            priority=priority,
            evidence=evidence,
        )
        hints[hint.hint_id] = hint
    return sorted(hints.values(), key=lambda hint: (-hint.priority, hint.hint_id))


def _hint(
    sample_id: str,
    *,
    action: str,
    target_component: str,
    rationale: str,
    priority: float,
    evidence: Mapping[str, Any],
) -> ModalProgramSynthesisHint:
    evidence_dict = dict(evidence)
    evidence_dict.setdefault("sample_id", sample_id)
    payload = {
        "action": action,
        "evidence": evidence_dict,
        "sample_id": sample_id,
        "target_component": target_component,
    }
    digest = hashlib.sha256(
        json.dumps(payload, ensure_ascii=True, sort_keys=True).encode("utf-8")
    ).hexdigest()[:16]
    return ModalProgramSynthesisHint(
        hint_id=f"modal-synthesis-{digest}",
        action=action,
        target_component=target_component,
        rationale=rationale,
        priority=round(max(0.0, float(priority)), 12),
        evidence=evidence_dict,
    )


def _rule_gap_examples(
    evidence_items: Sequence[Mapping[str, Any]],
) -> List[Dict[str, Any]]:
    examples: List[Dict[str, Any]] = []
    for evidence in evidence_items:
        for example in evidence.get("examples", []) or []:
            if isinstance(example, Mapping):
                examples.append(dict(example))
    return examples[:8]


def _rule_gap_drafted_logic_candidates(
    evidence_items: Sequence[Mapping[str, Any]],
) -> List[Dict[str, Any]]:
    candidates: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for evidence in evidence_items:
        for candidate in evidence.get("drafted_logic_candidates", []) or []:
            if not isinstance(candidate, Mapping):
                continue
            payload = dict(candidate)
            payload.setdefault("guidance_only", True)
            payload.setdefault("intended_use", "guidance_only")
            key = json.dumps(payload, ensure_ascii=True, sort_keys=True, default=str)
            if key in seen:
                continue
            seen.add(key)
            candidates.append(payload)
            if len(candidates) >= 12:
                return candidates
    return candidates


def _leanstral_guidance_items(value: Any) -> List[Dict[str, Any]]:
    if hasattr(value, "guidance"):
        value = getattr(value, "guidance")
    if hasattr(value, "to_dict"):
        value = value.to_dict()
    if isinstance(value, Mapping):
        if isinstance(value.get("guidance"), Mapping):
            return _leanstral_guidance_items(value.get("guidance"))
        raw_items = value.get("guidance_items")
        if raw_items is None:
            raw_items = value.get("items")
        if isinstance(raw_items, Sequence) and not isinstance(raw_items, (str, bytes)):
            return _leanstral_guidance_items(raw_items)
        if value.get("guidance_id") or value.get("schema_version") == "legal-ir-leanstral-draft-guidance-v1":
            return [dict(value)]
        return []
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        items: List[Dict[str, Any]] = []
        for item in value:
            items.extend(_leanstral_guidance_items(item))
        return items
    return []


def _mapping_items(value: Any) -> List[Dict[str, Any]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    items: List[Dict[str, Any]] = []
    for item in value:
        if hasattr(item, "to_dict"):
            item = item.to_dict()
        if isinstance(item, Mapping):
            items.append(dict(item))
    return items


def _dedupe_string_values(values: Iterable[Any]) -> List[str]:
    seen: set[str] = set()
    result: List[str] = []
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _leanstral_rule_gap_dedup_key(
    *,
    gap_id: str,
    normalized_rule_key: str,
    target_component: str,
    action: str,
) -> str:
    payload = {
        "action": action,
        "gap_id": gap_id,
        "normalized_rule_key": normalized_rule_key,
        "target_component": target_component,
    }
    digest = hashlib.sha256(
        json.dumps(payload, ensure_ascii=True, sort_keys=True).encode("utf-8")
    ).hexdigest()[:20]
    return f"leanstral-rule-gap:{digest}"


def _rule_gap_counterexamples(
    supporting: Sequence[Mapping[str, Any]],
    conflicting: Sequence[Mapping[str, Any]],
    *,
    validation_set: Mapping[str, Any],
) -> List[Dict[str, Any]]:
    examples: List[Dict[str, Any]] = []
    for example in validation_set.get("regression_examples", []) or []:
        if isinstance(example, Mapping):
            examples.append({"role": "regression", **dict(example)})
    for example in _rule_gap_examples(supporting):
        examples.append({"role": "supporting", **dict(example)})
    for example in _rule_gap_examples(conflicting):
        examples.append({"role": "conflicting", **dict(example)})

    deduped: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for example in examples:
        key = json.dumps(example, ensure_ascii=True, sort_keys=True, default=str)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(example)
        if len(deduped) >= 8:
            break
    return deduped


def _logic_view_hint(
    sample_id: str,
    introspection: Mapping[str, Any],
    *,
    action: str,
    target_component: str,
    rationale: str,
) -> ModalProgramSynthesisHint:
    target_distribution = dict(introspection.get("legal_ir_view_distribution") or {})
    predicted_distribution = dict(
        introspection.get("legal_ir_predicted_view_distribution") or {}
    )
    component_gaps = dict(introspection.get("legal_ir_component_gaps") or {})
    target_view = _primary_view_for_component(
        target_component,
        target_distribution,
        component_gaps,
    )
    return _hint(
        sample_id,
        action=action,
        target_component=target_component,
        rationale=rationale,
        priority=max(
            0.05,
            float(introspection.get("legal_ir_view_cross_entropy_loss") or 0.0),
        ),
        evidence={
            **_pipeline_evidence(introspection),
            "bridge_failure_name": _bridge_failure_name_for_route(
                action,
                target_component,
            ),
            "legal_ir_component_gaps": dict(
                component_gaps
            ),
            "legal_ir_predicted_view_distribution": dict(
                predicted_distribution
            ),
            "legal_ir_underrepresented_components": list(
                introspection.get("legal_ir_underrepresented_components") or []
            ),
            "legal_ir_view_cross_entropy_loss": introspection.get(
                "legal_ir_view_cross_entropy_loss"
            ),
            "legal_ir_view_distribution": dict(
                target_distribution
            ),
            "predicted_view": _primary_view_for_component(
                target_component,
                predicted_distribution,
                component_gaps,
            ),
            "primary_legal_ir_component_gap": _component_gap_value(
                target_view,
                component_gaps,
            ),
            "target_file_lane": _target_file_lane(target_component, action),
            "target_view": target_view,
            "top_predicted_views": _top_distribution_names(predicted_distribution),
            "top_target_views": _top_distribution_names(target_distribution),
        },
    )


def _feature_names(contributions: Any) -> List[str]:
    if not isinstance(contributions, Sequence) or isinstance(contributions, (str, bytes)):
        return []
    names: List[str] = []
    for contribution in contributions:
        if not isinstance(contribution, Mapping):
            continue
        feature = str(contribution.get("feature") or "").strip()
        if feature and feature not in names:
            names.append(feature)
    return names


def _frame_features(introspection: Mapping[str, Any]) -> List[str]:
    features: List[str] = []
    for key in ("top_family_contributions", "top_embedding_contributions"):
        for feature in _feature_names(introspection.get(key, [])):
            if feature and feature not in features:
                features.append(feature)
    return frame_ontology_feature_keys(features)


def _pipeline_evidence(introspection: Mapping[str, Any]) -> Dict[str, Any]:
    """Return compact stage evidence for legal text -> IR -> text repairs."""

    diagnostics = dict(introspection.get("pipeline_stage_diagnostics") or {})
    focus = [
        str(value)
        for value in introspection.get("pipeline_stage_focus", []) or []
        if str(value)
    ]
    if not focus and diagnostics:
        focus = _pipeline_focus_from_diagnostics(diagnostics)
    evidence: Dict[str, Any] = {}
    if diagnostics:
        evidence["pipeline_stage_diagnostics"] = {
            str(key): value
            for key, value in sorted(diagnostics.items())
        }
    if focus:
        evidence["pipeline_stage_focus"] = focus
        evidence["primary_pipeline_stage"] = focus[0]
    cosine_loss = introspection.get("cosine_loss")
    if cosine_loss not in (None, ""):
        evidence["cosine_loss"] = cosine_loss
    return evidence


def _pipeline_focus_from_diagnostics(diagnostics: Mapping[str, Any]) -> List[str]:
    focus: List[str] = []
    if bool(diagnostics.get("spacy_parser_missing_formula")):
        focus.append("spacy_parser")
    if bool(diagnostics.get("modal_family_cue_mismatch")) or _float_value(
        diagnostics.get("modal_family_target_probability_gap")
    ) > 0.0:
        focus.append("modal_family_registry")
    if _float_value(diagnostics.get("autoencoder_embedding_cosine_gap")) > 0.20:
        focus.append("autoencoder_embedding_head")
    if _float_value(diagnostics.get("ir_decoder_reconstruction_loss")) > 0.05:
        focus.append("typed_ir_decoder")
    if (
        _float_value(
            diagnostics.get("source_decompiled_text_embedding_cosine_loss")
        )
        > 0.25
        or _float_value(diagnostics.get("source_decompiled_text_token_loss")) > 0.25
    ):
        focus.append("semantic_decompiler")
    if (
        _float_value(diagnostics.get("legal_ir_view_cross_entropy_loss")) > 0.05
        or _float_value(diagnostics.get("legal_ir_component_gap_max")) > 0.02
    ):
        focus.append("legal_ir_multiview")
    return _unique_preserve_order(focus)


def _float_value(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _unique_preserve_order(values: Iterable[str]) -> List[str]:
    seen: set[str] = set()
    unique: List[str] = []
    for value in values:
        text = str(value)
        if not text or text in seen:
            continue
        seen.add(text)
        unique.append(text)
    return unique


def _top_distribution_names(distribution: Mapping[str, Any], *, limit: int = 5) -> List[str]:
    scored: List[tuple[float, str]] = []
    for name, value in dict(distribution or {}).items():
        try:
            scored.append((float(value), str(name)))
        except (TypeError, ValueError):
            continue
    return [
        name
        for _value, name in sorted(scored, key=lambda item: (-item[0], item[1]))[:limit]
    ]


def _top_component_gap_items(value: Any, *, limit: int = 8) -> List[List[Any]]:
    if not isinstance(value, Mapping):
        return []
    scored: List[tuple[float, str]] = []
    for name, gap in value.items():
        try:
            numeric_gap = float(gap)
        except (TypeError, ValueError):
            continue
        if numeric_gap <= 0.0:
            continue
        scored.append((numeric_gap, str(name)))
    return [
        [name, round(gap, 6)]
        for gap, name in sorted(scored, key=lambda item: (-item[0], item[1]))[:limit]
    ]


def _legal_ir_specific_focus_items(focus: Sequence[str]) -> List[str]:
    """Return LegalIR repair focus items that name a concrete bridge lane."""
    generic = {
        "repair_multiview_legal_ir_loss",
        "repair_multiview_legal_ir_view_coverage",
    }
    component_specific_prefixes = (
        "repair_cec_",
        "repair_deontic_",
        "repair_external_prover_",
        "repair_flogic_",
        "repair_tdfol_",
        "repair_zkp_",
    )
    component_specific_names = {
        "repair_multiview_legal_ir_graph_projection",
        "repair_multiview_legal_ir_prover_gate",
    }
    items: List[str] = []
    for raw_item in focus:
        item = str(raw_item)
        if item in generic:
            continue
        if item in component_specific_names or item.startswith(component_specific_prefixes):
            items.append(item)
    return items


def _primary_view_for_component(
    target_component: str,
    distribution: Mapping[str, Any],
    component_gaps: Mapping[str, Any],
) -> str:
    prefixes = _component_prefixes(target_component)
    candidates: List[tuple[float, float, str]] = []
    for name, raw_value in dict(distribution or {}).items():
        component = str(name)
        if prefixes and not any(
            component == prefix or component.startswith(prefix)
            for prefix in prefixes
        ):
            continue
        try:
            value = float(raw_value)
        except (TypeError, ValueError):
            value = 0.0
        candidates.append(
            (_component_gap_value(component, component_gaps), value, component)
        )
    if not candidates:
        for component, raw_gap in dict(component_gaps or {}).items():
            component_name = str(component)
            if prefixes and not any(
                component_name == prefix or component_name.startswith(prefix)
                for prefix in prefixes
            ):
                continue
            try:
                gap = float(raw_gap)
            except (TypeError, ValueError):
                gap = 0.0
            candidates.append((gap, 0.0, component_name))
    if not candidates:
        names = _top_distribution_names(distribution, limit=1)
        return names[0] if names else str(target_component)
    return sorted(candidates, key=lambda item: (-item[0], -item[1], item[2]))[0][2]


def _component_gap_value(component: str, component_gaps: Mapping[str, Any]) -> float:
    try:
        return round(float(dict(component_gaps or {}).get(str(component), 0.0)), 6)
    except (TypeError, ValueError):
        return 0.0


def _component_prefixes(target_component: str) -> List[str]:
    component = str(target_component or "")
    mapping = {
        "bridge.contracts": [
            "deontic.",
            "TDFOL.",
            "CEC.",
            "external_provers.",
            "knowledge_graphs.",
            "zkp.",
        ],
        "CEC.native": ["CEC."],
        "TDFOL.prover": ["TDFOL.", "fol."],
        "deontic.ir": ["deontic."],
        "external_provers.router": ["external_provers."],
        "knowledge_graphs.neo4j_compat": ["knowledge_graphs."],
        "modal.autoencoder": ["modal.autoencoder", "logic.optimizer.autoencoder"],
        "modal.frame_logic": ["modal.frame_logic", "frame_logic"],
        "zkp.circuits": ["zkp."],
    }
    return mapping.get(component, [component] if component else [])


def _target_file_lane(target_component: str, action: str) -> str:
    component = str(target_component or "")
    if component == "modal.compiler":
        return "compiler_parser"
    if component == "modal.compiler.registry":
        return "compiler_registry"
    if component == "modal.compiler.ambiguity":
        return "compiler_ambiguity"
    if component == "modal.ir_decompiler":
        return "ir_decompiler"
    if component == "modal.autoencoder" or component == "logic.optimizer.autoencoder":
        return "autoencoder"
    if component == "modal.frame_logic":
        return "frame_logic"
    if component == "bridge.contracts":
        return "bridge"
    if component.startswith("deontic."):
        return "deontic"
    if component.startswith("TDFOL.") or component.startswith("fol."):
        return "tdfol"
    if component.startswith("CEC."):
        return "cec"
    if component.startswith("external_provers."):
        return "external_provers"
    if component.startswith("knowledge_graphs."):
        return "knowledge_graph"
    if component.startswith("zkp."):
        return "zkp"
    return str(action or component or "unknown")


def _bridge_failure_name_for_route(
    action: str,
    target_component: str,
    *,
    loss_name: str = "",
) -> str:
    if loss_name:
        return str(loss_name)
    return {
        "repair_cec_dcec_bridge": "cec_dcec_validation_failure_ratio",
        "repair_deontic_bridge_quality_gate": "deontic_decoder_slot_loss",
        "repair_external_prover_router": "legal_ir_multiview_proof_failure_ratio",
        "repair_flogic_ontology_constraints": "flogic_similarity_loss",
        "repair_multiview_legal_ir_graph_projection": "legal_ir_multiview_graph_failure_penalty",
        "repair_multiview_legal_ir_loss": "legal_ir_view_cross_entropy_loss",
        "repair_tdfol_bridge_parse": "tdfol_parse_failure_ratio",
        "repair_zkp_attestation_bridge": "zkp_verification_failure_ratio",
    }.get(str(action), str(target_component))


def _priority_from_probability_gap(introspection: Mapping[str, Any]) -> float:
    target_probability = float(introspection.get("target_probability") or 0.0)
    predicted_probability = float(introspection.get("predicted_probability") or 0.0)
    return max(0.0, predicted_probability - target_probability, 1.0 - target_probability)


def _family_margin(introspection: Mapping[str, Any]) -> float:
    try:
        return float(introspection.get("family_margin") or 0.0)
    except (TypeError, ValueError):
        return 0.0


__all__ = [
    "ModalProgramSynthesisHint",
    "ModalResidualRepairRoute",
    "residual_signature_for_hint",
    "route_autoencoder_residual",
    "synthesis_hints_from_autoencoder_introspection",
    "synthesis_hints_from_autoencoder_introspections",
    "synthesis_hints_from_leanstral_guidance",
    "synthesis_hints_from_leanstral_rule_gap_report",
    "synthesis_hints_from_leanstral_rule_gaps",
]
