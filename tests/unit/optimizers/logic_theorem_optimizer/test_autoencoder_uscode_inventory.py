"""Offline source inventory and exact materialization; no model/parser execution."""
from dataclasses import dataclass, replace
import hashlib
import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_uscode_import as imp
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_uscode_inventory as inv
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_embedding_production import (
    EmbeddingInput, validate_embedding_inputs,
)
from ipfs_datasets_py.processors.legal_data.uscode_identity import LegalIdentity


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode("utf-8")


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _row(index=1, **changes):
    row = {"entry_cid": "sha256:" + f"{index:064x}", "legal_id": f"usc:us:5:{index}", "family": "corpus",
        "title": "5", "section": str(index), "admission_status": "admitted",
        "admission_reason": "synthetic published retrieval inclusion", "release_point": "us/pl/119/102",
        "source_checksum": "b" * 64, "source_cid": "b" * 64, "verification_result": "verified",
        "acquisition_time": "2026-09-08T22:59:35Z", "text": f"  § {index}. The agency shall retain café records.\n",
        "chapter": None, "subsection": None, "document_index": index,
        "official_source_url": f"https://uscode.house.gov/{index}", "package_id": None,
        "granule_id": None, "effective_date": None, "observed_at": None,
        "schema_version": imp.RELEASE_SCHEMA}
    row.update(changes)
    return row


def _wrapper(row):
    raw = _json(row)
    return {"entry_cid": row["entry_cid"], "legal_id": row.get("legal_id") or "",
            "family": row["family"], "record_sha256": _sha(raw), "record_json": raw.decode()}


@dataclass
class _ReleaseFixture:
    release: imp.USCodeRelease
    manifest_path: Path
    root: dict
    shards: tuple[Path, ...]
    descriptors: tuple[dict, ...]
    paths: dict

    def resolve(self, reference):
        return self.paths[reference["sha256"]]


def _release(tmp_path, shard_rows=None, *, wrapper_change=None, import_limits=None, extra_artifacts=()):
    """Create an independently sealed multi-shard source-only release."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    shard_rows = shard_rows if shard_rows is not None else [[_row(1), _row(2)], [_row(3)]]
    paths, shards, descriptors = {}, [], []
    for index, rows in enumerate(shard_rows):
        wrappers = [_wrapper(row) for row in rows]
        if wrapper_change is not None:
            wrapper_change(index, wrappers)
        path = tmp_path / f"source-{index:06d}.parquet"
        table = pa.Table.from_pylist(wrappers, schema=pa.schema([(name, pa.string()) for name in imp.WRAPPER_COLUMNS]))
        pq.write_table(table, path, compression="zstd")
        raw = path.read_bytes()
        descriptor = {"relative_path": f"data/corpus/part-{index:06d}.parquet", "family": "corpus",
            "sha256": _sha(raw), "size_bytes": len(raw), "row_count": len(rows),
            "schema_id": "uscode-corpus-row/v1", "media_type": "application/vnd.apache.parquet"}
        descriptors.append(descriptor)
        paths[descriptor["sha256"]] = path
        shards.append(path)
    manifest = {"schema_version": imp.RELEASE_SCHEMA, "release_profile": imp.RELEASE_PROFILE,
        "dataset_repo_id": "justicedao/ipfs_uscode", "default_excludes_recovery": True,
        "artifacts": [*descriptors, *extra_artifacts], "model_id": "thenlper/gte-small",
        "model_revision": "a" * 40, "vector_space_id": "synthetic-unused-vectors:d384",
        "release_point": "us/pl/119/102", "source_revision": "c" * 40}
    manifest["manifest_digest"] = _sha(_json(manifest))
    raw = _json(manifest) + b"\n"
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_bytes(raw)
    root = {"path": str(manifest_path), "sha256": _sha(raw), "bytes": len(raw)}
    paths[root["sha256"]] = manifest_path
    release = imp.load_uscode_release(root, repo_id="justicedao/ipfs_uscode", revision="d" * 40,
                                     limits=import_limits or imp.USCodeImportLimits())
    return _ReleaseFixture(release, manifest_path, root, tuple(shards), tuple(descriptors), paths)


def _build(fixture, **kwargs):
    return inv.build_uscode_source_inventory(fixture.release, resolver=fixture.resolve, **kwargs)


def _rows(inventory):
    return [row for shard in inventory.to_dict()["shards"] for row in shard["rows"]]


_DEFAULT_SELECTION = object()


def _materialize(inventory, fixture, destination, entry_cids=_DEFAULT_SELECTION):
    ids = [_row(1)["entry_cid"], _row(3)["entry_cid"]] if entry_cids is _DEFAULT_SELECTION else entry_cids
    return inv.materialize_uscode_inventory_inputs(inventory, ids, destination,
        release=fixture.release, resolver=fixture.resolve)


def test_complete_inventory_covers_every_declared_physical_row_without_text_or_vectors(tmp_path):
    fixture = _release(tmp_path)
    inventory = _build(fixture, batch_size=1)
    summary = inventory.summary()
    assert summary["complete"] is True
    assert summary["declared_corpus_closure_verified"] is True
    assert summary["grouping_metadata_complete"] is True
    assert summary["declared_row_count"] == summary["rows_scanned"] == 3
    assert summary["eligible_input_count"] == 3
    assert summary["status_counts"] == {"ready_published_text": 3}
    for name in ("training_eligible", "source_authority_authenticated", "original_official_source_bytes_verified",
                 "full_federal_corpus_complete", "global_holdout_verified", "admitted"):
        assert summary[name] is False
    payload = inventory.to_dict()
    assert payload["scope"] == "declared_corpus_family_only"
    assert len(payload["shards"]) == 2
    for shard, descriptor in zip(payload["shards"], fixture.descriptors):
        assert shard["status"] == "verified"
        assert shard["artifact"]["relative_path"] == descriptor["relative_path"]
        assert shard["rows_scanned"] == descriptor["row_count"]
        assert [row["row_index"] for row in shard["rows"]] == list(range(descriptor["row_count"]))
    raw = inventory.to_bytes()
    assert _row(1)["text"].encode() not in raw
    assert b"The agency shall retain" not in raw
    assert b'"embedding_vector"' not in raw and b'"record_json"' not in raw
    assert inventory.sha256 == _sha(raw)
    for row, original in zip(_rows(inventory), (_row(1), _row(2), _row(3))):
        metadata = row["metadata"]
        assert row["wrapper_verified"] is True
        assert row["duplicate_entry_cid"] is False
        assert row["status"] == row["original_status"] == "ready_published_text"
        assert metadata["record_sha256"] == _sha(_json(original))
        assert metadata["text_sha256"] == _sha(original["text"].encode())
        assert metadata["text_bytes"] == len(original["text"].encode())
        assert metadata["normalized_content_sha256"] == _sha(" ".join(original["text"].split()).casefold().encode())
        assert metadata["canonical_identity"]["document_id"] == original["legal_id"]
        citation = f"5 U.S.C. § {original['section']}"
        expected_input = {"schema": "source-embedding-input-v1", "title": "5", "section": original["section"],
            "text": original["text"], "citation": citation, "source": {
                "artifact": {"sha256": _sha(original["text"].encode()), "bytes": len(original["text"].encode())},
                "source_kind": "us_code", "release_id": fixture.release.release_id,
                "document_id": original["legal_id"], "language": "en", "citation": citation,
                "byte_start": 0, "byte_end": len(original["text"].encode()), "normalization": "identity"}}
        exact_input_bytes = json.dumps(expected_input, ensure_ascii=True, sort_keys=True,
                                      separators=(",", ":"), allow_nan=False).encode()
        assert metadata["input_id"] == "sha256:" + _sha(exact_input_bytes)


def test_noncorpus_family_descriptors_are_retained_without_reading_or_claiming_coverage(tmp_path):
    others = [{"relative_path": "recovery/part-000000.json", "family": "recovery", "sha256": "9" * 64,
               "size_bytes": 400, "row_count": 1, "schema_id": "uscode-recovery-quarantine/v1",
               "media_type": "application/json"},
              {"relative_path": "data/vectors/part-000000.parquet", "family": "vectors", "sha256": "8" * 64,
               "size_bytes": 500, "row_count": 3, "schema_id": "uscode-vector-row/v1",
               "media_type": "application/vnd.apache.parquet"}]
    fixture = _release(tmp_path, extra_artifacts=others)
    resolved = []

    def resolver(reference):
        resolved.append(reference["sha256"])
        return fixture.resolve(reference)

    inventory = inv.build_uscode_source_inventory(fixture.release, resolver=resolver)
    assert inventory.summary()["complete"] is True
    assert inventory.summary()["declared_row_count"] == 3
    assert inventory.summary()["full_federal_corpus_complete"] is False
    assert inventory.summary()["scope"] == "declared_corpus_family_only"
    saved_others = inventory.to_dict()["release"]["other_artifacts"]
    assert saved_others == [dict(("bytes" if key == "size_bytes" else key, value) for key, value in item.items())
                             for item in sorted(others, key=lambda item: item["relative_path"])]
    assert all(item["sha256"] not in resolved for item in others)


def test_inventory_determinism_reopen_detached_metadata_and_exclusive_save(tmp_path):
    fixture = _release(tmp_path)
    inventory = _build(fixture, batch_size=1)
    assert _build(fixture, batch_size=2).to_bytes() == inventory.to_bytes()
    saved = inventory.save(tmp_path / "inventory.json")
    assert saved["sha256"] == inventory.sha256
    assert saved["bytes"] == len(inventory.to_bytes())
    restored = inv.load_uscode_source_inventory(saved["path"], expected_sha256=saved["sha256"],
                                                expected_size_bytes=saved["bytes"])
    assert restored.to_bytes() == inventory.to_bytes()
    assert restored.summary() == inventory.summary()
    detached = restored.to_dict()
    detached["shards"][0]["rows"][0]["metadata"]["text_sha256"] = "f" * 64
    assert restored.to_bytes() == inventory.to_bytes()
    with pytest.raises((FileExistsError, inv.USCodeInventoryError)):
        restored.save(saved["path"])
    assert Path(saved["path"]).read_bytes() == inventory.to_bytes()


@pytest.mark.parametrize("mode", ["missing", "corrupt"])
def test_missing_or_corrupt_shard_preserves_declared_denominator_and_refuses_materialization(tmp_path, mode):
    fixture = _release(tmp_path)
    if mode == "missing":
        fixture.shards[1].unlink()
    else:
        fixture.shards[1].write_bytes(b"corrupt")
    inventory = _build(fixture)
    summary = inventory.summary()
    assert summary["complete"] is False
    assert summary["declared_corpus_closure_verified"] is False
    assert summary["grouping_metadata_complete"] is False
    assert summary["declared_row_count"] == 3
    assert summary["rows_scanned"] == 2
    shards = inventory.to_dict()["shards"]
    assert shards[1]["status"] == ("unavailable" if mode == "missing" else "corrupt")
    assert len(shards[1]["rows"]) == 1
    assert shards[1]["rows"][0]["row_index"] == 0
    assert shards[1]["rows"][0]["metadata"] is None
    with pytest.raises(inv.USCodeInventoryError):
        _materialize(inventory, fixture, tmp_path / "inputs", [_row(1)["entry_cid"]])
    assert not (tmp_path / "inputs").exists()


def test_absent_resolver_entry_is_a_missing_shard_not_a_silent_partial_selection(tmp_path):
    fixture = _release(tmp_path)
    del fixture.paths[fixture.descriptors[1]["sha256"]]
    inventory = _build(fixture)
    assert inventory.summary()["complete"] is False
    assert inventory.to_dict()["shards"][1]["status"] == "unavailable"
    assert len(_rows(inventory)) == 3


def test_final_closure_check_rejects_earlier_shard_mutation_while_reading_later_shard(tmp_path, monkeypatch):
    from contextlib import contextmanager
    fixture = _release(tmp_path)
    original = imp._verified_file
    first_closed = []

    @contextmanager
    def observed(path, reference, maximum):
        with original(path, reference, maximum) as stream:
            yield stream
        if Path(path) == fixture.shards[0]:
            first_closed.append(True)

    monkeypatch.setattr(imp, "_verified_file", observed)
    mutated = []

    def resolve(reference):
        if reference["sha256"] == fixture.descriptors[1]["sha256"] and first_closed and not mutated:
            raw = bytearray(fixture.shards[0].read_bytes())
            raw[len(raw) // 2] ^= 1
            fixture.shards[0].write_bytes(raw)
            mutated.append(True)
        return fixture.resolve(reference)

    with pytest.raises((inv.USCodeInventoryError, imp.USCodeImportError)):
        inv.build_uscode_source_inventory(fixture.release, resolver=resolve)
    assert mutated, "fixture must mutate a previously completely read shard"


def test_root_mutation_during_inventory_is_not_returned_as_success(tmp_path):
    fixture = _release(tmp_path)
    mutated = []

    def resolve(reference):
        if reference["sha256"] == fixture.descriptors[1]["sha256"] and not mutated:
            fixture.manifest_path.write_bytes(fixture.manifest_path.read_bytes() + b" ")
            mutated.append(True)
        return fixture.resolve(reference)

    with pytest.raises((inv.USCodeInventoryError, imp.USCodeImportError)):
        inv.build_uscode_source_inventory(fixture.release, resolver=resolve)
    assert mutated


def test_duplicate_entry_cids_across_shards_exclude_all_occurrences(tmp_path):
    duplicate = _row(1)
    fixture = _release(tmp_path, [[duplicate, _row(2)], [duplicate, _row(3)]])
    inventory = _build(fixture)
    duplicates = [row for row in _rows(inventory) if row["entry_cid"] == duplicate["entry_cid"]]
    assert len(duplicates) == 2
    assert all(row["duplicate_entry_cid"] and row["status"] == "duplicate_entry_cid" for row in duplicates)
    assert all(row["original_status"] == "ready_published_text" for row in duplicates)
    assert all(row["metadata"]["text_sha256"] == _sha(duplicate["text"].encode()) for row in duplicates)
    assert inventory.summary()["complete"] is True
    assert inventory.summary()["eligible_input_count"] == 2
    with pytest.raises(inv.USCodeInventoryError):
        _materialize(inventory, fixture, tmp_path / "duplicate", [duplicate["entry_cid"]])
    assert not (tmp_path / "duplicate").exists()


def test_local_duplicates_retain_verified_metadata_and_join_global_ambiguity(tmp_path):
    duplicate = _row(1)
    fixture = _release(tmp_path, [[duplicate, duplicate], [duplicate, _row(3)]])
    inventory = _build(fixture)
    rows = _rows(inventory)
    assert [row["original_status"] for row in rows[:3]] == [
        "duplicate_entry_cid", "duplicate_entry_cid", "ready_published_text"]
    assert all(row["status"] == "duplicate_entry_cid" and row["duplicate_entry_cid"] for row in rows[:3])
    assert all(row["wrapper_verified"] and row["metadata"] is not None for row in rows[:3])
    assert all(row["metadata"]["canonical_identity"]["document_id"] == "usc:us:5:1" for row in rows[:3])
    assert inventory.summary()["eligible_input_count"] == 1
    public = imp.read_corpus_shard(fixture.release, fixture.descriptors[0]["relative_path"], resolver=fixture.resolve)
    assert public.records == ()
    assert [item.status for item in public.dispositions] == ["duplicate_entry_cid", "duplicate_entry_cid"]


def test_global_duplicate_does_not_erase_original_hash_failure(tmp_path):
    def mutate(index, wrappers):
        if index == 0:
            wrappers[0]["record_sha256"] = "0" * 64
    fixture = _release(tmp_path, [[_row(1)], [_row(1), _row(3)]], wrapper_change=mutate)
    inventory = _build(fixture)
    rows = _rows(inventory)
    assert rows[0]["original_status"] == "record_hash_mismatch"
    assert rows[0]["status"] == "duplicate_entry_cid"
    assert rows[0]["metadata"] is None and rows[0]["wrapper_verified"] is False
    assert rows[1]["original_status"] == "ready_published_text"
    assert rows[1]["status"] == "duplicate_entry_cid"
    assert inventory.summary()["grouping_metadata_complete"] is False


@pytest.mark.parametrize("failure", [
    "invalid_wrapper", "record_hash_mismatch", "invalid_record_json", "wrapper_identity_mismatch",
])
def test_local_verified_duplicates_preserve_invalid_occurrence_failure(tmp_path, failure):
    def mutate(index, wrappers):
        if index != 0:
            return
        invalid = wrappers[2]
        if failure == "invalid_wrapper":
            invalid["family"] = "vectors"
        elif failure == "record_hash_mismatch":
            invalid["record_sha256"] = "0" * 64
        elif failure == "invalid_record_json":
            invalid["record_json"] = "["
            invalid["record_sha256"] = _sha(b"[")
        else:
            invalid["legal_id"] = "usc:us:5:999"

    duplicate = _row(1)
    fixture = _release(tmp_path, [[duplicate, duplicate, duplicate], [_row(3)]], wrapper_change=mutate)
    inventory = _build(fixture)
    rows = _rows(inventory)
    assert inventory.summary()["complete"] is True
    assert inventory.summary()["declared_row_count"] == inventory.summary()["rows_scanned"] == 4
    assert inventory.summary()["eligible_input_count"] == 1
    assert inventory.summary()["grouping_metadata_complete"] is False
    assert [row["original_status"] for row in rows[:3]] == [
        "duplicate_entry_cid", "duplicate_entry_cid", failure]
    assert all(row["status"] == "duplicate_entry_cid" and row["duplicate_entry_cid"] for row in rows[:3])
    assert all(row["wrapper_verified"] and row["metadata"] is not None for row in rows[:2])
    assert rows[2]["wrapper_verified"] is False and rows[2]["metadata"] is None
    public = imp.read_corpus_shard(fixture.release, fixture.descriptors[0]["relative_path"], resolver=fixture.resolve)
    assert public.records == ()
    assert [item.status for item in public.dispositions] == ["duplicate_entry_cid"] * 3
    with pytest.raises(inv.USCodeInventoryError):
        _materialize(inventory, fixture, tmp_path / "duplicate", [duplicate["entry_cid"]])
    assert not (tmp_path / "duplicate").exists()


def test_repeated_legal_identity_and_cross_edition_document_lineage_are_not_duplicate_cids(tmp_path):
    first = LegalIdentity("5", "10", edition="2023")
    second = LegalIdentity("5", "10", edition="2024")
    rows = [_row(1, section="10", legal_id=first.legal_id, edition="2023"),
            _row(2, section="10", legal_id=second.legal_id, edition="2024"),
            _row(3, section="10", legal_id=second.legal_id, edition="2024")]
    fixture = _release(tmp_path, [[rows[0]], rows[1:]])
    inventory = _build(fixture)
    metadata = [row["metadata"] for row in _rows(inventory)]
    assert {item["canonical_identity"]["document_id"] for item in metadata} == {"usc:us:5:10"}
    assert inventory.summary()["eligible_input_count"] == 3
    assert not any(row["duplicate_entry_cid"] for row in _rows(inventory))


@pytest.mark.parametrize("changes,status", [
    ({"admission_status": "excluded"}, "retrieval_disposition_excluded"),
    ({"text": " " * 3}, "missing_text"),
    ({"title": "7"}, "identity_mismatch"),
    ({"release_point": "us/pl/118/45"}, "release_point_mismatch"),
])
def test_excluded_row_dispositions_are_preserved_without_training_fallback(tmp_path, changes, status):
    fixture = _release(tmp_path, [[_row(1, **changes)], [_row(2)]])
    inventory = _build(fixture)
    row = _rows(inventory)[0]
    assert row["original_status"] == row["status"] == status
    assert row["wrapper_verified"] is True
    if status != "retrieval_disposition_excluded":
        assert row["metadata"]["input_id"] is None
    else:
        assert row["metadata"]["input_id"].startswith("sha256:")
    assert inventory.summary()["declared_row_count"] == 2
    assert inventory.summary()["eligible_input_count"] == 1
    if status in {"identity_mismatch", "release_point_mismatch"}:
        assert inventory.summary()["complete"] is True
        assert inventory.summary()["grouping_metadata_complete"] is False
    with pytest.raises(inv.USCodeInventoryError):
        _materialize(inventory, fixture, tmp_path / "excluded", [_row(1)["entry_cid"]])
    assert not (tmp_path / "excluded").exists()


def test_overlong_excluded_connector_retains_lineage_and_content_hashes(tmp_path):
    text = "The agency shall retain café records. " * 20
    fixture = _release(tmp_path, [[_row(1, text=text)], [_row(2, text="Short text.")]],
                       import_limits=imp.USCodeImportLimits(max_text_bytes=50))
    inventory = _build(fixture)
    excluded = _rows(inventory)[0]
    assert excluded["original_status"] == excluded["status"] == "text_exceeds_bound"
    metadata = excluded["metadata"]
    assert metadata["text_sha256"] == _sha(text.encode())
    assert metadata["normalized_content_sha256"] == _sha(" ".join(text.split()).casefold().encode())
    assert metadata["canonical_identity"]["document_id"] == "usc:us:5:1"
    # Exact source identity survives this lower importer limit; status controls selection.
    assert metadata["input_id"].startswith("sha256:")
    assert inventory.summary()["grouping_metadata_complete"] is True
    assert inventory.summary()["eligible_input_count"] == 1
    assert text.encode() not in inventory.to_bytes()


def test_importer_ready_text_beyond_producer_bound_is_explicitly_ineligible(tmp_path):
    text = "x" * (1024 * 1024 + 1)
    fixture = _release(tmp_path, [[_row(1, text=text)]],
                       import_limits=imp.USCodeImportLimits(max_text_bytes=2 * 1024 * 1024))
    inventory = _build(fixture)
    row = _rows(inventory)[0]
    assert row["original_status"] == "ready_published_text"
    assert row["status"] == "embedding_input_ineligible"
    assert row["metadata"]["input_id"] is None
    assert row["metadata"]["text_bytes"] == len(text)
    assert row["metadata"]["text_sha256"] == _sha(text.encode())
    assert inventory.summary()["complete"] is inventory.summary()["grouping_metadata_complete"] is True
    assert inventory.summary()["eligible_input_count"] == 0
    with pytest.raises(inv.USCodeInventoryError):
        _materialize(inventory, fixture, tmp_path / "overlong", [_row(1)["entry_cid"]])
    assert not (tmp_path / "overlong").exists()


def test_materialization_returns_exact_source_bound_embedding_inputs_and_preserves_requested_order(tmp_path):
    fixture = _release(tmp_path)
    inventory = _build(fixture)
    ids = [_row(3)["entry_cid"], _row(1)["entry_cid"]]
    batch = _materialize(inventory, fixture, tmp_path / "inputs", ids)
    assert type(batch.inputs) is tuple and all(type(item) is EmbeddingInput for item in batch.inputs)
    assert [item.text for item in batch.inputs] == [_row(3)["text"], _row(1)["text"]]
    by_id = {row["entry_cid"]: row for row in _rows(inventory)}
    assert [item.input_id for item in batch.inputs] == [by_id[key]["metadata"]["input_id"] for key in ids]
    paths = {source.artifact.sha256: Path(source.path) for source in batch.extraction.sources}
    assert validate_embedding_inputs(batch.inputs, resolver=lambda ref: paths[ref["sha256"]]) == batch.inputs
    for item in batch.inputs:
        assert item.source.source_kind == "us_code"
        assert item.source.release_id == fixture.release.release_id
        assert item.source.normalization == "identity"
        assert item.source.byte_start == 0
        assert item.source.byte_end == len(item.text.encode())
        assert paths[item.source.artifact.sha256].read_bytes() == item.text.encode()
    ref = batch.selection_receipt_artifact
    raw = Path(ref["path"]).read_bytes()
    assert ref["bytes"] == len(raw) and ref["sha256"] == _sha(raw)
    assert json.loads(raw) == batch.selection_receipt
    receipt = batch.selection_receipt
    assert receipt["inventory"] == {"sha256": inventory.sha256, "bytes": len(inventory.to_bytes())}
    assert receipt["release_manifest"] == fixture.release.manifest_reference
    assert receipt["entry_cids"] == ids
    assert receipt["input_ids"] == [item.input_id for item in batch.inputs]
    assert receipt["extraction_receipt"] == {key: batch.extraction.receipt_artifact[key] for key in ("sha256", "bytes")}
    assert receipt["selected_source_bytes_verified"] is True
    assert receipt["unselected_current_shards_reverified"] is False
    assert receipt["training_eligible"] is receipt["admitted"] is False


def test_inventory_reopen_materializes_identical_inputs_and_source_bytes(tmp_path):
    fixture = _release(tmp_path)
    inventory = _build(fixture)
    saved = inventory.save(tmp_path / "inventory.json")
    reopened = inv.load_uscode_source_inventory(saved["path"], expected_sha256=saved["sha256"],
                                                expected_size_bytes=saved["bytes"])
    first = _materialize(inventory, fixture, tmp_path / "first")
    second = _materialize(reopened, fixture, tmp_path / "second")
    assert [item.to_dict() for item in first.inputs] == [item.to_dict() for item in second.inputs]
    assert [Path(item.path).read_bytes() for item in first.extraction.sources] == [
        Path(item.path).read_bytes() for item in second.extraction.sources]
    assert inventory.to_bytes() == reopened.to_bytes()


@pytest.mark.parametrize("selection", [[], ["missing"], [_row(1)["entry_cid"]] * 2,
    [_row(1)["entry_cid"]] * 257, [_row(1)["entry_cid"], True], _row(1)["entry_cid"], None])
def test_materialization_requires_bounded_unique_known_eligible_ids_before_writes(tmp_path, selection):
    fixture = _release(tmp_path)
    inventory = _build(fixture)
    with pytest.raises(inv.USCodeInventoryError):
        _materialize(inventory, fixture, tmp_path / "invalid", selection)
    assert not (tmp_path / "invalid").exists()


def test_materialization_never_overwrites_existing_output_directory(tmp_path):
    fixture = _release(tmp_path)
    inventory = _build(fixture)
    destination = tmp_path / "existing"
    destination.mkdir()
    marker = destination / "marker"
    marker.write_bytes(b"retained original")
    with pytest.raises((FileExistsError, inv.USCodeInventoryError)):
        _materialize(inventory, fixture, destination)
    assert marker.read_bytes() == b"retained original"
    assert list(destination.iterdir()) == [marker]


@pytest.mark.parametrize("which", ["selected", "root"])
def test_materialization_rechecks_root_and_selected_source_closure_before_outputs(tmp_path, which):
    fixture = _release(tmp_path)
    inventory = _build(fixture)
    target = fixture.manifest_path if which == "root" else fixture.shards[0]
    target.write_bytes(target.read_bytes() + b" ")
    with pytest.raises((inv.USCodeInventoryError, imp.USCodeImportError)):
        _materialize(inventory, fixture, tmp_path / "mutated", [_row(1)["entry_cid"]])
    assert not (tmp_path / "mutated").exists()


def test_materialization_does_not_claim_current_verification_of_unselected_shards(tmp_path):
    fixture = _release(tmp_path)
    inventory = _build(fixture)
    fixture.shards[1].write_bytes(b"changed after complete historical scan")
    resolved = []

    def selected_only(reference):
        resolved.append(reference["sha256"])
        assert reference["sha256"] != fixture.descriptors[1]["sha256"]
        return fixture.resolve(reference)

    batch = inv.materialize_uscode_inventory_inputs(inventory, [_row(1)["entry_cid"]], tmp_path / "selected",
        release=fixture.release, resolver=selected_only)
    assert inventory.summary()["declared_corpus_closure_verified"] is True
    assert batch.selection_receipt["selected_source_bytes_verified"] is True
    assert batch.selection_receipt["unselected_current_shards_reverified"] is False
    assert batch.selection_receipt["selected_shards"] == [{"relative_path": fixture.descriptors[0]["relative_path"],
        "sha256": fixture.descriptors[0]["sha256"], "bytes": fixture.descriptors[0]["size_bytes"]}]
    assert len(batch.inputs) == 1 and resolved


def test_materialization_rejects_changed_release_binding(tmp_path):
    fixture = _release(tmp_path)
    inventory = _build(fixture)
    changed = replace(fixture.release, revision="f" * 40)
    with pytest.raises((inv.USCodeInventoryError, imp.USCodeImportError)):
        inv.materialize_uscode_inventory_inputs(inventory, [_row(1)["entry_cid"]], tmp_path / "foreign",
            release=changed, resolver=fixture.resolve)
    assert not (tmp_path / "foreign").exists()


@pytest.mark.parametrize("field,value", [("text_sha256", "a" * 64), ("record_sha256", "a" * 64),
    ("normalized_content_sha256", "a" * 64), ("input_id", "sha256:" + "a" * 64)])
def test_resealed_selected_metadata_cannot_borrow_a_real_source_locator(tmp_path, field, value):
    fixture = _release(tmp_path)
    original = _build(fixture)
    payload = original.to_dict()
    payload["shards"][0]["rows"][0]["metadata"][field] = value
    destination = tmp_path / "forged"
    with pytest.raises(inv.USCodeInventoryError):
        changed = inv.USCodeSourceInventory(_json(payload))
        _materialize(changed, fixture, destination, [_row(1)["entry_cid"]])
    assert not destination.exists()


@pytest.mark.parametrize("field,value", [("max_rows", 1), ("max_corpus_shards", 1),
    ("max_declared_compressed_bytes", 1), ("max_metadata_bytes", 1)])
def test_inventory_aggregate_bounds_are_enforced(tmp_path, field, value):
    fixture = _release(tmp_path)
    with pytest.raises(inv.USCodeInventoryError):
        _build(fixture, limits=inv.InventoryLimits(**{field: value}))


@pytest.mark.parametrize("field", ["max_rows", "max_corpus_shards", "max_declared_compressed_bytes", "max_metadata_bytes"])
@pytest.mark.parametrize("value", [0, -1, True, 1.5, 2**63])
def test_limits_are_strict_positive_bounded_integers(field, value):
    with pytest.raises(inv.USCodeInventoryError):
        inv.InventoryLimits(**{field: value})


@pytest.mark.parametrize("batch_size", [0, 257, True, 1.5])
def test_inventory_batch_size_preserves_existing_reader_bounds(tmp_path, batch_size):
    fixture = _release(tmp_path)
    with pytest.raises((inv.USCodeInventoryError, imp.USCodeImportError)):
        _build(fixture, batch_size=batch_size)


@pytest.mark.parametrize("raw", [b'{"schema_version":"x","schema_version":"y"}',
    b'{"x":NaN}', b'{"x":1e999}', b'{}', b'[]'])
def test_inventory_reader_rejects_ambiguous_nonfinite_or_wrong_shapes(raw):
    with pytest.raises(inv.USCodeInventoryError):
        inv.USCodeSourceInventory(raw)


@pytest.mark.parametrize("tamper", ["extra_root", "extra_row", "extra_metadata", "missing_row", "row_index",
    "bool_ordinal", "bool_scanned", "unverified_metadata", "false_global_duplicate", "forged_ready",
    "false_placeholder", "duplicate_shard", "reordered_shards", "mutable_release", "other_family_corpus"])
def test_canonical_resealed_inventory_rejects_inconsistent_closed_coverage(tmp_path, tamper):
    fixture = _release(tmp_path)
    payload = _build(fixture).to_dict()
    shard = payload["shards"][0]
    row = shard["rows"][0]
    if tamper == "extra_root":
        payload["trusted"] = True
    elif tamper == "extra_row":
        row["text"] = _row(1)["text"]
    elif tamper == "extra_metadata":
        row["metadata"]["embedding_vector"] = [1.0]
    elif tamper == "missing_row":
        shard["rows"].pop()
    elif tamper == "row_index":
        row["row_index"] = 1
    elif tamper == "bool_ordinal":
        row["row_index"] = False
    elif tamper == "bool_scanned":
        shard["rows_scanned"] = True
    elif tamper == "unverified_metadata":
        row["wrapper_verified"] = False
    elif tamper == "false_global_duplicate":
        row["duplicate_entry_cid"] = True
        row["status"] = "duplicate_entry_cid"
    elif tamper == "forged_ready":
        row["metadata"]["input_id"] = None
    elif tamper == "false_placeholder":
        row["original_status"] = row["status"] = "shard_unavailable"
    elif tamper == "duplicate_shard":
        payload["shards"].append(shard)
    elif tamper == "reordered_shards":
        payload["shards"].reverse()
    elif tamper == "mutable_release":
        payload["release"]["revision"] = "main"
    elif tamper == "other_family_corpus":
        payload["release"]["other_artifacts"].append(shard["artifact"])
    with pytest.raises(inv.USCodeInventoryError):
        inv.USCodeSourceInventory(_json(payload))


def test_inventory_reader_requires_canonical_bytes_not_just_equivalent_json(tmp_path):
    inventory = _build(_release(tmp_path))
    with pytest.raises(inv.USCodeInventoryError):
        inv.USCodeSourceInventory(inventory.to_bytes() + b"\n")
    with pytest.raises(inv.USCodeInventoryError):
        inv.USCodeSourceInventory(json.dumps(inventory.to_dict(), indent=2).encode())


def test_inventory_loader_checks_expected_bytes_sha_and_regular_file(tmp_path):
    fixture = _release(tmp_path)
    inventory = _build(fixture)
    saved = inventory.save(tmp_path / "inventory.json")
    for sha, size in (("0" * 64, saved["bytes"]), (saved["sha256"], saved["bytes"] + 1),
                      (saved["sha256"], True)):
        with pytest.raises(inv.USCodeInventoryError):
            inv.load_uscode_source_inventory(saved["path"], expected_sha256=sha, expected_size_bytes=size)
    alias = tmp_path / "alias.json"
    alias.symlink_to(saved["path"])
    with pytest.raises(inv.USCodeInventoryError):
        inv.load_uscode_source_inventory(alias, expected_sha256=saved["sha256"], expected_size_bytes=saved["bytes"])
    with pytest.raises(inv.USCodeInventoryError):
        inv.load_uscode_source_inventory(saved["path"], expected_sha256=saved["sha256"],
            expected_size_bytes=saved["bytes"], limits=inv.InventoryLimits(max_rows=1))
