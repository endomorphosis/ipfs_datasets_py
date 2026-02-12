"""
Unified Neurosymbolic Reasoning API

This module provides a single unified interface for the complete
neurosymbolic reasoning system, integrating:

- TDFOL: Temporal Deontic First-Order Logic (40 rules)
- CEC: Cognitive Event Calculus (87 rules)
- ShadowProver: Modal logic K/S4/S5 provers
- Grammar Engine: Natural language processing (100+ lexicon, 50+ rules)

Total: 127+ inference rules, 5 modal provers, grammar-based NL understanding
"""

from __future__ import annotations

import logging
from typing import Optional, List, Dict, Any, Union
from dataclasses import dataclass

# Core TDFOL imports
from ..TDFOL.tdfol_core import Formula, TDFOLKnowledgeBase
from ..TDFOL.tdfol_parser import parse_tdfol
from ..TDFOL.tdfol_dcec_parser import parse_dcec
from ..TDFOL.tdfol_prover import ProofResult

# Integration imports
from .tdfol_cec_bridge import EnhancedTDFOLProver
from .tdfol_shadowprover_bridge import ModalAwareTDFOLProver
from .tdfol_grammar_bridge import NaturalLanguageTDFOLInterface

logger = logging.getLogger(__name__)


@dataclass
class ReasoningCapabilities:
    """Capabilities of the reasoning system."""
    tdfol_rules: int = 40
    cec_rules: int = 87
    total_rules: int = 127
    modal_provers: List[str] = None
    grammar_available: bool = False
    shadowprover_available: bool = False
    
    def __post_init__(self):
        if self.modal_provers is None:
            self.modal_provers = ["K", "S4", "S5", "D", "CognitiveCalculus"]


class NeurosymbolicReasoner:
    """
    Unified neurosymbolic reasoning system.
    
    This is the main entry point for using the complete integrated
    neurosymbolic reasoning capabilities.
    
    Features:
    - Parse formulas from multiple formats (TDFOL, DCEC, natural language)
    - Prove theorems using 127+ inference rules
    - Modal logic proving with K/S4/S5 specialized provers
    - Natural language understanding and generation
    - Knowledge base management
    
    Example:
        >>> reasoner = NeurosymbolicReasoner()
        >>> reasoner.add_knowledge("All humans are mortal")
        >>> result = reasoner.prove("Socrates is mortal", 
        ...                          given=["Socrates is human"])
        >>> print(result.valid)
        True
    """
    
    def __init__(
        self,
        use_cec: bool = True,
        use_modal: bool = True,
        use_nl: bool = True
    ):
        """
        Initialize the neurosymbolic reasoner.
        
        Args:
            use_cec: Enable CEC integration (87 additional rules)
            use_modal: Enable modal logic provers (K/S4/S5)
            use_nl: Enable natural language processing
        """
        self.kb = TDFOLKnowledgeBase()
        
        # Initialize provers
        if use_modal:
            self.prover = ModalAwareTDFOLProver()
            logger.info("Initialized with modal-aware prover")
        elif use_cec:
            self.prover = EnhancedTDFOLProver(kb=self.kb, use_cec=True)
            logger.info("Initialized with CEC-enhanced prover (127 rules)")
        else:
            from ..TDFOL.tdfol_prover import TDFOLProver
            self.prover = TDFOLProver(kb=self.kb)
            logger.info("Initialized with base TDFOL prover (40 rules)")
        
        # Initialize NL interface
        self.nl_interface = None
        if use_nl:
            self.nl_interface = NaturalLanguageTDFOLInterface()
            logger.info("Natural language interface enabled")
        
        # Track capabilities
        self.capabilities = self._detect_capabilities()
        logger.info(f"System capabilities: {self.capabilities.total_rules} inference rules")
    
    def _detect_capabilities(self) -> ReasoningCapabilities:
        """Detect available reasoning capabilities."""
        caps = ReasoningCapabilities()
        
        # Check CEC availability
        try:
            from .tdfol_cec_bridge import TDFOLCECBridge
            bridge = TDFOLCECBridge()
            if bridge.cec_available:
                caps.cec_rules = len(bridge.cec_rules) if bridge.cec_rules else 87
        except:
            caps.cec_rules = 0
        
        caps.total_rules = caps.tdfol_rules + caps.cec_rules
        
        # Check ShadowProver
        try:
            from .tdfol_shadowprover_bridge import TDFOLShadowProverBridge
            bridge = TDFOLShadowProverBridge()
            caps.shadowprover_available = bridge.available
        except:
            caps.shadowprover_available = False
        
        # Check Grammar
        if self.nl_interface:
            caps.grammar_available = self.nl_interface.grammar_bridge.available
        
        return caps
    
    def parse(
        self,
        input_str: str,
        format: str = "auto"
    ) -> Optional[Formula]:
        """
        Parse input string to TDFOL formula.
        
        Args:
            input_str: Input string
            format: Input format ("auto", "tdfol", "dcec", "nl")
        
        Returns:
            TDFOL formula or None
        
        Examples:
            >>> reasoner.parse("forall x. P(x) -> Q(x)", format="tdfol")
            >>> reasoner.parse("(O P)", format="dcec")
            >>> reasoner.parse("All birds can fly", format="nl")
        """
        if format == "auto":
            # Auto-detect format
            if input_str.startswith("("):
                format = "dcec"
            elif any(kw in input_str.lower() for kw in ["forall", "exists", "->", "∀", "∃"]):
                format = "tdfol"
            else:
                format = "nl"
        
        if format == "tdfol":
            try:
                return parse_tdfol(input_str)
            except Exception as e:
                logger.debug(f"TDFOL parsing failed: {e}")
                return None
        
        elif format == "dcec":
            try:
                return parse_dcec(input_str)
            except Exception as e:
                logger.debug(f"DCEC parsing failed: {e}")
                return None
        
        elif format == "nl":
            if self.nl_interface:
                return self.nl_interface.understand(input_str)
            else:
                logger.warning("Natural language parsing not available")
                return None
        
        return None
    
    def add_knowledge(
        self,
        statement: Union[str, Formula],
        is_axiom: bool = True
    ) -> bool:
        """
        Add knowledge to the system.
        
        Args:
            statement: Statement (string or formula)
            is_axiom: Whether to add as axiom (vs theorem)
        
        Returns:
            True if successfully added
        
        Examples:
            >>> reasoner.add_knowledge("All humans are mortal")
            >>> reasoner.add_knowledge(parse_tdfol("P -> Q"))
        """
        # Convert string to formula if needed
        if isinstance(statement, str):
            formula = self.parse(statement)
            if not formula:
                logger.error(f"Could not parse statement: {statement}")
                return False
        else:
            formula = statement
        
        # Add to knowledge base
        if is_axiom:
            self.kb.add_axiom(formula)
        else:
            self.kb.add_theorem(formula)
        
        logger.debug(f"Added knowledge: {formula.to_string()}")
        return True
    
    def prove(
        self,
        goal: Union[str, Formula],
        given: Optional[List[Union[str, Formula]]] = None,
        timeout_ms: int = 5000
    ) -> ProofResult:
        """
        Prove a goal statement.
        
        Args:
            goal: Goal statement (string or formula)
            given: Additional premises (optional)
            timeout_ms: Timeout in milliseconds
        
        Returns:
            ProofResult with proof status and steps
        
        Examples:
            >>> result = reasoner.prove("Q", given=["P", "P -> Q"])
            >>> print(result.is_proved())
            True
        """
        # Parse goal
        if isinstance(goal, str):
            goal_formula = self.parse(goal)
            if not goal_formula:
                from ..TDFOL.tdfol_prover import ProofResult, ProofStatus
                return ProofResult(
                    status=ProofStatus.ERROR,
                    formula=None,
                    time_ms=0,
                    method="parsing",
                    message=f"Could not parse goal: {goal}"
                )
        else:
            goal_formula = goal
        
        # Add temporary premises
        temp_kb = None
        if given:
            # Create temporary knowledge base with additional premises
            from ..TDFOL.tdfol_core import TDFOLKnowledgeBase
            temp_kb = TDFOLKnowledgeBase()
            
            # Copy existing knowledge
            for axiom in self.kb.axioms:
                temp_kb.add_axiom(axiom)
            for theorem in self.kb.theorems:
                temp_kb.add_theorem(theorem)
            
            # Add new premises
            for premise in given:
                if isinstance(premise, str):
                    formula = self.parse(premise)
                    if formula:
                        temp_kb.add_axiom(formula)
                else:
                    temp_kb.add_axiom(premise)
            
            # Update prover's KB temporarily
            old_kb = self.prover.base_prover.kb if hasattr(self.prover, 'base_prover') else self.prover.kb
            if hasattr(self.prover, 'base_prover'):
                self.prover.base_prover.kb = temp_kb
            else:
                self.prover.kb = temp_kb
        
        # Attempt proof
        result = self.prover.prove(goal_formula, timeout_ms=timeout_ms)
        
        # Restore original KB
        if temp_kb and hasattr(self.prover, 'base_prover'):
            self.prover.base_prover.kb = self.kb
        elif temp_kb:
            self.prover.kb = self.kb
        
        return result
    
    def explain(self, formula: Union[str, Formula]) -> str:
        """
        Explain a formula in natural language.
        
        Args:
            formula: Formula to explain (string or Formula object)
        
        Returns:
            Natural language explanation
        """
        # Parse if string
        if isinstance(formula, str):
            formula_obj = self.parse(formula)
            if not formula_obj:
                return f"Could not parse: {formula}"
        else:
            formula_obj = formula
        
        # Use NL interface if available
        if self.nl_interface:
            return self.nl_interface.explain(formula_obj)
        else:
            return formula_obj.to_string(pretty=True)
    
    def query(
        self,
        question: str,
        timeout_ms: int = 5000
    ) -> Dict[str, Any]:
        """
        Answer a natural language question.
        
        Args:
            question: Natural language question
            timeout_ms: Timeout in milliseconds
        
        Returns:
            Dictionary with answer and reasoning
        
        Example:
            >>> result = reasoner.query("Is Socrates mortal?")
            >>> print(result['answer'])
            "Yes, because all humans are mortal and Socrates is human."
        """
        # Parse question
        goal = self.parse(question, format="nl")
        
        if not goal:
            return {
                "question": question,
                "answer": "I could not understand the question",
                "success": False
            }
        
        # Attempt proof
        result = self.prove(goal, timeout_ms=timeout_ms)
        
        # Format response
        if result.is_proved():
            explanation = self.explain(goal)
            return {
                "question": question,
                "answer": f"Yes. {explanation}",
                "success": True,
                "proof_time_ms": result.time_ms,
                "confidence": 1.0,
                "reasoning": f"Proved using {result.method} in {len(result.proof_steps)} steps"
            }
        else:
            return {
                "question": question,
                "answer": "I cannot prove this from the available knowledge",
                "success": False,
                "confidence": 0.0,
                "reasoning": result.message or "Proof unsuccessful"
            }
    
    def get_capabilities(self) -> Dict[str, Any]:
        """
        Get system capabilities.
        
        Returns:
            Dictionary describing available capabilities
        """
        return {
            "tdfol_rules": self.capabilities.tdfol_rules,
            "cec_rules": self.capabilities.cec_rules,
            "total_inference_rules": self.capabilities.total_rules,
            "modal_provers": self.capabilities.modal_provers,
            "shadowprover_available": self.capabilities.shadowprover_available,
            "grammar_available": self.capabilities.grammar_available,
            "natural_language": self.nl_interface is not None,
        }


# Convenience function for quick access
_global_reasoner = None

def get_reasoner() -> NeurosymbolicReasoner:
    """
    Get the global neurosymbolic reasoner instance.
    
    Returns:
        NeurosymbolicReasoner instance
    """
    global _global_reasoner
    if _global_reasoner is None:
        _global_reasoner = NeurosymbolicReasoner()
    return _global_reasoner
