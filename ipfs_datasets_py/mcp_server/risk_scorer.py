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
    "risk_score_from_dag",
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

    def _normalize_intent(
        self,
        tool: Any,
        actor: str = "",
        params: Optional[Dict[str, Any]] = None,
    ) -> tuple[str, str, Dict[str, Any]]:
        if isinstance(tool, dict):
            tool_name = str(tool.get("tool_name") or tool.get("tool") or "")
            actor_name = str(tool.get("actor") or actor or "")
            params_obj = tool.get("params")
            if not isinstance(params_obj, dict):
                params_obj = params or {}
            return tool_name, actor_name, params_obj

        if not isinstance(tool, str):
            tool_name = str(getattr(tool, "tool_name", getattr(tool, "tool", "")) or "")
            actor_name = str(getattr(tool, "actor", actor) or "")
            params_obj = getattr(tool, "params", params or {})
            if not isinstance(params_obj, dict):
                params_obj = params or {}
            return tool_name, actor_name, params_obj

        return tool, actor, params or {}

    def score_intent(
        self,
        tool: Any,
        actor: str = "",
        params: Optional[Dict[str, Any]] = None,
    ) -> RiskAssessment:
        policy = self._policy
        tool, actor, params = self._normalize_intent(tool, actor, params)

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
        tool: Any,
        actor: Any = "",
        params: Optional[Dict[str, Any]] = None,
    ) -> Any:
        if isinstance(actor, RiskScoringPolicy) and params is None:
            legacy_policy = actor
            assessment = RiskScorer(legacy_policy).score_intent(tool)
            return {
                "decision": "allow" if assessment.is_acceptable else "deny",
                "risk_score": assessment.score,
                "risk_level": assessment.level.value,
            }

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


def make_default_risk_policy(
    high_risk_tools: Optional[List[str]] = None,
    *,
    default_risk: float = 0.3,
    max_acceptable_risk: float = 0.75,
    actor_trust_levels: Optional[Dict[str, float]] = None,
    tool_risk_overrides: Optional[Dict[str, float]] = None,
) -> RiskScoringPolicy:
    overrides = dict(tool_risk_overrides or {})
    for tool_name in high_risk_tools or []:
        overrides.setdefault(str(tool_name), 0.70)
    return RiskScoringPolicy(
        tool_risk_overrides=overrides,
        default_risk=default_risk,
        actor_trust_levels=dict(actor_trust_levels or {}),
        max_acceptable_risk=max_acceptable_risk,
    )


def score_intent(tool: Any, actor: str = "", params: Optional[Dict[str, Any]] = None) -> RiskAssessment:
    return RiskScorer().score_intent(tool=tool, actor=actor, params=params)


def risk_score_from_dag(
    dag: Any,
    tool_name: str = "",
    *,
    rollback_penalty: float = 0.15,
    error_penalty: float = 0.10,
    max_penalty: float = 1.0,
) -> float:
    """Compatibility helper: derive a small risk penalty from EventDAG history.

    Returns a value in ``[0.0, 1.0]``. Empty DAGs return ``0.0``.
    """
    nodes: List[Any] = []
    raw_nodes = getattr(dag, "_nodes", None)
    if isinstance(raw_nodes, dict):
        nodes = list(raw_nodes.values())

    if not nodes:
        return 0.0

    penalty = 0.0
    for node in nodes:
        output_cid = str(getattr(node, "output_cid", "") or "").lower()
        receipt_cid = getattr(node, "receipt_cid", None)

        if "rollback" in output_cid:
            penalty += float(rollback_penalty)
        if receipt_cid in (None, ""):
            penalty += float(error_penalty)

    if "delete" in (tool_name or "").lower():
        penalty += 0.05

    return min(float(max_penalty), penalty)
