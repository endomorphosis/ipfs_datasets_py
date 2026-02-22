"""AI Dataset Builder engine — canonical business-logic location.

Contains ``DatasetMetrics``, ``SyntheticDataConfig``, and ``AIDatasetBuilder``
for AI-powered medical research dataset operations using HuggingFace models
via ``ipfs_accelerate_py`` (graceful fallback when not installed).

Previously embedded inside the MCP tool wrapper at
``ipfs_datasets_py/mcp_server/tools/medical_research_scrapers/ai_dataset_builder.py``.

Keeping them here means the same logic can be used from:
- ``ipfs_datasets_py.scrapers.medical.ai_dataset_builder_engine`` (package import)
- ``ipfs_datasets_py-cli medical dataset ...``                      (CLI)
- The MCP server tool (thin wrapper in tools/medical_research_scrapers/)
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

# Try to import ipfs_accelerate_py — graceful fallback if not available
try:
    from ipfs_accelerate_py import HuggingFaceModel, InferenceEngine, ModelConfig  # type: ignore

    ACCELERATE_AVAILABLE = True
except ImportError:
    ACCELERATE_AVAILABLE = False
    logging.warning("ipfs_accelerate_py not available — using mock implementations")


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# AI Dataset Builder class
# ---------------------------------------------------------------------------

class AIDatasetBuilder:
    """AI-powered dataset builder using HuggingFace models via ipfs_accelerate_py.

    Capabilities:
    - Build structured datasets from scraped medical research.
    - Filter and clean data using AI models.
    - Analyse data quality and relevance.
    - Generate synthetic data for augmentation.
    """

    def __init__(
        self,
        model_name: str = "meta-llama/Llama-2-7b-hf",
        use_accelerate: bool = True,
    ) -> None:
        self.model_name = model_name
        self.use_accelerate = use_accelerate and ACCELERATE_AVAILABLE
        self.logger = logging.getLogger(self.__class__.__name__)
        self.model = None

        if self.use_accelerate:
            self._initialize_accelerate_model()
        else:
            self.logger.info("Using mock model implementations")

    # ------------------------------------------------------------------
    # Initialisation
    # ------------------------------------------------------------------

    def _initialize_accelerate_model(self) -> None:
        """Initialise the ipfs_accelerate_py model."""
        try:
            config = ModelConfig(
                model_name=self.model_name,
                device="auto",
                torch_dtype="auto",
            )
            self.model = HuggingFaceModel(config)
            self.logger.info("Initialised model: %s", self.model_name)
        except Exception as exc:
            self.logger.error("Failed to initialise model: %s", exc)
            self.model = None
            self.use_accelerate = False

    # ------------------------------------------------------------------
    # Core public methods
    # ------------------------------------------------------------------

    def build_dataset(
        self,
        scraped_data: List[Dict[str, Any]],
        filter_criteria: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Build a structured dataset from scraped medical research data.

        Args:
            scraped_data:     List of scraped articles/trials.
            filter_criteria:  Optional filtering criteria.

        Returns:
            Dict with ``success``, ``dataset``, ``metrics``, ``original_count``,
            ``filtered_count``, ``model_used``.
        """
        self.logger.info("Building dataset from %d records", len(scraped_data))

        if self.use_accelerate and self.model:
            filtered_data = self._ai_filter_data(scraped_data, filter_criteria)
        else:
            filtered_data = self._basic_filter_data(scraped_data, filter_criteria)

        metrics = self._calculate_metrics(filtered_data)
        return {
            "success": True,
            "dataset": filtered_data,
            "metrics": metrics.__dict__,
            "original_count": len(scraped_data),
            "filtered_count": len(filtered_data),
            "model_used": self.model_name if self.use_accelerate else "basic_filtering",
        }

    def analyze_dataset(self, dataset: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Analyse dataset using AI models to extract insights.

        Args:
            dataset: List of dataset records.

        Returns:
            Dict with ``success``, ``metrics``, ``insights``, ``total_records``.
        """
        self.logger.info("Analysing dataset with %d records", len(dataset))
        metrics = self._calculate_metrics(dataset)

        insights = (
            self._ai_analyze_patterns(dataset)
            if self.use_accelerate and self.model
            else self._basic_analyze_patterns(dataset)
        )
        return {
            "success": True,
            "metrics": metrics.__dict__,
            "insights": insights,
            "total_records": len(dataset),
        }

    def transform_dataset(
        self,
        dataset: List[Dict[str, Any]],
        transformation_type: str,
        parameters: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Transform dataset using AI models.

        Args:
            dataset:             Dataset records.
            transformation_type: One of ``summarize``, ``extract_entities``, ``normalize``.
            parameters:          Optional transformation parameters.

        Returns:
            Transformed dataset dict.
        """
        self.logger.info("Transforming dataset with type: %s", transformation_type)

        if transformation_type == "summarize":
            return self._summarize_dataset(dataset, parameters)
        elif transformation_type == "extract_entities":
            return self._extract_entities(dataset, parameters)
        elif transformation_type == "normalize":
            return self._normalize_dataset(dataset, parameters)
        return {"success": False, "error": f"Unknown transformation type: {transformation_type}"}

    def generate_synthetic_data(
        self,
        template_data: List[Dict[str, Any]],
        config: Optional[SyntheticDataConfig] = None,
    ) -> Dict[str, Any]:
        """Generate synthetic medical research data for testing.

        Args:
            template_data: Sample data to use as template.
            config:        Generation configuration.

        Returns:
            Dict with ``success``, ``synthetic_data``, ``count``, ``config``.
        """
        if config is None:
            config = SyntheticDataConfig()
        self.logger.info("Generating %d synthetic samples", config.num_samples)

        if not self.use_accelerate or not self.model:
            return self._generate_mock_synthetic_data(template_data, config)

        synthetic_samples: List[Dict[str, Any]] = []
        for i in range(config.num_samples):
            template = template_data[i % len(template_data)]
            prompt = self._create_synthetic_generation_prompt(template)
            try:
                text = self.model.generate(
                    prompt,
                    max_length=config.max_length,
                    temperature=config.temperature,
                    top_p=config.top_p,
                )
                synthetic_samples.append({
                    "id": f"synthetic_{i + 1}",
                    "content": text,
                    "template_id": template.get("pmid") or template.get("nct_id"),
                    "generated_at": datetime.now().isoformat(),
                })
            except Exception as exc:
                self.logger.error("Synthetic generation failed for sample %d: %s", i, exc)

        return {
            "success": True,
            "synthetic_data": synthetic_samples,
            "count": len(synthetic_samples),
            "config": config.__dict__,
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _ai_filter_data(
        self,
        data: List[Dict[str, Any]],
        criteria: Optional[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        filtered: List[Dict[str, Any]] = []
        for item in data:
            text = self._extract_text_for_analysis(item)
            prompt = self._create_assessment_prompt(text, criteria)
            try:
                result = self.model.generate(prompt, max_length=100, temperature=0.3)
                if self._parse_filter_decision(result):
                    filtered.append(item)
            except Exception as exc:
                self.logger.warning("AI filtering failed for item: %s", exc)
                filtered.append(item)
        return filtered

    def _basic_filter_data(
        self,
        data: List[Dict[str, Any]],
        criteria: Optional[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        if not criteria:
            return data
        keywords: List[str] = criteria.get("keywords", [])
        filtered: List[Dict[str, Any]] = []
        for item in data:
            text = self._extract_text_for_analysis(item).lower()
            if not keywords or any(kw.lower() in text for kw in keywords):
                filtered.append(item)
        return filtered

    def _ai_analyze_patterns(self, dataset: List[Dict[str, Any]]) -> Dict[str, Any]:
        sample_size = min(10, len(dataset))
        texts = [self._extract_text_for_analysis(item) for item in dataset[:sample_size]]
        combined = "\n\n".join(texts[:3])
        prompt = (
            f"Analyse the following medical research dataset sample and identify key patterns:\n\n"
            f"{combined}\n\nProvide a structured analysis."
        )
        try:
            result = self.model.generate(prompt, max_length=500, temperature=0.5)
            return {"ai_analysis": result, "model_used": self.model_name, "sample_size": sample_size}
        except Exception as exc:
            self.logger.error("AI analysis failed: %s", exc)
            return {"error": str(exc), "fallback": "AI analysis unavailable"}

    def _basic_analyze_patterns(self, dataset: List[Dict[str, Any]]) -> Dict[str, Any]:
        from collections import Counter

        all_text = " ".join(
            self._extract_text_for_analysis(item) for item in dataset[:100]
        )
        words = all_text.lower().split()
        common_words = Counter(words).most_common(20)
        return {
            "common_terms": [{"term": w, "count": c} for w, c in common_words],
            "method": "basic_frequency_analysis",
        }

    def _summarize_dataset(
        self, dataset: List[Dict[str, Any]], parameters: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        summaries: List[Dict[str, Any]] = []
        for item in dataset[:10]:
            text = self._extract_text_for_analysis(item)
            record_id = item.get("pmid") or item.get("nct_id")
            if self.use_accelerate and self.model:
                prompt = f"Summarise the following medical research in 2-3 sentences:\n\n{text[:1000]}"
                try:
                    summaries.append({"original_id": record_id, "summary": self.model.generate(prompt, max_length=150, temperature=0.3)})
                except Exception as exc:
                    self.logger.warning("Summarisation failed: %s", exc)
                    summaries.append({"original_id": record_id, "summary": text[:200] + "..."})
            else:
                summaries.append({"original_id": record_id, "summary": text[:200] + "..."})
        return {"success": True, "summaries": summaries, "count": len(summaries)}

    def _extract_entities(
        self, dataset: List[Dict[str, Any]], parameters: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        entities: List[Dict[str, Any]] = []
        for item in dataset[:10]:
            record_id = item.get("pmid") or item.get("nct_id")
            text = self._extract_text_for_analysis(item)
            if self.use_accelerate and self.model:
                prompt = (
                    f"Extract medical entities from this text:\n\n{text[:800]}\n\n"
                    "List Conditions, Treatments, Outcomes, Measurements as JSON."
                )
                try:
                    entities.append({"record_id": record_id, "entities": self.model.generate(prompt, max_length=300, temperature=0.2)})
                except Exception as exc:
                    self.logger.warning("Entity extraction failed: %s", exc)
            else:
                entities.append({"record_id": record_id, "entities": {"conditions": [], "treatments": [], "outcomes": []}})
        return {"success": True, "extracted_entities": entities, "count": len(entities)}

    def _normalize_dataset(
        self, dataset: List[Dict[str, Any]], parameters: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        normalized = [
            {
                "id": item.get("pmid") or item.get("nct_id"),
                "title": item.get("title", ""),
                "abstract": item.get("abstract", ""),
                "date": item.get("publication_date") or item.get("start_date"),
                "type": "pubmed" if "pmid" in item else "clinical_trial",
                "metadata": {k: v for k, v in item.items() if k not in {"title", "abstract"}},
            }
            for item in dataset
        ]
        return {"success": True, "normalized_dataset": normalized, "count": len(normalized)}

    def _generate_mock_synthetic_data(
        self, template_data: List[Dict[str, Any]], config: SyntheticDataConfig
    ) -> Dict[str, Any]:
        samples = [
            {
                "id": f"synthetic_{i + 1}",
                "content": f"[Mock] Variation of: {template_data[i % len(template_data)].get('title', 'Unknown')}",
                "template_id": template_data[i % len(template_data)].get("pmid") or template_data[i % len(template_data)].get("nct_id"),
                "generated_at": datetime.now().isoformat(),
                "note": "Mock data — ipfs_accelerate_py not available",
            }
            for i in range(min(config.num_samples, 5))
        ]
        return {"success": True, "synthetic_data": samples, "count": len(samples), "config": config.__dict__, "mock": True}

    def _create_synthetic_generation_prompt(self, template: Dict[str, Any]) -> str:
        title = template.get("title", "")
        abstract = template.get("abstract", "")
        return (
            f"Generate a synthetic medical research article similar to this template:\n\n"
            f"Title: {title}\nAbstract: {abstract[:300]}\n\n"
            "Create a NEW article with similar topic but different findings.\n\nNew Article:"
        )

    def _extract_text_for_analysis(self, item: Dict[str, Any]) -> str:
        return " ".join(
            item[k] for k in ("title", "abstract", "summary") if k in item and item[k]
        )

    def _create_assessment_prompt(
        self, text: str, criteria: Optional[Dict[str, Any]]
    ) -> str:
        criteria_str = json.dumps(criteria) if criteria else "general quality and relevance"
        return (
            f"Assess the following medical research text for: {criteria_str}\n\n"
            f"Text: {text[:500]}\n\nIs this text relevant and high quality? Answer YES or NO."
        )

    def _parse_filter_decision(self, model_output: str) -> bool:
        output_lower = model_output.lower()
        return "yes" in output_lower and "no" not in output_lower[:20]

    def _calculate_metrics(self, dataset: List[Dict[str, Any]]) -> DatasetMetrics:
        if not dataset:
            return DatasetMetrics()
        total = len(dataset)
        ids = [item.get("pmid") or item.get("nct_id") for item in dataset]
        unique = len(set(filter(None, ids)))
        complete = sum(
            1 for item in dataset
            if item.get("title") and (item.get("abstract") or item.get("summary"))
        )
        completeness = complete / total if total > 0 else 0.0
        return DatasetMetrics(
            total_records=total,
            unique_records=unique,
            completeness_score=round(completeness, 3),
            quality_score=round(0.75 + completeness * 0.15, 3),
            relevance_score=round(0.70 + completeness * 0.20, 3),
            diversity_score=round(unique / total if total > 0 else 0.0, 3),
        )


__all__ = ["DatasetMetrics", "SyntheticDataConfig", "AIDatasetBuilder"]
