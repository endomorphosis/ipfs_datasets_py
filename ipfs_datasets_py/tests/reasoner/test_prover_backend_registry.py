"""Tests for prover backend registry and certificate contract.

Covers issue #1172 (Prover Certificate Contract).
"""
from __future__ import annotations

import pytest

# Path is set up by the layered conftest.py files (root, tests/, and this directory)
from reasoner.hybrid_v2_blueprint import parse_cnl_to_ir, check_compliance, clear_v2_proof_store
from reasoner.prover_backends import (
    create_default_prover_registry, normalize_prover_result,
    MockSMTBackend, MockFOLBackend, SMTStyleProverAdapter, FirstOrderProverAdapter,
    ProverResult, PROVER_ENVELOPE_SCHEMA_VERSION,
)
from reasoner.models import (
    ProofObject, ProofStep, ProofCertificate, IRReference, SourceProvenance,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def clear_proof_store():
    clear_v2_proof_store()
    yield
    clear_v2_proof_store()


@pytest.fixture
def registry():
    return create_default_prover_registry()


@pytest.fixture
def compliance_result():
    ir = parse_cnl_to_ir("Contractor shall submit the report")
    return check_compliance({"ir": ir, "facts": {}, "events": []}, {})


# ---------------------------------------------------------------------------
# TestProverCertificateContract
# ---------------------------------------------------------------------------

class TestProverCertificateContract:
    def test_smt_certificate_has_required_keys(self, registry):
        # GIVEN the smt_style backend
        backend = registry.get("smt_style")
        result = backend.prove("O(frm:abc)", ["premise"])
        cert = result.certificate
        # THEN certificate has required keys
        for key in ("format", "solver", "backend", "theorem_hash_hint"):
            assert key in cert, f"Missing SMT cert key: {key}"

    def test_fol_certificate_has_required_keys(self, registry):
        # GIVEN the first_order backend
        backend = registry.get("first_order")
        result = backend.prove("P(x)", ["A(x)"])
        cert = result.certificate
        # THEN certificate has required keys
        for key in ("format", "prover", "backend", "assumption_count"):
            assert key in cert, f"Missing FOL cert key: {key}"

    def test_mock_smt_certificate_keys(self, registry):
        # GIVEN the mock_smt backend
        backend = registry.get("mock_smt")
        result = backend.prove("O(frm:abc)", [])
        cert = result.certificate
        # THEN certificate has mock_smt-specific fields
        assert "format" in cert
        assert "backend" in cert
        assert cert["backend"] == "mock_smt"

    def test_mock_fol_certificate_keys(self, registry):
        # GIVEN the mock_fol backend
        backend = registry.get("mock_fol")
        result = backend.prove("O(frm:abc)", [])
        cert = result.certificate
        # THEN certificate has mock_fol-specific fields
        assert "format" in cert
        assert "backend" in cert
        assert cert["backend"] == "mock_fol"

    def test_normalize_prover_result_schema_version(self, registry):
        # GIVEN any prover backend result
        backend = registry.get("mock_smt")
        result = backend.prove("O(frm:abc)", [])
        # WHEN normalized
        envelope = normalize_prover_result(result)
        # THEN the schema_version matches the constant
        assert envelope["schema_version"] == PROVER_ENVELOPE_SCHEMA_VERSION

    def test_certificate_id_is_deterministic(self, registry):
        # GIVEN the same theorem and backend
        backend = registry.get("mock_smt")
        r1 = backend.prove("O(frm:abc)", ["p1"])
        r2 = backend.prove("O(frm:abc)", ["p1"])
        # THEN theorem_hash_hint is the same
        assert r1.certificate["theorem_hash_hint"] == r2.certificate["theorem_hash_hint"]

    def test_normalized_hash_present(self, registry):
        # GIVEN any backend result
        backend = registry.get("mock_smt")
        result = backend.prove("O(frm:abc)", [])
        envelope = normalize_prover_result(result)
        # THEN the envelope has backend field
        assert "backend" in envelope
        assert envelope["backend"] == "mock_smt"


# ---------------------------------------------------------------------------
# TestProofStepIRRefs
# ---------------------------------------------------------------------------

class TestProofStepIRRefs:
    def test_proof_steps_require_ir_refs(self, compliance_result):
        # GIVEN a compliance check result
        proof_id = compliance_result["proof_id"]
        from reasoner.hybrid_v2_blueprint import explain_proof
        expl = explain_proof(proof_id, format="json")
        steps = expl["steps"]
        # THEN each step has ir_refs (non-empty)
        assert len(steps) > 0
        for step in steps:
            assert "ir_refs" in step, f"Step missing ir_refs: {step}"

    def test_proof_steps_require_source_refs(self, compliance_result):
        # GIVEN a compliance check result
        proof_id = compliance_result["proof_id"]
        from reasoner.hybrid_v2_blueprint import explain_proof
        expl = explain_proof(proof_id, format="json")
        steps = expl["steps"]
        # THEN at least one step has source_refs
        has_source_refs = any("source_refs" in step for step in steps)
        assert has_source_refs, "No steps have source_refs"

    def test_proof_step_ir_refs_nonempty_after_compliance(self, compliance_result):
        # GIVEN a compliance check result
        proof_id = compliance_result["proof_id"]
        from reasoner.hybrid_v2_blueprint import explain_proof
        expl = explain_proof(proof_id, format="json")
        steps = expl["steps"]
        # THEN the first step's ir_refs are non-empty
        assert len(steps[0]["ir_refs"]) > 0


# ---------------------------------------------------------------------------
# TestProofHashReplay
# ---------------------------------------------------------------------------

class TestProofHashReplay:
    def test_proof_hash_is_deterministic(self):
        # GIVEN the same IR and query conditions
        ir = parse_cnl_to_ir("Contractor shall submit the report")
        r1 = check_compliance({"ir": ir, "facts": {}, "events": []}, {})
        r2 = check_compliance({"ir": ir, "facts": {}, "events": []}, {})
        # THEN same proof_id is produced
        assert r1["proof_id"] == r2["proof_id"]

    def test_replay_verification(self):
        # GIVEN a compliance result
        ir = parse_cnl_to_ir("Contractor shall submit the report")
        result = check_compliance({"ir": ir, "facts": {}, "events": []}, {})
        proof_id = result["proof_id"]
        # WHEN explained
        from reasoner.hybrid_v2_blueprint import explain_proof
        expl = explain_proof(proof_id, format="nl")
        # THEN the proof_id in the explanation matches
        assert expl["proof_id"] == proof_id

    def test_multiple_backends_registered(self, registry):
        # GIVEN the default registry
        backends = registry.list_backends()
        # THEN all four backends are present
        for name in ("smt_style", "first_order", "mock_smt", "mock_fol"):
            assert name in backends, f"Backend '{name}' missing from registry"


# ---------------------------------------------------------------------------
# TestProverEnvelopeValidation
# ---------------------------------------------------------------------------

class TestProverEnvelopeValidation:
    def test_envelope_schema_version(self, registry):
        # GIVEN mock_smt backend
        backend = registry.get("mock_smt")
        result = backend.prove("O(frm:test)", [])
        envelope = normalize_prover_result(result)
        # THEN schema_version is a string
        assert isinstance(envelope["schema_version"], str)
        assert len(envelope["schema_version"]) > 0

    def test_envelope_backend_field(self, registry):
        # GIVEN mock_fol backend
        backend = registry.get("mock_fol")
        result = backend.prove("F(frm:test)", [])
        envelope = normalize_prover_result(result)
        # THEN backend field matches
        assert envelope["backend"] == "mock_fol"

    def test_envelope_certificate_fields(self, registry):
        # GIVEN smt_style backend
        backend = registry.get("smt_style")
        result = backend.prove("O(frm:xyz)", ["h1", "h2"])
        envelope = normalize_prover_result(result)
        # THEN certificate is present
        assert "certificate" in envelope
        cert = envelope["certificate"]
        assert isinstance(cert, dict)
        assert len(cert) > 0
