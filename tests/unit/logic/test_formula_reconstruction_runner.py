"""Reconstruction comparison safeguards with small deterministic doubles.

These checks exercise artifact identity and control flow. They neither train a
neural model nor establish successful Lake execution or semantic correctness.
No sealed evaluation fixture or label file is opened by this test module.
"""
import copy
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture
def runner():
    path = Path(__file__).resolve().parents[3] / "scripts/ops/legal_ir/compare_formula_reconstruction_training.py"
    spec = importlib.util.spec_from_file_location("formula_reconstruction_runner_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _metrics(exact=0, facet=0):
    return {"valid_evaluation": True, "operational_complete": True,
            "exact_reconstruction": {"matched": exact},
            "facets": {"actor": {"matched": facet}, "action": {"matched": facet}}}


def _candidate(train=0, tune=0, facet=0, ce=1.0):
    return {"generation": {"training": _metrics(train), "tuning": _metrics(tune, facet)},
            "training": {"report": {"training_after": {"complete": True, "token_cross_entropy": ce}}}}


@pytest.mark.parametrize("partition", ["sealed_evaluation", "evaluation", "holdout", "", None])
def test_non_development_partition_rejected_before_reference_access(runner, monkeypatch, partition):
    def forbidden(*args):
        pytest.fail("a non-development target reference was accessed")
    monkeypatch.setattr(runner.shared, "read_reference", forbidden)
    with pytest.raises(RuntimeError, match="only training/tuning"):
        runner.development_targets({}, partition)


@pytest.mark.parametrize("partition", ["training", "tuning"])
def test_development_target_identity_and_partition_are_checked(runner, tmp_path, partition):
    target = runner.write(tmp_path / ("targets-" + partition + ".json"), [{"id": partition}])
    prepared = {"files": {partition: target}}
    assert runner.development_targets(prepared, partition) == [{"id": partition}]
    wrong = copy.deepcopy(prepared)
    wrong["files"][partition]["path"] = str(tmp_path / "wrong-partition.json")
    with pytest.raises(RuntimeError, match="target partition reference differs"):
        runner.development_targets(wrong, partition)
    Path(target["path"]).write_text("tampered target")
    with pytest.raises(RuntimeError, match="artifact changed"):
        runner.development_targets(prepared, partition)


def _raw_row():
    return {"sample_id": "span-1", "source_text_sha256": "abc", "embedding_provenance": {"model": "local"},
            "target": {"rules": [{"actor": "registrar"}]}, "latent": [0.2, -0.1, 0.0]}


def test_gain_checks_real_inputs_without_changing_provenance_or_targets(runner):
    before = [_raw_row()]
    after = copy.deepcopy(before)
    after[0]["latent"] = [value * 10 for value in before[0]["latent"]]
    original = copy.deepcopy((before, after))
    runner.require_raw_gain(before, after, 10.0)
    assert (before, after) == original


@pytest.mark.parametrize("mutation,reason", [
    ("row_count", "row count"), ("dimension", "dimension"), ("gain", "conditioning gain"),
    ("source", "provenance/targets"), ("target", "provenance/targets"),
    ("embedding", "provenance/targets"), ("nan", "conditioning gain"),
])
def test_actual_gain_rejects_changed_inputs(runner, mutation, reason):
    before, after = [_raw_row()], [_raw_row()]
    if mutation == "row_count":
        after.append(_raw_row())
    elif mutation == "dimension":
        after[0]["latent"].append(0.0)
    elif mutation == "gain":
        after[0]["latent"][0] *= 10
    elif mutation == "source":
        after[0]["source_text_sha256"] = "different"
    elif mutation == "target":
        after[0]["target"]["rules"][0]["actor"] = "different"
    elif mutation == "embedding":
        after[0]["embedding_provenance"]["model"] = "different"
    else:
        after[0]["latent"][0] = float("nan")
    with pytest.raises(RuntimeError, match=reason):
        runner.require_raw_gain(before, after, 1.0)


@pytest.mark.parametrize("gain", [float("inf"), float("-inf"), float("nan"), True, False, 0, -1, "10"])
def test_raw_gain_requires_finite_positive_numeric_scalar_even_without_rows(runner, gain):
    with pytest.raises(RuntimeError, match="finite positive gain required"):
        runner.require_raw_gain([], [], gain)


@pytest.mark.parametrize("before_value,after_value", [
    (float("inf"), float("inf")), (float("-inf"), float("-inf")),
    (float("nan"), float("nan")), (float("inf"), 1.0), (1.0, float("inf")),
    (True, 1.0), (1.0, True), (False, 0.0), (0.0, False), ("0.2", 0.2), (0.2, None),
])
def test_raw_gain_rejects_nonfinite_or_nonnumeric_vector_coordinates(runner, before_value, after_value):
    before, after = [_raw_row()], [_raw_row()]
    before[0]["latent"] = [before_value]
    after[0]["latent"] = [after_value]
    with pytest.raises(RuntimeError, match="raw conditioning gain differs"):
        runner.require_raw_gain(before, after, 1.0)


def test_raw_gain_rejects_finite_inputs_whose_scaled_value_overflows(runner):
    before, after = [_raw_row()], [_raw_row()]
    before[0]["latent"] = [1e308]
    after[0]["latent"] = [1e308]
    with pytest.raises(RuntimeError, match="raw conditioning gain differs"):
        runner.require_raw_gain(before, after, 10.0)


@pytest.mark.parametrize("gain,before_values,after_values", [
    (1, [1.79e308, -1.79e308, 0], [1.79e308, -1.79e308, 0.0]),
    (10.0, [1e307, -1e307, 0.0], [1e308, -1e308, 0]),
])
def test_raw_gain_accepts_finite_boundary_values_and_integer_coordinates(runner, gain, before_values, after_values):
    before, after = [_raw_row()], [_raw_row()]
    before[0]["latent"] = before_values
    after[0]["latent"] = after_values
    runner.require_raw_gain(before, after, gain)


@pytest.mark.parametrize("mutation", ["train_invalid", "tuning_incomplete", "loss_incomplete", "nan", "inf", "-inf"])
def test_selection_rejects_incomplete_or_nonfinite_evidence(runner, mutation):
    result = _candidate()
    if mutation == "train_invalid":
        result["generation"]["training"]["valid_evaluation"] = False
    elif mutation == "tuning_incomplete":
        result["generation"]["tuning"]["operational_complete"] = False
    elif mutation == "loss_incomplete":
        result["training"]["report"]["training_after"]["complete"] = False
    else:
        result["training"]["report"]["training_after"]["token_cross_entropy"] = float(mutation)
    with pytest.raises(RuntimeError, match="requires"):
        runner.training_candidate_key(result)


@pytest.mark.parametrize("profiles", [(), ("baseline_v1",), ("baseline_v1", "raw_gain10_v1", "unexpected")])
def test_selection_requires_every_predeclared_profile(runner, profiles):
    with pytest.raises(RuntimeError, match="all predeclared profiles"):
        runner.select_training_candidate({name: _candidate() for name in profiles})


def test_selection_order_is_free_running_reconstruction_before_scalar_loss(runner):
    ordered = [_candidate(train=1, tune=6, facet=6, ce=0.00001),
               _candidate(train=2, tune=0, facet=0, ce=2.0),
               _candidate(train=2, tune=1, facet=0, ce=3.0),
               _candidate(train=2, tune=1, facet=1, ce=4.0),
               _candidate(train=2, tune=1, facet=1, ce=0.1)]
    assert sorted(ordered, key=runner.training_candidate_key) == ordered
    results = {name: _candidate() for name in runner.PROFILE_IDS}
    assert runner.select_training_candidate(results) == runner.PROFILE_IDS[0]
    results[runner.PROFILE_IDS[-1]]["generation"]["tuning"]["operational_complete"] = False
    with pytest.raises(RuntimeError, match="complete free-running"):
        runner.select_training_candidate(results)


@pytest.fixture
def bounded_run(runner, tmp_path, monkeypatch):
    """Real JSON references, with no embedding, teacher, or neural model load."""
    torch = pytest.importorskip("torch")
    original_threads = torch.get_num_threads()
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import (
        autoencoder_runtime_registry as runtimes, autoencoder_decoded_schema as schemas,
        formula_generation_metrics as metrics, modal_joint_formula as joint, modal_latent_formula as learning,
    )
    directory = tmp_path / "comparison"
    behavior = {"fault": None, "schema_complete": True}
    events, opened_targets, runtime_instances = [], [], []
    train = [{"id": "train-" + str(index)} for index in range(24)]
    tune = [{"id": "tune-" + str(index)} for index in range(6)]
    samples = {row["id"]: SimpleNamespace(sample_id=row["id"]) for row in train + tune}
    def curriculum_rows(partition):
        assert partition in ("training", "tuning")
        return train if partition == "training" else tune
    prepared = {"files": {}}
    def prepare(path, **kwargs):
        assert (directory / "plan.json").is_file(), "plan must precede preparation"
        assert kwargs["optimizer_steps"] == runner.STEPS
        path.mkdir()
        for partition, rows in (("training", train), ("tuning", tune)):
            prepared["files"][partition] = runner.write(path / ("targets-" + partition + ".json"), rows)
        # A sentinel, not a real evaluation-label artifact.
        prepared["files"]["sealed_evaluation"] = {"forbidden": True}
        events.append("prepared")
    monkeypatch.setattr(runner.shared, "prepare", prepare)
    monkeypatch.setattr(runner.shared, "prepared_inputs", lambda path: (
        {}, SimpleNamespace(rows=curriculum_rows), prepared, samples))
    monkeypatch.setattr(runner, "sources", lambda: {"producer": "fixed"})
    original_read = runner.shared.read_reference
    def reading(ref):
        assert "forbidden" not in ref, "evaluation labels were accessed"
        opened_targets.append(Path(ref["path"]).name)
        return original_read(ref)
    monkeypatch.setattr(runner.shared, "read_reference", reading)
    monkeypatch.setattr(joint, "_core_binding", lambda model: copy.deepcopy(model.binding))
    def rows(model, batch, labels):
        assert [sample.sample_id for sample in batch] == [row["id"] for row in labels]
        return [{"sample_id": sample.sample_id, "target": label, "source_text_sha256": sample.sample_id,
                 "latent": [0.1 * model.gain, -0.2 * model.gain]} for sample, label in zip(batch, labels)]
    monkeypatch.setattr(joint, "_rows", rows)
    monkeypatch.setattr(learning, "build_checkpoint", lambda binding, rows, tuning, **options: {
        "binding": copy.deepcopy(binding), "config": options, "codec": {"vocabulary": "shared"},
        "model_state": {}, "progress": {"optimizer_steps": 0}, "training_ids": [row["sample_id"] for row in rows]})
    monkeypatch.setattr(runner, "condition_diagnostics", lambda checkpoint, rows: {"rows": len(rows)})

    class Runtime:
        def __init__(self, options, checkpoint=None):
            self.checkpoint = copy.deepcopy(checkpoint)
            self.reloaded = checkpoint is not None
            self.core = {}
            self.model = SimpleNamespace(binding=options, gain=10 if options["initial_embedding_scale"] == .2 else 1,
                state=SimpleNamespace(to_dict=lambda: self.core), attach_formula_checkpoint=self.attach,
                save_formula_checkpoint=self.save)
        def attach(self, checkpoint):
            self.checkpoint = copy.deepcopy(checkpoint)
        def save(self, path):
            assert self.checkpoint["progress"]["optimizer_steps"] == runner.STEPS
            events.append("save")
            return runner.write(path, self.checkpoint)
        def infer(self, batch):
            events.append("infer")
            assert all(sample.sample_id in samples for sample in batch)
            result = {"checkpoint_sha256": learning.checkpoint_digest(self.checkpoint),
                      "rows": [{"id": sample.sample_id} for sample in batch]}
            if behavior["fault"] == "reload" and self.reloaded:
                result["changed"] = True
            return result
        def train(self, batch, **kwargs):
            events.append("train")
            assert [sample.sample_id for sample in batch] == self.checkpoint["training_ids"]
            assert [row["id"] for row in kwargs["formula_targets"]] == self.checkpoint["training_ids"]
            assert [sample.sample_id for sample in kwargs["validation_samples"]] == [row["id"] for row in tune]
            steps = kwargs["max_optimizer_steps"]
            if behavior["fault"] == "budget" and steps == runner.STEPS:
                steps -= 1
            self.checkpoint["progress"]["optimizer_steps"] += steps
            if behavior["fault"] == "resume" and steps == 1 and self.reloaded:
                self.checkpoint["resume_changed"] = True
            if behavior["fault"] == "core":
                self.core["unexpected"] = 1
            return {"checkpoint": copy.deepcopy(self.checkpoint), "report": {
                "optimizer_steps": steps, "training_after": {"complete": True, "token_cross_entropy": .1},
                "tuning": {"complete": True}, "parameter_evidence": {
                    group: {"parameter_update_l2": 0.0 if behavior["fault"] == "no_update" else 1.0}
                    for group in ("projection", "decoder")},
                "checkpoint_sha256": learning.checkpoint_digest(self.checkpoint)}}
    def opening(*args, **kwargs):
        assert args == ("legal_ir", "current_v2")
        checkpoint = None
        if "formula_checkpoint" in kwargs:
            path = Path(kwargs.pop("formula_checkpoint"))
            assert runner.sha(path) == kwargs.pop("formula_sha256")
            checkpoint = json.loads(path.read_text())
        runtime = Runtime(kwargs, checkpoint)
        runtime_instances.append(runtime)
        return runtime
    monkeypatch.setattr(runtimes, "open_runtime", opening)
    def comparing(outputs, labels, *, partition):
        assert partition in ("training", "tuning")
        assert outputs["rows"] == labels
        return _metrics(exact=len(labels), facet=len(labels))
    monkeypatch.setattr(metrics, "compare_free_running_formulas", comparing)
    def schema(runtime, batch, **kwargs):
        events.append("schema")
        frozen = json.loads((directory / "frozen.json").read_text())
        assert set(frozen["candidate_reports"]) == set(runner.PROFILE_IDS)
        assert all((directory / (name + "-result.json")).is_file() for name in runner.PROFILE_IDS)
        assert runtime.checkpoint["progress"]["optimizer_steps"] == runner.STEPS
        assert [sample.sample_id for sample in batch] == [row["id"] for row in train + tune]
        return {"checkpoint_sha256": learning.checkpoint_digest(runtime.checkpoint),
                "schema_checks_complete": behavior["schema_complete"], "lake_build_count": 30,
                "schema_pass_count": 30 if behavior["schema_complete"] else 29}
    monkeypatch.setattr(schemas, "validate_decoded_outputs", schema)
    yield SimpleNamespace(directory=directory, behavior=behavior, events=events,
                          opened_targets=opened_targets, runtimes=runtime_instances)
    torch.set_num_threads(original_threads)


def test_complete_run_uses_only_development_labels_and_original_scored_heads(runner, bounded_run):
    case = bounded_run
    runner.run(case.directory)
    assert case.opened_targets == ["targets-training.json", "targets-tuning.json"]
    assert case.events.count("save") == len(runner.PROFILE_IDS)
    assert case.events[-1] == "schema"
    report = json.loads((case.directory / "report.json").read_text())
    assert report["operational_ok"] is True
    assert report["selected_training_candidate"] == runner.PROFILE_IDS[0]
    assert report["evaluation_targets_used"] is False
    assert report["held_out_generalization_evaluated"] is False
    assert report["selection_is_not_promotion"] is True
    assert report["training_quality_improved"] is False
    assert all(report[key] is False for key in runner.FALSE)
    for result in report["results"].values():
        assert result["reload_prediction_exact"] and result["resume_checkpoint_exact"]
        assert result["extra_resume_step_excluded_from_scored_head"]
        assert result["training"]["report"]["optimizer_steps"] == runner.STEPS
        head = json.loads(Path(result["head"]["path"]).read_text())
        assert head["progress"]["optimizer_steps"] == runner.STEPS


@pytest.mark.parametrize("fault,reason", [
    ("budget", "fixed update budget"), ("core", "sparse core mutated"),
    ("no_update", "parameter group did not train"), ("reload", "reload changed predictions"),
    ("resume", "resumed and uninterrupted updates differ"),
])
def test_training_or_replay_failure_never_reaches_selection_or_schema(runner, bounded_run, fault, reason):
    bounded_run.behavior["fault"] = fault
    with pytest.raises(RuntimeError, match=reason):
        runner.run(bounded_run.directory)
    assert "schema" not in bounded_run.events
    assert not (bounded_run.directory / "frozen.json").exists()
    assert not (bounded_run.directory / "report.json").exists()


def test_failed_schema_execution_preserves_diagnostic_report_without_qualification(runner, bounded_run):
    bounded_run.behavior["schema_complete"] = False
    with pytest.raises(RuntimeError, match="schema execution incomplete"):
        runner.run(bounded_run.directory)
    report = json.loads((bounded_run.directory / "report.json").read_text())
    assert report["operational_ok"] is False
    assert report["selection_is_not_promotion"] is True
    assert all(report[key] is False for key in runner.FALSE)
