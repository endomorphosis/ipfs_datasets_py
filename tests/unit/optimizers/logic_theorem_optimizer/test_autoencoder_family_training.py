"""Real target/weight integration and rare-family objective regression tests."""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import autoencoder_family_training as trainer
from ipfs_datasets_py.logic.formalization.autoencoder.family_training import prepare_family_training_targets
from ipfs_datasets_py.logic.intent_ir.formalize.rich_grammar import parse_instruction


def report(text, families=None):
    return prepare_family_training_targets("intent_ir", document=parse_instruction(text),
        source_text=text, requested_families=families)


@pytest.fixture
def corpus():
    families = ["dcec", "deontic", "frame_logic", "tdfol"]
    training = [report(f"The agent must save the {name} document.", families)
                for name in ("amber", "cobalt", "ivory")]
    validation = [report("The agent must save the validationunique report.", families)]
    return training, validation


def test_rare_families_and_absent_targets_are_not_diluted():
    torch = pytest.importorskip("torch")
    target = torch.ones((4, 3), dtype=torch.float64)
    prediction = torch.tensor([[2., 2., 3.], [2., 2., 1000.], [2., 2., -1000.], [2., 2., 0.]])
    mask = torch.tensor([[True, True, True], [True, True, False], [True, True, False], [True, True, False]])
    spans = {"a": (0, 1), "b": (1, 2), "c": (2, 3)}
    descriptors = {"a": {"logic_family": "deontic"}, "b": {"logic_family": "deontic"},
                   "c": {"logic_family": "event_calculus"}}
    loss, metrics = trainer._objective(torch, prediction, target, mask, spans, descriptors)
    assert float(loss) == pytest.approx(2.5)
    assert metrics["families"] == pytest.approx({"deontic": 1., "event_calculus": 4.})
    # Averaging minibatch estimates recovers the same full-corpus objective,
    # including batches with no event-calculus rows at all.
    estimates = [trainer._objective(torch, prediction[i:i+1], target[i:i+1], mask[i:i+1],
                spans, descriptors, population=(4, [4, 4, 1]))[0] for i in range(4)]
    assert float(sum(estimates) / 4) == pytest.approx(2.5)


def test_native_targets_train_reload_and_infer_without_validation_vocabulary(tmp_path, corpus):
    pytest.importorskip("torch")
    training, validation = corpus
    result = trainer.train_family_projection_autoencoder(training, validation,
        output_dir=tmp_path / "first", epochs=3, latent_width=2)
    saved, _ = trainer._read(result["descriptor"])
    assert not any("validationunique" in atom for _, atom in saved["space"]["columns"])
    assert result["report"]["optimizer_steps"] == 3
    assert result["report"]["trained_logic_families"] == ["dcec", "deontic", "frame_logic", "tdfol"]
    assert result["report"]["source_text_decoder_trained"] is False
    assert result["report"]["after"]["objective"] <= result["report"]["before"]["objective"]
    assert all(result["report"][key] is False for key in trainer.FALSE)
    inference = trainer.infer_family_projection_autoencoder(result["descriptor"], validation)
    assert inference["objective"] == pytest.approx(result["report"]["after"]["objective"])
    assert inference["formulas_generated"] is False
    assert any(row["unknown_atoms"] for row in inference["coverage"]["projections"])


def test_continuation_keeps_parent_and_validation_fixed(tmp_path, corpus):
    training, validation = corpus
    first = trainer.train_family_projection_autoencoder(training, validation,
        output_dir=tmp_path / "first", epochs=1, latent_width=2)
    original = (tmp_path / "first/family_checkpoint.json").read_bytes()
    next_train = [report("The agent must save the golden document.", ["dcec", "deontic", "frame_logic", "tdfol"])]
    child = trainer.train_family_projection_autoencoder(next_train, validation,
        output_dir=tmp_path / "child", epochs=1, latent_width=2, parent_descriptor=first["descriptor"])
    assert (tmp_path / "first/family_checkpoint.json").read_bytes() == original
    assert child["report"]["initialization"] == "complete_parent_structural_head"
    assert child["report"]["before"] == first["report"]["after"]
    with pytest.raises(ValueError, match="historical training/validation"):
        trainer.train_family_projection_autoencoder(next_train, training,
            output_dir=tmp_path / "bad", epochs=1, latent_width=2, parent_descriptor=first["descriptor"])


def test_source_overlap_and_forged_target_rejected_before_output(tmp_path, corpus):
    training, validation = corpus
    with pytest.raises(ValueError, match="source leakage"):
        trainer.train_family_projection_autoencoder(training, training,
            output_dir=tmp_path / "bad", epochs=1)
    assert not (tmp_path / "bad").exists()
    forged = copy.deepcopy(validation)
    forged[0]["projections"][0]["payload"] = {"fake": "proof"}
    with pytest.raises(ValueError, match="digest"):
        trainer.train_family_projection_autoencoder(training, forged,
            output_dir=tmp_path / "forged", epochs=1)
    assert not (tmp_path / "forged").exists()


def test_missing_family_mask_and_unseen_validation_family_are_explicit(tmp_path):
    training = [report("The agent must save amber records.", ["deontic", "tdfol"]),
                report("The agent must save cobalt records.", ["deontic"])]
    validation = [report("The agent must save violet records.", ["deontic", "tdfol", "dcec"])]
    trained = trainer.train_family_projection_autoencoder(training, validation,
        output_dir=tmp_path / "masked", epochs=1, latent_width=2)
    coverage = trained["report"]["validation_coverage"]
    assert any("dcec" in name for name in coverage["untrained_projection_ids"])
    assert "dcec" not in trained["report"]["trained_logic_families"]
    assert sum(row["projection_id"].endswith("/tdfol/v1") for row in
               trained["report"]["training_coverage"]["projections"]) == 1


def test_checkpoint_tamper_is_rejected(tmp_path, corpus):
    training, validation = corpus
    result = trainer.train_family_projection_autoencoder(training, validation,
        output_dir=tmp_path / "model", epochs=1, latent_width=2)
    path = tmp_path / "model/family_checkpoint.json"
    saved = json.loads(path.read_bytes())
    saved["parameters"][0][0][0] += 1.
    path.write_text(json.dumps(saved))
    with pytest.raises(ValueError, match="digest mismatch"):
        trainer.infer_family_projection_autoencoder(result["descriptor"], validation)


def test_native_projector_drift_invalidates_saved_head(tmp_path, corpus, monkeypatch):
    from ipfs_datasets_py.logic.intent_ir.formalize import extended_projections
    training, validation = corpus
    result = trainer.train_family_projection_autoencoder(training, validation,
        output_dir=tmp_path / "model", epochs=1, latent_width=2)
    native = Path(extended_projections.__file__)
    original = Path.read_bytes
    monkeypatch.setattr(Path, "read_bytes", lambda path: original(path) + b"# changed" if path == native else original(path))
    with pytest.raises(ValueError, match="native target producer changed"):
        trainer.infer_family_projection_autoencoder(result["descriptor"], validation)


def test_vocabulary_budget_retains_every_family_using_training_document_frequency():
    reports = [report(f"The agent must save the {name} document.") for name in ("amber", "cobalt", "ivory", "jade")]
    domain, rows = trainer._reports(reports)
    space = trainer._space(domain, reports, rows)
    assert len(space["columns"]) <= trainer.MAX_FEATURES
    assert set(name for name, _ in space["columns"]) == set(space["projections"])
    assert any(space["feature_selection"]["available_atoms"][name] > value
               for name, value in space["feature_selection"]["retained_atoms"].items())
