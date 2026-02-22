"""Session 50 — MCP++ spec alignment tests.

Tests for four new modules aligned to the MCP++ specification:
  - interface_descriptor.py  (Profile A: MCP-IDL)
  - cid_artifacts.py         (Profile B: CID-Native Execution Artifacts)
  - temporal_policy.py       (Profile D: Temporal Deontic Policy Evaluation)
  - event_dag.py             (Event DAG, Concurrency, and Ordering)

Reference spec:
  https://github.com/endomorphosis/Mcp-Plus-Plus/blob/main/docs/spec/mcp++-profiles-draft.md
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

import pytest


# ============================================================
# Profile A: interface_descriptor.py
# ============================================================

class TestArtifactCid:
    """artifact_cid() / _canonical_cid() shared behaviour."""

    def test_canonical_cid_deterministic(self) -> None:
        from ipfs_datasets_py.mcp_server.interface_descriptor import _canonical_cid
        a = _canonical_cid({"b": 2, "a": 1})
        b = _canonical_cid({"a": 1, "b": 2})
        assert a == b, "CID must be key-order independent"

    def test_canonical_cid_prefix(self) -> None:
        from ipfs_datasets_py.mcp_server.interface_descriptor import _canonical_cid
        cid = _canonical_cid({"x": 1})
        assert cid.startswith("bafy-mock-")

    def test_canonical_cid_different_content(self) -> None:
        from ipfs_datasets_py.mcp_server.interface_descriptor import _canonical_cid
        assert _canonical_cid({"a": 1}) != _canonical_cid({"a": 2})

    def test_canonical_cid_length(self) -> None:
        from ipfs_datasets_py.mcp_server.interface_descriptor import _canonical_cid
        cid = _canonical_cid({})
        # "bafy-mock-" + 32 hex chars
        assert len(cid) == len("bafy-mock-") + 32


class TestMethodSignature:
    def test_defaults(self) -> None:
        from ipfs_datasets_py.mcp_server.interface_descriptor import MethodSignature
        m = MethodSignature(name="repo.status")
        assert m.input_schema == {}
        assert m.output_schema == {}
        assert m.error_names == []

    def test_custom(self) -> None:
        from ipfs_datasets_py.mcp_server.interface_descriptor import MethodSignature
        m = MethodSignature(
            name="repo.clone",
            input_schema={"url": "string"},
            output_schema={"path": "string"},
            error_names=["NotFound"],
        )
        assert m.name == "repo.clone"
        assert "NotFound" in m.error_names


class TestCompatibilityInfo:
    def test_defaults(self) -> None:
        from ipfs_datasets_py.mcp_server.interface_descriptor import CompatibilityInfo
        c = CompatibilityInfo()
        assert c.compatible_with == []
        assert c.supersedes == []

    def test_custom(self) -> None:
        from ipfs_datasets_py.mcp_server.interface_descriptor import CompatibilityInfo
        c = CompatibilityInfo(compatible_with=["bafy-abc"], supersedes=["bafy-old"])
        assert "bafy-abc" in c.compatible_with
        assert "bafy-old" in c.supersedes


class TestInterfaceDescriptor:
    def _make(self) -> Any:
        from ipfs_datasets_py.mcp_server.interface_descriptor import (
            InterfaceDescriptor, MethodSignature, CompatibilityInfo,
        )
        return InterfaceDescriptor(
            name="git",
            namespace="com.example.tools",
            version="1.0.0",
            methods=[MethodSignature(name="repo.status")],
            errors=["NotFound"],
            requires=["mcp++/cid-envelope"],
            compatibility=CompatibilityInfo(compatible_with=["bafy-old"]),
            semantic_tags=["vcs"],
        )

    def test_required_fields(self) -> None:
        d = self._make()
        assert d.name == "git"
        assert d.namespace == "com.example.tools"
        assert d.version == "1.0.0"

    def test_to_dict_contains_all_keys(self) -> None:
        d = self._make()
        dd = d.to_dict()
        for key in ("name", "namespace", "version", "methods", "errors", "requires", "compatibility"):
            assert key in dd, f"Missing key: {key}"

    def test_interface_cid_is_stable(self) -> None:
        d = self._make()
        cid1 = d.interface_cid
        cid2 = d.interface_cid
        assert cid1 == cid2

    def test_different_descriptors_different_cids(self) -> None:
        from ipfs_datasets_py.mcp_server.interface_descriptor import InterfaceDescriptor
        d1 = InterfaceDescriptor(name="a", namespace="ns", version="1.0.0")
        d2 = InterfaceDescriptor(name="b", namespace="ns", version="1.0.0")
        assert d1.interface_cid != d2.interface_cid

    def test_minimal_descriptor(self) -> None:
        from ipfs_datasets_py.mcp_server.interface_descriptor import InterfaceDescriptor
        d = InterfaceDescriptor(name="tool", namespace="ns", version="1.0.0")
        assert d.interface_cid.startswith("bafy-mock-")


class TestInterfaceRepository:
    def test_register_and_list(self) -> None:
        from ipfs_datasets_py.mcp_server.interface_descriptor import (
            InterfaceDescriptor, InterfaceRepository,
        )
        repo = InterfaceRepository()
        desc = InterfaceDescriptor(name="git", namespace="ns", version="1.0.0")
        cid = repo.register(desc)
        assert cid in repo.list()
        assert len(repo) == 1

    def test_get_existing(self) -> None:
        from ipfs_datasets_py.mcp_server.interface_descriptor import (
            InterfaceDescriptor, InterfaceRepository,
        )
        repo = InterfaceRepository()
        desc = InterfaceDescriptor(name="git", namespace="ns", version="1.0.0")
        cid = repo.register(desc)
        fetched = repo.get(cid)
        assert fetched is desc

    def test_get_missing_returns_none(self) -> None:
        from ipfs_datasets_py.mcp_server.interface_descriptor import InterfaceRepository
        repo = InterfaceRepository()
        assert repo.get("bafy-nonexistent") is None

    def test_check_compat_direct_match(self) -> None:
        from ipfs_datasets_py.mcp_server.interface_descriptor import (
            InterfaceDescriptor, InterfaceRepository,
        )
        repo = InterfaceRepository()
        desc = InterfaceDescriptor(name="git", namespace="ns", version="1.0.0")
        cid = repo.register(desc)
        verdict = repo.check_compat(cid)
        assert verdict.compatible is True

    def test_check_compat_missing_capability(self) -> None:
        from ipfs_datasets_py.mcp_server.interface_descriptor import (
            InterfaceDescriptor, InterfaceRepository,
        )
        repo = InterfaceRepository()
        desc = InterfaceDescriptor(
            name="git", namespace="ns", version="1.0.0",
            requires=["mcp++/ucan"],
        )
        cid = repo.register(desc)
        verdict = repo.check_compat(cid, local_capabilities=[])
        assert verdict.compatible is False
        assert "mcp++/ucan" in verdict.requires_missing

    def test_check_compat_satisfied_capability(self) -> None:
        from ipfs_datasets_py.mcp_server.interface_descriptor import (
            InterfaceDescriptor, InterfaceRepository,
        )
        repo = InterfaceRepository()
        desc = InterfaceDescriptor(
            name="git", namespace="ns", version="1.0.0",
            requires=["mcp++/ucan"],
        )
        cid = repo.register(desc)
        verdict = repo.check_compat(cid, local_capabilities=["mcp++/ucan"])
        assert verdict.compatible is True

    def test_check_compat_unknown_cid(self) -> None:
        from ipfs_datasets_py.mcp_server.interface_descriptor import InterfaceRepository
        repo = InterfaceRepository()
        verdict = repo.check_compat("bafy-unknown")
        assert verdict.compatible is False
        assert "not found" in verdict.reasons[0].lower()

    def test_check_compat_via_compatible_with(self) -> None:
        from ipfs_datasets_py.mcp_server.interface_descriptor import (
            InterfaceDescriptor, InterfaceRepository, CompatibilityInfo,
        )
        repo = InterfaceRepository()
        old_cid = "bafy-mock-old-interface"
        desc = InterfaceDescriptor(
            name="git", namespace="ns", version="2.0.0",
            compatibility=CompatibilityInfo(compatible_with=[old_cid]),
        )
        repo.register(desc)
        verdict = repo.check_compat(old_cid)
        assert verdict.compatible is True

    def test_toolset_slice_no_filter(self) -> None:
        from ipfs_datasets_py.mcp_server.interface_descriptor import (
            InterfaceDescriptor, InterfaceRepository,
        )
        repo = InterfaceRepository()
        for i in range(5):
            repo.register(InterfaceDescriptor(name=f"t{i}", namespace="ns", version="1.0.0"))
        result = repo.toolset_slice()
        assert len(result) == 5

    def test_toolset_slice_budget(self) -> None:
        from ipfs_datasets_py.mcp_server.interface_descriptor import (
            InterfaceDescriptor, InterfaceRepository,
        )
        repo = InterfaceRepository()
        for i in range(10):
            repo.register(InterfaceDescriptor(name=f"t{i}", namespace="ns", version="1.0.0"))
        result = repo.toolset_slice(budget=3)
        assert len(result) == 3

    def test_toolset_slice_semantic_tags(self) -> None:
        from ipfs_datasets_py.mcp_server.interface_descriptor import (
            InterfaceDescriptor, InterfaceRepository,
        )
        repo = InterfaceRepository()
        repo.register(InterfaceDescriptor(name="git", namespace="ns", version="1.0.0", semantic_tags=["vcs"]))
        repo.register(InterfaceDescriptor(name="s3", namespace="ns", version="1.0.0", semantic_tags=["storage"]))
        result = repo.toolset_slice(semantic_tags=["vcs"])
        assert len(result) == 1

    def test_toolset_slice_required_capabilities(self) -> None:
        from ipfs_datasets_py.mcp_server.interface_descriptor import (
            InterfaceDescriptor, InterfaceRepository,
        )
        repo = InterfaceRepository()
        repo.register(InterfaceDescriptor(name="free", namespace="ns", version="1.0.0", requires=[]))
        repo.register(InterfaceDescriptor(name="ucan", namespace="ns", version="1.0.0", requires=["mcp++/ucan"]))
        # Caller only has no capabilities — should only get "free"
        result = repo.toolset_slice(required_capabilities=[])
        assert len(result) == 1


# ============================================================
# Profile B: cid_artifacts.py
# ============================================================

class TestArtifactCidHelper:
    def test_deterministic(self) -> None:
        from ipfs_datasets_py.mcp_server.cid_artifacts import artifact_cid
        a = artifact_cid({"z": 0, "a": 1})
        b = artifact_cid({"a": 1, "z": 0})
        assert a == b

    def test_prefix(self) -> None:
        from ipfs_datasets_py.mcp_server.cid_artifacts import artifact_cid
        assert artifact_cid({}).startswith("bafy-mock-")

    def test_distinct_for_different_values(self) -> None:
        from ipfs_datasets_py.mcp_server.cid_artifacts import artifact_cid
        assert artifact_cid({"v": 1}) != artifact_cid({"v": 2})


class TestIntentObject:
    def _make(self) -> Any:
        from ipfs_datasets_py.mcp_server.cid_artifacts import IntentObject
        return IntentObject(
            interface_cid="bafy-mock-iface",
            tool="repo.status",
            input_cid="bafy-mock-input",
            correlation_id="uuid-1",
        )

    def test_fields(self) -> None:
        obj = self._make()
        assert obj.tool == "repo.status"
        assert obj.correlation_id == "uuid-1"

    def test_intent_cid_stable(self) -> None:
        obj = self._make()
        assert obj.intent_cid == obj.intent_cid

    def test_intent_cid_prefix(self) -> None:
        assert self._make().intent_cid.startswith("bafy-mock-")

    def test_to_dict_keys(self) -> None:
        d = self._make().to_dict()
        for k in ("interface_cid", "tool", "input_cid", "correlation_id"):
            assert k in d

    def test_different_tools_different_cids(self) -> None:
        from ipfs_datasets_py.mcp_server.cid_artifacts import IntentObject
        a = IntentObject(interface_cid="x", tool="a", input_cid="y")
        b = IntentObject(interface_cid="x", tool="b", input_cid="y")
        assert a.intent_cid != b.intent_cid


class TestDecisionObject:
    def test_allow_verdict(self) -> None:
        from ipfs_datasets_py.mcp_server.cid_artifacts import DecisionObject
        d = DecisionObject(decision="allow", intent_cid="bafy-i", policy_cid="bafy-p")
        assert d.decision == "allow"

    def test_decision_cid_prefix(self) -> None:
        from ipfs_datasets_py.mcp_server.cid_artifacts import DecisionObject
        d = DecisionObject(decision="deny", intent_cid="bafy-i", policy_cid="bafy-p")
        assert d.decision_cid.startswith("bafy-mock-")

    def test_decision_cid_stable(self) -> None:
        from ipfs_datasets_py.mcp_server.cid_artifacts import DecisionObject
        d = DecisionObject(decision="allow", intent_cid="bafy-i", policy_cid="bafy-p")
        assert d.decision_cid == d.decision_cid

    def test_to_dict_contains_obligations(self) -> None:
        from ipfs_datasets_py.mcp_server.cid_artifacts import DecisionObject
        d = DecisionObject(
            decision="allow_with_obligations",
            intent_cid="bafy-i", policy_cid="bafy-p",
            obligations=[{"type": "produce_receipt", "deadline": "2026-12-31"}],
        )
        assert d.to_dict()["obligations"][0]["type"] == "produce_receipt"


class TestReceiptObject:
    def test_fields(self) -> None:
        from ipfs_datasets_py.mcp_server.cid_artifacts import ReceiptObject
        r = ReceiptObject(intent_cid="bafy-i", output_cid="bafy-o", decision_cid="bafy-d")
        assert r.intent_cid == "bafy-i"

    def test_receipt_cid_prefix(self) -> None:
        from ipfs_datasets_py.mcp_server.cid_artifacts import ReceiptObject
        r = ReceiptObject(intent_cid="bafy-i", output_cid="bafy-o", decision_cid="bafy-d")
        assert r.receipt_cid.startswith("bafy-mock-")

    def test_time_observed_auto_set(self) -> None:
        from ipfs_datasets_py.mcp_server.cid_artifacts import ReceiptObject
        r = ReceiptObject(intent_cid="bafy-i", output_cid="bafy-o", decision_cid="bafy-d")
        assert r.time_observed  # non-empty

    def test_to_dict_contains_correlation_id(self) -> None:
        from ipfs_datasets_py.mcp_server.cid_artifacts import ReceiptObject
        r = ReceiptObject(intent_cid="i", output_cid="o", decision_cid="d", correlation_id="x")
        assert r.to_dict()["correlation_id"] == "x"


class TestExecutionEnvelope:
    def test_fields(self) -> None:
        from ipfs_datasets_py.mcp_server.cid_artifacts import ExecutionEnvelope
        e = ExecutionEnvelope(
            interface_cid="bafy-iface",
            input_cid="bafy-input",
            intent_cid="bafy-intent",
        )
        assert e.policy_cid is None
        assert e.output_cid is None

    def test_envelope_cid_stable(self) -> None:
        from ipfs_datasets_py.mcp_server.cid_artifacts import ExecutionEnvelope
        e = ExecutionEnvelope(interface_cid="x", input_cid="y", intent_cid="z")
        assert e.envelope_cid == e.envelope_cid

    def test_to_dict_keys(self) -> None:
        from ipfs_datasets_py.mcp_server.cid_artifacts import ExecutionEnvelope
        e = ExecutionEnvelope(interface_cid="x", input_cid="y", intent_cid="z")
        d = e.to_dict()
        for k in ("interface_cid", "input_cid", "intent_cid", "parents"):
            assert k in d


class TestEventNode:
    def test_fields(self) -> None:
        from ipfs_datasets_py.mcp_server.cid_artifacts import EventNode
        node = EventNode(
            parents=["bafy-parent"],
            interface_cid="bafy-iface",
            intent_cid="bafy-intent",
        )
        assert node.parents == ["bafy-parent"]

    def test_event_cid_prefix(self) -> None:
        from ipfs_datasets_py.mcp_server.cid_artifacts import EventNode
        node = EventNode()
        assert node.event_cid.startswith("bafy-mock-")

    def test_event_cid_differs_when_parents_differ(self) -> None:
        from ipfs_datasets_py.mcp_server.cid_artifacts import EventNode
        a = EventNode(parents=[], intent_cid="same")
        b = EventNode(parents=["bafy-x"], intent_cid="same")
        assert a.event_cid != b.event_cid

    def test_to_dict_timestamps(self) -> None:
        from ipfs_datasets_py.mcp_server.cid_artifacts import EventNode
        node = EventNode()
        d = node.to_dict()
        assert "created" in d["timestamps"]
        assert "observed" in d["timestamps"]


# ============================================================
# Profile D: temporal_policy.py
# ============================================================

class TestPolicyClause:
    def test_defaults(self) -> None:
        from ipfs_datasets_py.mcp_server.temporal_policy import PolicyClause
        c = PolicyClause(clause_type="permission")
        assert c.actor == "*"
        assert c.action == "*"
        assert c.resource is None

    def test_to_dict_keys(self) -> None:
        from ipfs_datasets_py.mcp_server.temporal_policy import PolicyClause
        d = PolicyClause(clause_type="prohibition", actor="alice", action="delete").to_dict()
        for k in ("clause_type", "actor", "action", "resource", "valid_from", "valid_until"):
            assert k in d


class TestPolicyObject:
    def test_policy_cid_stable(self) -> None:
        from ipfs_datasets_py.mcp_server.temporal_policy import PolicyObject, PolicyClause
        p = PolicyObject(clauses=[PolicyClause(clause_type="permission")])
        assert p.policy_cid == p.policy_cid

    def test_policy_cid_prefix(self) -> None:
        from ipfs_datasets_py.mcp_server.temporal_policy import PolicyObject
        p = PolicyObject()
        assert p.policy_cid.startswith("bafy-mock-")

    def test_to_dict_has_clauses(self) -> None:
        from ipfs_datasets_py.mcp_server.temporal_policy import PolicyObject, PolicyClause
        p = PolicyObject(clauses=[PolicyClause(clause_type="obligation")])
        d = p.to_dict()
        assert len(d["clauses"]) == 1
        assert d["clauses"][0]["clause_type"] == "obligation"


class TestMakeSimplePermissionPolicy:
    def test_creates_permission_clause(self) -> None:
        from ipfs_datasets_py.mcp_server.temporal_policy import make_simple_permission_policy
        p = make_simple_permission_policy("alice", "repo.status")
        assert len(p.clauses) == 1
        assert p.clauses[0].clause_type == "permission"
        assert p.clauses[0].actor == "alice"
        assert p.clauses[0].action == "repo.status"

    def test_with_time_window(self) -> None:
        from ipfs_datasets_py.mcp_server.temporal_policy import make_simple_permission_policy
        p = make_simple_permission_policy(
            "*", "read",
            valid_from="2026-01-01T00:00:00Z",
            valid_until="2026-12-31T23:59:59Z",
        )
        assert p.clauses[0].valid_until == "2026-12-31T23:59:59Z"

    def test_description_auto_generated(self) -> None:
        from ipfs_datasets_py.mcp_server.temporal_policy import make_simple_permission_policy
        p = make_simple_permission_policy("bob", "write")
        assert "bob" in p.description or "write" in p.description

    def test_returns_policy_object(self) -> None:
        from ipfs_datasets_py.mcp_server.temporal_policy import (
            make_simple_permission_policy, PolicyObject,
        )
        p = make_simple_permission_policy("*", "*")
        assert isinstance(p, PolicyObject)


class TestPolicyEvaluatorAllow:
    def _setup(self) -> Any:
        from ipfs_datasets_py.mcp_server.temporal_policy import (
            make_simple_permission_policy, PolicyEvaluator,
        )
        from ipfs_datasets_py.mcp_server.cid_artifacts import IntentObject
        policy = make_simple_permission_policy("alice", "repo.status")
        intent = IntentObject(
            interface_cid="bafy-iface",
            tool="repo.status",
            input_cid="bafy-input",
        )
        evaluator = PolicyEvaluator()
        return policy, intent, evaluator

    def test_allow_when_permission_matches(self) -> None:
        policy, intent, evaluator = self._setup()
        decision = evaluator.evaluate(intent, policy, actor="alice")
        assert decision.decision == "allow"

    def test_decision_cid_set(self) -> None:
        policy, intent, evaluator = self._setup()
        decision = evaluator.evaluate(intent, policy, actor="alice")
        assert decision.decision_cid.startswith("bafy-mock-")

    def test_intent_cid_in_decision(self) -> None:
        policy, intent, evaluator = self._setup()
        decision = evaluator.evaluate(intent, policy, actor="alice")
        assert decision.intent_cid == intent.intent_cid

    def test_policy_cid_in_decision(self) -> None:
        policy, intent, evaluator = self._setup()
        decision = evaluator.evaluate(intent, policy, actor="alice")
        assert decision.policy_cid == policy.policy_cid

    def test_wildcard_actor_allows_any(self) -> None:
        from ipfs_datasets_py.mcp_server.temporal_policy import (
            make_simple_permission_policy, PolicyEvaluator,
        )
        from ipfs_datasets_py.mcp_server.cid_artifacts import IntentObject
        policy = make_simple_permission_policy("*", "repo.status")
        intent = IntentObject(interface_cid="x", tool="repo.status", input_cid="y")
        evaluator = PolicyEvaluator()
        decision = evaluator.evaluate(intent, policy, actor="carol")
        assert decision.decision == "allow"


class TestPolicyEvaluatorDeny:
    def test_deny_when_actor_mismatch(self) -> None:
        from ipfs_datasets_py.mcp_server.temporal_policy import (
            make_simple_permission_policy, PolicyEvaluator,
        )
        from ipfs_datasets_py.mcp_server.cid_artifacts import IntentObject
        policy = make_simple_permission_policy("alice", "repo.status")
        intent = IntentObject(interface_cid="x", tool="repo.status", input_cid="y")
        evaluator = PolicyEvaluator()
        decision = evaluator.evaluate(intent, policy, actor="eve")
        assert decision.decision == "deny"

    def test_deny_when_action_mismatch(self) -> None:
        from ipfs_datasets_py.mcp_server.temporal_policy import (
            make_simple_permission_policy, PolicyEvaluator,
        )
        from ipfs_datasets_py.mcp_server.cid_artifacts import IntentObject
        policy = make_simple_permission_policy("alice", "repo.status")
        intent = IntentObject(interface_cid="x", tool="repo.delete", input_cid="y")
        evaluator = PolicyEvaluator()
        decision = evaluator.evaluate(intent, policy, actor="alice")
        assert decision.decision == "deny"

    def test_deny_when_prohibition_matches(self) -> None:
        from ipfs_datasets_py.mcp_server.temporal_policy import (
            PolicyEvaluator, PolicyObject, PolicyClause,
        )
        from ipfs_datasets_py.mcp_server.cid_artifacts import IntentObject
        policy = PolicyObject(clauses=[
            PolicyClause(clause_type="permission", actor="*", action="*"),
            PolicyClause(clause_type="prohibition", actor="*", action="repo.delete"),
        ])
        intent = IntentObject(interface_cid="x", tool="repo.delete", input_cid="y")
        evaluator = PolicyEvaluator()
        decision = evaluator.evaluate(intent, policy, actor="alice")
        assert decision.decision == "deny"

    def test_deny_when_expired_valid_until(self) -> None:
        from ipfs_datasets_py.mcp_server.temporal_policy import (
            PolicyEvaluator, PolicyObject, PolicyClause,
        )
        from ipfs_datasets_py.mcp_server.cid_artifacts import IntentObject
        policy = PolicyObject(clauses=[
            PolicyClause(
                clause_type="permission",
                actor="*", action="*",
                valid_until="2020-01-01T00:00:00Z",  # in the past
            ),
        ])
        intent = IntentObject(interface_cid="x", tool="read", input_cid="y")
        evaluator = PolicyEvaluator()
        decision = evaluator.evaluate(intent, policy)
        assert decision.decision == "deny"

    def test_deny_when_not_yet_valid(self) -> None:
        from ipfs_datasets_py.mcp_server.temporal_policy import (
            PolicyEvaluator, PolicyObject, PolicyClause,
        )
        from ipfs_datasets_py.mcp_server.cid_artifacts import IntentObject
        far_future = "2099-01-01T00:00:00Z"
        policy = PolicyObject(clauses=[
            PolicyClause(clause_type="permission", actor="*", action="*", valid_from=far_future),
        ])
        intent = IntentObject(interface_cid="x", tool="read", input_cid="y")
        evaluator = PolicyEvaluator()
        decision = evaluator.evaluate(intent, policy)
        assert decision.decision == "deny"


class TestPolicyEvaluatorObligations:
    def test_allow_with_obligations(self) -> None:
        from ipfs_datasets_py.mcp_server.temporal_policy import (
            PolicyEvaluator, PolicyObject, PolicyClause,
        )
        from ipfs_datasets_py.mcp_server.cid_artifacts import IntentObject
        policy = PolicyObject(clauses=[
            PolicyClause(clause_type="permission", actor="*", action="read"),
            PolicyClause(
                clause_type="obligation",
                actor="*", action="*",
                obligation_deadline="2026-12-31T23:59:59Z",
            ),
        ])
        intent = IntentObject(interface_cid="x", tool="read", input_cid="y")
        evaluator = PolicyEvaluator()
        decision = evaluator.evaluate(intent, policy)
        assert decision.decision == "allow_with_obligations"
        assert len(decision.obligations) == 1
        assert decision.obligations[0]["deadline"] == "2026-12-31T23:59:59Z"

    def test_proofs_checked_recorded(self) -> None:
        from ipfs_datasets_py.mcp_server.temporal_policy import (
            make_simple_permission_policy, PolicyEvaluator,
        )
        from ipfs_datasets_py.mcp_server.cid_artifacts import IntentObject
        policy = make_simple_permission_policy("*", "*")
        intent = IntentObject(interface_cid="x", tool="t", input_cid="y")
        evaluator = PolicyEvaluator()
        decision = evaluator.evaluate(intent, policy, proofs_checked=["bafy-proof"])
        assert "bafy-proof" in decision.proofs_checked

    def test_evaluator_did_recorded(self) -> None:
        from ipfs_datasets_py.mcp_server.temporal_policy import (
            make_simple_permission_policy, PolicyEvaluator,
        )
        from ipfs_datasets_py.mcp_server.cid_artifacts import IntentObject
        policy = make_simple_permission_policy("*", "*")
        intent = IntentObject(interface_cid="x", tool="t", input_cid="y")
        evaluator = PolicyEvaluator()
        decision = evaluator.evaluate(intent, policy, evaluator_did="did:key:abc")
        assert "did:key:abc" in decision.evaluator_dids


# ============================================================
# Event DAG: event_dag.py
# ============================================================

class TestEventDAGBasics:
    def _node(self, parents=None, intent="intent-1") -> Any:
        from ipfs_datasets_py.mcp_server.cid_artifacts import EventNode
        return EventNode(parents=parents or [], intent_cid=intent)

    def test_empty_dag(self) -> None:
        from ipfs_datasets_py.mcp_server.event_dag import EventDAG
        dag = EventDAG()
        assert len(dag) == 0
        assert dag.frontier() == []

    def test_append_single_node(self) -> None:
        from ipfs_datasets_py.mcp_server.event_dag import EventDAG
        dag = EventDAG()
        node = self._node()
        cid = dag.append(node)
        assert len(dag) == 1
        assert cid in dag

    def test_get_existing_node(self) -> None:
        from ipfs_datasets_py.mcp_server.event_dag import EventDAG
        dag = EventDAG()
        node = self._node()
        cid = dag.append(node)
        assert dag.get(cid) is node

    def test_get_missing_returns_none(self) -> None:
        from ipfs_datasets_py.mcp_server.event_dag import EventDAG
        dag = EventDAG()
        assert dag.get("bafy-unknown") is None

    def test_idempotent_append(self) -> None:
        from ipfs_datasets_py.mcp_server.event_dag import EventDAG
        dag = EventDAG()
        node = self._node()
        cid1 = dag.append(node)
        cid2 = dag.append(node)
        assert cid1 == cid2
        assert len(dag) == 1

    def test_strict_mode_rejects_unknown_parent(self) -> None:
        from ipfs_datasets_py.mcp_server.event_dag import EventDAG
        from ipfs_datasets_py.mcp_server.cid_artifacts import EventNode
        dag = EventDAG(strict=True)
        child = EventNode(parents=["bafy-missing-parent"])
        with pytest.raises(ValueError, match="Unknown parent CID"):
            dag.append(child)

    def test_non_strict_mode_accepts_unknown_parent(self) -> None:
        from ipfs_datasets_py.mcp_server.event_dag import EventDAG
        from ipfs_datasets_py.mcp_server.cid_artifacts import EventNode
        dag = EventDAG(strict=False)
        child = EventNode(parents=["bafy-unknown"])
        cid = dag.append(child)
        assert cid in dag


class TestEventDAGFrontier:
    def test_single_root_is_frontier(self) -> None:
        from ipfs_datasets_py.mcp_server.event_dag import EventDAG
        from ipfs_datasets_py.mcp_server.cid_artifacts import EventNode
        dag = EventDAG()
        root = EventNode(intent_cid="root")
        cid_root = dag.append(root)
        assert dag.frontier() == [cid_root]

    def test_child_replaces_parent_in_frontier(self) -> None:
        from ipfs_datasets_py.mcp_server.event_dag import EventDAG
        from ipfs_datasets_py.mcp_server.cid_artifacts import EventNode
        dag = EventDAG()
        root = EventNode(intent_cid="root")
        cid_root = dag.append(root)
        child = EventNode(parents=[cid_root], intent_cid="child")
        cid_child = dag.append(child)
        frontier = dag.frontier()
        assert cid_child in frontier
        assert cid_root not in frontier

    def test_two_independent_nodes_both_in_frontier(self) -> None:
        from ipfs_datasets_py.mcp_server.event_dag import EventDAG
        from ipfs_datasets_py.mcp_server.cid_artifacts import EventNode
        dag = EventDAG(strict=False)
        a = EventNode(intent_cid="a")
        b = EventNode(intent_cid="b")
        cid_a = dag.append(a)
        cid_b = dag.append(b)
        frontier = dag.frontier()
        assert cid_a in frontier
        assert cid_b in frontier


class TestEventDAGWalk:
    def _build_chain(self, n: int) -> tuple:
        from ipfs_datasets_py.mcp_server.event_dag import EventDAG
        from ipfs_datasets_py.mcp_server.cid_artifacts import EventNode
        dag = EventDAG()
        cids = []
        prev = None
        for i in range(n):
            node = EventNode(parents=[prev] if prev else [], intent_cid=f"step-{i}")
            prev = dag.append(node)
            cids.append(prev)
        return dag, cids

    def test_walk_returns_all_ancestors(self) -> None:
        dag, cids = self._build_chain(4)
        walked = dag.walk(cids[-1])
        assert set(walked) == set(cids)

    def test_walk_single_node(self) -> None:
        dag, cids = self._build_chain(1)
        walked = dag.walk(cids[0])
        assert walked == [cids[0]]

    def test_walk_missing_cid(self) -> None:
        dag, _ = self._build_chain(2)
        assert dag.walk("bafy-missing") == []

    def test_walk_deduplicates_shared_ancestors(self) -> None:
        from ipfs_datasets_py.mcp_server.event_dag import EventDAG
        from ipfs_datasets_py.mcp_server.cid_artifacts import EventNode
        # Diamond: root → A, root → B, merge → [A, B]
        dag = EventDAG()
        root = EventNode(intent_cid="root")
        cid_root = dag.append(root)
        a = EventNode(parents=[cid_root], intent_cid="a")
        cid_a = dag.append(a)
        b = EventNode(parents=[cid_root], intent_cid="b")
        cid_b = dag.append(b)
        merge = EventNode(parents=[cid_a, cid_b], intent_cid="merge")
        cid_merge = dag.append(merge)
        walked = dag.walk(cid_merge)
        # root should appear exactly once
        assert walked.count(cid_root) == 1


class TestEventDAGRollback:
    def test_descendants_of_root(self) -> None:
        from ipfs_datasets_py.mcp_server.event_dag import EventDAG
        from ipfs_datasets_py.mcp_server.cid_artifacts import EventNode
        dag = EventDAG()
        root = EventNode(intent_cid="root")
        cid_root = dag.append(root)
        child = EventNode(parents=[cid_root], intent_cid="child")
        cid_child = dag.append(child)
        desc = dag.descendants(cid_root)
        assert cid_child in desc
        assert cid_root not in desc

    def test_rollback_to_alias(self) -> None:
        from ipfs_datasets_py.mcp_server.event_dag import EventDAG
        from ipfs_datasets_py.mcp_server.cid_artifacts import EventNode
        dag = EventDAG()
        root = EventNode(intent_cid="root")
        cid_root = dag.append(root)
        child = EventNode(parents=[cid_root], intent_cid="child")
        dag.append(child)
        assert dag.rollback_to(cid_root) == dag.descendants(cid_root)

    def test_leaf_has_no_descendants(self) -> None:
        from ipfs_datasets_py.mcp_server.event_dag import EventDAG
        from ipfs_datasets_py.mcp_server.cid_artifacts import EventNode
        dag = EventDAG()
        node = EventNode(intent_cid="leaf")
        cid = dag.append(node)
        assert dag.descendants(cid) == []


class TestEventDAGConcurrency:
    def test_independent_nodes_are_concurrent(self) -> None:
        from ipfs_datasets_py.mcp_server.event_dag import EventDAG
        from ipfs_datasets_py.mcp_server.cid_artifacts import EventNode
        dag = EventDAG(strict=False)
        a = EventNode(intent_cid="a")
        b = EventNode(intent_cid="b")
        cid_a = dag.append(a)
        cid_b = dag.append(b)
        assert dag.are_concurrent(cid_a, cid_b) is True

    def test_parent_child_not_concurrent(self) -> None:
        from ipfs_datasets_py.mcp_server.event_dag import EventDAG
        from ipfs_datasets_py.mcp_server.cid_artifacts import EventNode
        dag = EventDAG()
        root = EventNode(intent_cid="root")
        cid_root = dag.append(root)
        child = EventNode(parents=[cid_root], intent_cid="child")
        cid_child = dag.append(child)
        assert dag.are_concurrent(cid_root, cid_child) is False


class TestBuildLinearDag:
    def test_linear_chain_linked(self) -> None:
        from ipfs_datasets_py.mcp_server.event_dag import build_linear_dag
        from ipfs_datasets_py.mcp_server.cid_artifacts import EventNode
        nodes = [EventNode(intent_cid=f"step-{i}") for i in range(3)]
        dag = build_linear_dag(nodes)
        assert len(dag) == 3

    def test_linear_chain_single_frontier(self) -> None:
        from ipfs_datasets_py.mcp_server.event_dag import build_linear_dag
        from ipfs_datasets_py.mcp_server.cid_artifacts import EventNode
        nodes = [EventNode(intent_cid=f"s{i}") for i in range(4)]
        dag = build_linear_dag(nodes)
        # Only the last node should be in the frontier
        assert len(dag.frontier()) == 1
