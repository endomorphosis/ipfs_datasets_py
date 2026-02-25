"""TDFOL/CEC Formula Translation for Logic Optimizer.

This module provides translation between the Logic Optimizer's statement format
and TDFOL/CEC formula representations for proper theorem proving.

Integrates with:
- TDFOL parser for formula parsing
- CEC framework for event calculus
- Neurosymbolic API for unified reasoning
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple, cast
from dataclasses import dataclass
from enum import Enum

from ipfs_datasets_py.optimizers.common.backend_resilience import BackendCallPolicy, execute_with_resilience
from ipfs_datasets_py.optimizers.common.circuit_breaker import CircuitBreaker
from ipfs_datasets_py.optimizers.common.exceptions import CircuitBreakerOpenError, RetryableBackendError
from ipfs_datasets_py.optimizers.common.log_redaction import redact_sensitive

logger = logging.getLogger(__name__)


def _safe_error_text(error: Exception) -> str:
    """Render exception text with sensitive fragments redacted."""
    return cast(str, redact_sensitive(str(error)))


class FormulaFormalism(Enum):
    """Supported logic formalisms."""
    FOL = "fol"
    TDFOL = "tdfol"
    CEC = "cec"
    MODAL = "modal"
    DEONTIC = "deontic"


@dataclass
class TranslationResult:
    """Result of formula translation.
    
    Attributes:
        formula: Translated formula object
        formalism: Target formalism
        original_text: Original text
        success: Whether translation succeeded
        errors: Any errors encountered
        metadata: Additional metadata
    """
    formula: Any
    formalism: FormulaFormalism
    original_text: str
    success: bool
    errors: Optional[List[str]] = None
    metadata: Optional[Dict[str, Any]] = None
    
    def __post_init__(self) -> None:
        if self.errors is None:
            self.errors = []
        if self.metadata is None:
            self.metadata = {}


class TDFOLFormulaTranslator:
    """Translator for TDFOL formulas.
    
    Converts between Logic Optimizer statements and TDFOL formula objects
    for use with theorem provers.
    
    Example:
        >>> translator = TDFOLFormulaTranslator()
        >>> result = translator.translate_to_tdfol(
        ...     "All employees must complete training"
        ... )
        >>> print(result.formula)
    """
    
    def __init__(self) -> None:
        """Initialize the TDFOL translator."""
        self._parse_policy = BackendCallPolicy(
            service_name="tdfol_reasoner_parse",
            timeout_seconds=20.0,
            max_retries=1,
            initial_backoff_seconds=0.1,
            backoff_multiplier=2.0,
            max_backoff_seconds=0.5,
            circuit_failure_threshold=5,
            circuit_recovery_timeout=60.0,
        )
        self._parse_circuit_breaker = CircuitBreaker(
            name=self._parse_policy.service_name,
            failure_threshold=self._parse_policy.circuit_failure_threshold,
            recovery_timeout=self._parse_policy.circuit_recovery_timeout,
            expected_exception=Exception,
        )
        self._nl_generate_policy = BackendCallPolicy(
            service_name="tdfol_reasoner_nl_generate",
            timeout_seconds=20.0,
            max_retries=1,
            initial_backoff_seconds=0.1,
            backoff_multiplier=2.0,
            max_backoff_seconds=0.5,
            circuit_failure_threshold=5,
            circuit_recovery_timeout=60.0,
        )
        self._nl_generate_circuit_breaker = CircuitBreaker(
            name=self._nl_generate_policy.service_name,
            failure_threshold=self._nl_generate_policy.circuit_failure_threshold,
            recovery_timeout=self._nl_generate_policy.circuit_recovery_timeout,
            expected_exception=Exception,
        )
        self._init_parser()
        self._init_neurosymbolic()
        
    def _init_parser(self) -> None:
        """Initialize TDFOL parser."""
        try:
            from ipfs_datasets_py.logic.TDFOL.tdfol_parser import parse_tdfol
            self.parse_tdfol = parse_tdfol
            self.parser_available = True
            logger.info("TDFOL parser initialized")
        except ImportError as e:
            logger.warning(f"TDFOL parser not available: {e}")
            self.parse_tdfol = None
            self.parser_available = False
    
    def _init_neurosymbolic(self) -> None:
        """Initialize neurosymbolic reasoner."""
        try:
            from ipfs_datasets_py.logic.integration.neurosymbolic_api import (  # type: ignore[import-untyped]
                NeurosymbolicReasoner,
            )
            self.reasoner = NeurosymbolicReasoner(
                use_cec=True,
                use_modal=True,
                use_nl=True
            )
            self.reasoner_available = True
            logger.info("Neurosymbolic reasoner initialized")
        except (AttributeError, ImportError, RuntimeError, TypeError, ValueError) as e:
            logger.warning(f"Neurosymbolic reasoner not available: {e}")
            self.reasoner = None
            self.reasoner_available = False
    
    def translate_to_tdfol(
        self,
        text: str,
        context: Optional[Dict[str, Any]] = None
    ) -> TranslationResult:
        """Translate text to TDFOL formula.
        
        Args:
            text: Text to translate
            context: Optional context information
            
        Returns:
            TranslationResult with TDFOL formula
        """
        if not self.reasoner_available:
            return TranslationResult(
                formula=None,
                formalism=FormulaFormalism.TDFOL,
                original_text=text,
                success=False,
                errors=["Neurosymbolic reasoner not available"]
            )
        
        try:
            # Parse using neurosymbolic API
            formula = execute_with_resilience(
                lambda: self.reasoner.parse(text, format="auto"),
                self._parse_policy,
                circuit_breaker=self._parse_circuit_breaker,
            )
            
            if formula is None:
                # Fallback to pattern-based translation
                formula = self._pattern_based_translation(text)
            
            return TranslationResult(
                formula=formula,
                formalism=FormulaFormalism.TDFOL,
                original_text=text,
                success=formula is not None,
                metadata={'parser': 'neurosymbolic'}
            )
            
        except (
            AttributeError,
            CircuitBreakerOpenError,
            RetryableBackendError,
            RuntimeError,
            TypeError,
            ValueError,
        ) as e:
            safe_error = _safe_error_text(e)
            logger.error("TDFOL translation error: %s", safe_error)
            return TranslationResult(
                formula=None,
                formalism=FormulaFormalism.TDFOL,
                original_text=text,
                success=False,
                errors=[safe_error]
            )
    
    def _pattern_based_translation(self, text: str) -> Optional[Any]:
        """Pattern-based translation fallback.
        
        Args:
            text: Text to translate
            
        Returns:
            TDFOL formula or None
        """
        # Simple pattern matching for common patterns
        text_lower = text.lower()
        
        # Detect obligation patterns
        if 'must' in text_lower or 'required' in text_lower:
            return self._create_obligation_formula(text)
        
        # Detect permission patterns
        elif 'may' in text_lower or 'allowed' in text_lower:
            return self._create_permission_formula(text)
        
        # Detect prohibition patterns
        elif 'must not' in text_lower or 'prohibited' in text_lower:
            return self._create_prohibition_formula(text)
        
        # Default to simple predicate
        else:
            return self._create_simple_predicate(text)
    
    def _create_obligation_formula(self, text: str) -> Any:
        """Create obligation formula from text.
        
        Args:
            text: Text describing obligation
            
        Returns:
            TDFOL obligation formula
        """
        try:
            from ipfs_datasets_py.logic.TDFOL.tdfol_core import DeonticFormula, DeonticOperator
            
            # Extract subject and action
            # Simplified: just create a generic obligation
            predicate_str = text.replace('must', '').replace('required', '').strip()
            
            # Create obligation formula: O(predicate)
            formula = DeonticFormula(
                operator=DeonticOperator.OBLIGATION,
                formula=predicate_str
            )
            
            return formula
            
        except (AttributeError, ImportError, RuntimeError, TypeError, ValueError) as e:
            logger.debug(f"Error creating obligation formula: {e}")
            return None
    
    def _create_permission_formula(self, text: str) -> Any:
        """Create permission formula from text.
        
        Args:
            text: Text describing permission
            
        Returns:
            TDFOL permission formula
        """
        try:
            from ipfs_datasets_py.logic.TDFOL.tdfol_core import DeonticFormula, DeonticOperator
            
            predicate_str = text.replace('may', '').replace('allowed', '').strip()
            
            formula = DeonticFormula(
                operator=DeonticOperator.PERMISSION,
                formula=predicate_str
            )
            
            return formula
            
        except (AttributeError, ImportError, RuntimeError, TypeError, ValueError) as e:
            logger.debug(f"Error creating permission formula: {e}")
            return None
    
    def _create_prohibition_formula(self, text: str) -> Any:
        """Create prohibition formula from text.
        
        Args:
            text: Text describing prohibition
            
        Returns:
            TDFOL prohibition formula
        """
        try:
            from ipfs_datasets_py.logic.TDFOL.tdfol_core import DeonticFormula, DeonticOperator
            
            predicate_str = text.replace('must not', '').replace('prohibited', '').strip()
            
            formula = DeonticFormula(
                operator=DeonticOperator.PROHIBITION,
                formula=predicate_str
            )
            
            return formula
            
        except (AttributeError, ImportError, RuntimeError, TypeError, ValueError) as e:
            logger.debug(f"Error creating prohibition formula: {e}")
            return None
    
    def _create_simple_predicate(self, text: str) -> Any:
        """Create simple predicate from text.
        
        Args:
            text: Text to convert to predicate
            
        Returns:
            TDFOL predicate formula
        """
        try:
            from ipfs_datasets_py.logic.TDFOL.tdfol_core import Predicate
            
            # Simplified: create a predicate with the text as name
            # In a real implementation, this would do proper parsing
            formula = Predicate(name=text, terms=[])
            
            return formula
            
        except (AttributeError, ImportError, RuntimeError, TypeError, ValueError) as e:
            logger.debug(f"Error creating predicate: {e}")
            return None
    
    def translate_from_tdfol(
        self,
        formula: Any
    ) -> str:
        """Translate TDFOL formula to natural language.
        
        Args:
            formula: TDFOL formula object
            
        Returns:
            Natural language representation
        """
        if not self.reasoner_available or not self.reasoner.nl_interface:
            # Fallback to string representation
            return str(formula)
        
        try:
            # Use natural language interface for generation
            nl_text = execute_with_resilience(
                lambda: self.reasoner.nl_interface.generate(formula),
                self._nl_generate_policy,
                circuit_breaker=self._nl_generate_circuit_breaker,
            )
            return cast(str, nl_text)
            
        except (
            AttributeError,
            CircuitBreakerOpenError,
            RetryableBackendError,
            RuntimeError,
            TypeError,
            ValueError,
        ) as e:
            logger.debug("Error translating from TDFOL: %s", _safe_error_text(e))
            return str(formula)


class CECFormulaTranslator:
    """Translator for CEC (Cognitive Event Calculus) formulas.
    
    Converts between Logic Optimizer statements and CEC event representations.
    
    Example:
        >>> translator = CECFormulaTranslator()
        >>> result = translator.translate_to_cec(
        ...     "Training event starts at time 0"
        ... )
    """
    
    def __init__(self) -> None:
        """Initialize the CEC translator."""
        self._init_cec()
    
    def _init_cec(self) -> None:
        """Initialize CEC framework."""
        try:
            from ipfs_datasets_py.logic.CEC.cec_framework import CECFramework
            self.cec = CECFramework()
            self.cec_available = True
            logger.info("CEC framework initialized")
        except (AttributeError, ImportError, RuntimeError, TypeError, ValueError) as e:
            logger.warning(f"CEC framework not available: {e}")
            self.cec = None
            self.cec_available = False
    
    def translate_to_cec(
        self,
        text: str,
        context: Optional[Dict[str, Any]] = None
    ) -> TranslationResult:
        """Translate text to CEC event representation.
        
        Args:
            text: Text to translate
            context: Optional context information
            
        Returns:
            TranslationResult with CEC formula
        """
        if not self.cec_available:
            return TranslationResult(
                formula=None,
                formalism=FormulaFormalism.CEC,
                original_text=text,
                success=False,
                errors=["CEC framework not available"]
            )
        
        try:
            # Detect temporal patterns
            if 'starts' in text.lower() or 'begins' in text.lower():
                event_type = 'start'
            elif 'ends' in text.lower() or 'finishes' in text.lower():
                event_type = 'end'
            else:
                event_type = 'occurs'
            
            # Create CEC event (simplified)
            # In real implementation, this would use proper CEC API
            formula = {
                'event_type': event_type,
                'description': text,
                'formalism': 'cec'
            }
            
            return TranslationResult(
                formula=formula,
                formalism=FormulaFormalism.CEC,
                original_text=text,
                success=True,
                metadata={'event_type': event_type}
            )
            
        except (AttributeError, RuntimeError, TypeError, ValueError) as e:
            safe_error = _safe_error_text(e)
            logger.error("CEC translation error: %s", safe_error)
            return TranslationResult(
                formula=None,
                formalism=FormulaFormalism.CEC,
                original_text=text,
                success=False,
                errors=[safe_error]
            )


class UnifiedFormulaTranslator:
    """Unified translator supporting multiple formalisms.
    
    This translator automatically selects the appropriate formalism
    based on the input text and context.
    
    Example:
        >>> translator = UnifiedFormulaTranslator()
        >>> result = translator.translate(
        ...     "All employees must complete training",
        ...     formalism=FormulaFormalism.TDFOL
        ... )
    """
    
    def __init__(self) -> None:
        """Initialize the unified translator."""
        self.tdfol_translator = TDFOLFormulaTranslator()
        self.cec_translator = CECFormulaTranslator()
    
    def translate(
        self,
        text: str,
        formalism: Optional[FormulaFormalism] = None,
        context: Optional[Dict[str, Any]] = None
    ) -> TranslationResult:
        """Translate text to specified formalism.
        
        Args:
            text: Text to translate
            formalism: Target formalism (auto-detected if None)
            context: Optional context information
            
        Returns:
            TranslationResult
        """
        # Auto-detect formalism if not specified
        if formalism is None:
            formalism = self._detect_formalism(text)
        
        # Translate using appropriate translator
        if formalism == FormulaFormalism.TDFOL or formalism == FormulaFormalism.DEONTIC:
            return self.tdfol_translator.translate_to_tdfol(text, context)
        
        elif formalism == FormulaFormalism.CEC:
            return self.cec_translator.translate_to_cec(text, context)
        
        else:
            # Default to TDFOL
            return self.tdfol_translator.translate_to_tdfol(text, context)
    
    def _detect_formalism(self, text: str) -> FormulaFormalism:
        """Auto-detect appropriate formalism for text.
        
        Args:
            text: Text to analyze
            
        Returns:
            Detected formalism
        """
        text_lower = text.lower()
        
        # Check for temporal/event keywords (CEC)
        cec_keywords = ['event', 'starts', 'ends', 'occurs', 'happens', 'time']
        if any(kw in text_lower for kw in cec_keywords):
            return FormulaFormalism.CEC
        
        # Check for deontic keywords (TDFOL)
        deontic_keywords = ['must', 'may', 'shall', 'required', 'permitted', 'prohibited']
        if any(kw in text_lower for kw in deontic_keywords):
            return FormulaFormalism.TDFOL
        
        # Default to TDFOL
        return FormulaFormalism.TDFOL
    
    def get_capabilities(self) -> Dict[str, bool]:
        """Get translator capabilities.
        
        Returns:
            Dictionary of formalism support
        """
        return {
            'tdfol': self.tdfol_translator.parser_available or self.tdfol_translator.reasoner_available,
            'cec': self.cec_translator.cec_available,
            'neurosymbolic': self.tdfol_translator.reasoner_available
        }
