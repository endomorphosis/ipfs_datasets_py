"""Compliance Checker — rule-based intent compliance validation (Profile A §8).

Each :class:`ComplianceRule` is a named, optionally-removable predicate over
an intent dict.  A :class:`ComplianceChecker` holds an ordered set of rules
and produces a :class:`ComplianceReport` when :meth:`~ComplianceChecker.check`
is called.

Built-in rules
--------------
* ``tool_name_convention`` — tool name uses only [a-z0-9_]
* ``intent_has_actor`` — ``actor`` field present and non-empty
* ``actor_is_valid`` — actor matches ``[a-zA-Z0-9_\\-@.]+``
* ``params_are_serializable`` — ``params`` dict is JSON-serialisable

Usage::

    from ipfs_datasets_py.mcp_server.compliance_checker import (
        ComplianceChecker, ComplianceRule, make_default_checker,
    )

    checker = make_default_checker()
    report = checker.check({"tool": "read_file", "actor": "alice", "params": {}})
    print(report.passed)          # True
    print(report.failed_rules)    # []
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass
class ComplianceResult:
    """Outcome of a single :class:`ComplianceRule` check.

    Attributes
    ----------
    rule_id:
        Identifier matching :attr:`ComplianceRule.rule_id`.
    passed:
        Whether the rule passed.
    message:
        Human-readable description of the outcome.
    """

    rule_id: str
    passed: bool
    message: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {"rule_id": self.rule_id, "passed": self.passed, "message": self.message}


@dataclass
class ComplianceReport:
    """Aggregate result of checking all rules against a single intent.

    Attributes
    ----------
    results:
        List of per-rule :class:`ComplianceResult` objects.
    intent_snapshot:
        A shallow copy of the intent that was checked (for audit purposes).
    """

    results: List[ComplianceResult] = field(default_factory=list)
    intent_snapshot: Dict[str, Any] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        """Return *True* if **all** rules passed."""
        return all(r.passed for r in self.results)

    @property
    def failed_rules(self) -> List[str]:
        """Return the rule IDs of failed rules."""
        return [r.rule_id for r in self.results if not r.passed]

    @property
    def passed_rules(self) -> List[str]:
        """Return the rule IDs of passed rules."""
        return [r.rule_id for r in self.results if r.passed]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "passed": self.passed,
            "failed_rules": self.failed_rules,
            "results": [r.to_dict() for r in self.results],
        }


# ---------------------------------------------------------------------------
# ComplianceRule
# ---------------------------------------------------------------------------


@dataclass
class ComplianceRule:
    """A single named compliance predicate.

    Parameters
    ----------
    rule_id:
        Unique identifier.  Must be non-empty.
    description:
        Human-readable description shown in reports.
    check_fn:
        Callable ``(intent: dict) -> ComplianceResult``.  Receives the full
        intent dict and returns a :class:`ComplianceResult`.
    removable:
        Whether this rule can be removed via
        :meth:`ComplianceChecker.remove_rule`.
    """

    rule_id: str
    description: str
    check_fn: Callable[[Dict[str, Any]], ComplianceResult]
    removable: bool = True

    def __post_init__(self) -> None:
        if not self.rule_id:
            raise ValueError("ComplianceRule.rule_id must be non-empty")

    def check(self, intent: Dict[str, Any]) -> ComplianceResult:
        """Execute the check function and return the result."""
        try:
            result = self.check_fn(intent)
            if not isinstance(result, ComplianceResult):
                # Coerce a plain bool
                result = ComplianceResult(
                    rule_id=self.rule_id,
                    passed=bool(result),
                    message="(auto-coerced)",
                )
            return result
        except Exception as exc:
            logger.warning(
                "ComplianceRule %s raised %s: %s",
                self.rule_id,
                type(exc).__name__,
                exc,
            )
            return ComplianceResult(
                rule_id=self.rule_id,
                passed=False,
                message=f"Rule raised {type(exc).__name__}: {exc}",
            )

    def __repr__(self) -> str:
        return (
            f"ComplianceRule(rule_id={self.rule_id!r}, "
            f"removable={self.removable})"
        )


# ---------------------------------------------------------------------------
# ComplianceChecker
# ---------------------------------------------------------------------------


class ComplianceChecker:
    """Ordered collection of :class:`ComplianceRule` objects.

    Rules are checked in insertion order.  The checker continues through all
    rules even if an early rule fails (unless *fail_fast=True*).

    Parameters
    ----------
    rules:
        Initial list of rules.  Defaults to an empty list (use
        :func:`make_default_checker` for the built-in rule set).
    fail_fast:
        If *True*, stop checking after the first failed rule.
    """

    def __init__(
        self,
        rules: Optional[List[ComplianceRule]] = None,
        *,
        fail_fast: bool = False,
    ) -> None:
        self._rules: List[ComplianceRule] = list(rules or [])
        self.fail_fast = fail_fast

    # ------------------------------------------------------------------
    # Rule management
    # ------------------------------------------------------------------

    def add_rule(self, rule: ComplianceRule) -> None:
        """Append *rule* to the checker.

        Raises
        ------
        ValueError
            If a rule with the same ``rule_id`` already exists.
        """
        if any(r.rule_id == rule.rule_id for r in self._rules):
            raise ValueError(
                f"Rule with rule_id={rule.rule_id!r} already registered"
            )
        self._rules.append(rule)

    def remove_rule(self, rule_id: str) -> bool:
        """Remove the rule with *rule_id*.

        Returns *True* if the rule was found and removed, *False* if not found.

        Raises
        ------
        ValueError
            If the rule exists but has ``removable=False``.
        """
        for i, r in enumerate(self._rules):
            if r.rule_id == rule_id:
                if not r.removable:
                    raise ValueError(
                        f"Rule {rule_id!r} is not removable"
                    )
                del self._rules[i]
                return True
        return False

    def list_rules(self) -> List[Dict[str, Any]]:
        """Return a list of ``{rule_id, description, removable}`` dicts."""
        return [
            {
                "rule_id": r.rule_id,
                "description": r.description,
                "removable": r.removable,
            }
            for r in self._rules
        ]

    def get_rule(self, rule_id: str) -> Optional[ComplianceRule]:
        """Return the rule with *rule_id*, or *None*."""
        for r in self._rules:
            if r.rule_id == rule_id:
                return r
        return None

    def __len__(self) -> int:
        return len(self._rules)

    # ------------------------------------------------------------------
    # Checking
    # ------------------------------------------------------------------

    def check(self, intent: Dict[str, Any]) -> ComplianceReport:
        """Run all enabled rules against *intent* and return a :class:`ComplianceReport`."""
        results: List[ComplianceResult] = []
        snapshot = {k: v for k, v in intent.items() if k != "params"}

        for rule in self._rules:
            result = rule.check(intent)
            results.append(result)
            if self.fail_fast and not result.passed:
                break

        return ComplianceReport(results=results, intent_snapshot=snapshot)

    def diff(self, other: "ComplianceChecker") -> Dict[str, Any]:
        """CR154: Compare *self* against *other* and return a diff summary.

        The diff shows which rules are unique to each checker and which are
        shared.  Rules are compared by ``rule_id``.

        Returns
        -------
        dict with keys:

        * ``added_rules`` — rule IDs present in *other* but not in *self*.
        * ``removed_rules`` — rule IDs present in *self* but not in *other*.
        * ``common_rules`` — rule IDs present in both checkers.
        * ``changed_rules`` — rule IDs present in both but with differing
          ``description`` or ``removable`` values.
        """
        self_ids = {r.rule_id: r for r in self._rules}
        other_ids = {r.rule_id: r for r in other._rules}
        added = sorted(set(other_ids) - set(self_ids))
        removed = sorted(set(self_ids) - set(other_ids))
        common = sorted(set(self_ids) & set(other_ids))
        changed = [
            rid for rid in common
            if (
                self_ids[rid].description != other_ids[rid].description
                or self_ids[rid].removable != other_ids[rid].removable
            )
        ]
        return {
            "added_rules": added,
            "removed_rules": removed,
            "common_rules": common,
            "changed_rules": changed,
        }

    def __repr__(self) -> str:
        return f"ComplianceChecker(rules={len(self._rules)}, fail_fast={self.fail_fast})"


# ---------------------------------------------------------------------------
# Built-in rules
# ---------------------------------------------------------------------------

_TOOL_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_ACTOR_RE = re.compile(r"^[a-zA-Z0-9_\-@.]+$")


def _rule_tool_name_convention(intent: Dict[str, Any]) -> ComplianceResult:
    tool = intent.get("tool", "")
    ok = bool(tool) and bool(_TOOL_NAME_RE.match(str(tool)))
    return ComplianceResult(
        rule_id="tool_name_convention",
        passed=ok,
        message="OK" if ok else f"Invalid tool name: {tool!r}",
    )


def _rule_intent_has_actor(intent: Dict[str, Any]) -> ComplianceResult:
    actor = intent.get("actor", "")
    ok = bool(actor)
    return ComplianceResult(
        rule_id="intent_has_actor",
        passed=ok,
        message="OK" if ok else "Missing actor field",
    )


def _rule_actor_is_valid(intent: Dict[str, Any]) -> ComplianceResult:
    actor = str(intent.get("actor", ""))
    ok = bool(actor) and bool(_ACTOR_RE.match(actor))
    return ComplianceResult(
        rule_id="actor_is_valid",
        passed=ok,
        message="OK" if ok else f"Invalid actor format: {actor!r}",
    )


def _rule_params_are_serializable(intent: Dict[str, Any]) -> ComplianceResult:
    params = intent.get("params", {})
    try:
        json.dumps(params)
        ok = True
        msg = "OK"
    except (TypeError, ValueError) as exc:
        ok = False
        msg = f"Params not JSON-serialisable: {exc}"
    return ComplianceResult(
        rule_id="params_are_serializable",
        passed=ok,
        message=msg,
    )


_BUILTIN_RULES: List[ComplianceRule] = [
    ComplianceRule(
        rule_id="tool_name_convention",
        description="Tool name must match [a-z][a-z0-9_]*",
        check_fn=_rule_tool_name_convention,
        removable=False,
    ),
    ComplianceRule(
        rule_id="intent_has_actor",
        description="Intent must have a non-empty actor field",
        check_fn=_rule_intent_has_actor,
        removable=True,
    ),
    ComplianceRule(
        rule_id="actor_is_valid",
        description="Actor must match [a-zA-Z0-9_\\-@.]+",
        check_fn=_rule_actor_is_valid,
        removable=True,
    ),
    ComplianceRule(
        rule_id="params_are_serializable",
        description="params dict must be JSON-serialisable",
        check_fn=_rule_params_are_serializable,
        removable=True,
    ),
]


def make_default_checker(*, fail_fast: bool = False) -> ComplianceChecker:
    """Return a :class:`ComplianceChecker` pre-loaded with the four built-in rules."""
    import copy
    return ComplianceChecker(
        rules=[copy.copy(r) for r in _BUILTIN_RULES],
        fail_fast=fail_fast,
    )
