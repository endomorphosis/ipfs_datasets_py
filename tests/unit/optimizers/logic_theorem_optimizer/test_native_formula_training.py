"""Decoder-aware native training diagnostics, never semantic/Lake qualification."""
import copy
import hashlib
import importlib
import importlib.util
import os
from pathlib import Path
import sys

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_projection_features as features

PREFIX = "ipfs_datasets_py.optimizers.logic_theorem_optimizer"
ROOT = Path(features.__file__).resolve().parents[3]


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value


if os.environ.get("NATIVE_FORMULA_TRAINING_PATH"):
    learner = _load(os.environ["NATIVE_FORMULA_TRAINING_PATH"], PREFIX + ".native_formula_training")
else:
    learner = importlib.import_module(PREFIX + ".native_formula_training")
fixtures = _load(ROOT / "tests/unit/optimizers/logic_theorem_optimizer/test_autoencoder_projection_features.py",
                 "_native_formula_training_fixtures")


@pytest.fixture(autouse=True)
def one_cpu_thread():
    import torch
    previous = torch.get_num_threads()
    torch.set_num_threads(1)
    yield
    torch.set_num_threads(previous)


def _case(domain):
    prepare = {"intent_ir": fixtures._intent, "security_ir": fixtures._security, "ui_ux_ir": fixtures._ui}[domain]
    training = [prepare(1).to_dict(), prepare(2).to_dict()]
    projection = {"intent_ir": "intent-route/intentions/v1", "security_ir": "program.program_ir/v1",
                  "ui_ux_ir": "ui_ux_ir:event_calculus"}[domain]
    # Authored repeated structures under disjoint source identities exercise
    # reconstruction/storage plumbing, not semantic generalization. The report
    # must disclose this overlap rather than call it a held-out canary.
    tuning = copy.deepcopy(training)
    for index, target in enumerate(tuning):
        target["source_digest"] = hashlib.sha256(f"native-diagnostic-tuning/{domain}/{index}".encode()).hexdigest()
    return training, tuning, [projection]


def _build(domain="intent_ir", **config):
    training, tuning, ids = _case(domain)
    cp = learner.build_native_formula_checkpoint(domain, training, tuning, projection_ids=ids,
        latent_width=8, learning_rate=.04, batch_size=1, **config)
    return cp, training, tuning


_corpus = _case


@pytest.mark.parametrize("domain", ("intent_ir", "security_ir", "ui_ux_ir"))
def test_three_native_domains_train_real_categorical_head_and_decode(domain):
    cp, training, tuning = _build(domain)
    original = learner.checkpoint_digest(cp)
    result = learner.train_native_formula(cp, training, tuning, epochs=35, max_seconds=60)
    report, child = result["report"], result["checkpoint"]
    assert learner.validate_training_result(result) == report["checkpoint_sha256"]
    assert report["optimizer_steps"] == 70
    assert report["decoder_gradient_norm_max"] > 0
    assert report["initial_parameter_sha256"] != report["final_parameter_sha256"]
    assert child["latest"]["parameters"]["encoder_weight"] != cp["latest"]["parameters"]["encoder_weight"]
    assert child["latest"]["parameters"]["decoder_weight"] != cp["latest"]["parameters"]["decoder_weight"]
    assert report["training_after"]["categorical_cross_entropy"] < report["training_before"]["categorical_cross_entropy"]
    assert report["training_after"]["exact_projection_count"] == 2, report["training_after"]
    assert report["selected_tuning"]["exact_projection_count"] == 2
    assert report["tuning_structure_overlap_count"] == 2
    assert all(row["tuning"]["native_readout_executed"] for row in report["epoch_reports"])
    decoded = learner.infer_native_formula(child, training)
    assert decoded["decoded_projection_count"] == 2
    assert decoded["selected_weights"] and decoded["trained_neural_decoder"]
    assert all(decoded[key] is False for key in learner.FALSE)
    assert decoded["rows"][0]["projections"] != decoded["rows"][1]["projections"]
    assert learner.checkpoint_digest(cp) == original
    assert child["parent_checkpoint_sha256"] is None


def test_wrong_minority_polarity_has_loss_and_nonzero_gradient():
    import torch
    groups = [{"columns": [0]}, {"columns": [1]}, {"columns": [2, 3]}]
    # Many constant grammar fields do not dilute a wrong polarity leaf.
    groups = [{"columns": [0]} for _ in range(100)] + [groups[-1]]
    labels = torch.zeros((1, len(groups)), dtype=torch.long)
    right = torch.tensor([[10., 10., 8., -8.]], dtype=torch.float64, requires_grad=True)
    wrong = torch.tensor([[10., 10., -8., 8.]], dtype=torch.float64, requires_grad=True)
    right_loss = learner._categorical_loss(right, labels, groups)
    wrong_loss = learner._categorical_loss(wrong, labels, groups)
    wrong_loss.backward()
    assert wrong_loss > right_loss + 15
    assert wrong.grad[0, 2] < -.9 and wrong.grad[0, 3] > .9
    assert wrong.grad[0, 0] == 0


def test_exact_resume_keeps_adam_partial_epoch_and_candidate_selection(tmp_path):
    cp, training, tuning = _build()
    first = learner.train_native_formula(cp, training, tuning, epochs=2, max_optimizer_steps=1)
    assert first["checkpoint"]["latest"]["progress"]["row_cursor"] == 1
    path = tmp_path / "candidate.json"
    saved = learner.save_checkpoint(first["checkpoint"], path)
    loaded = learner.load_checkpoint(path, expected_sha256=saved["sha256"])
    resumed = learner.train_native_formula(loaded, training, tuning, epochs=2)
    full = learner.train_native_formula(cp, training, tuning, epochs=2)
    assert resumed["checkpoint"]["latest"] == full["checkpoint"]["latest"]
    assert resumed["checkpoint"]["selected"] == full["checkpoint"]["selected"]
    assert resumed["checkpoint"]["parent_checkpoint_sha256"] == learner.checkpoint_digest(loaded)
    assert learner.checkpoint_binding(resumed["checkpoint"]) == learner.checkpoint_binding(cp)
    assert all(row["step"] == 4 for row in resumed["checkpoint"]["latest"]["adam"].values())
    with pytest.raises(FileExistsError):
        learner.save_checkpoint(loaded, path)
    with pytest.raises(learner.NativeFormulaError, match="SHA"):
        learner.load_checkpoint(path, expected_sha256="a" * 64)


def test_epoch_resume_matches_uninterrupted_and_inference_uses_selected_or_latest():
    cp, training, tuning = _build()
    first = learner.train_native_formula(cp, training, tuning, epochs=1)["checkpoint"]
    resumed = learner.train_native_formula(first, training, tuning, epochs=1)["checkpoint"]
    full = learner.train_native_formula(cp, training, tuning, epochs=2)["checkpoint"]
    assert resumed["latest"] == full["latest"] and resumed["selected"] == full["selected"]
    assert learner.infer_native_formula(resumed, training, selected=False)["optimizer_steps"] == 4
    assert learner.infer_native_formula(resumed, training)["optimizer_steps"] == resumed["selected"]["optimizer_steps"]


def test_zero_and_changed_scores_never_copy_input_gold():
    cp, training, tuning = _build()
    result = learner.train_native_formula(cp, training, tuning, epochs=25)["checkpoint"]
    zero = copy.deepcopy(result)
    for key in ("decoder_weight", "decoder_bias"):
        if key.endswith("weight"):
            zero["selected"]["parameters"][key] = [[0. for v in row] for row in zero["selected"]["parameters"][key]]
        else:
            zero["selected"]["parameters"][key] = [0. for v in zero["selected"]["parameters"][key]]
    decoded = learner.infer_native_formula(zero, training)
    assert decoded["status"] == "abstained"
    assert all(row["projections"][0]["expression"] is None for row in decoded["rows"])


def test_decoded_invalidity_dominates_numerically_better_selection():
    cp, training, tuning = _build()
    report = learner.train_native_formula(cp, training, tuning, epochs=1)["report"]
    valid = copy.deepcopy(report["selected_tuning"])
    valid.update(valid_projection_count=2, exact_projection_count=2, invalid_projection_count=0)
    valid["invalid_reasons"] = {}
    for row in valid["projections"].values():
        row.update(valid=2, exact=2)
    invalid = copy.deepcopy(valid)
    invalid.update(valid_projection_count=0, exact_projection_count=0, invalid_projection_count=2,
                   categorical_cross_entropy=0.)
    invalid["invalid_reasons"] = {"decoded_native_validation_failed": 2}
    for row in invalid["projections"].values():
        row.update(valid=0, exact=0)
    assert learner._selection_key(valid) > learner._selection_key(invalid)


def test_unknown_atoms_mixed_shapes_split_overlap_and_changed_manifests_reject():
    cp, training, tuning = _build()
    with pytest.raises(learner.NativeFormulaError, match="unknown"):
        learner.infer_native_formula(cp, [fixtures._intent(30)])
    with pytest.raises(learner.NativeFormulaError, match="leakage"):
        learner.build_native_formula_checkpoint("intent_ir", training, training,
            projection_ids=cp["feature_space"]["projection_ids"])
    with pytest.raises(learner.NativeFormulaError, match="manifest"):
        learner.train_native_formula(cp, list(reversed(training)), tuning)
    changed = copy.deepcopy(training)
    selected = next(row for row in changed[1]["projections"] if row["projection_id"] == "intent-route/intentions/v1")
    selected["expression"].append(copy.deepcopy(selected["expression"][0]))
    with pytest.raises(learner.NativeFormulaError, match="variable shape"):
        learner.build_native_formula_checkpoint("intent_ir", changed, tuning,
            projection_ids=cp["feature_space"]["projection_ids"])


def test_constant_targets_cannot_claim_categorical_training():
    training, tuning, _ = _case("ui_ux_ir")
    with pytest.raises(learner.NativeFormulaError, match="no variable"):
        learner.build_native_formula_checkpoint("ui_ux_ir", training, tuning,
            projection_ids=["ui_ux_ir:flogic"])


def test_zero_deadline_preserves_latest_adam_and_reports_no_training():
    cp, training, tuning = _build()
    result = learner.train_native_formula(cp, training, tuning, epochs=4, max_seconds=0)
    assert result["checkpoint"]["latest"] == cp["latest"]
    assert result["checkpoint"]["selected"] == cp["selected"]
    assert result["report"]["stopped_reason"] == "deadline"
    assert not result["report"]["training_executed"]
    assert result["report"]["training_before"] is None


def test_deadline_preserves_pending_decoded_evaluation_before_more_updates(monkeypatch):
    import torch
    cp, training, tuning = _build()
    class Clock:
        now = 0.
        def monotonic(self):
            return self.now
    clock = Clock()
    loss = learner._categorical_loss
    count = 0
    def timed_loss(*args):
        nonlocal count
        value = loss(*args)
        if torch.is_grad_enabled():
            count += 1
            if count == 2:
                clock.now = 2.
        return value
    with monkeypatch.context() as patch:
        patch.setattr(learner, "time", clock)
        patch.setattr(learner, "_categorical_loss", timed_loss)
        interrupted = learner.train_native_formula(cp, training, tuning, epochs=2, max_seconds=1)
    pending = interrupted["checkpoint"]
    assert pending["latest"]["progress"] == {"epochs_completed": 1, "row_cursor": 0,
                                               "optimizer_steps": 2, "pending_evaluation": True}
    assert interrupted["report"]["stopped_reason"] == "deadline"
    resumed = learner.train_native_formula(pending, training, tuning, epochs=1)
    uninterrupted = learner.train_native_formula(cp, training, tuning, epochs=2)
    assert resumed["checkpoint"]["latest"] == uninterrupted["checkpoint"]["latest"]
    assert resumed["checkpoint"]["selected"] == uninterrupted["checkpoint"]["selected"]
    assert [r["epoch"] for r in resumed["report"]["epoch_reports"]] == [1, 2]


@pytest.mark.parametrize("field,value", [("qualified", True), ("proof_authority", True),
    ("publication_performed", True), ("checkpoint_sha256", "b" * 64), ("runtime_version", "native_v1"),
    ("parent_checkpoint_sha256", "c" * 64), ("progress", {})])
def test_forged_training_report_rejected(field, value):
    cp, training, tuning = _build()
    result = learner.train_native_formula(cp, training, tuning, epochs=1)
    result["report"][field] = value
    with pytest.raises(learner.NativeFormulaError):
        learner.validate_training_result(result)


def test_checkpoint_config_moments_authority_and_producer_fail_closed(monkeypatch):
    cp, training, tuning = _build()
    cp = learner.train_native_formula(cp, training, tuning, epochs=1)["checkpoint"]
    corruptions = [lambda c: c["config"].update(temperature=1),
        lambda c: c.update(admitted=True),
        lambda c: c["latest"]["adam"]["encoder_bias"].update(step=0),
        lambda c: c["latest"]["adam"]["encoder_bias"]["exp_avg_sq"].__setitem__(0, -1.),
        lambda c: c["implementation"].update(numerical={})]
    for corrupt in corruptions:
        changed = copy.deepcopy(cp); corrupt(changed)
        with pytest.raises(learner.NativeFormulaError):
            learner.validate_checkpoint(changed)
    original = Path.read_bytes
    own = Path(learner.__file__).resolve()
    monkeypatch.setattr(Path, "read_bytes", lambda path: original(path) + b"\n# drift" if path.resolve() == own else original(path))
    with pytest.raises(learner.NativeFormulaError, match="source changed"):
        learner.infer_native_formula(cp, training)


def test_thread_policy_is_caller_owned():
    import torch
    torch.set_num_threads(2)
    with pytest.raises(learner.NativeFormulaError, match="caller-managed"):
        learner._torch()
    assert torch.get_num_threads() == 2
