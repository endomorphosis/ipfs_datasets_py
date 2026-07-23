"""Ops-readiness and backend health checks for the ProveKit ZKP backend.

These tests validate that operators can check:

- ProveKit binary availability without triggering a build or network call.
- Artifact manifest integrity via SHA-256 digest comparison.
- Circuit manifests for all packaged Noir circuit families.
- Backend enablement status from the registry.
- Fail-closed readiness: unavailable binary or missing artifacts must never
  silently produce simulated proofs.

No private witness material is read, logged, or stored by any test in this
module.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any
import stat

import pytest

# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[4]
PACKAGE_ROOT = REPO_ROOT / "ipfs_datasets_py"
CIRCUITS_ROOT = PACKAGE_ROOT / "logic" / "zkp" / "provekit" / "circuits"
BUILD_SCRIPT = PACKAGE_ROOT / "processors" / "provekit_backend" / "build.sh"

# Known packaged circuit families with their expected Nargo package names.
KNOWN_CIRCUITS: dict[str, str] = {
    "knowledge_of_axioms": "provekit_knowledge_of_axioms",
    "tdfol_v1_trace": "provekit_tdfol_v1_trace",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_executable(path: Path) -> Path:
    """Create a minimal shell stub that exits 0 and is executable."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return path


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


# ---------------------------------------------------------------------------
# Binary availability checks
# ---------------------------------------------------------------------------

def test_binary_discovery_returns_none_when_no_binary_configured(monkeypatch):
    """discover_provekit_binary must return None when no binary is found."""
    from ipfs_datasets_py.logic.zkp.provekit.cli import discover_provekit_binary

    # Clear all env vars that could point to a real binary.
    cleared_env: dict[str, str] = {
        k: v for k, v in os.environ.items()
        if k not in {
            "IPFS_DATASETS_PROVEKIT_CLI",
            "IPFS_DATASETS_PROVEKIT_BIN",
            "PROVEKIT_CLI",
            "PROVEKIT_BIN",
            "IPFS_DATASETS_PROVEKIT_HOME",
            "PROVEKIT_HOME",
        }
    }

    result = discover_provekit_binary(
        env=cleared_env,
        package_dir=Path("/nonexistent-provekit-dir"),
        search_path=False,
    )

    assert result is None, (
        "discover_provekit_binary must return None when no binary is available; "
        f"got: {result}"
    )


def test_binary_discovery_finds_env_var_configured_binary(tmp_path, monkeypatch):
    """discover_provekit_binary returns the path when IPFS_DATASETS_PROVEKIT_CLI is set."""
    from ipfs_datasets_py.logic.zkp.provekit.cli import discover_provekit_binary

    binary = _make_executable(tmp_path / "provekit-cli")
    env = {"IPFS_DATASETS_PROVEKIT_CLI": str(binary)}

    result = discover_provekit_binary(env=env)

    assert result is not None
    assert result == binary


def test_binary_discovery_finds_home_env_var_configured_binary(tmp_path):
    """discover_provekit_binary finds the binary under PROVEKIT_HOME/bin."""
    from ipfs_datasets_py.logic.zkp.provekit.cli import discover_provekit_binary

    binary = _make_executable(tmp_path / "bin" / "provekit-cli")
    env = {"IPFS_DATASETS_PROVEKIT_HOME": str(tmp_path)}

    result = discover_provekit_binary(env=env)

    assert result is not None
    assert result == binary


def test_binary_discovery_raises_on_invalid_explicit_path(tmp_path):
    """discover_provekit_binary raises ZKPError when an explicit path is non-executable."""
    from ipfs_datasets_py.logic.zkp import ZKPError
    from ipfs_datasets_py.logic.zkp.provekit.cli import discover_provekit_binary

    missing = tmp_path / "nonexistent-provekit-cli"
    env = {"IPFS_DATASETS_PROVEKIT_CLI": str(missing)}

    with pytest.raises(ZKPError, match="not executable or does not exist"):
        discover_provekit_binary(env=env)


def test_binary_availability_reported_by_backend_object(tmp_path):
    """ProveKitBackend.binary_available() is True when binary path is executable."""
    from ipfs_datasets_py.logic.zkp.backends.provekit import ProveKitBackend

    binary = _make_executable(tmp_path / "provekit-cli")
    backend = ProveKitBackend(binary_path=str(binary))

    assert backend.binary_available() is True


def test_binary_unavailable_backend_reports_false(monkeypatch):
    """ProveKitBackend.binary_available() is False when no binary is discoverable."""
    from ipfs_datasets_py.logic.zkp.backends.provekit import ProveKitBackend

    monkeypatch.setattr(
        "ipfs_datasets_py.logic.zkp.backends.provekit.discover_provekit_binary",
        lambda: None,
    )
    backend = ProveKitBackend()

    assert backend.binary_available() is False


# ---------------------------------------------------------------------------
# Fail-closed readiness checks
# ---------------------------------------------------------------------------

def test_generate_proof_fails_closed_without_binary(monkeypatch):
    """generate_proof must raise ZKPError (not return a simulated proof) when no binary."""
    from ipfs_datasets_py.logic.zkp import ZKPError
    from ipfs_datasets_py.logic.zkp.backends.provekit import ProveKitBackend

    monkeypatch.setattr(
        "ipfs_datasets_py.logic.zkp.backends.provekit.discover_provekit_binary",
        lambda: None,
    )
    backend = ProveKitBackend()

    with pytest.raises(ZKPError):
        backend.generate_proof("Q", ["P", "P -> Q"], metadata={})


def test_generate_proof_fails_closed_without_artifact_metadata(tmp_path):
    """generate_proof raises ZKPError when provekit_artifacts key is absent from metadata."""
    from ipfs_datasets_py.logic.zkp import ZKPError
    from ipfs_datasets_py.logic.zkp.backends.provekit import ProveKitBackend

    binary = _make_executable(tmp_path / "provekit-cli")
    backend = ProveKitBackend(binary_path=str(binary))

    with pytest.raises(ZKPError):
        backend.generate_proof("Q", ["P"], metadata={})


def test_generate_proof_fails_closed_when_prover_key_missing(tmp_path):
    """generate_proof raises ZKPError when the prover key file does not exist."""
    from ipfs_datasets_py.logic.zkp import ZKPError
    from ipfs_datasets_py.logic.zkp.backends.provekit import ProveKitBackend

    binary = _make_executable(tmp_path / "provekit-cli")
    private_input = tmp_path / "Prover.toml"
    private_input.write_text('theorem_hash_field = "0x0"\n', encoding="utf-8")
    backend = ProveKitBackend(binary_path=str(binary))

    with pytest.raises(ZKPError):
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


def test_generate_proof_fails_closed_with_empty_theorem(tmp_path):
    """generate_proof raises ZKPError when theorem is empty."""
    from ipfs_datasets_py.logic.zkp import ZKPError
    from ipfs_datasets_py.logic.zkp.backends.provekit import ProveKitBackend

    binary = _make_executable(tmp_path / "provekit-cli")
    backend = ProveKitBackend(binary_path=str(binary))

    with pytest.raises(ZKPError, match="[Tt]heorem"):
        backend.generate_proof("", ["P -> Q"], metadata={})


def test_generate_proof_fails_closed_with_empty_axioms(tmp_path):
    """generate_proof raises ZKPError when axiom list is empty."""
    from ipfs_datasets_py.logic.zkp import ZKPError
    from ipfs_datasets_py.logic.zkp.backends.provekit import ProveKitBackend

    binary = _make_executable(tmp_path / "provekit-cli")
    backend = ProveKitBackend(binary_path=str(binary))

    with pytest.raises(ZKPError, match="[Aa]xiom"):
        backend.generate_proof("Q", [], metadata={})


def test_verify_proof_fails_closed_without_verifier_key(tmp_path):
    """verify_proof raises ZKPError when verifier key is absent."""
    from ipfs_datasets_py.logic.zkp import ZKPError, ZKPProof
    from ipfs_datasets_py.logic.zkp.backends.provekit import ProveKitBackend

    binary = _make_executable(tmp_path / "provekit-cli")
    backend = ProveKitBackend(binary_path=str(binary))
    proof = ZKPProof(
        proof_data=b"x" * 160,
        public_inputs={"theorem": "Q", "theorem_hash": "a" * 64},
        metadata={"backend": "provekit"},
        timestamp=0.0,
        size_bytes=160,
    )

    with pytest.raises(ZKPError):
        backend.verify_proof(proof)


# ---------------------------------------------------------------------------
# Circuit manifest checks
# ---------------------------------------------------------------------------

def test_all_known_circuits_have_nargo_toml():
    """Each packaged circuit directory must contain a Nargo.toml."""
    for circuit_name in KNOWN_CIRCUITS:
        circuit_dir = CIRCUITS_ROOT / circuit_name
        nargo_toml = circuit_dir / "Nargo.toml"
        assert nargo_toml.is_file(), (
            f"Missing Nargo.toml for circuit '{circuit_name}': {nargo_toml}"
        )


def test_all_known_circuits_have_main_nr():
    """Each packaged circuit directory must contain src/main.nr."""
    for circuit_name in KNOWN_CIRCUITS:
        circuit_dir = CIRCUITS_ROOT / circuit_name
        main_nr = circuit_dir / "src" / "main.nr"
        assert main_nr.is_file(), (
            f"Missing src/main.nr for circuit '{circuit_name}': {main_nr}"
        )


def test_nargo_toml_package_names_match_expected_names():
    """Nargo.toml [package] name must match the expected package name constant."""
    try:
        import tomllib
    except ImportError:
        import tomli as tomllib  # type: ignore[no-redef]

    for circuit_name, expected_package_name in KNOWN_CIRCUITS.items():
        nargo_toml = CIRCUITS_ROOT / circuit_name / "Nargo.toml"
        data = tomllib.loads(nargo_toml.read_text(encoding="utf-8"))
        actual_name = data.get("package", {}).get("name", "")
        assert actual_name == expected_package_name, (
            f"Circuit '{circuit_name}' Nargo.toml package name is '{actual_name}', "
            f"expected '{expected_package_name}'"
        )


def test_circuit_directory_contains_no_key_artifacts():
    """Packaged circuit directories must not include .pkp, .pkv, .np, or Prover.toml files."""
    forbidden_suffixes = {".pkp", ".pkv", ".np"}
    forbidden_names = {"Prover.toml"}

    for circuit_name in KNOWN_CIRCUITS:
        circuit_dir = CIRCUITS_ROOT / circuit_name
        if not circuit_dir.is_dir():
            continue
        for path in circuit_dir.rglob("*"):
            if not path.is_file():
                continue
            assert path.suffix not in forbidden_suffixes, (
                f"Key/proof artifact must not be packaged under circuit dir: {path}"
            )
            assert path.name not in forbidden_names, (
                f"Private witness file must not be packaged: {path}"
            )


def test_circuit_manifests_accessible_via_circuits_root_constant():
    """CIRCUITS_ROOT must point to a directory containing at least the known circuit families."""
    assert CIRCUITS_ROOT.is_dir(), f"CIRCUITS_ROOT does not exist: {CIRCUITS_ROOT}"
    for circuit_name in KNOWN_CIRCUITS:
        assert (CIRCUITS_ROOT / circuit_name).is_dir(), (
            f"Circuit directory missing: {CIRCUITS_ROOT / circuit_name}"
        )


# ---------------------------------------------------------------------------
# Artifact integrity checks (manifest validation)
# ---------------------------------------------------------------------------

def test_sha256_file_helper_produces_deterministic_digest(tmp_path):
    """sha256_file must produce the same digest for identical content."""
    from ipfs_datasets_py.logic.zkp.provekit.artifacts import sha256_file

    data = b"deterministic test content for sha256_file"
    f1 = tmp_path / "a.bin"
    f2 = tmp_path / "b.bin"
    f1.write_bytes(data)
    f2.write_bytes(data)

    assert sha256_file(f1) == sha256_file(f2)
    assert sha256_file(f1) == _sha256_bytes(data)


def test_sha256_directory_helper_produces_deterministic_digest(tmp_path):
    """sha256_directory must produce the same digest for identical directory content."""
    from ipfs_datasets_py.logic.zkp.provekit.artifacts import sha256_directory

    d1 = tmp_path / "dir1"
    d2 = tmp_path / "dir2"
    for d in (d1, d2):
        d.mkdir()
        (d / "Nargo.toml").write_text("[package]\nname = \"test\"\n", encoding="utf-8")
        (d / "src").mkdir()
        (d / "src" / "main.nr").write_text("fn main() {}\n", encoding="utf-8")

    assert sha256_directory(d1) == sha256_directory(d2)


def test_sha256_directory_ignores_excluded_suffixes(tmp_path):
    """sha256_directory digest must be unchanged when .pkp/.pkv files are added."""
    from ipfs_datasets_py.logic.zkp.provekit.artifacts import sha256_directory

    circuit_dir = tmp_path / "circuit"
    circuit_dir.mkdir()
    (circuit_dir / "Nargo.toml").write_text("[package]\nname = \"test\"\n", encoding="utf-8")

    digest_before = sha256_directory(circuit_dir)

    # Adding excluded artifacts must not change the digest.
    (circuit_dir / "test.pkp").write_bytes(b"prover key bytes")
    (circuit_dir / "test.pkv").write_bytes(b"verifier key bytes")

    digest_after = sha256_directory(circuit_dir)

    assert digest_before == digest_after, (
        "sha256_directory must exclude .pkp and .pkv artifacts from its digest"
    )


def test_artifact_manifest_validates_digest_mismatch_fails_closed(tmp_path):
    """ProveKitArtifactManifest.validate_files must raise ZKPError on digest mismatch."""
    from ipfs_datasets_py.logic.zkp import ZKPError
    from ipfs_datasets_py.logic.zkp.provekit.artifacts import (
        ProveKitArtifactManifest,
        sha256_directory,
        sha256_file,
    )
    from ipfs_datasets_py.logic.zkp.statement import format_circuit_ref

    noir_pkg = tmp_path / "circuit"
    noir_pkg.mkdir()
    (noir_pkg / "Nargo.toml").write_text("[package]\nname = \"test\"\n", encoding="utf-8")
    pkp = tmp_path / "test.pkp"
    pkv = tmp_path / "test.pkv"
    pkp.write_bytes(b"prover key")
    pkv.write_bytes(b"verifier key")

    manifest = ProveKitArtifactManifest(
        circuit_id="health_check_test",
        circuit_version=1,
        circuit_ref=format_circuit_ref("health_check_test", 1),
        ruleset_id="TDFOL_v1",
        hash_backend="sha256",
        noir_package_path=str(noir_pkg),
        prover_key_path=str(pkp),
        verifier_key_path=str(pkv),
        provekit_branch="v1",
        provekit_commit="aabbccdd",
        noir_package_sha256=sha256_directory(noir_pkg),
        prover_key_sha256=sha256_file(pkp),
        verifier_key_sha256=sha256_file(pkv),
    )

    # Files valid right now: should not raise.
    manifest.validate_files()

    # Mutate the prover key – digest now mismatches.
    pkp.write_bytes(b"tampered prover key content")

    with pytest.raises(ZKPError, match="digest mismatch"):
        manifest.validate_files()


def test_load_manifest_fails_closed_on_missing_file(tmp_path):
    """load_provekit_artifact_manifest raises ZKPError when the manifest file is absent."""
    from ipfs_datasets_py.logic.zkp import ZKPError
    from ipfs_datasets_py.logic.zkp.provekit.artifacts import load_provekit_artifact_manifest

    missing = tmp_path / "does_not_exist.json"

    with pytest.raises(ZKPError, match="does not exist"):
        load_provekit_artifact_manifest(missing)


def test_manifest_round_trip_preserves_all_fields(tmp_path):
    """save/load_provekit_artifact_manifest preserves all manifest fields."""
    from ipfs_datasets_py.logic.zkp.provekit.artifacts import (
        ProveKitArtifactManifest,
        load_provekit_artifact_manifest,
        save_provekit_artifact_manifest,
        sha256_directory,
        sha256_file,
    )
    from ipfs_datasets_py.logic.zkp.statement import format_circuit_ref

    noir_pkg = tmp_path / "circuit"
    noir_pkg.mkdir()
    (noir_pkg / "Nargo.toml").write_text("[package]\nname = \"rt\"\n", encoding="utf-8")
    pkp = tmp_path / "rt.pkp"
    pkv = tmp_path / "rt.pkv"
    pkp.write_bytes(b"prover key roundtrip")
    pkv.write_bytes(b"verifier key roundtrip")

    original = ProveKitArtifactManifest(
        circuit_id="health_roundtrip",
        circuit_version=1,
        circuit_ref=format_circuit_ref("health_roundtrip", 1),
        ruleset_id="TDFOL_v1",
        hash_backend="sha256",
        noir_package_path=str(noir_pkg),
        prover_key_path=str(pkp),
        verifier_key_path=str(pkv),
        provekit_branch="v1",
        provekit_commit="deadbeef",
        noir_package_sha256=sha256_directory(noir_pkg),
        prover_key_sha256=sha256_file(pkp),
        verifier_key_sha256=sha256_file(pkv),
    )

    manifest_path = save_provekit_artifact_manifest(original, tmp_path / "manifest.json")
    loaded = load_provekit_artifact_manifest(manifest_path, validate_files=True)

    assert loaded.circuit_id == original.circuit_id
    assert loaded.circuit_version == original.circuit_version
    assert loaded.circuit_ref == original.circuit_ref
    assert loaded.provekit_branch == original.provekit_branch
    assert loaded.prover_key_sha256 == original.prover_key_sha256
    assert loaded.verifier_key_sha256 == original.verifier_key_sha256
    assert loaded.noir_package_sha256 == original.noir_package_sha256


# ---------------------------------------------------------------------------
# Backend enablement / registry checks
# ---------------------------------------------------------------------------

def test_backend_registry_includes_provekit():
    """list_backends must include 'provekit' with WHIR in its description."""
    from ipfs_datasets_py.logic.zkp.backends import list_backends

    metadata = list_backends()

    assert "provekit" in metadata
    assert "WHIR" in metadata["provekit"]["description"]


def test_provekit_backend_selectable_from_registry():
    """get_backend('provekit') returns a ProveKitBackend without raising."""
    from ipfs_datasets_py.logic.zkp.backends import clear_backend_cache, get_backend
    from ipfs_datasets_py.logic.zkp.backends.provekit import ProveKitBackend

    clear_backend_cache()
    backend = get_backend("provekit")

    assert isinstance(backend, ProveKitBackend)
    assert backend.backend_id == "provekit"


def test_provekit_backend_aliases_all_resolve():
    """Backend aliases pk, provekit-whir, and whir must resolve to ProveKitBackend."""
    from ipfs_datasets_py.logic.zkp.backends import clear_backend_cache, get_backend
    from ipfs_datasets_py.logic.zkp.backends.provekit import ProveKitBackend

    for alias in ("pk", "provekit-whir", "whir"):
        clear_backend_cache()
        backend = get_backend(alias)
        assert isinstance(backend, ProveKitBackend), (
            f"Alias '{alias}' did not resolve to ProveKitBackend"
        )


def test_provekit_backend_reports_correct_proof_system():
    """ProveKitBackend must advertise proof_system = 'ProveKit-WHIR'."""
    from ipfs_datasets_py.logic.zkp.backends import clear_backend_cache, get_backend

    clear_backend_cache()
    backend = get_backend("provekit")

    assert backend.proof_system == "ProveKit-WHIR"


# ---------------------------------------------------------------------------
# Build-script packaging check (operator convenience)
# ---------------------------------------------------------------------------

def test_build_script_exists_and_is_executable():
    """The ProveKit build.sh helper must exist and be executable."""
    assert BUILD_SCRIPT.is_file(), f"build.sh not found at {BUILD_SCRIPT}"
    assert os.access(BUILD_SCRIPT, os.X_OK), f"build.sh is not executable: {BUILD_SCRIPT}"


def test_build_script_check_mode_passes_without_binary(monkeypatch):
    """build.sh --check must exit 0 and print a check-passed message even without a binary."""
    import subprocess

    result = subprocess.run(
        [str(BUILD_SCRIPT), "--check"],
        check=False,
        capture_output=True,
        text=True,
        timeout=15,
        env={
            **os.environ,
            "IPFS_DATASETS_PROVEKIT_CLI": "",
            "IPFS_DATASETS_PROVEKIT_HOME": "",
        },
    )

    assert result.returncode == 0, (
        f"build.sh --check failed (rc={result.returncode}):\n{result.stderr}"
    )
    assert "Packaging check passed" in result.stdout


def test_build_script_does_not_clone_or_build_rust():
    """build.sh must not contain git clone, cargo build, curl, or wget."""
    script_text = BUILD_SCRIPT.read_text(encoding="utf-8")

    for forbidden in ("git clone", "cargo build", "curl ", "wget "):
        assert forbidden not in script_text, (
            f"build.sh must not contain '{forbidden}' — operators manage builds externally"
        )


# ---------------------------------------------------------------------------
# Witness no-leak (boundary checks)
# ---------------------------------------------------------------------------

def test_private_witness_does_not_appear_in_manifest_fields(tmp_path):
    """Artifact manifests must not contain private witness field names."""
    from ipfs_datasets_py.logic.zkp.provekit.artifacts import (
        ProveKitArtifactManifest,
        sha256_directory,
        sha256_file,
    )
    from ipfs_datasets_py.logic.zkp.statement import format_circuit_ref

    noir_pkg = tmp_path / "circuit"
    noir_pkg.mkdir()
    (noir_pkg / "Nargo.toml").write_text("[package]\nname = \"wl\"\n", encoding="utf-8")
    pkp = tmp_path / "wl.pkp"
    pkv = tmp_path / "wl.pkv"
    pkp.write_bytes(b"pk")
    pkv.write_bytes(b"vk")

    manifest = ProveKitArtifactManifest(
        circuit_id="witness_leak_check",
        circuit_version=1,
        circuit_ref=format_circuit_ref("witness_leak_check", 1),
        ruleset_id="TDFOL_v1",
        hash_backend="sha256",
        noir_package_path=str(noir_pkg),
        prover_key_path=str(pkp),
        verifier_key_path=str(pkv),
        provekit_branch="v1",
        provekit_commit="cafebabe",
        noir_package_sha256=sha256_directory(noir_pkg),
        prover_key_sha256=sha256_file(pkp),
        verifier_key_sha256=sha256_file(pkv),
    )

    manifest_dict = manifest.to_dict()
    manifest_json = json.dumps(manifest_dict)

    # These keys would indicate private witness data in the manifest.
    private_witness_keys = {"private_axioms", "witness", "prover_toml", "axiom_text"}
    for key in private_witness_keys:
        assert key not in manifest_dict, (
            f"Manifest must not contain private witness field '{key}'"
        )
        assert f'"{key}"' not in manifest_json, (
            f"Manifest JSON must not contain private witness key '{key}'"
        )


def test_cli_wrapper_redacts_witness_path_in_prove_command(tmp_path):
    """ProveKitCLI.build_prove_command must mark the input path as sensitive."""
    from ipfs_datasets_py.logic.zkp.provekit.cli import SENSITIVE_REDACTION, ProveKitCLI

    binary = _make_executable(tmp_path / "provekit-cli")
    cli = ProveKitCLI(binary_path=str(binary))

    prover_key = tmp_path / "circuit.pkp"
    prover_key.write_bytes(b"pkp")
    input_path = tmp_path / "Prover.toml"
    input_path.write_text("secret = true\n", encoding="utf-8")
    proof_output = tmp_path / "proof.np"

    command = cli.build_prove_command(
        prover_key_path=prover_key,
        input_path=input_path,
        proof_path=proof_output,
    )

    assert str(input_path) in command.sensitive_values, (
        "Input (witness) path must be in sensitive_values"
    )
    redacted_argv = command.redacted_argv()
    assert str(input_path) not in " ".join(redacted_argv), (
        "Input (witness) path must not appear in redacted argv"
    )
    assert SENSITIVE_REDACTION in " ".join(redacted_argv), (
        "Redacted argv must contain the redaction sentinel"
    )
