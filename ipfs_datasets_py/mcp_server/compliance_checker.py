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
import re
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set

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
