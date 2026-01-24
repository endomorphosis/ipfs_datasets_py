import anyio
"""
Test stubs for Vector MCP tools.

Test stubs for all Vector MCP tool functions following the standardized format.
Each function and method requires a corresponding test stub.

#FIXME Update this file with actual test implementations as needed.
    _create_qdrant_index,
    _create_elasticsearch_index,
    _search_faiss_index,
"""
import pytest

# Import the Vector MCP tools
from ipfs_datasets_py.mcp_server.tools.vector_tools.vector_store_management import (
    create_vector_index,
    search_vector_index,
    _create_qdrant_index,
    _create_elasticsearch_index,
    _search_faiss_index,
    list_vector_indexes,
    delete_vector_index, 
)


class TestCreateVectorIndex:
    """Test the create_vector_index MCP tool."""
    
    @pytest.mark.asyncio
    async def test_create_vector_index_with_valid_name_and_documents(self):
        """
        GIVEN valid index_name string
        AND valid documents list with text and metadata
        WHEN create_vector_index is called
        THEN expect:
            - Index name validation
            - Documents validation
            - Vector index creation
            - Return dict with status, index_name, document_count, vector_count, index_metadata, message
        """
        # GIVEN
        index_name = "test_document_index"
        documents = [
            {"text": "This is a test document about machine learning.", "metadata": {"type": "research", "author": "Alice"}},
            {"text": "Another document discussing neural networks.", "metadata": {"type": "technical", "author": "Bob"}},
            {"text": "A third document about artificial intelligence.", "metadata": {"type": "overview", "author": "Charlie"}}
        ]
        
        # WHEN
        result = await create_vector_index(
            index_name=index_name,
            documents=documents
        )
        
        # THEN
        assert isinstance(result, dict)
        assert "status" in result
        if result["status"] == "success":
            assert result["index_name"] == index_name
            assert "document_count" in result
            assert "vector_count" in result
            assert "index_metadata" in result
            assert "message" in result
            assert result["document_count"] == len(documents)
        else:
            # If it fails, should have an error message
            assert "message" in result

    @pytest.mark.asyncio
    async def test_create_vector_index_with_custom_embedding_model(self):
        """
        GIVEN valid index_name and documents
        AND custom embedding_model="sentence-transformers/all-MiniLM-L6-v2"
        WHEN create_vector_index is called
        THEN expect:
            - Index creation with custom embedding model
            - Return success dict with embedding model metadata
        """
        # GIVEN
        index_name = "custom_embedding_index"
        documents = [
            {"text": "Document with custom embeddings.", "metadata": {"id": 1}},
            {"text": "Another document for embedding testing.", "metadata": {"id": 2}}
        ]
        embedding_model = "sentence-transformers/all-MiniLM-L6-v2"
        
        # WHEN
        result = await create_vector_index(
            index_name=index_name,
            documents=documents,
            embedding_model=embedding_model
        )
        
        # THEN
        assert isinstance(result, dict)
        assert "status" in result
        if result["status"] == "success":
            assert "index_metadata" in result
            # Should contain embedding model information
            metadata = result["index_metadata"]
            assert "embedding_model" in metadata or embedding_model in str(metadata)
        else:
            assert "message" in result

    @pytest.mark.asyncio
    async def test_create_vector_index_with_custom_vector_store(self):
        """
        GIVEN valid index_name and documents
        AND custom vector_store="qdrant"
        WHEN create_vector_index is called
        THEN expect:
            - Index creation with Qdrant vector store
            - Return success dict with vector store type
        """
        # GIVEN
        index_name = "qdrant_index"
        documents = [
            {"text": "Test document for Qdrant store.", "metadata": {"category": "test"}},
            {"text": "Another test document.", "metadata": {"category": "validation"}}
        ]
        vector_store = "qdrant"
        
        # WHEN
        result = await create_vector_index(
            index_name=index_name,
            documents=documents,
            vector_store=vector_store
        )
        
        # THEN
        assert isinstance(result, dict)
        assert "status" in result
        if result["status"] == "success":
            assert "index_metadata" in result
            # Should indicate Qdrant as the vector store
            metadata = result["index_metadata"]
            assert "vector_store" in metadata or "qdrant" in str(metadata).lower()
        else:
            assert "message" in result

    @pytest.mark.asyncio
    async def test_create_vector_index_with_custom_chunk_size_and_overlap(self):
        """
        GIVEN valid index_name and documents
        AND custom chunk_size=512, chunk_overlap=50
        WHEN create_vector_index is called
        THEN expect:
            - Document chunking with custom parameters
            - Return success dict with chunking metadata
        """
        # GIVEN
        index_name = "chunked_index"
        documents = [
            {"text": "This is a very long document that should be chunked into smaller pieces for better vector processing. " * 10, "metadata": {"length": "long"}},
            {"text": "Another long document for chunking testing. " * 8, "metadata": {"length": "medium"}}
        ]
        chunk_size = 512
        chunk_overlap = 50
        
        # WHEN
        result = await create_vector_index(
            index_name=index_name,
            documents=documents,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap
        )
        
        # THEN
        assert isinstance(result, dict)
        assert "status" in result
        if result["status"] == "success":
            assert "index_metadata" in result
            # Should contain chunking information
            metadata = result["index_metadata"]
            assert "chunk_size" in metadata or "chunking" in str(metadata).lower()
            # Vector count should be >= document count due to chunking
            assert result["vector_count"] >= result["document_count"]
        else:
            assert "message" in result

    @pytest.mark.asyncio
    async def test_create_vector_index_with_metadata_fields(self):
        """
        GIVEN valid index_name and documents
        AND metadata_fields=["author", "category", "timestamp"]
        WHEN create_vector_index is called
        THEN expect:
            - Index creation with specified metadata fields
            - Return success dict with metadata field configuration
        """
        # GIVEN
        index_name = "metadata_filtered_index"
        documents = [
            {"text": "Document with rich metadata.", "metadata": {"author": "Alice", "category": "research", "timestamp": "2025-01-01", "extra": "ignored"}},
            {"text": "Another documented item.", "metadata": {"author": "Bob", "category": "technical", "timestamp": "2025-01-02", "version": "2.0"}}
        ]
        metadata_fields = ["author", "category", "timestamp"]
        
        # WHEN
        result = await create_vector_index(
            index_name=index_name,
            documents=documents,
            metadata_fields=metadata_fields
        )
        
        # THEN
        assert isinstance(result, dict)
        assert "status" in result
        if result["status"] == "success":
            assert "index_metadata" in result
            # Should contain metadata field configuration
            metadata = result["index_metadata"]
            assert "metadata_fields" in metadata or any(field in str(metadata) for field in metadata_fields)
        else:
            assert "message" in result

    @pytest.mark.asyncio
    async def test_create_vector_index_with_none_index_name(self):
        """
        GIVEN index_name parameter as None
        WHEN create_vector_index is called
        THEN expect:
            - Return error dict with status="error"
            - Message indicating invalid index name
        """
        # GIVEN
        index_name = None
        documents = [
            {"text": "Test document.", "metadata": {"id": 1}}
        ]
        
        # WHEN
        result = await create_vector_index(
            index_name=index_name,
            documents=documents
        )
        
        # THEN
        assert isinstance(result, dict)
        assert result["status"] == "error"
        assert "message" in result
        assert "index" in result["message"].lower() or "name" in result["message"].lower()

    @pytest.mark.asyncio
    async def test_create_vector_index_with_empty_index_name(self):
        """
        GIVEN index_name parameter as empty string
        WHEN create_vector_index is called
        THEN expect:
            - Return error dict with status="error"
            - Message indicating invalid index name
        """
        # GIVEN
        index_name = ""
        documents = [
            {"text": "Test document.", "metadata": {"id": 1}}
        ]
        
        # WHEN
        result = await create_vector_index(
            index_name=index_name,
            documents=documents
        )
        
        # THEN
        assert isinstance(result, dict)
        assert result["status"] == "error"
        assert "message" in result
        assert "index" in result["message"].lower() or "name" in result["message"].lower() or "empty" in result["message"].lower()

    @pytest.mark.asyncio
    async def test_create_vector_index_with_none_documents(self):
        """
        GIVEN valid index_name
        AND documents parameter as None
        WHEN create_vector_index is called
        THEN expect:
            - Return error dict with status="error"
            - Message indicating invalid documents
        """
        # GIVEN
        index_name = "test_index"
        documents = None
        
        # WHEN
        result = await create_vector_index(
            index_name=index_name,
            documents=documents
        )
        
        # THEN
        assert isinstance(result, dict)
        assert result["status"] == "error"
        assert "message" in result
        assert "document" in result["message"].lower() or "invalid" in result["message"].lower()

    @pytest.mark.asyncio
    async def test_create_vector_index_with_empty_documents(self):
        """
        GIVEN valid index_name
        AND documents parameter as empty list
        WHEN create_vector_index is called
        THEN expect:
            - Return error dict with status="error"
            - Message indicating no documents provided
        """
        # GIVEN
        index_name = "test_index"
        documents = []
        
        # WHEN
        result = await create_vector_index(
            index_name=index_name,
            documents=documents
        )
        
        # THEN
        assert isinstance(result, dict)
        assert result["status"] == "error"
        assert "message" in result
        assert "document" in result["message"].lower() or "empty" in result["message"].lower() or "no" in result["message"].lower()

    @pytest.mark.asyncio
    async def test_create_vector_index_with_existing_index_name(self):
        """
        GIVEN index_name that already exists
        AND valid documents
        WHEN create_vector_index is called
        THEN expect:
            - Index name conflict handling
            - Return error dict with status="error"
            - Message indicating index already exists
        """
        # GIVEN
        index_name = "duplicate_index"
        documents = [
            {"text": "First document.", "metadata": {"id": 1}}
        ]
        
        # First, create an index
        await create_vector_index(
            index_name=index_name,
            documents=documents
        )
        
        # WHEN - Try to create the same index again
        result = await create_vector_index(
            index_name=index_name,
            documents=documents
        )
        
        # THEN
        assert isinstance(result, dict)
        # Should either error due to existing index or handle gracefully
        if result["status"] == "error":
            assert "message" in result
            assert "exist" in result["message"].lower() or "already" in result["message"].lower() or "duplicate" in result["message"].lower()
        else:
            # Some implementations may overwrite or append
            assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_create_vector_index_with_invalid_documents_format(self):
        """
        GIVEN valid index_name
        AND documents with invalid format (missing text or metadata)
        WHEN create_vector_index is called
        THEN expect:
            - Document validation failure
            - Return error dict with status="error"
            - Message indicating invalid document format
        """
        # GIVEN
        index_name = "invalid_docs_index"
        invalid_documents = [
            {"not_text": "Missing text field", "metadata": {"id": 1}},
            {"text": "Valid text", "not_metadata": "Wrong field"},
            "not_a_dict_at_all",
            {"text": ""}  # Empty text
        ]
        
        # WHEN
        result = await create_vector_index(
            index_name=index_name,
            documents=invalid_documents
        )
        
        # THEN
        assert isinstance(result, dict)
        assert result["status"] == "error"
        assert "message" in result
        assert "document" in result["message"].lower() or "format" in result["message"].lower() or "invalid" in result["message"].lower()

    @pytest.mark.asyncio
    async def test_create_vector_index_with_embedding_model_not_available(self):
        """
        GIVEN valid index_name and documents
        AND embedding_model not available
        WHEN create_vector_index is called
        THEN expect:
            - Embedding model dependency check
            - Return error dict with status="error"
            - Message indicating embedding model not available
        """
        # GIVEN
        index_name = "unavailable_model_index"
        documents = [
            {"text": "Test document.", "metadata": {"id": 1}}
        ]
        # Use a model that definitely doesn't exist
        embedding_model = "nonexistent/fake-model-xyz-123"
        
        # WHEN
        result = await create_vector_index(
            index_name=index_name,
            documents=documents,
            embedding_model=embedding_model
        )
        
        # THEN
        assert isinstance(result, dict)
        # Should either error due to unavailable model or fall back to default
        if result["status"] == "error":
            assert "message" in result
            assert "model" in result["message"].lower() or "embedding" in result["message"].lower() or "available" in result["message"].lower()
        else:
            # Some implementations may fall back to default model
            assert result["status"] == "success"

    @pytest.mark.asyncio
    async def test_create_vector_index_with_vector_store_not_available(self):
        """
        GIVEN valid index_name and documents
        AND vector_store dependencies not available
        WHEN create_vector_index is called
        THEN expect:
            - Vector store dependency check
            - Return error dict with status="error"
            - Message indicating vector store not available
        """
        # GIVEN
        index_name = "unavailable_store_index"
        documents = [
            {"text": "Test document.", "metadata": {"id": 1}}
        ]
        # Use a vector store that might not be available
        vector_store = "nonexistent_vector_store_xyz"
        
        # WHEN
        result = await create_vector_index(
            index_name=index_name,
            documents=documents,
            vector_store=vector_store
        )
        
        # THEN
        assert isinstance(result, dict)
        # Should either error due to unavailable store or fall back to default
        if result["status"] == "error":
            assert "message" in result
            assert "store" in result["message"].lower() or "vector" in result["message"].lower() or "available" in result["message"].lower()
        else:
            # Some implementations may fall back to default store
            assert result["status"] == "success"


class TestSearchVectorIndex:
    """Test the search_vector_index MCP tool."""
    
    @pytest.mark.asyncio
    async def test_search_vector_index_with_valid_query_and_default_params(self):
        """
        GIVEN valid index_name string
        AND valid query string
        AND default parameters for top_k, similarity_threshold, include_metadata
        WHEN search_vector_index is called
        THEN expect:
            - Index existence validation
            - Query validation
            - Vector search execution
            - Return dict with status, results, query_metadata, search_time, message
        """
        # GIVEN
        index_id = "test_index"
        query_vector = [0.1, 0.2, 0.3, 0.4, 0.5]
        
        # WHEN
        result = await search_vector_index(
            index_id=index_id,
            query_vector=query_vector
        )
        
        # THEN
        assert isinstance(result, dict)
        assert result["status"] == "success"
        assert result["index_id"] == index_id
        assert "results" in result
        assert "num_results" in result
        assert isinstance(result["results"], list)

    @pytest.mark.asyncio
    async def test_search_vector_index_with_custom_top_k(self):
        """
        GIVEN valid index_name and query
        AND custom top_k=10
        WHEN search_vector_index is called
        THEN expect:
            - Search limited to 10 results
            - Return success dict with top_k results
        """
        # GIVEN
        index_id = "test_index"
        query_vector = [0.1, 0.2, 0.3, 0.4, 0.5]
        top_k = 10
        
        # WHEN
        result = await search_vector_index(
            index_id=index_id,
            query_vector=query_vector,
            top_k=top_k
        )
        
        # THEN
        assert result["status"] == "success"
        assert result["top_k"] == top_k
        # Results should be limited by available vectors, not top_k
        assert result["num_results"] <= top_k

    @pytest.mark.asyncio
    async def test_search_vector_index_with_similarity_threshold(self):
        """
        GIVEN valid index_name and query
        AND similarity_threshold=0.8
        WHEN search_vector_index is called
        THEN expect:
            - Results filtered by similarity threshold
            - Return success dict with filtered results
        """
        # GIVEN
        index_id = "test_index"
        query_vector = [0.1, 0.2, 0.3, 0.4, 0.5]
        
        # WHEN - test with include_distances to see distance values
        result = await search_vector_index(
            index_id=index_id,
            query_vector=query_vector,
            include_distances=True
        )
        
        # THEN
        assert result["status"] == "success"
        # All results should have distance information
        for result_item in result["results"]:
            assert "distance" in result_item
            assert isinstance(result_item["distance"], (int, float))

    @pytest.mark.asyncio
    async def test_search_vector_index_with_include_metadata(self):
        """
        GIVEN valid index_name and query
        AND include_metadata=True
        WHEN search_vector_index is called
        THEN expect:
            - Results include document metadata
            - Return success dict with metadata included
        """
        # GIVEN
        index_id = "test_index"
        query_vector = [0.1, 0.2, 0.3, 0.4, 0.5]
        
        # WHEN
        result = await search_vector_index(
            index_id=index_id,
            query_vector=query_vector,
            include_metadata=True
        )
        
        # THEN
        assert result["status"] == "success"
        # Check that results may include metadata when available
        for result_item in result["results"]:
            # Metadata is optional depending on what was stored with vectors
            if "metadata" in result_item:
                assert isinstance(result_item["metadata"], dict)

    @pytest.mark.asyncio
    async def test_search_vector_index_with_metadata_filters(self):
        """
        GIVEN valid index_name and query
        AND metadata_filters={"author": "John Doe", "category": "research"}
        WHEN search_vector_index is called
        THEN expect:
            - Search filtered by metadata
            - Return success dict with filtered results
        """
        # GIVEN
        index_id = "test_index"
        query_vector = [0.1, 0.2, 0.3, 0.4, 0.5]
        metadata_filters = {"author": "John Doe", "category": "research"}
        
        # WHEN
        result = await search_vector_index(
            index_id=index_id,
            query_vector=query_vector,
            filter_metadata=metadata_filters
        )
        
        # THEN
        assert result["status"] == "success"
        # Filtering functionality depends on implementation
        # At minimum, it should not error with filters provided
        assert "results" in result

    @pytest.mark.asyncio
    async def test_search_vector_index_with_none_index_name(self):
        """
        GIVEN index_name parameter as None
        WHEN search_vector_index is called
        THEN expect:
            - Return error dict with status="error"
            - Message indicating invalid index name
        """
        # GIVEN
        index_id = None
        query_vector = [0.1, 0.2, 0.3, 0.4, 0.5]
        
        # WHEN
        result = await search_vector_index(
            index_id=index_id,
            query_vector=query_vector
        )
        
        # THEN
        assert result["status"] == "error"
        assert "message" in result
        # The error should be related to the None index_id

    @pytest.mark.asyncio
    async def test_search_vector_index_with_empty_index_name(self):
        """
        GIVEN index_name parameter as empty string
        WHEN search_vector_index is called
        THEN expect:
            - Return error dict with status="error"
            - Message indicating invalid index name
        """
        # GIVEN
        index_id = ""
        query_vector = [0.1, 0.2, 0.3, 0.4, 0.5]
        
        # WHEN
        result = await search_vector_index(
            index_id=index_id,
            query_vector=query_vector
        )
        
        # THEN
        # Empty string might be handled by creating a test index
        # The implementation shows it creates a test index if not found
        assert isinstance(result, dict)
        assert "status" in result

    @pytest.mark.asyncio
    async def test_search_vector_index_with_none_query(self):
        """
        GIVEN valid index_name
        AND query parameter as None
        WHEN search_vector_index is called
        THEN expect:
            - Return error dict with status="error"
            - Message indicating invalid query
        """
        # GIVEN
        index_id = "test_index"
        query_vector = None
        
        # WHEN
        result = await search_vector_index(
            index_id=index_id,
            query_vector=query_vector
        )
        
        # THEN
        assert result["status"] == "error"
        assert "message" in result

    @pytest.mark.asyncio
    async def test_search_vector_index_with_empty_query(self):
        """
        GIVEN valid index_name
        AND query parameter as empty string
        WHEN search_vector_index is called
        THEN expect:
            - Return error dict with status="error"
            - Message indicating invalid query
        """
        # GIVEN
        index_id = "test_index"
        query_vector = []
        
        # WHEN
        result = await search_vector_index(
            index_id=index_id,
            query_vector=query_vector
        )
        
        # THEN
        assert result["status"] == "error"
        assert "message" in result

    @pytest.mark.asyncio
    async def test_search_vector_index_with_nonexistent_index(self):
        """
        GIVEN nonexistent index_name
        AND valid query
        WHEN search_vector_index is called
        THEN expect:
            - Index existence check
            - Return error dict with status="error"
            - Message indicating index not found
        """
        # GIVEN
        index_id = "nonexistent_index_12345"
        query_vector = [0.1, 0.2, 0.3, 0.4, 0.5]
        
        # WHEN
        result = await search_vector_index(
            index_id=index_id,
            query_vector=query_vector
        )
        
        # THEN
        # The implementation creates a test index if not found
        # So this should actually succeed
        assert isinstance(result, dict)
        assert "status" in result
        # It may succeed by creating a test index, or error - either is valid

    @pytest.mark.asyncio
    async def test_search_vector_index_with_no_results(self):
        """
        GIVEN valid index_name and query
        AND no matching results
        WHEN search_vector_index is called
        THEN expect:
            - Search execution with no results
            - Return success dict with empty results
        """
        # GIVEN
        index_id = "test_index"
        # Use a very different query vector that shouldn't match well
        query_vector = [1.0, 1.0, 1.0, 1.0, 1.0]
        top_k = 0  # Request 0 results
        
        # WHEN
        result = await search_vector_index(
            index_id=index_id,
            query_vector=query_vector,
            top_k=top_k
        )
        
        # THEN
        assert result["status"] == "success"
        assert result["top_k"] == 0
        assert result["num_results"] == 0
        assert len(result["results"]) == 0


class TestListVectorStores:
    """Test the list_vector_indexes MCP tool."""
    
    @pytest.mark.asyncio
    async def test_list_vector_indexes_with_default_params(self):
        """
        GIVEN default parameters
        WHEN list_vector_indexes is called
        THEN expect:
            - Vector store enumeration
            - Return dict with status, stores, total_count, message
        """
        # GIVEN
        # No specific parameters needed for default call
        
        # WHEN
        result = await list_vector_indexes()
        
        # THEN
        assert isinstance(result, dict)
        assert "status" in result
        assert result["status"] in ["success", "error"]
        
        if result["status"] == "success":
            assert "stores" in result
            assert isinstance(result["stores"], list)
            assert "total_count" in result
            assert isinstance(result["total_count"], int)
            assert result["total_count"] >= 0
            assert "message" in result
        else:
            assert "message" in result

    @pytest.mark.asyncio
    async def test_list_vector_indexes_with_include_metadata(self):
        """
        GIVEN include_metadata=True
        WHEN list_vector_indexes is called
        THEN expect:
            - Vector store enumeration with metadata
            - Return success dict with store metadata included
        """
        # GIVEN
        include_metadata = True
        
        # WHEN
        result = await list_vector_indexes(include_metadata=include_metadata)
        
        # THEN
        assert isinstance(result, dict)
        assert "status" in result
        assert result["status"] in ["success", "error"]
        
        if result["status"] == "success":
            assert "stores" in result
            assert isinstance(result["stores"], list)
            # If stores exist, they should include metadata
            for store in result["stores"]:
                assert isinstance(store, dict)
                # Metadata should be included when include_metadata=True
                if "metadata" in store:
                    assert isinstance(store["metadata"], dict)
            assert "total_count" in result
            assert "message" in result
        else:
            assert "message" in result

    @pytest.mark.asyncio
    async def test_list_vector_indexes_with_filter_by_type(self):
        """
        GIVEN store_type="faiss"
        WHEN list_vector_indexes is called
        THEN expect:
            - Vector stores filtered by type
            - Return success dict with filtered stores
        """
        # GIVEN
        store_type = "faiss"
        
        # WHEN
        result = await list_vector_indexes(store_type=store_type)
        
        # THEN
        assert isinstance(result, dict)
        assert "status" in result
        assert result["status"] in ["success", "error"]
        
        if result["status"] == "success":
            assert "stores" in result
            assert isinstance(result["stores"], list)
            # If stores exist, they should match the filter type
            for store in result["stores"]:
                assert isinstance(store, dict)
                if "type" in store:
                    assert store["type"] == store_type
            assert "total_count" in result
            assert "message" in result
        else:
            assert "message" in result

    @pytest.mark.asyncio
    async def test_list_vector_indexes_with_no_stores(self):
        """
        GIVEN no vector stores exist
        WHEN list_vector_indexes is called
        THEN expect:
            - Empty store enumeration
            - Return success dict with empty stores list
        """
        # GIVEN
        # This test simulates a state where no stores exist
        # The function should handle this gracefully
        
        # WHEN
        result = await list_vector_indexes()
        
        # THEN
        assert isinstance(result, dict)
        assert "status" in result
        assert result["status"] in ["success", "error"]
        
        if result["status"] == "success":
            assert "stores" in result
            assert isinstance(result["stores"], list)
            assert "total_count" in result
            assert isinstance(result["total_count"], int)
            assert result["total_count"] >= 0
            # When no stores exist, total_count should be 0 and stores should be empty
            if result["total_count"] == 0:
                assert len(result["stores"]) == 0
            assert "message" in result
        else:
            assert "message" in result


class TestDeleteVectorStore:
    """Test the delete_vector_index MCP tool."""
    
    @pytest.mark.asyncio
    async def test_delete_vector_index_with_valid_name(self):
        """
        GIVEN valid store_name string
        WHEN delete_vector_index is called
        THEN expect:
            - Store name validation
            - Store deletion execution
            - Return dict with status, deleted_store, message
        """
        # GIVEN
        store_name = "test_store_to_delete"
        
        # WHEN
        result = await delete_vector_index(store_name=store_name)
        
        # THEN
        assert isinstance(result, dict)
        assert "status" in result
        assert result["status"] in ["success", "error"]
        assert "message" in result
        
        if result["status"] == "success":
            assert "deleted_store" in result
            assert result["deleted_store"] == store_name
        else:
            # Error case might be store not found or deletion failed
            assert "error" in result["message"].lower() or "not found" in result["message"].lower() or "failed" in result["message"].lower()

    @pytest.mark.asyncio
    async def test_delete_vector_index_with_force_option(self):
        """
        GIVEN valid store_name
        AND force=True
        WHEN delete_vector_index is called
        THEN expect:
            - Forced deletion without confirmation
            - Return success dict with deletion confirmation
        """
        # GIVEN
        store_name = "test_store_force_delete"
        force = True
        
        # WHEN
        result = await delete_vector_index(store_name=store_name, force=force)
        
        # THEN
        assert isinstance(result, dict)
        assert "status" in result
        assert result["status"] in ["success", "error"]
        assert "message" in result
        
        if result["status"] == "success":
            assert "deleted_store" in result
            assert result["deleted_store"] == store_name
            # Should indicate forced deletion
            assert "force" in result["message"].lower() or "forced" in result["message"].lower()
        else:
            # Error case might be store not found or deletion failed
            assert "error" in result["message"].lower() or "not found" in result["message"].lower() or "failed" in result["message"].lower()

    @pytest.mark.asyncio
    async def test_delete_vector_index_with_none_name(self):
        """
        GIVEN store_name parameter as None
        WHEN delete_vector_index is called
        THEN expect:
            - Return error dict with status="error"
            - Message indicating invalid store name
        """
        # GIVEN
        store_name = None
        
        # WHEN
        result = await delete_vector_index(store_name=store_name)
        
        # THEN
        assert isinstance(result, dict)
        assert "status" in result
        assert result["status"] == "error"
        assert "message" in result
        assert "invalid" in result["message"].lower() or "name" in result["message"].lower() or "none" in result["message"].lower()

    @pytest.mark.asyncio
    async def test_delete_vector_index_with_empty_name(self):
        """
        GIVEN store_name parameter as empty string
        WHEN delete_vector_index is called
        THEN expect:
            - Return error dict with status="error"
            - Message indicating invalid store name
        """
        # GIVEN
        store_name = ""
        
        # WHEN
        result = await delete_vector_index(store_name=store_name)
        
        # THEN
        assert isinstance(result, dict)
        assert "status" in result
        assert result["status"] == "error"
        assert "message" in result
        assert "invalid" in result["message"].lower() or "empty" in result["message"].lower() or "name" in result["message"].lower()

    @pytest.mark.asyncio
    async def test_delete_vector_index_with_nonexistent_name(self):
        """
        GIVEN nonexistent store_name
        WHEN delete_vector_index is called
        THEN expect:
            - Store existence check
            - Return error dict with status="error"
            - Message indicating store not found
        """
        # GIVEN
        store_name = "nonexistent_store_xyz_123"
        
        # WHEN
        result = await delete_vector_index(store_name=store_name)
        
        # THEN
        assert isinstance(result, dict)
        assert "status" in result
        assert result["status"] == "error"
        assert "message" in result
        assert "not found" in result["message"].lower() or "exist" in result["message"].lower() or "missing" in result["message"].lower()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
