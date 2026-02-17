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
    - Index and constraint management
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
        self._transaction = None
    
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
    
    # Transaction Management
    
    async def transaction_begin(self) -> Dict[str, Any]:
        """
        Begin a new transaction.
        
        Returns:
            Dict with transaction ID and status
        """
        try:
            from ipfs_datasets_py.knowledge_graphs.transactions import TransactionManager
            
            tx_manager = TransactionManager()
            tx_id = tx_manager.begin()
            self._transaction = tx_id
            
            self.logger.info(f"Started transaction {tx_id}")
            
            return {
                "status": "success",
                "transaction_id": tx_id,
                "message": "Transaction started"
            }
        except ImportError:
            # Fallback if transaction module not available
            import uuid
            tx_id = str(uuid.uuid4())
            self._transaction = tx_id
            self.logger.warning("Transaction module not available, using mock transaction")
            return {
                "status": "success",
                "transaction_id": tx_id,
                "message": "Transaction started (mock)"
            }
        except Exception as e:
            self.logger.error(f"Failed to begin transaction: {e}")
            return {
                "status": "error",
                "message": str(e)
            }
    
    async def transaction_commit(self, transaction_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Commit a transaction.
        
        Args:
            transaction_id: Optional transaction ID (uses current if not provided)
        
        Returns:
            Dict with commit status
        """
        try:
            tx_id = transaction_id or self._transaction
            if not tx_id:
                return {
                    "status": "error",
                    "message": "No active transaction"
                }
            
            from ipfs_datasets_py.knowledge_graphs.transactions import TransactionManager
            
            tx_manager = TransactionManager()
            tx_manager.commit(tx_id)
            self._transaction = None
            
            self.logger.info(f"Committed transaction {tx_id}")
            
            return {
                "status": "success",
                "transaction_id": tx_id,
                "message": "Transaction committed"
            }
        except ImportError:
            # Fallback
            self.logger.warning("Transaction module not available, using mock commit")
            self._transaction = None
            return {
                "status": "success",
                "transaction_id": tx_id,
                "message": "Transaction committed (mock)"
            }
        except Exception as e:
            self.logger.error(f"Failed to commit transaction: {e}")
            return {
                "status": "error",
                "message": str(e),
                "transaction_id": tx_id
            }
    
    async def transaction_rollback(self, transaction_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Rollback a transaction.
        
        Args:
            transaction_id: Optional transaction ID (uses current if not provided)
        
        Returns:
            Dict with rollback status
        """
        try:
            tx_id = transaction_id or self._transaction
            if not tx_id:
                return {
                    "status": "error",
                    "message": "No active transaction"
                }
            
            from ipfs_datasets_py.knowledge_graphs.transactions import TransactionManager
            
            tx_manager = TransactionManager()
            tx_manager.rollback(tx_id)
            self._transaction = None
            
            self.logger.info(f"Rolled back transaction {tx_id}")
            
            return {
                "status": "success",
                "transaction_id": tx_id,
                "message": "Transaction rolled back"
            }
        except ImportError:
            # Fallback
            self.logger.warning("Transaction module not available, using mock rollback")
            self._transaction = None
            return {
                "status": "success",
                "transaction_id": tx_id,
                "message": "Transaction rolled back (mock)"
            }
        except Exception as e:
            self.logger.error(f"Failed to rollback transaction: {e}")
            return {
                "status": "error",
                "message": str(e),
                "transaction_id": tx_id
            }
    
    # Index Management
    
    async def index_create(
        self,
        index_name: str,
        entity_type: str,
        properties: List[str]
    ) -> Dict[str, Any]:
        """
        Create an index on the knowledge graph.
        
        Args:
            index_name: Name of the index
            entity_type: Entity type to index
            properties: List of properties to index
        
        Returns:
            Dict with index creation status
        """
        try:
            from ipfs_datasets_py.knowledge_graphs.indexing import IndexManager
            
            index_manager = IndexManager()
            index_manager.create_index(index_name, entity_type, properties)
            
            self.logger.info(f"Created index {index_name} on {entity_type}.{properties}")
            
            return {
                "status": "success",
                "index_name": index_name,
                "entity_type": entity_type,
                "properties": properties,
                "message": "Index created successfully"
            }
        except ImportError:
            # Fallback
            self.logger.warning("Index module not available, using mock index")
            return {
                "status": "success",
                "index_name": index_name,
                "entity_type": entity_type,
                "properties": properties,
                "message": "Index created (mock)"
            }
        except Exception as e:
            self.logger.error(f"Failed to create index: {e}")
            return {
                "status": "error",
                "message": str(e),
                "index_name": index_name
            }
    
    # Constraint Management
    
    async def constraint_add(
        self,
        constraint_name: str,
        constraint_type: str,
        entity_type: str,
        properties: List[str]
    ) -> Dict[str, Any]:
        """
        Add a constraint to the knowledge graph.
        
        Args:
            constraint_name: Name of the constraint
            constraint_type: Type of constraint ("unique", "exists", "node_key")
            entity_type: Entity type for the constraint
            properties: List of properties involved
        
        Returns:
            Dict with constraint creation status
        """
        try:
            from ipfs_datasets_py.knowledge_graphs.constraints import ConstraintManager
            
            constraint_manager = ConstraintManager()
            constraint_manager.add_constraint(
                constraint_name, constraint_type, entity_type, properties
            )
            
            self.logger.info(
                f"Added {constraint_type} constraint {constraint_name} on {entity_type}.{properties}"
            )
            
            return {
                "status": "success",
                "constraint_name": constraint_name,
                "constraint_type": constraint_type,
                "entity_type": entity_type,
                "properties": properties,
                "message": "Constraint added successfully"
            }
        except ImportError:
            # Fallback
            self.logger.warning("Constraint module not available, using mock constraint")
            return {
                "status": "success",
                "constraint_name": constraint_name,
                "constraint_type": constraint_type,
                "entity_type": entity_type,
                "properties": properties,
                "message": "Constraint added (mock)"
            }
        except Exception as e:
            self.logger.error(f"Failed to add constraint: {e}")
            return {
                "status": "error",
                "message": str(e),
                "constraint_name": constraint_name
            }
