"""NL Policy Conflict Detector — BL122 (Phase 3c: conflict detection).

Detects conflicts in a compiled NL policy where the same action on the same
resource is simultaneously *permitted* and *prohibited* for the same actor.

Conflicts are classified as:
* ``"simultaneous_perm_prohib"`` — an action is both permitted and prohibited
* ``"multiple_obligations"`` — the same action is obligated more than once
  (not necessarily a hard conflict but may indicate intent mismatch)

Usage::

    from ipfs_datasets_py.logic.CEC.nl.nl_policy_conflict_detector import (
        NLPolicyConflictDetector, PolicyConflict, detect_conflicts,
    )
    from ipfs_datasets_py.logic.CEC.nl.nl_to_policy_compiler import NLToDCECCompiler

    compiler = NLToDCECCompiler()
    result = compiler.compile([
        "Alice may read all documents.",
        "Alice must not read any documents.",
    ])

    detector = NLPolicyConflictDetector()
    conflicts = detector.detect(result.clauses)
    for c in conflicts:
        print(c.conflict_type, c.action, c.actors)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass
class PolicyConflict:
    """A detected conflict between policy clauses.

    Attributes
    ----------
    conflict_type:
        One of ``"simultaneous_perm_prohib"`` or ``"multiple_obligations"``.
    action:
        The action (or resource) that is in conflict (e.g. ``"read"``).
    resource:
        The resource name involved (may be ``"*"`` / wildcard).
    actors:
        Set of actors affected by this conflict.
    clause_types:
        The set of clause types involved (``"permission"``, ``"prohibition"``,
        ``"obligation"``).
    description:
        Human-readable conflict description.
    """

    conflict_type: str
    action: str
    resource: str = "*"
    actors: Set[str] = field(default_factory=set)
    clause_types: Set[str] = field(default_factory=set)
    description: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """Serialise to a plain dict."""
        return {
            "conflict_type": self.conflict_type,
            "action": self.action,
            "resource": self.resource,
            "actors": sorted(self.actors),
            "clause_types": sorted(self.clause_types),
            "description": self.description,
        }


# ---------------------------------------------------------------------------
# Detector
# ---------------------------------------------------------------------------


class NLPolicyConflictDetector:
    """Detect conflicts in a list of compiled policy clauses.

    Parameters
    ----------
    wildcard:
        The wildcard string used for "any resource" / "any actor" matching.
        Defaults to ``"*"``.
    """

    def __init__(self, wildcard: str = "*") -> None:
        self._wildcard = wildcard

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def detect(self, clauses: List[Any]) -> List[PolicyConflict]:
        """Detect conflicts in *clauses*.

        Parameters
        ----------
        clauses:
            List of ``PolicyClause``-like objects with at least:
            ``clause_type`` (``"permission"``/``"prohibition"``/``"obligation"``),
            ``action`` (str), ``actor`` (str or ``None``),
            ``resource`` (str or ``None``).

        Returns
        -------
        list of :class:`PolicyConflict`
            Empty list when no conflicts are detected.
        """
        return self._check_perm_prohib(clauses) + self._check_multiple_obligations(clauses)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _key(self, clause: Any) -> str:
        """Normalise action + resource into a conflict grouping key."""
        action = getattr(clause, "action", None) or "*"
        resource = getattr(clause, "resource", None) or "*"
        return f"{action}::{resource}"

    def _actor(self, clause: Any) -> str:
        actor = getattr(clause, "actor", None)
        return actor if actor else self._wildcard

    def _check_perm_prohib(self, clauses: List[Any]) -> List[PolicyConflict]:
        """Return one conflict per (action, resource) pair that has both a
        permission and a prohibition clause."""
        permissions: Dict[str, List[Any]] = {}
        prohibitions: Dict[str, List[Any]] = {}

        for c in clauses:
            ct = getattr(c, "clause_type", None)
            k = self._key(c)
            if ct == "permission":
                permissions.setdefault(k, []).append(c)
            elif ct == "prohibition":
                prohibitions.setdefault(k, []).append(c)

        conflicts: List[PolicyConflict] = []
        for k in set(permissions) & set(prohibitions):
            action, resource = k.split("::", 1)
            perm_clauses = permissions[k]
            prohib_clauses = prohibitions[k]

            # Collect all actors mentioned in both sides
            actors: Set[str] = set()
            for c in perm_clauses + prohib_clauses:
                actors.add(self._actor(c))

            # Only a real conflict when actor sets overlap (or either side
            # has a wildcard actor)
            wildcard = self._wildcard
            perm_actors = {self._actor(c) for c in perm_clauses}
            prohib_actors = {self._actor(c) for c in prohib_clauses}
            has_overlap = bool(perm_actors & prohib_actors) or \
                          wildcard in perm_actors or \
                          wildcard in prohib_actors

            if has_overlap:
                overlapping = actors if wildcard in actors else (perm_actors & prohib_actors)
                conflicts.append(
                    PolicyConflict(
                        conflict_type="simultaneous_perm_prohib",
                        action=action,
                        resource=resource,
                        actors=overlapping or actors,
                        clause_types={"permission", "prohibition"},
                        description=(
                            f"Action '{action}' on '{resource}' is both permitted "
                            f"and prohibited for actor(s) "
                            f"{sorted(overlapping or actors)!r}."
                        ),
                    )
                )
        return conflicts

    def _check_multiple_obligations(self, clauses: List[Any]) -> List[PolicyConflict]:
        """Return a conflict for each (action, resource, actor) triple that
        has more than one obligation clause (duplicate obligations)."""
        obligations: Dict[str, List[Any]] = {}
        for c in clauses:
            ct = getattr(c, "clause_type", None)
            if ct != "obligation":
                continue
            key = f"{self._key(c)}::{self._actor(c)}"
            obligations.setdefault(key, []).append(c)

        conflicts: List[PolicyConflict] = []
        for key, cs in obligations.items():
            if len(cs) > 1:
                parts = key.split("::", 2)
                action, resource = parts[0], parts[1]
                actor = parts[2] if len(parts) > 2 else self._wildcard
                conflicts.append(
                    PolicyConflict(
                        conflict_type="multiple_obligations",
                        action=action,
                        resource=resource,
                        actors={actor},
                        clause_types={"obligation"},
                        description=(
                            f"Action '{action}' on '{resource}' has {len(cs)} "
                            f"obligation clauses for actor '{actor}' — possible duplicate."
                        ),
                    )
                )
        return conflicts


# ---------------------------------------------------------------------------
# Module-level convenience
# ---------------------------------------------------------------------------


def detect_conflicts(
    clauses: List[Any],
    *,
    wildcard: str = "*",
) -> List[PolicyConflict]:
    """Shorthand: instantiate a :class:`NLPolicyConflictDetector` and call
    :meth:`~NLPolicyConflictDetector.detect`.

    Parameters
    ----------
    clauses:
        Policy clause list (see :meth:`~NLPolicyConflictDetector.detect`).
    wildcard:
        Wildcard string (default ``"*"``).

    Returns
    -------
    list of :class:`PolicyConflict`
    """
    return NLPolicyConflictDetector(wildcard=wildcard).detect(clauses)
