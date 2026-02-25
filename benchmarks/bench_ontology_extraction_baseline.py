#!/usr/bin/env python3
"""
Comprehensive baseline benchmark for ontology extraction across multiple configurations.

This benchmark establishes performance and quality baselines for:
- Multiple extraction strategies (rule-based, hybrid, LLM-based)
- Multiple domains (general, legal, medical, business)
- Different text sizes (1k, 5k, 10k, 20k tokens)
- Entity deduplication (heuristic vs semantic)

Output: JSON report with metrics for regression tracking and a markdown summary.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from statistics import mean, median, stdev
from typing import List, Dict, Any
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ipfs_datasets_py.optimizers.graphrag.ontology_generator import (  # noqa: E402
    DataType,
    ExtractionConfig,
    ExtractionStrategy,
    OntologyGenerationContext,
    OntologyGenerator,
)


@dataclass
class BenchmarkResult:
    """Result of a single benchmark run."""
    
    case_name: str
    strategy: str
    domain: str
    text_size_tokens: int
    iterations: int
    warmups: int
    
    # Performance metrics
    avg_ms: float
    median_ms: float
    p95_ms: float
    p99_ms: float
    max_ms: float
    min_ms: float
    stddev_ms: float
    
    # Quality metrics
    avg_entities: float
    avg_relationships: float
    avg_confidence: float
    
    # Memory metrics (optional)
    peak_memory_mb: float = 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to JSON-serializable dict."""
        return {
            "case_name": self.case_name,
            "strategy": self.strategy,
            "domain": self.domain,
            "text_size_tokens": self.text_size_tokens,
            "iterations": self.iterations,
            "warmups": self.warmups,
            "performance": {
                "avg_ms": round(self.avg_ms, 4),
                "median_ms": round(self.median_ms, 4),
                "p95_ms": round(self.p95_ms, 4),
                "p99_ms": round(self.p99_ms, 4),
                "max_ms": round(self.max_ms, 4),
                "min_ms": round(self.min_ms, 4),
                "stddev_ms": round(self.stddev_ms, 4),
            },
            "quality": {
                "avg_entities": round(self.avg_entities, 2),
                "avg_relationships": round(self.avg_relationships, 2),
                "avg_confidence": round(self.avg_confidence, 4),
            },
            "memory": {
                "peak_memory_mb": round(self.peak_memory_mb, 2),
            },
        }


def _build_text(size_tokens: int) -> str:
    """Generate synthetic text of approximately the specified token count."""
    # Varied sentence patterns for more realistic extraction
    sentences = [
        "Dr. Alice Smith met Bob Johnson at Acme Corp on January 1, 2024 in New York City. ",
        "The Chief Executive Officer Jane Doe announced a partnership with XYZ Inc. ",
        "USD 1,000,000.00 was transferred to the account of John Williams at Banking Corp. ",
        "The obligation of Alice is to file the compliance report by March 15, 2024. ",
        "Microsoft Corporation acquired LinkedIn for $26.2 billion in an all-cash transaction. ",
        "The defendant, Robert Brown, was represented by Attorney Sarah Martinez. ",
        "Amazon Web Services provides cloud computing infrastructure to enterprise clients. ",
        "The plaintiff alleges that the defendant violated contract terms on February 28, 2024. ",
    ]
    
    # Each sentence ~20-25 tokens
    avg_tokens_per_sentence = 22
    iterations = size_tokens // avg_tokens_per_sentence
    
    return "".join([sentences[i % len(sentences)] for i in range(iterations)])


def _run_benchmark(
    generator: OntologyGenerator,
    context: OntologyGenerationContext,
    text: str,
    text_size_tokens: int,
    case_name: str,
    iterations: int = 10,
    warmups: int = 2,
) -> BenchmarkResult:
    """Run a single benchmark case."""
    
    # Warmup runs
    for _ in range(warmups):
        generator.extract_entities(text, context)
    
    # Measurement runs
    samples_ms: List[float] = []
    entity_counts: List[int] = []
    relationship_counts: List[int] = []
    confidence_scores: List[float] = []
    
    for _ in range(iterations):
        start = time.perf_counter()
        result = generator.extract_entities(text, context)
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        
        samples_ms.append(elapsed_ms)
        entity_counts.append(len(result.entities))
        relationship_counts.append(len(result.relationships))
        confidence_scores.append(result.confidence)
    
    # Calculate percentiles
    samples_ms.sort()
    p95_idx = max(0, int(iterations * 0.95) - 1)
    p99_idx = max(0, int(iterations * 0.99) - 1)
    
    return BenchmarkResult(
        case_name=case_name,
        strategy=str(context.extraction_strategy.value),
        domain=context.domain,
        text_size_tokens=text_size_tokens,
        iterations=iterations,
        warmups=warmups,
        avg_ms=mean(samples_ms),
        median_ms=median(samples_ms),
        p95_ms=samples_ms[p95_idx],
        p99_ms=samples_ms[p99_idx],
        max_ms=max(samples_ms),
        min_ms=min(samples_ms),
        stddev_ms=stdev(samples_ms) if len(samples_ms) > 1 else 0.0,
        avg_entities=mean(entity_counts),
        avg_relationships=mean(relationship_counts),
        avg_confidence=mean(confidence_scores),
    )


def _generate_markdown_report(results: List[BenchmarkResult], output_path: Path) -> None:
    """Generate a markdown summary report."""
    
    lines = [
        "# Ontology Extraction Baseline Benchmark",
        "",
        f"**Generated**: {time.strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "## Performance Summary",
        "",
        "| Case | Strategy | Domain | Tokens | Avg (ms) | P95 (ms) | Entities | Relationships |",
        "|------|----------|--------|--------|----------|----------|----------|---------------|",
    ]
    
    for result in results:
        lines.append(
            f"| {result.case_name} "
            f"| {result.strategy} "
            f"| {result.domain} "
            f"| {result.text_size_tokens:,} "
            f"| {result.avg_ms:.2f} "
            f"| {result.p95_ms:.2f} "
            f"| {result.avg_entities:.1f} "
            f"| {result.avg_relationships:.1f} |"
        )
    
    lines.extend([
        "",
        "## Detailed Metrics",
        "",
    ])
    
    for result in results:
        lines.extend([
            f"### {result.case_name}",
            "",
            f"**Configuration**:",
            f"- Strategy: {result.strategy}",
            f"- Domain: {result.domain}",
            f"- Text size: {result.text_size_tokens:,} tokens",
            f"- Iterations: {result.iterations} (warmups: {result.warmups})",
            "",
            f"**Performance**:",
            f"- Average: {result.avg_ms:.2f} ms",
            f"- Median: {result.median_ms:.2f} ms",
            f"- P95: {result.p95_ms:.2f} ms",
            f"- P99: {result.p99_ms:.2f} ms",
            f"- Min/Max: {result.min_ms:.2f} / {result.max_ms:.2f} ms",
            f"- Stddev: {result.stddev_ms:.2f} ms",
            "",
            f"**Quality**:",
            f"- Entities: {result.avg_entities:.2f}",
            f"- Relationships: {result.avg_relationships:.2f}",
            f"- Confidence: {result.avg_confidence:.4f}",
            "",
        ])
    
    output_path.write_text("\n".join(lines))


def main() -> None:
    """Run all benchmark cases and generate reports."""
    
    logging.disable(logging.CRITICAL)
    
    print("=== Ontology Extraction Baseline Benchmark ===")
    print()
    
    # Benchmark configurations
    cases = [
        # Small text (1k tokens)
        ("1k_general_rule", "general", ExtractionStrategy.RULE_BASED, 1000, 20, 3),
        ("1k_legal_rule", "legal", ExtractionStrategy.RULE_BASED, 1000, 20, 3),
        
        # Medium text (5k tokens)
        ("5k_general_rule", "general", ExtractionStrategy.RULE_BASED, 5000, 15, 2),
        ("5k_legal_rule", "legal", ExtractionStrategy.RULE_BASED, 5000, 15, 2),
        ("5k_business_rule", "business", ExtractionStrategy.RULE_BASED, 5000, 15, 2),
        
        # Large text (10k tokens)
        ("10k_general_rule", "general", ExtractionStrategy.RULE_BASED, 10000, 10, 2),
        ("10k_legal_rule", "legal", ExtractionStrategy.RULE_BASED, 10000, 10, 2),
        ("10k_medical_rule", "medical", ExtractionStrategy.RULE_BASED, 10000, 10, 2),
        
        # Very large text (20k tokens)
        ("20k_general_rule", "general", ExtractionStrategy.RULE_BASED, 20000, 5, 1),
    ]
    
    generator = OntologyGenerator(use_ipfs_accelerate=False)
    results: List[BenchmarkResult] = []
    
    for case_name, domain, strategy, size_tokens, iterations, warmups in cases:
        print(f"Running: {case_name}...")
        
        text = _build_text(size_tokens)
        context = OntologyGenerationContext(
            data_source="benchmark",
            data_type=DataType.TEXT,
            domain=domain,
            extraction_strategy=strategy,
            config=ExtractionConfig(
                confidence_threshold=0.5,
                sentence_window=2,
            ),
        )
        
        result = _run_benchmark(
            generator=generator,
            context=context,
            text=text,
            text_size_tokens=size_tokens,
            case_name=case_name,
            iterations=iterations,
            warmups=warmups,
        )
        
        results.append(result)
        print(f"  ✓ {result.avg_ms:.2f} ms avg, {result.avg_entities:.0f} entities, {result.avg_relationships:.0f} relationships")
    
    # Generate JSON report
    json_report = {
        "benchmark_name": "ontology_extraction_baseline",
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "results": [r.to_dict() for r in results],
    }
    
    json_path = Path(__file__).parent / "results" / "baseline_ontology_extraction.json"
    json_path.parent.mkdir(exist_ok=True)
    json_path.write_text(json.dumps(json_report, indent=2))
    print()
    print(f"✓ JSON report: {json_path}")
    
    # Generate markdown report
    md_path = Path(__file__).parent / "results" / "baseline_ontology_extraction.md"
    _generate_markdown_report(results, md_path)
    print(f"✓ Markdown report: {md_path}")
    
    print()
    print("=== Benchmark Complete ===")


if __name__ == "__main__":
    main()
