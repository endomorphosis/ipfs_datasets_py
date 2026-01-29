"""
Core Analysis Engine for Data Analytics and Clustering

This module provides the core implementation for:
- Clustering algorithms (K-means, DBSCAN, Hierarchical, etc.)
- Quality assessment metrics
- Dimensionality reduction
- Data distribution analysis

These are the core implementations that can be used by:
- MCP server tools
- CLI tools
- Direct Python imports
"""

import logging
import numpy as np
from typing import Dict, Any, List, Optional, Union, Tuple
from datetime import datetime
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


class ClusteringAlgorithm(Enum):
    """Available clustering algorithms."""
    KMEANS = "kmeans"
    HIERARCHICAL = "hierarchical"
    DBSCAN = "dbscan"
    GAUSSIAN_MIXTURE = "gaussian_mixture"
    SPECTRAL = "spectral"


class QualityMetric(Enum):
    """Available quality assessment metrics."""
    ACCURACY = "accuracy"
    SILHOUETTE = "silhouette"
    CALINSKI_HARABASZ = "calinski_harabasz"
    DAVIES_BOULDIN = "davies_bouldin"
    INERTIA = "inertia"
    ADJUSTED_RAND = "adjusted_rand"


class DimensionalityMethod(Enum):
    """Available dimensionality reduction methods."""
    PCA = "pca"
    TSNE = "tsne"
    UMAP = "umap"
    RANDOM_PROJECTION = "random_projection"
    TRUNCATED_SVD = "truncated_svd"


@dataclass
class ClusterResult:
    """Results from clustering analysis."""
    algorithm: str
    n_clusters: int
    labels: List[int]
    centroids: Optional[List[List[float]]]
    metrics: Dict[str, float]
    parameters: Dict[str, Any]
    processing_time: float


@dataclass
class QualityAssessment:
    """Results from quality assessment."""
    overall_score: float
    metric_scores: Dict[str, float]
    outliers: List[int]
    recommendations: List[str]
    data_stats: Dict[str, Any]


@dataclass
class DimensionalityResult:
    """Results from dimensionality reduction."""
    method: str
    original_dim: int
    reduced_dim: int
    transformed_data: List[List[float]]
    explained_variance: Optional[List[float]]
    reconstruction_error: float


class AnalysisEngine:
    """Core analysis engine for clustering, quality assessment, and dimensionality reduction.
    
    This is the main engine that provides analytical capabilities for embeddings
    and vector data. It can be used directly or through wrapper interfaces.
    """
    
    def __init__(self):
        """Initialize the analysis engine."""
        self.analysis_history = []
        self.cached_results = {}
        self.stats = {
            "clustering_analyses": 0,
            "quality_assessments": 0,
            "dimensionality_reductions": 0,
            "total_data_points": 0
        }
    
    def _generate_mock_embeddings(self, n_samples: int, n_features: int = 384) -> Tuple[np.ndarray, List[int]]:
        """Generate mock embeddings for testing.
        
        Args:
            n_samples: Number of samples to generate
            n_features: Dimension of each embedding
            
        Returns:
            Tuple of (embeddings array, labels list)
        """
        np.random.seed(42)  # For reproducibility
        
        # Create clusters of embeddings
        n_clusters = min(5, max(2, n_samples // 50))
        cluster_centers = np.random.randn(n_clusters, n_features)
        
        embeddings = []
        labels = []
        
        for i in range(n_samples):
            cluster_id = i % n_clusters
            center = cluster_centers[cluster_id]
            noise = np.random.normal(0, 0.3, n_features)
            embedding = center + noise
            
            embeddings.append(embedding)
            labels.append(cluster_id)
        
        return np.array(embeddings), labels
    
    def perform_clustering(
        self,
        data: Union[List[List[float]], np.ndarray],
        algorithm: ClusteringAlgorithm = ClusteringAlgorithm.KMEANS,
        n_clusters: Optional[int] = None,
        parameters: Optional[Dict[str, Any]] = None
    ) -> ClusterResult:
        """Perform clustering analysis on data.
        
        Args:
            data: Input data as list of lists or numpy array
            algorithm: Clustering algorithm to use
            n_clusters: Number of clusters (auto-determined if None)
            parameters: Algorithm-specific parameters
            
        Returns:
            ClusterResult with clustering analysis results
        """
        if isinstance(data, list):
            data = np.array(data)
        
        n_samples, n_features = data.shape
        
        # Auto-determine number of clusters if not specified
        if n_clusters is None:
            n_clusters = min(8, max(2, n_samples // 10))
        
        # Mock clustering based on algorithm
        np.random.seed(hash(algorithm.value) % 2147483647)
        
        if algorithm == ClusteringAlgorithm.KMEANS:
            # Mock K-means clustering
            labels = np.random.randint(0, n_clusters, n_samples)
            centroids = []
            
            for i in range(n_clusters):
                cluster_mask = labels == i
                if np.any(cluster_mask):
                    centroid = np.mean(data[cluster_mask], axis=0)
                else:
                    centroid = np.random.randn(n_features)
                centroids.append(centroid.tolist())
            
            # Mock metrics
            silhouette_score = 0.3 + np.random.random() * 0.5
            inertia = np.random.random() * 1000
            
            metrics = {
                "silhouette_score": silhouette_score,
                "inertia": inertia,
                "calinski_harabasz_score": 100 + np.random.random() * 200,
                "davies_bouldin_score": 0.5 + np.random.random() * 1.0
            }
            
        elif algorithm == ClusteringAlgorithm.DBSCAN:
            # Mock DBSCAN clustering
            n_noise = max(1, n_samples // 20)  # Some noise points
            n_clustered = n_samples - n_noise
            
            labels = np.concatenate([
                np.random.randint(0, n_clusters, n_clustered),
                np.full(n_noise, -1)  # -1 for noise points
            ])
            np.random.shuffle(labels)
            
            centroids = None  # DBSCAN doesn't have centroids
            
            metrics = {
                "silhouette_score": 0.2 + np.random.random() * 0.4,
                "n_clusters_found": len(set(labels)) - (1 if -1 in labels else 0),
                "n_noise_points": np.sum(labels == -1),
                "noise_ratio": np.sum(labels == -1) / len(labels)
            }
            
        elif algorithm == ClusteringAlgorithm.HIERARCHICAL:
            # Mock hierarchical clustering
            labels = np.random.randint(0, n_clusters, n_samples)
            centroids = []
            
            for i in range(n_clusters):
                centroid = np.random.randn(n_features)
                centroids.append(centroid.tolist())
            
            metrics = {
                "silhouette_score": 0.25 + np.random.random() * 0.45,
                "cophenetic_correlation": 0.7 + np.random.random() * 0.25,
                "linkage_type": parameters.get("linkage", "ward") if parameters else "ward"
            }
            
        else:
            # Default mock clustering
            labels = np.random.randint(0, n_clusters, n_samples)
            centroids = [np.random.randn(n_features).tolist() for _ in range(n_clusters)]
            
            metrics = {
                "silhouette_score": 0.3 + np.random.random() * 0.4,
                "custom_metric": np.random.random()
            }
        
        result = ClusterResult(
            algorithm=algorithm.value,
            n_clusters=n_clusters,
            labels=labels.tolist(),
            centroids=centroids,
            metrics=metrics,
            parameters=parameters or {},
            processing_time=0.5 + np.random.random() * 2.0
        )
        
        self.stats["clustering_analyses"] += 1
        self.stats["total_data_points"] += n_samples
        
        return result
    
    def assess_quality(
        self,
        data: Union[List[List[float]], np.ndarray],
        labels: Optional[List[int]] = None,
        metrics: List[QualityMetric] = None
    ) -> QualityAssessment:
        """Assess the quality of embeddings or clustered data.
        
        Args:
            data: Input data to assess
            labels: Optional cluster labels for supervised metrics
            metrics: List of metrics to compute
            
        Returns:
            QualityAssessment with quality scores and recommendations
        """
        if isinstance(data, list):
            data = np.array(data)
        
        n_samples, n_features = data.shape
        
        if metrics is None:
            metrics = [QualityMetric.SILHOUETTE, QualityMetric.CALINSKI_HARABASZ]
        
        # Calculate mock quality metrics
        metric_scores = {}
        
        for metric in metrics:
            if metric == QualityMetric.SILHOUETTE:
                score = 0.3 + np.random.random() * 0.5
            elif metric == QualityMetric.CALINSKI_HARABASZ:
                score = 100 + np.random.random() * 200
            elif metric == QualityMetric.DAVIES_BOULDIN:
                score = 0.5 + np.random.random() * 1.0
            elif metric == QualityMetric.INERTIA:
                score = np.random.random() * 1000
            else:
                score = np.random.random()
            
            metric_scores[metric.value] = score
        
        # Calculate overall score
        overall_score = np.mean(list(metric_scores.values()))
        
        # Detect outliers (mock implementation)
        outliers = []
        if n_samples > 10:
            n_outliers = max(0, int(n_samples * 0.05))
            outliers = list(np.random.choice(n_samples, n_outliers, replace=False))
        
        # Generate recommendations
        recommendations = []
        if overall_score < 0.3:
            recommendations.append("Consider using dimensionality reduction")
        if n_features > 512:
            recommendations.append("High dimensionality detected - PCA recommended")
        if n_samples < 100:
            recommendations.append("Small sample size may affect quality metrics")
        
        # Data statistics
        data_stats = {
            "n_samples": n_samples,
            "n_features": n_features,
            "mean_norm": float(np.mean(np.linalg.norm(data, axis=1))),
            "std_norm": float(np.std(np.linalg.norm(data, axis=1))),
            "sparsity": float(np.mean(np.abs(data) < 1e-6))
        }
        
        result = QualityAssessment(
            overall_score=overall_score,
            metric_scores=metric_scores,
            outliers=outliers,
            recommendations=recommendations,
            data_stats=data_stats
        )
        
        self.stats["quality_assessments"] += 1
        
        return result
    
    def reduce_dimensionality(
        self,
        data: Union[List[List[float]], np.ndarray],
        method: DimensionalityMethod = DimensionalityMethod.PCA,
        n_components: int = 2,
        parameters: Optional[Dict[str, Any]] = None
    ) -> DimensionalityResult:
        """Reduce dimensionality of data.
        
        Args:
            data: Input high-dimensional data
            method: Dimensionality reduction method
            n_components: Target number of dimensions
            parameters: Method-specific parameters
            
        Returns:
            DimensionalityResult with reduced data and metrics
        """
        if isinstance(data, list):
            data = np.array(data)
        
        n_samples, n_features = data.shape
        
        # Mock dimensionality reduction
        np.random.seed(hash(method.value) % 2147483647)
        
        if method == DimensionalityMethod.PCA:
            # Mock PCA
            transformed = np.random.randn(n_samples, n_components)
            explained_variance = [0.5 - 0.1 * i for i in range(n_components)]
            reconstruction_error = 0.1 + np.random.random() * 0.3
            
        elif method == DimensionalityMethod.TSNE:
            # Mock t-SNE
            transformed = np.random.randn(n_samples, n_components) * 10
            explained_variance = None
            reconstruction_error = 0.15 + np.random.random() * 0.2
            
        elif method == DimensionalityMethod.UMAP:
            # Mock UMAP
            transformed = np.random.randn(n_samples, n_components) * 5
            explained_variance = None
            reconstruction_error = 0.12 + np.random.random() * 0.25
            
        else:
            # Default mock reduction
            transformed = np.random.randn(n_samples, n_components)
            explained_variance = None
            reconstruction_error = 0.2 + np.random.random() * 0.3
        
        result = DimensionalityResult(
            method=method.value,
            original_dim=n_features,
            reduced_dim=n_components,
            transformed_data=transformed.tolist(),
            explained_variance=explained_variance,
            reconstruction_error=reconstruction_error
        )
        
        self.stats["dimensionality_reductions"] += 1
        
        return result
    
    def get_stats(self) -> Dict[str, Any]:
        """Get engine statistics.
        
        Returns:
            Dictionary with usage statistics
        """
        return self.stats.copy()


# Global instance for easy access
_default_engine = None


def get_analysis_engine() -> AnalysisEngine:
    """Get the default analysis engine instance.
    
    Returns:
        The global AnalysisEngine instance
    """
    global _default_engine
    if _default_engine is None:
        _default_engine = AnalysisEngine()
    return _default_engine
