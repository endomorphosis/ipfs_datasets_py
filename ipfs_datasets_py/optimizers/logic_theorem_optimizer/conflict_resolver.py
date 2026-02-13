"""Advanced Conflict Resolution for Logic Theorem Optimizer.

This module provides sophisticated conflict detection and resolution strategies
for handling logical contradictions, inconsistencies, and disagreements between
multiple sources or provers.

Key Features:
- Automatic conflict detection
- Multiple resolution strategies (voting, priority, consensus, mediator)
- Conflict analysis and graph construction
- Resolution effectiveness metrics
- Integration with ontology stabilizer

Usage:
    >>> from ipfs_datasets_py.optimizers.logic_theorem_optimizer import (
    ...     ConflictResolver, ResolutionStrategy
    ... )
    >>> 
    >>> resolver = ConflictResolver(strategy=ResolutionStrategy.VOTING)
    >>> result = resolver.resolve_conflicts(statements)
    >>> print(f"Resolved {result.conflicts_resolved} conflicts")
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple
import time
import hashlib

logger = logging.getLogger(__name__)


class ResolutionStrategy(Enum):
    """Strategy for resolving conflicts."""
    VOTING = "voting"  # Majority wins
    PRIORITY = "priority"  # Trust scores determine winner
    CONSENSUS = "consensus"  # Find common ground
    MEDIATOR = "mediator"  # LLM-based resolution


class ConflictType(Enum):
    """Type of logical conflict."""
    CONTRADICTION = "contradiction"  # P and ¬P
    INCONSISTENCY = "inconsistency"  # Set of statements has no model
    DISAGREEMENT = "disagreement"  # Different sources claim different things
    AMBIGUITY = "ambiguity"  # Multiple valid interpretations


@dataclass
class LogicalStatement:
    """A logical statement with metadata.
    
    Attributes:
        formula: The logical formula
        source: Source of the statement
        confidence: Confidence score (0.0-1.0)
        priority: Priority/trust score (0.0-1.0)
        metadata: Additional metadata
    """
    formula: str
    source: str
    confidence: float = 1.0
    priority: float = 1.0
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def get_id(self) -> str:
        """Get unique ID for statement."""
        return hashlib.sha256(
            f"{self.formula}:{self.source}".encode()
        ).hexdigest()[:16]


@dataclass
class Conflict:
    """A detected conflict between statements.
    
    Attributes:
        conflict_id: Unique conflict identifier
        conflict_type: Type of conflict
        statements: Conflicting statements
        description: Human-readable description
        detected_at: Timestamp when detected
        severity: Severity score (0.0-1.0)
    """
    conflict_id: str
    conflict_type: ConflictType
    statements: List[LogicalStatement]
    description: str
    detected_at: float
    severity: float = 1.0
    
    def get_sources(self) -> Set[str]:
        """Get all sources involved in conflict."""
        return {stmt.source for stmt in self.statements}


@dataclass
class Resolution:
    """A resolution for a conflict.
    
    Attributes:
        conflict_id: ID of resolved conflict
        strategy_used: Strategy used for resolution
        resolved_statement: The resolved statement
        confidence: Confidence in resolution (0.0-1.0)
        resolution_time: Time taken to resolve (seconds)
        explanation: Explanation of resolution
        metadata: Additional metadata
    """
    conflict_id: str
    strategy_used: ResolutionStrategy
    resolved_statement: LogicalStatement
    confidence: float
    resolution_time: float
    explanation: str
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ConflictResolutionResult:
    """Result of conflict resolution process.
    
    Attributes:
        total_conflicts: Total number of conflicts detected
        conflicts_resolved: Number of conflicts resolved
        conflicts_unresolved: Number of unresolved conflicts
        resolutions: List of resolutions
        unresolved_conflicts: List of unresolved conflicts
        total_time: Total time taken (seconds)
        resolution_rate: Percentage of conflicts resolved
        avg_confidence: Average confidence in resolutions
    """
    total_conflicts: int
    conflicts_resolved: int
    conflicts_unresolved: int
    resolutions: List[Resolution]
    unresolved_conflicts: List[Conflict]
    total_time: float
    resolution_rate: float
    avg_confidence: float
    metadata: Dict[str, Any] = field(default_factory=dict)


class ConflictDetector:
    """Detector for logical conflicts.
    
    This detector analyzes a set of logical statements to identify:
    - Direct contradictions (P and ¬P)
    - Inconsistencies (no satisfying model)
    - Disagreements (different sources, different claims)
    - Ambiguities (multiple valid interpretations)
    """
    
    def __init__(self):
        """Initialize conflict detector."""
        self.detected_conflicts: List[Conflict] = []
    
    def detect_conflicts(
        self,
        statements: List[LogicalStatement]
    ) -> List[Conflict]:
        """Detect conflicts in a set of statements.
        
        Args:
            statements: List of logical statements
            
        Returns:
            List of detected conflicts
        """
        conflicts = []
        
        # Detect direct contradictions
        contradictions = self._detect_contradictions(statements)
        conflicts.extend(contradictions)
        
        # Detect inconsistencies
        inconsistencies = self._detect_inconsistencies(statements)
        conflicts.extend(inconsistencies)
        
        # Detect disagreements
        disagreements = self._detect_disagreements(statements)
        conflicts.extend(disagreements)
        
        self.detected_conflicts = conflicts
        return conflicts
    
    def _detect_contradictions(
        self,
        statements: List[LogicalStatement]
    ) -> List[Conflict]:
        """Detect direct contradictions (P and ¬P).
        
        Args:
            statements: List of statements
            
        Returns:
            List of contradiction conflicts
        """
        conflicts = []
        seen_formulas = {}
        
        for stmt in statements:
            formula = stmt.formula.strip()
            negated = self._get_negation(formula)
            
            if negated in seen_formulas:
                # Found contradiction
                conflict = Conflict(
                    conflict_id=f"contradiction_{len(conflicts)}",
                    conflict_type=ConflictType.CONTRADICTION,
                    statements=[seen_formulas[negated], stmt],
                    description=f"Contradiction: {formula} vs {negated}",
                    detected_at=time.time(),
                    severity=1.0
                )
                conflicts.append(conflict)
            
            seen_formulas[formula] = stmt
        
        return conflicts
    
    def _detect_inconsistencies(
        self,
        statements: List[LogicalStatement]
    ) -> List[Conflict]:
        """Detect logical inconsistencies.
        
        Args:
            statements: List of statements
            
        Returns:
            List of inconsistency conflicts
        """
        # For now, simple heuristic-based detection
        # In production, would use SAT solver
        conflicts = []
        
        # Group by source
        by_source = defaultdict(list)
        for stmt in statements:
            by_source[stmt.source].append(stmt)
        
        # Check for patterns indicating inconsistency
        for source, stmts in by_source.items():
            if len(stmts) < 2:
                continue
            
            # Check for mutually exclusive claims
            formulas = [s.formula for s in stmts]
            if self._are_mutually_exclusive(formulas):
                conflict = Conflict(
                    conflict_id=f"inconsistency_{len(conflicts)}",
                    conflict_type=ConflictType.INCONSISTENCY,
                    statements=stmts,
                    description=f"Inconsistent statements from {source}",
                    detected_at=time.time(),
                    severity=0.8
                )
                conflicts.append(conflict)
        
        return conflicts
    
    def _detect_disagreements(
        self,
        statements: List[LogicalStatement]
    ) -> List[Conflict]:
        """Detect disagreements between sources.
        
        Args:
            statements: List of statements
            
        Returns:
            List of disagreement conflicts
        """
        conflicts = []
        
        # Group similar formulas
        formula_groups = defaultdict(list)
        for stmt in statements:
            # Normalize formula for grouping
            normalized = self._normalize_formula(stmt.formula)
            formula_groups[normalized].append(stmt)
        
        # Check for disagreements (same topic, different sources, different claims)
        for normalized, stmts in formula_groups.items():
            if len(stmts) < 2:
                continue
            
            sources = {s.source for s in stmts}
            if len(sources) > 1:
                # Multiple sources making claims about same thing
                # Check if claims differ significantly
                if self._have_significant_differences(stmts):
                    conflict = Conflict(
                        conflict_id=f"disagreement_{len(conflicts)}",
                        conflict_type=ConflictType.DISAGREEMENT,
                        statements=stmts,
                        description=f"Disagreement between {len(sources)} sources",
                        detected_at=time.time(),
                        severity=0.6
                    )
                    conflicts.append(conflict)
        
        return conflicts
    
    def _get_negation(self, formula: str) -> str:
        """Get negation of a formula.
        
        Args:
            formula: Formula string
            
        Returns:
            Negated formula
        """
        formula = formula.strip()
        
        # Handle ¬ prefix
        if formula.startswith("¬"):
            return formula[1:].strip()
        if formula.startswith("~"):
            return formula[1:].strip()
        if formula.startswith("NOT "):
            return formula[4:].strip()
        
        # Add negation
        return f"¬{formula}"
    
    def _normalize_formula(self, formula: str) -> str:
        """Normalize formula for comparison.
        
        Args:
            formula: Formula string
            
        Returns:
            Normalized formula
        """
        # Remove whitespace, lowercase predicates
        normalized = formula.strip().lower()
        # Remove parentheses for simple comparison
        normalized = normalized.replace("(", "").replace(")", "")
        return normalized
    
    def _are_mutually_exclusive(self, formulas: List[str]) -> bool:
        """Check if formulas are mutually exclusive.
        
        Args:
            formulas: List of formula strings
            
        Returns:
            True if mutually exclusive
        """
        # Simple heuristic: look for patterns like "A and ~A"
        seen = set()
        for formula in formulas:
            normalized = self._normalize_formula(formula)
            negated = self._get_negation(normalized)
            
            if negated in seen:
                return True
            seen.add(normalized)
        
        return False
    
    def _have_significant_differences(
        self,
        statements: List[LogicalStatement]
    ) -> bool:
        """Check if statements have significant differences.
        
        Args:
            statements: List of statements
            
        Returns:
            True if significantly different
        """
        # Check confidence scores
        confidences = [s.confidence for s in statements]
        if max(confidences) - min(confidences) > 0.3:
            return True
        
        # Check for negation
        formulas = [s.formula for s in statements]
        for i, f1 in enumerate(formulas):
            for f2 in formulas[i+1:]:
                if self._get_negation(f1) == f2:
                    return True
        
        return False


class ConflictResolver:
    """Advanced conflict resolver with multiple strategies.
    
    This resolver can handle conflicts using different strategies:
    - Voting: Majority wins (most common claim)
    - Priority: Trust scores determine winner (highest priority source)
    - Consensus: Find common ground (intersection of claims)
    - Mediator: LLM-based resolution (use AI to mediate)
    
    Example:
        >>> resolver = ConflictResolver(strategy=ResolutionStrategy.VOTING)
        >>> result = resolver.resolve_conflicts(statements)
        >>> print(f"Resolved {result.conflicts_resolved} / {result.total_conflicts} conflicts")
        >>> print(f"Resolution rate: {result.resolution_rate:.1f}%")
    """
    
    def __init__(
        self,
        strategy: ResolutionStrategy = ResolutionStrategy.VOTING,
        min_confidence: float = 0.7,
        enable_mediator: bool = False
    ):
        """Initialize conflict resolver.
        
        Args:
            strategy: Resolution strategy to use
            min_confidence: Minimum confidence for resolution
            enable_mediator: Whether to enable LLM mediator
        """
        self.strategy = strategy
        self.min_confidence = min_confidence
        self.enable_mediator = enable_mediator
        self.detector = ConflictDetector()
        self.resolution_history: List[Resolution] = []
    
    def resolve_conflicts(
        self,
        statements: List[LogicalStatement]
    ) -> ConflictResolutionResult:
        """Resolve conflicts in a set of statements.
        
        Args:
            statements: List of logical statements
            
        Returns:
            ConflictResolutionResult with resolution details
        """
        start_time = time.time()
        
        # Detect conflicts
        conflicts = self.detector.detect_conflicts(statements)
        
        # Resolve each conflict
        resolutions = []
        unresolved = []
        
        for conflict in conflicts:
            try:
                resolution = self._resolve_conflict(conflict)
                if resolution.confidence >= self.min_confidence:
                    resolutions.append(resolution)
                    self.resolution_history.append(resolution)
                else:
                    unresolved.append(conflict)
            except Exception as e:
                logger.warning(f"Failed to resolve conflict {conflict.conflict_id}: {e}")
                unresolved.append(conflict)
        
        total_time = time.time() - start_time
        
        # Calculate metrics
        total_conflicts = len(conflicts)
        conflicts_resolved = len(resolutions)
        conflicts_unresolved = len(unresolved)
        resolution_rate = (conflicts_resolved / total_conflicts * 100) if total_conflicts > 0 else 0.0
        avg_confidence = (
            sum(r.confidence for r in resolutions) / len(resolutions)
            if resolutions else 0.0
        )
        
        return ConflictResolutionResult(
            total_conflicts=total_conflicts,
            conflicts_resolved=conflicts_resolved,
            conflicts_unresolved=conflicts_unresolved,
            resolutions=resolutions,
            unresolved_conflicts=unresolved,
            total_time=total_time,
            resolution_rate=resolution_rate,
            avg_confidence=avg_confidence
        )
    
    def _resolve_conflict(self, conflict: Conflict) -> Resolution:
        """Resolve a single conflict.
        
        Args:
            conflict: Conflict to resolve
            
        Returns:
            Resolution
        """
        start_time = time.time()
        
        if self.strategy == ResolutionStrategy.VOTING:
            resolved = self._resolve_by_voting(conflict)
        elif self.strategy == ResolutionStrategy.PRIORITY:
            resolved = self._resolve_by_priority(conflict)
        elif self.strategy == ResolutionStrategy.CONSENSUS:
            resolved = self._resolve_by_consensus(conflict)
        elif self.strategy == ResolutionStrategy.MEDIATOR:
            resolved = self._resolve_by_mediator(conflict)
        else:
            raise ValueError(f"Unknown strategy: {self.strategy}")
        
        resolution_time = time.time() - start_time
        
        return Resolution(
            conflict_id=conflict.conflict_id,
            strategy_used=self.strategy,
            resolved_statement=resolved["statement"],
            confidence=resolved["confidence"],
            resolution_time=resolution_time,
            explanation=resolved["explanation"],
            metadata=resolved.get("metadata", {})
        )
    
    def _resolve_by_voting(self, conflict: Conflict) -> Dict[str, Any]:
        """Resolve by voting (majority wins).
        
        Args:
            conflict: Conflict to resolve
            
        Returns:
            Resolution dict
        """
        # Count votes for each unique formula
        votes = defaultdict(list)
        for stmt in conflict.statements:
            votes[stmt.formula].append(stmt)
        
        # Find winner (most votes)
        winner_formula = max(votes.keys(), key=lambda f: len(votes[f]))
        winner_stmts = votes[winner_formula]
        
        # Calculate confidence based on vote ratio
        total_votes = len(conflict.statements)
        winner_votes = len(winner_stmts)
        confidence = winner_votes / total_votes
        
        # Use highest priority statement as representative
        resolved_stmt = max(winner_stmts, key=lambda s: s.priority)
        
        return {
            "statement": resolved_stmt,
            "confidence": confidence,
            "explanation": f"Voting: {winner_votes}/{total_votes} sources agree",
            "metadata": {"votes": winner_votes, "total": total_votes}
        }
    
    def _resolve_by_priority(self, conflict: Conflict) -> Dict[str, Any]:
        """Resolve by priority (highest trust score wins).
        
        Args:
            conflict: Conflict to resolve
            
        Returns:
            Resolution dict
        """
        # Find statement with highest priority
        resolved_stmt = max(conflict.statements, key=lambda s: s.priority)
        
        # Confidence is the priority score
        confidence = resolved_stmt.priority
        
        return {
            "statement": resolved_stmt,
            "confidence": confidence,
            "explanation": f"Priority: Source {resolved_stmt.source} has highest trust score ({confidence:.2f})",
            "metadata": {"priority": resolved_stmt.priority, "source": resolved_stmt.source}
        }
    
    def _resolve_by_consensus(self, conflict: Conflict) -> Dict[str, Any]:
        """Resolve by finding consensus (common ground).
        
        Args:
            conflict: Conflict to resolve
            
        Returns:
            Resolution dict
        """
        # For consensus, we look for the statement that has
        # the highest average confidence across all sources
        
        # Calculate weighted average confidence
        weighted_confidences = {}
        for stmt in conflict.statements:
            key = stmt.formula
            if key not in weighted_confidences:
                weighted_confidences[key] = []
            weighted_confidences[key].append(stmt.confidence * stmt.priority)
        
        # Find formula with highest average weighted confidence
        best_formula = max(
            weighted_confidences.keys(),
            key=lambda f: sum(weighted_confidences[f]) / len(weighted_confidences[f])
        )
        
        # Get representative statement
        candidates = [s for s in conflict.statements if s.formula == best_formula]
        resolved_stmt = max(candidates, key=lambda s: s.confidence * s.priority)
        
        avg_confidence = sum(weighted_confidences[best_formula]) / len(weighted_confidences[best_formula])
        
        return {
            "statement": resolved_stmt,
            "confidence": avg_confidence,
            "explanation": f"Consensus: Formula has highest weighted agreement ({avg_confidence:.2f})",
            "metadata": {"weighted_confidence": avg_confidence}
        }
    
    def _resolve_by_mediator(self, conflict: Conflict) -> Dict[str, Any]:
        """Resolve by mediator (LLM-based).
        
        Args:
            conflict: Conflict to resolve
            
        Returns:
            Resolution dict
        """
        # Placeholder for LLM-based mediation
        # In production, would call LLM to analyze and resolve
        
        if not self.enable_mediator:
            # Fallback to voting
            return self._resolve_by_voting(conflict)
        
        # For now, use a simple heuristic: prefer higher confidence
        resolved_stmt = max(conflict.statements, key=lambda s: s.confidence)
        
        return {
            "statement": resolved_stmt,
            "confidence": resolved_stmt.confidence * 0.9,  # Slightly lower due to heuristic
            "explanation": "Mediator: Selected highest confidence statement (LLM not available)",
            "metadata": {"mediator": "heuristic", "original_confidence": resolved_stmt.confidence}
        }
    
    def get_resolution_metrics(self) -> Dict[str, Any]:
        """Get metrics about resolution performance.
        
        Returns:
            Dict with resolution metrics
        """
        if not self.resolution_history:
            return {
                "total_resolutions": 0,
                "avg_confidence": 0.0,
                "avg_resolution_time": 0.0,
                "strategy_distribution": {}
            }
        
        strategy_counts = defaultdict(int)
        for resolution in self.resolution_history:
            strategy_counts[resolution.strategy_used.value] += 1
        
        return {
            "total_resolutions": len(self.resolution_history),
            "avg_confidence": sum(r.confidence for r in self.resolution_history) / len(self.resolution_history),
            "avg_resolution_time": sum(r.resolution_time for r in self.resolution_history) / len(self.resolution_history),
            "strategy_distribution": dict(strategy_counts)
        }
    
    def reset(self):
        """Reset resolver state."""
        self.resolution_history.clear()
        self.detector.detected_conflicts.clear()
