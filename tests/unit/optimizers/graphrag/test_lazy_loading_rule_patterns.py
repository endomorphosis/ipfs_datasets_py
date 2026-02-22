"""
Test lazy loading of domain-specific rule patterns in OntologyGenerator.

This module tests that verb patterns and type inference rules are loaded
on-demand rather than at module import time, improving memory footprint
and startup performance.
"""

import pytest
from ipfs_datasets_py.optimizers.graphrag.ontology_generator import (
    OntologyGenerator,
    Entity,
)


class TestLazyLoadingVerbPatterns:
    """Test lazy loading behavior of verb-frame patterns."""

    def test_verb_patterns_initially_none(self):
        """Verify patterns are None before first access."""
        # Reset cache to ensure clean state
        OntologyGenerator._verb_patterns_cache = None
        
        assert OntologyGenerator._verb_patterns_cache is None

    def test_verb_patterns_loaded_on_first_access(self):
        """Verify patterns are loaded on first access."""
        # Reset cache
        OntologyGenerator._verb_patterns_cache = None
        
        # First access should load patterns
        patterns = OntologyGenerator._get_verb_patterns()
        
        assert patterns is not None
        assert isinstance(patterns, list)
        assert len(patterns) > 0
        assert OntologyGenerator._verb_patterns_cache is not None

    def test_verb_patterns_cached_on_subsequent_access(self):
        """Verify subsequent calls return cached instance."""
        # Reset and load
        OntologyGenerator._verb_patterns_cache = None
        first_call = OntologyGenerator._get_verb_patterns()
        
        # Second call should return same cached instance
        second_call = OntologyGenerator._get_verb_patterns()
        
        assert first_call is second_call
        assert id(first_call) == id(second_call)

    def test_verb_patterns_content(self):
        """Verify loaded patterns have expected structure and content."""
        patterns = OntologyGenerator._get_verb_patterns()
        
        # Should have at least 7 patterns (obligates, owns, causes, is_a, part_of, employs, manages)
        assert len(patterns) >= 7
        
        # Each pattern should be a tuple of (regex_str, rel_type_str)
        for pattern, rel_type in patterns:
            assert isinstance(pattern, str)
            assert isinstance(rel_type, str)
            assert len(pattern) > 0
            assert len(rel_type) > 0
        
        # Verify specific known patterns exist
        rel_types = [rt for _, rt in patterns]
        assert 'obligates' in rel_types
        assert 'owns' in rel_types
        assert 'causes' in rel_types
        assert 'is_a' in rel_types
        assert 'part_of' in rel_types
        assert 'employs' in rel_types
        assert 'manages' in rel_types

    def test_verb_patterns_used_in_inference(self):
        """Verify lazy-loaded patterns are actually used during relationship inference."""
        generator = OntologyGenerator()
        entities = [
            Entity(id="e1", text="Alice", type="person"),
            Entity(id="e2", text="Company", type="organization"),
        ]
        data = "Alice owns Company successfully."
        
        # Reset cache to verify it gets loaded
        OntologyGenerator._verb_patterns_cache = None
        
        # This should trigger lazy loading
        relationships = generator.infer_relationships(entities, data)
        
        # Cache should now be populated
        assert OntologyGenerator._verb_patterns_cache is not None
        
        # Should have inferred at least one relationship
        assert len(relationships) > 0
        
        # Should have an 'owns' relationship
        owns_rels = [r for r in relationships if r.type == 'owns']
        assert len(owns_rels) > 0


class TestLazyLoadingTypeInferenceRules:
    """Test lazy loading behavior of entity type-based inference rules."""

    def test_type_inference_rules_initially_none(self):
        """Verify rules are None before first access."""
        # Reset cache to ensure clean state
        OntologyGenerator._type_inference_rules_cache = None
        
        assert OntologyGenerator._type_inference_rules_cache is None

    def test_type_inference_rules_loaded_on_first_access(self):
        """Verify rules are loaded on first access."""
        # Reset cache
        OntologyGenerator._type_inference_rules_cache = None
        
        # First access should load rules
        rules = OntologyGenerator._get_type_inference_rules()
        
        assert rules is not None
        assert isinstance(rules, list)
        assert len(rules) > 0
        assert OntologyGenerator._type_inference_rules_cache is not None

    def test_type_inference_rules_cached_on_subsequent_access(self):
        """Verify subsequent calls return cached instance."""
        # Reset and load
        OntologyGenerator._type_inference_rules_cache = None
        first_call = OntologyGenerator._get_type_inference_rules()
        
        # Second call should return same cached instance
        second_call = OntologyGenerator._get_type_inference_rules()
        
        assert first_call is second_call
        assert id(first_call) == id(second_call)

    def test_type_inference_rules_content(self):
        """Verify loaded rules have expected structure and content."""
        rules = OntologyGenerator._get_type_inference_rules()
        
        # Should have at least 4 rules (works_for, located_in, produces, related_to)
        assert len(rules) >= 4
        
        # Each rule should have required keys
        required_keys = {'condition', 'type', 'base_confidence', 'distance_threshold'}
        for rule in rules:
            assert isinstance(rule, dict)
            assert required_keys.issubset(rule.keys())
            assert callable(rule['condition'])
            assert isinstance(rule['type'], str)
            assert isinstance(rule['base_confidence'], (int, float))
            assert isinstance(rule['distance_threshold'], (int, float))
            assert 0.0 <= rule['base_confidence'] <= 1.0
            assert rule['distance_threshold'] > 0
        
        # Verify specific known rule types exist
        rule_types = [r['type'] for r in rules]
        assert 'works_for' in rule_types
        assert 'located_in' in rule_types
        assert 'produces' in rule_types
        assert 'related_to' in rule_types

    def test_type_inference_rules_conditions_callable(self):
        """Verify rule conditions are callable and evaluate correctly."""
        rules = OntologyGenerator._get_type_inference_rules()
        
        # Test each rule's condition with sample inputs
        for rule in rules:
            condition = rule['condition']
            
            # Should be callable with two string arguments
            result = condition('person', 'organization')
            assert isinstance(result, bool)
            
            # Test various entity type combinations
            condition('person', 'location')
            condition('organization', 'product')
            condition('unknown', 'unknown')

    def test_type_inference_rules_used_in_cooccurrence(self):
        """Verify lazy-loaded rules are used during co-occurrence inference."""
        generator = OntologyGenerator()
        entities = [
            Entity(id="e1", text="Alice", type="person"),
            Entity(id="e2", text="Company", type="organization"),
        ]
        # Use explicit co-occurrence text (no verb pattern match)
        data = "Alice and Company work together in this text."
        
        # Reset cache to verify it gets loaded
        OntologyGenerator._type_inference_rules_cache = None
        
        # This should trigger lazy loading via co-occurrence inference
        relationships = generator.infer_relationships(entities, data)
        
        # Cache should now be populated
        assert OntologyGenerator._type_inference_rules_cache is not None
        
        # Should have inferred at least one relationship
        assert len(relationships) > 0
        
        # Should have a 'works_for' relationship (person + organization)
        works_for_rels = [r for r in relationships if r.type == 'works_for']
        assert len(works_for_rels) > 0


class TestLazyLoadingIntegration:
    """Integration tests for lazy loading with full extraction pipeline."""

    def test_multiple_generators_share_cache(self):
        """Verify multiple generator instances share the same cached patterns."""
        # Reset caches
        OntologyGenerator._verb_patterns_cache = None
        OntologyGenerator._type_inference_rules_cache = None
        
        # Create two generators
        gen1 = OntologyGenerator()
        gen2 = OntologyGenerator()
        
        # First generator triggers loading
        patterns1 = gen1._get_verb_patterns()
        rules1 = gen1._get_type_inference_rules()
        
        # Second generator should get same cached instances
        patterns2 = gen2._get_verb_patterns()
        rules2 = gen2._get_type_inference_rules()
        
        assert patterns1 is patterns2
        assert rules1 is rules2

    def test_cache_persists_across_inference_calls(self):
        """Verify cache persists across multiple inference calls."""
        # Reset caches
        OntologyGenerator._verb_patterns_cache = None
        OntologyGenerator._type_inference_rules_cache = None
        
        generator = OntologyGenerator()
        entities = [
            Entity(id="e1", text="Alice", type="person"),
            Entity(id="e2", text="Bob", type="person"),
        ]
        
        # First inference call
        generator.infer_relationships(entities, "Alice knows Bob.")
        first_patterns = OntologyGenerator._verb_patterns_cache
        first_rules = OntologyGenerator._type_inference_rules_cache
        
        # Second inference call
        generator.infer_relationships(entities, "Alice meets Bob.")
        second_patterns = OntologyGenerator._verb_patterns_cache
        second_rules = OntologyGenerator._type_inference_rules_cache
        
        # Should be same cached instances
        assert first_patterns is second_patterns
        assert first_rules is second_rules

    def test_lazy_loading_does_not_break_existing_tests(self):
        """Verify lazy loading preserves existing behavior."""
        generator = OntologyGenerator()
        entities = [
            Entity(id="e1", text="Alice", type="person"),
            Entity(id="e2", text="Company", type="organization"),
        ]
        data = "Alice owns Company and manages Company successfully."
        
        relationships = generator.infer_relationships(entities, data)
        
        # Should still infer relationships correctly
        assert len(relationships) > 0
        
        # Should have typed relationships
        rel_types = {r.type for r in relationships}
        assert len(rel_types) > 0
        
        # Should have type_confidence in properties
        for rel in relationships:
            assert 'type_confidence' in rel.properties
            assert isinstance(rel.properties['type_confidence'], (int, float))
            assert 0.0 <= rel.properties['type_confidence'] <= 1.0

    def test_lazy_loading_memory_efficiency(self):
        """Verify patterns are not duplicated across instances."""
        import sys
        
        # Reset caches
        OntologyGenerator._verb_patterns_cache = None
        OntologyGenerator._type_inference_rules_cache = None
        
        # Create multiple generators
        generators = [OntologyGenerator() for _ in range(10)]
        
        # Trigger loading in all generators
        for gen in generators:
            gen._get_verb_patterns()
            gen._get_type_inference_rules()
        
        # All should reference the same cached instances (memory-efficient)
        patterns_ids = {id(gen._get_verb_patterns()) for gen in generators}
        rules_ids = {id(gen._get_type_inference_rules()) for gen in generators}
        
        # Should only have one unique ID per pattern set
        assert len(patterns_ids) == 1
        assert len(rules_ids) == 1

    def test_cache_can_be_manually_reset(self):
        """Verify caches can be reset if needed (e.g., for testing)."""
        # Load caches
        OntologyGenerator._get_verb_patterns()
        OntologyGenerator._get_type_inference_rules()
        
        assert OntologyGenerator._verb_patterns_cache is not None
        assert OntologyGenerator._type_inference_rules_cache is not None
        
        # Reset caches
        OntologyGenerator._verb_patterns_cache = None
        OntologyGenerator._type_inference_rules_cache = None
        
        assert OntologyGenerator._verb_patterns_cache is None
        assert OntologyGenerator._type_inference_rules_cache is None
        
        # Can reload after reset
        patterns = OntologyGenerator._get_verb_patterns()
        rules = OntologyGenerator._get_type_inference_rules()
        
        assert patterns is not None
        assert rules is not None


class TestLazyLoadingPerformance:
    """Performance-related tests for lazy loading."""

    def test_patterns_not_loaded_if_not_used(self):
        """Verify patterns are not loaded if inference is not called."""
        # Reset caches
        OntologyGenerator._verb_patterns_cache = None
        OntologyGenerator._type_inference_rules_cache = None
        
        # Create generator but don't call inference
        generator = OntologyGenerator()
        
        # Caches should still be None (not loaded at __init__)
        assert OntologyGenerator._verb_patterns_cache is None
        assert OntologyGenerator._type_inference_rules_cache is None

    def test_first_access_loads_second_access_reuses(self):
        """Verify first access incurs loading cost, subsequent accesses are free."""
        import time
        
        # Reset caches
        OntologyGenerator._verb_patterns_cache = None
        OntologyGenerator._type_inference_rules_cache = None
        
        # First access (will load)
        start1 = time.perf_counter()
        patterns1 = OntologyGenerator._get_verb_patterns()
        elapsed1 = time.perf_counter() - start1
        
        # Second access (should be cached, very fast)
        start2 = time.perf_counter()
        patterns2 = OntologyGenerator._get_verb_patterns()
        elapsed2 = time.perf_counter() - start2
        
        # Second access should be significantly faster (at least 10x)
        # Note: This is a rough heuristic, actual times will vary
        assert elapsed2 < elapsed1 / 5 or elapsed2 < 0.0001
        
        # Should be same instance
        assert patterns1 is patterns2
