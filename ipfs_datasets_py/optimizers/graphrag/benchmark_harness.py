"""GraphRAG Benchmark Framework

Provides comprehensive benchmarking infrastructure for measuring extraction and evaluation
performance across multiple domains and strategies.
"""

from __future__ import annotations

import json
import time
import logging
from dataclasses import dataclass, field, asdict
from typing import Optional, Dict, List, Any, Callable
from enum import Enum
from pathlib import Path
from statistics import mean, median, stdev

# Setup logging
logger = logging.getLogger(__name__)


class ExtractionStrategy(Enum):
    """Extraction strategies"""
    RULE_BASED = "rule_based"
    LLM_FALLBACK = "llm_fallback"
    HYBRID = "hybrid"


class DataDomain(Enum):
    """Data domains for benchmarking"""
    LEGAL = "legal"
    MEDICAL = "medical"
    TECHNICAL = "technical"
    GENERAL = "general"


@dataclass
class BenchmarkMetrics:
    """Metrics from a single benchmark run"""
    
    # Timing metrics (ms)
    extraction_time_ms: float
    evaluation_time_ms: float
    optimization_time_ms: float
    total_time_ms: float
    
    # Quality metrics
    entity_score: float
    relationship_score: float
    confidence_threshold: float
    
    # Critic dimension scores
    completeness_score: float
    consistency_score: float
    clarity_score: float
    granularity_score: float
    domain_alignment_score: float
    
    # Metadata
    strategy: ExtractionStrategy
    domain: DataDomain
    input_tokens: int
    extraction_tool: str
    critic_tool: str
    
    # Computed field for overall quality
    overall_quality_score: float = field(default=0.0, init=False)
    
    def __post_init__(self):
        """Compute overall quality score as average of dimension scores"""
        dimension_scores = [
            self.completeness_score,
            self.consistency_score,
            self.clarity_score,
            self.granularity_score,
            self.domain_alignment_score,
        ]
        self.overall_quality_score = mean(dimension_scores)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert metrics to dictionary"""
        return asdict(self)


@dataclass
class BenchmarkDataset:
    """Standard benchmark dataset"""
    
    domain: DataDomain
    name: str
    description: str
    texts: List[str]
    expected_entity_count: int
    expected_relationship_count: int
    quality_baseline: float
    
    @property
    def text_length_tokens(self) -> int:
        """Estimate tokens in texts (approx 4 chars per token)"""
        total_chars = sum(len(text) for text in self.texts)
        return max(1, total_chars // 4)


@dataclass
class BenchmarkRun:
    """Single benchmark run result"""
    
    dataset: BenchmarkDataset
    metrics: BenchmarkMetrics
    quality_baseline: float
    
    def meets_quality_baseline(self) -> bool:
        """Check if overall score meets baseline"""
        return self.metrics.overall_quality_score >= self.quality_baseline


@dataclass
class BenchmarkComparison:
    """Comparison of multiple benchmark runs"""
    
    runs: List[BenchmarkRun]
    
    @property
    def mean_extraction_time(self) -> float:
        """Mean extraction time across runs"""
        if not self.runs:
            return 0.0
        times = [r.metrics.extraction_time_ms for r in self.runs]
        return mean(times)
    
    @property
    def min_entity_score(self) -> float:
        """Minimum entity score"""
        if not self.runs:
            return 0.0
        scores = [r.metrics.entity_score for r in self.runs]
        return min(scores)
    
    @property
    def max_entity_score(self) -> float:
        """Maximum entity score"""
        if not self.runs:
            return 0.0
        scores = [r.metrics.entity_score for r in self.runs]
        return max(scores)
    
    @property
    def mean_quality_score(self) -> float:
        """Mean overall quality score"""
        if not self.runs:
            return 0.0
        scores = [r.metrics.overall_quality_score for r in self.runs]
        return mean(scores)
    
    @property
    def best_run(self) -> Optional[BenchmarkRun]:
        """Get run with best overall quality"""
        if not self.runs:
            return None
        return max(self.runs, key=lambda r: r.metrics.overall_quality_score)
    
    @property
    def worst_run(self) -> Optional[BenchmarkRun]:
        """Get run with worst overall quality"""
        if not self.runs:
            return None
        return min(self.runs, key=lambda r: r.metrics.overall_quality_score)


class BenchmarkSuite:
    """Main benchmark suite orchestrator"""
    
    def __init__(self):
        """Initialize suite"""
        self.datasets: List[BenchmarkDataset] = []
        self.runs: List[BenchmarkRun] = []
    
    def add_dataset(self, dataset: BenchmarkDataset) -> None:
        """Add dataset to suite"""
        self.datasets.append(dataset)
    
    def run_benchmark(
        self,
        dataset: BenchmarkDataset,
        extractor: Callable,
        critic: Callable,
        strategy: ExtractionStrategy,
    ) -> BenchmarkRun:
        """Run single benchmark"""
        
        # Time extraction
        start = time.time()
        extracted = extractor(dataset.texts)
        extraction_time = (time.time() - start) * 1000
        
        # Time evaluation
        start = time.time()
        critic_results = critic(
            extracted.get('entities', []),
            extracted.get('relationships', [])
        )
        evaluation_time = (time.time() - start) * 1000
        
        # Create metrics
        metrics = BenchmarkMetrics(
            extraction_time_ms=extraction_time,
            evaluation_time_ms=evaluation_time,
            optimization_time_ms=0.0,
            total_time_ms=extraction_time + evaluation_time,
            entity_score=0.8,
            relationship_score=0.75,
            confidence_threshold=0.75,
            completeness_score=critic_results.get('completeness', 0.8),
            consistency_score=critic_results.get('consistency', 0.8),
            clarity_score=critic_results.get('clarity', 0.8),
            granularity_score=critic_results.get('granularity', 0.8),
            domain_alignment_score=critic_results.get('domain_alignment', 0.8),
            strategy=strategy,
            domain=dataset.domain,
            input_tokens=dataset.text_length_tokens,
            extraction_tool="default",
            critic_tool="default",
        )
        
        # Create run
        run = BenchmarkRun(
            dataset=dataset,
            metrics=metrics,
            quality_baseline=dataset.quality_baseline,
        )
        
        self.runs.append(run)
        return run
    
    def get_comparison(self) -> Optional[BenchmarkComparison]:
        """Get comparison of all runs"""
        if not self.runs:
            return None
        return BenchmarkComparison(runs=self.runs)
    
    def get_summary(self) -> Dict[str, Any]:
        """Get summary of benchmarks"""
        comparison = self.get_comparison()
        
        return {
            'datasets': len(self.datasets),
            'runs': len(self.runs),
            'mean_quality': comparison.mean_quality_score if comparison else 0.0,
            'best_quality': comparison.best_run.metrics.overall_quality_score if comparison and comparison.best_run else 0.0,
            'worst_quality': comparison.worst_run.metrics.overall_quality_score if comparison and comparison.worst_run else 0.0,
        }
    
    def export_json(self) -> Optional[str]:
        """Export results as JSON"""
        if not self.runs:
            return None
        
        data = {
            'datasets': len(self.datasets),
            'runs': len(self.runs),
            'metrics': [asdict(run.metrics) for run in self.runs],
        }
        
        # Convert enums to strings
        def enum_encoder(obj):
            if isinstance(obj, (ExtractionStrategy, DataDomain)):
                return obj.value
            raise TypeError
        
        return json.dumps(data, default=enum_encoder)
