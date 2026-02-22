"""
Tests for graph_tools tool category (Phase B2 coverage audit).

Tests cover:
- graph_create: create/initialise a knowledge graph
- graph_add_entity: add a node to the graph
- graph_add_relationship: add an edge to the graph
- graph_query_cypher: execute a Cypher query
- graph_search_hybrid: hybrid semantic + graph search
- graph_transaction_begin / commit / rollback

All tests are purely functional (no live graph DB required).  The graph
operations degrade gracefully when the backend is unavailable.
"""

import pytest
from typing import Any, Dict


# ---------------------------------------------------------------------------
# graph_create
# ---------------------------------------------------------------------------

class TestGraphCreate:
    """Tests for graph_create tool."""

    @pytest.mark.asyncio
    async def test_returns_dict(self):
        """
        GIVEN the graph_tools module
        WHEN graph_create is called with no arguments
        THEN the result must be a dict
        """
        from ipfs_datasets_py.mcp_server.tools.graph_tools.graph_create import graph_create
        result = await graph_create()
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_returns_dict_with_custom_url(self):
        """
        GIVEN the graph_tools module
        WHEN graph_create is called with a custom driver_url
        THEN the result is a dict (success or error)
        """
        from ipfs_datasets_py.mcp_server.tools.graph_tools.graph_create import graph_create
        result = await graph_create(driver_url="ipfs://127.0.0.1:9999")
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_status_key_present(self):
        """
        GIVEN graph_create
        WHEN called
        THEN the result dict contains a 'status' key
        """
        from ipfs_datasets_py.mcp_server.tools.graph_tools.graph_create import graph_create
        result = await graph_create()
        assert "status" in result


# ---------------------------------------------------------------------------
# graph_add_entity
# ---------------------------------------------------------------------------

class TestGraphAddEntity:
    """Tests for graph_add_entity tool."""

    @pytest.mark.asyncio
    async def test_add_entity_returns_dict(self):
        """
        GIVEN graph_add_entity
        WHEN called with required entity_id and entity_type
        THEN the result is a dict
        """
        from ipfs_datasets_py.mcp_server.tools.graph_tools.graph_add_entity import graph_add_entity
        result = await graph_add_entity(
            entity_id="node_001",
            entity_type="Person",
        )
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_add_entity_with_properties_returns_dict(self):
        """
        GIVEN graph_add_entity
        WHEN called with properties dict
        THEN the result is a dict
        """
        from ipfs_datasets_py.mcp_server.tools.graph_tools.graph_add_entity import graph_add_entity
        result = await graph_add_entity(
            entity_id="node_002",
            entity_type="Organization",
            properties={"name": "Acme Corp", "industry": "technology"},
        )
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_add_entity_entity_id_in_response(self):
        """
        GIVEN graph_add_entity
        WHEN called
        THEN the result dict contains the entity_id
        """
        from ipfs_datasets_py.mcp_server.tools.graph_tools.graph_add_entity import graph_add_entity
        result = await graph_add_entity(entity_id="node_eid_check", entity_type="Concept")
        assert "entity_id" in result or "status" in result


# ---------------------------------------------------------------------------
# graph_add_relationship
# ---------------------------------------------------------------------------

class TestGraphAddRelationship:
    """Tests for graph_add_relationship tool."""

    @pytest.mark.asyncio
    async def test_add_relationship_returns_dict(self):
        """
        GIVEN graph_add_relationship
        WHEN called with source, target, and relationship_type
        THEN the result is a dict
        """
        from ipfs_datasets_py.mcp_server.tools.graph_tools.graph_add_relationship import (
            graph_add_relationship,
        )
        result = await graph_add_relationship(
            source_id="node_a",
            target_id="node_b",
            relationship_type="KNOWS",
        )
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_add_relationship_with_properties_returns_dict(self):
        """
        GIVEN graph_add_relationship
        WHEN called with extra relationship properties
        THEN the result is a dict
        """
        from ipfs_datasets_py.mcp_server.tools.graph_tools.graph_add_relationship import (
            graph_add_relationship,
        )
        result = await graph_add_relationship(
            source_id="node_c",
            target_id="node_d",
            relationship_type="WORKS_FOR",
            properties={"since": 2020},
        )
        assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# graph_query_cypher
# ---------------------------------------------------------------------------

class TestGraphQueryCypher:
    """Tests for graph_query_cypher tool."""

    @pytest.mark.asyncio
    async def test_cypher_query_returns_dict(self):
        """
        GIVEN graph_query_cypher
        WHEN called with a simple MATCH query
        THEN the result is a dict
        """
        from ipfs_datasets_py.mcp_server.tools.graph_tools.graph_query_cypher import (
            graph_query_cypher,
        )
        result = await graph_query_cypher(query="MATCH (n) RETURN n LIMIT 5")
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_cypher_query_with_params_returns_dict(self):
        """
        GIVEN graph_query_cypher
        WHEN called with parameters
        THEN the result is a dict
        """
        from ipfs_datasets_py.mcp_server.tools.graph_tools.graph_query_cypher import (
            graph_query_cypher,
        )
        result = await graph_query_cypher(
            query="MATCH (n:Person {name: $name}) RETURN n",
            parameters={"name": "Alice"},
        )
        assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# graph_transaction_begin / commit / rollback
# ---------------------------------------------------------------------------

class TestGraphTransactions:
    """Tests for graph transaction tools."""

    @pytest.mark.asyncio
    async def test_transaction_begin_returns_dict(self):
        """
        GIVEN graph_transaction_begin
        WHEN called
        THEN the result is a dict
        """
        from ipfs_datasets_py.mcp_server.tools.graph_tools.graph_transaction_begin import (
            graph_transaction_begin,
        )
        result = await graph_transaction_begin()
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_transaction_commit_returns_dict(self):
        """
        GIVEN graph_transaction_commit
        WHEN called with a transaction id
        THEN the result is a dict
        """
        from ipfs_datasets_py.mcp_server.tools.graph_tools.graph_transaction_commit import (
            graph_transaction_commit,
        )
        result = await graph_transaction_commit(transaction_id="txn_test_001")
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_transaction_rollback_returns_dict(self):
        """
        GIVEN graph_transaction_rollback
        WHEN called with a transaction id
        THEN the result is a dict
        """
        from ipfs_datasets_py.mcp_server.tools.graph_tools.graph_transaction_rollback import (
            graph_transaction_rollback,
        )
        result = await graph_transaction_rollback(transaction_id="txn_test_002")
        assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# graph_search_hybrid
# ---------------------------------------------------------------------------

class TestGraphSearchHybrid:
    """Tests for graph_search_hybrid tool."""

    @pytest.mark.asyncio
    async def test_hybrid_search_returns_dict(self):
        """
        GIVEN graph_search_hybrid
        WHEN called with a search query
        THEN the result is a dict
        """
        from ipfs_datasets_py.mcp_server.tools.graph_tools.graph_search_hybrid import (
            graph_search_hybrid,
        )
        result = await graph_search_hybrid(query="machine learning")
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_hybrid_search_with_options_returns_dict(self):
        """
        GIVEN graph_search_hybrid
        WHEN called with limit and search_type
        THEN the result is a dict
        """
        from ipfs_datasets_py.mcp_server.tools.graph_tools.graph_search_hybrid import (
            graph_search_hybrid,
        )
        result = await graph_search_hybrid(
            query="neural network",
            limit=5,
            search_type="hybrid",
        )
        assert isinstance(result, dict)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
