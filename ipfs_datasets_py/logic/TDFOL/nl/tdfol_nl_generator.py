"""
TDFOL Formula Generator for Natural Language Processing

This module converts pattern matches from natural language text into formal
TDFOL (Temporal Deontic First-Order Logic) formulas.

Conversions:
- Universal quantification → ∀x.(Agent(x) → ...)
- Obligations → O(...)
- Permissions → P(...)
- Prohibitions → F(...) or ¬P(...)
- Temporal → □(...), ◊(...), X(...), U(..., ...)
- Conditionals → ... → ...
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple, Any

logger = logging.getLogger(__name__)

# Import TDFOL core components
try:
    from ..tdfol_core import (
        Formula,
        Predicate,
        Constant,
        Variable,
        FunctionApplication,
        create_implication,
        create_conjunction,
        create_disjunction,
        create_negation,
        create_universal,
        create_existential,
        create_obligation,
        create_permission,
        create_prohibition,
        create_always,
        create_eventually,
        create_next,
        create_until,
    )
    HAVE_TDFOL_CORE = True
except ImportError:
    HAVE_TDFOL_CORE = False
    logger.warning("TDFOL core not available, formula generation will be limited")

# Import pattern matcher
try:
    from .tdfol_nl_patterns import PatternMatch, PatternType
    HAVE_PATTERNS = True
except ImportError:
    HAVE_PATTERNS = False
    logger.warning("Pattern matcher not available")


@dataclass
class GeneratedFormula:
    """
    Result of generating a TDFOL formula from natural language.
    
    Contains:
    - The generated formula object
    - The pattern match that produced it
    - Confidence score
    - Alternative interpretations (if ambiguous)
    """
    
    formula: Optional[Formula]           # Generated TDFOL formula
    pattern_match: Optional[PatternMatch]  # Source pattern match
    confidence: float                    # Confidence score (0.0-1.0)
    formula_string: str                  # String representation
    entities: Dict[str, str]             # Extracted entities
    alternatives: List['GeneratedFormula'] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


class FormulaGenerator:
    """
    Generate TDFOL formulas from pattern matches.
    
    Converts matched patterns from natural language into formal TDFOL
    formulas using the TDFOL core components.
    
    Example:
        >>> from ipfs_datasets_py.logic.TDFOL.nl import PatternMatcher, FormulaGenerator
        >>> matcher = PatternMatcher()
        >>> generator = FormulaGenerator()
        >>> 
        >>> text = "All contractors must pay taxes."
        >>> matches = matcher.match(text)
        >>> formulas = generator.generate_from_matches(matches)
        >>> 
        >>> print(formulas[0].formula_string)
        ∀x.(Contractor(x) → O(PayTaxes(x)))
    """
    
    def __init__(self):
        """Initialize formula generator."""
        if not HAVE_TDFOL_CORE:
            raise ImportError(
                "TDFOL core is required for formula generation. "
                "Check TDFOL installation."
            )
        
        self._variable_counter = 0
    
    def generate_from_matches(
        self,
        matches: List[PatternMatch],
        context: Optional['Context'] = None
    ) -> List[GeneratedFormula]:
        """
        Generate TDFOL formulas from pattern matches.
        
        Args:
            matches: List of pattern matches from PatternMatcher
            context: Optional context for entity resolution
        
        Returns:
            List of generated formulas with metadata
        """
        formulas = []
        
        for match in matches:
            try:
                generated = self._generate_from_pattern(match, context)
                if generated:
                    formulas.append(generated)
            except Exception as e:
                logger.warning(f"Failed to generate formula from match {match.pattern.name}: {e}")
        
        return formulas
    
    def _generate_from_pattern(
        self,
        match: PatternMatch,
        context: Optional['Context'] = None
    ) -> Optional[GeneratedFormula]:
        """Generate formula from a single pattern match."""
        
        if match.pattern.type == PatternType.UNIVERSAL_QUANTIFICATION:
            return self._generate_universal(match, context)
        elif match.pattern.type == PatternType.OBLIGATION:
            return self._generate_obligation(match, context)
        elif match.pattern.type == PatternType.PERMISSION:
            return self._generate_permission(match, context)
        elif match.pattern.type == PatternType.PROHIBITION:
            return self._generate_prohibition(match, context)
        elif match.pattern.type == PatternType.TEMPORAL:
            return self._generate_temporal(match, context)
        elif match.pattern.type == PatternType.CONDITIONAL:
            return self._generate_conditional(match, context)
        
        return None
    
    def _generate_universal(
        self,
        match: PatternMatch,
        context: Optional['Context']
    ) -> Optional[GeneratedFormula]:
        """
        Generate universal quantification formula.
        
        Pattern: "All contractors must pay taxes"
        Formula: ∀x.(Contractor(x) → O(PayTaxes(x)))
        """
        entities = match.entities
        
        # Get agent and action
        agent = entities.get('agent', 'entity')
        action = entities.get('action', 'act')
        modality = entities.get('modality')
        
        # Create variable
        var = Variable(self._fresh_variable())
        
        # Create agent predicate: Contractor(x)
        agent_name = self._to_predicate_name(agent)
        agent_pred = Predicate(agent_name, [var])
        
        # Create action predicate
        action_name = self._to_predicate_name(action)
        action_pred = Predicate(action_name, [var])
        
        # Apply modality if present
        if modality in ['must', 'shall']:
            # O(PayTaxes(x))
            action_formula = create_obligation(action_pred)
        elif modality == 'may':
            # P(PayTaxes(x))
            action_formula = create_permission(action_pred)
        else:
            action_formula = action_pred
        
        # Create implication: Contractor(x) → O(PayTaxes(x))
        implication = create_implication(agent_pred, action_formula)
        
        # Create universal quantification: ∀x.(...)
        formula = create_universal(var, implication)
        
        return GeneratedFormula(
            formula=formula,
            pattern_match=match,
            confidence=match.confidence * 0.9,  # Slight confidence reduction
            formula_string=formula.to_string(pretty=True),
            entities=entities,
            metadata={'type': 'universal_quantification'}
        )
    
    def _generate_obligation(
        self,
        match: PatternMatch,
        context: Optional['Context']
    ) -> Optional[GeneratedFormula]:
        """
        Generate obligation formula.
        
        Pattern: "Contractor must pay taxes"
        Formula: O(Pay(contractor, taxes))
        """
        entities = match.entities
        
        agent = entities.get('agent', 'agent')
        action = entities.get('action', 'act')
        
        # Create terms
        agent_const = Constant(agent)
        action_name = self._to_predicate_name(action)
        
        # Check if there's an object
        if 'object' in entities:
            obj = entities['object']
            obj_const = Constant(obj)
            action_pred = Predicate(action_name, [agent_const, obj_const])
        else:
            action_pred = Predicate(action_name, [agent_const])
        
        # Create obligation: O(Pay(contractor, taxes))
        formula = create_obligation(action_pred)
        
        return GeneratedFormula(
            formula=formula,
            pattern_match=match,
            confidence=match.confidence,
            formula_string=formula.to_string(pretty=True),
            entities=entities,
            metadata={'type': 'obligation'}
        )
    
    def _generate_permission(
        self,
        match: PatternMatch,
        context: Optional['Context']
    ) -> Optional[GeneratedFormula]:
        """
        Generate permission formula.
        
        Pattern: "Contractor may request extension"
        Formula: P(Request(contractor, extension))
        """
        entities = match.entities
        
        agent = entities.get('agent', 'agent')
        action = entities.get('action', 'act')
        
        # Create terms
        agent_const = Constant(agent)
        action_name = self._to_predicate_name(action)
        
        # Check if there's an object
        if 'object' in entities:
            obj = entities['object']
            obj_const = Constant(obj)
            action_pred = Predicate(action_name, [agent_const, obj_const])
        else:
            action_pred = Predicate(action_name, [agent_const])
        
        # Create permission: P(Request(contractor, extension))
        formula = create_permission(action_pred)
        
        return GeneratedFormula(
            formula=formula,
            pattern_match=match,
            confidence=match.confidence,
            formula_string=formula.to_string(pretty=True),
            entities=entities,
            metadata={'type': 'permission'}
        )
    
    def _generate_prohibition(
        self,
        match: PatternMatch,
        context: Optional['Context']
    ) -> Optional[GeneratedFormula]:
        """
        Generate prohibition formula.
        
        Pattern: "Contractor must not disclose information"
        Formula: F(Disclose(contractor, information))
        """
        entities = match.entities
        
        agent = entities.get('agent', 'agent')
        action = entities.get('action', 'act')
        
        # Create terms
        agent_const = Constant(agent)
        action_name = self._to_predicate_name(action)
        
        # Check if there's an object
        if 'object' in entities:
            obj = entities['object']
            obj_const = Constant(obj)
            action_pred = Predicate(action_name, [agent_const, obj_const])
        else:
            action_pred = Predicate(action_name, [agent_const])
        
        # Create prohibition: F(Disclose(contractor, information))
        formula = create_prohibition(action_pred)
        
        return GeneratedFormula(
            formula=formula,
            pattern_match=match,
            confidence=match.confidence,
            formula_string=formula.to_string(pretty=True),
            entities=entities,
            metadata={'type': 'prohibition'}
        )
    
    def _generate_temporal(
        self,
        match: PatternMatch,
        context: Optional['Context']
    ) -> Optional[GeneratedFormula]:
        """
        Generate temporal formula.
        
        Pattern: "Payment must always be made"
        Formula: □(O(MakePayment()))
        
        Pattern: "Eventually contractor will deliver"
        Formula: ◊(Deliver(contractor))
        """
        text = match.text.lower()
        entities = match.entities
        
        # Determine temporal operator
        if 'always' in text or 'must always' in text:
            temporal_op = 'always'
        elif 'eventually' in text:
            temporal_op = 'eventually'
        elif 'within' in text or 'after' in text or 'before' in text:
            temporal_op = 'eventually'  # Treat deadlines as eventually
        elif 'next' in text or 'immediately' in text:
            temporal_op = 'next'
        elif 'until' in text:
            temporal_op = 'until'
        else:
            temporal_op = 'always'  # Default
        
        # Create base formula (try to extract action)
        action = entities.get('action')
        if action:
            action_name = self._to_predicate_name(action)
            agent = entities.get('agent')
            
            if agent:
                agent_const = Constant(agent)
                base_formula = Predicate(action_name, [agent_const])
            else:
                base_formula = Predicate(action_name, [])
            
            # Apply modality if present
            modality = entities.get('modality')
            if modality in ['must', 'shall']:
                base_formula = create_obligation(base_formula)
            elif modality == 'may':
                base_formula = create_permission(base_formula)
        else:
            # Create generic action
            base_formula = Predicate("Action", [])
        
        # Apply temporal operator
        if temporal_op == 'always':
            formula = create_always(base_formula)
        elif temporal_op == 'eventually':
            formula = create_eventually(base_formula)
        elif temporal_op == 'next':
            formula = create_next(base_formula)
        else:
            formula = create_always(base_formula)  # Default
        
        return GeneratedFormula(
            formula=formula,
            pattern_match=match,
            confidence=match.confidence * 0.85,
            formula_string=formula.to_string(pretty=True),
            entities=entities,
            metadata={'type': 'temporal', 'operator': temporal_op}
        )
    
    def _generate_conditional(
        self,
        match: PatternMatch,
        context: Optional['Context']
    ) -> Optional[GeneratedFormula]:
        """
        Generate conditional formula.
        
        Pattern: "If payment received then deliver goods"
        Formula: PaymentReceived() → DeliverGoods()
        """
        text = match.text.lower()
        entities = match.entities
        
        # Try to extract condition and consequence
        # This is simplified - real implementation would parse more carefully
        if 'if' in text and 'then' in text:
            parts = text.split('then')
            condition_text = parts[0].replace('if', '').strip()
            consequence_text = parts[1].strip() if len(parts) > 1 else ''
        elif 'when' in text:
            parts = text.split('when')
            condition_text = parts[1].split(',')[0].strip() if len(parts) > 1 else ''
            consequence_text = text.split(',')[1].strip() if ',' in text else ''
        else:
            condition_text = ''
            consequence_text = ''
        
        # Create condition formula (simplified)
        condition = Predicate(self._to_predicate_name(condition_text or "Condition"), [])
        
        # Create consequence formula (simplified)
        consequence = Predicate(self._to_predicate_name(consequence_text or "Consequence"), [])
        
        # Create implication
        formula = create_implication(condition, consequence)
        
        return GeneratedFormula(
            formula=formula,
            pattern_match=match,
            confidence=match.confidence * 0.8,  # Lower confidence for complex patterns
            formula_string=formula.to_string(pretty=True),
            entities=entities,
            metadata={'type': 'conditional'}
        )
    
    def _to_predicate_name(self, text: str) -> str:
        """
        Convert text to a valid predicate name.
        
        Example: "pay taxes" → "PayTaxes"
        """
        if not text:
            return "Predicate"
        
        # Remove special characters and split into words
        words = re.sub(r'[^a-zA-Z0-9\s]', '', text).split()
        
        # Capitalize each word and join
        name = ''.join(word.capitalize() for word in words if word)
        
        # Ensure it starts with uppercase
        if name and not name[0].isupper():
            name = name[0].upper() + name[1:]
        
        return name or "Predicate"
    
    def _fresh_variable(self) -> str:
        """Generate a fresh variable name."""
        var_name = f"x{self._variable_counter}"
        self._variable_counter += 1
        return var_name
    
    def reset_variables(self) -> None:
        """Reset variable counter."""
        self._variable_counter = 0
