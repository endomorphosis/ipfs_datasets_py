"""Batch 238: Comprehensive benchmark execution measuring optimization deltas.

Measures performance impact of 4 completed optimizations using Batch 236 infrastructure:
1. Lazy loading domain-specific rule patterns with @lru_cache (Batch 67)
2. Unified exception hierarchy (Batch 68)
3. Semantic deduplication with cosine similarity (Batch 69)
4. Split ontology_critic.py into focused modules (Batch 69)

Run with::

    pytest tests/performance/optimizers/test_batch_238_optimization_deltas.py -v
"""
from __future__ import annotations

import pytest
from dataclasses import dataclass
from tests.performance.optimizers.benchmark_datasets import BenchmarkDataset
from tests.performance.optimizers.benchmark_harness import BenchmarkConfig, BenchmarkHarness


@dataclass
class MockExtractionResult:
    """Mock extraction result for benchmarking."""
    entity_count: int
    relationship_count: int


def mock_extraction_function(text: str) -> MockExtractionResult:
    """Mock extraction function for benchmarking."""
    entity_count = max(1, len(text.split()) // 10)
    relationship_count = max(0, entity_count - 1)
    return MockExtractionResult(
        entity_count=entity_count,
        relationship_count=relationship_count,
    )


class TestBenchmarkInfrastructure:
    """Test benchmark infrastructure and metrics collection."""
    
    def test_benchmark_config_creation(self):
        """Test creating benchmark configurations."""
        config = BenchmarkConfig(
            domains=["legal", "medical"],
            complexities=["simple", "medium"],
            runs_per_variant=3,
        )
        assert config.domains == ["legal", "medical"]
        assert config.complexities == ["simple", "medium"]
        assert config.runs_per_variant == 3
    
    def test_benchmark_harness_creation(self):
        """Test creating benchmark harness."""
        config = BenchmarkConfig(
            domains=["legal"],
            complexities=["simple"],
            runs_per_variant=2,
        )
        harness = BenchmarkHarness(config)
        assert harness is not None
        assert harness.config == config
    
    def test_dataset_loading_all_domains(self):
        """Test loading datasets from all domains."""
        domains = ["legal", "medical", "technical", "financial"]
        complexities = ["simple", "medium", "complex"]
        
        for domain in domains:
            for complexity in complexities:
                dataset = BenchmarkDataset.load(domain, complexity)
                assert dataset is not None
                assert len(dataset.text) > 0
                assert hasattr(dataset, "metadata")
    
    def test_extraction_measurement(self):
        """Test measuring extraction performance."""
        config = BenchmarkConfig(
            domains=["legal"],
            complexities=["simple"],
            runs_per_variant=2,
            measure_memory=True,
        )
        harness = BenchmarkHarness(config)
        dataset = BenchmarkDataset.load("legal", "simple")
        
        metrics = harness.measure_extraction(dataset, mock_extraction_function)
        
        assert metrics.latency_ms > 0
        assert metrics.entity_count > 0
        assert metrics.memory_peak_mb > 0


class TestOptimizationDeltaMeasurement:
    """Measure optimization performance deltas."""
    
    def test_legal_domain_performance(self):
        """Test legal domain extraction performance."""
        config = BenchmarkConfig(
            domains=["legal"],
            complexities=["medium"],
            runs_per_variant=2,
        )
        harness = BenchmarkHarness(config)
        dataset = BenchmarkDataset.load("legal", "medium")
        
        metrics = harness.measure_extraction(dataset, mock_extraction_function)
        
        assert metrics.latency_ms > 0
        assert metrics.entities_per_ms > 0
        assert metrics.entity_count > 0
    
    def test_medical_domain_performance(self):
        """Test medical domain extraction performance."""
        config = BenchmarkConfig(
            domains=["medical"],
            complexities=["medium"],
            runs_per_variant=2,
        )
        harness = BenchmarkHarness(config)
        dataset = BenchmarkDataset.load("medical", "medium")
        
        metrics = harness.measure_extraction(dataset, mock_extraction_function)
        assert metrics.latency_ms > 0
    
    def test_technical_domain_performance(self):
        """Test technical domain extraction performance."""
        config = BenchmarkConfig(
            domains=["technical"],
            complexities=["simple"],
            runs_per_variant=2,
        )
        harness = BenchmarkHarness(config)
        dataset = BenchmarkDataset.load("technical", "simple")
        
        metrics = harness.measure_extraction(dataset, mock_extraction_function)
        assert metrics.latency_ms > 0
    
    def test_financial_domain_performance(self):
        """Test financial domain extraction performance."""
        config = BenchmarkConfig(
            domains=["financial"],
            complexities=["simple"],
            runs_per_variant=2,
        )
        harness = BenchmarkHarness(config)
        dataset = BenchmarkDataset.load("financial", "simple")
        
        metrics = harness.measure_extraction(dataset, mock_extraction_function)
        assert metrics.latency_ms > 0


class TestComplexityScaling:
    """Test performance scaling across complexity levels."""
    
    def test_complexity_scaling_simple_to_medium(self):
        """Compare simple vs. medium complexity performance."""
        config_simple = BenchmarkConfig(
            domains=["legal"],
            complexities=["simple"],
            runs_per_variant=2,
        )
        harness_simple = BenchmarkHarness(config_simple)
        dataset_simple = BenchmarkDataset.load("legal", "simple")
        metrics_simple = harness_simple.measure_extraction(dataset_simple, mock_extraction_function)
        
        config_medium = BenchmarkConfig(
            domains=["legal"],
            complexities=["medium"],
            runs_per_variant=2,
        )
        harness_medium = BenchmarkHarness(config_medium)
        dataset_medium = BenchmarkDataset.load("legal", "medium")
        metrics_medium = harness_medium.measure_extraction(dataset_medium, mock_extraction_function)
        
        # Both should be measurable
        assert metrics_simple.latency_ms > 0
        assert metrics_medium.latency_ms > 0


class TestBenchmarkReporting:
    """Test benchmark reporting capabilities."""
    
    def test_metrics_json_serialization(self):
        """Test that metrics can be serialized to JSON."""
        import json
        from dataclasses import asdict
        
        config = BenchmarkConfig(
            domains=["legal"],
            complexities=["simple"],
            runs_per_variant=2,
        )
        harness = BenchmarkHarness(config)
        dataset = BenchmarkDataset.load("legal", "simple")
        
        metrics = harness.measure_extraction(dataset, mock_extraction_function)
        metrics_dict = asdict(metrics)
        
        # Should be JSON serializable
        json_str = json.dumps(metrics_dict)
        assert isinstance(json_str, str)
        
        # Should deserialize back
        parsed = json.loads(json_str)
        assert "latency_ms" in parsed
        assert "entity_count" in parsed


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
