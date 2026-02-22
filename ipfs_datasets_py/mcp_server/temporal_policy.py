"""
Profile D: Temporal Deontic Policy Evaluation

Implements the temporal deontic policy profile from the MCP++ specification:
  https://github.com/endomorphosis/Mcp-Plus-Plus/blob/main/docs/spec/temporal-deontic-policy.md

This module provides a lightweight, self-contained policy evaluator that:
1. Represents policies as content-addressed objects (policy_cid).
2. Evaluates intent objects against policies at execution time.
3. Emits DecisionObject results (allow / deny / allow_with_obligations).
4. Integrates with the existing logic/ TDFOL reasoning module when present.

No external dependencies beyond stdlib. The TDFOL integration is optional.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from .interface_descriptor import compute_cid, _canonicalize
from .cid_artifacts import (
    DecisionObject, IntentObject, Obligation,
    ALLOW, DENY, ALLOW_WITH_OBLIGATIONS,
)

logger = logging.getLogger(__name__)


# ─── policy clause types ────────────────────────────────────────────────────


class PolicyClauseType:
    PERMISSION = "permission"
    PROHIBITION = "prohibition"
    OBLIGATION = "obligation"


@dataclass
class PolicyClause:
    """A single clause in a temporal deontic policy."""
    clause_type: str          # PolicyClauseType.*
    actor: Optional[str] = None
    action: Optional[str] = None
    resource: Optional[str] = None
    valid_from: Optional[float] = None   # Unix timestamp
    valid_until: Optional[float] = None  # Unix timestamp
    condition: Optional[str] = None
    obligation_deadline: Optional[str] = None

    def is_temporally_valid(self, at_time: Optional[float] = None) -> bool:
        """Return True if this clause is within its temporal window."""
        t = at_time if at_time is not None else time.time()
        if self.valid_from is not None and t < self.valid_from:
            return False
        if self.valid_until is not None and t > self.valid_until:
            return False
        return True


# ─── policy object ─────────────────────────────────────────────────────────


@dataclass
class PolicyObject:
    """
    Content-addressed policy (spec §2).

    Policies express permissions, prohibitions, obligations, and temporal
    constraints.  The policy_cid is computed from the canonical representation.
    """
    policy_id: str
    clauses: List[PolicyClause] = field(default_factory=list)
    version: str = "v1"
    description: Optional[str] = None

    _cid: Optional[str] = field(default=None, repr=False, compare=False)

    @property
    def policy_cid(self) -> str:
        if self._cid is None:
            self._cid = compute_cid(self._canonical_bytes())
        return self._cid

    def _canonical_bytes(self) -> bytes:
        d = {
            "policy_id": self.policy_id,
            "version": self.version,
            "clauses": [
                {
                    "clause_type": c.clause_type,
                    "actor": c.actor,
                    "action": c.action,
                    "resource": c.resource,
                    "valid_from": c.valid_from,
                    "valid_until": c.valid_until,
                    "condition": c.condition,
                    "obligation_deadline": c.obligation_deadline,
                }
                for c in self.clauses
            ],
        }
        return _canonicalize(d)

    def get_permissions(self) -> List[PolicyClause]:
        return [c for c in self.clauses
                if c.clause_type == PolicyClauseType.PERMISSION]

    def get_prohibitions(self) -> List[PolicyClause]:
        return [c for c in self.clauses
                if c.clause_type == PolicyClauseType.PROHIBITION]

    def get_obligations(self) -> List[PolicyClause]:
        return [c for c in self.clauses
                if c.clause_type == PolicyClauseType.OBLIGATION]


# ─── evaluator ─────────────────────────────────────────────────────────────


class PolicyEvaluator:
    """
    Runtime policy evaluator (spec §5).

    Checks intent objects against registered policies and emits
    DecisionObjects.

    Algorithm (non-normative, minimal):
    1. If a prohibition matches the intent → DENY
    2. If no permission matches → DENY (closed-world assumption)
    3. Otherwise → ALLOW (or ALLOW_WITH_OBLIGATIONS if obligations exist)
    """

    def __init__(self) -> None:
        self._policies: Dict[str, PolicyObject] = {}
        # Phase 6: decision memoization cache.
        # Key: (policy_cid, intent_cid, actor) → DecisionObject
        # Cache is invalidated (cleared) whenever a new policy is registered.
        self._decision_cache: Dict[tuple, "DecisionObject"] = {}

    def register_policy(self, policy: PolicyObject) -> str:
        """Register a policy and return its policy_cid.

        Registering a new policy invalidates the decision cache because
        existing evaluations may no longer be valid.
        """
        cid = policy.policy_cid
        if cid not in self._policies:
            # Only clear if this is a genuinely new policy to avoid
            # unnecessary cache thrashing when re-registering the same policy.
            self._decision_cache.clear()
        self._policies[cid] = policy
        return cid

    def clear_cache(self) -> int:
        """Explicitly clear the decision memoization cache.

        Returns the number of entries that were cleared.
        """
        n = len(self._decision_cache)
        self._decision_cache.clear()
        return n

    def get_policy(self, policy_cid: str) -> Optional[PolicyObject]:
        return self._policies.get(policy_cid)

    def evaluate(
        self,
        intent: IntentObject,
        policy_cid: str,
        *,
        at_time: Optional[float] = None,
        actor: Optional[str] = None,
        proofs: Optional[List[str]] = None,
        use_cache: bool = True,
    ) -> DecisionObject:
        """
        Evaluate *intent* against the policy identified by *policy_cid*.

        Returns a :class:`DecisionObject` with allow/deny/allow_with_obligations.

        Parameters
        ----------
        intent:
            The :class:`IntentObject` to evaluate.
        policy_cid:
            Identifier of the registered policy to check against.
        at_time:
            Unix timestamp to use for temporal clause validity.  Defaults to
            ``time.time()``.
        actor:
            Optional actor override (used for per-actor clause matching).
        proofs:
            Optional list of UCAN proof CIDs checked during delegation
            verification.
        use_cache:
            When *True* (default), previously computed decisions for the same
            ``(policy_cid, intent_cid, actor)`` triple are returned from the
            memoization cache.  Pass *False* to force re-evaluation.
        """
        # Phase 6: consult memoization cache first.
        # We only cache when at_time is None (i.e. wall-clock time) because
        # time-parameterised calls with an explicit timestamp are typically
        # used for testing temporal edge cases and should always re-evaluate.
        cache_key = (policy_cid, intent.cid, actor)
        if use_cache and at_time is None and cache_key in self._decision_cache:
            return self._decision_cache[cache_key]

        policy = self._policies.get(policy_cid)
        if policy is None:
            return DecisionObject(
                decision=DENY,
                intent_cid=intent.cid,
                policy_cid=policy_cid,
                justification=f"Unknown policy_cid: {policy_cid}",
            )

        t = at_time if at_time is not None else time.time()

        # 1. Check prohibitions first (deny overrides)
        for clause in policy.get_prohibitions():
            if not clause.is_temporally_valid(t):
                continue
            if self._clause_matches(clause, intent, actor):
                return DecisionObject(
                    decision=DENY,
                    intent_cid=intent.cid,
                    policy_cid=policy_cid,
                    proofs_checked=proofs or [],
                    justification=f"Prohibited by clause: action={clause.action}",
                    policy_version=policy.version,
                )

        # 2. Check permissions (must have at least one match)
        permitted = False
        for clause in policy.get_permissions():
            if not clause.is_temporally_valid(t):
                continue
            if self._clause_matches(clause, intent, actor):
                permitted = True
                break

        if not permitted:
            return DecisionObject(
                decision=DENY,
                intent_cid=intent.cid,
                policy_cid=policy_cid,
                proofs_checked=proofs or [],
                justification="No matching permission found (closed-world).",
                policy_version=policy.version,
            )

        # 3. Collect obligations
        spawned: List[Obligation] = []
        for clause in policy.get_obligations():
            if not clause.is_temporally_valid(t):
                continue
            if self._clause_matches(clause, intent, actor):
                spawned.append(Obligation(
                    type=clause.action or "unspecified",
                    deadline=clause.obligation_deadline,
                ))

        decision = ALLOW_WITH_OBLIGATIONS if spawned else ALLOW
        result = DecisionObject(
            decision=decision,
            intent_cid=intent.cid,
            policy_cid=policy_cid,
            proofs_checked=proofs or [],
            obligations=spawned,
            justification="Permission granted.",
            policy_version=policy.version,
        )
        # Phase 6: store in memoization cache (only for wall-clock evaluations).
        if use_cache and at_time is None:
            self._decision_cache[cache_key] = result
        return result

    @staticmethod
    def _clause_matches(
        clause: PolicyClause,
        intent: IntentObject,
        actor: Optional[str],
    ) -> bool:
        """Return True if *clause* applies to *intent*."""
        if clause.actor is not None and actor is not None:
            if clause.actor != actor and clause.actor != "*":
                return False
        if clause.action is not None:
            if clause.action != intent.tool and clause.action != "*":
                return False
        return True


# ─── module-level helpers ────────────────────────────────────────────────────


_global_evaluator: Optional[PolicyEvaluator] = None


def get_policy_evaluator() -> PolicyEvaluator:
    """Return the process-global PolicyEvaluator (lazy-init)."""
    global _global_evaluator
    if _global_evaluator is None:
        _global_evaluator = PolicyEvaluator()
    return _global_evaluator


class PolicyRegistry:
    """
    Durable policy store with JSON persistence (Profile D: spec §2).

    Wraps a :class:`PolicyEvaluator` and provides :meth:`save` / :meth:`load`
    helpers for JSON-based persistence.  In a production deployment these would
    serialize to IPFS CAR files; the JSON implementation here is intended for
    development and testing.
    """

    def __init__(self, evaluator: Optional[PolicyEvaluator] = None) -> None:
        self._evaluator = evaluator or PolicyEvaluator()
        self._meta: Dict[str, str] = {}  # policy_cid → policy_id

    @property
    def evaluator(self) -> PolicyEvaluator:
        return self._evaluator

    def register(self, policy: "PolicyObject") -> str:
        """Register a policy and return its policy_cid."""
        cid = self._evaluator.register_policy(policy)
        self._meta[cid] = policy.policy_id
        return cid

    def list_policies(self) -> List[Dict[str, str]]:
        """Return a list of registered policies with id and cid."""
        return [
            {"policy_id": pid, "policy_cid": cid}
            for cid, pid in self._meta.items()
        ]

    def evaluate(
        self,
        intent: "IntentObject",
        policy_cid: str,
        **kwargs: Any,
    ) -> "DecisionObject":
        """Delegate evaluation to the inner evaluator."""
        return self._evaluator.evaluate(intent, policy_cid, **kwargs)

    def save(self, path: str) -> None:
        """Persist registered policies to a JSON file.

        In production, replace with IPFS CAR serialisation.
        """
        import json as _json
        records = []
        for _cid, pol in self._evaluator._policies.items():
            records.append({
                "policy_id": pol.policy_id,
                "version": pol.version,
                "description": pol.description,
                "clauses": [
                    {
                        "clause_type": c.clause_type,
                        "actor": c.actor,
                        "action": c.action,
                        "resource": c.resource,
                        "valid_from": c.valid_from,
                        "valid_until": c.valid_until,
                        "condition": c.condition,
                        "obligation_deadline": c.obligation_deadline,
                    }
                    for c in pol.clauses
                ],
            })
        with open(path, "w") as f:
            _json.dump(records, f, indent=2)

    def load(self, path: str) -> int:
        """Load policies from a JSON file.  Returns number of policies loaded.

        In production, replace with IPFS CAR deserialisation.
        """
        import json as _json
        with open(path) as f:
            records = _json.load(f)
        count = 0
        for rec in records:
            clauses = [
                PolicyClause(
                    clause_type=c["clause_type"],
                    actor=c.get("actor"),
                    action=c.get("action"),
                    resource=c.get("resource"),
                    valid_from=c.get("valid_from"),
                    valid_until=c.get("valid_until"),
                    condition=c.get("condition"),
                    obligation_deadline=c.get("obligation_deadline"),
                )
                for c in rec.get("clauses", [])
            ]
            pol = PolicyObject(
                policy_id=rec["policy_id"],
                clauses=clauses,
                version=rec.get("version", "v1"),
                description=rec.get("description"),
            )
            self.register(pol)
            count += 1
        return count


# ─── module-level registry singleton ────────────────────────────────────────


_global_registry: Optional[PolicyRegistry] = None


def get_policy_registry() -> PolicyRegistry:
    """Return the process-global PolicyRegistry (lazy-init)."""
    global _global_registry
    if _global_registry is None:
        _global_registry = PolicyRegistry()
    return _global_registry


def make_simple_permission_policy(
    *,
    policy_id: str,
    allowed_tools: List[str],
    actor: Optional[str] = None,
    valid_until: Optional[float] = None,
) -> PolicyObject:
    """Helper: build a policy that permits a list of named tools."""
    clauses = [
        PolicyClause(
            clause_type=PolicyClauseType.PERMISSION,
            actor=actor,
            action=tool,
            valid_until=valid_until,
        )
        for tool in allowed_tools
    ]
    return PolicyObject(policy_id=policy_id, clauses=clauses)
