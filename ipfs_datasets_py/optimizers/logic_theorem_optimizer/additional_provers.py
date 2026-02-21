"""Additional Theorem Prover Integrations for Logic Optimizer.

This module provides integration with additional powerful theorem provers:
- Isabelle/HOL: Higher-order logic theorem prover
- Vampire: First-order automated theorem prover  
- E Prover: Equational theorem prover

These provers complement the existing Z3, CVC5, Lean, Coq, and SymbolicAI provers
to provide comprehensive coverage of different logic types and proof strategies.

Usage:
    >>> from ipfs_datasets_py.optimizers.logic_theorem_optimizer import (
    ...     IsabelleProver, VampireProver, EProver
    ... )
    >>> 
    >>> # Use Isabelle for HOL
    >>> isabelle = IsabelleProver()
    >>> result = isabelle.prove("∀x. P(x) → Q(x)")
    >>> 
    >>> # Use Vampire for FOL
    >>> vampire = VampireProver()
    >>> result = vampire.prove_fof("fof(axiom1, axiom, ...)") 
    >>> 
    >>> # Use E for equational logic
    >>> e_prover = EProver()
    >>> result = e_prover.prove_cnf("cnf(...)")
"""

from __future__ import annotations

import logging
import os
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional
import hashlib

logger = logging.getLogger(__name__)


class ProverType(Enum):
    """Type of theorem prover."""
    ISABELLE = "isabelle"
    VAMPIRE = "vampire"
    E_PROVER = "e_prover"


class ProofFormat(Enum):
    """Format for proof problems."""
    HOL = "hol"  # Higher-order logic (Isabelle)
    FOF = "fof"  # First-order form (TPTP)
    TFF = "tff"  # Typed first-order form (TPTP)
    CNF = "cnf"  # Conjunctive normal form
    THF = "thf"  # Typed higher-order form


@dataclass
class ProverResult:
    """Result from a theorem prover.
    
    Attributes:
        prover_name: Name of the prover used
        is_proved: True if theorem was proved
        confidence: Confidence score (0.0-1.0)
        proof_time: Time taken (seconds)
        proof_output: Raw output from prover
        proof_certificate: Proof certificate/trace if available
        error_message: Error message if proof failed
        timeout: True if prover timed out
    """
    prover_name: str
    is_proved: bool
    confidence: float
    proof_time: float
    proof_output: str = ""
    proof_certificate: Optional[str] = None
    error_message: Optional[str] = None
    timeout: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)


class IsabelleProver:
    """Isabelle/HOL theorem prover integration.
    
    Isabelle is a generic proof assistant that supports higher-order logic (HOL).
    It's particularly strong for:
    - Mathematical proofs
    - Program verification
    - Complex type theory
    - Interactive and automated proving
    
    This integration uses Isabelle's command-line interface to:
    1. Generate theory files from formulas
    2. Execute isabelle process on the theory
    3. Parse proof results
    
    Example:
        >>> prover = IsabelleProver(isabelle_path="/usr/bin/isabelle")
        >>> result = prover.prove("∀x. P(x) → Q(x)", timeout=10.0)
        >>> if result.is_proved:
        ...     print(f"Proved in {result.proof_time:.2f}s")
    """
    
    def __init__(
        self,
        isabelle_path: str = "isabelle",
        enable_cache: bool = True,
        default_timeout: float = 30.0
    ):
        """Initialize Isabelle prover.
        
        Args:
            isabelle_path: Path to isabelle executable
            enable_cache: Whether to cache proof results
            default_timeout: Default timeout for proofs (seconds)
        """
        self.isabelle_path = isabelle_path
        self.enable_cache = enable_cache
        self.default_timeout = default_timeout
        self.proof_cache: Dict[str, ProverResult] = {}
        self._check_availability()
    
    def _check_availability(self) -> bool:
        """Check if Isabelle is available."""
        try:
            result = subprocess.run(
                [self.isabelle_path, "version"],
                capture_output=True,
                timeout=5.0,
                text=True
            )
            return result.returncode == 0
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            logger.warning(f"Isabelle not found at: {self.isabelle_path}")
            return False
    
    def prove(
        self,
        formula: str,
        timeout: Optional[float] = None,
        use_sledgehammer: bool = True
    ) -> ProverResult:
        """Prove a formula using Isabelle/HOL.
        
        Args:
            formula: Formula in Isabelle/HOL syntax
            timeout: Timeout for proof (uses default if None)
            use_sledgehammer: Whether to use Sledgehammer automation
            
        Returns:
            ProverResult with proof status and details
        """
        timeout = timeout or self.default_timeout
        start_time = time.time()
        
        # Check cache
        if self.enable_cache:
            cache_key = self._get_cache_key(formula)
            if cache_key in self.proof_cache:
                cached = self.proof_cache[cache_key]
                logger.debug(f"Cache hit for Isabelle proof: {cache_key[:8]}")
                return cached
        
        try:
            # Generate Isabelle theory file
            theory_content = self._generate_theory(formula, use_sledgehammer)
            
            # Write to temporary file
            with tempfile.NamedTemporaryFile(
                mode='w',
                suffix='.thy',
                delete=False
            ) as f:
                f.write(theory_content)
                theory_file = f.name
            
            try:
                # Run Isabelle process
                result = subprocess.run(
                    [self.isabelle_path, "process", "-T", theory_file],
                    capture_output=True,
                    timeout=timeout,
                    text=True
                )
                
                proof_time = time.time() - start_time
                
                # Parse result
                is_proved = self._parse_result(result.stdout, result.stderr)
                confidence = 1.0 if is_proved else 0.0
                
                prover_result = ProverResult(
                    prover_name="isabelle",
                    is_proved=is_proved,
                    confidence=confidence,
                    proof_time=proof_time,
                    proof_output=result.stdout,
                    proof_certificate=result.stdout if is_proved else None,
                    error_message=result.stderr if not is_proved else None,
                    timeout=False,
                    metadata={"theory_file": theory_file, "use_sledgehammer": use_sledgehammer}
                )
                
                # Cache result
                if self.enable_cache:
                    self.proof_cache[cache_key] = prover_result
                
                return prover_result
                
            finally:
                # Cleanup
                try:
                    os.unlink(theory_file)
                except OSError:
                    pass
                    
        except subprocess.TimeoutExpired:
            proof_time = time.time() - start_time
            return ProverResult(
                prover_name="isabelle",
                is_proved=False,
                confidence=0.0,
                proof_time=proof_time,
                proof_output="",
                error_message=f"Timeout after {timeout}s",
                timeout=True
            )
        except Exception as e:
            proof_time = time.time() - start_time
            return ProverResult(
                prover_name="isabelle",
                is_proved=False,
                confidence=0.0,
                proof_time=proof_time,
                proof_output="",
                error_message=str(e),
                timeout=False
            )
    
    def _generate_theory(self, formula: str, use_sledgehammer: bool) -> str:
        """Generate Isabelle theory file from formula.
        
        Args:
            formula: Formula in HOL syntax
            use_sledgehammer: Whether to include Sledgehammer command
            
        Returns:
            Theory file content
        """
        sledgehammer_cmd = "sledgehammer" if use_sledgehammer else ""
        
        return f"""theory GeneratedProof
  imports Main
begin

theorem to_prove: "{formula}"
  {sledgehammer_cmd}
  by auto

end
"""
    
    def _parse_result(self, stdout: str, stderr: str) -> bool:
        """Parse Isabelle output to determine proof status.
        
        Args:
            stdout: Standard output from Isabelle
            stderr: Standard error from Isabelle
            
        Returns:
            True if proof succeeded
        """
        # Look for success indicators
        success_indicators = [
            "No errors",
            "Finished theory",
            "by auto",
            "by sledgehammer"
        ]
        
        # Look for error indicators
        error_indicators = [
            "error:",
            "Failed to",
            "Cannot",
            "Undefined"
        ]
        
        has_success = any(ind in stdout for ind in success_indicators)
        has_error = any(ind in stderr or ind in stdout for ind in error_indicators)
        
        return has_success and not has_error
    
    def _get_cache_key(self, formula: str) -> str:
        """Generate cache key for formula."""
        return hashlib.sha256(formula.encode()).hexdigest()


class VampireProver:
    """Vampire automated theorem prover integration.
    
    Vampire is a highly efficient first-order automated theorem prover.
    It excels at:
    - First-order logic with equality
    - TPTP problem format
    - Competition-level performance
    - Proof certificate generation
    
    This integration:
    1. Converts formulas to TPTP FOF/TFF format
    2. Invokes vampire command-line tool
    3. Parses proof results and certificates
    
    Example:
        >>> prover = VampireProver()
        >>> result = prover.prove_fof("fof(axiom, axiom, p(a)).\\nfof(goal, conjecture, q(a)).")
        >>> print(f"Proved: {result.is_proved}")
    """
    
    def __init__(
        self,
        vampire_path: str = "vampire",
        enable_cache: bool = True,
        default_timeout: float = 10.0
    ):
        """Initialize Vampire prover.
        
        Args:
            vampire_path: Path to vampire executable
            enable_cache: Whether to cache proof results
            default_timeout: Default timeout (seconds)
        """
        self.vampire_path = vampire_path
        self.enable_cache = enable_cache
        self.default_timeout = default_timeout
        self.proof_cache: Dict[str, ProverResult] = {}
        self._check_availability()
    
    def _check_availability(self) -> bool:
        """Check if Vampire is available."""
        try:
            result = subprocess.run(
                [self.vampire_path, "--version"],
                capture_output=True,
                timeout=5.0,
                text=True
            )
            return result.returncode == 0
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            logger.warning(f"Vampire not found at: {self.vampire_path}")
            return False
    
    def prove_fof(
        self,
        problem: str,
        timeout: Optional[float] = None,
        proof_output: bool = True
    ) -> ProverResult:
        """Prove a problem in TPTP FOF format.
        
        Args:
            problem: Problem in TPTP FOF format
            timeout: Timeout for proof
            proof_output: Whether to generate proof output
            
        Returns:
            ProverResult with proof status
        """
        timeout = timeout or self.default_timeout
        start_time = time.time()
        
        # Check cache
        if self.enable_cache:
            cache_key = self._get_cache_key(problem)
            if cache_key in self.proof_cache:
                return self.proof_cache[cache_key]
        
        try:
            # Write problem to temporary file
            with tempfile.NamedTemporaryFile(
                mode='w',
                suffix='.p',
                delete=False
            ) as f:
                f.write(problem)
                problem_file = f.name
            
            try:
                # Build vampire command
                cmd = [
                    self.vampire_path,
                    problem_file,
                    "-t", str(int(timeout)),
                ]
                
                if proof_output:
                    cmd.append("--proof")
                
                # Run Vampire
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    timeout=timeout + 1.0,  # Add buffer
                    text=True
                )
                
                proof_time = time.time() - start_time
                
                # Parse result
                is_proved, certificate = self._parse_vampire_output(
                    result.stdout,
                    result.stderr
                )
                
                prover_result = ProverResult(
                    prover_name="vampire",
                    is_proved=is_proved,
                    confidence=1.0 if is_proved else 0.0,
                    proof_time=proof_time,
                    proof_output=result.stdout,
                    proof_certificate=certificate,
                    error_message=result.stderr if not is_proved else None,
                    timeout=False,
                    metadata={"problem_file": problem_file}
                )
                
                # Cache result
                if self.enable_cache:
                    self.proof_cache[cache_key] = prover_result
                
                return prover_result
                
            finally:
                # Cleanup
                try:
                    os.unlink(problem_file)
                except OSError:
                    pass
                    
        except subprocess.TimeoutExpired:
            proof_time = time.time() - start_time
            return ProverResult(
                prover_name="vampire",
                is_proved=False,
                confidence=0.0,
                proof_time=proof_time,
                proof_output="",
                error_message=f"Timeout after {timeout}s",
                timeout=True
            )
        except Exception as e:
            proof_time = time.time() - start_time
            return ProverResult(
                prover_name="vampire",
                is_proved=False,
                confidence=0.0,
                proof_time=proof_time,
                proof_output="",
                error_message=str(e),
                timeout=False
            )
    
    def _parse_vampire_output(
        self,
        stdout: str,
        stderr: str
    ) -> tuple[bool, Optional[str]]:
        """Parse Vampire output.
        
        Args:
            stdout: Standard output
            stderr: Standard error
            
        Returns:
            Tuple of (is_proved, proof_certificate)
        """
        # Check for success
        is_proved = "% Refutation found" in stdout or "% Theorem" in stdout
        
        # Extract proof certificate
        certificate = None
        if is_proved:
            if "% Proof:" in stdout:
                start = stdout.find("% Proof:")
                end = stdout.find("% SZS output end", start)
                if start != -1:
                    if end != -1:
                        certificate = stdout[start:end]
                    else:
                        certificate = stdout[start:]
            else:
                # If no explicit proof section, use the whole output
                certificate = stdout
        
        return is_proved, certificate
    
    def _get_cache_key(self, problem: str) -> str:
        """Generate cache key."""
        return hashlib.sha256(problem.encode()).hexdigest()


class EProver:
    """E equational theorem prover integration.
    
    E is a high-performance theorem prover for first-order logic with equality.
    It specializes in:
    - Equational reasoning
    - Unit equality
    - CNF problems
    - Superposition calculus
    
    This integration:
    1. Accepts formulas in TPTP CNF/FOF format
    2. Runs E prover command-line tool
    3. Parses proof results
    
    Example:
        >>> prover = EProver()
        >>> result = prover.prove_cnf("cnf(a1, axiom, p(a)).\\ncnf(goal, negated_conjecture, ~p(a)).")
        >>> print(f"Refutation found: {result.is_proved}")
    """
    
    def __init__(
        self,
        eprover_path: str = "eprover",
        enable_cache: bool = True,
        default_timeout: float = 10.0
    ):
        """Initialize E prover.
        
        Args:
            eprover_path: Path to eprover executable
            enable_cache: Whether to cache results
            default_timeout: Default timeout (seconds)
        """
        self.eprover_path = eprover_path
        self.enable_cache = enable_cache
        self.default_timeout = default_timeout
        self.proof_cache: Dict[str, ProverResult] = {}
        self._check_availability()
    
    def _check_availability(self) -> bool:
        """Check if E prover is available."""
        try:
            result = subprocess.run(
                [self.eprover_path, "--version"],
                capture_output=True,
                timeout=5.0,
                text=True
            )
            return result.returncode == 0
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            logger.warning(f"E prover not found at: {self.eprover_path}")
            return False
    
    def prove_cnf(
        self,
        problem: str,
        timeout: Optional[float] = None,
        auto_mode: bool = True
    ) -> ProverResult:
        """Prove a problem in CNF format.
        
        Args:
            problem: Problem in TPTP CNF format
            timeout: Timeout for proof
            auto_mode: Use automatic mode selection
            
        Returns:
            ProverResult with proof status
        """
        timeout = timeout or self.default_timeout
        start_time = time.time()
        
        # Check cache
        if self.enable_cache:
            cache_key = self._get_cache_key(problem)
            if cache_key in self.proof_cache:
                return self.proof_cache[cache_key]
        
        try:
            # Write problem to file
            with tempfile.NamedTemporaryFile(
                mode='w',
                suffix='.p',
                delete=False
            ) as f:
                f.write(problem)
                problem_file = f.name
            
            try:
                # Build command
                cmd = [
                    self.eprover_path,
                    "--cpu-limit=" + str(int(timeout)),
                    "--proof-object"
                ]
                
                if auto_mode:
                    cmd.append("--auto")
                
                cmd.append(problem_file)
                
                # Run E prover
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    timeout=timeout + 1.0,
                    text=True
                )
                
                proof_time = time.time() - start_time
                
                # Parse result
                is_proved, certificate = self._parse_eprover_output(
                    result.stdout,
                    result.stderr
                )
                
                prover_result = ProverResult(
                    prover_name="e_prover",
                    is_proved=is_proved,
                    confidence=1.0 if is_proved else 0.0,
                    proof_time=proof_time,
                    proof_output=result.stdout,
                    proof_certificate=certificate,
                    error_message=result.stderr if not is_proved else None,
                    timeout=False,
                    metadata={"problem_file": problem_file, "auto_mode": auto_mode}
                )
                
                # Cache result
                if self.enable_cache:
                    self.proof_cache[cache_key] = prover_result
                
                return prover_result
                
            finally:
                # Cleanup
                try:
                    os.unlink(problem_file)
                except OSError:
                    pass
                    
        except subprocess.TimeoutExpired:
            proof_time = time.time() - start_time
            return ProverResult(
                prover_name="e_prover",
                is_proved=False,
                confidence=0.0,
                proof_time=proof_time,
                proof_output="",
                error_message=f"Timeout after {timeout}s",
                timeout=True
            )
        except Exception as e:
            proof_time = time.time() - start_time
            return ProverResult(
                prover_name="e_prover",
                is_proved=False,
                confidence=0.0,
                proof_time=proof_time,
                proof_output="",
                error_message=str(e),
                timeout=False
            )
    
    def _parse_eprover_output(
        self,
        stdout: str,
        stderr: str
    ) -> tuple[bool, Optional[str]]:
        """Parse E prover output.
        
        Args:
            stdout: Standard output
            stderr: Standard error
            
        Returns:
            Tuple of (is_proved, proof_certificate)
        """
        # Check for proof
        is_proved = (
            "# Proof found!" in stdout or
            "# SZS status Theorem" in stdout or
            "# SZS status Unsatisfiable" in stdout
        )
        
        # Extract certificate
        certificate = None
        if is_proved and "# Proof object" in stdout:
            start = stdout.find("# Proof object")
            end = stdout.find("# SZS output end", start)
            if start != -1 and end != -1:
                certificate = stdout[start:end]
        
        return is_proved, certificate
    
    def _get_cache_key(self, problem: str) -> str:
        """Generate cache key."""
        return hashlib.sha256(problem.encode()).hexdigest()


class AdditionalProversRegistry:
    """Registry for managing additional theorem provers.
    
    This registry provides a unified interface for accessing
    Isabelle, Vampire, and E prover instances. It handles:
    - Prover availability checking
    - Instance creation and caching
    - Automatic selection based on problem type
    
    Example:
        >>> registry = AdditionalProversRegistry()
        >>> if registry.is_available("vampire"):
        ...     prover = registry.get_prover("vampire")
        ...     result = prover.prove_fof(problem)
    """
    
    def __init__(self):
        """Initialize prover registry."""
        self._provers: Dict[str, Any] = {}
        self._availability: Dict[str, bool] = {}
        self._check_all_provers()
    
    def _check_all_provers(self):
        """Check availability of all provers."""
        try:
            isabelle = IsabelleProver()
            self._availability["isabelle"] = True
        except (OSError, ImportError, RuntimeError) as e:
            self._log.debug(f"Isabelle prover not available: {e}")
            self._availability["isabelle"] = False
        
        try:
            vampire = VampireProver()
            self._availability["vampire"] = True
        except (OSError, ImportError, RuntimeError) as e:
            self._log.debug(f"Vampire prover not available: {e}")
            self._availability["vampire"] = False
        
        try:
            e_prover = EProver()
            self._availability["e_prover"] = True
        except (OSError, ImportError, RuntimeError) as e:
            self._log.debug(f"E prover not available: {e}")
            self._availability["e_prover"] = False
    
    def is_available(self, prover_name: str) -> bool:
        """Check if a prover is available.
        
        Args:
            prover_name: Name of prover (isabelle, vampire, e_prover)
            
        Returns:
            True if prover is available
        """
        return self._availability.get(prover_name, False)
    
    def get_prover(self, prover_name: str) -> Any:
        """Get prover instance.
        
        Args:
            prover_name: Name of prover
            
        Returns:
            Prover instance
            
        Raises:
            ValueError: If prover not available
        """
        if not self.is_available(prover_name):
            raise ValueError(f"Prover {prover_name} is not available")
        
        # Return cached instance
        if prover_name in self._provers:
            return self._provers[prover_name]
        
        # Create new instance
        if prover_name == "isabelle":
            prover = IsabelleProver()
        elif prover_name == "vampire":
            prover = VampireProver()
        elif prover_name == "e_prover":
            prover = EProver()
        else:
            raise ValueError(f"Unknown prover: {prover_name}")
        
        self._provers[prover_name] = prover
        return prover
    
    def get_available_provers(self) -> List[str]:
        """Get list of available provers.
        
        Returns:
            List of prover names that are available
        """
        return [name for name, avail in self._availability.items() if avail]
    
    def get_recommended_prover(
        self,
        problem_type: ProofFormat
    ) -> Optional[str]:
        """Get recommended prover for problem type.
        
        Args:
            problem_type: Type of problem
            
        Returns:
            Recommended prover name or None
        """
        recommendations = {
            ProofFormat.HOL: "isabelle",
            ProofFormat.THF: "isabelle",
            ProofFormat.FOF: "vampire",
            ProofFormat.TFF: "vampire",
            ProofFormat.CNF: "e_prover"
        }
        
        recommended = recommendations.get(problem_type)
        if recommended and self.is_available(recommended):
            return recommended
        
        # Fallback to any available prover
        available = self.get_available_provers()
        return available[0] if available else None
