"""
v12 Sessions AG91 + AH92 + AE89/AF90 integration:

  AG91 — PolicyRegistry: register, list_policies, evaluate delegation,
         save/load JSON persistence
  AH92 — UCAN Delegation: Capability, DelegationToken, DelegationChain,
         DelegationEvaluator, module-level singleton
  AE89 — InterfaceDescriptor + HTM hook (smoke tests covering new methods)
"""
from __future__ import annotations

import json
import os
import tempfile
import time
from typing import Dict, Any, List
from unittest.mock import patch

import pytest

pytestmark = pytest.mark.asyncio


# ════════════════════════════════════════════════════════════════════════════
# AG91  PolicyRegistry
# ════════════════════════════════════════════════════════════════════════════

class TestPolicyRegistry:
    """Tests for the new PolicyRegistry class added to temporal_policy.py."""

    def _make_registry(self):
        from ipfs_datasets_py.mcp_server.temporal_policy import PolicyRegistry
        return PolicyRegistry()

    def _make_simple_policy(self, policy_id: str, tools: list):
        from ipfs_datasets_py.mcp_server.temporal_policy import (
            make_simple_permission_policy,
        )
        return make_simple_permission_policy(policy_id=policy_id, allowed_tools=tools)

    def _make_intent(self, tool: str):
        from ipfs_datasets_py.mcp_server.cid_artifacts import IntentObject
        return IntentObject(tool=tool)

    # ── basic operations ────────────────────────────────────────────────────

    def test_register_returns_policy_cid(self):
        reg = self._make_registry()
        pol = self._make_simple_policy("p1", ["tools/invoke"])
        cid = reg.register(pol)
        assert isinstance(cid, str)
        assert cid.startswith("sha256:")

    def test_list_policies_empty_initially(self):
        reg = self._make_registry()
        assert reg.list_policies() == []

    def test_list_policies_after_register(self):
        reg = self._make_registry()
        pol = self._make_simple_policy("pol-a", ["tool_x"])
        cid = reg.register(pol)
        listing = reg.list_policies()
        assert len(listing) == 1
        assert listing[0]["policy_id"] == "pol-a"
        assert listing[0]["policy_cid"] == cid

    def test_register_multiple_policies(self):
        reg = self._make_registry()
        for i in range(3):
            reg.register(self._make_simple_policy(f"p{i}", [f"tool_{i}"]))
        assert len(reg.list_policies()) == 3

    # ── evaluate delegation ─────────────────────────────────────────────────

    def test_evaluate_allow(self):
        from ipfs_datasets_py.mcp_server.cid_artifacts import ALLOW
        reg = self._make_registry()
        pol = self._make_simple_policy("allow_pol", ["data_fetch"])
        cid = reg.register(pol)
        intent = self._make_intent("data_fetch")
        decision = reg.evaluate(intent, cid)
        assert decision.is_allowed
        assert decision.decision == ALLOW

    def test_evaluate_deny_unknown_policy(self):
        from ipfs_datasets_py.mcp_server.cid_artifacts import DENY
        reg = self._make_registry()
        intent = self._make_intent("anything")
        decision = reg.evaluate(intent, "sha256:nonexistent")
        assert not decision.is_allowed
        assert decision.decision == DENY

    def test_evaluate_deny_when_tool_not_permitted(self):
        from ipfs_datasets_py.mcp_server.cid_artifacts import DENY
        reg = self._make_registry()
        pol = self._make_simple_policy("narrow_pol", ["allowed_tool"])
        cid = reg.register(pol)
        intent = self._make_intent("forbidden_tool")
        decision = reg.evaluate(intent, cid)
        assert not decision.is_allowed

    def test_evaluator_property(self):
        from ipfs_datasets_py.mcp_server.temporal_policy import PolicyEvaluator
        reg = self._make_registry()
        assert isinstance(reg.evaluator, PolicyEvaluator)

    # ── save / load ─────────────────────────────────────────────────────────

    def test_save_creates_file(self):
        reg = self._make_registry()
        pol = self._make_simple_policy("saveable", ["t1", "t2"])
        reg.register(pol)
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        try:
            reg.save(path)
            assert os.path.exists(path)
            with open(path) as f:
                data = json.load(f)
            assert isinstance(data, list)
            assert len(data) == 1
            assert data[0]["policy_id"] == "saveable"
        finally:
            os.unlink(path)

    def test_load_restores_policies(self):
        from ipfs_datasets_py.mcp_server.temporal_policy import PolicyRegistry
        # Save from one registry, load into another
        reg1 = PolicyRegistry()
        pol = self._make_simple_policy("to_load", ["load_tool"])
        reg1.register(pol)
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        try:
            reg1.save(path)

            reg2 = PolicyRegistry()
            count = reg2.load(path)
            assert count == 1
            listing = reg2.list_policies()
            assert listing[0]["policy_id"] == "to_load"
        finally:
            os.unlink(path)

    def test_load_allows_evaluation(self):
        from ipfs_datasets_py.mcp_server.temporal_policy import PolicyRegistry
        from ipfs_datasets_py.mcp_server.cid_artifacts import ALLOW
        reg1 = PolicyRegistry()
        pol = self._make_simple_policy("eval_pol", ["run_job"])
        reg1.register(pol)
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        try:
            reg1.save(path)
            reg2 = PolicyRegistry()
            reg2.load(path)
            intent = self._make_intent("run_job")
            cid = reg2.list_policies()[0]["policy_cid"]
            decision = reg2.evaluate(intent, cid)
            assert decision.decision == ALLOW
        finally:
            os.unlink(path)

    def test_global_registry_singleton(self):
        from ipfs_datasets_py.mcp_server.temporal_policy import (
            get_policy_registry, PolicyRegistry,
        )
        r1 = get_policy_registry()
        r2 = get_policy_registry()
        assert r1 is r2
        assert isinstance(r1, PolicyRegistry)


# ════════════════════════════════════════════════════════════════════════════
# AH92  UCAN Delegation
# ════════════════════════════════════════════════════════════════════════════

class TestCapability:

    def test_exact_match(self):
        from ipfs_datasets_py.mcp_server.ucan_delegation import Capability
        cap = Capability(resource="tools://invoke", ability="call")
        assert cap.matches("tools://invoke", "call")

    def test_no_match_wrong_ability(self):
        from ipfs_datasets_py.mcp_server.ucan_delegation import Capability
        cap = Capability(resource="tools://invoke", ability="call")
        assert not cap.matches("tools://invoke", "list")

    def test_wildcard_ability(self):
        from ipfs_datasets_py.mcp_server.ucan_delegation import Capability
        cap = Capability(resource="tools://invoke", ability="*")
        assert cap.matches("tools://invoke", "call")
        assert cap.matches("tools://invoke", "anything")

    def test_wildcard_resource(self):
        from ipfs_datasets_py.mcp_server.ucan_delegation import Capability
        cap = Capability(resource="*", ability="call")
        assert cap.matches("any_resource", "call")

    def test_both_wildcards(self):
        from ipfs_datasets_py.mcp_server.ucan_delegation import Capability
        cap = Capability(resource="*", ability="*")
        assert cap.matches("anything", "anything_else")


class TestDelegationToken:

    def _make_token(self, **kwargs) -> Any:
        from ipfs_datasets_py.mcp_server.ucan_delegation import (
            DelegationToken, Capability,
        )
        defaults = dict(
            issuer="did:example:issuer",
            audience="did:example:audience",
            capabilities=[Capability(resource="tools://invoke", ability="call")],
        )
        defaults.update(kwargs)
        return DelegationToken(**defaults)

    def test_cid_is_string_starting_sha256(self):
        tok = self._make_token()
        assert tok.cid.startswith("sha256:")

    def test_cid_deterministic(self):
        t1 = self._make_token()
        t2 = self._make_token()
        assert t1.cid == t2.cid

    def test_different_audience_gives_different_cid(self):
        t1 = self._make_token()
        t2 = self._make_token(audience="did:example:other")
        assert t1.cid != t2.cid

    def test_is_valid_no_expiry(self):
        tok = self._make_token()
        assert tok.is_valid()

    def test_is_valid_future_expiry(self):
        tok = self._make_token(expiry=time.time() + 3600)
        assert tok.is_valid()

    def test_is_invalid_past_expiry(self):
        tok = self._make_token(expiry=time.time() - 1)
        assert not tok.is_valid()

    def test_is_invalid_not_before_future(self):
        tok = self._make_token(not_before=time.time() + 3600)
        assert not tok.is_valid()

    def test_to_dict_has_required_keys(self):
        tok = self._make_token()
        d = tok.to_dict()
        for key in ("token_cid", "issuer", "audience", "capabilities"):
            assert key in d

    def test_from_dict_roundtrip(self):
        from ipfs_datasets_py.mcp_server.ucan_delegation import DelegationToken
        tok = self._make_token()
        restored = DelegationToken.from_dict(tok.to_dict())
        # CID will differ because from_dict builds a new object without _cid;
        # check structural equality instead
        assert restored.issuer == tok.issuer
        assert restored.audience == tok.audience
        assert len(restored.capabilities) == len(tok.capabilities)


class TestDelegationChain:

    def _make_chain(self, n_links: int = 2):
        """Build a valid n-link chain: root → hop1 → ... → leaf."""
        from ipfs_datasets_py.mcp_server.ucan_delegation import (
            DelegationToken, DelegationChain, Capability,
        )
        cap = Capability(resource="tools://invoke", ability="call")
        dids = [f"did:example:agent{i}" for i in range(n_links + 1)]
        tokens = []
        for i in range(n_links):
            tokens.append(DelegationToken(
                issuer=dids[i],
                audience=dids[i + 1],
                capabilities=[cap],
            ))
        chain = DelegationChain(tokens=tokens)
        return chain, dids

    def test_root_issuer(self):
        chain, dids = self._make_chain()
        assert chain.root_issuer == dids[0]

    def test_leaf_audience(self):
        chain, dids = self._make_chain()
        assert chain.leaf_audience == dids[-1]

    def test_valid_chain(self):
        chain, _ = self._make_chain()
        valid, reason = chain.is_valid_chain()
        assert valid, reason

    def test_broken_chain_invalid(self):
        from ipfs_datasets_py.mcp_server.ucan_delegation import (
            DelegationToken, DelegationChain, Capability,
        )
        cap = Capability(resource="*", ability="*")
        t1 = DelegationToken(issuer="a", audience="b", capabilities=[cap])
        t2 = DelegationToken(issuer="WRONG", audience="c", capabilities=[cap])
        chain = DelegationChain(tokens=[t1, t2])
        valid, reason = chain.is_valid_chain()
        assert not valid
        assert "break" in reason.lower() or "expected" in reason.lower()

    def test_expired_chain_invalid(self):
        from ipfs_datasets_py.mcp_server.ucan_delegation import (
            DelegationToken, DelegationChain, Capability,
        )
        cap = Capability(resource="*", ability="*")
        t = DelegationToken(issuer="a", audience="b", capabilities=[cap],
                            expiry=time.time() - 1)
        chain = DelegationChain(tokens=[t])
        valid, reason = chain.is_valid_chain()
        assert not valid

    def test_covers_matching_capability(self):
        chain, _ = self._make_chain()
        assert chain.covers("tools://invoke", "call")

    def test_does_not_cover_unrelated_capability(self):
        chain, _ = self._make_chain()
        assert not chain.covers("admin://settings", "write")

    def test_empty_chain(self):
        from ipfs_datasets_py.mcp_server.ucan_delegation import DelegationChain
        chain = DelegationChain(tokens=[])
        valid, _ = chain.is_valid_chain()
        assert not valid
        assert chain.root_issuer is None
        assert chain.leaf_audience is None


class TestDelegationEvaluator:

    def _build_two_token_chain(self):
        from ipfs_datasets_py.mcp_server.ucan_delegation import (
            DelegationToken, DelegationEvaluator, Capability,
        )
        cap = Capability(resource="tools://invoke", ability="call")
        root = DelegationToken(issuer="did:root", audience="did:alice", capabilities=[cap])
        leaf = DelegationToken(
            issuer="did:alice", audience="did:bob",
            capabilities=[cap], proof_cid=None,
        )
        # Manual proof_cid: leaf proof is root
        leaf_with_proof = DelegationToken(
            issuer="did:alice", audience="did:bob",
            capabilities=[cap],
            proof_cid=root.cid,
        )
        ev = DelegationEvaluator()
        ev.add_token(root)
        leaf_cid = ev.add_token(leaf_with_proof)
        return ev, leaf_cid

    def test_add_token_returns_cid(self):
        from ipfs_datasets_py.mcp_server.ucan_delegation import (
            DelegationToken, DelegationEvaluator, Capability,
        )
        ev = DelegationEvaluator()
        tok = DelegationToken(
            issuer="a", audience="b",
            capabilities=[Capability(resource="*", ability="*")],
        )
        cid = ev.add_token(tok)
        assert cid == tok.cid

    def test_get_token_returns_stored(self):
        from ipfs_datasets_py.mcp_server.ucan_delegation import (
            DelegationToken, DelegationEvaluator, Capability,
        )
        ev = DelegationEvaluator()
        tok = DelegationToken(
            issuer="a", audience="b",
            capabilities=[Capability(resource="*", ability="*")],
        )
        cid = ev.add_token(tok)
        assert ev.get_token(cid) is tok

    def test_get_token_unknown_returns_none(self):
        from ipfs_datasets_py.mcp_server.ucan_delegation import DelegationEvaluator
        ev = DelegationEvaluator()
        assert ev.get_token("sha256:nonexistent") is None

    def test_can_invoke_success(self):
        ev, leaf_cid = self._build_two_token_chain()
        allowed, reason = ev.can_invoke(
            "did:bob", "tools://invoke", "call", leaf_cid=leaf_cid
        )
        assert allowed, reason

    def test_can_invoke_wrong_principal(self):
        ev, leaf_cid = self._build_two_token_chain()
        allowed, reason = ev.can_invoke(
            "did:charlie", "tools://invoke", "call", leaf_cid=leaf_cid
        )
        assert not allowed

    def test_can_invoke_unknown_cid(self):
        from ipfs_datasets_py.mcp_server.ucan_delegation import DelegationEvaluator
        ev = DelegationEvaluator()
        allowed, reason = ev.can_invoke(
            "did:nobody", "r", "a", leaf_cid="sha256:missing"
        )
        assert not allowed
        assert "Unknown token" in reason

    def test_can_invoke_unmatched_capability(self):
        ev, leaf_cid = self._build_two_token_chain()
        allowed, reason = ev.can_invoke(
            "did:bob", "admin://settings", "write", leaf_cid=leaf_cid
        )
        assert not allowed

    def test_build_chain_single_token(self):
        from ipfs_datasets_py.mcp_server.ucan_delegation import (
            DelegationToken, DelegationEvaluator, Capability,
        )
        ev = DelegationEvaluator()
        tok = DelegationToken(
            issuer="root", audience="leaf",
            capabilities=[Capability(resource="*", ability="*")],
        )
        cid = ev.add_token(tok)
        chain = ev.build_chain(cid)
        assert len(chain.tokens) == 1
        assert chain.root_issuer == "root"

    def test_global_singleton(self):
        from ipfs_datasets_py.mcp_server.ucan_delegation import (
            get_delegation_evaluator, DelegationEvaluator,
        )
        e1 = get_delegation_evaluator()
        e2 = get_delegation_evaluator()
        assert e1 is e2
        assert isinstance(e1, DelegationEvaluator)


# ════════════════════════════════════════════════════════════════════════════
# AE89  InterfaceDescriptor hook (smoke tests)
# ════════════════════════════════════════════════════════════════════════════

class TestInterfaceDescriptorHook:
    """Verify that the new spec modules import cleanly and work together."""

    def test_all_three_modules_importable(self):
        import ipfs_datasets_py.mcp_server.interface_descriptor as _a
        import ipfs_datasets_py.mcp_server.cid_artifacts as _b
        import ipfs_datasets_py.mcp_server.temporal_policy as _d
        import ipfs_datasets_py.mcp_server.ucan_delegation as _c
        assert _a is not None
        assert _b is not None
        assert _c is not None
        assert _d is not None

    def test_compute_cid_stable_across_modules(self):
        from ipfs_datasets_py.mcp_server.interface_descriptor import compute_cid, _canonicalize
        from ipfs_datasets_py.mcp_server.cid_artifacts import artifact_cid

        data = {"tool": "mytool", "version": "1.0"}
        cid1 = compute_cid(_canonicalize(data))
        cid2 = artifact_cid(data)
        assert cid1 == cid2

    def test_intent_to_policy_to_decision_chain(self):
        """End-to-end: create intent → register policy → evaluate → check decision."""
        from ipfs_datasets_py.mcp_server.cid_artifacts import IntentObject, ALLOW
        from ipfs_datasets_py.mcp_server.temporal_policy import (
            PolicyRegistry, make_simple_permission_policy,
        )

        intent = IntentObject(tool="search")
        reg = PolicyRegistry()
        pol = make_simple_permission_policy(policy_id="smoke", allowed_tools=["search"])
        cid = reg.register(pol)
        decision = reg.evaluate(intent, cid)
        assert decision.decision == ALLOW
        assert decision.intent_cid == intent.cid

    def test_ucan_delegation_chain_with_policy_evaluation(self):
        """UCAN chain grants capability; policy registry allows tool."""
        from ipfs_datasets_py.mcp_server.ucan_delegation import (
            DelegationToken, DelegationEvaluator, Capability,
        )
        from ipfs_datasets_py.mcp_server.cid_artifacts import IntentObject, ALLOW
        from ipfs_datasets_py.mcp_server.temporal_policy import (
            PolicyRegistry, make_simple_permission_policy,
        )

        # UCAN: root → alice → bob for tools://search
        cap = Capability(resource="tools://search", ability="call")
        root = DelegationToken(issuer="did:root", audience="did:alice", capabilities=[cap])
        leaf = DelegationToken(issuer="did:alice", audience="did:bob",
                               capabilities=[cap], proof_cid=root.cid)
        ev = DelegationEvaluator()
        ev.add_token(root)
        leaf_cid = ev.add_token(leaf)

        allowed, reason = ev.can_invoke(
            "did:bob", "tools://search", "call", leaf_cid=leaf_cid
        )
        assert allowed, reason

        # Policy: search is permitted
        reg = PolicyRegistry()
        pol = make_simple_permission_policy(policy_id="p", allowed_tools=["search"])
        pcid = reg.register(pol)
        intent = IntentObject(tool="search")
        decision = reg.evaluate(intent, pcid)
        assert decision.decision == ALLOW
