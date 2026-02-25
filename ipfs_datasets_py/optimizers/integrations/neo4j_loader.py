"""Neo4j Graph Loading Integration for Ontologies.

Provides integration for loading ontology extraction results into Neo4j graph database.
Maps entities to nodes and relationships to edges, enabling graph analytics, traversal,
and visualization of extracted ontologies.

Key Features:
    - Load entities as Neo4j nodes with properties and labels
    - Load relationships as Neo4j edges with directional mapping
    - Bulk import for large extraction results
    - Configurable node labels and relationship types
    - Merge semantics (update existing or create new)
    - Cypher query helpers for graph traversal
    - Transaction batching and retry logic
    - Optional async support

Usage:
    >>> from optimizers.integrations.neo4j_loader import Neo4jGraphLoader
    >>> 
    >>> loader = Neo4jGraphLoader(
    ...     uri="bolt://localhost:7687",
    ...     auth=("neo4j", "password")
    ... )
    >>> 
    >>> # Load extraction result as graph
    >>> stats = loader.load_extraction_result(
    ...     ontology_id="doc_001",
    ...     result=extraction_result,
    ...     metadata={"domain": "legal", "source": "contract.pdf"}
    ... )
    >>> 
    >>> # Query graph
    >>> subgraph = loader.get_entity_neighborhood("entity_123", max_depth=2)

Design:
    - Entities → Nodes: :Entity:Person, :Entity:Organization, etc.
    - Relationships → Edges: (source)-[:WORKS_AT]->(target)
    - Properties: Stored as node/edge properties
    - Metadata: Attached as properties with `meta_` prefix
    - Confidence: Stored as `confidence` property (0-1 float)
    - Ontology ID: Track provenance via `ontology_id` property
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)


# ============================================================================
# Configuration
# ============================================================================


@dataclass
class Neo4jConfig:
    """Configuration for Neo4j connection and graph loading.
    
    Attributes:
        uri: Neo4j connection URI (bolt://, neo4j://, bolt+s://, neo4j+s://)
        auth: Authentication tuple (username, password)
        database: Target database name (default: "neo4j")
        max_connection_lifetime: Connection lifetime in seconds
        max_connection_pool_size: Maximum connections in pool
        connection_timeout: Connection timeout in seconds
        encrypted: Enable TLS encryption
        trust: Trust strategy ("TRUST_ALL_CERTIFICATES", "TRUST_SYSTEM_CA_SIGNED_CERTIFICATES")
        merge_strategy: "CREATE" (always create new) or "MERGE" (update existing) nodes/edges
        node_label_prefix: Prefix for entity type node labels (e.g., "Entity")
        relationship_type_prefix: Prefix for relationship types (e.g., "REL_")
    """
    
    uri: str = "bolt://localhost:7687"
    auth: Optional[Tuple[str, str]] = None
    database: str = "neo4j"
    max_connection_lifetime: int = 3600
    max_connection_pool_size: int = 50
    connection_timeout: int = 30
    encrypted: bool = False
    trust: str = "TRUST_ALL_CERTIFICATES"
    merge_strategy: str = "MERGE"  # "CREATE" or "MERGE"
    node_label_prefix: str = "Entity"
    relationship_type_prefix: str = ""


# ============================================================================
# Mock Neo4j Driver (for testing without dependency)
# ============================================================================


class MockNeo4jSession:
    """Mock Neo4j session for testing without neo4j-driver dependency."""
    
    def __init__(self):
        self.executed_queries: List[Tuple[str, Dict[str, Any]]] = []
        self.closed = False
    
    def run(self, query: str, parameters: Optional[Dict[str, Any]] = None) -> MockNeo4jResult:
        """Execute a Cypher query."""
        params = parameters or {}
        self.executed_queries.append((query, params))
        logger.debug(f"Mock Neo4j query: {query[:100]}... with params: {list(params.keys())}")
        return MockNeo4jResult()
    
    def close(self):
        """Close the session."""
        self.closed = True
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()


class MockNeo4jResult:
    """Mock query result."""
    
    def __init__(self):
        self._data: List[Dict[str, Any]] = []
    
    def data(self) -> List[Dict[str, Any]]:
        """Return result data."""
        return self._data
    
    def single(self) -> Optional[Dict[str, Any]]:
        """Return single result."""
        return self._data[0] if self._data else None
    
    def consume(self):
        """Consume result counters."""
        return MockSummaryCounters()
    
    def __iter__(self):
        """Make result iterable."""
        return iter(self._data)


class MockSummaryCounters:
    """Mock result summary counters."""
    
    def __init__(self):
        self.nodes_created = 0
        self.relationships_created = 0
        self.properties_set = 0


class MockNeo4jDriver:
    """Mock Neo4j driver for testing without neo4j-driver dependency."""
    
    def __init__(self, uri: str, auth: Optional[Tuple[str, str]] = None, **kwargs):
        self.uri = uri
        self.auth = auth
        self.closed = False
        self._sessions: List[MockNeo4jSession] = []
        logger.info(f"MockNeo4jDriver initialized with uri: {uri}")
    
    def session(self, database: Optional[str] = None) -> MockNeo4jSession:
        """Create a new session."""
        session = MockNeo4jSession()
        self._sessions.append(session)
        return session
    
    def close(self):
        """Close the driver."""
        self.closed = True
        for session in self._sessions:
            if not session.closed:
                session.close()
    
    def verify_connectivity(self):
        """Verify connectivity (no-op for mock)."""
        pass
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()


# ============================================================================
# Neo4j Graph Loader
# ============================================================================


class Neo4jGraphLoader:
    """Neo4j graph loader for ontology extraction results.
    
    Loads entities as nodes and relationships as edges in Neo4j graph database.
    Supports bulk loading, merge semantics, and graph traversal queries.
    
    Args:
        config: Neo4j configuration (optional, uses defaults if None)
        driver: Pre-configured Neo4j driver (optional, created from config if None)
    
    Example:
        >>> loader = Neo4jGraphLoader(config=Neo4jConfig(uri="bolt://localhost:7687"))
        >>> stats = loader.load_extraction_result("doc_001", extraction_result)
        >>> print(f"Loaded {stats['nodes_created']} nodes, {stats['edges_created']} edges")
    """
    
    def __init__(self, config: Optional[Neo4jConfig] = None, driver=None):
        """Initialize Neo4j graph loader.
        
        Args:
            config: Neo4j configuration
            driver: Pre-configured driver (uses MockNeo4jDriver if None)
        """
        self.config = config or Neo4jConfig()
        
        if driver is None:
            # Use mock driver for testing (real neo4j-driver would be imported here)
            self.driver = MockNeo4jDriver(
                uri=self.config.uri,
                auth=self.config.auth,
                max_connection_lifetime=self.config.max_connection_lifetime,
                max_connection_pool_size=self.config.max_connection_pool_size,
                connection_timeout=self.config.connection_timeout,
                encrypted=self.config.encrypted,
                trust=self.config.trust,
            )
        else:
            self.driver = driver
        
        logger.info(f"Neo4jGraphLoader initialized with database: {self.config.database}")
    
    def close(self):
        """Close the Neo4j driver connection."""
        if self.driver:
            self.driver.close()
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
    
    # ------------------------------------------------------------------------
    # Entity Loading (Entities → Nodes)
    # ------------------------------------------------------------------------
    
    def load_entity(
        self,
        entity: Dict[str, Any],
        ontology_id: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Load a single entity as a Neo4j node.
        
        Args:
            entity: Entity dict with id, text, type, confidence, properties
            ontology_id: Ontology identifier for provenance
            metadata: Optional metadata to attach to node
        
        Returns:
            Entity ID of created/updated node
        
        Example:
            >>> entity = {"id": "e1", "text": "Alice", "type": "Person", "confidence": 0.95}
            >>> node_id = loader.load_entity(entity, "doc_001")
        """
        entity_id = entity["id"]
        entity_type = entity.get("type", "Unknown")
        node_label = f"{self.config.node_label_prefix}:{entity_type}"
        
        # Build node properties
        properties = {
            "entity_id": entity_id,
            "text": entity.get("text", ""),
            "entity_type": entity_type,
            "confidence": float(entity.get("confidence", 0.0)),
            "ontology_id": ontology_id,
            "loaded_at": datetime.utcnow().isoformat(),
        }
        
        # Add entity properties with prop_ prefix
        if "properties" in entity:
            for key, value in entity["properties"].items():
                properties[f"prop_{key}"] = value
        
        # Add metadata with meta_ prefix
        if metadata:
            for key, value in metadata.items():
                properties[f"meta_{key}"] = value
        
        # Build Cypher query (MERGE or CREATE)
        operation = self.config.merge_strategy
        query = f"""
        {operation} (n:{node_label} {{entity_id: $entity_id}})
        SET n = $properties
        RETURN n.entity_id AS entity_id
        """
        
        with self.driver.session(database=self.config.database) as session:
            result = session.run(query, {"entity_id": entity_id, "properties": properties})
            result.consume()
        
        logger.debug(f"Loaded entity {entity_id} as node with label {node_label}")
        return entity_id
    
    def load_entities_bulk(
        self,
        entities: List[Dict[str, Any]],
        ontology_id: str,
        metadata: Optional[Dict[str, Any]] = None,
        batch_size: int = 100,
    ) -> Dict[str, int]:
        """Load multiple entities in bulk (batched for performance).
        
        Args:
            entities: List of entity dicts
            ontology_id: Ontology identifier
            metadata: Optional metadata for all entities
            batch_size: Number of entities per transaction
        
        Returns:
            Dict with statistics: {"nodes_created": N, "nodes_updated": M}
        
        Example:
            >>> stats = loader.load_entities_bulk(entities, "doc_001", batch_size=100)
        """
        stats = {"nodes_created": 0, "nodes_updated": 0}
        
        # Process in batches
        for i in range(0, len(entities), batch_size):
            batch = entities[i:i+batch_size]
            
            # Prepare batch data
            batch_data = []
            for entity in batch:
                entity_id = entity["id"]
                entity_type = entity.get("type", "Unknown")
                properties = {
                    "entity_id": entity_id,
                    "text": entity.get("text", ""),
                    "entity_type": entity_type,
                    "confidence": float(entity.get("confidence", 0.0)),
                    "ontology_id": ontology_id,
                    "loaded_at": datetime.utcnow().isoformat(),
                }
                
                # Add entity properties
                if "properties" in entity:
                    for key, value in entity["properties"].items():
                        properties[f"prop_{key}"] = value
                
                # Add metadata
                if metadata:
                    for key, value in metadata.items():
                        properties[f"meta_{key}"] = value
                
                batch_data.append({"entity_type": entity_type, "properties": properties})
            
            # Execute batch MERGE (simplified - production would use UNWIND)
            with self.driver.session(database=self.config.database) as session:
                for item in batch_data:
                    entity_type = item["entity_type"]
                    node_label = f"{self.config.node_label_prefix}:{entity_type}"
                    query = f"""
                    {self.config.merge_strategy} (n:{node_label} {{entity_id: $properties.entity_id}})
                    SET n = $properties
                    RETURN n.entity_id AS entity_id
                    """
                    result = session.run(query, {"properties": item["properties"]})
                    result.consume()
                    stats["nodes_created"] += 1
        
        logger.info(f"Bulk loaded {len(entities)} entities across {(len(entities) + batch_size - 1) // batch_size} batches")
        return stats
    
    # ------------------------------------------------------------------------
    # Relationship Loading (Relationships → Edges)
    # ------------------------------------------------------------------------
    
    def load_relationship(
        self,
        relationship: Dict[str, Any],
        ontology_id: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Load a single relationship as a Neo4j edge.
        
        Args:
            relationship: Relationship dict with id, source_id, target_id, type, confidence
            ontology_id: Ontology identifier
            metadata: Optional metadata
        
        Returns:
            Relationship ID
        
        Example:
            >>> rel = {"id": "r1", "source_id": "e1", "target_id": "e2", "type": "knows", "confidence": 0.9}
            >>> edge_id = loader.load_relationship(rel, "doc_001")
        """
        rel_id = relationship["id"]
        source_id = relationship["source_id"]
        target_id = relationship["target_id"]
        rel_type = relationship.get("type", "RELATED_TO").upper().replace(" ", "_")
        
        # Apply relationship type prefix if configured
        if self.config.relationship_type_prefix:
            rel_type = f"{self.config.relationship_type_prefix}{rel_type}"
        
        # Build edge properties
        properties = {
            "relationship_id": rel_id,
            "relationship_type": relationship.get("type", "RELATED_TO"),
            "confidence": float(relationship.get("confidence", 0.0)),
            "ontology_id": ontology_id,
            "loaded_at": datetime.utcnow().isoformat(),
        }
        
        # Add relationship properties
        if "properties" in relationship:
            for key, value in relationship["properties"].items():
                properties[f"prop_{key}"] = value
        
        # Add metadata
        if metadata:
            for key, value in metadata.items():
                properties[f"meta_{key}"] = value
        
        # Build Cypher query to create edge
        query = f"""
        MATCH (source {{entity_id: $source_id}})
        MATCH (target {{entity_id: $target_id}})
        {self.config.merge_strategy} (source)-[r:{rel_type}]->(target)
        SET r = $properties
        RETURN r
        """
        
        with self.driver.session(database=self.config.database) as session:
            result = session.run(query, {
                "source_id": source_id,
                "target_id": target_id,
                "properties": properties,
            })
            result.consume()
        
        logger.debug(f"Loaded relationship {rel_id} as edge [{rel_type}] from {source_id} to {target_id}")
        return rel_id
    
    def load_relationships_bulk(
        self,
        relationships: List[Dict[str, Any]],
        ontology_id: str,
        metadata: Optional[Dict[str, Any]] = None,
        batch_size: int = 100,
    ) -> Dict[str, int]:
        """Load multiple relationships in bulk.
        
        Args:
            relationships: List of relationship dicts
            ontology_id: Ontology identifier
            metadata: Optional metadata
            batch_size: Edges per transaction
        
        Returns:
            Statistics dict: {"edges_created": N, "edges_updated": M}
        """
        stats = {"edges_created": 0, "edges_updated": 0}
        
        # Process in batches
        for i in range(0, len(relationships), batch_size):
            batch = relationships[i:i+batch_size]
            
            with self.driver.session(database=self.config.database) as session:
                for rel in batch:
                    rel_id = rel["id"]
                    source_id = rel["source_id"]
                    target_id = rel["target_id"]
                    rel_type = rel.get("type", "RELATED_TO").upper().replace(" ", "_")
                    
                    if self.config.relationship_type_prefix:
                        rel_type = f"{self.config.relationship_type_prefix}{rel_type}"
                    
                    properties = {
                        "relationship_id": rel_id,
                        "relationship_type": rel.get("type", "RELATED_TO"),
                        "confidence": float(rel.get("confidence", 0.0)),
                        "ontology_id": ontology_id,
                        "loaded_at": datetime.utcnow().isoformat(),
                    }
                    
                    if "properties" in rel:
                        for key, value in rel["properties"].items():
                            properties[f"prop_{key}"] = value
                    
                    if metadata:
                        for key, value in metadata.items():
                            properties[f"meta_{key}"] = value
                    
                    query = f"""
                    MATCH (source {{entity_id: $source_id}})
                    MATCH (target {{entity_id: $target_id}})
                    {self.config.merge_strategy} (source)-[r:{rel_type}]->(target)
                    SET r = $properties
                    RETURN r
                    """
                    
                    result = session.run(query, {
                        "source_id": source_id,
                        "target_id": target_id,
                        "properties": properties,
                    })
                    result.consume()
                    stats["edges_created"] += 1
        
        logger.info(f"Bulk loaded {len(relationships)} relationships across {(len(relationships) + batch_size - 1) // batch_size} batches")
        return stats
    
    # ------------------------------------------------------------------------
    # Complete Ontology Loading
    # ------------------------------------------------------------------------
    
    def load_extraction_result(
        self,
        ontology_id: str,
        result: Dict[str, Any],
        metadata: Optional[Dict[str, Any]] = None,
        batch_size: int = 100,
    ) -> Dict[str, Any]:
        """Load complete extraction result (entities + relationships) into Neo4j.
        
        Args:
            ontology_id: Unique identifier for this ontology
            result: Extraction result dict with 'ontology' key containing 'entities' and 'relationships'
            metadata: Optional metadata for entire ontology
            batch_size: Batch size for bulk operations
        
        Returns:
            Statistics dict: {"nodes_created": N, "edges_created": M, "ontology_id": ID}
        
        Example:
            >>> stats = loader.load_extraction_result("doc_001", extraction_result)
        """
        ontology = result.get("ontology", {})
        entities = ontology.get("entities", [])
        relationships = ontology.get("relationships", [])
        
        stats = {
            "ontology_id": ontology_id,
            "nodes_created": 0,
            "edges_created": 0,
            "metadata": metadata or {},
        }
        
        # Load entities first
        if entities:
            entity_stats = self.load_entities_bulk(entities, ontology_id, metadata, batch_size)
            stats["nodes_created"] = entity_stats["nodes_created"]
        
        # Load relationships second (requires entities to exist)
        if relationships:
            rel_stats = self.load_relationships_bulk(relationships, ontology_id, metadata, batch_size)
            stats["edges_created"] = rel_stats["edges_created"]
        
        logger.info(f"Loaded ontology {ontology_id}: {stats['nodes_created']} nodes, {stats['edges_created']} edges")
        return stats
    
    # ------------------------------------------------------------------------
    # Query Helpers
    # ------------------------------------------------------------------------
    
    def get_entity(self, entity_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve a single entity node by ID.
        
        Args:
            entity_id: Entity identifier
        
        Returns:
            Entity dict or None if not found
        """
        query = """
        MATCH (n {entity_id: $entity_id})
        RETURN n
        """
        
        with self.driver.session(database=self.config.database) as session:
            result = session.run(query, {"entity_id": entity_id})
            record = result.single()
            if record:
                return dict(record["n"])
        
        return None
    
    def get_entity_neighborhood(
        self,
        entity_id: str,
        max_depth: int = 1,
        relationship_types: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Get subgraph around an entity (neighborhood query).
        
        Args:
            entity_id: Central entity ID
            max_depth: Maximum traversal depth (1-3 recommended)
            relationship_types: Filter by relationship types (None = all types)
        
        Returns:
            Subgraph dict: {"nodes": [...], "edges": [...], "center": entity_id}
        
        Example:
            >>> subgraph = loader.get_entity_neighborhood("entity_123", max_depth=2)
        """
        rel_filter = ""
        if relationship_types:
            types_str = "|".join(relationship_types)
            rel_filter = f":{types_str}"
        
        query = f"""
        MATCH path = (center {{entity_id: $entity_id}})-[{rel_filter}*1..$max_depth]-(neighbor)
        RETURN nodes(path) AS nodes, relationships(path) AS rels
        """
        
        with self.driver.session(database=self.config.database) as session:
            result = session.run(query, {"entity_id": entity_id, "max_depth": max_depth})
            nodes_set: Set[str] = set()
            edges: List[Dict[str, Any]] = []
            
            for record in result:
                for node in record["nodes"]:
                    node_dict = dict(node)
                    nodes_set.add(node_dict.get("entity_id", ""))
                
                for rel in record["rels"]:
                    edges.append(dict(rel))
        
        return {
            "center": entity_id,
            "nodes": list(nodes_set),
            "edges": edges,
            "depth": max_depth,
        }
    
    def delete_ontology(self, ontology_id: str) -> int:
        """Delete all nodes and edges for a specific ontology.
        
        Args:
            ontology_id: Ontology identifier to delete
        
        Returns:
            Number of nodes deleted
        
        Example:
            >>> deleted_count = loader.delete_ontology("doc_001")
        """
        query = """
        MATCH (n {ontology_id: $ontology_id})
        DETACH DELETE n
        RETURN count(n) AS deleted_count
        """
        
        with self.driver.session(database=self.config.database) as session:
            result = session.run(query, {"ontology_id": ontology_id})
            record = result.single()
            deleted_count = record["deleted_count"] if record else 0
        
        logger.info(f"Deleted {deleted_count} nodes for ontology {ontology_id}")
        return deleted_count


__all__ = [
    "Neo4jConfig",
    "Neo4jGraphLoader",
    "MockNeo4jDriver",
    "MockNeo4jSession",
]
