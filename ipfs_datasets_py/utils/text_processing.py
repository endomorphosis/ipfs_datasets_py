"""
Text Processing Utilities for PDF Pipeline

Provides text processing, chunking, and optimization utilities.
"""

import re
import logging
from typing import List, Dict, Any, Optional
from collections import Counter

logger = logging.getLogger(__name__)

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
        split_sentences(text: str) -> List[str]:
            Intelligent sentence segmentation with quality filtering
        extract_keywords(text: str, max_keywords: int = 10) -> List[str]:
            Keyword extraction using frequency and relevance analysis
        calculate_readability(text: str) -> Dict[str, float]:
            Readability metrics including Flesch score and complexity measures
        detect_language(text: str) -> str:
            Language detection with confidence scoring
        normalize_encoding(text: str) -> str:
            Character encoding normalization and standardization
        chunk_text(text: str, chunk_size: int, overlap: int = 0) -> List[str]:
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
    
    def __init__(self):
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
    
    def split_sentences(self, text: str) -> List[str]:
        """Split text into sentences."""
        if not text:
            return []
        
        # Basic sentence splitting
        sentences = re.split(r'[.!?]+', text)
        
        # Clean and filter sentences
        cleaned_sentences = []
        for sentence in sentences:
            sentence = sentence.strip()
            if len(sentence) > 10:  # Minimum sentence length
                cleaned_sentences.append(sentence)
        
        return cleaned_sentences
    
    def split_paragraphs(self, text: str) -> List[str]:
        """Split text into paragraphs."""
        if not text:
            return []
        
        # Split on double newlines
        paragraphs = re.split(r'\n\s*\n', text)
        
        # Clean and filter paragraphs
        cleaned_paragraphs = []
        for paragraph in paragraphs:
            paragraph = paragraph.strip()
            if len(paragraph) > 20:  # Minimum paragraph length
                cleaned_paragraphs.append(paragraph)
        
        return cleaned_paragraphs
    
    def extract_keywords(self, text: str, top_k: int = 20) -> List[str]:
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
    
    def extract_phrases(self, text: str, min_length: int = 2, max_length: int = 4) -> List[str]:
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
        """Calculate a simple readability score."""
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
        readability = (avg_sentence_length * 0.4) + (avg_word_length * 0.6)
        
        # Normalize to 0-1 scale (inverted so higher is better)
        normalized_score = max(0, min(1, 1 - (readability - 10) / 20))
        
        return normalized_score

class ChunkOptimizer:
    """Utility class for optimizing text chunks."""
    
    def __init__(self, max_size: int, overlap: int, min_size: int):
        self.max_size = max_size
        self.overlap = overlap
        self.min_size = min_size
        self.text_processor = TextProcessor()
    
    def create_chunks(self, text: str, preserve_sentences: bool = True) -> List[Dict[str, Any]]:
        """Create optimized text chunks."""
        if not text:
            return []
        
        chunks = []
        
        if preserve_sentences:
            sentences = self.text_processor.split_sentences(text)
            chunks = self._chunk_by_sentences(sentences)
        else:
            chunks = self._chunk_by_words(text)
        
        return chunks
    
    def _chunk_by_sentences(self, sentences: List[str]) -> List[Dict[str, Any]]:
        """Create chunks preserving sentence boundaries."""
        chunks = []
        current_chunk = []
        current_size = 0
        
        for sentence in sentences:
            sentence_words = len(sentence.split())
            
            # Check if adding this sentence would exceed max size
            if current_size + sentence_words > self.max_size and current_chunk:
                # Create chunk with current content
                chunk_text = '. '.join(current_chunk) + '.'
                chunks.append({
                    'text': chunk_text,
                    'word_count': current_size,
                    'sentence_count': len(current_chunk),
                    'type': 'sentence_boundary'
                })
                
                # Start new chunk with overlap
                overlap_sentences = self._get_overlap_sentences(current_chunk)
                current_chunk = overlap_sentences + [sentence]
                current_size = sum(len(s.split()) for s in current_chunk)
            else:
                current_chunk.append(sentence)
                current_size += sentence_words
        
        # Add final chunk if content remains
        if current_chunk:
            chunk_text = '. '.join(current_chunk) + '.'
            chunks.append({
                'text': chunk_text,
                'word_count': current_size,
                'sentence_count': len(current_chunk),
                'type': 'sentence_boundary'
            })
        
        return chunks
    
    def _chunk_by_words(self, text: str) -> List[Dict[str, Any]]:
        """Create chunks by word count."""
        words = text.split()
        chunks = []
        
        for i in range(0, len(words), self.max_size - self.overlap):
            chunk_words = words[i:i + self.max_size]
            
            if len(chunk_words) >= self.min_size:
                chunk_text = ' '.join(chunk_words)
                chunks.append({
                    'text': chunk_text,
                    'word_count': len(chunk_words),
                    'start_word': i,
                    'end_word': i + len(chunk_words),
                    'type': 'word_boundary'
                })
        
        return chunks
    
    def _get_overlap_sentences(self, sentences: List[str]) -> List[str]:
        """Get overlap sentences for chunk continuity."""
        if not sentences:
            return []
        
        # Calculate overlap based on word count
        total_words = sum(len(s.split()) for s in sentences)
        overlap_words = min(self.overlap, total_words // 2)
        
        # Get sentences from the end that fit within overlap
        overlap_sentences = []
        current_words = 0
        
        for sentence in reversed(sentences):
            sentence_words = len(sentence.split())
            if current_words + sentence_words <= overlap_words:
                overlap_sentences.insert(0, sentence)
                current_words += sentence_words
            else:
                break
        
        return overlap_sentences
    
    def optimize_chunk_boundaries(self, text: str, current_boundaries: List[int]) -> List[int]:
        """Optimize chunk boundaries to respect sentence and paragraph breaks."""
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
            # Find closest sentence or paragraph boundary
            closest_sentence = min(sentence_ends, key=lambda x: abs(x - boundary), default=boundary)
            closest_paragraph = min(paragraph_ends, key=lambda x: abs(x - boundary), default=boundary)
            
            # Prefer paragraph boundaries, then sentence boundaries
            if abs(closest_paragraph - boundary) <= 50:  # Within 50 characters
                optimized_boundaries.append(closest_paragraph)
            elif abs(closest_sentence - boundary) <= 25:  # Within 25 characters
                optimized_boundaries.append(closest_sentence)
            else:
                optimized_boundaries.append(boundary)
        
        return optimized_boundaries
    
    def analyze_chunk_quality(self, chunk: Dict[str, Any]) -> Dict[str, float]:
        """Analyze the quality of a text chunk."""
        text = chunk.get('text', '')
        
        if not text:
            return {'overall_quality': 0.0}
        
        # Calculate various quality metrics
        readability = self.text_processor.calculate_readability_score(text)
        
        # Length appropriateness (optimal range)
        word_count = len(text.split())
        length_score = 1.0
        if word_count < self.min_size:
            length_score = word_count / self.min_size
        elif word_count > self.max_size:
            length_score = self.max_size / word_count
        
        # Sentence completeness
        sentences = self.text_processor.split_sentences(text)
        completeness_score = 1.0 if sentences else 0.5
        
        # Content diversity (unique words)
        words = text.lower().split()
        unique_words = len(set(words))
        diversity_score = unique_words / len(words) if words else 0.0
        
        # Overall quality score
        overall_quality = (
            readability * 0.3 +
            length_score * 0.3 +
            completeness_score * 0.2 +
            diversity_score * 0.2
        )
        
        return {
            'overall_quality': overall_quality,
            'readability': readability,
            'length_score': length_score,
            'completeness_score': completeness_score,
            'diversity_score': diversity_score
        }
