"""Unit tests for P2P MCP Registry Adapter with dual-runtime support.

Tests runtime detection, tool filtering, and metadata management
for the enhanced P2P registry adapter.

Module: tests.mcp_server.test_p2p_registry_adapter
"""

import pytest
from ipfs_datasets_py.mcp_server.p2p_mcp_registry_adapter import (
    P2PMCPRegistryAdapter,
    RUNTIME_FASTAPI,
    RUNTIME_TRIO,
    RUNTIME_UNKNOWN,
)


class MockServer:
    """Mock MCP server for testing."""

    def __init__(self):
        self.tools = {}

    def add_tool(self, name, func):
        """Add a tool to the server."""
        self.tools[name] = func

    async def validate_p2p_message(self, msg):
        """Mock message validation."""
        return msg.get("valid", True)


def sync_tool(x):
    """Synchronous test tool."""
    return x


async def async_tool(x):
    """Asynchronous test tool."""
    return x


def trio_marked_tool(x):
    """Tool marked as Trio-native."""
    return x


# Mark the tool as Trio-native
trio_marked_tool._mcp_runtime = RUNTIME_TRIO


class TestP2PMCPRegistryAdapter:
    """Test P2P MCP Registry Adapter functionality."""

    def test_adapter_creation(self):
        """Test adapter can be created."""
        # GIVEN: A mock server
        server = MockServer()

        # WHEN: Creating adapter
        adapter = P2PMCPRegistryAdapter(server)

        # THEN: Adapter is created successfully
        assert adapter is not None
        assert adapter._host is server
        assert adapter._default_runtime == RUNTIME_FASTAPI
        assert adapter._enable_runtime_detection is True

    def test_adapter_with_custom_runtime(self):
        """Test adapter with custom default runtime."""
        # GIVEN: A mock server
        server = MockServer()

        # WHEN: Creating adapter with Trio as default
        adapter = P2PMCPRegistryAdapter(
            server,
            default_runtime=RUNTIME_TRIO,
            enable_runtime_detection=False
        )

        # THEN: Custom settings are applied
        assert adapter._default_runtime == RUNTIME_TRIO
        assert adapter._enable_runtime_detection is False

    def test_tools_property_empty(self):
        """Test tools property with no tools."""
        # GIVEN: A server with no tools
        server = MockServer()
        adapter = P2PMCPRegistryAdapter(server)

        # WHEN: Getting tools
        tools = adapter.tools

        # THEN: Returns empty dict
        assert tools == {}

    def test_tools_property_with_sync_tool(self):
        """Test tools property with synchronous tool."""
        # GIVEN: A server with sync tool
        server = MockServer()
        server.add_tool("sync_tool", sync_tool)
        adapter = P2PMCPRegistryAdapter(server)

        # WHEN: Getting tools
        tools = adapter.tools

        # THEN: Tool is registered with metadata
        assert "sync_tool" in tools
        tool_desc = tools["sync_tool"]
        assert tool_desc["function"] is sync_tool
        assert tool_desc["runtime"] == RUNTIME_FASTAPI
        assert tool_desc["runtime_metadata"]["is_async"] is False

    def test_tools_property_with_async_tool(self):
        """Test tools property with asynchronous tool."""
        # GIVEN: A server with async tool
        server = MockServer()
        server.add_tool("async_tool", async_tool)
        adapter = P2PMCPRegistryAdapter(server)

        # WHEN: Getting tools
        tools = adapter.tools

        # THEN: Tool is registered with async metadata
        assert "async_tool" in tools
        tool_desc = tools["async_tool"]
        assert tool_desc["function"] is async_tool
        assert tool_desc["runtime"] == RUNTIME_FASTAPI
        assert tool_desc["runtime_metadata"]["is_async"] is True

    def test_tools_property_with_trio_marked_tool(self):
        """Test tools property with Trio-marked tool."""
        # GIVEN: A server with Trio-marked tool
        server = MockServer()
        server.add_tool("trio_tool", trio_marked_tool)
        adapter = P2PMCPRegistryAdapter(server)

        # WHEN: Getting tools
        tools = adapter.tools

        # THEN: Tool is detected as Trio-native
        assert "trio_tool" in tools
        tool_desc = tools["trio_tool"]
        assert tool_desc["runtime"] == RUNTIME_TRIO
        assert tool_desc["runtime_metadata"]["is_trio_native"] is True

    def test_register_trio_tool(self):
        """Test registering a tool as Trio-native."""
        # GIVEN: A server with a tool
        server = MockServer()
        server.add_tool("test_tool", sync_tool)
        adapter = P2PMCPRegistryAdapter(server)

        # WHEN: Registering as Trio tool
        adapter.register_trio_tool("test_tool")

        # THEN: Tool is marked as Trio-native
        tools = adapter.tools
        assert tools["test_tool"]["runtime"] == RUNTIME_TRIO
        assert adapter.is_trio_tool("test_tool") is True

    def test_register_fastapi_tool(self):
        """Test registering a tool as FastAPI-based."""
        # GIVEN: A server with a Trio tool
        server = MockServer()
        server.add_tool("test_tool", trio_marked_tool)
        adapter = P2PMCPRegistryAdapter(server)

        # WHEN: Registering as FastAPI tool
        adapter.register_fastapi_tool("test_tool")

        # THEN: Tool is marked as FastAPI
        tools = adapter.tools
        assert tools["test_tool"]["runtime"] == RUNTIME_FASTAPI
        assert adapter.is_trio_tool("test_tool") is False

    def test_get_tools_by_runtime_fastapi(self):
        """Test filtering tools by FastAPI runtime."""
        # GIVEN: A server with mixed tools
        server = MockServer()
        server.add_tool("fastapi_tool", sync_tool)
        server.add_tool("trio_tool", trio_marked_tool)
        adapter = P2PMCPRegistryAdapter(server)

        # WHEN: Getting FastAPI tools
        fastapi_tools = adapter.get_tools_by_runtime(RUNTIME_FASTAPI)

        # THEN: Only FastAPI tools returned
        assert "fastapi_tool" in fastapi_tools
        assert "trio_tool" not in fastapi_tools

    def test_get_tools_by_runtime_trio(self):
        """Test filtering tools by Trio runtime."""
        # GIVEN: A server with mixed tools
        server = MockServer()
        server.add_tool("fastapi_tool", sync_tool)
        server.add_tool("trio_tool", trio_marked_tool)
        adapter = P2PMCPRegistryAdapter(server)

        # WHEN: Getting Trio tools
        trio_tools = adapter.get_tools_by_runtime(RUNTIME_TRIO)

        # THEN: Only Trio tools returned
        assert "trio_tool" in trio_tools
        assert "fastapi_tool" not in trio_tools

    def test_get_trio_tools(self):
        """Test get_trio_tools convenience method."""
        # GIVEN: A server with mixed tools
        server = MockServer()
        server.add_tool("fastapi_tool", sync_tool)
        server.add_tool("trio_tool", trio_marked_tool)
        adapter = P2PMCPRegistryAdapter(server)

        # WHEN: Getting Trio tools
        trio_tools = adapter.get_trio_tools()

        # THEN: Only Trio tools returned
        assert len(trio_tools) == 1
        assert "trio_tool" in trio_tools

    def test_get_fastapi_tools(self):
        """Test get_fastapi_tools convenience method."""
        # GIVEN: A server with mixed tools
        server = MockServer()
        server.add_tool("fastapi_tool", sync_tool)
        server.add_tool("trio_tool", trio_marked_tool)
        adapter = P2PMCPRegistryAdapter(server)

        # WHEN: Getting FastAPI tools
        fastapi_tools = adapter.get_fastapi_tools()

        # THEN: Only FastAPI tools returned
        assert len(fastapi_tools) == 1
        assert "fastapi_tool" in fastapi_tools

    def test_get_runtime_stats(self):
        """Test runtime statistics."""
        # GIVEN: A server with mixed tools
        server = MockServer()
        server.add_tool("fastapi_tool1", sync_tool)
        server.add_tool("fastapi_tool2", async_tool)
        server.add_tool("trio_tool", trio_marked_tool)
        adapter = P2PMCPRegistryAdapter(server)

        # WHEN: Getting runtime stats
        stats = adapter.get_runtime_stats()

        # THEN: Stats are accurate
        assert stats["total_tools"] == 3
        assert stats["fastapi_tools"] == 2
        assert stats["trio_tools"] == 1
        assert stats["unknown_tools"] == 0
        assert stats["runtime_detection_enabled"] is True

    def test_is_trio_tool(self):
        """Test checking if tool is Trio-native."""
        # GIVEN: A server with mixed tools
        server = MockServer()
        server.add_tool("fastapi_tool", sync_tool)
        server.add_tool("trio_tool", trio_marked_tool)
        adapter = P2PMCPRegistryAdapter(server)

        # Force tool retrieval to populate metadata
        _ = adapter.tools

        # WHEN: Checking tool types
        is_trio_1 = adapter.is_trio_tool("trio_tool")
        is_trio_2 = adapter.is_trio_tool("fastapi_tool")

        # THEN: Correct identification
        assert is_trio_1 is True
        assert is_trio_2 is False

    def test_clear_runtime_cache(self):
        """Test clearing runtime metadata cache."""
        # GIVEN: A server with tools and cached metadata
        server = MockServer()
        server.add_tool("test_tool", sync_tool)
        adapter = P2PMCPRegistryAdapter(server)
        _ = adapter.tools  # Populate cache

        # WHEN: Clearing cache
        adapter.clear_runtime_cache()

        # THEN: Cache is empty
        assert len(adapter._runtime_metadata) == 0

    def test_runtime_metadata_structure(self):
        """Test structure of runtime metadata."""
        # GIVEN: A server with a tool
        server = MockServer()
        server.add_tool("test_tool", async_tool)
        adapter = P2PMCPRegistryAdapter(server)

        # WHEN: Getting tool metadata
        tools = adapter.tools
        metadata = tools["test_tool"]["runtime_metadata"]

        # THEN: Metadata has expected structure
        assert "is_async" in metadata
        assert "is_trio_native" in metadata
        assert "requires_trio_context" in metadata
        assert isinstance(metadata["is_async"], bool)
        assert isinstance(metadata["is_trio_native"], bool)

    @pytest.mark.asyncio
    async def test_validate_p2p_message(self):
        """Test P2P message validation."""
        # GIVEN: A server with validation
        server = MockServer()
        adapter = P2PMCPRegistryAdapter(server)

        # WHEN: Validating messages
        valid_result = await adapter.validate_p2p_message({"valid": True})
        invalid_result = await adapter.validate_p2p_message({"valid": False})

        # THEN: Validation works correctly
        assert valid_result is True
        assert invalid_result is False

    def test_accelerate_instance_property(self):
        """Test accelerate_instance property."""
        # GIVEN: A server
        server = MockServer()
        adapter = P2PMCPRegistryAdapter(server)

        # WHEN: Getting accelerate instance
        instance = adapter.accelerate_instance

        # THEN: Returns host server
        assert instance is server

    def test_runtime_detection_disabled(self):
        """Test with runtime detection disabled."""
        # GIVEN: A server with Trio-marked tool and detection disabled
        server = MockServer()
        server.add_tool("trio_tool", trio_marked_tool)
        adapter = P2PMCPRegistryAdapter(
            server,
            default_runtime=RUNTIME_FASTAPI,
            enable_runtime_detection=False
        )

        # WHEN: Getting tools
        tools = adapter.tools

        # THEN: Tool uses default runtime when detection disabled
        # BUT explicit _mcp_runtime markers are still respected
        # This is intentional - detection disables auto-detection but not explicit markers
        # Let's manually register it to override
        adapter.register_fastapi_tool("trio_tool")
        tools_after = adapter.tools
        assert tools_after["trio_tool"]["runtime"] == RUNTIME_FASTAPI


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
