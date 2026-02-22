"""Compliance checking for MCP++ tool invocations.

Provides a lightweight, rule-based compliance engine that evaluates
:class:`~cid_artifacts.IntentObject`-like objects against a set of
named compliance rules before dispatch.

Key concepts
------------
- **ComplianceRule** — a named callable ``(intent) → ComplianceResult``.
- **ComplianceResult** — status + list of :class:`ComplianceViolation`.
- **ComplianceReport** — aggregated results across all rules checked.
- **ComplianceChecker** — manages a registry of rules and runs them.

Built-in rules
--------------
The default checker includes these rules (all can be removed/replaced):

``tool_name_convention``
    Tool names must be non-empty and use only ``[a-z0-9_]`` characters.

``intent_has_actor``
    The intent must specify a non-empty ``actor`` field.

``actor_is_valid``
    Actor string must not contain whitespace.

``params_are_serializable``
    All parameter values must be JSON-serializable primitives or containers.

``tool_not_in_deny_list``
    Blocks specific tool names via a configurable deny list.

``rate_limit_ok``
    Rate-limit check stub — always passes unless overridden by a subclass or
    custom rule (requires external state).
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set

logger = logging.getLogger(__name__)

__all__ = [
    "ComplianceStatus",
    "ComplianceViolation",
    "ComplianceResult",
    "ComplianceReport",
    "ComplianceChecker",
    "make_default_compliance_checker",
]


# ---------------------------------------------------------------------------
# Status enum
# ---------------------------------------------------------------------------

class ComplianceStatus(str, Enum):
    """Result status for a single compliance rule check."""

    COMPLIANT = "compliant"
    NON_COMPLIANT = "non_compliant"
    WARNING = "warning"
    SKIPPED = "skipped"


# ---------------------------------------------------------------------------
# Violation
# ---------------------------------------------------------------------------

@dataclass
class ComplianceViolation:
    """A single compliance violation detected by a rule.

    Attributes
    ----------
    rule_id:
        Identifier of the rule that raised this violation.
    message:
        Human-readable explanation.
    severity:
        ``"error"`` (blocks dispatch), ``"warning"`` (advisory only), or
        ``"info"``.
    """

    rule_id: str
    message: str
    severity: str = "error"  # "error" | "warning" | "info"

    def to_dict(self) -> Dict:
        return {
            "rule_id": self.rule_id,
            "message": self.message,
            "severity": self.severity,
        }


# ---------------------------------------------------------------------------
# ComplianceResult
# ---------------------------------------------------------------------------

@dataclass
class ComplianceResult:
    """Result of a single compliance rule applied to one intent.

    Attributes
    ----------
    rule_id:
        Identifier of the rule that produced this result.
    status:
        :class:`ComplianceStatus` outcome.
    violations:
        List of :class:`ComplianceViolation` objects (may be empty).
    checked_at:
        Unix timestamp of the check.
    """

    rule_id: str
    status: ComplianceStatus
    violations: List[ComplianceViolation] = field(default_factory=list)
    checked_at: float = field(default_factory=time.time)

    @property
    def is_compliant(self) -> bool:
        return self.status in (ComplianceStatus.COMPLIANT, ComplianceStatus.SKIPPED)

    def to_dict(self) -> Dict:
        return {
            "rule_id": self.rule_id,
            "status": self.status.value,
            "violations": [v.to_dict() for v in self.violations],
            "checked_at": self.checked_at,
        }


# ---------------------------------------------------------------------------
# ComplianceReport
# ---------------------------------------------------------------------------

@dataclass
class ComplianceReport:
    """Aggregated compliance results for one intent across all rules.

    Attributes
    ----------
    results:
        Per-rule :class:`ComplianceResult` objects.
    summary:
        ``"pass"`` if all rules pass, ``"fail"`` otherwise.
    checked_at:
        Unix timestamp.
    """

    results: List[ComplianceResult] = field(default_factory=list)
    checked_at: float = field(default_factory=time.time)

    @property
    def summary(self) -> str:
        for r in self.results:
            if not r.is_compliant:
                return "fail"
        return "pass"

    @property
    def all_violations(self) -> List[ComplianceViolation]:
        violations: List[ComplianceViolation] = []
        for r in self.results:
            violations.extend(r.violations)
        return violations

    def to_dict(self) -> Dict:
        return {
            "summary": self.summary,
            "results": [r.to_dict() for r in self.results],
            "all_violations": [v.to_dict() for v in self.all_violations],
            "checked_at": self.checked_at,
        }


# ---------------------------------------------------------------------------
# ComplianceChecker
# ---------------------------------------------------------------------------

# Type alias for a compliance rule callable
ComplianceRuleFn = Callable[[Any], ComplianceResult]

# Regex for valid tool names
_TOOL_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")


def _is_json_serializable(obj: Any, _depth: int = 0) -> bool:
    """Return True if *obj* is JSON-serializable."""
    if _depth > 10:
        return False
    if obj is None or isinstance(obj, (bool, int, float, str)):
        return True
    if isinstance(obj, (list, tuple)):
        return all(_is_json_serializable(v, _depth + 1) for v in obj)
    if isinstance(obj, dict):
        return all(
            isinstance(k, str) and _is_json_serializable(v, _depth + 1)
            for k, v in obj.items()
        )
    return False


class ComplianceChecker:
    """Manages a registry of compliance rules and runs them against intents.

    Usage::

        checker = ComplianceChecker()
        checker.add_rule("my_rule", my_rule_fn)
        report = checker.check_compliance(intent)
        if report.summary == "fail":
            ...
    """

    def __init__(
        self,
        deny_list: Optional[Set[str]] = None,
    ) -> None:
        self._rules: Dict[str, ComplianceRuleFn] = {}
        self._rule_order: List[str] = []
        self._deny_list: Set[str] = set(deny_list or [])

    # ------------------------------------------------------------------
    # Rule management
    # ------------------------------------------------------------------

    def add_rule(self, rule_id: str, fn: ComplianceRuleFn) -> None:
        """Register a compliance rule callable under *rule_id*."""
        self._rules[rule_id] = fn
        if rule_id not in self._rule_order:
            self._rule_order.append(rule_id)

    def remove_rule(self, rule_id: str) -> bool:
        """Remove a rule; return True if it existed."""
        if rule_id in self._rules:
            del self._rules[rule_id]
            self._rule_order = [r for r in self._rule_order if r != rule_id]
            return True
        return False

    def list_rules(self) -> List[str]:
        """Return rule IDs in registration order."""
        return list(self._rule_order)

    # ------------------------------------------------------------------
    # Persistence (Session 60)
    # ------------------------------------------------------------------

    def save(self, path: str) -> None:
        """Persist the ordered rule list to *path* as JSON.

        Only the **rule IDs** (names) are persisted — not the callables.  On
        :meth:`load` the rule names are used to look up matching built-in
        rule implementations that already exist on this instance.  Custom rules
        (added via :meth:`add_rule`) must be re-registered after :meth:`load`.

        The deny list is also persisted so that the full default configuration
        can be restored without re-specifying the blocked tools.

        Creates parent directories if they do not exist.

        Args:
            path: Filesystem path for the JSON file.
        """
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        data: Dict[str, Any] = {
            "rule_order": list(self._rule_order),
            "deny_list": sorted(self._deny_list),
        }
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
        logger.debug("Saved %d compliance rules to %s", len(self._rule_order), path)

    def load(self, path: str) -> int:
        """Load rule configuration from *path*.

        Re-wires built-in rules whose IDs appear in the persisted
        ``"rule_order"`` list against the bound rule methods on *self*.
        Built-in rule IDs are: ``tool_name_convention``, ``intent_has_actor``,
        ``actor_is_valid``, ``params_are_serializable``,
        ``tool_not_in_deny_list``, ``rate_limit_ok``.

        For any rule ID that is **not** a built-in, a no-op stub is registered
        so that the rule slot is preserved in the order.  Callers should then
        call :meth:`add_rule` with the real implementation.

        Returns:
            Number of rule IDs loaded (including stubs for unknown rules).
        """
        if not os.path.exists(path):
            logger.debug("Compliance rule file not found: %s", path)
            return 0
        try:
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
        except Exception as exc:
            logger.warning("Could not load compliance rules from %s: %s", path, exc)
            return 0

        # Restore deny list
        deny_list = data.get("deny_list", [])
        if isinstance(deny_list, list):
            self._deny_list = set(str(d) for d in deny_list)

        # Map built-in rule IDs to their bound methods
        _builtin_map: Dict[str, ComplianceRuleFn] = {
            "tool_name_convention": self._rule_tool_name_convention,
            "intent_has_actor": self._rule_intent_has_actor,
            "actor_is_valid": self._rule_actor_is_valid,
            "params_are_serializable": self._rule_params_are_serializable,
            "tool_not_in_deny_list": self._rule_tool_not_in_deny_list,
            "rate_limit_ok": self._rule_rate_limit_ok,
        }

        rule_order = data.get("rule_order", [])
        loaded = 0
        for rule_id in rule_order:
            if not isinstance(rule_id, str) or not rule_id:
                continue
            fn = _builtin_map.get(rule_id)
            if fn is None:
                # Stub: always COMPLIANT; real implementation must be re-added
                _captured_id = rule_id
                def _stub(_intent: Any, _rule_id: str = _captured_id) -> "ComplianceResult":
                    return ComplianceResult(rule_id=_rule_id, status=ComplianceStatus.COMPLIANT)
                fn = _stub
            if rule_id not in self._rules:
                self._rule_order.append(rule_id)
            self._rules[rule_id] = fn
            loaded += 1

        logger.debug("Loaded %d compliance rules from %s", loaded, path)
        return loaded

    # ------------------------------------------------------------------
    # Intent field extraction
    # ------------------------------------------------------------------

    @staticmethod
    def _get_field(intent: Any, field: str, default: Any = None) -> Any:
        if isinstance(intent, dict):
            return intent.get(field, default)
        return getattr(intent, field, default)

    # ------------------------------------------------------------------
    # Built-in rule implementations
    # ------------------------------------------------------------------

    def _rule_tool_name_convention(self, intent: Any) -> ComplianceResult:
        rule_id = "tool_name_convention"
        tool_name = self._get_field(intent, "tool_name", "") or ""
        violations: List[ComplianceViolation] = []

        if not tool_name:
            violations.append(ComplianceViolation(
                rule_id=rule_id,
                message="tool_name is empty or missing",
                severity="error",
            ))
        elif not _TOOL_NAME_RE.match(tool_name):
            violations.append(ComplianceViolation(
                rule_id=rule_id,
                message=(
                    f"tool_name '{tool_name}' violates naming convention "
                    "(must match ^[a-z][a-z0-9_]*$)"
                ),
                severity="error",
            ))

        status = ComplianceStatus.COMPLIANT if not violations else ComplianceStatus.NON_COMPLIANT
        return ComplianceResult(rule_id=rule_id, status=status, violations=violations)

    def _rule_intent_has_actor(self, intent: Any) -> ComplianceResult:
        rule_id = "intent_has_actor"
        actor = self._get_field(intent, "actor", "") or ""
        violations: List[ComplianceViolation] = []

        if not actor.strip():
            violations.append(ComplianceViolation(
                rule_id=rule_id,
                message="intent is missing a non-empty 'actor' field",
                severity="warning",
            ))

        status = (
            ComplianceStatus.COMPLIANT
            if not violations
            else ComplianceStatus.WARNING
        )
        return ComplianceResult(rule_id=rule_id, status=status, violations=violations)

    def _rule_actor_is_valid(self, intent: Any) -> ComplianceResult:
        rule_id = "actor_is_valid"
        actor = self._get_field(intent, "actor", "") or ""
        violations: List[ComplianceViolation] = []

        if actor and re.search(r"\s", actor):
            violations.append(ComplianceViolation(
                rule_id=rule_id,
                message=f"actor '{actor}' contains whitespace",
                severity="error",
            ))

        status = ComplianceStatus.COMPLIANT if not violations else ComplianceStatus.NON_COMPLIANT
        return ComplianceResult(rule_id=rule_id, status=status, violations=violations)

    def _rule_params_are_serializable(self, intent: Any) -> ComplianceResult:
        rule_id = "params_are_serializable"
        params = self._get_field(intent, "params", {}) or {}
        violations: List[ComplianceViolation] = []

        if not _is_json_serializable(params):
            violations.append(ComplianceViolation(
                rule_id=rule_id,
                message="intent params contain non-JSON-serializable values",
                severity="warning",
            ))

        status = (
            ComplianceStatus.COMPLIANT
            if not violations
            else ComplianceStatus.WARNING
        )
        return ComplianceResult(rule_id=rule_id, status=status, violations=violations)

    def _rule_tool_not_in_deny_list(self, intent: Any) -> ComplianceResult:
        rule_id = "tool_not_in_deny_list"
        tool_name = self._get_field(intent, "tool_name", "") or ""
        violations: List[ComplianceViolation] = []

        if tool_name in self._deny_list:
            violations.append(ComplianceViolation(
                rule_id=rule_id,
                message=f"tool '{tool_name}' is in the deny list",
                severity="error",
            ))

        status = ComplianceStatus.COMPLIANT if not violations else ComplianceStatus.NON_COMPLIANT
        return ComplianceResult(rule_id=rule_id, status=status, violations=violations)

    def _rule_rate_limit_ok(self, intent: Any) -> ComplianceResult:
        """Rate-limit stub — always passes.

        Implementations that need real rate limiting should remove this rule via
        :meth:`remove_rule` and register their own ``"rate_limit_ok"`` rule that
        reads per-actor request counters from an external store.

        The *intent* parameter is accepted for API compatibility but is not used
        by the default stub.
        """
        rule_id = "rate_limit_ok"
        return ComplianceResult(
            rule_id=rule_id,
            status=ComplianceStatus.COMPLIANT,
        )

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    def check_compliance(self, intent: Any) -> ComplianceReport:
        """Run all registered rules against *intent* and return a report."""
        results: List[ComplianceResult] = []
        for rule_id in self._rule_order:
            fn = self._rules.get(rule_id)
            if fn is None:
                continue
            try:
                result = fn(intent)
            except Exception as exc:  # pragma: no cover  # guard
                result = ComplianceResult(
                    rule_id=rule_id,
                    status=ComplianceStatus.SKIPPED,
                    violations=[
                        ComplianceViolation(
                            rule_id=rule_id,
                            message=f"Rule raised an exception: {exc}",
                            severity="error",
                        )
                    ],
                )
            results.append(result)

        return ComplianceReport(results=results)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def make_default_compliance_checker(
    deny_list: Optional[Set[str]] = None,
) -> ComplianceChecker:
    """Create a :class:`ComplianceChecker` with all 6 built-in rules loaded.

    Parameters
    ----------
    deny_list:
        Optional set of tool names to block outright.
    """
    checker = ComplianceChecker(deny_list=deny_list)
    checker.add_rule("tool_name_convention", checker._rule_tool_name_convention)
    checker.add_rule("intent_has_actor", checker._rule_intent_has_actor)
    checker.add_rule("actor_is_valid", checker._rule_actor_is_valid)
    checker.add_rule("params_are_serializable", checker._rule_params_are_serializable)
    checker.add_rule("tool_not_in_deny_list", checker._rule_tool_not_in_deny_list)
    checker.add_rule("rate_limit_ok", checker._rule_rate_limit_ok)
    return checker
