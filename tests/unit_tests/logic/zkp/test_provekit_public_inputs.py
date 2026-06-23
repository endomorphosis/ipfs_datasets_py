import json

import pytest

from ipfs_datasets_py.logic.zkp.canonicalization import (
    axioms_commitment_hex,
    theorem_hash_hex,
)
from ipfs_datasets_py.logic.zkp.circuits import (
    compiler_guidance_ref_from_metadata,
)
from ipfs_datasets_py.logic.zkp.provekit.public_inputs import (
    DEFAULT_PROVEKIT_HASH_BACKEND,
    PROVEKIT_PUBLIC_INPUT_SCHEMA_VERSION,
    ProveKitPublicInputRecord,
    build_provekit_public_input_record,
    field_element_from_hex_digest,
    field_element_from_text,
)
from ipfs_datasets_py.logic.zkp.statement import Statement


def test_build_record_preserves_existing_hash_and_commitment_semantics():
    record = build_provekit_public_input_record(
        theorem="  Q\n",
        private_axioms=["P", "P -> Q", "P"],
    )

    assert record.theorem == "  Q\n"
    assert record.theorem_hash == theorem_hash_hex("Q")
    assert record.axioms_commitment == axioms_commitment_hex(["P", "P -> Q"])
    assert record.circuit_ref == "provekit_knowledge_of_axioms@v1"
    assert record.circuit_version == 1
    assert record.ruleset_id == "TDFOL_v1"
    assert record.hash_backend == DEFAULT_PROVEKIT_HASH_BACKEND


def test_zkp_public_inputs_keep_current_backend_neutral_shape():
    record = build_provekit_public_input_record(
        theorem="Q",
        private_axioms=["P", "P -> Q"],
        circuit_id="custom_circuit",
        circuit_version=3,
        ruleset_id="LegalIR_TDFOL_v1",
        hash_backend="sha256",
    )

    public_inputs = record.to_zkp_public_inputs()

    assert public_inputs == {
        "theorem": "Q",
        "theorem_hash": theorem_hash_hex("Q"),
        "axioms_commitment": axioms_commitment_hex(["P", "P -> Q"]),
        "circuit_ref": "custom_circuit@v3",
        "circuit_version": 3,
        "ruleset_id": "LegalIR_TDFOL_v1",
    }
    assert "hash_backend" not in public_inputs
    assert "schema_version" not in public_inputs


def test_provekit_envelope_contains_field_projection_without_private_axioms():
    private_axioms = ["private_rule(alpha)", "private_rule(alpha) -> Q"]
    record = build_provekit_public_input_record(
        theorem="Q",
        private_axioms=private_axioms,
    )

    provekit_inputs = record.to_provekit_inputs()
    payload = json.dumps(provekit_inputs, sort_keys=True)

    assert provekit_inputs["schema_version"] == PROVEKIT_PUBLIC_INPUT_SCHEMA_VERSION
    assert provekit_inputs["hash_backend"] == "sha256"
    assert provekit_inputs["zkp_public_inputs"] == record.to_zkp_public_inputs()
    assert set(provekit_inputs["noir_field_inputs"]) == {
        "theorem_hash_field",
        "axioms_commitment_field",
        "circuit_version",
        "ruleset_id_field",
        "circuit_ref_field",
        "compiler_guidance_ref_field",
        "compiler_guidance_version",
        "hash_backend_field",
    }
    for axiom in private_axioms:
        assert axiom not in payload


def test_noir_field_projection_matches_statement_field_elements_for_core_fields():
    record = build_provekit_public_input_record(
        theorem="Q",
        private_axioms=["P", "P -> Q"],
        circuit_version=2,
        ruleset_id="TDFOL_v1",
    )

    fields = record.to_noir_field_inputs()
    statement_fields = Statement(
        theorem_hash=record.theorem_hash,
        axioms_commitment=record.axioms_commitment,
        circuit_version=record.circuit_version,
        ruleset_id=record.ruleset_id,
    ).to_field_elements()

    assert fields["theorem_hash_field"] == statement_fields[0]
    assert fields["axioms_commitment_field"] == statement_fields[1]
    assert fields["circuit_version"] == statement_fields[2]
    assert fields["ruleset_id_field"] == statement_fields[3]
    assert fields["circuit_ref_field"] == field_element_from_text(record.circuit_ref)
    assert fields["hash_backend_field"] == field_element_from_text("sha256")


def test_legacy_and_mismatched_circuit_refs_are_canonicalized_to_requested_version():
    legacy = build_provekit_public_input_record(
        theorem="Q",
        private_axioms=["P"],
        circuit_ref="legacy_circuit",
        circuit_version=4,
    )
    mismatched = build_provekit_public_input_record(
        theorem="Q",
        private_axioms=["P"],
        circuit_ref="legacy_circuit@v9",
        circuit_version=4,
    )

    assert legacy.circuit_ref == "legacy_circuit@v4"
    assert mismatched.circuit_ref == "legacy_circuit@v4"


def test_compiler_guidance_contract_is_mapped_to_existing_guidance_ref():
    metadata = {
        "compiler_guidance_contract": {
            "repair_hint": "prefer_tdfol_trace",
            "version": 1,
        }
    }

    record = build_provekit_public_input_record(
        theorem="Q",
        private_axioms=["P"],
        metadata=metadata,
    )
    expected_ref = compiler_guidance_ref_from_metadata(metadata)

    assert record.compiler_guidance_ref == expected_ref
    assert record.compiler_guidance_version == 1
    assert record.to_zkp_public_inputs()["compiler_guidance_ref"] == expected_ref
    assert record.to_noir_field_inputs()["compiler_guidance_ref_field"] == (
        field_element_from_hex_digest(expected_ref)
    )


def test_from_zkp_public_inputs_preserves_existing_optional_attestation_fields():
    public_inputs = {
        "theorem": "Q",
        "theorem_hash": theorem_hash_hex("Q"),
        "axioms_commitment": axioms_commitment_hex(["P"]),
        "circuit_ref": "knowledge_of_axioms",
        "circuit_version": 2,
        "ruleset_id": "TDFOL_v1",
        "attestation_ref": "a" * 64,
        "attestation_view_version": 1,
    }

    record = ProveKitPublicInputRecord.from_zkp_public_inputs(
        public_inputs,
        metadata={"hash_backend": "sha256"},
    )

    assert record.circuit_ref == "knowledge_of_axioms@v2"
    assert record.attestation_ref == "a" * 64
    assert record.attestation_view_version == 1
    assert record.to_zkp_public_inputs()["attestation_ref"] == "a" * 64


def test_with_attestation_derives_public_attestation_fields():
    record = build_provekit_public_input_record(
        theorem="Q",
        private_axioms=["P"],
    )

    attested = record.with_attestation(
        proof_data=b"provekit-proof-bytes",
        metadata={"backend": "provekit", "proof_system": "ProveKit-WHIR"},
    )

    assert attested.attestation_ref
    assert len(attested.attestation_ref) == 64
    assert attested.attestation_view_version == 1
    assert attested.to_zkp_public_inputs()["attestation_ref"] == (
        attested.attestation_ref
    )


def test_canonical_json_and_hash_are_deterministic():
    record = build_provekit_public_input_record(
        theorem="Q",
        private_axioms=["P", "P -> Q"],
    )
    same = build_provekit_public_input_record(
        theorem="Q",
        private_axioms=["P -> Q", "P"],
    )

    assert record.canonical_json() == same.canonical_json()
    assert record.canonical_hash() == same.canonical_hash()


@pytest.mark.parametrize(
    "kwargs",
    [
        {"theorem": "", "theorem_hash": "0" * 64, "axioms_commitment": "0" * 64},
        {"theorem": "Q", "theorem_hash": "0" * 63, "axioms_commitment": "0" * 64},
        {"theorem": "Q", "theorem_hash": "G" * 64, "axioms_commitment": "0" * 64},
        {"theorem": "Q", "theorem_hash": "A" * 64, "axioms_commitment": "0" * 64},
    ],
)
def test_record_rejects_invalid_core_public_inputs(kwargs):
    base = {
        "theorem": "Q",
        "theorem_hash": theorem_hash_hex("Q"),
        "axioms_commitment": axioms_commitment_hex(["P"]),
        "circuit_ref": "provekit_knowledge_of_axioms@v1",
        "circuit_version": 1,
        "ruleset_id": "TDFOL_v1",
    }
    base.update(kwargs)

    with pytest.raises((TypeError, ValueError)):
        ProveKitPublicInputRecord(**base)

