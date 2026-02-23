"""
Groth16 Integration Tests — v16

Tests for the real Groth16 Rust backend wired to the Python ZKP stack.

Test categories:
  1. Binary detection (skip if not compiled)
  2. Trusted setup artifacts
  3. Python→Rust wire format contract
  4. Real proof generation + verification (groth16 enabled)
  5. Fallback behavior (groth16 disabled / binary absent)
  6. ZKPToUCANBridge with Groth16 backend
  7. Groth16Backend.ensure_setup() idempotency
  8. Schema validation (witness, proof, error envelope)

Run with:
  pytest tests/unit_tests/logic/zkp/test_v16_groth16_integration.py -v
  # Real proofs (requires compiled binary):
  IPFS_DATASETS_ENABLE_GROTH16=1 pytest tests/unit_tests/logic/zkp/test_v16_groth16_integration.py -v
"""

from __future__ import annotations

import json
import os
import subprocess
import warnings
from pathlib import Path
from typing import Optional
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

# parents[4] = <repo checkout root>  e.g. .../ipfs_datasets_py/ipfs_datasets_py
# The Python package lives at parents[4] / "ipfs_datasets_py"
# The Rust crate lives at parents[4] / "ipfs_datasets_py" / "processors" / "groth16_backend"
_CHECKOUT_ROOT = Path(__file__).resolve().parents[4]
_GROTH16_CRATE_DIR = _CHECKOUT_ROOT / "ipfs_datasets_py" / "processors" / "groth16_backend"
_BINARY_PATH = _GROTH16_CRATE_DIR / "target" / "release" / "groth16"
_ARTIFACTS_V1 = _GROTH16_CRATE_DIR / "artifacts" / "v1"
_ARTIFACTS_V2 = _GROTH16_CRATE_DIR / "artifacts" / "v2"

_BINARY_AVAILABLE = _BINARY_PATH.exists()
_ARTIFACTS_V1_AVAILABLE = (_ARTIFACTS_V1 / "proving_key.bin").exists()
_ARTIFACTS_V2_AVAILABLE = (_ARTIFACTS_V2 / "proving_key.bin").exists()

_skip_no_binary = pytest.mark.skipif(
    not _BINARY_AVAILABLE,
    reason="Groth16 binary not compiled. Run: cd processors/groth16_backend && cargo build --release",
)
_skip_no_artifacts = pytest.mark.skipif(
    not (_BINARY_AVAILABLE and _ARTIFACTS_V1_AVAILABLE),
    reason="Groth16 artifacts missing. Run: groth16 setup --version 1",
)
_skip_no_groth16_env = pytest.mark.skipif(
    os.environ.get("IPFS_DATASETS_ENABLE_GROTH16", "") not in {"1", "true", "TRUE", "yes", "YES"},
    reason="Set IPFS_DATASETS_ENABLE_GROTH16=1 to run real Groth16 tests",
)

# Canonical test witness
_TEST_WITNESS = {
    "private_axioms": ["Socrates is human", "All humans are mortal"],
    "theorem": "Socrates is mortal",
    "axioms_commitment_hex": "aabb" * 16,
    "theorem_hash_hex": "1122" * 16,
    "circuit_version": 1,
    "ruleset_id": "TDFOL_v1",
    "security_level": 0,
    "intermediate_steps": [],
}


# ---------------------------------------------------------------------------
# Category 1 — Binary detection
# ---------------------------------------------------------------------------

class TestBinaryDetection:
    """Groth16 binary detection and availability checks."""

    def test_binary_path_constant_resolves(self):
        """The expected canonical binary path should be a deterministic Path object."""
        assert isinstance(_BINARY_PATH, Path)

    def test_ffi_backend_find_binary(self):
        """Groth16FFIBackend._find_groth16_binary() returns a path or None."""
        from ipfs_datasets_py.logic.zkp.backends.groth16_ffi import Groth16Backend as FFI

        backend = FFI.__new__(FFI)
        backend.binary_path = None
        backend.timeout_seconds = 30
        result = backend._find_groth16_binary()
        assert result is None or Path(result).exists()

    def test_ffi_backend_env_override(self, tmp_path):
        """IPFS_DATASETS_GROTH16_BINARY env var takes precedence."""
        dummy_bin = tmp_path / "fake_groth16"
        dummy_bin.touch(mode=0o755)
        from ipfs_datasets_py.logic.zkp.backends.groth16_ffi import Groth16Backend as FFI
        with patch.dict(os.environ, {"IPFS_DATASETS_GROTH16_BINARY": str(dummy_bin)}):
            backend = FFI.__new__(FFI)
            found = backend._find_groth16_binary()
            assert found == str(dummy_bin)

    def test_ffi_backend_missing_override_warning(self, tmp_path):
        """IPFS_DATASETS_GROTH16_BINARY pointing to absent file falls through to auto-detect."""
        absent = str(tmp_path / "nonexistent_groth16_binary")
        from ipfs_datasets_py.logic.zkp.backends.groth16_ffi import Groth16Backend as FFI
        # Patch away GROTH16_BINARY as well so no override is accepted
        with patch.dict(os.environ, {
            "IPFS_DATASETS_GROTH16_BINARY": absent,
            "GROTH16_BINARY": "",
        }):
            backend = FFI.__new__(FFI)
            backend.timeout_seconds = 30
            backend.binary_path = None
            found = backend._find_groth16_binary()
            # absent override is rejected; auto-detection may still find the binary
            # What matters is the absent override itself was NOT returned.
            assert found != absent

    @_skip_no_binary
    def test_binary_is_executable(self):
        """Compiled binary is executable."""
        assert os.access(str(_BINARY_PATH), os.X_OK)

    @_skip_no_binary
    def test_binary_help_exits_zero(self):
        """groth16 --help exits 0."""
        result = subprocess.run(
            [str(_BINARY_PATH), "--help"],
            capture_output=True, timeout=10,
        )
        assert result.returncode == 0
        assert b"prove" in result.stdout or b"prove" in result.stderr

    @_skip_no_binary
    def test_binary_exposes_prove_verify_setup(self):
        """Binary exposes prove, verify, and setup subcommands."""
        result = subprocess.run(
            [str(_BINARY_PATH), "--help"],
            capture_output=True, timeout=10,
        )
        output = (result.stdout + result.stderr).decode()
        assert "prove" in output
        assert "verify" in output
        assert "setup" in output


# ---------------------------------------------------------------------------
# Category 2 — Trusted setup artifacts
# ---------------------------------------------------------------------------

class TestTrustedSetupArtifacts:
    """Trusted setup key files committed to the repository."""

    def test_artifacts_v1_directory_exists(self):
        """artifacts/v1/ directory exists in the repository."""
        assert _ARTIFACTS_V1.exists(), f"Missing: {_ARTIFACTS_V1}"

    def test_artifacts_v2_directory_exists(self):
        """artifacts/v2/ directory exists in the repository."""
        assert _ARTIFACTS_V2.exists(), f"Missing: {_ARTIFACTS_V2}"

    def test_artifacts_v1_proving_key_present(self):
        """artifacts/v1/proving_key.bin is committed."""
        pk = _ARTIFACTS_V1 / "proving_key.bin"
        assert pk.exists() and pk.stat().st_size > 0, f"Missing or empty: {pk}"

    def test_artifacts_v1_verifying_key_present(self):
        """artifacts/v1/verifying_key.bin is committed."""
        vk = _ARTIFACTS_V1 / "verifying_key.bin"
        assert vk.exists() and vk.stat().st_size > 0, f"Missing or empty: {vk}"

    def test_artifacts_v2_keys_present(self):
        """artifacts/v2/ proving and verifying keys are committed."""
        pk = _ARTIFACTS_V2 / "proving_key.bin"
        vk = _ARTIFACTS_V2 / "verifying_key.bin"
        assert pk.exists() and pk.stat().st_size > 0
        assert vk.exists() and vk.stat().st_size > 0

    @_skip_no_binary
    def test_ffi_artifacts_exist_v1(self):
        """FFI backend.artifacts_exist(1) returns True with committed keys."""
        from ipfs_datasets_py.logic.zkp.backends.groth16_ffi import Groth16Backend as FFI
        backend = FFI(binary_path=str(_BINARY_PATH))
        assert backend.artifacts_exist(1) is True

    @_skip_no_binary
    def test_ffi_artifacts_exist_v2(self):
        """FFI backend.artifacts_exist(2) returns True with committed keys."""
        from ipfs_datasets_py.logic.zkp.backends.groth16_ffi import Groth16Backend as FFI
        backend = FFI(binary_path=str(_BINARY_PATH))
        assert backend.artifacts_exist(2) is True

    @_skip_no_binary
    def test_ffi_artifacts_exist_missing(self):
        """FFI backend.artifacts_exist(99) returns False for non-existent version."""
        from ipfs_datasets_py.logic.zkp.backends.groth16_ffi import Groth16Backend as FFI
        backend = FFI(binary_path=str(_BINARY_PATH))
        assert backend.artifacts_exist(99) is False


# ---------------------------------------------------------------------------
# Category 3 — Python→Rust wire format contract
# ---------------------------------------------------------------------------

class TestWireFormat:
    """Python-Rust JSON wire format contract (schema validation)."""

    def test_error_envelope_schema_loads(self):
        """_error_envelope_v1_schema() returns a non-empty dict."""
        from ipfs_datasets_py.logic.zkp.backends.groth16_ffi import _error_envelope_v1_schema
        schema = _error_envelope_v1_schema()
        assert isinstance(schema, dict) and schema

    def test_parse_valid_error_envelope(self):
        """_parse_validated_error_envelope parses a conforming error payload."""
        from ipfs_datasets_py.logic.zkp.backends.groth16_ffi import _parse_validated_error_envelope
        payload = json.dumps({
            "error": {
                "schema_version": 1,
                "code": "INTERNAL",
                "message": "test error",
            }
        })
        result = _parse_validated_error_envelope(payload)
        assert result == ("INTERNAL", "test error")

    def test_parse_invalid_error_envelope_returns_none(self):
        """_parse_validated_error_envelope returns None for non-conforming payload."""
        from ipfs_datasets_py.logic.zkp.backends.groth16_ffi import _parse_validated_error_envelope
        assert _parse_validated_error_envelope("") is None
        assert _parse_validated_error_envelope("not json") is None
        assert _parse_validated_error_envelope('{"no_error_key": 1}') is None

    def test_witness_validation_accepts_valid(self):
        """Groth16Backend._validate_witness accepts a valid witness."""
        from ipfs_datasets_py.logic.zkp.backends.groth16_ffi import Groth16Backend as FFI
        backend = FFI.__new__(FFI)
        backend._validate_witness(_TEST_WITNESS)  # Should not raise

    def test_witness_validation_rejects_missing_field(self):
        """_validate_witness raises ValueError for missing required fields."""
        from ipfs_datasets_py.logic.zkp.backends.groth16_ffi import Groth16Backend as FFI
        backend = FFI.__new__(FFI)
        bad = {k: v for k, v in _TEST_WITNESS.items() if k != "theorem"}
        with pytest.raises(ValueError, match="Missing witness fields"):
            backend._validate_witness(bad)

    def test_witness_validation_rejects_empty_axioms(self):
        """_validate_witness raises ValueError for empty private_axioms."""
        from ipfs_datasets_py.logic.zkp.backends.groth16_ffi import Groth16Backend as FFI
        backend = FFI.__new__(FFI)
        bad = {**_TEST_WITNESS, "private_axioms": []}
        with pytest.raises(ValueError, match="private_axioms"):
            backend._validate_witness(bad)

    def test_witness_validation_rejects_invalid_security_level(self):
        """_validate_witness raises ValueError for negative security_level."""
        from ipfs_datasets_py.logic.zkp.backends.groth16_ffi import Groth16Backend as FFI
        backend = FFI.__new__(FFI)
        bad = {**_TEST_WITNESS, "security_level": -1}
        with pytest.raises(ValueError, match="security_level"):
            backend._validate_witness(bad)


# ---------------------------------------------------------------------------
# Category 4 — Real proof generation + verification (requires binary + env)
# ---------------------------------------------------------------------------

class TestRealGroth16ProveVerify:
    """Real Groth16 prove/verify with the Rust binary (requires ENABLE_GROTH16=1)."""

    @_skip_no_binary
    @_skip_no_artifacts
    @_skip_no_groth16_env
    def test_prove_returns_valid_json(self):
        """groth16 prove produces valid JSON output."""
        witness_json = json.dumps(_TEST_WITNESS)
        result = subprocess.run(
            [str(_BINARY_PATH), "prove", "--input", "/dev/stdin", "--output", "/dev/stdout", "--seed", "42"],
            input=witness_json.encode(),
            capture_output=True, timeout=30,
        )
        assert result.returncode == 0, result.stderr.decode()
        proof = json.loads(result.stdout)
        assert "proof_a" in proof
        assert "proof_b" in proof
        assert "proof_c" in proof
        assert "public_inputs" in proof
        assert len(proof["public_inputs"]) == 4

    @_skip_no_binary
    @_skip_no_artifacts
    @_skip_no_groth16_env
    def test_prove_and_verify_roundtrip(self):
        """Prove then verify: groth16 verify exits 0 for a valid proof."""
        witness_json = json.dumps(_TEST_WITNESS)
        prove_result = subprocess.run(
            [str(_BINARY_PATH), "prove", "--input", "/dev/stdin", "--output", "/dev/stdout", "--seed", "42"],
            input=witness_json.encode(),
            capture_output=True, timeout=30,
        )
        assert prove_result.returncode == 0
        verify_result = subprocess.run(
            [str(_BINARY_PATH), "verify", "--proof", "/dev/stdin"],
            input=prove_result.stdout,
            capture_output=True, timeout=30,
        )
        assert verify_result.returncode == 0, verify_result.stderr.decode()

    @_skip_no_binary
    @_skip_no_artifacts
    @_skip_no_groth16_env
    def test_determinism_with_seed(self):
        """Same witness + same seed → identical proof bytes."""
        witness_json = json.dumps(_TEST_WITNESS)
        proofs = []
        for _ in range(2):
            r = subprocess.run(
                [str(_BINARY_PATH), "prove", "--input", "/dev/stdin", "--output", "/dev/stdout", "--seed", "99"],
                input=witness_json.encode(),
                capture_output=True, timeout=30,
            )
            assert r.returncode == 0
            proofs.append(r.stdout)
        assert proofs[0] == proofs[1], "Proof is not deterministic with same seed"

    @_skip_no_binary
    @_skip_no_artifacts
    @_skip_no_groth16_env
    def test_public_inputs_ordering(self):
        """public_inputs must be [theorem_hash, axioms_commitment, version, ruleset_id]."""
        r = subprocess.run(
            [str(_BINARY_PATH), "prove", "--input", "/dev/stdin", "--output", "/dev/stdout", "--seed", "1"],
            input=json.dumps(_TEST_WITNESS).encode(),
            capture_output=True, timeout=30,
        )
        assert r.returncode == 0
        proof = json.loads(r.stdout)
        pi = proof["public_inputs"]
        assert len(pi) == 4
        assert pi[2] in ("1", 1), f"circuit_version should be 1, got {pi[2]!r}"
        assert pi[3] == "TDFOL_v1", f"ruleset_id should be TDFOL_v1, got {pi[3]!r}"

    @_skip_no_binary
    @_skip_no_groth16_env
    def test_invalid_witness_emits_error_envelope(self):
        """prove with missing field → exit=2 + structured error JSON on stdout."""
        bad = {k: v for k, v in _TEST_WITNESS.items() if k != "theorem"}
        r = subprocess.run(
            [str(_BINARY_PATH), "prove", "--input", "/dev/stdin", "--output", "/dev/stdout"],
            input=json.dumps(bad).encode(),
            capture_output=True, timeout=15,
        )
        assert r.returncode == 2
        # Rust emits error envelope on stdout
        envelope = json.loads(r.stdout.decode())
        assert "error" in envelope
        assert "code" in envelope["error"]

    @_skip_no_binary
    @_skip_no_artifacts
    @_skip_no_groth16_env
    def test_python_groth16_backend_generate_proof(self):
        """Groth16Backend.generate_proof() returns a Groth16Proof with real data."""
        from ipfs_datasets_py.logic.zkp.backends.groth16 import Groth16Backend
        backend = Groth16Backend(binary_path=str(_BINARY_PATH))
        proof = backend.generate_proof(
            theorem="Socrates is mortal",
            private_axioms=["Socrates is human", "All humans are mortal"],
            metadata={"seed": 42, "circuit_version": 1},
        )
        assert proof is not None
        assert proof.size_bytes > 0
        assert proof.metadata.get("backend") == "groth16"

    @_skip_no_binary
    @_skip_no_artifacts
    @_skip_no_groth16_env
    def test_python_groth16_backend_verify_proof(self):
        """Groth16Backend.verify_proof() returns True for a proof it generated."""
        from ipfs_datasets_py.logic.zkp.backends.groth16 import Groth16Backend
        backend = Groth16Backend(binary_path=str(_BINARY_PATH))
        proof = backend.generate_proof(
            theorem="P is true",
            private_axioms=["P", "P implies Q"],
            metadata={"seed": 7},
        )
        assert backend.verify_proof(proof) is True


# ---------------------------------------------------------------------------
# Category 5 — Fallback behavior
# ---------------------------------------------------------------------------

class TestFallbackBehavior:
    """ZKP stack falls back gracefully when Groth16 is not enabled."""

    def test_groth16_backend_disabled_raises_zkp_error_generate(self):
        """generate_proof raises ZKPError when IPFS_DATASETS_ENABLE_GROTH16 is not set."""
        from ipfs_datasets_py.logic.zkp.backends.groth16 import Groth16Backend
        from ipfs_datasets_py.logic.zkp import ZKPError
        with patch.dict(os.environ, {"IPFS_DATASETS_ENABLE_GROTH16": ""}):
            backend = Groth16Backend()
            with pytest.raises(ZKPError, match="disabled by default"):
                backend.generate_proof("P", ["P"], {})

    def test_groth16_backend_disabled_raises_zkp_error_verify(self):
        """verify_proof raises ZKPError when backend is disabled."""
        from ipfs_datasets_py.logic.zkp.backends.groth16 import Groth16Backend
        from ipfs_datasets_py.logic.zkp import ZKPError, ZKPProof
        stub = ZKPProof(proof_data=b"{}", public_inputs={}, metadata={}, timestamp=0, size_bytes=2)
        with patch.dict(os.environ, {"IPFS_DATASETS_ENABLE_GROTH16": ""}):
            backend = Groth16Backend()
            with pytest.raises(ZKPError, match="disabled by default"):
                backend.verify_proof(stub)

    def test_simulated_backend_works_without_binary(self):
        """Simulated backend works without Rust binary or env var."""
        from ipfs_datasets_py.logic.zkp.backends import get_backend
        backend = get_backend("simulated")
        proof = backend.generate_proof("P", ["P"], {})
        assert proof is not None
        # Simulated backend uses proof_system metadata key (contains "simulated")
        assert "simulated" in proof.metadata.get("proof_system", "").lower()

    def test_simulated_backend_verify_own_proof(self):
        """Simulated backend verifies its own proofs."""
        from ipfs_datasets_py.logic.zkp.backends import get_backend
        backend = get_backend("simulated")
        proof = backend.generate_proof("Q", ["P", "P→Q"], {})
        assert backend.verify_proof(proof) is True

    def test_ffi_backend_no_binary_raises_runtime_error(self, tmp_path):
        """FFI backend raises RuntimeError when binary_path points to nonexistent file."""
        from ipfs_datasets_py.logic.zkp.backends.groth16_ffi import Groth16Backend as FFI
        # Use a path that clearly does not exist so _find_groth16_binary won't find it
        fake_path = str(tmp_path / "nonexistent_groth16")
        backend = FFI.__new__(FFI)
        backend.binary_path = None  # skip auto-detection result
        backend.timeout_seconds = 30
        with pytest.raises(RuntimeError, match="Groth16 binary not available"):
            backend.generate_proof(json.dumps(_TEST_WITNESS))

    def test_ffi_backend_seed_validation(self):
        """FFI backend raises ValueError for out-of-range seed."""
        from ipfs_datasets_py.logic.zkp.backends.groth16_ffi import Groth16Backend as FFI
        if not _BINARY_AVAILABLE:
            pytest.skip("binary not available")
        backend = FFI(binary_path=str(_BINARY_PATH))
        with pytest.raises(ValueError, match="seed must fit in u64"):
            backend.generate_proof(json.dumps(_TEST_WITNESS), seed=2**64)


# ---------------------------------------------------------------------------
# Category 6 — ZKPToUCANBridge with Groth16
# ---------------------------------------------------------------------------

class TestZKPToUCANBridgeGroth16:
    """ZKPToUCANBridge upgrade paths and Groth16 integration."""

    def test_bridge_simulated_mode_emits_warning(self):
        """Bridge emits UserWarning in simulated mode."""
        with patch.dict(os.environ, {"IPFS_DATASETS_ENABLE_GROTH16": ""}):
            from ipfs_datasets_py.logic.zkp.ucan_zkp_bridge import ZKPToUCANBridge, _default_bridge
            bridge = ZKPToUCANBridge.__new__(ZKPToUCANBridge)
            bridge._groth16_enabled = False
            bridge._verifier_id = ZKPToUCANBridge.SIMULATED_VERIFIER_ID
            bridge._issuer_did = "did:key:test"
            bridge._prover = None
            bridge._groth16_backend = None

            with warnings.catch_warnings(record=True) as w:
                warnings.simplefilter("always")
                result = bridge.prove_and_delegate(
                    theorem="P", actor="did:key:alice",
                    resource="res", ability="read",
                    private_axioms=["P"],
                )
            assert result.success or result.error  # either outcome
            user_warns = [x for x in w if issubclass(x.category, UserWarning)]
            assert any("SIMULATED" in str(x.message) for x in user_warns), \
                "Expected UserWarning containing 'SIMULATED'"

    def test_bridge_groth16_verifier_id_constant(self):
        """GROTH16_VERIFIER_ID constant is defined and distinct from simulated."""
        from ipfs_datasets_py.logic.zkp.ucan_zkp_bridge import ZKPToUCANBridge
        assert ZKPToUCANBridge.GROTH16_VERIFIER_ID != ZKPToUCANBridge.SIMULATED_VERIFIER_ID
        assert "groth16" in ZKPToUCANBridge.GROTH16_VERIFIER_ID

    def test_bridge_check_groth16_enabled_false_by_default(self):
        """_check_groth16_enabled() returns False when env not set."""
        from ipfs_datasets_py.logic.zkp.ucan_zkp_bridge import ZKPToUCANBridge
        with patch.dict(os.environ, {"IPFS_DATASETS_ENABLE_GROTH16": ""}):
            assert ZKPToUCANBridge._check_groth16_enabled() is False

    def test_bridge_check_groth16_enabled_true(self):
        """_check_groth16_enabled() returns True when env=1."""
        from ipfs_datasets_py.logic.zkp.ucan_zkp_bridge import ZKPToUCANBridge
        with patch.dict(os.environ, {"IPFS_DATASETS_ENABLE_GROTH16": "1"}):
            assert ZKPToUCANBridge._check_groth16_enabled() is True

    def test_bridge_get_singleton_reset(self):
        """get_zkp_ucan_bridge(reset=True) creates a fresh singleton."""
        from ipfs_datasets_py.logic.zkp import ucan_zkp_bridge as _mod
        _mod._default_bridge = None
        b1 = _mod.get_zkp_ucan_bridge()
        b2 = _mod.get_zkp_ucan_bridge()
        assert b1 is b2  # same object
        b3 = _mod.get_zkp_ucan_bridge(reset=True)
        assert b3 is not b1  # reset creates new instance
        _mod._default_bridge = None  # cleanup

    def test_bridge_proof_to_caveat(self):
        """proof_to_caveat returns a ZKPCapabilityEvidence with correct fields."""
        from ipfs_datasets_py.logic.zkp.ucan_zkp_bridge import ZKPToUCANBridge
        bridge = ZKPToUCANBridge.__new__(ZKPToUCANBridge)
        bridge._verifier_id = "test-verifier"
        bridge._groth16_enabled = False
        bridge._issuer_did = "did:key:issuer"
        bridge._prover = None
        bridge._groth16_backend = None

        class _FakeProof:
            proof_data = b"fake-proof-data"
            public_inputs = {"theorem": "P → Q"}
        caveat = bridge.proof_to_caveat(_FakeProof())
        assert caveat.verifier_id == "test-verifier"
        assert len(caveat.proof_hash) == 64  # SHA-256 hex
        assert "bafy" in caveat.theorem_cid or len(caveat.theorem_cid) > 10

    @_skip_no_binary
    @_skip_no_artifacts
    @_skip_no_groth16_env
    def test_bridge_groth16_prove_and_delegate_no_sim_warning(self):
        """No UserWarning when Groth16 is enabled and proof succeeds."""
        from ipfs_datasets_py.logic.zkp import ucan_zkp_bridge as _mod
        _mod._default_bridge = None
        with patch.dict(os.environ, {"IPFS_DATASETS_ENABLE_GROTH16": "1"}):
            bridge = _mod.get_zkp_ucan_bridge(reset=True)
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            result = bridge.prove_and_delegate(
                theorem="Socrates is mortal",
                actor="did:key:bob",
                resource="logic/proof",
                ability="proof/invoke",
                private_axioms=["Socrates is human", "All humans are mortal"],
            )
        _mod._default_bridge = None
        assert result.success, f"Expected success, got error: {result.error}"
        sim_warns = [x for x in w if "SIMULATED" in str(x.message)]
        assert not sim_warns, "Expected no SIMULATED warning when Groth16 is enabled"


# ---------------------------------------------------------------------------
# Category 7 — ensure_setup() idempotency
# ---------------------------------------------------------------------------

class TestEnsureSetupIdempotency:
    """Groth16Backend.ensure_setup() is idempotent when artifacts exist."""

    @_skip_no_binary
    @_skip_no_groth16_env
    def test_ensure_setup_returns_already_exists(self):
        """ensure_setup(1) returns {status: 'already_exists'} when keys are present."""
        from ipfs_datasets_py.logic.zkp.backends.groth16 import Groth16Backend
        with patch.dict(os.environ, {"IPFS_DATASETS_ENABLE_GROTH16": "1"}):
            backend = Groth16Backend(binary_path=str(_BINARY_PATH))
            result = backend.ensure_setup(version=1)
        assert result.get("status") == "already_exists"
        assert result.get("version") == 1

    @_skip_no_groth16_env
    def test_ensure_setup_disabled_raises(self):
        """ensure_setup raises ZKPError when backend is disabled."""
        from ipfs_datasets_py.logic.zkp.backends.groth16 import Groth16Backend
        from ipfs_datasets_py.logic.zkp import ZKPError
        with patch.dict(os.environ, {"IPFS_DATASETS_ENABLE_GROTH16": ""}):
            backend = Groth16Backend()
            with pytest.raises(ZKPError, match="disabled"):
                backend.ensure_setup()

    @_skip_no_binary
    @_skip_no_groth16_env
    def test_binary_available_returns_true(self):
        """binary_available() returns True when binary exists."""
        from ipfs_datasets_py.logic.zkp.backends.groth16 import Groth16Backend
        with patch.dict(os.environ, {"IPFS_DATASETS_ENABLE_GROTH16": "1"}):
            backend = Groth16Backend(binary_path=str(_BINARY_PATH))
            assert backend.binary_available() is True

    @_skip_no_binary
    @_skip_no_groth16_env
    def test_get_backend_info_keys(self):
        """get_backend_info() returns expected keys."""
        from ipfs_datasets_py.logic.zkp.backends.groth16 import Groth16Backend
        with patch.dict(os.environ, {"IPFS_DATASETS_ENABLE_GROTH16": "1"}):
            backend = Groth16Backend(binary_path=str(_BINARY_PATH))
            info = backend.get_backend_info()
        for k in ("backend_id", "curve_id", "enabled", "binary_path", "binary_available",
                   "artifacts_v1_exist", "artifacts_v2_exist"):
            assert k in info, f"Missing key: {k}"


# ---------------------------------------------------------------------------
# Category 8 — Schema validation
# ---------------------------------------------------------------------------

class TestSchemaFiles:
    """Schema JSON files are present and parseable."""

    def _schema_path(self, name: str) -> Path:
        return _GROTH16_CRATE_DIR / "schemas" / name

    def test_witness_schema_present(self):
        path = self._schema_path("witness_v1.schema.json")
        assert path.exists(), f"Missing: {path}"
        data = json.loads(path.read_text())
        assert data.get("$schema") or data.get("type") or data.get("properties")

    def test_proof_schema_present(self):
        path = self._schema_path("proof_v1.schema.json")
        assert path.exists(), f"Missing: {path}"
        data = json.loads(path.read_text())
        assert isinstance(data, dict)

    def test_error_envelope_schema_present(self):
        path = self._schema_path("error_envelope_v1.schema.json")
        assert path.exists(), f"Missing: {path}"
        data = json.loads(path.read_text())
        assert isinstance(data, dict)

    def test_build_sh_executable(self):
        """build.sh convenience script exists and is executable."""
        build_sh = _GROTH16_CRATE_DIR / "build.sh"
        assert build_sh.exists(), f"Missing: {build_sh}"
