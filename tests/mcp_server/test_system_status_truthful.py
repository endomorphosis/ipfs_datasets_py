import pytest


@pytest.mark.anyio
async def test_system_status_is_not_fabricated():
    from ipfs_datasets_py.mcp_server.tools.bespoke_tools.system_status import system_status

    status = await system_status()

    assert status["success"] is True
    assert status["overall_status"] in {"unknown", "healthy", "degraded"}

    # No hard-coded peer counts.
    assert status["network"]["ipfs_swarm"]["connected_peers"] is None
    assert status["network"]["ipfs_swarm"]["listening_addresses"] is None

    # Avoid made-up PIDs for external services; only current process PID may be present.
    assert "pid" not in status["services"]["ipfs_daemon"]
    assert isinstance(status["services"]["mcp_server"]["current_process_pid"], int)
    assert status["services"]["mcp_server"]["current_process_pid"] > 0

    # Avoid claiming tools_count unless it is actually known.
    assert status["network"]["api_endpoints"]["mcp_server"]["tools_count"] is None
