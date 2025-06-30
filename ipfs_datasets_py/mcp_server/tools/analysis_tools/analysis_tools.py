# analysis_tools.py

import asyncio
import logging
import numpy as np
from typing import Dict, Any, List, Optional, Union, Tuple
from datetime import datetime
from dataclasses import dataclass
from enum import Enum
import json

logger = logging.getLogger(__name__)

class ClusteringAlgorithm(Enum):
    KMEANS = "kmeans"
    HIERARCHICAL = "hierarchical"
    DBSCAN = "dbscan"
    GAUSSIAN_MIXTURE = "gaussian_mixture"
    SPECTRAL = "spectral"

class QualityMetric(Enum):
    SILHOUETTE = "silhouette"
    CALINSKI_HARABASZ = "calinski_harabasz"
    DAVIES_BOULDIN = "davies_bouldin"
    INERTIA = "inertia"
    ADJUSTED_RAND = "adjusted_rand"

class DimensionalityMethod(Enum):
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

class MockAnalysisEngine:
    """Mock analysis engine for testing and development."""
    
    def __init__(self):
        self.analysis_history = []
        self.cached_results = {}
        self.stats = {
            "clustering_analyses": 0,
            "quality_assessments": 0,
            "dimensionality_reductions": 0,
            "total_data_points": 0
        }
    
    def _generate_mock_embeddings(self, n_samples: int, n_features: int = 384) -> np.ndarray:
        """Generate mock embeddings for testing."""
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
        """Perform clustering analysis on data."""
        
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
        """Assess the quality of embeddings or clustered data."""
        
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
        
        # Detect mock outliers
        n_outliers = max(1, n_samples // 50)
        outliers = np.random.choice(n_samples, n_outliers, replace=False).tolist()
        
        # Generate overall score (weighted average of normalized metrics)
        normalized_scores = []
        for metric, score in metric_scores.items():
            if metric == "silhouette_score":
                normalized_scores.append(score)  # Already 0-1
            elif metric == "calinski_harabasz_score":
                normalized_scores.append(min(1.0, score / 300))  # Normalize to 0-1
            elif metric == "davies_bouldin_score":
                normalized_scores.append(1.0 - min(1.0, score / 2.0))  # Lower is better
            else:
                normalized_scores.append(score if 0 <= score <= 1 else min(1.0, abs(score)))
        
        overall_score = np.mean(normalized_scores) if normalized_scores else 0.5
        
        # Generate recommendations
        recommendations = []
        if overall_score < 0.3:
            recommendations.append("Consider increasing the number of clusters")
            recommendations.append("Check for data preprocessing issues")
        elif overall_score < 0.5:
            recommendations.append("Try different clustering algorithms")
            recommendations.append("Consider dimensionality reduction")
        else:
            recommendations.append("Quality looks good - consider fine-tuning parameters")
        
        if len(outliers) > n_samples * 0.1:
            recommendations.append("High number of outliers detected - consider data cleaning")
        
        # Data statistics
        data_stats = {
            "n_samples": n_samples,
            "n_features": n_features,
            "mean_norm": float(np.mean(np.linalg.norm(data, axis=1))),
            "std_norm": float(np.std(np.linalg.norm(data, axis=1))),
            "sparsity": float(np.mean(data == 0)) if data.size > 0 else 0.0,
            "outlier_ratio": len(outliers) / n_samples
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
        target_dim: int = 2,
        parameters: Optional[Dict[str, Any]] = None
    ) -> DimensionalityResult:
        """Perform dimensionality reduction on data."""
        
        if isinstance(data, list):
            data = np.array(data)
        
        n_samples, n_features = data.shape
        target_dim = min(target_dim, n_features, n_samples)
        
        # Mock dimensionality reduction
        np.random.seed(hash(method.value) % 2147483647)
        
        if method == DimensionalityMethod.PCA:
            # Mock PCA
            transformed_data = np.random.randn(n_samples, target_dim)
            
            # Mock explained variance ratios
            explained_variance = np.random.random(target_dim)
            explained_variance = explained_variance / np.sum(explained_variance)
            explained_variance = sorted(explained_variance, reverse=True)
            
            reconstruction_error = 0.1 + np.random.random() * 0.3
            
        elif method == DimensionalityMethod.TSNE:
            # Mock t-SNE
            transformed_data = np.random.randn(n_samples, target_dim) * 50
            explained_variance = None  # t-SNE doesn't provide explained variance
            reconstruction_error = np.random.random() * 0.5
            
        elif method == DimensionalityMethod.UMAP:
            # Mock UMAP
            transformed_data = np.random.randn(n_samples, target_dim) * 10
            explained_variance = None  # UMAP doesn't provide explained variance
            reconstruction_error = 0.05 + np.random.random() * 0.25
            
        else:
            # Default mock reduction
            transformed_data = np.random.randn(n_samples, target_dim)
            explained_variance = None
            reconstruction_error = np.random.random() * 0.4
        
        # Ensure transformed data has reasonable scale
        if method != DimensionalityMethod.TSNE:
            transformed_data = transformed_data * np.std(data.flatten()) + np.mean(data.flatten())
        
        result = DimensionalityResult(
            method=method.value,
            original_dim=n_features,
            reduced_dim=target_dim,
            transformed_data=transformed_data.tolist(),
            explained_variance=explained_variance,
            reconstruction_error=reconstruction_error
        )
        
        self.stats["dimensionality_reductions"] += 1
        
        return result

# Global analysis engine
_analysis_engine = MockAnalysisEngine()

async def cluster_analysis(
    data_source: str,
    algorithm: str = "kmeans",
    n_clusters: Optional[int] = None,
    data_params: Optional[Dict[str, Any]] = None,
    clustering_params: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Perform clustering analysis on embeddings or vector data.
    
    Args:
        data_source: Source of data (collection, file, ids, or mock)
        algorithm: Clustering algorithm to use
        n_clusters: Number of clusters (auto-determined if None)
        data_params: Parameters for data loading
        clustering_params: Parameters for clustering algorithm
    
    Returns:
        Dict containing clustering analysis results
    """
    try:
        logger.info(f"Performing {algorithm} clustering analysis on {data_source}")
        
        # Validate algorithm
        try:
            clustering_algo = ClusteringAlgorithm(algorithm)
        except ValueError:
            raise ValueError(f"Invalid algorithm: {algorithm}. Valid algorithms: {[a.value for a in ClusteringAlgorithm]}")
        
        # Load or generate data based on source
        if data_source == "mock":
            n_samples = data_params.get("n_samples", 1000) if data_params else 1000
            n_features = data_params.get("n_features", 384) if data_params else 384
            data, true_labels = _analysis_engine._generate_mock_embeddings(n_samples, n_features)
        else:
            # Mock data loading for other sources
            logger.warning(f"Using mock data for source: {data_source}")
            n_samples = 500
            n_features = 384
            data, true_labels = _analysis_engine._generate_mock_embeddings(n_samples, n_features)
        
        # Perform clustering
        result = _analysis_engine.perform_clustering(
            data=data,
            algorithm=clustering_algo,
            n_clusters=n_clusters,
            parameters=clustering_params
        )
        
        # Add additional analysis
        cluster_sizes = {}
        for label in result.labels:
            cluster_sizes[label] = cluster_sizes.get(label, 0) + 1
        
        return {
            "data_source": data_source,
            "algorithm": result.algorithm,
            "n_clusters": result.n_clusters,
            "cluster_labels": result.labels,
            "centroids": result.centroids,
            "metrics": result.metrics,
            "cluster_sizes": cluster_sizes,
            "data_shape": [len(data), len(data[0]) if data else 0],
            "parameters": {
                "clustering": result.parameters,
                "data_loading": data_params or {}
            },
            "processing_time_seconds": result.processing_time,
            "analyzed_at": datetime.now().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Clustering analysis failed: {e}")
        raise

async def quality_assessment(
    data_source: str,
    assessment_type: str = "comprehensive",
    metrics: Optional[List[str]] = None,
    data_params: Optional[Dict[str, Any]] = None,
    outlier_detection: bool = True
) -> Dict[str, Any]:
    """
    Assess the quality of embeddings and vector data.
    
    Args:
        data_source: Source of data to assess
        assessment_type: Type of assessment to perform
        metrics: Specific quality metrics to compute
        data_params: Parameters for data loading
        outlier_detection: Whether to perform outlier detection
    
    Returns:
        Dict containing quality assessment results
    """
    try:
        logger.info(f"Performing {assessment_type} quality assessment on {data_source}")
        
        # Validate metrics
        metric_enums = []
        if metrics:
            for metric in metrics:
                try:
                    metric_enums.append(QualityMetric(metric))
                except ValueError:
                    raise ValueError(f"Invalid metric: {metric}. Valid metrics: {[m.value for m in QualityMetric]}")
        
        # Load or generate data
        if data_source == "mock":
            n_samples = data_params.get("n_samples", 1000) if data_params else 1000
            n_features = data_params.get("n_features", 384) if data_params else 384
            data, labels = _analysis_engine._generate_mock_embeddings(n_samples, n_features)
        else:
            # Mock data loading
            logger.warning(f"Using mock data for source: {data_source}")
            n_samples = 500
            n_features = 384
            data, labels = _analysis_engine._generate_mock_embeddings(n_samples, n_features)
        
        # Perform quality assessment
        result = _analysis_engine.assess_quality(
            data=data,
            labels=labels if assessment_type == "clustering" else None,
            metrics=metric_enums
        )
        
        assessment_results = {
            "data_source": data_source,
            "assessment_type": assessment_type,
            "overall_quality_score": result.overall_score,
            "quality_level": "excellent" if result.overall_score > 0.7 
                           else "good" if result.overall_score > 0.5
                           else "fair" if result.overall_score > 0.3
                           else "poor",
            "metric_scores": result.metric_scores,
            "data_statistics": result.data_stats,
            "recommendations": result.recommendations,
            "assessed_at": datetime.now().isoformat()
        }
        
        if outlier_detection:
            assessment_results.update({
                "outliers_detected": len(result.outliers),
                "outlier_indices": result.outliers,
                "outlier_ratio": len(result.outliers) / result.data_stats["n_samples"]
            })
        
        return assessment_results
        
    except Exception as e:
        logger.error(f"Quality assessment failed: {e}")
        raise

async def dimensionality_reduction(
    data_source: str,
    method: str = "pca",
    target_dimensions: int = 2,
    data_params: Optional[Dict[str, Any]] = None,
    method_params: Optional[Dict[str, Any]] = None,
    return_transformed_data: bool = True
) -> Dict[str, Any]:
    """
    Perform dimensionality reduction on high-dimensional vector data.
    
    Args:
        data_source: Source of data to reduce
        method: Dimensionality reduction method
        target_dimensions: Target number of dimensions
        data_params: Parameters for data loading
        method_params: Parameters for reduction method
        return_transformed_data: Whether to return transformed data
    
    Returns:
        Dict containing dimensionality reduction results
    """
    try:
        logger.info(f"Performing {method} dimensionality reduction to {target_dimensions}D on {data_source}")
        
        # Validate method
        try:
            reduction_method = DimensionalityMethod(method)
        except ValueError:
            raise ValueError(f"Invalid method: {method}. Valid methods: {[m.value for m in DimensionalityMethod]}")
        
        # Load or generate data
        if data_source == "mock":
            n_samples = data_params.get("n_samples", 1000) if data_params else 1000
            n_features = data_params.get("n_features", 384) if data_params else 384
            data, _ = _analysis_engine._generate_mock_embeddings(n_samples, n_features)
        else:
            # Mock data loading
            logger.warning(f"Using mock data for source: {data_source}")
            n_samples = 500
            n_features = 384
            data, _ = _analysis_engine._generate_mock_embeddings(n_samples, n_features)
        
        # Validate target dimensions
        max_dim = min(data.shape[0], data.shape[1])
        target_dimensions = min(target_dimensions, max_dim)
        
        # Perform dimensionality reduction
        result = _analysis_engine.reduce_dimensionality(
            data=data,
            method=reduction_method,
            target_dim=target_dimensions,
            parameters=method_params
        )
        
        reduction_results = {
            "data_source": data_source,
            "method": result.method,
            "original_dimensions": result.original_dim,
            "target_dimensions": result.reduced_dim,
            "data_shape": [len(data), len(data[0])],
            "reduction_ratio": result.reduced_dim / result.original_dim,
            "reconstruction_error": result.reconstruction_error,
            "method_parameters": method_params or {},
            "reduced_at": datetime.now().isoformat()
        }
        
        if result.explained_variance:
            reduction_results.update({
                "explained_variance_ratio": result.explained_variance,
                "cumulative_variance": np.cumsum(result.explained_variance).tolist(),
                "variance_retained": sum(result.explained_variance)
            })
        
        if return_transformed_data:
            reduction_results["transformed_data"] = result.transformed_data
        else:
            reduction_results["transformed_data_shape"] = [len(result.transformed_data), len(result.transformed_data[0])]
        
        return reduction_results
        
    except Exception as e:
        logger.error(f"Dimensionality reduction failed: {e}")
        raise

async def analyze_data_distribution(
    data_source: str,
    analysis_type: str = "comprehensive",
    data_params: Optional[Dict[str, Any]] = None,
    visualization_config: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Analyze the distribution and characteristics of vector data.
    
    Args:
        data_source: Source of data to analyze
        analysis_type: Type of distribution analysis
        data_params: Parameters for data loading
        visualization_config: Configuration for visualization data
    
    Returns:
        Dict containing distribution analysis results
    """
    try:
        logger.info(f"Analyzing data distribution for {data_source}")
        
        # Load or generate data
        if data_source == "mock":
            n_samples = data_params.get("n_samples", 1000) if data_params else 1000
            n_features = data_params.get("n_features", 384) if data_params else 384
            data, _ = _analysis_engine._generate_mock_embeddings(n_samples, n_features)
        else:
            # Mock data loading
            logger.warning(f"Using mock data for source: {data_source}")
            n_samples = 500
            n_features = 384
            data, _ = _analysis_engine._generate_mock_embeddings(n_samples, n_features)
        
        # Calculate distribution statistics
        norms = np.linalg.norm(data, axis=1)
        means = np.mean(data, axis=0)
        stds = np.std(data, axis=0)
        
        # Feature statistics
        feature_stats = {
            "mean_values": {
                "mean": float(np.mean(means)),
                "std": float(np.std(means)),
                "min": float(np.min(means)),
                "max": float(np.max(means))
            },
            "std_values": {
                "mean": float(np.mean(stds)),
                "std": float(np.std(stds)),
                "min": float(np.min(stds)),
                "max": float(np.max(stds))
            }
        }
        
        # Vector norm statistics
        norm_stats = {
            "mean": float(np.mean(norms)),
            "std": float(np.std(norms)),
            "min": float(np.min(norms)),
            "max": float(np.max(norms)),
            "median": float(np.median(norms)),
            "q25": float(np.percentile(norms, 25)),
            "q75": float(np.percentile(norms, 75))
        }
        
        # Correlation and covariance analysis
        correlation_strength = float(np.mean(np.abs(np.corrcoef(data.T))))
        sparsity = float(np.mean(np.abs(data) < 1e-6))
        
        # Distance analysis (sample-based for efficiency)
        sample_size = min(100, len(data))
        sample_indices = np.random.choice(len(data), sample_size, replace=False)
        sample_data = data[sample_indices]
        
        # Pairwise distances
        from sklearn.metrics.pairwise import pairwise_distances
        distances = pairwise_distances(sample_data[:50], sample_data[:50])
        
        distance_stats = {
            "mean_distance": float(np.mean(distances[np.triu_indices_from(distances, k=1)])),
            "std_distance": float(np.std(distances[np.triu_indices_from(distances, k=1)])),
            "min_distance": float(np.min(distances[distances > 0])),
            "max_distance": float(np.max(distances))
        }
        
        results = {
            "data_source": data_source,
            "analysis_type": analysis_type,
            "data_shape": list(data.shape),
            "feature_statistics": feature_stats,
            "vector_norm_statistics": norm_stats,
            "distance_statistics": distance_stats,
            "correlation_strength": correlation_strength,
            "sparsity_ratio": sparsity,
            "data_quality_indicators": {
                "has_nans": bool(np.any(np.isnan(data))),
                "has_infs": bool(np.any(np.isinf(data))),
                "is_centered": abs(np.mean(data)) < 0.1,
                "is_normalized": 0.8 < np.mean(norms) < 1.2,
                "distribution_type": "normal" if norm_stats["std"] / norm_stats["mean"] < 0.5 else "diverse"
            },
            "analyzed_at": datetime.now().isoformat()
        }
        
        # Add visualization data if requested
        if visualization_config and visualization_config.get("include_histograms", False):
            # Sample data for histograms
            results["visualization_data"] = {
                "norm_histogram": {
                    "bins": np.histogram(norms, bins=20)[1].tolist(),
                    "counts": np.histogram(norms, bins=20)[0].tolist()
                },
                "feature_mean_histogram": {
                    "bins": np.histogram(means, bins=20)[1].tolist(), 
                    "counts": np.histogram(means, bins=20)[0].tolist()
                }
            }
        
        return results
        
    except Exception as e:
        logger.error(f"Data distribution analysis failed: {e}")
        raise
