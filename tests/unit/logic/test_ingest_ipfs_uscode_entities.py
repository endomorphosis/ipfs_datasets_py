"""Tiny, offline source-bound v2 ingestion; no training or legal admission."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace

import pyarrow as pa
import pyarrow.parquet as pq
import pytest


@pytest.fixture
def ingest():
    path = Path(__file__).resolve().parents[3] / "scripts/ops/legal_ir/ingest_ipfs_uscode_entities.py"
    spec = importlib.util.spec_from_file_location("_offline_entity_ingest_v2", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def cache_type():
    from ipfs_datasets_py.logic.autoformal.entity_cache import EntityCache, SCHEMA
    assert SCHEMA == "uscode-autoformal-entity-cache/v2"
    return EntityCache


@pytest.fixture
def cache(cache_type, tmp_path):
    value = cache_type(tmp_path / "queue-v2.duckdb")
    try:
        yield value
    finally:
        value.close()


def _rows():
    def row(identifier, kind, label, properties="{}"):
        return {"id": identifier, "type": kind, "label": label, "properties_json": properties}
    document = row("doc1", "legal_document", "First document")
    return [document, dict(document), row("doc1:section:1", "section", "1", '{"section_number":"1"}'),
            row("usc:title:1", "usc_title", "Title 1", '{"title_number":"1"}'),
            row("doc2", "legal_document", "Second document"),
            row("doc2:section:2", "section", "2", '{"section_number":"2"}'),
            row("usc:title:2", "usc_title", "Title 2", '{"title_number":"2"}')]


def _files(tmp_path, *, rows=None):
    entities, relationships = tmp_path / "entities.parquet", tmp_path / "relationships.parquet"
    pq.write_table(pa.Table.from_pylist(_rows() if rows is None else rows), entities, row_group_size=2)
    pq.write_table(pa.Table.from_pylist([
        {"type": "IN_TITLE", "source": "doc1", "target": "usc:title:1"},
        {"type": "HAS_SECTION", "source": "doc2", "target": "doc2:section:2"},
        {"type": "HAS_SECTION", "source": "doc1", "target": "doc1:section:1"},
        {"type": "IN_TITLE", "source": "doc2", "target": "usc:title:2"},
    ]), relationships, row_group_size=1)
    return entities, relationships


def _bind(cache, inputs, *, resume=True):
    checkpoint = cache.bind_inputs(inputs.manifest, resume=resume)
    assert checkpoint["input_id"] == inputs.input_id
    assert checkpoint["admitted"] is checkpoint["formalized"] is False
    return checkpoint


def _queue_count(cache):
    return cache._db.execute("SELECT count(*) FROM entity_queue").fetchone()[0]


@pytest.mark.parametrize("batch", [0, -1, 513, True, 1.5, "2"])
def test_batch_bounds_are_strict_before_input_access(ingest, batch):
    with pytest.raises(ingest.EntityIngestError, match="1 through 512"):
        ingest.enqueue_entities(None, None, batch=batch)


def test_exact_two_file_manifest_and_physical_duplicate_resume(ingest, cache, tmp_path):
    entities, relationships = _files(tmp_path)
    with ingest._BoundInputs(entities, relationships) as inputs:
        expected = {"schema_version": "entity-cache-inputs/v2", "dataset_id": "justicedao/ipfs_uscode",
                    "entity_identity_schema": "uscode-autoformal-entity-cache/v2"}
        for role, path, count in (("entities", entities, 7), ("relationships", relationships, 4)):
            expected[role] = {"sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                              "bytes": path.stat().st_size, "row_count": count}
        assert inputs.manifest == expected
        assert inputs.input_id == "sha256:" + hashlib.sha256(ingest._json(expected)).hexdigest()
        _bind(cache, inputs)
        assert cache.enqueue_source_batch(_rows()[:3], 0, 3, verify_inputs=inputs.verify_current) == 2
        result = ingest.enqueue_entities(cache, inputs, batch=2)
        assert result == {"admitted": False, "formalized": False, "entities": 7, "new": 4,
                          "resumed_from": 3, "input_id": inputs.input_id}
        assert _queue_count(cache) == 6
        assert cache.checkpoint()["next_ordinal"] == 7
        repeated = ingest.enqueue_entities(cache, inputs, batch=1)
        assert repeated["new"] == 0 and repeated["resumed_from"] == 7


@pytest.mark.parametrize("cursor", [-1, 8, True, "3", None])
def test_corrupt_cursor_is_never_reset_or_adopted(ingest, cache, tmp_path, monkeypatch, cursor):
    with ingest._BoundInputs(*_files(tmp_path)) as inputs:
        _bind(cache, inputs)
        invalid = {**cache.checkpoint(), "next_ordinal": cursor}
        monkeypatch.setattr(cache, "checkpoint", lambda: invalid)
        with pytest.raises(ingest.EntityIngestError, match="corrupt physical cursor"):
            ingest.enqueue_entities(cache, inputs, batch=2)
        assert _queue_count(cache) == 0


@pytest.mark.parametrize("role", ["entities", "relationships"])
def test_changed_pair_cannot_resume_or_poll(ingest, cache_type, tmp_path, monkeypatch, role):
    paths = _files(tmp_path)
    cache_path = tmp_path / "bound.duckdb"
    cache = cache_type(cache_path)
    with ingest._BoundInputs(*paths) as inputs:
        _bind(cache, inputs)
        ingest.enqueue_entities(cache, inputs, batch=2)
    cache.close()
    path = paths[0 if role == "entities" else 1]
    rows = pq.read_table(path).to_pylist()
    rows[0]["label" if role == "entities" else "target"] += " changed"
    pq.write_table(pa.Table.from_pylist(rows), path)
    monkeypatch.setattr(ingest, "_cache_type", lambda: cache_type)
    monkeypatch.setattr(ingest, "_poll", lambda *args: pytest.fail("polled before immutable binding rejection"))
    with pytest.raises(ValueError):
        ingest.main(["--parquet", str(paths[0]), "--relationships", str(paths[1]),
                     "--cache", str(cache_path), "--poll"])


@pytest.mark.parametrize("kind", ["symlink", "hardlink"])
def test_input_aliases_are_rejected(ingest, tmp_path, kind):
    entities, relationships = _files(tmp_path)
    alias = tmp_path / "alias.parquet"
    if kind == "symlink":
        alias.symlink_to(entities)
    else:
        os.link(entities, alias)
    with pytest.raises(ingest.EntityIngestError, match="alias|exclusive"):
        with ingest._BoundInputs(alias, relationships):
            pytest.fail("alias adopted")


@pytest.mark.parametrize("mutation", ["replace", "truncate", "symlink"])
def test_held_input_identity_detects_replacement_even_with_same_bytes(ingest, tmp_path, mutation):
    entities, relationships = _files(tmp_path)
    with ingest._BoundInputs(entities, relationships) as inputs:
        raw = entities.read_bytes()
        if mutation == "truncate":
            with entities.open("wb") as stream:
                stream.write(raw[:16])
        else:
            other = tmp_path / "replacement.parquet"
            other.write_bytes(raw)
            entities.unlink()
            if mutation == "replace":
                other.rename(entities)
            else:
                entities.symlink_to(other)
        with pytest.raises(ingest.EntityIngestError, match="identity changed"):
            inputs.verify_current()


def test_later_relationship_mutation_rolls_back_current_batch_only(ingest, cache, tmp_path, monkeypatch):
    entities, relationships = _files(tmp_path)
    with ingest._BoundInputs(entities, relationships) as inputs:
        _bind(cache, inputs)
        cache.enqueue_source_batch(_rows()[:2], 0, 2, verify_inputs=inputs.verify_current)
        original = cache.enqueue_source_batch
        def fail_current(rows, start, end, *, verify_inputs):
            def at_commit():
                with relationships.open("ab") as stream:
                    stream.write(b"drift")
                verify_inputs()
            return original(rows, start, end, verify_inputs=at_commit)
        monkeypatch.setattr(cache, "enqueue_source_batch", fail_current)
        with pytest.raises(ingest.EntityIngestError, match="identity changed"):
            ingest.enqueue_entities(cache, inputs, batch=2)
        assert cache.checkpoint()["next_ordinal"] == 2
        assert _queue_count(cache) == 1


def test_full_containment_uses_all_relationship_batches_and_preserves_enrichment(ingest, cache, tmp_path):
    with ingest._BoundInputs(*_files(tmp_path)) as inputs:
        _bind(cache, inputs)
        ingest.enqueue_entities(cache, inputs, batch=2)
        result = ingest.prepare_pending(cache, inputs, batch=1)
        assert result["admitted"] is result["formalized"] is False
        assert result["prepared"] == 6
        context = lambda identifier: json.loads(cache._db.execute(
            "SELECT context_json FROM entity_queue WHERE entity_id=?", [identifier]).fetchone()[0])
        assert context("doc1:section:1")["span_legal_id"] == "usc:us:1:1"
        assert context("doc2:section:2")["span_legal_id"] == "usc:us:2:2"
        assert "doc1:section:1" in context("usc:title:1")["scope_only_entity_ids"]
        assert "doc2:section:2" in context("usc:title:2")["scope_only_entity_ids"]
        cache.assign_span_context([{"legal_id": "usc:us:1:1", "source_span_id": "span-a"}])
        cache.assign_definition_closure([{"source_legal_id": "usc:us:1:1", "target_legal_id": "usc:us:1:9"}])
        enriched = context("doc1:section:1")
        repeated = ingest.prepare_pending(cache, inputs, batch=3)
        assert repeated == result
        final = context("doc1:section:1")
        assert final["contained_span_ids"] == enriched["contained_span_ids"] == ["span-a"]
        assert final["definition_targets"] == enriched["definition_targets"] == ["usc:us:1:9"]


def test_incomplete_queue_cannot_prepare(ingest, cache, tmp_path):
    with ingest._BoundInputs(*_files(tmp_path)) as inputs:
        _bind(cache, inputs)
        with pytest.raises(ingest.EntityIngestError, match="incomplete input"):
            ingest.prepare_pending(cache, inputs, batch=2)


@pytest.mark.parametrize("explicit_offline", [False, True])
def test_main_defaults_are_offline_without_claim_release(ingest, cache_type, tmp_path, monkeypatch, capsys,
                                                       explicit_offline):
    paths = _files(tmp_path)
    monkeypatch.setattr(ingest, "_cache_type", lambda: cache_type)
    monkeypatch.setattr(ingest, "_poll", lambda *args: pytest.fail("offline invocation polled"))
    monkeypatch.setattr(cache_type, "release_stale_claims", lambda *args: pytest.fail("claims implicitly released"))
    monkeypatch.setitem(sys.modules, "huggingface_hub", SimpleNamespace(
        HfApi=lambda: pytest.fail("offline invocation uploaded")))
    args = ["--parquet", str(paths[0]), "--relationships", str(paths[1]),
            "--cache", str(tmp_path / "offline.duckdb"), "--batch", "2"]
    if explicit_offline:
        args += ["--no-poll", "--no-upload"]
    assert ingest.main(args) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["admitted"] is report["formalized"] is False
    assert report["hf"]["uploaded"] is report["hf"]["remote_verified"] is False
    assert report["poll"]["poll_performed"] is False
    output = Path(report["hf"]["local_path"])
    assert output.name == "entity-resume-checkpoint-v2.parquet"
    assert output.parent.name == report["enqueued"]["input_id"][7:]
    assert output.parent.parent.name == "entity-hf-checkpoint-v2"
    assert pq.ParquetFile(output).metadata.num_rows > 0


def test_explicit_poll_runs_after_exact_binding_before_queue(ingest, cache_type, tmp_path, monkeypatch, capsys):
    paths = _files(tmp_path)
    monkeypatch.setattr(ingest, "_cache_type", lambda: cache_type)
    observed = []
    def poll(cache, inputs):
        inputs.verify_full()
        assert cache.checkpoint()["input_id"] == inputs.input_id
        assert _queue_count(cache) == 0
        observed.append(inputs.input_id)
        return {"changed": False, "admitted": False, "formalized": False}
    monkeypatch.setattr(ingest, "_poll", poll)
    assert ingest.main(["--parquet", str(paths[0]), "--relationships", str(paths[1]),
                        "--cache", str(tmp_path / "poll.duckdb"), "--poll", "--no-prepare"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert observed == [report["enqueued"]["input_id"]]
    assert report["stage"] == "entities_queued" and report["prepared"]["prepared"] == 0


def test_no_resume_refuses_existing_progress(ingest, cache, tmp_path):
    with ingest._BoundInputs(*_files(tmp_path)) as inputs:
        _bind(cache, inputs)
        cache.enqueue_source_batch(_rows()[:1], 0, 1, verify_inputs=inputs.verify_current)
        with pytest.raises(ValueError):
            cache.bind_inputs(inputs.manifest, resume=False)
        assert cache.checkpoint()["next_ordinal"] == 1


def test_explicit_upload_uses_versioned_key_and_parent_revision(ingest, cache, tmp_path, monkeypatch):
    with ingest._BoundInputs(*_files(tmp_path)) as inputs:
        _bind(cache, inputs)
        ingest.enqueue_entities(cache, inputs, batch=2)
        ingest.prepare_pending(cache, inputs, batch=2)
        calls = []
        class FakeApi:
            def create_repo(self, *args, **kwargs):
                calls.append(("create", args, kwargs))
            def repo_info(self, *args, **kwargs):
                return SimpleNamespace(sha="a" * 40)
            def upload_file(self, **kwargs):
                inputs.verify_full()
                assert kwargs["parent_commit"] == "a" * 40
                assert kwargs["path_in_repo"] == "autoformal/uscode/v2/" + inputs.input_id[7:] + "/entity-resume-checkpoint-v2.parquet"
                assert kwargs["path_or_fileobj"].read(4) == b"PAR1"
                calls.append(("upload", kwargs["path_in_repo"]))
                return SimpleNamespace(oid="b" * 40)
        monkeypatch.setitem(sys.modules, "huggingface_hub", SimpleNamespace(HfApi=FakeApi))
        receipt = ingest._flush(cache, tmp_path / "snapshots", upload=True, inputs=inputs)
        assert [call[0] for call in calls] == ["create", "upload"]
        assert receipt["uploaded"] is True and receipt["remote_verified"] is False
        assert receipt["revision"] == "b" * 40
        assert receipt["admitted"] is receipt["formalized"] is False


def test_input_drift_during_export_blocks_remote_write(ingest, cache, tmp_path, monkeypatch):
    entities, relationships = _files(tmp_path)
    with ingest._BoundInputs(entities, relationships) as inputs:
        _bind(cache, inputs)
        ingest.enqueue_entities(cache, inputs, batch=2)
        original = cache.write_resume_parquet
        def write_then_drift(path):
            result = original(path)
            with relationships.open("ab") as stream:
                stream.write(b"changed")
            return result
        monkeypatch.setattr(cache, "write_resume_parquet", write_then_drift)
        monkeypatch.setitem(sys.modules, "huggingface_hub", SimpleNamespace(
            HfApi=lambda: pytest.fail("remote client created after input drift")))
        with pytest.raises(ingest.EntityIngestError, match="identity changed"):
            ingest._flush(cache, tmp_path / "snapshots", upload=True, inputs=inputs)


def test_foreign_tree_is_rejected_before_cache_constructor(ingest, tmp_path, monkeypatch):
    foreign = SimpleNamespace(__file__=str(tmp_path / "HACC/tree_pin.py"),
                              require_workspace_logic_tree=lambda: pytest.fail("foreign pin called"))
    monkeypatch.setattr(ingest.importlib, "import_module", lambda name: foreign)
    monkeypatch.setattr(sys, "path", list(sys.path))
    with pytest.raises(ingest.EntityIngestError, match="canonical workspace tree"):
        ingest._cache_type()


@pytest.mark.parametrize("role", ["entities", "relationships"])
def test_arrow_reader_uses_bounded_single_thread_batches(ingest, tmp_path, role):
    with ingest._BoundInputs(*_files(tmp_path)) as inputs:
        observed = []
        attribute = "entity_file" if role == "entities" else "relationship_file"
        original = getattr(inputs, attribute)
        class Reader:
            schema_arrow = original.schema_arrow
            def iter_batches(self, **kwargs):
                observed.append(kwargs)
                yield from original.iter_batches(**kwargs)
        setattr(inputs, attribute, Reader())
        rows = [row for batch in inputs.batches(role, 2) for row in batch]
        assert len(rows) == (7 if role == "entities" else 4)
        columns = ["id", "type", "label", "properties_json"] if role == "entities" else ["type", "source", "target"]
        assert observed == [{"batch_size": 2, "columns": columns, "use_threads": False}]


def test_decoded_batch_bound_fails_before_enqueue(ingest, cache, tmp_path, monkeypatch):
    with ingest._BoundInputs(*_files(tmp_path)) as inputs:
        _bind(cache, inputs)
        monkeypatch.setattr(ingest, "MAX_BATCH_BYTES", 1)
        with pytest.raises(ingest.EntityIngestError, match="decoded batch"):
            ingest.enqueue_entities(cache, inputs, batch=2)
        assert _queue_count(cache) == 0 and cache.checkpoint()["next_ordinal"] == 0


@pytest.mark.parametrize("collision", ["database", "wal", "hardlink"])
def test_snapshot_never_replaces_cache_or_wal(ingest, tmp_path, monkeypatch, collision):
    with ingest._BoundInputs(*_files(tmp_path)) as inputs:
        destination = tmp_path / "snapshots"
        output = destination / inputs.input_id[7:] / ingest.SNAPSHOT_NAME
        output.parent.mkdir(parents=True)
        database = output if collision == "database" else tmp_path / "owner.duckdb"
        database.write_bytes(b"existing database must remain unchanged")
        if collision == "wal":
            # Make the output's exact lexical name the owner's WAL path.
            database = output.parent / "owner.duckdb"
            database.write_bytes(b"existing database must remain unchanged")
            output = Path(str(database) + ".wal")
            monkeypatch.setattr(ingest, "SNAPSHOT_NAME", output.name)
            output.write_bytes(b"existing WAL must remain unchanged")
        elif collision == "hardlink":
            os.link(database, output)
        before = database.read_bytes()
        fake = SimpleNamespace(path=database, checkpoint=lambda: {"input_id": inputs.input_id},
            register_agent=lambda *args: pytest.fail("registered agent before overlap rejection"),
            write_resume_parquet=lambda *args: pytest.fail("overwrote database or WAL"))
        with pytest.raises(ingest.EntityIngestError, match="cache|exclusive"):
            ingest._flush(fake, destination, upload=False, inputs=inputs)
        assert database.read_bytes() == before


@pytest.mark.parametrize("collision", ["database", "wal"])
def test_cache_factory_never_opens_a_source_as_database_or_wal(ingest, tmp_path, monkeypatch, collision):
    entities, relationships = _files(tmp_path)
    database = entities
    if collision == "wal":
        moved = tmp_path / "owner.duckdb.wal"
        entities.rename(moved)
        entities, database = moved, tmp_path / "owner.duckdb"
    before = entities.read_bytes()
    monkeypatch.setattr(ingest, "_cache_type", lambda: pytest.fail("cache factory touched source data"))
    with pytest.raises(ingest.EntityIngestError, match="overlaps an input"):
        ingest.main(["--parquet", str(entities), "--relationships", str(relationships), "--cache", str(database)])
    assert entities.read_bytes() == before


def test_oversized_remote_checkpoint_rejected_before_download(ingest, cache, tmp_path, monkeypatch):
    with ingest._BoundInputs(*_files(tmp_path)) as inputs:
        _bind(cache, inputs)
        class FakeApi:
            def repo_info(self, *args, **kwargs):
                return SimpleNamespace(sha="a" * 40)
            def get_paths_info(self, repo_id, paths, **kwargs):
                assert paths == [ingest._remote_key(cache)]
                assert kwargs["revision"] == "a" * 40
                return [SimpleNamespace(size=ingest.MAX_RESUME_FILE_BYTES + 1)]
        monkeypatch.setitem(sys.modules, "huggingface_hub", SimpleNamespace(HfApi=FakeApi,
            hf_hub_download=lambda *args, **kwargs: pytest.fail("downloaded oversized remote checkpoint")))
        result = ingest._poll(cache, inputs)
        assert result == {"changed": False, "error": "EntityIngestError", "admitted": False, "formalized": False}
        assert _queue_count(cache) == 0 and cache.checkpoint()["next_ordinal"] == 0
