"""
GraphRAG Integration Module for PDF Processing Pipeline

Integrates processed PDF content into GraphRAG knowledge graph:
- Creates entity-relationship structures
- Builds knowledge graph representations
- Supports cross-document relationship discovery
- Enables semantic querying and retrieval
- Maintains IPLD data integrity
"""
import logging
import hashlib
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, asdict
from datetime import datetime
import uuid
import re

import networkx as nx
import numpy as np

from ipfs_datasets_py.ipld import IPLDStorage
from ipfs_datasets_py.pdf_processing.llm_optimizer import LLMDocument, LLMChunk


logger = logging.getLogger(__name__)

@dataclass
class Entity:
    """
    Represents an entity extracted from documents for knowledge graph construction.

    An entity is a distinct object, concept, person, organization, or location
    identified within text chunks during the document processing pipeline.

    Attributes:
        id (str): Unique identifier for the entity within the knowledge graph.
        name (str): The canonical name or primary label of the entity.
        type (str): Category classification of the entity. Common types include:
            - 'person': Individual people
            - 'organization': Companies, institutions, groups
            - 'concept': Abstract ideas, topics, themes
            - 'location': Geographic places, addresses
            - 'event': Occurrences, incidents, activities
            - 'object': Physical items, products, artifacts
        description (str): Detailed textual description providing context and 
            additional information about the entity.
        confidence (float): Confidence score (0.0-1.0) indicating the reliability
            of the entity extraction and classification.
        source_chunks (List[str]): List of chunk identifiers where this entity
            appears, enabling traceability back to source documents.
        properties (Dict[str, Any]): Additional metadata and attributes specific
            to the entity type (e.g., dates, relationships, custom fields).
        embedding (Optional[np.ndarray]): High-dimensional vector representation
            of the entity for semantic similarity calculations. Defaults to None
            if not computed.

    Example:
        >>> entity = Entity(
        ...     id="ent_001",
        ...     name="John Smith",
        ...     type="person",
        ...     description="Software engineer at Tech Corp",
        ...     confidence=0.95,
        ...     source_chunks=["chunk_1", "chunk_3"],
        ...     properties={"role": "engineer", "company": "Tech Corp"}
        ... )
    """
    id: str
    name: str
    type: str  # 'person', 'organization', 'concept', 'location', etc.
    description: str
    confidence: float
    source_chunks: List[str]  # Chunk IDs where entity appears
    properties: Dict[str, Any]
    embedding: Optional[np.ndarray] = None

@dataclass
class Relationship:
    """
    Represents a relationship between two entities in a knowledge graph.

    This dataclass encapsulates the complete information about a relationship,
    including its participants, type, confidence metrics, and supporting evidence.

    Attributes:
        id (str): Unique identifier for this relationship instance.
        source_entity_id (str): Identifier of the entity that is the source/subject 
            of the relationship.
        target_entity_id (str): Identifier of the entity that is the target/object 
            of the relationship.
        relationship_type (str): The type or category of relationship (e.g., 
            "works_for", "located_in", "related_to").
        description (str): Human-readable description providing context and details 
            about the relationship.
        confidence (float): Confidence score indicating the reliability of this 
            relationship, typically in the range [0.0, 1.0].
        source_chunks (List[str]): List of source text chunks or document sections 
            that provide evidence for this relationship.
        properties (Dict[str, Any]): Additional metadata and properties associated 
            with the relationship, allowing for flexible extension of relationship 
            attributes.

    Example:
        >>> relationship = Relationship(
        ...     id="rel_001",
        ...     source_entity_id="person_123",
        ...     target_entity_id="company_456",
        ...     relationship_type="works_for",
        ...     description="John Doe is employed by Acme Corp as a software engineer",
        ...     confidence=0.95,
        ...     source_chunks=["chunk_1", "chunk_5"],
        ...     properties={"role": "software_engineer", "start_date": "2023-01-15"}
        ... )
    """
    id: str
    source_entity_id: str
    target_entity_id: str
    relationship_type: str
    description: str
    confidence: float
    source_chunks: List[str]
    properties: Dict[str, Any]

@dataclass
class KnowledgeGraph:
    """
    Complete knowledge graph representation containing entities, relationships, and document chunks.

    This class represents a comprehensive knowledge graph extracted from a document,
    including all entities, their relationships, the original text chunks, and associated
    metadata. It serves as the primary data structure for storing and managing
    knowledge graphs within the IPFS datasets system.

    Attributes:
        graph_id (str): Unique identifier for this knowledge graph instance.
        document_id (str): Identifier of the source document from which this graph was extracted.
        entities (List[Entity]): Collection of all entities identified in the document.
        relationships (List[Relationship]): Collection of relationships between entities.
        chunks (List[LLMChunk]): Original text chunks used for entity and relationship extraction.
        metadata (Dict[str, Any]): Additional metadata about the graph generation process,
            including extraction parameters, model information, and processing statistics.
        creation_timestamp (str): ISO 8601 timestamp indicating when the graph was created.
        ipld_cid (Optional[str]): Content identifier for IPFS/IPLD storage, set when the
            graph is stored in a distributed system. Defaults to None for newly created graphs.

    Example:
        >>> kg = KnowledgeGraph(
        ...     graph_id="kg_001",
        ...     document_id="doc_123",
        ...     entities=[entity1, entity2],
        ...     relationships=[rel1, rel2],
        ...     chunks=[chunk1, chunk2],
        ...     metadata={"model": "gpt-4", "confidence": 0.95},
        ...     creation_timestamp="2024-01-01T12:00:00Z"
        ... )
    """
    graph_id: str
    document_id: str
    entities: List[Entity]
    relationships: List[Relationship]
    chunks: List[LLMChunk]
    metadata: Dict[str, Any]
    creation_timestamp: str
    ipld_cid: Optional[str] = None


@dataclass
class CrossDocumentRelationship:
    """
    Represents a relationship between entities that spans across multiple documents.

    This dataclass captures relationships discovered between entities from different
    source documents, enabling cross-document knowledge discovery and connection
    mining within the knowledge graph system.

    Attributes:
        id (str): Unique identifier for this cross-document relationship instance.
        source_document_id (str): Identifier of the document containing the source entity.
        target_document_id (str): Identifier of the document containing the target entity.
        source_entity_id (str): Identifier of the entity in the source document that
            participates in this relationship.
        target_entity_id (str): Identifier of the entity in the target document that
            participates in this relationship.
        relationship_type (str): Type of cross-document relationship discovered.
            Common types include:
            - 'same_entity': Same entity mentioned across documents
            - 'similar_entity': Similar or related entities
            - 'references': One entity references another across documents
            - 'related_concept': Conceptually related entities
        confidence (float): Confidence score (0.0-1.0) indicating the reliability
            of the cross-document relationship discovery.
        evidence_chunks (List[str]): List of text chunk identifiers from both
            documents that provide evidence supporting this relationship.

    Example:
        >>> cross_rel = CrossDocumentRelationship(
        ...     id="cross_rel_001",
        ...     source_document_id="doc_123",
        ...     target_document_id="doc_456",
        ...     source_entity_id="entity_abc",
        ...     target_entity_id="entity_def",
        ...     relationship_type="same_entity",
        ...     confidence=0.95,
        ...     evidence_chunks=["chunk_1", "chunk_2", "chunk_10"]
        ... )
    """
    id: str
    source_document_id: str
    target_document_id: str
    source_entity_id: str
    target_entity_id: str
    relationship_type: str
    confidence: float
    evidence_chunks: List[str]

class GraphRAGIntegrator:
    """
    GraphRAG Integrator for PDF Content Processing
    The GraphRAGIntegrator class provides comprehensive functionality for integrating PDF content
    into GraphRAG (Graph Retrieval-Augmented Generation) knowledge structures. It processes
    LLM-optimized documents, extracts entities and relationships, creates knowledge graphs,
    and enables sophisticated querying capabilities across document collections.
    This class serves as the core component for building knowledge graphs from PDF documents,
    supporting both single-document analysis and cross-document relationship discovery.

    Key Features:
    - Entity extraction using pattern matching and NLP techniques
    - Relationship inference based on co-occurrence and context analysis
    - Cross-document entity linking and relationship discovery
    - IPLD (InterPlanetary Linked Data) storage integration
    - NetworkX graph representations for advanced analysis
    - Natural language querying capabilities
    - Entity neighborhood exploration

    Attributes:
        storage (IPLDStorage): IPLD storage instance for persistent graph storage
        similarity_threshold (float): Threshold for entity similarity matching (0.0-1.0)
        entity_extraction_confidence (float): Minimum confidence for entity extraction (0.0-1.0)
        knowledge_graphs (Dict[str, KnowledgeGraph]): Collection of document knowledge graphs
        global_entities (Dict[str, Entity]): Global entity registry across all documents
        cross_document_relationships (List[CrossDocumentRelationship]): Inter-document relationships
        document_graphs (Dict[str, nx.DiGraph]): NetworkX representations per document
        global_graph (nx.DiGraph): Global NetworkX graph combining all documents

    Public Methods:
        integrate_document(llm_document: LLMDocument) -> KnowledgeGraph:
            Extracts entities, relationships, creates knowledge graph, stores in IPLD,
            and updates global graph structures.
        query_graph(query: str, graph_id: Optional[str] = None, max_results: int = 10) -> Dict[str, Any]:
            Query the knowledge graph using natural language queries.
            Supports both document-specific and global graph querying with keyword-based
            and semantic search capabilities.
        get_entity_neighborhood(entity_id: str, depth: int = 2) -> Dict[str, Any]:
            Retrieve the neighborhood of a specific entity within the graph.
            Returns subgraph containing all nodes and edges within specified depth
            from the target entity.

    Private Methods:
        _extract_entities_from_chunks(chunks: List[LLMChunk]) -> List[Entity]:
            Extract and consolidate entities from document chunks using pattern matching
            and confidence filtering.
        _extract_entities_from_text(text: str, chunk_id: str) -> List[Dict[str, Any]]:
            Extract entities from individual text chunks using regex patterns for
            persons, organizations, locations, dates, and currency.
        _extract_relationships(entities: List[Entity], chunks: List[LLMChunk]) -> List[Relationship]:
            Extract relationships between entities within and across chunks using
            co-occurrence analysis and context inference.
        _extract_chunk_relationships(entities: List[Entity], chunk: LLMChunk) -> List[Relationship]:
            Extract relationships between entities within a single chunk based on
            co-occurrence and contextual analysis.
        _extract_cross_chunk_relationships(entities: List[Entity], chunks: List[LLMChunk]) -> List[Relationship]:
            Extract relationships between entities across different chunks using
            narrative sequence analysis.
        _infer_relationship_type(entity1: Entity, entity2: Entity, context: str) -> Optional[str]:
            Infer relationship type between two entities based on contextual keywords
            and entity types (e.g., 'works_for', 'founded', 'partners_with').
        _find_chunk_sequences(chunks: List[LLMChunk]) -> List[List[str]]:
            Identify sequences of related chunks (e.g., same page, sequential order)
            for narrative relationship extraction.
        _create_networkx_graph(knowledge_graph: KnowledgeGraph) -> nx.DiGraph:
            Create NetworkX directed graph representation from knowledge graph
            with entities as nodes and relationships as edges.
        _merge_into_global_graph(knowledge_graph: KnowledgeGraph):
            Merge document-specific knowledge graph into global graph structure,
            updating entity registry and NetworkX representation.
        _discover_cross_document_relationships(knowledge_graph: KnowledgeGraph):
            Discover and create relationships between entities across different documents
            using entity similarity and matching algorithms.
        _find_similar_entities(entity: Entity) -> List[Entity]:
            Find entities similar to a given entity across all documents using
            name similarity and type matching.
        _calculate_text_similarity(text1: str, text2: str) -> float:
            Calculate Jaccard similarity between two text strings based on
            word-level intersection and union.
        _store_knowledge_graph_ipld(knowledge_graph: KnowledgeGraph) -> str:
            Store knowledge graph in IPLD format with JSON serialization,
            handling numpy array conversion for embeddings.

    Usage Example:
        integrator = GraphRAGIntegrator(
            similarity_threshold=0.8,
            entity_extraction_confidence=0.6
        # Process document
        knowledge_graph = await integrator.integrate_document(llm_document)
        # Query the graph
        results = await integrator.query_graph("companies founded by John Smith")
        # Explore entity relationships
        neighborhood = await integrator.get_entity_neighborhood("entity_12345", depth=2)

    Notes:
        - Entity extraction uses regex patterns and can be enhanced with advanced NLP models
        - Relationship inference is based on co-occurrence and keyword matching
        - Cross-document relationships enable knowledge discovery across document collections
        - IPLD storage provides content-addressable persistence for knowledge graphs
        - NetworkX integration enables advanced graph analysis and algorithms
    """
    def __init__(self, 
                 storage: Optional[IPLDStorage] = None,
                 similarity_threshold: float = 0.8,
                 entity_extraction_confidence: float = 0.6):
        """
        This class integrates Knowledge Graphs with Retrieval-Augmented Generation (RAG)
        for enhanced document processing and analysis capabilities.

        Args:
            storage (Optional[IPLDStorage], optional): IPLD storage instance for data persistence.
                Defaults to a new IPLDStorage instance if not provided.
            similarity_threshold (float, optional): Threshold for entity similarity matching.
                Values between 0.0 and 1.0, where higher values require more similarity.
                Defaults to 0.8.
            entity_extraction_confidence (float, optional): Minimum confidence score for 
                entity extraction. Values between 0.0 and 1.0, where higher values require
                more confidence. Defaults to 0.6.

        Attributes initialized:
            storage (IPLDStorage): IPLD storage instance for data persistence.
            similarity_threshold (float): Threshold for entity similarity matching.
            entity_extraction_confidence (float): Minimum confidence for entity extraction.
            knowledge_graphs (Dict[str, KnowledgeGraph]): Storage for document-specific 
                knowledge graphs, keyed by document identifier.
            global_entities (Dict[str, Entity]): Global registry of entities across all
                documents, keyed by entity identifier.
            cross_document_relationships (List[CrossDocumentRelationship]): List of 
                relationships that span across multiple documents.
            document_graphs (Dict[str, nx.DiGraph]): NetworkX directed graphs for each
                document, keyed by document identifier.
            global_graph (nx.DiGraph): Global NetworkX directed graph containing all
                entities and relationships across documents.
        """
        self.storage = storage or IPLDStorage()
        self.similarity_threshold = similarity_threshold
        self.entity_extraction_confidence = entity_extraction_confidence
        
        # Graph storage
        self.knowledge_graphs: Dict[str, KnowledgeGraph] = {}
        self.global_entities: Dict[str, Entity] = {}
        self.cross_document_relationships: List[CrossDocumentRelationship] = []
        
        # NetworkX graphs for analysis
        self.document_graphs: Dict[str, nx.DiGraph] = {}
        self.global_graph = nx.DiGraph()
        
    async def integrate_document(self, llm_document: LLMDocument) -> KnowledgeGraph:
        """
        Integrate an LLM-optimized document into the GraphRAG system.

        This method performs end-to-end integration of a processed document into the GraphRAG
        knowledge graph system. It extracts entities and relationships from document chunks,
        creates a comprehensive knowledge graph, stores it in IPLD for distributed access,
        and merges it with the global knowledge graph to enable cross-document reasoning.

        Args:
            llm_document (LLMDocument): Pre-processed document containing optimized chunks,
                                       embeddings, and metadata from LLM processing pipeline.
                                       Must include document_id, title, and processed chunks.
            KnowledgeGraph: Comprehensive knowledge graph object containing:
                           - Extracted entities with types and attributes
                           - Discovered relationships with confidence scores
                           - Document chunks with semantic mappings
                           - IPLD CID for distributed storage
                           - Processing metadata and timestamps
                           - Unique graph identifier for tracking

        Returns:
            KnowledgeGraph: The created knowledge graph containing entities, relationships,
                            and metadata for the integrated document.

        Raises:
            ValueError: If llm_document is invalid or missing required fields
            IPLDStorageError: If knowledge graph cannot be stored in IPLD
            GraphProcessingError: If entity/relationship extraction fails
            NetworkError: If cross-document relationship discovery fails

        Example:
            >>> document = LLMDocument(document_id="doc123", title="Research Paper", chunks=[...])
            >>> kg = await integrator.integrate_document(document)

            >>> print(f"Created knowledge graph with {len(kg.entities)} entities")
        Note:
            This is an expensive operation that involves multiple AI model calls for entity
            and relationship extraction. Consider batching documents or using async processing
            for large document sets. The resulting knowledge graph is automatically merged
            with existing graphs to maintain global consistency.
        """
        logger.info(f"Starting GraphRAG integration for document: {llm_document.document_id}")
        
        # Extract entities from chunks
        entities = await self._extract_entities_from_chunks(llm_document.chunks)
        
        # Extract relationships
        relationships = await self._extract_relationships(entities, llm_document.chunks)
        
        # Create knowledge graph
        knowledge_graph = KnowledgeGraph(
            graph_id=f"kg_{llm_document.document_id}_{uuid.uuid4().hex[:8]}",
            document_id=llm_document.document_id,
            entities=entities,
            relationships=relationships,
            chunks=llm_document.chunks,
            metadata={
                'document_title': llm_document.title,
                'entity_count': len(entities),
                'relationship_count': len(relationships),
                'chunk_count': len(llm_document.chunks),
                'processing_timestamp': datetime.utcnow().isoformat()
            },
            creation_timestamp=datetime.utcnow().isoformat()
        )
        
        # Store in IPLD
        ipld_cid = await self._store_knowledge_graph_ipld(knowledge_graph)
        knowledge_graph.ipld_cid = ipld_cid
        
        # Update internal storage
        self.knowledge_graphs[knowledge_graph.graph_id] = knowledge_graph
        
        # Create NetworkX representation
        nx_graph = await self._create_networkx_graph(knowledge_graph)
        self.document_graphs[llm_document.document_id] = nx_graph
        
        # Merge with global graph
        await self._merge_into_global_graph(knowledge_graph)
        
        # Discover cross-document relationships
        await self._discover_cross_document_relationships(knowledge_graph)
        
        logger.info(f"GraphRAG integration complete: {len(entities)} entities, {len(relationships)} relationships")
        return knowledge_graph
    
    async def _extract_entities_from_chunks(self, chunks: List[LLMChunk]) -> List[Entity]:
        """Extract and consolidate entities from a list of LLM chunks.

        This method processes text chunks to identify and extract named entities, then
        consolidates duplicate entities across chunks to create a unified entity list.
        The extraction process includes entity deduplication, confidence scoring, and
        property merging.

        Args:
            chunks (List[LLMChunk]): List of text chunks to process for entity extraction.
                Each chunk should contain content and a unique chunk_id.

        Returns:
            List[Entity]: A filtered list of unique entities extracted from all chunks.
                Only entities meeting the minimum confidence threshold are included.
                Each entity contains:
                - Unique ID generated from name and type hash
                - Consolidated properties from all mentions
                - Maximum confidence score across all mentions
                - List of source chunk IDs where the entity was found

        Raises:
            Exception: May raise exceptions from the underlying entity extraction service
                or if chunk processing fails.

        Note:
            - Entities are deduplicated based on case-insensitive name and type matching
            - Entity confidence scores are maximized across multiple mentions
            - Properties from different mentions are merged (first occurrence wins for conflicts)
            - Only entities with confidence >= self.entity_extraction_confidence are returned
        """
        entities = []
        entity_mentions = {}  # Track entity mentions across chunks
        
        for chunk in chunks:
            # Extract entities from chunk content
            chunk_entities = await self._extract_entities_from_text(
                chunk.content, 
                chunk.chunk_id
            )
            
            for entity_data in chunk_entities:
                entity_key = (entity_data['name'].lower(), entity_data['type'])
                
                if entity_key in entity_mentions:
                    # Update existing entity
                    existing_entity = entity_mentions[entity_key]
                    existing_entity.source_chunks.append(chunk.chunk_id)
                    existing_entity.confidence = max(existing_entity.confidence, entity_data['confidence'])
                    
                    # Merge properties
                    for key, value in entity_data.get('properties', {}).items():
                        if key not in existing_entity.properties:
                            existing_entity.properties[key] = value
                else:
                    # Create new entity
                    entity_key = f"{entity_data['name']}_{entity_data['type']}"
                    entity_id = f"entity_{hashlib.md5(entity_key.encode()).hexdigest()[:8]}"
                    
                    entity = Entity(
                        id=entity_id,
                        name=entity_data['name'],
                        type=entity_data['type'],
                        description=entity_data.get('description', ''),
                        confidence=entity_data['confidence'],
                        source_chunks=[chunk.chunk_id],
                        properties=entity_data.get('properties', {}),
                        embedding=entity_data.get('embedding')
                    )
                    
                    entity_mentions[entity_key] = entity
                    entities.append(entity)
        
        # Filter entities by confidence
        filtered_entities = [
            entity for entity in entities 
            if entity.confidence >= self.entity_extraction_confidence
        ]
        
        logger.info(f"Extracted {len(filtered_entities)} entities from {len(chunks)} chunks")
        return filtered_entities
    
    async def _extract_entities_from_text(self, text: str, chunk_id: str) -> List[Dict[str, Any]]:
        """Extract named entities from a text chunk using pattern matching.

        This method identifies various types of entities (persons, organizations, locations,
        dates, and currency amounts) from the input text using regular expression patterns.
        It provides a foundation for entity extraction that can be enhanced with more
        sophisticated NLP models.

        Args:
            text (str): The input text chunk from which to extract entities.
            chunk_id (str): Unique identifier for the text chunk, used for tracking
                           and linking entities back to their source.

        Returns:
            List[Dict[str, Any]]: A list of unique entities found in the text, where each
                                 entity is represented as a dictionary containing:
                                 - 'name': The extracted entity text
                                 - 'type': Entity category ('person', 'organization', 'location', 'date', 'currency')
                                 - 'description': Human-readable description of the entity
                                 - 'confidence': Confidence score (0.7 for pattern matching)
                                 - 'properties': Additional metadata including extraction method and source chunk

        Entity Types Supported:
            - person: Names with titles (Dr. John Smith) or standard format (John Smith)
            - organization: Companies, corporations, universities with common suffixes
            - location: Addresses and city/state combinations
            - date: Various date formats (MM/DD/YYYY, Month DD, YYYY)
            - currency: Dollar amounts and currency expressions

        Raises:
            re.error: If any of the regex patterns are malformed (unlikely with static patterns).
        """
        entities = []
        
        # Named Entity Recognition patterns (can be enhanced with NLP models)
        patterns = {
            'person': [
                r'\b[A-Z][a-z]+ [A-Z][a-z]+\b',  # John Smith
                r'\b(?:Dr|Mr|Ms|Mrs|Prof)\.?\s+[A-Z][a-z]+ [A-Z][a-z]+\b'  # Dr. John Smith
            ],
            'organization': [
                r'\b[A-Z][a-z]+ (?:Inc|Corp|LLC|Ltd|Company|Corporation)\b',
                r'\b[A-Z][A-Z]+ [A-Z][a-z]+\b',  # IBM Corp
                r'\b[A-Z][a-z]+ University\b'
            ],
            'location': [
                r'\b[A-Z][a-z]+(?:,\s*[A-Z][a-z]+)*(?:,\s*[A-Z]{2})\b',  # City, State
                r'\b[A-Z][a-z]+ (?:Street|Avenue|Road|Boulevard|Drive)\b'
            ],
            'date': [
                r'\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b',
                r'\b(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+\d{4}\b'
            ],
            'currency': [
                r'\$\d{1,3}(?:,\d{3})*(?:\.\d{2})?\b',
                r'\b\d{1,3}(?:,\d{3})*(?:\.\d{2})?\s*(?:dollars|USD|cents)\b'
            ]
        }
        
        for entity_type, type_patterns in patterns.items():
            for pattern in type_patterns:
                matches = re.findall(pattern, text, re.IGNORECASE)
                for match in matches:
                    if len(match.strip()) > 2:  # Minimum length filter
                        entities.append({
                            'name': match.strip(),
                            'type': entity_type,
                            'description': f'{entity_type.capitalize()} found in chunk {chunk_id}',
                            'confidence': 0.7,  # Base confidence for pattern matching
                            'properties': {
                                'extraction_method': 'pattern_matching',
                                'source_chunk': chunk_id
                            }
                        })
        
        # Remove duplicates
        unique_entities = []
        seen_names = set()
        for entity in entities:
            name_key = entity['name'].lower()
            if name_key not in seen_names:
                seen_names.add(name_key)
                unique_entities.append(entity)
        
        return unique_entities
    
    async def _extract_relationships(self, 
                                   entities: List[Entity], 
                                   chunks: List[LLMChunk]) -> List[Relationship]:
        """Extract relationships between entities from text chunks.

        This method performs a two-phase relationship extraction process:
        1. Intra-chunk relationships: Identifies relationships between entities that
            appear together within the same text chunk
        2. Cross-chunk relationships: Discovers relationships between entities that
            span across different chunks within the same document

        The method builds an entity index for efficient lookup and processes
        relationships at both the local (chunk-level) and document-level scope
        to ensure comprehensive relationship mapping.

        Args:
            entities (List[Entity]): List of extracted entities with their source
                chunk references
            chunks (List[LLMChunk]): List of text chunks to analyze for relationships

        Returns:
            List[Relationship]: Combined list of all discovered relationships,
                including both intra-chunk and cross-chunk relationships

        Note:
            - Chunks with fewer than 2 entities are skipped for intra-chunk processing
            - Cross-chunk relationship extraction considers entity co-occurrence patterns
            - The total count of extracted relationships is logged for monitoring
        """

        relationships = []
        
        # Build entity index for quick lookup
        entity_by_chunk = {}
        for entity in entities:
            for chunk_id in entity.source_chunks:
                if chunk_id not in entity_by_chunk:
                    entity_by_chunk[chunk_id] = []
                entity_by_chunk[chunk_id].append(entity)
        
        # Extract relationships within chunks
        for chunk in chunks:
            chunk_entities = entity_by_chunk.get(chunk.chunk_id, [])
            if len(chunk_entities) >= 2:
                chunk_relationships = await self._extract_chunk_relationships(
                    chunk_entities, chunk
                )
                relationships.extend(chunk_relationships)
        
        # Extract cross-chunk relationships (same document)
        cross_chunk_relationships = await self._extract_cross_chunk_relationships(
            entities, chunks
        )
        relationships.extend(cross_chunk_relationships)
        
        logger.info(f"Extracted {len(relationships)} relationships")
        return relationships
    
    async def _extract_chunk_relationships(self, 
                                         entities: List[Entity], 
                                         chunk: LLMChunk) -> List[Relationship]:
        """Extract relationships between entities found within a single text chunk.

        This method identifies potential relationships by analyzing co-occurrence patterns
        of entities within the same chunk of text. It creates relationship objects based
        on contextual analysis and assigns confidence scores.

        Args:
            entities (List[Entity]): List of entities previously extracted from the chunk.
                Each entity should have 'id', 'name', and other relevant attributes.
            chunk (LLMChunk): The text chunk containing the entities. Must have 'content'
                and 'chunk_id' attributes for relationship extraction and tracking.

        Returns:
            List[Relationship]: A list of relationship objects connecting pairs of entities.
                Each relationship includes:
                - Unique identifier and source/target entity IDs
                - Inferred relationship type and descriptive text
                - Confidence score (base 0.6 for co-occurrence)
                - Source chunk reference and extraction metadata
                - Context snippet for relationship validation
        Notes:
            - Uses case-insensitive entity name matching within chunk content
            - Generates relationships for all entity pairs that co-occur in the text
            - Relationship types are inferred using contextual analysis
            - Only creates relationships when a valid type can be determined
            - Assigns MD5-based unique IDs to prevent duplicates
            - Includes extraction method metadata for traceability
        Example:
            If entities ["Apple Inc.", "iPhone"] are found in a chunk about product launches,
            this might generate a relationship with type "manufactures" connecting them.
        """
        relationships = []
        
        # Simple co-occurrence based relationships
        for i, entity1 in enumerate(entities):
            for entity2 in entities[i+1:]:
                # Check if entities co-occur in the chunk
                text_lower = chunk.content.lower()
                if (entity1.name.lower() in text_lower and 
                    entity2.name.lower() in text_lower):
                    
                    # Determine relationship type based on context
                    relationship_type = self._infer_relationship_type(
                        entity1, entity2, chunk.content
                    )
                    
                    if relationship_type:
                        rel_id = f"rel_{hashlib.md5(f'{entity1.id}_{entity2.id}_{relationship_type}'.encode()).hexdigest()[:8]}"
                        
                        relationship = Relationship(
                            id=rel_id,
                            source_entity_id=entity1.id,
                            target_entity_id=entity2.id,
                            relationship_type=relationship_type,
                            description=f"{entity1.name} {relationship_type} {entity2.name}",
                            confidence=0.6,  # Base confidence for co-occurrence
                            source_chunks=[chunk.chunk_id],
                            properties={
                                'extraction_method': 'co_occurrence',
                                'context_snippet': chunk.content[:200] + '...' if len(chunk.content) > 200 else chunk.content
                            }
                        )
                        relationships.append(relationship)
        
        return relationships
    
    def _infer_relationship_type(self, entity1: Entity, entity2: Entity, context: str) -> Optional[str]:
        """
        Infer the relationship type between two entities based on contextual information.

        This method analyzes the context string to determine the most appropriate relationship
        type between two entities by examining keywords and entity types. It supports various
        relationship categories including professional, organizational, and personal connections.

        Args:
            entity1 (Entity): The first entity in the relationship
            entity2 (Entity): The second entity in the relationship  
            context (str): The textual context containing information about the relationship
        Returns:
            Optional[str]: The inferred relationship type, or None if no relationship can be determined.
                          Possible return values include:
                          - Person-Organization: 'leads', 'works_for', 'founded', 'associated_with'
                          - Organization-Organization: 'acquired', 'partners_with', 'competes_with', 'related_to'
                          - Person-Person: 'collaborates_with', 'manages', 'knows'
                          - Location-based: 'located_in'
                          - Default: 'related_to'
        Examples:
            >>> _infer_relationship_type(person_entity, org_entity, "John is the CEO of ACME Corp")
            'leads'
            >>> _infer_relationship_type(org1_entity, org2_entity, "Microsoft acquired GitHub")
            'acquired'
            >>> _infer_relationship_type(person1_entity, person2_entity, "They work as colleagues")
            'collaborates_with'

        Note:
            The method performs case-insensitive keyword matching and prioritizes more specific
            relationships over generic ones. The relationship direction is implied by the order
            of entities (entity1 -> entity2).
        """
        context_lower = context.lower()
        
        # Person-Organization relationships
        if entity1.type == 'person' and entity2.type == 'organization':
            if any(keyword in context_lower for keyword in ['ceo', 'president', 'director', 'manager']):
                return 'leads'
            elif any(keyword in context_lower for keyword in ['employee', 'works', 'employed']):
                return 'works_for'
            elif any(keyword in context_lower for keyword in ['founded', 'founder']):
                return 'founded'
            else:
                return 'associated_with'
        
        # Organization-Organization relationships
        elif entity1.type == 'organization' and entity2.type == 'organization':
            if any(keyword in context_lower for keyword in ['acquired', 'bought', 'purchased']):
                return 'acquired'
            elif any(keyword in context_lower for keyword in ['partner', 'collaboration', 'joint']):
                return 'partners_with'
            elif any(keyword in context_lower for keyword in ['competitor', 'competes']):
                return 'competes_with'
            else:
                return 'related_to'
        
        # Person-Person relationships
        elif entity1.type == 'person' and entity2.type == 'person':
            if any(keyword in context_lower for keyword in ['colleague', 'team', 'together']):
                return 'collaborates_with'
            elif any(keyword in context_lower for keyword in ['report', 'manages', 'supervises']):
                return 'manages'
            else:
                return 'knows'
        
        # Location relationships
        elif 'location' in [entity1.type, entity2.type]:
            return 'located_in'
        
        # Default relationship
        return 'related_to'
    
    async def _extract_cross_chunk_relationships(self, 
                                               entities: List[Entity], 
                                               chunks: List[LLMChunk]) -> List[Relationship]:
        """Extract relationships between entities that span across multiple document chunks.

        This method identifies and creates relationships between entities based on their
        co-occurrence in sequential document chunks, establishing narrative connections
        that may not be explicitly stated but are implied by document structure.

        Args:
            entities (List[Entity]): List of extracted entities from the document,
                each containing source chunk information and entity metadata.
            chunks (List[LLMChunk]): List of document chunks in sequential order,
                used to determine narrative flow and proximity relationships.

        Returns:
            List[Relationship]: List of relationship objects representing cross-chunk
                connections. Each relationship includes:
                - Unique identifier and entity references
                - Relationship type ('narrative_sequence')
                - Confidence score (0.4 for narrative relationships)
                - Source chunks where both entities appear
                - Extraction metadata and sequence information

        Note:
            - Relationships are only created between different entities (entity1.id != entity2.id)
            - Confidence is set to 0.4 as these are inferred rather than explicit relationships
            - All combinations of entities within a sequence are connected (n*(n-1)/2 relationships)
            - Relationship IDs are generated using MD5 hash of entity ID pairs for consistency
        """
        relationships = []
        
        # Group entities by type for more efficient processing
        entities_by_type = {}
        for entity in entities:
            if entity.type not in entities_by_type:
                entities_by_type[entity.type] = []
            entities_by_type[entity.type].append(entity)
        
        # Find entities that appear in sequential chunks (narrative relationships)
        chunk_sequences = self._find_chunk_sequences(chunks)
        for seq in chunk_sequences:
            seq_entities = []
            for chunk_id in seq:
                chunk_entities = [e for e in entities if chunk_id in e.source_chunks]
                seq_entities.extend(chunk_entities)
            
            # Create narrative relationships
            if len(seq_entities) >= 2:
                for i, entity1 in enumerate(seq_entities):
                    for entity2 in seq_entities[i+1:]:
                        if entity1.id != entity2.id:
                            rel_id = f"rel_seq_{hashlib.md5(f'{entity1.id}_{entity2.id}'.encode()).hexdigest()[:8]}"
                            
                            relationship = Relationship(
                                id=rel_id,
                                source_entity_id=entity1.id,
                                target_entity_id=entity2.id,
                                relationship_type='narrative_sequence',
                                description=f"{entity1.name} appears in narrative sequence with {entity2.name}",
                                confidence=0.4,
                                source_chunks=list(set(entity1.source_chunks + entity2.source_chunks)),
                                properties={
                                    'extraction_method': 'narrative_sequence',
                                    'sequence_length': len(seq)
                                }
                            )
                            relationships.append(relationship)
        
        return relationships
    
    def _find_chunk_sequences(self, chunks: List[LLMChunk]) -> List[List[str]]:
        """Find sequences of related chunks based on their source page.
    
        Groups chunks that belong to the same page and returns sequences containing
        multiple chunks. Single-chunk pages are filtered out as they don't form
        meaningful sequences for processing.

        Args:
            chunks (List[LLMChunk]): List of LLM chunks to analyze for sequences.
                Each chunk must have a source_page and chunk_id attribute.

        Returns:
            List[List[str]]: List of sequences, where each sequence is a list of
                chunk IDs that belong to the same page. Only includes sequences
                with 2 or more chunks.

        Example:
            >>> chunks = [chunk1(page=1), chunk2(page=1), chunk3(page=2)]
            >>> sequences = self._find_chunk_sequences(chunks)
            >>> # Returns: [['chunk1_id', 'chunk2_id']] (page 2 filtered out)
        """
        sequences = []
        
        # Group chunks by page
        chunks_by_page = {}
        for chunk in chunks:
            page = chunk.source_page
            if page not in chunks_by_page:
                chunks_by_page[page] = []
            chunks_by_page[page].append(chunk.chunk_id)
        
        # Each page is a sequence
        for page, chunk_ids in chunks_by_page.items():
            if len(chunk_ids) > 1:
                sequences.append(chunk_ids)
        
        return sequences
    
    async def _create_networkx_graph(self, knowledge_graph: KnowledgeGraph) -> nx.DiGraph:
        """Create a NetworkX directed graph representation from a knowledge graph.

        Converts a KnowledgeGraph object into a NetworkX DiGraph where:
        - Entities become nodes with their properties as node attributes
        - Relationships become directed edges with their properties as edge attributes

        Args:
            knowledge_graph (KnowledgeGraph): The knowledge graph containing entities 
                and relationships to convert into NetworkX format.

        Returns:
            nx.DiGraph: A directed graph where:
                - Nodes represent entities with attributes: name, type, confidence, 
                  source_chunks, and any additional properties
                - Edges represent relationships with attributes: relationship_type, 
                  confidence, source_chunks, and any additional properties

        Note:
            The resulting NetworkX graph maintains all metadata from the original
            knowledge graph structure.
        """
        graph = nx.DiGraph()
        
        # Add entities as nodes
        for entity in knowledge_graph.entities:
            graph.add_node(
                entity.id,
                name=entity.name,
                type=entity.type,
                confidence=entity.confidence,
                source_chunks=entity.source_chunks,
                **entity.properties
            )
        
        # Add relationships as edges
        for relationship in knowledge_graph.relationships:
            graph.add_edge(
                relationship.source_entity_id,
                relationship.target_entity_id,
                relationship_type=relationship.relationship_type,
                confidence=relationship.confidence,
                source_chunks=relationship.source_chunks,
                **relationship.properties
            )
        
        return graph
    
    async def _merge_into_global_graph(self, knowledge_graph: KnowledgeGraph) -> None:
        """
        Merge a document-specific knowledge graph into the global knowledge graph.

        This method performs a two-phase merge operation:
        1. Merges entities from the document graph into the global entity collection,
           handling conflicts by combining source chunks and taking maximum confidence scores
        2. Composes the document's NetworkX graph structure with the global graph

        Args:
            knowledge_graph (KnowledgeGraph): The document-specific knowledge graph
                containing entities and relationships to be merged into the global graph.

        Side Effects:
            - Updates self.global_entities with new entities or merges existing ones
            - Modifies self.global_graph by composing it with the document graph
            - Deduplicates source chunks for entities that already exist globally
            - Updates entity confidence scores to reflect the maximum confidence seen

        Note:
            This is an asynchronous method that modifies the global graph state in-place.
            The merge operation preserves all nodes and edges from both graphs, with
            NetworkX handling any overlapping nodes automatically.
        """
        # Update global entities
        for entity in knowledge_graph.entities:
            if entity.id not in self.global_entities:
                self.global_entities[entity.id] = entity
            else:
                # Merge entity information
                existing = self.global_entities[entity.id]
                existing.source_chunks.extend(entity.source_chunks)
                existing.source_chunks = list(set(existing.source_chunks))
                existing.confidence = max(existing.confidence, entity.confidence)
        
        # Merge into global NetworkX graph
        doc_graph = self.document_graphs[knowledge_graph.document_id]
        self.global_graph = nx.compose(self.global_graph, doc_graph)
    
    async def _discover_cross_document_relationships(self, knowledge_graph: KnowledgeGraph):
        """Discover and establish relationships between entities across different documents.

        This method identifies entities that appear in multiple documents and creates
        cross-document relationships to connect related information. It analyzes entity
        similarity and determines whether entities represent the same concept or are
        merely similar across document boundaries.

        Args:
            knowledge_graph (KnowledgeGraph): The knowledge graph containing entities
                to analyze for cross-document relationships.

        Returns:
            None: The method updates self.cross_document_relationships in-place.

        Side Effects:
            - Extends self.cross_document_relationships with newly discovered relationships
            - Logs the number of relationships discovered

        Process:
            1. Iterates through all entities in the provided knowledge graph
            2. For each entity, finds similar entities from other documents using similarity matching
            3. Verifies that entities belong to different documents by checking source chunks
            4. Creates CrossDocumentRelationship objects with appropriate confidence scores:
               - 0.8 confidence for exact name matches (same_entity type)
               - 0.6 confidence for similar but not identical entities (similar_entity type)
            5. Includes evidence chunks from both entities to support the relationship

        Note:
            - Requires self.global_entities to be populated before execution
            - Returns early if no global entities are available
            - Assumes chunk IDs contain document information for proper cross-document detection
        """
        if not self.global_entities:
            return
        
        new_relationships = []
        
        for entity in knowledge_graph.entities:
            # Find similar entities in other documents
            similar_entities = await self._find_similar_entities(entity)
            
            for similar_entity in similar_entities:
                if similar_entity.id != entity.id:
                    # Check if they're from different documents
                    entity_docs = set()
                    similar_docs = set()
                    
                    for chunk_id in entity.source_chunks:
                        # Extract document ID from chunk (assuming chunk format includes doc info)
                        entity_docs.add(knowledge_graph.document_id)
                    
                    for chunk_id in similar_entity.source_chunks:
                        # Find document for this chunk
                        for kg in self.knowledge_graphs.values():
                            if any(c.chunk_id == chunk_id for c in kg.chunks):
                                similar_docs.add(kg.document_id)
                                break
                    
                    if entity_docs.intersection(similar_docs) == set():
                        # Different documents
                        cross_rel = CrossDocumentRelationship(
                            id=f"cross_{uuid.uuid4().hex[:8]}",
                            source_document_id=knowledge_graph.document_id,
                            target_document_id=list(similar_docs)[0] if similar_docs else 'unknown',
                            source_entity_id=entity.id,
                            target_entity_id=similar_entity.id,
                            relationship_type='same_entity' if entity.name.lower() == similar_entity.name.lower() else 'similar_entity',
                            confidence=0.8 if entity.name.lower() == similar_entity.name.lower() else 0.6,
                            evidence_chunks=entity.source_chunks + similar_entity.source_chunks
                        )
                        new_relationships.append(cross_rel)
        
        self.cross_document_relationships.extend(new_relationships)
        logger.info(f"Discovered {len(new_relationships)} cross-document relationships")
    
    async def _find_similar_entities(self, entity: Entity) -> List[Entity]:
        """Find entities similar to the given entity across all documents in the graph.

        This method searches through all global entities to identify those that are similar
        to the input entity based on name similarity and type matching. Entities are considered
        similar if they have the same type and their names exceed the configured similarity
        threshold.

        Args:
            entity (Entity): The reference entity to find similar matches for. Must have
                            'id', 'name', and 'type' attributes.

        Returns:
            List[Entity]: A list of entities that are similar to the input entity.
                         The list excludes the input entity itself and only includes
                         entities of the same type whose names have similarity scores
                         above the threshold.

        Note:
            - Uses the instance's similarity_threshold for determining matches
            - Relies on _calculate_text_similarity() for name comparison
            - Only considers entities with exact type matches
            - The input entity is automatically excluded from results
        """
        similar_entities = []
        
        for other_entity in self.global_entities.values():
            if other_entity.id == entity.id:
                continue
            
            # Name similarity
            name_similarity = self._calculate_text_similarity(entity.name, other_entity.name)
            
            # Type must match
            if entity.type == other_entity.type and name_similarity > self.similarity_threshold:
                similar_entities.append(other_entity)
        
        return similar_entities
    
    def _calculate_text_similarity(self, text1: str, text2: str) -> float:
        """Calculate the Jaccard similarity coefficient between two text strings.

        This method implements the Jaccard similarity algorithm, which measures
        similarity between two sets of words by calculating the ratio of their
        intersection to their union. The similarity score ranges from 0.0 (no
        common words) to 1.0 (identical word sets).
        The method performs case-insensitive comparison and treats each unique
        word as a single element in the set, regardless of word frequency.

        Args:
            text1 (str): The first text string to compare.
            text2 (str): The second text string to compare.
        Returns:
            float: The Jaccard similarity coefficient between 0.0 and 1.0, where:
                - 0.0 indicates no common words between the texts
                - 1.0 indicates identical word sets (after normalization)
                - Values closer to 1.0 indicate higher similarity
        Note:
            This is a simple implementation that:
            - Converts text to lowercase for case-insensitive comparison
            - Splits text on whitespace only (no advanced tokenization)
            - Treats punctuation as part of words
            - Does not account for word frequency or semantic meaning

        Example:
            >>> similarity = self._calculate_text_similarity("hello world", "world hello")
            >>> # Returns 1.0 (identical word sets)
            >>> similarity = self._calculate_text_similarity("hello world", "hello universe")
            >>> # Returns 0.33 (1 common word out of 3 total unique words)
        """
        # Simple Jaccard similarity
        words1 = set(text1.lower().split())
        words2 = set(text2.lower().split())
        
        intersection = words1.intersection(words2)
        union = words1.union(words2)
        
        if not union:
            return 0.0
        
        return len(intersection) / len(union)
    
    async def _store_knowledge_graph_ipld(self, knowledge_graph: KnowledgeGraph) -> str:
        """Store a knowledge graph in IPLD (InterPlanetary Linked Data) format.

        This method serializes a KnowledgeGraph object into a JSON-compatible format,
        handles numpy array conversion for embeddings, and stores the data in IPLD
        using the configured storage backend.

        Args:
            knowledge_graph (KnowledgeGraph): The knowledge graph object containing
                entities, relationships, chunks, and metadata to be stored.

        Returns:
            str: The Content Identifier (CID) of the stored knowledge graph in IPLD.
                 Returns an empty string if storage fails.

        Note:
            - Errors during storage are logged and result in an empty string return

        Raises:
            Exception: Catches and logs any storage-related exceptions, returning
                      empty string instead of propagating the error.
        """
        # Convert to serializable format
        kg_data = {
            'graph_id': knowledge_graph.graph_id,
            'document_id': knowledge_graph.document_id,
            'entities': [asdict(entity) for entity in knowledge_graph.entities],
            'relationships': [asdict(rel) for rel in knowledge_graph.relationships],
            'chunks': [asdict(chunk) for chunk in knowledge_graph.chunks],
            'metadata': knowledge_graph.metadata,
            'creation_timestamp': knowledge_graph.creation_timestamp
        }
        
        # Remove numpy arrays from entities for JSON serialization
        for entity_data in kg_data['entities']:
            if 'embedding' in entity_data and entity_data['embedding'] is not None:
                entity_data['embedding'] = entity_data['embedding'].tolist()
        
        # Remove numpy arrays from chunks
        for chunk_data in kg_data['chunks']:
            if 'embedding' in chunk_data and chunk_data['embedding'] is not None:
                chunk_data['embedding'] = chunk_data['embedding'].tolist()
        
        try:
            # Store in IPLD
            cid = await self.storage.store_json(kg_data)
            logger.info(f"Stored knowledge graph in IPLD: {cid}")
            return cid
        except Exception as e:
            logger.error(f"Failed to store knowledge graph in IPLD: {e}")
            return ""
    
    async def query_graph(self, 
                         query: str, 
                         graph_id: Optional[str] = None,
                         max_results: int = 10) -> Dict[str, Any]:
        """Query the knowledge graph using natural language to retrieve relevant entities and relationships.

        This method performs a keyword-based search across the knowledge graph(s) to find entities
        that match the given query. It searches entity names, types, and descriptions, scoring
        matches based on relevance. Related relationships are also retrieved for the matching entities.

        Args:
            query (str): Natural language query string to search for in the knowledge graph.
                The search is case-insensitive and matches against entity names, types, and descriptions.
            graph_id (Optional[str], optional): Specific knowledge graph identifier to query.
                If None, searches across the global merged graph containing all entities and relationships.
                Defaults to None.
            max_results (int, optional): Maximum number of top-scoring entities to return.
                Results are ranked by relevance score and limited to this number. Defaults to 10.

        Returns:
            Dict[str, Any]: A dictionary containing query results with the following structure:
                - 'query' (str): The original query string
                - 'entities' (List[Dict]): List of matching entities serialized as dictionaries,
                    ordered by relevance score (highest first)
                - 'relationships' (List[Dict]): List of relationships connected to the matching entities,
                    serialized as dictionaries
                - 'total_matches' (int): Total number of entities that matched the query before limiting
                - 'timestamp' (str): ISO format timestamp of when the query was executed

        Example:
            >>> results = await integrator.query_graph("financial transactions", max_results=5)
            >>> print(f"Found {results['total_matches']} matches")
            >>> for entity in results['entities']:
            ...     print(f"- {entity['name']} ({entity['type']})")
        """
        if graph_id and graph_id in self.knowledge_graphs:
            kg = self.knowledge_graphs[graph_id]
            entities = kg.entities
            relationships = kg.relationships
        else:
            # Query global graph
            entities = list(self.global_entities.values())
            relationships = []
            for kg in self.knowledge_graphs.values():
                relationships.extend(kg.relationships)
        
        # Simple keyword-based search (can be enhanced with semantic search)
        query_lower = query.lower()
        matching_entities = []
        
        for entity in entities:
            score = 0
            
            # Name match
            if query_lower in entity.name.lower():
                score += 2
            
            # Type match
            if query_lower in entity.type.lower():
                score += 1
            
            # Description match
            if query_lower in entity.description.lower():
                score += 1
            
            if score > 0:
                matching_entities.append((entity, score))
        
        # Sort by score and limit results
        matching_entities.sort(key=lambda x: x[1], reverse=True)
        top_entities = [entity for entity, score in matching_entities[:max_results]]
        
        # Find related relationships
        entity_ids = {entity.id for entity in top_entities}
        related_relationships = [
            rel for rel in relationships
            if rel.source_entity_id in entity_ids or rel.target_entity_id in entity_ids
        ]
        
        return {
            'query': query,
            'entities': [asdict(entity) for entity in top_entities],
            'relationships': [asdict(rel) for rel in related_relationships],
            'total_matches': len(matching_entities),
            'timestamp': datetime.utcnow().isoformat()
        }
    
    async def get_entity_neighborhood(self, 
                                    entity_id: str, 
                                    depth: int = 2) -> Dict[str, Any]:
        """Get the neighborhood of an entity in the graph within a specified depth.

        This method extracts a subgraph centered around a given entity, including all nodes
        and edges within the specified depth from the center entity. The method performs
        breadth-first traversal to collect neighboring nodes at each depth level.

        Args:
            entity_id (str): The unique identifier of the center entity to analyze.
            depth (int, optional): The maximum depth to traverse from the center entity.
                Defaults to 2. A depth of 1 includes only direct neighbors, depth of 2
                includes neighbors of neighbors, etc.

        Returns:
            Dict[str, Any]: A dictionary containing the neighborhood analysis results:
                - center_entity_id (str): The ID of the center entity
                - depth (int): The depth used for traversal
                - nodes (List[Dict]): List of node data dictionaries, each containing
                    node attributes plus an 'id' field
                - edges (List[Dict]): List of edge data dictionaries, each containing
                    edge attributes plus 'source' and 'target' fields
                - node_count (int): Total number of nodes in the subgraph
                - edge_count (int): Total number of edges in the subgraph
                If the entity is not found, returns:
                - error (str): Error message indicating the issue

        Raises:
            None: This method handles errors gracefully by returning error dictionaries.

        Note:
            - The method considers both incoming and outgoing edges (predecessors and successors)
            - The returned subgraph includes all nodes within the specified depth, not just
                those at exactly that depth
            - All data is converted to serializable format for easy JSON export
        """
        if entity_id not in self.global_entities:
            return {'error': 'Entity not found'}
        
        # Use global graph for neighborhood analysis
        if entity_id not in self.global_graph:
            return {'error': 'Entity not in graph'}
        
        # Get subgraph within specified depth
        subgraph_nodes = set([entity_id])
        
        for d in range(depth):
            new_nodes = set()
            for node in subgraph_nodes:
                # Add neighbors
                new_nodes.update(self.global_graph.neighbors(node))
                new_nodes.update(self.global_graph.predecessors(node))
            subgraph_nodes.update(new_nodes)
        
        # Extract subgraph
        subgraph = self.global_graph.subgraph(subgraph_nodes)
        
        # Convert to serializable format
        nodes_data = []
        for node in subgraph.nodes():
            node_data = dict(subgraph.nodes[node])
            node_data['id'] = node
            nodes_data.append(node_data)
        
        edges_data = []
        for source, target in subgraph.edges():
            edge_data = dict(subgraph.edges[source, target])
            edge_data['source'] = source
            edge_data['target'] = target
            edges_data.append(edge_data)
        
        return {
            'center_entity_id': entity_id,
            'depth': depth,
            'nodes': nodes_data,
            'edges': edges_data,
            'node_count': len(nodes_data),
            'edge_count': len(edges_data)
        }

