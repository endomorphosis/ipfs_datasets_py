"""Durable source delivery with tiny real Parquet and DuckDB fixtures.

The source labels and original producer declarations are data. These tests do
not qualify a model, a source authority, a language detector, or a Lean admit.
No network, child process, DuckLake extension, or Hugging Face write is used.
"""
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import shutil

import duckdb
import pytest

from ipfs_datasets_py.duckdb_control import source_corpus_catalog as catalog
from ipfs_datasets_py.logic.autoformal.tree_pin import require_workspace_logic_tree
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_uscode_corpus_export as export
from tests.unit.optimizers.logic_theorem_optimizer.test_autoencoder_uscode_corpus_export import (
    _campaign, _export, _plain, _row, _rows, offline_only,
)


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode()


def _dataset(language="en", **changes):
    return {"namespace": "federal-laws", "source_language": language,
            "jurisdiction": "US", "profile": "uscode-source-export-v1", **changes}


def _identity(value):
    return "sha256:" + hashlib.sha256(_json(value)).hexdigest()


def _version_id(payload):
    dataset_id = _identity({"schema_version": "source-corpus-dataset-v1",
                            "dataset": payload["dataset"]})
    return _identity({"schema_version": "source-corpus-version-v1",
        "dataset_id": dataset_id,
        "release_id": "sha256:" + payload["package_manifest_artifact"]["sha256"],
        "package_manifest_artifact": payload["package_manifest_artifact"]})


@dataclass
class Package:
    report: dict
    expected: list
    original_root: Path

    @property
    def ref(self):
        return {name: self.report["manifest_artifact"][name]
                for name in ("sha256", "bytes")}

    def resolve(self, reference):
        assert reference == self.ref
        return Path(self.report["manifest_artifact"]["path"])

    def payload(self, language="en", **changes):
        return {"dataset": _dataset(language, **changes),
                "package_manifest_artifact": self.ref}


def _package(root, *, campaign=False, rows=None):
    root.mkdir(parents=True)
    case = (_campaign(root / "source") if campaign else
            _plain(root / "source", shards=[rows] if rows is not None else None,
                   with_partitions=True))
    report = _export(case, root / "package", batch_size=2,
                     limits=export.CorpusExportLimits(max_rows_per_file=2))
    return Package(report, _rows(report), root)


def _register(owner, package, operation="register", language="en", **changes):
    return owner.register_export(operation, **package.payload(language, **changes),
                                 package_resolver=package.resolve)


def _no_resolver(*args, **kwargs):
    pytest.fail("durable replay must not reopen an original package resolver")


def _all_rows(owner, version_id, *, limit=2, max_bytes=8 * 1024 * 1024):
    result, after = [], -1
    for _ in range(100):
        page = owner.read_rows(version_id, after_ordinal=after,
                               limit=limit, max_bytes=max_bytes)
        assert page["version_id"] == version_id
        assert page["row_count"] == len(page["rows"]) <= limit
        assert len(_json(page["rows"])) <= max_bytes
        result.extend(page["rows"])
        if page["complete"]:
            assert page["next_after_ordinal"] is None
            return result
        assert page["rows"]
        assert page["next_after_ordinal"] == page["rows"][-1]["ordinal"] > after
        after = page["next_after_ordinal"]
    pytest.fail("pagination did not terminate")


def _expected(package):
    return [{"ordinal": index, **row} for index, row in enumerate(package.expected)]


def _no_authority(receipt):
    for name in ("admitted", "formalized", "source_authority_authenticated",
                 "language_verified", "publication_performed"):
        assert receipt[name] is False


def _files(root):
    return {str(path.relative_to(root)): {
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "bytes": path.stat().st_size,
    } for path in root.rglob("*") if path.is_file()}


@pytest.fixture(autouse=True)
def canonical_tree():
    expected = Path(__file__).resolve().parents[3] / "ipfs_datasets_py"
    assert all(Path(path).is_relative_to(expected)
               for path in require_workspace_logic_tree().values())


def test_full_rows_survive_owner_reopen_and_removal_of_original_package(tmp_path):
    package = _package(tmp_path / "original", campaign=True)
    original_package = Path(package.report["output_directory"])
    original_files = _files(original_package)
    database, owned = tmp_path / "catalog.duckdb", tmp_path / "owned"
    with catalog.SourceCorpusCatalog(database, owned) as owner:
        receipt = _register(owner, package)
        assert receipt["schema_version"] == "source-corpus-registration-v1"
        assert receipt["version_id"] == _version_id(package.payload())
        assert receipt["row_count"] == 6
        assert receipt["package_manifest_artifact"] == package.ref
        assert receipt["verification_scope"] == "registration_time_owned_package_and_materialized_rows"
        assert receipt["current_availability_verified"] is False
        _no_authority(receipt)
        version = owner.get_version(receipt["version_id"])
        assert version["schema_version"] == "source-corpus-version-v1"
        _no_authority(version["qualification"])
        assert version["dataset"] == _dataset()
        owner_package = Path(version["package_directory"])
        assert owner_package.is_relative_to(owned)
        assert owner_package != original_package
        assert _files(owner_package) == original_files
        for relative in original_files:
            copied, original = (owner_package / relative).stat(), (original_package / relative).stat()
            assert copied.st_nlink == 1
            assert (copied.st_dev, copied.st_ino) != (original.st_dev, original.st_ino)
        assert _all_rows(owner, receipt["version_id"]) == _expected(package)
    shutil.rmtree(package.original_root)
    with catalog.SourceCorpusCatalog(database, owned) as owner:
        assert owner.resolve_operation("register", package.payload()) == receipt
        assert owner.register_export("register", **package.payload(),
                                      package_resolver=_no_resolver) == receipt
        assert _all_rows(owner, receipt["version_id"]) == _expected(package)
        verification = owner.verify_version(receipt["version_id"])
        assert verification["schema_version"] == "source-corpus-verification-v1"
        assert verification["current_package_verified"] is True
        assert verification["materialized_rows_verified"] is True
        _no_authority(verification["qualification"])
        assert verification["row_count"] == 6
        assert verification["row_digest"] == receipt["row_digest"]
        actual = _all_rows(owner, receipt["version_id"], limit=1)
        assert [row["embedding_status"] for row in actual] == [
            "embedded", "embedded", "token_limit_exceeded", "missing_input",
            "unattempted", "source_ineligible"]
        assert actual[0]["input_id"] == actual[1]["input_id"]
        assert actual[0]["source_row_id"] != actual[1]["source_row_id"]
        for row in actual:
            assert row["admitted"] is row["formalized"] is False
            assert row["formalization_status"] == "not_observed"
        assert json.loads(actual[0]["record_json"])["admission_status"] == "admitted"


def test_declared_languages_and_releases_keep_distinct_versions_and_share_physical_rows(tmp_path):
    first = _package(tmp_path / "first")
    second = _package(tmp_path / "second", rows=[_row(1, text="Changed source text.")])
    database, owned = tmp_path / "catalog.duckdb", tmp_path / "owned"
    with catalog.SourceCorpusCatalog(database, owned) as owner:
        en = _register(owner, first, "first-en", "en")
        es = _register(owner, first, "first-es", "es")
        revised = _register(owner, second, "second-en", "en")
        assert len({item["version_id"] for item in (en, es, revised)}) == 3
        assert en["dataset_id"] != es["dataset_id"]
        assert en["dataset_id"] == revised["dataset_id"]
        assert en["release_id"] == es["release_id"] != revised["release_id"]
        assert owner.get_version(en["version_id"])["package_directory"] == owner.get_version(es["version_id"])["package_directory"]
        for receipt in (en, es, revised):
            _no_authority(receipt)
        assert _all_rows(owner, en["version_id"]) == _expected(first)
        assert _all_rows(owner, es["version_id"]) == _expected(first)
        assert _all_rows(owner, revised["version_id"]) == _expected(second)
    with duckdb.connect(str(database), read_only=True, config={"threads": 1}) as connection:
        counts = dict(connection.execute("SELECT release_id, count(*) FROM source_corpus.rows GROUP BY release_id").fetchall())
        assert counts == {en["release_id"]: len(first.expected), revised["release_id"]: len(second.expected)}
    with catalog.SourceCorpusCatalog(database, owned) as owner:
        assert owner.get_version(es["version_id"])["dataset"]["source_language"] == "es"
        assert _all_rows(owner, en["version_id"]) == _expected(first)


def test_lost_registration_reply_resolves_without_duplicate_rows_or_source_reads(tmp_path):
    package = _package(tmp_path / "input")
    database, owned = tmp_path / "catalog.duckdb", tmp_path / "owned"
    with catalog.SourceCorpusCatalog(database, owned) as owner:
        assert owner.resolve_operation("register", package.payload()) is None
        def lose_reply():
            _register(owner, package)
            raise ConnectionError("synthetic lost return after committed registration")
        with pytest.raises(ConnectionError, match="lost return"):
            lose_reply()
    shutil.rmtree(package.original_root)
    with catalog.SourceCorpusCatalog(database, owned) as owner:
        receipt = owner.resolve_operation("register", package.payload())
        assert receipt is not None
        assert owner.register_export("register", **package.payload(),
                                      package_resolver=_no_resolver) == receipt
        assert _all_rows(owner, receipt["version_id"]) == _expected(package)
        assert owner.resolve_operation("never-submitted", package.payload()) is None


def test_committed_batches_remain_invisible_until_exact_resume_completes(tmp_path, monkeypatch):
    package = _package(tmp_path / "input", rows=[_row(i) for i in range(1, 6)])
    database, owned = tmp_path / "catalog.duckdb", tmp_path / "owned"
    limits = catalog.SourceCatalogLimits(max_batch_rows=2)
    pending_version = _version_id(package.payload())
    committed = []
    original = catalog.SourceCorpusCatalog._store_batch
    def interrupted(self, release_id, start, rows):
        result = original(self, release_id, start, rows)
        committed.append((release_id, start, len(rows)))
        raise RuntimeError("synthetic owner interruption after a committed batch")
    with catalog.SourceCorpusCatalog(database, owned, limits=limits) as owner:
        with monkeypatch.context() as patch:
            patch.setattr(catalog.SourceCorpusCatalog, "_store_batch", interrupted)
            with pytest.raises(RuntimeError, match="after a committed batch"):
                _register(owner, package)
        assert committed == [(committed[0][0], 0, 2)]
        assert owner.resolve_operation("register", package.payload()) is None
        with pytest.raises(catalog.SourceCorpusCatalogError):
            owner.register_export("register", **package.payload("es"),
                                  package_resolver=_no_resolver)
        with pytest.raises(catalog.SourceCorpusCatalogError):
            owner.get_version(pending_version)
        with pytest.raises(catalog.SourceCorpusCatalogError):
            owner.read_rows(pending_version)
    with duckdb.connect(str(database), read_only=True, config={"threads": 1}) as connection:
        assert connection.execute("SELECT ordinal FROM source_corpus.rows ORDER BY ordinal").fetchall() == [(0,), (1,)]
    shutil.rmtree(package.original_root)
    resumed_limits = catalog.SourceCatalogLimits(max_batch_rows=3)
    with catalog.SourceCorpusCatalog(database, owned, limits=resumed_limits) as owner:
        receipt = owner.register_export("register", **package.payload(),
                                        package_resolver=_no_resolver)
        assert receipt["version_id"] == pending_version
        assert _all_rows(owner, receipt["version_id"]) == _expected(package)
        assert owner.verify_version(receipt["version_id"])["row_digest"] == receipt["row_digest"]
    with duckdb.connect(str(database), read_only=True, config={"threads": 1}) as connection:
        assert connection.execute("SELECT count(*), count(DISTINCT ordinal) FROM source_corpus.rows").fetchone() == (5, 5)


@pytest.mark.parametrize("change", ["language", "package"])
def test_operation_id_cannot_be_rebound_after_commit(tmp_path, change):
    package = _package(tmp_path / "input")
    other = _package(tmp_path / "other", rows=[_row(8)]) if change == "package" else package
    with catalog.SourceCorpusCatalog(tmp_path / "catalog.duckdb", tmp_path / "owned") as owner:
        receipt = _register(owner, package)
        payload = other.payload("es" if change == "language" else "en")
        with pytest.raises(catalog.SourceCorpusCatalogError):
            owner.register_export("register", **payload, package_resolver=other.resolve)
        with pytest.raises(catalog.SourceCorpusCatalogError):
            owner.resolve_operation("register", payload)
        assert owner.resolve_operation("register", package.payload()) == receipt


@pytest.mark.parametrize("change", [
    {"source_language": ""}, {"source_language": True}, {"namespace": ""},
    {"jurisdiction": 1}, {"profile": "constitution-source-export-v1"},
    {"source_authority_authenticated": True},
])
def test_dataset_labels_are_closed_bounded_declarations_before_source_access(tmp_path, change):
    with catalog.SourceCorpusCatalog(tmp_path / "catalog.duckdb", tmp_path / "owned") as owner:
        with pytest.raises(catalog.SourceCorpusCatalogError):
            owner.register_export("register", dataset=_dataset(**change),
                package_manifest_artifact={"sha256": "0" * 64, "bytes": 1},
                package_resolver=_no_resolver)


@pytest.mark.parametrize("reference", [
    {"sha256": "0" * 64, "bytes": True}, {"sha256": "0" * 64, "bytes": 1.0},
    {"sha256": "0" * 63, "bytes": 1},
    {"sha256": "0" * 64, "bytes": 1, "path": "/untrusted"},
])
def test_package_reference_requires_exact_bare_descriptor(tmp_path, reference):
    with catalog.SourceCorpusCatalog(tmp_path / "catalog.duckdb", tmp_path / "owned") as owner:
        with pytest.raises(catalog.SourceCorpusCatalogError):
            owner.register_export("register", dataset=_dataset(),
                package_manifest_artifact=reference, package_resolver=_no_resolver)


def test_owner_package_root_binding_and_second_owner_fail_closed(tmp_path):
    database, owned = tmp_path / "catalog.duckdb", tmp_path / "owned"
    with catalog.SourceCorpusCatalog(database, owned):
        with pytest.raises(catalog.SourceCorpusCatalogError):
            catalog.SourceCorpusCatalog(database, owned)
    with pytest.raises(catalog.SourceCorpusCatalogError):
        catalog.SourceCorpusCatalog(database, tmp_path / "different-owned-root")
    with catalog.SourceCorpusCatalog(database, owned):
        pass


@pytest.mark.parametrize("method", ["resolve_operation", "get_version", "read_rows"])
def test_inherited_owner_cannot_use_parent_connection(tmp_path, monkeypatch, method):
    with catalog.SourceCorpusCatalog(tmp_path / "catalog.duckdb", tmp_path / "owned") as owner:
        pid = os.getpid()
        with monkeypatch.context() as patch:
            patch.setattr(os, "getpid", lambda: pid + 10000)
            with pytest.raises(catalog.SourceCorpusCatalogError):
                if method == "resolve_operation":
                    owner.resolve_operation("unknown", {"dataset": _dataset(),
                        "package_manifest_artifact": {"sha256": "0" * 64, "bytes": 1}})
                else:
                    getattr(owner, method)("sha256:" + "0" * 64)


@pytest.mark.parametrize("sql", [
    "ALTER TABLE source_corpus.rows ADD COLUMN injected_field VARCHAR",
    "CREATE TABLE main.foreign_records (value INTEGER)",
])
def test_reopen_rejects_schema_drift(tmp_path, sql):
    database, owned = tmp_path / "catalog.duckdb", tmp_path / "owned"
    with catalog.SourceCorpusCatalog(database, owned):
        pass
    with duckdb.connect(str(database), config={"threads": 1}) as connection:
        connection.execute(sql)
    with pytest.raises(catalog.SourceCorpusCatalogError):
        catalog.SourceCorpusCatalog(database, owned)


@pytest.mark.parametrize("kwargs", [
    {"limit": 0}, {"limit": True}, {"limit": 257},
    {"after_ordinal": -2}, {"after_ordinal": False},
    {"max_bytes": 0}, {"max_bytes": True},
])
def test_read_bounds_reject_invalid_or_unbounded_requests(tmp_path, kwargs):
    package = _package(tmp_path / "input")
    with catalog.SourceCorpusCatalog(tmp_path / "catalog.duckdb", tmp_path / "owned") as owner:
        receipt = _register(owner, package)
        with pytest.raises(catalog.SourceCorpusCatalogError):
            owner.read_rows(receipt["version_id"], **kwargs)


def test_oversized_first_row_errors_instead_of_returning_nonprogressing_page(tmp_path):
    package = _package(tmp_path / "input", rows=[_row(1, text="é" * 4096), _row(2)])
    with catalog.SourceCorpusCatalog(tmp_path / "catalog.duckdb", tmp_path / "owned") as owner:
        receipt = _register(owner, package)
        with pytest.raises(catalog.SourceCorpusCatalogError):
            owner.read_rows(receipt["version_id"], max_bytes=1024)
        assert _all_rows(owner, receipt["version_id"], limit=1) == _expected(package)
        page = owner.read_rows(receipt["version_id"], after_ordinal=1, limit=1)
        assert page["rows"] == [] and page["complete"] is True
        assert page["next_after_ordinal"] is None


def test_current_verification_rejects_materialized_row_drift(tmp_path):
    package = _package(tmp_path / "input")
    database, owned = tmp_path / "catalog.duckdb", tmp_path / "owned"
    with catalog.SourceCorpusCatalog(database, owned) as owner:
        receipt = _register(owner, package)
    with duckdb.connect(str(database), config={"threads": 1}) as connection:
        connection.execute("UPDATE source_corpus.rows SET text='coherent-looking forged source' WHERE ordinal=0")
    with catalog.SourceCorpusCatalog(database, owned) as owner:
        assert owner.resolve_operation("register", package.payload()) == receipt
        assert receipt["current_availability_verified"] is False
        with pytest.raises(catalog.SourceCorpusCatalogError):
            owner.verify_version(receipt["version_id"])


@pytest.mark.parametrize("target", ["manifest", "query_shard"])
def test_current_verification_rejects_owned_package_byte_drift(tmp_path, target):
    package = _package(tmp_path / "input")
    database, owned = tmp_path / "catalog.duckdb", tmp_path / "owned"
    with catalog.SourceCorpusCatalog(database, owned) as owner:
        receipt = _register(owner, package)
        root = Path(owner.get_version(receipt["version_id"])["package_directory"])
        path = root / ("source-export.json" if target == "manifest"
                       else package.report["row_shards"][0]["relative_path"])
        raw = path.read_bytes()
        path.write_bytes(raw[:-1] + bytes([raw[-1] ^ 1]))
        assert owner.resolve_operation("register", package.payload()) == receipt
        with pytest.raises(catalog.SourceCorpusCatalogError):
            owner.verify_version(receipt["version_id"])


def test_resolver_wrong_bytes_never_exposes_a_version_or_committed_operation(tmp_path):
    package = _package(tmp_path / "input")
    path = Path(package.report["manifest_artifact"]["path"])
    path.write_bytes(path.read_bytes() + b" ")
    with catalog.SourceCorpusCatalog(tmp_path / "catalog.duckdb", tmp_path / "owned") as owner:
        with pytest.raises(catalog.SourceCorpusCatalogError):
            _register(owner, package)
        assert owner.resolve_operation("register", package.payload()) is None


def test_returned_rows_and_metadata_are_detached_from_persistent_identity(tmp_path):
    package = _package(tmp_path / "input")
    with catalog.SourceCorpusCatalog(tmp_path / "catalog.duckdb", tmp_path / "owned") as owner:
        receipt = _register(owner, package)
        version = owner.get_version(receipt["version_id"])
        version["dataset"]["source_language"] = "forged"
        page = owner.read_rows(receipt["version_id"])
        page["rows"][0]["admitted"] = True
        page["rows"][0]["text"] = "forged"
        assert owner.get_version(receipt["version_id"])["dataset"] == _dataset()
        assert _all_rows(owner, receipt["version_id"]) == _expected(package)


@pytest.mark.parametrize("limit", ["max_total_rows", "max_package_bytes"])
def test_registration_budget_failure_does_not_publish_partial_rows(tmp_path, limit):
    package = _package(tmp_path / "input")
    limits = catalog.SourceCatalogLimits(**{limit: 1})
    with catalog.SourceCorpusCatalog(tmp_path / "catalog.duckdb", tmp_path / "owned", limits=limits) as owner:
        with pytest.raises(catalog.SourceCorpusCatalogError):
            _register(owner, package)
        assert owner.resolve_operation("register", package.payload()) is None


@pytest.mark.parametrize(("missing", "after", "limit"), [
    pytest.param(1, -1, 2, id="last-ordinal-in-nonfinal-window"),
    pytest.param(4, 2, 2, id="last-ordinal-at-real-end"),
])
def test_short_ordinal_windows_reject_missing_rows(tmp_path, missing, after, limit):
    package = _package(tmp_path / "input", rows=[_row(i) for i in range(1, 6)])
    database, owned = tmp_path / "catalog.duckdb", tmp_path / "owned"
    with catalog.SourceCorpusCatalog(database, owned) as owner:
        receipt = _register(owner, package)
    # Keep the committed release/operation/checkpoint evidence intact. Only
    # remove a physical row so a short SQL window must not look like a valid
    # continuation or a completed release.
    with duckdb.connect(str(database), config={"threads": 1}) as connection:
        connection.execute("DELETE FROM source_corpus.rows WHERE release_id=? AND ordinal=?",
                           [receipt["release_id"], missing])
    with catalog.SourceCorpusCatalog(database, owned) as owner:
        assert owner.resolve_operation("register", package.payload()) == receipt
        with pytest.raises(catalog.SourceCorpusCatalogError):
            owner.read_rows(receipt["version_id"], after_ordinal=after, limit=limit)
        # The private bounded reader still supplies the independent full
        # readback check; SQL range narrowing must preserve its failure.
        with pytest.raises(catalog.SourceCorpusCatalogError):
            owner.verify_version(receipt["version_id"])


def test_byte_capped_short_windows_continue_without_losing_or_duplicating_rows(tmp_path):
    package = _package(tmp_path / "input", rows=[_row(i) for i in range(1, 6)])
    expected = _expected(package)
    budget = max(len(_json([row])) for row in expected)
    assert all(len(_json(expected[index:index + 2])) > budget
               for index in range(len(expected) - 1))
    with catalog.SourceCorpusCatalog(tmp_path / "catalog.duckdb", tmp_path / "owned") as owner:
        receipt = _register(owner, package)
        first = owner.read_rows(receipt["version_id"], limit=3, max_bytes=budget)
        assert first["rows"] == expected[:1]
        assert first["row_count"] == 1 and first["complete"] is False
        assert first["next_after_ordinal"] == 0
        assert _all_rows(owner, receipt["version_id"], limit=3, max_bytes=budget) == expected
        assert owner.verify_version(receipt["version_id"])["row_digest"] == receipt["row_digest"]
