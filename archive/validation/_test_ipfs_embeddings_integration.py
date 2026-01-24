import anyio
import json
from unittest.mock import patch, AsyncMock
import pytest

from ipfs_datasets_py.mcp_server.server import IPFSDatasetsMCPServer

@pytest.fixture
async def mcp_server_instance():
    """Fixture to provide an initialized MCP server instance."""
    server = IPFSDatasetsMCPServer()
    # Mock the run_stdio_async to prevent it from blocking
    server.mcp.run_stdio_async = AsyncMock()
    server.register_tools()
    return server

@pytest.mark.asyncio
async def test_ipfs_embeddings_tools_registered(mcp_server_instance):
    """
    Test that ipfs_embeddings_py tools are registered with the MCP server.
    """
    server = mcp_server_instance
    
    # Get the list of registered tools
    registered_tools = server.tools.keys()

    # Define some expected tools from ipfs_embeddings_py
    expected_tools = [
        "EmbeddingGenerationTool",
        "BatchEmbeddingTool",
        "MultimodalEmbeddingTool",
        "SemanticSearchTool",
        "SimilaritySearchTool",
        "FacetedSearchTool",
        "StorageManagementTool",
        "CollectionManagementTool",
        "RetrievalTool",
        "ClusterAnalysisTool",
        "QualityAssessmentTool",
        "DimensionalityReductionTool",
        "VectorIndexTool",
        "VectorRetrievalTool",
        "VectorMetadataTool",
        "IPFSClusterTool",
        "DistributedVectorTool",
        "IPFSMetadataTool",
    ]

    for tool_name in expected_tools:
        assert tool_name in registered_tools, f"Tool '{tool_name}' not found in registered tools."
        print(f"Tool '{tool_name}' is registered.")

@pytest.mark.asyncio
async def test_call_embedding_generation_tool(mcp_server_instance):
    """
    Test calling a specific ipfs_embeddings_py tool (EmbeddingGenerationTool)
    and verify its placeholder behavior.
    """
    server = mcp_server_instance
    
    tool_name = "EmbeddingGenerationTool"
    assert tool_name in server.tools, f"Tool '{tool_name}' not found for testing."

    # Prepare a mock request for the tool
    mock_request = {
        "name": tool_name,
        "arguments": {"text": "Hello, world!"}
    }

    # Call the tool directly via its registered function
    tool_func = server.tools[tool_name]
    result = await tool_func(**mock_request["arguments"])

    # Verify the placeholder behavior (e.g., returns a list of floats)
    assert isinstance(result, list)
    assert all(isinstance(x, float) for x in result)
    assert len(result) == 768 # Expected embedding size from placeholder

    print(f"Successfully called '{tool_name}'. Result type: {type(result)}, length: {len(result)}")
