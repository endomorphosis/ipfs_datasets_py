#!/usr/bin/env python3
"""
Test suite for analysis_tools functionality with GIVEN WHEN THEN format.

Written to match the actual analysis_tools API:
  perform_clustering_analysis(vectors, n_clusters, algorithm, ...)
  assess_embedding_quality(embeddings, ...)
  reduce_dimensionality(vectors, ...)
  detect_outliers(data, ...) — synchronous
  analyze_diversity(data, ...) — synchronous
Note: the original _test_analysis_tools.py used incorrect kwarg names.
"""

import pytest
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))


class TestClusteringAnalysis:
    """Test perform_clustering_analysis()."""

    @pytest.mark.asyncio
    async def test_kmeans_clustering(self):
        """GIVEN a set of vectors
        WHEN perform_clustering_analysis is called with algorithm='kmeans'
        THEN cluster labels and metrics are returned
        """
        import numpy as np
        from ipfs_datasets_py.mcp_server.tools.analysis_tools.analysis_tools import (
            perform_clustering_analysis,
        )
        vectors = np.random.rand(30, 8).tolist()
        result = await perform_clustering_analysis(vectors=vectors, algorithm="kmeans", n_clusters=3)
        assert result is not None
        assert result["success"] is True
        assert "cluster_labels" in result or "clusters" in result
        assert result["algorithm"] == "kmeans"

    @pytest.mark.asyncio
    async def test_dbscan_clustering(self):
        """GIVEN a set of vectors
        WHEN perform_clustering_analysis is called with algorithm='dbscan'
        THEN clustering result is returned
        """
        import numpy as np
        from ipfs_datasets_py.mcp_server.tools.analysis_tools.analysis_tools import (
            perform_clustering_analysis,
        )
        vectors = np.random.rand(20, 4).tolist()
        result = await perform_clustering_analysis(vectors=vectors, algorithm="dbscan")
        assert result is not None
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_invalid_algorithm_raises(self):
        """GIVEN an unknown algorithm name
        WHEN perform_clustering_analysis is called
        THEN a ValueError is raised
        """
        import numpy as np
        from ipfs_datasets_py.mcp_server.tools.analysis_tools.analysis_tools import (
            perform_clustering_analysis,
        )
        vectors = np.random.rand(10, 4).tolist()
        with pytest.raises(ValueError):
            await perform_clustering_analysis(vectors=vectors, algorithm="nonexistent_algo")

    @pytest.mark.asyncio
    async def test_clustering_result_has_metrics(self):
        """GIVEN a set of vectors
        WHEN perform_clustering_analysis is called
        THEN the metrics section is present
        """
        import numpy as np
        from ipfs_datasets_py.mcp_server.tools.analysis_tools.analysis_tools import (
            perform_clustering_analysis,
        )
        vectors = np.random.rand(40, 6).tolist()
        result = await perform_clustering_analysis(vectors=vectors, n_clusters=4)
        assert result is not None
        assert "metrics" in result or "cluster_sizes" in result


class TestEmbeddingQuality:
    """Test assess_embedding_quality()."""

    @pytest.mark.asyncio
    async def test_basic_quality_assessment(self):
        """GIVEN a set of embeddings
        WHEN assess_embedding_quality is called
        THEN an overall_score and recommendations are returned
        """
        import numpy as np
        from ipfs_datasets_py.mcp_server.tools.analysis_tools.analysis_tools import (
            assess_embedding_quality,
        )
        embeddings = np.random.rand(25, 8).tolist()
        result = await assess_embedding_quality(embeddings=embeddings)
        assert result is not None
        assert result["success"] is True
        assert "overall_score" in result
        assert "recommendations" in result

    @pytest.mark.asyncio
    async def test_quality_assessment_has_outliers(self):
        """GIVEN a set of embeddings
        WHEN assess_embedding_quality is called
        THEN the outliers field is present
        """
        import numpy as np
        from ipfs_datasets_py.mcp_server.tools.analysis_tools.analysis_tools import (
            assess_embedding_quality,
        )
        embeddings = np.random.rand(30, 12).tolist()
        result = await assess_embedding_quality(embeddings=embeddings)
        assert "outliers" in result or "n_outliers" in result


class TestDimensionalityReduction:
    """Test reduce_dimensionality()."""

    @pytest.mark.asyncio
    async def test_dimensionality_reduction_pca(self):
        """GIVEN high-dimensional vectors
        WHEN reduce_dimensionality is called with method='pca'
        THEN lower-dimensional vectors are returned
        """
        import numpy as np
        from ipfs_datasets_py.mcp_server.tools.analysis_tools.analysis_tools import (
            reduce_dimensionality,
        )
        vectors = np.random.rand(20, 16).tolist()
        result = await reduce_dimensionality(vectors=vectors, n_components=4, method="pca")
        assert result is not None
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_dimensionality_reduction_default(self):
        """GIVEN vectors
        WHEN reduce_dimensionality is called with defaults
        THEN a result is returned
        """
        import numpy as np
        from ipfs_datasets_py.mcp_server.tools.analysis_tools.analysis_tools import (
            reduce_dimensionality,
        )
        vectors = np.random.rand(15, 10).tolist()
        result = await reduce_dimensionality(vectors=vectors)
        assert result is not None


class TestSynchronousAnalysisFunctions:
    """Test synchronous analysis helper functions."""

    def test_detect_outliers(self):
        """GIVEN a dataset
        WHEN detect_outliers is called
        THEN a list of outlier indices is returned
        """
        import numpy as np
        from ipfs_datasets_py.mcp_server.tools.analysis_tools.analysis_tools import detect_outliers
        data = np.random.rand(50, 4)
        # Add obvious outlier
        data[0] = [100.0, 100.0, 100.0, 100.0]
        result = detect_outliers(data=data, threshold=3.0)
        assert isinstance(result, list)
        # The obvious outlier should be detected
        assert 0 in result

    def test_analyze_diversity(self):
        """GIVEN a dataset
        WHEN analyze_diversity is called
        THEN a dict of diversity metrics is returned
        """
        import numpy as np
        from ipfs_datasets_py.mcp_server.tools.analysis_tools.analysis_tools import analyze_diversity
        data = np.random.rand(20, 6)
        result = analyze_diversity(data=data)
        assert isinstance(result, dict)
        assert len(result) > 0

    def test_detect_drift(self):
        """GIVEN a reference and current dataset
        WHEN detect_drift is called
        THEN a drift analysis is returned
        """
        import numpy as np
        from ipfs_datasets_py.mcp_server.tools.analysis_tools.analysis_tools import detect_drift
        reference = np.random.rand(30, 4)
        current = np.random.rand(20, 4)
        result = detect_drift(old_data=reference, new_data=current)
        assert result is not None

    def test_analyze_similarity_patterns(self):
        """GIVEN a dataset
        WHEN analyze_similarity_patterns is called
        THEN a dict of similarity metrics is returned
        """
        import numpy as np
        from ipfs_datasets_py.mcp_server.tools.analysis_tools.analysis_tools import (
            analyze_similarity_patterns,
        )
        data = np.random.rand(15, 5)
        result = analyze_similarity_patterns(data=data)
        assert isinstance(result, dict)


class TestAnalysisToolsIntegration:
    """Integration tests for analysis_tools."""

    @pytest.mark.asyncio
    async def test_analysis_tools_error_handling(self):
        """GIVEN an invalid algorithm name
        WHEN perform_clustering_analysis is called
        THEN a ValueError is raised with valid algorithms listed
        """
        import numpy as np
        from ipfs_datasets_py.mcp_server.tools.analysis_tools.analysis_tools import (
            perform_clustering_analysis,
        )
        vectors = np.random.rand(10, 4).tolist()
        with pytest.raises(ValueError, match="Valid algorithms"):
            await perform_clustering_analysis(vectors=vectors, algorithm="invalid_algorithm")

    @pytest.mark.asyncio
    async def test_full_analysis_pipeline(self):
        """GIVEN a set of vectors
        WHEN clustering → quality assessment pipeline is run
        THEN both steps succeed
        """
        import numpy as np
        from ipfs_datasets_py.mcp_server.tools.analysis_tools.analysis_tools import (
            perform_clustering_analysis,
            assess_embedding_quality,
        )
        vectors = np.random.rand(50, 8).tolist()

        cluster_result = await perform_clustering_analysis(vectors=vectors, n_clusters=3)
        assert cluster_result["success"] is True

        quality_result = await assess_embedding_quality(embeddings=vectors)
        assert quality_result["success"] is True
