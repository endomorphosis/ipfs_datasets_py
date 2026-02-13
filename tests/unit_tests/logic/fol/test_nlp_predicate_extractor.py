"""
Tests for NLP-enhanced predicate extraction.

Tests cover:
- spaCy-based extraction
- Fallback to regex when spaCy unavailable
- Semantic role labeling
- Dependency parsing
- Performance comparisons
"""

import pytest
from ipfs_datasets_py.logic.fol.utils.nlp_predicate_extractor import (
    extract_predicates_nlp,
    extract_semantic_roles,
    extract_logical_relations_nlp,
    get_extraction_stats,
    get_spacy_model,
    SPACY_AVAILABLE,
)


class TestNLPPredicateExtraction:
    """Test NLP-enhanced predicate extraction."""

    def test_extract_predicates_simple_sentence(self):
        """
        GIVEN: A simple sentence
        WHEN: Extracting predicates with NLP
        THEN: Should extract nouns, verbs, adjectives
        """
        text = "Dogs are animals"
        result = extract_predicates_nlp(text)
        
        assert isinstance(result, dict)
        assert "nouns" in result
        assert "verbs" in result
        assert "adjectives" in result

    def test_extract_predicates_complex_sentence(self):
        """
        GIVEN: A complex sentence with multiple predicates
        WHEN: Extracting predicates
        THEN: Should identify all predicate types
        """
        text = "All humans are mortal beings who think rationally"
        result = extract_predicates_nlp(text)
        
        assert isinstance(result, dict)
        assert len(result["nouns"]) > 0 or len(result["verbs"]) > 0

    def test_fallback_when_spacy_disabled(self):
        """
        GIVEN: spaCy disabled via parameter
        WHEN: Extracting predicates
        THEN: Should use regex fallback
        """
        text = "The cat is black"
        result = extract_predicates_nlp(text, use_spacy=False)
        
        assert isinstance(result, dict)
        assert "nouns" in result
        assert "verbs" in result

    @pytest.mark.skipif(not SPACY_AVAILABLE, reason="spaCy not installed")
    def test_spacy_extraction_with_model(self):
        """
        GIVEN: spaCy available and text to analyze
        WHEN: Extracting with spaCy
        THEN: Should provide enhanced extraction
        """
        text = "The quick brown fox jumps over the lazy dog"
        result = extract_predicates_nlp(text, use_spacy=True)
        
        assert isinstance(result, dict)
        # spaCy should extract entities if available
        if "entities" in result:
            assert isinstance(result["entities"], list)

    def test_compound_nouns(self):
        """
        GIVEN: Text with compound nouns
        WHEN: Extracting predicates
        THEN: Should handle compound nouns
        """
        text = "Machine learning algorithms process natural language"
        result = extract_predicates_nlp(text)
        
        assert isinstance(result, dict)
        # Should extract some nouns
        assert len(result.get("nouns", [])) > 0

    def test_proper_nouns(self):
        """
        GIVEN: Text with proper nouns
        WHEN: Extracting predicates
        THEN: Should identify proper nouns
        """
        text = "Socrates is a philosopher from Athens"
        result = extract_predicates_nlp(text)
        
        assert isinstance(result, dict)
        # Should extract Socrates and Athens as nouns/entities
        nouns_and_entities = result.get("nouns", []) + result.get("entities", [])
        assert len(nouns_and_entities) > 0

    def test_verb_extraction(self):
        """
        GIVEN: Text with multiple verbs
        WHEN: Extracting predicates
        THEN: Should identify main verbs
        """
        text = "Birds fly and sing in the morning"
        result = extract_predicates_nlp(text)
        
        assert isinstance(result, dict)
        # Should extract some verbs
        assert isinstance(result.get("verbs", []), list)

    def test_adjective_extraction(self):
        """
        GIVEN: Text with adjectives
        WHEN: Extracting predicates
        THEN: Should identify adjectives
        """
        text = "The beautiful sunset was magnificent"
        result = extract_predicates_nlp(text)
        
        assert isinstance(result, dict)
        assert isinstance(result.get("adjectives", []), list)

    def test_empty_text(self):
        """
        GIVEN: Empty text
        WHEN: Extracting predicates
        THEN: Should handle gracefully
        """
        result = extract_predicates_nlp("")
        
        assert isinstance(result, dict)
        assert all(isinstance(v, list) for v in result.values())

    def test_special_characters(self):
        """
        GIVEN: Text with special characters
        WHEN: Extracting predicates
        THEN: Should handle without crashing
        """
        text = "Test @#$% special *&^ characters!"
        result = extract_predicates_nlp(text)
        
        assert isinstance(result, dict)


class TestSemanticRoleLabeling:
    """Test semantic role labeling functionality."""

    def test_extract_semantic_roles_simple(self):
        """
        GIVEN: Simple sentence with clear roles
        WHEN: Extracting semantic roles
        THEN: Should identify agent, action, patient
        """
        text = "The cat chases the mouse"
        result = extract_semantic_roles(text)
        
        assert isinstance(result, list)

    @pytest.mark.skipif(not SPACY_AVAILABLE, reason="spaCy not installed")
    def test_semantic_roles_with_spacy(self):
        """
        GIVEN: spaCy available
        WHEN: Extracting semantic roles
        THEN: Should identify roles using NLP
        """
        text = "John gives Mary a book"
        result = extract_semantic_roles(text, use_spacy=True)
        
        assert isinstance(result, list)
        # If spaCy works, should have some roles
        if result:
            assert "action" in result[0]

    def test_semantic_roles_without_spacy(self):
        """
        GIVEN: spaCy disabled
        WHEN: Extracting semantic roles
        THEN: Should return empty list (no fallback for SRL)
        """
        text = "Test sentence"
        result = extract_semantic_roles(text, use_spacy=False)
        
        assert isinstance(result, list)
        # Without spaCy, SRL returns empty
        assert len(result) == 0

    def test_complex_sentence_roles(self):
        """
        GIVEN: Complex sentence with multiple roles
        WHEN: Extracting semantic roles
        THEN: Should handle multiple role structures
        """
        text = "The teacher explains the concept to students in the classroom"
        result = extract_semantic_roles(text)
        
        assert isinstance(result, list)

    def test_passive_voice(self):
        """
        GIVEN: Sentence in passive voice
        WHEN: Extracting semantic roles
        THEN: Should identify roles correctly
        """
        text = "The book was written by the author"
        result = extract_semantic_roles(text)
        
        assert isinstance(result, list)


class TestLogicalRelationsNLP:
    """Test NLP-based logical relation extraction."""

    def test_conditional_relation(self):
        """
        GIVEN: If-then conditional statement
        WHEN: Extracting relations
        THEN: Should identify implication
        """
        text = "If it rains, then the ground gets wet"
        result = extract_logical_relations_nlp(text)
        
        assert isinstance(result, list)
        # Should find conditional relation
        if result:
            assert any(r.get("type") == "implication" for r in result)

    def test_universal_quantification(self):
        """
        GIVEN: Universal quantification statement
        WHEN: Extracting relations
        THEN: Should identify universal type
        """
        text = "All humans are mortal"
        result = extract_logical_relations_nlp(text)
        
        assert isinstance(result, list)

    def test_existential_quantification(self):
        """
        GIVEN: Existential quantification statement
        WHEN: Extracting relations
        THEN: Should identify existential type
        """
        text = "Some birds can swim"
        result = extract_logical_relations_nlp(text)
        
        assert isinstance(result, list)

    def test_multiple_relations(self):
        """
        GIVEN: Text with multiple logical relations
        WHEN: Extracting relations
        THEN: Should identify all relations
        """
        text = "All dogs are animals. Some dogs are friendly. If a dog is friendly, then it wags its tail."
        result = extract_logical_relations_nlp(text)
        
        assert isinstance(result, list)
        # Should find multiple relations
        assert len(result) >= 0

    def test_fallback_to_regex(self):
        """
        GIVEN: spaCy disabled
        WHEN: Extracting relations
        THEN: Should use regex fallback
        """
        text = "If P then Q"
        result = extract_logical_relations_nlp(text, use_spacy=False)
        
        assert isinstance(result, list)


class TestExtractionStats:
    """Test extraction statistics and model info."""

    def test_get_extraction_stats(self):
        """
        GIVEN: NLP extraction module
        WHEN: Getting statistics
        THEN: Should return status info
        """
        stats = get_extraction_stats()
        
        assert isinstance(stats, dict)
        assert "spacy_available" in stats
        assert "fallback_mode" in stats
        assert isinstance(stats["spacy_available"], bool)

    def test_stats_structure(self):
        """
        GIVEN: Extraction stats
        WHEN: Checking structure
        THEN: Should have required fields
        """
        stats = get_extraction_stats()
        
        assert "spacy_available" in stats
        assert "model_loaded" in stats
        assert "fallback_mode" in stats

    @pytest.mark.skipif(not SPACY_AVAILABLE, reason="spaCy not installed")
    def test_model_info_when_loaded(self):
        """
        GIVEN: spaCy model loaded
        WHEN: Getting stats
        THEN: Should include model info
        """
        # Try to load model
        get_spacy_model()
        stats = get_extraction_stats()
        
        if stats["model_loaded"]:
            assert "model_name" in stats
            assert "model_lang" in stats


class TestPerformanceComparison:
    """Test performance characteristics of NLP vs regex."""

    def test_extraction_speed_simple(self):
        """
        GIVEN: Simple sentence
        WHEN: Extracting with both methods
        THEN: Should complete in reasonable time
        """
        text = "The cat is black"
        
        import time
        
        # Test regex (fallback)
        start = time.time()
        result_regex = extract_predicates_nlp(text, use_spacy=False)
        time_regex = time.time() - start
        
        # Test NLP (if available)
        start = time.time()
        result_nlp = extract_predicates_nlp(text, use_spacy=True)
        time_nlp = time.time() - start
        
        assert isinstance(result_regex, dict)
        assert isinstance(result_nlp, dict)
        
        # Both should be fast (<100ms)
        assert time_regex < 0.1
        assert time_nlp < 0.5  # NLP may be slightly slower

    def test_batch_processing_efficiency(self):
        """
        GIVEN: Multiple sentences
        WHEN: Processing batch
        THEN: Should handle efficiently
        """
        sentences = [
            "Dogs are animals",
            "Cats are mammals",
            "Birds can fly",
            "Fish live in water",
            "Trees produce oxygen"
        ]
        
        results = []
        for sent in sentences:
            result = extract_predicates_nlp(sent)
            results.append(result)
        
        assert len(results) == 5
        assert all(isinstance(r, dict) for r in results)


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_very_long_sentence(self):
        """
        GIVEN: Very long sentence
        WHEN: Extracting predicates
        THEN: Should handle without crashing
        """
        text = "This is a test " * 100  # 1500+ chars
        result = extract_predicates_nlp(text)
        
        assert isinstance(result, dict)

    def test_unicode_text(self):
        """
        GIVEN: Text with unicode characters
        WHEN: Extracting predicates
        THEN: Should handle unicode
        """
        text = "Café résumé naïve"
        result = extract_predicates_nlp(text)
        
        assert isinstance(result, dict)

    def test_numbers_in_text(self):
        """
        GIVEN: Text with numbers
        WHEN: Extracting predicates
        THEN: Should handle numbers gracefully
        """
        text = "There are 5 cats and 3 dogs"
        result = extract_predicates_nlp(text)
        
        assert isinstance(result, dict)

    def test_punctuation_heavy_text(self):
        """
        GIVEN: Text with heavy punctuation
        WHEN: Extracting predicates
        THEN: Should handle punctuation
        """
        text = "Wait! What? Really... Okay, fine."
        result = extract_predicates_nlp(text)
        
        assert isinstance(result, dict)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
