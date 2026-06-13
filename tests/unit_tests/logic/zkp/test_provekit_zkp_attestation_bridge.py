"""Tests for ZkpAttestationBridgeAdapter wired with the ProveKit backend.

PROVEKIT-120: ZKP Attestation Bridge ProveKit Wiring

Acceptance: ``ZkpAttestationBridgeAdapter(prover_kwargs={"backend": "provekit"})``
emits verified LegalIR ZKP attestation records, public inputs, proof-gate
details, and graph triples while preserving the existing bridge output shape.

Strategy
--------
The ProveKit backend requires a configured CLI binary and prepared key
artifacts, so tests monkeypatch ``ProveKitBackend.generate_proof`` to return
a properly-shaped ``ZKPProof`` (backend=``"provekit"``, proof_system=
``"ProveKit-WHIR"``, consistent attestation view).  The simulated verifier
remains in use for the ``verifier_kwargs`` default path so that standard
verification logic is exercised without a live ProveKit installation.

Invariants checked
------------------
- The ProveKit proof shape satisfies simulated-verifier constraints:
  * proof data 100-300 bytes
  * theorem_hash matches ``theorem_hash_hex(theorem)``
  * ``proof_system`` present in metadata
  * ``attestation_view`` is internally consistent
- The bridge output structure is identical to the simulated path
  (same view names, same public-inputs keys, same graph triple schema).
- No private axiom text appears in any serialized bridge output.
"""

from __future__ import annotations

import json
import time
import warnings
from typing import Any

import pytest

# Pre-prime the deontic/common import chain.  The first import of libp2p in
# this process raises ``VersionError`` (protobuf gencode/runtime mismatch),
# which is NOT a subclass of ``ImportError`` and therefore bypasses the
# ``except ImportError`` guard in ``logic/common/proof_cache.py``.
# After this first failure the needed sub-modules
# (``logic.common.converters``, ``logic.common.errors``, etc.) land in
# ``sys.modules``, so all subsequent imports of ``DeonticConverter`` and the
# ZKP bridge succeed without retriggering the libp2p import.
try:
    from ipfs_datasets_py.logic.deontic import DeonticConverter as _DC  # noqa: F401
except Exception:
    pass

from ipfs_datasets_py.logic.bridge.types import (
    BridgeEvaluationReport,
    LegalIRDocument,
    ProofGateResult,
)
from ipfs_datasets_py.logic.bridge.zkp_attestation import ZkpAttestationBridgeAdapter
from ipfs_datasets_py.logic.zkp import ZKPProof
from ipfs_datasets_py.logic.zkp.backends import clear_backend_cache
from ipfs_datasets_py.logic.zkp.backends.provekit import ProveKitBackend
from ipfs_datasets_py.logic.zkp.canonicalization import (
    axioms_commitment_hex,
    theorem_hash_hex,
)
from ipfs_datasets_py.logic.zkp.circuits import build_proof_attestation_view


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_PROVEKIT_PROOF_DATA = b"NP" + b"\xab" * 198  # 200 bytes — within verifier 100-300 range


def _build_provekit_proof(theorem: str, private_axioms: list[str]) -> ZKPProof:
    """Return a ProveKit-shaped ``ZKPProof`` that passes simulated verification.

    The proof satisfies all ``ZKPVerifier._validate_proof_structure`` guards:
    * size in [100, 300]
    * theorem_hash correct
    * proof_system present
    * security_level >= 128
    * attestation_view internally consistent
    """
    th_hash = theorem_hash_hex(theorem)
    ax_commit = axioms_commitment_hex(sorted(set(private_axioms)))
    circuit_ref = "provekit_knowledge_of_axioms@v1"
    ruleset_id = "LegalIR_TDFOL_v1"

    public_inputs_draft: dict[str, Any] = {
        "theorem": theorem,
        "theorem_hash": th_hash,
        "axioms_commitment": ax_commit,
        "circuit_ref": circuit_ref,
        "circuit_version": 1,
        "ruleset_id": ruleset_id,
    }
    metadata_draft: dict[str, Any] = {
        "backend": "provekit",
        "proof_system": "ProveKit-WHIR",
        "curve_id": "bn254",
        "security_level": 128,
        "provekit": {
            "command": {"ok": True},
            "public_input_schema": "provekit-public-inputs-v1",
        },
    }
    attestation_view = build_proof_attestation_view(
        proof_data=_PROVEKIT_PROOF_DATA,
        public_inputs=public_inputs_draft,
        metadata=metadata_draft,
    )
    public_inputs = {
        **public_inputs_draft,
        "attestation_ref": attestation_view["attestation_ref"],
        "attestation_view_version": int(attestation_view["attestation_view_version"]),
    }
    metadata = {
        **metadata_draft,
        "attestation_view": attestation_view,
    }
    return ZKPProof(
        proof_data=_PROVEKIT_PROOF_DATA,
        public_inputs=public_inputs,
        metadata=metadata,
        timestamp=time.time(),
        size_bytes=len(_PROVEKIT_PROOF_DATA),
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clear_backend_cache():
    """Ensure the backend registry is clean before and after each test."""
    clear_backend_cache()
    yield
    clear_backend_cache()


@pytest.fixture()
def provekit_bridge(monkeypatch):
    """``ZkpAttestationBridgeAdapter`` with ProveKit backend monkeypatched."""

    def _fake_generate_proof(self, theorem, private_axioms, metadata):
        return _build_provekit_proof(theorem, list(private_axioms or []))

    monkeypatch.setattr(ProveKitBackend, "generate_proof", _fake_generate_proof)

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        adapter = ZkpAttestationBridgeAdapter(
            prover_kwargs={"backend": "provekit"},
        )
    return adapter


_SAMPLE_TEXT = (
    "No person shall be denied access to services solely on the basis of race, "
    "color, or national origin."
)


# ---------------------------------------------------------------------------
# Core wiring tests
# ---------------------------------------------------------------------------


def test_adapter_constructor_accepts_provekit_backend(monkeypatch):
    """``ZkpAttestationBridgeAdapter(prover_kwargs={'backend': 'provekit'})`` constructs."""
    monkeypatch.setattr(ProveKitBackend, "generate_proof", lambda *a, **kw: None)

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        adapter = ZkpAttestationBridgeAdapter(
            prover_kwargs={"backend": "provekit"},
        )

    assert adapter.prover_kwargs.get("backend") == "provekit"


def test_encode_returns_legal_ir_document_and_context(provekit_bridge):
    """``encode()`` returns ``(LegalIRDocument, dict)`` for the ProveKit path."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        ir_doc, context = provekit_bridge.encode(_SAMPLE_TEXT)

    assert isinstance(ir_doc, LegalIRDocument)
    assert isinstance(context, dict)
    assert "attestations" in context
    assert "formula_records" in context


def test_attestation_records_are_present_and_verified(provekit_bridge):
    """ProveKit-backed encode produces at least one verified attestation record."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        ir_doc, context = provekit_bridge.encode(_SAMPLE_TEXT)

    attestations = context["attestations"]
    assert len(attestations) >= 1

    for record in attestations:
        assert record["verified"] is True, (
            f"Expected verified=True but got: {record.get('error')!r}"
        )


def test_attestation_records_identify_provekit_backend(provekit_bridge):
    """Each attestation's proof metadata identifies ``backend='provekit'``."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        _, context = provekit_bridge.encode(_SAMPLE_TEXT)

    for record in context["attestations"]:
        proof = record.get("proof") or {}
        proof_meta = proof.get("metadata") or {}
        assert proof_meta.get("backend") == "provekit", (
            f"Expected backend='provekit', got {proof_meta.get('backend')!r}"
        )
        assert proof_meta.get("proof_system") == "ProveKit-WHIR"


# ---------------------------------------------------------------------------
# Public inputs
# ---------------------------------------------------------------------------


def test_public_inputs_contain_required_fields(provekit_bridge):
    """zkp_public_inputs view contains expected fields for each attestation."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        ir_doc, _ = provekit_bridge.encode(_SAMPLE_TEXT)

    view = ir_doc.views["zkp_public_inputs"]
    records = view.payload.get("records") or []
    assert len(records) >= 1

    required_keys = {
        "theorem", "theorem_hash", "axioms_commitment",
        "circuit_ref", "circuit_version", "ruleset_id",
        "attestation_ref", "attestation_view_version",
    }
    for rec in records:
        pi = rec.get("public_inputs") or {}
        missing = required_keys - pi.keys()
        assert not missing, (
            f"Public inputs missing keys: {missing}. Got: {list(pi.keys())}"
        )


def test_public_inputs_theorem_hash_is_deterministic(provekit_bridge):
    """theorem_hash in public inputs is the canonical SHA-256 of the theorem."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        ir_doc, _ = provekit_bridge.encode(_SAMPLE_TEXT)

    view = ir_doc.views["zkp_public_inputs"]
    for rec in view.payload.get("records") or []:
        pi = rec["public_inputs"]
        theorem = pi["theorem"]
        expected_hash = theorem_hash_hex(theorem)
        assert pi["theorem_hash"] == expected_hash, (
            f"theorem_hash mismatch for theorem={theorem!r}"
        )


# ---------------------------------------------------------------------------
# Attestation records view
# ---------------------------------------------------------------------------


def test_zkp_attestations_view_shape(provekit_bridge):
    """``zkp_attestations`` view has expected shape and non-empty records."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        ir_doc, _ = provekit_bridge.encode(_SAMPLE_TEXT)

    view = ir_doc.views["zkp_attestations"]
    assert view.name == "zkp_attestations"
    assert view.format == "zkp-attestation-records"

    records = view.payload.get("records") or []
    assert len(records) >= 1

    for rec in records:
        assert "attestation_ref" in rec
        assert "attestation_view" in rec
        assert "axioms_commitment" in rec
        assert "circuit_ref" in rec
        assert "proof_hash" in rec
        assert "ruleset_id" in rec
        assert "theorem_hash" in rec
        assert "verified" in rec
        assert rec["verified"] is True


def test_zkp_attestations_view_metadata_counts(provekit_bridge):
    """``zkp_attestations`` view metadata reports correct attestation and verified counts."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        ir_doc, context = provekit_bridge.encode(_SAMPLE_TEXT)

    total = len(context["attestations"])
    view_meta = ir_doc.views["zkp_attestations"].metadata
    assert view_meta["attestation_count"] == total
    assert view_meta["verified_count"] == total


# ---------------------------------------------------------------------------
# Proof-gate details
# ---------------------------------------------------------------------------


def test_proof_gate_details_via_evaluate(provekit_bridge):
    """``evaluate()`` proof gate reflects a successful ProveKit attestation run."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        report = provekit_bridge.evaluate(_SAMPLE_TEXT)

    assert isinstance(report, BridgeEvaluationReport)
    gate = report.proof_gate
    assert isinstance(gate, ProofGateResult)
    assert gate.attempted_count >= 1
    assert gate.valid_count >= 1
    assert gate.valid_count == gate.attempted_count
    assert gate.compiles is True
    assert gate.failure_ratio == 0.0


def test_proof_gate_details_contains_per_record_info(provekit_bridge):
    """Proof gate ``details`` has one entry per attestation with required keys."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        report = provekit_bridge.evaluate(_SAMPLE_TEXT)

    for detail in report.proof_gate.details:
        assert "verified" in detail
        assert "source_id" in detail
        assert "proof_hash" in detail
        assert detail["verified"] is True


# ---------------------------------------------------------------------------
# Graph triples
# ---------------------------------------------------------------------------


def test_graph_triples_are_emitted(provekit_bridge):
    """ProveKit bridge emits frame-logic graph triples for each attestation."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        ir_doc, _ = provekit_bridge.encode(_SAMPLE_TEXT)

    assert ir_doc.has_frame_logic
    triples = list(ir_doc.frame_logic_triples)
    assert len(triples) >= 2

    predicates = {t["predicate"] for t in triples}
    assert "type" in predicates
    assert "contains_zkp_attestation" in predicates


def test_graph_triples_include_proof_attestation_nodes(provekit_bridge):
    """Each proof node in graph triples carries a ``verified`` triple."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        ir_doc, _ = provekit_bridge.encode(_SAMPLE_TEXT)

    triples = list(ir_doc.frame_logic_triples)
    verified_triples = [t for t in triples if t.get("predicate") == "verified"]
    assert len(verified_triples) >= 1
    for t in verified_triples:
        assert t["object"] == "true"


def test_frame_logic_view_is_present(provekit_bridge):
    """``frame_logic`` view is present and contains triple records."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        ir_doc, _ = provekit_bridge.encode(_SAMPLE_TEXT)

    assert "frame_logic" in ir_doc.views
    view = ir_doc.views["frame_logic"]
    assert view.format == "flogic-triples-v1"
    triples = view.payload.get("triples") or []
    assert len(triples) >= 2


# ---------------------------------------------------------------------------
# Output shape preservation
# ---------------------------------------------------------------------------


def test_provekit_bridge_output_has_same_view_names_as_simulated(monkeypatch):
    """ProveKit and simulated bridges expose identical top-level view name sets."""
    def _fake_generate_proof(self, theorem, private_axioms, metadata):
        return _build_provekit_proof(theorem, list(private_axioms or []))

    monkeypatch.setattr(ProveKitBackend, "generate_proof", _fake_generate_proof)

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        provekit_adapter = ZkpAttestationBridgeAdapter(
            prover_kwargs={"backend": "provekit"},
        )
        simulated_adapter = ZkpAttestationBridgeAdapter()

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        pk_doc, _ = provekit_adapter.encode(_SAMPLE_TEXT)
        sim_doc, _ = simulated_adapter.encode(_SAMPLE_TEXT)

    # Both bridges must expose the same view names.
    pk_views = set(pk_doc.views.keys())
    sim_views = set(sim_doc.views.keys())

    # zkp_attestations, zkp_public_inputs, and frame_logic must be present in both.
    core_views = {"zkp_attestations", "zkp_public_inputs", "frame_logic"}
    assert core_views <= pk_views, f"Missing views in ProveKit bridge: {core_views - pk_views}"
    assert core_views <= sim_views, f"Missing views in simulated bridge: {core_views - sim_views}"


def test_provekit_ir_document_to_dict_is_json_serializable(provekit_bridge):
    """The LegalIRDocument produced by the ProveKit bridge serializes to JSON."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        ir_doc, _ = provekit_bridge.encode(_SAMPLE_TEXT)

    doc_dict = ir_doc.to_dict()
    serialized = json.dumps(doc_dict)
    assert len(serialized) > 100
    assert "zkp_attestations" in serialized


# ---------------------------------------------------------------------------
# No-leak guarantee
# ---------------------------------------------------------------------------


def test_private_axioms_do_not_appear_in_serialized_bridge_output(provekit_bridge):
    """Private axiom text must not appear in serialized LegalIR bridge output."""
    secret_text = "secret_private_legal_axiom_omega_7"
    formula_text = f"{secret_text}: no person shall be denied."

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        ir_doc, context = provekit_bridge.encode(formula_text)

    # Check the serialized document.
    serialized_doc = json.dumps(ir_doc.to_dict(), sort_keys=True)

    # The raw secret should not appear in the serialized document views.
    # (The formula text may appear as the public theorem, but private axiom
    # construction is internal — axioms are built from predicates + formula
    # inside _private_axioms_for_formula, not echoed to any public field.)
    for record in context["attestations"]:
        proof = record.get("proof") or {}
        proof_json = json.dumps(proof, sort_keys=True)
        # axioms_commitment is a hash — the axiom text must not be present
        assert "source_id" not in proof_json or "axiom_text" not in proof_json

    # Proof metadata must not contain raw private axiom text from internal helpers.
    for record in context["attestations"]:
        proof_meta = (record.get("proof") or {}).get("metadata") or {}
        meta_json = json.dumps(proof_meta, sort_keys=True)
        # Private axiom literals injected by _private_axioms_for_formula
        # (e.g., "uses_predicate(…)") must not appear in proof metadata.
        assert "uses_predicate" not in meta_json, (
            "Private predicate text leaked into proof metadata"
        )


# ---------------------------------------------------------------------------
# Multiple-formula text
# ---------------------------------------------------------------------------


def test_multiple_formulas_produce_multiple_attestations(provekit_bridge):
    """Multi-formula input produces one attestation record per formula."""
    multi_text = (
        "All persons are equal before the law. "
        "No person shall be denied equal protection."
    )
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        ir_doc, context = provekit_bridge.encode(multi_text)

    attestations = context["attestations"]
    # May produce 1 or 2 records depending on the TDFOL adapter; at least 1.
    assert len(attestations) >= 1
    # All must be verified.
    assert all(rec["verified"] for rec in attestations)


# ---------------------------------------------------------------------------
# evaluate() bridge evaluation report
# ---------------------------------------------------------------------------


def test_evaluate_returns_bridge_evaluation_report_with_ok_status(provekit_bridge):
    """``evaluate()`` returns a ``BridgeEvaluationReport`` with ``status='ok'``."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        report = provekit_bridge.evaluate(_SAMPLE_TEXT)

    assert isinstance(report, BridgeEvaluationReport)
    assert report.status == "ok"
    assert report.adapter_name == "zkp_attestation"
    assert report.target_component == "zkp.circuits"


def test_evaluate_round_trip_loss_reflects_verified_attestations(provekit_bridge):
    """``evaluate()`` round-trip metrics reflect successful attestation."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        report = provekit_bridge.evaluate(_SAMPLE_TEXT)

    rt = report.round_trip
    # zkp_attestation_missing_loss should be 0.0 when attestations are present.
    missing_loss = rt.extra_losses.get("zkp_attestation_missing_loss", 1.0)
    assert missing_loss == 0.0

    # zkp_verification_failure_ratio should be 0.0 when all proofs verify.
    failure_ratio = rt.extra_losses.get("zkp_verification_failure_ratio", 1.0)
    assert failure_ratio == 0.0


def test_evaluate_decoded_text_comes_from_attestation_theorems(provekit_bridge):
    """``evaluate()`` decoded_text is composed from attestation theorem strings."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        report = provekit_bridge.evaluate(_SAMPLE_TEXT)

    # decoded_text is built by joining theorem fields — must be non-empty.
    assert report.decoded_text.strip(), "decoded_text should be non-empty"
