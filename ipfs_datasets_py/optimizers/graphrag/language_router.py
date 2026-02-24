"""
Multi-language support and routing for GraphRAG ontology extraction.

This module provides automatic language detection and routing for GraphRAG
entity and relationship extraction across multiple languages. It enables
language-aware rule selection, domain vocabulary loading, and result
post-processing.

Components:
    - LanguageRouter: Main interface for language detection and routing
    - LanguageConfig: Configuration for language-specific extraction behavior
    - MultilingualExtractionResult: Result wrapper tracking language metadata
    - LanguageSpecificRules: Container for language-aware extraction rules

Example:
    >>> from ipfs_datasets_py.optimizers.graphrag.language_router import LanguageRouter
    >>> router = LanguageRouter()
    >>> text = "El paciente tiene una obligación de informar al médico"
    >>> language = router.detect_language(text)
    >>> language.value  # 'es'
    'es'
    >>> config = router.get_language_config(language)
    >>> config.domain_vocab.get('medical')[:3]  # Spanish medical terms
    ['paciente', 'médico', 'enfermedad']

Classes:
    LanguageRouter: Main router with language detection and config management
    LanguageConfig: Language-specific extraction configuration
    LanguageSpecificRules: Rules and patterns for language-aware extraction
    MultilingualExtractionResult: Result wrapper with language metadata
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Any
from enum import Enum
import logging
from functools import lru_cache

# Import existing language detector from CEC module
try:
    from ipfs_datasets_py.logic.CEC.nl.language_detector import (
        LanguageDetector,
        Language
    )
except ImportError:
    # Fallback if CEC module not available
    Language = None  # type: ignore
    LanguageDetector = None  # type: ignore


@dataclass
class LanguageConfig:
    """Configuration for language-specific ontology extraction.
    
    Attributes:
        language_code: ISO 639-1 language code (e.g., 'en', 'es', 'fr', 'de')
        language_name: Human-readable language name
        entity_type_keywords: Keywords for identifying entity types in this language
        relationship_type_keywords: Keywords for identifying relationship types
        domain_vocab: Domain-specific vocabulary for the language
        stopwords: Language-specific stopwords to exclude
        min_confidence_adjustment: Adjustment to confidence threshold for this language
        text_normalization_rules: Rules for normalizing text in this language
        pos_tagging_model: POS tagging model identifier for this language (optional)
        stemmer_config: Stemming configuration for this language
    """
    language_code: str
    language_name: str
    entity_type_keywords: Dict[str, List[str]] = field(default_factory=dict)
    relationship_type_keywords: Dict[str, List[str]] = field(default_factory=dict)
    domain_vocab: Dict[str, List[str]] = field(default_factory=dict)
    stopwords: List[str] = field(default_factory=list)
    min_confidence_adjustment: float = 0.0  # Adjust thresholds per language
    text_normalization_rules: List[Tuple[str, str]] = field(default_factory=list)
    pos_tagging_model: Optional[str] = None
    stemmer_config: Dict[str, Any] = field(default_factory=dict)
    
    def apply_confidence_adjustment(self, confidence: float) -> float:
        """Apply language-specific confidence adjustment.
        
        Some languages may be inherently harder to process due to morphology,
        ambiguity, or domain specificity. This adjusts the confidence threshold.
        
        Args:
            confidence: Original confidence score (0.0-1.0)
            
        Returns:
            Adjusted confidence score, clamped to [0.0, 1.0]
        """
        adjusted = confidence + self.min_confidence_adjustment
        return max(0.0, min(1.0, adjusted))


@dataclass
class LanguageSpecificRules:
    """Language-specific extraction rules and patterns.
    
    Attributes:
        language_code: ISO 639-1 language code
        entity_extraction_patterns: Regex patterns and rules for entity extraction
        relationship_inference_patterns: Patterns for inferring relationships
        abbreviation_patterns: Patterns for detecting abbreviations
        negation_markers: Words/phrases indicating negation in this language
        temporal_markers: Temporal expressions and keywords
        uncertainty_markers: Words indicating uncertainty or conditionality
    """
    language_code: str
    entity_extraction_patterns: List[Dict[str, Any]] = field(default_factory=list)
    relationship_inference_patterns: List[Dict[str, Any]] = field(default_factory=list)
    abbreviation_patterns: List[Tuple[str, str]] = field(default_factory=list)
    negation_markers: List[str] = field(default_factory=list)
    temporal_markers: List[str] = field(default_factory=list)
    uncertainty_markers: List[str] = field(default_factory=list)


@dataclass
class MultilingualExtractionResult:
    """Extraction result with language metadata.
    
    Wraps a standard extraction result and adds language-specific metadata
    for tracking language detection confidence and language-aware processing.
    
    Attributes:
        entities: Extracted entities
        relationships: Extracted relationships
        detected_language: Detected language (Language enum)
        language_confidence: Confidence of language detection (0.0-1.0)
        original_language_code: Original detected language code
        language_processing_notes: Notes from language-specific processing
        confidence_adjustments_applied: Whether confidence adjustments were applied
        extraction_region: Optional text region info if multilingual text was processed
    """
    entities: List[Dict[str, Any]]
    relationships: List[Dict[str, Any]]
    detected_language: str
    language_confidence: float
    original_language_code: str
    language_processing_notes: List[str] = field(default_factory=list)
    confidence_adjustments_applied: bool = False
    extraction_region: Optional[Dict[str, Any]] = None
    
    def to_standard_result(self) -> Dict[str, Any]:
        """Convert to standard extraction result format (without language metadata).
        
        Returns:
            Dict with 'entities' and 'relationships' keys
        """
        return {
            'entities': self.entities,
            'relationships': self.relationships,
            'language_metadata': {
                'detected_language': self.detected_language,
                'language_confidence': self.language_confidence,
                'processing_notes': self.language_processing_notes,
                'confidence_adjustments_applied': self.confidence_adjustments_applied,
            }
        }


class LanguageRouter:
    """Main interface for multi-language support in GraphRAG.
    
    This router provides:
    - Automatic language detection for input text
    - Language-specific configuration and rule selection
    - Domain vocabulary adaptation per language
    - Confidence adjustment for language-specific challenges
    - Multi-language aware extraction result handling
    
    Attributes:
        detector: LanguageDetector instance
        _language_configs: Cache of language-specific configurations
        _logger: Logger instance
        confidence_threshold: Minimum confidence for language detection
    """
    
    def __init__(
        self,
        confidence_threshold: float = 0.6,
        logger: Optional[logging.Logger] = None,
    ):
        """Initialize the language router.
        
        Args:
            confidence_threshold: Minimum confidence for language detection
            logger: Optional logger instance
        """
        if LanguageDetector is None:
            raise ImportError(
                "LanguageDetector not available. Ensure CEC module is installed."
            )
        
        self.detector = LanguageDetector(confidence_threshold=confidence_threshold)
        self.confidence_threshold = confidence_threshold
        self._logger = logger or logging.getLogger(__name__)
        self._language_configs: Dict[str, LanguageConfig] = {}
        self._language_rules: Dict[str, LanguageSpecificRules] = {}
        
        # Initialize default configurations
        self._init_default_configs()
    
    def _init_default_configs(self) -> None:
        """Initialize default language configurations."""
        # English configuration
        self._language_configs['en'] = LanguageConfig(
            language_code='en',
            language_name='English',
            entity_type_keywords={
                'PERSON': ['person', 'individual', 'entity', 'party', 'actor'],
                'ORGANIZATION': ['org', 'company', 'corporation', 'organization', 'entity'],
                'LOCATION': ['place', 'location', 'area', 'region', 'zone'],
                'DOCUMENT': ['document', 'agreement', 'contract', 'provision', 'clause'],
            },
            relationship_type_keywords={
                'obligates': ['require', 'must', 'shall', 'obligate'],
                'permits': ['allow', 'may', 'permit', 'enable'],
                'prohibits': ['forbid', 'prohibit', 'cannot', 'must not'],
                'relates_to': ['relate', 'connect', 'associate', 'link'],
            },
            domain_vocab={
                'legal': ['obligation', 'party', 'agreement', 'contract', 'provision'],
                'medical': ['patient', 'physician', 'diagnosis', 'treatment', 'disease'],
                'financial': ['transaction', 'payment', 'account', 'balance', 'fee'],
            },
            stopwords=['the', 'a', 'an', 'and', 'or', 'is', 'are', 'in', 'to', 'of'],
            min_confidence_adjustment=0.0,
        )
        
        # Spanish configuration
        self._language_configs['es'] = LanguageConfig(
            language_code='es',
            language_name='Spanish',
            entity_type_keywords={
                'PERSON': ['persona', 'individuo', 'entidad', 'parte', 'actor'],
                'ORGANIZATION': ['org', 'empresa', 'corporación', 'organización'],
                'LOCATION': ['lugar', 'ubicación', 'área', 'región', 'zona'],
                'DOCUMENT': ['documento', 'acuerdo', 'contrato', 'disposición', 'cláusula'],
            },
            relationship_type_keywords={
                'obligates': ['requiere', 'debe', 'deberá', 'obligar'],
                'permits': ['permite', 'puede', 'permitir', 'habilitar'],
                'prohibits': ['prohíbe', 'prohibir', 'no puede', 'no podrá'],
                'relates_to': ['relaciona', 'conecta', 'asocia', 'vincula'],
            },
            domain_vocab={
                'legal': ['obligación', 'parte', 'acuerdo', 'contrato', 'disposición'],
                'medical': ['paciente', 'médico', 'diagnóstico', 'tratamiento', 'enfermedad'],
                'financial': ['transacción', 'pago', 'cuenta', 'saldo', 'tarifa'],
            },
            stopwords=['el', 'la', 'un', 'una', 'y', 'o', 'es', 'son', 'en', 'de'],
            min_confidence_adjustment=-0.05,  # Spanish may need slightly lower threshold
        )
        
        # French configuration
        self._language_configs['fr'] = LanguageConfig(
            language_code='fr',
            language_name='French',
            entity_type_keywords={
                'PERSON': ['personne', 'individu', 'entité', 'partie', 'acteur'],
                'ORGANIZATION': ['org', 'entreprise', 'corporation', 'organisation'],
                'LOCATION': ['lieu', 'localisation', 'zone', 'région', 'secteur'],
                'DOCUMENT': ['document', 'accord', 'contrat', 'disposition', 'clause'],
            },
            relationship_type_keywords={
                'obligates': ['requiert', 'doit', 'devra', 'obliger'],
                'permits': ['permet', 'peut', 'autoriser', 'habiliter'],
                'prohibits': ['interdit', 'prohibe', 'ne peut', 'ne pourra'],
                'relates_to': ['relation', 'connecte', 'associe', 'lie'],
            },
            domain_vocab={
                'legal': ['obligation', 'partie', 'accord', 'contrat', 'disposition'],
                'medical': ['patient', 'médecin', 'diagnostic', 'traitement', 'maladie'],
                'financial': ['transaction', 'paiement', 'compte', 'solde', 'frais'],
            },
            stopwords=['le', 'la', 'les', 'un', 'une', 'et', 'ou', 'est', 'sont'],
            min_confidence_adjustment=0.0,
        )
        
        # German configuration
        self._language_configs['de'] = LanguageConfig(
            language_code='de',
            language_name='German',
            entity_type_keywords={
                'PERSON': ['person', 'individuum', 'entität', 'partei', 'akteur'],
                'ORGANIZATION': ['org', 'unternehmen', 'corporation', 'organisation'],
                'LOCATION': ['ort', 'ort', 'zone', 'region', 'sektor'],
                'DOCUMENT': ['dokument', 'vereinbarung', 'vertrag', 'bestimmung', 'klausel'],
            },
            relationship_type_keywords={
                'obligates': ['erfordert', 'muss', 'soll', 'verpflichten'],
                'permits': ['erlaubt', 'darf', 'berechtigt', 'berechtigung'],
                'prohibits': ['verbietet', 'darf nicht', 'kann nicht'],
                'relates_to': ['bezug', 'verbindet', 'assoziiert', 'verbindung'],
            },
            domain_vocab={
                'legal': ['verpflichtung', 'partei', 'vereinbarung', 'vertrag', 'bestimmung'],
                'medical': ['patient', 'arzt', 'diagnose', 'behandlung', 'krankheit'],
                'financial': ['transaktion', 'zahlung', 'konto', 'saldo', 'gebühr'],
            },
            stopwords=['der', 'die', 'das', 'ein', 'eine', 'und', 'oder', 'ist'],
            min_confidence_adjustment=-0.05,  # German compound words can be challenging
        )
        
        self._logger.debug(
            f"Initialized {len(self._language_configs)} default language configs"
        )
    
    def detect_language(self, text: str) -> str:
        """Detect language from text.
        
        Args:
            text: Input text to analyze
            
        Returns:
            ISO 639-1 language code (e.g., 'en', 'es', 'fr', 'de')
        """
        if Language is None:
            self._logger.warning(
                "LanguageDetector not available; defaulting to English"
            )
            return 'en'
        
        language = self.detector.detect(text)
        if language.value == 'unknown':
            self._logger.debug(f"Language detection failed for text; using English")
            return 'en'
        return language.value
    
    def detect_language_with_confidence(
        self, text: str
    ) -> Tuple[str, float]:
        """Detect language with confidence score.
        
        Args:
            text: Input text to analyze
            
        Returns:
            Tuple of (language_code, confidence_score)
        """
        if Language is None:
            return 'en', 1.0
        
        language, confidence = self.detector.detect_with_confidence(text)
        return language.value, confidence
    
    def get_language_config(self, language_code: str) -> LanguageConfig:
        """Get language-specific configuration.
        
        Args:
            language_code: ISO 639-1 language code
            
        Returns:
            LanguageConfig for the specified language, or English as fallback
        """
        if language_code in self._language_configs:
            return self._language_configs[language_code]
        
        self._logger.warning(
            f"Language config for '{language_code}' not found; using English"
        )
        return self._language_configs['en']
    
    def get_language_rules(self, language_code: str) -> LanguageSpecificRules:
        """Get language-specific extraction rules.
        
        Args:
            language_code: ISO 639-1 language code
            
        Returns:
            LanguageSpecificRules for the specified language
        """
        if language_code in self._language_rules:
            return self._language_rules[language_code]
        
        # Return default (empty) rules if not configured
        return LanguageSpecificRules(language_code=language_code)
    
    def register_language_config(
        self,
        language_code: str,
        config: LanguageConfig
    ) -> None:
        """Register or update language configuration.
        
        Args:
            language_code: ISO 639-1 language code
            config: LanguageConfig instance
        """
        self._language_configs[language_code] = config
        self._logger.debug(f"Registered language config for '{language_code}'")
    
    def register_language_rules(
        self,
        language_code: str,
        rules: LanguageSpecificRules
    ) -> None:
        """Register or update language-specific extraction rules.
        
        Args:
            language_code: ISO 639-1 language code
            rules: LanguageSpecificRules instance
        """
        self._language_rules[language_code] = rules
        self._logger.debug(f"Registered language rules for '{language_code}'")
    
    def get_supported_languages(self) -> List[str]:
        """Get list of configured language codes.
        
        Returns:
            List of ISO 639-1 language codes
        """
        return list(self._language_configs.keys())
    
    def extract_with_language_awareness(
        self,
        text: str,
        extractor_func,
        apply_confidence_adjustment: bool = True,
    ) -> MultilingualExtractionResult:
        """Execute extraction with language awareness.
        
        This method detects the input language, applies language-specific
        configuration, executes extraction, and returns result with language metadata.
        
        Args:
            text: Input text to extract from
            extractor_func: Callable that performs extraction (receives text, config)
            apply_confidence_adjustment: Whether to apply language-specific adjustments
            
        Returns:
            MultilingualExtractionResult with language metadata
        """
        # Detect language
        language_code, language_confidence = self.detect_language_with_confidence(text)
        config = self.get_language_config(language_code)
        
        # Execute extraction with language config
        entities, relationships = extractor_func(text, config)
        
        # Apply confidence adjustments if needed
        notes = []
        adjustments_applied = False
        if apply_confidence_adjustment and config.min_confidence_adjustment != 0.0:
            adjusted_entities = []
            for entity in entities:
                entity_copy = entity.copy()
                if 'confidence' in entity_copy:
                    original_conf = entity_copy['confidence']
                    entity_copy['confidence'] = config.apply_confidence_adjustment(
                        entity_copy['confidence']
                    )
                    if entity_copy['confidence'] != original_conf:
                        adjustments_applied = True
                        notes.append(
                            f"Confidence adjusted for {language_code}: "
                            f"{original_conf:.2f} → {entity_copy['confidence']:.2f}"
                        )
                adjusted_entities.append(entity_copy)
            entities = adjusted_entities
        
        return MultilingualExtractionResult(
            entities=entities,
            relationships=relationships,
            detected_language=config.language_name,
            language_confidence=language_confidence,
            original_language_code=language_code,
            language_processing_notes=notes,
            confidence_adjustments_applied=adjustments_applied,
        )
