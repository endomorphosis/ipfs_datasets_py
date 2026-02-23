"""Dispatch pipeline for MCP++ tool invocations.

Includes both a legacy stage-based pipeline and a newer MCP++ integrated
pipeline with compliance, risk, delegation, and policy evaluation.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from .cid_artifacts import DecisionObject, ReceiptObject, EventNode, artifact_cid

logger = logging.getLogger(__name__)


@dataclass
class PipelineIntent:
    """Unified intent representation for the dispatch pipeline."""

    tool_name: str
    actor: str = ""
    params: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        payload = json.dumps(
            {"tool": self.tool_name, "actor": self.actor, "params": self.params},
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        digest = hashlib.sha256(payload).hexdigest()
        self.intent_cid: str = f"bafy-mock-intent-{digest[:20]}"

    @property
    def tool(self) -> str:
        return self.tool_name

    def get(self, field_name: str, default: Any = None) -> Any:
        return getattr(self, field_name, default)


@dataclass
class PipelineStage:
    """Legacy stage definition with optional enum-like constants."""

    name: str
    handler: Optional[Callable[[Dict[str, Any]], Dict[str, Any]]] = None
    enabled: bool = True
    fail_open: bool = True

    @property
    def value(self) -> str:
        return self.name

    def run(self, intent: Dict[str, Any]) -> Dict[str, Any]:
        if self.handler is None:
            raise ValueError(f"Stage '{self.name}' has no handler")
        try:
            result = self.handler(intent)
            if not isinstance(result, dict):
                result = {"allowed": bool(result)}
            if "allowed" not in result:
                result["allowed"] = True
            return result
        except Exception as exc:
            logger.warning("Stage %s raised %s: %s", self.name, type(exc).__name__, exc)
            return {
                "allowed": self.fail_open,
                "error": str(exc),
                "stage": self.name,
            }


PipelineStage.COMPLIANCE = PipelineStage("compliance")
PipelineStage.RISK = PipelineStage("risk")
PipelineStage.DELEGATION = PipelineStage("delegation")
PipelineStage.POLICY = PipelineStage("policy")
PipelineStage.NL_UCAN_GATE = PipelineStage("nl_ucan_gate")
PipelineStage.PASS = PipelineStage("pass")


@dataclass
class StageOutcome:
    """Result of a single pipeline stage."""

    stage: PipelineStage
    passed: bool
    reason: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class StageMetric:
    """Per-stage timing and skip information."""

    stage_name: str
    skipped: bool = False
    duration_ms: float = 0.0
    allowed: Optional[bool] = None
    reason: str = ""


@dataclass
class PipelineResult:
    """Aggregated result across all pipeline stages."""

    allowed: bool
    stage_outcomes: List[StageOutcome] = field(default_factory=list)
    blocking_stage: Optional[PipelineStage] = None
    intent: Optional[PipelineIntent] = None
    decision: Optional[DecisionObject] = None
    stages_executed: List[str] = field(default_factory=list)
    stages_skipped: List[str] = field(default_factory=list)
    denied_by: Optional[str] = None
    metrics: List[StageMetric] = field(default_factory=list)
    extra: Dict[str, Any] = field(default_factory=dict)

    @property
    def verdict(self) -> str:
        return "allow" if self.allowed else "deny"

    @property
    def total_stages(self) -> int:
        return len(self.stages_executed) + len(self.stages_skipped)

    def to_dict(self) -> Dict[str, Any]:
        if self.stage_outcomes:
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
        return {
            "allowed": self.allowed,
            "stages_executed": list(self.stages_executed),
            "stages_skipped": list(self.stages_skipped),
            "denied_by": self.denied_by,
        }


class PipelineMetricsRecorder:
    """Collects aggregate stage metrics across multiple DispatchPipeline runs."""

    def __init__(self, namespace: str = "mcp_pipeline", audit_log: Optional[Any] = None) -> None:
        self.namespace = namespace
        self._audit_log = audit_log
        self._stage_durations: Dict[str, List[float]] = {}
        self._stage_executions: Dict[str, int] = {}
        self._stage_skips: Dict[str, int] = {}
        self._stage_denials: Dict[str, int] = {}
        self._total_runs: int = 0
        self._total_allowed: int = 0
        self._total_denied: int = 0

    def record_stage(
        self,
        stage_name: str,
        *,
        skipped: bool,
        duration_ms: float = 0.0,
        allowed: Optional[bool] = None,
    ) -> None:
        if skipped:
            self._stage_skips[stage_name] = self._stage_skips.get(stage_name, 0) + 1
            return
        self._stage_executions[stage_name] = self._stage_executions.get(stage_name, 0) + 1
        self._stage_durations.setdefault(stage_name, []).append(duration_ms)
        if allowed is False:
            self._stage_denials[stage_name] = self._stage_denials.get(stage_name, 0) + 1

    def record_run(self, *, allowed: bool) -> None:
        self._total_runs += 1
        if allowed:
            self._total_allowed += 1
        else:
            self._total_denied += 1
        if self._audit_log is not None:
            try:
                decision_str = "allow" if allowed else "deny"
                self._audit_log.record(
                    policy_cid=f"pipeline:{self.namespace}:run",
                    intent_cid=f"run:{self._total_runs}",
                    decision=decision_str,
                    tool="pipeline",
                    actor="pipeline",
                )
            except (TypeError, AttributeError, ValueError) as exc:
                logger.warning(
                    "PipelineMetricsRecorder audit record failed (namespace=%s, run=%s): %s",
                    self.namespace,
                    self._total_runs,
                    exc,
                )

    def get_metrics(self) -> Dict[str, Any]:
        avg_durations: Dict[str, float] = {}
        for stage, times in self._stage_durations.items():
            avg_durations[stage] = sum(times) / len(times) if times else 0.0
        return {
            "namespace": self.namespace,
            "total_runs": self._total_runs,
            "total_allowed": self._total_allowed,
            "total_denied": self._total_denied,
            "stage_executions": dict(self._stage_executions),
            "stage_skips": dict(self._stage_skips),
            "stage_denials": dict(self._stage_denials),
            "avg_stage_duration_ms": avg_durations,
        }

    def reset(self) -> None:
        self._stage_durations.clear()
        self._stage_executions.clear()
        self._stage_skips.clear()
        self._stage_denials.clear()
        self._total_runs = 0
        self._total_allowed = 0
        self._total_denied = 0

    def __repr__(self) -> str:
        return f"PipelineMetricsRecorder(namespace={self.namespace!r}, total_runs={self._total_runs})"


@dataclass
class PipelineConfig:
    """Configuration controlling which pipeline stages are enabled."""

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


class DispatchPipeline:
    """Composable MCP++ pre-dispatch pipeline with legacy support."""

    def __init__(
        self,
        stages: Optional[List[PipelineStage]] = None,
        metrics_recorder: Optional[PipelineMetricsRecorder] = None,
        *,
        short_circuit: bool = True,
        audit_log: Optional[Any] = None,
        config: PipelineConfig | None = None,
    ) -> None:
        self._legacy_mode = stages is not None
        if self._legacy_mode:
            self._stages: List[PipelineStage] = list(stages or [])
            self._recorder = metrics_recorder or PipelineMetricsRecorder()
            self.short_circuit = short_circuit
            self._audit_log = audit_log
            self.config = None
            self._event_dag = None
        else:
            self.config = config or PipelineConfig()
            self._event_dag: Any = None
            self._stages = []
            self._recorder = metrics_recorder
            self.short_circuit = short_circuit
            self._audit_log = audit_log

    def attach_event_dag(self, dag: Any) -> None:
        self._event_dag = dag

    def add_stage(self, stage: PipelineStage) -> None:
        if not self._legacy_mode:
            raise RuntimeError("add_stage is only available in legacy mode")
        self._stages.append(stage)

    def skip_stage(self, name: str) -> bool:
        if not self._legacy_mode:
            return False
        for s in self._stages:
            if s.name == name:
                s.enabled = False
                return True
        return False

    def enable_stage(self, name: str) -> bool:
        if not self._legacy_mode:
            return False
        for s in self._stages:
            if s.name == name:
                s.enabled = True
                return True
        return False

    def get_stage(self, name: str) -> Optional[PipelineStage]:
        if not self._legacy_mode:
            return None
        for s in self._stages:
            if s.name == name:
                return s
        return None

    @property
    def stage_names(self) -> List[str]:
        return [s.name for s in self._stages]

    def run(self, intent: Dict[str, Any] | PipelineIntent) -> PipelineResult:
        if self._legacy_mode:
            return self._run_legacy(intent if isinstance(intent, dict) else intent.__dict__)
        return self.check(intent)

    def _run_legacy(self, intent: Dict[str, Any]) -> PipelineResult:
        executed: List[str] = []
        skipped: List[str] = []
        metrics_list: List[StageMetric] = []
        denied_by: Optional[str] = None
        final_allowed = True

        for stage in self._stages:
            if not stage.enabled:
                skipped.append(stage.name)
                m = StageMetric(stage_name=stage.name, skipped=True)
                metrics_list.append(m)
                self._recorder.record_stage(stage.name, skipped=True)
                continue

            t0 = time.monotonic()
            result = stage.run(intent)
            duration_ms = (time.monotonic() - t0) * 1000.0
            allowed = bool(result.get("allowed", True))

            m = StageMetric(
                stage_name=stage.name,
                skipped=False,
                duration_ms=duration_ms,
                allowed=allowed,
                reason=result.get("reason", ""),
            )
            metrics_list.append(m)
            self._recorder.record_stage(
                stage.name,
                skipped=False,
                duration_ms=duration_ms,
                allowed=allowed,
            )
            executed.append(stage.name)

            if self._audit_log is not None:
                try:
                    decision_str = "allow" if allowed else "deny"
                    tool = intent.get("tool", stage.name)
                    actor = intent.get("actor", "unknown")
                    self._audit_log.record(
                        policy_cid=f"pipeline:{stage.name}",
                        intent_cid="pipeline_intent",
                        decision=decision_str,
                        tool=tool,
                        actor=actor,
                    )
                except (TypeError, AttributeError, ValueError) as exc:
                    logger.warning(
                        "DispatchPipeline audit record failed for stage %s: %s",
                        stage.name,
                        exc,
                    )

            if not allowed:
                final_allowed = False
                denied_by = stage.name
                if self.short_circuit:
                    remaining = self._stages[self._stages.index(stage) + 1 :]
                    for rs in remaining:
                        if rs.enabled:
                            skipped.append(rs.name)
                    break

        self._recorder.record_run(allowed=final_allowed)

        return PipelineResult(
            allowed=final_allowed,
            stages_executed=executed,
            stages_skipped=skipped,
            denied_by=denied_by,
            metrics=metrics_list,
        )

    def check(self, intent: PipelineIntent | Dict[str, Any]) -> PipelineResult:
        if isinstance(intent, dict):
            intent = PipelineIntent(
                tool_name=intent.get("tool_name") or intent.get("tool", ""),
                actor=intent.get("actor", ""),
                params=intent.get("params", {}),
            )
        cfg = self.config or PipelineConfig()
        stages: List[StageOutcome] = []

        if cfg.enable_compliance:
            outcome = self._run_compliance(intent, cfg)
            stages.append(outcome)
            if not outcome.passed:
                return self._build_result(False, stages, outcome.stage, intent)

        if cfg.enable_risk:
            outcome = self._run_risk(intent, cfg)
            stages.append(outcome)
            if not outcome.passed:
                return self._build_result(False, stages, outcome.stage, intent)

        if cfg.enable_delegation:
            outcome = self._run_delegation(intent, cfg)
            stages.append(outcome)
            if not outcome.passed:
                return self._build_result(False, stages, outcome.stage, intent)

        if cfg.enable_policy:
            outcome = self._run_policy(intent, cfg)
            stages.append(outcome)
            if not outcome.passed:
                return self._build_result(False, stages, outcome.stage, intent)

        if cfg.enable_nl_ucan_gate:
            outcome = self._run_nl_ucan_gate(intent, cfg)
            stages.append(outcome)
            if not outcome.passed:
                return self._build_result(False, stages, outcome.stage, intent)

        return self._build_result(True, stages, None, intent)

    def _run_compliance(self, intent: PipelineIntent, cfg: PipelineConfig) -> StageOutcome:
        try:
            from .compliance_checker import make_default_compliance_checker

            checker = cfg.compliance_checker or make_default_compliance_checker()
            report = checker.check(intent.__dict__)
            allowed = report.summary == "pass"
            return StageOutcome(
                stage=PipelineStage.COMPLIANCE,
                passed=allowed,
                reason=f"compliance summary: {report.summary}",
                metadata={"summary": report.summary},
            )
        except Exception as exc:
            return StageOutcome(
                stage=PipelineStage.COMPLIANCE,
                passed=True,
                reason=f"compliance unavailable ({exc}), skipping",
            )

    def _run_risk(self, intent: PipelineIntent, cfg: PipelineConfig) -> StageOutcome:
        try:
            from .risk_scorer import RiskScorer

            scorer = cfg.risk_scorer or RiskScorer(cfg.risk_policy)
            score = scorer.score_intent(
                tool=intent.tool_name,
                actor=intent.actor,
                params=intent.params,
            )
            allowed = getattr(score, "is_acceptable", True)
            return StageOutcome(
                stage=PipelineStage.RISK,
                passed=allowed,
                reason=f"risk score {score.score:.2f} ({score.level})",
                metadata=getattr(score, "to_dict", lambda: {})(),
            )
        except Exception as exc:
            return StageOutcome(
                stage=PipelineStage.RISK,
                passed=True,
                reason=f"risk_scorer unavailable ({exc}), skipping",
            )

    def _run_delegation(self, intent: PipelineIntent, cfg: PipelineConfig) -> StageOutcome:
        try:
            from .ucan_delegation import DelegationEvaluator

            evaluator = cfg.delegation_evaluator or DelegationEvaluator()
            actor = intent.actor or "anonymous"
            leaf_cid = cfg.delegation_leaf_cid or ""
            ok, reason = evaluator.can_invoke(
                leaf_cid=leaf_cid,
                resource=intent.tool_name,
                ability=intent.tool_name,
                actor=actor,
            )
            return StageOutcome(
                stage=PipelineStage.DELEGATION,
                passed=bool(ok),
                reason=str(reason),
            )
        except ImportError as exc:
            return StageOutcome(
                stage=PipelineStage.DELEGATION,
                passed=True,
                reason=f"ucan_delegation unavailable ({exc}), skipping",
            )

    def _run_policy(self, intent: PipelineIntent, cfg: PipelineConfig) -> StageOutcome:
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

    def _run_nl_ucan_gate(self, intent: PipelineIntent, cfg: PipelineConfig) -> StageOutcome:
        try:
            from .nl_ucan_policy import UCANPolicyGate

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

    def _build_result(
        self,
        allowed: bool,
        stages: List[StageOutcome],
        blocking_stage: Optional[PipelineStage],
        intent: PipelineIntent,
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


def _allow_all(intent: Dict[str, Any]) -> Dict[str, Any]:
    return {"allowed": True, "reason": "pass-through"}


def make_default_pipeline(
    metrics_recorder: Optional[PipelineMetricsRecorder] = None,
) -> DispatchPipeline:
    stages = [
        PipelineStage(
            name="tool_name_check",
            handler=lambda intent: {
                "allowed": bool(intent.get("tool")),
                "reason": "tool name present" if intent.get("tool") else "missing tool",
            },
        ),
        PipelineStage(
            name="actor_present_check",
            handler=lambda intent: {"allowed": True, "reason": "actor check pass-through"},
        ),
    ]
    return DispatchPipeline(stages=stages, metrics_recorder=metrics_recorder)


def make_full_pipeline(
    metrics_recorder: Optional[PipelineMetricsRecorder] = None,
) -> DispatchPipeline:
    stage_names = [
        "compliance",
        "risk",
        "delegation",
        "policy",
        "nl_ucan_gate",
    ]
    stages = [PipelineStage(name=n, handler=_allow_all) for n in stage_names]
    return DispatchPipeline(stages=stages, metrics_recorder=metrics_recorder)


def make_delegation_stage(manager: Any) -> PipelineStage:
    def _handler(intent: Dict[str, Any]) -> Dict[str, Any]:
        actor = intent.get("actor", "")
        tool = intent.get("tool", "")
        leaf_cid = intent.get("leaf_cid", "")
        ok, reason = manager.can_invoke(leaf_cid, tool, actor)
        return {"allowed": bool(ok), "reason": str(reason)}

    return PipelineStage(name="delegation", handler=_handler)
