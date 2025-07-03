import pytest


class TestLLMOptimizerInitialization:
    """Test LLMOptimizer initialization and configuration."""

    def test_init_with_default_parameters(self):
        """
        GIVEN no parameters provided to LLMOptimizer constructor
        WHEN LLMOptimizer is initialized
        THEN expect:
            - Instance created successfully
            - model_name set to "sentence-transformers/all-MiniLM-L6-v2"
            - tokenizer_name set to "gpt-3.5-turbo"
            - max_chunk_size set to 2048
            - chunk_overlap set to 200
            - min_chunk_size set to 100
            - _initialize_models called during initialization
        """

    def test_init_with_custom_parameters(self):
        """
        GIVEN custom parameters:
            - model_name: "sentence-transformers/paraphrase-MiniLM-L6-v2"
            - tokenizer_name: "gpt-4"
            - max_chunk_size: 4096
            - chunk_overlap: 400
            - min_chunk_size: 150
        WHEN LLMOptimizer is initialized
        THEN expect:
            - Instance created successfully
            - All attributes set to provided custom values
            - _initialize_models called with custom configuration
        """

    def test_init_with_zero_min_chunk_size(self):
        """
        GIVEN min_chunk_size parameter set to 0
        WHEN LLMOptimizer is initialized
        THEN expect:
            - Instance created successfully
            - min_chunk_size attribute set to 0
            - No validation errors during initialization
        """

    def test_init_with_overlap_larger_than_max_chunk(self):
        """
        GIVEN parameters where:
            - max_chunk_size: 1000
            - chunk_overlap: 1500 (larger than max_chunk_size)
        WHEN LLMOptimizer is initialized
        THEN expect:
            - Instance created successfully
            - Values stored as provided (validation may occur later in processing)
        """

    def test_init_with_negative_chunk_sizes(self):
        """
        GIVEN negative values for:
            - max_chunk_size: -100
            - chunk_overlap: -50
            - min_chunk_size: -25
        WHEN LLMOptimizer is initialized
        THEN expect:
            - Instance created successfully
            - Negative values stored (validation may occur during processing)
        """

    def test_init_with_empty_model_names(self):
        """
        GIVEN empty strings for:
            - model_name: ""
            - tokenizer_name: ""
        WHEN LLMOptimizer is initialized
        THEN expect:
            - Instance created successfully
            - Empty strings stored as model names
            - _initialize_models may handle empty names appropriately
        """

    def test_init_calls_initialize_models(self):
        """
        GIVEN valid initialization parameters
        WHEN LLMOptimizer is initialized
        THEN expect:
            - _initialize_models method is called exactly once
            - Method called after attribute assignment
        """







class TestLLMOptimizerInitializeModels:
    """Test LLMOptimizer._initialize_models method."""

    def test_initialize_models_with_gpt_tokenizer(self):
        """
        GIVEN LLMOptimizer with tokenizer_name containing "gpt"
        WHEN _initialize_models is called
        THEN expect:
            - tiktoken tokenizer is initialized for OpenAI model
            - SentenceTransformer model is loaded successfully
            - embedding_model attribute is set to SentenceTransformer instance
            - tokenizer attribute is set to tiktoken encoder
            - No exceptions raised during initialization
        """

    def test_initialize_models_with_huggingface_tokenizer(self):
        """
        GIVEN LLMOptimizer with tokenizer_name not containing "gpt"
        WHEN _initialize_models is called
        THEN expect:
            - HuggingFace AutoTokenizer is initialized
            - SentenceTransformer model is loaded successfully
            - embedding_model attribute is set to SentenceTransformer instance
            - tokenizer attribute is set to AutoTokenizer instance
            - No exceptions raised during initialization
        """

    def test_initialize_models_with_invalid_embedding_model(self):
        """
        GIVEN LLMOptimizer with invalid/non-existent model_name
        WHEN _initialize_models is called
        THEN expect:
            - Exception is caught and logged
            - embedding_model attribute is set to None
            - tokenizer initialization continues despite embedding failure
            - Method completes without raising exception
        """

    def test_initialize_models_with_invalid_tokenizer(self):
        """
        GIVEN LLMOptimizer with invalid/non-existent tokenizer_name
        WHEN _initialize_models is called
        THEN expect:
            - Exception is caught and logged during tokenizer initialization
            - tokenizer attribute is set to None or fallback method
            - embedding_model initialization continues if valid
            - Method completes without raising exception
        """

    def test_initialize_models_fallback_mechanism(self):
        """
        GIVEN LLMOptimizer where both model and tokenizer initialization fail
        WHEN _initialize_models is called
        THEN expect:
            - Both exceptions are caught and logged
            - embedding_model attribute is set to None
            - tokenizer attribute is set to None or fallback
            - System continues with reduced functionality
            - No exceptions propagated to caller
        """

    def test_initialize_models_sets_text_processor(self):
        """
        GIVEN LLMOptimizer instance
        WHEN _initialize_models is called
        THEN expect:
            - text_processor attribute is initialized
            - text_processor is instance of TextProcessor class
        """

    def test_initialize_models_sets_chunk_optimizer(self):
        """
        GIVEN LLMOptimizer instance with chunk size parameters
        WHEN _initialize_models is called
        THEN expect:
            - chunk_optimizer attribute is initialized
            - chunk_optimizer is instance of ChunkOptimizer class
            - ChunkOptimizer initialized with max_chunk_size, chunk_overlap, min_chunk_size
        """







class TestLLMOptimizerOptimizeForLLM:
    """Test LLMOptimizer.optimize_for_llm method."""

    def test_optimize_for_llm_with_valid_content(self):
        """
        GIVEN valid decomposed_content dict containing:
            - 'pages': List of page dictionaries with elements and content
            - 'metadata': Document-level metadata and properties
            - 'structure': Structural hierarchy information
        AND valid document_metadata dict containing:
            - document_id: "doc_001"
            - title: "Test Document"
        WHEN optimize_for_llm is called
        THEN expect:
            - LLMDocument instance returned
            - Document contains processed chunks with embeddings
            - Document summary is generated
            - Key entities are extracted
            - Processing metadata is populated
            - All async operations complete successfully
        """

    def test_optimize_for_llm_empty_decomposed_content(self):
        """
        GIVEN decomposed_content with empty pages list
        AND valid document_metadata
        WHEN optimize_for_llm is called
        THEN expect:
            - LLMDocument instance returned
            - Empty chunks list
            - Empty or minimal summary
            - Empty key entities list
            - Processing metadata indicates no content processed
        """

    def test_optimize_for_llm_missing_pages_key(self):
        """
        GIVEN decomposed_content missing 'pages' key
        AND valid document_metadata
        WHEN optimize_for_llm is called
        THEN expect:
            - KeyError raised or graceful handling
            - Method handles missing required structure appropriately
        """

    def test_optimize_for_llm_invalid_document_metadata(self):
        """
        GIVEN valid decomposed_content
        AND document_metadata missing required keys (document_id, title)
        WHEN optimize_for_llm is called
        THEN expect:
            - Method handles missing metadata gracefully
            - Default values used for missing fields
            - LLMDocument instance returned with available data
        """

    def test_optimize_for_llm_calls_all_processing_steps(self):
        """
        GIVEN valid decomposed_content and document_metadata
        WHEN optimize_for_llm is called
        THEN expect all processing methods called in sequence:
            - _extract_structured_text called with decomposed_content
            - _generate_document_summary called with structured_text
            - _create_optimal_chunks called with structured_text and decomposed_content
            - _establish_chunk_relationships called with chunks
            - _generate_embeddings called with chunks
            - _extract_key_entities called with structured_text
            - _generate_document_embedding called with summary and structured_text
        """

    def test_optimize_for_llm_handles_processing_exceptions(self):
        """
        GIVEN decomposed_content that causes exceptions in processing steps
        WHEN optimize_for_llm is called
        THEN expect:
            - Exceptions are caught and logged appropriately
            - Processing continues with fallback values where possible
            - LLMDocument returned even with partial processing failures
            - Error information included in processing metadata
        """

    def test_optimize_for_llm_populates_llm_document_correctly(self):
        """
        GIVEN valid inputs that complete processing successfully
        WHEN optimize_for_llm is called
        THEN expect returned LLMDocument contains:
            - document_id from document_metadata
            - title from document_metadata or extracted from content
            - chunks list with processed LLMChunk objects
            - summary string from document analysis
            - key_entities list with extracted entities
            - processing_metadata with timestamps and statistics
            - document_embedding array if embedding generation succeeds
        """








class TestLLMOptimizerExtractStructuredText:
    """Test LLMOptimizer._extract_structured_text method."""

    def test_extract_structured_text_with_valid_content(self):
        """
        GIVEN decomposed_content with:
            - 'pages': List containing pages with text elements
            - 'metadata': Document metadata
            - 'structure': Document structure information
        WHEN _extract_structured_text is called
        THEN expect:
            - Dict returned with 'pages', 'metadata', 'structure' keys
            - Only elements with type 'text' are processed
            - Element subtypes preserved for semantic classification
            - Positional and style information maintained
            - Page-level full text aggregated
        """

    def test_extract_structured_text_filters_text_elements_only(self):
        """
        GIVEN decomposed_content with pages containing mixed element types:
            - Elements with type 'text'
            - Elements with type 'image'
            - Elements with type 'table'
        WHEN _extract_structured_text is called
        THEN expect:
            - Only elements with type 'text' included in output
            - Non-text elements filtered out
            - Text element count matches filtered result
        """

    def test_extract_structured_text_preserves_element_metadata(self):
        """
        GIVEN decomposed_content with text elements containing:
            - content: Text content
            - subtype: Element subtype (paragraph, header, etc.)
            - position: Positional information
            - style: Style information
            - confidence: Confidence score
        WHEN _extract_structured_text is called
        THEN expect:
            - All element metadata preserved in output
            - Subtype information maintained for semantic processing
            - Position and style data available for context-aware chunking
        """

    def test_extract_structured_text_empty_pages(self):
        """
        GIVEN decomposed_content with empty pages list
        WHEN _extract_structured_text is called
        THEN expect:
            - Dict returned with empty pages list
            - Metadata and structure preserved from input
            - No processing errors for empty content
        """

    def test_extract_structured_text_pages_without_text_elements(self):
        """
        GIVEN decomposed_content with pages containing no 'text' type elements
        WHEN _extract_structured_text is called
        THEN expect:
            - Pages included in output but with empty or minimal elements
            - Full text for pages is empty or minimal
            - Structure preserved despite lack of text content
        """

    def test_extract_structured_text_aggregates_page_full_text(self):
        """
        GIVEN decomposed_content with pages containing multiple text elements
        WHEN _extract_structured_text is called
        THEN expect:
            - Each page has aggregated full_text from all text elements
            - Full text maintains order of elements within page
            - Text elements concatenated appropriately
        """

    def test_extract_structured_text_preserves_original_metadata(self):
        """
        GIVEN decomposed_content with metadata and structure sections
        WHEN _extract_structured_text is called
        THEN expect:
            - Original metadata preserved unchanged in output
            - Original structure information preserved unchanged
            - Only pages section is processed and modified
        """








class TestLLMOptimizerGenerateDocumentSummary:
    """Test LLMOptimizer._generate_document_summary method."""

    def test_generate_document_summary_with_valid_content(self):
        """
        GIVEN structured_text with pages containing full_text content
        WHEN _generate_document_summary is called
        THEN expect:
            - String summary returned
            - Summary contains key themes and information
            - Summary composed of highest-scoring sentences
            - Summary length optimized for overview purposes
            - Extractive summarization preserves original phrasing
        """

    def test_generate_document_summary_analyzes_first_50_sentences(self):
        """
        GIVEN structured_text with content containing more than 50 sentences
        WHEN _generate_document_summary is called
        THEN expect:
            - Only first 50 sentences analyzed for computational efficiency
            - Remaining sentences ignored in analysis
            - Summary generated from analyzed subset
        """

    def test_generate_document_summary_scores_by_position(self):
        """
        GIVEN structured_text with sentences at different positions
        WHEN _generate_document_summary is called
        THEN expect:
            - Earlier sentences receive higher position weighting
            - Position scoring influences final sentence selection
            - Document opening content prioritized in summary
        """

    def test_generate_document_summary_keyword_frequency_analysis(self):
        """
        GIVEN structured_text with sentences containing varying keyword frequencies
        WHEN _generate_document_summary is called
        THEN expect:
            - Keyword frequency analysis performed
            - Sentences with topically relevant keywords scored higher
            - High-frequency keywords contribute to sentence importance
        """

    def test_generate_document_summary_length_optimization(self):
        """
        GIVEN structured_text with sentences of varying lengths
        WHEN _generate_document_summary is called
        THEN expect:
            - Sentences between 10-30 words favored in scoring
            - Very short or very long sentences penalized
            - Length optimization improves summary readability
        """

    def test_generate_document_summary_returns_top_5_sentences(self):
        """
        GIVEN structured_text with sufficient content for analysis
        WHEN _generate_document_summary is called
        THEN expect:
            - Top 5 sentences by importance score included
            - Sentences ordered by importance in summary
            - Exactly 5 sentences unless insufficient content available
        """

    def test_generate_document_summary_empty_content(self):
        """
        GIVEN structured_text with empty or minimal content
        WHEN _generate_document_summary is called
        THEN expect:
            - Empty string or minimal summary returned
            - No errors raised for insufficient content
            - Graceful handling of edge case
        """

    def test_generate_document_summary_single_sentence_content(self):
        """
        GIVEN structured_text containing only one sentence
        WHEN _generate_document_summary is called
        THEN expect:
            - Single sentence returned as summary
            - No errors for insufficient sentence count
            - Summary maintains original sentence content
        """








class TestLLMOptimizerCreateOptimalChunks:
    """Test LLMOptimizer._create_optimal_chunks method."""

    def test_create_optimal_chunks_respects_token_limits(self):
        """
        GIVEN structured_text with content exceeding max_chunk_size
        AND decomposed_content with element information
        WHEN _create_optimal_chunks is called
        THEN expect:
            - All returned chunks respect max_chunk_size token limit
            - No chunk exceeds configured maximum tokens
            - Token counting performed accurately for size management
        """

    def test_create_optimal_chunks_maintains_semantic_boundaries(self):
        """
        GIVEN structured_text with clear semantic boundaries (paragraphs, sections)
        WHEN _create_optimal_chunks is called
        THEN expect:
            - Chunks break at semantic boundaries when possible
            - Paragraphs and sections not split mid-content
            - Semantic coherence preserved within chunks
        """

    def test_create_optimal_chunks_implements_overlap(self):
        """
        GIVEN structured_text requiring multiple chunks
        WHEN _create_optimal_chunks is called
        THEN expect:
            - Adjacent chunks have overlap content for context preservation
            - Overlap size matches configured chunk_overlap parameter
            - Overlapping content maintains narrative flow between chunks
        """

    def test_create_optimal_chunks_establishes_relationships(self):
        """
        GIVEN structured_text processed into multiple chunks
        WHEN _create_optimal_chunks is called
        THEN expect:
            - Sequential chunk relationships established
            - Related chunks identified based on content proximity
            - Relationship lists populated for context-aware processing
        """

    def test_create_optimal_chunks_classifies_semantic_types(self):
        """
        GIVEN structured_text with elements of different types:
            - Regular paragraph content
            - Table data
            - Headers and titles
            - Figure captions
        WHEN _create_optimal_chunks is called
        THEN expect:
            - Chunks classified by primary semantic type
            - Mixed content identified appropriately
            - Semantic type affects chunk processing decisions
        """

    def test_create_optimal_chunks_preserves_source_information(self):
        """
        GIVEN structured_text with page and element source information
        WHEN _create_optimal_chunks is called
        THEN expect:
            - Each chunk contains source_page information
            - source_element type preserved from original content
            - Source tracking enables traceability to original document
        """

    def test_create_optimal_chunks_optimizes_boundaries(self):
        """
        GIVEN content that could break at suboptimal positions
        WHEN _create_optimal_chunks is called
        THEN expect:
            - Chunk boundaries optimized to avoid breaking sentences mid-content
            - Paragraph boundaries preferred over arbitrary character positions
            - Boundary optimization improves chunk coherence
        """

    def test_create_optimal_chunks_handles_empty_content(self):
        """
        GIVEN structured_text with empty or minimal content
        WHEN _create_optimal_chunks is called
        THEN expect:
            - Empty list returned or single minimal chunk
            - No errors raised for insufficient content
            - Graceful handling of edge case
        """

    def test_create_optimal_chunks_sequential_ordering(self):
        """
        GIVEN structured_text with content from multiple pages
        WHEN _create_optimal_chunks is called
        THEN expect:
            - Chunks returned in sequential document order
            - Page order preserved in chunk sequence
            - Within-page element order maintained
        """








class TestLLMOptimizerCreateChunk:
    """Test LLMOptimizer._create_chunk method."""

    def test_create_chunk_with_valid_parameters(self):
        """
        GIVEN valid parameters:
            - content: "Sample text content for chunk"
            - chunk_id: 15
            - page_num: 3
            - metadata: {"semantic_types": ["text"], "source_elements": ["paragraph"]}
        WHEN _create_chunk is called
        THEN expect:
            - LLMChunk instance returned
            - content set to provided text
            - chunk_id formatted as "chunk_0015" with zero-padding
            - source_page set to 3
            - token_count calculated using configured tokenizer
            - relationships list initialized as empty
        """

    def test_create_chunk_formats_chunk_id_with_zero_padding(self):
        """
        GIVEN chunk_id values: 1, 15, 100, 9999
        WHEN _create_chunk is called for each
        THEN expect chunk IDs formatted as:
            - "chunk_0001"
            - "chunk_0015" 
            - "chunk_0100"
            - "chunk_9999"
        """

    def test_create_chunk_determines_semantic_type_from_metadata(self):
        """
        GIVEN metadata with different semantic_types:
            - {"semantic_types": ["text"]} -> semantic_type: "text"
            - {"semantic_types": ["table"]} -> semantic_type: "table"
            - {"semantic_types": ["header"]} -> semantic_type: "header"
            - {"semantic_types": ["text", "table"]} -> semantic_type: "mixed"
        WHEN _create_chunk is called
        THEN expect:
            - semantic_type determined with priority rules
            - Mixed content classified as "mixed"
            - Primary type selected for single-type content
        """

    def test_create_chunk_calculates_token_count(self):
        """
        GIVEN content with known token characteristics
        WHEN _create_chunk is called
        THEN expect:
            - token_count calculated using _count_tokens method
            - Token count reflects actual tokenizer output
            - Count used for chunk size validation
        """

    def test_create_chunk_includes_creation_timestamp(self):
        """
        GIVEN valid chunk creation parameters
        WHEN _create_chunk is called
        THEN expect:
            - metadata includes creation_timestamp
            - Timestamp reflects current time during creation
            - Timestamp useful for processing tracking
        """

    def test_create_chunk_includes_source_element_statistics(self):
        """
        GIVEN metadata containing source_elements information
        WHEN _create_chunk is called
        THEN expect:
            - metadata includes source element statistics
            - Element counts and types preserved
            - Statistics useful for chunk analysis
        """

    def test_create_chunk_sets_source_element_from_metadata(self):
        """
        GIVEN metadata with source_elements: ["paragraph", "header"]
        WHEN _create_chunk is called
        THEN expect:
            - source_element set to primary element type from metadata
            - Multiple source elements handled appropriately
            - Source tracking preserved for traceability
        """

    def test_create_chunk_initializes_empty_relationships(self):
        """
        GIVEN any valid chunk creation parameters
        WHEN _create_chunk is called
        THEN expect:
            - relationships list initialized as empty
            - List ready for later population by relationship establishment
            - No relationships assumed during individual chunk creation
        """

    def test_create_chunk_handles_empty_content(self):
        """
        GIVEN empty content string
        WHEN _create_chunk is called
        THEN expect:
            - LLMChunk created with empty content
            - token_count set to 0
            - Other metadata populated normally
        """








class TestLLMOptimizerEstablishChunkRelationships:
    """Test LLMOptimizer._establish_chunk_relationships method."""

    def test_establish_chunk_relationships_creates_sequential_relationships(self):
        """
        GIVEN list of chunks in sequential document order:
            - chunk_0001, chunk_0002, chunk_0003
        WHEN _establish_chunk_relationships is called
        THEN expect:
            - chunk_0001 relationships include chunk_0002
            - chunk_0002 relationships include chunk_0001 and chunk_0003
            - chunk_0003 relationships include chunk_0002
            - All sequential adjacencies captured
        """

    def test_establish_chunk_relationships_connects_same_page_chunks(self):
        """
        GIVEN chunks from same source page:
            - chunk_0001 (page 1), chunk_0002 (page 1), chunk_0005 (page 1)
        AND chunks from different pages:
            - chunk_0003 (page 2), chunk_0004 (page 3)
        WHEN _establish_chunk_relationships is called
        THEN expect:
            - Same-page chunks have relationships to each other
            - Different-page chunks not connected by page relationship
            - Page-based grouping preserved in relationships
        """

    def test_establish_chunk_relationships_limits_relationship_count(self):
        """
        GIVEN large number of chunks that could create many relationships
        WHEN _establish_chunk_relationships is called
        THEN expect:
            - Relationship lists limited to prevent performance degradation
            - Most relevant relationships preserved
            - Excessive connections pruned appropriately
        """

    def test_establish_chunk_relationships_creates_bidirectional_connections(self):
        """
        GIVEN chunks with established relationships
        WHEN _establish_chunk_relationships is called
        THEN expect:
            - All relationships are bidirectional
            - If chunk A relates to chunk B, then chunk B relates to chunk A
            - Symmetric relationship mapping maintained
        """

    def test_establish_chunk_relationships_handles_single_chunk(self):
        """
        GIVEN list containing only one chunk
        WHEN _establish_chunk_relationships is called
        THEN expect:
            - Single chunk has empty relationships list
            - No self-referential relationships created
            - Method handles edge case gracefully
        """

    def test_establish_chunk_relationships_handles_empty_chunk_list(self):
        """
        GIVEN empty list of chunks
        WHEN _establish_chunk_relationships is called
        THEN expect:
            - Empty list returned unchanged
            - No errors raised for empty input
            - Graceful handling of edge case
        """

    def test_establish_chunk_relationships_preserves_chunk_order(self):
        """
        GIVEN chunks in specific order
        WHEN _establish_chunk_relationships is called
        THEN expect:
            - Original chunk order preserved in returned list
            - Only relationships lists modified
            - Chunk sequence unchanged
        """

    def test_establish_chunk_relationships_considers_semantic_proximity(self):
        """
        GIVEN chunks with similar semantic types or content themes
        WHEN _establish_chunk_relationships is called
        THEN expect:
            - Semantically similar chunks may have relationships
            - Proximity based on content similarity considered
            - Related concepts connected across document sections
        """

    def test_establish_chunk_relationships_returns_same_chunks_modified(self):
        """
        GIVEN list of LLMChunk objects
        WHEN _establish_chunk_relationships is called
        THEN expect:
            - Same LLMChunk instances returned (not copies)
            - Only relationships attribute modified on existing objects
            - Object identity preserved throughout process
        """








class TestLLMOptimizerGenerateEmbeddings:
    """Test LLMOptimizer._generate_embeddings method."""

    def test_generate_embeddings_with_valid_chunks(self):
        """
        GIVEN list of LLMChunk objects with content
        AND embedding_model is available and functional
        WHEN _generate_embeddings is called
        THEN expect:
            - Each chunk gets embedding attribute populated
            - Embeddings are numpy arrays with consistent dimensions
            - All chunks processed successfully
            - Method returns same chunks with embeddings added
        """

    def test_generate_embeddings_processes_in_batches(self):
        """
        GIVEN list of more than 32 chunks
        WHEN _generate_embeddings is called
        THEN expect:
            - Chunks processed in batches of 32 for optimal performance
            - All batches processed completely
            - Batch processing improves computational efficiency
            - Final result includes embeddings for all chunks
        """

    def test_generate_embeddings_handles_embedding_failures(self):
        """
        GIVEN chunks where embedding generation fails for some batches
        WHEN _generate_embeddings is called
        THEN expect:
            - Failures handled gracefully without stopping processing
            - Failed chunks retain None embedding values
            - Successful chunks get proper embedding arrays
            - Processing continues with remaining batches
        """

    def test_generate_embeddings_with_no_embedding_model(self):
        """
        GIVEN LLMOptimizer with embedding_model set to None
        WHEN _generate_embeddings is called
        THEN expect:
            - Method skips embedding generation entirely
            - All chunks retain None for embedding attribute
            - No errors raised for missing model
            - Chunks returned unchanged
        """

    def test_generate_embeddings_returns_numpy_arrays(self):
        """
        GIVEN successful embedding generation
        WHEN _generate_embeddings is called
        THEN expect:
            - embedding attributes are numpy.ndarray instances
            - Arrays have consistent dimensionality across chunks
            - Arrays compatible with similarity calculations
            - Proper numerical data type for vector operations
        """

    def test_generate_embeddings_preserves_chunk_order(self):
        """
        GIVEN ordered list of chunks
        WHEN _generate_embeddings is called
        THEN expect:
            - Original chunk order preserved in returned list
            - Batch processing doesn't affect sequence
            - Chunk identity and relationships maintained
        """

    def test_generate_embeddings_handles_empty_chunk_list(self):
        """
        GIVEN empty list of chunks
        WHEN _generate_embeddings is called
        THEN expect:
            - Empty list returned unchanged
            - No errors raised for empty input
            - Method handles edge case gracefully
        """

    def test_generate_embeddings_handles_chunks_with_empty_content(self):
        """
        GIVEN chunks with empty or whitespace-only content
        WHEN _generate_embeddings is called
        THEN expect:
            - Empty content chunks handled appropriately
            - May receive default/zero embeddings or None values
            - No errors raised for empty content
            - Other chunks with content processed normally
        """

    def test_generate_embeddings_logs_batch_failures(self):
        """
        GIVEN embedding failures during batch processing
        WHEN _generate_embeddings is called
        THEN expect:
            - Failures logged with appropriate error information
            - Logging helps with debugging embedding issues
            - Processing continues despite logged errors
        """








class TestLLMOptimizerExtractKeyEntities:
    """Test LLMOptimizer._extract_key_entities method."""

    def test_extract_key_entities_finds_dates(self):
        """
        GIVEN structured_text containing various date formats:
            - MM/DD/YYYY: "12/25/2023"
            - YYYY-MM-DD: "2023-12-25"
            - Month DD, YYYY: "December 25, 2023"
        WHEN _extract_key_entities is called
        THEN expect:
            - Date entities extracted with type "date"
            - Multiple date formats recognized
            - Up to 10 dates included in results
            - Confidence scores reflect extraction method reliability
        """

    def test_extract_key_entities_finds_email_addresses(self):
        """
        GIVEN structured_text containing email addresses:
            - "user@example.com"
            - "admin@company.org"
            - "support@domain.net"
        WHEN _extract_key_entities is called
        THEN expect:
            - Email entities extracted with type "email"
            - RFC-compliant pattern matching used
            - Up to 5 emails included in results
            - Valid email formats recognized accurately
        """

    def test_extract_key_entities_finds_organizations(self):
        """
        GIVEN structured_text containing organization names:
            - "Microsoft Corporation"
            - "Stanford University" 
            - "World Health Organization"
        WHEN _extract_key_entities is called
        THEN expect:
            - Organization entities extracted with type "organization"
            - Capitalized multi-word phrases identified
            - Up to 10 organizations included in results
            - Organization detection based on capitalization patterns
        """

    def test_extract_key_entities_limits_results_per_type(self):
        """
        GIVEN structured_text with excessive entities of each type
        WHEN _extract_key_entities is called
        THEN expect:
            - Dates limited to 10 results maximum
            - Emails limited to 5 results maximum
            - Organizations limited to 10 results maximum
            - Quantity limits prevent overwhelming downstream processing
        """

    def test_extract_key_entities_includes_confidence_scores(self):
        """
        GIVEN structured_text with extractable entities
        WHEN _extract_key_entities is called
        THEN expect:
            - Each entity dictionary includes 'confidence' key
            - Confidence scores reflect extraction method reliability
            - Scores help assess entity extraction quality
            - Values appropriate for filtering decisions
        """

    def test_extract_key_entities_handles_empty_content(self):
        """
        GIVEN structured_text with empty or minimal content
        WHEN _extract_key_entities is called
        THEN expect:
            - Empty list returned
            - No errors raised for insufficient content
            - Graceful handling of edge case
        """

    def test_extract_key_entities_returns_proper_structure(self):
        """
        GIVEN structured_text with extractable entities
        WHEN _extract_key_entities is called
        THEN expect:
            - List of dictionaries returned
            - Each dictionary contains 'text', 'type', 'confidence' keys
            - Structure suitable for knowledge graph construction
            - Consistent format across all entity types
        """

    def test_extract_key_entities_handles_malformed_patterns(self):
        """
        GIVEN structured_text with malformed or partial entity patterns
        WHEN _extract_key_entities is called
        THEN expect:
            - Malformed patterns ignored or handled gracefully
            - Only valid entities included in results
            - Pattern matching robustness maintained
            - No errors for partial matches
        """

    def test_extract_key_entities_processes_page_level_content(self):
        """
        GIVEN structured_text with multiple pages containing full_text
        WHEN _extract_key_entities is called
        THEN expect:
            - All pages processed for entity extraction
            - Entities from all pages aggregated in results
            - Page boundaries don't limit entity recognition
        """









class TestLLMOptimizerGenerateDocumentEmbedding:
    """Test LLMOptimizer._generate_document_embedding method."""

    def test_generate_document_embedding_with_valid_inputs(self):
        """
        GIVEN valid summary string and structured_text with content
        AND embedding_model is available and functional
        WHEN _generate_document_embedding is called
        THEN expect:
            - numpy.ndarray returned representing document semantics
            - Embedding combines summary with key structural elements
            - High-dimensional vector suitable for similarity calculations
            - Document-level representation captures overall themes
        """

    def test_generate_document_embedding_combines_summary_and_headers(self):
        """
        GIVEN summary and structured_text with header elements
        WHEN _generate_document_embedding is called
        THEN expect:
            - Summary text included in embedding generation
            - Headers and titles prioritized for document representation
            - Structural elements enhance document characterization
            - Combined content provides comprehensive document view
        """

    def test_generate_document_embedding_limits_content_scope(self):
        """
        GIVEN structured_text with many pages and elements
        WHEN _generate_document_embedding is called
        THEN expect:
            - Only first 3 pages processed for efficiency
            - Up to 5 elements per page used
            - Content scope balances comprehensiveness with efficiency
            - Processing time optimized for document-level representation
        """

    def test_generate_document_embedding_prioritizes_structural_elements(self):
        """
        GIVEN structured_text with mixed element types
        WHEN _generate_document_embedding is called
        THEN expect:
            - Headers and titles prioritized in content selection
            - Structural elements weighted higher than regular text
            - Document organization reflected in embedding
            - Key sections contribute more to representation
        """

    def test_generate_document_embedding_handles_empty_summary(self):
        """
        GIVEN empty summary string and valid structured_text
        WHEN _generate_document_embedding is called
        THEN expect:
            - Embedding generated from structured_text content only
            - Empty summary handled gracefully
            - Document representation still meaningful
            - No errors for missing summary content
        """

    def test_generate_document_embedding_handles_minimal_content(self):
        """
        GIVEN minimal summary and structured_text with little content
        WHEN _generate_document_embedding is called
        THEN expect:
            - Embedding generated from available content
            - Minimal content handled appropriately
            - Vector representation reflects available information
            - No errors for sparse document content
        """

    def test_generate_document_embedding_handles_embedding_failure(self):
        """
        GIVEN inputs that cause embedding generation to fail
        WHEN _generate_document_embedding is called
        THEN expect:
            - None returned for failed embedding generation
            - Failures handled gracefully without raising exceptions
            - Error logged appropriately for debugging
            - System continues with missing document embedding
        """

    def test_generate_document_embedding_with_no_embedding_model(self):
        """
        GIVEN LLMOptimizer with embedding_model set to None
        WHEN _generate_document_embedding is called
        THEN expect:
            - None returned immediately
            - No processing attempted without model
            - Graceful handling of missing embedding capability
            - No errors for unavailable embedding model
        """

    def test_generate_document_embedding_content_preparation(self):
        """
        GIVEN summary and structured_text for embedding
        WHEN _generate_document_embedding is called
        THEN expect:
            - Content properly prepared and cleaned for embedding
            - Text concatenation handled appropriately
            - Special characters and formatting preserved or normalized
            - Input preparation optimizes embedding quality
        """









class TestLLMOptimizerCountTokens:
    """Test LLMOptimizer._count_tokens method."""

    def test_count_tokens_with_valid_text(self):
        """
        GIVEN non-empty text string and functional tokenizer
        WHEN _count_tokens is called
        THEN expect:
            - Integer token count returned
            - Count reflects configured tokenizer's calculation
            - Accurate token counting for chunk size management
            - Consistent results for identical input text
        """

    def test_count_tokens_with_empty_text(self):
        """
        GIVEN empty string or None as input
        WHEN _count_tokens is called
        THEN expect:
            - 0 returned for empty or None text input
            - No errors raised for empty input
            - Graceful handling of edge case
        """

    def test_count_tokens_with_tiktoken_tokenizer(self):
        """
        GIVEN LLMOptimizer configured with tiktoken tokenizer (OpenAI models)
        AND valid text input
        WHEN _count_tokens is called
        THEN expect:
            - tiktoken encoder used for token counting
            - Accurate count for OpenAI model compatibility
            - Proper handling of tiktoken-specific encoding
        """

    def test_count_tokens_with_huggingface_tokenizer(self):
        """
        GIVEN LLMOptimizer configured with HuggingFace tokenizer
        AND valid text input
        WHEN _count_tokens is called
        THEN expect:
            - HuggingFace tokenizer used for counting
            - Tokenization appropriate for specified model
            - Proper handling of HuggingFace tokenizer interface
        """

    def test_count_tokens_handles_tokenizer_failure(self):
        """
        GIVEN text input that causes tokenizer to fail
        WHEN _count_tokens is called
        THEN expect:
            - Fallback to word-based approximation (words * 1.3)
            - Warning logged about tokenization failure
            - Reasonable approximation returned for robustness
            - No exceptions raised despite tokenizer failure
        """

    def test_count_tokens_with_no_tokenizer(self):
        """
        GIVEN LLMOptimizer with tokenizer set to None
        AND valid text input
        WHEN _count_tokens is called
        THEN expect:
            - Fallback to word-based approximation used
            - Approximation formula: word count * 1.3
            - Reasonable estimate for token counting
            - Graceful degradation when tokenizer unavailable
        """

    def test_count_tokens_approximation_formula(self):
        """
        GIVEN text with known word count when using fallback
        WHEN _count_tokens is called with failed/missing tokenizer
        THEN expect:
            - Token count approximated as word_count * 1.3
            - Formula provides reasonable token estimate
            - Consistent approximation calculation
        """

    def test_count_tokens_logs_errors_appropriately(self):
        """
        GIVEN tokenization that fails with exceptions
        WHEN _count_tokens is called
        THEN expect:
            - Tokenization errors logged with warning level
            - Error information included for debugging
            - Logging helps identify tokenization issues
            - Processing continues with fallback method
        """

    def test_count_tokens_handles_special_characters(self):
        """
        GIVEN text containing special characters, unicode, punctuation
        WHEN _count_tokens is called
        THEN expect:
            - Special characters handled appropriately by tokenizer
            - Unicode text processed correctly
            - Punctuation contributes to token count as expected
            - Robust handling of diverse text content
        """









class TestLLMOptimizerGetChunkOverlap:
    """Test LLMOptimizer._get_chunk_overlap method."""

    def test_get_chunk_overlap_with_sufficient_content(self):
        """
        GIVEN content string longer than overlap requirements
        AND configured chunk_overlap parameter
        WHEN _get_chunk_overlap is called
        THEN expect:
            - Overlap text extracted from end of content
            - Overlap size approximated as chunk_overlap tokens / 4 words
            - Words extracted from end maintain narrative flow
            - Returned text suitable for next chunk's context preservation
        """

    def test_get_chunk_overlap_calculates_word_approximation(self):
        """
        GIVEN chunk_overlap of 200 tokens
        WHEN _get_chunk_overlap is called
        THEN expect:
            - Overlap size approximated as 200 / 4 = 50 words
            - Word-based approximation provides reasonable token estimation
            - Calculation consistent across different overlap values
        """

    def test_get_chunk_overlap_extracts_from_content_end(self):
        """
        GIVEN content: "This is a long piece of content with many words for testing overlap extraction functionality."
        WHEN _get_chunk_overlap is called
        THEN expect:
            - Words extracted from the end of the content
            - Overlap maintains document flow for next chunk
            - End-extraction preserves narrative continuity
        """

    def test_get_chunk_overlap_handles_insufficient_content(self):
        """
        GIVEN content string shorter than required overlap size
        WHEN _get_chunk_overlap is called
        THEN expect:
            - Empty string returned for insufficient content length
            - No errors raised for short content
            - Graceful handling when overlap exceeds content
        """

    def test_get_chunk_overlap_handles_empty_content(self):
        """
        GIVEN empty string as content
        WHEN _get_chunk_overlap is called
        THEN expect:
            - Empty string returned
            - No errors for empty input
            - Graceful edge case handling
        """

    def test_get_chunk_overlap_word_boundary_respect(self):
        """
        GIVEN content with clear word boundaries
        WHEN _get_chunk_overlap is called
        THEN expect:
            - Overlap extracted respects complete words
            - No partial words in overlap text
            - Word splitting handled appropriately
        """

    def test_get_chunk_overlap_with_different_overlap_sizes(self):
        """
        GIVEN different chunk_overlap values: 100, 200, 400
        WHEN _get_chunk_overlap is called for each
        THEN expect:
            - Overlap text size varies proportionally
            - 100 tokens ≈ 25 words overlap
            - 200 tokens ≈ 50 words overlap  
            - 400 tokens ≈ 100 words overlap
        """

    def test_get_chunk_overlap_preserves_text_formatting(self):
        """
        GIVEN content with whitespace and basic formatting
        WHEN _get_chunk_overlap is called
        THEN expect:
            - Basic text formatting preserved in overlap
            - Whitespace handling appropriate for context preservation
            - Overlap text maintains readability
        """

    def test_get_chunk_overlap_single_word_content(self):
        """
        GIVEN content containing only one word
        WHEN _get_chunk_overlap is called
        THEN expect:
            - Single word returned if overlap size permits
            - Empty string if word insufficient for overlap requirement
            - Appropriate handling of minimal content
        """








class TestTextProcessorSplitSentences:
    """Test TextProcessor.split_sentences method."""

    def test_split_sentences_with_periods(self):
        """
        GIVEN text with sentences ending in periods:
            "Hello world. This is a test. How are you today."
        WHEN split_sentences is called
        THEN expect:
            - List of three sentences returned
            - Sentences: ["Hello world", "This is a test", "How are you today"]
            - Periods removed from sentence endings
            - Whitespace trimmed from each sentence
        """

    def test_split_sentences_with_question_marks(self):
        """
        GIVEN text with sentences ending in question marks:
            "How are you? What is your name? Are you ready?"
        WHEN split_sentences is called
        THEN expect:
            - List of three sentences returned
            - Question marks used as sentence delimiters
            - Each sentence properly separated and trimmed
        """

    def test_split_sentences_with_exclamation_points(self):
        """
        GIVEN text with sentences ending in exclamation points:
            "Hello there! Welcome to the system! Let's get started!"
        WHEN split_sentences is called
        THEN expect:
            - List of three sentences returned
            - Exclamation points used as sentence delimiters
            - Proper sentence segmentation and trimming
        """

    def test_split_sentences_with_mixed_punctuation(self):
        """
        GIVEN text with mixed terminal punctuation:
            "Hello world. How are you? Great to see you! Let's continue."
        WHEN split_sentences is called
        THEN expect:
            - All terminal punctuation marks recognized
            - Four sentences properly separated
            - Mixed punctuation handled consistently
        """

    def test_split_sentences_excludes_empty_strings(self):
        """
        GIVEN text with consecutive punctuation or extra whitespace:
            "Hello.. How are you?? Welcome!"
        WHEN split_sentences is called
        THEN expect:
            - Empty strings filtered out of results
            - Only non-empty sentences included
            - Consecutive delimiters handled appropriately
        """

    def test_split_sentences_trims_whitespace(self):
        """
        GIVEN text with extra whitespace around sentences:
            "  Hello world  .   How are you  ?   Welcome  !"
        WHEN split_sentences is called
        THEN expect:
            - Leading and trailing whitespace removed from each sentence
            - Clean sentence text without extra spaces
            - Proper trimming applied consistently
        """

    def test_split_sentences_handles_empty_input(self):
        """
        GIVEN empty string input
        WHEN split_sentences is called
        THEN expect:
            - Empty list returned
            - No errors raised for empty input
            - Graceful handling of edge case
        """

    def test_split_sentences_handles_no_punctuation(self):
        """
        GIVEN text without terminal punctuation:
            "Hello world this is a test"
        WHEN split_sentences is called
        THEN expect:
            - Single sentence returned as is
            - No splitting occurs without delimiters
            - Entire text treated as one sentence
        """

    def test_split_sentences_handles_single_character_sentences(self):
        """
        GIVEN text with very short sentences:
            "A. B? C!"
        WHEN split_sentences is called
        THEN expect:
            - Single characters recognized as valid sentences
            - Three sentences: ["A", "B", "C"]
            - Short content handled appropriately
        """








class TestTextProcessorExtractKeywords:
    """Test TextProcessor.extract_keywords method."""

    def test_extract_keywords_with_default_top_k(self):
        """
        GIVEN text with various word frequencies
        AND no top_k parameter specified (defaults to 20)
        WHEN extract_keywords is called
        THEN expect:
            - Up to 20 keywords returned
            - Keywords ranked by frequency in descending order
            - Stop words filtered out from results
            - Most frequent significant terms included
        """

    def test_extract_keywords_with_custom_top_k(self):
        """
        GIVEN text content and top_k parameter set to 10
        WHEN extract_keywords is called
        THEN expect:
            - Exactly 10 keywords returned (or fewer if insufficient unique words)
            - Top 10 most frequent non-stop words included
            - Result limited to specified count
        """

    def test_extract_keywords_filters_short_words(self):
        """
        GIVEN text containing words of various lengths including words shorter than 3 characters:
            "I am a big dog and it is on my desk"
        WHEN extract_keywords is called
        THEN expect:
            - Words shorter than 3 characters excluded ("I", "am", "a", "is", "on", "my")
            - Only words 3+ characters included in results
            - Filtering improves keyword relevance
        """

    def test_extract_keywords_filters_stop_words(self):
        """
        GIVEN text containing common stop words:
            "the quick brown fox jumps over the lazy dog and the cat"
        WHEN extract_keywords is called
        THEN expect:
            - Stop words excluded ("the", "and", "over")
            - Content words included ("quick", "brown", "fox", "jumps", "lazy", "dog", "cat")
            - Comprehensive stop word filtering applied
        """

    def test_extract_keywords_case_insensitive_processing(self):
        """
        GIVEN text with mixed case words:
            "Python programming PYTHON Programming python"
        WHEN extract_keywords is called
        THEN expect:
            - Case-insensitive frequency counting
            - "python" and "programming" recognized regardless of case
            - Consistent keyword identification across case variations
        """

    def test_extract_keywords_ranks_by_frequency(self):
        """
        GIVEN text where word frequencies are known:
            "apple banana apple cherry apple banana apple"
        WHEN extract_keywords is called
        THEN expect:
            - Keywords returned in frequency order: ["apple", "banana", "cherry"]
            - Most frequent words appear first in results
            - Frequency-based ranking applied consistently
        """

    def test_extract_keywords_handles_empty_text(self):
        """
        GIVEN empty string input
        WHEN extract_keywords is called
        THEN expect:
            - Empty list returned
            - No errors raised for empty input
            - Graceful handling of edge case
        """

    def test_extract_keywords_handles_text_with_only_stop_words(self):
        """
        GIVEN text containing only stop words and short words:
            "the and or but a an it is on in"
        WHEN extract_keywords is called
        THEN expect:
            - Empty list returned after filtering
            - All words filtered out as stop words or too short
            - Proper filtering behavior for low-content text
        """

    def test_extract_keywords_handles_punctuation_and_special_characters(self):
        """
        GIVEN text with punctuation and special characters:
            "Hello, world! This is a test... @user #hashtag"
        WHEN extract_keywords is called
        THEN expect:
            - Punctuation handled appropriately in word extraction
            - Special characters may be filtered or processed
            - Focus on meaningful word content
        """

    def test_extract_keywords_with_insufficient_words_for_top_k(self):
        """
        GIVEN text with fewer unique keywords than top_k value
        AND top_k set to 10 but only 5 valid keywords available
        WHEN extract_keywords is called
        THEN expect:
            - All available keywords returned (5 in this case)
            - No padding or errors for insufficient word count
            - Result size matches available content
        """










class TestChunkOptimizerOptimizeBoundaries:
    """Test ChunkOptimizer.optimize_chunk_boundaries method."""

    def test_optimize_chunk_boundaries_prioritizes_paragraph_breaks(self):
        """
        GIVEN text with paragraph boundaries near chunk boundaries:
            - Text: "First paragraph content.\n\nSecond paragraph content.\n\nThird paragraph."
            - current_boundaries: [50] (near second paragraph break)
        WHEN optimize_chunk_boundaries is called
        THEN expect:
            - Boundary moved to paragraph break position
            - Paragraph boundary within 50 characters preferred
            - Optimized boundary improves semantic coherence
        """

    def test_optimize_chunk_boundaries_falls_back_to_sentence_breaks(self):
        """
        GIVEN text with sentence boundaries but no paragraph breaks near boundary:
            - Text: "First sentence. Second sentence. Third sentence continues."
            - current_boundaries: [30] (near sentence boundary, no paragraph break within 50 chars)
        WHEN optimize_chunk_boundaries is called
        THEN expect:
            - Boundary moved to nearest sentence ending within 25 characters
            - Sentence boundary used as fallback when no paragraph break available
            - Sentence endings include periods, exclamation points, question marks
        """

    def test_optimize_chunk_boundaries_maintains_original_when_no_natural_break(self):
        """
        GIVEN text without natural breaks near boundary:
            - Text: "This is a very long sentence without any natural breaking points nearby"
            - current_boundaries: [40] (no sentence or paragraph breaks within range)
        WHEN optimize_chunk_boundaries is called
        THEN expect:
            - Original boundary position maintained
            - No optimization when suitable natural division unavailable
            - Boundary unchanged when no better option found
        """

    def test_optimize_chunk_boundaries_handles_multiple_boundaries(self):
        """
        GIVEN text with multiple chunk boundaries:
            - current_boundaries: [100, 200, 300]
        WHEN optimize_chunk_boundaries is called
        THEN expect:
            - Each boundary optimized independently
            - All boundaries processed for natural break alignment
            - Optimized boundaries returned in same order
            - List length preserved
        """

    def test_optimize_chunk_boundaries_respects_search_ranges(self):
        """
        GIVEN text with natural breaks at various distances from boundary
        WHEN optimize_chunk_boundaries is called
        THEN expect:
            - Paragraph breaks considered within 50 characters of boundary
            - Sentence breaks considered within 25 characters of boundary
            - Breaks outside search range ignored
            - Search ranges prevent excessive boundary movement
        """

    def test_optimize_chunk_boundaries_handles_boundary_at_text_start(self):
        """
        GIVEN current_boundaries including position 0 or near text start
        WHEN optimize_chunk_boundaries is called
        THEN expect:
            - Start-of-text boundary handled appropriately
            - No attempt to move boundary before text beginning
            - Edge case handled gracefully
        """

    def test_optimize_chunk_boundaries_handles_boundary_at_text_end(self):
        """
        GIVEN current_boundaries including position near or at text end
        WHEN optimize_chunk_boundaries is called
        THEN expect:
            - End-of-text boundary handled appropriately
            - No attempt to move boundary beyond text length
            - Text length constraints respected
        """

    def test_optimize_chunk_boundaries_recognizes_all_sentence_endings(self):
        """
        GIVEN text with various sentence ending punctuation:
            - Periods: "First sentence."
            - Question marks: "Second sentence?"
            - Exclamation points: "Third sentence!"
        WHEN optimize_chunk_boundaries is called
        THEN expect:
            - All terminal punctuation recognized as sentence boundaries
            - Period, question mark, and exclamation point all considered
            - Comprehensive sentence boundary detection
        """

    def test_optimize_chunk_boundaries_handles_empty_boundary_list(self):
        """
        GIVEN empty current_boundaries list
        WHEN optimize_chunk_boundaries is called
        THEN expect:
            - Empty list returned unchanged
            - No errors raised for empty input
            - Graceful handling of edge case
        """

    def test_optimize_chunk_boundaries_preserves_boundary_order(self):
        """
        GIVEN current_boundaries in ascending order: [50, 150, 250]
        WHEN optimize_chunk_boundaries is called
        THEN expect:
            - Optimized boundaries maintain ascending order
            - Relative boundary positions preserved
            - Optimization doesn't disrupt boundary sequence
        """



if __name__ == "__main__":
    pytest.main([__file__, "-v"])