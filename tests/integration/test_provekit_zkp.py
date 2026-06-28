import json
import os
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.zkp import ZKPProof
from ipfs_datasets_py.logic.zkp.backends.provekit import ProveKitBackend
from ipfs_datasets_py.logic.zkp.circuits import attestation_view_matches_proof
from ipfs_datasets_py.logic.zkp.provekit.artifacts import (
    build_provekit_artifact_manifest,
)
from ipfs_datasets_py.logic.zkp.provekit.cli import ProveKitCLI, discover_provekit_binary
from ipfs_datasets_py.logic.zkp.provekit.witness import provekit_witness_workspace


def _truthy_env(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "y", "on"}


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _knowledge_circuit_dir() -> Path:
    return (
        _repo_root()
        / "ipfs_datasets_py"
        / "logic"
        / "zkp"
        / "provekit"
        / "circuits"
        / "knowledge_of_axioms"
    )


def _configured_provekit_binary() -> Path:
    try:
        binary = discover_provekit_binary()
    except Exception as exc:
        pytest.fail(f"Configured ProveKit binary is invalid: {exc}")
    if binary is None:
        pytest.skip(
            "Set IPFS_DATASETS_PROVEKIT_CLI or IPFS_DATASETS_PROVEKIT_HOME "
            "to run real ProveKit integration tests"
        )
    return binary


def test_provekit_integration_gate_respects_environment(monkeypatch):
    monkeypatch.setenv("IPFS_DATASETS_RUN_PROVEKIT_TESTS", "0")
    assert not _truthy_env("IPFS_DATASETS_RUN_PROVEKIT_TESTS")

    monkeypatch.setenv("IPFS_DATASETS_RUN_PROVEKIT_TESTS", "1")
    assert _truthy_env("IPFS_DATASETS_RUN_PROVEKIT_TESTS")


@pytest.mark.integration
@pytest.mark.skipif(
    not _truthy_env("IPFS_DATASETS_RUN_PROVEKIT_TESTS"),
    reason="Set IPFS_DATASETS_RUN_PROVEKIT_TESTS=1 to run real ProveKit CLI tests",
)
def test_real_provekit_prepare_prove_verify_roundtrip(tmp_path: Path):
    binary = _configured_provekit_binary()
    circuit_dir = _knowledge_circuit_dir()
    assert circuit_dir.is_dir()

    pkp = tmp_path / "provekit_knowledge_of_axioms.pkp"
    pkv = tmp_path / "provekit_knowledge_of_axioms.pkv"
    proof_path = tmp_path / "proof.np"
    target_dir = tmp_path / "target"

    cli = ProveKitCLI(binary_path=binary, timeout_seconds=60)
    prepare = cli.prepare(
        program_dir=circuit_dir,
        target_dir=target_dir,
        prover_key_path=pkp,
        verifier_key_path=pkv,
        force=True,
    )
    prepare.raise_for_failure()
    assert pkp.is_file()
    assert pkv.is_file()

    manifest = build_provekit_artifact_manifest(
        circuit_id="provekit_knowledge_of_axioms",
        noir_package_path=circuit_dir,
        prover_key_path=pkp,
        verifier_key_path=pkv,
        provekit_binary_path=binary,
        provekit_branch="v1",
        provekit_commit=os.environ.get(
            "IPFS_DATASETS_PROVEKIT_COMMIT",
            "4c085f03aa583c255dda4831f1dba7e8c3f284cb",
        ),
    )
    manifest.validate_files()

    private_axioms = ["secret integration fact", "secret integration fact -> Q"]
    with provekit_witness_workspace(
        theorem="Q",
        private_axioms=private_axioms,
        base_dir=tmp_path,
    ) as witness:
        backend = ProveKitBackend(binary_path=str(binary), timeout_seconds=60)
        proof = backend.generate_proof(
            theorem="Q",
            private_axioms=private_axioms,
            metadata={
                **manifest.to_backend_artifacts(),
                "provekit_artifacts": {
                    **manifest.to_backend_artifacts()["provekit_artifacts"],
                    "input_path": witness.prover_toml_path,
                    "proof_path": str(proof_path),
                },
            },
        )

    assert proof_path.is_file()
    assert proof.proof_data == proof_path.read_bytes()
    assert proof.size_bytes == len(proof.proof_data)
    assert backend.verify_proof(proof) is True
    assert attestation_view_matches_proof(
        proof_data=proof.proof_data,
        public_inputs=proof.public_inputs,
        metadata=proof.metadata,
    )

    proof_dict = proof.to_dict()
    payload = json.dumps(proof_dict, sort_keys=True)
    assert "secret integration fact" not in payload
    roundtrip = ZKPProof.from_dict(proof_dict)
    assert roundtrip.proof_data == proof.proof_data
    assert roundtrip.public_inputs == proof.public_inputs
    assert roundtrip.metadata == proof.metadata

