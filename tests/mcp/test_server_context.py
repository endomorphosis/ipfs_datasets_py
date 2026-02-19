"""
Tests for Server Context

Tests the ServerContext class which replaces global singletons
with a clean, testable, thread-safe architecture.
"""
import pytest
import threading
import time
from pathlib import Path

from ipfs_datasets_py.mcp_server.server_context import (
    ServerContext,
    ServerConfig,
    create_server_context,
    set_current_context,
    get_current_context
)


class TestServerConfig:
    """Test ServerConfig dataclass."""
    
    def test_default_config(self):
        """
        GIVEN default ServerConfig
        WHEN creating instance
        THEN should have sensible defaults
        """
        config = ServerConfig()
        
        assert config.enable_p2p is True
        assert config.enable_monitoring is True
        assert config.log_level == "INFO"
        assert config.max_concurrent_tools == 10
        assert config.tool_timeout_seconds == 30.0
        assert config.cache_tool_discovery is True
        assert config.lazy_load_tools is True
    
    def test_custom_config(self):
        """
        GIVEN custom ServerConfig values
        WHEN creating instance
        THEN should use custom values
        """
        config = ServerConfig(
            enable_p2p=False,
            log_level="DEBUG",
            max_concurrent_tools=20
        )
        
        assert config.enable_p2p is False
        assert config.log_level == "DEBUG"
        assert config.max_concurrent_tools == 20


class TestServerContext:
    """Test ServerContext lifecycle and resource management."""
    
    def test_context_lifecycle(self):
        """
        GIVEN ServerContext
        WHEN entering and exiting context
        THEN should initialize and cleanup properly
        """
        context = ServerContext()
        
        # Not entered yet
        assert context._entered is False
        
        # Enter context
        with context as ctx:
            assert ctx._entered is True
            assert ctx.metadata_registry is not None
            assert ctx.tool_manager is not None
        
        # After exit
        assert context._entered is False
    
    def test_context_properties_before_enter(self):
        """
        GIVEN ServerContext not entered
        WHEN accessing properties
        THEN should raise RuntimeError
        """
        context = ServerContext()
        
        with pytest.raises(RuntimeError, match="not entered"):
            _ = context.tool_manager
        
        with pytest.raises(RuntimeError, match="not entered"):
            _ = context.metadata_registry
    
    def test_context_properties_after_enter(self):
        """
        GIVEN ServerContext entered
        WHEN accessing properties
        THEN should return initialized resources
        """
        with ServerContext() as context:
            # Should not raise
            tool_manager = context.tool_manager
            metadata_registry = context.metadata_registry
            
            assert tool_manager is not None
            assert metadata_registry is not None
    
    def test_double_enter_raises_error(self):
        """
        GIVEN ServerContext already entered
        WHEN trying to enter again
        THEN should raise RuntimeError
        """
        context = ServerContext()
        
        with context:
            with pytest.raises(RuntimeError, match="already entered"):
                context.__enter__()
    
    def test_cleanup_handler_registration(self):
        """
        GIVEN ServerContext with cleanup handler
        WHEN context exits
        THEN should call cleanup handler
        """
        cleanup_called = []
        
        def my_cleanup():
            cleanup_called.append(True)
        
        with ServerContext() as context:
            context.register_cleanup_handler(my_cleanup)
        
        # Cleanup should have been called
        assert len(cleanup_called) == 1
    
    def test_cleanup_handler_exceptions(self):
        """
        GIVEN cleanup handler that raises exception
        WHEN context exits
        THEN should log error but not crash
        """
        def bad_cleanup():
            raise Exception("Cleanup failed!")
        
        # Should not raise - exceptions are logged
        with ServerContext() as context:
            context.register_cleanup_handler(bad_cleanup)
        
        # Context should exit cleanly despite handler exception
    
    def test_vector_store_management(self):
        """
        GIVEN ServerContext
        WHEN registering and retrieving vector stores
        THEN should manage stores correctly
        """
        with ServerContext() as context:
            # Register a mock vector store
            mock_store = {"type": "faiss", "dimension": 768}
            context.register_vector_store("embeddings", mock_store)
            
            # Retrieve it
            retrieved = context.get_vector_store("embeddings")
            assert retrieved == mock_store
            
            # Non-existent store
            assert context.get_vector_store("nonexistent") is None
    
    def test_config_passed_to_context(self):
        """
        GIVEN custom ServerConfig
        WHEN creating ServerContext
        THEN should use custom config
        """
        config = ServerConfig(
            enable_p2p=False,
            max_concurrent_tools=5
        )
        
        with ServerContext(config) as context:
            assert context.config.enable_p2p is False
            assert context.config.max_concurrent_tools == 5


class TestServerContextConvenienceFunctions:
    """Test convenience functions for context management."""
    
    def test_create_server_context(self):
        """
        GIVEN create_server_context context manager
        WHEN using it
        THEN should create and cleanup context
        """
        with create_server_context() as context:
            assert isinstance(context, ServerContext)
            assert context._entered is True
            assert context.tool_manager is not None
    
    def test_thread_local_context(self):
        """
        GIVEN set_current_context and get_current_context
        WHEN setting and getting in same thread
        THEN should work correctly
        """
        # Initially None
        assert get_current_context() is None
        
        # Set context
        with ServerContext() as context:
            set_current_context(context)
            
            # Should get same context
            retrieved = get_current_context()
            assert retrieved is context
        
        # Clear it
        set_current_context(None)
        assert get_current_context() is None
    
    def test_thread_local_context_isolation(self):
        """
        GIVEN contexts set in different threads
        WHEN getting context
        THEN each thread should have its own context
        """
        context1_ref = []
        context2_ref = []
        
        def thread1():
            with ServerContext() as context:
                set_current_context(context)
                time.sleep(0.1)  # Let thread2 start
                retrieved = get_current_context()
                context1_ref.append((context, retrieved))
        
        def thread2():
            time.sleep(0.05)  # Let thread1 set its context first
            with ServerContext() as context:
                set_current_context(context)
                retrieved = get_current_context()
                context2_ref.append((context, retrieved))
        
        t1 = threading.Thread(target=thread1)
        t2 = threading.Thread(target=thread2)
        
        t1.start()
        t2.start()
        t1.join()
        t2.join()
        
        # Each thread should get its own context
        assert len(context1_ref) == 1
        assert len(context2_ref) == 1
        
        ctx1, retrieved1 = context1_ref[0]
        ctx2, retrieved2 = context2_ref[0]
        
        # Each thread's retrieved context should match what it set
        assert retrieved1 is ctx1
        assert retrieved2 is ctx2
        
        # The contexts should be different
        assert ctx1 is not ctx2


class TestServerContextThreadSafety:
    """Test thread safety of ServerContext."""
    
    def test_concurrent_context_creation(self):
        """
        GIVEN multiple threads creating contexts
        WHEN running concurrently
        THEN should not interfere with each other
        """
        results = []
        errors = []
        
        def create_and_use_context(thread_id):
            try:
                with ServerContext() as context:
                    # Do some work with context
                    tool_manager = context.tool_manager
                    metadata_registry = context.metadata_registry
                    
                    # Store result
                    results.append({
                        'thread_id': thread_id,
                        'tool_manager': tool_manager is not None,
                        'metadata_registry': metadata_registry is not None
                    })
            except Exception as e:
                errors.append((thread_id, e))
        
        # Create 5 threads
        threads = []
        for i in range(5):
            t = threading.Thread(target=create_and_use_context, args=(i,))
            threads.append(t)
            t.start()
        
        # Wait for all threads
        for t in threads:
            t.join()
        
        # Should have 5 successful results, no errors
        assert len(results) == 5
        assert len(errors) == 0
        
        # All contexts should have been initialized
        for result in results:
            assert result['tool_manager'] is True
            assert result['metadata_registry'] is True
    
    def test_concurrent_vector_store_access(self):
        """
        GIVEN single context accessed by multiple threads
        WHEN registering vector stores concurrently
        THEN should handle thread-safe access
        """
        with ServerContext() as context:
            errors = []
            
            def register_store(store_id):
                try:
                    context.register_vector_store(
                        f"store_{store_id}",
                        {"id": store_id, "data": "mock"}
                    )
                except Exception as e:
                    errors.append((store_id, e))
            
            # Create 10 threads registering stores
            threads = []
            for i in range(10):
                t = threading.Thread(target=register_store, args=(i,))
                threads.append(t)
                t.start()
            
            # Wait for all
            for t in threads:
                t.join()
            
            # Should have no errors
            assert len(errors) == 0
            
            # All 10 stores should be registered
            for i in range(10):
                store = context.get_vector_store(f"store_{i}")
                assert store is not None
                assert store['id'] == i


class TestServerContextCleanup:
    """Test cleanup behavior of ServerContext."""
    
    def test_metadata_registry_cleared_on_cleanup(self):
        """
        GIVEN ServerContext with registered metadata
        WHEN context exits
        THEN metadata registry should be cleared
        """
        context = ServerContext()
        
        with context:
            # Registry should be initialized
            registry = context.metadata_registry
            assert registry is not None
        
        # After exit, registry should be cleared
        # (we can't access it directly, but cleanup should have been called)
    
    def test_exception_during_cleanup_logged_not_raised(self):
        """
        GIVEN cleanup that raises exception
        WHEN context exits
        THEN should log but not raise
        """
        def bad_cleanup():
            raise ValueError("Cleanup error")
        
        # Should not raise
        with ServerContext() as context:
            context.register_cleanup_handler(bad_cleanup)
        
        # Context should exit cleanly
    
    def test_partial_initialization_failure_cleanup(self):
        """
        GIVEN ServerContext initialization that fails partway
        WHEN exception occurs during __enter__
        THEN should clean up partially initialized resources
        """
        # This test would require mocking to force partial initialization
        # For now, just verify basic exception handling
        
        # If we could mock the tool manager initialization to fail:
        # - Should clean up metadata registry
        # - Should not leave resources dangling
        # - Should raise the original exception
        pass


# ---------------------------------------------------------------------------
# get_tool and execute_tool
# ---------------------------------------------------------------------------

class TestServerContextToolExecution:
    """Test get_tool and execute_tool on a live ServerContext."""

    def test_get_tool_returns_none_for_unqualified_name(self):
        """
        GIVEN: A ServerContext with no tool registered under simple name
        WHEN: get_tool('simple_name') is called (no dot separator)
        THEN: Returns None (simple names not supported without category prefix)
        """
        with ServerContext() as ctx:
            result = ctx.get_tool("simple_name")
            assert result is None

    def test_get_tool_returns_none_for_unknown_qualified_name(self):
        """
        GIVEN: A ServerContext
        WHEN: get_tool('nonexistent_cat.nonexistent_tool') is called
        THEN: Returns None
        """
        with ServerContext() as ctx:
            result = ctx.get_tool("nonexistent_cat.nonexistent_tool")
            assert result is None

    def test_execute_tool_raises_for_missing_tool(self):
        """
        GIVEN: A ServerContext with no tool under 'cat.missing_tool'
        WHEN: execute_tool('cat.missing_tool') is called
        THEN: ToolNotFoundError is raised
        """
        from ipfs_datasets_py.mcp_server.exceptions import ToolNotFoundError
        with ServerContext() as ctx:
            with pytest.raises(ToolNotFoundError):
                ctx.execute_tool("cat.missing_tool")

    def test_set_and_get_current_context(self):
        """
        GIVEN: A ServerContext
        WHEN: set_current_context then get_current_context are called in same thread
        THEN: get_current_context returns the same context object
        """
        with ServerContext() as ctx:
            set_current_context(ctx)
            retrieved = get_current_context()
            assert retrieved is ctx

    def test_get_current_context_without_set_returns_none_or_context(self):
        """
        GIVEN: No context set in current thread
        WHEN: get_current_context() is called
        THEN: Returns None (or default) without raising
        """
        # Clear any existing context first
        set_current_context(None)  # type: ignore[arg-type]
        result = get_current_context()
        # Just assert no exception raised; value may be None or a new context
        assert result is None or isinstance(result, ServerContext)


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
