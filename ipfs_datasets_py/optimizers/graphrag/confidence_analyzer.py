"""Confidence analysis and reporting utilities for extraction results.

Provides tools for analyzing entity and relationship confidence distributions,
identifying low-confidence results, and generating summary reports for quality
assessment.

Features:
- Confidence statistics (mean, median, stdev)
- Histograms with configurable bin sizes
- Confidence-based filtering and sorting
- Summary reports for batch analysis
- Confidence distribution visualization data
"""

from dataclasses import dataclass, field
from typing import Dict, List, Tuple, Optional, Any, TypedDict
import json


class ConfidenceStatsDict(TypedDict, total=False):
    """Type contract for ConfidenceStats.to_dict() return value.
    
    Fields:
        min: Minimum confidence score
        max: Maximum confidence score
        mean: Mean confidence score
        median: Median confidence score
        stdev: Standard deviation of confidence scores
        count: Number of confidence scores
    """
    min: float
    max: float
    mean: float
    median: float
    stdev: float
    count: int


class ConfidenceHistogramDict(TypedDict, total=False):
    """Type contract for ConfidenceHistogram.to_dict() return value.
    
    Fields:
        bins: List of (lower, upper) bin boundaries
        counts: Count of values in each bin
        total: Total number of values
    """
    bins: List[Tuple[float, float]]
    counts: List[int]
    total: int


class ConfidenceReportDict(TypedDict, total=False):
    """Type contract for ConfidenceReport.to_dict() return value.
    
    Fields:
        entity_stats: Entity confidence statistics
        entity_histogram: Entity confidence distribution
        low_confidence_threshold: Threshold for low confidence
        low_confidence_entities_count: Number of low confidence entities
        relationship_stats: Relationship confidence statistics (optional)
        relationship_histogram: Relationship confidence distribution (optional)
        low_confidence_relationships_count: Number of low confidence relationships (optional)
    """
    entity_stats: ConfidenceStatsDict
    entity_histogram: ConfidenceHistogramDict
    low_confidence_threshold: float
    low_confidence_entities_count: int
    relationship_stats: ConfidenceStatsDict
    relationship_histogram: ConfidenceHistogramDict
    low_confidence_relationships_count: int


@dataclass
class ConfidenceStats:
    """Statistical summary of confidence scores."""
    
    min_confidence: float
    max_confidence: float
    mean_confidence: float
    median_confidence: float
    stdev_confidence: float
    count: int
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "min": round(self.min_confidence, 4),
            "max": round(self.max_confidence, 4),
            "mean": round(self.mean_confidence, 4),
            "median": round(self.median_confidence, 4),
            "stdev": round(self.stdev_confidence, 4),
            "count": self.count,
        }


@dataclass
class ConfidenceHistogram:
    """Histogram of confidence score distribution."""
    
    bins: List[Tuple[float, float]]  # [(lower, upper), ...]
    counts: List[int]  # Count in each bin
    total: int
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "bins": [(round(l, 2), round(u, 2)) for l, u in self.bins],
            "counts": self.counts,
            "total": self.total,
        }
    
    def to_ascii_art(self, width: int = 60) -> str:
        """Generate ASCII histogram.
        
        Args:
            width: Maximum width of histogram bars
            
        Returns:
            Multi-line ASCII art string
        """
        if not self.counts or self.total == 0:
            return "Empty histogram"
        
        max_count = max(self.counts)
        lines = []
        
        for (lower, upper), count in zip(self.bins, self.counts):
            if max_count > 0:
                bar_width = int((count / max_count) * width)
            else:
                bar_width = 0
            bar = "█" * bar_width
            pct = (count / self.total * 100) if self.total > 0 else 0
            label = f"[{lower:.1f}-{upper:.1f}]"
            lines.append(f"{label:15s} {bar:60s} {count:4d} ({pct:5.1f}%)")
        
        return "\n".join(lines)


@dataclass
class ConfidenceReport:
    """Complete confidence analysis report."""
    
    entity_stats: ConfidenceStats
    entity_histogram: ConfidenceHistogram
    relationship_stats: Optional[ConfidenceStats] = None
    relationship_histogram: Optional[ConfidenceHistogram] = None
    low_confidence_entities: List[Tuple[str, float]] = field(default_factory=list)
    low_confidence_relationships: List[Tuple[str, float]] = field(default_factory=list)
    low_confidence_threshold: float = 0.6
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        result = {
            "entity_stats": self.entity_stats.to_dict(),
            "entity_histogram": self.entity_histogram.to_dict(),
            "low_confidence_threshold": self.low_confidence_threshold,
            "low_confidence_entities_count": len(self.low_confidence_entities),
        }
        
        if self.relationship_stats:
            result["relationship_stats"] = self.relationship_stats.to_dict()
            result["relationship_histogram"] = self.relationship_histogram.to_dict()
            result["low_confidence_relationships_count"] = len(self.low_confidence_relationships)
        
        return result
    
    def to_json(self, **kwargs) -> str:
        """Serialize to JSON string."""
        return json.dumps(self.to_dict(), **kwargs)
    
    def to_markdown(self) -> str:
        """Generate markdown report."""
        lines = [
            "# Confidence Analysis Report",
            "",
        ]
        
        # Entity statistics
        lines.extend([
            "## Entity Confidence Statistics",
            "",
            f"- **Count**: {self.entity_stats.count}",
            f"- **Mean**: {self.entity_stats.mean_confidence:.4f}",
            f"- **Median**: {self.entity_stats.median_confidence:.4f}",
            f"- **Min**: {self.entity_stats.min_confidence:.4f}",
            f"- **Max**: {self.entity_stats.max_confidence:.4f}",
            f"- **Stdev**: {self.entity_stats.stdev_confidence:.4f}",
            "",
        ])
        
        # Entity histogram
        lines.extend([
            "### Entity Confidence Distribution",
            "",
            "```",
            self.entity_histogram.to_ascii_art(),
            "```",
            "",
        ])
        
        # Relationship statistics (if present)
        if self.relationship_stats:
            lines.extend([
                "## Relationship Confidence Statistics",
                "",
                f"- **Count**: {self.relationship_stats.count}",
                f"- **Mean**: {self.relationship_stats.mean_confidence:.4f}",
                f"- **Median**: {self.relationship_stats.median_confidence:.4f}",
                f"- **Min**: {self.relationship_stats.min_confidence:.4f}",
                f"- **Max**: {self.relationship_stats.max_confidence:.4f}",
                f"- **Stdev**: {self.relationship_stats.stdev_confidence:.4f}",
                "",
            ])
            
            # Relationship histogram
            lines.extend([
                "### Relationship Confidence Distribution",
                "",
                "```",
                self.relationship_histogram.to_ascii_art(),
                "```",
                "",
            ])
        
        # Low confidence results
        if self.low_confidence_entities or self.low_confidence_relationships:
            lines.extend([
                f"## Low Confidence Results (< {self.low_confidence_threshold})",
                "",
            ])
            
            if self.low_confidence_entities:
                lines.extend([
                    f"### Entities ({len(self.low_confidence_entities)})",
                    "",
                    "| ID | Confidence |",
                    "|---|---|",
                ])
                for entity_id, conf in sorted(self.low_confidence_entities, key=lambda x: x[1])[:20]:
                    lines.append(f"| `{entity_id}` | {conf:.4f} |")
                if len(self.low_confidence_entities) > 20:
                    lines.append(f"| ... | ... | ({len(self.low_confidence_entities) - 20} more) |")
                lines.append("")
            
            if self.low_confidence_relationships:
                lines.extend([
                    f"### Relationships ({len(self.low_confidence_relationships)})",
                    "",
                    "| ID | Confidence |",
                    "|---|---|",
                ])
                for rel_id, conf in sorted(self.low_confidence_relationships, key=lambda x: x[1])[:20]:
                    lines.append(f"| `{rel_id}` | {conf:.4f} |")
                if len(self.low_confidence_relationships) > 20:
                    lines.append(f"| ... | ... | ({len(self.low_confidence_relationships) - 20} more) |")
                lines.append("")
        
        return "\n".join(lines)


def compute_confidence_stats(scores: List[float]) -> ConfidenceStats:
    """Compute confidence statistics from a list of scores.
    
    Args:
        scores: List of confidence scores (floats in [0.0, 1.0])
        
    Returns:
        ConfidenceStats with computed values
        
    Raises:
        ValueError: If scores list is empty
    """
    if not scores:
        raise ValueError("Cannot compute stats from empty scores list")
    
    scores_sorted = sorted(scores)
    n = len(scores)
    
    mean = sum(scores) / n
    
    # Median
    if n % 2 == 0:
        median = (scores_sorted[n // 2 - 1] + scores_sorted[n // 2]) / 2
    else:
        median = scores_sorted[n // 2]
    
    # Sample standard deviation
    variance = sum((s - mean) ** 2 for s in scores) / max(1, n - 1)
    stdev = variance ** 0.5
    
    return ConfidenceStats(
        min_confidence=scores_sorted[0],
        max_confidence=scores_sorted[-1],
        mean_confidence=mean,
        median_confidence=median,
        stdev_confidence=stdev,
        count=n,
    )


def compute_confidence_histogram(
    scores: List[float],
    num_bins: int = 10,
) -> ConfidenceHistogram:
    """Compute histogram of confidence scores.
    
    Args:
        scores: List of confidence scores (floats in [0.0, 1.0])
        num_bins: Number of histogram bins (default: 10)
        
    Returns:
        ConfidenceHistogram with bin definitions and counts
    """
    if not scores:
        return ConfidenceHistogram(bins=[], counts=[], total=0)
    
    # Create bins
    bin_edges = [(i / num_bins, (i + 1) / num_bins) for i in range(num_bins)]
    
    # Count scores in each bin
    counts = []
    for bin_idx, (lower, upper) in enumerate(bin_edges):
        # Last bin includes the upper edge (to capture 1.0 exactly)
        if bin_idx == num_bins - 1:
            count = sum(1 for s in scores if lower <= s <= upper)
        else:
            count = sum(1 for s in scores if lower <= s < upper)
        counts.append(count)
    
    return ConfidenceHistogram(
        bins=bin_edges,
        counts=counts,
        total=len(scores),
    )


def extract_entity_confidences(entities: List[Dict[str, Any]]) -> List[float]:
    """Extract confidence scores from entity list.
    
    Args:
        entities: List of entity dictionaries with 'confidence' key
        
    Returns:
        List of confidence float values
    """
    return [e.get("confidence", 1.0) for e in entities]


def extract_relationship_confidences(relationships: List[Dict[str, Any]]) -> List[float]:
    """Extract confidence scores from relationship list.
    
    Args:
        relationships: List of relationship dicts with 'confidence' key
        
    Returns:
        List of confidence float values
    """
    return [r.get("confidence", 1.0) for r in relationships]


def analyze_extraction_results(
    entities: List[Dict[str, Any]],
    relationships: Optional[List[Dict[str, Any]]] = None,
    low_confidence_threshold: float = 0.6,
    num_histogram_bins: int = 10,
) -> ConfidenceReport:
    """Analyze confidence distribution in extraction results.
    
    Args:
        entities: List of extracted entity dicts
        relationships: Optional list of inferred relationship dicts
        low_confidence_threshold: Threshold for flagging low-confidence results
        num_histogram_bins: Number of histogram bins
        
    Returns:
        ConfidenceReport with detailed analysis
        
    Example::
    
        report = analyze_extraction_results(
            entities=[{"id": "e1", "text": "Alice", "confidence": 0.95}, ...],
            relationships=[{"id": "r1", "source_id": "e1", "target_id": "e2", "confidence": 0.78}, ...],
            low_confidence_threshold=0.6,
        )
        print(report.to_markdown())
    """
    # Analyze entities
    entity_confidences = extract_entity_confidences(entities)
    entity_stats = compute_confidence_stats(entity_confidences)
    entity_histogram = compute_confidence_histogram(entity_confidences, num_histogram_bins)
    
    # Find low-confidence entities
    low_confidence_entities = [
        (e.get("id", "unknown"), float(e.get("confidence", 1.0)))
        for e in entities
        if e.get("confidence", 1.0) < low_confidence_threshold
    ]
    
    # Analyze relationships (if provided)
    relationship_stats = None
    relationship_histogram = None
    low_confidence_relationships = []
    
    if relationships:
        rel_confidences = extract_relationship_confidences(relationships)
        if rel_confidences:
            relationship_stats = compute_confidence_stats(rel_confidences)
            relationship_histogram = compute_confidence_histogram(rel_confidences, num_histogram_bins)
            
            low_confidence_relationships = [
                (r.get("id", "unknown"), float(r.get("confidence", 1.0)))
                for r in relationships
                if r.get("confidence", 1.0) < low_confidence_threshold
            ]
    
    return ConfidenceReport(
        entity_stats=entity_stats,
        entity_histogram=entity_histogram,
        relationship_stats=relationship_stats,
        relationship_histogram=relationship_histogram,
        low_confidence_entities=low_confidence_entities,
        low_confidence_relationships=low_confidence_relationships,
        low_confidence_threshold=low_confidence_threshold,
    )


if __name__ == "__main__":
    """Example usage."""
    # Example extraction results
    example_entities = [
        {"id": "e1", "text": "Alice", "type": "Person", "confidence": 0.95},
        {"id": "e2", "text": "Bob", "type": "Person", "confidence": 0.88},
        {"id": "e3", "text": "TechCorp", "type": "Organization", "confidence": 0.92},
        {"id": "e4", "text": "San Francisco", "type": "Location", "confidence": 0.55},
        {"id": "e5", "text": "CEO", "type": "Role", "confidence": 0.42},
    ]
    
    example_relationships = [
        {"id": "r1", "source_id": "e1", "target_id": "e3", "type": "works_for", "confidence": 0.85},
        {"id": "r2", "source_id": "e2", "target_id": "e3", "type": "works_for", "confidence": 0.78},
        {"id": "r3", "source_id": "e3", "target_id": "e4", "type": "located_in", "confidence": 0.91},
        {"id": "r4", "source_id": "e1", "target_id": "e5", "type": "has_role", "confidence": 0.38},
    ]
    
    # Generate report
    report = analyze_extraction_results(
        entities=example_entities,
        relationships=example_relationships,
        low_confidence_threshold=0.6,
    )
    
    # Display results
    print(report.to_markdown())
    print("\n" + "=" * 70)
    print("JSON Summary:")
    print(json.dumps(report.to_dict(), indent=2))
