import hashlib
import json

import pytest

from ipfs_datasets_py.logic.zkp import ZKPError
from ipfs_datasets_py.logic.zkp.provekit.artifacts import (
    PROVEKIT_ARTIFACT_MANIFEST_SCHEMA_VERSION,
    ProveKitArtifactManifest,
    build_provekit_artifact_manifest,
    find_provekit_key_pair,
    load_provekit_artifact_manifest,
    save_provekit_artifact_manifest,
    sha256_directory,
    sha256_file,
)


def _write_noir_package(root):
    root.mkdir(parents=True, exist_ok=True)
    (root / "Nargo.toml").write_text(
        "[package]\nname = \"provekit_knowledge_of_axioms\"\ntype = \"bin\"\n",
        encoding="utf-8",
    )
    (root / "src").mkdir()
    (root / "src" / "main.nr").write_text("fn main(x: Field) -> pub Field { x }\n", encoding="utf-8")
    return root


def _write_keys(root, stem="provekit_knowledge_of_axioms"):
    root.mkdir(parents=True, exist_ok=True)
    pkp = root / f"{stem}.pkp"
    pkv = root / f"{stem}.pkv"
    pkp.write_bytes(b"prover-key")
    pkv.write_bytes(b"verifier-key")
    return pkp, pkv


def test_sha256_file_matches_hashlib(tmp_path):
    path = tmp_path / "key.pkp"
    path.write_bytes(b"abc")

    assert sha256_file(path) == hashlib.sha256(b"abc").hexdigest()


def test_sha256_directory_is_deterministic_and_ignores_generated_outputs(tmp_path):
    package = _write_noir_package(tmp_path / "pkg")
    baseline = sha256_directory(package)

    (package / "target").mkdir()
    (package / "target" / "basic.json").write_text("generated", encoding="utf-8")
    (package / "provekit_knowledge_of_axioms.pkp").write_bytes(b"generated-key")

    assert sha256_directory(package) == baseline

    (package / "src" / "main.nr").write_text("fn main(x: Field) -> pub Field { x + 1 }\n", encoding="utf-8")
    assert sha256_directory(package) != baseline


def test_build_manifest_records_paths_versions_and_digests(tmp_path):
    package = _write_noir_package(tmp_path / "pkg")
    pkp, pkv = _write_keys(tmp_path)
    binary = tmp_path / "provekit-cli"
    binary.write_bytes(b"binary")

    manifest = build_provekit_artifact_manifest(
        circuit_id="provekit_knowledge_of_axioms",
        circuit_version=2,
        noir_package_path=package,
        prover_key_path=pkp,
        verifier_key_path=pkv,
        provekit_binary_path=binary,
        provekit_branch="v1",
        provekit_commit="4c085f03aa583c255dda4831f1dba7e8c3f284cb",
        hash_backend="sha256",
        ruleset_id="TDFOL_v1",
    )

    assert manifest.schema_version == PROVEKIT_ARTIFACT_MANIFEST_SCHEMA_VERSION
    assert manifest.circuit_ref == "provekit_knowledge_of_axioms@v2"
    assert manifest.prover_key_sha256 == sha256_file(pkp)
    assert manifest.verifier_key_sha256 == sha256_file(pkv)
    assert manifest.noir_package_sha256 == sha256_directory(package)
    assert manifest.provekit_binary_sha256 == sha256_file(binary)
    assert manifest.manifest_sha256() == ProveKitArtifactManifest.from_dict(
        json.loads(manifest.canonical_json())
    ).manifest_sha256()


def test_manifest_round_trip_load_save_and_validate(tmp_path):
    package = _write_noir_package(tmp_path / "pkg")
    pkp, pkv = _write_keys(tmp_path)
    manifest = build_provekit_artifact_manifest(
        circuit_id="provekit_knowledge_of_axioms",
        noir_package_path=package,
        prover_key_path=pkp,
        verifier_key_path=pkv,
        provekit_branch="v1",
        provekit_commit="4c085f03aa583c255dda4831f1dba7e8c3f284cb",
    )
    path = save_provekit_artifact_manifest(manifest, tmp_path / "provekit-artifacts.json")

    loaded = load_provekit_artifact_manifest(path)

    assert loaded == manifest
    loaded.validate_files()
    backend_artifacts = loaded.to_backend_artifacts()["provekit_artifacts"]
    assert backend_artifacts["prover_key_path"] == str(pkp.resolve())
    assert backend_artifacts["verifier_key_path"] == str(pkv.resolve())
    assert backend_artifacts["manifest_sha256"] == manifest.manifest_sha256()


def test_manifest_missing_key_fails_closed(tmp_path):
    package = _write_noir_package(tmp_path / "pkg")
    _, pkv = _write_keys(tmp_path)

    with pytest.raises(ZKPError, match="file does not exist"):
        build_provekit_artifact_manifest(
            circuit_id="provekit_knowledge_of_axioms",
            noir_package_path=package,
            prover_key_path=tmp_path / "missing.pkp",
            verifier_key_path=pkv,
            provekit_branch="v1",
            provekit_commit="4c085f03aa583c255dda4831f1dba7e8c3f284cb",
        )


def test_manifest_mismatched_key_hash_fails_closed(tmp_path):
    package = _write_noir_package(tmp_path / "pkg")
    pkp, pkv = _write_keys(tmp_path)
    manifest = build_provekit_artifact_manifest(
        circuit_id="provekit_knowledge_of_axioms",
        noir_package_path=package,
        prover_key_path=pkp,
        verifier_key_path=pkv,
        provekit_branch="v1",
        provekit_commit="4c085f03aa583c255dda4831f1dba7e8c3f284cb",
    )

    bad_data = manifest.to_dict()
    bad_data["prover_key_sha256"] = "0" * 64
    bad_manifest = ProveKitArtifactManifest.from_dict(bad_data)

    with pytest.raises(ZKPError, match="digest mismatch"):
        bad_manifest.validate_files()


def test_find_provekit_key_pair_prefers_exact_stem(tmp_path):
    other_pkp, other_pkv = _write_keys(tmp_path / "nested", stem="provekit_knowledge_of_axioms_v1")
    exact_pkp, exact_pkv = _write_keys(tmp_path, stem="provekit_knowledge_of_axioms")

    pair = find_provekit_key_pair(
        tmp_path,
        circuit_id="provekit_knowledge_of_axioms",
        circuit_version=1,
    )

    assert pair is not None
    assert pair.prover_key_path == str(exact_pkp.resolve())
    assert pair.verifier_key_path == str(exact_pkv.resolve())
    assert pair.prover_key_path != str(other_pkp.resolve())
    assert pair.verifier_key_path != str(other_pkv.resolve())


def test_find_provekit_key_pair_returns_none_when_absent(tmp_path):
    assert (
        find_provekit_key_pair(
            tmp_path,
            circuit_id="provekit_knowledge_of_axioms",
        )
        is None
    )


def test_find_provekit_key_pair_ambiguous_same_priority_fails_closed(tmp_path):
    _write_keys(tmp_path / "a", stem="provekit_knowledge_of_axioms")
    _write_keys(tmp_path / "b", stem="provekit_knowledge_of_axioms")

    with pytest.raises(ZKPError, match="Ambiguous"):
        find_provekit_key_pair(
            tmp_path,
            circuit_id="provekit_knowledge_of_axioms",
        )
