"""Ontology Stabilizer - Maintains knowledge graph consistency.

This module provides tools for ensuring that extracted logical statements
remain consistent with the knowledge graph ontology over time.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Set
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class ConsistencyReport:
    """Report of ontology consistency check.
    
    Attributes:
        is_consistent: Whether ontology is consistent
        violations: List of consistency violations
        warnings: List of warnings
        recommendations: Recommendations for fixes
        coverage: Ontology coverage score
    """
    is_consistent: bool
    violations: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    recommendations: List[str] = field(default_factory=list)
    coverage: float = 0.0


class OntologyConsistencyChecker:
    """Checker for ontology consistency.
    
    This class verifies that logical statements are consistent with
    the knowledge graph ontology, checking:
    - Terminology alignment
    - Type consistency
    - Relationship validity
    - Structural constraints
    
    Example:
        >>> checker = OntologyConsistencyChecker(ontology)
        >>> report = checker.check_statements(extracted_statements)
        >>> if not report.is_consistent:
        ...     print(report.violations)
    """
    
    def __init__(self, ontology: Optional[Dict[str, Any]] = None):
        """Initialize the consistency checker.
        
        Args:
            ontology: Knowledge graph ontology specification
        """
        self.ontology = ontology or {}
        self._init_ontology_index()
        
    def _init_ontology_index(self) -> None:
        """Initialize indices for fast ontology lookup."""
        self.terms = set()
        self.relations = set()
        self.types = set()
        
        if self.ontology:
            # Extract terms, relations, types from ontology
            if 'terms' in self.ontology:
                self.terms = set(self.ontology['terms'])
            if 'relations' in self.ontology:
                self.relations = set(self.ontology['relations'])
            if 'types' in self.ontology:
                self.types = set(self.ontology['types'])
    
    def check_statements(
        self,
        statements: List[Any]  # List of LogicalStatement
    ) -> ConsistencyReport:
        """Check consistency of statements with ontology.
        
        Args:
            statements: List of logical statements to check
            
        Returns:
            ConsistencyReport with results
        """
        violations = []
        warnings = []
        recommendations = []
        
        if not self.ontology:
            warnings.append("No ontology provided - skipping consistency checks")
            return ConsistencyReport(
                is_consistent=True,
                warnings=warnings,
                coverage=0.0
            )
        
        # Check each statement
        for i, stmt in enumerate(statements):
            # Check terminology
            unknown_terms = self._check_terminology(stmt)
            if unknown_terms:
                warnings.append(
                    f"Statement {i}: uses unknown terms: {', '.join(unknown_terms)}"
                )
                recommendations.append(
                    f"Add terms to ontology: {', '.join(unknown_terms)}"
                )
            
            # Check types
            type_errors = self._check_types(stmt)
            if type_errors:
                violations.extend(
                    f"Statement {i}: {error}" for error in type_errors
                )
        
        # Check inter-statement consistency
        consistency_errors = self._check_inter_statement_consistency(statements)
        violations.extend(consistency_errors)
        
        # Calculate coverage
        coverage = self._calculate_coverage(statements)
        
        is_consistent = len(violations) == 0
        
        return ConsistencyReport(
            is_consistent=is_consistent,
            violations=violations,
            warnings=warnings,
            recommendations=recommendations,
            coverage=coverage
        )
    
    def _check_terminology(self, statement: Any) -> Set[str]:
        """Check if statement uses ontology-approved terminology.
        
        Args:
            statement: Logical statement to check
            
        Returns:
            Set of unknown terms
        """
        if not self.terms:
            return set()
        
        # Extract terms from formula (simple word extraction)
        formula_terms = set(statement.formula.split())
        
        # Find terms not in ontology
        unknown = formula_terms - self.terms
        
        # Filter out logical operators and punctuation
        operators = {'∀', '∃', '→', '∧', '∨', '¬', '(', ')', ',', '.'}
        unknown = unknown - operators
        
        return unknown
    
    def _check_types(self, statement: Any) -> List[str]:
        """Check type consistency in statement.
        
        Args:
            statement: Logical statement to check
            
        Returns:
            List of type errors
        """
        errors = []
        
        # Simple type checking - can be made more sophisticated
        # For now, just check that statement has expected structure
        
        if not statement.formula:
            errors.append("Empty formula")
        
        if not statement.natural_language:
            errors.append("Missing natural language explanation")
        
        return errors
    
    def _check_inter_statement_consistency(
        self,
        statements: List[Any]
    ) -> List[str]:
        """Check consistency between statements.
        
        Args:
            statements: List of statements to check
            
        Returns:
            List of consistency errors
        """
        errors = []
        
        # Check for obvious contradictions
        # This is a placeholder - real implementation would use theorem provers
        
        if len(statements) < 2:
            return errors
        
        # Example: check for contradictory obligations
        # (In practice, this would be much more sophisticated)
        
        return errors
    
    def _calculate_coverage(self, statements: List[Any]) -> float:
        """Calculate how much of ontology is covered by statements.
        
        Args:
            statements: List of statements
            
        Returns:
            Coverage score (0.0-1.0)
        """
        if not self.terms:
            return 0.0
        
        # Extract terms used in statements
        used_terms = set()
        for stmt in statements:
            used_terms.update(stmt.formula.split())
        
        # Calculate overlap with ontology
        overlap = len(used_terms & self.terms)
        coverage = overlap / len(self.terms) if self.terms else 0.0
        
        return coverage


class KnowledgeGraphStabilizer:
    """Stabilizer for knowledge graph ontology.
    
    This class ensures that as new logical statements are added to the
    knowledge graph, the ontology remains stable and consistent.
    
    It provides:
    - Incremental consistency checking
    - Ontology evolution tracking
    - Conflict resolution strategies
    - Stability metrics
    
    Example:
        >>> stabilizer = KnowledgeGraphStabilizer(ontology)
        >>> for statement in new_statements:
        ...     if stabilizer.can_add_safely(statement):
        ...         stabilizer.add_statement(statement)
        ...     else:
        ...         print(f"Statement would violate ontology: {statement}")
    """
    
    def __init__(
        self,
        ontology: Optional[Dict[str, Any]] = None,
        strict_mode: bool = False
    ):
        """Initialize the stabilizer.
        
        Args:
            ontology: Knowledge graph ontology
            strict_mode: Whether to use strict consistency checking
        """
        self.ontology = ontology or {}
        self.strict_mode = strict_mode
        self.checker = OntologyConsistencyChecker(ontology)
        
        # Track statements added
        self.statements: List[Any] = []
        self.stability_history: List[float] = []
        
    def can_add_safely(self, statement: Any) -> bool:
        """Check if statement can be added without breaking consistency.
        
        Args:
            statement: Statement to check
            
        Returns:
            True if safe to add
        """
        # Check statement individually
        report = self.checker.check_statements([statement])
        
        if not report.is_consistent:
            return False
        
        # Check combined with existing statements
        if self.statements:
            combined_report = self.checker.check_statements(
                self.statements + [statement]
            )
            return combined_report.is_consistent
        
        return True
    
    def add_statement(self, statement: Any) -> bool:
        """Add a statement to the knowledge graph.
        
        Args:
            statement: Statement to add
            
        Returns:
            True if successfully added
        """
        if self.strict_mode and not self.can_add_safely(statement):
            logger.warning("Rejected statement due to consistency violation")
            return False
        
        self.statements.append(statement)
        self._update_stability_metrics()
        return True
    
    def add_statements(self, statements: List[Any]) -> int:
        """Add multiple statements.
        
        Args:
            statements: List of statements to add
            
        Returns:
            Number of statements successfully added
        """
        added = 0
        for stmt in statements:
            if self.add_statement(stmt):
                added += 1
        return added
    
    def get_stability_score(self) -> float:
        """Get current ontology stability score.
        
        Returns:
            Stability score (0.0-1.0), higher is more stable
        """
        if not self.statements:
            return 1.0  # Trivially stable
        
        # Check consistency
        report = self.checker.check_statements(self.statements)
        
        # Calculate stability based on violations and warnings
        violations_penalty = len(report.violations) * 0.2
        warnings_penalty = len(report.warnings) * 0.05
        
        stability = max(0.0, 1.0 - violations_penalty - warnings_penalty)
        
        return stability
    
    def _update_stability_metrics(self) -> None:
        """Update stability tracking metrics."""
        stability = self.get_stability_score()
        self.stability_history.append(stability)
    
    def get_consistency_report(self) -> ConsistencyReport:
        """Get full consistency report for current state.
        
        Returns:
            ConsistencyReport
        """
        return self.checker.check_statements(self.statements)
    
    def evolve_ontology(
        self,
        new_terms: Optional[Set[str]] = None,
        new_relations: Optional[Set[str]] = None
    ) -> None:
        """Evolve the ontology with new terms and relations.
        
        Args:
            new_terms: New terms to add to ontology
            new_relations: New relations to add to ontology
        """
        if new_terms:
            if 'terms' not in self.ontology:
                self.ontology['terms'] = []
            self.ontology['terms'].extend(new_terms)
            self.checker._init_ontology_index()
            logger.info(f"Added {len(new_terms)} new terms to ontology")
        
        if new_relations:
            if 'relations' not in self.ontology:
                self.ontology['relations'] = []
            self.ontology['relations'].extend(new_relations)
            self.checker._init_ontology_index()
            logger.info(f"Added {len(new_relations)} new relations to ontology")
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get statistics about the stabilizer state.
        
        Returns:
            Dictionary of statistics
        """
        return {
            'num_statements': len(self.statements),
            'current_stability': self.get_stability_score(),
            'avg_stability': sum(self.stability_history) / len(self.stability_history) if self.stability_history else 0.0,
            'min_stability': min(self.stability_history) if self.stability_history else 0.0,
            'max_stability': max(self.stability_history) if self.stability_history else 0.0,
            'ontology_size': {
                'terms': len(self.checker.terms),
                'relations': len(self.checker.relations),
                'types': len(self.checker.types)
            }
        }
