"""Performance tests for LLM fallback mechanism in OntologyGenerator.

Tests latency, memory usage, stress conditions, and concurrent access patterns.
Complements functional tests in test_llm_fallback_extraction.py with performance focus.

Run with: pytest test_llm_fallback_performance.py -v --tb=short
"""
from __future__ import annotations

import gc
import statistics
import sys
import time
from typing import List
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
)


# ===== Test Fixtures =====

@pytest.fixture
def small_text() -> str:
    """1KB text sample."""
    return (
        "The contract includes warranty and indemnification clauses. "
        "Parties agree to arbitration. Confidential information must be protected. "
    ) * 10  # ~1KB


@pytest.fixture
def medium_text() -> str:
    """10KB text sample."""
    return (
        "This Agreement includes a warranty and indemnification obligation. "
        "The parties agree to arbitration and waiver of jury trial. "
        "Confidential Information must be protected and returned upon termination. "
        "The Effective Date is January 1, 2024. Governing law is Delaware. "
    ) * 50  # ~10KB


@pytest.fixture
def large_text() -> str:
    """50KB text sample."""
    return (
        "This Services Agreement between Company A and Company B includes "
        "warranty provisions, indemnification obligations, limitation of liability, "
        "arbitration requirements, jury trial waiver, confidentiality terms, "
        "data protection requirements, intellectual property rights, termination clauses, "
        "and governing law provisions under Delaware law. Effective Date: 2024-01-01. "
    ) * 100  # ~50KB


@pytest.fixture
def generator() -> OntologyGenerator:
    """OntologyGenerator instance without IPFS accelerate."""
    return OntologyGenerator(use_ipfs_accelerate=False)


def _make_context(threshold: float = 0.5) -> OntologyGenerationContext:
    """Create test context with specified fallback threshold."""
    return OntologyGenerationContext(
        data_source="perf_test",
        data_type=DataType.TEXT,
        domain="legal",
        extraction_strategy=ExtractionStrategy.RULE_BASED,
        config=ExtractionConfig(llm_fallback_threshold=threshold, min_entity_length=2),
    )


def _make_low_confidence_result(n_entities: int = 5) -> EntityExtractionResult:
    """Create low-confidence extraction result to trigger fallback."""
    entities = [
        Entity(id=f"e{i}", type="Term", text=f"term_{i}", confidence=0.2)
        for i in range(n_entities)
    ]
    return EntityExtractionResult(
        entities=entities, relationships=[], confidence=0.2, metadata={}
    )


def _make_high_confidence_result(n_entities: int = 5) -> EntityExtractionResult:
    """Create high-confidence extraction result (LLM fallback succeeds)."""
    entities = [
        Entity(id=f"e{i}", type="Term", text=f"term_{i}", confidence=0.9)
        for i in range(n_entities)
    ]
    return EntityExtractionResult(
        entities=entities, relationships=[], confidence=0.9, metadata={}
    )


def _time_extraction(generator: OntologyGenerator, text: str, context: OntologyGenerationContext, runs: int = 5) -> dict:
    """Time extraction with warmup and multiple runs."""
    # Warmup (2 runs)
    for _ in range(2):
        generator.extract_entities(text, context)
    
    # Timed runs
    times = []
    for _ in range(runs):
        start = time.perf_counter()
        generator.extract_entities(text, context)
        elapsed = (time.perf_counter() - start) * 1000  # Convert to ms
        times.append(elapsed)
    
    return {
        "mean_ms": statistics.mean(times),
        "median_ms": statistics.median(times),
        "min_ms": min(times),
        "max_ms": max(times),
        "stdev_ms": statistics.stdev(times) if len(times) > 1 else 0.0,
        "times": times,
    }


# ===== Latency Benchmarks =====

class TestFallbackLatencyBaseline:
    """Baseline latency without fallback (threshold=0)."""
    
    def test_small_text_no_fallback(self, generator, small_text):
        """Baseline: 1KB text, no LLM fallback."""
        context = _make_context(threshold=0.0)
        stats = _time_extraction(generator, small_text, context, runs=5)
        
        # Should be fast (< 100ms for 1KB)
        assert stats["mean_ms"] < 100, f"Baseline too slow: {stats['mean_ms']:.2f}ms"
    
    def test_medium_text_no_fallback(self, generator, medium_text):
        """Baseline: 10KB text, no LLM fallback."""
        context = _make_context(threshold=0.0)
        stats = _time_extraction(generator, medium_text, context, runs=5)
        
        # Should scale reasonably (< 500ms for 10KB)
        assert stats["mean_ms"] < 500, f"Baseline too slow: {stats['mean_ms']:.2f}ms"
    
    def test_large_text_no_fallback(self, generator, large_text):
        """Baseline: 50KB text, no LLM fallback."""
        context = _make_context(threshold=0.0)
        stats = _time_extraction(generator, large_text, context, runs=3)
        
        # Should remain reasonable (< 2000ms for 50KB)
        assert stats["mean_ms"] < 2000, f"Baseline too slow: {stats['mean_ms']:.2f}ms"


class TestFallbackLatencyOverhead:
    """Latency overhead when fallback is triggered."""
    
    def test_fallback_overhead_small_text(self, generator, small_text):
        """Measure fallback overhead on 1KB text."""
        # Baseline (no fallback)
        context_baseline = _make_context(threshold=0.0)
        baseline_stats = _time_extraction(generator, small_text, context_baseline, runs=5)
        
        # With fallback (threshold=0.99, mock LLM backend)
        generator.llm_backend = MagicMock()
        context_fallback = _make_context(threshold=0.99)
        
        # Mock both rule-based and LLM extraction
        low_conf_result = _make_low_confidence_result(n_entities=3)
        high_conf_result = _make_high_confidence_result(n_entities=5)
        
        with patch.object(generator, "_extract_rule_based", return_value=low_conf_result), \
             patch.object(generator, "_extract_llm_based", return_value=high_conf_result):
            fallback_stats = _time_extraction(generator, small_text, context_fallback, runs=5)
        
        # Fallback should add some overhead but not excessive (< 50ms extra for mocked LLM)
        overhead_ms = fallback_stats["mean_ms"] - baseline_stats["mean_ms"]
        overhead_pct = (overhead_ms / baseline_stats["mean_ms"]) * 100 if baseline_stats["mean_ms"] > 0 else 0
        
        # Overhead should be reasonable (< 100% increase for mocked LLM)
        assert overhead_pct < 100, f"Fallback overhead too high: {overhead_pct:.1f}% ({overhead_ms:.2f}ms)"
    
    def test_fallback_overhead_consistent_across_runs(self, generator, medium_text):
        """Fallback overhead should be consistent (low variance)."""
        generator.llm_backend = MagicMock()
        context = _make_context(threshold=0.99)
        
        low_conf_result = _make_low_confidence_result(n_entities=5)
        high_conf_result = _make_high_confidence_result(n_entities=8)
        
        with patch.object(generator, "_extract_rule_based", return_value=low_conf_result), \
             patch.object(generator, "_extract_llm_based", return_value=high_conf_result):
            stats = _time_extraction(generator, medium_text, context, runs=10)
        
        # Coefficient of variation (stdev/mean) should be low (< 25%)
        cv = (stats["stdev_ms"] / stats["mean_ms"]) * 100 if stats["mean_ms"] > 0 else 0
        assert cv < 25, f"High variance in fallback overhead: CV={cv:.1f}%"


class TestFallbackScaling:
    """Test fallback performance scaling with text size."""
    
    def test_fallback_scales_linearly(self, generator, small_text, medium_text):
        """Fallback latency should scale roughly linearly with text size."""
        generator.llm_backend = MagicMock()
        
        # Small text (1KB)
        context_small = _make_context(threshold=0.99)
        low_conf = _make_low_confidence_result(n_entities=2)
        high_conf = _make_high_confidence_result(n_entities=4)
        
        with patch.object(generator, "_extract_rule_based", return_value=low_conf), \
             patch.object(generator, "_extract_llm_based", return_value=high_conf):
            stats_small = _time_extraction(generator, small_text, context_small, runs=5)
        
        # Medium text (10KB, 10x larger)
        context_medium = _make_context(threshold=0.99)
        with patch.object(generator, "_extract_rule_based", return_value=low_conf), \
             patch.object(generator, "_extract_llm_based", return_value=high_conf):
            stats_medium = _time_extraction(generator, medium_text, context_medium, runs=5)
        
        # Scaling factor should be reasonable (< 20x for 10x text size increase)
        scaling_factor = stats_medium["mean_ms"] / stats_small["mean_ms"] if stats_small["mean_ms"] > 0 else 0
        assert scaling_factor < 20, f"Poor scaling: {scaling_factor:.1f}x for 10x text"


# ===== Memory Profiling =====

class TestFallbackMemoryUsage:
    """Memory usage tests for fallback mechanism."""
    
    def test_no_memory_leak_repeated_fallback(self, generator, medium_text):
        """Repeated fallback calls should not leak memory."""
        generator.llm_backend = MagicMock()
        context = _make_context(threshold=0.99)
        
        low_conf = _make_low_confidence_result(n_entities=10)
        high_conf = _make_high_confidence_result(n_entities=15)
        
        with patch.object(generator, "_extract_rule_based", return_value=low_conf), \
             patch.object(generator, "_extract_llm_based", return_value=high_conf):
            
            # Run multiple iterations and check memory stability
            gc.collect()
            initial_objects = len(gc.get_objects())
            
            for _ in range(20):
                generator.extract_entities(medium_text, context)
            
            gc.collect()
            final_objects = len(gc.get_objects())
            
            # Object count shouldn't grow excessively (< 20% increase)
            growth_pct = ((final_objects - initial_objects) / initial_objects) * 100
            assert growth_pct < 20, f"Potential memory leak: {growth_pct:.1f}% object growth"
    
    def test_large_text_memory_efficient(self, generator, large_text):
        """Large text extraction should not consume excessive memory."""
        context = _make_context(threshold=0.0)
        
        gc.collect()
        initial_objects = len(gc.get_objects())
        
        # Single extraction of large text
        generator.extract_entities(large_text, context)
        
        gc.collect()
        final_objects = len(gc.get_objects())
        
        # Object count increase should be reasonable (< 30%)
        growth_pct = ((final_objects - initial_objects) / initial_objects) * 100
        assert growth_pct < 30, f"Excessive memory usage: {growth_pct:.1f}% object growth"


# ===== Stress Testing =====

class TestFallbackStressConditions:
    """Stress testing under extreme conditions."""
    
    def test_fallback_handles_many_entities(self, generator, large_text):
        """Fallback should handle extraction results with many entities."""
        generator.llm_backend = MagicMock()
        context = _make_context(threshold=0.99)
        
        # Create extraction results with 100 entities
        low_conf = _make_low_confidence_result(n_entities=100)
        high_conf = _make_high_confidence_result(n_entities=150)
        
        with patch.object(generator, "_extract_rule_based", return_value=low_conf), \
             patch.object(generator, "_extract_llm_based", return_value=high_conf):
            start = time.perf_counter()
            result = generator.extract_entities(large_text, context)
            elapsed_ms = (time.perf_counter() - start) * 1000
        
        # Should complete reasonably fast even with many entities (< 3s)
        assert elapsed_ms < 3000, f"Too slow with many entities: {elapsed_ms:.0f}ms"
        assert len(result.entities) == 150
    
    def test_fallback_exception_recovery_performance(self, generator, medium_text):
        """Exception recovery in fallback should not add significant overhead."""
        generator.llm_backend = MagicMock()
        context = _make_context(threshold=0.99)
        
        low_conf = _make_low_confidence_result(n_entities=5)
        
        # Time fallback with LLM exception (should fall back to rule-based)
        with patch.object(generator, "_extract_rule_based", return_value=low_conf), \
             patch.object(generator, "_extract_llm_based", side_effect=RuntimeError("LLM timeout")):
            
            times = []
            for _ in range(5):
                start = time.perf_counter()
                result = generator.extract_entities(medium_text, context)
                times.append((time.perf_counter() - start) * 1000)
            
            mean_ms = statistics.mean(times)
        
        # Exception handling should be fast (< 500ms)
        assert mean_ms < 500, f"Exception recovery too slow: {mean_ms:.2f}ms"


# ===== Concurrent Access =====

class TestFallbackConcurrency:
    """Test fallback under concurrent access patterns."""
    
    def test_sequential_fallback_calls_independent(self, generator, small_text):
        """Sequential fallback calls should not interfere with each other."""
        generator.llm_backend = MagicMock()
        context = _make_context(threshold=0.99)
        
        low_conf = _make_low_confidence_result(n_entities=3)
        high_conf = _make_high_confidence_result(n_entities=5)
        
        with patch.object(generator, "_extract_rule_based", return_value=low_conf), \
             patch.object(generator, "_extract_llm_based", return_value=high_conf):
            
            results = []
            for _ in range(10):
                result = generator.extract_entities(small_text, context)
                results.append(result)
            
            # All results should have same confidence (no state pollution)
            confidences = [r.confidence for r in results]
            assert len(set(confidences)) == 1, f"Inconsistent confidences: {confidences}"
            assert confidences[0] == 0.9


# ===== Performance Regression Guards =====

class TestFallbackPerformanceBaselines:
    """Regression tests: ensure performance doesn't degrade over time."""
    
    def test_baseline_performance_threshold(self, generator, medium_text):
        """Rule-based extraction baseline should meet performance target."""
        context = _make_context(threshold=0.0)
        stats = _time_extraction(generator, medium_text, context, runs=5)
        
        # Performance target: 10KB text in < 300ms (aggressive but achievable)
        assert stats["mean_ms"] < 300, (
            f"Performance regression: baseline {stats['mean_ms']:.2f}ms exceeds 300ms target"
        )
    
    def test_fallback_overhead_threshold(self, generator, medium_text):
        """Fallback overhead should remain within acceptable bounds."""
        # Baseline
        context_baseline = _make_context(threshold=0.0)
        baseline_stats = _time_extraction(generator, medium_text, context_baseline, runs=5)
        
        # With fallback
        generator.llm_backend = MagicMock()
        context_fallback = _make_context(threshold=0.99)
        
        low_conf = _make_low_confidence_result(n_entities=5)
        high_conf = _make_high_confidence_result(n_entities=8)
        
        with patch.object(generator, "_extract_rule_based", return_value=low_conf), \
             patch.object(generator, "_extract_llm_based", return_value=high_conf):
            fallback_stats = _time_extraction(generator, medium_text, context_fallback, runs=5)
        
        overhead_ms = fallback_stats["mean_ms"] - baseline_stats["mean_ms"]
        
        # Performance target: fallback overhead < 100ms for mocked LLM
        assert overhead_ms < 100, (
            f"Performance regression: fallback overhead {overhead_ms:.2f}ms exceeds 100ms target"
        )
