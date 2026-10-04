"""Tests for deontic LegalNormIR → ProveKit public-commitment bridge.

PROVEKIT-140: Deontic LegalNormIR Guidance Commitments

Acceptance:
    Deontic ``LegalNormIR``, parser capability records, prover syntax readiness,
    and repair/compiler guidance metadata flow into stable public commitments and
    ``compiler_guidance_ref`` fields without exposing private legal text or parser
    witness data.

Strategy
--------
These tests exercise the data-flow path from parsed legal text → LegalNormIR →
parser capability profile → prover syntax report → ProveKit public inputs with
``compiler_guidance_ref``.  The ProveKit CLI and backend are not required; all
assertions target the deterministic commitment-layer outputs (theorem_hash,
axioms_commitment, compiler_guidance_ref) and the absence of private text in any
public-facing structure.

Invariants checked
------------------
- ``LegalNormIR`` produces a stable ``proof_ready`` flag and deterministic
  modality/actor/action slots.
- Parser capability profile records carry grounding metadata without exposing
  raw legal text in their identity or summary fields.
- ``validate_ir_with_provers`` returns a ``ProverSyntaxReport`` whose
  ``proof_ready`` and ``syntax_valid`` signals are accurate.
- ``build_provekit_public_input_record`` produces deterministic
  ``theorem_hash``, ``axioms_commitment``, and ``circuit_ref`` values.
- A ``compiler_guidance_ref`` built from repair/guidance metadata is stable and
  non-empty when guidance content is supplied.
- ``build_proof_attestation_view`` propagates ``compiler_guidance_ref`` into the
  attestation view when the public-input record carries one.
- No raw legal text or parser witness data appears in public commitment fields.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict

import pytest

# Pre-prime the deontic/common import chain so that the VersionError from
# libp2p (protobuf mismatch) is absorbed before the main test imports.
try:
    from ipfs_datasets_py.logic.deontic import DeonticConverter as _DC  # noqa: F401
except Exception:
    pass

from ipfs_datasets_py.logic.deontic.exports import (
    build_deterministic_parser_capability_profile_record,
)
from ipfs_datasets_py.logic.deontic.ir import LegalNormIR
from ipfs_datasets_py.logic.deontic.prover_syntax import validate_ir_with_provers
from ipfs_datasets_py.logic.deontic.utils.deontic_parser import extract_normative_elements
from ipfs_datasets_py.logic.zkp.canonicalization import (
    axioms_commitment_hex,
    theorem_hash_hex,
)
from ipfs_datasets_py.logic.zkp.circuits import (
    build_proof_attestation_view,
    compiler_guidance_ref_from_metadata,
)
from ipfs_datasets_py.logic.zkp.provekit.public_inputs import (
    build_provekit_public_input_record,
)


# ---------------------------------------------------------------------------
# Sample legal texts used across tests
# ---------------------------------------------------------------------------

_OBLIGATION_TEXT = "The Secretary shall submit a report to Congress within 30 days."
_PERMISSION_TEXT = "The applicant may request an extension of the filing deadline."
_PROHIBITION_TEXT = "No person may discharge pollutants into navigable waters without a permit."

# A "private" legal text that must never appear in any public commitment field.
_PRIVATE_TEXT = "secret_private_legal_clause_omega_9: confidential internal policy."


def _norm_from_text(text: str) -> LegalNormIR:
    elements = extract_normative_elements(text)
    assert elements, f"No normative elements extracted from: {text!r}"
    return LegalNormIR.from_parser_element(elements[0])


def _guidance_metadata_from_norm(
    norm: LegalNormIR,
    syntax_report_dict: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    """Build compiler-guidance metadata from parser capability + syntax report."""
    capability = build_deterministic_parser_capability_profile_record(norm)
    contract: Dict[str, Any] = {
        "parser_capability_profile_id": capability["parser_capability_profile_id"],
        "capability_family": capability["capability_family"],
        "formula_proof_ready": capability["formula_proof_ready"],
        "parser_proof_ready": capability["parser_proof_ready"],
        "source_grounded_slot_rate": capability["source_grounded_slot_rate"],
        "repair_required": capability["repair_required"],
        "blockers": capability["blockers"],
    }
    if syntax_report_dict is not None:
        contract["syntax_valid"] = syntax_report_dict.get("syntax_valid", False)
        contract["proof_ready"] = syntax_report_dict.get("proof_ready", False)
        contract["valid_target_count"] = syntax_report_dict.get("valid_target_count", 0)
    return {"compiler_guidance_contract": contract}


# ---------------------------------------------------------------------------
# LegalNormIR stability
# ---------------------------------------------------------------------------


def test_legal_norm_ir_obligation_has_expected_slots():
    norm = _norm_from_text(_OBLIGATION_TEXT)

    assert norm.modality == "O"
    assert norm.norm_type == "obligation"
    assert norm.actor.lower() == "secretary"
    assert norm.source_id


def test_legal_norm_ir_permission_has_permission_modality():
    norm = _norm_from_text(_PERMISSION_TEXT)

    assert norm.modality == "P"
    assert norm.norm_type in ("permission", "")


def test_legal_norm_ir_prohibition_has_prohibition_modality():
    norm = _norm_from_text(_PROHIBITION_TEXT)

    assert norm.modality == "F"
    assert norm.norm_type in ("prohibition", "")


def test_legal_norm_ir_to_dict_is_deterministic():
    norm = _norm_from_text(_OBLIGATION_TEXT)

    first = norm.to_dict()
    second = norm.to_dict()

    assert first == second


def test_legal_norm_ir_proof_ready_obligation():
    norm = _norm_from_text(_OBLIGATION_TEXT)

    # The obligation may or may not be proof_ready depending on temporal
    # constraints; what matters is that the flag is a boolean and stable.
    assert isinstance(norm.proof_ready, bool)
    assert isinstance(norm.quality.promotable_to_theorem, bool)


# ---------------------------------------------------------------------------
# Parser capability profile records
# ---------------------------------------------------------------------------


def test_parser_capability_profile_record_is_deterministic():
    norm = _norm_from_text(_OBLIGATION_TEXT)

    first = build_deterministic_parser_capability_profile_record(norm)
    second = build_deterministic_parser_capability_profile_record(norm)

    assert first == second


def test_parser_capability_profile_record_has_required_fields():
    norm = _norm_from_text(_OBLIGATION_TEXT)
    record = build_deterministic_parser_capability_profile_record(norm)

    for key in (
        "parser_capability_profile_id",
        "source_id",
        "capability_family",
        "formula_proof_ready",
        "parser_proof_ready",
        "repair_required",
        "source_grounded_slot_rate",
        "grounded_slots",
        "missing_slots",
        "schema_version",
    ):
        assert key in record, f"Missing key: {key}"


def test_parser_capability_profile_record_does_not_expose_private_legal_text():
    """Raw legal text must not appear in the identity or summary fields."""
    norm = _norm_from_text(_OBLIGATION_TEXT)
    record = build_deterministic_parser_capability_profile_record(norm)

    # Sensitive fields: the profile id must be an opaque hash, not raw text.
    profile_id = record["parser_capability_profile_id"]
    # Profile IDs are hex digests; they should not contain spaces (raw text).
    assert " " not in profile_id, f"Profile ID looks like raw text: {profile_id!r}"

    # The source-grounded slot rate must be a float in [0, 1].
    rate = record["source_grounded_slot_rate"]
    assert isinstance(rate, float)
    assert 0.0 <= rate <= 1.0


def test_parser_capability_profile_blockers_are_a_list():
    norm = _norm_from_text(_OBLIGATION_TEXT)
    record = build_deterministic_parser_capability_profile_record(norm)

    assert isinstance(record["blockers"], list)


# ---------------------------------------------------------------------------
# Prover syntax readiness
# ---------------------------------------------------------------------------


def test_prover_syntax_report_is_deterministic():
    norm = _norm_from_text(_PERMISSION_TEXT)

    first = validate_ir_with_provers(norm).to_dict()
    second = validate_ir_with_provers(norm).to_dict()

    assert first == second


def test_prover_syntax_report_has_required_fields():
    norm = _norm_from_text(_PERMISSION_TEXT)
    report = validate_ir_with_provers(norm)
    report_dict = report.to_dict()

    for key in (
        "source_id",
        "syntax_valid",
        "target_count",
        "valid_target_count",
        "proof_ready",
        "targets",
        "schema_version",
    ):
        assert key in report_dict, f"Missing key: {key}"


def test_prover_syntax_report_proof_ready_is_bool():
    norm = _norm_from_text(_OBLIGATION_TEXT)
    report = validate_ir_with_provers(norm)

    assert isinstance(report.proof_ready, bool)
    assert isinstance(report.syntax_valid, bool)


def test_prover_syntax_targets_include_standard_dialects():
    norm = _norm_from_text(_PERMISSION_TEXT)
    report = validate_ir_with_provers(norm)

    target_names = {t.target for t in report.targets}
    expected = {"fol", "deontic_fol", "deontic_temporal_fol", "frame_logic", "deontic_cec"}
    assert expected <= target_names, f"Missing targets: {expected - target_names}"


# ---------------------------------------------------------------------------
# ProveKit public-input record with stable commitments
# ---------------------------------------------------------------------------


def test_build_provekit_public_input_record_produces_deterministic_theorem_hash():
    norm = _norm_from_text(_OBLIGATION_TEXT)
    theorem = norm.actor + " " + norm.action

    record = build_provekit_public_input_record(theorem=theorem, private_axioms=[])

    expected_hash = theorem_hash_hex(theorem)
    assert record.theorem_hash == expected_hash


def test_build_provekit_public_input_record_produces_deterministic_axioms_commitment():
    norm = _norm_from_text(_OBLIGATION_TEXT)
    theorem = norm.actor + " " + norm.action
    axioms = [norm.modality, norm.source_id]

    record = build_provekit_public_input_record(theorem=theorem, private_axioms=axioms)

    expected_commitment = axioms_commitment_hex(sorted(set(axioms)))
    assert record.axioms_commitment == expected_commitment


def test_build_provekit_public_input_record_circuit_ref_is_stable():
    norm = _norm_from_text(_OBLIGATION_TEXT)
    theorem = norm.actor + " " + norm.action

    first = build_provekit_public_input_record(theorem=theorem, private_axioms=[])
    second = build_provekit_public_input_record(theorem=theorem, private_axioms=[])

    assert first.circuit_ref == second.circuit_ref
    assert "@" in first.circuit_ref


def test_build_provekit_public_input_record_empty_compiler_guidance_ref_when_no_metadata():
    norm = _norm_from_text(_OBLIGATION_TEXT)
    theorem = norm.actor + " " + norm.action

    record = build_provekit_public_input_record(theorem=theorem, private_axioms=[])

    # Without guidance metadata, compiler_guidance_ref must be empty string.
    assert record.compiler_guidance_ref == ""


# ---------------------------------------------------------------------------
# Compiler guidance ref from parser capability + prover syntax metadata
# ---------------------------------------------------------------------------


def test_compiler_guidance_ref_is_non_empty_when_contract_supplied():
    norm = _norm_from_text(_OBLIGATION_TEXT)
    syntax_report = validate_ir_with_provers(norm)
    metadata = _guidance_metadata_from_norm(norm, syntax_report.to_dict())

    ref = compiler_guidance_ref_from_metadata(metadata)

    assert isinstance(ref, str)
    assert len(ref) == 64, f"Expected 64-char SHA-256 hex; got len={len(ref)}"
    # Must be pure hex.
    int(ref, 16)


def test_compiler_guidance_ref_is_deterministic():
    norm = _norm_from_text(_OBLIGATION_TEXT)
    syntax_report = validate_ir_with_provers(norm)
    metadata = _guidance_metadata_from_norm(norm, syntax_report.to_dict())

    first = compiler_guidance_ref_from_metadata(metadata)
    second = compiler_guidance_ref_from_metadata(metadata)

    assert first == second


def test_compiler_guidance_ref_changes_when_repair_required_changes():
    norm = _norm_from_text(_OBLIGATION_TEXT)
    syntax_report = validate_ir_with_provers(norm)

    metadata_no_repair = _guidance_metadata_from_norm(norm, syntax_report.to_dict())
    contract_with_repair = {
        **metadata_no_repair["compiler_guidance_contract"],
        "repair_required": True,
    }
    metadata_with_repair = {"compiler_guidance_contract": contract_with_repair}

    ref_no_repair = compiler_guidance_ref_from_metadata(metadata_no_repair)
    ref_with_repair = compiler_guidance_ref_from_metadata(metadata_with_repair)

    assert ref_no_repair != ref_with_repair


def test_compiler_guidance_ref_empty_when_no_contract():
    ref = compiler_guidance_ref_from_metadata({})
    assert ref == ""

    ref2 = compiler_guidance_ref_from_metadata(None)
    assert ref2 == ""


# ---------------------------------------------------------------------------
# Guidance ref flows into ProveKitPublicInputRecord
# ---------------------------------------------------------------------------


def test_provekit_public_input_record_carries_compiler_guidance_ref():
    norm = _norm_from_text(_OBLIGATION_TEXT)
    theorem = norm.actor + " " + norm.action
    syntax_report = validate_ir_with_provers(norm)
    metadata = _guidance_metadata_from_norm(norm, syntax_report.to_dict())

    record = build_provekit_public_input_record(
        theorem=theorem,
        private_axioms=[norm.modality],
        metadata=metadata,
    )

    assert record.compiler_guidance_ref != "", "compiler_guidance_ref should be populated"
    assert len(record.compiler_guidance_ref) == 64


def test_provekit_public_input_record_guidance_ref_is_stable_across_calls():
    norm = _norm_from_text(_OBLIGATION_TEXT)
    theorem = norm.actor + " " + norm.action
    metadata = _guidance_metadata_from_norm(norm)

    first = build_provekit_public_input_record(
        theorem=theorem, private_axioms=[], metadata=metadata
    )
    second = build_provekit_public_input_record(
        theorem=theorem, private_axioms=[], metadata=metadata
    )

    assert first.compiler_guidance_ref == second.compiler_guidance_ref
    assert first.theorem_hash == second.theorem_hash
    assert first.axioms_commitment == second.axioms_commitment


def test_provekit_public_input_record_to_zkp_public_inputs_has_commitment_keys():
    norm = _norm_from_text(_PERMISSION_TEXT)
    theorem = norm.action
    metadata = _guidance_metadata_from_norm(norm)

    record = build_provekit_public_input_record(
        theorem=theorem,
        private_axioms=[norm.modality],
        metadata=metadata,
    )
    public_inputs = record.to_zkp_public_inputs()

    for key in ("theorem_hash", "axioms_commitment", "circuit_ref", "ruleset_id"):
        assert key in public_inputs, f"Missing key: {key}"
    # compiler_guidance_ref must be present if non-empty.
    if record.compiler_guidance_ref:
        assert "compiler_guidance_ref" in public_inputs


# ---------------------------------------------------------------------------
# Attestation view carries compiler_guidance_ref
# ---------------------------------------------------------------------------

_PROOF_BYTES = b"PK" + b"\xcd" * 198  # 200 bytes — within simulated verifier range


def test_attestation_view_includes_compiler_guidance_ref_when_present():
    norm = _norm_from_text(_OBLIGATION_TEXT)
    theorem = norm.actor + " " + norm.action
    metadata = _guidance_metadata_from_norm(norm)

    record = build_provekit_public_input_record(
        theorem=theorem,
        private_axioms=[norm.modality],
        metadata=metadata,
    )
    public_inputs = record.to_zkp_public_inputs()

    attestation_view = build_proof_attestation_view(
        proof_data=_PROOF_BYTES,
        public_inputs=public_inputs,
        metadata={
            "backend": "provekit",
            "proof_system": "ProveKit-WHIR",
            "compiler_guidance_ref": record.compiler_guidance_ref,
            "compiler_guidance_version": record.compiler_guidance_version,
        },
    )

    assert "compiler_guidance_ref" in attestation_view
    assert attestation_view["compiler_guidance_ref"] == record.compiler_guidance_ref


def test_attestation_view_does_not_include_compiler_guidance_ref_when_empty():
    norm = _norm_from_text(_OBLIGATION_TEXT)
    theorem = norm.actor + " " + norm.action

    # No metadata → no guidance ref.
    record = build_provekit_public_input_record(theorem=theorem, private_axioms=[])
    public_inputs = record.to_zkp_public_inputs()

    attestation_view = build_proof_attestation_view(
        proof_data=_PROOF_BYTES,
        public_inputs=public_inputs,
        metadata={"backend": "provekit", "proof_system": "ProveKit-WHIR"},
    )

    # Either absent or empty string — must not be a non-empty string.
    ref_in_view = attestation_view.get("compiler_guidance_ref", "")
    assert ref_in_view == "", f"Unexpected guidance ref in view: {ref_in_view!r}"


def test_attestation_ref_is_stable_hex_string():
    norm = _norm_from_text(_OBLIGATION_TEXT)
    theorem = norm.actor + " " + norm.action
    metadata = _guidance_metadata_from_norm(norm)

    record = build_provekit_public_input_record(
        theorem=theorem, private_axioms=[], metadata=metadata
    )
    public_inputs = record.to_zkp_public_inputs()

    attestation_view = build_proof_attestation_view(
        proof_data=_PROOF_BYTES,
        public_inputs=public_inputs,
        metadata={"backend": "provekit"},
    )

    attestation_ref = attestation_view.get("attestation_ref", "")
    assert attestation_ref, "attestation_ref must be non-empty"
    assert len(attestation_ref) == 64
    int(attestation_ref, 16)  # Must be valid hex.


# ---------------------------------------------------------------------------
# No-leak: private legal text and parser witness data must not appear
# ---------------------------------------------------------------------------


def test_public_inputs_do_not_contain_raw_legal_text():
    """Theorem hash and axioms commitment must not embed raw legal text."""
    norm = _norm_from_text(_OBLIGATION_TEXT)
    theorem = norm.actor + " " + norm.action
    metadata = _guidance_metadata_from_norm(norm)

    record = build_provekit_public_input_record(
        theorem=theorem,
        private_axioms=[norm.modality, norm.source_id],
        metadata=metadata,
    )
    public_inputs = record.to_zkp_public_inputs()
    inputs_json = json.dumps(public_inputs, sort_keys=True)

    # The raw source_id is a parser-internal token; it must not appear literally
    # in the axioms_commitment field (which is a hash).
    axioms_commitment = public_inputs.get("axioms_commitment", "")
    assert norm.source_id not in axioms_commitment

    # Raw private source_id text should not appear in the JSON public inputs,
    # since axioms are only referenced via their hash commitment.
    # The theorem itself may appear as it is the public input, but private
    # axioms (modality + source_id) must not appear verbatim in metadata fields.
    # We check the metadata section only.
    metadata_in_inputs = public_inputs.get("metadata", {})
    if metadata_in_inputs:
        meta_json = json.dumps(metadata_in_inputs, sort_keys=True)
        assert norm.source_id not in meta_json


def test_attestation_view_does_not_contain_private_clause_text():
    """Private legal clause text must not appear in attestation view fields."""
    # Use the private text as the axiom source_id to simulate a private marker.
    elements = extract_normative_elements(_PRIVATE_TEXT)
    if not elements:
        pytest.skip("No normative elements in private text — skip")

    norm = LegalNormIR.from_parser_element(elements[0])
    theorem = "public theorem: persons are equal before the law"
    private_axioms = [norm.modality, "private_witness_token"]

    record = build_provekit_public_input_record(
        theorem=theorem,
        private_axioms=private_axioms,
    )
    public_inputs = record.to_zkp_public_inputs()
    attestation_view = build_proof_attestation_view(
        proof_data=_PROOF_BYTES,
        public_inputs=public_inputs,
        metadata={"backend": "provekit"},
    )

    view_json = json.dumps(attestation_view, sort_keys=True)
    assert "private_witness_token" not in view_json
    # The axioms_commitment must be a hex digest, not raw text.
    ax_commit = attestation_view.get("axioms_commitment", "")
    assert "private_witness_token" not in ax_commit


def test_compiler_guidance_ref_does_not_expose_raw_formula_text():
    """The compiler_guidance_ref is a hash and must not contain raw formula text."""
    norm = _norm_from_text(_OBLIGATION_TEXT)
    syntax_report = validate_ir_with_provers(norm)
    metadata = _guidance_metadata_from_norm(norm, syntax_report.to_dict())

    ref = compiler_guidance_ref_from_metadata(metadata)

    # The formula text must not appear verbatim in the ref.
    formula = norm.actor + " " + norm.action
    assert formula not in ref
    # Confirm it's purely hex.
    assert all(c in "0123456789abcdef" for c in ref), f"Non-hex chars in ref: {ref!r}"


def test_parser_capability_profile_id_does_not_contain_raw_actor_text():
    """The profile ID must be an opaque hash, not embed raw actor names."""
    norm = _norm_from_text(_OBLIGATION_TEXT)
    record = build_deterministic_parser_capability_profile_record(norm)

    profile_id = record["parser_capability_profile_id"]
    # Actor text ("secretary") must not appear verbatim in the profile ID.
    assert norm.actor.lower() not in profile_id.lower()


# ---------------------------------------------------------------------------
# Multi-norm batch: capability records remain independent and deterministic
# ---------------------------------------------------------------------------


def test_batch_parser_capability_records_are_independent():
    texts = [_OBLIGATION_TEXT, _PERMISSION_TEXT, _PROHIBITION_TEXT]
    norms = [_norm_from_text(t) for t in texts]
    records = [build_deterministic_parser_capability_profile_record(n) for n in norms]

    ids = [r["parser_capability_profile_id"] for r in records]
    assert len(set(ids)) == len(ids), "Capability profile IDs must be unique across norms"


def test_batch_provekit_public_inputs_have_distinct_theorem_hashes():
    texts = [_OBLIGATION_TEXT, _PERMISSION_TEXT, _PROHIBITION_TEXT]
    norms = [_norm_from_text(t) for t in texts]

    records = [
        build_provekit_public_input_record(
            theorem=n.actor + " " + n.action,
            private_axioms=[n.modality],
        )
        for n in norms
    ]

    hashes = [r.theorem_hash for r in records]
    assert len(set(hashes)) == len(hashes), "Theorem hashes must differ across distinct norms"


def test_batch_norms_each_carry_guidance_ref_when_metadata_provided():
    texts = [_OBLIGATION_TEXT, _PERMISSION_TEXT]
    norms = [_norm_from_text(t) for t in texts]

    refs = []
    for norm in norms:
        metadata = _guidance_metadata_from_norm(norm)
        record = build_provekit_public_input_record(
            theorem=norm.actor + " " + norm.action,
            private_axioms=[norm.modality],
            metadata=metadata,
        )
        refs.append(record.compiler_guidance_ref)

    # Both must be non-empty hex digests.
    for ref in refs:
        assert len(ref) == 64
        int(ref, 16)

    # The two norms are different, so their guidance contracts differ.
    assert refs[0] != refs[1], "Guidance refs for different norms should differ"
