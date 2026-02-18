"""
Groth16 Zero-Knowledge Proof Backend

Rust FFI wrapper for Groth16 zkSNARK proof generation and verification.
Implements the backend protocol from Phase 3A.

Status: FFI Integration (Phase 3C.2)
"""

import json
import subprocess
import os
from pathlib import Path
from typing import Optional, Protocol, runtime_checkable
from dataclasses import dataclass
from datetime import datetime
import logging

from ipfs_datasets_py.logic.zkp import ZKPProof

logger = logging.getLogger(__name__)


@runtime_checkable
class ZKPBackend(Protocol):
    """Protocol for ZKP backend implementations."""
    
    def generate_proof(self, witness_json: str) -> ZKPProof:
        """Generate a zero-knowledge proof."""
        ...
    
    def verify_proof(self, proof_json: str) -> bool:
        """Verify a zero-knowledge proof."""
        ...


@dataclass
class Groth16Proof(ZKPProof):
    """Groth16-specific proof structure."""
    
    proof_data: bytes  # Serialized proof (A, B, C components)
    public_inputs: dict  # 4-field public inputs
    metadata: dict
    timestamp: int
    size_bytes: int
    
    def to_dict(self) -> dict:
        """Serialize to dictionary."""
        return {
            'proof_data': self.proof_data.hex() if self.proof_data else None,
            'public_inputs': self.public_inputs,
            'metadata': self.metadata,
            'timestamp': self.timestamp,
            'size_bytes': self.size_bytes,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> 'Groth16Proof':
        """Deserialize from dictionary."""
        proof_data = bytes.fromhex(data.get('proof_data', '')) if data.get('proof_data') else None
        return cls(
            proof_data=proof_data,
            public_inputs=data.get('public_inputs', {}),
            metadata=data.get('metadata', {}),
            timestamp=data.get('timestamp', 0),
            size_bytes=data.get('size_bytes', 0),
        )


class Groth16Backend(ZKPBackend):
    """
    Real Groth16 zkSNARK backend using Rust FFI.
    
    Architecture:
    - Python: Witness validation and serialization
    - Rust: Proof generation and verification
    - Communication: JSON over subprocess
    """
    
    def __init__(self, binary_path: Optional[str] = None, timeout_seconds: int = 30):
        """
        Initialize Groth16 backend.
        
        Args:
            binary_path: Path to compiled groth16 binary. 
                        If None, searches in default locations.
            timeout_seconds: Timeout for subprocess calls.
        """
        self.binary_path = binary_path or self._find_groth16_binary()
        self.timeout_seconds = timeout_seconds
        
        if not self.binary_path:
            logger.warning(
                "Groth16 binary not found. "
                "Install Rust and run: cd ipfs_datasets_py/ipfs_datasets_py/processors/groth16_backend && cargo build --release "
                "(legacy docs may refer to ./groth16_backend)"
            )
        elif not os.path.exists(self.binary_path):
            logger.warning(f"Groth16 binary not found at {self.binary_path}")
    
    def _find_groth16_binary(self) -> Optional[str]:
        """Find groth16 binary in standard locations."""
        # Allow explicit override (useful for CI, dev machines, and when the Rust
        # crate is located outside of the Python package tree).
        for env_var in ("IPFS_DATASETS_GROTH16_BINARY", "GROTH16_BINARY"):
            override = os.environ.get(env_var)
            if override and Path(override).exists():
                logger.info(f"Using Groth16 binary from ${env_var}: {override}")
                return override

        # Canonical location (current):
        #   ipfs_datasets_py/ipfs_datasets_py/processors/groth16_backend/target/release/groth16
        package_root = Path(__file__).resolve().parents[3]  # .../ipfs_datasets_py/ipfs_datasets_py
        repo_root = package_root.parent  # .../ipfs_datasets_py

        candidates = [
            package_root / "processors" / "groth16_backend" / "target" / "release" / "groth16",

            # Backward-compatible legacy location (older docs/scripts):
            #   <project-root>/groth16_backend/target/release/groth16
            repo_root.parent / "groth16_backend" / "target" / "release" / "groth16",

            # If user installed a global binary
            Path.home() / ".cargo" / "bin" / "groth16",
        ]
        
        for path in candidates:
            if path.exists():
                logger.info(f"Found Groth16 binary at {path}")
                return str(path)
        
        return None
    
    def generate_proof(self, witness_json: str) -> ZKPProof:
        """
        Generate Groth16 proof from witness.
        
        Args:
            witness_json: Serialized MVPWitness as JSON string
            
        Returns:
            Groth16Proof object with cryptographic proof
        """
        if not self.binary_path:
            raise RuntimeError(
                "Groth16 binary not available. "
                "Please install Rust and compile groth16_backend"
            )
        
        # Validate witness before sending to Rust
        witness = json.loads(witness_json)
        self._validate_witness(witness)
        
        try:
            # Call Rust binary with witness
            result = subprocess.run(
                [self.binary_path, "prove", "--input", "/dev/stdin", "--output", "/dev/stdout"],
                input=witness_json.encode(),
                capture_output=True,
                timeout=self.timeout_seconds,
            )
            
            if result.returncode != 0:
                raise RuntimeError(
                    f"Groth16 proof generation failed: {result.stderr.decode()}"
                )
            
            # Parse proof from JSON
            proof_json = json.loads(result.stdout.decode())
            return self._parse_proof_output(proof_json, witness)
            
        except subprocess.TimeoutExpired:
            raise TimeoutError(f"Groth16 proof generation timeout after {self.timeout_seconds}s")
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON from Groth16 binary: {e}")
    
    def verify_proof(self, proof_json: str) -> bool:
        """
        Verify Groth16 proof.
        
        Args:
            proof_json: Serialized proof as JSON string
            
        Returns:
            True if proof is valid, False otherwise
        """
        if not self.binary_path:
            raise RuntimeError(
                "Groth16 binary not available. "
                "Please install Rust and compile groth16_backend"
            )
        
        try:
            # Call Rust binary to verify
            result = subprocess.run(
                [self.binary_path, "verify", "--proof", "/dev/stdin"],
                input=proof_json.encode(),
                capture_output=True,
                timeout=self.timeout_seconds,
            )
            
            # Exit code 0 = valid, non-zero = invalid
            return result.returncode == 0
            
        except subprocess.TimeoutExpired:
            raise TimeoutError(f"Groth16 verification timeout after {self.timeout_seconds}s")
        except Exception as e:
            raise RuntimeError(f"Groth16 verification error: {e}")
    
    def _validate_witness(self, witness: dict) -> None:
        """Validate witness structure before proof generation."""
        required_fields = [
            'private_axioms',
            'theorem',
            'axioms_commitment_hex',
            'theorem_hash_hex',
            'circuit_version',
            'ruleset_id',
        ]
        
        missing = [f for f in required_fields if f not in witness]
        if missing:
            raise ValueError(f"Missing witness fields: {missing}")
        
        if not isinstance(witness['private_axioms'], list) or not witness['private_axioms']:
            raise ValueError("private_axioms must be non-empty list")
        
        if not witness['theorem']:
            raise ValueError("theorem cannot be empty")
        
        if witness['circuit_version'] < 0:
            raise ValueError("circuit_version must be non-negative")
    
    def _parse_proof_output(self, proof_data: dict, witness: dict) -> Groth16Proof:
        """Parse proof JSON output from Rust binary."""
        # Extract public inputs from witness
        public_inputs = {
            'theorem_hash': witness.get('theorem_hash_hex', ''),
            'axioms_commitment': witness.get('axioms_commitment_hex', ''),
            'circuit_version': witness.get('circuit_version', 0),
            'ruleset_id': witness.get('ruleset_id', ''),
        }
        
        # Reconstruct proof (would be properly decoded from Rust)
        proof_hex = json.dumps(proof_data).encode()
        
        return Groth16Proof(
            proof_data=proof_hex,
            public_inputs=public_inputs,
            metadata={
                'backend': 'groth16',
                'curve': 'BN254',
                'version': proof_data.get('version', 1),
            },
            timestamp=proof_data.get('timestamp', 0),
            size_bytes=len(proof_hex) // 2,  # Approximate
        )
    
    def get_backend_info(self) -> dict:
        """Get backend information."""
        return {
            'name': 'Groth16',
            'type': 'real_zksnark',
            'curve': 'BN254',
            'proof_system': 'Groth16',
            'binary_path': self.binary_path,
            'timeout_seconds': self.timeout_seconds,
            'status': 'ready' if self.binary_path else 'not_available',
        }


class Groth16BackendFallback(ZKPBackend):
    """
    Fallback backend when Groth16 binary is not available.
    Generates placeholder proofs for testing FFI integration.
    """
    
    def generate_proof(self, witness_json: str) -> ZKPProof:
        """Generate placeholder proof (for testing)."""
        witness = json.loads(witness_json)
        
        # Validate witness
        self._validate_witness(witness)
        
        # Generate deterministic placeholder proof
        proof_data = (
            witness['theorem_hash_hex'] + 
            witness['axioms_commitment_hex']
        ).encode()
        
        proof = Groth16Proof(
            proof_data=proof_data,
            public_inputs={
                'theorem_hash': witness['theorem_hash_hex'],
                'axioms_commitment': witness['axioms_commitment_hex'],
                'circuit_version': witness['circuit_version'],
                'ruleset_id': witness['ruleset_id'],
            },
            metadata={
                'backend': 'groth16_fallback',
                'note': 'Placeholder proof - Rust binary not available',
            },
            timestamp=int(datetime.now().timestamp()),
            size_bytes=len(proof_data),
        )
        
        return proof
    
    def verify_proof(self, proof_json: str) -> bool:
        """Verify placeholder proof."""
        try:
            proof = json.loads(proof_json)
            # Basic validation: has required fields
            return 'public_inputs' in proof
        except:
            return False
    
    def _validate_witness(self, witness: dict) -> None:
        """Validate witness structure."""
        required_fields = [
            'private_axioms',
            'theorem',
            'axioms_commitment_hex',
            'theorem_hash_hex',
            'circuit_version',
            'ruleset_id',
        ]
        
        missing = [f for f in required_fields if f not in witness]
        if missing:
            raise ValueError(f"Missing witness fields: {missing}")
    
    def get_backend_info(self) -> dict:
        """Get backend information."""
        return {
            'name': 'Groth16Fallback',
            'type': 'placeholder_zksnark',
            'status': 'fallback_only',
            'note': 'Using placeholder for testing. Install Rust binary for real proofs.',
        }

