"""Freeze-barrier tests with real artifact checks and cheap model doubles.

No actual sealed embeddings, compiler labels, neural predictions, or Lake
builds are produced. Synthetic targets below carry source IDs only.
"""
import copy
import importlib.util
import json
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace

import pytest


@pytest.fixture
def runner():
    path = Path(__file__).resolve().parents[3] / "scripts/ops/legal_ir/evaluate_training_holdouts.py"
    spec = importlib.util.spec_from_file_location("evaluate_training_holdouts_test", path)
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
        autoencoder_runtime_registry, autoencoder_decoded_schema, modal_joint_formula,
        modal_latent_formula, formula_generation_metrics,
    )
    return autoencoder_runtime_registry, autoencoder_decoded_schema, modal_joint_formula, modal_latent_formula, formula_generation_metrics


def _fake_fast(monkeypatch):
    fast = ModuleType("ipfs_datasets_py.optimizers.logic_theorem_optimizer.modal_latent_formula_prepared")
    monkeypatch.setitem(sys.modules, fast.__name__, fast)
    package = sys.modules["ipfs_datasets_py.optimizers.logic_theorem_optimizer"]
    monkeypatch.setattr(package, "modal_latent_formula_prepared", fast, raising=False)
    return fast


def _rewrite(runner, path, value):
    """Explicit test tampering; production writes remain exclusive."""
    path.write_bytes(runner.raw(value))
    return runner.shared.reference(path)


def _report(runner, digest):
    return {"optimizer_steps": runner.STEPS, "stopped_reason": "optimizer_step_budget",
            "training_after": {"complete": True, "token_cross_entropy": .1, "reconstruction_mse": .01},
            "tuning": {"complete": True, "token_cross_entropy": .2, "reconstruction_mse": .02},
            "parameter_evidence": {name: {"parameter_update_l2": 1.0} for name in ("projection", "decoder")},
            "checkpoint_sha256": digest}


def _frozen(runner, directory, monkeypatch):
    monkeypatch.setattr(runner, "sources", lambda: {"producer": "fixed"})
    plan = {"source_hashes": runner.sources(), "panel_manifest_sha256": runner.panel().manifest_sha256,
            "settings": runner.settings()}
    plan_ref = runner.write(directory / "plan.json", plan)
    (directory / "development").mkdir()
    development_ref = runner.write(directory / "development/prepared.json", {"synthetic": True})
    preparation_ref = runner.write(directory / "prepared.json", {"plan": plan_ref, "development": development_ref})
    monkeypatch.setattr(runner, "inputs", lambda folder, split: ({}, {}))
    fits = {}
    for seed in runner.SEEDS:
        for arm in runner.ARMS:
            head = {"config": dict(plan["settings"]["profile"]["formula_options"], seed=seed, batch_size=8),
                    "progress": {"optimizer_steps": runner.STEPS}}
            head_ref = runner.write(directory / f"{seed}-{arm}-head.json", head)
            fits[f"{seed}/{arm}"] = runner.write(directory / f"{seed}-{arm}-fit.json", {
                "seed": seed, "arm": arm, "head": head_ref, "training_report": _report(runner, head_ref["sha256"]),
                "initial_identity": {"core": "same", "codec": "same", "model_state": str(seed)}})
    frozen = {"plan": plan_ref, "preparation": preparation_ref, "fits": fits, "evaluation_targets_opened": False}
    runner.write(directory / "frozen.json", frozen)
    return plan, frozen


def test_source_partitions_include_72_development_and_only_eight_sealed_sources(runner):
    panel = runner.panel()
    dev = runner.fixture_rows(panel, "development")
    sealed = runner.fixture_rows(panel, "sealed_evaluation")
    assert len(dev) == 72 and len(sealed) == 8
    assert {row["id"] for row in dev}.isdisjoint(row["id"] for row in sealed)
    assert {row["text"] for row in dev}.isdisjoint(row["text"] for row in sealed)
    assert all(row["split"] != "sealed_evaluation" for row in dev)
    assert all("parent_id" not in row for row in sealed)
    assert len(panel.training_rows()) == 32 and len(panel.training_rows(include_must=True)) == 64
    settings = runner.settings()
    assert settings["seeds"] == [1729, 1730, 1731]
    assert settings["batch_size"] == 8 and settings["row_presentations_per_arm"] == 8000
    assert settings["profile"]["formula_options"]["batch_size"] == 6  # Override must be explicit.
    assert panel.receipt["earlier_exposed_source_count"] == 75
    with pytest.raises(RuntimeError, match="partition"):
        runner.fixture_rows(panel, "unknown")


@pytest.mark.parametrize("damage,reason", [
    ("source", "producer source"), ("settings", "settings changed"),
    ("missing_fit", "all six fits"), ("missing_head", None), ("head_bytes", "artifact changed"),
    ("fit_bytes", "artifact changed"), ("head_configuration", "head configuration"),
    ("partial_budget", "fixed update budget"), ("head_step", "scored step"),
    ("paired_identity", "paired identity"), ("head_report", "head/report mismatch"),
])
def test_invalid_frozen_candidate_aborts_before_sealed_preparation(runner, tmp_path, monkeypatch, damage, reason):
    plan, frozen = _frozen(runner, tmp_path, monkeypatch)
    last = f"{runner.SEEDS[-1]}/{runner.ARMS[-1]}"
    fit_ref = frozen["fits"][last]
    fit = runner.shared.read_reference(fit_ref)
    if damage == "source":
        monkeypatch.setattr(runner, "sources", lambda: {"producer": "changed"})
    elif damage == "settings":
        plan["settings"]["batch_size"] = 7
        _rewrite(runner, tmp_path / "plan.json", plan)
    elif damage == "missing_fit":
        del frozen["fits"][last]
    elif damage == "missing_head":
        Path(fit["head"]["path"]).unlink()
    elif damage in ("head_bytes", "fit_bytes"):
        Path((fit["head"] if damage == "head_bytes" else fit_ref)["path"]).write_text("changed")
    else:
        if damage in ("head_configuration", "head_step"):
            head = runner.shared.read_reference(fit["head"])
            if damage == "head_configuration":
                head["config"]["batch_size"] = 6
            else:
                head["progress"]["optimizer_steps"] += 1
            fit["head"] = _rewrite(runner, Path(fit["head"]["path"]), head)
            fit["training_report"]["checkpoint_sha256"] = fit["head"]["sha256"]
        elif damage == "partial_budget":
            fit["training_report"]["optimizer_steps"] -= 1
        elif damage == "paired_identity":
            fit["initial_identity"]["codec"] = "different"
        else:
            fit["training_report"]["checkpoint_sha256"] = "0" * 64
        frozen["fits"][last] = _rewrite(runner, Path(fit_ref["path"]), fit)
    _rewrite(runner, tmp_path / "frozen.json", frozen)
    monkeypatch.setattr(runner, "prepare_partition", lambda *args: pytest.fail("sealed preparation occurred before all candidates were verified"))
    monkeypatch.setattr(_modules()[0], "open_runtime", lambda *args, **kwargs: pytest.fail("model opened before frozen artifact checks completed"))
    with pytest.raises((RuntimeError, FileNotFoundError), match=reason):
        runner.evaluate(tmp_path)
    assert not (tmp_path / "sealed_evaluation").exists()


def test_sixth_runtime_attachment_failure_does_not_open_sealed_sources(runner, tmp_path, monkeypatch):
    _, frozen = _frozen(runner, tmp_path, monkeypatch)
    expected = {runner.shared.read_reference(ref)["head"]["path"] for ref in frozen["fits"].values()}
    opened = []
    def opening(*args, **kwargs):
        opened.append(kwargs["formula_checkpoint"])
        if len(opened) == 6:
            raise ValueError("sixth checkpoint failed attachment")
        return object()
    monkeypatch.setattr(_modules()[0], "open_runtime", opening)
    monkeypatch.setattr(runner, "prepare_partition", lambda *args: pytest.fail("sealed labels opened before final runtime attached"))
    with pytest.raises(ValueError, match="sixth checkpoint"):
        runner.evaluate(tmp_path)
    assert len(opened) == 6 and set(opened) == expected


@pytest.mark.parametrize("schema_complete", [True, False])
def test_successful_barrier_precedes_sealed_preparation_and_fixed_schema_checks(runner, tmp_path, monkeypatch, schema_complete):
    _, frozen = _frozen(runner, tmp_path, monkeypatch)
    runtimes, schemas, joint, learning, metrics = _modules()
    expected_heads = {runner.shared.read_reference(ref)["head"]["path"] for ref in frozen["fits"].values()}
    rows = runner.panel().rows("sealed_evaluation")
    samples = {row["id"]: SimpleNamespace(sample_id=row["id"]) for row in rows}
    labels = {row["id"]: {"id": row["id"]} for row in rows}
    opened, predictions, schema_heads = [], [], []
    def opening(*args, **kwargs):
        path, digest = kwargs["formula_checkpoint"], kwargs["formula_sha256"]
        assert runner.sha(path) == digest
        opened.append(path)
        def infer(values):
            assert (tmp_path / "sealed_evaluation/prepared.json").exists()
            predictions.append(path)
            return {"checkpoint_sha256": digest, "rows": [{"id": value.sample_id} for value in values]}
        return SimpleNamespace(infer=infer, model=object(), digest=digest, path=path)
    monkeypatch.setattr(runtimes, "open_runtime", opening)
    def prepare(directory, split):
        assert split == "sealed_evaluation"
        assert len(opened) == 6 and set(opened) == expected_heads
        assert not predictions, "predictions preceded the all-head freeze barrier"
        (directory / split).mkdir()
        runner.write(directory / split / "prepared.json", {"synthetic_targets_only": True})
        return samples, labels
    monkeypatch.setattr(runner, "prepare_partition", prepare)
    monkeypatch.setattr(metrics, "compare_free_running_formulas", lambda output, target, **kwargs: {
        "valid_evaluation": True, "operational_complete": True, "exact_reconstruction": {"matched": 0, "total": 8}})
    monkeypatch.setattr(learning, "_restore", lambda head: (None, object(), None))
    monkeypatch.setattr(learning, "_metrics", lambda *args: {"complete": True})
    monkeypatch.setattr(joint, "_rows", lambda model, batch, labels: labels)
    # Synthetic heads need a target codec field only for the metric call.
    for ref in list(frozen["fits"].values()):
        fit = runner.shared.read_reference(ref)
        head = runner.shared.read_reference(fit["head"])
        head["codec"] = {}
        fit["head"] = _rewrite(runner, Path(fit["head"]["path"]), head)
        fit["training_report"]["checkpoint_sha256"] = fit["head"]["sha256"]
        frozen["fits"][f"{fit['seed']}/{fit['arm']}"] = _rewrite(runner, Path(ref["path"]), fit)
    _rewrite(runner, tmp_path / "frozen.json", frozen)
    def schema(runtime, batch, **kwargs):
        schema_heads.append(Path(runtime.path).name)
        assert len(batch) == 8
        return {"checkpoint_sha256": runtime.digest, "schema_checks_complete": schema_complete,
                "lake_build_count": 8, "schema_pass_count": 8 if schema_complete else 7}
    monkeypatch.setattr(schemas, "validate_decoded_outputs", schema)
    if schema_complete:
        runner.evaluate(tmp_path)
    else:
        with pytest.raises(RuntimeError, match="schema checks incomplete"):
            runner.evaluate(tmp_path)
    report = json.loads((tmp_path / "report.json").read_text())
    assert report["operational_ok"] is schema_complete
    assert report["holdout_opened_after_all_heads_frozen"] is True
    assert len(predictions) == 6
    assert schema_heads == [f"1729-{arm}-head.json" for arm in runner.ARMS]
    assert all(report[key] is False for key in runner.FALSE)


@pytest.mark.parametrize("resume_steps", [1, 0])
def test_fit_uses_only_development_sources_and_explicit_seed_batch_overrides(runner, tmp_path, monkeypatch, resume_steps):
    runtimes, _, joint, learning, metrics = _modules()
    fast = _fake_fast(monkeypatch)
    curriculum = runner.panel()
    rows = curriculum.development_rows(include_must=True)
    samples = {row["id"]: SimpleNamespace(sample_id=row["id"]) for row in rows}
    targets = {row["id"]: {"id": row["id"]} for row in rows}
    plan = {"settings": runner.settings()}
    runner.write(tmp_path / "plan.json", plan)
    runner.write(tmp_path / "prepared.json", {})
    monkeypatch.setattr(runner, "development_inputs", lambda directory: (plan, {}, samples, targets))
    monkeypatch.setattr(runner, "guard", lambda directory: plan)
    monkeypatch.setattr(runner, "prepare_partition", lambda *args: pytest.fail("fitting requested sealed preparation"))
    monkeypatch.setattr(joint, "_core_binding", lambda model: {"core": "fixed"})
    monkeypatch.setattr(joint, "_rows", lambda model, values, labels: [value.sample_id for value in values])
    built, fits, predictions = [], [], []
    def build(binding, train, tuning, **options):
        built.append((options["seed"], options["batch_size"], len(train), len(tuning)))
        return {"binding": binding, "config": options, "codec": {"same": True}, "model_state": {"seed": options["seed"]},
                "progress": {"optimizer_steps": 0}, "training_ids": train}
    monkeypatch.setattr(learning, "build_checkpoint", build)
    def training(checkpoint, train, tuning, **options):
        assert train == checkpoint["training_ids"]
        assert all(identifier in samples for identifier in train + tuning)
        count = options["max_optimizer_steps"]
        if count == 1:
            count = resume_steps
        fits.append((checkpoint["config"]["seed"], len(train), count))
        result = copy.deepcopy(checkpoint)
        result["progress"]["optimizer_steps"] += count
        report = _report(runner, learning.checkpoint_digest(result))
        report["optimizer_steps"] = count
        return {"checkpoint": result, "report": report}
    fast.train = training
    monkeypatch.setattr(learning, "load_checkpoint", lambda path, **kwargs: json.loads(Path(path).read_text()))
    class Runtime:
        def __init__(self, checkpoint=None):
            self.checkpoint = copy.deepcopy(checkpoint)
            self.model = SimpleNamespace(state=SimpleNamespace(to_dict=lambda: {}),
                attach_formula_checkpoint=self.attach, save_formula_checkpoint=lambda path: runner.write(path, self.checkpoint))
        def attach(self, checkpoint):
            self.checkpoint = copy.deepcopy(checkpoint)
        def infer(self, values):
            assert all(value.sample_id in samples for value in values)
            predictions.extend(value.sample_id for value in values)
            return {"checkpoint_sha256": learning.checkpoint_digest(self.checkpoint),
                    "rows": [{"id": value.sample_id} for value in values]}
    def opening(*args, **kwargs):
        checkpoint = json.loads(Path(kwargs["formula_checkpoint"]).read_text()) if "formula_checkpoint" in kwargs else None
        return Runtime(checkpoint)
    monkeypatch.setattr(runtimes, "open_runtime", opening)
    monkeypatch.setattr(metrics, "compare_free_running_formulas", lambda output, labels, **kwargs: {
        "valid_evaluation": True, "operational_complete": True, "exact_reconstruction": {"matched": len(labels)}})
    if resume_steps == 0:
        with pytest.raises(RuntimeError, match="resume probe did not execute"):
            runner.fit(tmp_path)
        assert not (tmp_path / "frozen.json").exists()
        assert (tmp_path / "fit-started.json").is_file()
        built_before = list(built)
        with pytest.raises(FileExistsError):
            runner.fit(tmp_path)
        assert built == built_before
        return
    runner.fit(tmp_path)
    assert built == [(seed, 8, count, 8) for seed in runner.SEEDS for count in (32, 64)]
    assert [(seed, count) for seed, count, steps in fits if steps == 1000] == [
        (seed, count) for seed in runner.SEEDS for count in (32, 64)]
    assert set(predictions) <= set(samples)
    frozen = json.loads((tmp_path / "frozen.json").read_text())
    assert len(frozen["fits"]) == 6 and frozen["evaluation_targets_opened"] is False
    for ref in frozen["fits"].values():
        result = runner.shared.read_reference(ref)
        head = runner.shared.read_reference(result["head"])
        assert head["progress"]["optimizer_steps"] == 1000
        assert result["row_presentations"] == 8000
        assert result["probe_step_excluded"] is True
        assert result["evaluation_targets_used"] is False
    built_before = list(built)
    with pytest.raises(RuntimeError, match="cannot be refitted"):
        runner.fit(tmp_path)
    assert built == built_before


def test_exposed_campaign_cannot_be_refitted_even_without_frozen_receipt(runner, tmp_path, monkeypatch):
    runtimes = _modules()[0]
    _fake_fast(monkeypatch)
    (tmp_path / "sealed_evaluation").mkdir()
    monkeypatch.setattr(runner, "development_inputs", lambda directory: ({}, {}, {}, {}))
    monkeypatch.setattr(runtimes, "open_runtime", lambda *args, **kwargs: pytest.fail("exposed campaign opened a fitting model"))
    with pytest.raises(RuntimeError, match="cannot be refitted"):
        runner.fit(tmp_path)
    assert not (tmp_path / "fit-started.json").exists()
