"""Synthetic actual-run wiring and failure boundaries; no native qualification."""

from dataclasses import replace
import json
import signal
from types import SimpleNamespace

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import modal_autoencoder as modal
from ipfs_datasets_py.optimizers.logic_theorem_optimizer import uscode_modal_daemon_runner as runner
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_samples import LegalSample
from ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_ir import ModalIRDocument


def _sample(index=0):
    text = f"The agency shall retain record {index}."
    return LegalSample(
        f"synthetic-daemon-{index}", "us_code", "5", str(index), f"5 U.S.C. {index}",
        text, text, "mock:synthetic-daemon", [0.25, -0.0, 0.5, -0.25],
        ModalIRDocument(f"synthetic-daemon-{index}", "us_code", text),
    )


def _evaluation(rows, *, target_count=0):
    return modal.AutoencoderEvaluation(
        len(rows), 0.5, 0.5, 0.5, 1.0, 0.0, 0.0,
        {sample.sample_id: list(sample.embedding_vector) for sample in rows},
        legal_ir_target_count=target_count,
        legal_ir_losses={"synthetic_bridge_loss": 0.25} if target_count else {},
    )


def _evaluate(autoencoder, rows, *, targets=None, bridges=("deontic_norms",), cap=0):
    kwargs = {} if targets is None else {"legal_ir_targets": targets}
    return runner.evaluate_autoencoder_with_bounded_metric_bridges(
        autoencoder, rows, legal_ir_bridge_names=bridges, legal_ir_evaluate_provers=False,
        legal_ir_parallel_workers=1, max_bridge_sample_text_chars=cap,
        use_sample_memory=False, **kwargs,
    )


def test_bounded_helper_injects_only_bridge_pass_and_preserves_custom_two_pass():
    samples, calls = [_sample()], []
    targets = {samples[0].sample_id: object()}

    class Consumer:
        def evaluate(self, rows, **kwargs):
            calls.append((list(rows), kwargs))
            return _evaluation(rows, target_count=len(rows) if kwargs["legal_ir_bridge_names"] else 0)

    result = _evaluate(Consumer(), samples, targets=targets)
    assert len(calls) == 2
    assert calls[0][1]["legal_ir_targets"] is targets
    assert calls[0][1]["legal_ir_bridge_names"] == ["deontic_norms"]
    assert calls[1][1]["legal_ir_bridge_names"] == ()
    assert "legal_ir_targets" not in calls[1][1]
    assert result.legal_ir_target_count == 1


@pytest.mark.parametrize("rows", [[], [_sample()]])
def test_bridge_off_ignores_supplied_targets_without_new_kwargs(rows):
    calls = []

    class Consumer:
        def evaluate(self, selected, **kwargs):
            calls.append(kwargs)
            return _evaluation(selected)

    result = _evaluate(Consumer(), rows, targets={"unrelated": object()}, bridges=())
    assert result.legal_ir_target_count == 0
    assert len(calls) == 1 and "legal_ir_targets" not in calls[0]


@pytest.mark.parametrize("failure", ["missing", "clones"])
def test_explicit_target_mapping_fails_before_partial_or_clone_evaluation(failure):
    sample = _sample()
    if failure == "clones":
        sample = replace(sample, text=sample.text * 10)
    targets = {} if failure == "missing" else {sample.sample_id: object()}

    class Forbidden:
        def evaluate(self, *args, **kwargs):
            raise AssertionError("incomplete or wrong-identity target map must not be consumed")

    with pytest.raises(ValueError):
        _evaluate(Forbidden(), [sample], targets=targets, cap=40 if failure == "clones" else 0)


@pytest.mark.parametrize("method", ["evaluate", "train_generalizable_projection", "alias_cached_legal_ir_targets"])
def test_native_eligibility_rejects_each_custom_method(method, monkeypatch):
    model = modal.AdaptiveModalAutoencoder(compute_device="python")
    assert runner._daemon_shared_target_skip_reason(model, [_sample()], max_bridge_sample_text_chars=0) is None
    monkeypatch.setattr(model, method, lambda *args, **kwargs: None)
    assert runner._daemon_shared_target_skip_reason(
        model, [_sample()], max_bridge_sample_text_chars=0,
    ) == "non_native_consumer"


@pytest.mark.parametrize("helper", ["runner", "projection"])
def test_native_eligibility_requires_both_bounding_helpers_to_keep_objects(helper, monkeypatch):
    sample = _sample()
    clone = replace(sample)
    assert clone == sample and clone is not sample
    owner, name = ((runner, "autoencoder_metric_bridge_samples_for_evaluation") if helper == "runner"
                   else (modal, "_bounded_legal_ir_metric_samples"))
    monkeypatch.setattr(owner, name, lambda rows, **kwargs: [clone])
    assert runner._daemon_shared_target_skip_reason(
        modal.AdaptiveModalAutoencoder(compute_device="python"), [sample],
        max_bridge_sample_text_chars=600,
    ) == "bounded_clones"


def test_bundle_identity_extends_lineage_without_changing_default_shape():
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.legal_ir_evaluation_cache import configuration_digest

    kwargs = dict(state_hash="state", compiler_commit="compiler", legal_ir_bridge_names=("deontic_norms",),
                  legal_ir_evaluate_provers=False, legal_ir_parallel_workers=1,
                  max_bridge_sample_text_chars=600, use_sample_memory=False)
    default = runner.autoencoder_evaluation_lineage([_sample()], **kwargs)
    absent = runner.autoencoder_evaluation_lineage([_sample()], target_bundle_identity=None, **kwargs)
    identity = {"artifact_sha256": "a" * 64, "snapshot_id": "sha256:" + "b" * 64,
                "config_sha256": "c" * 64, "selection_sha256": "d" * 64}
    bound = runner.autoencoder_evaluation_lineage([_sample()], target_bundle_identity=identity, **kwargs)
    other = runner.autoencoder_evaluation_lineage(
        [_sample()], target_bundle_identity={**identity, "artifact_sha256": "e" * 64}, **kwargs)
    assert default.to_dict() == absent.to_dict()
    legacy_configuration = {
        "compiler_commit": "compiler", "evaluation_kind": "full_family_autoencoder",
        "legal_ir_bridge_names": ["deontic_norms"], "legal_ir_evaluate_provers": False,
        "legal_ir_parallel_workers": 1, "max_bridge_sample_text_chars": 600,
        "use_sample_memory": False,
    }
    assert default.evaluator_hash == configuration_digest(legacy_configuration)
    assert bound.evaluator_hash == configuration_digest({
        **legacy_configuration, "target_bundle_identity": identity})
    assert bound.samples_hash == default.samples_hash and bound.state_hash == default.state_hash
    assert len({default.digest, bound.digest, other.digest}) == 3


def test_cli_descriptor_forwarded_only_to_paired_autoencoder_child(tmp_path):
    options = ["--autoencoder-target-bundle", str(tmp_path / "synthetic.bundle"),
               "--autoencoder-target-bundle-sha256", "a" * 64,
               "--autoencoder-target-bundle-bytes", "123",
               "--autoencoder-target-snapshot-id", "sha256:" + "b" * 64]
    parser = runner.build_uscode_modal_daemon_arg_parser()
    args = parser.parse_args(["--run-id", "synthetic-shared", *options])
    paired = runner.build_paired_daemon_commands(args, module_name=runner.__name__)
    for flag, expected in zip(options[::2], options[1::2]):
        command = paired["autoencoder_command"]
        assert command[command.index(flag) + 1] == expected
        assert flag not in paired["codex_command"]
        assert all(flag not in child["command"] for child in paired.get("codex_children", []))
    default = runner.build_paired_daemon_commands(
        parser.parse_args(["--run-id", "synthetic-default"]), module_name=runner.__name__)
    assert not any(flag in default["autoencoder_command"] for flag in options[::2])


@pytest.fixture
def actual_run(monkeypatch, tmp_path):
    """Run actual orchestration with synthetic consumers and no model training.

    Native eligibility is tested separately above; this wiring fixture replaces
    that guard explicitly to let fake model calls expose their exact arguments.
    Artifact verification is exercised separately by target-session tests.
    """
    train, validation = [_sample(0)], [_sample(1)]
    targets = {sample.sample_id: object() for sample in (*train, *validation)}
    seen = SimpleNamespace(evaluations=[], projections=[], sessions=[], events=[], lineages=[],
                           checkpoint_writes=[], promotions=[], sampling_calls=[],
                           fail_begin=0, fail_finish=0, fail_shutdown=False,
                           projection_error=None, skip_reason=None, writers=[])
    parser = runner.build_uscode_modal_daemon_arg_parser()
    args = parser.parse_args([
        "--run-id", "synthetic-target-session", "--duration-seconds", "60", "--max-cycles", "1",
        "--train-count", "1", "--validation-count", "1", "--validation-canary-count", "0",
        "--max-items", "0", "--max-inner-iterations", "1", "--test-every-cycles", "100",
        "--autoencoder-device", "python", "--autoencoder-canonical-warm-start", "off",
        "--snapshot-evaluation-enabled", "false", "--autoencoder-introspection-mode", "off",
        "--daemon-hammer-guidance-enabled", "false", "--bridge-loss-adapters", "none",
        "--bridge-evaluate-provers", "false", "--autoencoder-metric-bridge-adapters", "deontic_norms",
        "--autoencoder-before-train-eval-mode", "always", "--autoencoder-sample-memory-probe-mode", "off",
        "--compiler-ir-train-mode", "off", "--compiler-ir-guided-train-mode", "off",
    ])
    args.autoencoder_target_bundle = str(tmp_path / "synthetic.bundle")
    args.autoencoder_target_bundle_sha256 = "a" * 64
    args.autoencoder_target_bundle_bytes = 123
    args.autoencoder_target_snapshot_id = "sha256:" + "b" * 64

    class Session:
        def __init__(self, descriptor, **kwargs):
            self.descriptor, self.settings = descriptor, kwargs
            self.closed = self.poisoned = self.active = False
            self.begins = self.finishes = 0
            self.current_skip = None
            self.lineage_identity = None
            seen.sessions.append(self)

        def begin_cycle(self, train_rows, validation_rows, *, skip_reason=None):
            self.begins += 1
            self.active = True
            seen.events.append(("begin", self.begins))
            assert list(train_rows) == train and list(validation_rows) == validation
            if seen.fail_begin == self.begins:
                raise ValueError("synthetic producer source drift before use")
            self.current_skip = "bridge_off" if not self.settings["bridge_names"] else skip_reason
            self.lineage_identity = None if self.current_skip else {
                "artifact_sha256": self.descriptor.sha256,
                "snapshot_id": self.descriptor.snapshot_id, "selection_sha256": "c" * 64}
            return None if self.current_skip else targets

        def finish_cycle(self):
            seen.events.append(("finish", self.begins))
            if seen.fail_finish == self.begins:
                raise ValueError("synthetic producer source drift after use")
            self.finishes += 1
            self.active = False
            return {"status": "completed", "applied": self.current_skip is None}

        def abort_cycle(self, error=None):
            self.poisoned, self.active = True, False
            seen.events.append(("abort", type(error).__name__))

        def summary(self):
            return {"synthetic_fixture": True, "closed": self.closed, "poisoned": self.poisoned,
                    "active": self.active, "begins": self.begins, "finishes": self.finishes,
                    "skip_reason": self.current_skip}

        def verify_shutdown(self):
            seen.events.append(("verify_shutdown", self.begins))
            if seen.fail_shutdown:
                raise ValueError("synthetic shutdown producer drift")
            return self.summary()

        def close(self):
            self.closed = True
            seen.events.append(("close", self.begins))

    class Autoencoder:
        def __init__(self, *, state, **kwargs):
            self.state = state

        def compute_backend_metadata(self):
            return {"autoencoder_compute_backend": "synthetic_fixture",
                    "autoencoder_compute_device": "python"}

        def evaluate(self, rows, **kwargs):
            seen.evaluations.append((list(rows), kwargs))
            return _evaluation(rows, target_count=len(rows) if kwargs.get("legal_ir_bridge_names") else 0)

        def train_generalizable_projection(self, rows, **kwargs):
            seen.projections.append((list(rows), kwargs))
            if seen.projection_error is not None:
                raise seen.projection_error
            self.state.legal_ir_view_logits["synthetic_cycle"] = float(len(seen.projections))
            return {"accepted_epochs": 0, "stopped_reason": "synthetic-no-training"}

    def sampling(*args, **kwargs):
        seen.sampling_calls.append(kwargs)
        return [0], train, [1], validation, 2

    original_lineage = runner.autoencoder_evaluation_lineage

    def lineage(rows, **kwargs):
        seen.lineages.append((list(rows), kwargs))
        return original_lineage(rows, **kwargs)

    original_write = runner.AsyncArtifactWriter.write_state_checkpoint
    original_writer_init = runner.AsyncArtifactWriter.__init__

    def writer_init(writer, *args, **kwargs):
        original_writer_init(writer, *args, **kwargs)
        seen.writers.append(writer)

    def write_checkpoint(writer, *args, **kwargs):
        seen.checkpoint_writes.append(kwargs)
        seen.events.append(("checkpoint", kwargs.get("cycle")))
        return original_write(writer, *args, **kwargs)

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(runner, "VerifiedDaemonTargetSession", Session)
    monkeypatch.setattr(runner, "AdaptiveModalAutoencoder", Autoencoder)
    monkeypatch.setattr(runner, "_daemon_shared_target_skip_reason", lambda *args, **kwargs: seen.skip_reason)
    monkeypatch.setattr(runner, "autoencoder_evaluation_lineage", lineage)
    monkeypatch.setattr(runner.AsyncArtifactWriter, "write_state_checkpoint", write_checkpoint)
    monkeypatch.setattr(runner.AsyncArtifactWriter, "__init__", writer_init)
    monkeypatch.setattr(runner, "load_laws_table", lambda: SimpleNamespace(num_rows=2))
    monkeypatch.setattr(runner, "sample_train_validation_rows", sampling)
    monkeypatch.setattr(runner, "compiler_ir_metric_block", lambda *args, **kwargs: {
        "cross_entropy_loss": 1.0, "cosine_similarity": 0.5, "metric_failures": 0})
    monkeypatch.setattr(runner, "bridge_ir_metric_block", lambda *args, **kwargs: {
        "acceptance_rate": 1.0, "metric_failures": 0, "proof_failure_ratio": 0.0, "total_loss": 0.0})
    monkeypatch.setattr(runner, "learned_representation_promotion_report", lambda *args, **kwargs: {})

    def summary():
        return json.loads((tmp_path / "workspace/test-logs" / f"{args.run_id}.summary").read_text())

    return SimpleNamespace(args=args, seen=seen, targets=targets, train=train, validation=validation,
                           summary=summary, root=tmp_path)


def test_actual_runner_delivers_same_full_map_to_evaluation_and_projection(actual_run):
    case = actual_run
    assert runner.run_guarded_uscode_modal_daemon(case.args) == 0
    assert len(case.seen.sessions) == 1
    session = case.seen.sessions[0]
    assert session.settings["bridge_names"] == ["deontic_norms"]
    assert session.settings["evaluate_provers"] is False and session.settings["parallel_workers"] == 1
    assert session.begins == session.finishes == 1 and session.closed and not session.poisoned
    assert case.seen.projections[0][1]["legal_ir_targets"] is case.targets
    for rows, kwargs in case.seen.evaluations:
        if kwargs.get("legal_ir_bridge_names"):
            assert kwargs["legal_ir_targets"] is case.targets
        else:
            assert "legal_ir_targets" not in kwargs
    assert len(case.seen.lineages) == 4
    assert all(kwargs["target_bundle_identity"] == session.lineage_identity
               for _, kwargs in case.seen.lineages)
    assert case.seen.events.index(("finish", 1)) < case.seen.events.index(("checkpoint", 1))
    assert case.summary()["shared_target_session"]["closed"] is True


@pytest.mark.parametrize("mode", ["default", "bridge_off", "bounded_clones", "non_native_consumer"])
def test_actual_runner_preserves_live_paths_without_target_kwargs(actual_run, mode):
    case = actual_run
    if mode == "default":
        for name in ("autoencoder_target_bundle", "autoencoder_target_bundle_sha256",
                     "autoencoder_target_bundle_bytes", "autoencoder_target_snapshot_id"):
            setattr(case.args, name, None)
    elif mode == "bridge_off":
        case.args.autoencoder_metric_bridge_adapters = "none"
    else:
        case.seen.skip_reason = mode
    assert runner.run_guarded_uscode_modal_daemon(case.args) == 0
    assert all("legal_ir_targets" not in kwargs for _, kwargs in case.seen.evaluations)
    assert all("legal_ir_targets" not in kwargs for _, kwargs in case.seen.projections)
    assert all(kwargs.get("target_bundle_identity") is None for _, kwargs in case.seen.lineages)
    if mode == "default":
        assert case.seen.sessions == []
    else:
        assert case.seen.sessions[0].current_skip == mode
        assert case.seen.sessions[0].closed


@pytest.mark.parametrize("failed_cycle", [1, 2])
def test_after_use_source_failure_prevents_current_and_clean_shutdown_checkpoints(actual_run, failed_cycle):
    case = actual_run
    case.args.max_cycles = failed_cycle
    case.seen.fail_finish = failed_cycle
    with pytest.raises(ValueError, match="source drift after use"):
        runner.run_guarded_uscode_modal_daemon(case.args)
    assert len(case.seen.projections) == failed_cycle
    assert [row["cycle"] for row in case.seen.checkpoint_writes] == list(range(1, failed_cycle))
    assert all(row.get("metadata", {}).get("reason") != "clean_shutdown"
               for row in case.seen.checkpoint_writes)
    assert case.seen.sessions[0].closed and case.seen.sessions[0].poisoned
    summary = case.summary()
    assert summary["final_state_persistence"]["checkpoint_enqueued"] is False
    assert summary["final_state_persistence"]["reason"] == "shared_target_session_failed"
    state_path = case.root / "workspace/todo-queues" / f"{case.args.run_id}.state.json"
    if failed_cycle == 1:
        assert not state_path.exists()
    else:
        loaded = runner.load_autoencoder_checkpoint(state_path, recover=True).state
        assert loaded.legal_ir_view_logits["synthetic_cycle"] == 1.0


def test_shutdown_provenance_failure_keeps_prior_cycle_checkpoint_without_clean_rewrite(actual_run):
    case = actual_run
    case.seen.fail_shutdown = True
    with pytest.raises(ValueError, match="shutdown producer drift"):
        runner.run_guarded_uscode_modal_daemon(case.args)
    assert len(case.seen.checkpoint_writes) == 1
    assert case.seen.checkpoint_writes[0].get("metadata", {}).get("reason") != "clean_shutdown"
    assert case.seen.sessions[0].closed
    assert case.summary()["final_state_persistence"]["checkpoint_enqueued"] is False


def _pending_snapshot_evaluator(case, monkeypatch, *, cleanup_error=None):
    """Make a matching result available only during shutdown, never evaluate it."""
    snapshots = []

    class Evaluator:
        closed = False

        def __init__(self, callback, **kwargs):
            pass

        def before_training_step(self, **kwargs):
            return 0.0

        def summary(self):
            return {"enabled": True, "synthetic_fixture": True, "closed": self.closed}

        def poll_results(self):
            return [SimpleNamespace(snapshot_id="synthetic-pending-result")] if self.closed else []

        def publish(self, snapshot):
            snapshots.append(snapshot)
            return []

        def wait_until_idle(self, **kwargs):
            assert case.seen.sessions[0].closed, "bundle must close before fallible snapshot cleanup"
            if cleanup_error is not None:
                raise cleanup_error
            return True

        def close(self, **kwargs):
            self.closed = True

        def accept_result(self, *args, **kwargs):
            raise AssertionError("target-session failure must suppress pending snapshot acceptance")

        def promote_at_boundary(self, *args, **kwargs):
            raise AssertionError("target-session failure must suppress pending snapshot promotion")

    case.args.snapshot_evaluation_enabled = True
    monkeypatch.setattr(runner, "SnapshotEvaluator", Evaluator)
    monkeypatch.setattr(runner, "_matching_published_snapshot_boundary", lambda *args, **kwargs:
                        SimpleNamespace(sequence=1, versions=SimpleNamespace()))
    return snapshots


@pytest.mark.parametrize("failure", ["begin", "finish", "shutdown", "consumer"])
def test_failure_suppresses_matching_pending_snapshot_promotion(actual_run, monkeypatch, failure):
    case = actual_run
    snapshots = _pending_snapshot_evaluator(case, monkeypatch)
    if failure == "begin":
        case.seen.fail_begin = 1
        message = "source drift before use"
    elif failure == "finish":
        case.args.max_cycles = 2
        case.seen.fail_finish = 2
        message = "source drift after use"
    elif failure == "shutdown":
        case.seen.fail_shutdown = True
        message = "shutdown producer drift"
    else:
        case.seen.projection_error = ValueError("synthetic consumer failure")
        message = "consumer failure"
    with pytest.raises(ValueError, match=message):
        runner.run_guarded_uscode_modal_daemon(case.args)
    assert case.seen.sessions[0].closed
    summary = case.summary()
    assert summary["snapshot_shutdown"]["unmatched_result_ids"] == ["synthetic-pending-result"]
    assert summary["final_state_persistence"]["checkpoint_enqueued"] is False
    assert len(snapshots) == (1 if failure in {"finish", "shutdown"} else 0)
    assert len(case.seen.checkpoint_writes) == len(snapshots)
    if failure == "begin":
        assert case.seen.evaluations == [] and case.seen.projections == []


def test_shutdown_drift_survives_secondary_cleanup_error_and_restores_context(actual_run, monkeypatch):
    case = actual_run
    case.seen.fail_shutdown = True
    secondary = RuntimeError("synthetic secondary snapshot cleanup failure")
    _pending_snapshot_evaluator(case, monkeypatch, cleanup_error=secondary)
    previous_writer = getattr(runner._ASYNC_SUMMARY_WRITER, "writer", None)
    handlers = {number: signal.getsignal(number) for number in (signal.SIGINT, signal.SIGTERM)}
    try:
        with pytest.raises(ValueError, match="shutdown producer drift") as caught:
            runner.run_guarded_uscode_modal_daemon(case.args)
        assert caught.value.__cause__ is secondary
        assert case.seen.sessions[0].closed
        assert getattr(runner._ASYNC_SUMMARY_WRITER, "writer", None) is previous_writer
        assert {number: signal.getsignal(number) for number in handlers} == handlers
        assert len(case.seen.checkpoint_writes) == 1
    finally:
        # The preexisting general cleanup path need not finish after its own
        # injected failure; terminate this test's real writer thread explicitly.
        for writer in case.seen.writers:
            writer.close(wait=True)
