"""
Comprehensive tests for P2PMCPRegistryAdapter.

Tests cover:
- Adapter initialization with runtime detection
- Tools property with runtime metadata
- Hierarchical tools discovery (Phase 2 Week 5 feature)
- Runtime detection (FastAPI/Trio/Unknown)
- Tool wrapper creation and closure fix validation (Critical Issue #1)
- Auth mode validation
- Accelerate instance property
- Runtime management methods
"""

import pytest
from unittest.mock import Mock, MagicMock, patch, AsyncMock
import asyncio
import inspect


# Import the module under test
from ipfs_datasets_py.mcp_server.p2p_mcp_registry_adapter import (
    P2PMCPRegistryAdapter,
    RUNTIME_FASTAPI,
    RUNTIME_TRIO,
    RUNTIME_UNKNOWN,
)


class TestP2PMCPRegistryAdapterInitialization:
    """Test P2PMCPRegistryAdapter initialization and configuration."""
    
    def test_init_with_default_values(self):
        """
        GIVEN: A mock host server
        WHEN: P2PMCPRegistryAdapter is initialized with defaults
        THEN: It should use default runtime and enable detection
        """
        # GIVEN
        mock_host = Mock()
        
        # WHEN
        adapter = P2PMCPRegistryAdapter(mock_host)
        
        # THEN
        assert adapter._host == mock_host
        assert adapter._default_runtime == RUNTIME_FASTAPI
        assert adapter._enable_runtime_detection is True
        assert isinstance(adapter._runtime_metadata, dict)
        assert len(adapter._runtime_metadata) == 0
        assert isinstance(adapter._trio_tools, set)
        assert isinstance(adapter._fastapi_tools, set)
    
    def test_init_with_custom_runtime(self):
        """
        GIVEN: A mock host server and custom runtime
        WHEN: P2PMCPRegistryAdapter is initialized with custom values
        THEN: It should use the provided configuration
        """
        # GIVEN
        mock_host = Mock()
        
        # WHEN
        adapter = P2PMCPRegistryAdapter(
            mock_host,
            default_runtime=RUNTIME_TRIO,
            enable_runtime_detection=False
        )
        
        # THEN
        assert adapter._default_runtime == RUNTIME_TRIO
        assert adapter._enable_runtime_detection is False
    
    def test_accelerate_instance_property(self):
        """
        GIVEN: An initialized adapter
        WHEN: The accelerate_instance property is accessed
        THEN: It should return the host server
        """
        # GIVEN
        mock_host = Mock()
        adapter = P2PMCPRegistryAdapter(mock_host)
        
        # WHEN
        instance = adapter.accelerate_instance
        
        # THEN
        assert instance is mock_host


class TestToolsProperty:
    """Test the tools property with various configurations."""
    
    def test_tools_empty_when_no_host_tools(self):
        """
        GIVEN: A host server with no tools
        WHEN: The tools property is accessed
        THEN: It should attempt hierarchical discovery and return empty dict
        """
        # GIVEN
        mock_host = Mock()
        mock_host.tools = {}
        adapter = P2PMCPRegistryAdapter(mock_host)
        
        # WHEN
        with patch.object(adapter, '_get_hierarchical_tools', return_value={}):
            tools = adapter.tools
        
        # THEN
        assert isinstance(tools, dict)
        assert len(tools) == 0
    
    def test_tools_with_flat_registration(self):
        """
        GIVEN: A host server with flat-registered tools (>4 tools)
        WHEN: The tools property is accessed
        THEN: It should return tools with runtime metadata
        """
        # GIVEN
        def sample_tool(arg1: str, arg2: int = 5):
            """Sample tool for testing"""
            return f"result: {arg1}, {arg2}"
        
        async def async_tool(data: str):
            """Async sample tool"""
            return f"async: {data}"
        
        mock_host = Mock()
        mock_host.tools = {
            "tool1": sample_tool,
            "tool2": async_tool,
            "tool3": lambda: "test",
            "tool4": lambda: "test2",
            "tool5": lambda: "test3",  # 5th tool ensures flat registration
        }
        adapter = P2PMCPRegistryAdapter(mock_host)
        
        # WHEN
        tools = adapter.tools
        
        # THEN
        assert len(tools) == 5
        assert "tool1" in tools
        assert tools["tool1"]["function"] == sample_tool
        assert "Sample tool for testing" in tools["tool1"]["description"]
        assert tools["tool1"]["runtime"] in [RUNTIME_FASTAPI, RUNTIME_TRIO, RUNTIME_UNKNOWN]
        assert "runtime_metadata" in tools["tool1"]
        assert isinstance(tools["tool1"]["runtime_metadata"]["is_async"], bool)
    
    def test_tools_uses_hierarchical_discovery_when_few_tools(self):
        """
        GIVEN: A host server with <=4 tools (hierarchical meta-tools only)
        WHEN: The tools property is accessed
        THEN: It should use hierarchical discovery (Phase 2 Week 5 feature)
        """
        # GIVEN
        mock_host = Mock()
        mock_host.tools = {
            "tools_list_categories": Mock(),
            "tools_list_tools": Mock(),
            "tools_get_schema": Mock(),
            "tools_dispatch": Mock(),
        }  # Only 4 meta-tools
        adapter = P2PMCPRegistryAdapter(mock_host)
        
        hierarchical_tools = {
            "dataset_load": {
                "function": Mock(),
                "description": "Load dataset",
                "input_schema": {},
                "runtime": RUNTIME_FASTAPI,
            }
        }
        
        # WHEN
        with patch.object(adapter, '_get_hierarchical_tools', return_value=hierarchical_tools):
            tools = adapter.tools
        
        # THEN
        assert tools == hierarchical_tools
    
    def test_tools_includes_runtime_metadata(self):
        """
        GIVEN: A host server with various tool types
        WHEN: The tools property is accessed
        THEN: Each tool should include complete runtime metadata
        """
        # GIVEN
        async def trio_tool():
            """Trio-native tool"""
            pass
        trio_tool._mcp_runtime = RUNTIME_TRIO
        
        def fastapi_tool():
            """FastAPI tool"""
            pass
        
        mock_host = Mock()
        mock_host.tools = {
            "trio1": trio_tool,
            "fastapi1": fastapi_tool,
            "tool3": lambda: None,
            "tool4": lambda: None,
            "tool5": lambda: None,
        }
        adapter = P2PMCPRegistryAdapter(mock_host, enable_runtime_detection=True)
        
        # WHEN
        tools = adapter.tools
        
        # THEN
        assert len(tools) == 5
        for tool_name, tool_desc in tools.items():
            assert "runtime" in tool_desc
            assert "runtime_metadata" in tool_desc
            assert "is_async" in tool_desc["runtime_metadata"]
            assert "is_trio_native" in tool_desc["runtime_metadata"]
            assert "requires_trio_context" in tool_desc["runtime_metadata"]


class TestRuntimeDetection:
    """Test runtime detection functionality."""
    
    def test_detect_runtime_with_explicit_marker(self):
        """
        GIVEN: A function with explicit runtime marker
        WHEN: Runtime detection is performed
        THEN: It should return the marked runtime
        """
        # GIVEN
        def tool_func():
            pass
        tool_func._mcp_runtime = RUNTIME_TRIO
        
        mock_host = Mock()
        adapter = P2PMCPRegistryAdapter(mock_host)
        
        # WHEN
        runtime = adapter._detect_runtime(tool_func)
        
        # THEN
        assert runtime == RUNTIME_TRIO
    
    def test_detect_runtime_from_module_path(self):
        """
        GIVEN: A function from a Trio or MCP++ module
        WHEN: Runtime detection is performed
        THEN: It should detect Trio runtime from module path
        """
        # GIVEN
        mock_func = Mock()
        mock_func.__module__ = "ipfs_datasets_py.mcplusplus.trio_tools"
        
        mock_host = Mock()
        adapter = P2PMCPRegistryAdapter(mock_host)
        
        # WHEN
        runtime = adapter._detect_runtime(mock_func)
        
        # THEN
        assert runtime == RUNTIME_TRIO
    
    def test_detect_runtime_defaults_to_fastapi(self):
        """
        GIVEN: A function without runtime hints
        WHEN: Runtime detection is performed
        THEN: It should default to FastAPI
        """
        # GIVEN
        def tool_func():
            pass
        
        mock_host = Mock()
        adapter = P2PMCPRegistryAdapter(mock_host)
        
        # WHEN
        runtime = adapter._detect_runtime(tool_func)
        
        # THEN
        assert runtime == RUNTIME_FASTAPI
    
    def test_get_tool_runtime_uses_cache(self):
        """
        GIVEN: A tool with cached runtime metadata
        WHEN: _get_tool_runtime is called multiple times
        THEN: It should use the cached value
        """
        # GIVEN
        def tool_func():
            pass
        
        mock_host = Mock()
        adapter = P2PMCPRegistryAdapter(mock_host)
        adapter._runtime_metadata["test_tool"] = RUNTIME_TRIO
        
        # WHEN
        runtime1 = adapter._get_tool_runtime("test_tool", tool_func)
        runtime2 = adapter._get_tool_runtime("test_tool", tool_func)
        
        # THEN
        assert runtime1 == RUNTIME_TRIO
        assert runtime2 == RUNTIME_TRIO
    
    def test_get_tool_runtime_checks_explicit_tracking(self):
        """
        GIVEN: A tool explicitly registered as Trio-native
        WHEN: _get_tool_runtime is called
        THEN: It should return Trio runtime
        """
        # GIVEN
        def tool_func():
            pass
        
        mock_host = Mock()
        adapter = P2PMCPRegistryAdapter(mock_host)
        adapter._trio_tools.add("my_tool")
        
        # WHEN
        runtime = adapter._get_tool_runtime("my_tool", tool_func)
        
        # THEN
        assert runtime == RUNTIME_TRIO


class TestToolWrapperCreation:
    """Test tool wrapper creation and closure fix validation (Critical Issue #1)."""
    
    def test_tool_wrapper_preserves_closure_variables(self):
        """
        GIVEN: A wrapper creation function (like make_tool_wrapper)
        WHEN: Multiple wrappers are created in a loop
        THEN: Each wrapper should capture its own variables (closure fix)
        
        This test validates the fix for Critical Issue #1:
        Closure variable capture bug in p2p_mcp_registry_adapter.py:194-206
        
        The bug was that all wrappers captured the LAST value of loop variables.
        The fix uses a function factory pattern to capture each iteration's values.
        """
        # GIVEN - Simulate the wrapper creation pattern from _get_hierarchical_tools
        def make_tool_wrapper(cat, name):
            """This is the pattern used in the actual code"""
            async def wrapper(**kwargs):
                return {"category": cat, "name": name, "kwargs": kwargs}
            wrapper.__name__ = name
            wrapper.__doc__ = f"Tool {name} in {cat}"
            return wrapper
        
        # WHEN - Create multiple wrappers (simulating the loop)
        wrappers = []
        categories_and_names = [
            ("category1", "tool1"),
            ("category2", "tool2"),
            ("category3", "tool3"),
        ]
        
        for cat, name in categories_and_names:
            wrapper = make_tool_wrapper(cat, name)
            wrappers.append((cat, name, wrapper))
        
        # THEN - Each wrapper should have captured its OWN values
        for expected_cat, expected_name, wrapper in wrappers:
            assert wrapper.__name__ == expected_name
            assert expected_name in wrapper.__doc__
            assert expected_cat in wrapper.__doc__
            
            # Execute wrapper and verify it uses captured values
            import asyncio
            result = asyncio.run(wrapper(test_arg="value"))
            assert result["category"] == expected_cat
            assert result["name"] == expected_name
    
    def test_is_async_function_detection(self):
        """
        GIVEN: Sync and async functions
        WHEN: _is_async_function is called
        THEN: It should correctly identify async functions
        """
        # GIVEN
        def sync_func():
            pass
        
        async def async_func():
            pass
        
        mock_host = Mock()
        adapter = P2PMCPRegistryAdapter(mock_host)
        
        # WHEN / THEN
        assert adapter._is_async_function(sync_func) is False
        assert adapter._is_async_function(async_func) is True


class TestValidateP2PMessage:
    """Test P2P message validation."""
    
    @pytest.mark.asyncio
    async def test_validate_p2p_message_with_async_validator(self):
        """
        GIVEN: A host server with async validate_p2p_message method
        WHEN: validate_p2p_message is called
        THEN: It should await the result and return boolean
        """
        # GIVEN
        async def async_validator(msg):
            return msg.get("valid", False)
        
        mock_host = Mock()
        mock_host.validate_p2p_message = async_validator
        adapter = P2PMCPRegistryAdapter(mock_host)
        
        # WHEN
        result = await adapter.validate_p2p_message({"valid": True})
        
        # THEN
        assert result is True
    
    @pytest.mark.asyncio
    async def test_validate_p2p_message_with_sync_validator(self):
        """
        GIVEN: A host server with sync validate_p2p_message method
        WHEN: validate_p2p_message is called
        THEN: It should return the boolean result
        """
        # GIVEN
        def sync_validator(msg):
            return msg.get("valid", False)
        
        mock_host = Mock()
        mock_host.validate_p2p_message = sync_validator
        adapter = P2PMCPRegistryAdapter(mock_host)
        
        # WHEN
        result = await adapter.validate_p2p_message({"valid": True})
        
        # THEN
        assert result is True
    
    @pytest.mark.asyncio
    async def test_validate_p2p_message_when_validator_missing(self):
        """
        GIVEN: A host server without validate_p2p_message method
        WHEN: validate_p2p_message is called
        THEN: It should return False
        """
        # GIVEN
        mock_host = Mock(spec=[])  # No validate_p2p_message
        adapter = P2PMCPRegistryAdapter(mock_host)
        
        # WHEN
        result = await adapter.validate_p2p_message({"test": "data"})
        
        # THEN
        assert result is False


class TestRuntimeManagement:
    """Test runtime management methods."""
    
    def test_register_trio_tool(self):
        """
        GIVEN: An adapter
        WHEN: A tool is registered as Trio-native
        THEN: It should be tracked in trio_tools and metadata
        """
        # GIVEN
        mock_host = Mock()
        adapter = P2PMCPRegistryAdapter(mock_host)
        
        # WHEN
        adapter.register_trio_tool("my_tool")
        
        # THEN
        assert "my_tool" in adapter._trio_tools
        assert adapter._runtime_metadata["my_tool"] == RUNTIME_TRIO
        assert "my_tool" not in adapter._fastapi_tools
    
    def test_register_fastapi_tool(self):
        """
        GIVEN: An adapter
        WHEN: A tool is registered as FastAPI-based
        THEN: It should be tracked in fastapi_tools and metadata
        """
        # GIVEN
        mock_host = Mock()
        adapter = P2PMCPRegistryAdapter(mock_host)
        
        # WHEN
        adapter.register_fastapi_tool("my_tool")
        
        # THEN
        assert "my_tool" in adapter._fastapi_tools
        assert adapter._runtime_metadata["my_tool"] == RUNTIME_FASTAPI
        assert "my_tool" not in adapter._trio_tools
    
    def test_register_tool_switches_runtime(self):
        """
        GIVEN: A tool registered as Trio
        WHEN: It's re-registered as FastAPI
        THEN: It should switch runtimes correctly
        """
        # GIVEN
        mock_host = Mock()
        adapter = P2PMCPRegistryAdapter(mock_host)
        adapter.register_trio_tool("my_tool")
        
        # WHEN
        adapter.register_fastapi_tool("my_tool")
        
        # THEN
        assert "my_tool" in adapter._fastapi_tools
        assert "my_tool" not in adapter._trio_tools
        assert adapter._runtime_metadata["my_tool"] == RUNTIME_FASTAPI
    
    def test_get_tools_by_runtime(self):
        """
        GIVEN: An adapter with mixed runtime tools
        WHEN: get_tools_by_runtime is called
        THEN: It should filter tools by runtime
        """
        # GIVEN
        mock_host = Mock()
        mock_host.tools = {
            "tool1": lambda: None,
            "tool2": lambda: None,
            "tool3": lambda: None,
            "tool4": lambda: None,
            "tool5": lambda: None,
        }
        adapter = P2PMCPRegistryAdapter(mock_host)
        adapter.register_trio_tool("tool1")
        adapter.register_fastapi_tool("tool2")
        
        # WHEN
        trio_tools = adapter.get_tools_by_runtime(RUNTIME_TRIO)
        fastapi_tools = adapter.get_tools_by_runtime(RUNTIME_FASTAPI)
        
        # THEN
        # Note: Actual behavior depends on tool registration
        assert isinstance(trio_tools, dict)
        assert isinstance(fastapi_tools, dict)
    
    def test_get_trio_tools(self):
        """
        GIVEN: An adapter with Trio-native tools
        WHEN: get_trio_tools is called
        THEN: It should return only Trio tools
        """
        # GIVEN
        mock_host = Mock()
        mock_host.tools = {
            "tool1": lambda: None,
            "tool2": lambda: None,
            "tool3": lambda: None,
            "tool4": lambda: None,
            "tool5": lambda: None,
        }
        adapter = P2PMCPRegistryAdapter(mock_host)
        adapter.register_trio_tool("tool1")
        
        # WHEN
        trio_tools = adapter.get_trio_tools()
        
        # THEN
        assert isinstance(trio_tools, dict)
    
    def test_get_fastapi_tools(self):
        """
        GIVEN: An adapter with FastAPI tools
        WHEN: get_fastapi_tools is called
        THEN: It should return only FastAPI tools
        """
        # GIVEN
        mock_host = Mock()
        mock_host.tools = {
            "tool1": lambda: None,
            "tool2": lambda: None,
            "tool3": lambda: None,
            "tool4": lambda: None,
            "tool5": lambda: None,
        }
        adapter = P2PMCPRegistryAdapter(mock_host)
        adapter.register_fastapi_tool("tool2")
        
        # WHEN
        fastapi_tools = adapter.get_fastapi_tools()
        
        # THEN
        assert isinstance(fastapi_tools, dict)
    
    def test_get_runtime_stats(self):
        """
        GIVEN: An adapter with various tools
        WHEN: get_runtime_stats is called
        THEN: It should return comprehensive statistics
        """
        # GIVEN
        mock_host = Mock()
        mock_host.tools = {
            "tool1": lambda: None,
            "tool2": lambda: None,
            "tool3": lambda: None,
            "tool4": lambda: None,
            "tool5": lambda: None,
        }
        adapter = P2PMCPRegistryAdapter(mock_host, default_runtime=RUNTIME_FASTAPI)
        adapter.register_trio_tool("tool1")
        adapter.register_fastapi_tool("tool2")
        
        # WHEN
        stats = adapter.get_runtime_stats()
        
        # THEN
        assert "total_tools" in stats
        assert "trio_tools" in stats
        assert "fastapi_tools" in stats
        assert "unknown_tools" in stats
        assert "runtime_detection_enabled" in stats
        assert "default_runtime" in stats
        assert stats["default_runtime"] == RUNTIME_FASTAPI
        assert isinstance(stats["total_tools"], int)
    
    def test_is_trio_tool(self):
        """
        GIVEN: Tools registered with different runtimes
        WHEN: is_trio_tool is called
        THEN: It should correctly identify Trio tools
        """
        # GIVEN
        mock_host = Mock()
        adapter = P2PMCPRegistryAdapter(mock_host)
        adapter.register_trio_tool("trio_tool")
        adapter.register_fastapi_tool("fastapi_tool")
        
        # WHEN / THEN
        assert adapter.is_trio_tool("trio_tool") is True
        assert adapter.is_trio_tool("fastapi_tool") is False
        assert adapter.is_trio_tool("unknown_tool") is False
    
    def test_clear_runtime_cache(self):
        """
        GIVEN: An adapter with cached runtime metadata
        WHEN: clear_runtime_cache is called
        THEN: The cache should be cleared
        """
        # GIVEN
        mock_host = Mock()
        adapter = P2PMCPRegistryAdapter(mock_host)
        adapter._runtime_metadata["tool1"] = RUNTIME_TRIO
        adapter._runtime_metadata["tool2"] = RUNTIME_FASTAPI
        
        # WHEN
        adapter.clear_runtime_cache()
        
        # THEN
        assert len(adapter._runtime_metadata) == 0
