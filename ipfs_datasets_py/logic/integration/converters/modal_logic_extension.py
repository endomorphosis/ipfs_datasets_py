"""
Modal Logic Extension Module

This module provides extended support for modal logic, temporal logic, deontic logic,
and epistemic logic using SymbolicAI integration.

Modal Logic Types Supported:
- Alethic Modal Logic: Necessity (□) and Possibility (◇)
- Temporal Logic: Always (□), Eventually (◇), Until (U), Next (X)
- Deontic Logic: Obligation (O), Permission (P), Prohibition (F)
- Epistemic Logic: Knowledge (K), Belief (B), Common Knowledge (C)
"""

import json
import logging
import re
from typing import Dict, List, Optional, Union, Any, Tuple, TYPE_CHECKING
from dataclasses import dataclass
try:
    from beartype import beartype  # type: ignore
except ImportError:  # pragma: no cover
    def beartype(func):  # type: ignore
        return func
if TYPE_CHECKING:
    from symai import Symbol

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Fallback imports when SymbolicAI is not available
try:
    from symai import Symbol, Expression
    SYMBOLIC_AI_AVAILABLE = True
except (ImportError, SystemExit):
    SYMBOLIC_AI_AVAILABLE = False
    logger.warning("SymbolicAI not available. Modal logic features will be limited.")
    
    # Create mock classes for development/testing without SymbolicAI
    class Symbol:
        def __init__(self, value: str, semantic: bool = False):
            self.value = value
            self._semantic = semantic
            
        def query(self, prompt: str) -> str:
            return f"Mock response for: {prompt}"
    
    class Expression:
        pass


@dataclass
class ModalFormula:
    """Represents a modal logic formula with metadata."""
    formula: str
    modal_type: str  # 'alethic', 'temporal', 'deontic', 'epistemic'
    operators: List[str]
    base_formula: str
    confidence: float
    semantic_context: Dict[str, Any]


@dataclass
class LogicClassification:
    """Classification result for identifying logic type."""
    logic_type: str
    confidence: float
    indicators: List[str]
    context: Dict[str, Any]


class ModalLogicSymbol(Symbol):
    """Extended Symbol class with modal logic operators."""

    def __init__(self, value: str, semantic: bool = True, **kwargs):
        """Initialize modal logic symbol."""
        static_context = kwargs.pop("static_context", None)
        if kwargs:
            logger.debug("Ignoring unsupported ModalLogicSymbol kwargs: %s", list(kwargs.keys()))

        # Some Symbol implementations treat `static_context` as a reserved/managed attribute.
        # Prefer passing it through the base constructor when supported; otherwise keep it
        # on a private attribute to avoid reserved-property assignment errors.
        if static_context is not None:
            try:
                super().__init__(value, semantic, static_context=static_context)
            except TypeError:
                super().__init__(value, semantic)
                self._static_context = static_context
        else:
            super().__init__(value, semantic)

        # Ensure compatibility with code paths expecting a _semantic attribute.
        self._semantic = bool(semantic)
        self._modal_operators = {
            'necessity': '□',
            'possibility': '◇', 
            'obligation': 'O',
            'permission': 'P',
            'prohibition': 'F',
            'knowledge': 'K',
            'belief': 'B',
            'always': '□',
            'eventually': '◇',
            'next': 'X',
            'until': 'U'
        }
    
    def necessarily(self) -> 'ModalLogicSymbol':
        """Apply necessity modal operator (□)."""
        return ModalLogicSymbol(f"□({self.value})", semantic=self._semantic)
    
    def possibly(self) -> 'ModalLogicSymbol':
        """Apply possibility modal operator (◇)."""
        return ModalLogicSymbol(f"◇({self.value})", semantic=self._semantic)
    
    def obligation(self) -> 'ModalLogicSymbol':
        """Apply deontic obligation operator (O)."""
        return ModalLogicSymbol(f"O({self.value})", semantic=self._semantic)
    
    def permission(self) -> 'ModalLogicSymbol':
        """Apply deontic permission operator (P)."""
        return ModalLogicSymbol(f"P({self.value})", semantic=self._semantic)
    
    def prohibition(self) -> 'ModalLogicSymbol':
        """Apply deontic prohibition operator (F)."""
        return ModalLogicSymbol(f"F({self.value})", semantic=self._semantic)
    
    def knowledge(self, agent: str = "agent") -> 'ModalLogicSymbol':
        """Apply epistemic knowledge operator (K)."""
        return ModalLogicSymbol(f"K_{agent}({self.value})", semantic=self._semantic)
    
    def belief(self, agent: str = "agent") -> 'ModalLogicSymbol':
        """Apply epistemic belief operator (B)."""
        return ModalLogicSymbol(f"B_{agent}({self.value})", semantic=self._semantic)
    
    def temporal_always(self) -> 'ModalLogicSymbol':
        """Apply temporal always operator (□)."""
        return ModalLogicSymbol(f"□({self.value})", semantic=self._semantic)
    
    def temporal_eventually(self) -> 'ModalLogicSymbol':
        """Apply temporal eventually operator (◇)."""
        return ModalLogicSymbol(f"◇({self.value})", semantic=self._semantic)
    
    def temporal_next(self) -> 'ModalLogicSymbol':
        """Apply temporal next operator (X)."""
        return ModalLogicSymbol(f"X({self.value})", semantic=self._semantic)
    
    def temporal_until(self, condition: str) -> 'ModalLogicSymbol':
        """Apply temporal until operator (U)."""
        return ModalLogicSymbol(f"({self.value} U {condition})", semantic=self._semantic)


class AdvancedLogicConverter:
    """Advanced logic converter supporting multiple modal logics."""
    
    def __init__(self, confidence_threshold: float = 0.7):
        """Initialize the converter."""
        self.confidence_threshold = confidence_threshold
        self._logic_indicators = {
            'modal': ['might', 'could', 'necessarily', 'possibly'],
            'temporal': ['always', 'never', 'eventually', 'sometimes', 'until', 'before', 'after'],
            'deontic': [
                'must', 'shall', 'must not', 'shall not', 'ought', 'should',
                'permitted', 'forbidden', 'obliged', 'allowed', 'required'
            ],
            'epistemic': ['knows', 'believes', 'aware', 'certain', 'doubts', 'thinks']
        }

    def _normalize_query_response(self, response: Any) -> str:
        """Normalize SymbolicAI responses to a lowercase-friendly string."""
        if isinstance(response, list):
            normalized_items = self._normalize_symbol_items(response)
            return " ".join(str(item) for item in normalized_items)
        if isinstance(response, dict):
            return json.dumps(response)
        return str(response)

    def _normalize_symbol_items(self, items: List[Any]) -> List[Any]:
        """Normalize list items into Symbol-compatible objects with _semantic set."""
        normalized: List[Any] = []
        for item in items:
            if isinstance(item, list):
                normalized.extend(self._normalize_symbol_items(item))
                continue
            if isinstance(item, Symbol):
                if not hasattr(item, "_semantic"):
                    item._semantic = True
                normalized.append(item)
                continue
            normalized.append(ModalLogicSymbol(str(item), semantic=True))
        return normalized
        
    @beartype
    def detect_logic_type(self, text: str) -> LogicClassification:
        """
        Detect the type of logic most appropriate for the given text.
        
        Args:
            text: Input natural language text
            
        Returns:
            LogicClassification with detected type and confidence
        """
        if not text or not text.strip():
            raise ValueError("Text cannot be empty")
        
        text_lower = text.lower()
        
        # Score each logic type based on indicators
        scores = {}
        indicators_found = {}
        
        for logic_type, indicators in self._logic_indicators.items():
            score = 0
            found_indicators = []
            
            for indicator in indicators:
                if indicator in text_lower:
                    score += 1
                    found_indicators.append(indicator)
            
            # Normalize score by number of indicators
            normalized_score = score / len(indicators) if indicators else 0
            scores[logic_type] = normalized_score
            indicators_found[logic_type] = found_indicators
        
        # Find the logic type with highest score
        best_type = max(scores.keys(), key=lambda k: scores[k])
        best_score = scores[best_type]
        
        # If no strong indicators, default to standard FOL
        if best_score < 0.1:
            best_type = 'fol'
            best_score = 0.5
        
        return LogicClassification(
            logic_type=best_type,
            confidence=min(best_score * 2, 1.0),  # Scale confidence
            indicators=indicators_found.get(best_type, []),
            context={
                'all_scores': scores,
                'text_length': len(text),
                'detected_indicators': indicators_found
            }
        )
    
    @beartype
    def convert_to_modal_logic(self, text: str) -> ModalFormula:
        """
        Convert text to appropriate modal logic formula.
        
        Args:
            text: Input natural language text
            
        Returns:
            ModalFormula with converted logic
        """
        # Detect logic type first
        classification = self.detect_logic_type(text)
        logic_type = classification.logic_type
        
        if logic_type == "modal":
            return self._convert_to_modal_logic(text, classification)
        elif logic_type == "temporal":
            return self._convert_to_temporal_logic(text, classification)
        elif logic_type == "deontic":
            return self._convert_to_deontic_logic(text, classification)
        elif logic_type == "epistemic":
            return self._convert_to_epistemic_logic(text, classification)
        else:
            return self._convert_to_fol(text, classification)
    
    def _convert_to_modal_logic(self, text: str, classification: LogicClassification) -> ModalFormula:
        """Convert text to alethic modal logic."""
        symbol = ModalLogicSymbol(text, semantic=True)
        
        # Determine modal operator needed using fallback
        if SYMBOLIC_AI_AVAILABLE:
            modal_type = symbol.query(
                "Does this express necessity, possibility, or something else? "
                "Respond with: necessity, possibility, or neither"
            )
            modal_type_str = self._normalize_query_response(
                getattr(modal_type, 'value', modal_type)
            ).lower()
        else:
            # Fallback logic for when SymbolicAI is not available
            text_lower = text.lower()
            if any(word in text_lower for word in ['must', 'necessarily', 'required']):
                modal_type_str = 'necessity'
            elif any(word in text_lower for word in ['might', 'could', 'possibly']):
                modal_type_str = 'possibility' 
            else:
                modal_type_str = 'neither'
        
        if "necessity" in modal_type_str:
            modal_formula = symbol.necessarily()
        elif "possibility" in modal_type_str:
            modal_formula = symbol.possibly()
        else:
            modal_formula = symbol
        
        return ModalFormula(
            formula=modal_formula.value,
            modal_type="alethic",
            operators=['□'] if "necessity" in modal_type_str else ['◇'] if "possibility" in modal_type_str else [],
            base_formula=text,
            confidence=classification.confidence,
            semantic_context={
                "modal_operator": modal_type_str,
                "classification": classification
            }
        )
    
    def _convert_to_temporal_logic(self, text: str, classification: LogicClassification) -> ModalFormula:
        """Convert text to temporal logic."""
        symbol = ModalLogicSymbol(text, semantic=True)
        
        # Determine temporal operator using fallback logic
        if SYMBOLIC_AI_AVAILABLE:
            temporal_type = symbol.query(
                "Does this express something that is always true, eventually true, or something else? "
                "Respond with: always, eventually, or neither"
            )
            temporal_type_str = self._normalize_query_response(
                getattr(temporal_type, 'value', temporal_type)
            ).lower()
        else:
            # Fallback logic
            text_lower = text.lower()
            if any(word in text_lower for word in ['always', 'never', 'invariably']):
                temporal_type_str = 'always'
            elif any(word in text_lower for word in ['eventually', 'sometimes', 'finally']):
                temporal_type_str = 'eventually'
            else:
                temporal_type_str = 'neither'
        
        if "always" in temporal_type_str:
            temporal_formula = symbol.temporal_always()
        elif "eventually" in temporal_type_str:
            temporal_formula = symbol.temporal_eventually()
        else:
            temporal_formula = symbol
        
        return ModalFormula(
            formula=temporal_formula.value,
            modal_type="temporal",
            operators=['□'] if "always" in temporal_type_str else ['◇'] if "eventually" in temporal_type_str else [],
            base_formula=text,
            confidence=classification.confidence,
            semantic_context={
                "temporal_operator": temporal_type_str,
                "classification": classification
            }
        )
    
    def _convert_to_deontic_logic(self, text: str, classification: LogicClassification) -> ModalFormula:
        """Convert text to deontic logic."""
        symbol = ModalLogicSymbol(text, semantic=True)
        
        # Determine deontic operator using fallback logic
        if SYMBOLIC_AI_AVAILABLE:
            deontic_type = symbol.query(
                "Does this express an obligation, permission, prohibition, or something else? "
                "Respond with: obligation, permission, prohibition, or neither"
            )
            deontic_type_str = self._normalize_query_response(
                getattr(deontic_type, 'value', deontic_type)
            ).lower()
        else:
            # Fallback logic
            text_lower = text.lower()
            if any(word in text_lower for word in ['must', 'ought', 'should', 'obliged']):
                deontic_type_str = 'obligation'
            elif any(word in text_lower for word in ['may', 'allowed', 'permitted']):
                deontic_type_str = 'permission'
            elif any(word in text_lower for word in ['forbidden', 'prohibited', 'not allowed']):
                deontic_type_str = 'prohibition'
            else:
                deontic_type_str = 'neither'
        
        if "obligation" in deontic_type_str:
            deontic_formula = symbol.obligation()
        elif "permission" in deontic_type_str:
            deontic_formula = symbol.permission()
        elif "prohibition" in deontic_type_str:
            deontic_formula = symbol.prohibition()
        else:
            deontic_formula = symbol
        
        return ModalFormula(
            formula=deontic_formula.value,
            modal_type="deontic",
            operators=['O'] if "obligation" in deontic_type_str else 
                     ['P'] if "permission" in deontic_type_str else
                     ['F'] if "prohibition" in deontic_type_str else [],
            base_formula=text,
            confidence=classification.confidence,
            semantic_context={
                "deontic_operator": deontic_type_str,
                "classification": classification
            }
        )
    
    def _convert_to_epistemic_logic(self, text: str, classification: LogicClassification) -> ModalFormula:
        """Convert text to epistemic logic."""
        symbol = ModalLogicSymbol(text, semantic=True)
        
        # Determine epistemic operator using fallback logic
        if SYMBOLIC_AI_AVAILABLE:
            epistemic_type = symbol.query(
                "Does this express knowledge, belief, or something else? "
                "Respond with: knowledge, belief, or neither"
            )
            epistemic_type_str = self._normalize_query_response(
                getattr(epistemic_type, 'value', epistemic_type)
            ).lower()
        else:
            # Fallback logic
            text_lower = text.lower()
            if any(word in text_lower for word in ['knows', 'certain', 'aware']):
                epistemic_type_str = 'knowledge'
            elif any(word in text_lower for word in ['believes', 'thinks', 'suspects']):
                epistemic_type_str = 'belief'
            else:
                epistemic_type_str = 'neither'
        
        # Extract agent if possible (simple pattern matching)
        agent_match = re.search(r'(\w+)\s+(?:knows|believes|thinks)', text.lower())
        agent = agent_match.group(1) if agent_match else "agent"
        
        if "knowledge" in epistemic_type_str:
            epistemic_formula = symbol.knowledge(agent)
        elif "belief" in epistemic_type_str:
            epistemic_formula = symbol.belief(agent)
        else:
            epistemic_formula = symbol
        
        return ModalFormula(
            formula=epistemic_formula.value,
            modal_type="epistemic",
            operators=['K'] if "knowledge" in epistemic_type_str else ['B'] if "belief" in epistemic_type_str else [],
            base_formula=text,
            confidence=classification.confidence,
            semantic_context={
                "epistemic_operator": epistemic_type_str,
                "agent": agent,
                "classification": classification
            }
        )
    
    def _convert_to_fol(self, text: str, classification: LogicClassification) -> ModalFormula:
        """Convert text to standard First-Order Logic."""
        # Use existing FOL conversion logic
        from .symbolic_fol_bridge import SymbolicFOLBridge
        
        bridge = SymbolicFOLBridge()
        symbol = bridge.create_semantic_symbol(text)
        
        # Use fallback FOL conversion
        fol_result = bridge._fallback_to_fol_conversion(text)
        
        return ModalFormula(
            formula=fol_result.fol_formula,
            modal_type="fol",
            operators=[],
            base_formula=text,
            confidence=fol_result.confidence,
            semantic_context={
                "fol_components": fol_result.components,
                "classification": classification
            }
        )


# Convenience functions for quick modal logic conversion
@beartype
def convert_to_modal(text: str, confidence_threshold: float = 0.7) -> ModalFormula:
    """
    Quick conversion to modal logic.
    
    Args:
        text: Natural language text
        confidence_threshold: Minimum confidence for conversion
        
    Returns:
        ModalFormula result
    """
    converter = AdvancedLogicConverter(confidence_threshold)
    return converter.convert_to_modal_logic(text)


@beartype
def detect_logic_type(text: str) -> LogicClassification:
    """
    Quick logic type detection.
    
    Args:
        text: Natural language text
        
    Returns:
        LogicClassification result
    """
    converter = AdvancedLogicConverter()
    return converter.detect_logic_type(text)


# Export key classes and functions
__all__ = [
    'ModalLogicSymbol',
    'AdvancedLogicConverter', 
    'ModalFormula',
    'LogicClassification',
    'convert_to_modal',
    'detect_logic_type',
    'SYMBOLIC_AI_AVAILABLE'
]
