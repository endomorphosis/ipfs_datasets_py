"""
Analysis Tools MCP Wrapper

This module provides MCP tool interfaces for data analysis functionality.
The core implementation is in ipfs_datasets_py.analytics.analysis_engine

All business logic should reside in the core module, and this file serves
as a thin wrapper to expose that functionality through the MCP interface.
"""

import logging
import numpy as np
from typing import Dict, Any, List, Optional, Union
from datetime import datetime

# Import from core analytics module
from ipfs_datasets_py.analytics import (
    AnalysisEngine,
    ClusteringAlgorithm,
    QualityMetric,
    DimensionalityMethod,
    ClusterResult,
    QualityAssessment,
    DimensionalityResult,
    get_analysis_engine
)

# Import accelerate integration with fallback
try:
    from ipfs_datasets_py.ml.accelerate_integration import (
        AccelerateManager,
        is_accelerate_available,
        get_accelerate_status
    )
    HAVE_ACCELERATE = True
except ImportError:
    HAVE_ACCELERATE = False
    AccelerateManager = None
    is_accelerate_available = lambda: False
    get_accelerate_status = lambda: {"available": False, "reason": "accelerate_integration not installed"}

logger = logging.getLogger(__name__)

# Get the global analysis engine instance
_analysis_engine = get_analysis_engine()


async def cluster_analysis(
    data_source: str = "mock",
    algorithm: str = "kmeans",
    n_clusters: Optional[int] = None,
    vectors: Optional[List[List[float]]] = None,
    data_params: Optional[Dict[str, Any]] = None,
    clustering_params: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Perform clustering analysis on embeddings or vector data.
    
    This is a thin wrapper around the core AnalysisEngine.perform_clustering method.
    
    Args:
        data_source: Source of data (collection, file, ids, or mock)
        algorithm: Clustering algorithm to use (kmeans, hierarchical, dbscan, etc.)
        n_clusters: Number of clusters (auto-determined if None)
        vectors: Optional pre-loaded vectors to cluster
        data_params: Parameters for data loading
        clustering_params: Parameters for clustering algorithm
    
    Returns:
        Dict containing clustering analysis results
    """
    try:
        source_label = "vectors" if vectors is not None else data_source
        logger.info(f"Performing {algorithm} clustering analysis on {source_label}")
        
        # Validate algorithm
        try:
            clustering_algo = ClusteringAlgorithm(algorithm)
        except ValueError:
            raise ValueError(f"Invalid algorithm: {algorithm}. Valid algorithms: {[a.value for a in ClusteringAlgorithm]}")
        
        # Load or generate data based on source
        if vectors is not None:
            data = np.array(vectors)
        elif data_source == "mock":
            n_samples = data_params.get("n_samples", 1000) if data_params else 1000
            n_features = data_params.get("n_features", 384) if data_params else 384
            data, _ = _analysis_engine._generate_mock_embeddings(n_samples, n_features)
        else:
            # Mock data loading for other sources
            logger.warning(f"Using mock data for source: {data_source}")
            n_samples = 500
            n_features = 384
            data, _ = _analysis_engine._generate_mock_embeddings(n_samples, n_features)
        
        # Perform clustering using core engine
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
        
        data_shape = list(data.shape) if hasattr(data, "shape") else [len(data), len(data[0]) if data else 0]
        
        return {
            "success": True,
            "status": "success",
            "data_source": data_source,
            "algorithm": result.algorithm,
            "n_clusters": result.n_clusters,
            "cluster_labels": result.labels,
            "centroids": result.centroids,
            "cluster_centers": result.centroids,
            "metrics": result.metrics,
            "cluster_sizes": cluster_sizes,
            "clusters": result.labels,
            "data_shape": data_shape,
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
    data_source: str = "mock",
    assessment_type: str = "comprehensive",
    metrics: Optional[List[str]] = None,
    data: Optional[Dict[str, Any]] = None,
    embeddings: Optional[List[List[float]]] = None,
    data_params: Optional[Dict[str, Any]] = None,
    outlier_detection: bool = True
) -> Dict[str, Any]:
    """
    Assess the quality of embeddings and vector data.
    
    This is a thin wrapper around the core AnalysisEngine.assess_quality method.
    
    Args:
        data_source: Source of data to assess
        assessment_type: Type of assessment to perform
        metrics: Specific quality metrics to compute
        data: Optional dict with 'vectors' and 'labels' keys
        embeddings: Optional pre-loaded embeddings
        data_params: Parameters for data loading
        outlier_detection: Whether to perform outlier detection
    
    Returns:
        Dict containing quality assessment results
    """
    try:
        # Extract embeddings from data if provided
        if data is not None and isinstance(data, dict) and data.get("vectors") is not None:
            embeddings = data.get("vectors")
            labels = data.get("labels")
        else:
            labels = None
        
        logger.info(f"Performing {assessment_type} quality assessment on {data_source}")
        
        # Load or use provided embeddings
        if embeddings is not None:
            embedding_data = np.array(embeddings)
        elif data_source == "mock":
            n_samples = data_params.get("n_samples", 500) if data_params else 500
            n_features = data_params.get("n_features", 384) if data_params else 384
            embedding_data, labels = _analysis_engine._generate_mock_embeddings(n_samples, n_features)
        else:
            # Mock data loading
            logger.warning(f"Using mock data for source: {data_source}")
            embedding_data, labels = _analysis_engine._generate_mock_embeddings(500, 384)
        
        # Convert metric strings to enum
        quality_metrics = None
        if metrics:
            quality_metrics = []
            for metric_str in metrics:
                try:
                    quality_metrics.append(QualityMetric(metric_str))
                except ValueError:
                    logger.warning(f"Unknown metric: {metric_str}, skipping")
        
        # Perform quality assessment using core engine
        result = _analysis_engine.assess_quality(
            data=embedding_data,
            labels=labels,
            metrics=quality_metrics
        )
        
        return {
            "success": True,
            "status": "success",
            "data_source": data_source,
            "assessment_type": assessment_type,
            "overall_score": result.overall_score,
            "metric_scores": result.metric_scores,
            "outliers": result.outliers if outlier_detection else [],
            "n_outliers": len(result.outliers) if outlier_detection else 0,
            "recommendations": result.recommendations,
            "data_statistics": result.data_stats,
            "analyzed_at": datetime.now().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Quality assessment failed: {e}")
        raise


async def dimensionality_reduction(
    data_source: str = "mock",
    method: str = "pca",
    n_components: int = 2,
    vectors: Optional[List[List[float]]] = None,
    data_params: Optional[Dict[str, Any]] = None,
    method_params: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Reduce the dimensionality of embeddings using various algorithms.
    
    This is a thin wrapper around the core AnalysisEngine.reduce_dimensionality method.
    
    Args:
        data_source: Source of data
        method: Dimensionality reduction method (pca, tsne, umap, etc.)
        n_components: Target number of dimensions
        vectors: Optional pre-loaded vectors
        data_params: Parameters for data loading
        method_params: Parameters for the reduction method
    
    Returns:
        Dict containing dimensionality reduction results
    """
    try:
        logger.info(f"Performing {method} dimensionality reduction to {n_components} dimensions")
        
        # Validate method
        try:
            reduction_method = DimensionalityMethod(method)
        except ValueError:
            raise ValueError(f"Invalid method: {method}. Valid methods: {[m.value for m in DimensionalityMethod]}")
        
        # Load or use provided vectors
        if vectors is not None:
            data = np.array(vectors)
        elif data_source == "mock":
            n_samples = data_params.get("n_samples", 1000) if data_params else 1000
            n_features = data_params.get("n_features", 384) if data_params else 384
            data, _ = _analysis_engine._generate_mock_embeddings(n_samples, n_features)
        else:
            # Mock data loading
            logger.warning(f"Using mock data for source: {data_source}")
            data, _ = _analysis_engine._generate_mock_embeddings(1000, 384)
        
        # Perform dimensionality reduction using core engine
        result = _analysis_engine.reduce_dimensionality(
            data=data,
            method=reduction_method,
            n_components=n_components,
            parameters=method_params
        )
        
        return {
            "success": True,
            "status": "success",
            "data_source": data_source,
            "method": result.method,
            "original_dimensions": result.original_dim,
            "reduced_dimensions": result.reduced_dim,
            "transformed_data": result.transformed_data,
            "explained_variance": result.explained_variance,
            "reconstruction_error": result.reconstruction_error,
            "n_samples": len(result.transformed_data),
            "analyzed_at": datetime.now().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Dimensionality reduction failed: {e}")
        raise


async def analyze_data_distribution(
    data_source: str,
    analysis_type: str = "comprehensive",
    vectors: Optional[List[List[float]]] = None,
    data_params: Optional[Dict[str, Any]] = None,
    visualization_config: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Analyze the statistical distribution of embedding vectors.
    
    Args:
        data_source: Source of data to analyze
        analysis_type: Type of analysis (basic, comprehensive, detailed)
        vectors: Optional pre-loaded vectors
        data_params: Parameters for data loading
        visualization_config: Configuration for visualization data
    
    Returns:
        Dict containing distribution analysis results
    """
    try:
        logger.info(f"Analyzing data distribution for {data_source}")
        
        # Load or use provided vectors
        if vectors is not None:
            data = np.array(vectors)
        elif data_source == "mock":
            n_samples = data_params.get("n_samples", 1000) if data_params else 1000
            n_features = data_params.get("n_features", 384) if data_params else 384
            data, _ = _analysis_engine._generate_mock_embeddings(n_samples, n_features)
        else:
            # For other sources, use mock data
            logger.warning(f"Using mock data for source: {data_source}")
            data, _ = _analysis_engine._generate_mock_embeddings(1000, 384)
        
        # Calculate vector norms
        norms = np.linalg.norm(data, axis=1)
        
        # Feature statistics
        means = np.mean(data, axis=0)
        stds = np.std(data, axis=0)
        
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
        
        # Correlation and sparsity
        correlation_strength = float(np.mean(np.abs(np.corrcoef(data.T))))
        sparsity = float(np.mean(np.abs(data) < 1e-6))
        
        # Distance analysis (sample-based for efficiency)
        try:
            from sklearn.metrics.pairwise import pairwise_distances
            sample_size = min(50, len(data))
            sample_indices = np.random.choice(len(data), sample_size, replace=False)
            sample_data = data[sample_indices]
            distances = pairwise_distances(sample_data, sample_data)
            
            distance_stats = {
                "mean_distance": float(np.mean(distances[np.triu_indices_from(distances, k=1)])),
                "std_distance": float(np.std(distances[np.triu_indices_from(distances, k=1)])),
                "min_distance": float(np.min(distances[distances > 0])),
                "max_distance": float(np.max(distances))
            }
        except ImportError:
            distance_stats = {"note": "sklearn not available for distance calculation"}
        
        results = {
            "success": True,
            "status": "success",
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


# Legacy function names for backward compatibility
async def perform_clustering_analysis(*args, **kwargs):
    """Legacy wrapper for cluster_analysis."""
    return await cluster_analysis(*args, **kwargs)


async def assess_embedding_quality(*args, **kwargs):
    """Legacy wrapper for quality_assessment."""
    return await quality_assessment(*args, **kwargs)


async def reduce_dimensionality(*args, **kwargs):
    """Legacy wrapper for dimensionality_reduction."""
    return await dimensionality_reduction(*args, **kwargs)


# Export additional functions for compatibility
def detect_outliers(data: Union[List[List[float]], np.ndarray], threshold: float = 3.0) -> List[int]:
    """Detect outliers in data using z-score method."""
    if isinstance(data, list):
        data = np.array(data)
    
    norms = np.linalg.norm(data, axis=1)
    z_scores = np.abs((norms - np.mean(norms)) / np.std(norms))
    outlier_indices = np.where(z_scores > threshold)[0].tolist()
    
    return outlier_indices


def analyze_diversity(data: Union[List[List[float]], np.ndarray]) -> Dict[str, float]:
    """Analyze diversity/spread of data."""
    if isinstance(data, list):
        data = np.array(data)
    
    return {
        "variance": float(np.var(data)),
        "std": float(np.std(data)),
        "range": float(np.max(data) - np.min(data)),
        "coefficient_of_variation": float(np.std(data) / (np.mean(data) + 1e-10))
    }


def detect_drift(
    old_data: Union[List[List[float]], np.ndarray],
    new_data: Union[List[List[float]], np.ndarray]
) -> Dict[str, Any]:
    """Detect data drift between two datasets."""
    if isinstance(old_data, list):
        old_data = np.array(old_data)
    if isinstance(new_data, list):
        new_data = np.array(new_data)
    
    old_mean = np.mean(old_data, axis=0)
    new_mean = np.mean(new_data, axis=0)
    
    drift_magnitude = float(np.linalg.norm(new_mean - old_mean))
    
    return {
        "drift_detected": drift_magnitude > 0.1,
        "drift_magnitude": drift_magnitude,
        "old_mean_norm": float(np.linalg.norm(old_mean)),
        "new_mean_norm": float(np.linalg.norm(new_mean))
    }


def analyze_similarity_patterns(data: Union[List[List[float]], np.ndarray]) -> Dict[str, Any]:
    """Analyze similarity patterns in data."""
    if isinstance(data, list):
        data = np.array(data)
    
    # Sample for efficiency
    sample_size = min(100, len(data))
    sample_indices = np.random.choice(len(data), sample_size, replace=False)
    sample_data = data[sample_indices]
    
    try:
        from sklearn.metrics.pairwise import cosine_similarity
        similarities = cosine_similarity(sample_data)
        
        return {
            "mean_similarity": float(np.mean(similarities)),
            "std_similarity": float(np.std(similarities)),
            "min_similarity": float(np.min(similarities)),
            "max_similarity": float(np.max(similarities))
        }
    except ImportError:
        # Fallback without sklearn
        return {
            "note": "sklearn not available for similarity calculation"
        }
