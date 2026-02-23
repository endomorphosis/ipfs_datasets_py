"""
Profile B: CID-Native Execution Artifacts

Implements the CID-native artifacts from the MCP++ specification:
  https://github.com/endomorphosis/Mcp-Plus-Plus/blob/main/docs/spec/cid-native-artifacts.md

Provides:
- ExecutionEnvelope: wraps an MCP invocation with CID references
- IntentObject: minimal CID'd "what I plan to do"
- DecisionObject: CID'd policy evaluation result
- ReceiptObject: immutable CID'd execution receipt/attestation
- EventNode: DAG node linking intent/decision/receipt
- artifact_cid(): convenience CID helper

Backward-compatible: does not modify MCP JSON-RPC message formats.
"""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional

# Re-use the same canonicalize/compute_cid from interface_descriptor
from .interface_descriptor import _canonicalize, compute_cid


# ─── intent ──────────────────────────────────────────────────────────────────


@dataclass
class IntentObject:
    """
    CID'd "what I plan to do" object (spec §4).

    Required for policy evaluation and later replay.
    """
    tool: str
    input_cid: Optional[str] = None
    interface_cid: Optional[str] = None
    constraints_policy_cid: Optional[str] = None
    correlation_id: Optional[str] = None
    declared_side_effects: List[str] = field(default_factory=list)
    expected_output_schema_cid: Optional[str] = None

    _cid: Optional[str] = field(default=None, repr=False, compare=False)

    @property
    def cid(self) -> str:
        if self._cid is None:
            self._cid = compute_cid(self._canonical_bytes())
        return self._cid

    def _canonical_bytes(self) -> bytes:
        d = {
            "tool": self.tool,
            "input_cid": self.input_cid,
            "interface_cid": self.interface_cid,
            "constraints_policy_cid": self.constraints_policy_cid,
            "correlation_id": self.correlation_id,
            "declared_side_effects": sorted(self.declared_side_effects),
            "expected_output_schema_cid": self.expected_output_schema_cid,
        }
        return _canonicalize(d)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "intent_cid": self.cid,
            "tool": self.tool,
            "input_cid": self.input_cid,
            "interface_cid": self.interface_cid,
            "constraints_policy_cid": self.constraints_policy_cid,
            "correlation_id": self.correlation_id,
            "declared_side_effects": self.declared_side_effects,
        }


# ─── decision ────────────────────────────────────────────────────────────────


ALLOW = "allow"
DENY = "deny"
ALLOW_WITH_OBLIGATIONS = "allow_with_obligations"


@dataclass
class Obligation:
    """A spawned obligation from a policy decision."""
    type: str
    deadline: Optional[str] = None
    details: Optional[Dict[str, Any]] = None


@dataclass
class DecisionObject:
    """
    CID'd policy evaluation result (spec §5).

    Produced by evaluators after verifying proofs and evaluating policy.
    """
    decision: str  # ALLOW | DENY | ALLOW_WITH_OBLIGATIONS
    intent_cid: str
    policy_cid: Optional[str] = None
    proofs_checked: List[str] = field(default_factory=list)
    obligations: List[Obligation] = field(default_factory=list)
    justification: Optional[str] = None
    policy_version: str = "v1"
    evaluation_witness_cid: Optional[str] = None

    _cid: Optional[str] = field(default=None, repr=False, compare=False)

    @property
    def cid(self) -> str:
        if self._cid is None:
            self._cid = compute_cid(self._canonical_bytes())
        return self._cid

    def _canonical_bytes(self) -> bytes:
        d = {
            "decision": self.decision,
            "intent_cid": self.intent_cid,
            "policy_cid": self.policy_cid,
            "proofs_checked": sorted(self.proofs_checked),
            "obligations": [
                {"type": o.type, "deadline": o.deadline}
                for o in sorted(self.obligations, key=lambda x: x.type)
            ],
            "justification": self.justification,
            "policy_version": self.policy_version,
        }
        return _canonicalize(d)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "decision_cid": self.cid,
            "decision": self.decision,
            "intent_cid": self.intent_cid,
            "policy_cid": self.policy_cid,
            "proofs_checked": self.proofs_checked,
            "obligations": [
                {"type": o.type, "deadline": o.deadline}
                for o in self.obligations
            ],
            "justification": self.justification,
            "policy_version": self.policy_version,
        }

    @property
    def is_allowed(self) -> bool:
        return self.decision in (ALLOW, ALLOW_WITH_OBLIGATIONS)


# ─── receipt ─────────────────────────────────────────────────────────────────


@dataclass
class ReceiptObject:
    """
    Immutable CID'd execution receipt (spec §6).

    Audit substrate for disputes, rollbacks, and risk scoring.
    """
    intent_cid: str
    output_cid: Optional[str] = None
    decision_cid: Optional[str] = None
    observed_side_effects: List[str] = field(default_factory=list)
    proofs_checked: List[str] = field(default_factory=list)
    correlation_id: Optional[str] = None
    time_observed: Optional[str] = None

    _cid: Optional[str] = field(default=None, repr=False, compare=False)

    @property
    def cid(self) -> str:
        if self._cid is None:
            self._cid = compute_cid(self._canonical_bytes())
        return self._cid

    def _canonical_bytes(self) -> bytes:
        d = {
            "intent_cid": self.intent_cid,
            "output_cid": self.output_cid,
            "decision_cid": self.decision_cid,
            "observed_side_effects": sorted(self.observed_side_effects),
            "proofs_checked": sorted(self.proofs_checked),
            "correlation_id": self.correlation_id,
            "time_observed": self.time_observed,
        }
        return _canonicalize(d)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "receipt_cid": self.cid,
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
