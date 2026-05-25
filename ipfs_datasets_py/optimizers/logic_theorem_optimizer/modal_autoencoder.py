"""Deterministic modal autoencoder baselines, training state, and losses."""

from __future__ import annotations

import json
import hashlib
import math
import os
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

from .legal_samples import LegalSample
from .modal_registry import ModalLogicFamily

_LEGAL_IR_TARGET_CACHE_MAX = 2048
_LEGAL_IR_TARGET_CACHE_LOCK = threading.Lock()
_LEGAL_IR_TARGET_CACHE: Dict[str, Any] = {}


def cosine_similarity(left: Sequence[float], right: Sequence[float]) -> float:
    """Return cosine similarity for two vectors."""
    _check_same_length(left, right)
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0
    return sum(a * b for a, b in zip(left, right)) / (left_norm * right_norm)


def cosine_loss(left: Sequence[float], right: Sequence[float]) -> float:
    """Return ``1 - cosine_similarity``."""
    return 1.0 - cosine_similarity(left, right)


def mse_loss(left: Sequence[float], right: Sequence[float]) -> float:
    """Return mean squared reconstruction error."""
    _check_same_length(left, right)
    if not left:
        return 0.0
    return sum((a - b) ** 2 for a, b in zip(left, right)) / len(left)


def cross_entropy_loss(probabilities: Mapping[str, float], target: str) -> float:
    """Return categorical cross entropy for a target label."""
    probability = max(float(probabilities.get(target, 0.0)), 1e-12)
    return -math.log(probability)


def cross_entropy_distribution_loss(
    probabilities: Mapping[str, float],
    target_distribution: Mapping[str, float],
) -> float:
    """Return cross entropy against a target label distribution."""
    total_weight = sum(
        max(0.0, float(weight))
        for weight in target_distribution.values()
    )
    if total_weight <= 0.0:
        return 0.0
    loss = 0.0
    for family, weight in target_distribution.items():
        normalized_weight = max(0.0, float(weight)) / total_weight
        probability = max(float(probabilities.get(str(family), 0.0)), 1e-12)
        loss += normalized_weight * -math.log(probability)
    return loss


@dataclass(frozen=True)
class AutoencoderEvaluation:
    """Metrics for one deterministic baseline pass."""

    sample_count: int
    embedding_cosine_similarity: float
    cosine_loss: float
    reconstruction_loss: float
    cross_entropy_loss: float
    frame_ranking_loss: float
    symbolic_validity_penalty: float
    decoded_embeddings: Dict[str, List[float]]
    legal_ir_target_count: int = 0
    legal_ir_losses: Dict[str, float] = field(default_factory=dict)
    legal_ir_predicted_view_distribution: Dict[str, float] = field(default_factory=dict)
    legal_ir_target_hashes: Dict[str, str] = field(default_factory=dict)
    legal_ir_view_distribution: Dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, object]:
        return {
            "cosine_loss": self.cosine_loss,
            "cross_entropy_loss": self.cross_entropy_loss,
            "decoded_embeddings": self.decoded_embeddings,
            "embedding_cosine_similarity": self.embedding_cosine_similarity,
            "frame_ranking_loss": self.frame_ranking_loss,
            "legal_ir_losses": dict(sorted(self.legal_ir_losses.items())),
            "legal_ir_predicted_view_distribution": dict(
                sorted(self.legal_ir_predicted_view_distribution.items())
            ),
            "legal_ir_target_count": self.legal_ir_target_count,
            "legal_ir_target_hashes": dict(sorted(self.legal_ir_target_hashes.items())),
            "legal_ir_view_distribution": dict(sorted(self.legal_ir_view_distribution.items())),
            "reconstruction_loss": self.reconstruction_loss,
            "sample_count": self.sample_count,
            "symbolic_validity_penalty": self.symbolic_validity_penalty,
        }


@dataclass(frozen=True)
class AutoencoderFeatureContribution:
    """One explainable autoencoder contribution for advisor-driven synthesis."""

    feature: str
    contribution_type: str
    value: float
    magnitude: float
    family: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "contribution_type": self.contribution_type,
            "family": self.family,
            "feature": self.feature,
            "magnitude": self.magnitude,
            "metadata": dict(sorted(self.metadata.items())),
            "value": self.value,
        }


@dataclass(frozen=True)
class AutoencoderIntrospection:
    """Serializable evidence explaining an adaptive modal autoencoder decision."""

    sample_id: str
    target_family: str
    predicted_family: str
    target_probability: float
    predicted_probability: float
    family_margin: float
    cosine_similarity: float
    reconstruction_loss: float
    residual_vector: List[float]
    base_decoded_embedding: List[float]
    decoded_embedding: List[float]
    feature_count: int
    sample_memory_used: bool
    top_family_contributions: List[AutoencoderFeatureContribution] = field(default_factory=list)
    top_embedding_contributions: List[AutoencoderFeatureContribution] = field(default_factory=list)
    synthesis_focus: List[str] = field(default_factory=list)
    legal_ir_view_cross_entropy_loss: float = 0.0
    legal_ir_component_gaps: Dict[str, float] = field(default_factory=dict)
    legal_ir_losses: Dict[str, float] = field(default_factory=dict)
    legal_ir_underrepresented_components: List[str] = field(default_factory=list)
    legal_ir_overrepresented_components: List[str] = field(default_factory=list)
    legal_ir_view_distribution: Dict[str, float] = field(default_factory=dict)
    legal_ir_predicted_view_distribution: Dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "base_decoded_embedding": list(self.base_decoded_embedding),
            "cosine_similarity": self.cosine_similarity,
            "decoded_embedding": list(self.decoded_embedding),
            "family_margin": self.family_margin,
            "feature_count": self.feature_count,
            "legal_ir_predicted_view_distribution": dict(
                sorted(self.legal_ir_predicted_view_distribution.items())
            ),
            "legal_ir_component_gaps": dict(sorted(self.legal_ir_component_gaps.items())),
            "legal_ir_losses": dict(sorted(self.legal_ir_losses.items())),
            "legal_ir_overrepresented_components": list(
                self.legal_ir_overrepresented_components
            ),
            "legal_ir_underrepresented_components": list(
                self.legal_ir_underrepresented_components
            ),
            "legal_ir_view_cross_entropy_loss": self.legal_ir_view_cross_entropy_loss,
            "legal_ir_view_distribution": dict(sorted(self.legal_ir_view_distribution.items())),
            "predicted_family": self.predicted_family,
            "predicted_probability": self.predicted_probability,
            "reconstruction_loss": self.reconstruction_loss,
            "residual_vector": list(self.residual_vector),
            "sample_id": self.sample_id,
            "sample_memory_used": self.sample_memory_used,
            "synthesis_focus": list(self.synthesis_focus),
            "target_family": self.target_family,
            "target_probability": self.target_probability,
            "top_embedding_contributions": [
                contribution.to_dict()
                for contribution in self.top_embedding_contributions
            ],
            "top_family_contributions": [
                contribution.to_dict()
                for contribution in self.top_family_contributions
            ],
        }


@dataclass(frozen=True)
class ProverCompilationSignal:
    """Local theorem-prover compilation health for one modal IR sample."""

    attempted_count: int
    valid_count: int
    unavailable_count: int = 0
    error_count: int = 0
    failed_count: int = 0
    verified_by: List[str] = field(default_factory=list)
    details: List[Dict[str, Any]] = field(default_factory=list)

    @property
    def compiles(self) -> bool:
        """Return True when every attempted modal formula reached a prover route."""
        return self.attempted_count > 0 and self.valid_count == self.attempted_count

    @property
    def failure_ratio(self) -> float:
        """Return the fraction of formulas that failed local prover compilation."""
        if self.attempted_count <= 0:
            return 1.0
        failures = self.unavailable_count + self.error_count + self.failed_count
        return min(1.0, failures / self.attempted_count)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "attempted_count": self.attempted_count,
            "compiles": self.compiles,
            "details": list(self.details),
            "error_count": self.error_count,
            "failed_count": self.failed_count,
            "failure_ratio": self.failure_ratio,
            "unavailable_count": self.unavailable_count,
            "valid_count": self.valid_count,
            "verified_by": list(self.verified_by),
        }


@dataclass(frozen=True)
class CodexCallGateConfig:
    """Thresholds and call-cost settings for the Codex advisor gate."""

    min_cosine_similarity: float = 0.72
    max_cross_entropy_loss: float = 1.20
    max_reconstruction_loss: float = 0.20
    max_legal_ir_multiview_total_loss: float = 0.25
    max_legal_ir_view_cross_entropy_loss: float = 0.05
    max_legal_ir_proof_failure_ratio: float = 0.0
    max_legal_ir_graph_failure_penalty: float = 0.0
    max_frame_ranking_loss: float = 0.0
    max_symbolic_validity_penalty: float = 0.0
    require_prover_compilation: bool = True
    allow_repeat_signatures: bool = False
    max_codex_calls: Optional[int] = None
    min_net_benefit: float = 0.0
    codex_call_cost: float = 0.35
    cosine_weight: float = 1.0
    cross_entropy_weight: float = 1.0
    reconstruction_weight: float = 1.0
    legal_ir_weight: float = 1.0
    frame_weight: float = 0.5
    symbolic_weight: float = 1.0
    prover_weight: float = 1.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "allow_repeat_signatures": self.allow_repeat_signatures,
            "codex_call_cost": self.codex_call_cost,
            "cosine_weight": self.cosine_weight,
            "cross_entropy_weight": self.cross_entropy_weight,
            "frame_weight": self.frame_weight,
            "legal_ir_weight": self.legal_ir_weight,
            "max_codex_calls": self.max_codex_calls,
            "max_cross_entropy_loss": self.max_cross_entropy_loss,
            "max_frame_ranking_loss": self.max_frame_ranking_loss,
            "max_legal_ir_graph_failure_penalty": self.max_legal_ir_graph_failure_penalty,
            "max_legal_ir_multiview_total_loss": self.max_legal_ir_multiview_total_loss,
            "max_legal_ir_proof_failure_ratio": self.max_legal_ir_proof_failure_ratio,
            "max_legal_ir_view_cross_entropy_loss": self.max_legal_ir_view_cross_entropy_loss,
            "max_reconstruction_loss": self.max_reconstruction_loss,
            "max_symbolic_validity_penalty": self.max_symbolic_validity_penalty,
            "min_cosine_similarity": self.min_cosine_similarity,
            "min_net_benefit": self.min_net_benefit,
            "prover_weight": self.prover_weight,
            "reconstruction_weight": self.reconstruction_weight,
            "require_prover_compilation": self.require_prover_compilation,
            "symbolic_weight": self.symbolic_weight,
        }


@dataclass
class CodexCallCache:
    """In-memory cache for suppressing repeated Codex advisor calls."""

    codex_text_hashes: set[str] = field(default_factory=set)
    codex_feature_signature_hashes: set[str] = field(default_factory=set)
    local_success_feature_signature_hashes: set[str] = field(default_factory=set)
    codex_call_count: int = 0

    def record_codex_call(self, decision: "CodexCallDecision") -> None:
        self.codex_text_hashes.add(decision.text_hash)
        self.codex_feature_signature_hashes.add(decision.feature_signature_hash)
        self.codex_call_count += 1

    def record_local_success(self, decision: "CodexCallDecision") -> None:
        self.local_success_feature_signature_hashes.add(decision.feature_signature_hash)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "codex_call_count": self.codex_call_count,
            "codex_feature_signature_hashes": sorted(self.codex_feature_signature_hashes),
            "codex_text_hashes": sorted(self.codex_text_hashes),
            "local_success_feature_signature_hashes": sorted(
                self.local_success_feature_signature_hashes
            ),
        }


@dataclass(frozen=True)
class CodexCallDecision:
    """Decision record for whether the expensive Codex loop should run."""

    should_call_codex: bool
    reasons: List[str]
    suppressed_reasons: List[str]
    local_loss: float
    codex_call_cost: float
    net_benefit: float
    text_hash: str
    feature_signature: List[str]
    feature_signature_hash: str
    metrics: Dict[str, float]
    prover_signal: Optional[ProverCompilationSignal] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "codex_call_cost": self.codex_call_cost,
            "feature_signature": list(self.feature_signature),
            "feature_signature_hash": self.feature_signature_hash,
            "local_loss": self.local_loss,
            "metrics": dict(sorted(self.metrics.items())),
            "net_benefit": self.net_benefit,
            "prover_signal": self.prover_signal.to_dict() if self.prover_signal else None,
            "reasons": list(self.reasons),
            "should_call_codex": self.should_call_codex,
            "suppressed_reasons": list(self.suppressed_reasons),
            "text_hash": self.text_hash,
        }


@dataclass
class ModalAutoencoderTrainingState:
    """Mutable deterministic state for the modal encoder/decoder optimizer."""

    decoded_embeddings: Dict[str, List[float]] = field(default_factory=dict)
    family_logits: Dict[str, Dict[str, float]] = field(default_factory=dict)
    feature_embedding_weights: Dict[str, List[float]] = field(default_factory=dict)
    family_embedding_weights: Dict[str, List[float]] = field(default_factory=dict)
    feature_family_logits: Dict[str, Dict[str, float]] = field(default_factory=dict)
    legal_ir_view_logits: Dict[str, float] = field(default_factory=dict)
    legal_ir_view_embedding_weights: Dict[str, List[float]] = field(default_factory=dict)
    feature_legal_ir_view_logits: Dict[str, Dict[str, float]] = field(default_factory=dict)
    applied_todo_ids: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "applied_todo_ids": list(self.applied_todo_ids),
            "decoded_embeddings": {
                sample_id: list(vector)
                for sample_id, vector in sorted(self.decoded_embeddings.items())
            },
            "family_logits": {
                sample_id: dict(sorted(logits.items()))
                for sample_id, logits in sorted(self.family_logits.items())
            },
            "feature_legal_ir_view_logits": {
                feature: dict(sorted(logits.items()))
                for feature, logits in sorted(self.feature_legal_ir_view_logits.items())
            },
            "feature_embedding_weights": {
                feature: list(vector)
                for feature, vector in sorted(self.feature_embedding_weights.items())
            },
            "family_embedding_weights": {
                family: list(vector)
                for family, vector in sorted(self.family_embedding_weights.items())
            },
            "feature_family_logits": {
                feature: dict(sorted(logits.items()))
                for feature, logits in sorted(self.feature_family_logits.items())
            },
            "legal_ir_view_embedding_weights": {
                view: list(vector)
                for view, vector in sorted(self.legal_ir_view_embedding_weights.items())
            },
            "legal_ir_view_logits": dict(sorted(self.legal_ir_view_logits.items())),
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=True, sort_keys=True, separators=(",", ":"))

    def copy(self) -> "ModalAutoencoderTrainingState":
        """Return a deep copy suitable for transactional optimizer rollback."""
        return self.from_dict(self.to_dict())

    def generalizable_copy(self) -> "ModalAutoencoderTrainingState":
        """Return only feature-level state safe to reuse across samples.

        Sample-specific decoded embeddings and family logits are deliberately
        dropped.  Those entries are useful for transactional training, but they
        can contaminate future validation if carried into a fresh run.
        """
        return ModalAutoencoderTrainingState(
            feature_embedding_weights={
                feature: list(vector)
                for feature, vector in self.feature_embedding_weights.items()
            },
            family_embedding_weights={
                family: list(vector)
                for family, vector in self.family_embedding_weights.items()
            },
            feature_family_logits={
                feature: dict(logits)
                for feature, logits in self.feature_family_logits.items()
            },
            legal_ir_view_logits=dict(self.legal_ir_view_logits),
            legal_ir_view_embedding_weights={
                view: list(vector)
                for view, vector in self.legal_ir_view_embedding_weights.items()
            },
            feature_legal_ir_view_logits={
                feature: dict(logits)
                for feature, logits in self.feature_legal_ir_view_logits.items()
            },
        )

    def merge_generalizable_from(
        self,
        other: "ModalAutoencoderTrainingState",
        *,
        scale: float = 1.0,
    ) -> None:
        """Add feature-level weights from ``other`` into this state."""
        for feature, vector in other.feature_embedding_weights.items():
            if feature not in self.feature_embedding_weights:
                self.feature_embedding_weights[feature] = [
                    float(value) * scale for value in vector
                ]
                continue
            current = self.feature_embedding_weights[feature]
            if len(current) != len(vector):
                continue
            for index, value in enumerate(vector):
                current[index] += float(value) * scale

        for family, vector in other.family_embedding_weights.items():
            if family not in self.family_embedding_weights:
                self.family_embedding_weights[family] = [
                    float(value) * scale for value in vector
                ]
                continue
            current = self.family_embedding_weights[family]
            if len(current) != len(vector):
                continue
            for index, value in enumerate(vector):
                current[index] += float(value) * scale

        for view, vector in other.legal_ir_view_embedding_weights.items():
            if view not in self.legal_ir_view_embedding_weights:
                self.legal_ir_view_embedding_weights[view] = [
                    float(value) * scale for value in vector
                ]
                continue
            current = self.legal_ir_view_embedding_weights[view]
            if len(current) != len(vector):
                continue
            for index, value in enumerate(vector):
                current[index] += float(value) * scale

        for feature, logits in other.feature_family_logits.items():
            current_logits = self.feature_family_logits.setdefault(feature, {})
            for family, value in logits.items():
                current_logits[family] = current_logits.get(family, 0.0) + (
                    float(value) * scale
                )

        for view, value in other.legal_ir_view_logits.items():
            self.legal_ir_view_logits[view] = self.legal_ir_view_logits.get(view, 0.0) + (
                float(value) * scale
            )

        for feature, logits in other.feature_legal_ir_view_logits.items():
            current_logits = self.feature_legal_ir_view_logits.setdefault(feature, {})
            for view, value in logits.items():
                current_logits[view] = current_logits.get(view, 0.0) + (
                    float(value) * scale
                )

    @classmethod
    def average_generalizable(
        cls,
        states: Iterable["ModalAutoencoderTrainingState"],
    ) -> "ModalAutoencoderTrainingState":
        """Average feature-level state from previous runs for warm starts."""
        state_list = [state.generalizable_copy() for state in states]
        if not state_list:
            return cls()

        merged = cls()
        vector_counts: Dict[str, int] = {}
        family_vector_counts: Dict[str, int] = {}
        legal_view_vector_counts: Dict[str, int] = {}
        logit_counts: Dict[tuple[str, str], int] = {}
        legal_view_counts: Dict[str, int] = {}
        feature_legal_view_counts: Dict[tuple[str, str], int] = {}

        for state in state_list:
            for feature, vector in state.feature_embedding_weights.items():
                if feature not in merged.feature_embedding_weights:
                    merged.feature_embedding_weights[feature] = [0.0 for _ in vector]
                    vector_counts[feature] = 0
                current = merged.feature_embedding_weights[feature]
                if len(current) != len(vector):
                    continue
                for index, value in enumerate(vector):
                    current[index] += float(value)
                vector_counts[feature] += 1

            for family, vector in state.family_embedding_weights.items():
                if family not in merged.family_embedding_weights:
                    merged.family_embedding_weights[family] = [0.0 for _ in vector]
                    family_vector_counts[family] = 0
                current = merged.family_embedding_weights[family]
                if len(current) != len(vector):
                    continue
                for index, value in enumerate(vector):
                    current[index] += float(value)
                family_vector_counts[family] += 1

            for view, vector in state.legal_ir_view_embedding_weights.items():
                if view not in merged.legal_ir_view_embedding_weights:
                    merged.legal_ir_view_embedding_weights[view] = [0.0 for _ in vector]
                    legal_view_vector_counts[view] = 0
                current = merged.legal_ir_view_embedding_weights[view]
                if len(current) != len(vector):
                    continue
                for index, value in enumerate(vector):
                    current[index] += float(value)
                legal_view_vector_counts[view] += 1

            for feature, logits in state.feature_family_logits.items():
                current_logits = merged.feature_family_logits.setdefault(feature, {})
                for family, value in logits.items():
                    current_logits[family] = current_logits.get(family, 0.0) + float(value)
                    logit_counts[(feature, family)] = logit_counts.get((feature, family), 0) + 1

            for view, value in state.legal_ir_view_logits.items():
                merged.legal_ir_view_logits[view] = (
                    merged.legal_ir_view_logits.get(view, 0.0) + float(value)
                )
                legal_view_counts[view] = legal_view_counts.get(view, 0) + 1

            for feature, logits in state.feature_legal_ir_view_logits.items():
                current_logits = merged.feature_legal_ir_view_logits.setdefault(feature, {})
                for view, value in logits.items():
                    current_logits[view] = current_logits.get(view, 0.0) + float(value)
                    feature_legal_view_counts[(feature, view)] = (
                        feature_legal_view_counts.get((feature, view), 0) + 1
                    )

        for feature, count in vector_counts.items():
            if count <= 0:
                continue
            merged.feature_embedding_weights[feature] = [
                value / count for value in merged.feature_embedding_weights[feature]
            ]
        for family, count in family_vector_counts.items():
            if count <= 0:
                continue
            merged.family_embedding_weights[family] = [
                value / count for value in merged.family_embedding_weights[family]
            ]
        for view, count in legal_view_vector_counts.items():
            if count <= 0:
                continue
            merged.legal_ir_view_embedding_weights[view] = [
                value / count for value in merged.legal_ir_view_embedding_weights[view]
            ]
        for feature, logits in merged.feature_family_logits.items():
            for family, value in list(logits.items()):
                count = logit_counts.get((feature, family), 0)
                if count > 0:
                    logits[family] = value / count
        for view, value in list(merged.legal_ir_view_logits.items()):
            count = legal_view_counts.get(view, 0)
            if count > 0:
                merged.legal_ir_view_logits[view] = value / count
        for feature, logits in merged.feature_legal_ir_view_logits.items():
            for view, value in list(logits.items()):
                count = feature_legal_view_counts.get((feature, view), 0)
                if count > 0:
                    logits[view] = value / count
        return merged

    def save_json(self, path: str | Path) -> None:
        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(self.to_json() + "\n", encoding="utf-8")

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ModalAutoencoderTrainingState":
        return cls(
            decoded_embeddings={
                str(sample_id): [float(value) for value in vector]
                for sample_id, vector in dict(data.get("decoded_embeddings", {})).items()
            },
            family_logits={
                str(sample_id): {str(name): float(value) for name, value in dict(logits).items()}
                for sample_id, logits in dict(data.get("family_logits", {})).items()
            },
            feature_embedding_weights={
                str(feature): [float(value) for value in vector]
                for feature, vector in dict(data.get("feature_embedding_weights", {})).items()
            },
            family_embedding_weights={
                str(family): [float(value) for value in vector]
                for family, vector in dict(data.get("family_embedding_weights", {})).items()
            },
            feature_family_logits={
                str(feature): {str(name): float(value) for name, value in dict(logits).items()}
                for feature, logits in dict(data.get("feature_family_logits", {})).items()
            },
            legal_ir_view_logits={
                str(name): float(value)
                for name, value in dict(data.get("legal_ir_view_logits", {})).items()
            },
            legal_ir_view_embedding_weights={
                str(view): [float(value) for value in vector]
                for view, vector in dict(
                    data.get("legal_ir_view_embedding_weights", {})
                ).items()
            },
            feature_legal_ir_view_logits={
                str(feature): {str(name): float(value) for name, value in dict(logits).items()}
                for feature, logits in dict(
                    data.get("feature_legal_ir_view_logits", {})
                ).items()
            },
            applied_todo_ids=[str(value) for value in data.get("applied_todo_ids", [])],
        )

    @classmethod
    def load_json(cls, path: str | Path) -> "ModalAutoencoderTrainingState":
        source = Path(path)
        if not source.exists():
            return cls()
        return cls.from_dict(json.loads(source.read_text(encoding="utf-8")))


class ModalAutoencoderBaseline:
    """Dependency-free baseline for the future encoder/decoder pair."""

    def evaluate(
        self,
        samples: Iterable[LegalSample],
        *,
        legal_ir_bridge_names: Sequence[str] = (),
        legal_ir_targets: Optional[Mapping[str, Any] | Sequence[Any]] = None,
    ) -> AutoencoderEvaluation:
        """Evaluate deterministic reconstruction and modal-family losses."""
        sample_list = list(samples)
        if not sample_list:
            return AutoencoderEvaluation(
                sample_count=0,
                embedding_cosine_similarity=0.0,
                cosine_loss=0.0,
                reconstruction_loss=0.0,
                cross_entropy_loss=0.0,
                frame_ranking_loss=0.0,
                symbolic_validity_penalty=0.0,
                decoded_embeddings={},
            )
        legal_ir_payload = _legal_ir_target_payload(
            sample_list,
            bridge_names=legal_ir_bridge_names,
            legal_ir_targets=legal_ir_targets,
        )

        cosine_scores: List[float] = []
        cosine_losses: List[float] = []
        reconstruction_losses: List[float] = []
        ce_losses: List[float] = []
        frame_losses: List[float] = []
        symbolic_penalties: List[float] = []
        decoded_embeddings: Dict[str, List[float]] = {}

        for sample in sample_list:
            decoded = self.decode(self.encode(sample))
            decoded_embeddings[sample.sample_id] = decoded
            cosine_scores.append(cosine_similarity(sample.embedding_vector, decoded))
            cosine_losses.append(cosine_loss(sample.embedding_vector, decoded))
            reconstruction_losses.append(mse_loss(sample.embedding_vector, decoded))
            ce_losses.append(
                cross_entropy_distribution_loss(
                    self._family_distribution(sample),
                    _observed_family_distribution(sample),
                )
            )
            frame_losses.append(frame_ranking_loss(sample))
            symbolic_penalties.append(symbolic_validity_penalty(sample))

        return AutoencoderEvaluation(
            sample_count=len(sample_list),
            embedding_cosine_similarity=_mean(cosine_scores),
            cosine_loss=_mean(cosine_losses),
            reconstruction_loss=_mean(reconstruction_losses),
            cross_entropy_loss=_mean(ce_losses),
            frame_ranking_loss=_mean(frame_losses),
            symbolic_validity_penalty=_mean(symbolic_penalties),
            decoded_embeddings=decoded_embeddings,
            legal_ir_target_count=legal_ir_payload["target_count"],
            legal_ir_losses=legal_ir_payload["losses"],
            legal_ir_target_hashes=legal_ir_payload["target_hashes"],
            legal_ir_view_distribution=legal_ir_payload["view_distribution"],
        )

    def encode(self, sample: LegalSample) -> Dict[str, object]:
        """Encode sample into a deterministic intermediate representation."""
        return {
            "embedding": list(sample.embedding_vector),
            "families": self._family_distribution(sample),
            "sample_id": sample.sample_id,
            "selected_frame": sample.selected_frame,
        }

    def decode(self, encoded: Mapping[str, object]) -> List[float]:
        """Decode intermediate representation back to an embedding vector."""
        return [float(value) for value in encoded.get("embedding", [])]  # type: ignore[arg-type]

    def _target_family(self, sample: LegalSample) -> str:
        return _target_family(sample)

    def _family_distribution(self, sample: LegalSample) -> Dict[str, float]:
        return _observed_family_distribution(sample)


class AdaptiveModalAutoencoder:
    """Small trainable modal encoder/decoder used by the TODO supervisor.

    This is an adaptive diagnostic/advisor, not the canonical legal
    representation.  The expert-auditable path is the deterministic modal
    compiler/decompiler in ``ipfs_datasets_py.logic.modal``; this class keeps
    feature-level nudges only to identify where vague text, frame choice, or
    reconstruction may need compiler-rule improvements.
    """

    def __init__(
        self,
        *,
        state: Optional[ModalAutoencoderTrainingState] = None,
        initial_embedding_scale: float = 0.0,
        modal_families: Optional[Sequence[str]] = None,
        feature_codec: Optional[Any] = None,
        feature_embedding_weight_scale: float = 0.5,
        family_embedding_weight_scale: float = 0.5,
        feature_family_logit_scale: float = 0.0,
        legal_ir_view_logit_scale: float = 1.0,
        legal_ir_view_embedding_weight_scale: float = 0.5,
        cosine_reconstruction_weight: float = 0.25,
        max_token_features: int = 48,
        max_token_bigram_features: int = 24,
        max_token_trigram_features: int = 12,
        max_legal_ir_token_features: int = 24,
        max_legal_ir_token_bigram_features: int = 12,
        max_legal_ir_token_trigram_features: int = 8,
        feature_activity_reference: int = 64,
        feature_logit_clip: float = 24.0,
        compute_device: str = "auto",
    ) -> None:
        self.state = state or ModalAutoencoderTrainingState()
        self.initial_embedding_scale = float(initial_embedding_scale)
        self.modal_families = tuple(modal_families or _all_modal_families())
        self.feature_codec = feature_codec
        self.feature_embedding_weight_scale = max(
            0.0,
            float(feature_embedding_weight_scale),
        )
        self.family_embedding_weight_scale = max(
            0.0,
            float(family_embedding_weight_scale),
        )
        self.feature_family_logit_scale = max(0.0, float(feature_family_logit_scale))
        self.legal_ir_view_logit_scale = max(0.0, float(legal_ir_view_logit_scale))
        self.legal_ir_view_embedding_weight_scale = max(
            0.0,
            float(legal_ir_view_embedding_weight_scale),
        )
        self.cosine_reconstruction_weight = max(0.0, float(cosine_reconstruction_weight))
        self.max_token_features = max(0, int(max_token_features))
        self.max_token_bigram_features = max(0, int(max_token_bigram_features))
        self.max_token_trigram_features = max(0, int(max_token_trigram_features))
        self.max_legal_ir_token_features = max(0, int(max_legal_ir_token_features))
        self.max_legal_ir_token_bigram_features = max(
            0,
            int(max_legal_ir_token_bigram_features),
        )
        self.max_legal_ir_token_trigram_features = max(
            0,
            int(max_legal_ir_token_trigram_features),
        )
        self.feature_activity_reference = max(8, int(feature_activity_reference))
        self.feature_logit_clip = max(0.0, float(feature_logit_clip))
        (
            self.compute_device_request,
            self.compute_backend,
            self.compute_device,
            self._torch,
        ) = _resolve_vector_compute_backend(compute_device)
        self._sample_feature_cache: Dict[tuple[str, int], Dict[str, Any]] = {}
        self._legal_ir_loss_target_cache: Dict[str, Dict[str, float]] = {}
        self._legal_ir_view_target_cache: Dict[str, Dict[str, float]] = {}

    def evaluate(
        self,
        samples: Iterable[LegalSample],
        *,
        legal_ir_bridge_names: Sequence[str] = (),
        legal_ir_evaluate_provers: Optional[bool] = None,
        legal_ir_targets: Optional[Mapping[str, Any] | Sequence[Any]] = None,
        legal_ir_parallel_workers: Optional[int] = None,
        use_sample_memory: bool = True,
    ) -> AutoencoderEvaluation:
        """Evaluate current encoder/decoder state against legal samples."""
        sample_list = list(samples)
        if not sample_list:
            return AutoencoderEvaluation(
                sample_count=0,
                embedding_cosine_similarity=0.0,
                cosine_loss=0.0,
                reconstruction_loss=0.0,
                cross_entropy_loss=0.0,
                frame_ranking_loss=0.0,
                symbolic_validity_penalty=0.0,
                decoded_embeddings={},
            )
        legal_ir_payload = _legal_ir_target_payload(
            sample_list,
            bridge_names=legal_ir_bridge_names,
            evaluate_provers=legal_ir_evaluate_provers,
            legal_ir_targets=legal_ir_targets,
            parallel_workers=legal_ir_parallel_workers,
        )
        legal_ir_target_distributions: Mapping[str, Mapping[str, float]] = legal_ir_payload[
            "target_view_distributions_by_sample"
        ]
        legal_ir_target_losses: Mapping[str, Mapping[str, float]] = legal_ir_payload[
            "target_losses_by_sample"
        ]
        self._cache_legal_ir_targets(
            sample_list,
            legal_ir_target_distributions,
            legal_ir_target_losses,
        )

        cosine_scores: List[float] = []
        cosine_losses: List[float] = []
        reconstruction_losses: List[float] = []
        probability_maps: List[Mapping[str, float]] = []
        target_maps: List[Mapping[str, float]] = []
        frame_losses: List[float] = []
        symbolic_penalties: List[float] = []
        decoded_embeddings: Dict[str, List[float]] = {}
        target_vectors: List[List[float]] = []
        decoded_vectors: List[List[float]] = []

        for sample in sample_list:
            decoded = self.decode(self.encode(sample, use_sample_memory=use_sample_memory))
            decoded_embeddings[sample.sample_id] = decoded
            target_vectors.append(list(sample.embedding_vector))
            decoded_vectors.append(decoded)
            probability_maps.append(
                self._family_distribution(
                    sample,
                    use_sample_memory=use_sample_memory,
                )
            )
            target_maps.append(_observed_family_distribution(sample))
            frame_losses.append(frame_ranking_loss(sample))
            symbolic_penalties.append(symbolic_validity_penalty(sample))

        cosine_scores, reconstruction_losses = self._embedding_metrics(
            target_vectors,
            decoded_vectors,
        )
        cosine_losses = [1.0 - value for value in cosine_scores]
        ce_losses = self._cross_entropy_distribution_losses(
            probability_maps,
            target_maps,
        )
        legal_ir_losses = dict(legal_ir_payload["losses"])
        legal_ir_view_ce_losses: List[float] = []
        predicted_view_distributions: List[Mapping[str, float]] = []
        for sample in sample_list:
            target_view_distribution = legal_ir_target_distributions.get(sample.sample_id)
            if not target_view_distribution:
                continue
            predicted_view_distribution = self._legal_ir_view_distribution(
                sample,
                target_view_distribution,
                use_sample_memory=use_sample_memory,
            )
            predicted_view_distributions.append(predicted_view_distribution)
            legal_ir_view_ce_losses.append(
                cross_entropy_distribution_loss(
                    predicted_view_distribution,
                    target_view_distribution,
                )
            )
        if legal_ir_view_ce_losses:
            legal_ir_losses["legal_ir_view_cross_entropy_loss"] = _mean(
                legal_ir_view_ce_losses
            )

        return AutoencoderEvaluation(
            sample_count=len(sample_list),
            embedding_cosine_similarity=_mean(cosine_scores),
            cosine_loss=_mean(cosine_losses),
            reconstruction_loss=_mean(reconstruction_losses),
            cross_entropy_loss=_mean(ce_losses),
            frame_ranking_loss=_mean(frame_losses),
            symbolic_validity_penalty=_mean(symbolic_penalties),
            decoded_embeddings=decoded_embeddings,
            legal_ir_target_count=legal_ir_payload["target_count"],
            legal_ir_losses=legal_ir_losses,
            legal_ir_predicted_view_distribution=_mean_distributions(
                predicted_view_distributions
            ),
            legal_ir_target_hashes=legal_ir_payload["target_hashes"],
            legal_ir_view_distribution=legal_ir_payload["view_distribution"],
        )

    def _cache_legal_ir_targets(
        self,
        samples: Sequence[LegalSample],
        target_view_distributions: Mapping[str, Mapping[str, float]],
        target_losses_by_sample: Mapping[str, Mapping[str, float]],
    ) -> None:
        """Prime LegalIR target caches before decoding/evaluating samples."""
        for sample in samples:
            target_view_distribution = target_view_distributions.get(sample.sample_id)
            if target_view_distribution:
                cached_distribution = {
                    str(name): float(value)
                    for name, value in target_view_distribution.items()
                }
                self._legal_ir_view_target_cache[sample.sample_id] = cached_distribution
                self._legal_ir_view_target_cache[
                    _sample_content_cache_id(sample)
                ] = cached_distribution
            target_losses = target_losses_by_sample.get(sample.sample_id)
            if target_losses:
                cached_losses = {
                    str(name): float(value)
                    for name, value in target_losses.items()
                }
                self._legal_ir_loss_target_cache[sample.sample_id] = cached_losses
                self._legal_ir_loss_target_cache[
                    _sample_content_cache_id(sample)
                ] = cached_losses

    def encode(self, sample: LegalSample, *, use_sample_memory: bool = True) -> Dict[str, object]:
        """Encode sample into the current intermediate representation state."""
        return {
            "family_distribution": self._family_distribution(
                sample,
                use_sample_memory=use_sample_memory,
            ),
            "sample_id": sample.sample_id,
            "selected_frame": sample.selected_frame,
            "target_family": _target_family(sample),
            "target_family_distribution": _observed_family_distribution(sample),
            "embedding_projection": self._decoded_for(sample, use_sample_memory=use_sample_memory),
        }

    def decode(self, encoded: Mapping[str, object]) -> List[float]:
        """Decode the intermediate representation into an embedding vector."""
        return [
            float(value)
            for value in encoded.get("embedding_projection", [])  # type: ignore[arg-type]
        ]

    def introspect_sample(
        self,
        sample: LegalSample,
        *,
        use_sample_memory: bool = False,
        top_k: int = 8,
    ) -> AutoencoderIntrospection:
        """Explain which adaptive features influenced this sample.

        The default ignores sample-specific memory so the resulting evidence is
        suitable for deterministic compiler/decompiler synthesis.
        """
        logits = self._logits_for(sample, use_sample_memory=use_sample_memory)
        probabilities = _softmax(logits)
        target_family = _target_family(sample)
        predicted_family = max(
            probabilities,
            key=lambda family: (probabilities[family], family),
        ) if probabilities else ModalLogicFamily.HYBRID.value
        target_probability = float(probabilities.get(target_family, 0.0))
        predicted_probability = float(probabilities.get(predicted_family, 0.0))
        other_probabilities = [
            value for family, value in probabilities.items() if family != target_family
        ]
        best_other = max(other_probabilities) if other_probabilities else 0.0
        decoded = self._decoded_for(sample, use_sample_memory=use_sample_memory)
        base_decoded = self._base_decoded_for(sample)
        residual = [
            float(target_value) - float(decoded_value)
            for target_value, decoded_value in zip(sample.embedding_vector, decoded)
        ]
        feature_keys = self._feature_keys_for(sample)
        family_contributions = self._family_contributions_for(
            sample,
            feature_keys,
            use_sample_memory=use_sample_memory,
        )
        embedding_contributions = self._embedding_contributions_for(
            feature_keys,
            residual,
            dimensions=len(sample.embedding_vector),
            sample=sample,
            use_sample_memory=use_sample_memory,
        )
        legal_ir_view_distribution = self._legal_ir_view_target_cache.get(
            sample.sample_id,
            self._legal_ir_view_target_cache.get(_sample_content_cache_id(sample), {}),
        )
        legal_ir_losses = self._legal_ir_loss_target_cache.get(
            sample.sample_id,
            self._legal_ir_loss_target_cache.get(_sample_content_cache_id(sample), {}),
        )
        legal_ir_predicted_view_distribution: Dict[str, float] = {}
        legal_ir_view_cross_entropy_loss = 0.0
        if legal_ir_view_distribution:
            legal_ir_predicted_view_distribution = self._legal_ir_view_distribution(
                sample,
                legal_ir_view_distribution,
                use_sample_memory=use_sample_memory,
            )
            legal_ir_view_cross_entropy_loss = cross_entropy_distribution_loss(
                legal_ir_predicted_view_distribution,
                legal_ir_view_distribution,
            )
        legal_ir_component_gaps = _legal_ir_component_gaps(
            legal_ir_view_distribution,
            legal_ir_predicted_view_distribution,
        )
        legal_ir_underrepresented_components = _top_legal_ir_component_gaps(
            legal_ir_component_gaps,
            positive=True,
        )
        legal_ir_overrepresented_components = _top_legal_ir_component_gaps(
            legal_ir_component_gaps,
            positive=False,
        )
        return AutoencoderIntrospection(
            sample_id=sample.sample_id,
            target_family=target_family,
            predicted_family=predicted_family,
            target_probability=round(target_probability, 12),
            predicted_probability=round(predicted_probability, 12),
            family_margin=round(target_probability - best_other, 12),
            cosine_similarity=round(cosine_similarity(sample.embedding_vector, decoded), 12),
            reconstruction_loss=round(mse_loss(sample.embedding_vector, decoded), 12),
            residual_vector=[round(value, 12) for value in residual],
            base_decoded_embedding=[round(float(value), 12) for value in base_decoded],
            decoded_embedding=[round(float(value), 12) for value in decoded],
            feature_count=len(feature_keys),
            sample_memory_used=use_sample_memory,
            top_family_contributions=family_contributions[:max(top_k, 0)],
            top_embedding_contributions=embedding_contributions[:max(top_k, 0)],
            legal_ir_view_cross_entropy_loss=round(legal_ir_view_cross_entropy_loss, 12),
            legal_ir_component_gaps={
                key: round(float(value), 12)
                for key, value in sorted(legal_ir_component_gaps.items())
            },
            legal_ir_losses={
                key: round(float(value), 12)
                for key, value in sorted(legal_ir_losses.items())
            },
            legal_ir_underrepresented_components=legal_ir_underrepresented_components,
            legal_ir_overrepresented_components=legal_ir_overrepresented_components,
            legal_ir_view_distribution={
                key: round(float(value), 12)
                for key, value in sorted(legal_ir_view_distribution.items())
            },
            legal_ir_predicted_view_distribution={
                key: round(float(value), 12)
                for key, value in sorted(legal_ir_predicted_view_distribution.items())
            },
            synthesis_focus=self._synthesis_focus_for(
                sample,
                target_family=target_family,
                predicted_family=predicted_family,
                target_probability=target_probability,
                reconstruction_loss=mse_loss(sample.embedding_vector, decoded),
                legal_ir_view_cross_entropy_loss=legal_ir_view_cross_entropy_loss,
                legal_ir_view_distribution=legal_ir_view_distribution,
                legal_ir_predicted_view_distribution=legal_ir_predicted_view_distribution,
            ),
        )

    def codex_call_decision(
        self,
        sample: LegalSample,
        *,
        config: Optional[CodexCallGateConfig] = None,
        cache: Optional[CodexCallCache] = None,
        prover_signal: Optional[ProverCompilationSignal] = None,
        legal_ir_bridge_names: Sequence[str] | str = (),
        legal_ir_targets: Optional[Mapping[str, Any] | Sequence[Any]] = None,
        use_sample_memory: bool = False,
    ) -> CodexCallDecision:
        """Decide whether this sample is worth an expensive Codex advisor call."""
        gate = config or CodexCallGateConfig()
        evaluation = self.evaluate(
            [sample],
            legal_ir_bridge_names=legal_ir_bridge_names,
            legal_ir_targets=legal_ir_targets,
            use_sample_memory=use_sample_memory,
        )
        metrics = {
            "cosine_loss": evaluation.cosine_loss,
            "cross_entropy_loss": evaluation.cross_entropy_loss,
            "embedding_cosine_similarity": evaluation.embedding_cosine_similarity,
            "frame_ranking_loss": evaluation.frame_ranking_loss,
            "legal_ir_target_count": float(evaluation.legal_ir_target_count),
            "reconstruction_loss": evaluation.reconstruction_loss,
            "symbolic_validity_penalty": evaluation.symbolic_validity_penalty,
        }
        metrics.update(
            {
                str(name): float(value)
                for name, value in sorted(evaluation.legal_ir_losses.items())
            }
        )
        feature_signature = self.codex_feature_signature(sample)
        text_hash = _hash_text(sample.normalized_text)
        feature_signature_hash = _hash_json(feature_signature)
        reasons: List[str] = []
        suppressed_reasons: List[str] = []

        if evaluation.embedding_cosine_similarity < gate.min_cosine_similarity:
            reasons.append("low_embedding_cosine_similarity")
        if evaluation.cross_entropy_loss > gate.max_cross_entropy_loss:
            reasons.append("high_cross_entropy_loss")
        if evaluation.reconstruction_loss > gate.max_reconstruction_loss:
            reasons.append("high_reconstruction_loss")
        if evaluation.frame_ranking_loss > gate.max_frame_ranking_loss:
            reasons.append("frame_ranking_uncertain")
        if evaluation.symbolic_validity_penalty > gate.max_symbolic_validity_penalty:
            reasons.append("missing_or_invalid_symbolic_ir")
        if evaluation.legal_ir_target_count > 0:
            if (
                metrics.get("legal_ir_multiview_total_loss", 0.0)
                > gate.max_legal_ir_multiview_total_loss
            ):
                reasons.append("high_legal_ir_multiview_total_loss")
            if (
                metrics.get("legal_ir_view_cross_entropy_loss", 0.0)
                > gate.max_legal_ir_view_cross_entropy_loss
            ):
                reasons.append("high_legal_ir_view_cross_entropy_loss")
            if (
                metrics.get("legal_ir_multiview_proof_failure_ratio", 0.0)
                > gate.max_legal_ir_proof_failure_ratio
            ):
                reasons.append("legal_ir_prover_gate_failed")
            if (
                metrics.get("legal_ir_multiview_graph_failure_penalty", 0.0)
                > gate.max_legal_ir_graph_failure_penalty
            ):
                reasons.append("legal_ir_graph_projection_failed")

        if gate.require_prover_compilation:
            resolved_prover_signal = prover_signal or evaluate_modal_prover_compilation(sample)
            prover_signal = resolved_prover_signal
            if resolved_prover_signal.attempted_count == 0:
                reasons.append("no_modal_formula_for_prover")
            elif not resolved_prover_signal.compiles:
                if resolved_prover_signal.unavailable_count:
                    reasons.append("prover_route_unavailable")
                if resolved_prover_signal.error_count:
                    reasons.append("prover_error")
                if resolved_prover_signal.failed_count:
                    reasons.append("prover_rejected_ir")

        local_loss = _codex_gate_local_loss(
            metrics,
            gate,
            prover_signal=prover_signal,
        )
        net_benefit = local_loss - max(0.0, float(gate.codex_call_cost))

        if cache is not None:
            if (
                gate.max_codex_calls is not None
                and cache.codex_call_count >= gate.max_codex_calls
            ):
                suppressed_reasons.append("codex_call_budget_exhausted")
            if not gate.allow_repeat_signatures:
                if text_hash in cache.codex_text_hashes:
                    suppressed_reasons.append("duplicate_text_hash")
                if feature_signature_hash in cache.codex_feature_signature_hashes:
                    suppressed_reasons.append("duplicate_feature_signature")

        if net_benefit < gate.min_net_benefit:
            suppressed_reasons.append("codex_cost_exceeds_expected_benefit")

        should_call = bool(reasons) and not suppressed_reasons
        return CodexCallDecision(
            should_call_codex=should_call,
            reasons=_unique_preserve_order(reasons),
            suppressed_reasons=_unique_preserve_order(suppressed_reasons),
            local_loss=round(local_loss, 12),
            codex_call_cost=round(max(0.0, float(gate.codex_call_cost)), 12),
            net_benefit=round(net_benefit, 12),
            text_hash=text_hash,
            feature_signature=feature_signature,
            feature_signature_hash=feature_signature_hash,
            metrics={key: round(float(value), 12) for key, value in metrics.items()},
            prover_signal=prover_signal,
        )

    def codex_feature_signature(self, sample: LegalSample) -> List[str]:
        """Return the stable signature used to batch or suppress Codex calls."""
        keys = [
            f"text-shape:{_text_shape(sample.normalized_text)}",
            f"formula-count:{len(sample.modal_ir.formulas)}",
        ]
        keys.extend(self._feature_keys_for(sample))
        return _unique_preserve_order(keys)

    def apply_todos(
        self,
        todos: Iterable[object],
        samples_by_id: Mapping[str, LegalSample],
        *,
        learning_rate: float = 0.35,
    ) -> List[Dict[str, Any]]:
        """Apply a batch of claimed TODOs as deterministic optimizer updates."""
        return [
            self.apply_todo(todo, samples_by_id, learning_rate=learning_rate)
            for todo in todos
        ]

    def apply_todo(
        self,
        todo: object,
        samples_by_id: Mapping[str, LegalSample],
        *,
        learning_rate: float = 0.35,
    ) -> Dict[str, Any]:
        """Apply one TODO and return a compact update report."""
        action = str(getattr(todo, "action", ""))
        loss_name = str(getattr(todo, "loss_name", ""))
        todo_id = str(getattr(todo, "todo_id", ""))
        sample_ids = [str(value) for value in getattr(todo, "sample_ids", [])]
        changed: List[str] = []

        trainable = (
            action
            in {
                "improve_encoder_decoder_reconstruction",
                "improve_legal_ir_view_distribution",
                "improve_modal_family_classifier",
            }
            or loss_name
            in {
                "cosine_loss",
                "cross_entropy_loss",
                "legal_ir_view_cross_entropy_loss",
                "reconstruction_loss",
            }
        )
        if not trainable:
            return {
                "action": action,
                "changed": [],
                "reason": "todo targets deterministic program synthesis, not autoencoder SGD",
                "sample_ids": sample_ids,
                "skipped": True,
                "todo_id": todo_id,
            }

        for sample_id in sample_ids:
            sample = samples_by_id.get(sample_id)
            if sample is None:
                continue
            if action == "improve_modal_family_classifier" or loss_name == "cross_entropy_loss":
                self._nudge_family_logits(sample, learning_rate=learning_rate)
                changed.append("family_logits")
            if (
                action == "improve_legal_ir_view_distribution"
                or loss_name == "legal_ir_view_cross_entropy_loss"
            ):
                if self._nudge_legal_ir_view_logits(sample, learning_rate=learning_rate):
                    changed.append("legal_ir_view_logits")
            if (
                action == "improve_encoder_decoder_reconstruction"
                or loss_name in {"cosine_loss", "reconstruction_loss"}
            ):
                self._nudge_decoded_embedding(sample, learning_rate=learning_rate)
                changed.append("decoded_embedding")

        if todo_id and todo_id not in self.state.applied_todo_ids:
            self.state.applied_todo_ids.append(todo_id)
        return {
            "action": action,
            "changed": sorted(set(changed)),
            "sample_ids": sample_ids,
            "todo_id": todo_id,
        }

    def train_generalizable_projection(
        self,
        samples: Sequence[LegalSample],
        *,
        validation_samples: Optional[Sequence[LegalSample]] = None,
        legal_ir_bridge_names: Sequence[str] = (),
        legal_ir_evaluate_provers: Optional[bool] = None,
        legal_ir_targets: Optional[Mapping[str, Any] | Sequence[Any]] = None,
        legal_ir_parallel_workers: Optional[int] = None,
        epochs: int = 3,
        learning_rate: float = 0.35,
        l2_regularization: float = 0.0,
        max_cosine_regression: float = 0.01,
        max_reconstruction_regression: float = 0.02,
        max_cross_entropy_regression: float = 0.0,
        max_legal_ir_loss_regression: float = 0.02,
        objective_cross_entropy_weight: float = 1.0,
        objective_reconstruction_weight: float = 1.0,
        objective_cosine_gap_weight: float = 1.0,
        objective_legal_ir_weight: float = 1.0,
        hard_example_fraction: float = 1.0,
    ) -> Dict[str, Any]:
        """Train feature-level weights with rollback on holdout regression.

        This guarded path keeps sample-memory disabled for updates, so any
        accepted improvement must come from reusable feature embeddings/logits.
        """
        sample_list = list(samples)
        validation_list = list(validation_samples or [])
        target_samples = validation_list or sample_list
        evaluation_kwargs: Dict[str, Any] = {
            "legal_ir_bridge_names": legal_ir_bridge_names,
            "legal_ir_evaluate_provers": legal_ir_evaluate_provers,
            "legal_ir_targets": legal_ir_targets,
            "legal_ir_parallel_workers": legal_ir_parallel_workers,
            "use_sample_memory": False,
        }
        before = self.evaluate(target_samples, **evaluation_kwargs)
        if sample_list and validation_list:
            # Prime LegalIR target caches for training samples before feature-level
            # nudges.  Validation-only evaluation intentionally does not touch
            # training sample cache entries.
            self.evaluate(sample_list, **evaluation_kwargs)
        best_state = self.state.copy()
        best = before
        accepted_epochs = 0
        epoch_reports: List[Dict[str, Any]] = []
        objective_weights = {
            "cross_entropy": max(0.0, float(objective_cross_entropy_weight)),
            "reconstruction": max(0.0, float(objective_reconstruction_weight)),
            "cosine_gap": max(0.0, float(objective_cosine_gap_weight)),
            "legal_ir": max(0.0, float(objective_legal_ir_weight)),
        }
        hard_fraction = max(0.0, min(1.0, float(hard_example_fraction)))

        candidate_updates = (
            ("family_logits", ("family_logits",)),
            ("decoded_embedding", ("decoded_embedding",)),
            ("legal_ir_view_logits", ("legal_ir_view_logits",)),
            (
                "combined",
                ("family_logits", "decoded_embedding", "legal_ir_view_logits"),
            ),
        )

        for epoch in range(1, max(0, int(epochs)) + 1):
            epoch_before_state = self.state.copy()
            candidate_reports: List[Dict[str, Any]] = []
            selected: Optional[tuple[float, AutoencoderEvaluation, ModalAutoencoderTrainingState, str]] = None
            update_samples = self._select_hard_examples_for_projection(
                sample_list,
                hard_example_fraction=hard_fraction,
                objective_weights=objective_weights,
            )

            for update_name, update_targets in candidate_updates:
                self.state = epoch_before_state.copy()
                for sample in update_samples:
                    if "family_logits" in update_targets:
                        self._nudge_family_logits(
                            sample,
                            learning_rate=learning_rate,
                            update_sample_memory=False,
                        )
                    if "decoded_embedding" in update_targets:
                        self._nudge_decoded_embedding(
                            sample,
                            learning_rate=learning_rate,
                            update_sample_memory=False,
                        )
                    if "legal_ir_view_logits" in update_targets:
                        self._nudge_legal_ir_view_logits(
                            sample,
                            learning_rate=learning_rate,
                            update_sample_memory=False,
                        )
                self._regularize_feature_state(l2_regularization)
                after = self.evaluate(target_samples, **evaluation_kwargs)
                regressions = _evaluation_regressions_for_training(
                    best,
                    after,
                    max_cosine_regression=max_cosine_regression,
                    max_reconstruction_regression=max_reconstruction_regression,
                    max_cross_entropy_regression=max_cross_entropy_regression,
                    max_legal_ir_loss_regression=max_legal_ir_loss_regression,
                )
                objective_delta = (
                    _evaluation_objective_for_training(
                        best,
                        **objective_weights,
                    )
                    - _evaluation_objective_for_training(
                        after,
                        **objective_weights,
                    )
                )
                improved = _evaluation_improved_for_training(
                    best,
                    after,
                    max_cosine_regression=max_cosine_regression,
                    max_reconstruction_regression=max_reconstruction_regression,
                    max_cross_entropy_regression=max_cross_entropy_regression,
                    max_legal_ir_loss_regression=max_legal_ir_loss_regression,
                )
                candidate_reports.append(
                    {
                        "accepted": improved,
                        "cross_entropy_delta": best.cross_entropy_loss
                        - after.cross_entropy_loss,
                        "hard_example_count": len(update_samples),
                        "hard_example_fraction": hard_fraction,
                        "cosine_similarity_delta": (
                            after.embedding_cosine_similarity
                            - best.embedding_cosine_similarity
                        ),
                        "legal_ir_view_cross_entropy_delta": (
                            float(
                                best.legal_ir_losses.get(
                                    "legal_ir_view_cross_entropy_loss",
                                    0.0,
                                )
                            )
                            - float(
                                after.legal_ir_losses.get(
                                    "legal_ir_view_cross_entropy_loss",
                                    0.0,
                                )
                            )
                        ),
                        "objective_delta": objective_delta,
                        "pareto_regressions": regressions,
                        "reconstruction_delta": best.reconstruction_loss
                        - after.reconstruction_loss,
                        "update": update_name,
                    }
                )
                if improved and (
                    selected is None or objective_delta > selected[0]
                ):
                    selected = (
                        objective_delta,
                        after,
                        self.state.copy(),
                        update_name,
                    )

            if selected is None:
                self.state = epoch_before_state
                epoch_reports.append(
                    {
                        "accepted": False,
                        "candidate_reports": candidate_reports,
                        "epoch": epoch,
                        "objective_delta": max(
                            (
                                float(report.get("objective_delta", 0.0))
                                for report in candidate_reports
                            ),
                            default=0.0,
                        ),
                        "selected_update": None,
                    }
                )
                break

            objective_delta, after, selected_state, update_name = selected
            self.state = selected_state
            best = after
            best_state = self.state.copy()
            accepted_epochs += 1
            selected_report = next(
                report
                for report in candidate_reports
                if report["update"] == update_name
            )
            epoch_reports.append(
                {
                    **selected_report,
                    "accepted": True,
                    "candidate_reports": candidate_reports,
                    "epoch": epoch,
                    "objective_delta": objective_delta,
                    "selected_update": update_name,
                }
            )

        self.state = best_state
        return {
            "accepted_epochs": accepted_epochs,
            "after": best.to_dict(),
            "before": before.to_dict(),
            "compute_backend": self.compute_backend_metadata(),
            "epoch_reports": epoch_reports,
            "objective_weights": dict(objective_weights),
            "sample_memory_used": False,
            "validation_sample_count": len(target_samples),
        }

    def _select_hard_examples_for_projection(
        self,
        samples: Sequence[LegalSample],
        *,
        hard_example_fraction: float,
        objective_weights: Mapping[str, float],
    ) -> List[LegalSample]:
        if not samples:
            return []
        if hard_example_fraction >= 1.0 or len(samples) == 1:
            return list(samples)
        ranked = sorted(
            (
                (
                    self._sample_training_objective(
                        sample,
                        objective_weights=objective_weights,
                    ),
                    sample,
                )
                for sample in samples
            ),
            key=lambda item: item[0],
            reverse=True,
        )
        keep = max(1, int(math.ceil(len(ranked) * hard_example_fraction)))
        return [sample for _, sample in ranked[:keep]]

    def _sample_training_objective(
        self,
        sample: LegalSample,
        *,
        objective_weights: Mapping[str, float],
    ) -> float:
        ce_weight = max(0.0, float(objective_weights.get("cross_entropy", 1.0)))
        rec_weight = max(0.0, float(objective_weights.get("reconstruction", 1.0)))
        cos_weight = max(0.0, float(objective_weights.get("cosine_gap", 1.0)))
        legal_weight = max(0.0, float(objective_weights.get("legal_ir", 1.0)))

        decoded = self._decoded_for(sample, use_sample_memory=False)
        reconstruction = mse_loss(sample.embedding_vector, decoded)
        cosine_gap = max(0.0, 1.0 - cosine_similarity(sample.embedding_vector, decoded))
        distribution = self._family_distribution(sample, use_sample_memory=False)
        cross_entropy = cross_entropy_distribution_loss(
            distribution,
            _observed_family_distribution(sample),
        )

        legal_ir_loss = 0.0
        target_distribution = self._legal_ir_view_target_cache.get(sample.sample_id)
        if target_distribution:
            predicted = self._legal_ir_view_distribution(
                sample,
                target_distribution,
                use_sample_memory=False,
            )
            legal_ir_loss = cross_entropy_distribution_loss(predicted, target_distribution)

        return (
            (ce_weight * cross_entropy)
            + (rec_weight * reconstruction)
            + (cos_weight * cosine_gap)
            + (legal_weight * legal_ir_loss)
        )

    def _decoded_for(self, sample: LegalSample, *, use_sample_memory: bool = True) -> List[float]:
        stored = self.state.decoded_embeddings.get(sample.sample_id) if use_sample_memory else None
        if stored is not None and len(stored) == len(sample.embedding_vector):
            return list(stored)
        base = self._base_decoded_for(sample)
        family_adjustment = self._family_embedding_adjustment(
            sample,
            dimensions=len(base),
            use_sample_memory=use_sample_memory,
        )
        legal_ir_view_adjustment = self._legal_ir_view_embedding_adjustment(
            sample,
            dimensions=len(base),
            use_sample_memory=use_sample_memory,
        )
        adjustment = self._feature_embedding_adjustment(sample, dimensions=len(base))
        return [
            base_value + family_value + view_value + adjustment_value
            for base_value, family_value, view_value, adjustment_value in zip(
                base,
                family_adjustment,
                legal_ir_view_adjustment,
                adjustment,
            )
        ]

    def _base_decoded_for(self, sample: LegalSample) -> List[float]:
        cache = self._sample_cache_for(sample)
        cached = cache.get("base_decoded")
        if isinstance(cached, list) and len(cached) == len(sample.embedding_vector):
            return [float(value) for value in cached]

        if self.feature_codec is not None and hasattr(
            self.feature_codec,
            "decode_sample_embedding",
        ):
            decoded = self.feature_codec.decode_sample_embedding(
                sample,
                dimensions=len(sample.embedding_vector),
            )
            if len(decoded) == len(sample.embedding_vector):
                result = [float(value) for value in decoded]
                cache["base_decoded"] = list(result)
                return result
        result = [self.initial_embedding_scale * float(value) for value in sample.embedding_vector]
        cache["base_decoded"] = list(result)
        return result

    def _family_distribution(
        self,
        sample: LegalSample,
        *,
        use_sample_memory: bool = True,
    ) -> Dict[str, float]:
        return _softmax(self._logits_for(sample, use_sample_memory=use_sample_memory))

    def _legal_ir_view_distribution(
        self,
        sample: LegalSample,
        target_distribution: Mapping[str, float],
        *,
        use_sample_memory: bool = True,
    ) -> Dict[str, float]:
        families = _unique_preserve_order(
            [str(name) for name in target_distribution.keys()]
            + [
                str(family)
                for family in self.state.legal_ir_view_logits.keys()
                if self._is_legal_ir_view_family(str(family))
            ]
            + [
                str(family)
                for logits in self.state.feature_legal_ir_view_logits.values()
                for family in logits.keys()
                if self._is_legal_ir_view_family(str(family))
            ]
            + [
                str(family)
                for logits in self.state.feature_family_logits.values()
                for family in logits.keys()
                if self._is_legal_ir_view_family(str(family))
            ]
            + [
                str(family)
                for family in self.state.family_logits.get(sample.sample_id, {}).keys()
                if self._is_legal_ir_view_family(str(family))
            ]
        )
        logits = self._legal_ir_view_logits_for(
            sample,
            families,
            use_sample_memory=use_sample_memory,
        )
        return _softmax(logits)

    def _legal_ir_view_target_distribution_for_sample(
        self,
        sample: LegalSample,
    ) -> Dict[str, float]:
        distribution = self._legal_ir_view_target_cache.get(
            sample.sample_id,
            self._legal_ir_view_target_cache.get(_sample_content_cache_id(sample), {}),
        )
        return {
            str(name): _float_or_zero(value)
            for name, value in dict(distribution or {}).items()
            if _float_or_zero(value) > 0.0
        }

    def _legal_ir_view_distribution_for_embedding(
        self,
        sample: LegalSample,
        *,
        use_sample_memory: bool,
    ) -> Dict[str, float]:
        target_distribution = self._legal_ir_view_target_distribution_for_sample(sample)
        if target_distribution:
            return self._legal_ir_view_distribution(
                sample,
                target_distribution,
                use_sample_memory=use_sample_memory,
            )
        families = _unique_preserve_order(
            [
                str(view)
                for view in self.state.legal_ir_view_embedding_weights.keys()
                if self._is_legal_ir_view_family(str(view))
            ]
            + [
                str(view)
                for view in self.state.legal_ir_view_logits.keys()
                if self._is_legal_ir_view_family(str(view))
            ]
            + [
                str(view)
                for logits in self.state.feature_legal_ir_view_logits.values()
                for view in logits.keys()
                if self._is_legal_ir_view_family(str(view))
            ]
            + [
                str(view)
                for logits in self.state.feature_family_logits.values()
                for view in logits.keys()
                if self._is_legal_ir_view_family(str(view))
            ]
        )
        if not families:
            return {}
        return _softmax(
            self._legal_ir_view_logits_for(
                sample,
                families,
                use_sample_memory=use_sample_memory,
            )
        )

    def _is_legal_ir_view_family(self, family: str) -> bool:
        return str(family) not in self.modal_families

    def _legal_ir_view_logits_for(
        self,
        sample: LegalSample,
        families: Sequence[str],
        *,
        use_sample_memory: bool,
    ) -> Dict[str, float]:
        """Return logits from the dedicated LegalIR view head."""
        logits = {
            str(family): float(self.state.legal_ir_view_logits.get(str(family), 0.0))
            * self.legal_ir_view_logit_scale
            for family in families
        }
        feature_keys = self._legal_ir_view_feature_keys_for(sample)
        feature_scale = 1.0 / self._feature_activity_scale(len(feature_keys))
        for feature in feature_keys:
            for family, value in self.state.feature_legal_ir_view_logits.get(feature, {}).items():
                family = str(family)
                if family in logits:
                    logits[family] += (
                        float(value)
                        * self.legal_ir_view_logit_scale
                        * feature_scale
                    )
            # Backwards compatibility: older warm-starts stored LegalIR view
            # logits in the modal feature bucket, where the default modal scale
            # is zero.  Read those legal-view entries through the dedicated
            # scale so prior useful work remains visible.
            for family, value in self.state.feature_family_logits.get(feature, {}).items():
                family = str(family)
                if family in logits and self._is_legal_ir_view_family(family):
                    logits[family] += (
                        float(value)
                        * self.legal_ir_view_logit_scale
                        * feature_scale
                    )
        if use_sample_memory:
            for family, value in self.state.family_logits.get(sample.sample_id, {}).items():
                family = str(family)
                if family in logits and self._is_legal_ir_view_family(family):
                    logits[family] += float(value)
        return self._clip_logits(logits)

    def _logits_for(
        self,
        sample: LegalSample,
        *,
        use_sample_memory: bool = True,
    ) -> Dict[str, float]:
        logits = self._base_logits_for(sample)
        feature_keys = self._feature_keys_for(sample)
        feature_scale = 1.0 / self._feature_activity_scale(len(feature_keys))
        for feature in feature_keys:
            for family, value in self.state.feature_family_logits.get(feature, {}).items():
                if family in logits:
                    logits[family] += (
                        float(value)
                        * self.feature_family_logit_scale
                        * feature_scale
                    )
        if use_sample_memory:
            for family, value in self.state.family_logits.get(sample.sample_id, {}).items():
                if family in logits:
                    logits[family] += float(value)
        return self._clip_logits(logits)

    def _logits_for_families(
        self,
        sample: LegalSample,
        families: Sequence[str],
        *,
        use_sample_memory: bool,
    ) -> Dict[str, float]:
        base = self._base_logits_for(sample)
        logits = {
            str(family): float(base.get(str(family), 0.0))
            for family in families
        }
        feature_keys = self._feature_keys_for(sample)
        feature_scale = 1.0 / self._feature_activity_scale(len(feature_keys))
        for feature in feature_keys:
            for family, value in self.state.feature_family_logits.get(feature, {}).items():
                family = str(family)
                if family in logits:
                    logits[family] += (
                        float(value)
                        * self.feature_family_logit_scale
                        * feature_scale
                    )
        if use_sample_memory:
            for family, value in self.state.family_logits.get(sample.sample_id, {}).items():
                family = str(family)
                if family in logits:
                    logits[family] += float(value)
        return self._clip_logits(logits)

    def _base_logits_for(self, sample: LegalSample) -> Dict[str, float]:
        cache = self._sample_cache_for(sample)
        cached = cache.get("base_logits")
        if isinstance(cached, dict):
            logits = {
                family: float(cached.get(family, 0.0))
                for family in self.modal_families
            }
            return logits

        if self.feature_codec is not None and hasattr(
            self.feature_codec,
            "family_logits_for_sample",
        ):
            logits = self.feature_codec.family_logits_for_sample(
                sample,
                modal_families=self.modal_families,
            )
            logits = {str(family): float(value) for family, value in logits.items()}
        else:
            logits = {family: 0.0 for family in self.modal_families}
        for family in self.modal_families:
            logits.setdefault(family, 0.0)
        result = {
            family: float(logits.get(family, 0.0))
            for family in self.modal_families
        }
        cache["base_logits"] = dict(result)
        return result

    def _legal_ir_view_feature_keys_for(self, sample: LegalSample) -> List[str]:
        cache = self._sample_cache_for(sample)
        cached = cache.get("legal_ir_view_feature_keys")
        if isinstance(cached, list):
            return [str(value) for value in cached]

        keys = self._legal_ir_view_core_feature_keys_for(sample)
        # Include the legacy modal feature keys so warm-started LegalIR view
        # logits written before the dedicated head remain reusable.
        keys.extend(self._feature_keys_for(sample))
        result = _unique_preserve_order(keys)
        cache["legal_ir_view_feature_keys"] = list(result)
        return result

    def _legal_ir_view_core_feature_keys_for(self, sample: LegalSample) -> List[str]:
        cache = self._sample_cache_for(sample)
        cached = cache.get("legal_ir_view_core_feature_keys")
        if isinstance(cached, list):
            return [str(value) for value in cached]

        text = " ".join(str(sample.normalized_text or sample.text or "").split()).lower()
        tokens = _token_features(text)
        cue_names = self._cue_names_for_text(text)
        section_prefix = _section_prefix(sample.section)
        keys: List[str] = [
            "legal-ir:bias",
            f"legal-ir:formula-count-bin:{_count_bucket(len(sample.modal_ir.formulas))}",
            f"legal-ir:text-token-count-bin:{_count_bucket(len(tokens))}",
        ]
        if sample.title:
            keys.append(f"legal-ir:title:{sample.title}")
        if section_prefix:
            keys.append(f"legal-ir:section-prefix:{section_prefix}")
        if sample.selected_frame:
            keys.append(f"legal-ir:frame:{sample.selected_frame}")
        for cue_name in cue_names:
            keys.append(f"legal-ir:cue:{cue_name}")
            if section_prefix:
                keys.append(f"legal-ir:section-cue:{section_prefix}:{cue_name}")
            if sample.selected_frame:
                keys.append(f"legal-ir:frame-cue:{sample.selected_frame}:{cue_name}")

        formula_families: List[str] = []
        formula_operators: List[str] = []
        for formula in sample.modal_ir.formulas:
            family = str(formula.operator.family)
            operator = str(formula.operator.symbol)
            formula_families.append(family)
            formula_operators.append(operator)
            keys.append(f"legal-ir:modal-family:{family}")
            keys.append(f"legal-ir:modal-operator:{family}:{operator}")
            if sample.selected_frame:
                keys.append(f"legal-ir:frame-family:{sample.selected_frame}:{family}")
            cue = formula.metadata.get("cue") if formula.metadata else None
            if cue:
                cue_name = str(cue).lower()
                keys.append(f"legal-ir:modal-cue:{cue_name}")
                keys.append(f"legal-ir:cue-family:{cue_name}:{family}")

        for left_family, right_family in zip(formula_families, formula_families[1:]):
            keys.append(f"legal-ir:modal-transition:{left_family}->{right_family}")
        for left_operator, right_operator in zip(formula_operators, formula_operators[1:]):
            keys.append(f"legal-ir:operator-transition:{left_operator}->{right_operator}")

        keys.extend(self._modal_ir_structural_feature_keys_for(sample, prefix="legal-ir"))
        keys.extend(
            f"legal-ir:token:{token}"
            for token in tokens[:self.max_legal_ir_token_features]
        )
        keys.extend(
            _token_ngram_features(
                tokens,
                n=2,
                max_ngrams=self.max_legal_ir_token_bigram_features,
                prefix="legal-ir:token2",
            )
        )
        keys.extend(
            _token_ngram_features(
                tokens,
                n=3,
                max_ngrams=self.max_legal_ir_token_trigram_features,
                prefix="legal-ir:token3",
            )
        )
        if tokens:
            keys.append(f"legal-ir:token-first:{tokens[0]}")
            keys.append(f"legal-ir:token-last:{tokens[-1]}")
        if section_prefix:
            for token in tokens[:3]:
                keys.append(f"legal-ir:section-token:{section_prefix}:{token}")

        result = _unique_preserve_order(keys)
        cache["legal_ir_view_core_feature_keys"] = list(result)
        return result

    def _modal_ir_structural_feature_keys_for(
        self,
        sample: LegalSample,
        *,
        prefix: str = "",
    ) -> List[str]:
        key_prefix = f"{prefix}:" if prefix else ""
        keys: List[str] = []

        frame_logic = sample.modal_ir.frame_logic
        if frame_logic is not None:
            ontology = _feature_atom(getattr(frame_logic, "ontology_name", ""))
            if ontology:
                keys.append(f"{key_prefix}frame-logic-ontology:{ontology}")
            selected_frame = _feature_atom(getattr(frame_logic, "selected_frame", "") or "")
            if selected_frame:
                keys.append(f"{key_prefix}frame-logic-selected-frame:{selected_frame}")
            triples = list(getattr(frame_logic, "triples", []) or [])
            keys.append(
                f"{key_prefix}frame-logic-triple-count-bin:{_count_bucket(len(triples))}"
            )
            for label in sorted(getattr(frame_logic, "neo4j_node_labels", []) or [])[:8]:
                label_atom = _feature_atom(label)
                if label_atom:
                    keys.append(f"{key_prefix}kg-node-label:{label_atom}")
            for relation in sorted(
                getattr(frame_logic, "neo4j_relationship_types", []) or []
            )[:8]:
                relation_atom = _feature_atom(relation)
                if relation_atom:
                    keys.append(f"{key_prefix}kg-relation:{relation_atom}")
            for triple in triples[:12]:
                predicate = _feature_atom(getattr(triple, "predicate", ""))
                subject = _feature_atom(getattr(triple, "subject", ""))
                object_value = _feature_atom(getattr(triple, "object", ""))
                if predicate:
                    keys.append(f"{key_prefix}frame-logic-predicate:{predicate}")
                if subject and predicate:
                    keys.append(
                        f"{key_prefix}frame-logic-subject-predicate:{subject}:{predicate}"
                    )
                if predicate and object_value:
                    keys.append(
                        f"{key_prefix}frame-logic-predicate-object:{predicate}:{object_value}"
                    )

        for formula in sample.modal_ir.formulas:
            family = str(formula.operator.family)
            operator = _feature_atom(str(formula.operator.symbol))
            predicate_name = _feature_atom(getattr(formula.predicate, "name", ""))
            predicate_role = _feature_atom(getattr(formula.predicate, "role", "") or "none")
            arguments = list(getattr(formula.predicate, "arguments", []) or [])
            conditions = list(getattr(formula, "conditions", []) or [])
            exceptions = list(getattr(formula, "exceptions", []) or [])

            if predicate_name:
                keys.append(f"{key_prefix}predicate:{predicate_name}")
                keys.append(f"{key_prefix}family-predicate:{family}:{predicate_name}")
                if operator:
                    keys.append(
                        f"{key_prefix}operator-predicate:{family}:{operator}:{predicate_name}"
                    )
                if sample.selected_frame:
                    keys.append(
                        f"{key_prefix}frame-predicate:{sample.selected_frame}:{predicate_name}"
                    )
            if predicate_role:
                keys.append(f"{key_prefix}predicate-role:{predicate_role}")
                keys.append(f"{key_prefix}family-role:{family}:{predicate_role}")
            keys.append(
                f"{key_prefix}predicate-arity-bin:{_count_bucket(len(arguments))}"
            )
            keys.append(
                f"{key_prefix}condition-count-bin:{_count_bucket(len(conditions))}"
            )
            keys.append(
                f"{key_prefix}exception-count-bin:{_count_bucket(len(exceptions))}"
            )
            for argument in arguments[:6]:
                argument_atom = _feature_atom(argument)
                if argument_atom and predicate_name:
                    keys.append(
                        f"{key_prefix}predicate-argument:{predicate_name}:{argument_atom}"
                    )
            for condition in conditions[:4]:
                condition_atom = _feature_atom(condition, max_tokens=6)
                if condition_atom:
                    keys.append(f"{key_prefix}condition:{condition_atom}")
                    keys.append(f"{key_prefix}family-condition:{family}:{condition_atom}")
            for exception in exceptions[:4]:
                exception_atom = _feature_atom(exception, max_tokens=6)
                if exception_atom:
                    keys.append(f"{key_prefix}exception:{exception_atom}")
                    keys.append(f"{key_prefix}family-exception:{family}:{exception_atom}")

        return _unique_preserve_order(keys)

    def _nudge_decoded_embedding(
        self,
        sample: LegalSample,
        *,
        learning_rate: float,
        update_sample_memory: bool = True,
    ) -> None:
        step = _clamp_learning_rate(learning_rate)
        current = self._decoded_for(sample, use_sample_memory=update_sample_memory)
        if len(current) != len(sample.embedding_vector):
            current = [0.0 for _ in sample.embedding_vector]
        error = self._embedding_training_error(sample.embedding_vector, current)
        if update_sample_memory:
            self.state.decoded_embeddings[sample.sample_id] = self._blend_toward(
                current,
                sample.embedding_vector,
                step=step,
            )
        target_distribution = _observed_family_distribution(sample)
        for family, target_weight in target_distribution.items():
            normalized_weight = max(0.0, float(target_weight))
            if normalized_weight <= 0.0:
                continue
            weights = self.state.family_embedding_weights.setdefault(
                family,
                [0.0 for _ in sample.embedding_vector],
            )
            if len(weights) != len(sample.embedding_vector):
                weights[:] = [0.0 for _ in sample.embedding_vector]
            weights[:] = self._add_scaled_vector(
                weights,
                error,
                scale=step * normalized_weight,
            )
        legal_ir_view_distribution = _normalized_distribution(
            self._legal_ir_view_target_distribution_for_sample(sample)
        )
        for view, target_weight in legal_ir_view_distribution.items():
            normalized_weight = max(0.0, float(target_weight))
            if normalized_weight <= 0.0:
                continue
            weights = self.state.legal_ir_view_embedding_weights.setdefault(
                view,
                [0.0 for _ in sample.embedding_vector],
            )
            if len(weights) != len(sample.embedding_vector):
                weights[:] = [0.0 for _ in sample.embedding_vector]
            weights[:] = self._add_scaled_vector(
                weights,
                error,
                scale=step * normalized_weight,
            )
        feature_keys = self._feature_keys_for(sample)
        if not feature_keys:
            return
        for group_keys, feature_step in self._feature_update_groups_for(
            sample,
            step=step,
        ):
            for feature in group_keys:
                weights = self.state.feature_embedding_weights.setdefault(
                    feature,
                    [0.0 for _ in sample.embedding_vector],
                )
                if len(weights) != len(sample.embedding_vector):
                    weights[:] = [0.0 for _ in sample.embedding_vector]
                weights[:] = self._add_scaled_vector(weights, error, scale=feature_step)

    def _nudge_family_logits(
        self,
        sample: LegalSample,
        *,
        learning_rate: float,
        update_sample_memory: bool = True,
    ) -> None:
        step = _clamp_learning_rate(learning_rate)
        target_distribution = _observed_family_distribution(sample)
        predicted = self._family_distribution(
            sample,
            use_sample_memory=update_sample_memory,
        )
        families = _unique_preserve_order(
            list(self.modal_families)
            + list(target_distribution.keys())
            + list(predicted.keys())
        )
        if update_sample_memory:
            logits = self.state.family_logits.setdefault(sample.sample_id, {})
            for family in families:
                gradient = float(target_distribution.get(family, 0.0)) - float(
                    predicted.get(family, 0.0)
                )
                logits[family] = logits.get(family, 0.0) + (2.0 * step * gradient)
        feature_keys = self._feature_keys_for(sample)
        if not feature_keys:
            return
        for group_keys, feature_step in self._feature_update_groups_for(
            sample,
            step=step,
        ):
            for feature in group_keys:
                feature_logits = self.state.feature_family_logits.setdefault(feature, {})
                for family in families:
                    gradient = float(target_distribution.get(family, 0.0)) - float(
                        predicted.get(family, 0.0)
                    )
                    feature_logits[family] = feature_logits.get(family, 0.0) + (
                        2.0 * feature_step * gradient
                    )

    def _nudge_legal_ir_view_logits(
        self,
        sample: LegalSample,
        *,
        learning_rate: float,
        update_sample_memory: bool = True,
    ) -> bool:
        target_distribution = self._legal_ir_view_target_cache.get(sample.sample_id)
        if not target_distribution:
            return False
        step = _clamp_learning_rate(learning_rate)
        predicted = self._legal_ir_view_distribution(
            sample,
            target_distribution,
            use_sample_memory=update_sample_memory,
        )
        families = _unique_preserve_order(
            list(predicted.keys()) + list(target_distribution.keys())
        )
        for family in families:
            gradient = float(target_distribution.get(family, 0.0)) - float(
                predicted.get(family, 0.0)
            )
            self.state.legal_ir_view_logits[family] = (
                self.state.legal_ir_view_logits.get(family, 0.0)
                + (step * gradient)
            )
        if update_sample_memory:
            logits = self.state.family_logits.setdefault(sample.sample_id, {})
            for family in families:
                gradient = float(target_distribution.get(family, 0.0)) - float(
                    predicted.get(family, 0.0)
                )
                logits[family] = logits.get(family, 0.0) + (2.0 * step * gradient)

        for group_keys, feature_step in self._legal_ir_view_feature_update_groups_for(
            sample,
            step=step,
        ):
            for feature in group_keys:
                feature_logits = self.state.feature_legal_ir_view_logits.setdefault(feature, {})
                for family in families:
                    gradient = float(target_distribution.get(family, 0.0)) - float(
                        predicted.get(family, 0.0)
                    )
                    feature_logits[family] = feature_logits.get(family, 0.0) + (
                        2.0 * feature_step * gradient
                    )
        return True

    def _regularize_feature_state(self, l2_regularization: float) -> None:
        factor = max(0.0, 1.0 - max(0.0, float(l2_regularization)))
        if factor >= 1.0:
            return
        for feature, vector in list(self.state.feature_embedding_weights.items()):
            self.state.feature_embedding_weights[feature] = [
                float(value) * factor for value in vector
            ]
        for family, vector in list(self.state.family_embedding_weights.items()):
            self.state.family_embedding_weights[family] = [
                float(value) * factor for value in vector
            ]
        for view, vector in list(self.state.legal_ir_view_embedding_weights.items()):
            self.state.legal_ir_view_embedding_weights[view] = [
                float(value) * factor for value in vector
            ]
        for feature, logits in list(self.state.feature_family_logits.items()):
            self.state.feature_family_logits[feature] = {
                family: float(value) * factor
                for family, value in logits.items()
            }
        self.state.legal_ir_view_logits = {
            view: float(value) * factor
            for view, value in self.state.legal_ir_view_logits.items()
        }
        for feature, logits in list(self.state.feature_legal_ir_view_logits.items()):
            self.state.feature_legal_ir_view_logits[feature] = {
                view: float(value) * factor
                for view, value in logits.items()
            }

    def _family_embedding_adjustment(
        self,
        sample: LegalSample,
        *,
        dimensions: int,
        use_sample_memory: bool,
    ) -> List[float]:
        if self.family_embedding_weight_scale <= 0.0:
            return [0.0 for _ in range(dimensions)]
        distribution = self._family_distribution(
            sample,
            use_sample_memory=use_sample_memory,
        )
        weighted_vectors = [
            (float(weight), weights)
            for family, weight in distribution.items()
            for weights in [self.state.family_embedding_weights.get(family)]
            if float(weight) > 0.0 and weights is not None and len(weights) == dimensions
        ]
        if not weighted_vectors:
            return [0.0 for _ in range(dimensions)]
        if self._torch is not None and self.compute_device is not None:
            with self._torch.no_grad():
                weights_tensor = self._torch.tensor(
                    [weight for weight, _ in weighted_vectors],
                    dtype=self._torch.float64,
                    device=self.compute_device,
                ).reshape(-1, 1)
                vector_tensor = self._torch.tensor(
                    [vector for _, vector in weighted_vectors],
                    dtype=self._torch.float64,
                    device=self.compute_device,
                )
                adjustment = (weights_tensor * vector_tensor).sum(dim=0) * float(
                    self.family_embedding_weight_scale
                )
                return [float(value) for value in adjustment.detach().cpu().tolist()]
        adjustment = [0.0 for _ in range(dimensions)]
        for weight, vector in weighted_vectors:
            for index, value in enumerate(vector):
                adjustment[index] += (
                    weight * float(value) * self.family_embedding_weight_scale
                )
        return adjustment

    def _legal_ir_view_embedding_adjustment(
        self,
        sample: LegalSample,
        *,
        dimensions: int,
        use_sample_memory: bool,
    ) -> List[float]:
        if self.legal_ir_view_embedding_weight_scale <= 0.0:
            return [0.0 for _ in range(dimensions)]
        distribution = self._legal_ir_view_distribution_for_embedding(
            sample,
            use_sample_memory=use_sample_memory,
        )
        weighted_vectors = [
            (float(weight), weights)
            for view, weight in distribution.items()
            for weights in [self.state.legal_ir_view_embedding_weights.get(view)]
            if float(weight) > 0.0 and weights is not None and len(weights) == dimensions
        ]
        if not weighted_vectors:
            return [0.0 for _ in range(dimensions)]
        if self._torch is not None and self.compute_device is not None:
            with self._torch.no_grad():
                weights_tensor = self._torch.tensor(
                    [weight for weight, _ in weighted_vectors],
                    dtype=self._torch.float64,
                    device=self.compute_device,
                ).reshape(-1, 1)
                vector_tensor = self._torch.tensor(
                    [vector for _, vector in weighted_vectors],
                    dtype=self._torch.float64,
                    device=self.compute_device,
                )
                adjustment = (weights_tensor * vector_tensor).sum(dim=0) * float(
                    self.legal_ir_view_embedding_weight_scale
                )
                return [float(value) for value in adjustment.detach().cpu().tolist()]
        adjustment = [0.0 for _ in range(dimensions)]
        for weight, vector in weighted_vectors:
            for index, value in enumerate(vector):
                adjustment[index] += (
                    weight
                    * float(value)
                    * self.legal_ir_view_embedding_weight_scale
                )
        return adjustment

    def _feature_embedding_adjustment(self, sample: LegalSample, *, dimensions: int) -> List[float]:
        vectors = [
            weights
            for feature in self._feature_keys_for(sample)
            for weights in [self.state.feature_embedding_weights.get(feature)]
            if weights is not None and len(weights) == dimensions
        ]
        if not vectors:
            return [0.0 for _ in range(dimensions)]
        feature_scale = 1.0 / self._feature_activity_scale(len(vectors))
        if self._torch is not None and self.compute_device is not None:
            with self._torch.no_grad():
                tensor = self._torch.tensor(
                    vectors,
                    dtype=self._torch.float64,
                    device=self.compute_device,
                )
                adjustment = tensor.sum(dim=0) * (
                    float(self.feature_embedding_weight_scale) * feature_scale
                )
                return [float(value) for value in adjustment.detach().cpu().tolist()]
        adjustment = [0.0 for _ in range(dimensions)]
        for weights in vectors:
            for index, value in enumerate(weights):
                adjustment[index] += (
                    float(value)
                    * self.feature_embedding_weight_scale
                    * feature_scale
                )
        return adjustment

    def _embedding_training_error(
        self,
        target: Sequence[float],
        current: Sequence[float],
    ) -> List[float]:
        error = self._vector_difference(target, current)
        cosine_weight = self.cosine_reconstruction_weight
        if cosine_weight <= 0.0:
            return error
        target_norm = _vector_norm(target)
        if target_norm <= 0.0:
            return error
        current_norm = _vector_norm(current)
        current_unit = (
            [float(value) / current_norm for value in current]
            if current_norm > 0.0
            else [0.0 for _ in current]
        )
        target_unit = [float(value) / target_norm for value in target]
        directional_error = [
            (target_value - current_value) * target_norm
            for target_value, current_value in zip(target_unit, current_unit)
        ]
        return [
            raw_error + (cosine_weight * direction_value)
            for raw_error, direction_value in zip(error, directional_error)
        ]

    def compute_backend_metadata(self) -> Dict[str, str]:
        """Return the active vector math backend used by this autoencoder."""
        return {
            "autoencoder_compute_backend": self.compute_backend,
            "autoencoder_compute_device": str(self.compute_device or "python"),
            "autoencoder_compute_device_request": self.compute_device_request,
        }

    def _embedding_metrics(
        self,
        target_vectors: Sequence[Sequence[float]],
        decoded_vectors: Sequence[Sequence[float]],
    ) -> tuple[List[float], List[float]]:
        if self._torch is not None and self.compute_device is not None:
            with self._torch.no_grad():
                targets = self._torch.tensor(
                    target_vectors,
                    dtype=self._torch.float64,
                    device=self.compute_device,
                )
                decoded = self._torch.tensor(
                    decoded_vectors,
                    dtype=self._torch.float64,
                    device=self.compute_device,
                )
                dot = (targets * decoded).sum(dim=1)
                target_norm = self._torch.linalg.vector_norm(targets, dim=1)
                decoded_norm = self._torch.linalg.vector_norm(decoded, dim=1)
                denominator = target_norm * decoded_norm
                cosine = self._torch.where(
                    denominator > 0.0,
                    dot / denominator,
                    self._torch.zeros_like(denominator),
                )
                mse = ((targets - decoded) ** 2).mean(dim=1)
                return (
                    [float(value) for value in cosine.detach().cpu().tolist()],
                    [float(value) for value in mse.detach().cpu().tolist()],
                )
        return (
            [
                cosine_similarity(target, decoded)
                for target, decoded in zip(target_vectors, decoded_vectors)
            ],
            [
                mse_loss(target, decoded)
                for target, decoded in zip(target_vectors, decoded_vectors)
            ],
        )

    def _cross_entropy_distribution_losses(
        self,
        probability_maps: Sequence[Mapping[str, float]],
        target_maps: Sequence[Mapping[str, float]],
    ) -> List[float]:
        if self._torch is not None and self.compute_device is not None:
            families = tuple(
                dict.fromkeys(
                    list(self.modal_families)
                    + [
                        str(family)
                        for mapping in (*probability_maps, *target_maps)
                        for family in mapping.keys()
                    ]
                )
            )
            with self._torch.no_grad():
                probabilities = self._torch.tensor(
                    [
                        [float(mapping.get(family, 0.0)) for family in families]
                        for mapping in probability_maps
                    ],
                    dtype=self._torch.float64,
                    device=self.compute_device,
                ).clamp_min(1e-12)
                targets = self._torch.tensor(
                    [
                        [max(0.0, float(mapping.get(family, 0.0))) for family in families]
                        for mapping in target_maps
                    ],
                    dtype=self._torch.float64,
                    device=self.compute_device,
                )
                totals = targets.sum(dim=1, keepdim=True)
                normalized_targets = self._torch.where(
                    totals > 0.0,
                    targets / totals.clamp_min(1e-12),
                    self._torch.zeros_like(targets),
                )
                losses = (normalized_targets * -self._torch.log(probabilities)).sum(dim=1)
                return [float(value) for value in losses.detach().cpu().tolist()]
        return [
            cross_entropy_distribution_loss(probabilities, target)
            for probabilities, target in zip(probability_maps, target_maps)
        ]

    def _vector_difference(
        self,
        target: Sequence[float],
        current: Sequence[float],
    ) -> List[float]:
        if self._torch is not None and self.compute_device is not None:
            with self._torch.no_grad():
                target_tensor = self._torch.tensor(
                    target,
                    dtype=self._torch.float64,
                    device=self.compute_device,
                )
                current_tensor = self._torch.tensor(
                    current,
                    dtype=self._torch.float64,
                    device=self.compute_device,
                )
                return [
                    float(value)
                    for value in (target_tensor - current_tensor).detach().cpu().tolist()
                ]
        return [
            float(target_value) - float(current_value)
            for current_value, target_value in zip(current, target)
        ]

    def _blend_toward(
        self,
        current: Sequence[float],
        target: Sequence[float],
        *,
        step: float,
    ) -> List[float]:
        if self._torch is not None and self.compute_device is not None:
            with self._torch.no_grad():
                current_tensor = self._torch.tensor(
                    current,
                    dtype=self._torch.float64,
                    device=self.compute_device,
                )
                target_tensor = self._torch.tensor(
                    target,
                    dtype=self._torch.float64,
                    device=self.compute_device,
                )
                updated = current_tensor + float(step) * (target_tensor - current_tensor)
                return [float(value) for value in updated.detach().cpu().tolist()]
        return [
            float(current_value) + step * (float(target_value) - float(current_value))
            for current_value, target_value in zip(current, target)
        ]

    def _add_scaled_vector(
        self,
        current: Sequence[float],
        update: Sequence[float],
        *,
        scale: float,
    ) -> List[float]:
        if self._torch is not None and self.compute_device is not None:
            with self._torch.no_grad():
                current_tensor = self._torch.tensor(
                    current,
                    dtype=self._torch.float64,
                    device=self.compute_device,
                )
                update_tensor = self._torch.tensor(
                    update,
                    dtype=self._torch.float64,
                    device=self.compute_device,
                )
                updated = current_tensor + float(scale) * update_tensor
                return [float(value) for value in updated.detach().cpu().tolist()]
        return [
            float(current_value) + float(scale) * float(update_value)
            for current_value, update_value in zip(current, update)
        ]

    def _feature_keys_for(self, sample: LegalSample) -> List[str]:
        cache = self._sample_cache_for(sample)
        cached = cache.get("feature_keys")
        if isinstance(cached, list):
            return [str(value) for value in cached]

        keys: List[str] = []
        if self.feature_codec is not None and hasattr(
            self.feature_codec,
            "feature_keys_for_sample",
        ):
            keys.extend(
                str(value)
                for value in self.feature_codec.feature_keys_for_sample(sample)
            )
        keys.extend(self._fallback_feature_keys_for(sample))
        result = _unique_preserve_order(keys)
        cache["feature_keys"] = list(result)
        return result

    def _fallback_feature_keys_for(self, sample: LegalSample) -> List[str]:
        """Return codec-independent features that make SGD updates portable."""
        cache = self._sample_cache_for(sample)
        cached = cache.get("fallback_feature_keys")
        if isinstance(cached, list):
            return [str(value) for value in cached]

        text = " ".join(str(sample.normalized_text or sample.text or "").split()).lower()
        tokens = _token_features(text)
        cue_names = self._cue_names_for_text(text)
        section_prefix = _section_prefix(sample.section)
        keys: List[str] = [
            "bias:modal",
            f"formula-count-bin:{_count_bucket(len(sample.modal_ir.formulas))}",
            f"text-token-count-bin:{_count_bucket(len(tokens))}",
        ]
        if sample.title:
            keys.append(f"title:{sample.title}")
        if section_prefix:
            keys.append(f"section-prefix:{section_prefix}")
        if sample.selected_frame:
            keys.append(f"frame:{sample.selected_frame}")
        for cue_name in cue_names:
            keys.append(f"cue:{cue_name}")
            if section_prefix:
                keys.append(f"section-cue:{section_prefix}:{cue_name}")
            if sample.selected_frame:
                keys.append(f"frame-cue:{sample.selected_frame}:{cue_name}")

        formula_families: List[str] = []
        formula_operators: List[str] = []
        for formula in sample.modal_ir.formulas:
            family = str(formula.operator.family)
            operator = str(formula.operator.symbol)
            formula_families.append(family)
            formula_operators.append(operator)
            keys.append(f"modal-family:{family}")
            keys.append(f"modal-operator:{family}:{operator}")
            if sample.selected_frame:
                keys.append(f"frame-family:{sample.selected_frame}:{family}")
            cue = formula.metadata.get("cue") if formula.metadata else None
            if cue:
                cue_name = str(cue).lower()
                keys.append(f"modal-cue:{cue_name}")
                keys.append(f"cue-family:{cue_name}:{family}")

        for left_family, right_family in zip(formula_families, formula_families[1:]):
            keys.append(f"modal-transition:{left_family}->{right_family}")
        for left_operator, right_operator in zip(formula_operators, formula_operators[1:]):
            keys.append(f"operator-transition:{left_operator}->{right_operator}")

        keys.extend(self._modal_ir_structural_feature_keys_for(sample))
        keys.extend(f"token:{token}" for token in tokens[:self.max_token_features])
        keys.extend(
            _token_ngram_features(
                tokens,
                n=2,
                max_ngrams=self.max_token_bigram_features,
                prefix="token2",
            )
        )
        keys.extend(
            _token_ngram_features(
                tokens,
                n=3,
                max_ngrams=self.max_token_trigram_features,
                prefix="token3",
            )
        )
        if tokens:
            keys.append(f"token-first:{tokens[0]}")
            keys.append(f"token-last:{tokens[-1]}")
        if section_prefix:
            for token in tokens[:3]:
                keys.append(f"section-token:{section_prefix}:{token}")

        result = _unique_preserve_order(keys)
        cache["fallback_feature_keys"] = list(result)
        return result

    def _feature_update_groups_for(
        self,
        sample: LegalSample,
        *,
        step: float,
    ) -> List[tuple[List[str], float]]:
        all_keys = self._feature_keys_for(sample)
        if not all_keys:
            return []
        all_key_set = set(all_keys)
        fallback_keys = [
            key
            for key in _unique_preserve_order(self._fallback_feature_keys_for(sample))
            if key in all_key_set
        ]
        if not fallback_keys:
            return [(all_keys, step / len(all_keys))]

        fallback_set = set(fallback_keys)
        codec_only_keys = [key for key in all_keys if key not in fallback_set]
        fallback_core_keys = [
            key for key in fallback_keys if self._is_core_modal_feature_key(key)
        ]
        fallback_priority_keys = [
            key
            for key in fallback_core_keys
            if self._is_priority_modal_feature_key(key)
        ]
        fallback_priority_set = set(fallback_priority_keys)
        fallback_structural_keys = [
            key for key in fallback_core_keys if key not in fallback_priority_set
        ]
        fallback_lexical_keys = [
            key for key in fallback_keys if self._is_lexical_feature_key(key)
        ]
        fallback_core_set = set(fallback_core_keys)
        fallback_lexical_set = set(fallback_lexical_keys)
        fallback_other_keys = [
            key
            for key in fallback_keys
            if key not in fallback_core_set and key not in fallback_lexical_set
        ]
        weighted_groups: List[tuple[List[str], float]] = []
        if codec_only_keys:
            weighted_groups.extend(
                [
                    (fallback_priority_keys, 0.42),
                    (fallback_structural_keys, 0.18),
                    (fallback_lexical_keys, 0.25),
                    (fallback_other_keys, 0.05),
                    (codec_only_keys, 0.10),
                ]
            )
        else:
            weighted_groups.extend(
                [
                    (fallback_priority_keys, 0.50),
                    (fallback_structural_keys, 0.15),
                    (fallback_lexical_keys, 0.25),
                    (fallback_other_keys, 0.10),
                ]
            )
        groups = self._weighted_update_groups(step=step, groups=weighted_groups)
        return groups or [(all_keys, step / len(all_keys))]

    def _legal_ir_view_feature_update_groups_for(
        self,
        sample: LegalSample,
        *,
        step: float,
    ) -> List[tuple[List[str], float]]:
        all_keys = self._legal_ir_view_feature_keys_for(sample)
        if not all_keys:
            return []
        all_key_set = set(all_keys)
        core_keys = [
            key
            for key in _unique_preserve_order(
                self._legal_ir_view_core_feature_keys_for(sample)
            )
            if key in all_key_set
        ]
        if not core_keys:
            return [(all_keys, step / len(all_keys))]
        if set(core_keys) == set(all_keys):
            return [(core_keys, step / len(core_keys))]
        core_set = set(core_keys)
        shared_keys = [key for key in all_keys if key not in core_set]
        shared_structural = [
            key
            for key in shared_keys
            if not self._is_lexical_feature_key(key)
        ]
        shared_lexical = [
            key
            for key in shared_keys
            if self._is_lexical_feature_key(key)
        ]
        groups = self._weighted_update_groups(
            step=step,
            groups=[
                (core_keys, 0.55),
                (shared_structural, 0.30),
                (shared_lexical, 0.15),
            ],
        )
        return groups or [(all_keys, step / len(all_keys))]

    def _cue_names_for_text(self, text: str) -> List[str]:
        return [
            cue_name
            for cue_name, pattern in _LEGAL_IR_CUE_PATTERNS
            if pattern.search(text)
        ]

    def _is_lexical_feature_key(self, feature: str) -> bool:
        lexical_prefixes = (
            "token:",
            "token2:",
            "token3:",
            "token-first:",
            "token-last:",
            "legal-ir:token:",
            "legal-ir:token2:",
            "legal-ir:token3:",
            "legal-ir:token-first:",
            "legal-ir:token-last:",
        )
        return str(feature).startswith(lexical_prefixes)

    def _is_core_modal_feature_key(self, feature: str) -> bool:
        core_prefixes = (
            "bias:",
            "cue:",
            "cue-family:",
            "condition:",
            "condition-count-bin:",
            "exception:",
            "exception-count-bin:",
            "family-condition:",
            "family-exception:",
            "family-predicate:",
            "family-role:",
            "frame:",
            "frame-cue:",
            "frame-family:",
            "frame-logic-",
            "frame-predicate:",
            "formula-count-bin:",
            "kg-node-label:",
            "kg-relation:",
            "modal-cue:",
            "modal-family:",
            "modal-operator:",
            "modal-transition:",
            "operator-transition:",
            "operator-predicate:",
            "predicate:",
            "predicate-argument:",
            "predicate-arity-bin:",
            "predicate-role:",
            "section-cue:",
            "section-prefix:",
            "title:",
        )
        return str(feature).startswith(core_prefixes)

    def _is_priority_modal_feature_key(self, feature: str) -> bool:
        priority_prefixes = (
            "bias:",
            "cue:",
            "cue-family:",
            "frame:",
            "frame-cue:",
            "frame-family:",
            "formula-count-bin:",
            "modal-cue:",
            "modal-family:",
            "modal-operator:",
            "modal-transition:",
            "operator-transition:",
            "section-cue:",
            "section-prefix:",
            "title:",
        )
        return str(feature).startswith(priority_prefixes)

    def _feature_activity_scale(self, feature_count: int) -> float:
        if feature_count <= self.feature_activity_reference:
            return 1.0
        return math.sqrt(feature_count / max(1.0, float(self.feature_activity_reference)))

    def _clip_logits(self, logits: Dict[str, float]) -> Dict[str, float]:
        clip = float(self.feature_logit_clip)
        if clip <= 0.0:
            return dict(logits)
        return {
            name: max(-clip, min(clip, float(value)))
            for name, value in logits.items()
        }

    def _weighted_update_groups(
        self,
        *,
        step: float,
        groups: Sequence[tuple[Sequence[str], float]],
    ) -> List[tuple[List[str], float]]:
        prepared: List[tuple[List[str], float]] = []
        for keys, weight in groups:
            unique_keys = _unique_preserve_order(str(value) for value in keys)
            normalized_weight = max(0.0, float(weight))
            if not unique_keys or normalized_weight <= 0.0:
                continue
            prepared.append((unique_keys, normalized_weight))
        if not prepared:
            return []
        total_weight = sum(weight for _, weight in prepared)
        if total_weight <= 0.0:
            return []
        return [
            (
                keys,
                (step * (weight / total_weight)) / len(keys),
            )
            for keys, weight in prepared
        ]

    def _sample_cache_for(self, sample: LegalSample) -> Dict[str, Any]:
        return self._sample_feature_cache.setdefault(
            (_sample_content_cache_id(sample), len(sample.embedding_vector)),
            {},
        )

    def _family_contributions_for(
        self,
        sample: LegalSample,
        feature_keys: Sequence[str],
        *,
        use_sample_memory: bool,
    ) -> List[AutoencoderFeatureContribution]:
        target_distribution = _observed_family_distribution(sample)
        feature_scale = 1.0 / self._feature_activity_scale(len(feature_keys))
        contributions: List[AutoencoderFeatureContribution] = []
        for feature in feature_keys:
            logits = self.state.feature_family_logits.get(feature, {})
            for family, value in logits.items():
                if family not in self.modal_families:
                    continue
                family_value = (
                    float(value)
                    * self.feature_family_logit_scale
                    * feature_scale
                )
                contributions.append(
                    AutoencoderFeatureContribution(
                        feature=feature,
                        contribution_type="feature_family_logit",
                        family=family,
                        value=round(family_value, 12),
                        magnitude=round(abs(family_value), 12),
                        metadata={
                            "feature_family_logit_scale": self.feature_family_logit_scale,
                            "feature_activity_scale": feature_scale,
                            "raw_value": round(float(value), 12),
                            "supports_target": target_distribution.get(family, 0.0) > 0.0,
                            "target_probability": round(
                                float(target_distribution.get(family, 0.0)),
                                12,
                            ),
                        },
                    )
                )
        if use_sample_memory:
            for family, value in self.state.family_logits.get(sample.sample_id, {}).items():
                family_value = float(value)
                contributions.append(
                    AutoencoderFeatureContribution(
                        feature=f"sample-memory:{sample.sample_id}",
                        contribution_type="sample_family_logit",
                        family=family,
                        value=round(family_value, 12),
                        magnitude=round(abs(family_value), 12),
                        metadata={
                            "supports_target": target_distribution.get(family, 0.0) > 0.0,
                            "target_probability": round(
                                float(target_distribution.get(family, 0.0)),
                                12,
                            ),
                        },
                    )
                )
        return sorted(
            contributions,
            key=lambda contribution: (
                -contribution.magnitude,
                contribution.feature,
                contribution.family or "",
            ),
        )

    def _embedding_contributions_for(
        self,
        feature_keys: Sequence[str],
        residual: Sequence[float],
        *,
        dimensions: int,
        sample: LegalSample,
        use_sample_memory: bool,
    ) -> List[AutoencoderFeatureContribution]:
        contributions: List[AutoencoderFeatureContribution] = []
        residual_norm = _vector_norm(residual)
        for family, probability in self._family_distribution(
            sample,
            use_sample_memory=use_sample_memory,
        ).items():
            weights = self.state.family_embedding_weights.get(family)
            if weights is None or len(weights) != dimensions:
                continue
            scaled_weights = [
                float(value)
                * float(probability)
                * self.family_embedding_weight_scale
                for value in weights
            ]
            alignment = sum(
                float(left) * float(right)
                for left, right in zip(residual, scaled_weights)
            )
            weight_norm = _vector_norm(scaled_weights)
            normalized_alignment = alignment / (residual_norm * weight_norm) if residual_norm and weight_norm else 0.0
            contributions.append(
                AutoencoderFeatureContribution(
                    feature=f"modal-family-prototype:{family}",
                    contribution_type="family_embedding_weight",
                    value=round(alignment, 12),
                    magnitude=round(weight_norm, 12),
                    family=family,
                    metadata={
                        "alignment_with_residual": round(normalized_alignment, 12),
                        "family_embedding_probability": round(float(probability), 12),
                        "family_embedding_weight_scale": self.family_embedding_weight_scale,
                    },
                )
            )
        for view, probability in self._legal_ir_view_distribution_for_embedding(
            sample,
            use_sample_memory=use_sample_memory,
        ).items():
            weights = self.state.legal_ir_view_embedding_weights.get(view)
            if weights is None or len(weights) != dimensions:
                continue
            scaled_weights = [
                float(value)
                * float(probability)
                * self.legal_ir_view_embedding_weight_scale
                for value in weights
            ]
            alignment = sum(
                float(left) * float(right)
                for left, right in zip(residual, scaled_weights)
            )
            weight_norm = _vector_norm(scaled_weights)
            normalized_alignment = alignment / (residual_norm * weight_norm) if residual_norm and weight_norm else 0.0
            contributions.append(
                AutoencoderFeatureContribution(
                    feature=f"legal-ir-view-prototype:{view}",
                    contribution_type="legal_ir_view_embedding_weight",
                    value=round(alignment, 12),
                    magnitude=round(weight_norm, 12),
                    family=view,
                    metadata={
                        "alignment_with_residual": round(normalized_alignment, 12),
                        "legal_ir_view_embedding_probability": round(float(probability), 12),
                        "legal_ir_view_embedding_weight_scale": (
                            self.legal_ir_view_embedding_weight_scale
                        ),
                    },
                )
            )
        feature_scale = 1.0 / self._feature_activity_scale(len(feature_keys))
        for feature in feature_keys:
            weights = self.state.feature_embedding_weights.get(feature)
            if weights is None or len(weights) != dimensions:
                continue
            scaled_weights = [
                float(value) * self.feature_embedding_weight_scale * feature_scale
                for value in weights
            ]
            alignment = sum(float(left) * float(right) for left, right in zip(residual, scaled_weights))
            weight_norm = _vector_norm(scaled_weights)
            normalized_alignment = alignment / (residual_norm * weight_norm) if residual_norm and weight_norm else 0.0
            contributions.append(
                AutoencoderFeatureContribution(
                    feature=feature,
                    contribution_type="feature_embedding_weight",
                    value=round(alignment, 12),
                    magnitude=round(weight_norm, 12),
                    metadata={
                        "alignment_with_residual": round(normalized_alignment, 12),
                        "feature_embedding_weight_scale": self.feature_embedding_weight_scale,
                        "feature_activity_scale": feature_scale,
                    },
                )
            )
        return sorted(
            contributions,
            key=lambda contribution: (
                -abs(float(contribution.metadata.get("alignment_with_residual", 0.0))),
                -contribution.magnitude,
                contribution.feature,
            ),
        )

    def _synthesis_focus_for(
        self,
        sample: LegalSample,
        *,
        target_family: str,
        predicted_family: str,
        target_probability: float,
        reconstruction_loss: float,
        legal_ir_view_cross_entropy_loss: float = 0.0,
        legal_ir_view_distribution: Optional[Mapping[str, float]] = None,
        legal_ir_predicted_view_distribution: Optional[Mapping[str, float]] = None,
    ) -> List[str]:
        focus: List[str] = []
        if not sample.modal_ir.formulas:
            focus.append("add_deterministic_parser_rule")
        if predicted_family != target_family or target_probability < 0.5:
            focus.append("refine_modal_family_cue_rules")
        if reconstruction_loss > 0.05:
            focus.append("refine_typed_ir_or_decompiler_slots")
        if legal_ir_view_cross_entropy_loss > 0.05:
            distribution = legal_ir_view_distribution or {}
            predicted_distribution = legal_ir_predicted_view_distribution or {}
            focus.append("repair_multiview_legal_ir_loss")
            focus.extend(
                _legal_ir_program_synthesis_focus(
                    distribution,
                    predicted_distribution=predicted_distribution,
                )
            )
        if sample.selected_frame:
            focus.append("audit_frame_logic_terms")
        return _unique_preserve_order(focus)


def _legal_ir_program_synthesis_focus(
    target_distribution: Mapping[str, float],
    *,
    predicted_distribution: Optional[Mapping[str, float]] = None,
) -> List[str]:
    """Return bridge-specific repair focus items from LegalIR view mismatch."""

    target = {
        str(name): max(0.0, float(value))
        for name, value in dict(target_distribution or {}).items()
        if float(value) > 0.0
    }
    if not target:
        return []
    predicted = {
        str(name): max(0.0, float(value))
        for name, value in dict(predicted_distribution or {}).items()
    }
    component_gaps = _legal_ir_component_gaps(target, predicted)

    def needs_attention(component: str) -> bool:
        target_value = float(target.get(component, 0.0))
        if target_value <= 0.0:
            return False
        gap = float(component_gaps.get(component, 0.0))
        if gap <= 0.0:
            return False
        return gap >= 0.02 or (target_value >= 0.03 and gap / target_value >= 0.20)

    def has_component(*prefixes: str) -> bool:
        return any(
            needs_attention(component)
            and any(component == prefix or component.startswith(prefix) for prefix in prefixes)
            for component in target
        )

    focus: List[str] = []
    if has_component("deontic."):
        focus.append("repair_deontic_bridge_quality_gate")
    if has_component("TDFOL.", "fol."):
        focus.append("repair_tdfol_bridge_parse")
    if has_component("CEC."):
        focus.append("repair_cec_dcec_bridge")
    if has_component("external_provers."):
        focus.append("repair_external_prover_router")
    if has_component("knowledge_graphs."):
        focus.append("repair_multiview_legal_ir_graph_projection")
    if has_component("modal.frame_logic", "flogic."):
        focus.append("repair_flogic_ontology_constraints")
    if has_component("zkp."):
        focus.append("repair_zkp_attestation_bridge")
    return focus


def _legal_ir_component_gaps(
    target_distribution: Mapping[str, float],
    predicted_distribution: Mapping[str, float],
) -> Dict[str, float]:
    """Return target-minus-predicted mass for each LegalIR view component."""
    names = sorted(
        set(map(str, dict(target_distribution or {}).keys()))
        | set(map(str, dict(predicted_distribution or {}).keys()))
    )
    return {
        name: _float_or_zero(target_distribution.get(name, 0.0))
        - _float_or_zero(predicted_distribution.get(name, 0.0))
        for name in names
    }


def _top_legal_ir_component_gaps(
    component_gaps: Mapping[str, float],
    *,
    positive: bool,
    limit: int = 8,
    min_abs_gap: float = 0.01,
) -> List[str]:
    """Return largest under- or over-represented LegalIR view components."""
    scored = []
    for component, gap in dict(component_gaps or {}).items():
        gap = _float_or_zero(gap)
        if positive and gap <= 0.0:
            continue
        if not positive and gap >= 0.0:
            continue
        if abs(gap) < min_abs_gap:
            continue
        scored.append((abs(gap), str(component)))
    return [
        component
        for _gap, component in sorted(scored, key=lambda item: (-item[0], item[1]))[
            : max(0, int(limit))
        ]
    ]


def _observed_family_distribution(sample: LegalSample) -> Dict[str, float]:
    families = [formula.operator.family for formula in sample.modal_ir.formulas]
    if not families:
        return {ModalLogicFamily.HYBRID.value: 1.0}
    counts: Dict[str, int] = {}
    for family in families:
        counts[family] = counts.get(family, 0) + 1
    total = float(sum(counts.values()))
    return {family: count / total for family, count in sorted(counts.items())}


def _normalized_distribution(distribution: Mapping[str, float]) -> Dict[str, float]:
    positive = {
        str(name): max(0.0, _float_or_zero(value))
        for name, value in dict(distribution or {}).items()
    }
    total = sum(positive.values())
    if total <= 0.0:
        return {}
    return {
        name: value / total
        for name, value in sorted(positive.items())
        if value > 0.0
    }


def _legal_ir_target_payload(
    samples: Sequence[LegalSample],
    *,
    bridge_names: Sequence[str] = (),
    evaluate_provers: Optional[bool] = None,
    legal_ir_targets: Optional[Mapping[str, Any] | Sequence[Any]] = None,
    parallel_workers: Optional[int] = None,
) -> Dict[str, Any]:
    target_items = _legal_ir_target_items(
        samples,
        bridge_names=bridge_names,
        evaluate_provers=evaluate_provers,
        legal_ir_targets=legal_ir_targets,
        parallel_workers=parallel_workers,
    )
    loss_values: Dict[str, List[float]] = {}
    target_losses_by_sample: Dict[str, Dict[str, float]] = {}
    view_distribution_values: Dict[str, List[float]] = {}
    target_view_distributions_by_sample: Dict[str, Dict[str, float]] = {}
    target_hashes: Dict[str, str] = {}

    for sample_id, target in target_items:
        sample_losses: Dict[str, float] = {}
        for name, value in dict(getattr(target, "losses", {}) or {}).items():
            safe_value = _float_or_zero(value)
            loss_values.setdefault(str(name), []).append(safe_value)
            sample_losses[str(name)] = safe_value
        if sample_id and sample_losses:
            target_losses_by_sample[str(sample_id)] = dict(sorted(sample_losses.items()))
        target_view_distribution: Dict[str, float] = {}
        for name, value in dict(getattr(target, "view_distribution", {}) or {}).items():
            view_value = _float_or_zero(value)
            view_distribution_values.setdefault(str(name), []).append(view_value)
            if view_value > 0.0:
                target_view_distribution[str(name)] = view_value
        if sample_id and target_view_distribution:
            target_view_distributions_by_sample[str(sample_id)] = dict(
                sorted(target_view_distribution.items())
            )
        document = getattr(target, "document", None)
        if sample_id and document is not None and hasattr(document, "canonical_hash"):
            target_hashes[str(sample_id)] = str(document.canonical_hash())

    return {
        "losses": {
            name: _mean(values)
            for name, values in sorted(loss_values.items())
            if values
        },
        "target_view_distributions_by_sample": dict(
            sorted(target_view_distributions_by_sample.items())
        ),
        "target_losses_by_sample": dict(sorted(target_losses_by_sample.items())),
        "target_count": len(target_items),
        "target_hashes": dict(sorted(target_hashes.items())),
        "view_distribution": {
            name: _mean(values)
            for name, values in sorted(view_distribution_values.items())
            if values
        },
    }


def _legal_ir_target_items(
    samples: Sequence[LegalSample],
    *,
    bridge_names: Sequence[str] | str,
    evaluate_provers: Optional[bool] = None,
    legal_ir_targets: Optional[Mapping[str, Any] | Sequence[Any]],
    parallel_workers: Optional[int] = None,
) -> List[tuple[str, Any]]:
    if legal_ir_targets is not None:
        if isinstance(legal_ir_targets, Mapping):
            return [
                (sample.sample_id, target)
                for sample in samples
                for target in [legal_ir_targets.get(sample.sample_id)]
                if target is not None
            ]
        target_items: List[tuple[str, Any]] = []
        for index, target in enumerate(legal_ir_targets):
            if target is None:
                continue
            document = getattr(target, "document", None)
            sample_id = str(getattr(document, "document_id", "") or "")
            if not sample_id and index < len(samples):
                sample_id = samples[index].sample_id
            target_items.append((sample_id, target))
        return target_items

    names = _normalise_bridge_names(bridge_names)
    if not names:
        return []

    from ipfs_datasets_py.logic.bridge import evaluate_legal_ir_multiview

    def evaluate_sample(sample: LegalSample) -> tuple[str, Any]:
        cache_key = _legal_ir_target_cache_key(
            sample,
            bridge_names=names,
            evaluate_provers=evaluate_provers,
        )
        with _LEGAL_IR_TARGET_CACHE_LOCK:
            cached = _LEGAL_IR_TARGET_CACHE.get(cache_key)
        if cached is not None:
            return sample.sample_id, cached
        report = evaluate_legal_ir_multiview(
            sample.text,
            bridge_names=names,
            document_id=sample.sample_id,
            evaluate_provers=evaluate_provers,
            citation=sample.citation,
            source=sample.source,
            source_embedding=sample.embedding_vector,
        )
        target = report.training_target()
        with _LEGAL_IR_TARGET_CACHE_LOCK:
            if len(_LEGAL_IR_TARGET_CACHE) >= _LEGAL_IR_TARGET_CACHE_MAX:
                _LEGAL_IR_TARGET_CACHE.pop(next(iter(_LEGAL_IR_TARGET_CACHE)), None)
            _LEGAL_IR_TARGET_CACHE[cache_key] = target
        return sample.sample_id, target

    worker_count = _legal_ir_parallel_worker_count(
        requested=parallel_workers,
        item_count=len(samples),
    )
    if worker_count <= 1:
        return [evaluate_sample(sample) for sample in samples]

    with ThreadPoolExecutor(
        max_workers=worker_count,
        thread_name_prefix="legal-ir-target",
    ) as executor:
        return list(executor.map(evaluate_sample, samples))


def _legal_ir_parallel_worker_count(
    *,
    requested: Optional[int],
    item_count: int,
) -> int:
    if item_count <= 1:
        return 1
    if requested is None:
        raw = os.environ.get("IPFS_DATASETS_LEGAL_IR_PARALLEL_WORKERS", "").strip()
        if not raw:
            return 1
        try:
            requested = int(raw)
        except ValueError:
            return 1
    return max(1, min(int(requested), int(item_count)))


def _normalise_bridge_names(bridge_names: Sequence[str] | str) -> tuple[str, ...]:
    if isinstance(bridge_names, str):
        raw_names: Iterable[str] = bridge_names.split(",")
    else:
        raw_names = bridge_names
    return tuple(
        dict.fromkeys(
            str(name).strip()
            for name in raw_names
            if str(name).strip() and str(name).strip().lower() not in {"none", "off", "false"}
        )
    )


def _legal_ir_target_cache_key(
    sample: LegalSample,
    *,
    bridge_names: Sequence[str],
    evaluate_provers: Optional[bool],
) -> str:
    payload = {
        "bridge_names": list(bridge_names),
        "embedding_hash": _embedding_vector_hash(sample.embedding_vector),
        "evaluate_provers": evaluate_provers,
        "sample_content_hash": _sample_content_cache_id(sample),
        "source": sample.source,
        "text_hash": _text_hash(sample.normalized_text or sample.text),
    }
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=True, sort_keys=True).encode("utf-8")
    ).hexdigest()


def _sample_content_cache_id(sample: LegalSample) -> str:
    """Return a stable cache id for source text plus deterministic parser signals."""
    formula_signatures = []
    for formula in sample.modal_ir.formulas:
        metadata = dict(getattr(formula, "metadata", {}) or {})
        formula_signatures.append(
            {
                "cue": str(metadata.get("cue") or ""),
                "family": str(getattr(formula.operator, "family", "")),
                "symbol": str(getattr(formula.operator, "symbol", "")),
            }
        )
    payload = {
        "embedding_hash": _embedding_vector_hash(sample.embedding_vector),
        "embedding_model": sample.embedding_model,
        "formula_signatures": formula_signatures,
        "normalized_text_hash": _text_hash(sample.normalized_text),
        "selected_frame": sample.selected_frame,
        "source": sample.source,
        "text_hash": _text_hash(sample.text),
    }
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=True, sort_keys=True).encode("utf-8")
    ).hexdigest()


def _embedding_vector_hash(values: Sequence[float]) -> str:
    normalized = [round(float(value), 12) for value in values]
    return hashlib.sha256(
        json.dumps(normalized, ensure_ascii=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _text_hash(value: str) -> str:
    return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class _ModalStatement:
    formula: str
    natural_language: str
    confidence: float
    formalism: str
    metadata: Dict[str, Any] = field(default_factory=dict)


def evaluate_modal_prover_compilation(
    sample: LegalSample,
    *,
    prover_adapter: Optional[Any] = None,
    timeout: Optional[float] = None,
) -> ProverCompilationSignal:
    """Compile modal IR formulas through the local prover adapter."""
    formulas = list(sample.modal_ir.formulas)
    if not formulas:
        return ProverCompilationSignal(
            attempted_count=0,
            valid_count=0,
            details=[
                {
                    "reason": "sample contains no modal formulas",
                    "sample_id": sample.sample_id,
                }
            ],
        )

    if prover_adapter is None:
        from ipfs_datasets_py.optimizers.logic_theorem_optimizer.prover_integration import (
            ProverIntegrationAdapter,
        )

        prover_adapter = ProverIntegrationAdapter(use_provers=[], enable_cache=True)

    valid_count = 0
    unavailable_count = 0
    error_count = 0
    failed_count = 0
    verified_by: List[str] = []
    details: List[Dict[str, Any]] = []

    for formula in formulas:
        statement = _ModalStatement(
            formula=_render_modal_formula(formula),
            natural_language=_modal_formula_span_text(sample, formula),
            confidence=1.0,
            formalism="modal",
            metadata={
                "formula_id": formula.formula_id,
                "modal_family": formula.operator.family,
                "modal_system": formula.operator.system,
                "operator": formula.operator.symbol,
            },
        )
        result = prover_adapter.verify_statement(statement, timeout=timeout)
        statuses = [
            str(getattr(prover_result.status, "value", prover_result.status))
            for prover_result in result.prover_results
        ]
        verified_by.extend(str(name) for name in result.verified_by)
        if result.overall_valid:
            valid_count += 1
        elif "unavailable" in statuses:
            unavailable_count += 1
        elif "error" in statuses or "timeout" in statuses:
            error_count += 1
        else:
            failed_count += 1
        details.append(
            {
                "formula": statement.formula,
                "formula_id": formula.formula_id,
                "overall_valid": bool(result.overall_valid),
                "statuses": statuses,
                "verified_by": list(result.verified_by),
            }
        )

    return ProverCompilationSignal(
        attempted_count=len(formulas),
        valid_count=valid_count,
        unavailable_count=unavailable_count,
        error_count=error_count,
        failed_count=failed_count,
        verified_by=sorted(set(verified_by)),
        details=details,
    )


def _target_family(sample: LegalSample) -> str:
    if not sample.modal_ir.formulas:
        return ModalLogicFamily.HYBRID.value
    return sample.modal_ir.formulas[0].operator.family


def _all_modal_families() -> List[str]:
    return [family.value for family in ModalLogicFamily]


_TOKEN_RE = re.compile(r"[a-z0-9]+")
_LEGAL_IR_CONDITIONAL_CUE_RE = re.compile(
    r"\b(if|when|whenever|unless|provided|subject\s+to|condition|conditions|before|after)\b",
    re.IGNORECASE,
)
_LEGAL_IR_DEONTIC_CUE_RE = re.compile(
    r"\b(shall|must|may|required|requires|prohibited|authorized|eligible|entitled|permit|license)\b",
    re.IGNORECASE,
)
_LEGAL_IR_OBLIGATION_CUE_RE = re.compile(
    r"\b(shall|must|required|requires|duty|obligation|responsible)\b",
    re.IGNORECASE,
)
_LEGAL_IR_PERMISSION_CUE_RE = re.compile(
    r"\b(may|authorized|permitted|eligible|entitled|discretion|approval)\b",
    re.IGNORECASE,
)
_LEGAL_IR_TEMPORAL_CUE_RE = re.compile(
    r"\b(within|before|after|until|during|effective|expires?|repealed|deadline|days?|months?|years?)\b",
    re.IGNORECASE,
)
_LEGAL_IR_DEFINITION_CUE_RE = re.compile(
    r"\b(means|defined|definition|term|for\s+purposes\s+of|includes?)\b",
    re.IGNORECASE,
)
_LEGAL_IR_AUTHORITY_CUE_RE = re.compile(
    r"\b(secretary|administrator|agency|commission|authority|jurisdiction|regulation|rulemaking)\b",
    re.IGNORECASE,
)
_LEGAL_IR_ENFORCEMENT_CUE_RE = re.compile(
    r"\b(penalty|violation|fine|liable|liability|enforce|enforcement|action|remedy|sanction)\b",
    re.IGNORECASE,
)
_LEGAL_IR_EXCEPTION_CUE_RE = re.compile(
    r"\b(except|exception|notwithstanding|waiver|exemption|excluded?)\b",
    re.IGNORECASE,
)
_LEGAL_IR_CUE_PATTERNS = (
    ("conditional", _LEGAL_IR_CONDITIONAL_CUE_RE),
    ("deontic", _LEGAL_IR_DEONTIC_CUE_RE),
    ("obligation", _LEGAL_IR_OBLIGATION_CUE_RE),
    ("permission", _LEGAL_IR_PERMISSION_CUE_RE),
    ("temporal", _LEGAL_IR_TEMPORAL_CUE_RE),
    ("definition", _LEGAL_IR_DEFINITION_CUE_RE),
    ("authority", _LEGAL_IR_AUTHORITY_CUE_RE),
    ("enforcement", _LEGAL_IR_ENFORCEMENT_CUE_RE),
    ("exception", _LEGAL_IR_EXCEPTION_CUE_RE),
)
_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "be",
    "by",
    "for",
    "in",
    "is",
    "of",
    "or",
    "shall",
    "that",
    "the",
    "to",
    "under",
}


def _token_features(text: str, *, max_tokens: int = 40) -> List[str]:
    if max_tokens <= 0:
        return []
    return [
        token
        for token in _TOKEN_RE.findall(text.lower())
        if len(token) > 2 and token not in _STOPWORDS
    ][:max_tokens]


def _feature_atom(value: Any, *, max_tokens: int = 4) -> str:
    tokens = _TOKEN_RE.findall(str(value or "").lower())
    if max_tokens > 0:
        tokens = tokens[:max_tokens]
    return "_".join(tokens)


def _token_ngram_features(
    tokens: Sequence[str],
    *,
    n: int,
    max_ngrams: int,
    prefix: str,
) -> List[str]:
    if n <= 1 or max_ngrams <= 0 or len(tokens) < n:
        return []
    values: List[str] = []
    for index in range(0, len(tokens) - n + 1):
        values.append(f"{prefix}:{'_'.join(tokens[index:index + n])}")
        if len(values) >= max_ngrams:
            break
    return values


def _section_prefix(section: str) -> str:
    return str(section or "").split(".", 1)[0].split("-", 1)[0].split("(", 1)[0]


def _count_bucket(value: int) -> str:
    count = max(0, int(value))
    if count <= 0:
        return "0"
    if count == 1:
        return "1"
    if count <= 3:
        return "2-3"
    if count <= 7:
        return "4-7"
    if count <= 15:
        return "8-15"
    if count <= 31:
        return "16-31"
    return "32+"


def _unique_preserve_order(values: Iterable[str]) -> List[str]:
    seen: set[str] = set()
    result: List[str] = []
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _hash_json(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _text_shape(text: str) -> str:
    tokens = _token_features(text)
    return "|".join(tokens[:12]) or "empty"


def _render_modal_formula(formula: Any) -> str:
    arguments = ", ".join(str(value) for value in getattr(formula.predicate, "arguments", []))
    predicate = str(formula.predicate.name)
    if arguments:
        predicate = f"{predicate}({arguments})"
    return f"{formula.operator.symbol}[{formula.operator.family}:{formula.operator.system}]({predicate})"


def _modal_formula_span_text(sample: LegalSample, formula: Any) -> str:
    start = max(0, int(getattr(formula.provenance, "start_char", 0)))
    end = max(start, int(getattr(formula.provenance, "end_char", 0)))
    return sample.normalized_text[start:end] or sample.normalized_text


def _codex_gate_local_loss(
    metrics: Mapping[str, float],
    gate: CodexCallGateConfig,
    *,
    prover_signal: Optional[ProverCompilationSignal],
) -> float:
    cosine_gap = max(0.0, 1.0 - float(metrics.get("embedding_cosine_similarity", 0.0)))
    loss = (
        gate.cosine_weight * cosine_gap
        + gate.cross_entropy_weight * max(0.0, float(metrics.get("cross_entropy_loss", 0.0)))
        + gate.reconstruction_weight * max(0.0, float(metrics.get("reconstruction_loss", 0.0)))
        + gate.frame_weight * max(0.0, float(metrics.get("frame_ranking_loss", 0.0)))
        + gate.symbolic_weight * max(0.0, float(metrics.get("symbolic_validity_penalty", 0.0)))
    )
    legal_ir_loss = (
        max(0.0, float(metrics.get("legal_ir_multiview_total_loss", 0.0)))
        + max(0.0, float(metrics.get("legal_ir_view_cross_entropy_loss", 0.0)))
        + max(0.0, float(metrics.get("legal_ir_multiview_proof_failure_ratio", 0.0)))
        + max(0.0, float(metrics.get("legal_ir_multiview_graph_failure_penalty", 0.0)))
    )
    loss += gate.legal_ir_weight * legal_ir_loss
    if gate.require_prover_compilation:
        if prover_signal is None:
            loss += gate.prover_weight
        else:
            loss += gate.prover_weight * prover_signal.failure_ratio
    return loss


def _softmax(logits: Mapping[str, float]) -> Dict[str, float]:
    if not logits:
        return {}
    max_logit = max(float(value) for value in logits.values())
    exponentials = {
        name: math.exp(float(value) - max_logit)
        for name, value in logits.items()
    }
    total = sum(exponentials.values())
    if total == 0.0:
        uniform = 1.0 / len(exponentials)
        return {name: uniform for name in sorted(exponentials)}
    return {name: exponentials[name] / total for name in sorted(exponentials)}


def _clamp_learning_rate(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _resolve_vector_compute_backend(
    compute_device: str,
) -> tuple[str, str, Any | None, Any | None]:
    request = str(compute_device or "auto").strip().lower()
    if request in {"", "auto"}:
        request = "auto"
    if request in {"python", "list", "lists", "none", "off"}:
        return request, "python", None, None

    try:
        import torch  # type: ignore[import-not-found]
    except Exception:
        return request, "python", None, None

    if request == "auto":
        if bool(torch.cuda.is_available()):
            return request, "torch_cuda", torch.device("cuda"), torch
        return request, "python", None, None
    if request.startswith("cuda"):
        if bool(torch.cuda.is_available()):
            return request, "torch_cuda", torch.device(request), torch
        return request, "python_cuda_unavailable", None, None
    if request == "cpu":
        return request, "torch_cpu", torch.device("cpu"), torch
    return request, "python_unknown_device", None, None


def _mean(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _mean_distributions(
    distributions: Sequence[Mapping[str, float]],
) -> Dict[str, float]:
    values_by_name: Dict[str, List[float]] = {}
    for distribution in distributions:
        for name, value in dict(distribution or {}).items():
            values_by_name.setdefault(str(name), []).append(_float_or_zero(value))
    return {
        name: _mean(values)
        for name, values in sorted(values_by_name.items())
        if values
    }


def _float_or_zero(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _evaluation_improved_for_training(
    before: AutoencoderEvaluation,
    after: AutoencoderEvaluation,
    *,
    max_cosine_regression: float = 0.01,
    max_reconstruction_regression: float = 0.02,
    max_cross_entropy_regression: float = 0.0,
    max_legal_ir_loss_regression: float = 0.02,
) -> bool:
    """Return true when a feature update improves total loss without regressions."""
    if _evaluation_regressions_for_training(
        before,
        after,
        max_cosine_regression=max_cosine_regression,
        max_reconstruction_regression=max_reconstruction_regression,
        max_cross_entropy_regression=max_cross_entropy_regression,
        max_legal_ir_loss_regression=max_legal_ir_loss_regression,
    ):
        return False
    return (
        _evaluation_objective_for_training(after)
        < _evaluation_objective_for_training(before)
    )


def _evaluation_objective_for_training(
    evaluation: AutoencoderEvaluation,
    *,
    cross_entropy: float = 1.0,
    reconstruction: float = 1.0,
    cosine_gap: float = 1.0,
    legal_ir: float = 1.0,
) -> float:
    """Return a scalar objective where lower is better for guarded training."""
    return (
        (max(0.0, float(cross_entropy)) * evaluation.cross_entropy_loss)
        + (max(0.0, float(reconstruction)) * evaluation.reconstruction_loss)
        + (
            max(0.0, float(cosine_gap))
            * max(0.0, 1.0 - evaluation.embedding_cosine_similarity)
        )
        + (
            max(0.0, float(legal_ir))
            * _legal_ir_objective_component(evaluation.legal_ir_losses)
        )
    )


def _legal_ir_objective_component(losses: Mapping[str, float]) -> float:
    """Return a normalized LegalIR objective component.

    LegalIR exposes overlapping diagnostics: total loss, view cross entropy,
    proof ratios, graph penalties, and adapter-specific losses.  Summing every
    raw value lets one dense diagnostic swamp cosine/reconstruction.  This
    component keeps the important residuals visible while capping duplicate
    bridge detail.
    """
    values = {str(name): max(0.0, float(value)) for name, value in dict(losses).items()}
    if not values:
        return 0.0
    component = 0.0
    component += min(1.0, values.get("legal_ir_multiview_total_loss", 0.0))
    component += min(1.0, values.get("legal_ir_view_cross_entropy_loss", 0.0) / 3.0)
    component += min(1.0, values.get("legal_ir_multiview_proof_failure_ratio", 0.0))
    component += min(1.0, values.get("legal_ir_multiview_graph_failure_penalty", 0.0))
    detail = 0.0
    for name, value in values.items():
        if name in {
            "legal_ir_multiview_total_loss",
            "legal_ir_view_cross_entropy_loss",
            "legal_ir_multiview_proof_failure_ratio",
            "legal_ir_multiview_graph_failure_penalty",
        }:
            continue
        if name.startswith("legal_ir_") or name.startswith(("deontic_", "tdfol_", "cec_", "zkp_", "external_prover_")):
            detail += min(0.25, value)
    return component + min(1.0, detail)


def _evaluation_regressions_for_training(
    before: AutoencoderEvaluation,
    after: AutoencoderEvaluation,
    *,
    max_cosine_regression: float = 0.01,
    max_reconstruction_regression: float = 0.02,
    max_cross_entropy_regression: float = 0.0,
    max_legal_ir_loss_regression: float = 0.02,
) -> Dict[str, float]:
    """Return metric regressions that exceed the guarded training tolerances."""
    regressions: Dict[str, float] = {}
    cosine_regression = (
        before.embedding_cosine_similarity - after.embedding_cosine_similarity
    )
    if cosine_regression > max(0.0, float(max_cosine_regression)):
        regressions["embedding_cosine_similarity"] = cosine_regression
    reconstruction_regression = after.reconstruction_loss - before.reconstruction_loss
    if reconstruction_regression > max(0.0, float(max_reconstruction_regression)):
        regressions["reconstruction_loss"] = reconstruction_regression
    cross_entropy_regression = after.cross_entropy_loss - before.cross_entropy_loss
    if cross_entropy_regression > max(0.0, float(max_cross_entropy_regression)):
        regressions["cross_entropy_loss"] = cross_entropy_regression
    for name in sorted(set(before.legal_ir_losses) | set(after.legal_ir_losses)):
        regression = (
            float(after.legal_ir_losses.get(name, 0.0))
            - float(before.legal_ir_losses.get(name, 0.0))
        )
        if regression > max(0.0, float(max_legal_ir_loss_regression)):
            regressions[f"legal_ir:{name}"] = regression
    return regressions


def _vector_norm(values: Sequence[float]) -> float:
    return math.sqrt(sum(float(value) * float(value) for value in values))


def frame_ranking_loss(sample: LegalSample) -> float:
    """Return zero when the selected frame is ranked first, otherwise rank penalty."""
    if not sample.frame_candidates or sample.selected_frame is None:
        return 1.0
    for index, candidate in enumerate(sample.frame_candidates):
        if candidate.get("frame_id") == sample.selected_frame:
            return float(index)
    return float(len(sample.frame_candidates))


def symbolic_validity_penalty(sample: LegalSample) -> float:
    """Return a simple penalty for samples without parseable modal formulas."""
    return 0.0 if sample.modal_ir.formulas else 1.0


def _check_same_length(left: Sequence[float], right: Sequence[float]) -> None:
    if len(left) != len(right):
        raise ValueError("Vectors must have the same length")


__all__ = [
    "AdaptiveModalAutoencoder",
    "AutoencoderFeatureContribution",
    "AutoencoderEvaluation",
    "AutoencoderIntrospection",
    "CodexCallCache",
    "CodexCallDecision",
    "CodexCallGateConfig",
    "ModalAutoencoderBaseline",
    "ModalAutoencoderTrainingState",
    "ProverCompilationSignal",
    "cosine_loss",
    "cosine_similarity",
    "cross_entropy_distribution_loss",
    "cross_entropy_loss",
    "evaluate_modal_prover_compilation",
    "frame_ranking_loss",
    "mse_loss",
    "symbolic_validity_penalty",
]
