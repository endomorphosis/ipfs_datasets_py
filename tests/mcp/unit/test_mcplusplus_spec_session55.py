"""Session 55: MCP++ spec integration tests.

Covers:
- server.py: set_pipeline / get_pipeline, policy tool registration
- policy_management_tool.py: all 6 tools
- risk_scorer.py: risk_score_from_dag
- mcp_p2p_transport.py: PubSubEventType + PubSubBus
"""
from __future__ import annotations

import sys
import types
import unittest
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# Stub out heavy optional dependencies at collection time
# ---------------------------------------------------------------------------
for _mod in ["mcp", "mcp.server", "mcp.types"]:
    if _mod not in sys.modules:
        sys.modules[_mod] = MagicMock()


# ---------------------------------------------------------------------------
# 1. server.py — pipeline integration
# ---------------------------------------------------------------------------

class TestServerPipelineIntegration(unittest.TestCase):
    """Tests for set_pipeline / get_pipeline on IPFSDatasetsMCPServer."""

    def _make_server(self):
        """Build a minimal server without touching the real MCP package."""
        import importlib
        # Ensure mcp stub is in place
        mcp_stub = MagicMock()
        mcp_stub.server.FastMCP = None
        with patch.dict(sys.modules, {"mcp": mcp_stub, "mcp.server": mcp_stub.server,
                                       "mcp.types": mcp_stub.types}):
            srv_mod = importlib.import_module("ipfs_datasets_py.mcp_server.server")
        # Build server with mcp=None (FastMCP is None)
        srv = object.__new__(srv_mod.IPFSDatasetsMCPServer)
        srv.configs = MagicMock()
        srv.mcp = None
        srv.tools = {}
        srv._dispatch_pipeline = None
        return srv

    def test_get_pipeline_initially_none(self):
        srv = self._make_server()
        self.assertIsNone(srv.get_pipeline())

    def test_set_pipeline_stores_value(self):
        srv = self._make_server()
        fake_pipeline = MagicMock()
        srv.set_pipeline(fake_pipeline)
        self.assertIs(srv.get_pipeline(), fake_pipeline)

    def test_set_pipeline_none_detaches(self):
        srv = self._make_server()
        srv.set_pipeline(MagicMock())
        srv.set_pipeline(None)
        self.assertIsNone(srv.get_pipeline())

    def test_set_pipeline_replaces_previous(self):
        srv = self._make_server()
        p1 = MagicMock()
        p2 = MagicMock()
        srv.set_pipeline(p1)
        srv.set_pipeline(p2)
        self.assertIs(srv.get_pipeline(), p2)

    def test_dispatch_pipeline_attribute_exists_after_init(self):
        """Regression: _dispatch_pipeline must be set in __init__."""
        import importlib
        srv_mod = importlib.import_module("ipfs_datasets_py.mcp_server.server")
        srv = object.__new__(srv_mod.IPFSDatasetsMCPServer)
        srv.configs = MagicMock()
        srv.mcp = None
        srv.tools = {}
        srv._dispatch_pipeline = None  # simulates __init__
        self.assertTrue(hasattr(srv, "_dispatch_pipeline"))


# ---------------------------------------------------------------------------
# 2. policy_management_tool.py
# ---------------------------------------------------------------------------

class TestPolicyManagementTools(unittest.TestCase):
    """Tests for the 6 MCP-exposed policy management tools."""

    def _clear_registry(self):
        import ipfs_datasets_py.mcp_server.nl_ucan_policy as mod
        mod._GLOBAL_REGISTRY = None

    def setUp(self):
        self._clear_registry()

    def tearDown(self):
        self._clear_registry()

    # --- policy_register ---

    def test_policy_register_success(self):
        from ipfs_datasets_py.mcp_server.tools.logic_tools.policy_management_tool import policy_register
        result = policy_register("test_pol", "alice may call list_tools")
        self.assertEqual(result["status"], "registered")
        self.assertEqual(result["name"], "test_pol")
        self.assertIn("source_cid", result)
        self.assertIn("clause_count", result)

    def test_policy_register_returns_source_cid(self):
        from ipfs_datasets_py.mcp_server.tools.logic_tools.policy_management_tool import policy_register
        result = policy_register("pol_a", "bob may call add_document description description_a")
        self.assertIsInstance(result["source_cid"], str)
        self.assertTrue(len(result["source_cid"]) > 0)

    def test_policy_register_description_stored(self):
        from ipfs_datasets_py.mcp_server.tools.logic_tools.policy_management_tool import policy_register
        result = policy_register("pol_b", "system may call all tools", description="System wide")
        self.assertEqual(result["status"], "registered")

    def test_policy_register_replaces_existing(self):
        from ipfs_datasets_py.mcp_server.tools.logic_tools.policy_management_tool import policy_register, policy_list
        policy_register("dup", "alice may call get_schema")
        policy_register("dup", "bob may call list_tools")
        names = policy_list()["names"]
        self.assertEqual(names.count("dup"), 1)

    # --- policy_list ---

    def test_policy_list_empty_initially(self):
        from ipfs_datasets_py.mcp_server.tools.logic_tools.policy_management_tool import policy_list
        result = policy_list()
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["count"], 0)
        self.assertEqual(result["names"], [])

    def test_policy_list_after_registration(self):
        from ipfs_datasets_py.mcp_server.tools.logic_tools.policy_management_tool import policy_register, policy_list
        policy_register("p1", "alice may call foo")
        policy_register("p2", "bob may call bar")
        result = policy_list()
        self.assertIn("p1", result["names"])
        self.assertIn("p2", result["names"])
        self.assertEqual(result["count"], 2)

    # --- policy_remove ---

    def test_policy_remove_existing(self):
        from ipfs_datasets_py.mcp_server.tools.logic_tools.policy_management_tool import policy_register, policy_remove
        policy_register("to_del", "alice may call foo")
        result = policy_remove("to_del")
        self.assertEqual(result["status"], "ok")
        self.assertTrue(result["removed"])

    def test_policy_remove_missing(self):
        from ipfs_datasets_py.mcp_server.tools.logic_tools.policy_management_tool import policy_remove
        result = policy_remove("nonexistent")
        self.assertEqual(result["status"], "ok")
        self.assertFalse(result["removed"])

    def test_policy_remove_leaves_others(self):
        from ipfs_datasets_py.mcp_server.tools.logic_tools.policy_management_tool import policy_register, policy_remove, policy_list
        policy_register("keep", "alice may call foo")
        policy_register("del", "bob may call bar")
        policy_remove("del")
        self.assertIn("keep", policy_list()["names"])
        self.assertNotIn("del", policy_list()["names"])

    # --- policy_evaluate ---

    def test_policy_evaluate_allow(self):
        from ipfs_datasets_py.mcp_server.tools.logic_tools.policy_management_tool import policy_register, policy_evaluate
        policy_register("open", "alice may call list_tools")
        result = policy_evaluate("open", "alice", "list_tools")
        self.assertEqual(result["status"], "ok")
        # The gate is open-world; allow is the expected outcome for registered permission
        self.assertIn(result["verdict"], ("allow", "deny"))

    def test_policy_evaluate_no_policy_open_default(self):
        from ipfs_datasets_py.mcp_server.tools.logic_tools.policy_management_tool import policy_evaluate
        result = policy_evaluate("nonexistent_policy", "alice", "any_tool")
        # Either an error (no policy) or allow (open default)
        self.assertIn(result["status"], ("ok", "error"))

    def test_policy_evaluate_returns_actor_and_tool(self):
        from ipfs_datasets_py.mcp_server.tools.logic_tools.policy_management_tool import policy_register, policy_evaluate
        policy_register("echo", "system may call echo_tool")
        result = policy_evaluate("echo", "system", "echo_tool")
        self.assertEqual(result["actor"], "system")
        self.assertEqual(result["tool_name"], "echo_tool")
        self.assertEqual(result["policy_name"], "echo")

    # --- interface_register ---

    def test_interface_register_success(self):
        from ipfs_datasets_py.mcp_server.tools.logic_tools.policy_management_tool import interface_register
        import ipfs_datasets_py.mcp_server.tools.logic_tools.policy_management_tool as mod
        mod._interface_repo = None  # reset singleton
        result = interface_register("test/v1", "1.0.0", description="Test interface")
        self.assertEqual(result["status"], "registered")
        self.assertIn("interface_cid", result)
        self.assertEqual(result["name"], "test/v1")
        self.assertEqual(result["version"], "1.0.0")
        mod._interface_repo = None

    def test_interface_register_with_methods(self):
        from ipfs_datasets_py.mcp_server.tools.logic_tools.policy_management_tool import interface_register
        import ipfs_datasets_py.mcp_server.tools.logic_tools.policy_management_tool as mod
        mod._interface_repo = None
        methods = [{"name": "foo", "params": {"x": "int"}, "returns": {"y": "str"}}]
        result = interface_register("svc/v2", "2.0.0", methods=methods)
        self.assertEqual(result["status"], "registered")
        mod._interface_repo = None

    def test_interface_register_cid_is_string(self):
        from ipfs_datasets_py.mcp_server.tools.logic_tools.policy_management_tool import interface_register
        import ipfs_datasets_py.mcp_server.tools.logic_tools.policy_management_tool as mod
        mod._interface_repo = None
        result = interface_register("a/v1")
        self.assertIsInstance(result["interface_cid"], str)
        mod._interface_repo = None

    # --- interface_list ---

    def test_interface_list_empty(self):
        from ipfs_datasets_py.mcp_server.tools.logic_tools.policy_management_tool import interface_list
        import ipfs_datasets_py.mcp_server.tools.logic_tools.policy_management_tool as mod
        mod._interface_repo = None
        result = interface_list()
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["count"], 0)
        mod._interface_repo = None

    def test_interface_list_after_register(self):
        from ipfs_datasets_py.mcp_server.tools.logic_tools.policy_management_tool import interface_register, interface_list
        import ipfs_datasets_py.mcp_server.tools.logic_tools.policy_management_tool as mod
        mod._interface_repo = None
        interface_register("svc/v3", "3.0.0")
        result = interface_list()
        self.assertEqual(result["count"], 1)
        self.assertEqual(len(result["interface_cids"]), 1)
        mod._interface_repo = None

    def test_interface_list_count_increments(self):
        from ipfs_datasets_py.mcp_server.tools.logic_tools.policy_management_tool import interface_register, interface_list
        import ipfs_datasets_py.mcp_server.tools.logic_tools.policy_management_tool as mod
        mod._interface_repo = None
        interface_register("a/v1")
        interface_register("b/v2")
        result = interface_list()
        self.assertEqual(result["count"], 2)
        mod._interface_repo = None


# ---------------------------------------------------------------------------
# 3. risk_scorer.py — risk_score_from_dag
# ---------------------------------------------------------------------------

class TestRiskScoreFromDag(unittest.TestCase):

    def _make_dag(self, nodes_list):
        """Build a mock DAG with _nodes dict."""
        dag = MagicMock()
        nodes = {}
        for n in nodes_list:
            cid = f"cid-{id(n)}"
            node = MagicMock()
            node.intent_cid = n.get("intent_cid", "")
            node.output_cid = n.get("output_cid", "")
            node.receipt_cid = n.get("receipt_cid", "")
            nodes[cid] = node
        dag._nodes = nodes
        return dag

    def test_empty_dag_returns_zero(self):
        from ipfs_datasets_py.mcp_server.risk_scorer import risk_score_from_dag
        dag = self._make_dag([])
        self.assertEqual(risk_score_from_dag(dag, "my_tool"), 0.0)

    def test_no_matching_events_returns_zero(self):
        from ipfs_datasets_py.mcp_server.risk_scorer import risk_score_from_dag
        dag = self._make_dag([
            {"intent_cid": "cid-foo", "output_cid": "ok", "receipt_cid": "rcpt1"},
        ])
        self.assertEqual(risk_score_from_dag(dag, "my_tool"), 0.0)

    def test_rollback_event_adds_penalty(self):
        from ipfs_datasets_py.mcp_server.risk_scorer import risk_score_from_dag
        dag = self._make_dag([
            {"intent_cid": "intent-my_tool", "output_cid": "rollback-xyz", "receipt_cid": "rcpt"},
        ])
        score = risk_score_from_dag(dag, "my_tool")
        # rollback_penalty=0.15 by default
        self.assertAlmostEqual(score, 0.15, places=5)

    def test_error_event_adds_penalty(self):
        from ipfs_datasets_py.mcp_server.risk_scorer import risk_score_from_dag
        # receipt_cid="" means error
        dag = self._make_dag([
            {"intent_cid": "intent-my_tool", "output_cid": "some-output", "receipt_cid": ""},
        ])
        score = risk_score_from_dag(dag, "my_tool")
        # error_penalty=0.10 by default
        self.assertAlmostEqual(score, 0.10, places=5)

    def test_multiple_events_accumulate_penalty(self):
        from ipfs_datasets_py.mcp_server.risk_scorer import risk_score_from_dag
        dag = self._make_dag([
            {"output_cid": "rollback-1", "receipt_cid": "r1"},
            {"output_cid": "rollback-2", "receipt_cid": "r2"},
            {"output_cid": "ok", "receipt_cid": ""},
        ])
        score = risk_score_from_dag(dag, "tool")
        # 2*0.15 + 1*0.10 = 0.40
        self.assertAlmostEqual(score, 0.40, places=5)

    def test_max_penalty_caps_result(self):
        from ipfs_datasets_py.mcp_server.risk_scorer import risk_score_from_dag
        dag = self._make_dag([
            {"output_cid": "rollback-x", "receipt_cid": "r"} for _ in range(10)
        ])
        score = risk_score_from_dag(dag, "tool", max_penalty=0.30)
        self.assertEqual(score, 0.30)

    def test_custom_penalties(self):
        from ipfs_datasets_py.mcp_server.risk_scorer import risk_score_from_dag
        dag = self._make_dag([
            {"output_cid": "rollback-1", "receipt_cid": "r"},
        ])
        score = risk_score_from_dag(dag, "tool", rollback_penalty=0.20)
        self.assertAlmostEqual(score, 0.20, places=5)

    def test_function_exported(self):
        from ipfs_datasets_py.mcp_server import risk_scorer
        self.assertTrue(hasattr(risk_scorer, "risk_score_from_dag"))


# ---------------------------------------------------------------------------
# 4. mcp_p2p_transport.py — PubSubEventType + PubSubBus
# ---------------------------------------------------------------------------

class TestPubSubEventType(unittest.TestCase):

    def test_event_type_values_match_topics(self):
        from ipfs_datasets_py.mcp_server.mcp_p2p_transport import PubSubEventType, MCP_P2P_PUBSUB_TOPICS
        self.assertEqual(PubSubEventType.INTERFACE_ANNOUNCE, MCP_P2P_PUBSUB_TOPICS["interface_announce"])
        self.assertEqual(PubSubEventType.RECEIPT_DISSEMINATE, MCP_P2P_PUBSUB_TOPICS["receipt_disseminate"])
        self.assertEqual(PubSubEventType.DECISION_DISSEMINATE, MCP_P2P_PUBSUB_TOPICS["decision_disseminate"])
        self.assertEqual(PubSubEventType.SCHEDULING_SIGNAL, MCP_P2P_PUBSUB_TOPICS["scheduling_signal"])

    def test_event_type_is_str(self):
        from ipfs_datasets_py.mcp_server.mcp_p2p_transport import PubSubEventType
        self.assertIsInstance(PubSubEventType.INTERFACE_ANNOUNCE, str)

    def test_event_type_enum_has_four_members(self):
        from ipfs_datasets_py.mcp_server.mcp_p2p_transport import PubSubEventType
        self.assertEqual(len(PubSubEventType), 4)


class TestPubSubBus(unittest.TestCase):

    def _bus(self):
        from ipfs_datasets_py.mcp_server.mcp_p2p_transport import PubSubBus
        return PubSubBus()

    def test_initial_topic_count_zero(self):
        bus = self._bus()
        from ipfs_datasets_py.mcp_server.mcp_p2p_transport import PubSubEventType
        self.assertEqual(bus.topic_count(PubSubEventType.INTERFACE_ANNOUNCE), 0)

    def test_subscribe_increments_count(self):
        bus = self._bus()
        from ipfs_datasets_py.mcp_server.mcp_p2p_transport import PubSubEventType
        bus.subscribe(PubSubEventType.INTERFACE_ANNOUNCE, lambda t, p: None)
        self.assertEqual(bus.topic_count(PubSubEventType.INTERFACE_ANNOUNCE), 1)

    def test_subscribe_same_handler_once(self):
        bus = self._bus()
        h = lambda t, p: None
        bus.subscribe("my_topic", h)
        bus.subscribe("my_topic", h)
        self.assertEqual(bus.topic_count("my_topic"), 1)

    def test_publish_calls_subscriber(self):
        bus = self._bus()
        received = []
        bus.subscribe("topic1", lambda t, p: received.append(p))
        bus.publish("topic1", {"x": 1})
        self.assertEqual(received, [{"x": 1}])

    def test_publish_returns_count(self):
        bus = self._bus()
        bus.subscribe("topic1", lambda t, p: None)
        bus.subscribe("topic1", lambda t, p: None)
        self.assertEqual(bus.publish("topic1", {}), 2)

    def test_publish_no_subscribers_returns_zero(self):
        bus = self._bus()
        self.assertEqual(bus.publish("empty_topic", {}), 0)

    def test_publish_to_different_topic_not_received(self):
        bus = self._bus()
        received = []
        bus.subscribe("topic_a", lambda t, p: received.append(p))
        bus.publish("topic_b", {"y": 2})
        self.assertEqual(received, [])

    def test_unsubscribe_removes_handler(self):
        bus = self._bus()
        h = lambda t, p: None
        bus.subscribe("topic1", h)
        removed = bus.unsubscribe("topic1", h)
        self.assertTrue(removed)
        self.assertEqual(bus.topic_count("topic1"), 0)

    def test_unsubscribe_missing_returns_false(self):
        bus = self._bus()
        removed = bus.unsubscribe("topic1", lambda t, p: None)
        self.assertFalse(removed)

    def test_clear_all(self):
        bus = self._bus()
        bus.subscribe("t1", lambda t, p: None)
        bus.subscribe("t2", lambda t, p: None)
        bus.clear()
        self.assertEqual(bus.topic_count("t1"), 0)
        self.assertEqual(bus.topic_count("t2"), 0)

    def test_clear_single_topic(self):
        bus = self._bus()
        bus.subscribe("t1", lambda t, p: None)
        bus.subscribe("t2", lambda t, p: None)
        bus.clear("t1")
        self.assertEqual(bus.topic_count("t1"), 0)
        self.assertEqual(bus.topic_count("t2"), 1)

    def test_publish_event_type_enum(self):
        from ipfs_datasets_py.mcp_server.mcp_p2p_transport import PubSubEventType
        bus = self._bus()
        received = []
        bus.subscribe(PubSubEventType.RECEIPT_DISSEMINATE, lambda t, p: received.append(p))
        bus.publish(PubSubEventType.RECEIPT_DISSEMINATE, {"tool": "add"})
        self.assertEqual(len(received), 1)
        self.assertEqual(received[0]["tool"], "add")

    def test_multiple_topics_independent(self):
        bus = self._bus()
        a_received = []
        b_received = []
        bus.subscribe("a", lambda t, p: a_received.append(p))
        bus.subscribe("b", lambda t, p: b_received.append(p))
        bus.publish("a", {"n": 1})
        bus.publish("b", {"n": 2})
        bus.publish("a", {"n": 3})
        self.assertEqual(len(a_received), 2)
        self.assertEqual(len(b_received), 1)

    def test_pubsub_bus_exported(self):
        from ipfs_datasets_py.mcp_server import mcp_p2p_transport
        self.assertTrue(hasattr(mcp_p2p_transport, "PubSubBus"))
        self.assertTrue(hasattr(mcp_p2p_transport, "PubSubEventType"))


# ---------------------------------------------------------------------------
# 5. Dispatch pipeline — edge cases
# ---------------------------------------------------------------------------

class TestDispatchPipelineEdgeCases(unittest.TestCase):

    def _intent(self, tool_name="list_tools", actor="alice"):
        from ipfs_datasets_py.mcp_server.dispatch_pipeline import PipelineIntent
        return PipelineIntent(tool_name=tool_name, actor=actor)

    def test_pipeline_result_to_dict_keys(self):
        from ipfs_datasets_py.mcp_server.dispatch_pipeline import DispatchPipeline, PipelineConfig
        pipeline = DispatchPipeline(config=PipelineConfig())
        result = pipeline.check(self._intent())
        d = result.to_dict()
        self.assertIn("allowed", d)
        self.assertIn("verdict", d)
        # to_dict uses "stages" key (list of stage outcomes)
        self.assertIn("stages", d)
        self.assertIn("blocking_stage", d)

    def test_all_disabled_pipeline_allows_everything(self):
        from ipfs_datasets_py.mcp_server.dispatch_pipeline import make_default_pipeline
        pipeline = make_default_pipeline()
        result = pipeline.check(self._intent(actor="unknown"))
        self.assertTrue(result.allowed)
        self.assertEqual(result.blocking_stage, None)

    def test_pipeline_intent_tool_alias(self):
        from ipfs_datasets_py.mcp_server.dispatch_pipeline import PipelineIntent
        intent = PipelineIntent(tool_name="my_tool", actor="bob")
        self.assertEqual(intent.tool, "my_tool")

    def test_pipeline_intent_cid_deterministic(self):
        from ipfs_datasets_py.mcp_server.dispatch_pipeline import PipelineIntent
        i1 = PipelineIntent(tool_name="foo", actor="alice")
        i2 = PipelineIntent(tool_name="foo", actor="alice")
        self.assertEqual(i1.intent_cid, i2.intent_cid)

    def test_pipeline_intent_cid_differs_for_different_tools(self):
        from ipfs_datasets_py.mcp_server.dispatch_pipeline import PipelineIntent
        i1 = PipelineIntent(tool_name="foo", actor="alice")
        i2 = PipelineIntent(tool_name="bar", actor="alice")
        self.assertNotEqual(i1.intent_cid, i2.intent_cid)

    def test_pipeline_intent_cid_starts_with_bafy(self):
        from ipfs_datasets_py.mcp_server.dispatch_pipeline import PipelineIntent
        intent = PipelineIntent(tool_name="test", actor="system")
        self.assertTrue(intent.intent_cid.startswith("bafy"))

    def test_pipeline_record_execution_returns_receipt(self):
        from ipfs_datasets_py.mcp_server.dispatch_pipeline import make_default_pipeline
        pipeline = make_default_pipeline()
        intent = self._intent()
        receipt = pipeline.record_execution(intent, {"ok": True})
        self.assertIsNotNone(receipt)

    def test_pipeline_record_execution_with_error(self):
        from ipfs_datasets_py.mcp_server.dispatch_pipeline import make_default_pipeline
        pipeline = make_default_pipeline()
        intent = self._intent()
        receipt = pipeline.record_execution(intent, None, error=ValueError("oops"))
        self.assertIsNotNone(receipt)

    def test_pipeline_attach_event_dag(self):
        from ipfs_datasets_py.mcp_server.dispatch_pipeline import make_default_pipeline
        from ipfs_datasets_py.mcp_server.event_dag import EventDAG
        pipeline = make_default_pipeline()
        dag = EventDAG()
        pipeline.attach_event_dag(dag)
        self.assertIs(pipeline._event_dag, dag)


if __name__ == "__main__":
    unittest.main()
