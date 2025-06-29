"""
Interactive FOL Constructor Module

This module provides an interactive interface for constructing First-Order Logic
formulas step by step, with real-time analysis and validation using SymbolicAI.
"""

import logging
import json
import uuid
from datetime import datetime
from typing import Dict, List, Optional, Any, Tuple, Union
from dataclasses import dataclass, field
from beartype import beartype

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
from .symbolic_fol_bridge import SymbolicFOLBridge, LogicalComponents, FOLConversionResult
from .symbolic_logic_primitives import create_logic_symbol, LogicPrimitives


@dataclass
class StatementRecord:
    """Record of a single statement in the interactive session."""
    id: str
    text: str
    timestamp: datetime
    logical_components: Optional[LogicalComponents] = None
    fol_formula: Optional[str] = None
    confidence: float = 0.0
    is_consistent: Optional[bool] = None
    dependencies: List[str] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)


@dataclass
class SessionMetadata:
    """Metadata for an interactive FOL construction session."""
    session_id: str
    created_at: datetime
    last_modified: datetime
    total_statements: int
    consistent_statements: int
    inconsistent_statements: int
    average_confidence: float
    domain: str = "general"
    description: str = ""
    tags: List[str] = field(default_factory=list)


class InteractiveFOLConstructor:
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
    
    def export_session(self, format: str = "json") -> Dict[str, Any]:
        """
        Export the current session data.
        
        Args:
            format: Export format ("json", "fol", "prolog", "tptp")
            
        Returns:
            Dictionary with exported session data
        """
        try:
            export_data = {
                "session_metadata": {
                    "session_id": self.session_id,
                    "domain": self.domain,
                    "created_at": self.metadata.created_at.isoformat(),
                    "exported_at": datetime.now().isoformat(),
                    "total_statements": len(self.session_statements),
                    "average_confidence": self.metadata.average_confidence
                },
                "statements": [],
                "fol_formulas": [],
                "logical_analysis": self.analyze_logical_structure().get("analysis", {}),
                "consistency_report": self.validate_consistency().get("consistency_report", {})
            }
            
            # Export statements and formulas
            for statement in self.session_statements.values():
                statement_data = {
                    "id": statement.id,
                    "text": statement.text,
                    "timestamp": statement.timestamp.isoformat(),
                    "confidence": statement.confidence,
                    "is_consistent": statement.is_consistent,
                    "tags": statement.tags
                }
                
                if statement.logical_components:
                    statement_data["logical_components"] = {
                        "quantifiers": statement.logical_components.quantifiers,
                        "predicates": statement.logical_components.predicates,
                        "entities": statement.logical_components.entities,
                        "connectives": statement.logical_components.logical_connectives
                    }
                
                export_data["statements"].append(statement_data)
                
                # Add FOL formula in requested format
                if statement.fol_formula:
                    fol_data = {
                        "statement_id": statement.id,
                        "original_text": statement.text,
                        "fol_formula": statement.fol_formula,
                        "format": format
                    }
                    
                    # Convert to different formats if needed
                    if format != "symbolic":
                        converted_formula = self._convert_fol_format(statement.fol_formula, format)
                        fol_data["fol_formula"] = converted_formula
                    
                    export_data["fol_formulas"].append(fol_data)
            
            return {
                "status": "success",
                "export_data": export_data,
                "format": format
            }
            
        except Exception as e:
            logger.error(f"Failed to export session: {e}")
            return {
                "status": "error",
                "message": str(e)
            }
    
    def get_session_statistics(self) -> Dict[str, Any]:
        """Get comprehensive session statistics."""
        return {
            "session_id": self.session_id,
            "metadata": {
                "domain": self.domain,
                "created_at": self.metadata.created_at.isoformat(),
                "last_modified": self.metadata.last_modified.isoformat(),
                "total_statements": len(self.session_statements),
                "average_confidence": self.metadata.average_confidence
            },
            "logical_elements": self._count_logical_elements(),
            "bridge_statistics": self.bridge.get_statistics(),
            "session_health": self._assess_session_health()
        }
    
    # Private helper methods
    
    def _update_session_metadata(self):
        """Update session metadata after changes."""
        self.metadata.last_modified = datetime.now()
        self.metadata.total_statements = len(self.session_statements)
        
        if self.session_statements:
            total_confidence = sum(stmt.confidence for stmt in self.session_statements.values())
            self.metadata.average_confidence = total_confidence / len(self.session_statements)
            
            self.metadata.consistent_statements = sum(
                1 for stmt in self.session_statements.values() 
                if stmt.is_consistent is True
            )
            self.metadata.inconsistent_statements = sum(
                1 for stmt in self.session_statements.values() 
                if stmt.is_consistent is False
            )
    
    def _check_consistency_with_existing(self, new_text: str, fol_result: FOLConversionResult) -> Dict[str, Any]:
        """Check consistency of new statement with existing ones."""
        # Simple consistency checking - can be enhanced with theorem proving
        consistency_result = {
            "consistent": True,
            "conflicts": [],
            "warnings": []
        }
        
        # Basic contradiction detection
        new_text_lower = new_text.lower()
        
        for existing_statement in self.session_statements.values():
            existing_text_lower = existing_statement.text.lower()
            
            # Check for obvious contradictions
            if ("all" in new_text_lower and "no" in existing_text_lower) or \
               ("no" in new_text_lower and "all" in existing_text_lower):
                # Potential contradiction between universal statements
                consistency_result["consistent"] = False
                consistency_result["conflicts"].append({
                    "type": "universal_contradiction",
                    "existing_statement": existing_statement.text,
                    "new_statement": new_text
                })
        
        return consistency_result
    
    def _check_logical_conflict(self, stmt1: StatementRecord, stmt2: StatementRecord) -> Dict[str, Any]:
        """Check for logical conflicts between two statements."""
        # Simplified conflict detection
        conflict_result = {
            "has_conflict": False,
            "conflict_type": None,
            "description": ""
        }
        
        if not stmt1.fol_formula or not stmt2.fol_formula:
            return conflict_result
        
        # Basic contradiction patterns
        text1_lower = stmt1.text.lower()
        text2_lower = stmt2.text.lower()
        
        # Pattern: "All X are Y" vs "No X are Y"
        if ("all" in text1_lower and "no" in text2_lower) or \
           ("no" in text1_lower and "all" in text2_lower):
            conflict_result["has_conflict"] = True
            conflict_result["conflict_type"] = "universal_contradiction"
            conflict_result["description"] = "Universal statement contradicts negative universal"
        
        return conflict_result
    
    def _generate_consistency_recommendations(self, conflicts: List[Dict]) -> List[str]:
        """Generate recommendations for resolving consistency conflicts."""
        recommendations = []
        
        for conflict in conflicts:
            if conflict["conflict_type"] == "universal_contradiction":
                recommendations.append(
                    f"Review statements '{conflict['statement1']['text']}' and "
                    f"'{conflict['statement2']['text']}' for logical contradiction"
                )
        
        if len(conflicts) > 2:
            recommendations.append("Consider reviewing the domain assumptions and definitions")
        
        return recommendations
    
    def _generate_insights(self, analysis: Dict) -> List[str]:
        """Generate insights from logical structure analysis."""
        insights = []
        
        total_statements = analysis["session_overview"]["total_statements"]
        
        # Complexity insights
        complex_ratio = analysis["complexity_analysis"]["complex_statements"] / total_statements
        if complex_ratio > 0.7:
            insights.append("Session contains many complex logical statements")
        elif complex_ratio < 0.3:
            insights.append("Session primarily contains simple logical statements")
        
        # Consistency insights
        if analysis["consistency_analysis"]["inconsistent_statements"] > 0:
            insights.append("Some statements may be logically inconsistent")
        
        # Confidence insights
        low_confidence = analysis["confidence_distribution"]["low_confidence"]
        if low_confidence > total_statements * 0.3:
            insights.append("Many statements have low confidence - consider rephrasing")
        
        # Quantifier insights
        quantified_ratio = analysis["complexity_analysis"]["quantified_statements"] / total_statements
        if quantified_ratio > 0.5:
            insights.append("Session heavily uses quantified statements")
        
        return insights
    
    def _convert_fol_format(self, formula: str, target_format: str) -> str:
        """Convert FOL formula to different format."""
        if target_format == "prolog":
            # Simple conversion to Prolog syntax
            converted = formula.replace("∀", "forall")
            converted = converted.replace("∃", "exists")
            converted = converted.replace("→", ":-")
            converted = converted.replace("∧", ",")
            converted = converted.replace("∨", ";")
            return converted
        
        elif target_format == "tptp":
            # Simple conversion to TPTP format
            converted = formula.replace("∀", "!")
            converted = converted.replace("∃", "?")
            converted = converted.replace("→", "=>")
            converted = converted.replace("∧", "&")
            converted = converted.replace("∨", "|")
            return f"fof(statement, axiom, {converted})."
        
        return formula  # Return original for unknown formats
    
    def _count_logical_elements(self) -> Dict[str, int]:
        """Count logical elements across all statements."""
        counts = {
            "total_quantifiers": 0,
            "total_predicates": 0,
            "total_entities": 0,
            "total_connectives": 0
        }
        
        for statement in self.session_statements.values():
            if statement.logical_components:
                counts["total_quantifiers"] += len(statement.logical_components.quantifiers)
                counts["total_predicates"] += len(statement.logical_components.predicates)
                counts["total_entities"] += len(statement.logical_components.entities)
                counts["total_connectives"] += len(statement.logical_components.logical_connectives)
        
        return counts
    
    def _assess_session_health(self) -> Dict[str, Any]:
        """Assess the overall health of the session."""
        if not self.session_statements:
            return {"status": "empty", "score": 0}
        
        total_statements = len(self.session_statements)
        
        # Calculate health metrics
        avg_confidence = self.metadata.average_confidence
        consistency_ratio = self.metadata.consistent_statements / total_statements
        
        # Simple health score (0-100)
        health_score = (avg_confidence * 50) + (consistency_ratio * 50)
        
        health_status = "excellent" if health_score > 80 else \
                       "good" if health_score > 60 else \
                       "fair" if health_score > 40 else "poor"
        
        return {
            "status": health_status,
            "score": round(health_score, 2),
            "metrics": {
                "average_confidence": avg_confidence,
                "consistency_ratio": consistency_ratio,
                "total_statements": total_statements
            }
        }


def create_interactive_session(domain: str = "general", **kwargs) -> InteractiveFOLConstructor:
    """
    Factory function to create an interactive FOL constructor session.
    
    Args:
        domain: Domain of knowledge
        **kwargs: Additional parameters for InteractiveFOLConstructor
        
    Returns:
        InteractiveFOLConstructor instance
    """
    return InteractiveFOLConstructor(domain=domain, **kwargs)


# Example usage and testing
def demo_interactive_session():
    """Demonstrate the interactive FOL constructor."""
    print("Interactive FOL Constructor Demo")
    print("=" * 40)
    
    # Create session
    constructor = create_interactive_session(domain="animals")
    
    # Add some statements
    statements = [
        "All cats are animals",
        "Some cats are black",
        "Fluffy is a cat",
        "All animals need food"
    ]
    
    for statement in statements:
        result = constructor.add_statement(statement)
        print(f"Added: {statement}")
        print(f"FOL: {result.get('fol_formula', 'N/A')}")
        print(f"Confidence: {result.get('confidence', 0.0):.2f}")
        print("-" * 30)
    
    # Analyze structure
    analysis = constructor.analyze_logical_structure()
    print("\nLogical Structure Analysis:")
    if analysis["status"] == "success":
        logical_elements = analysis["analysis"]["logical_elements"]
        print(f"Quantifiers: {logical_elements['quantifiers']}")
        print(f"Predicates: {logical_elements['predicates']}")
        print(f"Entities: {logical_elements['entities']}")
    
    # Check consistency
    consistency = constructor.validate_consistency()
    print(f"\nConsistency: {consistency.get('consistency_report', {}).get('overall_consistent', 'Unknown')}")
    
    # Get statistics
    stats = constructor.get_session_statistics()
    print(f"\nSession Statistics:")
    print(f"Total statements: {stats['metadata']['total_statements']}")
    print(f"Average confidence: {stats['metadata']['average_confidence']:.2f}")
    
    return constructor


if __name__ == "__main__":
    demo_interactive_session()
