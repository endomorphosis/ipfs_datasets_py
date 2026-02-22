"""Policy Audit Log — Phase 8 Observability.

Every call to :meth:`~ipfs_datasets_py.mcp_server.temporal_policy.PolicyEvaluator.evaluate`
can optionally be recorded in a structured audit trail that can be persisted to
disk, exported to a logging backend, or consumed by monitoring tools.

Design goals
------------
* Zero overhead when disabled (``enabled=False`` or global singleton not initialised).
* Thread-safe (``threading.Lock`` protects the in-memory buffer).
* Pluggable sinks: stdout, file, or custom callable.
* Lightweight — stdlib only, no hard external dependencies.

Usage::

    from ipfs_datasets_py.mcp_server.policy_audit_log import (
        PolicyAuditLog, get_audit_log,
    )

    log = get_audit_log()          # process-global singleton
    log.record(
        policy_cid="bafy...",
        intent_cid="bafy...",
        actor="alice",
        decision="allow",
        tool="read",
    )
    print(log.recent(n=5))
"""
from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


# ─── data types ──────────────────────────────────────────────────────────────


@dataclass
class AuditEntry:
    """A single audit log entry.

    Attributes
    ----------
    timestamp:
        Unix timestamp (``time.time()``) at which the decision was recorded.
    policy_cid:
        CID of the policy that was evaluated.
    intent_cid:
        CID of the intent that was evaluated.
    actor:
        Optional actor identifier.
    tool:
        Tool name from the intent (or ``"unknown"``).
    decision:
        One of ``"allow"``, ``"deny"``, or ``"allow_with_obligations"``.
    justification:
        Human-readable justification string from the :class:`DecisionObject`.
    obligations:
        List of obligation type strings (if any).
    extra:
        Any additional metadata supplied by the caller.
    """
    timestamp: float
    policy_cid: str
    intent_cid: str
    decision: str
    actor: Optional[str] = None
    tool: str = "unknown"
    justification: str = ""
    obligations: List[str] = field(default_factory=list)
    extra: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict."""
        return asdict(self)

    def to_json(self) -> str:
        """Return the entry serialised as a compact JSON string."""
        return json.dumps(self.to_dict(), separators=(",", ":"))


# ─── audit log ───────────────────────────────────────────────────────────────


class PolicyAuditLog:
    """In-memory (optionally file-backed) audit trail for policy evaluations.

    Parameters
    ----------
    enabled:
        Master switch.  When *False*, :meth:`record` is a no-op.
    max_entries:
        Maximum number of entries kept in the in-memory ring buffer before
        the oldest entries are dropped.  ``0`` means unlimited.
    log_path:
        Optional path to a JSONL file.  Each :meth:`record` call appends one
        JSON line.  The file is opened in append mode; existing content is
        preserved.
    sink:
        Optional callable ``(entry: AuditEntry) -> None`` called on every
        recorded entry (after the in-memory buffer and before file write).
        Useful for forwarding entries to Prometheus counters, Sentry, etc.
    """

    def __init__(
        self,
        *,
        enabled: bool = True,
        max_entries: int = 10_000,
        log_path: Optional[str] = None,
        sink: Optional[Callable[[AuditEntry], None]] = None,
    ) -> None:
        self._enabled = enabled
        self._max_entries = max_entries
        self._log_path = Path(log_path) if log_path else None
        self._sink = sink
        self._entries: List[AuditEntry] = []
        self._lock = threading.Lock()
        self._total_recorded: int = 0
        self._counters: Dict[str, int] = {"allow": 0, "deny": 0, "allow_with_obligations": 0}

    # ── public API ────────────────────────────────────────────────────────────

    @property
    def enabled(self) -> bool:
        return self._enabled

    @enabled.setter
    def enabled(self, value: bool) -> None:
        self._enabled = value

    def record(
        self,
        *,
        policy_cid: str,
        intent_cid: str,
        decision: str,
        actor: Optional[str] = None,
        tool: str = "unknown",
        justification: str = "",
        obligations: Optional[List[str]] = None,
        extra: Optional[Dict[str, Any]] = None,
        timestamp: Optional[float] = None,
    ) -> Optional[AuditEntry]:
        """Record a policy evaluation decision.

        Parameters
        ----------
        policy_cid, intent_cid, decision:
            Required fields.
        actor, tool, justification, obligations, extra:
            Optional metadata.
        timestamp:
            Override the entry timestamp (defaults to ``time.time()``).

        Returns
        -------
        AuditEntry or None
            The created entry, or *None* if the log is disabled.
        """
        if not self._enabled:
            return None

        entry = AuditEntry(
            timestamp=timestamp if timestamp is not None else time.time(),
            policy_cid=policy_cid,
            intent_cid=intent_cid,
            decision=decision,
            actor=actor,
            tool=tool,
            justification=justification,
            obligations=obligations or [],
            extra=extra or {},
        )

        with self._lock:
            # Ring buffer: evict oldest when full
            if self._max_entries > 0 and len(self._entries) >= self._max_entries:
                self._entries.pop(0)
            self._entries.append(entry)
            self._total_recorded += 1
            self._counters[decision] = self._counters.get(decision, 0) + 1

        # Sink (outside lock to avoid deadlock if sink re-enters)
        if self._sink is not None:
            try:
                self._sink(entry)
            except Exception as exc:  # pragma: no cover
                logger.debug("Audit sink raised: %s", exc)

        # Append to JSONL file
        if self._log_path is not None:
            try:
                self._log_path.parent.mkdir(parents=True, exist_ok=True)
                with self._log_path.open("a", encoding="utf-8") as fh:
                    fh.write(entry.to_json() + "\n")
            except OSError as exc:  # pragma: no cover
                logger.debug("Audit file write failed: %s", exc)

        return entry

    def record_decision(
        self,
        decision_obj: Any,
        *,
        tool: str = "unknown",
        actor: Optional[str] = None,
        extra: Optional[Dict[str, Any]] = None,
    ) -> Optional[AuditEntry]:
        """Convenience wrapper: record a :class:`~temporal_policy.DecisionObject`.

        Extracts ``decision``, ``intent_cid``, ``policy_cid``, ``justification``,
        and ``obligations`` directly from *decision_obj* (duck typing).
        """
        if not self._enabled:
            return None
        return self.record(
            policy_cid=getattr(decision_obj, "policy_cid", ""),
            intent_cid=getattr(decision_obj, "intent_cid", ""),
            decision=getattr(decision_obj, "decision", "unknown"),
            actor=actor,
            tool=tool,
            justification=getattr(decision_obj, "justification", ""),
            obligations=[
                getattr(o, "type", str(o))
                for o in getattr(decision_obj, "obligations", [])
            ],
            extra=extra or {},
        )

    def recent(self, n: int = 20) -> List[AuditEntry]:
        """Return the *n* most recent audit entries (newest last)."""
        with self._lock:
            return list(self._entries[-n:])

    def all_entries(self) -> List[AuditEntry]:
        """Return a snapshot of all in-memory entries (oldest first)."""
        with self._lock:
            return list(self._entries)

    def decision_counts(self) -> Dict[str, int]:
        """Return a dict mapping ``decision → count`` for all recorded entries."""
        with self._lock:
            return dict(self._counters)

    def total_recorded(self) -> int:
        """Total number of entries recorded since this instance was created."""
        with self._lock:
            return self._total_recorded

    def clear(self) -> int:
        """Clear the in-memory buffer (does not truncate the JSONL file).

        Returns the number of entries that were removed.
        """
        with self._lock:
            n = len(self._entries)
            self._entries.clear()
            return n

    def stats(self) -> Dict[str, Any]:
        """Return a summary dict suitable for metrics/monitoring endpoints."""
        counts = self.decision_counts()
        total = self.total_recorded()
        allow = counts.get("allow", 0) + counts.get("allow_with_obligations", 0)
        deny = counts.get("deny", 0)
        return {
            "total_recorded": total,
            "in_memory": len(self._entries),
            "allow_count": allow,
            "deny_count": deny,
            "allow_rate": allow / total if total else 0.0,
            "deny_rate": deny / total if total else 0.0,
            "by_decision": counts,
            "log_path": str(self._log_path) if self._log_path else None,
            "enabled": self._enabled,
        }

    def __repr__(self) -> str:
        return (
            f"PolicyAuditLog("
            f"enabled={self._enabled}, "
            f"in_memory={len(self._entries)}, "
            f"total={self._total_recorded}"
            f")"
        )


# ─── module-level singleton ───────────────────────────────────────────────────


_default_audit_log: Optional[PolicyAuditLog] = None


def get_audit_log(
    *,
    log_path: Optional[str] = None,
    sink: Optional[Callable[[AuditEntry], None]] = None,
) -> PolicyAuditLog:
    """Return the process-global :class:`PolicyAuditLog` (lazy-init).

    Parameters
    ----------
    log_path:
        If given *and* no global log exists yet, the new singleton will write
        entries to this JSONL file.
    sink:
        If given *and* no global log exists yet, the new singleton will call
        this callable on every recorded entry.
    """
    global _default_audit_log
    if _default_audit_log is None:
        _default_audit_log = PolicyAuditLog(log_path=log_path, sink=sink)
    return _default_audit_log
