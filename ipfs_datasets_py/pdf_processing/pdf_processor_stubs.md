# Function and Class stubs from '/home/kylerose1946/ipfs_datasets_py/ipfs_datasets_py/pdf_processing/pdf_processor.py'

Files last updated: 1751978169.2389922

Stub file last updated: 2025-07-08 05:37:03

## PDFProcessor

```python
class PDFProcessor:
    """
    Core PDF Processing Pipeline Implementation

The PDFProcessor class implements a comprehensive 10-stage PDF processing pipeline
that transforms PDF documents into structured, searchable, and semantically enriched
data structures. The pipeline processes PDF files through decomposition, IPLD structuring,
OCR processing, LLM optimization, entity extraction, vector embedding generation,
GraphRAG integration, cross-document analysis, and query interface setup.

This class serves as the primary entry point for converting PDF documents into
knowledge graphs with full content addressability, semantic search capabilities,
and cross-document relationship discovery.

Args:
    storage (Optional[IPLDStorage], optional): IPLD storage instance for data persistence.
        Defaults to a new IPLDStorage instance if not provided.
    enable_monitoring (bool, optional): Enable performance monitoring and metrics collection.
        When True, initializes MonitoringSystem with Prometheus export capabilities.
        Defaults to False.
    enable_audit (bool, optional): Enable audit logging for security and compliance tracking.
        When True, initializes AuditLogger for data access and security event logging.
        Defaults to True.

Pipeline Stages:
1. PDF Input - Validation and analysis of input PDF file
2. Decomposition - Extract PDF layers, content, images, and metadata
3. IPLD Structuring - Create content-addressed data structures
4. OCR Processing - Process images with optical character recognition
5. LLM Optimization - Optimize content for language model consumption
6. Entity Extraction - Extract entities and relationships from content
7. Vector Embedding - Create semantic embeddings for content chunks
8. IPLD GraphRAG Integration - Integrate with GraphRAG knowledge system
9. Cross-Document Analysis - Analyze relationships across document collections
10. Query Interface Setup - Configure natural language query capabilities

Attributes:
    storage (IPLDStorage): IPLD storage instance for persistent data storage
    audit_logger (Optional[AuditLogger]): Audit logger for security and compliance tracking
    monitoring (Optional[MonitoringSystem]): Performance monitoring system for metrics collection
    processing_stats (Dict[str, Any]): Runtime statistics and performance metrics

Public Methods:
    process_pdf(pdf_path: Union[str, Path], metadata: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        Execute the complete PDF processing pipeline from input validation through
        query interface setup, returning comprehensive processing results.

Private Methods:
    _validate_and_analyze_pdf(pdf_path: Path) -> Dict[str, Any]:
        Stage 1: Validate PDF file integrity and extract basic metadata analysis.
    _decompose_pdf(pdf_path: Path) -> Dict[str, Any]:
        Stage 2: Decompose PDF into constituent elements including text, images,
        annotations, tables, and structural components.
    _extract_page_content(page, page_num: int) -> Dict[str, Any]:
        Extract comprehensive content from a single PDF page including text blocks,
        images, annotations, and vector graphics.
    _create_ipld_structure(decomposed_content: Dict[str, Any]) -> Dict[str, Any]:
        Stage 3: Create hierarchical IPLD structure with content-addressed storage
        for all decomposed PDF components.
    _process_ocr(decomposed_content: Dict[str, Any]) -> Dict[str, Any]:
        Stage 4: Process embedded images with multi-engine OCR for text extraction
        with confidence scoring and word-level positioning.
    _optimize_for_llm(decomposed_content: Dict[str, Any], ocr_results: Dict[str, Any]) -> Dict[str, Any]:
        Stage 5: Optimize extracted content for large language model consumption
        through chunking, summarization, and semantic structuring.
    _extract_entities(optimized_content: Dict[str, Any]) -> Dict[str, Any]:
        Stage 6: Extract named entities and relationships from optimized content
        using pattern matching and co-occurrence analysis.
    _create_embeddings(optimized_content: Dict[str, Any], entities_and_relations: Dict[str, Any]) -> Dict[str, Any]:
        Stage 7: Generate vector embeddings for content chunks and document-level
        representations using transformer models.
    _integrate_with_graphrag(ipld_structure: Dict[str, Any], entities_and_relations: Dict[str, Any], embeddings: Dict[str, Any]) -> Dict[str, Any]:
        Stage 8: Integrate processed content with GraphRAG system for knowledge
        graph construction and semantic relationship discovery.
    _analyze_cross_document_relationships(graph_nodes: Dict[str, Any]) -> List[Dict[str, Any]]:
        Stage 9: Analyze and discover relationships between entities across
        multiple documents in the knowledge graph.
    _setup_query_interface(graph_nodes: Dict[str, Any], cross_doc_relations: List[Dict[str, Any]]):
        Stage 10: Configure natural language query interface for semantic search
        and knowledge graph exploration.
    _calculate_file_hash(file_path: Path) -> str:
        Calculate SHA-256 hash of input file for integrity verification and
        content addressability.
    _extract_native_text(text_blocks: List[Dict[str, Any]]) -> str:
        Extract and concatenate native text content from PDF text blocks
        preserving document structure.
    _get_processing_time() -> float:
        Calculate total elapsed time for complete pipeline processing
        including all stages and error handling.
    _get_quality_scores() -> Dict[str, float]:
        Generate quality assessment scores for text extraction, OCR confidence,
        entity extraction, and overall processing quality.

Usage Example:
    # Basic usage with default settings
    processor = PDFProcessor()
    result = await processor.process_pdf("document.pdf")
    
    # Advanced usage with monitoring and custom storage
    storage = IPLDStorage(config={'node_url': 'http://localhost:5001'})
    processor = PDFProcessor(
        storage=storage,
        enable_monitoring=True,
        enable_audit=True
    )
    metadata = {'source': 'legal_docs', 'priority': 'high'}
    result = await processor.process_pdf(
        pdf_path="contract.pdf",
        metadata=metadata
    )
    
    # Check processing results
    if result['status'] == 'success':
        print(f"Document ID: {result['document_id']}")
        print(f"Entities found: {result['entities_count']}")
        print(f"IPLD CID: {result['ipld_cid']}")

Notes:
    - All processing stages are asynchronous for optimal performance
    - IPLD integration provides content-addressable storage and deduplication
    - GraphRAG integration enables semantic search and relationship discovery
    - Monitoring and audit logging support enterprise deployment requirements
    - Error handling ensures graceful failure with detailed error reporting
    - Cross-document analysis requires multiple documents in the knowledge graph
    - Pipeline is optimized for both single-document and batch processing scenarios
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## __init__

```python
def __init__(self, storage: Optional[IPLDStorage] = None, enable_monitoring: bool = False, enable_audit: bool = True):
    """
    Initialize the PDF processor with storage, monitoring, and audit capabilities.

Sets up the core PDF processing pipeline with configurable storage backend,
performance monitoring, and audit logging. Initializes processing state
tracking and prepares all necessary components for document processing.

Args:
    storage (Optional[IPLDStorage], optional): IPLD storage instance for data persistence.
        If None, creates a new IPLDStorage instance with default configuration.
        Custom storage instances allow for distributed IPFS node configuration.
        Defaults to None.
    enable_monitoring (bool, optional): Enable performance monitoring and metrics collection.
        When True, initializes MonitoringSystem with Prometheus export enabled,
        JSON metrics output, and operation tracking capabilities.
        Defaults to False.
    enable_audit (bool, optional): Enable audit logging for security and compliance.
        When True, initializes AuditLogger singleton for data access logging,
        security event tracking, and compliance reporting.
        Defaults to True.

Attributes initialized:
    storage (IPLDStorage): IPLD storage instance for persistent data storage.
        Handles content-addressed storage, IPFS integration, and data retrieval.
    audit_logger (Optional[AuditLogger]): Audit logger for security and compliance tracking.
        Logs data access events, security incidents, and processing activities.
    monitoring (Optional[MonitoringSystem]): Performance monitoring system for metrics.
        Tracks operation performance, resource usage, and system health metrics.
    processing_stats (Dict[str, Any]): Runtime statistics and performance metrics.
        Stores pipeline execution times, quality scores, and processing metadata.

Raises:
    ImportError: If monitoring dependencies are missing when enable_monitoring=True
    RuntimeError: If audit logger initialization fails when enable_audit=True
    ConnectionError: If IPLD storage cannot connect to IPFS node

Examples:
    >>> # Basic initialization with defaults
    >>> processor = PDFProcessor()
    >>> 
    >>> # Enterprise setup with full monitoring
    >>> custom_storage = IPLDStorage(config={'node_url': 'http://ipfs-cluster:5001'})
    >>> processor = PDFProcessor(
    ...     storage=custom_storage,
    ...     enable_monitoring=True,
    ...     enable_audit=True
    ... )
    >>> 
    >>> # Development setup without monitoring
    >>> processor = PDFProcessor(enable_monitoring=False, enable_audit=False)

Note:
    Monitoring configuration includes Prometheus export and JSON metrics output.
    Audit logging captures all data access and security events for compliance.
    IPLD storage provides content deduplication and distributed storage capabilities.
    """
```
* **Async:** False
* **Method:** True
* **Class:** PDFProcessor

## _analyze_cross_document_relationships

```python
async def _analyze_cross_document_relationships(self, graph_nodes: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Stage 9: Analyze and discover relationships between entities across documents.

Performs cross-document entity resolution and relationship discovery by comparing
entities across the global knowledge graph. Identifies entity aliases, merges
similar entities, and discovers implicit relationships between documents
based on shared entities, topics, and semantic similarity patterns.

Args:
    graph_nodes (Dict[str, Any]): GraphRAG integration results with knowledge graph.
        Contains document knowledge graph with entities and relationships.

Returns:
    List[Dict[str, Any]]: Cross-document relationships discovered between entities.
        Each relationship includes entity pairs, relationship type, confidence,
        and source documents for comprehensive cross-document analysis.

Raises:
    ValueError: If graph nodes structure is invalid or incomplete
    RuntimeError: If cross-document analysis encounters processing errors
    AttributeError: If knowledge graph lacks required methods or attributes
    MemoryError: If global graph size exceeds available memory for analysis

Examples:
    >>> cross_relations = await processor._analyze_cross_document_relationships(graph_nodes)
    >>> print(f"Found {len(cross_relations)} cross-document relationships")
    >>> for relation in cross_relations:
    ...     print(f"{relation['source']} -> {relation['target']} ({relation['type']})")

Note:
    Cross-document analysis requires multiple documents in the knowledge graph.
    Entity resolution uses similarity thresholds and fuzzy matching algorithms.
    Relationship discovery leverages both explicit mentions and implicit connections.
    Results enable comprehensive knowledge discovery across document collections.
    """
```
* **Async:** True
* **Method:** True
* **Class:** PDFProcessor

## _calculate_file_hash

```python
def _calculate_file_hash(self, file_path: Path) -> str:
    """
    Calculate SHA-256 hash of input file for integrity verification and content addressability.

Computes cryptographic hash of the input PDF file using SHA-256 algorithm
for content integrity verification, deduplication, and content addressability.
Processes file in chunks to handle large files efficiently without loading
entire file content into memory simultaneously.

Args:
    file_path (Path): Path object pointing to the file for hash calculation.
        Must be a readable file with appropriate permissions.

Returns:
    str: Hexadecimal representation of SHA-256 hash digest.
        Provides unique identifier for file content verification.

Raises:
    FileNotFoundError: If the file does not exist at the specified path
    PermissionError: If insufficient permissions to read the file
    IOError: If file system errors occur during reading
    OSError: If operating system level errors prevent file access

Examples:
    >>> hash_value = processor._calculate_file_hash(Path("document.pdf"))
    >>> print(f"File hash: {hash_value}")
    >>> # Hash can be used for deduplication
    >>> if hash_value in processed_hashes:
    ...     print("Document already processed")

Note:
    Uses 4KB chunks for memory-efficient processing of large files.
    SHA-256 provides cryptographically secure hash for integrity verification.
    Hash values enable content deduplication across document collections.
    Consistent hashing supports content addressability in IPLD storage.
    """
```
* **Async:** False
* **Method:** True
* **Class:** PDFProcessor

## _create_embeddings

```python
async def _create_embeddings(self, optimized_content: Dict[str, Any], entities_and_relations: Dict[str, Any]) -> Dict[str, Any]:
    """
    Stage 7: Generate vector embeddings for content chunks and document representation.

Creates high-dimensional vector representations for content chunks and document-level
summaries using transformer-based embedding models. Generates embeddings suitable
for semantic similarity search, clustering, and knowledge graph construction
with consistent dimensionality and normalization for downstream processing.

Args:
    optimized_content (Dict[str, Any]): LLM-optimized content with structured chunks.
        Contains LLM document with preprocessed chunks ready for embedding.
    entities_and_relations (Dict[str, Any]): Extracted entities and relationships.
        Used for context-aware embedding generation and entity-specific vectors.

Returns:
    Dict[str, Any]: Vector embedding results containing:
        - chunk_embeddings (List[Dict[str, Any]]): Per-chunk embeddings with metadata
        - document_embedding (List[float]): Document-level embedding vector
        - embedding_model (str): Identifier of the embedding model used

Raises:
    ImportError: If embedding model dependencies are not available
    RuntimeError: If embedding generation fails due to model or memory issues
    ValueError: If content structure is incompatible with embedding requirements
    MemoryError: If document size exceeds embedding model memory limits

Examples:
    >>> embeddings = await processor._create_embeddings(optimized_content, entities_relations)
    >>> chunk_embeds = embeddings['chunk_embeddings']
    >>> doc_embed = embeddings['document_embedding']
    >>> print(f"Generated {len(chunk_embeds)} chunk embeddings")
    >>> print(f"Document embedding dimension: {len(doc_embed)}")

Note:
    Uses sentence-transformers/all-MiniLM-L6-v2 as default embedding model.
    Embeddings are normalized for cosine similarity calculations.
    Chunk embeddings preserve content locality and semantic coherence.
    Document-level embeddings enable cross-document similarity analysis.
    """
```
* **Async:** True
* **Method:** True
* **Class:** PDFProcessor

## _create_ipld_structure

```python
async def _create_ipld_structure(self, decomposed_content: Dict[str, Any]) -> Dict[str, Any]:
    """
    Stage 3: Create hierarchical IPLD structure with content-addressed storage.

Transforms decomposed PDF content into InterPlanetary Linked Data (IPLD) format
providing content addressability, deduplication, and distributed storage capabilities.
Creates hierarchical node structure with separate storage for pages, metadata,
and content elements enabling efficient retrieval and cross-document linking.

Args:
    decomposed_content (Dict[str, Any]): Complete decomposed PDF content structure.
        Must contain pages, metadata, images, and structural information from
        the decomposition stage.

Returns:
    Dict[str, Any]: IPLD structure with content identifiers containing:
        - document (Dict[str, Any]): Document-level metadata and page references
        - content_map (Dict[str, str]): Mapping of content keys to IPLD CIDs
        - root_cid (str): Content identifier for the document root node

Raises:
    RuntimeError: If IPLD storage operations fail due to network or node issues
    ValueError: If decomposed content structure is invalid or incomplete
    ConnectionError: If IPFS node is unreachable or unresponsive
    StorageError: If content serialization or storage operations fail

Examples:
    >>> ipld_structure = await processor._create_ipld_structure(decomposed_content)
    >>> print(f"Root CID: {ipld_structure['root_cid']}")
    >>> print(f"Pages stored: {len(ipld_structure['content_map'])}")
    >>> # Retrieve specific page
    >>> page_cid = ipld_structure['content_map']['page_1']

Note:
    Each page is stored as a separate IPLD node for efficient retrieval.
    Content deduplication occurs automatically through content addressing.
    IPLD structure enables distributed storage and replication across nodes.
    Failed storage operations are logged but don't halt pipeline processing.
    """
```
* **Async:** True
* **Method:** True
* **Class:** PDFProcessor

## _decompose_pdf

```python
async def _decompose_pdf(self, pdf_path: Path) -> Dict[str, Any]:
    """
    Stage 2: Decompose PDF into constituent elements and content layers.

Performs comprehensive PDF decomposition extracting all content layers including
text blocks, images, annotations, tables, metadata, document structure, fonts,
and vector graphics. Uses both PyMuPDF and pdfplumber for complementary
extraction capabilities ensuring maximum content recovery and structural preservation.

Args:
    pdf_path (Path): Path object pointing to the validated PDF file.
        Must be a readable PDF file that has passed validation stage.

Returns:
    Dict[str, Any]: Comprehensive decomposed content structure containing:
        - pages (List[Dict[str, Any]]): Per-page content with elements, images, annotations
        - metadata (Dict[str, str]): Document metadata including title, author, dates
        - structure (Dict[str, Any]): Table of contents and outline information
        - images (List[Dict[str, Any]]): Extracted image data and metadata
        - fonts (List[Dict[str, str]]): Font information and usage statistics
        - annotations (List[Dict[str, Any]]): Comments, highlights, and markup elements

Raises:
    ValueError: If PDF file cannot be opened or is corrupted during processing
    RuntimeError: If PyMuPDF or pdfplumber encounter fatal errors during extraction
    MemoryError: If PDF file is too large for available system memory
    IOError: If file system errors occur during image extraction

Examples:
    >>> decomposed = await processor._decompose_pdf(Path("document.pdf"))
    >>> print(f"Pages: {len(decomposed['pages'])}")
    >>> print(f"Images: {len(decomposed['images'])}")
    >>> print(f"Title: {decomposed['metadata']['title']}")

Note:
    PyMuPDF handles comprehensive content extraction and image data.
    pdfplumber provides enhanced table detection and word-level positioning.
    Large PDF files are processed page-by-page to manage memory usage.
    Vector graphics and drawing elements are preserved with bounding boxes.
    """
```
* **Async:** True
* **Method:** True
* **Class:** PDFProcessor

## _extract_entities

```python
async def _extract_entities(self, optimized_content: Dict[str, Any]) -> Dict[str, Any]:
    """
    Stage 6: Extract named entities and relationships from optimized content.

Performs comprehensive named entity recognition and relationship extraction
from LLM-optimized content using pattern matching, co-occurrence analysis,
and contextual inference. Identifies persons, organizations, locations,
dates, and domain-specific entities with confidence scoring and relationship
classification for knowledge graph construction.

Args:
    optimized_content (Dict[str, Any]): LLM-optimized content with structured chunks.
        Must contain llm_document with processed chunks and entity annotations.

Returns:
    Dict[str, Any]: Entity and relationship extraction results containing:
        - entities (List[Dict[str, Any]]): Named entities with types, positions, confidence
        - relationships (List[Dict[str, Any]]): Entity relationships with types and sources

Raises:
    ValueError: If optimized content structure is invalid or missing required fields
    RuntimeError: If entity extraction engine encounters processing errors
    AttributeError: If LLM document lacks required attributes or methods
    TypeError: If entity or relationship objects have incorrect types

Examples:
    >>> entities_relations = await processor._extract_entities(optimized_content)
    >>> entities = entities_relations['entities']
    >>> relationships = entities_relations['relationships']
    >>> print(f"Found {len(entities)} entities and {len(relationships)} relationships")
    >>> for entity in entities[:5]:
    ...     print(f"{entity['text']} ({entity['type']})")

Note:
    Entity extraction leverages pre-existing annotations from LLM optimization.
    Relationship inference uses co-occurrence patterns within content chunks.
    Confidence scores enable filtering and quality assessment.
    Results integrate seamlessly with GraphRAG knowledge graph construction.
    """
```
* **Async:** True
* **Method:** True
* **Class:** PDFProcessor

## _extract_native_text

```python
def _extract_native_text(self, text_blocks: List[Dict[str, Any]]) -> str:
    """
    Extract and concatenate native text content from PDF text blocks preserving structure.

Processes text blocks extracted from PDF decomposition to create coherent
text representation while preserving document structure and readability.
Handles text block ordering, spacing, and formatting to maintain original
document flow and semantic meaning for downstream processing.

Args:
    text_blocks (List[Dict[str, Any]]): List of text block dictionaries from PDF extraction.
        Each block must contain 'content' field with extracted text content.

Returns:
    str: Concatenated text content preserving document structure and flow.
        Newlines separate text blocks to maintain readability and structure.

Raises:
    KeyError: If text blocks lack required 'content' field
    TypeError: If text_blocks is not a list or contains non-dictionary elements
    AttributeError: If text block content is not string-compatible

Examples:
    >>> text_blocks = [
    ...     {'content': 'Chapter 1: Introduction', 'bbox': [0, 0, 100, 20]},
    ...     {'content': 'This document describes...', 'bbox': [0, 25, 100, 45]}
    ... ]
    >>> text = processor._extract_native_text(text_blocks)
    >>> print(text)
    Chapter 1: Introduction
    This document describes...

Note:
    Preserves original text block ordering for document flow consistency.
    Newline separation maintains readability and paragraph structure.
    Empty or whitespace-only blocks are filtered to improve text quality.
    Result suitable for further processing including LLM optimization and entity extraction.
    """
```
* **Async:** False
* **Method:** True
* **Class:** PDFProcessor

## _extract_page_content

```python
async def _extract_page_content(self, page, page_num: int) -> Dict[str, Any]:
    """
    Extract comprehensive content from a single PDF page with detailed positioning.

Processes individual PDF pages to extract text blocks, embedded images, annotations,
vector graphics, and structural elements. Provides detailed positioning information,
confidence scores, and element classification for downstream processing stages.
Handles complex page layouts with overlapping elements and mixed content types.

Args:
    page: PyMuPDF page object representing a single PDF page.
        Must be a valid fitz.Page object with loaded content.
    page_num (int): Zero-based page number for identification and ordering.
        Used for element referencing and cross-page relationship analysis.

Returns:
    Dict[str, Any]: Comprehensive page content structure containing:
        - page_number (int): One-based page number for user reference
        - elements (List[Dict[str, Any]]): Structured elements with type, content, position
        - images (List[Dict[str, Any]]): Image metadata including size, colorspace, format
        - annotations (List[Dict[str, Any]]): Comments, highlights, and markup elements
        - text_blocks (List[Dict[str, Any]]): Text content with bounding boxes
        - drawings (List[Dict[str, Any]]): Vector graphics and drawing elements

Raises:
    AttributeError: If page object lacks required methods or properties
    MemoryError: If page contains extremely large images or complex graphics
    RuntimeError: If image extraction fails due to format or encoding issues
    ValueError: If page number is negative or exceeds document page count

Examples:
    >>> page_content = await processor._extract_page_content(page, 0)
    >>> print(f"Elements: {len(page_content['elements'])}")
    >>> print(f"Images: {len(page_content['images'])}")
    >>> for element in page_content['elements']:
    ...     print(f"{element['type']}: {element['content'][:50]}...")

Note:
    Text blocks preserve original formatting and positioning information.
    Images are extracted with metadata but not stored as binary data initially.
    Annotations include author information and modification timestamps.
    Vector graphics are catalogued but not rasterized unless specifically needed.
    """
```
* **Async:** True
* **Method:** True
* **Class:** PDFProcessor

## _get_processing_time

```python
def _get_processing_time(self, pdf_path) -> Dict[str, Any]:
    """
    Calculate total elapsed time for complete pipeline processing including all stages.

Computes total processing time from pipeline initiation through completion
including all 10 processing stages, error handling, and overhead operations.
Provides performance metrics for monitoring, optimization, and capacity planning
across different document types and sizes.

Args:
    None: Method accesses internal processing statistics and timestamps.

Returns:
    float: Total processing time in seconds with decimal precision.
        Includes all pipeline stages and overhead operations.

Raises:
    AttributeError: If processing statistics are not properly initialized
    ValueError: If timestamp calculations result in invalid time values

Examples:
    >>> processing_time = processor._get_processing_time()
    >>> print(f"Total processing time: {processing_time:.2f} seconds")
    >>> # Performance monitoring
    >>> if processing_time > 60.0:
    ...     print("Warning: Processing time exceeded threshold")

Note:
    Currently returns placeholder value for development purposes.
    Production implementation would track actual start and end timestamps.
    Processing time includes I/O operations, computation, and storage overhead.
    Metrics support performance optimization and capacity planning.
    """
```
* **Async:** False
* **Method:** True
* **Class:** PDFProcessor

## _get_processing_time

```python
def _get_processing_time(self) -> float:
    """
    Calculate total elapsed time for complete pipeline processing including all stages.

Computes total processing time from pipeline initiation through completion
including all 10 processing stages, error handling, and overhead operations.
Provides performance metrics for monitoring, optimization, and capacity planning
across different document types and sizes.

Args:
    None: Method accesses internal processing statistics and timestamps.

Returns:
    float: Total processing time in seconds with decimal precision.
        Includes all pipeline stages and overhead operations.

Raises:
    AttributeError: If processing statistics are not properly initialized
    ValueError: If timestamp calculations result in invalid time values

Examples:
    >>> processing_time = processor._get_processing_time()
    >>> print(f"Total processing time: {processing_time:.2f} seconds")
    >>> # Performance monitoring
    >>> if processing_time > 60.0:
    ...     print("Warning: Processing time exceeded threshold")

Note:
    Currently returns placeholder value for development purposes.
    Production implementation would track actual start and end timestamps.
    Processing time includes I/O operations, computation, and storage overhead.
    Metrics support performance optimization and capacity planning.
    """
```
* **Async:** False
* **Method:** True
* **Class:** PDFProcessor

## _get_quality_scores

```python
def _get_quality_scores(self) -> Dict[str, float]:
    """
    Generate quality assessment scores for processing stages and overall document quality.

Calculates comprehensive quality metrics for text extraction accuracy,
OCR confidence levels, entity extraction precision, and overall processing
quality. Provides quantitative assessment enabling quality control,
processing validation, and continuous improvement of pipeline performance.

Args:
    None: Method accesses internal processing statistics and quality metrics.

Returns:
    Dict[str, float]: Quality assessment scores containing:
        - text_extraction_quality (float): Native text extraction accuracy (0.0-1.0)
        - ocr_confidence (float): Average OCR confidence score (0.0-1.0)
        - entity_extraction_confidence (float): Entity extraction precision (0.0-1.0)
        - overall_quality (float): Weighted average of all quality metrics (0.0-1.0)

Raises:
    ValueError: If quality calculations result in invalid score ranges
    AttributeError: If required processing statistics are not available
    ZeroDivisionError: If quality calculations involve division by zero

Examples:
    >>> quality_scores = processor._get_quality_scores()
    >>> print(f"Overall quality: {quality_scores['overall_quality']:.2f}")
    >>> print(f"OCR confidence: {quality_scores['ocr_confidence']:.2f}")
    >>> # Quality-based filtering
    >>> if quality_scores['overall_quality'] < 0.8:
    ...     print("Warning: Low quality processing detected")

Note:
    Currently returns placeholder values for development purposes.
    Production implementation would calculate actual quality metrics.
    Quality scores enable automated quality control and threshold filtering.
    Metrics support continuous improvement and pipeline optimization.
    """
```
* **Async:** False
* **Method:** True
* **Class:** PDFProcessor

## _integrate_with_graphrag

```python
async def _integrate_with_graphrag(self, ipld_structure: Dict[str, Any], entities_and_relations: Dict[str, Any], embeddings: Dict[str, Any]) -> Dict[str, Any]:
    """
    Stage 8: Integrate processed content with GraphRAG knowledge system.

Combines IPLD structure, extracted entities, relationships, and embeddings
into a unified GraphRAG knowledge graph enabling semantic search, relationship
discovery, and cross-document analysis. Creates knowledge graph nodes with
content addressability and prepares data for natural language querying.

Args:
    ipld_structure (Dict[str, Any]): IPLD content structure with CIDs and references.
        Contains document hierarchy and content addressing information.
    entities_and_relations (Dict[str, Any]): Extracted entities and relationships.
        Provides knowledge graph nodes and edges for graph construction.
    embeddings (Dict[str, Any]): Vector embeddings for semantic search.
        Enables similarity-based querying and content clustering.

Returns:
    Dict[str, Any]: GraphRAG integration results containing:
        - document (Dict[str, Any]): Document metadata with ID and IPLD CID
        - knowledge_graph (KnowledgeGraph): Constructed knowledge graph object
        - entities (List[Entity]): Graph entities with embeddings and metadata
        - relationships (List[Relationship]): Graph relationships with types and weights

Raises:
    ValueError: If input data structures are incompatible or invalid
    RuntimeError: If GraphRAG integration fails due to system errors
    ImportError: If GraphRAG dependencies are not available
    StorageError: If knowledge graph storage operations fail

Examples:
    >>> graph_nodes = await processor._integrate_with_graphrag(
    ...     ipld_structure, entities_relations, embeddings
    ... )
    >>> kg = graph_nodes['knowledge_graph']
    >>> print(f"Graph with {len(kg.entities)} entities")
    >>> print(f"Document ID: {graph_nodes['document']['id']}")

Note:
    GraphRAG integration enables cross-document entity linking and relationship discovery.
    Knowledge graphs support both local and global entity resolution.
    IPLD integration provides content addressability for graph persistence.
    Results enable natural language querying and semantic exploration.
    """
```
* **Async:** True
* **Method:** True
* **Class:** PDFProcessor

## _optimize_for_llm

```python
async def _optimize_for_llm(self, decomposed_content: Dict[str, Any], ocr_results: Dict[str, Any]) -> Dict[str, Any]:
    """
    Stage 5: Optimize extracted content for large language model consumption.

Transforms raw PDF content into LLM-optimized format through intelligent chunking,
content structuring, summarization, and semantic type classification. Integrates
OCR results with native text and creates coherent, contextually meaningful
chunks suitable for embedding generation and semantic analysis.

Args:
    decomposed_content (Dict[str, Any]): Complete decomposed PDF content structure.
        Contains text blocks, images, annotations, and structural information.
    ocr_results (Dict[str, Any]): OCR processing results for embedded images.
        Provides extracted text content with confidence scores and positioning.

Returns:
    Dict[str, Any]: LLM-optimized content structure containing:
        - llm_document (LLMDocument): Structured document with chunks and metadata
        - chunks (List[LLMChunk]): Optimized content chunks with embeddings
        - summary (str): Document-level summary for context and retrieval
        - key_entities (List[Dict[str, Any]]): Extracted entities with types and positions

Raises:
    ValueError: If content structure is invalid or cannot be processed
    RuntimeError: If LLM optimization engine encounters fatal errors
    MemoryError: If document size exceeds available memory for processing
    ImportError: If required LLM optimization dependencies are missing

Examples:
    >>> optimized = await processor._optimize_for_llm(decomposed_content, ocr_results)
    >>> llm_doc = optimized['llm_document']
    >>> print(f"Chunks: {len(llm_doc.chunks)}")
    >>> print(f"Summary: {llm_doc.summary}")
    >>> print(f"Entities: {len(optimized['key_entities'])}")

Note:
    Chunking strategy preserves semantic coherence and context boundaries.
    OCR text is integrated seamlessly with native PDF text content.
    Entity extraction occurs during optimization for efficiency.
    Document embeddings are generated for similarity search and clustering.
    """
```
* **Async:** True
* **Method:** True
* **Class:** PDFProcessor

## _process_ocr

```python
async def _process_ocr(self, decomposed_content: Dict[str, Any]) -> Dict[str, Any]:
    """
    Stage 4: Process embedded images with multi-engine OCR for text extraction.

Applies optical character recognition to all embedded images within the PDF
using multiple OCR engines for accuracy comparison and confidence scoring.
Extracts text content, word-level positioning, and confidence metrics for
each recognized text element enabling comprehensive image-based content recovery.

Args:
    decomposed_content (Dict[str, Any]): Decomposed PDF content containing image data.
        Must include page-level image information with extraction metadata.

Returns:
    Dict[str, Any]: OCR processing results organized by page containing:
        - Page-keyed dictionary with OCR results for each image
        - For each image: text content, confidence score, engine used, word boxes
        - Aggregate confidence scores and text quality metrics

Raises:
    ImportError: If required OCR engine dependencies are not available
    RuntimeError: If OCR processing fails due to image format or corruption issues
    MemoryError: If images are too large for OCR processing memory limits
    TimeoutError: If OCR processing exceeds configured timeout limits

Examples:
    >>> ocr_results = await processor._process_ocr(decomposed_content)
    >>> for page_num, page_ocr in ocr_results.items():
    ...     for img_result in page_ocr:
    ...         print(f"Image {img_result['image_index']}: {img_result['text']}")
    ...         print(f"Confidence: {img_result['confidence']}")

Note:
    Currently implements mock OCR results for development purposes.
    Production implementation would integrate Tesseract, PaddleOCR, or cloud services.
    Multiple engines enable confidence comparison and accuracy validation.
    Word-level positioning supports precise content localization and extraction.
    """
```
* **Async:** True
* **Method:** True
* **Class:** PDFProcessor

## _setup_query_interface

```python
async def _setup_query_interface(self, graph_nodes: Dict[str, Any], cross_doc_relations: List[Dict[str, Any]]):
    """
    Stage 10: Configure natural language query interface for semantic search.

Initializes and configures the query engine with processed knowledge graph,
cross-document relationships, and semantic search capabilities. Sets up
natural language processing for query interpretation, graph traversal
algorithms, and result ranking for comprehensive document exploration.

Args:
    graph_nodes (Dict[str, Any]): GraphRAG integration results with knowledge graph.
        Contains complete knowledge graph structure with entities and relationships.
    cross_doc_relations (List[Dict[str, Any]]): Cross-document relationships discovered.
        Provides additional relationship context for enhanced query capabilities.

Returns:
    None: Method configures query interface without return value.
        Query engine is stored in class state for subsequent query processing.

Raises:
    ImportError: If query engine dependencies are not available
    RuntimeError: If query interface initialization fails due to system errors
    ValueError: If graph nodes or relationships have invalid structure
    ConfigurationError: If query engine configuration is incomplete or invalid

Examples:
    >>> await processor._setup_query_interface(graph_nodes, cross_relations)
    >>> # Query interface is now ready for natural language queries
    >>> # Example queries that would now be supported:
    >>> # "Find all documents mentioning John Smith"
    >>> # "Show relationships between ACME Corp and legal documents"
    >>> # "What entities are connected to contract negotiations?"

Note:
    Query interface supports both keyword-based and semantic search capabilities.
    Natural language processing enables intuitive query formulation.
    Graph traversal algorithms provide comprehensive relationship exploration.
    Results include relevance scoring and context-aware ranking.
    """
```
* **Async:** True
* **Method:** True
* **Class:** PDFProcessor

## _validate_and_analyze_pdf

```python
async def _validate_and_analyze_pdf(self, pdf_path: Path) -> Dict[str, Any]:
    """
    Stage 1: Validate PDF file integrity and extract basic metadata analysis.

Performs comprehensive validation of the input PDF file including existence checks,
file size validation, PDF format verification, and basic structural analysis.
Extracts essential metadata such as page count, file hash, and modification dates
for processing pipeline initialization and integrity verification.

Args:
    pdf_path (Path): Path object pointing to the PDF file for validation.
        Must be a valid pathlib.Path object with appropriate file permissions.

Returns:
    Dict[str, Any]: PDF validation and analysis results containing:
        - file_path (str): Absolute path to the validated PDF file
        - file_size (int): File size in bytes
        - page_count (int): Number of pages in the PDF document
        - file_hash (str): SHA-256 hash for integrity verification
        - analysis_timestamp (str): ISO format timestamp of analysis

Raises:
    FileNotFoundError: If the PDF file does not exist at the specified path
    ValueError: If the PDF file is empty, corrupted, or not a valid PDF format
    PermissionError: If insufficient permissions to read the PDF file
    RuntimeError: If PyMuPDF cannot open the PDF due to format issues

Examples:
    >>> pdf_info = await processor._validate_and_analyze_pdf(Path("document.pdf"))
    >>> print(f"Pages: {pdf_info['page_count']}")
    >>> print(f"Size: {pdf_info['file_size']} bytes")
    >>> print(f"Hash: {pdf_info['file_hash']}")

Note:
    Uses PyMuPDF for PDF format validation and page counting.
    File hash provides content addressability and deduplication capabilities.
    Analysis timestamp enables processing audit trails and cache validation.
    """
```
* **Async:** True
* **Method:** True
* **Class:** PDFProcessor

## process_pdf

```python
async def process_pdf(self, pdf_path: Union[str, Path], metadata: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Execute the complete PDF processing pipeline from input to query interface.

Processes a PDF document through all 10 pipeline stages: validation, decomposition,
IPLD structuring, OCR processing, LLM optimization, entity extraction, vector
embedding, GraphRAG integration, cross-document analysis, and query setup.
Returns comprehensive processing results with document metadata, entity counts,
and IPLD content identifiers.

Args:
    pdf_path (Union[str, Path]): Path to the PDF file to be processed.
        Must be a valid file path pointing to a readable PDF document.
        Supports both string paths and pathlib.Path objects.
    metadata (Optional[Dict[str, Any]], optional): Additional metadata for the document.
        Can include source information, processing priorities, custom tags,
        or domain-specific metadata. Merged with extracted document metadata.
        Defaults to None.

Returns:
    Dict[str, Any]: Comprehensive processing results containing:
        - status (str): Processing status ('success' or 'error')
        - document_id (str): Unique identifier for the processed document
        - ipld_cid (str): Content identifier for IPLD root node
        - entities_count (int): Number of extracted entities
        - relationships_count (int): Number of discovered relationships
        - cross_doc_relations (int): Number of cross-document relationships
        - processing_metadata (Dict[str, Any]): Processing statistics including:
            - pipeline_version (str): Version of the processing pipeline
            - processing_time (float): Total processing time in seconds
            - quality_scores (Dict[str, float]): Quality assessment metrics
            - stages_completed (int): Number of successfully completed stages
        For error cases, returns:
        - status (str): 'error'
        - error (str): Error message describing the failure
        - pdf_path (str): Original file path for debugging

Raises:
    FileNotFoundError: If the specified PDF file does not exist
    ValueError: If the PDF file is invalid, corrupted, or empty
    PermissionError: If insufficient permissions to read the PDF file
    RuntimeError: If critical pipeline stage fails and cannot be recovered
    TimeoutError: If processing exceeds configured timeout limits

Examples:
    >>> # Basic document processing
    >>> result = await processor.process_pdf("document.pdf")
    >>> if result['status'] == 'success':
    ...     print(f"Processed {result['entities_count']} entities")
    >>> 
    >>> # Processing with custom metadata
    >>> metadata = {
    ...     'source': 'legal_department',
    ...     'classification': 'confidential',
    ...     'priority': 'high'
    ... }
    >>> result = await processor.process_pdf("contract.pdf", metadata=metadata)
    >>> 
    >>> # Batch processing example
    >>> results = []
    >>> for pdf_file in pdf_directory.glob("*.pdf"):
    ...     result = await processor.process_pdf(pdf_file)
    ...     results.append(result)

Note:
    Processing is fully asynchronous and can handle large PDF files efficiently.
    All intermediate results are stored in IPLD for content addressability.
    Failed processing attempts are logged for debugging and error analysis.
    Cross-document relationships require multiple documents in the knowledge graph.
    """
```
* **Async:** True
* **Method:** True
* **Class:** PDFProcessor
