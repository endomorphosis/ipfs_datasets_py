"""
Multi-Language Support for Legal Search.

This module provides multi-language capabilities for legal search including
language detection, translation, cross-language citation extraction, and
support for international regulations (EU, etc.).

Features:
- Language detection for queries and results
- Translation layer for international regulations
- Language-specific legal term mappings
- Cross-language citation extraction
- EU regulations support (multiple languages)
- Language preference system
- Multilingual knowledge base entities

Usage:
    from ipfs_datasets_py.processors.legal_scrapers import MultiLanguageSupport
    
    ml = MultiLanguageSupport()
    
    # Detect language
    lang = ml.detect_language("Was sind die EPA-Vorschriften?")
    
    # Translate query
    translated = ml.translate_query("EPA regulations", target_lang="de")
    
    # Cross-language search
    results = ml.cross_language_search("water pollution", languages=["en", "de", "fr"])
"""

import logging
from typing import List, Dict, Optional, Any, Tuple, Union
from dataclasses import dataclass, field

# Optional language detection and translation imports
try:
    from langdetect import detect, detect_langs
    HAVE_LANGDETECT = True
except ImportError:
    HAVE_LANGDETECT = False
    detect = None
    detect_langs = None

try:
    from deep_translator import GoogleTranslator
    HAVE_TRANSLATOR = True
except ImportError:
    HAVE_TRANSLATOR = False
    GoogleTranslator = None

logger = logging.getLogger(__name__)


@dataclass
class LanguageConfig:
    """Configuration for multi-language support."""
    default_language: str = "en"
    supported_languages: List[str] = field(default_factory=lambda: ["en", "de", "fr", "es", "it"])
    enable_auto_detect: bool = True
    enable_translation: bool = True
    translation_cache_size: int = 1000


@dataclass
class TranslationResult:
    """Result of translation operation."""
    original_text: str
    translated_text: str
    source_lang: str
    target_lang: str
    confidence: float = 1.0


class MultiLanguageSupport:
    """
    Multi-language support for legal search.
    
    Provides comprehensive multi-language capabilities:
    - Language detection for queries and results
    - Translation layer for international regulations
    - Language-specific legal term mappings
    - Cross-language citation extraction
    - EU regulations support
    - Language preference system
    
    Example:
        >>> ml = MultiLanguageSupport()
        >>> lang = ml.detect_language("Was sind die EPA-Vorschriften?")  # "de"
        >>> translated = ml.translate_query("EPA regulations", target_lang="de")
        >>> results = ml.cross_language_search("water pollution", ["en", "de", "fr"])
    """
    
    # Legal term translations for common languages
    LEGAL_TERMS = {
        "en": {
            "regulation": "regulation",
            "law": "law",
            "statute": "statute",
            "court": "court",
            "agency": "agency",
            "compliance": "compliance",
            "enforcement": "enforcement",
        },
        "de": {
            "regulation": "Verordnung",
            "law": "Gesetz",
            "statute": "Satzung",
            "court": "Gericht",
            "agency": "Behörde",
            "compliance": "Einhaltung",
            "enforcement": "Durchsetzung",
        },
        "fr": {
            "regulation": "règlement",
            "law": "loi",
            "statute": "statut",
            "court": "tribunal",
            "agency": "agence",
            "compliance": "conformité",
            "enforcement": "application",
        },
        "es": {
            "regulation": "regulación",
            "law": "ley",
            "statute": "estatuto",
            "court": "tribunal",
            "agency": "agencia",
            "compliance": "cumplimiento",
            "enforcement": "aplicación",
        },
        "it": {
            "regulation": "regolamento",
            "law": "legge",
            "statute": "statuto",
            "court": "tribunale",
            "agency": "agenzia",
            "compliance": "conformità",
            "enforcement": "applicazione",
        }
    }
    
    # EU agency/authority mappings
    EU_AUTHORITIES = {
        "en": {
            "European Commission": ["European Commission", "EC"],
            "European Parliament": ["European Parliament", "EP"],
            "European Court of Justice": ["ECJ", "CJEU"],
            "European Medicines Agency": ["EMA"],
            "European Environment Agency": ["EEA"],
        },
        "de": {
            "European Commission": ["Europäische Kommission", "EK"],
            "European Parliament": ["Europäisches Parlament", "EP"],
            "European Court of Justice": ["EuGH", "Gerichtshof der Europäischen Union"],
            "European Medicines Agency": ["EMA", "Europäische Arzneimittel-Agentur"],
            "European Environment Agency": ["EUA", "Europäische Umweltagentur"],
        },
        "fr": {
            "European Commission": ["Commission européenne", "CE"],
            "European Parliament": ["Parlement européen", "PE"],
            "European Court of Justice": ["CJUE", "Cour de justice de l'Union européenne"],
            "European Medicines Agency": ["EMA", "Agence européenne des médicaments"],
            "European Environment Agency": ["AEE", "Agence européenne pour l'environnement"],
        }
    }
    
    def __init__(self, config: Optional[LanguageConfig] = None):
        """Initialize multi-language support.
        
        Args:
            config: Language configuration
        """
        self.config = config or LanguageConfig()
        self._translation_cache: Dict[Tuple[str, str, str], str] = {}
        
        # Check dependencies
        if not HAVE_LANGDETECT:
            logger.warning("langdetect not available, language detection disabled")
        if not HAVE_TRANSLATOR:
            logger.warning("deep-translator not available, translation disabled")
        
        logger.info(f"MultiLanguageSupport initialized (langdetect: {HAVE_LANGDETECT}, translator: {HAVE_TRANSLATOR})")
    
    def detect_language(
        self,
        text: str,
        return_probabilities: bool = False
    ) -> Union[str, List[Tuple[str, float]]]:
        """
        Detect language of text.
        
        Args:
            text: Text to detect language for
            return_probabilities: Whether to return probability distribution
            
        Returns:
            Language code (e.g., "en") or list of (lang, prob) tuples
        """
        if not HAVE_LANGDETECT:
            logger.warning("Language detection not available")
            return self.config.default_language if not return_probabilities else [(self.config.default_language, 1.0)]
        
        try:
            if return_probabilities:
                langs = detect_langs(text)
                return [(lang.lang, lang.prob) for lang in langs]
            else:
                return detect(text)
        except Exception as e:
            logger.warning(f"Language detection failed: {e}")
            return self.config.default_language if not return_probabilities else [(self.config.default_language, 1.0)]
    
    def translate_query(
        self,
        query: str,
        target_lang: str,
        source_lang: Optional[str] = None
    ) -> TranslationResult:
        """
        Translate query to target language.
        
        Args:
            query: Query to translate
            target_lang: Target language code
            source_lang: Source language (auto-detected if None)
            
        Returns:
            TranslationResult
        """
        if not HAVE_TRANSLATOR:
            logger.warning("Translation not available")
            return TranslationResult(
                original_text=query,
                translated_text=query,
                source_lang=source_lang or "en",
                target_lang=target_lang,
                confidence=0.0
            )
        
        # Detect source language if not provided
        if source_lang is None:
            source_lang = self.detect_language(query)
        
        # Check cache
        cache_key = (query, source_lang, target_lang)
        if cache_key in self._translation_cache:
            translated = self._translation_cache[cache_key]
            return TranslationResult(
                original_text=query,
                translated_text=translated,
                source_lang=source_lang,
                target_lang=target_lang
            )
        
        # Translate
        try:
            translator = GoogleTranslator(source=source_lang, target=target_lang)
            translated = translator.translate(query)
            
            # Cache result
            if len(self._translation_cache) < self.config.translation_cache_size:
                self._translation_cache[cache_key] = translated
            
            return TranslationResult(
                original_text=query,
                translated_text=translated,
                source_lang=source_lang,
                target_lang=target_lang
            )
        
        except Exception as e:
            logger.warning(f"Translation failed: {e}")
            return TranslationResult(
                original_text=query,
                translated_text=query,
                source_lang=source_lang,
                target_lang=target_lang,
                confidence=0.0
            )
    
    def translate_legal_term(
        self,
        term: str,
        target_lang: str,
        source_lang: str = "en"
    ) -> str:
        """
        Translate legal term using predefined mappings.
        
        Args:
            term: Legal term to translate
            target_lang: Target language
            source_lang: Source language
            
        Returns:
            Translated term
        """
        term_lower = term.lower()
        
        # Check if term exists in mappings
        if source_lang in self.LEGAL_TERMS:
            source_terms = self.LEGAL_TERMS[source_lang]
            # Find matching term in source language
            for eng_term, source_term in source_terms.items():
                if term_lower == source_term.lower() and target_lang in self.LEGAL_TERMS:
                    return self.LEGAL_TERMS[target_lang].get(eng_term, term)
        
        # Fallback to general translation
        if HAVE_TRANSLATOR:
            result = self.translate_query(term, target_lang, source_lang)
            return result.translated_text
        
        return term
    
    def expand_query_multilingual(
        self,
        query: str,
        target_languages: List[str]
    ) -> Dict[str, str]:
        """
        Expand query to multiple languages.
        
        Args:
            query: Query to expand
            target_languages: List of target language codes
            
        Returns:
            Dictionary mapping language codes to translated queries
        """
        expansions = {}
        source_lang = self.detect_language(query)
        
        for target_lang in target_languages:
            if target_lang == source_lang:
                expansions[target_lang] = query
            else:
                result = self.translate_query(query, target_lang, source_lang)
                expansions[target_lang] = result.translated_text
        
        return expansions
    
    def detect_eu_authority(
        self,
        text: str,
        language: Optional[str] = None
    ) -> List[str]:
        """
        Detect EU authorities mentioned in text.
        
        Args:
            text: Text to search
            language: Language of text (auto-detected if None)
            
        Returns:
            List of detected EU authority names (English)
        """
        if language is None:
            language = self.detect_language(text)
        
        if language not in self.EU_AUTHORITIES:
            return []
        
        detected = []
        text_lower = text.lower()
        
        for authority, variants in self.EU_AUTHORITIES[language].items():
            for variant in variants:
                if variant.lower() in text_lower:
                    detected.append(authority)
                    break
        
        return list(set(detected))
    
    def normalize_citation_multilingual(
        self,
        citation: str,
        source_lang: str
    ) -> str:
        """
        Normalize citation to English format.
        
        Args:
            citation: Citation text
            source_lang: Source language
            
        Returns:
            Normalized citation (English)
        """
        # Translate legal terms in citation
        words = citation.split()
        normalized_words = []
        
        for word in words:
            # Try to translate as legal term
            translated = self.translate_legal_term(word, "en", source_lang)
            normalized_words.append(translated)
        
        return " ".join(normalized_words)
    
    def create_multilingual_knowledge_base(
        self,
        entities: List[Dict[str, Any]],
        target_languages: List[str]
    ) -> Dict[str, List[Dict[str, Any]]]:
        """
        Create multilingual knowledge base from entities.
        
        Args:
            entities: List of entity dictionaries
            target_languages: Languages to create entries for
            
        Returns:
            Dictionary mapping languages to translated entity lists
        """
        multilingual_kb = {}
        
        for lang in target_languages:
            translated_entities = []
            
            for entity in entities:
                translated_entity = entity.copy()
                
                # Translate name
                if "name" in entity:
                    result = self.translate_query(entity["name"], lang)
                    translated_entity["name"] = result.translated_text
                
                # Translate description if present
                if "description" in entity:
                    result = self.translate_query(entity["description"], lang)
                    translated_entity["description"] = result.translated_text
                
                translated_entity["language"] = lang
                translated_entities.append(translated_entity)
            
            multilingual_kb[lang] = translated_entities
        
        return multilingual_kb
    
    def cross_language_search(
        self,
        query: str,
        languages: List[str],
        search_function: Optional[callable] = None
    ) -> Dict[str, List[Dict[str, Any]]]:
        """
        Perform search across multiple languages.
        
        Args:
            query: Original query
            languages: Languages to search in
            search_function: Function to perform search (takes query, returns results)
            
        Returns:
            Dictionary mapping languages to search results
        """
        results = {}
        
        # Translate query to each language
        translated_queries = self.expand_query_multilingual(query, languages)
        
        # Search in each language
        for lang, translated_query in translated_queries.items():
            if search_function:
                lang_results = search_function(translated_query)
                results[lang] = lang_results
            else:
                # Placeholder if no search function provided
                results[lang] = [{
                    "query": translated_query,
                    "language": lang
                }]
        
        return results
    
    def merge_multilingual_results(
        self,
        results_by_language: Dict[str, List[Dict[str, Any]]],
        deduplicate: bool = True
    ) -> List[Dict[str, Any]]:
        """
        Merge results from multiple languages.
        
        Args:
            results_by_language: Results grouped by language
            deduplicate: Whether to remove duplicate URLs
            
        Returns:
            Merged and optionally deduplicated results
        """
        merged = []
        seen_urls = set()
        
        for lang, results in results_by_language.items():
            for result in results:
                url = result.get("url", "")
                
                if deduplicate and url and url in seen_urls:
                    continue
                
                # Add language metadata
                result["source_language"] = lang
                merged.append(result)
                
                if url:
                    seen_urls.add(url)
        
        return merged
    
    def get_supported_languages(self) -> List[str]:
        """Get list of supported languages."""
        return self.config.supported_languages
    
    def is_eu_language(self, lang_code: str) -> bool:
        """Check if language is an official EU language."""
        eu_languages = [
            "bg", "cs", "da", "de", "el", "en", "es", "et", "fi", "fr",
            "ga", "hr", "hu", "it", "lt", "lv", "mt", "nl", "pl", "pt",
            "ro", "sk", "sl", "sv"
        ]
        return lang_code in eu_languages
