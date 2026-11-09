"""Stateless paired intake uses real v1/v2 tables and no durable feed owner."""
from pathlib import Path
import shutil

import pyarrow.parquet as pq
import pytest

from ipfs_datasets_py.logic.autoformal import paired_span_census as paired
from ipfs_datasets_py.logic.autoformal import span_cache_feed as feed
from tests.unit.logic.test_span_cache_paired_feed import (
    build_fixture, digest, serialize_fixture, source_row,
)


def staged(tmp_path, version=2, **fixture_options):
    bundle = build_fixture(version, **fixture_options)
    entry, files, manifest = serialize_fixture(tmp_path / "producer", bundle, version=version)
    root = tmp_path / "retained" / ("a" * 40)
    for relative, original in files.items():
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(original, target)
    return root, root / entry["path"], manifest, bundle


def load(root, manifest_path, manifest, **overrides):
    options = {"repository_root": root, "repository_id": paired.REPOSITORY,
               "path_in_repo": manifest["path_in_repo"],
               "expected_manifest_sha256": digest(manifest_path.read_bytes()),
               "max_bytes": 64 * 1024 * 1024, "max_rows": 128,
               "max_decoded_bytes": 64 * 1024 * 1024}
    options.update(overrides)
    return feed.load_paired_payload(manifest_path, **options)


@pytest.mark.parametrize("version", [1, 2])
def test_stateless_payload_preserves_exact_strict_owner_result(tmp_path, version):
    root, manifest_path, manifest, original = staged(tmp_path, version)
    actual = load(root, manifest_path, manifest)
    strict = paired.load_paired_census_bundle(manifest_path)
    assert {key: actual[key] for key in strict} == strict
    assert actual["paired_spans"] == original["paired_spans"]
    assert actual["goals"] == original["goals"]
    assert actual["fingerprint"] == manifest["fingerprint"]
    assert actual["decoded_bytes"] > 0
    assert actual["admitted"] is actual["formalized"] is actual["enqueued"] is False
    assert not list(tmp_path.rglob("*.duckdb"))
    assert load(root, manifest_path, manifest, expected_manifest_sha256=None) == actual


def test_wrong_independent_manifest_pin_refuses_before_any_table_read(tmp_path):
    root, manifest_path, manifest, _ = staged(tmp_path)
    for descriptor in manifest["tables"].values():
        (root / descriptor["path_in_repo"]).unlink()
    with pytest.raises(feed.FeedError, match="expected SHA256"):
        load(root, manifest_path, manifest, expected_manifest_sha256="0" * 64)


@pytest.mark.parametrize("pin", ["", "0" * 63, "A" * 64, True, 7])
def test_invalid_manifest_pin_refuses_without_reading_payload(tmp_path, pin):
    with pytest.raises(feed.FeedError, match="lowercase digest"):
        feed.load_paired_payload(tmp_path / "missing", repository_root=tmp_path,
            repository_id=paired.REPOSITORY,
            path_in_repo="autoformal/uscode/paired-v2/manifests/fixture/manifest-" + "a" * 64 + ".json",
            expected_manifest_sha256=pin, max_bytes=1024, max_rows=1, max_decoded_bytes=1024)


@pytest.mark.parametrize("name", ["max_bytes", "max_rows", "max_decoded_bytes"])
@pytest.mark.parametrize("value", [0, -1, True, 1.5, "1", None])
def test_bounds_require_positive_integers_before_filesystem_reads(tmp_path, name, value):
    options = {"max_bytes": 1024, "max_rows": 1, "max_decoded_bytes": 1024}
    options[name] = value
    with pytest.raises(feed.FeedError, match=name + " must be a positive integer"):
        feed.load_paired_payload(tmp_path / "missing", repository_root=tmp_path,
            repository_id=paired.REPOSITORY, path_in_repo="missing", **options)


@pytest.mark.parametrize("mutation", ["relative_root", "wrong_root", "root_symlink", "manifest_symlink"])
def test_exact_absolute_manifest_layout_is_required(tmp_path, mutation):
    root, manifest_path, manifest, _ = staged(tmp_path)
    options = {}
    if mutation == "relative_root":
        options["repository_root"] = Path("relative-root")
    elif mutation == "wrong_root":
        alternate = tmp_path / "wrong-root"
        alternate.mkdir()
        options["repository_root"] = alternate
    elif mutation == "root_symlink":
        alias = tmp_path / "alias"
        alias.symlink_to(root, target_is_directory=True)
        options["repository_root"] = alias
        manifest_path = alias / manifest["path_in_repo"]
    else:
        original = manifest_path.with_suffix(".retained")
        manifest_path.rename(original)
        manifest_path.symlink_to(original)
    with pytest.raises(feed.FeedError, match="absolute nonsymlink|repository layout"):
        load(root, manifest_path, manifest, **options)


@pytest.mark.parametrize("mutation", ["repository", "path", "traversal"])
def test_manifest_selection_is_bound_before_payload_reads(tmp_path, mutation):
    root, manifest_path, manifest, _ = staged(tmp_path)
    for descriptor in manifest["tables"].values():
        (root / descriptor["path_in_repo"]).unlink()
    if mutation == "repository":
        options = {"repository_id": "different/repository"}
    elif mutation == "path":
        options = {"path_in_repo": manifest["path_in_repo"].replace("paired-one", "another-agent")}
    else:
        options = {"path_in_repo": "../" + manifest["path_in_repo"]}
    with pytest.raises(feed.FeedError, match="binding differs|repository layout|relative repository path"):
        load(root, manifest_path, manifest, **options)


@pytest.mark.parametrize("kind", paired.TABLE_NAMES)
def test_exact_table_bytes_are_required(tmp_path, kind):
    root, manifest_path, manifest, _ = staged(tmp_path)
    path = root / manifest["tables"][kind]["path_in_repo"]
    original = path.read_bytes()
    path.write_bytes(bytes([original[0] ^ 1]) + original[1:])
    with pytest.raises(feed.FeedError, match="table size or hash differs"):
        load(root, manifest_path, manifest)


@pytest.mark.parametrize("alias_parent", [False, True])
def test_payload_file_or_parent_alias_cannot_escape_layout(tmp_path, alias_parent):
    root, manifest_path, manifest, _ = staged(tmp_path)
    table = root / manifest["tables"]["paired_spans"]["path_in_repo"]
    target = table.parent if alias_parent else table
    retained = target.with_name(target.name + ".retained")
    target.rename(retained)
    target.symlink_to(retained, target_is_directory=alias_parent)
    with pytest.raises(feed.FeedError, match="filesystem alias"):
        load(root, manifest_path, manifest)


def forbidden_full_loader(*args, **kwargs):
    raise AssertionError("full loader must not run after preflight exceeds a budget")


def test_compressed_population_bound_precedes_full_loader(tmp_path, monkeypatch):
    root, manifest_path, manifest, _ = staged(tmp_path)
    budget = len(manifest_path.read_bytes()) + manifest["tables"]["paired_spans"]["bytes"] - 1
    monkeypatch.setattr(paired, "load_paired_census_bundle", forbidden_full_loader)
    with pytest.raises(feed.FeedError, match="compressed size exceeds bound"):
        load(root, manifest_path, manifest, max_bytes=budget)


def test_aggregate_arrow_bound_precedes_full_loader(tmp_path, monkeypatch):
    root, manifest_path, manifest, _ = staged(tmp_path)
    sizes = []
    for descriptor in manifest["tables"].values():
        parquet = pq.ParquetFile(root / descriptor["path_in_repo"])
        sizes.append(sum(parquet.metadata.row_group(i).total_byte_size
                         for i in range(parquet.metadata.num_row_groups)))
    # Every individual table fits; the complete population does not.
    budget = len(manifest_path.read_bytes()) + max(sizes)
    monkeypatch.setattr(paired, "load_paired_census_bundle", forbidden_full_loader)
    with pytest.raises(feed.FeedError, match="aggregate Arrow allocation"):
        load(root, manifest_path, manifest, max_decoded_bytes=budget)


def test_artifact_expansion_bound_precedes_full_loader(tmp_path, monkeypatch):
    root, manifest_path, manifest, _ = staged(tmp_path, receipt_extra="x" * 100_000)
    monkeypatch.setattr(paired, "load_paired_census_bundle", forbidden_full_loader)
    with pytest.raises(feed.FeedError, match="artifact expansion exceeds ready bound"):
        load(root, manifest_path, manifest, max_decoded_bytes=20_000)


def test_row_population_bound_precedes_full_loader(tmp_path, monkeypatch):
    root, manifest_path, manifest, _ = staged(tmp_path,
        rows=[source_row("first"), source_row("second")])
    monkeypatch.setattr(paired, "load_paired_census_bundle", forbidden_full_loader)
    with pytest.raises(feed.FeedError, match="schema or row count exceeds bound"):
        load(root, manifest_path, manifest, max_rows=1)
