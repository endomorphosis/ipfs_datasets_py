"""Base critic interface for all optimizer types.

Provides the common evaluation interface that all critics follow:
    artifact → evaluate() → (score: float, feedback: list[str])

All critic implementations (OntologyCritic, LogicCritic, …) should extend
BaseCritic and implement at minimum ``evaluate()``.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class CriticResult:
    """Structured result returned by a critic evaluation.

    Attributes:
        score: Overall quality score in [0.0, 1.0].
        feedback: Ordered list of actionable improvement suggestions.
        dimensions: Per-dimension scores keyed by name.
        strengths: Observed strengths in the artifact.
        weaknesses: Observed weaknesses in the artifact.
        metadata: Arbitrary extra data (evaluator name, domain, …).
    """

    score: float
    feedback: List[str] = field(default_factory=list)
    dimensions: Dict[str, float] = field(default_factory=dict)
    strengths: List[str] = field(default_factory=list)
    weaknesses: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.score = float(max(0.0, min(1.0, self.score)))


class BaseCritic(ABC):
    """Abstract base class for all critic implementations.

    A critic evaluates an artifact produced by a generator and returns a
    structured :class:`CriticResult` that the optimizer uses to improve the
    artifact in the next iteration.

    Subclasses must implement :meth:`evaluate`.  Optionally override
    :meth:`compare` to support side-by-side comparison of two artifacts.

    Example::

        class MyCritic(BaseCritic):
            def evaluate(self, artifact, context):
                score = self._score(artifact)
                return CriticResult(
                    score=score,
                    feedback=["Add more detail"] if score < 0.8 else [],
                )

        critic = MyCritic()
        result = critic.evaluate(my_artifact, context)
        print(result.score)
    """

    # ------------------------------------------------------------------ #
    # Abstract interface                                                   #
    # ------------------------------------------------------------------ #

    @abstractmethod
    def evaluate(
        self,
        artifact: Any,
        context: Any,
        *,
        source_data: Optional[Any] = None,
    ) -> CriticResult:
        """Evaluate the quality of *artifact*.

        Args:
            artifact: The artifact to evaluate (type depends on the optimizer).
            context: The optimization context (e.g. ``OptimizationContext``).
            source_data: Optional original source data for reference evaluation.

        Returns:
            :class:`CriticResult` with score, feedback, and dimension scores.
        """

    # ------------------------------------------------------------------ #
    # Optional helpers                                                     #
    # ------------------------------------------------------------------ #

    def compare(
        self,
        artifact_a: Any,
        artifact_b: Any,
        context: Any,
    ) -> Dict[str, Any]:
        """Compare two artifacts and return a diff report.

        Default implementation evaluates both independently and computes
        per-dimension deltas.  Override for domain-specific comparison.

        Args:
            artifact_a: First artifact (typically the older version).
            artifact_b: Second artifact (typically the newer version).
            context: Shared optimization context.

        Returns:
            Dictionary with keys:
            - ``winner``: ``"a"``, ``"b"``, or ``"tie"``
            - ``delta``: score difference (b.score − a.score)
            - ``dimension_deltas``: per-dimension score deltas
            - ``result_a`` / ``result_b``: full :class:`CriticResult` objects
        """
        result_a = self.evaluate(artifact_a, context)
        result_b = self.evaluate(artifact_b, context)
        delta = result_b.score - result_a.score

        dim_deltas: Dict[str, float] = {}
        for dim in set(result_a.dimensions) | set(result_b.dimensions):
            dim_deltas[dim] = result_b.dimensions.get(dim, 0.0) - result_a.dimensions.get(dim, 0.0)

        if delta > 0.01:
            winner = "b"
        elif delta < -0.01:
            winner = "a"
        else:
            winner = "tie"

        return {
            "winner": winner,
            "delta": round(delta, 4),
            "dimension_deltas": dim_deltas,
            "result_a": result_a,
            "result_b": result_b,
        }

    def score_only(self, artifact: Any, context: Any) -> float:
        """Convenience wrapper — returns only the scalar score."""
        return self.evaluate(artifact, context).score

    def feedback_only(self, artifact: Any, context: Any) -> List[str]:
        """Convenience wrapper — returns only the feedback list."""
        return self.evaluate(artifact, context).feedback


__all__ = ["BaseCritic", "CriticResult"]
