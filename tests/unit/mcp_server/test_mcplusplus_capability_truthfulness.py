"""SCA-610: datasets MCP++ capability reporting is truthful."""

from __future__ import annotations

import asyncio

from ipfs_datasets_py.mcp_server.mcplusplus import bootstrap, peer_registry, task_queue


def test_bootstrap_never_succeeds_for_unimplemented_work() -> None:
    status = bootstrap.capability_status()
    assert status["reachable"] is False
    assert status["reason_codes"]
    result = asyncio.run(bootstrap.bootstrap_network())
    assert result["success"] is False
    assert result.get("peers_connected", 0) == 0
    assert "reason_codes" in result
    # Importable wrappers must not advertise success for TODO/stub paths.
    assert result["success"] is not True


def test_task_queue_available_means_self_tested_reachability() -> None:
    queue = task_queue.create_task_queue(queue_path=None)
    status = queue.capability_status()
    # Without durable queue path / verified backend, not reachable.
    assert status["reachable"] is False
    assert queue.available is False
    assert status["reason_codes"]
    # submit must fail closed
    task_id = asyncio.run(queue.submit("inference", {"prompt": "x"}))
    assert task_id is None


def test_peer_registry_empty_uninitialized_not_reachable() -> None:
    registry = peer_registry.create_peer_registry()
    status = registry.capability_status()
    # When backend import is missing or construct fails, reachable is false.
    if not status["import_ok"]:
        assert status["reachable"] is False
        assert "import_missing" in status["reason_codes"] or "backend_not_bound" in status[
            "reason_codes"
        ]
    else:
        # Import ok but no durable methods / construct => still not advertised.
        if not status["has_durable_instance"]:
            assert status["reachable"] is False
            assert status["reason_codes"]
    peers = asyncio.run(registry.discover_peers())
    assert peers == []


def test_capability_flags_equal_real_reachability_not_import_only() -> None:
    """An importable wrapper or obsolete symbol cannot advertise reachability."""

    # HAVE_* flags may be true when imports exist; available/reachable must not.
    bootstrap_status = bootstrap.capability_status()
    assert bootstrap_status["reachable"] is False or bootstrap_status["import_ok"] is True
    # If import_ok, reachable still requires self-test — currently false for stubs.
    if bootstrap_status["import_ok"]:
        assert bootstrap_status["reachable"] is False

    queue = task_queue.TaskQueueWrapper()
    # Import-only HAVE_TASK_QUEUE is not the capability flag under test.
    assert queue.available == queue.capability_status()["reachable"]
