"""Tests for GraphRAG benchmark suite"""

import pytest
import time
from ipfs_datasets_py.optimizers.graphrag.benchmark_harness import (
    BenchmarkMetrics,
    BenchmarkDataset,
    BenchmarkRun,
    BenchmarkComparison,
    BenchmarkSuite,
    ExtractionStrategy,
    DataDomain,
)
from ipfs_datasets_py.optimizers.graphrag.benchmark_datasets import (
    LEGAL_CONTRACT_EXCERPT,
    LEGAL_LITIGATION_SUMMARY,
    MEDICAL_DIAGNOSIS_REPORT,
    MEDICAL_PATHOLOGY_REPORT,
    TECHNICAL_SOFTWARE_ARCHITECTURE,
    TECHNICAL_DATABASE_SCHEMA,
    GENERAL_NEWS_ARTICLE,
    GENERAL_BIOGRAPHY,
    get_all_datasets,
    get_datasets_by_domain,
)


# Fixtures

@pytest.fixture
def sample_metrics():
    """Create sample metrics for testing"""
    return BenchmarkMetrics(
        extraction_time_ms=100.5,
        evaluation_time_ms=50.3,
        optimization_time_ms=25.1,
        total_time_ms=175.9,
        entity_score=0.85,
        relationship_score=0.80,
        confidence_threshold=0.75,
        completeness_score=0.88,
        consistency_score=0.82,
        clarity_score=0.80,
        granularity_score=0.85,
        domain_alignment_score=0.83,
        strategy=ExtractionStrategy.HYBRID,
        domain=DataDomain.LEGAL,
        input_tokens=1000,
        extraction_tool="test_tool",
        critic_tool="test_critic",
    )


@pytest.fixture
def sample_run(sample_metrics):
    """Create sample benchmark run"""
    return BenchmarkRun(
        dataset=LEGAL_CONTRACT_EXCERPT,
        metrics=sample_metrics,
        quality_baseline=0.75,
    )


@pytest.fixture
def benchmark_suite():
    """Create benchmark suite with standard datasets"""
    suite = BenchmarkSuite()
    suite.add_dataset(LEGAL_CONTRACT_EXCERPT)
    suite.add_dataset(MEDICAL_DIAGNOSIS_REPORT)
    suite.add_dataset(TECHNICAL_SOFTWARE_ARCHITECTURE)
    suite.add_dataset(GENERAL_NEWS_ARTICLE)
    return suite


# Tests

class TestBenchmarkMetrics:
    """Test BenchmarkMetrics"""
    
    def test_metrics_creation(self, sample_metrics):
        """Test creating metrics"""
        assert sample_metrics.extraction_time_ms == 100.5
        assert sample_metrics.entity_score == 0.85
        assert sample_metrics.strategy == ExtractionStrategy.HYBRID
    
    def test_metrics_overall_score_computation(self, sample_metrics):
        """Test overall quality score computation"""
        # Score should be average of 5 dimension scores
        expected = (0.88 + 0.82 + 0.80 + 0.85 + 0.83) / 5
        assert abs(sample_metrics.overall_quality_score - expected) < 0.01
    
    def test_metrics_to_dict(self, sample_metrics):
        """Test converting metrics to dict"""
        metrics_dict = sample_metrics.to_dict()
        assert 'extraction_time_ms' in metrics_dict
        assert metrics_dict['entity_score'] == 0.85
        assert metrics_dict['overall_quality_score'] > 0
    
    def test_metrics_zero_confidence(self):
        """Test metrics with zero confidence"""
        metrics = BenchmarkMetrics(
            extraction_time_ms=100.0,
            evaluation_time_ms=50.0,
            optimization_time_ms=25.0,
            total_time_ms=175.0,
            entity_score=0.8,
            relationship_score=0.8,
            confidence_threshold=0.0,
            completeness_score=0.8,
            consistency_score=0.8,
            clarity_score=0.8,
            granularity_score=0.8,
            domain_alignment_score=0.8,
            strategy=ExtractionStrategy.RULE_BASED,
            domain=DataDomain.MEDICAL,
            input_tokens=500,
            extraction_tool="test",
            critic_tool="test",
        )
        assert metrics.overall_quality_score > 0


class TestBenchmarkDataset:
    """Test BenchmarkDataset"""
    
    def test_dataset_creation(self):
        """Test creating dataset"""
        texts = ["Text 1", "Text 2"]
        dataset = BenchmarkDataset(
            domain=DataDomain.LEGAL,
            name="Test Dataset",
            description="Test Description",
            texts=texts,
            expected_entity_count=5,
            expected_relationship_count=3,
            quality_baseline=0.75,
        )
        assert dataset.name == "Test Dataset"
        assert dataset.expected_entity_count == 5
    
    def test_dataset_text_length(self):
        """Test dataset text length calculation"""
        texts = ["Hello", "World"]
        dataset = BenchmarkDataset(
            domain=DataDomain.TECHNICAL,
            name="Test",
            description="Test",
            texts=texts,
            expected_entity_count=2,
            expected_relationship_count=1,
            quality_baseline=0.70,
        )
        assert dataset.text_length_tokens > 0
    
    def test_get_all_datasets(self):
        """Test getting all datasets"""
        datasets = get_all_datasets()
        assert len(datasets) == 8
        assert all(isinstance(d, BenchmarkDataset) for d in datasets)
    
    def test_get_datasets_by_domain(self):
        """Test filtering datasets by domain"""
        legal_datasets = get_datasets_by_domain(DataDomain.LEGAL)
        assert len(legal_datasets) == 2
        assert all(d.domain == DataDomain.LEGAL for d in legal_datasets)


class TestBenchmarkRun:
    """Test BenchmarkRun"""
    
    def test_run_creation(self, sample_run):
        """Test creating benchmark run"""
        assert sample_run.dataset.name == LEGAL_CONTRACT_EXCERPT.name
        assert sample_run.quality_baseline == 0.75
    
    def test_meets_quality_baseline_true(self):
        """Test baseline check when passing"""
        metrics = BenchmarkMetrics(
            extraction_time_ms=100.0,
            evaluation_time_ms=50.0,
            optimization_time_ms=25.0,
            total_time_ms=175.0,
            entity_score=0.85,
            relationship_score=0.80,
            confidence_threshold=0.75,
            completeness_score=0.85,
            consistency_score=0.85,
            clarity_score=0.85,
            granularity_score=0.85,
            domain_alignment_score=0.85,
            strategy=ExtractionStrategy.HYBRID,
            domain=DataDomain.LEGAL,
            input_tokens=1000,
            extraction_tool="test",
            critic_tool="test",
        )
        run = BenchmarkRun(
            dataset=LEGAL_CONTRACT_EXCERPT,
            metrics=metrics,
            quality_baseline=0.75,
        )
        assert run.meets_quality_baseline()
    
    def test_meets_quality_baseline_false(self):
        """Test baseline check when failing"""
        metrics = BenchmarkMetrics(
            extraction_time_ms=100.0,
            evaluation_time_ms=50.0,
            optimization_time_ms=25.0,
            total_time_ms=175.0,
            entity_score=0.60,
            relationship_score=0.60,
            confidence_threshold=0.60,
            completeness_score=0.60,
            consistency_score=0.60,
            clarity_score=0.60,
            granularity_score=0.60,
            domain_alignment_score=0.60,
            strategy=ExtractionStrategy.RULE_BASED,
            domain=DataDomain.MEDICAL,
            input_tokens=500,
            extraction_tool="test",
            critic_tool="test",
        )
        run = BenchmarkRun(
            dataset=MEDICAL_DIAGNOSIS_REPORT,
            metrics=metrics,
            quality_baseline=0.80,
        )
        assert not run.meets_quality_baseline()


class TestBenchmarkComparison:
    """Test BenchmarkComparison"""
    
    def test_comparison_requirements(self):
        """Test comparison requires runs"""
        runs = []
        comparison = BenchmarkComparison(runs=runs)
        assert len(comparison.runs) == 0
    
    def test_comparison_statistics(self):
        """Test statistical calculations"""
        metrics1 = BenchmarkMetrics(
            extraction_time_ms=100.0, evaluation_time_ms=50.0, optimization_time_ms=25.0, total_time_ms=175.0,
            entity_score=0.80, relationship_score=0.80, confidence_threshold=0.75,
            completeness_score=0.80, consistency_score=0.80, clarity_score=0.80, granularity_score=0.80, domain_alignment_score=0.80,
            strategy=ExtractionStrategy.HYBRID, domain=DataDomain.LEGAL, input_tokens=1000,
            extraction_tool="test", critic_tool="test",
        )
        metrics2 = BenchmarkMetrics(
            extraction_time_ms=90.0, evaluation_time_ms=45.0, optimization_time_ms=20.0, total_time_ms=155.0,
            entity_score=0.75, relationship_score=0.75, confidence_threshold=0.70,
            completeness_score=0.75, consistency_score=0.75, clarity_score=0.75, granularity_score=0.75, domain_alignment_score=0.75,
            strategy=ExtractionStrategy.LLM_FALLBACK, domain=DataDomain.MEDICAL, input_tokens=800,
            extraction_tool="test", critic_tool="test",
        )
        run1 = BenchmarkRun(dataset=LEGAL_CONTRACT_EXCERPT, metrics=metrics1, quality_baseline=0.75)
        run2 = BenchmarkRun(dataset=MEDICAL_DIAGNOSIS_REPORT, metrics=metrics2, quality_baseline=0.70)
        comparison = BenchmarkComparison(runs=[run1, run2])
        
        assert comparison.mean_extraction_time > 0
        assert comparison.min_entity_score <= comparison.max_entity_score
    
    def test_comparison_best_worst(self):
        """Test best/worst selection"""
        metrics_good = BenchmarkMetrics(
            extraction_time_ms=100.0, evaluation_time_ms=50.0, optimization_time_ms=25.0, total_time_ms=175.0,
            entity_score=0.90, relationship_score=0.90, confidence_threshold=0.90,
            completeness_score=0.90, consistency_score=0.90, clarity_score=0.90, granularity_score=0.90, domain_alignment_score=0.90,
            strategy=ExtractionStrategy.HYBRID, domain=DataDomain.LEGAL, input_tokens=1000,
            extraction_tool="test", critic_tool="test",
        )
        metrics_bad = BenchmarkMetrics(
            extraction_time_ms=100.0, evaluation_time_ms=50.0, optimization_time_ms=25.0, total_time_ms=175.0,
            entity_score=0.50, relationship_score=0.50, confidence_threshold=0.50,
            completeness_score=0.50, consistency_score=0.50, clarity_score=0.50, granularity_score=0.50, domain_alignment_score=0.50,
            strategy=ExtractionStrategy.RULE_BASED, domain=DataDomain.MEDICAL, input_tokens=500,
            extraction_tool="test", critic_tool="test",
        )
        run_good = BenchmarkRun(dataset=LEGAL_CONTRACT_EXCERPT, metrics=metrics_good, quality_baseline=0.75)
        run_bad = BenchmarkRun(dataset=MEDICAL_DIAGNOSIS_REPORT, metrics=metrics_bad, quality_baseline=0.70)
        comparison = BenchmarkComparison(runs=[run_good, run_bad])
        
        best = comparison.best_run
        worst = comparison.worst_run
        assert best.metrics.overall_quality_score > worst.metrics.overall_quality_score


class TestBenchmarkSuite:
    """Test BenchmarkSuite"""
    
    def test_suite_creation(self, benchmark_suite):
        """Test creating suite with datasets"""
        assert len(benchmark_suite.datasets) == 4
        assert len(benchmark_suite.runs) == 0
    
    def test_suite_add_dataset(self, benchmark_suite):
        """Test adding dataset to suite"""
        original_count = len(benchmark_suite.datasets)
        benchmark_suite.add_dataset(LEGAL_LITIGATION_SUMMARY)
        assert len(benchmark_suite.datasets) == original_count + 1
    
    def test_suite_run_benchmark(self, benchmark_suite):
        """Test running a single benchmark"""
        def mock_extractor(texts):
            return {
                'entities': [
                    {'id': '1', 'text': 'test', 'confidence': 0.8},
                    {'id': '2', 'text': 'entity', 'confidence': 0.75}
                ],
                'relationships': [
                    {'source_id': '1', 'target_id': '2', 'type': 'relates_to', 'confidence': 0.7}
                ]
            }
        
        def mock_critic(entities, relationships):
            return {
                'completeness': 0.85,
                'consistency': 0.82,
                'clarity': 0.80,
                'granularity': 0.85,
                'domain_alignment': 0.83,
            }
        
        dataset = benchmark_suite.datasets[0]
        benchmark_suite.run_benchmark(
            dataset=dataset,
            extractor=mock_extractor,
            critic=mock_critic,
            strategy=ExtractionStrategy.HYBRID,
        )
        assert len(benchmark_suite.runs) > 0
    
    def test_suite_compare_strategies(self, benchmark_suite):
        """Test strategy comparison"""
        def mock_extractor(texts):
            return {
                'entities': [{'id': '1', 'text': 'test', 'confidence': 0.8}],
                'relationships': []
            }
        
        def mock_critic(entities, relationships):
            return {
                'completeness': 0.8, 'consistency': 0.8,
                'clarity': 0.8, 'granularity': 0.8, 'domain_alignment': 0.8,
            }
        
        for strategy in [ExtractionStrategy.RULE_BASED, ExtractionStrategy.LLM_FALLBACK]:
            benchmark_suite.run_benchmark(
                dataset=benchmark_suite.datasets[0],
                extractor=mock_extractor,
                critic=mock_critic,
                strategy=strategy,
            )
        
        comparison = benchmark_suite.get_comparison()
        assert comparison is not None
    
    def test_suite_compare_domains(self, benchmark_suite):
        """Test domain comparison"""
        def mock_extractor(texts):
            return {
                'entities': [{'id': '1', 'text': 'test', 'confidence': 0.8}],
                'relationships': []
            }
        
        def mock_critic(entities, relationships):
            return {
                'completeness': 0.8, 'consistency': 0.8,
                'clarity': 0.8, 'granularity': 0.8, 'domain_alignment': 0.8,
            }
        
        for dataset in benchmark_suite.datasets:
            benchmark_suite.run_benchmark(
                dataset=dataset,
                extractor=mock_extractor,
                critic=mock_critic,
                strategy=ExtractionStrategy.HYBRID,
            )
        
        comparison = benchmark_suite.get_comparison()
        assert comparison is not None
    
    def test_suite_get_summary(self, benchmark_suite):
        """Test suite summary"""
        def mock_extractor(texts):
            return {'entities': [], 'relationships': []}
        
        def mock_critic(entities, relationships):
            return {
                'completeness': 0.8, 'consistency': 0.8,
                'clarity': 0.8, 'granularity': 0.8, 'domain_alignment': 0.8,
            }
        
        benchmark_suite.run_benchmark(
            dataset=benchmark_suite.datasets[0],
            extractor=mock_extractor,
            critic=mock_critic,
            strategy=ExtractionStrategy.HYBRID,
        )
        
        summary = benchmark_suite.get_summary()
        assert 'datasets' in summary
        assert 'runs' in summary


class TestBenchmarkDatasets:
    """Test standard datasets"""
    
    def test_datasets_exist(self):
        """Test all datasets are available"""
        datasets = [
            LEGAL_CONTRACT_EXCERPT,
            LEGAL_LITIGATION_SUMMARY,
            MEDICAL_DIAGNOSIS_REPORT,
            MEDICAL_PATHOLOGY_REPORT,
            TECHNICAL_SOFTWARE_ARCHITECTURE,
            TECHNICAL_DATABASE_SCHEMA,
            GENERAL_NEWS_ARTICLE,
            GENERAL_BIOGRAPHY,
        ]
        assert len(datasets) == 8
        assert all(isinstance(d, BenchmarkDataset) for d in datasets)
    
    def test_datasets_domain_filter(self):
        """Test domain filtering"""
        legal = get_datasets_by_domain(DataDomain.LEGAL)
        medical = get_datasets_by_domain(DataDomain.MEDICAL)
        technical = get_datasets_by_domain(DataDomain.TECHNICAL)
        general = get_datasets_by_domain(DataDomain.GENERAL)
        
        assert len(legal) == 2
        assert len(medical) == 2
        assert len(technical) == 2
        assert len(general) == 2
    
    def test_datasets_baseline_validation(self):
        """Test baseline quality scores"""
        datasets = get_all_datasets()
        for dataset in datasets:
            assert 0.6 <= dataset.quality_baseline <= 0.8
    
    def test_datasets_text_quality(self):
        """Test dataset text content"""
        datasets = get_all_datasets()
        for dataset in datasets:
            assert len(dataset.texts) > 0
            assert all(isinstance(text, str) for text in dataset.texts)
            # Verify realistic text lengths (250+ tokens minimum for domain-specific content)
            assert dataset.text_length_tokens >= 250


class TestBenchmarkIntegration:
    """Integration tests"""
    
    def test_full_benchmark_workflow(self):
        """Test full benchmarking workflow"""
        suite = BenchmarkSuite()
        suite.add_dataset(LEGAL_CONTRACT_EXCERPT)
        suite.add_dataset(MEDICAL_DIAGNOSIS_REPORT)
        
        def mock_extractor(texts):
            return {
                'entities': [{'id': '1', 'text': 'test', 'confidence': 0.85}],
                'relationships': [{'source_id': '1', 'target_id': '1', 'type': 'relates_to', 'confidence': 0.8}]
            }
        
        def mock_critic(entities, relationships):
            return {
                'completeness': 0.82,
                'consistency': 0.80,
                'clarity': 0.78,
                'granularity': 0.81,
                'domain_alignment': 0.79,
            }
        
        # Run benchmarks
        for dataset in suite.datasets:
            suite.run_benchmark(
                dataset=dataset,
                extractor=mock_extractor,
                critic=mock_critic,
                strategy=ExtractionStrategy.HYBRID,
            )
        
        # Verify runs completed
        assert len(suite.runs) == 2
        
        # Get comparison
        comparison = suite.get_comparison()
        assert comparison is not None
        assert len(comparison.runs) == 2
        
        # Get summary
        summary = suite.get_summary()
        assert summary['datasets'] == 2
        assert summary['runs'] == 2
        
        # Verify export
        export_data = suite.export_json()
        assert export_data is not None
