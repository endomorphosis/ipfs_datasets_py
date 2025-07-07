# Function and Class stubs from '/home/kylerose1946/ipfs_datasets_py/ipfs_datasets_py/pdf_processing/llm_optimizer.py'

Files last updated: 1751884324.7225378

Stub file last updated: 2025-07-07 04:13:22

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
@dataclass
class LLMChunk:
    """
    Semantically optimized text chunk designed for effective LLM processing and analysis.

This dataclass represents an individual text chunk that has been optimized for language model
consumption, including the text content, vector embeddings, metadata, and contextual information.
Each chunk is designed to be semantically coherent, appropriately sized for LLM token limits,
and enriched with metadata to support various downstream NLP tasks.

LLMChunks maintain both the granular text content and the broader context within the document,
enabling effective processing while preserving document structure and narrative flow.

Attributes:
    content (str): The actual text content of the chunk, optimized for LLM processing.
    chunk_id (str): Unique identifier for this chunk within the document.
    source_page (int): Page number from the original document where this chunk originates.
    source_element (str): Type of source element that contributed to this chunk.
    token_count (int): Number of tokens in the content using the specified tokenizer.
    semantic_type (str): Classification of the chunk content type:
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

## LLMDocument

```python
@dataclass
class LLMDocument:
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

## __init__

```python
def __init__(self, model_name: str = "sentence-transformers/all-MiniLM-L6-v2", tokenizer_name: str = "gpt-3.5-turbo", max_chunk_size: int = 2048, chunk_overlap: int = 200, min_chunk_size: int = 100):
    """
    Initialize the LLM optimizer.

Args:
    model_name: Sentence transformer model for embeddings
    tokenizer_name: Tokenizer for token counting
    max_chunk_size: Maximum tokens per chunk
    chunk_overlap: Token overlap between chunks
    min_chunk_size: Minimum tokens per chunk
    """
```
* **Async:** False
* **Method:** True
* **Class:** LLMOptimizer

## __init__

```python
def __init__(self, max_size: int, overlap: int, min_size: int):
```
* **Async:** False
* **Method:** True
* **Class:** ChunkOptimizer

## _count_tokens

```python
def _count_tokens(self, text: str) -> int:
    """
    Count tokens in text using the configured tokenizer.
    """
```
* **Async:** False
* **Method:** True
* **Class:** LLMOptimizer

## _create_chunk

```python
async def _create_chunk(self, content: str, chunk_id: int, page_num: int, metadata: Dict[str, Any]) -> LLMChunk:
    """
    Create a single LLM chunk with metadata.
    """
```
* **Async:** True
* **Method:** True
* **Class:** LLMOptimizer

## _create_optimal_chunks

```python
async def _create_optimal_chunks(self, structured_text: Dict[str, Any], decomposed_content: Dict[str, Any]) -> List[LLMChunk]:
    """
    Create semantically optimal chunks for LLM processing.
    """
```
* **Async:** True
* **Method:** True
* **Class:** LLMOptimizer

## _establish_chunk_relationships

```python
def _establish_chunk_relationships(self, chunks: List[LLMChunk]) -> List[LLMChunk]:
    """
    Establish semantic relationships between chunks.
    """
```
* **Async:** False
* **Method:** True
* **Class:** LLMOptimizer

## _extract_key_entities

```python
async def _extract_key_entities(self, structured_text: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Extract key entities and concepts from the document.
    """
```
* **Async:** True
* **Method:** True
* **Class:** LLMOptimizer

## _extract_structured_text

```python
async def _extract_structured_text(self, decomposed_content: Dict[str, Any]) -> Dict[str, Any]:
    """
    Extract text content while preserving structure and context.
    """
```
* **Async:** True
* **Method:** True
* **Class:** LLMOptimizer

## _generate_document_embedding

```python
async def _generate_document_embedding(self, summary: str, structured_text: Dict[str, Any]) -> Optional[np.ndarray]:
    """
    Generate a document-level embedding.
    """
```
* **Async:** True
* **Method:** True
* **Class:** LLMOptimizer

## _generate_document_summary

```python
async def _generate_document_summary(self, structured_text: Dict[str, Any]) -> str:
    """
    Generate a comprehensive document summary.
    """
```
* **Async:** True
* **Method:** True
* **Class:** LLMOptimizer

## _generate_embeddings

```python
async def _generate_embeddings(self, chunks: List[LLMChunk]) -> List[LLMChunk]:
    """
    Generate embeddings for all chunks.
    """
```
* **Async:** True
* **Method:** True
* **Class:** LLMOptimizer

## _get_chunk_overlap

```python
def _get_chunk_overlap(self, content: str) -> str:
    """
    Get overlap content for chunk continuity.
    """
```
* **Async:** False
* **Method:** True
* **Class:** LLMOptimizer

## _initialize_models

```python
def _initialize_models(self):
    """
    Initialize embedding and tokenization models.
    """
```
* **Async:** False
* **Method:** True
* **Class:** LLMOptimizer

## extract_keywords

```python
def extract_keywords(self, text: str, top_k: int = 20) -> List[str]:
    """
    Extract the most important keywords and phrases from text using frequency analysis.

Args:
    text (str): Input text to extract keywords from.
    top_k (int): Maximum number of keywords to return. Defaults to 20.
    
Returns:
    List[str]: List of top keywords ranked by frequency, excluding common stop words.
    """
```
* **Async:** False
* **Method:** True
* **Class:** TextProcessor

## optimize_chunk_boundaries

```python
def optimize_chunk_boundaries(self, text: str, current_boundaries: List[int]) -> List[int]:
    """
    Analyze and optimize chunk boundary positions to respect natural language structure.

Args:
    text (str): The full text content to analyze for optimal boundaries.
    current_boundaries (List[int]): List of current boundary positions to optimize.
    
Returns:
    List[int]: Optimized boundary positions that respect sentence and paragraph breaks
              while maintaining size constraints and overlap requirements.
    """
```
* **Async:** False
* **Method:** True
* **Class:** ChunkOptimizer

## optimize_for_llm

```python
async def optimize_for_llm(self, decomposed_content: Dict[str, Any], document_metadata: Dict[str, Any]) -> LLMDocument:
    """
    Optimize decomposed PDF content for LLM consumption.

Args:
    decomposed_content: Content from PDF decomposition stage
    document_metadata: Document metadata and properties
    
Returns:
    LLMDocument with optimized chunks and embeddings
    """
```
* **Async:** True
* **Method:** True
* **Class:** LLMOptimizer

## split_sentences

```python
def split_sentences(self, text: str) -> List[str]:
    """
    Intelligently split text into individual sentences using advanced linguistic rules.

Args:
    text (str): Input text to split into sentences.
    
Returns:
    List[str]: List of individual sentences with whitespace stripped.
    """
```
* **Async:** False
* **Method:** True
* **Class:** TextProcessor
