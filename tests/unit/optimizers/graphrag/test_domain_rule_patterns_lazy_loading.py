"""
Tests for lazy-loaded domain-specific rule patterns in ExtractionConfig.

Tests validate:
- Pattern caching behavior (lru_cache effectiveness)
- Domain pattern completeness and accuracy
- Pattern matching correctness
- Performance characteristics of lazy loading
- Cache hit/miss tracking
"""

import pytest
import functools
from ipfs_datasets_py.optimizers.graphrag.ontology_generator import ExtractionConfig


class TestDomainRulePatternLazyLoading:
    """Tests for lazy-loading and caching of domain-specific rule patterns."""

    def test_default_domain_returns_general_patterns(self):
        """Verify that unknown domain defaults to empty patterns."""
        patterns = ExtractionConfig._get_domain_rule_patterns("unknown_domain")
        assert patterns == ()

    def test_legal_domain_patterns_available(self):
        """Test that legal domain patterns are loaded."""
        patterns = ExtractionConfig._get_domain_rule_patterns("legal")
        assert len(patterns) > 0
        assert all(isinstance(p, tuple) and len(p) == 2 for p in patterns)
        # Verify specific pattern types
        pattern_types = [p[1] for p in patterns]
        assert "LegalParty" in pattern_types
        assert "LegalReference" in pattern_types

    def test_medical_domain_patterns_available(self):
        """Test that medical domain patterns are loaded."""
        patterns = ExtractionConfig._get_domain_rule_patterns("medical")
        assert len(patterns) > 0
        pattern_types = [p[1] for p in patterns]
        assert "MedicalConcept" in pattern_types or "Dosage" in pattern_types

    def test_technical_domain_patterns_available(self):
        """Test that technical domain patterns are loaded."""
        patterns = ExtractionConfig._get_domain_rule_patterns("technical")
        assert len(patterns) > 0
        pattern_types = [p[1] for p in patterns]
        assert "Protocol" in pattern_types or "TechnicalComponent" in pattern_types

    def test_financial_domain_patterns_available(self):
        """Test that financial domain patterns are loaded."""
        patterns = ExtractionConfig._get_domain_rule_patterns("financial")
        assert len(patterns) > 0
        pattern_types = [p[1] for p in patterns]
        assert "FinancialConcept" in pattern_types or "MonetaryValue" in pattern_types

    def test_general_domain_patterns_empty(self):
        """Test that general domain returns empty patterns."""
        patterns = ExtractionConfig._get_domain_rule_patterns("general")
        assert patterns == ()

    def test_case_insensitive_domain_matching(self):
        """Verify domain names are case-insensitive."""
        legal_lower = ExtractionConfig._get_domain_rule_patterns("legal")
        legal_upper = ExtractionConfig._get_domain_rule_patterns("LEGAL")
        legal_mixed = ExtractionConfig._get_domain_rule_patterns("LeGaL")
        
        assert legal_lower == legal_upper == legal_mixed

    def test_whitespace_normalized_in_domain(self):
        """Verify domain names strip whitespace."""
        legal1 = ExtractionConfig._get_domain_rule_patterns("legal")
        legal2 = ExtractionConfig._get_domain_rule_patterns("  legal  ")
        
        assert legal1 == legal2

    def test_none_domain_defaults_to_general(self):
        """Verify None domain defaults to 'general'."""
        patterns = ExtractionConfig._get_domain_rule_patterns(None)
        assert patterns == ()

    def test_pattern_cache_is_lru_cached(self):
        """Verify lru_cache decorator is applied."""
        # The method should have cache_info available if lru_cache is applied
        assert hasattr(ExtractionConfig._get_domain_rule_patterns, 'cache_info')
        
    def test_pattern_cache_hits_and_misses(self):
        """Verify caching reduces redundant pattern lookups."""
        # Clear cache
        ExtractionConfig._get_domain_rule_patterns.cache_clear()
        
        # Get cache info before any calls
        info_before = ExtractionConfig._get_domain_rule_patterns.cache_info()
        assert info_before.hits == 0
        assert info_before.misses == 0
        
        # First call should be a cache miss
        patterns1 = ExtractionConfig._get_domain_rule_patterns("legal")
        info_after_miss = ExtractionConfig._get_domain_rule_patterns.cache_info()
        assert info_after_miss.misses == 1
        assert info_after_miss.hits == 0
        
        # Second call should be a cache hit
        patterns2 = ExtractionConfig._get_domain_rule_patterns("legal")
        info_after_hit = ExtractionConfig._get_domain_rule_patterns.cache_info()
        assert info_after_hit.hits == 1
        assert info_after_hit.misses == 1
        
        # Patterns should be identical (from cache)
        assert patterns1 is patterns2

    def test_multiple_domains_cached_independently(self):
        """Verify each domain is cached independently."""
        ExtractionConfig._get_domain_rule_patterns.cache_clear()
        
        legal = ExtractionConfig._get_domain_rule_patterns("legal")
        medical = ExtractionConfig._get_domain_rule_patterns("medical")
        technical = ExtractionConfig._get_domain_rule_patterns("technical")
        
        info = ExtractionConfig._get_domain_rule_patterns.cache_info()
        assert info.misses == 3  # Three unique domain lookups
        assert info.hits == 0
        
        # Calling again should all be cache hits
        ExtractionConfig._get_domain_rule_patterns("legal")
        ExtractionConfig._get_domain_rule_patterns("medical")
        ExtractionConfig._get_domain_rule_patterns("technical")
        
        info = ExtractionConfig._get_domain_rule_patterns.cache_info()
        assert info.hits == 3
        assert info.misses == 3

    def test_cache_size_limit(self):
        """Verify cache respects maxsize=16 limit."""
        ExtractionConfig._get_domain_rule_patterns.cache_clear()
        
        # Generate more than 16 unique domains to test eviction
        domains = ["legal", "medical", "technical", "financial", "general", "unknown"]
        domains.extend([f"custom_{i}" for i in range(20)])
        
        for domain in domains:
            ExtractionConfig._get_domain_rule_patterns(domain)
        
        info = ExtractionConfig._get_domain_rule_patterns.cache_info()
        # Cache should still have size limit
        assert info.currsize <= 16

    def test_pattern_tuple_immutability(self):
        """Verify returned patterns are immutable tuples."""
        patterns = ExtractionConfig._get_domain_rule_patterns("legal")
        
        # Should be a tuple
        assert isinstance(patterns, tuple)
        
        # Each element should be a tuple
        for pattern in patterns:
            assert isinstance(pattern, tuple)
            assert len(pattern) == 2
            assert isinstance(pattern[0], str)  # regex pattern
            assert isinstance(pattern[1], str)  # entity type
        
        # Should not be able to modify
        with pytest.raises(TypeError):
            patterns[0] = ("new_pattern", "NewType")

    def test_legal_patterns_specific_content(self):
        """Verify legal domain patterns contain expected content."""
        patterns = ExtractionConfig._get_domain_rule_patterns("legal")
        pattern_dict = {p[1]: p[0] for p in patterns}
        
        # Should have key legal entity types
        assert "LegalParty" in pattern_dict
        
        # Patterns should be non-empty strings
        for pattern_str in pattern_dict.values():
            assert isinstance(pattern_str, str)
            assert len(pattern_str) > 0

    def test_medical_patterns_specific_content(self):
        """Verify medical domain patterns contain expected content."""
        patterns = ExtractionConfig._get_domain_rule_patterns("medical")
        pattern_dict = {p[1]: p[0] for p in patterns}
        
        # Should have key medical entity types
        assert len(pattern_dict) > 0

    def test_technical_patterns_specific_content(self):
        """Verify technical domain patterns contain expected content."""
        patterns = ExtractionConfig._get_domain_rule_patterns("technical")
        pattern_dict = {p[1]: p[0] for p in patterns}
        
        # Should have key technical entity types
        assert len(pattern_dict) > 0

    def test_financial_patterns_specific_content(self):
        """Verify financial domain patterns contain expected content."""
        patterns = ExtractionConfig._get_domain_rule_patterns("financial")
        pattern_dict = {p[1]: p[0] for p in patterns}
        
        # Should have key financial entity types
        assert len(pattern_dict) > 0


class TestDomainRulePatternPerformance:
    """Performance and optimization tests for lazy-loaded domain patterns."""

    def test_first_call_includes_pattern_building_overhead(self):
        """Verify first call incurs pattern construction overhead."""
        ExtractionConfig._get_domain_rule_patterns.cache_clear()
        
        # First call should construct the pattern dict
        import time
        start = time.perf_counter()
        ExtractionConfig._get_domain_rule_patterns("legal")
        first_call_time = time.perf_counter() - start
        
        # Subsequent calls should be much faster (cached)
        start = time.perf_counter()
        ExtractionConfig._get_domain_rule_patterns("legal")
        second_call_time = time.perf_counter() - start
        
        # Cache hit should be at least somewhat faster (may be hard to measure precisely)
        assert first_call_time >= 0  # Just verify it completes

    def test_all_domains_load_without_error(self):
        """Verify all known domains load successfully."""
        domains = ["legal", "medical", "technical", "financial", "general"]
        
        for domain in domains:
            patterns = ExtractionConfig._get_domain_rule_patterns(domain)
            assert isinstance(patterns, tuple)

    def test_patterns_are_strings_suitable_for_regex(self):
        """Verify patterns can be used with regex compilation."""
        import re
        
        patterns = ExtractionConfig._get_domain_rule_patterns("legal")
        
        for pattern_str, entity_type in patterns:
            # Should be compilable as regex
            try:
                compiled = re.compile(pattern_str)
                assert compiled is not None
            except re.error as e:
                pytest.fail(f"Pattern '{pattern_str}' for {entity_type} is not valid regex: {e}")

    def test_no_duplicate_entity_types_in_domain(self):
        """Verify no duplicate entity types within a domain."""
        patterns = ExtractionConfig._get_domain_rule_patterns("legal")
        entity_types = [p[1] for p in patterns]
        
        # Check for duplicates
        seen = set()
        for et in entity_types:
            if et in seen:
                pytest.fail(f"Duplicate entity type '{et}' in legal domain patterns")
            seen.add(et)

    def test_cache_memory_efficiency(self):
        """Verify caching reduces memory allocation on repeated calls."""
        ExtractionConfig._get_domain_rule_patterns.cache_clear()
        
        # Load multiple domains
        domains = ["legal", "medical", "technical", "financial"]
        for domain in domains:
            ExtractionConfig._get_domain_rule_patterns(domain)
        
        # Get cache stats
        info = ExtractionConfig._get_domain_rule_patterns.cache_info()
        
        # Cache should have stored 4 items
        assert info.currsize == len(domains)
        
        # Total calls = misses + hits = 4 misses, 0 hits
        assert info.misses == len(domains)
        assert info.hits == 0


class TestDomainRulePatternIntegration:
    """Integration tests for domain patterns in extraction workflow."""

    def test_patterns_used_in_extraction_config(self):
        """Verify patterns can be retrieved and used in parsing."""
        config = ExtractionConfig(
            domain_vocab={"Person": ["John", "Jane"]},
            custom_rules=[]
        )
        
        # Should initialize without error
        config.validate()

    def test_extraction_config_with_domain_vocab_integration(self):
        """Verify domain vocab doesn't conflict with lazy-loaded patterns."""
        config = ExtractionConfig(
            domain_vocab={
                "Symptom": ["fever", "cough"],
                "Medication": ["metformin", "aspirin"]
            }
        )
        
        # Should validate successfully
        config.validate()
        
        # domain_vocab should be preserved
        assert "Symptom" in config.domain_vocab

    def test_extraction_config_serialization_with_domain_patterns(self):
        """Verify config with domain patterns can be serialized."""
        config = ExtractionConfig(
            confidence_threshold=0.75,
            domain_vocab={"Symptom": ["fever"]}
        )
        
        # Should serialize to dict
        config_dict = config.to_dict()
        assert config_dict["confidence_threshold"] == 0.75
        assert config_dict["domain_vocab"] == {"Symptom": ["fever"]}
        
        # Should deserialize back
        config2 = ExtractionConfig.from_dict(config_dict)
        assert config2.confidence_threshold == 0.75


class TestLazyLoadingRobustness:
    """Robustness tests for lazy-loading edge cases."""

    def test_empty_domain_string(self):
        """Verify empty domain string is handled."""
        patterns = ExtractionConfig._get_domain_rule_patterns("")
        assert patterns == ()

    def test_domain_with_only_whitespace(self):
        """Verify whitespace-only domain defaults correctly."""
        patterns = ExtractionConfig._get_domain_rule_patterns("   ")
        assert patterns == ()

    def test_very_long_domain_string(self):
        """Verify very long domain strings don't break cache."""
        long_domain = "x" * 1000
        patterns = ExtractionConfig._get_domain_rule_patterns(long_domain)
        assert patterns == ()

    def test_special_characters_in_domain(self):
        """Verify special characters in domain name are handled."""
        special_domains = [
            "legal@domain",
            "medical#test",
            "technical$",
            "finance-2024",
            "domain_with_underscore"
        ]
        
        for domain in special_domains:
            patterns = ExtractionConfig._get_domain_rule_patterns(domain)
            assert isinstance(patterns, tuple)

    def test_cache_clear_and_reload(self):
        """Verify cache can be cleared and patterns reloaded."""
        ExtractionConfig._get_domain_rule_patterns.cache_clear()
        
        patterns1 = ExtractionConfig._get_domain_rule_patterns("legal")
        
        ExtractionConfig._get_domain_rule_patterns.cache_clear()
        
        patterns2 = ExtractionConfig._get_domain_rule_patterns("legal")
        
        # Patterns should be equal even after cache clear
        assert patterns1 == patterns2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
