import json
import os
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from ipfs_datasets_py.logic.zkp.backends.groth16_ffi import Groth16Backend as Groth16FFIBackend


@pytest.fixture
def wire_vectors_path() -> Path:
    return Path(__file__).with_name("groth16_wire_vectors.json")


def _load_vectors(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    assert isinstance(data.get("version"), str)
    vectors = data.get("vectors")
    assert isinstance(vectors, dict)
    return vectors


@patch("subprocess.run")
def test_wire_vectors_allow_forward_compatible_witness_fields(mock_run, wire_vectors_path: Path):
    """Contract test: the Python wrapper must accept extra witness fields and keep stdin piping stable."""
    vectors = _load_vectors(wire_vectors_path)
    vector = vectors["modus_ponens_v1"]

    witness = vector["witness"]
    expected_public_inputs = vector["expected_public_inputs"]

    # Forward-compat witness fields (must not cause wrapper-side rejection)
    assert "security_level" in witness
    assert "some_future_field" in witness

    witness_json = json.dumps(witness)

    # Fixture invariant: ordering rules for CLI public_inputs list
    assert expected_public_inputs == [
        witness["theorem_hash_hex"],
        witness["axioms_commitment_hex"],
        str(witness["circuit_version"]),
        witness["ruleset_id"],
    ]

    # Simulate a successful Rust CLI response. The wrapper doesn't interpret the list,
    # but it must be able to decode JSON and return a Groth16Proof.
    proof_payload = {
        "proof_a": "[1,0]",
        "proof_b": "[[1,0],[0,1]]",
        "proof_c": "[1,0]",
        "public_inputs": expected_public_inputs,
        "timestamp": 0,
        "version": 1,
    }

    mock_run.return_value.returncode = 0
    mock_run.return_value.stdout = json.dumps(proof_payload).encode()
    mock_run.return_value.stderr = b""

    backend = Groth16FFIBackend(binary_path="/usr/bin/groth16")
    proof = backend.generate_proof(witness_json)

    assert proof.public_inputs["theorem"] == witness["theorem"]
    assert proof.public_inputs["theorem_hash"] == witness["theorem_hash_hex"]
    assert proof.public_inputs["axioms_commitment"] == witness["axioms_commitment_hex"]
    assert proof.public_inputs["circuit_version"] == witness["circuit_version"]
    assert proof.public_inputs["ruleset_id"] == witness["ruleset_id"]
    assert proof.metadata["security_level"] == witness["security_level"]
    assert proof.timestamp == 0

    # Contract: prove uses stdin/stdout JSON
    args, kwargs = mock_run.call_args
    assert args[0][:2] == ["/usr/bin/groth16", "prove"]
    assert "--input" in args[0] and "/dev/stdin" in args[0]
    assert "--output" in args[0] and "/dev/stdout" in args[0]
    assert kwargs.get("input") == witness_json.encode()
    assert kwargs.get("capture_output") is True


@pytest.mark.skipif(
    os.environ.get("IPFS_DATASETS_ENABLE_GROTH16", "").strip() not in {"1", "true", "TRUE", "yes", "YES"},
    reason="Groth16 backend is opt-in",
)
def test_groth16_cli_public_inputs_order_matches_vectors(wire_vectors_path: Path, monkeypatch):
    """End-to-end contract: Rust CLI emits `public_inputs` in the expected order."""
    vectors = _load_vectors(wire_vectors_path)
    vector = vectors["modus_ponens_v1"]
    witness = vector["witness"]
    expected_public_inputs = vector["expected_public_inputs"]

    # Ensure deterministic mode for stable assertions (if supported by binary).
    monkeypatch.setenv("GROTH16_BACKEND_DETERMINISTIC", "1")

    backend = Groth16FFIBackend(binary_path=None)
    if not backend.binary_path:
        pytest.skip("Groth16 binary not available")

    result = subprocess.run(
        [backend.binary_path, "prove", "--input", "/dev/stdin", "--output", "/dev/stdout"],
        input=json.dumps(witness).encode(),
        capture_output=True,
        timeout=60,
    )

    assert result.returncode == 0, result.stderr.decode(errors="replace")
    payload = json.loads(result.stdout.decode())
    assert isinstance(payload, dict)
    assert payload.get("public_inputs") == expected_public_inputs

    if "timestamp" in payload:
        assert payload["timestamp"] == 0


@pytest.mark.skipif(
    os.environ.get("IPFS_DATASETS_ENABLE_GROTH16", "").strip() not in {"1", "true", "TRUE", "yes", "YES"},
    reason="Groth16 backend is opt-in",
)
def test_groth16_wire_vectors_file_is_valid_json(wire_vectors_path: Path):
    _load_vectors(wire_vectors_path)
