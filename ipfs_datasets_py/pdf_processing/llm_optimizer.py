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
from typing import Any, Optional, Annotated
import re
from enum import StrEnum
import os


import tiktoken
from transformers import AutoTokenizer
import numpy as np
from sentence_transformers import SentenceTransformer
import nltk
from nltk.tokenize import sent_tokenize, word_tokenize
from nltk.tag import pos_tag
from nltk.chunk import ne_chunk
from nltk.tree import Tree
import pydantic

import openai


from ipfs_datasets_py.utils.text_processing import TextProcessor
from ipfs_datasets_py.utils.chunk_optimizer import ChunkOptimizer

logger = logging.getLogger(__name__)

from pydantic import (
    AfterValidator as AV,
    BaseModel, 
    Field, 
    field_validator,
    NonNegativeInt,
    ValidationError,
    computed_field
)

def _numpy_ndarrays_are_equal(x: Optional[np.ndarray], y: Optional[np.ndarray]) -> bool:
    """
    Compare two numpy arrays for equality, handling None values properly.
    
    Args:
        x: First numpy array or None
        y: Second numpy array or None
        
    Returns:
        bool: True if arrays are equal, False otherwise
    """
    # Both None - they're equal
    if x is None and y is None:
        return True
    
    # One is None, the other isn't - they're not equal
    if x is None or y is None:
        return False
    
    # Neither is a numpy array - they're not equal
    if not isinstance(x, np.ndarray) or not isinstance(y, np.ndarray):
        return False
    
    # Different shapes - they're not equal
    if x.shape != y.shape:
        return False
    
    try:
        # Check if all elements are equal (within floating point tolerance)
        return np.allclose(x, y, equal_nan=True)
    except Exception as e:
        logger.error(f"Unexpected error comparing numpy arrays: {e}")
        return False

# def _turn_str_into_list_of_str(s: Any) -> list[str]:
#     match s:
#         case str():
#             return [s]
#         case list():
#             if not all(isinstance(item, str) for item in s):
#                 raise ValidationError("All items in source_elements list must be strings")
#             return s
#         case _:
#             raise ValidationError(f"Unsupported type for source_elements: {type(s).__name__}")

def _test_set_elements(s: set[str]) -> set[str]:
    """
    Validates that all elements in a set are valid semantic types.

    Args:
        s (set[str]): A set of strings representing semantic types to validate.

    Returns:
        set[str]: The original set if all elements are valid.

    Raises:
        ValueError: If any element in the set is not one of the valid semantic types:
            "text", "table", "figure_caption", "header", or "mixed".

    Note:
        The function currently contains a bug where it checks `s not in valid_set` 
        instead of `item not in valid_set`.
    """
    if s is None:
        raise ValueError("Semantic types set cannot be None")

    valid_set = {"text", "table", "figure_caption", "header", "mixed"}
    for item in s:
        print(item)
        if item not in valid_set:
            raise ValueError(f"Invalid semantic type: {item}. Must be one of {valid_set}.")
    return s


class Classification(StrEnum):
    pass

# NOTE: From https://huggingface.co/datasets/KnutJaegersberg/wikipedia_categories, 7/25/2025
CLASSIFICATIONS = {
    "Science and technology",
    "Engineering",
    "Industry",
    "Language",
    "Government",
    "Education",
    "Nature",
    "Mass media",
    "People",
    "Military",
    "Energy",
    "Knowledge",
    "Life",
    "Organizations",
    "History",
    "Concepts",
    "Philosophy",
    "Food and drink",
    "Humanities",
    "World",
    "Geography",
    "Law",
    "Business",
    "Events",
    "Entertainment",
    "Culture",
    "Religion",
    "Ethics",
    "Sports",
    "Music",
    "Academic Disciplines",
    "Politics",
    "Economy",
    "Society",
    "Mathematics",
    "Policy",
    "Health"
}

class ClassificationResult(BaseModel):
    """Result of entity classification."""
    entity: str
    category: str
    confidence: float










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
        relationships (list[str]): list of chunk IDs that are semantically or structurally
            related to this chunk, enabling cross-chunk reasoning and context.
        embedding (Optional[np.ndarray]): Vector embedding representing the semantic content.
            Shape depends on the embedding model used. None if embeddings not generated.
    """
    content: str
    chunk_id: str
    source_page: NonNegativeInt
    source_elements: list[str]
    token_count: NonNegativeInt
    semantic_types: Annotated[set[str], AV(_test_set_elements)]
    relationships: list[str] = Field(default_factory=list)
    embedding: Optional[np.ndarray] = None

    class Config:
        arbitrary_types_allowed = True

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
        if not isinstance(other, LLMChunk):
            return False
        # Perform the array equality check separately from the rest of the fields.
        if not _numpy_ndarrays_are_equal(self.embedding, other.embedding):
            return False

        self_dict = self.model_dump()
        other_dict = other.model_dump()
        # Remove embeddings from comparison.
        self_dict.pop('embedding', None)
        other_dict.pop('embedding', None)

        return self_dict == other_dict

    def __str__(self) -> str:
        """
        Generate a concise string representation of the LLMChunk.

        This method provides a human-readable summary of the document's key attributes,
        including the document ID, title, number of chunks, and summary length.
        It is designed to be informative yet concise for quick inspection.

        Returns:
            str: String representation of the LLMDocument.
        """
        original_string = super().__str__()
        if self.embedding is not None and 'embedding' in original_string:
            # Remove the embedding field from the string representation
            original_string = re.sub(r'embedding=array\([^)]*\)', 'embedding=<omitted>)', original_string) 
        return original_string

    @field_validator('content')
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
        if v is None:
            raise ValueError("Content cannot be None")
        if not isinstance(v, str):
            raise ValueError("Content must be a string")
        return v



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
        chunks (list[LLMChunk]): list of semantically optimized text chunks with embeddings.
            Each chunk contains content, metadata, embeddings, and relationship information.
        summary (str): Comprehensive document summary generated from the full content.
        key_entities (list[dict[str, Any]]): Key entities extracted from the document content
            including text, type classification, and confidence scores.
        processing_metadata (dict[str, Any]): Document processing and optimization metadata
            including timestamps, chunk counts, token counts, and model information.
        document_embedding (Optional[np.ndarray]): Document-level vector embedding representing
            the overall semantic content. Shape depends on the embedding model used.
    """
    document_id: str
    title: str
    chunks: list[LLMChunk]
    summary: str
    key_entities: list[dict[str, Any]]
    processing_metadata: dict[str, Any]
    document_embedding: Optional[np.ndarray] = None

    class Config:
        arbitrary_types_allowed = True

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
        if not isinstance(other, LLMDocument):
            return False

        # Perform the array equality check separately from the rest of the fields.
        if not _numpy_ndarrays_are_equal(self.document_embedding, other.document_embedding):
            return False

        self_dict = self.model_dump()
        other_dict = other.model_dump()
        # Remove embeddings from comparison.
        self_dict.pop('document_embedding', None)
        other_dict.pop('document_embedding', None)

        return self_dict == other_dict

    def __str__(self) -> str:
        """
        Generate a concise string representation of the LLMDocument.

        This method provides a human-readable summary of the document's key attributes,
        including the document ID, title, number of chunks, and summary length.
        It is designed to be informative yet concise for quick inspection.

        Returns:
            str: String representation of the LLMDocument.
        """
        original_string = super().__str__()
        chunk_str_list = ', '.join([
            f"(chunk_id={chunk.chunk_id}, token_count={chunk.token_count})" 
            for chunk in self.chunks
        ])
        original_string = re.sub(r'chunks=\[.*\]', f'chunks=[{chunk_str_list}]', original_string)

        if 'document_embedding' in original_string:
            # Remove the document_embedding field from the string representation
            original_string = re.sub(r'document_embedding=array\([^)]*\)', 'document_embedding=<omitted>)', original_string) 
        
        # If the chunk is still too long, truncate to 499 characters.
        if len(original_string) > 500:
            original_string = original_string[:496] + '...'
        return original_string

    @field_validator('document_embedding')
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
        if v is None:
            return None
        if not isinstance(v, np.ndarray):
            raise ValueError(f"document_embedding must be a numpy array, got {type(v)}")
        return v.copy()  # This creates a copy!


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
    optimization_timestamp: float
    chunk_count: NonNegativeInt
    total_tokens: NonNegativeInt
    model_used: str
    tokenizer_used: str



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
    
    def __init__(self, 
                 model_name: str = "sentence-transformers/all-MiniLM-L6-v2",
                 tokenizer_name: str = "gpt-3.5-turbo",
                 max_chunk_size: int = 2048,
                 chunk_overlap: int = 200,
                 min_chunk_size: int = 100,
                 entity_classifications: list[str] = CLASSIFICATIONS,
                 ):
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
        self.model_name: str = model_name
        self.tokenizer_name: str = tokenizer_name
        self.max_chunk_size: int = max_chunk_size
        self.chunk_overlap: int = chunk_overlap
        self.min_chunk_size: int = min_chunk_size
        self.api_key = os.environ["OPENAI_API_KEY"]
        self.entity_classifications: set[str] = entity_classifications

        self.openai_async_client = openai.AsyncOpenAI(api_key=self.api_key)

        # Initialize models
        self._initialize_models()

        # Text processing utilities
        self.text_processor = TextProcessor()
        self.chunk_optimizer = ChunkOptimizer(
            max_size=max_chunk_size,
            overlap=chunk_overlap,
            min_size=min_chunk_size
        )

    def _initialize_models(self):
        """
        Initialize embedding and tokenization models with error handling and fallback options.

        This method loads the specified sentence transformer model for embeddings and
        tokenizer for token counting. It handles model loading errors gracefully by
        implementing fallback mechanisms to ensure the optimizer can function even
        with limited model availability.

        The method supports both tiktoken tokenizers (for OpenAI models) and HuggingFace
        tokenizers, automatically detecting the appropriate tokenizer type based on
        the model name. If model loading fails, fallback tokenization methods are used.

        Raises:
            OSError: If model files cannot be accessed or downloaded.

        Side Effects:
            Sets self.embedding_model to SentenceTransformer instance or None on failure.
            Sets self.tokenizer to appropriate tokenizer instance or None on failure.
            Logs initialization status and any errors encountered.

        Examples:
            >>> optimizer = LLMOptimizer()
            >>> # Logs: "Loaded embedding model: sentence-transformers/all-MiniLM-L6-v2"
            >>> # Logs: "Loaded tokenizer: gpt-3.5-turbo"
            
            >>> # With invalid model name
            >>> optimizer = LLMOptimizer(model_name="invalid-model")
            >>> # Logs: "Failed to initialize models: ..."
            >>> # Falls back to basic tokenization methods

        Note:
            This method is called automatically during __init__ and should not be
            called directly. Model loading is attempted once during initialization
            to avoid repeated loading overhead.
        """
        try:
            # Initialize sentence transformer for embeddings
            self.embedding_model = SentenceTransformer(self.model_name)
            logger.info(f"Loaded embedding model: {self.model_name}")
        except Exception as e:
            raise RuntimeError(f"Could not load embedding model for LLMOptimizer: {self.model_name}: {e}") from e

            # Initialize tokenizer for token counting
        try:
            if "gpt" in self.tokenizer_name.lower():
                self.tokenizer = tiktoken.encoding_for_model(self.tokenizer_name)
            else:
                self.tokenizer = AutoTokenizer.from_pretrained(self.tokenizer_name)

            logger.info(f"Loaded tokenizer: {self.tokenizer_name}")

        except Exception as e:
            raise RuntimeError(
                f"Could not load tokenizer for LLMOptimizer: {self.model_name}, {self.tokenizer_name}: {e}"
            ) from e

        try:
            self.openai_async_client = openai.AsyncOpenAI()
        except Exception as e:
            raise RuntimeError(f"Could not initialize OpenAI client: {e}") from e


    async def optimize_for_llm(self, 
                              decomposed_content: dict[str, Any],
                              document_metadata: dict[str, Any],
                              
                              ) -> LLMDocument:
        """
        Transform decomposed PDF content into an LLM-optimized document with semantic structure.

        This method performs the complete optimization pipeline, converting raw PDF decomposition
        output into a comprehensive LLMDocument optimized for language model consumption. The
        process includes text extraction, semantic chunking, embedding generation, entity
        extraction, and relationship establishment to create a rich, structured representation.

        The optimization preserves document structure while making content accessible to LLMs
        through intelligent chunking, token-aware segmentation, and contextual enrichment.

        Args:
            decomposed_content (dict[str, Any]): Content from PDF decomposition stage containing
                pages, elements, metadata, and structure information. Expected structure:
                {
                    'pages': [{'elements': [...], 'metadata': {...}}, ...],
                    'metadata': {...},
                    'structure': {...}
                }
            document_metadata (dict[str, Any]): Document metadata and properties including
                document_id, title, author, creation_date, and other document-level information.

        Returns:
            LLMDocument: Comprehensive container with optimized chunks, embeddings, and metadata
                containing document_id, title, chunks (list[LLMChunk]), summary, key_entities,
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
        timeout = 30 # seconds
        import asyncio

        async with asyncio.timeout(timeout):
        
            print("Starting LLM optimization process")
            
            # Extract text content with structure preservation
            structured_text = await self._extract_structured_text(decomposed_content)

            print("Extracted structured text content with preserved document structure")
            
            # Generate document summary
            document_summary = await self._generate_document_summary(structured_text)

            print("Generated document summary")
            
            # Create optimal chunks
            chunks = await self._create_optimal_chunks(structured_text)

            print(f"Created {len(chunks)} initial chunks")

            # Generate embeddings
            chunks_with_embeddings = await self._generate_embeddings(chunks)

            print("Generated embeddings for all chunks")

            # Extract key entities
            key_entities = await self._extract_key_entities(structured_text)

            print(f"Extracted {len(key_entities)} key entities from document")

            # Create document-level embedding
            document_embedding = await self._generate_document_embedding(document_summary, structured_text)

            print("Generated document-level embedding")

            # Build LLM document
            llm_document = LLMDocument(
                document_id=document_metadata.get('document_id', ''),
                title=document_metadata.get('title', ''),
                chunks=chunks_with_embeddings,
                summary=document_summary,
                key_entities=key_entities,
                document_embedding=document_embedding,
                processing_metadata= LLMDocumentProcessingMetadata(
                    optimization_timestamp=asyncio.get_event_loop().time(),
                    chunk_count=len(chunks_with_embeddings),
                    total_tokens=sum(chunk.token_count for chunk in chunks_with_embeddings),
                    model_used=self.model_name,
                    tokenizer_used=self.tokenizer_name
                ).model_dump()
            )
            
            print(f"LLM optimization complete: {len(chunks_with_embeddings)} chunks created")
            return llm_document

        raise TimeoutError(f"LLM optimization process timed out after '{timeout}' seconds")
    
    async def _extract_structured_text(self, decomposed_content: dict[str, Any]) -> dict[str, Any]:
        """
        Extract and organize text content while preserving document structure and element context.

        This method processes decomposed PDF content to create a structured text representation
        that maintains the hierarchical organization of the original document. It extracts
        text elements with their positional, stylistic, and semantic metadata to preserve
        context for downstream processing while organizing content by pages and elements.

        The structured output maintains element relationships, page boundaries, and content
        types to enable intelligent chunking and context-aware processing.

        Args:
            decomposed_content (dict[str, Any]): Raw decomposed PDF content containing pages,
                elements, and metadata from the PDF decomposition stage. Expected to contain
                'pages' list with element dictionaries including content, type, position,
                style, and confidence information.

        Returns:
            dict[str, Any]: Structured text representation with the following format:
                {
                    'pages': [
                        {
                            'page_number': int,
                            'elements': [
                                {
                                    'content': str,
                                    'type': str,
                                    'position': dict[str, Any],
                                    'style': dict[str, Any],
                                    'confidence': float
                                }, ...
                            ],
                            'full_text': str
                        }, ...
                    ],
                    'metadata': dict[str, Any],
                    'structure': dict[str, Any]
                }

        Raises:
            KeyError: If decomposed_content is missing required keys ('pages').
            TypeError: If decomposed_content structure is invalid or elements lack expected fields.
            ValueError: If page content cannot be processed or contains invalid data.

        Examples:
            >>> decomposed_content = {
            ...     'pages': [
            ...         {
            ...             'elements': [
            ...                 {
            ...                     'content': 'Chapter 1: Introduction',
            ...                     'type': 'text',
            ...                     'subtype': 'header',
            ...                     'position': {'x': 100, 'y': 50},
            ...                     'confidence': 0.95
            ...                 }
            ...             ]
            ...         }
            ...     ]
            ... }
            >>> structured = await optimizer._extract_structured_text(decomposed_content)
            >>> print(structured['pages'][0]['elements'][0]['type'])  # 'header'

        Note:
            This method filters out empty content and normalizes element types for
            consistent processing. Text elements are concatenated to create page-level
            full_text for document-wide operations.
        """
        # Validate required keys
        if 'pages' not in decomposed_content:
            raise KeyError("'pages' key is required in decomposed_content")
            
        structured_text = {
            'pages': [],
            'metadata': decomposed_content.get('metadata', {}),
            'structure': decomposed_content.get('structure', {})
        }
        
        for page_num, page_content in enumerate(decomposed_content['pages']):
            page_text = {
                'page_number': page_num + 1,
                'elements': [],
                'full_text': ''
            }
            
            # Extract all elements with context, preserving all metadata
            for element in page_content.get('elements', []):
                # Create element preserving ALL original metadata
                processed_element = {}
                
                # Preserve all fields from the original element
                for key, value in element.items():
                    processed_element[key] = value
                
                # Normalize type field: use subtype if available
                if 'subtype' in element:
                    processed_element['type'] = element.get('subtype')
                elif element.get('type') == 'text':
                    # Default text elements to 'paragraph' if no subtype
                    processed_element['type'] = 'paragraph'
                else:
                    processed_element['type'] = element.get('type', 'unknown')
                
                # Ensure required fields have defaults if missing
                if 'content' not in processed_element:
                    processed_element['content'] = ''
                if 'position' not in processed_element:
                    processed_element['position'] = {}
                if 'style' not in processed_element:
                    processed_element['style'] = {}
                if 'confidence' not in processed_element:
                    processed_element['confidence'] = 1.0
                
                page_text['elements'].append(processed_element)
                page_text['full_text'] += processed_element['content'] + '\n'
            
            structured_text['pages'].append(page_text)
        
        return structured_text
    
    async def _generate_document_summary(self, structured_text: dict[str, Any]) -> str:
        """
        Generate a comprehensive extractive summary of the document using keyword and position analysis.

        This method creates a concise summary by analyzing the full document text and selecting
        the most representative sentences based on keyword frequency, positional importance,
        and sentence characteristics. The summary captures the key themes and important
        information from the document while maintaining readability and coherence.

        The summarization algorithm combines multiple scoring factors including keyword presence,
        sentence position (earlier sentences weighted higher), and optimal sentence length
        to identify the most informative content for the summary.

        Args:
            structured_text (dict[str, Any]): Structured text representation from
                _extract_structured_text containing pages with full_text content.
                Expected format: {'pages': [{'full_text': str, ...}, ...]}

        Returns:
            str: Comprehensive document summary composed of the top-ranked sentences
                joined together. Typically 3-5 sentences capturing the main themes,
                key findings, and important information from the document.

        Raises:
            KeyError: If structured_text is missing required 'pages' key.
            ValueError: If no valid text content is found in the document.
            TypeError: If structured_text format is invalid.

        Examples:
            >>> structured_text = {
            ...     'pages': [
            ...         {'full_text': 'This paper presents a novel approach to...'},
            ...         {'full_text': 'The methodology involves three key steps...'}
            ...     ]
            ... }
            >>> summary = await optimizer._generate_document_summary(structured_text)
            >>> print(len(summary))  # Typically 200-500 characters
            >>> print(summary)  # "This paper presents a novel approach..."
        """
        try:
            # Combine all text content
            full_text = ""
            for page in structured_text['pages']:
                full_text += page['full_text'] + "\n"
            
            if not full_text.strip():
                raise ValueError("No valid text content found in structured_text")
            
            # Basic extractive summarization (can be enhanced with LLM)
            sentences = self.text_processor.split_sentences(full_text)
            print(f"sentences:\n{sentences}")
            
            # Score sentences by position and keyword frequency
            scored_sentences = []
            keywords = self.text_processor.extract_keywords(full_text, top_k=20)
            
            for i, sentence in enumerate(sentences[:50]):  # First 50 sentences
                score = 0
                # Position weight (earlier sentences get higher scores)
                score += (50 - i) / 50 * 0.3
                
                # Keyword presence
                for keyword in keywords:
                    if keyword.lower() in sentence.lower():
                        score += 0.1
                
                # Length penalty for very short/long sentences
                words = len(sentence.split())
                if 10 <= words <= 30:
                    score += 0.2
                
                scored_sentences.append((sentence, score))
            
            # Select top sentences for summary
            scored_sentences.sort(key=lambda x: x[1], reverse=True)
            print(f"scored sentences:\n{scored_sentences}")
            summary_sentences = [sent[0] for sent in scored_sentences[:5]]
            print(f"summary sentences:\n{summary_sentences}")

            return ".".join(summary_sentences)

        except Exception as e:
            msg = f"Summary generation failed with a {type(e).__name__}: {e}"
            logger.error(msg)
            return msg
    
    async def _create_optimal_chunks(self, structured_text: dict[str, Any]) -> list[LLMChunk]:
        """
        Create semantically coherent text chunks optimized for LLM processing with intelligent boundary detection.

        This method transforms structured text into optimal chunks that respect natural language
        boundaries while adhering to token limits and maintaining semantic coherence. It processes
        content page by page, grouping related elements and establishing chunk relationships
        to preserve document narrative flow and contextual information.

        The chunking algorithm considers semantic types, token counts, and overlap requirements
        to create chunks that maximize LLM comprehension while maintaining processing efficiency.

        Args:
            structured_text (dict[str, Any]): Structured text representation with pages and
                elements from _extract_structured_text. Expected format includes pages with
                elements containing content, type, and metadata.

        Returns:
            list[LLMChunk]: list of optimized text chunks with the following properties:
                - Each chunk respects max_chunk_size token limits
                - Overlapping content maintains narrative continuity
                - Semantic relationships established between related chunks
                - Rich metadata including source elements and content types
                - Unique identifiers for cross-referencing and relationship mapping

        Raises:
            ValueError: If token counting fails or chunk creation encounters invalid content.
            TypeError: If structured_text format is incompatible with chunking process.
            RuntimeError: If chunking process fails due to memory or processing constraints.

        Examples:
            >>> structured_text = {
            ...     'pages': [
            ...         {
            ...             'page_number': 1,
            ...             'elements': [
            ...                 {'content': 'Introduction text...', 'type': 'paragraph'},
            ...                 {'content': 'Table data...', 'type': 'table'}
            ...             ]
            ...         }
            ...     ]
            ... }
            >>> chunks = await optimizer._create_optimal_chunks(structured_text)
            >>> print(f"Created {len(chunks)} chunks")
            >>> print(f"First chunk: {chunks[0].chunk_id}")

        Note:
            Semantic relationships are established between adjacent and same-page chunks.
            The method preserves source element information for traceability.
        """
        chunks = []
        chunk_id_counter = 0
        
        for page in structured_text['pages']:
            page_num = page['page_number']
            
            # Process elements by semantic type
            current_chunk_content = ""
            source_elements = []

            for element in page['elements']:
                element_content = element['content'].strip()
                if not element_content:
                    continue
                
                # Calculate tokens for current content + new element
                potential_content = current_chunk_content + "\n" + element_content
                token_count = self._count_tokens(potential_content)
                
                # Check if adding this element would exceed chunk size
                if token_count > self.max_chunk_size and current_chunk_content:
                    # Create chunk with current content
                    chunk = await self._create_chunk(
                        current_chunk_content,
                        chunk_id_counter,
                        page_num,
                        source_elements
                    )
                    chunks.append(chunk)
                    chunk_id_counter += 1
                    
                    # Start new chunk with overlap
                    overlap_content = self._get_chunk_overlap(current_chunk_content)
                    current_chunk_content = overlap_content + "\n" + element_content
                else:
                    # Add element to current chunk
                    if current_chunk_content:
                        current_chunk_content += "\n" + element_content
                    else:
                        current_chunk_content = element_content
                    
                    source_elements.append(element['type'])

            # Create final chunk for page if content remains
            if current_chunk_content.strip():
                chunk = await self._create_chunk(
                    current_chunk_content,
                    chunk_id_counter,
                    page_num,
                    ['text'] # TODO Can't figure out the source elements for the last chunk if not page elements.
                )
                chunks.append(chunk)
                chunk_id_counter += 1
        
        # Establish relationships between chunks
        chunks = self._establish_chunk_relationships(chunks)
        
        return chunks


    async def _create_chunk(self, 
                          content: str, 
                          chunk_id: int, 
                          page_num: int,
                          source_elements: list[str]) -> LLMChunk:
        """
        Create a single LLMChunk instance with content processing and semantic type classification.

        This method constructs an individual LLMChunk from text content and associated metadata,
        performing token counting and semantic type determination. It creates a fully-formed 
        chunk ready for embedding generation and relationship establishment.

        The method analyzes the source elements to determine the primary semantic type following
        a priority hierarchy and generates comprehensive metadata for downstream processing.

        Args:
            content (str): The actual text content to be included in the chunk. Should be
                non-empty and properly formatted text ready for LLM processing.
            chunk_id (int): Unique integer identifier for this chunk within the document.
                Used to generate the formatted chunk_id string (e.g., "chunk_0001").
            page_num (int): Page number from the original document where this content
                originated. Used for traceability and same-page relationship establishment.
            source_elements (list[str]): list of element types that contributed to this chunk
                (e.g., ['paragraph', 'header', 'table']).

        Returns:
            LLMChunk: Fully constructed chunk instance with the following attributes populated:
                - content: Cleaned and stripped text content
                - chunk_id: Formatted identifier (e.g., "chunk_0001")
                - source_page: Source page number
                - source_elements: list of contributing element types
                - token_count: Accurate token count using configured tokenizer
                - semantic_types: Set of semantic content types present in the chunk
                - relationships: Empty list (populated later by _establish_chunk_relationships)
                - embedding: None (populated later by _generate_embeddings)

        Raises:
            ValueError: If content is empty, token counting fails, or invalid semantic type is determined.
            TypeError: If source_elements structure is invalid.
            RuntimeError: If chunk creation fails due to processing errors.

        Examples:
            >>> content = "This is the introduction to our research paper..."
            >>> source_elements = ['header', 'paragraph']
            >>> chunk = await optimizer._create_chunk(content, 0, 1, source_elements)
            >>> print(chunk.chunk_id)  # "chunk_0000"
            >>> print(chunk.semantic_types)  # {'header', 'paragraph'}
            >>> print(chunk.token_count)  # Actual token count

        Note:
            Semantic type determination follows a priority hierarchy: header > table > 
            figure_caption > mixed > text. The method automatically strips whitespace 
            and validates content before processing.
        """
        token_count = self._count_tokens(content)
        
        # Determine primary semantic type
        semantic_types = set(source_elements)

        # Priority hierarchy: header > table > figure_caption > mixed > text
        primary_type = None
        if 'header' in semantic_types:
            primary_type = 'header'
        elif 'table' in semantic_types:
            primary_type = 'table'
        elif 'figure_caption' in semantic_types:
            primary_type = 'figure_caption'
        elif len(semantic_types) > 1:
            primary_type = 'mixed'
        elif len(semantic_types) == 1:
            primary_type = list(semantic_types)[0]
        else:
            primary_type = 'text'
        
        # Validate semantic type against allowed values
        allowed_types = {'text', 'table', 'figure_caption', 'header', 'mixed'}
        if primary_type is None or primary_type not in allowed_types:
            raise ValueError(f"Invalid semantic type '{primary_type}' for chunk creation.")
        
        chunk = LLMChunk(
            content=content.strip(),
            chunk_id=f"chunk_{chunk_id:04d}",
            source_page=page_num,
            source_elements=source_elements,
            token_count=token_count,
            semantic_types=semantic_types,
            relationships=[],  # Will be populated later
        )

        return chunk
    
    def _establish_chunk_relationships(self, chunks: list[LLMChunk]) -> list[LLMChunk]:
        """
        Establish semantic and structural relationships between chunks to preserve document coherence.

        This method analyzes the collection of chunks to identify and establish meaningful
        relationships that maintain document structure and narrative flow. It considers
        sequential ordering, page boundaries, and semantic proximity to create a web
        of relationships that enables context-aware processing and cross-chunk reasoning.

        The relationship establishment preserves both local (adjacent chunks) and contextual
        (same-page chunks) connections while limiting relationship counts for performance.

        Args:
            chunks (list[LLMChunk]): list of LLMChunk instances with populated content and
                metadata but empty relationships lists. Chunks should be ordered logically
                (typically by page and position within page).

        Returns:
            list[LLMChunk]: The same list of chunks with populated relationships attributes.
                Each chunk will have its relationships list populated with chunk IDs of
                related chunks including:
                - Adjacent chunks (sequential relationships)
                - Same-page chunks (contextual relationships)
                - Limited to reasonable numbers for performance

        Raises:
            ValueError: If chunks list is empty or contains invalid chunk instances.
            TypeError: If chunks contain malformed chunk_id or source_page attributes.
            AttributeError: If chunk instances are missing required attributes.

        Examples:
            >>> chunks = [chunk1, chunk2, chunk3]  # Three sequential chunks
            >>> updated_chunks = optimizer._establish_chunk_relationships(chunks)
            >>> print(updated_chunks[1].relationships)
            >>> # ['chunk_0000', 'chunk_0002', 'other_same_page_chunks']
            
            >>> # Same page chunks get additional relationships
            >>> same_page_chunks = [chunk for chunk in chunks if chunk.source_page == 1]
            >>> print(len(same_page_chunks[0].relationships))  # Multiple relationships

        Note:
            Relationship limits are applied to prevent performance degradation with large
            documents. Sequential relationships are always established for adjacent chunks.
        """
        for i, chunk in enumerate(chunks):
            relationships = []
            
            # Adjacent chunks (sequential relationship)
            if i > 0:
                relationships.append(chunks[i-1].chunk_id)
            if i < len(chunks) - 1:
                relationships.append(chunks[i+1].chunk_id)
            
            # Same page chunks
            same_page_chunks = [
                c.chunk_id for c in chunks 
                if c.source_page == chunk.source_page and c.chunk_id != chunk.chunk_id
            ]
            relationships.extend(same_page_chunks)
            
            chunk.relationships = list(set(relationships))
        
        return chunks
    
    async def _generate_embeddings(self, chunks: list[LLMChunk]) -> list[LLMChunk]:
        """
        Generate vector embeddings for all chunks using the configured sentence transformer model.

        This method processes chunks in batches to generate high-quality vector embeddings
        that capture the semantic content of each text chunk. The embeddings enable semantic
        search, similarity comparison, and vector-based operations for downstream LLM tasks.

        The method handles batch processing for efficiency and includes comprehensive error
        handling to ensure processing continues even if individual batches fail.

        Args:
            chunks (list[LLMChunk]): list of LLMChunk instances with populated content.
                Each chunk should have valid content text for embedding generation.
                Chunks may or may not have existing embeddings (will be overwritten).

        Returns:
            list[LLMChunk]: The same list of chunks with populated embedding attributes.
                Successfully processed chunks will have numpy arrays in their embedding
                attribute. Failed chunks will retain None embeddings with error logging.

        Raises:
            RuntimeError: If no embedding model is available and embeddings cannot be generated.
            MemoryError: If batch processing exceeds available memory for large documents.
            ValueError: If chunks contain invalid or empty content that cannot be embedded.

        Examples:
            >>> chunks = [chunk1, chunk2, chunk3]  # Chunks with text content
            >>> embedded_chunks = await optimizer._generate_embeddings(chunks)
            >>> print(embedded_chunks[0].embedding.shape)  # (384,) for all-MiniLM-L6-v2
            >>> print(type(embedded_chunks[0].embedding))  # <class 'numpy.ndarray'>
            
            >>> # Check for successful embedding generation
            >>> successful = [c for c in embedded_chunks if c.embedding is not None]
            >>> print(f"{len(successful)}/{len(chunks)} chunks embedded successfully")
        """
        if not self.embedding_model:
            logger.warning("No embedding model available, skipping embedding generation")
            return chunks
        
        # Prepare texts for embedding
        texts = [chunk.content for chunk in chunks]
        
        # Generate embeddings in batches
        batch_size = 32
        for i in range(0, len(texts), batch_size):
            batch_texts = texts[i:i+batch_size]
            batch_chunks = chunks[i:i+batch_size]
            
            try:
                embeddings = self.embedding_model.encode(
                    batch_texts,
                    convert_to_numpy=True,
                    show_progress_bar=False
                )
                
                for chunk, embedding in zip(batch_chunks, embeddings):
                    chunk.embedding = embedding
                    
            except Exception as e:
                logger.error(f"Failed to generate embeddings for batch {i//batch_size + 1}: {e}")
                # Continue without embeddings for this batch
        
        return chunks

    async def _get_entity_classification(
        self, 
        sentence: str, 
        *,
        openai_client: Any, 
        classifications: set[str] = CLASSIFICATIONS,
        retries: int = 3,
        timeout: int = 30
    ) -> ClassificationResult:
        """
        Classify the type of entity in a sentence using an OpenAI language model.

        This function analyzes a given text segment and assigns it to one of the
        provided classification categories using OpenAI's completion API.

        Args:
            sentence (str): A semantic unit of English text to classify.
                Must satisfy the following criteria:
                - Non-empty string containing at least one word
                - Represents a single, coherent semantic unit.
                - Maximum of 512 characters.
                - No leading/trailing whitespace

            openai_client (Any): An OpenAI client instance with access to completion methods.
                The client must support the chat completions API and log probability functionality
                in order to constrain outputs to the specified classifications.

            classifications (set[str], optional): Set of categories to classify the sentence into.
                Requirements:
                - Non-empty set with at least one classification
                - Each classification should be a non-empty string
                - Classifications should be mutually exclusive when possible

                Defaults to the predefined CLASSIFICATIONS set based on Wikipedia categories.
                These categories are:
                - "Science and technology", "Engineering", "Industry", "Language",
                - "Government", "Education", "Nature", "Mass media", "People",
                - "Military", "Energy", "Knowledge", "Life", "Organizations",
                - "History", "Concepts", "Philosophy", "Food and drink",
                - "Humanities", "World", "Geography", "Law", "Business",
                - "Events", "Entertainment", "Culture", "Religion",
                - "Ethics", "Sports", "Music", "Academic Disciplines",
                - "Politics", "Economy", "Society", "Mathematics",
                - "Policy", "Health"

        Returns:
            ClassificationResult: An object containing:
                - entity (str): The original sentence being classified.
                - category (str): The most probable classification of the entity in the sentence.
                - confidence (int): A float between 0 and 1.
                    This represents the model's confidence in the classification.

        Classification Process:
            - Let temperature be 0.0 (ensures deterministic output).
            - Let base log threshold be the natural log of 0.05 (e.g. statistical significance threshold). 
            - Run the sentence through the OpenAI completion API, with a list of categories.
            - OpenAI's API will return the top 20 most probable categories in log Probability format.
            - For each category in the response:
                - If the log probability is below the threshold, exclude from further consideration.
            - If no categories remain after filtering, assign it as "unclassified" with confidence 0.0.
            - Else, re-perform classification with the remaining categories.
            - Continue until either:
                - No categories remain after filtering.
                - All categories are above the threshold.
                - The number of retries exceeds the specified limit.
            - If multiple categories remain, select the one with the highest log probability.
            - Convert this log probability into a probability score between 0 and 1.

        Raises:
            TypeError: If arguments have incorrect types.
            ValueError: If text is empty, categories is empty, or openai client is not set.
            asyncio.TimeoutError: If the API request exceeds the timeout.
            openai.APIError: If the OpenAI API returns an error.
            RuntimeError: If max retries exceeded or response parsing fails.

        Example:
            >>> import openai
            >>> client = openai.AsyncOpenAI(api_key="your-api-key")
            >>> sentence = "Apple Inc."
            >>> classifications = {'Technology', 'Business', 'Science', 'Other'}
            >>> result = await _get_entity_classification(
            ...     sentence,
            ...     openai_client=client,
            ...     classifications=classifications
            ... )
            >>> print(result)
            'Business'
        """
        pass


    async def _extract_key_entities(self, 
                                    structured_text: dict[str, Any],
                                    max_entities: int = 50
                                    ) -> list[dict[str, Any]]:
        """
        Extract key entities and concepts from document text using NLTK's advanced named entity recognition.

        This method performs comprehensive named entity recognition to identify and extract important
        entities such as people, organizations, locations, dates, and other significant information
        from the document text. It leverages NLTK's pre-trained models for reliable extraction
        and includes confidence scoring for each identified entity.

        The extraction process uses NLTK's named entity chunking combined with part-of-speech
        tagging to identify various entity types with high accuracy while limiting results
        to prevent overwhelming downstream processing.

        Args:
            structured_text (dict[str, Any]): Structured text representation containing
                pages with full_text content. Expected format from _extract_structured_text
                with 'pages' list containing page dictionaries with 'full_text' keys.
            max_entities (int): Maximum number of entities to extract. Defaults to 50.
                This limits the number of entities returned to prevent excessive output.

        Returns:
            list[dict[str, Any]]: list of extracted entities, each containing:
                - 'text' (str): The actual entity text as found in the document
                - 'type' (str): Entity type classification. The classifications are arbitrary.
                - 'confidence' (float): Confidence score between 0.0 and 1.0 indicating
                  extraction reliability based on entity type and context

        Raises:
            KeyError: If structured_text is missing required 'pages' key.
            ValueError: If no valid text content is found for entity extraction.
            ImportError: If required NLTK packages are not available (handled with fallback).
            TypeError: If structured_text format is incompatible with processing.

        Examples:
            >>> structured_text = {
            ...     'pages': [
            ...         {'full_text': 'John Smith works at Microsoft in Seattle on January 15, 2024.'},
            ...         {'full_text': 'The project cost $2.5 million and achieved 95% accuracy.'}
            ...     ]
            ... }
            >>> entities = await optimizer._extract_key_entities(structured_text)
            >>> print(entities)
            >>> # [
            >>> #     {'text': 'John Smith', 'type': 'PERSON', 'confidence': 0.9},
            >>> #     {'text': 'Microsoft', 'type': 'ORGANIZATION', 'confidence': 0.85},
            >>> #     {'text': 'Seattle', 'type': 'GPE', 'confidence': 0.8},
            >>> #     {'text': 'January 15, 2024', 'type': 'DATE', 'confidence': 0.7},
            >>> #     {'text': '$2.5 million', 'type': 'MONEY', 'confidence': 0.8},
            >>> #     {'text': '95%', 'type': 'PERCENT', 'confidence': 0.9}
            >>> # ]
        """
        if not isinstance(structured_text, dict):
            raise TypeError("structured_text must be a dictionary")
        if 'pages' not in structured_text.keys():
            raise KeyError("'pages' key is required in structured_text")
        if not isinstance(structured_text['pages'], list):
            raise TypeError("'pages' value must be a list")
        if not structured_text['pages']:
            raise ValueError("No pages found in structured_text for entity extraction")
        if not isinstance(max_entities, int):
            raise TypeError("max_entities must be an integer")
        if max_entities <= 0:
            raise ValueError("max_entities must be a positive integer")
        
        # Validate page structure
        for idx, page in enumerate(structured_text['pages']):
            if not isinstance(page, dict):
                raise TypeError(f"Page {idx} must be a dictionary")
            if 'full_text' not in page:
                raise KeyError(f"Page {idx} missing required 'full_text' key")
            if not isinstance(page['full_text'], str):
                raise TypeError(f"Page {idx} 'full_text' must be a string")
        
        # Combine all text for entity extraction
        full_text = ""
        for page in structured_text['pages']:
            full_text += page['full_text'] + "\n"
        
        if not full_text.strip():
            raise ValueError("No valid text content found for entity extraction")
        
        entities = []
        
        # Process text in sentences for better entity recognition
        sentences = sent_tokenize(full_text)
        
        for sentence in sentences:

            # Named entity recognition via LLM
            result: ClassificationResult = await self._get_entity_classification(
                sentence,
                openai_client=self.openai_async_client,
                classifications=self.entity_classifications,
                retries=3,
                timeout=30
            )

            entities.append({
                'text': result.entity,
                'type': result.category,
                'confidence': result.confidence
            })

        # Remove duplicates while preserving order
        seen = set()
        unique_entities = []
        for entity in entities:
            entity_key = (entity['text'].lower(), entity['type'])
            if entity_key not in seen:
                seen.add(entity_key)
                unique_entities.append(entity)
        
        # Sort by confidence and limit results
        unique_entities.sort(key=lambda x: x['confidence'], reverse=True)

        top_k_unique_entities = unique_entities[:max_entities]

        return top_k_unique_entities
    
    def _calculate_entity_confidence(self, entity_type: str, entity_text: str) -> float:
        """
        Calculate confidence score for extracted entities based on type and characteristics.
        
        Args:
            entity_type (str): The NLTK entity type (PERSON, ORGANIZATION, GPE, etc.)
            entity_text (str): The actual entity text
            
        Returns:
            float: Confidence score between 0.0 and 1.0
        """
        # TODO Where the hell do these numbers come from?
        base_confidence = {
            'PERSON': 0.85,
            'ORGANIZATION': 0.80,
            'GPE': 0.75,  # Geopolitical entity (countries, cities, states)
            'LOCATION': 0.75,
            'DATE': 0.70,
            'TIME': 0.70,
            'MONEY': 0.85,
            'PERCENT': 0.90,
            'FACILITY': 0.65,
            'EVENT': 0.60
        }.get(entity_type, 0.50)
        
        # Adjust confidence based on entity characteristics
        text_length = len(entity_text.split())
        
        # Longer entities (2-4 words) tend to be more reliable
        if 2 <= text_length <= 4:
            base_confidence += 0.05
        elif text_length > 4:
            base_confidence -= 0.05
        
        # Single character entities are likely noise
        if len(entity_text.strip()) == 1:
            base_confidence -= 0.3
        
        # Entities with mixed case are more likely to be valid
        if entity_text.istitle() or any(c.isupper() for c in entity_text):
            base_confidence += 0.05
        
        return max(0.0, min(1.0, base_confidence))
    
    async def _extract_entities_fallback(self, structured_text: dict[str, Any]) -> list[dict[str, Any]]:
        """
        Fallback entity extraction using basic pattern matching when NLTK is unavailable.
        
        Args:
            structured_text (dict[str, Any]): Structured text representation
            
        Returns:
            list[dict[str, Any]]: list of extracted entities with basic pattern matching
        """
        # Combine all text for entity extraction
        full_text = ""
        for page in structured_text['pages']:
            full_text += page['full_text'] + "\n"
        
        entities = []
        
        # Date patterns
        date_patterns = [
            r'\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b',
            r'\b\d{4}[/-]\d{1,2}[/-]\d{1,2}\b',
            r'\b(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+\d{4}\b'
        ]
        
        for pattern in date_patterns:
            dates = re.findall(pattern, full_text)
            for date in dates[:10]:
                entities.append({
                    'text': date,
                    'type': 'DATE',
                    'confidence': 0.7
                })
        
        # Email addresses
        email_pattern = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
        emails = re.findall(email_pattern, full_text)
        for email in emails[:5]:
            entities.append({
                'text': email,
                'type': 'EMAIL',
                'confidence': 0.9
            })
        
        # Money amounts
        money_pattern = r'\$\d{1,3}(?:,\d{3})*(?:\.\d{2})?|\$\d+(?:\.\d{2})?[KMB]?'
        money_amounts = re.findall(money_pattern, full_text)
        for amount in money_amounts[:10]:
            entities.append({
                'text': amount,
                'type': 'MONEY',
                'confidence': 0.8
            })
        
        # Percentages
        percent_pattern = r'\d+(?:\.\d+)?%'
        percentages = re.findall(percent_pattern, full_text)
        for percent in percentages[:10]:
            entities.append({
                'text': percent,
                'type': 'PERCENT',
                'confidence': 0.9
            })
        
        # Capitalized phrases (potential proper nouns)
        proper_noun_pattern = r'\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)+\b'
        proper_nouns = re.findall(proper_noun_pattern, full_text)
        for noun in proper_nouns[:15]:
            if len(noun.split()) >= 2:
                entities.append({
                    'text': noun,
                    'type': 'PROPER_NOUN',
                    'confidence': 0.5
                })
        
        return entities
    
    async def _generate_document_embedding(self, 
                                         summary: str, 
                                         structured_text: dict[str, Any]) -> Optional[np.ndarray]:
        """
        Generate a comprehensive document-level vector embedding representing the entire document's semantic content.

        This method creates a single vector embedding that captures the overall semantic
        meaning of the document by combining the document summary with key structural
        elements such as headers and introductory content. The resulting embedding
        enables document-level similarity comparison and semantic search operations.

        The embedding generation process prioritizes the most informative content
        including the summary and key headers from the first few pages to create
        a representative document vector.

        Args:
            summary (str): Comprehensive document summary generated by _generate_document_summary
                containing the most important sentences and key information from the document.
            structured_text (dict[str, Any]): Structured text representation containing
                pages with elements for header and title extraction. Used to supplement
                the summary with structural information.

        Returns:
            Optional[np.ndarray]: Document-level embedding vector as numpy array with
                dimensions matching the configured sentence transformer model output.
                Returns None if embedding generation fails or no embedding model is available.

        Raises:
            RuntimeError: If embedding model is unavailable when required.
            ValueError: If summary is empty or structured_text contains no usable content.
            MemoryError: If document content is too large for embedding generation.

        Examples:
            >>> summary = "This research paper presents novel machine learning approaches..."
            >>> structured_text = {
            ...     'pages': [
            ...         {
            ...             'elements': [
            ...                 {'content': 'Introduction', 'type': 'header'},
            ...                 {'content': 'Machine Learning Overview', 'type': 'title'}
            ...             ]
            ...         }
            ...     ]
            ... }
            >>> doc_embedding = await optimizer._generate_document_embedding(summary, structured_text)
            >>> print(doc_embedding.shape)  # (384,) for all-MiniLM-L6-v2
            >>> print(type(doc_embedding))  # <class 'numpy.ndarray'>
        """
        if not self.embedding_model:
            raise RuntimeError("No embedding model available for document embedding generation")
        
        # Combine summary with key parts of document
        doc_text = summary
        
        # Add key headers and first paragraphs
        for page in structured_text['pages'][:3]:  # First 3 pages
            for element in page['elements'][:5]:  # First 5 elements per page
                if element['type'] in ['header', 'title']:
                    doc_text += " " + element['content']
        
        try:
            embedding = self.embedding_model.encode(
                doc_text,
                convert_to_numpy=True,
                show_progress_bar=False
            )
            return embedding
        except Exception as e:
            logger.error(f"Failed to generate document embedding: {e}")
            return None
    
    def _count_tokens(self, text: str) -> int:
        """
        Count the number of tokens in text using the configured tokenizer.

        This method provides accurate token counting using the initialized tokenizer, which is
        essential for chunk size management and LLM compatibility. It handles both tiktoken
        tokenizers (for OpenAI models) and HuggingFace tokenizers.
    
        Accurate token counting ensures chunks remain within LLM context limits and enables
        precise overlap calculations for optimal chunk boundary management.

        Args:
            text (str): Input text to count tokens for. Can be empty string or any length
                of text content. Whitespace and formatting are preserved for accurate counting.

        Returns:
            int: Number of tokens in the input text according to the configured tokenizer.
                Returns 0 for empty input.

        Raises:
            RuntimeError: If no tokenizer is available for token counting.

        Examples:
            >>> text = "This is a sample text for token counting."
            >>> token_count = optimizer._count_tokens(text)
            >>> print(token_count)  # Exact count based on tokenizer (e.g., 9)
            
            >>> # Empty text handling
            >>> empty_count = optimizer._count_tokens("")
            >>> print(empty_count)  # 0
        """
        if not text:
            return 0

        if self.tokenizer is None:
            raise RuntimeError("No tokenizer available for token counting")

        try:
            if hasattr(self.tokenizer, 'encode'):
                # tiktoken or similar
                return len(self.tokenizer.encode(text))
            else:
                # HuggingFace tokenizer
                return len(self.tokenizer.tokenize(text))
        except Exception as e:
            raise RuntimeError("Token counting failed") from e
    
    def _get_chunk_overlap(self, content: str) -> str:
        """
        Extract overlap content from the end of a chunk to maintain context continuity between adjacent chunks.

        This method generates overlap text that preserves narrative flow and context when
        creating new chunks. It extracts the final portion of the current chunk content
        to be included at the beginning of the next chunk, ensuring that important context
        and relationships are maintained across chunk boundaries.

        The overlap extraction uses word-based approximation to respect the configured
        chunk_overlap token limit while preserving complete words and natural language structure.

        Args:
            content (str): The text content from which to extract overlap. Should be the
                complete content of the current chunk from which overlap will be taken.
                Can handle empty strings gracefully.

        Returns:
            str: Overlap text extracted from the end of the input content. Contains
                approximately chunk_overlap/4 words (to approximate token count) from
                the end of the content. Returns empty string if content is empty or
                insufficient for overlap extraction.

        Raises:
            No exceptions are raised. Method handles edge cases gracefully including
            empty content, very short content, and content shorter than overlap requirements.

        Examples:
            >>> content = "This is a long paragraph with multiple sentences. It contains important context information that should be preserved across chunk boundaries for optimal LLM processing."
            >>> overlap = optimizer._get_chunk_overlap(content)
            >>> print(overlap)  # "preserved across chunk boundaries for optimal LLM processing."
            
            >>> # Short content handling
            >>> short_content = "Brief text."
            >>> overlap = optimizer._get_chunk_overlap(short_content)
            >>> print(overlap)  # "Brief text." (entire content if shorter than overlap)
            
            >>> # Empty content handling
            >>> empty_overlap = optimizer._get_chunk_overlap("")
            >>> print(empty_overlap)  # ""
        """
        if not content:
            return ""
        
        # Get last N tokens for overlap
        words = content.split()
        overlap_words = min(self.chunk_overlap // 4, len(words))  # Approximate word count
        
        if overlap_words > 0:
            return " ".join(words[-overlap_words:])
        return ""

# Utility classes for text processing
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
    
    def split_sentences(self, text: str) -> list[str]:
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
            list[str]: list of individual sentences with leading/trailing whitespace stripped.
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
        if not isinstance(text, str):
            if text is None:
                raise TypeError("Input text cannot be None")
            raise TypeError(f"Input must be string, got {type(text).__name__}")
        
        if not text.strip():
            return []
        
        # Common abbreviations that should not split sentences
        abbreviations = {
            'Dr.', 'Mr.', 'Mrs.', 'Ms.', 'Prof.', 'Ph.D.', 'M.D.', 'B.A.', 'M.A.', 'M.S.',
            'B.S.', 'Ph.D', 'LLC.', 'Inc.', 'Corp.', 'Ltd.', 'Co.', 'vs.', 'etc.', 'i.e.',
            'e.g.', 'al.', 'et.', 'Jan.', 'Feb.', 'Mar.', 'Apr.', 'Jun.', 'Jul.', 'Aug.',
            'Sep.', 'Sept.', 'Oct.', 'Nov.', 'Dec.', 'U.S.', 'U.K.', 'U.S.A.', 'a.m.', 'p.m.',
            'A.M.', 'P.M.', 'St.', 'Ave.', 'Blvd.', 'Rd.', 'Jr.', 'Sr.', 'II.', 'III.', 'IV.'
        }
        
        # Create a temporary marker for abbreviations to protect them
        protected_text = text
        abbrev_markers = {}
        
        for i, abbrev in enumerate(abbreviations):
            if abbrev in protected_text:
                marker = f"__ABBREV_{i}__"
                abbrev_markers[marker] = abbrev
                protected_text = protected_text.replace(abbrev, marker)
        
        # Protect decimal numbers (e.g., 3.14, 15.7%)
        decimal_pattern = r'\b\d+\.\d+\b'
        decimals = re.findall(decimal_pattern, protected_text)
        decimal_markers = {}
        
        for i, decimal in enumerate(decimals):
            marker = f"__DECIMAL_{i}__"
            decimal_markers[marker] = decimal
            protected_text = protected_text.replace(decimal, marker)
        
        # Split on sentence terminators including Unicode punctuation
        # ASCII: . ! ?
        # Unicode: 。 ！ ？ … (Chinese/Japanese punctuation)
        sentence_pattern = r'[.!?。！？]+(?:\s|$)'
        
        # Split sentences
        sentences = re.split(sentence_pattern, protected_text)
        
        # Restore protected abbreviations and decimals
        restored_sentences = []
        for sentence in sentences:
            if sentence.strip():  # Skip empty sentences
                # Restore decimals
                for marker, original in decimal_markers.items():
                    sentence = sentence.replace(marker, original)
                
                # Restore abbreviations
                for marker, original in abbrev_markers.items():
                    sentence = sentence.replace(marker, original)
                
                restored_sentences.append(sentence.strip())
        
        return restored_sentences
    
    def extract_keywords(self, text: str, top_k: int = 20) -> list[str]:
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
            list[str]: Ordered list of the most significant keywords ranked by frequency
                and importance. Each keyword is a lowercase string with stop words removed.
                list length may be less than top_k if insufficient unique keywords exist.
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
        if not isinstance(top_k, int) or top_k <= 0:
            print(f"Invalid top_k value: {top_k}. Using default value of 20.")
            top_k = 20

        if not isinstance(text, str):
            return []

        # Simple keyword extraction based on frequency
        words = re.findall(r'\b[a-zA-Z]{3,}\b', text.lower())
        
        # Filter common stop words
        stop_words = {
            'the', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for', 
            'of', 'with', 'by', 'this', 'that', 'these', 'those', 'is', 
            'are', 'was', 'were', 'be', 'been', 'being', 'have', 'has', 
            'had', 'do', 'does', 'did', 'will', 'would', 'could', 'should',
            'can', 'very', 'most', 'able', 'way', 'make', 'it', 'from', 
            'a', 'an'
        }

        filtered_words = [w for w in words if w not in stop_words]
        
        # Count frequency
        word_freq = {}
        for word in filtered_words:
            word_freq[word] = word_freq.get(word, 0) + 1
        
        # Return top keywords
        sorted_words = sorted(word_freq.items(), key=lambda x: x[1], reverse=True)
        return [word for word, freq in sorted_words[:top_k]]

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
        if not isinstance(max_size, int) or not isinstance(overlap, int) or not isinstance(min_size, int):
            raise TypeError("max_size, overlap, and min_size must be integers.")

        if max_size <= 0 or min_size <= 0:
            raise ValueError("max_size and min_size must be positive integers")
        if overlap <= 0:
            raise ValueError("overlap must be non-negative.")

        if max_size <= min_size:
            raise ValueError("max_size must be greater than min_size.")
        if overlap >= max_size:
            raise ValueError("overlap must be less than max_size.")

        self.max_size = max_size
        self.overlap = overlap
        self.min_size = min_size
    
    def optimize_chunk_boundaries(self, text: str, current_boundaries: list[int]) -> list[int]:
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
            current_boundaries (list[int]): list of current character positions where chunk
                boundaries are planned. These positions will be analyzed and potentially
                adjusted to align with natural language structures.

        Returns:
            list[int]: Optimized boundary positions that respect natural language structure
                while maintaining reasonable proximity to the original positions. Boundaries
                are adjusted to align with sentence endings or paragraph breaks when possible,
                falling back to original positions when natural boundaries are not available.

        Raises:
            ValueError: If text is empty or current_boundaries contain invalid positions.
            TypeError: If current_boundaries is not a list or contains non-integer values.
            IndexError: If boundary positions exceed text length (handled with boundary clamping).

        Examples:
            >>> text = "First sentence. Second sentence.\\n\\nNew paragraph starts here. Another sentence."
            >>> boundaries = [25, 50]  # Arbitrary positions
            >>> optimizer = ChunkOptimizer(max_size=1024, overlap=100, min_size=50)
            >>> optimized = optimizer.optimize_chunk_boundaries(text, boundaries)
            >>> print(optimized)  # Adjusted to align with sentence/paragraph breaks
            
            >>> # Complex document with multiple paragraph breaks
            >>> long_text = "Para 1 content...\\n\\nPara 2 content...\\n\\nPara 3 content..."
            >>> rough_boundaries = [100, 200, 300]
            >>> optimized = optimizer.optimize_chunk_boundaries(long_text, rough_boundaries)
            >>> # Returns positions aligned with paragraph boundaries
        """
        if not isinstance(text, str):
            raise TypeError("Text must be a string.")
    
        if not text:
            raise ValueError("Text cannot be empty.")

        # Validate that all boundaries are integers
        for i, boundary in enumerate(current_boundaries):
            if not isinstance(boundary, int):
                raise TypeError(f"Boundary at index {i} must be an integer, got {type(boundary).__name__}")
            if boundary < 0:
                raise ValueError(f"Boundary at index {i} cannot be negative: {boundary}")

        text_length = len(text)

        # Find sentence boundaries
        sentence_ends = []
        for match in re.finditer(r'[.!?]+\s+', text):
            sentence_ends.append(match.end())
        
        # Find paragraph boundaries  
        paragraph_ends = []
        for match in re.finditer(r'\n\s*\n', text):
            paragraph_ends.append(match.end())
        
        optimized_boundaries = []
        
        for boundary in current_boundaries:
            # Clamp boundary to text length
            clamped_boundary = min(boundary, text_length)
            
            # Find closest sentence or paragraph boundary
            closest_sentence = min(sentence_ends, key=lambda x: abs(x - clamped_boundary), default=clamped_boundary)
            closest_paragraph = min(paragraph_ends, key=lambda x: abs(x - clamped_boundary), default=clamped_boundary)
            
            # Prefer paragraph boundaries, then sentence boundaries
            if abs(closest_paragraph - clamped_boundary) <= 50:  # Within 50 characters
                optimized_boundaries.append(closest_paragraph)
            elif abs(closest_sentence - clamped_boundary) <= 25:  # Within 25 characters
                optimized_boundaries.append(closest_sentence)
            else:
                optimized_boundaries.append(clamped_boundary)
        
        return optimized_boundaries
