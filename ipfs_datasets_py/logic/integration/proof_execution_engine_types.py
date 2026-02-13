"""
Proof Execution Engine Types

This module defines the type definitions, dataclasses, and enumerations
used by the Proof Execution Engine.

Extracted from proof_execution_engine.py to improve modularity and
prevent circular dependencies.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List


class ProofStatus(Enum):
    """
    Status of proof execution.
    
    Attributes:
        SUCCESS: Proof was successfully verified
        FAILURE: Proof verification failed
        TIMEOUT: Proof execution timed out
        ERROR: Error occurred during execution
        UNSUPPORTED: Prover doesn't support the formula type
        
    Example:
        >>> status = ProofStatus.SUCCESS
        >>> status.value
        'success'
    """
    SUCCESS = "success"
    FAILURE = "failure" 
    TIMEOUT = "timeout"
    ERROR = "error"
    UNSUPPORTED = "unsupported"


@dataclass
class ProofResult:
    """
    Result of executing a proof.
    
    Attributes:
        prover: Name of the theorem prover used
        statement: The statement that was proved
        status: Status of the proof execution
        proof_output: Output from the prover
        execution_time: Time taken to execute the proof (seconds)
        errors: List of error messages
        warnings: List of warning messages
        metadata: Additional metadata about the proof
        
    Example:
        >>> result = ProofResult(
        ...     prover="z3",
        ...     statement="P ∧ Q → P",
        ...     status=ProofStatus.SUCCESS,
        ...     execution_time=0.5
        ... )
    """
    prover: str
    statement: str
    status: ProofStatus
    proof_output: str = ""
    execution_time: float = 0.0
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """
        Convert to dictionary representation.
        
        Returns:
            Dictionary containing all proof result data
            
        Example:
            >>> result = ProofResult(prover="z3", statement="P", status=ProofStatus.SUCCESS)
            >>> d = result.to_dict()
            >>> d["prover"]
            'z3'
        """
        return {
            "prover": self.prover,
            "statement": self.statement,
            "status": self.status.value,
            "proof_output": self.proof_output,
            "execution_time": self.execution_time,
            "errors": self.errors,
            "warnings": self.warnings,
            "metadata": self.metadata
        }


# Export all types
__all__ = [
    'ProofStatus',
    'ProofResult',
]
