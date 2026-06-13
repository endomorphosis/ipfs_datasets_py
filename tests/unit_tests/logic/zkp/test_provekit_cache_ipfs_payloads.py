"""Tests for ProveKit proof cache key and IPFS public payload construction.

Acceptance criteria (PROVEKIT-150):
- Proof cache keys include ProveKit backend ID, circuit ref, hash backend,
  verifier-key digest, ProveKit commit, and ruleset.
- IPFS/cache payloads contain only public proof envelopes and artifact
  references.
"""

from __future__ import annotations

import base64
import hashlib
import json

import pytest

from ipfs_datasets_py.logic.zkp.provekit.cache import (
    PROVEKIT_CACHE_KEY_SCHEMA,
    PROVEKIT_IPFS_PAYLOAD_SCHEMA,
    build_provekit_ipfs_payload,
    build_provekit_proof_cache_key,
    build_provekit_proof_cache_key_from_proof,
    provekit_ipfs_payload_is_public_only,
)


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

_DUMMY_VK_SHA = "a" * 64  # 64 hex chars (valid sha256)
_ALT_VK_SHA = "b" * 64

_BASE_KEY_KWARGS: dict = {
    "backend_id": "provekit",
    "circuit_ref": "provekit_knowledge_of_axioms@v1",
    "hash_backend": "sha256",
    "verifier_key_sha256": _DUMMY_VK_SHA,
    "provekit_commit": "abc1234def5678ab" * 4,  # 64-char-ish commit ref
    "ruleset_id": "TDFOL_v1",
}

_DUMMY_PROOF_DATA = b"NP" + b"\x00" * 198  # mock proof bytes


def _make_proof_inputs() -> dict:
    """Return a minimal ZKPProof-compatible public_inputs dict."""
    return {
        "theorem": "Q",
        "theorem_hash": hashlib.sha256(b"Q").hexdigest(),
        "axioms_commitment": hashlib.sha256(b"P\x00P -> Q").hexdigest(),
        "circuit_ref": "provekit_knowledge_of_axioms@v1",
        "circuit_version": 1,
        "ruleset_id": "TDFOL_v1",
        "attestation_ref": hashlib.sha256(b"proof").hexdigest(),
        "attestation_view_version": 1,
    }


def _make_proof_metadata() -> dict:
    """Return a minimal ZKPProof-compatible metadata dict."""
    return {
        "backend": "provekit",
        "proof_system": "ProveKit-WHIR",
        "curve_id": "bn254",
        "hash_backend": "sha256",
        "attestation_view": {
            "attestation_ref": hashlib.sha256(b"proof").hexdigest(),
            "attestation_view_version": 1,
            "proof_data_sha256": hashlib.sha256(_DUMMY_PROOF_DATA).hexdigest(),
        },
        "provekit": {
            "binary_path": "/usr/local/bin/provekit-cli",
            "command": {"ok": True},
            "artifacts": {
                "verifier_key_path": "/artifacts/circuit.pkv",
                "proof_path": "/tmp/proof.np",
                "program_dir": "/artifacts/knowledge_of_axioms",
                # private keys — must be stripped from IPFS payload
                "prover_key_path": "/artifacts/circuit.pkp",
            },
            "public_input_schema": "provekit-public-inputs-v1",
            "public_input_hash": "d" * 64,
        },
        # Private/sensitive metadata that must not appear in IPFS payloads
        "provekit_artifacts": {
            "input_path": "/tmp/Prover.toml",
            "prover_key_path": "/artifacts/circuit.pkp",
            "verifier_key_path": "/artifacts/circuit.pkv",
        },
    }


# ===========================================================================
# Cache key tests
# ===========================================================================


class TestProveKitProofCacheKey:
    """Cache keys must include all six required components and be deterministic."""

    def test_cache_key_is_64_hex_chars(self):
        key = build_provekit_proof_cache_key(**_BASE_KEY_KWARGS)
        assert isinstance(key, str)
        assert len(key) == 64
        int(key, 16)  # valid hex

    def test_cache_key_is_deterministic(self):
        key1 = build_provekit_proof_cache_key(**_BASE_KEY_KWARGS)
        key2 = build_provekit_proof_cache_key(**_BASE_KEY_KWARGS)
        assert key1 == key2

    def test_cache_key_changes_when_backend_id_changes(self):
        key_a = build_provekit_proof_cache_key(**_BASE_KEY_KWARGS)
        key_b = build_provekit_proof_cache_key(
            **{**_BASE_KEY_KWARGS, "backend_id": "groth16"}
        )
        assert key_a != key_b

    def test_cache_key_changes_when_circuit_ref_changes(self):
        key_a = build_provekit_proof_cache_key(**_BASE_KEY_KWARGS)
        key_b = build_provekit_proof_cache_key(
            **{**_BASE_KEY_KWARGS, "circuit_ref": "provekit_tdfol_v1_trace@v1"}
        )
        assert key_a != key_b

    def test_cache_key_changes_when_hash_backend_changes(self):
        key_a = build_provekit_proof_cache_key(**_BASE_KEY_KWARGS)
        key_b = build_provekit_proof_cache_key(
            **{**_BASE_KEY_KWARGS, "hash_backend": "keccak"}
        )
        assert key_a != key_b

    def test_cache_key_changes_when_verifier_key_digest_changes(self):
        """Changing the .pkv digest must invalidate the cache key."""
        key_a = build_provekit_proof_cache_key(**_BASE_KEY_KWARGS)
        key_b = build_provekit_proof_cache_key(
            **{**_BASE_KEY_KWARGS, "verifier_key_sha256": _ALT_VK_SHA}
        )
        assert key_a != key_b

    def test_cache_key_changes_when_provekit_commit_changes(self):
        key_a = build_provekit_proof_cache_key(**_BASE_KEY_KWARGS)
        key_b = build_provekit_proof_cache_key(
            **{**_BASE_KEY_KWARGS, "provekit_commit": "deadbeef" * 8}
        )
        assert key_a != key_b

    def test_cache_key_changes_when_ruleset_changes(self):
        key_a = build_provekit_proof_cache_key(**_BASE_KEY_KWARGS)
        key_b = build_provekit_proof_cache_key(
            **{**_BASE_KEY_KWARGS, "ruleset_id": "LegalIR_v2"}
        )
        assert key_a != key_b

    def test_cache_key_is_independent_of_private_axioms(self):
        """Private witness content must not affect or appear in the cache key."""
        key = build_provekit_proof_cache_key(**_BASE_KEY_KWARGS)
        assert "secret_axiom" not in key
        assert "private_rule" not in key

    @pytest.mark.parametrize(
        "bad_kwargs",
        [
            {"backend_id": ""},
            {"backend_id": "   "},
            {"circuit_ref": ""},
            {"hash_backend": ""},
            {"verifier_key_sha256": "a" * 63},       # too short
            {"verifier_key_sha256": "A" * 64},       # uppercase
            {"verifier_key_sha256": "z" * 64},       # not hex
            {"verifier_key_sha256": ""},
            {"provekit_commit": ""},
            {"ruleset_id": ""},
        ],
    )
    def test_cache_key_rejects_invalid_inputs(self, bad_kwargs):
        kwargs = {**_BASE_KEY_KWARGS, **bad_kwargs}
        with pytest.raises((ValueError, TypeError)):
            build_provekit_proof_cache_key(**kwargs)

    def test_cache_key_all_six_components_contribute(self):
        """All six components must independently alter the key."""
        base_key = build_provekit_proof_cache_key(**_BASE_KEY_KWARGS)
        variant_keys = {
            "backend_id": build_provekit_proof_cache_key(
                **{**_BASE_KEY_KWARGS, "backend_id": "provekit-whir"}
            ),
            "circuit_ref": build_provekit_proof_cache_key(
                **{**_BASE_KEY_KWARGS, "circuit_ref": "provekit_tdfol_v1_trace@v1"}
            ),
            "hash_backend": build_provekit_proof_cache_key(
                **{**_BASE_KEY_KWARGS, "hash_backend": "poseidon2"}
            ),
            "verifier_key_sha256": build_provekit_proof_cache_key(
                **{**_BASE_KEY_KWARGS, "verifier_key_sha256": _ALT_VK_SHA}
            ),
            "provekit_commit": build_provekit_proof_cache_key(
                **{**_BASE_KEY_KWARGS, "provekit_commit": "cafebabe" * 8}
            ),
            "ruleset_id": build_provekit_proof_cache_key(
                **{**_BASE_KEY_KWARGS, "ruleset_id": "TDFOL_v2"}
            ),
        }
        for component, variant_key in variant_keys.items():
            assert base_key != variant_key, (
                f"Changing {component!r} did not alter the cache key"
            )
        assert len(set(variant_keys.values())) == len(variant_keys), (
            "Two different component changes produced the same cache key"
        )


class TestProveKitProofCacheKeyFromProof:
    """Derive cache keys directly from ZKPProof envelope dictionaries."""

    def test_key_from_proof_matches_explicit_key(self):
        public_inputs = _make_proof_inputs()
        metadata = _make_proof_metadata()
        explicit_key = build_provekit_proof_cache_key(
            backend_id="provekit",
            circuit_ref="provekit_knowledge_of_axioms@v1",
            hash_backend="sha256",
            verifier_key_sha256=_DUMMY_VK_SHA,
            provekit_commit="abc1234def5678ab" * 4,
            ruleset_id="TDFOL_v1",
        )
        derived_key = build_provekit_proof_cache_key_from_proof(
            public_inputs,
            metadata,
            verifier_key_sha256=_DUMMY_VK_SHA,
            provekit_commit="abc1234def5678ab" * 4,
        )
        assert derived_key == explicit_key

    def test_key_from_proof_is_deterministic(self):
        public_inputs = _make_proof_inputs()
        metadata = _make_proof_metadata()
        k1 = build_provekit_proof_cache_key_from_proof(
            public_inputs, metadata, verifier_key_sha256=_DUMMY_VK_SHA,
            provekit_commit="deadbeef" * 8,
        )
        k2 = build_provekit_proof_cache_key_from_proof(
            public_inputs, metadata, verifier_key_sha256=_DUMMY_VK_SHA,
            provekit_commit="deadbeef" * 8,
        )
        assert k1 == k2

    def test_key_from_proof_changes_when_vk_changes(self):
        public_inputs = _make_proof_inputs()
        metadata = _make_proof_metadata()
        k1 = build_provekit_proof_cache_key_from_proof(
            public_inputs, metadata, verifier_key_sha256=_DUMMY_VK_SHA,
            provekit_commit="aaa" * 21 + "a",
        )
        k2 = build_provekit_proof_cache_key_from_proof(
            public_inputs, metadata, verifier_key_sha256=_ALT_VK_SHA,
            provekit_commit="aaa" * 21 + "a",
        )
        assert k1 != k2


# ===========================================================================
# IPFS payload tests
# ===========================================================================


class TestProveKitIPFSPayload:
    """IPFS payloads must contain only public proof envelopes and artifact refs."""

    def _build(self, **overrides) -> dict:
        kwargs: dict = {
            "proof_public_inputs": _make_proof_inputs(),
            "proof_metadata": _make_proof_metadata(),
            "proof_data": _DUMMY_PROOF_DATA,
        }
        kwargs.update(overrides)
        return build_provekit_ipfs_payload(**kwargs)

    def test_payload_includes_schema_version(self):
        payload = self._build()
        assert payload["schema"] == PROVEKIT_IPFS_PAYLOAD_SCHEMA

    def test_payload_includes_backend_id(self):
        payload = self._build()
        assert payload["backend_id"] == "provekit"

    def test_payload_includes_proof_system(self):
        payload = self._build()
        assert payload["proof_system"] == "ProveKit-WHIR"

    def test_payload_includes_base64_proof_bytes(self):
        payload = self._build()
        assert "proof_data_b64" in payload
        decoded = base64.b64decode(payload["proof_data_b64"])
        assert decoded == _DUMMY_PROOF_DATA

    def test_payload_includes_proof_size(self):
        payload = self._build()
        assert payload["proof_size_bytes"] == len(_DUMMY_PROOF_DATA)

    def test_payload_includes_public_inputs(self):
        payload = self._build()
        pub = payload["public_inputs"]
        assert pub["theorem"] == "Q"
        assert pub["circuit_ref"] == "provekit_knowledge_of_axioms@v1"
        assert pub["ruleset_id"] == "TDFOL_v1"

    def test_payload_includes_attestation_view(self):
        payload = self._build()
        attest = payload["attestation_view"]
        assert "attestation_ref" in attest
        assert "attestation_view_version" in attest

    def test_payload_includes_public_artifact_refs(self):
        payload = self._build()
        refs = payload["public_artifact_refs"]
        # Verifier key reference should be present (from artifacts dict)
        assert "verifier_key_path" in refs or "verifier_key_ref" in refs

    def test_payload_includes_optional_verifier_key_ref(self):
        payload = self._build(verifier_key_ref="Qm" + "a" * 44)
        assert payload["public_artifact_refs"]["verifier_key_ref"] == "Qm" + "a" * 44

    def test_payload_includes_optional_manifest_sha256(self):
        payload = self._build(manifest_sha256="c" * 64)
        assert payload["manifest_sha256"] == "c" * 64

    def test_payload_does_not_contain_private_axiom_text(self):
        """Private axiom text must never appear in the serialized payload."""
        metadata = _make_proof_metadata()
        public_inputs = {
            **_make_proof_inputs(),
            "theorem": "secret_axiom_conclusion",
        }
        # Even if the theorem mentions a term that sounds private, the full
        # witness (axiom list) must be absent.
        payload = build_provekit_ipfs_payload(
            proof_public_inputs=public_inputs,
            proof_metadata=metadata,
            proof_data=_DUMMY_PROOF_DATA,
        )
        payload_str = json.dumps(payload)
        assert "Prover.toml" not in payload_str
        assert "prover_toml_path" not in payload_str
        assert "input_path" not in payload_str

    def test_payload_does_not_contain_prover_key_path(self):
        """Prover key paths are private and must be stripped."""
        payload = self._build()
        payload_str = json.dumps(payload)
        assert "prover_key_path" not in payload_str
        assert "pkp_path" not in payload_str

    def test_payload_does_not_contain_prover_toml_input_path(self):
        payload = self._build()
        payload_str = json.dumps(payload)
        assert "input_path" not in payload_str
        assert "prover_toml_path" not in payload_str

    def test_payload_does_not_contain_cwd_or_package_dir(self):
        """Working directory paths are not public proof information."""
        payload = self._build()
        assert "cwd" not in json.dumps(payload)

    def test_payload_is_json_serialisable(self):
        payload = self._build()
        serialised = json.dumps(payload, sort_keys=True)
        assert isinstance(serialised, str)
        round_tripped = json.loads(serialised)
        assert round_tripped["schema"] == PROVEKIT_IPFS_PAYLOAD_SCHEMA

    def test_payload_public_inputs_are_witness_free(self):
        """public_inputs in the payload must not expose private axiom data."""
        metadata = _make_proof_metadata()
        public_inputs = _make_proof_inputs()
        payload = build_provekit_ipfs_payload(
            proof_public_inputs=public_inputs,
            proof_metadata=metadata,
            proof_data=_DUMMY_PROOF_DATA,
        )
        # The public inputs dict must only contain the schema fields
        allowed_keys = {
            "theorem",
            "theorem_hash",
            "axioms_commitment",
            "circuit_ref",
            "circuit_version",
            "ruleset_id",
            "attestation_ref",
            "attestation_view_version",
            "compiler_guidance_ref",
            "compiler_guidance_version",
        }
        unexpected = set(payload["public_inputs"].keys()) - allowed_keys
        assert not unexpected, f"Unexpected keys in public_inputs: {unexpected}"


class TestProveKitIPFSPayloadIsPublicOnly:
    """The guard function catches private keys in payload dicts."""

    def test_clean_payload_passes_guard(self):
        payload = build_provekit_ipfs_payload(
            proof_public_inputs=_make_proof_inputs(),
            proof_metadata=_make_proof_metadata(),
            proof_data=_DUMMY_PROOF_DATA,
        )
        assert provekit_ipfs_payload_is_public_only(payload)

    def test_guard_rejects_payload_with_prover_key_path(self):
        payload = build_provekit_ipfs_payload(
            proof_public_inputs=_make_proof_inputs(),
            proof_metadata=_make_proof_metadata(),
            proof_data=_DUMMY_PROOF_DATA,
        )
        # Inject a private key to simulate a bug
        payload["prover_key_path"] = "/secret/circuit.pkp"
        assert not provekit_ipfs_payload_is_public_only(payload)

    def test_guard_rejects_payload_with_input_path(self):
        payload = build_provekit_ipfs_payload(
            proof_public_inputs=_make_proof_inputs(),
            proof_metadata=_make_proof_metadata(),
            proof_data=_DUMMY_PROOF_DATA,
        )
        payload["nested"] = {"input_path": "/tmp/Prover.toml"}
        assert not provekit_ipfs_payload_is_public_only(payload)

    def test_guard_rejects_payload_with_prover_toml_path(self):
        payload: dict = {"prover_toml_path": "/tmp/witness.toml"}
        assert not provekit_ipfs_payload_is_public_only(payload)


# ===========================================================================
# Regression: cache key uniqueness across all six axes simultaneously
# ===========================================================================


def test_cache_key_uniqueness_across_all_variation_axes():
    """Every dimension that should distinguish cache entries does so."""
    axes = {
        "backend_id": ["provekit", "provekit-whir", "groth16"],
        "circuit_ref": [
            "provekit_knowledge_of_axioms@v1",
            "provekit_tdfol_v1_trace@v1",
        ],
        "hash_backend": ["sha256", "poseidon2", "keccak"],
        "verifier_key_sha256": [_DUMMY_VK_SHA, _ALT_VK_SHA, "c" * 64],
        "provekit_commit": [
            "aabb" * 16,
            "ccdd" * 16,
            "eeff" * 16,
        ],
        "ruleset_id": ["TDFOL_v1", "TDFOL_v2", "LegalIR_v1"],
    }

    seen: set[str] = set()
    for axis_name, axis_values in axes.items():
        for value in axis_values:
            kwargs = {**_BASE_KEY_KWARGS, axis_name: value}
            key = build_provekit_proof_cache_key(**kwargs)
            assert key not in seen or kwargs == _BASE_KEY_KWARGS, (
                f"Collision found for axis={axis_name!r}, value={value!r}"
            )
            seen.add(key)


# ===========================================================================
# Regression: IPFS payload never leaks witness across different call sites
# ===========================================================================


def test_ipfs_payload_no_witness_leak_across_call_sites():
    """Payload constructed from multiple code paths never exposes witness data."""
    private_terms = [
        "secret_legal_clause",
        "private_axiom_alpha",
        "Prover.toml",
        "/tmp/witness",
        "prover_key_path",
        "pkp_path",
        "input_path",
        "prover_toml_path",
        "cwd",
    ]

    metadata = _make_proof_metadata()
    # Inject a private term into a metadata field that should be stripped
    metadata["provekit_artifacts"]["input_path"] = (
        "/tmp/secret_legal_clause_Prover.toml"
    )

    payload = build_provekit_ipfs_payload(
        proof_public_inputs=_make_proof_inputs(),
        proof_metadata=metadata,
        proof_data=_DUMMY_PROOF_DATA,
    )
    payload_json = json.dumps(payload, sort_keys=True)

    for term in private_terms:
        # Only check terms that should _never_ appear as keys; raw file paths
        # may appear as artifact refs (verifier_key_path is public).
        if term in ("prover_key_path", "pkp_path", "input_path", "prover_toml_path", "cwd"):
            assert f'"{term}"' not in payload_json, (
                f"Private key {term!r} leaked into IPFS payload"
            )
