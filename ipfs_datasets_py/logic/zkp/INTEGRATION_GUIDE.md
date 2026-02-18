# ZKP Module Integration Guide

## Overview

This guide explains how to integrate the ZKP module with other components of the `ipfs_datasets_py` logic module and external systems.

**Target Audience:** Developers integrating ZKP functionality into larger systems.

## Table of Contents

1. [Integration with Logic Module Components](#integration-with-logic-module-components)
2. [Integration with Storage Systems](#integration-with-storage-systems)
3. [Integration Patterns](#integration-patterns)
4. [Best Practices](#best-practices)
5. [Common Pitfalls](#common-pitfalls)
6. [Performance Considerations](#performance-considerations)

## Integration with Logic Module Components

### 1. First-Order Logic (FOL) Integration

Convert FOL formulas to ZKP circuits for zero-knowledge proofs.

```python
from ipfs_datasets_py.logic.fol import FOLConverter
from ipfs_datasets_py.logic.zkp import BooleanCircuit, ZKPProver, ZKPVerifier

class FOLZKPBridge:
    """Bridge FOL and ZKP modules."""
    
    def __init__(self):
        self.fol_converter = FOLConverter()
    
    def prove_fol_formula(self, formula: str, variable_assignment: dict):
        """
        Generate ZKP that formula is satisfied by assignment.
        
        Args:
            formula: FOL formula string (e.g., "P(x) AND Q(x)")
            variable_assignment: Variable values (e.g., {"x": "a", "P": True})
        
        Returns:
            Proof that formula is satisfied
        """
        # Convert FOL to circuit
        circuit = self._fol_to_circuit(formula)
        
        # Generate proof
        prover = ZKPProver(circuit)
        witness = self._assignment_to_witness(circuit, variable_assignment)
        proof = prover.generate_proof(witness, [True])
        
        return proof, prover.get_verification_key()
    
    def _fol_to_circuit(self, formula: str) -> BooleanCircuit:
        """Convert FOL formula to boolean circuit."""
        # Parse formula
        parsed = self.fol_converter.parse(formula)
        
        # Build circuit from parse tree
        circuit = BooleanCircuit()
        # ... implementation depends on FOL structure ...
        
        return circuit
    
    def _assignment_to_witness(self, circuit, assignment):
        """Map variable assignment to circuit witness."""
        witness = {}
        # ... map FOL variables to circuit wires ...
        return witness

# Usage
bridge = FOLZKPBridge()
formula = "forall x. P(x) -> Q(x)"
assignment = {"x": "a", "P(a)": True, "Q(a)": True}
proof, vk = bridge.prove_fol_formula(formula, assignment)
```

### 2. Deontic Logic Integration

Prove compliance with deontic obligations using ZKP.

```python
from ipfs_datasets_py.logic.deontic import DeonticReasoner
from ipfs_datasets_py.logic.zkp import BooleanCircuit, ZKPProver, ZKPVerifier

class DeonticZKPBridge:
    """Bridge Deontic Logic and ZKP."""
    
    def __init__(self):
        self.reasoner = DeonticReasoner()
    
    def prove_obligation_satisfied(self, obligation: str, actions: list):
        """
        Prove that actions satisfy obligation without revealing actions.
        
        Args:
            obligation: Deontic formula (e.g., "O(action1 OR action2)")
            actions: List of performed actions (private)
        
        Returns:
            ZKP that obligation is satisfied
        """
        # Check obligation satisfied
        satisfied = self.reasoner.check_obligation(obligation, actions)
        
        if not satisfied:
            raise ValueError("Obligation not satisfied!")
        
        # Build circuit
        circuit = self._obligation_to_circuit(obligation, len(actions))
        
        # Generate proof
        prover = ZKPProver(circuit)
        witness = {i: action in actions for i, action in enumerate(actions)}
        proof = prover.generate_proof(witness, [True])
        
        return proof, prover.get_verification_key()
    
    def _obligation_to_circuit(self, obligation: str, num_actions: int):
        """Convert deontic obligation to circuit."""
        circuit = BooleanCircuit()
        
        # Create wires for each possible action
        action_wires = [circuit.add_wire() for _ in range(num_actions)]
        for wire in action_wires:
            circuit.set_private_input(wire)
        
        # Build logic for obligation
        # O(A OR B) -> at least one action performed
        result = circuit.add_wire()
        # ... build OR of all action wires ...
        circuit.set_public_input(result)
        
        return circuit

# Usage
bridge = DeonticZKPBridge()
obligation = "O(report_incident OR escalate)"
actions = ["report_incident"]  # Private
proof, vk = bridge.prove_obligation_satisfied(obligation, actions)

# Verifier can check compliance without knowing which action
verifier = ZKPVerifier(vk)
is_compliant = verifier.verify_proof(proof, [True])
```

### 3. Temporal Logic Integration

Prove temporal properties hold over time.

```python
from ipfs_datasets_py.logic.temporal import TemporalReasoner
from ipfs_datasets_py.logic.zkp import BooleanCircuit, ZKPProver

class TemporalZKPBridge:
    """Bridge Temporal Logic and ZKP."""
    
    def prove_temporal_property(self, formula: str, trace: list):
        """
        Prove temporal formula holds for trace without revealing trace.
        
        Args:
            formula: LTL formula (e.g., "G(request -> F(response))")
            trace: Sequence of states (private)
        
        Returns:
            ZKP that formula holds
        """
        circuit = self._ltl_to_circuit(formula, len(trace))
        prover = ZKPProver(circuit)
        
        # Encode trace as witness
        witness = self._trace_to_witness(trace)
        proof = prover.generate_proof(witness, [True])
        
        return proof, prover.get_verification_key()
    
    def _ltl_to_circuit(self, formula: str, trace_length: int):
        """Convert LTL formula to circuit for trace length."""
        circuit = BooleanCircuit()
        # ... build circuit that checks LTL formula ...
        return circuit
    
    def _trace_to_witness(self, trace: list):
        """Encode trace as circuit witness."""
        witness = {}
        for i, state in enumerate(trace):
            # Encode state variables
            for var, value in state.items():
                witness[(i, var)] = value
        return witness

# Usage
bridge = TemporalZKPBridge()
formula = "G(request -> F(response))"  # Always: request eventually gets response
trace = [
    {"request": False, "response": False},
    {"request": True, "response": False},
    {"request": True, "response": True},  # Request satisfied
]
proof, vk = bridge.prove_temporal_property(formula, trace)
```

### 4. Modal Logic Integration

Prove knowledge/belief properties.

```python
from ipfs_datasets_py.logic.modal import ModalReasoner
from ipfs_datasets_py.logic.zkp import BooleanCircuit, ZKPProver

class ModalZKPBridge:
    """Bridge Modal Logic and ZKP."""
    
    def prove_knowledge(self, formula: str, world_knowledge: dict):
        """
        Prove knowledge of formula without revealing what you know.
        
        Args:
            formula: Modal formula (e.g., "K(p AND q)")
            world_knowledge: Known facts (private)
        
        Returns:
            ZKP of knowledge
        """
        circuit = self._modal_to_circuit(formula)
        prover = ZKPProver(circuit)
        
        witness = self._knowledge_to_witness(world_knowledge)
        proof = prover.generate_proof(witness, [True])
        
        return proof, prover.get_verification_key()
    
    def _modal_to_circuit(self, formula: str):
        """Convert modal formula to circuit."""
        circuit = BooleanCircuit()
        # K(p) means "know p" - build circuit checking p is known
        # ... implementation ...
        return circuit
    
    def _knowledge_to_witness(self, knowledge: dict):
        """Encode knowledge as witness."""
        return {k: v for k, v in knowledge.items()}

# Usage
bridge = ModalZKPBridge()
formula = "K(secret_key)"
knowledge = {"secret_key": True, "other_fact": False}  # Private
proof, vk = bridge.prove_knowledge(formula, knowledge)
```

### 5. Datalog Integration

Prove query results without revealing database.

```python
from ipfs_datasets_py.logic.datalog import DatalogEngine
from ipfs_datasets_py.logic.zkp import BooleanCircuit, ZKPProver

class DatalogZKPBridge:
    """Bridge Datalog and ZKP."""
    
    def prove_query_result(self, query: str, database: list, result: bool):
        """
        Prove query has specific result without revealing database.
        
        Args:
            query: Datalog query
            database: Facts (private)
            result: Query result (public)
        
        Returns:
            ZKP that query returns result
        """
        circuit = self._query_to_circuit(query, len(database))
        prover = ZKPProver(circuit)
        
        witness = self._database_to_witness(database)
        proof = prover.generate_proof(witness, [result])
        
        return proof, prover.get_verification_key()
    
    def _query_to_circuit(self, query: str, db_size: int):
        """Convert Datalog query to circuit."""
        circuit = BooleanCircuit()
        # Build circuit evaluating query over database
        # ... implementation ...
        return circuit
    
    def _database_to_witness(self, database: list):
        """Encode database as witness."""
        witness = {}
        for i, fact in enumerate(database):
            witness[i] = fact
        return witness

# Usage
bridge = DatalogZKPBridge()
query = "ancestor(X, Y)"
database = [  # Private
    ("parent", "alice", "bob"),
    ("parent", "bob", "charlie"),
]
result = True  # Yes, there are ancestors

proof, vk = bridge.prove_query_result(query, database, result)
```

### 6. ZKP-Specific Logic Operations

Helper functions for common ZKP patterns.

```python
from ipfs_datasets_py.logic.zkp import BooleanCircuit, ZKPProver, ZKPVerifier

class ZKPLogicHelper:
    """Helper functions for ZKP logic operations."""
    
    @staticmethod
    def prove_set_membership(element, set_elements, public_set_size):
        """
        Prove element is in set without revealing which element.
        
        Args:
            element: Element to prove membership of (private)
            set_elements: All possible elements (private)
            public_set_size: Size of set (public)
        
        Returns:
            Membership proof
        """
        circuit = BooleanCircuit()
        
        # Create wire for each set element
        element_wires = [circuit.add_wire() for _ in range(public_set_size)]
        for wire in element_wires:
            circuit.set_private_input(wire)
        
        # At least one must be True (element matches)
        result = circuit.add_wire()
        # Build OR of all element_wires
        # ... implementation ...
        circuit.set_public_input(result)
        
        prover = ZKPProver(circuit)
        witness = {i: (elem == element) for i, elem in enumerate(set_elements)}
        proof = prover.generate_proof(witness, [True])
        
        return proof, prover.get_verification_key()
    
    @staticmethod
    def prove_range(value, min_val, max_val):
        """
        Prove value is in range [min, max] without revealing value.
        
        Args:
            value: Value to prove (private)
            min_val: Minimum (public)
            max_val: Maximum (public)
        
        Returns:
            Range proof
        """
        # Convert to binary and build range circuit
        # ... implementation ...
        pass
    
    @staticmethod
    def prove_computation(inputs, computation_fn, expected_output):
        """
        Prove computation(inputs) = expected_output.
        
        Args:
            inputs: Private inputs
            computation_fn: Function to prove
            expected_output: Public output
        
        Returns:
            Computation proof
        """
        # Build circuit for computation
        # ... implementation ...
        pass

# Usage
helper = ZKPLogicHelper()
proof, vk = helper.prove_set_membership(
    element="alice",
    set_elements=["alice", "bob", "charlie"],
    public_set_size=3
)
```

## Integration with Storage Systems

### IPFS Integration

Store and retrieve ZKP proofs via IPFS.

```python
from ipfs_datasets_py.logic.zkp import ZKPProver, ZKPVerifier
from ipfs_datasets_py import IPFSDatasets
import json

class ZKPIPFSBridge:
    """Store ZKP proofs in IPFS."""
    
    def __init__(self):
        self.ipfs = IPFSDatasets()
    
    def store_proof(self, proof, verification_key):
        """Store proof and verification key in IPFS."""
        data = {
            'proof': proof,
            'verification_key': verification_key
        }
        
        # Serialize and store
        json_data = json.dumps(data)
        result = self.ipfs.ipfs_client.add_json(json_data)
        cid = result['Hash']
        
        return cid
    
    def retrieve_and_verify(self, cid, expected_public_inputs):
        """Retrieve proof from IPFS and verify."""
        # Retrieve
        json_data = self.ipfs.ipfs_client.get_json(cid)
        data = json.loads(json_data)
        
        # Verify
        verifier = ZKPVerifier(data['verification_key'])
        is_valid = verifier.verify_proof(data['proof'], expected_public_inputs)
        
        return is_valid

# Usage
bridge = ZKPIPFSBridge()

# Store proof
cid = bridge.store_proof(proof, verification_key)
print(f"Proof stored at IPFS CID: {cid}")

# Later: retrieve and verify
is_valid = bridge.retrieve_and_verify(cid, expected_public_inputs=[True])
```

## Integration Patterns

### Pattern 1: Proof Pipeline

Chain multiple ZKP operations.

```python
class ZKPPipeline:
    """Pipeline for chained ZKP operations."""
    
    def __init__(self):
        self.stages = []
    
    def add_stage(self, circuit, witness_fn):
        """Add pipeline stage."""
        self.stages.append((circuit, witness_fn))
    
    def execute(self, initial_input):
        """Execute pipeline, generating proofs at each stage."""
        proofs = []
        current_input = initial_input
        
        for circuit, witness_fn in self.stages:
            # Generate witness from current input
            witness = witness_fn(current_input)
            
            # Generate proof
            prover = ZKPProver(circuit)
            proof = prover.generate_proof(witness, [True])
            proofs.append(proof)
            
            # Update input for next stage
            current_input = self._extract_next_input(proof)
        
        return proofs
    
    def _extract_next_input(self, proof):
        """Extract public outputs as input for next stage."""
        return proof['public_inputs']

# Usage
pipeline = ZKPPipeline()
pipeline.add_stage(circuit1, lambda x: {...})
pipeline.add_stage(circuit2, lambda x: {...})
proofs = pipeline.execute(initial_data)
```

### Pattern 2: Proof Aggregation

Combine multiple proofs into one.

```python
class ZKPAggregator:
    """Aggregate multiple ZKP proofs."""
    
    def aggregate(self, proofs, public_inputs_list):
        """
        Create single proof proving all sub-proofs valid.
        
        Note: This is simplified. Real aggregation requires
        proof-carrying data or recursive SNARKs.
        """
        # Build aggregation circuit
        circuit = BooleanCircuit()
        
        # Add verification logic for each proof
        for i, (proof, public_inputs) in enumerate(zip(proofs, public_inputs_list)):
            # Encode verification as circuit constraints
            # ... implementation ...
            pass
        
        # Generate aggregate proof
        prover = ZKPProver(circuit)
        witness = self._proofs_to_witness(proofs)
        aggregate_proof = prover.generate_proof(witness, [True])
        
        return aggregate_proof

# Usage
aggregator = ZKPAggregator()
aggregate = aggregator.aggregate([proof1, proof2, proof3], public_inputs_list)
```

### Pattern 3: Proof Middleware

Intercept and process proofs.

```python
class ZKPMiddleware:
    """Middleware for proof generation/verification."""
    
    def __init__(self):
        self.before_prove_hooks = []
        self.after_prove_hooks = []
        self.before_verify_hooks = []
        self.after_verify_hooks = []
    
    def add_before_prove(self, hook):
        """Add hook called before proof generation."""
        self.before_prove_hooks.append(hook)
    
    def add_after_prove(self, hook):
        """Add hook called after proof generation."""
        self.after_prove_hooks.append(hook)
    
    def prove(self, prover, witness, public_inputs):
        """Generate proof with middleware."""
        # Before hooks
        for hook in self.before_prove_hooks:
            hook(prover, witness, public_inputs)
        
        # Generate proof
        proof = prover.generate_proof(witness, public_inputs)
        
        # After hooks
        for hook in self.after_prove_hooks:
            hook(proof)
        
        return proof
    
    def verify(self, verifier, proof, public_inputs):
        """Verify proof with middleware."""
        # Before hooks
        for hook in self.before_verify_hooks:
            hook(verifier, proof, public_inputs)
        
        # Verify
        is_valid = verifier.verify_proof(proof, public_inputs)
        
        # After hooks
        for hook in self.after_verify_hooks:
            hook(is_valid)
        
        return is_valid

# Usage
middleware = ZKPMiddleware()
middleware.add_before_prove(lambda p, w, pi: print("Proving..."))
middleware.add_after_prove(lambda proof: log_proof(proof))
proof = middleware.prove(prover, witness, public_inputs)
```

## Best Practices

### 1. Separate Concerns

Keep ZKP logic separate from business logic:

```python
# Good: Clear separation
class BusinessLogic:
    def process_data(self, data):
        result = self.compute(data)
        return result

class ZKPLayer:
    def prove_computation(self, business_logic, data, result):
        circuit = self.build_circuit_for(business_logic)
        proof = self.generate_proof(circuit, data, result)
        return proof
```

### 2. Use Adapters

Create adapters for clean integration:

```python
class FOLToZKPAdapter:
    """Adapter between FOL and ZKP modules."""
    
    def adapt_formula(self, fol_formula):
        """Convert FOL to ZKP circuit."""
        pass
    
    def adapt_witness(self, fol_assignment):
        """Convert FOL assignment to ZKP witness."""
        pass
```

### 3. Handle Errors Gracefully

```python
try:
    proof = prover.generate_proof(witness, public_inputs)
except ValueError as e:
    logger.error(f"Proof generation failed: {e}")
    # Fallback or retry logic
```

### 4. Cache Expensive Operations

```python
# Cache verification keys
@lru_cache(maxsize=100)
def get_verification_key(circuit_hash):
    return verification_keys[circuit_hash]
```

## Common Pitfalls

### ❌ Pitfall 1: Ignoring Simulation Limits

```python
# Bad: Using for access control
if zkp_verify(proof):
    grant_admin_access()  # Insecure!
```

### ❌ Pitfall 2: Exposing Private Data

```python
# Bad: Logging witness
logger.info(f"Witness: {witness}")  # Don't log secrets!
```

### ❌ Pitfall 3: Mismatched Public Inputs

```python
# Bad: Using wrong public inputs
proof = prover.generate_proof(witness, [True])
verifier.verify_proof(proof, [False])  # Will fail!
```

## Performance Considerations

### 1. Circuit Optimization

Minimize circuit complexity:

```python
# Bad: Redundant gates
for i in range(100):
    circuit.add_gate('AND', [w1, w2], w3)

# Good: Single gate
circuit.add_gate('AND', [w1, w2], w3)
```

### 2. Batch Operations

Process multiple proofs together:

```python
# Verify multiple proofs
results = [verifier.verify_proof(p, pi) for p, pi in proof_list]
```

### 3. Lazy Evaluation

Generate proofs only when needed:

```python
def get_proof():
    if not hasattr(get_proof, 'cached_proof'):
        get_proof.cached_proof = prover.generate_proof(witness, public_inputs)
    return get_proof.cached_proof
```

## See Also

- [EXAMPLES.md](EXAMPLES.md) - Usage examples
- [IMPLEMENTATION_GUIDE.md](IMPLEMENTATION_GUIDE.md) - Technical details
- [SECURITY_CONSIDERATIONS.md](SECURITY_CONSIDERATIONS.md) - Security analysis
- [PRODUCTION_UPGRADE_PATH.md](PRODUCTION_UPGRADE_PATH.md) - Production upgrade

---

**Remember**: This module provides simulation ZKPs for education and testing. Always use real cryptographic libraries for production!
