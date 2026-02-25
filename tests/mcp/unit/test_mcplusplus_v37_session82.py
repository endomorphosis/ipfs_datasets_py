"""
Session 82 E2E Tests — Advanced Observability & Lifecycle Hooks (MCP++ v38).

Tests cover:
1. PubSubBus.publish_stats() — observability statistics
2. ComplianceChecker.lifecycle_hooks — before/after callbacks for rotate and purge
3. EventNode.to_json() — JSON serialization
4. Cross-feature integration scenarios

Session documentation: MASTER_IMPROVEMENT_PLAN_2026_v37.md → v38
"""

import json
import os
import tempfile
import pytest
from typing import List, Dict, Any

from ipfs_datasets_py.mcp_server.mcp_p2p_transport import PubSubBus, PubSubEventType
from ipfs_datasets_py.mcp_server.compliance_checker import ComplianceChecker
from ipfs_datasets_py.mcp_server.cid_artifacts import EventNode


# ---------------------------------------------------------------------------
# Test Group 1: PubSubBus.publish_stats()
# ---------------------------------------------------------------------------

class TestPubSubBusPublishStats:
    """Test PubSubBus.publish_stats() observability method."""

    def test_publish_stats_empty_bus(self):
        """Stats should return empty dict when no subscriptions exist."""
        bus = PubSubBus()
        stats = bus.publish_stats()
        
        assert stats == {}
        assert isinstance(stats, dict)

    def test_publish_stats_single_topic(self):
        """Stats should return {topic: count} for single topic."""
        bus = PubSubBus()
        
        def handler1(topic, payload): pass
        def handler2(topic, payload): pass
        
        bus.subscribe("receipts", handler1)
        bus.subscribe("receipts", handler2)
        
        stats = bus.publish_stats()
        
        assert stats == {"receipts": 2}

    def test_publish_stats_multiple_topics(self):
        """Stats should include all topics with ≥1 subscriber."""
        bus = PubSubBus()
        
        def h1(t, p): pass
        def h2(t, p): pass
        def h3(t, p): pass
        
        bus.subscribe("receipts", h1)
        bus.subscribe("receipts", h2)
        bus.subscribe("delegation", h3)
        bus.subscribe("audit", h1)  # h1 subscribed to multiple topics
        
        stats = bus.publish_stats()
        
        assert stats == {"receipts": 2, "delegation": 1, "audit": 1}

    def test_publish_stats_excludes_zero_subscribers(self):
        """Topics with zero subscribers should not appear in stats."""
        bus = PubSubBus()
        
        def handler(t, p): pass
        
        bus.subscribe("receipts", handler)
        bus.subscribe("audit", handler)
        
        # Unsubscribe from audit
        bus.unsubscribe("audit", handler)
        
        stats = bus.publish_stats()
        
        assert "audit" not in stats
        assert stats == {"receipts": 1}

    def test_publish_stats_equivalent_to_snapshot(self):
        """pub_stats() should return same result as snapshot()."""
        bus = PubSubBus()
        
        def h1(t, p): pass
        def h2(t, p): pass
        
        bus.subscribe(PubSubEventType.INTERFACE_ANNOUNCE, h1)
        bus.subscribe(PubSubEventType.RECEIPT_DISSEMINATE, h2)
        
        stats = bus.publish_stats()
        snapshot = bus.snapshot()
        
        assert stats == snapshot

    def test_publish_stats_monitoring_integration(self):
        """Stats format suitable for monitoring dashboards."""
        bus = PubSubBus()
        
        for i in range(5):
            bus.subscribe(f"topic_{i}", lambda t, p: None)
        
        stats = bus.publish_stats()
        
        # Verify all keys are strings (topic names)
        assert all(isinstance(k, str) for k in stats.keys())
        # Verify all values are integers (subscriber counts)
        assert all(isinstance(v, int) and v >= 1 for v in stats.values())
        # Should have 5 active topics
        assert len(stats) == 5


# ---------------------------------------------------------------------------
# Test Group 2: ComplianceChecker.lifecycle_hooks
# ---------------------------------------------------------------------------

class TestComplianceCheckerLifecycleHooks:
    """Test ComplianceChecker lifecycle hook system."""

    def test_add_lifecycle_hook_rotate(self):
        """Should successfully add before_rotate hook."""
        invocations = []
        
        def hook(path: str) -> None:
            invocations.append(("before_rotate", path))
        
        ComplianceChecker.add_lifecycle_hook("before_rotate", hook)
        
        assert hook in ComplianceChecker.lifecycle_hooks["before_rotate"]
        
        # Cleanup
        ComplianceChecker.remove_lifecycle_hook("before_rotate", hook)

    def test_add_lifecycle_hook_invalid_type(self):
        """Should raise ValueError for invalid hook type."""
        def hook(path: str): pass
        
        with pytest.raises(ValueError, match="Unknown hook type"):
            ComplianceChecker.add_lifecycle_hook("invalid_hook", hook)

    def test_remove_lifecycle_hook(self):
        """Should successfully remove registered hook."""
        def hook(path: str): pass
        
        ComplianceChecker.add_lifecycle_hook("after_rotate", hook)
        removed = ComplianceChecker.remove_lifecycle_hook("after_rotate", hook)
        
        assert removed is True
        assert hook not in ComplianceChecker.lifecycle_hooks["after_rotate"]

    def test_remove_lifecycle_hook_not_registered(self):
        """Should return False when removing non-existent hook."""
        def hook(path: str): pass
        
        removed = ComplianceChecker.remove_lifecycle_hook("before_purge", hook)
        
        assert removed is False

    def test_clear_lifecycle_hooks_single_type(self):
        """Should clear all hooks of specified type."""
        def h1(path): pass
        def h2(path): pass
        
        ComplianceChecker.add_lifecycle_hook("before_rotate", h1)
        ComplianceChecker.add_lifecycle_hook("before_rotate", h2)
        ComplianceChecker.add_lifecycle_hook("after_rotate", h1)
        
        count = ComplianceChecker.clear_lifecycle_hooks("before_rotate")
        
        assert count == 2
        assert len(ComplianceChecker.lifecycle_hooks["before_rotate"]) == 0
        assert len(ComplianceChecker.lifecycle_hooks["after_rotate"]) == 1
        
        # Cleanup
        ComplianceChecker.clear_lifecycle_hooks()

    def test_clear_lifecycle_hooks_all(self):
        """Should clear all hooks across all types."""
        def h1(path): pass
        
        for hook_type in ["before_rotate", "after_rotate", "before_purge", "after_purge"]:
            ComplianceChecker.add_lifecycle_hook(hook_type, h1)
        
        count = ComplianceChecker.clear_lifecycle_hooks()
        
        assert count == 4
        for hooks in ComplianceChecker.lifecycle_hooks.values():
            assert len(hooks) == 0

    def test_rotate_bak_invokes_hooks(self):
        """rotate_bak should invoke before/after hooks."""
        invocations = []
        
        def before_hook(path: str):
            invocations.append(("before", path))
        
        def after_hook(path: str):
            invocations.append(("after", path))
        
        ComplianceChecker.add_lifecycle_hook("before_rotate", before_hook)
        ComplianceChecker.add_lifecycle_hook("after_rotate", after_hook)
        
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".txt") as f:
            path = f.name
            f.write("test content")
        
        try:
            # Create a .bak file
            bak_path = path + ".bak"
            with open(bak_path, "w") as f:
                f.write("backup content")
            
            # Rotate
            ComplianceChecker.rotate_bak(path, max_keep=3)
            
            # Verify hooks were called
            assert len(invocations) == 2
            assert invocations[0] == ("before", path)
            assert invocations[1] == ("after", path)
        
        finally:
            # Cleanup
            for ext in ["", ".bak", ".bak.1", ".bak.2", ".bak.3"]:
                try:
                    os.unlink(path + ext)
                except OSError:
                    pass
            ComplianceChecker.clear_lifecycle_hooks()

    def test_purge_bak_files_invokes_hooks(self):
        """purge_bak_files should invoke before/after hooks."""
        invocations = []
        
        def before_hook(path: str):
            invocations.append(("before_purge", path))
        
        def after_hook(path: str):
            invocations.append(("after_purge", path))
        
        ComplianceChecker.add_lifecycle_hook("before_purge", before_hook)
        ComplianceChecker.add_lifecycle_hook("after_purge", after_hook)
        
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".txt") as f:
            path = f.name
            f.write("test")
        
        try:
            # Create backup files
            for ext in [".bak", ".bak.1", ".bak.2"]:
                with open(path + ext, "w") as f:
                    f.write("backup")
            
            # Purge
            removed = ComplianceChecker.purge_bak_files(path)
            
            # Verify hooks were called
            assert removed == 3
            assert len(invocations) == 2
            assert invocations[0] == ("before_purge", path)
            assert invocations[1] == ("after_purge", path)
        
        finally:
            try:
                os.unlink(path)
            except OSError:
                pass
            ComplianceChecker.clear_lifecycle_hooks()

    def test_lifecycle_hook_exception_handling(self):
        """Hook exceptions should not break backup operations."""
        invocations = []
        
        def failing_hook(path: str):
            raise RuntimeError("Hook error")
        
        def working_hook(path: str):
            invocations.append(path)
        
        ComplianceChecker.add_lifecycle_hook("before_rotate", failing_hook)
        ComplianceChecker.add_lifecycle_hook("after_rotate", working_hook)
        
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".txt") as f:
            path = f.name
            f.write("test")
        
        try:
            bak_path = path + ".bak"
            with open(bak_path, "w") as f:
                f.write("backup")
            
            # rotate_bak should complete despite failing hook
            ComplianceChecker.rotate_bak(path, max_keep=3)
            
            # after_rotate hook should still execute
            assert len(invocations) == 1
            assert invocations[0] == path
        
        finally:
            for ext in ["", ".bak", ".bak.1"]:
                try:
                    os.unlink(path + ext)
                except OSError:
                    pass
            ComplianceChecker.clear_lifecycle_hooks()


# ---------------------------------------------------------------------------
# Test Group 3: EventNode.to_json()
# ---------------------------------------------------------------------------

class TestEventNodeToJson:
    """Test EventNode.to_json() serialization method."""

    def test_to_json_basic(self):
        """Should serialize EventNode to valid JSON string."""
        node = EventNode(
            parents=[],
            interface_cid="bafyreiabc123",
            intent_cid="bafyreiabc456",
            decision_cid="bafyreiabc789",
            output_cid="",
            receipt_cid="",
        )
        
        json_str = node.to_json()
        
        assert isinstance(json_str, str)
        # Should be parseable JSON
        data = json.loads(json_str)
        assert data["interface_cid"] == "bafyreiabc123"
        assert data["intent_cid"] == "bafyreiabc456"

    def test_to_json_with_indent(self):
        """Should support indent parameter for pretty printing."""
        node = EventNode(
            parents=["bafyreiabc"],
            interface_cid="bafyreiabc123",
            intent_cid="bafyreiabc456",
        )
        
        json_compact = node.to_json()
        json_pretty = node.to_json(indent=2)
        
        # Pretty version should have newlines
        assert "\n" not in json_compact
        assert "\n" in json_pretty
        # Both should parse to same data
        assert json.loads(json_compact) == json.loads(json_pretty)

    def test_to_json_includes_timestamps(self):
        """JSON should include timestamp fields."""
        node = EventNode(
            interface_cid="bafyrei",
            intent_cid="bafyrei",
        )
        
        data = json.loads(node.to_json())
        
        assert "timestamps" in data
        assert "created" in data["timestamps"]
        assert "observed" in data["timestamps"]
        # Timestamps should be ISO-8601 strings
        assert isinstance(data["timestamps"]["created"], str)
        assert "T" in data["timestamps"]["created"]
        assert "Z" in data["timestamps"]["created"]

    def test_to_json_handles_optional_fields(self):
        """JSON should properly handle None values for optional fields."""
        node = EventNode(
            interface_cid="bafyrei",
            intent_cid="bafyrei",
            proof_cid=None,
            peer_did=None,
        )
        
        data = json.loads(node.to_json())
        
        assert data["proof_cid"] is None
        assert data["peer_did"] is None

    def test_to_json_round_trip(self):
        """Should be able to reconstruct EventNode from JSON."""
        original = EventNode(
            parents=["cid1", "cid2"],
            interface_cid="bafyreiabc",
            intent_cid="bafyreiabc",
            decision_cid="bafyreiabc",
            output_cid="bafyreiabc",
            receipt_cid="bafyreiabc",
            proof_cid="bafyreiabc",
            peer_did="did:key:abc",
        )
        
        json_str = original.to_json()
        data = json.loads(json_str)
        
        # Reconstruct (manual extraction for this test)
        assert data["parents"] == ["cid1", "cid2"]
        assert data["interface_cid"] == "bafyreiabc"
        assert data["proof_cid"] == "bafyreiabc"
        assert data["peer_did"] == "did:key:abc"


# ---------------------------------------------------------------------------
# Test Group 4: Integration Scenarios
# ---------------------------------------------------------------------------

class TestSession82Integration:
    """Integration tests combining Session 82 features."""

    def test_pubsub_stats_with_compliance_hooks(self):
        """Monitor PubSub events during compliance operations."""
        bus = PubSubBus()
        events_received = []
        
        def audit_handler(topic, payload):
            events_received.append(payload)
        
        bus.subscribe("compliance_audit", audit_handler)
        
        # Add compliance hook that publishes to pubsub
        def rotation_audit(path: str):
            bus.publish("compliance_audit", {"event": "rotation", "path": path})
        
        ComplianceChecker.add_lifecycle_hook("after_rotate", rotation_audit)
        
        try:
            with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".txt") as f:
                path = f.name
                f.write("test")
            
            bak_path = path + ".bak"
            with open(bak_path, "w") as f:
                f.write("backup")
            
            # Rotate and verify pubsub event
            ComplianceChecker.rotate_bak(path, max_keep=3)
            
            # Check stats
            stats = bus.publish_stats()
            assert stats["compliance_audit"] == 1
            
            # Check event was received
            assert len(events_received) == 1
            assert events_received[0]["event"] == "rotation"
            assert events_received[0]["path"] == path
        
        finally:
            for ext in ["", ".bak", ".bak.1"]:
                try:
                    os.unlink(path + ext)
                except OSError:
                    pass
            ComplianceChecker.clear_lifecycle_hooks()

    def test_event_node_json_in_pubsub_payload(self):
        """Use EventNode.to_json() in PubSub event payloads."""
        bus = PubSubBus()
        received_events = []
        
        def handler(topic, payload):
            received_events.append(payload)
        
        bus.subscribe("event_dag", handler)
        
        # Create event node and publish as JSON
        node = EventNode(
            interface_cid="bafyrei123",
            intent_cid="bafyrei456",
            decision_cid="bafyrei789",
        )
        
        # Publish with JSON-serialized event
        bus.publish("event_dag", {
            "type": "new_event",
            "event_json": node.to_json(),
            "event_cid": node.event_cid,
        })
        
        # Verify
        assert len(received_events) == 1
        payload = received_events[0]
        assert payload["type"] == "new_event"
        
        # Verify JSON is parseable
        event_data = json.loads(payload["event_json"])
        assert event_data["interface_cid"] == "bafyrei123"

    def test_observability_dashboard_integration(self):
        """Simulate monitoring dashboard using publish_stats()."""
        bus = PubSubBus()
        
        # Simulate various services subscribing
        services = ["receipts", "delegation", "audit", "validation"]
        handlers_per_service = [3, 2, 1, 4]
        
        for service, count in zip(services, handlers_per_service):
            for i in range(count):
                bus.subscribe(service, lambda t, p: None)
        
        # Get stats for dashboard
        stats = bus.publish_stats()
        
        # Verify all services present
        assert len(stats) == 4
        assert stats["receipts"] == 3
        assert stats["delegation"] == 2
        assert stats["audit"] == 1
        assert stats["validation"] == 4
        
        # Calculate metrics
        total_subscriptions = sum(stats.values())
        active_topics = len(stats)
        avg_subscribers = total_subscriptions / active_topics
        
        assert total_subscriptions == 10
        assert active_topics == 4
        assert avg_subscribers == 2.5

    def test_compliance_lifecycle_audit_trail(self):
        """Build complete audit trail using lifecycle hooks."""
        audit_log = []
        
        def log_event(event_type: str):
            def hook(path: str):
                audit_log.append({
                    "event": event_type,
                    "path": path,
                    "timestamp": EventNode().timestamp_created,
                })
            return hook
        
        # Register all hooks
        ComplianceChecker.add_lifecycle_hook("before_rotate", log_event("rotate_start"))
        ComplianceChecker.add_lifecycle_hook("after_rotate", log_event("rotate_end"))
        ComplianceChecker.add_lifecycle_hook("before_purge", log_event("purge_start"))
        ComplianceChecker.add_lifecycle_hook("after_purge", log_event("purge_end"))
        
        try:
            with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".txt") as f:
                path = f.name
                f.write("test")
            
            # Create backups
            for ext in [".bak", ".bak.1"]:
                with open(path + ext, "w") as f:
                    f.write("backup")
            
            # Perform operations
            ComplianceChecker.rotate_bak(path, max_keep=3)
            ComplianceChecker.purge_bak_files(path)
            
            # Verify audit trail
            assert len(audit_log) == 4
            assert audit_log[0]["event"] == "rotate_start"
            assert audit_log[1]["event"] == "rotate_end"
            assert audit_log[2]["event"] == "purge_start"
            assert audit_log[3]["event"] == "purge_end"
            
            # All events for same path
            paths = [entry["path"] for entry in audit_log]
            assert all(p == path for p in paths)
        
        finally:
            try:
                os.unlink(path)
            except OSError:
                pass
            ComplianceChecker.clear_lifecycle_hooks()


# ---------------------------------------------------------------------------
# Regression Tests
# ---------------------------------------------------------------------------

class TestSession82Regressions:
    """Regression tests ensuring backward compatibility."""

    def test_pubsub_snapshot_unchanged(self):
        """snapshot() should still work identically."""
        bus = PubSubBus()
        
        def h(t, p): pass
        bus.subscribe("topic1", h)
        
        # Both methods should exist and return same result
        stats = bus.publish_stats()
        snapshot = bus.snapshot()
        
        assert stats == snapshot
        assert stats == {"topic1": 1}

    def test_compliance_rotate_without_hooks(self):
        """rotate_bak should work normally when no hooks registered."""
        # Clear any lingering hooks
        ComplianceChecker.clear_lifecycle_hooks()
        
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".txt") as f:
            path = f.name
            f.write("test")
        
        try:
            bak_path = path + ".bak"
            with open(bak_path, "w") as f:
                f.write("backup")
            
            # Should work without errors
            ComplianceChecker.rotate_bak(path, max_keep=3)
            
            # Backup should be rotated
            assert os.path.exists(path + ".bak.1")
        
        finally:
            for ext in ["", ".bak", ".bak.1"]:
                try:
                    os.unlink(path + ext)
                except OSError:
                    pass

    def test_event_node_to_dict_unchanged(self):
        """to_dict() should still work as before."""
        node = EventNode(
            interface_cid="abc",
            intent_cid="def",
        )
        
        data_dict = node.to_dict()
        
        # Verify structure unchanged
        assert "interface_cid" in data_dict
        assert "intent_cid" in data_dict
        assert "timestamps" in data_dict
        assert isinstance(data_dict["timestamps"], dict)
