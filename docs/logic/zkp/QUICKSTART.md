# ZKP Module - Quick Start Guide

**⚠️ IMPORTANT:** This module is a SIMULATION for educational purposes only. It is NOT cryptographically secure.

**Time to first proof:** 2 minutes  
**Prerequisites:** Python 3.12+, basic understanding of zero-knowledge proofs

---

## Installation

```bash
# Install the logic module (ZKP included)
pip install -e .
```

---

## Your First Zero-Knowledge Proof (30 seconds)

```python
from ipfs_datasets_py.logic.zkp import ZKPProver, ZKPVerifier

# Step 1: Create a prover
prover = ZKPProver()

# Step 2: Generate a proof (private axioms stay secret!)
proof = prover.generate_proof(
    theorem="Socrates is mortal",
    private_axioms=[
        "Socrates is human",      # This stays PRIVATE
        "All humans are mortal"   # This stays PRIVATE
    ]
)

# Step 3: Verify the proof (without seeing the axioms)
verifier = ZKPVerifier()
is_valid = verifier.verify_proof(proof)

print(f"✓ Proof verified: {is_valid}")
print(f"Proof size: {proof.size_bytes} bytes")
```

**Output:**
```
⚠️  WARNING: ipfs_datasets_py.logic.zkp is a SIMULATION module, NOT cryptographically secure!
✓ Proof verified: True
Proof size: 256 bytes
```

---

## What Just Happened?

You created a **zero-knowledge proof** that demonstrates:
- ✅ The theorem "Socrates is mortal" is true
- ✅ It follows from some axioms
- ❌ **WITHOUT revealing** what those axioms are!

The verifier can confirm the proof is valid without ever seeing:
- "Socrates is human"
- "All humans are mortal"

This is the power of zero-knowledge proofs!

---

## ⚠️ Critical Warning: This is a SIMULATION

**What this module IS:**
- ✅ Educational demonstration of ZKP concepts
- ✅ Fast prototyping tool (<0.1ms proving)
- ✅ API that mimics real ZKP systems
- ✅ Suitable for learning and development

**What this module is NOT:**
- ❌ Cryptographically secure
- ❌ Production-ready for sensitive data
- ❌ Real zkSNARKs (Groth16, PLONK, etc.)
- ❌ Suitable for actual privacy requirements

**For production use with real security, see:**
- [PRODUCTION_UPGRADE_PATH.md](./PRODUCTION_UPGRADE_PATH.md) - Upgrade to real Groth16
- [SECURITY_CONSIDERATIONS.md](./SECURITY_CONSIDERATIONS.md) - Security details

---

## Common Use Cases

### 1. Private Compliance Verification

Prove regulatory compliance without revealing internal policies:

```python
proof = prover.generate_proof(
    theorem="Company complies with GDPR",
    private_axioms=[
        "Internal policy A (secret)",
        "Internal policy B (secret)",
        "Policies A+B satisfy GDPR"
    ]
)

# Regulator verifies WITHOUT seeing internal policies
verifier.verify_proof(proof)  # True
```

### 2. Theorem Proving with Hidden Axioms

```python
proof = prover.generate_proof(
    theorem="Q",
    private_axioms=["P", "P -> Q"]  # Modus ponens
)

# Anyone can verify the theorem without seeing P or P->Q
verifier.verify_proof(proof)  # True
```

### 3. Caching for Performance

```python
prover = ZKPProver(enable_caching=True)

# First proof: ~0.1ms
proof1 = prover.generate_proof(theorem="Q", private_axioms=["P", "P->Q"])

# Second identical proof: <0.01ms (100x faster!)
proof2 = prover.generate_proof(theorem="Q", private_axioms=["P", "P->Q"])

stats = prover.get_stats()
print(f"Cache hit rate: {stats['cache_hit_rate']:.1%}")
```

---

## Next Steps

### Learn More

1. **[README.md](./README.md)** - Comprehensive overview with all features
2. **[EXAMPLES.md](./EXAMPLES.md)** - Detailed usage examples
3. **[IMPLEMENTATION_GUIDE.md](./IMPLEMENTATION_GUIDE.md)** - How it works internally

### Security & Production

4. **[SECURITY_CONSIDERATIONS.md](./SECURITY_CONSIDERATIONS.md)** - Important security info
5. **[PRODUCTION_UPGRADE_PATH.md](./PRODUCTION_UPGRADE_PATH.md)** - Path to real ZKP

### Integration

6. **[INTEGRATION_GUIDE.md](./INTEGRATION_GUIDE.md)** - Use with other logic modules
7. **[Full API Reference](./README.md#api-reference)** - Complete API documentation

---

## Quick Reference

### Basic API

```python
# Proof generation
prover = ZKPProver(security_level=128, enable_caching=True)
proof = prover.generate_proof(theorem="...", private_axioms=["..."])

# Proof verification
verifier = ZKPVerifier(security_level=128)
is_valid = verifier.verify_proof(proof)

# Statistics
prover_stats = prover.get_stats()
verifier_stats = verifier.get_stats()
```

### Circuit Construction

```python
from ipfs_datasets_py.logic.zkp import ZKPCircuit

circuit = ZKPCircuit()
p = circuit.add_input("P")
q = circuit.add_input("Q")
pq = circuit.add_and_gate(p, q)
circuit.set_output(pq)
```

### Proof Serialization

```python
# Convert to dict for storage
proof_dict = proof.to_dict()

# Store on IPFS, in database, etc.
# ...

# Reconstruct proof
from ipfs_datasets_py.logic.zkp import ZKPProof
reconstructed = ZKPProof.from_dict(proof_dict)
```

---

## Troubleshooting

### Import Warning Appears

**Problem:** Warning about simulation appears when importing

**Solution:** This is expected! The warning reminds you this is educational only.

```python
# To suppress warnings (not recommended)
import warnings
warnings.filterwarnings('ignore', category=UserWarning, module='ipfs_datasets_py.logic.zkp')
```

### Proof Verification Fails

**Problem:** `verify_proof()` returns `False`

**Common causes:**
1. Proof was corrupted during serialization
2. Security level mismatch between prover and verifier
3. Proof data was modified

**Solution:**
```python
# Ensure security levels match
prover = ZKPProver(security_level=128)
verifier = ZKPVerifier(security_level=128)

# Check proof structure
if proof.size_bytes < 100:
    print("Proof is too small, may be corrupted")
```

### Slow Performance

**Problem:** Proof generation is slower than expected

**Solution:** Enable caching

```python
prover = ZKPProver(enable_caching=True)  # 100x speedup for repeated proofs
```

---

## Examples

**For more examples**, see [EXAMPLES.md](EXAMPLES.md) which contains 14+ demonstrations including working example scripts.

### Example 1: Syllogism

```python
from ipfs_datasets_py.logic.zkp import ZKPProver, ZKPVerifier

prover = ZKPProver()

# Classic syllogism with private premises
proof = prover.generate_proof(
    theorem="Socrates is mortal",
    private_axioms=[
        "All men are mortal",
        "Socrates is a man"
    ]
)

verifier = ZKPVerifier()
assert verifier.verify_proof(proof)
print("✓ Syllogism verified without revealing premises!")
```

### Example 2: Access Control

```python
# Prove access rights without revealing which rules apply
proof = prover.generate_proof(
    theorem="User has admin access",
    private_axioms=[
        "User is in admin group",
        "Admin group has admin access"
    ]
)

# Verifier confirms access without seeing group membership
assert verifier.verify_proof(proof)
```

### Example 3: Mathematical Proof

```python
# Prove mathematical theorem with hidden axioms
proof = prover.generate_proof(
    theorem="2+2=4",
    private_axioms=[
        "Peano axiom 1",
        "Peano axiom 2",
        "Definition of addition"
    ]
)

assert verifier.verify_proof(proof)
print("✓ Mathematical proof verified!")
```

---

## Performance Characteristics

| Metric | Simulation | Real Groth16 |
|--------|------------|--------------|
| Proof Size | ~160 bytes | ~256 bytes |
| Proving Time | <0.1ms | <1 second |
| Verification Time | <0.01ms | <10ms |
| Security | NONE | 128-bit |
| Use Case | Learning | Production |

---

## Getting Help

- **Documentation:** [README.md](./README.md)
- **Examples:** [EXAMPLES.md](./EXAMPLES.md)
- **Issues:** [GitHub Issues](https://github.com/endomorphosis/ipfs_datasets_py/issues)

---

## License

Same as parent project (AGPL-3.0).

---

**You're now ready to use ZKP!** 🎉

Remember: This is a simulation for learning. For production security, upgrade to real Groth16 using [PRODUCTION_UPGRADE_PATH.md](./PRODUCTION_UPGRADE_PATH.md).
