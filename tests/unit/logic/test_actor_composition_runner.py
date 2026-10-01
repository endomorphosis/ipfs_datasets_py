"""Phase boundaries use real artifact checks with cheap model/backend doubles.

These tests establish ordering and fail-closed reporting, not neural learning,
embedding fidelity, successful Lake execution, or legal qualification.
"""
import copy
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture
def runner():
    path = Path(__file__).resolve().parents[3] / "scripts/ops/legal_ir/evaluate_actor_composition_curriculum.py"
    spec = importlib.util.spec_from_file_location("actor_composition_runner_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(autouse=True)
def restore_torch_threads():
    torch = pytest.importorskip("torch")
    previous = torch.get_num_threads()
    yield
    torch.set_num_threads(previous)


def _modules():
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import (
        autoencoder_runtime_registry, autoencoder_decoded_schema,
        formula_generation_metrics, modal_joint_formula, modal_latent_formula,
    )
    return (autoencoder_runtime_registry, autoencoder_decoded_schema,
            formula_generation_metrics, modal_joint_formula, modal_latent_formula)


def _rewrite(runner, path, value):
    path.write_bytes(runner.raw(value))
    return runner.reference(path)


def _frozen_run(runner, directory):
    plan = {"formula_options": runner.OPTIONS, "optimizer_steps_per_arm": 2,
            "source_hashes": {}}
    runner.write(directory / "plan.json", plan)
    targets = runner.write(directory / "targets-sealed_evaluation.json", [{"id": "sealed"}])
    prepared = {"files": {"sealed_evaluation": targets}}
    runner.write(directory / "prepared.json", prepared)
    heads, reports = {}, {}
    for arm in runner.ARMS:
        head = {"config": dict(runner.OPTIONS), "progress": {"optimizer_steps": 2},
                "test_arm_marker": arm}
        heads[arm] = runner.write(directory / (arm + "-head.json"), head)
        reports[arm] = runner.write(directory / (arm + "-training.json"), {
            "head": heads[arm], "initial_identity": {"model_state": "same initial state"},
            "report": {"checkpoint_sha256": heads[arm]["sha256"], "optimizer_steps": 2}})
    frozen = {"plan_sha256": runner.sha(directory / "plan.json"),
              "prepared_sha256": runner.sha(directory / "prepared.json"),
              "heads": heads, "training_reports": reports, "evaluation_targets_opened": False}
    runner.write(directory / "frozen.json", frozen)
    curriculum = SimpleNamespace(rows=lambda split: [{"id": "sealed"}])
    return plan, curriculum, prepared, {"sealed": object()}, frozen


@pytest.mark.parametrize("artifact", ["heads", "training_reports"])
def test_corrupt_second_artifact_aborts_before_models_or_sealed_labels(runner, tmp_path, monkeypatch, artifact):
    plan, curriculum, prepared, samples, frozen = _frozen_run(runner, tmp_path)
    Path(frozen[artifact][runner.ARMS[1]]["path"]).write_text("changed after freezing")
    monkeypatch.setattr(runner, "prepared_inputs", lambda directory: (plan, curriculum, prepared, samples))
    opened = []
    original = runner.read_reference
    def reading(reference):
        opened.append(Path(reference["path"]).name)
        assert reference != prepared["files"]["sealed_evaluation"], "sealed labels opened before both heads were verified"
        return original(reference)
    monkeypatch.setattr(runner, "read_reference", reading)
    runtimes = _modules()[0]
    def forbidden(*args, **kwargs):
        pytest.fail("runtime opened before both frozen artifacts were verified")
    monkeypatch.setattr(runtimes, "open_runtime", forbidden)
    with pytest.raises(RuntimeError, match="artifact changed"):
        runner.evaluate(tmp_path)
    assert Path(frozen[artifact][runner.ARMS[1]]["path"]).name in opened
    assert not (tmp_path / "report.json").exists()


def test_second_head_load_failure_precedes_sealed_label_access(runner, tmp_path, monkeypatch):
    plan, curriculum, prepared, samples, frozen = _frozen_run(runner, tmp_path)
    monkeypatch.setattr(runner, "prepared_inputs", lambda directory: (plan, curriculum, prepared, samples))
    original = runner.read_reference
    def reading(reference):
        assert reference != prepared["files"]["sealed_evaluation"], "sealed labels opened before second model loaded"
        return original(reference)
    monkeypatch.setattr(runner, "read_reference", reading)
    loaded = []
    def opening(*args, **kwargs):
        loaded.append(kwargs["formula_checkpoint"])
        if len(loaded) == 2:
            raise ValueError("second runtime rejected checkpoint")
        return object()
    monkeypatch.setattr(_modules()[0], "open_runtime", opening)
    with pytest.raises(ValueError, match="second runtime"):
        runner.evaluate(tmp_path)
    assert loaded == [frozen["heads"][arm]["path"] for arm in runner.ARMS]


@pytest.mark.parametrize("mutation,reason", [
    ("swapped_report", "fit receipt differs"),
    ("budget", "fixed optimizer budget"),
    ("configuration", "frozen optimizer settings"),
    ("initial_identity", "initialization differs"),
])
def test_frozen_semantic_binding_rejects_consistent_file_hashes(runner, tmp_path, mutation, reason):
    plan, _, _, _, frozen = _frozen_run(runner, tmp_path)
    arm = runner.ARMS[1]
    fit = runner.read_reference(frozen["training_reports"][arm])
    if mutation == "swapped_report":
        frozen["training_reports"][arm] = frozen["training_reports"][runner.ARMS[0]]
    else:
        if mutation == "initial_identity":
            fit["initial_identity"]["model_state"] = "different initialization"
        else:
            head = runner.read_reference(frozen["heads"][arm])
            if mutation == "budget":
                head["progress"]["optimizer_steps"] += 1
            else:
                head["config"]["learning_rate"] /= 2
            frozen["heads"][arm] = _rewrite(runner, Path(frozen["heads"][arm]["path"]), head)
            fit["head"] = frozen["heads"][arm]
            fit["report"]["checkpoint_sha256"] = fit["head"]["sha256"]
        frozen["training_reports"][arm] = _rewrite(runner, Path(frozen["training_reports"][arm]["path"]), fit)
    _rewrite(runner, tmp_path / "frozen.json", frozen)
    with pytest.raises(RuntimeError, match=reason):
        runner.verify_frozen_artifacts(tmp_path, plan)


@pytest.mark.parametrize("drift", ["embedding_receipt", "rebuilt_sample"])
@pytest.mark.parametrize("phase", ["train", "evaluate"])
def test_prepared_input_drift_aborts_before_training_or_inference(runner, tmp_path, monkeypatch, drift, phase):
    runner.write(tmp_path / "plan.json", {"plan": "fixed"})
    production = runner.write(tmp_path / "embedding-production.json", {"receipt": "original"})
    stored = runner.write(tmp_path / "student-samples.json", [{"vector": [0.25]}])
    runner.write(tmp_path / "prepared.json", {"plan_sha256": runner.sha(tmp_path / "plan.json"),
                 "files": {"embedding_production": production, "samples": stored}})
    monkeypatch.setattr(runner, "load_plan", lambda directory: {})
    monkeypatch.setattr(runner, "panel", lambda: object())
    built = []
    def native(*args):
        built.append(True)
        return {"sample": SimpleNamespace(to_dict=lambda: {"vector": [0.5]})}
    monkeypatch.setattr(runner, "native_samples", native)
    if drift == "embedding_receipt":
        Path(production["path"]).write_text("swapped receipt")
    def forbidden(*args, **kwargs):
        pytest.fail("model opened before prepared input identity was verified")
    monkeypatch.setattr(_modules()[0], "open_runtime", forbidden)
    with pytest.raises(RuntimeError, match="artifact changed|rebuilt student inputs differ"):
        getattr(runner, phase)(tmp_path)
    assert bool(built) == (drift == "rebuilt_sample")


@pytest.mark.parametrize("complete,builds,passes", [(False, 1, 1), (True, 0, 0), (True, 1, 0)])
def test_incomplete_lake_execution_retains_failed_operational_report(runner, tmp_path, monkeypatch, complete, builds, passes):
    plan, curriculum, prepared, samples, _ = _frozen_run(runner, tmp_path)
    monkeypatch.setattr(runner, "prepared_inputs", lambda directory: (plan, curriculum, prepared, samples))
    monkeypatch.setattr(runner, "sources", lambda: {})
    runtimes, schemas, metrics, _, _ = _modules()
    def opening(*args, **kwargs):
        digest = kwargs["formula_sha256"]
        def forbidden(*args, **kwargs):
            pytest.fail("evaluation attempted training")
        return SimpleNamespace(infer=lambda samples: {"checkpoint_sha256": digest},
                               train=forbidden, digest=digest)
    monkeypatch.setattr(runtimes, "open_runtime", opening)
    monkeypatch.setattr(metrics, "compare_free_running_formulas", lambda *args, **kwargs: {
        "valid_evaluation": True, "operational_complete": True, "exact_reconstruction": {"fraction": 1.0}})
    monkeypatch.setattr(schemas, "validate_decoded_outputs", lambda model, *args, **kwargs: {
        "checkpoint_sha256": model.digest, "schema_checks_complete": complete,
        "lake_build_count": builds, "schema_pass_count": passes})
    with pytest.raises(RuntimeError, match="schema checks incomplete"):
        runner.evaluate(tmp_path)
    report = json.loads((tmp_path / "report.json").read_text())
    assert report["experiment_completed"] is True
    assert report["operational_ok"] is False
    assert all(row["generated_schema_builds_ok"] is False for row in report["results"].values())
    assert all(report[key] is False for key in runner.FALSE)


def test_train_never_reads_sealed_targets_or_compiler_observations(runner, tmp_path, monkeypatch):
    """Run the whole fitting phase with deterministic cheap optimizer doubles."""
    runtimes, _, metrics, joint, learning = _modules()
    plan = {"formula_options": dict(runner.OPTIONS), "optimizer_steps_per_arm": 2,
            "training_max_seconds_per_arm": 10, "source_hashes": {}}
    runner.write(tmp_path / "plan.json", plan)
    runner.write(tmp_path / "prepared.json", {})
    train_rows = [{"id": "train-a"}, {"id": "train-b"}]
    tune_rows = [{"id": "tune"}]
    files = {"training": runner.write(tmp_path / "targets-training.json", train_rows),
             "tuning": runner.write(tmp_path / "targets-tuning.json", tune_rows)}
    for name in ("sealed_evaluation", "compiler_observations"):
        files[name] = runner.write(tmp_path / (name + ".json"), {"must_not_read": True})
    prepared = {"files": files}
    def rows(split, training_subset="balanced"):
        return tune_rows if split == "tuning" else train_rows[:1 if training_subset == "confounded_diagonal" else 2]
    curriculum = SimpleNamespace(rows=rows)
    samples = {row["id"]: SimpleNamespace(sample_id=row["id"]) for row in train_rows + tune_rows}
    monkeypatch.setattr(runner, "prepared_inputs", lambda directory: (plan, curriculum, prepared, samples))
    monkeypatch.setattr(runner, "sources", lambda: {})
    read_paths, original = [], runner.read_reference
    def reading(reference):
        read_paths.append(reference["path"])
        assert reference not in [files["sealed_evaluation"], files["compiler_observations"]]
        return original(reference)
    monkeypatch.setattr(runner, "read_reference", reading)
    monkeypatch.setattr(joint, "_core_binding", lambda model: {"core": "fixed"})
    monkeypatch.setattr(joint, "_rows", lambda model, samples, targets: [sample.sample_id for sample in samples])
    monkeypatch.setattr(learning, "build_checkpoint", lambda binding, training, tuning, **options: {
        "binding": binding, "config": options, "codec": {"vocabulary": "same"}, "model_state": {},
        "progress": {"optimizer_steps": 0}, "training_ids": training})
    class Runtime:
        def __init__(self, checkpoint=None):
            self.checkpoint = copy.deepcopy(checkpoint)
            self.model = SimpleNamespace(state=SimpleNamespace(to_dict=lambda: {}),
                attach_formula_checkpoint=self.attach,
                save_formula_checkpoint=lambda path: runner.write(path, self.checkpoint))
        def attach(self, checkpoint):
            self.checkpoint = copy.deepcopy(checkpoint)
        def infer(self, samples):
            assert all(sample.sample_id != "sealed" for sample in samples)
            return {"checkpoint_sha256": learning.checkpoint_digest(self.checkpoint),
                    "rows": [{"id": sample.sample_id} for sample in samples]}
        def train(self, samples, **kwargs):
            assert [sample.sample_id for sample in samples] == self.checkpoint["training_ids"]
            assert [row["id"] for row in kwargs["formula_targets"]] == self.checkpoint["training_ids"]
            step = kwargs["max_optimizer_steps"]
            self.checkpoint["progress"]["optimizer_steps"] += step
            return {"checkpoint": copy.deepcopy(self.checkpoint), "report": {
                "optimizer_steps": step, "training_after": {"complete": True}, "tuning": {"complete": True},
                "parameter_evidence": {group: {"parameter_update_l2": 1.0} for group in ("projection", "decoder")},
                "checkpoint_sha256": learning.checkpoint_digest(self.checkpoint), "elapsed_seconds": 0.0}}
    def opening(*args, **kwargs):
        checkpoint = json.loads(Path(kwargs["formula_checkpoint"]).read_text()) if "formula_checkpoint" in kwargs else None
        return Runtime(checkpoint)
    monkeypatch.setattr(runtimes, "open_runtime", opening)
    monkeypatch.setattr(metrics, "compare_free_running_formulas", lambda *args, **kwargs: {"valid_evaluation": True})
    runner.train(tmp_path)
    assert read_paths == [files["training"]["path"], files["tuning"]["path"]]
    frozen = json.loads((tmp_path / "frozen.json").read_text())
    assert frozen["evaluation_targets_opened"] is False
    assert set(frozen["heads"]) == set(runner.ARMS)
    runner.verify_frozen_artifacts(tmp_path, plan)
