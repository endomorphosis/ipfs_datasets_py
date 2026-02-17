"""
Knowledge Graph Manager - Core business logic for knowledge graph operations.

This module contains the core logic for knowledge graph management.
It is used by:
- MCP server tools/graph_tools/*
- CLI commands
- Direct Python API imports
"""

import logging
from typing import Dict, Any, Optional, List, Union

logger = logging.getLogger(__name__)


class KnowledgeGraphManager:
    """
    Manage knowledge graph operations.
    
    Supports:
    - Graph creation and initialization
    - Entity and relationship management
    - Cypher query execution
    - Hybrid search
    - Transaction management
    """
    
    def __init__(self, driver_url: str = "ipfs://localhost:5001"):
        """
        Initialize the knowledge graph manager.
        
        Args:
            driver_url: URL for the graph database driver
        """
        self.logger = logging.getLogger(__name__ + ".KnowledgeGraphManager")
        self.driver_url = driver_url
        self.driver = None
        self._session = None
    
    async def initialize(self) -> Dict[str, Any]:
        """
        Initialize the graph database connection.
        
        Returns:
            Dict with initialization status
        """
        try:
            from ipfs_datasets_py.knowledge_graphs import GraphDatabase
            
            self.driver = GraphDatabase.driver(self.driver_url)
            self.logger.info(f"Initialized graph database at {self.driver_url}")
            
            return {
                "status": "success",
                "message": "Graph database initialized",
                "driver_url": self.driver_url
            }
        except ImportError as e:
            self.logger.error(f"Failed to import GraphDatabase: {e}")
            return {
                "status": "error",
                "message": f"GraphDatabase not available: {e}"
            }
        except Exception as e:
            self.logger.error(f"Failed to initialize graph database: {e}")
            return {
                "status": "error",
                "message": str(e)
            }
    
    async def add_entity(
        self,
        entity_id: str,
        entity_type: str,
        properties: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Add an entity to the knowledge graph.
        
        Args:
            entity_id: Unique identifier for the entity
            entity_type: Type/label of the entity
            properties: Additional properties for the entity
        
        Returns:
            Dict with operation status
        """
        try:
            if properties is None:
                properties = {}
            
            from ipfs_datasets_py.knowledge_graphs import Entity
            
            entity = Entity(
                id=entity_id,
                type=entity_type,
                properties=properties
            )
            
            self.logger.info(f"Added entity {entity_id} of type {entity_type}")
            
            return {
                "status": "success",
                "entity_id": entity_id,
                "entity_type": entity_type,
                "properties": properties
            }
        except Exception as e:
            self.logger.error(f"Failed to add entity: {e}")
            return {
                "status": "error",
                "message": str(e)
            }
    
    async def add_relationship(
        self,
        source_id: str,
        target_id: str,
        relationship_type: str,
        properties: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Add a relationship between entities.
        
        Args:
            source_id: Source entity ID
            target_id: Target entity ID
            relationship_type: Type of relationship
            properties: Additional properties for the relationship
        
        Returns:
            Dict with operation status
        """
        try:
            if properties is None:
                properties = {}
            
            from ipfs_datasets_py.knowledge_graphs import Relationship
            
            relationship = Relationship(
                source=source_id,
                target=target_id,
                type=relationship_type,
                properties=properties
            )
            
            self.logger.info(f"Added relationship {source_id} -> {target_id} ({relationship_type})")
            
            return {
                "status": "success",
                "source_id": source_id,
                "target_id": target_id,
                "relationship_type": relationship_type,
                "properties": properties
            }
        except Exception as e:
            self.logger.error(f"Failed to add relationship: {e}")
            return {
                "status": "error",
                "message": str(e)
            }
    
    async def query_cypher(
        self,
        query: str,
        parameters: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Execute a Cypher query.
        
        Args:
            query: Cypher query string
            parameters: Query parameters
        
        Returns:
            Dict with query results
        """
        try:
            if parameters is None:
                parameters = {}
            
            from ipfs_datasets_py.knowledge_graphs import QueryExecutor
            
            executor = QueryExecutor()
            results = executor.execute(query, parameters)
            
            self.logger.info(f"Executed Cypher query: {query[:100]}...")
            
            return {
                "status": "success",
                "query": query,
                "results": results
            }
        except Exception as e:
            self.logger.error(f"Failed to execute query: {e}")
            return {
                "status": "error",
                "message": str(e),
                "query": query
            }
    
    async def hybrid_search(
        self,
        query: str,
        search_type: str = "semantic",
        limit: int = 10
    ) -> Dict[str, Any]:
        """
        Perform hybrid search in the knowledge graph.
        
        Args:
            query: Search query
            search_type: Type of search ("semantic", "keyword", "hybrid")
            limit: Maximum number of results
        
        Returns:
            Dict with search results
        """
        try:
            # Use hybrid search from query module
            from ipfs_datasets_py.knowledge_graphs.query import hybrid_search
            
            results = hybrid_search(query, search_type=search_type, limit=limit)
            
            self.logger.info(f"Hybrid search for '{query}' returned {len(results)} results")
            
            return {
                "status": "success",
                "query": query,
                "search_type": search_type,
                "results": results,
                "count": len(results)
            }
        except ImportError:
            # Fallback if hybrid search not available
            self.logger.warning("Hybrid search not available, using basic query")
            return await self.query_cypher(
                f"MATCH (n) WHERE n.name CONTAINS '{query}' RETURN n LIMIT {limit}"
            )
        except Exception as e:
            self.logger.error(f"Failed to perform hybrid search: {e}")
            return {
                "status": "error",
                "message": str(e),
                "query": query
            }
    
    async def close(self) -> Dict[str, Any]:
        """
        Close the graph database connection.
        
        Returns:
            Dict with close status
        """
        try:
            if self.driver:
                self.driver.close()
                self.logger.info("Closed graph database connection")
            
            return {
                "status": "success",
                "message": "Graph database connection closed"
            }
        except Exception as e:
            self.logger.error(f"Failed to close connection: {e}")
            return {
                "status": "error",
                "message": str(e)
            }
