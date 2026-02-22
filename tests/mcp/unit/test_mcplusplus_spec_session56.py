"""Session 56 tests: async policy registration, persistent policy store,
PubSubBus↔P2PServiceManager bridge, pipeline metrics recorder, DID delegation signing.

All 5 items from MASTER_IMPROVEMENT_PLAN_2026_v11.md "Next Steps" are exercised here.
"""
from __future__ import annotations

import json
import os
import tempfile
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

def _fresh_registry():
    """Return a new isolated PolicyRegistry (not the global singleton)."""
    from ipfs_datasets_py.mcp_server.nl_ucan_policy import PolicyRegistry
    return PolicyRegistry()


def _make_intent(tool="test_tool", actor="alice"):
    from ipfs_datasets_py.mcp_server.dispatch_pipeline import PipelineIntent
    return PipelineIntent(tool_name=tool, actor=actor, params={})


# ===========================================================================
# 1. FilePolicyStore — persistent policy store
# ===========================================================================

class TestFilePolicyStore:
    """Tests for FilePolicyStore persistence across restarts."""

    def test_save_creates_json_file(self, tmp_path):
        from ipfs_datasets_py.mcp_server.nl_ucan_policy import FilePolicyStore
        reg = _fresh_registry()
        reg.register("p1", "admin may call admin_tools")
        store = FilePolicyStore(str(tmp_path / "policies.json"), reg)
        store.save()
        assert (tmp_path / "policies.json").exists()

    def test_save_stores_nl_text(self, tmp_path):
        from ipfs_datasets_py.mcp_server.nl_ucan_policy import FilePolicyStore
        reg = _fresh_registry()
        reg.register("p1", "admin may call admin_tools")
        path = str(tmp_path / "policies.json")
        store = FilePolicyStore(path, reg)
        store.save()
        with open(path) as f:
            data = json.load(f)
        assert "p1" in data
        assert "admin may call admin_tools" in data["p1"]["nl_policy"]

    def test_save_stores_source_cid(self, tmp_path):
        from ipfs_datasets_py.mcp_server.nl_ucan_policy import FilePolicyStore, _make_policy_cid
        reg = _fresh_registry()
        reg.register("p1", "admin may call admin_tools")
        path = str(tmp_path / "policies.json")
        FilePolicyStore(path, reg).save()
        with open(path) as f:
            data = json.load(f)
        assert data["p1"]["source_cid"] == _make_policy_cid("admin may call admin_tools")

    def test_load_returns_zero_when_file_absent(self, tmp_path):
        from ipfs_datasets_py.mcp_server.nl_ucan_policy import FilePolicyStore
        store = FilePolicyStore(str(tmp_path / "nonexistent.json"), _fresh_registry())
        assert store.load() == 0

    def test_load_returns_zero_on_bad_json(self, tmp_path):
        from ipfs_datasets_py.mcp_server.nl_ucan_policy import FilePolicyStore
        path = str(tmp_path / "bad.json")
        with open(path, "w") as f:
            f.write("not json!!!!")
        store = FilePolicyStore(path, _fresh_registry())
        assert store.load() == 0

    def test_load_restores_policies(self, tmp_path):
        from ipfs_datasets_py.mcp_server.nl_ucan_policy import FilePolicyStore
        reg = _fresh_registry()
        reg.register("p1", "admin may call admin_tools")
        reg.register("p2", "alice must not call delete_tools")
        path = str(tmp_path / "policies.json")
        FilePolicyStore(path, reg).save()

        reg2 = _fresh_registry()
        n = FilePolicyStore(path, reg2).load()
        assert n == 2
        assert set(reg2.list_names()) == {"p1", "p2"}

    def test_load_recompiles_on_cid_mismatch(self, tmp_path):
        from ipfs_datasets_py.mcp_server.nl_ucan_policy import FilePolicyStore
        reg = _fresh_registry()
        reg.register("p1", "admin may call admin_tools")
        path = str(tmp_path / "policies.json")
        FilePolicyStore(path, reg).save()

        # Tamper the stored CID
        with open(path) as f:
            data = json.load(f)
        data["p1"]["source_cid"] = "bafy-tampered-cid"
        with open(path, "w") as f:
            json.dump(data, f)

        reg2 = _fresh_registry()
        # Should load successfully (recompiles), not raise
        n = FilePolicyStore(path, reg2).load()
        assert n == 1
        assert "p1" in reg2.list_names()

    def test_load_skips_empty_nl_policy(self, tmp_path):
        from ipfs_datasets_py.mcp_server.nl_ucan_policy import FilePolicyStore
        path = str(tmp_path / "policies.json")
        with open(path, "w") as f:
            json.dump({"bad": {"nl_policy": "", "description": "", "source_cid": ""}}, f)
        reg = _fresh_registry()
        n = FilePolicyStore(path, reg).load()
        assert n == 0

    def test_save_creates_parent_dirs(self, tmp_path):
        from ipfs_datasets_py.mcp_server.nl_ucan_policy import FilePolicyStore
        reg = _fresh_registry()
        reg.register("p1", "admin may call admin_tools")
        deep_path = str(tmp_path / "a" / "b" / "c" / "policies.json")
        FilePolicyStore(deep_path, reg).save()
        assert os.path.exists(deep_path)

    def test_roundtrip_preserves_description(self, tmp_path):
        from ipfs_datasets_py.mcp_server.nl_ucan_policy import FilePolicyStore
        reg = _fresh_registry()
        reg.register("p1", "admin may call admin_tools", description="Admin policy")
        path = str(tmp_path / "policies.json")
        FilePolicyStore(path, reg).save()
        with open(path) as f:
            data = json.load(f)
        assert data["p1"]["description"] == "Admin policy"


# ===========================================================================
# 2. AsyncPolicyRegistrar — async concurrent policy registration
# ===========================================================================

class TestAsyncPolicyRegistrar:
    """Tests for AsyncPolicyRegistrar (anyio-based concurrent registration)."""

    def test_register_many_sync_fallback(self):
        """register_many works synchronously when anyio is not needed."""
        import asyncio
        from ipfs_datasets_py.mcp_server.nl_ucan_policy import AsyncPolicyRegistrar
        reg = _fresh_registry()
        registrar = AsyncPolicyRegistrar(reg)
        result = asyncio.run(registrar.register_many({
            "p1": "admin may call admin_tools",
            "p2": "alice must not call delete_tools",
        }))
        assert set(result.keys()) == {"p1", "p2"}
        assert set(reg.list_names()) == {"p1", "p2"}

    def test_register_many_with_descriptions(self):
        import asyncio
        from ipfs_datasets_py.mcp_server.nl_ucan_policy import AsyncPolicyRegistrar
        reg = _fresh_registry()
        registrar = AsyncPolicyRegistrar(reg)
        asyncio.run(registrar.register_many(
            {"p1": "admin may call admin_tools"},
            descriptions={"p1": "Admin policy"},
        ))
        compiled = reg.get("p1")
        assert compiled is not None
        assert compiled.policy.description == "Admin policy"

    def test_register_many_returns_compiled_policies(self):
        import asyncio
        from ipfs_datasets_py.mcp_server.nl_ucan_policy import AsyncPolicyRegistrar, CompiledUCANPolicy
        reg = _fresh_registry()
        registrar = AsyncPolicyRegistrar(reg)
        result = asyncio.run(registrar.register_many({
            "p1": "admin may call admin_tools",
        }))
        assert isinstance(result["p1"], CompiledUCANPolicy)

    def test_register_many_empty_dict(self):
        import asyncio
        from ipfs_datasets_py.mcp_server.nl_ucan_policy import AsyncPolicyRegistrar
        reg = _fresh_registry()
        registrar = AsyncPolicyRegistrar(reg)
        result = asyncio.run(registrar.register_many({}))
        assert result == {}

    def test_register_many_anyio_path(self):
        """Uses anyio task group when anyio is available."""
        import anyio
        from ipfs_datasets_py.mcp_server.nl_ucan_policy import AsyncPolicyRegistrar
        reg = _fresh_registry()
        registrar = AsyncPolicyRegistrar(reg)
        async def _run():
            return await registrar.register_many({
                "p1": "admin may call admin_tools",
                "p2": "alice must not call delete_tools",
            })
        result = anyio.run(_run)
        assert len(result) == 2
        assert set(reg.list_names()) == {"p1", "p2"}


# ===========================================================================
# 3. PubSubBridge — PubSubBus ↔ P2PServiceManager bridge
# ===========================================================================

class TestPubSubBridge:
    """Tests for PubSubBridge connecting in-process bus to P2PServiceManager."""

    def _make_sm(self):
        events = []
        class FakeSM:
            def announce_capability(self, topic, payload):
                events.append((topic, payload))
        return FakeSM(), events

    def test_connect_registers_handlers_on_all_topics(self):
        from ipfs_datasets_py.mcp_server.mcp_p2p_transport import PubSubBridge, PubSubBus, PubSubEventType
        bus = PubSubBus()
        bridge = PubSubBridge(bus)
        sm, _ = self._make_sm()
        bridge.connect(sm)
        for evt in PubSubEventType:
            assert bus.topic_count(evt.value) >= 1

    def test_is_connected_after_connect(self):
        from ipfs_datasets_py.mcp_server.mcp_p2p_transport import PubSubBridge, PubSubBus
        bus = PubSubBus()
        bridge = PubSubBridge(bus)
        sm, _ = self._make_sm()
        assert not bridge.is_connected
        bridge.connect(sm)
        assert bridge.is_connected

    def test_publish_forwards_to_service_manager(self):
        from ipfs_datasets_py.mcp_server.mcp_p2p_transport import PubSubBridge, PubSubBus, PubSubEventType
        bus = PubSubBus()
        bridge = PubSubBridge(bus)
        sm, events = self._make_sm()
        bridge.connect(sm)
        topic = PubSubEventType.INTERFACE_ANNOUNCE.value
        bus.publish(topic, {"cid": "bafy-test"})
        assert any(t == topic for t, _ in events)

    def test_publish_receipt_disseminate(self):
        from ipfs_datasets_py.mcp_server.mcp_p2p_transport import PubSubBridge, PubSubBus, PubSubEventType
        bus = PubSubBus()
        bridge = PubSubBridge(bus)
        sm, events = self._make_sm()
        bridge.connect(sm)
        topic = PubSubEventType.RECEIPT_DISSEMINATE.value
        bus.publish(topic, {"receipt_cid": "bafy-r"})
        assert any(t == topic for t, _ in events)

    def test_disconnect_clears_handlers(self):
        from ipfs_datasets_py.mcp_server.mcp_p2p_transport import PubSubBridge, PubSubBus, PubSubEventType
        bus = PubSubBus()
        bridge = PubSubBridge(bus)
        sm, _ = self._make_sm()
        bridge.connect(sm)
        bridge.disconnect()
        for evt in PubSubEventType:
            assert bus.topic_count(evt.value) == 0

    def test_disconnect_sets_is_connected_false(self):
        from ipfs_datasets_py.mcp_server.mcp_p2p_transport import PubSubBridge, PubSubBus
        bus = PubSubBus()
        bridge = PubSubBridge(bus)
        sm, _ = self._make_sm()
        bridge.connect(sm)
        bridge.disconnect()
        assert not bridge.is_connected

    def test_double_connect_is_ignored(self):
        from ipfs_datasets_py.mcp_server.mcp_p2p_transport import PubSubBridge, PubSubBus, PubSubEventType
        bus = PubSubBus()
        bridge = PubSubBridge(bus)
        sm, _ = self._make_sm()
        bridge.connect(sm)
        count_before = bus.topic_count(PubSubEventType.INTERFACE_ANNOUNCE.value)
        bridge.connect(sm)  # second call should be no-op
        assert bus.topic_count(PubSubEventType.INTERFACE_ANNOUNCE.value) == count_before

    def test_disconnect_when_not_connected_is_noop(self):
        from ipfs_datasets_py.mcp_server.mcp_p2p_transport import PubSubBridge, PubSubBus
        bus = PubSubBus()
        bridge = PubSubBridge(bus)
        bridge.disconnect()  # should not raise
        assert not bridge.is_connected

    def test_get_global_bus_returns_pubsub_bus(self):
        from ipfs_datasets_py.mcp_server.mcp_p2p_transport import get_global_bus, PubSubBus
        bus = get_global_bus()
        assert isinstance(bus, PubSubBus)

    def test_get_global_bus_is_singleton(self):
        from ipfs_datasets_py.mcp_server.mcp_p2p_transport import get_global_bus
        assert get_global_bus() is get_global_bus()

    def test_service_manager_without_announce_capability(self):
        """Bridge works even if the SM lacks announce_capability (logs instead)."""
        from ipfs_datasets_py.mcp_server.mcp_p2p_transport import PubSubBridge, PubSubBus, PubSubEventType
        bus = PubSubBus()
        bridge = PubSubBridge(bus)
        class NoAnnounceSM:
            pass
        bridge.connect(NoAnnounceSM())
        # Publishing should not raise
        bus.publish(PubSubEventType.DECISION_DISSEMINATE.value, {"x": 1})
        assert bridge.is_connected


# ===========================================================================
# 4. PipelineMetricsRecorder — pipeline stage denials → monitoring
# ===========================================================================

class TestPipelineMetricsRecorder:
    """Tests for PipelineMetricsRecorder feeding denials into monitoring."""

    def test_allow_increments_allow_counts(self):
        from ipfs_datasets_py.mcp_server.dispatch_pipeline import PipelineMetricsRecorder, make_default_pipeline
        pipeline = make_default_pipeline()
        recorder = PipelineMetricsRecorder(pipeline)
        intent = _make_intent("some_tool", "alice")
        recorder.check_and_record(intent)
        stats = recorder.get_stats()
        assert stats["total_allows"] == 1
        assert stats["total_denials"] == 0
        assert stats["allow_counts"]["some_tool"] == 1

    def test_deny_increments_denial_counts(self):
        from ipfs_datasets_py.mcp_server.dispatch_pipeline import (
            PipelineMetricsRecorder, DispatchPipeline,
            PipelineResult, PipelineStage, PipelineIntent,
        )
        from ipfs_datasets_py.mcp_server.cid_artifacts import DecisionObject
        pipeline = DispatchPipeline()

        # Patch check() to return a deny
        def _deny_check(intent):
            decision = DecisionObject(decision="deny", intent_cid="x", policy_cid="p",
                                      proofs_checked=[], justification="test")
            return PipelineResult(allowed=False, stage_outcomes=[], blocking_stage=PipelineStage.COMPLIANCE,
                                  intent=intent, decision=decision)
        pipeline.check = _deny_check  # type: ignore[method-assign]

        recorder = PipelineMetricsRecorder(pipeline)
        recorder.check_and_record(_make_intent("blocked_tool", "alice"))
        stats = recorder.get_stats()
        assert stats["total_denials"] == 1
        assert stats["denial_counts"]["blocked_tool"] == 1

    def test_record_calls_collector_track_tool_execution(self):
        from ipfs_datasets_py.mcp_server.dispatch_pipeline import PipelineMetricsRecorder, make_default_pipeline
        collector = MagicMock()
        pipeline = make_default_pipeline()
        recorder = PipelineMetricsRecorder(pipeline, collector=collector)
        intent = _make_intent()
        recorder.check_and_record(intent)
        collector.track_tool_execution.assert_called_once()
        call_kwargs = collector.track_tool_execution.call_args
        assert "pipeline:test_tool" in str(call_kwargs)
        # success=True is passed as a keyword argument
        assert call_kwargs.kwargs.get("success") is True

    def test_record_reports_failure_for_deny(self):
        from ipfs_datasets_py.mcp_server.dispatch_pipeline import (
            PipelineMetricsRecorder, DispatchPipeline, PipelineResult, PipelineStage,
        )
        from ipfs_datasets_py.mcp_server.cid_artifacts import DecisionObject
        collector = MagicMock()
        pipeline = DispatchPipeline()

        def _deny(intent):
            d = DecisionObject(decision="deny", intent_cid="x", policy_cid="p",
                               proofs_checked=[], justification="test")
            return PipelineResult(allowed=False, stage_outcomes=[], blocking_stage=PipelineStage.COMPLIANCE,
                                  intent=intent, decision=d)
        pipeline.check = _deny  # type: ignore[method-assign]

        recorder = PipelineMetricsRecorder(pipeline, collector=collector)
        recorder.check_and_record(_make_intent())
        call_kwargs = collector.track_tool_execution.call_args
        success_val = call_kwargs.kwargs.get("success")
        assert success_val is False

    def test_get_stats_returns_both_counts(self):
        from ipfs_datasets_py.mcp_server.dispatch_pipeline import PipelineMetricsRecorder, make_default_pipeline
        pipeline = make_default_pipeline()
        recorder = PipelineMetricsRecorder(pipeline)
        recorder.check_and_record(_make_intent("tool_a"))
        recorder.check_and_record(_make_intent("tool_a"))
        recorder.check_and_record(_make_intent("tool_b"))
        stats = recorder.get_stats()
        assert stats["allow_counts"]["tool_a"] == 2
        assert stats["allow_counts"]["tool_b"] == 1
        assert stats["total_allows"] == 3

    def test_reset_clears_counts(self):
        from ipfs_datasets_py.mcp_server.dispatch_pipeline import PipelineMetricsRecorder, make_default_pipeline
        pipeline = make_default_pipeline()
        recorder = PipelineMetricsRecorder(pipeline)
        recorder.check_and_record(_make_intent())
        recorder.reset()
        stats = recorder.get_stats()
        assert stats["total_allows"] == 0
        assert stats["total_denials"] == 0

    def test_collector_exception_does_not_raise(self):
        from ipfs_datasets_py.mcp_server.dispatch_pipeline import PipelineMetricsRecorder, make_default_pipeline
        collector = MagicMock()
        collector.track_tool_execution.side_effect = RuntimeError("boom")
        pipeline = make_default_pipeline()
        recorder = PipelineMetricsRecorder(pipeline, collector=collector)
        # Should not raise
        recorder.check_and_record(_make_intent())

    def test_no_collector_no_error(self):
        from ipfs_datasets_py.mcp_server.dispatch_pipeline import PipelineMetricsRecorder, make_default_pipeline
        pipeline = make_default_pipeline()
        # collector=None, monitoring module patched to fail import
        recorder = PipelineMetricsRecorder(pipeline, collector=None)
        with patch("ipfs_datasets_py.mcp_server.dispatch_pipeline.PipelineMetricsRecorder._get_collector",
                   return_value=None):
            recorder.check_and_record(_make_intent())
        assert recorder.get_stats()["total_allows"] == 1


# ===========================================================================
# 5. DID key manager integration — DIDSignedDelegation, sign_delegation,
#    verify_delegation_signature
# ===========================================================================

class TestDIDDelegationIntegration:
    """Tests for DIDSignedDelegation + sign/verify helpers."""

    def _make_delegation(self):
        from ipfs_datasets_py.mcp_server.ucan_delegation import Capability, Delegation
        cap = Capability(resource="mcp:tool", ability="invoke")
        return Delegation(
            cid="did-test-cid",
            issuer="did:key:z6MkAlice",
            audience="did:key:z6MkBob",
            capabilities=[cap],
        )

    def test_sign_delegation_returns_did_signed_delegation(self):
        from ipfs_datasets_py.mcp_server.ucan_delegation import sign_delegation, DIDSignedDelegation
        d = self._make_delegation()
        signed = sign_delegation(d)
        assert isinstance(signed, DIDSignedDelegation)

    def test_sign_without_key_manager_returns_unsigned_sentinel(self):
        from ipfs_datasets_py.mcp_server.ucan_delegation import sign_delegation
        d = self._make_delegation()
        signed = sign_delegation(d)  # no manager in this env
        assert signed.signer_did == "did:key:unsigned"
        assert signed.signature == ""

    def test_sign_with_mock_key_manager(self):
        from ipfs_datasets_py.mcp_server.ucan_delegation import sign_delegation
        mgr = MagicMock()
        mgr.sign.return_value = b"\xde\xad\xbe\xef"
        mgr.did = "did:key:z6MkTest"
        d = self._make_delegation()
        signed = sign_delegation(d, key_manager=mgr)
        assert signed.signer_did == "did:key:z6MkTest"
        assert signed.signature == "deadbeef"

    def test_verify_with_mock_key_manager_success(self):
        from ipfs_datasets_py.mcp_server.ucan_delegation import (
            sign_delegation, verify_delegation_signature, DIDSignedDelegation,
        )
        mgr = MagicMock()
        mgr.sign.return_value = b"\xde\xad\xbe\xef"
        mgr.did = "did:key:z6MkTest"
        mgr.verify.return_value = True
        d = self._make_delegation()
        signed = sign_delegation(d, key_manager=mgr)
        ok = verify_delegation_signature(signed, key_manager=mgr)
        assert ok is True

    def test_verify_with_mock_key_manager_failure(self):
        from ipfs_datasets_py.mcp_server.ucan_delegation import (
            sign_delegation, verify_delegation_signature,
        )
        mgr = MagicMock()
        mgr.sign.return_value = b"\xde\xad\xbe\xef"
        mgr.did = "did:key:z6MkTest"
        mgr.verify.return_value = False
        d = self._make_delegation()
        signed = sign_delegation(d, key_manager=mgr)
        ok = verify_delegation_signature(signed, key_manager=mgr)
        assert ok is False

    def test_verify_empty_signature_returns_false(self):
        from ipfs_datasets_py.mcp_server.ucan_delegation import verify_delegation_signature, DIDSignedDelegation, Delegation, Capability
        cap = Capability(resource="r", ability="a")
        d = Delegation(cid="c", issuer="i", audience="a", capabilities=[cap])
        signed = DIDSignedDelegation(delegation=d, signature="", signer_did="did:key:x")
        assert verify_delegation_signature(signed) is False

    def test_verify_without_manager_returns_false(self):
        from ipfs_datasets_py.mcp_server.ucan_delegation import sign_delegation, verify_delegation_signature
        d = self._make_delegation()
        signed = sign_delegation(d)  # unsigned sentinel
        ok = verify_delegation_signature(signed)
        assert ok is False

    def test_did_signed_delegation_to_dict(self):
        from ipfs_datasets_py.mcp_server.ucan_delegation import DIDSignedDelegation
        mgr = MagicMock()
        mgr.sign.return_value = b"\xab\xcd"
        mgr.did = "did:key:z6MkTest"
        from ipfs_datasets_py.mcp_server.ucan_delegation import sign_delegation
        d = self._make_delegation()
        signed = sign_delegation(d, key_manager=mgr)
        dct = signed.to_dict()
        assert "signature" in dct
        assert dct["signer_did"] == "did:key:z6MkTest"
        assert "cid" in dct

    def test_sign_manager_exception_falls_back_to_unsigned(self):
        from ipfs_datasets_py.mcp_server.ucan_delegation import sign_delegation
        mgr = MagicMock()
        mgr.sign.side_effect = RuntimeError("key unavailable")
        mgr.did = "did:key:z6MkTest"
        d = self._make_delegation()
        signed = sign_delegation(d, key_manager=mgr)
        assert signed.signer_did == "did:key:unsigned"
        assert signed.signature == ""

    def test_verify_manager_exception_returns_false(self):
        from ipfs_datasets_py.mcp_server.ucan_delegation import (
            sign_delegation, verify_delegation_signature,
        )
        sign_mgr = MagicMock()
        sign_mgr.sign.return_value = b"\x01\x02"
        sign_mgr.did = "did:key:z"
        d = self._make_delegation()
        signed = sign_delegation(d, key_manager=sign_mgr)

        verify_mgr = MagicMock()
        verify_mgr.verify.side_effect = RuntimeError("crash")
        ok = verify_delegation_signature(signed, key_manager=verify_mgr)
        assert ok is False

    def test_verified_field_default_false(self):
        from ipfs_datasets_py.mcp_server.ucan_delegation import sign_delegation
        d = self._make_delegation()
        signed = sign_delegation(d)
        assert signed.verified is False


# ===========================================================================
# 6. Integration — FilePolicyStore + AsyncPolicyRegistrar round-trip
# ===========================================================================

class TestIntegration:
    """Cross-component integration tests."""

    def test_file_store_and_async_registrar_share_registry(self, tmp_path):
        import asyncio
        from ipfs_datasets_py.mcp_server.nl_ucan_policy import (
            AsyncPolicyRegistrar, FilePolicyStore, PolicyRegistry,
        )
        reg = PolicyRegistry()  # isolated, not the global singleton
        path = str(tmp_path / "shared.json")
        registrar = AsyncPolicyRegistrar(reg)
        asyncio.run(registrar.register_many({
            "pol_a": "admin may call admin_tools",
            "pol_b": "alice must not call delete_tools",
        }))
        FilePolicyStore(path, reg).save()

        reg2 = PolicyRegistry()  # fresh isolated registry
        n = FilePolicyStore(path, reg2).load()
        assert n == 2
        assert set(reg2.list_names()) == {"pol_a", "pol_b"}

    def test_pipeline_recorder_with_bridge_connected(self):
        """PipelineMetricsRecorder + PubSubBridge can run together."""
        from ipfs_datasets_py.mcp_server.dispatch_pipeline import PipelineMetricsRecorder, make_default_pipeline
        from ipfs_datasets_py.mcp_server.mcp_p2p_transport import PubSubBridge, PubSubBus, PubSubEventType
        pipeline = make_default_pipeline()
        recorder = PipelineMetricsRecorder(pipeline, collector=MagicMock())
        bus = PubSubBus()
        bridge = PubSubBridge(bus)
        events = []
        class SM:
            def announce_capability(self, t, p): events.append(p)
        bridge.connect(SM())

        intent = _make_intent()
        recorder.check_and_record(intent)
        bus.publish(PubSubEventType.RECEIPT_DISSEMINATE.value, {"tool": intent.tool_name})

        assert recorder.get_stats()["total_allows"] == 1
        assert len(events) == 1
        bridge.disconnect()
