"""Cross-runtime fixtures for the MCP++ Profile F MPC ceremony contract."""

from __future__ import annotations

import json
import asyncio
import hashlib
from pathlib import Path

import pytest
from starlette.requests import Request

from ipfs_datasets_py.logic.zkp.ceremony import (
    assert_arkworks_mpc_ceremony,
    assert_production_eligible_groth16_ceremony,
    ceremony_cid,
    validate_groth16_mpc_ceremony,
)
from ipfs_datasets_py.logic.zkp import ZKPError
from ipfs_datasets_py.logic.zkp.backends.groth16 import Groth16Backend


def _fixture_path() -> Path:
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "Mcp-Plus-Plus" / "tests-py" / "fixtures" / "valid" / "profile_f_groth16_mpc_ceremony.json"
        if candidate.is_file():
            return candidate
    raise RuntimeError("shared MCP++ ceremony fixture is unavailable")


def _fixture() -> dict:
    return json.loads(_fixture_path().read_text(encoding="utf-8"))


def _artifact(content: bytes) -> dict[str, int | str]:
    digest = hashlib.sha256(content).hexdigest()
    return {"sha256": digest, "cid": f"sha256:{digest}", "sizeBytes": len(content)}


def _arkworks_manifest(proving_key: Path, verifying_key: Path) -> dict:
    manifest = _fixture()
    manifest["keyFormat"] = "arkworks-canonical"
    manifest["circuitId"] = "knowledge_of_axioms@v1"
    proving_key_artifact = _artifact(proving_key.read_bytes())
    manifest["provingKey"] = proving_key_artifact
    manifest["contributions"][-1]["outputArtifactSha256"] = proving_key_artifact["sha256"]
    manifest["finalZkey"] = proving_key_artifact
    manifest["verificationKey"] = _artifact(verifying_key.read_bytes())
    for contribution in manifest["contributions"]:
        contribution["transcriptVerifier"] = "arkworks-mpc-verifier"
    return manifest


def test_shared_profile_f_fixture_is_production_eligible() -> None:
    manifest = _fixture()
    result = validate_groth16_mpc_ceremony(manifest)

    assert result.valid is True
    assert result.production_eligible is True
    assert result.independent_contributors == ("did:key:z6MkhAlice", "did:key:z6MkhBob")
    assert result.reasons == ()
    assert result.ceremony_cid == ceremony_cid(manifest)
    assert result.ceremony_cid == "sha256:645338f97ee9f1d17529c4be2b88f928b8bc4c19d906172f0ba0d269780f04b8"
    assert_production_eligible_groth16_ceremony(manifest)


def test_broken_initial_zkey_chain_is_rejected() -> None:
    manifest = _fixture()
    manifest["contributions"][0]["inputArtifactSha256"] = "0" * 64

    result = validate_groth16_mpc_ceremony(manifest)

    assert result.valid is False
    assert result.production_eligible is False
    assert "broken_artifact_chain_1" in result.reasons
    with pytest.raises(ValueError, match="not production eligible"):
        assert_production_eligible_groth16_ceremony(manifest)


def test_collecting_single_contributor_manifest_is_not_production_eligible() -> None:
    manifest = _fixture()
    manifest["contributions"] = [manifest["contributions"][0]]
    manifest.pop("finalZkey")
    manifest.pop("verificationKey")
    manifest.pop("finalizedAt")
    manifest["status"] = "collecting"

    result = validate_groth16_mpc_ceremony(manifest)

    assert result.valid is True
    assert result.production_eligible is False
    assert result.reasons == ("independent_contributor_quorum_not_met",)


def test_artifact_cid_must_match_its_hash() -> None:
    manifest = _fixture()
    manifest["verificationKey"]["cid"] = f"sha256:{'0' * 64}"

    result = validate_groth16_mpc_ceremony(manifest)

    assert result.valid is False
    assert "incomplete_finalization" in result.reasons


def test_arkworks_admission_binds_expected_circuit_and_local_verification_key(tmp_path: Path) -> None:
    proving_key = tmp_path / "proving_key.bin"
    verifying_key = tmp_path / "verifying_key.bin"
    proving_key.write_bytes(b"independently-generated-arkworks-proving-key")
    verifying_key.write_bytes(b"independently-generated-arkworks-verification-key")

    result = assert_arkworks_mpc_ceremony(
        _arkworks_manifest(proving_key, verifying_key),
        expected_circuit_id="knowledge_of_axioms@v1",
        proving_key_path=proving_key,
        verifying_key_path=verifying_key,
    )

    assert result.production_eligible is True


def test_arkworks_admission_rejects_missing_format_or_local_key_mismatch(tmp_path: Path) -> None:
    proving_key = tmp_path / "proving_key.bin"
    verifying_key = tmp_path / "verifying_key.bin"
    proving_key.write_bytes(b"first-proving-key")
    verifying_key.write_bytes(b"first-key")
    manifest = _arkworks_manifest(proving_key, verifying_key)
    manifest.pop("keyFormat")

    with pytest.raises(ValueError, match="keyFormat"):
        assert_arkworks_mpc_ceremony(
            manifest,
            expected_circuit_id="knowledge_of_axioms@v1",
            proving_key_path=proving_key,
            verifying_key_path=verifying_key,
        )

    manifest = _arkworks_manifest(proving_key, verifying_key)
    verifying_key.write_bytes(b"replaced-key")
    with pytest.raises(ValueError, match="verificationKey hash does not match the local artifact"):
        assert_arkworks_mpc_ceremony(
            manifest,
            expected_circuit_id="knowledge_of_axioms@v1",
            proving_key_path=proving_key,
            verifying_key_path=verifying_key,
        )


def test_arkworks_admission_rejects_a_proving_key_that_is_not_in_the_manifest(tmp_path: Path) -> None:
    proving_key = tmp_path / "proving_key.bin"
    verifying_key = tmp_path / "verifying_key.bin"
    proving_key.write_bytes(b"first-proving-key")
    verifying_key.write_bytes(b"verification-key")
    manifest = _arkworks_manifest(proving_key, verifying_key)
    proving_key.write_bytes(b"substituted-proving-key")

    with pytest.raises(ValueError, match="provingKey hash does not match the local artifact"):
        assert_arkworks_mpc_ceremony(
            manifest,
            expected_circuit_id="knowledge_of_axioms@v1",
            proving_key_path=proving_key,
            verifying_key_path=verifying_key,
        )


def test_backend_admits_only_the_key_in_an_arkworks_mpc_manifest(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    crate_root = tmp_path / "groth16_backend"
    binary = crate_root / "target" / "release" / "groth16"
    binary.parent.mkdir(parents=True)
    binary.write_bytes(b"placeholder")
    proving_key = crate_root / "artifacts" / "v1" / "proving_key.bin"
    verifying_key = crate_root / "artifacts" / "v1" / "verifying_key.bin"
    verifying_key.parent.mkdir(parents=True)
    proving_key.write_bytes(b"arkworks-pk")
    verifying_key.write_bytes(b"arkworks-vk")
    manifest_path = tmp_path / "ceremony.json"
    manifest_path.write_text(json.dumps(_arkworks_manifest(proving_key, verifying_key)), encoding="utf-8")

    monkeypatch.setenv("IPFS_DATASETS_ENABLE_GROTH16", "1")
    monkeypatch.setenv("IPFS_DATASETS_REQUIRE_MPC_CEREMONY", "1")
    monkeypatch.setenv("IPFS_DATASETS_GROTH16_CEREMONY_MANIFEST", str(manifest_path))

    Groth16Backend(binary_path=str(binary))._require_mpc_compatible_backend(
        circuit_id="knowledge_of_axioms", circuit_version=1
    )


def test_mcpplusplus_validator_method_returns_the_shared_contract() -> None:
    from ipfs_datasets_py.mcp_server.fastapi_service import mcp_jsonrpc_handler

    payload = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 7,
            "method": "mcp++/zk/ceremony/validate",
            "params": {"manifest": _fixture()},
        }
    ).encode("utf-8")

    async def receive() -> dict:
        return {"type": "http.request", "body": payload, "more_body": False}

    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/mcp",
            "headers": [(b"content-type", b"application/json")],
        },
        receive,
    )
    response = asyncio.run(mcp_jsonrpc_handler(request))

    assert response["id"] == 7
    assert response["result"]["valid"] is True
    assert response["result"]["production_eligible"] is True


def test_single_rng_backend_fails_closed_when_mpc_is_required(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("IPFS_DATASETS_ENABLE_GROTH16", "1")
    monkeypatch.setenv("IPFS_DATASETS_REQUIRE_MPC_CEREMONY", "1")

    with pytest.raises(ZKPError, match="single-RNG setup"):
        Groth16Backend().setup()
