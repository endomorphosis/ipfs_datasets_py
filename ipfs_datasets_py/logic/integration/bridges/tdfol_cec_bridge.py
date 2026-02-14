"""
TDFOL-CEC Integration Bridge

This module provides seamless integration between TDFOL and CEC native systems,
enabling TDFOL to use all 87 CEC inference rules plus modal logic provers.

Addresses: Integration of TDFOL prover with CEC's comprehensive rule set
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional, Set, Any

from ..TDFOL.tdfol_core import Formula, Predicate, Variable, Constant
from ..TDFOL.tdfol_prover import TDFOLProver, ProofResult, ProofStatus, ProofStep
from .base_prover_bridge import (
    BaseProverBridge,
    BridgeMetadata,
    BridgeCapability
)

logger = logging.getLogger(__name__)

# Try to import CEC components
CEC_AVAILABLE = False
try:
    from ..CEC.native import (
        prover_core,
        dcec_parsing,
        dcec_core,
    )
    CEC_AVAILABLE = True
    logger.info("CEC native modules loaded successfully")
except ImportError as e:
    logger.warning(f"CEC native modules not available: {e}")


class TDFOLCECBridge(BaseProverBridge):
    """
    Bridge between TDFOL and CEC systems.
    
    Features:
    - Use CEC's 87 inference rules in TDFOL proving
    - Convert between TDFOL and DCEC formula representations
    - Leverage CEC's optimized proof search
    """
    
    def __init__(self):
        """Initialize the TDFOL-CEC bridge."""
        super().__init__()
        
        if not self.cec_available:
            logger.warning("CEC integration disabled - CEC modules not available")
            return
        
        # Initialize CEC components
        self.cec_rules = self._load_cec_rules()
        logger.info(f"Loaded {len(self.cec_rules)} CEC inference rules")
    
    def _init_metadata(self) -> BridgeMetadata:
        """Initialize bridge metadata."""
        return BridgeMetadata(
            name="TDFOL-CEC Bridge",
            version="1.0.0",
            target_system="CEC",
            capabilities=[
                BridgeCapability.BIDIRECTIONAL_CONVERSION,
                BridgeCapability.RULE_EXTRACTION,
                BridgeCapability.OPTIMIZATION
            ],
            requires_external_prover=False,
            description="Integrates TDFOL with CEC's 87 inference rules and modal logic"
        )
    
    def _check_availability(self) -> bool:
        """Check if CEC modules are available."""
        self.cec_available = CEC_AVAILABLE
        return CEC_AVAILABLE
    
    def _load_cec_rules(self) -> List[Any]:
        """Load CEC inference rules."""
        if not self.cec_available:
            return []
        
        # Get all inference rule classes from prover_core
        import inspect
        rules = []
        
        try:
            # Get all classes that inherit from InferenceRule
            members = inspect.getmembers(prover_core, inspect.isclass)
            
            for name, cls in members:
                if 'Rule' in name and name != 'InferenceRule':
                    try:
                        # Instantiate the rule
                        rule_instance = cls()
                        rules.append(rule_instance)
                    except Exception as e:
                        logger.debug(f"Could not instantiate {name}: {e}")
        except Exception as e:
            logger.warning(f"Failed to load CEC rules: {e}")
        
        return rules
    
    def to_target_format(self, formula: Formula) -> str:
        """
        Convert TDFOL formula to DCEC string representation.
        
        Args:
            formula: TDFOL formula
        
        Returns:
            DCEC string representation
            
        Raises:
            ValueError: If formula cannot be converted
        """
        if not self.is_available():
            raise ValueError("CEC bridge not available")
        
        # Use the converter module
        from ..TDFOL.tdfol_converter import tdfol_to_dcec
        return tdfol_to_dcec(formula)
    
    def tdfol_to_dcec_string(self, formula: Formula) -> str:
        """Legacy method for backward compatibility."""
        return self.to_target_format(formula)
    
    def from_target_format(self, target_result: Any) -> ProofResult:
        """
        Convert CEC result back to TDFOL ProofResult.
        
        Args:
            target_result: Result from CEC prover
            
        Returns:
            ProofResult with standardized format
        """
        # CEC already returns ProofResult, so just pass through
        # In more complex bridges, this would do actual conversion
        if isinstance(target_result, ProofResult):
            return target_result
        
        # Default conversion for unknown result types
        return ProofResult(
            status=ProofStatus.UNKNOWN,
            formula=None,
            time_ms=0,
            method="cec_integration",
            message=f"Converted from CEC result: {target_result}"
        )
    
    def prove(
        self,
        formula: Formula,
        timeout: Optional[int] = None,
        axioms: Optional[List[Formula]] = None,
        **kwargs
    ) -> ProofResult:
        """
        Prove a formula using CEC.
        
        Args:
            formula: TDFOL formula to prove
            timeout: Optional timeout in seconds
            axioms: Optional list of axioms
            **kwargs: Additional CEC-specific parameters
            
        Returns:
            ProofResult with status and details
        """
        timeout_ms = (timeout * 1000) if timeout else 5000
        axioms = axioms or []
        
        return self.prove_with_cec(formula, axioms, timeout_ms)
    
    def dcec_string_to_tdfol(self, dcec_string: str) -> Formula:
        """
        Convert DCEC string to TDFOL formula.
        
        Args:
            dcec_string: DCEC string
        
        Returns:
            TDFOL formula
        """
        from ..TDFOL.tdfol_dcec_parser import parse_dcec
        return parse_dcec(dcec_string)
    
    def prove_with_cec(
        self,
        goal: Formula,
        axioms: List[Formula],
        timeout_ms: int = 5000
    ) -> ProofResult:
        """
        Prove a TDFOL goal using CEC's inference rules.
        
        Args:
            goal: Goal formula to prove
            axioms: List of axiom formulas
            timeout_ms: Timeout in milliseconds
        
        Returns:
            ProofResult with proof status and steps
        """
        if not self.cec_available:
            return ProofResult(
                status=ProofStatus.UNKNOWN,
                formula=goal,
                time_ms=0,
                method="cec_integration",
                message="CEC not available"
            )
        
        import time
        start_time = time.time()
        
        # Convert TDFOL formulas to DCEC strings
        try:
            goal_dcec = self.tdfol_to_dcec_string(goal)
            axioms_dcec = [self.tdfol_to_dcec_string(ax) for ax in axioms]
            
            logger.debug(f"Goal in DCEC: {goal_dcec}")
            logger.debug(f"Axioms in DCEC: {axioms_dcec}")
            
            # Parse DCEC strings to Formula objects
            from ..CEC.native import dcec_parsing
            
            try:
                goal_formula = dcec_parsing.parse_dcec_formula(goal_dcec)
                axiom_formulas = [dcec_parsing.parse_dcec_formula(ax) for ax in axioms_dcec]
            except Exception as e:
                logger.error(f"Failed to parse DCEC formulas: {e}")
                elapsed_ms = (time.time() - start_time) * 1000
                return ProofResult(
                    status=ProofStatus.ERROR,
                    formula=goal,
                    time_ms=elapsed_ms,
                    method="cec_integration",
                    message=f"DCEC parsing error: {e}"
                )
            
            # Create CEC prover instance
            cec_prover = prover_core.Prover(
                timeout_ms=timeout_ms,
                max_depth=100,  # Maximum proof depth
                enable_logging=False  # Disable verbose logging
            )
            
            # Add axioms to prover's knowledge base
            for ax_formula in axiom_formulas:
                cec_prover.add_axiom(ax_formula)
            
            logger.info(f"Attempting CEC proof with {len(axiom_formulas)} axioms")
            
            # Attempt proof using CEC's 87 inference rules
            cec_result = cec_prover.prove(goal_formula)
            
            elapsed_ms = (time.time() - start_time) * 1000
            
            # Convert CEC proof result to TDFOL ProofResult
            if cec_result.result == prover_core.ProofResult.PROVED:
                # Extract proof steps
                proof_steps = []
                for i, cec_step in enumerate(cec_result.proof_tree.steps):
                    step = ProofStep(
                        step_number=i + 1,
                        formula=goal,  # Simplified - could convert each step
                        rule_name=cec_step.rule,
                        premises=cec_step.premises,
                        justification=f"CEC rule: {cec_step.rule}"
                    )
                    proof_steps.append(step)
                
                logger.info(f"CEC proof succeeded with {len(proof_steps)} steps")
                
                return ProofResult(
                    status=ProofStatus.PROVED,
                    formula=goal,
                    time_ms=elapsed_ms,
                    method="cec_integration",
                    proof_steps=proof_steps,
                    message=f"Proved using CEC with {len(proof_steps)} inference steps"
                )
                
            elif cec_result.result == prover_core.ProofResult.DISPROVED:
                return ProofResult(
                    status=ProofStatus.DISPROVED,
                    formula=goal,
                    time_ms=elapsed_ms,
                    method="cec_integration",
                    message="Formula disproved by CEC"
                )
                
            elif cec_result.result == prover_core.ProofResult.TIMEOUT:
                return ProofResult(
                    status=ProofStatus.TIMEOUT,
                    formula=goal,
                    time_ms=elapsed_ms,
                    method="cec_integration",
                    message=f"CEC proving timed out after {timeout_ms}ms"
                )
                
            else:  # UNKNOWN or ERROR
                return ProofResult(
                    status=ProofStatus.UNKNOWN,
                    formula=goal,
                    time_ms=elapsed_ms,
                    method="cec_integration",
                    message=f"CEC could not determine proof status: {cec_result.result.value}"
                )
            
        except Exception as e:
            elapsed_ms = (time.time() - start_time) * 1000
            return ProofResult(
                status=ProofStatus.ERROR,
                formula=goal,
                time_ms=elapsed_ms,
                method="cec_integration",
                message=f"Error during CEC proving: {e}"
            )
    
    def get_applicable_cec_rules(self, formula: Formula) -> List[Any]:
        """
        Get CEC rules applicable to a given formula.
        
        Args:
            formula: TDFOL formula
        
        Returns:
            List of applicable CEC rules
        """
        if not self.cec_available:
            return []
        
        applicable = []
        
        # Convert formula to DCEC
        try:
            dcec_str = self.tdfol_to_dcec_string(formula)
            
            # Check each CEC rule
            for rule in self.cec_rules:
                # Check if rule is applicable
                # This is a placeholder - actual implementation would check rule preconditions
                applicable.append(rule)
        
        except Exception as e:
            logger.debug(f"Error checking rule applicability: {e}")
        
        return applicable


class EnhancedTDFOLProver(TDFOLProver):
    """
    Enhanced TDFOL prover with CEC integration.
    
    This prover can use both TDFOL's 40 rules and CEC's 87 rules,
    providing a total of 127 inference rules.
    """
    
    def __init__(self, kb=None, use_cec: bool = True):
        """
        Initialize enhanced prover.
        
        Args:
            kb: TDFOL knowledge base
            use_cec: Whether to use CEC integration
        """
        super().__init__(kb)
        
        self.use_cec = use_cec
        self.cec_bridge = None
        
        if use_cec:
            self.cec_bridge = TDFOLCECBridge()
            if self.cec_bridge.cec_available:
                logger.info("Enhanced TDFOL Prover with CEC integration (127 total rules)")
            else:
                logger.info("Enhanced TDFOL Prover (40 TDFOL rules only)")
        else:
            logger.info("TDFOL Prover (40 rules)")
    
    def prove(self, goal: Formula, timeout_ms: int = 5000, use_cec: Optional[bool] = None) -> ProofResult:
        """
        Prove a goal using TDFOL + CEC rules.
        
        Args:
            goal: Goal formula to prove
            timeout_ms: Timeout in milliseconds
            use_cec: Override to use/not use CEC (None = use instance setting)
        
        Returns:
            ProofResult
        """
        # First try TDFOL's own prover
        result = super().prove(goal, timeout_ms)
        
        if result.status == ProofStatus.PROVED:
            return result
        
        # If TDFOL didn't prove it and CEC is available, try with CEC
        should_use_cec = use_cec if use_cec is not None else self.use_cec
        
        if should_use_cec and self.cec_bridge and self.cec_bridge.cec_available:
            logger.debug("TDFOL proof unsuccessful, trying with CEC rules")
            
            axioms = list(self.kb.axioms) + list(self.kb.theorems)
            cec_result = self.cec_bridge.prove_with_cec(goal, axioms, timeout_ms)
            
            if cec_result.status == ProofStatus.PROVED:
                return cec_result
        
        return result


# Convenience function
def create_enhanced_prover(use_cec: bool = True) -> EnhancedTDFOLProver:
    """
    Create an enhanced TDFOL prover with optional CEC integration.
    
    Args:
        use_cec: Whether to enable CEC integration (127 total rules)
    
    Returns:
        EnhancedTDFOLProver instance
    
    Example:
        >>> prover = create_enhanced_prover(use_cec=True)
        >>> result = prover.prove(goal_formula)
    """
    return EnhancedTDFOLProver(use_cec=use_cec)
