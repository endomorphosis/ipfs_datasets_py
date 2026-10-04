"""Golden-vector regression tests for ProveKit ZKP logic.

Each vector in provekit_golden_vectors.json pins the expected output of a
deterministic function (canonicalization, public-input building, Prover.toml
rendering, attestation-ref derivation, or verifier-key hashing).  A failing
test here means a function's output changed in a way that would silently break
proof/verification round-trips.

Depends on: PROVEKIT-060, PROVEKIT-110, PROVEKIT-140
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.zkp.canonicalization import (
    axioms_commitment_hex,
    canonicalize_axioms,
    normalize_text,
    theorem_hash_hex,
)
from ipfs_datasets_py.logic.zkp.circuits import build_proof_attestation_view
from ipfs_datasets_py.logic.zkp.provekit.public_inputs import (
    build_provekit_public_input_record,
)
from ipfs_datasets_py.logic.zkp.provekit.witness import (
    render_knowledge_of_axioms_prover_toml,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

VECTORS_PATH = Path(__file__).parent / "provekit_golden_vectors.json"


@pytest.fixture(scope="module")
def vectors() -> dict:
    return json.loads(VECTORS_PATH.read_text(encoding="utf-8"))["vectors"]


# ---------------------------------------------------------------------------
# Theorem canonicalization
# ---------------------------------------------------------------------------


class TestTheoremCanonicalization:
    def test_modus_ponens_theorem_hash(self, vectors: dict) -> None:
        v = vectors["modus_ponens"]
        assert theorem_hash_hex(v["theorem"]) == v["theorem_hash"]

    def test_three_axiom_chain_theorem_hash(self, vectors: dict) -> None:
        v = vectors["three_axiom_chain"]
        assert theorem_hash_hex(v["theorem"]) == v["theorem_hash"]

    def test_syllogism_theorem_hash(self, vectors: dict) -> None:
        v = vectors["syllogism"]
        assert theorem_hash_hex(v["theorem"]) == v["theorem_hash"]

    def test_whitespace_theorem_hash_matches_canonical(self, vectors: dict) -> None:
        v = vectors["whitespace_normalization"]
        computed = theorem_hash_hex(v["theorem_raw"])
        assert computed == v["theorem_hash"]
        assert v["theorem_hash_matches_canonical"] is True

    def test_normalize_text_collapses_whitespace(self) -> None:
        assert normalize_text("  Q  ") == "Q"
        assert normalize_text("P  ->   Q") == "P -> Q"
        assert normalize_text("All  humans  are  mortal") == "All humans are mortal"

    def test_different_theorems_produce_different_hashes(self, vectors: dict) -> None:
        h1 = vectors["modus_ponens"]["theorem_hash"]
        h2 = vectors["three_axiom_chain"]["theorem_hash"]
        h3 = vectors["syllogism"]["theorem_hash"]
        assert len({h1, h2, h3}) == 3


# ---------------------------------------------------------------------------
# Axiom commitments
# ---------------------------------------------------------------------------


class TestAxiomCommitments:
    def test_modus_ponens_axioms_commitment(self, vectors: dict) -> None:
        v = vectors["modus_ponens"]
        assert axioms_commitment_hex(v["private_axioms"]) == v["axioms_commitment"]

    def test_axiom_reorder_commitment_matches_modus_ponens(self, vectors: dict) -> None:
        v = vectors["axiom_reorder"]
        computed = axioms_commitment_hex(v["private_axioms"])
        assert computed == v["expected_axioms_commitment"]
        assert v["matches_modus_ponens_commitment"] is True

    def test_whitespace_axioms_commitment_matches_canonical(self, vectors: dict) -> None:
        v = vectors["whitespace_normalization"]
        computed = axioms_commitment_hex(v["axioms_raw"])
        assert computed == v["axioms_commitment"]

    def test_deduplication_commitment(self, vectors: dict) -> None:
        v = vectors["deduplication"]
        computed = axioms_commitment_hex(v["axioms"])
        assert computed == v["axioms_commitment"]
        assert v["matches_single_p"] is True
        assert canonicalize_axioms(v["axioms"]) == v["canonical_axioms"]

    def test_three_axiom_chain_commitment(self, vectors: dict) -> None:
        v = vectors["three_axiom_chain"]
        assert axioms_commitment_hex(v["private_axioms"]) == v["axioms_commitment"]

    def test_syllogism_commitment(self, vectors: dict) -> None:
        v = vectors["syllogism"]
        assert axioms_commitment_hex(v["private_axioms"]) == v["axioms_commitment"]

    def test_different_axiom_sets_produce_different_commitments(self, vectors: dict) -> None:
        c1 = vectors["modus_ponens"]["axioms_commitment"]
        c2 = vectors["three_axiom_chain"]["axioms_commitment"]
        c3 = vectors["syllogism"]["axioms_commitment"]
        assert len({c1, c2, c3}) == 3


# ---------------------------------------------------------------------------
# Public inputs
# ---------------------------------------------------------------------------


class TestPublicInputs:
    def test_modus_ponens_public_inputs_shape(self, vectors: dict) -> None:
        v = vectors["modus_ponens"]
        record = build_provekit_public_input_record(
            theorem=v["theorem"],
            private_axioms=v["private_axioms"],
        )
        assert record.to_zkp_public_inputs() == v["public_inputs"]

    def test_modus_ponens_circuit_ref(self, vectors: dict) -> None:
        v = vectors["modus_ponens"]
        record = build_provekit_public_input_record(
            theorem=v["theorem"],
            private_axioms=v["private_axioms"],
        )
        assert record.circuit_ref == v["circuit_ref"]
        assert record.circuit_version == v["circuit_version"]

    def test_modus_ponens_noir_field_inputs(self, vectors: dict) -> None:
        v = vectors["modus_ponens"]
        record = build_provekit_public_input_record(
            theorem=v["theorem"],
            private_axioms=v["private_axioms"],
        )
        computed = record.to_noir_field_inputs()
        expected = {k: int(val) for k, val in v["noir_field_inputs"].items()}
        assert computed == expected

    def test_modus_ponens_canonical_hash(self, vectors: dict) -> None:
        v = vectors["modus_ponens"]
        record = build_provekit_public_input_record(
            theorem=v["theorem"],
            private_axioms=v["private_axioms"],
        )
        assert record.canonical_hash() == v["canonical_hash"]

    def test_three_axiom_chain_public_inputs(self, vectors: dict) -> None:
        v = vectors["three_axiom_chain"]
        record = build_provekit_public_input_record(
            theorem=v["theorem"],
            private_axioms=v["private_axioms"],
        )
        assert record.to_zkp_public_inputs() == v["public_inputs"]
        assert record.canonical_hash() == v["canonical_hash"]

    def test_syllogism_public_inputs(self, vectors: dict) -> None:
        v = vectors["syllogism"]
        record = build_provekit_public_input_record(
            theorem=v["theorem"],
            private_axioms=v["private_axioms"],
        )
        assert record.to_zkp_public_inputs() == v["public_inputs"]
        assert record.canonical_hash() == v["canonical_hash"]

    def test_compiler_guidance_public_inputs(self, vectors: dict) -> None:
        v = vectors["with_compiler_guidance"]
        record = build_provekit_public_input_record(
            theorem=v["theorem"],
            private_axioms=v["private_axioms"],
            metadata={
                "compiler_guidance_ref": v["compiler_guidance_ref"],
                "compiler_guidance_version": v["compiler_guidance_version"],
            },
        )
        pi = record.to_zkp_public_inputs()
        assert pi == v["public_inputs"]
        assert record.canonical_hash() == v["canonical_hash"]
        assert "compiler_guidance_ref" in pi
        assert pi["compiler_guidance_version"] == v["compiler_guidance_version"]

    def test_public_inputs_exclude_private_axiom_text(self, vectors: dict) -> None:
        v = vectors["modus_ponens"]
        record = build_provekit_public_input_record(
            theorem=v["theorem"],
            private_axioms=v["private_axioms"],
        )
        pi_str = json.dumps(record.to_zkp_public_inputs())
        for axiom in v["private_axioms"]:
            assert axiom not in pi_str, f"Private axiom leaked: {axiom}"


# ---------------------------------------------------------------------------
# Prover.toml rendering
# ---------------------------------------------------------------------------


class TestProverToml:
    def test_modus_ponens_prover_toml_exact(self, vectors: dict) -> None:
        v = vectors["modus_ponens"]
        record = build_provekit_public_input_record(
            theorem=v["theorem"],
            private_axioms=v["private_axioms"],
        )
        rendered = render_knowledge_of_axioms_prover_toml(record)
        assert rendered == v["prover_toml"]

    def test_prover_toml_contains_field_keys(self, vectors: dict) -> None:
        v = vectors["modus_ponens"]
        record = build_provekit_public_input_record(
            theorem=v["theorem"],
            private_axioms=v["private_axioms"],
        )
        rendered = render_knowledge_of_axioms_prover_toml(record)
        required_keys = [
            "theorem_hash_field",
            "axioms_commitment_field",
            "circuit_ref_field",
            "circuit_version",
            "ruleset_id_field",
            "hash_backend_field",
        ]
        for key in required_keys:
            assert key in rendered, f"Missing key in Prover.toml: {key}"

    def test_prover_toml_does_not_contain_private_axiom_text(self, vectors: dict) -> None:
        v = vectors["modus_ponens"]
        record = build_provekit_public_input_record(
            theorem=v["theorem"],
            private_axioms=v["private_axioms"],
        )
        rendered = render_knowledge_of_axioms_prover_toml(record)
        for axiom in v["private_axioms"]:
            assert axiom not in rendered, f"Private axiom leaked into Prover.toml: {axiom}"

    def test_prover_toml_is_deterministic(self, vectors: dict) -> None:
        v = vectors["modus_ponens"]
        record = build_provekit_public_input_record(
            theorem=v["theorem"],
            private_axioms=v["private_axioms"],
        )
        first = render_knowledge_of_axioms_prover_toml(record)
        second = render_knowledge_of_axioms_prover_toml(record)
        assert first == second


# ---------------------------------------------------------------------------
# Attestation refs
# ---------------------------------------------------------------------------


class TestAttestationRefs:
    def test_modus_ponens_attestation_ref_pinned(self, vectors: dict) -> None:
        v = vectors["modus_ponens"]
        record = build_provekit_public_input_record(
            theorem=v["theorem"],
            private_axioms=v["private_axioms"],
        )
        att = build_proof_attestation_view(
            proof_data=b"PROOF_BYTES",
            public_inputs=record.to_zkp_public_inputs(include_attestation=False),
            metadata={"hash_backend": "sha256"},
        )
        assert att["attestation_ref"] == v["attestation_ref"]
        assert att["attestation_view_version"] == v["attestation_view_version"]

    def test_attestation_ref_is_32_byte_hex(self, vectors: dict) -> None:
        v = vectors["modus_ponens"]
        ref = v["attestation_ref"]
        assert len(ref) == 64
        assert all(c in "0123456789abcdef" for c in ref)

    def test_attestation_ref_differs_from_theorem_hash(self, vectors: dict) -> None:
        v = vectors["modus_ponens"]
        assert v["attestation_ref"] != v["theorem_hash"]

    def test_attestation_ref_is_deterministic(self, vectors: dict) -> None:
        v = vectors["modus_ponens"]
        record = build_provekit_public_input_record(
            theorem=v["theorem"],
            private_axioms=v["private_axioms"],
        )
        pi = record.to_zkp_public_inputs(include_attestation=False)
        att1 = build_proof_attestation_view(
            proof_data=b"PROOF_BYTES",
            public_inputs=pi,
            metadata={"hash_backend": "sha256"},
        )
        att2 = build_proof_attestation_view(
            proof_data=b"PROOF_BYTES",
            public_inputs=pi,
            metadata={"hash_backend": "sha256"},
        )
        assert att1["attestation_ref"] == att2["attestation_ref"]

    def test_different_proof_bytes_produce_different_attestation_ref(self, vectors: dict) -> None:
        v = vectors["modus_ponens"]
        record = build_provekit_public_input_record(
            theorem=v["theorem"],
            private_axioms=v["private_axioms"],
        )
        pi = record.to_zkp_public_inputs(include_attestation=False)
        meta = {"hash_backend": "sha256"}
        att1 = build_proof_attestation_view(
            proof_data=b"PROOF_BYTES_A",
            public_inputs=pi,
            metadata=meta,
        )
        att2 = build_proof_attestation_view(
            proof_data=b"PROOF_BYTES_B",
            public_inputs=pi,
            metadata=meta,
        )
        assert att1["attestation_ref"] != att2["attestation_ref"]


# ---------------------------------------------------------------------------
# Verifier-key digests
# ---------------------------------------------------------------------------


class TestVerifierKeyDigests:
    def test_simulated_vk_digest_pinned(self, vectors: dict) -> None:
        v = vectors["verifier_key_digest"]
        vk_bytes = v["vk_source_label"].encode("utf-8")
        computed = hashlib.sha256(vk_bytes).hexdigest()
        assert computed == v["vk_digest_sha256"]

    def test_vk_digest_is_32_byte_hex(self, vectors: dict) -> None:
        v = vectors["verifier_key_digest"]
        digest = v["vk_digest_sha256"]
        assert len(digest) == 64
        assert all(c in "0123456789abcdef" for c in digest)

    def test_vk_digest_circuit_ref_present(self, vectors: dict) -> None:
        v = vectors["verifier_key_digest"]
        assert v["circuit_ref"] == "provekit_knowledge_of_axioms@v1"


# ---------------------------------------------------------------------------
# JSON file integrity
# ---------------------------------------------------------------------------


class TestGoldenVectorFileIntegrity:
    def test_all_expected_vectors_present(self, vectors: dict) -> None:
        expected = {
            "modus_ponens",
            "axiom_reorder",
            "whitespace_normalization",
            "deduplication",
            "three_axiom_chain",
            "syllogism",
            "with_compiler_guidance",
            "verifier_key_digest",
        }
        assert expected.issubset(set(vectors.keys()))

    def test_all_hex_fields_are_64_char_lowercase(self, vectors: dict) -> None:
        hex_fields = {
            "theorem_hash",
            "axioms_commitment",
            "attestation_ref",
            "canonical_hash",
            "compiler_guidance_ref",
        }
        for name, v in vectors.items():
            for field in hex_fields:
                if field in v:
                    val = v[field]
                    assert isinstance(val, str), f"{name}.{field} must be str"
                    assert len(val) == 64, f"{name}.{field} must be 64 chars"
                    assert val == val.lower(), f"{name}.{field} must be lowercase"
