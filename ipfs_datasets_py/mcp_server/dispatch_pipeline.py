"""MCP++ Integrated Dispatch Pipeline.

This module wires together all MCP++ execution profiles into a single,
composable pre-dispatch pipeline:

1. **Compliance check** (:mod:`compliance_checker`) — structural/policy rule
   validation (tool name convention, actor, params, deny-list, rate-limit).
2. **Risk scoring** (:mod:`risk_scorer`) — compute a numeric risk score and
   gate dispatch if the risk is unacceptable.
3. **UCAN delegation check** (:mod:`ucan_delegation`) — verify the actor has a
   valid delegated capability for the requested tool.
4. **Policy evaluation** (:mod:`temporal_policy`) — evaluate temporal deontic
   policy (permissions, prohibitions, obligations).
5. **NL-UCAN gate** (:mod:`nl_ucan_policy`) — check the natural-language UCAN
   policy gate (if any policies are registered).
6. **Event DAG append** (:mod:`event_dag`) — append an :class:`EventNode` to
   the execution history after a successful check.
7. **Receipt creation** — create a :class:`ReceiptObject` after execution
   completes.

All stages are optional and individually configurable.  An unconfigured
pipeline passes everything through, preserving the "open by default" principle
from the MCP++ spec.

Usage
-----
::

    from ipfs_datasets_py.mcp_server.dispatch_pipeline import (
        DispatchPipeline,
        PipelineConfig,
        PipelineResult,
    )

    pipeline = DispatchPipeline()
    result = pipeline.check(intent)
    if result.allowed:
        # dispatch the tool ...
        receipt = pipeline.record_execution(intent, execution_result)
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from .cid_artifacts import DecisionObject, ReceiptObject, EventNode, artifact_cid


# ---------------------------------------------------------------------------
# Unified pipeline intent
# ---------------------------------------------------------------------------


@dataclass
class PipelineIntent:
    """Unified intent representation for the dispatch pipeline.

    Combines the field names used across all MCP++ modules:

    - ``tool_name`` / ``tool`` — both refer to the same value; ``tool`` is an
      alias used by :mod:`temporal_policy`.
    - ``actor`` — the requesting actor identifier.
    - ``params`` — tool invocation parameters (JSON-serialisable dict).
    - ``intent_cid`` — a content-addressed ID computed from the other fields.

    Parameters
    ----------
    tool_name:
        The name of the tool being invoked.
    actor:
        The identity of the requesting agent.
    params:
        Tool parameters as a dict.
    """

    tool_name: str
    actor: str = ""
    params: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # Compute a stable intent CID from tool+actor+params
        payload = json.dumps(
            {"tool": self.tool_name, "actor": self.actor, "params": self.params},
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        digest = hashlib.sha256(payload).hexdigest()
        self.intent_cid: str = f"bafy-mock-intent-{digest[:20]}"  # mock CID (not a real IPFS CID)

    @property
    def tool(self) -> str:
        """Alias for :attr:`tool_name` (used by :mod:`temporal_policy`)."""
        return self.tool_name

    def get(self, field_name: str, default: Any = None) -> Any:
        """Dict-style accessor for compatibility with :mod:`risk_scorer`."""
        return getattr(self, field_name, default)


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


class PipelineStage(Enum):
    """Named stages of the dispatch pipeline."""

    COMPLIANCE = "compliance"
    RISK = "risk"
    DELEGATION = "delegation"
    POLICY = "policy"
    NL_UCAN_GATE = "nl_ucan_gate"
    PASS = "pass"


@dataclass
class StageOutcome:
    """Result of a single pipeline stage.

    Parameters
    ----------
    stage:
        Which pipeline stage produced this outcome.
    passed:
        Whether the stage allowed execution to continue.
    reason:
        Human-readable explanation.
    metadata:
        Optional extra data from the stage.
    """

    stage: PipelineStage
    passed: bool
    reason: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class PipelineResult:
    """Aggregated result across all pipeline stages.

    Parameters
    ----------
    allowed:
        True iff *all* enabled stages passed.
    stage_outcomes:
        Per-stage results in evaluation order.
    blocking_stage:
        The first stage that blocked the request (or None if allowed).
    intent:
        The intent that was evaluated.
    decision:
        A :class:`~cid_artifacts.DecisionObject` summarising the final verdict.
    """

    allowed: bool
    stage_outcomes: list[StageOutcome]
    blocking_stage: PipelineStage | None
    intent: "PipelineIntent"
    decision: DecisionObject | None = None

    @property
    def verdict(self) -> str:
        """Return ``"allow"`` or ``"deny"``."""
        return "allow" if self.allowed else "deny"

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a plain dict."""
        return {
            "allowed": self.allowed,
            "verdict": self.verdict,
            "blocking_stage": self.blocking_stage.value if self.blocking_stage else None,
            "stages": [
                {
                    "stage": o.stage.value,
                    "passed": o.passed,
                    "reason": o.reason,
                    "metadata": o.metadata,
                }
                for o in self.stage_outcomes
            ],
        }


# ---------------------------------------------------------------------------
# Pipeline configuration
# ---------------------------------------------------------------------------


@dataclass
class PipelineConfig:
    """Configuration controlling which pipeline stages are enabled.

    All stages default to **disabled** (opt-in) so that an unconfigured
    pipeline passes every intent through without requiring any setup.

    Parameters
    ----------
    enable_compliance:
        Enable structural compliance checking.
    enable_risk:
        Enable risk scoring and gating.
    enable_delegation:
        Enable UCAN delegation chain validation.
    enable_policy:
        Enable temporal deontic policy evaluation.
    enable_nl_ucan_gate:
        Enable NL-UCAN policy gate.
    compliance_checker:
        A pre-configured :class:`~compliance_checker.ComplianceChecker`
        instance.  If ``None`` and *enable_compliance* is True a default
        checker is created on first use.
    risk_scorer:
        A pre-configured :class:`~risk_scorer.RiskScorer` instance.
    risk_policy:
        A :class:`~risk_scorer.RiskScoringPolicy` to use with the scorer.
    policy_evaluator:
        A :class:`~temporal_policy.PolicyEvaluator` instance.
    policy_object:
        The :class:`~temporal_policy.PolicyObject` to evaluate against.
    delegation_evaluator:
        A :class:`~ucan_delegation.DelegationEvaluator` instance.
    delegation_leaf_cid:
        The leaf delegation CID to use when checking ``can_invoke``.
    nl_ucan_gate:
        A :class:`~nl_ucan_policy.UCANPolicyGate` instance.
    """

    enable_compliance: bool = False
    enable_risk: bool = False
    enable_delegation: bool = False
    enable_policy: bool = False
    enable_nl_ucan_gate: bool = False

    compliance_checker: Any = None
    risk_scorer: Any = None
    risk_policy: Any = None
    policy_evaluator: Any = None
    policy_object: Any = None
    delegation_evaluator: Any = None
    delegation_leaf_cid: str | None = None
    nl_ucan_gate: Any = None


# ---------------------------------------------------------------------------
# Pipeline implementation
# ---------------------------------------------------------------------------


class DispatchPipeline:
    """Composable MCP++ pre-dispatch pipeline.

    Evaluates a sequence of MCP++ profile checks in order and returns a
    :class:`PipelineResult` summarising whether the invocation should proceed.

    Parameters
    ----------
    config:
        Pipeline configuration.  Defaults to a fully-disabled (pass-through)
        configuration.
    """

    def __init__(self, config: PipelineConfig | None = None) -> None:
        self.config = config or PipelineConfig()
        self._event_dag: Any = None  # lazily attached

    def attach_event_dag(self, dag: Any) -> None:
        """Attach an :class:`~event_dag.EventDAG` to record execution history.

        Parameters
        ----------
        dag:
            An initialised :class:`~event_dag.EventDAG` instance.
        """
        self._event_dag = dag

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def check(self, intent: "PipelineIntent") -> PipelineResult:
        """Run all enabled pipeline stages against *intent*.

        Stages are evaluated in order.  The pipeline short-circuits and
        returns a DENY result as soon as any stage blocks the intent.

        Parameters
        ----------
        intent:
            The :class:`~cid_artifacts.IntentObject` to evaluate.

        Returns
        -------
        PipelineResult
        """
        cfg = self.config
        stages: list[StageOutcome] = []

        # Stage 1: Compliance
        if cfg.enable_compliance:
            outcome = self._run_compliance(intent, cfg)
            stages.append(outcome)
            if not outcome.passed:
                return self._build_result(False, stages, PipelineStage.COMPLIANCE, intent)

        # Stage 2: Risk scoring
        if cfg.enable_risk:
            outcome = self._run_risk(intent, cfg)
            stages.append(outcome)
            if not outcome.passed:
                return self._build_result(False, stages, PipelineStage.RISK, intent)

        # Stage 3: UCAN delegation
        if cfg.enable_delegation:
            outcome = self._run_delegation(intent, cfg)
            stages.append(outcome)
            if not outcome.passed:
                return self._build_result(False, stages, PipelineStage.DELEGATION, intent)

        # Stage 4: Temporal deontic policy
        if cfg.enable_policy:
            outcome = self._run_policy(intent, cfg)
            stages.append(outcome)
            if not outcome.passed:
                return self._build_result(False, stages, PipelineStage.POLICY, intent)

        # Stage 5: NL-UCAN gate
        if cfg.enable_nl_ucan_gate:
            outcome = self._run_nl_ucan_gate(intent, cfg)
            stages.append(outcome)
            if not outcome.passed:
                return self._build_result(False, stages, PipelineStage.NL_UCAN_GATE, intent)

        # All enabled stages passed
        stages.append(StageOutcome(stage=PipelineStage.PASS, passed=True, reason="all stages passed"))
        return self._build_result(True, stages, None, intent)

    def record_execution(
        self,
        intent: "PipelineIntent",
        execution_result: Any,
        error: Exception | None = None,
    ) -> ReceiptObject:
        """Create a :class:`~cid_artifacts.ReceiptObject` after execution.

        If an event DAG is attached the receipt is wrapped in an
        :class:`~cid_artifacts.EventNode` and appended to the DAG.

        Parameters
        ----------
        intent:
            The original intent.
        execution_result:
            The result returned by the tool (any JSON-serialisable value).
        error:
            Any exception that occurred during execution (or None on success).

        Returns
        -------
        ReceiptObject
        """
        # Compute output CID from result
        output_data: dict[str, Any] = {}
        if error:
            output_data["error"] = str(error)
        elif isinstance(execution_result, dict):
            output_data = execution_result
        else:
            output_data["result"] = execution_result

        output_cid = artifact_cid(output_data)
        status = "error" if error else "success"

        receipt = ReceiptObject(
            intent_cid=intent.intent_cid,
            output_cid=output_cid,
            decision_cid=f"bafy-mock-pipeline-{status}",  # mock CID (not a real IPFS CID)
            correlation_id=intent.intent_cid,
        )

        if self._event_dag is not None:
            try:
                node = EventNode(
                    parents=[],  # no parent: genesis node for this execution
                    intent_cid=intent.intent_cid,
                    receipt_cid=receipt.receipt_cid,
                )
                self._event_dag.append(node)
            except Exception:
                pass  # DAG errors must not fail execution recording

        return receipt

    # ------------------------------------------------------------------
    # Private stage runners
    # ------------------------------------------------------------------

    def _run_compliance(self, intent: "PipelineIntent", cfg: PipelineConfig) -> StageOutcome:
        """Run compliance stage."""
        try:
            from .compliance_checker import make_default_compliance_checker, ComplianceStatus
            checker = cfg.compliance_checker or make_default_compliance_checker()
            report = checker.check_compliance(intent)
            non_compliant = [
                r for r in report.results
                if r.status == ComplianceStatus.NON_COMPLIANT
            ]
            if non_compliant:
                reasons = "; ".join(
                    v.message
                    for r in non_compliant
                    for v in r.violations
                )
                return StageOutcome(
                    stage=PipelineStage.COMPLIANCE,
                    passed=False,
                    reason=f"compliance violations: {reasons}",
                    metadata={"non_compliant_rules": [r.rule_id for r in non_compliant]},
                )
            return StageOutcome(stage=PipelineStage.COMPLIANCE, passed=True, reason="all rules pass")
        except ImportError as exc:
            return StageOutcome(
                stage=PipelineStage.COMPLIANCE,
                passed=True,
                reason=f"compliance_checker unavailable ({exc}), skipping",
            )

    def _run_risk(self, intent: "PipelineIntent", cfg: PipelineConfig) -> StageOutcome:
        """Run risk scoring stage."""
        try:
            from .risk_scorer import RiskScorer, make_default_risk_policy, RiskLevel
            scorer = cfg.risk_scorer or RiskScorer()
            policy = cfg.risk_policy or make_default_risk_policy()
            score = scorer.score_intent(intent, policy)
            acceptable = scorer.is_acceptable(score, policy)
            if not acceptable:
                return StageOutcome(
                    stage=PipelineStage.RISK,
                    passed=False,
                    reason=f"risk score {score.score:.3f} ({score.level.value}) exceeds max {policy.max_acceptable_risk}",
                    metadata={"score": score.score, "level": score.level.value, "factors": score.factors},
                )
            return StageOutcome(
                stage=PipelineStage.RISK,
                passed=True,
                reason=f"risk score {score.score:.3f} ({score.level.value}) acceptable",
                metadata={"score": score.score, "level": score.level.value},
            )
        except ImportError as exc:
            return StageOutcome(
                stage=PipelineStage.RISK,
                passed=True,
                reason=f"risk_scorer unavailable ({exc}), skipping",
            )

    def _run_delegation(self, intent: "PipelineIntent", cfg: PipelineConfig) -> StageOutcome:
        """Run UCAN delegation stage."""
        try:
            from .ucan_delegation import get_delegation_evaluator
            evaluator = cfg.delegation_evaluator or get_delegation_evaluator()
            leaf_cid = cfg.delegation_leaf_cid
            if leaf_cid is None:
                return StageOutcome(
                    stage=PipelineStage.DELEGATION,
                    passed=True,
                    reason="no delegation_leaf_cid configured, skipping chain check",
                )
            tool = intent.tool_name
            actor = intent.actor or ""
            can_result = evaluator.can_invoke(
                leaf_cid=leaf_cid, resource=tool, ability=tool, actor=actor
            )
            # can_invoke returns (bool, reason) tuple
            can = can_result[0] if isinstance(can_result, tuple) else bool(can_result)
            if not can:
                reason = can_result[1] if isinstance(can_result, tuple) else "denied"
                return StageOutcome(
                    stage=PipelineStage.DELEGATION,
                    passed=False,
                    reason=f"actor '{actor}' not authorized via UCAN chain (leaf={leaf_cid}, tool={tool}): {reason}",
                )
            return StageOutcome(
                stage=PipelineStage.DELEGATION,
                passed=True,
                reason=f"UCAN chain valid for actor='{actor}', tool='{tool}'",
            )
        except ImportError as exc:
            return StageOutcome(
                stage=PipelineStage.DELEGATION,
                passed=True,
                reason=f"ucan_delegation unavailable ({exc}), skipping",
            )

    def _run_policy(self, intent: "PipelineIntent", cfg: PipelineConfig) -> StageOutcome:
        """Run temporal deontic policy stage."""
        try:
            from .temporal_policy import PolicyEvaluator
            evaluator = cfg.policy_evaluator or PolicyEvaluator()
            policy_obj = cfg.policy_object
            if policy_obj is None:
                return StageOutcome(
                    stage=PipelineStage.POLICY,
                    passed=True,
                    reason="no policy configured, skipping",
                )
            decision = evaluator.evaluate(intent, policy_obj, actor=intent.actor or None)
            allowed = decision.decision in ("allow", "allow_with_obligations")
            return StageOutcome(
                stage=PipelineStage.POLICY,
                passed=allowed,
                reason=f"policy verdict: {decision.decision}",
                metadata={"verdict": decision.decision, "obligations": decision.obligations},
            )
        except ImportError as exc:
            return StageOutcome(
                stage=PipelineStage.POLICY,
                passed=True,
                reason=f"temporal_policy unavailable ({exc}), skipping",
            )

    def _run_nl_ucan_gate(self, intent: "PipelineIntent", cfg: PipelineConfig) -> StageOutcome:
        """Run NL-UCAN policy gate stage."""
        try:
            from .nl_ucan_policy import get_policy_registry, UCANPolicyGate
            gate = cfg.nl_ucan_gate or UCANPolicyGate()
            actor = intent.actor or "anonymous"
            decision = gate.evaluate(intent, actor=actor)
            allowed = decision.decision in ("allow", "allow_with_obligations")
            return StageOutcome(
                stage=PipelineStage.NL_UCAN_GATE,
                passed=allowed,
                reason=f"NL-UCAN gate verdict: {decision.decision}",
                metadata={"verdict": decision.decision},
            )
        except ImportError as exc:
            return StageOutcome(
                stage=PipelineStage.NL_UCAN_GATE,
                passed=True,
                reason=f"nl_ucan_policy unavailable ({exc}), skipping",
            )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_result(
        self,
        allowed: bool,
        stages: list[StageOutcome],
        blocking_stage: PipelineStage | None,
        intent: "PipelineIntent",
    ) -> PipelineResult:
        verdict = "allow" if allowed else "deny"
        decision = DecisionObject(
            intent_cid=intent.intent_cid,
            decision=verdict,
            policy_cid="pipeline",
            justification=f"pipeline verdict after {len(stages)} stage(s)",
            obligations=[],
        )
        return PipelineResult(
            allowed=allowed,
            stage_outcomes=stages,
            blocking_stage=blocking_stage,
            intent=intent,
            decision=decision,
        )


# ---------------------------------------------------------------------------
# Convenience factory
# ---------------------------------------------------------------------------


def make_default_pipeline() -> DispatchPipeline:
    """Create a default (fully pass-through) :class:`DispatchPipeline`.

    Returns
    -------
    DispatchPipeline
        A pipeline with all stages disabled.  No gates are applied until
        stages are enabled in :attr:`DispatchPipeline.config`.
    """
    return DispatchPipeline(config=PipelineConfig())


def make_full_pipeline(
    *,
    compliance_checker: Any = None,
    risk_scorer: Any = None,
    risk_policy: Any = None,
    policy_evaluator: Any = None,
    policy_object: Any = None,
    delegation_evaluator: Any = None,
    delegation_leaf_cid: str | None = None,
    nl_ucan_gate: Any = None,
) -> DispatchPipeline:
    """Create a :class:`DispatchPipeline` with all stages enabled.

    Parameters
    ----------
    compliance_checker:
        Optional pre-built compliance checker.
    risk_scorer:
        Optional pre-built risk scorer.
    risk_policy:
        Optional risk scoring policy.
    policy_evaluator:
        Optional temporal policy evaluator.
    policy_object:
        Optional policy object to evaluate against.
    delegation_evaluator:
        Optional UCAN delegation evaluator.
    delegation_leaf_cid:
        UCAN leaf CID to check.
    nl_ucan_gate:
        Optional NL-UCAN policy gate.

    Returns
    -------
    DispatchPipeline
        A pipeline with every stage enabled.
    """
    return DispatchPipeline(
        config=PipelineConfig(
            enable_compliance=True,
            enable_risk=True,
            enable_delegation=True,
            enable_policy=True,
            enable_nl_ucan_gate=True,
            compliance_checker=compliance_checker,
            risk_scorer=risk_scorer,
            risk_policy=risk_policy,
            policy_evaluator=policy_evaluator,
            policy_object=policy_object,
            delegation_evaluator=delegation_evaluator,
            delegation_leaf_cid=delegation_leaf_cid,
            nl_ucan_gate=nl_ucan_gate,
        )
    )
