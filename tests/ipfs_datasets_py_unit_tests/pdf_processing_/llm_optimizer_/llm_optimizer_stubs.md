```python
"""
LLM Optimization Module for PDF Processing Pipeline

Optimizes extracted content for LLM consumption by:
- Chunking text into optimal sizes
- Preserving semantic relationships
- Generating structured summaries
- Creating context-aware embeddings
- Handling multi-modal content
"""
import asyncio
import logging
from typing import Dict, List, Any, Optional
from dataclasses import dataclass


@dataclass
class LLMChunk:
    """
    Represents an optimized text chunk prepared for Large Language Model processing.

    An LLMChunk is a segment of document content that has been sized, structured,
    and enriched specifically for consumption by language models. Each chunk
    maintains semantic coherence while respecting token limits and preserving
    relationships to other chunks within the document.

    Attributes:
        content (str): The actual text content of the chunk, cleaned and 
            formatted for optimal LLM processing.
        chunk_id (str): Unique identifier for this chunk within the document,
            typically formatted as "chunk_XXXX" where XXXX is a zero-padded number.
        source_page (int): Page number from the original PDF document where
            this chunk's content originated.
        source_element (str): Type or identifier of the source element(s) that
            contributed to this chunk (e.g., 'paragraph', 'table', 'header').
        token_count (int): Number of tokens in the content as calculated by
            the configured tokenizer, used for chunk size management.
        semantic_type (str): Primary semantic classification of the chunk content.
            Common types include:
            - 'text': Regular paragraph content
            - 'table': Tabular data and structures
            - 'figure_caption': Image and figure descriptions
            - 'header': Section titles and headings
            - 'mixed': Content spanning multiple semantic types
        relationships (List[str]): List of chunk IDs that have semantic or
            structural relationships to this chunk, enabling context-aware
            processing and cross-referencing.
        metadata (Dict[str, Any]): Additional processing metadata including
            creation timestamps, source element counts, and semantic type
            distributions within the chunk.
        embedding (Optional[np.ndarray]): High-dimensional vector representation
            of the chunk content for semantic similarity calculations and
            retrieval operations. Defaults to None if not computed.

    Example:
        >>> chunk = LLMChunk(
        ...     content="The quarterly results show significant growth...",
        ...     chunk_id="chunk_0015",
        ...     source_page=3,
        ...     source_element="paragraph",
        ...     token_count=245,
        ...     semantic_type="text",
        ...     relationships=["chunk_0014", "chunk_0016"],
        ...     metadata={"creation_timestamp": 1625097600.0}
        ... )
    """

@dataclass
class LLMDocument:
    """
    Complete document representation optimized for Large Language Model consumption.

    An LLMDocument contains all processed and optimized content from a source PDF,
    structured for efficient LLM processing, retrieval, and analysis. It serves
    as the final output of the PDF-to-LLM optimization pipeline.

    Attributes:
        document_id (str): Unique identifier for the document within the system,
            used for tracking and referencing across processing stages.
        title (str): Document title extracted from metadata or content, providing
            a human-readable identifier for the document.
        chunks (List[LLMChunk]): Complete list of optimized text chunks that
            comprise the document content, ordered sequentially by appearance.
        summary (str): Comprehensive document summary generated through extractive
            summarization techniques, capturing key themes and information.
        key_entities (List[Dict[str, Any]]): List of important entities extracted
            from the document, including people, organizations, dates, and concepts.
            Each entity dictionary contains 'text', 'type', and 'confidence' keys.
        processing_metadata (Dict[str, Any]): Metadata about the optimization
            process including timestamps, chunk counts, token statistics, and
            model configurations used during processing.
        document_embedding (Optional[np.ndarray]): Document-level vector
            representation combining summary and key content for similarity
            calculations and document clustering. Defaults to None if not computed.

    Example:
        >>> document = LLMDocument(
        ...     document_id="doc_2023_q3_report",
        ...     title="Q3 Financial Results",
        ...     chunks=[chunk1, chunk2, chunk3],
        ...     summary="The third quarter showed strong performance...",
        ...     key_entities=[{"text": "Q3 2023", "type": "date", "confidence": 0.9}],
        ...     processing_metadata={"chunk_count": 3, "total_tokens": 1250}
        ... )
    """

class LLMOptimizer:
    """
    Transforms PDF content into optimized representations for Large Language Model processing.

    The LLMOptimizer serves as the primary interface for converting decomposed PDF
    content into structured, tokenized, and embedded formats suitable for LLM
    consumption. It handles text chunking, semantic analysis, embedding generation,
    and relationship mapping to create comprehensive document representations.

    This class manages the complete optimization pipeline from raw PDF decomposition
    output to final LLMDocument objects ready for downstream processing, search,
    and analysis tasks.

    Attributes:
        model_name (str): Identifier for the sentence transformer model used for
            generating text embeddings and semantic representations.
        tokenizer_name (str): Identifier for the tokenization model used for
            accurate token counting and chunk size management.
        max_chunk_size (int): Maximum number of tokens allowed in a single chunk,
            ensuring compatibility with LLM context window limits.
        chunk_overlap (int): Number of tokens to overlap between adjacent chunks,
            maintaining context continuity across chunk boundaries.
        min_chunk_size (int): Minimum number of tokens required for a valid chunk,
            preventing creation of inefficiently small text segments.
        embedding_model (SentenceTransformer): Initialized sentence transformer
            model for generating high-quality text embeddings.
        tokenizer: Configured tokenizer instance for accurate token counting,
            supporting both tiktoken and HuggingFace tokenizers.
        text_processor (TextProcessor): Utility instance for text processing
            operations including sentence splitting and keyword extraction.
        chunk_optimizer (ChunkOptimizer): Utility instance for optimizing chunk
            boundaries to respect semantic and structural text divisions.

    Example:
        >>> optimizer = LLMOptimizer(
        ...     model_name="sentence-transformers/all-MiniLM-L6-v2",
        ...     tokenizer_name="gpt-3.5-turbo",
        ...     max_chunk_size=2048,
        ...     chunk_overlap=200
        ... )
        >>> optimized_doc = await optimizer.optimize_for_llm(
        ...     decomposed_content, document_metadata
        ... )
    """
    
    def __init__(self, 
                 model_name: str = "sentence-transformers/all-MiniLM-L6-v2",
                 tokenizer_name: str = "gpt-3.5-turbo",
                 max_chunk_size: int = 2048,
                 chunk_overlap: int = 200,
                 min_chunk_size: int = 100):
        """
        Initialize the LLM optimizer with specified models and chunking parameters.

        Configures the optimization pipeline with embedding models, tokenizers, and
        chunk size parameters. Initializes all required components for processing
        PDF content into LLM-ready formats.

        Args:
            model_name (str): Sentence transformer model identifier for generating
                text embeddings. Should be a valid model name from the sentence-transformers
                library or HuggingFace model hub. Defaults to "sentence-transformers/all-MiniLM-L6-v2".
            tokenizer_name (str): Tokenizer model identifier for accurate token counting.
                Supports tiktoken model names (e.g., "gpt-3.5-turbo") or HuggingFace
                tokenizer names. Defaults to "gpt-3.5-turbo".
            max_chunk_size (int): Maximum number of tokens per chunk, should align
                with target LLM context window capabilities. Defaults to 2048.
            chunk_overlap (int): Number of tokens to overlap between consecutive
                chunks for maintaining context continuity. Defaults to 200.
            min_chunk_size (int): Minimum viable chunk size in tokens, preventing
                creation of inefficiently small chunks. Defaults to 100.

        Raises:
            Exception: If model initialization fails, falls back to basic tokenization
                without embedding capabilities.

        Example:
            >>> optimizer = LLMOptimizer(
            ...     model_name="sentence-transformers/paraphrase-MiniLM-L6-v2",
            ...     tokenizer_name="gpt-4",
            ...     max_chunk_size=4096,
            ...     chunk_overlap=400
            ... )
        """
        
    def _initialize_models(self):
        """
        Initialize embedding and tokenization models for the optimization pipeline.

        Loads and configures the sentence transformer model for embedding generation
        and the tokenizer for accurate token counting. Handles different tokenizer
        types including tiktoken for OpenAI models and HuggingFace tokenizers.

        Sets up fallback mechanisms if model loading fails, ensuring the optimizer
        can continue with reduced functionality rather than complete failure.

        Raises:
            Exception: Logs errors during model initialization but continues with
                fallback tokenization methods to maintain system stability.

        Note:
            - tiktoken is used for OpenAI model tokenizers (detected by "gpt" in name)
            - HuggingFace AutoTokenizer is used for other model types
            - Embedding model failures result in None assignment, disabling embedding features
            - Tokenizer failures result in approximate token counting using word-based estimation
        """

    async def optimize_for_llm(self, 
                              decomposed_content: Dict[str, Any],
                              document_metadata: Dict[str, Any]) -> LLMDocument:
        """
        Transform decomposed PDF content into a comprehensive LLM-optimized document.

        Orchestrates the complete optimization pipeline, converting raw PDF decomposition
        output into structured, chunked, and embedded content ready for LLM processing.
        This includes text extraction, summarization, chunking, embedding generation,
        entity extraction, and relationship mapping.

        Args:
            decomposed_content (Dict[str, Any]): Content dictionary from PDF decomposition
                stage containing pages, elements, metadata, and structural information.
                Expected structure includes:
                - 'pages': List of page dictionaries with elements and content
                - 'metadata': Document-level metadata and properties
                - 'structure': Structural hierarchy and organization information
            document_metadata (Dict[str, Any]): Additional document metadata including
                document_id, title, processing parameters, and source information.

        Returns:
            LLMDocument: Fully optimized document object containing:
                - Segmented and embedded text chunks
                - Document-level summary and embedding
                - Extracted entities and key concepts
                - Inter-chunk relationships and metadata
                - Processing statistics and timestamps

        Example:
            >>> decomposed = {
            ...     'pages': [{'elements': [...], 'page_num': 1}],
            ...     'metadata': {'title': 'Report', 'author': 'John Doe'}
            ... }
            >>> metadata = {'document_id': 'doc_001', 'title': 'Annual Report'}
            >>> optimized = await optimizer.optimize_for_llm(decomposed, metadata)
            >>> print(f"Created {len(optimized.chunks)} chunks")
        """

    async def _extract_structured_text(self, decomposed_content: Dict[str, Any]) -> Dict[str, Any]:
        """
        Extract and structure text content while preserving document organization and context.

        Processes decomposed PDF content to create a structured text representation
        that maintains the original document's semantic organization. Extracts text
        elements with their positional, stylistic, and contextual information for
        optimal chunking and processing.

        Args:
            decomposed_content (Dict[str, Any]): Decomposed PDF content containing
                page-level elements, metadata, and structural information from the
                PDF decomposition stage.

        Returns:
            Dict[str, Any]: Structured text representation containing:
                - 'pages': List of page objects with extracted text elements
                - 'metadata': Preserved document metadata from decomposition
                - 'structure': Document structure and organization information
                Each page contains elements with content, type, position, style,
                and confidence information for semantic processing.

        Note:
            - Only processes elements with type 'text' from the decomposed content
            - Preserves element subtypes (paragraph, header, etc.) for semantic classification
            - Maintains positional and style information for context-aware chunking
            - Aggregates page-level full text for summary generation and analysis
        """

    async def _generate_document_summary(self, structured_text: Dict[str, Any]) -> str:
        """
        Generate a comprehensive extractive summary of the document content.

        Creates a concise but informative summary by analyzing sentence importance
        based on position, keyword frequency, and structural characteristics. Uses
        extractive summarization to preserve original phrasing while identifying
        the most significant content across the document.

        Args:
            structured_text (Dict[str, Any]): Structured text representation from
                the document containing pages with text elements and full text
                content for analysis and summarization.

        Returns:
            str: Document summary composed of the highest-scoring sentences that
                capture key themes, information, and conclusions. Summary length
                is optimized for overview purposes while maintaining coherence
                and informativeness.

        Note:
            - Analyzes first 50 sentences for computational efficiency
            - Scoring considers sentence position (earlier sentences weighted higher)
            - Keyword frequency analysis identifies topically relevant sentences
            - Length optimization favors sentences between 10-30 words
            - Returns top 5 sentences ordered by importance score
        """

    async def _create_optimal_chunks(self, 
                                   structured_text: Dict[str, Any],
                                   decomposed_content: Dict[str, Any]) -> List[LLMChunk]:
        """
        Create semantically coherent chunks optimized for LLM processing and understanding.

        Segments document content into chunks that respect token limits while maintaining
        semantic coherence and contextual relationships. Considers element types,
        content boundaries, and structural organization to create chunks that preserve
        meaning and enable effective LLM processing.

        Args:
            structured_text (Dict[str, Any]): Structured text representation with
                elements organized by page and semantic type for intelligent chunking.
            decomposed_content (Dict[str, Any]): Original decomposed content providing
                additional context and metadata for chunk optimization decisions.

        Returns:
            List[LLMChunk]: List of optimized text chunks, each containing:
                - Content sized within token limits
                - Semantic type classification
                - Source page and element information
                - Inter-chunk relationships
                - Processing metadata and statistics
                Chunks are ordered sequentially and include overlap for context continuity.

        Note:
            - Respects maximum token limits while maintaining semantic boundaries
            - Implements chunk overlap for context preservation across boundaries
            - Establishes relationships between sequential and related chunks
            - Classifies chunks by primary semantic type (text, table, header, mixed)
            - Optimizes boundaries to avoid breaking sentences or paragraphs mid-content
        """

    async def _create_chunk(self, 
                          content: str, 
                          chunk_id: int, 
                          page_num: int,
                          metadata: Dict[str, Any]) -> LLMChunk:
        """
        Create a single LLM chunk object with complete metadata and semantic classification.

        Constructs an individual LLMChunk from content and metadata, calculating
        token counts, determining semantic types, and preparing the chunk for
        embedding generation and relationship mapping.

        Args:
            content (str): Text content for the chunk, cleaned and formatted
                for LLM processing.
            chunk_id (int): Numeric identifier for generating unique chunk IDs
                within the document scope.
            page_num (int): Source page number from the original PDF document
                where this chunk's content originated.
            metadata (Dict[str, Any]): Chunk metadata including semantic types,
                source elements, and processing information for classification
                and relationship establishment.

        Returns:
            LLMChunk: Complete chunk object with content, metadata, semantic
                classification, and preparation for embedding generation.
                Relationships list is initialized empty for later population.

        Note:
            - Chunk IDs are formatted as "chunk_XXXX" with zero-padding
            - Semantic type is determined from metadata with priority rules
            - Token count is calculated using the configured tokenizer
            - Metadata includes creation timestamp and source element statistics
        """

    def _establish_chunk_relationships(self, chunks: List[LLMChunk]) -> List[LLMChunk]:
        """
        Establish semantic and structural relationships between document chunks.

        Analyzes chunk sequences, page organization, and content relationships to
        create connections that enable context-aware processing and cross-referencing.
        Relationships support LLM understanding of document flow and structure.

        Args:
            chunks (List[LLMChunk]): List of document chunks requiring relationship
                mapping and connection establishment for enhanced contextual processing.

        Returns:
            List[LLMChunk]: Same chunks with populated relationship lists containing
                IDs of related chunks based on sequential order, page organization,
                and semantic proximity.

        Note:
            - Sequential relationships connect adjacent chunks in document order
            - Same-page relationships connect chunks from identical source pages
            - Relationship lists are limited to prevent performance degradation
            - All relationships are bidirectional for comprehensive context mapping
        """

    async def _generate_embeddings(self, chunks: List[LLMChunk]) -> List[LLMChunk]:
        """
        Generate high-dimensional vector embeddings for all document chunks.

        Creates semantic vector representations of chunk content using sentence
        transformers, enabling similarity calculations, semantic search, and
        clustering operations. Processes chunks in batches for computational
        efficiency while handling potential failures gracefully.

        Args:
            chunks (List[LLMChunk]): List of chunks requiring embedding generation
                for semantic analysis and similarity operations.

        Returns:
            List[LLMChunk]: Same chunks with populated embedding arrays containing
                high-dimensional vectors representing semantic content. Chunks
                without successful embedding generation retain None values.

        Note:
            - Processes chunks in batches of 32 for optimal performance
            - Handles embedding failures gracefully, continuing with remaining batches
            - Returns numpy arrays for compatibility with similarity calculations
            - Skips embedding generation entirely if no embedding model is available
        """

    async def _extract_key_entities(self, structured_text: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Extract important entities and concepts from document content for knowledge representation.

        Identifies and extracts key entities including dates, email addresses, and
        organizations using pattern matching and text analysis. Provides structured
        entity information for knowledge graph construction and content analysis.

        Args:
            structured_text (Dict[str, Any]): Structured document text containing
                page-level content for entity extraction and analysis.

        Returns:
            List[Dict[str, Any]]: List of entity dictionaries, each containing:
                - 'text': The extracted entity text
                - 'type': Entity classification (date, email, organization)
                - 'confidence': Reliability score for the extraction
                Limited quantities per type to prevent overwhelming downstream processing.

        Note:
            - Date extraction handles multiple common formats (MM/DD/YYYY, YYYY-MM-DD)
            - Email extraction uses RFC-compliant pattern matching
            - Organization detection identifies capitalized multi-word phrases
            - Results are limited per type (dates: 10, emails: 5, organizations: 10)
            - Confidence scores reflect extraction method reliability
        """

    async def _generate_document_embedding(self, 
                                         summary: str, 
                                         structured_text: Dict[str, Any]) -> Optional[np.ndarray]:
        """
        Generate a document-level embedding representing the overall content and themes.

        Creates a comprehensive vector representation of the entire document by
        combining the generated summary with key structural elements like headers
        and opening content. This embedding enables document-level similarity
        calculations and clustering operations.

        Args:
            summary (str): Generated document summary capturing key themes and
                information for embedding generation.
            structured_text (Dict[str, Any]): Structured document content providing
                additional context through headers and key elements.

        Returns:
            Optional[np.ndarray]: High-dimensional vector representation of the
                document's semantic content, or None if embedding generation fails
                or no embedding model is available.

        Note:
            - Combines summary with headers and key content from first 3 pages
            - Prioritizes structural elements (headers, titles) for document representation
            - Uses first 5 elements per page to balance comprehensiveness with efficiency
            - Handles embedding failures gracefully, returning None for robustness
        """

    def _count_tokens(self, text: str) -> int:
        """
        Calculate the number of tokens in text using the configured tokenizer.

        Provides accurate token counting for chunk size management and LLM
        compatibility verification. Supports multiple tokenizer types with
        fallback approximation methods for robustness.

        Args:
            text (str): Input text requiring token count calculation for
                chunk size management and processing decisions.

        Returns:
            int: Number of tokens in the input text as determined by the
                configured tokenizer, or approximated count if tokenizer
                is unavailable.

        Note:
            - Returns 0 for empty or None text input
            - Supports tiktoken tokenizers for OpenAI models
            - Supports HuggingFace tokenizers for other model types  
            - Falls back to word-based approximation (words * 1.3) if tokenizer fails
            - Handles tokenization errors gracefully with warning logging
        """

    def _get_chunk_overlap(self, content: str) -> str:
        """
        Extract overlap content from chunk for maintaining context continuity across boundaries.

        Retrieves the final portion of chunk content to serve as overlap for the
        subsequent chunk, ensuring context preservation and semantic continuity
        across chunk boundaries for improved LLM understanding.

        Args:
            content (str): Source chunk content from which to extract overlap
                text for the next chunk's context preservation.

        Returns:
            str: Overlap text from the end of the content, sized according to
                the configured overlap parameters. Returns empty string if
                content is insufficient for overlap extraction.

        Note:
            - Overlap size is approximated as chunk_overlap tokens divided by 4 words
            - Extracts words from the end of content to maintain narrative flow
            - Returns empty string for insufficient content length
            - Word-based approximation provides reasonable token count estimation
        """


class TextProcessor:
    """
    Utility class providing text processing operations for document analysis and optimization.

    Offers fundamental text analysis capabilities including sentence segmentation,
    keyword extraction, and content preprocessing operations required throughout
    the LLM optimization pipeline.

    This class serves as a helper for various text processing tasks within the
    document optimization workflow, providing consistent and reliable text
    analysis functionality.
    """
    
    def split_sentences(self, text: str) -> List[str]:
        """
        Segment text into individual sentences for granular content analysis.

        Divides input text into sentence-level components using punctuation-based
        splitting, enabling sentence-level processing, scoring, and analysis for
        summarization and content organization tasks.

        Args:
            text (str): Input text requiring sentence-level segmentation for
                processing and analysis operations.

        Returns:
            List[str]: List of individual sentences with whitespace trimmed,
                excluding empty strings. Sentences are split on terminal
                punctuation marks (periods, exclamation points, question marks).

        Example:
            >>> processor = TextProcessor()
            >>> sentences = processor.split_sentences("Hello world. How are you?")
            >>> print(sentences)  # ["Hello world", "How are you"]
        """
    
    def extract_keywords(self, text: str, top_k: int = 20) -> List[str]:
        """
        Extract the most significant keywords from text content based on frequency analysis.

        Identifies important terms within text by analyzing word frequency while
        filtering common stop words. Provides ranked keywords for content analysis,
        summarization scoring, and topical understanding.

        Args:
            text (str): Input text from which to extract significant keywords
                for content analysis and processing.
            top_k (int): Maximum number of keywords to return, ranked by
                frequency. Defaults to 20.

        Returns:
            List[str]: List of significant keywords ranked by frequency, with
                stop words filtered and common terms excluded. Limited to
                top_k most frequent terms.

        Note:
            - Filters words shorter than 3 characters for relevance
            - Excludes comprehensive stop word list (articles, prepositions, etc.)
            - Case-insensitive processing for consistent keyword identification
            - Returns words ranked by frequency in descending order
        """


class ChunkOptimizer:
    """
    Utility class for optimizing text chunk boundaries to respect semantic and structural divisions.

    Provides intelligent chunk boundary optimization that considers sentence breaks,
    paragraph divisions, and content structure to create chunks that maintain
    semantic coherence while respecting size constraints.

    This class enhances the chunking process by ensuring boundaries fall at
    natural text divisions rather than arbitrary character positions.

    Attributes:
        max_size (int): Maximum allowed chunk size in tokens for boundary optimization.
        overlap (int): Token overlap between chunks for context preservation.
        min_size (int): Minimum viable chunk size for optimization decisions.
    """
    
    def __init__(self, max_size: int, overlap: int, min_size: int):
        """
        Initialize chunk optimizer with size parameters for boundary optimization.

        Configures the optimizer with chunk size constraints and overlap requirements
        for intelligent boundary placement that respects content structure.

        Args:
            max_size (int): Maximum tokens per chunk for optimization decisions.
            overlap (int): Token overlap between adjacent chunks.
            min_size (int): Minimum viable chunk size threshold.
        """
    
    def optimize_chunk_boundaries(self, text: str, current_boundaries: List[int]) -> List[int]:
        """
        Optimize chunk boundary positions to align with natural text divisions.

        Analyzes text structure to identify optimal boundary positions that respect
        sentence endings and paragraph breaks, improving chunk coherence and
        semantic integrity while maintaining size constraints.

        Args:
            text (str): Source text containing content for boundary optimization
                and structural analysis.
            current_boundaries (List[int]): Character positions of current chunk
                boundaries requiring optimization for better semantic alignment.

        Returns:
            List[int]: Optimized boundary positions that align with sentence or
                paragraph breaks where possible, maintaining chunk size constraints
                while improving semantic coherence.

        Note:
            - Prioritizes paragraph boundaries within 50 characters of original boundary
            - Falls back to sentence boundaries within 25 characters if no paragraph break
            - Maintains original boundary if no suitable natural division is found nearby
            - Considers both sentence endings (period, exclamation, question) and paragraph breaks
        """
```