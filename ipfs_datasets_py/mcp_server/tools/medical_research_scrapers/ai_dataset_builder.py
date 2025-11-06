"""
AI-Powered Dataset Builder and Analyzer for Medical Research.

This module integrates with ipfs_accelerate_py to provide AI model capabilities
for building, filtering, analyzing, and generating synthetic medical research data.

Features:
- Dataset building from scraped medical research
- AI-powered filtering and quality assessment
- Data transformation and extrapolation
- Synthetic data generation for testing and evaluation
"""

from typing import Dict, List, Any, Optional, Union
from dataclasses import dataclass, field
from datetime import datetime
import json
import logging

# Try to import ipfs_accelerate_py - graceful fallback if not available
try:
    from ipfs_accelerate_py import (
        HuggingFaceModel,
        ModelConfig,
        InferenceEngine
    )
    ACCELERATE_AVAILABLE = True
except ImportError:
    ACCELERATE_AVAILABLE = False
    logging.warning("ipfs_accelerate_py not available - using mock implementations")


@dataclass
class DatasetMetrics:
    """Metrics for evaluating dataset quality."""
    total_records: int = 0
    unique_records: int = 0
    completeness_score: float = 0.0
    quality_score: float = 0.0
    relevance_score: float = 0.0
    diversity_score: float = 0.0
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())


@dataclass
class SyntheticDataConfig:
    """Configuration for synthetic data generation."""
    base_model: str = "meta-llama/Llama-2-7b-hf"
    temperature: float = 0.7
    top_p: float = 0.9
    max_length: int = 512
    num_samples: int = 10
    seed: Optional[int] = None


class AIDatasetBuilder:
    """
    AI-powered dataset builder using HuggingFace models via ipfs_accelerate_py.
    
    This class provides capabilities to:
    - Build structured datasets from scraped medical research
    - Filter and clean data using AI models
    - Analyze data quality and relevance
    - Generate synthetic data for augmentation
    """
    
    def __init__(
        self,
        model_name: str = "meta-llama/Llama-2-7b-hf",
        use_accelerate: bool = True
    ):
        """
        Initialize the AI dataset builder.
        
        Args:
            model_name: HuggingFace model identifier
            use_accelerate: Whether to use ipfs_accelerate_py (if available)
        """
        self.model_name = model_name
        self.use_accelerate = use_accelerate and ACCELERATE_AVAILABLE
        self.logger = logging.getLogger(__name__)
        
        if self.use_accelerate:
            self._initialize_accelerate_model()
        else:
            self.logger.info("Using mock model implementations")
            self.model = None
    
    def _initialize_accelerate_model(self):
        """Initialize the ipfs_accelerate_py model."""
        try:
            config = ModelConfig(
                model_name=self.model_name,
                device="auto",
                torch_dtype="auto"
            )
            self.model = HuggingFaceModel(config)
            self.logger.info(f"Initialized model: {self.model_name}")
        except Exception as e:
            self.logger.error(f"Failed to initialize model: {e}")
            self.model = None
            self.use_accelerate = False
    
    def build_dataset(
        self,
        scraped_data: List[Dict[str, Any]],
        filter_criteria: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Build a structured dataset from scraped medical research data.
        
        Args:
            scraped_data: List of scraped articles/trials from PubMed or ClinicalTrials.gov
            filter_criteria: Optional filtering criteria (relevance, quality thresholds)
        
        Returns:
            Dictionary with built dataset and metrics
        """
        self.logger.info(f"Building dataset from {len(scraped_data)} records")
        
        # Apply AI-powered filtering if model is available
        if self.use_accelerate and self.model:
            filtered_data = self._ai_filter_data(scraped_data, filter_criteria)
        else:
            filtered_data = self._basic_filter_data(scraped_data, filter_criteria)
        
        # Calculate dataset metrics
        metrics = self._calculate_metrics(filtered_data)
        
        return {
            "success": True,
            "dataset": filtered_data,
            "metrics": metrics.__dict__,
            "original_count": len(scraped_data),
            "filtered_count": len(filtered_data),
            "model_used": self.model_name if self.use_accelerate else "basic_filtering"
        }
    
    def _ai_filter_data(
        self,
        data: List[Dict[str, Any]],
        criteria: Optional[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Filter data using AI model for relevance and quality assessment."""
        filtered = []
        
        for item in data:
            # Extract text for analysis
            text = self._extract_text_for_analysis(item)
            
            # Use model to assess relevance and quality
            prompt = self._create_assessment_prompt(text, criteria)
            
            try:
                result = self.model.generate(prompt, max_length=100, temperature=0.3)
                
                # Parse model output to determine if item passes filter
                if self._parse_filter_decision(result):
                    filtered.append(item)
            except Exception as e:
                self.logger.warning(f"AI filtering failed for item: {e}")
                # Fallback to including the item
                filtered.append(item)
        
        return filtered
    
    def _basic_filter_data(
        self,
        data: List[Dict[str, Any]],
        criteria: Optional[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Basic keyword-based filtering without AI model."""
        if not criteria:
            return data
        
        filtered = []
        keywords = criteria.get('keywords', [])
        min_quality = criteria.get('min_quality', 0.0)
        
        for item in data:
            # Simple keyword matching
            text = self._extract_text_for_analysis(item).lower()
            
            if keywords:
                if any(kw.lower() in text for kw in keywords):
                    filtered.append(item)
            else:
                filtered.append(item)
        
        return filtered
    
    def analyze_dataset(
        self,
        dataset: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Analyze dataset using AI models to extract insights.
        
        Args:
            dataset: List of dataset records
        
        Returns:
            Dictionary with analysis results
        """
        self.logger.info(f"Analyzing dataset with {len(dataset)} records")
        
        metrics = self._calculate_metrics(dataset)
        
        # AI-powered analysis if available
        if self.use_accelerate and self.model:
            insights = self._ai_analyze_patterns(dataset)
        else:
            insights = self._basic_analyze_patterns(dataset)
        
        return {
            "success": True,
            "metrics": metrics.__dict__,
            "insights": insights,
            "total_records": len(dataset)
        }
    
    def _ai_analyze_patterns(self, dataset: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Use AI model to analyze patterns in the dataset."""
        # Sample dataset for analysis
        sample_size = min(10, len(dataset))
        sample = dataset[:sample_size]
        
        # Create analysis prompt
        texts = [self._extract_text_for_analysis(item) for item in sample]
        combined_text = "\n\n".join(texts[:3])  # Use first 3 for context
        
        prompt = f"""Analyze the following medical research dataset sample and identify key patterns, themes, and insights:

{combined_text}

Provide a structured analysis including:
1. Main research themes
2. Common methodologies
3. Key findings patterns
4. Gaps or opportunities
"""
        
        try:
            analysis_result = self.model.generate(prompt, max_length=500, temperature=0.5)
            
            return {
                "ai_analysis": analysis_result,
                "model_used": self.model_name,
                "sample_size": sample_size
            }
        except Exception as e:
            self.logger.error(f"AI analysis failed: {e}")
            return {
                "error": str(e),
                "fallback": "AI analysis unavailable"
            }
    
    def _basic_analyze_patterns(self, dataset: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Basic pattern analysis without AI model."""
        # Extract common keywords
        all_text = " ".join([self._extract_text_for_analysis(item) for item in dataset[:100]])
        words = all_text.lower().split()
        
        # Count word frequencies (basic)
        from collections import Counter
        common_words = Counter(words).most_common(20)
        
        return {
            "common_terms": [{"term": word, "count": count} for word, count in common_words],
            "method": "basic_frequency_analysis"
        }
    
    def transform_dataset(
        self,
        dataset: List[Dict[str, Any]],
        transformation_type: str,
        parameters: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Transform dataset using AI models.
        
        Args:
            dataset: Dataset to transform
            transformation_type: Type of transformation (normalize, summarize, extract_entities)
            parameters: Optional transformation parameters
        
        Returns:
            Transformed dataset
        """
        self.logger.info(f"Transforming dataset with type: {transformation_type}")
        
        if transformation_type == "summarize":
            return self._summarize_dataset(dataset, parameters)
        elif transformation_type == "extract_entities":
            return self._extract_entities(dataset, parameters)
        elif transformation_type == "normalize":
            return self._normalize_dataset(dataset, parameters)
        else:
            return {"success": False, "error": f"Unknown transformation type: {transformation_type}"}
    
    def _summarize_dataset(
        self,
        dataset: List[Dict[str, Any]],
        parameters: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Generate summaries for dataset records."""
        summaries = []
        
        for item in dataset[:10]:  # Limit for performance
            text = self._extract_text_for_analysis(item)
            
            if self.use_accelerate and self.model:
                prompt = f"Summarize the following medical research in 2-3 sentences:\n\n{text[:1000]}"
                try:
                    summary = self.model.generate(prompt, max_length=150, temperature=0.3)
                    summaries.append({
                        "original_id": item.get('pmid') or item.get('nct_id'),
                        "summary": summary
                    })
                except Exception as e:
                    self.logger.warning(f"Summarization failed: {e}")
                    summaries.append({
                        "original_id": item.get('pmid') or item.get('nct_id'),
                        "summary": text[:200] + "..."
                    })
            else:
                # Basic truncation for mock
                summaries.append({
                    "original_id": item.get('pmid') or item.get('nct_id'),
                    "summary": text[:200] + "..."
                })
        
        return {
            "success": True,
            "summaries": summaries,
            "count": len(summaries)
        }
    
    def _extract_entities(
        self,
        dataset: List[Dict[str, Any]],
        parameters: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Extract medical entities (conditions, treatments, outcomes)."""
        entities = []
        
        for item in dataset[:10]:
            text = self._extract_text_for_analysis(item)
            
            if self.use_accelerate and self.model:
                prompt = f"""Extract medical entities from this text:

{text[:800]}

List:
- Conditions/Diseases
- Treatments/Interventions
- Outcomes
- Measurements

Format as JSON."""
                
                try:
                    result = self.model.generate(prompt, max_length=300, temperature=0.2)
                    entities.append({
                        "record_id": item.get('pmid') or item.get('nct_id'),
                        "entities": result
                    })
                except Exception as e:
                    self.logger.warning(f"Entity extraction failed: {e}")
            else:
                # Mock entity extraction
                entities.append({
                    "record_id": item.get('pmid') or item.get('nct_id'),
                    "entities": {"conditions": [], "treatments": [], "outcomes": []}
                })
        
        return {
            "success": True,
            "extracted_entities": entities,
            "count": len(entities)
        }
    
    def _normalize_dataset(
        self,
        dataset: List[Dict[str, Any]],
        parameters: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Normalize dataset format and structure."""
        normalized = []
        
        for item in dataset:
            # Create normalized record
            normalized_item = {
                "id": item.get('pmid') or item.get('nct_id'),
                "title": item.get('title', ''),
                "abstract": item.get('abstract', ''),
                "date": item.get('publication_date') or item.get('start_date'),
                "type": "pubmed" if 'pmid' in item else "clinical_trial",
                "metadata": {k: v for k, v in item.items() if k not in ['title', 'abstract']}
            }
            normalized.append(normalized_item)
        
        return {
            "success": True,
            "normalized_dataset": normalized,
            "count": len(normalized)
        }
    
    def generate_synthetic_data(
        self,
        template_data: List[Dict[str, Any]],
        config: Optional[SyntheticDataConfig] = None
    ) -> Dict[str, Any]:
        """
        Generate synthetic medical research data for testing and evaluation.
        
        Args:
            template_data: Sample data to use as template
            config: Configuration for synthetic data generation
        
        Returns:
            Generated synthetic data
        """
        if config is None:
            config = SyntheticDataConfig()
        
        self.logger.info(f"Generating {config.num_samples} synthetic samples")
        
        if not self.use_accelerate or not self.model:
            return self._generate_mock_synthetic_data(template_data, config)
        
        synthetic_samples = []
        
        # Use template data to create variations
        for i in range(config.num_samples):
            template = template_data[i % len(template_data)]
            
            prompt = self._create_synthetic_generation_prompt(template)
            
            try:
                synthetic_text = self.model.generate(
                    prompt,
                    max_length=config.max_length,
                    temperature=config.temperature,
                    top_p=config.top_p
                )
                
                synthetic_samples.append({
                    "id": f"synthetic_{i+1}",
                    "content": synthetic_text,
                    "template_id": template.get('pmid') or template.get('nct_id'),
                    "generated_at": datetime.now().isoformat()
                })
            except Exception as e:
                self.logger.error(f"Synthetic generation failed for sample {i}: {e}")
        
        return {
            "success": True,
            "synthetic_data": synthetic_samples,
            "count": len(synthetic_samples),
            "config": config.__dict__
        }
    
    def _generate_mock_synthetic_data(
        self,
        template_data: List[Dict[str, Any]],
        config: SyntheticDataConfig
    ) -> Dict[str, Any]:
        """Generate mock synthetic data without AI model."""
        synthetic_samples = []
        
        for i in range(min(config.num_samples, 5)):  # Limit for mock
            template = template_data[i % len(template_data)]
            
            # Create variation by modifying template
            synthetic_samples.append({
                "id": f"synthetic_{i+1}",
                "content": f"[Mock] Variation of: {template.get('title', 'Unknown')}",
                "template_id": template.get('pmid') or template.get('nct_id'),
                "generated_at": datetime.now().isoformat(),
                "note": "Mock data - ipfs_accelerate_py not available"
            })
        
        return {
            "success": True,
            "synthetic_data": synthetic_samples,
            "count": len(synthetic_samples),
            "config": config.__dict__,
            "mock": True
        }
    
    def _create_synthetic_generation_prompt(self, template: Dict[str, Any]) -> str:
        """Create prompt for synthetic data generation."""
        title = template.get('title', '')
        abstract = template.get('abstract', '')
        
        return f"""Generate a synthetic medical research article similar to this template:

Title: {title}
Abstract: {abstract[:300]}

Create a NEW article with:
- Similar research topic and methodology
- Different specific findings
- Plausible medical data
- Academic writing style

New Article:"""
    
    def _extract_text_for_analysis(self, item: Dict[str, Any]) -> str:
        """Extract text content from dataset item."""
        parts = []
        
        if 'title' in item:
            parts.append(item['title'])
        if 'abstract' in item:
            parts.append(item['abstract'])
        if 'summary' in item:
            parts.append(item['summary'])
        
        return " ".join(parts)
    
    def _create_assessment_prompt(
        self,
        text: str,
        criteria: Optional[Dict[str, Any]]
    ) -> str:
        """Create prompt for AI assessment."""
        criteria_str = json.dumps(criteria) if criteria else "general quality and relevance"
        
        return f"""Assess the following medical research text for: {criteria_str}

Text: {text[:500]}

Is this text relevant and high quality? Answer YES or NO and briefly explain."""
    
    def _parse_filter_decision(self, model_output: str) -> bool:
        """Parse model output to determine filter decision."""
        output_lower = model_output.lower()
        return "yes" in output_lower and "no" not in output_lower[:20]
    
    def _calculate_metrics(self, dataset: List[Dict[str, Any]]) -> DatasetMetrics:
        """Calculate quality metrics for the dataset."""
        if not dataset:
            return DatasetMetrics()
        
        total = len(dataset)
        
        # Check for unique records
        ids = [item.get('pmid') or item.get('nct_id') for item in dataset]
        unique = len(set(filter(None, ids)))
        
        # Completeness: percentage with key fields
        complete_records = sum(
            1 for item in dataset
            if item.get('title') and (item.get('abstract') or item.get('summary'))
        )
        completeness = complete_records / total if total > 0 else 0
        
        # Mock quality and relevance scores (would use AI in production)
        quality_score = 0.75 + (completeness * 0.15)  # 0.75-0.90 range
        relevance_score = 0.70 + (completeness * 0.20)  # 0.70-0.90 range
        diversity_score = unique / total if total > 0 else 0
        
        return DatasetMetrics(
            total_records=total,
            unique_records=unique,
            completeness_score=round(completeness, 3),
            quality_score=round(quality_score, 3),
            relevance_score=round(relevance_score, 3),
            diversity_score=round(diversity_score, 3)
        )


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
