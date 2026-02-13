"""
Cognitive Event Calculus (CEC) Framework

This module provides a unified neurosymbolic framework for Cognitive Event Calculus,
integrating multiple theorem provers and converters:

- DCEC_Library: Deontic Cognitive Event Calculus logic system
- Talos: Theorem prover interface with SPASS
- Eng-DCEC: English to DCEC converter using Grammatical Framework
- ShadowProver: Shadow theorem prover

The framework provides a high-level API for:
1. Converting natural language to formal logic
2. Building logical knowledge bases
3. Automated theorem proving
4. Neurosymbolic reasoning combining symbolic logic with AI
"""

from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass
from enum import Enum
import logging
from pathlib import Path

from .dcec_wrapper import DCECLibraryWrapper, DCECStatement
from .talos_wrapper import TalosWrapper, ProofAttempt, ProofResult
from .eng_dcec_wrapper import EngDCECWrapper, ConversionResult
from .shadow_prover_wrapper import ShadowProverWrapper, ProofTask, ProverStatus

try:
    from beartype import beartype  # type: ignore
except ImportError:  # pragma: no cover
    def beartype(func):  # type: ignore
        return func

logger = logging.getLogger(__name__)


class ReasoningMode(Enum):
    """Enumeration of reasoning modes."""
    SIMULTANEOUS = "simultaneous"  # Simultaneous reasoning
    TEMPORAL = "temporal"  # Temporal reasoning
    HYBRID = "hybrid"  # Combination of both


@dataclass
class FrameworkConfig:
    """Configuration for the CEC framework."""
    use_dcec: bool = True
    use_talos: bool = True
    use_eng_dcec: bool = True
    use_shadow_prover: bool = False
    reasoning_mode: ReasoningMode = ReasoningMode.SIMULTANEOUS
    gf_server_url: Optional[str] = None
    spass_path: Optional[str] = None
    shadow_prover_path: Optional[Path] = None
    shadow_prover_docker: bool = False


@dataclass
class ReasoningTask:
    """Represents a complete reasoning task."""
    natural_language: str
    dcec_formula: Optional[str] = None
    proof_result: Optional[ProofResult] = None
    conversion_result: Optional[ConversionResult] = None
    proof_attempt: Optional[ProofAttempt] = None
    shadow_proof: Optional[ProofTask] = None
    success: bool = False
    error_message: Optional[str] = None


class CECFramework:
    """
    Unified Cognitive Event Calculus Framework.
    
    This framework provides a complete neurosymbolic reasoning system
    that combines natural language understanding, formal logic, and
    automated theorem proving.
    
    Attributes:
        config: Framework configuration
        dcec_wrapper: DCEC Library wrapper
        talos_wrapper: Talos prover wrapper
        eng_dcec_wrapper: Eng-DCEC converter wrapper
        shadow_prover_wrapper: ShadowProver wrapper
        reasoning_tasks: History of reasoning tasks
    """
    
    def __init__(self, config: Optional[FrameworkConfig] = None):
        """
        Initialize the CEC Framework.
        
        Args:
            config: Optional framework configuration
        """
        self.config = config or FrameworkConfig()
        
        # Initialize wrappers
        self.dcec_wrapper: Optional[DCECLibraryWrapper] = None
        self.talos_wrapper: Optional[TalosWrapper] = None
        self.eng_dcec_wrapper: Optional[EngDCECWrapper] = None
        self.shadow_prover_wrapper: Optional[ShadowProverWrapper] = None
        
        self.reasoning_tasks: List[ReasoningTask] = []
        self._initialized = False
    
    @beartype
    def initialize(self) -> Dict[str, bool]:
        """
        Initialize all enabled components of the framework.
        
        Returns:
            Dictionary mapping component names to initialization status
        """
        results = {}
        
        # Initialize DCEC Library
        if self.config.use_dcec:
            self.dcec_wrapper = DCECLibraryWrapper()
            results["dcec"] = self.dcec_wrapper.initialize()
        
        # Initialize Talos
        if self.config.use_talos:
            self.talos_wrapper = TalosWrapper(spass_path=self.config.spass_path)
            results["talos"] = self.talos_wrapper.initialize()
        
        # Initialize Eng-DCEC
        if self.config.use_eng_dcec:
            self.eng_dcec_wrapper = EngDCECWrapper(gf_server_url=self.config.gf_server_url)
            results["eng_dcec"] = self.eng_dcec_wrapper.initialize()
        
        # Initialize ShadowProver
        if self.config.use_shadow_prover:
            self.shadow_prover_wrapper = ShadowProverWrapper(
                prover_path=self.config.shadow_prover_path,
                use_docker=self.config.shadow_prover_docker
            )
            results["shadow_prover"] = self.shadow_prover_wrapper.initialize()
        
        self._initialized = any(results.values())
        
        if self._initialized:
            logger.info(f"CEC Framework initialized. Components: {results}")
        else:
            logger.error("Failed to initialize any CEC Framework components")
        
        return results
    
    @beartype
    def convert_natural_language(self, text: str) -> ConversionResult:
        """
        Convert natural language to DCEC formula.
        
        Args:
            text: Natural language text
            
        Returns:
            ConversionResult object
        """
        if not self.eng_dcec_wrapper:
            logger.error("Eng-DCEC not available")
            return ConversionResult(
                english_text=text,
                success=False,
                error_message="Eng-DCEC not initialized"
            )
        
        return self.eng_dcec_wrapper.convert_to_dcec(text)
    
    @beartype
    def add_knowledge(self, statement: str, is_natural_language: bool = False) -> bool:
        """
        Add knowledge to the framework.
        
        Args:
            statement: Statement in DCEC format or natural language
            is_natural_language: If True, convert from natural language first
            
        Returns:
            bool: True if knowledge was added successfully
        """
        if not self.dcec_wrapper:
            logger.error("DCEC Library not available")
            return False
        
        dcec_statement = statement
        
        # Convert if needed
        if is_natural_language and self.eng_dcec_wrapper:
            conversion = self.eng_dcec_wrapper.convert_to_dcec(statement)
            if not conversion.success:
                logger.error(f"Failed to convert natural language: {statement}")
                return False
            dcec_statement = conversion.dcec_formula or statement
        
        # Add to DCEC container
        result = self.dcec_wrapper.add_statement(dcec_statement)
        return result.is_valid
    
    @beartype
    def prove_theorem(
        self,
        conjecture: str,
        axioms: Optional[List[str]] = None,
        use_temporal: bool = False,
        use_shadow_prover: bool = False
    ) -> ProofAttempt:
        """
        Attempt to prove a theorem.
        
        Args:
            conjecture: The theorem to prove
            axioms: Optional list of axioms
            use_temporal: If True, use temporal reasoning rules
            use_shadow_prover: If True, also try ShadowProver
            
        Returns:
            ProofAttempt object with results
        """
        if not self.talos_wrapper:
            logger.error("Talos not available")
            return ProofAttempt(
                conjecture=conjecture,
                axioms=axioms or [],
                result=ProofResult.ERROR,
                error_message="Talos not initialized"
            )
        
        # Try with Talos
        attempt = self.talos_wrapper.prove_theorem(
            conjecture=conjecture,
            axioms=axioms,
            use_temporal_rules=use_temporal
        )
        
        # Try with ShadowProver if requested and available
        if use_shadow_prover and self.shadow_prover_wrapper:
            try:
                logger.info("Attempting proof with ShadowProver")
                
                # Convert DCEC formula to TPTP format for ShadowProver
                tptp_formula = self._dcec_to_tptp_format(conjecture)
                tptp_axioms = [self._dcec_to_tptp_format(ax) for ax in (axioms or [])]
                
                # Determine appropriate modal logic
                # Use S4 for temporal reasoning, K for non-temporal/basic modal
                # Note: Deontic logic (D) would require detecting deontic operators
                # Currently only temporal vs non-temporal distinction is implemented
                logic_type = "S4" if use_temporal else "K"
                
                # Create proof task for ShadowProver
                shadow_task = ProofTask(
                    name=f"theorem_{hash(conjecture) % 10000}",
                    formula=tptp_formula,
                    assumptions=tptp_axioms,
                    logic=logic_type
                )
                
                # Submit to ShadowProver
                self.shadow_prover_wrapper.submit_proof_task(shadow_task)
                
                # Wait for result (with timeout)
                import time
                timeout = 10.0  # 10 seconds
                start = time.time()
                
                while time.time() - start < timeout:
                    status = self.shadow_prover_wrapper.check_task_status(shadow_task.name)
                    
                    if status == ProverStatus.COMPLETED:
                        # Get the proof result
                        proof = self.shadow_prover_wrapper.get_proof_result(shadow_task.name)
                        
                        if proof and proof.is_successful():
                            logger.info(f"ShadowProver successfully proved theorem with {logic_type} logic")
                            
                            # Update attempt with ShadowProver results
                            if not attempt.proof_found:  # Only if Talos didn't prove it
                                attempt.proof_found = True
                                attempt.method_used = f"shadowprover_{logic_type}"
                                attempt.result = ProofResult.PROVED
                                
                                # Extract proof steps if available
                                if hasattr(proof, 'steps') and proof.steps:
                                    attempt.proof_steps = [str(step) for step in proof.steps]
                            
                            break
                        else:
                            logger.info("ShadowProver could not prove theorem")
                            break
                    
                    elif status == ProverStatus.FAILED:
                        logger.warning("ShadowProver proof attempt failed")
                        break
                    
                    # Still running, wait a bit
                    time.sleep(0.5)
                
                if time.time() - start >= timeout:
                    logger.warning(f"ShadowProver proof timed out after {timeout}s")
                    
            except Exception as e:
                logger.error(f"Error during ShadowProver integration: {e}")
                # Don't fail the whole attempt, just log and continue
        
        return attempt
    
    @beartype
    def reason_about(
        self,
        natural_language: str,
        prove: bool = True,
        axioms: Optional[List[str]] = None
    ) -> ReasoningTask:
        """
        Perform complete reasoning about a natural language statement.
        
        This is the main high-level API that:
        1. Converts natural language to DCEC
        2. Adds to knowledge base
        3. Optionally proves the statement
        
        Args:
            natural_language: Natural language statement
            prove: If True, attempt to prove the statement
            axioms: Optional axioms for proving
            
        Returns:
            ReasoningTask object with complete results
        """
        task = ReasoningTask(natural_language=natural_language)
        
        try:
            # Step 1: Convert to DCEC
            if self.eng_dcec_wrapper:
                conversion = self.convert_natural_language(natural_language)
                task.conversion_result = conversion
                
                if not conversion.success:
                    task.error_message = f"Conversion failed: {conversion.error_message}"
                    self.reasoning_tasks.append(task)
                    return task
                
                task.dcec_formula = conversion.dcec_formula
            else:
                # Assume input is already in DCEC format
                task.dcec_formula = natural_language
            
            # Step 2: Add to knowledge base
            if task.dcec_formula and self.dcec_wrapper:
                self.add_knowledge(task.dcec_formula, is_natural_language=False)
            
            # Step 3: Prove if requested
            if prove and task.dcec_formula and self.talos_wrapper:
                use_temporal = self.config.reasoning_mode in [
                    ReasoningMode.TEMPORAL,
                    ReasoningMode.HYBRID
                ]
                
                proof = self.prove_theorem(
                    conjecture=task.dcec_formula,
                    axioms=axioms,
                    use_temporal=use_temporal
                )
                task.proof_attempt = proof
                task.proof_result = proof.result
            
            task.success = True
            
        except Exception as e:
            logger.error(f"Error during reasoning: {e}")
            task.error_message = str(e)
            task.success = False
        
        self.reasoning_tasks.append(task)
        return task
    
    @beartype
    def batch_reason(
        self,
        statements: List[str],
        prove: bool = True
    ) -> List[ReasoningTask]:
        """
        Perform reasoning on multiple statements.
        
        Args:
            statements: List of natural language statements
            prove: If True, attempt to prove each statement
            
        Returns:
            List of ReasoningTask objects
        """
        return [self.reason_about(stmt, prove=prove) for stmt in statements]
    
    def _dcec_to_tptp_format(self, dcec_formula: str) -> str:
        """
        Convert DCEC formula to TPTP (Thousands of Problems for Theorem Provers) format.
        
        TPTP is a standard format for automated theorem provers. This converts
        basic DCEC syntax to TPTP's first-order logic format.
        
        Args:
            dcec_formula: DCEC formula string
        
        Returns:
            TPTP formatted formula string
        """
        # Simple conversion - in production, would use proper parser
        tptp = dcec_formula
        
        # Convert common operators
        # Logical connectives
        tptp = tptp.replace(" & ", " & ")     # AND (already correct)
        tptp = tptp.replace(" | ", " | ")     # OR (already correct)
        tptp = tptp.replace(" -> ", " => ")   # IMPLIES
        tptp = tptp.replace(" <-> ", " <=> ") # IFF
        tptp = tptp.replace("~", "~")         # NOT (already correct)
        
        # Quantifiers
        tptp = tptp.replace("forall ", "! ")  # Universal
        tptp = tptp.replace("exists ", "? ")  # Existential
        
        # Modal operators to TPTP (use predicate notation)
        # Box (necessity) → box(...)
        tptp = tptp.replace("□(", "box(")
        tptp = tptp.replace("◇(", "diamond(")
        
        # Deontic operators (must come BEFORE temporal since F is ambiguous)
        # In DCEC: O = Obligation, P = Permission, F = Forbidden
        tptp = tptp.replace("O(", "obligated(")
        tptp = tptp.replace("P(", "permitted(")
        # Note: F( for deontic Forbidden comes before temporal F (Eventually)
        # Context-dependent: in pure deontic logic F=Forbidden, in temporal F=Eventually
        # Since this is DCEC (deontic+temporal), we prioritize deontic interpretation
        # For temporal "eventually", use explicit "Eventually(" or different marker
        tptp = tptp.replace("Forbidden(", "forbidden(")
        
        # Temporal operators  
        # Note: F( is ambiguous (could be Forbidden or Eventually)
        # In a proper implementation, would parse AST to distinguish context
        tptp = tptp.replace("G(", "always(")
        tptp = tptp.replace("Eventually(", "eventually(")  # Explicit temporal
        tptp = tptp.replace("X(", "next(")
        
        return tptp
    
    @beartype
    def get_statistics(self) -> Dict[str, Any]:
        """
        Get comprehensive statistics about the framework.
        
        Returns:
            Dictionary with statistics from all components
        """
        stats = {
            "initialized": self._initialized,
            "reasoning_tasks": len(self.reasoning_tasks),
            "successful_tasks": sum(1 for t in self.reasoning_tasks if t.success),
        }
        
        if self.dcec_wrapper:
            stats["dcec"] = {
                "statements": self.dcec_wrapper.get_statements_count()
            }
        
        if self.talos_wrapper:
            stats["talos"] = self.talos_wrapper.get_statistics()
        
        if self.eng_dcec_wrapper:
            stats["eng_dcec"] = self.eng_dcec_wrapper.get_conversion_statistics()
        
        if self.shadow_prover_wrapper:
            stats["shadow_prover"] = self.shadow_prover_wrapper.get_statistics()
        
        return stats
    
    def __repr__(self) -> str:
        """String representation of the framework."""
        status = "initialized" if self._initialized else "not initialized"
        components = []
        if self.dcec_wrapper:
            components.append("DCEC")
        if self.talos_wrapper:
            components.append("Talos")
        if self.eng_dcec_wrapper:
            components.append("Eng-DCEC")
        if self.shadow_prover_wrapper:
            components.append("ShadowProver")
        
        return f"CECFramework(status={status}, components={components}, tasks={len(self.reasoning_tasks)})"
