"""Per-round metric counters for ontology refinement tracking.

These utilities track detailed changes across refinement rounds, enabling
analytics on what works and what doesn't in the optimization loop.

Key metrics:
- entities_delta: number of entities added/removed/modified
- relationships_delta: number of relationships added/removed/modified  
- score_delta: change in overall score (improvement)
- action_counts: frequency of refinement actions applied
- convergence_rate: how quickly scores stabilize
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple
import logging

_logger = logging.getLogger(__name__)


@dataclass
class RoundMetrics:
    """Metrics for a single refinement round.
    
    Attributes:
        round_number: Round index (1-based)
        entities_count_before: Entity count before refinement
        entities_count_after: Entity count after refinement
        entities_delta: Net change (after - before)
        entities_added: Number of new entities
        entities_removed: Number of removed entities
        entities_modified: Number of entities with changed properties
        relationships_count_before: Relationship count before refinement
        relationships_count_after: Relationship count after refinement
        relationships_delta: Net change (after - before)
        relationships_added: Number of new relationships
        relationships_removed: Number of removed relationships
        score_before: Overall score before refinement
        score_after: Overall score after refinement
        score_delta: Score improvement (after - before)
        actions_applied: List of refinement actions executed
        execution_time_ms: Milliseconds to complete this round
        metadata: Additional round-specific data
    """
    round_number: int = 0
    entities_count_before: int = 0
    entities_count_after: int = 0
    entities_delta: int = 0
    entities_added: int = 0
    entities_removed: int = 0
    entities_modified: int = 0
    relationships_count_before: int = 0
    relationships_count_after: int = 0
    relationships_delta: int = 0
    relationships_added: int = 0
    relationships_removed: int = 0
    relationships_modified: int = 0
    score_before: float = 0.0
    score_after: float = 0.0
    score_delta: float = 0.0
    actions_applied: List[str] = field(default_factory=list)
    execution_time_ms: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            'round_number': self.round_number,
            'entities_count_before': self.entities_count_before,
            'entities_count_after': self.entities_count_after,
            'entities_delta': self.entities_delta,
            'entities_added': self.entities_added,
            'entities_removed': self.entities_removed,
            'entities_modified': self.entities_modified,
            'relationships_count_before': self.relationships_count_before,
            'relationships_count_after': self.relationships_count_after,
            'relationships_delta': self.relationships_delta,
            'relationships_added': self.relationships_added,
            'relationships_removed': self.relationships_removed,
            'score_before': self.score_before,
            'score_after': self.score_after,
            'score_delta': self.score_delta,
            'actions_applied': self.actions_applied,
            'execution_time_ms': self.execution_time_ms,
            'metadata': self.metadata,
        }
    
    def __repr__(self) -> str:
        """Concise REPL representation."""
        sign = "+" if self.score_delta >= 0 else ""
        return (
            f"RoundMetrics(r{self.round_number} | "
            f"e:{self.entities_delta:+d} r:{self.relationships_delta:+d} | "
            f"score:{sign}{self.score_delta:.3f} [{self.actions_applied}])"
        )


def compute_ontology_delta(
    ontology_before: Dict[str, Any],
    ontology_after: Dict[str, Any],
) -> Tuple[int, int, int, int, int, int]:
    """Compute entity and relationship changes between two ontologies.
    
    Args:
        ontology_before: Ontology dict before refinement
        ontology_after: Ontology dict after refinement
        
    Returns:
        Tuple of (entities_added, entities_removed, entities_modified,
                  relationships_added, relationships_removed, relationships_modified)
    """
    before_ents = {e.get("id"): e for e in ontology_before.get("entities", []) if e.get("id")}
    after_ents = {e.get("id"): e for e in ontology_after.get("entities", []) if e.get("id")}
    
    before_rels = {
        (r.get("source"), r.get("target"), r.get("type")): r
        for r in ontology_before.get("relationships", [])
        if r.get("source") and r.get("target")
    }
    after_rels = {
        (r.get("source"), r.get("target"), r.get("type")): r
        for r in ontology_after.get("relationships", [])
        if r.get("source") and r.get("target")
    }
    
    # Entity changes
    entity_ids_added = set(after_ents.keys()) - set(before_ents.keys())
    entity_ids_removed = set(before_ents.keys()) - set(after_ents.keys())
    entity_ids_common = set(before_ents.keys()) & set(after_ents.keys())
    
    entities_modified = sum(
        1 for eid in entity_ids_common
        if before_ents[eid] != after_ents[eid]
    )
    
    # Relationship changes
    rels_added = set(after_rels.keys()) - set(before_rels.keys())
    rels_removed = set(before_rels.keys()) - set(after_rels.keys())
    rels_common = set(before_rels.keys()) & set(after_rels.keys())
    
    rels_modified = sum(
        1 for rkey in rels_common
        if before_rels[rkey] != after_rels[rkey]
    )
    
    return (
        len(entity_ids_added),
        len(entity_ids_removed),
        entities_modified,
        len(rels_added),
        len(rels_removed),
        rels_modified,
    )


def create_round_metrics(
    round_number: int,
    ontology_before: Dict[str, Any],
    ontology_after: Dict[str, Any],
    score_before: float,
    score_after: float,
    actions_applied: Optional[List[str]] = None,
    execution_time_ms: float = 0.0,
    metadata: Optional[Dict[str, Any]] = None,
) -> RoundMetrics:
    """Create RoundMetrics for a refinement round.
    
    Args:
        round_number: Round index (1-based)
        ontology_before: Ontology state before refinement
        ontology_after: Ontology state after refinement
        score_before: Score before refinement
        score_after: Score after refinement
        actions_applied: List of refinement actions executed
        execution_time_ms: Time spent in refinement
        metadata: Additional round data
        
    Returns:
        RoundMetrics object with computed deltas
    """
    entities_added, entities_removed, entities_modified, \
        rels_added, rels_removed, rels_modified = compute_ontology_delta(
            ontology_before,
            ontology_after,
        )
    
    entities_before = len(ontology_before.get("entities", []))
    entities_after = len(ontology_after.get("entities", []))
    rels_before = len(ontology_before.get("relationships", []))
    rels_after = len(ontology_after.get("relationships", []))
    
    return RoundMetrics(
        round_number=round_number,
        entities_count_before=entities_before,
        entities_count_after=entities_after,
        entities_delta=entities_after - entities_before,
        entities_added=entities_added,
        entities_removed=entities_removed,
        entities_modified=entities_modified,
        relationships_count_before=rels_before,
        relationships_count_after=rels_after,
        relationships_delta=rels_after - rels_before,
        relationships_added=rels_added,
        relationships_removed=rels_removed,
        relationships_modified=rels_modified,
        score_before=round(score_before, 4),
        score_after=round(score_after, 4),
        score_delta=round(score_after - score_before, 4),
        actions_applied=actions_applied or [],
        execution_time_ms=round(execution_time_ms, 2),
        metadata=metadata or {},
    )


class RoundMetricsCollector:
    """Accumulates and analyzes per-round metrics across refinement cycles.
    
    Usage::
    
        collector = RoundMetricsCollector()
        
        for round in range(num_rounds):
            metrics = create_round_metrics(...)
            collector.record_round(metrics)
        
        print(f"Total improvement: {collector.total_score_delta():.3f}")
        print(f"Most effective actions: {collector.most_effective_actions()}")
    """
    
    def __init__(self):
        """Initialize metrics collector."""
        self.rounds: List[RoundMetrics] = []
        self._log = logging.getLogger(__name__)
    
    def record_round(self, metrics: RoundMetrics) -> None:
        """Record metrics for a refinement round.
        
        Args:
            metrics: RoundMetrics from the round
        """
        self.rounds.append(metrics)
        self._log.debug(f"Recorded: {metrics}")
    
    def total_entity_delta(self) -> int:
        """Total entities added across all rounds."""
        return sum(m.entities_delta for m in self.rounds)
    
    def total_relationship_delta(self) -> int:
        """Total relationships added across all rounds."""
        return sum(m.relationships_delta for m in self.rounds)
    
    def total_score_delta(self) -> float:
        """Total score improvement across all rounds."""
        if not self.rounds:
            return 0.0
        return self.rounds[-1].score_after - self.rounds[0].score_before
    
    def average_round_improvement(self) -> float:
        """Average score improvement per round."""
        if not self.rounds:
            return 0.0
        return self.total_score_delta() / len(self.rounds)
    
    def rounds_to_convergence(self, threshold: float = 0.001) -> Optional[int]:
        """Find the first round where improvement drops below threshold.
        
        Args:
            threshold: Minimum improvement to continue (default 0.1%)
            
        Returns:
            Round number where convergence occurred, or None if not converged
        """
        for i in range(1, len(self.rounds)):
            if self.rounds[i].score_delta < threshold:
                return i + 1
        return None
    
    def most_effective_actions(self, top_n: int = 5) -> List[Tuple[str, float]]:
        """Find refinement actions with highest average improvement.
        
        Args:
            top_n: Number of top actions to return
            
        Returns:
            List of (action, avg_improvement) tuples sorted by improvement
        """
        action_improvements: Dict[str, List[float]] = {}
        
        for metrics in self.rounds:
            for action in metrics.actions_applied:
                if action not in action_improvements:
                    action_improvements[action] = []
                action_improvements[action].append(metrics.score_delta)
        
        action_stats = [
            (action, sum(improvements) / len(improvements))
            for action, improvements in action_improvements.items()
        ]
        
        # Sort by average improvement (descending), then by frequency
        action_stats.sort(key=lambda x: (-x[1], len(action_improvements[x[0]])))
        return action_stats[:top_n]
    
    def to_dict(self) -> Dict[str, Any]:
        """Export all metrics as a nested dict."""
        return {
            'total_rounds': len(self.rounds),
            'total_entity_delta': self.total_entity_delta(),
            'total_relationship_delta': self.total_relationship_delta(),
            'total_score_delta': round(self.total_score_delta(), 4),
            'average_round_improvement': round(self.average_round_improvement(), 4),
            'rounds_to_convergence': self.rounds_to_convergence(),
            'rounds': [m.to_dict() for m in self.rounds],
            'most_effective_actions': self.most_effective_actions(),
        }
    
    def __repr__(self) -> str:
        """Concise REPL representation."""
        if not self.rounds:
            return "RoundMetricsCollector(0 rounds)"
        
        return (
            f"RoundMetricsCollector({len(self.rounds)} rounds | "
            f"e{self.total_entity_delta():+d} "
            f"r{self.total_relationship_delta():+d} | "
            f"score{self.total_score_delta():+.3f})"
        )


__all__ = [
    "RoundMetrics",
    "RoundMetricsCollector",
    "compute_ontology_delta",
    "create_round_metrics",
]
