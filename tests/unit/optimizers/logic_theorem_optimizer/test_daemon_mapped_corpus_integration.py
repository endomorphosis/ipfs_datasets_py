"""Real owner/input/runner wiring with synthetic optimizer and snapshot callbacks.

The registered vectors are declared fixtures, not generated embeddings. No
native learning, bridge evaluation, snapshot proof or performance is qualified.
"""
from __future__ import annotations

import json
from pathlib import Path
import struct
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.duckdb_control.autoencoder_registry import AutoencoderRegistry
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_arrow_inputs as arrow
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_daemon_corpus_inputs as inputs
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import uscode_modal_daemon_runner as runner
from tests.unit.optimizers.logic_theorem_optimizer.test_autoencoder_daemon_corpus_inputs import _prepare
from tests.unit.optimizers.logic_theorem_optimizer.test_daemon_corpus_input_integration import _SAMPLER
from tests.unit.optimizers.logic_theorem_optimizer.test_daemon_shared_target_integration import actual_run


def _bits(values):
    return b"".join(struct.pack(">d", value) for value in values)


@pytest.fixture
def mapped_run(actual_run, monkeypatch):
    case = actual_run
    owner_root = case.root / "issued-owner"
    owner_root.mkdir()
    with AutoencoderRegistry(owner_root / "registry.duckdb", owner_root / "artifacts") as registry:
        spec = _prepare(registry, owner_root, arrow_inputs=True)
        issued = inputs.export_daemon_corpus_inputs(registry, spec.run_id, operation_id="mapped-input-export")
        descriptor = inputs.DaemonCorpusInputDescriptor(**issued["descriptor"])
        for field in ("autoencoder_target_bundle", "autoencoder_target_bundle_sha256",
                      "autoencoder_target_bundle_bytes", "autoencoder_target_snapshot_id"):
            setattr(case.args, field, None)
        case.args.autoencoder_corpus_input = descriptor.path
        case.args.autoencoder_corpus_input_sha256 = descriptor.sha256
        case.args.autoencoder_corpus_input_bytes = descriptor.bytes
        case.args.train_count = case.args.validation_count = 2
        case.args.max_sample_text_chars = 0
        case.args.autoencoder_metric_bridge_max_sample_text_chars = 0
        case.args.snapshot_evaluation_enabled = True
        monkeypatch.setattr(runner, "sample_train_validation_rows", _SAMPLER)
        monkeypatch.setattr(runner, "load_laws_table", lambda: pytest.fail("unexpected legacy or remote loader"))
        monkeypatch.setattr(runner, "row_to_sample", lambda row: pytest.fail("unexpected mock-vector factory"))
        evaluated_bits, snapshot_rows = [], []
        original_evaluate = runner.AdaptiveModalAutoencoder.evaluate

        def observed_synthetic_evaluate(model, rows, **kwargs):
            # The optimizer is the explicitly synthetic actual_run consumer;
            # source/vector loading and selection above remain native.
            assert rows and all(type(row.embedding_vector) is arrow.MappedEmbeddingVector for row in rows)
            evaluated_bits.append({row.citation: _bits(row.embedding_vector) for row in rows})
            return original_evaluate(model, rows, **kwargs)

        def incomplete_snapshot(snapshot, template, **kwargs):
            del template
            selected = {role: kwargs[role + "_rows"] for role in ("train", "validation")}
            assert all(type(row.embedding_vector) is list for rows in selected.values() for row in rows)
            snapshot_rows.append((snapshot, selected))
            return {"synthetic_fixture": True, "snapshot_complete": False,
                    "aggregate": {"complete": False}, "evaluation_performed": False,
                    "proof": {"attempted_count": 0, "valid_count": 0}}

        monkeypatch.setattr(runner.AdaptiveModalAutoencoder, "evaluate", observed_synthetic_evaluate)
        monkeypatch.setattr(runner, "evaluate_production_snapshot_bundle", incomplete_snapshot)
        yield SimpleNamespace(case=case, registry=registry, spec=spec, issued=issued, descriptor=descriptor,
            evaluated_bits=evaluated_bits, snapshot_rows=snapshot_rows,
            arrow_path=Path(spec.arrow_embedding_inputs_artifact.path))


def test_native_mapped_inputs_reach_primary_consumers_and_detached_snapshot_survives_close(mapped_run):
    value, case = mapped_run, mapped_run.case
    assert runner.run_guarded_uscode_modal_daemon(case.args) == 0
    summary = case.summary()
    assert summary["corpus_inputs"]["closed"] is True
    assert summary["corpus_inputs"]["input_integrity_verified"] is True
    assert summary["corpus_inputs"]["poisoned"] is False
    assert summary["corpus_input_descriptor"] == value.descriptor.to_dict()
    assert case.seen.sessions == []
    expected = {row.citation: _bits(row.embedding_vector) for row in
                (*value.spec.samples, *value.spec.validation_samples)}
    assert value.evaluated_bits and {key for seen in value.evaluated_bits for key in seen} == set(expected)
    assert all(bits == expected[key] for seen in value.evaluated_bits for key, bits in seen.items())
    train, kwargs = case.seen.projections[0]
    validation = kwargs["validation_samples"]
    assert {row.citation for row in train} == {row.citation for row in value.spec.samples}
    assert {row.citation for row in validation} == {row.citation for row in value.spec.validation_samples}
    assert len(train) == len(validation) == 2
    for sample in [*train, *validation]:
        assert type(sample.embedding_vector) is arrow.MappedEmbeddingVector
        with pytest.raises(arrow.ArrowInputError, match="closed"):
            list(sample.embedding_vector)

    snapshot, detached = value.snapshot_rows[0]
    assert len(value.snapshot_rows) == 1
    for role, originals in (("train", train), ("validation", validation)):
        assert [row.sample_id for row in detached[role]] == [row.sample_id for row in originals]
        for row in detached[role]:
            assert type(row.embedding_vector) is list
            assert _bits(row.embedding_vector) == expected[row.citation]
            assert json.loads(row.to_json())["citation"] == row.citation
    assert summary["snapshot_shutdown"]["drained"] is True
    assert summary["latest_promoted_snapshot_complete"] is False

    checkpoint = runner.load_autoencoder_checkpoint(
        case.root / "workspace/todo-queues" / f"{case.args.run_id}.state.json")
    metadata = checkpoint.manifest.metadata
    assert metadata["corpus_input_provenance"] == summary["corpus_input_provenance"]
    assert snapshot.metadata["corpus_input_provenance"] == metadata["corpus_input_provenance"]
    arrow_ref = value.spec.arrow_embedding_inputs_artifact
    assert metadata["corpus_input_provenance"]["arrow_embedding_inputs_artifact"] == {
        "sha256": arrow_ref.sha256, "bytes": arrow_ref.bytes}
    assert summary["corpus_inputs"]["arrow_embedding_inputs_artifact"] == {
        "sha256": arrow_ref.sha256, "bytes": arrow_ref.bytes}
    assert summary["corpus_inputs"]["job_schema_version"] == "autoencoder-training-job-v7"
    assert metadata["corpus_input_provenance"]["arrow_embedding_inputs_verification"] == (
        summary["corpus_inputs"]["corpus_verification"]["arrow_embedding_inputs_verification"])
    assert summary["corpus_inputs"]["embedding_input_storage"] == "arrow_mapped_float32"
    assert metadata["corpus_input_provenance"]["embedding_input_storage"] == "arrow_mapped_float32"
    assert all(writer._closed for writer in case.seen.writers)


def test_same_inode_arrow_mutation_after_consumption_blocks_persistence_and_closes_views(mapped_run, monkeypatch):
    value, case = mapped_run, mapped_run.case
    case.args.snapshot_evaluation_enabled = False
    original_projection = runner.AdaptiveModalAutoencoder.train_generalizable_projection
    before = value.arrow_path.stat()

    def corrupt_after_synthetic_projection(model, rows, **kwargs):
        assert all(type(row.embedding_vector) is arrow.MappedEmbeddingVector for row in rows)
        result = original_projection(model, rows, **kwargs)
        # Change only framing, preserving size and mapped numeric buffer pages;
        # later file-integrity checks must reject the original content binding.
        with value.arrow_path.open("r+b") as stream:
            first = stream.read(1)
            stream.seek(0)
            stream.write(bytes([first[0] ^ 1]))
            stream.flush()
        assert value.arrow_path.stat().st_ino == before.st_ino
        assert value.arrow_path.stat().st_size == before.st_size
        return result

    monkeypatch.setattr(runner.AdaptiveModalAutoencoder, "train_generalizable_projection", corrupt_after_synthetic_projection)
    with pytest.raises((inputs.DaemonCorpusInputError, arrow.ArrowInputError), match="changed|identity|hash|checksum"):
        runner.run_guarded_uscode_modal_daemon(case.args)
    assert value.evaluated_bits and len(case.seen.projections) == 1
    assert case.seen.checkpoint_writes == []
    summary = case.summary()
    assert summary["final_state_persistence"]["checkpoint_enqueued"] is False
    assert summary["corpus_input_failure"]
    assert summary["corpus_inputs"]["closed"] is True
    assert summary["corpus_inputs"]["poisoned"] is True
    assert not (case.root / "workspace/todo-queues" / f"{case.args.run_id}.state.json").exists()
    for rows, kwargs in case.seen.projections:
        for row in [*rows, *kwargs["validation_samples"]]:
            with pytest.raises(arrow.ArrowInputError, match="closed"):
                list(row.embedding_vector)
    assert all(writer._closed for writer in case.seen.writers)
