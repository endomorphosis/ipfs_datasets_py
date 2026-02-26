"""Integration tests using the GraphRAG benchmark suite.

Tests verify:
- Benchmark suite functionality
- Performance metrics collection
- Results serialization and persistence
- Regression detection capabilities
"""

import pytest
import json
import tempfile
from pathlib import Path
from ipfs_datasets_py.optimizers.tests.unit.optimizers.graphrag.bench_graphrag import (
    BenchmarkConfig,
    GraphRAGBenchmarkSuite,
    TimingStats,
    MemoryStats,
    BenchmarkResult,
)


class TestBenchmarkConfiguration:
    """Test benchmark configuration options."""
    
    def test_default_config(self):
        """Test default configuration."""
        config = BenchmarkConfig()
        
        assert config.iterations == 3
        assert len(config.data_sizes) > 0
        assert config.enable_entity_extraction is True
        assert config.enable_memory_profiling is True
    
    def test_custom_config(self):
        """Test custom configuration."""
        config = BenchmarkConfig(
            data_sizes=[100, 1000],
            iterations=2,
            enable_memory_profiling=False,
        )
        
        assert config.data_sizes == [100, 1000]
        assert config.iterations == 2
        assert config.enable_memory_profiling is False
    
    def test_regression_thresholds(self):
        """Test regression detection thresholds."""
        config = BenchmarkConfig(regression_threshold_percent=20.0)
        
        assert config.regression_threshold_percent == 20.0


class TestTimingStats:
    """Test timing statistics collection."""
    
    def test_timing_stats_creation(self):
        """Test creating timing statistics."""
        stats = TimingStats(
            operation="entity_extraction",
            min_ms=10.5,
            max_ms=15.3,
            mean_ms=12.1,
            median_ms=11.8,
            stdev_ms=1.2,
            throughput_per_sec=100.5,
        )
        
        assert stats.operation == "entity_extraction"
        assert stats.mean_ms == 12.1
        assert stats.throughput_per_sec == 100.5
    
    def test_timing_stats_dict(self):
        """Test converting timing stats to dictionary."""
        stats = TimingStats(
            operation="test",
            mean_ms=10.0,
            throughput_per_sec=50.0,
        )
        
        d = stats.to_dict()
        assert isinstance(d, dict)
        assert d["operation"] == "test"
        assert d["mean_ms"] == 10.0
        assert d["throughput_per_sec"] == 50.0


class TestBenchmarkResult:
    """Test benchmark result creation."""
    
    def test_result_with_timing_only(self):
        """Test creating result with timing data."""
        timing = TimingStats(operation="test", mean_ms=10.0)
        result = BenchmarkResult(
            data_size_tokens=1000,
            operation="test",
            timing=timing,
        )
        
        assert result.data_size_tokens == 1000
        assert result.operation == "test"
        assert result.timing.mean_ms == 10.0
        assert result.memory is None
    
    def test_result_with_memory(self):
        """Test creating result with memory data."""
        timing = TimingStats(operation="test", mean_ms=10.0)
        memory = MemoryStats(operation="test", peak_mb=50.0)
        result = BenchmarkResult(
            data_size_tokens=1000,
            operation="test",
            timing=timing,
            memory=memory,
        )
        
        assert result.memory is not None
        assert result.memory.peak_mb == 50.0


class TestGraphRAGBenchmarkSuite:
    """Test the benchmark suite functionality."""
    
    def test_suite_initialization(self):
        """Test initializing benchmark suite."""
        config = BenchmarkConfig(
            data_sizes=[100, 500],
            iterations=2,
        )
        suite = GraphRAGBenchmarkSuite(config)
        
        assert suite.config == config
        assert len(suite.results) == 0
    
    def test_suite_default_config(self):
        """Test suite with default configuration."""
        suite = GraphRAGBenchmarkSuite()
        
        assert suite.config is not None
        assert len(suite.config.data_sizes) > 0
    
    def test_entity_extraction_benchmark(self):
        """Test entity extraction benchmark."""
        config = BenchmarkConfig(
            data_sizes=[100, 200],
            iterations=2,
            enable_memory_profiling=False,
            enable_relationship_detection=False,
            enable_confidence_scoring=False,
            enable_pipeline_throughput=False,
        )
        suite = GraphRAGBenchmarkSuite(config)
        
        results = suite.run_full_benchmark()
        
        assert "entity_extraction" in results
        assert len(results["entity_extraction"]) == 2  # One per data size
        
        # Check result properties
        for result in results["entity_extraction"]:
            assert result.operation == "entity_extraction"
            assert result.timing.mean_ms > 0
            assert result.timing.min_ms > 0
            assert result.timing.max_ms >= result.timing.mean_ms
            assert result.timing.throughput_per_sec > 0
    
    def test_relationship_detection_benchmark(self):
        """Test relationship detection benchmark."""
        config = BenchmarkConfig(
            data_sizes=[100],
            iterations=1,
            enable_entity_extraction=False,
            enable_confidence_scoring=False,
            enable_pipeline_throughput=False,
        )
        suite = GraphRAGBenchmarkSuite(config)
        
        results = suite.run_full_benchmark()
        
        assert "relationship_detection" in results
        assert len(results["relationship_detection"]) == 1
    
    def test_confidence_scoring_benchmark(self):
        """Test confidence scoring benchmark."""
        config = BenchmarkConfig(
            data_sizes=[100],
            iterations=1,
            enable_entity_extraction=False,
            enable_relationship_detection=False,
            enable_pipeline_throughput=False,
        )
        suite = GraphRAGBenchmarkSuite(config)
        
        results = suite.run_full_benchmark()
        
        assert "confidence_scoring" in results
        assert len(results["confidence_scoring"]) > 0
    
    def test_pipeline_throughput_benchmark(self):
        """Test pipeline throughput benchmark."""
        config = BenchmarkConfig(
            data_sizes=[100, 200],
            iterations=1,
            enable_entity_extraction=False,
            enable_relationship_detection=False,
            enable_confidence_scoring=False,
        )
        suite = GraphRAGBenchmarkSuite(config)
        
        results = suite.run_full_benchmark()
        
        assert "pipeline_throughput" in results
        assert len(results["pipeline_throughput"]) == 2
        
        # Check metadata
        for result in results["pipeline_throughput"]:
            assert "entities" in result.metadata
            assert "relationships" in result.metadata
            assert "throughput_tokens_per_sec" in result.metadata
    
    def test_full_benchmark(self):
        """Test running full benchmark with all operations."""
        config = BenchmarkConfig(
            data_sizes=[100, 200],
            iterations=1,
        )
        suite = GraphRAGBenchmarkSuite(config)
        
        results = suite.run_full_benchmark()
        
        # Should have results for all enabled operations
        assert "entity_extraction" in results
        assert "relationship_detection" in results
        assert "confidence_scoring" in results
        assert "pipeline_throughput" in results
        
        # Total results should be aggregated
        assert len(suite.results) > 0
    
    def test_results_json_export(self):
        """Test exporting benchmark results to JSON."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = BenchmarkConfig(
                data_sizes=[100],
                iterations=1,
                results_dir=tmpdir,
                enable_relationship_detection=False,
                enable_confidence_scoring=False,
                enable_pipeline_throughput=False,
            )
            suite = GraphRAGBenchmarkSuite(config)
            
            # Run benchmark
            suite.run_full_benchmark()
            
            # Export to JSON
            output_file = suite.save_results_json("test_results.json")
            
            # Verify file exists and is valid JSON
            assert Path(output_file).exists()
            
            with open(output_file) as f:
                data = json.load(f)
            
            assert "timestamp" in data
            assert "config" in data
            assert "results" in data
            assert len(data["results"]) > 0
            
            # Verify result structure
            result = data["results"][0]
            assert "data_size_tokens" in result
            assert "operation" in result
            assert "timing" in result
            assert result["timing"]["mean_ms"] > 0
    
    def test_memory_profiling_optional(self):
        """Test that memory profiling is optional."""
        config = BenchmarkConfig(
            data_sizes=[100],
            iterations=1,
            enable_memory_profiling=False,
            enable_relationship_detection=False,
            enable_confidence_scoring=False,
            enable_pipeline_throughput=False,
        )
        suite = GraphRAGBenchmarkSuite(config)
        
        results = suite.run_full_benchmark()
        
        # Results should exist even without memory profiling
        assert "entity_extraction" in results
        for result in results["entity_extraction"]:
            # Memory might be None since profiling is disabled
            # But timing should always be present
            assert result.timing is not None
            assert result.timing.mean_ms > 0


class TestPerformanceRegression:
    """Test regression detection capabilities."""
    
    def test_regression_detection_threshold(self):
        """Test detecting performance regression."""
        config = BenchmarkConfig(
            regression_threshold_percent=20.0
        )
        
        # Simulate baseline and regression
        baseline_ms = 100.0
        regressed_ms = 125.0  # 25% slower - exceeds 20% threshold
        
        percent_change = ((regressed_ms - baseline_ms) / baseline_ms) * 100
        
        assert percent_change > config.regression_threshold_percent
    
    def test_no_regression_within_threshold(self):
        """Test that small changes don't trigger regression."""
        config = BenchmarkConfig(
            regression_threshold_percent=20.0
        )
        
        baseline_ms = 100.0
        improved_ms = 110.0  # 10% slower - within threshold
        
        percent_change = ((improved_ms - baseline_ms) / baseline_ms) * 100
        
        assert percent_change <= config.regression_threshold_percent


class TestBenchmarkConsoleOutput:
    """Test console output formatting."""
    
    def test_summary_printing(self, capsys):
        """Test that summary can be printed without errors."""
        config = BenchmarkConfig(
            data_sizes=[100],
            iterations=1,
            enable_relationship_detection=False,
            enable_confidence_scoring=False,
            enable_pipeline_throughput=False,
        )
        suite = GraphRAGBenchmarkSuite(config)
        
        results = suite.run_full_benchmark()
        suite.print_summary(results)
        
        captured = capsys.readouterr()
        assert "entity" in captured.out.lower()
        assert "throughput" in captured.out.lower()
