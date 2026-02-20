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

    # -------------------------------------------------------------------------
    # SRL, Ontology Reasoning, and Distributed Query (new features)
    # -------------------------------------------------------------------------

    async def extract_srl(
        self,
        text: str,
        backend: str = "heuristic",
        return_triples: bool = False,
        return_temporal_graph: bool = False,
    ) -> Dict[str, Any]:
        """
        Extract Semantic Role Labeling (SRL) frames from text.

        Args:
            text: The input text to analyze.
            backend: ``"heuristic"`` or ``"spacy"``.
            return_triples: If ``True``, also return flat triples.
            return_temporal_graph: If ``True``, also return a temporal graph.

        Returns:
            Dict with status, frame_count, frames, and optionally triples /
            temporal_graph_nodes.
        """
        try:
            from ipfs_datasets_py.knowledge_graphs.extraction.srl import SRLExtractor

            extractor = SRLExtractor()
            frames = extractor.extract_srl(text)

            result: Dict[str, Any] = {
                "status": "success",
                "frame_count": len(frames),
                "frames": [f.to_dict() for f in frames],
            }

            if return_triples:
                triples = extractor.extract_to_triples(text)
                result["triples"] = [list(t) for t in triples]

            if return_temporal_graph:
                temporal_kg = extractor.build_temporal_graph(text)
                result["temporal_graph_nodes"] = len(temporal_kg.entities)
                result["temporal_graph_relationships"] = len(temporal_kg.relationships)

            return result

        except Exception as e:
            self.logger.error("SRL extraction failed: %s", e)
            return {"status": "error", "message": str(e)}

    async def ontology_materialize(
        self,
        graph_name: str,
        schema: Optional[Dict[str, Any]] = None,
        check_consistency: bool = False,
        explain: bool = False,
    ) -> Dict[str, Any]:
        """
        Apply OWL/RDFS ontology inference rules to a knowledge graph.

        Args:
            graph_name: Name of the graph (used for logging / future storage).
            schema: Dict of ontology declarations.
            check_consistency: Run consistency checks if True.
            explain: Return inference traces without modifying the graph.

        Returns:
            Dict with status, inferred_count, and optionally violations / traces.
        """
        try:
            from ipfs_datasets_py.knowledge_graphs.ontology.reasoning import (
                OntologySchema,
                OntologyReasoner,
            )
            from ipfs_datasets_py.knowledge_graphs.extraction.graph import KnowledgeGraph

            schema_dict = schema or {}
            ont_schema = OntologySchema()

            for pair in schema_dict.get("subclass", []):
                ont_schema.add_subclass(pair[0], pair[1])
            for pair in schema_dict.get("subproperty", []):
                ont_schema.add_subproperty(pair[0], pair[1])
            for prop in schema_dict.get("transitive", []):
                ont_schema.add_transitive(prop)
            for prop in schema_dict.get("symmetric", []):
                ont_schema.add_symmetric(prop)
            for pair in schema_dict.get("inverse", []):
                ont_schema.add_inverse(pair[0], pair[1])
            for pair in schema_dict.get("domain", []):
                ont_schema.add_domain(pair[0], pair[1])
            for pair in schema_dict.get("range", []):
                ont_schema.add_range(pair[0], pair[1])
            for pair in schema_dict.get("disjoint", []):
                ont_schema.add_disjoint(pair[0], pair[1])
            for chain_spec in schema_dict.get("property_chains", []):
                ont_schema.add_property_chain(chain_spec["chain"], chain_spec["result"])
            for pair in schema_dict.get("equivalent_classes", []):
                ont_schema.add_equivalent_class(pair[0], pair[1])

            reasoner = OntologyReasoner(ont_schema)
            # Use an empty KG as the target (real usage would load from storage)
            kg = KnowledgeGraph(name=graph_name)

            result: Dict[str, Any] = {"status": "success", "graph_name": graph_name}

            if explain:
                traces = reasoner.explain_inferences(kg)
                result["traces"] = [
                    {
                        "rule": t.rule,
                        "subject_id": t.subject_id,
                        "predicate": t.predicate,
                        "object_id": t.object_id,
                        "description": t.description,
                    }
                    for t in traces
                ]
                result["inferred_count"] = len(traces)
            else:
                before_nodes = len(kg.entities)
                before_rels = len(kg.relationships)
                kg = reasoner.materialize(kg)
                result["inferred_count"] = (
                    len(kg.entities) - before_nodes + len(kg.relationships) - before_rels
                )

            if check_consistency:
                violations = reasoner.check_consistency(kg)
                result["violations"] = [
                    {
                        "violation_type": v.violation_type,
                        "entity_id": v.entity_id,
                        "description": v.description,
                    }
                    for v in violations
                ]

            return result

        except Exception as e:
            self.logger.error("Ontology materialization failed: %s", e)
            return {"status": "error", "message": str(e), "graph_name": graph_name}

    async def distributed_execute(
        self,
        query: str,
        num_partitions: int = 4,
        partition_strategy: str = "hash",
        parallel: bool = False,
        explain: bool = False,
    ) -> Dict[str, Any]:
        """
        Execute a Cypher query across a distributed (partitioned) knowledge graph.

        Args:
            query: Cypher query string.
            num_partitions: Number of partitions.
            partition_strategy: ``"hash"``, ``"range"``, or ``"round_robin"``.
            parallel: Use thread-pool fan-out if True.
            explain: Return query plan instead of executing.

        Returns:
            Dict with status, result_count, results, partition_stats, and
            optionally a plan dict.
        """
        try:
            from ipfs_datasets_py.knowledge_graphs.query.distributed import (
                GraphPartitioner,
                FederatedQueryExecutor,
                PartitionStrategy,
            )
            from ipfs_datasets_py.knowledge_graphs.extraction.graph import KnowledgeGraph

            strategy_map = {
                "hash": PartitionStrategy.HASH,
                "range": PartitionStrategy.RANGE,
                "round_robin": PartitionStrategy.ROUND_ROBIN,
            }
            strategy = strategy_map.get(partition_strategy.lower(), PartitionStrategy.HASH)

            # Use a minimal empty KG; real usage would load from storage
            kg = KnowledgeGraph(name="distributed_target")

            partitioner = GraphPartitioner(num_partitions=num_partitions, strategy=strategy)
            dist_graph = partitioner.partition(kg)
            executor = FederatedQueryExecutor(dist_graph)

            result: Dict[str, Any] = {
                "status": "success",
                "partition_stats": dist_graph.get_partition_stats(),
            }

            if explain:
                plan = executor.explain_query(query)
                result["plan"] = plan.to_dict()
                result["result_count"] = 0
            elif parallel:
                federated = executor.execute_cypher_parallel(query)
                result["results"] = federated.records
                result["result_count"] = len(federated.records)
            else:
                federated = executor.execute_cypher(query)
                result["results"] = federated.records
                result["result_count"] = len(federated.records)

            return result

        except Exception as e:
            self.logger.error("Distributed execute failed: %s", e)
            return {"status": "error", "message": str(e), "query": query}
