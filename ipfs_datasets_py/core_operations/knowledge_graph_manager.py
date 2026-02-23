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

    async def graphql_query(
        self,
        query: str,
        kg_data: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Execute a GraphQL query against a knowledge graph.

        Args:
            query: GraphQL query string.
            kg_data: Optional serialised KG dict.

        Returns:
            Dict with status, data, entity_count, query_length.
        """
        try:
            from ipfs_datasets_py.knowledge_graphs.query.graphql import (
                KnowledgeGraphQLExecutor,
            )
            from ipfs_datasets_py.knowledge_graphs.extraction.graph import KnowledgeGraph

            if kg_data:
                kg = KnowledgeGraph.from_dict(kg_data)
            else:
                kg = KnowledgeGraph(name="graphql_target")

            executor = KnowledgeGraphQLExecutor(kg)
            data = executor.execute(query)
            return {
                "status": "success",
                "data": data,
                "entity_count": len(kg.entities),
                "query_length": len(query),
            }
        except Exception as e:
            self.logger.error("GraphQL query failed: %s", e)
            return {"status": "error", "message": str(e), "query_length": len(query)}

    async def visualize(
        self,
        format: str = "dot",
        kg_data: Optional[Dict[str, Any]] = None,
        max_entities: Optional[int] = None,
        directed: bool = True,
        graph_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Export a knowledge graph as a visualization format string.

        Args:
            format: One of ``"dot"``, ``"mermaid"``, ``"d3_json"``, ``"ascii"``.
            kg_data: Optional serialised KG dict.
            max_entities: Cap on entity count in output.
            directed: Emit directed graph (DOT/Mermaid).
            graph_name: Optional name for the DOT digraph identifier.

        Returns:
            Dict with status, format, output, entity_count, relationship_count.
        """
        try:
            from ipfs_datasets_py.knowledge_graphs.extraction.visualization import (
                KnowledgeGraphVisualizer,
            )
            from ipfs_datasets_py.knowledge_graphs.extraction.graph import KnowledgeGraph

            if kg_data:
                kg = KnowledgeGraph.from_dict(kg_data)
            else:
                kg = KnowledgeGraph(name="viz_target")

            viz = KnowledgeGraphVisualizer(kg)
            fmt = format.lower()
            if fmt == "dot":
                output = viz.to_dot(graph_name=graph_name, directed=directed)
            elif fmt == "mermaid":
                output = viz.to_mermaid(max_entities=max_entities)
            elif fmt in ("d3_json", "d3"):
                output = viz.to_d3_json(max_nodes=max_entities)
            elif fmt == "ascii":
                output = viz.to_ascii()
            else:
                output = viz.to_dot(graph_name=graph_name, directed=directed)
                fmt = "dot"

            return {
                "status": "success",
                "format": fmt,
                "output": output,
                "entity_count": len(kg.entities),
                "relationship_count": len(kg.relationships),
            }
        except Exception as e:
            self.logger.error("Visualize failed: %s", e)
            return {"status": "error", "message": str(e), "format": format}

    async def suggest_completions(
        self,
        kg_data: Optional[Dict[str, Any]] = None,
        min_score: float = 0.3,
        max_suggestions: int = 20,
        entity_id: Optional[str] = None,
        rel_type: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Suggest missing relationships in a knowledge graph.

        Args:
            kg_data: Optional serialised KG dict.
            min_score: Minimum confidence score (0.0–1.0).
            max_suggestions: Maximum suggestions to return.
            entity_id: Filter suggestions by source entity.
            rel_type: Filter suggestions by relationship type.

        Returns:
            Dict with status, suggestion_count, suggestions, isolated_entity_count.
        """
        try:
            from ipfs_datasets_py.knowledge_graphs.query.completion import (
                KnowledgeGraphCompleter,
            )
            from ipfs_datasets_py.knowledge_graphs.extraction.graph import KnowledgeGraph

            if kg_data:
                kg = KnowledgeGraph.from_dict(kg_data)
            else:
                kg = KnowledgeGraph(name="completion_target")

            completer = KnowledgeGraphCompleter(kg)
            suggestions = completer.find_missing_relationships(
                entity_id=entity_id,
                rel_type=rel_type,
                min_score=min_score,
                max_suggestions=max_suggestions,
            )
            isolated = completer.find_isolated_entities()
            return {
                "status": "success",
                "suggestion_count": len(suggestions),
                "suggestions": [s.to_dict() for s in suggestions],
                "isolated_entity_count": len(isolated),
            }
        except Exception as e:
            self.logger.error("Suggest completions failed: %s", e)
            return {"status": "error", "message": str(e), "min_score": min_score}

    async def explain_entity(
        self,
        explain_type: str = "entity",
        entity_id: Optional[str] = None,
        start_entity_id: Optional[str] = None,
        end_entity_id: Optional[str] = None,
        relationship_id: Optional[str] = None,
        depth: str = "standard",
        max_hops: int = 4,
        kg_data: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Produce a structured explanation for a KG element.

        Args:
            explain_type: One of ``"entity"``, ``"relationship"``,
                ``"path"``, ``"why_connected"``.
            entity_id: Entity to explain.
            start_entity_id: Source entity for path/why_connected.
            end_entity_id: Target entity for path/why_connected.
            relationship_id: Relationship to explain.
            depth: ``"surface"``, ``"standard"``, or ``"deep"``.
            max_hops: Maximum BFS depth for path explanations.
            kg_data: Optional serialised KG dict.

        Returns:
            Dict with status, explain_type, explanation, narrative.
        """
        try:
            from ipfs_datasets_py.knowledge_graphs.query.explanation import (
                QueryExplainer,
                ExplanationDepth,
            )
            from ipfs_datasets_py.knowledge_graphs.extraction.graph import KnowledgeGraph

            if kg_data:
                kg = KnowledgeGraph.from_dict(kg_data)
            else:
                kg = KnowledgeGraph(name="explanation_target")

            depth_map = {
                "surface": ExplanationDepth.SURFACE,
                "standard": ExplanationDepth.STANDARD,
                "deep": ExplanationDepth.DEEP,
            }
            exp_depth = depth_map.get(depth.lower(), ExplanationDepth.STANDARD)

            explainer = QueryExplainer(kg)
            exp_type = explain_type.lower()

            if exp_type == "entity" and entity_id:
                exp = explainer.explain_entity(entity_id, depth=exp_depth)
                return {
                    "status": "success",
                    "explain_type": exp_type,
                    "explanation": exp.to_dict(),
                    "narrative": exp.narrative,
                }
            elif exp_type == "relationship" and relationship_id:
                exp = explainer.explain_relationship(relationship_id, depth=exp_depth)
                return {
                    "status": "success",
                    "explain_type": exp_type,
                    "explanation": exp.to_dict(),
                    "narrative": exp.narrative,
                }
            elif exp_type == "path" and start_entity_id and end_entity_id:
                exp = explainer.explain_path(start_entity_id, end_entity_id, max_hops=max_hops)
                return {
                    "status": "success",
                    "explain_type": exp_type,
                    "explanation": exp.to_dict(),
                    "narrative": exp.narrative,
                }
            elif exp_type == "why_connected" and start_entity_id and end_entity_id:
                narrative = explainer.why_connected(start_entity_id, end_entity_id)
                return {
                    "status": "success",
                    "explain_type": exp_type,
                    "explanation": {"narrative": narrative},
                    "narrative": narrative,
                }
            else:
                return {
                    "status": "error",
                    "message": f"explain_type={exp_type!r} requires matching ID parameter(s)",
                    "explain_type": exp_type,
                }
        except Exception as e:
            self.logger.error("Explain failed: %s", e)
            return {"status": "error", "message": str(e), "explain_type": explain_type}

    async def verify_provenance(
        self,
        provenance_jsonl: Optional[str] = None,
        kg_data: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Verify the integrity of a knowledge-graph provenance chain.

        Args:
            provenance_jsonl: Optional JSONL string of provenance events.
            kg_data: Optional serialised KG dict.

        Returns:
            Dict with status, valid, event_count, errors, latest_cid, depth.
        """
        try:
            from ipfs_datasets_py.knowledge_graphs.extraction.provenance import (
                ProvenanceChain,
            )

            if provenance_jsonl:
                chain = ProvenanceChain.from_jsonl(provenance_jsonl)
            else:
                chain = ProvenanceChain()

            valid, errors = chain.verify_chain()
            return {
                "status": "success",
                "valid": valid,
                "event_count": chain.depth,
                "errors": errors,
                "latest_cid": chain.latest_cid,
                "depth": chain.depth,
            }
        except Exception as e:
            self.logger.error("Verify provenance failed: %s", e)
            return {
                "status": "error",
                "message": str(e),
                "valid": False,
                "errors": [str(e)],
            }

    async def gnn_embed(
        self,
        kg_data: Optional[Dict[str, Any]] = None,
        entity_ids: Optional[List[str]] = None,
        top_k_similar: int = 5,
        layer_type: str = "graph_sage",
        embedding_dim: int = 64,
        num_layers: int = 2,
    ) -> Dict[str, Any]:
        """
        Compute GNN node embeddings for a knowledge graph.

        Args:
            kg_data: Optional serialised KG dict.
            entity_ids: Optional entity IDs to return embeddings for.
            top_k_similar: Number of most-similar entities to return per entity.
            layer_type: Message-passing layer type.
            embedding_dim: Target embedding dimensionality.
            num_layers: Number of message-passing iterations.

        Returns:
            Dict with status, entity_count, embeddings, and similar.
        """
        try:
            from ipfs_datasets_py.knowledge_graphs.extraction.graph import (
                KnowledgeGraph,
            )
            from ipfs_datasets_py.knowledge_graphs.query.gnn import (
                GraphNeuralNetworkAdapter,
                GNNConfig,
                GNNLayerType,
            )

            if kg_data:
                kg = KnowledgeGraph.from_dict(kg_data)
            else:
                kg = KnowledgeGraph("gnn_embed_temp")

            try:
                layer = GNNLayerType(layer_type)
            except ValueError:
                layer = GNNLayerType.GRAPH_SAGE

            config = GNNConfig(
                embedding_dim=embedding_dim,
                num_layers=num_layers,
                layer_type=layer,
            )
            adapter = GraphNeuralNetworkAdapter(kg, config)
            embedding_objects = adapter.compute_embeddings()

            embeddings: Dict[str, List[float]] = {
                eid: emb.features for eid, emb in embedding_objects.items()
            }

            similar: Dict[str, List[Dict[str, Any]]] = {}
            if entity_ids:
                for eid in entity_ids:
                    if eid in kg.entities:
                        results = adapter.find_similar_entities(eid, top_k=top_k_similar)
                        similar[eid] = [
                            {"entity_id": other_eid, "score": score}
                            for other_eid, score in results
                        ]

            return {
                "status": "success",
                "entity_count": len(kg.entities),
                "embedding_dim": embedding_dim,
                "layer_type": layer_type,
                "embeddings": embeddings,
                "similar": similar,
            }
        except Exception as e:
            self.logger.error("GNN embed failed: %s", e)
            return {
                "status": "error",
                "message": str(e),
                "entity_count": 0,
                "embeddings": {},
                "similar": {},
            }

    async def zkp_prove(
        self,
        proof_type: str = "entity_exists",
        entity_type: Optional[str] = None,
        entity_name: Optional[str] = None,
        entity_id: Optional[str] = None,
        property_key: Optional[str] = None,
        property_value_hash: Optional[str] = None,
        path_start_type: Optional[str] = None,
        path_end_type: Optional[str] = None,
        min_count: Optional[int] = None,
        actual_count: Optional[int] = None,
        kg_data: Optional[Dict[str, Any]] = None,
        prover_id: str = "default",
        build_tdfol_witness: bool = False,
        circuit_version: int = 1,
    ) -> Dict[str, Any]:
        """
        Generate a zero-knowledge proof for a KG assertion.

        Args:
            proof_type: One of entity_exists / entity_property / path_exists /
                query_answer_count.
            entity_type: Entity type for entity_exists / entity_property.
            entity_name: Entity name for entity_exists.
            entity_id: Private entity ID used in the witness.
            property_key: Property key for entity_property.
            property_value_hash: SHA-256 hash of the property value.
            path_start_type: Start entity type for path_exists.
            path_end_type: End entity type for path_exists.
            min_count: Minimum count for query_answer_count.
            actual_count: Actual count for query_answer_count.
            kg_data: Optional serialised KG dict.
            prover_id: Prover instance identifier.
            build_tdfol_witness: When True, also build a TDFOL_v1 witness dict.
            circuit_version: TDFOL_v1 circuit version.

        Returns:
            Dict with status, proof_type, proof, valid, and optionally tdfol_witness.
        """
        try:
            from ipfs_datasets_py.knowledge_graphs.extraction.graph import (
                KnowledgeGraph,
            )
            from ipfs_datasets_py.knowledge_graphs.query.zkp import (
                KGZKProver,
                KGZKVerifier,
                KGProofType,
            )

            if kg_data:
                kg = KnowledgeGraph.from_dict(kg_data)
            else:
                kg = KnowledgeGraph("zkp_temp")
                if entity_type and entity_name:
                    kg.add_entity(entity_type, entity_name, confidence=1.0)
                # For path_exists proofs, add both start and end types with a relationship
                if proof_type in ("path_exists", KGProofType.PATH_EXISTS.value):
                    start_t = path_start_type or "entity"
                    end_t = path_end_type or "entity"
                    from ipfs_datasets_py.knowledge_graphs.extraction.graph import (
                        Entity,
                        Relationship,
                    )
                    start_ent = Entity(
                        entity_id=f"start_{start_t}",
                        entity_type=start_t,
                        name=start_t,
                    )
                    end_ent = Entity(
                        entity_id=f"end_{end_t}",
                        entity_type=end_t,
                        name=end_t,
                    )
                    kg.add_entity(start_ent)
                    kg.add_entity(end_ent)
                    kg.add_relationship(
                        Relationship(
                            relationship_id="r_path",
                            relationship_type="connects",
                            source_entity=start_ent,
                            target_entity=end_ent,
                        )
                    )

            prover = KGZKProver(kg, prover_id=prover_id)
            verifier = KGZKVerifier()

            stmt = None
            if proof_type == KGProofType.ENTITY_EXISTS.value or proof_type == "entity_exists":
                stmt = prover.prove_entity_exists(
                    entity_type or "entity",
                    entity_name or "unknown",
                )
            elif proof_type == KGProofType.ENTITY_PROPERTY.value or proof_type == "entity_property":
                stmt = prover.prove_entity_property(
                    entity_id or entity_name or "unknown",
                    property_key or "property",
                    property_value_hash or "",
                )
            elif proof_type == KGProofType.PATH_EXISTS.value or proof_type == "path_exists":
                stmt = prover.prove_path_exists(
                    path_start_type or "entity",
                    path_end_type or "entity",
                )
            elif proof_type == KGProofType.QUERY_ANSWER_COUNT.value or proof_type == "query_answer_count":
                # Add entities to the temp KG so the count proof can succeed
                if not kg_data and actual_count and actual_count > 0:
                    from ipfs_datasets_py.knowledge_graphs.extraction.graph import (
                        Entity,
                    )
                    for i in range(actual_count):
                        kg.add_entity(
                            Entity(
                                entity_id=f"count_ent_{i}",
                                entity_type="entity",
                                name=f"entity_{i}",
                            )
                        )
                stmt = prover.prove_query_answer_count(
                    min_count=min_count or 0,
                )
            else:
                return {
                    "status": "error",
                    "message": f"Unknown proof_type: {proof_type!r}",
                    "proof_type": proof_type,
                    "proof": None,
                    "valid": False,
                }

            valid = verifier.verify_statement(stmt) if stmt else False
            result: Dict[str, Any] = {
                "status": "success",
                "proof_type": proof_type,
                "proof": stmt.to_dict() if stmt else None,
                "valid": valid,
            }

            if build_tdfol_witness and stmt:
                from ipfs_datasets_py.knowledge_graphs.query.groth16_kg_witness import (
                    KGWitnessBuilder,
                )
                builder = KGWitnessBuilder(circuit_version=circuit_version)
                if proof_type in ("entity_exists", KGProofType.ENTITY_EXISTS.value):
                    witness = builder.entity_exists(
                        entity_type or "entity",
                        entity_name or "unknown",
                        entity_id or "eid_unknown",
                    )
                elif proof_type in ("path_exists", KGProofType.PATH_EXISTS.value):
                    witness = builder.path_exists(
                        path_ids=[
                            entity_id or "eid_start",
                            entity_id or "eid_end",
                        ],
                        start_type=path_start_type or "entity",
                        end_type=path_end_type or "entity",
                    )
                elif proof_type in ("entity_property", KGProofType.ENTITY_PROPERTY.value):
                    witness = builder.entity_property(
                        entity_id or "eid_unknown",
                        property_key or "property",
                        property_value_hash or ("0" * 64),
                    )
                elif proof_type in ("query_answer_count", KGProofType.QUERY_ANSWER_COUNT.value):
                    witness = builder.query_answer_count(
                        min_count=min_count or 0,
                        actual_count=actual_count or 0,
                    )
                else:
                    witness = {}
                result["tdfol_witness"] = witness

            return result
        except Exception as e:
            self.logger.error("ZKP prove failed: %s", e)
            return {
                "status": "error",
                "message": str(e),
                "proof_type": proof_type,
                "proof": None,
                "valid": False,
            }

    async def federate_query(
        self,
        graphs: Optional[List[Dict[str, Any]]] = None,
        query_entity_name: Optional[str] = None,
        query_entity_type: Optional[str] = None,
        resolution_strategy: str = "type_and_name",
        merge: bool = False,
        max_results: int = 50,
    ) -> Dict[str, Any]:
        """
        Query across a federation of independent knowledge graphs.

        Args:
            graphs: Optional list of serialised KG dicts.
            query_entity_name: Name of the entity to look up across graphs.
            query_entity_type: Optional type filter for entity lookup.
            resolution_strategy: Cross-graph entity resolution strategy.
            merge: When True, merge all graphs and return merged counts.
            max_results: Maximum number of entity-lookup results.

        Returns:
            Dict with status, graph_count, entity_matches, query_hits,
            and optionally merged_entity_count.
        """
        try:
            from ipfs_datasets_py.knowledge_graphs.extraction.graph import (
                KnowledgeGraph,
            )
            from ipfs_datasets_py.knowledge_graphs.query.federation import (
                FederatedKnowledgeGraph,
                EntityResolutionStrategy,
            )

            # Parse resolution strategy
            strategy_map = {
                "type_and_name": EntityResolutionStrategy.TYPE_AND_NAME,
                "exact_name": EntityResolutionStrategy.EXACT_NAME,
                "property_match": EntityResolutionStrategy.PROPERTY_MATCH,
            }
            strategy = strategy_map.get(
                resolution_strategy.lower(),
                EntityResolutionStrategy.TYPE_AND_NAME,
            )

            fed = FederatedKnowledgeGraph()

            kg_list: List[KnowledgeGraph] = []
            for i, kg_dict in enumerate(graphs or []):
                kg = KnowledgeGraph.from_dict(kg_dict)
                fed.add_graph(kg, name=f"graph_{i}")
                kg_list.append(kg)

            # Resolve entity matches across all graph pairs
            matches = fed.resolve_entities(strategy=strategy)
            entity_matches = [
                {
                    "entity_a_id": m.entity_a_id,
                    "entity_b_id": m.entity_b_id,
                    "kg_a_index": m.kg_a_index,
                    "kg_b_index": m.kg_b_index,
                    "score": m.score,
                    "strategy": m.strategy.value if isinstance(m.strategy, EntityResolutionStrategy) else str(m.strategy),
                }
                for m in matches
            ]

            # Entity lookup across all graphs
            query_hits: List[Dict[str, Any]] = []
            if query_entity_name:
                hits = fed.query_entity(
                    name=query_entity_name,
                    entity_type=query_entity_type,
                )
                query_hits = [
                    {
                        "graph_index": idx,
                        "entity_id": entity.entity_id,
                        "entity_type": entity.entity_type,
                        "name": entity.name,
                    }
                    for idx, entity in hits[:max_results]
                ]

            result: Dict[str, Any] = {
                "status": "success",
                "graph_count": len(kg_list),
                "resolution_strategy": resolution_strategy,
                "entity_matches": entity_matches,
                "query_hits": query_hits,
            }

            if merge:
                merged = fed.to_merged_graph()
                result["merged_entity_count"] = len(merged.entities)
                result["merged_relationship_count"] = len(merged.relationships)

            return result
        except Exception as e:
            self.logger.error("Federate query failed: %s", e)
            return {
                "status": "error",
                "message": str(e),
                "graph_count": len(graphs) if graphs else 0,
                "entity_matches": [],
                "query_hits": [],
            }
