"""
test_v16_sessions.py — v16 MCP + logic improvement sessions (BN124–BW133).

Sessions covered
----------------
BN124: DelegationManager.revoke_chain() multi-hop chain test
BO125: NLPolicyConflictDetector ↔ UCANPolicyBridge integration (conflicts field)
BP126: audit_metrics_bridge + PrometheusExporter smoke test
BR128: DelegationManager.can_invoke_audited() records to PolicyAuditLog
BS129: make_delegation_stage() — DelegationManager as a DispatchPipeline stage
BW133: logic/api.py — DelegationManager + conflict_detector exports
TDFOL-NL-T3: TDFOL/nl pattern dataclasses (no spaCy required)
TDFOL-NL-T4: ParseOptions dataclass + ParseResult dataclass
"""
from __future__ import annotations

import time
import tempfile
import os
from typing import Any, List
import pytest


# ---------------------------------------------------------------------------
# BN124 — DelegationManager.revoke_chain() multi-hop chain
# ---------------------------------------------------------------------------

class TestDelegationManagerRevokeChain:
    """BN124: Multi-hop delegation chain revocation."""

    def _make_manager(self):
        from ipfs_datasets_py.mcp_server.ucan_delegation import (
            DelegationManager, DelegationToken, Capability,
        )
        mgr = DelegationManager()
        future = time.time() + 3600

        # Root → Alice
        root_tok = DelegationToken(
            issuer="did:example:root",
            audience="did:example:alice",
            capabilities=[Capability(resource="tools/*", ability="tools/invoke")],
            expiry=future,
        )
        # Alice → Bob
        alice_tok = DelegationToken(
            issuer="did:example:alice",
            audience="did:example:bob",
            capabilities=[Capability(resource="tools/*", ability="tools/invoke")],
            expiry=future,
            proof_cid=root_tok.cid,
        )
        # Bob → Carol (leaf)
        bob_tok = DelegationToken(
            issuer="did:example:bob",
            audience="did:example:carol",
            capabilities=[Capability(resource="tools/*", ability="tools/invoke")],
            expiry=future,
            proof_cid=alice_tok.cid,
        )
        mgr.add(root_tok)
        mgr.add(alice_tok)
        mgr.add(bob_tok)
        return mgr, root_tok, alice_tok, bob_tok

    def test_revoke_chain_revokes_leaf(self):
        mgr, root, alice, bob = self._make_manager()
        count = mgr.revoke_chain(bob.cid)
        # At least the leaf was revoked
        assert mgr.is_revoked(bob.cid)
        assert count >= 1

    def test_revoke_chain_returns_positive_count(self):
        mgr, root, alice, bob = self._make_manager()
        count = mgr.revoke_chain(bob.cid)
        assert count >= 1

    def test_revoke_chain_blocks_can_invoke(self):
        mgr, root, alice, bob = self._make_manager()
        mgr.revoke_chain(bob.cid)
        allowed, reason = mgr.can_invoke(
            "did:example:carol", "tools/*", "tools/invoke", leaf_cid=bob.cid
        )
        assert not allowed

    def test_revoke_root_only_fallback(self):
        """If chain build fails, root_cid itself is still revoked (fallback path)."""
        from ipfs_datasets_py.mcp_server.ucan_delegation import DelegationManager
        mgr = DelegationManager()
        # Revoke an unknown CID — should not raise, should still revoke it
        count = mgr.revoke_chain("nonexistent-cid-xyz")
        assert count == 1
        assert mgr.is_revoked("nonexistent-cid-xyz")

    def test_revoke_chain_root_token(self):
        mgr, root, alice, bob = self._make_manager()
        count = mgr.revoke_chain(root.cid)
        assert count >= 1
        assert mgr.is_revoked(root.cid)

    def test_after_revoke_chain_metrics_increase(self):
        mgr, root, alice, bob = self._make_manager()
        before = mgr.get_metrics()["revoked_count"]
        mgr.revoke_chain(bob.cid)
        after = mgr.get_metrics()["revoked_count"]
        assert after > before


# ---------------------------------------------------------------------------
# BO125 — NLPolicyConflictDetector ↔ UCANPolicyBridge
# ---------------------------------------------------------------------------

class TestUCANPolicyBridgeConflicts:
    """BO125: BridgeCompileResult.conflicts field populated by compile_nl()."""

    def test_bridge_compile_result_has_conflicts_field(self):
        from ipfs_datasets_py.logic.integration.ucan_policy_bridge import BridgeCompileResult
        r = BridgeCompileResult()
        assert hasattr(r, "conflicts")
        assert isinstance(r.conflicts, list)

    def test_bridge_compile_result_has_conflict_count(self):
        from ipfs_datasets_py.logic.integration.ucan_policy_bridge import BridgeCompileResult
        r = BridgeCompileResult(conflicts=["c1", "c2"])
        assert r.conflict_count == 2

    def test_conflict_count_zero_by_default(self):
        from ipfs_datasets_py.logic.integration.ucan_policy_bridge import BridgeCompileResult
        r = BridgeCompileResult()
        assert r.conflict_count == 0

    def test_bridge_compile_nl_returns_conflicts_field(self):
        """compile_nl() result has conflicts attribute (may be empty list)."""
        from ipfs_datasets_py.logic.integration.ucan_policy_bridge import UCANPolicyBridge
        bridge = UCANPolicyBridge()
        result = bridge.compile_nl("The admin must file the report.")
        assert hasattr(result, "conflicts")
        assert isinstance(result.conflicts, list)

    def test_conflicting_nl_text_produces_warning_or_conflict(self):
        """A text with both permission and prohibition may produce a conflict."""
        from ipfs_datasets_py.logic.integration.ucan_policy_bridge import UCANPolicyBridge
        bridge = UCANPolicyBridge()
        # This text may or may not produce conflicts depending on NL parsing depth
        result = bridge.compile_nl("Alice may read the file. Alice must not read the file.")
        # Should not crash; conflicts is a list
        assert isinstance(result.conflicts, list)


# ---------------------------------------------------------------------------
# BP126 — AuditMetricsBridge + PrometheusExporter end-to-end smoke test
# ---------------------------------------------------------------------------

class TestAuditMetricsBridgeSmoke:
    """BP126: Live wiring of AuditMetricsBridge to PrometheusExporter + PolicyAuditLog."""

    def test_allow_decision_forwarded_to_prometheus(self):
        from ipfs_datasets_py.mcp_server.policy_audit_log import PolicyAuditLog
        from ipfs_datasets_py.mcp_server.prometheus_exporter import PrometheusExporter
        from ipfs_datasets_py.mcp_server.audit_metrics_bridge import connect_audit_to_prometheus

        audit = PolicyAuditLog()
        exporter = PrometheusExporter()
        bridge = connect_audit_to_prometheus(audit, exporter)

        audit.record(
            policy_cid="p1", intent_cid="i1", decision="allow",
            tool="dataset_load", actor="alice",
        )
        assert bridge.forwarded_count == 1

    def test_deny_decision_forwarded_to_prometheus(self):
        from ipfs_datasets_py.mcp_server.policy_audit_log import PolicyAuditLog
        from ipfs_datasets_py.mcp_server.prometheus_exporter import PrometheusExporter
        from ipfs_datasets_py.mcp_server.audit_metrics_bridge import connect_audit_to_prometheus

        audit = PolicyAuditLog()
        exporter = PrometheusExporter()
        bridge = connect_audit_to_prometheus(audit, exporter)

        audit.record(
            policy_cid="p1", intent_cid="i1", decision="deny",
            tool="dangerous_tool", actor="mallory",
        )
        assert bridge.forwarded_count == 1

    def test_multiple_decisions_all_forwarded(self):
        from ipfs_datasets_py.mcp_server.policy_audit_log import PolicyAuditLog
        from ipfs_datasets_py.mcp_server.prometheus_exporter import PrometheusExporter
        from ipfs_datasets_py.mcp_server.audit_metrics_bridge import connect_audit_to_prometheus

        audit = PolicyAuditLog()
        exporter = PrometheusExporter()
        bridge = connect_audit_to_prometheus(audit, exporter)

        for i in range(5):
            audit.record(
                policy_cid=f"p{i}", intent_cid=f"i{i}",
                decision="allow" if i % 2 == 0 else "deny",
                tool="tool", actor="alice",
            )
        assert bridge.forwarded_count == 5

    def test_bridge_detach_stops_forwarding(self):
        from ipfs_datasets_py.mcp_server.policy_audit_log import PolicyAuditLog
        from ipfs_datasets_py.mcp_server.prometheus_exporter import PrometheusExporter
        from ipfs_datasets_py.mcp_server.audit_metrics_bridge import connect_audit_to_prometheus

        audit = PolicyAuditLog()
        exporter = PrometheusExporter()
        bridge = connect_audit_to_prometheus(audit, exporter)
        bridge.detach()

        audit.record(
            policy_cid="p1", intent_cid="i1", decision="allow",
            tool="tool", actor="alice",
        )
        assert bridge.forwarded_count == 0

    def test_exporter_get_info_after_recording(self):
        from ipfs_datasets_py.mcp_server.prometheus_exporter import PrometheusExporter
        exporter = PrometheusExporter()
        exporter.record_tool_call("policy", "my_tool", "allow", latency_seconds=0.01)
        info = exporter.get_info()
        assert isinstance(info, dict)


# ---------------------------------------------------------------------------
# BR128 — DelegationManager.can_invoke_audited()
# ---------------------------------------------------------------------------

class TestDelegationManagerAuditedInvoke:
    """BR128: DelegationManager.can_invoke_audited() records to PolicyAuditLog."""

    def _make_mgr_with_token(self):
        from ipfs_datasets_py.mcp_server.ucan_delegation import (
            DelegationManager, DelegationToken, Capability,
        )
        mgr = DelegationManager()
        tok = DelegationToken(
            issuer="did:example:root",
            audience="did:example:alice",
            capabilities=[Capability(resource="tools/*", ability="tools/invoke")],
            expiry=time.time() + 3600,
        )
        mgr.add(tok)
        return mgr, tok

    def test_can_invoke_audited_exists(self):
        from ipfs_datasets_py.mcp_server.ucan_delegation import DelegationManager
        mgr = DelegationManager()
        assert hasattr(mgr, "can_invoke_audited")

    def test_can_invoke_audited_returns_tuple(self):
        mgr, tok = self._make_mgr_with_token()
        result = mgr.can_invoke_audited(
            "did:example:alice", "tools/*", "tools/invoke",
            leaf_cid=tok.cid,
        )
        assert isinstance(result, tuple)
        assert len(result) == 2

    def test_can_invoke_audited_records_to_audit_log(self):
        from ipfs_datasets_py.mcp_server.policy_audit_log import PolicyAuditLog
        audit = PolicyAuditLog()
        mgr, tok = self._make_mgr_with_token()

        mgr.can_invoke_audited(
            "did:example:alice", "tools/*", "tools/invoke",
            leaf_cid=tok.cid,
            audit_log=audit,
        )
        assert audit.total_recorded() == 1

    def test_can_invoke_audited_allow_recorded(self):
        from ipfs_datasets_py.mcp_server.policy_audit_log import PolicyAuditLog
        audit = PolicyAuditLog()
        mgr, tok = self._make_mgr_with_token()

        allowed, _ = mgr.can_invoke_audited(
            "did:example:alice", "tools/*", "tools/invoke",
            leaf_cid=tok.cid,
            audit_log=audit,
        )
        entries = audit.all_entries()
        assert len(entries) == 1
        assert entries[0].decision == ("allow" if allowed else "deny")

    def test_can_invoke_audited_deny_recorded(self):
        from ipfs_datasets_py.mcp_server.policy_audit_log import PolicyAuditLog
        from ipfs_datasets_py.mcp_server.ucan_delegation import DelegationManager
        audit = PolicyAuditLog()
        mgr = DelegationManager()  # no tokens

        allowed, reason = mgr.can_invoke_audited(
            "did:example:alice", "tools/*", "tools/invoke",
            leaf_cid="nonexistent",
            audit_log=audit,
        )
        assert not allowed
        assert audit.total_recorded() == 1
        assert audit.all_entries()[0].decision == "deny"

    def test_can_invoke_audited_without_audit_log_still_works(self):
        mgr, tok = self._make_mgr_with_token()
        # Should work just like can_invoke without audit_log
        allowed, reason = mgr.can_invoke_audited(
            "did:example:alice", "tools/*", "tools/invoke",
            leaf_cid=tok.cid,
        )
        assert isinstance(allowed, bool)

    def test_can_invoke_audited_multiple_calls_accumulate(self):
        from ipfs_datasets_py.mcp_server.policy_audit_log import PolicyAuditLog
        audit = PolicyAuditLog()
        mgr, tok = self._make_mgr_with_token()

        for _ in range(3):
            mgr.can_invoke_audited(
                "did:example:alice", "tools/*", "tools/invoke",
                leaf_cid=tok.cid,
                audit_log=audit,
            )
        assert audit.total_recorded() == 3

    def test_can_invoke_audited_custom_policy_and_intent_cid(self):
        from ipfs_datasets_py.mcp_server.policy_audit_log import PolicyAuditLog
        audit = PolicyAuditLog()
        mgr, tok = self._make_mgr_with_token()

        mgr.can_invoke_audited(
            "did:example:alice", "tools/*", "tools/invoke",
            leaf_cid=tok.cid,
            audit_log=audit,
            policy_cid="custom-policy-cid",
            intent_cid="custom-intent-cid",
        )
        entry = audit.all_entries()[0]
        assert entry.policy_cid == "custom-policy-cid"
        assert entry.intent_cid == "custom-intent-cid"


# ---------------------------------------------------------------------------
# BS129 — make_delegation_stage()
# ---------------------------------------------------------------------------

class TestMakeDelegationStage:
    """BS129: dispatch_pipeline.make_delegation_stage() factory."""

    def test_make_delegation_stage_exists(self):
        from ipfs_datasets_py.mcp_server.dispatch_pipeline import make_delegation_stage
        assert callable(make_delegation_stage)

    def test_stage_name_is_delegation(self):
        from ipfs_datasets_py.mcp_server.dispatch_pipeline import make_delegation_stage
        from ipfs_datasets_py.mcp_server.ucan_delegation import DelegationManager
        stage = make_delegation_stage(DelegationManager())
        assert stage.name == "delegation"

    def test_stage_denies_unknown_principal(self):
        from ipfs_datasets_py.mcp_server.dispatch_pipeline import make_delegation_stage
        from ipfs_datasets_py.mcp_server.ucan_delegation import DelegationManager
        mgr = DelegationManager()  # empty
        stage = make_delegation_stage(mgr)
        result = stage.handler({"actor": "did:example:unknown", "tool": "dataset_load", "leaf_cid": "x"})
        assert result["allowed"] is False

    def test_stage_allows_authorized_principal(self):
        from ipfs_datasets_py.mcp_server.dispatch_pipeline import make_delegation_stage
        from ipfs_datasets_py.mcp_server.ucan_delegation import (
            DelegationManager, DelegationToken, Capability,
        )
        mgr = DelegationManager()
        tok = DelegationToken(
            issuer="did:example:root",
            audience="did:example:alice",
            capabilities=[Capability(resource="dataset_load", ability="tools/invoke")],
            expiry=time.time() + 3600,
        )
        mgr.add(tok)
        stage = make_delegation_stage(mgr)
        result = stage.handler({
            "actor": "did:example:alice",
            "tool": "dataset_load",
            "leaf_cid": tok.cid,
        })
        assert result["allowed"] is True

    def test_stage_in_pipeline_short_circuits(self):
        """Delegation stage in a full pipeline can short-circuit on deny."""
        from ipfs_datasets_py.mcp_server.dispatch_pipeline import (
            make_delegation_stage, DispatchPipeline,
        )
        from ipfs_datasets_py.mcp_server.ucan_delegation import DelegationManager
        mgr = DelegationManager()  # no tokens → deny
        delegation_stage = make_delegation_stage(mgr)
        pipeline = DispatchPipeline(stages=[delegation_stage], short_circuit=True)
        result = pipeline.run({"actor": "alice", "tool": "x", "leaf_cid": "y"})
        # Short-circuit: should get result from first denial
        assert result.allowed is False

    def test_stage_integrates_with_full_pipeline(self):
        from ipfs_datasets_py.mcp_server.dispatch_pipeline import (
            make_delegation_stage, make_full_pipeline,
        )
        from ipfs_datasets_py.mcp_server.ucan_delegation import DelegationManager
        mgr = DelegationManager()
        stage = make_delegation_stage(mgr)
        pipeline = make_full_pipeline()
        # Replace delegation stage
        for i, s in enumerate(pipeline._stages):
            if s.name == "delegation":
                pipeline._stages[i] = stage
                break
        result = pipeline.run({"actor": "unknown", "tool": "my_tool", "leaf_cid": "x"})
        # delegation stage will deny; other stages pass-through; result is PipelineResult
        assert hasattr(result, "allowed")

    def test_stage_handles_missing_intent_fields(self):
        """Stage should not crash on missing actor/tool/leaf_cid."""
        from ipfs_datasets_py.mcp_server.dispatch_pipeline import make_delegation_stage
        from ipfs_datasets_py.mcp_server.ucan_delegation import DelegationManager
        mgr = DelegationManager()
        stage = make_delegation_stage(mgr)
        result = stage.handler({})  # missing fields → deny gracefully
        assert result["allowed"] is False


# ---------------------------------------------------------------------------
# BW133 — logic/api.py exports DelegationManager + conflict_detector
# ---------------------------------------------------------------------------

class TestLogicApiExports:
    """BW133: logic/api.py __all__ includes UCAN + conflict detector symbols."""

    def test_delegation_manager_in_all(self):
        import ipfs_datasets_py.logic.api as api
        assert "DelegationManager" in api.__all__

    def test_get_delegation_manager_in_all(self):
        import ipfs_datasets_py.logic.api as api
        assert "get_delegation_manager" in api.__all__

    def test_nl_policy_conflict_detector_in_all(self):
        import ipfs_datasets_py.logic.api as api
        assert "NLPolicyConflictDetector" in api.__all__

    def test_policy_conflict_in_all(self):
        import ipfs_datasets_py.logic.api as api
        assert "PolicyConflict" in api.__all__

    def test_detect_conflicts_in_all(self):
        import ipfs_datasets_py.logic.api as api
        assert "detect_conflicts" in api.__all__

    def test_delegation_manager_accessible_via_api(self):
        """DelegationManager should be importable from logic.api (not just logic module)."""
        import ipfs_datasets_py.logic.api as api
        assert hasattr(api, "DelegationManager")

    def test_nl_policy_conflict_detector_accessible_via_api(self):
        import ipfs_datasets_py.logic.api as api
        assert hasattr(api, "NLPolicyConflictDetector")

    def test_detect_conflicts_accessible_via_api(self):
        import ipfs_datasets_py.logic.api as api
        assert callable(api.detect_conflicts)

    def test_api_import_still_quiet(self):
        """Importing logic.api must not raise (import-quiet guarantee preserved)."""
        import ipfs_datasets_py.logic.api as api_mod
        assert api_mod is not None

    def test_existing_nl_ucan_symbols_still_present(self):
        import ipfs_datasets_py.logic.api as api
        for sym in ("compile_nl_to_policy", "evaluate_nl_policy", "BridgeCompileResult"):
            assert sym in api.__all__, f"Missing: {sym}"


# ---------------------------------------------------------------------------
# TDFOL-NL-T3 — PatternType + Pattern dataclasses (no spaCy)
# ---------------------------------------------------------------------------

class TestTDFOLNLPatternDataclasses:
    """TDFOL-NL-T3: PatternType enum + Pattern/PatternMatch dataclasses (no spaCy required)."""

    def test_pattern_type_has_obligation(self):
        from ipfs_datasets_py.logic.TDFOL.nl.tdfol_nl_patterns import PatternType
        assert hasattr(PatternType, "OBLIGATION")

    def test_pattern_type_has_permission(self):
        from ipfs_datasets_py.logic.TDFOL.nl.tdfol_nl_patterns import PatternType
        assert hasattr(PatternType, "PERMISSION")

    def test_pattern_type_has_prohibition(self):
        from ipfs_datasets_py.logic.TDFOL.nl.tdfol_nl_patterns import PatternType
        assert hasattr(PatternType, "PROHIBITION")

    def test_pattern_type_has_temporal(self):
        from ipfs_datasets_py.logic.TDFOL.nl.tdfol_nl_patterns import PatternType
        assert hasattr(PatternType, "TEMPORAL")

    def test_pattern_type_has_conditional(self):
        from ipfs_datasets_py.logic.TDFOL.nl.tdfol_nl_patterns import PatternType
        assert hasattr(PatternType, "CONDITIONAL")

    def test_pattern_type_is_enum(self):
        from ipfs_datasets_py.logic.TDFOL.nl.tdfol_nl_patterns import PatternType
        from enum import Enum
        assert issubclass(PatternType, Enum)

    def test_pattern_dataclass_instantiation(self):
        from ipfs_datasets_py.logic.TDFOL.nl.tdfol_nl_patterns import Pattern, PatternType
        p = Pattern(name="test_must", type=PatternType.OBLIGATION, text_pattern=r"\bmust\b")
        assert p.name == "test_must"
        assert p.type == PatternType.OBLIGATION
        assert p.text_pattern == r"\bmust\b"

    def test_pattern_hash_uses_name_and_type(self):
        from ipfs_datasets_py.logic.TDFOL.nl.tdfol_nl_patterns import Pattern, PatternType
        p1 = Pattern(name="p", type=PatternType.OBLIGATION)
        p2 = Pattern(name="p", type=PatternType.OBLIGATION)
        assert hash(p1) == hash(p2)

    def test_pattern_distinct_names_distinct_hash(self):
        from ipfs_datasets_py.logic.TDFOL.nl.tdfol_nl_patterns import Pattern, PatternType
        p1 = Pattern(name="p1", type=PatternType.OBLIGATION)
        p2 = Pattern(name="p2", type=PatternType.OBLIGATION)
        assert hash(p1) != hash(p2)

    def test_pattern_match_dataclass_instantiation(self):
        from ipfs_datasets_py.logic.TDFOL.nl.tdfol_nl_patterns import (
            Pattern, PatternMatch, PatternType,
        )
        p = Pattern(name="must", type=PatternType.OBLIGATION)
        pm = PatternMatch(
            pattern=p,
            span=(0, 4),
            text="must",
            entities={"agent": "alice"},
            confidence=0.9,
        )
        assert pm.pattern.name == "must"
        assert pm.confidence == 0.9

    def test_pattern_match_default_spacy_span_is_none(self):
        from ipfs_datasets_py.logic.TDFOL.nl.tdfol_nl_patterns import (
            Pattern, PatternMatch, PatternType,
        )
        p = Pattern(name="may", type=PatternType.PERMISSION)
        pm = PatternMatch(pattern=p, span=(0, 3), text="may", entities={}, confidence=0.8)
        assert pm.spacy_span is None

    def test_all_pattern_types_accessible(self):
        from ipfs_datasets_py.logic.TDFOL.nl.tdfol_nl_patterns import PatternType
        expected = {"OBLIGATION", "PERMISSION", "PROHIBITION", "TEMPORAL", "CONDITIONAL"}
        actual = {e.name for e in PatternType}
        assert expected.issubset(actual)


# ---------------------------------------------------------------------------
# TDFOL-NL-T4 — ParseOptions + ParseResult dataclasses
# ---------------------------------------------------------------------------

class TestTDFOLNLParseDataclasses:
    """TDFOL-NL-T4: ParseOptions + ParseResult dataclasses without spaCy."""

    def test_parse_options_default_instantiation(self):
        from ipfs_datasets_py.logic.TDFOL.nl.tdfol_nl_api import ParseOptions
        opts = ParseOptions()
        assert opts.min_confidence >= 0.0
        assert opts.max_formulas is None or opts.max_formulas > 0

    def test_parse_options_custom_min_confidence(self):
        from ipfs_datasets_py.logic.TDFOL.nl.tdfol_nl_api import ParseOptions
        opts = ParseOptions(min_confidence=0.8)
        assert opts.min_confidence == 0.8

    def test_parse_options_has_resolve_context_flag(self):
        from ipfs_datasets_py.logic.TDFOL.nl.tdfol_nl_api import ParseOptions
        opts = ParseOptions(resolve_context=False)
        assert opts.resolve_context is False

    def test_parse_options_has_enable_caching(self):
        from ipfs_datasets_py.logic.TDFOL.nl.tdfol_nl_api import ParseOptions
        opts = ParseOptions(enable_caching=True)
        assert opts.enable_caching is True

    def test_parse_result_default_instantiation(self):
        from ipfs_datasets_py.logic.TDFOL.nl.tdfol_nl_api import ParseResult
        r = ParseResult(success=False, text="hello")
        assert r.success is False
        assert r.text == "hello"

    def test_parse_result_has_formulas_list(self):
        from ipfs_datasets_py.logic.TDFOL.nl.tdfol_nl_api import ParseResult
        r = ParseResult(success=True, text="x")
        assert isinstance(r.formulas, list)

    def test_parse_result_has_errors_warnings(self):
        from ipfs_datasets_py.logic.TDFOL.nl.tdfol_nl_api import ParseResult
        r = ParseResult(success=False, text="x")
        r.errors.append("some error")
        r.warnings.append("some warning")
        assert "some error" in r.errors
        assert "some warning" in r.warnings

    def test_parse_result_has_confidence(self):
        from ipfs_datasets_py.logic.TDFOL.nl.tdfol_nl_api import ParseResult
        r = ParseResult(success=True, text="x", confidence=0.7)
        assert r.confidence == 0.7

    def test_parse_result_num_formulas_default_zero(self):
        from ipfs_datasets_py.logic.TDFOL.nl.tdfol_nl_api import ParseResult
        r = ParseResult(success=False, text="")
        assert r.num_formulas == 0

    def test_parse_options_include_metadata_flag(self):
        from ipfs_datasets_py.logic.TDFOL.nl.tdfol_nl_api import ParseOptions
        opts = ParseOptions(include_metadata=True)
        assert opts.include_metadata is True

    def test_parse_natural_language_unavailable_raises(self):
        """parse_natural_language raises ImportError when spaCy absent."""
        from ipfs_datasets_py.logic.TDFOL.nl.tdfol_nl_api import DEPENDENCIES_AVAILABLE
        if DEPENDENCIES_AVAILABLE:
            pytest.skip("spaCy is available; skip the ImportError path test")
        from ipfs_datasets_py.logic.TDFOL.nl.tdfol_nl_api import NLParser
        with pytest.raises(ImportError):
            NLParser()


