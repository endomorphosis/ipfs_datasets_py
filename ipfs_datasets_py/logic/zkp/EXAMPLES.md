# ZKP Module Examples

## Overview

This document provides comprehensive code examples for using the ZKP (Zero-Knowledge Proof) module. All examples are self-contained and ready to run.

**⚠️ SIMULATION ONLY**: Remember that this module provides educational simulation, not cryptographic security. See [SECURITY_CONSIDERATIONS.md](SECURITY_CONSIDERATIONS.md).

## Table of Contents

1. [Basic Examples](#basic-examples)
2. [Boolean Circuit Examples](#boolean-circuit-examples)
3. [Arithmetic Circuit Examples](#arithmetic-circuit-examples)
4. [Advanced Examples](#advanced-examples)
5. [Integration Examples](#integration-examples)
6. [Error Handling Examples](#error-handling-examples)
7. [Performance Examples](#performance-examples)
8. [Best Practices](#best-practices)

## Basic Examples

### Example 1: Your First Zero-Knowledge Proof

The simplest possible ZKP - proving knowledge of a secret bit.

```python
from ipfs_datasets_py.logic.zkp import BooleanCircuit, ZKPProver, ZKPVerifier

# Step 1: Define circuit
circuit = BooleanCircuit()
secret_wire = circuit.add_wire()
circuit.set_private_input(secret_wire)

# Step 2: Create prover and verifier
prover = ZKPProver(circuit)
verifier = ZKPVerifier(prover.get_verification_key())

# Step 3: Generate proof (prover knows secret=True)
witness = {secret_wire: True}
proof = prover.generate_proof(witness, public_inputs=[])

# Step 4: Verify proof (verifier doesn't learn secret!)
is_valid = verifier.verify_proof(proof, public_inputs=[])
print(f"Proof valid: {is_valid}")  # True

# The verifier now knows the prover has a secret,
# but doesn't know whether it's True or False!
```

### Example 2: Proving Knowledge of AND Result

Prove you know two secret bits that AND to True.

```python
from ipfs_datasets_py.logic.zkp import BooleanCircuit, ZKPProver, ZKPVerifier

# Circuit: secret1 AND secret2 = result (public)
circuit = BooleanCircuit()
w1 = circuit.add_wire()  # secret1 (private)
w2 = circuit.add_wire()  # secret2 (private)
w3 = circuit.add_wire()  # result (public)

circuit.add_gate('AND', [w1, w2], w3)
circuit.set_private_input(w1)
circuit.set_private_input(w2)
circuit.set_public_input(w3)

# Prover: I know two secret bits that AND to True
prover = ZKPProver(circuit)
witness = {w1: True, w2: True}
proof = prover.generate_proof(witness, public_inputs=[True])

# Verifier: Prove it!
verifier = ZKPVerifier(prover.get_verification_key())
is_valid = verifier.verify_proof(proof, public_inputs=[True])
print(f"Prover knows secrets that AND to True: {is_valid}")
```

### Example 3: Multiple Public Outputs

Circuit with multiple public outputs.

```python
from ipfs_datasets_py.logic.zkp import BooleanCircuit, ZKPProver, ZKPVerifier

circuit = BooleanCircuit()

# Three secret inputs
s1, s2, s3 = [circuit.add_wire() for _ in range(3)]
circuit.set_private_input(s1)
circuit.set_private_input(s2)
circuit.set_private_input(s3)

# Two public outputs: (s1 AND s2), (s2 OR s3)
out1 = circuit.add_wire()
out2 = circuit.add_wire()
circuit.add_gate('AND', [s1, s2], out1)
circuit.add_gate('OR', [s2, s3], out2)
circuit.set_public_input(out1)
circuit.set_public_input(out2)

# Prove knowledge of secrets producing these outputs
prover = ZKPProver(circuit)
witness = {s1: True, s2: True, s3: False}
public_inputs = [True, True]  # AND=True, OR=True
proof = prover.generate_proof(witness, public_inputs)

verifier = ZKPVerifier(prover.get_verification_key())
print(f"Valid: {verifier.verify_proof(proof, public_inputs)}")
```

## Boolean Circuit Examples

### Example 4: XOR Gate Implementation

Implement XOR using AND, OR, NOT gates.

```python
from ipfs_datasets_py.logic.zkp import BooleanCircuit, ZKPProver, ZKPVerifier

def build_xor_circuit():
    """Build XOR circuit: a XOR b = (a OR b) AND NOT(a AND b)"""
    circuit = BooleanCircuit()
    
    # Inputs
    a = circuit.add_wire()
    b = circuit.add_wire()
    circuit.set_private_input(a)
    circuit.set_private_input(b)
    
    # Intermediate wires
    a_or_b = circuit.add_wire()
    a_and_b = circuit.add_wire()
    not_a_and_b = circuit.add_wire()
    result = circuit.add_wire()
    
    # Gates
    circuit.add_gate('OR', [a, b], a_or_b)
    circuit.add_gate('AND', [a, b], a_and_b)
    circuit.add_gate('NOT', [a_and_b], not_a_and_b)
    circuit.add_gate('AND', [a_or_b, not_a_and_b], result)
    
    circuit.set_public_input(result)
    return circuit

# Test XOR circuit
circuit = build_xor_circuit()
prover = ZKPProver(circuit)
verifier = ZKPVerifier(prover.get_verification_key())

# Test cases: XOR truth table
test_cases = [
    ({0: False, 1: False}, [False]),  # 0 XOR 0 = 0
    ({0: False, 1: True}, [True]),    # 0 XOR 1 = 1
    ({0: True, 1: False}, [True]),    # 1 XOR 0 = 1
    ({0: True, 1: True}, [False]),    # 1 XOR 1 = 0
]

for witness, expected_output in test_cases:
    proof = prover.generate_proof(witness, expected_output)
    is_valid = verifier.verify_proof(proof, expected_output)
    print(f"XOR({witness[0]}, {witness[1]}) = {expected_output[0]}: {is_valid}")
```

### Example 5: Multiplexer Circuit

Build a 2-to-1 multiplexer: output = select ? b : a

```python
from ipfs_datasets_py.logic.zkp import BooleanCircuit, ZKPProver, ZKPVerifier

def build_mux_circuit():
    """Build 2-to-1 MUX: out = sel ? b : a"""
    circuit = BooleanCircuit()
    
    # Inputs (all private)
    a = circuit.add_wire()
    b = circuit.add_wire()
    sel = circuit.add_wire()
    circuit.set_private_input(a)
    circuit.set_private_input(b)
    circuit.set_private_input(sel)
    
    # Implementation: (sel AND b) OR (NOT(sel) AND a)
    not_sel = circuit.add_wire()
    sel_and_b = circuit.add_wire()
    not_sel_and_a = circuit.add_wire()
    output = circuit.add_wire()
    
    circuit.add_gate('NOT', [sel], not_sel)
    circuit.add_gate('AND', [sel, b], sel_and_b)
    circuit.add_gate('AND', [not_sel, a], not_sel_and_a)
    circuit.add_gate('OR', [sel_and_b, not_sel_and_a], output)
    
    circuit.set_public_input(output)
    return circuit

# Test MUX
circuit = build_mux_circuit()
prover = ZKPProver(circuit)
verifier = ZKPVerifier(prover.get_verification_key())

# sel=0: output should be a=True
witness = {0: True, 1: False, 2: False}  # a=True, b=False, sel=False
proof = prover.generate_proof(witness, [True])
print(f"MUX(sel=0): {verifier.verify_proof(proof, [True])}")

# sel=1: output should be b=False
witness = {0: True, 1: False, 2: True}  # a=True, b=False, sel=True
proof = prover.generate_proof(witness, [False])
print(f"MUX(sel=1): {verifier.verify_proof(proof, [False])}")
```

## Arithmetic Circuit Examples

### Example 6: Simple Arithmetic Constraint

Prove knowledge of x, y such that x * y = 15.

```python
from ipfs_datasets_py.logic.zkp import ArithmeticCircuit, ZKPProver, ZKPVerifier

# Build circuit: x * y = 15
circuit = ArithmeticCircuit()
x = circuit.create_variable('x', is_public=False)
y = circuit.create_variable('y', is_public=False)
result = circuit.create_variable('result', is_public=True)

# Constraint: x * y = result
circuit.add_constraint(
    a={'x': 1},           # a = x
    b={'y': 1},           # b = y
    c={'result': 1}       # c = result, so x * y = result
)

# Prove we know x=3, y=5 such that 3 * 5 = 15
prover = ZKPProver(circuit)
witness = {'x': 3, 'y': 5, 'result': 15}
proof = prover.generate_proof(witness, public_inputs=[15])

verifier = ZKPVerifier(prover.get_verification_key())
is_valid = verifier.verify_proof(proof, public_inputs=[15])
print(f"Proof that x * y = 15: {is_valid}")
```

### Example 7: Quadratic Equation

Prove knowledge of solution to x² + 3x - 10 = 0.

```python
from ipfs_datasets_py.logic.zkp import ArithmeticCircuit, ZKPProver, ZKPVerifier

# Build circuit for x² + 3x - 10 = 0
circuit = ArithmeticCircuit()
x = circuit.create_variable('x', is_public=False)
x_squared = circuit.create_variable('x_squared', is_public=False)
three_x = circuit.create_variable('three_x', is_public=False)
result = circuit.create_variable('result', is_public=True)

# Constraint 1: x * x = x_squared
circuit.add_constraint(
    a={'x': 1},
    b={'x': 1},
    c={'x_squared': 1}
)

# Constraint 2: 3 * x = three_x
circuit.add_constraint(
    a={'x': 3},
    b={},  # b = 1 (implicit)
    c={'three_x': 1}
)

# Constraint 3: x_squared + three_x - 10 = result (should be 0)
circuit.add_constraint(
    a={'x_squared': 1, 'three_x': 1},
    b={},  # b = 1
    c={'result': 1, 'ONE': 10}  # result + 10 = x² + 3x
)

# Solution: x = 2 (since 2² + 3*2 - 10 = 4 + 6 - 10 = 0)
prover = ZKPProver(circuit)
witness = {
    'x': 2,
    'x_squared': 4,
    'three_x': 6,
    'result': 0
}
proof = prover.generate_proof(witness, public_inputs=[0])

verifier = ZKPVerifier(prover.get_verification_key())
print(f"Valid solution to x² + 3x - 10 = 0: {verifier.verify_proof(proof, [0])}")
```

## Advanced Examples

### Example 8: Range Proof (Simplified)

Prove a value is within range [0, 15] without revealing it.

```python
from ipfs_datasets_py.logic.zkp import BooleanCircuit, ZKPProver, ZKPVerifier

def build_range_proof_circuit(num_bits=4):
    """Prove value fits in num_bits (range [0, 2^num_bits - 1])"""
    circuit = BooleanCircuit()
    
    # Binary representation bits (private)
    bits = []
    for i in range(num_bits):
        bit = circuit.add_wire()
        circuit.set_private_input(bit)
        bits.append(bit)
    
    # Just proving structure exists (simplified)
    # Real range proof would reconstruct value and check
    return circuit, bits

# Prove value 7 is in range [0, 15]
circuit, bits = build_range_proof_circuit(num_bits=4)
prover = ZKPProver(circuit)
verifier = ZKPVerifier(prover.get_verification_key())

# 7 in binary: 0111
witness = {
    bits[0]: True,   # LSB
    bits[1]: True,
    bits[2]: True,
    bits[3]: False   # MSB
}

proof = prover.generate_proof(witness, public_inputs=[])
print(f"Value in range [0, 15]: {verifier.verify_proof(proof, [])}")
```

### Example 9: Multi-Statement Proof

Prove multiple statements simultaneously.

```python
from ipfs_datasets_py.logic.zkp import BooleanCircuit, ZKPProver, ZKPVerifier

# Prove: (a AND b) = True AND (c OR d) = True
circuit = BooleanCircuit()
a, b, c, d = [circuit.add_wire() for _ in range(4)]
result1, result2 = [circuit.add_wire() for _ in range(2)]

for w in [a, b, c, d]:
    circuit.set_private_input(w)

circuit.add_gate('AND', [a, b], result1)
circuit.add_gate('OR', [c, d], result2)
circuit.set_public_input(result1)
circuit.set_public_input(result2)

# Both statements must be true
prover = ZKPProver(circuit)
witness = {a: True, b: True, c: False, d: True}
proof = prover.generate_proof(witness, public_inputs=[True, True])

verifier = ZKPVerifier(prover.get_verification_key())
is_valid = verifier.verify_proof(proof, [True, True])
print(f"Both statements proven: {is_valid}")
```

### Example 10: Batch Verification

Verify multiple proofs efficiently.

```python
from ipfs_datasets_py.logic.zkp import BooleanCircuit, ZKPProver, ZKPVerifier

# Create reusable circuit
circuit = BooleanCircuit()
w1, w2, w3 = [circuit.add_wire() for _ in range(3)]
circuit.add_gate('AND', [w1, w2], w3)
circuit.set_private_input(w1)
circuit.set_private_input(w2)
circuit.set_public_input(w3)

prover = ZKPProver(circuit)
verifier = ZKPVerifier(prover.get_verification_key())

# Generate multiple proofs
proofs = []
witnesses = [
    ({w1: True, w2: True}, [True]),
    ({w1: True, w2: False}, [False]),
    ({w1: False, w2: True}, [False]),
]

for witness, public_inputs in witnesses:
    proof = prover.generate_proof(witness, public_inputs)
    proofs.append((proof, public_inputs))

# Verify in batch
results = [verifier.verify_proof(p, pi) for p, pi in proofs]
print(f"Batch results: {results}")  # [True, True, True]
print(f"All valid: {all(results)}")
```

## Integration Examples

### Example 11: IPFS Storage Integration

Store and retrieve proofs via IPFS.

```python
from ipfs_datasets_py.logic.zkp import BooleanCircuit, ZKPProver, ZKPVerifier
import json

# Generate proof
circuit = BooleanCircuit()
w1, w2, w3 = [circuit.add_wire() for _ in range(3)]
circuit.add_gate('AND', [w1, w2], w3)
circuit.set_private_input(w1)
circuit.set_private_input(w2)
circuit.set_public_input(w3)

prover = ZKPProver(circuit)
witness = {w1: True, w2: True}
proof = prover.generate_proof(witness, [True])

# Store proof in IPFS
try:
    from ipfs_datasets_py import IPFSDatasets
    
    ipfs_ds = IPFSDatasets()
    
    # Serialize proof
    proof_json = json.dumps(proof)
    
    # Add to IPFS
    result = ipfs_ds.ipfs_client.add_json(proof_json)
    cid = result['Hash']
    print(f"Proof stored at: {cid}")
    
    # Retrieve and verify
    retrieved_proof_json = ipfs_ds.ipfs_client.get_json(cid)
    retrieved_proof = json.loads(retrieved_proof_json)
    
    verifier = ZKPVerifier(prover.get_verification_key())
    is_valid = verifier.verify_proof(retrieved_proof, [True])
    print(f"Retrieved proof valid: {is_valid}")
    
except ImportError:
    print("IPFS integration requires ipfs_datasets_py configured")
```

### Example 12: FOL Integration

Convert First-Order Logic to ZKP circuit.

```python
# Note: This is a simplified example
# Real FOL->ZKP conversion is complex

from ipfs_datasets_py.logic.zkp import BooleanCircuit, ZKPProver, ZKPVerifier

def fol_to_circuit(formula):
    """
    Convert simple FOL formula to circuit.
    Example: "P AND Q" -> circuit with AND gate
    """
    circuit = BooleanCircuit()
    
    if "AND" in formula:
        # Parse "P AND Q"
        p_wire = circuit.add_wire()
        q_wire = circuit.add_wire()
        result_wire = circuit.add_wire()
        
        circuit.set_private_input(p_wire)
        circuit.set_private_input(q_wire)
        circuit.add_gate('AND', [p_wire, q_wire], result_wire)
        circuit.set_public_input(result_wire)
        
        return circuit, [p_wire, q_wire]
    
    raise NotImplementedError("Only simple AND supported")

# Use FOL formula
formula = "P AND Q"
circuit, input_wires = fol_to_circuit(formula)

# Prove P=True, Q=True satisfies formula
prover = ZKPProver(circuit)
witness = {input_wires[0]: True, input_wires[1]: True}
proof = prover.generate_proof(witness, [True])

verifier = ZKPVerifier(prover.get_verification_key())
print(f"FOL formula proven: {verifier.verify_proof(proof, [True])}")
```

## Error Handling Examples

### Example 13: Handling Invalid Witness

```python
from ipfs_datasets_py.logic.zkp import BooleanCircuit, ZKPProver

circuit = BooleanCircuit()
w1, w2, w3 = [circuit.add_wire() for _ in range(3)]
circuit.add_gate('AND', [w1, w2], w3)
circuit.set_private_input(w1)
circuit.set_private_input(w2)
circuit.set_public_input(w3)

prover = ZKPProver(circuit)

# Invalid: witness doesn't satisfy circuit
# (True AND False = False, but we claim True!)
witness = {w1: True, w2: False}

try:
    proof = prover.generate_proof(witness, [True])  # Should be [False]
    print("Proof generated (shouldn't happen!)")
except ValueError as e:
    print(f"Caught invalid witness: {e}")
```

### Example 14: Handling Verification Failure

```python
from ipfs_datasets_py.logic.zkp import BooleanCircuit, ZKPProver, ZKPVerifier

circuit = BooleanCircuit()
w1, w2, w3 = [circuit.add_wire() for _ in range(3)]
circuit.add_gate('AND', [w1, w2], w3)
circuit.set_private_input(w1)
circuit.set_private_input(w2)
circuit.set_public_input(w3)

prover = ZKPProver(circuit)
verifier = ZKPVerifier(prover.get_verification_key())

# Generate valid proof
witness = {w1: True, w2: True}
proof = prover.generate_proof(witness, [True])

# Verify with wrong public inputs
is_valid = verifier.verify_proof(proof, [False])  # Wrong! Should be [True]
if not is_valid:
    print("Verification failed: public input mismatch")
    print(f"Proof claims: {proof['public_inputs']}")
    print(f"Verifier expects: [False]")
```

### Example 15: Graceful Degradation

```python
from ipfs_datasets_py.logic.zkp import BooleanCircuit, ZKPProver, ZKPVerifier
import logging

# Enable logging
logging.basicConfig(level=logging.WARNING)

def safe_verify(verifier, proof, public_inputs):
    """Verify with error handling."""
    try:
        return verifier.verify_proof(proof, public_inputs)
    except KeyError as e:
        logging.error(f"Malformed proof: missing key {e}")
        return False
    except TypeError as e:
        logging.error(f"Type error: {e}")
        return False
    except Exception as e:
        logging.error(f"Unexpected error: {e}")
        return False

# Test with various inputs
circuit = BooleanCircuit()
w = circuit.add_wire()
circuit.set_public_input(w)

prover = ZKPProver(circuit)
verifier = ZKPVerifier(prover.get_verification_key())

# Valid proof
proof = prover.generate_proof({w: True}, [True])
print(f"Valid proof: {safe_verify(verifier, proof, [True])}")

# Corrupted proof
corrupted_proof = proof.copy()
del corrupted_proof['proof_a']
print(f"Corrupted proof: {safe_verify(verifier, corrupted_proof, [True])}")
```

## Performance Examples

### Example 16: Performance Profiling

```python
import time
from ipfs_datasets_py.logic.zkp import BooleanCircuit, ZKPProver, ZKPVerifier

def profile_zkp_performance(num_gates):
    """Profile ZKP performance vs circuit size."""
    
    # Build circuit with num_gates AND gates
    circuit = BooleanCircuit()
    wires = [circuit.add_wire() for _ in range(num_gates + 1)]
    
    for w in wires[:-1]:
        circuit.set_private_input(w)
    
    for i in range(num_gates):
        circuit.add_gate('AND', [wires[i], wires[i]], wires[-1])
    
    circuit.set_public_input(wires[-1])
    
    # Profile proving
    prover = ZKPProver(circuit)
    witness = {w: True for w in wires[:-1]}
    
    start = time.time()
    proof = prover.generate_proof(witness, [True])
    prove_time = time.time() - start
    
    # Profile verification
    verifier = ZKPVerifier(prover.get_verification_key())
    start = time.time()
    verifier.verify_proof(proof, [True])
    verify_time = time.time() - start
    
    return prove_time, verify_time, len(json.dumps(proof))

# Test different circuit sizes
print("Gates | Prove (ms) | Verify (ms) | Proof Size (bytes)")
print("-" * 60)
for num_gates in [10, 50, 100, 500, 1000]:
    prove_t, verify_t, size = profile_zkp_performance(num_gates)
    print(f"{num_gates:5d} | {prove_t*1000:10.2f} | {verify_t*1000:11.2f} | {size:11d}")
```

## Best Practices

### ✅ DO: Always Validate Witnesses

```python
# Good: Validate before proving
def validate_witness(circuit, witness):
    try:
        result = circuit.evaluate(witness)
        return True
    except Exception as e:
        print(f"Invalid witness: {e}")
        return False

if validate_witness(circuit, witness):
    proof = prover.generate_proof(witness, public_inputs)
```

### ✅ DO: Cache Keys

```python
# Good: Reuse proving/verification keys
proving_key = prover.get_proving_key()
verification_key = prover.get_verification_key()

# Save for later
import pickle
with open('keys.pkl', 'wb') as f:
    pickle.dump({'proving': proving_key, 'verification': verification_key}, f)
```

### ✅ DO: Use Batch Verification

```python
# Good: Verify multiple proofs together
proofs_and_inputs = [(proof1, [True]), (proof2, [False]), (proof3, [True])]
results = [verifier.verify_proof(p, pi) for p, pi in proofs_and_inputs]
all_valid = all(results)
```

### ❌ DON'T: Trust Proofs in Production

```python
# Bad: Using simulation proofs for access control
if verifier.verify_proof(proof, [user_id]):
    grant_access(user)  # DON'T! Simulation proofs are not secure!

# Good: Use real cryptography for production
# See PRODUCTION_UPGRADE_PATH.md
```

### ❌ DON'T: Ignore Verification Failures

```python
# Bad: Assuming proofs always valid
proof = prover.generate_proof(witness, public_inputs)
# ... use proof without checking ...

# Good: Always verify
is_valid = verifier.verify_proof(proof, public_inputs)
if not is_valid:
    raise ValueError("Invalid proof generated!")
```

## See Also

- [QUICKSTART.md](QUICKSTART.md) - Quick introduction
- [IMPLEMENTATION_GUIDE.md](IMPLEMENTATION_GUIDE.md) - Technical details
- [INTEGRATION_GUIDE.md](INTEGRATION_GUIDE.md) - Integration patterns
- [SECURITY_CONSIDERATIONS.md](SECURITY_CONSIDERATIONS.md) - Security analysis
- [PRODUCTION_UPGRADE_PATH.md](PRODUCTION_UPGRADE_PATH.md) - Production upgrade

---

**Remember**: These examples use simulation ZKPs for education and testing. Always use real cryptographic libraries for production systems!
