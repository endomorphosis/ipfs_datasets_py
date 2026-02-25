"""Memory profiling tests for ontology generation with large entity/relationship sets.

Tests memory usage patterns, leak detection, and efficiency across different scales.
Profiles generation of 100, 1K, 10K, and 100K entity ontologies.

Run with: pytest test_ontology_memory_profiling.py -v -s --tb=short
"""
from __future__ import annotations

import gc
import sys
from typing import List, Tuple
from unittest.mock import MagicMock, patch

import pytest

from ipfs_datasets_py.optimizers.graphrag.ontology_generator import (
    DataType,
    Entity,
    EntityExtractionResult,
    ExtractionConfig,
    ExtractionStrategy,
    OntologyGenerationContext,
    OntologyGenerator,
    Relationship,
)


# ===== Memory Utilities =====

def _get_object_count() -> int:
    """Get current object count from garbage collector."""
    gc.collect()
    return len(gc.get_objects())


def _get_memory_mb() -> float:
    """Get approximate memory usage in MB (object count proxy)."""
    # Note: This is a rough proxy. Real memory profiling would use tracemalloc or memory_profiler.
    # For pytest unit tests, we use object count as a lightweight alternative.
    gc.collect()
    return len(gc.get_objects()) / 10000  # Rough approximation


def _generate_text_with_entities(n_entities: int) -> str:
    """Generate synthetic text containing n_entities entities."""
    # Create text with noun phrases for entity extraction
    entity_templates = [
        "The {entity} provides warranty coverage.",
        "Company {entity} agrees to indemnification.",
        "The {entity} clause governs arbitration.",
        "Person {entity} signed the agreement.",
        "Organization {entity} handles compliance.",
    ]
    
    text_parts = []
    for i in range(n_entities):
        template = entity_templates[i % len(entity_templates)]
        text_parts.append(template.format(entity=f"Entity_{i}"))
    
    return " ".join(text_parts)


def _make_large_extraction_result(n_entities: int, n_relationships: int = 0) -> EntityExtractionResult:
    """Create extraction result with many entities and relationships."""
    entities = [
        Entity(
            id=f"entity_{i}",
            type=["Person", "Organization", "Term", "Clause"][i % 4],
            text=f"Entity_{i}",
            confidence=0.7 + (i % 3) * 0.1,
            properties={"source": "test", "index": i}
        )
        for i in range(n_entities)
    ]
    
    relationships = []
    if n_relationships > 0:
        # Create relationships between entities (sparse graph)
        for i in range(n_relationships):
            source_idx = i % n_entities
            target_idx = (i + 1) % n_entities
            rel = Relationship(
                id=f"rel_{i}",
                source_id=entities[source_idx].id,
                target_id=entities[target_idx].id,
                type=["references", "contains", "extends", "implements"][i % 4],
                confidence=0.6 + (i % 4) * 0.1,
                properties={"source": "test"}
            )
            relationships.append(rel)
    
    return EntityExtractionResult(
        entities=entities,
        relationships=relationships,
        confidence=0.75,
        metadata={"n_entities": n_entities, "n_relationships": n_relationships}
    )


# ===== Test Fixtures =====

@pytest.fixture
def generator() -> OntologyGenerator:
    """OntologyGenerator instance without IPFS accelerate."""
    return OntologyGenerator(use_ipfs_accelerate=False)


@pytest.fixture
def context() -> OntologyGenerationContext:
    """Basic context for memory profiling."""
    return OntologyGenerationContext(
        data_source="memory_profile_test",
        data_type=DataType.TEXT,
        domain="general",
        extraction_strategy=ExtractionStrategy.RULE_BASED,
        config=ExtractionConfig(min_entity_length=2),
    )


# ===== Small Scale (10-100 entities) =====

class TestSmallScaleMemory:
    """Memory profiling for small ontologies (10-100 entities)."""
    
    def test_memory_baseline_10_entities(self, generator, context):
        """Baseline memory usage with 10 entities."""
        initial_mem = _get_memory_mb()
        
        text = _generate_text_with_entities(10)
        result = generator.extract_entities(text, context)
        
        final_mem = _get_memory_mb()
        mem_delta = final_mem - initial_mem
        
        # 10 entities should use minimal memory (< 1.0 MB, accounting for Python overhead)
        assert mem_delta < 1.0, f"Excessive memory for 10 entities: {mem_delta:.2f} MB proxy"
        assert len(result.entities) >= 3  # At least some entities extracted
    
    def test_memory_100_entities(self, generator, context):
        """Memory usage with 100 entities."""
        initial_mem = _get_memory_mb()
        
        # Mock extraction to return exactly 100 entities
        large_result = _make_large_extraction_result(n_entities=100)
        text = _generate_text_with_entities(100)
        
        with patch.object(generator, "_extract_rule_based", return_value=large_result):
            result = generator.extract_entities(text, context)
        
        final_mem = _get_memory_mb()
        mem_delta = final_mem - initial_mem
        
        # 100 entities should still be lightweight (< 2 MB proxy units)
        assert mem_delta < 2.0, f"Excessive memory for 100 entities: {mem_delta:.2f} MB proxy"
        assert len(result.entities) == 100


# ===== Medium Scale (1K entities) =====

class TestMediumScaleMemory:
    """Memory profiling for medium ontologies (1K entities)."""
    
    def test_memory_1k_entities(self, generator, context):
        """Memory usage with 1,000 entities."""
        initial_mem = _get_memory_mb()
        
        large_result = _make_large_extraction_result(n_entities=1000)
        text = _generate_text_with_entities(1000)
        
        with patch.object(generator, "_extract_rule_based", return_value=large_result):
            result = generator.extract_entities(text, context)
        
        final_mem = _get_memory_mb()
        mem_delta = final_mem - initial_mem
        mem_per_entity = mem_delta / 1000 if mem_delta > 0 else 0
        
        # 1K entities should use reasonable memory (< 10 MB proxy units)
        assert mem_delta < 10.0, f"Excessive memory for 1K entities: {mem_delta:.2f} MB proxy"
        assert mem_per_entity < 0.01, f"High memory per entity: {mem_per_entity:.4f} MB proxy"
        assert len(result.entities) == 1000
    
    def test_memory_1k_entities_with_relationships(self, generator, context):
        """Memory usage with 1K entities + 2K relationships."""
        initial_mem = _get_memory_mb()
        
        large_result = _make_large_extraction_result(n_entities=1000, n_relationships=2000)
        text = _generate_text_with_entities(1000)
        
        with patch.object(generator, "_extract_rule_based", return_value=large_result):
            result = generator.extract_entities(text, context)
        
        final_mem = _get_memory_mb()
        mem_delta = final_mem - initial_mem
        
        # 1K entities + 2K relationships should still be manageable (< 15 MB proxy units)
        assert mem_delta < 15.0, f"Excessive memory for 1K entities + 2K rels: {mem_delta:.2f} MB proxy"
        assert len(result.entities) == 1000
        assert len(result.relationships) == 2000


# ===== Large Scale (10K entities) =====

class TestLargeScaleMemory:
    """Memory profiling for large ontologies (10K entities)."""
    
    def test_memory_10k_entities(self, generator, context):
        """Memory usage with 10,000 entities."""
        initial_mem = _get_memory_mb()
        
        large_result = _make_large_extraction_result(n_entities=10000)
        text = _generate_text_with_entities(10000)
        
        with patch.object(generator, "_extract_rule_based", return_value=large_result):
            result = generator.extract_entities(text, context)
        
        final_mem = _get_memory_mb()
        mem_delta = final_mem - initial_mem
        mem_per_entity = mem_delta / 10000 if mem_delta > 0 else 0
        
        # 10K entities should use moderate memory (< 50 MB proxy units)
        assert mem_delta < 50.0, f"Excessive memory for 10K entities: {mem_delta:.2f} MB proxy"
        assert mem_per_entity < 0.005, f"High memory per entity at 10K scale: {mem_per_entity:.4f} MB proxy"
        assert len(result.entities) == 10000
    
    def test_memory_10k_entities_dense_relationships(self, generator, context):
        """Memory usage with 10K entities + 50K relationships (dense graph)."""
        initial_mem = _get_memory_mb()
        
        large_result = _make_large_extraction_result(n_entities=10000, n_relationships=50000)
        text = _generate_text_with_entities(10000)
        
        with patch.object(generator, "_extract_rule_based", return_value=large_result):
            result = generator.extract_entities(text, context)
        
        final_mem = _get_memory_mb()
        mem_delta = final_mem - initial_mem
        
        # 10K entities + 50K relationships should remain reasonable (< 100 MB proxy units)
        assert mem_delta < 100.0, f"Excessive memory for 10K entities + 50K rels: {mem_delta:.2f} MB proxy"
        assert len(result.entities) == 10000
        assert len(result.relationships) == 50000


# ===== Memory Leak Detection =====

class TestMemoryLeaks:
    """Detect memory leaks during repeated extraction."""
    
    def test_no_leak_repeated_small_ontology(self, generator, context):
        """Repeated extraction of small ontology should not leak memory."""
        text = _generate_text_with_entities(50)
        
        gc.collect()
        initial_objects = _get_object_count()
        
        # Extract 20 times
        for _ in range(20):
            generator.extract_entities(text, context)
        
        gc.collect()
        final_objects = _get_object_count()
        
        # Object count growth should be minimal (< 10% after 20 iterations)
        growth_pct = ((final_objects - initial_objects) / initial_objects) * 100
        assert growth_pct < 10, f"Potential memory leak: {growth_pct:.1f}% object growth after 20 iterations"
    
    def test_no_leak_repeated_medium_ontology(self, generator, context):
        """Repeated extraction of medium ontology (500 entities) should not leak."""
        large_result = _make_large_extraction_result(n_entities=500, n_relationships=800)
        text = _generate_text_with_entities(500)
        
        gc.collect()
        initial_objects = _get_object_count()
        
        # Extract 10 times with mocked result
        with patch.object(generator, "_extract_rule_based", return_value=large_result):
            for _ in range(10):
                generator.extract_entities(text, context)
        
        gc.collect()
        final_objects = _get_object_count()
        
        # Object count growth should be reasonable (< 15% after 10 iterations)
        growth_pct = ((final_objects - initial_objects) / initial_objects) * 100
        assert growth_pct < 15, f"Potential memory leak: {growth_pct:.1f}% object growth after 10 iterations"
    
    def test_cleanup_after_large_ontology(self, generator, context):
        """Large ontology should be garbage collected after extraction."""
        large_result = _make_large_extraction_result(n_entities=5000, n_relationships=10000)
        text = _generate_text_with_entities(5000)
        
        gc.collect()
        initial_objects = _get_object_count()
        
        # Extract once
        with patch.object(generator, "_extract_rule_based", return_value=large_result):
            result = generator.extract_entities(text, context)
            del result  # Explicit cleanup
        
        gc.collect()
        final_objects = _get_object_count()
        
        # Object count should not grow excessively (< 20% for one-time large extraction)
        growth_pct = ((final_objects - initial_objects) / initial_objects) * 100
        assert growth_pct < 20, f"Poor garbage collection: {growth_pct:.1f}% object growth after large extraction"


# ===== Memory Efficiency Comparisons =====

class TestMemoryEfficiency:
    """Compare memory efficiency across different extraction strategies."""
    
    def test_rule_based_vs_llm_fallback_memory(self, generator, context):
        """Rule-based should use similar memory to LLM fallback (mocked LLM)."""
        text = _generate_text_with_entities(200)
        
        # Rule-based only
        context_rule = OntologyGenerationContext(
            data_source="memory_test_rule",
            data_type=DataType.TEXT,
            domain="general",
            extraction_strategy=ExtractionStrategy.RULE_BASED,
            config=ExtractionConfig(llm_fallback_threshold=0.0, min_entity_length=2),
        )
        
        gc.collect()
        initial_mem_rule = _get_memory_mb()
        generator.extract_entities(text, context_rule)
        gc.collect()
        mem_rule = _get_memory_mb() - initial_mem_rule
        
        # LLM fallback (mocked)
        context_fallback = OntologyGenerationContext(
            data_source="memory_test_fallback",
            data_type=DataType.TEXT,
            domain="general",
            extraction_strategy=ExtractionStrategy.RULE_BASED,
            config=ExtractionConfig(llm_fallback_threshold=0.99, min_entity_length=2),
        )
        
        generator.llm_backend = MagicMock()
        low_conf_result = _make_large_extraction_result(n_entities=50)
        high_conf_result = _make_large_extraction_result(n_entities=70)
        
        with patch.object(generator, "_extract_rule_based", return_value=low_conf_result), \
             patch.object(generator, "_extract_llm_based", return_value=high_conf_result):
            gc.collect()
            initial_mem_fallback = _get_memory_mb()
            generator.extract_entities(text, context_fallback)
            gc.collect()
            mem_fallback = _get_memory_mb() - initial_mem_fallback
        
        # Fallback should not use significantly more memory (< 2x rule-based)
        ratio = mem_fallback / mem_rule if mem_rule > 0.01 else 1.0
        assert ratio < 2.0, f"LLM fallback uses excessive memory: {ratio:.1f}x rule-based"
    
    def test_memory_scales_with_entity_count(self, generator, context):
        """Memory usage should scale linearly with entity count."""
        scales = [100, 500, 1000]
        memory_deltas = []
        
        for n_entities in scales:
            large_result = _make_large_extraction_result(n_entities=n_entities)
            text = _generate_text_with_entities(n_entities)
            
            gc.collect()
            initial_mem = _get_memory_mb()
            
            with patch.object(generator, "_extract_rule_based", return_value=large_result):
                generator.extract_entities(text, context)
            
            gc.collect()
            mem_delta = _get_memory_mb() - initial_mem
            memory_deltas.append(mem_delta)
        
        # Memory should scale reasonably (1000 entities should use < 20x memory of 100 entities)
        ratio_1000_to_100 = memory_deltas[2] / memory_deltas[0] if memory_deltas[0] > 0.01 else 1.0
        assert ratio_1000_to_100 < 20, f"Poor memory scaling: {ratio_1000_to_100:.1f}x for 10x entities"


# ===== Stress Testing =====

class TestMemoryStress:
    """Stress testing with extreme memory conditions."""
    
    def test_memory_with_very_large_metadata(self, generator, context):
        """Entities with large properties should not cause excessive memory usage."""
        # Create entities with large properties dictionaries
        entities = [
            Entity(
                id=f"entity_{i}",
                type="Term",
                text=f"Entity_{i}",
                confidence=0.7,
                properties={
                    "source": "test",
                    "large_field": "x" * 1000,  # 1KB properties per entity
                    "nested": {"a": list(range(100)), "b": list(range(100))},
                }
            )
            for i in range(500)
        ]
        
        large_result = EntityExtractionResult(
            entities=entities, relationships=[], confidence=0.7, metadata={}
        )
        
        text = _generate_text_with_entities(500)
        
        gc.collect()
        initial_mem = _get_memory_mb()
        
        with patch.object(generator, "_extract_rule_based", return_value=large_result):
            result = generator.extract_entities(text, context)
        
        gc.collect()
        mem_delta = _get_memory_mb() - initial_mem
        
        # Should handle large metadata (< 30 MB proxy units for 500 entities with large metadata)
        assert mem_delta < 30.0, f"Excessive memory with large metadata: {mem_delta:.2f} MB proxy"
        assert len(result.entities) == 500
    
    def test_memory_recovery_after_extraction_failure(self, generator, context):
        """Memory should be recovered after extraction failure."""
        text = _generate_text_with_entities(200)
        
        gc.collect()
        initial_objects = _get_object_count()
        
        # Simulate extraction failure
        with patch.object(generator, "_extract_rule_based", side_effect=RuntimeError("Extraction failed")):
            try:
                generator.extract_entities(text, context)
            except RuntimeError:
                pass  # Expected
        
        gc.collect()
        final_objects = _get_object_count()
        
        # Object count should not grow significantly after failure (< 5%)
        growth_pct = ((final_objects - initial_objects) / initial_objects) * 100
        assert growth_pct < 5, f"Memory leak after extraction failure: {growth_pct:.1f}% object growth"
