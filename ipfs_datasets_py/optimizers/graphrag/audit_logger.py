"""
Audit logging infrastructure for ontology refinement tracking.

Provides comprehensive audit trail for:
- Refinement strategy decisions
- Action applications (merge, split, normalize, etc.)
- Score evolution across rounds
- Critic recommendations and feedback
- Configuration changes

Usage:
    >>> from ipfs_datasets_py.optimizers.graphrag.audit_logger import (
    ...     AuditLogger, AuditEvent
    ... )
    >>> 
    >>> logger = AuditLogger(output_dir="./audit_logs")
    >>> 
    >>> # Log refinement decision
    >>> logger.log_refinement_decision(
    ...     round_num=1,
    ...     ontology=ontology,
    ...     score=score,
    ...     strategy={"action": "merge_duplicates", "priority": "high"},
    ...     context=context
    ... )
    >>> 
    >>> # Export audit trail
    >>> logger.export_json("audit_trail.json")

Author: ipfs_datasets_py team
"""

import json
import logging
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
from enum import Enum


class EventType(str, Enum):
    """Types of auditable events in the refinement process."""
    
    REFINEMENT_CYCLE_START = "refinement_cycle_start"
    REFINEMENT_CYCLE_END = "refinement_cycle_end"
    STRATEGY_DECISION = "strategy_decision"
    ACTION_APPLY = "action_apply"
    SCORE_UPDATE = "score_update"
    RECOMMENDATION_ISSUED = "recommendation_issued"
    CONFIG_CHANGE = "config_change"
    CONVERGENCE_ACHIEVED = "convergence_achieved"
    MAX_ROUNDS_REACHED = "max_rounds_reached"
    ERROR_OCCURRED = "error_occurred"


@dataclass
class AuditEvent:
    """
    Single auditable event in the refinement process.
    
    Captures all context needed to replay/debug/analyze refinement decisions.
    
    Attributes:
        event_type: Type of event (see EventType enum)
        timestamp: ISO 8601 timestamp when event occurred
        round_num: Refinement round number (0 for pre-refinement events)
        event_data: Event-specific data (varies by event_type)
        metadata: Optional additional context
    """
    
    event_type: EventType
    timestamp: str
    round_num: int
    event_data: Dict[str, Any]
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    @classmethod
    def create(
        cls,
        event_type: EventType,
        round_num: int,
        event_data: Dict[str, Any],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> "AuditEvent":
        """Create an audit event with automatic timestamping."""
        return cls(
            event_type=event_type,
            timestamp=datetime.utcnow().isoformat() + "Z",
            round_num=round_num,
            event_data=event_data,
            metadata=metadata or {},
        )
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "event_type": self.event_type.value,
            "timestamp": self.timestamp,
            "round_num": self.round_num,
            "event_data": self.event_data,
            "metadata": self.metadata,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AuditEvent":
        """Deserialize from dictionary."""
        return cls(
            event_type=EventType(data["event_type"]),
            timestamp=data["timestamp"],
            round_num=data["round_num"],
            event_data=data["event_data"],
            metadata=data.get("metadata", {}),
        )


class AuditLogger:
    """
    Comprehensive audit logger for ontology refinement.
    
    Tracks all decisions, actions, scores, and recommendations throughout
    the refinement process. Provides JSON export for replay and analysis.
    
    Thread-safe for concurrent refinement sessions (each session gets unique ID).
    
    Attributes:
        session_id: Unique identifier for this audit session
        output_dir: Directory for audit log files (None = memory-only)
        events: List of all audit events in chronological order
        
    Example:
        >>> logger = AuditLogger(output_dir="./audit_logs")
        >>> 
        >>> # Start refinement cycle
        >>> logger.log_cycle_start(data="contract.txt", context=context)
        >>> 
        >>> # Log strategy decision
        >>> logger.log_refinement_decision(
        ...     round_num=1,
        ...     ontology=ontology,
        ...     score=score,
        ...     strategy=strategy,
        ...     context=context
        ... )
        >>> 
        >>> # Apply action
        >>> logger.log_action_apply(
        ...     round_num=1,
        ...     action_name="merge_duplicates",
        ...     ontology_before=ontology_before,
        ...     ontology_after=ontology_after
        ... )
        >>> 
        >>> # Export audit trail
        >>> logger.export_json("refinement_audit.json")
    """
    
    def __init__(
        self,
        session_id: Optional[str] = None,
        output_dir: Optional[Union[str, Path]] = None,
        enable_file_logging: bool = True,
        logger: Optional[logging.Logger] = None,
    ):
        """
        Initialize audit logger.
        
        Args:
            session_id: Unique session identifier. If None, auto-generated.
            output_dir: Directory to write audit files. If None, memory-only.
            enable_file_logging: Whether to write events to disk (default: True)
            logger: Optional Python logger for debug messages
        """
        self.session_id = session_id or self._generate_session_id()
        self.output_dir = Path(output_dir) if output_dir else None
        self.enable_file_logging = enable_file_logging and (output_dir is not None)
        self._log = logger or logging.getLogger(__name__)
        
        # Event storage
        self.events: List[AuditEvent] = []
        
        # Create output directory if needed
        if self.enable_file_logging:
            self.output_dir.mkdir(parents=True, exist_ok=True)
            self._log.info(f"Audit logger initialized: session_id={self.session_id}, output_dir={self.output_dir}")
        else:
            self._log.info(f"Audit logger initialized (memory-only): session_id={self.session_id}")
    
    @staticmethod
    def _generate_session_id() -> str:
        """Generate unique session ID from timestamp and random suffix."""
        import uuid
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        random_suffix = str(uuid.uuid4())[:8]
        return f"{timestamp}_{random_suffix}"
    
    def _add_event(self, event: AuditEvent) -> None:
        """Add event to storage and optionally write to disk."""
        self.events.append(event)
        
        # Optionally write to incremental log file
        if self.enable_file_logging:
            self._write_event_to_file(event)
    
    def _write_event_to_file(self, event: AuditEvent) -> None:
        """Append event to incremental log file (JSONL format)."""
        log_file = self.output_dir / f"audit_{self.session_id}.jsonl"
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(event.to_dict()) + "\n")
    
    # Event logging methods
    
    def log_cycle_start(
        self,
        data: Any,
        context: Any,  # OntologyGenerationContext
        max_rounds: int,
        convergence_threshold: float,
    ) -> None:
        """Log start of refinement cycle."""
        event = AuditEvent.create(
            event_type=EventType.REFINEMENT_CYCLE_START,
            round_num=0,
            event_data={
                "data_source": getattr(context, "data_source", str(data)[:100]),
                "domain": getattr(context, "domain", "unknown"),
                "extraction_strategy": str(getattr(context, "extraction_strategy", "unknown")),
                "max_rounds": max_rounds,
                "convergence_threshold": convergence_threshold,
            },
            metadata={
                "session_id": self.session_id,
            }
        )
        self._add_event(event)
        self._log.info(f"Refinement cycle started: max_rounds={max_rounds}, threshold={convergence_threshold}")
    
    def log_refinement_decision(
        self,
        round_num: int,
        ontology: Dict[str, Any],
        score: Any,  # CriticScore
        strategy: Dict[str, Any],
        context: Any,  # OntologyGenerationContext
    ) -> None:
        """Log refinement strategy decision."""
        event = AuditEvent.create(
            event_type=EventType.STRATEGY_DECISION,
            round_num=round_num,
            event_data={
                "ontology_stats": {
                    "entity_count": len(ontology.get("entities", [])),
                    "relationship_count": len(ontology.get("relationships", [])),
                },
                "score": {
                    "overall": getattr(score, "overall", 0.0),
                    "completeness": getattr(score, "completeness", 0.0),
                    "consistency": getattr(score, "consistency", 0.0),
                    "clarity": getattr(score, "clarity", 0.0),
                },
                "strategy": {
                    "action": strategy.get("action", "unknown"),
                    "priority": strategy.get("priority", "unknown"),
                    "rationale": strategy.get("rationale", ""),
                    "estimated_impact": strategy.get("estimated_impact", 0.0),
                    "affected_entity_count": strategy.get("affected_entity_count", 0),
                    "alternative_actions": strategy.get("alternative_actions", []),
                },
            },
            metadata={
                "domain": getattr(context, "domain", "unknown"),
            }
        )
        self._add_event(event)
        self._log.info(
            f"Round {round_num}: Strategy decision - {strategy.get('action')} "
            f"(priority: {strategy.get('priority')}, impact: +{strategy.get('estimated_impact', 0):.2f})"
        )
    
    def log_action_apply(
        self,
        round_num: int,
        action_name: str,
        ontology_before: Dict[str, Any],
        ontology_after: Dict[str, Any],
        execution_time_ms: Optional[float] = None,
    ) -> None:
        """Log application of refinement action."""
        before_stats = {
            "entity_count": len(ontology_before.get("entities", [])),
            "relationship_count": len(ontology_before.get("relationships", [])),
        }
        after_stats = {
            "entity_count": len(ontology_after.get("entities", [])),
            "relationship_count": len(ontology_after.get("relationships", [])),
        }
        
        event = AuditEvent.create(
            event_type=EventType.ACTION_APPLY,
            round_num=round_num,
            event_data={
                "action_name": action_name,
                "before": before_stats,
                "after": after_stats,
                "delta": {
                    "entities": after_stats["entity_count"] - before_stats["entity_count"],
                    "relationships": after_stats["relationship_count"] - before_stats["relationship_count"],
                },
                "execution_time_ms": execution_time_ms,
            }
        )
        self._add_event(event)
        self._log.info(
            f"Round {round_num}: Applied {action_name} - "
            f"entities: {before_stats['entity_count']} → {after_stats['entity_count']}, "
            f"relationships: {before_stats['relationship_count']} → {after_stats['relationship_count']}"
        )
    
    def log_score_update(
        self,
        round_num: int,
        score_before: Any,  # CriticScore
        score_after: Any,  # CriticScore
    ) -> None:
        """Log score change after refinement action."""
        event = AuditEvent.create(
            event_type=EventType.SCORE_UPDATE,
            round_num=round_num,
            event_data={
                "before": {
                    "overall": getattr(score_before, "overall", 0.0),
                    "completeness": getattr(score_before, "completeness", 0.0),
                    "consistency": getattr(score_before, "consistency", 0.0),
                    "clarity": getattr(score_before, "clarity", 0.0),
                },
                "after": {
                    "overall": getattr(score_after, "overall", 0.0),
                    "completeness": getattr(score_after, "completeness", 0.0),
                    "consistency": getattr(score_after, "consistency", 0.0),
                    "clarity": getattr(score_after, "clarity", 0.0),
                },
                "delta": {
                    "overall": getattr(score_after, "overall", 0.0) - getattr(score_before, "overall", 0.0),
                    "completeness": getattr(score_after, "completeness", 0.0) - getattr(score_before, "completeness", 0.0),
                    "consistency": getattr(score_after, "consistency", 0.0) - getattr(score_before, "consistency", 0.0),
                    "clarity": getattr(score_after, "clarity", 0.0) - getattr(score_before, "clarity", 0.0),
                },
            }
        )
        self._add_event(event)
        delta = getattr(score_after, "overall", 0.0) - getattr(score_before, "overall", 0.0)
        self._log.info(f"Round {round_num}: Score updated - overall: {getattr(score_after, 'overall', 0.0):.3f} (Δ{delta:+.3f})")
    
    def log_recommendations(
        self,
        round_num: int,
        score: Any,  # CriticScore
    ) -> None:
        """Log critic recommendations."""
        recommendations = list(getattr(score, "recommendations", []))
        event = AuditEvent.create(
            event_type=EventType.RECOMMENDATION_ISSUED,
            round_num=round_num,
            event_data={
                "recommendation_count": len(recommendations),
                "recommendations": recommendations,
                "score_overall": getattr(score, "overall", 0.0),
            }
        )
        self._add_event(event)
        self._log.info(f"Round {round_num}: {len(recommendations)} recommendations issued")
    
    def log_convergence(
        self,
        round_num: int,
        final_score: Any,  # CriticScore
        reason: str = "threshold_reached",
    ) -> None:
        """Log convergence achievement."""
        event = AuditEvent.create(
            event_type=EventType.CONVERGENCE_ACHIEVED,
            round_num=round_num,
            event_data={
                "final_score": {
                    "overall": getattr(final_score, "overall", 0.0),
                    "completeness": getattr(final_score, "completeness", 0.0),
                    "consistency": getattr(final_score, "consistency", 0.0),
                    "clarity": getattr(final_score, "clarity", 0.0),
                },
                "reason": reason,
                "total_rounds": round_num,
            }
        )
        self._add_event(event)
        self._log.info(f"Convergence achieved at round {round_num}: {getattr(final_score, 'overall', 0.0):.3f}")
    
    def log_max_rounds(
        self,
        round_num: int,
        final_score: Any,  # CriticScore
    ) -> None:
        """Log max rounds reached without convergence."""
        event = AuditEvent.create(
            event_type=EventType.MAX_ROUNDS_REACHED,
            round_num=round_num,
            event_data={
                "final_score": {
                    "overall": getattr(final_score, "overall", 0.0),
                    "completeness": getattr(final_score, "completeness", 0.0),
                    "consistency": getattr(final_score, "consistency", 0.0),
                    "clarity": getattr(final_score, "clarity", 0.0),
                },
                "total_rounds": round_num,
            }
        )
        self._add_event(event)
        self._log.warning(f"Max rounds ({round_num}) reached without convergence: {getattr(final_score, 'overall', 0.0):.3f}")
    
    def log_error(
        self,
        round_num: int,
        error_type: str,
        error_message: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Log error during refinement."""
        event = AuditEvent.create(
            event_type=EventType.ERROR_OCCURRED,
            round_num=round_num,
            event_data={
                "error_type": error_type,
                "error_message": error_message,
                "context": context or {},
            }
        )
        self._add_event(event)
        self._log.error(f"Round {round_num}: {error_type} - {error_message}")
    
    def log_config_change(
        self,
        round_num: int,
        config_before: Dict[str, Any],
        config_after: Dict[str, Any],
        reason: str = "",
    ) -> None:
        """Log configuration change during refinement."""
        event = AuditEvent.create(
            event_type=EventType.CONFIG_CHANGE,
            round_num=round_num,
            event_data={
                "config_before": config_before,
                "config_after": config_after,
                "reason": reason,
            }
        )
        self._add_event(event)
        self._log.info(f"Round {round_num}: Configuration changed - {reason}")
    
    # Export and analysis methods
    
    def export_json(self, filepath: Union[str, Path], pretty: bool = True) -> None:
        """
        Export full audit trail to JSON file.
        
        Args:
            filepath: Output file path
            pretty: Whether to pretty-print JSON (default: True)
        """
        filepath = Path(filepath)
        data = {
            "session_id": self.session_id,
            "event_count": len(self.events),
            "events": [event.to_dict() for event in self.events],
        }
        
        with open(filepath, "w", encoding="utf-8") as f:
            if pretty:
                json.dump(data, f, indent=2, sort_keys=True)
            else:
                json.dump(data, f, separators=(',', ':'), sort_keys=True)
        
        self._log.info(f"Exported {len(self.events)} events to {filepath}")
    
    def get_round_summary(self, round_num: int) -> Dict[str, Any]:
        """Get summary of events for a specific round."""
        round_events = [e for e in self.events if e.round_num == round_num]
        
        return {
            "round_num": round_num,
            "event_count": len(round_events),
            "events_by_type": {
                event_type.value: sum(1 for e in round_events if e.event_type == event_type)
                for event_type in EventType
            },
            "events": [e.to_dict() for e in round_events],
        }
    
    def get_score_evolution(self) -> List[Dict[str, Any]]:
        """Get score evolution across all rounds."""
        score_events = [e for e in self.events if e.event_type == EventType.SCORE_UPDATE]
        
        evolution = []
        for event in score_events:
            evolution.append({
                "round": event.round_num,
                "timestamp": event.timestamp,
                "score": event.event_data["after"],
                "delta": event.event_data["delta"],
            })
        
        return evolution
    
    def get_action_history(self) -> List[Dict[str, Any]]:
        """Get history of all applied actions."""
        action_events = [e for e in self.events if e.event_type == EventType.ACTION_APPLY]
        
        history = []
        for event in action_events:
            history.append({
                "round": event.round_num,
                "timestamp": event.timestamp,
                "action": event.event_data["action_name"],
                "delta": event.event_data["delta"],
                "execution_time_ms": event.event_data.get("execution_time_ms"),
            })
        
        return history
    
    def generate_summary_report(self) -> str:
        """Generate human-readable summary report."""
        if not self.events:
            return "No audit events recorded."
        
        lines = []
        lines.append("=" * 80)
        lines.append(f"AUDIT SUMMARY - Session {self.session_id}")
        lines.append("=" * 80)
        lines.append("")
        
        # Overall stats
        lines.append(f"Total Events: {len(self.events)}")
        max_round = max(e.round_num for e in self.events)
        lines.append(f"Rounds: {max_round}")
        lines.append("")
        
        # Event breakdown
        lines.append("Events by Type:")
        for event_type in EventType:
            count = sum(1 for e in self.events if e.event_type == event_type)
            if count > 0:
                lines.append(f"  {event_type.value}: {count}")
        lines.append("")
        
        # Score evolution
        score_evolution = self.get_score_evolution()
        if score_evolution:
            lines.append("Score Evolution:")
            first = score_evolution[0]
            last = score_evolution[-1]
            lines.append(f"  Round 1:  {first['score']['overall']:.3f}")
            lines.append(f"  Round {last['round']}: {last['score']['overall']:.3f}")
            total_delta = last['score']['overall'] - first['score']['overall']
            lines.append(f"  Improvement: {total_delta:+.3f}")
            lines.append("")
        
        # Action history
        action_history = self.get_action_history()
        if action_history:
            lines.append(f"Actions Applied: {len(action_history)}")
            for action in action_history:
                lines.append(f"  Round {action['round']}: {action['action']}")
            lines.append("")
        
        # Convergence status
        converged = any(e.event_type == EventType.CONVERGENCE_ACHIEVED for e in self.events)
        max_reached = any(e.event_type == EventType.MAX_ROUNDS_REACHED for e in self.events)
        
        if converged:
            lines.append("Status: ✅ CONVERGED")
        elif max_reached:
            lines.append("Status: ⚠️  MAX ROUNDS REACHED (DID NOT CONVERGE)")
        else:
            lines.append("Status: 🔄 IN PROGRESS")
        
        lines.append("=" * 80)
        
        return "\n".join(lines)
    
    def __repr__(self) -> str:
        return f"AuditLogger(session_id={self.session_id}, events={len(self.events)})"


# Convenience functions for common use cases

def create_audit_logger(
    output_dir: Union[str, Path] = "./audit_logs",
    session_id: Optional[str] = None,
) -> AuditLogger:
    """Create a new audit logger with default configuration."""
    return AuditLogger(
        session_id=session_id,
        output_dir=output_dir,
        enable_file_logging=True,
    )


def load_audit_trail(filepath: Union[str, Path]) -> List[AuditEvent]:
    """Load audit trail from JSON file."""
    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)
    
    return [AuditEvent.from_dict(event_dict) for event_dict in data["events"]]
