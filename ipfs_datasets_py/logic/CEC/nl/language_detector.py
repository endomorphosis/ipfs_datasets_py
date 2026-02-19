"""
Language Detection Module for CEC Natural Language Processing.

This module provides automatic language detection for natural language input,
supporting English, Spanish, French, and German with high accuracy.

Classes:
    Language: Enumeration of supported languages
    LanguageDetector: Main language detection class with multiple detection strategies

Usage:
    >>> from ipfs_datasets_py.logic.CEC.nl.language_detector import LanguageDetector, Language
    >>> detector = LanguageDetector()
    >>> language = detector.detect("This is an obligation")
    >>> language == Language.ENGLISH
    True
    >>> language = detector.detect("Esta es una obligación")
    >>> language == Language.SPANISH
    True
"""

from enum import Enum
from typing import Dict, List, Optional, Tuple
import re
from collections import Counter


class Language(Enum):
    """Supported languages for CEC natural language processing."""
    
    ENGLISH = "en"
    SPANISH = "es"
    FRENCH = "fr"
    GERMAN = "de"
    UNKNOWN = "unknown"
    
    def __str__(self) -> str:
        return self.value
    
    @classmethod
    def from_code(cls, code: str) -> 'Language':
        """Get Language from language code.
        
        Args:
            code: Language code (e.g., 'en', 'es', 'fr', 'de')
            
        Returns:
            Language enum value
            
        Raises:
            ValueError: If code is not supported
        """
        code = code.lower()
        for lang in cls:
            if lang.value == code:
                return lang
        raise ValueError(f"Unsupported language code: {code}")


class LanguageDetector:
    """
    Automatic language detection for CEC natural language input.
    
    This class implements multiple detection strategies:
    1. Character-based detection (special characters, diacritics)
    2. Keyword-based detection (common words, operators)
    3. Statistical n-gram analysis
    4. Fallback to English for ambiguous cases
    
    Attributes:
        confidence_threshold: Minimum confidence for language detection (default: 0.6)
        _language_keywords: Dict mapping languages to common keywords
        _language_patterns: Dict mapping languages to regex patterns
        _trigram_profiles: Dict mapping languages to character trigram frequencies
        
    Example:
        >>> detector = LanguageDetector()
        >>> lang, confidence = detector.detect_with_confidence("C'est une obligation")
        >>> lang == Language.FRENCH
        True
        >>> confidence > 0.8
        True
    """
    
    def __init__(self, confidence_threshold: float = 0.4):
        """Initialize language detector.
        
        Args:
            confidence_threshold: Minimum confidence for detection (0.0-1.0)
        """
        self.confidence_threshold = confidence_threshold
        self._language_keywords = self._init_language_keywords()
        self._language_patterns = self._init_language_patterns()
        self._trigram_profiles = self._init_trigram_profiles()
    
    def _init_language_keywords(self) -> Dict[Language, List[str]]:
        """Initialize keyword lists for each language.
        
        Returns:
            Dict mapping Language to list of common keywords
        """
        return {
            Language.ENGLISH: [
                'the', 'is', 'are', 'a', 'an', 'and', 'or', 'not', 'must', 'shall',
                'may', 'can', 'should', 'would', 'will', 'obligation', 'permission',
                'prohibited', 'required', 'allowed', 'if', 'then', 'always', 'never',
                'knows', 'believes', 'intends', 'obligated', 'permitted'
            ],
            Language.SPANISH: [
                'el', 'la', 'es', 'son', 'un', 'una', 'y', 'o', 'no', 'debe', 'puede',
                'podrá', 'debería', 'será', 'obligación', 'permiso', 'prohibido',
                'requerido', 'permitido', 'si', 'entonces', 'siempre', 'nunca',
                'sabe', 'cree', 'intenta', 'obligado', 'permitida', 'está'
            ],
            Language.FRENCH: [
                'le', 'la', 'les', 'est', 'sont', 'un', 'une', 'et', 'ou', 'ne', 'pas',
                'doit', 'peut', 'pourra', 'devrait', 'sera', 'obligation', 'permission',
                'interdit', 'requis', 'permis', 'si', 'alors', 'toujours', 'jamais',
                'sait', 'croit', 'intend', 'obligé', 'permise', 'c\'est'
            ],
            Language.GERMAN: [
                'der', 'die', 'das', 'ist', 'sind', 'ein', 'eine', 'und', 'oder',
                'nicht', 'muss', 'kann', 'soll', 'sollte', 'wird', 'verpflichtung',
                'erlaubnis', 'verboten', 'erforderlich', 'erlaubt', 'wenn', 'dann',
                'immer', 'nie', 'weiß', 'glaubt', 'beabsichtigt', 'verpflichtet',
                'gestattet', 'es'
            ]
        }
    
    def _init_language_patterns(self) -> Dict[Language, List[re.Pattern]]:
        """Initialize regex patterns for each language.
        
        Returns:
            Dict mapping Language to list of compiled regex patterns
        """
        return {
            Language.ENGLISH: [
                re.compile(r'\b(the|is|are)\b', re.IGNORECASE),
                re.compile(r'\b(must|shall|may)\b', re.IGNORECASE),
                re.compile(r'[a-z]+tion\b', re.IGNORECASE),  # -tion ending
            ],
            Language.SPANISH: [
                re.compile(r'\b(el|la|es|está)\b', re.IGNORECASE),
                re.compile(r'\b(debe|puede|será)\b', re.IGNORECASE),
                re.compile(r'[áéíóú]'),  # Spanish accents
                re.compile(r'\b[a-z]+ción\b', re.IGNORECASE),  # -ción ending
            ],
            Language.FRENCH: [
                re.compile(r'\b(le|la|les|est|c\'est)\b', re.IGNORECASE),
                re.compile(r'\b(doit|peut|sera)\b', re.IGNORECASE),
                re.compile(r'[àâçéèêëïîôùûü]'),  # French accents
                re.compile(r'\b[a-z]+tion\b', re.IGNORECASE),  # -tion ending
            ],
            Language.GERMAN: [
                re.compile(r'\b(der|die|das|ist)\b', re.IGNORECASE),
                re.compile(r'\b(muss|kann|soll)\b', re.IGNORECASE),
                re.compile(r'[äöüß]'),  # German special characters
                re.compile(r'\b[A-ZÄÖÜ][a-zäöü]+\b'),  # Capitalized nouns
            ],
        }
    
    def _init_trigram_profiles(self) -> Dict[Language, Dict[str, float]]:
        """Initialize character trigram frequency profiles.
        
        These profiles are based on statistical analysis of typical
        CEC-related text in each language.
        
        Returns:
            Dict mapping Language to trigram frequency profiles
        """
        return {
            Language.ENGLISH: {
                'the': 0.05, 'ing': 0.03, 'and': 0.03, 'ion': 0.02, 'ent': 0.02,
                'for': 0.02, 'hat': 0.02, 'ter': 0.02, 'tha': 0.02, 'ere': 0.02
            },
            Language.SPANISH: {
                'ión': 0.04, 'la ': 0.03, 'el ': 0.03, 'de ': 0.03, 'en ': 0.03,
                'que': 0.03, 'es ': 0.02, 'ent': 0.02, 'con': 0.02, 'ado': 0.02
            },
            Language.FRENCH: {
                'les': 0.04, 'ion': 0.03, 'de ': 0.03, 'le ': 0.03, 'ent': 0.03,
                'que': 0.03, 'est': 0.02, 'et ': 0.02, 'ont': 0.02, 'ait': 0.02
            },
            Language.GERMAN: {
                'der': 0.04, 'die': 0.04, 'und': 0.03, 'den': 0.03, 'cht': 0.03,
                'ung': 0.03, 'ich': 0.02, 'ein': 0.02, 'sch': 0.02, 'auf': 0.02
            },
        }
    
    def detect(self, text: str) -> Language:
        """Detect language from text.
        
        Args:
            text: Input text to analyze
            
        Returns:
            Detected Language enum value
        """
        language, _ = self.detect_with_confidence(text)
        return language
    
    def detect_with_confidence(self, text: str) -> Tuple[Language, float]:
        """Detect language with confidence score.
        
        This method combines multiple detection strategies:
        1. Pattern-based detection (70% weight)
        2. Keyword frequency (20% weight)
        3. Trigram analysis (10% weight)
        
        Args:
            text: Input text to analyze
            
        Returns:
            Tuple of (Language, confidence_score)
            
        Example:
            >>> detector = LanguageDetector()
            >>> lang, conf = detector.detect_with_confidence("Ceci est un test")
            >>> lang == Language.FRENCH
            True
        """
        if not text or not text.strip():
            return Language.UNKNOWN, 0.0
        
        text = text.lower().strip()
        
        # Combine scores from different strategies
        pattern_scores = self._pattern_based_detection(text)
        keyword_scores = self._keyword_based_detection(text)
        trigram_scores = self._trigram_based_detection(text)
        
        # Weighted combination
        final_scores: Dict[Language, float] = {}
        for lang in Language:
            if lang == Language.UNKNOWN:
                continue
            
            pattern_score = pattern_scores.get(lang, 0.0)
            keyword_score = keyword_scores.get(lang, 0.0)
            trigram_score = trigram_scores.get(lang, 0.0)
            
            # Weights: pattern 50%, keywords 35%, trigrams 15%
            # Adjusted to give more weight to keywords which are more reliable
            final_scores[lang] = (
                0.5 * pattern_score +
                0.35 * keyword_score +
                0.15 * trigram_score
            )
        
        if not final_scores:
            return Language.UNKNOWN, 0.0
        
        # Get language with highest score
        best_language = max(final_scores, key=lambda k: final_scores[k])
        best_score = final_scores[best_language]
        
        # Return UNKNOWN if confidence below threshold
        if best_score < self.confidence_threshold:
            return Language.UNKNOWN, best_score
        
        return best_language, best_score
    
    def _pattern_based_detection(self, text: str) -> Dict[Language, float]:
        """Detect language using regex patterns.
        
        Args:
            text: Lowercased input text
            
        Returns:
            Dict mapping Language to pattern match scores (0.0-1.0)
        """
        scores: Dict[Language, float] = {}
        
        for language, patterns in self._language_patterns.items():
            matches = 0
            for pattern in patterns:
                if pattern.search(text):
                    matches += 1
            
            # Normalize by number of patterns
            scores[language] = matches / len(patterns) if patterns else 0.0
        
        return scores
    
    def _keyword_based_detection(self, text: str) -> Dict[Language, float]:
        """Detect language using keyword frequency.
        
        Args:
            text: Lowercased input text
            
        Returns:
            Dict mapping Language to keyword match scores (0.0-1.0)
        """
        words = text.split()
        word_set = set(words)
        scores: Dict[Language, float] = {}
        
        for language, keywords in self._language_keywords.items():
            keyword_set = set(keywords)
            matches = len(word_set & keyword_set)
            
            # Improved scoring: count both unique and total matches
            if len(words) > 0:
                # Also count total keyword occurrences (not just unique)
                total_matches = sum(1 for word in words if word in keyword_set)
                unique_ratio = matches / min(len(word_set), 10)  # Unique matches
                frequency_ratio = total_matches / len(words)      # Total frequency
                scores[language] = min(1.0, (unique_ratio + frequency_ratio) / 2)
            else:
                scores[language] = 0.0
        
        return scores
    
    def _trigram_based_detection(self, text: str) -> Dict[Language, float]:
        """Detect language using character trigram analysis.
        
        Args:
            text: Lowercased input text
            
        Returns:
            Dict mapping Language to trigram similarity scores (0.0-1.0)
        """
        # Extract trigrams from text
        text_trigrams = self._extract_trigrams(text)
        if not text_trigrams:
            return {lang: 0.0 for lang in self._trigram_profiles}
        
        scores: Dict[Language, float] = {}
        for language, profile in self._trigram_profiles.items():
            similarity = self._calculate_trigram_similarity(text_trigrams, profile)
            scores[language] = similarity
        
        return scores
    
    def _extract_trigrams(self, text: str) -> Dict[str, float]:
        """Extract character trigrams with frequencies.
        
        Args:
            text: Input text
            
        Returns:
            Dict mapping trigrams to relative frequencies
        """
        if len(text) < 3:
            return {}
        
        trigrams = [text[i:i+3] for i in range(len(text) - 2)]
        trigram_counts = Counter(trigrams)
        total = sum(trigram_counts.values())
        
        return {
            trigram: count / total
            for trigram, count in trigram_counts.items()
        }
    
    def _calculate_trigram_similarity(
        self,
        text_trigrams: Dict[str, float],
        profile: Dict[str, float]
    ) -> float:
        """Calculate similarity between text trigrams and language profile.
        
        Uses cosine similarity between trigram frequency vectors.
        
        Args:
            text_trigrams: Trigram frequencies from input text
            profile: Language trigram profile
            
        Returns:
            Similarity score (0.0-1.0)
        """
        if not text_trigrams or not profile:
            return 0.0
        
        # Get common trigrams
        common_trigrams = set(text_trigrams.keys()) & set(profile.keys())
        if not common_trigrams:
            return 0.0
        
        # Calculate dot product
        dot_product = sum(
            text_trigrams[t] * profile[t]
            for t in common_trigrams
        )
        
        # Calculate magnitudes
        text_magnitude = sum(v * v for v in text_trigrams.values()) ** 0.5
        profile_magnitude = sum(v * v for v in profile.values()) ** 0.5
        
        if text_magnitude == 0 or profile_magnitude == 0:
            return 0.0
        
        # Cosine similarity
        return dot_product / (text_magnitude * profile_magnitude)
    
    def get_all_languages(self) -> List[Language]:
        """Get list of all supported languages (excluding UNKNOWN).
        
        Returns:
            List of Language enum values
        """
        return [lang for lang in Language if lang != Language.UNKNOWN]
    
    def is_supported(self, language: Language) -> bool:
        """Check if language is supported.
        
        Args:
            language: Language to check
            
        Returns:
            True if language is supported (not UNKNOWN)
        """
        return language != Language.UNKNOWN
