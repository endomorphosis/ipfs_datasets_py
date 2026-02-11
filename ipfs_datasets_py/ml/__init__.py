"""
Machine Learning components for GraphRAG content analysis and optimization.

This package provides ML-powered content classification, quality assessment,
and advanced analytics capabilities for the GraphRAG website processing system.
"""

from __future__ import annotations

import importlib
from typing import Any


_LAZY_EXPORTS: dict[str, tuple[str, str]] = {
    # Content Classification
    "ContentClassificationPipeline": ("content_classification", "ContentClassificationPipeline"),
    "QualityClassifier": ("content_classification", "QualityClassifier"),
    "TopicClassifier": ("content_classification", "TopicClassifier"),
    "SentimentAnalyzer": ("content_classification", "SentimentAnalyzer"),
    "ContentAnomalyDetector": ("content_classification", "ContentAnomalyDetector"),
    "ContentAnalysisReport": ("content_classification", "ContentAnalysisReport"),
    "ContentAnalysis": ("content_classification", "ContentAnalysis"),
    "analyze_website_content": ("content_classification", "analyze_website_content"),

    # Production Models
    "ProductionMLModelServer": ("quality_models", "ProductionMLModelServer"),
    "ProductionQualityModel": ("quality_models", "ProductionQualityModel"),
    "ProductionTopicModel": ("quality_models", "ProductionTopicModel"),
    "ModelMetadata": ("quality_models", "ModelMetadata"),
    "ModelPrediction": ("quality_models", "ModelPrediction"),
    "BatchPredictionResult": ("quality_models", "BatchPredictionResult"),
    "quick_quality_assessment": ("quality_models", "quick_quality_assessment"),
    "quick_topic_classification": ("quality_models", "quick_topic_classification"),
}

__all__ = [
    # Content Classification
    'ContentClassificationPipeline',
    'QualityClassifier', 
    'TopicClassifier',
    'SentimentAnalyzer',
    'ContentAnomalyDetector',
    'ContentAnalysisReport',
    'ContentAnalysis',
    'analyze_website_content',
    
    # Production Models
    'ProductionMLModelServer',
    'ProductionQualityModel',
    'ProductionTopicModel',
    'ModelMetadata',
    'ModelPrediction',
    'BatchPredictionResult',
    'quick_quality_assessment',
    'quick_topic_classification'
]


def __getattr__(name: str) -> Any:  # pragma: no cover
    target = _LAZY_EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module '{__name__}' has no attribute '{name}'")
    mod_name, attr_name = target
    mod = importlib.import_module(f"{__name__}.{mod_name}")
    value = getattr(mod, attr_name)
    globals()[name] = value
    return value