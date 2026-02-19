"""
Tests for global singleton refactoring to ServerContext pattern.

This test suite validates that all global singletons can now use ServerContext
while maintaining backward compatibility with existing code.

Module: tests/mcp/test_global_singleton_refactoring.py
"""

import pytest
from unittest.mock import Mock, patch
from ipfs_datasets_py.mcp_server.server_context import ServerContext
from ipfs_datasets_py.mcp_server.hierarchical_tool_manager import (
    get_tool_manager,
    HierarchicalToolManager
)
from ipfs_datasets_py.mcp_server.tool_metadata import (
    get_registry,
    ToolMetadataRegistry
)


class TestHierarchicalToolManagerRefactoring:
    """Test hierarchical_tool_manager.py refactoring."""
    
    def test_get_tool_manager_without_context_uses_global(self):
        """
        GIVEN: No ServerContext provided
        WHEN: Calling get_tool_manager()
        THEN: Returns global instance (backward compatibility)
        """
        # WHEN
        manager = get_tool_manager()
        
        # THEN
        assert manager is not None
        assert isinstance(manager, HierarchicalToolManager)
        
        # Should return same instance on subsequent calls
        manager2 = get_tool_manager()
        assert manager is manager2
    
    def test_get_tool_manager_with_context_uses_context(self):
        """
        GIVEN: ServerContext provided
        WHEN: Calling get_tool_manager(context)
        THEN: Returns context's tool_manager
        """
        # GIVEN
        with ServerContext() as context:
            # WHEN
            manager = get_tool_manager(context)
            
            # THEN
            assert manager is not None
            assert isinstance(manager, HierarchicalToolManager)
            assert manager is context.tool_manager
    
    def test_get_tool_manager_context_isolation(self):
        """
        GIVEN: Multiple ServerContext instances
        WHEN: Getting tool managers from each
        THEN: Each context has its own isolated manager
        """
        # GIVEN
        with ServerContext() as ctx1:
            with ServerContext() as ctx2:
                # WHEN
                manager1 = get_tool_manager(ctx1)
                manager2 = get_tool_manager(ctx2)
                
                # THEN
                assert manager1 is not manager2
                assert manager1 is ctx1.tool_manager
                assert manager2 is ctx2.tool_manager


class TestToolMetadataRefactoring:
    """Test tool_metadata.py refactoring."""
    
    def test_get_registry_without_context_uses_global(self):
        """
        GIVEN: No ServerContext provided
        WHEN: Calling get_registry()
        THEN: Returns global instance (backward compatibility)
        """
        # WHEN
        registry = get_registry()
        
        # THEN
        assert registry is not None
        assert isinstance(registry, ToolMetadataRegistry)
        
        # Should return same instance on subsequent calls
        registry2 = get_registry()
        assert registry is registry2
    
    def test_get_registry_with_context_uses_context(self):
        """
        GIVEN: ServerContext provided
        WHEN: Calling get_registry(context)
        THEN: Returns context's metadata_registry
        """
        # GIVEN
        with ServerContext() as context:
            # WHEN
            registry = get_registry(context)
            
            # THEN
            assert registry is not None
            assert isinstance(registry, ToolMetadataRegistry)
            assert registry is context.metadata_registry
    
    def test_get_registry_context_isolation(self):
        """
        GIVEN: Multiple ServerContext instances
        WHEN: Getting registries from each
        THEN: Each context has its own isolated registry
        """
        # GIVEN
        with ServerContext() as ctx1:
            with ServerContext() as ctx2:
                # WHEN
                registry1 = get_registry(ctx1)
                registry2 = get_registry(ctx2)
                
                # THEN
                assert registry1 is not registry2
                assert registry1 is ctx1.metadata_registry
                assert registry2 is ctx2.metadata_registry


class TestWorkflowSchedulerRefactoring:
    """Test mcplusplus/workflow_scheduler.py refactoring."""
    
    def test_get_scheduler_without_context_uses_global(self):
        """
        GIVEN: No ServerContext provided
        WHEN: Calling get_scheduler()
        THEN: Uses global MCP++ scheduler (backward compatibility)
        """
        from ipfs_datasets_py.mcp_server.mcplusplus.workflow_scheduler import (
            get_scheduler,
            HAVE_WORKFLOW_SCHEDULER
        )
        
        # WHEN
        scheduler = get_scheduler()
        
        # THEN
        if HAVE_WORKFLOW_SCHEDULER:
            # If MCP++ available, should return scheduler
            assert scheduler is not None
        else:
            # If MCP++ not available, should return None
            assert scheduler is None
    
    def test_get_scheduler_with_context_uses_context(self):
        """
        GIVEN: ServerContext with workflow_scheduler set
        WHEN: Calling get_scheduler(context)
        THEN: Returns context's workflow_scheduler
        """
        from ipfs_datasets_py.mcp_server.mcplusplus.workflow_scheduler import (
            get_scheduler
        )
        
        # GIVEN
        with ServerContext() as context:
            # Mock scheduler
            mock_scheduler = Mock()
            context.workflow_scheduler = mock_scheduler
            
            # WHEN
            scheduler = get_scheduler(context)
            
            # THEN
            assert scheduler is mock_scheduler
    
    def test_create_workflow_scheduler_with_context_stores_in_context(self):
        """
        GIVEN: ServerContext provided to create_workflow_scheduler
        WHEN: Creating a scheduler
        THEN: Scheduler is stored in context.workflow_scheduler
        """
        from ipfs_datasets_py.mcp_server.mcplusplus.workflow_scheduler import (
            create_workflow_scheduler,
            HAVE_WORKFLOW_SCHEDULER
        )
        
        if not HAVE_WORKFLOW_SCHEDULER:
            pytest.skip("MCP++ workflow scheduler not available")
        
        # GIVEN
        with ServerContext() as context:
            # WHEN
            scheduler = create_workflow_scheduler(context=context)
            
            # THEN
            if scheduler is not None:
                assert context.workflow_scheduler is scheduler


class TestVectorToolsSharedStateRefactoring:
    """Test tools/vector_tools/shared_state.py refactoring."""
    
    @pytest.mark.asyncio
    @pytest.mark.skip(reason="Vector tools require anyio dependency - tested separately")
    async def test_get_global_manager_without_context_uses_global(self):
        """
        GIVEN: No ServerContext provided
        WHEN: Calling get_global_manager()
        THEN: Uses global manager (backward compatibility)
        """
        from ipfs_datasets_py.mcp_server.tools.vector_tools.shared_state import (
            get_global_manager
        )
        
        # WHEN
        result = await get_global_manager()
        
        # THEN
        assert result is not None
        assert isinstance(result, dict)
        assert result.get("status") in ["success", "error"]
    
    @pytest.mark.asyncio
    @pytest.mark.skip(reason="Vector tools require anyio dependency - tested separately")
    async def test_get_global_manager_with_context_uses_context(self):
        """
        GIVEN: ServerContext provided
        WHEN: Calling get_global_manager(context)
        THEN: Uses context's vector stores
        """
        from ipfs_datasets_py.mcp_server.tools.vector_tools.shared_state import (
            get_global_manager
        )
        
        # GIVEN
        with ServerContext() as context:
            # WHEN
            result = await get_global_manager(context)
            
            # THEN
            assert result is not None
            assert isinstance(result, dict)
            assert result["status"] == "success"
            assert "ServerContext" in result["message"]
            assert result["manager_available"] is True


class TestBackwardCompatibility:
    """Test that refactored functions maintain backward compatibility."""
    
    def test_existing_code_without_context_still_works(self):
        """
        GIVEN: Existing code that doesn't use ServerContext
        WHEN: Calling refactored functions without context parameter
        THEN: All functions work correctly (backward compatibility)
        """
        # Import functions as existing code would
        from ipfs_datasets_py.mcp_server.hierarchical_tool_manager import get_tool_manager
        from ipfs_datasets_py.mcp_server.tool_metadata import get_registry
        from ipfs_datasets_py.mcp_server.mcplusplus.workflow_scheduler import get_scheduler
        
        # Call without context (old pattern)
        manager = get_tool_manager()
        registry = get_registry()
        scheduler = get_scheduler()
        
        # Should all return valid objects (or None for optional components)
        assert manager is not None
        assert registry is not None
        # scheduler may be None if MCP++ not installed
    
    def test_new_code_with_context_works(self):
        """
        GIVEN: New code using ServerContext pattern
        WHEN: Calling refactored functions with context parameter
        THEN: All functions use context's resources
        """
        from ipfs_datasets_py.mcp_server.hierarchical_tool_manager import get_tool_manager
        from ipfs_datasets_py.mcp_server.tool_metadata import get_registry
        from ipfs_datasets_py.mcp_server.mcplusplus.workflow_scheduler import get_scheduler
        
        # New pattern with context
        with ServerContext() as context:
            manager = get_tool_manager(context)
            registry = get_registry(context)
            scheduler = get_scheduler(context)
            
            # Should all use context's resources
            assert manager is context.tool_manager
            assert registry is context.metadata_registry
            # scheduler should be context's scheduler (if set)


class TestThreadSafetyWithContext:
    """Test thread safety when using ServerContext."""
    
    def test_concurrent_contexts_are_isolated(self):
        """
        GIVEN: Multiple threads using separate ServerContext instances
        WHEN: Each thread gets managers/registries
        THEN: Each context has isolated resources (no cross-contamination)
        """
        import threading
        from ipfs_datasets_py.mcp_server.hierarchical_tool_manager import get_tool_manager
        from ipfs_datasets_py.mcp_server.tool_metadata import get_registry
        
        results = []
        
        def worker(worker_id):
            with ServerContext() as context:
                manager = get_tool_manager(context)
                registry = get_registry(context)
                results.append({
                    'worker_id': worker_id,
                    'manager': manager,
                    'registry': registry,
                    'context_manager': context.tool_manager,
                    'context_registry': context.metadata_registry
                })
        
        # WHEN: Create 5 concurrent threads
        threads = []
        for i in range(5):
            t = threading.Thread(target=worker, args=(i,))
            threads.append(t)
            t.start()
        
        for t in threads:
            t.join()
        
        # THEN: Each worker got its own isolated resources
        assert len(results) == 5
        
        # Check managers are isolated
        managers = [r['manager'] for r in results]
        assert len(set(id(m) for m in managers)) == 5  # All different instances
        
        # Check registries are isolated
        registries = [r['registry'] for r in results]
        assert len(set(id(r) for r in registries)) == 5  # All different instances
        
        # Check each worker used its context's resources
        for result in results:
            assert result['manager'] is result['context_manager']
            assert result['registry'] is result['context_registry']


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
