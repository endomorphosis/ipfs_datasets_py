# Function and Class stubs from '/home/kylerose1946/ipfs_datasets_py/ipfs_datasets_py/pdf_processing/graphrag_integrator.py'

## CrossDocumentRelationship

```python
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
```
## Entity

```python
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
```
## GraphRAGIntegrator

```python
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
```
## KnowledgeGraph

```python
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
```
## Relationship

```python
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
```
## __init__

```python
def __init__(self, storage: Optional[IPLDStorage] = None, similarity_threshold: float = 0.8, entity_extraction_confidence: float = 0.6):
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
```
* **Async:** False
* **Method:** True
* **Class:** GraphRAGIntegrator

## _calculate_text_similarity

```python
def _calculate_text_similarity(self, text1: str, text2: str) -> float:
    """
    Calculate the Jaccard similarity coefficient between two text strings.

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
```
* **Async:** False
* **Method:** True
* **Class:** GraphRAGIntegrator

## _create_networkx_graph

```python
async def _create_networkx_graph(self, knowledge_graph: KnowledgeGraph) -> nx.DiGraph:
    """
    Create a NetworkX directed graph representation from a knowledge graph.

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
```
* **Async:** True
* **Method:** True
* **Class:** GraphRAGIntegrator

## _discover_cross_document_relationships

```python
async def _discover_cross_document_relationships(self, knowledge_graph: KnowledgeGraph):
    """
    Discover and establish relationships between entities across different documents.

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
```
* **Async:** True
* **Method:** True
* **Class:** GraphRAGIntegrator

## _extract_chunk_relationships

```python
async def _extract_chunk_relationships(self, entities: List[Entity], chunk: LLMChunk) -> List[Relationship]:
    """
    Extract relationships between entities found within a single text chunk.

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
```
* **Async:** True
* **Method:** True
* **Class:** GraphRAGIntegrator

## _extract_cross_chunk_relationships

```python
async def _extract_cross_chunk_relationships(self, entities: List[Entity], chunks: List[LLMChunk]) -> List[Relationship]:
    """
    Extract relationships between entities that span across multiple document chunks.

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
```
* **Async:** True
* **Method:** True
* **Class:** GraphRAGIntegrator

## _extract_entities_from_chunks

```python
async def _extract_entities_from_chunks(self, chunks: List[LLMChunk]) -> List[Entity]:
    """
    Extract and consolidate entities from a list of LLM chunks.

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
```
* **Async:** True
* **Method:** True
* **Class:** GraphRAGIntegrator

## _extract_entities_from_text

```python
async def _extract_entities_from_text(self, text: str, chunk_id: str) -> List[Dict[str, Any]]:
    """
    Extract named entities from a text chunk using pattern matching.

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
```
* **Async:** True
* **Method:** True
* **Class:** GraphRAGIntegrator

## _extract_relationships

```python
async def _extract_relationships(self, entities: List[Entity], chunks: List[LLMChunk]) -> List[Relationship]:
    """
    Extract relationships between entities from text chunks.

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
```
* **Async:** True
* **Method:** True
* **Class:** GraphRAGIntegrator

## _find_chunk_sequences

```python
def _find_chunk_sequences(self, chunks: List[LLMChunk]) -> List[List[str]]:
    """
    Find sequences of related chunks based on their source page.

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
```
* **Async:** False
* **Method:** True
* **Class:** GraphRAGIntegrator

## _find_similar_entities

```python
async def _find_similar_entities(self, entity: Entity) -> List[Entity]:
    """
    Find entities similar to the given entity across all documents in the graph.

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
```
* **Async:** True
* **Method:** True
* **Class:** GraphRAGIntegrator

## _infer_relationship_type

```python
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

    Raises:
        TypeError: If entity1 or entity2 is not an Entity instance
        ValueError: If context is empty or contains only whitespace
        AttributeError: If entities lack required type attribute

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
```
* **Async:** False
* **Method:** True
* **Class:** GraphRAGIntegrator

## _merge_into_global_graph

```python
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
```
* **Async:** True
* **Method:** True
* **Class:** GraphRAGIntegrator

## _store_knowledge_graph_ipld

```python
async def _store_knowledge_graph_ipld(self, knowledge_graph: KnowledgeGraph) -> str:
    """
    Store a knowledge graph in IPLD (InterPlanetary Linked Data) format.

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
```
* **Async:** True
* **Method:** True
* **Class:** GraphRAGIntegrator

## get_entity_neighborhood

```python
async def get_entity_neighborhood(self, entity_id: str, depth: int = 2) -> Dict[str, Any]:
    """
    Get the neighborhood of an entity in the graph within a specified depth.

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
```
* **Async:** True
* **Method:** True
* **Class:** GraphRAGIntegrator

## integrate_document

```python
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
```
* **Async:** True
* **Method:** True
* **Class:** GraphRAGIntegrator

## query_graph

```python
async def query_graph(self, query: str, graph_id: Optional[str] = None, max_results: int = 10) -> Dict[str, Any]:
    """
    Query the knowledge graph using natural language to retrieve relevant entities and relationships.

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
```
* **Async:** True
* **Method:** True
* **Class:** GraphRAGIntegrator
