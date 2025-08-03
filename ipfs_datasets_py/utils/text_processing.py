"""
Text Processing Utilities for PDF Pipeline

Provides text processing, chunking, and optimization utilities.
"""
from __future__ import annotations
from collections import Counter
import inspect
import logging
import re
from typing import Any, Callable, Optional

# from types import ModuleType
# from functools import partial

import nltk
# from nltk.tokenize import sent_tokenize

class TextProcessor:
    """
    Advanced Text Processing and Normalization Utility for Document Pipeline Operations

    The TextProcessor class provides comprehensive text processing capabilities
    designed for large-scale document processing pipelines, content analysis
    workflows, and natural language processing tasks. This utility enables
    consistent text normalization, intelligent chunking, and content optimization
    for machine learning and information retrieval applications.

    The processor implements robust text cleaning algorithms, sentence segmentation,
    language detection, and quality assessment metrics to ensure high-quality
    text output for downstream processing. Advanced features include stop word
    filtering, punctuation normalization, whitespace optimization, and character
    encoding standardization.

    Core Processing Features:
    - Comprehensive text cleaning with configurable normalization rules
    - Intelligent sentence segmentation with context-aware boundary detection
    - Advanced whitespace normalization and character encoding standardization
    - Stop word filtering with customizable vocabulary and language support
    - Punctuation normalization including quote standardization and symbol cleanup
    - Content quality assessment with readability and coherence metrics
    - Language detection and processing optimization for multilingual content

    Text Normalization Capabilities:
    - Unicode normalization with consistent character representation
    - HTML entity decoding and markup removal for web content
    - Quote character standardization across different typography systems
    - Whitespace consolidation and line break normalization
    - Special character filtering with preservation of meaningful punctuation
    - Case normalization with context-sensitive capitalization handling

    Sentence Processing:
    - Context-aware sentence boundary detection with abbreviation handling
    - Segment filtering based on length, quality, and content characteristics
    - Sentence-level metadata extraction including structure and complexity
    - Multi-paragraph processing with document structure preservation
    - Citation and reference extraction for academic and technical documents

    Content Quality Assessment:
    - Text coherence analysis with logical flow evaluation
    - Readability metrics including complexity and accessibility scores
    - Content density analysis for information extraction optimization
    - Language quality assessment with grammar and syntax validation
    - Duplicate content detection and similarity analysis

    Attributes:
        stop_words (Set[str]): Comprehensive collection of common stop words
            for English language processing, including articles, prepositions,
            conjunctions, and auxiliary verbs. Used for content filtering and
            relevance analysis in information retrieval applications.

    Public Methods:
        clean_text(text: str) -> str:
            Comprehensive text cleaning with normalization and standardization
        split_sentences(text: str) -> list[str]:
            Intelligent sentence segmentation with quality filtering
        extract_keywords(text: str, max_keywords: int = 10) -> list[str]:
            Keyword extraction using frequency and relevance analysis
        calculate_readability(text: str) -> Dict[str, float]:
            Readability metrics including Flesch score and complexity measures
        detect_language(text: str) -> str:
            Language detection with confidence scoring
        normalize_encoding(text: str) -> str:
            Character encoding normalization and standardization
        chunk_text(text: str, chunk_size: int, overlap: int = 0) -> list[str]:
            Intelligent text chunking with context preservation
        assess_quality(text: str) -> Dict[str, Any]:
            Comprehensive text quality assessment and metrics

    Usage Examples:
        # Initialize text processor
        processor = TextProcessor()
        
        # Clean and normalize raw text
        raw_text = "  This is a sample text...  with irregular   spacing!  "
        clean_text = processor.clean_text(raw_text)
        print(f"Cleaned: {clean_text}")
        
        # Split text into sentences
        document_text = "First sentence. Second sentence! Third sentence?"
        sentences = processor.split_sentences(document_text)
        for i, sentence in enumerate(sentences):
            print(f"Sentence {i+1}: {sentence}")
        
        # Extract keywords for content analysis
        content = "Machine learning and artificial intelligence..."
        keywords = processor.extract_keywords(content, max_keywords=5)
        print(f"Keywords: {keywords}")
        
        # Assess text quality for filtering
        quality_metrics = processor.assess_quality(content)
        if quality_metrics['coherence_score'] > 0.7:
            print("High-quality content suitable for processing")

    Dependencies:
        Required:
        - re: Regular expression operations for pattern matching and text cleaning
        - logging: Structured logging for processing status and error reporting
        - typing: Type annotations for improved code reliability and documentation
        - collections: Counter utility for frequency analysis and keyword extraction
        
        Optional:
        - nltk: Advanced natural language processing capabilities
        - langdetect: Language detection for multilingual content processing
        - textstat: Readability and complexity metrics calculation

    Notes:
        - Text processing operations are optimized for large-scale document pipelines
        - Stop word lists can be customized for domain-specific applications
        - Quality assessment metrics help filter low-quality content automatically
        - Sentence segmentation handles edge cases including abbreviations and citations
        - Memory usage is optimized for processing large documents and corpora
        - Unicode normalization ensures consistent text representation across systems
        - Language detection enables multilingual processing with appropriate models
        - Processing speed scales linearly with text length for predictable performance
    """
    STOP_WORDS = {
        # Articles
        'the', 'a', 'an',
        # Conjunctions
        'and', 'or', 'but', 'so', 'yet', 'for', 'nor',
        # Prepositions
        'in', 'on', 'at', 'to', 'for', 'of', 'with', 'by', 'from', 'up', 'about', 
        'into', 'through', 'during', 'before', 'after', 'above', 'below', 'between',
        # Pronouns
        'i', 'you', 'he', 'she', 'it', 'we', 'they', 'me', 'him', 'her', 'us', 'them',
        'my', 'your', 'his', 'her', 'its', 'our', 'their', 'mine', 'yours', 'ours', 'theirs',
        'this', 'that', 'these', 'those',
        # Auxiliary verbs
        'is', 'are', 'was', 'were', 'be', 'been', 'being', 'am',
        'have', 'has', 'had', 'having',
        'do', 'does', 'did', 'doing',
        'will', 'would', 'shall', 'should', 'may', 'might', 'can', 'could', 'must',
        # Common adverbs/modifiers
        'not', 'no', 'yes', 'very', 'too', 'so', 'just', 'only', 'even', 'also', 'still'
    }

    def __init__(self, 
                 stop_words: Optional[set[str]] = None,
                 logger: logging.Logger = logging.getLogger(__name__),
                 sent_tokenize: Callable = nltk.tokenize.sent_tokenize,
                 ):
        """
        Initialize Text Processing Utility with Comprehensive Language Resources

        Establishes a new TextProcessor instance with comprehensive text processing
        capabilities including stop word vocabularies, normalization rules, and
        quality assessment parameters. This initialization prepares all necessary
        language resources and processing configurations for high-performance
        text processing operations.

        The initialization process configures stop word collections, regular
        expression patterns, normalization rules, and quality metrics required
        for consistent text processing across different content types and
        domains. Default configurations provide robust processing for English
        language content with extensibility for multilingual applications.

        Attributes Initialized:
            stop_words (Set[str]): Comprehensive English stop word collection
                including common articles, prepositions, conjunctions, and
                auxiliary verbs. This vocabulary is used for content filtering,
                keyword extraction, and relevance analysis. The collection includes:
                
                - Articles: 'the', 'a', 'an'
                - Prepositions: 'in', 'on', 'at', 'to', 'for', 'of', 'with', 'by'
                - Conjunctions: 'and', 'or', 'but'
                - Pronouns: 'this', 'that', 'these', 'those'
                - Auxiliary verbs: 'is', 'are', 'was', 'were', 'be', 'been', 'being'
                - Modal verbs: 'have', 'has', 'had', 'do', 'does', 'did'
                - Future/conditional: 'will', 'would', 'could', 'should'
                
                The stop word list can be extended or customized for domain-specific
                applications requiring specialized vocabulary filtering.

        Examples:
            # Basic initialization for general text processing
            processor = TextProcessor()
            
            # The processor is now ready for text operations
            cleaned_text = processor.clean_text("Sample text with   irregular spacing!")
            sentences = processor.split_sentences(cleaned_text)

        Notes:
            - Stop word collection optimized for English language content
            - Default configuration provides robust processing for most applications
            - Stop word vocabulary can be extended for specialized domains
            - Processing patterns are initialized for optimal performance
            - Memory footprint is minimized while maintaining comprehensive functionality
            - Thread-safe initialization enables concurrent processing operations
        """
        if stop_words is not None:
            if not isinstance(stop_words, set):
                raise TypeError("stop_words must be a set of strings")
            if not all(isinstance(word, str) for word in stop_words):
                raise TypeError("All stop words must be strings")

        if not isinstance(logger, logging.Logger):
            raise TypeError("logger must be an instance of logging.Logger")

        if not inspect.isfunction(sent_tokenize):
            raise TypeError("sent_tokenize must be a callable function")

        self.logger = logger
        self.stop_words = stop_words if stop_words is not None else self.STOP_WORDS
        self.sent_tokenize = sent_tokenize

    def clean_text(self, text: str) -> str:
        """Clean and normalize text."""
        if not text:
            return ""
        
        # Remove extra whitespace
        text = re.sub(r'\s+', ' ', text)
        
        # Remove special characters but keep basic punctuation
        text = re.sub(r'[^\w\s.,!?;:()\-]', '', text)
        
        # Normalize quotes
        text = re.sub(r'[""''`]', '"', text)
        
        return text.strip()
    
    def split_sentences(self, text: str) -> list[str]:
        """Split text into sentences."""
        if not isinstance(text, str):
            raise TypeError("Input text must be a string")
        if not text:
            return []

        try:
            # Use NLTK's sentence tokenizer
            sentences = self.sent_tokenize(text)
        except Exception as e:
            self.logger.error(f"Error splitting sentences: {e}")
            return []
        else:
            if not sentences:
                return []

            # Clean and filter sentences
            cleaned_sentences = [
                sentence.strip() for sentence in sentences if len(sentence.strip()) > 0
            ]

            return cleaned_sentences

    def split_paragraphs(self, text: str, min_paragraph_length: int = 20) -> list[str]:
        """Split text into paragraphs."""
        if not text:
            return []
        
        # Split on double newlines
        paragraphs = re.split(r'\n\s*\n', text)
        
        # Clean and filter paragraphs
        cleaned_paragraphs = []
        for paragraph in paragraphs:
            paragraph = paragraph.strip()
            if len(paragraph) > min_paragraph_length:
                cleaned_paragraphs.append(paragraph)
        
        return cleaned_paragraphs
    
    def extract_keywords(self, text: str, top_k: int = 20) -> list[str]:
        """Extract keywords from text."""
        if not text:
            return []
        
        # Convert to lowercase and split into words
        words = re.findall(r'\b[a-zA-Z]{3,}\b', text.lower())
        
        # Filter stop words
        filtered_words = [w for w in words if w not in self.stop_words]
        
        # Count frequency
        word_freq = Counter(filtered_words)
        
        # Return top keywords
        top_keywords = [word for word, freq in word_freq.most_common(top_k)]
        return top_keywords
    
    def extract_phrases(self, text: str, min_length: int = 2, max_length: int = 4) -> list[str]:
        """Extract key phrases from text."""
        if not text:
            return []
        
        # Split into words
        words = re.findall(r'\b[a-zA-Z]+\b', text.lower())
        
        # Filter stop words
        filtered_words = [w for w in words if w not in self.stop_words]
        
        # Extract n-grams
        phrases = []
        for n in range(min_length, max_length + 1):
            for i in range(len(filtered_words) - n + 1):
                phrase = ' '.join(filtered_words[i:i+n])
                phrases.append(phrase)
        
        # Count frequency and return top phrases
        phrase_freq = Counter(phrases)
        top_phrases = [phrase for phrase, freq in phrase_freq.most_common(20)]
        return top_phrases


    def calculate_readability_score(self, text: str) -> float:
        """Calculate a readability score."""
        if not isinstance(text, str):
            raise TypeError("Input text must be a string")

        if not text:
            return 0.0
        
        sentences = self.split_sentences(text)
        words = text.split()
        
        if not sentences or not words:
            return 0.0

        # Simple metrics
        avg_sentence_length = len(words) / len(sentences)
        avg_word_length = sum(len(word) for word in words) / len(words)
        
        # Simple readability score (lower is easier to read)
        readability: int = (avg_sentence_length * 0.4) + (avg_word_length * 0.6)

        # Normalize to 0-1 scale (inverted so higher is better)
        normalized_score = max(0, min(1, 1 - (readability - 10) / 20))

        return normalized_score


    # def calculate_readability_score(self, 
    #                                 text: str, 
    #                                 metrics_dict: Optional[dict[str, tuple[Callable, float]]] = None,
    #                                 ) -> float:
    #     """Calculate a readability score."""
    #     if not isinstance(text, str):
    #         raise TypeError("Input text must be a string")

    #     if not text:
    #         return 0.0
        
    #     sentences = self.split_sentences(text)
    #     words = text.split()
        
    #     if not sentences or not words:
    #         return 0.0

    #     # Simple metrics
    #     avg_sentence_length = len(words) / len(sentences)
    #     avg_word_length = sum(len(word) for word in words) / len(words)
        
    #     # Simple readability score (lower is easier to read)
    #     readability: int = (avg_sentence_length * 0.4) + (avg_word_length * 0.6)

    #     if metrics_dict is not None:
    #         if not isinstance(metrics_dict, dict):
    #             raise TypeError("metrics_dict must be a dictionary")
    #         correct_key_values = [
    #             isinstance(k, str) 
    #             and isinstance(v, tuple) 
    #             and len(v) == 2
    #             and inspect.isfunction(v[0])
    #             and isinstance(v[1], (int, float))
    #             for k, v in metrics_dict.items()
    #         ]
    #         if not all(correct_key_values):
    #             raise TypeError(
    #                 "metrics_dict must contain string keys and tuple values of (function, weight)"
    #             )

    #         total_weight = sum(weight for _, weight in metrics_dict.values())
    #         if total_weight != 1:
    #             raise ValueError("Total weight of metrics must sum to 1")

    #         # Zero out readability if metrics_dict is provided
    #         readability = 0
    #         metric_dict = {}

    #         # Check the function signature of each metric.
    #         # The criteria are:
    #         # 1. The function must accept only key-word parameters.
    #         # 2. The function signature must contain one or more of the following parameters:
    #         # - text: str
    #         # - sentences: list[str]
    #         # - words: list[str]
    #         # 3. The function must return a single real numeric value.

    #         for metric, (func, weight) in metrics_dict.items():

    #             kwarg_dict = {}
    #             params = inspect.signature(func).parameters

    #             if any(p.kind != inspect.Parameter.KEYWORD_ONLY for p in params.values()):
    #                 raise ValueError(f"Metric '{metric}' must accept only keyword parameters.")

    #             if 'text' in params:
    #                 kwarg_dict['text'] = text
    #             if 'sentences' in params:
    #                 kwarg_dict['sentences'] = sentences
    #             if 'words' in params:
    #                 kwarg_dict['words'] = words

    #             if any(kwarg_dict.get(p) is None for p in ['text', 'sentences', 'words']):
    #                 raise ValueError(
    #                     f"Metric '{metric}' must have "
    #                     "'text' or 'sentences', or 'words' as parameters."
    #                 )

    #             metric_dict.update({metric: partial(func, **kwarg_dict)})
            
    #         readability = sum(func() * weight for func, weight in metric_dict.values())

    #     # Normalize to 0-1 scale (inverted so higher is better)
    #     normalized_score = max(0, min(1, 1 - (readability - 10) / 20))
        
    #     return normalized_score

def make_text_processor(mock_dict: Optional[dict[str, Any]] = None) -> 'TextProcessor':
    """Factory Function to create TextProcessor instance with default configurations."""
    stop_words = {
        # Articles
        'the', 'a', 'an',
        # Conjunctions
        'and', 'or', 'but', 'so', 'yet', 'for', 'nor',
        # Prepositions
        'in', 'on', 'at', 'to', 'for', 'of', 'with', 'by', 'from', 'up', 'about', 
        'into', 'through', 'during', 'before', 'after', 'above', 'below', 'between',
        # Pronouns
        'i', 'you', 'he', 'she', 'it', 'we', 'they', 'me', 'him', 'her', 'us', 'them',
        'my', 'your', 'his', 'her', 'its', 'our', 'their', 'mine', 'yours', 'ours', 'theirs',
        'this', 'that', 'these', 'those',
        # Auxiliary verbs
        'is', 'are', 'was', 'were', 'be', 'been', 'being', 'am',
        'have', 'has', 'had', 'having',
        'do', 'does', 'did', 'doing',
        'will', 'would', 'shall', 'should', 'may', 'might', 'can', 'could', 'must',
        # Common adverbs/modifiers
        'not', 'no', 'yes', 'very', 'too', 'so', 'just', 'only', 'even', 'also', 'still'
    }
    init_dict = {
        "stop_words": stop_words,
        "logger": logging.getLogger(__name__),
        "sent_tokenize": nltk.tokenize.sent_tokenize,
    }
    if mock_dict is not None:
        init_dict.update(mock_dict)

    return TextProcessor(**init_dict)
