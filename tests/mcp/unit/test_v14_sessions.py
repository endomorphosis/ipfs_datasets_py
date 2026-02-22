"""v14 MCP sessions — AT104/AU105/AV106/AW107/AX108/AY109/AZ110.

Covers:
  AT104 — dispatch_pipeline.py  (DispatchPipeline + PipelineMetricsRecorder)
  AU105 — mcp_p2p_transport.py  (TokenBucketRateLimiter + LengthPrefixFramer + MCPMessage)
  AV106 — compliance_checker.py (ComplianceChecker + custom rule add/remove)
  AW107 — risk_scorer.py        (RiskScorer + score_and_gate)
  AX108 — policy_audit_log.py   (sink callable + JSONL file + stats)
  AY109 — did_key_manager.py    (rotate_key + reload + info)
  AZ110 — secrets_vault.py      (list/iter/delete + encrypted round-trip)
"""
from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import time
import threading
from pathlib import Path
from typing import List
from unittest.mock import patch, MagicMock

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_REPO = Path(__file__).resolve().parents[3]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))


# ===========================================================================
# AT104 — DispatchPipeline + PipelineMetricsRecorder
# ===========================================================================

class TestDispatchPipelineBasics:
    def test_import(self):
        from ipfs_datasets_py.mcp_server.dispatch_pipeline import (
            DispatchPipeline, PipelineStage, PipelineResult, PipelineMetricsRecorder,
        )
        assert DispatchPipeline is not None

    def test_make_default_pipeline_runs(self):
        from ipfs_datasets_py.mcp_server.dispatch_pipeline import make_default_pipeline
        p = make_default_pipeline()
        result = p.run({"tool": "read", "actor": "alice", "params": {}})
        assert result.allowed is True
        assert len(result.stages_executed) >= 1

    def test_missing_tool_denied(self):
        from ipfs_datasets_py.mcp_server.dispatch_pipeline import make_default_pipeline
        p = make_default_pipeline()
        result = p.run({"actor": "alice", "params": {}})
        # tool_name_check stage returns allowed=False when tool is missing/empty
        assert result.allowed is False
        assert result.denied_by == "tool_name_check"

    def test_short_circuit_skips_remaining(self):
        from ipfs_datasets_py.mcp_server.dispatch_pipeline import (
            DispatchPipeline, PipelineStage,
        )
        ran = []

        def deny_all(intent):
            return {"allowed": False, "reason": "deny"}

        def should_not_run(intent):
            ran.append("stage2")
            return {"allowed": True}

        p = DispatchPipeline(stages=[
            PipelineStage(name="deny", handler=deny_all),
            PipelineStage(name="after", handler=should_not_run),
        ], short_circuit=True)
        result = p.run({"tool": "read"})
        assert result.allowed is False
        assert "after" in result.stages_skipped
        assert "stage2" not in ran

    def test_no_short_circuit_runs_all(self):
        from ipfs_datasets_py.mcp_server.dispatch_pipeline import (
            DispatchPipeline, PipelineStage,
        )
        ran = []

        def deny_first(intent):
            return {"allowed": False}

        def record_second(intent):
            ran.append("second")
            return {"allowed": True}

        p = DispatchPipeline(stages=[
            PipelineStage(name="s1", handler=deny_first),
            PipelineStage(name="s2", handler=record_second),
        ], short_circuit=False)
        p.run({"tool": "read"})
        assert "second" in ran

    def test_skip_stage_disables(self):
        from ipfs_datasets_py.mcp_server.dispatch_pipeline import (
            DispatchPipeline, PipelineStage,
        )
        ran = []

        def recorder(intent):
            ran.append("ran")
            return {"allowed": True}

        p = DispatchPipeline(stages=[PipelineStage(name="s1", handler=recorder)])
        p.skip_stage("s1")
        result = p.run({"tool": "read"})
        assert result.allowed is True
        assert "s1" in result.stages_skipped
        assert "ran" not in ran

    def test_enable_stage_re_enables(self):
        from ipfs_datasets_py.mcp_server.dispatch_pipeline import (
            DispatchPipeline, PipelineStage,
        )
        ran = []

        def recorder(intent):
            ran.append("ran")
            return {"allowed": True}

        p = DispatchPipeline(stages=[PipelineStage(name="s1", handler=recorder)])
        p.skip_stage("s1")
        p.enable_stage("s1")
        p.run({"tool": "read"})
        assert "ran" in ran

    def test_stage_names_property(self):
        from ipfs_datasets_py.mcp_server.dispatch_pipeline import make_full_pipeline
        p = make_full_pipeline()
        names = p.stage_names
        assert "compliance" in names
        assert "risk" in names
        assert "policy" in names

    def test_handler_exception_fail_open(self):
        from ipfs_datasets_py.mcp_server.dispatch_pipeline import (
            DispatchPipeline, PipelineStage,
        )

        def raise_fn(intent):
            raise RuntimeError("boom")

        p = DispatchPipeline(stages=[PipelineStage(name="s1", handler=raise_fn, fail_open=True)])
        result = p.run({"tool": "read"})
        # fail_open=True means exception → allowed=True
        assert result.allowed is True

    def test_handler_exception_fail_closed(self):
        from ipfs_datasets_py.mcp_server.dispatch_pipeline import (
            DispatchPipeline, PipelineStage,
        )

        def raise_fn(intent):
            raise RuntimeError("boom")

        p = DispatchPipeline(stages=[PipelineStage(name="s1", handler=raise_fn, fail_open=False)])
        result = p.run({"tool": "read"})
        assert result.allowed is False


class TestPipelineMetricsRecorder:
    def test_initial_state(self):
        from ipfs_datasets_py.mcp_server.dispatch_pipeline import PipelineMetricsRecorder
        r = PipelineMetricsRecorder()
        m = r.get_metrics()
        assert m["total_runs"] == 0
        assert m["total_allowed"] == 0

    def test_record_run_increments(self):
        from ipfs_datasets_py.mcp_server.dispatch_pipeline import PipelineMetricsRecorder
        r = PipelineMetricsRecorder()
        r.record_run(allowed=True)
        r.record_run(allowed=False)
        m = r.get_metrics()
        assert m["total_runs"] == 2
        assert m["total_allowed"] == 1
        assert m["total_denied"] == 1

    def test_record_stage_execution(self):
        from ipfs_datasets_py.mcp_server.dispatch_pipeline import PipelineMetricsRecorder
        r = PipelineMetricsRecorder()
        r.record_stage("s1", skipped=False, duration_ms=5.0)
        m = r.get_metrics()
        assert m["stage_executions"]["s1"] == 1
        assert abs(m["avg_stage_duration_ms"]["s1"] - 5.0) < 0.01

    def test_record_stage_skipped(self):
        from ipfs_datasets_py.mcp_server.dispatch_pipeline import PipelineMetricsRecorder
        r = PipelineMetricsRecorder()
        r.record_stage("s1", skipped=True)
        m = r.get_metrics()
        assert m["stage_skips"]["s1"] == 1
        assert "s1" not in m["stage_executions"]

    def test_reset_clears_all(self):
        from ipfs_datasets_py.mcp_server.dispatch_pipeline import PipelineMetricsRecorder
        r = PipelineMetricsRecorder()
        r.record_run(allowed=True)
        r.record_stage("s1", skipped=False, duration_ms=1.0)
        r.reset()
        m = r.get_metrics()
        assert m["total_runs"] == 0
        assert m["stage_executions"] == {}

    def test_namespace_in_metrics(self):
        from ipfs_datasets_py.mcp_server.dispatch_pipeline import PipelineMetricsRecorder
        r = PipelineMetricsRecorder(namespace="my_ns")
        assert r.get_metrics()["namespace"] == "my_ns"

    def test_pipeline_get_metrics_delegates(self):
        from ipfs_datasets_py.mcp_server.dispatch_pipeline import (
            make_default_pipeline, PipelineMetricsRecorder,
        )
        rec = PipelineMetricsRecorder()
        p = make_default_pipeline(metrics_recorder=rec)
        p.run({"tool": "read", "actor": "alice"})
        m = p.get_metrics()
        assert m["total_runs"] == 1


# ===========================================================================
# AU105 — TokenBucketRateLimiter + LengthPrefixFramer + MCPMessage
# ===========================================================================

class TestTokenBucketRateLimiter:
    def test_consume_succeeds_when_available(self):
        from ipfs_datasets_py.mcp_server.mcp_p2p_transport import TokenBucketRateLimiter
        lim = TokenBucketRateLimiter(rate=10.0, capacity=10.0)
        assert lim.consume(1.0) is True

    def test_consume_fails_when_empty(self):
        from ipfs_datasets_py.mcp_server.mcp_p2p_transport import TokenBucketRateLimiter
        lim = TokenBucketRateLimiter(rate=1.0, capacity=5.0)
        # Drain the bucket
        for _ in range(5):
            lim.consume(1.0)
        assert lim.consume(1.0) is False

    def test_available_starts_at_capacity(self):
        from ipfs_datasets_py.mcp_server.mcp_p2p_transport import TokenBucketRateLimiter
        lim = TokenBucketRateLimiter(rate=10.0, capacity=20.0)
        assert abs(lim.available() - 20.0) < 0.1

    def test_reset_refills_to_capacity(self):
        from ipfs_datasets_py.mcp_server.mcp_p2p_transport import TokenBucketRateLimiter
        lim = TokenBucketRateLimiter(rate=10.0, capacity=10.0)
        lim.consume(10.0)
        lim.reset()
        assert abs(lim.available() - 10.0) < 0.1

    def test_invalid_rate_raises(self):
        from ipfs_datasets_py.mcp_server.mcp_p2p_transport import TokenBucketRateLimiter
        with pytest.raises(ValueError):
            TokenBucketRateLimiter(rate=0.0, capacity=10.0)

    def test_invalid_capacity_raises(self):
        from ipfs_datasets_py.mcp_server.mcp_p2p_transport import TokenBucketRateLimiter
        with pytest.raises(ValueError):
            TokenBucketRateLimiter(rate=1.0, capacity=0.0)

    def test_get_info_has_required_keys(self):
        from ipfs_datasets_py.mcp_server.mcp_p2p_transport import TokenBucketRateLimiter
        lim = TokenBucketRateLimiter(rate=5.0, capacity=10.0)
        info = lim.get_info()
        assert "rate" in info
        assert "capacity" in info
        assert "available" in info

    def test_thread_safe_concurrent_consume(self):
        from ipfs_datasets_py.mcp_server.mcp_p2p_transport import TokenBucketRateLimiter
        lim = TokenBucketRateLimiter(rate=1000.0, capacity=100.0)
        results = []

        def consume_one():
            results.append(lim.consume(1.0))

        threads = [threading.Thread(target=consume_one) for _ in range(80)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        # At most 100 should succeed (capacity = 100)
        assert sum(results) <= 100

    def test_p2p_session_config_makes_limiter(self):
        from ipfs_datasets_py.mcp_server.mcp_p2p_transport import P2PSessionConfig
        cfg = P2PSessionConfig(rate_limit=50.0, capacity=100.0)
        lim = cfg.make_rate_limiter()
        assert lim.rate == 50.0
        assert lim.capacity == 100.0


class TestLengthPrefixFramer:
    def test_encode_decode_roundtrip(self):
        from ipfs_datasets_py.mcp_server.mcp_p2p_transport import LengthPrefixFramer
        framer = LengthPrefixFramer()
        data = b"hello world"
        encoded = framer.encode(data)
        payload, remainder = framer.decode(encoded)
        assert payload == data
        assert remainder == b""

    def test_decode_with_remainder(self):
        from ipfs_datasets_py.mcp_server.mcp_p2p_transport import LengthPrefixFramer
        framer = LengthPrefixFramer()
        msg1 = framer.encode(b"first")
        msg2 = framer.encode(b"second")
        p1, r1 = framer.decode(msg1 + msg2)
        assert p1 == b"first"
        p2, r2 = framer.decode(r1)
        assert p2 == b"second"
        assert r2 == b""

    def test_empty_payload(self):
        from ipfs_datasets_py.mcp_server.mcp_p2p_transport import LengthPrefixFramer
        framer = LengthPrefixFramer()
        encoded = framer.encode(b"")
        payload, _ = framer.decode(encoded)
        assert payload == b""

    def test_incomplete_frame_raises(self):
        from ipfs_datasets_py.mcp_server.mcp_p2p_transport import LengthPrefixFramer
        framer = LengthPrefixFramer()
        import struct
        # Claim 100 bytes but provide only 5
        header = struct.pack(">I", 100)
        with pytest.raises(ValueError, match="Incomplete"):
            framer.decode(header + b"short")


class TestMCPMessage:
    def test_default_id_generated(self):
        from ipfs_datasets_py.mcp_server.mcp_p2p_transport import MCPMessage
        m = MCPMessage(method="tools/call")
        assert len(m.id) == 32  # uuid4().hex

    def test_to_dict_has_required_fields(self):
        from ipfs_datasets_py.mcp_server.mcp_p2p_transport import MCPMessage
        m = MCPMessage(method="tools/list", params={"a": 1})
        d = m.to_dict()
        assert d["method"] == "tools/list"
        assert d["params"] == {"a": 1}
        assert d["jsonrpc"] == "2.0"

    def test_roundtrip_via_bytes(self):
        from ipfs_datasets_py.mcp_server.mcp_p2p_transport import MCPMessage
        m = MCPMessage(method="tools/call", params={"name": "echo"}, id="req-1")
        m2 = MCPMessage.from_bytes(m.to_bytes())
        assert m2.method == m.method
        assert m2.params == m.params
        assert m2.id == m.id

    def test_from_bytes_missing_method_raises(self):
        from ipfs_datasets_py.mcp_server.mcp_p2p_transport import MCPMessage
        with pytest.raises(ValueError, match="missing 'method'"):
            MCPMessage.from_bytes(json.dumps({"jsonrpc": "2.0"}).encode())

    def test_constants(self):
        from ipfs_datasets_py.mcp_server.mcp_p2p_transport import (
            MCP_P2P_PROTOCOL_ID, MCP_P2P_PUBSUB_TOPICS,
        )
        assert MCP_P2P_PROTOCOL_ID == "/mcp+p2p/1.0.0"
        assert "interface_announce" in MCP_P2P_PUBSUB_TOPICS


# ===========================================================================
# AV106 — ComplianceChecker + custom rule add/remove
# ===========================================================================

class TestComplianceCheckerBuiltIn:
    def _checker(self):
        from ipfs_datasets_py.mcp_server.compliance_checker import make_default_checker
        return make_default_checker()

    def test_valid_intent_passes(self):
        checker = self._checker()
        report = checker.check({"tool": "read_file", "actor": "alice", "params": {}})
        assert report.passed is True
        assert report.failed_rules == []

    def test_invalid_tool_name_fails(self):
        checker = self._checker()
        report = checker.check({"tool": "Read-File!", "actor": "alice", "params": {}})
        assert "tool_name_convention" in report.failed_rules

    def test_missing_actor_fails(self):
        checker = self._checker()
        report = checker.check({"tool": "read_file", "params": {}})
        assert "intent_has_actor" in report.failed_rules

    def test_invalid_actor_fails(self):
        checker = self._checker()
        report = checker.check({"tool": "read_file", "actor": "!!bad!!", "params": {}})
        assert "actor_is_valid" in report.failed_rules

    def test_non_serializable_params_fails(self):
        checker = self._checker()
        report = checker.check({
            "tool": "read_file",
            "actor": "alice",
            "params": {"fn": lambda: None},  # not JSON-serialisable
        })
        assert "params_are_serializable" in report.failed_rules


class TestComplianceCheckerCustomRules:
    def test_add_custom_rule(self):
        from ipfs_datasets_py.mcp_server.compliance_checker import (
            ComplianceChecker, ComplianceRule, ComplianceResult,
        )
        checker = ComplianceChecker()
        rule = ComplianceRule(
            rule_id="custom_check",
            description="Actor must be 'bob'",
            check_fn=lambda i: ComplianceResult(
                rule_id="custom_check",
                passed=i.get("actor") == "bob",
                message="OK" if i.get("actor") == "bob" else "Not bob",
            ),
        )
        checker.add_rule(rule)
        assert len(checker) == 1
        report = checker.check({"tool": "read", "actor": "bob", "params": {}})
        assert report.passed is True

    def test_duplicate_rule_id_raises(self):
        from ipfs_datasets_py.mcp_server.compliance_checker import (
            ComplianceChecker, ComplianceRule, ComplianceResult,
        )
        checker = ComplianceChecker()
        rule = ComplianceRule(
            rule_id="dup",
            description="d",
            check_fn=lambda i: ComplianceResult(rule_id="dup", passed=True),
        )
        checker.add_rule(rule)
        with pytest.raises(ValueError, match="already registered"):
            checker.add_rule(rule)

    def test_remove_rule(self):
        from ipfs_datasets_py.mcp_server.compliance_checker import make_default_checker
        checker = make_default_checker()
        initial_count = len(checker)
        removed = checker.remove_rule("intent_has_actor")
        assert removed is True
        assert len(checker) == initial_count - 1

    def test_remove_nonexistent_returns_false(self):
        from ipfs_datasets_py.mcp_server.compliance_checker import make_default_checker
        checker = make_default_checker()
        assert checker.remove_rule("no_such_rule") is False

    def test_remove_non_removable_raises(self):
        from ipfs_datasets_py.mcp_server.compliance_checker import make_default_checker
        checker = make_default_checker()
        with pytest.raises(ValueError, match="not removable"):
            checker.remove_rule("tool_name_convention")

    def test_list_rules_structure(self):
        from ipfs_datasets_py.mcp_server.compliance_checker import make_default_checker
        checker = make_default_checker()
        rules = checker.list_rules()
        assert isinstance(rules, list)
        assert all("rule_id" in r and "description" in r for r in rules)

    def test_fail_fast_stops_early(self):
        from ipfs_datasets_py.mcp_server.compliance_checker import make_default_checker
        checker = make_default_checker(fail_fast=True)
        # Invalid tool → fail at first rule, other rules not evaluated
        report = checker.check({"tool": "INVALID!", "actor": "alice", "params": {}})
        assert "tool_name_convention" in report.failed_rules
        # With fail_fast, only 1 result (the first failure)
        assert len(report.results) == 1

    def test_compliance_result_to_dict(self):
        from ipfs_datasets_py.mcp_server.compliance_checker import ComplianceResult
        cr = ComplianceResult(rule_id="test", passed=True, message="OK")
        d = cr.to_dict()
        assert d == {"rule_id": "test", "passed": True, "message": "OK"}


# ===========================================================================
# AW107 — RiskScorer + score_and_gate
# ===========================================================================

class TestRiskLevelFromScore:
    def test_negligible(self):
        from ipfs_datasets_py.mcp_server.risk_scorer import RiskLevel
        assert RiskLevel.from_score(0.0) == RiskLevel.NEGLIGIBLE
        assert RiskLevel.from_score(0.19) == RiskLevel.NEGLIGIBLE

    def test_low(self):
        from ipfs_datasets_py.mcp_server.risk_scorer import RiskLevel
        assert RiskLevel.from_score(0.2) == RiskLevel.LOW
        assert RiskLevel.from_score(0.39) == RiskLevel.LOW

    def test_medium(self):
        from ipfs_datasets_py.mcp_server.risk_scorer import RiskLevel
        assert RiskLevel.from_score(0.4) == RiskLevel.MEDIUM

    def test_high(self):
        from ipfs_datasets_py.mcp_server.risk_scorer import RiskLevel
        assert RiskLevel.from_score(0.6) == RiskLevel.HIGH

    def test_critical(self):
        from ipfs_datasets_py.mcp_server.risk_scorer import RiskLevel
        assert RiskLevel.from_score(0.8) == RiskLevel.CRITICAL
        assert RiskLevel.from_score(1.0) == RiskLevel.CRITICAL


class TestRiskScorer:
    def test_default_score_is_below_max(self):
        from ipfs_datasets_py.mcp_server.risk_scorer import RiskScorer
        scorer = RiskScorer()
        a = scorer.score_intent(tool="read", actor="alice")
        assert 0.0 <= a.score <= 1.0
        assert a.is_acceptable is True

    def test_high_base_risk_tool(self):
        from ipfs_datasets_py.mcp_server.risk_scorer import RiskScorer, RiskScoringPolicy
        policy = RiskScoringPolicy(tool_risk_overrides={"delete": 0.9})
        scorer = RiskScorer(policy=policy)
        a = scorer.score_intent(tool="delete", actor="")
        assert a.tool_base_risk == 0.9
        assert a.level.value in ("high", "critical")

    def test_trust_reduces_score(self):
        from ipfs_datasets_py.mcp_server.risk_scorer import RiskScorer, RiskScoringPolicy
        policy = RiskScoringPolicy(
            default_risk=0.6,
            actor_trust_levels={"admin": 0.5},
        )
        scorer = RiskScorer(policy=policy)
        low = scorer.score_intent(tool="write", actor="admin")
        high = scorer.score_intent(tool="write", actor="unknown")
        assert low.score < high.score

    def test_complexity_penalty(self):
        from ipfs_datasets_py.mcp_server.risk_scorer import RiskScorer
        scorer = RiskScorer()
        no_params = scorer.score_intent(tool="write", actor="alice", params={})
        many_params = scorer.score_intent(
            tool="write", actor="alice",
            params={f"k{i}": i for i in range(10)},
        )
        assert many_params.score > no_params.score

    def test_score_and_gate_allows_low_risk(self):
        from ipfs_datasets_py.mcp_server.risk_scorer import RiskScorer
        scorer = RiskScorer()
        a = scorer.score_and_gate(tool="read", actor="alice")
        assert a.is_acceptable is True

    def test_score_and_gate_raises_on_high_risk(self):
        from ipfs_datasets_py.mcp_server.risk_scorer import (
            RiskScorer, RiskScoringPolicy, RiskGateError,
        )
        policy = RiskScoringPolicy(
            tool_risk_overrides={"danger": 0.99},
            max_acceptable_risk=0.75,
        )
        scorer = RiskScorer(policy=policy)
        with pytest.raises(RiskGateError) as exc_info:
            scorer.score_and_gate(tool="danger", actor="")
        assert exc_info.value.assessment.tool == "danger"

    def test_get_info_has_keys(self):
        from ipfs_datasets_py.mcp_server.risk_scorer import RiskScorer
        info = RiskScorer().get_info()
        assert "default_risk" in info
        assert "max_acceptable_risk" in info

    def test_assessment_to_dict(self):
        from ipfs_datasets_py.mcp_server.risk_scorer import RiskScorer
        a = RiskScorer().score_intent("read", "alice")
        d = a.to_dict()
        assert "score" in d
        assert "level" in d
        assert "is_acceptable" in d


# ===========================================================================
# AX108 — policy_audit_log: sink + JSONL + stats
# ===========================================================================

class TestPolicyAuditLogSink:
    def test_sink_called_on_record(self):
        from ipfs_datasets_py.mcp_server.policy_audit_log import PolicyAuditLog
        received = []
        log = PolicyAuditLog(sink=received.append)
        log.record(
            policy_cid="bafy-p",
            intent_cid="bafy-i",
            actor="alice",
            decision="allow",
            tool="read",
        )
        assert len(received) == 1
        assert received[0].decision == "allow"

    def test_sink_not_called_when_disabled(self):
        from ipfs_datasets_py.mcp_server.policy_audit_log import PolicyAuditLog
        received = []
        log = PolicyAuditLog(enabled=False, sink=received.append)
        log.record(
            policy_cid="bafy-p",
            intent_cid="bafy-i",
            actor="alice",
            decision="allow",
            tool="read",
        )
        assert len(received) == 0

    def test_sink_exception_does_not_crash(self):
        from ipfs_datasets_py.mcp_server.policy_audit_log import PolicyAuditLog

        def bad_sink(entry):
            raise RuntimeError("sink error")

        log = PolicyAuditLog(sink=bad_sink)
        # Should not raise
        log.record(
            policy_cid="bafy-p",
            intent_cid="bafy-i",
            actor="alice",
            decision="allow",
        )


class TestPolicyAuditLogJSONL:
    def test_jsonl_file_written(self, tmp_path):
        from ipfs_datasets_py.mcp_server.policy_audit_log import PolicyAuditLog
        log_file = tmp_path / "audit.jsonl"
        log = PolicyAuditLog(log_path=str(log_file))
        log.record(
            policy_cid="bafy-p",
            intent_cid="bafy-i",
            actor="alice",
            decision="allow",
            tool="read",
        )
        assert log_file.exists()
        lines = log_file.read_text().strip().splitlines()
        assert len(lines) == 1
        obj = json.loads(lines[0])
        assert obj["decision"] == "allow"
        assert obj["actor"] == "alice"

    def test_jsonl_appends(self, tmp_path):
        from ipfs_datasets_py.mcp_server.policy_audit_log import PolicyAuditLog
        log_file = tmp_path / "audit.jsonl"
        for i in range(3):
            log = PolicyAuditLog(log_path=str(log_file))
            log.record(policy_cid="p", intent_cid=f"i{i}", decision="allow")
        lines = log_file.read_text().strip().splitlines()
        assert len(lines) == 3


class TestPolicyAuditLogStats:
    def test_stats_has_required_keys(self):
        from ipfs_datasets_py.mcp_server.policy_audit_log import PolicyAuditLog
        log = PolicyAuditLog()
        log.record(policy_cid="p", intent_cid="i", actor="alice", decision="allow", tool="read")
        log.record(policy_cid="p", intent_cid="i2", actor="bob", decision="deny", tool="delete")
        stats = log.stats()
        assert "total_recorded" in stats
        # stats() uses 'by_decision' key for the per-decision breakdown
        assert "by_decision" in stats
        assert stats["by_decision"].get("allow", 0) >= 1
        assert stats["by_decision"].get("deny", 0) >= 1

    def test_clear_removes_buffer_entries(self):
        from ipfs_datasets_py.mcp_server.policy_audit_log import PolicyAuditLog
        log = PolicyAuditLog()
        log.record(policy_cid="p", intent_cid="i", decision="allow")
        entries_before = len(log.all_entries())
        log.clear()
        # clear() empties the in-memory buffer; total_recorded() is a method
        assert len(log.all_entries()) == 0
        assert entries_before > 0

    def test_ring_buffer_max_entries(self):
        from ipfs_datasets_py.mcp_server.policy_audit_log import PolicyAuditLog
        log = PolicyAuditLog(max_entries=5)
        for i in range(10):
            log.record(policy_cid="p", intent_cid=f"i{i}", decision="allow")
        entries = log.all_entries()
        assert len(entries) <= 5


# ===========================================================================
# AY109 — did_key_manager: rotate_key + reload + info
# ===========================================================================

def _ucan_available() -> bool:
    try:
        import ucan  # noqa: F401
        return True
    except ImportError:
        return False


_skip_no_ucan = pytest.mark.skipif(
    not _ucan_available(),
    reason="py-ucan not installed",
)


class TestDIDKeyManagerExtra:
    @_skip_no_ucan
    def test_rotate_key_returns_new_did(self, tmp_path):
        from ipfs_datasets_py.mcp_server.did_key_manager import DIDKeyManager
        mgr = DIDKeyManager(key_file=tmp_path / "did_key.json")
        old_did = mgr.did
        new_did = mgr.rotate_key()
        assert new_did != old_did

    @_skip_no_ucan
    def test_rotate_key_persists(self, tmp_path):
        from ipfs_datasets_py.mcp_server.did_key_manager import DIDKeyManager
        key_file = tmp_path / "did_key.json"
        mgr = DIDKeyManager(key_file=key_file)
        new_did = mgr.rotate_key()
        # Reload
        mgr2 = DIDKeyManager(key_file=key_file)
        assert mgr2.did == new_did

    def test_info_dict_has_required_keys(self, tmp_path):
        from ipfs_datasets_py.mcp_server.did_key_manager import DIDKeyManager
        mgr = DIDKeyManager(key_file=tmp_path / "did_key.json")
        info = mgr.info()
        assert "did" in info
        assert "ucan_available" in info
        assert "key_file" in info

    @_skip_no_ucan
    def test_export_secret_b64_stable(self, tmp_path):
        from ipfs_datasets_py.mcp_server.did_key_manager import DIDKeyManager
        mgr = DIDKeyManager(key_file=tmp_path / "did_key.json")
        s1 = mgr.export_secret_b64()
        s2 = mgr.export_secret_b64()
        assert s1 == s2
        assert len(s1) > 0


# ===========================================================================
# AZ110 — secrets_vault: list/iter/delete + encrypted round-trip
# ===========================================================================

class TestSecretsVaultExtra:
    @_skip_no_ucan
    def test_list_names_returns_names(self, tmp_path):
        from ipfs_datasets_py.mcp_server.secrets_vault import SecretsVault
        v = SecretsVault(vault_file=tmp_path / "vault.json")
        v.set("OPENAI_API_KEY", "sk-test")
        v.set("PINECONE_KEY", "pc-test")
        names = v.list_names()
        assert "OPENAI_API_KEY" in names
        assert "PINECONE_KEY" in names

    @_skip_no_ucan
    def test_iter_over_names(self, tmp_path):
        from ipfs_datasets_py.mcp_server.secrets_vault import SecretsVault
        v = SecretsVault(vault_file=tmp_path / "vault.json")
        v.set("K1", "v1")
        v.set("K2", "v2")
        names = list(v)
        assert "K1" in names
        assert "K2" in names

    @_skip_no_ucan
    def test_delete_removes_secret(self, tmp_path):
        from ipfs_datasets_py.mcp_server.secrets_vault import SecretsVault
        v = SecretsVault(vault_file=tmp_path / "vault.json")
        v.set("K1", "v1")
        v.delete("K1")
        assert v.get("K1") is None
        assert "K1" not in v

    @_skip_no_ucan
    def test_len_after_operations(self, tmp_path):
        from ipfs_datasets_py.mcp_server.secrets_vault import SecretsVault
        v = SecretsVault(vault_file=tmp_path / "vault.json")
        assert len(v) == 0
        v.set("A", "1")
        v.set("B", "2")
        assert len(v) == 2
        v.delete("A")
        assert len(v) == 1

    @_skip_no_ucan
    def test_encrypted_roundtrip(self, tmp_path):
        from ipfs_datasets_py.mcp_server.secrets_vault import SecretsVault
        v = SecretsVault(vault_file=tmp_path / "vault.json")
        v.set("SECRET", "super-secret-value")
        # On-disk the value must NOT appear as plaintext
        raw = (tmp_path / "vault.json").read_text()
        assert "super-secret-value" not in raw
        # Reload vault and decrypt
        v2 = SecretsVault(vault_file=tmp_path / "vault.json")
        assert v2.get("SECRET") == "super-secret-value"

    def test_info_has_required_keys(self, tmp_path):
        from ipfs_datasets_py.mcp_server.secrets_vault import SecretsVault
        v = SecretsVault(vault_file=tmp_path / "vault.json")
        info = v.info()
        assert "vault_file" in info
        assert "secret_count" in info
