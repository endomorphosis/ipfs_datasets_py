"""Dispatch Pipeline — sequential stage execution with metrics (Profile E §4).

The :class:`DispatchPipeline` executes a sequence of named stages against a
single intent dict.  Each stage can:

* **Allow** the intent (return ``{"allowed": True, ...}``)
* **Deny** the intent (return ``{"allowed": False, ...}``)
* **Skip** itself by setting ``enabled = False``

Metrics are collected by :class:`PipelineMetricsRecorder` and are accessible
via :meth:`DispatchPipeline.get_metrics`.

Usage::

    from ipfs_datasets_py.mcp_server.dispatch_pipeline import (
        DispatchPipeline, PipelineStage, make_default_pipeline,
    )

    pipeline = make_default_pipeline()
    result = pipeline.run({"tool": "read", "actor": "alice", "params": {}})
    print(result.allowed, result.stages_executed)
"""
from __future__ import annotations

import time
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


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
    """Result produced by :meth:`DispatchPipeline.run`.

    Attributes
    ----------
    allowed:
        Whether the intent was ultimately allowed.
    stages_executed:
        Names of stages that actually ran (non-skipped).
    stages_skipped:
        Names of stages that were skipped.
    denied_by:
        Name of the stage that returned ``allowed=False``, if any.
    metrics:
        Per-stage :class:`StageMetric` list.
    """

    allowed: bool
    stages_executed: List[str] = field(default_factory=list)
    stages_skipped: List[str] = field(default_factory=list)
    denied_by: Optional[str] = None
    metrics: List[StageMetric] = field(default_factory=list)
    extra: Dict[str, Any] = field(default_factory=dict)

    @property
    def total_stages(self) -> int:
        return len(self.stages_executed) + len(self.stages_skipped)


# ---------------------------------------------------------------------------
# PipelineMetricsRecorder
# ---------------------------------------------------------------------------


class PipelineMetricsRecorder:
    """Collects aggregate stage metrics across multiple :meth:`DispatchPipeline.run` calls.

    Parameters
    ----------
    namespace:
        Optional label prefix for all recorded metric names.
    audit_log:
        CE141: Optional :class:`~policy_audit_log.PolicyAuditLog` instance.
        When provided, :meth:`record_run` writes a summary audit entry for
        every completed pipeline run.
    """

    def __init__(
        self,
        namespace: str = "mcp_pipeline",
        audit_log: Optional[Any] = None,  # CE141
    ) -> None:
        self.namespace = namespace
        self._audit_log = audit_log  # CE141
        self._stage_durations: Dict[str, List[float]] = {}
        self._stage_executions: Dict[str, int] = {}
        self._stage_skips: Dict[str, int] = {}
        self._stage_denials: Dict[str, int] = {}
        self._total_runs: int = 0
        self._total_allowed: int = 0
        self._total_denied: int = 0

    # ------------------------------------------------------------------
    # Recording
    # ------------------------------------------------------------------

    def record_stage(
        self,
        stage_name: str,
        *,
        skipped: bool,
        duration_ms: float = 0.0,
        allowed: Optional[bool] = None,
    ) -> None:
        """Record the outcome of a single stage execution."""
        if skipped:
            self._stage_skips[stage_name] = self._stage_skips.get(stage_name, 0) + 1
            return
        self._stage_executions[stage_name] = (
            self._stage_executions.get(stage_name, 0) + 1
        )
        self._stage_durations.setdefault(stage_name, []).append(duration_ms)
        if allowed is False:
            self._stage_denials[stage_name] = (
                self._stage_denials.get(stage_name, 0) + 1
            )

    def record_run(self, *, allowed: bool) -> None:
        """Record the final allowed/denied outcome of a complete pipeline run.

        CE141: When *audit_log* is set, also writes a summary audit entry.
        """
        self._total_runs += 1
        if allowed:
            self._total_allowed += 1
        else:
            self._total_denied += 1

        # CE141 — write audit entry for every completed pipeline run
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
                    self.namespace, self._total_runs, exc,
                )

    # ------------------------------------------------------------------
    # Metrics retrieval
    # ------------------------------------------------------------------

    def get_metrics(self) -> Dict[str, Any]:
        """Return a snapshot of all collected metrics."""
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
        """Reset all counters."""
        self._stage_durations.clear()
        self._stage_executions.clear()
        self._stage_skips.clear()
        self._stage_denials.clear()
        self._total_runs = 0
        self._total_allowed = 0
        self._total_denied = 0

    def __repr__(self) -> str:
        return (
            f"PipelineMetricsRecorder(namespace={self.namespace!r}, "
            f"total_runs={self._total_runs})"
        )


# ---------------------------------------------------------------------------
# PipelineStage
# ---------------------------------------------------------------------------


@dataclass
class PipelineStage:
    """A single named stage in a :class:`DispatchPipeline`.

    Parameters
    ----------
    name:
        Unique stage identifier.
    handler:
        Callable ``(intent: dict) -> dict`` that must return a dict with at
        least an ``allowed`` key.
    enabled:
        Whether this stage runs.  Can be toggled at runtime via
        :meth:`DispatchPipeline.skip_stage` / :meth:`DispatchPipeline.enable_stage`.
    fail_open:
        If *True* and the handler raises an exception, the stage is treated as
        **allowed** instead of **denied**.
    """

    name: str
    handler: Callable[[Dict[str, Any]], Dict[str, Any]]
    enabled: bool = True
    fail_open: bool = True

    def run(self, intent: Dict[str, Any]) -> Dict[str, Any]:
        """Execute the handler and return its result dict."""
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


# ---------------------------------------------------------------------------
# DispatchPipeline
# ---------------------------------------------------------------------------


class DispatchPipeline:
    """Sequential dispatch pipeline with per-stage metrics and skip control.

    Parameters
    ----------
    stages:
        Ordered list of :class:`PipelineStage` objects.
    metrics_recorder:
        Optional :class:`PipelineMetricsRecorder` for collecting aggregate metrics.
        If *None*, a default recorder is created.
    short_circuit:
        If *True* (default), the pipeline stops as soon as a stage returns
        ``allowed=False``.
    audit_log:
        CA137: Optional :class:`~policy_audit_log.PolicyAuditLog` instance.
        When provided, each stage result is recorded to the audit log.
    """

    def __init__(
        self,
        stages: Optional[List[PipelineStage]] = None,
        metrics_recorder: Optional[PipelineMetricsRecorder] = None,
        *,
        short_circuit: bool = True,
        audit_log: Optional[Any] = None,  # CA137
    ) -> None:
        self._stages: List[PipelineStage] = list(stages or [])
        self._recorder = metrics_recorder or PipelineMetricsRecorder()
        self.short_circuit = short_circuit
        self._audit_log = audit_log  # CA137

    # ------------------------------------------------------------------
    # Stage management
    # ------------------------------------------------------------------

    def add_stage(self, stage: PipelineStage) -> None:
        """Append a stage to the pipeline."""
        self._stages.append(stage)

    def skip_stage(self, name: str) -> bool:
        """Disable a stage by name.  Returns *True* if the stage was found."""
        for s in self._stages:
            if s.name == name:
                s.enabled = False
                return True
        return False

    def enable_stage(self, name: str) -> bool:
        """Enable a previously-disabled stage.  Returns *True* if found."""
        for s in self._stages:
            if s.name == name:
                s.enabled = True
                return True
        return False

    def get_stage(self, name: str) -> Optional[PipelineStage]:
        """Return the stage with *name*, or *None*."""
        for s in self._stages:
            if s.name == name:
                return s
        return None

    @property
    def stage_names(self) -> List[str]:
        """Ordered list of all stage names (enabled and disabled)."""
        return [s.name for s in self._stages]

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    def run(self, intent: Dict[str, Any]) -> PipelineResult:
        """Execute all enabled stages against *intent*.

        Parameters
        ----------
        intent:
            Dict with at minimum ``tool`` and optionally ``actor``, ``params``.

        Returns
        -------
        :class:`PipelineResult`
        """
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

            # CA137 — record stage result to audit log
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
                    logger.warning("DispatchPipeline audit record failed for stage %s: %s", stage.name, exc)

            if not allowed:
                final_allowed = False
                denied_by = stage.name
                if self.short_circuit:
                    # Mark remaining enabled stages as skipped
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

    def get_metrics(self) -> Dict[str, Any]:
        """Delegate to the embedded :class:`PipelineMetricsRecorder`."""
        return self._recorder.get_metrics()

    def __repr__(self) -> str:
        return (
            f"DispatchPipeline(stages={self.stage_names!r}, "
            f"short_circuit={self.short_circuit})"
        )


# ---------------------------------------------------------------------------
# Factory helpers
# ---------------------------------------------------------------------------


def _allow_all(intent: Dict[str, Any]) -> Dict[str, Any]:
    """Trivial pass-through stage handler."""
    return {"allowed": True, "reason": "pass-through"}


def make_default_pipeline(
    metrics_recorder: Optional[PipelineMetricsRecorder] = None,
) -> DispatchPipeline:
    """Create a two-stage pipeline (tool-name + actor-present) with no hard deps.

    Both stages are trivially pass-through so the pipeline always allows by default.
    Callers can replace handlers via :meth:`DispatchPipeline.get_stage`.
    """
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
    """Create a five-stage pipeline matching the MCP++ Profile E §4 dispatch spec.

    Stage order: compliance → risk → delegation → policy → nl_ucan_gate.
    All stages default to pass-through; wire real handlers at startup.
    """
    stage_names = [
        "compliance",
        "risk",
        "delegation",
        "policy",
        "nl_ucan_gate",
    ]
    stages = [
        PipelineStage(name=n, handler=_allow_all)
        for n in stage_names
    ]
    return DispatchPipeline(stages=stages, metrics_recorder=metrics_recorder)


def make_delegation_stage(manager: Any) -> "PipelineStage":
    """BS129: Create a :class:`PipelineStage` backed by a :class:`~ucan_delegation.DelegationManager`.

    The stage checks whether the requesting actor (``intent["actor"]``) can invoke
    the requested tool (``intent["tool"]``) via the delegation chain identified by
    ``intent.get("leaf_cid", "default")``.

    Parameters
    ----------
    manager:
        A :class:`~ucan_delegation.DelegationManager` instance.

    Returns
    -------
    :class:`PipelineStage` with name ``"delegation"``.
    """
    def _delegation_handler(intent: Dict[str, Any]) -> Dict[str, Any]:
        actor = intent.get("actor", "")
        tool = intent.get("tool", "")
        leaf_cid = intent.get("leaf_cid", "default")
        try:
            allowed, reason = manager.can_invoke(
                actor, tool, "tools/invoke", leaf_cid=leaf_cid
            )
            return {"allowed": allowed, "reason": reason}
        except Exception as exc:
            return {"allowed": False, "reason": f"delegation error: {exc}"}

    return PipelineStage(name="delegation", handler=_delegation_handler)
