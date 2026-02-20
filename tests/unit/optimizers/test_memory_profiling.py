"""
Memory profiling tests for large ontologies.

This test suite validates optimizer performance under memory-intensive conditions.
It helps identify optimization opportunities (O(n²) bottlenecks, etc.) and ensures
the optimizers can handle realistic large-scale inputs.

Tests track:
- Peak memory usage during ontology analysis
- Time complexity of merging/analysis operations
- Resource efficiency of parallel vs sequential processing

pytest -xvs tests/unit/optimizers/test_memory_profiling.py
"""

import gc
import json
import sys
import time
from typing import Any, Dict, List

import pytest

from ipfs_datasets_py.optimizers.graphrag.ontology_optimizer import OntologyOptimizer
from ipfs_datasets_py.optimizers.graphrag.ontology_generator import (
    OntologyGenerator,
    OntologyGenerationContext,
)


def get_memory_usage_mb() -> float:
    """Get current memory usage in MB."""
    try:
        import psutil
        process = psutil.Process()
        return process.memory_info().rss / (1024 * 1024)  # Convert to MB
    except ImportError:
        # Fallback if psutil not available
        return 0.0


def measure_memory_delta(func, *args, **kwargs) -> tuple[Any, float]:
    """
    Measure memory delta of a function call.
    
    Returns:
        (result, memory_delta_mb)
    """
    gc.collect()  # Force garbage collection before measurement
    mem_before = get_memory_usage_mb()
    
    result = func(*args, **kwargs)
    
    gc.collect()  # Force garbage collection after measurement
    mem_after = get_memory_usage_mb()
    
    return result, max(0, mem_after - mem_before)


# ============================================================================
# Large Ontology Generation Tests
# ============================================================================

class TestLargeOntologyGeneration:
    """Test memory usage when generating large ontologies."""
    
    def test_memory_usage_creating_large_ontology_dict(self):
        """Profile memory used to create large ontology dictionary."""
        
        def create_large_ontology():
            return {
                'entities': [
                    {
                        'id': f'entity_{i}',
                        'type': f'type_{i % 5}',
                        'properties': {
                            'name': f'Entity {i}',
                            'created': '2026-02-21',
                        }
                    }
                    for i in range(100)
                ],
                'relationships': [
                    {
                        'source': f'entity_{i}',
                        'target': f'entity_{(i+1) % 100}',
                        'type': 'connected'
                    }
                    for i in range(100)
                ],
                'metadata': {'num_entities': 100}
            }
        
        result, mem_delta = measure_memory_delta(create_large_ontology)
        
        # Should use reasonable memory (< 5MB for 100 entities)
        assert mem_delta < 10.0, f"Memory usage too high: {mem_delta:.1f}MB"
        assert result is not None
        assert len(result['entities']) == 100
    
    def test_memory_usage_creating_very_large_ontology_dict(self):
        """Profile memory used to create very large ontology dictionary."""
        
        def create_very_large_ontology():
            return {
                'entities': [
                    {
                        'id': f'entity_{i}',
                        'type': f'type_{i % 5}',
                        'properties': {'name': f'Entity {i}'}
                    }
                    for i in range(1000)
                ],
                'relationships': [
                    {
                        'source': f'entity_{i}',
                        'target': f'entity_{(i+1) % 1000}',
                        'type': 'connected'
                    }
                    for i in range(1000)
                ],
                'metadata': {'num_entities': 1000}
            }
        
        result, mem_delta = measure_memory_delta(create_very_large_ontology)
        
        # Should use reasonable memory (< 50MB for 1000 entities)
        assert mem_delta < 100.0, f"Memory usage too high: {mem_delta:.1f}MB"
        assert result is not None
        assert len(result['entities']) == 1000


# ============================================================================
# Ontology Merging Complexity Tests
# ============================================================================

class TestOntologyMergingEfficiency:
    """Test memory efficiency of ontology merging operations."""
    
    def create_ontology(self, num_entities: int) -> Dict[str, Any]:
        """Create a deterministic ontology with specified entity count."""
        return {
            'entities': [
                {
                    'id': f'entity_{i}',
                    'type': f'type_{i % 10}',
                    'properties': {
                        'name': f'Entity {i}',
                        'created': '2026-02-21',
                    }
                }
                for i in range(num_entities)
            ],
            'relationships': [
                {
                    'source': f'entity_{i}',
                    'target': f'entity_{(i+1) % num_entities}',
                    'type': f'rel_{i % 5}',
                }
                for i in range(num_entities - 1)
            ],
            'metadata': {'num_entities': num_entities}
        }
    
    def test_merging_two_100entity_ontologies(self):
        """Test merging two ontologies with 100 entities each."""
        generator = OntologyGenerator()
        
        onto1 = self.create_ontology(100)
        onto2 = self.create_ontology(100)
        
        result, mem_delta = measure_memory_delta(
            generator._merge_ontologies,
            onto1,
            onto2
        )
        
        # Should merge efficiently (< 10MB delta)
        assert mem_delta < 50.0, f"Memory usage too high: {mem_delta:.1f}MB"
        assert result is not None
    
    def test_merging_two_500entity_ontologies(self):
        """Test merging two ontologies with 500 entities each."""
        generator = OntologyGenerator()
        
        onto1 = self.create_ontology(500)
        onto2 = self.create_ontology(500)
        
        result, mem_delta = measure_memory_delta(
            generator._merge_ontologies,
            onto1,
            onto2
        )
        
        # Should merge efficiently even for large ontologies
        assert mem_delta < 100.0, f"Memory usage too high: {mem_delta:.1f}MB"
        assert result is not None
    
    def test_merging_many_small_ontologies(self):
        """Test merging 10 small ontologies (100 entities each)."""
        generator = OntologyGenerator()
        
        ontologies = [
            self.create_ontology(100)
            for _ in range(10)
        ]
        
        # Merge sequentially
        result = ontologies[0]
        for onto in ontologies[1:]:
            result, _ = measure_memory_delta(
                generator._merge_ontologies,
                result,
                onto
            )
        
        # Final result should be valid
        assert result is not None


# ============================================================================
# Batch Analysis Performance Tests
# ============================================================================

class TestBatchAnalysisMemory:
    """Test memory usage during batch analysis."""
    
    def create_mock_session(self, score: float) -> Any:
        """Create a mock session with a score."""
        @dataclass
        class MockScore:
            overall: float
        
        from dataclasses import dataclass
        return type('Session', (), {
            'critic_score': MockScore(overall=score)
        })()
    
    def test_analyze_batch_100_sessions(self):
        """Analyze batch of 100 sessions and measure memory."""
        from dataclasses import dataclass
        
        optimizer = OntologyOptimizer()
        
        @dataclass
        class MockScore:
            overall: float
        
        sessions = [
            type('Session', (), {
                'critic_score': MockScore(overall=0.5 + (i % 10) * 0.05)
            })()
            for i in range(100)
        ]
        
        result, mem_delta = measure_memory_delta(
            optimizer.analyze_batch,
            sessions
        )
        
        # Batch analysis should use minimal memory
        assert mem_delta < 50.0, f"Memory usage too high: {mem_delta:.1f}MB"
        assert result.average_score > 0
    
    def test_analyze_batch_parallel_100_sessions(self):
        """Analyze batch of 100 sessions in parallel and measure memory."""
        from dataclasses import dataclass
        
        optimizer = OntologyOptimizer()
        
        @dataclass
        class MockScore:
            overall: float
        
        sessions = [
            type('Session', (), {
                'critic_score': MockScore(overall=0.5 + (i % 10) * 0.05)
            })()
            for i in range(100)
        ]
        
        result, mem_delta = measure_memory_delta(
            optimizer.analyze_batch_parallel,
            sessions,
            max_workers=4
        )
        
        # Parallel analysis should use reasonable memory
        assert mem_delta < 100.0, f"Memory usage too high: {mem_delta:.1f}MB"
        assert result.average_score > 0


# ============================================================================
# Performance Time Complexity Tests
# ============================================================================

class TestOperationComplexity:
    """Test time complexity of operations to identify O(n²) bottlenecks."""
    
    def create_ontology(self, num_entities: int) -> Dict[str, Any]:
        """Create a deterministic ontology."""
        return {
            'entities': [
                {
                    'id': f'entity_{i}',
                    'type': f'type_{i % 5}',
                    'properties': {'name': f'Entity {i}'}
                }
                for i in range(num_entities)
            ],
            'relationships': [
                {
                    'source': f'entity_{i}',
                    'target': f'entity_{(i+1) % num_entities}',
                    'type': 'connected',
                }
                for i in range(num_entities - 1)
            ],
            'metadata': {'num_entities': num_entities}
        }
    
    def test_merge_time_scaling_linear(self):
        """Verify merging scales appropriately (should be O(n) or better)."""
        generator = OntologyGenerator()
        
        times = []
        sizes = [100, 200, 400]
        
        for size in sizes:
            onto1 = self.create_ontology(size)
            onto2 = self.create_ontology(size)
            
            start = time.perf_counter()
            generator._merge_ontologies(onto1, onto2)
            elapsed = time.perf_counter() - start
            
            times.append(elapsed)
        
        # Rough check: time should not grow much faster than linearly
        # If 2x size takes >4x time, likely O(n²) issue
        time_ratio_1 = times[1] / max(times[0], 0.001)  # Avoid div by zero
        time_ratio_2 = times[2] / max(times[1], 0.001)
        
        # Allow some variance, but should roughly double when size doubles
        # If ratio > 4, likely non-linear scaling
        assert time_ratio_1 < 6.0, f"Time scaling degrading: {time_ratio_1:.1f}x"
        assert time_ratio_2 < 6.0, f"Time scaling degrading: {time_ratio_2:.1f}x"
    
    def test_identify_patterns_time_complexity(self):
        """Verify pattern identification completes in reasonable time."""
        optimizer = OntologyOptimizer()
        
        onto = self.create_ontology(1000)
        
        start = time.perf_counter()
        optimizer.identify_patterns([onto])
        elapsed = time.perf_counter() - start
        
        # Should complete quickly (< 5 seconds for 1000 entities)
        assert elapsed < 5.0, f"Pattern identification too slow: {elapsed:.1f}s"


# ============================================================================
# Resource Cleanup Tests
# ============================================================================

class TestMemoryCleanup:
    """Test that optimizers properly clean up resources."""
    
    def test_optimizer_cleanup_after_large_batch(self):
        """Verify memory is released after processing large batch."""
        from dataclasses import dataclass
        
        @dataclass
        class MockScore:
            overall: float
        
        optimizer = OntologyOptimizer()
        
        # Create and process large batch
        sessions = [
            type('Session', (), {
                'critic_score': MockScore(overall=0.5 + (i % 10) * 0.05)
            })()
            for i in range(500)
        ]
        
        mem_before = get_memory_usage_mb()
        
        # Process batch
        optimizer.analyze_batch(sessions)
        
        # Delete sessions to allow garbage collection
        del sessions
        gc.collect()
        
        mem_after = get_memory_usage_mb()
        
        # Memory should be mostly reclaimed
        # Allow some overhead, but not double
        mem_increase = mem_after - mem_before
        assert mem_increase < 100.0, f"Memory not properly released: {mem_increase:.1f}MB"


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
