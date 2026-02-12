"""
ShadowProver Wrapper

This module provides a unified wrapper for ShadowProver that prefers the native
Python 3 implementation and falls back to the Java submodule if needed.

The native implementation provides:
- Modal logic proving (K, S4, S5)
- Cognitive calculus
- Tableau-based algorithms
- Problem file parsing (TPTP, custom formats)
"""

import sys
import os
from pathlib import Path
from typing import Dict, List, Optional, Any, Union
from dataclasses import dataclass
from enum import Enum
import logging
import subprocess

# ShadowProver path
SHADOW_PROVER_PATH = Path(__file__).parent / "ShadowProver"

try:
    from beartype import beartype  # type: ignore
except ImportError:  # pragma: no cover
    def beartype(func):  # type: ignore
        return func

# Try to import native implementation
try:
    from ..native import (
        create_prover,
        create_cognitive_prover,
        ModalLogic,
        ProofTree,
        ProofStatus as NativeProofStatus,
        parse_problem_file,
        SHADOWPROVER_AVAILABLE as NATIVE_AVAILABLE
    )
    NATIVE_AVAILABLE = True
except ImportError:
    NATIVE_AVAILABLE = False

logger = logging.getLogger(__name__)


class ProverStatus(Enum):
    """Enumeration of prover status."""
    SUCCESS = "success"
    FAILURE = "failure"
    TIMEOUT = "timeout"
    ERROR = "error"
    UNKNOWN = "unknown"


@dataclass
class ProofTask:
    """Represents a proof task for ShadowProver."""
    problem_file: str
    result: Optional[ProverStatus] = None
    output: Optional[str] = None
    execution_time: float = 0.0
    error_message: Optional[str] = None
    native_used: bool = False


class ShadowProverWrapper:
    """
    Unified wrapper for ShadowProver with native and Java implementations.
    
    This wrapper prefers the native Python 3 implementation for:
    - Better performance
    - No external dependencies
    - Easier debugging
    - Type safety
    
    Falls back to Java implementation if:
    - Native is not available
    - Specific features are needed
    - User explicitly requests Java
    
    Attributes:
        prover_path: Path to ShadowProver installation
        proof_tasks: List of proof tasks
        use_docker: Whether to use Docker for running the prover
        prefer_native: Whether to prefer native implementation (default: True)
    """
    
    def __init__(
        self,
        prover_path: Optional[Path] = None,
        use_docker: bool = False,
        prefer_native: bool = True
    ):
        """
        Initialize the ShadowProver wrapper.
        
        Args:
            prover_path: Optional path to ShadowProver directory
            use_docker: If True, use Docker to run ShadowProver
            prefer_native: If True, prefer native implementation (default: True)
        """
        self.prover_path = prover_path or SHADOW_PROVER_PATH
        self.use_docker = use_docker
        self.prefer_native = prefer_native and NATIVE_AVAILABLE
        self.proof_tasks: List[ProofTask] = []
        self._initialized = False
        self._native_prover = None
        
        if self.prefer_native and NATIVE_AVAILABLE:
            logger.info("Native ShadowProver implementation will be preferred")
        else:
            logger.info("Java ShadowProver implementation will be used")
        
    @beartype
    def initialize(self) -> bool:
        """
        Initialize the ShadowProver.
        
        For native implementation, this always succeeds.
        For Java implementation, checks that ShadowProver is available.
        
        Returns:
            bool: True if initialization succeeded, False otherwise
        """
        if self.prefer_native and NATIVE_AVAILABLE:
            self._initialized = True
            logger.info("Native ShadowProver initialized")
            return True
            
        try:
            # Check if ShadowProver directory exists
            if not self.prover_path.exists():
                logger.error(f"ShadowProver path does not exist: {self.prover_path}")
                return False
            
            # Check for run script or Docker
            run_script = self.prover_path / "run_shadowprover.sh"
            docker_compose = self.prover_path / "docker-compose.yml"
            
            if self.use_docker and docker_compose.exists():
                logger.info("ShadowProver will be run using Docker")
                self._initialized = True
                return True
            elif run_script.exists():
                logger.info("ShadowProver run script found")
                self._initialized = True
                return True
            else:
                logger.warning("ShadowProver run script not found")
                # Still mark as initialized to allow other operations
                self._initialized = True
                return True
                
        except Exception as e:
            logger.error(f"Failed to initialize ShadowProver: {e}")
            self._initialized = False
            return False
    
    @beartype
    def prove_problem(
        self,
        problem_file: str,
        timeout: int = 60,
        logic: Optional[str] = None
    ) -> ProofTask:
        """
        Attempt to prove a problem using ShadowProver.
        
        Uses native implementation if available and preferred,
        otherwise falls back to Java implementation.
        
        Args:
            problem_file: Path to the problem file (TPTP or custom format)
            timeout: Timeout in seconds
            logic: Optional logic system ('K', 'S4', 'S5', 'cognitive')
            
        Returns:
            ProofTask object with results
        """
        if not self._initialized:
            logger.error("ShadowProver not initialized. Call initialize() first.")
            return ProofTask(
                problem_file=problem_file,
                result=ProverStatus.ERROR,
                error_message="Prover not initialized"
            )
        
        # Try native implementation first if preferred
        if self.prefer_native and NATIVE_AVAILABLE:
            try:
                return self._prove_with_native(problem_file, logic)
            except Exception as e:
                logger.warning(f"Native proving failed: {e}, falling back to Java")
        
        # Fall back to Java implementation
        task = ProofTask(problem_file=problem_file)
        
        try:
            if self.use_docker:
                result = self._run_docker_proof(problem_file, timeout)
            else:
                result = self._run_direct_proof(problem_file, timeout)
            
            task.result = result.get("status", ProverStatus.ERROR)
            task.output = result.get("output", "")
            task.execution_time = result.get("time", 0.0)
            task.error_message = result.get("error")
            
            self.proof_tasks.append(task)
            return task
            
        except Exception as e:
            logger.error(f"Error during proof: {e}")
            task.result = ProverStatus.ERROR
            task.error_message = str(e)
            self.proof_tasks.append(task)
            return task
    
    def _run_docker_proof(self, problem_file: str, timeout: int) -> Dict[str, Any]:
        """
        Run proof using Docker.
        
        Args:
            problem_file: Path to problem file
            timeout: Timeout in seconds
            
        Returns:
            Dictionary with proof results
        """
        try:
            cmd = [
                "docker-compose",
                "-f", str(self.prover_path / "docker-compose.yml"),
                "run", "--rm",
                "shadowprover",
                problem_file
            ]
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=str(self.prover_path)
            )
            
            if result.returncode == 0:
                return {
                    "status": ProverStatus.SUCCESS,
                    "output": result.stdout,
                    "time": 0.0  # Would need to parse from output
                }
            else:
                return {
                    "status": ProverStatus.FAILURE,
                    "output": result.stdout,
                    "error": result.stderr
                }
                
        except subprocess.TimeoutExpired:
            return {
                "status": ProverStatus.TIMEOUT,
                "error": f"Proof timed out after {timeout} seconds"
            }
        except Exception as e:
            return {
                "status": ProverStatus.ERROR,
                "error": str(e)
            }
    
    def _run_direct_proof(self, problem_file: str, timeout: int) -> Dict[str, Any]:
        """
        Run proof directly using run script.
        
        Args:
            problem_file: Path to problem file
            timeout: Timeout in seconds
            
        Returns:
            Dictionary with proof results
        """
        try:
            run_script = self.prover_path / "run_shadowprover.sh"
            
            if not run_script.exists():
                return {
                    "status": ProverStatus.ERROR,
                    "error": "Run script not found"
                }
            
            cmd = [str(run_script), problem_file]
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=str(self.prover_path)
            )
            
            if result.returncode == 0:
                return {
                    "status": ProverStatus.SUCCESS,
                    "output": result.stdout,
                    "time": 0.0
                }
            else:
                return {
                    "status": ProverStatus.FAILURE,
                    "output": result.stdout,
                    "error": result.stderr
                }
                
        except subprocess.TimeoutExpired:
            return {
                "status": ProverStatus.TIMEOUT,
                "error": f"Proof timed out after {timeout} seconds"
            }
        except Exception as e:
            return {
                "status": ProverStatus.ERROR,
                "error": str(e)
            }
    
    @beartype
    def get_statistics(self) -> Dict[str, Any]:
        """
        Get statistics about proof tasks.
        
        Returns:
            Dictionary with statistics
        """
        if not self.proof_tasks:
            return {"total_tasks": 0}
        
        stats = {
            "total_tasks": len(self.proof_tasks),
            "success": 0,
            "failure": 0,
            "timeout": 0,
            "error": 0,
            "total_time": 0.0
        }
        
        for task in self.proof_tasks:
            if task.result:
                stats[task.result.value] += 1
            stats["total_time"] += task.execution_time
        
        if stats["total_tasks"] > 0:
            stats["average_time"] = stats["total_time"] / stats["total_tasks"]
        
        return stats
    
    @beartype
    def list_problem_files(self) -> List[str]:
        """
        List available problem files in the ShadowProver problems directory.
        
        Returns:
            List of problem file paths
        """
        problems_dir = self.prover_path / "problems"
        if not problems_dir.exists():
            logger.warning("Problems directory not found")
            return []
        
        problem_files = []
        for file_path in problems_dir.rglob("*.p"):
            problem_files.append(str(file_path.relative_to(self.prover_path)))
        
        return sorted(problem_files)
    
    def __repr__(self) -> str:
        """String representation of the wrapper."""
        status = "initialized" if self._initialized else "not initialized"
        mode = "docker" if self.use_docker else "direct"
        return f"ShadowProverWrapper(status={status}, mode={mode}, tasks={len(self.proof_tasks)})"
    
    def _prove_with_native(
        self,
        problem_file: str,
        logic: Optional[str] = None
    ) -> ProofTask:
        """Prove using native Python 3 implementation.
        
        Args:
            problem_file: Path to problem file
            logic: Optional logic system
            
        Returns:
            ProofTask with results
        """
        import time
        
        task = ProofTask(problem_file=problem_file, native_used=True)
        
        try:
            # Parse problem file
            problem = parse_problem_file(problem_file)
            
            # Determine logic
            if logic:
                logic_map = {
                    'K': ModalLogic.K,
                    'S4': ModalLogic.S4,
                    'S5': ModalLogic.S5,
                    'cognitive': ModalLogic.S5,  # Use S5 as base
                }
                modal_logic = logic_map.get(logic.upper(), problem.logic)
            else:
                modal_logic = problem.logic
            
            # Create prover
            if logic and logic.lower() == 'cognitive':
                prover = create_cognitive_prover()
            else:
                prover = create_prover(modal_logic)
            
            # Prove all goals
            start_time = time.time()
            results = []
            
            for goal in problem.goals:
                proof = prover.prove(goal, problem.assumptions)
                results.append(proof)
            
            end_time = time.time()
            
            # Determine overall status
            all_success = all(r.status == NativeProofStatus.SUCCESS for r in results)
            any_failure = any(r.status == NativeProofStatus.FAILURE for r in results)
            
            if all_success:
                task.result = ProverStatus.SUCCESS
            elif any_failure:
                task.result = ProverStatus.FAILURE
            else:
                task.result = ProverStatus.UNKNOWN
            
            task.execution_time = end_time - start_time
            task.output = f"Proved {len(results)} goals using native {modal_logic.value} prover"
            
            logger.info(f"Native prover completed: {task.result.value} in {task.execution_time:.2f}s")
            
        except Exception as e:
            task.result = ProverStatus.ERROR
            task.error_message = str(e)
            logger.error(f"Native proving error: {e}")
        
        self.proof_tasks.append(task)
        return task
    
    @beartype
    def prove_formula(
        self,
        formula: str,
        assumptions: Optional[List[str]] = None,
        logic: str = "K"
    ) -> ProofTask:
        """Prove a single formula using native implementation.
        
        Args:
            formula: Formula to prove
            assumptions: Optional list of assumptions
            logic: Logic system ('K', 'S4', 'S5', 'cognitive')
            
        Returns:
            ProofTask with results
        """
        import time
        
        task = ProofTask(problem_file="inline_formula", native_used=True)
        
        if not NATIVE_AVAILABLE or not self.prefer_native:
            task.result = ProverStatus.ERROR
            task.error_message = "Native implementation not available"
            return task
        
        try:
            # Determine logic
            logic_map = {
                'K': ModalLogic.K,
                'S4': ModalLogic.S4,
                'S5': ModalLogic.S5,
                'cognitive': ModalLogic.S5,
            }
            modal_logic = logic_map.get(logic.upper(), ModalLogic.K)
            
            # Create prover
            if logic.lower() == 'cognitive':
                prover = create_cognitive_prover()
            else:
                prover = create_prover(modal_logic)
            
            # Prove
            start_time = time.time()
            proof = prover.prove(formula, assumptions)
            end_time = time.time()
            
            # Convert status
            if proof.status == NativeProofStatus.SUCCESS:
                task.result = ProverStatus.SUCCESS
            elif proof.status == NativeProofStatus.FAILURE:
                task.result = ProverStatus.FAILURE
            else:
                task.result = ProverStatus.UNKNOWN
            
            task.execution_time = end_time - start_time
            task.output = f"Formula: {formula}, Status: {task.result.value}"
            
            logger.info(f"Proved formula: {task.result.value} in {task.execution_time:.2f}s")
            
        except Exception as e:
            task.result = ProverStatus.ERROR
            task.error_message = str(e)
            logger.error(f"Formula proving error: {e}")
        
        self.proof_tasks.append(task)
        return task
    
    def get_native_status(self) -> Dict[str, Any]:
        """Get status of native implementation.
        
        Returns:
            Dictionary with native implementation status
        """
        return {
            "available": NATIVE_AVAILABLE,
            "preferred": self.prefer_native,
            "active": self.prefer_native and NATIVE_AVAILABLE,
            "version": "0.8.0" if NATIVE_AVAILABLE else None,
            "features": [
                "Modal logic (K, S4, S5)",
                "Cognitive calculus",
                "Tableau proving",
                "Problem file parsing (TPTP, custom)"
            ] if NATIVE_AVAILABLE else []
        }
