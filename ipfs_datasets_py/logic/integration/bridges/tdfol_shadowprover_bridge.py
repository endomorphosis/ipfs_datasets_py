"""
TDFOL-ShadowProver Integration

This module integrates TDFOL with CEC's ShadowProver for modal logic proving.

Features:
- Use K, S4, S5 modal logic provers for temporal formulas
- Cognitive calculus for belief/knowledge reasoning
- Modal tableaux algorithm for systematic proof search
"""

from __future__ import annotations

import logging
from enum import Enum
from typing import Optional, List, Dict, Any

from ...TDFOL.tdfol_core import (
    Formula,
    TemporalFormula,
    TemporalOperator,
    DeonticFormula,
    DeonticOperator,
)
from ...TDFOL.tdfol_prover import ProofResult, ProofStatus, ProofStep
from .base_prover_bridge import (
    BaseProverBridge,
    BridgeMetadata,
    BridgeCapability
)

logger = logging.getLogger(__name__)

# Try to import ShadowProver components
SHADOWPROVER_AVAILABLE = False
try:
    from ...CEC.native import shadow_prover, modal_tableaux
    SHADOWPROVER_AVAILABLE = True
    logger.info("ShadowProver modules loaded successfully")
except ImportError as e:
    logger.warning(f"ShadowProver modules not available: {e}")


class ModalLogicType(Enum):
    """Modal logic systems supported."""
    K = "K"       # Basic modal logic
    T = "T"       # Reflexive (□p → p)
    S4 = "S4"     # Reflexive + Transitive
    S5 = "S5"     # Equivalence relation
    D = "D"       # Serial (□p → ◊p) - for deontic logic


class TDFOLShadowProverBridge(BaseProverBridge):
    """
    Bridge between TDFOL and ShadowProver.
    
    Enables proving of modal formulas using specialized modal logic provers.
    """
    
    def __init__(self):
        """Initialize the TDFOL-ShadowProver bridge."""
        super().__init__()
        
        if not self.available:
            logger.warning("ShadowProver integration disabled")
            return
        
        # Initialize modal provers
        self.k_prover = None
        self.s4_prover = None
        self.s5_prover = None
        self.cognitive_prover = None
        
        try:
            # Create prover instances
            self.k_prover = shadow_prover.KProver()
            self.s4_prover = shadow_prover.S4Prover()
            self.s5_prover = shadow_prover.S5Prover()
            self.cognitive_prover = shadow_prover.CognitiveCalculusProver()
            
            logger.info("Initialized K, S4, S5, and Cognitive provers")
        except Exception as e:
            logger.warning(f"Failed to initialize shadow provers: {e}")
            self.available = False
    
    def _init_metadata(self) -> BridgeMetadata:
        """Initialize bridge metadata."""
        return BridgeMetadata(
            name="TDFOL-ShadowProver Bridge",
            version="1.0.0",
            target_system="ShadowProver",
            capabilities=[
                BridgeCapability.BIDIRECTIONAL_CONVERSION,
                BridgeCapability.OPTIMIZATION
            ],
            requires_external_prover=False,
            description="Integrates TDFOL with ShadowProver modal logic systems (K, S4, S5)"
        )
    
    def _check_availability(self) -> bool:
        """Check if ShadowProver modules are available."""
        return SHADOWPROVER_AVAILABLE
    
    def to_target_format(self, formula: Formula) -> str:
        """
        Convert TDFOL formula to ShadowProver modal logic format.
        
        Args:
            formula: TDFOL formula
            
        Returns:
            Modal logic string representation
            
        Raises:
            ValueError: If formula cannot be converted
        """
        if not self.is_available():
            raise ValueError("ShadowProver bridge not available")
        
        return self.tdfol_to_modal_string(formula)
    
    def from_target_format(self, target_result: Any) -> ProofResult:
        """
        Convert ShadowProver result to TDFOL ProofResult.
        
        Args:
            target_result: Result from ShadowProver
            
        Returns:
            ProofResult with standardized format
        """
        if isinstance(target_result, ProofResult):
            return target_result
        
        return ProofResult(
            status=ProofStatus.UNKNOWN,
            formula=None,
            time_ms=0,
            method="shadowprover",
            message=f"Converted from ShadowProver result: {target_result}"
        )
    
    def prove(
        self,
        formula: Formula,
        timeout: Optional[int] = None,
        modal_logic: Optional[str] = None,
        **kwargs
    ) -> ProofResult:
        """
        Prove a formula using ShadowProver.
        
        Args:
            formula: TDFOL formula to prove
            timeout: Optional timeout in seconds
            modal_logic: Specific modal logic to use (K/S4/S5)
            **kwargs: Additional parameters
            
        Returns:
            ProofResult with status and details
        """
        return self.prove_modal_formula(formula)
    
    def select_modal_logic(self, formula: Formula) -> ModalLogicType:
        """
        Select appropriate modal logic system for a formula.
        
        Args:
            formula: TDFOL formula
        
        Returns:
            Appropriate modal logic type
        """
        # For temporal formulas, use S4 (good for temporal reasoning)
        if isinstance(formula, TemporalFormula):
            if formula.operator == TemporalOperator.ALWAYS:
                return ModalLogicType.S4  # □ is transitive in temporal logic
            elif formula.operator == TemporalOperator.EVENTUALLY:
                return ModalLogicType.S4
            else:
                return ModalLogicType.K  # Default to K for other temporal
        
        # For deontic formulas, use D (serial property)
        if isinstance(formula, DeonticFormula):
            return ModalLogicType.D  # O(p) → P(p) requires serial
        
        # Default to K (most general)
        return ModalLogicType.K
    
    def prove_modal(
        self,
        formula: Formula,
        logic_type: Optional[ModalLogicType] = None,
        modal_type: Optional[ModalLogicType] = None,  # compat alias for logic_type
        timeout_ms: int = 5000
    ) -> ProofResult:
        """
        Prove a modal formula using ShadowProver.
        
        Args:
            formula: TDFOL formula with modal operators
            logic_type: Modal logic to use (auto-selected if None)
            timeout_ms: Timeout in milliseconds
        
        Returns:
            ProofResult
        """
        if not self.available:
            return ProofResult(
                status=ProofStatus.UNKNOWN,
                formula=formula,
                time_ms=0,
                method="shadowprover",
                message="ShadowProver not available"
            )

        # Resolve modal_type alias
        if modal_type is not None and logic_type is None:
            logic_type = modal_type

        import time
        start_time = time.time()
        
        # Auto-select logic if not specified
        if logic_type is None:
            logic_type = self.select_modal_logic(formula)
        
        logger.debug(f"Using modal logic: {logic_type.value}")
        
        # Select appropriate prover
        prover = self._get_prover(logic_type)
        if prover is None:
            elapsed_ms = (time.time() - start_time) * 1000
            return ProofResult(
                status=ProofStatus.ERROR,
                formula=formula,
                time_ms=elapsed_ms,
                method="shadowprover",
                message=f"No prover available for {logic_type.value}"
            )
        
        try:
            # Convert TDFOL formula to modal logic string format
            modal_formula_str = self._tdfol_to_modal_format(formula)
            
            logger.debug(f"Converted to modal format: {modal_formula_str}")
            
            # Attempt proof using selected prover
            timeout_sec = timeout_ms / 1000.0
            
            proof_tree = prover.prove(
                goal=modal_formula_str,
                assumptions=None,
                timeout=int(timeout_sec)
            )
            
            elapsed_ms = (time.time() - start_time) * 1000
            
            # Convert proof result to TDFOL ProofResult
            if proof_tree.status == shadow_prover.ProofStatus.SUCCESS:
                # Extract proof steps
                proof_steps = []
                for i, sp_step in enumerate(proof_tree.steps):
                    step = ProofStep(
                        formula=formula,
                        rule_name=sp_step.rule_name,
                        premises=[],  # Could extract from sp_step.premises
                        justification=sp_step.justification or f"Modal rule: {sp_step.rule_name}"
                    )
                    proof_steps.append(step)
                
                logger.info(f"ShadowProver {logic_type.value} proof succeeded with {len(proof_steps)} steps")
                
                return ProofResult(
                    status=ProofStatus.PROVED,
                    formula=formula,
                    time_ms=elapsed_ms,
                    method=f"shadowprover_{logic_type.value}",
                    proof_steps=proof_steps,
                    message=f"Proved using {logic_type.value} modal logic with {len(proof_steps)} steps"
                )
                
            elif proof_tree.status == shadow_prover.ProofStatus.FAILURE:
                return ProofResult(
                    status=ProofStatus.DISPROVED,
                    formula=formula,
                    time_ms=elapsed_ms,
                    method=f"shadowprover_{logic_type.value}",
                    message=f"Formula refuted in {logic_type.value} modal logic"
                )
                
            elif proof_tree.status == shadow_prover.ProofStatus.TIMEOUT:
                return ProofResult(
                    status=ProofStatus.TIMEOUT,
                    formula=formula,
                    time_ms=elapsed_ms,
                    method=f"shadowprover_{logic_type.value}",
                    message=f"Proof timed out after {timeout_ms}ms"
                )
                
            else:  # UNKNOWN or ERROR
                return ProofResult(
                    status=ProofStatus.UNKNOWN,
                    formula=formula,
                    time_ms=elapsed_ms,
                    method=f"shadowprover_{logic_type.value}",
                    message=f"Could not determine proof status: {proof_tree.status.value}"
                )
            
        except Exception as e:
            elapsed_ms = (time.time() - start_time) * 1000
            return ProofResult(
                status=ProofStatus.ERROR,
                formula=formula,
                time_ms=elapsed_ms,
                method="shadowprover",
                message=f"Error during modal proving: {e}"
            )
    
    def _get_prover(self, logic_type: ModalLogicType):
        """Get prover instance for a modal logic type."""
        if logic_type == ModalLogicType.K:
            return self.k_prover
        elif logic_type == ModalLogicType.S4:
            return self.s4_prover
        elif logic_type == ModalLogicType.S5:
            return self.s5_prover
        elif logic_type == ModalLogicType.D:
            # D logic is a variant of K, use K prover
            return self.k_prover
        elif logic_type == ModalLogicType.T:
            # T is subset of S4, use S4 prover
            return self.s4_prover
        else:
            return self.k_prover  # Default
    
    def prove_with_tableaux(
        self,
        formula: Formula,
        timeout_ms: int = 5000
    ) -> ProofResult:
        """
        Prove formula using modal tableaux algorithm.
        
        Args:
            formula: TDFOL formula
            timeout_ms: Timeout in milliseconds
        
        Returns:
            ProofResult
        """
        if not self.available:
            return ProofResult(
                status=ProofStatus.UNKNOWN,
                formula=formula,
                time_ms=0,
                method="modal_tableaux",
                message="Modal tableaux not available"
            )
        
        import time
        start_time = time.time()
        
        try:
            # Create tableaux prover with appropriate logic
            logic_type = self.select_modal_logic(formula)
            modal_logic = self._modal_logic_type_to_enum(logic_type)
            
            tableaux_prover = modal_tableaux.TableauProver(modal_logic)
            
            # Convert formula to modal format
            modal_formula_str = self._tdfol_to_modal_format(formula)
            
            logger.debug(f"Attempting tableaux proof for: {modal_formula_str}")
            
            # Attempt proof using tableau method
            success, tableau = tableaux_prover.prove(modal_formula_str, assumptions=None)
            
            elapsed_ms = (time.time() - start_time) * 1000
            
            # Convert tableau result to ProofResult
            if success:
                # Extract proof steps from tableau
                proof_steps = []
                for i, sp_step in enumerate(tableau.proof_steps):
                    step = ProofStep(
                        step_number=i + 1,
                        formula=formula,
                        rule_name=sp_step.rule_name,
                        premises=[],
                        justification=sp_step.justification or f"Tableau rule: {sp_step.rule_name}"
                    )
                    proof_steps.append(step)
                
                logger.info(f"Modal tableaux proof succeeded with {len(proof_steps)} steps")
                
                return ProofResult(
                    status=ProofStatus.PROVED,
                    formula=formula,
                    time_ms=elapsed_ms,
                    method="modal_tableaux",
                    proof_steps=proof_steps,
                    message=f"Proved using modal tableaux with {len(proof_steps)} steps ({tableau.world_counter} worlds)"
                )
            else:
                return ProofResult(
                    status=ProofStatus.DISPROVED,
                    formula=formula,
                    time_ms=elapsed_ms,
                    method="modal_tableaux",
                    message=f"Formula refuted by modal tableaux (tableau remained open)"
                )
            
        except Exception as e:
            elapsed_ms = (time.time() - start_time) * 1000
            return ProofResult(
                status=ProofStatus.ERROR,
                formula=formula,
                time_ms=elapsed_ms,
                method="modal_tableaux",
                message=f"Error during tableaux proving: {e}"
            )
    
    def _tdfol_to_modal_format(self, formula: Formula) -> str:
        """
        Convert TDFOL formula to modal logic string format.
        
        Note: This is a simplified string-based conversion with known limitations.
        It performs global string replacements which may not correctly handle:
        - Complex nested formulas where operator context matters
        - Function/predicate arguments that get mixed with logical connectives
        
        For production use with complex formulas, consider implementing proper
        AST traversal to emit correct modal syntax while preserving predicate structure.
        
        Args:
            formula: TDFOL formula
        
        Returns:
            Modal logic string (with □, ◊, etc.)
        """
        # Get the string representation
        formula_str = formula.to_string()
        
        # Replace TDFOL operators with modal logic symbols
        # Temporal operators
        formula_str = formula_str.replace("Always(", "□(")
        formula_str = formula_str.replace("Eventually(", "◊(")
        formula_str = formula_str.replace("Next(", "X(")
        formula_str = formula_str.replace("Until(", "U(")
        
        # Deontic operators (map to modal)
        formula_str = formula_str.replace("Obligatory(", "□(")  # Obligation as necessity
        formula_str = formula_str.replace("Permitted(", "◊(")   # Permission as possibility
        
        # Logical connectives
        # Note: These simplified replacements work for basic formulas but may
        # not correctly handle all cases (e.g., mixing connective operators with
        # predicate arguments). A proper implementation would use AST traversal.
        formula_str = formula_str.replace("And(", "∧(")
        formula_str = formula_str.replace("Or(", "∨(")
        formula_str = formula_str.replace("Not(", "¬(")
        formula_str = formula_str.replace("Implies(", "→(")
        
        return formula_str
    
    def _modal_logic_type_to_enum(self, logic_type: ModalLogicType) -> 'shadow_prover.ModalLogic':
        """
        Convert ModalLogicType enum to shadow_prover.ModalLogic enum.
        
        Args:
            logic_type: Bridge's modal logic type
        
        Returns:
            ShadowProver's ModalLogic enum
        """
        if logic_type == ModalLogicType.K:
            return shadow_prover.ModalLogic.K
        elif logic_type == ModalLogicType.T:
            return shadow_prover.ModalLogic.T
        elif logic_type == ModalLogicType.S4:
            return shadow_prover.ModalLogic.S4
        elif logic_type == ModalLogicType.S5:
            return shadow_prover.ModalLogic.S5
        elif logic_type == ModalLogicType.D:
            return shadow_prover.ModalLogic.D
        else:
            return shadow_prover.ModalLogic.K  # Default


class ModalAwareTDFOLProver:
    """
    TDFOL Prover with modal logic awareness.
    
    Automatically routes modal formulas to appropriate specialized provers:
    - Temporal formulas → ShadowProver with S4
    - Deontic formulas → ShadowProver with D
    - Mixed formulas → Tableaux algorithm
    """
    
    def __init__(self):
        """Initialize modal-aware prover."""
        from ...TDFOL.tdfol_prover import TDFOLProver
        from ...TDFOL.tdfol_core import TDFOLKnowledgeBase
        
        self.base_prover = TDFOLProver(TDFOLKnowledgeBase())
        self.shadow_bridge = TDFOLShadowProverBridge()
        
        if self.shadow_bridge.available:
            logger.info("Modal-aware TDFOL Prover initialized with ShadowProver support")
        else:
            logger.info("Modal-aware TDFOL Prover initialized (ShadowProver unavailable)")
    
    def prove(
        self,
        formula: Formula,
        timeout_ms: int = 5000,
        use_modal_specialized: bool = True
    ) -> ProofResult:
        """
        Prove formula with automatic modal logic handling.
        
        Args:
            formula: TDFOL formula
            timeout_ms: Timeout in milliseconds
            use_modal_specialized: Use specialized modal provers
        
        Returns:
            ProofResult
        """
        # Check if formula has modal operators
        has_temporal = self._has_temporal_operators(formula)
        has_deontic = self._has_deontic_operators(formula)
        
        # If modal formula and specialized provers available, use them
        if use_modal_specialized and self.shadow_bridge.available:
            if has_temporal or has_deontic:
                logger.debug("Routing modal formula to ShadowProver")
                result = self.shadow_bridge.prove_modal(formula, timeout_ms=timeout_ms)
                
                # If ShadowProver succeeded, return
                if result.status == ProofStatus.PROVED:
                    return result
                
                # Otherwise, fall through to base prover
                logger.debug("ShadowProver unsuccessful, trying base prover")
        
        # Use base TDFOL prover
        return self.base_prover.prove(formula, timeout_ms)
    
    def _has_temporal_operators(self, formula: Formula) -> bool:
        """Check if formula contains temporal operators."""
        if isinstance(formula, TemporalFormula):
            return True
        
        # Check recursively in compound formulas
        if hasattr(formula, 'formula'):
            return self._has_temporal_operators(formula.formula)
        
        if hasattr(formula, 'left') and hasattr(formula, 'right'):
            return (self._has_temporal_operators(formula.left) or
                    self._has_temporal_operators(formula.right))
        
        return False
    
    def _has_deontic_operators(self, formula: Formula) -> bool:
        """Check if formula contains deontic operators."""
        if isinstance(formula, DeonticFormula):
            return True
        
        # Check recursively
        if hasattr(formula, 'formula'):
            return self._has_deontic_operators(formula.formula)
        
        if hasattr(formula, 'left') and hasattr(formula, 'right'):
            return (self._has_deontic_operators(formula.left) or
                    self._has_deontic_operators(formula.right))
        
        return False


# Convenience function
def create_modal_aware_prover() -> ModalAwareTDFOLProver:
    """
    Create a modal-aware TDFOL prover.
    
    This prover automatically uses specialized modal logic provers
    (K, S4, S5, D) for formulas with temporal/deontic operators.
    
    Returns:
        ModalAwareTDFOLProver instance
    
    Example:
        >>> prover = create_modal_aware_prover()
        >>> result = prover.prove(temporal_formula)
    """
    return ModalAwareTDFOLProver()
