from ipfs_datasets_py.logic.zkp.circuits import TDFOLv1DerivationCircuit
from ipfs_datasets_py.logic.zkp.witness_manager import WitnessManager


def test_tdfol_v1_derivation_circuit_accepts_valid_trace() -> None:
    manager = WitnessManager()
    witness = manager.generate_witness(
        axioms=["P", "P -> Q"],
        theorem="Q",
        circuit_version=2,
        ruleset_id="TDFOL_v1",
    )
    stmt = manager.create_proof_statement(witness, theorem="Q").statement

    circuit = TDFOLv1DerivationCircuit(circuit_version=2)
    assert circuit.verify_constraints(witness, stmt)


def test_tdfol_v1_derivation_circuit_rejects_missing_trace() -> None:
    manager = WitnessManager()
    witness = manager.generate_witness(
        axioms=["P", "P -> Q"],
        theorem="Q",
        intermediate_steps=[],
        circuit_version=2,
        ruleset_id="TDFOL_v1",
    )
    stmt = manager.create_proof_statement(witness, theorem="Q").statement

    circuit = TDFOLv1DerivationCircuit(circuit_version=2)
    assert not circuit.verify_constraints(witness, stmt)


def test_tdfol_v1_derivation_circuit_rejects_wrong_version() -> None:
    manager = WitnessManager()
    witness = manager.generate_witness(
        axioms=["P", "P -> Q"],
        theorem="Q",
        circuit_version=1,
        ruleset_id="TDFOL_v1",
    )
    stmt = manager.create_proof_statement(witness, theorem="Q").statement

    circuit = TDFOLv1DerivationCircuit(circuit_version=2)
    assert not circuit.verify_constraints(witness, stmt)
