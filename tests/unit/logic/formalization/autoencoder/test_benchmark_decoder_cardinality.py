"""Plan and frozen-replay input controls; these tests never load numerical models."""
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[5]
SCRIPTS = ROOT / "scripts/ops/autoencoder"


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


subject = load("cardinality_benchmark_unit", SCRIPTS / "benchmark_decoder_cardinality.py")
replay = load("cardinality_replay_unit", SCRIPTS / "decoder_fidelity_replay.py")
helpers = load("cardinality_helpers_unit", SCRIPTS / "benchmark_decoder_source_fidelity.py")


def fixed_plan():
    return dict(schema="decoder-cardinality-ablation-plan/v1", representation_dimension=384,
        arms=[dict(name="no_count", guide_boundary=False, cardinality_weight=0.),
              dict(name="aux_count", guide_boundary=False, cardinality_weight=.25),
              dict(name="guided_count", guide_boundary=True, cardinality_weight=.25)],
        seed_order=[1729, 2718], conditioning="every_step", loss="semantic_fields", epochs_per_source_stage=20,
        expected_optimizer_steps_per_arm=340, expected_training_token_presentations_per_arm=225840,
        batch_size=8, learning_rate=.001, max_seconds_per_arm=60, validation_interval=4,
        fixed_encoder_context_tokens=512, fixed_decoder_output_limit=512, projection_frozen=True,
        teacher_distillation_used=False, selection_unchanged=True, no_downloads=True,
        generation_reference_count_access=False, native_qualification=False)


def test_plan_accepts_only_the_predeclared_matched_six_arm_scope():
    plan = fixed_plan(); before = deepcopy(plan)
    subject.validate_plan(plan)
    assert plan == before
    assert len(plan["arms"])*len(plan["seed_order"]) == 6
    first, auxiliary, guided = plan["arms"]
    assert first["cardinality_weight"] == 0 and first["guide_boundary"] is False
    assert auxiliary["cardinality_weight"] == guided["cardinality_weight"] == .25
    assert auxiliary["guide_boundary"] is False and guided["guide_boundary"] is True
    # Additional descriptive metadata is allowed; it cannot override fixed keys.
    subject.validate_plan({**plan, "notes": "exposed development only"})


@pytest.mark.parametrize("key,value", [
    ("representation_dimension", 768), ("seed_order", [1729]),
    ("conditioning", "first_step"), ("loss", "reference_ce"),
    ("epochs_per_source_stage", 21), ("expected_optimizer_steps_per_arm", 339),
    ("expected_training_token_presentations_per_arm", 1), ("batch_size", 16),
    ("learning_rate", .01), ("max_seconds_per_arm", 120), ("validation_interval", 1),
    ("fixed_encoder_context_tokens", 1024), ("fixed_decoder_output_limit", 1024),
    ("projection_frozen", False), ("projection_frozen", 1),
    ("teacher_distillation_used", True), ("selection_unchanged", False),
    ("no_downloads", False), ("generation_reference_count_access", True),
    ("native_qualification", True), ("schema", "different-sweep"),
])
def test_scope_changes_reject_before_numerical_import(key, value):
    plan = fixed_plan(); plan[key] = value
    with pytest.raises(ValueError, match="unsupported cardinality experiment plan"):
        subject.validate_plan(plan)


@pytest.mark.parametrize("mutation", [
    lambda p: p["arms"].pop(),
    lambda p: p["arms"].reverse(),
    lambda p: p["arms"][0].update(cardinality_weight=.25),
    lambda p: p["arms"][1].update(guide_boundary=True),
    lambda p: p["arms"][2].update(cardinality_weight=.5),
    lambda p: p["arms"][2].update(reference_count_at_generation=True),
    lambda p: p.pop("no_downloads"),
])
def test_partial_or_unmatched_controls_cannot_silently_replace_the_plan(mutation):
    plan = fixed_plan(); mutation(plan)
    with pytest.raises(ValueError): subject.validate_plan(plan)


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True))
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def replay_inputs(tmp_path, monkeypatch):
    # Every preparation object is deliberately synthetic and stops before the
    # package import seam. No corpus, vectors, donor tensors or encoders load.
    extension_root = tmp_path / "extensions"
    dependency_root = tmp_path / "dependency"
    dependency_root.mkdir()
    relative = "scripts/ops/autoencoder/benchmark_decoder_source_fidelity.py"
    destination = extension_root / relative
    destination.parent.mkdir(parents=True)
    destination.write_bytes((SCRIPTS / "benchmark_decoder_source_fidelity.py").read_bytes())
    plan_path = tmp_path / "plan.json"
    plan_sha = write_json(plan_path, fixed_plan())
    manifest = dict(extensions={relative: helpers.sha(destination)}, inputs={}, plan_sha256=plan_sha)
    for key in ("donor", "paragraphs", "embeddings", "curriculum", "curriculum_inputs"):
        path = tmp_path / (key+".json")
        expected = write_json(path, dict(synthetic_identity=key))
        manifest[key] = str(path)
        manifest["inputs"][str(path)] = expected
    manifest_path = tmp_path / "manifest.json"
    write_json(manifest_path, manifest)
    arguments = SimpleNamespace(dependency_root=dependency_root, extension_root=extension_root,
        output=tmp_path/"new-results", manifest=manifest_path, plan=plan_path)
    calls = []
    def no_numerical_import(name):
        calls.append(name)
        raise RuntimeError("numerical import sentinel")
    monkeypatch.setattr(replay.importlib, "import_module", no_numerical_import)
    monkeypatch.delitem(sys.modules, "_decoder_fidelity_replay_helpers", raising=False)
    old_path, old_bytecode = list(sys.path), sys.dont_write_bytecode
    yield arguments, manifest, calls
    sys.modules.pop("_decoder_fidelity_replay_helpers", None)
    sys.path[:] = old_path
    sys.dont_write_bytecode = old_bytecode


def test_valid_frozen_preflight_reaches_explicit_import_seam_without_loading_models(replay_inputs):
    arguments, _, calls = replay_inputs
    with pytest.raises(RuntimeError, match="numerical import sentinel"):
        replay.load_context(arguments, validate_plan=subject.validate_plan)
    assert calls == ["ipfs_datasets_py.logic.formalization.autoencoder"]
    assert not arguments.output.exists()


@pytest.mark.parametrize("failure,reason", [
    ("output_exists", "fresh immutable"), ("plan_bytes", "plan changed"),
    ("unsupported_plan", "unsupported cardinality"), ("donor_bytes", "prepared input changed"),
    ("missing_pin", "not pinned"), ("helper_bytes", "replay helper differs"),
    ("wrong_helper_pin", "replay helper differs"), ("relative_input", "not pinned"),
])
def test_replay_guards_reject_mutated_inputs_before_package_import(replay_inputs, failure, reason):
    arguments, manifest, calls = replay_inputs
    if failure == "output_exists": arguments.output.mkdir()
    elif failure == "plan_bytes": arguments.plan.write_text("{}")
    elif failure == "unsupported_plan":
        plan = fixed_plan(); plan["generation_reference_count_access"] = True
        manifest["plan_sha256"] = write_json(arguments.plan, plan)
    elif failure == "donor_bytes": Path(manifest["donor"]).write_text("changed")
    elif failure == "missing_pin": manifest["inputs"].pop(manifest["donor"])
    elif failure == "helper_bytes":
        (arguments.extension_root / "scripts/ops/autoencoder/benchmark_decoder_source_fidelity.py").write_text("raise RuntimeError('must not execute')")
    elif failure == "wrong_helper_pin":
        manifest["extensions"]["scripts/ops/autoencoder/benchmark_decoder_source_fidelity.py"] = "0"*64
    elif failure == "relative_input": manifest["donor"] = "relative-donor.json"
    write_json(arguments.manifest, manifest)
    with pytest.raises(ValueError, match=reason):
        replay.load_context(arguments, validate_plan=subject.validate_plan)
    assert calls == []


def test_length_matched_source_shuffle_is_explicit_and_preserves_targets():
    rows = [dict(id=str(i), input=[float(i)], target_ids=[1, 3+i, 2], source_text="source"+str(i)) for i in range(4)]
    references = [dict(id=str(i), clause_count=1 if i<2 else 4) for i in range(4)]
    before = deepcopy(rows)
    shuffled, receipt = helpers.shuffle_inputs(rows, references)
    lengths = {row["id"]: row["clause_count"] for row in references}
    assert rows == before
    for original, changed in zip(rows, shuffled):
        source = receipt["source_assignment"][original["id"]]
        assert source != original["id"] and lengths[source] == lengths[original["id"]]
        assert changed["input"] != original["input"]
        assert {k:v for k,v in changed.items() if k != "input"} == {k:v for k,v in original.items() if k != "input"}
    assert receipt["kind"] == "source_shuffle" and len(receipt["input_substitutions"]) == 4


@pytest.mark.parametrize("case", ["singleton", "identical_vectors", "duplicate_id", "unknown_reference"])
def test_ineffective_or_unbound_shuffle_cannot_claim_a_control(case):
    rows = [dict(id="one", input=[1.]), dict(id="two", input=[2.])]
    references = [dict(id="one", clause_count=1), dict(id="two", clause_count=1)]
    if case == "singleton": references[1]["clause_count"] = 2
    if case == "identical_vectors": rows[1]["input"] = [1.]
    if case == "duplicate_id": rows[1]["id"] = "one"
    if case == "unknown_reference": references[1]["id"] = "missing"
    with pytest.raises(ValueError): helpers.shuffle_inputs(rows, references)


def small_budget():
    rows = [dict(id="short", target_ids=[1, 3, 2]), dict(id="long", target_ids=[1, 3, 4, 2])]
    stages = [dict(name="short", training_ids=["short"], epochs=20),
        dict(name="all", training_ids=["short", "long"], epochs=20)]
    plan = {**fixed_plan(), "batch_size": 1, "expected_optimizer_steps_per_arm": 60,
        "expected_training_token_presentations_per_arm": 140}
    return stages, rows, plan


def test_prefit_budget_counts_full_targets_and_cumulative_representations_exactly():
    stages, rows, plan = small_budget()
    before = deepcopy((stages, rows, plan))
    result = subject.derive_budget(stages, rows, plan)
    assert result["optimizer_steps"] == 60
    assert result["valid_target_token_presentations"] == 140
    assert result["row_presentations"] == 60
    assert [stage["optimizer_steps"] for stage in result["stages"]] == [20, 40]
    assert [stage["valid_target_token_presentations"] for stage in result["stages"]] == [40, 100]
    assert result["training_executed"] is False and result["deadline_completion_guaranteed"] is False
    assert (stages, rows, plan) == before


def test_prefit_update_count_uses_ceiling_for_partial_minibatches():
    stages, rows, plan = small_budget()
    rows.append(dict(id="third", target_ids=[1, 4, 2]))
    stages[-1]["training_ids"].append("third")
    plan.update(batch_size=2, expected_optimizer_steps_per_arm=60,
        expected_training_token_presentations_per_arm=180)
    result = subject.derive_budget(stages, rows, plan)
    assert result["optimizer_steps"] == 60
    assert result["row_presentations"] == 80


@pytest.mark.parametrize("mutation,reason", [
    (lambda s,r,p: p.update(expected_optimizer_steps_per_arm=59), "update budget"),
    (lambda s,r,p: p.update(expected_training_token_presentations_per_arm=139), "token presentation"),
    (lambda s,r,p: s[-1].update(epochs=19), "epoch budget"),
    (lambda s,r,p: s[-1].update(training_ids=["long"]), "retain previous"),
    (lambda s,r,p: s[-1].update(training_ids=["short"]), "include all"),
    (lambda s,r,p: s[-1].update(training_ids=["short", "missing"]), "existing training"),
    (lambda s,r,p: s[-1].update(training_ids=["short", "short"]), "existing training"),
    (lambda s,r,p: s[-1].update(name=s[0]["name"]), "stage name"),
    (lambda s,r,p: r[-1].update(id="short"), "unique bound"),
    (lambda s,r,p: r[-1].update(target_ids=[1, 3, 0, 2]), "untruncated"),
    (lambda s,r,p: r[-1].update(target_ids=[True, 3, 2]), "untruncated"),
    (lambda s,r,p: r[-1].update(target_ids=[1, 3]), "untruncated"),
    (lambda s,r,p: p.update(batch_size=0), "positive batch"),
    (lambda s,r,p: s.clear(), "nonempty source curriculum"),
])
def test_prefit_inconsistent_work_is_rejected_before_arm_execution(mutation, reason):
    stages, rows, plan = small_budget()
    mutation(stages, rows, plan)
    with pytest.raises(ValueError, match=reason): subject.derive_budget(stages, rows, plan)


def test_control_metadata_explicitly_limits_same_length_shuffle_claims():
    shuffled = subject.control_scope("source_shuffle")
    assert shuffled["shuffle_preserves_reference_clause_count"] is True
    assert shuffled["independent_count_generalization_test"] is False
    assert "count labels deliberately preserved" in shuffled["diagnostic_scope"]
    zero = subject.control_scope("zero_condition")
    assert zero["shuffle_preserves_reference_clause_count"] is False
    assert "learned count bias remains" in zero["diagnostic_scope"]
    assert subject.control_scope("conditioned")["independent_count_generalization_test"] is False
    with pytest.raises(ValueError): subject.control_scope("reference_counts_at_generation")
