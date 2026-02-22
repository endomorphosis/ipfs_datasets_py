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
from typing import Any, Dict, List, Optional

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

    clauses: List[PolicyClause] = field(default_factory=list)
    version: str = "v1"
    description: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """Serialise to a plain dict for canonicalisation."""
        return {
            "clauses": [c.to_dict() for c in self.clauses],
            "version": self.version,
            "description": self.description,
        }

    @property
    def policy_cid(self) -> str:
        """Content-addressed CID of this policy object."""
        return artifact_cid(self.to_dict())


# ---------------------------------------------------------------------------
# Factory helpers
# ---------------------------------------------------------------------------

def make_simple_permission_policy(
    actor: str,
    action: str,
    *,
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
    clause = PolicyClause(
        clause_type="permission",
        actor=actor,
        action=action,
        resource=resource,
        valid_from=valid_from,
        valid_until=valid_until,
    )
    return PolicyObject(clauses=[clause], description=description or f"Allow {actor} to call {action}")


# ---------------------------------------------------------------------------
# Policy Evaluator
# ---------------------------------------------------------------------------

def _parse_iso(ts: Optional[str]) -> Optional[datetime]:
    """Parse an ISO-8601 UTC timestamp string into a timezone-aware datetime.

    Args:
        ts: ISO-8601 string, or ``None``.

    Returns:
        A timezone-aware ``datetime`` object, or ``None`` if *ts* is falsy.
    """
    if not ts:
        return None
    try:
        # Python 3.11+ handles Z suffix; handle manually for ≥3.7
        ts_clean = ts.replace("Z", "+00:00")
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

    def evaluate(
        self,
        intent: IntentObject,
        policy: PolicyObject,
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
        effective_actor = actor or "*"
        effective_resource = resource

        has_permission = False
        obligations: List[Dict[str, Any]] = []
        denial_reasons: List[str] = []

        for clause in policy.clauses:
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
            intent_cid=intent.intent_cid,
            policy_cid=policy.policy_cid,
            proofs_checked=proofs_checked or [],
            justification=justification,
            obligations=obligations,
            evaluator_dids=[evaluator_did] if evaluator_did else [],
        )


# ---------------------------------------------------------------------------
# PolicyRegistry — thin re-export shim for backward compatibility
# ---------------------------------------------------------------------------
# The full implementation lives in nl_ucan_policy.PolicyRegistry.
# This import is deferred to avoid circular dependencies at load time.

def get_policy_registry() -> "PolicyRegistry":
    """Return the global :class:`~nl_ucan_policy.PolicyRegistry` singleton.

    This is a convenience re-export so callers can obtain the registry from
    either ``temporal_policy`` or ``nl_ucan_policy``.

    Returns:
        The singleton :class:`~nl_ucan_policy.PolicyRegistry` instance.
    """
    from .nl_ucan_policy import (  # noqa: PLC0415
        PolicyRegistry,
        get_policy_registry as _get,
    )
    return _get()
