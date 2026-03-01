from __future__ import annotations

from ipfs_datasets_py.processors.legal_data.reasoner.prover_backends import (
    FirstOrderProverAdapter,
    MockFOLBackend,
    MockSMTBackend,
    ProverBackendRegistry,
    SMTStyleProverAdapter,
    create_default_prover_registry,
)


def test_prover_registry_register_get_list_and_unregister() -> None:
    registry = ProverBackendRegistry()
    smt = MockSMTBackend()
    fol = MockFOLBackend()

    registry.register(smt)
    registry.register(fol)

    assert registry.list_backends() == ["mock_fol", "mock_smt"]
    assert registry.get("mock_smt") is smt

    registry.unregister("mock_smt")
    assert registry.list_backends() == ["mock_fol"]


def test_default_prover_registry_contains_reference_backends() -> None:
    registry = create_default_prover_registry()
    backends = registry.list_backends()

    assert "mock_smt" in backends
    assert "mock_fol" in backends
    assert "smt_style" in backends
    assert "first_order" in backends


def test_reference_backends_produce_certificate_payloads() -> None:
    registry = create_default_prover_registry()
    theorem = "forall x. Person(x) -> Mortal(x)"
    assumptions = ["Person(socrates)"]

    smt_result = registry.get("mock_smt").prove(theorem, assumptions)
    fol_result = registry.get("mock_fol").prove(theorem, assumptions)

    assert smt_result.backend == "mock_smt"
    assert fol_result.backend == "mock_fol"
    assert smt_result.certificate["format"] == "smt-certificate-v1"
    assert fol_result.certificate["format"] == "first-order-certificate-v1"


def test_concrete_adapters_emit_backend_specific_certificate_fields() -> None:
    registry = ProverBackendRegistry()
    registry.register(SMTStyleProverAdapter(solver_name="z3"))
    registry.register(FirstOrderProverAdapter(prover_name="eprover"))

    theorem = "forall x. P(x) -> Q(x)"
    assumptions = ["P(a)"]

    smt = registry.get("smt_style").prove(theorem, assumptions)
    fol = registry.get("first_order").prove(theorem, assumptions)

    assert smt.certificate["solver"] == "z3"
    assert fol.certificate["prover"] == "eprover"
