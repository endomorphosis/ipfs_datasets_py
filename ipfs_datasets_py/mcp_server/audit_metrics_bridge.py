"""Audit→Metrics Bridge — BG117 (Profile H: observability).

Connects :class:`~policy_audit_log.PolicyAuditLog` to
:class:`~prometheus_exporter.PrometheusExporter` so every policy decision is
automatically surfaced as a Prometheus metric.

Usage::

    from ipfs_datasets_py.mcp_server.audit_metrics_bridge import (
        AuditMetricsBridge, connect_audit_to_prometheus,
    )
    from ipfs_datasets_py.mcp_server.policy_audit_log import PolicyAuditLog
    from ipfs_datasets_py.mcp_server.prometheus_exporter import PrometheusExporter

    audit = PolicyAuditLog()
    exporter = PrometheusExporter()
    bridge = AuditMetricsBridge(audit, exporter)
    bridge.attach()          # wire sink
    bridge.detach()          # remove sink
    connect_audit_to_prometheus(audit, exporter)   # shorthand
"""
from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


class AuditMetricsBridge:
    """Connects a :class:`~policy_audit_log.PolicyAuditLog` to a
    :class:`~prometheus_exporter.PrometheusExporter`.

    When attached, every call to :meth:`~policy_audit_log.PolicyAuditLog.record`
    or :meth:`~policy_audit_log.PolicyAuditLog.record_decision` triggers
    :meth:`~prometheus_exporter.PrometheusExporter.record_tool_call` on the
    exporter with ``category="policy"`` and ``status="allowed"`` /
    ``"denied"``.

    Parameters
    ----------
    audit_log:
        The :class:`~policy_audit_log.PolicyAuditLog` to listen to.
    exporter:
        The :class:`~prometheus_exporter.PrometheusExporter` to forward
        metrics to.
    category:
        Prometheus ``category`` label value (default ``"policy"``).
    """

    def __init__(
        self,
        audit_log: Any,
        exporter: Any,
        *,
        category: str = "policy",
    ) -> None:
        self._audit = audit_log
        self._exporter = exporter
        self._category = category
        self._attached = False
        self._recorded: int = 0

    # ------------------------------------------------------------------
    # Sink (called by PolicyAuditLog on every record())
    # ------------------------------------------------------------------

    def _sink(self, entry: Any) -> None:  # entry: AuditEntry
        try:
            decision = getattr(entry, "decision", "unknown")
            tool = getattr(entry, "tool", None) or "unknown"
            status = "allowed" if decision in ("allow", "allow_with_obligations") else "denied"
            self._exporter.record_tool_call(
                category=self._category,
                tool=tool,
                status=status,
                latency_seconds=0.0,
            )
            self._recorded += 1
        except Exception as exc:  # pragma: no cover
            logger.warning("AuditMetricsBridge sink error: %s", exc)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def attach(self) -> None:
        """Wire ``_sink`` into the audit log.

        The audit log accepts exactly one sink in its constructor.  This
        method swaps the existing ``_sink`` attribute on the log so that
        subsequent records are forwarded to the exporter.
        """
        if self._attached:
            return
        # PolicyAuditLog stores its sink in `_sink`
        self._audit._sink = self._sink
        self._attached = True

    def detach(self) -> None:
        """Remove ``_sink`` from the audit log (sets it to ``None``)."""
        if not self._attached:
            return
        self._audit._sink = None
        self._attached = False

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    @property
    def is_attached(self) -> bool:
        """``True`` if the bridge is currently attached."""
        return self._attached

    @property
    def forwarded_count(self) -> int:
        """Total number of audit entries forwarded to the exporter."""
        return self._recorded

    def get_info(self) -> dict:
        """Return metadata about this bridge instance."""
        return {
            "attached": self._attached,
            "category": self._category,
            "forwarded_count": self._recorded,
        }

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"AuditMetricsBridge(attached={self._attached}, "
            f"forwarded={self._recorded})"
        )


# ---------------------------------------------------------------------------
# Module-level convenience
# ---------------------------------------------------------------------------


def connect_audit_to_prometheus(
    audit_log: Any,
    exporter: Any,
    *,
    category: str = "policy",
) -> AuditMetricsBridge:
    """Attach a new :class:`AuditMetricsBridge` and return it.

    Parameters
    ----------
    audit_log:
        A :class:`~policy_audit_log.PolicyAuditLog` instance.
    exporter:
        A :class:`~prometheus_exporter.PrometheusExporter` instance.
    category:
        Prometheus ``category`` label (default ``"policy"``).

    Returns
    -------
    AuditMetricsBridge
        The newly attached bridge.
    """
    bridge = AuditMetricsBridge(audit_log, exporter, category=category)
    bridge.attach()
    return bridge
