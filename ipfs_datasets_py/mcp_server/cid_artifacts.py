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
            "correlation_id": self.correlation_id,
            "time_observed": self.time_observed,
        }


# ─── execution envelope ──────────────────────────────────────────────────────


@dataclass
class ExecutionEnvelope:
    """
    CID-native wrapper around an MCP invocation (Profile B: spec §2).

    Carries CID references for audit, provenance, and policy evaluation
    without changing the MCP JSON-RPC payload.
    """
    interface_cid: Optional[str] = None
    input_cid: Optional[str] = None
    intent_cid: Optional[str] = None
    policy_cid: Optional[str] = None
    proof_cid: Optional[str] = None
    parents: List[str] = field(default_factory=list)

    # Output fields (filled after execution)
    output_cid: Optional[str] = None
    receipt_cid: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
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

    def is_complete(self) -> bool:
        """True if both output and receipt CIDs have been set."""
        return self.output_cid is not None and self.receipt_cid is not None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ExecutionEnvelope":
        return cls(
            interface_cid=data.get("interface_cid"),
            input_cid=data.get("input_cid"),
            intent_cid=data.get("intent_cid"),
            policy_cid=data.get("policy_cid"),
            proof_cid=data.get("proof_cid"),
            parents=data.get("parents", []),
            output_cid=data.get("output_cid"),
            receipt_cid=data.get("receipt_cid"),
        )


# ─── event node ──────────────────────────────────────────────────────────────


@dataclass
class EventNode:
    """
    Append-only DAG node (spec §7).

    Each event CID commits to intent, interface, proofs, decision, outputs,
    parents — enabling causal traversal, replay, and attribution.
    """
    intent_cid: str
    parents: List[str] = field(default_factory=list)
    interface_cid: Optional[str] = None
    proof_cid: Optional[str] = None
    decision_cid: Optional[str] = None
    output_cid: Optional[str] = None
    receipt_cid: Optional[str] = None
    peer_did: Optional[str] = None
    timestamp_created: Optional[str] = None

    _cid: Optional[str] = field(default=None, repr=False, compare=False)

    @property
    def cid(self) -> str:
        if self._cid is None:
            self._cid = compute_cid(self._canonical_bytes())
        return self._cid

    def _canonical_bytes(self) -> bytes:
        d = {
            "intent_cid": self.intent_cid,
            "parents": sorted(self.parents),
            "interface_cid": self.interface_cid,
            "proof_cid": self.proof_cid,
            "decision_cid": self.decision_cid,
            "output_cid": self.output_cid,
            "receipt_cid": self.receipt_cid,
            "peer_did": self.peer_did,
            "timestamp_created": self.timestamp_created,
        }
        return _canonicalize(d)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_cid": self.cid,
            "intent_cid": self.intent_cid,
            "parents": self.parents,
            "interface_cid": self.interface_cid,
            "proof_cid": self.proof_cid,
            "decision_cid": self.decision_cid,
            "output_cid": self.output_cid,
            "receipt_cid": self.receipt_cid,
            "peer_did": self.peer_did,
        }


# ─── convenience ─────────────────────────────────────────────────────────────


def artifact_cid(data: Any) -> str:
    """Compute a CID from an arbitrary JSON-serialisable object."""
    return compute_cid(_canonicalize(data))
