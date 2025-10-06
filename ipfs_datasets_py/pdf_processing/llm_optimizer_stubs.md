# Function and Class stubs from '/home/kylerose1946/ipfs_datasets_py/ipfs_datasets_py/pdf_processing/llm_optimizer.py'

Files last updated: 1752722887.5299017

Stub file last updated: 2025-07-16 20:28:21

## ChunkOptimizer

```python
class ChunkOptimizer:
    """
    Advanced text chunking optimization utility for intelligent boundary detection and content organization.

The ChunkOptimizer class provides sophisticated algorithms for determining optimal text chunk
boundaries that respect natural language structure, semantic coherence, and processing constraints.
It ensures that text chunks maintain narrative flow while adhering to token limits and
overlap requirements specified for downstream LLM processing.

This utility focuses on intelligent boundary detection that preserves sentence integrity,
paragraph structure, and semantic coherence while optimizing for LLM token windows.

Attributes:
    max_size (int): Maximum number of tokens allowed per chunk.
    overlap (int): Number of tokens to overlap between adjacent chunks.
    min_size (int): Minimum number of tokens required for a valid chunk.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## LLMChunk

```python
class LLMChunk(BaseModel):
    """
    Semantically optimized text chunk designed for effective LLM processing and analysis.

This Pydantic model represents an individual text chunk that has been optimized for language model
consumption, including the text content, vector embeddings, metadata, and contextual information.
Each chunk is designed to be semantically coherent, appropriately sized for LLM token limits,
and enriched with metadata to support various downstream NLP tasks.

LLMChunks maintain both the granular text content and the broader context within the document,
enabling effective processing while preserving document structure and narrative flow.

Attributes:
    content (str): The actual text content of the chunk, optimized for LLM processing.
    chunk_id (str): Unique identifier for this chunk within the document.
    source_page (int): Page number from the original document where this chunk originates.
    source_elements (list[str]): Type of source elements that contributed to this chunk.
    token_count (int): Number of tokens in the content using the specified tokenizer.
    semantic_types (str): Classification of the chunk content type:
        - 'text': Regular paragraph text
        - 'table': Structured table data
        - 'figure_caption': Figure or table caption
        - 'header': Section or chapter heading
        - 'mixed': Multiple content types combined
    relationships (List[str]): List of chunk IDs that are semantically or structurally
        related to this chunk, enabling cross-chunk reasoning and context.
    metadata (Dict[str, Any]): Additional chunk-specific metadata including semantic types,
        creation timestamp, and source element counts.
    embedding (Optional[np.ndarray]): Vector embedding representing the semantic content.
        Shape depends on the embedding model used. None if embeddings not generated.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## LLMChunkMetadata

```python
class LLMChunkMetadata(BaseModel):
    """
    Metadata container for LLM-processed document chunks.

This class stores metadata associated with document chunks that have been
processed for Large Language Model (LLM) consumption, including source
element information, semantic classification, and document location.

Attributes:
    source_elements (List[str]): List of source element identifiers or types
        that contributed to this chunk. Defaults to an empty list.
    semantic_types (set): Set of semantic type classifications for the chunk
        content (e.g., 'header', 'paragraph', 'table'). Defaults to an empty set.
    page_number (int): The page number in the source document where this
        chunk originates.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## LLMDocument

```python
class LLMDocument(BaseModel):
    """
    Comprehensive container for LLM-optimized document representation with semantic structure.

This dataclass represents the complete output of the LLM optimization process, containing
all necessary components for effective language model processing including semantically
chunked text, vector embeddings, extracted entities, document metadata, and quality metrics.
It serves as the primary data structure for downstream LLM operations like analysis,
summarization, question answering, and knowledge extraction.

The LLMDocument maintains both the granular chunk-level details and document-level
summaries, enabling both focused analysis of specific content sections and holistic
document understanding for comprehensive language model applications.

Attributes:
    document_id (str): Unique identifier for the document within the system.
    title (str): Human-readable title or name of the document.
    chunks (List[LLMChunk]): List of semantically optimized text chunks with embeddings.
        Each chunk contains content, metadata, embeddings, and relationship information.
    summary (str): Comprehensive document summary generated from the full content.
    key_entities (List[Dict[str, Any]]): Key entities extracted from the document content
        including text, type classification, and confidence scores.
    processing_metadata (Dict[str, Any]): Document processing and optimization metadata
        including timestamps, chunk counts, token counts, and model information.
    document_embedding (Optional[np.ndarray]): Document-level vector embedding representing
        the overall semantic content. Shape depends on the embedding model used.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## LLMDocumentProcessingMetadata

```python
class LLMDocumentProcessingMetadata(BaseModel):
    """
    Metadata model for tracking LLM document processing optimization details.

This class stores comprehensive information about the document processing
optimization performed by a Language Learning Model, including timing,
tokenization statistics, and model specifications.

Attributes:
    optimization_timestamp (float): Unix timestamp when the optimization was performed.
    chunk_count (NonNegativeInt): Number of document chunks processed during optimization.
    total_tokens (NonNegativeInt): Total number of tokens generated or processed.
    model_used (str): Identifier or name of the LLM model used for processing.
    tokenizer_used (str): Identifier or name of the tokenizer used for text preprocessing.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## LLMOptimizer

```python
class LLMOptimizer:
    """
    Advanced PDF content optimization engine specifically designed for Large Language Model consumption.

The LLMOptimizer class transforms decomposed PDF content into semantically rich, contextually
aware text chunks optimized for LLM processing. It performs intelligent text extraction,
semantic chunking, entity extraction, relationship discovery, and embedding generation
to create comprehensive LLMDocument objects that maximize the effectiveness of downstream
LLM operations while preserving document structure and meaning.

This class serves as the critical bridge between raw PDF content and LLM-ready data structures,
ensuring that the complexity and nuance of PDF documents are preserved while making them
accessible to language models for analysis, summarization, and knowledge extraction.

Key Features:
- Intelligent semantic text chunking with overlap optimization
- Context-aware entity extraction and relationship discovery
- Multi-modal embedding generation for semantic search
- Document structure preservation and metadata enrichment
- Token-aware chunking with configurable model compatibility
- Cross-chunk relationship establishment for narrative coherence
- Quality scoring and confidence tracking
- Performance monitoring and optimization metrics

Attributes:
    model_name (str): Sentence transformer model identifier for embedding generation.
    tokenizer_name (str): Tokenizer model identifier for accurate token counting.
    max_chunk_size (int): Maximum number of tokens allowed per text chunk.
    chunk_overlap (int): Number of tokens to overlap between adjacent chunks.
    min_chunk_size (int): Minimum number of tokens required for a valid chunk.
    embedding_model (SentenceTransformer): Loaded sentence transformer model for embeddings.
    tokenizer: Loaded tokenizer for token counting and text analysis.
    text_processor (TextProcessor): Utility for advanced text processing operations.
    chunk_optimizer (ChunkOptimizer): Utility for optimizing chunk boundaries and structure.

Usage Example:
    optimizer = LLMOptimizer(
        model_name="sentence-transformers/all-MiniLM-L6-v2",
        tokenizer_name="gpt-3.5-turbo",
        max_chunk_size=2048,
        chunk_overlap=200
    )
    
    # Optimize decomposed PDF content
    llm_document = await optimizer.optimize_for_llm(
        decomposed_content=pdf_content,
        document_metadata={"title": "Research Paper", "document_id": "doc123"}
    )
    
    # Access optimized chunks
    for chunk in llm_document.chunks:
        print(f"Chunk {chunk.chunk_id}: {chunk.token_count} tokens")

Notes:
    - Embedding models are loaded lazily to optimize memory usage
    - Token counting is performed using the specified tokenizer for accuracy
    - Chunk boundaries are optimized to respect sentence and paragraph breaks
    - Cross-chunk relationships preserve narrative flow and document structure
    - All processing is designed to be compatible with major LLM architectures
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## TextProcessor

```python
class TextProcessor:
    """
    Comprehensive text processing utility for advanced natural language operations and analysis.

The TextProcessor class provides a suite of sophisticated text processing capabilities
optimized for PDF content and LLM preparation. It handles sentence segmentation,
keyword extraction, language detection, text normalization, and various preprocessing
tasks essential for high-quality document analysis and optimization.

This utility serves as the foundation for text manipulation operations throughout
the PDF processing pipeline, ensuring consistent and high-quality text handling.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## __eq__

```python
def __eq__(self, other: Any) -> bool:
    """
    Check if this LLMChunk is equal to another object.

Two LLMChunk instances are considered equal if:
1. The other object is also an LLMChunk instance
2. Their embedding arrays are equal (using numpy array comparison)
3. All other fields in their model dictionaries are equal

Args:
    other (Any): The object to compare with this LLMChunk.
    
Returns:
    bool: True if the objects are equal, False otherwise.
    
Note:
    Embedding arrays are compared separately using a specialized numpy
    array equality function before comparing other model fields.
    """
```
* **Async:** False
* **Method:** True
* **Class:** LLMChunk

## __eq__

```python
def __eq__(self, other: Any) -> bool:
    """
    Check equality between two LLMDocument instances.

Compares all fields of the LLMDocument except for the document_embedding field,
which is handled separately using a specialized numpy array comparison function.
This approach ensures proper equality checking for numpy arrays while maintaining
efficient comparison for other fields.

Args:
    other (Any): The object to compare with this LLMDocument instance.

Returns:
    bool: True if both objects are LLMDocument instances and all fields
          (including embeddings) are equal, False otherwise.

Note:
    The document_embedding field is compared using _numpy_ndarrays_are_equal()
    to handle numpy array equality properly, while other fields are compared
    using standard dictionary equality after model serialization.
    """
```
* **Async:** False
* **Method:** True
* **Class:** LLMDocument

## __init__

```python
def __init__(self, model_name: str = "sentence-transformers/all-MiniLM-L6-v2", tokenizer_name: str = "gpt-3.5-turbo", max_chunk_size: int = 2048, chunk_overlap: int = 200, min_chunk_size: int = 100):
    """
    Initialize the LLM Optimizer with model configurations and processing parameters.

This constructor sets up the LLM optimization engine with configurable models and
chunking parameters. It initializes the embedding model, tokenizer, and text
processing utilities required for transforming PDF content into LLM-ready chunks.

Args:
    model_name (str, optional): Sentence transformer model identifier for generating
        vector embeddings. Must be a valid model name from the sentence-transformers
        library. Defaults to "sentence-transformers/all-MiniLM-L6-v2".
    tokenizer_name (str, optional): Tokenizer model identifier for accurate token
        counting. Supports both tiktoken (for GPT models) and HuggingFace tokenizers.
        Defaults to "gpt-3.5-turbo".
    max_chunk_size (int, optional): Maximum number of tokens allowed per text chunk.
        Must be positive integer. Recommended range: 512-4096 tokens.
        Defaults to 2048.
    chunk_overlap (int, optional): Number of tokens to overlap between adjacent chunks
        to maintain context continuity. Must be less than max_chunk_size.
        Defaults to 200.
    min_chunk_size (int, optional): Minimum number of tokens required for a valid chunk.
        Chunks smaller than this will be merged with adjacent chunks. Must be positive.
        Defaults to 100.

Attributes initialized:
    model_name (str): Stored sentence transformer model identifier.
    tokenizer_name (str): Stored tokenizer model identifier.
    max_chunk_size (int): Maximum tokens per chunk constraint.
    chunk_overlap (int): Token overlap between chunks setting.
    min_chunk_size (int): Minimum tokens per chunk requirement.
    embedding_model (SentenceTransformer): Loaded sentence transformer model instance.
    tokenizer: Loaded tokenizer instance (tiktoken or HuggingFace).
    text_processor (TextProcessor): Text processing utility for sentence splitting
        and keyword extraction.
    chunk_optimizer (ChunkOptimizer): Utility for optimizing chunk boundaries to
        respect natural language structure.

Raises:
    ValueError: If max_chunk_size <= min_chunk_size or if chunk_overlap >= max_chunk_size.
    ImportError: If required model dependencies are not available.
    OSError: If model files cannot be downloaded or loaded.

Examples:
    >>> # Default configuration for general use
    >>> optimizer = LLMOptimizer()
    
    >>> # Custom configuration for large context models
    >>> optimizer = LLMOptimizer(
    ...     model_name="sentence-transformers/all-mpnet-base-v2",
    ...     tokenizer_name="gpt-4",
    ...     max_chunk_size=4096,
    ...     chunk_overlap=400
    ... )
    
    >>> # Minimal overlap configuration for performance
    >>> optimizer = LLMOptimizer(
    ...     max_chunk_size=1024,
    ...     chunk_overlap=50,
    ...     min_chunk_size=200
    ... )

Note:
    Models are loaded lazily during initialization. If model loading fails,
    the optimizer will use fallback methods with reduced functionality.
    """
```
* **Async:** False
* **Method:** True
* **Class:** LLMOptimizer

## __init__

```python
def __init__(self, max_size: int, overlap: int, min_size: int):
    """
    Initialize the ChunkOptimizer with comprehensive chunking parameters and boundary detection settings.

This constructor establishes the fundamental parameters that govern text chunking behavior,
ensuring that all subsequent chunk optimization operations adhere to the specified
constraints for token limits, overlap requirements, and minimum chunk sizes. These
parameters form the foundation for intelligent boundary detection and content organization.

The initialization validates parameter relationships to ensure consistent and effective
chunking behavior that maintains document coherence while respecting LLM processing constraints.

Args:
    max_size (int): Maximum number of tokens allowed per text chunk. Must be a positive
        integer greater than min_size. Typical values range from 512 to 4096 tokens
        depending on the target LLM's context window and processing requirements.
    overlap (int): Number of tokens to overlap between adjacent chunks to maintain
        context continuity. Must be a positive integer less than max_size. Recommended
        range is 10-25% of max_size for optimal context preservation.
    min_size (int): Minimum number of tokens required for a valid chunk. Must be a
        positive integer less than max_size. Prevents creation of excessively small
        chunks that lack sufficient context for meaningful processing.

Attributes initialized:
    max_size (int): Stored maximum chunk size constraint for boundary calculations.
    overlap (int): Stored overlap requirement for context preservation between chunks.
    min_size (int): Stored minimum chunk size requirement for content adequacy validation.

Raises:
    ValueError: If max_size <= min_size or if overlap >= max_size (parameter validation).
    TypeError: If any parameter is not an integer type (type validation).
    AssertionError: If any parameter is negative or zero (constraint validation).

Examples:
    >>> # Standard configuration for GPT-3.5 compatibility
    >>> optimizer = ChunkOptimizer(max_size=2048, overlap=200, min_size=100)
    >>> print(f"Max: {optimizer.max_size}, Overlap: {optimizer.overlap}")
    
    >>> # High-overlap configuration for complex documents
    >>> optimizer = ChunkOptimizer(max_size=1024, overlap=256, min_size=50)
    >>> # 25% overlap for strong context preservation
    
    >>> # Minimal overlap for performance-focused processing
    >>> optimizer = ChunkOptimizer(max_size=4096, overlap=100, min_size=200)
    >>> # Large chunks with minimal overlap for speed
    """
```
* **Async:** False
* **Method:** True
* **Class:** ChunkOptimizer

## __str__

```python
def __str__(self) -> str:
    """
    Generate a concise string representation of the LLMChunk.

This method provides a human-readable summary of the document's key attributes,
including the document ID, title, number of chunks, and summary length.
It is designed to be informative yet concise for quick inspection.

Returns:
    str: String representation of the LLMDocument.
    """
```
* **Async:** False
* **Method:** True
* **Class:** LLMChunk

## __str__

```python
def __str__(self) -> str:
    """
    Generate a concise string representation of the LLMDocument.

This method provides a human-readable summary of the document's key attributes,
including the document ID, title, number of chunks, and summary length.
It is designed to be informative yet concise for quick inspection.

Returns:
    str: String representation of the LLMDocument.
    """
```
* **Async:** False
* **Method:** True
* **Class:** LLMDocument

## extract_keywords

```python
def extract_keywords(self, text: str, top_k: int = 20) -> List[str]:
    """
    Extract the most significant keywords and phrases from text using sophisticated frequency analysis and filtering.

This method performs advanced keyword extraction that identifies the most important
terms in a document by analyzing word frequency patterns while intelligently filtering
out common stop words and low-value terms. It employs regex-based tokenization to
extract meaningful words and applies frequency-based ranking to identify the most
significant content-bearing terms.

The extraction process combines multiple linguistic heuristics including minimum word
length requirements, stop word filtering, and frequency-based ranking to produce
a curated list of keywords that best represent the document's semantic content.

Args:
    text (str): Input text from which to extract keywords. Can be any length of
        content including full documents, paragraphs, or shorter text segments.
        Handles various text formats and encoding gracefully.
    top_k (int, optional): Maximum number of top-ranked keywords to return.
        Must be a positive integer. Larger values provide more comprehensive
        keyword coverage. Defaults to 20.

Returns:
    List[str]: Ordered list of the most significant keywords ranked by frequency
        and importance. Each keyword is a lowercase string with stop words removed.
        List length may be less than top_k if insufficient unique keywords exist.
        Returns empty list if no valid keywords are found.

Raises:
    ValueError: If top_k is not a positive integer (handled with default value).
    TypeError: If text is not a string (handled by converting to string).
    RuntimeError: If regex processing fails (handled with empty return).

Examples:
    >>> text = "Machine learning algorithms enable artificial intelligence systems to learn patterns from data and make predictions."
    >>> keywords = processor.extract_keywords(text, top_k=5)
    >>> print(keywords)
    >>> # ['machine', 'learning', 'algorithms', 'artificial', 'intelligence']
    
    >>> # Academic paper abstract
    >>> abstract = "This research investigates novel deep learning approaches for natural language processing tasks..."
    >>> keywords = processor.extract_keywords(abstract, top_k=10)
    >>> print(len(keywords))  # Up to 10 most relevant terms
    
    >>> # Short text handling
    >>> short_text = "Brief example."
    >>> keywords = processor.extract_keywords(short_text)
    >>> print(keywords)  # ['brief', 'example'] (excludes stop words)
    """
```
* **Async:** False
* **Method:** True
* **Class:** TextProcessor

## optimize_chunk_boundaries

```python
def optimize_chunk_boundaries(self, text: str, current_boundaries: List[int]) -> List[int]:
    """
    Analyze and optimize chunk boundary positions to respect natural language structure and semantic coherence.

This method performs sophisticated boundary optimization that moves chunk breaks from
arbitrary character positions to linguistically appropriate locations such as sentence
endings and paragraph breaks. It analyzes the input text to identify natural stopping
points and adjusts the provided boundary positions to align with these linguistic
structures while maintaining the overall chunking strategy.

The optimization process prioritizes paragraph boundaries over sentence boundaries,
as paragraph breaks typically represent stronger semantic divisions in the text.
When natural boundaries are not available within reasonable proximity, the method
preserves the original boundary positions to maintain chunk size constraints.

Args:
    text (str): The complete text content to analyze for optimal boundary positions.
        Should contain the full document or section being chunked, with original
        formatting and punctuation preserved for accurate boundary detection.
    current_boundaries (List[int]): List of current character positions where chunk
        boundaries are planned. These positions will be analyzed and potentially
        adjusted to align with natural language structures.

Returns:
    List[int]: Optimized boundary positions that respect natural language structure
        while maintaining reasonable proximity to the original positions. Boundaries
        are adjusted to align with sentence endings or paragraph breaks when possible,
        falling back to original positions when natural boundaries are not available.

Raises:
    ValueError: If text is empty or current_boundaries contain invalid positions.
    TypeError: If current_boundaries is not a list or contains non-integer values.
    IndexError: If boundary positions exceed text length (handled with boundary clamping).

Examples:
    >>> text = "First sentence. Second sentence.\n\nNew paragraph starts here. Another sentence."
    >>> boundaries = [25, 50]  # Arbitrary positions
    >>> optimizer = ChunkOptimizer(max_size=1024, overlap=100, min_size=50)
    >>> optimized = optimizer.optimize_chunk_boundaries(text, boundaries)
    >>> print(optimized)  # Adjusted to align with sentence/paragraph breaks
    
    >>> # Complex document with multiple paragraph breaks
    >>> long_text = "Para 1 content...\n\nPara 2 content...\n\nPara 3 content..."
    >>> rough_boundaries = [100, 200, 300]
    >>> optimized = optimizer.optimize_chunk_boundaries(long_text, rough_boundaries)
    >>> # Returns positions aligned with paragraph boundaries
    """
```
* **Async:** False
* **Method:** True
* **Class:** ChunkOptimizer

## optimize_for_llm

```python
async def optimize_for_llm(self, decomposed_content: Dict[str, Any], document_metadata: Dict[str, Any]) -> LLMDocument:
    """
    Transform decomposed PDF content into an LLM-optimized document with semantic structure.

This method performs the complete optimization pipeline, converting raw PDF decomposition
output into a comprehensive LLMDocument optimized for language model consumption. The
process includes text extraction, semantic chunking, embedding generation, entity
extraction, and relationship establishment to create a rich, structured representation.

The optimization preserves document structure while making content accessible to LLMs
through intelligent chunking, token-aware segmentation, and contextual enrichment.

Args:
    decomposed_content (Dict[str, Any]): Content from PDF decomposition stage containing
        pages, elements, metadata, and structure information. Expected structure:
        {
            'pages': [{'elements': [...], 'metadata': {...}}, ...],
            'metadata': {...},
            'structure': {...}
        }
    document_metadata (Dict[str, Any]): Document metadata and properties including
        document_id, title, author, creation_date, and other document-level information.

Returns:
    LLMDocument: Comprehensive container with optimized chunks, embeddings, and metadata
        containing document_id, title, chunks (List[LLMChunk]), summary, key_entities,
        document_embedding, and processing_metadata.

Raises:
    ValueError: If decomposed_content is missing required structure or contains invalid data.
    TypeError: If input parameters are not of expected types.
    RuntimeError: If optimization process fails due to model or processing errors.
    MemoryError: If document is too large for available memory during processing.

Examples:
    >>> decomposed_content = {
    ...     'pages': [{'elements': [...], 'metadata': {...}}],
    ...     'metadata': {'page_count': 10},
    ...     'structure': {'sections': [...]}
    ... }
    >>> metadata = {'document_id': 'doc123', 'title': 'Research Paper'}
    >>> llm_doc = await optimizer.optimize_for_llm(decomposed_content, metadata)
    >>> print(f"Created {len(llm_doc.chunks)} chunks")
    
    >>> # Access optimized content
    >>> for chunk in llm_doc.chunks:
    ...     print(f"Chunk {chunk.chunk_id}: {chunk.token_count} tokens")
    >>> print(f"Document summary: {llm_doc.summary[:100]}...")
    """
```
* **Async:** True
* **Method:** True
* **Class:** LLMOptimizer

## split_sentences

```python
def split_sentences(self, text: str) -> List[str]:
    """
    Intelligently split text into individual sentences using advanced linguistic rules and pattern recognition.

This method performs sophisticated sentence boundary detection that goes beyond simple
period-based splitting to handle complex sentence structures, abbreviations, and
edge cases commonly found in academic and professional documents. It uses regex
patterns to identify sentence terminators while preserving the integrity of
individual sentence units for downstream processing.

The splitting algorithm recognizes multiple sentence termination patterns including
periods, exclamation marks, and question marks, while handling edge cases such as
decimal numbers, abbreviations, and ellipses that might contain these characters
without indicating sentence boundaries.

Args:
    text (str): Input text to split into individual sentences. Can contain multiple
        paragraphs, various punctuation patterns, and complex sentence structures.
        Handles empty strings and None values gracefully.

Returns:
    List[str]: List of individual sentences with leading/trailing whitespace stripped.
        Each element represents a complete sentence unit. Empty sentences are filtered
        out. Maintains original sentence content and internal formatting.

Raises:
    TypeError: If input text is not a string type (logged as warning, returns empty list).
    ValueError: If regex processing fails due to malformed input (handled gracefully).

Examples:
    >>> text = "This is sentence one. This is sentence two! Is this sentence three?"
    >>> sentences = processor.split_sentences(text)
    >>> print(sentences)
    >>> # ['This is sentence one', 'This is sentence two', 'Is this sentence three']
    
    >>> # Complex text with abbreviations and numbers
    >>> complex_text = "Dr. Smith earned his Ph.D. in 1995. The study covered 3.14159 subjects."
    >>> sentences = processor.split_sentences(complex_text)
    >>> print(len(sentences))  # 2 (handles abbreviations correctly)
    
    >>> # Empty and edge case handling
    >>> empty_sentences = processor.split_sentences("")
    >>> print(empty_sentences)  # []

Note:
    Current implementation uses basic regex patterns for sentence detection.
    This can be enhanced with NLTK's PunktSentenceTokenizer or spaCy's
    sentence segmentation for higher accuracy with complex academic texts.
    The method preserves sentence content while normalizing whitespace.
    """
```
* **Async:** False
* **Method:** True
* **Class:** TextProcessor

## validate_and_copy_embedding

```python
@field_validator("document_embedding")
@classmethod
def validate_and_copy_embedding(cls, v: Optional[np.ndarray]) -> Optional[np.ndarray]:
    """
    Validates and creates a copy of the document embedding array.

This validator ensures that the document_embedding field is either None or a valid
numpy array. If a valid numpy array is provided, it creates and returns a copy of
the array to prevent external modifications to the original data.

Args:
    v (Optional[np.ndarray]): The document embedding to validate. Can be None
        or a numpy array containing the embedding vectors.

Returns:
    Optional[np.ndarray]: None if input is None, otherwise a copy of the input
        numpy array.

Raises:
    ValueError: If the input is not None and not a numpy array.
    """
```
* **Async:** False
* **Method:** True
* **Class:** LLMDocument

## validate_content

```python
@field_validator("content")
def validate_content(cls, v) -> str:
    """
    Validates the content field to ensure it meets required criteria.

This validator ensures that the content field is not None and is of string type.
It is typically used with Pydantic models to enforce data validation rules.

Args:
    cls: The class being validated (automatically provided by Pydantic)
    v: The value being validated for the content field

Returns:
    str: The validated content value if it passes all checks

Raises:
    ValueError: If content is None or not a string type

Example:
    This validator will automatically run when a Pydantic model with a 
    content field is instantiated or when the field is set.
    """
```
* **Async:** False
* **Method:** True
* **Class:** LLMChunk
