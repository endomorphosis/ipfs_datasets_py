"""
Integration for Vampire and E theorem provers.

This module provides interfaces to external ATP (Automated Theorem Proving)
systems, specifically Vampire and E prover, for enhanced theorem proving capabilities.

Features:
- Vampire prover integration (FOL with equality)
- E prover integration (equational reasoning)
- TPTP format conversion
- Proof certificate extraction
- Timeout and resource management
- Automatic prover selection

Example:
    >>> from ipfs_datasets_py.logic.integration.external_provers import VampireProver, EProver
    >>> 
    >>> # Use Vampire
    >>> vampire = VampireProver(timeout=60)
    >>> result = vampire.prove("∀x (P(x) → Q(x))")
    >>> 
    >>> # Use E prover
    >>> eprover = EProver(timeout=60)
    >>> result = eprover.prove("∀x∀y (R(x,y) → R(y,x))")
"""

import subprocess
import tempfile
import logging
import shutil
from dataclasses import dataclass
from typing import Optional, Dict, Any, List
from pathlib import Path
from enum import Enum

logger = logging.getLogger(__name__)


class ProverStatus(Enum):
    """Theorem prover result status."""
    THEOREM = "theorem"
    SATISFIABLE = "satisfiable"
    UNSATISFIABLE = "unsatisfiable"
    UNKNOWN = "unknown"
    TIMEOUT = "timeout"
    ERROR = "error"


@dataclass
class ProverResult:
    """
    Result from a theorem prover.
    
    Attributes:
        status: Proof status (theorem, sat, unsat, etc.)
        proof: Proof certificate if available
        time: Proof time in seconds
        prover: Name of the prover used
        error: Error message if failed
        statistics: Additional prover statistics
    """
    status: ProverStatus
    proof: Optional[str] = None
    time: float = 0.0
    prover: str = "unknown"
    error: Optional[str] = None
    statistics: Optional[Dict[str, Any]] = None


class VampireProver:
    """
    Interface to the Vampire theorem prover.
    
    Vampire is a powerful first-order logic prover with excellent
    performance on problems with equality.
    
    Args:
        timeout: Proof timeout in seconds (default: 60)
        vampire_path: Path to vampire executable (default: 'vampire')
        strategy: Vampire strategy mode (default: 'casc')
    
    Example:
        >>> vampire = VampireProver(timeout=30)
        >>> result = vampire.prove("∀x (P(x) → Q(x))")
        >>> if result.status == ProverStatus.THEOREM:
        ...     print("Theorem proved!")
    """
    
    def __init__(
        self,
        timeout: int = 60,
        vampire_path: str = 'vampire',
        strategy: str = 'casc'
    ):
        """Initialize Vampire prover."""
        self.timeout = timeout
        self.vampire_path = vampire_path
        self.strategy = strategy
        self._check_availability()
    
    def _check_availability(self) -> bool:
        """Check if Vampire is available."""
        try:
            result = subprocess.run(
                [self.vampire_path, '--version'],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0:
                logger.info(f"Vampire prover found: {self.vampire_path}")
                return True
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass
        
        logger.warning(
            f"Vampire not found at {self.vampire_path}. "
            "Install from: https://vprover.github.io/"
        )
        return False
    
    def _formula_to_tptp(self, formula: str) -> str:
        """Convert formula to TPTP format."""
        # Simple conversion - in production, use proper parser
        tptp = f"""fof(conjecture, conjecture, {formula})."""
        return tptp
    
    def prove(
        self,
        formula: str,
        axioms: Optional[List[str]] = None
    ) -> ProverResult:
        """
        Prove a formula using Vampire.
        
        Args:
            formula: FOL formula to prove
            axioms: Optional list of axioms
        
        Returns:
            ProverResult with proof status and details
        
        Example:
            >>> result = vampire.prove("∀x (P(x) → Q(x))")
            >>> print(result.status)
        """
        import time as time_module
        start_time = time_module.time()
        
        try:
            # Create TPTP problem file
            with tempfile.NamedTemporaryFile(
                mode='w',
                suffix='.p',
                delete=False
            ) as f:
                # Add axioms if provided
                if axioms:
                    for i, axiom in enumerate(axioms):
                        f.write(f"fof(axiom_{i}, axiom, {axiom}).\n")
                
                # Add conjecture
                f.write(self._formula_to_tptp(formula))
                problem_file = f.name
            
            # Run Vampire
            cmd = [
                self.vampire_path,
                '--mode', self.strategy,
                '--time_limit', str(self.timeout),
                problem_file
            ]
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.timeout + 5
            )
            
            elapsed = time_module.time() - start_time
            
            # Parse output
            output = result.stdout
            
            # Check for theorem
            if 'Theorem' in output or 'Refutation found' in output:
                status = ProverStatus.THEOREM
                # Extract proof
                proof = self._extract_proof(output)
            elif 'Satisfiable' in output:
                status = ProverStatus.SATISFIABLE
                proof = None
            elif 'Time limit' in output or 'Timeout' in output:
                status = ProverStatus.TIMEOUT
                proof = None
            else:
                status = ProverStatus.UNKNOWN
                proof = None
            
            # Extract statistics
            stats = self._extract_statistics(output)
            
            return ProverResult(
                status=status,
                proof=proof,
                time=elapsed,
                prover="Vampire",
                statistics=stats
            )
            
        except subprocess.TimeoutExpired:
            return ProverResult(
                status=ProverStatus.TIMEOUT,
                time=self.timeout,
                prover="Vampire"
            )
        except Exception as e:
            logger.error(f"Vampire error: {e}")
            return ProverResult(
                status=ProverStatus.ERROR,
                error=str(e),
                prover="Vampire"
            )
        finally:
            # Cleanup
            try:
                Path(problem_file).unlink()
            except:
                pass
    
    def _extract_proof(self, output: str) -> Optional[str]:
        """Extract proof from Vampire output."""
        lines = output.split('\n')
        proof_lines = []
        in_proof = False
        
        for line in lines:
            if 'Proof' in line or 'Refutation' in line:
                in_proof = True
            if in_proof:
                proof_lines.append(line)
            if in_proof and ('Success' in line or 'PROVED' in line):
                break
        
        return '\n'.join(proof_lines) if proof_lines else None
    
    def _extract_statistics(self, output: str) -> Dict[str, Any]:
        """Extract statistics from Vampire output."""
        stats = {}
        
        # Look for common statistics
        for line in output.split('\n'):
            if 'clauses' in line.lower():
                parts = line.split()
                for i, part in enumerate(parts):
                    if part.isdigit():
                        stats['clauses'] = int(part)
                        break
            if 'inferences' in line.lower():
                parts = line.split()
                for i, part in enumerate(parts):
                    if part.isdigit():
                        stats['inferences'] = int(part)
                        break
        
        return stats


class EProver:
    """
    Interface to the E theorem prover.
    
    E is a high-performance theorem prover for first-order logic
    with equality, particularly strong at equational reasoning.
    
    Args:
        timeout: Proof timeout in seconds (default: 60)
        eprover_path: Path to eprover executable (default: 'eprover')
        auto_mode: Use automatic mode (default: True)
    
    Example:
        >>> eprover = EProver(timeout=30)
        >>> result = eprover.prove("∀x∀y (f(x,y) = f(y,x))")
        >>> print(result.status)
    """
    
    def __init__(
        self,
        timeout: int = 60,
        eprover_path: str = 'eprover',
        auto_mode: bool = True
    ):
        """Initialize E prover."""
        self.timeout = timeout
        self.eprover_path = eprover_path
        self.auto_mode = auto_mode
        self._check_availability()
    
    def _check_availability(self) -> bool:
        """Check if E prover is available."""
        try:
            result = subprocess.run(
                [self.eprover_path, '--version'],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0 or 'E ' in result.stdout:
                logger.info(f"E prover found: {self.eprover_path}")
                return True
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass
        
        logger.warning(
            f"E prover not found at {self.eprover_path}. "
            "Install from: https://wwwlehre.dhbw-stuttgart.de/~sschulz/E/E.html"
        )
        return False
    
    def _formula_to_tptp(self, formula: str) -> str:
        """Convert formula to TPTP format."""
        tptp = f"""fof(conjecture, conjecture, {formula})."""
        return tptp
    
    def prove(
        self,
        formula: str,
        axioms: Optional[List[str]] = None
    ) -> ProverResult:
        """
        Prove a formula using E prover.
        
        Args:
            formula: FOL formula to prove
            axioms: Optional list of axioms
        
        Returns:
            ProverResult with proof status and details
        
        Example:
            >>> result = eprover.prove("∀x (x = x)")
            >>> print(result.status)
        """
        import time as time_module
        start_time = time_module.time()
        
        try:
            # Create TPTP problem file
            with tempfile.NamedTemporaryFile(
                mode='w',
                suffix='.p',
                delete=False
            ) as f:
                # Add axioms
                if axioms:
                    for i, axiom in enumerate(axioms):
                        f.write(f"fof(axiom_{i}, axiom, {axiom}).\n")
                
                # Add conjecture
                f.write(self._formula_to_tptp(formula))
                problem_file = f.name
            
            # Build command
            cmd = [self.eprover_path]
            if self.auto_mode:
                cmd.append('--auto')
            cmd.extend([
                '--cpu-limit=' + str(self.timeout),
                '--proof-object',
                problem_file
            ])
            
            # Run E prover
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.timeout + 5
            )
            
            elapsed = time_module.time() - start_time
            
            # Parse output
            output = result.stdout
            
            # Check status
            if 'Proof found' in output or 'Theorem' in output:
                status = ProverStatus.THEOREM
                proof = self._extract_proof(output)
            elif 'Satisfiable' in output:
                status = ProverStatus.SATISFIABLE
                proof = None
            elif 'ResourceOut' in output or 'Timeout' in output:
                status = ProverStatus.TIMEOUT
                proof = None
            else:
                status = ProverStatus.UNKNOWN
                proof = None
            
            # Extract statistics
            stats = self._extract_statistics(output)
            
            return ProverResult(
                status=status,
                proof=proof,
                time=elapsed,
                prover="E",
                statistics=stats
            )
            
        except subprocess.TimeoutExpired:
            return ProverResult(
                status=ProverStatus.TIMEOUT,
                time=self.timeout,
                prover="E"
            )
        except Exception as e:
            logger.error(f"E prover error: {e}")
            return ProverResult(
                status=ProverStatus.ERROR,
                error=str(e),
                prover="E"
            )
        finally:
            # Cleanup
            try:
                Path(problem_file).unlink()
            except:
                pass
    
    def _extract_proof(self, output: str) -> Optional[str]:
        """Extract proof from E prover output."""
        lines = output.split('\n')
        proof_lines = []
        in_proof = False
        
        for line in lines:
            if '# Proof object' in line:
                in_proof = True
            if in_proof:
                proof_lines.append(line)
            if in_proof and '# Proof object ends' in line:
                break
        
        return '\n'.join(proof_lines) if proof_lines else None
    
    def _extract_statistics(self, output: str) -> Dict[str, Any]:
        """Extract statistics from E prover output."""
        stats = {}
        
        for line in output.split('\n'):
            if 'Processed clauses' in line:
                parts = line.split(':')
                if len(parts) > 1:
                    try:
                        stats['processed_clauses'] = int(parts[1].strip())
                    except:
                        pass
            if 'Generated clauses' in line:
                parts = line.split(':')
                if len(parts) > 1:
                    try:
                        stats['generated_clauses'] = int(parts[1].strip())
                    except:
                        pass
        
        return stats


class ProverRegistry:
    """
    Registry for managing multiple theorem provers.
    
    Provides automatic prover selection based on formula characteristics
    and prover availability.
    
    Example:
        >>> registry = ProverRegistry()
        >>> registry.register(VampireProver())
        >>> registry.register(EProver())
        >>> 
        >>> # Automatic prover selection
        >>> result = registry.prove_auto("∀x P(x)")
    """
    
    def __init__(self):
        """Initialize prover registry."""
        self.provers: Dict[str, Any] = {}
    
    def register(self, prover: Any, name: Optional[str] = None) -> None:
        """
        Register a prover.
        
        Args:
            prover: Prover instance
            name: Optional name (uses prover class name if not provided)
        """
        if name is None:
            name = prover.__class__.__name__
        self.provers[name] = prover
        logger.info(f"Registered prover: {name}")
    
    def get_prover(self, name: str) -> Optional[Any]:
        """Get prover by name."""
        return self.provers.get(name)
    
    def list_provers(self) -> List[str]:
        """List all registered provers."""
        return list(self.provers.keys())
    
    def prove_auto(
        self,
        formula: str,
        axioms: Optional[List[str]] = None,
        prefer: Optional[str] = None
    ) -> ProverResult:
        """
        Automatically select and use best prover for formula.
        
        Args:
            formula: Formula to prove
            axioms: Optional axioms
            prefer: Preferred prover name
        
        Returns:
            Best proof result from available provers
        """
        if not self.provers:
            return ProverResult(
                status=ProverStatus.ERROR,
                error="No provers registered"
            )
        
        # Try preferred prover first
        if prefer and prefer in self.provers:
            result = self.provers[prefer].prove(formula, axioms)
            if result.status == ProverStatus.THEOREM:
                return result
        
        # Try all provers
        best_result = None
        for name, prover in self.provers.items():
            if name == prefer:
                continue  # Already tried
            
            result = prover.prove(formula, axioms)
            
            if result.status == ProverStatus.THEOREM:
                return result  # Found proof, stop
            
            # Track best result so far
            if best_result is None or self._is_better_result(result, best_result):
                best_result = result
        
        return best_result or ProverResult(
            status=ProverStatus.UNKNOWN,
            error="All provers failed"
        )
    
    def _is_better_result(self, r1: ProverResult, r2: ProverResult) -> bool:
        """Compare two results to determine which is better."""
        # Prefer proved over unknown
        if r1.status == ProverStatus.THEOREM and r2.status != ProverStatus.THEOREM:
            return True
        # Prefer faster proofs
        if r1.status == r2.status and r1.time < r2.time:
            return True
        return False


# Global registry
_global_registry: Optional[ProverRegistry] = None


def get_prover_registry() -> ProverRegistry:
    """
    Get or create the global prover registry.
    
    Returns:
        Global ProverRegistry instance
    
    Example:
        >>> registry = get_prover_registry()
        >>> registry.register(VampireProver())
    """
    global _global_registry
    
    if _global_registry is None:
        _global_registry = ProverRegistry()
        
        # Auto-register available provers
        try:
            _global_registry.register(VampireProver())
        except:
            pass
        
        try:
            _global_registry.register(EProver())
        except:
            pass
    
    return _global_registry
