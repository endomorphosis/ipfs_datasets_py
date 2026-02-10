"""
Deontic Logic Query Engine

This module provides a query interface for deontic logic formulas, enabling
users to query legal obligations, permissions, prohibitions, and perform
compliance checking against legal rule sets.
"""

import logging
from typing import Dict, List, Optional, Any, Union, Set
from dataclasses import dataclass, field
from enum import Enum
import re

from ..tools.deontic_logic_core import (
    DeonticFormula, DeonticOperator, LegalAgent, DeonticRuleSet,
    TemporalCondition, TemporalOperator
)
from .legal_domain_knowledge import LegalDomain

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class QueryType(Enum):
    """Types of queries supported by the deontic logic query engine."""
    OBLIGATIONS = "obligations"
    PERMISSIONS = "permissions"
    PROHIBITIONS = "prohibitions"
    AGENT_DUTIES = "agent_duties"
    COMPLIANCE_CHECK = "compliance_check"
    TEMPORAL_CONSTRAINTS = "temporal_constraints"
    CONFLICTS = "conflicts"


@dataclass
class QueryResult:
    """Result of a deontic logic query."""
    query_type: QueryType
    matching_formulas: List[DeonticFormula] = field(default_factory=list)
    total_matches: int = 0
    confidence_scores: List[float] = field(default_factory=list)
    query_metadata: Dict[str, Any] = field(default_factory=dict)
    reasoning: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "query_type": self.query_type.value,
            "total_matches": self.total_matches,
            "matching_formulas": [f.to_dict() for f in self.matching_formulas],
            "confidence_scores": self.confidence_scores,
            "query_metadata": self.query_metadata,
            "reasoning": self.reasoning
        }


@dataclass
class ComplianceResult:
    """Result of a compliance check."""
    is_compliant: bool
    compliance_score: float = 0.0
    violated_obligations: List[DeonticFormula] = field(default_factory=list)
    missing_permissions: List[DeonticFormula] = field(default_factory=list)
    violated_prohibitions: List[DeonticFormula] = field(default_factory=list)
    reasoning: str = ""
    recommendations: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "is_compliant": self.is_compliant,
            "compliance_score": self.compliance_score,
            "violated_obligations": [f.to_dict() for f in self.violated_obligations],
            "missing_permissions": [f.to_dict() for f in self.missing_permissions],
            "violated_prohibitions": [f.to_dict() for f in self.violated_prohibitions],
            "reasoning": self.reasoning,
            "recommendations": self.recommendations
        }


@dataclass
class LogicConflict:
    """Represents a logical conflict between deontic formulas."""
    conflict_type: str  # "obligation_prohibition", "circular_dependency", etc.
    formula1: DeonticFormula
    formula2: DeonticFormula
    severity: str  # "critical", "warning", "info"
    description: str
    confidence: float = 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "conflict_type": self.conflict_type,
            "formula1": self.formula1.to_dict(),
            "formula2": self.formula2.to_dict(),
            "severity": self.severity,
            "description": self.description,
            "confidence": self.confidence
        }


class DeonticQueryEngine:
    """Query engine for deontic logic formulas with compliance checking."""
    
    def __init__(self, rule_set: Optional[DeonticRuleSet] = None):
        """
        Initialize the deontic query engine.
        
        Args:
            rule_set: Optional rule set to query against
        """
        self.rule_set = rule_set
        self.formula_index: Dict[str, List[DeonticFormula]] = {}
        self.agent_index: Dict[str, List[DeonticFormula]] = {}
        self.operator_index: Dict[DeonticOperator, List[DeonticFormula]] = {}
        
        if rule_set:
            self._build_indexes(rule_set.formulas)
    
    def load_rule_set(self, rule_set: DeonticRuleSet):
        """Load a new rule set and rebuild indexes."""
        self.rule_set = rule_set
        self._build_indexes(rule_set.formulas)
        logger.info(f"Loaded rule set '{rule_set.name}' with {len(rule_set.formulas)} formulas")
    
    def _build_indexes(self, formulas: List[DeonticFormula]):
        """Build indexes for efficient querying."""
        self.formula_index.clear()
        self.agent_index.clear()
        self.operator_index.clear()
        
        for formula in formulas:
            # Index by proposition keywords
            proposition_words = set(re.findall(r'\w+', formula.proposition.lower()))
            for word in proposition_words:
                if word not in self.formula_index:
                    self.formula_index[word] = []
                self.formula_index[word].append(formula)
            
            # Index by agent
            if formula.agent:
                agent_key = formula.agent.identifier.lower()
                if agent_key not in self.agent_index:
                    self.agent_index[agent_key] = []
                self.agent_index[agent_key].append(formula)
            
            # Index by operator
            if formula.operator not in self.operator_index:
                self.operator_index[formula.operator] = []
            self.operator_index[formula.operator].append(formula)
        
        logger.debug(f"Built indexes: {len(self.formula_index)} propositions, "
                    f"{len(self.agent_index)} agents, {len(self.operator_index)} operators")
    
    def query_obligations(self, agent: Optional[str] = None, 
                         context: Optional[Dict[str, Any]] = None) -> QueryResult:
        """
        Find all obligations for a specific agent or in general.
        
        Args:
            agent: Optional agent identifier
            context: Optional context for filtering
            
        Returns:
            Query result with matching obligations
        """
        obligations = self.operator_index.get(DeonticOperator.OBLIGATION, [])
        
        if agent:
            # Filter by agent
            agent_key = agent.lower()
            obligations = [f for f in obligations 
                          if f.agent and agent_key in f.agent.identifier.lower()]
        
        # Apply context filtering if provided
        if context:
            obligations = self._apply_context_filter(obligations, context)
        
        return QueryResult(
            query_type=QueryType.OBLIGATIONS,
            matching_formulas=obligations,
            total_matches=len(obligations),
            confidence_scores=[f.confidence for f in obligations],
            query_metadata={"agent": agent, "context": context},
            reasoning=f"Found {len(obligations)} obligations" + (f" for agent {agent}" if agent else "")
        )
    
    def query_permissions(self, action: Optional[str] = None, 
                         agent: Optional[str] = None) -> QueryResult:
        """
        Find permissions for specific actions or agents.
        
        Args:
            action: Optional action to search for
            agent: Optional agent identifier
            
        Returns:
            Query result with matching permissions
        """
        permissions = self.operator_index.get(DeonticOperator.PERMISSION, [])
        
        if action:
            # Filter by action/proposition
            action_words = set(re.findall(r'\w+', action.lower()))
            permissions = [f for f in permissions 
                          if any(word in f.proposition.lower() for word in action_words)]
        
        if agent:
            # Filter by agent
            agent_key = agent.lower()
            permissions = [f for f in permissions 
                          if f.agent and agent_key in f.agent.identifier.lower()]
        
        return QueryResult(
            query_type=QueryType.PERMISSIONS,
            matching_formulas=permissions,
            total_matches=len(permissions),
            confidence_scores=[f.confidence for f in permissions],
            query_metadata={"action": action, "agent": agent},
            reasoning=f"Found {len(permissions)} permissions" + 
                     (f" for action '{action}'" if action else "") +
                     (f" for agent {agent}" if agent else "")
        )
    
    def query_prohibitions(self, action: Optional[str] = None,
                          agent: Optional[str] = None) -> QueryResult:
        """
        Find prohibitions for specific actions or agents.
        
        Args:
            action: Optional action to search for
            agent: Optional agent identifier
            
        Returns:
            Query result with matching prohibitions
        """
        prohibitions = self.operator_index.get(DeonticOperator.PROHIBITION, [])
        
        if action:
            # Filter by action/proposition
            action_words = set(re.findall(r'\w+', action.lower()))
            prohibitions = [f for f in prohibitions 
                           if any(word in f.proposition.lower() for word in action_words)]
        
        if agent:
            # Filter by agent
            agent_key = agent.lower()
            prohibitions = [f for f in prohibitions 
                           if f.agent and agent_key in f.agent.identifier.lower()]
        
        return QueryResult(
            query_type=QueryType.PROHIBITIONS,
            matching_formulas=prohibitions,
            total_matches=len(prohibitions),
            confidence_scores=[f.confidence for f in prohibitions],
            query_metadata={"action": action, "agent": agent},
            reasoning=f"Found {len(prohibitions)} prohibitions" +
                     (f" for action '{action}'" if action else "") +
                     (f" for agent {agent}" if agent else "")
        )
    
    def check_compliance(self, proposed_action: str, 
                        agent: str,
                        context: Optional[Dict[str, Any]] = None) -> ComplianceResult:
        """
        Check if a proposed action complies with the legal rules.
        
        Args:
            proposed_action: Description of the proposed action
            agent: Agent who would perform the action
            context: Optional context information
            
        Returns:
            Compliance analysis result
        """
        # Find relevant formulas
        action_words = set(re.findall(r'\w+', proposed_action.lower()))
        agent_key = agent.lower()
        
        # Check obligations
        obligations = self.query_obligations(agent, context).matching_formulas
        violated_obligations = []
        
        for obligation in obligations:
            # Check if the proposed action satisfies this obligation
            if not self._action_satisfies_obligation(proposed_action, obligation):
                violated_obligations.append(obligation)
        
        # Check prohibitions
        prohibitions = self.query_prohibitions(agent=agent).matching_formulas
        violated_prohibitions = []
        
        for prohibition in prohibitions:
            # Check if the proposed action violates this prohibition
            if self._action_violates_prohibition(proposed_action, prohibition):
                violated_prohibitions.append(prohibition)
        
        # Check permissions
        permissions = self.query_permissions(agent=agent).matching_formulas
        missing_permissions = []
        
        # Check if action requires permission that isn't granted
        if self._action_requires_permission(proposed_action) and not permissions:
            # Create a placeholder for missing permission
            missing_permissions.append("Action may require explicit permission")
        
        # Calculate compliance score
        total_violations = len(violated_obligations) + len(violated_prohibitions) + len(missing_permissions)
        total_relevant_rules = len(obligations) + len(prohibitions) + max(1, len(permissions))
        compliance_score = max(0.0, 1.0 - (total_violations / total_relevant_rules))
        
        is_compliant = total_violations == 0
        
        # Generate recommendations
        recommendations = []
        if violated_obligations:
            recommendations.append(f"Ensure compliance with {len(violated_obligations)} obligations")
        if violated_prohibitions:
            recommendations.append(f"Avoid actions that violate {len(violated_prohibitions)} prohibitions")
        if missing_permissions:
            recommendations.append("Obtain necessary permissions before proceeding")
        
        return ComplianceResult(
            is_compliant=is_compliant,
            compliance_score=compliance_score,
            violated_obligations=violated_obligations,
            missing_permissions=[],  # Simplified for now
            violated_prohibitions=violated_prohibitions,
            reasoning=f"Analyzed action '{proposed_action}' for agent '{agent}' against {total_relevant_rules} rules",
            recommendations=recommendations
        )
    
    def find_conflicts(self, formulas: Optional[List[DeonticFormula]] = None) -> List[LogicConflict]:
        """
        Find logical conflicts between deontic formulas.
        
        Args:
            formulas: Optional list of formulas to check (uses rule set if None)
            
        Returns:
            List of detected conflicts
        """
        if formulas is None:
            formulas = self.rule_set.formulas if self.rule_set else []
        
        conflicts = []
        
        # Check for obligation-prohibition conflicts
        obligations = [f for f in formulas if f.operator == DeonticOperator.OBLIGATION]
        prohibitions = [f for f in formulas if f.operator == DeonticOperator.PROHIBITION]
        
        for obligation in obligations:
            for prohibition in prohibitions:
                if self._formulas_conflict(obligation, prohibition):
                    conflicts.append(LogicConflict(
                        conflict_type="obligation_prohibition",
                        formula1=obligation,
                        formula2=prohibition,
                        severity="critical",
                        description=f"Obligation to {obligation.proposition} conflicts with "
                                  f"prohibition of {prohibition.proposition}",
                        confidence=0.8
                    ))
        
        # Check for circular dependencies
        circular_conflicts = self._find_circular_dependencies(formulas)
        conflicts.extend(circular_conflicts)
        
        # Check for temporal conflicts
        temporal_conflicts = self._find_temporal_conflicts(formulas)
        conflicts.extend(temporal_conflicts)
        
        return conflicts
    
    def query_by_natural_language(self, query: str) -> QueryResult:
        """
        Query using natural language.
        
        Args:
            query: Natural language query
            
        Returns:
            Query result based on natural language interpretation
        """
        query_lower = query.lower()
        
        # Parse query intent
        if any(word in query_lower for word in ["must", "obligation", "required", "duty"]):
            query_type = QueryType.OBLIGATIONS
            formulas = self.operator_index.get(DeonticOperator.OBLIGATION, [])
        elif any(word in query_lower for word in ["may", "can", "permission", "allowed"]):
            query_type = QueryType.PERMISSIONS
            formulas = self.operator_index.get(DeonticOperator.PERMISSION, [])
        elif any(word in query_lower for word in ["not", "prohibition", "forbidden", "banned"]):
            query_type = QueryType.PROHIBITIONS
            formulas = self.operator_index.get(DeonticOperator.PROHIBITION, [])
        else:
            # Default to searching all formulas
            query_type = QueryType.OBLIGATIONS
            formulas = self.rule_set.formulas if self.rule_set else []
        
        # Extract keywords from query
        keywords = set(re.findall(r'\w+', query_lower))
        keywords.discard('what')
        keywords.discard('are')
        keywords.discard('the')
        keywords.discard('for')
        keywords.discard('of')
        
        # Filter formulas based on keywords
        matching_formulas = []
        for formula in formulas:
            formula_text = (formula.proposition + " " + formula.source_text).lower()
            if any(keyword in formula_text for keyword in keywords):
                matching_formulas.append(formula)
        
        return QueryResult(
            query_type=query_type,
            matching_formulas=matching_formulas,
            total_matches=len(matching_formulas),
            confidence_scores=[f.confidence for f in matching_formulas],
            query_metadata={"natural_language_query": query, "extracted_keywords": list(keywords)},
            reasoning=f"Natural language query interpreted as {query_type.value} search with keywords: {keywords}"
        )
    
    def get_agent_summary(self, agent: str) -> Dict[str, Any]:
        """
        Get a comprehensive summary of all rules applying to a specific agent.
        
        Args:
            agent: Agent identifier
            
        Returns:
            Comprehensive agent summary
        """
        agent_key = agent.lower()
        agent_formulas = []
        
        if self.rule_set:
            agent_formulas = [f for f in self.rule_set.formulas 
                             if f.agent and agent_key in f.agent.identifier.lower()]
        
        # Categorize by operator
        summary = {
            "agent": agent,
            "total_rules": len(agent_formulas),
            "obligations": [f for f in agent_formulas if f.operator == DeonticOperator.OBLIGATION],
            "permissions": [f for f in agent_formulas if f.operator == DeonticOperator.PERMISSION],
            "prohibitions": [f for f in agent_formulas if f.operator == DeonticOperator.PROHIBITION],
            "temporal_constraints": []
        }
        
        # Extract temporal constraints
        for formula in agent_formulas:
            if formula.temporal_conditions:
                summary["temporal_constraints"].extend(formula.temporal_conditions)
        
        # Add counts
        summary["counts"] = {
            "obligations": len(summary["obligations"]),
            "permissions": len(summary["permissions"]),
            "prohibitions": len(summary["prohibitions"]),
            "temporal_constraints": len(summary["temporal_constraints"])
        }
        
        return summary
    
    def search_by_keywords(self, keywords: List[str], 
                          operator_filter: Optional[DeonticOperator] = None) -> QueryResult:
        """
        Search formulas by keywords with optional operator filtering.
        
        Args:
            keywords: List of keywords to search for
            operator_filter: Optional deontic operator to filter by
            
        Returns:
            Query result with matching formulas
        """
        matching_formulas = []
        formulas_to_search = []
        
        if operator_filter:
            formulas_to_search = self.operator_index.get(operator_filter, [])
        else:
            formulas_to_search = self.rule_set.formulas if self.rule_set else []
        
        for formula in formulas_to_search:
            formula_text = (formula.proposition + " " + formula.source_text).lower()
            if any(keyword.lower() in formula_text for keyword in keywords):
                matching_formulas.append(formula)
        
        return QueryResult(
            query_type=QueryType.OBLIGATIONS if operator_filter == DeonticOperator.OBLIGATION else QueryType.PERMISSIONS,
            matching_formulas=matching_formulas,
            total_matches=len(matching_formulas),
            confidence_scores=[f.confidence for f in matching_formulas],
            query_metadata={"keywords": keywords, "operator_filter": operator_filter.value if operator_filter else None},
            reasoning=f"Keyword search for {keywords} found {len(matching_formulas)} matches"
        )
    
    def _apply_context_filter(self, formulas: List[DeonticFormula], 
                            context: Dict[str, Any]) -> List[DeonticFormula]:
        """Apply context-based filtering to formulas."""
        filtered = []
        
        for formula in formulas:
            # Check temporal context
            if "time" in context:
                if not self._formula_applies_at_time(formula, context["time"]):
                    continue
            
            # Check conditional context
            if "conditions" in context:
                if not self._formula_conditions_met(formula, context["conditions"]):
                    continue
            
            filtered.append(formula)
        
        return filtered
    
    def _action_satisfies_obligation(self, action: str, obligation: DeonticFormula) -> bool:
        """Check if an action satisfies an obligation."""
        action_words = set(re.findall(r'\w+', action.lower()))
        obligation_words = set(re.findall(r'\w+', obligation.proposition.lower()))
        
        # Simple keyword overlap check (could be more sophisticated)
        overlap = len(action_words & obligation_words)
        return overlap > 0
    
    def _action_violates_prohibition(self, action: str, prohibition: DeonticFormula) -> bool:
        """Check if an action violates a prohibition."""
        action_words = set(re.findall(r'\w+', action.lower()))
        prohibition_words = set(re.findall(r'\w+', prohibition.proposition.lower()))
        
        # If action contains prohibited concepts, it's a violation
        overlap = len(action_words & prohibition_words)
        return overlap > 0
    
    def _action_requires_permission(self, action: str) -> bool:
        """Check if an action typically requires explicit permission."""
        # Actions that typically require permission
        permission_requiring_actions = [
            "inspect", "audit", "terminate", "modify", "access", "disclose"
        ]
        
        action_lower = action.lower()
        return any(perm_action in action_lower for perm_action in permission_requiring_actions)
    
    def _formulas_conflict(self, formula1: DeonticFormula, formula2: DeonticFormula) -> bool:
        """Check if two formulas logically conflict."""
        # Check for obligation-prohibition conflicts
        if (formula1.operator == DeonticOperator.OBLIGATION and 
            formula2.operator == DeonticOperator.PROHIBITION):
            
            # Check if they involve similar propositions and same agent
            if (formula1.agent and formula2.agent and 
                formula1.agent.identifier == formula2.agent.identifier):
                
                prop1_words = set(re.findall(r'\w+', formula1.proposition.lower()))
                prop2_words = set(re.findall(r'\w+', formula2.proposition.lower()))
                
                # If significant overlap in propositions, they may conflict
                overlap = len(prop1_words & prop2_words)
                return overlap >= 2
        
        return False
    
    def _find_circular_dependencies(self, formulas: List[DeonticFormula]) -> List[LogicConflict]:
        """Find circular dependencies in formulas."""
        # Simplified implementation - could be more sophisticated
        conflicts = []
        
        # Look for formulas that reference each other in conditions
        for i, formula1 in enumerate(formulas):
            for j, formula2 in enumerate(formulas[i+1:], i+1):
                if self._has_circular_dependency(formula1, formula2):
                    conflicts.append(LogicConflict(
                        conflict_type="circular_dependency",
                        formula1=formula1,
                        formula2=formula2,
                        severity="warning",
                        description="Formulas may have circular dependency",
                        confidence=0.6
                    ))
        
        return conflicts
    
    def _find_temporal_conflicts(self, formulas: List[DeonticFormula]) -> List[LogicConflict]:
        """Find temporal conflicts between formulas."""
        conflicts = []
        
        # Look for temporal impossibilities
        for i, formula1 in enumerate(formulas):
            for j, formula2 in enumerate(formulas[i+1:], i+1):
                if self._has_temporal_conflict(formula1, formula2):
                    conflicts.append(LogicConflict(
                        conflict_type="temporal_conflict",
                        formula1=formula1,
                        formula2=formula2,
                        severity="warning",
                        description="Formulas have conflicting temporal requirements",
                        confidence=0.7
                    ))
        
        return conflicts
    
    def _has_circular_dependency(self, formula1: DeonticFormula, formula2: DeonticFormula) -> bool:
        """Check if two formulas have circular dependency."""
        # Simplified check - in practice would be more sophisticated
        return False
    
    def _has_temporal_conflict(self, formula1: DeonticFormula, formula2: DeonticFormula) -> bool:
        """Check if two formulas have temporal conflicts."""
        # Simplified check - in practice would analyze temporal conditions
        return False
    
    def _formula_applies_at_time(self, formula: DeonticFormula, time: str) -> bool:
        """Check if formula applies at specified time."""
        # Simplified temporal checking
        return True
    
    def _formula_conditions_met(self, formula: DeonticFormula, conditions: Dict[str, Any]) -> bool:
        """Check if formula conditions are met."""
        # Simplified condition checking
        return True


# Convenience functions
def create_query_engine(rule_set: DeonticRuleSet) -> DeonticQueryEngine:
    """Create a query engine with a specific rule set."""
    return DeonticQueryEngine(rule_set)


def query_legal_rules(rule_set: DeonticRuleSet, 
                     natural_language_query: str) -> QueryResult:
    """Quick natural language query against a rule set."""
    engine = DeonticQueryEngine(rule_set)
    return engine.query_by_natural_language(natural_language_query)