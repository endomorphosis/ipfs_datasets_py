"""Profile D: Temporal Deontic Policy Evaluation.

Implements the MCP++ Profile D specification from:
https://github.com/endomorphosis/Mcp-Plus-Plus/blob/main/docs/spec/temporal-deontic-policy.md

Policies are content-addressed (``policy_cid``) and express:
- **Permissions** — what is allowed
- **Prohibitions** — what is forbidden
- **Obligations** — what must be done (often with deadlines)
- **Temporal constraints** — validity windows, deadlines, revocations

At execution time, a ``PolicyEvaluator`` accepts an ``IntentObject`` (from
``cid_artifacts``) plus a ``PolicyObject`` and returns a ``DecisionObject``.

The ``make_simple_permission_policy()`` factory builds a minimal policy that
grants a named actor permission to call a specific tool within a time window.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Union

from .cid_artifacts import DecisionObject, IntentObject, artifact_cid


# ---------------------------------------------------------------------------
# Policy representation
# ---------------------------------------------------------------------------

@dataclass
class PolicyClause:
    """A single deontic clause within a policy.

    Each clause represents one normative statement of the form::

        Permission / Prohibition / Obligation (actor, action, resource, time)

    Attributes:
        clause_type: One of ``"permission"``, ``"prohibition"``, ``"obligation"``.
        actor: The agent / role the clause applies to.  ``"*"`` matches any actor.
        action: The tool name / action name.  ``"*"`` matches any action.
        resource: Optional resource identifier scoped by this clause.
        valid_from: ISO-8601 UTC timestamp — clause is inactive before this.
        valid_until: ISO-8601 UTC timestamp — clause expires after this.
        obligation_deadline: For ``obligation`` clauses, the deadline by which
            the obligated action must be completed.
        metadata: Additional freeform key-value metadata.
    """

    clause_type: str  # "permission" | "prohibition" | "obligation"
    actor: str = "*"
    action: str = "*"
    resource: Optional[str] = None
    valid_from: Optional[str] = None
    valid_until: Optional[str] = None
    obligation_deadline: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def is_temporally_valid(self, now: Optional[Union[float, datetime]] = None) -> bool:
        """Return whether this clause is active at *now*.

        Accepts either a UNIX timestamp (float/int) or datetime for legacy tests.
        """
        if now is None:
            current = datetime.now(timezone.utc)
        elif isinstance(now, (int, float)):
            current = datetime.fromtimestamp(float(now), tz=timezone.utc)
        else:
            current = now
            if current.tzinfo is None:
                current = current.replace(tzinfo=timezone.utc)

        valid_from = _parse_iso(self.valid_from)
        if valid_from and current < valid_from:
            return False
        valid_until = _parse_iso(self.valid_until)
        if valid_until and current > valid_until:
            return False
        return True

    def to_dict(self) -> Dict[str, Any]:
        """Serialise to a plain dict."""
        return {
            "clause_type": self.clause_type,
            "actor": self.actor,
            "action": self.action,
            "resource": self.resource,
            "valid_from": self.valid_from,
            "valid_until": self.valid_until,
            "obligation_deadline": self.obligation_deadline,
            "metadata": self.metadata,
        }


@dataclass
class PolicyObject:
    """A content-addressed policy container (Profile D).

    A ``PolicyObject`` bundles deontic clauses and is identified by its
    ``policy_cid`` — the content-addressed hash of its canonical form.

    Attributes:
        clauses: List of deontic ``PolicyClause`` objects.
        version: Policy schema/language version string.
        description: Human-readable description of the policy intent.
    """

    policy_id: str = ""
    clauses: List[PolicyClause] = field(default_factory=list)
    version: str = "v1"
    description: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """Serialise to a plain dict for canonicalisation."""
        return {
            "policy_id": self.policy_id,
            "clauses": [c.to_dict() for c in self.clauses],
            "version": self.version,
            "description": self.description,
        }

    def _get_clauses_by_type(self, clause_type: str) -> List[PolicyClause]:
        return [c for c in self.clauses if c.clause_type == clause_type]

    def get_permissions(self) -> List[PolicyClause]:
        """Return all permission clauses (legacy compatibility API)."""
        return self._get_clauses_by_type("permission")

    def get_prohibitions(self) -> List[PolicyClause]:
        """Return all prohibition clauses (legacy compatibility API)."""
        return self._get_clauses_by_type("prohibition")

    def get_obligations(self) -> List[PolicyClause]:
        """Return all obligation clauses (legacy compatibility API)."""
        return self._get_clauses_by_type("obligation")

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PolicyObject":
        return cls(
            policy_id=data.get("policy_id", ""),
            clauses=[PolicyClause(**c) for c in data.get("clauses", [])],
            version=data.get("version", "v1"),
            description=data.get("description", ""),
        )

    @property
    def policy_cid(self) -> str:
        """Content-addressed CID of this policy object."""
        return artifact_cid(self.to_dict())


# ---------------------------------------------------------------------------
# Factory helpers
# ---------------------------------------------------------------------------

def make_simple_permission_policy(
    actor: Optional[str] = None,
    action: Optional[str] = None,
    *,
    policy_id: str = "",
    allowed_tools: Optional[List[str]] = None,
    resource: Optional[str] = None,
    valid_from: Optional[str] = None,
    valid_until: Optional[str] = None,
    description: str = "",
) -> PolicyObject:
    """Create a minimal permission policy for one actor + action.

    This factory is suitable for testing and simple deployment scenarios.
    It creates a single ``"permission"`` clause.

    Args:
        actor: Agent or role identifier (``"*"`` matches any).
        action: Tool / method name being granted (``"*"`` matches any).
        resource: Optional resource scope.
        valid_from: ISO-8601 UTC start of the permission window.
        valid_until: ISO-8601 UTC end of the permission window.
        description: Human-readable description for the policy.

    Returns:
        A ``PolicyObject`` containing one permission clause.

    Example::

        policy = make_simple_permission_policy(
            actor="did:key:abc123",
            action="repo.status",
            valid_until="2026-12-31T23:59:59Z",
        )
    """
    clauses: List[PolicyClause] = []

    if allowed_tools is not None:
        for tool_name in allowed_tools:
            clauses.append(
                PolicyClause(
                    clause_type="permission",
                    actor=actor or "*",
                    action=tool_name,
                    resource=resource,
                    valid_from=valid_from,
                    valid_until=valid_until,
                )
            )
    else:
        clauses.append(
            PolicyClause(
                clause_type="permission",
                actor=actor or "*",
                action=action or "*",
                resource=resource,
                valid_from=valid_from,
                valid_until=valid_until,
            )
        )

    policy_desc = description
    if not policy_desc:
        if allowed_tools:
            policy_desc = f"Allow {actor or '*'} to call {', '.join(allowed_tools)}"
        else:
            policy_desc = f"Allow {actor or '*'} to call {action or '*'}"

    return PolicyObject(policy_id=policy_id, clauses=clauses, description=policy_desc)


class PolicyClauseType:
    """Legacy enum-like constants for clause types."""

    PERMISSION = "permission"
    PROHIBITION = "prohibition"
    OBLIGATION = "obligation"


# ---------------------------------------------------------------------------
# Policy Evaluator
# ---------------------------------------------------------------------------

def _parse_iso(ts: Optional[Union[str, float, int, datetime]]) -> Optional[datetime]:
    """Parse an ISO-8601 UTC timestamp string into a timezone-aware datetime.

    Args:
        ts: ISO-8601 string, or ``None``.

    Returns:
        A timezone-aware ``datetime`` object, or ``None`` if *ts* is falsy.
    """
    if ts is None:
        return None
    if isinstance(ts, datetime):
        return ts if ts.tzinfo is not None else ts.replace(tzinfo=timezone.utc)
    if isinstance(ts, (int, float)):
        return datetime.fromtimestamp(float(ts), tz=timezone.utc)
    try:
        # Python 3.11+ handles Z suffix; handle manually for ≥3.7
        ts_clean = str(ts).replace("Z", "+00:00")
        return datetime.fromisoformat(ts_clean)
    except ValueError:
        return None


def _clause_matches(
    clause: PolicyClause,
    actor: str,
    action: str,
    resource: Optional[str],
    now: datetime,
) -> bool:
    """Return ``True`` when *clause* applies to the given execution context.

    Args:
        clause: The policy clause to test.
        actor: The acting agent's identifier.
        action: The tool/method name.
        resource: Optional resource identifier.
        now: The evaluation timestamp.

    Returns:
        Whether this clause applies in the current context.
    """
    # Actor check — wildcard matches any
    if clause.actor != "*" and clause.actor != actor:
        return False

    # Action check — wildcard matches any
    if clause.action != "*" and clause.action != action:
        return False

    # Resource check (optional — if clause has no resource, it's unconstrained)
    if clause.resource is not None and resource is not None:
        if clause.resource != resource:
            return False

    # Temporal validity
    valid_from = _parse_iso(clause.valid_from)
    if valid_from and now < valid_from:
        return False

    valid_until = _parse_iso(clause.valid_until)
    if valid_until and now > valid_until:
        return False

    return True


class PolicyEvaluator:
    """Runtime policy evaluator (Profile D).

    Evaluates an ``IntentObject`` against a ``PolicyObject`` and produces a
    ``DecisionObject`` whose verdict is one of:

    - ``"allow"`` — all matching clauses are permissions, no prohibitions
    - ``"deny"`` — at least one prohibition clause matches
    - ``"allow_with_obligations"`` — allowed but with outstanding obligations

    Usage::

        policy = make_simple_permission_policy("alice", "repo.status")
        intent = IntentObject(
            interface_cid="bafy-mock-...",
            tool="repo.status",
            input_cid="bafy-mock-...",
        )
        evaluator = PolicyEvaluator()
        decision = evaluator.evaluate(intent, policy)
        assert decision.decision == "allow"
    """

    def __init__(self) -> None:
        self._policies: Dict[str, PolicyObject] = {}

    def register_policy(self, policy: PolicyObject) -> str:
        """Register a policy and return its CID (legacy compatibility API)."""
        cid = policy.policy_cid
        self._policies[cid] = policy
        return cid

    def evaluate(
        self,
        intent: IntentObject,
        policy: Union[PolicyObject, str],
        *,
        actor: Optional[str] = None,
        resource: Optional[str] = None,
        now: Optional[datetime] = None,
        proofs_checked: Optional[List[str]] = None,
        evaluator_did: Optional[str] = None,
    ) -> DecisionObject:
        """Evaluate an intent against a policy and produce a decision.

        The algorithm is:
        1. For each clause in *policy*, test whether it matches the intent.
        2. If ANY matching clause is a **prohibition**, verdict is ``"deny"``.
        3. If at least one matching clause is a **permission**, check obligations.
        4. If obligation clauses match, verdict is ``"allow_with_obligations"``.
        5. Otherwise verdict is ``"deny"`` (no explicit permission found).

        Args:
            intent: The ``IntentObject`` being evaluated.
            policy: The ``PolicyObject`` containing deontic clauses.
            actor: Override the actor identifier (defaults to ``"*"``).
            resource: Optional resource scope for the action.
            now: Evaluation timestamp (defaults to current UTC time).
            proofs_checked: CIDs of proofs/UCAN chains validated before
                calling this evaluator.
            evaluator_did: DID of the evaluating agent.

        Returns:
            A ``DecisionObject`` with the verdict and any spawned obligations.
        """
        eval_time = now or datetime.now(timezone.utc)
        if isinstance(policy, str):
            policy_obj = self._policies.get(policy)
            if policy_obj is None:
                return DecisionObject(
                    decision="deny",
                    intent_cid=intent.cid,
                    policy_cid=policy,
                    proofs_checked=proofs_checked or [],
                    justification=f"Unknown policy CID: {policy}",
                    obligations=[],
                )
        else:
            policy_obj = policy

        effective_actor = actor or "*"
        effective_resource = resource

        has_permission = False
        obligations: List[Dict[str, Any]] = []
        denial_reasons: List[str] = []

        for clause in policy_obj.clauses:
            if not _clause_matches(clause, effective_actor, intent.tool, effective_resource, eval_time):
                continue

            if clause.clause_type == "prohibition":
                denial_reasons.append(f"Prohibited: actor={effective_actor} action={intent.tool}")
            elif clause.clause_type == "permission":
                has_permission = True
            elif clause.clause_type == "obligation":
                obligations.append(
                    {
                        "type": "obligation",
                        "action": clause.action,
                        "deadline": clause.obligation_deadline or "",
                        "metadata": clause.metadata,
                    }
                )

        # Build verdict
        if denial_reasons:
            verdict = "deny"
            justification = "; ".join(denial_reasons)
        elif has_permission and obligations:
            verdict = "allow_with_obligations"
            justification = f"Permitted with {len(obligations)} obligation(s)"
        elif has_permission:
            verdict = "allow"
            justification = f"Explicit permission for actor={effective_actor} action={intent.tool}"
        else:
            verdict = "deny"
            justification = f"No matching permission for actor={effective_actor} action={intent.tool}"

        return DecisionObject(
            decision=verdict,
            intent_cid=intent.cid,
            policy_cid=policy_obj.policy_cid,
            proofs_checked=proofs_checked or [],
            justification=justification,
            obligations=obligations,
            evaluator_dids=[evaluator_did] if evaluator_did else [],
        )


class _PolicyRegistryMeta(type):
    def __instancecheck__(cls, instance: Any) -> bool:
        if super().__instancecheck__(instance):
            return True
        try:
            from .nl_ucan_policy import PolicyRegistry as _NLPolicyRegistry

            return isinstance(instance, _NLPolicyRegistry)
        except Exception:
            return False


class PolicyRegistry(metaclass=_PolicyRegistryMeta):
    """In-memory policy registry with JSON persistence (legacy compatibility API)."""

    def __init__(self, *, evaluator: Optional[PolicyEvaluator] = None) -> None:
        self.evaluator = evaluator or PolicyEvaluator()
        self._policies: Dict[str, PolicyObject] = {}

    def register(self, policy: PolicyObject) -> str:
        cid = self.evaluator.register_policy(policy)
        self._policies[cid] = policy
        return cid

    def list_policies(self) -> List[Dict[str, str]]:
        return [
            {
                "policy_id": policy.policy_id,
                "policy_cid": cid,
            }
            for cid, policy in self._policies.items()
        ]

    def evaluate(self, intent: IntentObject, policy_cid: str, **kwargs: Any) -> DecisionObject:
        return self.evaluator.evaluate(intent, policy_cid, **kwargs)

    def save(self, path: str) -> None:
        data = []
        for cid, policy in self._policies.items():
            entry = policy.to_dict()
            entry["policy_cid"] = cid
            data.append(entry)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, sort_keys=True)

    def load(self, path: str) -> int:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        count = 0
        for entry in data:
            policy = PolicyObject.from_dict(entry)
            cid = self.register(policy)
            if entry.get("policy_cid") and entry["policy_cid"] != cid:
                self._policies[entry["policy_cid"]] = policy
            count += 1
        return count


# ---------------------------------------------------------------------------
# PolicyRegistry — thin re-export shim for backward compatibility
# ---------------------------------------------------------------------------
# The full implementation lives in nl_ucan_policy.PolicyRegistry.
# This import is deferred to avoid circular dependencies at load time.

_GLOBAL_POLICY_EVALUATOR: Optional[PolicyEvaluator] = None
_GLOBAL_POLICY_REGISTRY: Optional[PolicyRegistry] = None


def get_policy_evaluator() -> PolicyEvaluator:
    """Return process-global policy evaluator singleton."""
    global _GLOBAL_POLICY_EVALUATOR
    if _GLOBAL_POLICY_EVALUATOR is None:
        _GLOBAL_POLICY_EVALUATOR = PolicyEvaluator()
    return _GLOBAL_POLICY_EVALUATOR


def get_policy_registry() -> PolicyRegistry:
    """Return process-global policy registry singleton."""
    try:
        from .nl_ucan_policy import get_policy_registry as _get_nl_policy_registry

        return _get_nl_policy_registry()
    except Exception:
        global _GLOBAL_POLICY_REGISTRY
        if _GLOBAL_POLICY_REGISTRY is None:
            _GLOBAL_POLICY_REGISTRY = PolicyRegistry(evaluator=get_policy_evaluator())
        return _GLOBAL_POLICY_REGISTRY
