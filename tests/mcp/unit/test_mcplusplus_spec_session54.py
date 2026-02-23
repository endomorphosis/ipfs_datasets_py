"""Session 54: Tests for mcp_p2p_transport.py and dispatch_pipeline.py."""
import json
import struct
import pytest
from unittest.mock import MagicMock, patch


# ── mcp_p2p_transport ────────────────────────────────────────────────────────

from ipfs_datasets_py.mcp_server.mcp_p2p_transport import (
    MCP_P2P_PROTOCOL_ID,
    MCP_P2P_SESSION_PROTOCOL_ID,
    MCP_P2P_EVENTS_PROTOCOL_ID,
    DEFAULT_MAX_FRAME_BYTES,
    MIN_MAX_FRAME_BYTES,
    MCP_P2P_PUBSUB_TOPICS,
    P2PSessionState,
    MCPMessage,
    LengthPrefixFramer,
    FrameTooBigError,
    P2PSessionConfig,
    TokenBucketRateLimiter,
)


class TestProtocolConstants:
    def test_protocol_id_value(self):
        assert MCP_P2P_PROTOCOL_ID == "/mcp+p2p/1.0.0"

    def test_session_protocol_id(self):
        assert "mcp+p2p" in MCP_P2P_SESSION_PROTOCOL_ID

    def test_events_protocol_id(self):
        assert "mcp+p2p" in MCP_P2P_EVENTS_PROTOCOL_ID

    def test_default_max_frame_bytes(self):
        assert DEFAULT_MAX_FRAME_BYTES == 16 * 1024 * 1024

    def test_min_max_frame_bytes(self):
        assert MIN_MAX_FRAME_BYTES == 1024 * 1024

    def test_pubsub_topics_keys(self):
        assert "interface_announce" in MCP_P2P_PUBSUB_TOPICS
        assert "receipt_disseminate" in MCP_P2P_PUBSUB_TOPICS
        assert "decision_disseminate" in MCP_P2P_PUBSUB_TOPICS
        assert "scheduling_signal" in MCP_P2P_PUBSUB_TOPICS

    def test_pubsub_topics_mcp_p2p_prefix(self):
        for v in MCP_P2P_PUBSUB_TOPICS.values():
            assert v.startswith("/mcp+p2p/topics/")


class TestP2PSessionState:
    def test_enum_values(self):
        states = {s.value for s in P2PSessionState}
        assert states == {"disconnected", "connecting", "handshaking", "active", "closing", "closed"}

    def test_active_state(self):
        assert P2PSessionState.ACTIVE.value == "active"


class TestMCPMessage:
    def test_to_bytes_is_json(self):
        msg = MCPMessage(payload={"jsonrpc": "2.0", "method": "test", "id": 1})
        data = msg.to_bytes()
        parsed = json.loads(data)
        assert parsed["method"] == "test"

    def test_from_bytes_roundtrip(self):
        payload = {"jsonrpc": "2.0", "method": "tools/list", "id": 42}
        msg = MCPMessage(payload=payload, message_id=42)
        data = msg.to_bytes()
        msg2 = MCPMessage.from_bytes(data, message_id=42)
        assert msg2.payload == payload
        assert msg2.message_id == 42

    def test_from_bytes_invalid_utf8(self):
        with pytest.raises(ValueError, match="invalid UTF-8"):
            MCPMessage.from_bytes(b"\xff\xfe")

    def test_from_bytes_invalid_json(self):
        with pytest.raises(ValueError, match="invalid JSON"):
            MCPMessage.from_bytes(b"not-json")

    def test_from_bytes_non_object(self):
        with pytest.raises(ValueError, match="expected JSON object"):
            MCPMessage.from_bytes(b"[1,2,3]")

    def test_is_request(self):
        msg = MCPMessage(payload={"jsonrpc": "2.0", "method": "foo", "id": 1})
        assert msg.is_request()
        assert not msg.is_notification()
        assert not msg.is_response()

    def test_is_notification(self):
        msg = MCPMessage(payload={"jsonrpc": "2.0", "method": "foo"})
        assert msg.is_notification()
        assert not msg.is_request()

    def test_is_response(self):
        msg = MCPMessage(payload={"jsonrpc": "2.0", "id": 1, "result": {}})
        assert msg.is_response()
        assert not msg.is_request()

    def test_error_response_is_response(self):
        msg = MCPMessage(payload={"jsonrpc": "2.0", "id": 1, "error": {"code": -32600}})
        assert msg.is_response()


class TestLengthPrefixFramer:
    def test_encode_produces_header_plus_body(self):
        framer = LengthPrefixFramer()
        msg = MCPMessage(payload={"jsonrpc": "2.0", "method": "test", "id": 1})
        frame = framer.encode(msg)
        assert len(frame) == framer.HEADER_SIZE + len(msg.to_bytes())

    def test_header_is_big_endian_length(self):
        framer = LengthPrefixFramer()
        msg = MCPMessage(payload={"x": "y"})
        frame = framer.encode(msg)
        (declared_len,) = struct.unpack("!I", frame[:4])
        assert declared_len == len(msg.to_bytes())

    def test_decode_roundtrip(self):
        framer = LengthPrefixFramer()
        payload = {"jsonrpc": "2.0", "method": "ping", "id": 99}
        msg = MCPMessage(payload=payload)
        frame = framer.encode(msg)
        decoded = framer.decode(frame)
        assert decoded.payload == payload

    def test_decode_header_returns_int(self):
        framer = LengthPrefixFramer()
        header = struct.pack("!I", 42)
        assert framer.decode_header(header) == 42

    def test_decode_header_wrong_length(self):
        framer = LengthPrefixFramer()
        with pytest.raises(ValueError):
            framer.decode_header(b"\x00\x00")

    def test_decode_body(self):
        framer = LengthPrefixFramer()
        payload = {"z": 1}
        body = json.dumps(payload).encode("utf-8")
        msg = framer.decode_body(body)
        assert msg.payload == payload

    def test_encode_too_big_raises(self):
        framer = LengthPrefixFramer(max_frame_bytes=MIN_MAX_FRAME_BYTES)
        big_payload = {"x": "a" * (MIN_MAX_FRAME_BYTES + 1)}
        msg = MCPMessage(payload=big_payload)
        with pytest.raises(FrameTooBigError):
            framer.encode(msg)

    def test_decode_header_too_big_raises(self):
        framer = LengthPrefixFramer(max_frame_bytes=MIN_MAX_FRAME_BYTES)
        # Declare body size = 2 * limit
        too_big = MIN_MAX_FRAME_BYTES * 2
        header = struct.pack("!I", too_big)
        with pytest.raises(FrameTooBigError):
            framer.decode_header(header)

    def test_decode_short_frame_raises(self):
        framer = LengthPrefixFramer()
        with pytest.raises(ValueError):
            framer.decode(b"\x00\x00")

    def test_decode_length_mismatch_raises(self):
        framer = LengthPrefixFramer()
        # Build a frame with wrong declared length
        body = b'{"a":1}'
        wrong_header = struct.pack("!I", len(body) + 10)
        with pytest.raises(ValueError, match="length mismatch"):
            framer.decode(wrong_header + body)

    def test_max_frame_bytes_below_min_raises(self):
        with pytest.raises(ValueError):
            LengthPrefixFramer(max_frame_bytes=100)


class TestP2PSessionConfig:
    def test_defaults(self):
        cfg = P2PSessionConfig()
        assert cfg.protocol_id == MCP_P2P_PROTOCOL_ID
        assert cfg.max_frame_bytes == DEFAULT_MAX_FRAME_BYTES
        assert cfg.peer_id is None
        assert cfg.multiaddrs == []
        assert not cfg.enable_pubsub
        assert cfg.pubsub_topics == []

    def test_custom_values(self):
        cfg = P2PSessionConfig(
            peer_id="Qmfoo",
            multiaddrs=["/ip4/127.0.0.1/tcp/4001"],
            enable_pubsub=True,
        )
        assert cfg.peer_id == "Qmfoo"
        assert cfg.enable_pubsub

    def test_make_framer(self):
        cfg = P2PSessionConfig()
        framer = cfg.make_framer()
        assert isinstance(framer, LengthPrefixFramer)
        assert framer.max_frame_bytes == DEFAULT_MAX_FRAME_BYTES

    def test_to_dict(self):
        cfg = P2PSessionConfig(peer_id="Qmbar")
        d = cfg.to_dict()
        assert d["protocol_id"] == MCP_P2P_PROTOCOL_ID
        assert d["peer_id"] == "Qmbar"
        assert "max_frame_bytes" in d


class TestTokenBucketRateLimiter:
    def test_initial_full(self):
        rl = TokenBucketRateLimiter(capacity=10)
        assert rl.tokens == 10

    def test_consume_success(self):
        rl = TokenBucketRateLimiter(capacity=10, refill_rate=0)
        assert rl.consume(1) is True
        # tokens decrease (then get refill_rate=0 added back)
        assert rl.tokens < 10

    def test_consume_depletes_and_denies(self):
        rl = TokenBucketRateLimiter(capacity=5, refill_rate=0)
        # Drain all tokens
        for _ in range(5):
            rl.consume(1)
        assert rl.consume(1) is False

    def test_refill(self):
        rl = TokenBucketRateLimiter(capacity=10, refill_rate=5)
        # Drain to 0
        rl._tokens = 0
        # consume() will refill by refill_rate first
        result = rl.consume(3)
        assert result is True

    def test_reset(self):
        rl = TokenBucketRateLimiter(capacity=10, refill_rate=0)
        rl._tokens = 0
        rl.reset()
        assert rl.tokens == 10

    def test_invalid_capacity(self):
        with pytest.raises(ValueError):
            TokenBucketRateLimiter(capacity=0)

    def test_invalid_refill_rate(self):
        with pytest.raises(ValueError):
            TokenBucketRateLimiter(refill_rate=-1)

    def test_consume_count_zero_raises(self):
        rl = TokenBucketRateLimiter()
        with pytest.raises(ValueError):
            rl.consume(0)


# ── dispatch_pipeline ────────────────────────────────────────────────────────

from ipfs_datasets_py.mcp_server.dispatch_pipeline import (
    DispatchPipeline,
    PipelineConfig,
    PipelineResult,
    PipelineStage,
    StageOutcome,
    make_default_pipeline,
    make_full_pipeline,
    PipelineIntent,
)
from ipfs_datasets_py.mcp_server.cid_artifacts import ReceiptObject


def _make_intent(tool="test_tool", actor="alice", params=None):
    return PipelineIntent(tool_name=tool, actor=actor, params=params or {})


class TestPipelineConstants:
    def test_stage_enum_values(self):
        assert PipelineStage.COMPLIANCE.value == "compliance"
        assert PipelineStage.RISK.value == "risk"
        assert PipelineStage.DELEGATION.value == "delegation"
        assert PipelineStage.POLICY.value == "policy"
        assert PipelineStage.NL_UCAN_GATE.value == "nl_ucan_gate"
        assert PipelineStage.PASS.value == "pass"


class TestStageOutcome:
    def test_fields(self):
        o = StageOutcome(stage=PipelineStage.COMPLIANCE, passed=True, reason="ok")
        assert o.stage == PipelineStage.COMPLIANCE
        assert o.passed is True
        assert o.reason == "ok"

    def test_default_metadata(self):
        o = StageOutcome(stage=PipelineStage.RISK, passed=False)
        assert o.metadata == {}


class TestPipelineResult:
    def test_verdict_allow(self):
        intent = _make_intent()
        result = PipelineResult(allowed=True, stage_outcomes=[], blocking_stage=None, intent=intent)
        assert result.verdict == "allow"

    def test_verdict_deny(self):
        intent = _make_intent()
        result = PipelineResult(
            allowed=False,
            stage_outcomes=[],
            blocking_stage=PipelineStage.COMPLIANCE,
            intent=intent,
        )
        assert result.verdict == "deny"

    def test_to_dict(self):
        intent = _make_intent()
        outcome = StageOutcome(stage=PipelineStage.COMPLIANCE, passed=True, reason="ok")
        result = PipelineResult(allowed=True, stage_outcomes=[outcome], blocking_stage=None, intent=intent)
        d = result.to_dict()
        assert d["allowed"] is True
        assert d["verdict"] == "allow"
        assert d["blocking_stage"] is None
        assert len(d["stages"]) == 1

    def test_to_dict_blocking(self):
        intent = _make_intent()
        outcome = StageOutcome(stage=PipelineStage.RISK, passed=False, reason="too risky")
        result = PipelineResult(
            allowed=False,
            stage_outcomes=[outcome],
            blocking_stage=PipelineStage.RISK,
            intent=intent,
        )
        d = result.to_dict()
        assert d["blocking_stage"] == "risk"


class TestDefaultPipeline:
    def test_all_stages_disabled_by_default(self):
        cfg = PipelineConfig()
        assert not cfg.enable_compliance
        assert not cfg.enable_risk
        assert not cfg.enable_delegation
        assert not cfg.enable_policy
        assert not cfg.enable_nl_ucan_gate

    def test_make_default_pipeline_returns_pipeline(self):
        p = make_default_pipeline()
        assert isinstance(p, DispatchPipeline)

    def test_default_pipeline_allows_everything(self):
        p = make_default_pipeline()
        intent = _make_intent()
        result = p.check(intent)
        assert result.allowed is True
        assert result.blocking_stage is None

    def test_default_pipeline_pass_stage_appended(self):
        p = make_default_pipeline()
        result = p.check(_make_intent())
        stages = [o.stage for o in result.stage_outcomes]
        assert PipelineStage.PASS in stages

    def test_make_full_pipeline_enables_all_stages(self):
        p = make_full_pipeline()
        assert p.config.enable_compliance
        assert p.config.enable_risk
        assert p.config.enable_delegation
        assert p.config.enable_policy
        assert p.config.enable_nl_ucan_gate


class TestComplianceStage:
    def test_compliance_passes_valid_intent(self):
        from ipfs_datasets_py.mcp_server.compliance_checker import make_default_compliance_checker
        cfg = PipelineConfig(enable_compliance=True, compliance_checker=make_default_compliance_checker())
        p = DispatchPipeline(config=cfg)
        # valid tool name, valid actor
        result = p.check(_make_intent(tool="valid_tool", actor="alice"))
        assert result.allowed is True

    def test_compliance_blocks_invalid_tool_name(self):
        from ipfs_datasets_py.mcp_server.compliance_checker import make_default_compliance_checker
        cfg = PipelineConfig(enable_compliance=True, compliance_checker=make_default_compliance_checker())
        p = DispatchPipeline(config=cfg)
        # tool name starts with uppercase → violates convention
        result = p.check(_make_intent(tool="InvalidTool", actor="alice"))
        assert result.allowed is False
        assert result.blocking_stage == PipelineStage.COMPLIANCE

    def test_compliance_blocks_actor_with_spaces(self):
        from ipfs_datasets_py.mcp_server.compliance_checker import make_default_compliance_checker
        cfg = PipelineConfig(enable_compliance=True, compliance_checker=make_default_compliance_checker())
        p = DispatchPipeline(config=cfg)
        result = p.check(_make_intent(tool="good_tool", actor="bad actor"))
        assert result.allowed is False

    def test_compliance_stage_in_outcomes(self):
        from ipfs_datasets_py.mcp_server.compliance_checker import make_default_compliance_checker
        cfg = PipelineConfig(enable_compliance=True, compliance_checker=make_default_compliance_checker())
        p = DispatchPipeline(config=cfg)
        result = p.check(_make_intent())
        stages = [o.stage for o in result.stage_outcomes]
        assert PipelineStage.COMPLIANCE in stages


class TestRiskStage:
    def test_risk_passes_safe_tool(self):
        from ipfs_datasets_py.mcp_server.risk_scorer import RiskScorer, make_default_risk_policy
        cfg = PipelineConfig(
            enable_risk=True,
            risk_scorer=RiskScorer(),
            risk_policy=make_default_risk_policy(),
        )
        p = DispatchPipeline(config=cfg)
        # default risk is 0.3, trust is 1.0, max_acceptable is 0.75 → passes
        result = p.check(_make_intent(tool="safe_tool", actor="trusted_actor"))
        assert result.allowed is True

    def test_risk_blocks_high_risk_tool(self):
        from ipfs_datasets_py.mcp_server.risk_scorer import RiskScorer, RiskScoringPolicy
        policy = RiskScoringPolicy(
            tool_risk_overrides={"dangerous_tool": 0.9},
            default_risk=0.3,
            max_acceptable_risk=0.5,
        )
        cfg = PipelineConfig(
            enable_risk=True,
            risk_scorer=RiskScorer(),
            risk_policy=policy,
        )
        p = DispatchPipeline(config=cfg)
        result = p.check(_make_intent(tool="dangerous_tool", actor="alice"))
        assert result.allowed is False
        assert result.blocking_stage == PipelineStage.RISK

    def test_risk_stage_metadata_has_score(self):
        from ipfs_datasets_py.mcp_server.risk_scorer import RiskScorer, make_default_risk_policy
        cfg = PipelineConfig(
            enable_risk=True,
            risk_scorer=RiskScorer(),
            risk_policy=make_default_risk_policy(),
        )
        p = DispatchPipeline(config=cfg)
        result = p.check(_make_intent())
        risk_outcome = next(o for o in result.stage_outcomes if o.stage == PipelineStage.RISK)
        assert "score" in risk_outcome.metadata


class TestDelegationStage:
    def test_delegation_skips_when_no_leaf_cid(self):
        cfg = PipelineConfig(enable_delegation=True, delegation_leaf_cid=None)
        p = DispatchPipeline(config=cfg)
        result = p.check(_make_intent())
        del_outcome = next(o for o in result.stage_outcomes if o.stage == PipelineStage.DELEGATION)
        assert del_outcome.passed is True
        assert "no delegation_leaf_cid" in del_outcome.reason

    def test_delegation_blocks_when_chain_empty(self):
        from ipfs_datasets_py.mcp_server.ucan_delegation import DelegationEvaluator
        evaluator = DelegationEvaluator()  # empty chain
        cfg = PipelineConfig(
            enable_delegation=True,
            delegation_evaluator=evaluator,
            delegation_leaf_cid="cid-leaf-does-not-exist",
        )
        p = DispatchPipeline(config=cfg)
        result = p.check(_make_intent(tool="some_tool", actor="alice"))
        assert result.allowed is False
        assert result.blocking_stage == PipelineStage.DELEGATION

    def test_delegation_allows_valid_chain(self):
        from ipfs_datasets_py.mcp_server.ucan_delegation import (
            DelegationEvaluator, Delegation, Capability,
        )
        evaluator = DelegationEvaluator()
        cap = Capability(resource="some_tool", ability="some_tool")
        deleg = Delegation(
            cid="leaf-cid-1",
            issuer="root",
            audience="alice",
            capabilities=[cap],
            expiry=9999999999,
        )
        evaluator.add(deleg)
        cfg = PipelineConfig(
            enable_delegation=True,
            delegation_evaluator=evaluator,
            delegation_leaf_cid="leaf-cid-1",
        )
        p = DispatchPipeline(config=cfg)
        result = p.check(_make_intent(tool="some_tool", actor="alice"))
        assert result.allowed is True


class TestPolicyStage:
    def test_policy_skips_when_none(self):
        cfg = PipelineConfig(enable_policy=True, policy_object=None)
        p = DispatchPipeline(config=cfg)
        result = p.check(_make_intent())
        pol_outcome = next(o for o in result.stage_outcomes if o.stage == PipelineStage.POLICY)
        assert pol_outcome.passed is True
        assert "no policy configured" in pol_outcome.reason

    def test_policy_allows_matching_permission(self):
        from ipfs_datasets_py.mcp_server.temporal_policy import (
            PolicyEvaluator, make_simple_permission_policy,
        )
        policy = make_simple_permission_policy(actor="alice", action="test_tool")
        cfg = PipelineConfig(
            enable_policy=True,
            policy_evaluator=PolicyEvaluator(),
            policy_object=policy,
        )
        p = DispatchPipeline(config=cfg)
        result = p.check(_make_intent(tool="test_tool", actor="alice"))
        assert result.allowed is True

    def test_policy_denies_prohibition(self):
        from ipfs_datasets_py.mcp_server.temporal_policy import (
            PolicyEvaluator, PolicyObject, PolicyClause,
        )
        clause = PolicyClause(clause_type="prohibition", actor="alice", action="bad_tool")
        policy = PolicyObject(clauses=[clause])
        cfg = PipelineConfig(
            enable_policy=True,
            policy_evaluator=PolicyEvaluator(),
            policy_object=policy,
        )
        p = DispatchPipeline(config=cfg)
        result = p.check(_make_intent(tool="bad_tool", actor="alice"))
        assert result.allowed is False
        assert result.blocking_stage == PipelineStage.POLICY


class TestNLUCANGateStage:
    def test_nl_ucan_gate_open_by_default(self):
        from ipfs_datasets_py.mcp_server.nl_ucan_policy import UCANPolicyGate
        cfg = PipelineConfig(
            enable_nl_ucan_gate=True,
            nl_ucan_gate=UCANPolicyGate(),
        )
        p = DispatchPipeline(config=cfg)
        result = p.check(_make_intent())
        assert result.allowed is True


class TestRecordExecution:
    def test_returns_receipt(self):
        p = make_default_pipeline()
        intent = _make_intent()
        receipt = p.record_execution(intent, {"status": "ok"})
        assert isinstance(receipt, ReceiptObject)
        assert receipt.intent_cid == intent.intent_cid
        # ReceiptObject has output_cid and decision_cid, not status
        assert receipt.output_cid.startswith("bafy")

    def test_error_path(self):
        p = make_default_pipeline()
        intent = _make_intent()
        receipt = p.record_execution(intent, None, error=ValueError("fail"))
        # On error the decision_cid contains 'error'
        assert "error" in receipt.decision_cid or receipt.decision_cid.startswith("bafy-mock-pipeline")

    def test_with_event_dag(self):
        from ipfs_datasets_py.mcp_server.event_dag import EventDAG
        dag = EventDAG()
        p = make_default_pipeline()
        p.attach_event_dag(dag)
        intent = _make_intent()
        receipt = p.record_execution(intent, {"data": "x"})
        assert receipt.intent_cid == intent.intent_cid
        # EventDAG should have at least one node
        assert len(dag.frontier()) >= 1

    def test_dag_error_does_not_fail_receipt(self):
        bad_dag = MagicMock()
        bad_dag.append.side_effect = RuntimeError("dag exploded")
        p = make_default_pipeline()
        p._event_dag = bad_dag
        intent = _make_intent()
        # Should not raise
        receipt = p.record_execution(intent, {"x": 1})
        assert receipt.intent_cid == intent.intent_cid


class TestMultiStageIntegration:
    def test_compliance_plus_risk_both_pass(self):
        from ipfs_datasets_py.mcp_server.compliance_checker import make_default_compliance_checker
        from ipfs_datasets_py.mcp_server.risk_scorer import RiskScorer, make_default_risk_policy
        p = DispatchPipeline(
            config=PipelineConfig(
                enable_compliance=True,
                enable_risk=True,
                compliance_checker=make_default_compliance_checker(),
                risk_scorer=RiskScorer(),
                risk_policy=make_default_risk_policy(),
            )
        )
        result = p.check(_make_intent(tool="safe_tool", actor="bob"))
        assert result.allowed is True
        stages = [o.stage for o in result.stage_outcomes]
        assert PipelineStage.COMPLIANCE in stages
        assert PipelineStage.RISK in stages

    def test_compliance_short_circuits_before_risk(self):
        from ipfs_datasets_py.mcp_server.compliance_checker import make_default_compliance_checker
        from ipfs_datasets_py.mcp_server.risk_scorer import RiskScorer, make_default_risk_policy
        p = DispatchPipeline(
            config=PipelineConfig(
                enable_compliance=True,
                enable_risk=True,
                compliance_checker=make_default_compliance_checker(),
                risk_scorer=RiskScorer(),
                risk_policy=make_default_risk_policy(),
            )
        )
        # BAD tool name → compliance fails, risk never runs
        result = p.check(_make_intent(tool="BadTool", actor="alice"))
        assert result.allowed is False
        assert result.blocking_stage == PipelineStage.COMPLIANCE
        stages = [o.stage for o in result.stage_outcomes]
        assert PipelineStage.RISK not in stages


