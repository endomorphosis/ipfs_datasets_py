#!/usr/bin/env python3
"""
Test suite for analysis tools functionality.
"""

import pytest
import asyncio
import sys
import numpy as np
from pathlib import Path
from unittest.mock import Mock, AsyncMock, patch, MagicMock

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


class TestAnalysisTools:
    """Test analysis tools functionality."""

    @pytest.mark.asyncio
    async def test_perform_clustering_analysis(self):
        """Test clustering analysis functionality."""
        from ipfs_datasets_py.mcp_server.tools.analysis_tools.analysis_tools import perform_clustering_analysis
        
        # Create test data
        test_vectors = np.random.rand(100, 50).tolist()
        
        result = await perform_clustering_analysis(
            vectors=test_vectors,
            algorithm="kmeans",
            n_clusters=5,
            include_metrics=True
        )
        
        assert result is not None
        assert "status" in result
        assert "clustering_result" in result or "clusters" in result or "labels" in result
    
    @pytest.mark.asyncio
    async def test_assess_embedding_quality(self):
        """Test embedding quality assessment."""
        from ipfs_datasets_py.mcp_server.tools.analysis_tools.analysis_tools import assess_embedding_quality
        
        # Create test embeddings
        test_embeddings = np.random.rand(50, 128).tolist()
        test_labels = np.random.randint(0, 5, 50).tolist()
        
        result = await assess_embedding_quality(
            embeddings=test_embeddings,
            labels=test_labels,
            metrics=["silhouette", "calinski_harabasz"]
        )
        
        assert result is not None
        assert "status" in result
        assert "quality_assessment" in result or "metrics" in result
    
    @pytest.mark.asyncio
    async def test_reduce_dimensionality(self):
        """Test dimensionality reduction functionality."""
        from ipfs_datasets_py.mcp_server.tools.analysis_tools.analysis_tools import reduce_dimensionality
        
        # Create high-dimensional test data
        test_data = np.random.rand(100, 512).tolist()
        
        result = await reduce_dimensionality(
            vectors=test_data,
            method="pca",
            target_dimensions=50,
            preserve_variance=0.95
        )
        
        assert result is not None
        assert "status" in result
        assert "reduced_vectors" in result or "transformed_data" in result
    
    @pytest.mark.asyncio
    async def test_analyze_similarity_patterns(self):
        """Test similarity pattern analysis."""
        from ipfs_datasets_py.mcp_server.tools.analysis_tools.analysis_tools import analyze_similarity_patterns
        
        # Create test vectors
        test_vectors = np.random.rand(50, 128).tolist()
        
        result = await analyze_similarity_patterns(
            vectors=test_vectors,
            similarity_metric="cosine",
            threshold=0.8,
            include_graph=True
        )
        
        assert result is not None
        assert "status" in result
        assert "similarity_analysis" in result or "patterns" in result
    
    @pytest.mark.asyncio
    async def test_detect_drift(self):
        """Test concept drift detection."""
        from ipfs_datasets_py.mcp_server.tools.analysis_tools.analysis_tools import detect_drift
        
        # Create reference and current embeddings
        reference_embeddings = np.random.rand(100, 128).tolist()
        current_embeddings = np.random.rand(100, 128).tolist()
        
        result = await detect_drift(
            reference_embeddings=reference_embeddings,
            current_embeddings=current_embeddings,
            drift_threshold=0.1,
            method="statistical"
        )
        
        assert result is not None
        assert "status" in result
        assert "drift_detected" in result or "drift_score" in result
    
    @pytest.mark.asyncio
    async def test_outlier_detection(self):
        """Test outlier detection in embeddings."""
        from ipfs_datasets_py.mcp_server.tools.analysis_tools.analysis_tools import detect_outliers
        
        # Create test data with some outliers
        normal_data = np.random.normal(0, 1, (90, 50))
        outlier_data = np.random.normal(5, 1, (10, 50))
        test_data = np.vstack([normal_data, outlier_data]).tolist()
        
        result = await detect_outliers(
            vectors=test_data,
            method="isolation_forest",
            contamination=0.1
        )
        
        assert result is not None
        assert "status" in result
        assert "outliers" in result or "outlier_scores" in result
    
    @pytest.mark.asyncio
    async def test_diversity_analysis(self):
        """Test embedding diversity analysis."""
        from ipfs_datasets_py.mcp_server.tools.analysis_tools.analysis_tools import analyze_diversity
        
        test_embeddings = np.random.rand(100, 128).tolist()
        
        result = await analyze_diversity(
            embeddings=test_embeddings,
            diversity_metrics=["entropy", "variance", "coverage"],
            reference_embeddings=None
        )
        
        assert result is not None
        assert "status" in result
        assert "diversity_analysis" in result or "diversity_scores" in result


class TestAnalysisDataStructures:
    """Test analysis tools data structures and utilities."""

    def test_cluster_result_creation(self):
        """Test ClusterResult dataclass creation."""
        from ipfs_datasets_py.mcp_server.tools.analysis_tools.analysis_tools import ClusterResult
        
        result = ClusterResult(
            algorithm="kmeans",
            n_clusters=5,
            labels=[0, 1, 2, 0, 1],
            centroids=None,
            metrics={"silhouette": 0.8},
            parameters={"n_clusters": 5},
            processing_time=1.5
        )
        
        assert result.algorithm == "kmeans"
        assert result.n_clusters == 5
        assert len(result.labels) == 5
        assert result.metrics["silhouette"] == 0.8
    
    def test_quality_assessment_creation(self):
        """Test QualityAssessment dataclass creation."""
        from ipfs_datasets_py.mcp_server.tools.analysis_tools.analysis_tools import QualityAssessment
        
        assessment = QualityAssessment(
            overall_score=0.85,
            metric_scores={"silhouette": 0.8, "calinski_harabasz": 0.9}
        )
        
        assert assessment.overall_score == 0.85
        assert assessment.metric_scores["silhouette"] == 0.8
    
    def test_enum_definitions(self):
        """Test that enums are properly defined."""
        from ipfs_datasets_py.mcp_server.tools.analysis_tools.analysis_tools import (
            ClusteringAlgorithm,
            QualityMetric,
            DimensionalityMethod
        )
        
        assert ClusteringAlgorithm.KMEANS.value == "kmeans"
        assert QualityMetric.SILHOUETTE.value == "silhouette"
        assert DimensionalityMethod.PCA.value == "pca"


class TestAnalysisToolsIntegration:
    """Test analysis tools integration with other components."""

    @pytest.mark.asyncio
    async def test_analysis_tools_mcp_registration(self):
        """Test that analysis tools are properly registered with MCP."""
        from ipfs_datasets_py.mcp_server.tools.tool_registration import get_registered_tools
        
        tools = get_registered_tools()
        analysis_tools = [tool for tool in tools if 'analysis' in tool.get('name', '').lower()]
        
        assert len(analysis_tools) > 0, "Analysis tools should be registered"
    
    @pytest.mark.asyncio
    async def test_analysis_tools_error_handling(self):
        """Test error handling in analysis tools."""
        from ipfs_datasets_py.mcp_server.tools.analysis_tools.analysis_tools import perform_clustering_analysis
        
        # Test with invalid algorithm
        result = await perform_clustering_analysis(
            vectors=[[1, 2, 3], [4, 5, 6]],
            algorithm="invalid_algorithm",
            n_clusters=2
        )
        
        assert result is not None
        assert "status" in result
        # Should handle error gracefully
        assert result["status"] in ["error", "success"]
    
    @pytest.mark.asyncio
    async def test_analysis_with_empty_data(self):
        """Test analysis tools with empty data."""
        from ipfs_datasets_py.mcp_server.tools.analysis_tools.analysis_tools import assess_embedding_quality
        
        result = await assess_embedding_quality(
            embeddings=[],
            labels=[],
            metrics=["silhouette"]
        )
        
        assert result is not None
        assert "status" in result
        # Should handle empty data gracefully


class TestAnalysisVisualization:
    """Test analysis visualization capabilities."""

    @pytest.mark.asyncio
    async def test_generate_cluster_visualization(self):
        """Test cluster visualization generation."""
        try:
            from ipfs_datasets_py.mcp_server.tools.analysis_tools.analysis_tools import generate_cluster_visualization
            
            test_vectors = np.random.rand(50, 10).tolist()
            test_labels = np.random.randint(0, 3, 50).tolist()
            
            result = await generate_cluster_visualization(
                vectors=test_vectors,
                labels=test_labels,
                method="tsne",
                output_path="/tmp/cluster_vis.png"
            )
            
            assert result is not None
            assert "status" in result
        except ImportError:
            raise ImportError("Visualization tools not available")
    
    @pytest.mark.asyncio
    async def test_generate_quality_report(self):
        """Test quality report generation."""
        try:
            from ipfs_datasets_py.mcp_server.tools.analysis_tools.analysis_tools import generate_quality_report
            
            test_metrics = {
                "silhouette": 0.8,
                "calinski_harabasz": 100.5,
                "davies_bouldin": 0.3
            }
            
            result = await generate_quality_report(
                metrics=test_metrics,
                output_format="html",
                output_path="/tmp/quality_report.html"
            )
            
            assert result is not None
            assert "status" in result
        except ImportError:
            raise ImportError("Report generation tools not available")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
