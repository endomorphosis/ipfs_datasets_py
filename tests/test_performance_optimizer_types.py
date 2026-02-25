"""
Comprehensive tests for performance_optimizer.py TypedDict contracts.

Tests validate:
1. TypedDict structure and field presence
2. Return type contracts for optimization methods
3. Resource monitoring and prediction accuracy
4. Cache strategy optimization
5. Performance analysis and recommendations
6. Type contract data flow integration
"""

import pytest
import asyncio
import psutil
from datetime import datetime, timedelta
from typing import Dict, Any, List

from ipfs_datasets_py.optimizers.performance_optimizer import (
    ContentCacheManager,
    ResourceMonitor,
    WebsiteProcessingOptimizer,
    CachePoliciesDict,
    ResourceUtilizationDict,
    ResourcePredictionDict,
    ContentComplexityAnalysisDict,
    CacheOptimizationStrategyDict,
    OptimizationRecommendationsDict,
    PerformanceAnalysisDict,
    ProcessingMetrics,
    OptimizedProcessingPlan,
)
from ipfs_datasets_py.content_discovery import ContentAsset, ContentManifest


class TestCachePoliciesDictType:
    """Validate CachePoliciesDict structure and content"""
    
    def test_cache_policies_has_all_required_fields(self):
        """Verify CachePoliciesDict contains expected TTL fields"""
        cache_mgr = ContentCacheManager()
        policies = cache_mgr._get_default_policies()
        
        assert 'html_content_ttl' in policies
        assert 'pdf_content_ttl' in policies
        assert 'media_transcripts_ttl' in policies
        assert 'embeddings_ttl' in policies
        assert 'max_cache_size_gb' in policies
    
    def test_cache_policies_values_are_correct_types(self):
        """Verify CachePoliciesDict values are integers"""
        cache_mgr = ContentCacheManager()
        policies = cache_mgr._get_default_policies()
        
        assert isinstance(policies['html_content_ttl'], int)
        assert isinstance(policies['pdf_content_ttl'], int)
        assert isinstance(policies['max_cache_size_gb'], int)
        assert all(isinstance(v, int) for v in policies.values())


class TestResourceUtilizationDictType:
    """Validate ResourceUtilizationDict structure"""
    
    @pytest.mark.asyncio
    async def test_resource_utilization_dict_has_cpu_Memory_fields(self):
        """Verify ResourceUtilizationDict contains CPU and memory metrics"""
        monitor = ResourceMonitor()
        resources = await monitor.get_current_resources()
        
        assert 'cpu_percent' in resources
        assert 'memory_percent' in resources
        assert 'available_memory_gb' in resources
        assert 'disk_usage_percent' in resources
        assert 'timestamp' in resources
    
    @pytest.mark.asyncio
    async def test_resource_utilization_dict_numeric_values_in_range(self):
        """Verify CPU and memory percentages are valid ranges"""
        monitor = ResourceMonitor()
        resources = await monitor.get_current_resources()
        
        assert 0 <= resources['cpu_percent'] <= 100
        assert 0 <= resources['memory_percent'] <= 100
        assert resources['available_memory_gb'] >= 0
        assert isinstance(resources['disk_free_gb'], float)
    
    @pytest.mark.asyncio
    async def test_resource_utilization_dict_has_backwards_compat_aliases(self):
        """Verify backwards compatible field aliases exist"""
        monitor = ResourceMonitor()
        resources = await monitor.get_current_resources()
        
        # Should have both original and alias fields
        assert 'available_memory_gb' in resources
        assert 'memory_available_gb' in resources
        assert 'disk_percent' in resources
        assert 'disk_usage_percent' in resources


class TestResourcePredictionDictType:
    """Validate ResourcePredictionDict structure"""
    
    @pytest.mark.asyncio
    async def test_resource_prediction_dict_structure(self):
        """Verify ResourcePredictionDict has required fields"""
        monitor = ResourceMonitor()
        prediction = await monitor.predict_resource_usage({
            'html_processing': 10,
            'pdf_processing': 5,
            'media_processing': 2
        })
        
        assert 'cpu_percent' in prediction
        assert 'memory_gb' in prediction
        assert 'processing_time_minutes' in prediction
    
    @pytest.mark.asyncio
    async def test_resource_prediction_values_are_numeric(self):
        """Verify all prediction values are numeric"""
        monitor = ResourceMonitor()
        prediction = await monitor.predict_resource_usage({
            'html_processing': 20,
            'pdf_processing': 10
        })
        
        assert isinstance(prediction['cpu_percent'], (int, float))
        assert isinstance(prediction['memory_gb'], (int, float))
        assert isinstance(prediction['processing_time_minutes'], (int, float))
        assert all(v >= 0 for v in prediction.values())


class TestContentComplexityAnalysisDictType:
    """Validate ContentComplexityAnalysisDict structure"""
    
    def test_complexity_analysis_contains_required_metrics(self):
        """Verify ContentComplexityAnalysisDict has all complexity metrics"""
        optimizer = WebsiteProcessingOptimizer()
        manifest = self._create_test_manifest()
        
        analysis = optimizer._analyze_content_complexity(manifest)
        
        assert 'html_complexity' in analysis
        assert 'pdf_complexity' in analysis
        assert 'media_complexity' in analysis
        assert 'total_size_mb' in analysis
        assert 'estimated_processing_difficulty' in analysis
    
    def test_complexity_analysis_values_are_numeric(self):
        """Verify complexity values are numeric and in valid ranges"""
        optimizer = WebsiteProcessingOptimizer()
        manifest = self._create_test_manifest()
        
        analysis = optimizer._analyze_content_complexity(manifest)
        
        assert isinstance(analysis['html_complexity'], (int, float))
        assert isinstance(analysis['pdf_complexity'], (int, float))
        assert isinstance(analysis['total_size_mb'], (int, float))
        assert isinstance(analysis['estimated_processing_difficulty'], (int, float))
        assert 0 <= analysis['estimated_processing_difficulty'] <= 100
    
    @staticmethod
    def _create_test_manifest() -> ContentManifest:
        """Helper to create test content manifest"""
        return ContentManifest(
            base_url="https://example.com",
            html_pages=[ContentAsset("https://example.com/page1", "page", "text/html", 10 * 1024)],
            pdf_documents=[ContentAsset("https://example.com/doc1.pdf", "doc", "application/pdf", 1024 * 1024)],
            media_files=[ContentAsset("https://example.com/video1.mp4", "video", "video/mp4", 50 * 1024 * 1024)],
            structured_data=[],
            total_assets=3,
            discovery_timestamp=datetime.now()
        )


class TestCacheOptimizationStrategyDictType:
    """Validate CacheOptimizationStrategyDict structure"""
    
    def test_cache_optimization_strategy_dict_structure(self):
        """Verify CacheOptimizationStrategyDict has expected fields"""
        optimizer = WebsiteProcessingOptimizer()
        manifest = self._create_test_manifest()
        
        strategy = optimizer._optimize_cache_usage(manifest)
        
        assert 'priorities' in strategy
        assert 'max_cache_items' in strategy
        assert 'cache_compression' in strategy
        assert 'distributed_cache' in strategy
    
    def test_cache_priorities_dict_structure(self):
        """Verify priorities sub-dict has content type entries"""
        optimizer = WebsiteProcessingOptimizer()
        manifest = self._create_test_manifest()
        
        strategy = optimizer._optimize_cache_usage(manifest)
        priorities = strategy['priorities']
        
        assert isinstance(priorities, dict)
        assert 'embeddings' in priorities
        assert 'processed_text' in priorities
        assert 'media_transcripts' in priorities
    
    def test_cache_strategy_constraint_values(self):
        """Verify constraint values are valid types"""
        optimizer = WebsiteProcessingOptimizer()
        manifest = self._create_test_manifest()
        
        strategy = optimizer._optimize_cache_usage(manifest)
        
        assert isinstance(strategy['max_cache_items'], int)
        assert isinstance(strategy['cache_compression'], bool)
        assert isinstance(strategy['distributed_cache'], bool)
    
    @staticmethod
    def _create_test_manifest() -> ContentManifest:
        """Helper to create test content manifest"""
        return ContentManifest(
            base_url="https://example.com",
            html_pages=[ContentAsset(f"https://example.com/page{i}", "page", "text/html", 10 * 1024)
                       for i in range(50)],
            pdf_documents=[ContentAsset("https://example.com/doc1.pdf", "doc", "application/pdf", 1024 * 1024)],
            media_files=[ContentAsset("https://example.com/video1.mp4", "video", "video/mp4", 50 * 1024 * 1024)],
            structured_data=[],
            total_assets=52,
            discovery_timestamp=datetime.now()
        )


class TestOptimizationRecommendationsDictType:
    """Validate OptimizationRecommendationsDict structure"""
    
    @pytest.mark.asyncio
    async def test_optimization_recommendations_dict_structure(self):
        """Verify OptimizationRecommendationsDict has expected fields"""
        optimizer = WebsiteProcessingOptimizer()
        recommendations = await optimizer.get_optimization_recommendations()
        
        assert 'strategy' in recommendations
        assert 'batch_size' in recommendations
        assert 'parallel_workers' in recommendations
    
    @pytest.mark.asyncio
    async def test_optimization_recommendations_valid_strategy_values(self):
        """Verify strategy field has valid values"""
        optimizer = WebsiteProcessingOptimizer()
        recommendations = await optimizer.get_optimization_recommendations()
        
        assert recommendations['strategy'] in ['fast', 'balanced', 'comprehensive']
        assert isinstance(recommendations['batch_size'], int)
        assert isinstance(recommendations['parallel_workers'], int)
    
    @pytest.mark.asyncio
    async def test_optimization_recommendations_constraint_values(self):
        """Verify constraint values are within valid ranges"""
        optimizer = WebsiteProcessingOptimizer()
        recommendations = await optimizer.get_optimization_recommendations()
        
        assert recommendations['batch_size'] > 0
        assert recommendations['parallel_workers'] > 0
        assert recommendations['parallel_workers'] <= 10


class TestPerformanceAnalysisDictType:
    """Validate PerformanceAnalysisDict structure"""
    
    @pytest.mark.asyncio
    async def test_performance_analysis_dict_structure(self):
        """Verify PerformanceAnalysisDict has required fields"""
        optimizer = WebsiteProcessingOptimizer()
        
        # Create mock plan and metrics
        plan = self._create_mock_plan()
        metrics = ProcessingMetrics(
            total_items=100,
            processing_time_seconds=300,
            memory_peak_gb=4.5,
            cpu_usage_percent=75,
            success_rate=0.98,
            errors=[]
        )
        
        analysis = await optimizer.monitor_processing_performance(plan, metrics)
        
        assert 'plan_vs_actual' in analysis
        assert 'recommendations' in analysis
    
    @pytest.mark.asyncio
    async def test_performance_analysis_comparisons_numeric(self):
        """Verify performance comparison values are numeric"""
        optimizer = WebsiteProcessingOptimizer()
        
        plan = self._create_mock_plan()
        metrics = ProcessingMetrics(
            total_items=50,
            processing_time_seconds=120,
            memory_peak_gb=2.0,
            cpu_usage_percent=60,
            success_rate=0.99,
            errors=[]
        )
        
        analysis = await optimizer.monitor_processing_performance(plan, metrics)
        comparison = analysis['plan_vs_actual']
        
        assert isinstance(comparison['estimated_time'], (int, float))
        assert isinstance(comparison['actual_time'], (int, float))
        assert isinstance(comparison['time_accuracy'], (int, float))
    
    @pytest.mark.asyncio
    async def test_performance_recommendations_are_strings(self):
        """Verify recommendations list contains string messages"""
        optimizer = WebsiteProcessingOptimizer()
        
        plan = self._create_mock_plan()
        metrics = ProcessingMetrics(
            total_items=200,
            processing_time_seconds=600,  # Slower than expected
            memory_peak_gb=10,  # Higher than expected
            cpu_usage_percent=90,
            success_rate=0.85,  # Lower than acceptable
            errors=['timeout_1', 'memory_error_1']
        )
        
        analysis = await optimizer.monitor_processing_performance(plan, metrics)
        recommendations = analysis['recommendations']
        
        assert isinstance(recommendations, list)
        assert all(isinstance(rec, str) for rec in recommendations)
    
    @staticmethod
    def _create_mock_plan() -> OptimizedProcessingPlan:
        """Helper to create mock processing plan"""
        return OptimizedProcessingPlan(
            batch_strategy={'html_batch_size': 50, 'pdf_batch_size': 10},
            cache_strategy={'max_items': 500},
            processing_order=['html', 'pdf', 'media'],
            estimated_time_minutes=10,
            memory_requirements_gb=4,
            recommended_parallel_workers=4
        )


class TestResourceMonitorIntegration:
    """Integration tests for ResourceMonitor with type contracts"""
    
    @pytest.mark.asyncio
    async def test_resource_monitor_returns_utilization_dict(self):
        """Verify ResourceMonitor.get_current_resources returns correct type"""
        monitor = ResourceMonitor()
        resources = await monitor.get_current_resources()
        
        # Should be a dict with required fields
        assert isinstance(resources, dict)
        assert 'cpu_percent' in resources
        assert 'timestamp' in resources
    
    @pytest.mark.asyncio
    async def test_resource_prediction_returns_prediction_dict(self):
        """Verify ResourceMonitor.predict_resource_usage returns correct type"""
        monitor = ResourceMonitor()
        prediction = await monitor.predict_resource_usage({
            'html_processing': 15,
            'pdf_processing': 5
        })
        
        assert isinstance(prediction, dict)
        assert 'cpu_percent' in prediction
        assert 'memory_gb' in prediction


class TestOptimizerIntegration:
    """Integration tests for WebsiteProcessingOptimizer with type contracts"""
    
    def test_analyzer_returns_complexity_dict(self):
        """Verify optimizer analysis returns proper type"""
        optimizer = WebsiteProcessingOptimizer()
        manifest = self._create_test_manifest()
        
        analysis = optimizer._analyze_content_complexity(manifest)
        
        assert isinstance(analysis, dict)
        assert all(isinstance(v, (int, float)) for v in analysis.values())
    
    def test_cache_optimizer_returns_strategy_dict(self):
        """Verify cache optimizer returns strategy dict"""
        optimizer = WebsiteProcessingOptimizer()
        manifest = self._create_test_manifest()
        
        strategy = optimizer._optimize_cache_usage(manifest)
        
        assert isinstance(strategy, dict)
        assert 'priorities' in strategy
    
    @pytest.mark.asyncio
    async def test_recommendations_returns_typed_dict(self):
        """Verify recommendations method returns typed dict"""
        optimizer = WebsiteProcessingOptimizer()
        recommendations = await optimizer.get_optimization_recommendations()
        
        assert isinstance(recommendations, dict)
        assert 'strategy' in recommendations
    
    @staticmethod
    def _create_test_manifest() -> ContentManifest:
        """Helper to create test manifest"""
        return ContentManifest(
            base_url="https://example.com",
            html_pages=[ContentAsset("https://example.com/page1", "page", "text/html", 10 * 1024)],
            pdf_documents=[ContentAsset("https://example.com/doc1.pdf", "doc", "application/pdf", 1024 * 1024)],
            media_files=[],
            structured_data=[],
            total_assets=2,
            discovery_timestamp=datetime.now()
        )


class TestTypeContractDataFlow:
    """Test data flow through type contracts"""
    
    @pytest.mark.asyncio
    async def test_resource_utilization_timestamp_is_iso_format(self):
        """Verify resource timestamps are ISO format"""
        monitor = ResourceMonitor()
        resources = await monitor.get_current_resources()
        
        timestamp_str = resources['timestamp']
        try:
            datetime.fromisoformat(timestamp_str)
        except ValueError:
            pytest.fail(f"Timestamp not in ISO format: {timestamp_str}")
    
    @pytest.mark.asyncio
    async def test_cache_policies_ttl_values_are_positive(self):
        """Verify cache TTL values are positive integers"""
        cache_mgr = ContentCacheManager()
        policies = cache_mgr._get_default_policies()
        
        ttl_fields = ['html_content_ttl', 'pdf_content_ttl', 'media_transcripts_ttl', 'embeddings_ttl']
        for field in ttl_fields:
            assert policies[field] > 0, f"{field} should be positive"
    
    def test_complexity_analysis_difficulty_normalized(self):
        """Verify difficulty score is within expected range"""
        optimizer = WebsiteProcessingOptimizer()
        manifest = ContentManifest(
            base_url="https://example.com",
            html_pages=[ContentAsset("https://example.com/page1", "page", "text/html", 10 * 1024)],
            pdf_documents=[],
            media_files=[],
            structured_data=[],
            total_assets=1,
            discovery_timestamp=datetime.now()
        )
        
        analysis = optimizer._analyze_content_complexity(manifest)
        difficulty = analysis['estimated_processing_difficulty']
        
        assert 0 <= difficulty <= 100


class TestTypeContractConsistency:
    """Test consistency of type contracts across methods"""
    
    @pytest.mark.asyncio
    async def test_monitor_resources_matches_get_current_resources(self):
        """Verify monitor_resources returns same type as get_current_resources"""
        optimizer = WebsiteProcessingOptimizer()
        monitor = optimizer.resource_monitor
        
        # Get from both methods
        resources2 = await optimizer.monitor_resources()
        resources1 = await monitor.get_current_resources()
        
        # Should have same field structure
        assert set(resources2.keys()) == set(resources1.keys())
    
    @pytest.mark.asyncio
    async def test_optimization_recommendations_consistency_across_calls(self):
        """Verify recommendations are consistent when called multiple times"""
        optimizer = WebsiteProcessingOptimizer()
        
        rec1 = await optimizer.get_optimization_recommendations()
        rec2 = await optimizer.get_optimization_recommendations()
        
        # Both should have same field structure
        assert set(rec1.keys()) == set(rec2.keys())
        # Strategy should be one of valid values in both calls
        assert rec1['strategy'] in ['fast', 'balanced', 'comprehensive']
        assert rec2['strategy'] in ['fast', 'balanced', 'comprehensive']


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
