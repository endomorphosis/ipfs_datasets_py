import json
import time
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.zkp import ZKPError, ZKPProof
from ipfs_datasets_py.logic.zkp.backends.provekit import ProveKitBackend
from ipfs_datasets_py.logic.zkp.circuits import (
    attestation_view_matches_proof,
    complete_zkp_attestation_record,
    decode_simulated_proof_layout,
    zkp_attestation_legal_ir_view_loss,
)


def _fake_provekit_cli(path: Path, *, write_proof: bool = True) -> Path:
    script = f"""#!/usr/bin/env python3
import pathlib
import sys

cmd = sys.argv[1] if len(sys.argv) > 1 else ""
if cmd == "prove":
    if {str(write_proof)!r} == "True":
        out = pathlib.Path(sys.argv[sys.argv.index("--out") + 1])
        out.write_bytes(b"NP" + b"x" * 198)
    print("fake prove ok")
    raise SystemExit(0)
if cmd == "verify":
    print("fake verify ok")
    raise SystemExit(0)
raise SystemExit(2)
"""
    path.write_text(script, encoding="utf-8")
    path.chmod(path.stat().st_mode | 0o111)
    return path


def _artifact_metadata(tmp_path: Path) -> dict:
    pkp = tmp_path / "circuit.pkp"
    pkv = tmp_path / "circuit.pkv"
    prover_toml = tmp_path / "Prover.toml"
    proof_path = tmp_path / "proof.np"
    pkp.write_bytes(b"pkp")
    pkv.write_bytes(b"pkv")
    prover_toml.write_text('theorem_hash_field = "1"\n', encoding="utf-8")
    return {
        "security_level": 128,
        "provekit_artifacts": {
            "program_dir": str(tmp_path),
            "prover_key_path": str(pkp),
            "verifier_key_path": str(pkv),
            "input_path": str(prover_toml),
            "proof_path": str(proof_path),
        },
    }


def test_backend_returns_zkpproof_envelope_with_attestation(tmp_path):
    binary = _fake_provekit_cli(tmp_path / "provekit-cli")
    backend = ProveKitBackend(binary_path=str(binary))
    metadata = _artifact_metadata(tmp_path)
    started = time.time()

    proof = backend.generate_proof(
        theorem="Q",
        private_axioms=["private axiom", "private axiom -> Q"],
        metadata=metadata,
    )

    assert isinstance(proof, ZKPProof)
    assert proof.proof_data == b"NP" + b"x" * 198
    assert proof.size_bytes == len(proof.proof_data)
    assert proof.timestamp >= started
    assert proof.public_inputs["theorem"] == "Q"
    assert proof.public_inputs["circuit_ref"] == "provekit_knowledge_of_axioms@v1"
    assert proof.metadata["backend"] == "provekit"
    assert proof.metadata["proof_system"] == "ProveKit-WHIR"
    assert proof.metadata["curve_id"] == "bn254"
    assert proof.metadata["provekit"]["command"]["ok"] is True
    assert proof.metadata["provekit"]["public_input_schema"] == "provekit-public-inputs-v1"

    assert proof.public_inputs["attestation_ref"]
    assert proof.public_inputs["attestation_view_version"] == 1
    assert proof.metadata["attestation_view"]["attestation_ref"] == proof.public_inputs["attestation_ref"]
    assert attestation_view_matches_proof(
        proof_data=proof.proof_data,
        public_inputs=proof.public_inputs,
        metadata=proof.metadata,
    )


def test_backend_envelope_does_not_leak_private_axiom_text(tmp_path):
    binary = _fake_provekit_cli(tmp_path / "provekit-cli")
    backend = ProveKitBackend(binary_path=str(binary))

    proof = backend.generate_proof(
        theorem="Q",
        private_axioms=["secret legal axiom", "secret legal axiom -> Q"],
        metadata=_artifact_metadata(tmp_path),
    )

    payload = json.dumps(proof.to_dict(), sort_keys=True)
    assert "secret legal axiom" not in payload


def test_backend_verify_uses_envelope_artifacts(tmp_path):
    binary = _fake_provekit_cli(tmp_path / "provekit-cli")
    backend = ProveKitBackend(binary_path=str(binary))
    proof = backend.generate_proof(
        theorem="Q",
        private_axioms=["P", "P -> Q"],
        metadata=_artifact_metadata(tmp_path),
    )

    assert backend.verify_proof(proof) is True


def test_attestation_check_rejects_stale_proof_bytes(tmp_path):
    binary = _fake_provekit_cli(tmp_path / "provekit-cli")
    backend = ProveKitBackend(binary_path=str(binary))
    proof = backend.generate_proof(
        theorem="Q",
        private_axioms=["P", "P -> Q"],
        metadata=_artifact_metadata(tmp_path),
    )

    assert not attestation_view_matches_proof(
        proof_data=b"changed proof bytes",
        public_inputs=proof.public_inputs,
        metadata=proof.metadata,
    )


def test_simulated_proof_layout_decodes_serialized_hex():
    from ipfs_datasets_py.logic.zkp import ZKPProver

    proof = ZKPProver().generate_proof(
        theorem="Q",
        private_axioms=["P", "P -> Q"],
        metadata={"security_level": 128},
    )
    proof_dict = proof.to_dict()

    layout = decode_simulated_proof_layout(proof_dict["proof_data"])

    assert layout["valid"] is True
    assert layout["format"] == "SIMZKP/1"


def test_sparse_legal_ir_record_is_completed_from_nested_proof():
    from ipfs_datasets_py.logic.zkp import ZKPProver

    proof = ZKPProver().generate_proof(
        theorem="Q",
        private_axioms=["P", "P -> Q"],
        metadata={"security_level": 128},
    )
    sparse_record = {
        "proof": proof.to_dict(),
        "form_id": "us-code-33-701e-19ea9c3021f51521",
    }

    completed = complete_zkp_attestation_record(sparse_record)

    assert completed["attestation_ref"] == proof.public_inputs["attestation_ref"]
    assert completed["attestation_view"]["attestation_ref"] == completed["attestation_ref"]
    assert completed["public_inputs"]["attestation_ref"] == completed["attestation_ref"]
    assert completed["proof_hash"]
    assert completed["source_id"] == "us-code-33-701e-19ea9c3021f51521"
    assert zkp_attestation_legal_ir_view_loss([sparse_record]) == 0.0


def test_flattened_record_replaces_empty_duplicated_attestation_fields():
    from ipfs_datasets_py.logic.zkp import ZKPProver

    proof = ZKPProver().generate_proof(
        theorem="Q",
        private_axioms=["P", "P -> Q"],
        metadata={
            "circuit_ref": "legal_ir_zkp_attestation@v1",
            "circuit_version": 1,
            "ruleset_id": "LegalIR_TDFOL_v1",
        },
    )
    proof_dict = proof.to_dict()
    flattened_record = {
        "attestation_ref": "",
        "attestation_view_version": 0,
        "proof_data": proof_dict["proof_data"],
        "proof_hash": "",
        "public_inputs": {
            key: value
            for key, value in proof_dict["public_inputs"].items()
            if not key.startswith("attestation_")
        },
        "metadata": proof_dict["metadata"],
        "sample_id": "us-code-42-18726.-3ff52550e83c51a1",
    }

    completed = complete_zkp_attestation_record(flattened_record)

    assert completed["attestation_ref"] == proof.public_inputs["attestation_ref"]
    assert completed["attestation_view_version"] == 1
    assert completed["public_inputs"]["attestation_ref"] == completed["attestation_ref"]
    assert completed["proof_hash"] == proof.metadata["attestation_view"]["proof_digest"]
    assert completed["axioms_commitment"] == proof.public_inputs["axioms_commitment"]
    assert completed["source_id"] == "us-code-42-18726.-3ff52550e83c51a1"
    assert zkp_attestation_legal_ir_view_loss([flattened_record]) == 0.0


def test_backend_fails_if_cli_succeeds_without_proof_file(tmp_path):
    binary = _fake_provekit_cli(tmp_path / "provekit-cli", write_proof=False)
    backend = ProveKitBackend(binary_path=str(binary))

    with pytest.raises(ZKPError, match="proof output was not created"):
        backend.generate_proof(
            theorem="Q",
            private_axioms=["P", "P -> Q"],
            metadata=_artifact_metadata(tmp_path),
        )
