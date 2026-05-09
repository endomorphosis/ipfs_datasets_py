"""Deterministic modal autoencoder baselines, training state, and losses."""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

from .legal_samples import LegalSample
from .modal_registry import ModalLogicFamily


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

    def to_dict(self) -> Dict[str, object]:
        return {
            "cosine_loss": self.cosine_loss,
            "cross_entropy_loss": self.cross_entropy_loss,
            "decoded_embeddings": self.decoded_embeddings,
            "embedding_cosine_similarity": self.embedding_cosine_similarity,
            "frame_ranking_loss": self.frame_ranking_loss,
            "reconstruction_loss": self.reconstruction_loss,
            "sample_count": self.sample_count,
            "symbolic_validity_penalty": self.symbolic_validity_penalty,
        }


@dataclass
class ModalAutoencoderTrainingState:
    """Mutable deterministic state for the modal encoder/decoder optimizer."""

    decoded_embeddings: Dict[str, List[float]] = field(default_factory=dict)
    family_logits: Dict[str, Dict[str, float]] = field(default_factory=dict)
    feature_embedding_weights: Dict[str, List[float]] = field(default_factory=dict)
    feature_family_logits: Dict[str, Dict[str, float]] = field(default_factory=dict)
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
            "feature_embedding_weights": {
                feature: list(vector)
                for feature, vector in sorted(self.feature_embedding_weights.items())
            },
            "feature_family_logits": {
                feature: dict(sorted(logits.items()))
                for feature, logits in sorted(self.feature_family_logits.items())
            },
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=True, sort_keys=True, separators=(",", ":"))

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
            feature_family_logits={
                str(feature): {str(name): float(value) for name, value in dict(logits).items()}
                for feature, logits in dict(data.get("feature_family_logits", {})).items()
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

    def evaluate(self, samples: Iterable[LegalSample]) -> AutoencoderEvaluation:
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
            target_family = self._target_family(sample)
            ce_losses.append(cross_entropy_loss(self._family_distribution(sample), target_family))
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

    This is intentionally dependency-free: it is not a neural model, but it has
    enough mutable state to let daemon iterations prove that claimed TODOs move
    cross entropy down and cosine similarity up before work is marked complete.
    """

    def __init__(
        self,
        *,
        state: Optional[ModalAutoencoderTrainingState] = None,
        initial_embedding_scale: float = 0.0,
        modal_families: Optional[Sequence[str]] = None,
        feature_codec: Optional[Any] = None,
    ) -> None:
        self.state = state or ModalAutoencoderTrainingState()
        self.initial_embedding_scale = float(initial_embedding_scale)
        self.modal_families = tuple(modal_families or _all_modal_families())
        self.feature_codec = feature_codec

    def evaluate(self, samples: Iterable[LegalSample]) -> AutoencoderEvaluation:
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
                cross_entropy_loss(self._family_distribution(sample), _target_family(sample))
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
        )

    def encode(self, sample: LegalSample) -> Dict[str, object]:
        """Encode sample into the current intermediate representation state."""
        return {
            "family_distribution": self._family_distribution(sample),
            "sample_id": sample.sample_id,
            "selected_frame": sample.selected_frame,
            "target_family": _target_family(sample),
            "embedding_projection": self._decoded_for(sample),
        }

    def decode(self, encoded: Mapping[str, object]) -> List[float]:
        """Decode the intermediate representation into an embedding vector."""
        return [
            float(value)
            for value in encoded.get("embedding_projection", [])  # type: ignore[arg-type]
        ]

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

        for sample_id in sample_ids:
            sample = samples_by_id.get(sample_id)
            if sample is None:
                continue
            if action == "improve_modal_family_classifier" or loss_name == "cross_entropy_loss":
                self._nudge_family_logits(sample, learning_rate=learning_rate)
                changed.append("family_logits")
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

    def _decoded_for(self, sample: LegalSample) -> List[float]:
        stored = self.state.decoded_embeddings.get(sample.sample_id)
        if stored is not None and len(stored) == len(sample.embedding_vector):
            return list(stored)
        base = self._base_decoded_for(sample)
        adjustment = self._feature_embedding_adjustment(sample, dimensions=len(base))
        return [
            base_value + adjustment_value
            for base_value, adjustment_value in zip(base, adjustment)
        ]

    def _base_decoded_for(self, sample: LegalSample) -> List[float]:
        if self.feature_codec is not None and hasattr(
            self.feature_codec,
            "decode_sample_embedding",
        ):
            decoded = self.feature_codec.decode_sample_embedding(
                sample,
                dimensions=len(sample.embedding_vector),
            )
            if len(decoded) == len(sample.embedding_vector):
                return [float(value) for value in decoded]
        return [self.initial_embedding_scale * float(value) for value in sample.embedding_vector]

    def _family_distribution(self, sample: LegalSample) -> Dict[str, float]:
        return _softmax(self._logits_for(sample))

    def _logits_for(self, sample: LegalSample) -> Dict[str, float]:
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
        for feature in self._feature_keys_for(sample):
            for family, value in self.state.feature_family_logits.get(feature, {}).items():
                if family in logits:
                    logits[family] += float(value)
        for family, value in self.state.family_logits.get(sample.sample_id, {}).items():
            if family in logits:
                logits[family] += float(value)
        return logits

    def _nudge_decoded_embedding(self, sample: LegalSample, *, learning_rate: float) -> None:
        step = _clamp_learning_rate(learning_rate)
        current = self._decoded_for(sample)
        if len(current) != len(sample.embedding_vector):
            current = [0.0 for _ in sample.embedding_vector]
        error = [
            float(target_value) - current_value
            for current_value, target_value in zip(current, sample.embedding_vector)
        ]
        self.state.decoded_embeddings[sample.sample_id] = [
            current_value + step * (float(target_value) - current_value)
            for current_value, target_value in zip(current, sample.embedding_vector)
        ]
        feature_keys = self._feature_keys_for(sample)
        if not feature_keys:
            return
        feature_step = step / len(feature_keys)
        for feature in feature_keys:
            weights = self.state.feature_embedding_weights.setdefault(
                feature,
                [0.0 for _ in sample.embedding_vector],
            )
            if len(weights) != len(sample.embedding_vector):
                weights[:] = [0.0 for _ in sample.embedding_vector]
            for index, value in enumerate(error):
                weights[index] += feature_step * value

    def _nudge_family_logits(self, sample: LegalSample, *, learning_rate: float) -> None:
        step = _clamp_learning_rate(learning_rate)
        target = _target_family(sample)
        logits = self.state.family_logits.setdefault(sample.sample_id, {})
        logits[target] = logits.get(target, 0.0) + (2.0 * step)
        for family in self.modal_families:
            if family != target:
                logits[family] = logits.get(family, 0.0) - (
                    step / max(len(self.modal_families) - 1, 1)
                )
        feature_keys = self._feature_keys_for(sample)
        if not feature_keys:
            return
        feature_step = step / len(feature_keys)
        for feature in feature_keys:
            feature_logits = self.state.feature_family_logits.setdefault(feature, {})
            feature_logits[target] = feature_logits.get(target, 0.0) + (2.0 * feature_step)
            for family in self.modal_families:
                if family != target:
                    feature_logits[family] = feature_logits.get(family, 0.0) - (
                        feature_step / max(len(self.modal_families) - 1, 1)
                    )

    def _feature_embedding_adjustment(self, sample: LegalSample, *, dimensions: int) -> List[float]:
        adjustment = [0.0 for _ in range(dimensions)]
        for feature in self._feature_keys_for(sample):
            weights = self.state.feature_embedding_weights.get(feature)
            if weights is None or len(weights) != dimensions:
                continue
            for index, value in enumerate(weights):
                adjustment[index] += float(value)
        return adjustment

    def _feature_keys_for(self, sample: LegalSample) -> List[str]:
        if self.feature_codec is not None and hasattr(
            self.feature_codec,
            "feature_keys_for_sample",
        ):
            return _unique_preserve_order(
                str(value)
                for value in self.feature_codec.feature_keys_for_sample(sample)
            )
        keys: List[str] = []
        if sample.selected_frame:
            keys.append(f"frame:{sample.selected_frame}")
        for formula in sample.modal_ir.formulas:
            keys.append(f"modal-family:{formula.operator.family}")
            keys.append(f"modal-operator:{formula.operator.family}:{formula.operator.symbol}")
            cue = formula.metadata.get("cue") if formula.metadata else None
            if cue:
                keys.append(f"modal-cue:{str(cue).lower()}")
        keys.extend(f"token:{token}" for token in _token_features(sample.normalized_text))
        return _unique_preserve_order(keys)


def _observed_family_distribution(sample: LegalSample) -> Dict[str, float]:
    families = [formula.operator.family for formula in sample.modal_ir.formulas]
    if not families:
        return {ModalLogicFamily.HYBRID.value: 1.0}
    counts: Dict[str, int] = {}
    for family in families:
        counts[family] = counts.get(family, 0) + 1
    total = float(sum(counts.values()))
    return {family: count / total for family, count in sorted(counts.items())}


def _target_family(sample: LegalSample) -> str:
    if not sample.modal_ir.formulas:
        return ModalLogicFamily.HYBRID.value
    return sample.modal_ir.formulas[0].operator.family


def _all_modal_families() -> List[str]:
    return [family.value for family in ModalLogicFamily]


_TOKEN_RE = re.compile(r"[a-z0-9]+")
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


def _token_features(text: str) -> List[str]:
    return [
        token
        for token in _TOKEN_RE.findall(text.lower())
        if len(token) > 2 and token not in _STOPWORDS
    ][:40]


def _unique_preserve_order(values: Iterable[str]) -> List[str]:
    seen: set[str] = set()
    result: List[str] = []
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


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


def _mean(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0


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
    "AutoencoderEvaluation",
    "ModalAutoencoderBaseline",
    "ModalAutoencoderTrainingState",
    "cosine_loss",
    "cosine_similarity",
    "cross_entropy_loss",
    "frame_ranking_loss",
    "mse_loss",
    "symbolic_validity_penalty",
]
