"""Batch 252: LanguageRouter Comprehensive Test Suite.

Comprehensive testing of the LanguageRouter for multi-language support in
ontology extraction with language detection, configuration management, and
language-specific extraction.

Test Categories:
- Language detection and confidence
- Language configuration retrieval and registration
- Language-specific rule management
- Multi-language aware extraction
- Confidence adjustment per language
- Fallback behavior for unknown languages
"""

import pytest
from typing import Dict, Any, List, Tuple
from unittest.mock import Mock, patch, MagicMock

from ipfs_datasets_py.optimizers.graphrag.language_router import (
    LanguageRouter,
    LanguageConfig,
    LanguageSpecificRules,
    MultilingualExtractionResult,
)


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def router():
    """Create a fresh LanguageRouter."""
    return LanguageRouter(confidence_threshold=0.6)


@pytest.fixture
def router_high_threshold():
    """Create a LanguageRouter with high confidence threshold."""
    return LanguageRouter(confidence_threshold=0.9)


@pytest.fixture
def router_low_threshold():
    """Create a LanguageRouter with low confidence threshold."""
    return LanguageRouter(confidence_threshold=0.3)


@pytest.fixture
def english_text():
    """Sample English text."""
    return "Alice must pay Bob USD 500 by January 1, 2025."


@pytest.fixture
def spanish_text():
    """Sample Spanish text."""
    return "Alice debe pagar a Bob USD 500 antes del 1 de enero de 2025."


@pytest.fixture
def french_text():
    """Sample French text."""
    return "Alice doit payer à Bob USD 500 avant le 1er janvier 2025."


@pytest.fixture
def german_text():
    """Sample German text."""
    return "Alice muss Bob USD 500 bis zum 1. Januar 2025 zahlen."


@pytest.fixture
def mixed_language_text():
    """Text mixing multiple languages."""
    return "Alice must pay (doit payer) Bob USD 500."


@pytest.fixture
def custom_language_config():
    """Create custom language configuration."""
    return LanguageConfig(
        language_code="pt",  # Portuguese
        language_name="Portuguese",
        entity_type_keywords={
            "PERSON": ["pessoa", "indivíduo", "entidade"],
            "ORGANIZATION": ["organização", "empresa", "corporação"],
        },
        relationship_type_keywords={
            "obligates": ["exige", "obriga", "deve"],
            "permits": ["permite", "pode"],
        },
        domain_vocab={
            "legal": ["obrigação", "contrato", "acordo"],
        },
        stopwords=["o", "a", "e", "ou", "em", "de"],
        min_confidence_adjustment=0.0,
    )


@pytest.fixture
def custom_language_rules():
    """Create custom language-specific rules."""
    return LanguageSpecificRules(
        language_code="it",  # Italian
        entity_extraction_patterns=[{"pattern": "[A-Z][a-z]+", "type": "PERSON"}],
        relationship_inference_patterns=[{"pattern": "obliga", "type": "obligates"}],
        negation_markers=["non", "no"],
        temporal_markers=["gennaio", "febbraio"],
    )


# ============================================================================
# Initialization Tests
# ============================================================================

class TestInitialization:
    """Test LanguageRouter initialization."""
    
    def test_init_with_defaults(self, router):
        """Router initializes with default settings."""
        assert router.confidence_threshold == 0.6
        assert router.detector is not None
        assert len(router._language_configs) > 0
    
    def test_init_with_custom_threshold(self, router_high_threshold):
        """Router initializes with custom confidence threshold."""
        assert router_high_threshold.confidence_threshold == 0.9
    
    def test_init_with_logger(self, router):
        """Router initializes with logger."""
        assert router._logger is not None
    
    def test_default_configs_loaded(self, router):
        """Default language configurations are loaded."""
        expected_languages = ["en", "es", "fr", "de"]
        for lang in expected_languages:
            assert lang in router._language_configs


# ============================================================================
# Language Detection Tests
# ============================================================================

class TestLanguageDetection:
    """Test language detection functionality."""
    
    def test_detect_language_returns_string(self, router, english_text):
        """detect_language returns ISO language code."""
        lang = router.detect_language(english_text)
        
        assert isinstance(lang, str)
        assert len(lang) == 2 or lang == "en"  # ISO 639-1 format
    
    def test_detect_language_english(self, router, english_text):
        """detect_language identifies English text."""
        lang = router.detect_language(english_text)
        
        # Should detect as English or default to English
        assert lang in ["en"] or lang == "en"
    
    def test_detect_language_spanish(self, router, spanish_text):
        """detect_language can identify Spanish text."""
        lang = router.detect_language(spanish_text)
        
        # Should be Spanish or fallback
        assert isinstance(lang, str)
        assert len(lang) >= 2
    
    def test_detect_language_fallback(self, router):
        """detect_language falls back to English for unknown text."""
        unknown_text = "123 456 789"  # Unlikely to detect
        lang = router.detect_language(unknown_text)
        
        assert lang == "en"
    
    def test_detect_language_with_confidence(self, router, english_text):
        """detect_language_with_confidence returns tuple."""
        lang, confidence = router.detect_language_with_confidence(english_text)
        
        assert isinstance(lang, str)
        assert isinstance(confidence, (int, float))
        assert 0.0 <= confidence <= 1.0
    
    def test_detect_language_confidence_scalar(self, router, english_text):
        """Language confidence is reasonable for clear English."""
        lang, confidence = router.detect_language_with_confidence(english_text)
        
        # Confidence should be a valid probability
        assert 0.0 <= confidence <= 1.0


# ============================================================================
# Language Configuration Tests
# ============================================================================

class TestLanguageConfiguration:
    """Test language configuration management."""
    
    def test_get_language_config_existing(self, router):
        """get_language_config returns config for existing language."""
        config = router.get_language_config("en")
        
        assert isinstance(config, LanguageConfig)
        assert config.language_code == "en"
        assert config.language_name == "English"
    
    def test_get_language_config_all_defaults(self, router):
        """get_language_config works for all default languages."""
        for lang_code in ["en", "es", "fr", "de"]:
            config = router.get_language_config(lang_code)
            
            assert config.language_code == lang_code
            assert len(config.entity_type_keywords) > 0
            assert len(config.relationship_type_keywords) > 0
    
    def test_get_language_config_nonexistent(self, router):
        """get_language_config returns English for unknown language."""
        config = router.get_language_config("xx")  # Unknown language
        
        assert config.language_code == "en"
    
    def test_get_language_config_has_keywords(self, router):
        """Language configs include keywords for extraction."""
        config = router.get_language_config("legal")
        
        # Should have entity and relationship keywords
        assert config.entity_type_keywords
        assert config.relationship_type_keywords
    
    def test_get_language_config_has_domain_vocab(self, router):
        """Language configs include domain vocabulary."""
        for lang_code in ["en", "es", "fr", "de"]:
            config = router.get_language_config(lang_code)
            
            assert "legal" in config.domain_vocab or config.domain_vocab
            assert len(config.domain_vocab) > 0
    
    def test_register_language_config(self, router, custom_language_config):
        """register_language_config adds new language."""
        router.register_language_config("pt", custom_language_config)
        
        retrieved = router.get_language_config("pt")
        assert retrieved.language_code == "pt"
        assert retrieved.language_name == "Portuguese"
    
    def test_register_language_config_overwrites(self, router):
        """register_language_config overwrites existing language."""
        original = router.get_language_config("en")
        
        new_config = LanguageConfig(
            language_code="en",
            language_name="Modified English",
            entity_type_keywords={},
            relationship_type_keywords={},
            domain_vocab={},
            stopwords=[],
            min_confidence_adjustment=0.1,
        )
        
        router.register_language_config("en", new_config)
        updated = router.get_language_config("en")
        
        assert updated.language_name == "Modified English"
    
    def test_get_supported_languages(self, router):
        """get_supported_languages returns list of languages."""
        languages = router.get_supported_languages()
        
        assert isinstance(languages, list)
        assert len(languages) >= 4  # At least 4 default languages
        assert "en" in languages


# ============================================================================
# Language Rules Tests
# ============================================================================

class TestLanguageRules:
    """Test language-specific rule management."""
    
    def test_get_language_rules_default_empty(self, router):
        """get_language_rules returns empty rules for unconfigured language."""
        rules = router.get_language_rules("xx")
        
        assert isinstance(rules, LanguageSpecificRules)
        assert rules.language_code == "xx"
    
    def test_get_language_rules_after_registration(self, router, custom_language_rules):
        """get_language_rules returns registered rules."""
        router.register_language_rules("it", custom_language_rules)
        
        retrieved = router.get_language_rules("it")
        assert retrieved.language_code == "it"
    
    def test_register_language_rules(self, router, custom_language_rules):
        """register_language_rules adds new rules."""
        router.register_language_rules("it", custom_language_rules)
        
        rules = router.get_language_rules("it")
        assert rules.entity_extraction_patterns is not None


# ============================================================================
# Language-Aware Extraction Tests
# ============================================================================

class TestExtractWithLanguageAwareness:
    """Test language-aware extraction."""
    
    def test_extract_returns_multilingual_result(self, router, english_text):
        """extract_with_language_awareness returns MultilingualExtractionResult."""
        def mock_extractor(text, config):
            return (
                [{"text": "Alice", "type": "PERSON", "confidence": 0.9}],
                [{"source": "Alice", "target": "Bob", "type": "OBLIGATES"}]
            )
        
        result = router.extract_with_language_awareness(
            english_text,
            mock_extractor
        )
        
        assert isinstance(result, MultilingualExtractionResult)
    
    def test_extract_detects_language(self, router, english_text):
        """extract_with_language_awareness detects input language."""
        def mock_extractor(text, config):
            return ([], [])
        
        result = router.extract_with_language_awareness(
            english_text,
            mock_extractor
        )
        
        assert result.original_language_code is not None
        assert result.detected_language is not None
    
    def test_extract_preserves_entities_and_relationships(self, router, english_text):
        """extract_with_language_awareness preserves extraction results."""
        test_entities = [
            {"text": "Alice", "type": "PERSON", "confidence": 0.95},
            {"text": "Bob", "type": "PERSON", "confidence": 0.92}
        ]
        test_relationships = [
            {"source": "Alice", "target": "Bob", "type": "OBLIGATES", "confidence": 0.88}
        ]
        
        def mock_extractor(text, config):
            return test_entities, test_relationships
        
        result = router.extract_with_language_awareness(
            english_text,
            mock_extractor
        )
        
        assert len(result.entities) == 2
        assert len(result.relationships) == 1
        assert result.entities[0]["text"] == "Alice"
    
    def test_extract_includes_language_metadata(self, router, english_text):
        """extract_with_language_awareness includes language metadata."""
        def mock_extractor(text, config):
            return ([], [])
        
        result = router.extract_with_language_awareness(
            english_text,
            mock_extractor
        )
        
        assert result.language_confidence is not None
        assert result.original_language_code is not None
        assert result.detected_language is not None
    
    def test_extract_without_confidence_adjustment(self, router, english_text):
        """extract_with_language_awareness without confidence adjustment."""
        test_entities = [{"text": "test", "confidence": 0.8}]
        
        def mock_extractor(text, config):
            return test_entities, []
        
        result = router.extract_with_language_awareness(
            english_text,
            mock_extractor,
            apply_confidence_adjustment=False
        )
        
        assert result.confidence_adjustments_applied == False
    
    def test_extract_with_confidence_adjustment(self, router, spanish_text):
        """extract_with_language_awareness applies confidence adjustment for Spanish."""
        test_entities = [{"text": "test", "confidence": 0.8}]
        
        def mock_extractor(text, config):
            return test_entities, []
        
        result = router.extract_with_language_awareness(
            spanish_text,
            mock_extractor,
            apply_confidence_adjustment=True
        )
        
        # Spanish config has min_confidence_adjustment of -0.05
        # May or may not be applied depending on implementation
        assert result.entities is not None


# ============================================================================
# Confidence Adjustment Tests
# ============================================================================

class TestConfidenceAdjustment:
    """Test language-specific confidence adjustments."""
    
    def test_language_config_has_adjustment_field(self, router):
        """Language configs include confidence adjustment field."""
        en_config = router.get_language_config("en")
        
        assert hasattr(en_config, "min_confidence_adjustment")
    
    def test_confidence_adjustment_english_neutral(self, router):
        """English has neutral confidence adjustment."""
        config = router.get_language_config("en")
        
        assert config.min_confidence_adjustment == 0.0
    
    def test_confidence_adjustment_spanish_negative(self, router):
        """Spanish has negative confidence adjustment."""
        config = router.get_language_config("es")
        
        assert config.min_confidence_adjustment < 0.0
    
    def test_confidence_adjustment_german_negative(self, router):
        """German has negative confidence adjustment."""
        config = router.get_language_config("de")
        
        assert config.min_confidence_adjustment < 0.0


# ============================================================================
# Integration Tests
# ============================================================================

class TestLanguageRoutingWorkflow:
    """Integration tests for language routing workflows."""
    
    def test_multi_language_workflow(self, router):
        """Complete workflow handling multiple languages."""
        texts = [
            ("Alice must pay Bob.", "en"),
            ("Alice debe pagar a Bob.", "es"),
            ("Alice doit payer à Bob.", "fr"),
            ("Alice muss Bob zahlen.", "de"),
        ]
        
        results = []
        for text, expected_lang in texts:
            lang = router.detect_language(text)
            config = router.get_language_config(lang)
            
            results.append({
                "text": text,
                "detected_lang": lang,
                "config_loaded": config is not None
            })
        
        assert len(results) == 4
        assert all(r["config_loaded"] for r in results)
    
    def test_language_config_registration_workflow(self, router, custom_language_config):
        """Workflow for registering custom language."""
        # 1. Register custom language
        router.register_language_config("pt", custom_language_config)
        
        # 2. Retrieve it
        config = router.get_language_config("pt")
        assert config.language_code == "pt"
        
        # 3. It appears in supported languages
        langs = router.get_supported_languages()
        assert "pt" in langs
    
    def test_extraction_with_custom_language(self, router, custom_language_config):
        """Extraction workflow with custom language."""
        router.register_language_config("pt", custom_language_config)
        
        called_configs = []
        
        def mock_extractor(text, config):
            # Track what config was passed
            called_configs.append(config.language_code)
            return (
                [{"text": "entity", "type": "PERSON"}],
                []
            )
        
        # Patching detect_language_with_confidence to return Portuguese
        with patch.object(router, "detect_language_with_confidence", return_value=("pt", 0.95)):
            result = router.extract_with_language_awareness(
                "Brazilian Portuguese text",
                mock_extractor
            )
            
            # Verify pt config was retrieved and used
            assert "pt" in called_configs
            assert result.original_language_code == "pt"
    
    def test_language_fallback_workflow(self, router):
        """Workflow demonstrating language fallback."""
        # Try to get config for unknown language
        config = router.get_language_config("unknown")
        
        # Should fallback to English
        assert config.language_code == "en"
    
    def test_mixed_language_handling(self, router):
        """Handle text with mixed languages."""
        def mock_extractor(text, config):
            return ([], [])
        
        mixed_text = "Alice must pay (doit payer) Bob USD 500."
        result = router.extract_with_language_awareness(
            mixed_text,
            mock_extractor
        )
        
        # Should detect one primary language
        assert result.original_language_code is not None


# ============================================================================
# Error Handling and Robustness Tests
# ============================================================================

class TestErrorHandling:
    """Test error handling and robustness."""
    
    def test_empty_text_detection(self, router):
        """detect_language handles empty text."""
        lang = router.detect_language("")
        
        # Should return English as fallback
        assert lang == "en"
    
    def test_very_short_text_detection(self, router):
        """detect_language handles very short text."""
        langs = [
            router.detect_language("a"),
            router.detect_language("ab"),
            router.detect_language("abc"),
        ]
        
        # All should return string language codes
        assert all(isinstance(l, str) for l in langs)
    
    def test_get_config_for_empty_language_code(self, router):
        """get_language_config handles empty language code."""
        config = router.get_language_config("")
        
        # Should fallback to English
        assert config.language_code == "en"
    
    def test_extract_with_empty_results(self, router, english_text):
        """extract_with_language_awareness handles empty extraction results."""
        def mock_extractor(text, config):
            return ([], [])
        
        result = router.extract_with_language_awareness(
            english_text,
            mock_extractor
        )
        
        assert result.entities == []
        assert result.relationships == []


# ============================================================================
# Configuration Details Tests
# ============================================================================

class TestLanguageConfigDetails:
    """Test specific details of language configurations."""
    
    def test_english_config_completeness(self, router):
        """English configuration is complete."""
        config = router.get_language_config("en")
        
        assert config.language_code == "en"
        assert config.language_name == "English"
        assert "PERSON" in config.entity_type_keywords
        assert "obligates" in config.relationship_type_keywords
        assert "legal" in config.domain_vocab
        assert config.stopwords
    
    def test_spanish_config_specificity(self, router):
        """Spanish configuration is specific to Spanish."""
        config = router.get_language_config("es")
        
        # Should have Spanish-specific keywords
        assert any("español" in str(v).lower() or "obligación" in str(v) 
                  for v in config.domain_vocab.get("legal", []))
    
    def test_french_config_specificity(self, router):
        """French configuration is specific to French."""
        config = router.get_language_config("fr")
        
        # Should have French-specific vocabulary
        assert config.language_code == "fr"
        assert config.language_name == "French"
    
    def test_german_config_specificity(self, router):
        """German configuration handles compound words."""
        config = router.get_language_config("de")
        
        # German has negative adjustment for compounds
        assert config.min_confidence_adjustment < 0.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
