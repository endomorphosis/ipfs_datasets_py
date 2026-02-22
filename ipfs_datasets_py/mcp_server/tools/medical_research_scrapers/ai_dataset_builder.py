"""AI-Powered Dataset Builder and Analyzer for Medical Research (thin MCP wrapper).

Business logic (``DatasetMetrics``, ``SyntheticDataConfig``, ``AIDatasetBuilder``) lives in:
    ipfs_datasets_py.scrapers.medical.ai_dataset_builder_engine
"""

from typing import Dict, List, Any, Optional
import logging

from ipfs_datasets_py.scrapers.medical.ai_dataset_builder_engine import (  # noqa: F401
    DatasetMetrics,
    SyntheticDataConfig,
    AIDatasetBuilder,
)

logger = logging.getLogger(__name__)


# MCP Tool Functions

def build_medical_dataset(
    scraped_data: List[Dict[str, Any]],
    filter_criteria: Optional[Dict[str, Any]] = None,
    model_name: str = "meta-llama/Llama-2-7b-hf"
) -> Dict[str, Any]:
    """
    MCP tool: Build a structured dataset from scraped medical research.
    
    Args:
        scraped_data: List of scraped medical research records
        filter_criteria: Optional filtering criteria
        model_name: HuggingFace model to use for AI operations
    
    Returns:
        Built dataset with metrics
    """
    builder = AIDatasetBuilder(model_name=model_name)
    return builder.build_dataset(scraped_data, filter_criteria)


def analyze_medical_dataset(
    dataset: List[Dict[str, Any]],
    model_name: str = "meta-llama/Llama-2-7b-hf"
) -> Dict[str, Any]:
    """
    MCP tool: Analyze medical research dataset using AI.
    
    Args:
        dataset: Dataset to analyze
        model_name: HuggingFace model to use
    
    Returns:
        Analysis results with insights and metrics
    """
    builder = AIDatasetBuilder(model_name=model_name)
    return builder.analyze_dataset(dataset)


def transform_medical_dataset(
    dataset: List[Dict[str, Any]],
    transformation_type: str,
    parameters: Optional[Dict[str, Any]] = None,
    model_name: str = "meta-llama/Llama-2-7b-hf"
) -> Dict[str, Any]:
    """
    MCP tool: Transform medical dataset using AI.
    
    Args:
        dataset: Dataset to transform
        transformation_type: Type (summarize, extract_entities, normalize)
        parameters: Optional transformation parameters
        model_name: HuggingFace model to use
    
    Returns:
        Transformed dataset
    """
    builder = AIDatasetBuilder(model_name=model_name)
    return builder.transform_dataset(dataset, transformation_type, parameters)


def generate_synthetic_medical_data(
    template_data: List[Dict[str, Any]],
    num_samples: int = 10,
    model_name: str = "meta-llama/Llama-2-7b-hf",
    temperature: float = 0.7
) -> Dict[str, Any]:
    """
    MCP tool: Generate synthetic medical research data.
    
    Args:
        template_data: Template data for generation
        num_samples: Number of synthetic samples to generate
        model_name: HuggingFace model to use
        temperature: Generation temperature
    
    Returns:
        Generated synthetic data
    """
    config = SyntheticDataConfig(
        base_model=model_name,
        temperature=temperature,
        num_samples=num_samples
    )
    builder = AIDatasetBuilder(model_name=model_name)
    return builder.generate_synthetic_data(template_data, config)
