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
        action="refine_typed_ir_or_decompiler_slots",
        target_component="modal.ir_decompiler",
        rationale="Cosine residuals indicate typed IR/decompiler slots are losing embedding semantics.",
        priority=0.5,
    ),
    "reconstruction_loss": ModalResidualRepairRoute(
        action="refine_typed_ir_or_decompiler_slots",
        target_component="modal.ir_decompiler",
        rationale="Reconstruction residuals indicate typed IR/decompiler slots are losing source semantics.",
        priority=0.5,
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
        "family_pair": [
            evidence.get("predicted_family"),
            evidence.get("target_family"),
        ],
        "frame_features": sorted(map(str, evidence.get("frame_features", []) or []))[:8],
        "target_component": hint.target_component,
        "top_embedding_features": sorted(
            map(str, evidence.get("top_embedding_features", []) or [])
        )[:8],
        "top_family_features": sorted(
            map(str, evidence.get("top_family_features", []) or [])
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
    hints: List[ModalProgramSynthesisHint] = []
    routed_loss_names = [
        "cross_entropy_loss",
        "cosine_loss",
        "reconstruction_loss",
        "legal_ir_view_cross_entropy_loss",
        "legal_ir_multiview_proof_failure_ratio",
        "legal_ir_multiview_graph_failure_penalty",
        "deontic_decoder_slot_loss",
    ]

    for loss_name in routed_loss_names:
        value = introspection.get(loss_name)
        if value in (None, "", 0, 0.0):
            continue
        route = route_autoencoder_residual(loss_name, focus=focus)
        if route is None:
            continue
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
                    "predicted_family": introspection.get("predicted_family"),
                    "target_family": introspection.get("target_family"),
                    "top_embedding_features": _feature_names(
                        introspection.get("top_embedding_contributions", [])
                    ),
                    "top_family_features": _feature_names(
                        introspection.get("top_family_contributions", [])
                    ),
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
                    "target_family": introspection.get("target_family"),
                    "predicted_family": introspection.get("predicted_family"),
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
                    "family_margin": introspection.get("family_margin"),
                    "predicted_family": introspection.get("predicted_family"),
                    "target_family": introspection.get("target_family"),
                    "target_probability": introspection.get("target_probability"),
                    "top_family_features": _feature_names(
                        introspection.get("top_family_contributions", [])
                    ),
                },
            )
        )

    if "refine_typed_ir_or_decompiler_slots" in focus:
        hints.append(
            _hint(
                sample_id,
                action="refine_typed_ir_or_decompiler_slots",
                target_component="modal.ir_decompiler",
                rationale="Embedding residuals point to information not well represented by the typed IR/decompiler.",
                priority=float(introspection.get("reconstruction_loss") or 0.0),
                evidence={
                    "cosine_similarity": introspection.get("cosine_similarity"),
                    "reconstruction_loss": introspection.get("reconstruction_loss"),
                    "top_embedding_features": _feature_names(
                        introspection.get("top_embedding_contributions", [])
                    ),
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
        hints.append(
            _hint(
                sample_id,
                action="repair_multiview_legal_ir_loss",
                target_component="bridge.contracts",
                rationale="Adaptive LegalIR evidence shows the compiler/decompiler view distribution is not aligned with the canonical multiview target.",
                priority=max(
                    0.05,
                    float(introspection.get("legal_ir_view_cross_entropy_loss") or 0.0),
                ),
                evidence={
                    "legal_ir_predicted_view_distribution": predicted_distribution,
                    "legal_ir_view_cross_entropy_loss": introspection.get(
                        "legal_ir_view_cross_entropy_loss"
                    ),
                    "legal_ir_view_distribution": target_distribution,
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
            _hint(
                sample_id,
                action="repair_deontic_bridge_quality_gate",
                target_component="deontic.ir",
                rationale="The canonical multiview LegalIR target includes deontic structure that the adaptive view model cannot yet reconstruct confidently.",
                priority=max(
                    0.05,
                    float(introspection.get("legal_ir_view_cross_entropy_loss") or 0.0),
                ),
                evidence={
                    "legal_ir_predicted_view_distribution": dict(
                        introspection.get("legal_ir_predicted_view_distribution") or {}
                    ),
                    "legal_ir_view_cross_entropy_loss": introspection.get(
                        "legal_ir_view_cross_entropy_loss"
                    ),
                    "legal_ir_view_distribution": dict(
                        introspection.get("legal_ir_view_distribution") or {}
                    ),
                },
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
                    "frame_features": frame_features,
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
                    "family_margin": introspection.get("family_margin"),
                    "predicted_family": introspection.get("predicted_family"),
                    "target_family": introspection.get("target_family"),
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


def _logic_view_hint(
    sample_id: str,
    introspection: Mapping[str, Any],
    *,
    action: str,
    target_component: str,
    rationale: str,
) -> ModalProgramSynthesisHint:
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
            "legal_ir_predicted_view_distribution": dict(
                introspection.get("legal_ir_predicted_view_distribution") or {}
            ),
            "legal_ir_view_cross_entropy_loss": introspection.get(
                "legal_ir_view_cross_entropy_loss"
            ),
            "legal_ir_view_distribution": dict(
                introspection.get("legal_ir_view_distribution") or {}
            ),
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
]
