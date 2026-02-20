"""
Interactive FOL Constructor Module

This module provides an interactive interface for constructing First-Order Logic
formulas step by step, with real-time analysis and validation using SymbolicAI.

Refactored to improve modularity - types and utilities extracted to separate modules.
"""

import logging
import json
import uuid
from datetime import datetime
from typing import Dict, List, Optional, Any, Tuple, Union
try:
    from beartype import beartype  # type: ignore
except Exception:  # pragma: no cover
    def beartype(func):  # type: ignore
        return func

# Configure logging
logger = logging.getLogger(__name__)

# Conditional imports
try:
    from symai import Symbol
    SYMBOLIC_AI_AVAILABLE = True
except ImportError:
    SYMBOLIC_AI_AVAILABLE = False
    logger.warning("SymbolicAI not available. Interactive constructor will use fallback mode.")
    
    class Symbol:
        def __init__(self, value: str, semantic: bool = False):
            self.value = value
            self._semantic = semantic

# Local imports
from ..bridges.symbolic_fol_bridge import SymbolicFOLBridge, LogicalComponents, FOLConversionResult
from ..symbolic.symbolic_logic_primitives import create_logic_symbol, LogicPrimitives

# Import types from separate module (refactored for modularity)
from .interactive_fol_types import StatementRecord, SessionMetadata
from ._fol_constructor_io import FOLConstructorIOMixin


class InteractiveFOLConstructor(FOLConstructorIOMixin):
    """
    Interactive FOL constructor for step-by-step logic building.
    
    This class provides an interactive interface for constructing logical
    formulas incrementally, with real-time analysis, consistency checking,
    and formula generation.
    """
    
    def __init__(
        self,
        domain: str = "general",
        confidence_threshold: float = 0.6,
        enable_consistency_checking: bool = True
    ):
        """
        Initialize the interactive FOL constructor.
        
        Args:
            domain: Domain of knowledge (e.g., "mathematics", "legal", "general")
            confidence_threshold: Minimum confidence for accepting statements
            enable_consistency_checking: Whether to check logical consistency
        """
        self.session_id = str(uuid.uuid4())
        self.domain = domain
        self.confidence_threshold = confidence_threshold
        self.enable_consistency_checking = enable_consistency_checking
        
        # Session state
        self.session_statements: Dict[str, StatementRecord] = {}
        self.session_symbols: List[Symbol] = []
        self.current_context: List[str] = []
        
        # Components
        self.bridge = SymbolicFOLBridge(
            confidence_threshold=confidence_threshold,
            fallback_enabled=True
        )
        
        # Session metadata
        self.metadata = SessionMetadata(
            session_id=self.session_id,
            created_at=datetime.now(),
            last_modified=datetime.now(),
            total_statements=0,
            consistent_statements=0,
            inconsistent_statements=0,
            average_confidence=0.0,
            domain=domain
        )
        
        logger.info(f"Interactive FOL Constructor initialized for domain '{domain}'")
    
    @beartype
    def add_statement(
        self, 
        text: str, 
        tags: Optional[List[str]] = None,
        force_add: bool = False
    ) -> Dict[str, Any]:
        """
        Add a new statement to the interactive session.
        
        Args:
            text: Natural language statement to add
            tags: Optional tags for categorizing the statement
            force_add: Whether to add statement even if confidence is low
            
        Returns:
            Dictionary with analysis results and statement metadata
        """
        if not text or not text.strip():
            raise ValueError("Statement text cannot be empty")
        
        text = text.strip()
        statement_id = str(uuid.uuid4())
        
        try:
            # Step 1: Create semantic symbol and analyze
            symbol = self.bridge.create_semantic_symbol(text)
            if not symbol:
                raise ValueError("Failed to create semantic symbol")
            
            # Step 2: Extract logical components
            components = self.bridge.extract_logical_components(symbol)
            
            # Step 3: Convert to FOL
            fol_result = self.bridge.semantic_to_fol(symbol)
            
            # Step 4: Check confidence threshold
            if not force_add and fol_result.confidence < self.confidence_threshold:
                logger.warning(
                    f"Statement confidence ({fol_result.confidence:.2f}) below threshold "
                    f"({self.confidence_threshold:.2f})"
                )
                return {
                    "status": "warning",
                    "message": "Statement confidence below threshold",
                    "statement_id": statement_id,
                    "confidence": fol_result.confidence,
                    "threshold": self.confidence_threshold,
                    "fol_formula": fol_result.fol_formula,
                    "components": components.__dict__,
                    "recommendation": "Consider rephrasing or use force_add=True"
                }
            
            # Step 5: Check consistency with existing statements
            consistency_result = None
            if self.enable_consistency_checking and len(self.session_statements) > 0:
                consistency_result = self._check_consistency_with_existing(text, fol_result)
            
            # Step 6: Create statement record
            statement_record = StatementRecord(
                id=statement_id,
                text=text,
                timestamp=datetime.now(),
                logical_components=components,
                fol_formula=fol_result.fol_formula,
                confidence=fol_result.confidence,
                is_consistent=consistency_result.get("consistent", True) if consistency_result else True,
                tags=tags or []
            )
            
            # Step 7: Add to session
            self.session_statements[statement_id] = statement_record
            self.session_symbols.append(symbol)
            self.current_context.append(text)
            
            # Step 8: Update metadata
            self._update_session_metadata()
            
            # Step 9: Prepare response
            response = {
                "status": "success",
                "statement_id": statement_id,
                "text": text,
                "fol_formula": fol_result.fol_formula,
                "confidence": fol_result.confidence,
                "logical_components": {
                    "quantifiers": components.quantifiers,
                    "predicates": components.predicates,
                    "entities": components.entities,
                    "connectives": components.logical_connectives
                },
                "reasoning_steps": fol_result.reasoning_steps,
                "session_summary": {
                    "total_statements": len(self.session_statements),
                    "average_confidence": self.metadata.average_confidence
                }
            }
            
            if consistency_result:
                response["consistency_check"] = consistency_result
            
            logger.info(f"Added statement: '{text[:50]}...' with confidence {fol_result.confidence:.2f}")
            return response
            
        except Exception as e:
            logger.error(f"Failed to add statement '{text}': {e}")
            return {
                "status": "error",
                "message": str(e),
                "statement_id": statement_id,
                "text": text
            }
    
    @beartype
    def remove_statement(self, statement_id: str) -> Dict[str, Any]:
        """
        Remove a statement from the session.
        
        Args:
            statement_id: ID of the statement to remove
            
        Returns:
            Dictionary with removal results
        """
        if statement_id not in self.session_statements:
            return {
                "status": "error",
                "message": f"Statement with ID {statement_id} not found"
            }
        
        try:
            removed_statement = self.session_statements.pop(statement_id)
            
            # Remove from context and symbols
            if removed_statement.text in self.current_context:
                self.current_context.remove(removed_statement.text)
            
            # Note: Removing from session_symbols is complex since we don't have direct mapping
            # For now, we'll just mark it as removed and rebuild symbols when needed
            
            self._update_session_metadata()
            
            return {
                "status": "success",
                "message": f"Statement removed: '{removed_statement.text[:50]}...'",
                "removed_statement": {
                    "id": statement_id,
                    "text": removed_statement.text,
                    "fol_formula": removed_statement.fol_formula
                },
                "session_summary": {
                    "total_statements": len(self.session_statements),
                    "average_confidence": self.metadata.average_confidence
                }
            }
            
        except Exception as e:
            logger.error(f"Failed to remove statement {statement_id}: {e}")
            return {
                "status": "error",
                "message": str(e)
            }
    
    def analyze_logical_structure(self) -> Dict[str, Any]:
        """
        Analyze the logical structure of all statements in the session.
        
        Returns:
            Dictionary with comprehensive structural analysis
        """
        if not self.session_statements:
            return {
                "status": "empty",
                "message": "No statements to analyze"
            }
        
        try:
            analysis = {
                "session_overview": {
                    "total_statements": len(self.session_statements),
                    "domain": self.domain,
                    "session_id": self.session_id
                },
                "logical_elements": {
                    "quantifiers": {},
                    "predicates": {},
                    "entities": {},
                    "connectives": {}
                },
                "complexity_analysis": {
                    "simple_statements": 0,
                    "complex_statements": 0,
                    "conditional_statements": 0,
                    "quantified_statements": 0
                },
                "consistency_analysis": {
                    "consistent_statements": 0,
                    "inconsistent_statements": 0,
                    "unknown_consistency": 0
                },
                "confidence_distribution": {
                    "high_confidence": 0,  # > 0.8
                    "medium_confidence": 0,  # 0.5 - 0.8
                    "low_confidence": 0     # < 0.5
                }
            }
            
            # Analyze each statement
            for statement in self.session_statements.values():
                components = statement.logical_components
                if components:
                    # Count logical elements
                    for quantifier in components.quantifiers:
                        analysis["logical_elements"]["quantifiers"][quantifier] = \
                            analysis["logical_elements"]["quantifiers"].get(quantifier, 0) + 1
                    
                    for predicate in components.predicates:
                        analysis["logical_elements"]["predicates"][predicate] = \
                            analysis["logical_elements"]["predicates"].get(predicate, 0) + 1
                    
                    for entity in components.entities:
                        analysis["logical_elements"]["entities"][entity] = \
                            analysis["logical_elements"]["entities"].get(entity, 0) + 1
                    
                    for connective in components.logical_connectives:
                        analysis["logical_elements"]["connectives"][connective] = \
                            analysis["logical_elements"]["connectives"].get(connective, 0) + 1
                
                # Analyze complexity
                if statement.fol_formula:
                    if any(q in statement.fol_formula for q in ["∀", "∃", "forall", "exists"]):
                        analysis["complexity_analysis"]["quantified_statements"] += 1
                    
                    if any(c in statement.fol_formula for c in ["→", "=>", "implies", "if"]):
                        analysis["complexity_analysis"]["conditional_statements"] += 1
                    
                    if any(c in statement.fol_formula for c in ["∧", "∨", "&", "|", "and", "or"]):
                        analysis["complexity_analysis"]["complex_statements"] += 1
                    else:
                        analysis["complexity_analysis"]["simple_statements"] += 1
                
                # Analyze consistency
                if statement.is_consistent is True:
                    analysis["consistency_analysis"]["consistent_statements"] += 1
                elif statement.is_consistent is False:
                    analysis["consistency_analysis"]["inconsistent_statements"] += 1
                else:
                    analysis["consistency_analysis"]["unknown_consistency"] += 1
                
                # Analyze confidence
                if statement.confidence > 0.8:
                    analysis["confidence_distribution"]["high_confidence"] += 1
                elif statement.confidence > 0.5:
                    analysis["confidence_distribution"]["medium_confidence"] += 1
                else:
                    analysis["confidence_distribution"]["low_confidence"] += 1
            
            # Add insights
            analysis["insights"] = self._generate_insights(analysis)
            
            return {
                "status": "success",
                "analysis": analysis,
                "timestamp": datetime.now().isoformat()
            }
            
        except Exception as e:
            logger.error(f"Failed to analyze logical structure: {e}")
            return {
                "status": "error",
                "message": str(e)
            }
    
    def generate_fol_incrementally(self) -> List[Dict[str, Any]]:
        """
        Generate FOL formulas for all statements with incremental analysis.
        
        Returns:
            List of dictionaries with FOL formulas and metadata
        """
        if not self.session_statements:
            return []
        
        fol_formulas = []
        
        for statement_id, statement in self.session_statements.items():
            formula_data = {
                "statement_id": statement_id,
                "original_text": statement.text,
                "fol_formula": statement.fol_formula,
                "confidence": statement.confidence,
                "timestamp": statement.timestamp.isoformat(),
                "is_consistent": statement.is_consistent,
                "tags": statement.tags
            }
            
            if statement.logical_components:
                formula_data["logical_components"] = {
                    "quantifiers": statement.logical_components.quantifiers,
                    "predicates": statement.logical_components.predicates,
                    "entities": statement.logical_components.entities,
                    "connectives": statement.logical_components.logical_connectives
                }
            
            fol_formulas.append(formula_data)
        
        return fol_formulas
    
    def validate_consistency(self) -> Dict[str, Any]:
        """
        Validate logical consistency across all statements in the session.
        
        Returns:
            Dictionary with consistency validation results
        """
        if len(self.session_statements) < 2:
            return {
                "status": "insufficient_data",
                "message": "Need at least 2 statements to check consistency"
            }
        
        try:
            consistency_report = {
                "overall_consistent": True,
                "total_statements": len(self.session_statements),
                "consistent_pairs": 0,
                "inconsistent_pairs": 0,
                "conflicts": [],
                "warnings": []
            }
            
            statements = list(self.session_statements.values())
            
            # Check pairwise consistency
            for i in range(len(statements)):
                for j in range(i + 1, len(statements)):
                    stmt1, stmt2 = statements[i], statements[j]
                    
                    conflict = self._check_logical_conflict(stmt1, stmt2)
                    
                    if conflict["has_conflict"]:
                        consistency_report["inconsistent_pairs"] += 1
                        consistency_report["overall_consistent"] = False
                        consistency_report["conflicts"].append({
                            "statement1": {
                                "id": stmt1.id,
                                "text": stmt1.text,
                                "fol": stmt1.fol_formula
                            },
                            "statement2": {
                                "id": stmt2.id,
                                "text": stmt2.text,
                                "fol": stmt2.fol_formula
                            },
                            "conflict_type": conflict["conflict_type"],
                            "description": conflict["description"]
                        })
                    else:
                        consistency_report["consistent_pairs"] += 1
            
            # Add recommendations
            if not consistency_report["overall_consistent"]:
                consistency_report["recommendations"] = self._generate_consistency_recommendations(
                    consistency_report["conflicts"]
                )
            
            return {
                "status": "success",
                "consistency_report": consistency_report,
                "timestamp": datetime.now().isoformat()
            }
            
        except Exception as e:
            logger.error(f"Failed to validate consistency: {e}")
            return {
                "status": "error",
                "message": str(e)
            }
    


# Backward compatibility: Import utilities for existing code
from .interactive_fol_utils import create_interactive_session, demo_interactive_session

# Export for external use
__all__ = [
    'InteractiveFOLConstructor',
    'create_interactive_session',
    'demo_interactive_session',
    'StatementRecord',
    'SessionMetadata',
    'SYMBOLIC_AI_AVAILABLE'
]


if __name__ == "__main__":
    demo_interactive_session()
