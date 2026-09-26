"""Mapped-vector snapshot lifetimes, without inference, training or proof work.

The real Arrow fixture declares synthetic embedding provenance. Tests exercise
native sample deepcopy, CPU snapshot evaluation and the real evaluator queue.
Compiler/proof callbacks in the full-bundle case are explicitly empty fixtures;
the embedding evaluator and snapshot aggregation are not replaced. These tests
isolate the copy/queue boundary and do not qualify a full daemon invocation.
"""
from __future__ import annotations

import copy
from threading import Event

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_arrow_inputs as arrow
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import modal_autoencoder as autoencoder
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import uscode_modal_daemon_runner as runner
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.snapshot_evaluator import (
    SnapshotEvaluator,
    SnapshotEvaluatorClosed,
)
from tests.unit.optimizers.logic_theorem_optimizer.test_autoencoder_arrow_sample_adapter import (
    _float_bits,
    _sample,
    mapped_fixture,  # noqa: F401 -- shared real IPC fixture, explicitly synthetic vectors
)


def _snapshot(template, sample, *, sequence=1):
    return runner.build_autoencoder_evaluation_snapshot(
        template.state, sequence=sequence, compiler_version="mapped-lifetime-fixture",
        holdout_sample_ids=[sample.sample_id], validation_mode="fixed_canary",
        metadata={"fixture": "synthetic_embedding_declarations_no_inference"})


def _metric(snapshot, template, rows):
    evaluator = runner.autoencoder_for_evaluation_snapshot(snapshot, template)
    return runner._snapshot_autoencoder_metric(
        evaluator, rows, legal_ir_bridge_names=(), legal_ir_evaluate_provers=False,
        legal_ir_parallel_workers=1, max_bridge_sample_text_chars=0)


def test_detached_published_rows_evaluate_exactly_after_mapping_closes(mapped_fixture):
    mapping, record, values = mapped_fixture
    source = _sample(record, mapping.row(record.record_id))
    ordinary = _sample(record, values)
    template = autoencoder.AdaptiveModalAutoencoder(compute_device="python")
    snapshot = _snapshot(template, source)
    state_before = template.state.to_json()
    expected = _metric(snapshot, template, [ordinary])

    # This is the existing daemon publication expression. No publisher helper
    # exists independently of main; this test isolates its copy operation.
    published_rows = tuple(copy.deepcopy([source]))
    assert published_rows[0] is not source
    assert type(published_rows[0].embedding_vector) is list
    assert _float_bits(published_rows[0].embedding_vector) == _float_bits(values)
    mapping.close()
    with pytest.raises(arrow.ArrowInputError, match="closed"):
        source.to_dict()

    observed = _metric(snapshot, template, published_rows)
    assert observed == expected
    assert observed["sample_count"] == 1
    assert template.state.to_json() == state_before
    assert published_rows[0].to_json() == ordinary.to_json()


def test_inflight_real_snapshot_bundle_finishes_after_nonblocking_close_and_pending_cancellation(mapped_fixture):
    mapping, record, values = mapped_fixture
    source = _sample(record, mapping.row(record.record_id))
    template = autoencoder.AdaptiveModalAutoencoder(compute_device="python")
    first, queued = _snapshot(template, source), _snapshot(template, source, sequence=2)
    state_before = template.state.to_json()
    expected = _metric(first, template, [_sample(record, values)])
    # Capture sample ownership before enqueue, matching the production boundary.
    train_rows = tuple(copy.deepcopy([source]))
    validation_rows = tuple(copy.deepcopy([source]))
    entered, resume = Event(), Event()
    evaluated_sequences, compiler_calls, proof_calls = [], [], []

    def empty_compiler(rows, feature_codec, **kwargs):
        del feature_codec
        for row in rows:
            assert type(row.embedding_vector) is list
            assert _float_bits(row.embedding_vector) == _float_bits(values)
        compiler_calls.append(kwargs["evaluation_role"])
        return {"sample_count": len(rows), "fixture": "no_compiler_evaluation",
            "attempted_count": 0, "valid_count": 0, "autoencoder_guidance_enabled": False,
            "autoencoder_guidance_applied_count": 0, "cosine_similarity": 0.0,
            "cross_entropy_loss": 0.0, "source_copy_reward_hack_penalty": 0.0}

    def empty_proof(row):
        assert _float_bits(row.embedding_vector) == _float_bits(values)
        proof_calls.append(row.sample_id)
        return {"sample_id": row.sample_id, "fixture": "no_proof_evaluation",
            "attempted_count": 0, "valid_count": 0, "failed_count": 0,
            "error_count": 0, "unavailable_count": 0}

    def evaluate(snapshot):
        evaluated_sequences.append(snapshot.sequence)
        entered.set()
        assert resume.wait(10), "test did not release the in-flight callback"
        return runner.evaluate_production_snapshot_bundle(
            snapshot, template, train_rows=train_rows, validation_rows=validation_rows,
            validation_mode="fixed_canary", feature_codec=template.feature_codec,
            legal_ir_bridge_names=(), legal_ir_evaluate_provers=False,
            legal_ir_parallel_workers=1, max_bridge_sample_text_chars=0,
            compiler_metric_fn=empty_compiler, proof_metric_fn=empty_proof)

    evaluator = SnapshotEvaluator(evaluate, queue_capacity=1)
    try:
        evaluator.publish(first)
        assert entered.wait(10)
        evaluator.publish(queued)
        assert evaluator.pending_count == 1
        evaluator.close(wait=False, cancel_pending=True)
        assert evaluator.worker is not None and evaluator.worker.is_alive()
        assert evaluator.summary()["closed"] is True
        assert evaluator.pending_count == 0
        dropped, = evaluator.dropped_snapshots
        assert dropped.dropped_snapshot_id == queued.snapshot_id
        assert dropped.reason == "shutdown_cancelled_unevaluated_snapshot"
        with pytest.raises(SnapshotEvaluatorClosed):
            evaluator.publish(_snapshot(template, source, sequence=3))

        mapping.close()
        with pytest.raises(arrow.ArrowInputError, match="closed"):
            list(source.embedding_vector)
        resume.set()
        result = evaluator.wait_for_result(sequence=1, timeout=20)
        assert result is not None and result.succeeded, None if result is None else result.error
        assert result.versions == first.versions
        assert result.metrics["validation"] == expected
        assert result.metrics["train_sample_count"] == result.metrics["holdout_sample_count"] == 1
        assert result.metrics["snapshot_complete"] is True
        assert result.metrics["proof"]["attempted_count"] == result.metrics["proof"]["valid_count"] == 0
        assert len(compiler_calls) == 4 and proof_calls
        assert evaluated_sequences == [1]
        assert evaluator.wait_for_result(sequence=2, timeout=0) is None
        assert template.state.to_json() == state_before
    finally:
        resume.set()
        evaluator.close(wait=True, cancel_pending=True)
    assert evaluator.worker is not None and not evaluator.worker.is_alive()


def test_uncopied_closed_mapping_becomes_failed_snapshot_evidence(mapped_fixture):
    """Negative control: queueing alone does not extend mapped-owner lifetime."""
    mapping, record, _ = mapped_fixture
    source = _sample(record, mapping.row(record.record_id))
    template = autoencoder.AdaptiveModalAutoencoder(compute_device="python")
    snapshot = _snapshot(template, source)
    mapping.close()
    evaluator = SnapshotEvaluator(lambda item: _metric(item, template, [source]))
    try:
        evaluator.publish(snapshot)
        result = evaluator.wait_for_result(timeout=20)
        assert result is not None and not result.succeeded
        assert "ArrowInputError" in result.error and "closed" in result.error
        assert not evaluator.accept_result(result, snapshot.versions, expected_sequence=1)
    finally:
        evaluator.close(wait=True, cancel_pending=True)
