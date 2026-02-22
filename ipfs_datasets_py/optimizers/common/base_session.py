"""Base session dataclass for all optimizer types.

Tracks the state of an active optimization session: rounds completed, scores
recorded, convergence status, and execution time.  All concrete session classes
(``MediatorState``, ``TheoremSession``, …) should either extend
``BaseSession`` directly or mirror its interface.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional


@dataclass
class RoundRecord:
    """Record of a single optimization round.

    Attributes:
        round_number: 1-based round index.
        score: Quality score after this round.
        feedback: Feedback messages that drove the next refinement.
        artifact_snapshot: Optional serializable snapshot of the artifact.
        duration_ms: Wall-clock time spent in this round (milliseconds).
        metadata: Extra per-round data.
    """

    round_number: int
    score: float
    feedback: List[str] = field(default_factory=list)
    artifact_snapshot: Optional[Any] = None
    duration_ms: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __repr__(self) -> str:
        """Concise REPL-friendly representation."""
        fb_count = len(self.feedback)
        has_snapshot = self.artifact_snapshot is not None
        return (
            f"RoundRecord(round={self.round_number}, score={self.score:.3f}, "
            f"feedback_items={fb_count}, has_artifact={has_snapshot}, "
            f"duration_ms={self.duration_ms:.1f})"
        )


@dataclass
class BaseSession:
    """Common state container for an optimization session.

    Tracks rounds, scores, and convergence so that all optimizer types share a
    consistent session data model.

    Attributes:
        session_id: Unique identifier for this session.
        domain: Optimization domain (e.g. ``"graphrag"``, ``"logic"``, ``"agentic"``).
        max_rounds: Maximum number of refinement rounds allowed.
        target_score: Score at which optimization is considered successful.
        convergence_threshold: Minimum score improvement required to continue.
        rounds: Ordered list of :class:`RoundRecord` objects.
        converged: ``True`` once convergence criteria are met.
        started_at: Wall-clock time when the session began.
        finished_at: Wall-clock time when the session ended (or ``None``).
        metadata: Arbitrary extra session metadata.

    Example::

        session = BaseSession(
            session_id="s-001",
            domain="graphrag",
            max_rounds=10,
            target_score=0.85,
        )
        session.record_round(score=0.62, feedback=["Add more entities"])
        session.record_round(score=0.79, feedback=["Improve consistency"])
        session.finish()
        print(session.best_score)   # 0.79
        print(session.trend)        # "improving"
    """

    session_id: str
    domain: str = "general"
    max_rounds: int = 10
    target_score: float = 0.85
    convergence_threshold: float = 0.01

    rounds: List[RoundRecord] = field(default_factory=list)
    converged: bool = False
    started_at: datetime = field(default_factory=datetime.now)
    finished_at: Optional[datetime] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    # Internal timer (not serialized)
    _round_start: float = field(default=0.0, repr=False, compare=False)

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def start_round(self) -> int:
        """Mark the beginning of a new round.

        Returns:
            The 1-based round number that is about to start.
        """
        self._round_start = time.monotonic()
        return len(self.rounds) + 1

    def record_round(
        self,
        score: float,
        feedback: Optional[List[str]] = None,
        artifact_snapshot: Optional[Any] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> RoundRecord:
        """Record the result of a completed round.

        Args:
            score: Quality score achieved this round.
            feedback: Suggestions for the next round.
            artifact_snapshot: Optional artifact to persist.
            metadata: Extra per-round data.

        Returns:
            The :class:`RoundRecord` that was appended.
        """
        duration_ms = (time.monotonic() - self._round_start) * 1000.0
        record = RoundRecord(
            round_number=len(self.rounds) + 1,
            score=float(score),
            feedback=list(feedback or []),
            artifact_snapshot=artifact_snapshot,
            duration_ms=round(duration_ms, 2),
            metadata=metadata or {},
        )
        self.rounds.append(record)

        # Check convergence
        if score >= self.target_score:
            self.converged = True
        elif len(self.rounds) >= 2:
            improvement = self.rounds[-1].score - self.rounds[-2].score
            if improvement < self.convergence_threshold:
                self.converged = True

        return record

    def finish(self) -> None:
        """Mark the session as complete."""
        self.finished_at = datetime.now()

    def __repr__(self) -> str:
        """Concise REPL-friendly representation."""
        status = "converged" if self.converged else "active" if self.finished_at is None else "finished"
        best = self.best_score
        return (
            f"BaseSession(id={self.session_id!r}, domain={self.domain!r}, "
            f"rounds={len(self.rounds)}/{self.max_rounds}, best_score={best:.3f}, "
            f"status={status})"
        )

    # ------------------------------------------------------------------ #
    # Derived properties                                                   #
    # ------------------------------------------------------------------ #

    @property
    def current_round(self) -> int:
        """Number of rounds completed so far."""
        return len(self.rounds)

    @property
    def best_score(self) -> float:
        """Highest score achieved across all rounds."""
        return max((r.score for r in self.rounds), default=0.0)

    @property
    def latest_score(self) -> float:
        """Score from the most recent round (0.0 if no rounds yet)."""
        return self.rounds[-1].score if self.rounds else 0.0

    @property
    def scores(self) -> List[float]:
        """All recorded scores in chronological order."""
        return [r.score for r in self.rounds]

    @property
    def trend(self) -> str:
        """Overall trend across all rounds.

        Returns:
            One of ``"improving"``, ``"stable"``, ``"degrading"``,
            or ``"insufficient_data"``.
        """
        if len(self.rounds) < 2:
            return "insufficient_data"
        delta = self.rounds[-1].score - self.rounds[0].score
        if delta > 0.05:
            return "improving"
        if delta < -0.05:
            return "degrading"
        return "stable"

    @property
    def total_duration_ms(self) -> float:
        """Total wall-clock time across all recorded rounds."""
        return sum(r.duration_ms for r in self.rounds)

    @property
    def score_delta(self) -> float:
        """Score improvement from first to last round (negative = regression)."""
        if len(self.rounds) < 2:
            return 0.0
        return self.rounds[-1].score - self.rounds[0].score

    @property
    def avg_score(self) -> float:
        """Mean score across all rounds (0.0 if no rounds)."""
        if not self.rounds:
            return 0.0
        return sum(r.score for r in self.rounds) / len(self.rounds)

    @property
    def regression_count(self) -> int:
        """Number of rounds where the score decreased relative to the previous round."""
        count = 0
        for i in range(1, len(self.rounds)):
            if self.rounds[i].score < self.rounds[i - 1].score:
                count += 1
        return count

    def to_dict(self) -> Dict[str, Any]:
        """Serialize session state to a plain dictionary."""
        return {
            "session_id": self.session_id,
            "domain": self.domain,
            "max_rounds": self.max_rounds,
            "target_score": self.target_score,
            "current_round": self.current_round,
            "best_score": self.best_score,
            "latest_score": self.latest_score,
            "avg_score": round(self.avg_score, 4),
            "score_delta": round(self.score_delta, 4),
            "regression_count": self.regression_count,
            "trend": self.trend,
            "converged": self.converged,
            "total_duration_ms": self.total_duration_ms,
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "metadata": self.metadata,
            "rounds": [
                {
                    "round": r.round_number,
                    "score": r.score,
                    "feedback_count": len(r.feedback),
                    "duration_ms": r.duration_ms,
                }
                for r in self.rounds
            ],
        }

    def to_json(self, **json_kwargs) -> str:
        """Serialize session state to a JSON string.

        Args:
            **json_kwargs: Passed directly to ``json.dumps()`` (e.g. ``indent=2``).

        Returns:
            JSON string representation of the session.
        """
        import json as _json
        return _json.dumps(self.to_dict(), **json_kwargs)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "BaseSession":
        """Reconstruct a (finished) BaseSession from a plain dictionary.

        Args:
            data: Dictionary as produced by :meth:`to_dict`.

        Returns:
            A new :class:`BaseSession` with rounds and metadata populated.
        """
        import datetime as _dt

        session = cls(
            session_id=data.get("session_id", "unknown"),
            domain=data.get("domain", "general"),
            max_rounds=data.get("max_rounds", 10),
            target_score=data.get("target_score", 0.85),
        )
        for r in data.get("rounds", []):
            session.start_round()
            session.record_round(score=r.get("score", 0.0), feedback={}, metadata={})
        session.metadata.update(data.get("metadata") or {})
        try:
            session.started_at = _dt.datetime.fromisoformat(data["started_at"])
        except (KeyError, ValueError):
            pass
        if data.get("finished_at"):
            try:
                session.finished_at = _dt.datetime.fromisoformat(data["finished_at"])
            except (ValueError,):
                pass
        return session

    @classmethod
    def from_json(cls, json_str: str) -> "BaseSession":
        """Reconstruct a :class:`BaseSession` from a JSON string.

        Args:
            json_str: JSON string as produced by :meth:`to_json`.
        """
        import json as _json
        return cls.from_dict(_json.loads(json_str))


__all__ = ["BaseSession", "RoundRecord"]
