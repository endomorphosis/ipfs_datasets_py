"""Group exclusion and metadata boundaries for the shared numerical recipe."""
from copy import deepcopy

import pytest

from ipfs_datasets_py.logic.formalization.autoencoder import grouped_source_training_384 as subject


def target(first=0, second=0):
    return {"kind": "intent_rich_ast", "document": {"kind": "atom",
        "actor": ["operator", "auditor"][first], "action": ["save", "erase"][second],
        "object": "report", "modality": "required"}}


def rows(split):
    result = []
    for index, (first, second) in enumerate(((0, 0), (0, 1), (1, 0))):
        for variant in range(2):
            result.append({"id": f"{split}-{index}-{variant}", "group_id": f"{split}-group-{index}",
                "split": split, "source_text": f"{split} source {index} wording {variant}",
                "embedding": [float(first) * 2 - 1, float(second) * 2 - 1,
                    (.001 if split == "train" else .011) + variant * .001 + index * .0001] + [0.] * 381,
                "target": target(first, second)})
    return result


def forbid_fit(monkeypatch):
    monkeypatch.setattr(subject.api, "train_structured_source_decoder_384",
        lambda *args, **kwargs: pytest.fail("invalid corpus reached fitting"))


@pytest.mark.parametrize("side", ["train", "validation"])
@pytest.mark.parametrize("split", ["test", "canary", "tuning", "valid", "inference", ""])
def test_fit_rejects_wrong_split_before_numerical_work(monkeypatch, side, split):
    forbid_fit(monkeypatch)
    training, validation = rows("train"), rows("validation")
    (training if side == "train" else validation)[0]["split"] = split
    with pytest.raises(ValueError, match="expected .* split"):
        subject.train_grouped_source_decoder_384("intent_ir", training, validation, parent_projection={})


@pytest.mark.parametrize("extra", ["reference_metadata", "proof_authority", "latent", "source_sha256", "knowledge_graph"])
def test_metadata_cannot_enter_feature_rows(monkeypatch, extra):
    forbid_fit(monkeypatch)
    training = rows("train")
    training[0][extra] = {"answer": "forbidden"}
    with pytest.raises(ValueError, match="closed grouped"):
        subject.train_grouped_source_decoder_384("intent_ir", training, rows("validation"), parent_projection={})


@pytest.mark.parametrize("key", subject.EXCLUSION_KEYS)
def test_independent_leakage_routes_are_rejected(monkeypatch, key):
    forbid_fit(monkeypatch)
    training, validation = rows("train"), rows("validation")
    if key in ("id", "group_id"):
        validation[0][key] = training[0][key]
    elif key == "source_sha256":
        validation[0]["source_text"] = training[0]["source_text"]
    elif key == "normalized_source_sha256":
        validation[0]["source_text"] = "  " + training[0]["source_text"].upper().replace(" ", "\n  ") + " "
    else:
        validation[0]["embedding"] = [int(value) if value == int(value) else value
            for value in training[0]["embedding"]]
        validation[0]["embedding"][-1] = -0.0
        assert subject.digest(validation[0]["embedding"]) != subject.digest(training[0]["embedding"])
    with pytest.raises(ValueError, match="training/validation " + key + " overlap"):
        subject.train_grouped_source_decoder_384("intent_ir", training, validation, parent_projection={})


@pytest.mark.parametrize("key", ["source_text", "embedding"])
def test_identical_variants_cannot_claim_different_groups(monkeypatch, key):
    forbid_fit(monkeypatch)
    training = rows("train")
    training[2][key] = deepcopy(training[0][key])
    with pytest.raises(ValueError, match="different leakage groups"):
        subject.train_grouped_source_decoder_384("intent_ir", training, rows("validation"), parent_projection={})


@pytest.mark.parametrize("key", ["source_text", "embedding"])
def test_identical_decoder_inputs_cannot_have_conflicting_labels(monkeypatch, key):
    forbid_fit(monkeypatch)
    training = rows("train")
    training[1][key] = deepcopy(training[0][key])
    training[1]["target"] = target(1, 1)
    with pytest.raises(ValueError, match="conflicting targets"):
        subject.train_grouped_source_decoder_384("intent_ir", training, rows("validation"), parent_projection={})


@pytest.mark.parametrize("domain", subject.shared.DOMAINS)
def test_all_four_native_target_owners_validate_before_fit(monkeypatch, domain):
    forbid_fit(monkeypatch)
    training = rows("train")
    training[0]["target"] = {"unknown_contract": True}
    with pytest.raises((ValueError, TypeError, KeyError)):
        subject.train_grouped_source_decoder_384(domain, training, rows("validation"), parent_projection={})


def test_ui_semantic_vocabulary_uses_strict_public_preflight(monkeypatch):
    monkeypatch.setattr(subject.structured, "train", lambda *args, **kwargs: pytest.fail("invalid UI fitted"))
    training, validation = rows("train"), rows("validation")
    for row in training + validation:
        row["target"] = {"kind": "ui_component", "document": {"component_id": "submit", "role": "button",
            "privacy_sensitivity": "sensitive", "presentation_classification": "interactive"}}
    with pytest.raises(ValueError, match="closed vocabulary"):
        subject.train_grouped_source_decoder_384("ui_ux_ir", training, validation, parent_projection={})


def test_dispatch_removes_group_metadata_and_preserves_options_and_checkpoint(monkeypatch):
    training, validation = rows("train"), rows("validation")
    # One leakage unit can include different actions/actors/polarities.
    for row in training:
        row["group_id"] = "one-shared-training-group"
    original = deepcopy((training, validation))
    checkpoint = {"schema": "unmodified-checkpoint-test", "parent_sha256": "a" * 64,
        "config": {"ridges": [.01]}}
    parent, config = {"parent": True}, {"ridges": [.01]}

    def fit(domain, train, tune, **options):
        assert domain == "intent_ir"
        assert all(set(row) == set(subject.DECODER_FIELDS) for row in train + tune)
        assert options == {"parent_projection": parent, "config": config}
        return {"checkpoint": checkpoint, "metrics": {"test_used_for_selection": False}}

    monkeypatch.setattr(subject.api, "train_structured_source_decoder_384", fit)
    result = subject.train_grouped_source_decoder_384("intent_ir", training, validation,
        parent_projection=parent, config=config)
    assert result["checkpoint"] is checkpoint
    assert (training, validation) == original
    report, recipe = result["report"], result["report"]["recipe"]
    assert report["training_variant_count"] == 6
    assert report["training_unique_group_count"] == 1
    assert report["training_variants_per_public_fit_second"] == pytest.approx(
        6 * report["training_groups_per_public_fit_second"])
    assert report["validation_unique_group_count"] == 3
    assert recipe["checkpoint_sha256"] == subject.digest(checkpoint)
    assert report["recipe_sha256"] == subject.digest(recipe)
    assert all(set(binding) == {"id", "group_id", "split", "source_sha256", "normalized_source_sha256",
        "embedding_sha256", "numeric_embedding_sha256", "target_sha256"}
        for binding in recipe["training_bindings"] + recipe["validation_bindings"])
    assert recipe["group_or_split_metadata_used_as_features"] is False
    assert recipe["automatic_semantic_grouping_performed"] is False
    assert report["proof_authority"] is False and report["includes_embedding_generation"] is False


def test_implementation_changes_during_fit_are_rejected(monkeypatch):
    pin_calls = iter([{"version": 1}, {"version": 2}])
    monkeypatch.setattr(subject, "_pins", lambda: next(pin_calls))
    monkeypatch.setattr(subject.api, "train_structured_source_decoder_384", lambda *a, **k: {})
    with pytest.raises(ValueError, match="implementation changed"):
        subject.train_grouped_source_decoder_384("intent_ir", rows("train"), rows("validation"), parent_projection={})


def test_actual_numerical_fit_preserves_parent_and_reconstructs_tuning():
    torch = pytest.importorskip("torch")
    pytest.importorskip("numpy")
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer import modal_latent_formula as legal
    previous = torch.get_num_threads()
    torch.set_num_threads(1)
    try:
        binding = {"domain": "legal_ir", "lineage_id": "current_legal_v2", "dimension": 384,
            "runtime_profile": "grouped-source-recipe-unit-test/v1", "core_sha256": "a" * 64}
        examples = [{"id": "parent-train", "source_text": "The agency must save the report.",
            "latent": [.5] + [0.] * 383, "embedding": [.3] + [0.] * 383,
            "canonical_ir": {"rules": [{"modality": "O", "actor": "agency", "action": "save", "object": "report",
                "conditions": [], "exceptions": [], "temporal": []}]}}]
        initial = legal.build_checkpoint(binding, examples, [], hidden_size=16,
            token_embedding_dim=8, projection_width=4, batch_size=1)
        parent = legal.train(initial, examples, [], epochs=1, max_seconds=30)["checkpoint"]
        before = deepcopy(parent)
        result = subject.train_grouped_source_decoder_384("intent_ir", rows("train"), rows("validation"),
            parent_projection=parent, config={"ridges": [.001, .01]})
    finally:
        torch.set_num_threads(previous)
    assert parent == before
    assert result["checkpoint"]["schema"] == subject.structured.SCHEMA
    assert result["metrics"]["selected_validation"]["exact_targets"] == 6
    assert result["checkpoint"]["lineage"]["parent_encoder_frozen"] is True
    assert all("group_id" not in row and "split" not in row
        for row in result["checkpoint"]["training_manifest"])
    inputs = [{key: row[key] for key in ("id", "source_text", "embedding")} for row in rows("validation")]
    output = subject.api.infer_structured_source_decoder_384(result["checkpoint"], inputs)
    assert [row["candidate_ir"] for row in output["rows"]] == [row["target"] for row in rows("validation")]
    assert output["proof_authority"] is False
