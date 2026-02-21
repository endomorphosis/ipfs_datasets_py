"""OntologyLearningAdapter — feedback-driven extraction tuning.

Tracks which extraction patterns led to high-quality ontologies (as judged
by the critic) and adjusts confidence thresholds accordingly.  This creates
a closed feedback loop:

    OntologyGenerator → OntologyCritic → OntologyMediator → OntologyLearningAdapter
                ↑_____________________________________________|

The adapter is **stateful but side-effect-free**: it never mutates the
generator directly.  Instead call :meth:`get_extraction_hint` to retrieve
a recommended threshold before generating, and call :meth:`apply_feedback`
after each refinement cycle to record the outcome.

Usage
-----
.. code-block:: python

    from ipfs_datasets_py.optimizers.graphrag.ontology_learning_adapter import (
        OntologyLearningAdapter,
    )

    adapter = OntologyLearningAdapter(domain="legal")

    # Before extraction:
    threshold = adapter.get_extraction_hint()

    # After a refinement cycle:
    adapter.apply_feedback(final_score=state.critic_scores[-1].overall,
                           actions=state.refinement_history)

    # Inspect weights:
    print(adapter.get_stats())
"""

from __future__ import annotations

import logging
import math
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

_logger = logging.getLogger(__name__)

# Default fallback threshold for LLM extraction
_DEFAULT_THRESHOLD: float = 0.5
# How many feedback samples must accumulate before adjusting threshold
_MIN_SAMPLES_FOR_ADJUSTMENT: int = 3
# Weight given to recent feedback vs. historical average (0–1, higher = more reactive)
_EMA_ALPHA: float = 0.3


@dataclass
class FeedbackRecord:
    """Single feedback observation from one refinement cycle."""

    final_score: float
    action_types: List[str] = field(default_factory=list)
    confidence_at_extraction: Optional[float] = None


class OntologyLearningAdapter:
    """Adapt extraction thresholds based on refinement cycle feedback.

    Args:
        domain: Domain hint used for per-domain threshold tracking.
        base_threshold: Initial extraction confidence threshold.
        ema_alpha: Exponential moving-average smoothing factor for threshold
            updates (0 < alpha ≤ 1, higher = more reactive to recent data).
        min_samples: Minimum feedback samples before adjusting threshold.
    """

    def __init__(
        self,
        domain: str = "general",
        base_threshold: float = _DEFAULT_THRESHOLD,
        ema_alpha: float = _EMA_ALPHA,
        min_samples: int = _MIN_SAMPLES_FOR_ADJUSTMENT,
    ) -> None:
        self.domain = domain
        self._base_threshold = base_threshold
        self._current_threshold: float = base_threshold
        self._ema_alpha = ema_alpha
        self._min_samples = min_samples

        self._feedback: List[FeedbackRecord] = []
        # Per action-type: running weighted success count and total count
        self._action_success: Dict[str, float] = defaultdict(float)
        self._action_count: Dict[str, int] = defaultdict(int)

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def apply_feedback(
        self,
        final_score: float,
        actions: Optional[Sequence[Any]] = None,
        confidence_at_extraction: Optional[float] = None,
    ) -> None:
        """Record outcomes of a completed refinement cycle.

        Args:
            final_score: Overall critic score at the end of the cycle (0–1).
            actions: Sequence of refinement history entries (dicts with an
                ``'action'`` key) or :class:`MediatorState` round entries.
            confidence_at_extraction: Rule-based confidence that was
                reported at extraction time (optional, used for correlation).
        """
        action_types: List[str] = []
        for entry in (actions or []):
            action_str = (
                entry.get("action", "") if isinstance(entry, dict) else str(entry)
            )
            if action_str:
                action_types.append(action_str)

        record = FeedbackRecord(
            final_score=max(0.0, min(1.0, float(final_score))),
            action_types=action_types,
            confidence_at_extraction=confidence_at_extraction,
        )
        self._feedback.append(record)

        # Update per-action success rates
        for action in action_types:
            self._action_count[action] += 1
            self._action_success[action] += record.final_score

        # Adjust threshold via EMA once we have enough samples
        if len(self._feedback) >= self._min_samples:
            self._update_threshold()

        _logger.debug(
            "OntologyLearningAdapter.apply_feedback: score=%.3f actions=%s "
            "new_threshold=%.3f samples=%d",
            record.final_score,
            action_types,
            self._current_threshold,
            len(self._feedback),
        )

    def get_extraction_hint(self) -> float:
        """Return the recommended extraction confidence threshold.

        The hint is computed as the EMA-adjusted threshold with a small
        correction derived from the **average per-action success rate**.
        When successful actions dominate, the correction lowers the threshold
        slightly (allow more extractions); when actions are rarely successful
        the threshold is raised.

        Returns:
            Float in [0.1, 0.9].  Values below this threshold should trigger
            LLM-based fallback extraction.
        """
        base = self._current_threshold
        if not self._action_count:
            return base

        # Weighted mean success rate across all recorded actions
        total_count = sum(self._action_count.values())
        total_success = sum(self._action_success.values())
        mean_action_success = total_success / total_count if total_count else 0.5

        # Correction: ±0.05 based on deviation from neutral (0.5)
        correction = 0.05 * (0.5 - mean_action_success)  # positive → raise threshold
        adjusted = base + correction
        return max(0.1, min(0.9, adjusted))

    def get_stats(self) -> Dict[str, Any]:
        """Return a summary of the adapter's internal state.

        Returns:
            Dictionary with keys ``current_threshold``, ``sample_count``,
            ``mean_score``, ``p50_score``, ``p90_score``,
            ``action_success_rates``, ``domain``.
        """
        scores = [r.final_score for r in self._feedback]
        mean_score = sum(scores) / len(scores) if scores else 0.0

        def _percentile(data: list, pct: float) -> float:
            """Return the *pct*-th percentile of *data* (0–100)."""
            if not data:
                return 0.0
            sorted_data = sorted(data)
            idx = (pct / 100.0) * (len(sorted_data) - 1)
            lo = int(idx)
            hi = min(lo + 1, len(sorted_data) - 1)
            frac = idx - lo
            return sorted_data[lo] + frac * (sorted_data[hi] - sorted_data[lo])

        action_success_rates: Dict[str, float] = {}
        for action, count in self._action_count.items():
            if count > 0:
                action_success_rates[action] = self._action_success[action] / count

        return {
            "domain": self.domain,
            "current_threshold": self._current_threshold,
            "base_threshold": self._base_threshold,
            "sample_count": len(self._feedback),
            "mean_score": mean_score,
            "p50_score": _percentile(scores, 50),
            "p90_score": _percentile(scores, 90),
            "action_success_rates": action_success_rates,
        }

    def reset(self) -> None:
        """Reset adapter state to base threshold (useful for testing)."""
        self._feedback.clear()
        self._action_success.clear()
        self._action_count.clear()
        self._current_threshold = self._base_threshold

    def top_actions(self, n: int = 5) -> List[Dict[str, Any]]:
        """Return the top-N actions sorted by mean success rate (descending).

        Args:
            n: Maximum number of actions to return (default: 5).

        Returns:
            List of dicts with keys:
            - ``action``: action name
            - ``count``: number of times applied
            - ``mean_success``: mean critic score when this action was applied
        """
        results = []
        for action, count in self._action_count.items():
            if count > 0:
                mean_success = self._action_success[action] / count
                results.append({
                    "action": action,
                    "count": count,
                    "mean_success": round(mean_success, 4),
                })
        results.sort(key=lambda x: x["mean_success"], reverse=True)
        return results[:max(1, n)]

    # ------------------------------------------------------------------ #
    # Internal helpers                                                     #
    # ------------------------------------------------------------------ #

    def _update_threshold(self) -> None:
        """Update current threshold using EMA of recent mean scores."""
        recent = self._feedback[-self._min_samples :]
        recent_mean = sum(r.final_score for r in recent) / len(recent)

        # When recent mean quality is high (≥ 0.8), loosen threshold (let more
        # rule-based results through).  When low (< 0.5), tighten threshold
        # (trigger LLM fallback more aggressively).
        target = self._score_to_threshold(recent_mean)
        self._current_threshold = (
            self._ema_alpha * target
            + (1.0 - self._ema_alpha) * self._current_threshold
        )
        # Clamp to [0.1, 0.9]
        self._current_threshold = max(0.1, min(0.9, self._current_threshold))

    def to_dict(self) -> Dict[str, Any]:
        """Serialize adapter state to a JSON-compatible dictionary.

        Returns:
            Dict with all state needed to reconstruct the adapter via
            :meth:`from_dict`.
        """
        return {
            "domain": self.domain,
            "base_threshold": self._base_threshold,
            "current_threshold": self._current_threshold,
            "ema_alpha": self._ema_alpha,
            "min_samples": self._min_samples,
            "feedback": [
                {
                    "final_score": r.final_score,
                    "action_types": list(r.action_types),
                    "confidence_at_extraction": r.confidence_at_extraction,
                }
                for r in self._feedback
            ],
            "action_success": dict(self._action_success),
            "action_count": dict(self._action_count),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "OntologyLearningAdapter":
        """Reconstruct an adapter from a serialized dictionary.

        Args:
            data: Dictionary as produced by :meth:`to_dict`.

        Returns:
            New :class:`OntologyLearningAdapter` with restored state.
        """
        adapter = cls(
            domain=data.get("domain", "general"),
            base_threshold=float(data.get("base_threshold", _DEFAULT_THRESHOLD)),
            ema_alpha=float(data.get("ema_alpha", _EMA_ALPHA)),
            min_samples=int(data.get("min_samples", _MIN_SAMPLES_FOR_ADJUSTMENT)),
        )
        adapter._current_threshold = float(
            data.get("current_threshold", adapter._base_threshold)
        )
        for rec in data.get("feedback", []):
            adapter._feedback.append(
                FeedbackRecord(
                    final_score=float(rec.get("final_score", 0.0)),
                    action_types=list(rec.get("action_types", [])),
                    confidence_at_extraction=rec.get("confidence_at_extraction"),
                )
            )
        for action, success in data.get("action_success", {}).items():
            adapter._action_success[action] = float(success)
        for action, count in data.get("action_count", {}).items():
            adapter._action_count[action] = int(count)
        return adapter

    def serialize(self) -> bytes:
        """Serialize adapter state to UTF-8 encoded JSON bytes.

        This is a pickle-free, human-readable alternative to binary
        serialisation.  Round-trip via :meth:`deserialize`.

        Returns:
            UTF-8 encoded JSON bytes representing the full adapter state.
        """
        import json as _json
        return _json.dumps(self.to_dict(), indent=None, separators=(",", ":")).encode("utf-8")

    @classmethod
    def deserialize(cls, data: bytes) -> "OntologyLearningAdapter":
        """Reconstruct an adapter from bytes produced by :meth:`serialize`.

        Args:
            data: UTF-8 encoded JSON bytes (output of :meth:`serialize`).

        Returns:
            New :class:`OntologyLearningAdapter` with restored state.
        """
        import json as _json
        return cls.from_dict(_json.loads(data.decode("utf-8")))

    @staticmethod
    def _score_to_threshold(mean_score: float) -> float:
        """Map mean quality score to a target confidence threshold.

        Higher quality → lower threshold (less LLM fallback needed).
        Lower quality  → higher threshold (more LLM fallback triggered).
        """
        # Linear inverse mapping: score 1.0 → threshold 0.2, score 0.0 → 0.9
        return 0.9 - 0.7 * max(0.0, min(1.0, mean_score))

    def reset_feedback(self) -> int:
        """Clear the feedback history without resetting thresholds or action stats.

        Removes all :class:`FeedbackRecord` entries from the internal list
        while preserving the current threshold and action success/count
        dictionaries.

        Returns:
            Number of feedback records that were cleared.

        Example:
            >>> n = adapter.reset_feedback()
            >>> len(adapter._feedback) == 0
            True
        """
        count = len(self._feedback)
        self._feedback.clear()
        return count

    def feedback_summary(self) -> Dict[str, Any]:
        """Return descriptive statistics for the current feedback history.

        Returns:
            Dict with keys:

            * ``"count"`` -- number of feedback records.
            * ``"mean_score"`` -- mean ``final_score`` across records.
            * ``"min_score"`` -- minimum ``final_score``.
            * ``"max_score"`` -- maximum ``final_score``.
            * ``"current_threshold"`` -- current extraction threshold.

        Example:
            >>> summary = adapter.feedback_summary()
            >>> summary["count"] == len(adapter._feedback)
            True
        """
        count = len(self._feedback)
        if count == 0:
            return {
                "count": 0,
                "mean_score": 0.0,
                "min_score": 0.0,
                "max_score": 0.0,
                "current_threshold": self._current_threshold,
            }
        scores = [r.final_score for r in self._feedback]
        return {
            "count": count,
            "mean_score": round(sum(scores) / count, 6),
            "min_score": round(min(scores), 6),
            "max_score": round(max(scores), 6),
            "current_threshold": self._current_threshold,
        }

    def serialize_to_file(self, path: str) -> None:
        """Persist the adapter state to a JSON file.

        Serializes :attr:`_feedback`, :attr:`_current_threshold`, and
        :attr:`_action_count` / :attr:`_action_success` dicts to a JSON file
        so the adapter can be restored later via :meth:`from_file`.

        Args:
            path: Filesystem path to write.  Parent directory must exist.

        Example:
            >>> adapter.serialize_to_file("/tmp/adapter.json")
        """
        import json as _json
        payload = {
            "current_threshold": self._current_threshold,
            "action_count": dict(self._action_count),
            "action_success": dict(self._action_success),
            "feedback": [
                {
                    "final_score": r.final_score,
                    "action_types": list(r.action_types),
                    "confidence_at_extraction": r.confidence_at_extraction,
                }
                for r in self._feedback
            ],
        }
        with open(path, "w", encoding="utf-8") as fh:
            _json.dump(payload, fh, indent=2)

    @classmethod
    def from_file(cls, path: str, **init_kwargs) -> "OntologyLearningAdapter":
        """Restore an adapter previously saved with :meth:`serialize_to_file`.

        Args:
            path: Path of the JSON file written by :meth:`serialize_to_file`.
            **init_kwargs: Extra keyword arguments forwarded to
                :meth:`__init__` (e.g. ``domain``, ``base_threshold``).

        Returns:
            New :class:`OntologyLearningAdapter` with state restored.

        Example:
            >>> adapter2 = OntologyLearningAdapter.from_file("/tmp/adapter.json")
        """
        import json as _json
        with open(path, "r", encoding="utf-8") as fh:
            payload = _json.load(fh)
        instance = cls(**init_kwargs)
        instance._current_threshold = payload.get("current_threshold", instance._current_threshold)
        instance._action_count = dict(payload.get("action_count", {}))
        instance._action_success = dict(payload.get("action_success", {}))
        instance._feedback = [
            FeedbackRecord(
                final_score=r["final_score"],
                action_types=list(r.get("action_types", [])),
                confidence_at_extraction=r.get("confidence_at_extraction"),
            )
            for r in payload.get("feedback", [])
        ]
        return instance

    def top_feedback_scores(self, n: int = 5) -> List["FeedbackRecord"]:
        """Return the top *n* feedback records sorted by ``final_score`` descending.

        Args:
            n: Number of records to return.  Defaults to 5.

        Returns:
            List of :class:`FeedbackRecord` objects, length <= n, in
            descending score order.

        Example:
            >>> top = adapter.top_feedback_scores(3)
            >>> len(top) <= 3
            True
        """
        return sorted(self._feedback, key=lambda r: r.final_score, reverse=True)[:n]

    def feedback_count(self) -> int:
        """Return the number of feedback records in the history.

        Shortcut for ``len(adapter._feedback)``.

        Returns:
            Non-negative integer.

        Example:
            >>> adapter.feedback_count()
            0
        """
        return len(self._feedback)

    def worst_feedback_scores(self, n: int = 5) -> List["FeedbackRecord"]:
        """Return the bottom *n* feedback records sorted by ``final_score`` ascending.

        Args:
            n: Number of records to return.  Defaults to 5.

        Returns:
            List of :class:`FeedbackRecord` objects, length <= n, in
            ascending score order (worst first).

        Example:
            >>> worst = adapter.worst_feedback_scores(3)
            >>> len(worst) <= 3
            True
        """
        return sorted(self._feedback, key=lambda r: r.final_score)[:n]

    def mean_score(self) -> float:
        """Return the mean ``final_score`` across all feedback records.

        Returns:
            Mean score as a float.  Returns ``0.0`` if no feedback has been
            recorded.

        Example:
            >>> adapter.mean_score()
            0.0
        """
        if not self._feedback:
            return 0.0
        return sum(r.final_score for r in self._feedback) / len(self._feedback)

    def score_variance(self) -> float:
        """Return the variance of ``final_score`` across all feedback records.

        Returns:
            Variance as a float.  Returns ``0.0`` when there are fewer than
            two feedback records.

        Example:
            >>> adapter.score_variance()
            0.0
        """
        if len(self._feedback) < 2:
            return 0.0
        mean = self.mean_score()
        return sum((r.final_score - mean) ** 2 for r in self._feedback) / len(self._feedback)

    def load_feedback_from_list(self, records: List["FeedbackRecord"]) -> int:
        """Bulk-load a list of :class:`FeedbackRecord` objects into this adapter.

        Existing feedback is preserved; new records are appended.

        Args:
            records: List of :class:`FeedbackRecord` objects to add.

        Returns:
            Total number of feedback records after the load.

        Example:
            >>> n = adapter.load_feedback_from_list([record1, record2])
            >>> n >= 2
            True
        """
        self._feedback.extend(records)
        return len(self._feedback)

    def latest_feedback(self) -> Optional["FeedbackRecord"]:
        """Return the most recently recorded :class:`FeedbackRecord`.

        Returns:
            The last feedback entry, or ``None`` if no feedback has been
            recorded.

        Example:
            >>> adapter.latest_feedback()
        """
        if not self._feedback:
            return None
        return self._feedback[-1]

    def clear_feedback(self) -> int:
        """Remove all feedback records from this adapter.

        Returns:
            Number of records cleared.

        Example:
            >>> adapter.clear_feedback()
            0
        """
        n = len(self._feedback)
        self._feedback.clear()
        return n

    def feedback_summary_dict(self) -> dict:
        """Return a summary dict with count, mean, and variance of feedback scores.

        Returns:
            Dict with keys ``count``, ``mean``, ``variance``.

        Example:
            >>> adapter.feedback_summary_dict()
            {'count': 0, 'mean': 0.0, 'variance': 0.0}
        """
        return {
            "count": self.feedback_count(),
            "mean": self.mean_score(),
            "variance": self.score_variance(),
        }
