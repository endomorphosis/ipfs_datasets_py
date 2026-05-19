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


def synthesis_hints_from_autoencoder_introspection(
    introspection: Mapping[str, Any],
) -> List[ModalProgramSynthesisHint]:
    """Convert one introspection record into typed synthesis hints."""
    sample_id = str(introspection.get("sample_id") or "")
    focus = [str(value) for value in introspection.get("synthesis_focus", [])]
    hints: List[ModalProgramSynthesisHint] = []

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
    "synthesis_hints_from_autoencoder_introspection",
    "synthesis_hints_from_autoencoder_introspections",
]
