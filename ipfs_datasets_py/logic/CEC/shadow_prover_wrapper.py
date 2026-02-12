"""
ShadowProver Wrapper

This module provides a Python wrapper for the ShadowProver submodule,
which is a theorem prover that can work alongside other provers.

ShadowProver provides automated theorem proving capabilities with
support for various logical systems and proof strategies.
"""

import sys
import os
from pathlib import Path
from typing import Dict, List, Optional, Any
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

logger = logging.getLogger(__name__)


class ProverStatus(Enum):
    """Enumeration of prover status."""
    SUCCESS = "success"
    FAILURE = "failure"
    TIMEOUT = "timeout"
    ERROR = "error"


@dataclass
class ProofTask:
    """Represents a proof task for ShadowProver."""
    problem_file: str
    result: Optional[ProverStatus] = None
    output: Optional[str] = None
    execution_time: float = 0.0
    error_message: Optional[str] = None


class ShadowProverWrapper:
    """
    Wrapper for ShadowProver providing a clean Python API.
    
    ShadowProver is a Java-based theorem prover. This wrapper
    manages the interaction with the prover through its command-line
    interface or Docker container.
    
    Attributes:
        prover_path: Path to ShadowProver installation
        proof_tasks: List of proof tasks
        use_docker: Whether to use Docker for running the prover
    """
    
    def __init__(
        self,
        prover_path: Optional[Path] = None,
        use_docker: bool = False
    ):
        """
        Initialize the ShadowProver wrapper.
        
        Args:
            prover_path: Optional path to ShadowProver directory
            use_docker: If True, use Docker to run ShadowProver
        """
        self.prover_path = prover_path or SHADOW_PROVER_PATH
        self.use_docker = use_docker
        self.proof_tasks: List[ProofTask] = []
        self._initialized = False
        
    @beartype
    def initialize(self) -> bool:
        """
        Initialize the ShadowProver.
        
        Checks that ShadowProver is available and can be executed.
        
        Returns:
            bool: True if initialization succeeded, False otherwise
        """
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
        timeout: int = 60
    ) -> ProofTask:
        """
        Attempt to prove a problem using ShadowProver.
        
        Args:
            problem_file: Path to the problem file (TPTP format)
            timeout: Timeout in seconds
            
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
