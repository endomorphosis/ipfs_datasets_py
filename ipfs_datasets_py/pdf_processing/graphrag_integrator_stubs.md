# Function and Class stubs from '/ipfs_datasets_py/ipfs_datasets_py/pdf_processing/graphrag_integrator.py'

Stub file last updated: 2025-08-30 05:37:03

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
* **Async:** False
* **Method:** False
* **Class:** N/A

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
* **Async:** False
* **Method:** False
* **Class:** N/A

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

    Examples:
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
* **Async:** False
* **Method:** False
* **Class:** N/A

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
* **Async:** False
* **Method:** False
* **Class:** N/A

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
* **Async:** False
* **Method:** False
* **Class:** N/A

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

## get_entity_neighborhood

```python
async def get_entity_neighborhood(self, 
                                entity_id: str, 
                                depth: int = 2) -> Dict[str, Any]:
"""Get the neighborhood of an entity in the graph within a specified depth.

This method extracts a subgraph centered around a given entity, including all nodes
and edges within the specified depth from the center entity. The method performs
breadth-first traversal to collect neighboring nodes at each depth level, considering
both incoming and outgoing relationships.

Args:
    entity_id (str): The unique identifier of the center entity to analyze.
    Must be a valid entity ID that exists in the global entity registry.
    depth (int, optional): The maximum depth to traverse from the center entity.
    Defaults to 2. Must be a non-negative integer where:
    - depth=0: Only the center entity
    - depth=1: Center entity and direct neighbors
    - depth=2: Center entity, direct neighbors, and their neighbors
    - etc.

Returns:
    Dict[str, Any]: A dictionary containing the neighborhood analysis results:
    Success case:
    - 'center_entity_id' (str): The ID of the center entity
    - 'depth' (int): The depth used for traversal
    - 'nodes' (List[Dict]): List of node data dictionaries, each containing
        all node attributes plus an 'id' field
    - 'edges' (List[Dict]): List of edge data dictionaries, each containing
        all edge attributes plus 'source' and 'target' fields
    - 'node_count' (int): Total number of nodes in the subgraph
    - 'edge_count' (int): Total number of edges in the subgraph
    
    Error cases:
    - {'error': 'Entity not found'}: If entity_id is not in global_entities
    - {'error': 'Entity not in graph'}: If entity_id is not in global_graph

Raises:
    TypeError: If entity_id is not a string or depth is not an integer.
    ValueError: If entity_id is empty or depth is negative.

Examples:
    >>> neighborhood = await integrator.get_entity_neighborhood("entity_123", depth=1)
    >>> print(f"Found {neighborhood['node_count']} nodes and {neighborhood['edge_count']} edges")
    
    >>> # Get deeper neighborhood
    >>> deep_neighborhood = await integrator.get_entity_neighborhood("entity_123", depth=3)
    >>> print(f"3-depth neighborhood has {deep_neighborhood['node_count']} nodes")

Note:
    - Uses the global graph (self.global_graph) for comprehensive analysis
    - Considers both incoming (predecessors) and outgoing (successors) edges
    - The returned subgraph includes all nodes within the specified depth, not just
        those at exactly that depth
    - All data is converted to serializable format for JSON compatibility
    - Performance scales with graph size and depth - use smaller depths for large graphs
"""
```
* **Async:** True
* **Method:** True
* **Class:** GraphRAGIntegrator

## integrate_document

```python
async def integrate_document(self, llm_document: LLMDocument) -> KnowledgeGraph:
"""Integrate an LLM-optimized document into the GraphRAG system.

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
"""Query the knowledge graph using natural language to retrieve relevant entities and relationships.

This method performs intelligent search across the knowledge graph(s) to find entities
that match the given query. It uses both keyword-based matching and entity extraction
to identify relevant entities and their relationships. The search algorithm scores
matches based on name similarity, type matching, and description relevance.

Args:
    query (str): Natural language query string to search for in the knowledge graph.
        The search is case-insensitive and matches against entity names, types, and descriptions.
        Can include entity names like "John Smith" or concepts like "artificial intelligence companies".
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
    - 'extracted_entities' (List[str]): Entity names extracted from the query using NLP
    - 'timestamp' (str): ISO format timestamp of when the query was executed

Raises:
    TypeError: If query is not a string or max_results is not an integer.
    ValueError: If query is empty/whitespace-only or max_results is less than or equal to 0.
    KeyError: If graph_id is provided but does not exist in the knowledge graphs.

Example:
    >>> results = await integrator.query_graph("companies founded by John Smith", max_results=5)
    >>> print(f"Found {results['total_matches']} matches")
    >>> print(f"Extracted entities: {results['extracted_entities']}")
    >>> for entity in results['entities']:
    ...     print(f"- {entity['name']} ({entity['type']}) - Score: {entity.get('_score', 0)}")

Note:
    - Uses NLP-based entity extraction to identify potential entity names in the query
    - Scoring system: exact name matches (score +3), entity name in query (+2), 
        type matches (+1), description matches (+1)
    - Related relationships are automatically included for all matching entities
    - Empty queries return empty results rather than all entities
"""
```
* **Async:** True
* **Method:** True
* **Class:** GraphRAGIntegrator
