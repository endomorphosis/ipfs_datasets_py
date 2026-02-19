"""
Zero-Knowledge Proof Circuits for Logic Operations.

Defines arithmetic circuits that can be used to create zero-knowledge
proofs for various logic operations, and MVP circuits for statement proving.
"""

from typing import List, Dict, Any, Tuple
from dataclasses import dataclass
from typing import Any, Dict

from .canonicalization import canonicalize_axioms, hash_axioms_commitment, tdfol_v1_axioms_commitment_hex_v2
from .canonicalization import hash_theorem
from .statement import Statement, Witness
from .legal_theorem_semantics import parse_tdfol_v1_axiom, parse_tdfol_v1_theorem
import hashlib


@dataclass
class CircuitGate:
    """
    A single gate in a logic circuit.
    
    Attributes:
        gate_type: Type of gate (AND, OR, NOT, IMPLIES, etc.)
        inputs: Input wire indices
        output: Output wire index
    """
    gate_type: str
    inputs: List[int]
    output: int


class ZKPCircuit:
    """
    Arithmetic circuit for zero-knowledge proofs of logic formulas.
    
    Converts logic operations into arithmetic circuits over finite fields,
    which can then be proven using zkSNARKs.
    
    Example:
        >>> circuit = ZKPCircuit()
        >>> # Create circuit for: (P AND Q) IMPLIES R
        >>> p_wire = circuit.add_input("P")
        >>> q_wire = circuit.add_input("Q")
        >>> r_wire = circuit.add_input("R")
        >>> pq_wire = circuit.add_and_gate(p_wire, q_wire)
        >>> output = circuit.add_implies_gate(pq_wire, r_wire)
        >>> circuit.set_output(output)
        >>> 
        >>> print(f"Circuit has {circuit.num_gates()} gates")
        Circuit has 3 gates
    
    Note:
        This is a high-level circuit representation. For actual zkSNARK
        proving, the circuit would be compiled to R1CS (Rank-1 Constraint
        System) constraints over a finite field.
    """
    
    def __init__(self):
        """Initialize empty circuit."""
        self._gates: List[CircuitGate] = []
        self._inputs: Dict[str, int] = {}  # name -> wire index
        self._outputs: List[int] = []
        self._next_wire: int = 0
    
    def add_input(self, name: str) -> int:
        """
        Add an input wire to the circuit.
        
        Args:
            name: Name of the input (e.g., "P", "Q")
        
        Returns:
            int: Wire index for this input
        """
        wire = self._next_wire
        self._next_wire += 1
        self._inputs[name] = wire
        return wire
    
    def add_and_gate(self, wire_a: int, wire_b: int) -> int:
        """
        Add an AND gate to the circuit.
        
        In arithmetic circuits over finite fields:
            AND(a, b) = a * b
        
        Args:
            wire_a: First input wire
            wire_b: Second input wire
        
        Returns:
            int: Output wire index
        """
        output_wire = self._next_wire
        self._next_wire += 1
        
        self._gates.append(CircuitGate(
            gate_type="AND",
            inputs=[wire_a, wire_b],
            output=output_wire
        ))
        
        return output_wire
    
    def add_or_gate(self, wire_a: int, wire_b: int) -> int:
        """
        Add an OR gate to the circuit.
        
        In arithmetic circuits:
            OR(a, b) = a + b - (a * b)
        
        Args:
            wire_a: First input wire
            wire_b: Second input wire
        
        Returns:
            int: Output wire index
        """
        output_wire = self._next_wire
        self._next_wire += 1
        
        self._gates.append(CircuitGate(
            gate_type="OR",
            inputs=[wire_a, wire_b],
            output=output_wire
        ))
        
        return output_wire
    
    def add_not_gate(self, wire: int) -> int:
        """
        Add a NOT gate to the circuit.
        
        In arithmetic circuits:
            NOT(a) = 1 - a
        
        Args:
            wire: Input wire
        
        Returns:
            int: Output wire index
        """
        output_wire = self._next_wire
        self._next_wire += 1
        
        self._gates.append(CircuitGate(
            gate_type="NOT",
            inputs=[wire],
            output=output_wire
        ))
        
        return output_wire
    
    def add_implies_gate(self, wire_a: int, wire_b: int) -> int:
        """
        Add an IMPLIES gate to the circuit.
        
        In logic: A -> B = (NOT A) OR B
        In arithmetic: IMPLIES(a, b) = (1 - a) + b - ((1 - a) * b)
        
        Args:
            wire_a: Antecedent wire
            wire_b: Consequent wire
        
        Returns:
            int: Output wire index
        """
        output_wire = self._next_wire
        self._next_wire += 1
        
        self._gates.append(CircuitGate(
            gate_type="IMPLIES",
            inputs=[wire_a, wire_b],
            output=output_wire
        ))
        
        return output_wire
    
    def add_xor_gate(self, wire_a: int, wire_b: int) -> int:
        """
        Add an XOR gate to the circuit.
        
        In arithmetic: XOR(a, b) = a + b - 2(a * b)
        
        Args:
            wire_a: First input wire
            wire_b: Second input wire
        
        Returns:
            int: Output wire index
        """
        output_wire = self._next_wire
        self._next_wire += 1
        
        self._gates.append(CircuitGate(
            gate_type="XOR",
            inputs=[wire_a, wire_b],
            output=output_wire
        ))
        
        return output_wire
    
    def set_output(self, wire: int):
        """
        Mark a wire as a circuit output.
        
        Args:
            wire: Wire index to mark as output
        """
        self._outputs.append(wire)
    
    def num_gates(self) -> int:
        """Get the number of gates in the circuit."""
        return len(self._gates)
    
    def num_inputs(self) -> int:
        """Get the number of input wires."""
        return len(self._inputs)
    
    def num_wires(self) -> int:
        """Get the total number of wires."""
        return self._next_wire
    
    def get_circuit_hash(self) -> str:
        """
        Compute a hash of the circuit structure.
        
        Returns:
            str: Hex-encoded hash of circuit
        """
        circuit_data = {
            'num_gates': len(self._gates),
            'num_inputs': len(self._inputs),
            'num_wires': self._next_wire,
            'gates': [
                {
                    'type': gate.gate_type,
                    'inputs': gate.inputs,
                    'output': gate.output
                }
                for gate in self._gates
            ],
        }
        
        import json
        circuit_json = json.dumps(circuit_data, sort_keys=True)
        return hashlib.sha256(circuit_json.encode()).hexdigest()
    
    def to_r1cs(self) -> Dict[str, Any]:
        """
        Convert circuit to R1CS (Rank-1 Constraint System).
        
        R1CS is the constraint system used by zkSNARKs like Groth16.
        Each constraint has the form: (A · w) * (B · w) = (C · w)
        where w is the witness vector.
        
        Returns:
            dict: R1CS representation with A, B, C matrices
        
        Note:
            This is a simplified representation. Real R1CS compilation
            would produce sparse matrices over a finite field.
        """
        # Simplified R1CS representation
        constraints = []
        
        for gate in self._gates:
            if gate.gate_type == "AND":
                # a * b = c
                constraints.append({
                    'type': 'multiplication',
                    'A': gate.inputs[0],
                    'B': gate.inputs[1],
                    'C': gate.output,
                })
            elif gate.gate_type == "OR":
                # OR(a,b) = a + b - a*b
                # Needs multiple constraints
                constraints.append({
                    'type': 'or_composition',
                    'inputs': gate.inputs,
                    'output': gate.output,
                })
            # Other gate types...
        
        return {
            'num_constraints': len(constraints),
            'num_variables': self._next_wire,
            'constraints': constraints,
            'public_inputs': list(self._outputs),
        }
    
    def __repr__(self) -> str:
        return (
            f"ZKPCircuit("
            f"inputs={self.num_inputs()}, "
            f"gates={self.num_gates()}, "
            f"wires={self.num_wires()})"
        )

# MVP (Minimum Viable Proof) Circuit Support
# ==========================================

@dataclass
class MVPCircuit:
    """
    Minimum Viable Proof circuit for knowledge-of-axioms.
    
    Circuit statement: "I know a set of axioms whose SHA256 commitment matches X."
    
    This is a non-cryptographic first implementation.
    In production, this would be compiled to R1CS / arithmetic constraints.
    """
    
    circuit_version: int = 1
    circuit_type: str = "knowledge_of_axioms"
    
    def num_inputs(self) -> int:
        """Number of public input field elements."""
        return 4  # theorem_hash, axioms_commitment, circuit_version, ruleset_id
    
    def num_constraints(self) -> int:
        """Number of constraints in circuit."""
        return 1  # commitment check constraint
    
    def compile(self) -> Dict[str, Any]:
        """
        Compile circuit to schema (JSON representation).
        
        In production, this would generate R1CS or other constraint format.
        
        Returns:
            Dictionary describing circuit structure
        """
        return {
            'version': self.circuit_version,
            'type': self.circuit_type,
            'num_inputs': self.num_inputs(),
            'num_constraints': self.num_constraints(),
            'description': 'Prove knowledge of axioms matching a commitment',
        }

    def verify_constraints(self, witness: Witness, statement: Statement) -> bool:
        """Evaluate MVP constraints for the given witness and statement.

        This provides a concrete, non-cryptographic constraint evaluation path
        for the MVP circuit. It is intentionally strict and fail-closed.

        Constraints (v1):
        - circuit version matches
        - ruleset_id matches
        - SHA256(canonicalize_axioms(witness.axioms)) == statement.axioms_commitment
        - witness.axioms_commitment_hex matches the same computed commitment
        """
        try:
            if statement.circuit_version != self.circuit_version:
                return False
            if witness.circuit_version != statement.circuit_version:
                return False
            if witness.ruleset_id != statement.ruleset_id:
                return False

            canonical_axioms = canonicalize_axioms(witness.axioms)
            if witness.axioms != canonical_axioms:
                return False
            expected_commitment_hex = hash_axioms_commitment(canonical_axioms).hex()

            if statement.axioms_commitment != expected_commitment_hex:
                return False
            if witness.axioms_commitment_hex != expected_commitment_hex:
                return False

            return True
        except (AttributeError, TypeError, ValueError):
            return False


def create_knowledge_of_axioms_circuit(circuit_version: int = 1) -> MVPCircuit:
    """
    Create a knowledge-of-axioms circuit.
    
    Args:
        circuit_version: Circuit version number (default 1 for MVP)
    
    Returns:
        MVPCircuit instance
    """
    return MVPCircuit(circuit_version=circuit_version)


@dataclass
class TDFOLv1DerivationCircuit:
    """Constraint evaluation for the `TDFOL_v1` MVP semantics (P7.2).

    This is still a *non-cryptographic* constraint checker implemented in
    Python, but it defines a witness structure that is designed to be compiled
    to arithmetic constraints later.

    Witness requirements (v2):
    - witness.axioms: canonicalized axioms
    - witness.theorem: theorem atom (string)
    - witness.intermediate_steps: derivation trace of atoms (strings)

    Public statement requirements:
    - statement.theorem_hash == hash_theorem(witness.theorem)
    - statement.axioms_commitment == tdfol_v1_axioms_commitment_hex_v2(witness.axioms)
    - statement.ruleset_id == 'TDFOL_v1'
    - statement.circuit_version == 2
    """

    circuit_version: int = 2
    circuit_type: str = "tdfol_v1_horn_derivation"

    def num_inputs(self) -> int:
        return 4

    def compile(self) -> Dict[str, Any]:
        return {
            'version': self.circuit_version,
            'type': self.circuit_type,
            'num_inputs': self.num_inputs(),
            'description': 'Prove theorem holds under TDFOL_v1 Horn-fragment semantics using a derivation trace',
        }

    def verify_constraints(self, witness: Witness, statement: Statement) -> bool:
        try:
            if statement.circuit_version != self.circuit_version:
                return False
            if witness.circuit_version != statement.circuit_version:
                return False
            if statement.ruleset_id != "TDFOL_v1":
                return False
            if witness.ruleset_id != statement.ruleset_id:
                return False

            if not witness.theorem:
                return False

            theorem_atom = parse_tdfol_v1_theorem(witness.theorem)
            if statement.theorem_hash != hash_theorem(theorem_atom).hex():
                return False

            canonical_axioms = canonicalize_axioms(witness.axioms)
            if witness.axioms != canonical_axioms:
                return False
            expected_commitment_hex = tdfol_v1_axioms_commitment_hex_v2(canonical_axioms)
            if statement.axioms_commitment != expected_commitment_hex:
                return False
            if witness.axioms_commitment_hex != expected_commitment_hex:
                return False

            # Validate the derivation trace.
            #
            # Rules:
            # - Each trace entry must be an atom.
            # - Facts (axioms without antecedent) are initially known.
            # - For any derived atom X that is not a fact, there must exist an axiom (P -> X)
            #   with P already known.
            if witness.intermediate_steps is None or len(witness.intermediate_steps) == 0:
                return False

            parsed_axioms = [parse_tdfol_v1_axiom(a) for a in canonical_axioms]
            facts = {ax.consequent for ax in parsed_axioms if ax.antecedent is None}
            implications = [ax for ax in parsed_axioms if ax.antecedent is not None]

            known = set(facts)
            seen = set()

            for raw_step in witness.intermediate_steps:
                step = parse_tdfol_v1_theorem(raw_step)

                # Keep trace strictly additive.
                if step in seen:
                    return False
                seen.add(step)

                if step not in known:
                    # Must be justified by some implication whose antecedent is already known.
                    ok = False
                    for ax in implications:
                        assert ax.antecedent is not None
                        if ax.consequent == step and ax.antecedent in known:
                            ok = True
                            break
                    if not ok:
                        return False
                    known.add(step)

            return theorem_atom in known

        except Exception:
            return False

def create_implication_circuit(num_premises: int) -> ZKPCircuit:
    """
    Create a circuit for proving: (P1 AND P2 AND ... AND Pn) IMPLIES Q
    
    This is useful for proving theorems where multiple premises
    lead to a conclusion.
    
    Args:
        num_premises: Number of premise variables
    
    Returns:
        ZKPCircuit: Circuit that verifies the implication
    
    Example:
        >>> # Create circuit for: (P AND Q) IMPLIES R
        >>> circuit = create_implication_circuit(num_premises=2)
        >>> print(circuit)
        ZKPCircuit(inputs=3, gates=3, wires=7)
    """
    circuit = ZKPCircuit()
    
    # Add premise inputs
    premise_wires = []
    for i in range(num_premises):
        wire = circuit.add_input(f"P{i}")
        premise_wires.append(wire)
    
    # Add conclusion input
    q_wire = circuit.add_input("Q")
    
    # AND all premises together
    if num_premises == 1:
        premises_wire = premise_wires[0]
    else:
        premises_wire = circuit.add_and_gate(premise_wires[0], premise_wires[1])
        for i in range(2, num_premises):
            premises_wire = circuit.add_and_gate(premises_wire, premise_wires[i])
    
    # Create implication: premises -> Q
    result_wire = circuit.add_implies_gate(premises_wire, q_wire)
    circuit.set_output(result_wire)
    
    return circuit
