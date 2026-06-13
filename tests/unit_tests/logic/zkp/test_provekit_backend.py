import json
import subprocess
import sys
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.zkp import ZKPError, ZKPProof
from ipfs_datasets_py.logic.zkp.backends import (
    backend_is_available,
    clear_backend_cache,
    get_backend,
    list_backends,
)
from ipfs_datasets_py.logic.zkp.backends.provekit import ProveKitBackend


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _executable(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    path.chmod(path.stat().st_mode | 0o111)
    return path


def test_backend_registry_lists_provekit_metadata():
    metadata = list_backends()

    assert "provekit" in metadata
    assert metadata["provekit"]["module"] == "provekit"
    assert metadata["provekit"]["class_name"] == "ProveKitBackend"
    assert "WHIR" in metadata["provekit"]["description"]


def test_get_backend_provekit_and_aliases_are_lazy():
    clear_backend_cache()

    backend = get_backend("provekit")
    assert backend.backend_id == "provekit"

    for alias in ["pk", "provekit-whir", "whir", "PROVEKIT"]:
        clear_backend_cache()
        alias_backend = get_backend(alias)
        assert alias_backend.backend_id == "provekit"


def test_backend_availability_only_checks_selection_not_binary_readiness():
    clear_backend_cache()

    assert backend_is_available("provekit") is True


def test_unavailable_binary_fails_closed(monkeypatch):
    backend = ProveKitBackend()
    monkeypatch.setattr(
        "ipfs_datasets_py.logic.zkp.backends.provekit.discover_provekit_binary",
        lambda: None,
    )

    with pytest.raises(ZKPError, match="ProveKit backend is unavailable"):
        backend.generate_proof("Q", ["P", "P -> Q"], metadata={})


def test_missing_artifacts_fail_closed_after_binary_resolution(tmp_path):
    binary = _executable(tmp_path / "provekit-cli")
    backend = ProveKitBackend(binary_path=str(binary))

    with pytest.raises(ZKPError, match="requires explicit artifact metadata"):
        backend.generate_proof("Q", ["P"], metadata={})


def test_missing_prover_key_fails_closed(tmp_path):
    binary = _executable(tmp_path / "provekit-cli")
    private_input = tmp_path / "Prover.toml"
    private_input.write_text('a = "1"\n', encoding="utf-8")
    backend = ProveKitBackend(binary_path=str(binary))

    with pytest.raises(ZKPError, match="prover key"):
        backend.generate_proof(
            "Q",
            ["P"],
            metadata={
                "provekit_artifacts": {
                    "prover_key_path": tmp_path / "missing.pkp",
                    "input_path": private_input,
                    "proof_path": tmp_path / "proof.np",
                }
            },
        )


def test_verify_requires_verifier_artifacts(tmp_path):
    binary = _executable(tmp_path / "provekit-cli")
    backend = ProveKitBackend(binary_path=str(binary))
    proof = ZKPProof(
        proof_data=b"x" * 160,
        public_inputs={"theorem": "Q", "theorem_hash": "0" * 64},
        metadata={"backend": "provekit", "proof_system": "ProveKit-WHIR"},
        timestamp=0.0,
        size_bytes=160,
    )

    with pytest.raises(ZKPError, match="requires explicit artifact metadata"):
        backend.verify_proof(proof)


def test_get_backend_info_is_lightweight_when_binary_missing(monkeypatch):
    backend = ProveKitBackend()
    monkeypatch.setattr(
        "ipfs_datasets_py.logic.zkp.backends.provekit.discover_provekit_binary",
        lambda: None,
    )

    info = backend.get_backend_info()

    assert info["backend_id"] == "provekit"
    assert info["binary_available"] is False
    assert info["requires_artifacts"] is True


def test_logic_api_import_is_quiet_and_does_not_import_provekit_backend():
    code = """
import json
import sys
import warnings
warnings.simplefilter("error")
import ipfs_datasets_py.logic.api
print(json.dumps({
    "provekit_backend_imported": "ipfs_datasets_py.logic.zkp.backends.provekit" in sys.modules,
    "provekit_cli_imported": "ipfs_datasets_py.logic.zkp.provekit.cli" in sys.modules,
}, sort_keys=True))
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(_repo_root()),
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout.strip())
    assert data == {
        "provekit_backend_imported": False,
        "provekit_cli_imported": False,
    }

