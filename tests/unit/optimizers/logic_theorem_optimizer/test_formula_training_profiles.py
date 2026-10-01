"""Existing model configuration interventions are explicit and isolated.

Synthetic vectors below test exact algebra and checkpoint binding, not semantic
embeddings, legal fidelity, or the usefulness of any training profile.
"""
import importlib.util
import json
from pathlib import Path

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import formula_training_profiles as profiles


def test_profiles_are_copy_safe_and_do_not_silently_change_defaults():
    first = profiles.get_training_profile("baseline_v1")
    first["core_options"]["initial_embedding_scale"] = 99.0
    first["formula_options"]["reconstruction_weight"] = 99.0
    default = profiles.get_training_profile("baseline_v1")
    assert default["core_options"]["initial_embedding_scale"] == .02
    assert default["formula_options"]["reconstruction_weight"] == 1.0
    assert profiles.validate_training_profile(json.loads(json.dumps(default))) == default
    assert default["existing_defaults_changed"] is False
    for name in profiles.PROFILE_IDS:
        profile = profiles.get_training_profile(name)
        assert profile["fresh_sparse_core_required"] and profile["fresh_formula_checkpoint_required"]
        assert all(profile[key] is False for key in profiles.FALSE)


@pytest.mark.parametrize("field,change", [
    ("core_options", {"initial_embedding_scale": 1.0}),
    ("formula_options", {"reconstruction_weight": 0.0}),
    ("formula_options", {"formula_weight": True}),
    ("training_budget", {"max_optimizer_steps": 2000}),
])
def test_modified_profile_requires_a_new_version(field, change):
    profile = profiles.get_training_profile("raw_gain10_v1")
    profile[field].update(change)
    with pytest.raises(ValueError, match="versioned definition"):
        profiles.validate_training_profile(profile)


@pytest.mark.parametrize("options", [
    {"domain": "security_ir"}, {"domain": "intent_ir"}, {"domain": "ui_ux_ir"},
    {"runtime_version": "legacy_v1"}, {"runtime_version": "legacy_v1_optimized"},
])
def test_profiles_cannot_be_applied_to_other_domains_or_lineages(options):
    with pytest.raises(ValueError, match="legal_ir/current_v2"):
        profiles.get_training_profile("baseline_v1", **options)
    with pytest.raises(ValueError, match="legal_ir/current_v2"):
        profiles.validate_training_profile(profiles.get_training_profile("baseline_v1"), **options)


def test_unknown_or_authority_elevating_profile_rejected():
    with pytest.raises(ValueError, match="unknown"):
        profiles.get_training_profile("automatic")
    profile = profiles.get_training_profile("baseline_v1")
    profile["qualified"] = True
    with pytest.raises(ValueError, match="versioned definition"):
        profiles.validate_training_profile(profile)


def test_actual_raw_gain_preserves_direction_and_changes_core_binding():
    torch = pytest.importorskip("torch")
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import modal_joint_formula as joint
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import modal_latent_formula as learning
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.autoencoder_lineages import current_v2
    path = Path(__file__).parents[2] / "logic/test_autoencoder_lineage_runtimes.py"
    spec = importlib.util.spec_from_file_location("training_profile_sample_fixture", path)
    fixture = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixture)
    sample = fixture.sample(current_v2)
    target = {"id": sample.sample_id, "source_text": sample.text,
              "canonical_ir": {"rules": [{"modality": "O", "actor": "agency", "action": "submit",
                                         "object": "reports", "conditions": [], "exceptions": [], "temporal": []}]}}
    previous = torch.get_num_threads()
    torch.set_num_threads(1)
    try:
        definitions = [profiles.get_training_profile(name) for name in profiles.PROFILE_IDS]
        models = [current_v2.Autoencoder(**profile["core_options"]) for profile in definitions]
        rows = [joint._rows(model, [sample], [target]) for model in models]
        assert rows[1][0]["latent"] == pytest.approx([10 * value for value in rows[0][0]["latent"]], rel=1e-12, abs=1e-12)
        assert rows[2] == rows[0]
        bindings = [joint._core_binding(model) for model in models]
        assert bindings[0] == bindings[2] and bindings[1] != bindings[0]
        heads = [learning.build_checkpoint(binding, values, [], **profile["formula_options"])
                 for binding, values, profile in zip(bindings, rows, definitions)]
        assert heads[0]["model_state"] == heads[1]["model_state"] == heads[2]["model_state"]
        assert heads[0]["codec"] == heads[1]["codec"] == heads[2]["codec"]
        assert heads[0]["training_manifest_sha256"] == heads[2]["training_manifest_sha256"]
        assert heads[0]["training_manifest_sha256"] != heads[1]["training_manifest_sha256"]
        assert heads[2]["config"]["reconstruction_weight"] == 10.0
        with pytest.raises(ValueError, match="another core"):
            models[1].attach_formula_checkpoint(heads[0])
        models[1].attach_formula_checkpoint(heads[1])
        assert models[1].formula_checkpoint == heads[1]
        assert sample.embedding_vector == fixture.sample(current_v2).embedding_vector
    finally:
        torch.set_num_threads(previous)
