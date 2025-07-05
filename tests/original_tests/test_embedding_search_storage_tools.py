"""
Tests for embedding-related MCP tools.
"""

import pytest
import asyncio
import os
import tempfile
import numpy as np
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from pathlib import Path

# import sys # Commented out old sys.path modifications
# sys.path.append('/home/barberb/laion-embeddings-1/tests/test_mcp_tools') # Commented out old sys.path modifications
# sys.path.append('/home/barberb/laion-embeddings-1') # Commented out old sys.path modifications
from tests.conftest import ( # Updated import for conftest
    mock_embedding_service, sample_embeddings, sample_metadata,
    create_sample_file, TEST_MODEL_NAME, TEST_BATCH_SIZE
)

# Import the tools from their new locations
from ipfs_datasets_py.mcp_tools.tools.embedding_tools import EmbeddingGenerationTool, BatchEmbeddingTool, MultimodalEmbeddingTool
# Assuming storage tools are also migrated to ipfs_datasets_py.mcp_tools.tools
# from ipfs_datasets_py.mcp_tools.tools.storage_tools import save_embeddings_tool, load_embeddings_tool # Assuming storage tools are migrated
from ipfs_datasets_py.mcp_tools.tools.search_tools import SemanticSearchTool # Removed BatchSearchTool as it's not in the migrated code

# Assuming get_supported_models is available or mocked
# from ipfs_datasets_py.embeddings.models import get_supported_models # Example updated import


@pytest.mark.asyncio
class TestEmbeddingTools:
    """Test suite for embedding MCP tools."""
    
    # Patch the actual service path in the current project
    @patch('ipfs_datasets_py.embeddings.create_embeddings.create_embeddings') # Updated patch target
    async def test_generate_embedding_tool(self, mock_service_class, mock_embedding_service): # Renamed test to match tool
        """Test generating a single embedding from text."""
        # Instantiate the tool
        embedding_tool = EmbeddingGenerationTool(mock_embedding_service)
        
        text = "Hello world"
        
        # Call the execute method of the tool instance
        result = await embedding_tool.execute(
            parameters={ # Pass parameters as a dictionary
                "text": text,
                "model": TEST_MODEL_NAME,
                "normalize": True
            }
        )
        
        assert result["text"] == text
        assert result["model"] == TEST_MODEL_NAME
        assert "embedding" in result
        assert "dimension" in result
        assert result["normalized"] is True
        
        # Verify service was called correctly
        mock_embedding_service.generate_embedding.assert_called_once_with(text, TEST_MODEL_NAME, True) # Updated mock method and arguments

    @patch('ipfs_datasets_py.embeddings.create_embeddings.create_embeddings') # Updated patch target
    async def test_generate_batch_embeddings_tool(self, mock_service_class, mock_embedding_service): # Renamed test to match tool
        """Test generating embeddings for multiple texts in batch."""
        # Instantiate the tool
        batch_embedding_tool = BatchEmbeddingTool(mock_embedding_service)
        
        texts = ["Text 1", "Text 2", "Text 3"]
        batch_size = 2
        
        # Call the execute method of the tool instance
        result = await batch_embedding_tool.execute(
            parameters={ # Pass parameters as a dictionary
                "texts": texts,
                "model": TEST_MODEL_NAME,
                "normalize": True,
                "batch_size": batch_size
            }
        )
        
        assert result["texts"] == texts
        assert result["model"] == TEST_MODEL_NAME
        assert "embeddings" in result
        assert result["count"] == len(texts)
        assert "dimension" in result
        assert result["normalized"] is True
        assert result["batch_size"] == batch_size
        
        # Verify service was called correctly
        mock_embedding_service.generate_batch_embeddings.assert_called_once_with(texts, TEST_MODEL_NAME, True, batch_size) # Updated mock method and arguments

    # Note: The original test `test_create_embeddings_from_file_tool` and `test_batch_create_embeddings_tool`
    # seem to be testing functions that are not directly exposed as MCP tools in the migrated structure.
    # The migrated MCP tools are `EmbeddingGenerationTool`, `BatchEmbeddingTool`, and `MultimodalEmbeddingTool`.
    # I have adapted the tests to match the new tool structure.
    # The `create_embeddings_from_file_tool_invalid_file` test is also for a non-migrated function.

    # Add a test for MultimodalEmbeddingTool
    @patch('ipfs_datasets_py.embeddings.create_embeddings.create_embeddings') # Updated patch target
    async def test_generate_multimodal_embedding_tool(self, mock_service_class, mock_embedding_service):
        """Test generating multimodal embeddings."""
        # Instantiate the tool
        multimodal_embedding_tool = MultimodalEmbeddingTool(mock_embedding_service)

        content = {"text": "a cat and a dog", "image_url": "http://example.com/cat_dog.jpg"}
        model = "clip-vit-base-patch32"
        fusion_strategy = "concatenate"

        result = await multimodal_embedding_tool.execute(
            parameters={
                "content": content,
                "model": model,
                "fusion_strategy": fusion_strategy,
                "normalize": True
            }
        )

        assert result["content"] == content
        assert result["model"] == model
        assert "embedding" in result
        assert "dimension" in result
        assert result["fusion_strategy"] == fusion_strategy
        assert result["normalized"] is True
        assert "modalities" in result

        # Verify service was called correctly
        mock_embedding_service.generate_multimodal_embedding.assert_called_once_with(content, model, fusion_strategy, True)


    # Note: The original `test_list_available_models_tool` and `test_compare_embeddings_tool`
    # are for functions that might not be directly part of the core embedding service
    # or might be implemented differently. I will keep them commented out for now
    # and address them if needed based on the current project's requirements.

    # @patch('src.mcp_server.tools.embedding_tools.get_supported_models')
    # async def test_list_available_models_tool(self, mock_get_models):
    #     """Test listing available embedding models."""
    #     from src.mcp_server.tools.embedding_tools import list_available_models_tool

    #     mock_get_models.return_value = [
    #         {"name": "model1", "dimension": 384, "description": "Small model"},
    #         {"name": "model2", "dimension": 768, "description": "Large model"}
    #     ]

    #     result = await list_available_models_tool(provider="sentence-transformers")

    #     assert result["success"] is True
    #     assert result["provider"] == "sentence-transformers"
    #     assert len(result["models"]) == 2
    #     assert result["models"][0]["name"] == "model1"
    #     assert result["models"][1]["dimension"] == 768

    # @patch('src.mcp_server.tools.embedding_tools.EmbeddingService')
    # async def test_compare_embeddings_tool(self, mock_service_class, mock_embedding_service, sample_embeddings):
    #     """Test comparing embeddings similarity."""
    #     from src.mcp_server.tools.embedding_tools import compare_embeddings_tool

    #     mock_service_class.return_value = mock_embedding_service

    #     embedding1 = sample_embeddings[0]
    #     embedding2 = sample_embeddings[1]

    #     result = await compare_embeddings_tool(
    #         embedding1=embedding1,
    #         embedding2=embedding2,
    #         metric="cosine"
    #     )

    #     assert result["success"] is True
    #     assert "similarity_score" in result
    #     assert result["metric"] == "cosine"
    #     assert 0 <= result["similarity_score"] <= 1

    # def test_tool_metadata_structure(self):
    #     """Test that tool metadata is properly structured."""
    #     from src.mcp_server.tools.embedding_tools import TOOL_METADATA

    #     # Check create_embeddings_from_text_tool metadata
    #     text_meta = TOOL_METADATA["create_embeddings_from_text_tool"]
    #     assert text_meta["name"] == "create_embeddings_from_text_tool"
    #     assert "description" in text_meta
    #     assert "parameters" in text_meta

    #     params = text_meta["parameters"]
    #     assert params["type"] == "object"
    #     assert "texts" in params["required"]
    #     assert "model_name" in params["required"]

    #     # Check create_embeddings_from_file_tool metadata
    #     file_meta = TOOL_METADATA["create_embeddings_from_file_tool"]
    #     assert file_meta["name"] == "create_embeddings_from_file_tool"
    #     assert "file_path" in file_meta["parameters"]["required"]

    #     # Check default values
    #     file_props = file_meta["parameters"]["properties"]
    #     assert file_props["normalize"]["default"] is True
    #     assert file_props["batch_size"]["default"] == 32


@pytest.mark.asyncio
class TestStorageTools:
    """Test suite for storage-related MCP tools."""
    # Note: Storage tools are not part of the initial core migration scope.
    # I will comment out these tests for now and address them if storage features are integrated later.

    # @patch('src.mcp_server.tools.storage_tools.StorageManager')
    # async def test_save_embeddings_tool(self, mock_storage_class, sample_embeddings, sample_metadata, temp_dir):
    #     """Test saving embeddings to storage."""
    #     from src.mcp_server.tools.storage_tools import save_embeddings_tool

    #     mock_storage = Mock()
    #     mock_storage.save_embeddings = AsyncMock(return_value={
    #         "success": True,
    #         "file_path": "/saved/embeddings.parquet",
    #         "count": len(sample_embeddings),
    #         "size_bytes": 1024000
    #     })
    #     mock_storage_class.return_value = mock_storage

    #     output_path = os.path.join(temp_dir, "embeddings.parquet")

    #     result = await save_embeddings_tool(
    #         embeddings=sample_embeddings[:10],
    #         metadata=sample_metadata[:10],
    #         output_path=output_path,
    #         format="parquet",
    #         compression="gzip"
    #     )

    #     assert result["success"] is True
    #     assert result["embeddings_saved"] == 10
    #     assert result["output_path"] == output_path
    #     assert result["format"] == "parquet"
    #     assert "file_size" in result

    # @patch('src.mcp_server.tools.storage_tools.StorageManager')
    # async def test_load_embeddings_tool(self, mock_storage_class, sample_embeddings, temp_dir):
    #     """Test loading embeddings from storage."""
    #     from src.mcp_server.tools.storage_tools import load_embeddings_tool

    #     mock_storage = Mock()
    #     mock_storage.load_embeddings = AsyncMock(return_value={
    #         "success": True,
    #         "embeddings": sample_embeddings[:5],
    #         "metadata": [{"id": i} for i in range(5)],
    #         "count": 5
    #     })
    #     mock_storage_class.return_value = mock_storage

    #     input_path = os.path.join(temp_dir, "embeddings.parquet")

    #     result = await load_embeddings_tool(
    #         input_path=input_path,
    #         limit=5,
    #         offset=0,
    #         include_metadata=True
    #     )

    #     assert result["success"] is True
    #     assert result["input_path"] == input_path
    #     assert result["embeddings_loaded"] == 5
    #     assert len(result["embeddings"]) == 5
    #     assert "metadata" in result

    # async def test_load_embeddings_tool_invalid_path(self, temp_dir):
    #     """Test loading embeddings from invalid path."""
    #     from src.mcp_server.tools.storage_tools import load_embeddings_tool

    #     invalid_path = os.path.join(temp_dir, "nonexistent.parquet")

    #     result = await load_embeddings_tool(input_path=invalid_path)

    #     assert result["success"] is False
    #     assert "does not exist" in result["error"]


@pytest.mark.asyncio
class TestSearchTools:
    """Test suite for search-related MCP tools."""

    # Patch the actual service path in the current project
    @patch('ipfs_datasets_py.search.search_embeddings.search_embeddings') # Updated patch target
    async def test_semantic_search_tool(self, mock_service_class, mock_vector_service): # Updated mock fixture name
        """Test semantic search functionality."""
        # Instantiate the tool
        semantic_search_tool_instance = SemanticSearchTool(mock_vector_service) # Instantiate the tool

        mock_service_class.return_value = mock_vector_service # Ensure the patch returns the mock vector service

        query = "test query"
        top_k = 5
        collection = "test_index" # Renamed from index_id to match tool schema
        filter_metadata = {"category": "documents"} # Renamed from filter_metadata to match tool schema

        # Call the execute method of the tool instance
        result = await semantic_search_tool_instance.execute( # Updated call
            parameters={ # Pass parameters as a dictionary
                "query": query,
                "top_k": top_k,
                "collection": collection,
                "filters": filter_metadata # Updated parameter name
            }
        )

        assert result["query"] == query
        assert result["top_k"] == top_k
        assert result["collection"] == collection
        assert "results" in result
        assert "total_found" in result

        # Verify service was called correctly
        # The semantic search tool calls index_knn on the vector service
        mock_vector_service.index_knn.assert_called_once_with([query], ANY) # Updated mock method and arguments (ANY for model)


    # Note: The original `test_batch_search_tool` and `test_search_tool_metadata_structure`
    # are for functions/metadata that might not be directly part of the core search service
    # or might be implemented differently. I will keep them commented out for now
    # and address them if needed based on the current project's requirements.

    # @patch('src.mcp_server.tools.search_tools.SearchService')
    # async def test_batch_search_tool(self, mock_service_class):
    #     """Test batch search functionality."""
    #     from src.mcp_server.tools.search_tools import batch_search_tool
    #
    #     mock_service = Mock()
    #     mock_service.batch_search = AsyncMock(return_value={
    #         "success": True,
    #         "total_queries": 3,
    #         "results": [
    #             {"query": "query1", "results": [{"id": "1", "score": 0.9}]},
    #             {"query": "query2", "results": [{"id": "2", "score": 0.8}]},
    #             {"query": "query3", "results": [{"id": "3", "score": 0.7}]}
    #         ]
    #     })
    #     mock_service_class.return_value = mock_service
    #
    #     queries = ["query1", "query2", "query3"]
    #
    #     result = await batch_search_tool(
    #         queries=queries,
    #         index_id="test_index",
    #         top_k=3,
    #         parallel=True
    #     )
    #
    #     assert result["success"] is True
    #     assert result["total_queries"] == 3
    #     assert len(result["results"]) == 3
    #     assert result["parallel"] is True
    #
    # def test_search_tool_metadata_structure(self):
    #     """Test search tool metadata structure."""
    #     from src.mcp_server.tools.search_tools import TOOL_METADATA
    #
    #     # Check semantic_search_tool metadata
    #     search_meta = TOOL_METADATA["semantic_search_tool"]
    #     assert search_meta["name"] == "semantic_search_tool"
    #     assert "query" in search_meta["parameters"]["required"]
    #
    #     # Check default values
    #     search_props = search_meta["parameters"]["properties"]
    #     assert search_props["top_k"]["default"] == 10


if __name__ == "__main__":
    pytest.main([__file__])
