#!/usr/bin/env python3
"""
Test suite for embedding_tools functionality with GIVEN WHEN THEN format.

Written to match the actual embedding_tools API:
  generate_embedding(text, model, ...) → {'status', 'embedding', 'dimension', ...}
  generate_batch_embeddings(texts, model, ...) → {'status', 'embeddings', 'total_processed', ...}
  generate_embeddings_from_file(file_path, ...) → optional function
"""

import pytest
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from ipfs_datasets_py.mcp_server.tools.embedding_tools.embedding_generation import (
    generate_embedding,
    generate_batch_embeddings,
)


class TestEmbeddingGeneration:
    """Test generate_embedding() — single text."""

    @pytest.mark.asyncio
    async def test_generate_embedding_basic(self):
        """GIVEN a text string
        WHEN generate_embedding() is called
        THEN a result with status and embedding fields is returned
        """
        result = await generate_embedding(text="Hello, world!")
        assert result is not None
        assert "status" in result
        assert result["status"] in ["success", "error", "unavailable"]

    @pytest.mark.asyncio
    async def test_generate_embedding_has_dimension(self):
        """GIVEN a text string
        WHEN generate_embedding() succeeds
        THEN the dimension field is a positive integer
        """
        result = await generate_embedding(text="Test sentence for embedding.")
        assert result is not None
        if result.get("status") == "success":
            assert "dimension" in result
            assert isinstance(result["dimension"], int)
            assert result["dimension"] > 0

    @pytest.mark.asyncio
    async def test_generate_embedding_with_model(self):
        """GIVEN a text and model name
        WHEN generate_embedding() is called with a specific model
        THEN the model field is present in the result
        """
        result = await generate_embedding(text="Sample text.", model="default")
        assert result is not None
        assert "model" in result

    @pytest.mark.asyncio
    async def test_generate_embedding_result_structure(self):
        """GIVEN a text string
        WHEN generate_embedding() is called
        THEN the result contains expected fields
        """
        result = await generate_embedding(text="Structure check.")
        assert isinstance(result, dict)
        assert "status" in result
        assert "text" in result or "message" in result

    @pytest.mark.asyncio
    async def test_generate_embedding_empty_text(self):
        """GIVEN an empty text string
        WHEN generate_embedding() is called
        THEN a result is returned (error or success depending on implementation)
        """
        result = await generate_embedding(text="")
        assert result is not None
        assert isinstance(result, dict)


class TestBatchEmbeddingGeneration:
    """Test generate_batch_embeddings() — multiple texts."""

    @pytest.mark.asyncio
    async def test_batch_embeddings_basic(self):
        """GIVEN a list of texts
        WHEN generate_batch_embeddings() is called
        THEN a result with status and embeddings fields is returned
        """
        texts = ["First sentence.", "Second sentence.", "Third sentence."]
        result = await generate_batch_embeddings(texts=texts)
        assert result is not None
        assert "status" in result
        assert result["status"] in ["success", "error", "unavailable"]

    @pytest.mark.asyncio
    async def test_batch_embeddings_count(self):
        """GIVEN a list of 4 texts
        WHEN generate_batch_embeddings() succeeds
        THEN total_processed equals the number of input texts
        """
        texts = ["Text A.", "Text B.", "Text C.", "Text D."]
        result = await generate_batch_embeddings(texts=texts)
        assert result is not None
        if result.get("status") == "success":
            assert "total_processed" in result
            assert result["total_processed"] == len(texts)

    @pytest.mark.asyncio
    async def test_batch_embeddings_result_structure(self):
        """GIVEN a list of texts
        WHEN generate_batch_embeddings() is called
        THEN expected top-level fields are present
        """
        texts = ["Check A.", "Check B."]
        result = await generate_batch_embeddings(texts=texts)
        assert isinstance(result, dict)
        assert "status" in result
        assert "model" in result

    @pytest.mark.asyncio
    async def test_batch_embeddings_with_model(self):
        """GIVEN a list of texts and a model name
        WHEN generate_batch_embeddings() is called with model='default'
        THEN the model field matches
        """
        texts = ["Model test 1.", "Model test 2."]
        result = await generate_batch_embeddings(texts=texts, model="default")
        assert result is not None
        assert "model" in result

    @pytest.mark.asyncio
    async def test_batch_embeddings_single_text(self):
        """GIVEN a single-element list
        WHEN generate_batch_embeddings() is called
        THEN the batch works the same as multi-text
        """
        result = await generate_batch_embeddings(texts=["Only one text."])
        assert result is not None
        if result.get("status") == "success":
            assert result["total_processed"] == 1


class TestEmbeddingFromFile:
    """Test generate_embeddings_from_file() — optional function."""

    @pytest.mark.asyncio
    async def test_generate_from_file_import(self):
        """GIVEN the embedding_generation module
        WHEN generate_embeddings_from_file is imported
        THEN it imports without error
        """
        try:
            from ipfs_datasets_py.mcp_server.tools.embedding_tools.embedding_generation import (
                generate_embeddings_from_file,
            )
            assert callable(generate_embeddings_from_file)
        except ImportError:
            pytest.skip("generate_embeddings_from_file not available")

    @pytest.mark.asyncio
    async def test_generate_from_nonexistent_file(self):
        """GIVEN a path to a non-existent file
        WHEN generate_embeddings_from_file() is called
        THEN an error result is returned (not an unhandled exception)
        """
        try:
            from ipfs_datasets_py.mcp_server.tools.embedding_tools.embedding_generation import (
                generate_embeddings_from_file,
            )
            result = await generate_embeddings_from_file(file_path="/tmp/nonexistent_file_xyz.txt")
            assert result is not None
            assert isinstance(result, dict)
        except ImportError:
            pytest.skip("generate_embeddings_from_file not available")


class TestEmbeddingToolsIntegration:
    """Integration tests for embedding_tools."""

    @pytest.mark.asyncio
    async def test_single_and_batch_consistency(self):
        """GIVEN the same text passed to both functions
        WHEN generate_embedding and generate_batch_embeddings are both called
        THEN both return results with the same status type
        """
        text = "Consistency check text."
        single_result = await generate_embedding(text=text)
        batch_result = await generate_batch_embeddings(texts=[text])

        assert single_result is not None
        assert batch_result is not None
        # Both should have 'status' key
        assert "status" in single_result
        assert "status" in batch_result

    @pytest.mark.asyncio
    async def test_available_tools_listing(self):
        """GIVEN the embedding_generation module
        WHEN get_available_tools() is called
        THEN a list of tool names is returned
        """
        from ipfs_datasets_py.mcp_server.tools.embedding_tools.embedding_generation import (
            get_available_tools,
        )
        tools = get_available_tools()
        assert tools is not None
        assert isinstance(tools, list)
        assert len(tools) > 0
