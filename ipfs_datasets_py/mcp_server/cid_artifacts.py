"""Profile B: CID-Native Execution Artifacts.

Implements the MCP++ Profile B specification from:
https://github.com/endomorphosis/Mcp-Plus-Plus/blob/main/docs/spec/cid-native-artifacts.md

Every execution step produces a set of immutable, content-addressed (CID-native)
artifacts that provide provenance, auditability, and replay capability:

- ``IntentObject``      — "what I plan to do" (pre-execution)
- ``DecisionObject``    — policy evaluation result
- ``ReceiptObject``     — immutable execution outcome record
- ``ExecutionEnvelope`` — wrapper around an MCP invocation referencing CIDs
- ``EventNode``         — links the above into an append-only Event DAG

The ``artifact_cid()`` helper converts any of these to a content-derived CID.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# CID helper
# ---------------------------------------------------------------------------

def artifact_cid(obj: Any) -> str:
    """Compute a deterministic mock-CID for any JSON-serialisable artifact.

    Uses canonical JSON (sorted keys, no extra whitespace) → SHA-256 hex,
    prefixed with ``"bafy-mock-"`` to make the placeholder origin obvious.

    Args:
        obj: Any JSON-serialisable Python value (dict, list, str, …).

    Returns:
        A stable, content-derived string identifier.

    Example::

        >>> artifact_cid({"tool": "repo.status", "input": {}})
        'bafy-mock-...'
    """
    canonical = json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    digest = hashlib.sha256(canonical.encode()).hexdigest()
    return f"bafy-mock-{digest[:32]}"


def _utcnow() -> str:
    """Return the current UTC time as an ISO-8601 string."""
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Intent Object (Profile B §4)
# ---------------------------------------------------------------------------

@dataclass
class IntentObject:
    """Immutable "what I plan to do" description used for policy evaluation.

    An ``IntentObject`` is content-addressed to an ``intent_cid``.  It is
    created *before* execution and referenced by the downstream decision,
    receipt, and event artifacts.

    Attributes:
        interface_cid: CID of the Interface Descriptor for this tool.
        tool: Stable tool / method name (e.g. ``"repo.status"``).
        input_cid: CID of the canonicalised input parameters.
        correlation_id: Ephemeral nonce or UUID for trace correlation.
        constraints_policy_cid: Optional CID of the narrowed policy for this action.
        expected_output_schema_cid: Optional CID of the expected output schema.
        declared_side_effects: Capability strings or CIDs for declared side-effects.
    """

    interface_cid: str
    tool: str
    input_cid: str
    correlation_id: str = ""
    constraints_policy_cid: Optional[str] = None
    expected_output_schema_cid: Optional[str] = None
    declared_side_effects: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Serialise to a plain dict for canonicalisation / CID derivation."""
        return {
            "interface_cid": self.interface_cid,
            "tool": self.tool,
            "input_cid": self.input_cid,
            "correlation_id": self.correlation_id,
            "constraints_policy_cid": self.constraints_policy_cid,
            "expected_output_schema_cid": self.expected_output_schema_cid,
            "declared_side_effects": self.declared_side_effects,
        }

    @property
    def intent_cid(self) -> str:
        """Content-addressed CID of this intent object."""
        return artifact_cid(self.to_dict())


# ---------------------------------------------------------------------------
# Decision Object (Profile B §5)
# ---------------------------------------------------------------------------

@dataclass
class DecisionObject:
    """Result of policy evaluation at execution time.

    A ``DecisionObject`` is produced by evaluators after verifying proofs and
    evaluating policy against the intent.  It is content-addressed to a
    ``decision_cid``.

    Attributes:
        decision: Verdict — one of ``"allow"``, ``"deny"``,
            ``"allow_with_obligations"``.
        intent_cid: CID of the ``IntentObject`` being evaluated.
        policy_cid: CID of the policy used in this evaluation.
        proofs_checked: CIDs of proofs/UCAN chains validated.
        justification: Human-readable or structured explanation.
        obligations: List of obligation dicts with ``type`` and ``deadline``.
        policy_version: Version string of the policy language/schema.
        evaluator_dids: DID strings of evaluating agents.
    """

    decision: str  # "allow" | "deny" | "allow_with_obligations"
    intent_cid: str
    policy_cid: str
    proofs_checked: List[str] = field(default_factory=list)
    justification: str = ""
    obligations: List[Dict[str, Any]] = field(default_factory=list)
    policy_version: str = "v1"
    evaluator_dids: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Serialise to a plain dict for canonicalisation / CID derivation."""
        return {
            "decision": self.decision,
            "intent_cid": self.intent_cid,
            "policy_cid": self.policy_cid,
            "proofs_checked": self.proofs_checked,
            "justification": self.justification,
            "obligations": self.obligations,
            "policy_version": self.policy_version,
            "evaluator_dids": self.evaluator_dids,
        }

    @property
    def decision_cid(self) -> str:
        """Content-addressed CID of this decision object."""
        return artifact_cid(self.to_dict())


# ---------------------------------------------------------------------------
# Receipt Object (Profile B §6)
# ---------------------------------------------------------------------------

@dataclass
class ReceiptObject:
    """Immutable execution outcome record suitable for audit and disputes.

    A ``ReceiptObject`` is content-addressed to a ``receipt_cid``.

    Attributes:
        intent_cid: CID of the originating intent.
        output_cid: CID of the canonicalised execution output.
        decision_cid: CID of the policy decision that authorised execution.
        observed_side_effects: CIDs or capability strings for actual side effects.
        proofs_checked: CIDs of proofs validated during execution.
        correlation_id: Trace correlation ID (carried from intent).
        time_observed: ISO-8601 UTC timestamp of when execution completed.
    """

    intent_cid: str
    output_cid: str
    decision_cid: str
    observed_side_effects: List[str] = field(default_factory=list)
    proofs_checked: List[str] = field(default_factory=list)
    correlation_id: str = ""
    time_observed: str = field(default_factory=_utcnow)

    def to_dict(self) -> Dict[str, Any]:
        """Serialise to a plain dict for canonicalisation / CID derivation."""
        return {
            "intent_cid": self.intent_cid,
            "output_cid": self.output_cid,
            "decision_cid": self.decision_cid,
            "observed_side_effects": self.observed_side_effects,
            "proofs_checked": self.proofs_checked,
            "correlation_id": self.correlation_id,
            "time_observed": self.time_observed,
        }

    @property
    def receipt_cid(self) -> str:
        """Content-addressed CID of this receipt."""
        return artifact_cid(self.to_dict())


# ---------------------------------------------------------------------------
# Execution Envelope (Profile B §5)
# ---------------------------------------------------------------------------

@dataclass
class ExecutionEnvelope:
    """CID-native wrapper around an MCP invocation (Profile B).

    An ``ExecutionEnvelope`` bundles all pre-execution CIDs needed to form
    a complete, auditable execution record.  Post-execution, add ``output_cid``
    and ``receipt_cid``.

    Attributes:
        interface_cid: Interface Descriptor CID for the tool being called.
        input_cid: CID of the canonicalised input parameters.
        intent_cid: CID of the ``IntentObject`` for this invocation.
        policy_cid: Optional CID of the active policy at invocation time.
        proof_cid: Optional CID of the UCAN/proof bundle.
        parents: CIDs of causally preceding event nodes.
        output_cid: CID of the result (populated post-execution).
        receipt_cid: CID of the ``ReceiptObject`` (populated post-execution).
    """

    interface_cid: str
    input_cid: str
    intent_cid: str
    policy_cid: Optional[str] = None
    proof_cid: Optional[str] = None
    parents: List[str] = field(default_factory=list)
    output_cid: Optional[str] = None
    receipt_cid: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Serialise to a plain dict."""
        return {
            "interface_cid": self.interface_cid,
            "input_cid": self.input_cid,
            "intent_cid": self.intent_cid,
            "policy_cid": self.policy_cid,
            "proof_cid": self.proof_cid,
            "parents": self.parents,
            "output_cid": self.output_cid,
            "receipt_cid": self.receipt_cid,
        }

    @property
    def envelope_cid(self) -> str:
        """Content-addressed CID of this execution envelope."""
        return artifact_cid(self.to_dict())


# ---------------------------------------------------------------------------
# Event Node (Profile B §7 + Event DAG spec)
# ---------------------------------------------------------------------------

@dataclass
class EventNode:
    """A single node in the append-only Event DAG.

    Event nodes link intents, decisions, receipts, and outputs into a causal
    graph suitable for provenance, replay, rollback, and audit.

    Attributes:
        parents: CIDs of causally preceding event nodes (empty for root events).
        interface_cid: Interface Descriptor CID.
        intent_cid: CID of the intent that triggered this event.
        decision_cid: CID of the policy decision.
        output_cid: CID of the execution output.
        receipt_cid: CID of the execution receipt.
        proof_cid: Optional CID of the proof bundle.
        peer_did: Optional DID string of the executing peer.
        timestamp_created: ISO-8601 UTC creation timestamp.
        timestamp_observed: ISO-8601 UTC observation timestamp.
    """

    parents: List[str] = field(default_factory=list)
    interface_cid: str = ""
    intent_cid: str = ""
    decision_cid: str = ""
    output_cid: str = ""
    receipt_cid: str = ""
    proof_cid: Optional[str] = None
    peer_did: Optional[str] = None
    timestamp_created: str = field(default_factory=_utcnow)
    timestamp_observed: str = field(default_factory=_utcnow)

    def to_dict(self) -> Dict[str, Any]:
        """Serialise to a plain dict for canonicalisation / CID derivation."""
        return {
            "parents": self.parents,
            "interface_cid": self.interface_cid,
            "intent_cid": self.intent_cid,
            "decision_cid": self.decision_cid,
            "output_cid": self.output_cid,
            "receipt_cid": self.receipt_cid,
            "proof_cid": self.proof_cid,
            "peer_did": self.peer_did,
            "timestamps": {
                "created": self.timestamp_created,
                "observed": self.timestamp_observed,
            },
        }

    @property
    def event_cid(self) -> str:
        """Content-addressed CID of this event node."""
        return artifact_cid(self.to_dict())
