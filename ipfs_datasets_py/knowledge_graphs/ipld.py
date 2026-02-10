"""
IPLD Knowledge Graph Module

Provides a class for representing and storing knowledge graphs using IPLD.
This module implements entity and relationship modeling with IPLD for
content-addressed graph storage.

Features:
- Entity and relationship modeling with IPLD
- Graph traversal with relationship path following
- Vector-augmented graph queries
- Cross-document reasoning capabilities
- Export to/import from CAR files
- Automatic chunking for large graphs (prevents IPFS 1MiB block limit errors)

Large Graph Handling:
When a knowledge graph grows large (e.g., 10,000+ entities), the root node
metadata can exceed IPFS's 1MiB block size limit. This module automatically
detects when data arrays (entity_ids, entity_cids, relationship_ids,
relationship_cids) exceed the threshold (800KB by default) and stores them
in separate IPLD blocks, referencing them by CID in the root node. This
ensures the root block stays well under the 1MB limit while maintaining
full functionality and backward compatibility.
"""

import os
import json
import uuid
import logging
from typing import Dict, List, Any, Optional, Set, Tuple, Union
from collections import defaultdict
from collections import deque
import numpy as np

from ipfs_datasets_py.data_transformation.ipld.storage import IPLDStorage
from ipfs_datasets_py.data_transformation.ipld.dag_pb import create_dag_node, parse_dag_node
from ipfs_datasets_py.data_transformation.ipld.optimized_codec import OptimizedEncoder, OptimizedDecoder
from ipfs_datasets_py.vector_stores.ipld import IPLDVectorStore, SearchResult

try:
    from slugify import slugify
except ImportError:
    # Simple fallback implementation of slugify
    import re
    def slugify(text):
        text = text.lower().strip()
        text = re.sub(r'[^\w\s-]', '', text)
        text = re.sub(r'[\s_-]+', '-', text)
        return text

try:
    import ipld_car
    HAVE_IPLD_CAR = True
except ImportError:
    HAVE_IPLD_CAR = False

# Maximum size for a single IPLD block before chunking (800KB to stay under 1MB limit)
# IPFS has a 1MiB limit for blocks that can be exchanged with other peers
MAX_BLOCK_SIZE = 800 * 1024

# Type for entity and relationship IDs
EntityID = str
RelationshipID = str

class Entity:
    """
    Represents an entity in a knowledge graph.

    Entities are nodes in the knowledge graph with a type, name,
    and optional properties.
    """

    def __init__(
        self,
        entity_id: EntityID = None,
        entity_type: str = "entity",
        name: str = "",
        properties: Optional[Dict[str, Any]] = None,
        confidence: float = 1.0,
        source_text: str = None
    ):
        """
        Initialize an entity.

        Args:
            entity_id: Optional ID for the entity (auto-generated if None)
            entity_type: Type of the entity
            name: Name of the entity
            properties: Optional properties for the entity
            confidence: Confidence score for the entity (0.0 to 1.0)
            source_text: Optional source text from which the entity was extracted
        """
        self.id = entity_id or str(uuid.uuid4())
        self.type = entity_type
        self.name = name
        self.properties = properties or {}
        self.confidence = confidence
        self.source_text = source_text
        self.cid = None  # Will be set when stored in IPLD

    def to_dict(self) -> Dict[str, Any]:
        """Convert entity to dictionary representation."""
        return {
            "id": self.id,
            "type": self.type,
            "name": self.name,
            "properties": self.properties,
            "confidence": self.confidence,
            "source_text": self.source_text
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Entity':
        """Create entity from dictionary representation."""
        entity = cls(
            entity_id=data.get("id"),
            entity_type=data.get("type", "entity"),
            name=data.get("name", ""),
            properties=data.get("properties", {}),
            confidence=data.get("confidence", 1.0),
            source_text=data.get("source_text")
        )
        entity.cid = data.get("cid")
        return entity

    def __str__(self) -> str:
        """Get string representation of the entity."""
        return f"Entity(id={self.id}, type={self.type}, name={self.name})"

class Relationship:
    """
    Represents a relationship between entities in a knowledge graph.

    Relationships are edges in the knowledge graph connecting entities
    with a specific relationship type and optional properties.
    """

    def __init__(
        self,
        relationship_id: RelationshipID = None,
        relationship_type: str = "related_to",
        source: Union[Entity, EntityID] = None,
        target: Union[Entity, EntityID] = None,
        properties: Optional[Dict[str, Any]] = None,
        confidence: float = 1.0,
        source_text: str = None
    ):
        """
        Initialize a relationship.

        Args:
            relationship_id: Optional ID for the relationship (auto-generated if None)
            relationship_type: Type of the relationship
            source: Source entity or entity ID
            target: Target entity or entity ID
            properties: Optional properties for the relationship
            confidence: Confidence score for the relationship (0.0 to 1.0)
            source_text: Optional source text from which the relationship was extracted
        """
        self.id = relationship_id or str(uuid.uuid4())
        self.type = relationship_type

        # Extract entity IDs if entities are provided
        if isinstance(source, Entity):
            self.source_id = source.id
        else:
            self.source_id = source

        if isinstance(target, Entity):
            self.target_id = target.id
        else:
            self.target_id = target

        self.properties = properties or {}
        self.confidence = confidence
        self.source_text = source_text
        self.cid = None  # Will be set when stored in IPLD

    def to_dict(self) -> Dict[str, Any]:
        """Convert relationship to dictionary representation."""
        return {
            "id": self.id,
            "type": self.type,
            "source_id": self.source_id,
            "target_id": self.target_id,
            "properties": self.properties,
            "confidence": self.confidence,
            "source_text": self.source_text
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Relationship':
        """Create relationship from dictionary representation."""
        relationship = cls(
            relationship_id=data.get("id"),
            relationship_type=data.get("type", "related_to"),
            source=data.get("source_id"),
            target=data.get("target_id"),
            properties=data.get("properties", {}),
            confidence=data.get("confidence", 1.0),
            source_text=data.get("source_text")
        )
        relationship.cid = data.get("cid")
        return relationship

    def __str__(self) -> str:
        """Get string representation of the relationship."""
        return f"Relationship(id={self.id}, type={self.type}, source={self.source_id}, target={self.target_id})"

class IPLDKnowledgeGraph:
    """
    Knowledge graph using IPLD for storage.

    This class provides a knowledge graph implementation that uses IPLD for
    content-addressed storage of entities and relationships. It supports graph
    traversal, vector-augmented queries, and cross-document reasoning.
    """

    def __init__(
        self,
        name: str = "knowledge_graph",
        storage: Optional[IPLDStorage] = None,
        vector_store: Optional[IPLDVectorStore] = None
    ):
        """
        Initialize knowledge graph.

        Args:
            name: Name of the knowledge graph
            storage: Optional IPLD storage to use
            vector_store: Optional vector store for vector-augmented queries
        """
        self.name = name
        self.storage = storage or IPLDStorage()
        self.vector_store = vector_store

        # Initialize data structures
        self.entities: Dict[EntityID, Entity] = {}
        self.relationships: Dict[RelationshipID, Relationship] = {}

        # Index for efficient access
        self._entity_index: Dict[str, Set[EntityID]] = defaultdict(set)  # type -> entity_ids
        self._relationship_index: Dict[str, Set[RelationshipID]] = defaultdict(set)  # type -> relationship_ids
        self._source_relationships: Dict[EntityID, Set[RelationshipID]] = defaultdict(set)  # source_id -> relationship_ids
        self._target_relationships: Dict[EntityID, Set[RelationshipID]] = defaultdict(set)  # target_id -> relationship_ids

        # For entity-entity relationships
        self._entity_relationships: Dict[Tuple[EntityID, EntityID], Set[RelationshipID]] = defaultdict(set)  # (source_id, target_id) -> relationship_ids

        # Track CIDs
        self.root_cid = None
        self._entity_cids: Dict[EntityID, str] = {}
        self._relationship_cids: Dict[RelationshipID, str] = {}

    @property
    def entity_count(self) -> int:
        """Get the number of entities in the graph."""
        return len(self.entities)

    @property
    def relationship_count(self) -> int:
        """Get the number of relationships in the graph."""
        return len(self.relationships)

    def add_entity(
        self,
        entity_type: str = "entity",
        name: str = "",
        entity_id: Optional[EntityID] = None,
        properties: Optional[Dict[str, Any]] = None,
        confidence: float = 1.0,
        source_text: str = None,
        vector: Optional[np.ndarray] = None
    ) -> Entity:
        """
        Add entity node to graph.

        Args:
            entity_type: Type of the entity
            name: Name of the entity
            entity_id: Optional ID for the entity (auto-generated if None)
            properties: Optional properties for the entity
            confidence: Confidence score for the entity (0.0 to 1.0)
            source_text: Optional source text from which the entity was extracted
            vector: Optional embedding vector for the entity

        Returns:
            Entity object that was added
        """
        # Create entity
        entity = Entity(
            entity_id=entity_id,
            entity_type=entity_type,
            name=name,
            properties=properties,
            confidence=confidence,
            source_text=source_text
        )

        # Add to entities collection
        self.entities[entity.id] = entity

        # Index by type
        self._entity_index[entity_type].add(entity.id)

        # Add vector if provided
        if vector is not None and self.vector_store is not None:
            # Add vector with entity ID as metadata
            vector_ids = self.vector_store.add_vectors(
                [vector],
                [{"entity_id": entity.id, "type": entity_type, "name": name}]
            )

            # Store vector ID in entity properties
            if not entity.properties:
                entity.properties = {}

            if "vector_ids" not in entity.properties:
                entity.properties["vector_ids"] = []

            if vector_ids:
                entity.properties["vector_ids"].extend(vector_ids)

        # Store in IPLD
        self._store_entity(entity)

        # Update the root CID
        self._update_root_cid()

        return entity

    def add_relationship(
        self,
        relationship_type: str,
        source: Union[Entity, EntityID],
        target: Union[Entity, EntityID],
        properties: Optional[Dict[str, Any]] = None,
        confidence: float = 1.0,
        source_text: str = None,
        relationship_id: Optional[RelationshipID] = None
    ) -> Relationship:
        """
        Add relationship between entities.

        Args:
            relationship_type: Type of the relationship
            source: Source entity or entity ID
            target: Target entity or entity ID
            properties: Optional properties for the relationship
            confidence: Confidence score for the relationship (0.0 to 1.0)
            source_text: Optional source text from which the relationship was extracted
            relationship_id: Optional ID for the relationship (auto-generated if None)

        Returns:
            Relationship object that was added
        """
        # Create relationship
        relationship = Relationship(
            relationship_id=relationship_id,
            relationship_type=relationship_type,
            source=source,
            target=target,
            properties=properties,
            confidence=confidence,
            source_text=source_text
        )

        # Validate entity IDs
        source_id = relationship.source_id
        target_id = relationship.target_id

        if source_id not in self.entities:
            raise ValueError(f"Source entity {source_id} not found in the graph")

        if target_id not in self.entities:
            raise ValueError(f"Target entity {target_id} not found in the graph")

        # Add to relationships collection
        self.relationships[relationship.id] = relationship

        # Index by type
        self._relationship_index[relationship_type].add(relationship.id)

        # Index by source and target
        self._source_relationships[source_id].add(relationship.id)
        self._target_relationships[target_id].add(relationship.id)

        # Index by entity pair
        self._entity_relationships[(source_id, target_id)].add(relationship.id)

        # Store in IPLD
        self._store_relationship(relationship)

        # Update the root CID
        self._update_root_cid()

        return relationship

    def get_entity(self, entity_id: EntityID) -> Optional[Entity]:
        """
        Get entity by ID.

        Args:
            entity_id: ID of the entity

        Returns:
            Entity if found, None otherwise
        """
        return self.entities.get(entity_id)

    def get_entities_by_type(self, entity_type: str) -> List[Entity]:
        """
        Get entities by type.

        Args:
            entity_type: Type of entities to retrieve

        Returns:
            List of entities of the specified type
        """
        entity_ids = self._entity_index.get(entity_type, set())
        return [self.entities[entity_id] for entity_id in entity_ids if entity_id in self.entities]

    def get_relationship(self, relationship_id: RelationshipID) -> Optional[Relationship]:
        """
        Get relationship by ID.

        Args:
            relationship_id: ID of the relationship

        Returns:
            Relationship if found, None otherwise
        """
        return self.relationships.get(relationship_id)

    def get_relationships_by_type(self, relationship_type: str) -> List[Relationship]:
        """
        Get relationships by type.

        Args:
            relationship_type: Type of relationships to retrieve

        Returns:
            List of relationships of the specified type
        """
        relationship_ids = self._relationship_index.get(relationship_type, set())
        return [self.relationships[relationship_id] for relationship_id in relationship_ids if relationship_id in self.relationships]

    def get_entity_relationships(
        self,
        entity_id: EntityID,
        direction: str = "both",
        relationship_types: Optional[List[str]] = None
    ) -> List[Relationship]:
        """
        Get relationships for an entity.

        Args:
            entity_id: ID of the entity
            direction: Direction of relationships ('outgoing', 'incoming', or 'both')
            relationship_types: Optional list of relationship types to filter by

        Returns:
            List of relationships for the entity
        """
        relationships = []

        # Get outgoing relationships
        if direction in ["outgoing", "both"]:
            outgoing_ids = self._source_relationships.get(entity_id, set())
            for rel_id in outgoing_ids:
                rel = self.relationships.get(rel_id)
                if rel and (relationship_types is None or rel.type in relationship_types):
                    relationships.append(rel)

        # Get incoming relationships
        if direction in ["incoming", "both"]:
            incoming_ids = self._target_relationships.get(entity_id, set())
            for rel_id in incoming_ids:
                rel = self.relationships.get(rel_id)
                if rel and (relationship_types is None or rel.type in relationship_types):
                    relationships.append(rel)

        return relationships

    def query(
        self,
        start_entity: Union[Entity, EntityID],
        relationship_path: List[str],
        max_results: int = 100,
        min_confidence: float = 0.0
    ) -> List[Dict[str, Any]]:
        """
        Query graph following relationship paths.

        Args:
            start_entity: Starting entity or entity ID
            relationship_path: Path of relationship types to follow
            max_results: Maximum number of results to return
            min_confidence: Minimum confidence score for entities and relationships

        Returns:
            List of matching entities and relationships
        """
        # Get start entity ID
        if isinstance(start_entity, Entity):
            start_id = start_entity.id
        else:
            start_id = start_entity

        # Check if start entity exists
        if start_id not in self.entities:
            return []

        # Initialize results with start entity
        results = [{"entity": self.entities[start_id], "path": []}]

        # Follow relationship path
        for rel_type in relationship_path:
            new_results = []

            for result in results:
                current_entity = result["entity"]
                current_path = result["path"]

                # Get relationships of the specified type
                relationships = self.get_entity_relationships(
                    current_entity.id,
                    direction="outgoing",
                    relationship_types=[rel_type]
                )

                # Filter by confidence
                relationships = [rel for rel in relationships if rel.confidence >= min_confidence]

                # Add new results
                for rel in relationships:
                    # Get target entity
                    target_entity = self.entities.get(rel.target_id)
                    if not target_entity or target_entity.confidence < min_confidence:
                        continue

                    # Create new path
                    new_path = current_path + [(rel_type, rel.id, target_entity.id)]

                    # Add to new results
                    new_results.append({
                        "entity": target_entity,
                        "path": new_path
                    })

                    # Check if we've reached the maximum
                    if len(new_results) >= max_results:
                        break

                # Check if we've reached the maximum
                if len(new_results) >= max_results:
                    break

            # Update results for next step
            results = new_results

            # Stop if we have no results
            if not results:
                break

        return results

    def vector_augmented_query(
        self,
        query_vector: np.ndarray,
        relationship_constraints: Optional[List[Dict[str, Any]]] = None,
        top_k: int = 10,
        max_hops: int = 2,
        min_confidence: float = 0.0
    ) -> List[Dict[str, Any]]:
        """
        GraphRAG query combining vector similarity and graph traversal.

        Args:
            query_vector: Query vector for similarity search
            relationship_constraints: Optional constraints on traversal
            top_k: Number of results to return
            max_hops: Maximum number of hops from seed nodes
            min_confidence: Minimum confidence score for entities and relationships

        Returns:
            List of ranked results with entity and relationship data
        """
        if self.vector_store is None:
            raise ValueError("Vector store is required for vector-augmented queries")

        # Phase 1: Vector search to find seed entities
        vector_results = self.vector_store.search(query_vector, top_k=top_k * 2)

        # Extract entity IDs from vector results
        seed_entity_ids = []
        for result in vector_results:
            entity_id = result.metadata.get("entity_id")
            if entity_id and entity_id in self.entities:
                seed_entity_ids.append(entity_id)

        # Phase 2: Graph traversal from seed entities
        graph_results = []
        visited_entities = set()

        for entity_id in seed_entity_ids:
            # Skip if already visited
            if entity_id in visited_entities:
                continue

            # Mark as visited
            visited_entities.add(entity_id)

            # Get the entity
            entity = self.entities.get(entity_id)
            if not entity or entity.confidence < min_confidence:
                continue

            # Find the corresponding vector result
            vector_score = 0.0
            for result in vector_results:
                if result.metadata.get("entity_id") == entity_id:
                    vector_score = result.score
                    break

            # Add the seed entity to results
            graph_results.append({
                "entity": entity,
                "vector_score": vector_score,
                "graph_score": 1.0,  # Maximum graph score for seed entities
                "combined_score": vector_score,  # Will be updated later
                "path": [],  # Empty path for seed entities
                "hops": 0
            })

            # Stop if we have enough results
            if len(graph_results) >= top_k:
                break

        # Traverse the graph if we need more hops
        if max_hops > 0:
            # Traverse from each seed entity
            for hop in range(1, max_hops + 1):
                # Get entities from the previous hop
                prev_hop_entities = [
                    result["entity"].id for result in graph_results
                    if result["hops"] == hop - 1
                ]

                # Expand each entity
                for entity_id in prev_hop_entities:
                    # Get relationships for this entity
                    relationships = self.get_entity_relationships(
                        entity_id,
                        direction="both"
                    )

                    # Filter by constraints if provided
                    if relationship_constraints:
                        filtered_relationships = []
                        for rel in relationships:
                            for constraint in relationship_constraints:
                                rel_type = constraint.get("type")
                                if rel_type and rel.type != rel_type:
                                    continue

                                direction = constraint.get("direction", "both")
                                if direction == "outgoing" and rel.source_id != entity_id:
                                    continue
                                if direction == "incoming" and rel.target_id != entity_id:
                                    continue

                                filtered_relationships.append(rel)
                        relationships = filtered_relationships

                    # Filter by confidence
                    relationships = [rel for rel in relationships if rel.confidence >= min_confidence]

                    # Process each relationship
                    for rel in relationships:
                        # Determine the target entity
                        target_id = rel.target_id if rel.source_id == entity_id else rel.source_id

                        # Skip if already visited
                        if target_id in visited_entities:
                            continue

                        # Mark as visited
                        visited_entities.add(target_id)

                        # Get the target entity
                        target_entity = self.entities.get(target_id)
                        if not target_entity or target_entity.confidence < min_confidence:
                            continue

                        # Calculate graph score based on relationship confidence and hop distance
                        # Score decreases with distance from seed entities
                        graph_score = rel.confidence * (1.0 - (hop / max_hops))

                        # Find source entity in results
                        source_result = next(
                            (r for r in graph_results if r["entity"].id == entity_id),
                            None
                        )

                        if not source_result:
                            continue

                        # Get source's vector score
                        vector_score = source_result["vector_score"] * 0.8  # Discount for hop

                        # Calculate combined score
                        combined_score = (vector_score + graph_score) / 2

                        # Create path information
                        path = source_result["path"].copy()
                        path.append({
                            "source": entity_id,
                            "target": target_id,
                            "relationship": rel.type,
                            "relationship_id": rel.id
                        })

                        # Add to results
                        graph_results.append({
                            "entity": target_entity,
                            "vector_score": vector_score,
                            "graph_score": graph_score,
                            "combined_score": combined_score,
                            "path": path,
                            "hops": hop
                        })

        # Sort results by combined score
        graph_results.sort(key=lambda x: x["combined_score"], reverse=True)

        # Return top-k results
        return graph_results[:top_k]

    def cross_document_reasoning(
        self,
        query: str,
        query_vector: np.ndarray,
        document_node_types: List[str] = ["document", "paper"],
        max_hops: int = 2,
        min_relevance: float = 0.6,
        max_documents: int = 5,
        reasoning_depth: str = "moderate"
    ) -> Dict[str, Any]:
        """
        Reason across multiple documents using entity-mediated connections.

        This method goes beyond simple document retrieval by connecting information
        across multiple documents, identifying complementary or contradictory information,
        and generating synthesized answers with confidence scores.

        Args:
            query: Natural language query to reason about
            query_vector: Query embedding vector
            document_node_types: Types of nodes representing documents
            max_hops: Maximum number of hops between documents
            min_relevance: Minimum relevance score for documents
            max_documents: Maximum number of documents to reason across
            reasoning_depth: Reasoning depth ('basic', 'moderate', or 'deep')

        Returns:
            Dict with the following keys:
            - answer: Synthesized answer to the query
            - documents: Relevant documents used
            - evidence_paths: Paths connecting information
            - confidence: Confidence score for the answer
            - reasoning_trace: Step-by-step reasoning process
        """
        if self.vector_store is None:
            raise ValueError("Vector store is required for cross-document reasoning")

        # Step 1: Find relevant documents using vector search
        vector_results = self.vector_store.search(query_vector, top_k=max_documents * 2)

        # Filter for document nodes
        document_results = []
        for result in vector_results:
            entity_id = result.metadata.get("entity_id")
            entity = self.entities.get(entity_id)

            if entity and entity.type in document_node_types and result.score >= min_relevance:
                document_results.append({
                    "document": entity,
                    "score": result.score
                })

        # Limit to max_documents
        document_results = document_results[:max_documents]

        # Step 2: Find connections between documents through entities
        evidence_paths = []

        # Get all document IDs
        document_ids = [doc["document"].id for doc in document_results]

        # Check all pairs of documents
        for i, doc1 in enumerate(document_results):
            for j, doc2 in enumerate(document_results[i+1:], i+1):
                # Get document entities
                doc1_id = doc1["document"].id
                doc2_id = doc2["document"].id

                # Find entities connected to both documents
                doc1_entities = self._get_connected_entities(doc1_id, max_hops=1)
                doc2_entities = self._get_connected_entities(doc2_id, max_hops=1)

                # Find common entities
                common_entities = doc1_entities.intersection(doc2_entities)

                # Create evidence paths for common entities
                for entity_id in common_entities:
                    entity = self.entities.get(entity_id)
                    if not entity:
                        continue

                    # Create evidence path
                    evidence_paths.append({
                        "doc1": doc1["document"],
                        "doc2": doc2["document"],
                        "entity": entity,
                        "doc1_score": doc1["score"],
                        "doc2_score": doc2["score"],
                        "path_score": (doc1["score"] + doc2["score"]) / 2
                    })

        # Sort evidence paths by score
        evidence_paths.sort(key=lambda x: x["path_score"], reverse=True)

        # Step 3: Generate a synthesized answer (in a real implementation, this would use an LLM)
        # For this implementation, we'll simulate an answer based on the available information

        # Create document summaries
        document_summaries = []
        for doc in document_results:
            document = doc["document"]
            summary = {
                "id": document.id,
                "title": document.properties.get("title", document.name),
                "type": document.type,
                "relevance": doc["score"]
            }
            document_summaries.append(summary)

        # Create evidence chain summaries
        evidence_chain_summaries = []
        for path in evidence_paths:
            chain = {
                "entity_name": path["entity"].name,
                "entity_type": path["entity"].type,
                "doc1_title": path["doc1"].properties.get("title", path["doc1"].name),
                "doc2_title": path["doc2"].properties.get("title", path["doc2"].name),
                "strength": path["path_score"]
            }
            evidence_chain_summaries.append(chain)

        # Create a mock reasoning trace
        reasoning_trace = [
            "Identified relevant documents based on semantic similarity",
            f"Found {len(document_results)} relevant documents above the threshold",
            f"Discovered {len(evidence_paths)} evidence chains connecting documents"
        ]

        if reasoning_depth == "moderate":
            reasoning_trace.append("Analyzed entity-mediated connections between documents")
            reasoning_trace.append("Evaluated consistency and complementarity of information")
        elif reasoning_depth == "deep":
            reasoning_trace.append("Conducted detailed analysis of entity relationships")
            reasoning_trace.append("Evaluated logical consistency across document statements")
            reasoning_trace.append("Identified potential information gaps and contradictions")

        # Calculate confidence based on document relevance and evidence paths
        confidence = 0.0
        if document_results:
            # Base confidence on average document score
            doc_confidence = sum(doc["score"] for doc in document_results) / len(document_results)

            # Adjust based on evidence paths
            if evidence_paths:
                path_confidence = sum(path["path_score"] for path in evidence_paths) / len(evidence_paths)
                # Weight document scores more heavily than paths
                confidence = 0.7 * doc_confidence + 0.3 * path_confidence
            else:
                confidence = doc_confidence

        # Clamp confidence to [0, 1]
        confidence = max(0.0, min(1.0, confidence))

        # Create a sample answer
        if document_results:
            highest_doc = max(document_results, key=lambda x: x["score"])
            answer = f"Based on {len(document_results)} relevant documents"

            if evidence_paths:
                answer += f" connected by {len(evidence_paths)} entity relationships"

            answer += f", the most relevant information comes from the document titled '{highest_doc['document'].properties.get('title', highest_doc['document'].name)}'."

            if evidence_paths:
                top_entity = evidence_paths[0]["entity"].name
                answer += f" The concept of '{top_entity}' appears to be central to answering this query."
        else:
            answer = "Could not find relevant information to answer this query."
            confidence = 0.1

        return {
            "answer": answer,
            "documents": document_summaries,
            "evidence_paths": evidence_chain_summaries,
            "confidence": confidence,
            "reasoning_trace": reasoning_trace
        }

    def get_entities_by_vector_ids(self, vector_ids: List[str]) -> List[Entity]:
        """
        Get entities that reference the given vector IDs.

        Args:
            vector_ids: List of vector IDs (CIDs)

        Returns:
            List of entities referencing these vectors
        """
        # Convert to set for faster lookups
        vector_id_set = set(vector_ids)

        # Find entities that reference any of these vector IDs
        matching_entities = []
        for entity in self.entities.values():
            # Check if the entity has vector_ids in its properties
            entity_vector_ids = entity.properties.get("vector_ids", [])

            # Check for overlap with the provided vector_ids
            if any(vid in vector_id_set for vid in entity_vector_ids):
                matching_entities.append(entity)

        return matching_entities

    def traverse_from_entities(
        self,
        entities: List[Union[Entity, EntityID]],
        relationship_types: Optional[List[str]] = None,
        max_depth: int = 2,
        max_nodes_visited: Optional[int] = None,
        max_edges_traversed: Optional[int] = None
    ) -> List[Entity]:
        """
        Traverse graph from seed entities.

        Args:
            entities: List of starting entities or entity IDs
            relationship_types: Optional list of relationship types to follow
            max_depth: Maximum traversal depth

        Returns:
            List of entities reached through traversal
        """
        traversed = self.traverse_from_entities_with_depths(
            entities=entities,
            relationship_types=relationship_types,
            max_depth=max_depth,
            max_nodes_visited=max_nodes_visited,
            max_edges_traversed=max_edges_traversed,
        )
        return [entity for entity, _depth in traversed]

    def traverse_from_entities_with_depths(
        self,
        entities: List[Union[Entity, EntityID]],
        relationship_types: Optional[List[str]] = None,
        max_depth: int = 2,
        max_nodes_visited: Optional[int] = None,
        max_edges_traversed: Optional[int] = None,
    ) -> List[Tuple[Entity, int]]:
        """Traverse graph from seed entities, returning (entity, depth).

        Depth is the number of hops from the nearest seed entity.
        """
        # Convert to entity IDs
        entity_ids: List[EntityID] = []
        for entity in entities:
            if isinstance(entity, Entity):
                entity_ids.append(entity.id)
            else:
                entity_ids.append(entity)

        # visited_ids tracks all seen nodes; depths records the shortest depth.
        visited_ids: Set[EntityID] = set()
        depths: Dict[EntityID, int] = {}
        result: List[Tuple[Entity, int]] = []

        # Seed queue
        queue = deque()
        for entity_id in entity_ids:
            if entity_id in visited_ids:
                continue
            visited_ids.add(entity_id)
            depths[entity_id] = 0
            entity_obj = self.entities.get(entity_id)
            if entity_obj is not None:
                result.append((entity_obj, 0))
            queue.append((entity_id, 0))

        edges_traversed = 0

        while queue:
            current_id, depth = queue.popleft()
            if depth >= max_depth:
                continue

            # Get relationships for this entity
            relationships = self.get_entity_relationships(
                current_id,
                direction="both",
                relationship_types=relationship_types,
            )
            edges_traversed += len(relationships)
            if max_edges_traversed is not None and edges_traversed >= max_edges_traversed:
                break

            for rel in relationships:
                target_id = rel.target_id if rel.source_id == current_id else rel.source_id
                if target_id in visited_ids:
                    continue

                visited_ids.add(target_id)
                target_depth = depth + 1
                depths[target_id] = target_depth

                entity_obj = self.entities.get(target_id)
                if entity_obj is not None:
                    result.append((entity_obj, target_depth))

                if max_nodes_visited is not None and len(visited_ids) >= max_nodes_visited:
                    return result

                queue.append((target_id, target_depth))

        return result

    def _get_connected_entities(
        self,
        entity_id: EntityID,
        max_hops: int = 1,
        relationship_types: Optional[List[str]] = None
    ) -> Set[EntityID]:
        """
        Get entities connected to the given entity.

        Args:
            entity_id: ID of the entity
            max_hops: Maximum number of hops
            relationship_types: Optional list of relationship types to filter by

        Returns:
            Set of entity IDs connected to the given entity
        """
        # Set of connected entity IDs
        connected_ids = set()

        # Set of visited entity IDs to avoid cycles
        visited_ids = {entity_id}

        # Queue for BFS traversal
        queue = deque([(entity_id, 0)])  # (entity_id, depth)

        while queue:
            current_id, depth = queue.popleft()

            # Stop if we've reached max hops
            if depth > max_hops:
                continue

            # Get relationships for this entity
            relationships = self.get_entity_relationships(
                current_id,
                direction="both",
                relationship_types=relationship_types
            )

            # Process connected entities
            for rel in relationships:
                # Determine the target entity
                target_id = rel.target_id if rel.source_id == current_id else rel.source_id

                # Skip if already visited
                if target_id in visited_ids:
                    continue

                # Mark as visited
                visited_ids.add(target_id)

                # Add to connected IDs
                connected_ids.add(target_id)

                # Add to queue for next iteration (if not at max depth)
                if depth < max_hops:
                    queue.append((target_id, depth + 1))

        return connected_ids

    def _store_entity(self, entity: Entity) -> str:
        """
        Store entity in IPLD.

        Args:
            entity: Entity to store

        Returns:
            CID of the stored entity
        """
        # Convert to dictionary
        entity_dict = entity.to_dict()

        # Generate a CID prefix for deterministic CIDs
        slug = slugify(entity.name) if entity.name else entity.id[:8]

        # Store in IPLD
        entity_bytes = json.dumps(entity_dict).encode()
        entity_cid = self.storage.store(entity_bytes)

        # Update entity with CID
        entity.cid = entity_cid

        # Store in CID index
        self._entity_cids[entity.id] = entity_cid

        return entity_cid

    def _store_relationship(self, relationship: Relationship) -> str:
        """
        Store relationship in IPLD.

        Args:
            relationship: Relationship to store

        Returns:
            CID of the stored relationship
        """
        # Convert to dictionary
        relationship_dict = relationship.to_dict()

        # Store in IPLD
        relationship_bytes = json.dumps(relationship_dict).encode()
        relationship_cid = self.storage.store(relationship_bytes)

        # Update relationship with CID
        relationship.cid = relationship_cid

        # Store in CID index
        self._relationship_cids[relationship.id] = relationship_cid

        return relationship_cid

    def _update_root_cid(self):
        """Update the root CID of the knowledge graph."""
        # Create root node with graph metadata
        root_node = {
            "type": "knowledge_graph",
            "name": self.name,
            "entity_count": len(self.entities),
            "relationship_count": len(self.relationships),
            "entity_types": list(self._entity_index.keys()),
            "relationship_types": list(self._relationship_index.keys()),
        }
        
        # Helper function to store large data as separate block
        def store_if_large(data, field_name):
            data_bytes = json.dumps(data).encode()
            if len(data_bytes) > MAX_BLOCK_SIZE:
                # Store as separate block and return CID reference
                cid = self.storage.store(data_bytes)
                return {"_cid": cid, "_chunked": True}
            return data
        
        # Store entity and relationship data, chunking if necessary
        root_node["entity_ids"] = store_if_large(
            list(self.entities.keys()), 
            "entity_ids"
        )
        root_node["entity_cids"] = store_if_large(
            self._entity_cids, 
            "entity_cids"
        )
        root_node["relationship_ids"] = store_if_large(
            list(self.relationships.keys()), 
            "relationship_ids"
        )
        root_node["relationship_cids"] = store_if_large(
            self._relationship_cids, 
            "relationship_cids"
        )

        # Store the root node
        root_bytes = json.dumps(root_node).encode()
        self.root_cid = self.storage.store(root_bytes)

    def export_to_car(self, output_path: str) -> str:
        """
        Export knowledge graph to CAR file.

        Args:
            output_path: Path to output CAR file

        Returns:
            Root CID of the exported graph
        """
        if not HAVE_IPLD_CAR:
            raise ImportError("ipld_car module is required for CAR file export")

        # Make sure the root CID is updated
        self._update_root_cid()

        # Collect all blocks
        blocks = {}

        # Add the root block
        root_block = self.storage.get(self.root_cid)
        if root_block:
            blocks[self.root_cid] = root_block

        # Add all entity blocks
        for entity_id, entity_cid in self._entity_cids.items():
            entity_block = self.storage.get(entity_cid)
            if entity_block:
                blocks[entity_cid] = entity_block

        # Add all relationship blocks
        for rel_id, rel_cid in self._relationship_cids.items():
            rel_block = self.storage.get(rel_cid)
            if rel_block:
                blocks[rel_cid] = rel_block

        # Convert blocks to the format expected by ipld_car
        car_blocks = [(cid, data) for cid, data in blocks.items()]

        # Encode as CAR file
        car_data = ipld_car.encode([self.root_cid], car_blocks)

        # Write to file
        with open(output_path, "wb") as f:
            f.write(car_data)

        return self.root_cid

    @classmethod
    def from_cid(
        cls,
        cid: str,
        storage: Optional[IPLDStorage] = None,
        vector_store: Optional[IPLDVectorStore] = None
    ) -> 'IPLDKnowledgeGraph':
        """
        Load knowledge graph from IPFS by CID.

        Args:
            cid: Root CID of the knowledge graph
            storage: Optional IPLD storage to use
            vector_store: Optional vector store to use

        Returns:
            Loaded knowledge graph
        """
        # Initialize storage if not provided
        storage = storage or IPLDStorage()

        # Get the root node
        root_bytes = storage.get(cid)
        if not root_bytes:
            raise ValueError(f"Could not find root node with CID {cid}")

        root_node = json.loads(root_bytes.decode())

        # Check if it's a knowledge graph
        if root_node.get("type") != "knowledge_graph":
            raise ValueError(f"Node with CID {cid} is not a knowledge graph")

        # Create a new knowledge graph
        kg = cls(
            name=root_node.get("name", "knowledge_graph"),
            storage=storage,
            vector_store=vector_store
        )

        # Set the root CID
        kg.root_cid = cid

        # Helper function to load data that might be chunked
        def load_data(field_value):
            """Load data, handling both inline and chunked formats."""
            if isinstance(field_value, dict) and field_value.get("_chunked"):
                # Data is stored in a separate block
                chunked_cid = field_value.get("_cid")
                if chunked_cid:
                    chunked_bytes = storage.get(chunked_cid)
                    return json.loads(chunked_bytes.decode())
            return field_value

        # Load entity and relationship CIDs, handling chunked data
        kg._entity_cids = load_data(root_node.get("entity_cids", {}))
        kg._relationship_cids = load_data(root_node.get("relationship_cids", {}))

        # Load entities
        for entity_id, entity_cid in kg._entity_cids.items():
            entity_bytes = storage.get(entity_cid)
            if not entity_bytes:
                logging.warning(f"Could not find entity with CID {entity_cid}")
                continue

            entity_dict = json.loads(entity_bytes.decode())
            entity = Entity.from_dict(entity_dict)
            entity.cid = entity_cid

            # Add to entities collection
            kg.entities[entity.id] = entity

            # Index by type
            kg._entity_index[entity.type].add(entity.id)

        # Load relationships
        for rel_id, rel_cid in kg._relationship_cids.items():
            rel_bytes = storage.get(rel_cid)
            if not rel_bytes:
                logging.warning(f"Could not find relationship with CID {rel_cid}")
                continue

            rel_dict = json.loads(rel_bytes.decode())
            relationship = Relationship.from_dict(rel_dict)
            relationship.cid = rel_cid

            # Add to relationships collection
            kg.relationships[relationship.id] = relationship

            # Index by type
            kg._relationship_index[relationship.type].add(relationship.id)

            # Index by source and target
            kg._source_relationships[relationship.source_id].add(relationship.id)
            kg._target_relationships[relationship.target_id].add(relationship.id)

            # Index by entity pair
            kg._entity_relationships[(relationship.source_id, relationship.target_id)].add(relationship.id)

        return kg

    @classmethod
    def from_car(
        cls,
        car_path: str,
        storage: Optional[IPLDStorage] = None,
        vector_store: Optional[IPLDVectorStore] = None
    ) -> 'IPLDKnowledgeGraph':
        """
        Load knowledge graph from CAR file.

        Args:
            car_path: Path to CAR file
            storage: Optional IPLD storage to use
            vector_store: Optional vector store to use

        Returns:
            Loaded knowledge graph
        """
        if not HAVE_IPLD_CAR:
            raise ImportError("ipld_car module is required for CAR file import")

        # Initialize storage if not provided
        storage = storage or IPLDStorage()

        # Read CAR file
        with open(car_path, "rb") as f:
            car_data = f.read()

        # Decode CAR file
        roots, blocks = ipld_car.decode(car_data)
        if not roots:
            raise ValueError("CAR file has no roots")

        root_cid = roots[0]

        # Import blocks into storage
        for cid, block_data in blocks.items():
            storage.put(cid, block_data)

        # Load knowledge graph from root CID
        return cls.from_cid(root_cid, storage, vector_store)

    def __str__(self) -> str:
        """Get string representation of the knowledge graph."""
        return f"IPLDKnowledgeGraph(name={self.name}, entities={len(self.entities)}, relationships={len(self.relationships)})"
