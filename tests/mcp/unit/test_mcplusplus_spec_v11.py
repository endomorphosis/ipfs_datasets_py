"""
Session AA85: MCP-IDL Profile A — interface_descriptor.py tests (23 tests)
Session AB86: Profile B — cid_artifacts.py tests (21 tests)
Session AC87: Profile D — temporal_policy.py tests (16 tests)
Session AD88: P2P transport / integration alignment tests (8 tests)

v11 MCP++ spec alignment — 68 new tests total.
"""
from __future__ import annotations

import hashlib
import time
import pytest

# ══════════════════════════════════════════════════════════════════════════════
# AA85 — Profile A: MCP-IDL (interface_descriptor.py)
# ══════════════════════════════════════════════════════════════════════════════

class TestComputeCid:
    """compute_cid / _canonicalize helpers."""

    def test_same_input_same_cid(self):
        from ipfs_datasets_py.mcp_server.interface_descriptor import compute_cid, _canonicalize
        data = b"hello world"
        assert compute_cid(data) == compute_cid(data)

    def test_different_input_different_cid(self):
        from ipfs_datasets_py.mcp_server.interface_descriptor import compute_cid
        assert compute_cid(b"abc") != compute_cid(b"xyz")

    def test_cid_starts_with_sha256_prefix(self):
        from ipfs_datasets_py.mcp_server.interface_descriptor import compute_cid
        cid = compute_cid(b"test")
        assert cid.startswith("sha256:")

    def test_canonical_bytes_key_order_stable(self):
        from ipfs_datasets_py.mcp_server.interface_descriptor import _canonicalize
        d1 = _canonicalize({"b": 2, "a": 1})
        d2 = _canonicalize({"a": 1, "b": 2})
        assert d1 == d2


class TestInterfaceDescriptor:
    """InterfaceDescriptor: canonical_bytes, interface_cid, to_dict, from_dict."""

    def _make_desc(self, name="git", version="1.0.0"):
        from ipfs_datasets_py.mcp_server.interface_descriptor import (
            InterfaceDescriptor, MethodSignature
        )
        return InterfaceDescriptor(
            name=name,
            namespace="com.example",
            version=version,
            methods=[
                MethodSignature(name="status", input_schema={"type": "object"}),
                MethodSignature(name="commit"),
            ],
            semantic_tags=["vcs"],
        )

    def test_interface_cid_is_string(self):
        desc = self._make_desc()
        assert isinstance(desc.interface_cid, str)

    def test_identical_descriptors_same_cid(self):
        d1 = self._make_desc()
        d2 = self._make_desc()
        assert d1.interface_cid == d2.interface_cid

    def test_different_version_different_cid(self):
        d1 = self._make_desc(version="1.0.0")
        d2 = self._make_desc(version="2.0.0")
        assert d1.interface_cid != d2.interface_cid

    def test_to_dict_contains_interface_cid(self):
        desc = self._make_desc()
        d = desc.to_dict()
        assert "interface_cid" in d
        assert d["interface_cid"] == desc.interface_cid

    def test_to_dict_contains_name(self):
        desc = self._make_desc()
        assert desc.to_dict()["name"] == "git"

    def test_from_dict_roundtrip_preserves_cid(self):
        from ipfs_datasets_py.mcp_server.interface_descriptor import InterfaceDescriptor
        desc = self._make_desc()
        d = desc.to_dict()
        recovered = InterfaceDescriptor.from_dict(d)
        assert recovered.interface_cid == desc.interface_cid

    def test_canonical_bytes_are_deterministic(self):
        desc = self._make_desc()
        assert desc.canonical_bytes() == desc.canonical_bytes()

    def test_methods_sorted_in_canonical_form(self):
        from ipfs_datasets_py.mcp_server.interface_descriptor import (
            InterfaceDescriptor, MethodSignature
        )
        d1 = InterfaceDescriptor(
            name="svc", namespace="n", version="1.0",
            methods=[MethodSignature("b"), MethodSignature("a")],
        )
        d2 = InterfaceDescriptor(
            name="svc", namespace="n", version="1.0",
            methods=[MethodSignature("a"), MethodSignature("b")],
        )
        assert d1.canonical_bytes() == d2.canonical_bytes()


class TestInterfaceRepository:
    """InterfaceRepository: register, list, get, compat, select."""

    def _repo(self):
        from ipfs_datasets_py.mcp_server.interface_descriptor import InterfaceRepository
        return InterfaceRepository()

    def _desc(self, name="svc"):
        from ipfs_datasets_py.mcp_server.interface_descriptor import (
            InterfaceDescriptor, MethodSignature
        )
        return InterfaceDescriptor(
            name=name, namespace="ns", version="1.0",
            methods=[MethodSignature("run")],
            semantic_tags=["compute"],
        )

    def test_register_returns_cid(self):
        repo = self._repo()
        cid = repo.register(self._desc())
        assert isinstance(cid, str) and cid.startswith("sha256:")

    def test_list_returns_registered_cids(self):
        repo = self._repo()
        cid = repo.register(self._desc())
        assert cid in repo.list()

    def test_get_returns_descriptor_dict(self):
        repo = self._repo()
        desc = self._desc()
        cid = repo.register(desc)
        result = repo.get(cid)
        assert result is not None
        assert result["name"] == "svc"

    def test_get_unknown_cid_returns_none(self):
        repo = self._repo()
        assert repo.get("sha256:" + "0" * 64) is None

    def test_compat_known_compatible(self):
        from ipfs_datasets_py.mcp_server.interface_descriptor import (
            InterfaceDescriptor, MethodSignature
        )
        repo = self._repo()
        # candidate has superset of methods
        candidate = InterfaceDescriptor(
            name="c", namespace="ns", version="1.0",
            methods=[MethodSignature("run"), MethodSignature("list")],
        )
        required = InterfaceDescriptor(
            name="r", namespace="ns", version="1.0",
            methods=[MethodSignature("run")],
        )
        c_cid = repo.register(candidate)
        r_cid = repo.register(required)
        verdict = repo.compat(c_cid, required_cid=r_cid)
        assert verdict.compatible is True

    def test_compat_missing_method_incompatible(self):
        from ipfs_datasets_py.mcp_server.interface_descriptor import (
            InterfaceDescriptor, MethodSignature
        )
        repo = self._repo()
        candidate = InterfaceDescriptor(
            name="c", namespace="ns", version="1.0",
            methods=[MethodSignature("run")],
        )
        required = InterfaceDescriptor(
            name="r", namespace="ns", version="1.0",
            methods=[MethodSignature("run"), MethodSignature("advanced_op")],
        )
        c_cid = repo.register(candidate)
        r_cid = repo.register(required)
        verdict = repo.compat(c_cid, required_cid=r_cid)
        assert verdict.compatible is False
        assert any("advanced_op" in reason for reason in verdict.reasons)

    def test_compat_unknown_cid_incompatible(self):
        repo = self._repo()
        verdict = repo.compat("sha256:" + "f" * 64)
        assert verdict.compatible is False

    def test_select_by_semantic_tag(self):
        repo = self._repo()
        repo.register(self._desc("compute-svc"))
        result = repo.select("compute task", budget=5)
        assert len(result) >= 1

    def test_select_budget_limits_results(self):
        from ipfs_datasets_py.mcp_server.interface_descriptor import (
            InterfaceDescriptor, MethodSignature
        )
        repo = self._repo()
        for i in range(5):
            d = InterfaceDescriptor(
                name=f"svc{i}", namespace="ns", version="1.0",
                methods=[MethodSignature("run")],
                semantic_tags=["compute"],
            )
            repo.register(d)
        result = repo.select("compute", budget=2)
        assert len(result) <= 2

    def test_len_counts_registered(self):
        repo = self._repo()
        assert len(repo) == 0
        repo.register(self._desc("a"))
        repo.register(self._desc("b"))
        assert len(repo) == 2

    def test_global_repo_singleton(self):
        from ipfs_datasets_py.mcp_server.interface_descriptor import (
            get_interface_repository
        )
        r1 = get_interface_repository()
        r2 = get_interface_repository()
        assert r1 is r2


# ══════════════════════════════════════════════════════════════════════════════
# AB86 — Profile B: CID-Native Artifacts (cid_artifacts.py)
# ══════════════════════════════════════════════════════════════════════════════

class TestIntentObject:
    """IntentObject: cid stability and to_dict."""

    def test_cid_is_str(self):
        from ipfs_datasets_py.mcp_server.cid_artifacts import IntentObject
        intent = IntentObject(tool="run_query")
        assert isinstance(intent.cid, str)

    def test_same_intent_same_cid(self):
        from ipfs_datasets_py.mcp_server.cid_artifacts import IntentObject
        i1 = IntentObject(tool="run_query", input_cid="sha256:abc")
        i2 = IntentObject(tool="run_query", input_cid="sha256:abc")
        assert i1.cid == i2.cid

    def test_different_tool_different_cid(self):
        from ipfs_datasets_py.mcp_server.cid_artifacts import IntentObject
        i1 = IntentObject(tool="toolA")
        i2 = IntentObject(tool="toolB")
        assert i1.cid != i2.cid

    def test_to_dict_has_intent_cid_key(self):
        from ipfs_datasets_py.mcp_server.cid_artifacts import IntentObject
        intent = IntentObject(tool="x")
        d = intent.to_dict()
        assert "intent_cid" in d and d["intent_cid"] == intent.cid

    def test_to_dict_has_tool(self):
        from ipfs_datasets_py.mcp_server.cid_artifacts import IntentObject
        assert IntentObject(tool="my_tool").to_dict()["tool"] == "my_tool"


class TestDecisionObject:
    """DecisionObject: cid, is_allowed, to_dict."""

    def test_allow_decision_is_allowed(self):
        from ipfs_datasets_py.mcp_server.cid_artifacts import DecisionObject, ALLOW
        d = DecisionObject(decision=ALLOW, intent_cid="sha256:abc")
        assert d.is_allowed is True

    def test_deny_decision_not_allowed(self):
        from ipfs_datasets_py.mcp_server.cid_artifacts import DecisionObject, DENY
        d = DecisionObject(decision=DENY, intent_cid="sha256:abc")
        assert d.is_allowed is False

    def test_allow_with_obligations_is_allowed(self):
        from ipfs_datasets_py.mcp_server.cid_artifacts import (
            DecisionObject, ALLOW_WITH_OBLIGATIONS, Obligation
        )
        d = DecisionObject(
            decision=ALLOW_WITH_OBLIGATIONS,
            intent_cid="sha256:abc",
            obligations=[Obligation(type="produce_receipt")],
        )
        assert d.is_allowed is True

    def test_cid_is_deterministic(self):
        from ipfs_datasets_py.mcp_server.cid_artifacts import DecisionObject, ALLOW
        d1 = DecisionObject(decision=ALLOW, intent_cid="sha256:x", justification="ok")
        d2 = DecisionObject(decision=ALLOW, intent_cid="sha256:x", justification="ok")
        assert d1.cid == d2.cid

    def test_to_dict_contains_decision_cid(self):
        from ipfs_datasets_py.mcp_server.cid_artifacts import DecisionObject, DENY
        d = DecisionObject(decision=DENY, intent_cid="sha256:abc")
        assert "decision_cid" in d.to_dict()


class TestReceiptObject:
    """ReceiptObject: cid and to_dict."""

    def test_cid_stable(self):
        from ipfs_datasets_py.mcp_server.cid_artifacts import ReceiptObject
        r = ReceiptObject(intent_cid="sha256:abc", output_cid="sha256:out")
        assert r.cid == r.cid

    def test_to_dict_has_receipt_cid(self):
        from ipfs_datasets_py.mcp_server.cid_artifacts import ReceiptObject
        r = ReceiptObject(intent_cid="sha256:abc")
        assert "receipt_cid" in r.to_dict()


class TestExecutionEnvelope:
    """ExecutionEnvelope: to_dict, is_complete, from_dict roundtrip."""

    def test_is_complete_false_when_no_output(self):
        from ipfs_datasets_py.mcp_server.cid_artifacts import ExecutionEnvelope
        env = ExecutionEnvelope(intent_cid="sha256:intent")
        assert env.is_complete() is False

    def test_is_complete_true_when_both_set(self):
        from ipfs_datasets_py.mcp_server.cid_artifacts import ExecutionEnvelope
        env = ExecutionEnvelope(
            intent_cid="sha256:intent",
            output_cid="sha256:out",
            receipt_cid="sha256:rcpt",
        )
        assert env.is_complete() is True

    def test_from_dict_roundtrip(self):
        from ipfs_datasets_py.mcp_server.cid_artifacts import ExecutionEnvelope
        env = ExecutionEnvelope(
            interface_cid="sha256:iface",
            intent_cid="sha256:intent",
            parents=["sha256:parent"],
        )
        recovered = ExecutionEnvelope.from_dict(env.to_dict())
        assert recovered.interface_cid == env.interface_cid
        assert recovered.parents == env.parents

    def test_to_dict_keys(self):
        from ipfs_datasets_py.mcp_server.cid_artifacts import ExecutionEnvelope
        env = ExecutionEnvelope()
        d = env.to_dict()
        for key in ("interface_cid", "input_cid", "intent_cid", "policy_cid",
                    "proof_cid", "parents", "output_cid", "receipt_cid"):
            assert key in d


class TestEventNode:
    """EventNode: cid and DAG linking."""

    def test_cid_is_str(self):
        from ipfs_datasets_py.mcp_server.cid_artifacts import EventNode
        ev = EventNode(intent_cid="sha256:intent")
        assert isinstance(ev.cid, str)

    def test_parent_cids_change_event_cid(self):
        from ipfs_datasets_py.mcp_server.cid_artifacts import EventNode
        e1 = EventNode(intent_cid="sha256:intent", parents=[])
        e2 = EventNode(intent_cid="sha256:intent", parents=["sha256:prev"])
        assert e1.cid != e2.cid

    def test_to_dict_has_event_cid(self):
        from ipfs_datasets_py.mcp_server.cid_artifacts import EventNode
        assert "event_cid" in EventNode(intent_cid="sha256:i").to_dict()


class TestArtifactCid:
    def test_artifact_cid_stable(self):
        from ipfs_datasets_py.mcp_server.cid_artifacts import artifact_cid
        assert artifact_cid({"key": "val"}) == artifact_cid({"key": "val"})

    def test_artifact_cid_different_for_different_data(self):
        from ipfs_datasets_py.mcp_server.cid_artifacts import artifact_cid
        assert artifact_cid({"a": 1}) != artifact_cid({"a": 2})


# ══════════════════════════════════════════════════════════════════════════════
# AC87 — Profile D: Temporal Deontic Policy (temporal_policy.py)
# ══════════════════════════════════════════════════════════════════════════════

class TestPolicyObject:
    """PolicyObject: policy_cid stability and clause accessors."""

    def _make_policy(self):
        from ipfs_datasets_py.mcp_server.temporal_policy import (
            PolicyObject, PolicyClause, PolicyClauseType
        )
        return PolicyObject(
            policy_id="test-policy",
            clauses=[
                PolicyClause(clause_type=PolicyClauseType.PERMISSION, action="run_query"),
                PolicyClause(clause_type=PolicyClauseType.PROHIBITION, action="delete_all"),
                PolicyClause(clause_type=PolicyClauseType.OBLIGATION,
                             action="produce_receipt",
                             obligation_deadline="2026-12-31T00:00:00Z"),
            ],
        )

    def test_policy_cid_is_str(self):
        p = self._make_policy()
        assert isinstance(p.policy_cid, str)

    def test_same_policy_same_cid(self):
        p1 = self._make_policy()
        p2 = self._make_policy()
        assert p1.policy_cid == p2.policy_cid

    def test_get_permissions(self):
        p = self._make_policy()
        assert len(p.get_permissions()) == 1
        assert p.get_permissions()[0].action == "run_query"

    def test_get_prohibitions(self):
        p = self._make_policy()
        assert len(p.get_prohibitions()) == 1

    def test_get_obligations(self):
        p = self._make_policy()
        assert len(p.get_obligations()) == 1


class TestPolicyClauseTemporal:
    """PolicyClause temporal validity windows."""

    def test_valid_within_window(self):
        from ipfs_datasets_py.mcp_server.temporal_policy import (
            PolicyClause, PolicyClauseType
        )
        now = time.time()
        c = PolicyClause(
            clause_type=PolicyClauseType.PERMISSION,
            valid_from=now - 100,
            valid_until=now + 100,
        )
        assert c.is_temporally_valid(now) is True

    def test_invalid_before_window(self):
        from ipfs_datasets_py.mcp_server.temporal_policy import (
            PolicyClause, PolicyClauseType
        )
        now = time.time()
        c = PolicyClause(
            clause_type=PolicyClauseType.PERMISSION,
            valid_from=now + 100,
        )
        assert c.is_temporally_valid(now) is False

    def test_invalid_after_window(self):
        from ipfs_datasets_py.mcp_server.temporal_policy import (
            PolicyClause, PolicyClauseType
        )
        now = time.time()
        c = PolicyClause(
            clause_type=PolicyClauseType.PERMISSION,
            valid_until=now - 100,
        )
        assert c.is_temporally_valid(now) is False

    def test_no_window_always_valid(self):
        from ipfs_datasets_py.mcp_server.temporal_policy import (
            PolicyClause, PolicyClauseType
        )
        c = PolicyClause(clause_type=PolicyClauseType.PERMISSION)
        assert c.is_temporally_valid() is True


class TestPolicyEvaluator:
    """PolicyEvaluator: allow / deny / obligations."""

    def _setup(self):
        from ipfs_datasets_py.mcp_server.temporal_policy import (
            PolicyEvaluator, PolicyObject, PolicyClause, PolicyClauseType,
            make_simple_permission_policy
        )
        from ipfs_datasets_py.mcp_server.cid_artifacts import IntentObject
        evaluator = PolicyEvaluator()
        policy = make_simple_permission_policy(
            policy_id="p1", allowed_tools=["run_query", "list_datasets"]
        )
        pcid = evaluator.register_policy(policy)
        return evaluator, pcid

    def test_allow_permitted_tool(self):
        from ipfs_datasets_py.mcp_server.cid_artifacts import IntentObject, ALLOW
        evaluator, pcid = self._setup()
        intent = IntentObject(tool="run_query")
        decision = evaluator.evaluate(intent, pcid)
        assert decision.decision == ALLOW

    def test_deny_unpermitted_tool(self):
        from ipfs_datasets_py.mcp_server.cid_artifacts import IntentObject, DENY
        evaluator, pcid = self._setup()
        intent = IntentObject(tool="delete_all")
        decision = evaluator.evaluate(intent, pcid)
        assert decision.decision == DENY

    def test_deny_unknown_policy_cid(self):
        from ipfs_datasets_py.mcp_server.cid_artifacts import IntentObject, DENY
        evaluator, _ = self._setup()
        intent = IntentObject(tool="run_query")
        decision = evaluator.evaluate(intent, "sha256:" + "0" * 64)
        assert decision.decision == DENY

    def test_prohibition_overrides_permission(self):
        from ipfs_datasets_py.mcp_server.temporal_policy import (
            PolicyEvaluator, PolicyObject, PolicyClause, PolicyClauseType
        )
        from ipfs_datasets_py.mcp_server.cid_artifacts import IntentObject, DENY
        evaluator = PolicyEvaluator()
        policy = PolicyObject(
            policy_id="conflict-policy",
            clauses=[
                PolicyClause(clause_type=PolicyClauseType.PERMISSION, action="*"),
                PolicyClause(clause_type=PolicyClauseType.PROHIBITION, action="danger_op"),
            ],
        )
        pcid = evaluator.register_policy(policy)
        intent = IntentObject(tool="danger_op")
        decision = evaluator.evaluate(intent, pcid)
        assert decision.decision == DENY

    def test_obligation_spawned_on_match(self):
        from ipfs_datasets_py.mcp_server.temporal_policy import (
            PolicyEvaluator, PolicyObject, PolicyClause, PolicyClauseType
        )
        from ipfs_datasets_py.mcp_server.cid_artifacts import (
            IntentObject, ALLOW_WITH_OBLIGATIONS
        )
        evaluator = PolicyEvaluator()
        policy = PolicyObject(
            policy_id="obs-policy",
            clauses=[
                PolicyClause(clause_type=PolicyClauseType.PERMISSION, action="*"),
                PolicyClause(
                    clause_type=PolicyClauseType.OBLIGATION,
                    action="*",  # wildcard matches any tool
                    obligation_deadline="2026-12-31T00:00:00Z",
                ),
            ],
        )
        pcid = evaluator.register_policy(policy)
        intent = IntentObject(tool="any_tool")
        decision = evaluator.evaluate(intent, pcid)
        assert decision.decision == ALLOW_WITH_OBLIGATIONS
        assert len(decision.obligations) == 1

    def test_decision_has_intent_cid(self):
        from ipfs_datasets_py.mcp_server.cid_artifacts import IntentObject
        evaluator, pcid = self._setup()
        intent = IntentObject(tool="run_query")
        decision = evaluator.evaluate(intent, pcid)
        assert decision.intent_cid == intent.cid

    def test_global_evaluator_singleton(self):
        from ipfs_datasets_py.mcp_server.temporal_policy import get_policy_evaluator
        e1 = get_policy_evaluator()
        e2 = get_policy_evaluator()
        assert e1 is e2


# ══════════════════════════════════════════════════════════════════════════════
# AD88 — P2P transport / integration alignment
# ══════════════════════════════════════════════════════════════════════════════

class TestMCPPlusPlusAlignment:
    """Integration alignment: spec concepts map to existing mcplusplus module."""

    def test_workflow_engine_exists(self):
        from ipfs_datasets_py.mcp_server.mcplusplus import workflow_engine
        assert hasattr(workflow_engine, 'WorkflowEngine') or \
               hasattr(workflow_engine, 'Task') or \
               hasattr(workflow_engine, 'WorkflowStatus')

    def test_peer_registry_wrapper_exists(self):
        from ipfs_datasets_py.mcp_server.mcplusplus import peer_registry
        assert hasattr(peer_registry, 'PeerRegistryWrapper')

    def test_task_queue_wrapper_exists(self):
        from ipfs_datasets_py.mcp_server.mcplusplus import task_queue
        assert hasattr(task_queue, 'TaskQueueWrapper')

    def test_priority_queue_module_importable(self):
        from ipfs_datasets_py.mcp_server.mcplusplus import priority_queue
        assert priority_queue is not None

    def test_interface_descriptor_importable(self):
        """Profile A module loads cleanly."""
        import importlib
        mod = importlib.import_module(
            'ipfs_datasets_py.mcp_server.interface_descriptor'
        )
        assert hasattr(mod, 'InterfaceDescriptor')
        assert hasattr(mod, 'InterfaceRepository')

    def test_cid_artifacts_importable(self):
        """Profile B module loads cleanly."""
        import importlib
        mod = importlib.import_module('ipfs_datasets_py.mcp_server.cid_artifacts')
        assert hasattr(mod, 'ExecutionEnvelope')
        assert hasattr(mod, 'IntentObject')
        assert hasattr(mod, 'DecisionObject')
        assert hasattr(mod, 'ReceiptObject')
        assert hasattr(mod, 'EventNode')

    def test_temporal_policy_importable(self):
        """Profile D module loads cleanly."""
        import importlib
        mod = importlib.import_module('ipfs_datasets_py.mcp_server.temporal_policy')
        assert hasattr(mod, 'PolicyEvaluator')
        assert hasattr(mod, 'PolicyObject')
        assert hasattr(mod, 'make_simple_permission_policy')

    def test_end_to_end_intent_policy_receipt_chain(self):
        """Full Profile B + D pipeline: intent → decision → receipt → event."""
        from ipfs_datasets_py.mcp_server.cid_artifacts import (
            IntentObject, ReceiptObject, EventNode
        )
        from ipfs_datasets_py.mcp_server.temporal_policy import (
            PolicyEvaluator, make_simple_permission_policy
        )
        from ipfs_datasets_py.mcp_server.cid_artifacts import ALLOW

        # 1. Create policy
        evaluator = PolicyEvaluator()
        policy = make_simple_permission_policy(
            policy_id="e2e-test", allowed_tools=["run_analysis"]
        )
        pcid = evaluator.register_policy(policy)

        # 2. Build intent
        intent = IntentObject(tool="run_analysis", correlation_id="test-corr")

        # 3. Evaluate → decision
        decision = evaluator.evaluate(intent, pcid)
        assert decision.is_allowed

        # 4. Build receipt
        receipt = ReceiptObject(
            intent_cid=intent.cid,
            output_cid="sha256:output",
            decision_cid=decision.cid,
            correlation_id="test-corr",
        )

        # 5. Append event node to DAG
        event = EventNode(
            intent_cid=intent.cid,
            decision_cid=decision.cid,
            receipt_cid=receipt.cid,
            output_cid="sha256:output",
        )

        # All CIDs are non-empty strings
        assert intent.cid and decision.cid and receipt.cid and event.cid
        # Event links back to intent
        assert event.to_dict()["intent_cid"] == intent.cid
