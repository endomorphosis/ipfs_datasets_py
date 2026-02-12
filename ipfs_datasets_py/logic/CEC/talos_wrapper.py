"""
Talos Theorem Prover Wrapper

This module provides a Python wrapper for the Talos submodule,
which interfaces with the SPASS theorem prover for DCEC formulas.

Talos manages proof generation, proof trees, and interaction with
the SPASS automated theorem prover.

This wrapper now supports both:
1. Native Python 3 theorem prover (preferred, from ipfs_datasets_py.logic.CEC.native)
2. Python 2 submodule fallback (Talos/SPASS)
"""

import sys
import os
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass
from enum import Enum
import logging

# Add Talos to Python path
TALOS_PATH = Path(__file__).parent / "Talos"
if str(TALOS_PATH) not in sys.path:
    sys.path.insert(0, str(TALOS_PATH))

try:
    from beartype import beartype  # type: ignore
except ImportError:  # pragma: no cover
    def beartype(func):  # type: ignore
        return func

logger = logging.getLogger(__name__)


class ProofResult(Enum):
    """Enumeration of possible proof results."""
    PROVED = "proved"
    DISPROVED = "disproved"
    TIMEOUT = "timeout"
    ERROR = "error"
    UNKNOWN = "unknown"


@dataclass
class ProofAttempt:
    """Represents a theorem proving attempt."""
    conjecture: str
    axioms: List[str]
    result: ProofResult
    proof_tree: Optional[Any] = None
    output: Optional[str] = None
    error_message: Optional[str] = None
    execution_time: float = 0.0


class TalosWrapper:
    """
    Wrapper for Talos theorem prover providing a clean Python API.
    
    This wrapper manages theorem proving tasks using SPASS,
    handles proof trees, and provides methods for automated reasoning.
    
    Supports both native Python 3 theorem prover and Python 2 submodule fallback.
    
    Attributes:
        spass_container: The underlying spassContainer instance (if using submodule)
        prover: The native TheoremProver instance (if using native)
        proof_attempts: List of proof attempts
        simultaneous_rules: Dictionary of simultaneous reasoning rules
        temporal_rules: Dictionary of temporal reasoning rules
        use_native: Whether to prefer native Python 3 implementation
        is_native: Whether currently using native implementation
    """
    
    def __init__(self, spass_path: Optional[str] = None, use_native: bool = True):
        """
        Initialize the Talos wrapper.
        
        Args:
            spass_path: Optional path to SPASS executable (for submodule)
            use_native: If True (default), prefer native Python 3 implementation
                       with fallback to submodule. If False, use submodule only.
        """
        self.spass_container = None
        self.prover = None
        self.spass_path = spass_path
        self.proof_attempts: List[ProofAttempt] = []
        self.simultaneous_rules: Dict[str, Tuple[str, List[str]]] = {}
        self.temporal_rules: Dict[str, Tuple[str, List[str]]] = {}
        self._initialized = False
        self.use_native = use_native
        self.is_native = False
        
    @beartype
    def initialize(self) -> bool:
        """
        Initialize the Talos prover and SPASS container.
        
        Attempts to use native Python 3 theorem prover first (if use_native=True),
        then falls back to Python 2 Talos/SPASS if native is unavailable.
        
        Returns:
            bool: True if initialization succeeded, False otherwise
        """
        # Try native implementation first if requested
        if self.use_native:
            try:
                from ipfs_datasets_py.logic.CEC.native import TheoremProver
                
                self.prover = TheoremProver()
                self._initialized = True
                self.is_native = True
                logger.info("Talos wrapper initialized successfully (using native Python 3 prover)")
                return True
                
            except ImportError as e:
                logger.debug(f"Native theorem prover not available: {e}")
                logger.info("Falling back to Talos/SPASS submodule")
            except Exception as e:
                logger.warning(f"Failed to initialize native theorem prover: {e}")
                logger.info("Falling back to Talos/SPASS submodule")
        
        # Fall back to Python 2 submodule
        try:
            # Import Talos modules
            from talos import spassContainer
            
            self.spass_container = spassContainer()
            
            # Load standard rules if available
            if hasattr(self.spass_container, 'simultaneousRules'):
                self.simultaneous_rules = self.spass_container.simultaneousRules
            if hasattr(self.spass_container, 'temporalRules'):
                self.temporal_rules = self.spass_container.temporalRules
                
            self._initialized = True
            self.is_native = False
            logger.info("Talos theorem prover initialized successfully (using Python 2 submodule)")
            return True
            
        except ImportError as e:
            logger.error(f"Failed to import Talos: {e}")
            logger.warning("Talos not available. No theorem prover backend available.")
            self._initialized = False
            self.is_native = False
            return False
        except Exception as e:
            logger.error(f"Failed to initialize Talos: {e}")
            self._initialized = False
            self.is_native = False
            return False
    
    @beartype
    def prove_theorem(
        self,
        conjecture: Any,  # Can be str or Formula object
        axioms: Optional[List[Any]] = None,
        timeout: int = 30,
        use_temporal_rules: bool = False
    ) -> ProofAttempt:
        """
        Attempt to prove a theorem.
        
        Args:
            conjecture: The theorem to prove (string or Formula object)
            axioms: List of axioms to use in the proof (strings or Formula objects)
            timeout: Timeout in seconds for the proof attempt
            use_temporal_rules: Whether to use temporal reasoning rules
            
        Returns:
            ProofAttempt object with results
        """
        if not self._initialized:
            logger.error("Talos not initialized. Call initialize() first.")
            return ProofAttempt(
                conjecture=str(conjecture),
                axioms=[str(a) for a in (axioms or [])],
                result=ProofResult.ERROR,
                error_message="Prover not initialized"
            )
        
        axioms = axioms or []
        
        try:
            if self.is_native:
                # Use native theorem prover
                logger.info(f"Attempting to prove (native): {str(conjecture)[:50]}...")
                
                # Convert to native format if needed
                native_attempt = self.prover.prove_theorem(
                    goal=conjecture,
                    axioms=axioms
                )
                
                # Convert native ProofResult to wrapper ProofResult
                if native_attempt.result.name == "PROVED":
                    result = ProofResult.PROVED
                elif native_attempt.result.name == "DISPROVED":
                    result = ProofResult.DISPROVED
                else:
                    result = ProofResult.UNKNOWN
                
                attempt = ProofAttempt(
                    conjecture=str(conjecture),
                    axioms=[str(a) for a in axioms],
                    result=result,
                    proof_tree=native_attempt.proof_tree,
                    output=str(native_attempt),
                    execution_time=0.0
                )
                
            else:
                # Use Talos/SPASS submodule
                rules = self.temporal_rules if use_temporal_rules else self.simultaneous_rules
                
                logger.info(f"Attempting to prove (submodule): {str(conjecture)[:50]}...")
                
                # Placeholder for actual proof execution
                # The real implementation would call SPASS through Talos
                result = ProofResult.UNKNOWN
                proof_tree = None
                output = ""
                
                attempt = ProofAttempt(
                    conjecture=str(conjecture),
                    axioms=[str(a) for a in axioms],
                    result=result,
                    proof_tree=proof_tree,
                    output=output
                )
            
            self.proof_attempts.append(attempt)
            return attempt
            
        except Exception as e:
            logger.error(f"Error during proof attempt: {e}")
            return ProofAttempt(
                conjecture=str(conjecture),
                axioms=[str(a) for a in axioms],
                result=ProofResult.ERROR,
                error_message=str(e)
            )
    
    @beartype
    def add_axiom(self, name: str, formula: str, dependencies: Optional[List[str]] = None) -> bool:
        """
        Add an axiom to the prover's knowledge base.
        
        Args:
            name: Name/identifier for the axiom
            formula: The axiom formula
            dependencies: List of function/predicate dependencies
            
        Returns:
            bool: True if axiom was added successfully
        """
        if not self._initialized:
            logger.error("Talos not initialized")
            return False
            
        try:
            if hasattr(self.spass_container, 'axioms'):
                self.spass_container.axioms[name] = formula
                logger.info(f"Added axiom: {name}")
                return True
            else:
                logger.warning("SPASS container does not support axioms")
                return False
        except Exception as e:
            logger.error(f"Error adding axiom: {e}")
            return False
    
    @beartype
    def get_proof_tree(self, attempt_index: int = -1) -> Optional[Any]:
        """
        Get the proof tree for a specific proof attempt.
        
        Args:
            attempt_index: Index of the proof attempt (-1 for most recent)
            
        Returns:
            Proof tree object or None if not available
        """
        if not self.proof_attempts:
            logger.warning("No proof attempts available")
            return None
            
        try:
            attempt = self.proof_attempts[attempt_index]
            return attempt.proof_tree
        except IndexError:
            logger.error(f"Invalid proof attempt index: {attempt_index}")
            return None
    
    @beartype
    def get_available_rules(self, temporal: bool = False) -> Dict[str, Tuple[str, List[str]]]:
        """
        Get the available reasoning rules.
        
        Args:
            temporal: If True, return temporal rules; otherwise simultaneous rules
            
        Returns:
            Dictionary of rule names to (formula, dependencies) tuples
        """
        return self.temporal_rules if temporal else self.simultaneous_rules
    
    @beartype
    def format_proof_output(self, attempt: ProofAttempt) -> str:
        """
        Format a proof attempt's output for display.
        
        Args:
            attempt: The proof attempt to format
            
        Returns:
            Formatted string representation
        """
        lines = [
            f"Proof Attempt:",
            f"  Conjecture: {attempt.conjecture[:80]}...",
            f"  Result: {attempt.result.value}",
            f"  Axioms: {len(attempt.axioms)} axiom(s)",
        ]
        
        if attempt.error_message:
            lines.append(f"  Error: {attempt.error_message}")
            
        if attempt.output:
            lines.append(f"  Output: {attempt.output[:200]}...")
            
        return "\n".join(lines)
    
    @beartype
    def get_statistics(self) -> Dict[str, Any]:
        """
        Get statistics about proof attempts.
        
        Returns:
            Dictionary with statistics
        """
        if not self.proof_attempts:
            return {"total_attempts": 0}
            
        results = {}
        for result_type in ProofResult:
            count = sum(1 for a in self.proof_attempts if a.result == result_type)
            results[result_type.value] = count
            
        return {
            "total_attempts": len(self.proof_attempts),
            "results": results,
            "simultaneous_rules": len(self.simultaneous_rules),
            "temporal_rules": len(self.temporal_rules)
        }
    
    @beartype
    def get_backend_info(self) -> Dict[str, Any]:
        """
        Get information about the currently active backend.
        
        Returns:
            Dictionary with backend information
        """
        return {
            "initialized": self._initialized,
            "is_native": self.is_native,
            "backend": "native_python3" if self.is_native else "python2_submodule",
            "use_native_preference": self.use_native,
            "proof_attempts": len(self.proof_attempts)
        }
    
    def __repr__(self) -> str:
        """String representation of the wrapper."""
        status = "initialized" if self._initialized else "not initialized"
        backend = " (native)" if self.is_native else " (submodule)"
        return f"TalosWrapper(status={status}{backend if self._initialized else ''}, attempts={len(self.proof_attempts)})"
