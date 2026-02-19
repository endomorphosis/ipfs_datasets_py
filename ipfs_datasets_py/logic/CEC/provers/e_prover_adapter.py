"""
E Theorem Prover Adapter for CEC (Phase 6 Week 2).

This module provides integration with the E automated theorem prover,
an efficient theorem prover based on the superposition calculus.

Classes:
    EProverAdapter: Main adapter for E prover
    EProverProofResult: Result of E proving attempt

Features:
    - DCEC to TPTP translation
    - Subprocess-based E prover invocation
    - TPTP format input/output
    - Proof parsing and validation
    - Timeout and resource configuration
    - Strategy selection (auto, default, heuristic)

Requirements:
    - E prover binary must be installed and in PATH
    - Install: Download from https://wwwlehre.dhbw-stuttgart.de/~sschulz/E/E.html

Usage:
    >>> from ipfs_datasets_py.logic.CEC.provers.e_prover_adapter import EProverAdapter
    >>> adapter = EProverAdapter()
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
class EProverProofResult:
    """Result of E prover attempt.
    
    Attributes:
        status: Proof status
        is_valid: Whether formula is provably valid
        proof_output: Raw E prover output
        proof_time: Time taken (seconds)
        error_message: Error message if failed
        strategy_used: Strategy used by E prover
    """
    status: ProofStatus
    is_valid: bool = False
    proof_output: str = ""
    proof_time: float = 0.0
    error_message: Optional[str] = None
    strategy_used: str = "auto"


class EProverAdapter:
    """
    Adapter for E theorem prover.
    
    E is a high-performance theorem prover that uses
    superposition calculus for equational logic.
    
    Attributes:
        eprover_path: Path to E prover binary
        timeout: Timeout in seconds
        strategy: Proof strategy
        
    Example:
        >>> adapter = EProverAdapter(timeout=30, strategy="auto")
        >>> result = adapter.prove(formula, axioms)
        >>> if result.is_valid:
        ...     print("Proof found!")
    """
    
    def __init__(
        self,
        eprover_path: str = "eprover",
        timeout: int = 30,
        strategy: str = "auto"
    ):
        """Initialize E prover adapter.
        
        Args:
            eprover_path: Path to E binary (default: "eprover" in PATH)
            timeout: Timeout in seconds (default: 30)
            strategy: Proof strategy (default: "auto")
        """
        self.eprover_path = eprover_path
        self.timeout = timeout
        self.strategy = strategy
        self._check_installation()
    
    def _check_installation(self) -> None:
        """Check if E prover is installed."""
        try:
            result = subprocess.run(
                [self.eprover_path, "--version"],
                capture_output=True,
                timeout=5
            )
            if result.returncode == 0:
                logger.info(f"E prover found: {self.eprover_path}")
            else:
                logger.warning(f"E prover binary found but version check failed")
        except (FileNotFoundError, subprocess.TimeoutExpired):
            logger.warning(f"E prover not found at: {self.eprover_path}")
    
    def is_available(self) -> bool:
        """Check if E prover is available.
        
        Returns:
            True if E prover binary exists
        """
        try:
            result = subprocess.run(
                [self.eprover_path, "--version"],
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
        timeout_override: Optional[int] = None,
        strategy_override: Optional[str] = None
    ) -> EProverProofResult:
        """Prove formula using E prover.
        
        Args:
            formula: Formula to prove
            axioms: Optional list of axioms
            timeout_override: Optional timeout override
            strategy_override: Optional strategy override
            
        Returns:
            EProverProofResult with proof status
        """
        import time
        start_time = time.time()
        
        try:
            # Create TPTP problem
            tptp_problem = create_tptp_problem(formula, axioms, "eprover_problem")
            
            # Write to temporary file
            with tempfile.NamedTemporaryFile(
                mode='w',
                suffix='.p',
                delete=False
            ) as f:
                f.write(tptp_problem)
                problem_file = f.name
            
            try:
                # Prepare command
                timeout = timeout_override if timeout_override else self.timeout
                strategy = strategy_override if strategy_override else self.strategy
                
                cmd = [self.eprover_path, problem_file, f"--cpu-limit={timeout}"]
                
                # Add strategy if not auto
                if strategy != "auto":
                    cmd.append(f"--auto-schedule={strategy}")
                
                # Run E prover
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=timeout + 5  # Extra buffer
                )
                
                output = result.stdout
                proof_time = time.time() - start_time
                
                # Parse output
                if "Proof found" in output or "Theorem" in output:
                    return EProverProofResult(
                        status=ProofStatus.VALID,
                        is_valid=True,
                        proof_output=output,
                        proof_time=proof_time,
                        strategy_used=strategy
                    )
                elif "Satisfiable" in output or "Completion found" in output:
                    return EProverProofResult(
                        status=ProofStatus.SATISFIABLE,
                        is_valid=False,
                        proof_output=output,
                        proof_time=proof_time,
                        strategy_used=strategy
                    )
                elif "Timeout" in output or "Time limit" in output:
                    return EProverProofResult(
                        status=ProofStatus.TIMEOUT,
                        is_valid=False,
                        proof_output=output,
                        proof_time=proof_time,
                        strategy_used=strategy
                    )
                else:
                    return EProverProofResult(
                        status=ProofStatus.UNKNOWN,
                        is_valid=False,
                        proof_output=output,
                        proof_time=proof_time,
                        strategy_used=strategy
                    )
            
            finally:
                # Clean up temporary file
                if os.path.exists(problem_file):
                    os.unlink(problem_file)
        
        except subprocess.TimeoutExpired:
            return EProverProofResult(
                status=ProofStatus.TIMEOUT,
                is_valid=False,
                proof_time=time.time() - start_time,
                error_message="E prover process timed out",
                strategy_used=strategy_override or self.strategy
            )
        
        except Exception as e:
            logger.error(f"E prover error: {e}")
            return EProverProofResult(
                status=ProofStatus.ERROR,
                is_valid=False,
                proof_time=time.time() - start_time,
                error_message=str(e),
                strategy_used=strategy_override or self.strategy
            )


def check_eprover_installation() -> bool:
    """Check if E prover is installed.
    
    Returns:
        True if E prover is available
    """
    try:
        result = subprocess.run(
            ["eprover", "--version"],
            capture_output=True,
            timeout=5
        )
        return result.returncode == 0
    except:
        return False
