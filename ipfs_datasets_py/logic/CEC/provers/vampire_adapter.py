"""
Vampire Theorem Prover Adapter for CEC (Phase 6 Week 2).

This module provides integration with the Vampire automated theorem prover,
one of the most powerful first-order theorem provers.

Classes:
    VampireAdapter: Main adapter for Vampire prover
    VampireProofResult: Result of Vampire proving attempt

Features:
    - DCEC to TPTP translation
    - Subprocess-based Vampire invocation
    - TPTP format input/output
    - Proof parsing and validation
    - Timeout and resource configuration

Requirements:
    - Vampire binary must be installed and in PATH
    - Install: Download from https://vprover.github.io/

Usage:
    >>> from ipfs_datasets_py.logic.CEC.provers.vampire_adapter import VampireAdapter
    >>> adapter = VampireAdapter()
    >>> result = adapter.prove(formula, axioms)
    >>> result.is_valid
    True
"""

from typing import List, Optional, Dict, Any
from dataclasses import dataclass
import subprocess
import tempfile
import os
import logging
from pathlib import Path

from .tptp_utils import create_tptp_problem
from .z3_adapter import ProofStatus
from ..native.dcec_core import Formula

logger = logging.getLogger(__name__)


@dataclass
class VampireProofResult:
    """Result of Vampire proof attempt.
    
    Attributes:
        status: Proof status
        is_valid: Whether formula is provably valid
        proof_output: Raw Vampire output
        proof_time: Time taken (seconds)
        error_message: Error message if failed
    """
    status: ProofStatus
    is_valid: bool = False
    proof_output: str = ""
    proof_time: float = 0.0
    error_message: Optional[str] = None


class VampireAdapter:
    """
    Adapter for Vampire theorem prover.
    
    Vampire is a first-order theorem prover that excels at
    complex logical reasoning and saturation-based proving.
    
    Attributes:
        vampire_path: Path to Vampire binary
        timeout: Timeout in seconds
        
    Example:
        >>> adapter = VampireAdapter(timeout=30)
        >>> result = adapter.prove(formula, axioms)
        >>> if result.is_valid:
        ...     print("Theorem proved!")
    """
    
    def __init__(
        self,
        vampire_path: str = "vampire",
        timeout: int = 30
    ):
        """Initialize Vampire adapter.
        
        Args:
            vampire_path: Path to Vampire binary (default: "vampire" in PATH)
            timeout: Timeout in seconds (default: 30)
        """
        self.vampire_path = vampire_path
        self.timeout = timeout
        self._check_installation()
    
    def _check_installation(self) -> None:
        """Check if Vampire is installed."""
        try:
            result = subprocess.run(
                [self.vampire_path, "--version"],
                capture_output=True,
                timeout=5
            )
            if result.returncode == 0:
                logger.info(f"Vampire found: {self.vampire_path}")
            else:
                logger.warning(f"Vampire binary found but version check failed")
        except (FileNotFoundError, subprocess.TimeoutExpired):
            logger.warning(f"Vampire not found at: {self.vampire_path}")
    
    def is_available(self) -> bool:
        """Check if Vampire is available.
        
        Returns:
            True if Vampire binary exists
        """
        try:
            result = subprocess.run(
                [self.vampire_path, "--version"],
                capture_output=True,
                timeout=5
            )
            return result.returncode == 0
        except:
            return False
    
    def prove(
        self,
        formula: Formula,
        axioms: Optional[List[Formula]] = None,
        timeout_override: Optional[int] = None
    ) -> VampireProofResult:
        """Prove formula using Vampire.
        
        Args:
            formula: Formula to prove
            axioms: Optional list of axioms
            timeout_override: Optional timeout override
            
        Returns:
            VampireProofResult with proof status
        """
        import time
        start_time = time.time()
        
        try:
            # Create TPTP problem
            tptp_problem = create_tptp_problem(formula, axioms, "vampire_problem")
            
            # Write to temporary file
            with tempfile.NamedTemporaryFile(
                mode='w',
                suffix='.p',
                delete=False
            ) as f:
                f.write(tptp_problem)
                problem_file = f.name
            
            try:
                # Run Vampire
                timeout = timeout_override if timeout_override else self.timeout
                result = subprocess.run(
                    [self.vampire_path, problem_file, f"--time_limit={timeout}"],
                    capture_output=True,
                    text=True,
                    timeout=timeout + 5  # Extra buffer
                )
                
                output = result.stdout
                proof_time = time.time() - start_time
                
                # Parse output
                if "Refutation found" in output or "Theorem" in output:
                    return VampireProofResult(
                        status=ProofStatus.VALID,
                        is_valid=True,
                        proof_output=output,
                        proof_time=proof_time
                    )
                elif "Satisfiable" in output:
                    return VampireProofResult(
                        status=ProofStatus.SATISFIABLE,
                        is_valid=False,
                        proof_output=output,
                        proof_time=proof_time
                    )
                elif "Timeout" in output or "Time limit" in output:
                    return VampireProofResult(
                        status=ProofStatus.TIMEOUT,
                        is_valid=False,
                        proof_output=output,
                        proof_time=proof_time
                    )
                else:
                    return VampireProofResult(
                        status=ProofStatus.UNKNOWN,
                        is_valid=False,
                        proof_output=output,
                        proof_time=proof_time
                    )
            
            finally:
                # Clean up temporary file
                if os.path.exists(problem_file):
                    os.unlink(problem_file)
        
        except subprocess.TimeoutExpired:
            return VampireProofResult(
                status=ProofStatus.TIMEOUT,
                is_valid=False,
                proof_time=time.time() - start_time,
                error_message="Vampire process timed out"
            )
        
        except Exception as e:
            logger.error(f"Vampire error: {e}")
            return VampireProofResult(
                status=ProofStatus.ERROR,
                is_valid=False,
                proof_time=time.time() - start_time,
                error_message=str(e)
            )


def check_vampire_installation() -> bool:
    """Check if Vampire is installed.
    
    Returns:
        True if Vampire is available
    """
    try:
        result = subprocess.run(
            ["vampire", "--version"],
            capture_output=True,
            timeout=5
        )
        return result.returncode == 0
    except:
        return False
