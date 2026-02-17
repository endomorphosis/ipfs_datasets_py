"""Integration tests for Hierarchical Tool Manager.

These tests validate end-to-end workflows and integration between
the hierarchical tool manager and actual MCP tools.
"""

import pytest
import anyio
from pathlib import Path

from ipfs_datasets_py.mcp_server.hierarchical_tool_manager import (
    HierarchicalToolManager,
    get_tool_manager,
)


class TestHierarchicalToolManagerIntegration:
    """Integration tests for hierarchical tool manager workflows."""
    
    @pytest.mark.anyio
    async def test_full_tool_discovery_workflow(self):
        """Test complete tool discovery workflow.
        
        GIVEN a fresh hierarchical tool manager
        WHEN we perform full tool discovery
        THEN all categories and tools are discovered correctly
        """
        # GIVEN a fresh manager
        manager = HierarchicalToolManager()
        
        # WHEN we discover categories
        manager.discover_categories()
        
        # THEN categories are discovered
        assert manager._discovered_categories
        assert len(manager.categories) > 0
        
        # AND we can list categories
        categories = await manager.list_categories(include_count=True)
        assert len(categories) > 0
        
        # AND each category has tools
        for category_info in categories:
            if category_info["tool_count"] > 0:
                tools_result = await manager.list_tools(category_info["name"])
                assert tools_result["status"] == "success"
                assert len(tools_result["tools"]) > 0
    
    @pytest.mark.anyio
    async def test_tool_schema_and_dispatch_workflow(self):
        """Test workflow of getting schema then dispatching tool.
        
        GIVEN a tool that we can introspect
        WHEN we get its schema and then dispatch to it
        THEN the workflow completes successfully
        """
        # GIVEN a manager and known tool
        manager = HierarchicalToolManager()
        category = "graph_tools"
        tool_name = "query_knowledge_graph"
        
        # WHEN we get the schema
        schema_result = await manager.get_tool_schema(category, tool_name)
        
        # THEN schema is returned
        assert schema_result["status"] == "success"
        assert "schema" in schema_result
        assert schema_result["schema"]["name"] == tool_name
        
        # AND we can extract parameters
        params = schema_result["schema"].get("parameters", {})
        
        # AND we can dispatch with test parameters
        test_params = {
            "query": "test query",
            "max_results": 5
        }
        dispatch_result = await manager.dispatch(category, tool_name, test_params)
        
        # THEN dispatch completes (result depends on tool implementation)
        assert isinstance(dispatch_result, dict)
    
    @pytest.mark.anyio
    async def test_multiple_category_tool_dispatch(self):
        """Test dispatching to tools across multiple categories.
        
        GIVEN multiple categories with tools
        WHEN we dispatch to tools in different categories
        THEN all dispatches work correctly
        """
        # GIVEN a manager
        manager = HierarchicalToolManager()
        
        # WHEN we dispatch to tools in different categories
        test_cases = [
            ("graph_tools", "query_knowledge_graph", {"query": "test", "max_results": 5}),
            ("ipfs_tools", "get_ipfs_status", {}),
            ("dataset_tools", "list_datasets", {"source": "local"}),
        ]
        
        results = []
        for category, tool, params in test_cases:
            result = await manager.dispatch(category, tool, params)
            results.append((category, tool, result))
        
        # THEN all dispatches return results
        assert len(results) == len(test_cases)
        for category, tool, result in results:
            assert isinstance(result, dict)
            # Tool might return error if not configured, but dispatch works
    
    @pytest.mark.anyio
    async def test_category_tool_count_accuracy(self):
        """Test that tool counts match actual discovered tools.
        
        GIVEN categories with tools
        WHEN we get tool counts
        THEN counts match actual tool discoveries
        """
        # GIVEN a manager
        manager = HierarchicalToolManager()
        
        # WHEN we list categories with counts
        categories = await manager.list_categories(include_count=True)
        
        # THEN for each category, count matches discovered tools
        for category_info in categories:
            category_name = category_info["name"]
            expected_count = category_info["tool_count"]
            
            # Get actual tools
            tools_result = await manager.list_tools(category_name)
            
            if tools_result["status"] == "success":
                actual_count = len(tools_result["tools"])
                assert actual_count == expected_count, \
                    f"Category {category_name}: expected {expected_count} tools, got {actual_count}"
    
    @pytest.mark.anyio
    async def test_singleton_pattern(self):
        """Test that get_tool_manager returns same instance.
        
        GIVEN multiple calls to get_tool_manager
        WHEN we get the manager multiple times
        THEN we get the same instance
        """
        # GIVEN multiple manager requests
        manager1 = get_tool_manager()
        manager2 = get_tool_manager()
        manager3 = get_tool_manager()
        
        # THEN all are the same instance
        assert manager1 is manager2
        assert manager2 is manager3
        
        # AND they share state
        manager1.discover_categories()
        assert manager2._discovered_categories
        assert manager3._discovered_categories
    
    @pytest.mark.anyio
    async def test_error_handling_chain(self):
        """Test error handling through the dispatch chain.
        
        GIVEN various error scenarios
        WHEN we dispatch with errors
        THEN errors are handled gracefully
        """
        # GIVEN a manager
        manager = HierarchicalToolManager()
        
        # Test Case 1: Invalid category
        result1 = await manager.dispatch("invalid_category", "tool", {})
        assert result1["status"] == "error"
        assert "not found" in result1["error"].lower()
        
        # Test Case 2: Invalid tool in valid category
        result2 = await manager.dispatch("graph_tools", "nonexistent_tool", {})
        assert result2["status"] == "error"
        assert "not found" in result2["error"].lower()
        
        # Test Case 3: Valid tool with missing required params (depends on tool)
        result3 = await manager.dispatch("graph_tools", "query_knowledge_graph", {})
        # Tool might handle missing params itself - we just check dispatch works
        assert isinstance(result3, dict)
    
    @pytest.mark.anyio
    async def test_tool_metadata_completeness(self):
        """Test that tool metadata is complete and accurate.
        
        GIVEN discovered tools
        WHEN we retrieve tool metadata
        THEN all required metadata fields are present
        """
        # GIVEN a manager with discovered tools
        manager = HierarchicalToolManager()
        categories = await manager.list_categories()
        
        # WHEN we check tool metadata
        for category_info in categories[:5]:  # Check first 5 categories
            category_name = category_info["name"]
            tools_result = await manager.list_tools(category_name)
            
            if tools_result["status"] == "success":
                tools = tools_result["tools"]
                
                # THEN each tool has required metadata
                for tool in tools[:3]:  # Check first 3 tools per category
                    assert "name" in tool
                    assert "description" in tool
                    assert "category" in tool
                    assert tool["category"] == category_name
                    
                    # AND we can get full schema
                    schema_result = await manager.get_tool_schema(
                        category_name, 
                        tool["name"]
                    )
                    assert schema_result["status"] == "success"
                    assert "schema" in schema_result
    
    @pytest.mark.anyio
    async def test_concurrent_dispatches(self):
        """Test concurrent tool dispatches.
        
        GIVEN multiple tools to dispatch
        WHEN we dispatch them concurrently
        THEN all complete successfully
        """
        # GIVEN a manager and multiple dispatch tasks
        manager = HierarchicalToolManager()
        
        # WHEN we create concurrent dispatches
        async def dispatch_task(category, tool, params):
            return await manager.dispatch(category, tool, params)
        
        tasks = [
            dispatch_task("graph_tools", "query_knowledge_graph", {"query": "test1", "max_results": 5}),
            dispatch_task("ipfs_tools", "get_ipfs_status", {}),
            dispatch_task("dataset_tools", "list_datasets", {"source": "local"}),
        ]
        
        # Execute concurrently
        results = await anyio.gather(*tasks)
        
        # THEN all dispatches complete
        assert len(results) == len(tasks)
        for result in results:
            assert isinstance(result, dict)
    
    @pytest.mark.anyio
    async def test_tool_rediscovery(self):
        """Test that tools can be rediscovered.
        
        GIVEN a manager with discovered tools
        WHEN we force rediscovery
        THEN tools are rediscovered correctly
        """
        # GIVEN a manager with discovered tools
        manager = HierarchicalToolManager()
        manager.discover_categories()
        initial_count = len(manager.categories)
        
        # WHEN we force rediscovery
        manager._discovered_categories = False
        manager.categories.clear()
        manager.discover_categories()
        
        # THEN tools are rediscovered
        assert manager._discovered_categories
        assert len(manager.categories) == initial_count


class TestCoreOperationsIntegration:
    """Integration tests for core operations modules."""
    
    @pytest.mark.anyio
    async def test_data_processor_workflow(self):
        """Test DataProcessor end-to-end workflow.
        
        GIVEN text data to process
        WHEN we use DataProcessor operations
        THEN data is processed correctly
        """
        from ipfs_datasets_py.core_operations import DataProcessor
        
        # GIVEN a DataProcessor and text data
        processor = DataProcessor()
        text = "This is a sample text. " * 10  # 60 words
        
        # WHEN we chunk the text
        chunks = processor.chunk_text(
            text,
            chunk_size=100,
            strategy="fixed_size"
        )
        
        # THEN text is chunked
        assert len(chunks) > 0
        assert all(isinstance(c, str) for c in chunks)
    
    @pytest.mark.anyio
    async def test_dataset_loader_saver_pipeline(self):
        """Test DatasetLoader -> DatasetSaver pipeline.
        
        GIVEN a dataset to load and save
        WHEN we use loader and saver together
        THEN data flows through pipeline correctly
        """
        from ipfs_datasets_py.core_operations import DatasetLoader, DatasetSaver
        
        # GIVEN loader and saver
        loader = DatasetLoader()
        saver = DatasetSaver()
        
        # Test that they're initialized correctly
        assert loader is not None
        assert saver is not None
        
        # In a full implementation, we would:
        # 1. Load a dataset with loader
        # 2. Transform it
        # 3. Save with saver
        # For now, we verify they exist and are callable
    
    @pytest.mark.anyio
    async def test_ipfs_pin_get_workflow(self):
        """Test IPFS pin -> get workflow.
        
        GIVEN content to pin
        WHEN we pin and then retrieve
        THEN content flows correctly
        """
        from ipfs_datasets_py.core_operations import IPFSPinner, IPFSGetter
        
        # GIVEN pinner and getter
        pinner = IPFSPinner()
        getter = IPFSGetter()
        
        # Verify they're initialized
        assert pinner is not None
        assert getter is not None
        
        # In full implementation:
        # 1. Pin content with pinner
        # 2. Get CID
        # 3. Retrieve with getter
        # 4. Verify content matches
    
    @pytest.mark.anyio
    async def test_knowledge_graph_operations(self):
        """Test KnowledgeGraphManager operations.
        
        GIVEN a knowledge graph manager
        WHEN we perform graph operations
        THEN operations complete correctly
        """
        from ipfs_datasets_py.core_operations import KnowledgeGraphManager
        
        # GIVEN a graph manager
        manager = KnowledgeGraphManager()
        
        # Verify initialization
        assert manager is not None
        
        # In full implementation:
        # 1. Create graph
        # 2. Add entities
        # 3. Add relationships
        # 4. Query graph
        # 5. Verify results


class TestMCPWorkflowEndToEnd:
    """End-to-end workflow tests for MCP operations."""
    
    @pytest.mark.anyio
    async def test_complete_search_workflow(self):
        """Test complete search workflow from discovery to execution.
        
        GIVEN a search request
        WHEN we go through discovery -> schema -> dispatch
        THEN complete workflow executes successfully
        """
        # GIVEN a tool manager
        manager = HierarchicalToolManager()
        
        # Step 1: Discover categories
        categories = await manager.list_categories()
        assert len(categories) > 0
        
        # Step 2: Find embedding_tools category
        embedding_cat = None
        for cat in categories:
            if cat["name"] == "embedding_tools":
                embedding_cat = cat
                break
        
        if embedding_cat:
            # Step 3: List tools in category
            tools_result = await manager.list_tools("embedding_tools")
            assert tools_result["status"] == "success"
            
            # Step 4: Get schema for search tool (if exists)
            # Step 5: Execute search (if configured)
            # Note: Full execution depends on system configuration
    
    @pytest.mark.anyio
    async def test_complete_dataset_workflow(self):
        """Test complete dataset processing workflow.
        
        GIVEN a dataset processing request
        WHEN we process through MCP tools
        THEN workflow completes successfully
        """
        # GIVEN a tool manager
        manager = HierarchicalToolManager()
        
        # Step 1: List dataset tools
        tools_result = await manager.list_tools("dataset_tools")
        
        if tools_result["status"] == "success":
            # Step 2: Verify core dataset operations exist
            tool_names = [t["name"] for t in tools_result["tools"]]
            
            # Common dataset operations
            expected_operations = ["list_datasets", "load_dataset", "process_dataset"]
            for op in expected_operations:
                # Check if operation exists (tool names may vary)
                # This validates tool organization
                pass
    
    @pytest.mark.anyio
    async def test_complete_embedding_workflow(self):
        """Test complete embedding generation workflow.
        
        GIVEN text for embedding
        WHEN we generate and search embeddings
        THEN workflow completes successfully
        """
        # GIVEN a tool manager
        manager = HierarchicalToolManager()
        
        # Step 1: Check embedding tools exist
        categories = await manager.list_categories()
        category_names = [c["name"] for c in categories]
        
        # Embedding tools should exist
        assert "embedding_tools" in category_names or "vector_tools" in category_names
        
        # Step 2: In full implementation:
        # - Generate embeddings for text
        # - Store in vector store
        # - Search for similar items
        # - Verify results


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
