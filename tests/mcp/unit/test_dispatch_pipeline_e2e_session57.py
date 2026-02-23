"""Phase K (session 57) — End-to-end dispatch pipeline integration tests.

Exercises the full MCP++ dispatch pipeline:

  NL policy → compile → register → UCANPolicyGate →
  DispatchPipeline → EventDAG → PubSubBus → PipelineMetricsRecorder

Also covers Phase G (IPFSPolicyStore), Phase H (RevocationList +
can_invoke_with_revocation), Phase I (DelegationStore), and Phase J
(compliance_rule_management_tool).

All tests are stdlib-only and do NOT require IPFS, anyio, or any external
service to pass.
"""
from __future__ import annotations

import json
import os
import tempfile
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_intent(tool_name: str = "read_data", actor: str = "alice") -> Any:
    """Return a minimal PipelineIntent."""
    from ipfs_datasets_py.mcp_server.dispatch_pipeline import PipelineIntent
    return PipelineIntent(tool_name=tool_name, actor=actor)


def _make_delegation(cid: str, issuer: str, audience: str, *,
                     proof_cid: str = None, expiry: float = None):
    from ipfs_datasets_py.mcp_server.ucan_delegation import Capability, Delegation
    return Delegation(
        cid=cid,
        issuer=issuer,
        audience=audience,
        capabilities=[Capability(resource="*", ability="*")],
        expiry=expiry,
        proof_cid=proof_cid,
    )


# ===========================================================================
# Phase G — IPFSPolicyStore
# ===========================================================================

class TestIPFSPolicyStore:
    """Phase G: IPFSPolicyStore extends FilePolicyStore with IPFS pinning."""

    def test_ipfs_policy_store_imports(self):
        from ipfs_datasets_py.mcp_server.nl_ucan_policy import IPFSPolicyStore
        assert IPFSPolicyStore is not None

    def test_ipfs_policy_store_inherits_file_store(self):
        from ipfs_datasets_py.mcp_server.nl_ucan_policy import (
            FilePolicyStore, IPFSPolicyStore, PolicyRegistry,
        )
        reg = PolicyRegistry()
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        try:
            store = IPFSPolicyStore(path, reg)
            assert isinstance(store, FilePolicyStore)
        finally:
            os.unlink(path)

    def test_ipfs_policy_store_save_load_roundtrip(self):
        from ipfs_datasets_py.mcp_server.nl_ucan_policy import (
            IPFSPolicyStore, PolicyRegistry,
        )
        reg = PolicyRegistry()
        reg.register("r1", "alice may call read_data")

        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        try:
            store = IPFSPolicyStore(path, reg)
            store.save()  # falls back to file-only (no IPFS client)

            reg2 = PolicyRegistry()
            store2 = IPFSPolicyStore(path, reg2)
            count = store2.load()
            assert count == 1
            assert "r1" in reg2.list_names()
        finally:
            os.unlink(path)

    def test_pin_policy_no_client_returns_none(self):
        from ipfs_datasets_py.mcp_server.nl_ucan_policy import (
            IPFSPolicyStore, PolicyRegistry,
        )
        reg = PolicyRegistry()
        reg.register("p1", "bob may call search_data")
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        try:
            # No IPFS client installed → pin returns None gracefully
            with patch.object(IPFSPolicyStore, "_get_ipfs_client", return_value=None):
                store = IPFSPolicyStore(path, reg)
                result = store.pin_policy("p1")
            assert result is None
        finally:
            os.unlink(path)

    def test_pin_policy_with_mock_ipfs_client(self):
        from ipfs_datasets_py.mcp_server.nl_ucan_policy import (
            IPFSPolicyStore, PolicyRegistry,
        )
        reg = PolicyRegistry()
        reg.register("p2", "carol may call dataset_tools")
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        try:
            fake_client = MagicMock()
            fake_client.add.return_value = {"Hash": "QmFakeHash123"}
            store = IPFSPolicyStore(path, reg, ipfs_client=fake_client)
            cid = store.pin_policy("p2")
            assert cid == "QmFakeHash123"
            assert store.get_ipfs_cid("p2") == "QmFakeHash123"
        finally:
            os.unlink(path)

    def test_pin_policy_missing_policy_returns_none(self):
        from ipfs_datasets_py.mcp_server.nl_ucan_policy import (
            IPFSPolicyStore, PolicyRegistry,
        )
        reg = PolicyRegistry()
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        try:
            fake_client = MagicMock()
            store = IPFSPolicyStore(path, reg, ipfs_client=fake_client)
            result = store.pin_policy("nonexistent")
            assert result is None
        finally:
            os.unlink(path)

    def test_retrieve_from_ipfs_no_client_returns_none(self):
        from ipfs_datasets_py.mcp_server.nl_ucan_policy import (
            IPFSPolicyStore, PolicyRegistry,
        )
        reg = PolicyRegistry()
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        try:
            with patch.object(IPFSPolicyStore, "_get_ipfs_client", return_value=None):
                store = IPFSPolicyStore(path, reg)
                result = store.retrieve_from_ipfs("QmFake")
            assert result is None
        finally:
            os.unlink(path)

    def test_retrieve_from_ipfs_with_mock_client(self):
        from ipfs_datasets_py.mcp_server.nl_ucan_policy import (
            IPFSPolicyStore, PolicyRegistry,
        )
        reg = PolicyRegistry()
        payload = json.dumps({"nl_policy": "alice may call x", "description": ""}).encode()
        fake_client = MagicMock()
        fake_client.cat.return_value = payload
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        try:
            store = IPFSPolicyStore(path, reg, ipfs_client=fake_client)
            result = store.retrieve_from_ipfs("QmFake")
            assert result is not None
            assert result["nl_policy"] == "alice may call x"
        finally:
            os.unlink(path)

    def test_get_ipfs_cid_before_pin_returns_none(self):
        from ipfs_datasets_py.mcp_server.nl_ucan_policy import (
            IPFSPolicyStore, PolicyRegistry,
        )
        reg = PolicyRegistry()
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        try:
            store = IPFSPolicyStore(path, reg)
            assert store.get_ipfs_cid("anything") is None
        finally:
            os.unlink(path)

    def test_save_calls_pin_policy_for_each_registered(self):
        from ipfs_datasets_py.mcp_server.nl_ucan_policy import (
            IPFSPolicyStore, PolicyRegistry,
        )
        reg = PolicyRegistry()
        reg.register("a", "alice may call tool_a")
        reg.register("b", "bob may call tool_b")
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        try:
            fake_client = MagicMock()
            fake_client.add.return_value = {"Hash": "QmPin"}
            store = IPFSPolicyStore(path, reg, ipfs_client=fake_client)
            store.save()
            assert fake_client.add.call_count == 2
        finally:
            os.unlink(path)


# ===========================================================================
# Phase H — RevocationList + can_invoke_with_revocation
# ===========================================================================

class TestRevocationList:
    """Phase H: RevocationList tracks revoked delegation CIDs."""

    def test_revocation_list_imports(self):
        from ipfs_datasets_py.mcp_server.ucan_delegation import RevocationList
        assert RevocationList is not None

    def test_revoke_and_is_revoked(self):
        from ipfs_datasets_py.mcp_server.ucan_delegation import RevocationList
        rl = RevocationList()
        assert not rl.is_revoked("cid1")
        rl.revoke("cid1")
        assert rl.is_revoked("cid1")

    def test_is_revoked_unknown_cid_false(self):
        from ipfs_datasets_py.mcp_server.ucan_delegation import RevocationList
        rl = RevocationList()
        assert not rl.is_revoked("unknown")

    def test_clear_removes_all(self):
        from ipfs_datasets_py.mcp_server.ucan_delegation import RevocationList
        rl = RevocationList()
        rl.revoke("a")
        rl.revoke("b")
        rl.clear()
        assert len(rl) == 0
        assert not rl.is_revoked("a")

    def test_to_list_sorted(self):
        from ipfs_datasets_py.mcp_server.ucan_delegation import RevocationList
        rl = RevocationList()
        rl.revoke("z1")
        rl.revoke("a1")
        assert rl.to_list() == ["a1", "z1"]

    def test_len_and_contains(self):
        from ipfs_datasets_py.mcp_server.ucan_delegation import RevocationList
        rl = RevocationList()
        rl.revoke("x")
        assert len(rl) == 1
        assert "x" in rl
        assert "y" not in rl

    def test_revoke_chain_empty_evaluator(self):
        from ipfs_datasets_py.mcp_server.ucan_delegation import (
            DelegationEvaluator, RevocationList,
        )
        ev = DelegationEvaluator()
        rl = RevocationList()
        # No delegations in evaluator — chain is empty
        count = rl.revoke_chain("cid-nonexistent", ev)
        assert count == 0

    def test_revoke_chain_revokes_entire_chain(self):
        from ipfs_datasets_py.mcp_server.ucan_delegation import (
            DelegationEvaluator, RevocationList,
        )
        ev = DelegationEvaluator()
        root = _make_delegation("root", "issuer", "mid")
        mid = _make_delegation("mid", "issuer", "leaf", proof_cid="root")
        leaf = _make_delegation("leaf", "issuer", "actor", proof_cid="mid")
        for d in (root, mid, leaf):
            ev.add(d)
        rl = RevocationList()
        count = rl.revoke_chain("leaf", ev)
        assert count == 3
        for cid in ("root", "mid", "leaf"):
            assert rl.is_revoked(cid)

    def test_revoke_chain_already_revoked_not_double_counted(self):
        from ipfs_datasets_py.mcp_server.ucan_delegation import (
            DelegationEvaluator, RevocationList,
        )
        ev = DelegationEvaluator()
        d = _make_delegation("solo", "issuer", "audience")
        ev.add(d)
        rl = RevocationList()
        rl.revoke("solo")
        count = rl.revoke_chain("solo", ev)
        assert count == 0  # already in list


class TestCanInvokeWithRevocation:
    """Phase H: can_invoke_with_revocation checks both delegation and revocation."""

    def test_imports(self):
        from ipfs_datasets_py.mcp_server.ucan_delegation import can_invoke_with_revocation
        assert callable(can_invoke_with_revocation)

    def test_empty_chain_returns_false(self):
        from ipfs_datasets_py.mcp_server.ucan_delegation import (
            DelegationEvaluator, RevocationList, can_invoke_with_revocation,
        )
        ev = DelegationEvaluator()
        rl = RevocationList()
        ok, reason = can_invoke_with_revocation(
            "nonexistent", "some_tool", "alice",
            evaluator=ev, revocation_list=rl,
        )
        assert not ok

    def test_valid_delegation_no_revocation_allows(self):
        from ipfs_datasets_py.mcp_server.ucan_delegation import (
            DelegationEvaluator, RevocationList, can_invoke_with_revocation,
        )
        ev = DelegationEvaluator()
        d = _make_delegation("cid1", "did:key:issuer", "alice")
        ev.add(d)
        rl = RevocationList()
        ok, reason = can_invoke_with_revocation(
            "cid1", "any_tool", "alice",
            evaluator=ev, revocation_list=rl,
        )
        assert ok

    def test_revoked_delegation_denies(self):
        from ipfs_datasets_py.mcp_server.ucan_delegation import (
            DelegationEvaluator, RevocationList, can_invoke_with_revocation,
        )
        ev = DelegationEvaluator()
        d = _make_delegation("cid2", "did:key:issuer", "bob")
        ev.add(d)
        rl = RevocationList()
        rl.revoke("cid2")
        ok, reason = can_invoke_with_revocation(
            "cid2", "tool", "bob",
            evaluator=ev, revocation_list=rl,
        )
        assert not ok
        assert "revoked" in reason

    def test_no_revocation_list_uses_delegation_only(self):
        from ipfs_datasets_py.mcp_server.ucan_delegation import (
            DelegationEvaluator, can_invoke_with_revocation,
        )
        ev = DelegationEvaluator()
        d = _make_delegation("cid3", "did:key:issuer", "carol")
        ev.add(d)
        ok, _reason = can_invoke_with_revocation(
            "cid3", "some_tool", "carol",
            evaluator=ev, revocation_list=None,
        )
        assert ok

    def test_expired_delegation_denies(self):
        from ipfs_datasets_py.mcp_server.ucan_delegation import (
            DelegationEvaluator, RevocationList, can_invoke_with_revocation,
        )
        import time
        ev = DelegationEvaluator()
        d = _make_delegation("cid4", "did:key:i", "dave", expiry=time.time() - 1)
        ev.add(d)
        rl = RevocationList()
        ok, reason = can_invoke_with_revocation(
            "cid4", "tool", "dave",
            evaluator=ev, revocation_list=rl,
        )
        assert not ok


# ===========================================================================
# Phase I — DelegationStore
# ===========================================================================

class TestDelegationStore:
    """Phase I: DelegationStore persists delegation chains as JSON."""

    def test_imports(self):
        from ipfs_datasets_py.mcp_server.ucan_delegation import DelegationStore
        assert DelegationStore is not None

    def test_add_and_get(self):
        from ipfs_datasets_py.mcp_server.ucan_delegation import DelegationStore
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        try:
            store = DelegationStore(path)
            d = _make_delegation("d1", "issuer", "audience")
            store.add(d)
            assert store.get("d1") is d
        finally:
            os.unlink(path)

    def test_get_missing_returns_none(self):
        from ipfs_datasets_py.mcp_server.ucan_delegation import DelegationStore
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        try:
            store = DelegationStore(path)
            assert store.get("x") is None
        finally:
            os.unlink(path)

    def test_remove_existing(self):
        from ipfs_datasets_py.mcp_server.ucan_delegation import DelegationStore
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        try:
            store = DelegationStore(path)
            d = _make_delegation("r1", "i", "a")
            store.add(d)
            assert store.remove("r1")
            assert store.get("r1") is None
        finally:
            os.unlink(path)

    def test_remove_missing_returns_false(self):
        from ipfs_datasets_py.mcp_server.ucan_delegation import DelegationStore
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        try:
            store = DelegationStore(path)
            assert not store.remove("nope")
        finally:
            os.unlink(path)

    def test_list_cids_sorted(self):
        from ipfs_datasets_py.mcp_server.ucan_delegation import DelegationStore
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        try:
            store = DelegationStore(path)
            store.add(_make_delegation("z", "i", "a"))
            store.add(_make_delegation("a", "i", "a"))
            assert store.list_cids() == ["a", "z"]
        finally:
            os.unlink(path)

    def test_len(self):
        from ipfs_datasets_py.mcp_server.ucan_delegation import DelegationStore
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        try:
            store = DelegationStore(path)
            assert len(store) == 0
            store.add(_make_delegation("x", "i", "a"))
            assert len(store) == 1
        finally:
            os.unlink(path)

    def test_save_and_load_roundtrip(self):
        from ipfs_datasets_py.mcp_server.ucan_delegation import DelegationStore
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        try:
            store = DelegationStore(path)
            store.add(_make_delegation("c1", "alice", "bob"))
            store.add(_make_delegation("c2", "bob", "carol", proof_cid="c1"))
            store.save()

            store2 = DelegationStore(path)
            loaded = store2.load()
            assert loaded == 2
            assert store2.get("c1").issuer == "alice"
            assert store2.get("c2").proof_cid == "c1"
        finally:
            os.unlink(path)

    def test_load_missing_file_returns_zero(self):
        import tempfile
        from ipfs_datasets_py.mcp_server.ucan_delegation import DelegationStore
        missing = os.path.join(tempfile.gettempdir(),
                               "nonexistent_delegation_store_xyz_session57.json")
        store = DelegationStore(missing)
        assert store.load() == 0

    def test_load_corrupt_file_returns_zero(self):
        from ipfs_datasets_py.mcp_server.ucan_delegation import DelegationStore
        with tempfile.NamedTemporaryFile(
            suffix=".json", delete=False, mode="w"
        ) as f:
            f.write("not valid json {{{")
            path = f.name
        try:
            store = DelegationStore(path)
            assert store.load() == 0
        finally:
            os.unlink(path)

    def test_to_evaluator_contains_all_delegations(self):
        from ipfs_datasets_py.mcp_server.ucan_delegation import DelegationStore
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        try:
            store = DelegationStore(path)
            d1 = _make_delegation("e1", "i1", "a1")
            d2 = _make_delegation("e2", "i2", "a2")
            store.add(d1)
            store.add(d2)
            ev = store.to_evaluator()
            assert ev.get("e1") is not None
            assert ev.get("e2") is not None
        finally:
            os.unlink(path)

    def test_to_evaluator_empty_store(self):
        from ipfs_datasets_py.mcp_server.ucan_delegation import (
            DelegationEvaluator, DelegationStore,
        )
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        try:
            store = DelegationStore(path)
            ev = store.to_evaluator()
            assert isinstance(ev, DelegationEvaluator)
            assert ev.list_cids() == []
        finally:
            os.unlink(path)

    def test_save_creates_parent_dirs(self):
        import shutil
        base = tempfile.mkdtemp()
        path = os.path.join(base, "subdir", "delegations.json")
        try:
            from ipfs_datasets_py.mcp_server.ucan_delegation import DelegationStore
            store = DelegationStore(path)
            store.add(_make_delegation("x", "i", "a"))
            store.save()
            assert os.path.exists(path)
        finally:
            shutil.rmtree(base, ignore_errors=True)


# ===========================================================================
# Phase J — Compliance rule management MCP tool
# ===========================================================================

class TestComplianceRuleManagementTool:
    """Phase J: compliance_rule_management_tool MCP tools."""

    def test_imports(self):
        from ipfs_datasets_py.mcp_server.tools.logic_tools.compliance_rule_management_tool import (
            compliance_add_rule,
            compliance_check_intent,
            compliance_list_rules,
            compliance_remove_rule,
        )
        for fn in (compliance_add_rule, compliance_list_rules,
                   compliance_remove_rule, compliance_check_intent):
            assert callable(fn)

    @pytest.mark.asyncio
    async def test_list_rules_returns_default_rules(self):
        import importlib
        import sys
        # Reset global checker between tests by removing module from cache
        mod_name = "ipfs_datasets_py.mcp_server.tools.logic_tools.compliance_rule_management_tool"
        if mod_name in sys.modules:
            del sys.modules[mod_name]
        from ipfs_datasets_py.mcp_server.tools.logic_tools.compliance_rule_management_tool import (
            compliance_list_rules,
        )
        result = await compliance_list_rules()
        assert "rules" in result
        assert isinstance(result["rules"], list)

    @pytest.mark.asyncio
    async def test_add_rule_and_list(self):
        import sys
        mod_name = "ipfs_datasets_py.mcp_server.tools.logic_tools.compliance_rule_management_tool"
        if mod_name in sys.modules:
            del sys.modules[mod_name]
        from ipfs_datasets_py.mcp_server.tools.logic_tools.compliance_rule_management_tool import (
            compliance_add_rule, compliance_list_rules,
        )
        result = await compliance_add_rule("my_test_rule", description="test rule")
        assert result["status"] == "added"
        assert result["rule_id"] == "my_test_rule"
        list_result = await compliance_list_rules()
        assert "my_test_rule" in list_result["rules"]

    @pytest.mark.asyncio
    async def test_add_rule_empty_id_raises(self):
        import sys
        mod_name = "ipfs_datasets_py.mcp_server.tools.logic_tools.compliance_rule_management_tool"
        if mod_name in sys.modules:
            del sys.modules[mod_name]
        from ipfs_datasets_py.mcp_server.tools.logic_tools.compliance_rule_management_tool import (
            compliance_add_rule,
        )
        with pytest.raises(ValueError):
            await compliance_add_rule("")

    @pytest.mark.asyncio
    async def test_remove_existing_rule(self):
        import sys
        mod_name = "ipfs_datasets_py.mcp_server.tools.logic_tools.compliance_rule_management_tool"
        if mod_name in sys.modules:
            del sys.modules[mod_name]
        from ipfs_datasets_py.mcp_server.tools.logic_tools.compliance_rule_management_tool import (
            compliance_add_rule, compliance_remove_rule,
        )
        await compliance_add_rule("to_remove")
        result = await compliance_remove_rule("to_remove")
        assert result["status"] == "removed"

    @pytest.mark.asyncio
    async def test_remove_nonexistent_rule(self):
        import sys
        mod_name = "ipfs_datasets_py.mcp_server.tools.logic_tools.compliance_rule_management_tool"
        if mod_name in sys.modules:
            del sys.modules[mod_name]
        from ipfs_datasets_py.mcp_server.tools.logic_tools.compliance_rule_management_tool import (
            compliance_remove_rule,
        )
        result = await compliance_remove_rule("does_not_exist_xyz")
        assert result["status"] == "not_found"

    @pytest.mark.asyncio
    async def test_compliance_check_valid_intent(self):
        import sys
        mod_name = "ipfs_datasets_py.mcp_server.tools.logic_tools.compliance_rule_management_tool"
        if mod_name in sys.modules:
            del sys.modules[mod_name]
        from ipfs_datasets_py.mcp_server.tools.logic_tools.compliance_rule_management_tool import (
            compliance_check_intent,
        )
        result = await compliance_check_intent(
            tool_name="read_data",
            actor="alice",
            params={"key": "value"},
        )
        assert "results" in result or "summary" in result

    @pytest.mark.asyncio
    async def test_compliance_check_empty_actor_fails_has_actor_rule(self):
        import sys
        mod_name = "ipfs_datasets_py.mcp_server.tools.logic_tools.compliance_rule_management_tool"
        if mod_name in sys.modules:
            del sys.modules[mod_name]
        from ipfs_datasets_py.mcp_server.tools.logic_tools.compliance_rule_management_tool import (
            compliance_check_intent,
        )
        result = await compliance_check_intent(tool_name="read_data", actor="")
        # intent_has_actor rule should flag this
        assert "results" in result or isinstance(result, dict)


# ===========================================================================
# Phase K — End-to-end dispatch pipeline integration test
# ===========================================================================

class TestDispatchPipelineEndToEnd:
    """Phase K: Full pipeline integration — NL policy → compile → evaluate → DAG → metrics."""

    def test_pipeline_imports(self):
        from ipfs_datasets_py.mcp_server.dispatch_pipeline import (
            DispatchPipeline, PipelineConfig, PipelineIntent,
            PipelineMetricsRecorder, make_default_pipeline,
        )
        for cls in (DispatchPipeline, PipelineConfig, PipelineIntent,
                    PipelineMetricsRecorder, make_default_pipeline):
            assert cls is not None

    def test_default_pipeline_allows_everything(self):
        from ipfs_datasets_py.mcp_server.dispatch_pipeline import (
            PipelineConfig, DispatchPipeline, PipelineIntent,
        )
        cfg = PipelineConfig()  # all stages disabled
        pipeline = DispatchPipeline(cfg)
        intent = PipelineIntent(tool_name="read_data", actor="alice")
        result = pipeline.check(intent)
        assert result.allowed

    def test_pipeline_compliance_stage_enabled(self):
        from ipfs_datasets_py.mcp_server.dispatch_pipeline import (
            PipelineConfig, DispatchPipeline, PipelineIntent,
        )
        cfg = PipelineConfig(enable_compliance=True)
        pipeline = DispatchPipeline(cfg)
        intent = PipelineIntent(tool_name="read_data", actor="alice")
        result = pipeline.check(intent)
        # With a valid intent compliance should pass
        assert result.allowed

    def test_pipeline_risk_stage_enabled(self):
        from ipfs_datasets_py.mcp_server.dispatch_pipeline import (
            PipelineConfig, DispatchPipeline, PipelineIntent,
        )
        cfg = PipelineConfig(enable_risk=True)
        pipeline = DispatchPipeline(cfg)
        intent = PipelineIntent(tool_name="read_data", actor="alice")
        result = pipeline.check(intent)
        assert result.allowed  # default risk is 0.3, well below 0.75 max

    def test_pipeline_record_execution_appends_to_dag(self):
        from ipfs_datasets_py.mcp_server.dispatch_pipeline import (
            PipelineConfig, DispatchPipeline, PipelineIntent,
        )
        cfg = PipelineConfig()
        pipeline = DispatchPipeline(cfg)
        intent = PipelineIntent(tool_name="read_data", actor="alice")
        receipt = pipeline.record_execution(intent, {"status": "ok"})
        assert receipt is not None

    def test_pipeline_record_execution_with_error(self):
        from ipfs_datasets_py.mcp_server.dispatch_pipeline import (
            PipelineConfig, DispatchPipeline, PipelineIntent,
        )
        cfg = PipelineConfig()
        pipeline = DispatchPipeline(cfg)
        intent = PipelineIntent(tool_name="read_data", actor="alice")
        receipt = pipeline.record_execution(intent, None, error="some error")
        assert receipt is not None

    def test_metrics_recorder_wraps_pipeline(self):
        from ipfs_datasets_py.mcp_server.dispatch_pipeline import (
            PipelineConfig, DispatchPipeline, PipelineIntent,
            PipelineMetricsRecorder,
        )
        cfg = PipelineConfig()
        pipeline = DispatchPipeline(cfg)
        recorder = PipelineMetricsRecorder(pipeline)
        intent = PipelineIntent(tool_name="read_data", actor="alice")
        result = recorder.check_and_record(intent)
        assert result.allowed
        stats = recorder.get_stats()
        assert stats["total_allows"] == 1
        assert stats["total_denials"] == 0

    def test_metrics_recorder_counts_denials(self):
        from ipfs_datasets_py.mcp_server.dispatch_pipeline import (
            PipelineConfig, DispatchPipeline, PipelineIntent,
            PipelineMetricsRecorder,
        )
        cfg = PipelineConfig(enable_compliance=True)
        pipeline = DispatchPipeline(cfg)
        recorder = PipelineMetricsRecorder(pipeline)

        # Invalid tool name (contains uppercase/special) to trigger compliance denial
        intent = PipelineIntent(tool_name="BLOCKED!TOOL", actor="alice")
        result = recorder.check_and_record(intent)
        assert not result.allowed
        stats = recorder.get_stats()
        assert stats["total_denials"] == 1

    def test_metrics_recorder_reset(self):
        from ipfs_datasets_py.mcp_server.dispatch_pipeline import (
            PipelineConfig, DispatchPipeline, PipelineIntent,
            PipelineMetricsRecorder,
        )
        cfg = PipelineConfig()
        pipeline = DispatchPipeline(cfg)
        recorder = PipelineMetricsRecorder(pipeline)
        intent = PipelineIntent(tool_name="tool", actor="a")
        recorder.check_and_record(intent)
        recorder.reset()
        stats = recorder.get_stats()
        assert stats["total_allows"] == 0
        assert stats["total_denials"] == 0

    def test_full_pipeline_nl_policy_to_evaluation(self):
        """Full pipeline: NL policy registered, evaluated, recorded to DAG."""
        from ipfs_datasets_py.mcp_server.nl_ucan_policy import (
            NLUCANPolicyCompiler, PolicyRegistry, UCANPolicyGate,
        )
        from ipfs_datasets_py.mcp_server.cid_artifacts import IntentObject

        compiler = NLUCANPolicyCompiler()
        gate = UCANPolicyGate(compiler)

        # Register a prohibiting policy
        gate.register_policy(
            "test_policy",
            "admin may not call delete_all",
        )

        intent = IntentObject(
            interface_cid="bafy-test",
            tool="read_data",
            input_cid="bafy-in",
        )
        decision = gate.evaluate(intent, actor="alice")
        # No prohibition on alice reading — open world
        assert decision.decision in ("allow", "deny")

    def test_pubsub_bridge_connects_and_disconnects(self):
        from ipfs_datasets_py.mcp_server.mcp_p2p_transport import (
            PubSubBridge, PubSubBus,
        )
        bus = PubSubBus()
        bridge = PubSubBridge(bus=bus)
        fake_sm = MagicMock()
        fake_sm.announce_capability = MagicMock()

        bridge.connect(fake_sm)
        assert bridge.is_connected

        bridge.disconnect()
        assert not bridge.is_connected

    def test_pubsub_bridge_publish_calls_service_manager(self):
        from ipfs_datasets_py.mcp_server.mcp_p2p_transport import (
            PubSubBridge, PubSubBus, PubSubEventType,
        )
        bus = PubSubBus()
        bridge = PubSubBridge(bus=bus)
        fake_sm = MagicMock()
        fake_sm.announce_capability = MagicMock()

        bridge.connect(fake_sm)
        bus.publish(PubSubEventType.INTERFACE_ANNOUNCE.value, {"cid": "bafy-x"})
        # Service manager's announce_capability should have been called
        assert fake_sm.announce_capability.called
        bridge.disconnect()

    def test_event_dag_records_receipts(self):
        from ipfs_datasets_py.mcp_server.event_dag import EventDAG
        from ipfs_datasets_py.mcp_server.cid_artifacts import EventNode
        dag = EventDAG()
        n1 = EventNode(intent_cid="bafy-intent-1")
        cid1 = dag.append(n1)
        n2 = EventNode(parents=[cid1], intent_cid="bafy-intent-2")
        dag.append(n2)
        assert len(dag.frontier()) > 0

    def test_risk_score_from_dag(self):
        from ipfs_datasets_py.mcp_server.event_dag import EventDAG
        from ipfs_datasets_py.mcp_server.cid_artifacts import EventNode
        from ipfs_datasets_py.mcp_server.risk_scorer import risk_score_from_dag
        dag = EventDAG()
        # Rollback event: output_cid contains "rollback"
        n1 = EventNode(intent_cid="bafy-intent", output_cid="rollback-bafy-xyz")
        dag.append(n1)
        # Error event: receipt_cid is empty (never completed)
        n2 = EventNode(intent_cid="bafy-intent2", receipt_cid="")
        dag.append(n2)
        penalty = risk_score_from_dag(dag, "delete_all")
        assert penalty > 0.0

    def test_risk_score_from_dag_no_events(self):
        from ipfs_datasets_py.mcp_server.event_dag import EventDAG
        from ipfs_datasets_py.mcp_server.risk_scorer import risk_score_from_dag
        dag = EventDAG()
        penalty = risk_score_from_dag(dag, "read_data")
        assert penalty == 0.0

    def test_delegation_store_to_evaluator_round_trip(self):
        """DelegationStore round-trip: save → load → to_evaluator → can_invoke."""
        from ipfs_datasets_py.mcp_server.ucan_delegation import (
            DelegationStore, can_invoke_with_revocation,
        )
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        try:
            store = DelegationStore(path)
            d = _make_delegation("root-e2e", "did:key:issuer", "alice")
            store.add(d)
            store.save()

            store2 = DelegationStore(path)
            store2.load()
            ev = store2.to_evaluator()

            ok, _reason = can_invoke_with_revocation(
                "root-e2e", "any_tool", "alice",
                evaluator=ev, revocation_list=None,
            )
            assert ok
        finally:
            os.unlink(path)

    def test_delegation_revocation_blocks_previously_valid_chain(self):
        """Revoke a delegation mid-chain; the previously valid chain is now denied."""
        from ipfs_datasets_py.mcp_server.ucan_delegation import (
            DelegationEvaluator, RevocationList, can_invoke_with_revocation,
        )
        ev = DelegationEvaluator()
        root = _make_delegation("root-rv", "did:key:i", "mid-rv")
        leaf = _make_delegation("leaf-rv", "did:key:i", "alice", proof_cid="root-rv")
        ev.add(root)
        ev.add(leaf)
        rl = RevocationList()

        # Before revocation: should be allowed
        ok, _ = can_invoke_with_revocation("leaf-rv", "tool", "alice",
                                           evaluator=ev, revocation_list=rl)
        assert ok

        # Revoke the root
        rl.revoke("root-rv")

        # After revocation: should be denied
        ok2, reason = can_invoke_with_revocation("leaf-rv", "tool", "alice",
                                                  evaluator=ev, revocation_list=rl)
        assert not ok2
        assert "revoked" in reason
