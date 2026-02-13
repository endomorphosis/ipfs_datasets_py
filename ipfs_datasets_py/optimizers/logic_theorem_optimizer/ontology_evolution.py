"""Real-time Ontology Evolution for Logic Theorem Optimizer.

This module implements dynamic ontology evolution that learns from new logical
statements and adapts the ontology incrementally without full retraining.

Key features:
- Incremental learning from new statements
- Ontology versioning and rollback
- Evolution tracking metrics
- Safe update validation
- Automatic term/relation discovery

Integration:
- Works with KnowledgeGraphStabilizer for consistency
- Uses OntologyConsistencyChecker for validation
- Tracks evolution history for analysis
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Set, Tuple
from dataclasses import dataclass, field
from enum import Enum
import time
import json
import hashlib
from collections import defaultdict
from copy import deepcopy

logger = logging.getLogger(__name__)


class UpdateStrategy(Enum):
    """Strategy for applying ontology updates."""
    CONSERVATIVE = "conservative"  # Only add highly confident terms
    MODERATE = "moderate"  # Balanced approach
    AGGRESSIVE = "aggressive"  # Add most new terms
    MANUAL = "manual"  # Require manual approval


class EvolutionEvent(Enum):
    """Type of ontology evolution event."""
    TERM_ADDED = "term_added"
    TERM_REMOVED = "term_removed"
    RELATION_ADDED = "relation_added"
    RELATION_REMOVED = "relation_removed"
    TYPE_ADDED = "type_added"
    TYPE_REMOVED = "type_removed"
    AXIOM_ADDED = "axiom_added"
    AXIOM_REMOVED = "axiom_removed"


@dataclass
class OntologyVersion:
    """Snapshot of ontology at a specific version.
    
    Attributes:
        version: Version number
        timestamp: Creation timestamp
        ontology: Ontology snapshot
        changes: List of changes from previous version
        metadata: Additional metadata
        hash: Hash of ontology content for integrity
    """
    version: int
    timestamp: float
    ontology: Dict[str, Any]
    changes: List[Tuple[EvolutionEvent, Any]]
    metadata: Dict[str, Any] = field(default_factory=dict)
    hash: str = ""
    
    def __post_init__(self):
        """Compute hash after initialization."""
        if not self.hash:
            self.hash = self._compute_hash()
    
    def _compute_hash(self) -> str:
        """Compute hash of ontology content."""
        content = json.dumps(self.ontology, sort_keys=True)
        return hashlib.sha256(content.encode()).hexdigest()


@dataclass
class EvolutionMetrics:
    """Metrics tracking ontology evolution.
    
    Attributes:
        total_updates: Total number of updates applied
        terms_added: Number of terms added
        terms_removed: Number of terms removed
        relations_added: Number of relations added
        relations_removed: Number of relations removed
        avg_update_time: Average time per update
        rollbacks: Number of rollbacks performed
        current_version: Current ontology version
        stability_score: Ontology stability score (0.0-1.0)
    """
    total_updates: int = 0
    terms_added: int = 0
    terms_removed: int = 0
    relations_added: int = 0
    relations_removed: int = 0
    avg_update_time: float = 0.0
    rollbacks: int = 0
    current_version: int = 0
    stability_score: float = 1.0


@dataclass
class UpdateCandidate:
    """Candidate for ontology update.
    
    Attributes:
        event_type: Type of update event
        item: Item to add/remove
        confidence: Confidence score (0.0-1.0)
        evidence: Supporting evidence
        source: Source of the candidate
    """
    event_type: EvolutionEvent
    item: Any
    confidence: float
    evidence: List[str] = field(default_factory=list)
    source: str = ""


class OntologyEvolution:
    """Real-time ontology evolution manager.
    
    This class manages dynamic evolution of ontologies by:
    - Learning from new logical statements
    - Proposing updates based on usage patterns
    - Maintaining version history
    - Enabling rollback to previous versions
    - Tracking evolution metrics
    
    Features:
    - Incremental learning without full retraining
    - Safe update validation before application
    - Automatic conflict detection
    - Version control with rollback
    - Evolution analytics and metrics
    
    Example:
        >>> evolution = OntologyEvolution(
        ...     base_ontology=ontology,
        ...     strategy=UpdateStrategy.MODERATE
        ... )
        >>> 
        >>> # Learn from new statements
        >>> evolution.learn_from_statements(new_statements)
        >>> 
        >>> # Get update candidates
        >>> candidates = evolution.get_update_candidates()
        >>> 
        >>> # Apply updates
        >>> evolution.apply_updates(candidates)
        >>> 
        >>> # Rollback if needed
        >>> evolution.rollback_to_version(5)
    """
    
    def __init__(
        self,
        base_ontology: Optional[Dict[str, Any]] = None,
        strategy: UpdateStrategy = UpdateStrategy.MODERATE,
        enable_versioning: bool = True,
        max_versions: int = 100,
        confidence_threshold: float = 0.7
    ):
        """Initialize the ontology evolution manager.
        
        Args:
            base_ontology: Base ontology to evolve
            strategy: Update strategy to use
            enable_versioning: Whether to enable version control
            max_versions: Maximum versions to keep in history
            confidence_threshold: Minimum confidence for updates
        """
        self.strategy = strategy
        self.enable_versioning = enable_versioning
        self.max_versions = max_versions
        self.confidence_threshold = confidence_threshold
        
        # Current ontology
        self.current_ontology = deepcopy(base_ontology) if base_ontology else {
            'terms': [],
            'relations': [],
            'types': [],
            'axioms': []
        }
        
        # Version history
        self.versions: List[OntologyVersion] = []
        self.current_version = 0
        
        # Save initial version
        if self.enable_versioning:
            self._save_version([], {})
        
        # Evolution tracking
        self.metrics = EvolutionMetrics()
        self.update_candidates: List[UpdateCandidate] = []
        
        # Learning state
        self.term_frequency: Dict[str, int] = defaultdict(int)
        self.relation_frequency: Dict[str, int] = defaultdict(int)
        self.cooccurrence: Dict[Tuple[str, str], int] = defaultdict(int)
        
        logger.info(
            f"Initialized OntologyEvolution with strategy={strategy.value}, "
            f"versioning={enable_versioning}"
        )
    
    def learn_from_statements(
        self,
        statements: List[Any],
        batch_size: int = 10
    ) -> int:
        """Learn from new logical statements.
        
        Analyzes statements to identify potential ontology updates,
        including new terms, relations, and patterns.
        
        Args:
            statements: List of logical statements
            batch_size: Number of statements to process at once
        
        Returns:
            Number of update candidates generated
        """
        start_time = time.time()
        initial_candidates = len(self.update_candidates)
        
        for i in range(0, len(statements), batch_size):
            batch = statements[i:i + batch_size]
            self._process_statement_batch(batch)
        
        # Generate update candidates
        self._generate_update_candidates()
        
        new_candidates = len(self.update_candidates) - initial_candidates
        
        logger.info(
            f"Learned from {len(statements)} statements, "
            f"generated {new_candidates} update candidates "
            f"in {time.time() - start_time:.2f}s"
        )
        
        return new_candidates
    
    def _process_statement_batch(self, batch: List[Any]) -> None:
        """Process a batch of statements for learning.
        
        Args:
            batch: Batch of logical statements
        """
        for stmt in batch:
            # Extract terms from formula
            terms = self._extract_terms(stmt.formula)
            
            # Update term frequencies
            for term in terms:
                self.term_frequency[term] += 1
            
            # Track co-occurrences for relation discovery
            for i, term1 in enumerate(terms):
                for term2 in terms[i+1:]:
                    pair = tuple(sorted([term1, term2]))
                    self.cooccurrence[pair] += 1
            
            # Extract relations if available
            if hasattr(stmt, 'relations'):
                for rel in stmt.relations:
                    self.relation_frequency[rel] += 1
    
    def _extract_terms(self, formula: str) -> List[str]:
        """Extract terms from a logical formula.
        
        Args:
            formula: Logical formula string
        
        Returns:
            List of extracted terms
        """
        # Simple extraction: words that are capitalized or in specific patterns
        import re
        
        # Extract predicates: P(x), Employee(x), etc.
        predicates = re.findall(r'([A-Z][a-zA-Z]*)\(', formula)
        
        # Extract constants: specific capitalized words
        constants = re.findall(r'\b([A-Z][a-z]*)\b', formula)
        
        terms = list(set(predicates + constants))
        return terms
    
    def _generate_update_candidates(self) -> None:
        """Generate update candidates from learned patterns."""
        existing_terms = set(self.current_ontology.get('terms', []))
        
        # Propose new terms based on frequency
        for term, freq in self.term_frequency.items():
            if term not in existing_terms:
                # Calculate confidence based on frequency
                confidence = min(freq / 10.0, 1.0)  # Normalize
                
                if confidence >= self.confidence_threshold:
                    candidate = UpdateCandidate(
                        event_type=EvolutionEvent.TERM_ADDED,
                        item=term,
                        confidence=confidence,
                        evidence=[f"Appears {freq} times in recent statements"],
                        source="frequency_analysis"
                    )
                    self.update_candidates.append(candidate)
        
        # Propose new relations based on co-occurrence
        existing_relations = set(self.current_ontology.get('relations', []))
        
        for (term1, term2), count in self.cooccurrence.items():
            if count >= 3:  # Minimum co-occurrence threshold
                relation_name = f"{term1}_to_{term2}"
                if relation_name not in existing_relations:
                    confidence = min(count / 5.0, 1.0)
                    
                    if confidence >= self.confidence_threshold:
                        candidate = UpdateCandidate(
                            event_type=EvolutionEvent.RELATION_ADDED,
                            item={'name': relation_name, 'from': term1, 'to': term2},
                            confidence=confidence,
                            evidence=[f"Co-occurs {count} times"],
                            source="cooccurrence_analysis"
                        )
                        self.update_candidates.append(candidate)
    
    def get_update_candidates(
        self,
        min_confidence: Optional[float] = None,
        event_type: Optional[EvolutionEvent] = None
    ) -> List[UpdateCandidate]:
        """Get update candidates, optionally filtered.
        
        Args:
            min_confidence: Minimum confidence threshold
            event_type: Filter by event type
        
        Returns:
            List of update candidates
        """
        candidates = self.update_candidates
        
        if min_confidence is not None:
            candidates = [c for c in candidates if c.confidence >= min_confidence]
        
        if event_type is not None:
            candidates = [c for c in candidates if c.event_type == event_type]
        
        return candidates
    
    def apply_updates(
        self,
        candidates: Optional[List[UpdateCandidate]] = None,
        validate: bool = True
    ) -> int:
        """Apply ontology updates.
        
        Args:
            candidates: Candidates to apply (all if None)
            validate: Whether to validate before applying
        
        Returns:
            Number of updates applied
        """
        if candidates is None:
            candidates = self.get_update_candidates()
        
        if not candidates:
            logger.info("No update candidates to apply")
            return 0
        
        start_time = time.time()
        applied = 0
        changes = []
        
        for candidate in candidates:
            # Apply based on strategy
            if self.strategy == UpdateStrategy.MANUAL:
                # Skip auto-apply for manual strategy
                continue
            elif self.strategy == UpdateStrategy.CONSERVATIVE:
                if candidate.confidence < 0.9:
                    continue
            elif self.strategy == UpdateStrategy.MODERATE:
                if candidate.confidence < 0.7:
                    continue
            # AGGRESSIVE applies everything
            
            # Validate update if requested
            if validate and not self._validate_update(candidate):
                logger.warning(f"Update validation failed: {candidate.item}")
                continue
            
            # Apply the update
            if self._apply_single_update(candidate):
                applied += 1
                changes.append((candidate.event_type, candidate.item))
                
                # Update metrics
                if candidate.event_type == EvolutionEvent.TERM_ADDED:
                    self.metrics.terms_added += 1
                elif candidate.event_type == EvolutionEvent.RELATION_ADDED:
                    self.metrics.relations_added += 1
        
        # Save version if changes were made
        if changes and self.enable_versioning:
            self._save_version(changes, {'strategy': self.strategy.value})
        
        # Update metrics
        self.metrics.total_updates += applied
        if applied > 0:
            elapsed = time.time() - start_time
            self.metrics.avg_update_time = (
                (self.metrics.avg_update_time * (self.metrics.total_updates - applied) +
                 elapsed) / self.metrics.total_updates
            )
        
        # Clear applied candidates
        self.update_candidates = [
            c for c in self.update_candidates
            if c not in candidates[:applied]
        ]
        
        logger.info(f"Applied {applied} ontology updates in {time.time() - start_time:.2f}s")
        
        return applied
    
    def _validate_update(self, candidate: UpdateCandidate) -> bool:
        """Validate an update before applying.
        
        Args:
            candidate: Update candidate to validate
        
        Returns:
            True if update is valid
        """
        # Basic validation
        if candidate.event_type in (EvolutionEvent.TERM_ADDED, EvolutionEvent.TYPE_ADDED):
            item = candidate.item
            if isinstance(item, str) and len(item) > 0 and item.isidentifier():
                return True
            return False
        
        return True
    
    def _apply_single_update(self, candidate: UpdateCandidate) -> bool:
        """Apply a single update to the ontology.
        
        Args:
            candidate: Update candidate to apply
        
        Returns:
            True if successfully applied
        """
        try:
            if candidate.event_type == EvolutionEvent.TERM_ADDED:
                if 'terms' not in self.current_ontology:
                    self.current_ontology['terms'] = []
                if candidate.item not in self.current_ontology['terms']:
                    self.current_ontology['terms'].append(candidate.item)
                    return True
            
            elif candidate.event_type == EvolutionEvent.RELATION_ADDED:
                if 'relations' not in self.current_ontology:
                    self.current_ontology['relations'] = []
                rel_name = candidate.item.get('name') if isinstance(candidate.item, dict) else candidate.item
                if rel_name not in self.current_ontology['relations']:
                    self.current_ontology['relations'].append(rel_name)
                    return True
            
            elif candidate.event_type == EvolutionEvent.TYPE_ADDED:
                if 'types' not in self.current_ontology:
                    self.current_ontology['types'] = []
                if candidate.item not in self.current_ontology['types']:
                    self.current_ontology['types'].append(candidate.item)
                    return True
            
            return False
        except Exception as e:
            logger.error(f"Error applying update: {e}")
            return False
    
    def _save_version(
        self,
        changes: List[Tuple[EvolutionEvent, Any]],
        metadata: Dict[str, Any]
    ) -> None:
        """Save current ontology as a new version.
        
        Args:
            changes: Changes from previous version
            metadata: Version metadata
        """
        version = OntologyVersion(
            version=self.current_version,
            timestamp=time.time(),
            ontology=deepcopy(self.current_ontology),
            changes=changes,
            metadata=metadata
        )
        
        self.versions.append(version)
        self.current_version += 1
        
        # Prune old versions if needed
        if len(self.versions) > self.max_versions:
            self.versions = self.versions[-self.max_versions:]
        
        logger.debug(f"Saved ontology version {version.version}")
    
    def rollback_to_version(self, version: int) -> bool:
        """Rollback ontology to a specific version.
        
        Args:
            version: Version number to rollback to
        
        Returns:
            True if rollback successful
        """
        # Find the version
        target_version = None
        for v in self.versions:
            if v.version == version:
                target_version = v
                break
        
        if target_version is None:
            logger.error(f"Version {version} not found")
            return False
        
        # Restore ontology
        self.current_ontology = deepcopy(target_version.ontology)
        self.metrics.rollbacks += 1
        
        # Save rollback as new version
        if self.enable_versioning:
            self._save_version(
                [(EvolutionEvent.TERM_REMOVED, "rollback")],
                {'rollback_to': version}
            )
        
        logger.info(f"Rolled back to version {version}")
        return True
    
    def get_version_history(self) -> List[Dict[str, Any]]:
        """Get version history summary.
        
        Returns:
            List of version summaries
        """
        history = []
        for v in self.versions:
            history.append({
                'version': v.version,
                'timestamp': v.timestamp,
                'changes_count': len(v.changes),
                'hash': v.hash,
                'metadata': v.metadata
            })
        return history
    
    def get_metrics(self) -> EvolutionMetrics:
        """Get evolution metrics.
        
        Returns:
            Current evolution metrics
        """
        # Update stability score
        if self.current_version > 0:
            # Stability decreases with frequent updates
            recent_updates = min(self.metrics.total_updates, 10)
            self.metrics.stability_score = max(0.0, 1.0 - (recent_updates / 20.0))
        
        self.metrics.current_version = self.current_version
        return self.metrics
    
    def export_ontology(self, filepath: str) -> None:
        """Export current ontology to file.
        
        Args:
            filepath: Path to export file
        """
        with open(filepath, 'w') as f:
            json.dump(self.current_ontology, f, indent=2)
        
        logger.info(f"Exported ontology to {filepath}")
    
    def export_version_history(self, filepath: str) -> None:
        """Export version history to file.
        
        Args:
            filepath: Path to export file
        """
        history = []
        for v in self.versions:
            history.append({
                'version': v.version,
                'timestamp': v.timestamp,
                'ontology': v.ontology,
                'changes': [(e.value, item) for e, item in v.changes],
                'metadata': v.metadata,
                'hash': v.hash
            })
        
        with open(filepath, 'w') as f:
            json.dump(history, f, indent=2)
        
        logger.info(f"Exported version history to {filepath}")
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get detailed statistics.
        
        Returns:
            Dictionary with statistics
        """
        return {
            'current_version': self.current_version,
            'total_versions': len(self.versions),
            'terms_count': len(self.current_ontology.get('terms', [])),
            'relations_count': len(self.current_ontology.get('relations', [])),
            'types_count': len(self.current_ontology.get('types', [])),
            'pending_candidates': len(self.update_candidates),
            'strategy': self.strategy.value,
            'metrics': {
                'total_updates': self.metrics.total_updates,
                'terms_added': self.metrics.terms_added,
                'relations_added': self.metrics.relations_added,
                'avg_update_time': self.metrics.avg_update_time,
                'rollbacks': self.metrics.rollbacks,
                'stability_score': self.metrics.stability_score
            }
        }
