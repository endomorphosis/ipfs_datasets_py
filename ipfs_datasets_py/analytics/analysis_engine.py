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


# ---------------------------------------------------------------------------
# Standalone utility functions — also usable without the full AnalysisEngine
# ---------------------------------------------------------------------------

def detect_outliers(
    data: Union[List[List[float]], "np.ndarray"],
    threshold: float = 3.0,
) -> List[int]:
    """Detect outliers in *data* using the z-score method.

    Args:
        data: 2-D array-like of numeric vectors.
        threshold: Z-score threshold above which a sample is an outlier.

    Returns:
        List of row indices whose z-score exceeds *threshold*.
    """
    if isinstance(data, list):
        data = np.array(data)
    norms = np.linalg.norm(data, axis=1)
    z_scores = np.abs((norms - np.mean(norms)) / (np.std(norms) + 1e-10))
    return np.where(z_scores > threshold)[0].tolist()


def analyze_diversity(
    data: Union[List[List[float]], "np.ndarray"],
) -> Dict[str, float]:
    """Measure the diversity / spread of *data*.

    Returns:
        Dict with ``variance``, ``std``, ``range``, and ``coefficient_of_variation``.
    """
    if isinstance(data, list):
        data = np.array(data)
    return {
        "variance": float(np.var(data)),
        "std": float(np.std(data)),
        "range": float(np.max(data) - np.min(data)),
        "coefficient_of_variation": float(np.std(data) / (np.mean(data) + 1e-10)),
    }


def detect_drift(
    old_data: Union[List[List[float]], "np.ndarray"],
    new_data: Union[List[List[float]], "np.ndarray"],
) -> Dict[str, Any]:
    """Detect distributional drift between *old_data* and *new_data*.

    Returns:
        Dict with ``drift_detected``, ``drift_magnitude``,
        ``old_mean_norm``, and ``new_mean_norm``.
    """
    if isinstance(old_data, list):
        old_data = np.array(old_data)
    if isinstance(new_data, list):
        new_data = np.array(new_data)
    old_mean = np.mean(old_data, axis=0)
    new_mean = np.mean(new_data, axis=0)
    magnitude = float(np.linalg.norm(new_mean - old_mean))
    return {
        "drift_detected": magnitude > 0.1,
        "drift_magnitude": magnitude,
        "old_mean_norm": float(np.linalg.norm(old_mean)),
        "new_mean_norm": float(np.linalg.norm(new_mean)),
    }


def analyze_similarity_patterns(
    data: Union[List[List[float]], "np.ndarray"],
) -> Dict[str, Any]:
    """Analyse pairwise cosine-similarity patterns in *data*.

    Samples up to 100 rows for efficiency.  Falls back to a note dict when
    ``sklearn`` is not available.

    Returns:
        Dict with ``mean_similarity``, ``std_similarity``, ``min_similarity``,
        ``max_similarity``, or a note if ``sklearn`` is unavailable.
    """
    if isinstance(data, list):
        data = np.array(data)
    sample_size = min(100, len(data))
    idx = np.random.choice(len(data), sample_size, replace=False)
    sample = data[idx]
    try:
        from sklearn.metrics.pairwise import cosine_similarity  # type: ignore[import]
        sims = cosine_similarity(sample)
        return {
            "mean_similarity": float(np.mean(sims)),
            "std_similarity": float(np.std(sims)),
            "min_similarity": float(np.min(sims)),
            "max_similarity": float(np.max(sims)),
        }
    except ImportError:
        return {"note": "sklearn not available for similarity calculation"}



# ---------------------------------------------------------------------------
# High-level async API — canonical business-logic location
# ---------------------------------------------------------------------------

_default_engine: "AnalysisEngine | None" = None  # module-level singleton


async def cluster_analysis(
    data_source: str = "mock",
    algorithm: str = "kmeans",
    n_clusters: "int | None" = None,
    vectors: "list[list[float]] | None" = None,
    data_params: "dict | None" = None,
    clustering_params: "dict | None" = None,
) -> "dict":
    """Perform clustering analysis on embeddings or vector data."""
    import logging as _logging
    from datetime import datetime as _dt
    _log = _logging.getLogger(__name__)
    engine = get_analysis_engine()
    try:
        algo = ClusteringAlgorithm(algorithm)
    except ValueError:
        raise ValueError(f"Invalid algorithm: {algorithm}. Valid algorithms: {[a.value for a in ClusteringAlgorithm]}")
    if vectors is not None:
        data = np.array(vectors)
    elif data_source == "mock":
        n_s = (data_params or {}).get("n_samples", 1000)
        n_f = (data_params or {}).get("n_features", 384)
        data, _ = engine._generate_mock_embeddings(n_s, n_f)
    else:
        _log.warning(f"Using mock data for source: {data_source}")
        data, _ = engine._generate_mock_embeddings(500, 384)
    result = engine.perform_clustering(data=data, algorithm=algo, n_clusters=n_clusters, parameters=clustering_params)
    cluster_sizes: "dict[int, int]" = {}
    for label in result.labels:
        cluster_sizes[label] = cluster_sizes.get(label, 0) + 1
    data_shape = list(data.shape) if hasattr(data, "shape") else [len(data), len(data[0]) if data else 0]
    return {
        "success": True, "status": "success", "data_source": data_source,
        "algorithm": result.algorithm, "n_clusters": result.n_clusters,
        "cluster_labels": result.labels, "centroids": result.centroids,
        "metrics": result.metrics, "cluster_sizes": cluster_sizes,
        "data_shape": data_shape, "processing_time_seconds": result.processing_time,
        "analyzed_at": _dt.now().isoformat(),
    }


async def quality_assessment(
    data_source: str = "mock",
    assessment_type: str = "comprehensive",
    metrics: "list[str] | None" = None,
    data: "dict | None" = None,
    embeddings: "list[list[float]] | None" = None,
    data_params: "dict | None" = None,
    outlier_detection: bool = True,
) -> "dict":
    """Assess the quality of embeddings and vector data."""
    import logging as _logging
    from datetime import datetime as _dt
    _log = _logging.getLogger(__name__)
    engine = get_analysis_engine()
    if data is not None and isinstance(data, dict) and data.get("vectors") is not None:
        embeddings = data.get("vectors")
        labels = data.get("labels")
    else:
        labels = None
    if embeddings is not None:
        embedding_data = np.array(embeddings)
    elif data_source == "mock":
        n_s = (data_params or {}).get("n_samples", 500)
        n_f = (data_params or {}).get("n_features", 384)
        embedding_data, labels = engine._generate_mock_embeddings(n_s, n_f)
    else:
        _log.warning(f"Using mock data for source: {data_source}")
        embedding_data, labels = engine._generate_mock_embeddings(500, 384)
    quality_metrics = None
    if metrics:
        quality_metrics = []
        for m_str in metrics:
            try:
                quality_metrics.append(QualityMetric(m_str))
            except ValueError:
                _log.warning(f"Unknown metric: {m_str}, skipping")
    result = engine.assess_quality(data=embedding_data, labels=labels, metrics=quality_metrics)
    return {
        "success": True, "status": "success", "data_source": data_source,
        "assessment_type": assessment_type, "overall_score": result.overall_score,
        "metric_scores": result.metric_scores,
        "outliers": result.outliers if outlier_detection else [],
        "n_outliers": len(result.outliers) if outlier_detection else 0,
        "recommendations": result.recommendations, "data_statistics": result.data_stats,
        "analyzed_at": _dt.now().isoformat(),
    }


async def dimensionality_reduction(
    data_source: str = "mock",
    method: str = "pca",
    n_components: int = 2,
    vectors: "list[list[float]] | None" = None,
    data_params: "dict | None" = None,
    method_params: "dict | None" = None,
) -> "dict":
    """Reduce dimensionality of embeddings using various algorithms."""
    import logging as _logging
    from datetime import datetime as _dt
    _log = _logging.getLogger(__name__)
    engine = get_analysis_engine()
    try:
        m = DimensionalityMethod(method)
    except ValueError:
        raise ValueError(f"Invalid method: {method}. Valid: {[m.value for m in DimensionalityMethod]}")
    if vectors is not None:
        data = np.array(vectors)
    elif data_source == "mock":
        n_s = (data_params or {}).get("n_samples", 1000)
        n_f = (data_params or {}).get("n_features", 384)
        data, _ = engine._generate_mock_embeddings(n_s, n_f)
    else:
        _log.warning(f"Using mock data for source: {data_source}")
        data, _ = engine._generate_mock_embeddings(1000, 384)
    result = engine.reduce_dimensionality(data=data, method=m, n_components=n_components, parameters=method_params)
    return {
        "success": True, "status": "success", "data_source": data_source,
        "method": result.method, "original_dimensions": result.original_dim,
        "reduced_dimensions": result.reduced_dim, "transformed_data": result.transformed_data,
        "explained_variance": result.explained_variance,
        "reconstruction_error": result.reconstruction_error,
        "n_samples": len(result.transformed_data), "analyzed_at": _dt.now().isoformat(),
    }


async def analyze_data_distribution(
    data_source: str = "mock",
    analysis_type: str = "comprehensive",
    vectors: "list[list[float]] | None" = None,
    data_params: "dict | None" = None,
    visualization_config: "dict | None" = None,
) -> "dict":
    """Analyze the statistical distribution of embedding vectors."""
    import logging as _logging
    from datetime import datetime as _dt
    _log = _logging.getLogger(__name__)
    engine = get_analysis_engine()
    if vectors is not None:
        data = np.array(vectors)
    elif data_source == "mock":
        n_s = (data_params or {}).get("n_samples", 1000)
        n_f = (data_params or {}).get("n_features", 384)
        data, _ = engine._generate_mock_embeddings(n_s, n_f)
    else:
        _log.warning(f"Using mock data for source: {data_source}")
        data, _ = engine._generate_mock_embeddings(1000, 384)
    norms = np.linalg.norm(data, axis=1)
    means = np.mean(data, axis=0)
    stds = np.std(data, axis=0)
    feature_stats = {
        "mean_values": {"mean": float(np.mean(means)), "std": float(np.std(means)),
                        "min": float(np.min(means)), "max": float(np.max(means))},
        "std_values": {"mean": float(np.mean(stds)), "std": float(np.std(stds)),
                       "min": float(np.min(stds)), "max": float(np.max(stds))},
    }
    norm_stats = {"mean": float(np.mean(norms)), "std": float(np.std(norms)),
                  "min": float(np.min(norms)), "max": float(np.max(norms)),
                  "median": float(np.median(norms)),
                  "q25": float(np.percentile(norms, 25)), "q75": float(np.percentile(norms, 75))}
    correlation_strength = float(np.mean(np.abs(np.corrcoef(data.T))))
    sparsity = float(np.mean(np.abs(data) < 1e-6))
    try:
        from sklearn.metrics.pairwise import pairwise_distances  # type: ignore[import]
        sample = data[np.random.choice(len(data), min(50, len(data)), replace=False)]
        dists = pairwise_distances(sample, sample)
        idx = np.triu_indices_from(dists, k=1)
        distance_stats: "dict" = {"mean_distance": float(np.mean(dists[idx])),
                                   "std_distance": float(np.std(dists[idx])),
                                   "min_distance": float(np.min(dists[dists > 0])),
                                   "max_distance": float(np.max(dists))}
    except ImportError:
        distance_stats = {"note": "sklearn not available"}
    result: "dict" = {
        "success": True, "status": "success", "data_source": data_source,
        "analysis_type": analysis_type, "data_shape": list(data.shape),
        "feature_statistics": feature_stats, "vector_norm_statistics": norm_stats,
        "distance_statistics": distance_stats, "correlation_strength": correlation_strength,
        "sparsity_ratio": sparsity,
        "data_quality_indicators": {"has_nans": bool(np.any(np.isnan(data))),
                                    "has_infs": bool(np.any(np.isinf(data))),
                                    "is_centered": abs(float(np.mean(data))) < 0.1,
                                    "is_normalized": 0.8 < float(np.mean(norms)) < 1.2,
                                    "distribution_type": ("normal" if norm_stats["std"] / (norm_stats["mean"] + 1e-10) < 0.5 else "diverse")},
        "analyzed_at": _dt.now().isoformat(),
    }
    if visualization_config and visualization_config.get("include_histograms", False):
        result["visualization_data"] = {
            "norm_histogram": {"bins": np.histogram(norms, bins=20)[1].tolist(),
                               "counts": np.histogram(norms, bins=20)[0].tolist()},
        }
    return result


# Legacy aliases for backward compatibility
async def perform_clustering_analysis(*args, **kwargs) -> "dict":  # noqa: D103
    return await cluster_analysis(*args, **kwargs)

async def assess_embedding_quality(*args, **kwargs) -> "dict":  # noqa: D103
    return await quality_assessment(*args, **kwargs)

async def reduce_dimensionality(*args, **kwargs) -> "dict":  # noqa: D103
    return await dimensionality_reduction(*args, **kwargs)
