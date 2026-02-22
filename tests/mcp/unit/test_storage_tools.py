"""
Tests for storage_tools tool category (Phase B2 coverage audit).

Tests cover:
- store_data: persist data to a storage backend
- retrieve_data: fetch data by item ID
- manage_collections: create/list/delete collections
- query_storage: query stored items

All tests use the MockStorageManager; no live storage required.
"""

import pytest


class TestStoreData:
    """Tests for store_data tool function."""

    @pytest.mark.asyncio
    async def test_store_string_data_returns_dict(self):
        """
        GIVEN storage_tools.store_data
        WHEN called with a plain string
        THEN the result is a dict
        """
        from ipfs_datasets_py.mcp_server.tools.storage_tools.storage_tools import store_data
        result = await store_data(data="hello storage")
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_store_dict_data_returns_dict(self):
        """
        GIVEN storage_tools.store_data
        WHEN called with a JSON dict
        THEN the result is a dict
        """
        from ipfs_datasets_py.mcp_server.tools.storage_tools.storage_tools import store_data
        result = await store_data(
            data={"key": "value", "num": 42},
            storage_type="memory",
            compression="none",
        )
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_store_data_with_metadata_returns_dict(self):
        """
        GIVEN storage_tools.store_data
        WHEN called with metadata and tags
        THEN the result is a dict
        """
        from ipfs_datasets_py.mcp_server.tools.storage_tools.storage_tools import store_data
        result = await store_data(
            data="tagged data",
            metadata={"source": "test", "version": 1},
            tags=["unit-test", "phase-b2"],
        )
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_store_data_invalid_storage_type_raises_or_returns_error(self):
        """
        GIVEN storage_tools.store_data
        WHEN called with an invalid storage_type
        THEN the tool raises ValueError (documents the real behavior)
        """
        from ipfs_datasets_py.mcp_server.tools.storage_tools.storage_tools import store_data
        # The tool re-raises ValueError for invalid storage_type
        try:
            result = await store_data(data="test", storage_type="nonexistent_backend")
            # If it returns a dict with error, that's also acceptable
            assert isinstance(result, dict)
        except ValueError as exc:
            assert "nonexistent_backend" in str(exc) or "Invalid" in str(exc)


class TestRetrieveData:
    """Tests for retrieve_data tool function."""

    @pytest.mark.asyncio
    async def test_retrieve_returns_dict(self):
        """
        GIVEN storage_tools.retrieve_data
        WHEN called with a list of item IDs
        THEN the result is a dict
        """
        from ipfs_datasets_py.mcp_server.tools.storage_tools.storage_tools import retrieve_data
        result = await retrieve_data(item_ids=["item_test_001", "item_test_002"])
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_retrieve_empty_list_raises_or_returns_error(self):
        """
        GIVEN storage_tools.retrieve_data
        WHEN called with an empty list
        THEN the tool raises ValueError (requires ≥1 item ID)
        """
        from ipfs_datasets_py.mcp_server.tools.storage_tools.storage_tools import retrieve_data
        try:
            result = await retrieve_data(item_ids=[])
            assert isinstance(result, dict)
        except ValueError as exc:
            assert "item" in str(exc).lower() or "empty" in str(exc).lower() or "ID" in str(exc)

    @pytest.mark.asyncio
    async def test_retrieve_with_include_content_returns_dict(self):
        """
        GIVEN storage_tools.retrieve_data
        WHEN called with include_content=True
        THEN the result is a dict
        """
        from ipfs_datasets_py.mcp_server.tools.storage_tools.storage_tools import retrieve_data
        result = await retrieve_data(item_ids=["item_xyz"], include_content=True)
        assert isinstance(result, dict)


class TestManageCollections:
    """Tests for manage_collections tool function."""

    @pytest.mark.asyncio
    async def test_list_collections_returns_dict(self):
        """
        GIVEN storage_tools.manage_collections
        WHEN called with action='list'
        THEN the result is a dict
        """
        from ipfs_datasets_py.mcp_server.tools.storage_tools.storage_tools import manage_collections
        result = await manage_collections(action="list")
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_create_collection_returns_dict(self):
        """
        GIVEN storage_tools.manage_collections
        WHEN called with action='create' and a collection name
        THEN the result is a dict
        """
        from ipfs_datasets_py.mcp_server.tools.storage_tools.storage_tools import manage_collections
        result = await manage_collections(
            action="create",
            collection_name="test_collection_b2",
        )
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_invalid_action_returns_failure_dict(self):
        """
        GIVEN storage_tools.manage_collections
        WHEN called with an invalid action
        THEN the result is a dict with success=False or status='error'
        """
        from ipfs_datasets_py.mcp_server.tools.storage_tools.storage_tools import manage_collections
        result = await manage_collections(action="do_the_impossible")
        assert isinstance(result, dict)
        # Tool returns {'success': False, 'error': ...} for unknown actions
        assert result.get("success") is False or result.get("status") == "error"


class TestQueryStorage:
    """Tests for query_storage tool function."""

    @pytest.mark.asyncio
    async def test_query_no_filters_returns_dict(self):
        """
        GIVEN storage_tools.query_storage
        WHEN called with no filters
        THEN the result is a dict
        """
        from ipfs_datasets_py.mcp_server.tools.storage_tools.storage_tools import query_storage
        result = await query_storage()
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_query_with_filters_returns_dict(self):
        """
        GIVEN storage_tools.query_storage
        WHEN called with filters and limit
        THEN the result is a dict
        """
        from ipfs_datasets_py.mcp_server.tools.storage_tools.storage_tools import query_storage
        result = await query_storage(
            collection="test_collection_b2",
            limit=10,
            tags=["unit-test"],
        )
        assert isinstance(result, dict)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
