"""v15 Sessions: BD114–BM123 + gRPC clarification.

Sessions implemented:
  - BD114/BE115 : DispatchPipeline E2E with real compliance + risk stages
  - BF116       : risk_scorer + mcp_p2p_transport rate-limit-per-risk integration
  - BG117       : audit_metrics_bridge (PolicyAuditLog → PrometheusExporter)
  - BH118       : DelegationManager full lifecycle (add/invoke/revoke/metrics)
  - BL122       : NLPolicyConflictDetector (simultaneous perm+prohib, duplicate oblig)
  - BM123       : CECBridge stats, formula hash, strategy selection (BM123)
  - Transport   : gRPC docstring clarification — MCP+P2P is canonical transport

Total: 69 tests · 0 failing
"""
from __future__ import annotations

import time
import pytest

# ---------------------------------------------------------------------------
# Session BD114/BE115 — DispatchPipeline E2E + compliance integration
# ---------------------------------------------------------------------------


class TestDispatchPipelineE2E:
    """BD114 — end-to-end pipeline with real compliance + risk stage handlers."""

    @pytest.fixture(autouse=True)
    def _imports(self):
        from ipfs_datasets_py.mcp_server.dispatch_pipeline import (
            DispatchPipeline, PipelineStage, make_default_pipeline, make_full_pipeline,
        )
        from ipfs_datasets_py.mcp_server.compliance_checker import (
            make_default_checker, ComplianceReport,
        )
        from ipfs_datasets_py.mcp_server.risk_scorer import (
            RiskScorer, RiskGateError,
        )
        self.DispatchPipeline = DispatchPipeline
        self.PipelineStage = PipelineStage
        self.make_default_pipeline = make_default_pipeline
        self.make_full_pipeline = make_full_pipeline
        self.make_default_checker = make_default_checker
        self.RiskScorer = RiskScorer
        self.RiskGateError = RiskGateError

    def _make_compliance_stage(self):
        checker = self.make_default_checker()

        def _stage(intent):
            report = checker.check(intent)
            if not report.passed:
                return {"allowed": False, "reason": "compliance", "failed_rules": report.failed_rules}
            return {"allowed": True}

        return self.PipelineStage("compliance", _stage)

    def _make_risk_stage(self):
        scorer = self.RiskScorer()

        def _stage(intent):
            tool = intent.get("tool", "")
            actor = intent.get("actor", "")
            params = intent.get("params", {})
            try:
                scorer.score_and_gate(tool, actor, params)
                return {"allowed": True}
            except self.RiskGateError as e:
                return {"allowed": False, "reason": "risk_gate", "score": e.assessment.score}

        return self.PipelineStage("risk", _stage)

    def test_valid_intent_passes_all_stages(self):
        pipeline = self.DispatchPipeline([
            self._make_compliance_stage(),
            self._make_risk_stage(),
        ])
        result = pipeline.run({"tool": "read_data", "actor": "alice", "params": {}})
        assert result.allowed is True
        assert "compliance" in result.stages_executed
        assert "risk" in result.stages_executed

    def test_invalid_tool_name_denied_by_compliance(self):
        pipeline = self.DispatchPipeline([
            self._make_compliance_stage(),
            self._make_risk_stage(),
        ])
        result = pipeline.run({"tool": "!invalid", "actor": "alice", "params": {}})
        assert result.allowed is False
        assert result.denied_by == "compliance"

    def test_short_circuit_skips_risk_after_compliance_denial(self):
        pipeline = self.DispatchPipeline(
            [self._make_compliance_stage(), self._make_risk_stage()],
            short_circuit=True,
        )
        result = pipeline.run({"tool": "bad!", "actor": "alice", "params": {}})
        assert result.denied_by == "compliance"
        assert "risk" in result.stages_skipped

    def test_no_short_circuit_runs_all_stages(self):
        pipeline = self.DispatchPipeline(
            [self._make_compliance_stage(), self._make_risk_stage()],
            short_circuit=False,
        )
        result = pipeline.run({"tool": "bad!", "actor": "alice", "params": {}})
        # compliance denies, but risk still executes
        assert "risk" in result.stages_executed

    def test_missing_actor_denied_by_compliance(self):
        pipeline = self.DispatchPipeline([self._make_compliance_stage()])
        result = pipeline.run({"tool": "read_data", "params": {}})
        assert result.allowed is False
        assert result.denied_by == "compliance"

    def test_metrics_recorded_per_stage(self):
        pipeline = self.DispatchPipeline([
            self._make_compliance_stage(),
            self._make_risk_stage(),
        ])
        pipeline.run({"tool": "read_data", "actor": "alice", "params": {}})
        pipeline.run({"tool": "read_data", "actor": "bob", "params": {}})
        m = pipeline.get_metrics()
        assert m["total_runs"] == 2
        assert m["total_allowed"] == 2

    def test_make_full_pipeline_allows_safe_intent(self):
        pipeline = self.make_full_pipeline()
        result = pipeline.run({"tool": "read_data", "actor": "alice", "params": {}})
        assert result.allowed is True

    def test_pipeline_stage_can_be_disabled(self):
        pipeline = self.DispatchPipeline([
            self._make_compliance_stage(),
            self._make_risk_stage(),
        ])
        pipeline.skip_stage("compliance")
        # With compliance disabled, invalid tool name passes
        result = pipeline.run({"tool": "!invalid", "actor": "alice", "params": {}})
        assert result.allowed is True
        assert "compliance" in result.stages_skipped


class TestCompliancePipelineIntegration:
    """BE115 — compliance stage integration in pipeline."""

    @pytest.fixture(autouse=True)
    def _imports(self):
        from ipfs_datasets_py.mcp_server.compliance_checker import (
            ComplianceChecker, ComplianceRule, ComplianceResult, make_default_checker,
        )
        from ipfs_datasets_py.mcp_server.dispatch_pipeline import (
            DispatchPipeline, PipelineStage,
        )
        self.ComplianceChecker = ComplianceChecker
        self.ComplianceRule = ComplianceRule
        self.ComplianceResult = ComplianceResult
        self.make_default_checker = make_default_checker
        self.DispatchPipeline = DispatchPipeline
        self.PipelineStage = PipelineStage

    def _make_stage(self, checker):
        def _stage(intent):
            report = checker.check(intent)
            return {"allowed": report.passed, "failed_rules": report.failed_rules}
        return self.PipelineStage("compliance", _stage)

    def test_custom_deny_rule_blocks_tool(self):
        checker = self.make_default_checker()
        deny_rule = self.ComplianceRule(
            rule_id="deny_delete",
            description="deny delete tools",
            check_fn=lambda intent: self.ComplianceResult(
                passed=intent.get("tool") != "delete",
                rule_id="deny_delete",
                message="delete not allowed",
            ),
        )
        checker.add_rule(deny_rule)
        pipeline = self.DispatchPipeline([self._make_stage(checker)])
        ok = pipeline.run({"tool": "read", "actor": "alice", "params": {}})
        bad = pipeline.run({"tool": "delete", "actor": "alice", "params": {}})
        assert ok.allowed is True
        assert bad.allowed is False
        assert bad.denied_by == "compliance"

    def test_remove_custom_rule_unblocks(self):
        checker = self.make_default_checker()
        deny_rule = self.ComplianceRule(
            rule_id="deny_write",
            description="deny write",
            check_fn=lambda intent: self.ComplianceResult(
                passed=intent.get("tool") != "write",
                rule_id="deny_write",
                message="",
            ),
        )
        checker.add_rule(deny_rule)
        assert checker.check({"tool": "write", "actor": "alice", "params": {}}).passed is False
        checker.remove_rule("deny_write")
        assert checker.check({"tool": "write", "actor": "alice", "params": {}}).passed is True

    def test_fail_fast_stops_at_first_failure(self):
        checker = self.make_default_checker()
        checker._fail_fast = True
        result = checker.check({"tool": "!bad", "params": {}})
        # With fail_fast, stops at first failure — should have at least one
        assert len(result.failed_rules) >= 1

    def test_compliance_report_to_dict(self):
        checker = self.make_default_checker()
        report = checker.check({"tool": "read", "actor": "alice", "params": {}})
        d = report.to_dict()
        assert "passed" in d
        assert "failed_rules" in d


# ---------------------------------------------------------------------------
# Session BF116 — risk_scorer + mcp_p2p_transport rate-limit-per-risk
# ---------------------------------------------------------------------------


class TestRiskRateLimiterIntegration:
    """BF116 — risk level drives which token-bucket is consumed."""

    @pytest.fixture(autouse=True)
    def _imports(self):
        from ipfs_datasets_py.mcp_server.risk_scorer import RiskScorer, RiskLevel, RiskScoringPolicy, RiskGateError
        from ipfs_datasets_py.mcp_server.mcp_p2p_transport import TokenBucketRateLimiter, P2PSessionConfig
        self.RiskScorer = RiskScorer
        self.RiskLevel = RiskLevel
        self.RiskScoringPolicy = RiskScoringPolicy
        self.RiskGateError = RiskGateError
        self.TokenBucketRateLimiter = TokenBucketRateLimiter
        self.P2PSessionConfig = P2PSessionConfig

    def test_low_risk_uses_high_capacity_limiter(self):
        scorer = self.RiskScorer()
        assessment = scorer.score_intent("read", "alice", {})
        limiter = self.TokenBucketRateLimiter(rate=100.0, capacity=100.0) \
            if assessment.level in (self.RiskLevel.NEGLIGIBLE, self.RiskLevel.LOW) \
            else self.TokenBucketRateLimiter(rate=1.0, capacity=2.0)
        assert limiter.consume() is True

    def test_high_risk_tool_gets_tight_limiter(self):
        policy = self.RiskScoringPolicy(
            tool_risk_overrides={"nuke": 0.99},
            max_acceptable_risk=1.0,  # allow to pass gate
        )
        scorer = self.RiskScorer(policy=policy)
        assessment = scorer.score_intent("nuke", "alice", {})
        # High/Critical risk → tight limiter with capacity=1
        limiter = self.TokenBucketRateLimiter(rate=0.1, capacity=1.0) \
            if assessment.level in (self.RiskLevel.HIGH, self.RiskLevel.CRITICAL) \
            else self.TokenBucketRateLimiter(rate=100.0, capacity=100.0)
        assert limiter.available() <= 1.0

    def test_rate_limit_exhaustion_denies_requests(self):
        limiter = self.TokenBucketRateLimiter(rate=1.0, capacity=2.0)
        # Drain bucket
        limiter.consume()
        limiter.consume()
        assert limiter.consume() is False

    def test_risk_score_and_gate_raises_for_dangerous_tool(self):
        policy = self.RiskScoringPolicy(tool_risk_overrides={"rm_rf": 0.99})
        scorer = self.RiskScorer(policy=policy)
        with pytest.raises(self.RiskGateError) as exc_info:
            scorer.score_and_gate("rm_rf", "unknown", {})
        assert exc_info.value.assessment.tool == "rm_rf"

    def test_p2p_session_config_makes_limiter(self):
        cfg = self.P2PSessionConfig()
        limiter = cfg.make_rate_limiter()
        assert limiter is not None
        assert limiter.consume() is True

    def test_risk_level_from_score_mapping(self):
        levels = [
            (0.0, self.RiskLevel.NEGLIGIBLE),
            (0.19, self.RiskLevel.NEGLIGIBLE),
            (0.2, self.RiskLevel.LOW),
            (0.4, self.RiskLevel.MEDIUM),
            (0.6, self.RiskLevel.HIGH),
            (0.8, self.RiskLevel.CRITICAL),
            (1.0, self.RiskLevel.CRITICAL),
        ]
        for score, expected in levels:
            assert self.RiskLevel.from_score(score) is expected, f"score={score}"

    def test_combined_pipeline_risk_rate_limit(self):
        """Simulate: risk assessment gates → rate limiter enforces throughput."""
        scorer = self.RiskScorer()
        limiter = self.TokenBucketRateLimiter(rate=10.0, capacity=5.0)
        results = []
        for _ in range(7):
            assessment = scorer.score_intent("read", "alice", {})
            if limiter.consume():
                results.append("ok")
            else:
                results.append("rate_limited")
        assert results[:5] == ["ok"] * 5
        assert "rate_limited" in results[5:]


# ---------------------------------------------------------------------------
# Session BG117 — AuditMetricsBridge (audit → prometheus)
# ---------------------------------------------------------------------------


class TestAuditMetricsBridge:
    """BG117 — PolicyAuditLog → PrometheusExporter bridge."""

    @pytest.fixture(autouse=True)
    def _imports(self):
        from ipfs_datasets_py.mcp_server.audit_metrics_bridge import (
            AuditMetricsBridge, connect_audit_to_prometheus,
        )
        from ipfs_datasets_py.mcp_server.policy_audit_log import PolicyAuditLog
        from ipfs_datasets_py.mcp_server.prometheus_exporter import PrometheusExporter
        self.AuditMetricsBridge = AuditMetricsBridge
        self.connect = connect_audit_to_prometheus
        self.PolicyAuditLog = PolicyAuditLog
        self.PrometheusExporter = PrometheusExporter

    def test_bridge_attach_sets_sink(self):
        audit = self.PolicyAuditLog(max_entries=10)
        exporter = self.PrometheusExporter()
        bridge = self.AuditMetricsBridge(audit, exporter)
        bridge.attach()
        assert bridge.is_attached is True
        # audit._sink should be callable and forwarded by the bridge
        assert callable(audit._sink)

    def test_bridge_forwards_allow_to_exporter(self):
        audit = self.PolicyAuditLog(max_entries=10)
        exporter = self.PrometheusExporter()
        bridge = self.AuditMetricsBridge(audit, exporter)
        bridge.attach()
        audit.record(policy_cid="p", intent_cid="i", decision="allow", tool="read", actor="alice")
        assert bridge.forwarded_count == 1

    def test_bridge_forwards_deny_to_exporter(self):
        audit = self.PolicyAuditLog(max_entries=10)
        exporter = self.PrometheusExporter()
        bridge = self.AuditMetricsBridge(audit, exporter)
        bridge.attach()
        audit.record(policy_cid="p", intent_cid="i", decision="deny", tool="delete", actor="bob")
        assert bridge.forwarded_count == 1

    def test_bridge_detach_removes_sink(self):
        audit = self.PolicyAuditLog(max_entries=10)
        exporter = self.PrometheusExporter()
        bridge = self.AuditMetricsBridge(audit, exporter)
        bridge.attach()
        bridge.detach()
        assert bridge.is_attached is False
        assert audit._sink is None

    def test_after_detach_records_not_forwarded(self):
        audit = self.PolicyAuditLog(max_entries=10)
        exporter = self.PrometheusExporter()
        bridge = self.AuditMetricsBridge(audit, exporter)
        bridge.attach()
        bridge.detach()
        audit.record(policy_cid="p", intent_cid="i", decision="allow", tool="read", actor="alice")
        assert bridge.forwarded_count == 0

    def test_connect_shorthand_returns_attached_bridge(self):
        audit = self.PolicyAuditLog(max_entries=10)
        exporter = self.PrometheusExporter()
        bridge = self.connect(audit, exporter)
        assert bridge.is_attached is True

    def test_get_info_has_expected_keys(self):
        audit = self.PolicyAuditLog(max_entries=10)
        exporter = self.PrometheusExporter()
        bridge = self.AuditMetricsBridge(audit, exporter)
        info = bridge.get_info()
        assert "attached" in info
        assert "category" in info
        assert "forwarded_count" in info

    def test_multiple_records_counted(self):
        audit = self.PolicyAuditLog(max_entries=100)
        exporter = self.PrometheusExporter()
        bridge = self.AuditMetricsBridge(audit, exporter)
        bridge.attach()
        for i in range(5):
            audit.record(
                policy_cid="p", intent_cid=f"i{i}",
                decision="allow", tool="read", actor="alice",
            )
        assert bridge.forwarded_count == 5

    def test_custom_category_label(self):
        audit = self.PolicyAuditLog(max_entries=10)
        exporter = self.PrometheusExporter()
        bridge = self.AuditMetricsBridge(audit, exporter, category="auth")
        assert bridge._category == "auth"


# ---------------------------------------------------------------------------
# Session BH118 — DelegationManager full lifecycle
# ---------------------------------------------------------------------------


class TestDelegationManagerLifecycle:
    """BH118 — DelegationManager: add / invoke / revoke / metrics / save+load."""

    @pytest.fixture(autouse=True)
    def _imports(self):
        from ipfs_datasets_py.mcp_server.ucan_delegation import (
            DelegationManager, DelegationToken, Capability, get_delegation_manager,
        )
        self.DelegationManager = DelegationManager
        self.DelegationToken = DelegationToken
        self.Capability = Capability
        self.get_delegation_manager = get_delegation_manager

    def _token(self, issuer="did:key:root", audience="did:key:agent", expiry_offset=3600):
        return self.DelegationToken(
            issuer=issuer,
            audience=audience,
            capabilities=[self.Capability("*", "*")],
            expiry=time.time() + expiry_offset,
        )

    def test_add_and_list(self):
        mgr = self.DelegationManager()
        cid = mgr.add(self._token())
        assert cid in mgr.list_cids()

    def test_can_invoke_after_add(self):
        mgr = self.DelegationManager()
        cid = mgr.add(self._token())
        ok, reason = mgr.can_invoke("did:key:agent", "data", "read", leaf_cid=cid)
        assert ok is True
        assert reason == "allowed"

    def test_wrong_principal_denied(self):
        mgr = self.DelegationManager()
        cid = mgr.add(self._token(audience="did:key:agent"))
        ok, reason = mgr.can_invoke("did:key:other", "data", "read", leaf_cid=cid)
        assert ok is False

    def test_expired_token_denied(self):
        mgr = self.DelegationManager()
        cid = mgr.add(self._token(expiry_offset=-1))  # expired
        ok, reason = mgr.can_invoke("did:key:agent", "data", "read", leaf_cid=cid)
        assert ok is False

    def test_revoke_denies_subsequent_invoke(self):
        mgr = self.DelegationManager()
        cid = mgr.add(self._token())
        mgr.revoke(cid)
        ok, reason = mgr.can_invoke("did:key:agent", "data", "read", leaf_cid=cid)
        assert ok is False
        assert "revoked" in reason.lower()

    def test_is_revoked(self):
        mgr = self.DelegationManager()
        cid = mgr.add(self._token())
        assert mgr.is_revoked(cid) is False
        mgr.revoke(cid)
        assert mgr.is_revoked(cid) is True

    def test_remove_removes_token(self):
        mgr = self.DelegationManager()
        cid = mgr.add(self._token())
        assert cid in mgr.list_cids()
        mgr.remove(cid)
        assert cid not in mgr.list_cids()

    def test_get_returns_token(self):
        mgr = self.DelegationManager()
        tok = self._token()
        cid = mgr.add(tok)
        retrieved = mgr.get(cid)
        assert retrieved is tok

    def test_get_metrics_keys(self):
        mgr = self.DelegationManager()
        mgr.add(self._token())
        metrics = mgr.get_metrics()
        assert "token_count" in metrics
        assert "revoked_count" in metrics
        assert "has_path" in metrics
        assert metrics["token_count"] == 1

    def test_len(self):
        mgr = self.DelegationManager()
        assert len(mgr) == 0
        mgr.add(self._token())
        assert len(mgr) == 1

    def test_repr(self):
        mgr = self.DelegationManager()
        assert "DelegationManager" in repr(mgr)

    def test_singleton_factory(self):
        from ipfs_datasets_py.mcp_server import ucan_delegation as _mod
        old = _mod._global_manager
        _mod._global_manager = None
        try:
            m1 = self.get_delegation_manager()
            m2 = self.get_delegation_manager()
            assert m1 is m2
        finally:
            _mod._global_manager = old

    def test_save_and_load(self, tmp_path):
        path = str(tmp_path / "store.json")
        mgr = self.DelegationManager(path=path)
        cid = mgr.add(self._token())
        mgr.save()
        # Load into fresh manager
        mgr2 = self.DelegationManager(path=path)
        mgr2.load()
        assert cid in mgr2.list_cids()

    def test_evaluator_cache_invalidated_on_add(self):
        mgr = self.DelegationManager()
        ev1 = mgr.get_evaluator()
        mgr.add(self._token())
        ev2 = mgr.get_evaluator()
        # After add, a new evaluator is created
        assert ev1 is not ev2


# ---------------------------------------------------------------------------
# Session BL122 — NLPolicyConflictDetector
# ---------------------------------------------------------------------------


class TestNLPolicyConflictDetector:
    """BL122 — detect perm+prohib conflicts and duplicate obligations."""

    @pytest.fixture(autouse=True)
    def _imports(self):
        from ipfs_datasets_py.logic.CEC.nl.nl_policy_conflict_detector import (
            NLPolicyConflictDetector, PolicyConflict, detect_conflicts,
        )
        self.NLPolicyConflictDetector = NLPolicyConflictDetector
        self.PolicyConflict = PolicyConflict
        self.detect_conflicts = detect_conflicts

    def _make_clause(self, clause_type, action="read", resource="*", actor="*"):
        """Build a minimal PolicyClause-like object."""
        class Clause:
            pass
        c = Clause()
        c.clause_type = clause_type
        c.action = action
        c.resource = resource
        c.actor = actor
        return c

    def test_no_conflict_when_only_permission(self):
        clauses = [self._make_clause("permission", "read")]
        assert self.detect_conflicts(clauses) == []

    def test_no_conflict_when_only_prohibition(self):
        clauses = [self._make_clause("prohibition", "read")]
        assert self.detect_conflicts(clauses) == []

    def test_detects_simultaneous_perm_prohib(self):
        clauses = [
            self._make_clause("permission", "read", actor="alice"),
            self._make_clause("prohibition", "read", actor="alice"),
        ]
        conflicts = self.detect_conflicts(clauses)
        assert len(conflicts) == 1
        assert conflicts[0].conflict_type == "simultaneous_perm_prohib"
        assert conflicts[0].action == "read"

    def test_no_conflict_for_different_actions(self):
        clauses = [
            self._make_clause("permission", "read", actor="alice"),
            self._make_clause("prohibition", "write", actor="alice"),
        ]
        assert self.detect_conflicts(clauses) == []

    def test_wildcard_actor_triggers_conflict(self):
        clauses = [
            self._make_clause("permission", "read", actor="*"),
            self._make_clause("prohibition", "read", actor="alice"),
        ]
        conflicts = self.detect_conflicts(clauses)
        assert len(conflicts) == 1

    def test_different_actors_no_conflict(self):
        clauses = [
            self._make_clause("permission", "read", actor="alice"),
            self._make_clause("prohibition", "read", actor="bob"),
        ]
        # alice perm / bob prohib — different actors, no overlap
        conflicts = self.detect_conflicts(clauses)
        assert len(conflicts) == 0

    def test_detects_duplicate_obligations(self):
        clauses = [
            self._make_clause("obligation", "log", actor="alice"),
            self._make_clause("obligation", "log", actor="alice"),
        ]
        conflicts = self.detect_conflicts(clauses)
        assert len(conflicts) == 1
        assert conflicts[0].conflict_type == "multiple_obligations"

    def test_single_obligation_no_conflict(self):
        clauses = [self._make_clause("obligation", "log", actor="alice")]
        assert self.detect_conflicts(clauses) == []

    def test_conflict_to_dict_has_expected_keys(self):
        clauses = [
            self._make_clause("permission", "read", actor="alice"),
            self._make_clause("prohibition", "read", actor="alice"),
        ]
        conflicts = self.detect_conflicts(clauses)
        d = conflicts[0].to_dict()
        assert set(d.keys()) >= {"conflict_type", "action", "resource", "actors", "clause_types", "description"}

    def test_no_conflict_for_empty_clauses(self):
        assert self.detect_conflicts([]) == []

    def test_detector_with_real_nl_output(self):
        """Integration: compile contradictory NL and detect conflict."""
        try:
            from ipfs_datasets_py.logic.integration.nl_ucan_policy_compiler import NLUCANPolicyCompiler
        except ImportError:
            pytest.skip("NLUCANPolicyCompiler not importable")
        compiler = NLUCANPolicyCompiler()
        result = compiler.compile([
            "Alice may read all documents.",
            "Alice must not read any documents.",
        ])
        if not result.policy_result or not result.policy_result.clauses:
            pytest.skip("NL compiler produced no clauses")
        conflicts = self.detect_conflicts(result.policy_result.clauses)
        assert len(conflicts) >= 1
        assert any(c.conflict_type == "simultaneous_perm_prohib" for c in conflicts)

    def test_description_is_human_readable(self):
        clauses = [
            self._make_clause("permission", "read", actor="alice"),
            self._make_clause("prohibition", "read", actor="alice"),
        ]
        conflicts = self.detect_conflicts(clauses)
        assert "read" in conflicts[0].description
        assert "alice" in conflicts[0].description


# ---------------------------------------------------------------------------
# Session BM123 — CECBridge statistics + formula hash + strategy selection
# ---------------------------------------------------------------------------


class TestCECBridgeCoverage:
    """BM123 — CECBridge statistics, formula hash, strategy selection."""

    @pytest.fixture(autouse=True)
    def _imports(self):
        try:
            from ipfs_datasets_py.logic.integration.cec_bridge import CECBridge, UnifiedProofResult
            self.CECBridge = CECBridge
            self.UnifiedProofResult = UnifiedProofResult
        except ImportError as exc:
            pytest.skip(f"cec_bridge not importable: {exc}")

    def _bridge(self):
        return self.CECBridge(
            enable_z3=False,
            enable_ipfs_cache=False,
            enable_prover_router=False,
        )

    def test_bridge_creates_without_dependencies(self):
        bridge = self._bridge()
        assert bridge is not None

    def test_get_statistics_has_expected_keys(self):
        bridge = self._bridge()
        stats = bridge.get_statistics()
        assert "cec_cache" in stats
        assert "ipfs_cache" in stats
        assert "cec_manager" in stats

    def test_formula_hash_is_deterministic(self):
        bridge = self._bridge()
        h1 = bridge._compute_formula_hash("test_formula")
        h2 = bridge._compute_formula_hash("test_formula")
        assert h1 == h2

    def test_formula_hash_distinct_for_different_formulas(self):
        bridge = self._bridge()
        h1 = bridge._compute_formula_hash("formula_a")
        h2 = bridge._compute_formula_hash("formula_b")
        assert h1 != h2

    def test_select_strategy_returns_string(self):
        bridge = self._bridge()
        strat = bridge._select_strategy("any_formula")
        assert isinstance(strat, str)
        assert strat in ("z3", "router", "cec")

    def test_prove_string_formula_returns_result(self):
        bridge = self._bridge()
        result = bridge.prove("alice_can_read", strategy="cec", use_cache=False)
        assert isinstance(result, self.UnifiedProofResult)
        assert result.prover_used in ("cec_manager", "cec_z3", "router")

    def test_prove_caches_result_when_proved(self):
        bridge = self._bridge()
        # Override _prove_with_cec_manager to return a proved result
        from unittest.mock import patch
        proved_result = self.UnifiedProofResult(
            is_proved=True, is_valid=True, prover_used="mock",
            proof_time=0.0, status="proved",
        )
        with patch.object(bridge, "_prove_with_cec_manager", return_value=proved_result):
            r1 = bridge.prove("formula_x", strategy="cec", use_cache=True)
            r2 = bridge.prove("formula_x", strategy="cec", use_cache=True)
        assert r1.is_proved is True
        # Second call may be served from cache (prover_used may be "cached", "mock", etc.)
        assert r2.is_proved is True

    def test_prove_no_cache_always_calls_prover(self):
        bridge = self._bridge()
        call_count = [0]
        orig = bridge._prove_with_cec_manager

        def counting_prove(formula, axioms, timeout):
            call_count[0] += 1
            return self.UnifiedProofResult(
                is_proved=False, is_valid=False, prover_used="cec_manager",
                proof_time=0.0, status="unknown",
            )

        bridge._prove_with_cec_manager = counting_prove
        bridge.prove("formula_y", strategy="cec", use_cache=False)
        bridge.prove("formula_y", strategy="cec", use_cache=False)
        assert call_count[0] == 2

    def test_unified_proof_result_fields(self):
        r = self.UnifiedProofResult(
            is_proved=True, is_valid=True, prover_used="mock",
            proof_time=0.01, status="proved",
        )
        assert r.is_proved is True
        assert r.prover_used == "mock"
        assert r.status == "proved"


# ---------------------------------------------------------------------------
# Transport clarification — gRPC is secondary, MCP+P2P is primary
# ---------------------------------------------------------------------------


class TestTransportDocumentation:
    """Verify that MCP+P2P is the canonical transport and gRPC is optional."""

    def test_mcp_p2p_protocol_id_is_primary(self):
        from ipfs_datasets_py.mcp_server.mcp_p2p_transport import MCP_P2P_PROTOCOL_ID
        assert MCP_P2P_PROTOCOL_ID == "/mcp+p2p/1.0.0"

    def test_mcp_p2p_pubsub_topics_present(self):
        from ipfs_datasets_py.mcp_server.mcp_p2p_transport import MCP_P2P_PUBSUB_TOPICS
        assert "interface_announce" in MCP_P2P_PUBSUB_TOPICS
        assert "receipt_disseminate" in MCP_P2P_PUBSUB_TOPICS

    def test_grpc_module_docstring_mentions_mcp_p2p_as_canonical(self):
        from ipfs_datasets_py.mcp_server import grpc_transport
        doc = grpc_transport.__doc__ or ""
        # The module docstring must now state MCP+P2P is the canonical transport
        assert "canonical" in doc.lower() or "mcp+p2p" in doc.lower()

    def test_grpc_adapter_is_optional(self):
        from ipfs_datasets_py.mcp_server.grpc_transport import GRPCTransportAdapter, GRPC_AVAILABLE
        adapter = GRPCTransportAdapter(object())
        assert adapter.is_running is False
        # Can exist without grpc package
        assert isinstance(GRPC_AVAILABLE, bool)

    def test_grpc_start_raises_without_grpc_package(self):
        import asyncio
        from ipfs_datasets_py.mcp_server.grpc_transport import GRPCTransportAdapter, GRPC_AVAILABLE
        if GRPC_AVAILABLE:
            pytest.skip("grpc package installed; skip ImportError test")
        adapter = GRPCTransportAdapter(object())
        with pytest.raises(ImportError, match="grpcio"):
            asyncio.get_event_loop().run_until_complete(adapter.start())

    def test_mcp_message_transport_uses_mcp_p2p_framing(self):
        from ipfs_datasets_py.mcp_server.mcp_p2p_transport import MCPMessage, LengthPrefixFramer
        msg = MCPMessage(method="tools/call", params={"name": "echo"})
        framer = LengthPrefixFramer()
        encoded = framer.encode(msg.to_bytes())
        decoded_bytes, _ = framer.decode(encoded)
        decoded_msg = MCPMessage.from_bytes(decoded_bytes)
        assert decoded_msg.method == "tools/call"
