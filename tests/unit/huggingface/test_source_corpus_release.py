"""Offline source-plan binding; no live catalog, Hub, model or process work."""
from copy import deepcopy
from dataclasses import fields, replace
import hashlib
import json
from pathlib import Path
import shutil

import pytest

from ipfs_datasets_py.duckdb_control import source_corpus_catalog as catalog
from ipfs_datasets_py.duckdb_control import source_corpus_binding as binding_module
from ipfs_datasets_py.huggingface import source_corpus_release as release
from ipfs_datasets_py.huggingface.publication_profile import BASE_PROHIBITED_OPERATIONS
from ipfs_datasets_py.huggingface.publisher import HuggingFaceReleasePublisher, PublicationPlan
from tests.unit.duckdb_control.test_source_corpus_catalog import _package, _dataset, canonical_tree
from tests.unit.optimizers.logic_theorem_optimizer.test_autoencoder_uscode_corpus_export import offline_only


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode()


def _sha(value):
    return hashlib.sha256(value).hexdigest()


def _ids(version):
    dataset_id, release_id, version_id = catalog._identities({
        "dataset": version["dataset"], "package_manifest_artifact": version["package_manifest_artifact"]})
    version.update(dataset_id=dataset_id, release_id=release_id, version_id=version_id)
    return version


def _fixture(root, *, campaign=True):
    package = _package(root, campaign=campaign)
    digest = hashlib.sha256()
    for ordinal, row in enumerate(package.expected):
        digest.update(_json({"ordinal": ordinal, **row}) + b"\n")
    version = _ids({"schema_version": "source-corpus-version-v1", "dataset": _dataset(),
        "package_manifest_artifact": package.ref,
        "package_directory": "/historical-unavailable-owner/packages/" + package.ref["sha256"],
        "row_count": len(package.expected), "row_digest": digest.hexdigest(),
        "qualification": dict.fromkeys(("admitted", "formalized", "source_authority_authenticated",
                                        "language_verified", "publication_performed"), False)})
    return package, version


def _plan(package, version, **changes):
    return release.plan_source_corpus_release(version, package.report["output_directory"],
        **{"repository_id": "example/source-corpus", "audited_parent_commit": "a" * 40, **changes})


def _forbidden(*args, **kwargs):
    pytest.fail("source planning must not open a catalog or contact publication/download methods")


@pytest.fixture(autouse=True)
def no_catalog_or_publication(monkeypatch):
    monkeypatch.setattr(catalog.SourceCorpusCatalog, "__init__", _forbidden)
    for name in ("publish_append_only", "verify_post_publication", "redownload_and_validate_pinned",
                 "inventory_remote_objects_at_commit", "canary_promote_pointer"):
        monkeypatch.setattr(HuggingFaceReleasePublisher, name, _forbidden)


def test_complete_source_package_plan_preserves_exact_bytes_schema_and_false_authority(tmp_path, monkeypatch):
    package, version = _fixture(tmp_path / "input")
    original_version = deepcopy(version)
    manifest = json.loads(Path(package.report["manifest_artifact"]["path"]).read_bytes())
    expected = {item["relative_path"]: (item["sha256"], item["bytes"]) for item in manifest["files"]}
    expected["source-export.json"] = (package.ref["sha256"], package.ref["bytes"])
    observed = []
    original = HuggingFaceReleasePublisher.plan_dry_run
    def inspect(self, manifest, **kwargs):
        assert self.api is None
        observed.append(deepcopy(manifest))
        return original(self, manifest, **kwargs)
    monkeypatch.setattr(HuggingFaceReleasePublisher, "plan_dry_run", inspect)
    result = _plan(package, version)
    assert result["schema_version"] == "source-corpus-hf-release-plan-v1"
    assert version == original_version
    assert len(observed) == 1
    assert all("size_bytes" in item and "bytes" not in item for item in observed[0]["files"])
    plan = result["publication_plan"]
    assert plan["schema_version"] == "source-corpus-hf-publication-plan/v1"
    assert plan["repository_type"] == "dataset"
    assert plan["repository_id"] == "example/source-corpus"
    assert plan["release_id"] == version["version_id"].replace(":", "-")
    assert plan["release_sha256"] == package.ref["sha256"]
    assert {item["relative_path"]: (item["sha256"], item["size_bytes"])
            for item in plan["operations"]} == expected
    assert plan["upload_file_count"] == result["file_count"] == len(expected)
    assert plan["upload_bytes"] == result["total_bytes"] == sum(size for _, size in expected.values())
    assert plan["existing_remote_paths"] == plan["skipped_exact_matches"] == []
    assert all(item["operation"] == "add" and item["remote_path"] == plan["release_prefix"] + "/" + item["relative_path"]
               for item in plan["operations"])
    assert BASE_PROHIBITED_OPERATIONS <= set(plan["prohibited_operations"])
    assert result["source_version"] == {key: value for key, value in version.items() if key != "package_directory"}
    assert plan["metadata"]["source_version"] == result["source_version"]
    assert plan["metadata"]["dataset_config"] == plan["metadata"]["physical_dataset_split"] == "corpus"
    assert plan["metadata"]["source_partition_column"] == "split"
    assert plan["metadata"]["source_export_manifest_included"] is True
    assert plan["metadata"]["canonical_release_manifest_included"] is False
    assert plan["metadata"]["root_dataset_card_publication"] == "separate_reviewed_bootstrap_or_cas_required"
    for name, value in result["qualification"].items():
        assert value is (name in {"package_verified", "source_version_binding_verified"})
        assert plan["metadata"][name] is value
    encoded = _json(result).decode()
    assert str(tmp_path) not in encoded and version["package_directory"] not in encoded
    assert "abby" not in encoded.casefold()
    assert plan["dry_run"] is True and plan["remote_write_contacted"] is False
    # Recompute the existing generic plan digest, including our source binding.
    field_names = {field.name for field in fields(PublicationPlan)}
    values = {key: value for key, value in plan.items() if key in field_names}
    from ipfs_datasets_py.huggingface.publisher import PublicationFilePlan
    values["operations"] = tuple(PublicationFilePlan(**item) for item in plan["operations"])
    assert PublicationPlan(**values).plan_digest == plan["plan_digest"]


def test_relocation_does_not_change_plan_and_never_reads_old_catalog_paths(tmp_path):
    package, version = _fixture(tmp_path / "input")
    first = _plan(package, version)
    moved = tmp_path / "relocated-package"
    Path(package.report["output_directory"]).rename(moved)
    shutil.rmtree(package.original_root)
    second = release.plan_source_corpus_release(version, moved,
        repository_id="example/source-corpus", audited_parent_commit="a" * 40)
    assert second == first


@pytest.mark.parametrize("change", ["source_language", "namespace", "jurisdiction", "repository"])
def test_declared_labels_and_destination_are_bound_to_plan_identity(tmp_path, change):
    package, version = _fixture(tmp_path / "input", campaign=False)
    baseline = _plan(package, version)
    changed = deepcopy(version)
    options = {}
    if change == "repository":
        options["repository_id"] = "example/another-source-corpus"
    else:
        changed["dataset"][change] = {"source_language": "es", "namespace": "other-corpus", "jurisdiction": "US-FED"}[change]
        _ids(changed)
    result = _plan(package, changed, **options)
    assert result["publication_plan"]["plan_digest"] != baseline["publication_plan"]["plan_digest"]
    before = baseline["publication_plan"]["operations"]
    after = result["publication_plan"]["operations"]
    assert [(row["relative_path"], row["sha256"], row["size_bytes"]) for row in before] == [
        (row["relative_path"], row["sha256"], row["size_bytes"]) for row in after]
    assert result["qualification"]["language_verified"] is False


@pytest.mark.parametrize("change", [
    "extra_field", "missing_field", "dataset_id", "release_id", "version_id", "row_count_bool",
    "row_digest_shape", "admitted", "numeric_false", "ref_bytes_float", "historical_relative_path",
])
def test_invalid_captured_version_fails_before_package_access(tmp_path, monkeypatch, change):
    package, version = _fixture(tmp_path / "input", campaign=False)
    if change == "extra_field":
        version["unexpected"] = True
    elif change == "missing_field":
        version.pop("dataset")
    elif change in {"dataset_id", "release_id", "version_id"}:
        version[change] = "sha256:" + "0" * 64
    elif change == "row_count_bool":
        version["row_count"] = True
    elif change == "row_digest_shape":
        version["row_digest"] = "not-a-digest"
    elif change == "admitted":
        version["qualification"]["admitted"] = True
    elif change == "numeric_false":
        version["qualification"]["formalized"] = 0
    elif change == "ref_bytes_float":
        version["package_manifest_artifact"]["bytes"] = float(version["package_manifest_artifact"]["bytes"])
    else:
        version["package_directory"] = "historical/relative/path"
    monkeypatch.setattr(release.export, "_directory", _forbidden)
    with pytest.raises(release.SourceCorpusReleaseError):
        _plan(package, version)


@pytest.mark.parametrize("change", ["row_count", "row_digest"])
def test_well_formed_but_wrong_row_summary_rejects_exact_package(tmp_path, change):
    package, version = _fixture(tmp_path / "input", campaign=False)
    version[change] = version[change] + 1 if change == "row_count" else "0" * 64
    with pytest.raises(release.SourceCorpusReleaseError, match="source rows differ"):
        _plan(package, version)


@pytest.mark.parametrize("change", ["missing", "modified", "extra", "symlink", "root_symlink"])
def test_missing_changed_aliased_or_extra_package_files_are_rejected(tmp_path, change):
    package, version = _fixture(tmp_path / "input", campaign=False)
    root = Path(package.report["output_directory"])
    path = root / package.report["row_shards"][0]["relative_path"]
    if change == "missing":
        path.unlink()
    elif change == "modified":
        raw = path.read_bytes()
        path.write_bytes(raw[:-1] + bytes([raw[-1] ^ 1]))
    elif change == "extra":
        (root / "unlisted.txt").write_bytes(b"unlisted")
    elif change == "symlink":
        outside = tmp_path / "outside.parquet"
        path.rename(outside)
        path.symlink_to(outside)
    else:
        alias = tmp_path / "alias"
        alias.symlink_to(root, target_is_directory=True)
        package.report["output_directory"] = str(alias)
    with pytest.raises(release.SourceCorpusReleaseError):
        _plan(package, version)


@pytest.mark.parametrize("change", ["mutate_file", "remove_file", "add_file", "drop_operation"])
def test_planning_boundary_rechecks_source_bytes_and_exact_operation_closure(tmp_path, monkeypatch, change):
    package, version = _fixture(tmp_path / "input", campaign=False)
    root = Path(package.report["output_directory"])
    path = root / "README.md"
    original = HuggingFaceReleasePublisher.plan_dry_run
    def alter(self, manifest, **kwargs):
        plan = original(self, manifest, **kwargs)
        if change == "mutate_file":
            raw = path.read_bytes()
            path.write_bytes(raw[:-1] + bytes([raw[-1] ^ 1]))
        elif change == "remove_file":
            path.unlink()
        elif change == "add_file":
            (root / "racing-extra.txt").write_bytes(b"not listed")
        else:
            plan = replace(plan, operations=plan.operations[:-1])
        return plan
    monkeypatch.setattr(HuggingFaceReleasePublisher, "plan_dry_run", alter)
    with pytest.raises(release.SourceCorpusReleaseError):
        _plan(package, version)


@pytest.mark.parametrize("repository", ["", "missing-namespace", "org/../repo", "org/repo/subdir", True])
def test_profile_requires_explicit_safe_dataset_destination(repository):
    with pytest.raises(release.SourceCorpusReleaseError):
        release.source_corpus_publication_profile(repository)


def test_declared_parent_is_bound_without_claiming_remote_verification(tmp_path):
    package, version = _fixture(tmp_path / "input", campaign=False)
    first = _plan(package, version, audited_parent_commit="")
    second = _plan(package, version, audited_parent_commit="b" * 40)
    assert first["publication_plan"]["plan_digest"] != second["publication_plan"]["plan_digest"]
    assert second["publication_plan"]["audited_parent_commit"] == "b" * 40
    assert second["qualification"]["remote_parent_verified"] is False
    with pytest.raises(release.SourceCorpusReleaseError):
        _plan(package, version, audited_parent_commit="main")


def test_shared_binding_exposes_detached_metadata_and_independent_ordered_passes(tmp_path):
    package, version = _fixture(tmp_path / "input")
    expected_version = {key: value for key, value in version.items() if key != "package_directory"}
    expected_rows = [{"ordinal": index, **row} for index, row in enumerate(package.expected)]
    with binding_module.SourceCorpusBinding(version, package.report["output_directory"]) as binding:
        assert binding.source_version == expected_version
        assert binding.manifest_artifact == package.ref
        assert binding.package_root == Path(package.report["output_directory"])
        assert binding.file_count == len(binding.file_descriptors)
        assert binding.total_bytes == sum(row["bytes"] for row in binding.file_descriptors)
        exposed = binding.source_version
        exposed["dataset"]["source_language"] = "forged"
        descriptors = binding.file_descriptors
        descriptors[0]["bytes"] = 1
        manifest = binding.manifest
        manifest["files"].clear()
        assert binding.source_version == expected_version
        assert binding.file_descriptors != descriptors
        assert binding.manifest["files"]
        first = list(binding.iter_rows())
        assert first == expected_rows
        first[0]["admitted"] = True
        assert list(binding.iter_rows()) == expected_rows
        assert binding.row_count == len(expected_rows)
        assert binding.row_digest == version["row_digest"]
        assert binding.verify_current() is None


@pytest.mark.parametrize("boundary", ["thread", "process", "closed", "reenter"])
def test_shared_binding_rejects_foreign_owner_expiry_and_reentry(tmp_path, monkeypatch, boundary):
    package, version = _fixture(tmp_path / "input", campaign=False)
    binding = binding_module.SourceCorpusBinding(version, package.report["output_directory"])
    with binding:
        if boundary == "closed":
            binding.close()
            with pytest.raises(binding_module.SourceCorpusBindingError):
                binding.iter_rows()
        elif boundary == "reenter":
            with pytest.raises(binding_module.SourceCorpusBindingError):
                binding.__enter__()
        else:
            module, name = ((binding_module.threading, "get_ident") if boundary == "thread"
                            else (binding_module.os, "getpid"))
            original = getattr(module, name)()
            with monkeypatch.context() as patch:
                patch.setattr(module, name, lambda: original + 1)
                with pytest.raises(binding_module.SourceCorpusBindingError):
                    binding.verify_current()
    with pytest.raises(binding_module.SourceCorpusBindingError):
        binding.__enter__()


def test_shared_row_iterator_rechecks_nonrow_evidence_on_exhaustion(tmp_path):
    package, version = _fixture(tmp_path / "input", campaign=False)
    root = Path(package.report["output_directory"])
    with binding_module.SourceCorpusBinding(version, root) as binding:
        iterator = binding.iter_rows()
        assert next(iterator)["ordinal"] == 0
        (root / "README.md").write_bytes(b"changed source evidence")
        with pytest.raises(binding_module.SourceCorpusBindingError):
            list(iterator)
        with pytest.raises(binding_module.SourceCorpusBindingError):
            binding.verify_current()


def test_detached_version_validation_has_no_filesystem_dependency(tmp_path, monkeypatch):
    _, version = _fixture(tmp_path / "input", campaign=False)
    detached = {key: value for key, value in version.items() if key != "package_directory"}
    monkeypatch.setattr(binding_module.export, "_directory", _forbidden)
    normalized = binding_module.validate_source_version(detached)
    assert normalized == detached
    normalized["dataset"]["source_language"] = "changed"
    assert detached["dataset"]["source_language"] == "en"
    with pytest.raises(binding_module.SourceCorpusBindingError):
        binding_module.validate_source_version(version)


def test_binding_alias_entry_uses_public_error_and_cleans_up(tmp_path, monkeypatch):
    package, version = _fixture(tmp_path / "input", campaign=False)
    root = Path(package.report["output_directory"])
    alias = tmp_path / "alias"
    alias.symlink_to(root, target_is_directory=True)
    monkeypatch.setattr(binding_module.export, "verify_uscode_source_export", _forbidden)
    binding = binding_module.SourceCorpusBinding(version, alias)
    with pytest.raises(binding_module.SourceCorpusBindingError, match="alias"):
        binding.__enter__()
    assert binding._fd is None
    with pytest.raises(binding_module.SourceCorpusBindingError, match="cannot be reused"):
        binding.__enter__()


def test_live_binding_rejects_shard_and_root_aliases_with_public_error(tmp_path):
    package, version = _fixture(tmp_path / "input", campaign=False)
    root = Path(package.report["output_directory"])
    with binding_module.SourceCorpusBinding(version, root) as binding:
        iterator = binding.iter_rows()
        parent = root / "data" / "source_rows"
        moved = tmp_path / "moved-shards"
        parent.rename(moved)
        parent.symlink_to(moved, target_is_directory=True)
        with pytest.raises(binding_module.SourceCorpusBindingError, match="alias"):
            next(iterator)
        iterator.close()
        moved_root = tmp_path / "moved-package"
        root.rename(moved_root)
        root.symlink_to(moved_root, target_is_directory=True)
        with pytest.raises(binding_module.SourceCorpusBindingError, match="alias"):
            binding.source_version
        with pytest.raises(binding_module.SourceCorpusBindingError, match="alias"):
            binding.verify_current()
    assert binding._fd is None
