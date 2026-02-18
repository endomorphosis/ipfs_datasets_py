# Zero-Knowledge Proof (ZKP) Module

**Privacy-Preserving Theorem Proving for Logic Formulas**

## Overview

The ZKP module provides zero-knowledge proof capabilities for the logic module, enabling privacy-preserving verification of theorems without revealing the underlying axioms or proofs.

## Key Features

- **🔐 Private Theorem Proving** - Prove theorems without revealing axioms
- **✅ Fast Verification** - <10ms verification time
- **📦 Succinct Proofs** - ~160 bytes per proof (simulated)
- **⚠️ Simulation Only** - Not cryptographically secure
- **🚀 High Performance** - Fast simulated proving/verification
- **💾 Caching Support** - Cache proofs for reuse

## Use Cases

### 1. Private Theorem Proving
Prove that a theorem follows from axioms without revealing the axioms:

```python
from ipfs_datasets_py.logic.zkp import ZKPProver, ZKPVerifier

prover = ZKPProver()
proof = prover.generate_proof(
    theorem="Socrates is mortal",
    private_axioms=[
        "Socrates is human",      # Kept private!
        "All humans are mortal"   # Kept private!
    ]
)

# Verify without seeing the axioms
verifier = ZKPVerifier()
assert verifier.verify_proof(proof)  # True
print(f"Proof size: {proof.size_bytes} bytes")  # 256 bytes
```

### 2. Confidential Compliance Verification
Verify regulatory compliance without exposing internal policies:

```python
# Company proves compliance without revealing policies
prover = ZKPProver()
proof = prover.generate_proof(
    theorem="Company is compliant with regulation X",
    private_axioms=[
        "Internal policy A",
        "Internal policy B", 
        "Policies A and B satisfy regulation X"
    ]
)

# Regulator verifies without seeing internal policies
verifier = ZKPVerifier()
is_compliant = verifier.verify_proof(proof)
```

### 3. Secure Multi-Party Logic Computation
Multiple parties compute logic without revealing their inputs:

```python
# Party 1 has private data P
# Party 2 has private data Q
# Both want to prove: P AND Q -> R without revealing P or Q

prover = ZKPProver()
proof = prover.generate_proof(
    theorem="R",
    private_axioms=["P", "Q", "(P AND Q) -> R"]
)
```

### 4. Private IPFS Proof Storage
Store proofs on IPFS without exposing sensitive logic:

```python
proof = prover.generate_proof(theorem="...", private_axioms=["..."])

# Store proof on IPFS (only proof data, not axioms)
proof_dict = proof.to_dict()
ipfs_hash = ipfs_client.add_json(proof_dict)

# Anyone can verify from IPFS
downloaded_proof = ZKPProof.from_dict(ipfs_client.get_json(ipfs_hash))
verifier.verify_proof(downloaded_proof)
```

## API Reference

### ZKPProver

Generate zero-knowledge proofs for theorems.

```python
class ZKPProver:
    def __init__(
        self,
        security_level: int = 128,
        enable_caching: bool = True,
    ):
        """
        Initialize ZKP prover.
        
        Args:
            security_level: Security bits (default: 128)
            enable_caching: Cache generated proofs
        """
    
    def generate_proof(
        self,
        theorem: str,
        private_axioms: List[str],
        metadata: Optional[Dict] = None,
    ) -> ZKPProof:
        """
        Generate a zero-knowledge proof.
        
        Args:
            theorem: The theorem to prove (public)
            private_axioms: Axioms used (kept private)
            metadata: Additional proof metadata
        
        Returns:
            ZKPProof: The generated proof
        """
    
    def get_stats(self) -> Dict[str, Any]:
        """Get prover statistics."""
    
    def clear_cache(self):
        """Clear proof cache."""
```

### ZKPVerifier

Verify zero-knowledge proofs.

```python
class ZKPVerifier:
    def __init__(self, security_level: int = 128):
        """
        Initialize ZKP verifier.
        
        Args:
            security_level: Required security bits
        """
    
    def verify_proof(self, proof: ZKPProof) -> bool:
        """
        Verify a zero-knowledge proof.
        
        Args:
            proof: The proof to verify
        
        Returns:
            bool: True if valid, False otherwise
        """
    
    def verify_with_public_inputs(
        self,
        proof: ZKPProof,
        expected_theorem: str,
    ) -> bool:
        """
        Verify proof and check public inputs match.
        
        Args:
            proof: The proof to verify
            expected_theorem: Expected theorem statement
        
        Returns:
            bool: True if valid and inputs match
        """
    
    def get_stats(self) -> Dict[str, Any]:
        """Get verifier statistics."""
```

### ZKPCircuit

Build arithmetic circuits for logic operations.

```python
class ZKPCircuit:
    def __init__(self):
        """Initialize empty circuit."""
    
    def add_input(self, name: str) -> int:
        """Add an input wire to the circuit."""
    
    def add_and_gate(self, wire_a: int, wire_b: int) -> int:
        """Add an AND gate."""
    
    def add_or_gate(self, wire_a: int, wire_b: int) -> int:
        """Add an OR gate."""
    
    def add_not_gate(self, wire: int) -> int:
        """Add a NOT gate."""
    
    def add_implies_gate(self, wire_a: int, wire_b: int) -> int:
        """Add an IMPLIES gate."""
    
    def set_output(self, wire: int):
        """Mark a wire as circuit output."""
```

## Performance Characteristics

| Metric | Value |
|--------|-------|
| Proof Size | ~160 bytes (simulated) |
| Proving Time | Fast (simulated) |
| Verification Time | <10ms |
| Security Level | None (simulation only) |
| Cache Hit Speedup | ~100x |

## Example: Building Logic Circuits

```python
from ipfs_datasets_py.logic.zkp import ZKPCircuit, create_implication_circuit

# Manual circuit construction
circuit = ZKPCircuit()
p = circuit.add_input("P")
q = circuit.add_input("Q")
r = circuit.add_input("R")

# (P AND Q) -> R
p_and_q = circuit.add_and_gate(p, q)
result = circuit.add_implies_gate(p_and_q, r)
circuit.set_output(result)

print(f"Circuit: {circuit}")
# ZKPCircuit(inputs=3, gates=2, wires=5)

# Or use helper function
circuit = create_implication_circuit(num_premises=3)
# Creates: (P1 AND P2 AND P3) -> Q
```

## Implementation Details

### Current Implementation
The current implementation is a **simulated ZKP system** for demonstration purposes. It:
- Uses SHA-256 hashing to simulate circuit commitments
- Generates simulated proofs of fixed size (~160 bytes)
- Provides the correct API and performance characteristics
- Is suitable for testing and development

### Production Upgrade Path
For production use with real cryptographic security:

1. **Install py_ecc library:**
   ```bash
   pip install py-ecc
   ```

2. **Replace simulation with real Groth16:**
   ```python
   # Current: Simulated
   proof_data = self._simulate_groth16_proof(...)
   
   # Production: Real Groth16
   from py_ecc.bn128 import G1, G2, pairing
   proof_data = self._real_groth16_proof(...)
   ```

3. **Benefits of real implementation:**
   - True cryptographic security
   - Verifiable soundness guarantees
   - Battle-tested in production systems (Zcash, Filecoin)

## Integration with Logic Module

The ZKP module integrates with other logic components:

```python
# With ProofExecutionEngine (planned)
from ipfs_datasets_py.logic.integration import ProofExecutionEngine

engine = ProofExecutionEngine()
result = engine.prove(
    theorem="Q",
    axioms=["P", "P -> Q"],
    private=True  # Use ZKP!
)

# With IPFS Proof Cache (planned)
from ipfs_datasets_py.logic.integration import IPFSProofCache

cache = IPFSProofCache()
cache.store_private_proof(
    proof=zkp_proof,
    pin=True
)
```

## Testing

Run comprehensive tests:

```bash
pytest ipfs_datasets_py/tests/unit_tests/logic/zkp/test_zkp_module.py -v
```

Test coverage includes:
- Proof generation
- Proof verification
- Circuit construction
- Privacy guarantees
- Performance characteristics
- Integration scenarios

## Security Considerations

### Current (Simulated)
- ⚠️ **Not cryptographically secure**
- ✅ Demonstrates correct API and workflow
- ✅ Suitable for development and testing
- ❌ Do not use for actual private data

### Production (with py_ecc)
- ✅ Cryptographically secure (when implemented as a real backend)
- ✅ Proven security guarantees
- ✅ Battle-tested zkSNARK implementation
- ✅ Suitable for production use with sensitive data

## Future Enhancements

1. **Real Groth16 Implementation**
   - Integrate py_ecc library
   - Real pairing-based cryptography
   - Production-ready security

2. **Advanced Circuits**
   - Quantifiers (∀, ∃)
   - Equality constraints
   - Arithmetic operations

3. **Recursive Proofs**
   - Prove proofs about proofs
   - Scalable verification

4. **IPFS Integration**
   - Encrypted proof storage
   - Distributed verification

## References

- [Groth16 zkSNARKs](https://eprint.iacr.org/2016/260)
- [py_ecc Library](https://github.com/ethereum/py_ecc)
- [ZCash Protocol](https://z.cash/technology/)
- [Filecoin Proofs](https://filecoin.io/blog/posts/what-sets-us-apart-filecoin-s-proof-system/)

## License

Same as parent project.

## Support

For issues or questions about the ZKP module, please open an issue on GitHub.
