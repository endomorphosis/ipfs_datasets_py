"""Risk Scorer — intent risk assessment and gate (MCP++ pipeline §risk stage).

The :class:`RiskScorer` computes a numeric risk score in ``[0, 1]`` for an
intent dict and either returns it as a :class:`RiskAssessment` or raises
:exc:`RiskGateError` if the score exceeds the policy maximum.

Risk formula::

    base_risk = policy.tool_risk_overrides.get(tool, policy.default_risk)
    trust_factor = 1.0 - min(0.5, policy.actor_trust_levels.get(actor, 0.0))
    complexity_penalty = min(0.2, len(params) * 0.02)
    score = min(1.0, base_risk * trust_factor + complexity_penalty)

Usage::

    from ipfs_datasets_py.mcp_server.risk_scorer import RiskScorer, RiskScoringPolicy

    policy = RiskScoringPolicy(
        tool_risk_overrides={"delete": 0.9},
        actor_trust_levels={"admin": 0.5},
    )
    scorer = RiskScorer(policy=policy)
    assessment = scorer.score_intent(tool="delete", actor="admin")
    print(assessment.level)      # RiskLevel.HIGH  (≈ 0.65)

    # score_and_gate raises RiskGateError if score > max_acceptable_risk
    scorer.score_and_gate(tool="read", actor="alice")  # OK
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class RiskGateError(Exception):
    """Raised by :meth:`RiskScorer.score_and_gate` when risk is unacceptable.

    Attributes
    ----------
    assessment:
        The :class:`RiskAssessment` that triggered the gate.
    """

    def __init__(self, message: str, assessment: "RiskAssessment") -> None:
        super().__init__(message)
        self.assessment = assessment


# ---------------------------------------------------------------------------
# RiskLevel
# ---------------------------------------------------------------------------


class RiskLevel(str, Enum):
    """Categorical risk level derived from a numeric score.

    | Level      | Score range |
    |------------|-------------|
    | NEGLIGIBLE | [0.0, 0.2)  |
    | LOW        | [0.2, 0.4)  |
    | MEDIUM     | [0.4, 0.6)  |
    | HIGH       | [0.6, 0.8)  |
    | CRITICAL   | [0.8, 1.0]  |
    """

    NEGLIGIBLE = "negligible"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

    @classmethod
    def from_score(cls, score: float) -> "RiskLevel":
        """Derive the level from a numeric *score* in ``[0, 1]``."""
        if score < 0.2:
            return cls.NEGLIGIBLE
        if score < 0.4:
            return cls.LOW
        if score < 0.6:
            return cls.MEDIUM
        if score < 0.8:
            return cls.HIGH
        return cls.CRITICAL


# ---------------------------------------------------------------------------
# RiskScoringPolicy
# ---------------------------------------------------------------------------


@dataclass
class RiskScoringPolicy:
    """Configuration for the :class:`RiskScorer`.

    Attributes
    ----------
    tool_risk_overrides:
        Per-tool base risk overrides in ``[0, 1]``.  Tools not listed fall
        back to *default_risk*.
    default_risk:
        Default base risk for tools without a specific override.
    actor_trust_levels:
        Per-actor trust bonus in ``[0, 0.5]``.  Higher trust → lower score.
    max_acceptable_risk:
        Upper bound for :meth:`RiskScorer.score_and_gate`.  A score strictly
        exceeding this value raises :exc:`RiskGateError`.
    """

    tool_risk_overrides: Dict[str, float] = field(default_factory=dict)
    default_risk: float = 0.3
    actor_trust_levels: Dict[str, float] = field(default_factory=dict)
    max_acceptable_risk: float = 0.75


# ---------------------------------------------------------------------------
# RiskAssessment
# ---------------------------------------------------------------------------


@dataclass
class RiskAssessment:
    """Outcome of :meth:`RiskScorer.score_intent`.

    Attributes
    ----------
    score:
        Computed numeric score in ``[0, 1]``.
    level:
        Categorical :class:`RiskLevel`.
    is_acceptable:
        Whether ``score <= policy.max_acceptable_risk``.
    tool_base_risk:
        Base risk before trust/complexity adjustments.
    trust_factor:
        Multiplier applied to base risk (``1 - trust_bonus``).
    complexity_penalty:
        Additive penalty based on params count.
    tool:
        Tool name used in the assessment.
    actor:
        Actor name used in the assessment.
    """

    score: float
    level: RiskLevel
    is_acceptable: bool
    tool_base_risk: float
    trust_factor: float
    complexity_penalty: float
    tool: str = ""
    actor: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "score": self.score,
            "level": self.level.value,
            "is_acceptable": self.is_acceptable,
            "tool_base_risk": self.tool_base_risk,
            "trust_factor": self.trust_factor,
            "complexity_penalty": self.complexity_penalty,
            "tool": self.tool,
            "actor": self.actor,
        }


# ---------------------------------------------------------------------------
# RiskScorer
# ---------------------------------------------------------------------------


class RiskScorer:
    """Computes and gates intent risk.

    Parameters
    ----------
    policy:
        Optional :class:`RiskScoringPolicy`.  Defaults to the standard policy
        (0.3 default risk, 0.75 max acceptable).
    """

    def __init__(self, policy: Optional[RiskScoringPolicy] = None) -> None:
        self._policy = policy or RiskScoringPolicy()

    @property
    def policy(self) -> RiskScoringPolicy:
        """The active :class:`RiskScoringPolicy`."""
        return self._policy

    # ------------------------------------------------------------------
    # Scoring
    # ------------------------------------------------------------------

    def score_intent(
        self,
        tool: str,
        actor: str = "",
        params: Optional[Dict[str, Any]] = None,
    ) -> RiskAssessment:
        """Compute and return a :class:`RiskAssessment` for the given intent.

        Parameters
        ----------
        tool:
            Tool name from the intent.
        actor:
            Actor identifier from the intent.
        params:
            Optional params dict — used for complexity penalty only.
        """
        policy = self._policy
        params = params or {}

        # Base risk for the tool
        base_risk = policy.tool_risk_overrides.get(tool, policy.default_risk)

        # Trust factor: actor trust reduces the effective risk
        trust_bonus = min(0.5, policy.actor_trust_levels.get(actor, 0.0))
        trust_factor = 1.0 - trust_bonus

        # Complexity penalty: more params → slightly higher risk
        complexity_penalty = min(0.2, len(params) * 0.02)

        score = min(1.0, base_risk * trust_factor + complexity_penalty)
        level = RiskLevel.from_score(score)
        is_acceptable = score <= policy.max_acceptable_risk

        return RiskAssessment(
            score=score,
            level=level,
            is_acceptable=is_acceptable,
            tool_base_risk=base_risk,
            trust_factor=trust_factor,
            complexity_penalty=complexity_penalty,
            tool=tool,
            actor=actor,
        )

    def is_acceptable(self, assessment: RiskAssessment) -> bool:
        """Return whether *assessment.score* is within the policy limit."""
        return assessment.score <= self._policy.max_acceptable_risk

    def score_and_gate(
        self,
        tool: str,
        actor: str = "",
        params: Optional[Dict[str, Any]] = None,
    ) -> RiskAssessment:
        """Score the intent and raise :exc:`RiskGateError` if unacceptable.

        Returns the :class:`RiskAssessment` if the score is within the
        policy's ``max_acceptable_risk`` threshold.

        Raises
        ------
        RiskGateError
            If ``assessment.score > policy.max_acceptable_risk``.
        """
        assessment = self.score_intent(tool=tool, actor=actor, params=params)
        if not assessment.is_acceptable:
            raise RiskGateError(
                f"Risk score {assessment.score:.3f} for tool={tool!r} "
                f"exceeds max_acceptable_risk={self._policy.max_acceptable_risk}",
                assessment=assessment,
            )
        return assessment

    def get_info(self) -> Dict[str, Any]:
        """Return a dict describing the scorer configuration."""
        return {
            "default_risk": self._policy.default_risk,
            "max_acceptable_risk": self._policy.max_acceptable_risk,
            "tool_overrides_count": len(self._policy.tool_risk_overrides),
            "actor_trust_count": len(self._policy.actor_trust_levels),
        }

    def __repr__(self) -> str:
        return (
            f"RiskScorer(default_risk={self._policy.default_risk}, "
            f"max_acceptable={self._policy.max_acceptable_risk})"
        )
