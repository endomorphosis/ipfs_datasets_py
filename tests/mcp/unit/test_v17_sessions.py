"""v17 sessions: BX134/BZ136/CA137/CB138/CC139/CD140/CE141/CH144.

Coverage
--------
BX134  NLPolicyConflictDetector.detect_and_warn() emits warnings + audit entries
BZ136  UCANPolicyBridge.evaluate_with_manager() wired to DelegationManager
CA137  DispatchPipeline(audit_log=...) records every stage result
CB138  detect_i18n_conflicts() for French/Spanish/German + I18NConflictResult
CC139  DelegationChain.to_ascii_tree() + __str__ + __len__
CD140  logic/api.py smoke: all __all__ symbols load without ImportError
CE141  PipelineMetricsRecorder(audit_log=...) records summary on each run
CH144  delegation_audit_tool — 7 MCP tools for DelegationManager + PolicyAuditLog
"""
from __future__ import annotations

import warnings
import pytest


# ===========================================================================
# BX134 — NLPolicyConflictDetector.detect_and_warn()
# ===========================================================================

class TestBX134DetectAndWarn:
    """BX134: detect_and_warn emits UserWarning and writes audit entries."""

    @pytest.fixture()
    def two_conflict_clauses(self):
        class _Clause:
            def __init__(self, ct, action, actor=None, resource=None):
                self.clause_type = ct
                self.action = action
                self.actor = actor or "*"
                self.resource = resource or "*"
        return [
            _Clause("permission", "read"),
            _Clause("prohibition", "read"),
        ]

    def _make_audit(self):
        from ipfs_datasets_py.mcp_server.policy_audit_log import PolicyAuditLog
        return PolicyAuditLog()

    def test_no_conflicts_no_warnings(self):
        from ipfs_datasets_py.logic.CEC.nl.nl_policy_conflict_detector import NLPolicyConflictDetector
        det = NLPolicyConflictDetector()
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            conflicts = det.detect_and_warn([])
        assert conflicts == []
        assert len(w) == 0

    def test_conflict_emits_user_warning(self, two_conflict_clauses):
        from ipfs_datasets_py.logic.CEC.nl.nl_policy_conflict_detector import NLPolicyConflictDetector
        det = NLPolicyConflictDetector()
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            conflicts = det.detect_and_warn(two_conflict_clauses)
        assert len(conflicts) == 1
        assert len(w) == 1
        assert issubclass(w[0].category, UserWarning)
        assert "conflict" in str(w[0].message).lower()

    def test_conflict_writes_audit_entry(self, two_conflict_clauses):
        from ipfs_datasets_py.logic.CEC.nl.nl_policy_conflict_detector import NLPolicyConflictDetector
        det = NLPolicyConflictDetector()
        audit = self._make_audit()
        with warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            det.detect_and_warn(two_conflict_clauses, audit_log=audit)
        assert audit.total_recorded() == 1
        entry = audit.recent(1)[0]
        assert entry.decision == "deny"
        assert entry.actor == "conflict_detector"

    def test_no_audit_when_audit_log_none(self, two_conflict_clauses):
        """Should not raise even without audit_log."""
        from ipfs_datasets_py.logic.CEC.nl.nl_policy_conflict_detector import NLPolicyConflictDetector
        det = NLPolicyConflictDetector()
        with warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            conflicts = det.detect_and_warn(two_conflict_clauses, audit_log=None)
        assert len(conflicts) == 1

    def test_policy_cid_used_in_audit(self, two_conflict_clauses):
        from ipfs_datasets_py.logic.CEC.nl.nl_policy_conflict_detector import NLPolicyConflictDetector
        det = NLPolicyConflictDetector()
        audit = self._make_audit()
        with warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            det.detect_and_warn(two_conflict_clauses, audit_log=audit, policy_cid="custom-policy-123")
        entry = audit.recent(1)[0]
        assert entry.policy_cid == "custom-policy-123"


# ===========================================================================
# BZ136 — UCANPolicyBridge.evaluate_with_manager()
# ===========================================================================

class TestBZ136EvaluateWithManager:
    """BZ136: evaluate_with_manager uses real DelegationManager for UCAN check."""

    def _make_bridge(self):
        from ipfs_datasets_py.logic.integration.ucan_policy_bridge import UCANPolicyBridge
        return UCANPolicyBridge()

    def _make_manager(self):
        from ipfs_datasets_py.mcp_server.ucan_delegation import DelegationManager
        return DelegationManager()

    def test_manager_none_falls_back_to_evaluate(self):
        """manager=None must fall back to the standard evaluate() path."""
        bridge = self._make_bridge()
        result = bridge.evaluate_with_manager("test-policy", tool="read", manager=None)
        assert result.policy_cid == "test-policy"
        assert result.decision in ("allow", "deny")

    def test_result_has_expected_shape(self):
        bridge = self._make_bridge()
        mgr = self._make_manager()
        result = bridge.evaluate_with_manager(
            "p1", tool="write", actor="alice", leaf_cid="cid1", manager=mgr
        )
        assert hasattr(result, "decision")
        assert hasattr(result, "ucan_allowed")
        assert hasattr(result, "revoked")
        assert hasattr(result, "reason")

    def test_revoked_token_returns_deny(self):
        bridge = self._make_bridge()
        mgr = self._make_manager()
        mgr.revoke("revoked-cid")
        result = bridge.evaluate_with_manager(
            "p1", tool="read", actor="alice", leaf_cid="revoked-cid", manager=mgr
        )
        assert result.decision == "deny"
        assert result.revoked is True

    def test_non_revoked_ucan_check_runs(self):
        bridge = self._make_bridge()
        mgr = self._make_manager()
        # No chain in store → UCAN check produces None or False; still a result
        result = bridge.evaluate_with_manager(
            "p1", tool="read", actor="alice", leaf_cid="non-existent-cid", manager=mgr
        )
        assert result.decision in ("allow", "deny")
        # ucan_allowed may be False/None when no chain present
        assert result.ucan_allowed in (True, False, None)

    def test_no_leaf_cid_skips_ucan_check(self):
        bridge = self._make_bridge()
        mgr = self._make_manager()
        result = bridge.evaluate_with_manager(
            "p1", tool="read", actor="alice", leaf_cid=None, manager=mgr
        )
        # No revocation check, no UCAN chain check
        assert result.revoked is False
        assert result.ucan_allowed is None


# ===========================================================================
# CA137 — DispatchPipeline audit_log parameter
# ===========================================================================

class TestCA137DispatchPipelineAudit:
    """CA137: DispatchPipeline records each stage result to PolicyAuditLog."""

    def _make_audit(self):
        from ipfs_datasets_py.mcp_server.policy_audit_log import PolicyAuditLog
        return PolicyAuditLog()

    def _make_allow_stage(self, name="allow"):
        from ipfs_datasets_py.mcp_server.dispatch_pipeline import PipelineStage
        return PipelineStage(name=name, handler=lambda i: {"allowed": True})

    def _make_deny_stage(self, name="deny"):
        from ipfs_datasets_py.mcp_server.dispatch_pipeline import PipelineStage
        return PipelineStage(name=name, handler=lambda i: {"allowed": False, "reason": "denied"})

    def test_audit_log_receives_allow_entry(self):
        from ipfs_datasets_py.mcp_server.dispatch_pipeline import DispatchPipeline
        audit = self._make_audit()
        pipeline = DispatchPipeline(audit_log=audit)
        pipeline.add_stage(self._make_allow_stage())
        pipeline.run({"tool": "read", "actor": "alice"})
        assert audit.total_recorded() == 1
        entry = audit.recent(1)[0]
        assert entry.decision == "allow"

    def test_audit_log_receives_deny_entry(self):
        from ipfs_datasets_py.mcp_server.dispatch_pipeline import DispatchPipeline
        audit = self._make_audit()
        pipeline = DispatchPipeline(audit_log=audit)
        pipeline.add_stage(self._make_deny_stage())
        pipeline.run({"tool": "write", "actor": "eve"})
        assert audit.total_recorded() >= 1
        entry = audit.recent(1)[0]
        assert entry.decision == "deny"

    def test_no_audit_when_audit_log_none(self):
        """No audit_log → pipeline runs without error."""
        from ipfs_datasets_py.mcp_server.dispatch_pipeline import DispatchPipeline
        pipeline = DispatchPipeline(audit_log=None)
        pipeline.add_stage(self._make_allow_stage())
        result = pipeline.run({"tool": "read"})
        assert result.allowed is True

    def test_two_stages_two_audit_entries(self):
        from ipfs_datasets_py.mcp_server.dispatch_pipeline import DispatchPipeline
        audit = self._make_audit()
        pipeline = DispatchPipeline(audit_log=audit, short_circuit=False)
        pipeline.add_stage(self._make_allow_stage("s1"))
        pipeline.add_stage(self._make_allow_stage("s2"))
        pipeline.run({"tool": "read", "actor": "alice"})
        assert audit.total_recorded() == 2

    def test_short_circuit_limits_audit_entries(self):
        from ipfs_datasets_py.mcp_server.dispatch_pipeline import DispatchPipeline
        audit = self._make_audit()
        pipeline = DispatchPipeline(audit_log=audit, short_circuit=True)
        pipeline.add_stage(self._make_deny_stage("deny"))
        pipeline.add_stage(self._make_allow_stage("allow"))
        pipeline.run({"tool": "read", "actor": "eve"})
        # Only the deny stage ran
        assert audit.total_recorded() == 1

    def test_actor_field_in_audit_entry(self):
        from ipfs_datasets_py.mcp_server.dispatch_pipeline import DispatchPipeline
        audit = self._make_audit()
        pipeline = DispatchPipeline(audit_log=audit)
        pipeline.add_stage(self._make_allow_stage())
        pipeline.run({"tool": "list", "actor": "bob"})
        entry = audit.recent(1)[0]
        assert entry.actor == "bob"


# ===========================================================================
# CB138 — detect_i18n_conflicts / I18NConflictResult
# ===========================================================================

class TestCB138I18NConflicts:
    """CB138: detect_i18n_conflicts for French/Spanish/German."""

    def test_french_permission_and_prohibition(self):
        from ipfs_datasets_py.logic.CEC.nl.nl_policy_conflict_detector import detect_i18n_conflicts
        text = "Alice peut utiliser le système mais ne doit pas partager les données"
        r = detect_i18n_conflicts(text, language="fr")
        assert r.has_permission is True
        assert r.has_prohibition is True
        assert r.has_simultaneous_conflict is True
        assert r.language == "fr"

    def test_french_permission_only(self):
        from ipfs_datasets_py.logic.CEC.nl.nl_policy_conflict_detector import detect_i18n_conflicts
        r = detect_i18n_conflicts("L'agent peut accéder au système", language="fr")
        assert r.has_permission is True
        assert r.has_prohibition is False
        assert r.has_simultaneous_conflict is False

    def test_spanish_simultaneous_conflict(self):
        from ipfs_datasets_py.logic.CEC.nl.nl_policy_conflict_detector import detect_i18n_conflicts
        text = "El agente puede acceder pero no debe compartir los datos"
        r = detect_i18n_conflicts(text, language="es")
        assert r.has_permission is True
        assert r.has_prohibition is True
        assert r.has_simultaneous_conflict is True
        assert r.language == "es"

    def test_german_prohibition_only(self):
        from ipfs_datasets_py.logic.CEC.nl.nl_policy_conflict_detector import detect_i18n_conflicts
        r = detect_i18n_conflicts("Das ist verboten", language="de")
        assert r.has_prohibition is True
        assert r.has_permission is False
        assert r.has_simultaneous_conflict is False
        assert r.language == "de"

    def test_unknown_language_returns_no_conflict(self):
        from ipfs_datasets_py.logic.CEC.nl.nl_policy_conflict_detector import detect_i18n_conflicts
        r = detect_i18n_conflicts("some text", language="xx")
        assert r.has_permission is False
        assert r.has_prohibition is False
        assert r.has_simultaneous_conflict is False

    def test_i18n_result_to_dict(self):
        from ipfs_datasets_py.logic.CEC.nl.nl_policy_conflict_detector import detect_i18n_conflicts
        r = detect_i18n_conflicts("peut accéder mais interdit", language="fr")
        d = r.to_dict()
        assert "language" in d
        assert "has_simultaneous_conflict" in d
        assert "matched_permission_keywords" in d
        assert "matched_prohibition_keywords" in d

    def test_matched_keywords_populated(self):
        from ipfs_datasets_py.logic.CEC.nl.nl_policy_conflict_detector import detect_i18n_conflicts
        r = detect_i18n_conflicts("peut accéder mais interdit d'exporter", language="fr")
        assert "peut" in r.matched_permission_keywords
        assert "interdit" in r.matched_prohibition_keywords

    def test_i18n_result_class_available_from_api(self):
        import ipfs_datasets_py.logic.api as api
        assert "detect_i18n_conflicts" in api.__all__
        assert "I18NConflictResult" in api.__all__


# ===========================================================================
# CC139 — DelegationChain.to_ascii_tree() + __str__ + __len__
# ===========================================================================

class TestCC139DelegationChainAscii:
    """CC139: DelegationChain ASCII visualization."""

    def _make_chain(self, n=2):
        import time
        from ipfs_datasets_py.mcp_server.ucan_delegation import (
            DelegationChain, DelegationToken, Capability,
        )
        chain = DelegationChain()
        now = time.time()
        cap = Capability(resource="logic/*", ability="invoke/*")
        dids = [f"did:key:actor{i}" for i in range(n + 1)]
        for i in range(n):
            chain.append(DelegationToken(
                issuer=dids[i],
                audience=dids[i + 1],
                capabilities=[cap],
                expiry=now + 3600,
            ))
        return chain

    def test_empty_chain_returns_sentinel(self):
        from ipfs_datasets_py.mcp_server.ucan_delegation import DelegationChain
        c = DelegationChain()
        assert c.to_ascii_tree() == "(empty chain)"

    def test_str_delegates_to_ascii_tree(self):
        chain = self._make_chain(2)
        assert str(chain) == chain.to_ascii_tree()

    def test_ascii_tree_contains_token_count(self):
        chain = self._make_chain(3)
        tree = chain.to_ascii_tree()
        assert "3 tokens" in tree

    def test_ascii_tree_shows_issuer_audience(self):
        chain = self._make_chain(2)
        tree = chain.to_ascii_tree()
        assert "did:key:actor0" in tree
        assert "did:key:actor1" in tree
        assert "did:key:actor2" in tree
        assert "→" in tree

    def test_ascii_tree_last_row_uses_corner(self):
        chain = self._make_chain(2)
        tree = chain.to_ascii_tree()
        lines = tree.splitlines()
        assert lines[-1].startswith("└─")

    def test_ascii_tree_middle_rows_use_branch(self):
        chain = self._make_chain(3)
        tree = chain.to_ascii_tree()
        lines = tree.splitlines()
        # First token row (index 1) should use ├─
        assert lines[1].startswith("├─")

    def test_len_returns_token_count(self):
        chain = self._make_chain(4)
        assert len(chain) == 4

    def test_len_empty_chain(self):
        from ipfs_datasets_py.mcp_server.ucan_delegation import DelegationChain
        assert len(DelegationChain()) == 0

    def test_single_token_uses_corner_only(self):
        chain = self._make_chain(1)
        tree = chain.to_ascii_tree()
        lines = tree.splitlines()
        assert lines[-1].startswith("└─")
        assert "1 token" in tree

    def test_ascii_tree_contains_caps(self):
        chain = self._make_chain(1)
        tree = chain.to_ascii_tree()
        assert "invoke/*" in tree or "logic/*" in tree


# ===========================================================================
# CD140 — logic/api.py smoke tests
# ===========================================================================

class TestCD140ApiSmoke:
    """CD140: all __all__ symbols in logic/api.py load without ImportError."""

    def test_all_symbols_importable(self):
        import ipfs_datasets_py.logic.api as api
        errors = []
        for name in api.__all__:
            if not hasattr(api, name):
                errors.append(name)
        assert errors == [], f"Missing from api module: {errors}"

    def test_all_list_is_nonempty(self):
        import ipfs_datasets_py.logic.api as api
        assert len(api.__all__) > 50  # well over 50 symbols expected

    def test_delegation_manager_accessible(self):
        import ipfs_datasets_py.logic.api as api
        if "DelegationManager" not in api.__all__:
            pytest.skip("DelegationManager not available")
        assert hasattr(api, "DelegationManager")

    def test_detect_i18n_conflicts_accessible(self):
        import ipfs_datasets_py.logic.api as api
        if "detect_i18n_conflicts" not in api.__all__:
            pytest.skip("detect_i18n_conflicts not available")
        assert callable(api.detect_i18n_conflicts)

    def test_i18n_result_class_accessible(self):
        import ipfs_datasets_py.logic.api as api
        if "I18NConflictResult" not in api.__all__:
            pytest.skip("I18NConflictResult not available")
        assert api.I18NConflictResult is not None

    def test_ucan_policy_bridge_accessible(self):
        import ipfs_datasets_py.logic.api as api
        assert "UCANPolicyBridge" in api.__all__
        assert hasattr(api, "UCANPolicyBridge")

    def test_detect_conflicts_callable(self):
        import ipfs_datasets_py.logic.api as api
        if "detect_conflicts" not in api.__all__:
            pytest.skip("detect_conflicts not available")
        assert callable(api.detect_conflicts)


# ===========================================================================
# CE141 — PipelineMetricsRecorder(audit_log=...) records on record_run
# ===========================================================================

class TestCE141MetricsRecorderAudit:
    """CE141: PipelineMetricsRecorder writes summary audit entry on record_run."""

    def _make_audit(self):
        from ipfs_datasets_py.mcp_server.policy_audit_log import PolicyAuditLog
        return PolicyAuditLog()

    def test_record_run_allow_writes_audit(self):
        from ipfs_datasets_py.mcp_server.dispatch_pipeline import PipelineMetricsRecorder
        audit = self._make_audit()
        rec = PipelineMetricsRecorder(audit_log=audit)
        rec.record_run(allowed=True)
        assert audit.total_recorded() == 1
        entry = audit.recent(1)[0]
        assert entry.decision == "allow"

    def test_record_run_deny_writes_audit(self):
        from ipfs_datasets_py.mcp_server.dispatch_pipeline import PipelineMetricsRecorder
        audit = self._make_audit()
        rec = PipelineMetricsRecorder(audit_log=audit)
        rec.record_run(allowed=False)
        entry = audit.recent(1)[0]
        assert entry.decision == "deny"

    def test_no_audit_when_audit_log_none(self):
        from ipfs_datasets_py.mcp_server.dispatch_pipeline import PipelineMetricsRecorder
        rec = PipelineMetricsRecorder(audit_log=None)
        rec.record_run(allowed=True)  # should not raise

    def test_multiple_runs_multiple_entries(self):
        from ipfs_datasets_py.mcp_server.dispatch_pipeline import PipelineMetricsRecorder
        audit = self._make_audit()
        rec = PipelineMetricsRecorder(audit_log=audit)
        rec.record_run(allowed=True)
        rec.record_run(allowed=False)
        rec.record_run(allowed=True)
        assert audit.total_recorded() == 3

    def test_audit_entry_uses_namespace(self):
        from ipfs_datasets_py.mcp_server.dispatch_pipeline import PipelineMetricsRecorder
        audit = self._make_audit()
        rec = PipelineMetricsRecorder(namespace="my_pipeline", audit_log=audit)
        rec.record_run(allowed=True)
        entry = audit.recent(1)[0]
        assert "my_pipeline" in entry.policy_cid

    def test_counters_still_increment_with_audit(self):
        from ipfs_datasets_py.mcp_server.dispatch_pipeline import PipelineMetricsRecorder
        audit = self._make_audit()
        rec = PipelineMetricsRecorder(audit_log=audit)
        rec.record_run(allowed=True)
        rec.record_run(allowed=True)
        rec.record_run(allowed=False)
        m = rec.get_metrics()
        assert m["total_runs"] == 3
        assert m["total_allowed"] == 2
        assert m["total_denied"] == 1


# ===========================================================================
# CH144 — delegation_audit_tool MCP tools
# ===========================================================================

class TestCH144DelegationAuditTool:
    """CH144: 7 MCP tools for DelegationManager + PolicyAuditLog."""

    def test_tool_list_has_7_entries(self):
        from ipfs_datasets_py.mcp_server.tools.logic_tools.delegation_audit_tool import (
            DELEGATION_AUDIT_TOOLS,
        )
        assert len(DELEGATION_AUDIT_TOOLS) >= 7  # CI145 added delegation_chain_ascii (v18)

    def test_all_tools_have_name_description_function(self):
        from ipfs_datasets_py.mcp_server.tools.logic_tools.delegation_audit_tool import (
            DELEGATION_AUDIT_TOOLS,
        )
        for t in DELEGATION_AUDIT_TOOLS:
            assert "name" in t
            assert "description" in t
            assert callable(t["function"])

    def test_delegation_get_metrics_ok(self):
        from ipfs_datasets_py.mcp_server.tools.logic_tools.delegation_audit_tool import (
            delegation_get_metrics,
        )
        r = delegation_get_metrics()
        assert r["status"] == "ok"
        assert "token_count" in r
        assert "revoked_count" in r

    def test_audit_log_stats_ok(self):
        from ipfs_datasets_py.mcp_server.tools.logic_tools.delegation_audit_tool import (
            audit_log_stats,
        )
        r = audit_log_stats()
        assert r["status"] == "ok"
        assert "total_recorded" in r

    def test_audit_log_recent_ok(self):
        from ipfs_datasets_py.mcp_server.tools.logic_tools.delegation_audit_tool import (
            audit_log_recent,
        )
        r = audit_log_recent(n=5)
        assert r["status"] == "ok"
        assert isinstance(r["entries"], list)

    def test_delegation_add_token_ok(self):
        from ipfs_datasets_py.mcp_server.tools.logic_tools.delegation_audit_tool import (
            delegation_add_token,
        )
        r = delegation_add_token(
            issuer="did:key:root",
            audience="did:key:agent",
            resource="*",
            ability="*",
            lifetime_seconds=3600,
        )
        assert r["status"] == "ok"
        assert "cid" in r

    def test_delegation_revoke_ok(self):
        from ipfs_datasets_py.mcp_server.tools.logic_tools.delegation_audit_tool import (
            delegation_revoke,
        )
        r = delegation_revoke("some-cid-xyz")
        assert r["status"] == "ok"
        assert r["revoked_cid"] == "some-cid-xyz"

    def test_delegation_revoke_chain_ok(self):
        from ipfs_datasets_py.mcp_server.tools.logic_tools.delegation_audit_tool import (
            delegation_revoke_chain,
        )
        r = delegation_revoke_chain("root-cid-abc")
        assert r["status"] == "ok"
        assert "revoked_count" in r
        assert r["revoked_count"] >= 1

    def test_delegation_can_invoke_ok(self):
        from ipfs_datasets_py.mcp_server.tools.logic_tools.delegation_audit_tool import (
            delegation_can_invoke,
        )
        r = delegation_can_invoke(principal="alice", tool="read")
        assert r["status"] == "ok"
        assert "allowed" in r
        assert "reason" in r

    def test_tool_names_are_strings(self):
        from ipfs_datasets_py.mcp_server.tools.logic_tools.delegation_audit_tool import (
            DELEGATION_AUDIT_TOOLS,
        )
        names = [t["name"] for t in DELEGATION_AUDIT_TOOLS]
        assert all(isinstance(n, str) for n in names)
        assert "delegation_add_token" in names
        assert "audit_log_stats" in names
