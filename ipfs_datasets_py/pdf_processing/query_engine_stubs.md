# Function and Class stubs from '/home/kylerose1946/ipfs_datasets_py/ipfs_datasets_py/pdf_processing/query_engine.py'

Files last updated: 1751977888.5166698

Stub file last updated: 2025-07-08 05:37:03

## QueryEngine

```python
class QueryEngine:
    """
    Advanced Query Engine for PDF Knowledge Base Processing and Retrieval

The QueryEngine class provides comprehensive natural language querying capabilities
over processed PDF content stored in GraphRAG knowledge structures. It supports
multiple query types including entity search, relationship analysis, semantic search,
document-level queries, cross-document analysis, and graph traversal operations.
This class serves as the primary interface for accessing and exploring PDF-derived
knowledge graphs, offering both precise keyword matching and semantic understanding.

Args:
    graphrag_integrator (GraphRAGIntegrator): GraphRAG integration system for accessing
        knowledge graphs, entities, relationships, and document structures.
    storage (Optional[IPLDStorage], optional): IPLD storage instance for persistent
        data access and caching. Defaults to a new IPLDStorage instance if not provided.
    embedding_model (str, optional): Name/path of the sentence transformer model for
        semantic search operations. Defaults to "sentence-transformers/all-MiniLM-L6-v2".
        Must be compatible with sentence-transformers library.

Key Features:
- Multi-type query processing (entity, relationship, semantic, document, cross-document, graph traversal)
- Natural language query understanding with automatic type detection
- Semantic search using sentence transformer embeddings
- Cross-document relationship discovery and analysis
- Graph path finding and traversal operations
- Query result caching and performance optimization
- Intelligent query suggestions based on results
- Comprehensive analytics and monitoring capabilities

Attributes:
    graphrag (GraphRAGIntegrator): GraphRAG integration system for knowledge access
    storage (IPLDStorage): IPLD storage for persistent data operations
    embedding_model (SentenceTransformer): Sentence transformer model for semantic search
    query_processors (Dict[str, callable]): Mapping of query types to processing functions
    embedding_cache (Dict[str, Any]): Cache for embedding computations
    query_cache (Dict[str, QueryResponse]): Cache for frequent query responses

Public Methods:
    query(query_text: str, query_type: Optional[str] = None, filters: Optional[Dict[str, Any]] = None, max_results: int = 20) -> QueryResponse:
        Process a natural language query and return structured results.
        Supports automatic query type detection, filtering, result limiting,
        and comprehensive response metadata.
    get_query_analytics() -> Dict[str, Any]:
        Retrieve analytics about query patterns, performance metrics, and cache utilization.
        Provides insights into query distribution, processing times, and system usage.

Private Methods:
    _normalize_query(query: str) -> str:
        Normalize query text by lowercasing, whitespace cleanup, and stop word removal.
    _detect_query_type(query: str) -> str:
        Auto-detect query type based on keyword patterns and linguistic cues.
    _process_entity_query(query: str, filters: Optional[Dict[str, Any]], max_results: int) -> List[QueryResult]:
        Process entity-focused queries using name matching and type filtering.
    _process_relationship_query(query: str, filters: Optional[Dict[str, Any]], max_results: int) -> List[QueryResult]:
        Process relationship-focused queries with entity and type matching.
    _process_semantic_query(query: str, filters: Optional[Dict[str, Any]], max_results: int) -> List[QueryResult]:
        Process semantic search queries using embedding similarity.
    _process_document_query(query: str, filters: Optional[Dict[str, Any]], max_results: int) -> List[QueryResult]:
        Process document-level queries with title, entity, and content matching.
    _process_cross_document_query(query: str, filters: Optional[Dict[str, Any]], max_results: int) -> List[QueryResult]:
        Process cross-document relationship analysis queries.
    _process_graph_traversal_query(query: str, filters: Optional[Dict[str, Any]], max_results: int) -> List[QueryResult]:
        Process graph path-finding and traversal queries using NetworkX.
    _extract_entity_names_from_query(query: str) -> List[str]:
        Extract potential entity names from query text using capitalization patterns.
    _get_entity_documents(entity: Entity) -> List[str]:
        Retrieve document IDs where a specific entity appears.
    _get_relationship_documents(relationship: Relationship) -> List[str]:
        Retrieve document IDs where a specific relationship appears.
    _generate_query_suggestions(query: str, results: List[QueryResult]) -> List[str]:
        Generate intelligent follow-up query suggestions based on result content.

Usage Example:
    # Initialize query engine
    engine = QueryEngine(
        graphrag_integrator=my_graphrag,
        storage=my_storage,
        embedding_model="sentence-transformers/all-MiniLM-L6-v2"
    )
    
    # Execute natural language query
    response = await engine.query(
        "Who are the founders of technology companies?",
        filters={"entity_type": "Person"},
        max_results=10
    )
    
    # Access results and suggestions
    for result in response.results:
        print(f"{result.content} (score: {result.relevance_score})")
    
    # Get system analytics
    analytics = await engine.get_query_analytics()
    print(f"Total queries: {analytics['total_queries']}")

Notes:
    - Query type auto-detection uses keyword patterns and can be overridden manually
    - Semantic search requires successful loading of the embedding model
    - Cross-document queries depend on pre-computed cross-document relationships
    - Graph traversal uses NetworkX shortest path algorithms
    - Result caching improves performance for repeated queries
    - All async methods support concurrent execution for better performance
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## QueryResponse

```python
@dataclass
class QueryResponse:
    """
    Complete query response containing results and execution metadata.

Represents the full response from a query operation against the PDF knowledge base,
including all matched results, execution analytics, query suggestions, and comprehensive
metadata for monitoring, debugging, and user experience enhancement. This class serves
as the primary interface between the query engine and consuming applications.

Args:
    query (str): Original query text as submitted by the user.
        Preserved exactly as received for reference and logging.
    query_type (str): Detected or specified query type.
        Values: 'entity_search', 'relationship_search', 'semantic_search',
        'document_search', 'cross_document', 'graph_traversal'.
    results (List[QueryResult]): Ordered list of query results.
        Sorted by relevance score in descending order.
        May be empty if no matches found.
    total_results (int): Total number of results returned.
        Equal to len(results), provided for convenience.
    processing_time (float): Query execution time in seconds.
        Measured from query start to response completion.
        Useful for performance monitoring and optimization.
    suggestions (List[str]): Generated follow-up query suggestions.
        Based on result content and query patterns.
        Limited to 5 suggestions maximum.
    metadata (Dict[str, Any]): Query execution metadata and context.
        Includes normalized_query, filters_applied, timestamp, and
        other execution context information.

Attributes:
    query (str): Original user query string
    query_type (str): Classified query type
    results (List[QueryResult]): Matched and ranked results
    total_results (int): Count of returned results
    processing_time (float): Execution duration in seconds
    suggestions (List[str]): Generated query suggestions
    metadata (Dict[str, Any]): Execution context and metadata

Usage Example:
    response = QueryResponse(
        query="Who founded Microsoft?",
        query_type="entity_search",
        results=[entity_result1, entity_result2],
        total_results=2,
        processing_time=0.15,
        suggestions=["What is Microsoft?", "Microsoft founders relationships"],
        metadata={
            "normalized_query": "who founded microsoft",
            "filters_applied": {},
            "timestamp": "2025-07-08T12:00:00Z"
        }
    )

Notes:
    - Processing time includes query normalization, processing, and result formatting
    - Suggestions are generated based on result content and common query patterns
    - Metadata provides transparency into query processing for debugging
    - Results are always ordered by relevance score (highest first)
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## QueryResult

```python
@dataclass
class QueryResult:
    """
    Single query result item from the PDF knowledge base query engine.

Represents an individual result returned from querying the PDF knowledge base,
containing all necessary information to identify, display, and trace back to
the source content. Each result includes relevance scoring, source attribution,
and rich metadata for advanced processing and visualization.

Args:
    id (str): Unique identifier for the result item.
        Format varies by type (entity_id, chunk_id, document_id, relationship_id).
    type (str): Type of result content.
        Valid values: 'entity', 'relationship', 'chunk', 'document', 
        'cross_document_relationship', 'graph_path'.
    content (str): Main textual content of the result.
        For entities: name, type, and description.
        For relationships: formatted relationship statement.
        For chunks: text content (may be truncated).
        For documents: summary information.
    relevance_score (float): Normalized relevance score between 0.0 and 1.0.
        Higher values indicate greater relevance to the query.
        Calculated using different algorithms per result type.
    source_document (str): Document identifier(s) where result originated.
        Single document ID for single-document results.
        'multiple' for cross-document results.
        'unknown' if source cannot be determined.
    source_chunks (List[str]): List of chunk identifiers containing the result.
        Empty list for synthetic results like graph paths.
        Multiple chunks for entities/relationships spanning chunks.
    metadata (Dict[str, Any]): Additional structured information about the result.
        Content varies by result type, may include entity properties,
        relationship details, document statistics, path information, etc.

Attributes:
    id (str): Unique result identifier
    type (str): Result content type classification
    content (str): Primary textual result content
    relevance_score (float): Query relevance score (0.0-1.0)
    source_document (str): Source document attribution
    source_chunks (List[str]): Source chunk identifiers
    metadata (Dict[str, Any]): Type-specific additional information

Usage Example:
    result = QueryResult(
        id="entity_12345",
        type="entity",
        content="John Smith (Person): CEO of ACME Corporation",
        relevance_score=0.85,
        source_document="doc_001",
        source_chunks=["chunk_001", "chunk_003"],
        metadata={
            "entity_name": "John Smith",
            "entity_type": "Person",
            "confidence": 0.9,
            "properties": {"role": "CEO", "company": "ACME Corporation"}
        }
    )

Notes:
    - Relevance scores are normalized across different query types for consistency
    - Metadata structure varies significantly by result type
    - Source attribution enables traceability back to original content
    - Results support both single-document and cross-document scenarios
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## SemanticSearchResult

```python
@dataclass
class SemanticSearchResult:
    """
    Result from semantic search operations on PDF document chunks.

Represents a semantically matched chunk from the PDF knowledge base, containing
the original content, similarity scores, source attribution, and related entity
information. Used specifically for semantic search queries that leverage embedding
models to find conceptually similar content rather than exact keyword matches.

Args:
    chunk_id (str): Unique identifier for the document chunk.
        Format: typically "doc_id_chunk_number" or similar pattern.
    content (str): Full textual content of the matched chunk.
        May include multiple sentences or paragraphs from the original document.
    similarity_score (float): Cosine similarity score between 0.0 and 1.0.
        Calculated between query embedding and chunk embedding.
        Higher values indicate greater semantic similarity.
    document_id (str): Identifier of the source document.
        Links back to the original PDF document.
    page_number (int): Page number in the source document where chunk appears.
        1-indexed page numbering following PDF conventions.
    semantic_types (str): Classification of the chunk's semantic content.
        Values may include: 'paragraph', 'heading', 'list', 'table', 'figure_caption',
        'abstract', 'conclusion', 'methodology', etc.
    related_entities (List[str]): Names of entities extracted from this chunk.
        Provides context about people, organizations, locations, and concepts
        mentioned in the semantically matched content.

Attributes:
    chunk_id (str): Unique chunk identifier
    content (str): Full chunk text content
    similarity_score (float): Semantic similarity score (0.0-1.0)
    document_id (str): Source document identifier
    page_number (int): Source page number (1-indexed)
    semantic_types (str): Content type classification
    related_entities (List[str]): Entity names found in chunk

Usage Example:
    result = SemanticSearchResult(
        chunk_id="doc_001_chunk_042",
        content="The company was founded in 1975 by Bill Gates and Paul Allen...",
        similarity_score=0.87,
        document_id="doc_001",
        page_number=3,
        semantic_types={"paragraph"},
        related_entities=["Bill Gates", "Paul Allen", "Microsoft"]
    )

Notes:
    - Similarity scores use cosine similarity between sentence transformer embeddings
    - Semantic types help categorize the nature of matched content
    - Related entities provide additional context for understanding results
    - Page numbers help users locate content in original documents
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## __init__

```python
def __init__(self, graphrag_integrator: GraphRAGIntegrator, storage: Optional[IPLDStorage] = None, embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"):
    """
    Initialize the QueryEngine with GraphRAG integration and semantic search capabilities.

Sets up the query processing system by configuring GraphRAG integration, IPLD storage,
embedding models for semantic search, query processors for different query types,
and caching systems for performance optimization. The initialization process includes
loading the sentence transformer model and establishing query processing pipelines.

Args:
    graphrag_integrator (GraphRAGIntegrator): GraphRAG integration system providing
        access to knowledge graphs, entities, relationships, and document structures.
        Must be properly initialized with processed documents.
    storage (Optional[IPLDStorage], optional): IPLD storage instance for persistent
        data operations and result caching. Defaults to a new IPLDStorage instance
        if not provided. Used for storing query results and embeddings.
    embedding_model (str, optional): Name or path of the sentence transformer model
        for semantic search operations. Defaults to "sentence-transformers/all-MiniLM-L6-v2".
        Must be compatible with the sentence-transformers library.

Attributes initialized:
    graphrag (GraphRAGIntegrator): GraphRAG integration system for knowledge access.
    storage (IPLDStorage): IPLD storage for persistent operations and caching.
    embedding_model (SentenceTransformer): Loaded sentence transformer model for
        semantic search. Set to None if model loading fails.
    query_processors (Dict[str, callable]): Dictionary mapping query type strings to
        their corresponding processing functions. Includes entity_search, relationship_search,
        semantic_search, document_search, cross_document, and graph_traversal.
    embedding_cache (Dict[str, Any]): Cache for storing computed embeddings to avoid
        redundant calculations during repeated queries.
    query_cache (Dict[str, QueryResponse]): Cache for storing complete query responses
        to improve performance for repeated queries.

Raises:
    ImportError: If sentence-transformers library is not available.
    RuntimeError: If GraphRAG integrator is not properly initialized.
    ValueError: If embedding_model name is invalid or incompatible.

Examples:
    >>> # Basic initialization
    >>> engine = QueryEngine(my_graphrag_integrator)
    
    >>> # With custom storage and embedding model
    >>> engine = QueryEngine(
    ...     graphrag_integrator=my_graphrag,
    ...     storage=my_ipld_storage,
    ...     embedding_model="sentence-transformers/paraphrase-MiniLM-L6-v2"
    ... )

Notes:
    - Embedding model loading is attempted during initialization; failures are logged but don't prevent operation
    - Query processors are registered for all supported query types during initialization
    - Caches are initialized as empty dictionaries and populated during operation
    - IPLD storage is created with default settings if not provided
    """
```
* **Async:** False
* **Method:** True
* **Class:** QueryEngine

## _detect_query_type

```python
def _detect_query_type(self, query: str) -> str:
    """
    Auto-detect query type based on linguistic patterns and keyword analysis.

This method analyzes the normalized query text to automatically classify the
user's intent and determine the most appropriate query processing approach.
It uses pattern matching against common query structures and keywords to
identify whether the user is seeking entities, relationships, documents,
or other types of information.

Args:
    query (str): Normalized query string (lowercased, stop words removed).
        Should be output from _normalize_query for consistent detection.

Returns:
    str: Detected query type string for routing to appropriate processor.
        Possible values:
        - 'entity_search': Questions about specific entities (who, what, person, organization)
        - 'relationship_search': Questions about connections (relationship, related, works for)
        - 'cross_document': Multi-document analysis (across documents, compare, multiple)
        - 'graph_traversal': Path-finding queries (path, connected through, how are)
        - 'document_search': Document-level queries (document, paper, article, file)
        - 'semantic_search': Default fallback for conceptual queries

Raises:
    TypeError: If query is not a string.
    ValueError: If query is empty after normalization.

Examples:
    >>> _detect_query_type("who is bill gates")
    'entity_search'
    >>> _detect_query_type("relationship microsoft apple")
    'relationship_search'
    >>> _detect_query_type("compare different documents")
    'cross_document'
    >>> _detect_query_type("path john smith microsoft")
    'graph_traversal'
    >>> _detect_query_type("machine learning applications")
    'semantic_search'

Notes:
    - Detection is based on keyword presence, not semantic understanding
    - Order of pattern checking determines priority when multiple patterns match
    - Defaults to semantic_search for ambiguous or unrecognized patterns
    - Keywords are checked using substring matching for flexibility
    - Detection accuracy improves with well-formed natural language queries
    """
```
* **Async:** False
* **Method:** True
* **Class:** QueryEngine

## _extract_entity_names_from_query

```python
def _extract_entity_names_from_query(self, query: str) -> List[str]:
    """
    Extract potential entity names from query text using capitalization patterns.

This method identifies likely entity names within query text by detecting
sequences of capitalized words, which typically indicate proper nouns such
as person names, organization names, locations, and other named entities.
It uses simple heuristics based on capitalization patterns commonly found
in entity references.

Args:
    query (str): Query string that may contain entity names.
        Can be normalized or raw query text. Capitalization is required
        for entity detection.

Returns:
    List[str]: List of potential entity names extracted from the query.
        Each name is a space-separated sequence of capitalized words.
        Returns empty list if no capitalized sequences are found.
        Names are returned in order of appearance in the query.

Raises:
    TypeError: If query is not a string.
    ValueError: If query is empty or contains only whitespace.

Examples:
    >>> _extract_entity_names_from_query("Who is Bill Gates?")
    ['Bill Gates']
    >>> _extract_entity_names_from_query("Microsoft and Apple are competitors")
    ['Microsoft', 'Apple']
    >>> _extract_entity_names_from_query("path from John Smith to Mary Johnson")
    ['John Smith', 'Mary Johnson']
    >>> _extract_entity_names_from_query("what is artificial intelligence")
    []

Notes:
    - Only detects capitalized word sequences (minimum 3 characters per word)
    - Stops collecting words when a non-capitalized word is encountered
    - Does not validate whether extracted names correspond to actual entities
    - Simple pattern matching may miss some entities or include false positives
    - Works best with properly formatted natural language queries
    """
```
* **Async:** False
* **Method:** True
* **Class:** QueryEngine

## _generate_query_suggestions

```python
async def _generate_query_suggestions(self, query: str, results: List[QueryResult]) -> List[str]:
    """
    Generate intelligent follow-up query suggestions based on result content and patterns.

This method analyzes query results to create contextually relevant follow-up queries
that help users explore related information, dive deeper into specific topics, or
discover new connections within the knowledge base. Suggestions are generated based
on entities mentioned, relationships found, and document patterns in the results.

Args:
    query (str): Original query string used for context.
        Helps maintain relevance to user's original intent.
    results (List[QueryResult]): Query results to analyze for suggestion generation.
        Typically the top-ranked results that provide the richest content
        for generating meaningful follow-up queries.

Returns:
    List[str]: List of suggested follow-up queries (maximum 5).
        Suggestions are ordered by relevance and likelihood of user interest.
        Returns empty list if no meaningful suggestions can be generated.
        Each suggestion is a complete, executable query string.

Raises:
    TypeError: If results contains non-QueryResult objects.
    ValueError: If results list is empty (no suggestions possible).

Examples:
    >>> results = [entity_result_gates, entity_result_microsoft]
    >>> suggestions = await _generate_query_suggestions("Bill Gates", results)
    >>> print(suggestions)
    ['What is Bill Gates?', 'What are the relationships of Bill Gates?', 
     'What is Microsoft?', 'Find all founded relationships']

Notes:
    - Analyzes top 5 results for entity and relationship content
    - Generates entity-specific queries for people and organizations mentioned
    - Suggests cross-document analysis when multiple documents are involved
    - Creates relationship-type queries when specific relationship types are found
    - Limits output to 5 suggestions to avoid overwhelming users
    """
```
* **Async:** True
* **Method:** True
* **Class:** QueryEngine

## _get_entity_documents

```python
def _get_entity_documents(self, entity: Entity) -> List[str]:
    """
    Retrieve document IDs where a specific entity appears in the knowledge base.

This method identifies all documents that contain references to a given entity
by checking entity source chunks against document chunk collections. It provides
document-level attribution for entities, enabling traceability and document-
specific filtering in query results.

Args:
    entity (Entity): Entity object to search for in document collections.
        Must have valid source_chunks attribute containing chunk identifiers
        where the entity was extracted.

Returns:
    List[str]: List of document IDs where the entity appears.
        Document IDs correspond to knowledge graph document identifiers.
        Returns ['unknown'] if entity appears in no identifiable documents.
        Documents are returned in order of knowledge graph iteration.

Raises:
    TypeError: If entity is not an Entity instance.
    AttributeError: If entity lacks required source_chunks attribute.
    RuntimeError: If knowledge graph data is corrupted or inaccessible.

Examples:
    >>> entity = Entity(id="ent_001", name="Bill Gates", source_chunks=["doc1_chunk5"])
    >>> _get_entity_documents(entity)
    ['document_001']
    >>> cross_doc_entity = Entity(id="ent_002", source_chunks=["doc1_ch1", "doc2_ch3"])
    >>> _get_entity_documents(cross_doc_entity)
    ['document_001', 'document_002']

Notes:
    - Searches through all knowledge graphs in the GraphRAG integrator
    - Matches entity source chunks against document chunk identifiers
    - Returns unique document IDs (no duplicates)
    - Used for source attribution in query results
    - Performance scales with number of documents and chunks
    """
```
* **Async:** False
* **Method:** True
* **Class:** QueryEngine

## _get_relationship_documents

```python
def _get_relationship_documents(self, relationship: Relationship) -> List[str]:
    """
    Retrieve document IDs where a specific relationship appears in the knowledge base.

This method identifies all documents that contain evidence for a given relationship
by checking relationship source chunks against document chunk collections. It provides
document-level attribution for relationships, enabling traceability and source
verification for relationship-based query results.

Args:
    relationship (Relationship): Relationship object to search for in document collections.
        Must have valid source_chunks attribute containing chunk identifiers
        where the relationship evidence was found.

Returns:
    List[str]: List of document IDs where the relationship appears.
        Document IDs correspond to knowledge graph document identifiers.
        Returns ['unknown'] if relationship appears in no identifiable documents.
        Documents are returned in order of knowledge graph iteration.

Raises:
    TypeError: If relationship is not a Relationship instance.
    AttributeError: If relationship lacks required source_chunks attribute.
    RuntimeError: If knowledge graph data is corrupted or inaccessible.

Examples:
    >>> rel = Relationship(id="rel_001", source_chunks=["doc1_chunk3"])
    >>> _get_relationship_documents(rel)
    ['document_001']
    >>> cross_doc_rel = Relationship(id="rel_002", source_chunks=["doc1_ch2", "doc3_ch1"])
    >>> _get_relationship_documents(cross_doc_rel)
    ['document_001', 'document_003']

Notes:
    - Searches through all knowledge graphs in the GraphRAG integrator
    - Matches relationship source chunks against document chunk identifiers
    - Returns unique document IDs (no duplicates)
    - Used for source attribution in relationship query results
    - Critical for establishing relationship provenance and evidence
    """
```
* **Async:** False
* **Method:** True
* **Class:** QueryEngine

## _normalize_query

```python
def _normalize_query(self, query: str) -> str:
    """
    Normalize query text for consistent processing across all query types.

This method standardizes query text by performing lowercasing, whitespace cleanup,
and stop word removal to improve matching accuracy and reduce noise in query
processing. The normalization process enhances the effectiveness of both keyword
matching and semantic search operations.

Args:
    query (str): Raw query string from user input.
        May contain mixed case, extra whitespace, and common stop words.

Returns:
    str: Normalized query string with:
        - All text converted to lowercase
        - Multiple whitespace characters collapsed to single spaces
        - Leading and trailing whitespace removed
        - Common English stop words filtered out
        - Remaining words joined with single spaces

Raises:
    TypeError: If query is not a string.
    ValueError: If query is empty or contains only whitespace.

Examples:
    >>> _normalize_query("  Who IS the  CEO of   Microsoft?  ")
    'who ceo microsoft'
    >>> _normalize_query("COMPANIES founded BY bill gates")
    'companies founded bill gates'
    >>> _normalize_query("The relationship between AI and automation")
    'relationship ai automation'

Notes:
    - Stop words removed: 'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for', 'of', 'with', 'by'
    - Punctuation is preserved for potential entity name matching
    - Single character words are not specifically filtered unless they are stop words
    - Normalization improves both keyword and semantic matching effectiveness
    """
```
* **Async:** False
* **Method:** True
* **Class:** QueryEngine

## _process_cross_document_query

```python
async def _process_cross_document_query(self, query: str, filters: Optional[Dict[str, Any]], max_results: int) -> List[QueryResult]:
    """
    Process cross-document analysis queries examining relationships spanning multiple documents.

This method handles queries focused on discovering and analyzing relationships that
exist between entities across different documents in the knowledge base. It leverages
pre-computed cross-document relationships to identify connections, patterns, and
insights that span the entire document collection.

Args:
    query (str): Normalized query string focused on cross-document analysis.
        Should contain terms related to document comparison, entity connections,
        or multi-document relationship discovery.
    filters (Optional[Dict[str, Any]]): Cross-document filtering criteria.
        Supported filter keys:
        - 'source_document': Filter by specific source document
        - 'target_document': Filter by specific target document
        - 'relationship_type': Filter by specific cross-document relationship type
        - 'min_confidence': Minimum confidence score for cross-document relationships
    max_results (int): Maximum number of cross-document results to return.
        Must be positive integer.

Returns:
    List[QueryResult]: Ordered list of cross-document relationship results sorted by relevance.
        Each result contains formatted cross-document relationship description,
        relevance scoring, multi-document source attribution, and metadata including
        entity details from both documents and relationship evidence.

Raises:
    ValueError: If max_results is not positive.
    TypeError: If filters contain invalid data types.
    RuntimeError: If cross-document relationship data is corrupted or inaccessible.
    KeyError: If referenced entities are missing from global entity registry.

Examples:
    >>> # Find cross-document entity connections
    >>> results = await _process_cross_document_query("companies across documents", None, 10)
    >>> print(results[0].content)  # "Microsoft (doc1) founded GitHub (doc2)"
    
    >>> # Filter by relationship type
    >>> results = await _process_cross_document_query(
    ...     "acquisitions multiple documents",
    ...     {"relationship_type": "acquired"},
    ...     5
    ... )

Notes:
    - Requires pre-computed cross-document relationships from GraphRAG integrator
    - Returns empty results if no cross-document relationships exist
    - Scoring considers entity name matching and relationship type relevance
    - Results include evidence chunks from both source and target documents
    - Missing entities are logged and skipped rather than causing failures
    """
```
* **Async:** True
* **Method:** True
* **Class:** QueryEngine

## _process_document_query

```python
async def _process_document_query(self, query: str, filters: Optional[Dict[str, Any]], max_results: int) -> List[QueryResult]:
    """
    Process document-level queries analyzing entire documents and their characteristics.

This method handles queries seeking information about documents themselves rather
than specific content within documents. It analyzes document metadata, titles,
entity distributions, and overall content characteristics to match user queries
with relevant documents in the knowledge base.

Args:
    query (str): Normalized query string focused on document-level information.
        Can include document titles, topics, entity counts, or document characteristics.
    filters (Optional[Dict[str, Any]]): Document-specific filtering criteria.
        Supported filter keys:
        - 'document_id': Limit to specific document (for detailed analysis)
        - 'min_entities': Minimum number of entities in document
        - 'min_relationships': Minimum number of relationships in document
        - 'creation_date': Filter by document creation/processing date
    max_results (int): Maximum number of document results to return.
        Must be positive integer.

Returns:
    List[QueryResult]: Ordered list of document results sorted by relevance score.
        Each result contains document summary, statistics, key entities, and
        metadata including processing information and IPLD storage details.

Raises:
    ValueError: If max_results is not positive.
    TypeError: If filters contain invalid data types.
    RuntimeError: If document metadata is corrupted or inaccessible.
    AttributeError: If documents lack required metadata attributes.

Examples:
    >>> # Find documents about specific topics
    >>> results = await _process_document_query("artificial intelligence papers", None, 5)
    >>> print(results[0].content)  # Document summary with entity counts
    
    >>> # Filter by document characteristics
    >>> results = await _process_document_query(
    ...     "technology documents",
    ...     {"min_entities": 10, "min_relationships": 5},
    ...     3
    ... )

Notes:
    - Scoring combines title matching, entity content matching, and document characteristics
    - Document summaries include entity counts, relationship counts, and key entities
    - Results provide comprehensive document metadata for detailed analysis
    - Entity sampling is limited to first 5 entities for readability
    - Content sampling analyzes first 10 chunks for performance optimization
    """
```
* **Async:** True
* **Method:** True
* **Class:** QueryEngine

## _process_entity_query

```python
async def _process_entity_query(self, query: str, filters: Optional[Dict[str, Any]], max_results: int) -> List[QueryResult]:
    """
    Process entity-focused queries using name matching and type filtering.

This method handles queries seeking information about specific entities (people,
organizations, locations, etc.) by performing fuzzy name matching, description
analysis, and type-based filtering. It scores entities based on query relevance
and returns formatted results with comprehensive metadata.

Args:
    query (str): Normalized query string focused on entity identification.
        Should contain entity names, types, or descriptive terms.
    filters (Optional[Dict[str, Any]]): Entity-specific filtering criteria.
        Supported filter keys:
        - 'entity_type': Filter by specific entity type (Person, Organization, etc.)
        - 'document_id': Limit to entities appearing in specific document
        - 'confidence': Minimum confidence score for entity extraction
    max_results (int): Maximum number of entity results to return.
        Must be positive integer.

Returns:
    List[QueryResult]: Ordered list of entity results sorted by relevance score.
        Each result contains entity information, relevance scoring, source attribution,
        and metadata including entity properties and confidence scores.

Raises:
    ValueError: If max_results is not positive.
    TypeError: If filters contain invalid data types.
    RuntimeError: If GraphRAG entity data is corrupted or inaccessible.

Examples:
    >>> # Find specific person
    >>> results = await _process_entity_query("bill gates", None, 10)
    >>> print(results[0].content)  # "Bill Gates (Person): Co-founder of Microsoft"
    
    >>> # Filter by entity type
    >>> results = await _process_entity_query(
    ...     "technology companies",
    ...     {"entity_type": "Organization"},
    ...     5
    ... )

Notes:
    - Scoring combines name similarity, description matching, and exact matches
    - Entity type matching is case-sensitive and must match extracted types exactly
    - Document filtering checks entity presence in document chunks
    - Relevance scores are normalized to 0-1 range for consistency
    - Results include source document attribution for traceability
    """
```
* **Async:** True
* **Method:** True
* **Class:** QueryEngine

## _process_graph_traversal_query

```python
async def _process_graph_traversal_query(self, query: str, filters: Optional[Dict[str, Any]], max_results: int) -> List[QueryResult]:
    """
    Process graph traversal queries for path-finding and connection analysis.

This method handles queries seeking to understand how entities are connected
through the knowledge graph by finding paths, analyzing connection degrees,
and exploring relationship networks. It uses NetworkX graph algorithms to
compute shortest paths and analyze graph structure between specified entities.

Args:
    query (str): Normalized query string focused on graph traversal and paths.
        Should contain entity names for path finding or connection analysis terms.
        Examples: "path from X to Y", "how are X and Y connected", "connection degree"
    filters (Optional[Dict[str, Any]]): Graph traversal filtering criteria.
        Supported filter keys:
        - 'max_path_length': Maximum allowed path length for traversal
        - 'entity_types': Filter path entities by specific types
        - 'relationship_types': Filter path relationships by specific types
        - 'min_confidence': Minimum confidence for path relationships
    max_results (int): Maximum number of path results to return.
        Must be positive integer.

Returns:
    List[QueryResult]: Ordered list of graph path results sorted by path length.
        Each result contains formatted path description, path length as relevance score,
        multiple document attribution, and metadata including complete path information
        and entity details for each path node.

Raises:
    ValueError: If max_results is not positive or fewer than 2 entities extracted.
    TypeError: If filters contain invalid data types.
    RuntimeError: If NetworkX graph is corrupted or inaccessible.
    ImportError: If NetworkX library is not available.
    NetworkXNoPath: If no path exists between specified entities.

Examples:
    >>> # Find connection path
    >>> results = await _process_graph_traversal_query("path Bill Gates Microsoft", None, 5)
    >>> print(results[0].content)  # "Path: Bill Gates → founded → Microsoft"
    
    >>> # Limited path length
    >>> results = await _process_graph_traversal_query(
    ...     "connection John Smith Apple",
    ...     {"max_path_length": 3},
    ...     10
    ... )

Notes:
    - Requires NetworkX library and properly constructed global graph
    - Extracts entity names using capitalization patterns
    - Shorter paths receive higher relevance scores
    - Returns empty results if fewer than 2 entities can be identified
    - Path finding is limited to prevent excessive computation
    """
```
* **Async:** True
* **Method:** True
* **Class:** QueryEngine

## _process_relationship_query

```python
async def _process_relationship_query(self, query: str, filters: Optional[Dict[str, Any]], max_results: int) -> List[QueryResult]:
    """
    Process relationship-focused queries analyzing connections between entities.

This method handles queries seeking information about relationships between entities
by analyzing relationship types, entity names, and descriptive context. It performs
comprehensive matching across relationship attributes and participating entities to
identify relevant connections within the knowledge graph.

Args:
    query (str): Normalized query string focused on relationship identification.
        Should contain relationship types, entity names, or connection descriptors.
    filters (Optional[Dict[str, Any]]): Relationship-specific filtering criteria.
        Supported filter keys:
        - 'relationship_type': Filter by specific relationship type (founded, works_for, etc.)
        - 'entity_id': Limit to relationships involving specific entity
        - 'confidence': Minimum confidence score for relationship extraction
        - 'document_id': Limit to relationships from specific document
    max_results (int): Maximum number of relationship results to return.
        Must be positive integer.

Returns:
    List[QueryResult]: Ordered list of relationship results sorted by relevance score.
        Each result contains formatted relationship description, relevance scoring,
        source attribution, and metadata including entity details and relationship properties.

Raises:
    ValueError: If max_results is not positive.
    TypeError: If filters contain invalid data types.
    RuntimeError: If GraphRAG relationship data is corrupted or inaccessible.
    KeyError: If referenced entities are missing from global entity registry.

Examples:
    >>> # Find founding relationships
    >>> results = await _process_relationship_query("founded companies", None, 10)
    >>> print(results[0].content)  # "Bill Gates founded Microsoft"
    
    >>> # Find relationships for specific entity
    >>> results = await _process_relationship_query(
    ...     "microsoft relationships",
    ...     {"entity_id": "entity_microsoft_001"},
    ...     5
    ... )

Notes:
    - Scoring considers relationship type matching, entity name matching, and description content
    - Relationship types use underscore format (e.g., 'works_for', 'founded_by')
    - Entity filtering checks both source and target entity participation
    - Results include complete entity information for both relationship participants
    - Missing entities are skipped with warning logs rather than causing failures
    """
```
* **Async:** True
* **Method:** True
* **Class:** QueryEngine

## _process_semantic_query

```python
async def _process_semantic_query(self, query: str, filters: Optional[Dict[str, Any]], max_results: int) -> List[QueryResult]:
    """
    Process semantic search queries using embedding similarity matching.

This method handles conceptual queries by computing semantic similarity between
the query text and document chunks using sentence transformer embeddings. It
performs vector-based matching to find content that is conceptually related
rather than requiring exact keyword matches, enabling more flexible and
intelligent content discovery.

Args:
    query (str): Normalized query string for semantic matching.
        Can contain concepts, topics, or descriptive terms that don't require
        exact keyword matches in the target content.
    filters (Optional[Dict[str, Any]]): Semantic search filtering criteria.
        Supported filter keys:
        - 'document_id': Limit search to specific document
        - 'semantic_types': Filter by chunk content type (paragraph, heading, etc.)
        - 'min_similarity': Minimum cosine similarity threshold (0.0-1.0)
        - 'page_range': Tuple of (start_page, end_page) for page filtering
    max_results (int): Maximum number of semantic results to return.
        Must be positive integer.

Returns:
    List[QueryResult]: Ordered list of chunk results sorted by semantic similarity.
        Each result contains chunk content, similarity scores, source attribution,
        and metadata including related entities and semantic classifications.

Raises:
    ValueError: If max_results is not positive or similarity thresholds are invalid.
    TypeError: If filters contain invalid data types.
    RuntimeError: If embedding model is not available or embedding computation fails.
    AttributeError: If chunks lack required embedding attributes.

Examples:
    >>> # Conceptual search
    >>> results = await _process_semantic_query("machine learning applications", None, 10)
    >>> print(f"Similarity: {results[0].relevance_score}")
    
    >>> # Filtered semantic search
    >>> results = await _process_semantic_query(
    ...     "artificial intelligence",
    ...     {"document_id": "doc_001", "min_similarity": 0.7},
    ...     5
    ... )

Notes:
    - Requires successfully loaded sentence transformer embedding model
    - Uses cosine similarity between query and chunk embeddings
    - Chunks without embeddings are automatically skipped
    - Related entities are identified by checking entity source chunks
    - Content may be truncated in results for readability (full content in metadata)
    """
```
* **Async:** True
* **Method:** True
* **Class:** QueryEngine

## get_query_analytics

```python
async def get_query_analytics(self) -> Dict[str, Any]:
    """
    Retrieve comprehensive analytics about query patterns, performance, and system usage.

This method analyzes cached query data to provide insights into query engine
performance, user behavior patterns, query type distributions, and system
utilization metrics. The analytics help with performance optimization,
understanding user needs, and monitoring system health.

Returns:
    Dict[str, Any]: Comprehensive analytics dictionary containing:
        - 'total_queries': Total number of queries processed and cached
        - 'query_types': Distribution of query types with counts
        - 'average_processing_time': Mean query processing time in seconds
        - 'average_results_per_query': Mean number of results returned per query
        - 'cache_size': Number of cached query responses
        - 'embedding_cache_size': Number of cached embedding computations
        Returns {'message': 'No query data available'} if no queries have been processed.

Raises:
    RuntimeError: If cache data is corrupted or inaccessible.
    ValueError: If cached query responses lack required timing information.

Examples:
    >>> analytics = await engine.get_query_analytics()
    >>> print(f"Processed {analytics['total_queries']} queries")
    >>> print(f"Average time: {analytics['average_processing_time']:.3f}s")
    >>> print(f"Query types: {analytics['query_types']}")
    {
        'total_queries': 150,
        'query_types': {
            'entity_search': 60,
            'semantic_search': 45,
            'relationship_search': 30,
            'document_search': 15
        },
        'average_processing_time': 0.145,
        'average_results_per_query': 8.2,
        'cache_size': 150,
        'embedding_cache_size': 45
    }

Notes:
    - Analytics are based on cached query data only
    - Processing times include all operations from normalization to response generation
    - Query type distribution helps understand user behavior patterns
    - Cache metrics indicate memory usage and optimization opportunities
    - Used for performance monitoring and system optimization decisions
    """
```
* **Async:** True
* **Method:** True
* **Class:** QueryEngine

## query

```python
async def query(self, query_text: str, query_type: Optional[str] = None, filters: Optional[Dict[str, Any]] = None, max_results: int = 20) -> QueryResponse:
    """
    Process a natural language query against the PDF knowledge base.

This method serves as the primary interface for querying the PDF knowledge base,
supporting natural language input with automatic query type detection, result
filtering, and comprehensive response generation. It handles query normalization,
type detection, cache management, result processing, and suggestion generation
to provide a complete query experience.

Args:
    query_text (str): Natural language query string from the user.
        Can include complex questions, entity names, relationship queries,
        or semantic search terms. No specific format required.
    query_type (Optional[str], optional): Specific query type to force processing mode.
        Valid values: 'entity_search', 'relationship_search', 'semantic_search',
        'document_search', 'cross_document', 'graph_traversal'.
        If None, query type will be auto-detected. Defaults to None.
    filters (Optional[Dict[str, Any]], optional): Additional filtering criteria.
        Common filter keys: 'document_id', 'entity_type', 'relationship_type',
        'semantic_types', 'min_similarity'. Structure varies by query type.
        Defaults to None (no filtering).
    max_results (int, optional): Maximum number of results to return.
        Must be positive integer. Large values may impact performance.
        Defaults to 20.

Returns:
    QueryResponse: Complete query response containing:
        - Original query and detected/specified type
        - Ordered list of QueryResult objects (by relevance)
        - Total result count and processing time
        - Generated query suggestions for follow-up
        - Comprehensive metadata about query execution

Raises:
    ValueError: If query_text is empty or max_results is not positive.
    TypeError: If filters contain invalid data types for specific query types.
    RuntimeError: If query processing fails due to system errors.
    TimeoutError: If query processing exceeds reasonable time limits.

Examples:
    >>> # Basic entity search
    >>> response = await engine.query("Who is Bill Gates?")
    >>> print(f"Found {response.total_results} results")
    
    >>> # Relationship search with filtering
    >>> response = await engine.query(
    ...     "founders of companies",
    ...     query_type="relationship_search",
    ...     filters={"relationship_type": "founded"},
    ...     max_results=10
    ... )
    
    >>> # Semantic search across specific document
    >>> response = await engine.query(
    ...     "artificial intelligence applications",
    ...     query_type="semantic_search",
    ...     filters={"document_id": "doc_001", "min_similarity": 0.7}
    ... )

Notes:
    - Query normalization includes lowercasing, whitespace cleanup, and stop word removal
    - Auto-detection uses keyword patterns to classify query intent
    - Results are cached for performance; identical queries return cached responses
    - Processing time includes all operations from normalization to suggestion generation
    - Suggestions are generated based on result content and common query patterns
    """
```
* **Async:** True
* **Method:** True
* **Class:** QueryEngine
