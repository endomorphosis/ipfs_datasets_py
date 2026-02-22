"""Unit tests for p2p_workflow_tools (Phase B2).

All tools return a dict when the P2P scheduler is unavailable (no external
deps required).  Tests verify the return-type contract and graceful
degradation path.
"""
from __future__ import annotations

import asyncio
import pytest

from ipfs_datasets_py.mcp_server.tools.p2p_workflow_tools.p2p_workflow_tools import (
    initialize_p2p_scheduler,
    schedule_p2p_workflow,
    get_next_p2p_workflow,
    add_p2p_peer,
    remove_p2p_peer,
    get_p2p_scheduler_status,
    calculate_peer_distance,
    get_workflow_tags,
    get_assigned_workflows,
)


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ---------------------------------------------------------------------------
# initialize_p2p_scheduler
# ---------------------------------------------------------------------------

class TestInitializeP2pScheduler:
    def test_returns_dict(self):
        result = _run(initialize_p2p_scheduler())
        assert isinstance(result, dict)

    def test_has_success_key(self):
        result = _run(initialize_p2p_scheduler())
        assert "success" in result

    def test_peer_id_param_accepted(self):
        result = _run(initialize_p2p_scheduler(peer_id="test-peer"))
        assert isinstance(result, dict)

    def test_peers_list_accepted(self):
        result = _run(initialize_p2p_scheduler(peers=["p1", "p2"]))
        assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# schedule_p2p_workflow
# ---------------------------------------------------------------------------

class TestScheduleP2pWorkflow:
    def test_returns_dict(self):
        result = _run(schedule_p2p_workflow(
            workflow_id="wf-1",
            name="Test Workflow",
            tags=["p2p_eligible"],
        ))
        assert isinstance(result, dict)

    def test_has_success_or_error_key(self):
        result = _run(schedule_p2p_workflow(
            workflow_id="wf-2",
            name="My Workflow",
            tags=["code_gen"],
            priority=2.0,
        ))
        assert "success" in result or "error" in result

    def test_metadata_accepted(self):
        result = _run(schedule_p2p_workflow(
            workflow_id="wf-3",
            name="Workflow with Metadata",
            tags=["web_scrape"],
            metadata={"author": "test"},
        ))
        assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# get_next_p2p_workflow
# ---------------------------------------------------------------------------

class TestGetNextP2pWorkflow:
    def test_returns_dict(self):
        result = _run(get_next_p2p_workflow())
        assert isinstance(result, dict)

    def test_has_success_or_workflow_key(self):
        result = _run(get_next_p2p_workflow())
        assert "success" in result or "workflow" in result or "error" in result


# ---------------------------------------------------------------------------
# Peer management
# ---------------------------------------------------------------------------

class TestP2pPeerManagement:
    def test_add_peer_returns_dict(self):
        result = _run(add_p2p_peer(peer_id="QmPeer1"))
        assert isinstance(result, dict)

    def test_remove_peer_returns_dict(self):
        result = _run(remove_p2p_peer(peer_id="QmPeer1"))
        assert isinstance(result, dict)

    def test_add_peer_with_address(self):
        result = _run(add_p2p_peer(peer_id="QmPeer2"))
        assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# Status / utility
# ---------------------------------------------------------------------------

class TestP2pSchedulerStatus:
    def test_returns_dict(self):
        result = _run(get_p2p_scheduler_status())
        assert isinstance(result, dict)

    def test_has_success_or_status_key(self):
        result = _run(get_p2p_scheduler_status())
        assert "success" in result or "status" in result or "error" in result


class TestCalculatePeerDistance:
    def test_returns_dict(self):
        result = _run(calculate_peer_distance(hash1="abc123", hash2="def456"))
        assert isinstance(result, dict)

    def test_has_distance_or_error_key(self):
        result = _run(calculate_peer_distance(hash1="abc123", hash2="def456"))
        assert "distance" in result or "success" in result or "error" in result


class TestGetWorkflowTags:
    def test_returns_dict(self):
        result = _run(get_workflow_tags())
        assert isinstance(result, dict)

    def test_has_tags_or_error_key(self):
        result = _run(get_workflow_tags())
        assert "tags" in result or "success" in result or "error" in result


class TestGetAssignedWorkflows:
    def test_returns_dict(self):
        result = _run(get_assigned_workflows())
        assert isinstance(result, dict)

    def test_has_workflows_or_error_key(self):
        result = _run(get_assigned_workflows())
        assert "workflows" in result or "success" in result or "error" in result
