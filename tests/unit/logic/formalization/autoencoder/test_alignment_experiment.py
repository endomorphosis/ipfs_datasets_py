"""Training isolation, retrieval composition, and honest experiment controls."""
from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path

import pytest
from ipfs_datasets_py.logic.formalization.autoencoder import alignment_experiment as subject

ROOT = Path(__file__).resolve().parents[5]
CONFIG = ROOT/"configs/autoencoders/alignment_projection_development_v1.json"


def target(actor="clerk", action="retain", modality="O", object_="certificate"):
    return {"rules": [{"modality": modality, "actor": actor, "action": action, "object": object_,
                       "conditions": [], "exceptions": [], "temporal": []}]}


def row(identity, actor, action, first, second, split="train"):
    return {"id": identity, "group_id": "group-"+identity, "split": split, "wording_style": 0,
            "target": target(actor, action), "target_sha256": subject._digest(target(actor, action)),
            "unit_vector": [first, second]+[0.0]*382}


def ranking(candidates, query_id="dev"):
    return [{"id": query_id, "retrieved": [{"candidate_id": c["candidate_id"], "cosine_similarity": .9-i*.1}
                                           for i,c in enumerate(candidates)]}]


@pytest.mark.parametrize("field,value", [("shared_dimensions", [True]), ("seeds", [0, 0]),
    ("negative_weights", [float("nan")]), ("steps", True), ("top_k", 0), ("learning_rate", 2),
    ("temperature", 0), ("max_seconds", 301)])
def test_resource_and_identity_config_is_closed_and_bounded(tmp_path, field, value):
    config = json.loads(CONFIG.read_text())
    config[field] = value
    path = tmp_path/"config.json"
    path.write_text(json.dumps(config))
    with pytest.raises(ValueError):
        subject.load_projection_experiment_config(path)


def test_config_acceptance_binds_exact_bytes_without_optional_import(tmp_path):
    value, binding = subject.load_projection_experiment_config(CONFIG)
    assert value["seeds"] == [0, 1, 2]
    assert binding["sha256"] == hashlib.sha256(CONFIG.read_bytes()).hexdigest()


def test_training_duplicate_wordings_collapse_into_identical_candidate_pool():
    a = row("a", "clerk", "retain", 1., 0.)
    b = row("b", "clerk", "retain", 0., 1.)
    candidates = subject.training_candidates([a,b])
    assert len(candidates) == 1 and candidates[0]["train_ids"] == ["a", "b"]
    assert candidates[0]["source_vector"][:2] == pytest.approx([2**-.5]*2)
    assert subject.training_candidates([b,a]) == candidates


def test_complementary_support_requires_correct_modality_and_object():
    candidates = subject.training_candidates([row("a", "clerk", "issue", 1., 0.),
                                              row("b", "officer", "retain", 0., 1.)])
    dev = row("dev", "clerk", "retain", 1., 0., "validation")
    score = subject.score_rankings(ranking(candidates), [dev], candidates, 2)
    assert score["summary"]["complementary_actor_action_support"] == 1
    assert score["summary"]["best_top_k_core_fraction"] == .75
    assert score["summary"]["core_ndcg"] == 1
    next(c for c in candidates if c["target"]["rules"][0]["action"] == "retain")["target"]["rules"][0]["modality"] = "F"
    score = subject.score_rankings(ranking(candidates), [dev], candidates, 2)
    assert score["summary"]["complementary_actor_action_support"] == 0
    assert score["summary"]["action_support"] == 0


def test_development_reference_mutation_cannot_change_source_only_rankings():
    candidates = subject.training_candidates([row("a", "clerk", "retain", 1., 0.),
                                              row("b", "officer", "issue", 0., 1.)])
    dev = row("dev", "executor", "retain", .8, .6, "validation")
    def ranks():
        return subject.rank_vectors([dev["id"]], [dev["unit_vector"]],
            [c["candidate_id"] for c in candidates], [c["source_vector"] for c in candidates], 2)
    frozen = ranks()
    first = subject.score_rankings(frozen, [dev], candidates, 2)
    dev["target"] = target("executor", "issue", "F")
    assert ranks() == frozen
    assert subject.score_rankings(frozen, [dev], candidates, 2)["summary"] != first["summary"]


def test_rankings_reject_duplicate_or_external_candidate_ids():
    candidates = subject.training_candidates([row("a", "clerk", "retain", 1., 0.)])
    dev = row("dev", "executor", "retain", .8, .6, "validation")
    bad = ranking(candidates)
    bad[0]["retrieved"][0]["candidate_id"] = "not-training"
    with pytest.raises(ValueError, match="declared unique"):
        subject.score_rankings(bad, [dev], candidates, 1)


def test_model_fit_has_no_development_inputs_and_changes_both_heads():
    torch = pytest.importorskip("torch")
    from ipfs_datasets_py.logic.formalization.autoencoder.alignment_projection import (
        create_projection_heads,
    )

    training = [row("a", "clerk", "retain", 1., 0.), row("b", "officer", "issue", 0., 1.)]
    settings = {"steps": 4, "temperature": .07, "learning_rate": .1, "weight_decay": .0001}
    original_threads = torch.get_num_threads()
    try:
        torch.set_num_threads(1)
        model, codec, trace = subject._fit_projection(training, settings, 384, 0, 2, float("inf"))
        initial = create_projection_heads(384, codec["feature_dimension"], 384, 0)
        assert trace["completed_steps"] == 4 and not trace["development_used_in_fit"]
        assert all(torch.isfinite(p).all() for p in model.parameters())
        changed = [name for name, tensor in model.state_dict().items() if not torch.equal(tensor, initial.state_dict()[name])]
        assert any("source" in name for name in changed) and any("formal" in name for name in changed)
        clone, clone_codec, clone_trace = subject._fit_projection(deepcopy(training), settings, 384, 0, 2, float("inf"))
        assert codec == clone_codec
        assert trace["pre_step_losses"] == clone_trace["pre_step_losses"]
        assert all(torch.equal(v, clone.state_dict()[k]) for k,v in model.state_dict().items())
    finally:
        torch.set_num_threads(original_threads)


def test_deadline_preserves_partial_training_steps():
    pytest.importorskip("torch")
    training = [row("a", "clerk", "retain", 1., 0.), row("b", "officer", "issue", 0., 1.)]
    settings = {"steps": 4, "temperature": .07, "learning_rate": .1, "weight_decay": .0001}
    _, _, trace = subject._fit_projection(training, settings, 384, 0, 1, 0)
    assert trace["completed_steps"] == 0 and trace["requested_steps"] == 4


def test_repository_mismatch_and_existing_evidence_fail_before_fit(tmp_path):
    with pytest.raises(ValueError, match="executing study package"):
        subject.run_projection_experiment(CONFIG, tmp_path, tmp_path, tmp_path/"run")
    with pytest.raises(ValueError, match="fresh output"):
        subject.run_projection_experiment(CONFIG, ROOT, tmp_path, tmp_path)


def test_loaded_projection_module_from_another_tree_is_rejected(tmp_path, monkeypatch):
    from types import SimpleNamespace

    monkeypatch.setitem(subject.sys.modules,
                        "ipfs_datasets_py.logic.formalization.autoencoder.alignment_projection",
                        SimpleNamespace(__file__=str(tmp_path/"alignment_projection.py")))
    with pytest.raises(ValueError, match="another tree"):
        subject.run_projection_experiment(CONFIG, ROOT, tmp_path, tmp_path/"output")


def test_full_experiment_reference_mutation_preserves_checkpoint_and_rankings(tmp_path):
    pytest.importorskip("torch")
    base = json.loads((ROOT/"configs/autoencoders/alignment_study_development_v1.json").read_text())
    settings = json.loads(CONFIG.read_text())
    settings.update(shared_dimensions=[384], seeds=[0], negative_weights=[1], steps=2)
    (tmp_path/"protocol.md").write_text("protected protocol")
    (tmp_path/"provenance.json").write_text("{}")
    def binding(path):
        return {"path": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    base["protected_protocols"] = [binding(tmp_path/"protocol.md")]
    base["corpus"]["provenance"] = [binding(tmp_path/"provenance.json")]
    def source_row(identity, actor, action, vector, split):
        text = f"The {actor} must {action} the certificate."
        return {"id": identity, "group_id": "group-"+identity, "split": split, "source_text": text,
                "source_sha256": hashlib.sha256(text.encode()).hexdigest(),
                "embedding": vector, "embedding_sha256": subject._digest(vector), "target": target(actor, action)}
    train = [source_row("a", "clerk", "retain", [1.,0.]+[0.]*382, "train"),
             source_row("b", "officer", "issue", [0.,1.]+[0.]*382, "train")]
    dev = [source_row("dev", "executor", "register", [.8,.6]+[0.]*382, "validation")]
    (tmp_path/"train.json").write_text(json.dumps({"rows": train}))
    base["corpus"]["train"] = binding(tmp_path/"train.json")
    def execute(destination):
        (tmp_path/"validation.json").write_text(json.dumps({"rows": dev}))
        base["corpus"]["development"] = binding(tmp_path/"validation.json")
        (tmp_path/"base.json").write_text(json.dumps(base))
        settings["study_config"] = binding(tmp_path/"base.json")
        (tmp_path/"experiment.json").write_text(json.dumps(settings))
        return subject.run_projection_experiment(tmp_path/"experiment.json", ROOT, tmp_path, tmp_path/destination)
    first = execute("run-01")
    dev[0]["target"] = target("executor", "register", "F")
    second = execute("run-02")
    a, b = first["trials"][0], second["trials"][0]
    assert a["checkpoint"]["sha256"] == b["checkpoint"]["sha256"]
    assert first["candidate_pool"] == second["candidate_pool"]
    for arm in ("source_to_source", "source_to_formal"):
        assert [r["retrieved"] for r in a[arm]["rows"]] == [r["retrieved"] for r in b[arm]["rows"]]
    assert a["source_to_formal"]["summary"] != b["source_to_formal"]["summary"]
    reviewer = json.loads((tmp_path/"run-01/reviewer_items.json").read_text())
    assert "organizer_payload" not in reviewer
    assert first["primary_fidelity"]["status"] == "unavailable" and not first["qualified"]
