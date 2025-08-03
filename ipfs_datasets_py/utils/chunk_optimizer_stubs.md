# Function and Class stubs from '/home/kylerose1946/ipfs_datasets_py/ipfs_datasets_py/utils/chunk_optimizer.py'

Files last updated: 1753049696.2461429

Stub file last updated: 2025-07-20 15:22:21

## ChunkMetrics

```python
@dataclass
class ChunkMetrics:
    """
    Comprehensive quality metrics for evaluating text chunk characteristics.

The ChunkMetrics dataclass encapsulates multiple dimensions of chunk quality assessment,
providing a standardized structure for storing and comparing chunk evaluation results.
Each metric represents a different aspect of chunk quality, with scores normalized to
a 0.0-1.0 range for easy comparison and aggregation.

This dataclass is used by the ChunkOptimizer to quantify the suitability of text chunks
for LLM processing, enabling data-driven decisions about chunk selection, ordering, and
optimization. The metrics balance various quality aspects to ensure chunks are both
rich in information and structurally sound.

Attributes:
    coherence_score (float): Measure of logical flow and sentence connectivity within
        the chunk. Based on transition word usage and referential elements like pronouns.
        Range: 0.0-1.0, where 1.0 indicates excellent flow with clear connections.
    
    completeness_score (float): Measure of structural completeness, evaluating whether
        sentences and thoughts are properly concluded. Based on punctuation patterns
        and sentence boundaries. Range: 0.0-1.0, where 1.0 indicates all sentences
        are properly formed and ended.
    
    length_score (float): Measure of size appropriateness relative to configured
        boundaries (min_size, max_size). Optimal at the midpoint between boundaries.
        Range: 0.0-1.0, where 1.0 indicates ideal length for processing.
    
    semantic_density (float): Measure of information richness, calculating the ratio
        of meaningful content words to total words and vocabulary diversity.
        Range: 0.0-1.0, where 1.0 indicates high information content with minimal filler.
    
    overall_quality (float): Weighted aggregate of all metrics providing a single
        quality indicator. Calculated as: coherence*0.3 + completeness*0.25 + 
        length*0.25 + density*0.2. Range: 0.0-1.0, where 1.0 indicates excellent
        overall quality.

Usage Example:
    >>> metrics = ChunkMetrics(
    ...     coherence_score=0.85,
    ...     completeness_score=0.92,
    ...     length_score=0.78,
    ...     semantic_density=0.81,
    ...     overall_quality=0.84
    ... )
    >>> print(f"Overall quality: {metrics.overall_quality:.2%}")
    84.00%
    >>> 
    >>> # Compare chunks
    >>> if chunk1.metrics.overall_quality > chunk2.metrics.overall_quality:
    ...     print("Chunk 1 is higher quality")

Notes:
    - All scores are normalized to 0.0-1.0 for consistency
    - Overall quality weights are fixed and not configurable
    - Higher scores always indicate better quality
    - Scores are calculated independently but may correlate
    - No validation is performed on score ranges in the dataclass

Areas for Improvement:
    - Add validation to ensure scores are within 0.0-1.0 range
    - Include confidence intervals or standard deviations for scores
    - Add timestamp for when metrics were calculated
    - Include raw component scores before weighting
    - Add comparison methods (__lt__, __gt__, etc.) for sorting
    - Include metric calculation parameters for reproducibility
    - Add optional metadata fields for debugging
    - Consider making overall_quality a computed property
    - Add method to recalculate overall_quality with custom weights
    - Include explanations for why certain scores are low
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## ChunkOptimizer

```python
class ChunkOptimizer:
    """
    Advanced Chunk Optimization for LLM Consumption

The ChunkOptimizer class provides sophisticated text chunking strategies optimized for
Large Language Model (LLM) processing. It creates, evaluates, and optimizes text chunks
to maximize coherence, completeness, and semantic density while respecting size constraints.
This class implements multiple chunking algorithms including structure-aware and sliding
window approaches, with comprehensive quality scoring for each chunk.

The optimizer is designed to handle various document types and structures, preserving
narrative flow and semantic boundaries while ensuring chunks remain within LLM context
windows. It evaluates chunks across multiple dimensions including coherence, completeness,
length appropriateness, and semantic density to produce high-quality segments for processing.

Args:
    max_size (int, optional): Maximum size of each chunk in tokens/words. This defines
        the upper boundary for chunk size to fit within LLM context windows.
        Defaults to 2048.
    overlap (int, optional): Number of tokens/words to overlap between consecutive chunks.
        Overlap helps maintain context continuity across chunk boundaries.
        Defaults to 200.
    min_size (int, optional): Minimum acceptable size for a chunk in tokens/words.
        Chunks smaller than this are candidates for merging. Defaults to 100.

Key Features:
- Structure-aware chunking that respects document organization (paragraphs, sections)
- Sliding window chunking for uniform text segmentation
- Intelligent boundary optimization to avoid breaking semantic units
- Multi-dimensional quality scoring (coherence, completeness, length, density)
- Chunk merging capabilities for undersized segments
- Overlap management for context preservation across chunks

Attributes:
    max_size (int): Maximum chunk size in tokens/words
    overlap (int): Overlap size between consecutive chunks
    min_size (int): Minimum acceptable chunk size

Public Methods:
    optimize_chunks(text: str, preserve_structure: bool = True) -> List[Dict[str, Any]]:
        Create optimized chunks from input text with quality scoring and boundary optimization.
    merge_small_chunks(chunks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        Merge chunks that fall below the minimum size threshold to improve processing efficiency.

Private Methods:
    _create_structure_aware_chunks(text: str) -> List[Dict[str, Any]]:
        Create chunks that preserve document structure by respecting paragraph boundaries.
    _create_sliding_window_chunks(text: str) -> List[Dict[str, Any]]:
        Create uniformly-sized chunks using a sliding window approach.
    _create_chunk_dict(content: str, token_count: int, paragraphs: List[str], chunk_type: str) -> Dict[str, Any]:
        Create standardized chunk dictionary with metadata and statistics.
    _optimize_boundaries(chunks: List[Dict[str, Any]], full_text: str) -> List[Dict[str, Any]]:
        Optimize chunk boundaries to improve coherence and completeness.
    _optimize_end_boundary(content: str) -> str:
        Optimize the ending boundary of a chunk to avoid incomplete sentences.
    _get_overlap_content(content: str) -> str:
        Extract appropriate overlap content from the end of a chunk.
    _split_sentences(text: str) -> List[str]:
        Split text into individual sentences using regex patterns.
    _calculate_chunk_metrics(chunk: Dict[str, Any]) -> ChunkMetrics:
        Calculate comprehensive quality metrics for a chunk.
    _calculate_coherence(content: str) -> float:
        Calculate coherence score based on transition words and pronoun usage.
    _calculate_completeness(content: str) -> float:
        Calculate completeness score based on sentence structure and endings.
    _calculate_length_score(word_count: int) -> float:
        Calculate length appropriateness score based on optimal size range.
    _calculate_semantic_density(content: str) -> float:
        Calculate semantic density based on meaningful word ratio and vocabulary richness.

Usage Example:
    optimizer = ChunkOptimizer(
        max_size=2048,
        overlap=200,
        min_size=100
    )
    
    # Create optimized chunks from document
    chunks = optimizer.optimize_chunks(document_text, preserve_structure=True)
    
    # Merge small chunks if needed
    final_chunks = optimizer.merge_small_chunks(chunks)
    
    # Access chunk information
    for chunk in final_chunks:
        print(f"Quality Score: {chunk['quality_score']}")
        print(f"Token Count: {chunk['token_count']}")
        print(f"Content: {chunk['content'][:100]}...")

Notes:
    - The optimizer uses word count as a proxy for token count, which may not be accurate
      for all tokenization schemes
    - Quality scores are normalized to 0.0-1.0 range for easy comparison
    - Structure-aware chunking is recommended for documents with clear formatting
    - Sliding window approach works better for continuous prose without clear breaks
    - Overlap content is conservatively calculated as 1/4 of the specified overlap parameter

Areas for Improvement:
    - Token counting currently uses word splitting which may not match actual LLM tokenization
    - Sentence splitting regex could be enhanced to handle edge cases (abbreviations, decimals)
    - Coherence calculation could benefit from more sophisticated NLP techniques
    - No support for handling special document structures (tables, lists, code blocks)
    - Missing validation for input parameters (negative values, overlap > max_size)
    - No async support for processing large documents
    - Could benefit from configurable stop words for different domains
    - No support for custom quality metric weights
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## __init__

```python
def __init__(self, max_size: int = 2048, overlap: int = 200, min_size: int = 100):
    """
    Initialize the ChunkOptimizer with configurable chunking parameters.

This constructor sets up the fundamental parameters that control how text is divided
into chunks for LLM processing. The parameters balance between maintaining semantic
coherence (through overlap) and respecting LLM context window limitations (through
size constraints).

Args:
    max_size (int, optional): Maximum size of each chunk in words. This parameter
        defines the upper limit for chunk size to ensure compatibility with LLM
        context windows. Should be set based on the target LLM's token limits,
        accounting for the difference between word and token counts.
        Defaults to 2048.
    overlap (int, optional): Number of words to overlap between consecutive chunks.
        This overlap helps maintain context continuity when processing chunks
        sequentially. The actual overlap used may be less (1/4 of this value)
        to prevent excessive redundancy. Defaults to 200.
    min_size (int, optional): Minimum acceptable size for a chunk in words.
        Chunks smaller than this threshold are candidates for merging with
        adjacent chunks to improve processing efficiency. Defaults to 100.

Attributes Initialized:
    max_size (int): Maximum chunk size in words, used as the upper boundary
        for all chunking operations.
    overlap (int): Configured overlap size, though actual overlap may be
        adjusted during processing.
    min_size (int): Minimum chunk size threshold for merging operations.

Raises:
    None currently, but should validate parameters.

Examples:
    >>> # Standard configuration for GPT-style models
    >>> optimizer = ChunkOptimizer(max_size=2048, overlap=200, min_size=100)
    
    >>> # Configuration for smaller context windows
    >>> small_optimizer = ChunkOptimizer(max_size=512, overlap=50, min_size=50)
    
    >>> # Configuration for large context models
    >>> large_optimizer = ChunkOptimizer(max_size=8192, overlap=500, min_size=200)

Notes:
    - Word count is used as a proxy for token count; actual tokens may vary
    - No parameter validation is currently performed
    - Consider model-specific tokenization when setting max_size

Areas for Improvement:
    - Add parameter validation (e.g., max_size > min_size, overlap < max_size)
    - Add type validation to ensure all parameters are positive integers
    - Consider adding logger initialization for debugging
    - Could accept a tokenizer parameter for accurate token counting
    - Should validate that overlap is reasonable relative to max_size
    """
```
* **Async:** False
* **Method:** True
* **Class:** ChunkOptimizer

## _calculate_chunk_metrics

```python
def _calculate_chunk_metrics(self, chunk: Dict[str, Any]) -> ChunkMetrics:
    """
    Calculate comprehensive quality metrics for a text chunk across multiple dimensions.

This method evaluates a chunk's quality by computing scores for coherence, completeness,
length appropriateness, and semantic density. These individual metrics are combined
using weighted averaging to produce an overall quality score. The metrics help identify
high-quality chunks suitable for LLM processing and those that may need improvement.

Args:
    chunk (Dict[str, Any]): A chunk dictionary containing at minimum:
        - 'content' (str): The text content to evaluate
        - 'word_count' (int): Pre-calculated word count for efficiency
        Other fields may be present but are not used in metric calculation.

Returns:
    ChunkMetrics: A dataclass containing:
        - coherence_score (float): Measure of text flow and connectivity (0.0-1.0)
        - completeness_score (float): Measure of sentence/thought completion (0.0-1.0)
        - length_score (float): Measure of size appropriateness (0.0-1.0)
        - semantic_density (float): Measure of meaningful content ratio (0.0-1.0)
        - overall_quality (float): Weighted combination of all metrics (0.0-1.0)

Metric Weights:
    - Coherence: 30% - How well sentences flow and connect
    - Completeness: 25% - Whether thoughts are fully expressed
    - Length: 25% - Appropriateness of chunk size
    - Semantic Density: 20% - Ratio of meaningful to filler words

Examples:
    >>> chunk = {
    ...     'content': 'This is a well-formed chunk. It has good flow.',
    ...     'word_count': 10
    ... }
    >>> metrics = optimizer._calculate_chunk_metrics(chunk)
    >>> print(f"Overall quality: {metrics.overall_quality:.2f}")
    >>> print(f"Coherence: {metrics.coherence_score:.2f}")

Notes:
    - All scores are normalized to 0.0-1.0 range
    - Higher scores indicate better quality
    - Weights are fixed and not configurable
    - Some metrics may be less reliable for very short chunks

Areas for Improvement:
    - Make metric weights configurable for different use cases
    - Add caching for expensive calculations on identical content
    - Include readability metrics (Flesch-Kincaid, etc.)
    - Add domain-specific quality indicators
    - Consider chunk position in document (intro/body/conclusion)
    - Implement language-specific metric adjustments
    - Add confidence intervals for metric scores
    - Include topic coherence using embeddings
    - Support custom metric plugins
    """
```
* **Async:** False
* **Method:** True
* **Class:** ChunkOptimizer

## _calculate_coherence

```python
def _calculate_coherence(self, content: str) -> float:
    """
    Calculate coherence score based on linguistic markers of text flow and connectivity.

This method evaluates how well sentences within a chunk connect and flow together
by analyzing transition words and pronoun usage. Coherent text typically contains
explicit connectives (transition words) and referential elements (pronouns) that
link sentences and maintain topical continuity.

Args:
    content (str): The text content to analyze for coherence. Should contain
        multiple sentences for meaningful coherence measurement. Single sentences
        receive a default score of 0.8.

Returns:
    float: Coherence score between 0.0 and 1.0, where:
        - 1.0 indicates excellent coherence with strong connectives
        - 0.8 is the default for single sentences (assumed coherent)
        - 0.5 indicates moderate coherence
        - 0.0 indicates poor coherence with no connecting elements

Scoring Components:
    1. Transition Words (60% weight):
    - Counts transitional phrases in sentences after the first
    - Includes: however, therefore, furthermore, moreover, etc.
    - Score = min(1.0, transition_count / (sentence_count - 1))
    
    2. Pronoun References (40% weight):
    - Counts pronouns that indicate referential continuity
    - Includes: he, she, it, they, this, that, these, those
    - Expected ratio: 1 pronoun per 20 words
    - Score = min(1.0, pronoun_count / expected_pronouns)

Examples:
    >>> # High coherence with transitions and pronouns
    >>> text = "John founded the company. However, he faced challenges. Therefore, they pivoted."
    >>> score = optimizer._calculate_coherence(text)
    >>> print(f"Coherence: {score:.2f}")  # High score due to "However" and "Therefore"
    
    >>> # Low coherence with disconnected sentences
    >>> text = "Sales increased. Weather was good. Stocks fell."
    >>> score = optimizer._calculate_coherence(text)
    >>> print(f"Coherence: {score:.2f}")  # Low score due to no transitions

Notes:
    - Single sentences receive 0.8 by default (cannot measure flow)
    - Case-insensitive matching for transition words
    - Simple word-boundary checking may miss some transitions
    - Pronoun counting is basic and may include false positives

Areas for Improvement:
    - Expand transition word list with more sophisticated phrases
    - Add weighted scoring based on transition word strength
    - Implement co-reference resolution for better pronoun tracking
    - Consider sentence embedding similarity for semantic coherence
    - Add support for domain-specific transition words
    - Handle nested sentences and complex punctuation
    - Detect topical shifts that break coherence
    - Include lexical chain analysis for topic continuity
    - Add cultural/language-specific coherence patterns
    """
```
* **Async:** False
* **Method:** True
* **Class:** ChunkOptimizer

## _calculate_completeness

```python
def _calculate_completeness(self, content: str) -> float:
    """
    Calculate completeness score based on sentence structure and proper text boundaries.

This method evaluates whether a chunk represents a complete unit of text by examining
sentence endings, structure, and overall composition. Complete chunks are more suitable
for independent processing as they contain fully-formed thoughts and proper conclusions.

Args:
    content (str): The text content to evaluate for completeness. Can be any length
        but requires non-empty content for meaningful scoring. Empty content returns 0.0.

Returns:
    float: Completeness score between 0.0 and 1.0, where:
        - 1.0 indicates perfect completeness with all sentences properly ended
        - 0.7-0.9 indicates good completeness with minor issues
        - 0.5 indicates moderate completeness
        - 0.0 indicates empty or severely incomplete content

Scoring Components:
    1. Proper Ending (40% weight):
    - Checks if last sentence ends with terminal punctuation (. ! ? : ;)
    - Full score (1.0) if properly ended, reduced score (0.7) otherwise
    
    2. Sentence Completeness (40% weight):
    - Ratio of properly ended sentences to total sentences
    - Helps identify chunks with multiple incomplete sentences
    
    3. Multiple Sentences (20% weight):
    - Rewards chunks with multiple sentences (better context)
    - Single sentences receive 0.8, multiple sentences receive 1.0

Examples:
    >>> # Perfect completeness
    >>> content = "This is complete. Every sentence ends properly. Perfect score here!"
    >>> score = optimizer._calculate_completeness(content)
    >>> print(f"Completeness: {score:.2f}")  # 1.0
    
    >>> # Incomplete ending
    >>> content = "This sentence is complete. But this one is not"
    >>> score = optimizer._calculate_completeness(content)
    >>> print(f"Completeness: {score:.2f}")  # ~0.74 (0.7*0.4 + 0.5*0.4 + 1.0*0.2)
    
    >>> # Single complete sentence
    >>> content = "Just one complete sentence."
    >>> score = optimizer._calculate_completeness(content)
    >>> print(f"Completeness: {score:.2f}")  # 0.96 (1.0*0.4 + 1.0*0.4 + 0.8*0.2)

Notes:
    - Empty content returns 0.0 immediately
    - Colons and semicolons are considered valid endings
    - Does not evaluate semantic completeness, only structural
    - May not handle all edge cases (e.g., quoted text, URLs)

Areas for Improvement:
    - Add semantic completeness checking beyond punctuation
    - Handle special cases like bullet points or numbered lists
    - Consider paragraph-level completeness for structured documents
    - Add detection for truncated words or obvious cut-offs
    - Support for code blocks or technical content with different rules
    - Implement language-specific completeness rules
    - Add handling for ellipses as intentional incomplete endings
    - Consider context from surrounding chunks for better evaluation
    - Weight sentences by importance rather than treating equally
    """
```
* **Async:** False
* **Method:** True
* **Class:** ChunkOptimizer

## _calculate_length_score

```python
def _calculate_length_score(self, word_count: int) -> float:
    """
    Calculate length appropriateness score based on configured size boundaries.

This method evaluates whether a chunk's length falls within the optimal range defined
by min_size and max_size parameters. Chunks within the acceptable range receive higher
scores, with the ideal length being the midpoint between minimum and maximum. Scores
decrease proportionally for chunks outside the range.

Args:
    word_count (int): The number of words in the chunk. Must be non-negative.
        Used to determine position relative to configured size boundaries.

Returns:
    float: Length score between 0.0 and 1.0, where:
        - 1.0 indicates optimal length (at the midpoint of min_size and max_size)
        - Decreases linearly as length moves away from ideal
        - Proportionally reduced for undersized chunks (< min_size)
        - Proportionally reduced for oversized chunks (> max_size)

Scoring Algorithm:
    - If word_count < min_size: score = word_count / min_size
    - If word_count > max_size: score = max_size / word_count
    - If min_size <= word_count <= max_size:
    - Calculate distance from ideal length (midpoint)
    - Score = 1.0 - (distance / max_possible_distance)

Examples:
    >>> optimizer = ChunkOptimizer(max_size=1000, min_size=100)
    >>> # Ideal length = (100 + 1000) / 2 = 550 words
    
    >>> score = optimizer._calculate_length_score(550)
    >>> print(f"Score at ideal: {score:.2f}")  # 1.0
    
    >>> score = optimizer._calculate_length_score(50)
    >>> print(f"Score when too small: {score:.2f}")  # 0.5 (50/100)
    
    >>> score = optimizer._calculate_length_score(2000)
    >>> print(f"Score when too large: {score:.2f}")  # 0.5 (1000/2000)
    
    >>> score = optimizer._calculate_length_score(700)
    >>> print(f"Score near ideal: {score:.2f}")  # ~0.73

Notes:
    - Assumes min_size < max_size (not validated)
    - Linear scoring may not reflect actual quality impact
    - No special handling for edge cases (zero length, negative values)
    - Ideal length is always the arithmetic mean of boundaries

Areas for Improvement:
    - Add validation for word_count >= 0
    - Make ideal length calculation configurable (not always midpoint)
    - Implement non-linear scoring curves (e.g., sigmoid, gaussian)
    - Add different penalties for oversized vs undersized chunks
    - Consider content type in scoring (code vs prose)
    - Add hysteresis to prevent boundary oscillation
    - Support multiple optimal length ranges
    - Include variance penalty for inconsistent chunk sizes
    - Make scoring more forgiving near boundaries
    """
```
* **Async:** False
* **Method:** True
* **Class:** ChunkOptimizer

## _calculate_semantic_density

```python
def _calculate_semantic_density(self, content: str) -> float:
    """
    Calculate semantic density based on the ratio of meaningful content words to total words.

This method evaluates the information richness of text by measuring the proportion of
meaningful words (excluding stop words and very short words) and vocabulary diversity.
Higher semantic density indicates more informative content with less filler, making
it more valuable for LLM processing and knowledge extraction.

Args:
    content (str): The text content to analyze. Will be converted to lowercase
        and split on whitespace for word-level analysis. Empty content returns 0.0.

Returns:
    float: Semantic density score between 0.0 and 1.0, where:
        - 1.0 indicates maximum density (all meaningful words, high uniqueness)
        - 0.7-0.9 typical for informative content
        - 0.5 indicates moderate density with some filler
        - 0.0 indicates empty content or all stop words

Scoring Components:
    1. Meaningful Word Ratio (70% weight):
    - Excludes common stop words (the, a, an, and, or, etc.)
    - Excludes words with length <= 2 characters
    - Score = meaningful_words / total_words
    
    2. Vocabulary Richness (30% weight):
    - Measures unique meaningful words vs total meaningful words
    - Penalizes repetitive content
    - Score = unique_meaningful / total_meaningful

Stop Words List:
    Common English function words including:
    - Articles: the, a, an
    - Conjunctions: and, or, but
    - Prepositions: in, on, at, to, for, of, with, by
    - Auxiliary verbs: is, are, was, were, be, been, being, have, has, had, do, does, did

Examples:
    >>> # High density with meaningful content
    >>> content = "Quantum computing revolutionizes cryptography algorithms"
    >>> score = optimizer._calculate_semantic_density(content)
    >>> print(f"Density: {score:.2f}")  # High score, all meaningful words
    
    >>> # Low density with many stop words
    >>> content = "The cat is on the mat and it is by the door"
    >>> score = optimizer._calculate_semantic_density(content)
    >>> print(f"Density: {score:.2f}")  # Lower score due to stop words
    
    >>> # Repetitive content
    >>> content = "Important important important very very important"
    >>> score = optimizer._calculate_semantic_density(content)
    >>> print(f"Density: {score:.2f}")  # Reduced by uniqueness penalty

Notes:
    - Case-insensitive stop word matching
    - Simple length-based filtering may exclude valid short words
    - Stop word list is English-specific and hardcoded
    - Does not consider word importance or domain relevance

Areas for Improvement:
    - Add configurable stop word lists for different domains
    - Support multiple languages with appropriate stop words
    - Consider TF-IDF or similar weighting for word importance
    - Add domain-specific meaningful word detection
    - Handle contractions and hyphenated words properly
    - Consider n-grams for phrase-level density
    - Add support for technical terms and acronyms
    - Implement adaptive stop word detection based on corpus
    - Include part-of-speech tagging for better classification
    - Add semantic similarity clustering for true uniqueness
    """
```
* **Async:** False
* **Method:** True
* **Class:** ChunkOptimizer

## _create_chunk_dict

```python
def _create_chunk_dict(self, content: str, token_count: int, paragraphs: List[str], chunk_type: str) -> Dict[str, Any]:
    """
    Create a standardized dictionary structure for chunk metadata and statistics.

This method constructs a consistent data structure for all chunks regardless of their
creation method. It calculates various statistics about the chunk content and packages
all information into a standardized format that can be used throughout the chunking
pipeline for analysis, scoring, and optimization.

Args:
    content (str): The full text content of the chunk. This should be the final,
        processed text that will be used for downstream tasks.
    token_count (int): The pre-calculated token/word count for the chunk. This is
        typically calculated by the calling method to avoid redundant counting.
    paragraphs (List[str]): List of individual paragraphs that comprise this chunk.
        For sliding window chunks, this is typically a single-element list.
        For structure-aware chunks, contains the actual paragraph texts.
    chunk_type (str): Identifier for the chunking method used. Expected values are
        'structure_aware', 'sliding_window', or 'merged' to indicate the chunk's origin.

Returns:
    Dict[str, Any]: A standardized chunk dictionary containing:
        - 'content' (str): The provided text content
        - 'token_count' (int): The provided token count
        - 'paragraph_count' (int): Number of paragraphs (len(paragraphs))
        - 'sentence_count' (int): Number of sentences detected in content
        - 'chunk_type' (str): The chunking method identifier
        - 'word_count' (int): Fresh count of whitespace-separated words
        - 'char_count' (int): Total character count including spaces
        - 'paragraphs' (List[str]): The provided paragraph list

Examples:
    >>> content = "This is a sample chunk. It has two sentences."
    >>> paragraphs = [content]
    >>> chunk_dict = optimizer._create_chunk_dict(
    ...     content=content,
    ...     token_count=9,
    ...     paragraphs=paragraphs,
    ...     chunk_type='sliding_window'
    ... )
    >>> print(chunk_dict['sentence_count'])  # 2
    >>> print(chunk_dict['word_count'])      # 9

Notes:
    - Sentence counting relies on the _split_sentences method
    - Word count is recalculated from content, not taken from token_count
    - No validation is performed on input parameters
    - The structure is designed for extensibility with additional metrics

Areas for Improvement:
    - Add validation for empty content or paragraphs
    - Include timestamp or version information for tracking
    - Add checksum or hash for content integrity verification
    - Consider adding language detection metadata
    - Include average word/sentence length statistics
    - Add support for custom metadata fields
    - Validate that paragraphs content matches content parameter
    - Consider memory optimization for large paragraph lists
    """
```
* **Async:** False
* **Method:** True
* **Class:** ChunkOptimizer

## _create_sliding_window_chunks

```python
def _create_sliding_window_chunks(self, text: str) -> List[Dict[str, Any]]:
    """
    Create uniformly-sized chunks using a sliding window approach with configurable overlap.

This method implements a sliding window chunking algorithm that divides text into
regular-sized segments without regard for document structure. It moves through the
text with a fixed step size (determined by max_size and overlap), creating chunks
of consistent size. This approach is useful for texts without clear structure or
when uniform processing is required.

Args:
    text (str): The input text to be chunked. Will be split into words using
        whitespace as delimiter. Can be any length of continuous text without
        specific structure requirements.

Returns:
    List[Dict[str, Any]]: A list of chunk dictionaries, each containing:
        - 'content' (str): The text content (words joined by spaces)
        - 'token_count' (int): Number of words in the chunk
        - 'paragraph_count' (int): Always 1 (treats chunk as single paragraph)
        - 'sentence_count' (int): Number of sentences detected in chunk
        - 'chunk_type' (str): Always 'sliding_window' for this method
        - 'word_count' (int): Same as token_count
        - 'char_count' (int): Total character count
        - 'paragraphs' (List[str]): Single-element list with chunk content
        - 'start_index' (int): Word index where this chunk begins
        - 'end_index' (int): Word index where this chunk ends (exclusive)

Algorithm Details:
    - Step size = max(1, max_size - overlap) to ensure forward progress
    - Each chunk contains max_size words (except possibly the last)
    - Chunks overlap by 'overlap' words with the previous chunk
    - Small final chunks below min_size are included but may be merged later

Examples:
    >>> text = "Word " * 1000  # 1000 words
    >>> optimizer = ChunkOptimizer(max_size=100, overlap=20, min_size=50)
    >>> chunks = optimizer._create_sliding_window_chunks(text)
    >>> print(f"Number of chunks: {len(chunks)}")
    >>> print(f"Step size: {100 - 20} = 80 words")
    >>> print(f"Overlap verification: {chunks[1]['start_index'] - chunks[0]['start_index']}")

Notes:
    - Words are defined as whitespace-separated tokens
    - Preserves original word spacing when reconstructing content
    - Does not break words or apply any text normalization
    - Final chunk may be smaller than max_size if insufficient words remain
    - Overlap is exact except for the final chunk

Areas for Improvement:
    - Add option to handle overlap as percentage of max_size
    - Implement sentence-aware boundaries to avoid mid-sentence splits
    - Add support for character-based windowing instead of word-based
    - Consider overlapping with previous chunk's end sentences
    - Add validation for edge cases (overlap >= max_size)
    - Implement dynamic step size based on content density
    - Add option to exclude chunks below min_size
    - Support for custom tokenization beyond whitespace splitting
    """
```
* **Async:** False
* **Method:** True
* **Class:** ChunkOptimizer

## _create_structure_aware_chunks

```python
def _create_structure_aware_chunks(self, text: str) -> List[Dict[str, Any]]:
    """
    Create chunks that preserve and respect document structure through paragraph boundaries.

This method implements a structure-aware chunking algorithm that maintains document
organization by treating paragraphs as atomic units. It accumulates paragraphs into
chunks until adding another would exceed the maximum size limit, then creates a new
chunk with appropriate overlap. This approach preserves semantic coherence by avoiding
splits within paragraphs and maintaining narrative flow.

Args:
    text (str): The input text to be chunked. Expected to contain paragraph breaks
        indicated by double newlines (\n\n). The text can be of any length and
        may contain multiple paragraphs or be a single continuous block.

Returns:
    List[Dict[str, Any]]: A list of chunk dictionaries, each containing:
        - 'content' (str): The concatenated text content of included paragraphs
        - 'token_count' (int): Total word count of the chunk
        - 'paragraph_count' (int): Number of complete paragraphs in the chunk
        - 'sentence_count' (int): Total sentences across all paragraphs
        - 'chunk_type' (str): Always 'structure_aware' for this method
        - 'word_count' (int): Same as token_count (word-based counting)
        - 'char_count' (int): Total character count
        - 'paragraphs' (List[str]): List of individual paragraph texts

Internal Logic:
    1. Splits text into paragraphs using double newline delimiter
    2. Iterates through paragraphs, accumulating them into chunks
    3. When size limit approached, creates chunk and starts new one
    4. Applies overlap by carrying forward content from previous chunk
    5. Ensures final partial chunk is included if non-empty

Examples:
    >>> text = """First paragraph with some content.
    ... 
    ... Second paragraph that continues the narrative.
    ... 
    ... Third paragraph with conclusion."""
    >>> chunks = optimizer._create_structure_aware_chunks(text)
    >>> print(f"Paragraphs per chunk: {[c['paragraph_count'] for c in chunks]}")
    [2, 1]

Notes:
    - Empty paragraphs (only whitespace) are skipped
    - Overlap is created from the end of previous chunk, not full paragraphs
    - Paragraphs are joined with double newlines in the final content
    - Single very large paragraphs may exceed max_size limits
    - No splitting occurs within paragraphs, maintaining their integrity

Areas for Improvement:
    - Handle single paragraphs that exceed max_size by splitting at sentence boundaries
    - Add configuration for paragraph detection (single vs double newlines)
    - Implement smart overlap that prefers complete sentences
    - Add support for preserving markdown headers or section markers
    - Consider weighted paragraph sizing based on content importance
    - Add detection for different paragraph styles (indented, numbered, etc.)
    - Optimize memory usage by using generators for very large texts
    - Add validation for malformed paragraph structures
    """
```
* **Async:** False
* **Method:** True
* **Class:** ChunkOptimizer

## _get_overlap_content

```python
def _get_overlap_content(self, content: str) -> str:
    """
    Extract appropriate overlap content from the end of a chunk for continuity.

This method creates overlap content that will be prepended to the next chunk to maintain
context across chunk boundaries. It uses a conservative approach, taking only 1/4 of the
configured overlap parameter to prevent excessive redundancy. The method attempts to
select complete sentences for the overlap when possible.

Args:
    content (str): The chunk content from which to extract overlap. Typically the
        complete content of a chunk that has just been created.

Returns:
    str: The overlap text to be prepended to the next chunk. Returns:
        - Complete sentences from the end if possible
        - Word-based overlap if sentence extraction fails
        - Empty string if content is too short for meaningful overlap

Overlap Strategy:
    1. Calculate overlap size as min(overlap/4, total_words)
    2. Extract that many words from the end of content
    3. Attempt to extract complete sentences from those words
    4. Fall back to word-based overlap if sentence extraction fails

Examples:
    >>> optimizer = ChunkOptimizer(overlap=200)  # Effective overlap = 50 words
    >>> content = "Beginning of chunk. Middle section here. Final sentence of chunk."
    >>> overlap = optimizer._get_overlap_content(content)
    >>> # May return "Final sentence of chunk." if it fits within word limit
    
    >>> short_content = "Very short chunk."
    >>> overlap = optimizer._get_overlap_content(short_content)
    >>> # Returns "Very short chunk." or empty string based on word count

Notes:
    - Conservative overlap (1/4) prevents excessive redundancy between chunks
    - Prefers semantic boundaries (sentences) over arbitrary word cuts
    - Empty string return prevents prepending meaningless fragments
    - Single sentence overlaps are preferred over partial multi-sentence

Areas for Improvement:
    - Make the 1/4 reduction factor configurable
    - Add option for paragraph-based overlap for structured documents
    - Implement smart overlap sizing based on content complexity
    - Consider overlap quality scoring to select best sentences
    - Add support for preserving key entities or topics in overlap
    - Handle special cases like bullet points or numbered lists
    - Add minimum overlap size to ensure meaningful context
    - Consider semantic importance when selecting overlap content
    """
```
* **Async:** False
* **Method:** True
* **Class:** ChunkOptimizer

## _optimize_boundaries

```python
def _optimize_boundaries(self, chunks: List[Dict[str, Any]], full_text: str) -> List[Dict[str, Any]]:
    """
    Optimize chunk boundaries to improve coherence and avoid incomplete semantic units.

This method refines the boundaries of existing chunks to ensure they end at natural
breaking points such as sentence endings. It focuses on middle chunks (not first or last)
since they are most likely to have arbitrary boundaries from the chunking process.
The optimization helps prevent chunks from ending mid-sentence or mid-thought.

Args:
    chunks (List[Dict[str, Any]]): List of chunk dictionaries to optimize. Each chunk
        should contain at least a 'content' field with the text to be optimized.
        Chunks are modified in-place within new dictionaries.
    full_text (str): The complete original text from which chunks were created.
        Currently unused but provided for potential future enhancements such as
        looking ahead to next chunk content.

Returns:
    List[Dict[str, Any]]: A new list of optimized chunk dictionaries with updated:
        - 'content': Potentially shortened text ending at sentence boundary
        - 'token_count': Updated word count after optimization
        - 'word_count': Updated word count after optimization
        - 'char_count': Updated character count after optimization
        All other fields are preserved from the original chunks.

Optimization Strategy:
    - First and last chunks are preserved as-is
    - Middle chunks have their end boundaries optimized
    - Removes incomplete sentences at chunk ends
    - Updates relevant statistics after content modification

Examples:
    >>> chunks = [
    ...     {'content': 'First chunk content.'},
    ...     {'content': 'Middle chunk with incomplete sent'},
    ...     {'content': 'Last chunk content.'}
    ... ]
    >>> optimized = optimizer._optimize_boundaries(chunks, full_text)
    >>> # Middle chunk may be shortened to remove incomplete sentence

Notes:
    - Only end boundaries are currently optimized, not start boundaries
    - Single-chunk lists are returned unchanged
    - The full_text parameter is not currently utilized
    - Optimization may result in slightly smaller chunks

Areas for Improvement:
    - Implement start boundary optimization for better sentence beginnings
    - Use full_text to look ahead and redistribute content between chunks
    - Add configuration for optimization aggressiveness
    - Consider preserving removed content in metadata for recovery
    - Implement optimization for other semantic boundaries (paragraphs, sections)
    - Add metrics to measure optimization effectiveness
    - Support for undo/rollback of optimization
    - Consider bi-directional optimization between adjacent chunks
    """
```
* **Async:** False
* **Method:** True
* **Class:** ChunkOptimizer

## _optimize_end_boundary

```python
def _optimize_end_boundary(self, content: str) -> str:
    """
    Optimize the ending boundary of a chunk to ensure it concludes at a natural break point.

This method examines the end of a chunk's content and removes incomplete or very short
final sentences that would be better included with the next chunk. It helps ensure
chunks end with complete thoughts, improving readability and comprehension when chunks
are processed independently.

Args:
    content (str): The chunk content to optimize. Expected to contain one or more
        sentences that may not end at an ideal boundary due to size-based cutting.

Returns:
    str: The optimized content with incomplete final sentences removed. If the last
        sentence is complete and substantial, returns the original content. If optimization
        occurs, ensures the result ends with proper punctuation.

Optimization Criteria:
    - Removes last sentence if it has fewer than 5 words
    - Removes last sentence if it doesn't end with terminal punctuation (., !, ?)
    - Preserves single-sentence chunks even if they don't meet criteria
    - Ensures result ends with a period if sentences were removed

Examples:
    >>> # Remove incomplete sentence
    >>> content = "This is a complete sentence. This is not comp"
    >>> optimized = optimizer._optimize_end_boundary(content)
    >>> print(optimized)  # "This is a complete sentence."
    
    >>> # Remove very short sentence
    >>> content = "This is a long sentence with substance. Too short."
    >>> optimized = optimizer._optimize_end_boundary(content)
    >>> print(optimized)  # "This is a long sentence with substance."
    
    >>> # Preserve complete content
    >>> content = "This ends properly with enough words in the last sentence."
    >>> optimized = optimizer._optimize_end_boundary(content)
    >>> print(optimized)  # Original content unchanged

Notes:
    - Relies on _split_sentences for sentence detection
    - The 5-word threshold is hardcoded and may not suit all content types
    - Always preserves at least one sentence to avoid empty chunks
    - Adds periods to ensure proper ending punctuation

Areas for Improvement:
    - Make word count threshold configurable
    - Consider sentence quality beyond just length
    - Handle other valid sentence endings (quotes, parentheses)
    - Preserve ellipses (...) as valid endings
    - Add language-specific sentence ending rules
    - Consider semantic completeness, not just punctuation
    - Handle edge cases like URLs or abbreviations at sentence end
    - Add option to move incomplete sentences to next chunk instead of removing
    """
```
* **Async:** False
* **Method:** True
* **Class:** ChunkOptimizer

## _split_sentences

```python
def _split_sentences(self, text: str) -> List[str]:
    """
    Split text into individual sentences using regex-based pattern matching.

This method implements sentence boundary detection using regular expressions that
identify terminal punctuation followed by whitespace. It handles common sentence
endings (periods, exclamation marks, question marks) and filters out empty results
to provide clean sentence segmentation.

Args:
    text (str): The text to split into sentences. Can be a single sentence,
        paragraph, or multi-paragraph text. No preprocessing is required.

Returns:
    List[str]: A list of sentences with whitespace trimmed. Empty strings are
        filtered out. Returns empty list if input text contains no valid sentences.
        Each sentence retains its terminal punctuation.

Regex Pattern:
    - (?<=[.!?])\s+ : Positive lookbehind for terminal punctuation followed by whitespace
    - Splits after ., !, or ? when followed by spaces
    - Preserves the punctuation with the preceding sentence

Examples:
    >>> text = "First sentence. Second sentence! Is this third? Yes."
    >>> sentences = optimizer._split_sentences(text)
    >>> print(sentences)
    ['First sentence.', 'Second sentence!', 'Is this third?', 'Yes.']
    
    >>> # Handles multiple spaces
    >>> text = "Sentence one.    Sentence two."
    >>> sentences = optimizer._split_sentences(text)
    >>> print(len(sentences))  # 2
    
    >>> # Single sentence without terminal punctuation
    >>> text = "Incomplete sentence without period"
    >>> sentences = optimizer._split_sentences(text)
    >>> print(sentences)  # ['Incomplete sentence without period']

Notes:
    - Does not handle abbreviations (e.g., "Dr.", "Inc.")
    - May incorrectly split on decimal numbers (e.g., "3.14")
    - Assumes whitespace after punctuation indicates sentence boundary
    - Does not recognize ellipses (...) as sentence boundaries
    - Terminal punctuation inside quotes may cause incorrect splits

Areas for Improvement:
    - Add abbreviation detection to avoid false splits
    - Handle decimal numbers and times (e.g., "3.14", "2:30 p.m.")
    - Support for ellipses as valid sentence endings
    - Consider quotation mark handling ("He said 'Hello.'")
    - Add support for other sentence endings (e.g., Chinese period "。")
    - Implement ML-based sentence detection for complex cases
    - Handle edge cases like URLs with periods
    - Add configuration for custom sentence boundaries
    - Consider using NLTK or spaCy for more robust splitting
    """
```
* **Async:** False
* **Method:** True
* **Class:** ChunkOptimizer

## merge_small_chunks

```python
def merge_small_chunks(self, chunks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Merge consecutive chunks that fall below the minimum size threshold.

This method post-processes a list of chunks by combining undersized chunks with their
neighbors to improve processing efficiency and maintain better context. It iterates
through chunks sequentially, merging small chunks with the next chunk if the combined
size remains within limits. This helps eliminate fragments while preserving quality.

Args:
    chunks (List[Dict[str, Any]]): List of chunk dictionaries to process. Each chunk
        must contain at minimum:
        - 'content' (str): Text content of the chunk
        - 'word_count' (int): Number of words in the chunk
        - 'paragraphs' (List[str]): List of paragraphs in the chunk
        Empty list returns empty list.

Returns:
    List[Dict[str, Any]]: A new list of chunks with small chunks merged. Merged chunks
        contain:
        - Combined content with double newline separation
        - Updated word counts and statistics
        - Concatenated paragraph lists
        - 'chunk_type' set to 'merged'
        - Recalculated quality metrics
        - New quality score

Merging Logic:
    1. Iterate through chunks sequentially
    2. If chunk is too small (word_count < min_size) and not the last:
    - Check if merging with next chunk stays within max_size
    - If yes: merge and skip next chunk
    - If no: keep original chunk
    3. Last chunk is never merged (nowhere to merge to)
    4. Quality metrics are recalculated for merged chunks

Examples:
    >>> chunks = [
    ...     {'content': 'Small chunk', 'word_count': 2, 'paragraphs': ['Small chunk']},
    ...     {'content': 'Another small one', 'word_count': 3, 'paragraphs': ['Another small one']},
    ...     {'content': 'Normal sized chunk with more content', 'word_count': 7, 'paragraphs': ['Normal sized chunk with more content']}
    ... ]
    >>> optimizer = ChunkOptimizer(min_size=5)
    >>> merged = optimizer.merge_small_chunks(chunks)
    >>> print(len(merged))  # Likely 2 instead of 3
    >>> print(merged[0]['chunk_type'])  # 'merged'

Notes:
    - Only merges adjacent chunks (no look-ahead beyond next)
    - Preserves chunk order in the document
    - May result in chunks exceeding max_size in edge cases
    - Quality scores are recalculated for merged chunks
    - Original chunks are not modified (new dictionaries created)

Areas for Improvement:
    - Implement look-ahead to find best merge candidates
    - Add option to merge backwards (with previous chunk)
    - Consider content similarity when deciding to merge
    - Add configurable merge strategy (greedy, optimal, balanced)
    - Implement three-way merging for very small chunks
    - Add metrics tracking for merge operations
    - Consider preserving original chunk boundaries in metadata
    - Add option to redistribute content between chunks
    - Implement quality threshold to prevent bad merges
    - Add support for non-consecutive chunk merging based on topic
    """
```
* **Async:** False
* **Method:** True
* **Class:** ChunkOptimizer

## optimize_chunks

```python
def optimize_chunks(self, text: str, preserve_structure: bool = True) -> List[Dict[str, Any]]:
    """
    Create optimized text chunks with comprehensive quality scoring and boundary refinement.

This method serves as the primary interface for text chunking, orchestrating the entire
optimization pipeline. It creates initial chunks using either structure-aware or sliding
window approaches, optimizes chunk boundaries for better coherence, and calculates
quality metrics for each chunk. The resulting chunks are scored and ranked for
downstream processing prioritization.

Args:
    text (str): The input text to be chunked. Can be any length of prose text,
        including documents with multiple paragraphs, sections, or continuous text.
        Empty strings will return an empty list.
    preserve_structure (bool, optional): Whether to preserve document structure
        during chunking. When True, uses structure-aware chunking that respects
        paragraph boundaries. When False, uses sliding window approach for
        uniform segmentation. Defaults to True.

Returns:
    List[Dict[str, Any]]: A list of optimized chunk dictionaries, each containing:
        - 'content' (str): The actual text content of the chunk
        - 'token_count' (int): Estimated token count (currently word count)
        - 'paragraph_count' (int): Number of paragraphs in the chunk
        - 'sentence_count' (int): Number of sentences in the chunk
        - 'chunk_type' (str): Type of chunking used ('structure_aware' or 'sliding_window')
        - 'word_count' (int): Actual word count of the chunk
        - 'char_count' (int): Character count of the chunk
        - 'paragraphs' (List[str]): List of individual paragraphs in the chunk
        - 'metrics' (ChunkMetrics): Detailed quality metrics object
        - 'quality_score' (float): Overall quality score (0.0-1.0)
        - Additional fields depending on chunk type (e.g., 'start_index', 'end_index')

Raises:
    Currently no exceptions are explicitly raised, but potential issues include:
    - Memory errors for extremely large texts
    - Regex errors in sentence splitting

Examples:
    >>> optimizer = ChunkOptimizer(max_size=1000)
    >>> text = "Long document with multiple paragraphs..."
    
    >>> # Structure-preserving chunking
    >>> chunks = optimizer.optimize_chunks(text, preserve_structure=True)
    >>> print(f"Created {len(chunks)} chunks")
    >>> print(f"First chunk quality: {chunks[0]['quality_score']:.2f}")
    
    >>> # Sliding window chunking
    >>> uniform_chunks = optimizer.optimize_chunks(text, preserve_structure=False)
    >>> high_quality = [c for c in uniform_chunks if c['quality_score'] > 0.8]

Notes:
    - Empty text returns an empty list without error
    - Quality scores combine coherence, completeness, length, and semantic density
    - Boundary optimization may reduce chunk sizes to improve completeness
    - Structure-aware chunking typically produces higher quality scores
    - Processing time scales linearly with text length

Areas for Improvement:
    - Add progress callback for long documents
    - Implement caching for repeated text processing
    - Add option to return only high-quality chunks above a threshold
    - Consider parallel processing for very large texts
    - Add memory usage estimation for large documents
    - Implement custom quality weight configuration
    - Add support for preserving special formatting (markdown, code blocks)
    - Consider returning generator for memory efficiency with huge texts
    """
```
* **Async:** False
* **Method:** True
* **Class:** ChunkOptimizer
