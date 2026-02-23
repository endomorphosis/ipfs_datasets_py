"""Risk scoring for MCP++ tool invocations."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

__all__ = [
    "RiskLevel",
    "RiskScore",
    "RiskAssessment",
    "RiskScoringPolicy",
    "RiskScorer",
    "RiskGateError",
    "make_default_risk_policy",
    "score_intent",
]


class RiskGateError(Exception):
    """Raised when risk is unacceptable."""

    def __init__(self, message: str, assessment: "RiskAssessment") -> None:
        super().__init__(message)
        self.assessment = assessment


class RiskLevel(str, Enum):
    """Categorical risk level, from lowest to highest."""

    NEGLIGIBLE = "negligible"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

    @classmethod
    def from_score(cls, score: float) -> "RiskLevel":
        if score < 0.20:
            return cls.NEGLIGIBLE
        if score < 0.40:
            return cls.LOW
        if score < 0.60:
            return cls.MEDIUM
        if score < 0.80:
            return cls.HIGH
        return cls.CRITICAL


@dataclass
class RiskScore:
    """Result of a risk scoring computation."""

    level: RiskLevel
    score: float
    factors: List[str] = field(default_factory=list)
    mitigation_hints: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "level": self.level.value,
            "score": self.score,
            "factors": list(self.factors),
            "mitigation_hints": list(self.mitigation_hints),
        }


@dataclass
class RiskAssessment(RiskScore):
    """Detailed assessment returned by RiskScorer.score_intent."""

    is_acceptable: bool = True
    tool_base_risk: float = 0.0
    trust_factor: float = 1.0
    complexity_penalty: float = 0.0
    tool: str = ""
    actor: str = ""

    def to_dict(self) -> Dict[str, Any]:
        base = super().to_dict()
        base.update(
            {
                "is_acceptable": self.is_acceptable,
                "tool_base_risk": self.tool_base_risk,
                "trust_factor": self.trust_factor,
                "complexity_penalty": self.complexity_penalty,
                "tool": self.tool,
                "actor": self.actor,
            }
        )
        return base


@dataclass
class RiskScoringPolicy:
    """Configures the risk scoring behavior."""

    tool_risk_overrides: Dict[str, float] = field(default_factory=dict)
    default_risk: float = 0.3
    actor_trust_levels: Dict[str, float] = field(default_factory=dict)
    max_acceptable_risk: float = 0.75

    def get_tool_risk(self, tool_name: str) -> float:
        return self.tool_risk_overrides.get(tool_name, self.default_risk)

    def get_actor_trust(self, actor: str) -> float:
        return self.actor_trust_levels.get(actor, 0.5)


class RiskScorer:
    """Computes and gates intent risk."""

    _PARAM_PENALTY = 0.02
    _MAX_COMPLEXITY = 0.2

    def __init__(self, policy: Optional[RiskScoringPolicy] = None) -> None:
        self._policy = policy or RiskScoringPolicy()

    @property
    def policy(self) -> RiskScoringPolicy:
        return self._policy

    def score_intent(
        self,
        tool: str,
        actor: str = "",
        params: Optional[Dict[str, Any]] = None,
    ) -> RiskAssessment:
        policy = self._policy
        params = params or {}

        base_risk = policy.tool_risk_overrides.get(tool, policy.default_risk)
        trust_bonus = min(0.5, policy.actor_trust_levels.get(actor, 0.0))
        trust_factor = 1.0 - trust_bonus
        complexity_penalty = min(self._MAX_COMPLEXITY, len(params) * self._PARAM_PENALTY)

        score = min(1.0, base_risk * trust_factor + complexity_penalty)
        level = RiskLevel.from_score(score)
        is_acceptable = score <= policy.max_acceptable_risk

        factors = ["base_risk", "trust_factor", "complexity_penalty"]
        mitigation_hints: List[str] = []
        if level in (RiskLevel.HIGH, RiskLevel.CRITICAL):
            mitigation_hints.append("Consider reducing tool scope or adding approvals")

        return RiskAssessment(
            level=level,
            score=score,
            factors=factors,
            mitigation_hints=mitigation_hints,
            is_acceptable=is_acceptable,
            tool_base_risk=base_risk,
            trust_factor=trust_factor,
            complexity_penalty=complexity_penalty,
            tool=tool,
            actor=actor,
        )

    def is_acceptable(self, assessment: RiskAssessment) -> bool:
        return assessment.score <= self._policy.max_acceptable_risk

    def score_and_gate(
        self,
        tool: str,
        actor: str = "",
        params: Optional[Dict[str, Any]] = None,
    ) -> RiskAssessment:
        assessment = self.score_intent(tool=tool, actor=actor, params=params)
        if not assessment.is_acceptable:
            raise RiskGateError(
                f"Risk score {assessment.score:.3f} for tool={tool!r} exceeds limit",
                assessment,
            )
        return assessment

    def get_info(self) -> Dict[str, Any]:
        return {
            "default_risk": self._policy.default_risk,
            "max_acceptable_risk": self._policy.max_acceptable_risk,
        }


def make_default_risk_policy() -> RiskScoringPolicy:
    return RiskScoringPolicy()


def score_intent(tool: str, actor: str = "", params: Optional[Dict[str, Any]] = None) -> RiskAssessment:
    return RiskScorer().score_intent(tool=tool, actor=actor, params=params)
