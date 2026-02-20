"""
TDFOL-Grammar Integration

This module integrates TDFOL with CEC's grammar engine for natural language processing.

Features:
- Natural language → TDFOL conversion using grammar-based parsing
- Support for 100+ lexicon entries and 50+ compositional rules
- Bidirectional NL ↔ TDFOL conversion
"""

from __future__ import annotations

import logging
from typing import Optional, List, Dict, Any, Tuple

from ...TDFOL.tdfol_core import Formula
from ...TDFOL.tdfol_dcec_parser import parse_dcec
from ...TDFOL.tdfol_prover import ProofResult, ProofStatus
from .base_prover_bridge import (
    BaseProverBridge,
    BridgeMetadata,
    BridgeCapability
)

logger = logging.getLogger(__name__)

# Try to import grammar components
GRAMMAR_AVAILABLE = False
try:
    from ...CEC.native import grammar_engine, dcec_english_grammar, nl_converter
    GRAMMAR_AVAILABLE = True
    logger.info("Grammar engine modules loaded successfully")
except ImportError as e:
    logger.warning(f"Grammar engine modules not available: {e}")


class TDFOLGrammarBridge(BaseProverBridge):
    """
    Bridge between TDFOL and CEC's grammar engine.
    
    Enables natural language → TDFOL formula conversion using
    comprehensive grammar-based parsing.
    """
    
    def __init__(self):
        """Initialize the TDFOL-Grammar bridge."""
        super().__init__()
        
        if not self.available:
            logger.warning("Grammar integration disabled")
            return
        
        # Initialize grammar components
        self.grammar_engine = None
        self.dcec_grammar = None
        self.nl_converter = None
        
        try:
            # Create grammar instances
            self.grammar_engine = grammar_engine.GrammarEngine()
            self.dcec_grammar = dcec_english_grammar.DCECEnglishGrammar()
            # NL converter is a module, use its functions directly
            
            logger.info("Initialized grammar engine with 100+ lexicon entries")
        except Exception as e:
            logger.warning(f"Failed to initialize grammar engine: {e}")
            self.available = False
    
    def _init_metadata(self) -> BridgeMetadata:
        """Initialize bridge metadata."""
        return BridgeMetadata(
            name="TDFOL-Grammar Bridge",
            version="1.0.0",
            target_system="Grammar",
            capabilities=[
                BridgeCapability.BIDIRECTIONAL_CONVERSION
            ],
            requires_external_prover=False,
            description="Integrates TDFOL with grammar-based NL parsing (100+ lexicon entries)"
        )
    
    def _check_availability(self) -> bool:
        """Check if grammar modules are available."""
        return GRAMMAR_AVAILABLE
    
    def to_target_format(self, formula: Formula) -> str:
        """
        Convert TDFOL formula to natural language (grammar format).
        
        Args:
            formula: TDFOL formula
            
        Returns:
            Natural language representation
            
        Raises:
            ValueError: If formula cannot be converted
        """
        if not self.is_available():
            raise ValueError("Grammar bridge not available")
        
        return self.formula_to_natural_language(formula)
    
    def from_target_format(self, target_result: Any) -> ProofResult:
        """
        Convert grammar result to TDFOL ProofResult.
        
        Note: Grammar bridge is primarily for parsing, not proving.
        
        Args:
            target_result: Result from grammar parsing
            
        Returns:
            ProofResult with standardized format
        """
        # Grammar bridge doesn't do proving, so this is a placeholder
        return ProofResult(
            status=ProofStatus.UNKNOWN,
            formula=None,
            time_ms=0,
            method="grammar",
            message="Grammar bridge is for parsing, not proving"
        )
    
    def prove(
        self,
        formula: Formula,
        timeout: Optional[int] = None,
        **kwargs
    ) -> ProofResult:
        """
        Grammar bridge doesn't support proving.
        
        Args:
            formula: TDFOL formula
            timeout: Ignored
            **kwargs: Ignored
            
        Returns:
            ProofResult indicating proving not supported
        """
        return ProofResult(
            status=ProofStatus.UNKNOWN,
            formula=formula,
            time_ms=0,
            method="grammar",
            message="Grammar bridge is for NL parsing, not theorem proving"
        )
    
    def parse_natural_language(
        self,
        text: str,
        use_fallback: bool = True
    ) -> Optional[Formula]:
        """
        Parse natural language text to TDFOL formula using grammar.
        
        Args:
            text: Natural language text
            use_fallback: Fall back to pattern matching if grammar fails
        
        Returns:
            TDFOL formula or None if parsing fails
        
        Examples:
            >>> bridge = TDFOLGrammarBridge()
            >>> f = bridge.parse_natural_language("All humans are mortal")
            >>> print(f.to_string())
            ∀x.(Human(x) → Mortal(x))
            
            >>> f = bridge.parse_natural_language("It is obligatory to report")
            >>> print(f.to_string())
            O(Report)
        """
        if not self.available:
            logger.warning("Grammar not available, using DCEC parser fallback")
            return self._fallback_parse(text)
        
        try:
            # Try grammar-based parsing first
            dcec_str = self.dcec_grammar.parse_to_dcec(text)
            
            if dcec_str:
                logger.debug(f"Grammar parsed '{text}' to DCEC: {dcec_str}")
                
                # Convert DCEC to TDFOL
                formula = parse_dcec(dcec_str)
                return formula
            else:
                logger.debug(f"Grammar parsing returned None for '{text}'")
                
                if use_fallback:
                    return self._fallback_parse(text)
                return None
                
        except Exception as e:
            logger.debug(f"Grammar parsing failed for '{text}': {e}")
            
            if use_fallback:
                return self._fallback_parse(text)
            return None
    
    def _fallback_parse(self, text: str) -> Optional[Formula]:
        """
        Fallback parsing using pattern matching.
        
        Args:
            text: Natural language text
        
        Returns:
            TDFOL formula or None
        """
        if not self.available:
            return None
        
        try:
            # Use NL converter's pattern matching
            dcec_str = nl_converter.convert_to_dcec(text)
            
            if dcec_str:
                logger.debug(f"Pattern matching converted '{text}' to: {dcec_str}")
                formula = parse_dcec(dcec_str)
                return formula
        except Exception as e:
            logger.debug(f"Fallback parsing failed: {e}")
        
        # Try CEC DCEC parser for formal logical syntax (handles P -> Q, etc.)
        # Only use if TDFOL parser didn't work; wrap in try/except to convert if needed
        try:
            from ...CEC.native import parse_dcec_string as _cec_parse
            from ...TDFOL.tdfol_core import Formula as _TDFOLFormula
            cec_formula = _cec_parse(text)
            if cec_formula is not None and isinstance(cec_formula, _TDFOLFormula):
                logger.debug(f"CEC parser (TDFOL-compat) succeeded for '{text}'")
                return cec_formula
        except Exception as e:
            logger.debug(f"CEC parser fallback failed: {e}")
        
        # Last resort: try to parse directly as TDFOL formula syntax
        try:
            from ...TDFOL.tdfol_parser import parse_tdfol_safe
            formula = parse_tdfol_safe(text)
            if formula is not None:
                logger.debug(f"TDFOL parser fallback succeeded for '{text}'")
                return formula
        except Exception as e:
            logger.debug(f"TDFOL parser fallback failed: {e}")
        
        # Final fallback: build simple TDFOL formula from text structure
        try:
            from ...TDFOL.tdfol_core import Predicate, Implication, Conjunction, Negation
            stripped = text.strip()
            
            # Handle implication "A -> B" or "A => B"
            for sep in [' -> ', ' => ', ' --> ']:
                if sep in stripped:
                    parts = stripped.split(sep, 1)
                    left = self._fallback_parse(parts[0].strip())
                    right = self._fallback_parse(parts[1].strip())
                    if left is not None and right is not None:
                        return Implication(left, right)
                    break
            
            # Handle simple atom
            if stripped and stripped.replace("_", "").replace("-", "").isalnum():
                pred = Predicate(stripped, ())
                logger.debug(f"Created atom '{stripped}' as fallback for '{text}'")
                return pred
        except Exception as e:
            logger.debug(f"Atom creation fallback failed: {e}")
        
        return None
    
    def formula_to_natural_language(
        self,
        formula: Formula,
        style: str = "formal"
    ) -> str:
        """
        Convert TDFOL formula to natural language.
        
        Args:
            formula: TDFOL formula
            style: Output style ("formal", "casual", "technical")
        
        Returns:
            Natural language text
        
        Examples:
            >>> f = parse_tdfol("forall x. Human(x) -> Mortal(x)")
            >>> bridge.formula_to_natural_language(f)
            "All humans are mortal"
        """
        if not self.available:
            # Fallback to pretty string representation
            return formula.to_string(pretty=True)
        
        try:
            # Convert TDFOL to DCEC string
            from ...TDFOL.tdfol_converter import tdfol_to_dcec
            dcec_str = tdfol_to_dcec(formula)
            
            # Use grammar engine for DCEC → NL
            # This is a placeholder - actual implementation needed
            nl_text = self._dcec_to_natural_language(dcec_str, style)
            
            return nl_text
            
        except Exception as e:
            logger.debug(f"Formula to NL conversion failed: {e}")
            return formula.to_string(pretty=True)
    
    def _dcec_to_natural_language(self, dcec_str: str, style: str) -> str:
        """
        Convert DCEC string to natural language using grammar engine.
        
        This method leverages the grammar engine's generation capabilities
        for high-quality natural language output.
        
        Args:
            dcec_str: DCEC formula as string
            style: Style of natural language (formal, casual, technical)
            
        Returns:
            Natural language text
        """
        # Try grammar-based generation if available
        if self.dcec_grammar and GRAMMAR_AVAILABLE:
            try:
                # Parse DCEC string to Formula object
                dcec_formula = parse_dcec(dcec_str)
                
                if dcec_formula:
                    # Use grammar engine to generate natural English
                    natural_text = self.dcec_grammar.formula_to_english(dcec_formula)
                    
                    # Reject dict-like fallback strings from grammar (e.g. "{'type': 'unknown', ...}")
                    if isinstance(natural_text, str) and natural_text.startswith("{"):
                        logger.debug("Grammar returned dict-like string, using template fallback")
                    else:
                        # Apply style modifications
                        if style == "casual":
                            natural_text = self._apply_casual_style(natural_text)
                        elif style == "technical":
                            pass
                        
                        logger.debug(f"Grammar-based generation successful: {natural_text}")
                        return natural_text
                else:
                    logger.debug("DCEC parsing returned None, using template fallback")
            
            except Exception as e:
                logger.warning(f"Grammar generation failed: {e}, falling back to templates")
        
        # Template-based fallback (original implementation)
        templates = {
            "formal": {
                "O": "It is obligatory that",
                "P": "It is permitted that",
                "F": "It is forbidden that",
                "always": "always",
                "eventually": "eventually",
                "forall": "For all",
                "exists": "There exists",
            },
            "casual": {
                "O": "must",
                "P": "may",
                "F": "must not",
                "always": "always",
                "eventually": "sometime",
                "forall": "all",
                "exists": "some",
            },
        }
        
        template_set = templates.get(style, templates["formal"])
        
        # Simple template application
        # Strategy: G→always (always temporal), X→next (always temporal)
        # F: temporal only when wrapping another modal op (G/F/X/O/P), else deontic (forbidden)
        result = dcec_str
        import re as _re
        
        # G and X are always temporal
        result = _re.sub(r'\(G ', '(always ', result)
        result = _re.sub(r'\(X ', '(next ', result)
        
        # F: temporal when wrapping deontic/modal sub-ops, else deontic
        # Match (F (O ...), (F (P ...), (F (G ...), (F (F ...) — these are temporal F wrapping modal
        deontic_ops = '|'.join(['O', 'P', 'F', 'G', 'X', 'always', 'next', 'eventually'])
        result = _re.sub(r'\(F \((' + deontic_ops + r')\b', r'(eventually (\1', result)
        # (G (P x)) after G replacement: (always (P x)) — now apply deontic for P
        
        # Apply deontic templates for O/P/F (if not already converted)
        for key, value in template_set.items():
            if key in ('O', 'P', 'F'):
                result = result.replace(f"({key} ", f"{value} ")
        
        # Apply remaining template keywords (always, eventually etc.)
        for key, value in template_set.items():
            if key not in ('O', 'P', 'F'):
                result = result.replace(f"({key} ", f"({value} ")
        
        logger.debug(f"Template-based generation: {result}")
        return result
    
    def _apply_casual_style(self, formal_text: str) -> str:
        """
        Post-process formal English to casual style.
        
        Args:
            formal_text: Formally phrased English text
            
        Returns:
            Casually phrased English text
        """
        # Define formal → casual replacements
        casual_replacements = {
            "It is obligatory that": "must",
            "It is permissible that": "can",
            "It is forbidden that": "must not",
            "it is obligatory that": "must",
            "it is permissible that": "can",
            "it is forbidden that": "must not",
            "is obligatory": "must",
            "is permissible": "can",
            "is forbidden": "must not",
            "obligated": "must",
            "permitted": "can",
            "prohibited": "must not",
            "For all": "all",
            "There exists": "some",
            "for all": "all",
            "there exists": "some",
            "believes": "thinks",
            "eventually": "sometime",
        }
        
        result = formal_text
        for formal, casual in casual_replacements.items():
            result = result.replace(formal, casual)
        
        return result
    
    def batch_parse(
        self,
        texts: List[str]
    ) -> List[Tuple[str, Optional[Formula]]]:
        """
        Parse multiple natural language texts.
        
        Args:
            texts: List of natural language texts
        
        Returns:
            List of (text, formula) tuples
        """
        results = []
        
        for text in texts:
            formula = self.parse_natural_language(text)
            results.append((text, formula))
        
        return results
    
    def analyze_parse_quality(
        self,
        text: str,
        expected_formula: Optional[Formula] = None
    ) -> Dict[str, Any]:
        """
        Analyze the quality of a parse.
        
        Args:
            text: Natural language text
            expected_formula: Expected TDFOL formula (for validation)
        
        Returns:
            Dictionary with parse quality metrics
        """
        result = {
            "text": text,
            "success": False,
            "method": None,
            "formula": None,
            "matches_expected": None,
        }
        
        # Try grammar-based parsing
        formula = self.parse_natural_language(text, use_fallback=False)
        
        if formula:
            result["success"] = True
            result["method"] = "grammar"
            result["formula"] = formula.to_string()
        else:
            # Try fallback
            formula = self._fallback_parse(text)
            if formula:
                result["success"] = True
                result["method"] = "pattern_matching"
                result["formula"] = formula.to_string()
        
        # Check against expected
        if expected_formula and formula:
            result["matches_expected"] = (
                formula.to_string() == expected_formula.to_string()
            )
        
        return result


class NaturalLanguageTDFOLInterface:
    """
    High-level interface for natural language ↔ TDFOL conversion.
    
    Provides easy-to-use API for:
    - Converting natural language to logical formulas
    - Converting formulas back to natural language
    - Interactive reasoning in natural language
    """
    
    def __init__(self):
        """Initialize the natural language interface."""
        self.grammar_bridge = TDFOLGrammarBridge()
        
        from .tdfol_cec_bridge import EnhancedTDFOLProver
        self.prover = EnhancedTDFOLProver(use_cec=True)
        
        if self.grammar_bridge.available:
            logger.info("Natural Language TDFOL Interface initialized")
        else:
            logger.info("Natural Language TDFOL Interface (limited - no grammar)")
    
    def understand(self, text: str) -> Optional[Formula]:
        """
        Understand natural language as a logical formula.
        
        Args:
            text: Natural language text
        
        Returns:
            TDFOL formula
        
        Example:
            >>> interface = NaturalLanguageTDFOLInterface()
            >>> formula = interface.understand("All birds can fly")
            >>> print(formula.to_string())
            ∀x.(Bird(x) → CanFly(x))
        """
        return self.grammar_bridge.parse_natural_language(text)
    
    def explain(self, formula: Formula) -> str:
        """
        Explain a logical formula in natural language.
        
        Args:
            formula: TDFOL formula
        
        Returns:
            Natural language explanation
        """
        return self.grammar_bridge.formula_to_natural_language(formula)
    
    def reason(
        self,
        premises: List[str],
        conclusion: str
    ) -> Dict[str, Any]:
        """
        Reason from natural language premises to conclusion.
        
        Args:
            premises: List of premise statements
            conclusion: Conclusion statement
        
        Returns:
            Dictionary with reasoning result
        
        Example:
            >>> result = interface.reason(
            ...     premises=["All humans are mortal", "Socrates is human"],
            ...     conclusion="Socrates is mortal"
            ... )
            >>> print(result['valid'])
            True
        """
        # Parse premises
        premise_formulas = []
        for premise in premises:
            formula = self.understand(premise)
            if formula:
                premise_formulas.append(formula)
            else:
                return {
                    "valid": False,
                    "error": f"Could not parse premise: {premise}"
                }
        
        # Parse conclusion
        conclusion_formula = self.understand(conclusion)
        if not conclusion_formula:
            return {
                "valid": False,
                "error": f"Could not parse conclusion: {conclusion}"
            }
        
        # Add premises to knowledge base
        from ...TDFOL.tdfol_core import TDFOLKnowledgeBase
        kb = TDFOLKnowledgeBase()
        for formula in premise_formulas:
            kb.add_axiom(formula)
        
        # Create prover and attempt proof
        from .tdfol_cec_bridge import EnhancedTDFOLProver
        prover = EnhancedTDFOLProver(kb=kb, use_cec=True)
        
        result = prover.prove(conclusion_formula)
        
        return {
            "valid": result.is_proved(),
            "premises": premises,
            "conclusion": conclusion,
            "proof_time_ms": result.time_ms,
            "proof_steps": len(result.proof_steps) if result.proof_steps else 0,
            "method": result.method,
        }


# Convenience functions
def parse_nl(text: str) -> Optional[Formula]:
    """
    Parse natural language to TDFOL formula.
    
    Args:
        text: Natural language text
    
    Returns:
        TDFOL formula
    """
    bridge = TDFOLGrammarBridge()
    return bridge.parse_natural_language(text)


def explain_formula(formula: Formula) -> str:
    """
    Explain TDFOL formula in natural language.
    
    Args:
        formula: TDFOL formula
    
    Returns:
        Natural language explanation
    """
    bridge = TDFOLGrammarBridge()
    return bridge.formula_to_natural_language(formula)
