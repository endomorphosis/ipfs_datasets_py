"""Actual runner lifecycle with synthetic inputs; no native training claims."""

import copy
import json
import random
import signal
import struct
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import uscode_modal_daemon_runner as runner
from tests.unit.optimizers.logic_theorem_optimizer.test_daemon_shared_target_integration import actual_run, _sample


_SAMPLER = runner.sample_train_validation_rows


def _options(path):
    return ["--autoencoder-corpus-input", str(path),
            "--autoencoder-corpus-input-sha256", "a" * 64,
            "--autoencoder-corpus-input-bytes", "123"]


def test_cli_triplet_forwarded_only_to_autoencoder_child(tmp_path):
    parser = runner.build_uscode_modal_daemon_arg_parser()
    options = _options(tmp_path / "owner.snapshot")
    args = parser.parse_args(["--run-id", "corpus-cli", "--validation-canary-count", "0", *options])
    paired = runner.build_paired_daemon_commands(args, module_name=runner.__name__)
    for flag, value in zip(options[::2], options[1::2]):
        assert paired["autoencoder_command"][paired["autoencoder_command"].index(flag) + 1] == value
        assert flag not in paired["codex_command"]
    default = runner.build_paired_daemon_commands(parser.parse_args(["--run-id", "legacy-cli"]),
                                                 module_name=runner.__name__)
    assert all(flag not in default["autoencoder_command"] for flag in options[::2])


@pytest.mark.parametrize("kind", ["partial", "count", "indices"])
def test_bad_options_reject_before_input_or_writer_creation(kind, tmp_path, monkeypatch):
    parser = runner.build_uscode_modal_daemon_arg_parser()
    options = _options(tmp_path / "owner.snapshot")
    args = parser.parse_args(["--run-id", "reject", "--validation-canary-count", "0",
                              *(options[:2] if kind == "partial" else options)])
    if kind == "count":
        args.validation_canary_count = 1
    if kind == "indices":
        args.validation_canary_indices = "0"
    monkeypatch.setattr(runner, "VerifiedDaemonCorpusInputs", lambda *a: pytest.fail("input opened"))
    monkeypatch.setattr(runner, "AsyncArtifactWriter", lambda *a, **k: pytest.fail("writer opened"))
    with pytest.raises(ValueError):
        runner.run_guarded_uscode_modal_daemon(args)
    with pytest.raises(ValueError):
        runner.build_paired_daemon_commands(args, module_name=runner.__name__)


class Inventory:
    row_count = 6

    def __init__(self):
        self.built = []

    def indices_for(self, role):
        return (0, 1, 2) if role == "train" else (3, 4, 5)

    def text_length(self, index):
        return 100 if index == 1 else 10

    def build_sample(self, index):
        self.built.append(index)
        return SimpleNamespace(sample_id=f"row-{index}", text="x" * self.text_length(index))


def test_partition_sampling_preserves_full_range_rng_rejection_counts_caps_and_exclusions():
    inventory = Inventory()
    rng, reference_rng = random.Random(14), random.Random(14)
    expected, attempts, selected = [], 0, set()
    for allowed, blocked in (({0, 1, 2}, {"row-2"}), ({3, 4, 5}, {"row-4"})):
        while True:
            attempts += 1
            index = reference_rng.randrange(6)
            if index in selected or index not in allowed or inventory.text_length(index) > 20:
                continue
            if f"row-{index}" in blocked:
                continue
            selected.add(index)
            expected.append(index)
            break
    ti, train, vi, validation, actual_attempts = _SAMPLER(
        None, rng, train_count=1, validation_count=1, corpus_inputs=inventory,
        max_sample_text_chars=20, blocked_train_sample_ids={"row-2"},
        blocked_validation_sample_ids={"row-4"},
    )
    assert ti + vi == expected and actual_attempts == attempts
    assert [sample.sample_id for sample in train + validation] == [f"row-{i}" for i in expected]
    assert rng.getstate() == reference_rng.getstate()
    assert 1 not in inventory.built


def test_insufficient_inventory_fails_before_rng_or_sample_build():
    inventory, rng = Inventory(), random.Random(9)
    before = rng.getstate()
    with pytest.raises(ValueError, match="insufficient train inventory"):
        _SAMPLER(None, rng, train_count=3, validation_count=1,
                 max_sample_text_chars=20, corpus_inputs=inventory)
    assert rng.getstate() == before and inventory.built == []


def test_blocked_ids_retain_bounded_rejection_without_fallback():
    inventory = Inventory()
    with pytest.raises(RuntimeError, match="Unable to sample"):
        runner._sample_one_row(None, random.Random(9), selected_indices=set(),
                               corpus_inputs=inventory, corpus_role="train", max_attempts=7,
                               blocked_sample_ids={"row-0", "row-1", "row-2"})
    assert len(inventory.built) <= 7


@pytest.fixture
def corpus_run(actual_run, monkeypatch):
    case = actual_run
    for name in ("autoencoder_target_bundle", "autoencoder_target_bundle_sha256",
                 "autoencoder_target_bundle_bytes", "autoencoder_target_snapshot_id"):
        setattr(case.args, name, None)
    case.args.autoencoder_corpus_input = str(case.root / "owner.snapshot")
    case.args.autoencoder_corpus_input_sha256 = "a" * 64
    case.args.autoencoder_corpus_input_bytes = 123
    case.seen.corpora = []
    case.seen.corpus_failure = None
    case.seen.selected_failure = False
    case.seen.corpus_events = []

    class Corpus:
        row_count = 2

        def __init__(self, descriptor):
            self.closed, self.counts, self.selected = False, {}, 0
            case.seen.corpora.append(self)
            if case.seen.corpus_failure == ("constructor", 1):
                raise ValueError("synthetic corpus constructor failure")

        def indices_for(self, role):
            return (0,) if role == "train" else (1,)

        def text_length(self, index):
            return len(_sample(index).text)

        def record_id(self, index):
            return f"record-{index}"

        def build_sample(self, index):
            return copy.deepcopy(_sample(index))

        def verify_selected(self, indices, samples, *, role):
            self.selected += 1
            assert indices == list(self.indices_for(role))
            for index, sample in zip(indices, samples):
                expected = _sample(index)
                if sample.text != expected.text or b"".join(struct.pack("!d", x) for x in sample.embedding_vector) != (
                    b"".join(struct.pack("!d", x) for x in expected.embedding_vector)
                ):
                    raise ValueError("synthetic selected source or vector changed")
            if case.seen.selected_failure and self.selected > 2:
                raise ValueError("synthetic selected source or vector changed")

        def verify_boundary(self, phase):
            assert not self.closed
            self.counts[phase] = self.counts.get(phase, 0) + 1
            case.seen.corpus_events.append(phase)
            if case.seen.corpus_failure == (phase, self.counts[phase]):
                raise ValueError(f"synthetic corpus failure: {phase}")

        def close(self):
            self.closed = True

        def summary(self):
            return {"synthetic_fixture": True, "closed": self.closed,
                    "counts": {"selected_checks": self.selected, **self.counts},
                    "job_spec_sha256": "b" * 64, "variant_manifest_sha256": "c" * 64,
                    "corpus_verification": {
                        "dataset_snapshot_id": "dataset:fixture", "split_snapshot_id": "split:fixture",
                        "corpus_index_verification": {"index_sha256": "d" * 64},
                        "embedding_production_verification": {"sha256": "e" * 64, "bytes": 456},
                    }}

    monkeypatch.setattr(runner, "VerifiedDaemonCorpusInputs", Corpus)
    monkeypatch.setattr(runner, "sample_train_validation_rows", _SAMPLER)
    monkeypatch.setattr(runner, "load_laws_table", lambda: pytest.fail("network/default corpus fallback"))
    monkeypatch.setattr(runner, "row_to_sample", lambda row: pytest.fail("legacy/mock vector factory"))
    return case


def test_actual_run_consumes_local_samples_and_persists_identity(corpus_run):
    case = corpus_run
    assert runner.run_guarded_uscode_modal_daemon(case.args) == 0
    identity = {"sha256": "a" * 64, "bytes": 123}
    assert case.summary()["corpus_input_identity"] == identity
    assert case.summary()["corpus_inputs"]["closed"] is True
    assert case.seen.corpora[0].selected == 4
    assert all(call[1]["corpus_input_identity"] == identity for call in case.seen.lineages)
    assert all(row["metadata"]["corpus_input_identity"] == identity for row in case.seen.checkpoint_writes)
    state = runner.load_autoencoder_checkpoint(case.root / "workspace/todo-queues" / f"{case.args.run_id}.state.json")
    assert state.manifest.metadata["corpus_input_identity"] == identity
    provenance = state.manifest.metadata["corpus_input_provenance"]
    assert provenance["descriptor"] == case.summary()["corpus_input_descriptor"]
    assert provenance["job_spec_sha256"] == "b" * 64
    assert provenance["index_sha256"] == "d" * 64
    assert provenance["embedding_production_artifact"] == {"sha256": "e" * 64, "bytes": 456}
    assert case.seen.corpus_events.index("before_persistence") < case.seen.corpus_events.index("checkpoint_enqueue")


@pytest.mark.parametrize("phase, writes", [
    ("before_sampling", 0), ("before_consume", 0), ("before_persistence", 0),
    ("checkpoint_enqueue", 0), ("shutdown", 1), ("final_checkpoint", 1),
])
def test_boundary_failure_blocks_new_and_clean_shutdown_writes(corpus_run, phase, writes):
    case = corpus_run
    case.seen.corpus_failure = (phase, 1)
    with pytest.raises(ValueError, match=phase):
        runner.run_guarded_uscode_modal_daemon(case.args)
    assert len(case.seen.checkpoint_writes) == writes
    assert all(row["metadata"].get("reason") != "clean_shutdown" for row in case.seen.checkpoint_writes)
    assert case.summary()["final_state_persistence"]["checkpoint_enqueued"] is False
    assert case.summary()["corpus_input_failure"]["phase"] == phase
    assert case.seen.corpora[0].closed
    assert all(writer._closed for writer in case.seen.writers)


def test_failure_after_prior_valid_cycle_preserves_only_prior_checkpoint(corpus_run):
    case = corpus_run
    case.args.max_cycles = 2
    case.seen.corpus_failure = ("before_persistence", 2)
    with pytest.raises(ValueError, match="before_persistence"):
        runner.run_guarded_uscode_modal_daemon(case.args)
    assert [row["cycle"] for row in case.seen.checkpoint_writes] == [1]
    assert case.summary()["cycles"] == 1


def test_selected_sample_mutation_cannot_be_persisted(corpus_run):
    case = corpus_run
    case.seen.selected_failure = True
    with pytest.raises(ValueError, match="selected source or vector changed"):
        runner.run_guarded_uscode_modal_daemon(case.args)
    assert case.seen.checkpoint_writes == [] and case.seen.corpora[0].closed


def test_startup_checkpoint_guard_and_cleanup(corpus_run, monkeypatch):
    case = corpus_run
    original = runner.ModalAutoencoderTrainingState.compact_generalizable_capacity

    def compact(state, *args, **kwargs):
        report = original(state, *args, **kwargs)
        return {**report, "compacted": True}

    monkeypatch.setattr(runner.ModalAutoencoderTrainingState, "compact_generalizable_capacity", compact)
    case.seen.corpus_failure = ("startup_checkpoint", 1)
    before_writer = getattr(runner._ASYNC_SUMMARY_WRITER, "writer", None)
    handlers = {number: signal.getsignal(number) for number in (signal.SIGINT, signal.SIGTERM)}
    with pytest.raises(ValueError, match="startup_checkpoint"):
        runner.run_guarded_uscode_modal_daemon(case.args)
    assert case.seen.checkpoint_writes == [] and case.seen.corpora[0].closed
    assert all(writer._closed for writer in case.seen.writers)
    assert getattr(runner._ASYNC_SUMMARY_WRITER, "writer", None) is before_writer
    assert {number: signal.getsignal(number) for number in handlers} == handlers
    assert case.summary()["corpus_input_failure"]["phase"] == "startup_checkpoint"


@pytest.mark.parametrize("change", ["removed", "changed", "summary_removed", "summary_unbound"])
def test_restart_cannot_replace_or_drop_bound_input_identity(corpus_run, change):
    case = corpus_run
    assert runner.run_guarded_uscode_modal_daemon(case.args) == 0
    writer_count = len(case.seen.writers)
    if change == "summary_removed":
        (case.root / "workspace/test-logs" / f"{case.args.run_id}.summary").unlink()
    if change == "summary_unbound":
        (case.root / "workspace/test-logs" / f"{case.args.run_id}.summary").write_text("{}")
    if change == "changed":
        case.args.autoencoder_corpus_input_sha256 = "b" * 64
    else:
        for name in ("autoencoder_corpus_input", "autoencoder_corpus_input_sha256", "autoencoder_corpus_input_bytes"):
            setattr(case.args, name, None)
    with pytest.raises(ValueError, match="descriptor|identity"):
        runner.run_guarded_uscode_modal_daemon(case.args)
    assert len(case.seen.writers) == writer_count


def test_unbound_completed_run_cannot_acquire_input_identity(corpus_run):
    case = corpus_run
    summary_path = case.root / "workspace/test-logs" / f"{case.args.run_id}.summary"
    summary_path.parent.mkdir(parents=True)
    summary_path.write_text(json.dumps({"cycles": 1}))
    with pytest.raises(ValueError, match="existing unbound"):
        runner.run_guarded_uscode_modal_daemon(case.args)
    assert case.seen.writers == [] and case.seen.corpora == []


def test_default_actual_run_omits_input_session_and_lineage(actual_run, monkeypatch):
    case = actual_run
    monkeypatch.setattr(runner, "VerifiedDaemonCorpusInputs", lambda *a: pytest.fail("unexpected input session"))
    assert runner.run_guarded_uscode_modal_daemon(case.args) == 0
    assert "corpus_input_identity" not in case.summary()
    assert all("corpus_input_identity" not in kwargs for _, kwargs in case.seen.lineages)


def test_constructor_failure_happens_before_any_writer(corpus_run):
    case = corpus_run
    case.seen.corpus_failure = ("constructor", 1)
    with pytest.raises(ValueError, match="constructor failure"):
        runner.run_guarded_uscode_modal_daemon(case.args)
    assert case.seen.writers == []


def test_replayed_checkpoint_binding_is_checked_before_state_consumption(corpus_run, monkeypatch):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder_checkpoint import serialize_checkpoint

    case = corpus_run
    state_path = case.root / "workspace/todo-queues" / f"{case.args.run_id}.state.json"

    def replay(writer):
        state_path.write_bytes(serialize_checkpoint(
            runner.ModalAutoencoderTrainingState(),
            metadata={"corpus_input_identity": {"sha256": "f" * 64, "bytes": 123}},
        ))
        return [SimpleNamespace(to_dict=lambda: {"synthetic_fixture": True})]

    monkeypatch.setattr(runner.AsyncArtifactWriter, "replay_crash_artifacts", replay)
    monkeypatch.setattr(runner, "load_autoencoder_checkpoint", lambda *a, **k:
                        pytest.fail("conflicting replayed checkpoint consumed"))
    with pytest.raises(ValueError, match="checkpoint corpus input identity"):
        runner.run_guarded_uscode_modal_daemon(case.args)
    assert case.seen.corpora[0].closed and all(writer._closed for writer in case.seen.writers)
    assert case.seen.checkpoint_writes == []


@pytest.mark.parametrize("cleanup_failure", [False, True])
def test_replay_without_descriptor_closes_writer_and_preserves_rejection(actual_run, monkeypatch, cleanup_failure):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_autoencoder_checkpoint import serialize_checkpoint

    case = actual_run
    state_path = case.root / "workspace/todo-queues" / f"{case.args.run_id}.state.json"
    previous_writer = getattr(runner._ASYNC_SUMMARY_WRITER, "writer", None)
    handlers = {number: signal.getsignal(number) for number in (signal.SIGINT, signal.SIGTERM)}

    def replay(writer):
        state_path.write_bytes(serialize_checkpoint(
            runner.ModalAutoencoderTrainingState(),
            metadata={"corpus_input_identity": {"sha256": "a" * 64, "bytes": 123}},
        ))
        return [SimpleNamespace(to_dict=lambda: {"synthetic_fixture": True})]

    original_close = runner.AsyncArtifactWriter.close

    def close(writer, **kwargs):
        result = original_close(writer, **kwargs)
        if cleanup_failure:
            raise OSError("synthetic writer cleanup failure")
        return result

    monkeypatch.setattr(runner.AsyncArtifactWriter, "replay_crash_artifacts", replay)
    monkeypatch.setattr(runner.AsyncArtifactWriter, "close", close)
    monkeypatch.setattr(runner, "load_autoencoder_checkpoint", lambda *a, **k:
                        pytest.fail("bound checkpoint consumed without descriptor"))
    with pytest.raises(ValueError, match="checkpoint corpus input identity") as caught:
        runner.run_guarded_uscode_modal_daemon(case.args)
    if cleanup_failure:
        assert isinstance(caught.value.__cause__, OSError)
    assert len(case.seen.writers) == 1 and case.seen.writers[0]._closed
    assert case.seen.evaluations == case.seen.projections == case.seen.checkpoint_writes == []
    assert getattr(runner._ASYNC_SUMMARY_WRITER, "writer", None) is previous_writer
    assert {number: signal.getsignal(number) for number in handlers} == handlers


def test_loaded_binding_rejection_without_descriptor_restores_startup_context(actual_run, monkeypatch):
    case = actual_run
    state_path = case.root / "workspace/todo-queues" / f"{case.args.run_id}.state.json"
    state_path.parent.mkdir(parents=True)
    state_path.write_text("{}")
    previous_writer = getattr(runner._ASYNC_SUMMARY_WRITER, "writer", None)
    handlers = {number: signal.getsignal(number) for number in (signal.SIGINT, signal.SIGTERM)}
    # Simulate a different binding observed by the normal state loader after
    # metadata preflight; the new guard must reject before state consumption.
    monkeypatch.setattr(runner, "load_autoencoder_checkpoint", lambda *a, **k: SimpleNamespace(
        manifest=SimpleNamespace(metadata={"corpus_input_identity": {"sha256": "a" * 64, "bytes": 123}}),
        delta_manifests=(), state=object(),
    ))
    with pytest.raises(ValueError, match="replayed checkpoint corpus input identity"):
        runner.run_guarded_uscode_modal_daemon(case.args)
    assert len(case.seen.writers) == 1 and case.seen.writers[0]._closed
    assert case.seen.evaluations == case.seen.projections == case.seen.checkpoint_writes == []
    assert getattr(runner._ASYNC_SUMMARY_WRITER, "writer", None) is previous_writer
    assert {number: signal.getsignal(number) for number in handlers} == handlers


def test_startup_failure_after_thread_setup_closes_all_resources(corpus_run, monkeypatch):
    case = corpus_run
    case.args.snapshot_evaluation_enabled = True
    evaluators = []
    original = runner.SnapshotEvaluator.__init__

    def initialized(evaluator, *args, **kwargs):
        original(evaluator, *args, **kwargs)
        evaluators.append(evaluator)

    monkeypatch.setattr(runner.SnapshotEvaluator, "__init__", initialized)
    monkeypatch.setattr(runner, "ModalTodoSupervisor", lambda **kwargs:
                        (_ for _ in ()).throw(ValueError("synthetic startup consumer failure")))
    with pytest.raises(ValueError, match="startup consumer failure"):
        runner.run_guarded_uscode_modal_daemon(case.args)
    assert evaluators and all(evaluator._closed for evaluator in evaluators)
    assert all(writer._closed for writer in case.seen.writers)
    assert case.seen.corpora[0].closed and case.seen.checkpoint_writes == []


def test_startup_diagnostic_write_failure_preserves_primary(corpus_run, monkeypatch):
    from pathlib import Path

    case = corpus_run
    primary = ValueError("synthetic startup primary")
    monkeypatch.setattr(runner, "ModalTodoSupervisor", lambda **kwargs:
                        (_ for _ in ()).throw(primary))
    original = Path.write_text

    def write(path, *args, **kwargs):
        if path.suffix == ".summary":
            raise OSError("synthetic diagnostic write failure")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", write)
    with pytest.raises(ValueError) as caught:
        runner.run_guarded_uscode_modal_daemon(case.args)
    assert caught.value is primary and isinstance(caught.value.__cause__, OSError)
    assert case.seen.corpora[0].closed and all(writer._closed for writer in case.seen.writers)


def test_async_snapshots_stay_enabled_and_post_drain_guard_blocks_promotion(corpus_run, monkeypatch):
    case = corpus_run
    case.args.snapshot_evaluation_enabled = True
    case.seen.corpus_failure = ("post_snapshot_drain", 1)
    snapshots, copied_jobs, evaluators = [], [], []

    class Evaluator:
        def __init__(self, callback, **kwargs):
            self.closed = False
            self.jobs = dict(zip(callback.__code__.co_freevars,
                                 (cell.cell_contents for cell in callback.__closure__)))["snapshot_evaluation_jobs"]
            evaluators.append(self)

        def summary(self):
            return {"enabled": True, "closed": self.closed}

        def before_training_step(self, **kwargs):
            return 0

        def publish(self, snapshot):
            snapshots.append(snapshot)
            copied_jobs.append(self.jobs[snapshot.snapshot_id])
            return []

        def poll_results(self):
            return [SimpleNamespace(snapshot_id="pending")] if self.closed else []

        def wait_until_idle(self, **kwargs):
            assert not case.seen.corpora[0].closed
            return True

        def close(self, **kwargs):
            self.closed = True

        def accept_result(self, *args, **kwargs):
            pytest.fail("unverified pending result accepted")

    monkeypatch.setattr(runner, "SnapshotEvaluator", Evaluator)
    monkeypatch.setattr(runner, "_matching_published_snapshot_boundary", lambda *a, **k:
                        SimpleNamespace(sequence=1, versions=SimpleNamespace()))
    with pytest.raises(ValueError, match="post_snapshot_drain"):
        runner.run_guarded_uscode_modal_daemon(case.args)
    assert len(snapshots) == len(case.seen.checkpoint_writes) == 1
    assert snapshots[0].metadata["corpus_input_identity"] == {"sha256": "a" * 64, "bytes": 123}
    assert copied_jobs[0]["train_rows"][0].embedding_vector == _sample(0).embedding_vector
    assert copied_jobs[0]["train_rows"][0] is not case.seen.projections[0][0][0]
    assert all(evaluator.closed for evaluator in evaluators)
    assert case.summary()["snapshot_shutdown"]["unmatched_result_ids"] == ["pending"]
    assert case.summary()["final_state_persistence"]["checkpoint_enqueued"] is False
