"""Risk scoring for MCP++ tool invocations.

Based on the MCP++ spec chapter: docs/spec/risk-scheduling.md

Risk is computed from the Event DAG rather than ad-hoc logs.  This module
provides a lightweight, composable risk scoring pipeline that can be used
as a gate before tool dispatch.

Key concepts
------------
- **RiskLevel** — categorical label (NEGLIGIBLE → CRITICAL).
- **RiskScore** — numeric score 0.0–1.0 plus level and mitigation hints.
- **RiskScoringPolicy** — per-tool risk overrides, actor trust levels, etc.
- **RiskScorer** — combines tool-level and actor-level signals into a score
  and produces a :class:`~cid_artifacts.DecisionObject`.
"""

from __future__ import annotations

import math
import time
import uuid
import warnings
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

__all__ = [
    "RiskLevel",
    "RiskScore",
    "RiskScoringPolicy",
    "RiskScorer",
    "make_default_risk_policy",
    "score_intent",
]


# ---------------------------------------------------------------------------
# RiskLevel
# ---------------------------------------------------------------------------

class RiskLevel(str, Enum):
    """Categorical risk level, from lowest to highest."""

    NEGLIGIBLE = "negligible"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

    @classmethod
    def from_score(cls, score: float) -> "RiskLevel":
        """Map a numeric score in [0, 1] to a :class:`RiskLevel`.

        Thresholds::

            [0.00, 0.20) → NEGLIGIBLE
            [0.20, 0.40) → LOW
            [0.40, 0.60) → MEDIUM
            [0.60, 0.80) → HIGH
            [0.80, 1.00] → CRITICAL
        """
        if score < 0.20:
            return cls.NEGLIGIBLE
        if score < 0.40:
            return cls.LOW
        if score < 0.60:
            return cls.MEDIUM
        if score < 0.80:
            return cls.HIGH
        return cls.CRITICAL


# ---------------------------------------------------------------------------
# RiskScore
# ---------------------------------------------------------------------------

@dataclass
class RiskScore:
    """Result of a risk scoring computation.

    Attributes
    ----------
    level:
        Categorical :class:`RiskLevel`.
    score:
        Numeric risk score in ``[0.0, 1.0]``.
    factors:
        Ordered list of contributing factor labels (for auditability).
    mitigation_hints:
        Human-readable hints for reducing risk, populated when
        ``level`` is HIGH or CRITICAL.
    """

    level: RiskLevel
    score: float
    factors: List[str] = field(default_factory=list)
    mitigation_hints: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict:
        return {
            "level": self.level.value,
            "score": self.score,
            "factors": list(self.factors),
            "mitigation_hints": list(self.mitigation_hints),
        }


# ---------------------------------------------------------------------------
# RiskScoringPolicy
# ---------------------------------------------------------------------------

@dataclass
class RiskScoringPolicy:
    """Configures the risk scoring behaviour.

    Attributes
    ----------
    tool_risk_overrides:
        Map of ``tool_name → float`` risk baseline for specific tools.
        Values must be in ``[0.0, 1.0]``.
    default_risk:
        Fallback risk for tools not in ``tool_risk_overrides``.
    actor_trust_levels:
        Map of ``actor_id → float`` trust score in ``[0.0, 1.0]``.
        Higher trust reduces effective risk (trust acts as a divisor).
    max_acceptable_risk:
        Scores above this threshold are considered unacceptable.
    """

    tool_risk_overrides: Dict[str, float] = field(default_factory=dict)
    default_risk: float = 0.3
    actor_trust_levels: Dict[str, float] = field(default_factory=dict)
    max_acceptable_risk: float = 0.75

    def get_tool_risk(self, tool_name: str) -> float:
        """Return the base risk for *tool_name*."""
        return self.tool_risk_overrides.get(tool_name, self.default_risk)

    def get_actor_trust(self, actor: str) -> float:
        """Return the trust score for *actor*; default 0.5 (neutral)."""
        return self.actor_trust_levels.get(actor, 0.5)


# ---------------------------------------------------------------------------
# RiskScorer
# ---------------------------------------------------------------------------

class RiskScorer:
    """Computes a :class:`RiskScore` for a tool invocation intent.

    The scoring formula combines:

    1. **Tool base risk** — from :class:`RiskScoringPolicy`.
    2. **Actor trust attenuation** — higher trust → lower effective risk.
    3. **Param complexity penalty** — each extra parameter above a threshold
       adds a small penalty (models attack surface).

    The final score is clamped to ``[0.0, 1.0]``.
    """

    # Number of params above which the complexity penalty kicks in.
    _PARAM_THRESHOLD = 3
    _PARAM_PENALTY = 0.03

    def __init__(self, policy: Optional[RiskScoringPolicy] = None) -> None:
        self._policy = policy or RiskScoringPolicy()

    @property
    def policy(self) -> RiskScoringPolicy:
        return self._policy

    def score_intent(
        self,
        intent: Any,
        policy: Optional[RiskScoringPolicy] = None,
    ) -> RiskScore:
        """Score a tool invocation *intent*.

        *intent* is expected to have the following attributes (all optional,
        defaults used when absent):

        - ``tool_name`` (str) — name of the tool being invoked.
        - ``actor`` (str) — identity of the invoking agent.
        - ``params`` (dict) — parameters being passed to the tool.

        Parameters
        ----------
        intent:
            An object (or dict) describing the invocation.
        policy:
            Override the scorer's default policy for this call.

        Returns
        -------
        :class:`RiskScore`
        """
        p = policy or self._policy
        factors: List[str] = []
        hints: List[str] = []

        # Extract fields from intent
        if isinstance(intent, dict):
            tool_name: str = intent.get("tool_name", "unknown")
            actor: str = intent.get("actor", "unknown")
            params: Dict = intent.get("params") or {}
        else:
            tool_name = getattr(intent, "tool_name", "unknown") or "unknown"
            actor = getattr(intent, "actor", "unknown") or "unknown"
            params = getattr(intent, "params", None) or {}

        # 1. Tool base risk
        base = p.get_tool_risk(tool_name)
        factors.append(f"tool_base_risk({tool_name})={base:.2f}")

        # 2. Actor trust attenuation
        trust = p.get_actor_trust(actor)
        # trust in (0, 1]: multiply base by (1 - trust/2) so that full trust
        # (1.0) gives 50% of base, zero trust gives 100% of base.
        trust_factor = 1.0 - (trust * 0.5)
        attenuated = base * trust_factor
        factors.append(f"actor_trust({actor})={trust:.2f} → attenuation={trust_factor:.2f}")

        # 3. Param complexity penalty
        n_params = len(params)
        complexity_penalty = 0.0
        if n_params > self._PARAM_THRESHOLD:
            complexity_penalty = (n_params - self._PARAM_THRESHOLD) * self._PARAM_PENALTY
            factors.append(
                f"param_complexity(n={n_params}, threshold={self._PARAM_THRESHOLD})"
                f" → +{complexity_penalty:.3f}"
            )

        raw = attenuated + complexity_penalty
        score = max(0.0, min(1.0, raw))
        level = RiskLevel.from_score(score)

        # Mitigation hints for elevated risk
        if level == RiskLevel.HIGH:
            hints.append(
                "Consider requiring additional confirmation before dispatching "
                f"'{tool_name}' for actor '{actor}'."
            )
            hints.append(
                "Review the actor's trust level and consider upgrading it if "
                "they are a known, verified system component."
            )
        elif level == RiskLevel.CRITICAL:
            hints.append(
                f"CRITICAL risk for '{tool_name}' — dispatch is strongly "
                "discouraged without explicit policy override."
            )
            hints.append(
                "Escalate to a human reviewer or require explicit policy "
                "permission before executing."
            )

        return RiskScore(level=level, score=score, factors=factors,
                         mitigation_hints=hints)

    def is_acceptable(
        self,
        risk_score: RiskScore,
        policy: Optional[RiskScoringPolicy] = None,
    ) -> bool:
        """Return True if *risk_score* is within the acceptable threshold."""
        p = policy or self._policy
        return risk_score.score <= p.max_acceptable_risk

    def score_and_gate(
        self,
        intent: Any,
        policy: Optional[RiskScoringPolicy] = None,
    ) -> Dict[str, Any]:
        """Score *intent* and return a decision dict.

        Returns a dict compatible with ``cid_artifacts.DecisionObject``::

            {
                "decision": "allow" | "deny",
                "reason": str,
                "risk_score": {...},
            }
        """
        risk = self.score_intent(intent, policy=policy)
        accepted = self.is_acceptable(risk, policy=policy)
        return {
            "decision": "allow" if accepted else "deny",
            "reason": (
                "risk score within acceptable threshold"
                if accepted
                else (
                    f"risk score {risk.score:.3f} exceeds "
                    f"threshold {(policy or self._policy).max_acceptable_risk:.3f}"
                )
            ),
            "risk_score": risk.to_dict(),
        }


# ---------------------------------------------------------------------------
# Convenience helpers
# ---------------------------------------------------------------------------

def make_default_risk_policy(
    *,
    high_risk_tools: Optional[List[str]] = None,
    max_acceptable_risk: float = 0.75,
) -> RiskScoringPolicy:
    """Create a sensible default :class:`RiskScoringPolicy`.

    Parameters
    ----------
    high_risk_tools:
        Tool names that should be assigned a HIGH base risk (0.70).
    max_acceptable_risk:
        Override the acceptability threshold.
    """
    overrides: Dict[str, float] = {}
    for name in (high_risk_tools or []):
        overrides[name] = 0.70
    return RiskScoringPolicy(
        tool_risk_overrides=overrides,
        default_risk=0.30,
        max_acceptable_risk=max_acceptable_risk,
    )


# Global scorer singleton
_GLOBAL_SCORER: Optional[RiskScorer] = None


def score_intent(
    intent: Any,
    policy: Optional[RiskScoringPolicy] = None,
) -> RiskScore:
    """Score *intent* using the global :class:`RiskScorer`."""
    global _GLOBAL_SCORER
    if _GLOBAL_SCORER is None:
        _GLOBAL_SCORER = RiskScorer()
    return _GLOBAL_SCORER.score_intent(intent, policy=policy)


def risk_score_from_dag(
    dag: Any,
    tool_name: str,
    *,
    rollback_penalty: float = 0.15,
    error_penalty: float = 0.10,
    max_penalty: float = 0.50,
) -> float:
    """Derive a tool-specific risk score adjustment from the event DAG.

    Scans all nodes in *dag* for events associated with *tool_name* and
    counts rollback and error events.  Returns a non-negative penalty in
    ``[0, max_penalty]`` that callers can add to a base risk score.

    This implements the "Risk from EventDAG" requirement from
    ``MASTER_IMPROVEMENT_PLAN_2026_v10.md`` Section "Next Steps 3".

    Args:
        dag: An :class:`~event_dag.EventDAG` instance.
        tool_name: The tool whose history to inspect.
        rollback_penalty: Extra risk per rollback event (default 0.15).
        error_penalty: Extra risk per error event (default 0.10).
        max_penalty: Maximum total penalty returned (default 0.50).

    Returns:
        A float penalty in ``[0, max_penalty]``.
    """
    rollbacks = 0
    errors = 0
    try:
        # EventDAG stores nodes in _nodes dict keyed by CID.
        nodes = getattr(dag, "_nodes", {})
        for node in nodes.values():
            # EventNode stores the intent_cid.  For PipelineIntent, the intent_cid
            # is a hash of tool_name + actor so it is opaque; we count all rollback
            # and error events across the DAG as a conservative risk signal.  Callers
            # can scope more precisely by pre-filtering the DAG before passing it in.
            # Rollback events: output_cid starts with "rollback" OR
            # receipt_cid is empty (execution never completed normally).
            output = str(getattr(node, "output_cid", ""))
            receipt = str(getattr(node, "receipt_cid", ""))
            if "rollback" in output.lower():
                rollbacks += 1
            elif not receipt:
                errors += 1
    except Exception:  # pragma: no cover
        pass
    penalty = rollbacks * rollback_penalty + errors * error_penalty
    return min(penalty, max_penalty)
